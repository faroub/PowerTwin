"""Readiness of the historian database store and the migration that serves it.

The readiness probe answers three different questions, each stronger than the
last, and this module tests them against real state:

1. ``unconfigured`` — the application resolved no database URL at all.
2. ``unreachable`` — the application resolved a URL, but it cannot reach the
   database through it.
3. ``schema_missing`` — the database is reachable, but the migrations of the
   release have not been applied to it.

The engine and the session factory of the historian are replaced per test, so
a test of an unmigrated store never witnesses the schema of a migrated one and
every module-level import stays honest. The migration itself is executed by the
``alembic`` tool inside the test process, the same thing the deployment's
``migrate`` service does.
"""

import os
import socket
import subprocess
import sys
import time
import uuid
from typing import Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.historian import db as historian_db
from backend.app.historian.service import HistorianService

#: The pinned image of a real TimescaleDB. The probe has to compare against the
#: schema of the store the application really talks to.
TIMESCALEDB_IMAGE = (
    "timescale/timescaledb@sha256:5d7a2f9d9d593315368338aa6054fda37d7707b4a12a912e30dcb7523385e2b4"
)
ALEMBIC_COMMAND = [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini"]
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
READINESS_PASSWORD = "pt-readiness-not-a-credential"
READINESS_URL_TEMPLATE = "postgresql+asyncpg://postgres:{password}@127.0.0.1:{port}/powertwin_db"


def _docker_available() -> bool:
    """Return whether a running Docker daemon that the test can spawn."""
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "ID"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        return result.stdout.strip() != ""
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def _free_port() -> int:
    """Return the first free local port of the host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run_command(command: list[str], env: dict[str, str]) -> str:
    """Run a process with the recorded environment and return what it printed."""
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    return result.stdout + result.stderr


def _run_command_with_retries(command: list[str], env: dict[str, str]) -> str:
    """Run a command, retaking an airline-style transient failure.

    A container that just opened its port and a database that is still
    checking its signal can reject one launch of the migration tool; a
    deliberate operator would retry the command in that case, and the test
    does the same.
    """
    output = ""
    fragments = ("connection refused", "connection reset", "timed out", "connect call failed")
    for _attempt in range(12):
        output = _run_command(command, env)
        if output.strip() and not any(fragment in output.lower() for fragment in fragments):
            return output
        time.sleep(1)
    return output


def _fake_table_result(tables) -> Any:
    """Return a result object that yields ``tables`` when the session executes."""

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return tables

    return FakeResult()


def _fake_session_faculties(tables=(), error=None):
    """Build the session class that boards the readiness probe against ``tables``.

    The probe opens a session through `AsyncSessionLocal`, so the patched
    object must behave like the factory the probe already knows: it is called
    once and yields one session.
    """

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, statement):
            if error is not None:
                raise error
            return _fake_table_result(tables)

    return FakeSession()


def _patch_historian_url(tables=(), error=None) -> mock.patch:
    """Return a context manager that boards the readiness probe against ``tables``."""
    return mock.patch.object(
        historian_db,
        "AsyncSessionLocal",
        mock.MagicMock(return_value=_fake_session_faculties(tables, error)),
    )


def _container_ready(name: str, port: int) -> bool:
    """Return whether the server inside the container answers on ``port``."""
    result = subprocess.run(
        ["docker", "exec", name, "sh", "-c", "pg_isready -U postgres -d powertwin_db"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return False

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        try:
            sock.connect(("127.0.0.1", port))
        except OSError:
            # The server process is up but the host port is not yet bound;
            # the probe must not start while the connection is still refused.
            return False
        return True


def _start_container(port: int) -> str:
    """Start a disposable empty TimescaleDB container at ``port`` and name it."""
    name = f"pt-readiness-{uuid.uuid4().hex[:8]}"
    environment = {
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": READINESS_PASSWORD,
        "POSTGRES_DB": "powertwin_db",
    }
    _run_command(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            f"127.0.0.1:{port}:5432",
            "-e",
            f"POSTGRES_USER={environment['POSTGRES_USER']}",
            "-e",
            f"POSTGRES_PASSWORD={environment['POSTGRES_PASSWORD']}",
            "-e",
            f"POSTGRES_DB={environment['POSTGRES_DB']}",
            TIMESCALEDB_IMAGE,
        ],
        dict(os.environ, **environment),
    )

    for _ in range(90):
        if _container_ready(name, port):
            return name
        time.sleep(1)
    raise RuntimeError(f"The container {name} did not become ready in time")


def _stop_container(name: str) -> None:
    """Remove a container the test process no longer needs."""
    _run_command(["docker", "rm", "-f", name], {})


def _engine_for(port: int) -> Any:
    """Return a detached engine and session factory for a given local port."""
    target_url = READINESS_URL_TEMPLATE.format(port=port, password=READINESS_PASSWORD)
    engine = create_async_engine(
        target_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        connect_args={"timeout": 5},
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, session_factory


def _alembic_env(port: int, env: dict[str, str] | None = None) -> dict[str, str]:
    """Build the environment the alembic run reads against ``port``."""
    base = {
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": READINESS_PASSWORD,
        "POSTGRES_SERVER": "127.0.0.1",
        "POSTGRES_PORT": str(port),
        "POSTGRES_DB": "powertwin_db",
        "PYTHONPATH": REPO_ROOT,
    }
    base.update(env or {})
    return base


def _list_tables(port: int) -> list[str]:
    """Return the public tables of the database behind ``port`` sorted."""
    result = subprocess.run(
        [
            "psql",
            "-h",
            "127.0.0.1",
            "-p",
            str(port),
            "-U",
            "postgres",
            "-d",
            "powertwin_db",
            "-t",
            "-c",
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PGPASSWORD=READINESS_PASSWORD),
    )
    return sorted(row.strip() for row in result.stdout.splitlines() if row.strip())


def _count_rows(port: int, table: str) -> int:
    """Return the row count of ``table`` of the database behind ``port``."""
    result = subprocess.run(
        [
            "psql",
            "-h",
            "127.0.0.1",
            "-p",
            str(port),
            "-U",
            "postgres",
            "-d",
            "powertwin_db",
            "-t",
            "-c",
            f"SELECT count(*) FROM {table}",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PGPASSWORD=READINESS_PASSWORD),
    )
    return int(result.stdout.strip())


@pytest.fixture
def port() -> int:
    """A local port the test can bind to without colliding with anything."""
    return _free_port()


# --------------------------------------------------------------------------
# Unit tests of the gated evaluation
# --------------------------------------------------------------------------


def test_expected_tables_holds_every_model_and_the_migration_version() -> None:
    """The comparison must cover every table the ORM declares and the version."""
    tables = historian_db.get_expected_tables()
    assert tables == {
        "alembic_version",
        "alarms_and_events",
        "battery_warranty_metrics",
        "command_records",
        "equipment_inventory",
        "plant_configurations",
        "simulation_runs",
        "telemetry_data",
        "users",
    }


@pytest.mark.asyncio
async def test_readiness_unconfigured_when_no_url_resolves() -> None:
    """The probe reports an unrouted deployment when the URL is missing."""
    with (
        mock.patch.object(historian_db, "settings", mock.MagicMock(DATABASE_URL=None)),
        _patch_historian_url(),
    ):
        readiness = await historian_db.check_database_readiness()

    assert readiness.configured is False
    assert readiness.reachable is False
    assert readiness.complete is False
    assert readiness.ready is False
    assert readiness.status == historian_db.DatabaseReadiness.STATUS_UNCONFIGURED
    assert readiness.reason == "DATABASE_UNCONFIGURED"
    assert readiness.missing_tables == []
    assert readiness.error == "no database URL resolved"


@pytest.mark.asyncio
async def test_readiness_unreachable_when_the_server_refuses_the_connection() -> None:
    """A connection that never answers reports the failure to reach it."""
    with (
        mock.patch.object(historian_db, "settings", mock.MagicMock(DATABASE_URL="not-empty")),
        _patch_historian_url(
            error=ConnectionRefusedError("[Errno 111] Connect call failed ('127.0.0.1', 1)")
        ),
    ):
        readiness = await historian_db.check_database_readiness()

    assert readiness.configured is True
    assert readiness.reachable is False
    assert readiness.complete is False
    assert readiness.ready is False
    assert readiness.status == historian_db.DatabaseReadiness.STATUS_UNREACHABLE
    assert readiness.reason == "DATABASE_UNREACHABLE"
    assert readiness.error is not None
    assert readiness.missing_tables == []


@pytest.mark.asyncio
async def test_readiness_missing_tables_after_empty_schema() -> None:
    """A reachable database that never ran a migration names every missing table."""
    expected = sorted(historian_db.get_expected_tables())
    with (
        mock.patch.object(historian_db, "settings", mock.MagicMock(DATABASE_URL="not-empty")),
        _patch_historian_url(tables=[]),
    ):
        readiness = await historian_db.check_database_readiness()

    assert readiness.configured is True
    assert readiness.reachable is True
    assert readiness.complete is False
    assert readiness.ready is False
    assert readiness.status == historian_db.DatabaseReadiness.STATUS_SCHEMA_MISSING
    assert readiness.reason == "DATABASE_SCHEMA_MISSING"
    assert readiness.missing_tables == expected


@pytest.mark.asyncio
async def test_readiness_complete_when_every_table_exists() -> None:
    """A database that holds every table passes the completeness gate."""
    expected = sorted(historian_db.get_expected_tables())
    with (
        mock.patch.object(historian_db, "settings", mock.MagicMock(DATABASE_URL="not-empty")),
        _patch_historian_url(tables=expected),
    ):
        readiness = await historian_db.check_database_readiness()

    assert readiness.configured is True
    assert readiness.reachable is True
    assert readiness.complete is True
    assert readiness.ready is True
    assert readiness.status == historian_db.DatabaseReadiness.STATUS_COMPLETE
    # A passing evaluation carries no failure reason at all.
    assert readiness.reason is None


@pytest.mark.asyncio
async def test_readiness_as_state_lists_every_table() -> None:
    """The state that the endpoint sends carries the expected table names."""
    expected = sorted(historian_db.get_expected_tables())
    with (
        mock.patch.object(historian_db, "settings", mock.MagicMock(DATABASE_URL="not-empty")),
        _patch_historian_url(tables=expected),
    ):
        readiness = await historian_db.check_database_readiness()

    state = readiness.as_state()
    assert state["tables"] == expected
    assert state["configured"] is True
    assert state["reachable"] is True
    assert state["complete"] is True
    assert "missing_tables" not in state


# --------------------------------------------------------------------------
# Endpoint behavior of the readiness probe
# --------------------------------------------------------------------------


def _health_module_probe() -> Any:
    """Return a patch of the readiness function in the health router module."""
    module = __import__("backend.app.api.health", fromlist=["check_database_readiness"])
    return mock.patch.object(
        module, "check_database_readiness", historian_db.check_database_readiness
    )


def test_readiness_endpoint_reports_not_ready(client: TestClient) -> None:
    """The endpoint reports the reason the readiness gate failed."""
    with (
        mock.patch.object(historian_db, "settings", mock.MagicMock(DATABASE_URL="not-empty")),
        _patch_historian_url(tables=[]),
        _health_module_probe(),
    ):
        response = client.get("/health/readiness")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["database"] == "schema_missing"
    assert data["reason"] == "DATABASE_SCHEMA_MISSING"
    assert data["missing_tables"] == sorted(historian_db.get_expected_tables())


def test_readiness_endpoint_reports_complete(client: TestClient) -> None:
    """The endpoint stays 200 ready when the probe passes."""
    with (
        mock.patch.object(historian_db, "settings", mock.MagicMock(DATABASE_URL="not-empty")),
        _patch_historian_url(tables=sorted(historian_db.get_expected_tables())),
        _health_module_probe(),
    ):
        response = client.get("/health/readiness")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "complete"


# --------------------------------------------------------------------------
# Integration tests of the probe and of the migration
# --------------------------------------------------------------------------


@pytest.fixture
def container(request, port: int) -> int:
    """Start a disposable empty TimescaleDB container for the duration of a test."""
    name = _start_container(port)
    request.addfinalizer(lambda: _stop_container(name))
    return port


#: The readiness probe opens one session through `AsyncSessionLocal`; this
#: helper reassembles the module's pieces, patches them for one call, and tears
#: them down again, so every call starts from a fresh connection pool.
async def _probe_snapshot(port: int, engine: Any, session_factory: Any) -> Any:
    """Board the readiness gate against ``port`` once and return the outcome."""
    with (
        mock.patch.object(historian_db, "engine", engine),
        mock.patch.object(historian_db, "AsyncSessionLocal", session_factory),
        mock.patch.object(
            historian_db,
            "settings",
            mock.MagicMock(
                DATABASE_URL=READINESS_URL_TEMPLATE.format(port=port, password=READINESS_PASSWORD)
            ),
        ),
    ):
        return await historian_db.check_database_readiness()


async def _probe_ready(port: int) -> Any:
    """Return the readiness of the database behind ``port`` at one snapshot.

    A container that just started its Postgres process answers an early
    connection with a reset, so the snapshot retries the same gaze until it
    either resolves the real state of the database or stops being transient.
    """
    engine, session_factory = _engine_for(port)
    try:
        for _attempt in range(90):
            readiness = await _probe_snapshot(port, engine, session_factory)
            if readiness.status != historian_db.DatabaseReadiness.STATUS_UNREACHABLE:
                return readiness
            time.sleep(1)
        return readiness
    finally:
        await engine.dispose()


@pytest.mark.skipif(not _docker_available(), reason="Docker is not available")
async def test_readiness_fails_without_migration(container) -> None:
    """Readiness reports the missing tables of a database that never migrated."""
    port = container

    readiness = await _probe_ready(port)

    assert readiness.ready is False
    assert readiness.status == historian_db.DatabaseReadiness.STATUS_SCHEMA_MISSING
    assert readiness.reason == "DATABASE_SCHEMA_MISSING"
    assert readiness.missing_tables == sorted(historian_db.get_expected_tables())
    assert _list_tables(port) == []
    assert readiness.error is None


@pytest.mark.skipif(not _docker_available(), reason="Docker is not available")
async def test_alembic_upgrade_restores_readiness(container) -> None:
    """An explicit migration run restores the readiness of the endpoint."""
    port = container

    # An empty database never ran a migration, so no prior revision is applied
    # and the first upgrade has to land cleanly.
    output = _run_command_with_retries(
        ALEMBIC_COMMAND + ["upgrade", "001_initial_schema"],
        _alembic_env(port),
    )
    tables = _list_tables(port)
    assert tables == sorted(t for t in historian_db.get_expected_tables() if t != "users")

    # The readiness probe fails again until the next revision is applied: the
    # database moved one revision but still carries a missing table.
    readiness = await _probe_ready(port)
    assert readiness.ready is False
    assert readiness.status == historian_db.DatabaseReadiness.STATUS_SCHEMA_MISSING
    assert readiness.reason == "DATABASE_SCHEMA_MISSING"
    assert readiness.missing_tables == ["users"]

    output = _run_command_with_retries(
        ALEMBIC_COMMAND + ["upgrade", "002_user_accounts"],
        _alembic_env(port),
    )
    assert "Running upgrade 001_initial_schema -> 002_user_accounts" in output

    readiness = await _probe_ready(port)

    assert readiness.ready is True
    assert readiness.status == historian_db.DatabaseReadiness.STATUS_COMPLETE
    assert _list_tables(port) == sorted(historian_db.get_expected_tables())


@pytest.mark.skipif(not _docker_available(), reason="Docker is not available")
async def test_historian_writes_after_the_migration(container) -> None:
    """The historian has to write into the database readiness proved to host."""
    port = container

    _run_command_with_retries(ALEMBIC_COMMAND + ["upgrade", "head"], _alembic_env(port))
    readiness = await _probe_ready(port)
    assert readiness.ready is True
    assert readiness.status == historian_db.DatabaseReadiness.STATUS_COMPLETE

    engine, session_factory = _engine_for(port)
    with (
        mock.patch.object(historian_db, "engine", engine),
        mock.patch.object(historian_db, "AsyncSessionLocal", session_factory),
        mock.patch.object(
            historian_db,
            "settings",
            mock.MagicMock(
                DATABASE_URL=READINESS_URL_TEMPLATE.format(port=port, password=READINESS_PASSWORD)
            ),
        ),
    ):
        service = HistorianService()
        service.record_telemetry(
            tag_id="bms_1_soc",
            equipment_id="battery_container_1",
            val_float=12.5,
            unit="percent",
            timestamp_ns=1700000000000000000,
            source_timestamp_ns=1700000000000000000,
            quality="GOOD",
            source_type="SIMULATED",
            simulation_run_id="RUN_001",
        )
        session = session_factory()
        written = await service.flush_buffer_to_db(session)
        await engine.dispose()

    assert written.telemetry == 1
    assert _count_rows(port, "telemetry_data") == 1
    assert _list_tables(port) == sorted(historian_db.get_expected_tables())
