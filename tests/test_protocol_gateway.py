"""Automated Unit & Integration Tests for WP12 External Protocol Gateway."""

from backend.app.communication.gateway_service import ProtocolGatewayService
from backend.app.communication.modbus_server import ModbusTCPGatewayServer
from backend.app.controllers.command_log import CommandStatus, ControlCommandLog


def test_modbus_server_read_only_telemetry() -> None:
    """Test reading telemetry registers from Modbus TCP server."""
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=5020)
    server.start()

    server.update_telemetry_point("PLANT_ACTIVE_POWER_MW", 4.85)
    server.update_telemetry_point("GRID_FREQUENCY_HZ", 50.02)

    assert server.read_register(0) == 4.85
    assert server.read_register(6) == 50.02
    server.stop()


def test_modbus_write_rejection_when_writes_disabled() -> None:
    """Test safety invariant: Modbus writes are rejected when ALLOW_EXTERNAL_MODBUS_WRITES is False."""
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=5020)
    server.allow_writes = False  # Disabled by default

    accepted, reason = server.process_inbound_write(address=100, value=5_000_000.0)
    assert accepted is False
    assert "REJECTED_WRITES_DISABLED" in reason


def test_modbus_write_out_of_range_rejection() -> None:
    """Test write commands exceeding max limits are rejected."""
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=5020)
    server.allow_writes = True

    # Max limit is 50 MW. Attempting +100 MW write -> Rejected
    accepted, reason = server.process_inbound_write(address=100, value=100_000_000.0)
    assert accepted is False
    assert "REJECTED_OUT_OF_RANGE" in reason


def test_watchdog_heartbeat_timeout_handling() -> None:
    """Test external controller watchdog heartbeat timeout (> 5 seconds)."""
    audit_log = ControlCommandLog()
    gateway = ProtocolGatewayService(audit_log=audit_log, watchdog_timeout_ns=5_000_000_000)
    gateway.modbus_server.allow_writes = True

    # Heartbeat pulse at t=1,000,000,000 ns (1s)
    acc, _ = gateway.process_external_command(
        requestor="CIL_PPC",
        target_equipment_id="PPC_01",
        address=104,
        value=1.0,
        current_time_ns=1_000_000_000,
    )
    assert acc is True

    # Check heartbeat at t=3,000,000,000 ns (2s elapsed) -> OK
    ok, _ = gateway.check_watchdog_heartbeat(current_time_ns=3_000_000_000)
    assert ok is True

    # Check heartbeat at t=7,000,000,000 ns (6s elapsed > 5s timeout) -> Timeout!
    stale_ok, msg = gateway.check_watchdog_heartbeat(current_time_ns=7_000_000_000)
    assert stale_ok is False
    assert "WATCHDOG_TIMEOUT" in msg


def test_communication_loss_simulation() -> None:
    """Test simulated communication line drop rejects commands."""
    audit_log = ControlCommandLog()
    gateway = ProtocolGatewayService(audit_log=audit_log)
    gateway.modbus_server.allow_writes = True

    # Simulate comms drop
    gateway.simulate_comms_drop(True)

    acc, reason = gateway.process_external_command(
        requestor="CIL_PPC",
        target_equipment_id="PPC_01",
        address=100,
        value=5_000_000.0,
        current_time_ns=1_000_000_000,
    )

    assert acc is False
    assert "REJECTED_COMMUNICATION_LOSS" in reason
    assert audit_log.entries[-1].status == CommandStatus.REJECTED_INTERLOCK
