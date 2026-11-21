"""Renewable Power Smoothing Grid Service Plugin."""

from backend.app.equipment.interfaces.grid_service import (
    GridServiceInterface,
    GridServiceMetadata,
    GridServiceStatus,
)


class RenewableSmoothingPlugin(GridServiceInterface):
    """Renewable Power Smoothing plugin absorbing or injecting power to damp solar/wind ramps."""

    def __init__(
        self,
        equipment_id: str = "RENEWABLE_SMOOTHING_01",
        max_ramp_rate_w_per_s: float = 1_000_000.0,
        rated_capacity_w: float = 5_000_000.0,
    ) -> None:
        metadata = GridServiceMetadata(
            service_id="RENEWABLE_SMOOTHING_01",
            service_name="Renewable Power Ramp-Rate Smoothing",
            version="1.0.0",
            activation_conditions={
                "renewable_ramp_rate_exceeds": max_ramp_rate_w_per_s
            },
            required_equipment_capabilities=["RAMP_SMOOTHING", "FAST_RESPONSE"],
            power_and_energy_requirements={"max_power_w": rated_capacity_w},
            response_time_assumptions_ms=500.0,
            ramp_rate_requirements_w_per_s=10_000_000.0,
            min_soc_pct=10.0,
            max_soc_pct=90.0,
        )
        super().__init__(equipment_id=equipment_id, grid_service_metadata=metadata)
        self.max_ramp_rate_w_per_s: float = max_ramp_rate_w_per_s
        self.rated_capacity_w: float = rated_capacity_w
        self.last_power_w: float = 0.0

    def calculate_service_request(
        self,
        grid_frequency_hz: float,
        poi_voltage_v: float,
        current_soc_pct: float,
        active_power_w: float = 0.0,
        timestamp_ns: int = 0,
    ) -> tuple[float, float]:
        """Calculate smoothing charge/discharge request to enforce max ramp rate on solar/wind."""
        if not self.is_available(current_soc_pct):
            self.service_status = GridServiceStatus.UNAVAILABLE
            return (0.0, 0.0)

        dt_s = 0.1
        delta_p = active_power_w - self.last_power_w
        self.last_power_w = active_power_w
        ramp_rate = delta_p / dt_s

        if abs(ramp_rate) <= self.max_ramp_rate_w_per_s:
            self.service_status = GridServiceStatus.IDLE
            return (0.0, 0.0)

        self.service_status = GridServiceStatus.ACTIVE
        target_delta = (abs(ramp_rate) - self.max_ramp_rate_w_per_s) * dt_s
        smooth_p = -target_delta if ramp_rate > 0 else target_delta
        clamped_p = max(-self.rated_capacity_w, min(self.rated_capacity_w, smooth_p))

        return (clamped_p, 0.0)
