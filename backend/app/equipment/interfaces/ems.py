"""Energy Management System (EMS) Interface."""

from pydantic import BaseModel

from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class EMSConfig(BaseModel):
    """Configuration schema for EMS."""

    strategy: str = "SCHEDULED_DISPATCH"


class EMSCommand(BaseModel):
    """Command schema for EMS."""

    set_strategy: str | None = None


class EMSInterface(BaseEquipmentInterface):
    """Generic interface for Energy Management Systems."""

    def __init__(self, equipment_id: str = "EMS_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.EMS)
