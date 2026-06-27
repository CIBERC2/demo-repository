"""
plugins/sysinfo.py — Información del sistema del agente.
"""

from __future__ import annotations

import os
import platform
import socket
import time
from typing import Any

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from .base import BasePlugin


class SysInfoPlugin(BasePlugin):
    name = "sysinfo"
    description = "Recopila información del sistema del agente"

    def actions(self) -> list[str]:
        return ["summary", "processes", "network", "env"]

    async def execute(self, action: str, args: dict[str, Any]) -> Any:
        if action == "summary":
            return self._summary()
        if action == "processes":
            return self._processes(limit=args.get("limit", 20))
        if action == "network":
            return self._network()
        if action == "env":
            return dict(os.environ)
        return {"error": f"Unknown action: {action}"}

    def _summary(self) -> dict:
        info = {
            "hostname": socket.gethostname(),
            "os": platform.system(),
            "os_version": platform.version(),
            "arch": platform.machine(),
            "python": platform.python_version(),
            "user": os.getenv("USERNAME") or os.getenv("USER") or "unknown",
            "cwd": os.getcwd(),
            "pid": os.getpid(),
            "time": time.time(),
        }
        if HAS_PSUTIL:
            info["cpu_count"] = psutil.cpu_count()
            info["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            info["mem_total_gb"] = round(mem.total / 1e9, 2)
            info["mem_used_pct"] = mem.percent
            info["boot_time"] = psutil.boot_time()
        return info

    def _processes(self, limit: int = 20) -> list[dict]:
        if not HAS_PSUTIL:
            return [{"error": "psutil not available"}]
        procs = []
        for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x.get("cpu_percent") or 0, reverse=True)
        return procs[:limit]

    def _network(self) -> dict:
        if not HAS_PSUTIL:
            return {"error": "psutil not available"}
        conns = []
        try:
            for c in psutil.net_connections(kind="inet"):
                conns.append({
                    "fd": c.fd,
                    "laddr": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "",
                    "raddr": f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "",
                    "status": c.status,
                    "pid": c.pid,
                })
        except Exception as exc:
            conns = [{"error": str(exc)}]
        ifaces = {}
        for name, addrs in psutil.net_if_addrs().items():
            ifaces[name] = [{"family": str(a.family), "address": a.address} for a in addrs]
        return {"connections": conns, "interfaces": ifaces}
