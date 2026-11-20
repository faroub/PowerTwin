"""Generic Battery System Physical and Energy-Balance Model.

DOCUMENTED SIGN CONVENTION:
  +P (Positive Power) = DISCHARGING (Battery delivering power to AC grid/plant)
  -P (Negative Power) = CHARGING (Battery absorbing power from AC grid/plant)
  +I (Positive Current) = DISCHARGE CURRENT out of battery terminal
  -I (Negative Current) = CHARGE CURRENT into battery terminal
"""

import logging

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

logger = logging.getLogger(__name__)


class BatterySystemConfigModel(BaseModel):
    """Configuration schema for Generic Battery System Model."""

    capacity_wh: float = Field(
        default=100_000_000.0, description="Nominal battery energy capacity in Wh (e.g. 100 MWh)"
    )
    nominal_voltage_v: float = Field(default=1000.0, description="Nominal DC voltage in Volts")
    initial_soc_pct: float = Field(default=50.0, description="Initial State of Charge (%)")
    min_soc_pct: float = Field(default=5.0, description="Minimum allowable SoC limit (%)")
    max_soc_pct: float = Field(default=95.0, description="Maximum allowable SoC limit (%)")
    max_charge_power_w: float = Field(
        default=50_000_000.0, description="Maximum charge power capability in Watts"
    )
    max_discharge_power_w: float = Field(
        default=50_000_000.0, description="Maximum discharge power capability in Watts"
    )
    charge_efficiency: float = Field(
        default=0.97, description="Battery charge efficiency (0.0 to 1.0)"
    )
    discharge_efficiency: float = Field(
        default=0.97, description="Battery discharge efficiency (0.0 to 1.0)"
    )
    aux_power_w: float = Field(
        default=10_000.0, description="Continuous auxiliary container load in Watts"
    )
    initial_temp_c: float = Field(default=25.0, description="Initial temperature in deg C")
    initial_soh_pct: float = Field(default=100.0, description="Initial State of Health (%)")
    thermal_mass_j_per_c: float = Field(
        default=50_000_000.0, description="Lumped container thermal mass in J/degC"
    )

    @field_validator(
        "capacity_wh", "nominal_voltage_v", "max_charge_power_w", "max_discharge_power_w"
    )
    @classmethod
    def validate_positive(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"Value must be strictly positive (> 0), got: {v}")
        return v

    @field_validator("charge_efficiency", "discharge_efficiency")
    @classmethod
    def validate_efficiency(cls, v: float) -> float:
        if v <= 0.0 or v > 1.0:
            raise ValueError(f"Efficiency must be in range (0.0, 1.0], got: {v}")
        return v

    @field_validator("initial_soc_pct", "min_soc_pct", "max_soc_pct")
    @classmethod
    def validate_soc_bounds(cls, v: float) -> float:
        if v < 0.0 or v > 100.0:
            raise ValueError(f"SoC value must be between 0.0 and 100.0, got: {v}")
        return v


class GenericBatterySystemModel:
    """Configurable, energy-balanced Battery System Model."""

    def __init__(
        self,
        equipment_id: str = "BATTERY_SYS_01",
        config: BatterySystemConfigModel | None = None,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.equipment_type: EquipmentType = EquipmentType.BATTERY_SYSTEM
        self.config: BatterySystemConfigModel = (
            config if config is not None else BatterySystemConfigModel()
        )

        self.soc_pct: float = self.config.initial_soc_pct
        self.soh_pct: float = self.config.initial_soh_pct
        self.temperature_c: float = self.config.initial_temp_c
        self.active_power_w: float = 0.0
        self.current_a: float = 0.0
        self.voltage_v: float = self.config.nominal_voltage_v
        self.operating_state: OperatingState = OperatingState.STANDBY
        self.is_available: bool = True
        self.active_alarms: list[AlarmRecord] = []
        self.metadata: EquipmentMetadata = EquipmentMetadata(
            manufacturer="Generic BESS", model_name="Energy-Balanced Battery Model V1"
        )

        self.total_throughput_wh: float = 0.0
        self.last_step_timestamp_ns: int = 0

    @property
    def round_trip_efficiency(self) -> float:
        """Return total round-trip efficiency (RTE = eta_charge * eta_discharge)."""
        return self.config.charge_efficiency * self.config.discharge_efficiency

    @property
    def stored_energy_wh(self) -> float:
        """Return current usable stored chemical energy in Watt-hours."""
        return self.config.capacity_wh * (self.soc_pct / 100.0) * (self.soh_pct / 100.0)

    def get_available_power_limits(self) -> tuple[float, float]:
        """Calculate dynamic available charge and discharge power limits in Watts."""
        if not self.is_available or self.operating_state in (
            OperatingState.OFF,
            OperatingState.FAULTED,
            OperatingState.EMERGENCY_STOP,
        ):
            return (0.0, 0.0)

        # Discharge power limits (+W)
        if self.soc_pct <= self.config.min_soc_pct:
            avail_dis_w = 0.0
        else:
            usable_energy_wh = (
                self.config.capacity_wh * ((self.soc_pct - self.config.min_soc_pct) / 100.0)
            )
            max_dis_power_from_energy = usable_energy_wh * self.config.discharge_efficiency
            avail_dis_w = min(self.config.max_discharge_power_w, max_dis_power_from_energy)

        # Charge power limits (-W magnitude)
        if self.soc_pct >= self.config.max_soc_pct:
            avail_ch_w = 0.0
        else:
            headroom_energy_wh = (
                self.config.capacity_wh * ((self.config.max_soc_pct - self.soc_pct) / 100.0)
            )
            max_ch_power_from_energy = headroom_energy_wh / self.config.charge_efficiency
            avail_ch_w = min(self.config.max_charge_power_w, max_ch_power_from_energy)

        return (avail_ch_w, avail_dis_w)

    def step(self, power_demand_w: float, delta_t_s: float, timestamp_ns: int = 0) -> None:
        """Execute battery energy balance step for time step delta_t_s."""
        if delta_t_s <= 0.0:
            raise InvalidTimeStepError(
                f"Simulation delta_t_s must be strictly positive (> 0.0), got: {delta_t_s}"
            )

        self.last_step_timestamp_ns = timestamp_ns
        avail_ch_w, avail_dis_w = self.get_available_power_limits()

        # Clamp requested power against available limits
        if power_demand_w > 0.0:  # Discharging
            actual_p_w = min(power_demand_w, avail_dis_w)
        elif power_demand_w < 0.0:  # Charging
            actual_p_w = max(power_demand_w, -avail_ch_w)
        else:
            actual_p_w = 0.0

        self.active_power_w = actual_p_w

        # Update OCV terminal voltage approximation based on SoC
        self.voltage_v = self.config.nominal_voltage_v * (0.85 + 0.30 * (self.soc_pct / 100.0))
        self.current_a = actual_p_w / max(self.voltage_v, 1.0)

        # 1. Chemical energy change calculation
        if actual_p_w > 0.0:  # Discharging: draws P_bat / eta_dis
            chem_power_w = actual_p_w / self.config.discharge_efficiency
            delta_e_chem_wh = (chem_power_w * delta_t_s) / 3600.0
            delta_soc_pct = -(delta_e_chem_wh / self.config.capacity_wh) * 100.0
            losses_w = chem_power_w - actual_p_w
        elif actual_p_w < 0.0:  # Charging: stores |P_bat| * eta_ch
            abs_p_w = abs(actual_p_w)
            chem_power_w = abs_p_w * self.config.charge_efficiency
            delta_e_chem_wh = (chem_power_w * delta_t_s) / 3600.0
            delta_soc_pct = +(delta_e_chem_wh / self.config.capacity_wh) * 100.0
            losses_w = abs_p_w - chem_power_w
        else:
            chem_power_w = 0.0
            delta_e_chem_wh = 0.0
            delta_soc_pct = 0.0
            losses_w = 0.0

        # 2. Continuous Auxiliary Power Consumption
        aux_e_wh = (self.config.aux_power_w * delta_t_s) / 3600.0
        aux_soc_pct = (aux_e_wh / self.config.capacity_wh) * 100.0

        # Update SoC and clamp between min and max limits
        new_soc = self.soc_pct + delta_soc_pct - aux_soc_pct
        self.soc_pct = max(self.config.min_soc_pct, min(self.config.max_soc_pct, new_soc))

        # Accumulate energy throughput
        self.total_throughput_wh += abs(actual_p_w * delta_t_s) / 3600.0

        # 3. Lumped Thermal Mass Update (Losses + Aux heat - Passive cooling)
        delta_q_joules = (losses_w + self.config.aux_power_w) * delta_t_s
        temp_rise_c = delta_q_joules / self.config.thermal_mass_j_per_c
        cooling_c = (self.temperature_c - 25.0) * (0.01 * delta_t_s)
        self.temperature_c += temp_rise_c - cooling_c

        # Update operating state
        if not self.is_available or self.operating_state == OperatingState.FAULTED:
            pass
        elif actual_p_w != 0.0:
            self.operating_state = OperatingState.RUNNING
        else:
            self.operating_state = OperatingState.STANDBY

    def set_fault(self, alarm_code: str, description: str) -> None:
        """Trigger an equipment fault state."""
        self.operating_state = OperatingState.FAULTED
        self.is_available = False
        alarm = AlarmRecord(
            code=alarm_code,
            severity=AlarmSeverity.FAULT,
            description=description,
            timestamp_ns=self.last_step_timestamp_ns,
            source_id=self.equipment_id,
        )
        self.active_alarms.append(alarm)

    def clear_faults(self) -> None:
        """Clear active faults and restore standby state."""
        for a in self.active_alarms:
            a.cleared = True
        self.operating_state = OperatingState.STANDBY
        self.is_available = True

    def get_state(self) -> UniversalEquipmentState:
        """Return universal equipment state snapshot."""
        avail_ch_w, avail_dis_w = self.get_available_power_limits()
        return UniversalEquipmentState(
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            metadata=self.metadata,
            operating_state=self.operating_state,
            is_available=self.is_available,
            timestamp_ns=self.last_step_timestamp_ns,
            measurements={
                "soc_pct": TelemetryPoint(
                    value=self.soc_pct,
                    unit="pct",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "soh_pct": TelemetryPoint(
                    value=self.soh_pct,
                    unit="pct",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "voltage_v": TelemetryPoint(
                    value=self.voltage_v,
                    unit="V",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "current_a": TelemetryPoint(
                    value=self.current_a,
                    unit="A",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "active_power_w": TelemetryPoint(
                    value=self.active_power_w,
                    unit="W",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
                "temperature_c": TelemetryPoint(
                    value=self.temperature_c,
                    unit="degC",
                    timestamp_ns=self.last_step_timestamp_ns,
                    source_id=self.equipment_id,
                ),
            },
            active_limits={
                "available_charge_power_w": avail_ch_w,
                "available_discharge_power_w": avail_dis_w,
            },
            alarms=[a for a in self.active_alarms if not a.cleared],
        )
