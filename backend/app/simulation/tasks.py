"""Scheduled plant tasks driving the authoritative simulation pipeline.

Deterministic tick pipeline (one authoritative state owner per equipment):

    Phase 1 : DummyGridPlugin/DummyAuxiliaryPlugin  Ambient environment emulation.
    Phase 2 : PlantControlTask                      EMS -> PPC dispatch -> per-PCS setpoints.
    Phase 3 : GenericPCSPlugin                      PCS inverter physical stepping.
    Phase 4 : PlantBatteryDistributionTask          PCS actual power -> per-battery commands.
    Phase 4 : GenericBatteryPlugin                  Battery energy balance stepping.
    Phase 5 : PlantNetworkTask                      transformers -> switchgear -> POI -> meters.

One physical model is never advanced twice within a single simulation tick:
the generic plugins own the PCS and battery dynamics, PlantNetworkTask owns
the BOP network, and PlantControlTask owns the control hierarchy.
"""

import math
from typing import Any

from backend.app.controllers.ems import EnergyManagementSystem
from backend.app.controllers.equipment_controller import BESSEquipmentController
from backend.app.controllers.ppc import PowerPlantController
from backend.app.models.battery.bms import GenericBMSModel
from backend.app.models.battery.system import GenericBatterySystemModel
from backend.app.models.bop.switchgear import GenericSwitchgearModel
from backend.app.models.bop.transformer import GenericTransformerModel
from backend.app.models.grid.grid_model import GenericGridModel, GridOperatingState
from backend.app.models.grid.network import PlantElectricalNetwork
from backend.app.models.grid.poi_model import POIModel
from backend.app.models.meter.meter_model import GenericMeterModel
from backend.app.models.pcs.pcs_model import GenericPCSModel
from backend.app.simulation.context import SimulationContext
from backend.app.simulation.task import SimulationTask

# --------------------------------------------------------------------------- #
# Shared state keys owned by the plant tasks.
# --------------------------------------------------------------------------- #

KEY_EM_REQ_P_W = "ems_requested_p_w"
KEY_EM_REQ_Q_VAR = "ems_requested_q_var"
KEY_EM_ACC_P_W = "ems_accepted_p_w"
KEY_EM_ACC_Q_VAR = "ems_accepted_q_var"

KEY_PCS_CMD_ACTIVE_W = "pcs_cmd_active_power_w"
KEY_PCS_CMD_REACTIVE_W = "pcs_cmd_reactive_power_var"
KEY_PCS_CMD_ACTIVE_W_PREFIX = "pcs_cmd_active_power_w_"
KEY_PCS_CMD_REACTIVE_W_PREFIX = "pcs_cmd_reactive_power_var_"
KEY_PCS_ACTUAL_P_W = "pcs_actual_power_w"
KEY_PCS_ACTUAL_Q_VAR = "pcs_actual_reactive_power_var"

KEY_BATTERY_CMD_P_W = "battery_cmd_power_w"
KEY_BATTERY_CMD_P_W_PREFIX = "battery_cmd_power_w_"

KEY_GRID_VOLTAGE_V = "grid_voltage_v"
KEY_GRID_FREQUENCY_HZ = "grid_frequency_hz"
KEY_PCS_AC_GRID_VOLTAGE_V = "pcs_ac_grid_voltage_v"
KEY_BATTERY_VOLTAGE_V = "battery_voltage_v"


class PlantControlTask(SimulationTask):
    """Phase 2 task: EMS feasibility/dispatch and per-PCS setpoint wiring.

    Executes the EMS/PPC dispatch chain once per tick and writes the accepted
    per-PCS setpoint commands into the simulation shared state. The PCS plugin
    tasks in Phase 3 consume those keys as their authoritative command source.
    """

    def __init__(
        self,
        ems: EnergyManagementSystem,
        ppc: PowerPlantController,
        equipment_controller: BESSEquipmentController,
        battery_systems: list[GenericBatterySystemModel],
        bms_units: list[GenericBMSModel] | None = None,
        pcs_units: list[GenericPCSModel] | None = None,
        *,
        grid: GenericGridModel,
        transformers: list[GenericTransformerModel] | None = None,
        switches: list[GenericSwitchgearModel] | None = None,
        meters: list[GenericMeterModel] | None = None,
        poi: POIModel | None = None,
        name: str = "PLANT_CONTROL_TASK",
        phase: int = 2,
        priority: int = 0,
        interval_ticks: int = 1,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name=name,
            phase=phase,
            priority=priority,
            interval_ticks=interval_ticks,
            enabled=enabled,
        )
        self.ems = ems
        self.ppc = ppc
        self.equipment_controller = equipment_controller
        self.battery_systems = battery_systems
        self.bms_units = list(bms_units or [])
        self.pcs_units = list(pcs_units or [])
        self.grid = grid
        self.transformers = list(transformers or [])
        self.switches = list(switches or [])
        self.meters = list(meters or [])
        self.poi = poi
        self._last_dispatch_p = 0.0
        self._last_dispatch_q = 0.0

    def execute(self, ctx: SimulationContext) -> None:
        if not self.enabled:
            return

        # 1. Operator/EMS dispatch request. The API layer writes the requested
        #    real-time setpoints into the shared state before this task runs.
        req_p = ctx.shared_state.get(KEY_EM_REQ_P_W, 0.0)
        req_q = ctx.shared_state.get(KEY_EM_REQ_Q_VAR, 0.0)
        if not math.isfinite(req_p) or not math.isfinite(req_q):
            req_p, req_q = 0.0, 0.0

        # 2. Collapse all NaN/Infinity inputs to a zero dispatch before the
        #    EMS/PPC chain runs so the plant never accepts a non-finite command.
        if req_p != req_p or req_q != req_q:
            req_p, req_q = 0.0, 0.0

        # 2. EMS feasibility check followed by PPC unit allocation.
        acc_p, acc_q = self.ems.dispatch_step(
            requested_p_w=req_p,
            requested_q_var=req_q,
            ppc=self.ppc,
            battery=self.battery_systems,
            bms_list=self.bms_units,
            pcs_list=self.pcs_units,
            equipment_controller=self.equipment_controller,
            grid_frequency_hz=self.grid.config.nominal_frequency_hz,
            timestamp_ns=ctx.current_tick_ns,
        )
        self._last_dispatch_p = acc_p
        self._last_dispatch_q = acc_q

        ctx.shared_state[KEY_EM_ACC_P_W] = acc_p
        ctx.shared_state[KEY_EM_ACC_Q_VAR] = acc_q

        # 3. Write the per-PCS command setpoints into the shared state.
        #    PPC allocation is authoritative; each PCS unit receives its own
        #    key so different weights/capacities are handled correctly.
        for pcs in self.pcs_units:
            key_p = f"{KEY_PCS_CMD_ACTIVE_W_PREFIX}{pcs.equipment_id}"
            key_q = f"{KEY_PCS_CMD_REACTIVE_W_PREFIX}{pcs.equipment_id}"
            ctx.shared_state[key_p] = pcs.requested_p_w
            ctx.shared_state[key_q] = pcs.requested_q_var

        # 4. Plant-level totals remain on the legacy keys for readers.
        ctx.shared_state[KEY_PCS_CMD_ACTIVE_W] = acc_p
        ctx.shared_state[KEY_PCS_CMD_REACTIVE_W] = acc_q

        # 5. Evaluate each BMS against the actual battery measurements so that
        #    protection limits are live for every tick of the pipeline.
        for bms, bat in zip(self.bms_units, self.battery_systems, strict=True):
            bms.evaluate_protection(
                voltage_v=bat.voltage_v,
                current_a=bat.current_a,
                soc_pct=bat.soc_pct,
                temp_c=bat.temperature_c,
                timestamp_ns=ctx.current_tick_ns,
                quality="GOOD",
            )

    def get_task_state(self) -> dict[str, Any]:
        """Include the controller and BMS state in the snapshot."""
        state = super().get_task_state()
        state["equipment_controller"] = self._equipment_controller_state()
        state["bms_states"] = [unit.get_state() for unit in self.bms_units]
        return state

    def set_task_state(self, state: dict[str, Any]) -> None:
        """Restore the controller and BMS state from the snapshot."""
        super().set_task_state(state)
        controller_state = state.get("equipment_controller")
        if controller_state is not None:
            self._restore_equipment_controller_state(controller_state)
        for unit, unit_state in zip(self.bms_units, state.get("bms_states", []), strict=True):
            unit.restore_state_snapshot(unit_state)

    def restore_to_initial(self) -> None:
        """Reset the plant's BMS fleet and controller to their initial conditions."""
        for bms in self.bms_units:
            bms.reset_to_initial_conditions()
        self.equipment_controller.reset_to_initial_conditions()

    def _equipment_controller_state(self) -> dict[str, Any]:
        """Capture the equipment controller internal state."""
        return {
            "operating_state": self.equipment_controller.operating_state.value,
            "is_available": self.equipment_controller.is_available,
            "last_heartbeat_ns": self.equipment_controller.last_heartbeat_ns,
            "state_history": [
                (ts, from_state, to_state)
                for ts, from_state, to_state in self.equipment_controller.state_history
            ],
            "active_alarms": [
                alarm.model_dump(mode="json") for alarm in self.equipment_controller.active_alarms
            ],
        }

    def _restore_equipment_controller_state(self, state: dict[str, Any]) -> None:
        """Restore the equipment controller internal state."""
        self.equipment_controller.operating_state = state.get(
            "operating_state", self.equipment_controller.operating_state
        )
        if isinstance(self.equipment_controller.operating_state, str):
            from backend.app.equipment.models import OperatingState

            self.equipment_controller.operating_state = OperatingState(
                self.equipment_controller.operating_state
            )
        self.equipment_controller.is_available = state.get(
            "is_available", self.equipment_controller.is_available
        )
        self.equipment_controller.last_heartbeat_ns = state.get(
            "last_heartbeat_ns", self.equipment_controller.last_heartbeat_ns
        )
        history = state.get("state_history", [])
        self.equipment_controller.state_history = [
            (int(ts), str(from_state), str(to_state)) for ts, from_state, to_state in history
        ]


class PlantBatteryDistributionTask(SimulationTask):
    """Phase 4 task: distribute PCS actual output into per-battery commands.

    The PCS inverter step feeds each battery container; the active output of
    the available PCS fleet is split evenly over the available battery
    containers, keying the command in the shared state per battery ID.
    """

    def __init__(
        self,
        battery_systems: list[GenericBatterySystemModel] | None = None,
        pcs_units: list[GenericPCSModel] | None = None,
        name: str = "BATTERY_DISTRIBUTION_TASK",
        phase: int = 4,
        priority: int = 0,
        interval_ticks: int = 1,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name=name,
            phase=phase,
            priority=priority,
            interval_ticks=interval_ticks,
            enabled=enabled,
        )
        self.battery_systems = list(battery_systems or [])
        self.pcs_units = list(pcs_units or [])

    def execute(self, ctx: SimulationContext) -> None:
        if not self.enabled:
            return

        total_pcs_p = sum(pcs.actual_p_w for pcs in self.pcs_units if pcs.is_available)
        # The PCS fleet is the single source of truth for the plant active power
        # that each battery must track.
        available = [bat for bat in self.battery_systems if bat.is_available]
        count = max(1, len(available))

        for bat in self.battery_systems:
            if bat.is_available:
                # Active power demand split evenly across available battery containers
                ctx.shared_state[f"{KEY_BATTERY_CMD_P_W_PREFIX}{bat.equipment_id}"] = (
                    total_pcs_p / count
                )
            else:
                ctx.shared_state[f"{KEY_BATTERY_CMD_P_W_PREFIX}{bat.equipment_id}"] = 0.0


class PlantNetworkTask(SimulationTask):
    """Phase 5 task: BOP network physics (transformers -> switchgear -> POI -> meters).

    Reads the actual PCS outputs produced in Phase 3 and computes the phasor
    power flow through the transformer, switchgear, POI and meters.
    """

    def __init__(
        self,
        network: PlantElectricalNetwork | None = None,
        grid: GenericGridModel | None = None,
        transformers: list[GenericTransformerModel] | None = None,
        switches: list[GenericSwitchgearModel] | None = None,
        meters: list[GenericMeterModel] | None = None,
        poi: POIModel | None = None,
        pcs_units: list[GenericPCSModel] | None = None,
        name: str = "PLANT_NETWORK_TASK",
        phase: int = 5,
        priority: int = 0,
        interval_ticks: int = 1,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name=name,
            phase=phase,
            priority=priority,
            interval_ticks=interval_ticks,
            enabled=enabled,
        )
        self.network = network if network is not None else PlantElectricalNetwork()
        # A network tick needs a grid model; default to the generic model when
        # the task is constructed without one.
        self.grid: GenericGridModel = grid if grid is not None else GenericGridModel()
        self.transformers = list(transformers or [])
        self.switches = list(switches or [])
        self.meters = list(meters or [])
        self.poi = poi
        self.pcs_units = list(pcs_units or [])

    def execute(self, ctx: SimulationContext) -> None:
        if not self.enabled:
            return

        delta_t_s = ctx.delta_t_s
        timestamp_ns = ctx.current_tick_ns

        # 1. Grid/Environment update (previous POI net power for impedance drop).
        grid_v, grid_f = self.grid.step(
            plant_net_p_w=self.poi.active_power_w if self.poi else 0.0,
            plant_net_q_var=self.poi.reactive_power_var if self.poi else 0.0,
            delta_t_s=delta_t_s,
            timestamp_ns=timestamp_ns,
        )

        # 2. BOP boundary power: actual PCS outputs.
        net_pcs_p = sum(pcs.actual_p_w for pcs in self.pcs_units if pcs.is_available)
        net_pcs_q = sum(pcs.actual_q_var for pcs in self.pcs_units if pcs.is_available)

        # 3. Transformer primary voltage (impedance-drop corrected grid voltage).
        is_closed = all(swg.breaker_closed for swg in self.switches)
        if not is_closed or self.grid.grid_state != GridOperatingState.GRID_CONNECTED:
            pcs_ac_v = self._primary_voltage()
        else:
            pcs_ac_v = grid_v / self._turns_ratio()

        num_xfrms = len(self.transformers)

        # 4. Transformers driven from the actual PCS outputs.
        for xfrm in self.transformers:
            xfrm.step(
                primary_power_w=net_pcs_p / num_xfrms,
                primary_power_var=net_pcs_q / num_xfrms,
                primary_voltage_v=pcs_ac_v,
                delta_t_s=delta_t_s,
                timestamp_ns=timestamp_ns,
            )

        # 5. Switchgear with the resulting secondary current.
        net_plant_p = (
            sum(xfrm.secondary_power_w for xfrm in self.transformers) if is_closed else 0.0
        )
        net_plant_q = (
            sum(xfrm.secondary_power_var for xfrm in self.transformers) if is_closed else 0.0
        )

        s_sec_sq = net_plant_p**2 + net_plant_q**2
        s_sec = s_sec_sq**0.5
        i_sec = s_sec / (math.sqrt(3.0) * max(1.0, grid_v))

        for swg in self.switches:
            swg.step(current_a=i_sec, timestamp_ns=timestamp_ns, delta_t_s=delta_t_s)

        # 6. POI and meters.
        if self.poi is not None:
            self.poi.step(
                net_p_w=net_plant_p,
                net_q_var=net_plant_q,
                voltage_v=grid_v,
                frequency_hz=grid_f,
                delta_t_s=delta_t_s,
                timestamp_ns=timestamp_ns,
            )

        for mtr in self.meters:
            mtr.step(
                active_power_w=net_plant_p,
                reactive_power_var=net_plant_q,
                voltage_v=grid_v,
                frequency_hz=grid_f,
                delta_t_s=delta_t_s,
                timestamp_ns=timestamp_ns,
            )

        # 7. Atomic wall-clock/phase state for the next tick's PCS and battery tasks.
        ctx.shared_state[KEY_GRID_VOLTAGE_V] = grid_v
        ctx.shared_state[KEY_GRID_FREQUENCY_HZ] = grid_f
        ctx.shared_state[KEY_PCS_AC_GRID_VOLTAGE_V] = pcs_ac_v

    def get_task_state(self) -> dict[str, Any]:
        """Capture the full BOP network state (grid, transformers, switchgear, POI, meters)."""
        state = super().get_task_state()
        state["grid"] = self.grid.get_state()
        state["transformers"] = [model.get_state() for model in self.transformers]
        state["switchgear"] = [model.get_state() for model in self.switches]
        state["meters"] = [model.get_state() for model in self.meters]
        state["poi"] = self.poi.get_state() if self.poi else None
        return state

    def set_task_state(self, state: dict[str, Any]) -> None:
        """Restore the full BOP network state (grid, transformers, switchgear, POI, meters)."""
        super().set_task_state(state)
        grid_state = state.get("grid")
        if grid_state is not None:
            self.grid.restore_state_snapshot(grid_state)
        for xfrm, xfrm_state in zip(self.transformers, state.get("transformers", []), strict=True):
            xfrm.restore_state_snapshot(xfrm_state)
        for swg, swg_state in zip(self.switches, state.get("switchgear", []), strict=True):
            swg.restore_state_snapshot(swg_state)
        for mtr, mtr_state in zip(self.meters, state.get("meters", []), strict=True):
            mtr.restore_state_snapshot(mtr_state)
        if self.poi is not None:
            poi_state = state.get("poi")
            if poi_state is not None:
                self.poi.restore_state_snapshot(poi_state)

    def restore_to_initial(self) -> None:
        """Reset the plant BOP network models to their initial conditions."""
        self.grid.reset_to_initial_conditions()
        for xfrm in self.transformers:
            xfrm.reset_to_initial_conditions()
        for swg in self.switches:
            swg.reset_to_initial_conditions()
        for mtr in self.meters:
            mtr.reset_to_initial_conditions()
        if self.poi is not None:
            self.poi.reset_to_initial_conditions()

    def _primary_voltage(self) -> float:
        """Return the transformer primary (LV) voltage, e.g. 690 V."""
        if not self.transformers:
            return 0.0
        return self.transformers[0].config.primary_voltage_v

    def _turns_ratio(self) -> float:
        """Return the transformer turns ratio V_sec / V_pri."""
        if not self.transformers:
            return 1.0
        return self.transformers[0].config.turns_ratio
