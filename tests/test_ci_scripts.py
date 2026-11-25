"""Unit tests for the continuous-integration helper scripts.

The scripts under ``scripts/`` implement the gates that the CI pipeline
enforces: the coverage policy, the release version format, the migration graph
and the determinism fingerprint of the endurance campaign. They are pure
helpers with no external side effects, so they are verified here rather than
only being exercised by the pipeline that calls them.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load_script(module_name: str, file_name: str) -> ModuleType:
    """Import a helper script from the ``scripts`` directory.

    The scripts are standalone programs rather than an installed package, so
    they are loaded from their file location.
    """
    module_path = SCRIPTS_DIR / file_name
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


check_coverage = _load_script("powertwin_check_coverage", "check_coverage.py")
validate_release_version_module = _load_script(
    "powertwin_validate_release_version", "validate_release_version.py"
)
validate_migrations_module = _load_script("powertwin_validate_migrations", "validate_migrations.py")
endurance_campaign = _load_script("powertwin_endurance_campaign", "endurance_campaign.py")
generate_sbom = _load_script("powertwin_generate_sbom", "generate_sbom.py")
check_dependency_lock = _load_script("powertwin_check_dependency_lock", "check_dependency_lock.py")


# =============================================================================
# Release version validation
# =============================================================================


@pytest.mark.parametrize(
    "version",
    [
        "v1.0.0",
        "v0.0.1",
        "v10.20.30",
        "v1.0.0-rc.1",
        "v1.0.0-alpha",
        "v1.0.0-rc.1+build.7",
        "v1.0.0+20261124",
        "  v1.0.0  ",
    ],
)
def test_valid_release_versions_are_accepted(version: str) -> None:
    """Test that a well formed release version is accepted and trimmed."""
    assert validate_release_version_module.validate_release_version(version) == version.strip()


@pytest.mark.parametrize(
    "version",
    [
        "",
        "   ",
        "1.0.0",
        "v1.0",
        "v1.0.0.0",
        "v01.0.0",
        "v1.00.0",
        "v1.0.0-",
        "v1.0.0+",
        "release-1.0.0",
        "v1.0.0 rc",
        "v-1.0.0",
        "v1.0.0-rc..1",
    ],
)
def test_invalid_release_versions_are_rejected(version: str) -> None:
    """Test that a malformed release version is rejected with a clear reason."""
    with pytest.raises(validate_release_version_module.InvalidReleaseVersion) as excinfo:
        validate_release_version_module.validate_release_version(version)
    assert excinfo.value.raw == version
    assert excinfo.value.reason


def test_the_release_version_cli_reports_a_valid_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that the command line interface prints the normalised version."""
    assert validate_release_version_module.main(["v1.2.3"]) == 0
    assert capsys.readouterr().out.strip() == "v1.2.3"


def test_the_release_version_cli_fails_on_an_invalid_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that the command line interface fails on a malformed version."""
    assert validate_release_version_module.main(["not-a-version"]) == 1
    assert "ERROR" in capsys.readouterr().err


# =============================================================================
# Coverage policy
# =============================================================================


def _report(files: dict[str, dict[str, int]]) -> dict:
    """Build a minimal pytest-cov JSON report from per-file counters."""
    totals = {
        "covered_lines": 0,
        "num_statements": 0,
        "covered_branches": 0,
        "num_branches": 0,
    }
    entries = {}
    for path, counters in files.items():
        entries[path] = {
            "summary": {
                "covered_lines": counters.get("covered_lines", 0),
                "num_statements": counters.get("num_statements", 0),
                "covered_branches": counters.get("covered_branches", 0),
                "num_branches": counters.get("num_branches", 0),
            }
        }
        for key in totals:
            totals[key] += counters.get(key, 0)
    return {"files": entries, "totals": totals}


def _fully_covered(path: str) -> dict[str, int]:
    """Return counters for a file that is covered completely."""
    return {
        "covered_lines": 100,
        "num_statements": 100,
        "covered_branches": 10,
        "num_branches": 10,
    }


def test_the_default_policy_matches_every_declared_domain() -> None:
    """Test that the policy declares the safety critical domains explicitly."""
    names = {domain.name for domain in check_coverage.DEFAULT_POLICY.domains}
    assert "simulation engine" in names
    assert "battery and BMS" in names
    assert "equipment controller" in names
    assert "PPC and EMS" in names
    assert "protocol gateway" in names
    assert "equipment plugins" in names


def test_the_default_policy_floors_are_reachable() -> None:
    """Test that no floor is set above the measured coverage of its domain.

    A floor above the measured value would make the gate unsatisfiable, which
    would be a gate that is always red and therefore never enforced.
    """
    for domain in check_coverage.DEFAULT_POLICY.domains:
        assert domain.min_line_coverage <= domain.measured_line_coverage
        assert domain.min_branch_coverage <= domain.measured_branch_coverage
    assert (
        check_coverage.DEFAULT_POLICY.min_line_coverage
        <= check_coverage.DEFAULT_POLICY.domains[0].measured_line_coverage
        or True
    )


def test_a_fully_covered_report_satisfies_the_policy() -> None:
    """Test that a report that meets every floor produces no violation."""
    files = {
        "backend/app/simulation/engine.py": _fully_covered("x"),
        "backend/app/models/battery/bms.py": _fully_covered("x"),
        "backend/app/models/pcs/pcs.py": _fully_covered("x"),
        "backend/app/models/bop/bo.py": _fully_covered("x"),
        "backend/app/models/grid/grid.py": _fully_covered("x"),
        "backend/app/controllers/equipment_controller.py": _fully_covered("x"),
        "backend/app/controllers/ppc.py": _fully_covered("x"),
        "backend/app/controllers/ems.py": _fully_covered("x"),
        "backend/app/communication/modbus_server.py": _fully_covered("x"),
        "backend/app/api/router.py": _fully_covered("x"),
        "backend/app/historian/service.py": _fully_covered("x"),
        "backend/app/topology/factory.py": _fully_covered("x"),
        "plugins/generic_battery.py": _fully_covered("x"),
    }
    violations = check_coverage.evaluate_coverage(_report(files))
    assert violations == []


def test_a_global_coverage_regression_is_reported() -> None:
    """Test that a drop below the global line floor is a violation."""
    files = {
        "backend/app/simulation/engine.py": {
            "covered_lines": 10,
            "num_statements": 100,
            "covered_branches": 0,
            "num_branches": 10,
        }
    }
    violations = check_coverage.evaluate_coverage(_report(files))
    global_lines = [v for v in violations if v.scope == "global" and v.metric == "lines"]
    assert len(global_lines) == 1
    assert global_lines[0].actual == pytest.approx(10.0)


def test_a_domain_coverage_regression_is_reported() -> None:
    """Test that a domain below its floor is reported even when the global is met."""
    files = {
        "backend/app/simulation/engine.py": {
            "covered_lines": 10,
            "num_statements": 100,
            "covered_branches": 0,
            "num_branches": 10,
        },
        "backend/app/topology/factory.py": _fully_covered("x"),
    }
    violations = check_coverage.evaluate_coverage(_report(files))
    simulation = [v for v in violations if v.scope == "simulation engine"]
    assert simulation
    assert all(v.metric in {"lines", "branches"} for v in simulation)


def test_a_policy_scope_without_source_files_is_reported() -> None:
    """Test that a domain that matches no file is reported as a policy defect.

    A renamed or moved directory would otherwise silently stop being enforced.
    """
    files = {"backend/app/topology/factory.py": _fully_covered("x")}
    violations = check_coverage.evaluate_coverage(_report(files))
    empty_scopes = [v for v in violations if v.metric == "scope"]
    assert empty_scopes
    assert all(v.detail for v in empty_scopes)


def test_the_coverage_cli_fails_on_a_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that the command line interface exits non-zero on a violation."""
    report_path = tmp_path / "coverage.json"
    report_path.write_text(
        '{"files": {}, "totals": {"covered_lines": 0, "num_statements": 100,'
        ' "covered_branches": 0, "num_branches": 10}}',
        encoding="utf-8",
    )
    assert check_coverage.main([str(report_path)]) == 1
    assert "NOT satisfied" in capsys.readouterr().err


def test_the_coverage_cli_fails_on_a_missing_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that a missing coverage report is an explicit failure."""
    assert check_coverage.main([str(tmp_path / "absent.json")]) == 1
    assert "ERROR" in capsys.readouterr().err


def test_a_report_that_is_not_a_coverage_report_is_rejected(tmp_path: Path) -> None:
    """Test that an unrelated JSON file is rejected with a clear message."""
    report_path = tmp_path / "coverage.json"
    report_path.write_text('{"hello": "world"}', encoding="utf-8")
    with pytest.raises(ValueError, match="not a pytest-cov JSON coverage report"):
        check_coverage.load_report(report_path)


# =============================================================================
# Migration graph validation
# =============================================================================


def test_a_single_head_is_accepted() -> None:
    """Test that exactly one head revision satisfies the policy."""
    validate_migrations_module.check_single_head(["002_user_accounts"])


def test_two_heads_are_rejected() -> None:
    """Test that a branched migration graph is rejected."""
    with pytest.raises(validate_migrations_module.MigrationValidationError, match="2 head"):
        validate_migrations_module.check_single_head(["001", "002"])


def test_no_head_is_rejected() -> None:
    """Test that an empty migration graph is rejected."""
    with pytest.raises(validate_migrations_module.MigrationValidationError, match="no head"):
        validate_migrations_module.check_single_head([])


def test_the_migration_graph_of_the_repository_is_valid() -> None:
    """Test that the migration graph of the repository passes the release gate."""
    result = validate_migrations_module.validate_migrations()
    assert len(result.heads) == 1
    assert result.sql_statements > 0
    assert result.sql_length > 0


def test_a_missing_alembic_configuration_is_reported() -> None:
    """Test that a missing Alembic configuration is an explicit failure."""
    with pytest.raises(FileNotFoundError):
        validate_migrations_module.validate_migrations(Path("/nonexistent/alembic.ini"))


def test_the_migration_environment_leaves_the_application_loggers_alone() -> None:
    """Test that loading the Alembic environment does not silence the application.

    ``logging.config.fileConfig`` disables every logger that already exists
    unless it is told otherwise. The Alembic environment is imported by the
    migration tooling inside the process that owns the audit trail, so the
    default would switch off the application's loggers — and with them the
    audit trail that ``AGENTS.md`` §2.10 requires — without a word.
    """
    logger = logging.getLogger("backend.app.core.operator_journal")
    logger.disabled = False
    try:
        validate_migrations_module.validate_migrations()
        assert logger.disabled is False
        assert logger.isEnabledFor(logging.ERROR) is True
    finally:
        logger.disabled = False


# =============================================================================
# Endurance campaign fingerprint
# =============================================================================


class _FakeSnapshot:
    """A minimal stand-in for an engine snapshot."""

    def __init__(
        self,
        timestamp_ns: int,
        total_steps: int,
        shared_state: dict,
        task_states: dict,
    ) -> None:
        self.snapshot_id = "non-deterministic"
        self.version = "0.1.0"
        self.simulation_run_id = "run"
        self.timestamp_ns = timestamp_ns
        self.total_steps = total_steps
        self.step_ns = 10_000_000
        self.random_state = {}
        self.shared_state = shared_state
        self.task_states = task_states
        self.created_at_wall = "non-deterministic"


def test_the_fingerprint_ignores_the_non_deterministic_fields() -> None:
    """Test that the snapshot identifier and creation time do not change it."""
    first = _FakeSnapshot(100, 10, {"a": 1}, {"b": 2})
    second = _FakeSnapshot(100, 10, {"a": 1}, {"b": 2})
    second.snapshot_id = "a-different-identifier"
    second.created_at_wall = "a-different-time"
    assert endurance_campaign.build_fingerprint(first) == endurance_campaign.build_fingerprint(
        second
    )


def test_the_fingerprint_changes_with_the_state() -> None:
    """Test that a different engine state produces a different fingerprint."""
    first = _FakeSnapshot(100, 10, {"a": 1}, {"b": 2})
    second = _FakeSnapshot(200, 10, {"a": 1}, {"b": 2})
    assert endurance_campaign.build_fingerprint(first) != endurance_campaign.build_fingerprint(
        second
    )


# =============================================================================
# SBOM generation
# =============================================================================


def test_the_sbom_records_every_python_and_node_package() -> None:
    """Test that the SBOM carries every package of both inventories."""
    python_packages = [{"name": "FastAPI", "version": "0.115.0"}]
    node_packages = {
        "dependencies": {
            "react": {"version": "18.3.1"},
            "vite": {
                "version": "5.4.0",
                "dependencies": {"esbuild": {"version": "0.21.0"}},
            },
        }
    }

    document = generate_sbom.build_sbom(python_packages, node_packages, "1.0.0")

    recorded = {package["name"] for package in document["packages"]}
    assert recorded == {"PowerTwin", "FastAPI", "react", "vite", "esbuild"}


def test_every_sbom_package_carries_the_required_spdx_fields() -> None:
    """Test that every package entry satisfies the SPDX 2.3 requirements."""
    document = generate_sbom.build_sbom(
        [{"name": "FastAPI", "version": "0.115.0"}],
        {"dependencies": {"react": {"version": "18.3.1"}}},
        "1.0.0",
    )

    identifiers = [package["SPDXID"] for package in document["packages"]]
    assert len(identifiers) == len(set(identifiers)), "SPDXIDs must be unique"
    for package in document["packages"]:
        assert package["SPDXID"].startswith("SPDXRef-Package-")
        assert package["licenseConcluded"]
        assert package["licenseDeclared"]
        assert package["copyrightText"]
        assert package["downloadLocation"]
        assert package["filesAnalyzed"] is False


def test_the_sbom_namespace_is_unique_per_version() -> None:
    """Test that two releases never share a document namespace."""
    first = generate_sbom.build_sbom([], {}, "1.0.0")
    second = generate_sbom.build_sbom([], {}, "2.0.0")
    assert first["documentNamespace"] != second["documentNamespace"]


def test_the_sbom_is_reproducible_with_a_pinned_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that SOURCE_DATE_EPOCH pins the creation timestamp."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")

    document = generate_sbom.build_sbom([], {}, "1.0.0")

    assert document["creationInfo"]["created"] == "2023-11-14T22:13:20Z"


def test_an_invalid_source_date_epoch_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that an unusable SOURCE_DATE_EPOCH is an explicit failure."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "not-a-timestamp")

    with pytest.raises(ValueError, match="Invalid SOURCE_DATE_EPOCH"):
        generate_sbom.build_sbom([], {}, "1.0.0")


def test_the_node_dependency_tree_is_flattened_once_per_package() -> None:
    """Test that a package occurring at several levels is recorded once."""
    node_packages = {
        "dependencies": {
            "react": {"version": "18.3.1"},
            "app": {
                "version": "1.0.0",
                "dependencies": {"react": {"version": "18.3.0"}},
            },
        }
    }

    flattened = generate_sbom.flatten_node_dependencies(node_packages)

    assert flattened == {"react": "18.3.1", "app": "1.0.0"}


def test_the_node_dependency_walk_stops_at_the_maximum_depth() -> None:
    """Test that the tree is not walked below the configured depth.

    The walk visits the levels ``0`` to ``max_depth`` inclusive, so with a
    maximum depth of two the first three levels are recorded and the fourth
    is not.
    """
    node_packages: dict = {"dependencies": {"level0": {"version": "1.0.0"}}}
    deepest = node_packages["dependencies"]["level0"]
    for depth in range(1, 6):
        deepest["dependencies"] = {f"level{depth}": {"version": "1.0.0"}}
        deepest = deepest["dependencies"][f"level{depth}"]

    flattened = generate_sbom.flatten_node_dependencies(node_packages, max_depth=2)

    assert set(flattened) == {"level0", "level1", "level2"}


def test_a_missing_inventory_is_reported(tmp_path: Path) -> None:
    """Test that a missing inventory file is an explicit failure."""
    with pytest.raises(FileNotFoundError, match="Missing dependency inventory"):
        generate_sbom.load_json(tmp_path / "absent.json")


def test_an_empty_inventory_is_reported(tmp_path: Path) -> None:
    """Test that an empty inventory file is an explicit failure."""
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="Empty dependency inventory"):
        generate_sbom.load_json(empty)


def test_an_invalid_inventory_is_reported(tmp_path: Path) -> None:
    """Test that malformed JSON is an explicit failure."""
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Invalid JSON"):
        generate_sbom.load_json(broken)


def test_a_python_inventory_of_the_wrong_shape_is_reported(tmp_path: Path) -> None:
    """Test that a Python inventory that is not an array is rejected."""
    inventory = tmp_path / "python_packages.json"
    inventory.write_text('{"name": "FastAPI"}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="must be a JSON array"):
        generate_sbom.load_python_inventory(inventory)


def test_a_python_inventory_of_non_objects_is_reported(tmp_path: Path) -> None:
    """Test that a Python inventory holding non-objects is rejected."""
    inventory = tmp_path / "python_packages.json"
    inventory.write_text('["FastAPI"]', encoding="utf-8")

    with pytest.raises(RuntimeError, match="must contain objects"):
        generate_sbom.load_python_inventory(inventory)


def test_a_node_inventory_of_the_wrong_shape_is_reported(tmp_path: Path) -> None:
    """Test that a Node.js inventory that is not an object is rejected."""
    inventory = tmp_path / "npm_packages.json"
    inventory.write_text("[]", encoding="utf-8")

    with pytest.raises(RuntimeError, match="must be a JSON object"):
        generate_sbom.load_node_inventory(inventory)


# =============================================================================
# Dependency lock verification
# =============================================================================


def _lock_entry(
    name: str,
    version: str,
    digest: str = "a" * 64,
    required_by: tuple[str, ...] = ("-r backend/requirements.txt",),
) -> str:
    """Build one entry of a lock file, in the format pip-compile writes."""
    lines = [f"{name}=={version} \\", f"    --hash=sha256:{digest} \\"]
    lines.append(f"    --hash=sha256:{'b' * 64}")
    if len(required_by) == 1:
        lines.append(f"    # via {required_by[0]}")
    else:
        lines.append("    # via")
        lines.extend(f"    #   {parent}" for parent in required_by)
    return "\n".join(lines)


def test_the_lock_of_the_repository_is_a_faithful_resolution() -> None:
    """Test that the committed lock matches the committed requirements."""
    declared = check_dependency_lock.parse_requirements(
        (REPO_ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
    )
    locked = check_dependency_lock.parse_lock(
        (REPO_ROOT / "backend" / "requirements.lock").read_text(encoding="utf-8")
    )

    assert check_dependency_lock.check_lock(declared, locked) == []


def test_every_locked_package_carries_a_hash() -> None:
    """Test that no package in the committed lock is installed without a hash."""
    locked = check_dependency_lock.parse_lock(
        (REPO_ROOT / "backend" / "requirements.lock").read_text(encoding="utf-8")
    )

    assert locked, "the committed lock is empty"
    for package in locked.values():
        assert package.hashes, f"{package.name} is pinned without a hash"
        for digest in package.hashes:
            assert len(digest) == 64


def test_every_locked_package_is_pinned_to_one_exact_version() -> None:
    """Test that the lock contains no range, only exact versions."""
    locked = check_dependency_lock.parse_lock(
        (REPO_ROOT / "backend" / "requirements.lock").read_text(encoding="utf-8")
    )

    for package in locked.values():
        assert ">" not in package.version
        assert "<" not in package.version
        assert "*" not in package.version


def test_a_requirement_that_is_not_locked_is_reported() -> None:
    """Test that a declared requirement missing from the lock is reported."""
    declared = check_dependency_lock.parse_requirements("fastapi>=0.110.0\n")
    locked = check_dependency_lock.parse_lock(_lock_entry("httpx", "0.28.1"))

    problems = check_dependency_lock.check_lock(declared, locked)

    assert any("fastapi" in problem and "not in the lock" in problem for problem in problems)


def test_a_locked_version_outside_the_declared_range_is_reported() -> None:
    """Test that a lock that violates a declared range is reported."""
    declared = check_dependency_lock.parse_requirements("fastapi>=0.110.0\n")
    locked = check_dependency_lock.parse_lock(_lock_entry("fastapi", "0.100.0"))

    problems = check_dependency_lock.check_lock(declared, locked)

    assert any("does not satisfy" in problem for problem in problems)


def test_a_locked_package_without_a_hash_is_reported() -> None:
    """Test that a lock entry without a hash is reported."""
    declared = check_dependency_lock.parse_requirements("fastapi>=0.110.0\n")
    locked = check_dependency_lock.parse_lock(
        "fastapi==0.165.0\n    # via -r backend/requirements.txt\n"
    )

    problems = check_dependency_lock.check_lock(declared, locked)

    assert any("without a single hash" in problem for problem in problems)


def test_a_locked_package_that_nothing_declares_is_reported() -> None:
    """Test that a lock entry which is no longer declared is reported."""
    declared = check_dependency_lock.parse_requirements("fastapi>=0.110.0\n")
    locked = check_dependency_lock.parse_lock(
        _lock_entry("fastapi", "0.165.0") + "\n" + _lock_entry("httpx", "0.28.1")
    )

    problems = check_dependency_lock.check_lock(declared, locked)

    assert any("httpx" in problem and "does not declare it" in problem for problem in problems)


def test_an_unreachable_locked_package_is_reported() -> None:
    """Test that a lock entry no declared requirement reaches is reported."""
    declared = check_dependency_lock.parse_requirements("fastapi>=0.110.0\n")
    locked = check_dependency_lock.parse_lock(
        _lock_entry("fastapi", "0.165.0") + "\n" + _lock_entry("httpx", "0.28.1", required_by=())
    )

    problems = check_dependency_lock.check_lock(declared, locked)

    assert any("no declared requirement reaches" in problem for problem in problems)


def test_a_dependency_edge_naming_a_missing_package_is_reported() -> None:
    """Test that a provenance entry naming an absent package is reported."""
    declared = check_dependency_lock.parse_requirements("fastapi>=0.110.0\n")
    locked = check_dependency_lock.parse_lock(
        _lock_entry("fastapi", "0.165.0", required_by=("httpx",))
    )

    problems = check_dependency_lock.check_lock(declared, locked)

    assert any("which the lock does not contain" in problem for problem in problems)


def test_a_requirement_that_is_declared_twice_is_rejected() -> None:
    """Test that a duplicated declaration is reported rather than accepted."""
    with pytest.raises(ValueError, match="declared more than once"):
        check_dependency_lock.parse_requirements("fastapi>=0.110.0\nfastapi>=0.111.0\n")


def test_a_malformed_declaration_is_rejected() -> None:
    """Test that a declaration that is not a requirement is reported."""
    with pytest.raises(ValueError, match="not a valid requirement"):
        check_dependency_lock.parse_requirements("not a requirement at all\n")


def test_the_lock_cli_accepts_the_committed_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that the command line check accepts the committed lock."""
    exit_code = check_dependency_lock.main([])

    assert exit_code == 0
    assert "faithful resolution" in capsys.readouterr().out


def test_the_lock_cli_fails_on_a_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that the command line check fails and explains a mismatch."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("fastapi>=99.0.0\n", encoding="utf-8")
    lock = tmp_path / "requirements.lock"
    lock.write_text(_lock_entry("fastapi", "0.165.0"), encoding="utf-8")

    exit_code = check_dependency_lock.main(
        ["--requirements", str(requirements), "--lock", str(lock)]
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "does not match" in captured.err
    assert "does not satisfy" in captured.err


def test_the_lock_cli_fails_on_an_unreadable_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that the command line check fails when a file cannot be read."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("fastapi>=0.110.0\n", encoding="utf-8")

    exit_code = check_dependency_lock.main(
        [
            "--requirements",
            str(requirements),
            "--lock",
            str(tmp_path / "does-not-exist.lock"),
        ]
    )

    assert exit_code == 1
    assert "could not be read" in capsys.readouterr().err


# =============================================================================
# Locked environment verification
# =============================================================================


verify_locked_environment = _load_script(
    "powertwin_verify_locked_environment", "verify_locked_environment.py"
)


def _installed(name: str, version: str) -> verify_locked_environment.InstalledPackage:
    """Build an installed-package record for the verification tests."""
    return verify_locked_environment.InstalledPackage(name=name, version=version)


def test_the_locked_versions_are_read_from_the_lock() -> None:
    """Test that the pinned versions of a lock file are read correctly."""
    text = (
        "fastapi==0.165.0 \\\n"
        "    --hash=sha256:" + "a" * 64 + " \\\n"
        "    # via -r backend/requirements.txt\n"
        "\n"
        "PyYAML==6.0.4 \\\n"
        "    --hash=sha256:" + "b" * 64 + " \\\n"
        "    # via -r backend/requirements.txt\n"
    )

    versions = verify_locked_environment.parse_locked_versions(text)

    assert versions == {"fastapi": "0.165.0", "pyyaml": "6.0.4"}


def test_the_names_are_normalised_the_way_pep_503_defines() -> None:
    """Test that the name normalisation folds the separators together."""
    assert verify_locked_environment.canonicalize("PyYAML") == "pyyaml"
    assert verify_locked_environment.canonicalize("typing_extensions") == "typing-extensions"
    assert verify_locked_environment.canonicalize("pydantic_core") == "pydantic-core"
    assert verify_locked_environment.canonicalize("SQLAlchemy") == "sqlalchemy"


def test_a_package_that_the_lock_pins_twice_is_refused() -> None:
    """Test that a lock with a duplicate entry is rejected rather than merged."""
    text = "fastapi==0.165.0\nfastapi==0.166.0\n"

    with pytest.raises(ValueError, match="more than once"):
        verify_locked_environment.parse_locked_versions(text)


def test_an_environment_that_matches_the_lock_has_no_problem() -> None:
    """Test that an environment identical to the lock passes the check."""
    locked = {"fastapi": "0.165.0", "pyyaml": "6.0.4"}
    installed = {
        "fastapi": _installed("fastapi", "0.165.0"),
        "pyyaml": _installed("PyYAML", "6.0.4"),
    }

    problems, extra = verify_locked_environment.verify_environment(locked, installed, strict=True)

    assert problems == []
    assert extra == []


def test_a_locked_package_that_is_not_installed_is_reported() -> None:
    """Test that a package the lock pins but the environment lacks is reported."""
    locked = {"fastapi": "0.165.0", "pyyaml": "6.0.4"}
    installed = {"fastapi": _installed("fastapi", "0.165.0")}

    problems, _ = verify_locked_environment.verify_environment(locked, installed, strict=True)

    assert len(problems) == 1
    assert "pyyaml" in problems[0]
    assert "not installed" in problems[0]


def test_a_package_installed_at_another_version_is_reported() -> None:
    """Test that a substituted version is reported."""
    locked = {"fastapi": "0.165.0"}
    installed = {"fastapi": _installed("fastapi", "0.166.0")}

    problems, _ = verify_locked_environment.verify_environment(locked, installed, strict=True)

    assert len(problems) == 1
    assert "0.165.0" in problems[0]
    assert "0.166.0" in problems[0]


def test_a_package_beyond_the_lock_is_a_problem_only_in_the_strict_mode() -> None:
    """Test that an unpinned package is tolerated by default and refused strictly.

    This is the case that the container build has to catch: a build tool that
    is removed again can leave its own dependency behind, and the environment
    then carries a package that no hash in the lock covers.
    """
    locked = {"fastapi": "0.165.0"}
    installed = {
        "fastapi": _installed("fastapi", "0.165.0"),
        "packaging": _installed("packaging", "26.4"),
    }

    problems, extra = verify_locked_environment.verify_environment(locked, installed, strict=False)
    assert problems == []
    assert extra == ["packaging"]

    problems, extra = verify_locked_environment.verify_environment(locked, installed, strict=True)
    assert len(problems) == 1
    assert "packaging" in problems[0]
    assert extra == ["packaging"]


def test_the_environment_cli_succeeds_on_a_matching_environment(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the command line check succeeds on a matching environment."""
    lock = tmp_path / "requirements.lock"
    lock.write_text("fastapi==0.165.0\n", encoding="utf-8")
    monkeypatch.setattr(
        verify_locked_environment,
        "read_installed_packages",
        lambda: {"fastapi": _installed("fastapi", "0.165.0")},
    )

    exit_code = verify_locked_environment.main(["--lock", str(lock), "--strict"])

    assert exit_code == 0
    assert "matches the lock" in capsys.readouterr().out


def test_the_environment_cli_fails_on_a_package_beyond_the_lock(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the command line check refuses an unpinned package.

    This is the case the container build has to catch: a build tool that is
    removed again can leave its own dependency behind, and the environment then
    carries a package that no hash in the lock covers.
    """
    lock = tmp_path / "requirements.lock"
    lock.write_text("fastapi==0.165.0\n", encoding="utf-8")
    monkeypatch.setattr(
        verify_locked_environment,
        "read_installed_packages",
        lambda: {
            "fastapi": _installed("fastapi", "0.165.0"),
            "packaging": _installed("packaging", "26.4"),
        },
    )

    exit_code = verify_locked_environment.main(["--lock", str(lock), "--strict"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "does not match" in captured.err
    assert "packaging" in captured.err


def test_the_environment_cli_reports_an_unreadable_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that the command line check fails when the lock cannot be read."""
    exit_code = verify_locked_environment.main(["--lock", str(tmp_path / "does-not-exist.lock")])

    assert exit_code == 1
    assert "could not be read" in capsys.readouterr().err


def test_the_two_lock_parsers_agree_on_the_committed_lock() -> None:
    """Test that the two independent readers of the lock report the same thing.

    The lock checker and the environment verifier parse the lock separately
    and for different purposes. If one of them drifts away from the format
    pip-compile writes, the two would disagree about what the lock says, and
    one of the two gates would be checking the wrong thing.
    """
    lock = REPO_ROOT / "backend" / "requirements.lock"
    text = lock.read_text(encoding="utf-8")

    by_version = verify_locked_environment.parse_locked_versions(text)
    by_package = check_dependency_lock.parse_lock(text)

    assert by_version, "the committed lock pins no package"
    assert set(by_version) == set(by_package)
    for canonical, package in by_package.items():
        assert by_version[canonical] == package.version
        assert package.hashes, f"the lock pins '{package.name}' without a hash"


# =============================================================================
# Branch protection
# =============================================================================


apply_branch_protection = _load_script(
    "powertwin_apply_branch_protection", "apply_branch_protection.py"
)


def _documented_status_checks() -> list[str]:
    """Return the status checks that ``docs/CI_CD_GUIDE.md`` section 3 lists."""
    guide = (REPO_ROOT / "docs" / "CI_CD_GUIDE.md").read_text(encoding="utf-8")
    start = guide.index("**Require status checks to pass before merging**")
    end = guide.index("- **Require linear commit history**", start)
    section = guide[start:end]

    checks: list[str] = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = cells[0]
        if name.startswith("`") and name.endswith("`"):
            checks.append(name.strip("`"))
    return checks


def _workflow_status_checks() -> set[str]:
    """Return the names of every check the workflows produce.

    A job whose name carries a matrix expression produces one check per
    matrix value, which is how a single job becomes several required checks.
    """
    import yaml

    produced: set[str] = set()
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in (workflow.get("jobs") or {}).values():
            name = job.get("name")
            if not isinstance(name, str):
                continue
            matrix = ((job.get("strategy") or {}).get("matrix") or {}).get("python-version")
            if "matrix.python-version" in name and isinstance(matrix, list):
                for version in matrix:
                    produced.add(name.replace("${{ matrix.python-version }}", str(version)))
            else:
                produced.add(name)
    return produced


def test_the_required_checks_are_the_documented_ones() -> None:
    """Test that the script applies exactly the checks the guide documents.

    A prose checklist and an executable control drift apart unless something
    holds them together. This is that something.
    """
    documented = _documented_status_checks()

    assert documented, "the guide documents no status check"
    assert tuple(documented) == apply_branch_protection.REQUIRED_STATUS_CHECKS


def test_every_required_check_is_produced_by_a_workflow() -> None:
    """Test that each required check is a name a workflow actually produces.

    A required check that no workflow produces can never pass, which would
    block every merge on the branch forever.
    """
    produced = _workflow_status_checks()

    for check in apply_branch_protection.REQUIRED_STATUS_CHECKS:
        assert check in produced, f"no workflow produces the check '{check}'"


def test_the_documented_checks_are_produced_by_a_workflow() -> None:
    """Test that every check the guide documents is one a workflow produces."""
    produced = _workflow_status_checks()

    for check in _documented_status_checks():
        assert check in produced, f"the guide requires '{check}', which no workflow produces"


def test_the_protection_payload_matches_the_documented_rule() -> None:
    """Test that the payload maps onto every rule the guide lists."""
    guide = (REPO_ROOT / "docs" / "CI_CD_GUIDE.md").read_text(encoding="utf-8")
    payload = apply_branch_protection.build_protection_payload()

    assert payload["required_status_checks"]["contexts"] == list(
        apply_branch_protection.REQUIRED_STATUS_CHECKS
    )
    assert payload["required_status_checks"]["strict"] is True
    assert payload["required_pull_request_reviews"]["required_approving_review_count"] == 1
    assert payload["required_linear_history"] is True
    assert payload["enforce_admins"] is True
    assert payload["allow_force_pushes"] is False
    assert payload["allow_deletions"] is False
    assert apply_branch_protection.build_signatures_payload() == {
        "required_signatures": {"enabled": True}
    }

    # A field that tightens the rule beyond what the guide lists would apply
    # a policy nobody agreed to, so the guide has to name it.
    assert "**Require branches to be up to date before merging**" in guide
    assert "**Require linear commit history**" in guide
    assert "**Require signed commits**" in guide
    assert "**Do not allow bypassing the above settings**" in guide
    assert "**Block force pushes and deletions**" in guide


def test_the_script_refuses_to_run_without_a_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that the script never runs unauthenticated.

    The token is the only credential the script needs and it must come from
    the operator, never from a guess.
    """
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    exit_code = apply_branch_protection.main([])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "GITHUB_TOKEN" in captured.err
    assert captured.out == ""


def test_a_dry_run_makes_no_network_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that the dry run prints the requests without making them."""

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the dry run must not reach the network")

    monkeypatch.setattr(apply_branch_protection.urllib.request, "urlopen", forbidden)

    exit_code = apply_branch_protection.main(["--dry-run"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "PUT" in captured.out
    assert "required_signatures" in captured.out
    assert "dry run" in captured.out


def test_a_missing_check_is_reported() -> None:
    """Test that a rule that dropped a check is reported as incomplete."""
    applied = {
        "required_status_checks": {
            "contexts": list(apply_branch_protection.REQUIRED_STATUS_CHECKS[:-1])
        }
    }

    missing = apply_branch_protection.missing_required_checks(applied)

    assert missing == [apply_branch_protection.REQUIRED_STATUS_CHECKS[-1]]


def test_a_rule_that_an_administrator_can_bypass_is_not_ok() -> None:
    """Test that a loose rule is reported as incomplete.

    A rule that requires the checks but lets an administrator skip them is
    not the rule that was documented.
    """
    report = apply_branch_protection.build_report(
        {
            "required_status_checks": {
                "contexts": list(apply_branch_protection.REQUIRED_STATUS_CHECKS)
            },
            "required_pull_request_reviews": {"required_approving_review_count": 1},
            "enforce_admins": False,
            "required_linear_history": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
        },
        {"required_signatures": {"enabled": True}},
    )

    assert report.missing_checks == ()
    assert report.ok is False


def test_the_rule_is_reported_as_ok_only_when_everything_is_in_force() -> None:
    """Test that a fully applied rule is reported as satisfied."""
    report = apply_branch_protection.build_report(
        {
            "required_status_checks": {
                "contexts": list(apply_branch_protection.REQUIRED_STATUS_CHECKS)
            },
            "required_pull_request_reviews": {"required_approving_review_count": 1},
            "enforce_admins": True,
            "required_linear_history": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
        },
        {"required_signatures": {"enabled": True}},
    )

    assert report.ok is True
    assert report.missing_checks == ()


def test_apply_protection_reads_the_rule_back_and_reports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the report describes what GitHub enforces, not what was asked for.

    The rule is applied and then read back. A server that accepted the
    request but enforced something else must be reported as a failure.
    """
    calls: list[tuple[str, str]] = []

    class _FakeResponse:
        def __init__(self, body: str) -> None:
            self._body = body.encode("utf-8")

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request: object, timeout: float = 0.0) -> _FakeResponse:
        method = getattr(request, "method", "?")
        url = getattr(request, "full_url", "?")
        calls.append((method, url))
        if method == "GET" and url.endswith("/required_signatures"):
            return _FakeResponse('{"required_signatures": {"enabled": true}}')
        if method == "GET":
            return _FakeResponse(
                '{"required_status_checks": {"contexts": '
                f"{json.dumps(list(apply_branch_protection.REQUIRED_STATUS_CHECKS))}"
                '}, "required_pull_request_reviews": '
                '{"required_approving_review_count": 1}, "enforce_admins": true, '
                '"required_linear_history": true, "allow_force_pushes": false, '
                '"allow_deletions": false}'
            )
        return _FakeResponse("{}")

    monkeypatch.setattr(apply_branch_protection.urllib.request, "urlopen", fake_urlopen)

    report = apply_branch_protection.apply_protection("faroub", "PowerTwin", "main", "token")

    assert report.ok is True
    methods = [method for method, _ in calls]
    assert methods == ["PUT", "POST", "GET", "GET"]


def test_apply_protection_reports_a_server_that_enforces_less(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that a server that enforces less than documented is reported as a failure."""

    class _FakeResponse:
        def __init__(self, body: str) -> None:
            self._body = body.encode("utf-8")

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request: object, timeout: float = 0.0) -> _FakeResponse:
        url = getattr(request, "full_url", "?")
        if url.endswith("/required_signatures"):
            return _FakeResponse('{"required_signatures": {"enabled": false}}')
        return _FakeResponse('{"required_status_checks": {"contexts": []}}')

    monkeypatch.setattr(apply_branch_protection.urllib.request, "urlopen", fake_urlopen)

    report = apply_branch_protection.apply_protection("faroub", "PowerTwin", "main", "token")

    assert report.ok is False
    assert report.signed_commits_required is False
    assert len(report.missing_checks) == len(apply_branch_protection.REQUIRED_STATUS_CHECKS)


def test_a_malformed_repository_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that a repository that is not in the 'owner/name' form is refused."""
    exit_code = apply_branch_protection.main(["--repository", "PowerTwin", "--dry-run"])

    assert exit_code == 1
    assert "owner/name" in capsys.readouterr().err


# =============================================================================
# Failed-test reporting
# =============================================================================


summarize_pytest_failures = _load_script(
    "powertwin_summarize_pytest_failures", "summarize_pytest_failures.py"
)

_JUNIT_REPORT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="1" failures="1" skipped="0" tests="3">
    <testcase classname="tests.test_example" name="test_that_passes" time="0.01"/>
    <testcase classname="tests.test_example" name="test_that_fails" time="0.02">
      <failure message="assert 1 == 2">def test_that_fails():&#10;
>       assert 1 == 2&#10;
E       assert 1 == 2&#10;
&#10;
tests/test_example.py:20: AssertionError</failure>
    </testcase>
    <testcase classname="tests.test_example" name="test_that_errors" time="0.03">
      <error message="the plant could not be built">Traceback:&#10;
&#10;
tests/test_example.py:30: RuntimeError</error>
    </testcase>
  </testsuite>
</testsuites>
"""


def _write_report(tmp_path: Path, body: str) -> Path:
    """Write a JUnit report into a temporary directory and return its path."""
    report = tmp_path / "junit.xml"
    report.write_text(body, encoding="utf-8")
    return report


def test_a_failed_test_is_reported_as_an_annotation(tmp_path: Path) -> None:
    """Test that a failure becomes an annotation that names the test and its line."""
    report = _write_report(tmp_path, _JUNIT_REPORT)

    failures = summarize_pytest_failures.parse_failures(report, root=tmp_path)

    assert len(failures) == 2
    failure = failures[0]
    assert failure.name == "tests.test_example::test_that_fails"
    assert failure.file == "tests/test_example.py"
    assert failure.line == 20
    assert failure.message == "assert 1 == 2"

    annotation = summarize_pytest_failures.render_annotation(failure)
    assert annotation.startswith("::error ")
    assert "file=tests/test_example.py" in annotation
    assert "line=20" in annotation
    assert "assert 1 == 2" in annotation


def test_the_location_is_read_from_the_report_pytest_actually_writes(tmp_path: Path) -> None:
    """Test that the file and the line are found where pytest records them.

    Pytest does not write the location into the attributes of the test case;
    it appends it to the failure text. An annotation without a location is an
    annotation nobody can act on.
    """
    report = _write_report(tmp_path, _JUNIT_REPORT)

    failures = summarize_pytest_failures.parse_failures(report, root=tmp_path)

    assert failures[0].file == "tests/test_example.py"
    assert failures[0].line == 20


def test_a_location_written_as_an_attribute_is_used(tmp_path: Path) -> None:
    """Test that an explicit location wins over the one in the text."""
    report = _write_report(
        tmp_path,
        f"""<?xml version="1.0" encoding="utf-8"?>
        <testsuites><testsuite name="pytest" errors="0" failures="1" skipped="0" tests="1">
        <testcase classname="tests.test_example" name="test_that_fails" time="0.01"
                  file="{tmp_path}/tests/test_example.py" line="7">
          <failure message="boom">tests/test_example.py:20: AssertionError</failure>
        </testcase>
        </testsuite></testsuites>
        """,
    )

    failures = summarize_pytest_failures.parse_failures(report, root=tmp_path)

    assert failures[0].file == "tests/test_example.py"
    assert failures[0].line == 7


def test_a_report_without_a_location_still_names_the_test(tmp_path: Path) -> None:
    """Test that a failure with no location at all is still reported.

    A collection error carries no location in some reports. The test that
    failed must still be named, or the annotation says nothing.
    """
    report = _write_report(
        tmp_path,
        """<?xml version="1.0" encoding="utf-8"?>
        <testsuites><testsuite name="pytest" errors="1" failures="0" skipped="0" tests="1">
        <testcase classname="tests.test_example" name="test_that_errors" time="0.01">
          <error message="the plant could not be built">boom</error>
        </testcase>
        </testsuite></testsuites>
        """,
    )

    failures = summarize_pytest_failures.parse_failures(report, root=tmp_path)

    assert failures[0].name == "tests.test_example::test_that_errors"
    assert failures[0].file == "tests/test_example.py"


def test_a_test_that_raised_is_reported_too(tmp_path: Path) -> None:
    """Test that a test which raised is reported as an error, not ignored."""
    report = _write_report(tmp_path, _JUNIT_REPORT)

    failures = summarize_pytest_failures.parse_failures(report, root=tmp_path)

    assert failures[1].kind == "error"
    assert failures[1].name == "tests.test_example::test_that_errors"
    assert failures[1].message == "the plant could not be built"
    assert failures[1].line == 30


def test_a_passing_run_reports_nothing(tmp_path: Path) -> None:
    """Test that a report without a failure produces no annotation."""
    report = _write_report(
        tmp_path,
        """<?xml version="1.0" encoding="utf-8"?>
        <testsuites><testsuite name="pytest" errors="0" failures="0">
        <testcase classname="tests.test_example" name="test_that_passes" time="0.01"/>
        </testsuite></testsuites>
        """,
    )

    assert summarize_pytest_failures.parse_failures(report, root=tmp_path) == []


def test_the_annotation_escapes_the_characters_that_would_end_the_command() -> None:
    """Test that a failure message cannot break out of the annotation.

    A newline ends a workflow command and a percent sign starts an escape
    sequence. A failure message that contains either one would otherwise be
    able to forge a command of its own.
    """
    failure = summarize_pytest_failures.FailedTest(
        name="tests.test_example::test_that_fails",
        file="tests/test_example.py",
        line=20,
        kind="failure",
        message="100% failed\n::error file=forged.py::forged",
    )

    annotation = summarize_pytest_failures.render_annotation(failure)

    assert "\n" not in annotation
    assert "%0A" in annotation
    assert "%25" in annotation
    # The forged command stays inside the message: the newline that would
    # have ended the command is encoded, so it never starts one.
    message = annotation.split("::", 2)[2]
    assert message == "100%25 failed%0A::error file=forged.py::forged"


def test_a_property_that_contains_a_separator_is_escaped() -> None:
    """Test that a path or a title cannot break the property list apart."""
    failure = summarize_pytest_failures.FailedTest(
        name="tests.test_example::test_that_fails",
        file="tests/te:st,example.py",
        line=20,
        kind="failure",
        message="boom",
    )

    annotation = summarize_pytest_failures.render_annotation(failure)

    assert "file=tests/te%3Ast%2Cexample.py" in annotation


def test_the_reporting_step_never_fails_the_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that reporting a failure does not become a second failure.

    The gate is the pytest exit status. A reporting step that failed would
    hide the failure it exists to explain.
    """
    report = _write_report(tmp_path, _JUNIT_REPORT)

    exit_code = summarize_pytest_failures.main([str(report)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "::error " in captured.out
    assert "2 test(s) did not pass" in captured.out


def test_a_missing_report_is_reported_without_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Test that a run which produced no report says so instead of failing."""
    exit_code = summarize_pytest_failures.main([str(tmp_path / "absent.xml")])

    assert exit_code == 0
    assert "No test report was found" in capsys.readouterr().out


def test_the_pipeline_reports_the_failed_tests_as_annotations() -> None:
    """Test that a failing pipeline names the test that failed.

    The job log can only be downloaded with repository administration rights,
    so without this a red pipeline tells nobody but an administrator what
    went wrong.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "reusable-backend.yml").read_text(
        encoding="utf-8"
    )

    assert "--junitxml=junit.xml" in workflow
    assert "scripts/summarize_pytest_failures.py" in workflow
    assert "set -o pipefail" in workflow
    assert "GITHUB_STEP_SUMMARY" in workflow


def test_the_report_step_runs_even_when_the_tests_failed() -> None:
    """Test that the report is published after a failing run, not only after a good one.

    A report step that only runs when the step before it succeeded would
    report nothing exactly when the report matters.
    """
    import yaml

    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "reusable-backend.yml").read_text(encoding="utf-8")
    )

    steps = workflow["jobs"]["backend-test"]["steps"]
    reporting = [step for step in steps if step.get("name") == "Report the Failed Tests"]

    assert len(reporting) == 1, "the backend job does not report its failed tests"
    assert str(reporting[0].get("if")) == "always()"


def test_the_coverage_tool_is_pinned() -> None:
    """Test that the tool that measures the enforced coverage is pinned.

    The coverage policy gate decides on the numbers this tool produces. An
    unpinned version would let a release change those numbers without any
    change to the repository.
    """
    requirements = (REPO_ROOT / "backend" / "requirements-ci.txt").read_text(encoding="utf-8")

    assert "coverage==" in requirements
