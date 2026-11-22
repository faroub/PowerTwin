"""Scenario Runner — Automated Execution and Engineering Criteria Evaluation.

The scenario runner drives the **authoritative simulation execution pipeline**
through ``PlantTopologyFactory``. It never implements its own physics loop:

    * The plant is built by the topology factory, which registers every
      equipment plugin and plant-level task (Control, Distribution, Network)
      on the engine.
    * The scenario request is written into the shared state as the EMS request,
      so the PlantControlTask derives the accepted dispatch deterministically.
    * Metrics are recorded from the real physical models (PCS actual power,
      battery SoC, POI measurements) rather than from dispatched setpoints.
"""

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
        """Build plant, inject scheduled faults, run the simulation pipeline, evaluate criteria.

        Args:
            scenario: ScenarioDefinition containing plant config, faults, and acceptance criteria.

        Returns:
            ScenarioTestReport detailing pass/fail status and evidence records.
        """
        logger.info("Starting automated scenario run '%s'", scenario.scenario_id)

        # 1. Build Plant Topology (authoritative plant + pipeline tasks)
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

        # 4. Equipment Controller Layer-A Startup Sequence
        if plant.switchgear:
            plant.equipment_controller.execute_startup_sequence(
                bms_list=plant.bms_units,
                pcs_list=plant.pcs_units,
                switchgear=plant.switchgear[0],
                container_temp_c=25.0,
                current_time_ns=0,
            )

        engine = plant.simulation_engine
        engine.start()

        # 5. Execute the Authoritative Simulation Pipeline Tick by Tick
        tick_step_ns = engine.config.tick_step_ns
        total_ticks = math.ceil(scenario.simulation_duration_ns / tick_step_ns)
        current_time_ns = 0
        aborted: str | None = None

        recorded_metrics: dict[str, Any] = {}

        for _ in range(total_ticks):
            current_time_ns += tick_step_ns

            # Process scheduled faults against the plant instances.
            fault_engine.process_tick(current_time_ns, plant)

            # EMS/PPC setpoints travel through the shared state so the engine's
            # PlantControlTask can derive the accepted dispatch and per-PCS
            # commands deterministically.
            engine.context.shared_state["ems_requested_p_w"] = float(
                scenario.requested_p_w if math.isfinite(scenario.requested_p_w) else 0.0
            )
            engine.context.shared_state["ems_requested_q_var"] = float(
                scenario.requested_q_var if math.isfinite(scenario.requested_q_var) else 0.0
            )

            # Step the authoritative pipeline (Phase 2 -> Phase 5).
            try:
                engine.step(1)
            except Exception as err:  # noqa: BLE001
                logger.error("Simulation pipeline failed at t=%d ns: %s", current_time_ns, err)
                aborted = f"Simulation pipeline failed at t={current_time_ns} ns: {err}"
                break

            # Record authoritative physical measurements from the live plant.
            recorded_metrics["POI_ACTIVE_POWER_W"] = plant.poi.active_power_w
            recorded_metrics["POI_REACTIVE_POWER_VAR"] = plant.poi.reactive_power_var
            recorded_metrics["ACCEPTED_POWER_W"] = engine.shared_state.get("ems_accepted_p_w", 0.0)
            recorded_metrics["EQUIPMENT_CONTROLLER_STATE"] = (
                plant.equipment_controller.operating_state.value
            )
            recorded_metrics["PPC_ACCEPTED_P_W"] = plant.ppc.accepted_p_w
            recorded_metrics["ACTIVE_PCS_COUNT"] = sum(
                1 for pcs in plant.pcs_units if pcs.is_available
            )
            recorded_metrics["ACTIVE_BATTERY_COUNT"] = sum(
                1 for b in plant.battery_systems if b.is_available
            )
            recorded_metrics["EQUIPMENT_CONTROLLER_AVAILABLE"] = (
                plant.equipment_controller.is_available
            )
            # Authoritative per-PCS physics outputs (plugin-driven, not setpoints).
            recorded_metrics["PCS_ACTIVE_POWER_W"] = float(
                sum(pcs.actual_p_w for pcs in plant.pcs_units)
            )
            recorded_metrics["BATTERY_SOC_PCT"] = sum(
                b.soc_pct for b in plant.battery_systems
            ) / max(1, len(plant.battery_systems))

        # 6. Evaluate Engineering Acceptance Criteria
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

        if aborted is not None:
            summary += f" Aborted: {aborted}."
            overall_passed = False

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
            return bool(actual == target)
        elif op == "NE":
            return bool(actual != target)
        elif op == "LE":
            return bool(actual <= target)
        elif op == "GE":
            return bool(actual >= target)
        elif op == "APPROX":
            return bool(abs(actual - target) <= crit.tolerance)
        return False
