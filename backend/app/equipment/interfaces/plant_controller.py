"""Plant Controller Interface."""

from pydantic import BaseModel, Field

from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType, OperatingState


class PlantControllerConfig(BaseModel):
    """Configuration schema for Master Plant Controller."""

    plant_rated_power_w: float = Field(default=50_000_000.0)


class PlantControllerCommand(BaseModel):
    """Command schema for Master Plant Controller."""

    target_state: OperatingState | None = None


class PlantControllerInterface(BaseEquipmentInterface):
    """Generic interface for Master Plant Controllers."""

    def __init__(self, equipment_id: str = "PLANT_CTRL_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.PLANT_CONTROLLER)
