"""Tests for the read-only plant topology endpoint.

The endpoint answers the question the removed ``ConfigurationView`` used to
answer with a fabrication: what plant is running, and what does it contain.

The properties these tests state:

* the answer describes the plant that owns the engine,
* a plant that is not attached is reported as not configured, not as an
  empty plant,
* every illustrative parameter is labelled as illustrative,
* a vendor the topology does not declare is reported as absent rather than
  filled in with a placeholder,
* the endpoint is read-only and needs the read-configuration permission.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.simulation.runtime import SimulationRuntime
from backend.app.topology.factory import PlantTopologyFactory

REFERENCE_CONFIG = "configs/reference_10mw_20mwh.yaml"


def _build_plant(source_path: str | None = REFERENCE_CONFIG) -> Any:
    factory = PlantTopologyFactory()
    return factory.build_plant(
        factory.load_config_from_yaml(REFERENCE_CONFIG),
        source_path=source_path,
    )


def _app_with_plant(plant: Any) -> Any:
    runtime = SimulationRuntime()
    runtime.attach_plant(plant)
    state = SimpleNamespace(simulation_runtime=runtime)
    return SimpleNamespace(state=state)


@pytest.fixture
def topology_client() -> Any:
    """A test client whose runtime owns the reference plant."""
    from backend.app.simulation.runtime import get_simulation_runtime

    plant = _build_plant()
    runtime = get_simulation_runtime(app=app)
    runtime.attach_plant(plant)
    with TestClient(app) as client:
        yield client
    runtime.drop()


def _login(client: Any, dev_test_password: str, username: str = "observer") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": dev_test_password},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_the_endpoint_requires_authentication() -> None:
    """An unauthenticated read is refused."""
    with TestClient(app) as client:
        response = client.get("/api/v1/topology")

    assert response.status_code == 401


def test_the_endpoint_reports_the_running_plant(
    topology_client: Any, dev_test_password: str
) -> None:
    """The answer names the plant that owns the engine."""
    headers = _login(topology_client, dev_test_password)

    response = topology_client.get("/api/v1/topology", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["plant_configured"] is True
    assert body["plant_id"] == "REF_PLANT_10MW_20MWH"
    assert body["plant_name"] == "PowerTwin Reference 10 MW / 20 MWh BESS Plant"
    assert body["source_path"] == REFERENCE_CONFIG


def test_the_endpoint_lists_every_item_of_the_equipment_inventory(
    topology_client: Any, dev_test_password: str
) -> None:
    """The inventory holds the plant's containers, PCS units and balance of plant."""
    headers = _login(topology_client, dev_test_password)

    body = topology_client.get("/api/v1/topology", headers=headers).json()

    assert body["counts"]["BATTERY_SYSTEM"] == 4
    assert body["counts"]["PCS"] == 4
    assert body["counts"]["TRANSFORMER"] == 1
    assert body["counts"]["SWITCHGEAR"] == 1
    assert body["counts"]["METER"] == 1
    assert body["counts"]["POI"] == 1
    assert body["counts"]["GRID_MODEL"] == 1

    identifiers = {item["equipment_id"] for item in body["equipment"]}
    assert "CONTAINER_01" in identifiers
    assert "PCS_01" in identifiers
    assert "POI_01" in identifiers


def test_the_endpoint_reports_the_ratings_of_the_plant(
    topology_client: Any, dev_test_password: str
) -> None:
    """The plant's ratings are the ones the topology declares."""
    headers = _login(topology_client, dev_test_password)

    body = topology_client.get("/api/v1/topology", headers=headers).json()

    assert body["rated_power_w"] == 10_000_000.0
    assert body["rated_energy_wh"] == 20_000_000.0


def test_the_endpoint_labels_illustrative_parameters(
    topology_client: Any, dev_test_password: str
) -> None:
    """The reference plant's parameters are illustrative, and it says so."""
    headers = _login(topology_client, dev_test_password)

    body = topology_client.get("/api/v1/topology", headers=headers).json()

    assert body["illustrative"] is True
    assert all(item["illustrative"] is True for item in body["equipment"])


def test_the_endpoint_reports_a_declared_vendor_and_an_absent_one(
    topology_client: Any, dev_test_password: str
) -> None:
    """A vendor the topology declares is named; one it does not is absent."""
    headers = _login(topology_client, dev_test_password)

    body = topology_client.get("/api/v1/topology", headers=headers).json()
    by_id = {item["equipment_id"]: item for item in body["equipment"]}

    assert by_id["CONTAINER_01"]["manufacturer"] == "Reference Cell Co"
    # The topology declares no vendor for the transformer, so the endpoint
    # reports none. The model falls back on a placeholder manufacturer, and a
    # placeholder on a configuration screen reads as a configured vendor.
    assert by_id["XFRM_MAIN_01"]["manufacturer"] is None


def test_the_endpoint_reports_the_capacity_of_a_container(
    topology_client: Any, dev_test_password: str
) -> None:
    """A container's nominal capacity is reported in Wh."""
    headers = _login(topology_client, dev_test_password)

    body = topology_client.get("/api/v1/topology", headers=headers).json()
    by_id = {item["equipment_id"]: item for item in body["equipment"]}

    assert by_id["CONTAINER_01"]["capacity_wh"] == 5_000_000.0
    assert by_id["PCS_01"]["rated_power_w"] == 2_500_000.0


def test_the_endpoint_reports_the_platform_safety_posture(
    topology_client: Any, dev_test_password: str
) -> None:
    """The response carries the safety report the platform enforces."""
    headers = _login(topology_client, dev_test_password)

    body = topology_client.get("/api/v1/topology", headers=headers).json()

    assert body["safety"]["simulation_only"] is True
    assert body["safety"]["hardware_integration_enabled"] is False


def test_the_endpoint_reports_that_no_plant_is_attached(
    client: TestClient, dev_test_password: str
) -> None:
    """A platform with no plant says so instead of answering with an empty plant."""
    from backend.app.simulation.runtime import get_simulation_runtime

    runtime = get_simulation_runtime(app=app)
    runtime.drop()
    headers = _login(client, dev_test_password)

    body = client.get("/api/v1/topology", headers=headers).json()

    assert body["plant_configured"] is False
    assert body["plant_id"] is None
    assert body["equipment"] == []
    assert body["message"] is not None


def test_the_endpoint_changes_nothing(topology_client: Any, dev_test_password: str) -> None:
    """The endpoint is read-only: a read leaves the plant exactly as it was."""
    headers = _login(topology_client, dev_test_password)
    before = topology_client.get("/api/v1/topology", headers=headers).json()

    topology_client.get("/api/v1/topology", headers=headers)

    after = topology_client.get("/api/v1/topology", headers=headers).json()
    assert after == before


def test_the_endpoint_publishes_no_write_route() -> None:
    """There is no way to change a plant's topology through this router."""
    schema = app.openapi()
    topology_path = schema["paths"]["/api/v1/topology"]

    assert set(topology_path) == {"get"}
    assert "post" not in topology_path
    assert "put" not in topology_path
    assert "delete" not in topology_path


def test_a_plant_built_without_a_path_reports_no_source(
    topology_client: Any, dev_test_password: str
) -> None:
    """A plant built in code has no configuration file to name."""
    from backend.app.simulation.runtime import get_simulation_runtime

    runtime = get_simulation_runtime(app=app)
    runtime.attach_plant(_build_plant(source_path=None))
    headers = _login(topology_client, dev_test_password)

    body = topology_client.get("/api/v1/topology", headers=headers).json()

    assert body["source_path"] is None
    assert body["plant_configured"] is True
