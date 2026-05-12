from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import ApiKey, Merchant, MerchantAccount
from app.security import hash_api_key

DEV_MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000001")
DEV_MERCHANT_ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000002")
DEV_API_KEY_ID = UUID("00000000-0000-0000-0000-000000000003")
DEV_API_KEY_PLAINTEXT = "sk_test_dev_rutiva_001"


async def _ensure_merchant(session: AsyncSession) -> None:
    res = await session.execute(select(Merchant).where(Merchant.id == DEV_MERCHANT_ID))
    if res.scalar_one_or_none():
        return
    session.add(
        Merchant(
            id=DEV_MERCHANT_ID,
            external_id="merch_dev_001",
            legal_name="Dev Merchant C.A.",
            rif="J-12345678-9",
            contact_email="dev@rutiva.local",
            status="active",
        )
    )


async def _ensure_account(session: AsyncSession) -> None:
    res = await session.execute(
        select(MerchantAccount).where(MerchantAccount.id == DEV_MERCHANT_ACCOUNT_ID)
    )
    if res.scalar_one_or_none():
        return
    session.add(
        MerchantAccount(
            id=DEV_MERCHANT_ACCOUNT_ID,
            merchant_id=DEV_MERCHANT_ID,
            acquiring_bank="0114",
            account_type="merchant_direct",
            account_number_encrypted=b"DEV-ACCOUNT-PLAINTEXT-PLACEHOLDER",
            is_default=True,
            status="active",
        )
    )


async def _ensure_api_key(session: AsyncSession) -> None:
    expected_hash = hash_api_key(DEV_API_KEY_PLAINTEXT)
    res = await session.execute(select(ApiKey).where(ApiKey.id == DEV_API_KEY_ID))
    existing = res.scalar_one_or_none()
    if existing:
        if existing.key_hash != expected_hash:
            existing.key_hash = expected_hash
            existing.revoked_at = None
        return
    session.add(
        ApiKey(
            id=DEV_API_KEY_ID,
            merchant_id=DEV_MERCHANT_ID,
            external_id="ak_dev_001",
            key_hash=expected_hash,
            key_type="secret",
            environment="test",
            label="dev stub key",
        )
    )


async def seed_dev_fixtures() -> None:
    async with AsyncSessionLocal() as session:
        await _ensure_merchant(session)
        await session.flush()
        await _ensure_account(session)
        await _ensure_api_key(session)
        await session.commit()
