"""Verify that the installed environment is the one the dependency lock describes.

``backend/requirements.lock`` pins every runtime dependency to one exact
version and records the SHA-256 hash of every distribution of that version.
The container image and the pipeline install it with ``--require-hashes``, so
pip verifies the artefact of every package it installs.

What pip cannot check is the other direction: whether anything else ended up
in the environment. A build tool that is installed and then removed can leave
its own dependencies behind, and an environment that carries a package nobody
pinned is an environment whose contents are no longer fully determined by the
lock.

This script closes that direction. It compares the distributions that are
actually installed against the packages the lock pins, and reports

* a locked package that is not installed at all,
* a locked package that is installed at a different version, and
* a package that is installed but that the lock does not pin.

In the strict mode, which the container build uses, the installed set has to
be **exactly** the locked set. In the default mode, which the pipeline uses,
the locked packages have to be present at exactly the locked versions, and the
additional packages — the build tooling — are reported but permitted.

The script uses the standard library only. That is deliberate: it has to run
inside the container image, whose virtual environment carries nothing but the
packages of the lock.

Safety note
-----------
This script reads two files and inspects the installed distributions. It
writes nothing, installs nothing and contacts no external service.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import re
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "InstalledPackage",
    "canonicalize",
    "main",
    "parse_locked_versions",
    "read_installed_packages",
    "verify_environment",
]


REPO_ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = REPO_ROOT / "backend" / "requirements.lock"

#: A line that opens a new entry in the lock file.
_ENTRY_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[^\]]*\])?"
    r"==(?P<version>[^\s\\;]+)"
)


@dataclass(frozen=True)
class InstalledPackage:
    """A distribution that is installed in the current environment."""

    name: str
    version: str

    @property
    def canonical_name(self) -> str:
        """The normalised name, as PEP 503 defines it."""
        return canonicalize(self.name)


def canonicalize(name: str) -> str:
    """Normalise a distribution name, as PEP 503 defines it.

    The normalisation lowercases the name and replaces every run of ``-``,
    ``_`` and ``.`` with a single ``-``, so that ``PyYAML``, ``pyyaml`` and
    ``py-yaml`` all name the same distribution.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_locked_versions(text: str) -> dict[str, str]:
    """Read the pinned version of every package in a lock file.

    The returned mapping is keyed by the normalised package name.
    """
    versions: dict[str, str] = {}
    for line in text.splitlines():
        entry = _ENTRY_PATTERN.match(line)
        if entry is None:
            continue
        canonical = canonicalize(entry.group("name"))
        if canonical in versions:
            raise ValueError(f"the lock pins '{entry.group('name')}' more than once")
        versions[canonical] = entry.group("version")
    return versions


def read_installed_packages() -> dict[str, InstalledPackage]:
    """Read the distributions that are installed in the current environment.

    The returned mapping is keyed by the normalised package name. When a
    distribution is installed more than once, the highest version is reported,
    which is the one that would be imported.
    """
    installed: dict[str, InstalledPackage] = {}
    for distribution in importlib.metadata.distributions():
        raw_name = distribution.metadata["Name"]
        if not raw_name:
            continue
        package = InstalledPackage(name=raw_name, version=distribution.version or "")
        existing = installed.get(package.canonical_name)
        if existing is None or package.version > existing.version:
            installed[package.canonical_name] = package
    return installed


def verify_environment(
    locked: dict[str, str],
    installed: dict[str, InstalledPackage],
    *,
    strict: bool,
) -> tuple[list[str], list[str]]:
    """Compare the installed environment with the lock.

    Returns the problems that were found and the extra packages that were
    tolerated. In the strict mode an extra package is a problem rather than a
    tolerated observation.
    """
    problems: list[str] = []

    for canonical, version in sorted(locked.items()):
        package = installed.get(canonical)
        if package is None:
            problems.append(f"the lock pins '{canonical}', which is not installed")
            continue
        if package.version != version:
            problems.append(
                f"the lock pins '{package.name}' at {version}, but {package.version} is installed"
            )

    extra = sorted(set(installed) - set(locked))
    if strict:
        for canonical in extra:
            problems.append(
                f"'{installed[canonical].name}' is installed but the lock does not pin it"
            )

    return problems, extra


def main(argv: list[str]) -> int:
    """Verify the installed environment and report the outcome."""
    parser = argparse.ArgumentParser(
        description="Verify that the installed environment matches the dependency lock."
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=LOCK_FILE,
        help="the lock file the environment is compared against",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="require the installed set to be exactly the locked set",
    )
    args = parser.parse_args(argv)

    try:
        locked = parse_locked_versions(args.lock.read_text())
    except (OSError, ValueError) as exc:
        print(f"the dependency lock could not be read: {exc}", file=sys.stderr)
        return 1

    installed = read_installed_packages()
    problems, extra = verify_environment(locked, installed, strict=args.strict)

    if problems:
        print(
            f"The installed environment does not match {args.lock}.",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    if extra:
        print(f"{len(extra)} package(s) are installed beyond the lock: " + ", ".join(extra))
    print(
        f"The environment matches the lock: {len(locked)} locked packages, "
        f"each installed at exactly the pinned version."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
