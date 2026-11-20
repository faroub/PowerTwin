"""Power Plant Controller (PPC) Interface."""

from pydantic import BaseModel, Field
from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import EquipmentType


class PPCConfig(BaseModel):
    """Configuration schema for PPC."""

    p_ramp_rate_limit_w_per_s: float = Field(default=10_000_000.0, description="Ramp limit MW/s")
    droop_pct: float = Field(default=5.0)


class PPCCommand(BaseModel):
    """Command schema for PPC."""

    p_poi_setpoint_w: float | None = None
    q_poi_setpoint_var: float | None = None
    enable_droop: bool | None = None


class PPCInterface(BaseEquipmentInterface):
    """Generic interface for Power Plant Controllers."""

    def __init__(self, equipment_id: str = "PPC_01") -> None:
        super().__init__(equipment_id=equipment_id, equipment_type=EquipmentType.PPC)
