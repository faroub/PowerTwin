"""SMA Sunny Central UP Central Inverter Plugin."""

import math
from typing import Any

from backend.app.equipment.interfaces.pcs import PCSInterface
from backend.app.equipment.models import (
    EquipmentMetadata,
    UniversalEquipmentState,
)
from backend.app.models.pcs.pcs_model import GenericPCSModel, PCSConfigModel
from backend.app.simulation.context import SimulationContext
from plugins.base import BasePlugin
from plugins.generic_pcs import (
    KEY_PCS_CMD_ACTIVE_W_PREFIX,
    KEY_PCS_CMD_REACTIVE_W_PREFIX,
    KEY_PCS_CMD_ACTIVE_W,
    KEY_PCS_CMD_REACTIVE_W,
    KEY_BATTERY_DC_VOLTAGE_V,
    KEY_PCS_AC_GRID_VOLTAGE_V,
    _read_setpoint,
)
from plugins.manifest import PluginCategory, PluginHealthStatus, PluginManifest


class SMASunnyCentralPCSPlugin(BasePlugin, PCSInterface):
    """SMA Sunny Central 4400 UP 4.4 MW Central Inverter Plugin."""

    def __init__(self, equipment_id: str = "SMA_SC4400_01") -> None:
        BasePlugin.__init__(
            self,
            name=equipment_id,
            phase=3,  # Phase 3: Actuators & PCS
            priority=10,
            interval_ticks=1,
        )
        PCSInterface.__init__(self, equipment_id=equipment_id)

        # 1. Vendor Configuration (Data Source: SMA Sunny Central 4400 UP Datasheet)
        self.rated_power_w: float = 4_400_000.0  # 4.4 MW
        self.rated_apparent_power_va: float = 4_840_000.0  # 4.84 MVA
        self.ac_voltage_v: float = 690.0
        self.ambient_temp_c: float = 25.0

        pcs_cfg = PCSConfigModel(
            rated_active_power_w=self.rated_power_w,
            rated_apparent_power_va=self.rated_apparent_power_va,
            ac_voltage_nominal_v=self.ac_voltage_v,
            dc_voltage_min_v=880.0,
            dc_voltage_max_v=1500.0,
        )
        self.physical_model: GenericPCSModel = GenericPCSModel(
            equipment_id=equipment_id, config=pcs_cfg
        )

        self.supported_capabilities: list[str] = [
            "Q_ON_DEMAND_NIGHT",
            "SUNSPEC_MODBUS_MAP",
            "GRID_FORMING_CAPABLE",
        ]
        self.known_limitations: str = (
            "Active power derates linearly above 45 deg C ambient "
            "temperature down to 80% at 60 deg C."
        )

    @property
    def manifest(self) -> PluginManifest:
        """Return plugin manifest metadata."""
        return PluginManifest(
            plugin_id="SMA_SunnyCentral_v1",
            name="SMA Sunny Central 4400 UP Inverter",
            version="1.0.0",
            api_version="0.1.0",
            category=PluginCategory.PCS,
            author="SMA / PowerTwin Core",
            capabilities=self.supported_capabilities,
            dependencies=[],
        )

    def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate input configuration parameters."""
        try:
            if "rated_power_w" in config:
                pwr = float(config["rated_power_w"])
                if pwr <= 0.0 or not math.isfinite(pwr):
                    return False
            if "rated_apparent_power_va" in config:
                pwr = float(config["rated_apparent_power_va"])
                if pwr <= 0.0 or not math.isfinite(pwr):
                    return False
            if "ambient_temp_c" in config:
                temp = float(config["ambient_temp_c"])
                if temp < -40.0 or temp > 80.0 or not math.isfinite(temp):
                    return False
            return True
        except (ValueError, TypeError):
            return False

    def initialize(self, config: dict[str, Any]) -> None:
        """Initialize vendor equipment instance."""
        if not self.validate_config(config):
            raise ValueError("Invalid configuration for SMA Sunny Central plugin")

        if "rated_power_w" in config:
            self.rated_power_w = float(config["rated_power_w"])
            self.physical_model.config.rated_active_power_w = self.rated_power_w
        if "rated_apparent_power_va" in config:
            self.rated_apparent_power_va = float(config["rated_apparent_power_va"])
            self.physical_model.config.rated_apparent_power_va = (
                self.rated_apparent_power_va
            )
        if "ambient_temp_c" in config:
            self.ambient_temp_c = float(config["ambient_temp_c"])
        self.enabled = True
        self.health_status = PluginHealthStatus.HEALTHY

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        """Step physical model dynamics per simulation tick with thermal derating."""
        # Apply thermal derating
        if self.ambient_temp_c > 45.0:
            derate_pct = max(0.80, 1.0 - (self.ambient_temp_c - 45.0) * 0.0133)
            self.physical_model.config.rated_active_power_w = (
                self.rated_power_w * derate_pct
            )
        else:
            self.physical_model.config.rated_active_power_w = self.rated_power_w

        # Read per-device command from shared state (written by PlantControlTask)
        p_req = _read_setpoint(
            ctx.shared_state,
            f"{KEY_PCS_CMD_ACTIVE_W_PREFIX}{self.physical_model.equipment_id}",
            KEY_PCS_CMD_ACTIVE_W,
            self.physical_model.requested_p_w,
        )
        q_req = _read_setpoint(
            ctx.shared_state,
            f"{KEY_PCS_CMD_REACTIVE_W_PREFIX}{self.physical_model.equipment_id}",
            KEY_PCS_CMD_REACTIVE_W,
            self.physical_model.requested_q_var,
        )
        self.physical_model.process_command(
            {"enable_inverter": True, "requested_p_w": p_req, "requested_q_var": q_req}
        )

        # Read DC bus voltage from shared state (computed by PlantBatteryDistributionTask)
        dc_v = _read_setpoint(
            ctx.shared_state,
            KEY_BATTERY_DC_VOLTAGE_V,
            KEY_BATTERY_DC_VOLTAGE_V,
            1000.0,
        )
        # Read AC grid voltage from shared state (computed by PlantNetworkTask)
        ac_v = _read_setpoint(
            ctx.shared_state,
            KEY_PCS_AC_GRID_VOLTAGE_V,
            KEY_PCS_AC_GRID_VOLTAGE_V,
            690.0,
        )

        self.physical_model.step(
            dc_voltage_v=dc_v,
            ac_grid_voltage_v=ac_v,
            delta_t_s=delta_t_s,
            timestamp_ns=ctx.current_tick_ns,
        )

        # Publish actual power to shared state for Battery Distribution Task
        ctx.shared_state["pcs_active_power_w"] = self.physical_model.actual_p_w
        ctx.shared_state["pcs_reactive_power_var"] = self.physical_model.actual_q_var
        ctx.shared_state[
            f"{KEY_PCS_CMD_ACTIVE_W_PREFIX}{self.physical_model.equipment_id}"
        ] = self.physical_model.actual_p_w
        ctx.shared_state[
            f"{KEY_PCS_CMD_REACTIVE_W_PREFIX}{self.physical_model.equipment_id}"
        ] = self.physical_model.actual_q_var

    def shutdown(self) -> None:
        """Clean up plugin state."""
        self.enabled = False
        self.health_status = PluginHealthStatus.DISABLED

    def get_state(self) -> UniversalEquipmentState:
        """Return vendor-specific universal telemetry state."""
        state = self.physical_model.get_state()
        state.metadata = EquipmentMetadata(
            manufacturer="SMA",
            model_name="Sunny Central 4400 UP",
            serial_number=f"SMA-SC-{self.equipment_id}",
        )
        return state
