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
  5. Overflow files are rotated once they exceed OVERFLOW_MAX_BYTES so a long outage
     cannot exhaust the host disk; rotated archives are replayed in chronological order.
  6. When database reconnects, buffered items and overflow file entries are written
     sequentially to TimescaleDB by flush_buffer_to_db() and replay_overflow_to_db().
     The overflow file is only truncated after a successful commit, so a failed
     replay never loses data.
"""

import json
import logging
import os
import queue
import threading
import time
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

# Maximum size of a single overflow file before it is rotated to an archive.
OVERFLOW_MAX_BYTES: int = 64 * 1024 * 1024

#: The reason a record was sent to the overflow file. The in-memory buffer
#: was full — an application capacity problem.
OVERFLOW_REASON_BUFFER_FULL: str = "memory buffer full"

#: The reason a record was sent to the overflow file. The database commit
#: failed — an infrastructure problem, not a capacity one.
OVERFLOW_REASON_COMMIT_FAILED: str = "database commit failed"

# Overflow file stem -> (ORM model, attribute name)
OVERFLOW_STREAMS: dict[str, type[Any]] = {
    "telemetry_overflow": TelemetryDataModel,
    "command_overflow": CommandRecordModel,
    "event_overflow": AlarmsAndEventsModel,
}


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

    def _write_overflow_to_disk(
        self,
        filename: str,
        payload: dict[str, Any],
        reason: str = OVERFLOW_REASON_BUFFER_FULL,
    ) -> None:
        """Write item to the append-only disk overflow file.

        Two different conditions send data here, and an operator has to be
        able to tell them apart: the in-memory buffer is full (an application
        capacity problem) or the database commit failed (an infrastructure
        problem). The reason is carried into the log line for that reason.
        """
        filepath = os.path.join(OVERFLOW_DIR, filename)
        logger.warning(
            "Historian %s. Writing emergency overflow to %s",
            reason,
            filepath,
        )
        line = json.dumps(payload) + "\n"
        with self._lock:
            self._rotate_if_needed(filepath)
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

    def _rotate_if_needed(self, filepath: str) -> None:
        """Rotate an oversized overflow file to a timestamped archive.

        Rotation keeps a single file from exhausting the host disk during a long
        database outage. The archive is replayed in chronological order, so no
        record is lost by rotating.
        """
        try:
            current_size = os.path.getsize(filepath)
        except OSError:
            return

        if current_size < OVERFLOW_MAX_BYTES:
            return

        stem, ext = os.path.splitext(filepath)
        archive = f"{stem}.{int(time.time() * 1e6)}{ext}"
        os.rename(filepath, archive)
        logger.warning("Rotated oversized historian overflow file to %s", archive)

    def _overflow_files(self, stem: str) -> list[str]:
        """Return overflow file paths for a stream, archives first (oldest first)."""
        try:
            names = os.listdir(OVERFLOW_DIR)
        except OSError:
            return []

        ext = ".json"
        prefix = f"{stem}."

        def sort_key(name: str) -> tuple[int, str]:
            # Rotated archives sort before the live file so they replay first.
            if name == f"{stem}{ext}":
                return (1, name)
            return (0, name)

        matching = [
            os.path.join(OVERFLOW_DIR, name)
            for name in names
            if (name == f"{stem}{ext}" or name.startswith(prefix)) and name.endswith(ext)
        ]
        return sorted(matching, key=lambda p: sort_key(os.path.basename(p)))

    def _read_overflow_file(self, filepath: str) -> list[dict[str, Any]]:
        """Read every valid JSON record from an overflow file.

        Corrupt trailing lines (for example a partially written record after a
        crash) are skipped rather than aborting the replay of the rest.
        """
        records: list[dict[str, Any]] = []
        try:
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("Skipping corrupt historian overflow record in %s", filepath)
                        continue
                    if isinstance(parsed, dict):
                        records.append(parsed)
        except OSError as err:
            logger.error("Could not read historian overflow file %s: %s", filepath, err)
        return records

    def get_overflow_status(self) -> dict[str, Any]:
        """Report pending disk-overflow record counts per stream."""
        status: dict[str, Any] = {}
        for stem in OVERFLOW_STREAMS:
            files = self._overflow_files(stem)
            record_count = 0
            total_bytes = 0
            for path in files:
                record_count += len(self._read_overflow_file(path))
                try:
                    total_bytes += os.path.getsize(path)
                except OSError:
                    pass
            status[stem] = {
                "file_count": len(files),
                "pending_records": record_count,
                "total_bytes": total_bytes,
            }
        status["total_pending_records"] = sum(
            int(entry["pending_records"])
            for key, entry in status.items()
            if key != "total_pending_records"
        )
        return status

    async def replay_overflow_to_db(self, session: AsyncSession) -> tuple[int, int, int]:
        """Replay disk-overflow records into the database.

        The overflow file is only truncated after a successful commit. A failed
        commit leaves every record on disk so nothing is silently discarded.
        """
        replayed = {"telemetry_overflow": 0, "command_overflow": 0, "event_overflow": 0}
        pending: dict[str, list[dict[str, Any]]] = {}
        files_by_stream: dict[str, list[str]] = {}

        for stem in OVERFLOW_STREAMS:
            files = self._overflow_files(stem)
            files_by_stream[stem] = files
            records: list[dict[str, Any]] = []
            for path in files:
                records.extend(self._read_overflow_file(path))
            pending[stem] = records
            replayed[stem] = len(records)

        if not any(replayed.values()):
            return (0, 0, 0)

        try:
            for stem, model in OVERFLOW_STREAMS.items():
                records = pending[stem]
                if not records:
                    continue
                session.add_all([model(**record) for record in records])

            await session.commit()
        except Exception as err:
            logger.error("Overflow replay commit failed (%s). Overflow files preserved.", err)
            await session.rollback()
            return (0, 0, 0)

        # Only now that the rows are committed is it safe to clear the files.
        for files in files_by_stream.values():
            if not files:
                continue
            for path in files:
                try:
                    with open(path, "w", encoding="utf-8"):
                        pass
                except OSError as err:
                    logger.error("Could not truncate historian overflow file %s: %s", path, err)

        logger.info(
            "Historian overflow replay committed: %d telemetry, %d commands, %d events.",
            replayed["telemetry_overflow"],
            replayed["command_overflow"],
            replayed["event_overflow"],
        )
        return (
            replayed["telemetry_overflow"],
            replayed["command_overflow"],
            replayed["event_overflow"],
        )

    async def flush_all_to_db(self, session: AsyncSession) -> tuple[int, int, int]:
        """Flush the memory buffer and then replay the disk overflow.

        The memory flush drains the in-memory queues first. If its commit fails
        the drained items are re-persisted to the overflow file by
        flush_buffer_to_db(), and the subsequent disk replay picks them up, so a
        record is never written twice and never lost.
        """
        telemetry, commands, events = await self.flush_buffer_to_db(session)
        replayed = await self.replay_overflow_to_db(session)
        return (
            telemetry + replayed[0],
            commands + replayed[1],
            events + replayed[2],
        )

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
                self._write_overflow_to_disk(
                    "telemetry_overflow.json", item, OVERFLOW_REASON_COMMIT_FAILED
                )
            for item in raw_commands:
                self._write_overflow_to_disk(
                    "command_overflow.json", item, OVERFLOW_REASON_COMMIT_FAILED
                )
            for item in raw_events:
                self._write_overflow_to_disk(
                    "event_overflow.json", item, OVERFLOW_REASON_COMMIT_FAILED
                )

            return (0, 0, 0)

    def get_buffer_status(self) -> dict[str, Any]:
        """Return current buffer usage metrics."""
        return {
            "telemetry_buffer_size": self._telemetry_queue.qsize(),
            "command_buffer_size": self._command_queue.qsize(),
            "event_buffer_size": self._event_queue.qsize(),
            "max_buffer_capacity": self.max_buffer_size,
        }
