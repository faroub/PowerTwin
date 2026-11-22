"""CATL EnerOne Liquid-Cooled LFP Battery Container Plugin."""

from typing import Any

from backend.app.equipment.interfaces.battery import BatterySystemInterface
from backend.app.equipment.models import (
    EquipmentMetadata,
    TelemetryPoint,
    UniversalEquipmentState,
)
from backend.app.models.battery.system import (
    BatterySystemConfigModel,
    GenericBatterySystemModel,
)
from backend.app.simulation.context import SimulationContext
from plugins.base import BasePlugin
from plugins.manifest import PluginCategory, PluginHealthStatus, PluginManifest


class CATLEnerOneBatteryPlugin(BasePlugin, BatterySystemInterface):
    """CATL EnerOne 3.727 MWh Outdoor Liquid-Cooled LFP Battery System Plugin."""

    def __init__(self, equipment_id: str = "CATL_ENERONE_01") -> None:
        BasePlugin.__init__(self, name=equipment_id)
        BatterySystemInterface.__init__(self, equipment_id=equipment_id)

        # 1. Vendor Configuration (Data Source: CATL EnerOne Technical Datasheet)
        self.capacity_wh: float = 3_727_000.0  # 3.727 MWh
        self.nominal_voltage_v: float = 1331.2  # 416S x 3.2V LFP cells
        self.max_continuous_power_w: float = 1_863_500.0  # 0.5C max rate
        self.soc_pct: float = 50.0

        # 2. Generic Physical Model Instance
        b_cfg = BatterySystemConfigModel(
            capacity_wh=self.capacity_wh,
            nominal_voltage_v=self.nominal_voltage_v,
            initial_soc_pct=self.soc_pct,
            max_charge_power_w=self.max_continuous_power_w,
            max_discharge_power_w=self.max_continuous_power_w,
        )
        self.physical_model: GenericBatterySystemModel = GenericBatterySystemModel(
            equipment_id=equipment_id, config=b_cfg
        )

        # 3. Vendor Capabilities & Limitations
        self.supported_capabilities: list[str] = [
            "LIQUID_COOLING",
            "LFP_CHEMISTRY",
            "MODBUS_TCP_MONITORING",
            "HIGH_SAFETY_IP55",
        ]
        self.known_limitations: str = (
            "LFP voltage plateau between 30% and 70% SoC requires coulomb "
            "counting for precision."
        )

    @property
    def manifest(self) -> PluginManifest:
        """Return plugin manifest metadata."""
        return PluginManifest(
            plugin_id="CATL_EnerOne_v1",
            name="CATL EnerOne 3.727MWh Liquid-Cooled BESS",
            category=PluginCategory.BATTERY,
            version="1.0.0",
            capabilities=self.supported_capabilities,
        )

    def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate input configuration parameters."""
        return True

    def initialize(self, config: dict[str, Any]) -> None:
        """Initialize vendor equipment instance."""
        if "capacity_wh" in config:
            self.capacity_wh = float(config["capacity_wh"])
            self.physical_model.config.capacity_wh = self.capacity_wh
            # Update max discharge power if scaled by capacity
            if "max_discharge_power_w" in config:
                self.max_continuous_power_w = float(config["max_discharge_power_w"])
            else:
                self.max_continuous_power_w = self.capacity_wh * 0.5
            self.physical_model.config.max_discharge_power_w = (
                self.max_continuous_power_w
            )
            self.physical_model.config.max_charge_power_w = self.max_continuous_power_w
        if "nominal_voltage_v" in config:
            self.nominal_voltage_v = float(config["nominal_voltage_v"])
            self.physical_model.config.nominal_voltage_v = self.nominal_voltage_v
        if "initial_soc_pct" in config:
            self.soc_pct = float(config["initial_soc_pct"])
            self.physical_model.soc_pct = self.soc_pct
        self.enabled = True
        self.health_status = PluginHealthStatus.HEALTHY

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        """Step physical model dynamics per simulation tick."""
        self.physical_model.step(
            power_demand_w=self.physical_model.active_power_w,
            delta_t_s=delta_t_s,
            timestamp_ns=ctx.current_tick_ns,
        )

    def shutdown(self) -> None:
        """Clean up plugin state."""
        self.enabled = False

    def get_state(self) -> UniversalEquipmentState:
        """Return vendor-specific universal telemetry state."""
        state = self.physical_model.get_state()
        state.metadata = EquipmentMetadata(
            manufacturer="CATL",
            model_name="EnerOne Liquid-Cooled BESS",
            serial_number=f"CATL-EO-{self.equipment_id}",
        )
        state.measurements["coolant_temp_c"] = TelemetryPoint(
            value=self.physical_model.temperature_c - 2.0,
            unit="degC",
            timestamp_ns=self.physical_model.last_step_timestamp_ns,
            source_id=self.equipment_id,
        )
        return state
