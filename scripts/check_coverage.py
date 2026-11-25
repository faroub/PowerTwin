"""Enforce the PowerTwin coverage policy in continuous integration.

The coverage floors enforced by CI are defined once, in :data:`DEFAULT_POLICY`.
This module is the single source of truth for that policy: the CI workflow
calls it, the unit tests verify it, and ``docs/CI_CD_GUIDE.md`` documents it.

Why the floors are not the aspirational targets
------------------------------------------------
The domain targets that were originally published in the CI/CD guide (90 % for
the safety-critical domains, 85 % for the controllers and the plugins) are
*roadmap* targets, not the current state of the repository. The measured
coverage of the reference plant at the time of writing is listed next to every
floor in :data:`DEFAULT_POLICY`. The floors sit a couple of percentage points
below the measured value so that the gate catches a genuine regression while
remaining stable when unrelated code changes.

The policy is deliberately *not* aspirational. A gate that cannot be met is
not a gate: it is a red build that everyone learns to ignore.

Safety note
-----------
This script only reads a coverage report that was produced locally by
``pytest-cov``. It never starts the simulation, never opens a socket and never
touches a database. It cannot affect any simulated or physical equipment.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_POLICY",
    "CoveragePolicy",
    "DomainPolicy",
    "Violation",
    "evaluate_coverage",
    "load_report",
    "main",
]


@dataclass(frozen=True)
class DomainPolicy:
    """Coverage floors enforced for one domain of the codebase.

    Attributes:
        name: Human readable domain name used in the report.
        prefixes: Path prefixes that select the files of the domain. A file
            belongs to the domain when its repository-relative path starts
            with one of these prefixes.
        min_line_coverage: Minimum covered-lines percentage.
        min_branch_coverage: Minimum covered-branches percentage.
        measured_line_coverage: Line coverage measured when the floor was set.
            It is reported by the tool so that the gap to the floor is visible.
        measured_branch_coverage: Branch coverage measured when the floor was
            set.
    """

    name: str
    prefixes: tuple[str, ...]
    min_line_coverage: float
    min_branch_coverage: float
    measured_line_coverage: float
    measured_branch_coverage: float


@dataclass(frozen=True)
class CoveragePolicy:
    """The complete set of coverage floors enforced by CI.

    Attributes:
        min_line_coverage: Global minimum covered-lines percentage.
        min_branch_coverage: Global minimum covered-branches percentage.
        domains: The per-domain floors.
    """

    min_line_coverage: float
    min_branch_coverage: float
    domains: tuple[DomainPolicy, ...]


@dataclass(frozen=True)
class Violation:
    """A single coverage floor that was not met.

    Attributes:
        scope: ``"global"`` or the name of the domain that failed.
        metric: ``"lines"`` or ``"branches"``.
        actual: The measured percentage.
        minimum: The required minimum percentage.
        detail: An optional explanation, used for the "no source files"
            case where no percentage exists.
    """

    scope: str
    metric: str
    actual: float | None
    minimum: float
    detail: str = ""


#: The coverage policy enforced by CI.
#:
#: The ``measured_*`` values are the coverage of the repository at the time
#: this policy was written. They are not enforced; they exist so that the
#: report shows how much headroom each floor still has.
DEFAULT_POLICY = CoveragePolicy(
    min_line_coverage=80.0,
    min_branch_coverage=60.0,
    domains=(
        DomainPolicy(
            name="simulation engine",
            prefixes=("backend/app/simulation/",),
            min_line_coverage=75.0,
            min_branch_coverage=53.0,
            measured_line_coverage=77.34,
            measured_branch_coverage=55.28,
        ),
        DomainPolicy(
            name="battery and BMS",
            prefixes=("backend/app/models/battery/",),
            min_line_coverage=88.0,
            min_branch_coverage=72.0,
            measured_line_coverage=90.10,
            measured_branch_coverage=74.44,
        ),
        DomainPolicy(
            name="PCS, BoP and grid models",
            prefixes=(
                "backend/app/models/pcs/",
                "backend/app/models/bop/",
                "backend/app/models/grid/",
            ),
            min_line_coverage=87.0,
            min_branch_coverage=67.0,
            measured_line_coverage=89.01,
            measured_branch_coverage=69.41,
        ),
        DomainPolicy(
            name="equipment controller",
            prefixes=("backend/app/controllers/equipment_controller.py",),
            min_line_coverage=89.0,
            min_branch_coverage=81.0,
            measured_line_coverage=91.06,
            measured_branch_coverage=83.33,
        ),
        DomainPolicy(
            name="PPC and EMS",
            prefixes=(
                "backend/app/controllers/ppc.py",
                "backend/app/controllers/ems.py",
            ),
            min_line_coverage=89.0,
            min_branch_coverage=74.0,
            measured_line_coverage=91.80,
            measured_branch_coverage=76.83,
        ),
        DomainPolicy(
            name="protocol gateway",
            prefixes=("backend/app/communication/",),
            min_line_coverage=75.0,
            min_branch_coverage=63.0,
            measured_line_coverage=77.96,
            measured_branch_coverage=65.38,
        ),
        DomainPolicy(
            name="API and historian",
            prefixes=("backend/app/api/", "backend/app/historian/"),
            min_line_coverage=76.0,
            min_branch_coverage=49.0,
            measured_line_coverage=78.97,
            measured_branch_coverage=51.72,
        ),
        DomainPolicy(
            name="plant topology",
            prefixes=("backend/app/topology/",),
            min_line_coverage=90.0,
            min_branch_coverage=82.0,
            measured_line_coverage=92.91,
            measured_branch_coverage=84.21,
        ),
        DomainPolicy(
            name="equipment plugins",
            prefixes=("plugins/",),
            min_line_coverage=76.0,
            min_branch_coverage=55.0,
            measured_line_coverage=78.53,
            measured_branch_coverage=57.78,
        ),
    ),
)


def _percentage(covered: int, total: int) -> float:
    """Return the covered percentage, or 100.0 when there is nothing to cover."""
    if total <= 0:
        return 100.0
    return covered / total * 100.0


def _matches(path: str, prefixes: tuple[str, ...]) -> bool:
    """Return True when ``path`` belongs to one of the given prefixes."""
    return any(path.startswith(prefix) for prefix in prefixes)


def load_report(path: Path) -> dict[str, Any]:
    """Load a ``pytest-cov`` JSON coverage report.

    Args:
        path: Path of the JSON report.

    Returns:
        The decoded report.

    Raises:
        FileNotFoundError: If the report does not exist.
        ValueError: If the report is not a valid coverage report.
    """
    if not path.is_file():
        msg = f"The coverage report '{path}' does not exist."
        raise FileNotFoundError(msg)

    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        msg = f"The coverage report '{path}' is not valid JSON: {err}"
        raise ValueError(msg) from err

    if not isinstance(report, dict) or "files" not in report or "totals" not in report:
        msg = (
            f"The file '{path}' is not a pytest-cov JSON coverage report "
            "(it has no 'files' and 'totals' sections)."
        )
        raise ValueError(msg)

    return report


def evaluate_coverage(
    report: dict[str, Any], policy: CoveragePolicy = DEFAULT_POLICY
) -> list[Violation]:
    """Evaluate a coverage report against the policy.

    Args:
        report: A decoded ``pytest-cov`` JSON coverage report.
        policy: The policy to enforce.

    Returns:
        The list of violations. An empty list means the policy is satisfied.
    """
    violations: list[Violation] = []
    files = report["files"]
    totals = report["totals"]

    # Global floors.
    global_lines = _percentage(
        int(totals.get("covered_lines", 0)), int(totals.get("num_statements", 0))
    )
    if global_lines < policy.min_line_coverage:
        violations.append(
            Violation(
                scope="global",
                metric="lines",
                actual=global_lines,
                minimum=policy.min_line_coverage,
            )
        )

    global_branches = _percentage(
        int(totals.get("covered_branches", 0)), int(totals.get("num_branches", 0))
    )
    if global_branches < policy.min_branch_coverage:
        violations.append(
            Violation(
                scope="global",
                metric="branches",
                actual=global_branches,
                minimum=policy.min_branch_coverage,
            )
        )

    # Per-domain floors.
    for domain in policy.domains:
        covered_lines = num_statements = covered_branches = num_branches = 0
        matched = 0
        for path, entry in files.items():
            if not _matches(path, domain.prefixes):
                continue
            matched += 1
            summary = entry["summary"]
            covered_lines += int(summary.get("covered_lines", 0))
            num_statements += int(summary.get("num_statements", 0))
            covered_branches += int(summary.get("covered_branches", 0))
            num_branches += int(summary.get("num_branches", 0))

        if matched == 0:
            # A policy scope that no longer matches any source file would
            # silently stop being enforced. That is a policy defect, not a
            # coverage result, so it is reported as a violation.
            violations.append(
                Violation(
                    scope=domain.name,
                    metric="scope",
                    actual=None,
                    minimum=0.0,
                    detail=(
                        "no source file matches this policy scope; the floor is not being enforced"
                    ),
                )
            )
            continue

        domain_lines = _percentage(covered_lines, num_statements)
        if domain_lines < domain.min_line_coverage:
            violations.append(
                Violation(
                    scope=domain.name,
                    metric="lines",
                    actual=domain_lines,
                    minimum=domain.min_line_coverage,
                )
            )

        domain_branch_rate = _percentage(covered_branches, num_branches)
        if domain_branch_rate < domain.min_branch_coverage:
            violations.append(
                Violation(
                    scope=domain.name,
                    metric="branches",
                    actual=domain_branch_rate,
                    minimum=domain.min_branch_coverage,
                )
            )

    return violations


def format_report(report: dict[str, Any], policy: CoveragePolicy = DEFAULT_POLICY) -> str:
    """Return a human readable coverage table."""
    totals = report["totals"]
    lines: list[str] = []
    lines.append(f"{'scope':<28} {'lines':>16} {'branches':>16}  floor")
    lines.append("-" * 76)

    global_lines = _percentage(
        int(totals.get("covered_lines", 0)), int(totals.get("num_statements", 0))
    )
    global_branches = _percentage(
        int(totals.get("covered_branches", 0)), int(totals.get("num_branches", 0))
    )
    lines.append(
        f"{'global':<28} {global_lines:>9.2f}% {global_branches:>9.2f}%   "
        f">= {policy.min_line_coverage:.0f}% / {policy.min_branch_coverage:.0f}%"
    )

    for domain in policy.domains:
        covered_lines = num_statements = covered_branches = num_branches = 0
        matched = 0
        for path, entry in report["files"].items():
            if not _matches(path, domain.prefixes):
                continue
            matched += 1
            summary = entry["summary"]
            covered_lines += int(summary.get("covered_lines", 0))
            num_statements += int(summary.get("num_statements", 0))
            covered_branches += int(summary.get("covered_branches", 0))
            num_branches += int(summary.get("num_branches", 0))

        if matched == 0:
            lines.append(f"{domain.name:<28} {'NO SOURCE FILES':>16} {'-':>16}   -")
            continue

        domain_lines = _percentage(covered_lines, num_statements)
        domain_branches = _percentage(covered_branches, num_branches)
        lines.append(
            f"{domain.name:<28} {domain_lines:>9.2f}% {domain_branches:>9.2f}%   "
            f">= {domain.min_line_coverage:.0f}% / {domain.min_branch_coverage:.0f}%"
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the coverage gate.

    Args:
        argv: Command line arguments. Defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` when the policy is satisfied, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(
        description="Enforce the PowerTwin coverage policy against a pytest-cov JSON report."
    )
    parser.add_argument(
        "report",
        type=Path,
        help="Path of the pytest-cov JSON coverage report (coverage.json).",
    )
    args = parser.parse_args(argv)

    try:
        report = load_report(args.report)
    except (FileNotFoundError, ValueError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print(format_report(report))
    violations = evaluate_coverage(report)
    if not violations:
        print("\nThe coverage policy is satisfied.")
        return 0

    print("\nThe coverage policy is NOT satisfied:", file=sys.stderr)
    for violation in violations:
        if violation.detail:
            print(
                f"  - [{violation.scope}] {violation.detail}",
                file=sys.stderr,
            )
            continue
        if violation.actual is None:
            print(
                f"  - [{violation.scope}] {violation.metric} coverage is unknown",
                file=sys.stderr,
            )
            continue
        print(
            f"  - [{violation.scope}] {violation.metric} coverage "
            f"{violation.actual:.2f}% is below the required {violation.minimum:.2f}%",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
