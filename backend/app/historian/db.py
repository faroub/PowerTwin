"""Database Session and Connection Health Management.

The module owns the connection engine of the platform's historian and the
readiness evaluation of that store.

The readiness evaluation is a sequence of gates, each one stronger than the
last, so that the operator can tell a *configuration* problem from an
*outage* and an *unmigrated* database from an unreachable one:

1. ``configured`` — the application resolves a database URL, so a deployment
   can reach a database in principle.
2. ``reachable`` — a connection through that URL was established.
3. ``complete`` — every table the ORM models declare exists, so the
   migrations of the release have been applied to that database.

**A migration is never part of this module.** Running a migration from inside
the application would execute one per worker instance, and a deployment that
was upgraded without its database being migrated is another failure mode the
database has to report: the readiness probe answers it. The migration of a
database is an explicit, deliberate operator action, executed by the
``migrate`` service of the deployment, documented by ``docs/``.

The unittests drive the service with their own engine, so the module never
assumes a specific server is reachable.

Every connection attempt is bounded by a timeout, so the probe answers with
the reason for a failure rather than hanging the process forever.
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import settings
from backend.app.historian.models import Base

logger = logging.getLogger(__name__)

#: Maximum time, in seconds, a connection attempt is allowed to take. A
#: database that never answers the handshake holds the readiness probe and the
#: operator no information about why.
CONNECT_TIMEOUT_S: float = 5.0


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    connect_args={"timeout": int(CONNECT_TIMEOUT_S)},
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


def get_expected_tables() -> frozenset[str]:
    """Return the table names the application requires from the database.

    The names come from the ORM metadata: every table the models declare must
    be created by the migrations of this release. ``alembic_version`` is
    included because a database that never ran a migration has neither the
    tables nor the version table the migration history records.

    A migration that was never run therefore leaves the database incomplete,
    and the readiness evaluation names the missing tables rather than the
    symbols of a table that the application might have wanted.
    """
    tables = set(Base.metadata.tables)
    tables.add("alembic_version")
    return frozenset(tables)


class DatabaseReadiness:
    """Detailed outcome of the database readiness evaluation."""

    STATUS_CONFIGURED = "configured"
    STATUS_UNCONFIGURED = "unconfigured"
    STATUS_UNREACHABLE = "unreachable"
    STATUS_SCHEMA_MISSING = "schema_missing"
    STATUS_COMPLETE = "complete"

    def __init__(
        self,
        *,
        configured: bool = False,
        reachable: bool = False,
        complete: bool = False,
        missing_tables: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        self.configured = configured
        self.reachable = reachable
        self.complete = complete
        self.missing_tables = missing_tables or []
        self.error = error

    @property
    def ready(self) -> bool:
        """Return whether every readiness gate passed."""
        return self.configured and self.reachable and self.complete

    @property
    def status(self) -> str:
        """Return the readiness state of the database for the response body."""
        if not self.configured:
            return DatabaseReadiness.STATUS_UNCONFIGURED
        if not self.reachable:
            return DatabaseReadiness.STATUS_UNREACHABLE
        if not self.complete:
            return DatabaseReadiness.STATUS_SCHEMA_MISSING
        return DatabaseReadiness.STATUS_COMPLETE

    @property
    def reason(self) -> str | None:
        """Return the stable identifier of the readiness failure, if any.

        A database that passed every gate carries no failure, and the value
        must stay empty so that a consumer never reads a failure reason where
        there is only completeness.
        """
        if not self.configured:
            return "DATABASE_UNCONFIGURED"
        if not self.reachable:
            return "DATABASE_UNREACHABLE"
        if not self.complete:
            return "DATABASE_SCHEMA_MISSING"
        return None

    def as_state(self) -> dict[str, Any]:
        """Export the evaluation for the health probe response."""
        state: dict[str, Any] = {
            "configured": self.configured,
            "reachable": self.reachable,
            "complete": self.complete,
            "tables": sorted(get_expected_tables()),
        }
        if self.missing_tables:
            state["missing_tables"] = sorted(self.missing_tables)
        if self.error:
            state["error"] = self.error
        return state


async def check_database_readiness() -> DatabaseReadiness:
    """Evaluate the readiness of the database-backed historian store.

    The gates run in order of cost: a connection that cannot be established
    does not waste a query against a table list it cannot read, and a
    completely empty database names every table it wants instead of an
    engine-level error the operator cannot use.

    Returns:
        The outcome of the evaluation, with every gate that failed named in
        ``missing_tables`` and ``error`` rather than a generic failure.
    """
    configured = bool(settings.DATABASE_URL)
    if not configured:
        return DatabaseReadiness(
            configured=False,
            reachable=False,
            error="no database URL resolved",
        )

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))

            result = await session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            )
            tables = {str(name) for name in result.scalars().all()}
            missing_tables = sorted(get_expected_tables() - tables)
    except Exception as err:  # noqa: BLE001 - the failure names the cause
        logger.warning("The database readiness check failed: %s", err)
        return DatabaseReadiness(
            configured=True,
            reachable=False,
            error=str(err),
        )

    return DatabaseReadiness(
        configured=True,
        reachable=True,
        complete=len(missing_tables) == 0,
        missing_tables=missing_tables,
        error=None,
    )
