"""Database Session and Connection Health Management."""

import logging
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for obtaining async database sessions."""
    async with AsyncSessionLocal() as session:
        yield session


async def check_database_health() -> dict[str, Any]:
    """Perform database connection ping and return health status dictionary."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            val = result.scalar()
            if val == 1:
                return {
                    "database": "postgresql",
                    "status": "HEALTHY",
                    "connected": True,
                }
            return {"database": "postgresql", "status": "UNHEALTHY", "connected": False}
    except Exception as e:
        logger.warning("Database health check ping failed: %s", e)
        return {
            "database": "postgresql",
            "status": "UNAVAILABLE",
            "connected": False,
            "error": str(e),
        }
