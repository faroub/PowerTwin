"""Historian Query API — Time-Series, Audit Log, Alarm, and Warranty Retrieval.

Every endpoint is read-only and requires the READ_TELEMETRY permission, so an
OBSERVER account can browse history without gaining any control capability.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.rbac import Permission, require_permission
from backend.app.historian.db import get_db
from backend.app.historian.query import HistorianQueryEngine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Historian"])

# Upper bounds on the number of rows a single query may return. The historian
# is a time-series store; an unbounded scan would exhaust database memory.
MAX_TELEMETRY_ROWS = 10_000
MAX_COMMAND_ROWS = 5_000
MAX_ALARM_ROWS = 5_000


async def _run_query[T](operation: Callable[[], Awaitable[T]]) -> T:
    """Run a historian query and turn a store failure into an explicit answer.

    The historian is backed by a database. When that database is unreachable
    the query cannot be answered, and an unhandled exception would reach the
    operator as a bare 500 with no explanation of what went wrong. The
    failure is caught, logged and reported as 503 with a detail the screen
    can show: "the store is unavailable" and "the query returned no rows"
    are different statements, and the operator has to be able to tell them
    apart.

    Both a SQLAlchemy error and an OS error are caught. The asyncpg driver
    lets the underlying socket error escape untranslated when the host name
    cannot be resolved, so a store that is simply not there arrives as
    ``socket.gaierror`` rather than as a ``SQLAlchemyError``.
    """
    try:
        return await operation()
    except (SQLAlchemyError, OSError) as err:
        logger.error("The historian query could not be answered: %s", err)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The historian store is unavailable; the query could not be answered.",
        ) from err


@router.get("/historian/telemetry")
async def query_telemetry(
    equipment_id: str | None = Query(default=None, description="Filter by equipment identifier"),
    tag_id: str | None = Query(default=None, description="Filter by telemetry tag"),
    simulation_run_id: str | None = Query(
        default=None, description="Filter by simulation run identifier"
    ),
    start_time_ns: int | None = Query(default=None, description="Inclusive lower time bound (ns)"),
    end_time_ns: int | None = Query(default=None, description="Inclusive upper time bound (ns)"),
    sampling_step_ns: int | None = Query(
        default=None, description="Downsampling step in nanoseconds"
    ),
    limit: int = Query(default=1000, ge=1, le=MAX_TELEMETRY_ROWS),
    session: AsyncSession = Depends(get_db),
    _user: Any = Depends(require_permission(Permission.READ_TELEMETRY)),
) -> dict[str, Any]:
    """Return historical telemetry records for a plant, run, or tag."""
    if start_time_ns is not None and end_time_ns is not None and end_time_ns < start_time_ns:
        raise HTTPException(
            status_code=422,
            detail="end_time_ns must be greater than or equal to start_time_ns.",
        )

    engine = HistorianQueryEngine(session)
    records = await _run_query(
        lambda: engine.query_telemetry(
            equipment_id=equipment_id,
            tag_id=tag_id,
            simulation_run_id=simulation_run_id,
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            sampling_step_ns=sampling_step_ns,
            limit=limit,
        )
    )
    return {"count": len(records), "records": records}


@router.get("/historian/commands")
async def query_commands(
    target_equipment_id: str | None = Query(default=None, description="Filter by target equipment"),
    simulation_run_id: str | None = Query(
        default=None, description="Filter by simulation run identifier"
    ),
    limit: int = Query(default=100, ge=1, le=MAX_COMMAND_ROWS),
    session: AsyncSession = Depends(get_db),
    _user: Any = Depends(require_permission(Permission.READ_TELEMETRY)),
) -> dict[str, Any]:
    """Return the traceable command audit log."""
    engine = HistorianQueryEngine(session)
    records = await _run_query(
        lambda: engine.query_commands(
            target_equipment_id=target_equipment_id,
            simulation_run_id=simulation_run_id,
            limit=limit,
        )
    )
    return {"count": len(records), "records": records}


@router.get("/historian/alarms")
async def query_alarms(
    equipment_id: str | None = Query(default=None, description="Filter by equipment identifier"),
    severity: str | None = Query(default=None, description="Filter by alarm severity"),
    limit: int = Query(default=100, ge=1, le=MAX_ALARM_ROWS),
    session: AsyncSession = Depends(get_db),
    _user: Any = Depends(require_permission(Permission.READ_TELEMETRY)),
) -> dict[str, Any]:
    """Return the alarms and events log."""
    engine = HistorianQueryEngine(session)
    records = await _run_query(
        lambda: engine.query_alarms(
            equipment_id=equipment_id,
            severity=severity,
            limit=limit,
        )
    )
    return {"count": len(records), "records": records}


@router.get("/historian/warranty/{container_id}")
async def query_warranty_metrics(
    container_id: str,
    simulation_run_id: str | None = Query(
        default=None,
        description=(
            "Report on this simulation run only. The store holds one warranty row "
            "per container and run, so a container that has been run more than "
            "once has one row per run."
        ),
    ),
    session: AsyncSession = Depends(get_db),
    _user: Any = Depends(require_permission(Permission.READ_TELEMETRY)),
) -> dict[str, Any]:
    """Return the warranty and degradation metrics for a battery container."""
    engine = HistorianQueryEngine(session)
    metrics = await _run_query(
        lambda: engine.query_warranty_metrics(container_id, simulation_run_id)
    )
    if metrics is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No warranty metrics recorded for container '{container_id}'.",
        )
    return metrics
