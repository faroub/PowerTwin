"""Plant Electrical Network Integration Model.

Connects BatterySystem -> PCS -> Transformer -> Switchgear -> POI -> Grid.
"""

from backend.app.models.battery.system import GenericBatterySystemModel
from backend.app.models.bop.switchgear import GenericSwitchgearModel
from backend.app.models.bop.transformer import GenericTransformerModel
from backend.app.models.grid.grid_model import GenericGridModel, GridOperatingState
from backend.app.models.grid.poi_model import POIModel
from backend.app.models.grid.power_flow_interface import SimplePhasorPowerFlowSolver
from backend.app.models.meter.meter_model import GenericMeterModel
from backend.app.models.pcs.pcs_model import GenericPCSModel


class PlantElectricalNetwork:
    """Integrated BESS plant electrical network connecting generation, storage, and POI grid."""

    def __init__(
        self,
        battery: GenericBatterySystemModel | None = None,
        pcs: GenericPCSModel | None = None,
        transformer: GenericTransformerModel | None = None,
        switchgear: GenericSwitchgearModel | None = None,
        poi: POIModel | None = None,
        meter: GenericMeterModel | None = None,
        grid: GenericGridModel | None = None,
    ) -> None:
        self.battery: GenericBatterySystemModel = (
            battery if battery is not None else GenericBatterySystemModel()
        )
        self.pcs: GenericPCSModel = pcs if pcs is not None else GenericPCSModel()
        self.transformer: GenericTransformerModel = (
            transformer if transformer is not None else GenericTransformerModel()
        )
        self.switchgear: GenericSwitchgearModel = (
            switchgear if switchgear is not None else GenericSwitchgearModel()
        )
        self.poi: POIModel = poi if poi is not None else POIModel()
        self.meter: GenericMeterModel = meter if meter is not None else GenericMeterModel()
        self.grid: GenericGridModel = grid if grid is not None else GenericGridModel()

        self.power_flow_solver = SimplePhasorPowerFlowSolver()
        self.switchgear.breaker_closed = True

    def step(
        self,
        requested_p_w: float,
        requested_q_var: float,
        delta_t_s: float,
        timestamp_ns: int = 0,
    ) -> None:
        """Execute integrated plant electrical network simulation step."""
        # 1. Update Grid Model & Grid Disturbances
        is_closed = self.switchgear.breaker_closed
        net_plant_p = self.transformer.secondary_power_w if is_closed else 0.0
        net_plant_q = self.transformer.secondary_power_var if is_closed else 0.0

        grid_v, grid_f = self.grid.step(
            plant_net_p_w=net_plant_p,
            plant_net_q_var=net_plant_q,
            delta_t_s=delta_t_s,
            timestamp_ns=timestamp_ns,
        )

        # 2. Check Breaker State & Grid Connection
        if not is_closed or self.grid.grid_state != GridOperatingState.GRID_CONNECTED:
            pcs_ac_v = self.transformer.config.primary_voltage_v
        else:
            pcs_ac_v = grid_v / self.transformer.config.turns_ratio

        # 3. Process PCS Inverter Setpoints
        cmd = {
            "enable_inverter": True,
            "requested_p_w": requested_p_w,
            "requested_q_var": requested_q_var,
        }
        self.pcs.process_command(cmd)
        self.pcs.step(
            dc_voltage_v=self.battery.voltage_v,
            ac_grid_voltage_v=pcs_ac_v,
            delta_t_s=delta_t_s,
            timestamp_ns=timestamp_ns,
        )

        # 4. Step Battery System
        self.battery.step(
            power_demand_w=self.pcs.actual_p_w,
            delta_t_s=delta_t_s,
            timestamp_ns=timestamp_ns,
        )

        # 5. Step Transformer with PCS AC output
        self.transformer.step(
            primary_power_w=self.pcs.actual_p_w,
            primary_power_var=self.pcs.actual_q_var,
            primary_voltage_v=pcs_ac_v,
            delta_t_s=delta_t_s,
            timestamp_ns=timestamp_ns,
        )

        # 6. Step Switchgear with secondary current
        s_sec_sq = (
            self.transformer.secondary_power_w**2 + self.transformer.secondary_power_var**2
        )
        s_sec = s_sec_sq**0.5
        i_sec = s_sec / (1.73205 * max(1.0, grid_v))
        self.switchgear.step(current_a=i_sec, timestamp_ns=timestamp_ns, delta_t_s=delta_t_s)

        # 7. Step POI & Meter
        poi_p = self.transformer.secondary_power_w if is_closed else 0.0
        poi_q = self.transformer.secondary_power_var if is_closed else 0.0

        self.poi.step(
            net_p_w=poi_p,
            net_q_var=poi_q,
            voltage_v=grid_v,
            frequency_hz=grid_f,
            delta_t_s=delta_t_s,
            timestamp_ns=timestamp_ns,
        )

        self.meter.step(
            active_power_w=poi_p,
            reactive_power_var=poi_q,
            voltage_v=grid_v,
            frequency_hz=grid_f,
            delta_t_s=delta_t_s,
            timestamp_ns=timestamp_ns,
        )
