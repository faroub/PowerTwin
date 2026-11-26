"""Tests for the simulation runner's execution-loop lifecycle.

The runner owns the thread that drives the simulation clock. Two properties
decide whether the platform is deterministic:

* a **stop is final**: no tick is started behind the back of a stop, and the
  engine is left in the stopped state rather than in a state that a tick has
  changed after the stop was acknowledged,
* a **start always leaves a running loop**: the thread of a previous
  generation must not clear the state of the generation that replaced it, and
  the engine must never report a running loop that nothing drives.

The interleavings that break these properties are forced here with a gated
step and a task that holds a tick open, so the tests do not depend on the
timing of a contended machine to reach the broken ordering.
"""

import threading
import time

from backend.app.simulation.context import SimulationContext
from backend.app.simulation.manager import SimulationRunManager
from backend.app.simulation.runner import SimulationRunner
from backend.app.simulation.state import SimulationState
from backend.app.simulation.task import SimulationTask

#: How long a test waits for the loop to reach a state it expects.
WAIT_TIMEOUT_S = 5.0

#: How many start/stop/start cycles the generation test repeats. The broken
#: ordering was observed in roughly one cycle in fourteen, so a hundred
#: cycles fail with a probability above 99.9 % while the repaired runner
#: passes every one of them.
GENERATION_CYCLES = 100


class _BlockingTask(SimulationTask):
    """A task that holds a tick open until the test releases it.

    The tick stays inside the runner's action lock for as long as the task
    waits, which is what lets a test place a stop in the middle of a tick.
    """

    def __init__(self) -> None:
        super().__init__(name="blocking", phase=1, interval_ticks=1)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.ticks = 0

    def execute(self, ctx: SimulationContext) -> None:
        """Count the tick and hold it open until the test releases it."""
        self.ticks += 1
        self.entered.set()
        self.release.wait(timeout=WAIT_TIMEOUT_S)


class _GatedStepManager(SimulationRunManager):
    """A manager whose step waits for the test before the tick is executed.

    The gate places a stop in the window between the run loop's read of the
    engine state and the execution of the tick. The tick is held *before* it
    takes the engine's execution lock, so a stop can be honoured while the
    tick is waiting.
    """

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()
        self.entered = threading.Event()

    def step(self, num_ticks: int = 1) -> list[str]:
        """Wait for the gate before the tick is executed."""
        self.entered.set()
        self.gate.wait(timeout=WAIT_TIMEOUT_S)
        return super().step(num_ticks)


class _GatedTeardownRunner(SimulationRunner):
    """A runner whose execution thread is held in its teardown.

    The window in which a start could adopt a thread that is about to exit
    is a few instructions wide. Holding the teardown open turns it into a
    place a test can act in, so the broken ordering is reached every time
    instead of once in thousands of runs.

    The gate is armed by the assignment of the run flag **from the execution
    thread itself**, which is what distinguishes the teardown of the thread
    from the stop that the caller issues.
    """

    def __init__(self, manager: SimulationRunManager) -> None:
        self._running_value = False
        self.teardown_entered = threading.Event()
        self.teardown_release = threading.Event()
        super().__init__(manager)

    @property
    def _running(self) -> bool:
        """The run flag of the execution loop."""
        return self._running_value

    @_running.setter
    def _running(self, value: bool) -> None:
        """Set the run flag, holding the teardown of the execution thread."""
        if not value and threading.current_thread() is getattr(self, "_thread", None):
            self.teardown_entered.set()
            self.teardown_release.wait(timeout=WAIT_TIMEOUT_S)
        self._running_value = value


def _wait_until(predicate, *, description: str) -> None:
    """Wait until ``predicate`` holds.

    Args:
        predicate: The condition to wait for.
        description: What is being waited for, used in the failure message.

    Raises:
        AssertionError: If the condition did not hold in time.
    """
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while not predicate():
        if time.monotonic() > deadline:
            msg = f"Timed out waiting for {description}."
            raise AssertionError(msg)
        time.sleep(0.01)


def test_a_tick_that_starts_after_a_stop_does_not_leave_the_engine_paused() -> None:
    """A stop must not be overturned by a tick that starts behind its back.

    The gate holds the tick between the run loop's read of the engine state
    and the execution of the tick. The stop is issued while the tick waits,
    so the engine is stopped before the tick runs. The tick must then leave
    the engine stopped rather than move it to the paused state that a step
    out of the stopped state produces.
    """
    manager = _GatedStepManager()
    runner = SimulationRunner(manager)

    runner.start()
    assert manager.entered.wait(timeout=WAIT_TIMEOUT_S), "the loop never reached the tick"

    stopper = threading.Thread(target=runner.stop, name="stopper")
    stopper.start()

    # Release the tick. A repaired runner holds its action lock across the
    # tick, so the stop is honoured only once the tick has finished; an
    # unrepaired runner honours the stop first and the tick then runs
    # against a stopped engine.
    manager.gate.set()
    stopper.join(timeout=WAIT_TIMEOUT_S)
    assert not stopper.is_alive(), "the stop did not finish after the tick"

    assert manager.state == SimulationState.STOPPED, (
        f"the engine was left in state {manager.state} after a stop"
    )


def test_a_stop_waits_for_a_tick_in_flight_and_leaves_the_engine_stopped() -> None:
    """A stop must not be overtaken by a tick, and must leave the engine stopped.

    The task holds the first tick open, so the stop arrives while a tick is
    in flight. The tick must finish before the stop is honoured, the engine
    must be left stopped, and no further tick may start afterwards.
    """
    manager = SimulationRunManager()
    task = _BlockingTask()
    manager.register_task(task)
    runner = SimulationRunner(manager)

    runner.start()
    assert task.entered.wait(timeout=WAIT_TIMEOUT_S), "the task never started a tick"

    stopper = threading.Thread(target=runner.stop, name="stopper")
    stopper.start()

    # The stop cannot be honoured while the tick holds the action lock, so the
    # engine is still running and the stop is still waiting.
    time.sleep(0.05)
    assert stopper.is_alive(), "the stop was honoured in the middle of a tick"
    assert manager.state == SimulationState.RUNNING

    task.release.set()
    stopper.join(timeout=WAIT_TIMEOUT_S)
    assert not stopper.is_alive(), "the stop did not finish after the tick"

    assert manager.state == SimulationState.STOPPED

    ticks_at_stop = task.ticks
    time.sleep(0.2)
    assert task.ticks == ticks_at_stop, "a tick was started behind the back of a stop"


def test_a_start_after_a_stop_leaves_a_loop_that_advances_the_clock() -> None:
    """A start must not adopt the execution thread that is on its way out.

    The thread of the previous generation has decided to exit when the next
    start arrives, but it has not finished doing so. A start that adopts it
    leaves the runner reporting that it is running while nothing drives the
    clock, and the thread that was adopted clears the state of the runner on
    its way out.
    """
    manager = SimulationRunManager()
    runner = _GatedTeardownRunner(manager)

    runner.start()
    _wait_until(
        lambda: manager.clock.total_steps > 0,
        description="the clock to advance",
    )

    runner.stop()

    # The execution thread is now held in its teardown: it has decided to
    # exit, but it has not finished doing so.
    assert runner.teardown_entered.wait(timeout=WAIT_TIMEOUT_S), (
        "the execution thread never reached its teardown; the test no longer "
        "observes the window it was written for"
    )

    release = threading.Timer(0.2, runner.teardown_release.set)
    release.start()
    try:
        runner.start()
        assert runner.is_running is True
    finally:
        release.cancel()
        runner.teardown_release.set()

    before = manager.clock.total_steps
    _wait_until(
        lambda: manager.clock.total_steps > before,
        description="the clock to advance under the new generation",
    )


def test_a_rapid_start_stop_start_leaves_a_loop_that_advances_the_clock() -> None:
    """A rapid start/stop/start must leave a loop that really ticks.

    The thread of the previous generation is on its way out when the next
    start arrives. It must not clear the state of the generation that
    replaced it, and the engine must never report a running loop that
    nothing drives.
    """
    manager = SimulationRunManager()
    runner = SimulationRunner(manager)

    for cycle in range(GENERATION_CYCLES):
        runner.start()
        runner.stop()
        runner.start()

        assert runner.is_running is True, f"the runner stopped itself in cycle {cycle}"

        before = manager.clock.total_steps
        deadline = time.monotonic() + WAIT_TIMEOUT_S
        while manager.clock.total_steps == before and time.monotonic() < deadline:
            time.sleep(0.005)
        assert manager.clock.total_steps > before, (
            f"the runner reported a running loop that nothing drove in cycle {cycle}"
        )

        runner.stop()


def test_a_stop_freezes_the_clock() -> None:
    """The clock does not advance once a stop has been honoured."""
    manager = SimulationRunManager()
    runner = SimulationRunner(manager)

    runner.start()
    _wait_until(
        lambda: manager.clock.total_steps > 0,
        description="the clock to advance",
    )

    runner.stop()
    assert manager.state == SimulationState.STOPPED

    frozen = manager.clock.total_steps
    time.sleep(0.2)
    assert manager.clock.total_steps == frozen


def test_a_pause_does_not_delay_a_stop() -> None:
    """A paused loop is stopped promptly.

    The loop waits for the pause to be lifted. That wait must not hold the
    action lock, because a stop that arrives during it would otherwise wait
    for the wait to time out.
    """
    manager = SimulationRunManager()
    runner = SimulationRunner(manager)

    runner.start()
    _wait_until(
        lambda: manager.clock.total_steps > 0,
        description="the clock to advance",
    )
    runner.pause()

    started = time.monotonic()
    runner.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"The stop of a paused loop took {elapsed:.1f} s."
    assert runner.is_running is False
    assert manager.state == SimulationState.STOPPED
