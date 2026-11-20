"""Battery System Interface."""

from pydantic import BaseModel, Field, field_validator

from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class BatterySystemConfig(BaseModel):
    """Configuration schema for Battery System models."""

    capacity_wh: float = Field(default=100_000_000.0, description="Nominal capacity in Wh")
    nominal_voltage_v: float = Field(default=1000.0, description="Nominal DC voltage in V")
    max_charge_current_a: float = Field(default=1000.0, description="Max charge limit (+A)")
    max_discharge_current_a: float = Field(default=1000.0, description="Max discharge limit (+A)")
    initial_soc_pct: float = Field(default=50.0, description="Initial State of Charge (%)")

    @field_validator("nominal_voltage_v", "capacity_wh")
    @classmethod
    def validate_positive(cls, v: float) -> float:
        if v <= 0.0:
            raise ValueError(f"Value must be strictly positive (> 0.0), got: {v}")
        return v

    @field_validator("initial_soc_pct")
    @classmethod
    def validate_soc(cls, v: float) -> float:
        if v < 0.0 or v > 100.0:
            raise ValueError(f"initial_soc_pct must be between 0.0 and 100.0, got: {v}")
        return v


class BatterySystemCommand(BaseModel):
    """Command schema for Battery System."""

    set_contactor_close: bool | None = None
    reset_faults: bool = False


class BatterySystemInterface(BaseEquipmentInterface):
    """Generic interface for Battery System models."""

    def __init__(self, equipment_id: str = "BATTERY_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.BATTERY_SYSTEM)
