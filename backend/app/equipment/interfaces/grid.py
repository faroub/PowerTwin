"""Grid Model Interface."""

from pydantic import BaseModel, Field

from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class GridModelConfig(BaseModel):
    """Configuration schema for Synthetic Grid Model."""

    nominal_frequency_hz: float = Field(default=60.0)
    nominal_voltage_v: float = Field(default=13800.0)


class GridModelCommand(BaseModel):
    """Command schema for Grid Model."""

    grid_frequency_target_hz: float | None = None
    grid_voltage_target_v: float | None = None


class GridModelInterface(BaseEquipmentInterface):
    """Generic interface for POI Grid models."""

    def __init__(self, equipment_id: str = "GRID_MODEL_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.GRID_MODEL)
