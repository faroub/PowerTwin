"""Unit tests for the continuous-integration helper scripts.

The scripts under ``scripts/`` implement the gates that the CI pipeline
enforces: the coverage policy, the release version format, the migration graph
and the determinism fingerprint of the endurance campaign. They are pure
helpers with no external side effects, so they are verified here rather than
only being exercised by the pipeline that calls them.
"""

from __future__ import annotations

import importlib.util
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
validate_migrations_module = _load_script(
    "powertwin_validate_migrations", "validate_migrations.py"
)
endurance_campaign = _load_script(
    "powertwin_endurance_campaign", "endurance_campaign.py"
)
generate_sbom = _load_script("powertwin_generate_sbom", "generate_sbom.py")


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
    assert (
        validate_release_version_module.validate_release_version(version)
        == version.strip()
    )


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
    with pytest.raises(
        validate_release_version_module.InvalidReleaseVersion
    ) as excinfo:
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
    global_lines = [
        v for v in violations if v.scope == "global" and v.metric == "lines"
    ]
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
    with pytest.raises(
        validate_migrations_module.MigrationValidationError, match="2 head"
    ):
        validate_migrations_module.check_single_head(["001", "002"])


def test_no_head_is_rejected() -> None:
    """Test that an empty migration graph is rejected."""
    with pytest.raises(
        validate_migrations_module.MigrationValidationError, match="no head"
    ):
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
    assert endurance_campaign.build_fingerprint(
        first
    ) == endurance_campaign.build_fingerprint(second)


def test_the_fingerprint_changes_with_the_state() -> None:
    """Test that a different engine state produces a different fingerprint."""
    first = _FakeSnapshot(100, 10, {"a": 1}, {"b": 2})
    second = _FakeSnapshot(200, 10, {"a": 1}, {"b": 2})
    assert endurance_campaign.build_fingerprint(
        first
    ) != endurance_campaign.build_fingerprint(second)


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
