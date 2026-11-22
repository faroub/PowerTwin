"""Tests for deployment binding safety and production configuration validity.

These tests verify that:
    * The deployment Compose file does not publish writable interfaces to
      untrusted networks by default.
    * The required production configuration is either enforced or documented.
"""

import subprocess

import yaml


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _load_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_deployment_compose_binds_ports_to_loopback() -> None:
    """Test all published ports in the deployment Compose file are loopback-bound."""
    deployment = _load("deployment/docker-compose.yml")

    for service_name, service_definition in deployment["services"].items():
        for port in service_definition.get("ports", []):
            assert port.startswith("127.0.0.1:"), (
                f"Service '{service_name}' publishes port '{port}' "
                "without a loopback interface binding."
            )


def test_root_compose_binds_ports_to_loopback() -> None:
    """Test all published ports in the root Compose file are loopback-bound."""
    root = _load("docker-compose.yml")

    for service_name, service_definition in root["services"].items():
        for port in service_definition.get("ports", []):
            assert port.startswith("127.0.0.1:"), (
                f"Service '{service_name}' publishes port '{port}' "
                "without a loopback interface binding."
            )


def test_production_config_requires_password_via_environment() -> None:
    """Test the production template does not contain a fixed password string."""
    production = _load("configs/prod.yaml")

    database = production.get("database", {})
    password = database.get("password", "")
    assert password.startswith("${"), (
        "The production configuration must not contain a fixed password."
    )


def test_environment_example_does_not_ship_a_password() -> None:
    """Test the environment example does not ship a fixed database password."""
    content = _load_text("configs/.env.example")
    assert "powertwin_secret" not in content, (
        "Template files must not ship a fixed password."
    )
    assert "powertwin_prod_secure_password" not in content


def test_deployment_docker_compose_gets_password_from_environment() -> None:
    """Test the deployment Compose file reads the password from the environment."""
    deployment = _load("deployment/docker-compose.yml")

    for service_name, service_definition in deployment["services"].items():
        if "POSTGRES_PASSWORD" in service_definition.get("environment", {}):
            reference = service_definition["environment"]["POSTGRES_PASSWORD"]
            assert "${POSTGRES_PASSWORD}" in reference, (
                f"Service '{service_name}' must read the database password "
                "from the environment."
            )


def test_root_docker_compose_gets_password_from_environment() -> None:
    """Test the root Compose file reads the password from the environment."""
    root = _load("docker-compose.yml")

    for service_name, service_definition in root["services"].items():
        if "POSTGRES_PASSWORD" in service_definition.get("environment", {}):
            reference = service_definition["environment"]["POSTGRES_PASSWORD"]
            assert "${POSTGRES_PASSWORD}" in reference, (
                f"Service '{service_name}' must read the database password "
                "from the environment."
            )


def test_idea_artifacts_are_untracked() -> None:
    """Test the repository does not track IDE cache files."""
    tracked = _git_ls_files(".idea")
    assert tracked == "", "IDE cache files must not be tracked in version control."


def test_pycache_artifacts_are_untracked() -> None:
    """Test the repository does not track Python cache files."""
    tracked = _git_ls_files("pycache")
    assert tracked == "", "Python cache files must not be tracked in version control."


def test_overflow_files_are_untracked() -> None:
    """Test the repository does not track historian overflow files."""
    tracked = _git_ls_files("overflow")
    assert tracked == "", (
        "Historian overflow artifacts must not be tracked in version control."
    )


def test_port_binding_constraint_in_config_safety_invariants() -> None:
    """Test the configuration rejects Modbus writes outside the loopback interface."""
    from backend.app.core.config import settings

    assert settings.PROTOCOL_GATEWAY_HOST == "127.0.0.1"
    assert settings.ALLOW_EXTERNAL_MODBUS_WRITES is False


def test_alembic_migrations_edge_resource_allocated() -> None:
    """Test the migration graph resolves through the head migration."""
    output = _run_alembic_history()
    assert "001_initial_schema -> 002_user_accounts (head)" in output


def test_alembic_config_has_qualname_logger_definitions() -> None:
    """Test the alembic.ini logging configuration uses explicit qualnames."""
    content = _load_text("backend/alembic.ini")
    assert "[logger_root]" in content
    assert "qualname = sqlalchemy.engine" in content
    assert "qualname = alembic" in content


def _git_ls_files(pattern: str) -> str:
    """Return tracked paths that match the given pattern."""
    result = subprocess.run(
        ["git", "ls-files", pattern],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _run_alembic_history() -> str:
    """Run the alembic history command against the backend migration environment."""
    result = subprocess.run(
        ["alembic", "history"],
        cwd="backend",
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout
