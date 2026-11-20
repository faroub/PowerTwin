"""Grid Service Interface."""

from pydantic import BaseModel
from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class GridServiceConfig(BaseModel):
    """Configuration schema for Grid Service (e.g. FFR, Volt-VAR, Frequency Regulation)."""

    service_type: str = "FREQUENCY_REGULATION"


class GridServiceCommand(BaseModel):
    """Command schema for Grid Service."""

    enable_service: bool


class GridServiceInterface(BaseEquipmentInterface):
    """Generic interface for Grid Service algorithms."""

    def __init__(self, equipment_id: str = "GRID_SVC_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.GRID_SERVICE)
