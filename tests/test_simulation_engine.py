"""Automated Test Suite for WP02 Independent Deterministic Simulation Engine."""

import pytest

from backend.app.simulation.clock import SimulationClock
from backend.app.simulation.config import SimulationConfiguration
from backend.app.simulation.context import SimulationContext
from backend.app.simulation.event import SimulationEvent
from backend.app.simulation.example import (
    create_example_simulation,
)
from backend.app.simulation.exceptions import (
    InvalidTimeStepError,
    SnapshotIncompatibleError,
    TaskExecutionError,
)
from backend.app.simulation.manager import SimulationRunManager
from backend.app.simulation.snapshot import SimulationSnapshot
from backend.app.simulation.state import SimulationState
from backend.app.simulation.task import SimulationTask


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


def test_task_execution_order_is_deterministic() -> None:
    """Test task execution order follows Phase -> Priority -> Name sorting."""
    execution_order: list[str] = []
    config = SimulationConfiguration(tick_step_ns=10_000_000)
    runner = SimulationRunManager(config=config)

    # Register out of order
    runner.register_task(CountingTask(name="Phase3_Task", phase=3, log_list=execution_order))
    runner.register_task(CountingTask(name="Phase1_TaskB", phase=1, priority=10, log_list=execution_order))
    runner.register_task(CountingTask(name="Phase1_TaskA", phase=1, priority=5, log_list=execution_order))
    runner.register_task(CountingTask(name="Phase2_Task", phase=2, log_list=execution_order))

    runner.single_step()

    expected_order = [
        "Phase1_TaskA@10000000",
        "Phase1_TaskB@10000000",
        "Phase2_Task@10000000",
        "Phase3_Task@10000000",
    ]
    assert execution_order == expected_order


def test_different_task_rates() -> None:
    """Test multi-rate tasks (every tick vs every N ticks)."""
    runner = SimulationRunManager()
    fast_task = CountingTask(name="Fast100Hz", interval_ticks=1)
    slow_task = CountingTask(name="Slow10Hz", interval_ticks=10)

    runner.register_task(fast_task)
    runner.register_task(slow_task)

    # Run 10 ticks
    runner.step(10)

    assert fast_task.execution_count == 10
    assert slow_task.execution_count == 1  # Executed only on tick 1 (step 1)


def test_reset_restores_initial_conditions() -> None:
    """Test reset restores time, RNG, and task states."""
    runner = SimulationRunManager()
    task = CountingTask(name="Task1")
    runner.register_task(task)

    runner.step(5)
    assert runner.clock.total_steps == 5
    assert task.execution_count == 5

    runner.reset()

    assert runner.clock.time_ns == 0
    assert runner.clock.total_steps == 0
    assert runner.state == SimulationState.STOPPED
    assert task.execution_count == 0
    assert task.enabled is True


def test_snapshot_create_and_restore() -> None:
    """Test snapshot creation and state restoration."""
    runner = create_example_simulation(seed=12345)
    runner.step(5)

    snapshot = runner.create_snapshot()
    assert snapshot.total_steps == 5
    assert snapshot.timestamp_ns == 50_000_000
    assert "p_gen_w" in snapshot.shared_state

    val_at_5 = snapshot.shared_state["p_gen_w"]

    # Run another 5 steps
    runner.step(5)
    assert runner.clock.total_steps == 10

    # Restore snapshot back to step 5
    runner.restore_snapshot(snapshot)
    assert runner.clock.total_steps == 5
    assert runner.clock.time_ns == 50_000_000
    assert runner.shared_state["p_gen_w"] == val_at_5


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


def test_identical_seeded_runs_produce_identical_results() -> None:
    """Test bit-exact replay determinism across separate runs with same seed."""
    run1 = create_example_simulation(seed=999)
    run1.step(20)

    run2 = create_example_simulation(seed=999)
    run2.step(20)

    assert run1.clock.time_ns == run2.clock.time_ns
    assert run1.shared_state["p_gen_w"] == run2.shared_state["p_gen_w"]
    assert run1.shared_state["net_power_w"] == run2.shared_state["net_power_w"]


def test_failed_task_fail_fast_policy() -> None:
    """Test FAIL_FAST policy aborts simulation upon task failure."""
    config = SimulationConfiguration(error_policy="FAIL_FAST")
    runner = SimulationRunManager(config=config)
    runner.register_task(FailingTask(fail_at_tick=20_000_000))

    runner.single_step()  # 10ms - OK
    with pytest.raises(TaskExecutionError):
        runner.single_step()  # 20ms - Fails!

    assert runner.state == SimulationState.FAULTED


def test_failed_task_continue_policy() -> None:
    """Test CONTINUE_WITH_FAULT_LOG policy safe-parks task without crashing engine."""
    config = SimulationConfiguration(error_policy="CONTINUE_WITH_FAULT_LOG")
    runner = SimulationRunManager(config=config)
    task = FailingTask(fail_at_tick=20_000_000)
    runner.register_task(task)

    events_received: list[SimulationEvent] = []
    runner.events.subscribe_all(events_received.append)

    runner.step(3)  # Step 1: OK, Step 2: Faults & Safe-parks, Step 3: Skipped

    assert task.enabled is False
    assert runner.state == SimulationState.STOPPED or runner.state == SimulationState.RUNNING
    fault_events = [e for e in events_received if e.name == "TASK_FAULTED"]
    assert len(fault_events) == 1
    assert fault_events[0].source == "FailingTask"


def test_example_simulation_integration() -> None:
    """Test complete small example simulation execution."""
    runner = create_example_simulation(seed=42)
    events: list[SimulationEvent] = []
    runner.events.subscribe_all(events.append)

    runner.step(4)

    assert runner.clock.total_steps == 4
    assert runner.clock.time_ns == 40_000_000
    assert "p_gen_w" in runner.shared_state
    assert "net_power_w" in runner.shared_state

    # Verify event counts (Generator runs 4 times, Load runs 2 times on step 1 & step 3)
    gen_events = [e for e in events if e.name == "POWER_GENERATED"]
    load_events = [e for e in events if e.name == "NET_POWER_CALCULATED"]
    assert len(gen_events) == 4
    assert len(load_events) == 2
