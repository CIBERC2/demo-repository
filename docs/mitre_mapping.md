# Mapeo MITRE ATT&CK — C2 Aligo
**Hackathon Aligo Defensores Informáticos · Junio 2026**

---

## Táctica: Command and Control (TA0011)

Nuestro C2 implementa un canal de comunicación encubierto, cifrado de
extremo a extremo y resiliente ante fallos de red. A continuación se mapea
cada técnica con detalle de implementación, nivel de evasión y controles
defensivos correspondientes.

---

### T1071 — Application Layer Protocol

| Campo | Detalle |
|---|---|
| **Implementación en Aligo** | WebSocket sobre puerto 443 (HTTPS). El tráfico aparece como una conexión persistente WebSocket a cualquier servicio SaaS corporativo. |
| **Decisión de diseño** | Usar puerto 443 hace que el tráfico pase a través de la mayoría de firewalls corporativos sin inspección adicional. El handshake WebSocket es HTTP/1.1 estándar. |
| **Detección Blue Team** | Analizar conexiones WebSocket de larga duración a IPs desconocidas. JA3 fingerprinting del TLS. Monitoreo de DNS para dominios C2 recientes. |
| **Nivel de detección** | **Medio** — visible en logs de proxy si se hace inspección TLS |
| **Mitigación MITRE** | M1031 Network Intrusion Prevention, M1037 Filter Network Traffic |

---

### T1071.004 — DNS

| Campo | Detalle |
|---|---|
| **Implementación en Aligo** | Canal alternativo mediante registros TXT. El agente codifica mensajes en subdominios: `<payload_b32>.<seq>.<agent_prefix>.c2.<dominio>`. El servidor responde con la siguiente task en el TXT de la respuesta. |
| **Decisión de diseño** | El DNS casi nunca se bloquea porque rompe la resolución de nombres. Es el canal de fallback automático cuando WebSocket no está disponible. |
| **Detección Blue Team** | Monitoreo de volumen anómalo de peticiones DNS TXT. Análisis de entropía de subdominios (base32 tiene entropía alta). Correlación de frecuencia de consultas. |
| **Nivel de detección** | **Difícil** — DNS suele quedar fuera del alcance de EDR y SIEM estándar |
| **Mitigación MITRE** | M1037 Filter Network Traffic (bloquear DNS hacia resolvers no corporativos), DNS over HTTPS monitoring |

---

### T1572 — Protocol Tunneling

| Campo | Detalle |
|---|---|
| **Implementación en Aligo** | Comandos cifrados AES-256-GCM dentro de WebSocket. El payload no corresponde a ningún protocolo conocido — es un JSON con un campo `envelope` que contiene nonce + ciphertext en base64. |
| **Decisión de diseño** | Incluso con inspección TLS (MITM corporativo), el inspector solo ve bytes cifrados AES-GCM dentro del WebSocket. No hay patrones reconocibles. |
| **Detección Blue Team** | DPI behavioral analysis — buscar flujos WebSocket con payloads de tamaño consistente y alta entropía. Anomalías en timing (beaconing regular de heartbeats). |
| **Nivel de detección** | **Difícil** — requiere inspección deep packet con correlación de comportamiento |
| **Mitigación MITRE** | M1031 Network Intrusion Prevention, M1020 SSL/TLS Inspection |

---

### T1573 — Encrypted Channel

| Campo | Detalle |
|---|---|
| **Implementación en Aligo** | Esquema híbrido: handshake RSA-3072 OAEP para distribución de clave → sesión AES-256-GCM con nonce único por mensaje → firma HMAC-SHA256 sobre cada mensaje → campo `seq` anti-replay. |
| **Decisión de diseño** | Control total del protocolo criptográfico sin depender de TLS de terceros. Permite rotar claves de sesión por agente y detectar tampering a nivel de aplicación. |
| **Detección Blue Team** | Análisis de handshake inicial (intercambio de claves RSA en claro antes de cifrar). Pattern matching en los primeros mensajes de una nueva conexión WS. |
| **Nivel de detección** | **Difícil** — una vez establecida la sesión AES, el contenido es opaco |
| **Mitigación MITRE** | M1031, M1020, M1041 Encrypt Sensitive Information |

---

### T1573.002 — Asymmetric Cryptography

| Campo | Detalle |
|---|---|
| **Implementación en Aligo** | RSA-3072 para el handshake inicial (OAEP + SHA-256). La clave pública del servidor se distribuye por `/api/pubkey`. Cada agente genera su propio par RSA-2048 para futuro mTLS. |
| **Decisión de diseño** | RSA-3072 supera el umbral NIST recomendado para 2030+. El agente cifra la `session_key` con la pubkey del servidor — solo el servidor puede descifrarla, garantizando autenticidad del canal. |
| **Detección Blue Team** | Captura del handshake inicial para análisis de tamaño de mensaje (RSA-3072 produce ~512 bytes de ciphertext). Fingerprinting del tamaño de los primeros frames WebSocket. |
| **Nivel de detección** | **Medio** — el handshake ocurre en texto antes de activar AES |
| **Mitigación MITRE** | M1031, Threat Intelligence para identificar fingerprints de handshakes conocidos |

---

### T1095 — Non-Application Layer Protocol

| Campo | Detalle |
|---|---|
| **Implementación en Aligo** | Protocolo propio "Aligo/1.0" sobre WebSocket. Los tipos de mensaje (HELLO, HANDSHAKE, HEARTBEAT, TASK, RESULT, EVENT, BYE) no corresponden a ningún protocolo de aplicación estándar. |
| **Decisión de diseño** | Al no usar REST/HTTP dentro del WebSocket, no hay Content-Type reconocible, no hay User-Agent estándar, no hay estructura HTTP de request/response que los proxies puedan parsear. |
| **Detección Blue Team** | Behavioral analysis del flujo WebSocket. Inspección de payloads para detectar estructura JSON personalizada vs protocolos conocidos (STOMP, MQTT, etc.). |
| **Nivel de detección** | **Difícil** — el protocolo custom no activa reglas de firmas IDS estándar |
| **Mitigación MITRE** | M1031, Reglas Snort/Suricata personalizadas para WebSocket con payloads de alta entropía |

---

### T1105 — Ingress Tool Transfer

| Campo | Detalle |
|---|---|
| **Implementación en Aligo** | Hot-swap de plugins firmados RSA-PSS. El operador envía código Python en base64 dentro de un mensaje `TASK` tipo `__load__`, firmado con la clave privada RSA del servidor. El agente verifica la firma antes de importar. |
| **Decisión de diseño** | La firma RSA-PSS + SHA-256 garantiza que solo el servidor legítimo puede enviar código ejecutable. Si la firma falla, el código nunca se importa — el agente loguea la anomalía y continúa. |
| **Detección Blue Team** | Monitoreo de escritura de archivos .py temporales en el filesystem del endpoint. Correlación de eventos de importación dinámica de módulos Python. |
| **Nivel de detección** | **Muy difícil** — el plugin viaja cifrado AES-GCM y se elimina tras importación |
| **Mitigación MITRE** | M1045 Code Signing (implementado en Aligo), M1038 Execution Prevention |

---

### T1568 — Dynamic Resolution

| Campo | Detalle |
|---|---|
| **Implementación en Aligo** | Fallback automático WebSocket → DNS cuando el canal primario falla. El agente detecta la desconexión en el backoff loop y puede redirigir al canal DNS sin intervención del operador. |
| **Decisión de diseño** | La resiliencia de canal evita que un simple bloqueo de puerto corte el acceso. El canal DNS usa un dominio configurable en `.env`, que puede rotarse remotamente. |
| **Detección Blue Team** | Monitoreo de cambios en patrones de comunicación: mismo host que cambia de WebSocket a DNS. Correlación de logs de red y DNS en el mismo timeframe. |
| **Nivel de detección** | **Difícil** — los dos canales parecen tráfico independiente no relacionado |
| **Mitigación MITRE** | M1031, M1037, DNS Sinkholing, Monitoreo de TXT records salientes |

---

## Resumen de Niveles de Detección

| Técnica | ID | Nivel |
|---|---|---|
| Application Layer Protocol | T1071 | Medio |
| DNS | T1071.004 | Difícil |
| Protocol Tunneling | T1572 | Difícil |
| Encrypted Channel | T1573 | Difícil |
| Asymmetric Cryptography | T1573.002 | Medio |
| Non-App Layer Protocol | T1095 | Difícil |
| Ingress Tool Transfer | T1105 | Muy difícil |
| Dynamic Resolution | T1568 | Difícil |

---

## Preguntas del Jurado y Respuestas Preparadas

**Q: "¿Por qué pub/sub y no polling?"**

A: El polling clásico genera un patrón de beaconing completamente predecible —
una petición HTTP cada N segundos es una firma de red trivial que cualquier
SIEM detecta con una regla de correlación temporal (T1071: frequency of
connections). Nuestro pub/sub con SSE mantiene una sola conexión persistente
abierta; los datos fluyen solo cuando hay algo que enviar. Desde el punto de
vista del Blue Team, el patrón es idéntico a WebSocket de Slack o Teams:
una conexión de larga duración sin ciclos regulares detectables.

---

**Q: "¿Por qué RSA + AES y no solo TLS?"**

A: TLS delega el cifrado a la implementación del sistema operativo o del
runtime, que puede estar sujeto a inspección corporativa mediante MITM
con certificados raíz instalados en el endpoint (T1573.002). Al implementar
nuestro propio esquema híbrido RSA-3072 + AES-256-GCM dentro del WebSocket,
el tráfico permanece opaco incluso cuando el proxy corporativo rompe TLS:
el inspector solo ve bytes cifrados AES que no puede descifrar sin la
`session_key` negociada en el handshake RSA. Control total del protocolo
criptográfico sin depender de terceros.

---

**Q: "¿Qué pasa si el servidor C2 cae?"**

A: El agente implementa backoff exponencial (1s → 2s → 4s → 8s → 30s máx)
sobre el canal WebSocket. Si los reintentos fallan durante N ciclos, activa
automáticamente el canal DNS alternativo (T1568: Dynamic Resolution) que
tunneliza comandos dentro de registros TXT, canal que casi nunca se bloquea
porque hacerlo rompe la resolución de nombres del segmento. El operador
no necesita intervenir — el cambio de canal es transparente.

---

**Q: "¿Cómo sabe el jurado que el audit trail no fue alterado?"**

A: Cada bloque del audit trail contiene el campo `prev_hash` = SHA-256 del
bloque anterior, y `block_hash` = SHA-256 de todos sus propios campos
incluyendo `prev_hash`. Alterar cualquier bloque invalida su `block_hash`,
lo cual invalida el `prev_hash` del siguiente, propagando el fallo en cascada.
El método `verify_chain()` recorre la cadena completa en O(n) y retorna
la lista exacta de bloques comprometidos. Es el mismo principio que Bitcoin:
es computacionalmente inviable alterar un bloque sin recalcular toda la
cadena posterior con la potencia necesaria.

---

**Q: "¿Qué diferencia a este C2 de Cobalt Strike o Sliver?"**

A: Tres diferencias fundamentales:

1. **Arquitectura pub/sub nativa**: Cobalt Strike y Sliver usan polling
   con beacons periódicos — un patrón de red detectable. Nuestro C2 usa
   pub/sub puro con SSE y WebSocket persistente: sin ciclos regulares.

2. **Audit trail inmutable integrado**: ningún C2 open-source o comercial
   incluye una cadena de hashes de auditabilidad built-in. En Aligo, cada
   comando ejecutado queda en el trail con su hash encadenado — esencial
   para operaciones legales y compliance en un red team autorizado.

3. **Hot-swap con firma RSA-PSS**: los plugins se cargan en caliente con
   verificación criptográfica del emisor. Un plugin malicioso inyectado
   en tránsito o por un agente comprometido es rechazado automáticamente.

4. **Código propio, auditable, de laboratorio**: diseñado para entender,
   no para ocultar. El objetivo es educativo y defensivo — los analistas
   pueden leer cada línea para comprender las técnicas que detectan.
