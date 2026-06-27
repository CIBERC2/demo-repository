"""
protocol.py — Esquema de mensajes del C2 (Aligo Protocol v1).

Cada mensaje sobre el cable tiene la forma:

    {
        "id":        "<uuid v4 único del mensaje>",
        "type":      "<HELLO|HANDSHAKE|HEARTBEAT|TASK|RESULT|ERROR|EVENT|BYE>",
        "agent_id":  "<uuid del agente, vacío en HELLO>",
        "ts":        <epoch float>,
        "payload":   {<contenido en claro o sobre cifrado>},
        "sig":       "<HMAC-SHA256 base64 sobre los demás campos>"
    }

El campo `payload` puede contener un Envelope (ver crypto.py) cuando el
mensaje es post-handshake, o datos en claro para HELLO/HANDSHAKE.
"""

from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "openc2/1.0"


class MessageType(str, Enum):
    HELLO = "HELLO"                # agent -> server, anuncia su existencia + pubkey
    HANDSHAKE = "HANDSHAKE"        # server <-> agent, intercambio de clave de sesión
    HEARTBEAT = "HEARTBEAT"        # agent -> server, latido periódico
    TASK = "TASK"                  # server -> agent, ejecutar algo (publish)
    RESULT = "RESULT"              # agent -> server, salida de una task
    EVENT = "EVENT"                # agent -> server, evento asíncrono (telemetría)
    ERROR = "ERROR"                # cualquier dirección, fallo recuperable
    BYE = "BYE"                    # despedida limpia


class Message(BaseModel):
    """Mensaje base del protocolo. Cifrado/firma se aplican aparte."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType
    agent_id: str = ""
    ts: float = Field(default_factory=lambda: time.time())
    payload: dict[str, Any] = Field(default_factory=dict)
    sig: str = ""

    def to_bytes_for_signature(self) -> bytes:
        """Serialización determinista para firmar/verificar (excluye sig)."""
        data = self.model_dump(exclude={"sig"})
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def to_wire(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_wire(cls, raw: str | bytes) -> "Message":
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return cls.model_validate_json(raw)


# ---------------------------------------------------------------------------
# Payload schemas
# ---------------------------------------------------------------------------

class HelloPayload(BaseModel):
    """El agente se presenta sin sesión todavía."""

    protocol: str = PROTOCOL_VERSION
    hostname: str
    os: str
    arch: str
    user: str
    capabilities: list[str] = Field(default_factory=list)
    agent_pub_pem: str  # PEM del agente para futuro mTLS opcional
    label: str = ""     # etiqueta opcional para múltiples agentes en el mismo host


class HandshakeServerPayload(BaseModel):
    """El servidor responde con su pubkey + agent_id asignado."""

    protocol: str = PROTOCOL_VERSION
    server_pub_pem: str
    agent_id: str
    challenge: str  # nonce a re-firmar por el agente con sesión


class HandshakeAgentPayload(BaseModel):
    """El agente entrega la session_key envuelta + challenge resuelto."""

    wrapped_session_key: str  # base64 del RSA-OAEP(session_key)
    challenge_ack: str        # base64 del HMAC-SHA256(session_key, challenge)


class HeartbeatPayload(BaseModel):
    uptime: float
    cpu: float | None = None
    mem: float | None = None
    plugins: list[str] = Field(default_factory=list)


class TaskPayload(BaseModel):
    """Comando que el operador envía al agente vía servidor."""

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    plugin: str            # nombre del plugin a invocar (e.g. "shell")
    action: str            # acción dentro del plugin
    args: dict[str, Any] = Field(default_factory=dict)
    timeout: float = 30.0


class ResultPayload(BaseModel):
    task_id: str
    ok: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0


class EventPayload(BaseModel):
    name: str
    data: dict[str, Any] = Field(default_factory=dict)


class ErrorPayload(BaseModel):
    code: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
