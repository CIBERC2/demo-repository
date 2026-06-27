"""
audit_trail.py — Registro inmutable de comandos ejecutados (blockchain ligero).

Cada bloque encadena el hash SHA-256 del bloque anterior:
    block_hash = SHA256(block_id || timestamp || agent_id || command || result_hash || prev_hash)

El bloque génesis tiene prev_hash = "0" * 64.
Persistencia: audit_trail.jsonl (append-only, una línea JSON por bloque).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


AUDIT_FILE = Path(os.getenv("AUDIT_FILE", "audit_trail.jsonl"))


@dataclass
class AuditBlock:
    block_id: int
    timestamp: float
    agent_id: str
    command: str            # "plugin.action" o descripción corta
    result_hash: str        # SHA-256 del resultado serializado
    prev_hash: str
    block_hash: str = ""

    def _compute_hash(self) -> str:
        raw = (
            f"{self.block_id}"
            f"{self.timestamp:.6f}"
            f"{self.agent_id}"
            f"{self.command}"
            f"{self.result_hash}"
            f"{self.prev_hash}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def finalize(self) -> "AuditBlock":
        self.block_hash = self._compute_hash()
        return self

    def is_valid(self) -> bool:
        return self._compute_hash() == self.block_hash

    def to_dict(self) -> dict:
        return asdict(self)


def _hash_result(result: object) -> str:
    serialized = json.dumps(result, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


class AuditTrail:
    def __init__(self, path: Path = AUDIT_FILE) -> None:
        self.path = path
        self._chain: list[AuditBlock] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            # Crear bloque génesis
            genesis = AuditBlock(
                block_id=0,
                timestamp=time.time(),
                agent_id="SYSTEM",
                command="GENESIS",
                result_hash="0" * 64,
                prev_hash="0" * 64,
            ).finalize()
            self._chain = [genesis]
            self._append_to_file(genesis)
            return

        self._chain = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                self._chain.append(AuditBlock(**data))

    def _append_to_file(self, block: AuditBlock) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(block.to_dict()) + "\n")

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def add_entry(
        self,
        agent_id: str,
        command: str,
        result: object,
    ) -> AuditBlock:
        prev = self._chain[-1]
        block = AuditBlock(
            block_id=len(self._chain),
            timestamp=time.time(),
            agent_id=agent_id,
            command=command,
            result_hash=_hash_result(result),
            prev_hash=prev.block_hash,
        ).finalize()
        self._chain.append(block)
        self._append_to_file(block)
        return block

    def verify_chain(self) -> dict:
        """
        Recorre toda la cadena y verifica integridad.
        Retorna: {"valid": bool, "total": int, "corrupt": list[int]}
        """
        corrupt: list[int] = []
        for i, block in enumerate(self._chain):
            if not block.is_valid():
                corrupt.append(block.block_id)
                continue
            if i > 0:
                prev = self._chain[i - 1]
                if block.prev_hash != prev.block_hash:
                    corrupt.append(block.block_id)

        return {
            "valid": len(corrupt) == 0,
            "total": len(self._chain),
            "corrupt_blocks": corrupt,
        }

    def get_block(self, n: int) -> Optional[AuditBlock]:
        for b in self._chain:
            if b.block_id == n:
                return b
        return None

    def last(self, n: int = 50) -> list[AuditBlock]:
        return self._chain[-n:]

    def export_json(self) -> list[dict]:
        return [b.to_dict() for b in self._chain]

    def __len__(self) -> int:
        return len(self._chain)


# Singleton global — importar desde cualquier módulo del servidor
_trail: Optional[AuditTrail] = None


def get_trail() -> AuditTrail:
    global _trail
    if _trail is None:
        _trail = AuditTrail()
    return _trail
