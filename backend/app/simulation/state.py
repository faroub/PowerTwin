"""Simulation Engine Lifecycle State."""

from enum import Enum


class SimulationState(str, Enum):
    """Lifecycle operational state of the simulation engine."""

    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    FAULTED = "FAULTED"
    COMPLETED = "COMPLETED"
