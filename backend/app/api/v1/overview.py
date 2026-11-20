"""Plant Overview and Telemetry Stream Endpoints."""

import datetime
from typing import Any

from fastapi import APIRouter

from backend.app.core.safety import get_safety_report
from backend.app.simulation.engine_stub import engine_stub

router = APIRouter(tags=["Plant Overview"])


@router.get("/overview")
async def get_plant_overview() -> dict[str, Any]:
    """Return real-time Plant Overview SCADA metrics."""
    now_wall = datetime.datetime.now(datetime.UTC).strftime("%H:%M:%S UTC")
    return {
        "plant_name": "PowerTwin Reference 10 MW / 20 MWh BESS Plant",
        "active_power_mw": 4.85,
        "reactive_power_mvar": 0.50,
        "avail_charge_mw": 10.00,
        "avail_discharge_mw": 10.00,
        "total_energy_mwh": 20.00,
        "average_soc_pct": 64.5,
        "grid_frequency_hz": 50.02,
        "poi_voltage_kv": 13.81,
        "active_alarms_count": 0,
        "equipment_availability_pct": 100.0,
        "simulation_state": "RUNNING",
        "simulation_time_str": "00:15:30.450.000",
        "wall_clock_time_str": now_wall,
        "safety": get_safety_report(),
        "engine": engine_stub.get_status(),
    }
