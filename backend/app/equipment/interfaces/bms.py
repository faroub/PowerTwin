"""Battery Management System (BMS) Interface."""

from pydantic import BaseModel, Field

from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType, OperatingState


class BMSConfig(BaseModel):
    """Configuration schema for BMS."""

    over_voltage_limit_v: float = Field(default=1200.0)
    under_voltage_limit_v: float = Field(default=800.0)
    over_temp_limit_c: float = Field(default=60.0)


class BMSCommand(BaseModel):
    """Command schema for BMS."""

    target_state: OperatingState | None = None
    close_contactors: bool | None = None
    clear_faults: bool = False


class BMSInterface(BaseEquipmentInterface):
    """Generic interface for BMS controllers."""

    def __init__(self, equipment_id: str = "BMS_MASTER_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.BMS)
