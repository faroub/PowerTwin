"""Generic Step-Up Transformer Model."""

import math

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


class TransformerConfigModel(BaseModel):
    """Configuration schema for Step-Up Transformer."""

    rating_va: float = Field(
        default=10_000_000.0, description="Nominal apparent power rating (10 MVA)"
    )
    primary_voltage_v: float = Field(default=690.0, description="Primary low-voltage side (690V)")
    secondary_voltage_v: float = Field(
        default=13800.0, description="Secondary medium-voltage side (13.8kV)"
    )
    core_loss_pct: float = Field(default=0.002, description="No-load / Core loss fraction (0.2%)")
    copper_loss_pct: float = Field(
        default=0.010, description="Full-load / Copper loss fraction (1.0%)"
    )
    over_temp_fault_c: float = Field(default=110.0, description="Winding temperature fault cutoff")
    thermal_mass_j_per_c: float = Field(default=10_000_000.0, description="Thermal mass in J/degC")

    @field_validator("rating_va", "primary_voltage_v", "secondary_voltage_v")
    @classmethod
    def validate_positive(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"Value must be strictly positive (> 0), got: {v}")
        return v

    @property
    def turns_ratio(self) -> float:
        """Return turns ratio N = V_sec / V_pri."""
        return self.secondary_voltage_v / self.primary_voltage_v


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


class GenericTransformerModel:
    """Configurable Step-Up Transformer Model with core and copper loss calculations."""

    def __init__(
        self,
        equipment_id: str = "XFRM_01",
        config: TransformerConfigModel | None = None,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.equipment_type: EquipmentType = EquipmentType.TRANSFORMER
        self.config: TransformerConfigModel = (
            config if config is not None else TransformerConfigModel()
        )

        self.primary_power_w: float = 0.0
        self.primary_power_var: float = 0.0
        self.secondary_power_w: float = 0.0
        self.secondary_power_var: float = 0.0

        self.primary_voltage_v: float = self.config.primary_voltage_v
        self.secondary_voltage_v: float = self.config.secondary_voltage_v

        self.winding_temp_c: float = 25.0
        self.operating_state: OperatingState = OperatingState.STANDBY
        self.is_available: bool = True
        self.active_alarms: list[AlarmRecord] = []
        self.last_step_timestamp_ns: int = 0

    def step(
        self,
        primary_power_w: float,
        primary_power_var: float,
        primary_voltage_v: float,
        delta_t_s: float,
        timestamp_ns: int = 0,
    ) -> None:
        """Execute transformer physics step for time step delta_t_s."""
        if delta_t_s <= 0.0:
            raise InvalidTimeStepError(
                f"Simulation delta_t_s must be strictly positive (> 0.0), got: {delta_t_s}"
            )

        self.last_step_timestamp_ns = timestamp_ns
        self.primary_power_w = primary_power_w
        self.primary_power_var = primary_power_var
        self.primary_voltage_v = primary_voltage_v
        self.secondary_voltage_v = primary_voltage_v * self.config.turns_ratio

        if not self.is_available or self.operating_state == OperatingState.FAULTED:
            self.secondary_power_w = 0.0
            self.secondary_power_var = 0.0
            return

        # Calculate apparent power load factor: k = S_actual / S_rated
        s_actual = math.sqrt(primary_power_w**2 + primary_power_var**2)
        load_factor = min(1.5, s_actual / max(1.0, self.config.rating_va))

        # Core loss P_core (constant when energized)
        p_core = self.config.core_loss_pct * self.config.rating_va

        # Copper loss P_copper = P_copper_rated * (k)^2
        p_copper = self.config.copper_loss_pct * self.config.rating_va * (load_factor**2)

        total_loss_w = p_core + p_copper

        # Secondary output power = Primary power - losses
        if primary_power_w >= 0.0:
            self.secondary_power_w = max(0.0, primary_power_w - total_loss_w)
        else:
            self.secondary_power_w = primary_power_w - total_loss_w

        self.secondary_power_var = primary_power_var

        # Thermal winding update
        heat_joules = total_loss_w * delta_t_s
        temp_rise = heat_joules / self.config.thermal_mass_j_per_c
        cooling = (self.winding_temp_c - 25.0) * (0.005 * delta_t_s)
        self.winding_temp_c += temp_rise - cooling

        if self.winding_temp_c >= self.config.over_temp_fault_c:
            self.operating_state = OperatingState.FAULTED
            self.is_available = False
            msg = (
                f"Winding temp ({self.winding_temp_c:.1f} C) exceeded "
                f"cutoff ({self.config.over_temp_fault_c:.1f} C)"
            )
            alarm = AlarmRecord(
                code="XFRM_OVER_TEMP_FAULT",
                severity=AlarmSeverity.CRITICAL,
                description=msg,
                timestamp_ns=timestamp_ns,
                source_id=self.equipment_id,
            )
            self.active_alarms.append(alarm)
        elif s_actual > 0.0:
            self.operating_state = OperatingState.RUNNING
        else:
            self.operating_state = OperatingState.STANDBY

    def get_state(self) -> UniversalEquipmentState:
        """Return universal equipment state snapshot."""
        s_actual = math.sqrt(self.primary_power_w**2 + self.primary_power_var**2)
        return UniversalEquipmentState(
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            metadata=EquipmentMetadata(
                manufacturer="Generic BESS", model_name="Step-Up Transformer 10MVA"
            ),
            operating_state=self.operating_state,
            is_available=self.is_available,
            timestamp_ns=self.last_step_timestamp_ns,
            measurements={
                "primary_power_w": TelemetryPoint(
                    value=self.primary_power_w,
                    unit="W",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "primary_power_var": TelemetryPoint(
                    value=self.primary_power_var,
                    unit="VAR",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "secondary_power_w": TelemetryPoint(
                    value=self.secondary_power_w,
                    unit="W",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "secondary_power_var": TelemetryPoint(
                    value=self.secondary_power_var,
                    unit="VAR",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "primary_voltage_v": TelemetryPoint(
                    value=self.primary_voltage_v,
                    unit="V",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "secondary_voltage_v": TelemetryPoint(
                    value=self.secondary_voltage_v,
                    unit="V",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "apparent_power_va": TelemetryPoint(
                    value=s_actual,
                    unit="VA",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "winding_temp_c": TelemetryPoint(
                    value=self.winding_temp_c,
                    unit="degC",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
            },
            active_limits={"rating_va": self.config.rating_va},
            alarms=[a for a in self.active_alarms if not a.cleared],
        )

    def restore_state_snapshot(self, state: UniversalEquipmentState) -> None:
        """Restore transformer physical and thermal state from a snapshot."""
        self.last_step_timestamp_ns = state.timestamp_ns
        self.operating_state = state.operating_state
        self.is_available = state.is_available
        self.primary_power_w = _restore_measurement(state.measurements, "primary_power_w", 0.0)
        self.primary_power_var = _restore_measurement(state.measurements, "primary_power_var", 0.0)
        self.secondary_power_w = _restore_measurement(state.measurements, "secondary_power_w", 0.0)
        self.secondary_power_var = _restore_measurement(
            state.measurements, "secondary_power_var", 0.0
        )
        self.primary_voltage_v = _restore_measurement(
            state.measurements, "primary_voltage_v", self.config.primary_voltage_v
        )
        self.secondary_voltage_v = _restore_measurement(
            state.measurements, "secondary_voltage_v", self.config.secondary_voltage_v
        )
        self.winding_temp_c = _restore_measurement(state.measurements, "winding_temp_c", 25.0)
        self.active_alarms = list(state.alarms)

    def reset_to_initial_conditions(self) -> None:
        """Reset transformer thermal and control state to its configured initial conditions."""
        self.primary_power_w = 0.0
        self.primary_power_var = 0.0
        self.secondary_power_w = 0.0
        self.secondary_power_var = 0.0
        self.primary_voltage_v = self.config.primary_voltage_v
        self.secondary_voltage_v = self.config.secondary_voltage_v
        self.winding_temp_c = 25.0
        self.operating_state = OperatingState.STANDBY
        self.is_available = True
        self.active_alarms.clear()
        self.last_step_timestamp_ns = 0
