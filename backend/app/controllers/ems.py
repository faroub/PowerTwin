"""Energy Management System (EMS — Layer C) — Economic Dispatch and Feasibility Checking."""

import logging
import math
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.controllers.equipment_controller import BESSEquipmentController
from backend.app.controllers.ppc import PowerPlantController
from backend.app.equipment.models import OperatingState
from backend.app.models.battery.bms import GenericBMSModel
from backend.app.models.battery.system import GenericBatterySystemModel
from backend.app.models.bop.transformer import GenericTransformerModel
from backend.app.models.grid.poi_model import POIModel
from backend.app.models.pcs.pcs_model import GenericPCSModel

logger = logging.getLogger(__name__)

# Default POI bound used when the plant POI model is unknown to the EMS.
DEFAULT_POI_LIMIT_W: float = 50_000_000.0


class EMSMode(StrEnum):
    """EMS Operational Dispatch Modes."""

    MANUAL_DISPATCH = "MANUAL_DISPATCH"
    SCHEDULED_PROFILE = "SCHEDULED_PROFILE"
    PEAK_SHAVING = "PEAK_SHAVING"
    FREQUENCY_RESPONSE = "FREQUENCY_RESPONSE"


class DispatchFeasibilityResult(BaseModel):
    """Feasibility report returned by EMS dispatch feasibility check."""

    is_feasible: bool
    status_code: str
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

    @field_validator("droop_pct")
    @classmethod
    def validate_droop_pct(cls, v: float) -> float:
        if v <= 0.0 or v > 100.0 or math.isnan(v) or math.isinf(v):
            raise ValueError(f"EMS droop_pct must be in (0.0, 100.0], got: {v}")
        return v

    @field_validator("f_deadband_hz")
    @classmethod
    def validate_f_deadband_hz(cls, v: float) -> float:
        if v < 0.0 or v > 10.0 or math.isnan(v) or math.isinf(v):
            raise ValueError(f"EMS f_deadband_hz must be in [0.0, 10.0], got: {v}")
        return v


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
        batteries: GenericBatterySystemModel | list[GenericBatterySystemModel] | None = None,
        bms_list: list[GenericBMSModel] | None = None,
        pcs_list: list[GenericPCSModel] | None = None,
        equipment_controller: BESSEquipmentController | None = None,
        poi: POIModel | None = None,
        poi_max_export_p_w: float | None = None,
        poi_max_import_p_w: float | None = None,
        timestamp_ns: int = 0,
        battery: GenericBatterySystemModel | list[GenericBatterySystemModel] | None = None,
    ) -> DispatchFeasibilityResult:
        """Verify whether a requested dispatch setpoint is physically and operationally feasible.

        The authoritative POI import/export limits come from the configured POI model
        when it is passed to the check; a missed POI falls back to the (default)
        import/export limits so no unbounded dispatch can be accepted.
        """
        bat_input = batteries if batteries is not None else battery
        bms_input = bms_list if bms_list is not None else []
        pcs_input = pcs_list if pcs_list is not None else []

        # 1. Reject every non-finite setpoint before any arithmetic runs.
        if (
            not math.isfinite(p_req)
            or not math.isfinite(q_req)
            or math.isnan(p_req)
            or math.isnan(q_req)
            or math.isinf(p_req)
            or math.isinf(q_req)
        ):
            logger.warning("Rejected non-finite EMS dispatch request (p=%r, q=%r).", p_req, q_req)
            return DispatchFeasibilityResult(
                is_feasible=False,
                status_code="REJECTED_NON_FINITE",
                requested_p_w=p_req,
                max_feasible_p_w=0.0,
                requested_q_var=q_req,
                max_feasible_q_var=0.0,
                reason="NON_FINITE_DISPATCH_REQUEST",
            )

        # 2. Reject stale equipment controller heartbeats (watchdog interlock).
        if equipment_controller is not None and (
            not equipment_controller.is_available
            or equipment_controller.operating_state != OperatingState.RUNNING
        ):
            return DispatchFeasibilityResult(
                is_feasible=False,
                status_code="REJECTED_INTERLOCK",
                requested_p_w=p_req,
                max_feasible_p_w=0.0,
                requested_q_var=q_req,
                max_feasible_q_var=0.0,
                reason="EQUIPMENT_CONTROLLER_UNAVAILABLE",
            )

        if equipment_controller is not None and (
            equipment_controller.last_heartbeat_ns > 0.0
            and (timestamp_ns - equipment_controller.last_heartbeat_ns)
            > equipment_controller.config.watchdog_timeout_ns
        ):
            msg = (
                f"WATCHDOG_TIMEOUT: EquipmentController heartbeat stale "
                f"{(timestamp_ns - equipment_controller.last_heartbeat_ns) / 1e9:.2f}s "
                f"(timeout {equipment_controller.config.watchdog_timeout_ns} ns)"
            )
            logger.warning(msg)
            return DispatchFeasibilityResult(
                is_feasible=False,
                status_code="REJECTED_INTERLOCK",
                requested_p_w=p_req,
                max_feasible_p_w=0.0,
                requested_q_var=q_req,
                max_feasible_q_var=0.0,
                reason="EQUIPMENT_CONTROLLER_WATCHDOG_STALE",
            )

        if bat_input is None:
            battery_list: list[GenericBatterySystemModel] = []
        elif isinstance(bat_input, list):
            battery_list = bat_input
        else:
            battery_list = [bat_input]

        # 2. Multi-Container Battery & BMS Power Limits Aggregation
        active_bats = [b for b in battery_list if b.is_available]
        active_bms = [bms for bms in bms_input if bms.is_available]
        active_pcs = [
            pcs
            for pcs in pcs_input
            if pcs.is_available
            and pcs.operating_state in (OperatingState.RUNNING, OperatingState.STANDBY)
        ]

        if not active_bats or not active_bms or not active_pcs:
            return DispatchFeasibilityResult(
                is_feasible=False,
                status_code="REJECTED_INFEASIBLE",
                requested_p_w=p_req,
                max_feasible_p_w=0.0,
                requested_q_var=q_req,
                max_feasible_q_var=0.0,
                reason="NO_ACTIVE_EQUIPMENT_AVAILABLE",
            )

        sum_bat_dis_w = sum(b.get_available_power_limits()[1] for b in active_bats)
        sum_bat_ch_w = sum(b.get_available_power_limits()[0] for b in active_bats)

        sum_bms_dis_w = sum(bms.dpl_w for bms in active_bms)
        sum_bms_ch_w = sum(bms.cpl_w for bms in active_bms)

        sum_pcs_active_power_w = sum(pcs.config.rated_active_power_w for pcs in active_pcs)

        # 3. Resolve the authoritative POI import/export limits.
        export_limit = poi_max_export_p_w if poi_max_export_p_w is not None else DEFAULT_POI_LIMIT_W
        import_limit = poi_max_import_p_w if poi_max_import_p_w is not None else DEFAULT_POI_LIMIT_W
        if poi is not None:
            export_limit = poi.config.max_export_power_w
            import_limit = poi.config.max_import_power_w

        # 4. Aggregate the equipment limits under the resolved interconnection limits.
        effective_dis_max_w = min(
            sum_bat_dis_w, sum_bms_dis_w, sum_pcs_active_power_w, export_limit
        )
        effective_ch_max_w = min(sum_bat_ch_w, sum_bms_ch_w, sum_pcs_active_power_w, import_limit)

        # 5. Active Power Feasibility
        if p_req > 0.0:  # Discharging
            if effective_dis_max_w <= 0.0:
                return DispatchFeasibilityResult(
                    is_feasible=False,
                    status_code="REJECTED_INFEASIBLE",
                    requested_p_w=p_req,
                    max_feasible_p_w=0.0,
                    requested_q_var=q_req,
                    max_feasible_q_var=0.0,
                    reason="BATTERY_EMPTY_OR_DISCHARGE_RESTRICTED",
                )
            feasible_p = min(p_req, effective_dis_max_w)
            p_feasible = feasible_p == p_req
        elif p_req < 0.0:  # Charging
            abs_p = abs(p_req)
            if effective_ch_max_w <= 0.0:
                return DispatchFeasibilityResult(
                    is_feasible=False,
                    status_code="REJECTED_INFEASIBLE",
                    requested_p_w=p_req,
                    max_feasible_p_w=0.0,
                    requested_q_var=q_req,
                    max_feasible_q_var=0.0,
                    reason="BATTERY_FULL_OR_CHARGE_RESTRICTED",
                )
            feasible_p = -min(abs_p, effective_ch_max_w)
            p_feasible = abs(feasible_p) == abs_p
        else:
            feasible_p = 0.0
            p_feasible = True

        # 6. Reactive Power Headroom Aggregation
        num_active = len(active_pcs)
        unit_p = abs(feasible_p) / max(1, num_active)

        total_q_headroom_var = sum(
            math.sqrt(max(0.0, (pcs.config.rated_apparent_power_va**2) - (unit_p**2)))
            for pcs in active_pcs
        )

        feasible_q = max(-total_q_headroom_var, min(total_q_headroom_var, q_req))
        q_feasible = feasible_q == q_req

        is_overall_feasible = p_feasible and q_feasible
        status_code = "FEASIBLE" if is_overall_feasible else "DERATED_BY_SAFETY_LIMITS"
        reason = (
            "DISPATCH_FEASIBLE"
            if is_overall_feasible
            else "DISPATCH_DERATED_DUE_TO_EQUIPMENT_LIMITS"
        )

        return DispatchFeasibilityResult(
            is_feasible=is_overall_feasible,
            status_code=status_code,
            requested_p_w=p_req,
            max_feasible_p_w=feasible_p,
            requested_q_var=q_req,
            max_feasible_q_var=feasible_q,
            reason=reason,
        )

    def dispatch_step(
        self,
        requested_p_w: float,
        requested_q_var: float,
        ppc: PowerPlantController,
        battery: GenericBatterySystemModel | list[GenericBatterySystemModel],
        bms_list: list[GenericBMSModel],
        pcs_list: list[GenericPCSModel],
        equipment_controller: BESSEquipmentController,
        grid_frequency_hz: float = 50.0,
        timestamp_ns: int = 0,
        poi: POIModel | None = None,
        transformers: list[GenericTransformerModel] | None = None,
    ) -> tuple[float, float]:
        """Execute EMS dispatch loop, performing feasibility check before forwarding to PPC.

        The authoritative POI import/export limits are read from the attached POI
        model, so the dispatch can never be accepted beyond the configured grid
        interconnection.
        """
        self.requested_p_w = requested_p_w
        self.requested_q_var = requested_q_var

        target_p = requested_p_w
        target_q = requested_q_var

        # 1. Frequency Response Droop (Automatically determines 50 Hz or 60 Hz nominal base)
        if self.active_mode == EMSMode.FREQUENCY_RESPONSE:
            f_nom = 60.0 if grid_frequency_hz >= 55.0 else 50.0
            f_diff = grid_frequency_hz - f_nom
            if abs(f_diff) > self.config.f_deadband_hz:
                plant_p_rated = ppc.config.plant_rated_active_power_w
                droop_p = -(plant_p_rated / (self.config.droop_pct / 100.0)) * (f_diff / f_nom)
                target_p = droop_p

        # 1b. Scheduled Profile Mode (Time-of-Use Dispatch)
        if self.active_mode == EMSMode.SCHEDULED_PROFILE and self.schedule:
            for item in self.schedule:
                start_ns = item.start_time_ns
                end_ns = start_ns + int(item.duration_s * 1e9)
                if start_ns <= timestamp_ns < end_ns:
                    target_p = item.p_demand_w
                    target_q = item.q_demand_var
                    break

        # 2. Feasibility Evaluation
        feasibility = self.check_feasibility(
            target_p,
            target_q,
            batteries=battery,
            bms_list=bms_list,
            pcs_list=pcs_list,
            equipment_controller=equipment_controller,
            poi=poi,
            timestamp_ns=timestamp_ns,
        )

        if (
            not feasibility.is_feasible
            and feasibility.max_feasible_p_w == 0.0
            and feasibility.max_feasible_q_var == 0.0
        ):
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

        # 3. Forward Feasible Setpoints to PPC
        dispatch_p = feasibility.max_feasible_p_w
        dispatch_q = feasibility.max_feasible_q_var
        acc_p, acc_q = ppc.dispatch_poi_setpoint(
            dispatch_p,
            dispatch_q,
            pcs_list,
            transformers=transformers,
            timestamp_ns=timestamp_ns,
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
