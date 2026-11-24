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
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DOCKERFILE = REPO_ROOT / "deployment" / "Dockerfile.backend"
FRONTEND_DOCKERFILE = REPO_ROOT / "deployment" / "Dockerfile.frontend"
COMPOSE_FILES = (
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "deployment" / "docker-compose.yml",
)
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SECURITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security.yml"

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


healthcheck = _load_module(
    "powertwin_healthcheck", REPO_ROOT / "deployment" / "healthcheck.py"
)


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
    def test_the_health_probe_uses_the_python_standard_library(
        self, path: Path
    ) -> None:
        text = path.read_text()
        assert "deployment/healthcheck.py" in text
        assert "curl" not in text

    @pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: p.name)
    def test_the_ports_are_bound_to_the_loopback_interface(self, path: Path) -> None:
        for line in path.read_text().splitlines():
            if '- "' in line and "ports" not in line:
                assert "127.0.0.1:" in line, (
                    f"a published port is not loopback bound: {line}"
                )


class TestCiWorkflow:
    """The pipeline must validate the compose file without weakening it."""

    def test_the_compose_validation_supplies_a_validation_only_password(self) -> None:
        assert (
            f'POSTGRES_PASSWORD: "{VALIDATION_PLACEHOLDER}"' in CI_WORKFLOW.read_text()
        )

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
            healthcheck.build_url("/health/readiness")
            == "http://127.0.0.1:8000/health/readiness"
        )
        assert (
            healthcheck.build_url("health/readiness")
            == "http://127.0.0.1:8000/health/readiness"
        )

    def test_a_successful_answer_is_healthy(self, http_server: HTTPServer) -> None:
        assert healthcheck.probe(_url(http_server, "/ok")) is True

    def test_an_error_answer_is_not_healthy(self, http_server: HTTPServer) -> None:
        assert healthcheck.probe(_url(http_server, "/missing")) is False

    def test_an_unreachable_endpoint_is_not_healthy(self) -> None:
        assert healthcheck.probe("http://127.0.0.1:1/nothing", timeout=1.0) is False

    def test_the_probe_only_ever_reads(self, http_server: HTTPServer) -> None:
        healthcheck.probe(_url(http_server, "/ok"))
        assert REQUESTS == ["GET"]

    def test_the_exit_status_follows_the_probe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(healthcheck, "probe", lambda url: True)
        assert healthcheck.main(["healthcheck.py"]) == 0
        monkeypatch.setattr(healthcheck, "probe", lambda url: False)
        assert healthcheck.main(["healthcheck.py"]) == 1
