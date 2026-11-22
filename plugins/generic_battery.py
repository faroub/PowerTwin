"""Generic Battery System Equipment Plugin."""

from typing import Any

from backend.app.equipment.interfaces.battery import (
    BatterySystemConfig,
    BatterySystemInterface,
)
from backend.app.equipment.models import UniversalEquipmentState
from backend.app.models.battery.system import (
    BatterySystemConfigModel,
    GenericBatterySystemModel,
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
        self.physical_model = GenericBatterySystemModel(
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
        p_pcs_w = ctx.shared_state.get(
            "pcs_cmd_active_power_w", self.physical_model.active_power_w
        )
        self.physical_model.step(
            power_demand_w=p_pcs_w,
            delta_t_s=delta_t_s,
            timestamp_ns=ctx.current_tick_ns,
        )

        ctx.shared_state["battery_soc_pct"] = self.physical_model.soc_pct
        ctx.shared_state["battery_voltage_v"] = self.physical_model.voltage_v
        ctx.shared_state["battery_current_a"] = self.physical_model.current_a

    def process_command(self, cmd: dict[str, Any]) -> bool:
        if cmd.get("reset_faults"):
            self.physical_model.clear_faults()
            return True
        return False

    def get_state(self) -> UniversalEquipmentState:
        return self.physical_model.get_state()

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "capacity_wh": self.physical_model.config.capacity_wh,
            "nominal_voltage_v": self.physical_model.config.nominal_voltage_v,
        }

    def shutdown(self) -> None:
        self.enabled = False
