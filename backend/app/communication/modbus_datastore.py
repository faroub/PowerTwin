"""Modbus TCP register codec and datastore for the isolated CIL gateway.

This module contains the protocol-level concerns of the controller-in-the-loop
(Modbus TCP) gateway:

* the mapping between a typed register value and its 16-bit Modbus register
  representation (encoding/decoding, including scaling),
* the pymodbus datastore context that serves the register table over a real
  TCP socket.

The module contains no plant access and no simulation logic. Every write that
reaches the datastore is handed to the owning gateway service, which performs
the semantic validation, the audit trail and the routing into the simulation.

Safety rules honoured here:

* only holding registers are exposed (function code 3 read / 6, 16 write),
* a write to a read-only telemetry register is rejected with a Modbus
  exception, never silently accepted,
* a write that cannot be decoded into the register's declared data type is
  rejected with a Modbus exception,
* the datastore never opens an outbound connection; it is a server only.
"""

from __future__ import annotations

import logging
import struct
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from pymodbus.datastore import ModbusBaseSlaveContext
from pymodbus.pdu import ExceptionResponse

from backend.app.communication.adapter import ModbusRegisterMapSpec, RegisterDataType

if TYPE_CHECKING:
    from backend.app.communication.modbus_server import ModbusTCPGatewayServer

logger = logging.getLogger(__name__)

# Modbus function codes supported by the gateway.
FC_READ_HOLDING_REGISTERS: int = 3
FC_WRITE_SINGLE_REGISTER: int = 6
FC_WRITE_MULTIPLE_REGISTERS: int = 16

# Number of 16-bit Modbus registers occupied by each supported data type.
REGISTER_WIDTH: dict[RegisterDataType, int] = {
    RegisterDataType.INT16: 1,
    RegisterDataType.UINT16: 1,
    RegisterDataType.INT32: 2,
    RegisterDataType.UINT32: 2,
    RegisterDataType.FLOAT32: 2,
    RegisterDataType.FLOAT64: 4,
    RegisterDataType.BITFIELD: 1,
}


class RegisterDecodeError(ValueError):
    """Raised when a register payload cannot be decoded into its data type."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def registers_for(data_type: RegisterDataType) -> int:
    """Return the number of 16-bit registers occupied by a data type."""
    return REGISTER_WIDTH[data_type]


def encode_value(data_type: RegisterDataType, value: float, scale_factor: float = 1.0) -> list[int]:
    """Encode a typed value into its 16-bit Modbus register representation.

    Args:
        data_type: The declared data type of the register.
        value: The engineering value (already in the register's unit).
        scale_factor: Multiplier applied to the engineering value before the
            raw representation is produced.

    Returns:
        The list of 16-bit unsigned register words, most significant first.

    Raises:
        RegisterDecodeError: If the value cannot be represented in the type.
    """
    raw = float(value) * float(scale_factor)

    if data_type == RegisterDataType.FLOAT32:
        try:
            packed = struct.pack(">f", raw)
        except (OverflowError, struct.error) as err:
            raise RegisterDecodeError(f"Value {value} is not representable as FLOAT32.") from err
    elif data_type == RegisterDataType.FLOAT64:
        try:
            packed = struct.pack(">d", raw)
        except (OverflowError, struct.error) as err:
            raise RegisterDecodeError(f"Value {value} is not representable as FLOAT64.") from err
    elif data_type == RegisterDataType.UINT16:
        if not raw.is_integer() or not 0 <= raw <= 0xFFFF:
            raise RegisterDecodeError(f"Value {value} is not a valid UINT16.")
        return [int(raw)]
    elif data_type == RegisterDataType.INT16:
        if not raw.is_integer() or not -0x8000 <= raw <= 0x7FFF:
            raise RegisterDecodeError(f"Value {value} is not a valid INT16.")
        return [int(raw) & 0xFFFF]
    elif data_type == RegisterDataType.UINT32:
        if not raw.is_integer() or not 0 <= raw <= 0xFFFF_FFFF:
            raise RegisterDecodeError(f"Value {value} is not a valid UINT32.")
        packed = struct.pack(">I", int(raw))
    elif data_type == RegisterDataType.INT32:
        if not raw.is_integer() or not -0x8000_0000 <= raw <= 0x7FFF_FFFF:
            raise RegisterDecodeError(f"Value {value} is not a valid INT32.")
        packed = struct.pack(">i", int(raw))
    elif data_type == RegisterDataType.BITFIELD:
        if not raw.is_integer() or not 0 <= raw <= 0xFFFF:
            raise RegisterDecodeError(f"Value {value} is not a valid BITFIELD.")
        return [int(raw)]
    else:  # pragma: no cover - exhaustive over the StrEnum
        raise RegisterDecodeError(f"Unsupported register data type '{data_type}'.")

    words = struct.unpack(f">{len(packed) // 2}H", packed)
    return [int(word) for word in words]


def decode_value(data_type: RegisterDataType, registers: list[int]) -> float:
    """Decode 16-bit Modbus registers into the declared engineering value.

    Args:
        data_type: The declared data type of the register.
        registers: The raw register words, most significant first.

    Returns:
        The decoded engineering value.

    Raises:
        RegisterDecodeError: If the payload does not match the data type.
    """
    expected = registers_for(data_type)
    if len(registers) != expected:
        raise RegisterDecodeError(
            f"Expected {expected} register(s) for {data_type}, received {len(registers)}."
        )

    if data_type == RegisterDataType.FLOAT32:
        return float(struct.unpack(">f", struct.pack(">HH", *registers))[0])
    if data_type == RegisterDataType.FLOAT64:
        return float(struct.unpack(">d", struct.pack(">HHHH", *registers))[0])
    if data_type == RegisterDataType.UINT16:
        return float(registers[0])
    if data_type == RegisterDataType.INT16:
        return float(registers[0] - 0x10000 if registers[0] & 0x8000 else registers[0])
    if data_type == RegisterDataType.UINT32:
        return float(struct.unpack(">I", struct.pack(">HH", *registers))[0])
    if data_type == RegisterDataType.INT32:
        return float(struct.unpack(">i", struct.pack(">HH", *registers))[0])
    if data_type == RegisterDataType.BITFIELD:
        return float(registers[0])

    raise RegisterDecodeError(f"Unsupported register data type '{data_type}'.")


class PowerTwinModbusContext(ModbusBaseSlaveContext):
    """pymodbus datastore context serving the PowerTwin CIL register table.

    The context is a *slave* datastore: it never opens an outbound
    connection and never contacts an external device. Reads are served from
    the register table owned by the gateway server; writes are validated by
    the gateway service, which owns the audit trail and the plant routing.
    """

    def __init__(self, server: ModbusTCPGatewayServer) -> None:
        self._server = server

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #

    async def async_getValues(
        self, fc_as_hex: int, address: int, count: int = 1
    ) -> list[int] | int:
        """Serve a read request from the register table.

        Args:
            fc_as_hex: The Modbus function code of the request.
            address: The first register address of the request.
            count: The number of registers requested.

        Returns:
            The raw register words, or a Modbus exception code.
        """
        if fc_as_hex != FC_READ_HOLDING_REGISTERS:
            return ExceptionResponse.ILLEGAL_FUNCTION

        try:
            return self._server.read_raw_registers(address, count)
        except ValueError as err:
            logger.warning("Rejected Modbus read at 0x%04X: %s", address, err)
            return ExceptionResponse.ILLEGAL_ADDRESS

    def getValues(self, fc_as_hex: int, address: int, count: int = 1) -> Sequence[int | bool]:
        """Synchronous read helper (pymodbus calls the async variant)."""
        return self._server.read_raw_registers(address, count)

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #

    async def async_setValues(
        self, fc_as_hex: int, address: int, values: Sequence[int | bool]
    ) -> int:
        """Validate and route a write request.

        Args:
            fc_as_hex: The Modbus function code of the request.
            address: The first register address of the request.
            values: The raw register words supplied by the client.

        Returns:
            ``0`` when the write was accepted, otherwise the Modbus exception
            code that the client receives.
        """
        if fc_as_hex not in (FC_WRITE_SINGLE_REGISTER, FC_WRITE_MULTIPLE_REGISTERS):
            return ExceptionResponse.ILLEGAL_FUNCTION

        accepted, reason, exception_code = self._server.handle_raw_write(
            address=address,
            values=[int(value) for value in values],
            function_code=fc_as_hex,
        )
        if accepted:
            return 0
        logger.warning("Rejected Modbus write at 0x%04X: %s", address, reason)
        return exception_code

    def setValues(self, fc_as_hex: int, address: int, values: Any) -> int:
        """Synchronous write helper (pymodbus calls the async variant)."""
        return self._server.handle_raw_write(
            address=address,
            values=[int(value) for value in values],
            function_code=fc_as_hex,
        )[2]


def spec_for_address(
    register_map: dict[int, ModbusRegisterMapSpec], address: int
) -> ModbusRegisterMapSpec | None:
    """Return the register specification starting at ``address``, if any."""
    return register_map.get(address)
