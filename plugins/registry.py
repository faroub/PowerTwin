"""Controlled Plugin Registry and Lifecycle Manager.

Strictly manages plugin registration, validation, activation, dependency checking,
and safety boundaries. Loading arbitrary Python files from untrusted user paths is PROHIBITED.
"""

import logging
from typing import Any

from backend.app.simulation.exceptions import InitializationError
from plugins.base import BasePlugin
from plugins.manifest import PluginHealthStatus, PluginManifest

logger = logging.getLogger(__name__)

CURRENT_API_VERSION: str = "0.1.0"


class PluginRegistry:
    """Registry managing plugin discovery, validation, enabling, and lifecycle."""

    def __init__(self, api_version: str = CURRENT_API_VERSION) -> None:
        self.api_version: str = api_version
        self._registered_classes: dict[str, type[BasePlugin]] = {}
        self._active_plugins: dict[str, BasePlugin] = {}

    def register_plugin_class(self, plugin_cls: type[BasePlugin]) -> None:
        """Register a plugin class into the approved registry.

        Args:
            plugin_cls: Subclass of BasePlugin.
        """
        dummy = plugin_cls()
        manifest = dummy.manifest

        if not self.validate_api_compatibility(manifest):
            raise InitializationError(
                f"Plugin '{manifest.plugin_id}' API version '{manifest.api_version}' "
                f"incompatible with supported version '{self.api_version}'"
            )

        if manifest.plugin_id in self._registered_classes:
            logger.warning(
                "Overwriting existing plugin class registration: '%s'", manifest.plugin_id
            )

        self._registered_classes[manifest.plugin_id] = plugin_cls
        logger.info("Registered plugin class '%s' (v%s)", manifest.plugin_id, manifest.version)

    def validate_api_compatibility(self, manifest: PluginManifest) -> bool:
        """Validate if plugin API version matches registry API version."""
        manifest_major = manifest.api_version.split(".")[0]
        supported_major = self.api_version.split(".")[0]
        return manifest_major == supported_major

    def get_registered_manifests(self) -> list[PluginManifest]:
        """Return list of manifests for all registered plugin classes."""
        manifests: list[PluginManifest] = []
        for cls in self._registered_classes.values():
            manifests.append(cls().manifest)
        return manifests

    def validate_dependencies(self, plugin_id: str) -> bool:
        """Verify all dependencies for a plugin are currently registered and enabled."""
        if plugin_id not in self._registered_classes:
            return False

        dummy = self._registered_classes[plugin_id]()
        for dep_id in dummy.manifest.dependencies:
            if dep_id not in self._active_plugins or not self._active_plugins[dep_id].enabled:
                logger.error("Plugin '%s' missing enabled dependency '%s'", plugin_id, dep_id)
                return False

        return True

    def create_and_initialize(
        self, plugin_id: str, config: dict[str, Any]
    ) -> BasePlugin:
        """Instantiate, validate configuration, and initialize a registered plugin.

        Args:
            plugin_id: Unique string identifier of registered plugin class.
            config: Configuration dictionary.

        Returns:
            Initialized BasePlugin instance (disabled by default per safety rules).
        """
        if plugin_id not in self._registered_classes:
            raise InitializationError(f"Plugin ID '{plugin_id}' is not registered.")

        plugin_cls = self._registered_classes[plugin_id]
        plugin = plugin_cls()

        if not plugin.validate_config(config):
            raise InitializationError(f"Configuration validation failed for plugin '{plugin_id}'")

        try:
            plugin.initialize(config)
            plugin.health_status = PluginHealthStatus.HEALTHY
            self._active_plugins[plugin_id] = plugin
            return plugin
        except Exception as e:
            plugin.health_status = PluginHealthStatus.FAULTED
            raise InitializationError(f"Plugin '{plugin_id}' initialization failed: {e}") from e

    def enable_plugin(self, plugin_id: str) -> None:
        """Enable an initialized plugin after verifying dependencies."""
        if plugin_id not in self._active_plugins:
            raise InitializationError(f"Plugin '{plugin_id}' is not instantiated.")

        if not self.validate_dependencies(plugin_id):
            raise InitializationError(
                f"Cannot enable plugin '{plugin_id}': missing active dependencies."
            )

        plugin = self._active_plugins[plugin_id]
        if plugin.health_status == PluginHealthStatus.FAULTED:
            raise InitializationError(f"Cannot enable faulted plugin '{plugin_id}'.")

        plugin.enabled = True
        plugin.health_status = PluginHealthStatus.HEALTHY
        logger.info("Enabled plugin '%s'", plugin_id)

    def disable_plugin(self, plugin_id: str) -> None:
        """Disable an active plugin."""
        if plugin_id in self._active_plugins:
            plugin = self._active_plugins[plugin_id]
            plugin.enabled = False
            plugin.health_status = PluginHealthStatus.DISABLED
            logger.info("Disabled plugin '%s'", plugin_id)

    def get_plugin(self, plugin_id: str) -> BasePlugin | None:
        """Return active plugin instance by plugin_id."""
        return self._active_plugins.get(plugin_id)

    def shutdown_all(self) -> None:
        """Safely shutdown all active plugins."""
        for plugin in self._active_plugins.values():
            try:
                plugin.enabled = False
                plugin.shutdown()
            except Exception as e:  # noqa: BLE001
                logger.error("Error shutting down plugin '%s': %s", plugin.name, e)
        self._active_plugins.clear()
