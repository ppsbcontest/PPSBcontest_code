# Tareas para implementación — Rutiva MVP (Día 3-4)

## Contexto del proyecto

Estoy construyendo **Rutiva**, una API de pagos C2P para Venezuela inspirada en Stripe. Aplico al concurso Shark Bank Bancaribe (cierre 17 de mayo). El backend está en Python 3.12 + FastAPI + SQLAlchemy 2.0 async + Pydantic v2 + PostgreSQL 16. Posicionamiento: facilitador puro sobre Open Banking de Bancaribe en Fase 1, con visión de evolución a multi-banco (Fase 2) y agregador apadrinado (Fase 3).

La arquitectura actual está documentada en `RESUMEN_TECNICO.md` en el raíz del repo. Léelo completo antes de empezar para entender:
- Estructura de directorios (modelos por dominio, no por capa).
- Outbox pattern para webhooks (record_attempts en misma TX del cambio de estado).
- API keys hasheadas con `sha256(pepper:plaintext)`.
- State machine de payment_intents: `created → succeeded | failed`.
- Lógica especial de conexión a Supabase (PgBouncer 6543, asyncpg, statement_cache_size=0).

**Nota sobre naming**: el producto se llama **Rutiva**. Aplica este nombre en:
- Headers HTTP custom: `X-Rutiva-Signature`, `X-Rutiva-Event-Type` (renombrar desde `X-Pasarela-*` si existen).
- Título de la API FastAPI (`title="Rutiva API"`).
- Mensajes visibles al usuario, descripciones OpenAPI, docstrings.
- Contact info y URLs placeholder (usar `rutiva.dev` como dominio placeholder).
- **NO renombres** el paquete Python `app/` ni rutas internas — es refactor innecesario ahora.
- **NO renombres** prefijos de IDs existentes (`pi_`, `sk_test_`, `pk_test_`, `whsec_`, etc.) — esos son convención técnica neutral.

**Restricción global**: NO refactorizar código existente que ya funcione. NO agregar dependencias nuevas sin justificación. NO cambiar la arquitectura por preferencias personales. Solo implementar lo que pido, lo más cercano posible al estilo del código existente.

---

## Tareas a implementar, en este orden

### Tarea 0 (rápida): Aplicar el nombre Rutiva donde corresponda

**Por qué importa**: consistencia de marca antes de empezar features nuevas. Si hay cualquier referencia a "Pasarela" como nombre del producto (no como concepto técnico), reemplazar por "Rutiva".

**Implementación**:

1. Buscar en todo el repo (excluyendo `.venv`, `node_modules`, `.git`, archivos `.md` de docs antiguos):
   - Strings `"Pasarela"` que sean nombre del producto → `"Rutiva"`.
   - Headers `X-Pasarela-*` → `X-Rutiva-*` en código que los **emite** y código que los **lee/valida**.
   - Title/description de FastAPI app.
   - Mensajes de log que mencionen el producto.

2. NO tocar:
   - El nombre del paquete Python `app/`.
   - Los prefijos de IDs (`pi_`, `sk_test_`, etc.).
   - Comentarios técnicos que usen "pasarela" como sustantivo común ("la pasarela hace X") — esos están bien.
   - Archivos `.md` de documentación interna salvo `README.md` si lo encuentras.

3. Si hay constantes globales (`APP_NAME`, `PRODUCT_NAME`, etc.), actualízalas en su lugar central.

**Criterio de aceptación**: `grep -ri "pasarela" --include="*.py"` no devuelve referencias al producto (solo al concepto). Header `X-Rutiva-Signature` aparece en webhook dispatcher y se valida igual.

---

### Tarea 1: Idempotency-Key obligatorio en POST /v1/payments

**Por qué importa**: sin idempotencia, un retry de red puede crear dos `payment_intents` y cobrar dos veces al cliente. Es requisito básico para una pasarela seria.

**Implementación**:

1. Agregar migración Alembic que añade a `payment_intents`:
   - Columna `idempotency_key VARCHAR(100) NULL`.
   - Índice único compuesto `(merchant_id, idempotency_key) WHERE idempotency_key IS NOT NULL`.

2. En el endpoint `POST /v1/payments`:
   - Leer header `Idempotency-Key` (opcional pero recomendado en docs).
   - Si llega y ya existe un `payment_intent` con `(merchant_id, idempotency_key)`:
     - Devolver el `payment_intent` existente con HTTP 200 (no 201) y el body completo idéntico a la respuesta original.
     - **No** procesar nada nuevo.
     - **Importante**: en este caso de replay, NO devolver el `client_secret` (ver Tarea 2) ya que ese solo se entrega una vez.
   - Si llega y no existe: persistirlo junto al payment_intent.
   - Si no llega: comportamiento actual (sin idempotencia).

3. Validación del header: longitud máxima 100 chars, regex `^[A-Za-z0-9_\-:.]+$`.

4. Documentar el comportamiento en docstring del endpoint.

**Criterio de aceptación**: dos llamadas con el mismo `Idempotency-Key` y body idéntico devuelven el mismo `payment_intent`. Con body distinto pero misma key: devolver error 422 "idempotency_key_mismatch".

---

### Tarea 2: client_secret para autorización de Widget en confirm (Opción B confirmada)

**Por qué importa**: el flujo Stripe-style donde el Widget en el frontend puede confirmar pagos sin exponer la `sk_`. Es el patrón estándar de la industria y lo esperado por developers que conozcan Stripe/Mercado Pago. Esto es DX-first puro y alinea con la propuesta de valor pública de Rutiva.

**Implementación**:

1. Agregar migración Alembic que añade a `payment_intents`:
   - Columna `client_secret_hash VARCHAR(64) NOT NULL` (sha256 hex).

2. En la creación del payment_intent (`POST /v1/payments`):
   - Generar `client_secret = f"{external_id}_secret_{secrets.token_urlsafe(24)}"`.
   - Guardar `client_secret_hash = sha256(client_secret.encode()).hexdigest()` en la DB.
   - Devolver el `client_secret` (plaintext) **una sola vez** en la respuesta del create.
   - **Nunca** devolverlo en `GET /v1/payments/{id}` ni en listados.
   - **Nunca** devolverlo en replays de idempotencia (ver Tarea 1).

3. En `POST /v1/payments/{id}/confirm`, aceptar dos modos de autenticación:
   - **Modo A (backend, ya existe)**: `Authorization: Bearer sk_xxx` + body `{"otp": "..."}`.
   - **Modo B (widget, nuevo)**: sin `Authorization` header, body `{"client_secret": "...", "otp": "..."}`.
   - Si llega `client_secret` en body: 
     - Verificar que el `pi_xxx` del path corresponda al prefijo del `client_secret` (split por `_secret_`).
     - Calcular `sha256(client_secret).hexdigest()` y compararlo con `payment_intent.client_secret_hash` usando `hmac.compare_digest` (timing-safe).
     - Si valida, permitir el confirm sin requerir API key. El `merchant_id` se obtiene del payment_intent encontrado.
   - Si llegan **ambos** (sk_ y client_secret): preferir sk_ (modo backend), ignorar client_secret silenciosamente.
   - Si no llega ninguno: 401 "authentication_required".
   - Si el `client_secret` es inválido o no corresponde al `pi_xxx`: 403 "invalid_client_secret".

4. CORS: el endpoint confirm debe aceptar requests desde orígenes externos (el Widget vivirá en sitios de comerciantes). Configurar CORS específicamente para `POST /v1/payments/{id}/confirm` y `OPTIONS` con `allow_origins=["*"]`, `allow_methods=["POST", "OPTIONS"]`, `allow_headers=["Content-Type"]`. El resto del API mantiene origins restringidos a los dominios de Rutiva.

5. Crear un schema Pydantic separado para el response del create que SÍ incluye `client_secret`, vs el schema general de payment_intent que NO lo incluye. Algo como:
   - `PaymentIntentResponse` (sin client_secret) — usado en GET, list.
   - `PaymentIntentCreateResponse(PaymentIntentResponse)` (con client_secret) — solo en POST create.

**Criterio de aceptación**: 
- Crear un payment_intent con `Bearer sk_xxx` devuelve `client_secret` en la respuesta.
- Confirmar ese intent con solo `{"client_secret": "...", "otp": "111111"}` (sin Authorization header) funciona y devuelve 200.
- Confirmar con un `client_secret` que no corresponde a ese `pi_xxx` devuelve 403 "invalid_client_secret".
- `GET /v1/payments/{id}` no incluye `client_secret` ni `client_secret_hash` en el response.
- `GET /v1/payments` (listado) no los incluye en ningún elemento.
- Preflight OPTIONS al confirm desde un origen arbitrario funciona.

---

### Tarea 3: Validadores Pydantic para datos venezolanos

**Por qué importa**: si recibimos teléfonos o cédulas mal formateados, el banco rechaza con errores genéricos y el comerciante no entiende qué pasó. Validar en el borde da errores claros.

**Implementación**:

1. En el schema Pydantic del request de `POST /v1/payments` (probablemente `app/schemas/payment.py`), agregar field_validators a `CustomerData` (o el nombre que tengas):

   - `customer_phone`: regex `^04\d{9}$`. Mensaje de error: "Teléfono debe tener formato 04XXXXXXXXX (11 dígitos)".
   - `customer_id_document`: regex `^[VEJGP]\d{6,9}$` después de hacer `.upper().strip()`. Mensaje: "Cédula/RIF debe ser formato V/E/J/G/P seguido de 6-9 dígitos".
   - `customer_bank_code`: regex `^\d{4}$`. Adicionalmente, validar contra lista de bancos soportados (ver Tarea 4). Mensaje: "Código de banco inválido o no soportado".

2. En el schema Pydantic de `Merchant` (si existe endpoint admin de creación), agregar:
   - `rif`: regex `^[VEJGP]-\d{8}-\d$` después de `.upper().strip()`. Mensaje: "RIF debe tener formato X-XXXXXXXX-X".

3. Para el `amount`:
   - Asegurar que es `int >= 1` (en céntimos).
   - Máximo razonable: `1_000_000_000_00` (mil millones en céntimos). Mensaje: "Monto fuera del rango permitido".

**Criterio de aceptación**: llamadas con datos mal formateados devuelven 422 con mensajes claros en español que el comerciante puede mostrar al cliente final.

---

### Tarea 4: Endpoint GET /v1/banks

**Por qué importa**: el Widget necesita poblar el dropdown de "banco del cliente". Sin este endpoint, los developers tienen que hardcodear la lista. También es necesario para la validación de la Tarea 3.

**Implementación**:

1. Crear `app/api/v1/banks.py` con endpoint `GET /v1/banks`.

2. No requiere autenticación (es información pública). CORS abierto (`allow_origins=["*"]`) ya que el Widget lo consume.

3. Llama a `bank_adapter.list_supported_banks()` (el MockBankAdapter ya tiene esta lista en su código actual; usar esa).

4. Response shape:
```json
   {
     "object": "list",
     "data": [
       { "code": "0102", "name": "Banco de Venezuela" },
       { "code": "0105", "name": "Banco Mercantil" },
       { "code": "0114", "name": "Bancaribe" }
     ]
   }
```

5. Cache la lista en memoria por 1 hora con `functools.lru_cache` o variable de módulo con timestamp (la lista cambia muy raramente). Como `list_supported_banks` es async, hacé un wrapper o cache manual.

6. Registrar el router en `app/main.py`.

**Criterio de aceptación**: `curl http://localhost:8000/v1/banks` devuelve la lista de bancos venezolanos sin requerir auth. Llamadas repetidas en menos de 1h no llaman al adapter dos veces.

---

### Tarea 5: Estado canceled + expiración automática

**Por qué importa**: payment_intents creados que nunca se confirman quedan en estado `created` para siempre, ensuciando métricas y dashboard.

**Implementación**:

1. Migración Alembic:
   - Agregar valor `canceled` permitido al status (si es CHECK constraint, modificarlo; si es columna libre, solo documentar).
   - Agregar columna `expires_at TIMESTAMP NOT NULL DEFAULT (now() + interval '15 minutes')` a `payment_intents`. Backfill: para filas existentes, `expires_at = created_at + interval '15 minutes'`.
   - Agregar columna `canceled_at TIMESTAMP NULL`.

2. En la creación de payment_intent: setear `expires_at = created_at + timedelta(minutes=15)`.

3. Crear nuevo endpoint `POST /v1/payments/{id}/cancel`:
   - Requiere `Bearer sk_xxx` (no aceptar `client_secret` para cancelar — solo el comerciante puede cancelar desde su backend).
   - Solo permite cancelar si `status == "created"`.
   - Setea `status = "canceled"`, `canceled_at = now()`.
   - Emite evento `payment_intent.canceled` + webhook attempts (mismo patrón outbox).
   - Devuelve el payment_intent actualizado.

4. En `POST /v1/payments/{id}/confirm`: si `now() > expires_at`, rechazar con 400 "payment_expired" y opcionalmente auto-cancelar (setear `status = "canceled"`, `canceled_at = now()`, emitir evento + webhooks).

5. (Opcional, baja prioridad) Crear un script `scripts/expire_old_intents.py` que pueda correrse manualmente o como cron:
```python
   # Pseudocódigo
   UPDATE payment_intents 
   SET status = 'canceled', canceled_at = now()
   WHERE status = 'created' AND expires_at < now()
   RETURNING id;
   # Para cada id retornado, emitir evento + webhooks.
```
   Documentar que se puede correr como cron job pero no obligatorio para MVP.

**Criterio de aceptación**:
- `POST /v1/payments/{id}/cancel` cancela exitosamente intents en `created`.
- Intentar cancelar un intent ya `succeeded` devuelve 400 "invalid_state".
- Confirmar un intent después de su `expires_at` devuelve 400 "payment_expired".
- Tras cancelación, se emite evento `payment_intent.canceled` y se disparan webhooks suscritos.

---

### Tarea 6: Documentación pública mínima en código (Rutiva-branded)

**Por qué importa**: el repo es público y va a ser parte del pitch a Bancaribe. Los docstrings y openapi descriptions cuentan. Esto soporta directamente la propuesta de valor de "DX-first + transparencia".

**Implementación**:

1. Para cada endpoint público (todos los `/v1/*`), agregar:
   - Docstring claro en español que explique qué hace.
   - `description=...` y `summary=...` en el decorator `@router.post/get`.
   - `responses={...}` documentando los códigos de error principales (400, 401, 404, 422, 500).
   - Ejemplos en el `examples=` de los schemas Pydantic donde tenga sentido (especialmente request/response de payments).

2. En `app/main.py`, ajustar la `FastAPI(...)` instancia:
```python
   app = FastAPI(
       title="Rutiva API",
       description=(
           "API de pagos C2P (Customer-to-Payment) para el ecosistema venezolano. "
           "Rutiva permite a comerciantes aceptar pagos desde cualquier banco "
           "venezolano usando el flujo OTP-bancario estándar, con una experiencia "
           "developer-first inspirada en las mejores prácticas globales.\n\n"
           "**Documentación pública**: https://docs.rutiva.dev\n"
           "**Estado**: MVP funcional. Integración con Bancaribe Open Banking en proceso."
       ),
       version="0.1.0",
       contact={
           "name": "Equipo Rutiva",
           "url": "https://rutiva.dev",
       },
       license_info={"name": "Proprietary"},
   )
```

3. Verificar que `/docs` (Swagger UI) muestra todos los endpoints organizados por tags razonables: `payments`, `webhooks`, `banks`, `meta`.

4. Si tienes un endpoint `GET /` o `GET /health`, asegurar que el response menciona `"service": "rutiva-api"` o similar.

**Criterio de aceptación**: abrir `http://localhost:8000/docs` muestra una documentación que parece profesional, con descripciones claras en español, ejemplos, errores documentados, y el branding de Rutiva consistente.

---

## Tareas que NO debes hacer

- ❌ No implementes retries de webhooks (lo haré después con worker durable).
- ❌ No agregues rate limiting todavía (Cloudflare lo hará en producción).
- ❌ No cambies el hashing de API keys (sha256+pepper está bien justificado).
- ❌ No migres a TIMESTAMPTZ ahora (en roadmap, no urgente).
- ❌ No cifres `signing_secret_encrypted` ni `account_number_encrypted` todavía (en roadmap, BYTEA preserva tipo).
- ❌ No agregues tests unitarios extensivos (solo si no toma mucho tiempo, prefiero avanzar).
- ❌ No agregues Celery/Arq/Redis (BackgroundTasks es suficiente por ahora).
- ❌ No renombres el paquete `app/` a `rutiva/` (deuda innecesaria a 5 días del envío).
- ❌ No renombres prefijos de IDs existentes (`pi_`, `sk_test_`, `whsec_`, etc.).

---

## Orden y entrega

Implementa en el orden listado (0 → 6). Después de cada tarea:

1. Confirma que compila y arranca con `uvicorn app.main:app --reload`.
2. Verifica con un curl o request manual que la nueva funcionalidad anda.
3. Haz commit con mensaje semántico:
   - `chore: rebrand product references to Rutiva`
   - `feat: add idempotency key support to payment intents`
   - `feat: add client_secret for widget-side confirmation`
   - `feat: add Pydantic validators for Venezuelan data formats`
   - `feat: add GET /v1/banks public endpoint`
   - `feat: add canceled state and expiration to payment intents`
   - `docs: improve OpenAPI documentation and Rutiva branding`

4. Antes de pasar a la siguiente, dime brevemente qué hiciste y si encontraste algún issue.

Si en cualquier punto encuentras una decisión arquitectónica importante que no está cubierta acá, **detente y pregúntame**. No tomes decisiones grandes por tu cuenta.

Empieza por la Tarea 0.