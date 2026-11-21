"""Automatic Frequency Restoration Reserve (aFRR) Grid Service Plugin."""

from backend.app.equipment.interfaces.grid_service import (
    GridServiceInterface,
    GridServiceMetadata,
    GridServiceStatus,
)


class AFRRPlugin(GridServiceInterface):
    """Automatic Frequency Restoration Reserve (aFRR) secondary control plugin."""

    def __init__(
        self,
        equipment_id: str = "AFRR_01",
        rated_capacity_w: float = 10_000_000.0,
    ) -> None:
        metadata = GridServiceMetadata(
            service_id="AFRR_01",
            service_name="Automatic Frequency Restoration Reserve (aFRR)",
            version="1.0.0",
            activation_conditions={"signal": "AGC_SECONDARY_CONTROL"},
            required_equipment_capabilities=["AGC_CONTROL", "SECONDARY_RESPONSE"],
            power_and_energy_requirements={"min_power_w": rated_capacity_w},
            response_time_assumptions_ms=30000.0,
            ramp_rate_requirements_w_per_s=1_000_000.0,
            min_soc_pct=15.0,
            max_soc_pct=85.0,
        )
        super().__init__(equipment_id=equipment_id, grid_service_metadata=metadata)
        self.rated_capacity_w: float = rated_capacity_w
        self.agc_target_p_w: float = 0.0

    def set_agc_target(self, target_p_w: float) -> None:
        """Update secondary control AGC setpoint."""
        self.agc_target_p_w = target_p_w

    def calculate_service_request(
        self,
        grid_frequency_hz: float,
        poi_voltage_v: float,
        current_soc_pct: float,
        active_power_w: float = 0.0,
        timestamp_ns: int = 0,
    ) -> tuple[float, float]:
        """Calculate secondary control response to AGC dispatch signal."""
        if not self.is_available(current_soc_pct):
            self.service_status = GridServiceStatus.UNAVAILABLE
            return (0.0, 0.0)

        if self.agc_target_p_w == 0.0:
            self.service_status = GridServiceStatus.IDLE
            return (0.0, 0.0)

        self.service_status = GridServiceStatus.ACTIVE
        p_clamped = max(
            -self.rated_capacity_w, min(self.rated_capacity_w, self.agc_target_p_w)
        )
        return (p_clamped, 0.0)
