"""Generic Master BMS Controller Model.

SIMULATION MODEL DISCLAIMER:
  This software BMS controller model simulates protection threshold logic for software
  testing and Controller-in-the-Loop integration.
  It is NOT certified hardware or a replacement for physical BMS protection equipment.

Monitors battery measurements, enforces voltage/current/thermal limits,
calculates dynamic charge/discharge power limits (CPL/DPL), and manages contactor permissives.
"""

import logging
import math
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


def _restore_measurement(
    measurements: dict[str, TelemetryPoint], name: str, default: float
) -> float:
    """Restore a float telemetry measurement, rejecting non-finite values.

    Returns `default` when the measurement is missing or not finite.
    """
    point = measurements.get(name)
    if point is None:
        return default
    value = point.value
    if not math.isfinite(value):
        return default
    return value


class BMSProtectionLimits(BaseModel):
    """BMS safety protection and warning thresholds."""

    over_voltage_fault_v: float = Field(default=1500.0)
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
        self.cpl_w: float = self.limits.max_charge_current_a * 1000.0
        self.dpl_w: float = self.limits.max_discharge_current_a * 1000.0

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
                if (
                    not self.interlock_ok
                    or self.operating_state == OperatingState.FAULTED
                    or not self.is_available
                ):
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
        quality: str = "GOOD",
    ) -> None:
        """Evaluate battery sensor measurements against protection thresholds and compute limits."""
        if (
            quality != "GOOD"
            or math.isnan(voltage_v)
            or math.isnan(current_a)
            or math.isnan(soc_pct)
            or math.isnan(temp_c)
        ):
            logger.warning(
                "BMS evaluation received bad quality or non-finite inputs: quality=%s", quality
            )
            return

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
            ccl = self.limits.max_charge_current_a
            dcl = self.limits.max_discharge_current_a

            if temp_c > self.limits.over_temp_warn_c or temp_c < self.limits.under_temp_warn_c:
                ccl *= 0.5
                dcl *= 0.5

            if soc_pct >= 95.0:
                ccl *= max(0.0, (100.0 - soc_pct) / 5.0)
            if soc_pct <= 10.0:
                dcl *= max(0.0, soc_pct / 10.0)

            self.ccl_a = ccl
            self.dcl_a = dcl

        self.cpl_w = self.ccl_a * voltage_v
        self.dpl_w = self.dcl_a * voltage_v

    def _trigger_fault(self, code: str, description: str, timestamp_ns: int) -> None:
        """Helper to trip BMS into fault state with alarm deduplication."""
        self.operating_state = OperatingState.FAULTED
        self.contactors_closed = False
        self.is_available = False
        self.ccl_a = 0.0
        self.dcl_a = 0.0

        if not any(a.code == code and not a.cleared for a in self.active_alarms):
            alarm = AlarmRecord(
                code=code,
                severity=AlarmSeverity.CRITICAL,
                description=description,
                timestamp_ns=timestamp_ns,
                source_id=self.equipment_id,
            )
            self.active_alarms.append(alarm)

    def clear_faults(self, current_temp_c: float = 25.0, current_voltage_v: float = 1000.0) -> bool:
        """Clear active BMS faults if triggering fault condition is no longer active.

        Returns:
            True if faults cleared successfully, False if fault condition remains active.
        """
        if (
            current_temp_c >= self.limits.over_temp_fault_c
            or current_temp_c <= self.limits.under_temp_fault_c
        ):
            logger.warning("BMS clear_faults rejected: temperature fault condition still active.")
            return False

        if current_voltage_v >= self.limits.over_voltage_fault_v or (
            current_voltage_v <= self.limits.under_voltage_fault_v and current_voltage_v > 0.0
        ):
            logger.warning("BMS clear_faults rejected: voltage fault condition still active.")
            return False

        for a in self.active_alarms:
            a.cleared = True
        self.operating_state = OperatingState.STANDBY
        self.is_available = True
        self.interlock_ok = True
        return True

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
                "active_warnings": TelemetryPoint(
                    value=float(len(self.active_warnings)),
                    unit="count",
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

    def reset_to_initial_conditions(self) -> None:
        """Reset BMS protection and state to its configured initial conditions."""
        self.operating_state = OperatingState.STANDBY
        self.contactors_closed = False
        self.is_available = True
        self.interlock_ok = True
        self.ccl_a = self.limits.max_charge_current_a
        self.dcl_a = self.limits.max_discharge_current_a
        self.cpl_w = self.limits.max_charge_current_a * 1000.0
        self.dpl_w = self.limits.max_discharge_current_a * 1000.0
        self.active_warnings.clear()
        self.active_alarms.clear()
        self.last_step_timestamp_ns = 0

    def restore_state_snapshot(self, state: UniversalEquipmentState) -> None:
        """Restore BMS protection and state from a universal equipment state snapshot.

        The dynamic limits (CCL/DCL/CPL/DPL) are restored from the measurements
        captured when the snapshot was taken.
        """
        self.last_step_timestamp_ns = state.timestamp_ns
        self.operating_state = state.operating_state
        self.is_available = state.is_available
        self.ccl_a = _restore_measurement(
            state.measurements, "ccl_a", self.limits.max_charge_current_a
        )
        self.dcl_a = _restore_measurement(
            state.measurements, "dcl_a", self.limits.max_discharge_current_a
        )
        self.cpl_w = _restore_measurement(
            state.measurements, "cpl_w", self.limits.max_charge_current_a * 1000.0
        )
        self.dpl_w = _restore_measurement(
            state.measurements, "dpl_w", self.limits.max_discharge_current_a * 1000.0
        )
        # Active warnings are recomputed live by evaluate_protection, they are
        # not durable state; alarms and limits are restored verbatim.
        self.active_warnings = []
        self.active_alarms = list(state.alarms)
