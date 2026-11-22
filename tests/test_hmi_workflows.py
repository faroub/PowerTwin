"""Automated Test Suite for Industrial HMI Workflows and Simulation Control API."""

from fastapi.testclient import TestClient

from backend.app.api.v1.simulation_ctrl import set_active_simulation_engine
from backend.app.topology.factory import PlantTopologyFactory


def test_unauthenticated_requests_rejected(client: TestClient) -> None:
    """Test unauthenticated requests to protected endpoints return 401 Unauthorized."""
    res_overview = client.get("/api/v1/overview")
    assert res_overview.status_code == 401

    res_control = client.post("/api/v1/simulation/control", json={"action": "PAUSE"})
    assert res_control.status_code == 401


def test_observer_role_can_read_telemetry_but_cannot_modify_simulation(
    client: TestClient,
) -> None:
    """Test OBSERVER role can read overview SCADA metrics but is denied
    simulation control actions."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(
        factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml")
    )
    plant.simulation_engine.shared_state["plant_instance"] = plant
    set_active_simulation_engine(plant.simulation_engine)

    login_res = client.post(
        "/api/v1/auth/login", json={"username": "observer", "password": "observer123"}
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    overview_res = client.get("/api/v1/overview", headers=headers)
    assert overview_res.status_code == 200
    assert overview_res.json()["simulation_state"] == "STOPPED"
    assert overview_res.json()["total_energy_mwh"] == 20.0

    control_res = client.post(
        "/api/v1/simulation/control", json={"action": "PAUSE"}, headers=headers
    )
    assert control_res.status_code == 403
    assert "Access denied" in control_res.json()["detail"]

    set_active_simulation_engine(None)


def test_simulation_control_returns_503_when_no_engine_connected(
    client: TestClient,
) -> None:
    """Test simulation control API returns 503 NOT_CONNECTED when no active engine is attached."""
    set_active_simulation_engine(None)

    login_res = client.post(
        "/api/v1/auth/login", json={"username": "engineer", "password": "engineer123"}
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post(
        "/api/v1/simulation/control", json={"action": "PAUSE"}, headers=headers
    )
    assert res.status_code == 503
    data = res.json()["detail"]
    assert data["status"] == "NOT_CONNECTED"


def test_simulation_control_executes_action_on_active_engine(
    client: TestClient,
) -> None:
    """Test simulation control API executes action on active
    SimulationRunManager engine instance."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(
        factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml")
    )
    plant.simulation_engine.shared_state["plant_instance"] = plant
    set_active_simulation_engine(plant.simulation_engine)

    login_res = client.post(
        "/api/v1/auth/login", json={"username": "engineer", "password": "engineer123"}
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Execute START action
    res_start = client.post(
        "/api/v1/simulation/control", json={"action": "START"}, headers=headers
    )
    assert res_start.status_code == 200
    data_start = res_start.json()
    assert data_start["status"] == "SUCCESS"
    assert data_start["engine_state"] == "RUNNING"

    # Execute PAUSE action
    res_pause = client.post(
        "/api/v1/simulation/control", json={"action": "PAUSE"}, headers=headers
    )
    assert res_pause.status_code == 200
    data_pause = res_pause.json()
    assert data_pause["status"] == "SUCCESS"
    assert data_pause["engine_state"] == "PAUSED"

    set_active_simulation_engine(None)


def test_simulation_control_rejects_unknown_action(client: TestClient) -> None:
    """Test simulation control API rejects unknown/invalid action string with 422."""
    login_res = client.post(
        "/api/v1/auth/login", json={"username": "engineer", "password": "engineer123"}
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post(
        "/api/v1/simulation/control",
        json={"action": "UNKNOWN_ACTION_STRING"},
        headers=headers,
    )
    assert res.status_code == 422
