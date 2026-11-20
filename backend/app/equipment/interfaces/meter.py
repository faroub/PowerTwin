"""Meter & Sensor Interface."""

from pydantic import BaseModel, Field
from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class MeterConfig(BaseModel):
    """Configuration schema for POI Power Meter."""

    accuracy_pct: float = Field(default=0.2, description="Meter accuracy tolerance percentage")


class MeterCommand(BaseModel):
    """Command schema for Meter."""

    reset_energy_registers: bool = False


class MeterInterface(BaseEquipmentInterface):
    """Generic interface for Revenue / Revenue-grade Meters."""

    def __init__(self, equipment_id: str = "METER_POI_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.METER)
