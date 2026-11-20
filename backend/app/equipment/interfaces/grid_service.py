"""Standardized Grid Service Interface Specification."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class GridServiceStatus(StrEnum):
    """Grid Service Operational Status."""

    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"
    UNAVAILABLE = "UNAVAILABLE"


class GridServiceMetadata(BaseModel):
    """Declarative Grid Service Metadata and Market Requirements Specification."""

    service_id: str = Field(description="Unique service identifier e.g. 'FCR_01'")
    service_name: str = Field(description="Display name e.g. 'Frequency Containment Reserve'")
    version: str = Field(default="1.0.0", description="Configuration version")
    activation_conditions: dict[str, Any] = Field(
        default_factory=dict, description="Triggers for service activation"
    )
    required_equipment_capabilities: list[str] = Field(
        default_factory=list, description="Capabilities e.g. ['FAST_RAMP', 'BIDIRECTIONAL_POWER']"
    )
    power_and_energy_requirements: dict[str, float] = Field(
        default_factory=dict, description="Min power and energy requirements"
    )
    response_time_assumptions_ms: float = Field(
        default=500.0, description="Response time requirement in ms"
    )
    ramp_rate_requirements_w_per_s: float = Field(
        default=10_000_000.0, description="Min ramp rate in W/s"
    )
    min_soc_pct: float = Field(default=10.0, description="Min SoC boundary for availability")
    max_soc_pct: float = Field(default=90.0, description="Max SoC boundary for availability")
    availability_requirements: dict[str, Any] = Field(
        default_factory=dict, description="System availability requirements"
    )


class GridServiceInterface(BaseEquipmentInterface):
    """Standardized Abstract Interface for BESS Grid Service Plugins."""

    def __init__(
        self,
        equipment_id: str = "GRID_SVC_01",
        grid_service_metadata: GridServiceMetadata | None = None,
    ) -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.GRID_SERVICE)
        self.grid_service_metadata: GridServiceMetadata = (
            grid_service_metadata
            if grid_service_metadata is not None
            else GridServiceMetadata(
                service_id=equipment_id, service_name="Generic Grid Service"
            )
        )
        self.service_status: GridServiceStatus = GridServiceStatus.IDLE
        self.performance_score: float = 1.0

    def is_available(self, current_soc_pct: float, current_temp_c: float = 25.0) -> bool:
        """Check if grid service availability criteria are satisfied."""
        if self.service_status == GridServiceStatus.DEACTIVATED:
            return False

        if (
            current_soc_pct < self.grid_service_metadata.min_soc_pct
            or current_soc_pct > self.grid_service_metadata.max_soc_pct
        ):
            return False

        return True

    def calculate_service_request(
        self,
        grid_frequency_hz: float,
        poi_voltage_v: float,
        current_soc_pct: float,
        active_power_w: float = 0.0,
        timestamp_ns: int = 0,
    ) -> tuple[float, float]:
        """Calculate requested active (P_req) and reactive (Q_req) power setpoint.

        Returns:
            Tuple of (requested_p_w, requested_q_var)
        """
        raise NotImplementedError("Subclasses must implement calculate_service_request()")

    def calculate_performance_score(
        self, requested_p_w: float, actual_p_w: float, duration_s: float = 1.0
    ) -> float:
        """Calculate service compliance/performance score (0.0 to 1.0)."""
        if requested_p_w == 0.0:
            return 1.0

        ratio = min(1.0, max(0.0, actual_p_w / requested_p_w))
        self.performance_score = ratio
        return ratio
