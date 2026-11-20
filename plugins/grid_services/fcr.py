"""Frequency Containment Reserve (FCR) Grid Service Plugin."""

from backend.app.equipment.interfaces.grid_service import (
    GridServiceInterface,
    GridServiceMetadata,
    GridServiceStatus,
)


class FCRPlugin(GridServiceInterface):
    """Frequency Containment Reserve (FCR) fast primary frequency response plugin."""

    def __init__(
        self,
        equipment_id: str = "FCR_01",
        nominal_frequency_hz: float = 50.0,
        f_deadband_hz: float = 0.02,
        droop_pct: float = 2.0,
        rated_capacity_w: float = 10_000_000.0,
    ) -> None:
        metadata = GridServiceMetadata(
            service_id="FCR_01",
            service_name="Frequency Containment Reserve (FCR)",
            version="1.0.0",
            activation_conditions={"frequency_deviation_exceeds_hz": f_deadband_hz},
            required_equipment_capabilities=["FAST_RAMP", "FREQUENCY_RESPONSE"],
            power_and_energy_requirements={"min_power_w": rated_capacity_w},
            response_time_assumptions_ms=200.0,
            ramp_rate_requirements_w_per_s=10_000_000.0,
            min_soc_pct=15.0,
            max_soc_pct=85.0,
        )
        super().__init__(equipment_id=equipment_id, grid_service_metadata=metadata)
        self.nominal_frequency_hz: float = nominal_frequency_hz
        self.f_deadband_hz: float = f_deadband_hz
        self.droop_pct: float = droop_pct
        self.rated_capacity_w: float = rated_capacity_w

    def calculate_service_request(
        self,
        grid_frequency_hz: float,
        poi_voltage_v: float,
        current_soc_pct: float,
        active_power_w: float = 0.0,
        timestamp_ns: int = 0,
    ) -> tuple[float, float]:
        """Calculate fast proportional active power response to frequency deviations."""
        if not self.is_available(current_soc_pct):
            self.service_status = GridServiceStatus.UNAVAILABLE
            return (0.0, 0.0)

        f_dev = grid_frequency_hz - self.nominal_frequency_hz
        if abs(f_dev) <= self.f_deadband_hz:
            self.service_status = GridServiceStatus.IDLE
            return (0.0, 0.0)

        self.service_status = GridServiceStatus.ACTIVE
        p_req = - (self.rated_capacity_w / (self.droop_pct / 100.0)) * (f_dev / self.nominal_frequency_hz)
        p_req_clamped = max(-self.rated_capacity_w, min(self.rated_capacity_w, p_req))
        return (p_req_clamped, 0.0)
