"""Plant Overview and Telemetry Stream Endpoints."""

import datetime
from typing import Any

from fastapi import APIRouter, Depends

from backend.app.api.v1.simulation_ctrl import get_active_simulation_engine
from backend.app.core.rbac import Permission, require_permission
from backend.app.core.safety import get_safety_report
from backend.app.simulation.engine_stub import engine_stub

router = APIRouter(tags=["Plant Overview"])


@router.get("/overview")
async def get_plant_overview(
    _user: Any = Depends(require_permission(Permission.READ_TELEMETRY)),
) -> dict[str, Any]:
    """Return real-time Plant Overview SCADA metrics from active plant instance."""
    now_wall = datetime.datetime.now(datetime.UTC).strftime("%H:%M:%S UTC")
    engine = get_active_simulation_engine()

    if (
        engine is None
        or not hasattr(engine, "context")
        or "plant_instance" not in engine.shared_state
    ):
        return {
            "plant_name": "PowerTwin BESS Plant (Disconnected)",
            "active_power_mw": None,
            "reactive_power_mvar": None,
            "avail_charge_mw": None,
            "avail_discharge_mw": None,
            "total_energy_mwh": None,
            "average_soc_pct": None,
            "grid_frequency_hz": None,
            "poi_voltage_kv": None,
            "active_alarms_count": 0,
            "equipment_availability_pct": 0.0,
            "simulation_state": "NOT_CONNECTED",
            "simulation_time_str": "00:00:00.000.000",
            "wall_clock_time_str": now_wall,
            "safety": get_safety_report(),
            "engine": engine_stub.get_status(),
        }

    plant = engine.shared_state["plant_instance"]
    poi_state = plant.poi.get_state()
    p_w = poi_state.measurements.get("active_power_w")
    q_var = poi_state.measurements.get("reactive_power_var")
    v_v = poi_state.measurements.get("voltage_v")
    f_hz = poi_state.measurements.get("frequency_hz")

    p_mw = round(p_w.value / 1e6, 2) if p_w else 0.0
    q_mvar = round(q_var.value / 1e6, 2) if q_var else 0.0
    v_kv = round(v_v.value / 1e3, 2) if v_v else 13.81
    f_val = round(f_hz.value, 2) if f_hz else 50.0

    active_bats = [b for b in plant.battery_systems if b.is_available]
    total_bats = len(plant.battery_systems)
    avg_soc = (
        round(sum(b.soc_pct for b in active_bats) / max(1, len(active_bats)), 1)
        if active_bats
        else 0.0
    )

    avail_ch_mw = (
        round(sum(b.get_available_power_limits()[0] for b in active_bats) / 1e6, 2)
        if active_bats
        else 0.0
    )
    avail_dis_mw = (
        round(sum(b.get_available_power_limits()[1] for b in active_bats) / 1e6, 2)
        if active_bats
        else 0.0
    )
    total_energy_mwh = round(sum(b.config.capacity_wh for b in plant.battery_systems) / 1e6, 2)

    avail_pct = round((len(active_bats) / max(1, total_bats)) * 100.0, 1) if total_bats else 100.0
    alarms_cnt = sum(len(b.active_alarms) for b in plant.battery_systems) + len(
        plant.poi.active_alarms
    )

    return {
        "plant_name": plant.topology_config.name,
        "active_power_mw": p_mw,
        "reactive_power_mvar": q_mvar,
        "avail_charge_mw": avail_ch_mw,
        "avail_discharge_mw": avail_dis_mw,
        "total_energy_mwh": total_energy_mwh,
        "average_soc_pct": avg_soc,
        "grid_frequency_hz": f_val,
        "poi_voltage_kv": v_kv,
        "active_alarms_count": alarms_cnt,
        "equipment_availability_pct": avail_pct,
        "simulation_state": engine.state.value
        if hasattr(engine.state, "value")
        else str(engine.state),
        "simulation_time_str": engine.clock.format_timestamp(),
        "wall_clock_time_str": now_wall,
        "safety": get_safety_report(),
        "engine": engine_stub.get_status(),
    }
