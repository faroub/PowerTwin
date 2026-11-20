"""Example External CIL Controller Implementation.

Demonstrates how an external Power Plant Controller (PPC) or Energy Management System (EMS)
connects over the loopback protocol gateway (Modbus TCP 127.0.0.1:5020) to:
  1. Read SCADA telemetry points (Plant P, Q, Voltage, Frequency, SoC).
  2. Send active & reactive power command setpoints to in-memory simulation instances.
  3. Send periodic watchdog heartbeat counter pulses to prevent watchdog timeout trips.

SAFETY WARNING:
  This controller operates strictly on simulation instances via loopback (127.0.0.1:5020).
  Hardware integration remains strictly disabled (HARDWARE_INTEGRATION_ENABLED = False).
"""

import logging
import time

from backend.app.communication.gateway_service import ProtocolGatewayService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ExternalCILController")


class ExternalCILPPCController:
    """External Controller-in-the-Loop PPC Client."""

    def __init__(self, gateway_service: ProtocolGatewayService) -> None:
        self.gateway = gateway_service
        self.heartbeat_counter: int = 0
        self.requestor_id: str = "EXTERNAL_CIL_PPC_V1"

    def run_control_cycle(
        self, target_p_w: float, target_q_var: float, current_time_ns: int
    ) -> None:
        """Execute one control cycle: Read telemetry, update heartbeat, send setpoints."""
        # 1. Read SCADA Telemetry Registers (Read-Only)
        p_mw = self.gateway.modbus_server.read_register(0)
        q_mvar = self.gateway.modbus_server.read_register(2)
        v_kv = self.gateway.modbus_server.read_register(4)
        f_hz = self.gateway.modbus_server.read_register(6)
        soc_pct = self.gateway.modbus_server.read_register(8)

        msg = (
            f"CIL PPC Read Telemetry -> P: {p_mw or 0.0:.2f} MW, Q: {q_mvar or 0.0:.2f} MVAR, "
            f"V: {v_kv or 0.0:.2f} kV, f: {f_hz or 0.0:.2f} Hz, SoC: {soc_pct or 0.0:.1f}%"
        )
        logger.info(msg)

        # 2. Update Watchdog Heartbeat Counter Pulse
        self.heartbeat_counter += 1
        acc_hb, hb_reason = self.gateway.process_external_command(
            requestor=self.requestor_id,
            target_equipment_id="PPC_01",
            address=104,
            value=float(self.heartbeat_counter),
            current_time_ns=current_time_ns,
        )
        if not acc_hb:
            logger.warning("Heartbeat write rejected: %s", hb_reason)

        # 3. Dispatch Active & Reactive Power Setpoints
        acc_p, p_reason = self.gateway.process_external_command(
            requestor=self.requestor_id,
            target_equipment_id="PPC_01",
            address=100,
            value=target_p_w,
            current_time_ns=current_time_ns,
        )

        acc_q, q_reason = self.gateway.process_external_command(
            requestor=self.requestor_id,
            target_equipment_id="PPC_01",
            address=102,
            value=target_q_var,
            current_time_ns=current_time_ns,
        )

        p_status = "ACCEPTED" if acc_p else f"REJECTED: {p_reason}"
        q_status = "ACCEPTED" if acc_q else f"REJECTED: {q_reason}"
        logger.info(
            "CIL PPC Dispatch Setpoints -> P: %.1f MW (%s), Q: %.1f MVAR (%s)",
            target_p_w / 1e6,
            p_status,
            target_q_var / 1e6,
            q_status,
        )


if __name__ == "__main__":
    logger.info("Starting External CIL Controller Demonstration...")
    gateway = ProtocolGatewayService()
    gateway.start_gateway()

    gateway.sync_telemetry_from_plant(
        active_power_mw=4.85,
        reactive_power_mvar=0.50,
        poi_voltage_kv=13.81,
        grid_frequency_hz=50.02,
        average_soc_pct=65.0,
    )

    controller = ExternalCILPPCController(gateway_service=gateway)

    for tick in range(1, 4):
        t_ns = tick * 1_000_000_000
        controller.run_control_cycle(target_p_w=5_000_000.0, target_q_var=0.0, current_time_ns=t_ns)
        time.sleep(0.5)

    gateway.stop_gateway()
    logger.info("CIL Controller Demonstration finished.")
