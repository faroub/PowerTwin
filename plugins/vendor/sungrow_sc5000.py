"""Sungrow SC5000UD-MV Inverter Plugin."""

from typing import Any

from backend.app.equipment.interfaces.pcs import PCSInterface
from backend.app.equipment.models import (
    EquipmentMetadata,
    UniversalEquipmentState,
)
from backend.app.models.pcs.pcs_model import GenericPCSModel, PCSConfigModel
from backend.app.simulation.context import SimulationContext
from plugins.base import BasePlugin
from plugins.manifest import PluginCategory, PluginHealthStatus, PluginManifest


class SungrowSC5000PCSPlugin(BasePlugin, PCSInterface):
    """Sungrow SC5000UD-MV 5.0 MW Turnkey Central Inverter Plugin."""

    def __init__(self, equipment_id: str = "SUNGROW_SC5000_01") -> None:
        BasePlugin.__init__(self, name=equipment_id)
        PCSInterface.__init__(self, equipment_id=equipment_id)

        # 1. Vendor Configuration (Data Source: Sungrow SC5000UD Specification Sheet 2023)
        self.rated_power_w: float = 5_000_000.0  # 5.0 MW
        self.rated_apparent_power_va: float = 5_500_000.0  # 5.5 MVA
        self.ac_voltage_v: float = 690.0

        pcs_cfg = PCSConfigModel(
            rated_active_power_w=self.rated_power_w,
            rated_apparent_power_va=self.rated_apparent_power_va,
            ac_voltage_nominal_v=self.ac_voltage_v,
            dc_voltage_min_v=1000.0,
            dc_voltage_max_v=1500.0,
        )
        self.physical_model = GenericPCSModel(equipment_id=equipment_id, config=pcs_cfg)

        self.supported_capabilities: list[str] = [
            "BLACK_START_CAPABLE",
            "FOUR_QUADRANT_OPERATION",
            "MODBUS_SUNSPEC_COMPLIANT",
        ]
        self.known_limitations: str = (
            "Minimum DC operating voltage is 1000 V DC; "
            "inverter trips under-voltage below 950 V DC."
        )

    @property
    def manifest(self) -> PluginManifest:
        """Return plugin manifest metadata."""
        return PluginManifest(
            plugin_id="Sungrow_SC5000_v1",
            name="SC5000UD-MV Turnkey Inverter Station",
            category=PluginCategory.PCS,
            version="1.0.0",
            capabilities=self.supported_capabilities,
        )

    def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate input configuration parameters."""
        return True

    def initialize(self, config: dict[str, Any]) -> None:
        """Initialize vendor equipment instance."""
        if "rated_power_w" in config:
            self.rated_power_w = float(config["rated_power_w"])
            self.physical_model.config.rated_active_power_w = self.rated_power_w
        if "rated_apparent_power_va" in config:
            self.rated_apparent_power_va = float(config["rated_apparent_power_va"])
            self.physical_model.config.rated_apparent_power_va = (
                self.rated_apparent_power_va
            )
        self.enabled = True
        self.health_status = PluginHealthStatus.HEALTHY

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        """Step physical model dynamics per simulation tick."""
        self.physical_model.step(
            dc_voltage_v=1100.0,
            ac_grid_voltage_v=690.0,
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
            manufacturer="Sungrow",
            model_name="SC5000UD-MV",
            serial_number=f"SNG-SC5K-{self.equipment_id}",
        )
        return state
