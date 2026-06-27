# Aligo C2 — Cryptographic Scheme

## Primitives

| Layer     | Algorithm     | Key size | Notes |
|-----------|---------------|----------|-------|
| Handshake | RSA-OAEP      | 3072-bit | SHA-256 hash + MGF1 |
| Session   | AES-256-GCM   | 256-bit  | Unique 96-bit nonce per msg |
| Integrity | HMAC-SHA256   | session key | Over all fields except `sig` |
| Server ID | RSA-PSS (opt) | 3072-bit | For future mutual TLS |

## Key Lifecycle

```
Server startup
  ├── load or generate RSA-3072 keypair (keys/)
  └── expose public key via GET /api/pubkey

Agent connect
  ├── generates ephemeral RSA keypair (not persisted)
  ├── HELLO contains agent public key PEM
  ├── receives server public key in HANDSHAKE
  ├── generates 256-bit session_key = os.urandom(32)
  ├── wraps:  RSA-OAEP(server_pub, session_key)
  └── proves: HMAC-SHA256(session_key, challenge)

Session active
  └── all messages: AES-256-GCM(session_key, plaintext, aad=msg_id)
       + HMAC-SHA256(session_key, serialized_msg)

Session end
  └── session_key discarded — next connect = new key
```

## AES-GCM Nonce Strategy

- Nonce is `os.urandom(12)` (96 bits) per message.
- With 32-bit counter probability of collision at 2^32 messages ≈ 4 billion.
- GCM authentication tag is appended to ciphertext by `cryptography` lib.
- AAD = message UUID ensures that swapping envelopes between messages fails
  authentication.

## HMAC Verification

Signature covers: `JSON.dumps({all fields except sig}, sort_keys=True)`.
Sort order is deterministic across Python versions.
`hmac.compare_digest` prevents timing attacks.
