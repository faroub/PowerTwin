"""Generic Master BMS Controller Model.

Monitors battery measurements, enforces voltage/current/thermal limits,
calculates dynamic charge/discharge power limits (CPL/DPL), and manages contactor permissives.
"""

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


class BMSProtectionLimits(BaseModel):
    """BMS safety protection and warning thresholds."""

    over_voltage_fault_v: float = Field(default=1250.0)
    under_voltage_fault_v: float = Field(default=750.0)
    over_temp_warn_c: float = Field(default=45.0)
    over_temp_fault_c: float = Field(default=60.0)
    under_temp_warn_c: float = Field(default=5.0)
    under_temp_fault_c: float = Field(default=-10.0)
    high_soc_warn_pct: float = Field(default=90.0)
    low_soc_warn_pct: float = Field(default=10.0)
    max_charge_current_a: float = Field(default=1000.0)
    max_discharge_current_a: float = Field(default=1000.0)


class BMSCommandPayload(BaseModel):
    """Command schema for Master BMS."""

    target_state: OperatingState | None = None
    close_contactors: bool | None = None
    reset_faults: bool = False


class GenericBMSModel:
    """Master Battery Management System (BMS) Controller Model."""

    def __init__(
        self,
        equipment_id: str = "BMS_MASTER_01",
        limits: BMSProtectionLimits | None = None,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.equipment_type: EquipmentType = EquipmentType.BMS
        self.limits: BMSProtectionLimits = limits if limits is not None else BMSProtectionLimits()

        self.operating_state: OperatingState = OperatingState.STANDBY
        self.contactors_closed: bool = False
        self.interlock_ok: bool = True
        self.is_available: bool = True

        self.ccl_a: float = self.limits.max_charge_current_a
        self.dcl_a: float = self.limits.max_discharge_current_a
        self.cpl_w: float = 0.0
        self.dpl_w: float = 0.0

        self.active_warnings: list[str] = []
        self.active_alarms: list[AlarmRecord] = []
        self.last_step_timestamp_ns: int = 0

    def process_command(self, cmd: dict[str, Any]) -> bool:
        """Process inbound BMS command payload.

        Returns:
            True if command accepted, False if rejected by interlocks or validation.
        """
        try:
            parsed = BMSCommandPayload(**cmd)

            if parsed.reset_faults:
                self.clear_faults()

            if parsed.close_contactors is True:
                if not self.interlock_ok or self.operating_state == OperatingState.FAULTED:
                    logger.warning("BMS rejected contactor close command: interlock/fault active.")
                    return False
                self.contactors_closed = True
                self.operating_state = OperatingState.RUNNING
            elif parsed.close_contactors is False:
                self.contactors_closed = False
                self.operating_state = OperatingState.STANDBY

            if parsed.target_state is not None:
                if parsed.target_state == OperatingState.EMERGENCY_STOP:
                    self.operating_state = OperatingState.EMERGENCY_STOP
                    self.contactors_closed = False
                    self.is_available = False
                elif parsed.target_state == OperatingState.OFF:
                    self.operating_state = OperatingState.OFF
                    self.contactors_closed = False

            return True
        except Exception as e:
            logger.error("BMS command validation failed: %s", e)
            return False

    def evaluate_protection(
        self,
        voltage_v: float,
        current_a: float,
        soc_pct: float,
        temp_c: float,
        timestamp_ns: int = 0,
    ) -> None:
        """Evaluate battery sensor measurements against protection thresholds and compute limits."""
        self.last_step_timestamp_ns = timestamp_ns
        self.active_warnings.clear()

        # 1. Critical Safety Fault Evaluation
        if temp_c >= self.limits.over_temp_fault_c:
            msg = (
                f"Battery temp ({temp_c:.1f} C) exceeded "
                f"cutoff ({self.limits.over_temp_fault_c:.1f} C)"
            )
            self._trigger_fault("OVER_TEMP_FAULT", msg, timestamp_ns)
        elif temp_c <= self.limits.under_temp_fault_c:
            msg = (
                f"Battery temp ({temp_c:.1f} C) fell below "
                f"cutoff ({self.limits.under_temp_fault_c:.1f} C)"
            )
            self._trigger_fault("UNDER_TEMP_FAULT", msg, timestamp_ns)

        if voltage_v >= self.limits.over_voltage_fault_v:
            msg = (
                f"DC voltage ({voltage_v:.1f} V) exceeded "
                f"limit ({self.limits.over_voltage_fault_v:.1f} V)"
            )
            self._trigger_fault("OVER_VOLTAGE_FAULT", msg, timestamp_ns)
        elif voltage_v <= self.limits.under_voltage_fault_v and voltage_v > 0.0:
            msg = (
                f"DC voltage ({voltage_v:.1f} V) fell below "
                f"limit ({self.limits.under_voltage_fault_v:.1f} V)"
            )
            self._trigger_fault("UNDER_VOLTAGE_FAULT", msg, timestamp_ns)

        # 2. Warning Thresholds
        if soc_pct >= self.limits.high_soc_warn_pct:
            self.active_warnings.append("HIGH_SOC_WARN")
        elif soc_pct <= self.limits.low_soc_warn_pct:
            self.active_warnings.append("LOW_SOC_WARN")

        if temp_c >= self.limits.over_temp_warn_c:
            self.active_warnings.append("HIGH_TEMP_WARN")
        elif temp_c <= self.limits.under_temp_warn_c:
            self.active_warnings.append("LOW_TEMP_WARN")

        # 3. Dynamic Current and Power Derating Calculation
        if self.operating_state in (
            OperatingState.OFF,
            OperatingState.FAULTED,
            OperatingState.EMERGENCY_STOP,
        ):
            self.ccl_a = 0.0
            self.dcl_a = 0.0
        else:
            # Base limits
            ccl = self.limits.max_charge_current_a
            dcl = self.limits.max_discharge_current_a

            # Thermal derating (50% reduction outside optimal 5C-45C window)
            if temp_c > self.limits.over_temp_warn_c or temp_c < self.limits.under_temp_warn_c:
                ccl *= 0.5
                dcl *= 0.5

            # SoC derating near extremes
            if soc_pct >= 95.0:
                ccl *= max(0.0, (100.0 - soc_pct) / 5.0)
            if soc_pct <= 10.0:
                dcl *= max(0.0, soc_pct / 10.0)

            self.ccl_a = ccl
            self.dcl_a = dcl

        self.cpl_w = self.ccl_a * voltage_v
        self.dpl_w = self.dcl_a * voltage_v

    def _trigger_fault(self, code: str, description: str, timestamp_ns: int) -> None:
        """Helper to trip BMS into fault state."""
        self.operating_state = OperatingState.FAULTED
        self.contactors_closed = False
        self.is_available = False
        self.ccl_a = 0.0
        self.dcl_a = 0.0

        alarm = AlarmRecord(
            code=code,
            severity=AlarmSeverity.CRITICAL,
            description=description,
            timestamp_ns=timestamp_ns,
            source_id=self.equipment_id,
        )
        self.active_alarms.append(alarm)

    def clear_faults(self) -> None:
        """Clear active BMS faults."""
        for a in self.active_alarms:
            a.cleared = True
        self.operating_state = OperatingState.STANDBY
        self.is_available = True
        self.interlock_ok = True

    def get_state(self) -> UniversalEquipmentState:
        """Return universal equipment state for Master BMS."""
        return UniversalEquipmentState(
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            metadata=EquipmentMetadata(
                manufacturer="Generic BESS", model_name="Master BMS Controller V1"
            ),
            operating_state=self.operating_state,
            is_available=self.is_available,
            timestamp_ns=self.last_step_timestamp_ns,
            measurements={
                "ccl_a": TelemetryPoint(
                    value=self.ccl_a,
                    unit="A",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "dcl_a": TelemetryPoint(
                    value=self.dcl_a,
                    unit="A",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "cpl_w": TelemetryPoint(
                    value=self.cpl_w,
                    unit="W",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "dpl_w": TelemetryPoint(
                    value=self.dpl_w,
                    unit="W",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
            },
            active_limits={
                "charge_current_limit_a": self.ccl_a,
                "discharge_current_limit_a": self.dcl_a,
            },
            alarms=[a for a in self.active_alarms if not a.cleared],
        )
