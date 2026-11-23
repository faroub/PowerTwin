# PowerTwin — Plugin Architecture Specification

## 1. Overview & Purpose

The PowerTwin plugin subsystem allows third-party developers and equipment manufacturers to integrate custom battery electro-thermal models, proprietary inverter control logic, and specialized EMS dispatch strategies without modifying the core simulation codebase.

---

## 2. Plugin Metadata & Manifest

Every plugin MUST include a metadata declaration class conforming to the `PluginManifest` schema:

```python
from pydantic import BaseModel
from enum import Enum


class PluginCategory(str, Enum):
    BATTERY_MODEL = "BATTERY_MODEL"
    PCS_MODEL = "PCS_MODEL"
    CONTROLLER = "CONTROLLER"
    GRID_SCENARIO = "GRID_SCENARIO"


class PluginManifest(BaseModel):
    plugin_id: str  # e.g., "vendor_acme_lfp_cell_v2"
    name: str
    version: str  # SemVer e.g., "1.2.0"
    min_powertwin_api_version: str  # e.g., "1.0.0"
    category: PluginCategory
    author: str
    capabilities: list[str]
    dependencies: list[str] = []
    is_trusted: bool = False
```

---

## 3. Standardized Plugin Interface

All equipment or controller plugins MUST implement the `BasePlugin` abstract base class:

```python
from abc import ABC, abstractmethod


class BasePlugin(ABC):
    @property
    @abstractmethod
    def manifest(self) -> PluginManifest:
        """Return plugin metadata manifest."""
        pass

    @abstractmethod
    def validate_config(self, config: dict) -> bool:
        """Validate input configuration parameters before initialization."""
        pass

    @abstractmethod
    def initialize(self, config: dict) -> None:
        """Initialize internal state and resources."""
        pass

    @abstractmethod
    def step(self, simulation_tick_ns: int, delta_t_s: float, inputs: dict) -> dict:
        """Execute model calculation for a single simulation tick."""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Clean up plugin resources safely."""
        pass
```

---

## 4. Security, Isolation & Safety Rules

1. **Disabled by Default**: Plugins are strictly ignored upon engine startup unless explicitly declared in the active simulation configuration under `enabled_plugins`.
2. **Prohibition of Arbitrary Path Loading**: Plugins cannot be dynamically loaded from unverified user-supplied file system paths. All plugins must be installed in designated `plugins/` subdirectories and verified against an approved manifest registry.
3. **Fault Containment**:
   - Every invocation of `plugin.step()` is wrapped in an isolated exception handler boundary.
   - If a plugin raises an unhandled exception or outputs non-physical NaN/Inf values, the engine intercepts the fault, sets the plugin status to `FAULTED`, logs the error in the audit log, and safe-parks the associated simulated component without crashing the central engine loop.
4. **No Untrusted Execution**: Plugins are executed within restricted process/thread sandboxes with zero permission to initiate external network sockets or modify filesystem directories outside their allocated configuration path.
