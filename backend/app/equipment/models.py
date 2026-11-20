"""Universal Equipment State Model and Common Data Enums."""

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class EquipmentType(StrEnum):
    """Categorization of BESS equipment and control entities."""

    BATTERY_SYSTEM = "BATTERY_SYSTEM"
    BMS = "BMS"
    PCS = "PCS"
    TRANSFORMER = "TRANSFORMER"
    SWITCHGEAR = "SWITCHGEAR"
    METER = "METER"
    AUXILIARY_SYSTEM = "AUXILIARY_SYSTEM"
    GRID_MODEL = "GRID_MODEL"
    PLANT_CONTROLLER = "PLANT_CONTROLLER"
    PPC = "PPC"
    EMS = "EMS"
    GRID_SERVICE = "GRID_SERVICE"


class OperatingState(StrEnum):
    """Universal operational state across all equipment models."""

    OFF = "OFF"
    STANDBY = "STANDBY"
    RUNNING = "RUNNING"
    FAULTED = "FAULTED"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class CommunicationStatus(StrEnum):
    """Communication link status of an equipment component."""

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    SIMULATED = "SIMULATED"


class QualityFlag(StrEnum):
    """Data quality status tag for telemetry metrics."""

    GOOD = "GOOD"
    BAD = "BAD"
    UNCERTAIN = "UNCERTAIN"
    STALE = "STALE"


class AlarmSeverity(StrEnum):
    """Alarm severity levels."""

    INFO = "INFO"
    WARNING = "WARNING"
    FAULT = "FAULT"
    CRITICAL = "CRITICAL"


class TelemetryPoint(BaseModel):
    """Standardized measurement payload with explicit unit and data quality tag."""

    value: float
    unit: str = Field(description="Explicit SI unit (e.g., V, A, W, VAR, degC, Hz, Ohm)")
    timestamp_ns: int = Field(description="Simulation tick timestamp in nanoseconds")
    quality: QualityFlag = Field(default=QualityFlag.GOOD)
    source_id: str = Field(description="Entity ID of sensor or component")


class AlarmRecord(BaseModel):
    """Standardized alarm and event record."""

    alarm_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    code: str = Field(description="Unique alarm code e.g. 'OVER_TEMP_FAULT'")
    severity: AlarmSeverity
    description: str
    timestamp_ns: int
    source_id: str
    acknowledged: bool = False
    cleared: bool = False


class EquipmentMetadata(BaseModel):
    """Equipment metadata and manufacturer specifications."""

    manufacturer: str = Field(default="Generic BESS")
    model_name: str = Field(default="Standard Model")
    firmware_version: str = Field(default="1.0.0")
    serial_number: str = Field(default="SIM-0000-0000")
    is_illustrative: bool = Field(
        default=True,
        description="Explicit flag indicating illustrative model parameters",
    )


class UniversalEquipmentState(BaseModel):
    """Universal equipment state envelope reported by all models."""

    equipment_id: str
    equipment_type: EquipmentType
    metadata: EquipmentMetadata = Field(default_factory=EquipmentMetadata)
    operating_state: OperatingState = OperatingState.STANDBY
    is_available: bool = True
    comm_status: CommunicationStatus = CommunicationStatus.SIMULATED
    timestamp_ns: int = 0
    quality: QualityFlag = QualityFlag.GOOD
    measurements: dict[str, TelemetryPoint] = Field(default_factory=dict)
    active_limits: dict[str, float] = Field(default_factory=dict)
    alarms: list[AlarmRecord] = Field(default_factory=list)
