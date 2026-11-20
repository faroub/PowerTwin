"""Energy Arbitrage Grid Service Plugin (Time-of-Use Schedule Dispatch)."""

from backend.app.equipment.interfaces.grid_service import (
    GridServiceInterface,
    GridServiceMetadata,
    GridServiceStatus,
)


class EnergyArbitragePlugin(GridServiceInterface):
    """Energy Arbitrage plugin providing scheduled time-of-use charge/discharge requests."""

    def __init__(
        self,
        equipment_id: str = "ENERGY_ARBITRAGE_01",
        target_discharge_p_w: float = 10_000_000.0,
        target_charge_p_w: float = -10_000_000.0,
    ) -> None:
        metadata = GridServiceMetadata(
            service_id="ENERGY_ARBITRAGE_01",
            service_name="Energy Arbitrage Dispatch",
            version="1.0.0",
            activation_conditions={"trigger": "SCHEDULE_TIME"},
            required_equipment_capabilities=["ENERGY_STORAGE", "SCHEDULED_DISPATCH"],
            power_and_energy_requirements={"min_power_w": 1_000_000.0},
            response_time_assumptions_ms=5000.0,
            ramp_rate_requirements_w_per_s=2_000_000.0,
            min_soc_pct=10.0,
            max_soc_pct=90.0,
        )
        super().__init__(equipment_id=equipment_id, grid_service_metadata=metadata)
        self.target_discharge_p_w: float = target_discharge_p_w
        self.target_charge_p_w: float = target_charge_p_w
        self.scheduled_action: str = "IDLE"

    def calculate_service_request(
        self,
        grid_frequency_hz: float,
        poi_voltage_v: float,
        current_soc_pct: float,
        active_power_w: float = 0.0,
        timestamp_ns: int = 0,
    ) -> tuple[float, float]:
        """Calculate active power request based on scheduled time-of-use action."""
        if not self.is_available(current_soc_pct):
            self.service_status = GridServiceStatus.UNAVAILABLE
            return (0.0, 0.0)

        if self.scheduled_action == "DISCHARGE":
            self.service_status = GridServiceStatus.ACTIVE
            return (self.target_discharge_p_w, 0.0)
        elif self.scheduled_action == "CHARGE":
            self.service_status = GridServiceStatus.ACTIVE
            return (self.target_charge_p_w, 0.0)
        else:
            self.service_status = GridServiceStatus.IDLE
            return (0.0, 0.0)
