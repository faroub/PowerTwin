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
        name: str,
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
        pass

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> bool:
        """Validate input configuration parameters."""
        pass

    @abstractmethod
    def initialize(self, config: dict[str, Any]) -> None:
        """Initialize plugin equipment model state."""
        pass

    @abstractmethod
    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        """Execute model tick physics for current tick."""
        pass

    def execute(self, ctx: SimulationContext) -> None:
        """Execute tick wrapped in fault containment boundary."""
        if not self.enabled or self.health_status == PluginHealthStatus.FAULTED:
            return

        try:
            self.step_plugin(ctx, ctx.delta_t_s)
        except Exception as e:
            self.health_status = PluginHealthStatus.FAULTED
            self.enabled = False
            logger.error(
                "Fault containment: Plugin '%s' raised exception at tick %d ns: %s",
                self.name,
                ctx.current_tick_ns,
                e,
                exc_info=True,
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

    def get_equipment_state(self) -> UniversalEquipmentState | None:
        """Return underlying equipment state if interface attached."""
        if self._equipment_interface is not None:
            return self._equipment_interface.get_state()
        return None

    def get_alarms(self) -> list[AlarmRecord]:
        """Return active alarms from underlying equipment interface."""
        if self._equipment_interface is not None:
            return self._equipment_interface.get_alarms()
        return []

    @abstractmethod
    def shutdown(self) -> None:
        """Safely clean up plugin resources."""
        pass
