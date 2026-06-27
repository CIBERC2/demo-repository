# Aligo Protocol v1.0 Specification

## Wire Format

Every message on the wire is JSON:

```json
{
  "id":        "<uuid-v4>",
  "type":      "<MessageType>",
  "agent_id":  "<uuid-v4 | empty-string>",
  "ts":        1234567890.123,
  "sig":       "<base64-HMAC-SHA256>",
  "envelope":  {
    "nonce":  "<base64-12-bytes>",
    "ct":     "<base64-ciphertext+GCM-tag>",
    "aad":    "<base64-message-id>"
  }
}
```

The `envelope` field replaces a plaintext `payload` once the session
key is established. Before that (HELLO, HANDSHAKE), `payload` is sent
in the clear.

## Message Types

| Type        | Direction        | Encrypted | Description |
|-------------|-----------------|-----------|-------------|
| `HELLO`     | agent → server  | No        | Registration + agent pub key |
| `HANDSHAKE` | server ↔ agent  | Partially | Key exchange (see below) |
| `HEARTBEAT` | agent → server  | Yes       | Periodic liveness + metrics |
| `TASK`      | server → agent  | Yes       | Command to execute |
| `RESULT`    | agent → server  | Yes       | Command output |
| `EVENT`     | agent → server  | Yes       | Async telemetry |
| `ERROR`     | bidirectional   | Yes*      | Recoverable error |
| `BYE`       | bidirectional   | Yes       | Clean disconnect |

## Handshake Sequence

```
Agent                              Server
  │                                  │
  │──── HELLO (plain) ──────────────▶│
  │     {hostname, os, arch,         │
  │      capabilities, pub_pem}      │
  │                                  │  registers provisional ID
  │                                  │  generates challenge nonce
  │◀─── HANDSHAKE (plain) ───────────│
  │     {server_pub_pem,             │
  │      agent_id, challenge}        │
  │                                  │
  │  generate session_key (32 bytes) │
  │  wrap = RSA-OAEP(server_pub,     │
  │                  session_key)    │
  │  ack = HMAC(session_key,         │
  │             challenge)           │
  │                                  │
  │──── HANDSHAKE (plain) ──────────▶│
  │     {wrapped_session_key,        │
  │      challenge_ack}              │
  │                                  │  unwrap session_key
  │                                  │  verify challenge_ack
  │                                  │  register agent_id
  │◀─── HANDSHAKE (encrypted!) ──────│
  │     {ok: true, agent_id}         │
  │                                  │
  │ ←——— AES-256-GCM session ————→ │
```

## Payload Schemas

### TaskPayload
```json
{
  "task_id": "<uuid>",
  "plugin":  "shell",
  "action":  "exec",
  "args":    {"cmd": "whoami", "timeout": 10},
  "timeout": 30.0
}
```

### ResultPayload
```json
{
  "task_id":     "<uuid>",
  "ok":          true,
  "output":      {"stdout": "...", "stderr": "", "returncode": 0},
  "error":       null,
  "duration_ms": 42.1
}
```
