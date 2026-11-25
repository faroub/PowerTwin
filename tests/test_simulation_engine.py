"""Automated Test Suite for WP02 Independent Deterministic Simulation Engine &
PT-005 Lifecycle/Snapshot Semantics."""

import pytest

from backend.app.models.battery.bms import GenericBMSModel
from backend.app.models.battery.system import GenericBatterySystemModel
from backend.app.models.pcs.pcs_model import GenericPCSModel
from backend.app.simulation.clock import SimulationClock
from backend.app.simulation.config import SimulationConfiguration
from backend.app.simulation.context import SimulationContext
from backend.app.simulation.exceptions import (
    InvalidTimeStepError,
    SimulationError,
    SnapshotIncompatibleError,
)
from backend.app.simulation.manager import SimulationRunManager
from backend.app.simulation.snapshot import SimulationSnapshot
from backend.app.simulation.state import SimulationState
from backend.app.simulation.task import SimulationTask
from plugins.generic_battery import GenericBatteryPlugin
from plugins.generic_pcs import GenericPCSPlugin


class CountingTask(SimulationTask):
    """Test task recording execution ticks."""

    def __init__(
        self,
        name: str,
        phase: int = 1,
        priority: int = 0,
        interval_ticks: int = 1,
        log_list: list[str] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            phase=phase,
            priority=priority,
            interval_ticks=interval_ticks,
        )
        self.log_list: list[str] = log_list if log_list is not None else []
        self.executed_ticks: list[int] = []

    def execute(self, ctx: SimulationContext) -> None:
        self.executed_ticks.append(ctx.current_tick_ns)
        self.log_list.append(f"{self.name}@{ctx.current_tick_ns}")


class FailingTask(SimulationTask):
    """Test task raising an unhandled exception."""

    def __init__(self, name: str = "FailingTask", fail_at_tick: int = 20_000_000) -> None:
        super().__init__(name=name, phase=2, priority=0, interval_ticks=1)
        self.fail_at_tick = fail_at_tick

    def execute(self, ctx: SimulationContext) -> None:
        if ctx.current_tick_ns >= self.fail_at_tick:
            raise RuntimeError(f"Simulated fault in task '{self.name}'")


def test_time_advances_correctly() -> None:
    """Test SimulationClock advances time deterministically by step size."""
    clock = SimulationClock(step_ns=10_000_000, initial_ticks_ns=0)
    assert clock.time_ns == 0
    assert clock.total_steps == 0
    assert clock.time_seconds == 0.0

    t1 = clock.advance()
    assert t1 == 10_000_000
    assert clock.time_ns == 10_000_000
    assert clock.total_steps == 1
    assert clock.time_seconds == 0.01

    t2 = clock.advance()
    assert t2 == 20_000_000
    assert clock.total_steps == 2
    assert clock.format_timestamp() == "00:00:00.020.000"


def test_invalid_clock_step() -> None:
    """Test invalid time steps raise InvalidTimeStepError."""
    with pytest.raises(InvalidTimeStepError):
        SimulationClock(step_ns=0)
    with pytest.raises(InvalidTimeStepError):
        SimulationClock(step_ns=-5)


def test_pause_and_resume() -> None:
    """Test pause and resume state transitions."""
    runner = SimulationRunManager()
    assert runner.state == SimulationState.STOPPED

    runner.start()
    assert runner.state == SimulationState.RUNNING

    runner.pause()
    assert runner.state == SimulationState.PAUSED

    runner.resume()
    assert runner.state == SimulationState.RUNNING

    runner.stop()
    assert runner.state == SimulationState.STOPPED


def test_step_while_stopped_or_paused() -> None:
    """Test stepping while stopped or paused advances clock and sets state to PAUSED."""
    runner = SimulationRunManager()
    task = CountingTask(name="StepTask")
    runner.register_task(task)

    assert runner.state == SimulationState.STOPPED
    runner.step(1)
    assert runner.clock.total_steps == 1
    assert runner.state == SimulationState.PAUSED

    runner.step(2)
    assert runner.clock.total_steps == 3
    assert runner.state == SimulationState.PAUSED


def test_single_step() -> None:
    """Test single-step advances exactly one tick."""
    runner = SimulationRunManager()
    task = CountingTask(name="SingleStepTask")
    runner.register_task(task)

    runner.start()
    assert runner.clock.time_ns == 0
    assert runner.clock.total_steps == 0

    executed = runner.single_step()
    assert executed == ["SingleStepTask"]
    assert runner.clock.time_ns == 10_000_000
    assert runner.clock.total_steps == 1
    assert task.execution_count == 1


def test_reset_restores_equipment_and_bms_states() -> None:
    """Test reset restores battery SoC, PCS state, and clears BMS faults."""
    battery = GenericBatterySystemModel()
    battery.soc_pct = 20.0
    battery.active_power_w = 5_000_000.0

    pcs = GenericPCSModel()
    pcs.requested_p_w = 5_000_000.0
    pcs.actual_p_w = 4_925_000.0

    bms = GenericBMSModel()
    bms.evaluate_protection(voltage_v=1000.0, current_a=0.0, soc_pct=50.0, temp_c=65.0)
    assert bms.is_available is False

    # Reset
    battery.reset_to_initial_conditions()
    pcs.reset_to_initial_conditions()
    bms.clear_faults()

    assert battery.soc_pct == 50.0
    assert battery.active_power_w == 0.0
    assert pcs.requested_p_w == 0.0
    assert pcs.actual_p_w == 0.0
    assert bms.is_available is True


def test_reset_preserves_plugin_disabled_status() -> None:
    """Test reset does not accidentally enable a previously disabled plugin."""
    runner = SimulationRunManager()
    plugin1 = GenericBatteryPlugin(equipment_id="BAT1")
    plugin2 = GenericPCSPlugin(equipment_id="PCS1")

    runner.register_task(plugin1)
    runner.register_task(plugin2)

    plugin1.enabled = True
    plugin2.enabled = False  # Explicitly disabled

    runner.reset()

    assert plugin1.enabled is True
    assert plugin2.enabled is False  # Preserved disabled state


def test_snapshot_restores_physical_equipment_states() -> None:
    """Test snapshot serialization and restoration includes underlying physical equipment states."""
    runner = SimulationRunManager()
    bat_plugin = GenericBatteryPlugin(equipment_id="BAT_CONT_01")
    bat_plugin.initialize({"initial_soc_pct": 50.0, "capacity_wh": 10_000_000.0})
    bat_plugin.enabled = True
    runner.register_task(bat_plugin)

    # Step simulation and discharge battery
    bat_plugin.physical_model.active_power_w = 2_000_000.0  # +2 MW discharge
    runner.step(5)

    snapshot = runner.create_snapshot()
    assert snapshot.total_steps == 5
    soc_at_snap = bat_plugin.physical_model.soc_pct
    assert soc_at_snap < 50.0  # Discharged

    # Run another 5 steps
    runner.step(5)
    assert bat_plugin.physical_model.soc_pct < soc_at_snap

    # Restore snapshot
    runner.restore_snapshot(snapshot)
    assert runner.clock.total_steps == 5
    assert bat_plugin.physical_model.soc_pct == soc_at_snap


def test_snapshot_incompatible_version() -> None:
    """Test invalid snapshot version raises SnapshotIncompatibleError."""
    snapshot = SimulationSnapshot(
        version="9.9.9",
        simulation_run_id="test",
        timestamp_ns=0,
        total_steps=0,
        step_ns=10000000,
        random_state={},
        shared_state={},
        task_states={},
    )
    with pytest.raises(SnapshotIncompatibleError):
        snapshot.validate_compatibility()


def test_clock_total_steps_restore_uses_public_api() -> None:
    """Test the total step counter can be restored publicly and validates non-negative."""
    clock = SimulationClock(step_ns=10_000_000)
    clock.advance()
    clock.advance()
    clock.advance()
    assert clock.total_steps == 3

    clock.restore_total_steps(1)
    assert clock.total_steps == 1

    with pytest.raises(InvalidTimeStepError):
        clock.restore_total_steps(-1)


def test_snapshot_restores_step_counter_deterministically() -> None:
    """Test that restore_snapshot uses the public step counter (no private attribute patch)."""
    runner = SimulationRunManager()
    bat_plugin = GenericBatteryPlugin(equipment_id="BAT_CONT_01")
    bat_plugin.initialize({"initial_soc_pct": 50.0, "capacity_wh": 10_000_000.0})
    bat_plugin.enabled = True
    runner.register_task(bat_plugin)

    # Discharge at 2 MW so the punch-out SoC is tracked through the task loop
    bat_plugin.physical_model.active_power_w = 2_000_000.0
    runner.step(5)

    snapshot = runner.create_snapshot()
    assert snapshot.total_steps == 5
    soc_at_snapshot = bat_plugin.physical_model.soc_pct
    assert soc_at_snapshot < 50.0

    runner.step(5)
    assert runner.clock.total_steps == 10
    assert runner.clock.time_ns == 100_000_000
    assert bat_plugin.physical_model.soc_pct < soc_at_snapshot

    # Restore: step counter and the deterministic RNG state must both be restored
    runner.restore_snapshot(snapshot)
    assert runner.clock.total_steps == 5
    assert runner.clock.time_ns == 50_000_000
    assert runner.state == SimulationState.PAUSED
    assert bat_plugin.physical_model.soc_pct == soc_at_snapshot

    # A second run from the restored state continues down from the stored SoC
    runner.start()
    runner.step(5)
    assert runner.clock.total_steps == 10
    assert bat_plugin.physical_model.soc_pct < soc_at_snapshot
    runner.stop()


def test_failed_task_fail_fast_policy() -> None:
    """Test FAIL_FAST policy aborts simulation upon task failure."""
    config = SimulationConfiguration(error_policy="FAIL_FAST")
    runner = SimulationRunManager(config=config)
    runner.register_task(FailingTask(fail_at_tick=20_000_000))

    runner.single_step()  # 10ms - OK
    with pytest.raises(SimulationError):
        runner.single_step()  # 20ms - Fails!

    assert runner.state == SimulationState.FAULTED
