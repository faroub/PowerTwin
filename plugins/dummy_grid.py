"""Dummy Grid Equipment Plugin."""

from typing import Any
from backend.app.equipment.interfaces.grid import GridModelConfig, GridModelInterface
from backend.app.equipment.models import (
    EquipmentMetadata,
    OperatingState,
    TelemetryPoint,
    UniversalEquipmentState,
)
from backend.app.simulation.context import SimulationContext
from plugins.base import BasePlugin
from plugins.manifest import PluginCategory, PluginManifest


class DummyGridPlugin(BasePlugin, GridModelInterface):
    """Dummy Grid model executing in Phase 1 (Environment & Grid)."""

    def __init__(self, equipment_id: str = "DUMMY_GRID_01") -> None:
        BasePlugin.__init__(
            self,
            name=equipment_id,
            phase=1,  # Phase 1: Environment & Grid
            priority=5,
            interval_ticks=1,
        )
        GridModelInterface.__init__(self, equipment_id=equipment_id)
        self._config: GridModelConfig = GridModelConfig()
        self.frequency_hz: float = 60.0
        self.voltage_v: float = 13800.0

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id="dummy_grid_v1",
            name="Dummy Synthetic Grid Plugin",
            version="1.0.0",
            api_version="0.1.0",
            category=PluginCategory.GRID,
            author="PowerTwin Core",
            capabilities=["synthetic_frequency", "synthetic_voltage"],
            dependencies=[],
        )

    def validate_config(self, config: dict[str, Any]) -> bool:
        try:
            GridModelConfig(**config)
            return True
        except Exception:
            return False

    def initialize(self, config: dict[str, Any]) -> None:
        self._config = GridModelConfig(**config)
        self.frequency_hz = self._config.nominal_frequency_hz
        self.voltage_v = self._config.nominal_voltage_v
        self._operating_state = OperatingState.RUNNING
        self._is_available = True
        self._is_initialized = True

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        # Generate small deterministic frequency jitter
        jitter = ctx.random.gauss(mu=0.0, sigma=0.005)
        self.frequency_hz = self._config.nominal_frequency_hz + jitter

        ctx.shared_state["grid_frequency_hz"] = self.frequency_hz
        ctx.shared_state["grid_voltage_v"] = self.voltage_v

    def process_command(self, cmd: dict[str, Any]) -> bool:
        if "target_frequency_hz" in cmd:
            self.frequency_hz = float(cmd["target_frequency_hz"])
            return True
        return False

    def get_state(self) -> UniversalEquipmentState:
        t_ns = getattr(self, "last_execution_tick_ns", 0) or 0
        return UniversalEquipmentState(
            equipment_id=self.equipment_id,
            equipment_type=self.equipment_type,
            metadata=EquipmentMetadata(manufacturer="Generic", model_name="Synthetic Grid Node"),
            operating_state=self._operating_state,
            is_available=self._is_available,
            timestamp_ns=t_ns,
            measurements={
                "frequency_hz": TelemetryPoint(
                    value=self.frequency_hz, unit="Hz", timestamp_ns=t_ns, source_id=self.equipment_id
                ),
                "voltage_v": TelemetryPoint(
                    value=self.voltage_v, unit="V", timestamp_ns=t_ns, source_id=self.equipment_id
                ),
            },
        )

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "nominal_frequency_hz": self._config.nominal_frequency_hz,
            "nominal_voltage_v": self._config.nominal_voltage_v,
        }

    def shutdown(self) -> None:
        self._operating_state = OperatingState.OFF
        self._is_available = False
