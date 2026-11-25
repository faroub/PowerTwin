"""Plugin Manifest and Metadata Definitions."""

from enum import StrEnum

from pydantic import BaseModel, Field


class PluginCategory(StrEnum):
    """Categorization of simulation plugins."""

    BATTERY = "BATTERY"
    PCS = "PCS"
    GRID = "GRID"
    AUXILIARY = "AUXILIARY"
    CONTROLLER = "CONTROLLER"
    METER = "METER"
    TRANSFORMER = "TRANSFORMER"
    SWITCHGEAR = "SWITCHGEAR"
    GRID_SERVICE = "GRID_SERVICE"


class PluginHealthStatus(StrEnum):
    """Health status of a plugin component."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAULTED = "FAULTED"
    DISABLED = "DISABLED"


class PluginManifest(BaseModel):
    """Metadata manifest describing a simulation plugin."""

    plugin_id: str = Field(description="Unique string identifier e.g. 'generic_battery_v1'")
    name: str = Field(description="Human-readable plugin name")
    version: str = Field(default="1.0.0", description="Plugin SemVer version string")
    api_version: str = Field(
        default="0.1.0", description="PowerTwin plugin API compatibility version"
    )
    category: PluginCategory
    author: str = Field(default="PowerTwin Open Core")
    capabilities: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list, description="List of required plugin_ids")
