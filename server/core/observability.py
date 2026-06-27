"""
observability.py — Métricas internas del C2 en tiempo real.

Todos los contadores son thread-safe con asyncio.Lock.
El snapshot() se emite por SSE/WebSocket cada 5 segundos.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any


MAX_ERRORS   = 100
MAX_TIMELINE = 200


class Metrics:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

        self.commands_sent: int      = 0
        self.results_received: int   = 0
        self.agents_connected: int   = 0
        self.agents_dead: int        = 0
        self.channel_switches: int   = 0

        self._response_times: deque[float] = deque(maxlen=100)
        self.avg_response_time_ms: float   = 0.0

        self.errors: deque[dict]   = deque(maxlen=MAX_ERRORS)
        self.timeline: deque[dict] = deque(maxlen=MAX_TIMELINE)

    # ------------------------------------------------------------------
    # Mutators (todos async)
    # ------------------------------------------------------------------

    async def inc_commands_sent(self, agent_id: str = "", detail: str = "") -> None:
        async with self._lock:
            self.commands_sent += 1
            self.timeline.append({
                "ts": time.time(),
                "event": "command_sent",
                "agent_id": agent_id,
                "detail": detail,
            })

    async def inc_results(self, agent_id: str, duration_ms: float, ok: bool, detail: str = "") -> None:
        async with self._lock:
            self.results_received += 1
            self._response_times.append(duration_ms)
            self.avg_response_time_ms = (
                sum(self._response_times) / len(self._response_times)
                if self._response_times else 0.0
            )
            self.timeline.append({
                "ts": time.time(),
                "event": "result_received" if ok else "result_error",
                "agent_id": agent_id,
                "detail": detail or f"{duration_ms:.0f}ms",
            })

    async def agent_online(self, agent_id: str, hostname: str) -> None:
        async with self._lock:
            self.agents_connected += 1
            self.timeline.append({
                "ts": time.time(),
                "event": "agent_online",
                "agent_id": agent_id,
                "detail": hostname,
            })

    async def agent_offline(self, agent_id: str) -> None:
        async with self._lock:
            self.agents_connected = max(0, self.agents_connected - 1)
            self.agents_dead += 1
            self.timeline.append({
                "ts": time.time(),
                "event": "agent_offline",
                "agent_id": agent_id,
                "detail": "",
            })

    async def inc_channel_switch(self, agent_id: str, from_ch: str, to_ch: str) -> None:
        async with self._lock:
            self.channel_switches += 1
            self.timeline.append({
                "ts": time.time(),
                "event": "channel_switch",
                "agent_id": agent_id,
                "detail": f"{from_ch}→{to_ch}",
            })

    async def record_error(self, agent_id: str, error_type: str, detail: str) -> None:
        async with self._lock:
            entry = {
                "ts": time.time(),
                "agent_id": agent_id,
                "error_type": error_type,
                "detail": detail,
            }
            self.errors.append(entry)
            self.timeline.append({
                "ts": time.time(),
                "event": "error",
                "agent_id": agent_id,
                "detail": f"[{error_type}] {detail}",
            })

    # ------------------------------------------------------------------
    # Snapshot serializable
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "commands_sent":        self.commands_sent,
            "results_received":     self.results_received,
            "agents_connected":     self.agents_connected,
            "agents_dead":          self.agents_dead,
            "channel_switches":     self.channel_switches,
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
            "errors":               list(self.errors)[-5:],
            "timeline":             list(self.timeline)[-20:],
        }


# Singleton global
_metrics: Metrics | None = None


def get_metrics() -> Metrics:
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics
