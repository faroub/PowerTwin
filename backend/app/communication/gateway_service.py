"""Protocol Gateway Service — Isolated External Controller Bridge & CIL Management.

This service owns everything that is *not* protocol framing:

* the semantic validation of an external command,
* the auditable trail of every accepted and rejected command,
* the routing of a command into the internal simulation plant,
* the watchdog that places the simulated plant in a defined safe state when
  the external controller stops communicating.

The service never opens a socket itself: the Modbus TCP listener is owned by
:class:`ModbusTCPGatewayServer`, which calls back into this service for every
write request.
"""

import logging
import time
from typing import Any

from backend.app.communication.modbus_server import ModbusTCPGatewayServer
from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.controllers.ems import EMSMode
from backend.app.core.config import settings
from backend.app.topology.factory import BuiltPlantInstance

logger = logging.getLogger(__name__)

# Modbus register addresses handled by the gateway service.
REGISTER_COMMAND_ACTIVE_POWER_W: int = 100
REGISTER_COMMAND_REACTIVE_POWER_VAR: int = 102
REGISTER_WATCHDOG_HEARTBEAT_COUNTER: int = 104
REGISTER_COMMAND_EMS_MODE: int = 106
REGISTER_COMMAND_RESET_FAULTS: int = 108

# EMS operational mode encoding used by register 106. The numbers match the
# order of the EMSMode enumeration so a controller can select a mode without
# knowing the string names.
EMS_MODE_BY_CODE: dict[int, EMSMode] = {
    0: EMSMode.MANUAL_DISPATCH,
    1: EMSMode.SCHEDULED_PROFILE,
    2: EMSMode.PEAK_SHAVING,
    3: EMSMode.FREQUENCY_RESPONSE,
}


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
        # The gateway service owns validation, audit and plant routing; the
        # Modbus server calls back into it for every write request.
        self.modbus_server.write_router = self

        self.last_heartbeat_ns: int = 0
        self.last_heartbeat_counter: int = 0
        self.comms_dropped: bool = False

        self._heartbeat_seen: bool = False
        self._watchdog_tripped: bool = False
        self._last_command_time_ns: int = 0

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

    # ------------------------------------------------------------------ #
    # Write router (called from the Modbus listener thread)
    # ------------------------------------------------------------------ #

    def route_write(self, address: int, value: float, client_id: str) -> tuple[bool, str]:
        """Validate, execute and audit a write decoded from the Modbus wire.

        This is the entry point used by the Modbus TCP listener. The command
        is applied to the plant under the simulation execution lock, so it can
        never be applied in the middle of a simulation tick.
        """
        timestamp_ns = self._resolve_timestamp_ns()
        target = self._resolve_target_equipment_id()
        return self.process_external_command(
            requestor=client_id,
            target_equipment_id=target,
            address=address,
            value=value,
            current_time_ns=timestamp_ns,
        )

    def audit_rejected_write(self, address: int, reason: str, client_id: str) -> None:
        """Audit a write that was rejected before it could be decoded.

        A write to an undocumented address, or a write whose register count
        does not match the declared data type, never reaches the semantic
        validation path; it is audited here so that no attempt is invisible.
        """
        timestamp_ns = self._resolve_timestamp_ns()
        self._log_audit(
            timestamp_ns,
            client_id,
            self._resolve_target_equipment_id(),
            address,
            0.0,
            CommandStatus.REJECTED_INTERLOCK,
            reason,
        )

    def _resolve_timestamp_ns(self) -> int:
        """Return the authoritative simulation timestamp for an external command.

        The simulation clock is used whenever a plant is bound, so an external
        command carries the same time base as the telemetry it acts on. A
        detached gateway falls back to the wall clock, which is only used for
        the audit trail of a command that cannot touch a plant.
        """
        if self.plant_instance is not None:
            try:
                return int(self.plant_instance.simulation_engine.clock.time_ns)
            except Exception as err:  # noqa: BLE001 - never break the command path
                logger.debug("Simulation clock unavailable for audit timestamp: %s", err)
        return self._last_command_time_ns or time.time_ns()

    def _resolve_target_equipment_id(self) -> str:
        """Return the audit target component for an external command."""
        if self.plant_instance is not None:
            return self.plant_instance.ppc.equipment_id
        return "PPC_MAIN_01"

    # ------------------------------------------------------------------ #
    # Command execution
    # ------------------------------------------------------------------ #

    def process_external_command(
        self,
        requestor: str,
        target_equipment_id: str,
        address: int,
        value: float,
        current_time_ns: int,
    ) -> tuple[bool, str]:
        """Validate, execute, and audit an external controller write command."""
        self._last_command_time_ns = current_time_ns

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

        # 2. Heartbeat sequencing is validated before the register is written:
        #    a repeated or out-of-order heartbeat is a protocol violation and
        #    must never refresh the watchdog.
        if address == REGISTER_WATCHDOG_HEARTBEAT_COUNTER:
            heartbeat_reason = self._validate_heartbeat_sequence(value, current_time_ns)
            if heartbeat_reason is not None:
                self._log_audit(
                    current_time_ns,
                    requestor,
                    target_equipment_id,
                    address,
                    value,
                    CommandStatus.REJECTED_INTERLOCK,
                    heartbeat_reason,
                )
                return (False, heartbeat_reason)

        # 3. Process Modbus Write Register Validation
        accepted, reason = self.modbus_server.process_inbound_write(
            address, value, client_id=requestor
        )

        if not accepted:
            status = CommandStatus.REJECTED_INTERLOCK
            self._log_audit(
                current_time_ns, requestor, target_equipment_id, address, value, status, reason
            )
            return (False, reason)

        # 4. Watchdog Heartbeat Update
        if address == REGISTER_WATCHDOG_HEARTBEAT_COUNTER:
            self.last_heartbeat_ns = current_time_ns
            self.last_heartbeat_counter = int(value)
            self._heartbeat_seen = True
            self._watchdog_tripped = False
            if self.plant_instance is not None:
                self.plant_instance.equipment_controller.update_heartbeat(current_time_ns)

        # 5. Route Command Writes to Plant Dispatch Loop
        accepted_value: dict[str, Any] = {"address": address, "value": value}
        if self.plant_instance is not None:
            accepted_value = self._apply_to_plant(
                address=address,
                value=value,
                current_time_ns=current_time_ns,
            )

        status = CommandStatus.ACCEPTED
        self._log_audit(
            current_time_ns,
            requestor,
            target_equipment_id,
            address,
            value,
            status,
            reason,
            accepted_value=accepted_value,
        )
        return (True, reason)

    def _validate_heartbeat_sequence(self, value: float, current_time_ns: int) -> str | None:
        """Validate the watchdog heartbeat counter and timestamp.

        Returns:
            A rejection reason, or None when the heartbeat is acceptable.
        """
        counter = int(value)
        if self._heartbeat_seen and counter <= self.last_heartbeat_counter:
            return (
                f"REJECTED_STALE_HEARTBEAT: Heartbeat counter {counter} did not advance past "
                f"{self.last_heartbeat_counter}."
            )
        if self._heartbeat_seen and current_time_ns < self.last_heartbeat_ns:
            return (
                f"REJECTED_STALE_HEARTBEAT: Heartbeat timestamp {current_time_ns} precedes the "
                f"last accepted heartbeat {self.last_heartbeat_ns}."
            )
        return None

    def _apply_to_plant(self, address: int, value: float, current_time_ns: int) -> dict[str, Any]:
        """Apply an accepted command to the bound simulation plant.

        The plant is mutated under the simulation execution lock so a command
        can never interleave with a simulation tick.
        """
        plant = self.plant_instance
        if plant is None:
            return {"address": address, "value": value}

        lock = plant.simulation_engine.execution_lock
        with lock:
            if address in (REGISTER_COMMAND_ACTIVE_POWER_W, REGISTER_COMMAND_REACTIVE_POWER_VAR):
                return self._apply_power_setpoint(address, value, current_time_ns)
            if address == REGISTER_COMMAND_EMS_MODE:
                return self._apply_ems_mode(int(value), current_time_ns)
            if address == REGISTER_COMMAND_RESET_FAULTS:
                return self._apply_fault_reset(int(value), current_time_ns)
        return {"address": address, "value": value}

    def _apply_power_setpoint(
        self, address: int, value: float, current_time_ns: int
    ) -> dict[str, Any]:
        """Route a P/Q setpoint through the plant EMS."""
        plant = self.plant_instance
        assert plant is not None  # noqa: S101 - guarded by the caller

        p_set = self.modbus_server.read_register(REGISTER_COMMAND_ACTIVE_POWER_W)
        q_set = self.modbus_server.read_register(REGISTER_COMMAND_REACTIVE_POWER_VAR)
        p_set_val = p_set if p_set is not None else 0.0
        q_set_val = q_set if q_set is not None else 0.0

        acc_p, acc_q = plant.ems.dispatch_step(
            requested_p_w=p_set_val,
            requested_q_var=q_set_val,
            ppc=plant.ppc,
            battery=plant.battery_systems,
            bms_list=plant.bms_units,
            pcs_list=plant.pcs_units,
            equipment_controller=plant.equipment_controller,
            grid_frequency_hz=plant.grid.frequency_hz,
            timestamp_ns=current_time_ns,
        )
        logger.info(
            "Routed Modbus setpoint (P=%.1f MW) -> Accepted (P=%.1f MW, Q=%.1f MVAR)",
            p_set_val / 1e6,
            acc_p / 1e6,
            acc_q / 1e6,
        )
        return {"address": address, "value": value, "accepted_p_w": acc_p, "accepted_q_var": acc_q}

    def _apply_ems_mode(self, mode_code: int, current_time_ns: int) -> dict[str, Any]:
        """Select the EMS operational mode (register 106)."""
        plant = self.plant_instance
        assert plant is not None  # noqa: S101 - guarded by the caller

        mode = EMS_MODE_BY_CODE.get(mode_code)
        if mode is None:
            return {"address": REGISTER_COMMAND_EMS_MODE, "value": mode_code}
        plant.ems.active_mode = mode
        logger.info("External controller selected EMS mode %s.", mode.value)
        self.audit_log.log_entry(
            timestamp_ns=current_time_ns,
            source_layer="EXTERNAL_CIL",
            target_component=plant.ems.equipment_id,
            action_name="SET_EMS_MODE",
            requested_value={"mode_code": mode_code},
            accepted_value={"mode": mode.value},
            status=CommandStatus.ACCEPTED,
            reason="EMS_MODE_CHANGED",
        )
        return {
            "address": REGISTER_COMMAND_EMS_MODE,
            "value": mode_code,
            "mode": mode.value,
        }

    def _apply_fault_reset(self, flag: int, current_time_ns: int) -> dict[str, Any]:
        """Reset the active equipment faults (register 108).

        A value of 1 requests the reset; a value of 0 is a no-op. The reset is
        only performed when the fault condition itself has cleared, which the
        BMS verifies internally.
        """
        plant = self.plant_instance
        assert plant is not None  # noqa: S101 - guarded by the caller

        if int(flag) != 1:
            return {"address": REGISTER_COMMAND_RESET_FAULTS, "value": flag, "reset": False}

        reset_count = 0
        for bms in plant.bms_units:
            if bms.process_command({"reset_faults": True}):
                reset_count += 1

        logger.info("External controller requested a fault reset on %d BMS unit(s).", reset_count)
        self.audit_log.log_entry(
            timestamp_ns=current_time_ns,
            source_layer="EXTERNAL_CIL",
            target_component=plant.equipment_controller.equipment_id,
            action_name="RESET_FAULTS",
            requested_value={"flag": 1},
            accepted_value={"bms_units_reset": reset_count},
            status=CommandStatus.ACCEPTED,
            reason="FAULT_RESET_REQUESTED",
        )
        return {
            "address": REGISTER_COMMAND_RESET_FAULTS,
            "value": flag,
            "reset": True,
            "bms_units_reset": reset_count,
        }

    # ------------------------------------------------------------------ #
    # Watchdog
    # ------------------------------------------------------------------ #

    def check_watchdog_heartbeat(self, current_time_ns: int) -> tuple[bool, str]:
        """Verify external controller watchdog heartbeat is fresh (< 5 seconds).

        When the heartbeat is stale, the simulated plant is placed in a
        defined safe state: the dispatch is driven to zero and the equipment
        controller performs a graceful shutdown into STANDBY. The transition
        happens once per timeout episode.

        The "no heartbeat yet" case is decided by an explicit flag rather than
        by the timestamp, because the simulation clock starts at zero and a
        heartbeat accepted at the very first tick would otherwise be
        indistinguishable from no heartbeat at all.
        """
        if not self._heartbeat_seen:
            return (True, "HEARTBEAT_INITIALIZING")

        elapsed_ns = current_time_ns - self.last_heartbeat_ns
        if elapsed_ns > self.watchdog_timeout_ns:
            msg = f"WATCHDOG_TIMEOUT: Heartbeat stale > {elapsed_ns / 1e9:.1f}s"
            logger.warning(msg)
            if not self._watchdog_tripped:
                self._watchdog_tripped = True
                self.apply_watchdog_safe_state(current_time_ns)
            return (False, msg)

        return (True, "HEARTBEAT_OK")

    def apply_watchdog_safe_state(self, current_time_ns: int) -> bool:
        """Place the simulated plant in the defined safe state.

        The defined safe state is: zero active and reactive power dispatch and
        a graceful equipment shutdown into STANDBY. It is deliberately not an
        emergency stop: an emergency trip is a hardware protection function and
        must never be produced by a software watchdog.

        Returns:
            True when the safe state was applied, False when no plant is bound.
        """
        plant = self.plant_instance
        if plant is None:
            logger.warning("Watchdog timeout with no plant bound; no safe state applied.")
            return False

        lock = plant.simulation_engine.execution_lock
        with lock:
            plant.ems.dispatch_step(
                requested_p_w=0.0,
                requested_q_var=0.0,
                ppc=plant.ppc,
                battery=plant.battery_systems,
                bms_list=plant.bms_units,
                pcs_list=plant.pcs_units,
                equipment_controller=plant.equipment_controller,
                grid_frequency_hz=plant.grid.frequency_hz,
                timestamp_ns=current_time_ns,
            )
            if plant.switchgear:
                plant.equipment_controller.execute_shutdown_sequence(
                    bms_list=plant.bms_units,
                    pcs_list=plant.pcs_units,
                    switchgear=plant.switchgear[0],
                    current_time_ns=current_time_ns,
                )

        self.audit_log.log_entry(
            timestamp_ns=current_time_ns,
            source_layer="EXTERNAL_CIL_WATCHDOG",
            target_component=plant.equipment_controller.equipment_id,
            action_name="WATCHDOG_SAFE_STATE",
            requested_value={"target_state": "STANDBY", "p_w": 0.0, "q_var": 0.0},
            accepted_value={"target_state": "STANDBY", "p_w": 0.0, "q_var": 0.0},
            status=CommandStatus.ACCEPTED,
            reason="WATCHDOG_TIMEOUT_SAFE_STATE_APPLIED",
        )
        logger.warning("Watchdog timeout: simulated plant placed in the safe state (STANDBY).")
        return True

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #

    def _log_audit(
        self,
        current_time_ns: int,
        requestor: str,
        target_equipment_id: str,
        address: int,
        value: float,
        status: CommandStatus,
        reason: str,
        accepted_value: dict[str, Any] | None = None,
    ) -> None:
        """Helper to log external command into traceable audit log."""
        spec = self.modbus_server.register_map.get(address)
        reg_name = spec.name if spec else f"0x{address:04X}"
        if accepted_value is None:
            accepted_value = {"address": address, "value": 0.0}
        self.audit_log.log_entry(
            timestamp_ns=current_time_ns,
            source_layer=f"EXTERNAL_CIL:{requestor}",
            target_component=target_equipment_id,
            action_name=f"WRITE_REGISTER:{reg_name}",
            requested_value={"address": address, "value": value},
            accepted_value=accepted_value,
            status=status,
            reason=reason,
        )
