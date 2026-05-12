import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthContext, get_auth_context, get_bank_adapter, get_optional_auth_context
from app.banking.base import BankAdapter
from app.banking.schemas import C2PRequest
from app.database import get_db
from app.models import MerchantAccount, PaymentIntent
from app.schemas.payment import (
    PaymentConfirmRequest,
    PaymentCreateRequest,
    PaymentCreateResponse,
    PaymentListResponse,
    PaymentResponse,
)
from app.services.events import EventService
from app.services.webhooks import WebhookService

_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]+$")

router = APIRouter(prefix="/v1/payments", tags=["payments"])


def _new_external_id() -> str:
    return f"pi_{secrets.token_urlsafe(16)}"


def _encode_cursor(created_at: datetime, intent_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{intent_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    pad = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + pad).decode("utf-8")
        ca_iso, id_str = raw.split("|", 1)
        return datetime.fromisoformat(ca_iso), UUID(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_cursor")


PAYMENT_INTENT_TTL = timedelta(minutes=15)


def _intent_payload(intent: PaymentIntent) -> dict:
    return {
        "id": str(intent.id),
        "external_id": intent.external_id,
        "status": intent.status,
        "amount_cents": intent.amount_cents,
        "currency": intent.currency,
        "merchant_id": str(intent.merchant_id),
        "bank_reference": intent.bank_reference,
        "failure_code": intent.failure_code,
        "failure_message": intent.failure_message,
        "created_at": intent.created_at.isoformat() if intent.created_at else None,
        "updated_at": intent.updated_at.isoformat() if intent.updated_at else None,
    }


@router.post("", response_model=PaymentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payload: PaymentCreateRequest,
    background: BackgroundTasks,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> PaymentIntent:
    """Crea un payment_intent.

    Header opcional `Idempotency-Key` (max 100 chars, regex `^[A-Za-z0-9_\\-:.]+$`).
    Si se repite la misma key con body idéntico, devuelve el intent existente con HTTP 200.
    Si la key se repite con body distinto, devuelve 422 `idempotency_key_mismatch`.
    """
    if idempotency_key is not None:
        if len(idempotency_key) > 100 or not _IDEMPOTENCY_KEY_RE.match(idempotency_key):
            raise HTTPException(status_code=422, detail="invalid_idempotency_key")
        res = await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.merchant_id == auth.merchant_id,
                PaymentIntent.idempotency_key == idempotency_key,
            )
        )
        existing = res.scalar_one_or_none()
        if existing is not None:
            if (
                existing.amount_cents != payload.amount
                or existing.currency != payload.currency
                or existing.customer_phone != payload.customer_phone
                or existing.customer_id_document != payload.customer_id_document
                or existing.customer_bank_code != payload.customer_bank_code
            ):
                raise HTTPException(status_code=422, detail="idempotency_key_mismatch")
            response.status_code = status.HTTP_200_OK
            return existing

    external_id = _new_external_id()
    client_secret_plain = f"{external_id}_secret_{secrets.token_urlsafe(24)}"
    client_secret_hash = hashlib.sha256(client_secret_plain.encode("utf-8")).hexdigest()

    intent = PaymentIntent(
        external_id=external_id,
        merchant_id=auth.merchant_id,
        merchant_account_id=auth.merchant_account_id,
        amount_cents=payload.amount,
        currency=payload.currency,
        status="created",
        customer_phone=payload.customer_phone,
        customer_id_document=payload.customer_id_document,
        customer_bank_code=payload.customer_bank_code,
        flow_mode="direct_to_merchant",
        idempotency_key=idempotency_key,
        client_secret_hash=client_secret_hash,
        expires_at=datetime.utcnow() + PAYMENT_INTENT_TTL,
    )
    db.add(intent)
    await db.flush()

    event_payload = {"type": "payment_intent.created", "data": _intent_payload(intent)}
    await EventService.record(
        db,
        event_type="payment_intent.created",
        payload=event_payload,
        related_entity_id=intent.id,
        related_entity_type="payment_intent",
        actor_id=auth.api_key_id,
        actor_type="api_key",
    )
    attempt_ids = await WebhookService.record_attempts(
        db,
        merchant_id=auth.merchant_id,
        event_type="payment_intent.created",
        payload=event_payload,
        payment_intent_id=intent.id,
    )

    await db.commit()
    await db.refresh(intent)

    for aid in attempt_ids:
        background.add_task(WebhookService.dispatch, aid)

    resp = PaymentCreateResponse.model_validate(intent)
    resp.client_secret = client_secret_plain
    return resp


@router.options("/{intent_id}/confirm", include_in_schema=False)
async def confirm_payment_preflight(intent_id: str) -> Response:
    return Response(status_code=204)


@router.post("/{intent_id}/confirm", response_model=PaymentResponse)
async def confirm_payment(
    intent_id: UUID,
    payload: PaymentConfirmRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth_context),
    bank: BankAdapter = Depends(get_bank_adapter),
) -> PaymentIntent:
    """Confirma un payment_intent con OTP del cliente.

    Dos modos de autenticación:
    - Backend: header `Authorization: Bearer sk_xxx` (modo comerciante).
    - Widget: body `client_secret` emitido en la respuesta del create (sin API key).
    Si ambos llegan, prevalece sk_. Sin ninguno: 401.
    """
    intent = await db.get(PaymentIntent, intent_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="payment_intent_not_found")

    if auth is not None:
        if intent.merchant_id != auth.merchant_id:
            raise HTTPException(status_code=404, detail="payment_intent_not_found")
        actor_id = auth.api_key_id
        actor_type = "api_key"
    else:
        if not payload.client_secret:
            raise HTTPException(status_code=401, detail="authentication_required")
        prefix = payload.client_secret.split("_secret_", 1)[0]
        if prefix != intent.external_id or intent.client_secret_hash is None:
            raise HTTPException(status_code=403, detail="invalid_client_secret")
        provided_hash = hashlib.sha256(payload.client_secret.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(provided_hash, intent.client_secret_hash):
            raise HTTPException(status_code=403, detail="invalid_client_secret")
        actor_id = None
        actor_type = "client_secret"

    if intent.status not in ("created", "requires_confirmation"):
        raise HTTPException(
            status_code=409, detail=f"invalid_state:{intent.status}"
        )

    if intent.expires_at is not None and datetime.utcnow() > intent.expires_at:
        intent.status = "canceled"
        intent.canceled_at = datetime.utcnow()
        intent.updated_at = datetime.utcnow()
        exp_payload = {"type": "payment_intent.canceled", "data": _intent_payload(intent)}
        await EventService.record(
            db,
            event_type="payment_intent.canceled",
            payload=exp_payload,
            related_entity_id=intent.id,
            related_entity_type="payment_intent",
            actor_id=actor_id,
            actor_type=actor_type,
        )
        exp_attempt_ids = await WebhookService.record_attempts(
            db,
            merchant_id=intent.merchant_id,
            event_type="payment_intent.canceled",
            payload=exp_payload,
            payment_intent_id=intent.id,
        )
        await db.commit()
        for aid in exp_attempt_ids:
            background.add_task(WebhookService.dispatch, aid)
        raise HTTPException(status_code=400, detail="payment_expired")

    account = await db.get(MerchantAccount, intent.merchant_account_id)
    if account is None:
        raise HTTPException(status_code=500, detail="merchant_account_missing")

    now = datetime.utcnow()
    intent.confirmed_at = now

    c2p_req = C2PRequest(
        merchant_account=account.account_number_encrypted.decode("utf-8", errors="ignore"),
        customer_phone=intent.customer_phone,
        customer_id=intent.customer_id_document,
        customer_bank=intent.customer_bank_code,
        otp=payload.otp,
        amount_cents=intent.amount_cents,
        currency=intent.currency,
        reference=intent.external_id,
    )

    try:
        resp = await bank.initiate_c2p(c2p_req)
        intent.status = "succeeded"
        intent.bank_reference = resp.reference
        intent.succeeded_at = datetime.utcnow()
    except ValueError as e:
        intent.status = "failed"
        intent.failure_code = "bank_declined"
        intent.failure_message = str(e)
        intent.failed_at = datetime.utcnow()

    intent.updated_at = datetime.utcnow()

    final_event_type = (
        "payment_intent.succeeded" if intent.status == "succeeded" else "payment_intent.failed"
    )
    event_payload = {"type": final_event_type, "data": _intent_payload(intent)}
    await EventService.record(
        db,
        event_type=final_event_type,
        payload=event_payload,
        related_entity_id=intent.id,
        related_entity_type="payment_intent",
        actor_id=actor_id,
        actor_type=actor_type,
    )
    attempt_ids = await WebhookService.record_attempts(
        db,
        merchant_id=intent.merchant_id,
        event_type=final_event_type,
        payload=event_payload,
        payment_intent_id=intent.id,
    )

    await db.commit()
    await db.refresh(intent)

    for aid in attempt_ids:
        background.add_task(WebhookService.dispatch, aid)
    return intent


@router.get("", response_model=PaymentListResponse)
async def list_payments(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> PaymentListResponse:
    stmt = select(PaymentIntent).where(PaymentIntent.merchant_id == auth.merchant_id)
    if cursor:
        ca, cid = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                PaymentIntent.created_at < ca,
                and_(PaymentIntent.created_at == ca, PaymentIntent.id < cid),
            )
        )
    stmt = stmt.order_by(
        PaymentIntent.created_at.desc(), PaymentIntent.id.desc()
    ).limit(limit + 1)

    res = await db.execute(stmt)
    rows = list(res.scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        _encode_cursor(items[-1].created_at, items[-1].id) if has_more and items else None
    )
    return PaymentListResponse(
        items=[PaymentResponse.model_validate(it) for it in items],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post("/{intent_id}/cancel", response_model=PaymentResponse)
async def cancel_payment(
    intent_id: UUID,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> PaymentIntent:
    """Cancela un payment_intent en estado `created`. Solo backend (sk_)."""
    intent = await db.get(PaymentIntent, intent_id)
    if intent is None or intent.merchant_id != auth.merchant_id:
        raise HTTPException(status_code=404, detail="payment_intent_not_found")
    if intent.status != "created":
        raise HTTPException(status_code=400, detail=f"invalid_state:{intent.status}")

    intent.status = "canceled"
    intent.canceled_at = datetime.utcnow()
    intent.updated_at = datetime.utcnow()

    event_payload = {"type": "payment_intent.canceled", "data": _intent_payload(intent)}
    await EventService.record(
        db,
        event_type="payment_intent.canceled",
        payload=event_payload,
        related_entity_id=intent.id,
        related_entity_type="payment_intent",
        actor_id=auth.api_key_id,
        actor_type="api_key",
    )
    attempt_ids = await WebhookService.record_attempts(
        db,
        merchant_id=auth.merchant_id,
        event_type="payment_intent.canceled",
        payload=event_payload,
        payment_intent_id=intent.id,
    )

    await db.commit()
    await db.refresh(intent)

    for aid in attempt_ids:
        background.add_task(WebhookService.dispatch, aid)
    return intent


@router.get("/{intent_id}", response_model=PaymentResponse)
async def get_payment(
    intent_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth_context),
) -> PaymentIntent:
    intent = await db.get(PaymentIntent, intent_id)
    if intent is None or intent.merchant_id != auth.merchant_id:
        raise HTTPException(status_code=404, detail="payment_intent_not_found")
    return intent
