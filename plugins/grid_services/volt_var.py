"""Voltage and Reactive-Power Support Grid Service Plugin."""

from backend.app.equipment.interfaces.grid_service import (
    GridServiceInterface,
    GridServiceMetadata,
    GridServiceStatus,
)


class VoltVarSupportPlugin(GridServiceInterface):
    """Volt-VAR curve regulation providing reactive power support during voltage deviations."""

    def __init__(
        self,
        equipment_id: str = "VOLT_VAR_01",
        nominal_voltage_v: float = 13800.0,
        voltage_deadband_pct: float = 1.0,
        max_q_var: float = 5_000_000.0,
    ) -> None:
        metadata = GridServiceMetadata(
            service_id="VOLT_VAR_01",
            service_name="Voltage & Volt-VAR Reactive Power Support",
            version="1.0.0",
            activation_conditions={"voltage_deviation_pct_exceeds": voltage_deadband_pct},
            required_equipment_capabilities=["VAR_SUPPORT", "VOLT_VAR_REGULATION"],
            power_and_energy_requirements={"max_q_var": max_q_var},
            response_time_assumptions_ms=50.0,
            ramp_rate_requirements_w_per_s=50_000_000.0,
            min_soc_pct=5.0,
            max_soc_pct=95.0,
        )
        super().__init__(equipment_id=equipment_id, grid_service_metadata=metadata)
        self.nominal_voltage_v: float = nominal_voltage_v
        self.voltage_deadband_pct: float = voltage_deadband_pct
        self.max_q_var: float = max_q_var

    def calculate_service_request(
        self,
        grid_frequency_hz: float,
        poi_voltage_v: float,
        current_soc_pct: float,
        active_power_w: float = 0.0,
        timestamp_ns: int = 0,
    ) -> tuple[float, float]:
        """Calculate reactive power (Q_req) support based on POI voltage deviation."""
        if not self.is_available(current_soc_pct):
            self.service_status = GridServiceStatus.UNAVAILABLE
            return (0.0, 0.0)

        v_dev_pct = ((poi_voltage_v - self.nominal_voltage_v) / self.nominal_voltage_v) * 100.0
        if abs(v_dev_pct) <= self.voltage_deadband_pct:
            self.service_status = GridServiceStatus.IDLE
            return (0.0, 0.0)

        self.service_status = GridServiceStatus.ACTIVE
        q_req = -(v_dev_pct / 5.0) * self.max_q_var
        q_clamped = max(-self.max_q_var, min(self.max_q_var, q_req))
        return (0.0, q_clamped)
