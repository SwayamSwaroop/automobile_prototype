"""Async PostgreSQL engine and request-scoped sessions."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.settings.config import get_settings

settings = get_settings()
async_engine = create_async_engine(
    settings.async_db_url,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a session; routers explicitly own commit/rollback via db.begin()."""
    async with AsyncSessionLocal() as session:
        yield session
