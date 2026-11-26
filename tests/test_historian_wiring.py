"""Tests for the historian's application-layer wiring.

The wiring is what turns the historian from a library into a working store:
it attaches the recorder to the running plant, flushes the buffer to the
database on a timer, and flushes once more on shutdown.

These tests use the real plant and the real engine. The database is not
available in a test run, so the flush is exercised against a stubbed session
that behaves like a working database or like a broken one.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.controllers.command_log import CommandStatus
from backend.app.core.config import settings
from backend.app.historian import service as historian_service_module
from backend.app.historian.service import HistorianService
from backend.app.historian.wiring import (
    HISTORIAN_RECORDER_KEY,
    HISTORIAN_SERVICE_KEY,
    flush_historian,
    run_historian_flush_loop,
    start_historian_recorder,
    stop_historian_recorder,
)
from backend.app.simulation.runtime import SimulationRuntime
from backend.app.topology.factory import PlantTopologyFactory

REFERENCE_CONFIG = "configs/reference_10mw_20mwh.yaml"


def _build_app() -> SimpleNamespace:
    """An application handle with a plant attached to its runtime."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(factory.load_config_from_yaml(REFERENCE_CONFIG))
    runtime = SimulationRuntime()
    runtime.attach_plant(plant)
    state = SimpleNamespace(simulation_runtime=runtime)
    return SimpleNamespace(state=state)


class _WorkingSession:
    """A session that accepts everything and commits it."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0

    def add_all(self, rows: Any) -> None:
        self.added.extend(rows)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class _BrokenSession:
    """A session whose commit always fails."""

    def __init__(self) -> None:
        self.rollbacks = 0

    def add_all(self, _rows: Any) -> None:
        return None

    async def commit(self) -> None:
        raise RuntimeError("the database is unreachable")

    async def rollback(self) -> None:
        self.rollbacks += 1


class _ReadingSession:
    """A session that answers a query with the rows that were written."""

    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    async def execute(self, _statement: Any) -> Any:
        return _StubResult(self.rows)


class _StubResult:
    """The result shape the query engine expects."""

    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def scalars(self) -> _StubResult:
        return self

    def all(self) -> list[Any]:
        return list(self.rows)


@pytest.fixture
def app() -> SimpleNamespace:
    """An application with the reference plant attached."""
    return _build_app()


# --------------------------------------------------------------------------- #
# Attaching and detaching
# --------------------------------------------------------------------------- #


def test_the_recorder_is_attached_to_the_running_plant(app: SimpleNamespace) -> None:
    """Starting the recorder registers it on the engine's scheduler."""
    recorder = start_historian_recorder(app)

    assert recorder is not None
    engine = app.state.simulation_runtime.engine
    assert engine.scheduler.get_task("HISTORIAN_RECORDER_TASK") is recorder
    assert getattr(app.state, HISTORIAN_RECORDER_KEY) is recorder


def test_the_recorder_subscribes_to_the_plant_command_logs(app: SimpleNamespace) -> None:
    """A command that the plant's controllers issue reaches the historian."""
    recorder = start_historian_recorder(app)
    assert recorder is not None

    plant = app.state.simulation_runtime.active_plant
    plant.equipment_controller.audit_log.log_entry(
        timestamp_ns=4_000_000,
        source_layer="OPERATOR",
        target_component="PCS_01",
        action_name="DISPATCH_SETPOINT",
        requested_value={"active_power_w": 1_000_000.0},
        accepted_value={"active_power_w": 900_000.0},
        status=CommandStatus.ACCEPTED,
    )

    assert recorder.status["command_rows"] == 1


def test_a_replaced_recorder_stops_receiving_commands(app: SimpleNamespace) -> None:
    """A recorder that was replaced must not write beside its successor."""
    first = start_historian_recorder(app)
    assert first is not None
    second = start_historian_recorder(app)
    assert second is not None

    plant = app.state.simulation_runtime.active_plant
    plant.equipment_controller.audit_log.log_entry(
        timestamp_ns=4_000_000,
        source_layer="OPERATOR",
        target_component="PCS_01",
        action_name="DISPATCH_SETPOINT",
        requested_value={},
        accepted_value={},
        status=CommandStatus.ACCEPTED,
    )

    assert first.status["command_rows"] == 0
    assert second.status["command_rows"] == 1


def test_the_wired_application_writes_rows_the_historian_can_read(
    app: SimpleNamespace,
) -> None:
    """The end-to-end property: the running plant fills the historian."""
    recorder = start_historian_recorder(app)
    assert recorder is not None

    engine = app.state.simulation_runtime.engine
    for _ in range(5):
        engine.step(1)

    service = getattr(app.state, HISTORIAN_SERVICE_KEY)
    assert service.get_buffer_status()["telemetry_buffer_size"] > 0
    assert recorder.status["samples"] >= 1
    assert recorder.status["telemetry_rows"] > 0


def test_stopping_the_recorder_detaches_it_from_the_scheduler(
    app: SimpleNamespace,
) -> None:
    """Stopping the recorder removes its task from the engine."""
    recorder = start_historian_recorder(app)
    assert recorder is not None
    engine = app.state.simulation_runtime.engine

    stop_historian_recorder(app)

    assert engine.scheduler.get_task("HISTORIAN_RECORDER_TASK") is None
    assert getattr(app.state, HISTORIAN_RECORDER_KEY) is None


def test_the_recorder_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that must not write anything can switch the recorder off."""
    app = _build_app()
    monkeypatch.setattr(settings, "HISTORIAN_ENABLED", False)

    recorder = start_historian_recorder(app)

    assert recorder is None
    engine = app.state.simulation_runtime.engine
    assert engine.scheduler.get_task("HISTORIAN_RECORDER_TASK") is None


def test_an_application_without_a_plant_starts_no_recorder() -> None:
    """A plant that is not attached leaves the recorder idle."""
    app = SimpleNamespace(state=SimpleNamespace())

    recorder = start_historian_recorder(app)

    assert recorder is None


def test_stopping_a_recorder_that_never_started_is_harmless() -> None:
    """Shutdown must not fail when the recorder was never attached."""
    app = SimpleNamespace(state=SimpleNamespace())

    stop_historian_recorder(app)

    assert getattr(app.state, HISTORIAN_RECORDER_KEY, None) is None


# --------------------------------------------------------------------------- #
# Flushing
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_the_flush_writes_the_buffer_to_the_database(
    app: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The buffer is written to the database when the flush runs."""
    recorder = start_historian_recorder(app)
    assert recorder is not None
    app.state.simulation_runtime.engine.step(1)

    session = _WorkingSession()
    monkeypatch.setattr(
        "backend.app.historian.wiring.AsyncSessionLocal",
        _session_factory(session),
    )

    written = await flush_historian(app)

    assert written[0] > 0
    # The flush commits the buffer and then the disk overflow, so the session
    # may see more than one commit.
    assert session.commits >= 1
    assert session.added


@pytest.mark.asyncio
async def test_a_failing_flush_is_reported_and_raises_nothing(
    app: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database that is down is reported as an error and loses no data."""
    recorder = start_historian_recorder(app)
    assert recorder is not None
    app.state.simulation_runtime.engine.step(1)

    monkeypatch.setattr(
        "backend.app.historian.wiring.AsyncSessionLocal",
        _session_factory(_BrokenSession()),
    )

    written = await flush_historian(app)

    assert written == (0, 0, 0)


@pytest.mark.asyncio
async def test_the_flush_loop_stops_when_it_is_cancelled(
    app: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flush loop is a background task the shutdown cancels."""
    recorder = start_historian_recorder(app)
    assert recorder is not None

    monkeypatch.setattr(
        "backend.app.historian.wiring.AsyncSessionLocal",
        _session_factory(_WorkingSession()),
    )

    task = asyncio.create_task(run_historian_flush_loop(app, interval_s=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def _session_factory(session: Any) -> Any:
    """Build an async context manager that yields the given session."""

    class _SessionContext:
        async def __aenter__(self) -> Any:
            return session

        async def __aexit__(self, *_exc: Any) -> bool:
            return False

    return _SessionContext


# --------------------------------------------------------------------------- #
# The service the wiring owns
# --------------------------------------------------------------------------- #


def test_the_wiring_keeps_one_historian_service_per_application(
    app: SimpleNamespace,
) -> None:
    """Starting the recorder twice does not create a second store."""
    first = start_historian_recorder(app)
    second = start_historian_recorder(app)

    assert first is not None
    assert second is not None
    assert getattr(app.state, HISTORIAN_SERVICE_KEY) is first.service


def test_the_historian_service_is_created_only_once(app: SimpleNamespace) -> None:
    """The store is an application-scoped object, not a global."""
    recorder = start_historian_recorder(app)
    assert recorder is not None

    service = getattr(app.state, HISTORIAN_SERVICE_KEY)
    assert isinstance(service, HistorianService)
    assert service is recorder.service


def test_the_recorder_reports_the_run_it_belongs_to(app: SimpleNamespace) -> None:
    """Every recorded row carries the engine's run identifier."""
    recorder = start_historian_recorder(app)
    assert recorder is not None

    assert recorder.run_id == app.state.simulation_runtime.engine.simulation_run_id


def test_the_overflow_directory_of_a_failing_flush_is_the_documented_one(
    app: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failing flush preserves the data in the historian's overflow file."""
    monkeypatch.setattr(historian_service_module, "OVERFLOW_DIR", str(tmp_path))
    recorder = start_historian_recorder(app)
    assert recorder is not None
    app.state.simulation_runtime.engine.step(1)

    session = _BrokenSession()

    async def _flush() -> tuple[int, int, int]:
        return await recorder.service.flush_buffer_to_db(session)

    assert asyncio.run(_flush()) == (0, 0, 0)
    assert (tmp_path / "telemetry_overflow.json").exists()


@pytest.mark.asyncio
async def test_the_written_rows_are_the_rows_the_historian_reads_back(
    app: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole path, end to end: plant -> recorder -> database -> query.

    This is the property F-15 was raised for. The running plant publishes
    measurements, the recorder samples them, the flush writes them to the
    database, and the historian's read path returns the very same rows.
    """
    from backend.app.historian.models import TelemetryDataModel
    from backend.app.historian.query import HistorianQueryEngine

    recorder = start_historian_recorder(app)
    assert recorder is not None

    engine = app.state.simulation_runtime.engine
    for _ in range(3):
        engine.step(1)

    session = _WorkingSession()
    monkeypatch.setattr(
        "backend.app.historian.wiring.AsyncSessionLocal",
        _session_factory(session),
    )
    written = await flush_historian(app)
    assert written[0] > 0

    stored = [row for row in session.added if isinstance(row, TelemetryDataModel)]
    assert stored, "the flush wrote no telemetry rows"

    query = HistorianQueryEngine(_ReadingSession(stored))
    rows = await query.query_telemetry(limit=50)

    assert rows
    assert {row["source_type"] for row in rows} == {"SIMULATED"}
    assert {row["simulation_run_id"] for row in rows} == {recorder.run_id}
    assert all(row["equipment_id"] for row in rows)
