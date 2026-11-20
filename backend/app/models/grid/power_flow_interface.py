"""Power Flow Solver Interface for Future Pandapower or OpenDSS Integration.

DOCUMENTED DESIGN:
  SimplePhasorPowerFlowSolver provides fundamental RMS phasor power flow solution for WP04C.
  PandaPowerOpenDSSInterfaceStub provides an extensible interface definition for external
  AC load-flow solvers (Pandapower / OpenDSS) in future WP06 distribution network extensions.
"""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class PowerFlowResult(BaseModel):
    """Power flow solver solution payload."""

    bus_voltages_v: dict[str, float] = Field(default_factory=dict)
    branch_currents_a: dict[str, float] = Field(default_factory=dict)
    active_power_losses_w: float = 0.0
    reactive_power_losses_var: float = 0.0
    converged: bool = True


class PowerFlowSolverInterface(ABC):
    """Abstract interface for AC power flow calculation engines."""

    @abstractmethod
    def solve_power_flow(
        self,
        grid_voltage_v: float,
        grid_frequency_hz: float,
        plant_p_w: float,
        plant_q_var: float,
        network_params: dict[str, Any],
    ) -> PowerFlowResult:
        """Solve network voltage, current, and losses."""
        pass


class SimplePhasorPowerFlowSolver(PowerFlowSolverInterface):
    """Steady-state 1-bus RMS phasor power flow solver."""

    def solve_power_flow(
        self,
        grid_voltage_v: float,
        grid_frequency_hz: float,
        plant_p_w: float,
        plant_q_var: float,
        network_params: dict[str, Any],
    ) -> PowerFlowResult:
        r_grid = network_params.get("r_grid_ohm", 0.05)
        x_grid = network_params.get("x_grid_ohm", 0.20)

        # Delta V ~ (P*R + Q*X) / V_grid
        v_drop = ((plant_p_w * r_grid) + (plant_q_var * x_grid)) / max(1.0, grid_voltage_v)
        v_poi = grid_voltage_v + v_drop

        s_actual = (plant_p_w**2 + plant_q_var**2) ** 0.5
        i_actual = s_actual / (1.73205 * max(1.0, v_poi))

        p_loss = (i_actual**2) * r_grid
        q_loss = (i_actual**2) * x_grid

        return PowerFlowResult(
            bus_voltages_v={"POI": v_poi, "GRID": grid_voltage_v},
            branch_currents_a={"GRID_BRANCH": i_actual},
            active_power_losses_w=p_loss,
            reactive_power_losses_var=q_loss,
            converged=True,
        )


class PandaPowerOpenDSSInterfaceStub(PowerFlowSolverInterface):
    """Placeholder interface stub for external Pandapower / OpenDSS solvers."""

    def solve_power_flow(
        self,
        grid_voltage_v: float,
        grid_frequency_hz: float,
        plant_p_w: float,
        plant_q_var: float,
        network_params: dict[str, Any],
    ) -> PowerFlowResult:
        raise NotImplementedError(
            "PandaPower/OpenDSS external power flow solver integration is a structured stub. "
            "Use SimplePhasorPowerFlowSolver for WP04C."
        )
