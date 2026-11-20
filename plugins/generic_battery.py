"""Generic Battery System Equipment Plugin."""

from typing import Any
from backend.app.equipment.interfaces.battery import BatterySystemConfig, BatterySystemInterface
from backend.app.equipment.models import (
    EquipmentMetadata,
    OperatingState,
    QualityFlag,
    TelemetryPoint,
    UniversalEquipmentState,
)
from backend.app.simulation.context import SimulationContext
from plugins.base import BasePlugin
from plugins.manifest import PluginCategory, PluginManifest


class GenericBatteryPlugin(BasePlugin, BatterySystemInterface):
    """Generic Battery System plugin executing in Phase 4 (Physical Battery Dynamics)."""

    def __init__(self, equipment_id: str = "GENERIC_BATTERY_01") -> None:
        BasePlugin.__init__(
            self,
            name=equipment_id,
            phase=4,  # Phase 4: Battery Physics
            priority=10,
            interval_ticks=1,
        )
        BatterySystemInterface.__init__(self, equipment_id=equipment_id)
        self._config: BatterySystemConfig = BatterySystemConfig()
        self.soc_pct: float = 50.0
        self.voltage_v: float = 1000.0
        self.current_a: float = 0.0
        self.temp_c: float = 25.0

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
        except Exception:
            return False

    def initialize(self, config: dict[str, Any]) -> None:
        self._config = BatterySystemConfig(**config)
        self.soc_pct = self._config.initial_soc_pct
        self.voltage_v = self._config.nominal_voltage_v
        self._operating_state = OperatingState.STANDBY
        self._is_available = True
        self._is_initialized = True

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        # Read PCS or controller power demand from shared state (+W = Discharging, -W = Charging)
        p_pcs_w = ctx.shared_state.get("pcs_active_power_w", 0.0)

        # Calculate current: I = P / V (+A = Discharge out of battery, -A = Charge into battery)
        self.current_a = p_pcs_w / max(self.voltage_v, 1.0)

        # Simple energy integration: dSoC = (-I * dt / nominal_capacity_ah) * 100
        capacity_ah = self._config.capacity_wh / self._config.nominal_voltage_v
        dsoc = (-self.current_a * (delta_t_s / 3600.0) / max(capacity_ah, 1.0)) * 100.0
        self.soc_pct = max(0.0, min(100.0, self.soc_pct + dsoc))

        # Update OCV voltage approximation based on SoC
        self.voltage_v = self._config.nominal_voltage_v * (0.9 + 0.2 * (self.soc_pct / 100.0))

        # Store state in shared bus
        ctx.shared_state["battery_soc_pct"] = self.soc_pct
        ctx.shared_state["battery_voltage_v"] = self.voltage_v
        ctx.shared_state["battery_current_a"] = self.current_a

        if self.current_a != 0.0:
            self._operating_state = OperatingState.RUNNING

    def process_command(self, cmd: dict[str, Any]) -> bool:
        if "reset_faults" in cmd and cmd["reset_faults"]:
            self._operating_state = OperatingState.STANDBY
            return True
        return False

    def get_state(self) -> UniversalEquipmentState:
        t_ns = getattr(self, "last_execution_tick_ns", 0) or 0
        return UniversalEquipmentState(
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            metadata=EquipmentMetadata(manufacturer="Generic", model_name="LFP Container V1"),
            operating_state=self._operating_state,
            is_available=self._is_available,
            timestamp_ns=t_ns,
            measurements={
                "soc_pct": TelemetryPoint(
                    value=self.soc_pct, unit="pct", timestamp_ns=t_ns, source_id=self.equipment_id
                ),
                "voltage_v": TelemetryPoint(
                    value=self.voltage_v, unit="V", timestamp_ns=t_ns, source_id=self.equipment_id
                ),
                "current_a": TelemetryPoint(
                    value=self.current_a, unit="A", timestamp_ns=t_ns, source_id=self.equipment_id
                ),
            },
            active_limits={
                "max_charge_current_a": self._config.max_charge_current_a,
                "max_discharge_current_a": self._config.max_discharge_current_a,
            },
        )

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "capacity_wh": self._config.capacity_wh,
            "nominal_voltage_v": self._config.nominal_voltage_v,
        }

    def shutdown(self) -> None:
        self._operating_state = OperatingState.OFF
        self._is_available = False
