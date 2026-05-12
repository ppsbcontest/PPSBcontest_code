import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import WebhookAttempt, WebhookEndpoint


def _new_attempt_external_id() -> str:
    return f"whatt_{secrets.token_urlsafe(12)}"


def generate_signing_secret() -> str:
    return f"whsec_{secrets.token_urlsafe(32)}"


def sign_payload(secret: str, timestamp: int, body: str) -> str:
    """Stripe-style. HMAC-SHA256 over '{timestamp}.{body}'."""
    msg = f"{timestamp}.{body}".encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256)
    return mac.hexdigest()


def signature_header(secret: str, body: str) -> tuple[str, int]:
    ts = int(time.time())
    sig = sign_payload(secret, ts, body)
    return f"t={ts},v1={sig}", ts


class WebhookService:
    @staticmethod
    def _event_matches(enabled: list[str], event_type: str) -> bool:
        if "*" in enabled:
            return True
        if event_type in enabled:
            return True
        prefix = event_type.split(".", 1)[0] + ".*"
        return prefix in enabled

    @staticmethod
    async def record_attempts(
        session: AsyncSession,
        merchant_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        payment_intent_id: UUID | None = None,
    ) -> list[UUID]:
        """Outbox: insert webhook_attempts rows in the caller's transaction.
        Returns attempt IDs. Caller commits, then schedules dispatch."""
        stmt = select(WebhookEndpoint).where(
            WebhookEndpoint.merchant_id == merchant_id,
            WebhookEndpoint.status == "active",
        )
        res = await session.execute(stmt)
        endpoints = list(res.scalars().all())

        attempt_ids: list[UUID] = []
        for ep in endpoints:
            if not WebhookService._event_matches(ep.enabled_events, event_type):
                continue
            attempt = WebhookAttempt(
                webhook_endpoint_id=ep.id,
                payment_intent_id=payment_intent_id,
                event_type=event_type,
                payload=payload,
                attempt_number=1,
                delivered=False,
            )
            session.add(attempt)
            await session.flush()
            attempt_ids.append(attempt.id)
        return attempt_ids

    @staticmethod
    async def dispatch(attempt_id: UUID) -> None:
        """Background task. New session — caller's TX already committed."""
        async with AsyncSessionLocal() as session:
            attempt = await session.get(WebhookAttempt, attempt_id)
            if attempt is None or attempt.delivered:
                return
            endpoint = await session.get(WebhookEndpoint, attempt.webhook_endpoint_id)
            if endpoint is None or endpoint.status != "active":
                return

            body = json.dumps(attempt.payload, default=str, separators=(",", ":"))
            secret = endpoint.signing_secret_encrypted.decode("utf-8", errors="ignore")
            sig_header, _ = signature_header(secret, body)

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        endpoint.url,
                        content=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Rutiva-Signature": sig_header,
                            "X-Rutiva-Event-Type": attempt.event_type,
                        },
                    )
                attempt.response_status = resp.status_code
                attempt.response_body = resp.text[:2000]
                attempt.delivered = 200 <= resp.status_code < 300
                if attempt.delivered:
                    from datetime import datetime

                    attempt.delivered_at = datetime.utcnow()
            except Exception as e:
                attempt.response_status = 0
                attempt.response_body = f"client_error:{type(e).__name__}:{str(e)[:500]}"
                attempt.delivered = False

            await session.commit()
