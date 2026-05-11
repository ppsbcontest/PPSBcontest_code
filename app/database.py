import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Strip libpq-only params asyncpg rejects (e.g. sslmode). asyncpg uses ssl arg.
_ssl_required = "sslmode=require" in DATABASE_URL or "ssl=require" in DATABASE_URL
if "?" in DATABASE_URL:
    base, _, qs = DATABASE_URL.partition("?")
    kept = [p for p in qs.split("&") if not p.startswith("sslmode=") and not p.startswith("ssl=")]
    DATABASE_URL = base + ("?" + "&".join(kept) if kept else "")

_connect_args: dict = {}
if _ssl_required or any(h in DATABASE_URL for h in ("supabase.co", "supabase.com", "neon.tech")):
    _connect_args["ssl"] = "require"

# Supabase transaction pooler (port 6543) is PgBouncer in transaction mode —
# breaks prepared statements. Disable asyncpg statement cache for that case.
_is_pooler_tx = ":6543/" in DATABASE_URL or "pooler.supabase.com:6543" in DATABASE_URL
if _is_pooler_tx:
    _connect_args["statement_cache_size"] = 0
    _connect_args["prepared_statement_cache_size"] = 0

engine = create_async_engine(DATABASE_URL, echo=False, connect_args=_connect_args)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session