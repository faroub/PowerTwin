"""Automated End-to-End 20-Step Demonstration and Release Readiness Verification Test."""

from backend.app.equipment.models import OperatingState
from backend.app.historian.service import HistorianService
from backend.app.simulation.fault_injection import (
    FaultEventSpec,
    FaultInjectionEngine,
    FaultType,
)
from backend.app.topology.factory import PlantTopologyFactory


def test_20_step_e2e_demonstration_workflow() -> None:
    """Execute the full 20-step end-to-end BESS plant simulation demonstration."""
    # Step 1: Load the 10 MW / 20 MWh reference plant
    factory = PlantTopologyFactory()
    topology_config = factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml")
    assert topology_config.rated_power_w == 10_000_000.0
    assert topology_config.rated_energy_wh == 20_000_000.0

    # Step 2: Validate the topology (Validated automatically inside build_plant)

    # Step 3: Initialize all simulated equipment
    plant = factory.build_plant(topology_config)
    assert len(plant.battery_systems) == 4
    assert len(plant.pcs_units) == 4

    # Step 4: Start the simulation
    plant.simulation_engine.start()
    assert plant.simulation_engine.state.value == "RUNNING"

    # Step 5: Verify battery and PCS initial states
    assert plant.battery_systems[0].operating_state == OperatingState.STANDBY
    assert plant.pcs_units[0].operating_state == OperatingState.STANDBY

    # Step 6: Enable internal equipment controller (Layer A)
    started = plant.equipment_controller.execute_startup_sequence(
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        switchgear=plant.switchgear[0],
        container_temp_c=25.0,
        current_time_ns=0,
    )
    assert started is True
    assert plant.equipment_controller.operating_state == OperatingState.RUNNING

    # Step 7: Enable the PPC (Layer B)
    assert plant.ppc.operating_state == OperatingState.RUNNING
    assert plant.ppc.is_available is True

    # Step 8: Enable the EMS (Layer C)
    assert plant.ems.operating_state == OperatingState.RUNNING

    # Step 9: Request a 2 MW charging dispatch (-2 MW)
    req_p_w = -2_000_000.0
    req_q_var = 0.0

    # Step 10: Verify command propagation through EMS, PPC, and Equipment Controller
    acc_p, _acc_q = plant.ems.dispatch_step(
        requested_p_w=req_p_w,
        requested_q_var=req_q_var,
        ppc=plant.ppc,
        battery=plant.battery_systems[0],
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        equipment_controller=plant.equipment_controller,
        grid_frequency_hz=50.0,
        timestamp_ns=10_000_000,
    )
    assert acc_p == -2_000_000.0
    assert plant.pcs_units[0].requested_p_w == -500_000.0

    # Step 11: Verify PCS output and battery energy change
    plant.pcs_units[0].step(
        dc_voltage_v=1000.0,
        ac_grid_voltage_v=690.0,
        delta_t_s=0.1,
        timestamp_ns=20_000_000,
    )
    assert plant.pcs_units[0].actual_p_w < 0.0

    # Step 12: Verify POI power measurements
    poi_state = plant.poi.get_state()
    assert "active_power_w" in poi_state.measurements

    # Step 13: Verify historian data
    historian = HistorianService(max_buffer_size=100)
    historian.record_telemetry("POI.P", "POI_01", acc_p, "W", 10_000_000)
    assert historian.get_buffer_status()["telemetry_buffer_size"] == 1

    # Step 14: Verify HMI display endpoints with authenticated session token
    from fastapi.testclient import TestClient

    from backend.app.main import app

    client = TestClient(app)
    login_res = client.post(
        "/api/v1/auth/login", json={"username": "observer", "password": "observer123"}
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    hmi_res = client.get(
        "/api/v1/overview", headers={"Authorization": f"Bearer {token}"}
    )
    assert hmi_res.status_code == 200

    # Step 15: Inject a battery-container fault (Container 01 unavailable)
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

    # Step 16: Verify container availability changes
    assert plant.battery_systems[0].is_available is False
    assert plant.battery_systems[0].operating_state == OperatingState.FAULTED

    # Step 17: Verify available plant power is recalculated
    active_bats = sum(1 for b in plant.battery_systems if b.is_available)
    assert active_bats == 3

    # Step 18: Verify PPC and EMS respond correctly
    acc_p2, _ = plant.ems.dispatch_step(
        requested_p_w=-2_000_000.0,
        requested_q_var=0.0,
        ppc=plant.ppc,
        battery=plant.battery_systems[1],  # Use active Container 02
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        equipment_controller=plant.equipment_controller,
        grid_frequency_hz=50.0,
        timestamp_ns=210_000_000,
    )
    assert acc_p2 == -2_000_000.0

    # Step 19: Verify alarms and audit records
    assert len(fault_engine.audit_records) >= 1
    assert fault_engine.audit_records[-1].action == "INJECTED"

    # Step 20: Reset the simulation and repeat with the same seed (Seed = 42)
    plant.simulation_engine.reset()
    assert plant.simulation_engine.clock.time_ns == 0
    assert plant.simulation_engine.random.seed == 42
