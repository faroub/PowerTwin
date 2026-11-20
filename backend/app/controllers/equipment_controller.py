"""Equipment Controller (Layer A) — Device Startup/Shutdown Sequencing and Interlocks."""

import logging

from pydantic import BaseModel, Field

from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.equipment.models import AlarmRecord, OperatingState
from backend.app.models.battery.bms import GenericBMSModel
from backend.app.models.bop.switchgear import GenericSwitchgearModel
from backend.app.models.pcs.pcs_model import GenericPCSModel

logger = logging.getLogger(__name__)


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

    def check_permissives(
        self,
        bms_list: list[GenericBMSModel],
        pcs_list: list[GenericPCSModel],
        switchgear: GenericSwitchgearModel,
        container_temp_c: float = 25.0,
        current_time_ns: int = 0,
    ) -> tuple[bool, str]:
        """Check equipment permissives prior to startup."""
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
        """Execute coordinated equipment startup sequence."""
        self.update_heartbeat(current_time_ns)
        permissives_ok, reason = self.check_permissives(
            bms_list, pcs_list, switchgear, container_temp_c, current_time_ns
        )

        if not permissives_ok:
            logger.warning("Startup sequence aborted: %s", reason)
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

        self.operating_state = OperatingState.STANDBY

        # Step 2: Close Switchgear
        switchgear.process_command({"close_breaker": True})

        # Step 3: Close BMS Contactors
        for bms in bms_list:
            bms.process_command({"close_contactors": True})

        # Step 4: Enable PCS Inverters
        for pcs in pcs_list:
            pcs.process_command({"enable_inverter": True})

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

    def update_heartbeat(self, current_time_ns: int) -> None:
        """Update communication watchdog heartbeat timestamp."""
        self.last_heartbeat_ns = current_time_ns
