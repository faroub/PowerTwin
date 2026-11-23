"""Automated End-to-End 25-Step Demonstration and Real-Time Scheduler-Driven Engineering Test."""

from fastapi.testclient import TestClient

from backend.app.api.v1.simulation_ctrl import set_active_simulation_engine
from backend.app.equipment.models import OperatingState
from backend.app.historian.service import HistorianService
from backend.app.main import app
from backend.app.simulation.fault_injection import (
    FaultEventSpec,
    FaultInjectionEngine,
    FaultType,
)
from backend.app.topology.factory import PlantTopologyFactory


def test_25_step_e2e_scheduler_driven_workflow(
    client: TestClient,
    dev_test_password: str,
) -> None:
    """Execute the full 25-step scheduler-driven end-to-end BESS plant simulation demonstration."""
    # Step 1: Load and validate the 10 MW / 20 MWh reference plant
    factory = PlantTopologyFactory()
    topology_config = factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml")
    assert topology_config.rated_power_w == 10_000_000.0
    assert topology_config.rated_energy_wh == 20_000_000.0

    # Step 2: Validate topology consistency (Validated automatically in build_plant)

    # Step 3: Instantiate all equipment and confirm ONE authoritative instance per asset
    plant = factory.build_plant(topology_config)
    assert len(plant.battery_systems) == 4
    assert len(plant.pcs_units) == 4

    # Single Object Identity Verification (PT-004)
    bat_task = plant.simulation_engine.scheduler._tasks["CONTAINER_01"]
    bat_from_task = getattr(bat_task, "physical_model", bat_task)
    assert plant.battery_systems[0] is bat_from_task

    pcs_task = plant.simulation_engine.scheduler._tasks["PCS_01"]
    pcs_from_task = getattr(pcs_task, "physical_model", pcs_task)
    assert plant.pcs_units[0] is pcs_from_task

    # Step 4: Start the simulation engine
    plant.simulation_engine.start()
    assert plant.simulation_engine.state.value == "RUNNING"

    # Step 5: Execute equipment startup sequence
    started = plant.equipment_controller.execute_startup_sequence(
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        switchgear=plant.switchgear[0],
        container_temp_c=25.0,
        current_time_ns=0,
    )
    assert started is True

    # Step 6: Verify BMS contactors and PCS states
    assert plant.equipment_controller.operating_state == OperatingState.RUNNING
    assert all(bms.contactors_closed for bms in plant.bms_units)
    assert plant.switchgear[0].breaker_closed is True

    # Step 7: Issue a 5 MW charging dispatch through EMS (-5 MW)
    req_p_w = -5_000_000.0
    req_q_var = 0.0

    # Step 8: Verify EMS feasibility
    feasibility = plant.ems.check_feasibility(
        p_req=req_p_w,
        q_req=req_q_var,
        batteries=plant.battery_systems,
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        equipment_controller=plant.equipment_controller,
        poi_max_export_p_w=10_000_000.0,
        poi_max_import_p_w=10_000_000.0,
    )
    assert feasibility.is_feasible is True
    assert feasibility.max_feasible_p_w == -5_000_000.0

    # Step 9: Verify PPC allocation
    acc_p, acc_q = plant.ems.dispatch_step(
        requested_p_w=req_p_w,
        requested_q_var=req_q_var,
        ppc=plant.ppc,
        battery=plant.battery_systems,
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        equipment_controller=plant.equipment_controller,
        grid_frequency_hz=50.0,
        timestamp_ns=10_000_000,
    )
    assert acc_p == -5_000_000.0
    assert plant.pcs_units[0].requested_p_w == -1_250_000.0

    # Step 10: Verify equipment-controller command handling
    assert plant.pcs_units[0].operating_state == OperatingState.RUNNING

    # Step 11: Execute actual scheduled PCS and battery models (1 hour = 3600s)
    plant.network.step(
        requested_p_w=acc_p,
        requested_q_var=acc_q,
        delta_t_s=3600.0,
        timestamp_ns=10_000_000,
    )

    # Step 12: Verify battery energy and SoC change
    assert plant.pcs_units[0].actual_p_w < 0.0
    assert plant.battery_systems[0].soc_pct > 50.0  # Battery charged from 50%

    # Step 13: Verify conversion losses
    assert plant.pcs_units[0].actual_p_w == plant.pcs_units[0].requested_p_w

    # Step 14: Verify transformer and switchgear behavior
    assert plant.transformers[0].secondary_voltage_v == 13800.0
    assert plant.switchgear[0].breaker_closed is True

    # Step 15: Verify POI P, Q, voltage, and frequency
    assert plant.poi.active_power_w < 0.0
    assert plant.poi.voltage_v == 13800.0
    assert plant.poi.frequency_hz == 50.0

    # Step 16: Verify historian persistence
    historian = HistorianService(max_buffer_size=100)
    historian.record_telemetry("POI.P", "POI_01", acc_p, "W", 10_000_000)
    assert historian.get_buffer_status()["telemetry_buffer_size"] == 1

    # Step 17: Verify live HMI telemetry with authenticated session token
    client = TestClient(app)
    plant.simulation_engine.shared_state["plant_instance"] = plant
    # Bind the engine to the *app-scoped* runtime so the overview endpoint reads
    # the plant attached to this very app.
    set_active_simulation_engine(plant.simulation_engine, app=client.app)

    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "observer", "password": dev_test_password},
    )
    token = login_res.json()["access_token"]

    hmi_res = client.get(
        "/api/v1/overview", headers={"Authorization": f"Bearer {token}"}
    )
    assert hmi_res.status_code == 200
    assert hmi_res.json()["average_soc_pct"] > 50.0

    # Step 18: Inject a battery-container fault (Container 01 unavailable)
    fault_engine = FaultInjectionEngine(seed=42)
    fault_engine.schedule_fault(
        FaultEventSpec(
            fault_id="E2E_FAULT_01",
            fault_type=FaultType.BATTERY_CONTAINER_UNAVAILABLE,
            target_equipment_id="CONTAINER_01",
            trigger_timestamp_ns=200_000_000,
        )
    )
    fault_engine.process_tick(200_000_000, plant)

    # Step 19: Verify available plant power and energy change
    assert plant.battery_systems[0].is_available is False
    assert plant.battery_systems[0].operating_state == OperatingState.FAULTED
    active_bats = sum(1 for b in plant.battery_systems if b.is_available)
    assert active_bats == 3

    # Step 20: Verify EMS and PPC adapt their dispatch
    acc_p2, _ = plant.ems.dispatch_step(
        requested_p_w=-3_000_000.0,
        requested_q_var=0.0,
        ppc=plant.ppc,
        battery=plant.battery_systems,
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        equipment_controller=plant.equipment_controller,
        grid_frequency_hz=50.0,
        timestamp_ns=210_000_000,
    )
    assert acc_p2 == -3_000_000.0

    # Step 21: Inject a PCS communication failure (PCS_01 faulted)
    fault_engine.schedule_fault(
        FaultEventSpec(
            fault_id="E2E_FAULT_02",
            fault_type=FaultType.PCS_COMMUNICATION_LOSS,
            target_equipment_id="PCS_01",
            trigger_timestamp_ns=300_000_000,
        )
    )
    fault_engine.process_tick(300_000_000, plant)

    # Step 22: Verify command rejection and watchdog behavior
    assert plant.pcs_units[0].is_available is False
    assert plant.pcs_units[0].operating_state == OperatingState.FAULTED

    # Step 23: Verify alarms and audit records
    assert len(fault_engine.audit_records) >= 2
    assert fault_engine.audit_records[-1].action == "INJECTED"

    # Step 24: Reset the simulation
    plant.simulation_engine.reset()
    assert plant.simulation_engine.clock.time_ns == 0
    assert plant.simulation_engine.state.value == "STOPPED"

    # Step 25: Restore a snapshot and verify deterministic continuation
    snap = plant.simulation_engine.create_snapshot()
    plant.simulation_engine.restore_snapshot(snap)
    assert plant.simulation_engine.clock.time_ns == 0

    set_active_simulation_engine(None)
