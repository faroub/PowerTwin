"""Application-layer wiring of the warranty recorder.

The wiring is what turns the warranty analysis from a library into a working
feature: it attaches the recorder to the running plant and detaches it again.

It mirrors `backend/app/historian/wiring.py` on purpose. The recorder
registers *itself* as a scheduled task from the application layer, so the
simulation engine never imports the warranty analysis and never holds a
database session (`AGENTS.md` §3).
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.core.config import settings
from backend.app.historian.wiring import HISTORIAN_SERVICE_KEY
from backend.app.warranty.parameters import deployment_parameters
from backend.app.warranty.recorder import WarrantyRecorder

logger = logging.getLogger(__name__)

WARRANTY_RECORDER_KEY = "warranty_recorder"


def start_warranty_recorder(app: Any) -> WarrantyRecorder | None:
    """Attach a warranty recorder to the running plant.

    Returns the recorder, or nothing when the platform runs without a plant
    or with the warranty analysis switched off. Nothing is raised when the
    recorder cannot be attached: a platform that cannot analyse its warranty
    state must still simulate.

    The call is idempotent. A recorder that is already attached is detached
    first, so re-attaching — after a plant rebuild, say — replaces it rather
    than colliding with the task name it already holds on the scheduler.
    """
    if not settings.WARRANTY_ENABLED:
        logger.info("The warranty analysis is switched off; no snapshot is recorded.")
        return None

    runtime = getattr(app.state, "simulation_runtime", None)
    plant = getattr(runtime, "active_plant", None)
    engine = getattr(runtime, "engine", None)
    if plant is None or engine is None:
        logger.info("No plant is attached; the warranty recorder stays idle.")
        return None

    # Detach a recorder that is already attached, so the scheduler never sees
    # two tasks with the same name.
    stop_warranty_recorder(app)

    # The recorder writes into the historian's buffer, so it needs the
    # historian's service. The historian may be switched off while the
    # warranty analysis is on; in that case there is nothing to write into
    # and the recorder stays idle rather than building a second store.
    service = getattr(app.state, HISTORIAN_SERVICE_KEY, None)
    if service is None:
        logger.info(
            "The historian is switched off; the warranty recorder has nowhere to write "
            "its snapshots and stays idle."
        )
        return None

    recorder = WarrantyRecorder(
        plant=plant,
        sink=service,
        run_id=engine.simulation_run_id,
        sample_interval_ticks=settings.WARRANTY_SAMPLE_INTERVAL_TICKS,
        parameters=deployment_parameters(),
    )
    engine.scheduler.register_task(recorder)
    setattr(app.state, WARRANTY_RECORDER_KEY, recorder)

    logger.info(
        "The warranty recorder is attached: every %d ticks, %d container(s) analysed.",
        recorder.sample_interval_ticks,
        len(getattr(plant, "battery_systems", None) or []),
    )
    return recorder


def stop_warranty_recorder(app: Any) -> None:
    """Detach the warranty recorder from the running plant."""
    recorder = getattr(app.state, WARRANTY_RECORDER_KEY, None)
    if recorder is None:
        return

    runtime = getattr(app.state, "simulation_runtime", None)
    engine = getattr(runtime, "engine", None)
    if engine is not None:
        try:
            engine.scheduler.unregister_task(recorder.name)
        except Exception as err:  # noqa: BLE001
            logger.warning("The warranty recorder could not be unregistered: %s", err)

    setattr(app.state, WARRANTY_RECORDER_KEY, None)
    logger.info("The warranty recorder analysed %s", recorder.status)
