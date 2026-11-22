"""Abstract Base Simulation Task definition."""

from abc import ABC, abstractmethod
from typing import Any

from backend.app.simulation.context import SimulationContext


class SimulationTask(ABC):
    """Abstract base class for all scheduled simulation tasks.

    Tasks execute within an assigned Phase (1 to 6) and Priority, at configured tick intervals.
    """

    def __init__(
        self,
        name: str,
        phase: int = 1,
        priority: int = 0,
        interval_ticks: int = 1,
        enabled: bool = True,
    ) -> None:
        if phase < 1 or phase > 6:
            raise ValueError(f"Task phase must be between 1 and 6, got: {phase}")
        if interval_ticks < 1:
            raise ValueError(f"Task interval_ticks must be >= 1, got: {interval_ticks}")

        self.name: str = name
        self.phase: int = phase
        self.priority: int = priority
        self.interval_ticks: int = interval_ticks
        self.enabled: bool = enabled
        self.execution_count: int = 0
        self.last_execution_tick_ns: int | None = None

        # One authoritative physical model owned by this task, if any. Tasks
        # like PlantControlTask own a cluster of models they reset directly.
        self.physical_model: Any = None

    @abstractmethod
    def execute(self, ctx: SimulationContext) -> None:
        """Execute task logic for a single simulation tick.

        Args:
            ctx: SimulationContext providing access to clock, random RNG, events, and shared state.
        """
        pass

    def get_task_state(self) -> dict[str, Any]:
        """Return task internal state dictionary for snapshot serialization."""
        state = {
            "name": self.name,
            "phase": self.phase,
            "priority": self.priority,
            "interval_ticks": self.interval_ticks,
            "enabled": self.enabled,
            "execution_count": self.execution_count,
            "last_execution_tick_ns": self.last_execution_tick_ns,
        }
        if self.physical_model is not None:
            state["physical_model"] = self.physical_model.get_model_state()
        return state

    def restore_to_initial(self) -> None:
        """Reset the task-owned physical model to its initial conditions (no-op by default).

        Tasks that own an equipment cluster (PlantControlTask, PlantNetworkTask)
        override this to restore their full fleet. Plugins rely on the default
        physical-model reset provided here.
        """
        if self.physical_model is not None and hasattr(
            self.physical_model, "reset_to_initial_conditions"
        ):
            self.physical_model.reset_to_initial_conditions()

    def set_task_state(self, state: dict[str, Any]) -> None:
        """Restore task internal state from snapshot state dictionary."""
        self.enabled = state.get("enabled", True)
        self.execution_count = state.get("execution_count", 0)
        self.last_execution_tick_ns = state.get("last_execution_tick_ns")
