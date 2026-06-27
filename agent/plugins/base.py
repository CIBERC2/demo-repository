"""
plugins/base.py — Interfaz base para todos los plugins del agente.

Cada plugin debe implementar BasePlugin. Los plugins hot-swapped deben
además definir name/version/author y exponer una clase llamada `Plugin`.

Mejora 3: la firma RSA-PSS se verifica en agent.py ANTES de importar.
Si la firma falla, el código nunca se ejecuta.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BasePlugin(ABC):
    # Metadatos obligatorios en plugins hot-swappable
    name: str    = "base"
    version: str = "0.0.0"
    author: str  = "unknown"
    description: str = ""

    @abstractmethod
    async def execute(self, action: str, args: dict[str, Any]) -> Any:
        """Ejecuta una acción y retorna un dict serializable."""

    def actions(self) -> list[str]:
        """Lista de acciones soportadas."""
        return []

    def validate(self) -> bool:
        """Auto-validación antes de ejecutarse. Retorna False para rechazar carga."""
        return bool(self.name and self.version and self.author)

    async def teardown(self) -> None:
        """Limpieza al descargar el plugin."""
