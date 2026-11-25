"""Alembic environment configuration."""

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from backend.app.core.config import settings
from backend.app.historian.models import Base
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name:
    # `fileConfig` disables every logger that already exists unless it is
    # told otherwise. The Alembic environment is imported by the migration
    # tooling *inside* the process that owns the audit trail, so the default
    # would switch off the application's loggers — and with them the audit
    # trail that `AGENTS.md` §2.10 requires — without a word.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# The ORM metadata is the second half of the comparison that `alembic check`
# performs: it renders the schema the application expects and compares it with
# the schema the migrations produce. Without it the command cannot detect a
# model that was changed without a migration, which is exactly the drift this
# repository has to catch before a release.
target_metadata = Base.metadata

# `create_hypertable('telemetry_data', 'timestamp_ns', ...)` in migration
# `001_initial_schema` makes TimescaleDB create a descending index on the time
# column. The ORM cannot declare that index because TimescaleDB owns it, and
# it is re-created every time the migration runs, so it must be excluded from
# the comparison rather than mirrored in the models. Excluding it here keeps
# `alembic check` a truthful drift gate instead of one that always reports a
# difference nobody is allowed to fix.
TIMESCALEDB_MANAGED_INDEXES = frozenset({"telemetry_data_timestamp_ns_idx"})


def include_object(
    object: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Exclude indexes that TimescaleDB owns from the autogenerate comparison."""
    if type_ == "index" and name in TIMESCALEDB_MANAGED_INDEXES:
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Any) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations online using asyncio."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
