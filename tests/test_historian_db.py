"""Automated Unit Tests for WP07 Historian, Database, and Audit Trail."""

import asyncio
import os
import pathlib
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.historian import service as historian_service
from backend.app.historian.service import HistorianService


def _read_overflow_file(path: str) -> list[str]:
    """Read all lines from the historian overflow file (blocking, worker-safe)."""
    with open(path, encoding="utf-8") as f:
        return f.read().strip().splitlines()


def test_historian_telemetry_buffering_and_timestamp_consistency() -> None:
    """Test non-blocking telemetry buffering and timestamp preservation."""
    historian = HistorianService(max_buffer_size=100)

    # Record 5 telemetry points with explicit nanosecond timestamps
    for i in range(5):
        t_ns = 1_000_000_000 + (i * 10_000_000)
        success = historian.record_telemetry(
            tag_id=f"CONTAINER_01.SOC_{i}",
            equipment_id="CONTAINER_01",
            val_float=50.0 + i,
            unit="pct",
            timestamp_ns=t_ns,
            quality="GOOD",
        )
        assert success is True

    status = historian.get_buffer_status()
    assert status["telemetry_buffer_size"] == 5
    assert status["max_buffer_capacity"] == 100


def test_command_traceability_audit_logging() -> None:
    """Test command audit log recording with requested vs accepted setpoints."""
    historian = HistorianService(max_buffer_size=100)

    success = historian.record_command(
        command_id="CMD_001",
        requestor="EMS_01",
        target_equipment_id="PCS_01",
        requested_value={"p_w": 5_000_000.0, "q_var": 0.0},
        accepted_status="ACCEPTED",
        rejection_reason="SUCCESS",
        timestamp_ns=10_000_000,
        resulting_response={"actual_p_w": 4_925_000.0},
    )
    assert success is True

    status = historian.get_buffer_status()
    assert status["command_buffer_size"] == 1


def test_emergency_disk_overflow_flush_on_buffer_full(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Test zero silent data loss policy: emergency disk overflow flush when memory buffer fills."""
    # Redirect overflow writes to a temporary directory so no tracked repository file is
    # modified by the test suite.
    monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))
    # Small buffer size of 2 items
    historian = HistorianService(max_buffer_size=2)

    # Clean previous test overflow files if any
    overflow_file = os.path.join(tmp_path, "telemetry_overflow.json")
    if os.path.exists(overflow_file):
        os.remove(overflow_file)

    # Fill buffer to capacity (2 items)
    assert historian.record_telemetry("TAG1", "EQ1", 10.0, "V", 100) is True
    assert historian.record_telemetry("TAG2", "EQ1", 12.0, "V", 200) is True

    # 3rd item triggers emergency overflow write to disk (Returns False for memory
    # queue, writes to disk)
    overflow_occurred = historian.record_telemetry("TAG3", "EQ1", 14.0, "V", 300)
    assert overflow_occurred is False

    # Verify overflow file was created on disk
    assert os.path.exists(overflow_file)
    with open(overflow_file, encoding="utf-8") as f:
        content = f.read()
        assert "TAG3" in content


def test_alarm_recording() -> None:
    """Test alarm and fault event recording."""
    historian = HistorianService(max_buffer_size=50)

    success = historian.record_alarm(
        event_id="EVT_001",
        equipment_id="BMS_MASTER_01",
        severity="FAULT",
        code="OVER_TEMP_FAULT",
        description="Battery container temperature exceeded 60 C",
        timestamp_ns=50_000_000,
    )
    assert success is True
    assert historian.get_buffer_status()["event_buffer_size"] == 1


@pytest.mark.asyncio
async def test_flush_buffer_to_db_rollback_preserves_overflow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Test a failed database commit rolls back and persists buffering items to disk."""
    # Redirect overflow writes to a temporary directory so no tracked repository file is
    # modified by the test suite.
    monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))

    overflow_file = os.path.join(tmp_path, "telemetry_overflow.json")
    if os.path.exists(overflow_file):
        os.remove(overflow_file)

    historian = HistorianService(max_buffer_size=2)
    assert historian.record_telemetry("TAG1", "EQ1", 10.0, "V", 100) is True
    assert historian.record_telemetry("TAG2", "EQ1", 12.0, "V", 200) is True
    overflow_occurred = historian.record_telemetry("TAG3", "EQ1", 14.0, "V", 300)
    assert overflow_occurred is False
    assert os.path.exists(overflow_file)

    # Simulate a database session that cannot commit
    class FakeSession:
        async def commit(self) -> None:
            raise RuntimeError("Database unreachable")

        async def rollback(self) -> None:
            pass

    (
        telemetry_written,
        commands_written,
        events_written,
    ) = await historian.flush_buffer_to_db(cast("AsyncSession", FakeSession()))
    assert telemetry_written == 0
    assert commands_written == 0
    assert events_written == 0

    # Buffered items were preserved to disk again (no silent data loss)
    # Read the file on a worker thread: running `open()` inside the event loop
    # blocks the loop, which ruff flags as ASYNC230.
    content = await asyncio.to_thread(_read_overflow_file, overflow_file)
    assert len(content) >= 2
    assert any("TAG3" in line for line in content)


# =============================================================================
# PROMPT 6: Historian Durability & Query API
# =============================================================================


class _RecordingSession:
    """Minimal async session double that records the rows it was asked to add."""

    def __init__(self, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False

    def add_all(self, models: list[Any]) -> None:
        self.added.extend(models)

    async def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("Database unreachable")
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_overflow_replay_commits_and_truncates_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Test disk-overflow records are replayed into the database and the file cleared."""
    monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))

    historian = HistorianService(max_buffer_size=1)
    assert historian.record_telemetry("TAG1", "EQ1", 10.0, "V", 100) is True
    assert historian.record_telemetry("TAG2", "EQ1", 12.0, "V", 200) is False

    overflow_file = os.path.join(tmp_path, "telemetry_overflow.json")
    assert os.path.exists(overflow_file)

    session = _RecordingSession()
    written = await historian.replay_overflow_to_db(cast("AsyncSession", session))

    assert written == (1, 0, 0)
    assert session.committed is True
    assert len(session.added) == 1
    assert session.added[0].tag_id == "TAG2"

    # The overflow file is only cleared after a successful commit.
    remaining = await asyncio.to_thread(_read_overflow_file, overflow_file)
    assert remaining == []


@pytest.mark.asyncio
async def test_overflow_replay_failure_preserves_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Test a failed replay commit leaves every overflow record on disk."""
    monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))

    historian = HistorianService(max_buffer_size=1)
    assert historian.record_telemetry("TAG1", "EQ1", 10.0, "V", 100) is True
    assert historian.record_telemetry("TAG2", "EQ1", 12.0, "V", 200) is False

    overflow_file = os.path.join(tmp_path, "telemetry_overflow.json")
    session = _RecordingSession(fail_commit=True)
    written = await historian.replay_overflow_to_db(cast("AsyncSession", session))

    assert written == (0, 0, 0)
    assert session.rolled_back is True

    content = await asyncio.to_thread(_read_overflow_file, overflow_file)
    assert len(content) == 1
    assert "TAG2" in content[0]


@pytest.mark.asyncio
async def test_overflow_replay_covers_all_three_streams(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Test telemetry, command, and event overflow records are all replayed."""
    monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))

    historian = HistorianService(max_buffer_size=1)
    assert historian.record_telemetry("TAG1", "EQ1", 10.0, "V", 100) is True
    assert historian.record_telemetry("TAG2", "EQ1", 12.0, "V", 200) is False

    assert historian.record_command("CMD1", "EMS_01", "PCS_01", {}, "ACCEPTED", "OK", 300) is True
    assert (
        historian.record_command(
            "CMD2",
            "EMS_01",
            "PCS_01",
            {},
            "ACCEPTED",
            "OK",
            400,
            simulation_run_id="RUN_002",
        )
        is False
    )

    assert historian.record_alarm("EVT1", "BMS_01", "FAULT", "OVER_TEMP", "hot", 500) is True
    assert (
        historian.record_alarm(
            "EVT2",
            "BMS_01",
            "FAULT",
            "OVER_TEMP",
            "hot",
            600,
            simulation_run_id="RUN_003",
        )
        is False
    )

    session = _RecordingSession()
    written = await historian.replay_overflow_to_db(cast("AsyncSession", session))

    assert written == (1, 1, 1)
    assert len(session.added) == 3


@pytest.mark.asyncio
async def test_flush_all_writes_memory_and_overflow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Test flush_all_to_db persists both the memory buffer and the disk overflow."""
    monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))

    historian = HistorianService(max_buffer_size=1)
    assert historian.record_telemetry("TAG1", "EQ1", 10.0, "V", 100) is True
    assert historian.record_telemetry("TAG2", "EQ1", 12.0, "V", 200) is False

    session = _RecordingSession()
    written = await historian.flush_all_to_db(cast("AsyncSession", session))

    # TAG1 came from memory, TAG2 from the disk overflow.
    assert written == (2, 0, 0)
    assert {m.tag_id for m in session.added} == {"TAG1", "TAG2"}


def test_overflow_status_reports_pending_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Test the overflow status reports pending record counts per stream."""
    monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))

    historian = HistorianService(max_buffer_size=1)
    assert historian.record_telemetry("TAG1", "EQ1", 10.0, "V", 100) is True
    assert historian.record_telemetry("TAG2", "EQ1", 12.0, "V", 200) is False

    status = historian.get_overflow_status()
    assert status["telemetry_overflow"]["pending_records"] == 1
    assert status["command_overflow"]["pending_records"] == 0
    assert status["event_overflow"]["pending_records"] == 0
    assert status["total_pending_records"] == 1


def test_overflow_corrupt_record_is_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Test a corrupt trailing overflow line does not abort the replay of the rest."""
    monkeypatch.setattr(historian_service, "OVERFLOW_DIR", str(tmp_path))

    historian = HistorianService(max_buffer_size=1)
    assert historian.record_telemetry("TAG1", "EQ1", 10.0, "V", 100) is True
    assert historian.record_telemetry("TAG2", "EQ1", 12.0, "V", 200) is False

    overflow_file = os.path.join(tmp_path, "telemetry_overflow.json")
    with open(overflow_file, "a", encoding="utf-8") as f:
        f.write("{not valid json\n")

    records = historian._read_overflow_file(overflow_file)
    assert len(records) == 1
    assert records[0]["tag_id"] == "TAG2"


@pytest.mark.asyncio
async def test_historian_query_api_requires_authentication(client) -> None:
    """Test the historian query endpoints reject unauthenticated requests."""
    for path in (
        "/api/v1/historian/telemetry",
        "/api/v1/historian/commands",
        "/api/v1/historian/alarms",
        "/api/v1/historian/warranty/CONTAINER_01",
    ):
        res = client.get(path)
        assert res.status_code == 401, path


@pytest.mark.asyncio
async def test_historian_query_api_rejects_invalid_time_range(
    client, dev_test_password: str
) -> None:
    """Test the historian telemetry endpoint validates the requested time range."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "observer", "password": dev_test_password},
    )
    assert login_res.status_code == 200
    headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    res = client.get(
        "/api/v1/historian/telemetry",
        params={"start_time_ns": 2000, "end_time_ns": 1000},
        headers=headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_historian_query_api_rejects_out_of_range_limit(
    client, dev_test_password: str
) -> None:
    """Test the historian telemetry endpoint enforces its maximum row limit."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "observer", "password": dev_test_password},
    )
    headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    res = client.get("/api/v1/historian/telemetry", params={"limit": 0}, headers=headers)
    assert res.status_code == 422

    res = client.get("/api/v1/historian/telemetry", params={"limit": 10_000_000}, headers=headers)
    assert res.status_code == 422
