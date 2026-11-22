"""Simulation Control API Endpoints for Real Simulation Engine Lifecycle Management."""

from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.app.core.rbac import Permission, require_permission
from backend.app.core.safety import get_safety_report
from backend.app.simulation.manager import SimulationRunManager

router = APIRouter(tags=["Simulation Control"])

# Global reference to active plant simulation engine (set when plant topology is built)
_active_simulation_engine: SimulationRunManager | None = None


def set_active_simulation_engine(engine: SimulationRunManager | None) -> None:
    """Attach active plant simulation engine instance to control router."""
    global _active_simulation_engine
    _active_simulation_engine = engine


def get_active_simulation_engine() -> SimulationRunManager | None:
    """Return active plant simulation engine instance."""
    return _active_simulation_engine


class SimulationActionEnum(StrEnum):
    """Valid, typed simulation engine control actions."""

    START = "START"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STOP = "STOP"
    STEP = "STEP"
    RESET = "RESET"
    SET_SPEED = "SET_SPEED"


class SimulationControlRequest(BaseModel):
    """Typed request payload schema for simulation control actions."""

    action: SimulationActionEnum
    speed_factor: float | None = Field(
        default=None, description="Target speed factor for SET_SPEED"
    )
    steps: int | None = Field(default=1, description="Number of ticks for STEP action")


class SimulationControlResponse(BaseModel):
    """Response payload schema for simulation control execution."""

    action: SimulationActionEnum
    status: str
    engine_state: str
    message: str
    safety_status: str


@router.post(
    "/simulation/control",
    response_model=SimulationControlResponse,
    status_code=status.HTTP_200_OK,
)
async def dispatch_simulation_control(
    payload: SimulationControlRequest,
    _user: Any = Depends(require_permission(Permission.MODIFY_SIMULATION)),
) -> SimulationControlResponse:
    """Execute simulation engine lifecycle action on active engine instance.

    Returns HTTP 503 Service Unavailable if engine is not connected/running.
    """
    engine = get_active_simulation_engine()
    safety = get_safety_report()

    # 1. Reject if no active simulation engine is attached
    if engine is None:
        msg = (
            f"Simulation control action '{payload.action.value}' cannot be executed: "
            "No active plant simulation engine is connected. Status: NOT_CONNECTED."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "action": payload.action.value,
                "status": "NOT_CONNECTED",
                "message": msg,
            },
        )

    # 2. Execute verified lifecycle action on real simulation engine
    act = payload.action
    if act == SimulationActionEnum.START:
        engine.start()
    elif act == SimulationActionEnum.PAUSE:
        engine.pause()
    elif act == SimulationActionEnum.RESUME:
        engine.resume()
    elif act == SimulationActionEnum.STOP:
        engine.stop()
    elif act == SimulationActionEnum.STEP:
        num_steps = payload.steps if payload.steps and payload.steps > 0 else 1
        engine.step(num_steps)
    elif act == SimulationActionEnum.RESET:
        engine.reset()
    elif act == SimulationActionEnum.SET_SPEED:
        if payload.speed_factor is None or payload.speed_factor < 0.0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SET_SPEED action requires a non-negative 'speed_factor' parameter.",
            )
        engine.set_speed_factor(payload.speed_factor)

    engine_state_str = engine.state.value if hasattr(engine.state, "value") else str(engine.state)
    msg = f"Action '{act.value}' successfully executed on simulation engine."

    return SimulationControlResponse(
        action=act,
        status="SUCCESS",
        engine_state=engine_state_str,
        message=msg,
        safety_status=safety["safety_status"],
    )
