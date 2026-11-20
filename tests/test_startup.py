"""Test application startup and health check endpoints."""

from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    """Test /health endpoint returns HTTP 200 and healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "powertwin-backend"
    assert "safety" in data
    assert data["safety"]["application_mode"] == "SIMULATION ONLY"


def test_liveness_endpoint(client: TestClient) -> None:
    """Test /health/liveness endpoint."""
    response = client.get("/health/liveness")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_endpoint(client: TestClient) -> None:
    """Test /health/readiness endpoint."""
    response = client.get("/health/readiness")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["safety"]["simulation_only"] is True


def test_system_info_endpoint(client: TestClient) -> None:
    """Test /api/v1/info endpoint."""
    response = client.get("/api/v1/info")
    assert response.status_code == 200
    data = response.json()
    assert data["project_name"] == "PowerTwin BESS Simulator"
    assert data["version"] == "0.1.0"
    assert data["safety"]["simulation_only"] is True
    assert data["engine"]["mode"] == "SIMULATION_ONLY"
