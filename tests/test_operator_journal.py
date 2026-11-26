"""Tests for the dedicated, append-only operator-action journal (F-09).

The journal is the platform's durable, tamper-evident audit trail. These
tests cover the properties a warranty or dispute analysis relies on:

* an entry is written and read back unchanged,
* the chain of hashes links every entry to its predecessor,
* an entry that is altered, removed or reordered is detected,
* the chain continues across a restart instead of starting a second chain,
* a write that fails is reported rather than swallowed,
* every category that ``AGENTS.md`` §2.10 requires to be recorded — commands,
  setpoint changes, configuration changes, faults and operator actions — is
  actually recorded.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.controllers.command_log import CommandStatus, ControlCommandLog
from backend.app.core.audit import AuditLog
from backend.app.core.config_audit import ConfigChangeAuditLog
from backend.app.core.operator_journal import (
    GENESIS_HASH,
    OperatorActionJournal,
    OperatorJournalError,
    get_operator_journal,
    set_operator_journal,
)
from backend.app.simulation.fault_injection import (
    FaultEventSpec,
    FaultInjectionEngine,
    FaultType,
)
from backend.app.simulation.runtime import get_simulation_runtime
from backend.app.topology.factory import PlantTopologyFactory

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _journal(tmp_path: Path, name: str = "journal.jsonl") -> OperatorActionJournal:
    """Build a journal that writes to a temporary file."""
    return OperatorActionJournal(tmp_path / name)


def _rewrite(path: Path, lines: list[str]) -> None:
    """Replace the content of the journal file with the given lines."""
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Writing and reading
# --------------------------------------------------------------------------- #


class TestTheJournalRecords:
    """The journal accepts an entry and reads it back unchanged."""

    def test_an_entry_is_read_back_unchanged(self, tmp_path: Path) -> None:
        """A recorded entry keeps every field it was written with."""
        journal = _journal(tmp_path)

        entry = journal.record(
            action="SIMULATION_START",
            actor="operator",
            target="PLANT_01",
            source="OPERATOR",
            outcome="SUCCESS",
            details={"engine_state": "RUNNING"},
        )

        assert entry.sequence == 1
        assert entry.action == "SIMULATION_START"
        assert entry.actor == "operator"
        assert entry.target == "PLANT_01"
        assert entry.outcome == "SUCCESS"
        assert entry.details == {"engine_state": "RUNNING"}

        read_back = journal.read()
        assert len(read_back) == 1
        assert read_back[0] == entry
        journal.close()

    def test_the_entries_are_numbered_from_one(self, tmp_path: Path) -> None:
        """Every entry carries its position in the chain."""
        journal = _journal(tmp_path)

        for _ in range(3):
            journal.record(action="SIMULATION_STEP", actor="operator", target="PLANT_01")

        assert [entry.sequence for entry in journal.read()] == [1, 2, 3]
        assert journal.sequence == 3
        journal.close()

    def test_the_first_entry_follows_the_genesis_hash(self, tmp_path: Path) -> None:
        """The chain starts from a fixed, well-known value."""
        journal = _journal(tmp_path)

        entry = journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")

        assert entry.previous_hash == GENESIS_HASH
        assert len(entry.entry_hash) == 64
        journal.close()

    def test_every_entry_follows_its_predecessor(self, tmp_path: Path) -> None:
        """Each entry names the hash of the entry before it."""
        journal = _journal(tmp_path)

        first = journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")
        second = journal.record(action="SIMULATION_PAUSE", actor="operator", target="PLANT_01")

        assert second.previous_hash == first.entry_hash
        assert second.entry_hash != first.entry_hash
        journal.close()

    def test_the_file_is_created_on_the_first_write_only(self, tmp_path: Path) -> None:
        """Building a journal never touches the filesystem."""
        path = tmp_path / "journal.jsonl"
        journal = OperatorActionJournal(path)

        assert not path.exists()
        journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")
        assert path.exists()
        journal.close()

    def test_a_value_that_is_not_json_native_is_stored_as_text(self, tmp_path: Path) -> None:
        """An exotic detail value does not make the write fail."""
        journal = _journal(tmp_path)

        class Exotic:
            def __repr__(self) -> str:
                return "EXOTIC"

        entry = journal.record(
            action="SIMULATION_START",
            actor="operator",
            target="PLANT_01",
            details={"value": Exotic()},
        )

        assert isinstance(entry.details["value"], str)
        assert journal.read()[0].details["value"] == entry.details["value"]
        journal.close()

    def test_a_secret_in_the_details_is_redacted(self, tmp_path: Path) -> None:
        """The journal never becomes a second store of credentials."""
        journal = _journal(tmp_path)

        entry = journal.record(
            action="CONFIGURATION_CHANGE",
            actor="operator",
            target="PCS_01.password",
            details={"password": "SuperSecret123"},
        )

        assert "SuperSecret123" not in json.dumps(entry.details)
        assert entry.details["password"] == "***REDACTED***"
        journal.close()

    def test_a_credential_in_a_connection_url_is_redacted(self, tmp_path: Path) -> None:
        """A credential embedded in a URL never reaches the trail in clear text."""
        journal = _journal(tmp_path)

        entry = journal.record(
            action="CONFIGURATION_CHANGE",
            actor="operator",
            target="PCS_01.endpoint",
            details={"endpoint": "postgresql://user:hunter2@db:5432/powertwin"},
        )

        assert "hunter2" not in json.dumps(entry.details)
        journal.close()


# --------------------------------------------------------------------------- #
# Tamper evidence
# --------------------------------------------------------------------------- #


class TestTheChainDetectsTampering:
    """An edited, removed or reordered entry breaks the chain."""

    def test_an_intact_journal_verifies(self, tmp_path: Path) -> None:
        """A journal that was not touched verifies as intact."""
        journal = _journal(tmp_path)
        for index in range(4):
            journal.record(action=f"SIMULATION_STEP_{index}", actor="operator", target="PLANT_01")

        verification = journal.verify()

        assert verification.ok is True
        assert verification.entries == 4
        assert verification.first_broken_sequence is None
        journal.close()

    def test_an_altered_entry_is_detected(self, tmp_path: Path) -> None:
        """Changing the content of an entry breaks the chain at that entry."""
        journal = _journal(tmp_path)
        journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")
        journal.record(action="SIMULATION_PAUSE", actor="operator", target="PLANT_01")
        journal.close()

        path = tmp_path / "journal.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        payload = json.loads(lines[0])
        payload["actor"] = "somebody_else"
        lines[0] = json.dumps(payload)
        _rewrite(path, lines)

        verification = journal.verify()

        assert verification.ok is False
        assert verification.first_broken_sequence == 1
        assert "altered" in (verification.reason or "")
        journal.close()

    def test_a_removed_entry_is_detected(self, tmp_path: Path) -> None:
        """Deleting an entry breaks the chain at the entry that followed it."""
        journal = _journal(tmp_path)
        journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")
        journal.record(action="SIMULATION_PAUSE", actor="operator", target="PLANT_01")
        journal.record(action="SIMULATION_RESUME", actor="operator", target="PLANT_01")
        journal.close()

        path = tmp_path / "journal.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        _rewrite(path, [lines[0], lines[2]])

        verification = journal.verify()

        assert verification.ok is False
        assert verification.first_broken_sequence == 2
        journal.close()

    def test_reordered_entries_are_detected(self, tmp_path: Path) -> None:
        """Swapping two entries breaks the chain."""
        journal = _journal(tmp_path)
        journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")
        journal.record(action="SIMULATION_PAUSE", actor="operator", target="PLANT_01")
        journal.close()

        path = tmp_path / "journal.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        _rewrite(path, [lines[1], lines[0]])

        verification = journal.verify()

        assert verification.ok is False
        assert verification.first_broken_sequence == 1
        journal.close()

    def test_a_truncated_entry_is_detected(self, tmp_path: Path) -> None:
        """A half-written line is reported as a break, not ignored."""
        journal = _journal(tmp_path)
        journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")
        journal.close()

        path = tmp_path / "journal.jsonl"
        path.write_text('{"sequence": 1, "action": "SIM', encoding="utf-8")

        verification = journal.verify()

        assert verification.ok is False
        assert verification.first_broken_sequence == 1
        assert "not valid JSON" in (verification.reason or "")
        journal.close()

    def test_the_read_view_skips_a_malformed_line(self, tmp_path: Path) -> None:
        """The convenience read tolerates a damaged line; verify does not."""
        journal = _journal(tmp_path)
        journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")
        journal.close()

        path = tmp_path / "journal.jsonl"
        path.write_text('{"broken": true}\n', encoding="utf-8")

        assert journal.read() == []
        assert journal.verify().ok is False
        journal.close()


# --------------------------------------------------------------------------- #
# Restart behaviour
# --------------------------------------------------------------------------- #


class TestTheChainSurvivesARestart:
    """A journal that is reopened continues the chain it already had."""

    def test_a_reopened_journal_continues_the_chain(self, tmp_path: Path) -> None:
        """The second run does not start a second, parallel chain."""
        first = _journal(tmp_path)
        first.record(action="SIMULATION_START", actor="operator", target="PLANT_01")
        first.close()

        second = _journal(tmp_path)
        entry = second.record(action="SIMULATION_PAUSE", actor="operator", target="PLANT_01")

        assert entry.sequence == 2
        assert second.verify().ok is True
        assert second.verify().entries == 2
        second.close()

    def test_the_journal_is_never_rewritten(self, tmp_path: Path) -> None:
        """Reopening the journal appends; it does not truncate what is there."""
        path = tmp_path / "journal.jsonl"
        first = _journal(tmp_path)
        first.record(action="SIMULATION_START", actor="operator", target="PLANT_01")
        first.close()
        before = path.read_text(encoding="utf-8")

        second = _journal(tmp_path)
        second.record(action="SIMULATION_PAUSE", actor="operator", target="PLANT_01")
        second.close()
        after = path.read_text(encoding="utf-8")

        assert after.startswith(before)
        assert len(after.splitlines()) == 2


# --------------------------------------------------------------------------- #
# Failure handling
# --------------------------------------------------------------------------- #


class TestAFailedWriteIsReported:
    """A journal that cannot be written says so; it never fails silently."""

    def test_a_write_to_an_unusable_path_raises(self, tmp_path: Path) -> None:
        """The failure is surfaced as a typed error."""
        unusable = tmp_path / "journal.jsonl"
        unusable.mkdir()
        journal = OperatorActionJournal(unusable)

        with pytest.raises(OperatorJournalError):
            journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")

        assert journal.degraded is True
        assert journal.last_error is not None

    def test_an_invalid_path_is_reported_as_a_journal_error(self, tmp_path: Path) -> None:
        """A path the platform cannot even name is still a typed journal error.

        The contract is that a caller only ever has to handle
        ``OperatorJournalError``; a raw ``ValueError`` from the path handling
        would break that contract.
        """
        journal = OperatorActionJournal(tmp_path / "invalid\0name" / "journal.jsonl")

        with pytest.raises(OperatorJournalError):
            journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")

        assert journal.degraded is True

    def test_a_write_failure_does_not_advance_the_chain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed entry is not counted as written."""

        def failing_fsync(_fileno: int) -> None:
            raise OSError("the storage device refused the write")

        journal = _journal(tmp_path)
        journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")
        assert journal.sequence == 1

        monkeypatch.setattr(os, "fsync", failing_fsync)
        with pytest.raises(OperatorJournalError):
            journal.record(action="SIMULATION_PAUSE", actor="operator", target="PLANT_01")

        assert journal.sequence == 1
        assert journal.degraded is True
        journal.close()

    def test_a_failed_write_is_logged_as_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The failure is reported in the structured log, not swallowed."""

        def failing_fsync(_fileno: int) -> None:
            raise OSError("the storage device refused the write")

        journal = _journal(tmp_path)
        journal.record(action="SIMULATION_START", actor="operator", target="PLANT_01")

        monkeypatch.setattr(os, "fsync", failing_fsync)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(OperatorJournalError):
                journal.record(action="SIMULATION_PAUSE", actor="operator", target="PLANT_01")

        assert any(record.levelno == logging.ERROR for record in caplog.records)
        journal.close()


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


class TestTheJournalIsResolvedOnce:
    """Every caller in the process writes to the same trail."""

    def test_every_caller_resolves_the_same_journal(self, tmp_path: Path) -> None:
        """A caller with and a caller without an application handle agree."""
        journal = _journal(tmp_path)
        set_operator_journal(_FakeApp(), journal)

        assert get_operator_journal() is journal
        assert get_operator_journal(app=_FakeApp()) is journal
        assert get_operator_journal(request=_FakeRequest(_FakeApp())) is journal

    def test_an_application_without_a_journal_adopts_the_process_one(self, tmp_path: Path) -> None:
        """An application that asks for a journal gets the process journal."""
        journal = _journal(tmp_path)
        set_operator_journal(_FakeApp(), journal)
        other = _FakeApp()

        assert get_operator_journal(app=other) is journal
        assert other.state.operator_journal is journal


class _FakeState:
    """A minimal stand-in for ``app.state``."""

    def __init__(self) -> None:
        self.operator_journal: Any = None


class _FakeApp:
    """A minimal stand-in for a FastAPI application."""

    def __init__(self) -> None:
        self.state = _FakeState()


class _FakeRequest:
    """A minimal stand-in for a FastAPI request."""

    def __init__(self, app: _FakeApp) -> None:
        self.app = app


# --------------------------------------------------------------------------- #
# The recorded categories
# --------------------------------------------------------------------------- #


class TestEveryRequiredCategoryIsRecorded:
    """``AGENTS.md`` §2.10 lists what has to be in an auditable log."""

    def test_a_command_reaches_the_journal(self, tmp_path: Path) -> None:
        """A control command is written to the trail."""
        journal = _journal(tmp_path)
        set_operator_journal(_FakeApp(), journal)

        log = ControlCommandLog()
        log.log_entry(
            timestamp_ns=1_000,
            source_layer="EMS",
            target_component="PCS_01",
            action_name="DISPATCH_SETPOINT",
            requested_value={"p_w": 1_000_000},
            accepted_value={"p_w": 900_000},
            status=CommandStatus.DERATED,
            reason="LIMITED_BY_SOC",
        )

        entries = journal.read()
        assert len(entries) == 1
        assert entries[0].action == "DISPATCH_SETPOINT"
        assert entries[0].actor == "EMS"
        assert entries[0].target == "PCS_01"
        assert entries[0].outcome == "DERATED"
        assert entries[0].details["reason"] == "LIMITED_BY_SOC"
        journal.close()

    def test_a_configuration_change_reaches_the_journal(self, tmp_path: Path) -> None:
        """A configuration change is written to the trail."""
        journal = _journal(tmp_path)
        set_operator_journal(_FakeApp(), journal)

        log = ConfigChangeAuditLog()
        log.log_change(
            timestamp_ns=2_000,
            user_id="operator",
            component_name="PCS_01",
            parameter_name="rated_power_w",
            old_value="1000000",
            new_value="1200000",
        )

        entries = journal.read()
        assert len(entries) == 1
        assert entries[0].action == "CONFIGURATION_CHANGE"
        assert entries[0].target == "PCS_01.rated_power_w"
        assert entries[0].details["new_value"] == "1200000"
        journal.close()

    def test_an_authentication_event_reaches_the_journal(self, tmp_path: Path) -> None:
        """An authentication event is written to the trail."""
        journal = _journal(tmp_path)
        set_operator_journal(_FakeApp(), journal)

        log = AuditLog(log_dir=str(tmp_path / "audit"))
        log.record("LOGIN_SUCCESS", actor="operator", target="operator")
        log.record_failure("LOGIN_FAILED", actor="operator", target="operator")

        entries = journal.read()
        assert len(entries) == 2
        assert entries[0].outcome == "SUCCESS"
        assert entries[1].outcome == "FAILURE"
        journal.close()

    def test_a_fault_reaches_the_journal(self, tmp_path: Path) -> None:
        """An injected and a cleared fault are written to the trail."""
        journal = _journal(tmp_path)
        set_operator_journal(_FakeApp(), journal)

        factory = PlantTopologyFactory()
        plant = factory.build_plant(
            factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml")
        )
        engine = FaultInjectionEngine()
        fault = FaultEventSpec(
            fault_id="FAULT_01",
            fault_type=FaultType.BATTERY_CONTAINER_UNAVAILABLE,
            target_equipment_id="CONTAINER_01",
            trigger_timestamp_ns=0,
        )
        engine.schedule_fault(fault)
        engine.process_tick(1_000, plant)
        engine.clear_fault("FAULT_01", 2_000, plant)

        entries = journal.read()
        assert [entry.action for entry in entries] == ["FAULT_INJECTED", "FAULT_CLEARED"]
        assert entries[0].target == "CONTAINER_01"
        assert entries[0].details["fault_id"] == "FAULT_01"
        assert journal.verify().ok is True
        journal.close()

    def test_an_operator_action_reaches_the_journal(
        self, client: TestClient, dev_test_password: str, tmp_path: Path
    ) -> None:
        """The simulation control endpoint records what the operator did."""
        journal = _journal(tmp_path)
        set_operator_journal(client.app, journal)

        factory = PlantTopologyFactory()
        plant = factory.build_plant(
            factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml")
        )
        get_simulation_runtime(app=client.app).attach_plant(plant)

        login = client.post(
            "/api/v1/auth/login",
            json={"username": "engineer", "password": dev_test_password},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = client.post(
            "/api/v1/simulation/control", json={"action": "PAUSE"}, headers=headers
        )
        assert response.status_code == 200

        actions = [entry.action for entry in journal.read()]
        assert "SIMULATION_PAUSE" in actions

        get_simulation_runtime(app=client.app).drop()
        journal.close()

    def test_a_rejected_operator_action_reaches_the_journal(
        self, client: TestClient, dev_test_password: str, tmp_path: Path
    ) -> None:
        """A refused action is recorded too: a trail that only shows success hides attempts."""
        journal = _journal(tmp_path)
        set_operator_journal(client.app, journal)
        get_simulation_runtime(app=client.app).drop()

        login = client.post(
            "/api/v1/auth/login",
            json={"username": "engineer", "password": dev_test_password},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = client.post(
            "/api/v1/simulation/control", json={"action": "PAUSE"}, headers=headers
        )
        assert response.status_code == 503

        rejected = [entry for entry in journal.read() if entry.action == "SIMULATION_PAUSE"]
        assert len(rejected) == 1
        assert rejected[0].outcome == "REJECTED"
        assert rejected[0].details["reason"] == "NOT_CONNECTED"
        journal.close()

    def test_an_out_of_range_step_count_is_recorded_as_rejected(
        self, client: TestClient, dev_test_password: str, tmp_path: Path
    ) -> None:
        """A refused STEP is recorded with the reason it was refused."""
        journal = _journal(tmp_path)
        set_operator_journal(client.app, journal)

        factory = PlantTopologyFactory()
        plant = factory.build_plant(
            factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml")
        )
        get_simulation_runtime(app=client.app).attach_plant(plant)

        login = client.post(
            "/api/v1/auth/login",
            json={"username": "engineer", "password": dev_test_password},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = client.post(
            "/api/v1/simulation/control",
            json={"action": "STEP", "steps": 0},
            headers=headers,
        )
        assert response.status_code == 400

        rejected = [entry for entry in journal.read() if entry.action == "SIMULATION_STEP"]
        assert len(rejected) == 1
        assert rejected[0].outcome == "REJECTED"
        assert rejected[0].details["reason"] == "INVALID_STEP_COUNT"

        get_simulation_runtime(app=client.app).drop()
        journal.close()

    def test_an_invalid_setpoint_is_recorded_as_rejected(
        self, client: TestClient, dev_test_password: str, tmp_path: Path
    ) -> None:
        """An out-of-range command is recorded with the reason it was refused."""
        journal = _journal(tmp_path)
        set_operator_journal(client.app, journal)

        factory = PlantTopologyFactory()
        plant = factory.build_plant(
            factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml")
        )
        get_simulation_runtime(app=client.app).attach_plant(plant)

        login = client.post(
            "/api/v1/auth/login",
            json={"username": "engineer", "password": dev_test_password},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = client.post(
            "/api/v1/simulation/control",
            json={"action": "SET_SPEED", "speed_factor": -1.0},
            headers=headers,
        )
        assert response.status_code == 400

        rejected = [entry for entry in journal.read() if entry.action == "SIMULATION_SET_SPEED"]
        assert len(rejected) == 1
        assert rejected[0].outcome == "REJECTED"
        assert rejected[0].details["reason"] == "INVALID_SPEED_FACTOR"

        get_simulation_runtime(app=client.app).drop()
        journal.close()
