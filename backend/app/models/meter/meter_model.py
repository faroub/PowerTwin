"""Generic Revenue-Grade Meter Model.

DOCUMENTED MODEL LIMITATION:
  This meter model calculates RMS steady-state phasor power, voltage, current, and energy registers.
  It does NOT model electromagnetic-transient (EMT) switching waveforms or high-frequency harmonics.
"""

import math

from pydantic import BaseModel, Field, field_validator

from backend.app.equipment.models import (
    EquipmentMetadata,
    EquipmentType,
    OperatingState,
    QualityFlag,
    TelemetryPoint,
    UniversalEquipmentState,
)
from backend.app.simulation.exceptions import InvalidTimeStepError


class MeterConfigModel(BaseModel):
    """Configuration schema for Meter Model."""

    nominal_voltage_v: float = Field(default=13800.0, description="Nominal AC line voltage")
    accuracy_class_pct: float = Field(
        default=0.2, description="Meter accuracy class percentage (0.2%)"
    )

    @field_validator("nominal_voltage_v")
    @classmethod
    def validate_positive(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"Value must be strictly positive (> 0), got: {v}")
        return v


class GenericMeterModel:
    """Configurable RMS Revenue-Grade Power Meter Model."""

    def __init__(
        self,
        equipment_id: str = "METER_POI_01",
        config: MeterConfigModel | None = None,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.equipment_type: EquipmentType = EquipmentType.METER
        self.config: MeterConfigModel = config if config is not None else MeterConfigModel()

        self.active_power_w: float = 0.0
        self.reactive_power_var: float = 0.0
        self.apparent_power_va: float = 0.0
        self.voltage_v: float = self.config.nominal_voltage_v
        self.current_a: float = 0.0
        self.power_factor: float = 1.0
        self.frequency_hz: float = 60.0

        # Accumulated Energy Registers (Wh & VARh)
        self.energy_export_wh: float = 0.0  # Delivered to grid (+P)
        self.energy_import_wh: float = 0.0  # Absorbed from grid (-P)
        self.reactive_export_varh: float = 0.0
        self.reactive_import_varh: float = 0.0

        self.quality: QualityFlag = QualityFlag.GOOD
        self.operating_state: OperatingState = OperatingState.RUNNING
        self.is_available: bool = True
        self.last_step_timestamp_ns: int = 0

    def step(
        self,
        active_power_w: float,
        reactive_power_var: float,
        voltage_v: float,
        frequency_hz: float,
        delta_t_s: float,
        timestamp_ns: int = 0,
        quality: QualityFlag = QualityFlag.GOOD,
    ) -> None:
        """Execute meter measurement step and update accumulated energy registers."""
        if delta_t_s <= 0.0:
            raise InvalidTimeStepError(
                f"Simulation delta_t_s must be strictly positive (> 0.0), got: {delta_t_s}"
            )

        self.last_step_timestamp_ns = timestamp_ns
        self.quality = quality
        self.active_power_w = active_power_w
        self.reactive_power_var = reactive_power_var
        self.voltage_v = max(1.0, voltage_v)
        self.frequency_hz = frequency_hz

        # Apparent power S = sqrt(P^2 + Q^2)
        self.apparent_power_va = math.sqrt(active_power_w**2 + reactive_power_var**2)

        # 3-Phase Line Current I = S / (sqrt(3) * V_line)
        self.current_a = self.apparent_power_va / (math.sqrt(3.0) * self.voltage_v)

        # Power factor PF = P / S
        if self.apparent_power_va > 0.0:
            self.power_factor = abs(active_power_w) / self.apparent_power_va
        else:
            self.power_factor = 1.0

        # Accumulate Energy Registers
        dt_hours = delta_t_s / 3600.0
        if active_power_w >= 0.0:
            self.energy_export_wh += active_power_w * dt_hours
        else:
            self.energy_import_wh += abs(active_power_w) * dt_hours

        if reactive_power_var >= 0.0:
            self.reactive_export_varh += reactive_power_var * dt_hours
        else:
            self.reactive_import_varh += abs(reactive_power_var) * dt_hours

    def reset_registers(self) -> None:
        """Reset accumulated energy registers."""
        self.energy_export_wh = 0.0
        self.energy_import_wh = 0.0
        self.reactive_export_varh = 0.0
        self.reactive_import_varh = 0.0

    def get_state(self) -> UniversalEquipmentState:
        """Return universal equipment state snapshot."""
        return UniversalEquipmentState(
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            metadata=EquipmentMetadata(
                manufacturer="Generic BESS", model_name="POI Revenue Meter Class 0.2"
            ),
            operating_state=self.operating_state,
            is_available=self.is_available,
            timestamp_ns=self.last_step_timestamp_ns,
            quality=self.quality,
            measurements={
                "active_power_w": TelemetryPoint(
                    value=self.active_power_w,
                    unit="W",
                    timestamp_ns=self.last_step_timestamp_ns,
                    quality=self.quality,
                    source_id=self.equipment_id,
                ),
                "reactive_power_var": TelemetryPoint(
                    value=self.reactive_power_var,
                    unit="VAR",
                    timestamp_ns=self.last_step_timestamp_ns,
                    quality=self.quality,
                    source_id=self.equipment_id,
                ),
                "apparent_power_va": TelemetryPoint(
                    value=self.apparent_power_va,
                    unit="VA",
                    timestamp_ns=self.last_step_timestamp_ns,
                    quality=self.quality,
                    source_id=self.equipment_id,
                ),
                "voltage_v": TelemetryPoint(
                    value=self.voltage_v,
                    unit="V",
                    timestamp_ns=self.last_step_timestamp_ns,
                    quality=self.quality,
                    source_id=self.equipment_id,
                ),
                "current_a": TelemetryPoint(
                    value=self.current_a,
                    unit="A",
                    timestamp_ns=self.last_step_timestamp_ns,
                    quality=self.quality,
                    source_id=self.equipment_id,
                ),
                "frequency_hz": TelemetryPoint(
                    value=self.frequency_hz,
                    unit="Hz",
                    timestamp_ns=self.last_step_timestamp_ns,
                    quality=self.quality,
                    source_id=self.equipment_id,
                ),
                "power_factor": TelemetryPoint(
                    value=self.power_factor,
                    unit="ratio",
                    timestamp_ns=self.last_step_timestamp_ns,
                    quality=self.quality,
                    source_id=self.equipment_id,
                ),
                "energy_export_wh": TelemetryPoint(
                    value=self.energy_export_wh,
                    unit="Wh",
                    timestamp_ns=self.last_step_timestamp_ns,
                    quality=self.quality,
                    source_id=self.equipment_id,
                ),
                "energy_import_wh": TelemetryPoint(
                    value=self.energy_import_wh,
                    unit="Wh",
                    timestamp_ns=self.last_step_timestamp_ns,
                    quality=self.quality,
                    source_id=self.equipment_id,
                ),
            },
        )
