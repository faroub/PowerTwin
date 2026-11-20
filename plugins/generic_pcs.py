"""Generic PCS Inverter Equipment Plugin."""

from typing import Any

from backend.app.equipment.interfaces.pcs import PCSCommand, PCSConfig, PCSInterface
from backend.app.equipment.models import (
    EquipmentMetadata,
    OperatingState,
    TelemetryPoint,
    UniversalEquipmentState,
)
from backend.app.simulation.context import SimulationContext
from plugins.base import BasePlugin
from plugins.manifest import PluginCategory, PluginManifest


class GenericPCSPlugin(BasePlugin, PCSInterface):
    """Generic PCS Inverter plugin executing in Phase 3 (Actuators & PCS)."""

    def __init__(self, equipment_id: str = "GENERIC_PCS_01") -> None:
        BasePlugin.__init__(
            self,
            name=equipment_id,
            phase=3,  # Phase 3: PCS & Actuators
            priority=10,
            interval_ticks=1,
        )
        PCSInterface.__init__(self, equipment_id=equipment_id)
        self._config: PCSConfig = PCSConfig()
        self.active_power_w: float = 0.0
        self.reactive_power_var: float = 0.0
        self.efficiency_pct: float = 98.5

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
        self._operating_state = OperatingState.STANDBY
        self._is_available = True
        self._is_initialized = True

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        p_req = ctx.shared_state.get("pcs_cmd_active_power_w", self.active_power_w)
        q_req = ctx.shared_state.get("pcs_cmd_reactive_power_var", self.reactive_power_var)

        p_clamped = max(-self._config.rated_power_w, min(self._config.rated_power_w, p_req))
        q_clamped = max(
            -self._config.rated_apparent_power_va,
            min(self._config.rated_apparent_power_va, q_req),
        )

        self.active_power_w = p_clamped
        self.reactive_power_var = q_clamped

        ctx.shared_state["pcs_active_power_w"] = self.active_power_w
        ctx.shared_state["pcs_reactive_power_var"] = self.reactive_power_var

        if self.active_power_w != 0.0 or self.reactive_power_var != 0.0:
            self._operating_state = OperatingState.RUNNING

    def process_command(self, cmd: dict[str, Any]) -> bool:
        try:
            parsed = PCSCommand(**cmd)
            self.active_power_w = parsed.active_power_setpoint_w
            self.reactive_power_var = parsed.reactive_power_setpoint_var
            return True
        except ValueError:
            return False

    def get_state(self) -> UniversalEquipmentState:
        t_ns = getattr(self, "last_execution_tick_ns", 0) or 0
        return UniversalEquipmentState(
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            metadata=EquipmentMetadata(manufacturer="Generic", model_name="PCS Inverter 5MW"),
            operating_state=self._operating_state,
            is_available=self._is_available,
            timestamp_ns=t_ns,
            measurements={
                "active_power_w": TelemetryPoint(
                    value=self.active_power_w,
                    unit="W",
                    timestamp_ns=t_ns,
                    source_id=self.equipment_id,
                ),
                "reactive_power_var": TelemetryPoint(
                    value=self.reactive_power_var,
                    unit="VAR",
                    timestamp_ns=t_ns,
                    source_id=self.equipment_id,
                ),
                "efficiency_pct": TelemetryPoint(
                    value=self.efficiency_pct,
                    unit="pct",
                    timestamp_ns=t_ns,
                    source_id=self.equipment_id,
                ),
            },
            active_limits={
                "rated_power_w": self._config.rated_power_w,
                "rated_apparent_power_va": self._config.rated_apparent_power_va,
            },
        )

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "rated_power_w": self._config.rated_power_w,
            "rated_apparent_power_va": self._config.rated_apparent_power_va,
        }

    def shutdown(self) -> None:
        self.active_power_w = 0.0
        self.reactive_power_var = 0.0
        self._operating_state = OperatingState.OFF
        self._is_available = False
