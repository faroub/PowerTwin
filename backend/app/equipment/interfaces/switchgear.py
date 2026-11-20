"""Switchgear & Circuit Breaker Interface."""

from pydantic import BaseModel, Field

from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class SwitchgearConfig(BaseModel):
    """Configuration schema for MV Switchgear."""

    rated_voltage_v: float = Field(default=13800.0)
    rated_current_a: float = Field(default=2000.0)


class SwitchgearCommand(BaseModel):
    """Command schema for Switchgear breaker."""

    target_breaker_closed: bool


class SwitchgearInterface(BaseEquipmentInterface):
    """Generic interface for Switchgear models."""

    def __init__(self, equipment_id: str = "SWG_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.SWITCHGEAR)
