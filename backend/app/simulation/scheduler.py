"""Deterministic Simulation Scheduler.

Schedules and executes SimulationTasks in strict DAG Phase and Priority order.
"""

import logging

from backend.app.simulation.context import SimulationContext
from backend.app.simulation.exceptions import InitializationError, TaskExecutionError
from backend.app.simulation.task import SimulationTask

logger = logging.getLogger(__name__)


class SimulationScheduler:
    """Task scheduler ensuring deterministic execution ordering."""

    def __init__(self, error_policy: str = "FAIL_FAST") -> None:
        self._tasks: dict[str, SimulationTask] = {}
        self._sorted_tasks_cache: list[SimulationTask] = []
        self._cache_valid: bool = False
        self.error_policy: str = error_policy

    def register_task(self, task: SimulationTask) -> None:
        """Register a simulation task.

        Args:
            task: SimulationTask instance.
        """
        if task.name in self._tasks:
            raise InitializationError(
                f"Cannot register duplicate task name: '{task.name}'"
            )

        self._tasks[task.name] = task
        self._cache_valid = False
        logger.debug(
            "Registered task '%s' (Phase %d, Priority %d, Interval %d)",
            task.name,
            task.phase,
            task.priority,
            task.interval_ticks,
        )

    def unregister_task(self, task_name: str) -> None:
        """Unregister a task by name."""
        if task_name in self._tasks:
            del self._tasks[task_name]
            self._cache_valid = False

    def get_task(self, task_name: str) -> SimulationTask | None:
        """Return registered task by name."""
        return self._tasks.get(task_name)

    def clear_tasks(self) -> None:
        """Remove all registered tasks."""
        self._tasks.clear()
        self._sorted_tasks_cache.clear()
        self._cache_valid = False

    def _get_sorted_tasks(self) -> list[SimulationTask]:
        """Return registered tasks sorted deterministically by Phase, Priority, Name."""
        if not self._cache_valid:
            self._sorted_tasks_cache = sorted(
                self._tasks.values(),
                key=lambda t: (t.phase, t.priority, t.name),
            )
            self._cache_valid = True
        return self._sorted_tasks_cache

    def step_scheduler(self, ctx: SimulationContext) -> list[str]:
        """Execute all tasks scheduled for the current tick step.

        Args:
            ctx: SimulationContext for current tick.

        Returns:
            List of names of tasks executed during this step.
        """
        executed_tasks: list[str] = []
        tasks = self._get_sorted_tasks()
        step_number = ctx.clock.total_steps

        for task in tasks:
            if not task.enabled:
                continue

            # Evaluate interval schedule (e.g. interval=1 every step, interval=10 every 10th step)
            if (step_number - 1) % task.interval_ticks != 0:
                continue

            try:
                task.execute(ctx)
                task.execution_count += 1
                task.last_execution_tick_ns = ctx.current_tick_ns
                executed_tasks.append(task.name)
            except Exception as e:
                logger.error(
                    "Task '%s' failed at tick %d ns: %s",
                    task.name,
                    ctx.current_tick_ns,
                    e,
                    exc_info=True,
                )
                if self.error_policy == "FAIL_FAST":
                    raise TaskExecutionError(task.name, ctx.current_tick_ns, e) from e
                else:
                    # Safe-park task by disabling it and logging fault
                    task.enabled = False
                    ctx.emit_event(
                        name="TASK_FAULTED",
                        source=task.name,
                        payload={
                            "task_name": task.name,
                            "error": str(e),
                            "action": "TASK_DISABLED",
                        },
                    )

        return executed_tasks
