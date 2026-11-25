"""Unit tests for the deployment artefacts and the pipeline gates that cover them.

The container images, the compose files and the pipeline definitions decide
what the service runs as, what it can reach and what the pipeline enforces.
A regression in them is invisible to the Python test suite, because the suite
exercises the application and not the way it is packaged, so the invariants
that matter are asserted here.

The assertions are deliberately about the *intent* of the artefacts rather
than about an exact byte sequence, so that a comment or a reordering does not
break them, while a real regression - a build tool left in the runtime layer,
an unpinned base image, a mandatory secret that became optional - does.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from backend.app.historian.models import Base

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DOCKERFILE = REPO_ROOT / "deployment" / "Dockerfile.backend"
FRONTEND_DOCKERFILE = REPO_ROOT / "deployment" / "Dockerfile.frontend"
COMPOSE_FILES = (
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "deployment" / "docker-compose.yml",
)
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
MIGRATION_ENV = REPO_ROOT / "backend" / "migrations" / "env.py"
MIGRATION_VERSIONS = REPO_ROOT / "backend" / "migrations" / "versions"

# The value the CI workflow supplies to the compose validation step. It is a
# placeholder for a syntax check, not a credential.
VALIDATION_PLACEHOLDER = "ci-compose-validation-placeholder-not-a-credential"


def _load_module(module_name: str, path: Path) -> ModuleType:
    """Import a standalone script from its file location."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


healthcheck = _load_module("powertwin_healthcheck", REPO_ROOT / "deployment" / "healthcheck.py")


def _stages(dockerfile: Path) -> list[str]:
    """Split a Dockerfile into its stages, each starting with its FROM line."""
    stages: list[str] = []
    current: list[str] = []
    for line in dockerfile.read_text().splitlines():
        if line.strip().upper().startswith("FROM "):
            if current:
                stages.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        stages.append("\n".join(current))
    return stages


def _runtime_stage(dockerfile: Path) -> str:
    """Return the text of the last stage of a Dockerfile."""
    stages = _stages(dockerfile)
    assert stages, f"{dockerfile} declares no stage"
    return stages[-1]


def _workflow_steps(workflow: Path) -> list[str]:
    """Split a workflow file into its individual steps."""
    parts = workflow.read_text().split("\n      - name: ")
    return [part for part in parts[1:] if part.strip()]


class TestBackendImage:
    """The backend image must not carry anything that only a build needs."""

    def test_the_image_is_built_in_two_stages(self) -> None:
        stages = _stages(BACKEND_DOCKERFILE)
        assert len(stages) == 2, "the backend image must separate building from running"

    def test_the_runtime_stage_carries_no_build_toolchain(self) -> None:
        runtime = _runtime_stage(BACKEND_DOCKERFILE)
        for tool in ("build-essential", "libpq-dev", "gcc", "g++", "cmake"):
            assert tool not in runtime, f"{tool} must not be in the runtime layer"

    def test_the_builder_stage_carries_the_build_toolchain(self) -> None:
        builder = _stages(BACKEND_DOCKERFILE)[0]
        assert "build-essential" in builder

    def test_the_runtime_stage_applies_the_available_operating_system_patches(
        self,
    ) -> None:
        runtime = _runtime_stage(BACKEND_DOCKERFILE)
        assert "apt-get upgrade" in runtime

    def test_the_built_environment_does_not_ship_a_package_installer(self) -> None:
        builder = _stages(BACKEND_DOCKERFILE)[0]
        assert "pip uninstall -y pip" in builder
        assert "pip uninstall -y wheel" in builder
        runtime = _runtime_stage(BACKEND_DOCKERFILE)
        assert "pip install" not in runtime

    def test_the_runtime_stage_removes_the_system_package_installer(self) -> None:
        # The virtual environment has no installer of its own, but the base
        # image ships pip for the system interpreter. A deployed image must
        # carry neither.
        runtime = _runtime_stage(BACKEND_DOCKERFILE)
        assert "/usr/local/bin/pip" in runtime
        assert "/usr/local/lib/python3.12/site-packages/pip" in runtime

    def test_the_dependencies_are_installed_from_the_lock_with_hashes(self) -> None:
        builder = _stages(BACKEND_DOCKERFILE)[0]
        assert "requirements.lock" in builder
        assert "--require-hashes" in builder
        assert "-r /tmp/requirements.txt" not in builder

    def test_the_built_environment_is_verified_against_the_lock(self) -> None:
        builder = _stages(BACKEND_DOCKERFILE)[0]
        assert "verify_locked_environment.py" in builder
        assert "--strict" in builder

    def test_the_build_tool_leaves_no_dependency_of_its_own_behind(self) -> None:
        # The wheel builder has a dependency of its own. Removing the builder
        # alone leaves that dependency in the environment, and the image would
        # then carry a package that no hash in the lock covers.
        builder = _stages(BACKEND_DOCKERFILE)[0]
        assert "pip uninstall -y packaging" in builder

    def test_the_service_runs_as_a_non_root_user(self) -> None:
        runtime = _runtime_stage(BACKEND_DOCKERFILE)
        assert "\nUSER powertwin" in runtime

    def test_the_health_probe_needs_no_extra_http_client(self) -> None:
        runtime = _runtime_stage(BACKEND_DOCKERFILE)
        probe = runtime.split("HEALTHCHECK", 1)[1]
        assert "healthcheck.py" in probe
        assert "curl" not in probe

    def test_every_base_image_is_pinned_by_digest(self) -> None:
        for stage in _stages(BACKEND_DOCKERFILE):
            assert "@sha256:" in stage.splitlines()[0]


class TestFrontendImage:
    """The frontend image is deployed exactly like the backend image."""

    def test_every_base_image_is_pinned_by_digest(self) -> None:
        from_lines = [
            line
            for line in FRONTEND_DOCKERFILE.read_text().splitlines()
            if line.strip().upper().startswith("FROM ")
        ]
        assert from_lines
        for line in from_lines:
            assert "@sha256:" in line


class TestComposeFiles:
    """The compose files must keep their mandatory secret and stay minimal."""

    @pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
    def test_the_database_password_stays_mandatory(self, path: Path) -> None:
        assert "${POSTGRES_PASSWORD:?" in path.read_text()

    @pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
    def test_no_compose_file_carries_a_literal_password(self, path: Path) -> None:
        text = path.read_text()
        assert VALIDATION_PLACEHOLDER not in text
        for line in text.splitlines():
            if "POSTGRES_PASSWORD:" in line:
                value = line.split("POSTGRES_PASSWORD:", 1)[1].strip()
                assert value.startswith('"${') or value.startswith("${"), (
                    f"the compose file carries a literal password: {line}"
                )

    @pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
    def test_the_health_probe_uses_the_python_standard_library(self, path: Path) -> None:
        text = path.read_text()
        assert "deployment/healthcheck.py" in text
        assert "curl" not in text

    @pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
    def test_the_ports_are_bound_to_the_loopback_interface(self, path: Path) -> None:
        for line in path.read_text().splitlines():
            if '- "' in line and "ports" not in line:
                assert "127.0.0.1:" in line, f"a published port is not loopback bound: {line}"

    @pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
    def test_the_operator_action_journal_survives_the_container(self, path: Path) -> None:
        """The audit trail must not disappear with the container that wrote it.

        The operator-action journal is the platform's append-only, tamper-evident
        record. Left in the container's writable layer it is lost as soon as the
        container is replaced, which is exactly when a warranty or dispute
        analysis needs it.
        """
        compose = yaml.safe_load(path.read_text())
        backend = compose["services"]["backend"]
        journal_path = backend["environment"]["OPERATOR_JOURNAL_PATH"]

        mounts = backend.get("volumes") or []
        assert any("operator_journal" in str(mount) for mount in mounts), (
            f"{path.name} does not mount a volume for the operator-action journal"
        )
        assert any(str(mount).endswith(journal_path.rsplit("/", 1)[0]) for mount in mounts), (
            f"{path.name} mounts the journal volume somewhere other than the journal's directory"
        )
        assert "operator_journal" in (compose.get("volumes") or {}), (
            f"{path.name} mounts a journal volume it never declares"
        )


class TestCiWorkflow:
    """The pipeline must validate the compose file without weakening it."""

    def test_the_compose_validation_supplies_a_validation_only_password(self) -> None:
        assert f'POSTGRES_PASSWORD: "{VALIDATION_PLACEHOLDER}"' in CI_WORKFLOW.read_text()

    def test_the_validation_placeholder_is_never_persisted(self) -> None:
        text = CI_WORKFLOW.read_text()
        assert text.count(VALIDATION_PLACEHOLDER) == 1
        assert 'echo "$POSTGRES_PASSWORD"' not in text

    def test_the_workflow_does_not_introduce_a_default_password(self) -> None:
        assert "${POSTGRES_PASSWORD:-" not in CI_WORKFLOW.read_text()

    def test_the_pipeline_starts_the_built_image_and_checks_it(self) -> None:
        text = CI_WORKFLOW.read_text()
        assert "powertwin-backend:ci-test" in text
        assert "simulation_only" in text


class TestDependencyLock:
    """Every workflow must install the pinned, hash-verified dependency set."""

    WORKFLOWS = tuple((REPO_ROOT / ".github" / "workflows").glob("*.yml"))

    def test_the_lock_is_committed(self) -> None:
        lock = REPO_ROOT / "backend" / "requirements.lock"
        assert lock.is_file(), "the dependency lock is not committed"
        assert lock.read_text().strip()

    def test_every_workflow_installs_the_lock_with_hashes(self) -> None:
        for workflow in self.WORKFLOWS:
            for line in workflow.read_text().splitlines():
                stripped = line.strip()
                if not stripped.startswith("pip install"):
                    continue
                assert "backend/requirements.txt" not in stripped, (
                    f"{workflow.name} installs the declared ranges instead of the lock: {stripped}"
                )
                if "backend/requirements.lock" in stripped:
                    assert "--require-hashes" in stripped, (
                        f"{workflow.name} installs the lock without verifying "
                        f"its hashes: {stripped}"
                    )

    def test_the_workflows_cache_the_lock(self) -> None:
        for workflow in self.WORKFLOWS:
            text = workflow.read_text()
            if "pip install" not in text:
                continue
            assert "backend/requirements.lock" in text, (
                f"{workflow.name} does not declare the lock as a cache dependency"
            )

    def test_the_workflows_verify_the_installed_environment(self) -> None:
        # A workflow that installs the lock proves that the pinned versions
        # were available; it does not prove that they are the ones that ended
        # up in the environment. Every workflow that installs the runtime
        # dependencies also has to assert the latter.
        for workflow in self.WORKFLOWS:
            text = workflow.read_text()
            if "backend/requirements.lock" not in text:
                continue
            if "pip install --require-hashes -r backend/requirements.lock" not in text:
                continue
            assert "scripts/verify_locked_environment.py" in text, (
                f"{workflow.name} installs the lock but does not verify the environment"
            )


class TestSecurityWorkflow:
    """Both deployed images are scanned, each under a policy it can satisfy."""

    def test_both_deployed_images_are_scanned(self) -> None:
        text = SECURITY_WORKFLOW.read_text()
        assert "powertwin-backend:scan" in text
        assert "powertwin-frontend:scan" in text

    def test_the_operating_system_policy_requires_a_fix_to_be_available(self) -> None:
        steps = _workflow_steps(SECURITY_WORKFLOW)
        os_steps = [step for step in steps if 'vuln-type: "os"' in step]
        assert os_steps, "no operating-system scan is configured"
        for step in os_steps:
            assert 'ignore-unfixed: "true"' in step

    def test_the_application_package_policy_is_strict(self) -> None:
        steps = _workflow_steps(SECURITY_WORKFLOW)
        library_steps = [step for step in steps if 'vuln-type: "library"' in step]
        assert library_steps, "no application-package scan is configured"
        for step in library_steps:
            assert "ignore-unfixed" not in step

    def test_every_scan_fails_the_job_on_a_finding(self) -> None:
        steps = _workflow_steps(SECURITY_WORKFLOW)
        scan_steps = [step for step in steps if "trivy-action" in step]
        assert scan_steps
        for step in scan_steps:
            assert 'exit-code: "1"' in step
            assert 'severity: "CRITICAL,HIGH"' in step


# =============================================================================
# The health probe itself
# =============================================================================

REQUESTS: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    """A minimal handler that answers 200 on /ok and 404 everywhere else."""

    def do_GET(self) -> None:  # noqa: N802 - the name is imposed by BaseHTTPRequestHandler
        REQUESTS.append(self.command)
        if self.path == "/ok":
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *args: object) -> None:
        """Silence the default logging to stderr."""


@pytest.fixture
def http_server() -> Iterator[HTTPServer]:
    """Run a throwaway HTTP server on the loopback interface."""
    REQUESTS.clear()
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _url(server: HTTPServer, path: str) -> str:
    host, port = server.server_address
    return f"http://{host}:{port}{path}"


class TestHealthProbe:
    """The probe decides whether a container is healthy, so it must be exact."""

    def test_the_url_is_built_from_the_path(self) -> None:
        assert (
            healthcheck.build_url("/health/readiness") == "http://127.0.0.1:8000/health/readiness"
        )
        assert healthcheck.build_url("health/readiness") == "http://127.0.0.1:8000/health/readiness"

    def test_a_successful_answer_is_healthy(self, http_server: HTTPServer) -> None:
        assert healthcheck.probe(_url(http_server, "/ok")) is True

    def test_an_error_answer_is_not_healthy(self, http_server: HTTPServer) -> None:
        assert healthcheck.probe(_url(http_server, "/missing")) is False

    def test_an_unreachable_endpoint_is_not_healthy(self) -> None:
        assert healthcheck.probe("http://127.0.0.1:1/nothing", timeout=1.0) is False

    def test_the_probe_only_ever_reads(self, http_server: HTTPServer) -> None:
        healthcheck.probe(_url(http_server, "/ok"))
        assert REQUESTS == ["GET"]

    def test_the_exit_status_follows_the_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(healthcheck, "probe", lambda url: True)
        assert healthcheck.main(["healthcheck.py"]) == 0
        monkeypatch.setattr(healthcheck, "probe", lambda url: False)
        assert healthcheck.main(["healthcheck.py"]) == 1


class TestFrontendEndToEndSuite:
    """The end-to-end suite drives the shipped HMI against a mock platform.

    The suite is the only part of the repository that runs the HMI as an
    operator would. Two properties have to hold for it, and neither is
    visible to the Python test suite on its own:

    * It must never be able to reach a running platform. A test that could
      address a live installation would be an outward-facing action that
      nobody authorised, so the mock answers every API request, aborts the
      paths it does not model, and blocks every host but the local preview
      server.
    * It must be part of the pipeline. A suite that only runs on a
      developer's machine is documentation, not a gate.
    """

    FRONTEND = REPO_ROOT / "frontend"
    WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-frontend.yml"
    CONFIG = FRONTEND / "playwright.config.ts"
    MOCK = FRONTEND / "e2e" / "mockPlatform.ts"

    def test_the_pipeline_runs_the_end_to_end_suite(self) -> None:
        text = self.WORKFLOW.read_text()
        assert "npm run test:e2e" in text, "the end-to-end suite is not run by the pipeline"
        assert "npx playwright install --with-deps chromium" in text, (
            "the pipeline runs the end-to-end suite without installing its browser"
        )

    def test_the_browser_is_installed_before_the_suite_runs(self) -> None:
        text = self.WORKFLOW.read_text()
        assert text.index("playwright install") < text.index("npm run test:e2e")

    def test_the_suite_serves_the_built_artefact_on_the_loopback_interface(
        self,
    ) -> None:
        text = self.CONFIG.read_text()
        assert "PREVIEW_HOST = '127.0.0.1'" in text
        assert "vite preview" in text, "the suite does not run against the built artefact"
        # The preview server must not be bound to every interface: an
        # end-to-end run must not be reachable from an untrusted network.
        assert "0.0.0.0" not in text

    def test_the_mock_answers_every_api_request_and_blocks_every_other_host(
        self,
    ) -> None:
        text = self.MOCK.read_text()
        assert "'**/api/v1/**'" in text, "the mock does not intercept the platform API"
        assert "route.abort('failed')" in text, "an API path the mock does not model is not aborted"
        assert "route.abort('blockedbyclient')" in text, (
            "a request to a host other than the preview server is not blocked"
        )

    def test_the_end_to_end_scripts_are_declared(self) -> None:
        package = json.loads((self.FRONTEND / "package.json").read_text())
        scripts = package["scripts"]
        assert scripts["test:e2e"] == "playwright test"
        # The end-to-end suite must exercise a fresh build of the artefact,
        # never a stale one left over from an earlier run.
        assert "build" in scripts["pretest:e2e"]

    def test_the_playwright_dependency_is_declared(self) -> None:
        package = json.loads((self.FRONTEND / "package.json").read_text())
        assert "@playwright/test" in package["devDependencies"]

    def test_the_unit_suite_does_not_collect_the_end_to_end_specs(self) -> None:
        text = (self.FRONTEND / "vite.config.ts").read_text()
        assert "e2e/**" in text, "Vitest would collect the Playwright specs, which run in a browser"

    def test_the_end_to_end_code_is_type_checked(self) -> None:
        config = json.loads((self.FRONTEND / "tsconfig.json").read_text())
        assert "e2e" in config["include"]
        assert "playwright.config.ts" in config["include"]

    def test_the_end_to_end_artifacts_are_not_committed(self) -> None:
        ignore = (REPO_ROOT / ".gitignore").read_text()
        assert "frontend/test-results/" in ignore
        assert "frontend/playwright-report/" in ignore


class TestMigrationDriftGate:
    """A release must fail when the ORM and the migrations disagree.

    The offline validator proves that the migration graph has a single head
    and that the whole chain renders to SQL. It cannot prove that the ORM
    models describe the same schema as the migration history: that comparison
    needs a live database and a non-empty `target_metadata`.

    Four properties have to hold, and none of them is visible to the
    application test suite on its own:

    * The Alembic environment must declare the ORM metadata, otherwise the
      comparison is empty and always passes.
    * The TimescaleDB-owned index must be excluded, otherwise the comparison
      always fails for a difference nobody is allowed to fix.
    * The release pipeline must run the comparison against a real database,
      otherwise the difference is never noticed.
    * The ORM must declare the index set the migrations create, otherwise the
      comparison fails on every release.
    """

    def test_the_alembic_environment_declares_the_orm_metadata(self) -> None:
        text = MIGRATION_ENV.read_text()
        assert "target_metadata = Base.metadata" in text, (
            "the Alembic environment does not compare the ORM metadata with the "
            "migrations, so a model changed without a migration goes unnoticed"
        )
        assert "target_metadata = None" not in text

    def test_the_alembic_environment_excludes_the_timescaledb_owned_index(self) -> None:
        text = MIGRATION_ENV.read_text()
        assert "telemetry_data_timestamp_ns_idx" in text, (
            "the index that TimescaleDB creates is not excluded from the "
            "comparison, so every release would report it as drift"
        )
        assert "include_object=include_object" in text, (
            "the exclusion is declared but not passed to Alembic"
        )

    def test_the_orm_declares_the_index_set_the_migrations_create(self) -> None:
        created: set[str] = set()
        for migration in sorted(MIGRATION_VERSIONS.glob("*.py")):
            created.update(re.findall(r'op\.create_index\(\s*"([^"]+)"', migration.read_text()))
        assert created, "no index was found in the migrations"
        declared = {
            index.name for table in Base.metadata.tables.values() for index in table.indexes
        }
        assert declared == created, (
            "the ORM and the migrations declare different index sets, so "
            "`alembic check` would fail on every release"
        )

    @staticmethod
    def _release_job() -> dict[str, object]:
        workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text())
        job = workflow["jobs"]["release-build"]
        assert isinstance(job, dict)
        return job

    @staticmethod
    def _drift_gate_step(job: dict[str, object]) -> dict[str, object]:
        """Return the one step that runs `alembic check`."""
        steps = job["steps"]
        assert isinstance(steps, list)
        gates = [
            step for step in steps if re.search(r"alembic[^\n]*\bcheck\b", step.get("run", ""))
        ]
        assert len(gates) == 1, (
            f"the drift gate must be a single, identifiable step, found {len(gates)}"
        )
        gate = gates[0]
        assert isinstance(gate, dict)
        return gate

    def test_the_release_pipeline_runs_the_drift_gate_against_a_database(self) -> None:
        job = self._release_job()
        assert job.get("services"), (
            "the release job has no database to compare the ORM metadata against"
        )
        services = job["services"]
        assert isinstance(services, dict)
        service = next(iter(services.values()))
        assert service["image"].startswith("timescale/timescaledb@sha256:"), (
            "the drift gate must run against a digest-pinned TimescaleDB image: "
            "the migrations convert a table into a hypertable, which a plain "
            "PostgreSQL server cannot do"
        )
        assert "pg_isready" in service["options"], (
            "the drift gate may start before the database is ready to serve"
        )

        gate = self._drift_gate_step(job)
        run = gate["run"]
        assert "upgrade head" in run, (
            "the drift gate does not build the schema the migrations describe"
        )
        check = re.search(r"alembic[^\n]*\bcheck\b", run)
        assert check is not None
        assert run.index("upgrade head") < check.start(), (
            "the drift gate compares before the schema it compares against exists"
        )

    def test_the_drift_gate_step_and_the_service_container_agree_on_the_credentials(
        self,
    ) -> None:
        job = self._release_job()
        services = job["services"]
        assert isinstance(services, dict)
        service = next(iter(services.values()))
        service_env = service["env"]

        step_env = self._drift_gate_step(job)["env"]
        for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
            assert step_env[key] == service_env[key], (
                f"the drift gate and its database disagree on {key}"
            )
        assert "POSTGRES_SERVER" in step_env and "POSTGRES_PORT" in step_env, (
            "the drift gate does not say where the database is"
        )
