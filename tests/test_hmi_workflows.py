"""Automated Test Suite for Industrial HMI Workflows and RBAC Enforcement."""

from fastapi.testclient import TestClient


def test_unauthenticated_requests_rejected(client: TestClient) -> None:
    """Test unauthenticated requests to protected endpoints return 401 Unauthorized."""
    res_overview = client.get("/api/v1/overview")
    assert res_overview.status_code == 401

    res_control = client.post("/api/v1/simulation/control", json={"action": "PAUSE"})
    assert res_control.status_code == 401


def test_observer_role_can_read_telemetry_but_cannot_modify_simulation(
    client: TestClient,
) -> None:
    """Test OBSERVER role can read overview SCADA metrics but is denied simulation control actions."""
    # 1. Login as observer
    login_res = client.post(
        "/api/v1/auth/login", json={"username": "observer", "password": "observer123"}
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Read overview telemetry -> 200 OK
    overview_res = client.get("/api/v1/overview", headers=headers)
    assert overview_res.status_code == 200
    assert overview_res.json()["active_power_mw"] == 4.85

    # 3. Attempt simulation control action -> 403 Forbidden
    control_res = client.post(
        "/api/v1/simulation/control", json={"action": "PAUSE"}, headers=headers
    )
    assert control_res.status_code == 403
    assert "Access denied" in control_res.json()["detail"]


def test_engineer_role_can_modify_simulation(client: TestClient) -> None:
    """Test ENGINEER role can execute simulation control actions."""
    # 1. Login as engineer
    login_res = client.post(
        "/api/v1/auth/login", json={"username": "engineer", "password": "engineer123"}
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Execute simulation control action -> 200 OK
    control_res = client.post(
        "/api/v1/simulation/control", json={"action": "PAUSE"}, headers=headers
    )
    assert control_res.status_code == 200
    assert control_res.json()["status"] == "EXECUTED_ON_SIMULATION_INSTANCE"
