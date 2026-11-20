"""Auxiliary Systems (HVAC, Fire Suppression, Controls) Interface."""

from pydantic import BaseModel, Field
from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class AuxiliaryConfig(BaseModel):
    """Configuration schema for HVAC and Auxiliary Container loads."""

    cooling_capacity_w: float = Field(default=50_000.0, description="HVAC cooling capacity in Watts")
    aux_base_power_w: float = Field(default=5000.0, description="Baseline auxiliary electrical power draw")


class AuxiliaryCommand(BaseModel):
    """Command schema for HVAC Auxiliary System."""

    setpoint_temp_c: float = Field(default=23.0)


class AuxiliarySystemInterface(BaseEquipmentInterface):
    """Generic interface for Container Auxiliary and HVAC systems."""

    def __init__(self, equipment_id: str = "AUX_CONTAINER_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.AUXILIARY_SYSTEM)
