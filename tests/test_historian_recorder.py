"""Tests for the historian recorder — the application layer's write path.

The historian subsystem (ring buffer, disk overflow, database flush) and its
read-only query API were implemented and unit-tested before anything called
them. These tests drive the missing half: the recorder that turns the running
plant into historian rows.

The properties that matter are stated here as tests:

* the recorder samples the plant's published measurements,
* it samples on tick boundaries, not on wall-clock time,
* it records an alarm once when it is raised and once when it is cleared,
* a command reaches the historian through the plant's own command log,
* a defect in the recorder never becomes a simulation fault,
* the engine does not depend on the database.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.equipment.models import (
    AlarmRecord,
    AlarmSeverity,
    EquipmentMetadata,
    EquipmentType,
    OperatingState,
    QualityFlag,
    TelemetryPoint,
    UniversalEquipmentState,
)
from backend.app.historian import service as historian_service_module
from backend.app.historian.recorder import HistorianRecorder
from backend.app.historian.service import HistorianService
from backend.app.simulation.clock import SimulationClock
from backend.app.simulation.context import SimulationContext
from backend.app.simulation.event import EventDispatcher
from backend.app.simulation.random_manager import SeededRandomManager
from backend.app.topology.factory import PlantTopologyFactory

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_CONFIG = "configs/reference_10mw_20mwh.yaml"


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #


class _StubModel:
    """A plant model that publishes a fixed state."""

    def __init__(self, state: UniversalEquipmentState) -> None:
        self._state = state

    def get_state(self) -> UniversalEquipmentState:
        return self._state


def _state(
    equipment_id: str,
    equipment_type: EquipmentType = EquipmentType.BATTERY_SYSTEM,
    measurements: dict[str, TelemetryPoint] | None = None,
    alarms: list[AlarmRecord] | None = None,
) -> UniversalEquipmentState:
    return UniversalEquipmentState(
        equipment_id=equipment_id,
        equipment_type=equipment_type,
        metadata=EquipmentMetadata(manufacturer="Generic BESS"),
        operating_state=OperatingState.RUNNING,
        timestamp_ns=1_000,
        measurements=measurements or {},
        alarms=alarms or [],
    )


def _measurement(value: float, unit: str = "V") -> TelemetryPoint:
    return TelemetryPoint(
        value=value,
        unit=unit,
        timestamp_ns=1_000,
        quality=QualityFlag.GOOD,
        source_id="SOURCE_01",
    )


class _StubPlant:
    """A plant that publishes the states it was given."""

    def __init__(self, states: list[UniversalEquipmentState]) -> None:
        self.battery_systems = [_StubModel(state) for state in states]
        self.bms_units: list[Any] = []
        self.pcs_units: list[Any] = []
        self.transformers: list[Any] = []
        self.switchgear: list[Any] = []
        self.meters: list[Any] = []
        self.poi: Any = None
        self.grid: Any = None
        self.equipment_controller: Any = None
        self.ems: Any = None
        self.ppc: Any = None


def _context(tick_ns: int = 5_000_000) -> SimulationContext:
    """A simulation context positioned at a tick."""
    clock = SimulationClock(step_ns=10_000_000, initial_ticks_ns=tick_ns)
    return SimulationContext(
        clock=clock,
        random=SeededRandomManager(seed=42),
        events=EventDispatcher(),
        run_id="RUN_TEST",
        shared_state={},
    )


def _drain(service: HistorianService) -> list[dict[str, Any]]:
    """Take everything the historian's telemetry queue holds."""
    rows: list[dict[str, Any]] = []
    while not service._telemetry_queue.empty():
        rows.append(service._telemetry_queue.get_nowait())
    return rows


def _drain_alarms(service: HistorianService) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    while not service._event_queue.empty():
        rows.append(service._event_queue.get_nowait())
    return rows


def _drain_commands(service: HistorianService) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    while not service._command_queue.empty():
        rows.append(service._command_queue.get_nowait())
    return rows


def _build_reference_plant() -> Any:
    factory = PlantTopologyFactory()
    return factory.build_plant(factory.load_config_from_yaml(REFERENCE_CONFIG))


# --------------------------------------------------------------------------- #
# Telemetry
# --------------------------------------------------------------------------- #


def test_the_recorder_records_the_measurements_the_plant_publishes() -> None:
    """Every measurement of every piece of equipment reaches the historian."""
    service = HistorianService()
    plant = _StubPlant(
        [
            _state(
                "CONTAINER_01",
                measurements={
                    "voltage_v": _measurement(812.4),
                    "soc_pct": _measurement(55.0, "pct"),
                },
            ),
            _state("PCS_01", measurements={"active_power_w": _measurement(2_500_000.0, "W")}),
        ]
    )
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_01", interval_ticks=1)

    recorder.execute(_context())

    rows = _drain(service)
    assert len(rows) == 3
    by_tag = {(row["equipment_id"], row["tag_id"]): row for row in rows}
    assert by_tag[("CONTAINER_01", "voltage_v")]["val_float"] == 812.4
    assert by_tag[("CONTAINER_01", "voltage_v")]["unit"] == "V"
    assert by_tag[("CONTAINER_01", "soc_pct")]["unit"] == "pct"
    assert by_tag[("PCS_01", "active_power_w")]["val_float"] == 2_500_000.0


def test_every_recorded_row_carries_the_run_the_tick_and_the_quality() -> None:
    """Every row carries a timestamp, a quality, a source and a run identifier."""
    service = HistorianService()
    plant = _StubPlant([_state("CONTAINER_01", measurements={"voltage_v": _measurement(812.4)})])
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_42", interval_ticks=1)

    recorder.execute(_context(tick_ns=7_000_000))

    row = _drain(service)[0]
    assert row["timestamp_ns"] == 7_000_000
    assert row["source_timestamp_ns"] == 1_000
    assert row["quality"] == "GOOD"
    assert row["source_type"] == "SIMULATED"
    assert row["simulation_run_id"] == "RUN_42"


def test_a_sample_that_finds_nothing_records_nothing() -> None:
    """A plant with no measurements produces no rows, and no error."""
    service = HistorianService()
    plant = _StubPlant([_state("CONTAINER_01")])
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_01", interval_ticks=1)

    recorder.execute(_context())

    assert _drain(service) == []
    assert recorder.status["telemetry_rows"] == 0
    assert recorder.status["last_error"] is None


def test_the_recorder_samples_the_real_plant() -> None:
    """The reference plant publishes measurements, and they reach the historian."""
    service = HistorianService()
    plant = _build_reference_plant()
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_01", interval_ticks=1)

    plant.simulation_engine.step(1)
    recorder.execute(_context(tick_ns=plant.simulation_engine.clock.time_ns))

    rows = _drain(service)
    assert rows, "the reference plant published no measurements"
    assert {row["source_type"] for row in rows} == {"SIMULATED"}
    assert all(row["simulation_run_id"] == "RUN_01" for row in rows)


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_the_recorder_samples_on_tick_boundaries_and_not_on_wall_clock_time() -> None:
    """The recorder is a scheduled task, so the scheduler decimates it.

    A recorder driven by a wall-clock timer would produce a series that
    depends on how fast the host happened to be, and a replay would not
    reproduce it. The recorder is therefore registered as a task with an
    ``interval_ticks`` decimation, and the scheduler decides when it runs.
    """
    plant = _StubPlant([_state("CONTAINER_01", measurements={"voltage_v": _measurement(812.4)})])
    recorder = HistorianRecorder(
        plant=plant, service=HistorianService(), run_id="RUN_01", interval_ticks=10
    )

    assert recorder.interval_ticks == 10
    assert recorder.phase == 6
    assert recorder.enabled is True

    # The scheduler is what applies the decimation: a task with an interval
    # of 10 runs on every tenth tick and not before.
    real_plant = _build_reference_plant()
    real_plant.simulation_engine.scheduler.register_task(recorder)

    for _ in range(30):
        real_plant.simulation_engine.step(1)

    assert recorder.execution_count == 3


def test_the_recorder_does_not_change_what_the_simulation_computes() -> None:
    """Attaching the recorder leaves the run's fingerprint untouched.

    The recorder only reads the plant. It never writes back into it and never
    consumes the simulation's random source, so the run it observes is the
    run the engine would have produced alone.
    """

    def fingerprint(plant: Any) -> str:
        plant.simulation_engine.run_headless(50)
        return f"{plant.simulation_engine.clock.time_ns}:{plant.battery_systems[0].soc_pct:.6f}"

    alone = fingerprint(_build_reference_plant())

    plant = _build_reference_plant()
    recorder = HistorianRecorder(
        plant=plant, service=HistorianService(), run_id="RUN_01", interval_ticks=1
    )
    plant.simulation_engine.scheduler.register_task(recorder)

    assert fingerprint(plant) == alone


# --------------------------------------------------------------------------- #
# Alarms
# --------------------------------------------------------------------------- #


def test_an_alarm_is_recorded_once_when_it_is_raised() -> None:
    """An alarm that stays active is written once, not on every sample."""
    service = HistorianService()
    alarm = AlarmRecord(
        code="OVER_TEMP_FAULT",
        severity=AlarmSeverity.FAULT,
        description="The container is too hot.",
        timestamp_ns=1_000,
        source_id="CONTAINER_01",
    )
    plant = _StubPlant([_state("CONTAINER_01", alarms=[alarm])])
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_01", interval_ticks=1)

    recorder.execute(_context())
    recorder.execute(_context(tick_ns=6_000_000))
    recorder.execute(_context(tick_ns=7_000_000))

    rows = _drain_alarms(service)
    assert len(rows) == 1
    assert rows[0]["code"] == "OVER_TEMP_FAULT"
    assert rows[0]["severity"] == "FAULT"
    assert rows[0]["equipment_id"] == "CONTAINER_01"


def test_an_alarm_is_recorded_again_when_it_is_cleared() -> None:
    """A clear is a separate statement about the plant, and it is recorded."""
    service = HistorianService()
    alarm = AlarmRecord(
        code="OVER_TEMP_FAULT",
        severity=AlarmSeverity.FAULT,
        description="The container is too hot.",
        timestamp_ns=1_000,
        source_id="CONTAINER_01",
    )
    plant = _StubPlant([_state("CONTAINER_01", alarms=[alarm])])
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_01", interval_ticks=1)

    recorder.execute(_context())
    plant.battery_systems[0]._state = _state("CONTAINER_01")
    recorder.execute(_context(tick_ns=6_000_000))

    rows = _drain_alarms(service)
    assert len(rows) == 2
    assert rows[1]["event_id"].endswith("_CLEARED")
    assert rows[1]["code"] == "OVER_TEMP_FAULT"
    assert "cleared" in rows[1]["description"].lower()


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def test_a_command_reaches_the_historian_through_the_plant_command_log() -> None:
    """The command log stays the single write path for a control action.

    The recorder subscribes to the log rather than wrapping it, so a command
    is written to the time-series store and to the operator-action journal
    from the same entry.
    """
    service = HistorianService()
    audit_log = ControlCommandLog()
    plant = _StubPlant([])
    plant.equipment_controller = type("_Holder", (), {"audit_log": audit_log})()
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_01", interval_ticks=1)

    assert recorder.attach_to_plant() == 1

    audit_log.log_entry(
        timestamp_ns=4_000_000,
        source_layer="OPERATOR",
        target_component="PCS_01",
        action_name="DISPATCH_SETPOINT",
        requested_value={"active_power_w": 1_000_000.0},
        accepted_value={"active_power_w": 900_000.0},
        status=CommandStatus.ACCEPTED,
        reason="SUCCESS",
    )

    rows = _drain_commands(service)
    assert len(rows) == 1
    assert rows[0]["target_equipment_id"] == "PCS_01"
    assert rows[0]["accepted_status"] == "ACCEPTED"
    assert rows[0]["simulation_run_id"] == "RUN_01"
    assert rows[0]["requested_value"]["action_name"] == "DISPATCH_SETPOINT"


def test_a_rejected_command_is_recorded_with_its_reason() -> None:
    """A refused command is a fact about the plant and is recorded as one."""
    service = HistorianService()
    audit_log = ControlCommandLog()
    plant = _StubPlant([])
    plant.ems = type("_Holder", (), {"audit_log": audit_log})()
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_01", interval_ticks=1)
    recorder.attach_to_plant()

    audit_log.log_entry(
        timestamp_ns=4_000_000,
        source_layer="EMS",
        target_component="PCS_02",
        action_name="DISPATCH_SETPOINT",
        requested_value={"active_power_w": 9_000_000.0},
        accepted_value={},
        status=CommandStatus.REJECTED_OUT_OF_BOUNDS,
        reason="The requested power exceeds the rating.",
    )

    rows = _drain_commands(service)
    assert len(rows) == 1
    assert rows[0]["accepted_status"] == "REJECTED_OUT_OF_BOUNDS"
    assert "exceeds the rating" in rows[0]["rejection_reason"]


def test_the_recorder_subscribes_to_every_controller_of_the_real_plant() -> None:
    """Every controller that owns a command log is subscribed."""
    plant = _build_reference_plant()
    recorder = HistorianRecorder(
        plant=plant, service=HistorianService(), run_id="RUN_01", interval_ticks=1
    )

    subscribed = recorder.attach_to_plant()

    assert subscribed >= 1
    assert plant.equipment_controller.audit_log in recorder._control_logs()


def test_a_sink_that_fails_does_not_cost_the_others_their_record() -> None:
    """One broken consumer must not silence the journal or the other sinks."""
    audit_log = ControlCommandLog()
    seen: list[str] = []

    def broken(_entry: Any) -> None:
        raise RuntimeError("the sink is broken")

    def working(entry: Any) -> None:
        seen.append(entry.action_name)

    audit_log.add_sink(broken)
    audit_log.add_sink(working)

    audit_log.log_entry(
        timestamp_ns=1,
        source_layer="OPERATOR",
        target_component="PCS_01",
        action_name="DISPATCH_SETPOINT",
        requested_value={},
        accepted_value={},
        status=CommandStatus.ACCEPTED,
    )

    assert seen == ["DISPATCH_SETPOINT"]
    assert len(audit_log.entries) == 1


# --------------------------------------------------------------------------- #
# Failure behaviour
# --------------------------------------------------------------------------- #


def test_a_defect_in_the_recorder_never_becomes_a_simulation_fault() -> None:
    """A recording defect is reported as an error and never propagates."""

    class _BrokenModel:
        def get_state(self) -> UniversalEquipmentState:
            raise RuntimeError("the model is broken")

    plant = _StubPlant([])
    plant.battery_systems = [_BrokenModel()]
    service = HistorianService()
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_01", interval_ticks=1)

    recorder.execute(_context())

    assert recorder.status["last_error"] is not None
    assert "the model is broken" in recorder.status["last_error"]


def test_one_broken_model_does_not_cost_the_plant_its_sample() -> None:
    """A model that cannot publish its state is skipped, not fatal."""
    service = HistorianService()

    class _BrokenModel:
        def get_state(self) -> UniversalEquipmentState:
            raise RuntimeError("the model is broken")

    plant = _StubPlant([_state("PCS_01", measurements={"active_power_w": _measurement(1.0, "W")})])
    plant.battery_systems = [_BrokenModel(), *plant.battery_systems]
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_01", interval_ticks=1)

    recorder.execute(_context())

    rows = _drain(service)
    assert len(rows) == 1
    assert rows[0]["equipment_id"] == "PCS_01"


def test_the_recorder_writes_into_the_buffer_without_ever_blocking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The historian's queue is bounded, and a full queue spills to disk.

    The recorder must never block the simulation thread, so a full buffer
    spills to the historian's append-only overflow file instead of waiting.
    """
    monkeypatch.setattr(historian_service_module, "OVERFLOW_DIR", str(tmp_path))
    service = HistorianService(max_buffer_size=1)
    plant = _StubPlant(
        [
            _state(
                "CONTAINER_01",
                measurements={
                    "voltage_v": _measurement(812.4),
                    "soc_pct": _measurement(55.0, "pct"),
                },
            )
        ]
    )
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_01", interval_ticks=1)

    recorder.execute(_context())

    # The first row is queued; the second overflowed. Nothing was lost.
    assert service.get_buffer_status()["telemetry_buffer_size"] == 1
    assert recorder.status["telemetry_rows"] == 2

    overflow_file = tmp_path / "telemetry_overflow.json"
    assert overflow_file.exists()
    assert len(overflow_file.read_text().strip().splitlines()) == 1


@pytest.mark.asyncio
async def test_a_failing_flush_keeps_the_data_in_the_overflow_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A database that cannot be written loses nothing and raises nothing."""
    monkeypatch.setattr(historian_service_module, "OVERFLOW_DIR", str(tmp_path))
    service = HistorianService()
    plant = _StubPlant([_state("CONTAINER_01", measurements={"voltage_v": _measurement(812.4)})])
    recorder = HistorianRecorder(plant=plant, service=service, run_id="RUN_01", interval_ticks=1)
    recorder.execute(_context())

    class _FailingSession:
        def add_all(self, _rows: Any) -> None:
            return None

        def add(self, _model: Any) -> None:
            return None

        async def get(self, _model: Any, _key: Any) -> None:
            """No existing row: every write in this double is an insert."""
            return None

        async def commit(self) -> None:
            raise RuntimeError("the database is unreachable")

        async def rollback(self) -> None:
            return None

    written = await service.flush_buffer_to_db(_FailingSession())

    assert written == (0, 0, 0, 0)
    overflow_file = tmp_path / "telemetry_overflow.json"
    assert overflow_file.exists()
    assert "CONTAINER_01" in overflow_file.read_text()


# --------------------------------------------------------------------------- #
# Architecture
# --------------------------------------------------------------------------- #


def test_the_simulation_package_does_not_import_the_database_or_the_historian() -> None:
    """The engine stays independent of the database and of the historian.

    ``AGENTS.md`` §3 requires it. The recorder lives outside the simulation
    package and registers itself as a task, so the dependency runs recorder ->
    engine and never engine -> database.
    """
    simulation_root = REPOSITORY_ROOT / "backend" / "app" / "simulation"
    forbidden = ("backend.app.historian", "sqlalchemy", "asyncpg")

    offenders: list[str] = []
    for path in sorted(simulation_root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if any(name.startswith(bad) for bad in forbidden):
                    offenders.append(f"{path.relative_to(REPOSITORY_ROOT)}: {name}")

    assert offenders == [], f"The simulation package imports the database: {offenders}"


def test_the_recorder_holds_no_database_session() -> None:
    """The recorder writes into a buffer; the flush happens elsewhere."""
    plant = _StubPlant([])
    recorder = HistorianRecorder(
        plant=plant, service=HistorianService(), run_id="RUN_01", interval_ticks=1
    )

    # The recorder's only reference to persistence is the historian service,
    # whose flush methods take a session as an argument.
    assert recorder.service is not None
    assert not hasattr(recorder, "session")
    assert not hasattr(recorder, "_session")


def test_the_recorder_is_registered_as_a_task_on_the_engine_scheduler() -> None:
    """The scheduler, not a timer, decides when the recorder samples."""
    plant = _build_reference_plant()
    recorder = HistorianRecorder(
        plant=plant, service=HistorianService(), run_id="RUN_01", interval_ticks=10
    )

    plant.simulation_engine.scheduler.register_task(recorder)

    assert plant.simulation_engine.scheduler.get_task("HISTORIAN_RECORDER_TASK") is recorder


@pytest.mark.parametrize(
    "field", ["HISTORIAN_ENABLED", "HISTORIAN_SAMPLE_INTERVAL_TICKS", "HISTORIAN_FLUSH_INTERVAL_S"]
)
def test_the_historian_settings_exist_and_are_documented(field: str) -> None:
    """The recorder is configurable and its settings are part of the model."""
    from backend.app.core.config import Settings

    assert field in Settings.model_fields
