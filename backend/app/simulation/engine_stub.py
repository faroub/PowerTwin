"""Simulation engine placeholder stub.

Full simulation physics, tick-clock execution, and DAG state management
will be implemented in subsequent work packages.
"""

from typing import Any


class SimulationEngineStub:
    """Stub interface for central simulation engine."""

    def __init__(self) -> None:
        self.is_running: bool = False
        self.current_tick: int = 0

    def get_status(self) -> dict[str, Any]:
        """Return engine placeholder status."""
        return {
            "status": "NOT_STARTED",
            "mode": "SIMULATION_ONLY",
            "current_tick": self.current_tick,
            "is_running": self.is_running,
            "message": "Simulation physics engine initialization pending WP02+",
        }


engine_stub = SimulationEngineStub()
