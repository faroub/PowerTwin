"""Application wiring for the authoritative simulation execution pipeline.

This module is the single place where a plant is turned into a live, bound,
engine-bound plant instance:

    plant topology config  ->  built plant  ->  engine  ->  runner thread

The plant is built on application **start-up** (so the API never depends on a
module-level global) and released on **shutdown** (so the execution thread
terminates and every plugin is stopped).

Typical usage::

    from backend.app.simulation.application import init_simulation, close_simulation

    async def lifespan(app: FastAPI):
        init_simulation(app)
        yield
        close_simulation(app)
"""

import logging
from typing import Any

from backend.app.core.config import settings
from backend.app.simulation.runtime import (
    get_simulation_runtime,
)
from backend.app.topology.factory import PlantTopologyFactory

logger = logging.getLogger(__name__)


def init_simulation(app: Any = None) -> dict[str, Any]:
    """Build the configured plant and bind it to the application-scoped runtime.

    The plant is constructed from ``settings.TOPOLOGY_CONFIG_PATH`` (an explicit,
    documented configuration) and the engine configuration is derived from the
    ``SIMULATION_*`` settings. When no topology path is configured, the engine
    starts detached (``NOT_CONNECTED``) so the application still serves the
    telemetry endpoints while a plant is built by another controller component.

    Returns:
        A status dict describing the plant and the engine configuration.
    """
    topology_path = settings.TOPOLOGY_CONFIG_PATH
    runtime = get_simulation_runtime(app=app)
    if topology_path:
        topology_config = PlantTopologyFactory.load_config_from_yaml(topology_path)
        plant = PlantTopologyFactory().build_plant(
            topology_config,
            sim_config=settings.create_simulation_configuration(),
            source_path=topology_path,
        )
        if app is not None:
            runtime.bind_to_app(app)
        runtime.attach_plant(plant)
        logger.info(
            "Plant built: %s (%s; %d containers, %d PCS, %d transformers, %d meters)",
            plant.topology_config.name,
            plant.topology_config.plant_id,
            len(plant.battery_systems),
            len(plant.pcs_units),
            len(plant.transformers),
            len(plant.meters),
        )
        return {
            "plant_configured": True,
            "plant_topic": topology_config.plant_id,
            "runtime": runtime.status(),
        }

    logger.info("No TOPOLOGY_CONFIG_PATH configured; starting without a plant instance.")
    if app is not None:
        runtime.bind_to_app(app)
    return {
        "plant_configured": False,
        "engine_state": "NOT_CONNECTED",
        "message": "No topology path configured: engine is attached, no plant.",
    }


def close_simulation(app: Any = None) -> None:
    """Stop the execution thread, release the engine and shut down the plugins."""
    runtime = get_simulation_runtime(app=app)
    runtime.shutdown()
    runtime.drop()
    logger.info("Simulation runtime released.")
