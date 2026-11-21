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


class POIConfigModel(BaseModel):
    """Configuration schema for Point of Interconnection (POI)."""

    nominal_voltage_v: float = Field(default=13800.0, description="Nominal POI voltage in V")
    max_export_power_w: float = Field(
        default=50_000_000.0, description="Maximum allowed export power limit (+W = +50 MW)"
    )
    max_import_power_w: float = Field(
        default=50_000_000.0, description="Maximum allowed import power limit (-W = 50 MW)"
    )
    voltage_high_limit_v: float = Field(
        default=14490.0, description="High voltage limit (+5% = 14.49 kV)"
    )
    voltage_low_limit_v: float = Field(
        default=13110.0, description="Low voltage limit (-5% = 13.11 kV)"
    )
    frequency_high_limit_hz: float = Field(
        default=60.5, description="High frequency limit (60.5 Hz)"
    )
    frequency_low_limit_hz: float = Field(default=59.5, description="Low frequency limit (59.5 Hz)")

    @field_validator("nominal_voltage_v", "max_export_power_w", "max_import_power_w")
    @classmethod
    def validate_positive(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"Value must be strictly positive (> 0), got: {v}")
        return v


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
        self.frequency_hz: float = 60.0
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
        if delta_t_s <= 0.0:
            raise InvalidTimeStepError(
                f"Simulation delta_t_s must be strictly positive (> 0.0), got: {delta_t_s}"
            )

        self.last_step_timestamp_ns = timestamp_ns
        self.active_alarms.clear()

        self.active_power_w = net_p_w
        self.reactive_power_var = net_q_var
        self.voltage_v = max(1.0, voltage_v)
        self.frequency_hz = frequency_hz

        # Determine Flow Direction
        if net_p_w > 0.001:
            self.flow_direction = FlowDirection.EXPORTING
        elif net_p_w < -0.001:
            self.flow_direction = FlowDirection.IMPORTING
        else:
            self.flow_direction = FlowDirection.ZERO

        # Apparent Power S = sqrt(P^2 + Q^2)
        self.apparent_power_va = math.sqrt(net_p_w**2 + net_q_var**2)

        # 3-Phase Line Current I = S / (sqrt(3) * V)
        self.current_a = self.apparent_power_va / (math.sqrt(3.0) * self.voltage_v)

        # Power Factor PF = |P| / S
        if self.apparent_power_va > 0.0:
            self.power_factor = abs(net_p_w) / self.apparent_power_va
        else:
            self.power_factor = 1.0

        # Limit Exceeded Warning/Alarm Detection
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

        if voltage_v > self.config.voltage_high_limit_v:
            msg = (
                f"POI voltage ({voltage_v:.1f} V) exceeded "
                f"high limit ({self.config.voltage_high_limit_v:.1f} V)"
            )
            self._raise_alarm("POI_OVER_VOLTAGE", msg)
        elif voltage_v < self.config.voltage_low_limit_v and voltage_v > 0.0:
            msg = (
                f"POI voltage ({voltage_v:.1f} V) fell "
                f"below low limit ({self.config.voltage_low_limit_v:.1f} V)"
            )
            self._raise_alarm("POI_UNDER_VOLTAGE", msg)

        if frequency_hz > self.config.frequency_high_limit_hz:
            msg = (
                f"POI frequency ({frequency_hz:.2f} Hz) exceeded "
                f"high limit ({self.config.frequency_high_limit_hz:.2f} Hz)"
            )
            self._raise_alarm("POI_OVER_FREQ", msg)
        elif frequency_hz < self.config.frequency_low_limit_hz and frequency_hz > 0.0:
            msg = (
                f"POI frequency ({frequency_hz:.2f} Hz) fell "
                f"below low limit ({self.config.frequency_low_limit_hz:.2f} Hz)"
            )
            self._raise_alarm("POI_UNDER_FREQ", msg)

    def _raise_alarm(self, code: str, description: str) -> None:
        """Helper to append POI limit alarm record."""
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
