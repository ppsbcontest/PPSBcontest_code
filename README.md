# Pasarela API

Pasarela de pagos C2P (Customer-to-Payment) para el mercado venezolano. Backend FastAPI con integración a bancos vía Strategy Pattern.

## Stack

- **Python 3.12** + FastAPI (async)
- **SQLAlchemy 2.0** (Mapped/mapped_column) + asyncpg
- **PostgreSQL 16+**
- **Alembic** para migraciones
- **httpx** para webhooks salientes
- **Sentry SDK** (opcional, prod)

## Estructura

```
app/
├── api/v1/
│   ├── payments.py             # POST /v1/payments, /confirm, GET, list
│   └── webhook_endpoints.py    # POST/GET /v1/webhook_endpoints
├── banking/
│   ├── base.py                 # BankAdapter ABC (Strategy Pattern)
│   ├── mock.py                 # MockBankAdapter (80% éxito, 1-3s latencia)
│   └── bancaribe.py            # BancaribeAdapter stub (pendiente Día 7)
├── models/                     # Paquete por dominio
│   ├── merchant.py             # Merchant, ApiKey, MerchantAccount
│   ├── payment.py              # PaymentIntent
│   ├── webhook.py              # WebhookEndpoint, WebhookAttempt
│   └── event.py                # Event
├── schemas/                    # Pydantic request/response
├── services/
│   ├── events.py               # EventService (audit log)
│   └── webhooks.py             # WebhookService + HMAC + dispatcher
├── api/deps.py                 # Auth middleware (API Key + sha256)
├── bootstrap.py                # Seed dev fixtures (merchant, account, api_key)
├── database.py                 # Engine + Base + get_db
├── security.py                 # API key hashing (sha256 + pepper)
└── main.py                     # FastAPI app + Sentry init + lifespan
alembic/                        # Migraciones
Dockerfile                      # Imagen producción
docker-compose.yml              # Postgres local dev
```

## Setup local

### 1. Postgres con Docker

```bash
docker compose up -d
```

Levanta `pasarela_db` en `localhost:5432`.

### 2. Variables de entorno

Copia `.env.example` a `.env` y ajusta:

```bash
cp .env.example .env
```

```
DATABASE_URL=postgresql+asyncpg://pasarela_user:pasarela_password@localhost:5432/pasarela_db
API_KEY_PEPPER=dev_pepper_local
SENTRY_DSN=         # vacío en dev
ENVIRONMENT=development
```

### 3. Dependencias

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Migraciones

```bash
alembic upgrade head
```

### 5. Arrancar API

```bash
uvicorn app.main:app --reload
```

Disponible en `http://localhost:8000`. Docs: `/docs`.

Al primer arranque, `bootstrap.py` seedea:
- 1 merchant dev (`merch_dev_001`)
- 1 cuenta default
- 1 API key con plaintext: **`sk_test_dev_pasarela_001`** (solo dev, no prod)

## Variables de entorno

| Variable | Descripción | Requerido |
|---|---|---|
| `DATABASE_URL` | Conexión Postgres. Acepta `postgres://`, `postgresql://`, o `postgresql+asyncpg://`. Auto-detecta SSL para Supabase/Neon | Sí |
| `API_KEY_PEPPER` | Pepper para hash sha256 de API keys. Mín 32 chars, genera con `openssl rand -hex 32` | Sí |
| `SENTRY_DSN` | DSN Sentry para captura de errores | No |
| `ENVIRONMENT` | `development`, `staging`, `production`. En `production` no se ejecuta el seed dev | No (default `development`) |
| `PORT` | Puerto HTTP (lo inyecta Koyeb) | No (default 8000) |

## Autenticación

API key por request. Dos formatos aceptados:

```
Authorization: Bearer sk_test_dev_pasarela_001
```

o

```
X-API-Key: sk_test_dev_pasarela_001
```

El servidor hashea con sha256 + pepper, busca en `api_keys.key_hash`, valida `revoked_at IS NULL`, carga cuenta default activa, y actualiza `last_used_at`.

## Endpoints

### Health

```
GET /health → {"status": "ok"}
```

### Payments

| Método | Path | Descripción |
|---|---|---|
| POST | `/v1/payments` | Crear payment intent (estado `created`) |
| POST | `/v1/payments/{id}/confirm` | Confirmar con OTP, llama bank.initiate_c2p, transita a `succeeded`/`failed` |
| GET | `/v1/payments/{id}` | Detalle |
| GET | `/v1/payments?limit=20&cursor=<b64>` | Listado paginado (cursor compuesto created_at + id) |

### Webhook endpoints

| Método | Path | Descripción |
|---|---|---|
| POST | `/v1/webhook_endpoints` | Registrar URL receptora. **Devuelve `signing_secret` plaintext UNA SOLA VEZ** |
| GET | `/v1/webhook_endpoints?limit=&cursor=` | Listado paginado |

## Webhooks salientes

### Eventos emitidos

- `webhook_endpoint.created`
- `payment_intent.created`
- `payment_intent.succeeded`
- `payment_intent.failed`

### Firma HMAC-SHA256 (estilo Stripe)

Cada request lleva header:

```
X-Pasarela-Signature: t=<unix_timestamp>,v1=<sha256_hex>
X-Pasarela-Event-Type: payment_intent.succeeded
```

Donde `v1 = HMAC_SHA256(signing_secret, f"{t}.{body}")`. El receptor debe:

1. Parsear `t` y `v1` del header.
2. Recalcular HMAC sobre `{t}.{body}` con el secret guardado.
3. Comparar con `hmac.compare_digest`.
4. Rechazar si `t` es muy viejo (mitiga replay).

Ejemplo Python receptor:

```python
expected = hmac.new(secret.encode(), f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, v1)
```

### Outbox pattern

`WebhookService.record_attempts` inserta filas en `webhook_attempts` **dentro de la misma transacción** del cambio de estado. Tras el commit, el handler agenda `BackgroundTasks.add_task(WebhookService.dispatch, attempt_id)`. Si la TX falla → 0 webhooks enviados. Atómico.

### Filtro de eventos

`enabled_events` en `webhook_endpoints` soporta:

- `["*"]` — todos
- `["payment_intent.succeeded"]` — exacto
- `["payment_intent.*"]` — wildcard por prefijo

## Bank Adapter (Strategy Pattern)

`BankAdapter` (ABC) define:

```python
async def initiate_c2p(self, req: C2PRequest) -> C2PResponse
async def query_operation(self, ref: str) -> OperationStatus
async def list_supported_banks(self) -> list[dict]
@property
def supports_aggregator_mode(self) -> bool
```

Implementaciones:

- `MockBankAdapter` — simula latencia 1-3s, 80% éxito aleatorio, 20% `ValueError("fondos_insuficientes")`. Útil para dev/staging.
- `BancaribeAdapter` — stub. Llamada real pendiente Día 7.

Selección actual: `get_bank_adapter()` en `app/api/deps.py`. Cambiar ahí para swap.

## Migraciones

```bash
# Crear nueva
alembic revision --autogenerate -m "descripcion"

# Aplicar
alembic upgrade head

# Verificar diff
alembic check

# Rollback
alembic downgrade -1
```

`alembic/env.py` lee `DATABASE_URL` y maneja Supabase/Neon SSL automáticamente.

## Testing manual E2E

```bash
KEY="sk_test_dev_pasarela_001"
H="Authorization: Bearer $KEY"
BASE="http://localhost:8000"

# Health
curl -s $BASE/health

# Crear webhook endpoint (guarda signing_secret de la respuesta)
curl -s -X POST $BASE/v1/webhook_endpoints -H "$H" -H "Content-Type: application/json" \
  -d '{"url":"https://webhook.site/<tu-uuid>","enabled_events":["*"]}'

# Crear payment intent
PI=$(curl -s -X POST $BASE/v1/payments -H "$H" -H "Content-Type: application/json" \
  -d '{"amount":50000,"currency":"VES","customer_phone":"04141234567","customer_id_document":"V12345678","customer_bank_code":"0114"}')
ID=$(echo "$PI" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Confirmar (dispara webhook payment_intent.succeeded o .failed)
curl -s -X POST $BASE/v1/payments/$ID/confirm -H "$H" -H "Content-Type: application/json" \
  -d '{"client_secret":"stub","otp":"1234"}'

# Listado paginado
curl -s "$BASE/v1/payments?limit=5" -H "$H"
```

Verifica recepción del webhook en `webhook.site` (o ngrok hacia receiver local).

## Deploy

### Producción: Koyeb + Supabase (free tier)

**Postgres**: Supabase project, usar **Transaction pooler** (puerto 6543).

```
postgresql://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:6543/postgres
```

El código detecta puerto 6543 y desactiva prepared statements de asyncpg automáticamente (compatibilidad PgBouncer transaction mode).

**Aplicar migraciones a Supabase** desde local:

```bash
DATABASE_URL="postgresql://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:6543/postgres" \
  alembic upgrade head
```

**Koyeb**: crear servicio desde GitHub repo, builder Dockerfile. Env vars:

```
DATABASE_URL=postgresql://postgres.<ref>:<pass>@aws-1-<region>.pooler.supabase.com:6543/postgres
API_KEY_PEPPER=<openssl rand -hex 32>
SENTRY_DSN=<DSN sentry, opcional>
ENVIRONMENT=production
PORT=8000
```

Health check: `GET /health` puerto 8000.

El `CMD` del Dockerfile ejecuta `alembic upgrade head && uvicorn`, asegurando migraciones aplicadas al boot.

### Build Docker local

```bash
docker build -t pasarela:test .
docker run --rm --network host \
  -e DATABASE_URL="..." \
  -e API_KEY_PEPPER="..." \
  -e ENVIRONMENT="staging" \
  -e PORT="8000" \
  pasarela:test
```

## Notas técnicas

- **Datetimes**: las columnas usan `TIMESTAMP WITHOUT TIME ZONE`. Código usa `datetime.utcnow()` (naive UTC). Migración futura a `TIMESTAMPTZ` recomendada.
- **`signing_secret_encrypted`**: actualmente guarda plaintext bytes. TODO: cifrar con Fernet/KMS antes de prod real.
- **Dev API key seed**: solo se ejecuta cuando `ENVIRONMENT != production`. En prod debes crear keys reales vía endpoint admin (pendiente).
- **Webhook retries**: 1 solo intento por ahora. Worker durable para reintentos exponenciales: pendiente.
- **`client_secret`** en confirm: recibido pero no validado. Pendiente: persistir hash al crear, comparar al confirm.

## Roadmap

Ver `07-roadmap.md` y `PLAN_DIARIO.md`.

## Documentación complementaria

- `01-vision-tecnica.md` — visión técnica
- `02-arquitectura.md` — arquitectura
- `03-modelo-datos.md` — modelo de datos
- `04-api-spec.md` — spec API detallada
- `05-flujo-c2p.md` — flujo C2P paso a paso
- `06-seguridad.md` — modelo de seguridad
- `07-roadmap.md` — roadmap
