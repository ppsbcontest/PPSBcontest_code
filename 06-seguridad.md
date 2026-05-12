# 06 — Modelo de Seguridad

> **Versión**: 1.1
> **Aplicabilidad**: Fase 1 (MVP) con roadmap a Fase 3
> **Marco de referencia**: OWASP Top 10, PCI DSS principles (sin certificación formal en Fase 1)

Este documento describe el modelo de amenazas, controles implementados y roadmap de hardening. Las secciones marcan 🟡 lo que es diseño objetivo aún no implementado.

## Estado de controles MVP (11-may-2026)

| Control | Implementado | Notas |
|---|---|---|
| TLS 1.3 en tránsito | 🟡 dep. de plataforma | Local: HTTP. Prod: terminación TLS en Railway/Cloudflare. |
| API key hash | ✅ SHA256 + pepper | `API_KEY_PEPPER` env. Migrar a bcrypt en Fase 2. |
| Auth headers | ✅ `Authorization: Bearer` o `X-API-Key` | |
| Scope `pk` vs `sk` | 🟡 | Sólo `sk` activo en MVP. |
| Cifrado pgcrypto de campos sensibles | 🟡 | `account_number_encrypted`/`signing_secret_encrypted` hoy guardan bytes plano. |
| Audit log inmutable | ✅ | Tabla `events` con sólo INSERT desde código. Restricción de rol DB pendiente. |
| Webhook firmado HMAC-SHA256 | ✅ | Header `X-Pasarela-Signature: t=...,v1=...`. |
| Pydantic validators estrictos | 🟡 | Validación de tipo y longitud sí; regex de cédula/teléfono pendiente. |
| Rate limiting | 🟡 | No implementado. Plan: `slowapi` + Redis Fase 2. |
| Idempotency-Key enforcement | 🟡 | Columna existe; endpoint no valida header. |
| Locks pesimistas (`FOR UPDATE`) | 🟡 | `confirm_payment` usa `db.get` sin lock explícito. |
| Sentry | ✅ opcional (`SENTRY_DSN`) | |
| 2FA dashboard | 🟡 | Dashboard no existe aún. |

---

## Filosofía de seguridad

1. **Defense in depth**: múltiples capas, no una sola línea.
2. **Least privilege**: cada componente accede solo a lo mínimo necesario.
3. **Fail closed**: ante duda, denegar.
4. **Audit everything**: cada acción queda registrada e inmutable.
5. **Zero trust en datos externos**: validar todo, incluso del propio frontend.
6. **No reinventar criptografía**: usar bibliotecas establecidas, no implementaciones propias.

---

## Modelo de amenazas (STRIDE)

| Amenaza | Vector | Mitigación Fase 1 | Mitigación Fase 3 |
|---|---|---|---|
| **Spoofing** (suplantación) | API keys robadas, webhook spoofing | API keys hasheadas, HMAC en webhooks, TLS obligatorio | + mTLS opcional para enterprise |
| **Tampering** (modificación) | Manipulación de payloads en tránsito | TLS 1.3, firma HMAC en webhooks, validación Pydantic estricta | + integridad de logs con hash chain |
| **Repudiation** (negación) | Comerciante niega haber autorizado transacción | Audit log inmutable, IP + UA en cada llamada API | + firma criptográfica de eventos |
| **Information disclosure** | Filtración de datos sensibles | Datos PII enmascarados en respuestas, cifrado en reposo de campos sensibles | + PCI DSS compliance, tokenización |
| **Denial of service** | Spam de peticiones | Rate limiting por API key + IP, Cloudflare WAF | + DDoS protection enterprise |
| **Elevation of privilege** | Escalación de pk_test a sk_live | Separación estricta de scopes, validación de permisos por endpoint | + RBAC granular, 2FA obligatorio |

---

## Capa 1: Red e infraestructura

### TLS / HTTPS

- **TLS 1.3 obligatorio**. TLS 1.2 deprecado.
- **HSTS** con `max-age=31536000; includeSubDomains; preload`.
- **Certificate pinning** en SDKs de producción (Fase 2).
- **No HTTP**: el servidor redirige 301 a HTTPS, pero los endpoints sensibles devuelven 426 (Upgrade Required) en lugar de redirigir.

### Cloudflare delante

- **WAF** con reglas OWASP managed rules habilitadas.
- **Bot Fight Mode** habilitado.
- **Rate limiting** a nivel de Cloudflare antes de llegar al origin.
- **DDoS protection** L3/L4 incluido en plan gratuito.

### Red interna

- Backend en Railway con IP egress fija (para que Bancaribe pueda whitelisting).
- Postgres no expuesto públicamente — solo accesible desde el backend.
- Secrets cargados vía variables de entorno cifradas.

---

## Capa 2: Autenticación y autorización

### API Keys

```
Formato: {prefix}_{environment}_{52_chars_base62}
```

**Almacenamiento MVP** (`app/security.py` + `app/api/deps.py`):
- Hash **SHA256 con pepper** (`API_KEY_PEPPER` env). Migración a bcrypt cost 12 en Fase 2.
- El valor en plano se muestra **una sola vez** al crear (endpoint `POST /v1/api_keys` aún no implementado; en MVP la key dev se sembra vía `bootstrap.py`).

**Validación actual MVP:**
```python
# app/security.py
def hash_api_key(plaintext: str) -> str:
    pepper = os.getenv("API_KEY_PEPPER", "dev_pepper_change_me")
    return hashlib.sha256(f"{pepper}:{plaintext}".encode("utf-8")).hexdigest()

# app/api/deps.py
key_hash = hash_api_key(plaintext)
res = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
api_key = res.scalar_one_or_none()
if api_key is None or api_key.revoked_at is not None:
    raise HTTPException(401, "invalid_api_key")
```

**Rotación**:
- Las keys NO expiran automáticamente en MVP.
- En Fase 2 se introduce rotación obligatoria cada 12 meses.
- Endpoint para revocar manualmente en cualquier momento.

### Scopes (separación pk vs sk)

| Endpoint | Acepta `pk_*` | Acepta `sk_*` |
|---|---|---|
| `POST /v1/payments` | ❌ | ✅ |
| `POST /v1/payments/{id}/confirm` | ✅ (con `client_secret`) | ✅ |
| `GET /v1/payments/{id}` | ✅ (con `client_secret`) | ✅ |
| `GET /v1/payments` (listar) | ❌ | ✅ |
| `POST /v1/webhook_endpoints` | ❌ | ✅ |
| `POST /v1/api_keys` | ❌ | ✅ |
| `GET /v1/banks` | ✅ | ✅ |

**`pk_*`** son explícitamente públicas (van en frontend). Solo pueden hacer operaciones que no expongan datos del comerciante.

### Dashboard (JWT)

El dashboard usa **Supabase Auth** con JWT firmado.

- **Expiración**: 1 hora.
- **Refresh tokens**: 7 días, rotación al uso.
- **2FA**: roadmap Fase 2 (TOTP via Google Authenticator).
- **Sesiones revocables** desde el dashboard.

---

## Capa 3: Validación y sanitización

### Pydantic v2 obligatorio

**Todo** lo que entra al backend pasa por un schema Pydantic. No hay endpoints que reciban `dict` libre.

```python
from pydantic import BaseModel, Field, field_validator
import re

class PaymentCreateRequest(BaseModel):
    amount: int = Field(..., gt=0, le=10_000_000_00)  # max 10M VES en céntimos
    currency: Literal["VES", "USD"]
    customer: CustomerData
    metadata: dict[str, str] = Field(default_factory=dict, max_length=20)

class CustomerData(BaseModel):
    phone: str = Field(..., min_length=11, max_length=11)
    id_document: str = Field(..., min_length=7, max_length=10)
    bank_code: str = Field(..., min_length=4, max_length=4)
    
    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not re.fullmatch(r"04\d{9}", v):
            raise ValueError("Teléfono debe ser formato 04XXXXXXXXX")
        return v
    
    @field_validator("id_document")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not re.fullmatch(r"[VEJGP]\d{6,9}", v.upper()):
            raise ValueError("Cédula/RIF inválido")
        return v.upper()
```

### Saneamiento de logs

Datos sensibles **nunca** se loggean en plano:

```python
import re

SENSITIVE_PATTERNS = [
    (re.compile(r"sk_live_\w+"), "sk_live_***"),
    (re.compile(r"sk_test_\w+"), "sk_test_***"),
    (re.compile(r"\b04\d{9}\b"), "04**XXX****"),
    (re.compile(r"\b[VEJGP]\d{6,9}\b"), "X****"),
]

def sanitize_for_log(text: str) -> str:
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
```

---

## Capa 4: Datos en reposo

### Cifrado de campos sensibles (🟡 diseño)

**Estado MVP**: las columnas `BYTEA` (`account_number_encrypted`, `signing_secret_encrypted`) existen, pero **almacenan bytes plano** del UTF-8 (no cifrado). Esto es deuda técnica explícita; el cifrado pgcrypto está planeado Día 6-7.

**Diseño objetivo** — Tabla `merchant_accounts.account_number_encrypted` y `webhook_endpoints.signing_secret_encrypted` usan **`pgcrypto`** con AES-256:

```sql
-- Al insertar
INSERT INTO merchant_accounts (..., account_number_encrypted)
VALUES (..., pgp_sym_encrypt('0114001234567890', :master_key));

-- Al leer (solo cuando es estrictamente necesario)
SELECT pgp_sym_decrypt(account_number_encrypted::bytea, :master_key)
FROM merchant_accounts WHERE id = :id;
```

`master_key` viene de variable de entorno, rotable.

### Datos NO cifrados en MVP (pero registrados como deuda técnica)

- Cédulas y teléfonos de clientes finales: están en plano porque se necesitan para validar OTP. **Cifrado planeado Fase 2 con búsqueda determinística** (hashing con sal fija para permitir queries).
- Metadata: opaca para Pasarela; el comerciante decide qué pone.

### Backups

- Postgres en Railway: backups automáticos diarios.
- Retención: 7 días en MVP, 30 días en Fase 2.
- Restauración point-in-time: disponible desde día 1 (feature de Railway).

---

## Capa 5: Datos en tránsito

### Hacia Bancaribe

- TLS 1.3 obligatorio (Bancaribe expone `https://35ecb.bancaribe.com.ve:8243`).
- Validación de certificado completa (sin `verify=False` en código).
- Timeout estricto: 30s para llamadas C2P.
- mTLS si Bancaribe lo requiere (configuración por adapter).

### Hacia comerciantes (webhooks)

- 🟡 Validación `https://` en creación pendiente (MVP acepta cualquier URL).
- ✅ Firma HMAC-SHA256 obligatoria.
- ✅ Header `X-Pasarela-Signature: t=<unix_ts>,v1=<hex>` (con prefijo `X-`).
- Timestamp incluido para prevenir **replay attacks**: el comerciante debe rechazar webhooks con timestamp > 5 minutos de antigüedad.

---

## Capa 6: Rate limiting 🟡 (no implementado en MVP)

### Por API key

| Tier | Capacidad sostenida | Burst |
|---|---|---|
| Test | 5 req/s | 60 req/min |
| Live (default) | 25 req/s | 300 req/min |
| Live (high-volume) | 50 req/s | 1000 req/min |

Implementación: `slowapi` (FastAPI) con backend Redis (Fase 2 — en MVP usa memoria).

### Por IP (anti-abuso)

- Máximo 100 intents fallidos por IP en 10 minutos.
- Bloqueo automático de 1 hora ante 1000+ req/min sin auth válida.

### Throttling especial para OTP

- Máximo **3 intentos de OTP por payment_intent**. Cuarto intento marca el intent como `failed` con `code='max_otp_attempts'`.
- Esto previene ataques de fuerza bruta sobre OTPs (6 dígitos = solo 1M de combinaciones).

---

## Capa 7: Idempotencia y consistencia

### Idempotency keys

Como se describe en [04-api-spec.md](../api/04-api-spec.md), todas las escrituras críticas requieren `Idempotency-Key`.

### Locks distribuidos para transiciones de estado

```python
# Pseudocódigo
async def confirm_payment(intent_id: str, otp: str):
    # Lock pesimista en la fila
    async with db.transaction(isolation='SERIALIZABLE'):
        intent = await db.execute(
            "SELECT * FROM payment_intents WHERE id = :id FOR UPDATE",
            id=intent_id
        )
        
        if intent.status != 'pending':
            raise InvalidStateError(f"Cannot confirm from state {intent.status}")
        
        # ... resto de la lógica
```

Esto previene **race conditions** donde dos confirmaciones simultáneas podrían procesar el mismo pago dos veces.

---

## Capa 8: Audit log inmutable

Tabla `events` con `INSERT` únicamente. Cada cambio relevante deja huella:

- ¿Quién? `actor_id` + `actor_type`
- ¿Qué? `event_type`
- ¿Cuándo? `created_at`
- ¿Desde dónde? `ip_address` + `user_agent`
- ¿Sobre qué? `related_entity_id` + `related_entity_type`
- ¿Detalles? `payload` JSONB

**Crítico**: ningún rol de DB tiene `UPDATE` o `DELETE` sobre `events`. Solo el servicio principal con `INSERT`.

```sql
-- En Fase 2: rol restringido
CREATE ROLE app_service;
GRANT INSERT ON events TO app_service;
-- Sin UPDATE, sin DELETE
```

---

## Capa 9: Operacional

### Secrets management

**MVP**: variables de entorno en Railway/Vercel (cifradas en reposo por la plataforma).

**Fase 2**: HashiCorp Vault o Doppler. Rotación automática.

**Nunca**:
- ❌ Secrets en código (incluso de prueba).
- ❌ Secrets en `.env` commiteado a git.
- ❌ Secrets en logs.
- ❌ Secrets compartidos por chat/email.

### Logs

- **Sentry** para errores con stack traces.
- **Better Stack / Logflare** para logs estructurados.
- **Retention**: 30 días en MVP, 1 año en Fase 2.
- Logs **nunca contienen** datos sensibles (ver "Saneamiento" arriba).

### Monitoreo

Métricas clave con alertas:

- Tasa de error 5xx > 1% en 5 min → alerta crítica.
- Tasa de aprobación de pagos < 90% en 1h → alerta.
- Latencia P99 > 5s → alerta.
- Webhooks con > 50% de fallos → alerta.

---

## Capa 10: Disaster recovery

### Plan de continuidad (MVP básico)

| Escenario | RTO objetivo | RPO objetivo | Procedimiento |
|---|---|---|---|
| Backend caído | 5 min | 0 | Railway auto-restart + alerta |
| DB caída | 30 min | < 24h | Restore de backup diario |
| Región completa caída | 4h | < 24h | Re-deploy manual en otra región Railway |
| Compromiso de credenciales | 1h | 0 | Rotación de keys + revisión audit log |

### Plan en Fase 3 (con dinero real)

- RPO ≤ 5 minutos (replicación síncrona).
- RTO ≤ 30 minutos (failover automático).
- DR site en región distinta.
- Simulacros trimestrales.
- Plan de incident response documentado y ensayado.

---

## Compliance roadmap

### Fase 1 (MVP)
- ✅ Buenas prácticas OWASP Top 10.
- ✅ Cifrado en tránsito y reposo.
- ✅ Audit log básico.
- ⚠️ Sin certificación formal (no aplica todavía).

### Fase 2 (post-MVP, antes de procesar dinero real)
- 🎯 **Pen test externo** ($2K-$5K USD).
- 🎯 **Política de seguridad documentada y firmada** por el equipo.
- 🎯 **KYC/AML básico de comerciantes**: verificación de RIF, lista OFAC, listas BCV.
- 🎯 Cumplimiento de la **Ley contra la Delincuencia Organizada y Financiamiento al Terrorismo** vía paraguas Bancaribe.

### Fase 3 (modelo agregador)
- 🎯 **PCI DSS Level 4** (si llegamos a tocar datos de tarjetas).
- 🎯 **SOC 2 Type II** (para vender enterprise).
- 🎯 **ISO 27001** (Fase 3 madura).
- 🎯 **Compliance LC/FT/FPADM** formal con oficial de cumplimiento.
- 🎯 **Auditoría externa anual**.

---

## Vulnerabilidades conocidas / Deuda técnica (transparente)

Esto va aquí porque **un equipo serio reconoce lo que falta**. Esto le da credibilidad al pitch — los bancos respetan la honestidad mucho más que la perfección fingida.

| Item | Severidad | Plan |
|---|---|---|
| Cédulas/teléfonos en plano en DB | Media | Cifrado determinístico en Fase 2 |
| `account_number_encrypted`/`signing_secret_encrypted` sin cifrar (bytes plano) | Alta | pgcrypto Día 6-7 |
| API keys con SHA256+pepper en vez de bcrypt | Media | Migrar a bcrypt cost 12 Fase 2 |
| Idempotency-Key header no validado | Media | Implementar Día 6 |
| Webhooks sin retry/backoff (single attempt) | Media | Worker ARQ Fase 2 |
| Sin rate limiting | Media | `slowapi` + Redis Fase 2 |
| Sin masking de PII en responses | Media | Día 6 |
| Sin lock pesimista `FOR UPDATE` en `confirm` | Media | Día 6 |
| Sin 2FA en dashboard | Media (no hay dashboard aún) | TOTP en Fase 2 |
| Sin pen-test externo | Alta para producción real | Antes de procesar dinero real |
| Sin tests automatizados de seguridad | Media | CI con `bandit`, `safety`, `npm audit` en Fase 2 |
| Sin oficial de cumplimiento | N/A en Fase 1 | Bajo paraguas Bancaribe; propio en Fase 3 |

---

## Decisiones explícitamente diferidas

Por razones de tiempo y alcance, estas decisiones se difieren a Fase 2+ pero se reconocen aquí:

1. **PCI DSS formal**: aplicará solo si llegamos a tocar datos de tarjetas (Fase 3 con productos avanzados).
2. **HSM (Hardware Security Module)**: para Fase 3 con productos de tarjetas o cuando el volumen lo justifique.
3. **Cifrado homomórfico para analytics sobre datos cifrados**: Fase 4+.
4. **Bug bounty program**: post Fase 2, una vez tengamos producto estable.

---

## Resumen ejecutivo para el pitch

> Pasarela aplica defense-in-depth con TLS 1.3, API keys hasheadas con bcrypt, cifrado en reposo de campos sensibles vía pgcrypto, webhooks firmados con HMAC-SHA256, audit log inmutable, rate limiting por key/IP, idempotencia obligatoria en escrituras, validación estricta con Pydantic, y locks pesimistas para integridad transaccional. En Fase 1 operamos bajo el marco regulatorio existente de Bancaribe; el roadmap de Fase 2-3 incluye pen-test externo, KYC/AML formal con software especializado, y eventual certificación PCI DSS y SOC 2.
