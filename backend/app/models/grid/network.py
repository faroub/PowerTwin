"""Plant Electrical Network Integration Model.

Connects Batteries -> PCS Units -> Transformers -> Switchgear -> POI -> Grid.
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
    """Integrated BESS plant electrical network connecting components and POI."""

    def __init__(
        self,
        battery: GenericBatterySystemModel | list[GenericBatterySystemModel] | None = None,
        pcs: GenericPCSModel | list[GenericPCSModel] | None = None,
        transformer: GenericTransformerModel | list[GenericTransformerModel] | None = None,
        switchgear: GenericSwitchgearModel | list[GenericSwitchgearModel] | None = None,
        poi: POIModel | None = None,
        meter: GenericMeterModel | list[GenericMeterModel] | None = None,
        grid: GenericGridModel | None = None,
    ) -> None:
        if isinstance(battery, list):
            self.batteries: list[GenericBatterySystemModel] = battery
        elif battery is not None:
            self.batteries = [battery]
        else:
            self.batteries = [GenericBatterySystemModel()]

        if isinstance(pcs, list):
            self.pcs_units: list[GenericPCSModel] = pcs
        elif pcs is not None:
            self.pcs_units = [pcs]
        else:
            self.pcs_units = [GenericPCSModel()]

        if isinstance(transformer, list):
            self.transformers: list[GenericTransformerModel] = transformer
        elif transformer is not None:
            self.transformers = [transformer]
        else:
            self.transformers = [GenericTransformerModel()]

        if isinstance(switchgear, list):
            self.switchgear_list: list[GenericSwitchgearModel] = switchgear
        elif switchgear is not None:
            self.switchgear_list = [switchgear]
        else:
            self.switchgear_list = [GenericSwitchgearModel()]

        if isinstance(meter, list):
            self.meters: list[GenericMeterModel] = meter
        elif meter is not None:
            self.meters = [meter]
        else:
            self.meters = [GenericMeterModel()]

        self.poi: POIModel = poi if poi is not None else POIModel()
        self.grid: GenericGridModel = grid if grid is not None else GenericGridModel()

        # Backward compatibility single-instance aliases
        self.battery: GenericBatterySystemModel = self.batteries[0]
        self.pcs: GenericPCSModel = self.pcs_units[0]
        self.transformer: GenericTransformerModel = self.transformers[0]
        self.switchgear: GenericSwitchgearModel = self.switchgear_list[0]
        self.meter: GenericMeterModel = self.meters[0]

        self.power_flow_solver = SimplePhasorPowerFlowSolver()
        for swg in self.switchgear_list:
            swg.breaker_closed = True

    def step(
        self,
        requested_p_w: float,
        requested_q_var: float,
        delta_t_s: float,
        timestamp_ns: int = 0,
    ) -> None:
        """Execute integrated plant electrical network simulation step."""
        is_closed = all(swg.breaker_closed for swg in self.switchgear_list)

        # 1. Update Grid Model & Grid Disturbances
        grid_v, grid_f = self.grid.step(
            plant_net_p_w=self.poi.active_power_w,
            plant_net_q_var=self.poi.reactive_power_var,
            delta_t_s=delta_t_s,
            timestamp_ns=timestamp_ns,
        )

        # 2. Check Breaker State & Grid Connection
        if not is_closed or self.grid.grid_state != GridOperatingState.GRID_CONNECTED:
            pcs_ac_v = self.transformers[0].config.primary_voltage_v
        else:
            pcs_ac_v = grid_v / self.transformers[0].config.turns_ratio

        # 3. Process PCS Inverter Setpoints
        active_pcs = [pcs for pcs in self.pcs_units if pcs.is_available]
        num_active_pcs = len(active_pcs) if active_pcs else 1
        unit_p_w = requested_p_w / num_active_pcs
        unit_q_var = requested_q_var / num_active_pcs

        cmd = {
            "enable_inverter": True,
            "requested_p_w": unit_p_w,
            "requested_q_var": unit_q_var,
        }

        for pcs in self.pcs_units:
            if pcs.is_available:
                pcs.process_command(cmd)
                dc_v = self.batteries[0].voltage_v if self.batteries else 1000.0
                pcs.step(
                    dc_voltage_v=dc_v,
                    ac_grid_voltage_v=pcs_ac_v,
                    delta_t_s=delta_t_s,
                    timestamp_ns=timestamp_ns,
                )

        # 4. Step Battery Systems
        num_active_bats = len([b for b in self.batteries if b.is_available]) or 1
        net_actual_p_w = sum(pcs.actual_p_w for pcs in self.pcs_units if pcs.is_available)
        unit_bat_p_w = net_actual_p_w / num_active_bats

        for bat in self.batteries:
            if bat.is_available:
                bat.step(
                    power_demand_w=unit_bat_p_w,
                    delta_t_s=delta_t_s,
                    timestamp_ns=timestamp_ns,
                )

        # 5. Step Transformers with PCS AC output
        net_pcs_p = sum(pcs.actual_p_w for pcs in self.pcs_units if pcs.is_available)
        net_pcs_q = sum(pcs.actual_q_var for pcs in self.pcs_units if pcs.is_available)
        num_xfrms = len(self.transformers)

        for xfrm in self.transformers:
            xfrm.step(
                primary_power_w=net_pcs_p / num_xfrms,
                primary_power_var=net_pcs_q / num_xfrms,
                primary_voltage_v=pcs_ac_v,
                delta_t_s=delta_t_s,
                timestamp_ns=timestamp_ns,
            )

        # 6. Step Switchgear
        net_plant_p = (
            sum(xfrm.secondary_power_w for xfrm in self.transformers) if is_closed else 0.0
        )
        net_plant_q = (
            sum(xfrm.secondary_power_var for xfrm in self.transformers) if is_closed else 0.0
        )

        s_sec_sq = net_plant_p**2 + net_plant_q**2
        s_sec = s_sec_sq**0.5
        i_sec = s_sec / (1.73205 * max(1.0, grid_v))

        for swg in self.switchgear_list:
            swg.step(current_a=i_sec, timestamp_ns=timestamp_ns, delta_t_s=delta_t_s)

        # 7. Step POI & Meters
        poi_p = net_plant_p if is_closed else 0.0
        poi_q = net_plant_q if is_closed else 0.0

        self.poi.step(
            net_p_w=poi_p,
            net_q_var=poi_q,
            voltage_v=grid_v,
            frequency_hz=grid_f,
            delta_t_s=delta_t_s,
            timestamp_ns=timestamp_ns,
        )

        for mtr in self.meters:
            mtr.step(
                active_power_w=poi_p,
                reactive_power_var=poi_q,
                voltage_v=grid_v,
                frequency_hz=grid_f,
                delta_t_s=delta_t_s,
                timestamp_ns=timestamp_ns,
            )
