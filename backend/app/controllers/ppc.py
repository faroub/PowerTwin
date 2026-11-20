"""Power Plant Controller (PPC — Layer B) — POI Power Regulation and Unit Allocation."""

import logging
import math
from enum import StrEnum

from pydantic import BaseModel, Field

from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.equipment.models import OperatingState
from backend.app.models.bop.transformer import GenericTransformerModel
from backend.app.models.pcs.pcs_model import GenericPCSModel

logger = logging.getLogger(__name__)


class PPCPriorityMode(StrEnum):
    """PPC PQ Priority Modes."""

    ACTIVE_POWER_PRIORITY = "ACTIVE_POWER_PRIORITY"
    REACTIVE_POWER_PRIORITY = "REACTIVE_POWER_PRIORITY"


class PPCControlMode(StrEnum):
    """PPC Operational Control Modes."""

    MANUAL_PQ = "MANUAL_PQ"
    VOLT_VAR = "VOLT_VAR"
    POWER_FACTOR = "POWER_FACTOR"


class PPCConfigModel(BaseModel):
    """Configuration schema for Power Plant Controller."""

    plant_rated_active_power_w: float = Field(
        default=50_000_000.0, description="Plant max active power rating (50 MW)"
    )
    plant_rated_apparent_power_va: float = Field(
        default=55_000_000.0, description="Plant max apparent power rating (55 MVA)"
    )
    max_ramp_rate_w_per_s: float = Field(
        default=10_000_000.0, description="POI Active power ramp rate limit (10 MW/s)"
    )
    priority_mode: PPCPriorityMode = Field(default=PPCPriorityMode.ACTIVE_POWER_PRIORITY)
    default_control_mode: PPCControlMode = Field(default=PPCControlMode.MANUAL_PQ)
    target_power_factor: float = Field(default=1.0)


class PowerPlantController:
    """Power Plant Controller (Layer B) regulating POI active/reactive power and unit allocation."""

    def __init__(
        self,
        equipment_id: str = "PPC_01",
        config: PPCConfigModel | None = None,
        audit_log: ControlCommandLog | None = None,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.config: PPCConfigModel = config if config is not None else PPCConfigModel()
        self.audit_log: ControlCommandLog = (
            audit_log if audit_log is not None else ControlCommandLog()
        )

        self.control_mode: PPCControlMode = self.config.default_control_mode

        # Setpoints
        self.requested_p_w: float = 0.0
        self.requested_q_var: float = 0.0

        self.accepted_p_w: float = 0.0
        self.accepted_q_var: float = 0.0

        self.operating_state: OperatingState = OperatingState.RUNNING
        self.is_available: bool = True

    def dispatch_poi_setpoint(
        self,
        requested_p_w: float,
        requested_q_var: float,
        pcs_units: list[GenericPCSModel],
        transformer: GenericTransformerModel | None = None,
        poi_voltage_v: float = 13800.0,
        timestamp_ns: int = 0,
    ) -> tuple[float, float]:
        """Validate setpoints, enforce plant PQ capability, allocate power to active PCS units."""
        self.requested_p_w = requested_p_w
        self.requested_q_var = requested_q_var

        # 1. Filter Available PCS Units
        available_pcs = [
            pcs
            for pcs in pcs_units
            if pcs.is_available
            and pcs.operating_state in (OperatingState.RUNNING, OperatingState.STANDBY)
        ]

        if not available_pcs or not self.is_available:
            self.accepted_p_w = 0.0
            self.accepted_q_var = 0.0
            for pcs in pcs_units:
                pcs.process_command({"requested_p_w": 0.0, "requested_q_var": 0.0})
            self.audit_log.log_entry(
                timestamp_ns=timestamp_ns,
                source_layer="PPC",
                target_component=self.equipment_id,
                action_name="DISPATCH_POI_SETPOINT",
                requested_value={"p_w": requested_p_w, "q_var": requested_q_var},
                accepted_value={"p_w": 0.0, "q_var": 0.0},
                status=CommandStatus.REJECTED_INTERLOCK,
                reason="NO_AVAILABLE_PCS_UNITS",
            )
            return (0.0, 0.0)

        plant_avail_p_max = sum(pcs.config.rated_active_power_w for pcs in available_pcs)
        plant_avail_s_max = sum(pcs.config.rated_apparent_power_va for pcs in available_pcs)

        # 2. Control Mode Modifications (Volt-VAR / Power Factor)
        effective_q_req = requested_q_var
        if self.control_mode == PPCControlMode.VOLT_VAR:
            v_dev_pct = (poi_voltage_v - 13800.0) / 13800.0
            if abs(v_dev_pct) > 0.01:
                effective_q_req = -v_dev_pct * 10.0 * (plant_avail_s_max * 0.1)

        elif self.control_mode == PPCControlMode.POWER_FACTOR:
            pf = max(0.8, min(1.0, self.config.target_power_factor))
            if pf < 1.0:
                effective_q_req = requested_p_w * math.tan(math.acos(pf))

        # 3. Enforce Plant Apparent Power Capability Circle (P^2 + Q^2 <= S_plant_max^2)
        s_max_cap = min(self.config.plant_rated_apparent_power_va, plant_avail_s_max)
        p_cap = min(self.config.plant_rated_active_power_w, plant_avail_p_max)

        if self.config.priority_mode == PPCPriorityMode.ACTIVE_POWER_PRIORITY:
            p_accepted = max(-p_cap, min(p_cap, requested_p_w))
            q_headroom_sq = max(0.0, (s_max_cap**2) - (p_accepted**2))
            q_max_avail = math.sqrt(q_headroom_sq)
            q_accepted = max(-q_max_avail, min(q_max_avail, effective_q_req))
        else:  # REACTIVE_POWER_PRIORITY
            q_accepted = max(-s_max_cap, min(s_max_cap, effective_q_req))
            p_headroom_sq = max(0.0, (s_max_cap**2) - (q_accepted**2))
            p_max_avail = min(p_cap, math.sqrt(p_headroom_sq))
            p_accepted = max(-p_max_avail, min(p_max_avail, requested_p_w))

        self.accepted_p_w = p_accepted
        self.accepted_q_var = q_accepted

        # 4. Power Allocation Among Available PCS Units
        num_units = len(available_pcs)
        unit_p_w = p_accepted / num_units
        unit_q_var = q_accepted / num_units

        for pcs in pcs_units:
            if pcs in available_pcs:
                pcs.process_command({"requested_p_w": unit_p_w, "requested_q_var": unit_q_var})
            else:
                pcs.process_command({"requested_p_w": 0.0, "requested_q_var": 0.0})

        is_exact = p_accepted == requested_p_w and q_accepted == requested_q_var
        status = CommandStatus.ACCEPTED if is_exact else CommandStatus.DERATED

        self.audit_log.log_entry(
            timestamp_ns=timestamp_ns,
            source_layer="PPC",
            target_component=self.equipment_id,
            action_name="DISPATCH_POI_SETPOINT",
            requested_value={"p_w": requested_p_w, "q_var": requested_q_var},
            accepted_value={"p_w": p_accepted, "q_var": q_accepted},
            status=status,
            reason="POI_DISPATCH_PROCESSED",
        )

        return (p_accepted, q_accepted)
