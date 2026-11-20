"""Scenario Format and Engineering Acceptance Criteria Specifications."""

from typing import Any

from pydantic import BaseModel, Field

from backend.app.simulation.fault_injection import FaultEventSpec


class AcceptanceCriteriaSpec(BaseModel):
    """Specification for evaluating engineering acceptance criteria."""

    criterion_id: str = Field(description="Unique criterion ID e.g. 'CRIT_01'")
    description: str = Field(description="Human-readable criterion description")
    metric_name: str = Field(
        description="Metric name e.g. 'POI_EXPORT_W', 'PPC_STATE', 'ACCEPTED_POWER_W'"
    )
    operator: str = Field(
        default="EQ", description="Comparison operator: 'LE', 'GE', 'EQ', 'NE', 'APPROX'"
    )
    target_value: Any = Field(description="Expected target value")
    tolerance: float = Field(default=0.0, description="Tolerance band for numerical comparison")


class ScenarioDefinition(BaseModel):
    """Declarative Scenario Format Specification."""

    scenario_id: str = Field(description="Unique scenario ID e.g. 'SCENARIO_01'")
    description: str = Field(description="Detailed scenario description")
    plant_config_path: str = Field(
        default="configs/reference_10mw_20mwh.yaml", description="YAML plant config filepath"
    )
    initial_conditions: dict[str, Any] = Field(
        default_factory=dict, description="Initial SoC, voltages, temperatures"
    )
    controller_config: dict[str, Any] = Field(default_factory=dict)
    grid_config: dict[str, Any] = Field(default_factory=dict)
    simulation_duration_ns: int = Field(
        default=1_000_000_000, description="Scenario duration in nanoseconds (e.g. 1 second)"
    )
    requested_p_w: float = Field(default=0.0, description="Requested active power setpoint")
    requested_q_var: float = Field(default=0.0, description="Requested reactive power setpoint")
    fault_sequence: list[FaultEventSpec] = Field(
        default_factory=list, description="Sequence of scheduled fault events"
    )
    expected_behavior: str = Field(description="Summary of expected physical/control response")
    acceptance_criteria: list[AcceptanceCriteriaSpec] = Field(
        default_factory=list, description="Explicit engineering acceptance criteria"
    )


class ScenarioTestReport(BaseModel):
    """Structured Test Report generated after scenario execution."""

    scenario_id: str
    description: str
    passed: bool
    total_ticks_executed: int
    duration_simulated_s: float
    criteria_results: list[dict[str, Any]]
    fault_audit_records: list[dict[str, Any]]
    summary_notes: str
