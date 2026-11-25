"""Generic Configurable Grid Simulation Model.

Models synthetic grid voltage, grid frequency, grid impedance (R + jX),
short-circuit strength (SCR/MVA), and configurable grid disturbances (steps, ramps, disconnections).
"""

import math
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from backend.app.equipment.models import (
    EquipmentMetadata,
    EquipmentType,
    OperatingState,
    TelemetryPoint,
    UniversalEquipmentState,
)
from backend.app.simulation.exceptions import InvalidTimeStepError


def _restore_measurement(
    measurements: dict[str, "TelemetryPoint"], name: str, default: float
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


class GridOperatingState(StrEnum):
    """Grid interconnection operating states."""

    GRID_CONNECTED = "GRID_CONNECTED"
    ISLANDED = "ISLANDED"
    FAULTED = "FAULTED"
    DISCONNECTED = "DISCONNECTED"


class DisturbanceType(StrEnum):
    """Grid disturbance event types."""

    FREQUENCY_STEP = "FREQUENCY_STEP"
    FREQUENCY_RAMP = "FREQUENCY_RAMP"
    VOLTAGE_STEP = "VOLTAGE_STEP"
    VOLTAGE_RAMP = "VOLTAGE_RAMP"
    GRID_DISCONNECTION = "GRID_DISCONNECTION"
    GRID_RECONNECTION = "GRID_RECONNECTION"


class GridDisturbance(BaseModel):
    """Grid disturbance schedule item."""

    disturbance_type: DisturbanceType
    start_time_ns: int = Field(default=0, description="Simulation tick start timestamp in ns")
    duration_s: float = Field(default=0.0, description="Duration in seconds (for ramps)")
    magnitude: float = Field(
        default=0.0, description="Magnitude (Delta f in Hz, Delta V in V, or ramp rate)"
    )


class GridConfigModel(BaseModel):
    """Configuration schema for Synthetic Grid Model."""

    nominal_frequency_hz: float = Field(default=60.0, description="Nominal grid frequency in Hz")
    nominal_voltage_v: float = Field(default=13800.0, description="Nominal POI voltage in V")
    grid_resistance_ohm: float = Field(default=0.05, description="Grid resistance R in Ohms")
    grid_reactance_ohm: float = Field(default=0.20, description="Grid reactance X in Ohms")
    short_circuit_mva: float = Field(default=500.0, description="Short-circuit capacity in MVA")

    @field_validator("nominal_frequency_hz", "nominal_voltage_v", "short_circuit_mva")
    @classmethod
    def validate_positive(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"Value must be strictly positive (> 0), got: {v}")
        return v


class GenericGridModel:
    """Configurable Grid Simulation Model with disturbance injection."""

    def __init__(
        self,
        equipment_id: str = "GRID_MODEL_01",
        config: GridConfigModel | None = None,
        is_illustrative: bool = True,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.equipment_type: EquipmentType = EquipmentType.GRID_MODEL
        self.is_illustrative: bool = is_illustrative
        self.config: GridConfigModel = config if config is not None else GridConfigModel()

        self.frequency_hz: float = self.config.nominal_frequency_hz
        self.voltage_v: float = self.config.nominal_voltage_v
        self.grid_state: GridOperatingState = GridOperatingState.GRID_CONNECTED
        self.is_available: bool = True
        self.is_islanding: bool = False

        self._active_disturbances: list[GridDisturbance] = []
        self.last_step_timestamp_ns: int = 0

    def apply_disturbance(self, disturbance: GridDisturbance) -> None:
        """Schedule a grid disturbance event."""
        self._active_disturbances.append(disturbance)

    def disconnect_grid(self) -> None:
        """Disconnect grid into islanded / disconnected state."""
        self.grid_state = GridOperatingState.DISCONNECTED
        self.is_islanding = True

    def reconnect_grid(self) -> None:
        """Reconnect grid back to GRID_CONNECTED state."""
        self.grid_state = GridOperatingState.GRID_CONNECTED
        self.is_islanding = False

    def step(
        self,
        plant_net_p_w: float,
        plant_net_q_var: float,
        delta_t_s: float,
        timestamp_ns: int = 0,
    ) -> tuple[float, float]:
        """Execute grid step, process disturbances, and compute grid voltage & frequency."""
        if delta_t_s <= 0.0:
            raise InvalidTimeStepError(
                f"Simulation delta_t_s must be strictly positive (> 0.0), got: {delta_t_s}"
            )

        self.last_step_timestamp_ns = timestamp_ns

        if self.grid_state in (GridOperatingState.DISCONNECTED, GridOperatingState.ISLANDED):
            self.voltage_v = 0.0
            self.frequency_hz = 0.0
            return (0.0, 0.0)

        target_f = self.config.nominal_frequency_hz
        target_v = self.config.nominal_voltage_v

        for dist in self._active_disturbances:
            if timestamp_ns >= dist.start_time_ns:
                elapsed_ns = timestamp_ns - dist.start_time_ns
                elapsed_s = elapsed_ns / 1_000_000_000.0

                if dist.disturbance_type == DisturbanceType.GRID_DISCONNECTION:
                    self.disconnect_grid()
                    return (0.0, 0.0)

                elif dist.disturbance_type == DisturbanceType.GRID_RECONNECTION:
                    self.reconnect_grid()

                elif dist.disturbance_type == DisturbanceType.FREQUENCY_STEP:
                    target_f += dist.magnitude

                elif dist.disturbance_type == DisturbanceType.FREQUENCY_RAMP:
                    ramp_duration = max(0.001, dist.duration_s)
                    progress = min(1.0, elapsed_s / ramp_duration)
                    target_f += dist.magnitude * progress

                elif dist.disturbance_type == DisturbanceType.VOLTAGE_STEP:
                    target_v += dist.magnitude

                elif dist.disturbance_type == DisturbanceType.VOLTAGE_RAMP:
                    ramp_duration = max(0.001, dist.duration_s)
                    progress = min(1.0, elapsed_s / ramp_duration)
                    target_v += dist.magnitude * progress

        # Grid impedance voltage drop: Delta V ~ (P*R + Q*X) / V_nom
        delta_v_impedance = (
            (plant_net_p_w * self.config.grid_resistance_ohm)
            + (plant_net_q_var * self.config.grid_reactance_ohm)
        ) / max(1.0, target_v)

        self.voltage_v = max(0.0, target_v + delta_v_impedance)
        self.frequency_hz = target_f

        return (self.voltage_v, self.frequency_hz)

    def restore_state_snapshot(self, state: UniversalEquipmentState) -> None:
        """Restore grid model physical state from a universal equipment state snapshot."""
        self.last_step_timestamp_ns = state.timestamp_ns
        self.is_available = state.is_available
        self.voltage_v = _restore_measurement(state.measurements, "voltage_v", 0.0)
        self.frequency_hz = _restore_measurement(
            state.measurements, "frequency_hz", self.config.nominal_frequency_hz
        )
        self.is_islanding = bool(_restore_measurement(state.measurements, "islanding", 0.0) > 0.0)
        if state.operating_state == OperatingState.RUNNING:
            self.grid_state = GridOperatingState.GRID_CONNECTED
        else:
            self.grid_state = GridOperatingState.DISCONNECTED

    def reset_to_initial_conditions(self) -> None:
        """Reset the grid model to its configured initial and connected state."""
        self.voltage_v = self.config.nominal_voltage_v
        self.frequency_hz = self.config.nominal_frequency_hz
        self.grid_state = GridOperatingState.GRID_CONNECTED
        self.is_available = True
        self.is_islanding = False
        self.last_step_timestamp_ns = 0
        self._active_disturbances.clear()

    def get_state(self) -> UniversalEquipmentState:
        """Return universal equipment state snapshot."""
        op_state = (
            OperatingState.RUNNING
            if self.grid_state == GridOperatingState.GRID_CONNECTED
            else OperatingState.OFF
        )
        return UniversalEquipmentState(
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            metadata=EquipmentMetadata(
                manufacturer="Generic BESS",
                model_name="Synthetic Grid Node",
                is_illustrative=self.is_illustrative,
            ),
            operating_state=op_state,
            is_available=self.is_available,
            timestamp_ns=self.last_step_timestamp_ns,
            measurements={
                "frequency_hz": TelemetryPoint(
                    value=self.frequency_hz,
                    unit="Hz",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "voltage_v": TelemetryPoint(
                    value=self.voltage_v,
                    unit="V",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "islanding": TelemetryPoint(
                    value=1.0 if self.is_islanding else 0.0,
                    unit="bool",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
            },
            active_limits={
                "short_circuit_mva": self.config.short_circuit_mva,
            },
        )
