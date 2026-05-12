import os
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI

from app.api.v1 import payments, webhook_endpoints
from app.bootstrap import seed_dev_fixtures

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


app = FastAPI(title="Rutiva API", lifespan=lifespan)

app.include_router(payments.router)
app.include_router(webhook_endpoints.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
