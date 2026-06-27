"""
plugins/opsec.py — Detección de EDR/AV/SIEM, análisis forense de event logs y OPSEC.
Lab / Red Team — ambiente controlado y autorizado.

Acciones:
  edr_check       → Procesos EDR/AV/forense activos en el sistema
  defender_status → Estado real de Windows Defender + amenazas recientes
  event_scan      → Escaneo de Event Logs: Defender, Sysmon, Security
  sysmon_check    → ¿Sysmon activo? ¿Qué captura?
  firewall_check  → Reglas activas, cambios recientes
  sandbox_detect  → ¿Corremos en sandbox/VM/entorno de análisis?
  net_monitor     → Herramientas de captura de red activas
  full_report     → Todas las verificaciones en paralelo + semáforo de riesgo
  watch_start     → Monitoreo continuo en background — alertas automáticas vía SSE
  watch_stop      → Detener monitoreo
"""

from __future__ import annotations

import asyncio
import os
import platform
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from .base import BasePlugin


# ---------------------------------------------------------------------------
# Base de conocimiento — herramientas defensivas conocidas
# ---------------------------------------------------------------------------

EDR_AV_PROCS: dict[str, tuple[str, str]] = {
    # proceso_lower: (producto, categoría)
    # --- EDR corporativos ---
    "csfalconservice.exe":   ("CrowdStrike Falcon",          "EDR"),
    "csagent.exe":           ("CrowdStrike Falcon Agent",    "EDR"),
    "csfalconclient.exe":    ("CrowdStrike Client",          "EDR"),
    "sentinelagent.exe":     ("SentinelOne Agent",           "EDR"),
    "sentinelone.exe":       ("SentinelOne",                 "EDR"),
    "sentinelhelper.exe":    ("SentinelOne Helper",          "EDR"),
    "cbdefense.exe":         ("Carbon Black Defense",        "EDR"),
    "cbcloud.exe":           ("Carbon Black Cloud",          "EDR"),
    "cb.exe":                ("Carbon Black",                "EDR"),
    "cylancesvc.exe":        ("Cylance PROTECT",             "EDR"),
    "hmpalert.exe":          ("HitmanPro Alert",             "EDR"),
    "taniumclient.exe":      ("Tanium Client",               "EDR"),
    "velociraptor.exe":      ("Velociraptor IR",             "EDR"),
    "mbae64.exe":            ("Malwarebytes Anti-Exploit",   "EDR"),
    "tplink.exe":            ("Trend Micro Apex",            "EDR"),
    "coreserviceshell.exe":  ("Trend Micro",                 "EDR"),
    "ds_agent.exe":          ("Deep Security Agent",         "EDR"),
    "xagt.exe":              ("FireEye HX",                  "EDR"),
    "fe_avk.exe":            ("FireEye AV",                  "EDR"),
    # --- Antivirus ---
    "msmpeng.exe":           ("Windows Defender",            "AV"),
    "nissrv.exe":            ("Defender Network Inspection", "AV"),
    "mpcmdrun.exe":          ("Defender CLI",                "AV"),
    "ekrn.exe":              ("ESET NOD32 Kernel",           "AV"),
    "egui.exe":              ("ESET GUI",                    "AV"),
    "avp.exe":               ("Kaspersky AV",                "AV"),
    "kavtray.exe":           ("Kaspersky Tray",              "AV"),
    "mcafeecoretray.exe":    ("McAfee",                      "AV"),
    "mfeann.exe":            ("McAfee ANN",                  "AV"),
    "ccsvchst.exe":          ("Symantec Endpoint",           "AV"),
    "smcgui.exe":            ("Symantec MC",                 "AV"),
    "avgnt.exe":             ("Avira",                       "AV"),
    "avastui.exe":           ("Avast",                       "AV"),
    "mbam.exe":              ("Malwarebytes",                "AV"),
    "sophossps.exe":         ("Sophos SPS",                  "AV"),
    "sav32cli.exe":          ("Sophos AV CLI",               "AV"),
    # --- Monitoreo / SIEM ---
    "sysmon.exe":            ("Sysmon x86",                  "MONITOR"),
    "sysmon64.exe":          ("Sysmon x64",                  "MONITOR"),
    "osqueryd.exe":          ("osquery daemon",              "MONITOR"),
    "wazuh-agent.exe":       ("Wazuh Agent",                 "SIEM"),
    "splunkd.exe":           ("Splunk UF",                   "SIEM"),
    "nxlogd.exe":            ("NXLog",                       "SIEM"),
    "filebeat.exe":          ("Elastic Filebeat",            "SIEM"),
    "winlogbeat.exe":        ("Elastic Winlogbeat",          "SIEM"),
    # --- Forense / Análisis activo ---
    "wireshark.exe":         ("Wireshark",                   "FORENSIC"),
    "dumpcap.exe":           ("Dumpcap (Wireshark)",         "FORENSIC"),
    "tcpview.exe":           ("TCPView (Sysinternals)",      "FORENSIC"),
    "procmon.exe":           ("Process Monitor x86",         "FORENSIC"),
    "procmon64.exe":         ("Process Monitor x64",         "FORENSIC"),
    "processhacker.exe":     ("Process Hacker",              "FORENSIC"),
    "procexp.exe":           ("Process Explorer x86",        "FORENSIC"),
    "procexp64.exe":         ("Process Explorer x64",        "FORENSIC"),
    "autoruns.exe":          ("Autoruns",                    "FORENSIC"),
    "autoruns64.exe":        ("Autoruns x64",                "FORENSIC"),
    "x64dbg.exe":            ("x64dbg Debugger",             "FORENSIC"),
    "ollydbg.exe":           ("OllyDbg",                     "FORENSIC"),
    "windbg.exe":            ("WinDbg",                      "FORENSIC"),
    "ida.exe":               ("IDA Pro x86",                 "FORENSIC"),
    "ida64.exe":             ("IDA Pro x64",                 "FORENSIC"),
    "pestudio.exe":          ("PEstudio",                    "FORENSIC"),
    "fiddler.exe":           ("Fiddler Proxy",               "FORENSIC"),
    "networkminer.exe":      ("NetworkMiner",                "FORENSIC"),
    "regshot.exe":           ("Regshot",                     "FORENSIC"),
    "cutter.exe":            ("Cutter (Rizin)",              "FORENSIC"),
    "ghidra.exe":            ("Ghidra",                      "FORENSIC"),
    "dnspy.exe":             ("dnSpy (.NET)",                "FORENSIC"),
    "hollowshunter.exe":     ("HollowsHunter",               "FORENSIC"),
}

CATEGORY_SEVERITY = {
    "EDR":      "CRITICAL",
    "AV":       "HIGH",
    "MONITOR":  "HIGH",
    "SIEM":     "HIGH",
    "FORENSIC": "CRITICAL",
}

RISK_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "CLEAN": 0}


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class OpsecPlugin(BasePlugin):
    name        = "opsec"
    version     = "1.0.0"
    author      = "aligo-c2"
    description = "Detección OPSEC: EDR/AV, event logs, Sysmon, Defender, sandbox, red"

    def __init__(self) -> None:
        self._watch_task: asyncio.Task | None = None
        self._watch_interval: int = 60
        # Callback inyectado por el agente para enviar alertas proactivas
        self.alert_callback: Callable[[dict], Awaitable[None]] | None = None

    def actions(self) -> list[str]:
        return [
            "edr_check",
            "defender_status",
            "event_scan",
            "sysmon_check",
            "firewall_check",
            "sandbox_detect",
            "net_monitor",
            "full_report",
            "watch_start",
            "watch_stop",
        ]

    async def execute(self, action: str, args: dict[str, Any]) -> Any:
        dispatch = {
            "edr_check":       self._edr_check,
            "defender_status": self._defender_status,
            "event_scan":      self._event_scan,
            "sysmon_check":    self._sysmon_check,
            "firewall_check":  self._firewall_check,
            "sandbox_detect":  self._sandbox_detect,
            "net_monitor":     self._net_monitor,
            "full_report":     self._full_report,
            "watch_start":     self._watch_start,
            "watch_stop":      self._watch_stop,
        }
        fn = dispatch.get(action)
        if fn is None:
            return {"error": f"Unknown action: {action}", "available": self.actions()}
        return await fn(args)

    # ------------------------------------------------------------------
    # edr_check — procesos EDR/AV/SIEM/forense activos
    # ------------------------------------------------------------------

    async def _edr_check(self, args: dict) -> dict:
        all_procs = await self._get_running_procs()
        detected = []

        for proc_name, proc_info in all_procs.items():
            key = proc_name.lower()
            if key in EDR_AV_PROCS:
                product, cat = EDR_AV_PROCS[key]
                detected.append({
                    "process":  proc_name,
                    "pid":      proc_info.get("pid"),
                    "product":  product,
                    "category": cat,
                    "severity": CATEGORY_SEVERITY.get(cat, "MEDIUM"),
                })

        status = (
            "CRITICAL" if any(d["severity"] == "CRITICAL" for d in detected) else
            "HIGH"     if any(d["severity"] == "HIGH"     for d in detected) else
            "CLEAN"
        )
        return {
            "status":        status,
            "detected":      detected,
            "total_found":   len(detected),
            "scanned_procs": len(all_procs),
            "ts":            _now(),
        }

    # ------------------------------------------------------------------
    # defender_status — estado real de Windows Defender
    # ------------------------------------------------------------------

    async def _defender_status(self, args: dict) -> dict:
        if platform.system() != "Windows":
            return {"error": "Solo Windows", "ts": _now()}

        status_raw = await self._ps(
            "Get-MpComputerStatus | Select-Object "
            "AntivirusEnabled,RealTimeProtectionEnabled,BehaviorMonitorEnabled,"
            "IoavProtectionEnabled,AMServiceEnabled,NISEnabled,"
            "AntivirusSignatureAge,AntivirusSignatureVersion,"
            "QuickScanAge,FullScanAge | ConvertTo-Json"
        )

        # Amenazas activas recientes
        threats_raw = await self._ps(
            "Get-MpThreatDetection | Sort-Object InitialDetectionTime -Descending "
            "| Select-Object -First 10 "
            "| Select-Object ThreatID,ProcessName,InitialDetectionTime,"
            "RemediationTime,ActionSuccess | ConvertTo-Json"
        )

        # Historial de amenazas (incluye lo que puso en cuarentena)
        threat_hist = await self._ps(
            "Get-MpThreat | Select-Object -First 10 "
            "| Select-Object ThreatID,ThreatName,SeverityID,IsActive,Resources | ConvertTo-Json"
        )

        status_out = status_raw.get("output", "")
        threats_out = threats_raw.get("output", "")

        # ¿Hay detecciones activas recientes?
        has_active_threats = (
            threats_out not in (None, "null", "[]", "")
            and len(threats_out) > 10
        )

        return {
            "risk":             "CRITICAL" if has_active_threats else "LOW",
            "has_active_threats": has_active_threats,
            "defender_status":  status_out,
            "recent_detections": threats_out,
            "threat_history":   threat_hist.get("output"),
            "ts":               _now(),
        }

    # ------------------------------------------------------------------
    # event_scan — Event Logs con indicadores de detección
    # ------------------------------------------------------------------

    async def _event_scan(self, args: dict) -> dict:
        if platform.system() != "Windows":
            return {"error": "Solo Windows", "ts": _now()}

        hours = int(args.get("hours", 2))

        # Defender Operational — detecciones directas
        defender_ev = await self._ps(
            f"Get-WinEvent -LogName 'Microsoft-Windows-Windows Defender/Operational' "
            f"-MaxEvents 100 -ErrorAction SilentlyContinue "
            f"| Where-Object {{ $_.TimeCreated -gt (Get-Date).AddHours(-{hours}) "
            f"-and $_.Id -in @(1006,1007,1116,1117,1118,1119,5001,5004) }} "
            f"| Select-Object TimeCreated,Id,Message | ConvertTo-Json -Depth 2"
        )

        # Sysmon — actividad de monitoreo (¿cuántos eventos y de qué tipo?)
        sysmon_ev = await self._ps(
            f"Get-WinEvent -LogName 'Microsoft-Windows-Sysmon/Operational' "
            f"-MaxEvents 500 -ErrorAction SilentlyContinue "
            f"| Where-Object {{ $_.TimeCreated -gt (Get-Date).AddHours(-{hours}) }} "
            f"| Group-Object Id | Select-Object @{{N='EventID';E={{$_.Name}}}},Count "
            f"| ConvertTo-Json"
        )

        # Security log — eventos críticos (log borrado, reglas firewall, servicios nuevos)
        security_ev = await self._ps(
            f"Get-WinEvent -LogName 'Security' -MaxEvents 500 -ErrorAction SilentlyContinue "
            f"| Where-Object {{ $_.TimeCreated -gt (Get-Date).AddHours(-{hours}) "
            f"-and $_.Id -in @(1102,4946,4947,4948,7045,4698,4720,4732) }} "
            f"| Select-Object TimeCreated,Id,Message | ConvertTo-Json -Depth 2"
        )

        # System log — servicios y cambios del sistema
        system_ev = await self._ps(
            f"Get-WinEvent -LogName 'System' -MaxEvents 200 -ErrorAction SilentlyContinue "
            f"| Where-Object {{ $_.TimeCreated -gt (Get-Date).AddHours(-{hours}) "
            f"-and $_.Id -in @(7045,7036) }} "
            f"| Select-Object TimeCreated,Id,Message | ConvertTo-Json -Depth 2"
        )

        def_out      = str(defender_ev.get("output") or "")
        security_out = str(security_ev.get("output") or "")
        sysmon_out   = str(sysmon_ev.get("output") or "")

        defender_hit  = any(f'"{x}"' in def_out or f': {x},' in def_out
                            for x in ["1116", "1117", "1006", "1007"])
        audit_cleared = '"1102"' in security_out or ': 1102,' in security_out
        sysmon_active = sysmon_out not in (None, "null", "[]", "", "None")

        risk = (
            "CRITICAL" if defender_hit or audit_cleared else
            "HIGH"     if sysmon_active else
            "LOW"
        )

        return {
            "risk_level":    risk,
            "hours_back":    hours,
            "warnings": {
                "defender_detected": defender_hit,
                "audit_log_cleared": audit_cleared,
                "sysmon_active":     sysmon_active,
            },
            "defender_events": def_out or None,
            "sysmon_activity": sysmon_out or None,
            "security_events": security_out or None,
            "system_events":   system_ev.get("output"),
            "ts": _now(),
        }

    # ------------------------------------------------------------------
    # sysmon_check — ¿Sysmon activo? ¿Qué reglas tiene?
    # ------------------------------------------------------------------

    async def _sysmon_check(self, args: dict) -> dict:
        if platform.system() != "Windows":
            return {"error": "Solo Windows", "ts": _now()}

        svc = await self._ps(
            "Get-Service Sysmon64,Sysmon -ErrorAction SilentlyContinue "
            "| Select-Object Name,Status,StartType | ConvertTo-Json"
        )

        # Leer config actual de Sysmon (muestra qué eventos captura)
        cfg = await self._ps(
            "try { & \"$env:SystemRoot\\Sysmon64.exe\" -c 2>&1 | Out-String } "
            "catch { try { & \"$env:SystemRoot\\Sysmon.exe\" -c 2>&1 | Out-String } "
            "catch { 'Sysmon no encontrado' } }"
        )

        # Últimos 20 eventos capturados
        recent = await self._ps(
            "Get-WinEvent -LogName 'Microsoft-Windows-Sysmon/Operational' "
            "-MaxEvents 20 -ErrorAction SilentlyContinue "
            "| Select-Object TimeCreated,Id,Message | ConvertTo-Json -Depth 2"
        )

        svc_out = str(svc.get("output") or "")
        running = "Running" in svc_out

        return {
            "sysmon_active":  running,
            "risk":           "HIGH" if running else "CLEAN",
            "service_status": svc_out or None,
            "config_rules":   cfg.get("output"),
            "recent_events":  recent.get("output"),
            "recommendation": (
                "Sysmon registra creación de procesos, conexiones, archivos. "
                "Evitar técnicas que generen eventos 1,3,11. Considerar limpiar "
                "logs: wevtutil cl Microsoft-Windows-Sysmon/Operational"
            ) if running else "Sysmon no activo",
            "ts": _now(),
        }

    # ------------------------------------------------------------------
    # firewall_check — estado del firewall, reglas de bloqueo
    # ------------------------------------------------------------------

    async def _firewall_check(self, args: dict) -> dict:
        if platform.system() != "Windows":
            r = await self._cmd("iptables -L -n -v 2>/dev/null || nft list ruleset 2>/dev/null")
            return {"firewall_rules": r.get("stdout"), "ts": _now()}

        # Reglas BLOCK activas — ¿nos bloquearon?
        block = await self._ps(
            "Get-NetFirewallRule "
            "| Where-Object { $_.Action -eq 'Block' -and $_.Enabled -eq 'True' } "
            "| Select-Object DisplayName,Direction,Profile,Action "
            "| ConvertTo-Json"
        )

        # Cambios recientes en reglas (últimas 4h)
        changes = await self._ps(
            "Get-WinEvent -LogName 'Security' -MaxEvents 200 -ErrorAction SilentlyContinue "
            "| Where-Object { $_.Id -in @(4946,4947,4948) "
            "-and $_.TimeCreated -gt (Get-Date).AddHours(-4) } "
            "| Select-Object TimeCreated,Id,Message | ConvertTo-Json -Depth 2"
        )

        # Perfil del firewall (Domain/Private/Public habilitados?)
        profile = await self._ps(
            "Get-NetFirewallProfile "
            "| Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction "
            "| ConvertTo-Json"
        )

        changes_out  = str(changes.get("output") or "")
        recent_rules = changes_out not in (None, "null", "[]", "", "None")

        return {
            "risk":            "HIGH" if recent_rules else "LOW",
            "block_rules":     block.get("output"),
            "recent_changes":  changes_out or None,
            "profile":         profile.get("output"),
            "warning":         "Reglas de firewall modificadas recientemente — posible respuesta a incidente" if recent_rules else None,
            "ts":              _now(),
        }

    # ------------------------------------------------------------------
    # sandbox_detect — VM / sandbox / entorno de análisis
    # ------------------------------------------------------------------

    async def _sandbox_detect(self, args: dict) -> dict:
        indicators: list[dict] = []
        is_windows = platform.system() == "Windows"

        # Usuario típico de sandbox
        sandbox_users = {
            "sandbox", "malware", "virus", "test", "analysis", "user",
            "admin", "john", "alice", "bob", "sample", "honey", "cuckoo",
        }
        current_user = (os.getenv("USERNAME") or os.getenv("USER") or "").lower()
        if current_user in sandbox_users:
            indicators.append({
                "check": "username", "value": current_user,
                "risk": "HIGH", "detail": "Usuario típico de sandbox/análisis",
            })

        if is_windows:
            # Procesos de VM
            vm_procs = await self._ps(
                "Get-Process -ErrorAction SilentlyContinue "
                "| Where-Object { $_.ProcessName -in @("
                "'vboxservice','vboxtray','vmtoolsd','vmwaretray','vmwareuser',"
                "'vmsrvc','vmusrvc','prl_tools','prl_cc','xenservice','qemu-ga',"
                "'joeboxserver','joeboxcontrol') } "
                "| Select-Object ProcessName,Id | ConvertTo-Json"
            )
            vm_out = str(vm_procs.get("output") or "")
            if vm_out not in (None, "null", "[]", "", "None"):
                indicators.append({
                    "check": "vm_processes", "value": vm_out[:300],
                    "risk": "HIGH", "detail": "Procesos de VM/sandbox activos",
                })

            # BIOS strings
            bios = await self._ps(
                "Get-WmiObject Win32_BIOS -ErrorAction SilentlyContinue "
                "| Select-Object Manufacturer,Version,SerialNumber | ConvertTo-Json"
            )
            bios_out = str(bios.get("output") or "").lower()
            for v in ["vmware", "virtualbox", "vbox", "qemu", "xen", "innotek", "bochs"]:
                if v in bios_out:
                    indicators.append({
                        "check": "bios_vm_strings", "value": v,
                        "risk": "HIGH", "detail": f"String de VM en BIOS: {v}",
                    })
                    break

            # RAM total
            ram_r = await self._ps(
                "[Math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)"
            )
            try:
                ram_gb = float(str(ram_r.get("output") or "8").strip())
                if ram_gb < 2:
                    indicators.append({
                        "check": "low_ram", "value": f"{ram_gb}GB",
                        "risk": "MEDIUM", "detail": "RAM < 2GB — típico de sandbox",
                    })
            except (ValueError, TypeError):
                pass

            # CPU count
            cpu_r = await self._ps(
                "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors"
            )
            try:
                cpus = int(str(cpu_r.get("output") or "4").strip())
                if cpus <= 1:
                    indicators.append({
                        "check": "single_cpu", "value": str(cpus),
                        "risk": "MEDIUM", "detail": "CPU único — típico de sandbox",
                    })
            except (ValueError, TypeError):
                pass

            # Uptime bajo (sistema recién iniciado para análisis)
            up_r = await self._ps(
                "((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalMinutes"
            )
            try:
                mins = float(str(up_r.get("output") or "9999").strip())
                if mins < 5:
                    indicators.append({
                        "check": "very_low_uptime", "value": f"{mins:.1f}min",
                        "risk": "HIGH", "detail": "Sistema iniciado hace < 5min — posible análisis",
                    })
            except (ValueError, TypeError):
                pass

            # Pantalla sin usuario interactivo
            screen_r = await self._ps(
                "(Get-Process -Name explorer -ErrorAction SilentlyContinue) -ne $null"
            )
            if str(screen_r.get("output") or "").strip() == "False":
                indicators.append({
                    "check": "no_explorer", "value": "explorer.exe not running",
                    "risk": "MEDIUM", "detail": "Sin sesión de escritorio activa",
                })

        # Rutas típicas de sandbox
        sandbox_paths = [
            r"C:\cuckoo", r"C:\analysis", r"C:\sandbox", r"C:\iDEFENSE",
            r"C:\joe sandbox", "/tmp/cuckoo", "/opt/cuckoo",
        ]
        for sp in sandbox_paths:
            if os.path.exists(sp):
                indicators.append({
                    "check": "sandbox_path", "value": sp,
                    "risk": "HIGH", "detail": "Directorio típico de sandbox",
                })

        risk = (
            "HIGH"   if any(i["risk"] == "HIGH"   for i in indicators) else
            "MEDIUM" if any(i["risk"] == "MEDIUM" for i in indicators) else
            "CLEAN"
        )
        return {
            "in_sandbox":      risk != "CLEAN",
            "risk":            risk,
            "indicators":      indicators,
            "indicator_count": len(indicators),
            "ts":              _now(),
        }

    # ------------------------------------------------------------------
    # net_monitor — captura de red y proxies activos
    # ------------------------------------------------------------------

    async def _net_monitor(self, args: dict) -> dict:
        all_procs = await self._get_running_procs()
        net_tools: list[dict] = []

        net_tool_db = {
            "wireshark.exe":    ("Wireshark",              "CRITICAL"),
            "dumpcap.exe":      ("Dumpcap (Wireshark BE)", "CRITICAL"),
            "tcpview.exe":      ("TCPView Sysinternals",   "CRITICAL"),
            "fiddler.exe":      ("Fiddler HTTPS Proxy",    "CRITICAL"),
            "fiddler4.exe":     ("Fiddler 4",              "CRITICAL"),
            "charles.exe":      ("Charles Proxy",          "CRITICAL"),
            "mitmproxy.exe":    ("mitmproxy",              "CRITICAL"),
            "mitmdump.exe":     ("mitmdump",               "CRITICAL"),
            "burpsuite.exe":    ("Burp Suite",             "CRITICAL"),
            "networkminer.exe": ("NetworkMiner",           "CRITICAL"),
            "tcpdump.exe":      ("tcpdump Windows",        "CRITICAL"),
            "rawcap.exe":       ("RawCap",                 "HIGH"),
            "microsoft network monitor.exe": ("MS Network Monitor", "HIGH"),
        }

        for proc_name in all_procs:
            key = proc_name.lower()
            if key in net_tool_db:
                label, sev = net_tool_db[key]
                net_tools.append({
                    "process":  proc_name,
                    "pid":      all_procs[proc_name].get("pid"),
                    "tool":     label,
                    "severity": sev,
                })

        # Interfaces en modo promiscuo (sniffing pasivo)
        promisc_info = None
        if platform.system() == "Windows":
            promisc_r = await self._ps(
                "Get-NetAdapter -ErrorAction SilentlyContinue "
                "| Where-Object { $_.PromiscuousMode -eq $true } "
                "| Select-Object Name,InterfaceDescription | ConvertTo-Json"
            )
            promisc_out = str(promisc_r.get("output") or "")
            if promisc_out not in (None, "null", "[]", "", "None"):
                promisc_info = promisc_out
                net_tools.append({
                    "check":    "promiscuous_interface",
                    "value":    promisc_out[:300],
                    "severity": "CRITICAL",
                    "detail":   "Interfaz en modo promiscuo — sniffing activo",
                })

        risk = "CRITICAL" if net_tools else "CLEAN"
        return {
            "risk":             risk,
            "tools_active":     net_tools,
            "tools_count":      len(net_tools),
            "promiscuous_iface": promisc_info,
            "ts":               _now(),
        }

    # ------------------------------------------------------------------
    # full_report — reporte OPSEC completo con semáforo
    # ------------------------------------------------------------------

    async def _full_report(self, args: dict) -> dict:
        hours = int(args.get("hours", 2))

        checks = await asyncio.gather(
            self._edr_check({}),
            self._defender_status({}),
            self._event_scan({"hours": hours}),
            self._sysmon_check({}),
            self._firewall_check({}),
            self._sandbox_detect({}),
            self._net_monitor({}),
            return_exceptions=True,
        )
        labels = ["edr", "defender", "events", "sysmon", "firewall", "sandbox", "net_monitor"]

        report: dict[str, Any] = {}
        max_score = 0

        for label, res in zip(labels, checks):
            if isinstance(res, Exception):
                report[label] = {"error": str(res), "risk": "UNKNOWN"}
            else:
                report[label] = res
                # Extraer campo de riesgo (cada sub-check usa una clave distinta)
                risk_val = (
                    res.get("risk") or res.get("risk_level") or
                    res.get("status") or "CLEAN"
                )
                max_score = max(max_score, RISK_ORDER.get(risk_val, 0))

        rev = {v: k for k, v in RISK_ORDER.items()}
        overall = rev.get(max_score, "CLEAN")

        # Recomendaciones accionables
        recs: list[str] = []
        edr = report.get("edr", {})
        if edr.get("total_found", 0) > 0:
            prods = [d["product"] for d in edr.get("detected", [])]
            recs.append(f"EDR/AV ACTIVO: {', '.join(prods)} — evitar shellcode, inyección de proceso, binarios sin firmar")

        if report.get("sysmon", {}).get("sysmon_active"):
            recs.append("SYSMON ACTIVO — registra PID, conexiones, archivos. Considera: wevtutil cl Microsoft-Windows-Sysmon/Operational")

        ev = report.get("events", {})
        if ev.get("warnings", {}).get("defender_detected"):
            recs.append("DEFENDER DETECTÓ AMENAZA — payload comprometido. Rotar herramientas y eliminar artefactos")
        if ev.get("warnings", {}).get("audit_log_cleared"):
            recs.append("AUDIT LOG BORRADO (EventID 1102) — posible investigación IR activa")

        if report.get("sandbox", {}).get("in_sandbox"):
            n = report["sandbox"].get("indicator_count", 0)
            recs.append(f"SANDBOX/VM DETECTADO ({n} indicadores) — tu muestra puede estar siendo analizada")

        nm = report.get("net_monitor", {})
        if nm.get("tools_count", 0) > 0:
            tools = [t.get("tool", "?") for t in nm.get("tools_active", [])]
            recs.append(f"CAPTURA DE RED: {', '.join(tools)} — tu tráfico C2 puede estar siendo capturado")

        fw = report.get("firewall", {})
        if fw.get("risk") == "HIGH":
            recs.append("FIREWALL MODIFICADO recientemente — posible bloqueo de tu canal C2")

        if not recs:
            recs.append("Sin indicadores de detección en este momento")

        return {
            "overall_risk":    overall,
            "scan_time":       _now(),
            "hours_analyzed":  hours,
            "recommendations": recs,
            "details":         report,
        }

    # ------------------------------------------------------------------
    # watch — monitoreo continuo en background
    # ------------------------------------------------------------------

    async def _watch_start(self, args: dict) -> dict:
        interval = int(args.get("interval_seconds", 60))
        if self._watch_task and not self._watch_task.done():
            return {"status": "already_running", "interval_seconds": self._watch_interval}
        self._watch_interval = interval
        self._watch_task = asyncio.create_task(self._watch_loop())
        return {
            "status":           "started",
            "interval_seconds": interval,
            "message":          f"Monitoreo OPSEC activo cada {interval}s — alertas automáticas via SSE",
        }

    async def _watch_stop(self, args: dict) -> dict:
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()
            return {"status": "stopped"}
        return {"status": "not_running"}

    async def _watch_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._watch_interval)
                report = await self._full_report({})
                overall = report.get("overall_risk", "CLEAN")

                # Solo alertar si hay riesgo real
                if overall in ("HIGH", "CRITICAL") and self.alert_callback:
                    await self.alert_callback({
                        "type":            "opsec_alert",
                        "risk":            overall,
                        "recommendations": report.get("recommendations", []),
                        "scan_time":       report.get("scan_time"),
                    })
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def teardown(self) -> None:
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_running_procs(self) -> dict[str, dict]:
        try:
            import psutil
            return {
                p.info["name"]: {"pid": p.info["pid"]}
                for p in psutil.process_iter(["name", "pid"])
                if p.info.get("name")
            }
        except ImportError:
            pass
        if platform.system() == "Windows":
            r = await self._cmd("tasklist /FO CSV /NH")
            procs: dict[str, dict] = {}
            for line in r.get("stdout", "").splitlines():
                parts = line.replace('"', "").split(",")
                if parts:
                    procs[parts[0]] = {"pid": parts[1] if len(parts) > 1 else "?"}
            return procs
        r = await self._cmd("ps -eo pid,comm --no-headers 2>/dev/null")
        procs = {}
        for line in r.get("stdout", "").splitlines():
            p = line.strip().split(None, 1)
            if len(p) == 2:
                procs[p[1]] = {"pid": p[0]}
        return procs

    async def _ps(self, cmd: str, timeout: float = 20.0) -> dict:
        """Ejecuta PowerShell con NonInteractive + Bypass."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-NonInteractive", "-NoProfile",
                "-ExecutionPolicy", "Bypass", "-Command", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "output": stdout.decode("utf-8", errors="replace").strip() or None,
                "error":  stderr.decode("utf-8", errors="replace").strip() or None,
                "rc":     proc.returncode,
            }
        except asyncio.TimeoutError:
            return {"output": None, "error": f"Timeout {timeout}s", "rc": -1}
        except Exception as exc:
            return {"output": None, "error": str(exc), "rc": -1}

    async def _cmd(self, cmd: str, timeout: float = 10.0) -> dict:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "rc":     proc.returncode,
            }
        except asyncio.TimeoutError:
            return {"stdout": "", "stderr": f"Timeout {timeout}s", "rc": -1}
        except Exception as exc:
            return {"stdout": "", "stderr": str(exc), "rc": -1}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
