"""Modbus TCP Gateway Server Adapter for CIL External Controller Interoperability.

This module implements a **real** Modbus TCP server: it opens a TCP socket on
the loopback interface and speaks the Modbus TCP protocol through the
``pymodbus`` library. The register table is served from the internal
simulation plant; the server never opens an outbound connection and never
touches physical equipment.

Safety properties enforced here:

* the listener binds to a loopback address only; any other host is refused,
* the server is disabled by default and must be explicitly enabled,
* telemetry registers are read-only and a write to them is rejected with a
  Modbus exception rather than silently accepted,
* a write that does not match the declared data type of the register is
  rejected with a Modbus exception,
* non-finite and out-of-range command values are rejected,
* every write attempt is handed to the owning gateway service, which owns the
  audit trail and the routing into the simulation.
"""

import asyncio
import logging
import math
import threading
from typing import Any

from pymodbus.datastore import ModbusServerContext
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.pdu import ExceptionResponse
from pymodbus.server import ModbusTcpServer
from pymodbus.server.requesthandler import ServerRequestHandler

from backend.app.communication.adapter import (
    ModbusRegisterMapSpec,
    ProtocolAdapterInterface,
    RegisterDataType,
)
from backend.app.communication.modbus_datastore import (
    PowerTwinModbusContext,
    RegisterDecodeError,
    decode_value,
    encode_value,
    registers_for,
)
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Hosts the gateway is allowed to bind to. A Modbus TCP server exposes a
# writable control interface, so it must never be reachable from an untrusted
# network.
LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})

# Number of event-loop iterations that are executed while the gateway is shut
# down. A connection that is accepted concurrently with the shutdown is
# completed and closed by the accept callback, and the close notification needs
# a couple of loop iterations to run before the event loop may be torn down.
# Draining the loop guarantees that no transport is finalised against a closed
# loop.
SHUTDOWN_DRAIN_ITERATIONS: int = 16

# Maximum time the shutdown may take before the caller gives up waiting for
# the listener thread. The shutdown itself is a handful of event-loop
# iterations, so this budget only exists to stop a wedged listener from
# blocking the caller forever.
SHUTDOWN_TIMEOUT_S: float = 10.0

# Default identity reported to Modbus clients that ask for the device
# identification (FC43). It describes the *simulator*, never real equipment.
SERVER_IDENTITY: dict[str, str] = {
    "VendorName": "PowerTwin",
    "ProductCode": "PowerTwin BESS CIL Gateway",
    "VendorUrl": "https://localhost",
    "ProductName": "PowerTwin Modbus TCP CIL Gateway",
    "ModelName": "PowerTwin-CIL",
    "MajorMinorRevision": "1.0.0",
    "UserApplicationName": "PowerTwin BESS Simulator (simulation only)",
}

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
    10: ModbusRegisterMapSpec(
        address=10,
        name="EQUIPMENT_AVAILABILITY_PCT",
        data_type=RegisterDataType.FLOAT32,
        unit="pct",
        is_writable=False,
        description="Plant Equipment Availability Percentage",
    ),
    12: ModbusRegisterMapSpec(
        address=12,
        name="ACTIVE_ALARMS_COUNT",
        data_type=RegisterDataType.UINT32,
        unit="count",
        is_writable=False,
        description="Total Active Critical Alarms Count",
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
    106: ModbusRegisterMapSpec(
        address=106,
        name="COMMAND_EMS_MODE",
        data_type=RegisterDataType.UINT16,
        unit="enum",
        is_writable=True,
        min_value=0.0,
        max_value=3.0,
        description="EMS Operational Mode (0=MANUAL, 1=SCHEDULED, 2=PEAK, 3=DROOP)",
    ),
    108: ModbusRegisterMapSpec(
        address=108,
        name="COMMAND_RESET_FAULTS",
        data_type=RegisterDataType.UINT16,
        unit="flag",
        is_writable=True,
        min_value=0.0,
        max_value=1.0,
        description="Reset Active Equipment Faults (1 = Reset)",
    ),
}


class _ClientTrackingRequestHandler(ServerRequestHandler):
    """Request handler that records the peer address of the connected client.

    The peer address is only used for the audit trail; it never influences the
    command that is executed.

    The handler also registers its transport with the owning gateway. The
    gateway uses that registry to close every connection when the listener is
    shut down, including a connection that is accepted *while* the shutdown is
    running. Such a connection is invisible to the protocol library's own
    bookkeeping and would otherwise be left dangling.
    """

    def __init__(
        self,
        owner: Any,
        trace_packet: Any,
        trace_pdu: Any,
        trace_connect: Any,
        peer_holder: dict[str, Any],
        gateway: "ModbusTCPGatewayServer",
    ) -> None:
        super().__init__(owner, trace_packet, trace_pdu, trace_connect)  # type: ignore[no-untyped-call]
        self._peer_holder = peer_holder
        self._gateway = gateway

    def callback_data(self, data: bytes, addr: tuple[int, int] | None = None) -> int:
        """Record the peer address before delegating to the base handler."""
        if addr is not None:
            self._peer_holder["peer"] = f"{addr[0]}:{addr[1]}"
        return super().callback_data(data, addr)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Register the connection so the gateway can close it on shutdown."""
        super().connection_made(transport)
        self._gateway.register_connection(self, transport)

    def connection_lost(self, exc: Exception | None) -> None:
        """Forget the connection once its transport is closed."""
        try:
            super().connection_lost(exc)
        finally:
            self._gateway.unregister_connection(self)


class _PowerTwinModbusTcpServer(ModbusTcpServer):
    """Modbus TCP server that tracks the connected client's peer address."""

    def __init__(self, *args: Any, gateway: "ModbusTCPGatewayServer", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._gateway = gateway

    def callback_new_connection(self) -> Any:
        """Create a request handler that tracks the connecting peer.

        The protocol factory runs inside the accept task of the event loop,
        which may still be pending when the listener is closed. Refusing the
        connection here means that no transport is built for it: the accept
        task fails cleanly instead of attaching a half-built transport to a
        server object that has already been closed.
        """
        if self._gateway.shutting_down:
            logger.info(
                "Refusing a Modbus TCP connection that arrived while the gateway is shutting down."
            )
            raise ConnectionAbortedError(
                "The Modbus TCP gateway is shutting down; the connection is refused."
            )
        if self.trace_connect:
            self.trace_connect(True)
        return _ClientTrackingRequestHandler(
            self,
            self.trace_packet,
            self.trace_pdu,
            self.trace_connect,
            self._gateway.peer_holder,
            self._gateway,
        )


class ModbusTCPGatewayServer(ProtocolAdapterInterface):
    """Modbus TCP Gateway Server operating on loopback isolated network only.

    The server owns the register table and the TCP listener. Semantic
    validation of a command, the audit trail and the routing into the
    simulation plant are owned by :class:`ProtocolGatewayService`, which
    registers itself as the write router.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5020,
        register_map: dict[int, ModbusRegisterMapSpec] | None = None,
        enabled: bool | None = None,
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
        self.enabled: bool = settings.PROTOCOL_GATEWAY_ENABLED if enabled is None else bool(enabled)

        # Router installed by the gateway service; owns validation, audit and
        # the routing into the simulation.
        self.write_router: Any = None

        # Raw 16-bit register words, indexed by their physical Modbus address.
        self._raw_registers: dict[int, int] = {}
        self._rebuild_raw_registers()

        # TCP listener state.
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tcp_server: _PowerTwinModbusTcpServer | None = None
        self._ready = threading.Event()
        self._start_error: BaseException | None = None
        self._peer: dict[str, Any] = {"peer": "unknown"}

        # Registry of the accepted connections. A connection that is accepted
        # while the listener is closing is invisible to the protocol library's
        # own bookkeeping, so the gateway keeps its own registry and closes
        # every transport before the event loop is torn down.
        self._connection_transports: dict[int, tuple[Any, asyncio.BaseTransport]] = {}
        self._shutting_down: bool = False
        self._connection_counted: bool = False

        self.client_connected: bool = False
        self.client_id: str = "EXTERNAL_CIL_CONTROLLER"

    # ------------------------------------------------------------------ #
    # Connection registry
    # ------------------------------------------------------------------ #

    @property
    def peer_holder(self) -> dict[str, Any]:
        """Return the mutable holder of the last peer address seen."""
        return self._peer

    @property
    def open_connection_count(self) -> int:
        """Return the number of accepted connections that are still open."""
        return len(self._connection_transports)

    @property
    def shutting_down(self) -> bool:
        """Return True while the listener is being shut down."""
        return self._shutting_down

    def register_connection(self, handler: Any, transport: asyncio.BaseTransport) -> None:
        """Register an accepted connection.

        When the listener is already closing, the transport is closed straight
        away: a connection that is accepted during the shutdown must never
        outlive the event loop.
        """
        self._connection_transports[id(handler)] = (handler, transport)
        if self._shutting_down:
            logger.debug("Closing a Modbus TCP connection that was accepted during shutdown.")
            transport.close()

    def unregister_connection(self, handler: Any) -> None:
        """Forget a connection whose transport has been closed."""
        self._connection_transports.pop(id(handler), None)

    def close_connection_transports(self) -> int:
        """Close every accepted connection that is still open.

        The registry entries are *not* removed here: they are removed by
        :meth:`unregister_connection` when the transport reports that the
        connection is lost. The caller can therefore wait until the
        connections are really closed.

        Returns:
            The number of transports that were closed by this call.
        """
        closed = 0
        for _handler, transport in list(self._connection_transports.values()):
            try:
                if not transport.is_closing():
                    transport.close()
                    closed += 1
            except Exception as err:  # noqa: BLE001 - shutdown must never raise
                logger.debug("Closing a Modbus TCP connection transport reported: %s", err)
        return closed

    # ------------------------------------------------------------------ #
    # Register table
    # ------------------------------------------------------------------ #

    def _rebuild_raw_registers(self) -> None:
        """Rebuild the raw register words from the typed register values."""
        self._raw_registers.clear()
        for address, spec in self.register_map.items():
            self._write_raw_registers(address, spec, self.register_values.get(address, 0.0))

    def _write_raw_registers(self, address: int, spec: ModbusRegisterMapSpec, value: float) -> None:
        """Encode a value into the raw register words of a register."""
        words = encode_value(spec.data_type, value, spec.scale_factor)
        for offset, word in enumerate(words):
            self._raw_registers[address + offset] = word

    def read_raw_registers(self, address: int, count: int) -> list[int]:
        """Return the raw register words of a read request.

        Args:
            address: The first register address of the request.
            count: The number of registers requested.

        Returns:
            The raw 16-bit register words.

        Raises:
            ValueError: If the requested range leaves the documented map.
        """
        if count < 1:
            raise ValueError("A read must request at least one register.")

        words: list[int] = []
        for index in range(address, address + count):
            if index not in self._raw_registers:
                raise ValueError(f"Register 0x{index:04X} is not part of the documented map.")
            words.append(self._raw_registers[index])
        return words

    def read_register(self, address: int) -> float | None:
        """Read value from in-memory register table."""
        return self.register_values.get(address, None)

    def update_telemetry_point(self, name: str, value: float, quality: str = "GOOD") -> None:
        """Update in-memory register table from simulation model telemetry.

        A non-finite measurement is rejected: a NaN or an infinity in a
        telemetry register would be read by the external controller as a valid
        plant measurement.
        """
        if name not in self.tag_to_address:
            return
        numeric = float(value)
        if not math.isfinite(numeric):
            logger.warning(
                "Rejected non-finite telemetry '%s' (%s); the register is left unchanged.",
                name,
                quality,
            )
            return
        addr = self.tag_to_address[name]
        spec = self.register_map[addr]
        self.register_values[addr] = numeric
        self._write_raw_registers(addr, spec, numeric)

    # ------------------------------------------------------------------ #
    # Write validation
    # ------------------------------------------------------------------ #

    def process_inbound_write(
        self, address: int, value: float, client_id: str = "EXTERNAL_CIL_CONTROLLER"
    ) -> tuple[bool, str]:
        """Validate and execute inbound Modbus write command from external controller."""
        if math.isnan(value) or math.isinf(value):
            return (False, f"REJECTED_NON_FINITE: Value {value} is non-finite.")

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
        self._write_raw_registers(address, spec, value)
        logger.info("Accepted Modbus write to 0x%04X (%s) = %f", address, spec.name, value)
        return (True, "ACCEPTED")

    def handle_raw_write(
        self,
        address: int,
        values: list[int],
        function_code: int,
        client_id: str | None = None,
    ) -> tuple[bool, str, int]:
        """Validate, route and store a raw Modbus write.

        Args:
            address: The first register address of the write request.
            values: The raw register words supplied by the client.
            function_code: The Modbus function code of the request.
            client_id: Optional override for the audited client identity.

        Returns:
            A tuple of (accepted, reason, modbus_exception_code). The
            exception code is ``0`` when the write was accepted.
        """
        actor = client_id or self.current_client_id

        spec = self.register_map.get(address)
        if spec is None:
            reason = (
                f"REJECTED_INVALID_ADDRESS: Modbus address 0x{address:04X} is not a documented "
                "register start address."
            )
            self._audit_rejection(address, reason, actor)
            return (False, reason, ExceptionResponse.ILLEGAL_ADDRESS)

        expected = registers_for(spec.data_type)
        if len(values) != expected:
            reason = (
                f"REJECTED_INVALID_DATA_TYPE: Register '{spec.name}' (0x{address:04X}) is "
                f"{spec.data_type} and requires exactly {expected} register(s); received "
                f"{len(values)}."
            )
            self._audit_rejection(address, reason, actor)
            return (False, reason, ExceptionResponse.ILLEGAL_VALUE)

        try:
            decoded = decode_value(spec.data_type, values)
        except RegisterDecodeError as err:
            reason = (
                f"REJECTED_INVALID_DATA_TYPE: Register '{spec.name}' (0x{address:04X}) could not "
                f"be decoded as {spec.data_type}: {err.reason}"
            )
            self._audit_rejection(address, reason, actor)
            return (False, reason, ExceptionResponse.ILLEGAL_VALUE)

        if self.write_router is not None:
            accepted, reason = self.write_router.route_write(address, decoded, actor)
        else:
            accepted, reason = self.process_inbound_write(address, decoded, client_id=actor)

        if accepted:
            return (True, reason, 0)

        return (False, reason, _exception_code_for_reason(reason))

    def _audit_rejection(self, address: int, reason: str, client_id: str) -> None:
        """Report a framing-level rejection to the audit owner, if any."""
        if self.write_router is not None:
            self.write_router.audit_rejected_write(address, reason, client_id)

    @property
    def current_client_id(self) -> str:
        """Return the identity of the currently connected external controller."""
        peer = self._peer.get("peer", "unknown")
        if peer and peer != "unknown":
            return f"{self.client_id}@{peer}"
        return self.client_id

    # ------------------------------------------------------------------ #
    # Listener lifecycle
    # ------------------------------------------------------------------ #

    def start(self) -> bool:
        """Start the Modbus TCP listener on the loopback interface.

        Returns:
            True when the listener is bound and serving, False otherwise.
        """
        if self.host not in LOOPBACK_HOSTS:
            msg = f"SAFETY INVARIANT VIOLATION: Refusing to bind host '{self.host}'"
            logger.error(msg)
            return False

        if not self.enabled:
            logger.info(
                "Modbus TCP Gateway is disabled (PROTOCOL_GATEWAY_ENABLED is False); "
                "no socket is opened."
            )
            return False

        if self.is_running:
            return True

        self._ready.clear()
        self._start_error = None
        self._shutting_down = False
        self._connection_counted = False
        self._connection_transports.clear()
        self._thread = threading.Thread(
            target=self._serve, name="PowerTwin-modbus-tcp", daemon=True
        )
        self._thread.start()

        if not self._ready.wait(timeout=5.0):
            logger.error("Modbus TCP Gateway did not report readiness within 5 s.")
            self.stop()
            return False

        if self._start_error is not None:
            logger.error("Modbus TCP Gateway failed to start: %s", self._start_error)
            self.stop()
            return False

        self.is_running = True
        logger.info("Modbus TCP Server started on %s:%d", self.host, self.port)
        return True

    def _serve(self) -> None:
        """Run the pymodbus server on a dedicated event loop in this thread."""

        async def _bootstrap() -> None:
            """Create, bind and serve the listener inside the running event loop.

            ``pymodbus`` resolves the running loop when the server object is
            constructed, so the server must be built from inside the loop.
            Readiness is signalled once the socket is bound, and the coroutine
            then blocks until the shutdown releases the serving future.

            The shutdown itself is performed here, inside the event loop, so
            that a single task drives the whole listener lifecycle. The
            serving future is released by :meth:`stop` from the caller thread;
            the listener and its connections are closed here.
            """
            context = ModbusServerContext(  # type: ignore[no-untyped-call]
                slaves=PowerTwinModbusContext(self), single=True
            )
            identity = ModbusDeviceIdentification(  # type: ignore[no-untyped-call]
                info_name=dict(SERVER_IDENTITY)
            )
            server = _PowerTwinModbusTcpServer(
                context,
                address=(self.host, self.port),
                identity=identity,
                gateway=self,
                trace_connect=self._on_connect_trace,
            )
            self._tcp_server = server
            await server.serve_forever(background=True)
            self._ready.set()
            try:
                await server.serving
            finally:
                await self._shutdown_listener(server)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(_bootstrap())
        except BaseException as err:  # noqa: BLE001 - surfaced through _start_error
            self._start_error = err
        finally:
            self._ready.set()
            try:
                # Drain the loop so that every close callback scheduled by the
                # shutdown runs before the loop is closed, so no transport is
                # finalised against a dead loop.
                loop.run_until_complete(self._drain_loop())
            except Exception as err:  # noqa: BLE001 - best effort cleanup
                logger.debug("Modbus TCP loop drain reported: %s", err)
            if self._connection_transports:
                logger.warning(
                    "%d Modbus TCP connection transport(s) were still open at shutdown.",
                    len(self._connection_transports),
                )
            try:
                loop.close()
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass
            self._loop = None
            self._tcp_server = None
            self.is_running = False

    async def _drain_loop(self, *, until_connections_closed: bool = False) -> None:
        """Let the event loop run its pending callbacks.

        A shutdown is a sequence of deferred callbacks: closing a transport
        only schedules its close notification, and the transport is detached
        from the server object in that notification. The loop therefore has to
        run between the individual steps of the shutdown.

        Args:
            until_connections_closed: When True, the drain stops as soon as
                every accepted connection has reported that it is closed.
        """
        for _ in range(SHUTDOWN_DRAIN_ITERATIONS):
            await asyncio.sleep(0)
            if until_connections_closed and not self._connection_transports:
                return

    def _stop_accepting(self, server: Any) -> None:
        """Stop the listener from accepting new connections.

        The protocol library closes the server object in a single step, and
        that step also invalidates the object for a connection that is being
        accepted at that exact moment: the new transport cannot be attached to
        a closed server, the transport construction fails and the half-built
        transport is leaked.

        Removing the accept callback first keeps the server object valid, so
        an in-flight accept can still be completed and closed. The server
        object itself is closed afterwards, once the pending accepts have
        drained. The listening socket is closed here, so the port is released
        immediately.

        ``loop._stop_serving`` is the exact operation that
        ``asyncio.Server.close`` performs internally; it has been stable since
        Python 3.7. The raw sockets are used rather than
        ``asyncio.Server.sockets``, because the latter returns read-only
        wrappers that deliberately do not expose ``close()``. The call is
        guarded so that a future interpreter that removes it degrades to the
        single-step shutdown instead of failing.
        """
        loop = asyncio.get_running_loop()
        stop_serving = getattr(loop, "_stop_serving", None)
        listener = getattr(server, "transport", None)
        raw_sockets = getattr(listener, "_sockets", None)
        if stop_serving is None or not raw_sockets:  # pragma: no cover - defensive
            logger.warning(
                "The event loop does not expose the accept-callback removal; "
                "the Modbus TCP listener is closed in a single step."
            )
            return

        for sock in raw_sockets:
            try:
                stop_serving(sock)
            except Exception as err:  # noqa: BLE001 - best effort cleanup
                logger.debug("Removing the Modbus TCP accept callback reported: %s", err)

    async def _shutdown_listener(self, server: Any) -> None:
        """Close the listener and its connections inside the event loop.

        The shutdown runs in three ordered phases. The order matters, because
        ``asyncio.Server`` tolerates neither a transport that is attached
        after the server object was closed, nor a transport that is detached
        from the server object after it was closed:

        1. the accept callback is removed. The listening socket is closed, so
           the port is released straight away, but the server object stays
           valid: a connection that was accepted concurrently can still be
           completed and closed instead of failing half-built,
        2. the accepted connections are closed and the loop is drained until
           every connection has reported that it is closed. Every transport is
           detached from the server object while that object is still valid,
        3. the server object is closed.
        """
        self._stop_accepting(server)
        await self._drain_loop()

        self.close_connection_transports()
        await self._drain_loop(until_connections_closed=True)

        server.close()
        await self._drain_loop()

    async def _release_serving(self, server: Any) -> None:
        """Release the serving future so that the shutdown can start.

        The serving future is completed from inside the event loop, which
        resumes the serving coroutine and lets it run the shutdown.
        """
        if not server.serving.done():
            server.serving.set_result(True)

    def _on_connect_trace(self, connected: bool) -> None:
        """Track the connection state of the external controller."""
        if connected:
            # The protocol library reports a connection both when the handler
            # is created and when the connection is established. Only the first
            # report of a connection episode is counted, so that the counter
            # matches the number of real connections.
            if not self._connection_counted:
                self._connection_counted = True
                self.client_connections_count += 1
            self.client_connected = True
            logger.info("External CIL controller connected (%s).", self.current_client_id)
        else:
            self._connection_counted = False
            self.client_connected = False
            logger.warning("External CIL controller disconnected.")

    def stop(self) -> None:
        """Stop the Modbus TCP listener and release the port."""
        loop = self._loop
        server = self._tcp_server
        if loop is not None and server is not None:
            # From this point on a connection that is still accepted by the
            # event loop is closed immediately instead of being left dangling.
            self._shutting_down = True
            try:
                # Releasing the serving future makes the serving coroutine run
                # the shutdown inside the event loop. The shutdown itself
                # completes when the listener thread returns.
                future = asyncio.run_coroutine_threadsafe(self._release_serving(server), loop)
                future.result(timeout=SHUTDOWN_TIMEOUT_S)
            except Exception:  # noqa: BLE001 - shutdown must never raise
                logger.exception("Modbus TCP server shutdown reported a failure.")

        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=SHUTDOWN_TIMEOUT_S)
            if thread.is_alive():
                logger.error(
                    "The Modbus TCP listener thread did not stop within %.1f s.",
                    SHUTDOWN_TIMEOUT_S,
                )

        self._thread = None
        self._loop = None
        self._tcp_server = None
        self.client_connected = False
        self.is_running = False
        logger.info("Modbus TCP Gateway Server stopped.")


def _exception_code_for_reason(reason: str) -> int:
    """Map a rejection reason to the Modbus exception code returned to the client."""
    if reason.startswith("REJECTED_READ_ONLY"):
        return ExceptionResponse.ILLEGAL_ADDRESS
    if reason.startswith("REJECTED_INVALID_ADDRESS"):
        return ExceptionResponse.ILLEGAL_ADDRESS
    if reason.startswith("REJECTED_WRITES_DISABLED"):
        return ExceptionResponse.SLAVE_FAILURE
    if reason.startswith("REJECTED_INVALID_DATA_TYPE"):
        return ExceptionResponse.ILLEGAL_VALUE
    if reason.startswith("REJECTED_OUT_OF_RANGE"):
        return ExceptionResponse.ILLEGAL_VALUE
    if reason.startswith("REJECTED_NON_FINITE"):
        return ExceptionResponse.ILLEGAL_VALUE
    return ExceptionResponse.SLAVE_FAILURE
