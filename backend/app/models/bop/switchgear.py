"""Generic Switchgear and Circuit Breaker Model."""

import logging
from typing import Any

from pydantic import BaseModel, Field

from backend.app.equipment.models import (
    AlarmRecord,
    AlarmSeverity,
    EquipmentMetadata,
    EquipmentType,
    OperatingState,
    TelemetryPoint,
    UniversalEquipmentState,
)

logger = logging.getLogger(__name__)


class SwitchgearConfigModel(BaseModel):
    """Configuration schema for Switchgear."""

    rated_voltage_v: float = Field(default=13800.0, description="Rated breaker AC voltage")
    rated_current_a: float = Field(default=2000.0, description="Rated breaker continuous current")


class SwitchgearCommandPayload(BaseModel):
    """Command schema for Switchgear breaker control."""

    close_breaker: bool | None = None
    trip_breaker: bool = False
    reset_fault: bool = False


class GenericSwitchgearModel:
    """Configurable MV/HV Circuit Breaker Switchgear Model."""

    def __init__(
        self,
        equipment_id: str = "SWG_01",
        config: SwitchgearConfigModel | None = None,
        is_illustrative: bool = True,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.equipment_type: EquipmentType = EquipmentType.SWITCHGEAR
        self.is_illustrative: bool = is_illustrative
        self.config: SwitchgearConfigModel = (
            config if config is not None else SwitchgearConfigModel()
        )

        self.breaker_closed: bool = False
        self.interlock_ok: bool = True
        self.trip_coil_healthy: bool = True
        self.operating_state: OperatingState = OperatingState.STANDBY
        self.is_available: bool = True
        self.active_alarms: list[AlarmRecord] = []
        self.last_step_timestamp_ns: int = 0

    def process_command(self, cmd: dict[str, Any]) -> bool:
        """Process breaker command payload.

        Returns:
            True if command accepted, False if rejected by interlocks or fault state.
        """
        try:
            parsed = SwitchgearCommandPayload(**cmd)

            if parsed.reset_fault:
                self.clear_faults()

            if parsed.trip_breaker:
                self.trip_breaker("MANUAL_OPERATOR_TRIP", "Manual operator trip command issued")
                return True

            if parsed.close_breaker is True:
                if not self.interlock_ok or self.operating_state == OperatingState.FAULTED:
                    logger.warning("Switchgear rejected close command: Interlocks not OK.")
                    return False
                self.breaker_closed = True
                self.operating_state = OperatingState.RUNNING
                return True
            elif parsed.close_breaker is False:
                self.breaker_closed = False
                self.operating_state = OperatingState.STANDBY
                return True

            return True
        except Exception as e:
            logger.error("Switchgear command validation failed: %s", e)
            return False

    def trip_breaker(
        self, code: str = "BREAKER_TRIPPED", description: str = "Protection trip"
    ) -> None:
        """Trip circuit breaker open immediately."""
        self.breaker_closed = False
        self.operating_state = OperatingState.FAULTED
        self.is_available = False
        alarm = AlarmRecord(
            code=code,
            severity=AlarmSeverity.CRITICAL,
            description=description,
            timestamp_ns=self.last_step_timestamp_ns,
            source_id=self.equipment_id,
        )
        self.active_alarms.append(alarm)

    def clear_faults(self) -> None:
        """Clear active faults and restore breaker interlocks."""
        for a in self.active_alarms:
            a.cleared = True
        self.interlock_ok = True
        self.operating_state = OperatingState.STANDBY
        self.is_available = True

    def step(self, current_a: float, timestamp_ns: int = 0, delta_t_s: float = 0.01) -> None:
        """Execute step and evaluate over-current trip protection."""
        self.last_step_timestamp_ns = timestamp_ns

        if self.breaker_closed and current_a > self.config.rated_current_a * 1.5:
            msg = (
                f"Breaker current ({current_a:.1f} A) exceeded 150% "
                f"rating ({self.config.rated_current_a * 1.5:.1f} A)"
            )
            self.trip_breaker("OVER_CURRENT_TRIP", msg)

    def get_state(self) -> UniversalEquipmentState:
        """Return universal equipment state snapshot."""
        return UniversalEquipmentState(
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            metadata=EquipmentMetadata(
                manufacturer="Generic BESS",
                model_name="MV Vacuum Circuit Breaker 13.8kV",
                is_illustrative=self.is_illustrative,
            ),
            operating_state=self.operating_state,
            is_available=self.is_available,
            timestamp_ns=self.last_step_timestamp_ns,
            measurements={
                "breaker_closed": TelemetryPoint(
                    value=1.0 if self.breaker_closed else 0.0,
                    unit="bool",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "interlock_ok": TelemetryPoint(
                    value=1.0 if self.interlock_ok else 0.0,
                    unit="bool",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
            },
            active_limits={
                "rated_voltage_v": self.config.rated_voltage_v,
                "rated_current_a": self.config.rated_current_a,
            },
            alarms=[a for a in self.active_alarms if not a.cleared],
        )

    def restore_state_snapshot(self, state: UniversalEquipmentState) -> None:
        """Restore switchgear physical and operator state from a snapshot."""
        self.last_step_timestamp_ns = state.timestamp_ns
        self.operating_state = state.operating_state
        self.is_available = state.is_available
        breaker_point = state.measurements.get("breaker_closed")
        self.breaker_closed = bool(breaker_point.value) if breaker_point is not None else False
        interlock_point = state.measurements.get("interlock_ok")
        self.interlock_ok = bool(interlock_point.value) if interlock_point is not None else True
        self.active_alarms = list(state.alarms)

    def reset_to_initial_conditions(self) -> None:
        """Reset switchgear to its configured safe and idle defaults."""
        self.breaker_closed = False
        self.interlock_ok = True
        self.trip_coil_healthy = True
        self.operating_state = OperatingState.STANDBY
        self.is_available = True
        self.active_alarms.clear()
        self.last_step_timestamp_ns = 0
