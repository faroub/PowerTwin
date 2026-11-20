"""PowerTwin Equipment Plugin Framework Package."""

from plugins.base import BasePlugin
from plugins.dummy_auxiliary import DummyAuxiliaryPlugin
from plugins.dummy_grid import DummyGridPlugin
from plugins.generic_battery import GenericBatteryPlugin
from plugins.generic_pcs import GenericPCSPlugin
from plugins.manifest import PluginCategory, PluginHealthStatus, PluginManifest
from plugins.registry import CURRENT_API_VERSION, PluginRegistry

__all__ = [
    "CURRENT_API_VERSION",
    "BasePlugin",
    "DummyAuxiliaryPlugin",
    "DummyGridPlugin",
    "GenericBatteryPlugin",
    "GenericPCSPlugin",
    "PluginCategory",
    "PluginHealthStatus",
    "PluginManifest",
    "PluginRegistry",
]
