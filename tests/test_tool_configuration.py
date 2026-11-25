"""Tests that pin the repository's lint tool configuration.

Ruff discovers its configuration **per file**, by walking up the directory
tree from the file that is being linted. ``backend/`` therefore has its own
configuration in ``backend/pyproject.toml``, and every other Python tree
(``scripts/``, ``tests/``, ``plugins/``, ``deployment/``) is covered by the
root ``ruff.toml``.

Two configurations for one repository is a drift risk: they can disagree, and
nothing in the pipeline notices. Audit finding **F-11** recorded exactly that
disagreement — a line length of 100 in ``backend/`` against 88 everywhere
else, and ``E501`` ignored in one tree and active in the other.

The tests below make the two declarations unable to diverge again:

* they must agree on the line length, the target version and the lint rule
  selection,
* ``E501`` must be active in both, because a formatter never reflows prose,
* and the pipeline must lint every Python tree in the repository, so that no
  tree can be left without a declared style.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

ROOT_RUFF_CONFIG = REPO_ROOT / "ruff.toml"
BACKEND_PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"
BACKEND_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-backend.yml"

# The Python trees the repository contains. Every one of them must be covered
# by a lint configuration and by the pipeline invocation that enforces it.
PYTHON_TREES = ("backend", "deployment", "plugins", "scripts", "tests")


def _load_toml(path: Path) -> dict[str, Any]:
    """Read a TOML file into a dictionary."""
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _ruff_settings(document: dict[str, Any]) -> dict[str, Any]:
    """Return the Ruff settings of a configuration document.

    The root file carries the settings at the top level; the backend file
    nests them under ``tool.ruff``. Both are reduced to the same shape here so
    that they can be compared directly.
    """
    if "tool" in document:
        ruff = document["tool"]["ruff"]
    else:
        ruff = document
    return {
        "line-length": ruff["line-length"],
        "target-version": ruff["target-version"],
        "select": list(ruff["lint"]["select"]),
        "ignore": list(ruff["lint"]["ignore"]),
    }


def _pipeline_ruff_targets() -> set[str]:
    """Return the trees each Ruff invocation covers.

    The Ruff invocations are read out of the workflow rather than assumed, so
    that this test follows the pipeline if the workflow changes. The two
    invocations are returned separately: the formatter only checks that the
    files are formatted, while the linter is what enforces the rule set and
    the line length, so a tree that only one of them covers is not covered.
    """
    workflow = yaml.safe_load(BACKEND_WORKFLOW.read_text())

    def _walk(node: Any) -> list[str]:
        if isinstance(node, dict):
            return [str(node.get("run", ""))] + [
                run for value in node.values() for run in _walk(value)
            ]
        if isinstance(node, list):
            return [run for value in node for run in _walk(value)]
        return []

    commands = [command for command in _walk(workflow) if "ruff" in command]
    assert commands, "the workflow no longer runs Ruff"

    covered: dict[str, set[str]] = {"format": set(), "lint": set()}
    for command in commands:
        for kind, pattern in (
            ("format", r"ruff format --check\s+([^\n]+)"),
            ("lint", r"ruff check\s+([^\n]+)"),
        ):
            for match in re.finditer(pattern, command):
                covered[kind].update(match.group(1).split())
    return covered


class TestTheLintConfigurationsAgree:
    """The two Ruff declarations must describe one style."""

    def test_both_configurations_are_present(self) -> None:
        assert ROOT_RUFF_CONFIG.is_file(), "the root Ruff configuration is missing"
        assert BACKEND_PYPROJECT.is_file(), "the backend project configuration is missing"

    def test_the_line_length_is_the_same_in_both_trees(self) -> None:
        """One line length for the whole repository (audit finding F-11)."""
        root = _ruff_settings(_load_toml(ROOT_RUFF_CONFIG))
        backend = _ruff_settings(_load_toml(BACKEND_PYPROJECT))

        assert root["line-length"] == backend["line-length"], (
            f"the root tree is formatted at {root['line-length']} characters and the "
            f"backend tree at {backend['line-length']}; a line that is acceptable in "
            "one tree is rejected in the other"
        )

    def test_the_rule_selection_is_the_same_in_both_trees(self) -> None:
        """The same rules, with the same exceptions, in both trees."""
        root = _ruff_settings(_load_toml(ROOT_RUFF_CONFIG))
        backend = _ruff_settings(_load_toml(BACKEND_PYPROJECT))

        assert root["select"] == backend["select"], (
            "the two trees select different rule sets, so a lint result depends "
            "on which tree a file lives in"
        )
        assert root["ignore"] == backend["ignore"], (
            "the two trees ignore different rules, so a lint result depends on "
            "which tree a file lives in"
        )

    def test_the_target_version_is_the_same_in_both_trees(self) -> None:
        """The same Python version is targeted in both trees."""
        root = _ruff_settings(_load_toml(ROOT_RUFF_CONFIG))
        backend = _ruff_settings(_load_toml(BACKEND_PYPROJECT))

        assert root["target-version"] == backend["target-version"]

    def test_the_long_line_rule_is_active_in_both_trees(self) -> None:
        """E501 is enforced everywhere, because the formatter never reflows prose.

        Ruff's formatter reflows code but not docstrings or comments, so a
        tree that ignores E501 can contain prose lines that no formatter run
        will ever shorten. Enforcing the rule in both trees is what keeps the
        declared line length true of the whole file.
        """
        root = _ruff_settings(_load_toml(ROOT_RUFF_CONFIG))
        backend = _ruff_settings(_load_toml(BACKEND_PYPROJECT))

        assert "E501" not in root["ignore"], (
            "the root tree ignores E501, so its declared line length is not "
            "enforced on the prose the formatter cannot reflow"
        )
        assert "E501" not in backend["ignore"], (
            "the backend tree ignores E501, so its declared line length is not "
            "enforced on the prose the formatter cannot reflow"
        )
        assert "E" in root["select"] and "E" in backend["select"], (
            "the pycodestyle rules must be selected for E501 to have any effect"
        )


class TestEveryPythonTreeIsCovered:
    """No tree may be left without a declared style or an enforced gate."""

    @pytest.mark.parametrize("tree", PYTHON_TREES)
    def test_the_tree_exists_and_holds_python_files(self, tree: str) -> None:
        assert (REPO_ROOT / tree).is_dir(), f"the '{tree}' tree is missing"
        assert list((REPO_ROOT / tree).rglob("*.py")), f"the '{tree}' tree holds no Python file"

    def test_no_python_tree_is_outside_the_declared_set(self) -> None:
        """A new top-level Python tree must be added to the declared set.

        A tree that is not declared here is a tree whose line length and rule
        set are not pinned by anything, which is the condition F-11 recorded.
        """
        found = {
            path.relative_to(REPO_ROOT).parts[0]
            for path in REPO_ROOT.rglob("*.py")
            if not any(
                part in {".git", "node_modules", "__pycache__", ".venv", "frontend"}
                for part in path.relative_to(REPO_ROOT).parts
            )
        }
        assert found == set(PYTHON_TREES), (
            f"the Python trees {sorted(found)} do not match the declared set "
            f"{sorted(PYTHON_TREES)}; a tree outside it has no pinned style"
        )

    def test_the_pipeline_lints_every_python_tree(self) -> None:
        """The gate must reach every tree, or the pinning is decorative.

        Both invocations are checked separately. The linter is what enforces
        the rule set and the line length, and the formatter is what proves the
        files are laid out in it; a tree that only one of them covers has its
        style pinned but not enforced.
        """
        covered = _pipeline_ruff_targets()

        for kind in ("format", "lint"):
            for tree in PYTHON_TREES:
                assert tree in covered[kind], (
                    f"the pipeline's {kind} invocation does not reach the '{tree}' "
                    "tree, so its pinned configuration is never enforced there"
                )

    def test_the_pipeline_runs_both_the_formatter_and_the_linter(self) -> None:
        """Formatting and linting are separate gates, and both must run."""
        workflow = yaml.safe_load(BACKEND_WORKFLOW.read_text())

        commands = [
            str(step.get("run", ""))
            for job in workflow.get("jobs", {}).values()
            for step in job.get("steps", [])
        ]
        assert any("ruff format --check" in command for command in commands), (
            "the pipeline no longer checks the formatting"
        )
        assert any("ruff check" in command for command in commands), (
            "the pipeline no longer runs the linter"
        )
