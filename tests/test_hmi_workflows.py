"""Automated Test Suite for WP08 Industrial HMI Workflows."""

from fastapi.testclient import TestClient


def test_hmi_overview_endpoint(client: TestClient) -> None:
    """Test /api/v1/overview endpoint returns SCADA plant metrics."""
    response = client.get("/api/v1/overview")
    assert response.status_code == 200
    data = response.json()

    assert "plant_name" in data
    assert data["active_power_mw"] == 4.85
    assert data["average_soc_pct"] == 64.5
    assert data["grid_frequency_hz"] == 50.02
    assert data["poi_voltage_kv"] == 13.81
    assert data["safety"]["application_mode"] == "SIMULATION ONLY"


def test_simulation_control_endpoint_guardrails(client: TestClient) -> None:
    """Test /api/v1/simulation/control endpoint operates strictly on simulation instance."""
    response = client.post(
        "/api/v1/simulation/control",
        json={"action": "PAUSE"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "EXECUTED_ON_SIMULATION_INSTANCE"
    assert "Zero real equipment targeted" in data["message"]
