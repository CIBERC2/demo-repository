"""
agent_manager.py — Registro central de agentes + pub/sub interno.

Mantiene el estado de cada agente conectado y expone un broker
publish/subscribe in-memory que reemplaza al polling clásico:

  - Cada agente tiene una cola asyncio de tasks pendientes.
  - El operador publica una task -> se entrega al instante por WebSocket.
  - Los resultados, eventos y heartbeats se emiten a suscriptores
    (dashboard, CLI, otros agentes coordinados).

Diseñado para correr dentro del loop de uvicorn.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Callable

from .protocol import Message, MessageType
from .audit_trail import get_trail
from .observability import get_metrics
from .solana_anchor import anchor_hash as _solana_anchor

_log = logging.getLogger("c2.queue_db")
QUEUE_DB = Path(os.getenv("QUEUE_DB_PATH", "pending_tasks.db"))


@dataclass
class AgentState:
    agent_id: str
    hostname: str = ""
    os: str = ""
    arch: str = ""
    user: str = ""
    label: str = ""    # etiqueta para diferenciar múltiples agentes en el mismo host
    capabilities: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    connected: bool = True
    session_key: bytes | None = None  # AES-256 negociada en handshake
    metrics: dict[str, float] = field(default_factory=dict)

    # cola privada de tasks listas para enviar al socket del agente
    outbox: asyncio.Queue[Message] = field(default_factory=asyncio.Queue)

    @property
    def host_key(self) -> str:
        """Clave única para persistencia: hostname o hostname:label si hay label."""
        return f"{self.hostname}:{self.label}" if self.label else self.hostname

    def public(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "hostname": self.hostname,
            "label": self.label,
            "os": self.os,
            "arch": self.arch,
            "user": self.user,
            "capabilities": self.capabilities,
            "plugins": self.plugins,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "connected": self.connected,
            "metrics": self.metrics,
        }


class PubSub:
    """Broker mínimo asíncrono: múltiples consumidores por tópico."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, topic: str) -> asyncio.Queue:
        async with self._lock:
            q: asyncio.Queue = asyncio.Queue(maxsize=1024)
            self._subscribers.setdefault(topic, set()).add(q)
            return q

    async def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        async with self._lock:
            if topic in self._subscribers:
                self._subscribers[topic].discard(q)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]

    async def publish(self, topic: str, payload: dict) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(topic, ()))
            queues += list(self._subscribers.get("*", ()))
        for q in queues:
            if not q.full():
                q.put_nowait({"topic": topic, "data": payload, "ts": time.time()})

    async def stream(self, topic: str) -> AsyncIterator[dict]:
        q = await self.subscribe(topic)
        try:
            while True:
                msg = await q.get()
                yield msg
        finally:
            await self.unsubscribe(topic, q)


def _init_queue_db() -> None:
    with sqlite3.connect(QUEUE_DB) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pending_tasks "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, hostname TEXT NOT NULL, "
            "task_json TEXT NOT NULL, created_at REAL NOT NULL)"
        )
        conn.commit()


class AgentManager:
    def __init__(self) -> None:
        self._agents: dict[str, AgentState] = {}
        self.pubsub = PubSub()
        self._lock = asyncio.Lock()
        self.on_register: list[Callable[[AgentState], None]] = []
        self.on_disconnect: list[Callable[[AgentState], None]] = []
        _init_queue_db()

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    async def register(
        self,
        hostname: str,
        os_name: str,
        arch: str,
        user: str,
        capabilities: list[str],
        session_key: bytes,
        label: str = "",
    ) -> AgentState:
        async with self._lock:
            agent_id = str(uuid.uuid4())
            state = AgentState(
                agent_id=agent_id,
                hostname=hostname,
                os=os_name,
                arch=arch,
                user=user,
                label=label,
                capabilities=capabilities,
                session_key=session_key,
            )
            self._agents[agent_id] = state

        # Restaurar tareas pendientes persistidas para este host_key
        restored = await asyncio.to_thread(self._load_pending_for_host, state.host_key)
        for raw in restored:
            try:
                msg = Message.from_wire(raw)
                await state.outbox.put(msg)
            except Exception as exc:
                _log.warning("Cola restaurada: mensaje invalido para %s: %s", hostname, exc)
        if restored:
            _log.info("Restauradas %d tareas pendientes para %s", len(restored), state.host_key)

        for cb in self.on_register:
            try:
                cb(state)
            except Exception:
                pass
        await get_metrics().agent_online(state.agent_id, state.hostname)
        await self.pubsub.publish("agents.registered", state.public())
        return state

    async def disconnect(self, agent_id: str) -> None:
        async with self._lock:
            state = self._agents.get(agent_id)
            if not state:
                return
            state.connected = False
            state.last_seen = time.time()
        for cb in self.on_disconnect:
            try:
                cb(state)
            except Exception:
                pass
        await get_metrics().agent_offline(agent_id)
        await self.pubsub.publish("agents.disconnected", state.public())

    def get(self, agent_id: str) -> AgentState | None:
        return self._agents.get(agent_id)

    def all(self) -> list[AgentState]:
        return list(self._agents.values())

    # ------------------------------------------------------------------
    # Tasks (operator -> agent)
    # ------------------------------------------------------------------

    async def enqueue_task(self, agent_id: str, message: Message) -> bool:
        state = self.get(agent_id)
        if not state or not state.connected:
            return False
        await state.outbox.put(message)
        plugin = message.payload.get("plugin", "")
        action = message.payload.get("action", "")
        await get_metrics().inc_commands_sent(agent_id, f"{plugin}.{action}")
        await self.pubsub.publish(
            "agents.task_enqueued",
            {"agent_id": agent_id, "task_id": message.payload.get("task_id"), "type": message.type},
        )
        return True

    async def next_task(self, agent_id: str) -> Message | None:
        state = self.get(agent_id)
        if not state:
            return None
        return await state.outbox.get()

    # ------------------------------------------------------------------
    # Telemetría entrante
    # ------------------------------------------------------------------

    async def handle_heartbeat(self, agent_id: str, payload: dict) -> None:
        state = self.get(agent_id)
        if not state:
            return
        state.last_seen = time.time()
        state.metrics = {
            "cpu": payload.get("cpu") or 0.0,
            "mem": payload.get("mem") or 0.0,
            "uptime": payload.get("uptime") or 0.0,
        }
        state.plugins = payload.get("plugins") or state.plugins
        await self.pubsub.publish("agents.heartbeat", {
            "agent_id": agent_id,
            "metrics": state.metrics,
            "plugins": state.plugins,
        })

    async def handle_result(self, agent_id: str, payload: dict) -> None:
        task_id = payload.get("task_id", "?")
        ok = payload.get("ok", False)
        duration_ms = payload.get("duration_ms", 0.0)
        command_label = f"task:{task_id[:8]}"
        # Audit trail + Solana anchor (fire-and-forget)
        block = get_trail().add_entry(agent_id=agent_id, command=command_label, result=payload)
        asyncio.create_task(_solana_anchor(block.block_hash, block.block_id))
        # Observability
        await get_metrics().inc_results(
            agent_id=agent_id,
            duration_ms=duration_ms,
            ok=ok,
            detail=command_label,
        )
        await self.pubsub.publish("agents.result", {"agent_id": agent_id, **payload})

    async def handle_event(self, agent_id: str, payload: dict) -> None:
        await self.pubsub.publish("agents.event", {"agent_id": agent_id, **payload})

    # ------------------------------------------------------------------
    # SQLite queue persistence
    # ------------------------------------------------------------------

    def _load_pending_for_host(self, hostname: str) -> list[str]:
        """Lee y elimina tareas pendientes de un hostname desde SQLite."""
        try:
            with sqlite3.connect(QUEUE_DB) as conn:
                rows = conn.execute(
                    "SELECT id, task_json FROM pending_tasks WHERE hostname=? ORDER BY id",
                    (hostname,),
                ).fetchall()
                if rows:
                    ids = [r[0] for r in rows]
                    conn.execute(f"DELETE FROM pending_tasks WHERE id IN ({','.join('?'*len(ids))})", ids)
                    conn.commit()
                return [r[1] for r in rows]
        except Exception as exc:
            _log.warning("Error al leer pending_tasks: %s", exc)
            return []

    async def flush_to_db(self) -> int:
        """
        Persiste las tareas pendientes de todos los agentes a SQLite.
        Llamar en SIGTERM para no perder tareas en cola.
        Retorna el numero total de tareas guardadas.
        """
        total = 0
        async with self._lock:
            agents_snapshot = list(self._agents.values())

        rows: list[tuple[str, str, float]] = []
        for state in agents_snapshot:
            while not state.outbox.empty():
                try:
                    msg = state.outbox.get_nowait()
                    rows.append((state.host_key, msg.to_wire(), time.time()))
                    total += 1
                except asyncio.QueueEmpty:
                    break

        if rows:
            try:
                await asyncio.to_thread(self._write_pending_rows, rows)
                _log.info("Persistidas %d tareas pendientes a %s", total, QUEUE_DB)
            except Exception as exc:
                _log.error("Error al persistir cola: %s", exc)
        return total

    def _write_pending_rows(self, rows: list[tuple[str, str, float]]) -> None:
        with sqlite3.connect(QUEUE_DB) as conn:
            conn.executemany(
                "INSERT INTO pending_tasks (hostname, task_json, created_at) VALUES (?,?,?)",
                rows,
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Cleanup periódico
    # ------------------------------------------------------------------

    async def reap_dead(self, ttl_seconds: float = 60.0) -> int:
        now = time.time()
        dead = []
        async with self._lock:
            for aid, state in self._agents.items():
                if state.connected and (now - state.last_seen) > ttl_seconds:
                    dead.append(aid)
        for aid in dead:
            await self.disconnect(aid)
        return len(dead)
