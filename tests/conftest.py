"""Pytest fixtures for PowerTwin tests."""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide TestClient for FastAPI endpoint testing."""
    return TestClient(app)
