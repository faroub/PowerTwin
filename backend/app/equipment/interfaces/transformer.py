"""Transformer Interface."""

from pydantic import BaseModel, Field
from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class TransformerConfig(BaseModel):
    """Configuration schema for Step-Up Transformer."""

    rating_va: float = Field(default=10_000_000.0, description="Nominal rating in VA")
    primary_voltage_v: float = Field(default=690.0)
    secondary_voltage_v: float = Field(default=13800.0)
    impedance_pct: float = Field(default=5.75)


class TransformerCommand(BaseModel):
    """Command schema for Transformer."""

    adjust_tap_position: int | None = None


class TransformerInterface(BaseEquipmentInterface):
    """Generic interface for Transformer models."""

    def __init__(self, equipment_id: str = "XFRM_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.TRANSFORMER)
