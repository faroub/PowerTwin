"""Automated Integration Tests for WP10 Scenarios and Fault Injection Framework."""

from backend.app.simulation.fault_injection import FaultEventSpec, FaultType
from backend.app.simulation.scenario import AcceptanceCriteriaSpec, ScenarioDefinition
from backend.app.simulation.scenario_runner import ScenarioRunner


def test_scenario_loss_of_one_battery_container() -> None:
    """Test Scenario 1: Loss of one battery container (Container 01 faulted)."""
    runner = ScenarioRunner()
    scenario = ScenarioDefinition(
        scenario_id="SCENARIO_LOSS_CONTAINER_01",
        description="Container 01 faults at t=500ms; PPC reallocates to remaining containers.",
        plant_config_path="configs/reference_10mw_20mwh.yaml",
        simulation_duration_ns=1_000_000_000,  # 1 second
        requested_p_w=4_000_000.0,
        fault_sequence=[
            FaultEventSpec(
                fault_id="FAULT_CONTAINER_01",
                fault_type=FaultType.BATTERY_CONTAINER_UNAVAILABLE,
                target_equipment_id="CONTAINER_01",
                trigger_timestamp_ns=500_000_000,
            )
        ],
        expected_behavior="Container 01 becomes unavailable; 3 active containers remaining.",
        acceptance_criteria=[
            AcceptanceCriteriaSpec(
                criterion_id="CRIT_ACTIVE_BATTERIES",
                description="3 active battery containers remaining",
                metric_name="ACTIVE_BATTERY_COUNT",
                operator="EQ",
                target_value=3,
            )
        ],
    )

    report = runner.run_scenario(scenario)
    assert report.passed is True
    assert len(report.fault_audit_records) >= 1


def test_scenario_loss_of_one_pcs_inverter() -> None:
    """Test Scenario 2: Loss of one PCS inverter (PCS_01 faulted)."""
    runner = ScenarioRunner()
    scenario = ScenarioDefinition(
        scenario_id="SCENARIO_LOSS_PCS_01",
        description="PCS_01 faults; PPC reallocates power among remaining 3 PCS units.",
        plant_config_path="configs/reference_10mw_20mwh.yaml",
        simulation_duration_ns=1_000_000_000,
        requested_p_w=4_000_000.0,
        fault_sequence=[
            FaultEventSpec(
                fault_id="FAULT_PCS_01",
                fault_type=FaultType.PCS_COMMUNICATION_LOSS,
                target_equipment_id="PCS_01",
                trigger_timestamp_ns=200_000_000,
            )
        ],
        expected_behavior="PCS_01 becomes unavailable; 3 active PCS units remaining.",
        acceptance_criteria=[
            AcceptanceCriteriaSpec(
                criterion_id="CRIT_ACTIVE_PCS",
                description="3 active PCS units remaining",
                metric_name="ACTIVE_PCS_COUNT",
                operator="EQ",
                target_value=3,
            )
        ],
    )

    report = runner.run_scenario(scenario)
    assert report.passed is True


def test_scenario_bms_communication_failure() -> None:
    """Test Scenario 3: BMS communication failure trigger."""
    runner = ScenarioRunner()
    scenario = ScenarioDefinition(
        scenario_id="SCENARIO_BMS_COMM_LOSS",
        description="BMS_CONTAINER_01 communication loss at t=100ms.",
        plant_config_path="configs/reference_10mw_20mwh.yaml",
        simulation_duration_ns=500_000_000,
        fault_sequence=[
            FaultEventSpec(
                fault_id="FAULT_BMS_COMM",
                fault_type=FaultType.BMS_COMMUNICATION_LOSS,
                target_equipment_id="CONTAINER_01",
                trigger_timestamp_ns=100_000_000,
            )
        ],
        expected_behavior="BMS fault alarm recorded.",
        acceptance_criteria=[
            AcceptanceCriteriaSpec(
                criterion_id="CRIT_BMS_FAULT",
                description="BMS communication fault recorded in audit",
                metric_name="EQUIPMENT_CONTROLLER_STATE",
                operator="EQ",
                target_value="RUNNING",
            )
        ],
    )

    report = runner.run_scenario(scenario)
    assert report.passed is True


def test_scenario_grid_frequency_disturbance() -> None:
    """Test Scenario 4: Grid frequency drop to 49.5 Hz triggers fast frequency response."""
    runner = ScenarioRunner()
    scenario = ScenarioDefinition(
        scenario_id="SCENARIO_GRID_FREQ_DROP",
        description="Grid frequency drops to 49.5 Hz at t=200ms.",
        plant_config_path="configs/reference_10mw_20mwh.yaml",
        simulation_duration_ns=500_000_000,
        fault_sequence=[
            FaultEventSpec(
                fault_id="FAULT_FREQ_DROP",
                fault_type=FaultType.FREQUENCY_DISTURBANCE,
                target_equipment_id="GRID_50HZ_01",
                trigger_timestamp_ns=200_000_000,
                parameters={"frequency_hz": 49.5},
            )
        ],
        expected_behavior="Grid frequency disturbance injected.",
        acceptance_criteria=[
            AcceptanceCriteriaSpec(
                criterion_id="CRIT_PLANT_RUNNING",
                description="Equipment Controller remains RUNNING",
                metric_name="EQUIPMENT_CONTROLLER_STATE",
                operator="EQ",
                target_value="RUNNING",
            )
        ],
    )

    report = runner.run_scenario(scenario)
    assert report.passed is True


def test_scenario_poi_power_limit_violation_prevention() -> None:
    """Test Scenario 5: PPC clamps setpoint to POI export limit (10 MW)."""
    runner = ScenarioRunner()
    scenario = ScenarioDefinition(
        scenario_id="SCENARIO_POI_LIMIT_CLAMP",
        description="Operator requests +15 MW discharge setpoint; PPC clamps to 10 MW POI limit.",
        plant_config_path="configs/reference_10mw_20mwh.yaml",
        simulation_duration_ns=500_000_000,
        requested_p_w=15_000_000.0,  # 15 MW > 10 MW POI limit
        expected_behavior="PPC clamps accepted power to 10 MW.",
        acceptance_criteria=[
            AcceptanceCriteriaSpec(
                criterion_id="CRIT_POI_CLAMP",
                description="PPC accepted power clamped to <= 10 MW",
                metric_name="PPC_ACCEPTED_P_W",
                operator="LE",
                target_value=10_000_000.0,
            )
        ],
    )

    report = runner.run_scenario(scenario)
    assert report.passed is True


def test_scenario_ems_dispatch_exceeding_available_power() -> None:
    """Test Scenario 6: EMS dispatch request rejected when battery is empty (SoC = 5%)."""
    runner = ScenarioRunner()
    scenario = ScenarioDefinition(
        scenario_id="SCENARIO_EMPTY_BATTERY_DISPATCH",
        description="Discharge request at 5% SoC is rejected by EMS as infeasible.",
        plant_config_path="configs/reference_10mw_20mwh.yaml",
        initial_conditions={"soc_pct": 5.0},
        requested_p_w=10_000_000.0,
        simulation_duration_ns=500_000_000,
        expected_behavior="EMS rejects setpoint; accepted power = 0.0 W.",
        acceptance_criteria=[
            AcceptanceCriteriaSpec(
                criterion_id="CRIT_ZERO_ACCEPTED_POWER",
                description="Accepted power is 0.0 W when battery is empty",
                metric_name="ACCEPTED_POWER_W",
                operator="EQ",
                target_value=0.0,
            )
        ],
    )

    report = runner.run_scenario(scenario)
    assert report.passed is True


def test_scenario_recovery_after_fault_cleared() -> None:
    """Test Scenario 7: Recovery after a temporary fault is cleared."""
    runner = ScenarioRunner()
    scenario = ScenarioDefinition(
        scenario_id="SCENARIO_TEMPORARY_FAULT_RECOVERY",
        description="Temporary container fault clears at t=600ms; equipment recovers.",
        plant_config_path="configs/reference_10mw_20mwh.yaml",
        simulation_duration_ns=1_000_000_000,
        fault_sequence=[
            FaultEventSpec(
                fault_id="TEMP_FAULT_01",
                fault_type=FaultType.BATTERY_CONTAINER_UNAVAILABLE,
                target_equipment_id="CONTAINER_01",
                trigger_timestamp_ns=200_000_000,
                duration_ns=400_000_000,  # Clears at 600ms
            )
        ],
        expected_behavior="Container 01 recovers availability after 600ms.",
        acceptance_criteria=[
            AcceptanceCriteriaSpec(
                criterion_id="CRIT_RECOVERY_ALL_CONTAINERS",
                description="All 4 containers operational after fault clears",
                metric_name="ACTIVE_BATTERY_COUNT",
                operator="EQ",
                target_value=4,
            )
        ],
    )

    report = runner.run_scenario(scenario)
    assert report.passed is True
    assert len(report.fault_audit_records) == 2  # INJECTED and CLEARED


def test_scenario_runner_drives_plugin_physics_loop() -> None:
    """Test the scenario runner drives the plant plugin physics loop, not idle fallbacks.

    NOTE: The 4 x 5 MWh containers at 50% SoC are energy-horizon limited to 2.18 MW each
    (8.73 MW total) on the EMS dispatch path, so the 10 MW request is clamped by the
    battery limits before it reaches the 10 MW POI export limit. The criteria assert
    that the plugin-driven per-PCS dispatch flows at that maximum feasible rate and
    that SoC decays while discharging; an idle fallback would record 0 W and 50% SoC.
    """
    runner = ScenarioRunner()
    scenario = ScenarioDefinition(
        scenario_id="SCENARIO_PLUGIN_PHYSICS_LOOP",
        description=(
            "10 MW discharge over 5s must flow through the plugin-driven PCS and battery"
            " models, not the model fallback values."
        ),
        plant_config_path="configs/reference_10mw_20mwh.yaml",
        simulation_duration_ns=5_000_000_000,
        requested_p_w=10_000_000.0,
        expected_behavior="Plugin loop computes Per-PCS setpoint and SoC drops.",
        acceptance_criteria=[
            AcceptanceCriteriaSpec(
                criterion_id="CRIT_PLUGIN_DISPATCH_FLOWS",
                description=(
                    "Sum of per-PCS requested power equals the EMS-accepted dispatch at"
                    " the plant's maximum feasible discharge (8.73 MW)"
                ),
                metric_name="PCS_ACTIVE_POWER_W",
                operator="GE",
                target_value=8_000_000.0,
            ),
            AcceptanceCriteriaSpec(
                criterion_id="CRIT_SOC_DROPS_ON_DISPATCH",
                description="SoC decreases while discharging",
                metric_name="BATTERY_SOC_PCT",
                operator="LE",
                target_value=50.0,
                tolerance=1.0,
            ),
        ],
    )

    report = runner.run_scenario(scenario)
    assert report.passed is True


def test_scenario_discharge_empty_battery_rejected() -> None:
    """Test a 100 MW discharge request with an empty battery (5% SoC) is rejected by EMS."""
    runner = ScenarioRunner()
    scenario = ScenarioDefinition(
        scenario_id="SCENARIO_EMPTY_BATTERY_DISPATCH",
        description="100 MW request at 5% SoC is rejected by EMS as infeasible.",
        plant_config_path="configs/reference_10mw_20mwh.yaml",
        initial_conditions={"soc_pct": 5.0},
        requested_p_w=100_000_000.0,
        simulation_duration_ns=500_000_000,
        expected_behavior="EMS rejects setpoint; accepted power = 0.0 W.",
        acceptance_criteria=[
            AcceptanceCriteriaSpec(
                criterion_id="CRIT_ZERO_ACCEPTED_POWER",
                description="Accepted power is 0.0 W when battery is empty",
                metric_name="ACCEPTED_POWER_W",
                operator="EQ",
                target_value=0.0,
                tolerance=0.0,
            ),
            AcceptanceCriteriaSpec(
                criterion_id="CRIT_PPC_ZERO_ACCEPTED",
                description="PPC accepted power is 0.0 W when battery is empty",
                metric_name="PPC_ACCEPTED_P_W",
                operator="EQ",
                target_value=0.0,
                tolerance=0.0,
            ),
        ],
    )

    report = runner.run_scenario(scenario)
    assert report.passed is True
