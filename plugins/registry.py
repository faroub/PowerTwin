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
        self._registered_manifests: dict[str, PluginManifest] = {}
        self._active_plugins: dict[str, BasePlugin] = {}

    def register_plugin_class(self, plugin_cls: type[BasePlugin]) -> None:
        """Register a plugin class into the approved registry and cache manifest.

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
            logger.info(
                "Updating existing plugin class registration: '%s'", manifest.plugin_id
            )

        self._registered_classes[manifest.plugin_id] = plugin_cls
        self._registered_manifests[manifest.plugin_id] = manifest
        logger.info(
            "Registered plugin class '%s' (v%s)", manifest.plugin_id, manifest.version
        )

    def validate_api_compatibility(self, manifest: PluginManifest) -> bool:
        """Validate if plugin API version matches registry API version."""
        manifest_major = manifest.api_version.split(".")[0]
        supported_major = self.api_version.split(".")[0]
        return manifest_major == supported_major

    def get_registered_manifests(self) -> list[PluginManifest]:
        """Return list of manifests for all registered plugin classes without
        instantiating objects."""
        return list(self._registered_manifests.values())

    def validate_dependencies(self, instance_key: str) -> bool:
        """Verify all dependencies for a plugin instance are currently registered and enabled."""
        if instance_key not in self._active_plugins:
            return False

        plugin = self._active_plugins[instance_key]
        for dep_id in plugin.manifest.dependencies:
            if (
                dep_id not in self._active_plugins
                or not self._active_plugins[dep_id].enabled
            ):
                logger.error(
                    "Plugin instance '%s' missing enabled dependency '%s'",
                    instance_key,
                    dep_id,
                )
                return False

        return True

    def create_and_initialize(
        self, plugin_id: str, config: dict[str, Any], instance_id: str | None = None
    ) -> BasePlugin:
        """Instantiate, validate configuration, and initialize a registered plugin.

        Plugins remain DISABLED after initialization until explicitly enabled via enable_plugin().
        """
        if plugin_id not in self._registered_classes:
            raise InitializationError(f"Plugin ID '{plugin_id}' is not registered.")

        plugin_cls = self._registered_classes[plugin_id]
        key = instance_id if instance_id else plugin_id
        plugin = plugin_cls()
        plugin.name = key
        if hasattr(plugin, "equipment_id"):
            object.__setattr__(plugin, "equipment_id", key)

        if not plugin.validate_config(config):
            plugin.health_status = PluginHealthStatus.FAULTED
            plugin.enabled = False
            raise InitializationError(
                f"Configuration validation failed for plugin '{plugin_id}' (instance '{key}')"
            )

        try:
            plugin.initialize(config)
            plugin.health_status = PluginHealthStatus.HEALTHY
            plugin.enabled = False  # Plugins remain disabled by default until
            # enable_plugin() is called
            self._active_plugins[key] = plugin
            return plugin
        except Exception as e:
            plugin.health_status = PluginHealthStatus.FAULTED
            plugin.enabled = False
            raise InitializationError(
                f"Plugin '{plugin_id}' instance '{key}' initialization failed: {e}"
            ) from e

    def enable_plugin(self, instance_key: str) -> None:
        """Enable an initialized plugin instance after verifying dependencies."""
        if instance_key not in self._active_plugins:
            raise InitializationError(
                f"Plugin instance '{instance_key}' is not instantiated."
            )

        if not self.validate_dependencies(instance_key):
            raise InitializationError(
                f"Cannot enable plugin instance '{instance_key}': missing active dependencies."
            )

        plugin = self._active_plugins[instance_key]
        if plugin.health_status == PluginHealthStatus.FAULTED:
            raise InitializationError(
                f"Cannot enable faulted plugin instance '{instance_key}'."
            )

        plugin.enabled = True
        plugin.health_status = PluginHealthStatus.HEALTHY
        logger.info("Enabled plugin instance '%s'", instance_key)

    def disable_plugin(self, instance_key: str) -> None:
        """Disable an active plugin instance."""
        if instance_key in self._active_plugins:
            plugin = self._active_plugins[instance_key]
            plugin.enabled = False
            plugin.health_status = PluginHealthStatus.DISABLED
            logger.info("Disabled plugin instance '%s'", instance_key)

    def get_plugin(self, instance_key: str) -> BasePlugin | None:
        """Return active plugin instance by instance_key or equipment_id."""
        return self._active_plugins.get(instance_key)

    def shutdown_all(self) -> None:
        """Safely shutdown all active plugins."""
        for plugin in self._active_plugins.values():
            try:
                plugin.enabled = False
                plugin.shutdown()
            except Exception as e:  # noqa: BLE001
                logger.error("Error shutting down plugin '%s': %s", plugin.name, e)
        self._active_plugins.clear()
