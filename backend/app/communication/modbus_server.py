"""Modbus TCP Gateway Server Adapter for CIL External Controller Interoperability."""

import logging

from backend.app.communication.adapter import (
    ModbusRegisterMapSpec,
    ProtocolAdapterInterface,
    RegisterDataType,
)
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_REGISTER_MAP: dict[int, ModbusRegisterMapSpec] = {
    0: ModbusRegisterMapSpec(
        address=0,
        name="PLANT_ACTIVE_POWER_MW",
        data_type=RegisterDataType.FLOAT32,
        unit="MW",
        is_writable=False,
        description="Plant Net Active Power Export (+MW)",
    ),
    2: ModbusRegisterMapSpec(
        address=2,
        name="PLANT_REACTIVE_POWER_MVAR",
        data_type=RegisterDataType.FLOAT32,
        unit="MVAR",
        is_writable=False,
        description="Plant Net Reactive Power (+MVAR)",
    ),
    4: ModbusRegisterMapSpec(
        address=4,
        name="POI_VOLTAGE_KV",
        data_type=RegisterDataType.FLOAT32,
        unit="kV",
        is_writable=False,
        description="POI AC Nominal Voltage",
    ),
    6: ModbusRegisterMapSpec(
        address=6,
        name="GRID_FREQUENCY_HZ",
        data_type=RegisterDataType.FLOAT32,
        unit="Hz",
        is_writable=False,
        description="Grid Operating Frequency",
    ),
    8: ModbusRegisterMapSpec(
        address=8,
        name="AVERAGE_SOC_PCT",
        data_type=RegisterDataType.FLOAT32,
        unit="pct",
        is_writable=False,
        description="Plant Average State of Charge",
    ),
    100: ModbusRegisterMapSpec(
        address=100,
        name="COMMAND_ACTIVE_POWER_W",
        data_type=RegisterDataType.FLOAT32,
        unit="W",
        is_writable=True,
        min_value=-50_000_000.0,
        max_value=50_000_000.0,
        description="Active Power Setpoint (+W Discharge, -W Charge)",
    ),
    102: ModbusRegisterMapSpec(
        address=102,
        name="COMMAND_REACTIVE_POWER_VAR",
        data_type=RegisterDataType.FLOAT32,
        unit="VAR",
        is_writable=True,
        min_value=-50_000_000.0,
        max_value=50_000_000.0,
        description="Reactive Power Setpoint (+VAR Supply, -VAR Absorb)",
    ),
    104: ModbusRegisterMapSpec(
        address=104,
        name="WATCHDOG_HEARTBEAT_COUNTER",
        data_type=RegisterDataType.UINT32,
        unit="count",
        is_writable=True,
        min_value=0.0,
        max_value=4294967295.0,
        description="External Controller Watchdog Heartbeat Counter",
    ),
}


class ModbusTCPGatewayServer(ProtocolAdapterInterface):
    """Modbus TCP Gateway Server operating on loopback isolated network only."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5020,
        register_map: dict[int, ModbusRegisterMapSpec] | None = None,
    ) -> None:
        super().__init__(adapter_name="ModbusTCP_Gateway", host=host, port=port)
        self.register_map: dict[int, ModbusRegisterMapSpec] = (
            register_map if register_map is not None else DEFAULT_REGISTER_MAP
        )
        self.register_values: dict[int, float] = {addr: 0.0 for addr in self.register_map}
        self.tag_to_address: dict[str, int] = {
            spec.name: addr for addr, spec in self.register_map.items()
        }

        self.allow_writes: bool = settings.ALLOW_EXTERNAL_MODBUS_WRITES

    def start(self) -> bool:
        """Start Modbus TCP server listener on loopback adapter."""
        if self.host not in ("127.0.0.1", "localhost", "::1"):
            msg = f"SAFETY INVARIANT VIOLATION: Refusing to bind host '{self.host}'"
            logger.error(msg)
            return False

        self.is_running = True
        logger.info("Modbus TCP Server started on %s:%d", self.host, self.port)
        return True

    def stop(self) -> None:
        """Stop Modbus TCP server listener."""
        self.is_running = False
        logger.info("Modbus TCP Gateway Server stopped.")

    def update_telemetry_point(self, name: str, value: float, quality: str = "GOOD") -> None:
        """Update in-memory register table from simulation model telemetry."""
        if name in self.tag_to_address:
            addr = self.tag_to_address[name]
            self.register_values[addr] = float(value)

    def read_register(self, address: int) -> float | None:
        """Read value from in-memory register table."""
        return self.register_values.get(address, None)

    def process_inbound_write(
        self, address: int, value: float, client_id: str = "EXTERNAL_CIL_CONTROLLER"
    ) -> tuple[bool, str]:
        """Validate and execute inbound Modbus write command from external controller."""
        if not self.allow_writes:
            return (
                False,
                "REJECTED_WRITES_DISABLED: ALLOW_EXTERNAL_MODBUS_WRITES is False in safety config.",
            )

        if address not in self.register_map:
            return (
                False,
                f"REJECTED_INVALID_ADDRESS: Modbus address 0x{address:04X} not found in map.",
            )

        spec = self.register_map[address]

        if not spec.is_writable:
            msg = f"REJECTED_READ_ONLY: Register '{spec.name}' (0x{address:04X}) read-only."
            return (False, msg)

        if spec.min_value is not None and value < spec.min_value:
            return (False, f"REJECTED_OUT_OF_RANGE: Value {value} is below min ({spec.min_value}).")

        if spec.max_value is not None and value > spec.max_value:
            return (False, f"REJECTED_OUT_OF_RANGE: Value {value} is above max ({spec.max_value}).")

        self.register_values[address] = value
        logger.info("Accepted Modbus write to 0x%04X (%s) = %f", address, spec.name, value)
        return (True, "ACCEPTED")
