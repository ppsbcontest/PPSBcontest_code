# 02 — Arquitectura del Sistema

> **Versión**: 1.1
> **Fecha**: 11 de mayo de 2026
> **Stack actual MVP**: Python 3.12 / FastAPI / PostgreSQL 16 / SQLAlchemy 2.0 async / Alembic / asyncpg / Sentry
> **Stack planeado (post-MVP)**: + Next.js Dashboard, Checkout Widget (TS/Vite), Resend, Supabase Auth

Este documento describe la arquitectura del MVP (Fase 1) usando el modelo C4 (Context, Containers, Components). Las decisiones arquitectónicas tomadas aquí permiten evolución a Fase 2 (multi-banco) y Fase 3 (modelo agregador) sin reescritura.

## Estado del MVP (al 11-may-2026)

Implementado:
- Core API (FastAPI) con endpoints `POST /v1/payments`, `POST /v1/payments/{id}/confirm`, `GET /v1/payments`, `GET /v1/payments/{id}`, `POST /v1/webhook_endpoints`, `GET /v1/webhook_endpoints`, `GET /health`.
- Modelos SQLAlchemy + migración inicial Alembic (`3ca9bba912db_20260511_initial_schema`).
- Bank Adapter (Strategy) con `MockBankAdapter` (activo) y `BancaribeAdapter` (stub `NotImplementedError`).
- Audit log (`events`) append-only via `EventService`.
- Outbox webhook: insert de `webhook_attempts` en misma TX + dispatch via `BackgroundTasks` con firma HMAC-SHA256.
- Auth API key (SHA256+pepper) vía header `Authorization: Bearer` o `X-API-Key`.
- Bootstrap seed de merchant/account/api_key dev en arranque non-prod.
- Sentry init opcional via `SENTRY_DSN`.
- Docker Compose local con Postgres 16; Dockerfile productivo corre `alembic upgrade head` + uvicorn.

Pendiente / no en código aún:
- Dashboard Next.js, Checkout Widget, Tienda demo.
- Endpoints `/v1/banks`, `/v1/api_keys`, `/v1/payments/{id}/cancel`, GET/DELETE de un `webhook_endpoint`.
- `client_secret` real (solo expone payment via API key).
- Enforcement de `Idempotency-Key` (columna existe, header no validado).
- Rate limiting, cifrado pgcrypto de `account_number_encrypted` / `signing_secret_encrypted` (hoy guardados como bytes plano).
- Retry/backoff de webhooks (hoy: un único intento por BackgroundTask).
- Integración real Bancaribe C2P2 (planeada Día 7).

---

## Nivel 1 — Diagrama de Contexto (System Context)

```mermaid
graph TB
    Customer[Cliente Final<br/>persona natural<br/>compra en e-commerce]
    Merchant[Comerciante<br/>SMB con tienda online<br/>cuenta jurídica Bancaribe]
    Developer[Desarrollador<br/>integra Pasarela en sitio<br/>del comerciante]

    Pasarela[Pasarela<br/>capa DX sobre Open Banking<br/>SDK + Dashboard + Widget]

    Bancaribe[Open Banking Bancaribe<br/>C2P2, B2P, ConsultarOperaciones<br/>Transferencia Inmediata]
    Conexus[Red Conexus<br/>liquidación interbancaria<br/>BCV]
    OtherBanks[Otros Bancos<br/>BNC, Mercantil, BVC<br/>donde el cliente final tiene cuenta]

    Customer -->|paga via C2P| Pasarela
    Developer -->|integra SDK| Pasarela
    Merchant -->|configura via Dashboard| Pasarela
    Pasarela -->|registrarPagoC2pApi| Bancaribe
    Bancaribe -->|valida OTP, debita| Conexus
    Conexus -->|orquesta interbancario| OtherBanks
    Conexus -->|liquida a comercio| Bancaribe

    style Pasarela fill:#4F46E5,color:#fff
    style Bancaribe fill:#0EA5E9,color:#fff
```

### Actores

| Actor | Descripción |
|---|---|
| **Cliente Final** | Persona natural con cuenta en cualquier banco venezolano que compra en una tienda integrada con Pasarela. |
| **Comerciante (SMB)** | Pequeña/mediana empresa con cuenta jurídica en Bancaribe. Es el usuario principal del Dashboard. |
| **Desarrollador** | Integrador técnico que conecta Pasarela al e-commerce del comerciante. Puede ser interno o agencia. |
| **Pasarela** | Nuestro sistema. Capa DX entre el comerciante y Bancaribe. |
| **Open Banking Bancaribe** | APIs del banco. Procesa C2P, valida OTP, ejecuta liquidación. |
| **Red Conexus / Otros Bancos** | Infraestructura interbancaria que valida la cuenta del cliente y mueve los fondos. |

---

## Nivel 2 — Diagrama de Containers

```mermaid
graph TB
    subgraph " "
        Browser[Navegador del Cliente Final<br/>checkout integrado]
        MerchSite[Sitio del Comerciante<br/>WooCommerce / custom]
        DashUI[Dashboard del Comerciante<br/>Next.js + shadcn/ui]
    end

    subgraph "Pasarela Platform"
        Widget[Checkout Widget<br/>TypeScript / Vite library<br/>servido vía CDN]
        API[Core API<br/>Python 3.12 + FastAPI<br/>en Railway]
        DB[(PostgreSQL 16<br/>transacciones, eventos<br/>API keys, webhooks)]
        WebhookWorker[Webhook Dispatcher<br/>FastAPI BackgroundTasks<br/>retries con backoff]
    end

    subgraph "External Systems"
        BancaribeAPI[Open Banking Bancaribe<br/>C2P2 v1.0.0]
        Sentry[Sentry<br/>error tracking]
        Resend[Resend<br/>emails transaccionales]
    end

    Browser -->|carga| Widget
    Widget -->|POST /v1/payments/confirm| API
    MerchSite -->|servidor a servidor<br/>POST /v1/payments| API
    DashUI -->|REST + JWT| API
    API <-->|read/write| DB
    API -->|encola webhook| WebhookWorker
    WebhookWorker -->|HTTP POST firmado| MerchSite
    API -->|registrarPagoC2pApi| BancaribeAPI
    API -->|errores| Sentry
    API -->|emails| Resend

    style API fill:#4F46E5,color:#fff
    style DB fill:#059669,color:#fff
```

### Containers

| Container | Tecnología | Responsabilidad |
|---|---|---|
| **Core API** | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 async, asyncpg | REST, auth API key (SHA256+pepper), orquestación de pagos, audit log, outbox webhooks. |
| **PostgreSQL** | Postgres 16 (docker-compose local; Railway/Supabase en deploy) | Almacén transaccional. `amount_cents BIGINT` (céntimos enteros, no NUMERIC en MVP). Audit log append-only. |
| **Webhook Dispatcher** | FastAPI `BackgroundTasks` (MVP, **un intento**) → ARQ/Celery con backoff (Fase 2) | Envío asíncrono outbox. Firma HMAC-SHA256 header `X-Pasarela-Signature`. |
| **Bank Adapter** | Strategy Pattern. `MockBankAdapter` activo. `BancaribeAdapter` stub. | Aísla integración bancaria del core. |
| **Sentry** | SaaS (opcional vía `SENTRY_DSN`) | Captura de errores. |
| **Checkout Widget** (planeado) | TypeScript, Vite library mode | Modal embebible. No en repo aún. |
| **Dashboard** (planeado) | Next.js 15, Tailwind, shadcn/ui, Supabase Auth | UI comerciante. No en repo aún. |
| **Resend** (planeado) | SaaS | Emails transaccionales. No integrado aún. |

---

## Nivel 3 — Diagrama de Componentes (Core API)

```mermaid
graph TB
    subgraph "Core API (FastAPI)"
        Router[API Router<br/>/v1 endpoints]
        Auth[Auth Middleware<br/>API Key + JWT]
        RateLimit[Rate Limiter<br/>per API key + IP]
        Idem[Idempotency Layer<br/>en memoria MVP / Redis Fase 2]

        PaymentService[Payment Service<br/>orquestación core]
        WebhookService[Webhook Service<br/>dispatcher + firma HMAC]
        MerchantService[Merchant Service<br/>CRUD de comerciantes]
        EventService[Event Service<br/>audit log append-only]

        BankAdapter[Bank Adapter<br/>Strategy Pattern]
        BancaribeImpl[Bancaribe Adapter<br/>C2P2 integration]
        MockImpl[Mock Adapter<br/>simulación para demo]

        Repos[Repositories<br/>SQLAlchemy data access]
    end

    Router --> Auth
    Auth --> RateLimit
    RateLimit --> Idem
    Idem --> PaymentService
    Idem --> MerchantService

    PaymentService --> BankAdapter
    PaymentService --> EventService
    PaymentService --> WebhookService

    BankAdapter --> BancaribeImpl
    BankAdapter --> MockImpl

    PaymentService --> Repos
    MerchantService --> Repos
    EventService --> Repos
    WebhookService --> Repos

    style BankAdapter fill:#F59E0B,color:#000
```

### Componentes clave

#### Bank Adapter (Strategy Pattern)

El componente más estratégico. Permite intercambiar la implementación bancaria sin tocar el core. En Fase 1 solo existe `BancaribeImpl` (más `MockImpl` para demo). En Fase 2 se agregarán `BNCImpl`, `MercantilImpl`, etc.

```python
# app/banking/base.py
from abc import ABC, abstractmethod
from app.banking.schemas import C2PRequest, C2PResponse, OperationStatus

class BankAdapter(ABC):
    """
    Interfaz base para adapters bancarios.
    Soporta modo Facilitator (Fase 1) y Aggregator (Fase 3).
    """

    @abstractmethod
    async def initiate_c2p(self, req: C2PRequest) -> C2PResponse:
        """
        Inicia un cobro C2P. En Fase 1 (facilitator) la liquidación
        va directo al comerciante. En Fase 3 (aggregator) iría a
        cuenta operativa apadrinada.
        """
        pass

    @abstractmethod
    async def query_operation(self, ref: str) -> OperationStatus:
        """Consulta el estado de una operación previamente iniciada."""
        pass

    @abstractmethod
    async def list_supported_banks(self) -> list[dict]:
        """Lista de bancos cuyas claves OTP puede validar."""
        pass

    @property
    @abstractmethod
    def supports_aggregator_mode(self) -> bool:
        """True solo si hay contrato de sub-agencia activo (Fase 3)."""
        pass
```

#### Idempotency Layer

Crítico para pagos. Diseño: cada `POST /v1/payments` lleva header `Idempotency-Key`. Si llega dos veces, devuelve respuesta original sin reprocesar.

**Estado MVP**: columna `payment_intents.idempotency_key` existe + índice único por `(merchant_id, idempotency_key)`, pero el enforcement del header en el endpoint **aún no implementado**. Pendiente Día 6.
**Fase 2**: Redis con `SET NX EX 86400` para concurrencia distribuida.

#### Event Service (Audit Log)

Tabla `events` append-only. Cada cambio de estado de un payment, cada llamada al banco, cada webhook enviado se inserta como evento inmutable. Esto:

- Garantiza auditabilidad completa (requisito regulatorio en Fase 3)
- Permite reconstruir el estado de cualquier transacción
- Habilita event sourcing en Fase 3 sin cambios de modelo

#### Webhook Service (Outbox Pattern)

Los webhooks no se envían directamente desde el código que procesa el pago. Se insertan en tabla `webhook_attempts` dentro de la **misma transacción** que el cambio de estado del payment. Un dispatcher lee y envía firmado HMAC-SHA256.

**Estado MVP**: dispatch via `FastAPI BackgroundTasks` con **un solo intento** post-commit. Si falla, queda `delivered=false` en DB (replay manual).
**Fase 2**: worker ARQ/Celery con backoff exponencial 1m/5m/15m/1h/6h/24h.

Garantía outbox: **ningún cambio de estado queda sin fila en `webhook_attempts`** incluso si el proceso muere, porque la fila se inserta en la misma TX.

---

## Decisiones arquitectónicas (ADRs)

### ADR-001: FastAPI sobre alternativas (Django, Flask, Node.js)

**Contexto**: necesitamos un framework web async, tipado, con generación automática de OpenAPI.

**Decisión**: FastAPI + Pydantic v2.

**Razones**:
- Tipado fuerte con Pydantic — crítico para datos financieros (cédulas, teléfonos, montos).
- OpenAPI/Swagger auto-generado — alineado con filosofía developer-first.
- Async nativo — necesario para llamadas concurrentes a Bancaribe.
- Stack Python familiar para el equipo (proyectos previos validados).

**Trade-offs aceptados**: ecosistema de Python para fintech enterprise es menor que el de Java/Spring, pero suficiente para MVP y Fase 2.

### ADR-002: PostgreSQL como única DB transaccional

**Contexto**: necesitamos consistencia ACID estricta para transacciones financieras.

**Decisión**: PostgreSQL 16 con `SERIALIZABLE` isolation para escrituras críticas. NUMERIC(19,4) para todos los montos (nunca FLOAT).

**Alternativas descartadas**: NoSQL (MongoDB, DynamoDB) — pierden ACID. SQLite — no escala.

### ADR-003: Bank Adapter como Strategy Pattern

**Contexto**: Fase 1 es Bancaribe-only, pero Fase 2 requiere multi-banco.

**Decisión**: clase abstracta `BankAdapter` con implementaciones intercambiables. El core nunca conoce qué banco está hablando.

**Beneficio**: agregar BNC en Fase 2 es escribir un `BNCAdapter`, no modificar el core.

### ADR-004: Idempotency obligatoria en endpoints de escritura

**Contexto**: pagos no pueden duplicarse por reintentos del cliente.

**Decisión**: header `Idempotency-Key` obligatorio en `POST /v1/payments`. Respuestas cacheadas 24h.

**Implementación MVP**: dict en memoria con TTL.
**Implementación Fase 2**: Redis distribuido.

### ADR-005: Audit log append-only desde día 1

**Contexto**: Fase 3 (modelo agregador) requerirá auditoría regulatoria completa. Construir esto en MVP cuesta poco; agregar después es caro.

**Decisión**: tabla `events` con inserciones únicamente. Cada cambio de estado se registra como evento. Event sourcing-ready.

### ADR-006: Outbox pattern para webhooks

**Contexto**: webhooks no entregados son una causa común de bugs en pasarelas de pago.

**Decisión**: webhooks se insertan en tabla `webhook_outbox` dentro de la transacción del cambio de estado. Dispatcher separado consume la tabla.

**Beneficio**: garantía de entrega even si el servicio se reinicia.

### ADR-007: Monorepo con apps separadas

**Contexto**: 4 productos relacionados (API, Dashboard, Widget, Tienda Demo).

**Decisión**: monorepo con `apps/` y `packages/`. Sin herramientas pesadas tipo Nx (innecesario para MVP).

**Trade-off**: deploys separados (Railway para backend, Vercel para frontends), pero versiones sincronizadas vía Git.

---

## Capacidades preparadas para Fase 3 (Modelo Agregador)

El MVP incluye los siguientes ganchos arquitectónicos pensados para activarse cuando exista el contrato de sub-agencia con Bancaribe:

1. **Tabla `merchant_accounts`** con campo `bank` y `account_type` (preparada para múltiples bancos y para tipo "operativa apadrinada" en Fase 3).
2. **Campo `flow_mode`** en transacciones: `direct_to_merchant` (Fase 1) o `via_aggregator` (Fase 3, no implementado).
3. **Modelo de `settlement`** separado del modelo de `payment`: en Fase 1 son síncronos, en Fase 3 desacoplados.
4. **`BankAdapter.supports_aggregator_mode`**: flag que indica si el banco actual permite operación apadrinada.

---

## Diagrama de despliegue (deployment)

```
┌────────────────────────────────────────────────────────────────┐
│                      Cloudflare DNS + WAF                       │
└────────────────┬───────────────────────────┬───────────────────┘
                 │                           │
                 ▼                           ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│  Vercel (planeado)        │    │  Railway / Supabase       │
│  ─────                    │    │  ─────                    │
│  - landing.pasarela.dev   │    │  - api.pasarela.dev       │
│  - app.pasarela.dev       │    │    (FastAPI, Dockerfile)  │
│  - tienda.pasarela.dev    │    │  - Postgres 16            │
│  - cdn.pasarela.dev/      │    │    (docker-compose local) │
│    checkout.js            │    │                           │
└──────────────────────────┘    └──────────┬───────────────┘
                                            │
                                            ▼
                                ┌──────────────────────────┐
                                │  Bancaribe Open Banking   │
                                │  35ecb.bancaribe.com.ve   │
                                └──────────────────────────┘
```

---

## Próximos pasos

- Implementación del Core API (Día 2)
- Deploy en Railway (Día 3)
- Dashboard funcional (Día 3-4)
- Checkout Widget (Día 4-5)
- Documentación pública en `docs.pasarela.dev` (Día 6)
