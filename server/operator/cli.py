"""
operator/cli.py — Interfaz del operador C2 con Rich + Typer.

Comandos principales:
  agents list                 — listar agentes activos
  agents info <id>            — detalles de un agente
  task exec <agent> <plugin> <action> [args JSON]
  task shell <agent> <cmd>    — atajo para shell.exec
  stream                      — SSE en tiempo real en la terminal
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_server_root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _server_root)

app = typer.Typer(
    name="aligo",
    help="C2 Aligo — Interfaz del Operador",
    no_args_is_help=True,
    add_completion=False,
)
agents_app = typer.Typer(help="Gestión de agentes", no_args_is_help=True)
task_app = typer.Typer(help="Enviar tasks a agentes", no_args_is_help=True)
app.add_typer(agents_app, name="agents")
app.add_typer(task_app, name="task")

console = Console()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _base_url() -> str:
    return os.getenv("C2_URL", "http://localhost:8000")


def _headers() -> dict:
    return {
        "X-Operator-Token": os.getenv("OPERATOR_TOKEN", "openc2-dev-token"),
        "Content-Type": "application/json",
    }


def _http_get(path: str) -> dict | list:
    import urllib.request
    url = _base_url() + path
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as exc:
        console.print(f"[red]Error conectando al servidor:[/red] {exc}")
        raise typer.Exit(1)


def _http_post(path: str, body: dict) -> dict:
    import urllib.request
    url = _base_url() + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as exc:
        console.print(f"[red]Error en POST:[/red] {exc}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# agents commands
# ---------------------------------------------------------------------------

@agents_app.command("list")
def agents_list():
    """Lista todos los agentes registrados."""
    agents = _http_get("/api/agents")
    if not agents:
        console.print("[yellow]No hay agentes conectados.[/yellow]")
        return

    table = Table(title="Agentes C2 Aligo", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=36)
    table.add_column("Hostname")
    table.add_column("OS")
    table.add_column("User")
    table.add_column("Plugins")
    table.add_column("CPU%")
    table.add_column("Mem%")
    table.add_column("Estado")

    for a in agents:
        estado = "[green]● LIVE[/green]" if a["connected"] else "[red]○ OFF[/red]"
        metrics = a.get("metrics", {})
        table.add_row(
            a["agent_id"][:8] + "…",
            a["hostname"],
            a["os"],
            a["user"],
            ", ".join(a.get("plugins") or a.get("capabilities") or []),
            f"{metrics.get('cpu', 0):.1f}",
            f"{metrics.get('mem', 0):.1f}",
            estado,
        )
    console.print(table)


@agents_app.command("info")
def agents_info(agent_id: str):
    """Detalles completos de un agente."""
    # Permite prefijo corto (primeros 8 chars)
    all_agents = _http_get("/api/agents")
    match = [a for a in all_agents if a["agent_id"].startswith(agent_id)]
    if not match:
        console.print(f"[red]Agente no encontrado:[/red] {agent_id}")
        raise typer.Exit(1)
    a = match[0]
    panel_content = json.dumps(a, indent=2, default=str)
    console.print(Panel(panel_content, title=f"Agente [cyan]{a['agent_id'][:12]}[/cyan]", expand=False))


# ---------------------------------------------------------------------------
# task commands
# ---------------------------------------------------------------------------

@task_app.command("exec")
def task_exec(
    agent_id: str,
    plugin: str,
    action: str,
    args: Optional[str] = typer.Argument(None, help="JSON de argumentos"),
    timeout: float = 30.0,
):
    """Envía una task a un agente y espera el resultado."""
    all_agents = _http_get("/api/agents")
    match = [a for a in all_agents if a["agent_id"].startswith(agent_id)]
    if not match:
        console.print(f"[red]Agente no encontrado:[/red] {agent_id}")
        raise typer.Exit(1)
    full_id = match[0]["agent_id"]

    body = {
        "plugin": plugin,
        "action": action,
        "args": json.loads(args) if args else {},
        "timeout": timeout,
    }
    with console.status(f"Enviando task [cyan]{plugin}.{action}[/cyan] a [green]{full_id[:8]}[/green]…"):
        resp = _http_post(f"/api/agents/{full_id}/task", body)
    task_id = resp.get("task_id", "?")
    console.print(f"[green]✓ Task encolada:[/green] {task_id}")
    console.print("[dim]El resultado llegará al stream SSE del operador.[/dim]")


@task_app.command("shell")
def task_shell(agent_id: str, cmd: str, timeout: float = 15.0):
    """Atajo: ejecuta un comando shell en el agente."""
    all_agents = _http_get("/api/agents")
    match = [a for a in all_agents if a["agent_id"].startswith(agent_id)]
    if not match:
        console.print(f"[red]Agente no encontrado:[/red] {agent_id}")
        raise typer.Exit(1)
    full_id = match[0]["agent_id"]

    body = {"plugin": "shell", "action": "exec", "args": {"cmd": cmd}, "timeout": timeout}
    resp = _http_post(f"/api/agents/{full_id}/task", body)
    console.print(f"[green]✓ Shell task:[/green] {resp.get('task_id')}")


# ---------------------------------------------------------------------------
# stream — SSE en terminal
# ---------------------------------------------------------------------------

@app.command("stream")
def stream():
    """SSE en tiempo real: heartbeats, resultados, eventos."""
    import urllib.request
    url = _base_url() + "/api/stream"
    req = urllib.request.Request(url, headers=_headers())
    console.print("[cyan]Conectado al stream C2 Aligo. Ctrl+C para salir.[/cyan]\n")
    try:
        with urllib.request.urlopen(req, timeout=None) as r:
            for line in r:
                line = line.decode("utf-8").strip()
                if not line or line.startswith(":"):
                    continue
                if line.startswith("data: "):
                    raw = line[6:]
                    try:
                        ev = json.loads(raw)
                        topic = ev.get("topic", "")
                        data = ev.get("data", {})
                        ts = time.strftime("%H:%M:%S", time.localtime(ev.get("ts", time.time())))
                        if "heartbeat" in topic:
                            aid = data.get("agent_id", "?")[:8]
                            m = data.get("metrics", {})
                            console.print(
                                f"[dim]{ts}[/dim] [blue]HB[/blue] {aid} "
                                f"cpu={m.get('cpu',0):.1f}% mem={m.get('mem',0):.1f}%"
                            )
                        elif "result" in topic:
                            aid = data.get("agent_id", "?")[:8]
                            ok = data.get("ok", False)
                            tag = "[green]OK[/green]" if ok else "[red]ERR[/red]"
                            console.print(f"[dim]{ts}[/dim] {tag} [{aid}] task={data.get('task_id','?')[:8]}")
                            out = data.get("output")
                            if out and isinstance(out, dict):
                                stdout = out.get("stdout", "")
                                if stdout:
                                    console.print(Panel(stdout.strip(), title="stdout", style="dim"))
                        elif "registered" in topic:
                            aid = data.get("agent_id", "?")[:8]
                            console.print(f"[dim]{ts}[/dim] [green]AGENT ONLINE[/green] {aid} @ {data.get('hostname')}")
                        elif "disconnected" in topic:
                            aid = data.get("agent_id", "?")[:8]
                            console.print(f"[dim]{ts}[/dim] [red]AGENT OFFLINE[/red] {aid}")
                        else:
                            console.print(f"[dim]{ts}[/dim] [{topic}] {json.dumps(data)[:100]}")
                    except json.JSONDecodeError:
                        console.print(f"[dim]{raw}[/dim]")
    except KeyboardInterrupt:
        console.print("\n[yellow]Stream cerrado.[/yellow]")


@app.command("audit")
def audit(limit: int = typer.Option(20, help="Últimos N bloques")):
    """Muestra el audit trail con verificación de cadena de hashes."""
    resp = _http_get(f"/audit?limit={limit}")
    integrity = resp.get("integrity", {})
    blocks = resp.get("blocks", [])

    status_color = "green" if integrity.get("valid") else "red"
    status_icon = "✓" if integrity.get("valid") else "✗"
    console.print(
        f"\n[bold {status_color}]{status_icon} Cadena de hashes:[/bold {status_color}] "
        f"{'ÍNTEGRA' if integrity.get('valid') else 'COMPROMETIDA'} · "
        f"{integrity.get('total', 0)} bloques · "
        f"Corruptos: {integrity.get('corrupt_blocks', [])}\n"
    )

    table = Table(title="Audit Trail — C2 Aligo", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Timestamp", width=19)
    table.add_column("Agent ID", width=10)
    table.add_column("Comando", width=22)
    table.add_column("Hash (12)", width=13)
    table.add_column("Estado")

    corrupt_ids = set(integrity.get("corrupt_blocks", []))
    for b in blocks:
        bid = b["block_id"]
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(b["timestamp"]))
        aid = b["agent_id"][:8] + "…" if len(b["agent_id"]) > 8 else b["agent_id"]
        cmd = b["command"][:22]
        bhash = b["block_hash"][:12]
        ok = bid not in corrupt_ids and bid != 0
        estado = "[green]✓[/green]" if ok else ("[dim]genesis[/dim]" if bid == 0 else "[red]✗ CORRUPT[/red]")
        table.add_row(str(bid), ts, aid, cmd, bhash, estado)

    console.print(table)


@app.command("plugin-load")
def plugin_load(
    plugin_file: str = typer.Argument(..., help="Ruta al archivo .py del plugin"),
    agent_id: str    = typer.Argument(..., help="Agent ID o prefijo"),
):
    """
    Firma y carga un plugin en un agente remoto (hot-swap con firma RSA-PSS).
    """
    plugin_path = Path(plugin_file)
    if not plugin_path.exists():
        console.print(f"[red]Archivo no encontrado:[/red] {plugin_file}")
        raise typer.Exit(1)

    # Cargar clave privada del servidor para firmar
    try:
        from core import crypto as srv_crypto
        from dotenv import load_dotenv
        load_dotenv()
        priv_path = Path(os.getenv("SERVER_PRIVATE_KEY_PATH", "keys/server_priv.pem"))
        pub_path  = Path(os.getenv("SERVER_PUBLIC_KEY_PATH",  "keys/server_pub.pem"))
        server_priv = srv_crypto.load_or_create_keypair(priv_path, pub_path)
    except Exception as exc:
        console.print(f"[red]Error cargando clave del servidor:[/red] {exc}")
        raise typer.Exit(1)

    code_bytes    = plugin_path.read_bytes()
    code_b64      = base64.b64encode(code_bytes).decode("ascii")
    plugin_sig    = srv_crypto.sign_plugin(server_priv, code_bytes)
    plugin_name   = plugin_path.stem

    # Buscar agente
    all_agents = _http_get("/api/agents")
    match = [a for a in all_agents if a["agent_id"].startswith(agent_id)]
    if not match:
        console.print(f"[red]Agente no encontrado:[/red] {agent_id}")
        raise typer.Exit(1)
    full_id = match[0]["agent_id"]

    body = {
        "plugin": "__load__",
        "action": "load",
        "args": {
            "name":             plugin_name,
            "code_b64":         code_b64,
            "plugin_signature": plugin_sig,
        },
        "timeout": 30.0,
    }
    with console.status(f"Firmando y enviando plugin [cyan]{plugin_name}[/cyan] → [green]{full_id[:8]}[/green]…"):
        resp = _http_post(f"/api/agents/{full_id}/task", body)

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Plugin")
    table.add_column("Agente")
    table.add_column("Task ID")
    table.add_column("Estado")
    table.add_row(
        plugin_name,
        full_id[:8] + "…",
        resp.get("task_id", "?")[:12],
        "[green]encolado — ver stream para resultado[/green]",
    )
    console.print(table)
    console.print("[dim]El resultado (cargado / firma inválida / error) aparecerá en el stream SSE.[/dim]")


@app.command("opsec")
def opsec_check(
    agent_id: Optional[str] = typer.Argument(None, help="Agent ID o prefijo (auto-detecta si omites)"),
    hours: int = typer.Option(2, help="Horas de logs a escanear"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Monitoreo continuo cada 30s"),
):
    """
    Chequeo OPSEC — ¿te están mirando durante el pentest?

    Escanea: EDR/AV, Sysmon, Defender, Event Logs, captura de red, sandbox.
    Muestra semáforo de riesgo y recomendaciones accionables.
    """
    import threading
    import urllib.request

    # Encontrar agente conectado
    all_agents = _http_get("/api/agents")
    live = [a for a in all_agents if a["connected"]]
    if not live:
        console.print("[red]No hay agentes conectados.[/red]")
        raise typer.Exit(1)

    if agent_id:
        match = [a for a in live if a["agent_id"].startswith(agent_id)]
        if not match:
            console.print(f"[red]Agente no encontrado:[/red] {agent_id}")
            raise typer.Exit(1)
        target = match[0]
    else:
        target = live[0]

    full_id = target["agent_id"]
    action  = "watch_start" if watch else "full_report"
    args    = {"interval_seconds": 30} if watch else {"hours": hours}

    # Abrir SSE antes de enviar la task para no perder el resultado
    result_event = threading.Event()
    opsec_result: dict = {}

    def _listen_sse():
        url = _base_url() + f"/api/stream?token={_headers().get('X-Operator-Token','')}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
            with urllib.request.urlopen(req, timeout=90) as r:
                for raw_line in r:
                    if result_event.is_set():
                        break
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(line[5:])
                        if ev.get("topic") != "agents.result":
                            continue
                        d = ev.get("data", {})
                        if d.get("agent_id") != full_id:
                            continue
                        out = d.get("output", {})
                        if "overall_risk" in out or "status" in out:
                            opsec_result.update(d)
                            result_event.set()
                    except Exception:
                        pass
        except Exception:
            result_event.set()

    t = threading.Thread(target=_listen_sse, daemon=True)
    t.start()
    time.sleep(0.3)

    # Enviar task
    body = {"plugin": "opsec", "action": action, "args": args, "timeout": 70}
    with console.status(f"[cyan]Ejecutando opsec.{action} en {target['hostname']} ({full_id[:8]})…[/cyan]"):
        _http_post(f"/api/agents/{full_id}/task", body)
        result_event.wait(timeout=75)

    if watch:
        console.print(f"[green]✓ Monitoreo OPSEC activo[/green] cada 30s en [cyan]{target['hostname']}[/cyan]")
        console.print("[dim]Las alertas aparecerán en el dashboard y en `aligo stream`.[/dim]")
        return

    if not opsec_result:
        console.print("[yellow]Sin respuesta del agente (timeout).[/yellow]")
        raise typer.Exit(1)

    out = opsec_result.get("output", {})
    overall = out.get("overall_risk", "UNKNOWN")
    recs    = out.get("recommendations", [])
    details = out.get("details", {})
    ms      = opsec_result.get("duration_ms", 0)

    # Semáforo de riesgo
    color = {"CRITICAL": "bold red", "HIGH": "red", "MEDIUM": "yellow", "LOW": "green", "CLEAN": "green"}.get(overall, "white")
    icon  = {"CRITICAL": "[!] CRITICO", "HIGH": "[!] ALTO", "MEDIUM": "[~] MEDIO", "LOW": "[OK] BAJO", "CLEAN": "[OK] LIMPIO"}.get(overall, "[?]")

    console.print()
    console.print(Panel(
        f"[{color}]  RIESGO: {overall} — {icon}[/{color}]",
        title=f"OPSEC STATUS | {target['hostname']} | {full_id[:8]} | {ms:.0f}ms",
        border_style="green" if overall in ("CLEAN","LOW") else ("yellow" if overall == "MEDIUM" else "red"),
        expand=False,
    ))

    # Recomendaciones
    if recs:
        console.print("\n[bold]ACCIONES RECOMENDADAS:[/bold]")
        for r in recs:
            bullet_color = "red" if any(w in r for w in ("DETECTADO","CRITICO","COMPROMETIDO","BORRADO","ACTIVO","CAPTURA")) else "yellow"
            console.print(f"  [{bullet_color}]-> {r}[/{bullet_color}]")

    # Tabla de detalle
    console.print()
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("Check",    width=14)
    table.add_column("Riesgo",   width=10)
    table.add_column("Detalle",  width=55)

    def _risk_style(r: str) -> str:
        return {"CRITICAL": "bold red", "HIGH": "red", "MEDIUM": "yellow", "CLEAN": "green", "LOW": "green"}.get(r, "white")

    def _row(label, data, detail_fn):
        r = data.get("risk") or data.get("risk_level") or data.get("status") or "?"
        s = _risk_style(r)
        table.add_row(label, f"[{s}]{r}[/{s}]", detail_fn(data))

    _row("EDR / AV",   details.get("edr",{}),
         lambda d: f"{d.get('total_found',0)} detectados / {d.get('scanned_procs',0)} procs | " +
                   (", ".join(x["product"] for x in d.get("detected", [])) or "LIMPIO"))

    _row("Defender",   details.get("defender",{}),
         lambda d: f"amenazas_activas={d.get('has_active_threats',False)}")

    ev = details.get("events", {})
    w  = ev.get("warnings", {})
    _row("Event Logs", ev,
         lambda d: f"defender_hit={w.get('defender_detected')} | sysmon={w.get('sysmon_active')} | log_cleared={w.get('audit_log_cleared')}")

    _row("Sysmon",     details.get("sysmon",{}),
         lambda d: f"activo={d.get('sysmon_active',False)}")

    _row("Firewall",   details.get("firewall",{}),
         lambda d: "cambios recientes detectados" if d.get("risk") == "HIGH" else "sin cambios recientes")

    _row("Sandbox/VM", details.get("sandbox",{}),
         lambda d: f"in_sandbox={d.get('in_sandbox',False)} | indicadores={d.get('indicator_count',0)}")

    nm = details.get("net_monitor", {})
    _row("Red/Captura", nm,
         lambda d: (", ".join(t.get("tool","?") for t in d.get("tools_active",[])) or "LIMPIO"))

    console.print(table)
    console.print(f"\n[dim]Escaneado: {out.get('scan_time','')}[/dim]")


@app.command("health")
def health():
    """Verifica el estado del servidor."""
    resp = _http_get("/health")
    rprint(resp)


if __name__ == "__main__":
    app()
