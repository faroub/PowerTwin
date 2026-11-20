"""Simulation Engine Custom Exceptions."""


class SimulationError(Exception):
    """Base exception for all simulation engine errors."""

    pass


class InvalidTimeStepError(SimulationError):
    """Raised when an invalid time step or tick step is specified."""

    pass


class TaskExecutionError(SimulationError):
    """Raised when a simulation task execution fails."""

    def __init__(self, task_name: str, tick_ns: int, original_exception: Exception):
        self.task_name = task_name
        self.tick_ns = tick_ns
        self.original_exception = original_exception
        super().__init__(
            f"Task '{task_name}' failed at tick {tick_ns} ns: {original_exception}"
        )


class SnapshotIncompatibleError(SimulationError):
    """Raised when attempting to restore an incompatible snapshot."""

    pass


class InitializationError(SimulationError):
    """Raised when a component or engine fails to initialize."""

    pass
