"""Historian Service with In-Memory Buffering and Zero Silent Data Loss Policy.

DOCUMENTED BUFFERING & DATA LOSS POLICY:
  1. The simulation engine pushes telemetry measurements, command records, and alarms to a
     thread-safe in-memory ring buffer (max capacity: 10,000 entries).
  2. The simulation tick loop is NEVER blocked by database latency or outages.
  3. If the PostgreSQL/TimescaleDB database is temporarily unavailable, items accumulate
     in the in-memory buffer.
  4. If the buffer reaches 100% capacity before database recovers, overflow entries are
     flushed to an emergency append-only JSON file in 'backend/app/historian/overflow/'
     so NO DATA IS SILENTLY DISCARDED.
  5. When database reconnects, buffered items and overflow file entries are written
     sequentially to TimescaleDB.
"""

import json
import logging
import os
import queue
import threading
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.historian.models import (
    AlarmsAndEventsModel,
    CommandRecordModel,
    TelemetryDataModel,
)

logger = logging.getLogger(__name__)

OVERFLOW_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overflow")
MAX_BUFFER_SIZE: int = 10_000


class HistorianService:
    """Thread-safe, non-blocking Historian ingestion service."""

    def __init__(self, max_buffer_size: int = MAX_BUFFER_SIZE) -> None:
        self.max_buffer_size: int = max_buffer_size
        self._telemetry_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_buffer_size)
        self._command_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_buffer_size)
        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_buffer_size)
        self._lock = threading.Lock()

        self._ensure_overflow_dir()

    def _ensure_overflow_dir(self) -> None:
        """Create overflow directory if it doesn't exist."""
        os.makedirs(OVERFLOW_DIR, exist_ok=True)

    def record_telemetry(
        self,
        tag_id: str,
        equipment_id: str,
        val_float: float,
        unit: str,
        timestamp_ns: int,
        source_timestamp_ns: int | None = None,
        quality: str = "GOOD",
        source_type: str = "SIMULATED",
        simulation_run_id: str = "RUN_001",
    ) -> bool:
        """Record telemetry point to non-blocking buffer."""
        src_ts = source_timestamp_ns if source_timestamp_ns is not None else timestamp_ns
        payload = {
            "tag_id": tag_id,
            "equipment_id": equipment_id,
            "val_float": float(val_float),
            "unit": unit,
            "timestamp_ns": timestamp_ns,
            "source_timestamp_ns": src_ts,
            "quality": quality,
            "source_type": source_type,
            "simulation_run_id": simulation_run_id,
        }
        try:
            self._telemetry_queue.put_nowait(payload)
            return True
        except queue.Full:
            self._write_overflow_to_disk("telemetry_overflow.json", payload)
            return False

    def record_command(
        self,
        command_id: str,
        requestor: str,
        target_equipment_id: str,
        requested_value: dict[str, Any],
        accepted_status: str,
        rejection_reason: str,
        timestamp_ns: int,
        resulting_response: dict[str, Any] | None = None,
        simulation_run_id: str = "RUN_001",
    ) -> bool:
        """Record command audit log entry to buffer."""
        payload = {
            "command_id": command_id,
            "requestor": requestor,
            "target_equipment_id": target_equipment_id,
            "requested_value": requested_value,
            "accepted_status": accepted_status,
            "rejection_reason": rejection_reason,
            "timestamp_ns": timestamp_ns,
            "resulting_response": resulting_response if resulting_response is not None else {},
            "simulation_run_id": simulation_run_id,
        }
        try:
            self._command_queue.put_nowait(payload)
            return True
        except queue.Full:
            self._write_overflow_to_disk("command_overflow.json", payload)
            return False

    def record_alarm(
        self,
        event_id: str,
        equipment_id: str,
        severity: str,
        code: str,
        description: str,
        timestamp_ns: int,
        simulation_run_id: str = "RUN_001",
    ) -> bool:
        """Record alarm/event entry to buffer."""
        payload = {
            "event_id": event_id,
            "equipment_id": equipment_id,
            "severity": severity,
            "code": code,
            "description": description,
            "timestamp_ns": timestamp_ns,
            "simulation_run_id": simulation_run_id,
            "acknowledged": False,
            "cleared": False,
        }
        try:
            self._event_queue.put_nowait(payload)
            return True
        except queue.Full:
            self._write_overflow_to_disk("event_overflow.json", payload)
            return False

    def _write_overflow_to_disk(self, filename: str, payload: dict[str, Any]) -> None:
        """Write item to append-only disk overflow file when memory buffer is 100% full."""
        filepath = os.path.join(OVERFLOW_DIR, filename)
        logger.warning("Historian memory buffer full. Writing emergency overflow to %s", filepath)
        with self._lock:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")

    async def flush_buffer_to_db(self, session: AsyncSession) -> tuple[int, int, int]:
        """Flush in-memory buffered telemetry, commands, and alarms to TimescaleDB.

        Rolls back and preserves data on disk overflow if database commit fails.
        """
        raw_telemetry: list[dict[str, Any]] = []
        while not self._telemetry_queue.empty():
            try:
                raw_telemetry.append(self._telemetry_queue.get_nowait())
            except queue.Empty:
                break

        raw_commands: list[dict[str, Any]] = []
        while not self._command_queue.empty():
            try:
                raw_commands.append(self._command_queue.get_nowait())
            except queue.Empty:
                break

        raw_events: list[dict[str, Any]] = []
        while not self._event_queue.empty():
            try:
                raw_events.append(self._event_queue.get_nowait())
            except queue.Empty:
                break

        telemetry_models = [TelemetryDataModel(**item) for item in raw_telemetry]
        command_models = [CommandRecordModel(**item) for item in raw_commands]
        event_models = [AlarmsAndEventsModel(**item) for item in raw_events]

        try:
            if telemetry_models:
                session.add_all(telemetry_models)
            if command_models:
                session.add_all(command_models)
            if event_models:
                session.add_all(event_models)

            await session.commit()
            return (len(telemetry_models), len(command_models), len(event_models))
        except Exception as err:
            logger.error("Database commit failed (%s). Preserving data in overflow.", err)
            await session.rollback()

            for item in raw_telemetry:
                self._write_overflow_to_disk("telemetry_overflow.json", item)
            for item in raw_commands:
                self._write_overflow_to_disk("command_overflow.json", item)
            for item in raw_events:
                self._write_overflow_to_disk("event_overflow.json", item)

            return (0, 0, 0)

    def get_buffer_status(self) -> dict[str, Any]:
        """Return current buffer usage metrics."""
        return {
            "telemetry_buffer_size": self._telemetry_queue.qsize(),
            "command_buffer_size": self._command_queue.qsize(),
            "event_buffer_size": self._event_queue.qsize(),
            "max_buffer_capacity": self.max_buffer_size,
        }
