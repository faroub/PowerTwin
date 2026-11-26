"""Test application startup and health check endpoints."""

from fastapi.testclient import TestClient

from backend.app.simulation.runtime import get_simulation_runtime
from backend.app.topology.factory import PlantTopologyFactory


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


def test_system_info_reports_the_engine_that_owns_the_plant(
    client: TestClient,
    dev_test_password: str,
) -> None:
    """The info endpoint must report the engine of the running application.

    The status used to be resolved through the module-level fall-back runtime,
    which never holds the application's plant. The endpoint then answered
    NOT_CONNECTED while the Plant Overview reported the running plant: two
    reads of the same plant disagreed, and the HMI — which takes the engine
    state it shows the operator from this endpoint — displayed a plant that
    was running as one that was not connected.
    """
    factory = PlantTopologyFactory()
    plant = factory.build_plant(factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml"))
    runtime = get_simulation_runtime(app=client.app)
    runtime.attach_plant(plant)
    try:
        runtime.start()

        info = client.get("/api/v1/info")
        assert info.status_code == 200
        engine_info = info.json()["engine"]
        assert engine_info["status"] == "RUNNING"
        assert engine_info["is_running"] is True

        # The Plant Overview must tell the same story about the same engine.
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "engineer", "password": dev_test_password},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        overview = client.get(
            "/api/v1/overview",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert overview.status_code == 200
        overview_engine = overview.json()["engine"]
        assert overview_engine["status"] == engine_info["status"]
        assert overview_engine["is_running"] == engine_info["is_running"]
        assert overview_engine["mode"] == engine_info["mode"]
        # The clock advances between the two reads, so the second read can
        # only be at or ahead of the first — never behind it.
        assert overview_engine["current_tick"] >= engine_info["current_tick"]
    finally:
        runtime.drop()
