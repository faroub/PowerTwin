"""Peak Shaving Grid Service Plugin."""

from backend.app.equipment.interfaces.grid_service import (
    GridServiceInterface,
    GridServiceMetadata,
    GridServiceStatus,
)


class PeakShavingPlugin(GridServiceInterface):
    """Peak Shaving plugin discharging BESS when facility load demand exceeds threshold."""

    def __init__(
        self,
        equipment_id: str = "PEAK_SHAVING_01",
        demand_threshold_w: float = 8_000_000.0,
        max_discharge_w: float = 5_000_000.0,
    ) -> None:
        metadata = GridServiceMetadata(
            service_id="PEAK_SHAVING_01",
            service_name="Facility Peak Shaving",
            version="1.0.0",
            activation_conditions={"facility_demand_exceeds_w": demand_threshold_w},
            required_equipment_capabilities=["PEAK_SHAVING", "DEMAND_LIMITING"],
            power_and_energy_requirements={"max_power_w": max_discharge_w},
            response_time_assumptions_ms=1000.0,
            ramp_rate_requirements_w_per_s=5_000_000.0,
            min_soc_pct=10.0,
            max_soc_pct=90.0,
        )
        super().__init__(equipment_id=equipment_id, grid_service_metadata=metadata)
        self.demand_threshold_w: float = demand_threshold_w
        self.max_discharge_w: float = max_discharge_w

    def calculate_service_request(
        self,
        grid_frequency_hz: float,
        poi_voltage_v: float,
        current_soc_pct: float,
        active_power_w: float = 0.0,
        timestamp_ns: int = 0,
    ) -> tuple[float, float]:
        """Calculate peak shaving discharge request when load exceeds threshold."""
        if not self.is_available(current_soc_pct):
            self.service_status = GridServiceStatus.UNAVAILABLE
            return (0.0, 0.0)

        if active_power_w <= self.demand_threshold_w:
            self.service_status = GridServiceStatus.IDLE
            return (0.0, 0.0)

        self.service_status = GridServiceStatus.ACTIVE
        excess_demand = active_power_w - self.demand_threshold_w
        shave_p_req = min(self.max_discharge_w, excess_demand)
        return (shave_p_req, 0.0)
