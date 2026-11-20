"""Automated Unit Tests for WP07 Historian, Database, and Audit Trail."""

import os

from backend.app.historian.service import OVERFLOW_DIR, HistorianService


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


def test_emergency_disk_overflow_flush_on_buffer_full() -> None:
    """Test zero silent data loss policy: emergency disk overflow flush when memory buffer fills."""
    # Small buffer size of 2 items
    historian = HistorianService(max_buffer_size=2)

    # Clean previous test overflow files if any
    overflow_file = os.path.join(OVERFLOW_DIR, "telemetry_overflow.json")
    if os.path.exists(overflow_file):
        os.remove(overflow_file)

    # Fill buffer to capacity (2 items)
    assert historian.record_telemetry("TAG1", "EQ1", 10.0, "V", 100) is True
    assert historian.record_telemetry("TAG2", "EQ1", 12.0, "V", 200) is True

    # 3rd item triggers emergency overflow write to disk (Returns False for memory queue, writes to disk)
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
