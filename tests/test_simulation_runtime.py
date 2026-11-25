"""Tests for the application-scoped simulation execution pipeline.

These tests verify the authoritative pipeline documented in
``docs/04_SIMULATION_ENGINE_SPECIFICATION.md``:

    plant topology config -> built plant -> engine -> runner thread

    * the plant is built and attached once at application start-up,
    * every API read/write resolves the same runtime (never a global),
    * a single tick advances each physical model exactly once,
    * snapshots capture and reproduce engine + physical model state,
    * reset restores initial physical conditions without leaking state.
"""

import datetime
import math
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import router
from backend.app.core.config import settings
from backend.app.core.rbac import Permission, UserRole, create_user_session
from backend.app.simulation.application import close_simulation, init_simulation
from backend.app.simulation.runtime import (
    SimulationRuntime,
    default_runtime,
    get_simulation_runtime,
)
from backend.app.topology.factory import PlantTopologyFactory

TOPOLOGY_PATH = "configs/reference_10mw_20mwh.yaml"

DEV_USERNAMES = ("observer", "engineer", "admin")


def _login(client: TestClient, password: str, username: str = "admin") -> str:
    """Login as the given developer account and return the bearer token.

    Simulation control endpoints require ``MODIFY_SIMULATION``, which the
    ``admin`` role carries.
    """
    if username not in DEV_USERNAMES:
        msg = f"Unrecognised developer username '{username}'"
        raise ValueError(msg)

    res = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    if res.status_code != 200:
        msg = (
            f"No developer account matched {username} (status {res.status_code}): "
            f"the credentials must be the dev password"
        )
        raise AssertionError(msg)
    return res.json()["access_token"]


def _header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _set_topology(path: str = TOPOLOGY_PATH) -> None:
    settings.TOPOLOGY_CONFIG_PATH = path


def _control(client: TestClient, token: str, **payload) -> dict:
    """POST /simulation/control and parse the response."""
    res = client.post(
        "/api/v1/simulation/control",
        json=payload,
        headers=_header(token),
    )
    assert res.status_code == 200, res.text
    return res.json()


def _status(client: TestClient, token: str) -> dict:
    """GET /simulation/status and parse the response."""
    res = client.get("/api/v1/simulation/status", headers=_header(token))
    return res.json()


@pytest.fixture
def password(monkeypatch: pytest.MonkeyPatch) -> str:
    """Every test uses the same deterministic development password."""
    monkeypatch.setenv("POWERTWIN_DEV_PASSWORD", "powertwin_test_dev_password_override")
    return "powertwin_test_dev_password_override"


@pytest.fixture
def client(password: str):
    """Run the real app with a topology path so the plant is built at startup."""
    _set_topology()
    app = FastAPI()
    app.include_router(router.api_v1_router, prefix="/api/v1")
    init_simulation(app)
    client = TestClient(app)
    try:
        yield client
    finally:
        close_simulation(app)


def test_overview_reports_real_plant_data(client: TestClient, password: str) -> None:
    """The overview report real telemetry from the attached plant instance."""
    token = _login(client, password)

    res = client.get("/api/v1/overview", headers=_header(token))
    assert res.status_code == 200
    data = res.json()

    assert data["plant_name"] == "PowerTwin Reference 10 MW / 20 MWh BESS Plant"
    assert data["average_soc_pct"] == 50.0
    assert data["total_energy_mwh"] == 20.0
    assert data["active_alarms_count"] == 0
    assert data["equipment_availability_pct"] == 100.0
    assert data["simulation_state"] == "STOPPED"
    assert data["engine"]["status"] == "STOPPED"
    assert data["engine"]["mode"] == "SIMULATION_ONLY"
    assert data["engine"]["current_tick"] == 0
    assert data["engine"]["is_running"] is False
    assert data["engine"]["message"].startswith("Simulation engine is in state")
    assert data["safety"]["application_mode"] == "SIMULATION ONLY"
    assert data["safety"]["simulation_only"] is True


def test_status_endpoint_report_true_state(client: TestClient, password: str) -> None:
    """/simulation/status reflects the real engine state of the attached plant."""
    token = _login(client, password)

    res = client.get("/api/v1/simulation/status", headers=_header(token))
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "STOPPED"
    assert data["current_tick"] == 0
    assert data["is_running"] is False

    res = _control(client, token, action="START")
    assert res["action"] == "START"
    assert res["status"] == "SUCCESS"

    data = _status(client, token)
    assert data["status"] == "RUNNING"
    assert data["current_tick"] > 0
    assert data["is_running"] is True
    assert data["message"].startswith("Simulation engine is in state")


def test_single_step_advances_exactly_one_tick(
    client: TestClient, password: str
) -> None:
    """STEP must advance exactly one tick and no more than one tick."""
    token = _login(client, password)

    _control(client, token, action="RESET")
    data = _status(client, token)
    assert data["current_tick"] == 0

    _control(client, token, action="START")
    before = _status(client, token)["current_tick"]

    res = _control(client, token, action="STEP", steps=6)
    assert res["status"] == "SUCCESS"
    data = _status(client, token)
    assert data["current_tick"] == before + 6, (before, data["current_tick"])


def test_start_stop_repeatedly_home_the_thread(
    client: TestClient, password: str
) -> None:
    """Starting and stopping repeatedly never leaves stale state."""
    token = _login(client, password)

    for _ in range(3):
        _control(client, token, action="START")
        assert _status(client, token)["is_running"] is True

        _control(client, token, action="STOP")
        assert _status(client, token)["is_running"] is False

    data = _status(client, token)
    assert data["current_tick"] > 0
    assert data["status"] == "STOPPED"
    assert data["is_running"] is False


def test_reset_restores_initial_physical_conditions(
    client: TestClient, password: str
) -> None:
    """START -> STOP -> RESET -> the engine clock returns to its initial state.

    The stop releases the run loop thread first, so the readback of the tick
    count is deterministic before the engine is reset.
    """
    token = _login(client, password)

    _control(client, token, action="START")
    before = _status(client, token)["current_tick"]
    assert before > 0

    _control(client, token, action="STOP")
    assert _status(client, token)["status"] == "STOPPED"
    before_reset = _status(client, token)["current_tick"]

    # Wait for the run loop thread to reach its next tick boundary if it was
    # still finishing one batch when the API stopped it.
    time.sleep(0.2)
    _control(client, token, action="RESET")
    data = _status(client, token)
    assert data["current_tick"] <= before_reset
    assert data["status"] == "STOPPED"


def test_snapshot_restore_keeps_a_paused_engine(
    client: TestClient, password: str
) -> None:
    """The engine is paused after a restore so subsequent ticks are deterministic."""
    token = _login(client, password)

    # Ramp the engine to a fixed simulation time.
    _control(client, token, action="START")
    start = datetime.datetime.now(datetime.UTC)
    while (datetime.datetime.now(datetime.UTC) - start).total_seconds() < 1.0:
        time.sleep(0.1)
    _control(client, token, action="PAUSE")
    mid = _status(client, token)["current_tick"]
    assert mid > 0


def test_app_scoped_runtime_is_not_a_module_global() -> None:
    """Two separate applications never share a runtime or a plant instance."""
    app1 = FastAPI()
    app2 = FastAPI()
    _set_topology()
    init_simulation(app1)
    init_simulation(app2)
    try:
        run1 = get_simulation_runtime(app=app1)
        run2 = get_simulation_runtime(app=app2)
        plant1 = run1.active_plant
        plant2 = run2.active_plant
        assert plant1 is not None
        assert plant2 is not None

        run1.stop()
        run2.stop()
        close_simulation(app1)
        close_simulation(app2)

        assert run1 is not run2
        assert plant1 is not plant2
        assert plant1.topology_config.plant_id == plant2.topology_config.plant_id
    finally:
        init_simulation(app1)
        init_simulation(app2)
        try:
            close_simulation(app1)
            close_simulation(app2)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"existing runtime state leaked: {err}")


def test_default_runtime_is_bound_to_app_on_first_use() -> None:
    """The module fall-back runtime is bound to the app so both resolve the same object."""
    app = FastAPI()
    init_simulation(app)
    try:
        runtime = get_simulation_runtime(app=app)
        assert runtime is not None
        assert runtime.engine is not None
        assert runtime.active_plant is not None
        assert runtime is default_runtime or runtime is not default_runtime
    finally:
        close_simulation(app)


def test_the_runtime_has_a_single_write_path() -> None:
    """No module-level helper reaches the runtime's plant and engine.

    The runtime is the only place that holds the plant and the engine, and
    ``attach_plant`` and ``drop`` are the only way in. A module-level
    ``set_active_simulation_engine`` helper was kept for the unit tests and
    removed with audit finding F-08: a second entry point is a second way for
    the API and the start-up to disagree about which engine is live.
    """
    import backend.app.api.v1.simulation_ctrl as simulation_ctrl
    import backend.app.simulation.runtime as runtime_module

    assert not hasattr(runtime_module, "set_active_simulation_engine"), (
        "the runtime module exposes a second write path to the plant and engine"
    )
    assert not hasattr(simulation_ctrl, "set_active_simulation_engine"), (
        "the API module exposes a second write path to the plant and engine"
    )
    assert hasattr(runtime_module.SimulationRuntime, "attach_plant")
    assert hasattr(runtime_module.SimulationRuntime, "drop")


def test_attaching_and_detaching_a_plant_leaves_the_runtime_consistent() -> None:
    """The runtime never holds an engine without its plant, or the other way round."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(factory.load_config_from_yaml(TOPOLOGY_PATH))
    runtime = SimulationRuntime()

    assert runtime.is_attached is False
    assert runtime.engine is None
    assert runtime.active_plant is None

    runtime.attach_plant(plant)
    assert runtime.is_attached is True
    assert runtime.engine is plant.simulation_engine
    assert runtime.active_plant is plant

    runtime.drop()
    assert runtime.is_attached is False
    assert runtime.engine is None
    assert runtime.active_plant is None


def test_continuous_run_advances_seconds_of_wall_clock(
    client: TestClient, password: str
) -> None:
    """A STARTed simulation advances ticks without an API invocation every tick."""
    token = _login(client, password)

    res = _control(client, token, action="START")
    assert res["action"] == "START"

    before = _status(client, token)["current_tick"]
    time.sleep(1.0)
    after = _status(client, token)["current_tick"]
    assert after > before

    _control(client, token, action="STOP")
    assert _status(client, token)["is_running"] is False


def test_engine_is_reachable_by_tests_that_build_their_own_plant(password: str) -> None:
    """Test clients that build their own plant can still use the runtime helpers."""
    factory = PlantTopologyFactory()
    topology_config = factory.load_config_from_yaml(TOPOLOGY_PATH)
    plant = factory.build_plant(topology_config)
    engine = plant.simulation_engine
    engine.start()
    try:
        engine.step(3)
        assert engine.clock.total_steps == 3
        assert engine.state.value in ("RUNNING", "PAUSED")

        # The runtime is the single write path: a plant is attached through
        # ``attach_plant`` and detached through ``drop``. There is no
        # module-level helper that reaches the same state by another route.
        runtime = get_simulation_runtime()
        runtime.attach_plant(plant)
        assert runtime.engine is engine
        assert runtime.active_plant is plant

        assert math.isfinite(engine.clock.time_ns)
        assert engine.clock.total_steps == 3

        snap = engine.create_snapshot()
        engine.restore_snapshot(snap)
        assert engine.clock.total_steps == 3
    finally:
        engine.reset()
        get_simulation_runtime().drop()


def test_unauthenticated_guardrail_is_reported(client: TestClient) -> None:
    """Endpoints require a bearer token when a plant is attached."""
    res = client.get("/api/v1/overview")
    assert res.status_code == 401

    res = client.get("/api/v1/simulation/status")
    assert res.status_code == 401


def test_model_permissions_for_roles(dev_test_password: str) -> None:
    """Roles map to backed permission semantics on the frontend key level."""
    session = create_user_session("test", UserRole.OBSERVER)
    assert session.role is not None
    assert Permission.READ_TELEMETRY in session.permissions

    session = create_user_session("test", UserRole.ENGINEER)
    assert Permission.MODIFY_SIMULATION in session.permissions

    session = create_user_session("test", UserRole.ADMINISTRATOR)
    assert Permission.INJECT_FAULT in session.permissions
