"""Energy Management System (EMS — Layer C) — Economic Dispatch and Feasibility Checking."""

import logging
from enum import StrEnum

from pydantic import BaseModel, Field

from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.controllers.equipment_controller import BESSEquipmentController
from backend.app.controllers.ppc import PowerPlantController
from backend.app.equipment.models import OperatingState
from backend.app.models.battery.bms import GenericBMSModel
from backend.app.models.battery.system import GenericBatterySystemModel
from backend.app.models.pcs.pcs_model import GenericPCSModel

logger = logging.getLogger(__name__)


class EMSMode(StrEnum):
    """EMS Operational Dispatch Modes."""

    MANUAL_DISPATCH = "MANUAL_DISPATCH"
    SCHEDULED_PROFILE = "SCHEDULED_PROFILE"
    PEAK_SHAVING = "PEAK_SHAVING"
    FREQUENCY_RESPONSE = "FREQUENCY_RESPONSE"


class DispatchFeasibilityResult(BaseModel):
    """Feasibility report returned by EMS dispatch feasibility check."""

    is_feasible: bool
    requested_p_w: float
    max_feasible_p_w: float
    requested_q_var: float
    max_feasible_q_var: float
    reason: str


class DispatchScheduleItem(BaseModel):
    """Schedule item definition for time-of-use dispatch."""

    start_time_ns: int
    duration_s: float
    p_demand_w: float
    q_demand_var: float = 0.0


class EMSConfigModel(BaseModel):
    """Configuration schema for EMS."""

    mode: EMSMode = Field(default=EMSMode.MANUAL_DISPATCH)
    target_soc_pct: float = Field(default=50.0, description="Target SoC for auto-recharge/idle")
    droop_pct: float = Field(default=5.0, description="P-f frequency droop percentage (5%)")
    f_deadband_hz: float = Field(default=0.03, description="Frequency deadband in Hz (+/-0.03 Hz)")


class EnergyManagementSystem:
    """Energy Management System (Layer C) executing dispatch optimization and feasibility."""

    def __init__(
        self,
        equipment_id: str = "EMS_01",
        config: EMSConfigModel | None = None,
        audit_log: ControlCommandLog | None = None,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.config: EMSConfigModel = config if config is not None else EMSConfigModel()
        self.audit_log: ControlCommandLog = (
            audit_log if audit_log is not None else ControlCommandLog()
        )

        self.active_mode: EMSMode = self.config.mode
        self.requested_p_w: float = 0.0
        self.requested_q_var: float = 0.0

        self.schedule: list[DispatchScheduleItem] = []
        self.operating_state: OperatingState = OperatingState.RUNNING

    def check_feasibility(
        self,
        p_req: float,
        q_req: float,
        battery: GenericBatterySystemModel,
        bms_list: list[GenericBMSModel],
        pcs_list: list[GenericPCSModel],
        equipment_controller: BESSEquipmentController,
    ) -> DispatchFeasibilityResult:
        """Verify whether a requested dispatch setpoint is physically and operationally feasible."""
        # 1. Equipment Controller Availability Check
        if (
            not equipment_controller.is_available
            or equipment_controller.operating_state != OperatingState.RUNNING
        ):
            return DispatchFeasibilityResult(
                is_feasible=False,
                requested_p_w=p_req,
                max_feasible_p_w=0.0,
                requested_q_var=q_req,
                max_feasible_q_var=0.0,
                reason="EQUIPMENT_CONTROLLER_UNAVAILABLE",
            )

        # 2. Battery SoC & Power Limit Check
        ch_avail_w, dis_avail_w = battery.get_available_power_limits()

        # 3. BMS Power Limit Check
        bms_ch_limit_w = min((bms.cpl_w for bms in bms_list if bms.is_available), default=0.0)
        bms_dis_limit_w = min((bms.dpl_w for bms in bms_list if bms.is_available), default=0.0)

        effective_ch_max_w = min(ch_avail_w, bms_ch_limit_w)
        effective_dis_max_w = min(dis_avail_w, bms_dis_limit_w)

        # 4. Feasibility Evaluation
        if p_req > 0.0:  # Discharging
            if effective_dis_max_w <= 0.0:
                return DispatchFeasibilityResult(
                    is_feasible=False,
                    requested_p_w=p_req,
                    max_feasible_p_w=0.0,
                    requested_q_var=q_req,
                    max_feasible_q_var=0.0,
                    reason=f"BATTERY_EMPTY_OR_DISCHARGE_RESTRICTED (SoC = {battery.soc_pct:.1f}%)",
                )
            feasible_p = min(p_req, effective_dis_max_w)
            is_feasible = feasible_p == p_req
        elif p_req < 0.0:  # Charging
            abs_p = abs(p_req)
            if effective_ch_max_w <= 0.0:
                return DispatchFeasibilityResult(
                    is_feasible=False,
                    requested_p_w=p_req,
                    max_feasible_p_w=0.0,
                    requested_q_var=q_req,
                    max_feasible_q_var=0.0,
                    reason=f"BATTERY_FULL_OR_CHARGE_RESTRICTED (SoC = {battery.soc_pct:.1f}%)",
                )
            feasible_p = -min(abs_p, effective_ch_max_w)
            is_feasible = abs(feasible_p) == abs_p
        else:
            feasible_p = 0.0
            is_feasible = True

        reason = "DISPATCH_FEASIBLE" if is_feasible else "DISPATCH_DERATED_DUE_TO_BATTERY_LIMITS"
        return DispatchFeasibilityResult(
            is_feasible=is_feasible,
            requested_p_w=p_req,
            max_feasible_p_w=feasible_p,
            requested_q_var=q_req,
            max_feasible_q_var=q_req,
            reason=reason,
        )

    def dispatch_step(
        self,
        requested_p_w: float,
        requested_q_var: float,
        ppc: PowerPlantController,
        battery: GenericBatterySystemModel,
        bms_list: list[GenericBMSModel],
        pcs_list: list[GenericPCSModel],
        equipment_controller: BESSEquipmentController,
        grid_frequency_hz: float = 60.0,
        timestamp_ns: int = 0,
    ) -> tuple[float, float]:
        """Execute EMS dispatch loop, performing feasibility check before forwarding to PPC."""
        self.requested_p_w = requested_p_w
        self.requested_q_var = requested_q_var

        target_p = requested_p_w
        target_q = requested_q_var

        if self.active_mode == EMSMode.FREQUENCY_RESPONSE:
            f_diff = grid_frequency_hz - 60.0
            if abs(f_diff) > self.config.f_deadband_hz:
                droop_p = -(50_000_000.0 / (self.config.droop_pct / 100.0)) * (f_diff / 60.0)
                target_p = droop_p

        # 1. Check Feasibility
        feasibility = self.check_feasibility(
            target_p, target_q, battery, bms_list, pcs_list, equipment_controller
        )

        if not feasibility.is_feasible and feasibility.max_feasible_p_w == 0.0:
            self.audit_log.log_entry(
                timestamp_ns=timestamp_ns,
                source_layer="EMS",
                target_component=self.equipment_id,
                action_name="EMS_DISPATCH",
                requested_value={"p_w": requested_p_w, "q_var": requested_q_var},
                accepted_value={"p_w": 0.0, "q_var": 0.0},
                status=CommandStatus.REJECTED_INFEASIBLE,
                reason=feasibility.reason,
            )
            ppc.dispatch_poi_setpoint(0.0, 0.0, pcs_list, timestamp_ns=timestamp_ns)
            return (0.0, 0.0)

        # 2. Dispatch Feasible P to PPC
        dispatch_p = feasibility.max_feasible_p_w
        acc_p, acc_q = ppc.dispatch_poi_setpoint(
            dispatch_p, target_q, pcs_list, timestamp_ns=timestamp_ns
        )

        status = CommandStatus.ACCEPTED if feasibility.is_feasible else CommandStatus.DERATED
        self.audit_log.log_entry(
            timestamp_ns=timestamp_ns,
            source_layer="EMS",
            target_component=self.equipment_id,
            action_name="EMS_DISPATCH",
            requested_value={"p_w": requested_p_w, "q_var": requested_q_var},
            accepted_value={"p_w": acc_p, "q_var": acc_q},
            status=status,
            reason=feasibility.reason,
        )

        return (acc_p, acc_q)
