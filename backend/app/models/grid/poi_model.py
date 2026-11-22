"""Point of Interconnection (POI) Metering and Limit Detection Model.

DOCUMENTED SIGN CONVENTION:
  +P (Positive Active Power) = EXPORTING to AC Grid (Plant delivering power)
  -P (Negative Active Power) = IMPORTING from AC Grid (Plant absorbing power)
  Flow Direction: EXPORTING (+P), IMPORTING (-P), ZERO (P == 0)
"""

import math
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from backend.app.equipment.models import (
    AlarmRecord,
    AlarmSeverity,
    EquipmentMetadata,
    EquipmentType,
    OperatingState,
    TelemetryPoint,
    UniversalEquipmentState,
)
from backend.app.simulation.exceptions import InvalidTimeStepError


class FlowDirection(StrEnum):
    """Energy flow direction indicator at POI."""

    EXPORTING = "EXPORTING"
    IMPORTING = "IMPORTING"
    ZERO = "ZERO"


def _restore_measurement_value(
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


def _direction_of_power(active_power_w: float) -> FlowDirection:
    """Restore the POI flow direction for a restored active power value."""
    if active_power_w > 0.001:
        return FlowDirection.EXPORTING
    if active_power_w < -0.001:
        return FlowDirection.IMPORTING
    return FlowDirection.ZERO


class POIConfigModel(BaseModel):
    """Configuration schema for Point of Interconnection (POI)."""

    nominal_voltage_v: float = Field(default=13800.0, description="Nominal POI voltage in V")
    nominal_frequency_hz: float = Field(default=50.0, description="Nominal POI frequency in Hz")
    max_export_power_w: float = Field(
        default=50_000_000.0, description="Maximum allowed export power limit (+W = +50 MW)"
    )
    max_import_power_w: float = Field(
        default=50_000_000.0, description="Maximum allowed import power limit (-W = 50 MW)"
    )
    voltage_high_limit_v: float | None = Field(default=None)
    voltage_low_limit_v: float | None = Field(default=None)
    frequency_high_limit_hz: float | None = Field(default=None)
    frequency_low_limit_hz: float | None = Field(default=None)

    @field_validator("nominal_voltage_v", "max_export_power_w", "max_import_power_w")
    @classmethod
    def validate_positive(cls, v: float) -> float:
        if v <= 0.0 or math.isnan(v) or math.isinf(v):
            raise ValueError(f"Value must be strictly positive (> 0), got: {v}")
        return v

    def get_effective_limits(self) -> tuple[float, float, float, float]:
        """Return (v_high, v_low, f_high, f_low) configured or derived from nominals."""
        v_high = (
            self.voltage_high_limit_v
            if self.voltage_high_limit_v is not None
            else self.nominal_voltage_v * 1.05
        )
        v_low = (
            self.voltage_low_limit_v
            if self.voltage_low_limit_v is not None
            else self.nominal_voltage_v * 0.95
        )
        f_high = (
            self.frequency_high_limit_hz
            if self.frequency_high_limit_hz is not None
            else self.nominal_frequency_hz + 0.5
        )
        f_low = (
            self.frequency_low_limit_hz
            if self.frequency_low_limit_hz is not None
            else self.nominal_frequency_hz - 0.5
        )
        return (v_high, v_low, f_high, f_low)


class POIModel:
    """Point of Interconnection (POI) Metering and Limit Monitoring Model."""

    def __init__(
        self,
        equipment_id: str = "POI_METER_01",
        config: POIConfigModel | None = None,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.equipment_type: EquipmentType = EquipmentType.METER
        self.config: POIConfigModel = config if config is not None else POIConfigModel()

        self.active_power_w: float = 0.0
        self.reactive_power_var: float = 0.0
        self.apparent_power_va: float = 0.0
        self.voltage_v: float = self.config.nominal_voltage_v
        self.current_a: float = 0.0
        self.frequency_hz: float = self.config.nominal_frequency_hz
        self.power_factor: float = 1.0
        self.flow_direction: FlowDirection = FlowDirection.ZERO

        self.operating_state: OperatingState = OperatingState.RUNNING
        self.is_available: bool = True
        self.active_alarms: list[AlarmRecord] = []
        self.last_step_timestamp_ns: int = 0

    def step(
        self,
        net_p_w: float,
        net_q_var: float,
        voltage_v: float,
        frequency_hz: float,
        delta_t_s: float,
        timestamp_ns: int = 0,
    ) -> None:
        """Execute POI metering step and monitor POI limits."""
        if delta_t_s <= 0.0 or math.isnan(delta_t_s) or math.isinf(delta_t_s):
            raise InvalidTimeStepError(
                f"Simulation delta_t_s must be strictly positive and finite, got: {delta_t_s}"
            )

        self.last_step_timestamp_ns = timestamp_ns
        self.active_alarms.clear()

        self.active_power_w = net_p_w
        self.reactive_power_var = net_q_var
        self.voltage_v = max(1.0, voltage_v)
        self.frequency_hz = frequency_hz

        if net_p_w > 0.001:
            self.flow_direction = FlowDirection.EXPORTING
        elif net_p_w < -0.001:
            self.flow_direction = FlowDirection.IMPORTING
        else:
            self.flow_direction = FlowDirection.ZERO

        self.apparent_power_va = math.sqrt(net_p_w**2 + net_q_var**2)
        self.current_a = self.apparent_power_va / (math.sqrt(3.0) * self.voltage_v)

        if self.apparent_power_va > 0.0:
            self.power_factor = abs(net_p_w) / self.apparent_power_va
        else:
            self.power_factor = 1.0

        v_high, v_low, f_high, f_low = self.config.get_effective_limits()

        if net_p_w > self.config.max_export_power_w:
            msg = (
                f"Export power ({net_p_w / 1e6:.2f} MW) exceeded "
                f"limit ({self.config.max_export_power_w / 1e6:.2f} MW)"
            )
            self._raise_alarm("POI_EXPORT_LIMIT_EXCEEDED", msg)

        if net_p_w < -self.config.max_import_power_w:
            msg = (
                f"Import power ({abs(net_p_w) / 1e6:.2f} MW) exceeded "
                f"limit ({self.config.max_import_power_w / 1e6:.2f} MW)"
            )
            self._raise_alarm("POI_IMPORT_LIMIT_EXCEEDED", msg)

        if voltage_v > v_high:
            msg = f"POI voltage ({voltage_v:.1f} V) exceeded high limit ({v_high:.1f} V)"
            self._raise_alarm("POI_OVER_VOLTAGE", msg)
        elif voltage_v < v_low and voltage_v > 0.0:
            msg = f"POI voltage ({voltage_v:.1f} V) fell below low limit ({v_low:.1f} V)"
            self._raise_alarm("POI_UNDER_VOLTAGE", msg)

        if frequency_hz > f_high:
            msg = f"POI frequency ({frequency_hz:.2f} Hz) exceeded high limit ({f_high:.2f} Hz)"
            self._raise_alarm("POI_OVER_FREQ", msg)
        elif frequency_hz < f_low and frequency_hz > 0.0:
            msg = f"POI frequency ({frequency_hz:.2f} Hz) fell below low limit ({f_low:.2f} Hz)"
            self._raise_alarm("POI_UNDER_FREQ", msg)

    def _raise_alarm(self, code: str, description: str) -> None:
        """Helper to append POI limit alarm record with deduplication."""
        if not any(a.code == code and not a.cleared for a in self.active_alarms):
            alarm = AlarmRecord(
                code=code,
                severity=AlarmSeverity.WARNING,
                description=description,
                timestamp_ns=self.last_step_timestamp_ns,
                source_id=self.equipment_id,
            )
            self.active_alarms.append(alarm)

    def get_state(self) -> UniversalEquipmentState:
        """Return universal equipment state snapshot."""
        t_ns = self.last_step_timestamp_ns
        eq_id = self.equipment_id
        return UniversalEquipmentState(
            equipment_id=eq_id,
            equipment_type=self.equipment_type,
            metadata=EquipmentMetadata(
                manufacturer="Generic BESS", model_name="POI Boundary Meter V1"
            ),
            operating_state=self.operating_state,
            is_available=self.is_available,
            timestamp_ns=t_ns,
            measurements={
                "active_power_w": TelemetryPoint(
                    value=self.active_power_w, unit="W", timestamp_ns=t_ns, source_id=eq_id
                ),
                "reactive_power_var": TelemetryPoint(
                    value=self.reactive_power_var, unit="VAR", timestamp_ns=t_ns, source_id=eq_id
                ),
                "voltage_v": TelemetryPoint(
                    value=self.voltage_v, unit="V", timestamp_ns=t_ns, source_id=eq_id
                ),
                "current_a": TelemetryPoint(
                    value=self.current_a, unit="A", timestamp_ns=t_ns, source_id=eq_id
                ),
                "frequency_hz": TelemetryPoint(
                    value=self.frequency_hz, unit="Hz", timestamp_ns=t_ns, source_id=eq_id
                ),
                "power_factor": TelemetryPoint(
                    value=self.power_factor, unit="ratio", timestamp_ns=t_ns, source_id=eq_id
                ),
            },
            active_limits={
                "max_export_power_w": self.config.max_export_power_w,
                "max_import_power_w": self.config.max_import_power_w,
            },
            alarms=[a for a in self.active_alarms if not a.cleared],
        )

    def restore_state_snapshot(self, state: UniversalEquipmentState) -> None:
        """Restore POI physical model state from a universal equipment state snapshot.

        The measured values and alarms are restored verbatim so that an exact
        continuation from the restored point is possible.
        """
        self.last_step_timestamp_ns = state.timestamp_ns
        self.operating_state = state.operating_state
        self.is_available = state.is_available
        self.active_power_w = _restore_measurement_value(state.measurements, "active_power_w", 0.0)
        self.reactive_power_var = _restore_measurement_value(
            state.measurements, "reactive_power_var", 0.0
        )
        self.voltage_v = _restore_measurement_value(
            state.measurements, "voltage_v", self.config.nominal_voltage_v
        )
        self.current_a = _restore_measurement_value(state.measurements, "current_a", 0.0)
        self.frequency_hz = _restore_measurement_value(
            state.measurements, "frequency_hz", self.config.nominal_frequency_hz
        )
        self.power_factor = _restore_measurement_value(state.measurements, "power_factor", 1.0)
        self.flow_direction = _direction_of_power(self.active_power_w)
        self.active_alarms = list(state.alarms)

    def reset_to_initial_conditions(self) -> None:
        """Reset the POI metering model to its configured initial conditions."""
        self.active_power_w = 0.0
        self.reactive_power_var = 0.0
        self.apparent_power_va = 0.0
        self.voltage_v = self.config.nominal_voltage_v
        self.current_a = 0.0
        self.frequency_hz = self.config.nominal_frequency_hz
        self.power_factor = 1.0
        self.flow_direction = FlowDirection.ZERO
        self.operating_state = OperatingState.RUNNING
        self.is_available = True
        self.active_alarms = []
        self.last_step_timestamp_ns = 0
