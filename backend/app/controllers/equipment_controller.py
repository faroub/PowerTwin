"""Equipment Controller (Layer A) — Device Startup/Shutdown Sequencing and Interlocks."""

import logging
from enum import StrEnum

from pydantic import BaseModel, Field

from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.equipment.models import AlarmRecord, OperatingState
from backend.app.models.battery.bms import GenericBMSModel
from backend.app.models.bop.switchgear import GenericSwitchgearModel
from backend.app.models.pcs.pcs_model import GenericPCSModel

logger = logging.getLogger(__name__)


class StartupStep(StrEnum):
    """Defined Startup Sequence State Machine Steps."""

    CHECK_PERMISSIVES = "CHECK_PERMISSIVES"
    CLOSE_BREAKER = "CLOSE_BREAKER"
    CLOSE_CONTACTORS = "CLOSE_CONTACTORS"
    ENABLE_INVERTERS = "ENABLE_INVERTERS"
    COMPLETED = "COMPLETED"


class EquipmentControllerConfig(BaseModel):
    """Configuration schema for Equipment Controller."""

    watchdog_timeout_ns: int = Field(
        default=5_000_000_000, description="Watchdog heartbeat timeout (5 seconds)"
    )
    max_container_temp_c: float = Field(
        default=45.0, description="Max safe container temp for startup permissive"
    )


class BESSEquipmentController:
    """Equipment Controller (Layer A) coordinating local device startup/shutdown and interlocks."""

    def __init__(
        self,
        equipment_id: str = "EQ_CTRL_01",
        config: EquipmentControllerConfig | None = None,
        audit_log: ControlCommandLog | None = None,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.config: EquipmentControllerConfig = (
            config if config is not None else EquipmentControllerConfig()
        )
        self.audit_log: ControlCommandLog = (
            audit_log if audit_log is not None else ControlCommandLog()
        )

        self.operating_state: OperatingState = OperatingState.STANDBY
        self.is_available: bool = True
        self.last_heartbeat_ns: int = 0
        self.active_alarms: list[AlarmRecord] = []
        self.state_history: list[tuple[int, str, str]] = []

    def log_state_transition(self, timestamp_ns: int, from_state: str, to_state: str) -> None:
        """Record state transition history."""
        self.state_history.append((timestamp_ns, from_state, to_state))
        logger.info(
            "EquipmentController transition: %s -> %s at t=%d", from_state, to_state, timestamp_ns
        )

    def check_permissives(
        self,
        bms_list: list[GenericBMSModel],
        pcs_list: list[GenericPCSModel],
        switchgear: GenericSwitchgearModel,
        container_temp_c: float = 25.0,
        current_time_ns: int = 0,
    ) -> tuple[bool, str]:
        """Check equipment permissives prior to startup."""
        if self.operating_state == OperatingState.EMERGENCY_STOP:
            return (False, "E_STOP_ACTIVE: Cannot startup while Emergency Stop is latched.")

        # 1. Watchdog timeout check
        if (
            self.last_heartbeat_ns > 0
            and (current_time_ns - self.last_heartbeat_ns) > self.config.watchdog_timeout_ns
        ):
            timeout_s = self.config.watchdog_timeout_ns // 1e9
            return (False, f"WATCHDOG_TIMEOUT: Heartbeat stale > {timeout_s:.1f}s")

        # 2. Container Temperature check
        if container_temp_c > self.config.max_container_temp_c:
            msg = (
                f"CONTAINER_OVER_TEMP: Temp ({container_temp_c:.1f} C) "
                f"exceeds safe limit ({self.config.max_container_temp_c:.1f} C)"
            )
            return (False, msg)

        # 3. Switchgear Interlocks check
        if not switchgear.interlock_ok or switchgear.operating_state == OperatingState.FAULTED:
            return (False, "SWITCHGEAR_INTERLOCK_FAULT: Switchgear interlocks not OK")

        # 4. BMS Fault check
        for bms in bms_list:
            if not bms.is_available or bms.operating_state == OperatingState.FAULTED:
                return (False, f"BMS_FAULT: BMS '{bms.equipment_id}' is in fault state")

        # 5. PCS Fault check
        for pcs in pcs_list:
            if pcs.operating_state == OperatingState.FAULTED:
                return (False, f"PCS_FAULT: PCS '{pcs.equipment_id}' is in fault state")

        return (True, "PERMISSIVES_OK")

    def execute_startup_sequence(
        self,
        bms_list: list[GenericBMSModel],
        pcs_list: list[GenericPCSModel],
        switchgear: GenericSwitchgearModel,
        container_temp_c: float = 25.0,
        current_time_ns: int = 0,
    ) -> bool:
        """Execute state-machine startup sequence with command result verification and rollback."""
        self.update_heartbeat(current_time_ns)

        # Step 1: CHECK_PERMISSIVES
        self.log_state_transition(
            current_time_ns, self.operating_state.value, StartupStep.CHECK_PERMISSIVES.value
        )
        permissives_ok, reason = self.check_permissives(
            bms_list, pcs_list, switchgear, container_temp_c, current_time_ns
        )

        if not permissives_ok:
            logger.warning("Startup sequence aborted at CHECK_PERMISSIVES: %s", reason)
            self.audit_log.log_entry(
                timestamp_ns=current_time_ns,
                source_layer="EQUIPMENT_CONTROLLER",
                target_component=self.equipment_id,
                action_name="STARTUP_SEQUENCE",
                requested_value={"target_state": "RUNNING"},
                accepted_value={"target_state": self.operating_state.value},
                status=CommandStatus.REJECTED_INTERLOCK,
                reason=reason,
            )
            return False

        # Step 2: CLOSE_BREAKER
        self.log_state_transition(
            current_time_ns, StartupStep.CHECK_PERMISSIVES.value, StartupStep.CLOSE_BREAKER.value
        )
        res_swg = switchgear.process_command({"close_breaker": True})
        if not res_swg or not switchgear.breaker_closed:
            self._rollback_startup(
                bms_list, pcs_list, switchgear, "CLOSE_BREAKER_FAILED", current_time_ns
            )
            return False

        # Step 3: CLOSE_CONTACTORS
        self.log_state_transition(
            current_time_ns, StartupStep.CLOSE_BREAKER.value, StartupStep.CLOSE_CONTACTORS.value
        )
        for bms in bms_list:
            res_bms = bms.process_command({"close_contactors": True})
            if not res_bms or not bms.contactors_closed:
                self._rollback_startup(
                    bms_list,
                    pcs_list,
                    switchgear,
                    f"BMS_CONTACTORS_FAILED_{bms.equipment_id}",
                    current_time_ns,
                )
                return False

        # Step 4: ENABLE_INVERTERS
        self.log_state_transition(
            current_time_ns, StartupStep.CLOSE_CONTACTORS.value, StartupStep.ENABLE_INVERTERS.value
        )
        for pcs in pcs_list:
            res_pcs = pcs.process_command({"enable_inverter": True})
            if not res_pcs:
                self._rollback_startup(
                    bms_list,
                    pcs_list,
                    switchgear,
                    f"PCS_ENABLE_FAILED_{pcs.equipment_id}",
                    current_time_ns,
                )
                return False

        # Step 5: COMPLETED -> RUNNING
        self.log_state_transition(
            current_time_ns, StartupStep.ENABLE_INVERTERS.value, OperatingState.RUNNING.value
        )
        self.operating_state = OperatingState.RUNNING
        self.audit_log.log_entry(
            timestamp_ns=current_time_ns,
            source_layer="EQUIPMENT_CONTROLLER",
            target_component=self.equipment_id,
            action_name="STARTUP_SEQUENCE",
            requested_value={"target_state": "RUNNING"},
            accepted_value={"target_state": "RUNNING"},
            status=CommandStatus.ACCEPTED,
            reason="STARTUP_SEQUENCE_SUCCESSFUL",
        )
        return True

    def _rollback_startup(
        self,
        bms_list: list[GenericBMSModel],
        pcs_list: list[GenericPCSModel],
        switchgear: GenericSwitchgearModel,
        failure_reason: str,
        current_time_ns: int,
    ) -> None:
        """Rollback partially executed startup sequence to safe STANDBY state."""
        logger.error("Startup sequence failed (%s); executing rollback.", failure_reason)

        stop_cmd = {"enable_inverter": False, "requested_p_w": 0.0, "requested_q_var": 0.0}
        for pcs in pcs_list:
            pcs.process_command(stop_cmd)

        for bms in bms_list:
            bms.process_command({"close_contactors": False})

        switchgear.process_command({"close_breaker": False})

        self.log_state_transition(
            current_time_ns, self.operating_state.value, OperatingState.STANDBY.value
        )
        self.operating_state = OperatingState.STANDBY

        self.audit_log.log_entry(
            timestamp_ns=current_time_ns,
            source_layer="EQUIPMENT_CONTROLLER",
            target_component=self.equipment_id,
            action_name="STARTUP_ROLLBACK",
            requested_value={"action": "ROLLBACK"},
            accepted_value={"state": "STANDBY"},
            status=CommandStatus.REJECTED_INTERLOCK,
            reason=failure_reason,
        )

    def execute_shutdown_sequence(
        self,
        bms_list: list[GenericBMSModel],
        pcs_list: list[GenericPCSModel],
        switchgear: GenericSwitchgearModel,
        current_time_ns: int = 0,
    ) -> None:
        """Execute coordinated graceful shutdown sequence."""
        stop_cmd = {"enable_inverter": False, "requested_p_w": 0.0, "requested_q_var": 0.0}
        for pcs in pcs_list:
            pcs.process_command(stop_cmd)

        for bms in bms_list:
            bms.process_command({"close_contactors": False})

        switchgear.process_command({"close_breaker": False})

        self.operating_state = OperatingState.STANDBY
        self.audit_log.log_entry(
            timestamp_ns=current_time_ns,
            source_layer="EQUIPMENT_CONTROLLER",
            target_component=self.equipment_id,
            action_name="SHUTDOWN_SEQUENCE",
            requested_value={"target_state": "STANDBY"},
            accepted_value={"target_state": "STANDBY"},
            status=CommandStatus.ACCEPTED,
            reason="SHUTDOWN_SEQUENCE_SUCCESSFUL",
        )

    def emergency_stop(
        self,
        bms_list: list[GenericBMSModel],
        pcs_list: list[GenericPCSModel],
        switchgear: GenericSwitchgearModel,
        reason: str = "EMERGENCY_STOP_TRIGGERED",
        current_time_ns: int = 0,
    ) -> None:
        """Execute emergency stop trip: Trip switchgear, trip contactors, trip PCS."""
        switchgear.trip_breaker("E_STOP_TRIP", reason)
        for bms in bms_list:
            bms.process_command({"target_state": OperatingState.EMERGENCY_STOP})

        stop_cmd = {"enable_inverter": False, "requested_p_w": 0.0, "requested_q_var": 0.0}
        for pcs in pcs_list:
            pcs.process_command(stop_cmd)

        self.log_state_transition(
            current_time_ns, self.operating_state.value, OperatingState.EMERGENCY_STOP.value
        )
        self.operating_state = OperatingState.EMERGENCY_STOP
        self.is_available = False
        self.audit_log.log_entry(
            timestamp_ns=current_time_ns,
            source_layer="EQUIPMENT_CONTROLLER",
            target_component=self.equipment_id,
            action_name="EMERGENCY_STOP",
            requested_value={"action": "E_STOP"},
            accepted_value={"state": "EMERGENCY_STOP"},
            status=CommandStatus.FAULT_TRIP,
            reason=reason,
        )

    def reset_emergency_stop(self) -> None:
        """Explicit reset sequence required to unlatch Emergency Stop state."""
        if self.operating_state == OperatingState.EMERGENCY_STOP:
            self.operating_state = OperatingState.STANDBY
            self.is_available = True
            logger.info("Emergency Stop latched state reset to STANDBY.")

    def reset_to_initial_conditions(self) -> None:
        """Reset the equipment controller to its initial (STANDBY) conditions."""
        self.log_state_transition(
            self.last_heartbeat_ns or 0, self.operating_state.value, OperatingState.STANDBY.value
        )
        self.operating_state = OperatingState.STANDBY
        self.is_available = True
        self.active_alarms = []
        logger.info("EquipmentController reset to initial conditions (STANDBY).")

    def update_heartbeat(self, current_time_ns: int) -> None:
        """Update communication watchdog heartbeat timestamp."""
        self.last_heartbeat_ns = current_time_ns
