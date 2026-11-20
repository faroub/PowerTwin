"""Protocol Gateway Service — Isolated External Controller Bridge & CIL Management."""

import logging

from backend.app.communication.modbus_server import ModbusTCPGatewayServer
from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class ProtocolGatewayService:
    """Protocol Gateway Service managing external protocol adapters, watchdog, and CIL bridge."""

    def __init__(
        self,
        audit_log: ControlCommandLog | None = None,
        watchdog_timeout_ns: int = 5_000_000_000,
    ) -> None:
        self.audit_log: ControlCommandLog = (
            audit_log if audit_log is not None else ControlCommandLog()
        )
        self.watchdog_timeout_ns: int = watchdog_timeout_ns

        self.modbus_server = ModbusTCPGatewayServer(
            host=settings.PROTOCOL_GATEWAY_HOST,
            port=settings.PROTOCOL_GATEWAY_PORT,
        )

        self.last_heartbeat_ns: int = 0
        self.last_heartbeat_counter: int = 0
        self.comms_dropped: bool = False

    def start_gateway(self) -> bool:
        """Start protocol gateway servers on isolated loopback adapter."""
        return self.modbus_server.start()

    def stop_gateway(self) -> None:
        """Stop protocol gateway servers."""
        self.modbus_server.stop()

    def simulate_comms_drop(self, is_dropped: bool = True) -> None:
        """Simulate communication line drop / connection loss."""
        self.comms_dropped = is_dropped
        if is_dropped:
            logger.warning("Simulated external communication line drop ACTIVATED.")
        else:
            logger.info("Simulated external communication line RESTORED.")

    def sync_telemetry_from_plant(
        self,
        active_power_mw: float,
        reactive_power_mvar: float,
        poi_voltage_kv: float,
        grid_frequency_hz: float,
        average_soc_pct: float,
    ) -> None:
        """Sync simulation plant telemetry to Modbus server register table."""
        if self.comms_dropped:
            return

        self.modbus_server.update_telemetry_point("PLANT_ACTIVE_POWER_MW", active_power_mw)
        self.modbus_server.update_telemetry_point("PLANT_REACTIVE_POWER_MVAR", reactive_power_mvar)
        self.modbus_server.update_telemetry_point("POI_VOLTAGE_KV", poi_voltage_kv)
        self.modbus_server.update_telemetry_point("GRID_FREQUENCY_HZ", grid_frequency_hz)
        self.modbus_server.update_telemetry_point("AVERAGE_SOC_PCT", average_soc_pct)

    def process_external_command(
        self,
        requestor: str,
        target_equipment_id: str,
        address: int,
        value: float,
        current_time_ns: int,
    ) -> tuple[bool, str]:
        """Validate, execute, and audit an external controller write command."""
        # 1. Comms Drop Check
        if self.comms_dropped:
            reason = "REJECTED_COMMUNICATION_LOSS: External communication line is offline."
            self._log_audit(
                current_time_ns,
                requestor,
                target_equipment_id,
                address,
                value,
                CommandStatus.REJECTED_INTERLOCK,
                reason,
            )
            return (False, reason)

        # 2. Process Modbus Write
        accepted, reason = self.modbus_server.process_inbound_write(
            address, value, client_id=requestor
        )

        # 3. Watchdog Heartbeat Update
        if accepted and address == 104:
            self.last_heartbeat_ns = current_time_ns
            self.last_heartbeat_counter = int(value)

        status = CommandStatus.ACCEPTED if accepted else CommandStatus.REJECTED_INTERLOCK
        self._log_audit(
            current_time_ns, requestor, target_equipment_id, address, value, status, reason
        )
        return (accepted, reason)

    def check_watchdog_heartbeat(self, current_time_ns: int) -> tuple[bool, str]:
        """Verify external controller watchdog heartbeat is fresh (< 5 seconds)."""
        if self.last_heartbeat_ns == 0:
            return (True, "HEARTBEAT_INITIALIZING")

        elapsed_ns = current_time_ns - self.last_heartbeat_ns
        if elapsed_ns > self.watchdog_timeout_ns:
            msg = f"WATCHDOG_TIMEOUT: Heartbeat stale > {elapsed_ns / 1e9:.1f}s"
            logger.warning(msg)
            return (False, msg)

        return (True, "HEARTBEAT_OK")

    def _log_audit(
        self,
        current_time_ns: int,
        requestor: str,
        target_equipment_id: str,
        address: int,
        value: float,
        status: CommandStatus,
        reason: str,
    ) -> None:
        """Helper to log external command into traceable audit log."""
        spec = self.modbus_server.register_map.get(address)
        reg_name = spec.name if spec else f"0x{address:04X}"
        acc_val = value if status == CommandStatus.ACCEPTED else 0.0
        self.audit_log.log_entry(
            timestamp_ns=current_time_ns,
            source_layer=f"EXTERNAL_CIL:{requestor}",
            target_component=target_equipment_id,
            action_name=f"WRITE_REGISTER:{reg_name}",
            requested_value={"address": address, "value": value},
            accepted_value={"address": address, "value": acc_val},
            status=status,
            reason=reason,
        )
