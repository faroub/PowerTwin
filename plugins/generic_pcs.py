"""Generic PCS Inverter Equipment Plugin."""

import math
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
        self.physical_model: GenericPCSModel = GenericPCSModel(
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
        self.physical_model.config.rated_apparent_power_va = self._config.rated_apparent_power_va
        self.enabled = True

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
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

        # The PCS tracks the actual battery DC voltage so the PCS step runs
        # against the real DC bus, not a hard-coded dummy.
        dc_v = _read_setpoint(
            ctx.shared_state,
            KEY_BATTERY_DC_VOLTAGE_V,
            KEY_BATTERY_DC_VOLTAGE_V,
            1000.0,
        )
        self.physical_model.step(
            dc_voltage_v=dc_v,
            ac_grid_voltage_v=self._ac_grid_voltage(ctx),
            delta_t_s=delta_t_s,
            timestamp_ns=ctx.current_tick_ns,
        )

        ctx.shared_state["pcs_active_power_w"] = self.physical_model.actual_p_w
        ctx.shared_state["pcs_reactive_power_var"] = self.physical_model.actual_q_var
        ctx.shared_state[f"{KEY_PCS_ACTUAL_P_W_PREFIX}{self.physical_model.equipment_id}"] = (
            self.physical_model.actual_p_w
        )
        ctx.shared_state[f"{KEY_PCS_ACTUAL_Q_PREFIX}{self.physical_model.equipment_id}"] = (
            self.physical_model.actual_q_var
        )

    @staticmethod
    def _ac_grid_voltage(ctx: SimulationContext) -> float:
        """Read the PCS AC grid voltage from the authoritative shared state."""
        voltage = ctx.shared_state.get(KEY_PCS_AC_GRID_VOLTAGE_V, 690.0)
        return voltage if math.isfinite(voltage) and voltage > 0.0 else 690.0

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


# --------------------------------------------------------------------------- #
# Shared state keys owned by the plant tasks.

# Per-device command keys written by the PlantControlTask (Phase 2).
KEY_PCS_CMD_ACTIVE_W_PREFIX = "pcs_cmd_active_power_w_"
KEY_PCS_CMD_REACTIVE_W_PREFIX = "pcs_cmd_reactive_power_var_"
# Legacy flat command keys: a single value for the whole PCS fleet (older
# callers and direct-engine tests).
KEY_PCS_CMD_ACTIVE_W = "pcs_cmd_active_power_w"
KEY_PCS_CMD_REACTIVE_W = "pcs_cmd_reactive_power_var"

# Per-device actual power keys written by the PCS plugin itself.
KEY_PCS_ACTUAL_P_W_PREFIX = "pcs_actual_power_w_"
KEY_PCS_ACTUAL_Q_PREFIX = "pcs_actual_reactive_power_var_"

# Authoritative AC grid voltage read by all PCS units in Phase 3.
KEY_PCS_AC_GRID_VOLTAGE_V = "pcs_ac_grid_voltage_v"

# Authoritative DC bus voltage computed by the PlantBatteryDistributionTask
# (Phase 4) from the available battery voltages; the PCS plugins read it in
# Phase 3 for the *next* tick's DC operating point.
KEY_BATTERY_DC_VOLTAGE_V = "battery_dc_voltage_v"


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
