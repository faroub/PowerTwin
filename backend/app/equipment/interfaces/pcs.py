"""Power Conversion System (PCS) Interface."""

from pydantic import BaseModel, Field
from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class PCSConfig(BaseModel):
    """Configuration schema for PCS (Inverter)."""

    rated_power_w: float = Field(default=5_000_000.0, description="Rated active power (+W = Discharging)")
    rated_apparent_power_va: float = Field(default=5_500_000.0, description="Max apparent power S_max")
    dc_voltage_nominal_v: float = Field(default=1000.0)
    ac_voltage_nominal_v: float = Field(default=690.0)


class PCSCommand(BaseModel):
    """Command schema for PCS."""

    active_power_setpoint_w: float = Field(default=0.0, description="+W = Discharge into grid, -W = Charge")
    reactive_power_setpoint_var: float = Field(default=0.0, description="+VAR = Supplying VARs")
    enable_inverter: bool | None = None
    reset_fault: bool = False


class PCSInterface(BaseEquipmentInterface):
    """Generic interface for PCS inverter models."""

    def __init__(self, equipment_id: str = "PCS_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.PCS)
