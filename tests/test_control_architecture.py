"""Automated Unit Tests for WP05 BESS Control Architecture."""

import pytest

from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.controllers.ems import EMSConfigModel, EMSMode, EnergyManagementSystem
from backend.app.controllers.equipment_controller import (
    BESSEquipmentController,
    EquipmentControllerConfig,
)
from backend.app.controllers.ppc import (
    PowerPlantController,
    PPCConfigModel,
    PPCPriorityMode,
)
from backend.app.equipment.models import OperatingState
from backend.app.models.battery.bms import GenericBMSModel
from backend.app.models.battery.system import (
    BatterySystemConfigModel,
    GenericBatterySystemModel,
)
from backend.app.models.bop.switchgear import GenericSwitchgearModel
from backend.app.models.pcs.pcs_model import GenericPCSModel, PCSConfigModel


def test_startup_and_shutdown_sequencing() -> None:
    """Test Layer A Equipment Controller startup and shutdown sequencing."""
    audit_log = ControlCommandLog()
    eq_ctrl = BESSEquipmentController(audit_log=audit_log)

    bms = GenericBMSModel("BMS_01")
    pcs1 = GenericPCSModel("PCS_01")
    pcs2 = GenericPCSModel("PCS_02")
    swg = GenericSwitchgearModel("SWG_01")

    # Initial state: STANDBY
    assert eq_ctrl.operating_state == OperatingState.STANDBY

    # Execute Startup Sequence
    started = eq_ctrl.execute_startup_sequence(
        bms_list=[bms],
        pcs_list=[pcs1, pcs2],
        switchgear=swg,
        container_temp_c=25.0,
        current_time_ns=1000,
    )

    assert started is True
    assert eq_ctrl.operating_state == OperatingState.RUNNING
    assert swg.breaker_closed is True
    assert bms.contactors_closed is True
    assert pcs1.operating_state == OperatingState.RUNNING
    assert pcs2.operating_state == OperatingState.RUNNING

    # Execute Shutdown Sequence
    eq_ctrl.execute_shutdown_sequence(
        bms_list=[bms],
        pcs_list=[pcs1, pcs2],
        switchgear=swg,
        current_time_ns=2000,
    )

    assert eq_ctrl.operating_state == OperatingState.STANDBY
    assert swg.breaker_closed is False
    assert bms.contactors_closed is False
    assert pcs1.operating_state == OperatingState.STANDBY


def test_startup_aborted_when_permissives_fail() -> None:
    """Test startup sequence is rejected when container temp exceeds limit."""
    audit_log = ControlCommandLog()
    eq_ctrl = BESSEquipmentController(
        config=EquipmentControllerConfig(max_container_temp_c=45.0),
        audit_log=audit_log,
    )

    bms = GenericBMSModel()
    pcs = GenericPCSModel()
    swg = GenericSwitchgearModel()

    # Attempt startup at 50 C container temp -> Fails
    started = eq_ctrl.execute_startup_sequence(
        bms_list=[bms],
        pcs_list=[pcs],
        switchgear=swg,
        container_temp_c=50.0,
        current_time_ns=1000,
    )

    assert started is False
    assert eq_ctrl.operating_state == OperatingState.STANDBY
    assert audit_log.entries[-1].status == CommandStatus.REJECTED_INTERLOCK


def test_pcs_power_allocation_among_available_units() -> None:
    """Test PPC allocates power setpoint proportionally among available active PCS units."""
    audit_log = ControlCommandLog()
    ppc = PowerPlantController(audit_log=audit_log)

    pcs1 = GenericPCSModel("PCS_01")
    pcs2 = GenericPCSModel("PCS_02")
    pcs1.operating_state = OperatingState.RUNNING
    pcs2.operating_state = OperatingState.RUNNING

    # Request +4 MW discharge setpoint
    acc_p, _acc_q = ppc.dispatch_poi_setpoint(
        requested_p_w=4_000_000.0,
        requested_q_var=0.0,
        pcs_units=[pcs1, pcs2],
        timestamp_ns=1000,
    )

    assert acc_p == 4_000_000.0
    # Each unit allocated 2 MW
    assert pcs1.requested_p_w == 2_000_000.0
    assert pcs2.requested_p_w == 2_000_000.0

    # If PCS2 becomes unavailable / faulted -> 100% power allocated to PCS1
    pcs2.operating_state = OperatingState.FAULTED
    pcs2.is_available = False

    acc_p2, _ = ppc.dispatch_poi_setpoint(
        requested_p_w=4_000_000.0,
        requested_q_var=0.0,
        pcs_units=[pcs1, pcs2],
        timestamp_ns=2000,
    )

    assert acc_p2 == 4_000_000.0
    assert pcs1.requested_p_w == 4_000_000.0
    assert pcs2.requested_p_w == 0.0


def test_ppc_active_and_reactive_power_constraints() -> None:
    """Test PPC enforces S_plant_max capability circle clamping."""
    config = PPCConfigModel(priority_mode=PPCPriorityMode.ACTIVE_POWER_PRIORITY)
    ppc = PowerPlantController(config=config)
    pcs_units = [
        GenericPCSModel(
            f"PCS_{i}",
            config=PCSConfigModel(rated_active_power_w=5_000_000.0, rated_apparent_power_va=5_500_000.0),
        )
        for i in range(10)
    ]
    for pcs in pcs_units:
        pcs.operating_state = OperatingState.RUNNING

    # Plant S_max = 55 MVA, Request P = 50 MW, Q = 50 MVAR -> Exceeds S_max
    acc_p, acc_q = ppc.dispatch_poi_setpoint(
        requested_p_w=50_000_000.0,
        requested_q_var=50_000_000.0,
        pcs_units=pcs_units,
        timestamp_ns=1000,
    )

    assert acc_p == 50_000_000.0
    # Max Q = sqrt(55^2 - 50^2) = sqrt(3025 - 2500) = sqrt(525) = 22.91 MVAR
    assert pytest.approx(acc_q / 1e6, abs=0.1) == 22.91


def test_ems_dispatch_infeasibility_when_battery_empty() -> None:
    """Test EMS rejects discharge request when battery is empty (SoC <= 5%)."""
    audit_log = ControlCommandLog()
    ems = EnergyManagementSystem(audit_log=audit_log)
    ppc = PowerPlantController()
    eq_ctrl = BESSEquipmentController()
    eq_ctrl.operating_state = OperatingState.RUNNING

    battery = GenericBatterySystemModel(config=BatterySystemConfigModel(initial_soc_pct=5.0))
    bms = GenericBMSModel()
    bms.evaluate_protection(voltage_v=1000.0, current_a=0.0, soc_pct=5.0, temp_c=25.0)
    pcs = GenericPCSModel()
    pcs.operating_state = OperatingState.RUNNING

    # Feasibility check for discharge at 5% SoC
    feasibility = ems.check_feasibility(
        p_req=10_000_000.0,
        q_req=0.0,
        battery=battery,
        bms_list=[bms],
        pcs_list=[pcs],
        equipment_controller=eq_ctrl,
    )

    assert feasibility.is_feasible is False
    assert feasibility.max_feasible_p_w == 0.0
    assert "BATTERY_EMPTY" in feasibility.reason

    # Execute EMS dispatch step -> Rejected as infeasible
    acc_p, _acc_q = ems.dispatch_step(
        requested_p_w=10_000_000.0,
        requested_q_var=0.0,
        ppc=ppc,
        battery=battery,
        bms_list=[bms],
        pcs_list=[pcs],
        equipment_controller=eq_ctrl,
        timestamp_ns=1000,
    )

    assert acc_p == 0.0
    assert audit_log.entries[-1].status == CommandStatus.REJECTED_INFEASIBLE


def test_ems_frequency_response_mode() -> None:
    """Test EMS P-f droop frequency response mode."""
    ems = EnergyManagementSystem(config=EMSConfigModel(mode=EMSMode.FREQUENCY_RESPONSE))
    ppc = PowerPlantController()
    eq_ctrl = BESSEquipmentController()
    eq_ctrl.operating_state = OperatingState.RUNNING

    battery = GenericBatterySystemModel(config=BatterySystemConfigModel(initial_soc_pct=50.0))
    bms = GenericBMSModel()
    bms.evaluate_protection(voltage_v=1000.0, current_a=0.0, soc_pct=50.0, temp_c=25.0)
    pcs = GenericPCSModel()
    pcs.operating_state = OperatingState.RUNNING

    # Frequency drop to 59.7 Hz (-0.3 Hz drop) -> BESS discharges to support grid
    acc_p, _acc_q = ems.dispatch_step(
        requested_p_w=0.0,
        requested_q_var=0.0,
        ppc=ppc,
        battery=battery,
        bms_list=[bms],
        pcs_list=[pcs],
        equipment_controller=eq_ctrl,
        grid_frequency_hz=59.7,
        timestamp_ns=1000,
    )

    assert acc_p > 0.0  # Discharging to support grid frequency


def test_fault_handling_emergency_stop_and_recovery() -> None:
    """Test Emergency Stop trip and recovery restart behavior."""
    eq_ctrl = BESSEquipmentController()
    bms = GenericBMSModel()
    pcs = GenericPCSModel()
    swg = GenericSwitchgearModel()

    # Emergency Stop trip
    eq_ctrl.emergency_stop(
        bms_list=[bms],
        pcs_list=[pcs],
        switchgear=swg,
        reason="OPERATOR_E_STOP_BUTTON",
        current_time_ns=1000,
    )

    assert eq_ctrl.operating_state == OperatingState.EMERGENCY_STOP
    assert eq_ctrl.is_available is False
    assert swg.breaker_closed is False
    assert bms.operating_state == OperatingState.EMERGENCY_STOP

    # Recovery: Reset fault state
    bms.clear_faults()
    swg.clear_faults()
    eq_ctrl.is_available = True
    eq_ctrl.operating_state = OperatingState.STANDBY

    # Startup after recovery succeeds
    started = eq_ctrl.execute_startup_sequence(
        bms_list=[bms],
        pcs_list=[pcs],
        switchgear=swg,
        container_temp_c=25.0,
        current_time_ns=2000,
    )

    assert started is True
    assert eq_ctrl.operating_state == OperatingState.RUNNING
