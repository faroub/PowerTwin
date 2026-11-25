"""Simulation Control API Endpoints for Real Simulation Engine Lifecycle Management.

All values are read from the application-scoped simulation runtime rather than
a module-level global singleton so that the plant, engine and execution runner
are the ones attached by the application start-up.

The runtime is the **single** write path to that state. A plant is attached
with ``SimulationRuntime.attach_plant`` and detached with
``SimulationRuntime.drop``; this module deliberately offers no second way in,
because a second entry point is a second way for the API and the start-up to
disagree about which engine is live.

Every action an operator performs here is written to the dedicated
operator-action journal, including the actions that are **rejected**: a
refused action is part of the trail, because a trail that only records what
succeeded cannot show what was attempted.
"""

import logging
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.app.core.operator_journal import (
    OperatorJournalError,
    get_operator_journal,
)
from backend.app.core.rbac import Permission, require_permission
from backend.app.core.safety import get_safety_report
from backend.app.simulation.runtime import (
    get_simulation_runtime,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Simulation Control"])


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
    request: Request,
    _user: Any = Depends(require_permission(Permission.MODIFY_SIMULATION)),
) -> SimulationControlResponse:
    """Execute simulation engine lifecycle action on active engine instance.

    Returns HTTP 503 Service Unavailable if engine is not connected/running.
    """
    runtime = get_simulation_runtime(request=request)
    engine = runtime.engine
    safety = get_safety_report()
    actor = getattr(_user, "username", "UNKNOWN")
    act = payload.action

    # 1. Reject if no active simulation engine is attached
    if engine is None:
        msg = (
            f"Simulation control action '{payload.action.value}' cannot be executed: "
            "No active plant simulation engine is connected. Status: NOT_CONNECTED."
        )
        _record_operator_action(
            request=request,
            actor=actor,
            action=act,
            outcome="REJECTED",
            reason="NOT_CONNECTED",
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
    if act == SimulationActionEnum.START:
        runtime.start()
    elif act == SimulationActionEnum.PAUSE:
        runtime.pause()
    elif act == SimulationActionEnum.RESUME:
        runtime.resume()
    elif act == SimulationActionEnum.STOP:
        runtime.stop()
    elif act == SimulationActionEnum.STEP:
        num_steps = payload.steps if payload.steps and payload.steps > 0 else 1
        runtime.step(num_steps)
    elif act == SimulationActionEnum.RESET:
        runtime.reset()
    elif act == SimulationActionEnum.SET_SPEED:
        if payload.speed_factor is None or payload.speed_factor < 0.0:
            _record_operator_action(
                request=request,
                actor=actor,
                action=act,
                outcome="REJECTED",
                reason="INVALID_SPEED_FACTOR",
                details={"speed_factor": payload.speed_factor},
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SET_SPEED action requires a non-negative 'speed_factor' parameter.",
            )
        runtime.set_speed_factor(payload.speed_factor)

    engine_state_str = engine.state.value if hasattr(engine.state, "value") else str(engine.state)
    msg = f"Action '{act.value}' successfully executed on simulation engine."

    _record_operator_action(
        request=request,
        actor=actor,
        action=act,
        outcome="SUCCESS",
        reason="EXECUTED",
        details={
            "engine_state": engine_state_str,
            "steps": payload.steps,
            "speed_factor": payload.speed_factor,
        },
    )

    return SimulationControlResponse(
        action=act,
        status="SUCCESS",
        engine_state=engine_state_str,
        message=msg,
        safety_status=safety["safety_status"],
    )


def _record_operator_action(
    *,
    request: Request,
    actor: str,
    action: SimulationActionEnum,
    outcome: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Write an operator action to the dedicated operator-action journal.

    A journal that cannot be written is reported as an error and the journal
    marks itself degraded; the error is never swallowed. The action itself is
    not undone: the engine has already advanced by the time the record is
    written, and a simulation action cannot be rolled back.
    """
    runtime = get_simulation_runtime(request=request)
    plant = runtime.active_plant
    target = plant.topology_config.plant_id if plant is not None else "NO_PLANT"

    payload: dict[str, Any] = {"reason": reason}
    if details:
        payload.update(details)

    try:
        get_operator_journal(request=request).record(
            action=f"SIMULATION_{action.value}",
            actor=actor,
            target=target,
            source="OPERATOR",
            outcome=outcome,
            details=payload,
        )
    except OperatorJournalError as err:
        logger.error("The operator action could not reach the journal: %s", err)


@router.get("/simulation/status", response_model=dict[str, Any])
async def get_simulation_status(
    request: Request,
    _user: Any = Depends(require_permission(Permission.READ_TELEMETRY)),
) -> dict[str, Any]:
    """Return the authoritative simulation engine status of the active plant."""
    runtime = get_simulation_runtime(request=request)
    return runtime.status()
