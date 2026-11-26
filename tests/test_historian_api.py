"""Tests for the historian query API.

The historian is the platform's time-series store. Its query endpoints are
read-only and guarded by the READ_TELEMETRY permission, and the screen that
reads them has to be able to tell three situations apart: the store holds
rows, the store holds no rows, and the store cannot be reached at all.

The tests below drive the endpoints through a stubbed session so that they
assert the endpoint's behaviour rather than the presence of a database.
"""

import socket
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.app.historian.db import get_db
from backend.app.main import app


class _StubResult:
    """The subset of a SQLAlchemy result the query engine reads."""

    def __init__(self, records: list[Any]) -> None:
        self._records = records

    def scalars(self) -> "_StubResult":
        return self

    def all(self) -> list[Any]:
        return self._records

    def first(self) -> Any | None:
        return self._records[0] if self._records else None


class _StubSession:
    """A session that answers every query with the same rows."""

    def __init__(self, records: list[Any]) -> None:
        self._records = records

    async def execute(self, _statement: Any) -> _StubResult:
        return _StubResult(self._records)


class _UnavailableSession:
    """A session whose every query fails the way an unreachable store does."""

    async def execute(self, _statement: Any) -> _StubResult:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


class _UnresolvableHostSession:
    """A session whose every query fails the way an unresolvable host does.

    The asyncpg driver lets the socket error escape untranslated when the
    store's host name cannot be resolved, so this failure arrives as an
    ``OSError`` rather than as a ``SQLAlchemyError``.
    """

    async def execute(self, _statement: Any) -> _StubResult:
        raise socket.gaierror(-2, "Name or service not known")


def _override_session(client: TestClient, session: Any) -> None:
    """Point the endpoint's session dependency at a stub."""

    async def _stub() -> AsyncIterator[Any]:
        yield session

    app.dependency_overrides[get_db] = _stub


@pytest.fixture
def telemetry_row() -> SimpleNamespace:
    """A telemetry row shaped the way the historian stores one."""
    return SimpleNamespace(
        timestamp_ns=1_000_000_000,
        source_timestamp_ns=1_000_000_000,
        tag_id="dc_voltage_v",
        equipment_id="CONTAINER_01",
        val_float=812.4,
        unit="V",
        quality="GOOD",
        source_type="SIMULATED",
        simulation_run_id="RUN_01",
    )


@pytest.fixture
def warranty_row() -> SimpleNamespace:
    """A warranty row shaped the way the historian stores one."""
    return SimpleNamespace(
        container_id="CONTAINER_01",
        simulation_run_id="RUN_01",
        updated_at_ns=3_600_000_000_000,
        total_energy_throughput_wh=124_500_000.0,
        equivalent_full_cycles=6.2,
        max_temperature_recorded_c=41.5,
        time_above_45c_seconds=12.5,
        current_soh_pct=98.4,
    )


@pytest.fixture
def auth_headers(client: TestClient, dev_test_password: str) -> dict[str, str]:
    """Sign in as an observer, who is allowed to read telemetry."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "observer", "password": dev_test_password},
    )
    assert login_res.status_code == 200
    return {"Authorization": f"Bearer {login_res.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    """Never let a stubbed session leak into the next test."""
    yield
    app.dependency_overrides.pop(get_db, None)


def test_the_historian_queries_reject_an_unauthenticated_request(client: TestClient) -> None:
    """An unauthenticated read of the historian is refused."""
    assert client.get("/api/v1/historian/telemetry").status_code == 401
    assert client.get("/api/v1/historian/commands").status_code == 401
    assert client.get("/api/v1/historian/alarms").status_code == 401
    assert client.get("/api/v1/historian/warranty/CONTAINER_01").status_code == 401


def test_an_observer_can_read_the_telemetry_the_store_holds(
    client: TestClient,
    auth_headers: dict[str, str],
    telemetry_row: SimpleNamespace,
) -> None:
    """The telemetry endpoint answers with the rows the store holds."""
    _override_session(client, _StubSession([telemetry_row]))

    res = client.get("/api/v1/historian/telemetry", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    record = body["records"][0]
    assert record["equipment_id"] == "CONTAINER_01"
    assert record["tag_id"] == "dc_voltage_v"
    assert record["value"] == 812.4
    assert record["unit"] == "V"
    assert record["quality"] == "GOOD"


def test_an_empty_store_answers_with_no_rows(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """An empty store is a successful query that returned nothing."""
    _override_session(client, _StubSession([]))

    res = client.get("/api/v1/historian/telemetry", headers=auth_headers)

    assert res.status_code == 200
    assert res.json() == {"count": 0, "records": []}


def test_an_unreachable_store_is_reported_as_unavailable(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A store that cannot be reached is reported as unavailable.

    The screen has to be able to tell "the store holds no rows" from "the
    store could not be asked". A bare 500 would tell the operator neither.
    """
    _override_session(client, _UnavailableSession())

    res = client.get("/api/v1/historian/telemetry", headers=auth_headers)

    assert res.status_code == 503
    assert "unavailable" in res.json()["detail"].lower()


def test_an_unresolvable_store_host_is_reported_as_unavailable(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A store whose host cannot be resolved is reported as unavailable too.

    The asyncpg driver lets the socket error escape untranslated, so the
    failure arrives as an ``OSError`` and not as a ``SQLAlchemyError``.
    """
    _override_session(client, _UnresolvableHostSession())

    res = client.get("/api/v1/historian/telemetry", headers=auth_headers)

    assert res.status_code == 503
    assert "unavailable" in res.json()["detail"].lower()


def test_a_reversed_time_range_is_refused(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A range that ends before it starts is refused before it is run."""
    _override_session(client, _StubSession([]))

    res = client.get(
        "/api/v1/historian/telemetry",
        params={"start_time_ns": 2_000, "end_time_ns": 1_000},
        headers=auth_headers,
    )

    assert res.status_code == 422


def test_the_warranty_endpoint_answers_with_the_recorded_metrics(
    client: TestClient,
    auth_headers: dict[str, str],
    warranty_row: SimpleNamespace,
) -> None:
    """The warranty endpoint answers with the metrics the store holds."""
    _override_session(client, _StubSession([warranty_row]))

    res = client.get("/api/v1/historian/warranty/CONTAINER_01", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["container_id"] == "CONTAINER_01"
    assert body["total_energy_throughput_wh"] == 124_500_000.0
    assert body["equivalent_full_cycles"] == 6.2
    assert body["current_soh_pct"] == 98.4


def test_the_warranty_endpoint_answers_with_the_verdict_and_the_projection(
    client: TestClient,
    auth_headers: dict[str, str],
    warranty_row: SimpleNamespace,
) -> None:
    """The endpoint adds the verdict and the projection to the stored row.

    The screen has to be able to say where the container stands against its
    warranty band, and the degradation model behind the answer is
    illustrative, so the answer says so too.
    """
    _override_session(client, _StubSession([warranty_row]))

    res = client.get("/api/v1/historian/warranty/CONTAINER_01", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["warranty_status"] == "WITHIN_WARRANTY"
    assert body["warranty_threshold_pct"] == 70.0
    assert body["projection_horizon_years"] == 10.0
    assert body["projected_soh_pct"] is not None
    assert body["illustrative"] is True


def test_the_warranty_endpoint_can_be_pinned_to_one_run(
    client: TestClient,
    auth_headers: dict[str, str],
    warranty_row: SimpleNamespace,
) -> None:
    """The store holds one row per container and run."""
    _override_session(client, _StubSession([warranty_row]))

    res = client.get(
        "/api/v1/historian/warranty/CONTAINER_01",
        params={"simulation_run_id": "RUN_01"},
        headers=auth_headers,
    )

    assert res.status_code == 200
    assert res.json()["simulation_run_id"] == "RUN_01"


def test_the_warranty_endpoint_reports_a_worn_container_as_at_the_end_of_its_life(
    client: TestClient,
    auth_headers: dict[str, str],
    warranty_row: SimpleNamespace,
) -> None:
    """A container below its threshold is not reported as being in warranty."""
    warranty_row.current_soh_pct = 65.0
    _override_session(client, _StubSession([warranty_row]))

    res = client.get("/api/v1/historian/warranty/CONTAINER_01", headers=auth_headers)

    assert res.status_code == 200
    assert res.json()["warranty_status"] == "AT_END_OF_LIFE"


def test_the_warranty_endpoint_reports_an_unknown_verdict_rather_than_a_number(
    client: TestClient,
    auth_headers: dict[str, str],
    warranty_row: SimpleNamespace,
) -> None:
    """A row without a state of health answers UNKNOWN, not a plausible number."""
    warranty_row.current_soh_pct = None
    _override_session(client, _StubSession([warranty_row]))

    res = client.get("/api/v1/historian/warranty/CONTAINER_01", headers=auth_headers)

    assert res.status_code == 200
    body = res.json()
    assert body["warranty_status"] == "UNKNOWN"
    assert body["projected_soh_pct"] is None


def test_a_container_without_a_warranty_record_is_reported_as_missing(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A container the store knows nothing about answers 404, not an error page."""
    _override_session(client, _StubSession([]))

    res = client.get("/api/v1/historian/warranty/CONTAINER_99", headers=auth_headers)

    assert res.status_code == 404
    assert "CONTAINER_99" in res.json()["detail"]
