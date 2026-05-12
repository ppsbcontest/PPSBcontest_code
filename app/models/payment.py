from datetime import datetime
from typing import Any

from sqlalchemy import String, BigInteger, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PaymentIntent(Base):
    __tablename__ = "payment_intents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    external_id: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False)
    merchant_account_id: Mapped[str] = mapped_column(ForeignKey("merchant_accounts.id"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="created")
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_id_document: Mapped[str] = mapped_column(String(15), nullable=False)
    customer_bank_code: Mapped[str] = mapped_column(String(8), nullable=False)
    flow_mode: Mapped[str] = mapped_column(String(32), nullable=False, server_default="direct_to_merchant")
    bank_reference: Mapped[str] = mapped_column(String(100), nullable=True)
    failure_code: Mapped[str] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[str] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=True)
    client_secret_hash: Mapped[str] = mapped_column(String(64), nullable=True)
    metadata_data: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, server_default='{}')
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    confirmed_at: Mapped[datetime] = mapped_column(nullable=True)
    succeeded_at: Mapped[datetime] = mapped_column(nullable=True)
    failed_at: Mapped[datetime] = mapped_column(nullable=True)
    canceled_at: Mapped[datetime] = mapped_column(nullable=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now() + interval '15 minutes'"))
