"""Simulation Engine Integration Status Provider."""

from typing import Any

from backend.app.api.v1.simulation_ctrl import get_active_simulation_engine


class SimulationEngineStatusProvider:
    """Provides status from active simulation engine or returns NOT_CONNECTED."""

    def get_status(self) -> dict[str, Any]:
        """Return actual active simulation engine status."""
        engine = get_active_simulation_engine()
        if engine is None:
            return {
                "status": "NOT_CONNECTED",
                "mode": "SIMULATION_ONLY",
                "current_tick": 0,
                "is_running": False,
                "message": "No active simulation engine instance attached.",
            }

        state_str = engine.state.value if hasattr(engine.state, "value") else str(engine.state)
        return {
            "status": state_str,
            "mode": "SIMULATION_ONLY",
            "current_tick": engine.clock.total_steps,
            "is_running": (state_str == "RUNNING"),
            "message": f"Simulation engine is in state '{state_str}'.",
        }


engine_stub = SimulationEngineStatusProvider()
