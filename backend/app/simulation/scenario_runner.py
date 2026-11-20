"""Scenario Runner — Automated Execution and Engineering Criteria Evaluation."""

import logging
import math
from typing import Any

from backend.app.simulation.fault_injection import FaultInjectionEngine
from backend.app.simulation.scenario import (
    AcceptanceCriteriaSpec,
    ScenarioDefinition,
    ScenarioTestReport,
)
from backend.app.topology.factory import BuiltPlantInstance, PlantTopologyFactory

logger = logging.getLogger(__name__)


class ScenarioRunner:
    """Automated Scenario Runner executing scenarios and evaluating engineering criteria."""

    def __init__(self, factory: PlantTopologyFactory | None = None) -> None:
        self.factory: PlantTopologyFactory = (
            factory if factory is not None else PlantTopologyFactory()
        )

    def run_scenario(self, scenario: ScenarioDefinition) -> ScenarioTestReport:
        """Build plant, inject scheduled faults, run simulation loop, evaluate acceptance criteria.

        Args:
            scenario: ScenarioDefinition containing plant config, faults, and acceptance criteria.

        Returns:
            ScenarioTestReport detailing pass/fail status and evidence records.
        """
        logger.info("Starting automated scenario run '%s'", scenario.scenario_id)

        # 1. Build Plant Topology
        topology_config = self.factory.load_config_from_yaml(scenario.plant_config_path)
        plant: BuiltPlantInstance = self.factory.build_plant(topology_config)

        # 2. Setup Fault Injection Engine
        fault_engine = FaultInjectionEngine(seed=42)
        for fault in scenario.fault_sequence:
            fault_engine.schedule_fault(fault)

        # 3. Apply Initial Conditions
        init_soc = scenario.initial_conditions.get("soc_pct", 50.0)
        for bat in plant.battery_systems:
            bat.soc_pct = init_soc

        # 4. Execute Simulation Loop Tick by Tick
        tick_step_ns = 10_000_000  # 10 ms tick step
        total_ticks = math.ceil(scenario.simulation_duration_ns / tick_step_ns)
        current_time_ns = 0

        # Layer A Startup
        plant.equipment_controller.execute_startup_sequence(
            bms_list=plant.bms_units,
            pcs_list=plant.pcs_units,
            switchgear=plant.switchgear[0],
            container_temp_c=25.0,
            current_time_ns=current_time_ns,
        )

        recorded_metrics: dict[str, Any] = {}

        for _ in range(total_ticks):
            current_time_ns += tick_step_ns

            # Process Fault Schedule
            fault_engine.process_tick(current_time_ns, plant)

            # EMS & PPC Dispatch Loop
            acc_p, acc_q = plant.ems.dispatch_step(
                requested_p_w=scenario.requested_p_w,
                requested_q_var=scenario.requested_q_var,
                ppc=plant.ppc,
                battery=plant.battery_systems[0],
                bms_list=plant.bms_units,
                pcs_list=plant.pcs_units,
                equipment_controller=plant.equipment_controller,
                grid_frequency_hz=plant.grid.config.nominal_frequency_hz,
                timestamp_ns=current_time_ns,
            )

            # Step Physics
            plant.simulation_engine.step(1)

            # Record final tick metrics
            eq_state = plant.equipment_controller.operating_state.value
            pcs_avail_cnt = sum(1 for pcs in plant.pcs_units if pcs.is_available)
            bat_avail_cnt = sum(1 for b in plant.battery_systems if b.is_available)

            recorded_metrics["POI_ACTIVE_POWER_W"] = acc_p
            recorded_metrics["POI_REACTIVE_POWER_VAR"] = acc_q
            recorded_metrics["ACCEPTED_POWER_W"] = acc_p
            recorded_metrics["EQUIPMENT_CONTROLLER_STATE"] = eq_state
            recorded_metrics["PPC_ACCEPTED_P_W"] = plant.ppc.accepted_p_w
            recorded_metrics["ACTIVE_PCS_COUNT"] = pcs_avail_cnt
            recorded_metrics["ACTIVE_BATTERY_COUNT"] = bat_avail_cnt
            recorded_metrics["EQUIPMENT_CONTROLLER_AVAILABLE"] = (
                plant.equipment_controller.is_available
            )

        # 5. Evaluate Engineering Acceptance Criteria
        criteria_results: list[dict[str, Any]] = []
        overall_passed = True

        for crit in scenario.acceptance_criteria:
            passed_crit = self._evaluate_criterion(crit, recorded_metrics)
            if not passed_crit:
                overall_passed = False

            criteria_results.append(
                {
                    "criterion_id": crit.criterion_id,
                    "description": crit.description,
                    "metric_name": crit.metric_name,
                    "target_value": crit.target_value,
                    "actual_value": recorded_metrics.get(crit.metric_name, None),
                    "passed": passed_crit,
                }
            )

        fault_audit_logs = [record.model_dump() for record in fault_engine.audit_records]

        summary = (
            f"Scenario '{scenario.scenario_id}' completed. "
            f"Result: {'PASSED' if overall_passed else 'FAILED'}. "
            f"Executed {total_ticks} ticks ({scenario.simulation_duration_ns / 1e9:.2f}s)."
        )

        logger.info(summary)

        return ScenarioTestReport(
            scenario_id=scenario.scenario_id,
            description=scenario.description,
            passed=overall_passed,
            total_ticks_executed=total_ticks,
            duration_simulated_s=scenario.simulation_duration_ns / 1e9,
            criteria_results=criteria_results,
            fault_audit_records=fault_audit_logs,
            summary_notes=summary,
        )

    def _evaluate_criterion(self, crit: AcceptanceCriteriaSpec, metrics: dict[str, Any]) -> bool:
        """Evaluate a single engineering criterion against recorded metrics."""
        actual = metrics.get(crit.metric_name)
        target = crit.target_value
        op = crit.operator.upper()

        if actual is None:
            return False

        if op == "EQ":
            return actual == target
        elif op == "NE":
            return actual != target
        elif op == "LE":
            return actual <= target
        elif op == "GE":
            return actual >= target
        elif op == "APPROX":
            return abs(actual - target) <= crit.tolerance
        return False
