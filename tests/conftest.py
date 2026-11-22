"""Pytest fixtures for PowerTwin tests."""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide TestClient for FastAPI endpoint testing."""
    return TestClient(app)


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
