import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_settings = get_settings()

# prepare_threshold=None disables server-side prepared statements, so poolers (Supabase/pgbouncer) work.
# Every database round trip counts when the API and the database are far apart, so: no pre-ping query on each
# checkout (connections are recycled before the pooler would drop them, and TCP keepalives catch dead ones), and a
# pool small enough that API + workflow + provider service stay inside Supabase's free pooler limit (~15).
engine = create_async_engine(
    _settings.sqlalchemy_url,
    pool_size=6,
    max_overflow=3,
    pool_pre_ping=False,
    pool_recycle=240,
    connect_args={"prepare_threshold": None, "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10,
                  "keepalives_count": 3},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# Read-only work runs in autocommit mode: no BEGIN/COMMIT round trips around each request.
ReadSession = async_sessionmaker(engine.execution_options(isolation_level="AUTOCOMMIT"), expire_on_commit=False)
_read_slots = asyncio.Semaphore(5)


async def read_parallel(**parts: Callable[[AsyncSession], Awaitable[Any]]) -> dict[str, Any]:
    """Run independent read queries at the same time, each on its own read-only connection.

    A page that needs ten lookups then costs about one database round trip instead of ten."""

    async def run(fn: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
        async with _read_slots, ReadSession() as s:
            return await fn(s)

    names = list(parts)
    values = await asyncio.gather(*(run(parts[n]) for n in names))
    return dict(zip(names, values, strict=True))


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


async def init_db() -> None:
    from app.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
