"""Generic Battery System Equipment Plugin."""

import math
from typing import Any

from backend.app.equipment.interfaces.battery import (
    BatterySystemConfig,
    BatterySystemInterface,
)
from backend.app.equipment.models import UniversalEquipmentState
from backend.app.models.battery.system import (
    BatterySystemConfigModel,
    GenericBatterySystemModel,
    battery_capabilities,
)
from backend.app.simulation.context import SimulationContext
from plugins.base import BasePlugin
from plugins.manifest import PluginCategory, PluginHealthStatus, PluginManifest


class GenericBatteryPlugin(BasePlugin, BatterySystemInterface):
    """Generic Battery System plugin executing in Phase 4 (Physical Battery Dynamics)."""

    def __init__(self, equipment_id: str = "GENERIC_BATTERY_01") -> None:
        BasePlugin.__init__(
            self,
            name=equipment_id,
            phase=4,
            priority=10,
            interval_ticks=1,
        )
        BatterySystemInterface.__init__(self, equipment_id=equipment_id)
        self._config: BatterySystemConfig = BatterySystemConfig()
        self.physical_model: GenericBatterySystemModel = GenericBatterySystemModel(
            equipment_id=equipment_id,
            config=BatterySystemConfigModel(
                capacity_wh=100_000_000.0,
                nominal_voltage_v=1000.0,
                initial_soc_pct=50.0,
            ),
        )

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id="generic_battery_v1",
            name="Generic Battery System Plugin",
            version="1.0.0",
            api_version="0.1.0",
            category=PluginCategory.BATTERY,
            author="PowerTwin Core",
            capabilities=["soc_tracking", "voltage_current_telemetry"],
            dependencies=[],
        )

    def validate_config(self, config: dict[str, Any]) -> bool:
        try:
            BatterySystemConfig(**config)
            return True
        except ValueError:
            return False

    def initialize(self, config: dict[str, Any]) -> None:
        self._config = BatterySystemConfig(**config)
        self.physical_model.config.capacity_wh = self._config.capacity_wh
        self.physical_model.config.nominal_voltage_v = self._config.nominal_voltage_v
        self.physical_model.soc_pct = self._config.initial_soc_pct
        self.enabled = True
        self.health_status = PluginHealthStatus.HEALTHY

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        p_cmd = _read_setpoint(
            ctx.shared_state,
            f"{KEY_BATTERY_CMD_P_W_PREFIX}{self.physical_model.equipment_id}",
            KEY_BATTERY_CMD_P_W,
            ctx.shared_state.get(KEY_PCS_CMD_ACTIVE_W, self.physical_model.active_power_w),
        )
        if not math.isfinite(p_cmd):
            p_cmd = 0.0
        self.physical_model.step(
            power_demand_w=p_cmd,
            delta_t_s=delta_t_s,
            timestamp_ns=ctx.current_tick_ns,
        )

        ctx.shared_state["battery_soc_pct"] = self.physical_model.soc_pct
        ctx.shared_state["battery_voltage_v"] = self.physical_model.voltage_v
        ctx.shared_state["battery_current_a"] = self.physical_model.current_a
        ctx.shared_state[f"{KEY_BATTERY_DC_VOLTAGE_V}_{self.physical_model.equipment_id}"] = (
            self.physical_model.voltage_v
        )

    def process_command(self, cmd: dict[str, Any]) -> bool:
        if cmd.get("reset_faults"):
            self.physical_model.clear_faults()
            return True
        return False

    def get_state(self) -> UniversalEquipmentState:
        return self.physical_model.get_state()

    def get_capabilities(self) -> dict[str, Any]:
        """Return what this container actually runs with.

        The values are read from the live configuration, so a calibrated
        container reports its calibrated values.
        """
        return battery_capabilities(self.physical_model.config)

    def shutdown(self) -> None:
        self.enabled = False


# --------------------------------------------------------------------------- #
# Shared state keys owned by the plant tasks.

# Per-device command key written by the PlantBatteryDistributionTask (Phase 4).
KEY_BATTERY_CMD_P_W_PREFIX = "battery_cmd_power_w_"
# Legacy flat command key: a single value for the whole battery fleet (older
# callers and direct-engine tests).
KEY_BATTERY_CMD_P_W = "battery_cmd_power_w"

KEY_BATTERY_DC_VOLTAGE_V = "battery_dc_voltage_v"

# Key written by the PCS plugins; the battery task falls back to it when the
# per-device key is absent.
KEY_PCS_CMD_ACTIVE_W = "pcs_cmd_active_power_w"


def _read_setpoint(
    shared_state: dict[str, Any],
    keyed: str,
    flat: str,
    fallback: float,
) -> float:
    """Read a per-device command key, falling back to the legacy flat key.

    The authoritative command source is the keyed key (one value per device).
    The legacy flat key is kept for older callers and direct-engine tests that
    write a single value for the whole fleet.
    """
    raw = shared_state.get(keyed, shared_state.get(flat, fallback))
    if not isinstance(raw, (int, float)) or not math.isfinite(raw):
        return fallback
    return float(raw)
