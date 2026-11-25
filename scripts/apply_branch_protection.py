"""Apply the documented branch protection to ``main`` — and prove it took effect.

Why this exists
---------------
Audit finding **F-04** recorded that the required branch-protection rule set
for ``main`` was *documented* in ``docs/CI_CD_GUIDE.md`` section 3 but never
applied: the configuration of a repository is a property of GitHub, not of the
source tree, so it cannot be changed by a commit.

A prose checklist is not a control. It goes stale the moment a job is
renamed, and it cannot be verified. This script turns the checklist into an
executable action:

* the required status checks are declared **once**, in this module,
* the payload is built from that declaration and can be printed without
  touching the network (``--dry-run``),
* after the rule is applied it is **read back** from GitHub and compared
  against the declaration, so the result is a verified fact rather than a
  claim.

The script never invents a rule set of its own. It applies exactly what
``docs/CI_CD_GUIDE.md`` section 3 specifies, and ``tests/test_ci_scripts.py``
fails if the documentation, the code and the workflow job names ever diverge.

Credentials
-----------
The token is read from the ``GITHUB_TOKEN`` environment variable, or given
with ``--token``. The script refuses to run without one, never prompts for
one, never writes one to disk and never prints one. A repository
administrator runs it with a token that carries ``administration`` permission
on the repository.

Safety note
-----------
Applying branch protection to ``main`` makes ``main`` harder to push to: the
pull-request requirement, the required checks, the signed-commit requirement
and the ban on force pushes all take effect immediately. ``--dry-run`` prints
exactly what would be applied without applying it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BranchProtectionError",
    "DEFAULT_API_URL",
    "DEFAULT_BRANCH",
    "DEFAULT_REPOSITORY",
    "REQUIRED_APPROVALS",
    "REQUIRED_STATUS_CHECKS",
    "ProtectionReport",
    "apply_protection",
    "build_protection_payload",
    "build_signatures_payload",
    "main",
    "missing_required_checks",
    "protection_url",
    "required_signatures_url",
]

DEFAULT_REPOSITORY = "faroub/PowerTwin"
DEFAULT_BRANCH = "main"
DEFAULT_API_URL = "https://api.github.com"

#: The status checks that must pass before a commit can land on ``main``.
#: These are the names the workflows produce. ``docs/CI_CD_GUIDE.md`` section 3
#: lists the same names, and ``tests/test_ci_scripts.py`` fails if the
#: documentation, this declaration and the workflow job names ever diverge.
REQUIRED_STATUS_CHECKS: tuple[str, ...] = (
    "Backend Lint & Typecheck",
    "Backend Unit & Integration Tests",
    "Backend Tests (Python 3.13)",
    "Backend Tests (Python 3.14)",
    "Frontend Lint, Test & Build",
    "System Engineering & Physics Validation",
    "Infrastructure & Docker Build Validation",
    "Final CI Summary",
)

#: The number of approving reviews a pull request needs before it can merge.
REQUIRED_APPROVALS = 1


class BranchProtectionError(RuntimeError):
    """Raised when the branch protection cannot be applied or verified."""


@dataclass(frozen=True)
class ProtectionReport:
    """What GitHub reports about the rule that is in force on a branch.

    Attributes:
        required_checks: The status checks the branch requires.
        missing_checks: The required checks the branch does **not** require.
        approving_reviews_required: How many approving reviews a pull request
            needs before it can merge.
        admins_enforced: Whether the rule applies to administrators too.
        linear_history_required: Whether the branch requires a linear history.
        force_pushes_allowed: Whether a force push is still permitted.
        deletions_allowed: Whether the branch can still be deleted.
        signed_commits_required: Whether a commit must carry a signature.
    """

    required_checks: tuple[str, ...]
    missing_checks: tuple[str, ...]
    approving_reviews_required: int
    admins_enforced: bool
    linear_history_required: bool
    force_pushes_allowed: bool
    deletions_allowed: bool
    signed_commits_required: bool

    @property
    def ok(self) -> bool:
        """True when every property the documented rule set demands is in force.

        The rule is only satisfied when nothing is missing and nothing is
        looser than specified: a rule that requires the checks but lets an
        administrator skip them is not the rule that was documented.
        """
        return (
            not self.missing_checks
            and self.approving_reviews_required >= REQUIRED_APPROVALS
            and self.admins_enforced
            and self.linear_history_required
            and not self.force_pushes_allowed
            and not self.deletions_allowed
            and self.signed_commits_required
        )

    def describe(self) -> list[str]:
        """Return one line per property, for the operator to read."""
        return [
            f"Required status checks: {len(self.required_checks)}",
            f"Missing status checks: {', '.join(self.missing_checks) or 'none'}",
            f"Approving reviews required: {self.approving_reviews_required}",
            f"Rule enforced for administrators: {self.admins_enforced}",
            f"Linear history required: {self.linear_history_required}",
            f"Force pushes allowed: {self.force_pushes_allowed}",
            f"Branch deletion allowed: {self.deletions_allowed}",
            f"Signed commits required: {self.signed_commits_required}",
        ]


def protection_url(owner: str, repo: str, branch: str, api_url: str = DEFAULT_API_URL) -> str:
    """Return the URL of the branch-protection resource."""
    return f"{api_url.rstrip('/')}/repos/{owner}/{repo}/branches/{branch}/protection"


def required_signatures_url(
    owner: str, repo: str, branch: str, api_url: str = DEFAULT_API_URL
) -> str:
    """Return the URL of the required-signatures resource."""
    base = f"{api_url.rstrip('/')}/repos/{owner}/{repo}/branches/{branch}/protection"
    return f"{base}/required_signatures"


def build_protection_payload(
    *,
    required_checks: Sequence[str] = REQUIRED_STATUS_CHECKS,
    approving_reviews: int = REQUIRED_APPROVALS,
) -> dict[str, Any]:
    """Build the body of the branch-protection request.

    Every field maps onto a line of ``docs/CI_CD_GUIDE.md`` section 3:

    ==============================  ==========================================
    Documented rule                 Field
    ==============================  ==========================================
    Require a pull request          ``required_pull_request_reviews``
    At least one approval           ``required_approving_review_count``
    Require the listed status       ``required_status_checks.contexts``
    checks to pass
    Require branches to be up to    ``required_status_checks.strict``
    date before merging
    Require linear commit history   ``required_linear_history``
    Require signed commits          applied separately, see
                                   :func:`build_signatures_payload`
    No bypassing by administrators   ``enforce_admins``
    Block force pushes              ``allow_force_pushes``
    Block deletions                 ``allow_deletions``
    ==============================  ==========================================

    Args:
        required_checks: The status checks the branch must require.
        approving_reviews: How many approving reviews a pull request needs.

    Returns:
        The request body.
    """
    return {
        "required_status_checks": {
            # `strict` requires the branch to be up to date with `main`
            # before it merges, so a commit that was green against an older
            # base cannot land after the base moved.
            "strict": True,
            "contexts": list(required_checks),
        },
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False,
            "required_approving_review_count": approving_reviews,
        },
        # No push restriction: the protection is about what has to pass, not
        # about who may push at all.
        "restrictions": None,
        "required_linear_history": True,
        "required_conversation_resolution": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "lock_branch": False,
        "allow_fork_syncing": True,
    }


def build_signatures_payload() -> dict[str, Any]:
    """Build the body of the required-signatures request."""
    return {"required_signatures": {"enabled": True}}


def missing_required_checks(applied: dict[str, Any]) -> list[str]:
    """Return the required checks that the applied rule does not require.

    GitHub returns the required checks in two shapes: the legacy ``contexts``
    list and the newer ``checks`` array. Both are read, so the comparison does
    not depend on which one the server happens to fill in.

    Args:
        applied: The branch-protection resource as GitHub reports it.

    Returns:
        The names of the required checks that are absent, in declaration
        order.
    """
    status_checks = applied.get("required_status_checks") or {}
    present = {str(context) for context in status_checks.get("contexts") or []}
    for check in status_checks.get("checks") or []:
        if isinstance(check, dict) and isinstance(check.get("context"), str):
            present.add(check["context"])
    return [name for name in REQUIRED_STATUS_CHECKS if name not in present]


def _request(
    method: str,
    url: str,
    token: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Perform one authenticated GitHub API request.

    Args:
        method: The HTTP method.
        url: The absolute URL.
        token: The API token. It is sent in the ``Authorization`` header and
            is never logged or printed.
        payload: The request body, if any.
        timeout: The socket timeout in seconds.

    Returns:
        The decoded response body, or an empty mapping for an empty response.

    Raises:
        BranchProtectionError: If the request fails or the response is not
            JSON.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)  # noqa: S310 - fixed API host
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace").strip()
        msg = f"{method} {url} failed with HTTP {err.code}: {detail}"
        raise BranchProtectionError(msg) from err
    except urllib.error.URLError as err:
        msg = f"{method} {url} could not reach GitHub: {err.reason}"
        raise BranchProtectionError(msg) from err

    if not body:
        return {}
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as err:
        msg = f"{method} {url} returned a response that is not JSON."
        raise BranchProtectionError(msg) from err
    if not isinstance(decoded, dict):
        msg = f"{method} {url} returned a JSON value that is not an object."
        raise BranchProtectionError(msg)
    return decoded


def _read_protection(
    owner: str, repo: str, branch: str, token: str, *, api_url: str, timeout: float
) -> dict[str, Any]:
    """Read the branch-protection resource back from GitHub."""
    return _request(
        "GET",
        protection_url(owner, repo, branch, api_url),
        token,
        timeout=timeout,
    )


def _read_signatures(
    owner: str, repo: str, branch: str, token: str, *, api_url: str, timeout: float
) -> dict[str, Any]:
    """Read the required-signatures resource back from GitHub."""
    return _request(
        "GET",
        required_signatures_url(owner, repo, branch, api_url),
        token,
        timeout=timeout,
    )


def build_report(applied: dict[str, Any], signatures: dict[str, Any]) -> ProtectionReport:
    """Compare what GitHub reports with what the documented rule set demands.

    Args:
        applied: The branch-protection resource as GitHub reports it.
        signatures: The required-signatures resource as GitHub reports it.

    Returns:
        The report.
    """
    status_checks = applied.get("required_status_checks") or {}
    contexts = {str(context) for context in status_checks.get("contexts") or []}
    for check in status_checks.get("checks") or []:
        if isinstance(check, dict) and isinstance(check.get("context"), str):
            contexts.add(check["context"])

    reviews = applied.get("required_pull_request_reviews") or {}
    approving = reviews.get("required_approving_review_count")
    approvals = approving if isinstance(approving, int) else 0

    return ProtectionReport(
        required_checks=tuple(sorted(contexts)),
        missing_checks=tuple(missing_required_checks(applied)),
        approving_reviews_required=approvals,
        admins_enforced=bool(applied.get("enforce_admins")),
        linear_history_required=bool(applied.get("required_linear_history")),
        force_pushes_allowed=bool(applied.get("allow_force_pushes")),
        deletions_allowed=bool(applied.get("allow_deletions")),
        signed_commits_required=bool((signatures.get("required_signatures") or {}).get("enabled")),
    )


def apply_protection(
    owner: str,
    repo: str,
    branch: str,
    token: str,
    *,
    api_url: str = DEFAULT_API_URL,
    timeout: float = 30.0,
) -> ProtectionReport:
    """Apply the documented rule set to a branch and verify the result.

    The rule is applied, then read back, so that the report describes what
    GitHub actually enforces rather than what was asked for.

    Args:
        owner: The repository owner.
        repo: The repository name.
        branch: The branch to protect.
        token: The API token.
        api_url: The base URL of the API.
        timeout: The socket timeout in seconds.

    Returns:
        The report of what is in force.

    Raises:
        BranchProtectionError: If a request fails.
    """
    _request(
        "PUT",
        protection_url(owner, repo, branch, api_url),
        token,
        payload=build_protection_payload(),
        timeout=timeout,
    )
    _request(
        "POST",
        required_signatures_url(owner, repo, branch, api_url),
        token,
        payload=build_signatures_payload(),
        timeout=timeout,
    )

    applied = _read_protection(owner, repo, branch, token, api_url=api_url, timeout=timeout)
    signatures = _read_signatures(owner, repo, branch, token, api_url=api_url, timeout=timeout)
    return build_report(applied, signatures)


def _parse_repository(value: str) -> tuple[str, str]:
    """Split an ``owner/repo`` string into its two parts."""
    parts = value.split("/")
    if len(parts) != 2 or not all(parts):
        msg = f"The repository '{value}' is not in the 'owner/name' form."
        raise BranchProtectionError(msg)
    return parts[0], parts[1]


def main(argv: list[str] | None = None) -> int:
    """Run the branch-protection application.

    Args:
        argv: Command line arguments. Defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` when the rule is in force and verified, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Apply the branch-protection rule set that docs/CI_CD_GUIDE.md section 3 "
            "specifies, and read it back to prove that it is in force."
        )
    )
    parser.add_argument(
        "--repository",
        default=DEFAULT_REPOSITORY,
        help=f"The repository, as 'owner/name' (default: {DEFAULT_REPOSITORY}).",
    )
    parser.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help=f"The branch to protect (default: {DEFAULT_BRANCH}).",
    )
    parser.add_argument(
        "--token",
        default=None,
        help=(
            "The API token. Defaults to the GITHUB_TOKEN environment variable. "
            "The token is never printed and never written to disk."
        ),
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"The base URL of the GitHub API (default: {DEFAULT_API_URL}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the requests that would be made and make no network call.",
    )
    args = parser.parse_args(argv)

    try:
        owner, repo = _parse_repository(args.repository)
    except BranchProtectionError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    payload = build_protection_payload()
    signatures_payload = build_signatures_payload()

    if args.dry_run:
        print(f"PUT {protection_url(owner, repo, args.branch, args.api_url)}")
        print(json.dumps(payload, indent=2, sort_keys=True))
        print(f"POST {required_signatures_url(owner, repo, args.branch, args.api_url)}")
        print(json.dumps(signatures_payload, indent=2, sort_keys=True))
        print(
            f"The rule requires {len(REQUIRED_STATUS_CHECKS)} status checks, "
            f"{REQUIRED_APPROVALS} approving review and signed commits."
        )
        print("No request was made: this was a dry run.")
        return 0

    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print(
            "ERROR: no API token. Set GITHUB_TOKEN, or pass --token. The token must "
            "carry 'administration' permission on the repository.",
            file=sys.stderr,
        )
        return 1

    try:
        report = apply_protection(
            owner,
            repo,
            args.branch,
            token,
            api_url=args.api_url,
        )
    except BranchProtectionError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    for line in report.describe():
        print(line)

    if not report.ok:
        print(
            "ERROR: the rule is not in force as documented. The report above says what is missing.",
            file=sys.stderr,
        )
        return 1

    print(f"The branch protection of {owner}/{repo}@{args.branch} is in force.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
