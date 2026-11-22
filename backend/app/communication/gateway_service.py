"""Protocol Gateway Service — Isolated External Controller Bridge & CIL Management."""

import logging

from backend.app.communication.modbus_server import ModbusTCPGatewayServer
from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.core.config import settings
from backend.app.topology.factory import BuiltPlantInstance

logger = logging.getLogger(__name__)


class ProtocolGatewayService:
    """Protocol Gateway Service managing external protocol adapters, watchdog, and CIL bridge."""

    def __init__(
        self,
        audit_log: ControlCommandLog | None = None,
        watchdog_timeout_ns: int = 5_000_000_000,
        plant_instance: BuiltPlantInstance | None = None,
    ) -> None:
        self.audit_log: ControlCommandLog = (
            audit_log if audit_log is not None else ControlCommandLog()
        )
        self.watchdog_timeout_ns: int = watchdog_timeout_ns
        self.plant_instance: BuiltPlantInstance | None = plant_instance

        self.modbus_server = ModbusTCPGatewayServer(
            host=settings.PROTOCOL_GATEWAY_HOST,
            port=settings.PROTOCOL_GATEWAY_PORT,
        )

        self.last_heartbeat_ns: int = 0
        self.last_heartbeat_counter: int = 0
        self.comms_dropped: bool = False

    def bind_to_plant_instance(self, plant: BuiltPlantInstance) -> None:
        """Bind active plant instance to protocol gateway."""
        self.plant_instance = plant

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
        active_power_mw: float | None = None,
        reactive_power_mvar: float | None = None,
        poi_voltage_kv: float | None = None,
        grid_frequency_hz: float | None = None,
        average_soc_pct: float | None = None,
    ) -> None:
        """Sync simulation plant telemetry to Modbus server register table."""
        if self.comms_dropped:
            return

        if self.plant_instance is not None:
            poi_state = self.plant_instance.poi.get_state()
            p_w = poi_state.measurements.get("active_power_w")
            q_var = poi_state.measurements.get("reactive_power_var")
            v_v = poi_state.measurements.get("voltage_v")
            f_hz = poi_state.measurements.get("frequency_hz")

            p_mw = (p_w.value / 1e6) if p_w else 0.0
            q_mvar = (q_var.value / 1e6) if q_var else 0.0
            v_kv = (v_v.value / 1e3) if v_v else 13.81
            f_val = f_hz.value if f_hz else 50.0

            active_bats = [b for b in self.plant_instance.battery_systems if b.is_available]
            soc_val = (
                sum(b.soc_pct for b in active_bats) / max(1, len(active_bats))
                if active_bats
                else 0.0
            )

            avail_pct = (
                (len(active_bats) / max(1, len(self.plant_instance.battery_systems))) * 100.0
                if self.plant_instance.battery_systems
                else 100.0
            )

            alarms_cnt = sum(len(b.active_alarms) for b in self.plant_instance.battery_systems)

            self.modbus_server.update_telemetry_point("PLANT_ACTIVE_POWER_MW", p_mw)
            self.modbus_server.update_telemetry_point("PLANT_REACTIVE_POWER_MVAR", q_mvar)
            self.modbus_server.update_telemetry_point("POI_VOLTAGE_KV", v_kv)
            self.modbus_server.update_telemetry_point("GRID_FREQUENCY_HZ", f_val)
            self.modbus_server.update_telemetry_point("AVERAGE_SOC_PCT", soc_val)
            self.modbus_server.update_telemetry_point("EQUIPMENT_AVAILABILITY_PCT", avail_pct)
            self.modbus_server.update_telemetry_point("ACTIVE_ALARMS_COUNT", float(alarms_cnt))
        else:
            if active_power_mw is not None:
                self.modbus_server.update_telemetry_point("PLANT_ACTIVE_POWER_MW", active_power_mw)
            if reactive_power_mvar is not None:
                self.modbus_server.update_telemetry_point(
                    "PLANT_REACTIVE_POWER_MVAR", reactive_power_mvar
                )
            if poi_voltage_kv is not None:
                self.modbus_server.update_telemetry_point("POI_VOLTAGE_KV", poi_voltage_kv)
            if grid_frequency_hz is not None:
                self.modbus_server.update_telemetry_point("GRID_FREQUENCY_HZ", grid_frequency_hz)
            if average_soc_pct is not None:
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

        # 2. Process Modbus Write Register Validation
        accepted, reason = self.modbus_server.process_inbound_write(
            address, value, client_id=requestor
        )

        if not accepted:
            status = CommandStatus.REJECTED_INTERLOCK
            self._log_audit(
                current_time_ns, requestor, target_equipment_id, address, value, status, reason
            )
            return (False, reason)

        # 3. Watchdog Heartbeat Update
        if address == 104:
            self.last_heartbeat_ns = current_time_ns
            self.last_heartbeat_counter = int(value)
            if self.plant_instance is not None:
                self.plant_instance.equipment_controller.update_heartbeat(current_time_ns)

        # 4. Route Command Writes to Plant Dispatch Loop
        if self.plant_instance is not None:
            if address in (100, 102):
                p_set = self.modbus_server.read_register(100) if address == 102 else value
                q_set = self.modbus_server.read_register(102) if address == 100 else value
                p_set_val = p_set if p_set is not None else 0.0
                q_set_val = q_set if q_set is not None else 0.0

                acc_p, acc_q = self.plant_instance.ems.dispatch_step(
                    requested_p_w=p_set_val,
                    requested_q_var=q_set_val,
                    ppc=self.plant_instance.ppc,
                    battery=self.plant_instance.battery_systems,
                    bms_list=self.plant_instance.bms_units,
                    pcs_list=self.plant_instance.pcs_units,
                    equipment_controller=self.plant_instance.equipment_controller,
                    grid_frequency_hz=self.plant_instance.grid.frequency_hz,
                    timestamp_ns=current_time_ns,
                )
                logger.info(
                    "Routed Modbus setpoint (P=%.1f MW) -> Accepted (P=%.1f MW, Q=%.1f MVAR)",
                    p_set_val / 1e6,
                    acc_p / 1e6,
                    acc_q / 1e6,
                )

        status = CommandStatus.ACCEPTED
        self._log_audit(
            current_time_ns, requestor, target_equipment_id, address, value, status, reason
        )
        return (True, reason)

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
