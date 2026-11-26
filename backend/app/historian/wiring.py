"""Application-layer wiring of the historian recorder.

This module is the bridge between the running simulation and the historian's
time-series store. It lives in the application layer on purpose:

* ``AGENTS.md`` §3 requires the simulation engine to stay independent of the
  database. The recorder registers *itself* as a scheduled task from here, so
  the engine never imports the historian and never holds a database session.
* ``AGENTS.md`` §6 requires the simulation to be driven by deterministic time.
  The recorder samples on tick boundaries, so the recorded series is a
  function of the run and not of how fast the host happened to be.

The flush runs on the event loop, never on the simulation thread: the
simulation thread only ever puts a payload on the historian's non-blocking
queue.
"""

import asyncio
import logging
from typing import Any

from backend.app.core.config import settings
from backend.app.historian.db import AsyncSessionLocal
from backend.app.historian.recorder import HistorianRecorder
from backend.app.historian.service import FlushCounts, HistorianService

logger = logging.getLogger(__name__)

HISTORIAN_RECORDER_KEY = "historian_recorder"
HISTORIAN_SERVICE_KEY = "historian_service"


def start_historian_recorder(app: Any) -> HistorianRecorder | None:
    """Attach a historian recorder to the running plant.

    Returns the recorder, or nothing when the platform runs without a plant
    or with the historian switched off. Nothing is raised when the recorder
    cannot be attached: a platform that cannot record history must still
    simulate.

    The call is idempotent. A recorder that is already attached is detached
    first, so re-attaching — after a plant rebuild, say — replaces it rather
    than colliding with the task name it already holds on the scheduler.
    """
    if not settings.HISTORIAN_ENABLED:
        logger.info("The historian recorder is switched off; the store stays empty.")
        return None

    runtime = getattr(app.state, "simulation_runtime", None)
    plant = getattr(runtime, "active_plant", None)
    engine = getattr(runtime, "engine", None)
    if plant is None or engine is None:
        logger.info("No plant is attached; the historian recorder stays idle.")
        return None

    # Detach a recorder that is already attached, so the scheduler never sees
    # two tasks with the same name.
    stop_historian_recorder(app)

    service = getattr(app.state, HISTORIAN_SERVICE_KEY, None)
    if service is None:
        service = HistorianService()
        setattr(app.state, HISTORIAN_SERVICE_KEY, service)

    recorder = HistorianRecorder(
        plant=plant,
        service=service,
        run_id=engine.simulation_run_id,
        interval_ticks=settings.HISTORIAN_SAMPLE_INTERVAL_TICKS,
    )
    engine.scheduler.register_task(recorder)
    subscribed = recorder.attach_to_plant()
    setattr(app.state, HISTORIAN_RECORDER_KEY, recorder)

    logger.info(
        "The historian recorder is attached: every %d ticks, %d command log(s) subscribed.",
        recorder.interval_ticks,
        subscribed,
    )
    return recorder


def stop_historian_recorder(app: Any) -> None:
    """Detach the recorder and flush everything it recorded."""
    recorder = getattr(app.state, HISTORIAN_RECORDER_KEY, None)
    if recorder is None:
        return

    runtime = getattr(app.state, "simulation_runtime", None)
    engine = getattr(runtime, "engine", None)
    if engine is not None:
        try:
            engine.scheduler.unregister_task(recorder.name)
        except Exception as err:  # noqa: BLE001
            logger.warning("The historian recorder could not be unregistered: %s", err)

    try:
        recorder.detach_from_plant()
    except Exception as err:  # noqa: BLE001
        logger.warning("The historian recorder could not be unsubscribed: %s", err)

    setattr(app.state, HISTORIAN_RECORDER_KEY, None)
    logger.info("The historian recorder recorded %s", recorder.status)


async def flush_historian(app: Any) -> FlushCounts:
    """Flush the historian's buffer and its disk overflow to the database.

    A database that cannot be reached is reported as an error and the data
    stays where it is: the historian's own overflow file already holds
    everything that was not committed, and the next flush tries again.
    """
    service = getattr(app.state, HISTORIAN_SERVICE_KEY, None)
    if service is None:
        return FlushCounts()
    try:
        async with AsyncSessionLocal() as session:
            written: FlushCounts = await service.flush_all_to_db(session)
    except Exception as err:  # noqa: BLE001
        logger.error("The historian could not be flushed to the database: %s", err)
        return FlushCounts()
    if written.total:
        logger.info(
            "The historian flushed %d telemetry, %d command, %d event and %d warranty row(s).",
            written.telemetry,
            written.commands,
            written.events,
            written.warranty,
        )
    return written


async def run_historian_flush_loop(app: Any, interval_s: float) -> None:
    """Flush the historian to the database until the application stops.

    The loop is a plain sleep between flushes: it paces the *database* work,
    not the simulation, and the simulation's determinism does not depend on
    it.
    """
    while True:
        try:
            await asyncio.sleep(interval_s)
            await flush_historian(app)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            logger.error("The historian flush loop failed and will continue: %s", err)
