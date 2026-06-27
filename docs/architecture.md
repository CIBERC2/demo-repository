# C2 Aligo — Architecture

## Overview

```
┌─────────────────────────────────────────────────────────┐
│                    OPERATOR SIDE                         │
│  ┌─────────────┐        ┌──────────────────────────┐    │
│  │  CLI (Rich) │        │  Dashboard (React/Vite)  │    │
│  │  operator/  │        │  port 5173               │    │
│  │  cli.py     │        │  SSE + REST              │    │
│  └──────┬──────┘        └──────────┬───────────────┘    │
└─────────┼───────────────────────────┼───────────────────┘
          │ REST /api/*               │ SSE /api/stream
          │ X-Operator-Token          │
          ▼                           ▼
┌─────────────────────────────────────────────────────────┐
│               C2 SERVER  (FastAPI + uvicorn)            │
│                       port 8000                          │
│                                                          │
│  ┌────────────┐  ┌───────────────┐  ┌────────────────┐  │
│  │ WebSocket  │  │ AgentManager  │  │   PubSub       │  │
│  │ Channel    │  │ (register,    │  │  (in-memory    │  │
│  │ /ws        │  │  outbox,      │  │   broker)      │  │
│  └─────┬──────┘  │  heartbeat)   │  └───────┬────────┘  │
│        │         └───────────────┘          │            │
│  ┌─────┴──────┐  ┌───────────────┐          │            │
│  │ DNS Channel│  │ crypto.py     │          │            │
│  │ UDP/5353   │  │ RSA-OAEP      │   topics:│            │
│  └────────────┘  │ AES-256-GCM   │  agents.*│            │
│                  │ HMAC-SHA256   │          │            │
│                  └───────────────┘          │            │
└─────────────────────────────────────────────────────────┘
          ▲ WS (encrypted)        ▲ DNS TXT (covert)
          │                       │
┌─────────┴───────────────────────┴───────────────────────┐
│                     AGENT SIDE                           │
│  ┌───────────────────────────────────────────────────┐  │
│  │                  agent.py                          │  │
│  │  ┌─────────┐  ┌──────────┐  ┌─────────────────┐  │  │
│  │  │Handshake│  │Heartbeat │  │  Task Handler   │  │  │
│  │  │ RSA→AES │  │  loop    │  │  (async)        │  │  │
│  │  └─────────┘  └──────────┘  └────────┬────────┘  │  │
│  │                                       │            │  │
│  │         Plugin Registry               ▼            │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐    │  │
│  │  │  shell   │  │ sysinfo  │  │  hot-loaded  │    │  │
│  │  │ plugin   │  │ plugin   │  │  plugins     │    │  │
│  │  └──────────┘  └──────────┘  └──────────────┘    │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### Pub/Sub over polling
AgentManager has an in-memory PubSub broker. When a task result arrives,
it is published to a topic. The SSE endpoint streams that to the dashboard
in real time — no polling loops anywhere.

### Hybrid encryption
- **Handshake**: RSA-OAEP (3072-bit) to exchange a symmetric key securely.
- **Session**: AES-256-GCM — every message gets a unique nonce.
- **Integrity**: HMAC-SHA256 (keyed with session key) on every message.

### Modular agents
Plugins are plain Python classes. They can be hot-loaded at runtime
(no restart) via the `__load__` magic task — base64-encode a Python file,
send it as a TASK, and the agent replaces the running plugin.

### Dual channel
- **Primary**: WebSocket — low latency, full-duplex.
- **Fallback**: DNS TXT over UDP/5353 — for environments that only allow
  DNS egress. The agent encodes messages as base32 subdomains.

---

## Alineación con MITRE ATT&CK

Ver documento completo: [docs/mitre_mapping.md](mitre_mapping.md)

Las 8 técnicas mapeadas en nuestro C2:

| ID | Nombre | Componente Aligo |
|---|---|---|
| T1071 | Application Layer Protocol | WebSocket :443 |
| T1071.004 | DNS | Canal DNS TXT fallback |
| T1572 | Protocol Tunneling | AES-GCM dentro de WebSocket |
| T1573 | Encrypted Channel | Esquema híbrido RSA+AES+HMAC |
| T1573.002 | Asymmetric Cryptography | RSA-3072 OAEP handshake |
| T1095 | Non-Application Layer Protocol | Protocolo Aligo/1.0 custom |
| T1105 | Ingress Tool Transfer | Hot-swap plugins firmados RSA-PSS |
| T1568 | Dynamic Resolution | Fallback automático WS→DNS |

---

## Nivel 4 — Características Avanzadas (v2.0)

### Audit Trail Inmutable
Cada comando ejecutado genera un bloque encadenado (SHA-256 sobre el bloque
anterior). `verify_chain()` detecta cualquier alteración retroactiva.
Ver: `server/core/audit_trail.py` · Endpoint: `GET /audit`

### Observabilidad Interna
Métricas en tiempo real sin SIEM externo: comandos enviados, tiempo de
respuesta promedio, switches de canal, timeline de eventos.
Ver: `server/core/observability.py` · Endpoint: `GET /metrics`

### Hot-swap con Firma RSA-PSS
Los plugins enviados remotamente son verificados criptográficamente antes
de importarse. Un plugin sin firma válida nunca ejecuta código.
Ver: `server/core/crypto.py` · `agent/agent.py` · Comando: `plugin-load`
