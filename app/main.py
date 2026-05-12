import os
import re
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, Response

from app.api.v1 import banks, payments, webhook_endpoints
from app.bootstrap import seed_dev_fixtures

_CONFIRM_PATH_RE = re.compile(r"^/v1/payments/[^/]+/confirm/?$")
_BANKS_PATH_RE = re.compile(r"^/v1/banks/?$")


def _is_public_widget_path(path: str) -> tuple[bool, str]:
    if _CONFIRM_PATH_RE.match(path):
        return True, "POST, OPTIONS"
    if _BANKS_PATH_RE.match(path):
        return True, "GET, OPTIONS"
    return False, ""


class WidgetCORSMiddleware(BaseHTTPMiddleware):
    """CORS abierto para endpoints consumidos directamente por el Widget público."""

    async def dispatch(self, request, call_next):
        is_public, methods = _is_public_widget_path(request.url.path)
        if is_public and request.method == "OPTIONS":
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": methods,
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Max-Age": "600",
                },
            )
        response = await call_next(request)
        if is_public:
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = methods
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

_sentry_dsn = os.getenv("SENTRY_DSN")
if _sentry_dsn:
    sentry_sdk.init(
        dsn=_sentry_dsn,
        environment=os.getenv("ENVIRONMENT", "development"),
        traces_sample_rate=0.1,
        send_default_pii=False,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("ENVIRONMENT", "development") != "production":
        await seed_dev_fixtures()
    yield


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
    contact={"name": "Equipo Rutiva", "url": "https://rutiva.dev"},
    license_info={"name": "Proprietary"},
    lifespan=lifespan,
    openapi_tags=[
        {"name": "payments", "description": "Crear, confirmar, cancelar y consultar payment_intents."},
        {"name": "webhooks", "description": "Endpoints receptores registrados por el comerciante."},
        {"name": "banks", "description": "Lista pública de bancos venezolanos soportados."},
        {"name": "meta", "description": "Health checks y metadata del servicio."},
    ],
)
app.add_middleware(WidgetCORSMiddleware)

app.include_router(payments.router)
app.include_router(webhook_endpoints.router)
app.include_router(banks.router)


@app.get("/health", tags=["meta"], summary="Health check")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "rutiva-api"}


@app.get("/ping", include_in_schema=False, response_class=PlainTextResponse)
async def ping() -> str:
    return "pong"
