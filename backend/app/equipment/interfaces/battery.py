"""Battery System Interface."""

from typing import Any
from pydantic import BaseModel, Field
from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class BatterySystemConfig(BaseModel):
    """Configuration schema for Battery System models."""

    capacity_wh: float = Field(default=100_000_000.0, description="Nominal capacity in Watt-hours")
    nominal_voltage_v: float = Field(default=1000.0, description="Nominal DC voltage in Volts")
    max_charge_current_a: float = Field(default=1000.0, description="Max charge current limit (+A)")
    max_discharge_current_a: float = Field(default=1000.0, description="Max discharge current limit (+A)")
    initial_soc_pct: float = Field(default=50.0, description="Initial State of Charge (0-100%)")


class BatterySystemCommand(BaseModel):
    """Command schema for Battery System."""

    set_contactor_close: bool | None = None
    reset_faults: bool = False


class BatterySystemInterface(BaseEquipmentInterface):
    """Generic interface for Battery System models."""

    def __init__(self, equipment_id: str = "BATTERY_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.BATTERY_SYSTEM)
