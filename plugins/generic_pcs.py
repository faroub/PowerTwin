"""Generic PCS Inverter Equipment Plugin."""

from typing import Any

from backend.app.equipment.interfaces.pcs import PCSConfig, PCSInterface
from backend.app.equipment.models import UniversalEquipmentState
from backend.app.models.pcs.pcs_model import GenericPCSModel, PCSConfigModel
from backend.app.simulation.context import SimulationContext
from plugins.base import BasePlugin
from plugins.manifest import PluginCategory, PluginManifest


class GenericPCSPlugin(BasePlugin, PCSInterface):
    """Generic PCS Inverter plugin executing in Phase 3 (Actuators & PCS)."""

    def __init__(self, equipment_id: str = "GENERIC_PCS_01") -> None:
        BasePlugin.__init__(
            self,
            name=equipment_id,
            phase=3,
            priority=10,
            interval_ticks=1,
        )
        PCSInterface.__init__(self, equipment_id=equipment_id)
        self._config: PCSConfig = PCSConfig()
        self.physical_model = GenericPCSModel(
            equipment_id=equipment_id,
            config=PCSConfigModel(
                rated_active_power_w=5_000_000.0,
                rated_apparent_power_va=5_500_000.0,
            ),
        )

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id="generic_pcs_v1",
            name="Generic PCS Inverter Plugin",
            version="1.0.0",
            api_version="0.1.0",
            category=PluginCategory.PCS,
            author="PowerTwin Core",
            capabilities=["active_power_dispatch", "reactive_power_dispatch"],
            dependencies=[],
        )

    def validate_config(self, config: dict[str, Any]) -> bool:
        try:
            PCSConfig(**config)
            return True
        except ValueError:
            return False

    def initialize(self, config: dict[str, Any]) -> None:
        self._config = PCSConfig(**config)
        self.physical_model.config.rated_active_power_w = self._config.rated_power_w
        self.physical_model.config.rated_apparent_power_va = (
            self._config.rated_apparent_power_va
        )
        self.enabled = True

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        p_req = ctx.shared_state.get(
            "pcs_cmd_active_power_w", self.physical_model.requested_p_w
        )
        q_req = ctx.shared_state.get(
            "pcs_cmd_reactive_power_var", self.physical_model.requested_q_var
        )
        self.physical_model.process_command(
            {"enable_inverter": True, "requested_p_w": p_req, "requested_q_var": q_req}
        )

        self.physical_model.step(
            dc_voltage_v=1000.0,
            ac_grid_voltage_v=690.0,
            delta_t_s=delta_t_s,
            timestamp_ns=ctx.current_tick_ns,
        )

        ctx.shared_state["pcs_active_power_w"] = self.physical_model.actual_p_w
        ctx.shared_state["pcs_reactive_power_var"] = self.physical_model.actual_q_var

    def process_command(self, cmd: dict[str, Any]) -> bool:
        return self.physical_model.process_command(cmd)

    def get_state(self) -> UniversalEquipmentState:
        return self.physical_model.get_state()

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "rated_power_w": self.physical_model.config.rated_active_power_w,
            "rated_apparent_power_va": self.physical_model.config.rated_apparent_power_va,
        }

    def shutdown(self) -> None:
        self.enabled = False
