"""Generic PCS (Power Conversion System) Inverter Model.

DOCUMENTED SIGN CONVENTION:
  +P (Positive Active Power) = DISCHARGING into AC grid/plant
  -P (Negative Active Power) = CHARGING from AC grid/plant
  +Q (Positive Reactive Power) = SUPPLYING inductive VARs (Capacitive/Lagging)
  -Q (Negative Reactive Power) = ABSORBING VARs (Inductive/Leading)

FOUR EXPLICIT P & Q VALUES DISTINGUISHED:
  1. Requested P, Q: Target setpoint submitted by PPC/EMS.
  2. Accepted P, Q: Validated setpoint after PQ circle (P^2 + Q^2 <= S_max^2) and DC window limits.
  3. Actual P, Q: Physical AC output generated after applying ramp rate limit and efficiency losses.
  4. Measured P, Q: Telemetry values reported by simulated AC sensors.
"""

import math
from typing import Any

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


class PCSConfigModel(BaseModel):
    """Configuration schema for Generic PCS Model."""

    rated_active_power_w: float = Field(
        default=5_000_000.0, description="Nominal rated active power capacity (+W = Discharge)"
    )
    rated_apparent_power_va: float = Field(
        default=5_500_000.0, description="Max apparent power capability S_max"
    )
    ac_voltage_nominal_v: float = Field(default=690.0, description="Nominal AC terminal voltage")
    dc_voltage_min_v: float = Field(default=800.0, description="Min operating DC voltage")
    dc_voltage_max_v: float = Field(default=1200.0, description="Max operating DC voltage")
    max_ac_current_a: float = Field(default=4600.0, description="Maximum AC current capability")
    ramp_rate_limit_w_per_s: float = Field(
        default=10_000_000.0, description="Max active power ramp rate limit in W/s (10 MW/s)"
    )
    efficiency: float = Field(
        default=0.985, description="Inverter conversion efficiency (0.985 = 98.5%)"
    )
    over_temp_warn_c: float = Field(default=80.0, description="IGBT temp warning threshold")
    over_temp_fault_c: float = Field(default=95.0, description="IGBT temp fault cutoff")
    thermal_mass_j_per_c: float = Field(
        default=500_000.0, description="IGBT heatsink thermal mass in J/degC"
    )

    @field_validator(
        "rated_active_power_w",
        "rated_apparent_power_va",
        "ac_voltage_nominal_v",
        "ramp_rate_limit_w_per_s",
    )
    @classmethod
    def validate_positive(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"Value must be strictly positive (> 0), got: {v}")
        return v

    @field_validator("efficiency")
    @classmethod
    def validate_efficiency(cls, v: float) -> float:
        if v <= 0.0 or v > 1.0:
            raise ValueError(f"Efficiency must be in (0.0, 1.0], got: {v}")
        return v


class PCSCommandModel(BaseModel):
    """Command schema for PCS setpoint dispatch."""

    requested_p_w: float = Field(default=0.0, description="+W = Discharge, -W = Charge")
    requested_q_var: float = Field(default=0.0, description="+VAR = Supply VARs")
    enable_inverter: bool | None = None
    reset_fault: bool = False


class GenericPCSModel:
    """Configurable Inverter PCS Model with P^2 + Q^2 <= S_max^2 capability circle clamping."""

    def __init__(
        self,
        equipment_id: str = "PCS_01",
        config: PCSConfigModel | None = None,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.equipment_type: EquipmentType = EquipmentType.PCS
        self.config: PCSConfigModel = config if config is not None else PCSConfigModel()

        # 1. Requested Setpoints (Input from PPC/EMS)
        self.requested_p_w: float = 0.0
        self.requested_q_var: float = 0.0

        # 2. Accepted Setpoints (After PQ circle & boundary clamping)
        self.accepted_p_w: float = 0.0
        self.accepted_q_var: float = 0.0

        # 3. Actual Physical Output (After ramp limiter & efficiency)
        self.actual_p_w: float = 0.0
        self.actual_q_var: float = 0.0

        # 4. Measured Telemetry Values (With sensor noise)
        self.measured_p_w: float = 0.0
        self.measured_q_var: float = 0.0

        self.igbt_temp_c: float = 25.0
        self.operating_state: OperatingState = OperatingState.STANDBY
        self.is_available: bool = True
        self.active_alarms: list[AlarmRecord] = []
        self.metadata: EquipmentMetadata = EquipmentMetadata(
            manufacturer="Generic BESS", model_name="PCS Inverter 5MW V1"
        )
        self.last_step_timestamp_ns: int = 0

    def process_command(self, cmd: dict[str, Any]) -> bool:
        """Process inbound P & Q command setpoints."""
        try:
            parsed = PCSCommandModel(**cmd)
            if parsed.reset_fault:
                self.clear_faults()

            if parsed.enable_inverter is True and self.is_available:
                self.operating_state = OperatingState.RUNNING
            elif parsed.enable_inverter is False:
                self.operating_state = OperatingState.STANDBY

            self.requested_p_w = parsed.requested_p_w
            self.requested_q_var = parsed.requested_q_var
            return True
        except Exception:
            return False

    def evaluate_pq_capability_circle(
        self, p_req: float, q_req: float, s_max_eff: float
    ) -> tuple[float, float]:
        """Enforce apparent power circle constraint: P^2 + Q^2 <= S_max^2."""
        p_clamped = max(
            -self.config.rated_active_power_w,
            min(self.config.rated_active_power_w, p_req),
        )
        p_accepted = max(-s_max_eff, min(s_max_eff, p_clamped))
        q_headroom_sq = max(0.0, (s_max_eff**2) - (p_accepted**2))
        q_max_avail = math.sqrt(q_headroom_sq)
        q_accepted = max(-q_max_avail, min(q_max_avail, q_req))
        return (p_accepted, q_accepted)

    def step(
        self,
        dc_voltage_v: float,
        ac_grid_voltage_v: float,
        delta_t_s: float,
        timestamp_ns: int = 0,
    ) -> None:
        """Execute physical PCS step for time step delta_t_s."""
        if delta_t_s <= 0.0:
            raise InvalidTimeStepError(
                f"Simulation delta_t_s must be strictly positive (> 0.0), got: {delta_t_s}"
            )

        self.last_step_timestamp_ns = timestamp_ns

        # 1. DC Voltage Operating Range Verification
        if dc_voltage_v > self.config.dc_voltage_max_v:
            msg = (
                f"DC voltage ({dc_voltage_v:.1f} V) exceeded "
                f"max ({self.config.dc_voltage_max_v:.1f} V)"
            )
            self._trigger_fault("DC_OVER_VOLTAGE_FAULT", msg, timestamp_ns)
        elif dc_voltage_v < self.config.dc_voltage_min_v and dc_voltage_v > 0.0:
            msg = (
                f"DC voltage ({dc_voltage_v:.1f} V) fell "
                f"below min ({self.config.dc_voltage_min_v:.1f} V)"
            )
            self._trigger_fault("DC_UNDER_VOLTAGE_FAULT", msg, timestamp_ns)

        # 2. Thermal Derating Interface
        s_max_effective = self.config.rated_apparent_power_va
        if self.igbt_temp_c >= self.config.over_temp_fault_c:
            msg = (
                f"IGBT temp ({self.igbt_temp_c:.1f} C) exceeded "
                f"cutoff ({self.config.over_temp_fault_c:.1f} C)"
            )
            self._trigger_fault("OVER_TEMP_FAULT", msg, timestamp_ns)
        elif self.igbt_temp_c >= self.config.over_temp_warn_c:
            derate_factor = max(
                0.5,
                1.0
                - 0.5
                * (
                    (self.igbt_temp_c - self.config.over_temp_warn_c)
                    / (self.config.over_temp_fault_c - self.config.over_temp_warn_c)
                ),
            )
            s_max_effective *= derate_factor

        if not self.is_available or self.operating_state in (
            OperatingState.OFF,
            OperatingState.FAULTED,
            OperatingState.EMERGENCY_STOP,
        ):
            self.accepted_p_w = 0.0
            self.accepted_q_var = 0.0
            self.actual_p_w = 0.0
            self.actual_q_var = 0.0
            self.measured_p_w = 0.0
            self.measured_q_var = 0.0
            return

        # 3. Evaluate Apparent Power Circle & Accept Setpoints
        p_acc, q_acc = self.evaluate_pq_capability_circle(
            self.requested_p_w, self.requested_q_var, s_max_effective
        )
        self.accepted_p_w = p_acc
        self.accepted_q_var = q_acc

        # 4. Enforce Ramp Rate Limit on Active Power P
        max_delta_p = self.config.ramp_rate_limit_w_per_s * delta_t_s
        p_delta = self.accepted_p_w - self.actual_p_w

        if abs(p_delta) > max_delta_p:
            p_actual_next = self.actual_p_w + math.copysign(max_delta_p, p_delta)
        else:
            p_actual_next = self.accepted_p_w

        if p_actual_next > 0.0:
            self.actual_p_w = p_actual_next * self.config.efficiency
            p_losses = p_actual_next * (1.0 - self.config.efficiency)
        elif p_actual_next < 0.0:
            self.actual_p_w = p_actual_next / self.config.efficiency
            p_losses = abs(p_actual_next) * (1.0 - self.config.efficiency)
        else:
            self.actual_p_w = 0.0
            p_losses = 0.0

        self.actual_q_var = self.accepted_q_var
        self.measured_p_w = self.actual_p_w
        self.measured_q_var = self.actual_q_var

        # 6. IGBT Heatsink Thermal Model Update
        heat_joules = p_losses * delta_t_s
        temp_rise = heat_joules / self.config.thermal_mass_j_per_c
        cooling = (self.igbt_temp_c - 25.0) * (0.02 * delta_t_s)
        self.igbt_temp_c += temp_rise - cooling

    def _trigger_fault(self, code: str, description: str, timestamp_ns: int) -> None:
        """Helper to trip PCS into fault state."""
        self.operating_state = OperatingState.FAULTED
        self.is_available = False
        self.accepted_p_w = 0.0
        self.accepted_q_var = 0.0
        self.actual_p_w = 0.0
        self.actual_q_var = 0.0

        alarm = AlarmRecord(
            code=code,
            severity=AlarmSeverity.CRITICAL,
            description=description,
            timestamp_ns=timestamp_ns,
            source_id=self.equipment_id,
        )
        self.active_alarms.append(alarm)

    def clear_faults(self) -> None:
        """Clear active PCS faults."""
        for a in self.active_alarms:
            a.cleared = True
        self.operating_state = OperatingState.STANDBY
        self.is_available = True

    def get_state(self) -> UniversalEquipmentState:
        """Return universal equipment state snapshot."""
        return UniversalEquipmentState(
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            metadata=self.metadata,
            operating_state=self.operating_state,
            is_available=self.is_available,
            timestamp_ns=self.last_step_timestamp_ns,
            measurements={
                "requested_p_w": TelemetryPoint(
                    value=self.requested_p_w,
                    unit="W",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "requested_q_var": TelemetryPoint(
                    value=self.requested_q_var,
                    unit="VAR",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "accepted_p_w": TelemetryPoint(
                    value=self.accepted_p_w,
                    unit="W",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "accepted_q_var": TelemetryPoint(
                    value=self.accepted_q_var,
                    unit="VAR",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "actual_p_w": TelemetryPoint(
                    value=self.actual_p_w,
                    unit="W",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "actual_q_var": TelemetryPoint(
                    value=self.actual_q_var,
                    unit="VAR",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "measured_p_w": TelemetryPoint(
                    value=self.measured_p_w,
                    unit="W",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "measured_q_var": TelemetryPoint(
                    value=self.measured_q_var,
                    unit="VAR",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "igbt_temp_c": TelemetryPoint(
                    value=self.igbt_temp_c,
                    unit="degC",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
            },
            active_limits={
                "rated_active_power_w": self.config.rated_active_power_w,
                "rated_apparent_power_va": self.config.rated_apparent_power_va,
                "ramp_rate_limit_w_per_s": self.config.ramp_rate_limit_w_per_s,
            },
            alarms=[a for a in self.active_alarms if not a.cleared],
        )
