"""Abstract Base Interface for All PowerTwin Equipment Models."""

from abc import ABC, abstractmethod
from typing import Any
from backend.app.equipment.models import (
    AlarmRecord,
    EquipmentMetadata,
    EquipmentType,
    OperatingState,
    UniversalEquipmentState,
)
from backend.app.simulation.context import SimulationContext


class BaseEquipmentInterface(ABC):
    """Abstract base class for all equipment, model, and controller interfaces."""

    def __init__(
        self,
        equipment_id: str,
        equipment_type: EquipmentType,
        metadata: EquipmentMetadata | None = None,
    ) -> None:
        self.equipment_id: str = equipment_id
        self.equipment_type: EquipmentType = equipment_type
        self.metadata: EquipmentMetadata = (
            metadata if metadata is not None else EquipmentMetadata()
        )
        self._operating_state: OperatingState = OperatingState.OFF
        self._is_available: bool = False
        self._active_alarms: list[AlarmRecord] = []
        self._is_initialized: bool = False

    @abstractmethod
    def initialize(self, config: dict[str, Any]) -> None:
        """Initialize equipment model state and parameters.

        Args:
            config: Equipment-specific configuration dictionary.
        """
        pass

    @abstractmethod
    def step(self, ctx: SimulationContext, delta_t_s: float) -> None:
        """Execute physical model step for a single simulation tick.

        Args:
            ctx: SimulationContext for current tick step.
            delta_t_s: Step duration in seconds.
        """
        pass

    @abstractmethod
    def process_command(self, cmd: dict[str, Any]) -> bool:
        """Process an inbound command payload.

        Args:
            cmd: Command dictionary.

        Returns:
            True if command accepted, False if rejected.
        """
        pass

    @abstractmethod
    def get_state(self) -> UniversalEquipmentState:
        """Return universal equipment state snapshot."""
        pass

    @abstractmethod
    def get_capabilities(self) -> dict[str, Any]:
        """Return dictionary of equipment technical capabilities."""
        pass

    def get_alarms(self) -> list[AlarmRecord]:
        """Return active alarms list."""
        return [a for a in self._active_alarms if not a.cleared]

    def get_health(self) -> dict[str, Any]:
        """Return component health status summary."""
        return {
            "equipment_id": self.equipment_id,
            "equipment_type": self.equipment_type,
            "is_initialized": self._is_initialized,
            "operating_state": self._operating_state,
            "is_available": self._is_available,
            "active_alarms_count": len(self.get_alarms()),
        }

    @abstractmethod
    def shutdown(self) -> None:
        """Clean up equipment model resources safely."""
        pass
