"""Tests for the battery warranty analysis and its write path.

`AGENTS.md` §1 lists warranty analysis as a mission item. The historian's
`battery_warranty_metrics` table and the read endpoint have existed for a
while, but nothing ever wrote a row, so the screen could only ever say "No
warranty metrics are recorded".

These tests hold the properties that matter:

* the degradation model is **illustrative** and says so (`AGENTS.md` §2.13,
  §2.14);
* the time above 45 degC is accumulated exactly, not on decimated samples;
* the recorder **never changes the plant** — the degradation is reported, not
  applied back;
* the snapshot is written, superseded by a newer one, and never walked
  backwards by a stale one;
* a failed commit loses nothing, and the replay collapses the duplicates the
  snapshot's primary key forbids.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.historian import service as historian_service
from backend.app.historian.query import HistorianQueryEngine
from backend.app.historian.service import FlushCounts, HistorianService
from backend.app.historian.wiring import HISTORIAN_SERVICE_KEY
from backend.app.models.battery.system import BatterySystemConfigModel, GenericBatterySystemModel
from backend.app.simulation.clock import SimulationClock
from backend.app.simulation.context import SimulationContext
from backend.app.simulation.event import EventDispatcher
from backend.app.simulation.random_manager import SeededRandomManager
from backend.app.simulation.runtime import SimulationRuntime
from backend.app.topology.factory import PlantTopologyFactory
from backend.app.warranty.assessment import assess_warranty
from backend.app.warranty.degradation import (
    WARRANTY_STATUS_AT_END_OF_LIFE,
    WARRANTY_STATUS_UNKNOWN,
    WARRANTY_STATUS_WITHIN_WARRANTY,
    DegradationModel,
    DegradationParameters,
)
from backend.app.warranty.parameters import deployment_parameters
from backend.app.warranty.recorder import (
    TEMPERATURE_THRESHOLD_C,
    WARRANTY_RECORDER_PHASE,
    WarrantyRecorder,
)
from backend.app.warranty.wiring import (
    WARRANTY_RECORDER_KEY,
    start_warranty_recorder,
    stop_warranty_recorder,
)

REFERENCE_CONFIG = "configs/reference_10mw_20mwh.yaml"

# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #


class _StubPlant:
    """A plant that holds a fixed list of battery models."""

    def __init__(self, batteries: list[Any]) -> None:
        self.battery_systems = batteries


class _StubSink:
    """A sink that records what the recorder publishes."""

    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []
        self.telemetry: list[dict[str, Any]] = []

    def record_warranty_metrics(self, **kwargs: Any) -> bool:
        self.snapshots.append(dict(kwargs))
        return True

    def record_telemetry(self, **kwargs: Any) -> bool:
        self.telemetry.append(dict(kwargs))
        return True


class _ExistingRow:
    """A row the database already holds."""

    def __init__(self, updated_at_ns: int) -> None:
        self.container_id = "CONTAINER_01"
        self.simulation_run_id = "RUN_001"
        self.updated_at_ns = updated_at_ns
        self.total_energy_throughput_wh = 0.0
        self.equivalent_full_cycles = 0.0
        self.max_temperature_recorded_c = 25.0
        self.time_above_45c_seconds = 0.0
        self.current_soh_pct = 100.0


class _QueryResult:
    """The result shape the query engine reads."""

    def __init__(self, records: list[Any]) -> None:
        self._records = records

    def scalars(self) -> _QueryResult:
        return self

    def first(self) -> Any | None:
        return self._records[0] if self._records else None


class _QuerySession:
    """A session that answers a query with a fixed row and keeps the statement."""

    def __init__(self, records: list[Any]) -> None:
        self.records = records
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _QueryResult:
        self.statements.append(statement)
        return _QueryResult(self.records)


def _warranty_row(**overrides: Any) -> SimpleNamespace:
    """A warranty row shaped the way the historian stores one."""
    values: dict[str, Any] = {
        "container_id": "CONTAINER_01",
        "simulation_run_id": "RUN_001",
        "updated_at_ns": 3_600_000_000_000,
        "total_energy_throughput_wh": 124_500_000.0,
        "equivalent_full_cycles": 6.2,
        "max_temperature_recorded_c": 41.5,
        "time_above_45c_seconds": 12.5,
        "current_soh_pct": 98.4,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _UpsertSession:
    """A session that answers a primary-key lookup with a fixed row."""

    def __init__(self, existing: Any = None, fail_commit: bool = False) -> None:
        self.existing = existing
        self.fail_commit = fail_commit
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False

    def add_all(self, rows: Any) -> None:
        self.added.extend(rows)

    def add(self, model: Any) -> None:
        self.added.append(model)

    async def get(self, _model: Any, _key: Any) -> Any:
        return self.existing

    async def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("the database is unreachable")
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def _context(tick_ns: int = 5_000_000, step_ns: int = 10_000_000) -> SimulationContext:
    """A simulation context positioned at a tick."""
    clock = SimulationClock(step_ns=step_ns, initial_ticks_ns=tick_ns)
    return SimulationContext(
        clock=clock,
        random=SeededRandomManager(seed=42),
        events=EventDispatcher(),
        run_id="RUN_TEST",
        shared_state={},
    )


def _battery(
    container_id: str = "CONTAINER_01",
    capacity_wh: float = 1_000_000.0,
    temperature_c: float = 25.0,
) -> GenericBatterySystemModel:
    """A battery model the recorder can read."""
    model = GenericBatterySystemModel(
        equipment_id=container_id,
        config=BatterySystemConfigModel(
            capacity_wh=capacity_wh,
            nominal_voltage_v=1000.0,
            initial_temp_c=temperature_c,
        ),
    )
    model.temperature_c = temperature_c
    return model


def _record_snapshot(
    service: HistorianService,
    *,
    container_id: str = "CONTAINER_01",
    run_id: str = "RUN_001",
    updated_at_ns: int = 1_000,
    soh_pct: float = 99.0,
) -> None:
    """Put a warranty snapshot into the historian's buffer."""
    service.record_warranty_metrics(
        container_id=container_id,
        simulation_run_id=run_id,
        updated_at_ns=updated_at_ns,
        total_energy_throughput_wh=1000.0,
        equivalent_full_cycles=0.5,
        max_temperature_recorded_c=31.0,
        time_above_45c_seconds=12.0,
        current_soh_pct=soh_pct,
    )


# --------------------------------------------------------------------------- #
# The degradation model
# --------------------------------------------------------------------------- #


class TestTheDegradationModel:
    """The model is illustrative, and it says so."""

    def test_the_parameters_are_marked_illustrative(self) -> None:
        """`AGENTS.md` §2.13 and §2.14: no manufacturer-accuracy claim."""
        assert DegradationParameters().illustrative is True

    def test_a_fresh_container_has_a_full_state_of_health(self) -> None:
        model = DegradationModel()

        assert model.observed_soh_pct(0.0, 0.0, 25.0) == pytest.approx(100.0)

    def test_the_state_of_health_falls_with_elapsed_time(self) -> None:
        model = DegradationModel()
        one_year = 365.25 * 24.0 * 3600.0

        soh = model.observed_soh_pct(one_year, 0.0, 25.0)

        assert soh < 100.0
        assert soh == pytest.approx(100.0 - DegradationParameters().calendar_fade_pct_per_year)

    def test_the_state_of_health_falls_with_cycling(self) -> None:
        model = DegradationModel()

        soh = model.observed_soh_pct(0.0, 1000.0, 25.0)

        assert soh == pytest.approx(100.0 - DegradationParameters().cycle_fade_pct_per_1000_efc)

    def test_a_hot_container_fades_faster(self) -> None:
        model = DegradationModel()
        one_year = 365.25 * 24.0 * 3600.0

        cool = model.observed_soh_pct(one_year, 0.0, 25.0)
        hot = model.observed_soh_pct(one_year, 0.0, 55.0)

        assert hot < cool

    def test_the_state_of_health_never_goes_below_zero(self) -> None:
        model = DegradationModel()

        soh = model.observed_soh_pct(365.25 * 24.0 * 3600.0 * 500.0, 100_000.0, 80.0)

        assert soh == 0.0

    def test_a_negative_history_is_refused(self) -> None:
        model = DegradationModel()

        with pytest.raises(ValueError, match="negative"):
            model.observed_soh_pct(-1.0, 0.0, 25.0)

    def test_the_projection_continues_the_observed_duty(self) -> None:
        """A container that cycles keeps cycling in the projection."""
        model = DegradationModel()
        one_year = 365.25 * 24.0 * 3600.0

        cycled = model.projected_soh_pct(
            current_soh_pct=90.0,
            elapsed_seconds=one_year,
            equivalent_full_cycles=500.0,
            temperature_c=25.0,
            horizon_years=10.0,
        )
        idle = model.projected_soh_pct(
            current_soh_pct=90.0,
            elapsed_seconds=one_year,
            equivalent_full_cycles=0.0,
            temperature_c=25.0,
            horizon_years=10.0,
        )

        assert cycled < idle

    def test_the_projection_never_goes_below_zero(self) -> None:
        model = DegradationModel()

        projected = model.projected_soh_pct(
            current_soh_pct=1.0,
            elapsed_seconds=1.0,
            equivalent_full_cycles=0.0,
            temperature_c=25.0,
            horizon_years=50.0,
        )

        assert projected == 0.0

    def test_the_verdict_is_within_the_warranty_above_the_threshold(self) -> None:
        model = DegradationModel()

        assert model.warranty_status(85.0) == WARRANTY_STATUS_WITHIN_WARRANTY

    def test_the_verdict_is_at_the_end_of_life_at_the_threshold(self) -> None:
        model = DegradationModel()
        threshold = DegradationParameters().warranty_threshold_soh_pct

        assert model.warranty_status(threshold) == WARRANTY_STATUS_AT_END_OF_LIFE
        assert model.warranty_status(threshold - 1.0) == WARRANTY_STATUS_AT_END_OF_LIFE

    def test_the_verdict_is_unknown_without_a_state_of_health(self) -> None:
        model = DegradationModel()

        assert model.warranty_status(None) == WARRANTY_STATUS_UNKNOWN
        assert model.warranty_status(float("nan")) == WARRANTY_STATUS_UNKNOWN


class TestTheAssessment:
    """The recorder and the read path have to agree on the numbers."""

    def test_the_assessment_reports_the_verdict_and_the_projection(self) -> None:
        assessment = assess_warranty(
            current_soh_pct=90.0,
            equivalent_full_cycles=100.0,
            elapsed_seconds=365.25 * 24.0 * 3600.0,
            max_temperature_recorded_c=30.0,
        )

        assert assessment.warranty_status == WARRANTY_STATUS_WITHIN_WARRANTY
        assert assessment.projected_soh_pct is not None
        assert assessment.projected_soh_pct < 90.0
        assert assessment.warranty_threshold_pct == 70.0
        assert assessment.illustrative is True

    def test_a_projection_that_cannot_be_computed_stays_unknown(self) -> None:
        """A missing number must not read like a measured one."""
        assessment = assess_warranty(
            current_soh_pct=None,
            equivalent_full_cycles=100.0,
            elapsed_seconds=1000.0,
            max_temperature_recorded_c=30.0,
        )

        assert assessment.warranty_status == WARRANTY_STATUS_UNKNOWN
        assert assessment.projected_soh_pct is None
        assert assessment.current_soh_pct is None

    def test_a_missing_temperature_leaves_the_projection_unknown(self) -> None:
        assessment = assess_warranty(
            current_soh_pct=90.0,
            equivalent_full_cycles=100.0,
            elapsed_seconds=1000.0,
            max_temperature_recorded_c=None,
        )

        assert assessment.projected_soh_pct is None
        # The verdict is still reported: a known state of health is worth
        # reporting on its own.
        assert assessment.warranty_status == WARRANTY_STATUS_WITHIN_WARRANTY

    def test_the_annual_cycle_rate_is_derived_from_the_observed_duty(self) -> None:
        one_year = 365.25 * 24.0 * 3600.0

        assessment = assess_warranty(
            current_soh_pct=90.0,
            equivalent_full_cycles=500.0,
            elapsed_seconds=one_year,
            max_temperature_recorded_c=30.0,
        )

        assert assessment.annual_equivalent_full_cycles == pytest.approx(500.0)

    def test_no_elapsed_time_means_no_cycle_rate(self) -> None:
        """A rate over no time is not a rate."""
        assessment = assess_warranty(
            current_soh_pct=100.0,
            equivalent_full_cycles=500.0,
            elapsed_seconds=0.0,
            max_temperature_recorded_c=30.0,
        )

        assert assessment.annual_equivalent_full_cycles == 0.0


# --------------------------------------------------------------------------- #
# The recorder
# --------------------------------------------------------------------------- #


class TestTheWarrantyRecorder:
    """The recorder observes the plant and never changes it."""

    def test_the_recorder_runs_in_the_last_phase_after_the_historian(self) -> None:
        """The snapshot and the telemetry sample describe the same plant."""
        recorder = WarrantyRecorder(
            plant=_StubPlant([_battery()]), sink=_StubSink(), run_id="RUN_001"
        )

        assert recorder.phase == WARRANTY_RECORDER_PHASE
        assert recorder.priority > 100
        assert recorder.interval_ticks == 1

    def test_the_recorder_runs_on_every_tick(self) -> None:
        """The time above 45 degC is an integral, so it cannot be decimated."""
        recorder = WarrantyRecorder(
            plant=_StubPlant([_battery()]), sink=_StubSink(), run_id="RUN_001"
        )

        assert recorder.interval_ticks == 1

    def test_the_recorder_does_not_change_the_plant(self) -> None:
        """The degradation is reported, not applied back."""
        battery = _battery()
        plant = _StubPlant([battery])
        recorder = WarrantyRecorder(plant=plant, sink=_StubSink(), run_id="RUN_001")

        before = (
            battery.soc_pct,
            battery.soh_pct,
            battery.temperature_c,
            battery.active_power_w,
            battery.total_throughput_wh,
        )
        for tick in range(1, 20):
            recorder.execute(_context(tick_ns=tick * 10_000_000))
        after = (
            battery.soc_pct,
            battery.soh_pct,
            battery.temperature_c,
            battery.active_power_w,
            battery.total_throughput_wh,
        )

        assert before == after

    def test_the_time_above_the_threshold_is_accumulated_exactly(self) -> None:
        """Ten hot ticks of 10 ms are 0.1 s, not a decimated sample of it."""
        battery = _battery(temperature_c=TEMPERATURE_THRESHOLD_C + 5.0)
        sink = _StubSink()
        recorder = WarrantyRecorder(
            plant=_StubPlant([battery]), sink=sink, run_id="RUN_001", sample_interval_ticks=1
        )

        for tick in range(1, 11):
            recorder.execute(_context(tick_ns=tick * 10_000_000))

        snapshot = sink.snapshots[-1]
        assert snapshot["time_above_45c_seconds"] == pytest.approx(0.1)

    def test_a_cold_container_accumulates_no_hot_time(self) -> None:
        battery = _battery(temperature_c=20.0)
        sink = _StubSink()
        recorder = WarrantyRecorder(
            plant=_StubPlant([battery]), sink=sink, run_id="RUN_001", sample_interval_ticks=1
        )

        for tick in range(1, 11):
            recorder.execute(_context(tick_ns=tick * 10_000_000))

        assert sink.snapshots[-1]["time_above_45c_seconds"] == pytest.approx(0.0)

    def test_the_highest_temperature_is_recorded(self) -> None:
        battery = _battery(temperature_c=25.0)
        sink = _StubSink()
        recorder = WarrantyRecorder(
            plant=_StubPlant([battery]), sink=sink, run_id="RUN_001", sample_interval_ticks=1
        )

        battery.temperature_c = 47.5
        recorder.execute(_context(tick_ns=10_000_000))
        battery.temperature_c = 30.0
        recorder.execute(_context(tick_ns=20_000_000))

        assert sink.snapshots[-1]["max_temperature_recorded_c"] == pytest.approx(47.5)

    def test_the_snapshot_is_published_at_the_sample_interval(self) -> None:
        sink = _StubSink()
        recorder = WarrantyRecorder(
            plant=_StubPlant([_battery()]),
            sink=sink,
            run_id="RUN_001",
            sample_interval_ticks=10,
        )

        for tick in range(1, 12):
            recorder.execute(_context(tick_ns=tick * 10_000_000))

        # The first tick publishes, the next nine do not, and the eleventh does.
        assert len(sink.snapshots) == 2
        assert [row["updated_at_ns"] for row in sink.snapshots] == [10_000_000, 110_000_000]

    def test_the_equivalent_full_cycles_come_from_the_throughput(self) -> None:
        """One full cycle is two times the capacity in throughput."""
        battery = _battery(capacity_wh=1_000_000.0)
        sink = _StubSink()
        recorder = WarrantyRecorder(
            plant=_StubPlant([battery]), sink=sink, run_id="RUN_001", sample_interval_ticks=1
        )

        battery.total_throughput_wh = 2_000_000.0
        recorder.execute(_context(tick_ns=10_000_000))

        assert sink.snapshots[-1]["equivalent_full_cycles"] == pytest.approx(1.0)

    def test_the_snapshot_carries_every_metric(self) -> None:
        """The ORM's client-side defaults would turn "not recorded" into a
        misleading zero, so every column is set explicitly.
        """
        battery = _battery()
        sink = _StubSink()
        recorder = WarrantyRecorder(
            plant=_StubPlant([battery]), sink=sink, run_id="RUN_001", sample_interval_ticks=1
        )

        recorder.execute(_context(tick_ns=10_000_000))
        snapshot = sink.snapshots[-1]

        assert set(snapshot) == {
            "container_id",
            "simulation_run_id",
            "updated_at_ns",
            "total_energy_throughput_wh",
            "equivalent_full_cycles",
            "max_temperature_recorded_c",
            "time_above_45c_seconds",
            "current_soh_pct",
        }

    def test_the_recorder_publishes_the_time_series(self) -> None:
        battery = _battery()
        sink = _StubSink()
        recorder = WarrantyRecorder(
            plant=_StubPlant([battery]), sink=sink, run_id="RUN_001", sample_interval_ticks=1
        )

        recorder.execute(_context(tick_ns=10_000_000))

        tags = {row["tag_id"] for row in sink.telemetry}
        assert "warranty.current_soh_pct" in tags
        assert "warranty.projected_soh_pct" in tags
        assert "warranty.equivalent_full_cycles" in tags
        assert "warranty.total_throughput_wh" in tags
        assert "warranty.max_temperature_c" in tags
        assert "warranty.time_above_45c_s" in tags
        assert all(row["equipment_id"] == "CONTAINER_01" for row in sink.telemetry)
        assert all(row["simulation_run_id"] == "RUN_001" for row in sink.telemetry)

    def test_the_recorder_publishes_the_projection_the_read_path_reproduces(self) -> None:
        """The recorder and the read path must not disagree on the number."""
        battery = _battery(temperature_c=40.0)
        sink = _StubSink()
        recorder = WarrantyRecorder(
            plant=_StubPlant([battery]), sink=sink, run_id="RUN_001", sample_interval_ticks=1
        )

        battery.total_throughput_wh = 500_000.0
        recorder.execute(_context(tick_ns=60_000_000_000))

        published = next(
            row["val_float"]
            for row in sink.telemetry
            if row["tag_id"] == "warranty.projected_soh_pct"
        )
        snapshot = sink.snapshots[-1]

        replayed = assess_warranty(
            current_soh_pct=snapshot["current_soh_pct"],
            equivalent_full_cycles=snapshot["equivalent_full_cycles"],
            elapsed_seconds=snapshot["updated_at_ns"] / 1_000_000_000.0,
            max_temperature_recorded_c=snapshot["max_temperature_recorded_c"],
        )

        assert replayed.projected_soh_pct == pytest.approx(published)

    def test_a_defect_never_becomes_a_simulation_fault(self) -> None:
        class _BrokenSink(_StubSink):
            def record_warranty_metrics(self, **kwargs: Any) -> bool:
                raise RuntimeError("the sink is broken")

        recorder = WarrantyRecorder(
            plant=_StubPlant([_battery()]), sink=_BrokenSink(), run_id="RUN_001"
        )

        recorder.execute(_context())

        assert recorder.status["errors"] == 1
        assert recorder.status["last_error"] is not None

    def test_the_status_describes_what_was_analysed(self) -> None:
        recorder = WarrantyRecorder(
            plant=_StubPlant([_battery(), _battery("CONTAINER_02")]),
            sink=_StubSink(),
            run_id="RUN_001",
        )

        status = recorder.status

        assert status["containers"] == 2
        assert status["run_id"] == "RUN_001"
        assert status["illustrative"] is True


# --------------------------------------------------------------------------- #
# The historian write path
# --------------------------------------------------------------------------- #


class TestTheWarrantyWritePath:
    """The snapshot is written, superseded, and never walked backwards."""

    def test_a_snapshot_is_written_to_the_database(self) -> None:
        service = HistorianService()
        _record_snapshot(service)

        session = _UpsertSession()
        written = asyncio_run(service.flush_buffer_to_db(cast("AsyncSession", session)))

        assert written.warranty == 1
        assert session.committed is True
        assert len(session.added) == 1
        assert session.added[0].container_id == "CONTAINER_01"

    def test_a_newer_snapshot_replaces_the_older_one(self) -> None:
        """The table holds one row per container and run."""
        service = HistorianService()
        _record_snapshot(service, updated_at_ns=100, soh_pct=95.0)
        _record_snapshot(service, updated_at_ns=200, soh_pct=90.0)

        assert service.get_buffer_status()["warranty_snapshot_count"] == 1

        session = _UpsertSession()
        written = asyncio_run(service.flush_buffer_to_db(cast("AsyncSession", session)))

        assert written.warranty == 1
        assert session.added[0].current_soh_pct == pytest.approx(90.0)

    def test_an_existing_row_is_updated_and_not_duplicated(self) -> None:
        service = HistorianService()
        _record_snapshot(service, updated_at_ns=200, soh_pct=90.0)

        existing = _ExistingRow(updated_at_ns=100)
        session = _UpsertSession(existing=existing)
        written = asyncio_run(service.flush_buffer_to_db(cast("AsyncSession", session)))

        assert written.warranty == 1
        assert session.added == []
        assert existing.current_soh_pct == pytest.approx(90.0)

    def test_a_stale_snapshot_never_walks_the_history_backwards(self) -> None:
        """A late snapshot must not overwrite a newer one that is already stored."""
        service = HistorianService()
        _record_snapshot(service, updated_at_ns=100, soh_pct=95.0)

        existing = _ExistingRow(updated_at_ns=200)
        session = _UpsertSession(existing=existing)
        written = asyncio_run(service.flush_buffer_to_db(cast("AsyncSession", session)))

        assert written.warranty == 0
        assert existing.current_soh_pct == pytest.approx(100.0)

    def test_the_snapshot_is_written_in_the_same_transaction_as_the_streams(
        self,
    ) -> None:
        """A reader never sees telemetry without the matching snapshot."""
        service = HistorianService()
        service.record_telemetry("TAG1", "EQ1", 10.0, "V", 100)
        _record_snapshot(service)

        session = _UpsertSession()
        asyncio_run(service.flush_buffer_to_db(cast("AsyncSession", session)))

        assert session.committed is True
        assert len(session.added) == 2  # the telemetry row and the snapshot

    def test_a_failed_commit_preserves_the_snapshot_on_disk(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))
        service = HistorianService()
        _record_snapshot(service)

        session = _UpsertSession(fail_commit=True)
        written = asyncio_run(service.flush_buffer_to_db(cast("AsyncSession", session)))

        assert written == FlushCounts()
        assert session.rolled_back is True

        overflow_file = tmp_path / "warranty_overflow.json"
        assert overflow_file.exists()
        assert "CONTAINER_01" in overflow_file.read_text()

    def test_the_replay_collapses_the_duplicates_the_primary_key_forbids(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))
        service = HistorianService()
        _record_snapshot(service, updated_at_ns=100, soh_pct=95.0)
        _record_snapshot(service, updated_at_ns=200, soh_pct=90.0)

        session = _UpsertSession(fail_commit=True)
        asyncio_run(service.flush_buffer_to_db(cast("AsyncSession", session)))

        replay_session = _UpsertSession()
        written = asyncio_run(service.replay_overflow_to_db(cast("AsyncSession", replay_session)))

        assert written.warranty == 1
        assert len(replay_session.added) == 1
        assert replay_session.added[0].current_soh_pct == pytest.approx(90.0)

    def test_the_replay_upserts_rather_than_inserting(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Two rows with the same key would collide, so the replay updates."""
        monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))
        service = HistorianService()
        _record_snapshot(service, updated_at_ns=100, soh_pct=95.0)

        session = _UpsertSession(fail_commit=True)
        asyncio_run(service.flush_buffer_to_db(cast("AsyncSession", session)))

        existing = _ExistingRow(updated_at_ns=50)
        replay_session = _UpsertSession(existing=existing)
        asyncio_run(service.replay_overflow_to_db(cast("AsyncSession", replay_session)))

        assert replay_session.added == []
        assert existing.current_soh_pct == pytest.approx(95.0)

    def test_the_buffer_status_reports_the_snapshot_count(self) -> None:
        service = HistorianService()
        _record_snapshot(service)
        _record_snapshot(service, container_id="CONTAINER_02")

        assert service.get_buffer_status()["warranty_snapshot_count"] == 2

    def test_the_overflow_status_covers_the_warranty_stream(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))
        service = HistorianService()
        _record_snapshot(service)

        session = _UpsertSession(fail_commit=True)
        asyncio_run(service.flush_buffer_to_db(cast("AsyncSession", session)))

        status = service.get_overflow_status()

        assert status["warranty_overflow"]["pending_records"] == 1
        assert status["total_pending_records"] == 1

    def test_the_flush_counts_name_every_stream(self) -> None:
        """A format string that no longer matches the values is a defect that
        only shows up at run time, so the counts are a named tuple.
        """
        counts = FlushCounts(telemetry=1, commands=2, events=3, warranty=4)

        assert counts.total == 10
        assert counts.telemetry == 1
        assert counts.warranty == 4

    def test_the_warranty_stream_is_not_replayed_as_a_plain_insert(self) -> None:
        """The snapshot has a composite primary key, so a plain insert of two
        rows for the same container would collide.
        """
        assert "warranty_overflow" not in historian_service.OVERFLOW_STREAMS
        assert "warranty_overflow" in historian_service.OVERFLOW_FILE_STEMS


# --------------------------------------------------------------------------- #
# The read path
# --------------------------------------------------------------------------- #


class TestTheWarrantyReadPath:
    """The screen must not show a number the recorder did not write."""

    def test_the_read_path_reproduces_the_recorder_projection(self) -> None:
        """The two paths read the same columns with the same arithmetic."""
        battery = _battery(temperature_c=40.0)
        sink = _StubSink()
        recorder = WarrantyRecorder(
            plant=_StubPlant([battery]),
            sink=sink,
            run_id="RUN_001",
            sample_interval_ticks=1,
            parameters=deployment_parameters(),
        )
        battery.total_throughput_wh = 500_000.0
        recorder.execute(_context(tick_ns=60_000_000_000))

        published = next(
            row["val_float"]
            for row in sink.telemetry
            if row["tag_id"] == "warranty.projected_soh_pct"
        )
        snapshot = sink.snapshots[-1]

        session = _QuerySession([_warranty_row(**snapshot)])
        engine = HistorianQueryEngine(cast("AsyncSession", session))
        metrics = asyncio_run(engine.query_warranty_metrics("CONTAINER_01"))

        assert metrics is not None
        assert metrics["projected_soh_pct"] == pytest.approx(published)

    def test_the_read_path_reports_the_verdict(self) -> None:
        session = _QuerySession([_warranty_row(current_soh_pct=98.4)])
        engine = HistorianQueryEngine(cast("AsyncSession", session))

        metrics = asyncio_run(engine.query_warranty_metrics("CONTAINER_01"))

        assert metrics is not None
        assert metrics["warranty_status"] == WARRANTY_STATUS_WITHIN_WARRANTY
        assert metrics["warranty_threshold_pct"] == 70.0
        assert metrics["projection_horizon_years"] == 10.0
        assert metrics["illustrative"] is True

    def test_a_worn_container_is_reported_as_at_the_end_of_its_life(self) -> None:
        session = _QuerySession([_warranty_row(current_soh_pct=65.0)])
        engine = HistorianQueryEngine(cast("AsyncSession", session))

        metrics = asyncio_run(engine.query_warranty_metrics("CONTAINER_01"))

        assert metrics is not None
        assert metrics["warranty_status"] == WARRANTY_STATUS_AT_END_OF_LIFE

    def test_a_row_without_a_state_of_health_is_unknown(self) -> None:
        """A missing number must not read like a measured one."""
        session = _QuerySession([_warranty_row(current_soh_pct=None)])
        engine = HistorianQueryEngine(cast("AsyncSession", session))

        metrics = asyncio_run(engine.query_warranty_metrics("CONTAINER_01"))

        assert metrics is not None
        assert metrics["warranty_status"] == WARRANTY_STATUS_UNKNOWN
        assert metrics["projected_soh_pct"] is None

    def test_the_run_can_be_pinned(self) -> None:
        """The table holds one row per container and run."""
        session = _QuerySession([_warranty_row(simulation_run_id="RUN_002")])
        engine = HistorianQueryEngine(cast("AsyncSession", session))

        asyncio_run(engine.query_warranty_metrics("CONTAINER_01", "RUN_002"))

        statement = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
        assert "simulation_run_id" in statement
        assert "RUN_002" in statement

    def test_without_a_run_the_newest_row_of_any_run_is_answered(self) -> None:
        session = _QuerySession([_warranty_row()])
        engine = HistorianQueryEngine(cast("AsyncSession", session))

        asyncio_run(engine.query_warranty_metrics("CONTAINER_01"))

        statement = str(session.statements[0])
        assert "ORDER BY" in statement
        assert "DESC" in statement

    def test_a_container_the_store_knows_nothing_about_answers_nothing(self) -> None:
        session = _QuerySession([])
        engine = HistorianQueryEngine(cast("AsyncSession", session))

        metrics = asyncio_run(engine.query_warranty_metrics("CONTAINER_99"))

        assert metrics is None


# --------------------------------------------------------------------------- #
# The wiring
# --------------------------------------------------------------------------- #


def _build_app(with_historian: bool = True) -> SimpleNamespace:
    """An application handle with the reference plant attached."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(factory.load_config_from_yaml(REFERENCE_CONFIG))
    runtime = SimulationRuntime()
    runtime.attach_plant(plant)
    state = SimpleNamespace(simulation_runtime=runtime)
    if with_historian:
        setattr(state, HISTORIAN_SERVICE_KEY, HistorianService())
    return SimpleNamespace(state=state)


class TestTheWarrantyWiring:
    """The wiring attaches the recorder to the running plant."""

    def test_the_recorder_is_attached_to_the_running_plant(self) -> None:
        app = _build_app()

        recorder = start_warranty_recorder(app)

        assert recorder is not None
        engine = app.state.simulation_runtime.engine
        assert engine.scheduler.get_task("WARRANTY_RECORDER_TASK") is recorder
        assert getattr(app.state, WARRANTY_RECORDER_KEY) is recorder

    def test_the_recorder_reports_the_engine_run(self) -> None:
        app = _build_app()

        recorder = start_warranty_recorder(app)

        assert recorder is not None
        assert recorder.run_id == app.state.simulation_runtime.engine.simulation_run_id

    def test_attaching_twice_replaces_the_recorder(self) -> None:
        """The scheduler never sees two tasks with the same name."""
        app = _build_app()

        first = start_warranty_recorder(app)
        second = start_warranty_recorder(app)

        assert first is not None
        assert second is not None
        assert first is not second
        engine = app.state.simulation_runtime.engine
        assert engine.scheduler.get_task("WARRANTY_RECORDER_TASK") is second

    def test_stopping_the_recorder_detaches_it(self) -> None:
        app = _build_app()
        recorder = start_warranty_recorder(app)
        assert recorder is not None
        engine = app.state.simulation_runtime.engine

        stop_warranty_recorder(app)

        assert engine.scheduler.get_task("WARRANTY_RECORDER_TASK") is None
        assert getattr(app.state, WARRANTY_RECORDER_KEY) is None

    def test_the_analysis_can_be_switched_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = _build_app()
        monkeypatch.setattr(settings, "WARRANTY_ENABLED", False)

        recorder = start_warranty_recorder(app)

        assert recorder is None
        engine = app.state.simulation_runtime.engine
        assert engine.scheduler.get_task("WARRANTY_RECORDER_TASK") is None

    def test_the_recorder_stays_idle_without_a_historian(self) -> None:
        """With nowhere to write, the recorder does not run at all."""
        app = _build_app(with_historian=False)

        recorder = start_warranty_recorder(app)

        assert recorder is None
        engine = app.state.simulation_runtime.engine
        assert engine.scheduler.get_task("WARRANTY_RECORDER_TASK") is None

    def test_an_application_without_a_plant_starts_no_recorder(self) -> None:
        app = SimpleNamespace(state=SimpleNamespace())

        recorder = start_warranty_recorder(app)

        assert recorder is None

    def test_stopping_a_recorder_that_never_started_is_harmless(self) -> None:
        app = SimpleNamespace(state=SimpleNamespace())

        stop_warranty_recorder(app)

        assert getattr(app.state, WARRANTY_RECORDER_KEY, None) is None

    def test_the_wired_application_records_a_snapshot(self) -> None:
        """The end-to-end property: the running plant fills the table."""
        app = _build_app()
        recorder = start_warranty_recorder(app)
        assert recorder is not None

        engine = app.state.simulation_runtime.engine
        for _ in range(3):
            engine.step(1)

        service = getattr(app.state, HISTORIAN_SERVICE_KEY)
        assert service.get_buffer_status()["warranty_snapshot_count"] > 0
        assert recorder.status["snapshots_published"] >= 1


def asyncio_run(coro: Any) -> Any:
    """Run a coroutine to completion."""
    import asyncio

    return asyncio.run(coro)
