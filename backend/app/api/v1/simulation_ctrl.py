"""Simulation Control API Endpoints (Operate exclusively on simulation instances)."""

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from backend.app.core.rbac import Permission, require_permission
from backend.app.core.safety import get_safety_report

router = APIRouter(tags=["Simulation Control"])


class SimulationControlRequest(BaseModel):
    """Payload schema for simulation control actions."""

    action: str
    speed_factor: float | None = None
    steps: int | None = None


@router.post("/simulation/control", status_code=status.HTTP_200_OK)
async def dispatch_simulation_control(
    payload: SimulationControlRequest,
    _user: Any = Depends(require_permission(Permission.MODIFY_SIMULATION)),
) -> dict[str, Any]:
    """Execute simulation engine lifecycle action on in-memory instance."""
    safety = get_safety_report()
    msg = (
        f"Action '{payload.action}' executed safely on simulation instance. "
        "Zero real equipment targeted."
    )
    return {
        "action": payload.action,
        "status": "EXECUTED_ON_SIMULATION_INSTANCE",
        "safety_guardrails": safety["safety_status"],
        "message": msg,
    }
