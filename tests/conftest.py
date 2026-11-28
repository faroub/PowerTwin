"""Pytest fixtures for PowerTwin tests."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.operator_journal import (
    OperatorActionJournal,
    set_operator_journal,
)
from backend.app.core.revocation import reset_development_store
from backend.app.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide TestClient for FastAPI endpoint testing."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_revocation_store() -> Iterator[None]:
    """Start every test with an empty development revocation store.

    The store of a development environment lives in the process, so without
    this the revocations of one test would still be there for the next one.
    """
    reset_development_store()
    yield
    reset_development_store()


@pytest.fixture(autouse=True)
def operator_journal(tmp_path: Path) -> Iterator[OperatorActionJournal]:
    """Point the operator-action journal at a temporary file for the test.

    The journal is always on, so without this every test that logs anything
    would append to the journal under the repository's working directory.
    The trail belongs to the test run, not to the working tree.
    """
    journal = OperatorActionJournal(tmp_path / "operator_actions.jsonl")
    set_operator_journal(app, journal)
    yield journal
    journal.close()


@pytest.fixture
def dev_test_password(monkeypatch: pytest.MonkeyPatch) -> str:
    """Seed the shared development password for the duration of a test.

    Development accounts never use hardcoded passwords: they derive a shared
    password from the `POWERTWIN_DEV_PASSWORD` environment variable, otherwise
    a process-scoped random secret. Tests that exercise development accounts
    can use this fixture to pin a deterministic one.
    """
    password = "powertwin_test_dev_password_override"
    monkeypatch.setenv("POWERTWIN_DEV_PASSWORD", password)
    return password
