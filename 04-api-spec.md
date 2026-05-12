# 04 — API Specification

> **Versión**: v1.1
> **Base URL (local)**: `http://localhost:8000`
> **Base URL (sandbox planeado)**: `https://api.pasarela.dev/v1`
> **Formato**: REST + JSON
> **Autenticación**: API Key vía `Authorization: Bearer <key>` o `X-API-Key: <key>`
> **Inspirada en**: Stripe API design principles

## Leyenda de estado

- ✅ implementado en MVP
- 🟡 spec definida, no implementada aún (Día 6-7)
- 🔵 Fase 2+

---

## Principios de diseño

1. **REST limpio**: recursos como sustantivos, acciones como verbos HTTP.
2. **Versionado en URL**: `/v1/` permite breaking changes en `/v2/` sin romper integraciones.
3. **IDs prefijados**: `pi_xxx`, `mch_xxx`, `evt_xxx` (autoexplicativos).
4. **Idempotencia obligatoria** en endpoints de escritura.
5. **Errores claros**: códigos semánticos + mensajes descriptivos en español.
6. **Paginación cursor-based** para listados largos.
7. **Webhooks firmados** con HMAC-SHA256.

---

## Autenticación

Toda llamada protegida acepta cualquiera de:

```http
Authorization: Bearer sk_test_<clave>
X-API-Key: sk_test_<clave>
```

MVP entrega solo **secret keys** (`sk_test_*`). El bootstrap dev crea: `sk_test_dev_pasarela_001`.

Tipos planeados:
- **`pk_test_*` / `pk_live_*`** (🟡): publishable, frontend, scope reducido.
- **`sk_test_*` / `sk_live_*`** (✅): secret, backend, acceso completo.

Hash en DB: SHA256 con pepper (`API_KEY_PEPPER` env). Migración a bcrypt planeada Fase 2.

**Nunca expongas un secret key en HTML, JavaScript del cliente, o repositorios públicos.**

---

## Idempotencia

Endpoints de escritura **aceptarán** header `Idempotency-Key`:

```http
Idempotency-Key: cliente-orden-12345
```

Si el mismo `Idempotency-Key` llega dos veces (combinado con el mismo `sk`), se devuelve la respuesta original sin reprocesar. TTL: 24 horas.

**Estado MVP** (🟡): columna `payment_intents.idempotency_key` + índice único `(merchant_id, idempotency_key)` existen, pero el endpoint **no valida ni consulta el header todavía**. Pendiente Día 6.

---

## Endpoints

### Payment Intents

#### `POST /v1/payments` ✅

Crea un nuevo intent de cobro C2P.

**Request actual MVP** (campos planos, no anidados):
```json
{
  "amount": 5000,
  "currency": "VES",
  "customer_phone": "04141234567",
  "customer_id_document": "V12345678",
  "customer_bank_code": "0114"
}
```

**Request objetivo (planeado, anidado + metadata)**:
```json
{
  "amount": 5000,
  "currency": "VES",
  "customer": {
    "phone": "04141234567",
    "id_document": "V12345678",
    "bank_code": "0114"
  },
  "metadata": {
    "order_id": "ORD-12345"
  }
}
```

**Notas**:
- `amount` está en céntimos (5000 = 50.00 VES). Esto evita errores de redondeo.
- `bank_code` es el código ABA del banco del cliente (no del comerciante).
- `metadata` es opcional, sirve para vincular con sistemas del comerciante.

**Response 201 actual MVP** (campos planos, sin masking, sin client_secret, sin expires_at):
```json
{
  "id": "uuid",
  "external_id": "pi_xxxxxxxxxxxx",
  "merchant_id": "uuid",
  "merchant_account_id": "uuid",
  "amount_cents": 5000,
  "currency": "VES",
  "status": "created",
  "customer_phone": "04141234567",
  "customer_id_document": "V12345678",
  "customer_bank_code": "0114",
  "flow_mode": "direct_to_merchant",
  "bank_reference": null,
  "failure_code": null,
  "failure_message": null,
  "created_at": "2026-05-11T18:30:00",
  "updated_at": "2026-05-11T18:30:00",
  "confirmed_at": null,
  "succeeded_at": null,
  "failed_at": null
}
```

**Pendientes**:
- 🟡 Masking de `customer_phone` / `customer_id_document` en respuesta.
- 🟡 `client_secret` para uso frontend con `pk_*`.
- 🟡 Campo `expires_at` + job de expiración a 15 min.
- 🟡 `metadata` y wrapper `customer` anidado.

---

#### `POST /v1/payments/{intent_id}/confirm` ✅

Confirma el pago con la clave OTP. MVP actual lo expone via `sk` (Authorization). El uso desde frontend con `pk` + `client_secret` queda 🟡.

**Path param**: `{intent_id}` es el UUID interno (no `external_id`).

**Request actual MVP:**
```json
{
  "client_secret": "ignored_in_mvp",
  "otp": "123456"
}
```

Nota: el schema requiere `client_secret` pero en MVP **no se valida** (auth real vía API key). El estado de entrada aceptado es `created` o `requires_confirmation`. La llamada usa `MockBankAdapter` (80% éxito aleatorio).

**Response 200 (éxito):**
```json
{
  "id": "pi_x9y8z7w6v5u4t3s2r1q0",
  "object": "payment_intent",
  "status": "succeeded",
  "amount": 5000,
  "currency": "VES",
  "bank_reference": "BCRB-2026-0509-7890123",
  "succeeded_at": "2026-05-09T18:32:15Z"
}
```

**Response 402 (rechazado por banco):**
```json
{
  "error": {
    "type": "card_error",
    "code": "insufficient_funds",
    "message": "Fondos insuficientes en la cuenta del cliente.",
    "payment_intent": "pi_x9y8z7w6v5u4t3s2r1q0"
  }
}
```

**Response 400 (OTP inválido):**
```json
{
  "error": {
    "type": "invalid_request_error",
    "code": "invalid_otp",
    "message": "La clave OTP es incorrecta o ha expirado."
  }
}
```

---

#### `GET /v1/payments/{id}`

Consulta un payment intent específico.

**Response 200:**
```json
{
  "id": "pi_x9y8z7w6v5u4t3s2r1q0",
  "object": "payment_intent",
  "status": "succeeded",
  "amount": 5000,
  "currency": "VES",
  "customer": {
    "phone": "0414****567",
    "id_document": "V*****678",
    "bank_code": "0114"
  },
  "bank_reference": "BCRB-2026-0509-7890123",
  "metadata": { "order_id": "ORD-12345" },
  "created_at": "2026-05-09T18:30:00Z",
  "succeeded_at": "2026-05-09T18:32:15Z"
}
```

---

#### `GET /v1/payments` ✅

Lista payment intents del comerciante.

**Query params actual MVP:**
- `limit` (1-100, default 20)
- `cursor` (opaco, base64url de `created_at|uuid`)

**Pendiente** (🟡): filtros `status`, `created[gte]`, `created[lte]`.

**Response 200 (formato actual):**
```json
{
  "items": [
    { "id": "uuid", "external_id": "pi_xxx", "status": "succeeded", "amount_cents": 5000, ... }
  ],
  "next_cursor": "base64url|opaco|null",
  "has_more": true
}
```

---

#### `POST /v1/payments/{id}/cancel` 🟡 (no implementado)

Cancela un payment intent que aún no se ha procesado (estados `created` o `pending`).

**Response 200:**
```json
{
  "id": "pi_x9y8z7w6v5u4t3s2r1q0",
  "object": "payment_intent",
  "status": "canceled",
  "canceled_at": "2026-05-09T18:35:00Z"
}
```

---

### Webhooks

#### `POST /v1/webhook_endpoints` ✅

Registra una URL para recibir notificaciones de eventos.

**Request:**
```json
{
  "url": "https://mi-tienda.com/webhooks/pasarela",
  "enabled_events": ["payment.succeeded", "payment.failed"]
}
```

`enabled_events` acepta valores específicos o `["*"]` para todos los eventos.

**Response 201 actual MVP** (prefix `whep_`, no `we_`):
```json
{
  "id": "uuid",
  "external_id": "whep_xxxxxxxxxxxx",
  "merchant_id": "uuid",
  "url": "https://mi-tienda.com/webhooks/pasarela",
  "enabled_events": ["payment_intent.succeeded", "payment_intent.failed"],
  "status": "active",
  "created_at": "...",
  "updated_at": "...",
  "signing_secret": "whsec_xxxxxxxxxxxxxxxxxxxxxxxx"
}
```

**El `signing_secret` se devuelve UNA SOLA VEZ.** Guárdalo seguro — se usa para validar las firmas HMAC de los webhooks entrantes.

---

#### `GET /v1/webhook_endpoints` ✅

Lista los endpoints configurados (paginación cursor — mismo formato que `/v1/payments`).

---

#### `DELETE /v1/webhook_endpoints/{id}` 🟡 (no implementado)

Elimina un endpoint.

---

### API Keys 🟡 (no implementado)

#### `POST /v1/api_keys`

Genera un nuevo par de API keys (publishable + secret).

**Request:**
```json
{
  "label": "Producción WooCommerce",
  "environment": "live"
}
```

**Response 201:**
```json
{
  "publishable_key": "pk_live_51HxYzABC...",
  "secret_key": "sk_live_51HxYzDEF...",
  "label": "Producción WooCommerce",
  "environment": "live",
  "created_at": "2026-05-09T18:00:00Z"
}
```

**El `secret_key` se devuelve UNA SOLA VEZ.** Si lo pierdes, debes generar uno nuevo y revocar el anterior.

---

#### `POST /v1/api_keys/{id}/revoke`

Revoca una API key. Llamadas con esa key fallarán con 401.

---

### Banks (recurso público) 🟡 (no implementado)

#### `GET /v1/banks`

Lista los bancos cuyas claves OTP pueden ser validadas (corresponde a `listarBancosApi` de Bancaribe).

**Response 200:**
```json
{
  "object": "list",
  "data": [
    { "code": "0102", "name": "Banco de Venezuela" },
    { "code": "0105", "name": "Banco Mercantil" },
    { "code": "0114", "name": "Bancaribe" },
    { "code": "0134", "name": "Banesco" },
    { "code": "0163", "name": "Banco del Tesoro" },
    { "code": "0191", "name": "BNC" }
  ]
}
```

---

## Webhooks salientes

Cuando ocurre un evento, Pasarela hace un `POST` al `url` del `webhook_endpoint`.

**Headers actuales MVP:**
```http
Content-Type: application/json
X-Pasarela-Signature: t=1731234567,v1=abc123def456...
X-Pasarela-Event-Type: payment_intent.succeeded
```

Nota: el header de firma es `X-Pasarela-Signature` (con prefijo `X-`). El body se envía como JSON serializado compacto (`separators=(",", ":")`).

**Payload actual MVP:**
```json
{
  "type": "payment_intent.succeeded",
  "data": {
    "id": "uuid",
    "external_id": "pi_xxx",
    "status": "succeeded",
    "amount_cents": 5000,
    "currency": "VES",
    "merchant_id": "uuid",
    "bank_reference": "MOCK-...",
    "created_at": "...",
    "updated_at": "...",
    "failure_code": null,
    "failure_message": null
  }
}
```

Nota: el wrapper `id`/`object`/`created_at`/`data.object` estilo Stripe es objetivo de diseño. MVP usa `{type, data}` plano.

### Verificación de firma

El header `Pasarela-Signature` contiene `t=<timestamp>,v1=<hmac>`. Para validar:

```python
import hmac
import hashlib

def verify_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    parts = dict(p.split("=") for p in signature_header.split(","))
    timestamp = parts["t"]
    expected = parts["v1"]
    
    signed_payload = f"{timestamp}.{payload.decode()}".encode()
    computed = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(computed, expected)
```

### Reintentos

**Estado MVP** (🟡): un único intento por `BackgroundTask`. Si responde no-2xx o lanza error, `delivered=false` queda en DB sin reintento automático. Pendiente worker con backoff.

**Diseño objetivo** (Fase 2): si tu endpoint no devuelve `2xx`, Pasarela reintenta con backoff exponencial:

| Intento | Tiempo desde el primero |
|---|---|
| 1 | 0s (inmediato) |
| 2 | 1 minuto |
| 3 | 5 minutos |
| 4 | 15 minutos |
| 5 | 1 hora |
| 6 | 6 horas |
| 7 | 24 horas |

Después del séptimo intento, el webhook se marca como `failed` y debe re-enviarse manualmente desde el dashboard.

### Eventos disponibles

| Evento | Cuándo ocurre | Estado |
|---|---|---|
| `payment_intent.created` | Se crea un nuevo payment intent | ✅ |
| `payment_intent.succeeded` | Pago confirmado por el banco | ✅ |
| `payment_intent.failed` | Pago rechazado | ✅ |
| `webhook_endpoint.created` | Se registró un nuevo endpoint (audit log; no se dispara webhook) | ✅ (solo evento) |
| `payment_intent.pending` / `.processing` / `.canceled` | Estados intermedios | 🟡 |

Nota: el namespace actual es `payment_intent.*` (no `payment.*`).

---

## Errores

Todos los errores siguen este formato:

```json
{
  "error": {
    "type": "<categoría>",
    "code": "<código_específico>",
    "message": "Mensaje legible en español",
    "param": "<campo_afectado_opcional>",
    "request_id": "req_xxx"
  }
}
```

### Categorías de error

| `type` | Descripción | HTTP Status |
|---|---|---|
| `invalid_request_error` | Petición mal formada o parámetros inválidos | 400 |
| `authentication_error` | API key inválida o ausente | 401 |
| `permission_error` | API key válida pero sin permisos | 403 |
| `not_found_error` | Recurso no existe | 404 |
| `rate_limit_error` | Demasiadas peticiones | 429 |
| `card_error` | Error procesando el pago (rechazo del banco) | 402 |
| `api_error` | Error interno de Pasarela | 500 |
| `bank_error` | Error de Bancaribe (timeout, indisponibilidad) | 502 |

### Códigos específicos comunes

| `code` | Descripción |
|---|---|
| `invalid_phone` | Teléfono no cumple formato `04XXXXXXXXX` |
| `invalid_id_document` | Cédula no cumple formato `[VEJGP]\d+` |
| `invalid_bank_code` | Banco no soportado |
| `invalid_amount` | Monto fuera de rango |
| `invalid_otp` | Clave OTP incorrecta o expirada |
| `insufficient_funds` | Fondos insuficientes |
| `account_blocked` | Cuenta del cliente bloqueada |
| `payment_already_processed` | Intent ya en estado final |
| `payment_expired` | Intent expiró antes de confirmarse |
| `bank_timeout` | Bancaribe no respondió a tiempo |

---

## Rate limits 🟡 (no implementado en MVP)

| Tier | Requests por minuto | Requests por segundo |
|---|---|---|
| Test environment | 60 | 5 |
| Live (default) | 300 | 25 |
| Live (high-volume) | 1000 | 50 |

Headers de respuesta:
```http
X-RateLimit-Limit: 300
X-RateLimit-Remaining: 287
X-RateLimit-Reset: 1731234600
```

---

## OpenAPI / Swagger

La especificación completa en formato OpenAPI 3.1 está disponible en:
```
https://api.pasarela.dev/openapi.json
```

Swagger UI en:
```
https://api.pasarela.dev/docs
```

---

## SDKs (Fase 1 vs roadmap)

| Lenguaje | Estado |
|---|---|
| JavaScript / TypeScript (browser y Node) | ✅ MVP |
| Python | 🟡 Fase 1 (después de MVP) |
| PHP | 🟡 Fase 1 |
| Plugin WooCommerce | 🟡 Fase 1 |
| Plugin Shopify | 🟡 Fase 2 |
| Plugin Magento / PrestaShop | 🟡 Fase 2 |
| Go / Ruby / Java | 🔵 Fase 2+ según demanda |
