"""Dummy Auxiliary Systems Equipment Plugin."""

from typing import Any

from backend.app.equipment.interfaces.auxiliary import (
    AuxiliaryConfig,
    AuxiliarySystemInterface,
)
from backend.app.equipment.models import (
    EquipmentMetadata,
    OperatingState,
    TelemetryPoint,
    UniversalEquipmentState,
)
from backend.app.simulation.context import SimulationContext
from plugins.base import BasePlugin
from plugins.manifest import PluginCategory, PluginManifest


class DummyAuxiliaryPlugin(BasePlugin, AuxiliarySystemInterface):
    """Dummy Auxiliary HVAC plugin executing in Phase 5 (Auxiliary & BOP)."""

    def __init__(self, equipment_id: str = "DUMMY_AUX_01") -> None:
        BasePlugin.__init__(
            self,
            name=equipment_id,
            phase=5,  # Phase 5: Auxiliary & BOP
            priority=10,
            interval_ticks=1,
        )
        AuxiliarySystemInterface.__init__(self, equipment_id=equipment_id)
        self._config: AuxiliaryConfig = AuxiliaryConfig()
        self.container_temp_c: float = 25.0
        self.target_temp_c: float = 23.0
        self.hvac_power_w: float = 5000.0

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id="dummy_auxiliary_v1",
            name="Dummy Auxiliary HVAC Plugin",
            version="1.0.0",
            api_version="0.1.0",
            category=PluginCategory.AUXILIARY,
            author="PowerTwin Core",
            capabilities=["hvac_thermal_control", "aux_load_simulation"],
            dependencies=[],
        )

    def validate_config(self, config: dict[str, Any]) -> bool:
        try:
            AuxiliaryConfig(**config)
            return True
        except ValueError:
            return False

    def initialize(self, config: dict[str, Any]) -> None:
        self._config = AuxiliaryConfig(**config)
        self.hvac_power_w = self._config.aux_base_power_w
        self._operating_state = OperatingState.RUNNING
        self._is_available = True
        self._is_initialized = True

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        temp_diff = self.container_temp_c - self.target_temp_c
        self.container_temp_c -= temp_diff * (0.1 * delta_t_s)

        ctx.shared_state["container_temp_c"] = self.container_temp_c
        ctx.shared_state["aux_power_w"] = self.hvac_power_w

    def process_command(self, cmd: dict[str, Any]) -> bool:
        if "setpoint_temp_c" in cmd:
            self.target_temp_c = float(cmd["setpoint_temp_c"])
            return True
        return False

    def get_state(self) -> UniversalEquipmentState:
        t_ns = getattr(self, "last_execution_tick_ns", 0) or 0
        return UniversalEquipmentState(
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            metadata=EquipmentMetadata(manufacturer="Generic", model_name="Aux HVAC V1"),
            operating_state=self._operating_state,
            is_available=self._is_available,
            timestamp_ns=t_ns,
            measurements={
                "container_temp_c": TelemetryPoint(
                    value=self.container_temp_c,
                    unit="degC",
                    timestamp_ns=t_ns,
                    source_id=self.equipment_id,
                ),
                "hvac_power_w": TelemetryPoint(
                    value=self.hvac_power_w,
                    unit="W",
                    timestamp_ns=t_ns,
                    source_id=self.equipment_id,
                ),
            },
        )

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "cooling_capacity_w": self._config.cooling_capacity_w,
            "aux_base_power_w": self._config.aux_base_power_w,
        }

    def shutdown(self) -> None:
        self._operating_state = OperatingState.OFF
        self._is_available = False
