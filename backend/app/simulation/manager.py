"""Simulation Run Manager — Master Simulation Lifecycle Controller."""

import logging
import time
import uuid
from typing import Any

from backend.app.simulation.clock import NANOSECONDS_PER_SECOND, SimulationClock
from backend.app.simulation.config import SimulationConfiguration
from backend.app.simulation.context import SimulationContext
from backend.app.simulation.event import EventDispatcher
from backend.app.simulation.exceptions import (
    SimulationError,
)
from backend.app.simulation.random_manager import SeededRandomManager
from backend.app.simulation.scheduler import SimulationScheduler
from backend.app.simulation.snapshot import SimulationSnapshot
from backend.app.simulation.state import SimulationState
from backend.app.simulation.task import SimulationTask

logger = logging.getLogger(__name__)


class SimulationRunManager:
    """Master controller managing simulation clock, scheduler, state, and execution loop."""

    def __init__(self, config: SimulationConfiguration | None = None) -> None:
        self.config: SimulationConfiguration = (
            config if config is not None else SimulationConfiguration()
        )
        self.simulation_run_id: str = str(uuid.uuid4())

        self.clock = SimulationClock(step_ns=self.config.tick_step_ns)
        self.random = SeededRandomManager(seed=self.config.random_seed)
        self.events = EventDispatcher()
        self.scheduler = SimulationScheduler(error_policy=self.config.error_policy)

        self.shared_state: dict[str, Any] = {}
        self.context = SimulationContext(
            clock=self.clock,
            random=self.random,
            events=self.events,
            run_id=self.simulation_run_id,
            shared_state=self.shared_state,
        )

        self.state: SimulationState = SimulationState.STOPPED

    def register_task(self, task: SimulationTask) -> None:
        """Register a task with the simulation scheduler."""
        self.scheduler.register_task(task)

    def set_speed_factor(self, multiplier: float) -> None:
        """Update simulation wall-clock speed pacing factor."""
        if multiplier < 0.0:
            raise ValueError("Speed factor multiplier must be >= 0.0")
        self.config.speed_factor = multiplier

    def start(self) -> None:
        """Start or restart simulation execution."""
        if self.state == SimulationState.FAULTED:
            raise SimulationError(
                "Cannot start faulted simulation engine. Please reset engine first."
            )

        if self.state in (SimulationState.RUNNING, SimulationState.PAUSED):
            logger.warning("Simulation is already started in state %s", self.state)
            self.state = SimulationState.RUNNING
            return

        self.state = SimulationState.RUNNING
        self.context.emit_event(
            name="SIMULATION_STARTED",
            source="SIMULATION_ENGINE",
            payload={"run_id": self.simulation_run_id, "timestamp_ns": self.clock.time_ns},
        )

    def pause(self) -> None:
        """Pause simulation execution at the current tick."""
        if self.state != SimulationState.RUNNING:
            return

        self.state = SimulationState.PAUSED
        self.context.emit_event(
            name="SIMULATION_PAUSED",
            source="SIMULATION_ENGINE",
            payload={"run_id": self.simulation_run_id, "timestamp_ns": self.clock.time_ns},
        )

    def resume(self) -> None:
        """Resume simulation execution from paused state."""
        if self.state == SimulationState.FAULTED:
            raise SimulationError(
                "Cannot resume faulted simulation engine. Please reset engine first."
            )

        if self.state != SimulationState.PAUSED:
            return

        self.state = SimulationState.RUNNING
        self.context.emit_event(
            name="SIMULATION_RESUMED",
            source="SIMULATION_ENGINE",
            payload={"run_id": self.simulation_run_id, "timestamp_ns": self.clock.time_ns},
        )

    def stop(self) -> None:
        """Stop simulation execution."""
        if self.state == SimulationState.STOPPED:
            return

        self.state = SimulationState.STOPPED
        self.context.emit_event(
            name="SIMULATION_STOPPED",
            source="SIMULATION_ENGINE",
            payload={"run_id": self.simulation_run_id, "timestamp_ns": self.clock.time_ns},
        )

    def single_step(self) -> list[str]:
        """Execute exactly one simulation tick step.

        Returns:
            List of names of executed tasks.
        """
        return self.step(num_ticks=1)

    def step(self, num_ticks: int = 1) -> list[str]:
        """Execute exactly num_ticks simulation steps.

        Args:
            num_ticks: Number of ticks to execute.

        Returns:
            List of names of executed tasks across the step(s).
        """
        if num_ticks <= 0:
            raise ValueError(f"num_ticks must be strictly positive (> 0), got: {num_ticks}")

        if self.state == SimulationState.FAULTED:
            raise SimulationError(
                "Cannot step faulted simulation engine. Please reset engine first."
            )

        if self.state == SimulationState.COMPLETED:
            raise SimulationError(
                "Cannot step completed simulation engine. Please reset engine first."
            )

        initial_state = self.state
        executed_summary: list[str] = []

        try:
            for _ in range(num_ticks):
                if (
                    self.config.max_ticks is not None
                    and self.clock.total_steps >= self.config.max_ticks
                ):
                    self.state = SimulationState.COMPLETED
                    self.context.emit_event(
                        name="SIMULATION_COMPLETED",
                        source="SIMULATION_ENGINE",
                        payload={
                            "run_id": self.simulation_run_id,
                            "timestamp_ns": self.clock.time_ns,
                        },
                    )
                    break

                # Advance clock by fixed tick step
                self.clock.advance()

                # Execute scheduled tasks for current tick
                tasks_run = self.scheduler.step_scheduler(self.context)
                executed_summary.extend(tasks_run)

            # If stepped while PAUSED or STOPPED, keep in PAUSED state
            if (
                initial_state in (SimulationState.PAUSED, SimulationState.STOPPED)
                and self.state != SimulationState.COMPLETED
            ):
                self.state = SimulationState.PAUSED

        except Exception as err:
            self.state = SimulationState.FAULTED
            self.context.emit_event(
                name="SIMULATION_FAULTED",
                source="SIMULATION_ENGINE",
                payload={
                    "run_id": self.simulation_run_id,
                    "timestamp_ns": self.clock.time_ns,
                    "error": str(err),
                },
            )
            raise SimulationError(f"Simulation tick step failed: {err}") from err

        return executed_summary

    def run_headless(self, max_ticks: int) -> int:
        """Run engine synchronously for max_ticks at maximum headless speed.

        Args:
            max_ticks: Number of ticks to execute.

        Returns:
            Total ticks executed.
        """
        self.start()
        ticks_executed = 0
        for _ in range(max_ticks):
            if self.state != SimulationState.RUNNING:
                break
            self.step(1)
            ticks_executed += 1
        self.stop()
        return ticks_executed

    def pace_tick_wall_clock(self, start_wall_s: float) -> None:
        """Pace execution loop to match target speed factor if speed_factor > 0."""
        if self.config.speed_factor <= 0.0:
            return

        target_duration_s = (self.clock.step_ns / NANOSECONDS_PER_SECOND) / self.config.speed_factor
        elapsed_s = time.perf_counter() - start_wall_s
        sleep_needed_s = target_duration_s - elapsed_s

        if sleep_needed_s > 0:
            time.sleep(sleep_needed_s)

    def reset(self, config_override: SimulationConfiguration | None = None) -> None:
        """Reset simulation engine to initial conditions, preserving task enabled states."""
        if config_override is not None:
            self.config = config_override

        self.simulation_run_id = str(uuid.uuid4())
        self.clock.reset(initial_ticks_ns=0, step_ns=self.config.tick_step_ns)
        self.random.reseed(self.config.random_seed)
        self.events.clear()
        self.shared_state.clear()
        self.scheduler.error_policy = self.config.error_policy

        # Re-initialize context reference
        self.context = SimulationContext(
            clock=self.clock,
            random=self.random,
            events=self.events,
            run_id=self.simulation_run_id,
            shared_state=self.shared_state,
        )

        # Reset task internal execution counts and physical models, preserving task enabled state
        for task in self.scheduler._tasks.values():
            task.execution_count = 0
            task.last_execution_tick_ns = None
            if hasattr(task, "physical_model") and hasattr(
                task.physical_model, "reset_to_initial_conditions"
            ):
                task.physical_model.reset_to_initial_conditions()

        self.state = SimulationState.STOPPED

    def create_snapshot(self) -> SimulationSnapshot:
        """Capture engine state snapshot."""
        task_states = {name: task.get_task_state() for name, task in self.scheduler._tasks.items()}
        return SimulationSnapshot(
            simulation_run_id=self.simulation_run_id,
            timestamp_ns=self.clock.time_ns,
            total_steps=self.clock.total_steps,
            step_ns=self.clock.step_ns,
            random_state=self.random.get_state(),
            shared_state=dict(self.shared_state),
            task_states=task_states,
        )

    def restore_snapshot(self, snapshot: SimulationSnapshot) -> None:
        """Restore engine state from a snapshot.

        Args:
            snapshot: SimulationSnapshot object to restore.
        """
        snapshot.validate_compatibility()

        self.simulation_run_id = snapshot.simulation_run_id
        self.clock.reset(initial_ticks_ns=snapshot.timestamp_ns, step_ns=snapshot.step_ns)
        self.clock._total_steps = snapshot.total_steps
        self.random.set_state(snapshot.random_state)
        self.shared_state.clear()
        self.shared_state.update(snapshot.shared_state)

        # Re-link context
        self.context = SimulationContext(
            clock=self.clock,
            random=self.random,
            events=self.events,
            run_id=self.simulation_run_id,
            shared_state=self.shared_state,
        )

        # Restore task states
        for name, task in self.scheduler._tasks.items():
            if name in snapshot.task_states:
                task.set_task_state(snapshot.task_states[name])

        self.state = SimulationState.PAUSED
