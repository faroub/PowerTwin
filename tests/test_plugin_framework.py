"""Automated Test Suite for Plugin Framework and Reference Plugins."""

from typing import Any
import pytest
from backend.app.equipment.models import OperatingState
from backend.app.simulation.context import SimulationContext
from backend.app.simulation.exceptions import InitializationError
from backend.app.simulation.manager import SimulationRunManager
from backend.app.simulation.task import SimulationTask
from plugins.base import BasePlugin
from plugins.dummy_auxiliary import DummyAuxiliaryPlugin
from plugins.dummy_grid import DummyGridPlugin
from plugins.generic_battery import GenericBatteryPlugin
from plugins.generic_pcs import GenericPCSPlugin
from plugins.manifest import PluginCategory, PluginHealthStatus, PluginManifest
from plugins.registry import PluginRegistry


class IncompatiblePlugin(BasePlugin):
    """Test plugin with incompatible API version."""

    def __init__(self) -> None:
        super().__init__(name="IncompatiblePlugin")

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id="incompatible_plugin",
            name="Incompatible Plugin",
            version="1.0.0",
            api_version="99.0.0",  # Incompatible!
            category=PluginCategory.BATTERY,
        )

    def validate_config(self, config: dict[str, Any]) -> bool:
        return True

    def initialize(self, config: dict[str, Any]) -> None:
        pass

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        pass

    def shutdown(self) -> None:
        pass


class DependentPlugin(BasePlugin):
    """Test plugin declaring a dependency on generic_battery_v1."""

    def __init__(self) -> None:
        super().__init__(name="DependentPlugin")

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id="dependent_plugin",
            name="Dependent Plugin",
            version="1.0.0",
            api_version="0.1.0",
            category=PluginCategory.CONTROLLER,
            dependencies=["generic_battery_v1"],  # Depends on battery
        )

    def validate_config(self, config: dict[str, Any]) -> bool:
        return True

    def initialize(self, config: dict[str, Any]) -> None:
        pass

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        pass

    def shutdown(self) -> None:
        pass


class CustomSolarPVPlugin(BasePlugin):
    """Demonstration of a new custom equipment plugin registered dynamically."""

    def __init__(self, equipment_id: str = "SOLAR_PV_01") -> None:
        super().__init__(name=equipment_id, phase=1, priority=20)
        self.solar_output_w: float = 0.0

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            plugin_id="custom_solar_pv_v1",
            name="Custom Solar PV Generator Plugin",
            version="1.0.0",
            api_version="0.1.0",
            category=PluginCategory.GRID_SERVICE,
            author="Third Party Vendor",
        )

    def validate_config(self, config: dict[str, Any]) -> bool:
        return "peak_capacity_w" in config

    def initialize(self, config: dict[str, Any]) -> None:
        self.solar_output_w = float(config["peak_capacity_w"])
        self.health_status = PluginHealthStatus.HEALTHY

    def step_plugin(self, ctx: SimulationContext, delta_t_s: float) -> None:
        ctx.shared_state["solar_output_w"] = self.solar_output_w

    def shutdown(self) -> None:
        self.solar_output_w = 0.0


def test_plugin_registration_and_api_compatibility() -> None:
    """Test registration and API compatibility validation."""
    registry = PluginRegistry(api_version="0.1.0")

    # Register valid plugin
    registry.register_plugin_class(GenericBatteryPlugin)
    manifests = registry.get_registered_manifests()
    assert len(manifests) == 1
    assert manifests[0].plugin_id == "generic_battery_v1"

    # Incompatible plugin registration fails
    with pytest.raises(InitializationError):
        registry.register_plugin_class(IncompatiblePlugin)


def test_invalid_configuration_rejection() -> None:
    """Test rejection of invalid plugin configuration."""
    registry = PluginRegistry()
    registry.register_plugin_class(GenericBatteryPlugin)

    # Invalid config (negative voltage)
    with pytest.raises(InitializationError):
        registry.create_and_initialize("generic_battery_v1", {"nominal_voltage_v": -500})


def test_missing_dependency_validation() -> None:
    """Test enabling plugin fails if declared dependency is missing."""
    registry = PluginRegistry()
    registry.register_plugin_class(DependentPlugin)
    registry.register_plugin_class(GenericBatteryPlugin)

    # Instantiate dependent plugin
    dep_inst = registry.create_and_initialize("dependent_plugin", {})

    # Enable fails because generic_battery_v1 is not instantiated/enabled
    with pytest.raises(InitializationError):
        registry.enable_plugin("dependent_plugin")


def test_plugin_lifecycle_and_execution() -> None:
    """Test full plugin lifecycle: Register -> Initialize -> Enable -> Step -> Shutdown."""
    registry = PluginRegistry()
    registry.register_plugin_class(GenericBatteryPlugin)
    registry.register_plugin_class(GenericPCSPlugin)

    battery = registry.create_and_initialize("generic_battery_v1", {"initial_soc_pct": 75.0})
    pcs = registry.create_and_initialize("generic_pcs_v1", {"rated_power_w": 2_000_000.0})

    registry.enable_plugin("generic_battery_v1")
    registry.enable_plugin("generic_pcs_v1")

    assert battery.enabled is True
    assert pcs.enabled is True

    # Connect to SimulationRunManager
    runner = SimulationRunManager()
    runner.register_task(battery)
    runner.register_task(pcs)

    # Set discharge demand setpoint
    runner.shared_state["pcs_cmd_active_power_w"] = 1_000_000.0  # 1 MW discharge

    runner.step(10)  # Run 10 steps (100ms)

    assert runner.shared_state["battery_current_a"] > 0  # Discharging
    assert battery.get_equipment_state().operating_state == OperatingState.RUNNING

    registry.shutdown_all()
    assert battery.enabled is False


def test_engine_independence_with_new_custom_plugin() -> None:
    """Demonstrate a new custom plugin can be registered and run without altering simulation engine."""
    registry = PluginRegistry()
    registry.register_plugin_class(CustomSolarPVPlugin)

    solar_plugin = registry.create_and_initialize("custom_solar_pv_v1", {"peak_capacity_w": 25_000_000.0})
    registry.enable_plugin("custom_solar_pv_v1")

    # Pure simulation engine without modifications
    engine = SimulationRunManager()
    engine.register_task(solar_plugin)

    engine.step(1)

    # State updated cleanly by custom solar plugin
    assert engine.shared_state["solar_output_w"] == 25_000_000.0
