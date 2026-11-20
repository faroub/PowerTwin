"""Simulation Engine Lifecycle State."""

from enum import StrEnum


class SimulationState(StrEnum):
    """Lifecycle operational state of the simulation engine."""

    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FAULTED = "FAULTED"
    COMPLETED = "COMPLETED"
