"""Automated Unit & Integration Tests for Isolated Protocol Gateway and CIL Modbus TCP."""

import math

from backend.app.communication.gateway_service import ProtocolGatewayService
from backend.app.communication.modbus_server import ModbusTCPGatewayServer
from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.topology.factory import PlantTopologyFactory


def test_modbus_server_read_only_telemetry() -> None:
    """Test reading telemetry registers from Modbus TCP server."""
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=5020)
    server.start()

    server.update_telemetry_point("PLANT_ACTIVE_POWER_MW", 4.85)
    server.update_telemetry_point("GRID_FREQUENCY_HZ", 50.02)

    assert server.read_register(0) == 4.85
    assert server.read_register(6) == 50.02
    server.stop()


def test_modbus_non_loopback_binding_rejection() -> None:
    """Test safety invariant: Modbus server refuses to bind non-loopback host interfaces."""
    server = ModbusTCPGatewayServer(host="192.168.1.100", port=5020)
    started = server.start()
    assert started is False
    assert server.is_running is False


def test_modbus_write_rejection_when_writes_disabled() -> None:
    """Test safety invariant: Modbus writes are rejected when ALLOW_EXTERNAL_MODBUS_WRITES is False."""
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=5020)
    server.allow_writes = False

    accepted, reason = server.process_inbound_write(address=100, value=5_000_000.0)
    assert accepted is False
    assert "REJECTED_WRITES_DISABLED" in reason


def test_modbus_write_read_only_register_rejection() -> None:
    """Test writing to read-only telemetry register (address 0) is rejected."""
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=5020)
    server.allow_writes = True

    accepted, reason = server.process_inbound_write(address=0, value=10.0)
    assert accepted is False
    assert "REJECTED_READ_ONLY" in reason


def test_modbus_write_non_finite_rejection() -> None:
    """Test writing non-finite NaN / Inf values is rejected."""
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=5020)
    server.allow_writes = True

    accepted, reason = server.process_inbound_write(address=100, value=math.nan)
    assert accepted is False
    assert "REJECTED_NON_FINITE" in reason


def test_modbus_write_out_of_range_rejection() -> None:
    """Test write commands exceeding max limits are rejected."""
    server = ModbusTCPGatewayServer(host="127.0.0.1", port=5020)
    server.allow_writes = True

    accepted, reason = server.process_inbound_write(address=100, value=100_000_000.0)
    assert accepted is False
    assert "REJECTED_OUT_OF_RANGE" in reason


def test_watchdog_heartbeat_timeout_handling() -> None:
    """Test external controller watchdog heartbeat timeout (> 5 seconds)."""
    audit_log = ControlCommandLog()
    gateway = ProtocolGatewayService(
        audit_log=audit_log, watchdog_timeout_ns=5_000_000_000
    )
    gateway.modbus_server.allow_writes = True

    acc, _ = gateway.process_external_command(
        requestor="CIL_PPC",
        target_equipment_id="PPC_01",
        address=104,
        value=1.0,
        current_time_ns=1_000_000_000,
    )
    assert acc is True

    ok, _ = gateway.check_watchdog_heartbeat(current_time_ns=3_000_000_000)
    assert ok is True

    stale_ok, msg = gateway.check_watchdog_heartbeat(current_time_ns=7_000_000_000)
    assert stale_ok is False
    assert "WATCHDOG_TIMEOUT" in msg


def test_modbus_command_forwarding_to_plant_simulation() -> None:
    """Test end-to-end command forwarding from Modbus write to plant simulation response."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(
        factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml")
    )

    plant.equipment_controller.execute_startup_sequence(
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        switchgear=plant.switchgear[0],
        container_temp_c=25.0,
        current_time_ns=0,
    )

    gateway = ProtocolGatewayService(plant_instance=plant)
    gateway.modbus_server.allow_writes = True

    acc, _reason = gateway.process_external_command(
        requestor="CIL_CONTROLLER_TEST",
        target_equipment_id="PPC_MAIN_01",
        address=100,
        value=2_000_000.0,
        current_time_ns=10_000_000,
    )
    assert acc is True
    assert plant.ppc.accepted_p_w == 2_000_000.0
    assert plant.pcs_units[0].requested_p_w == 500_000.0


def test_communication_loss_simulation() -> None:
    """Test simulated communication line drop rejects commands."""
    audit_log = ControlCommandLog()
    gateway = ProtocolGatewayService(audit_log=audit_log)
    gateway.modbus_server.allow_writes = True

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
