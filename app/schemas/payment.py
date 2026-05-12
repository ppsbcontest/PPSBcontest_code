import re
from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.banking.mock import SUPPORTED_BANK_CODES

_PHONE_RE = re.compile(r"^04\d{9}$")
_ID_DOC_RE = re.compile(r"^[VEJGP]\d{6,9}$")
_BANK_CODE_RE = re.compile(r"^\d{4}$")

_MAX_AMOUNT_CENTS = 1_000_000_000_00


class PaymentCreateRequest(BaseModel):
    amount: int = Field(..., ge=1, le=_MAX_AMOUNT_CENTS, description="Monto en céntimos. Máximo 100_000_000_000.")
    currency: Literal["VES", "USD"]
    customer_phone: str = Field(..., min_length=7, max_length=20)
    customer_id_document: str = Field(..., min_length=5, max_length=15)
    customer_bank_code: str = Field(..., min_length=4, max_length=8)

    @field_validator("customer_phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        if not _PHONE_RE.match(v):
            raise ValueError("Teléfono debe tener formato 04XXXXXXXXX (11 dígitos)")
        return v

    @field_validator("customer_id_document")
    @classmethod
    def _validate_id_doc(cls, v: str) -> str:
        norm = v.upper().strip()
        if not _ID_DOC_RE.match(norm):
            raise ValueError("Cédula/RIF debe ser formato V/E/J/G/P seguido de 6-9 dígitos")
        return norm

    @field_validator("customer_bank_code")
    @classmethod
    def _validate_bank_code(cls, v: str) -> str:
        if not _BANK_CODE_RE.match(v) or v not in SUPPORTED_BANK_CODES:
            raise ValueError("Código de banco inválido o no soportado")
        return v


class PaymentConfirmRequest(BaseModel):
    client_secret: Optional[str] = None
    otp: str = Field(..., min_length=4, max_length=12)


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_id: str
    merchant_id: UUID
    merchant_account_id: UUID
    amount_cents: int
    currency: str
    status: str
    customer_phone: str
    customer_id_document: str
    customer_bank_code: str
    flow_mode: str
    bank_reference: Optional[str] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime] = None
    succeeded_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class PaymentCreateResponse(PaymentResponse):
    client_secret: Optional[str] = None


class PaymentListResponse(BaseModel):
    items: List[PaymentResponse]
    next_cursor: Optional[str] = None
    has_more: bool
