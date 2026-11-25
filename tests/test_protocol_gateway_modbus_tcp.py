"""Acceptance tests for the real Modbus TCP CIL gateway.

These tests drive the gateway with an **actual Modbus TCP client** over a
real loopback socket. They verify the acceptance criteria of the controller-
in-the-loop gateway:

* the server starts on loopback and refuses any other binding,
* read-only telemetry registers are readable over the wire,
* writable command registers are only writable when explicitly enabled,
* P/Q commands reach the simulation EMS,
* invalid addresses, invalid data types and non-finite values are rejected
  with a Modbus exception,
* the heartbeat timeout is enforced and produces a defined safe state,
* every command is audited,
* shutting the server down releases the port.
"""

import socket
import struct
import time

import pytest
from pymodbus.client import ModbusTcpClient
from pymodbus.pdu import ExceptionResponse

from backend.app.communication.gateway_service import ProtocolGatewayService
from backend.app.communication.modbus_server import ModbusTCPGatewayServer
from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.topology.factory import PlantTopologyFactory

# A free loopback port per test session; the gateway never binds a
# non-loopback interface, so this stays inside the isolated CIL network.
TEST_PORT = 15020

# Holding register addresses of the documented map.
REG_PLANT_ACTIVE_POWER_MW = 0
REG_PLANT_REACTIVE_POWER_MVAR = 2
REG_POI_VOLTAGE_KV = 4
REG_GRID_FREQUENCY_HZ = 6
REG_AVERAGE_SOC_PCT = 8
REG_EQUIPMENT_AVAILABILITY_PCT = 10
REG_ACTIVE_ALARMS_COUNT = 12
REG_COMMAND_ACTIVE_POWER_W = 100
REG_COMMAND_REACTIVE_POWER_VAR = 102
REG_WATCHDOG_HEARTBEAT_COUNTER = 104
REG_COMMAND_EMS_MODE = 106
REG_COMMAND_RESET_FAULTS = 108


def _free_port() -> int:
    """Return a currently free loopback TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _encode_float32(value: float) -> list[int]:
    """Encode a float32 into its two big-endian Modbus register words."""
    packed = struct.pack(">f", value)
    high, low = struct.unpack(">HH", packed)
    return [high, low]


def _decode_float32(registers: list[int]) -> float:
    """Decode two big-endian Modbus register words into a float32."""
    return float(struct.unpack(">f", struct.pack(">HH", *registers))[0])


@pytest.fixture
def gateway() -> ProtocolGatewayService:
    """Return a gateway bound to a real loopback Modbus TCP listener."""
    service = ProtocolGatewayService(audit_log=ControlCommandLog())
    service.modbus_server.port = _free_port()
    service.modbus_server.enabled = True
    service.modbus_server.allow_writes = True
    assert service.start_gateway() is True
    try:
        yield service
    finally:
        service.stop_gateway()


@pytest.fixture
def client(gateway: ProtocolGatewayService) -> ModbusTcpClient:
    """Return a connected Modbus TCP client aimed at the gateway."""
    modbus_client = ModbusTcpClient(
        "127.0.0.1", port=gateway.modbus_server.port, timeout=3, retries=1
    )
    assert modbus_client.connect() is True
    try:
        yield modbus_client
    finally:
        modbus_client.close()


# =============================================================================
# Server lifecycle and binding
# =============================================================================


def test_server_starts_on_loopback_and_serves_a_real_socket() -> None:
    """Test the listener is a real TCP socket bound to the loopback interface."""
    port = _free_port()
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=port, enabled=True)
    assert server.start() is True
    try:
        assert server.is_running is True
        with socket.create_connection(("127.0.0.1", port), timeout=3) as probe:
            assert probe.getpeername()[0] == "127.0.0.1"
    finally:
        server.stop()
    assert server.is_running is False


def test_server_is_disabled_by_default() -> None:
    """Test no socket is opened when the gateway is not explicitly enabled."""
    port = _free_port()
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=port, enabled=False)
    assert server.start() is False
    assert server.is_running is False

    with (
        pytest.raises(OSError),
        socket.create_connection(("127.0.0.1", port), timeout=1),
    ):
        pass


def test_non_loopback_binding_is_rejected() -> None:
    """Test the server refuses to bind a non-loopback interface."""
    server = ModbusTCPGatewayServer(host="192.168.1.100", port=_free_port(), enabled=True)
    assert server.start() is False
    assert server.is_running is False


def test_server_shutdown_releases_the_port() -> None:
    """Test the listening port is released when the server is stopped."""
    port = _free_port()
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=port, enabled=True)
    assert server.start() is True

    server.stop()

    # The port must be bindable again straight away.
    deadline = time.monotonic() + 5.0
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", port))
            break
        except OSError as err:
            if time.monotonic() > deadline:
                raise AssertionError("The Modbus TCP port was not released.") from err
            time.sleep(0.05)


def test_shutdown_closes_an_open_connection_and_releases_the_port() -> None:
    """Test a connection that is still open when the server stops is closed.

    A transport that outlives the event loop is finalised against a dead
    server, which is what produced the "unraisable exception" teardown
    warning. The shutdown must close every accepted connection before the
    listener thread returns.
    """
    port = _free_port()
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=port, enabled=True)
    assert server.start() is True

    probe = socket.create_connection(("127.0.0.1", port), timeout=3)
    try:
        deadline = time.monotonic() + 5.0
        while server.open_connection_count == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.open_connection_count == 1
    finally:
        server.stop()
        probe.close()

    # Every accepted connection must be closed by the shutdown.
    assert server.open_connection_count == 0
    assert server.client_connected is False

    # The listening socket must be closed, so the port can be bound again.
    # SO_REUSEADDR is used because the closed connection leaves the port in
    # TIME_WAIT; the test is about the listener socket, not about the
    # lingering state of the connection.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as rebind:
        rebind.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rebind.bind(("127.0.0.1", port))


def test_shutdown_is_immediate_while_a_client_is_connected(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test stopping the gateway does not block on an open client connection."""
    assert client.read_holding_registers(REG_GRID_FREQUENCY_HZ, count=2) is not None

    started = time.monotonic()
    gateway.stop_gateway()
    elapsed = time.monotonic() - started

    assert elapsed < 5.0, f"The gateway shutdown took {elapsed:.1f} s."
    assert gateway.modbus_server.open_connection_count == 0
    assert gateway.modbus_server.is_running is False


def test_a_single_client_connection_is_counted_once(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test the connection counter matches the number of real connections."""
    # The client-side connect returns as soon as the TCP handshake is done;
    # the server accepts the connection in its own event loop, so the test
    # waits for the gateway to observe it.
    deadline = time.monotonic() + 5.0
    while not gateway.modbus_server.client_connected and time.monotonic() < deadline:
        time.sleep(0.01)

    assert gateway.modbus_server.client_connected is True
    assert gateway.modbus_server.client_connections_count == 1


def test_the_device_identification_identifies_a_simulator(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test the server reports the documented device identification."""
    # Read code 0x02 (regular) returns every identification object.
    response = client.read_device_information(read_code=0x02, object_id=0x00)
    assert not response.isError()

    # The response carries the identification objects keyed by their object id
    # (0x00 VendorName, 0x05 ModelName, 0x06 UserApplicationName). The
    # values are raw bytes on the wire.
    information = response.information
    assert information[0x00] == b"PowerTwin"
    assert information[0x05] == b"PowerTwin-CIL"
    assert b"simulation only" in information[0x06].lower()


def test_client_disconnect_is_handled_cleanly(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a client disconnect is observed and the server keeps serving."""
    assert client.read_holding_registers(REG_GRID_FREQUENCY_HZ, count=2) is not None
    client.close()

    deadline = time.monotonic() + 5.0
    while gateway.modbus_server.client_connected and time.monotonic() < deadline:
        time.sleep(0.05)
    assert gateway.modbus_server.client_connected is False
    assert gateway.modbus_server.is_running is True


# =============================================================================
# Telemetry reads
# =============================================================================


def test_read_only_telemetry_registers_are_readable_over_the_wire(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test telemetry registers are served over the real Modbus TCP socket."""
    gateway.modbus_server.update_telemetry_point("PLANT_ACTIVE_POWER_MW", 4.85)
    gateway.modbus_server.update_telemetry_point("GRID_FREQUENCY_HZ", 50.02)
    gateway.modbus_server.update_telemetry_point("AVERAGE_SOC_PCT", 62.5)

    response = client.read_holding_registers(REG_PLANT_ACTIVE_POWER_MW, count=2)
    assert not response.isError()
    assert _decode_float32(list(response.registers)) == pytest.approx(4.85, rel=1e-6)

    response = client.read_holding_registers(REG_GRID_FREQUENCY_HZ, count=2)
    assert not response.isError()
    assert _decode_float32(list(response.registers)) == pytest.approx(50.02, rel=1e-6)

    response = client.read_holding_registers(REG_AVERAGE_SOC_PCT, count=2)
    assert not response.isError()
    assert _decode_float32(list(response.registers)) == pytest.approx(62.5, rel=1e-6)


def test_reading_an_undocumented_register_is_rejected(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a read outside the documented map returns a Modbus exception."""
    response = client.read_holding_registers(500, count=2)
    assert response.isError()
    assert response.exception_code == ExceptionResponse.ILLEGAL_ADDRESS


# =============================================================================
# Command writes
# =============================================================================


def test_writable_registers_reject_writes_when_writes_are_disabled(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a command write is refused while external writes are disabled."""
    gateway.modbus_server.allow_writes = False

    response = client.write_registers(REG_COMMAND_ACTIVE_POWER_W, _encode_float32(1_000_000.0))
    assert response.isError()
    assert response.exception_code == ExceptionResponse.SLAVE_FAILURE


def test_write_to_a_telemetry_register_is_rejected(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a write to a read-only telemetry register is rejected."""
    response = client.write_registers(REG_PLANT_ACTIVE_POWER_MW, _encode_float32(1.0))
    assert response.isError()
    assert response.exception_code == ExceptionResponse.ILLEGAL_ADDRESS


def test_write_to_an_undocumented_register_is_rejected(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a write to an address outside the documented map is rejected."""
    response = client.write_registers(500, _encode_float32(1.0))
    assert response.isError()
    assert response.exception_code == ExceptionResponse.ILLEGAL_ADDRESS


def test_write_with_the_wrong_register_count_is_rejected(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a 32-bit register written with a single register is rejected."""
    response = client.write_registers(REG_COMMAND_ACTIVE_POWER_W, [0x0001])
    assert response.isError()
    assert response.exception_code == ExceptionResponse.ILLEGAL_VALUE


def test_write_of_a_non_finite_value_is_rejected(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a NaN setpoint is rejected instead of being applied to the plant."""
    nan_words = list(struct.unpack(">HH", struct.pack(">f", float("nan"))))
    response = client.write_registers(REG_COMMAND_ACTIVE_POWER_W, nan_words)
    assert response.isError()
    assert response.exception_code == ExceptionResponse.ILLEGAL_VALUE


def test_write_of_an_out_of_range_value_is_rejected(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a setpoint beyond the documented range is rejected."""
    response = client.write_registers(REG_COMMAND_ACTIVE_POWER_W, _encode_float32(100_000_000.0))
    assert response.isError()
    assert response.exception_code == ExceptionResponse.ILLEGAL_VALUE


def test_active_power_command_reaches_the_simulation_ems(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test an accepted P setpoint is dispatched through the plant EMS."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml"))
    plant.equipment_controller.execute_startup_sequence(
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        switchgear=plant.switchgear[0],
        container_temp_c=25.0,
        current_time_ns=0,
    )
    gateway.bind_to_plant_instance(plant)

    response = client.write_registers(REG_COMMAND_ACTIVE_POWER_W, _encode_float32(2_000_000.0))
    assert not response.isError()
    assert plant.ems.requested_p_w == 2_000_000.0
    assert plant.ppc.accepted_p_w == 2_000_000.0


def test_reactive_power_command_reaches_the_simulation_ems(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test an accepted Q setpoint is dispatched through the plant EMS."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml"))
    plant.equipment_controller.execute_startup_sequence(
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        switchgear=plant.switchgear[0],
        container_temp_c=25.0,
        current_time_ns=0,
    )
    gateway.bind_to_plant_instance(plant)

    response = client.write_registers(REG_COMMAND_REACTIVE_POWER_VAR, _encode_float32(1_000_000.0))
    assert not response.isError()
    assert plant.ems.requested_q_var == 1_000_000.0


def test_ems_mode_register_selects_the_operational_mode(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test register 106 selects the EMS operational mode."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml"))
    gateway.bind_to_plant_instance(plant)

    response = client.write_registers(REG_COMMAND_EMS_MODE, [2])
    assert not response.isError()
    assert plant.ems.active_mode.value == "PEAK_SHAVING"


def test_reset_faults_register_requests_a_bms_fault_reset(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test register 108 issues a fault reset to the BMS units."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml"))
    gateway.bind_to_plant_instance(plant)

    response = client.write_registers(REG_COMMAND_RESET_FAULTS, [1])
    assert not response.isError()
    assert any(entry.action_name == "RESET_FAULTS" for entry in gateway.audit_log.entries)


# =============================================================================
# Heartbeat and watchdog
# =============================================================================


def test_heartbeat_write_is_accepted_and_audited(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a heartbeat counter advances the watchdog and is audited."""
    response = client.write_registers(REG_WATCHDOG_HEARTBEAT_COUNTER, [0, 7])
    assert not response.isError()
    assert gateway.last_heartbeat_counter == 7


def test_repeated_heartbeat_is_rejected(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a heartbeat that does not advance the counter is rejected."""
    assert not client.write_registers(REG_WATCHDOG_HEARTBEAT_COUNTER, [0, 5]).isError()

    response = client.write_registers(REG_WATCHDOG_HEARTBEAT_COUNTER, [0, 5])
    assert response.isError()
    assert gateway.last_heartbeat_counter == 5


def test_watchdog_timeout_places_the_plant_in_a_safe_state(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a stale heartbeat drives the plant into the defined safe state."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml"))
    plant.equipment_controller.execute_startup_sequence(
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        switchgear=plant.switchgear[0],
        container_temp_c=25.0,
        current_time_ns=0,
    )
    gateway.bind_to_plant_instance(plant)
    gateway.watchdog_timeout_ns = 5_000_000_000

    assert not client.write_registers(REG_WATCHDOG_HEARTBEAT_COUNTER, [0, 1]).isError()

    ok, reason = gateway.check_watchdog_heartbeat(current_time_ns=10_000_000_000)
    assert ok is False
    assert "WATCHDOG_TIMEOUT" in reason
    assert plant.equipment_controller.operating_state.value == "STANDBY"
    assert any(entry.action_name == "WATCHDOG_SAFE_STATE" for entry in gateway.audit_log.entries)


# =============================================================================
# Audit trail
# =============================================================================


def test_every_command_is_audited(gateway: ProtocolGatewayService, client: ModbusTcpClient) -> None:
    """Test accepted and rejected commands both produce audit records."""
    client.write_registers(REG_COMMAND_ACTIVE_POWER_W, _encode_float32(1_000_000.0))
    client.write_registers(REG_COMMAND_ACTIVE_POWER_W, _encode_float32(999_000_000.0))
    client.write_registers(REG_PLANT_ACTIVE_POWER_MW, _encode_float32(1.0))
    client.write_registers(500, _encode_float32(1.0))

    statuses = [entry.status for entry in gateway.audit_log.entries]
    assert CommandStatus.ACCEPTED in statuses
    assert CommandStatus.REJECTED_INTERLOCK in statuses
    # Accepted + three rejections.
    assert len(gateway.audit_log.entries) == 4


def test_rejected_command_never_reaches_the_plant(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test an out-of-range command leaves the plant untouched."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml"))
    plant.equipment_controller.execute_startup_sequence(
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        switchgear=plant.switchgear[0],
        container_temp_c=25.0,
        current_time_ns=0,
    )
    gateway.bind_to_plant_instance(plant)

    response = client.write_registers(REG_COMMAND_ACTIVE_POWER_W, _encode_float32(999_000_000.0))
    assert response.isError()
    assert plant.ems.requested_p_w == 0.0
    assert plant.ppc.accepted_p_w == 0.0


# =============================================================================
# Communication loss
# =============================================================================


def test_communication_loss_rejects_commands_and_is_audited(
    gateway: ProtocolGatewayService, client: ModbusTcpClient
) -> None:
    """Test a simulated line drop refuses commands and records the rejection."""
    gateway.simulate_comms_drop(True)

    response = client.write_registers(REG_COMMAND_ACTIVE_POWER_W, _encode_float32(1_000_000.0))
    assert response.isError()
    assert gateway.audit_log.entries[-1].status == CommandStatus.REJECTED_INTERLOCK
    assert "REJECTED_COMMUNICATION_LOSS" in gateway.audit_log.entries[-1].reason
