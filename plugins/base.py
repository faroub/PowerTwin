"""Abstract Base Class for All PowerTwin Simulation Plugins."""

import logging
from abc import ABC, abstractmethod
from typing import Any

from backend.app.equipment.base import BaseEquipmentInterface
from backend.app.equipment.models import AlarmRecord, UniversalEquipmentState
from backend.app.simulation.context import SimulationContext
from backend.app.simulation.task import SimulationTask
from plugins.manifest import PluginHealthStatus, PluginManifest

logger = logging.getLogger(__name__)


class BasePlugin(SimulationTask, ABC):
    """Abstract Base Class for all equipment plugins.

    Inherits from SimulationTask to execute natively inside SimulationRunManager's scheduler.
    """

    def __init__(
        self,
        name: str = "BasePlugin",
        phase: int = 1,
        priority: int = 0,
        interval_ticks: int = 1,
    ) -> None:
        super().__init__(
            name=name,
            phase=phase,
            priority=priority,
            interval_ticks=interval_ticks,
            enabled=False,  # Disabled by default per Safety Rules
        )
        self.health_status: PluginHealthStatus = PluginHealthStatus.DISABLED
        self._equipment_interface: BaseEquipmentInterface | None = None

    @property
    @abstractmethod
    def manifest(self) -> PluginManifest:
        """Return metadata manifest for this plugin."""

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate input configuration parameters."""

    @abstractmethod
    def initialize(self, config: dict[str, Any]) -> None:
        """Initialize plugin equipment model state."""

    @abstractmethod
    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        """Execute model tick physics for current tick."""

    def step(self, ctx: SimulationContext, delta_t_s: float) -> None:
        """Forward step to step_plugin for equipment interface compatibility."""
        self.step_plugin(ctx, delta_t_s)

    def execute(self, ctx: SimulationContext) -> None:
        """Execute tick wrapped in fault containment boundary."""
        if not self.enabled or self.health_status == PluginHealthStatus.FAULTED:
            return

        try:
            self.step_plugin(ctx, ctx.delta_t_s)
        except Exception as e:
            self.health_status = PluginHealthStatus.FAULTED
            self.enabled = False
            logger.exception(
                "Fault containment: Plugin '%s' raised exception at tick %d ns",
                self.name,
                ctx.current_tick_ns,
            )
            ctx.emit_event(
                name="PLUGIN_FAULTED",
                source=self.name,
                payload={
                    "plugin_id": self.manifest.plugin_id,
                    "error": str(e),
                    "action": "PLUGIN_SAFE_PARKED",
                },
            )
            raise

    def get_task_state(self) -> dict[str, Any]:
        """Return task state including plugin health and underlying physical model state."""
        state = super().get_task_state()
        state["health_status"] = self.health_status.value
        if hasattr(self, "physical_model") and hasattr(
            self.physical_model, "get_model_state"
        ):
            state["physical_model"] = self.physical_model.get_model_state()
        return state

    def set_task_state(self, state: dict[str, Any]) -> None:
        """Restore task state including plugin health and underlying physical model state."""
        super().set_task_state(state)
        if "health_status" in state:
            self.health_status = PluginHealthStatus(state["health_status"])
        if (
            "physical_model" in state
            and hasattr(self, "physical_model")
            and hasattr(self.physical_model, "set_model_state")
        ):
            self.physical_model.set_model_state(state["physical_model"])

    def get_equipment_state(self) -> UniversalEquipmentState | None:
        """Return underlying equipment state if interface attached."""
        if hasattr(self, "physical_model") and hasattr(
            self.physical_model, "get_state"
        ):
            st = self.physical_model.get_state()
            if isinstance(st, UniversalEquipmentState):
                return st
        if isinstance(self, BaseEquipmentInterface):
            return self.get_state()
        if self._equipment_interface is not None:
            return self._equipment_interface.get_state()
        return None

    def get_alarms(self) -> list[AlarmRecord]:
        """Return active alarms from underlying physical model or equipment interface without recursion."""
        if hasattr(self, "physical_model") and hasattr(
            self.physical_model, "active_alarms"
        ):
            return [a for a in self.physical_model.active_alarms if not a.cleared]
        if self._equipment_interface is not None:
            return self._equipment_interface.get_alarms()
        return []

    @abstractmethod
    def shutdown(self) -> None:
        """Safely clean up plugin resources."""
