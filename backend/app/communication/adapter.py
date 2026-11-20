"""Protocol Adapter Interface Specification for Modbus TCP, OPC UA, and MQTT Adapters."""

from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import BaseModel, Field


class RegisterDataType(StrEnum):
    """Modbus and Protocol Register Data Types."""

    INT16 = "INT16"
    UINT16 = "UINT16"
    INT32 = "INT32"
    UINT32 = "UINT32"
    FLOAT32 = "FLOAT32"
    FLOAT64 = "FLOAT64"
    BITFIELD = "BITFIELD"


class ModbusRegisterMapSpec(BaseModel):
    """Specification for a Modbus Register Mapping."""

    address: int = Field(description="Modbus register 0-based address offset")
    name: str = Field(description="Telemetry tag or command name e.g. 'P_SETPOINT_W'")
    data_type: RegisterDataType
    unit: str = Field(default="", description="SI Unit e.g. 'W', 'V', 'Hz'")
    scale_factor: float = Field(default=1.0, description="Multiplier scale factor")
    is_writable: bool = Field(
        default=False, description="True = Command register, False = Read-Only"
    )
    min_value: float | None = Field(default=None)
    max_value: float | None = Field(default=None)
    description: str = Field(default="")


class ProtocolAdapterInterface(ABC):
    """Abstract Adapter Interface for external communication protocols (Modbus, OPC UA, MQTT)."""

    def __init__(self, adapter_name: str, host: str = "127.0.0.1", port: int = 5020) -> None:
        self.adapter_name: str = adapter_name
        self.host: str = host  # Loopback by default per safety invariants
        self.port: int = port
        self.is_running: bool = False
        self.client_connections_count: int = 0
        self.allow_writes: bool = False

    @abstractmethod
    def start(self) -> bool:
        """Start the protocol server/gateway service on loopback network."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the protocol server/gateway service."""

    @abstractmethod
    def update_telemetry_point(self, name: str, value: float, quality: str = "GOOD") -> None:
        """Update a protocol telemetry point value from simulation state."""

    @abstractmethod
    def process_inbound_write(
        self, address: int, value: float, client_id: str = "UNKNOWN"
    ) -> tuple[bool, str]:
        """Validate and process an inbound write command from an external controller.

        Returns:
            Tuple of (accepted_boolean, rejection_reason_string)
        """
