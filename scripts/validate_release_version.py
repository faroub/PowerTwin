"""Validate the version of a PowerTwin release.

A release version is used for the tag of a published release, the name of the
release tarball, the tag of the container images and the version recorded in
the software bill of materials. A malformed value would therefore propagate
into every artefact of a release, which is why the value is validated before
anything is built.

The accepted format is a semantic version with a mandatory ``v`` prefix, which
is the format the release workflow triggers on::

    vMAJOR.MINOR.PATCH
    vMAJOR.MINOR.PATCH-PRERELEASE
    vMAJOR.MINOR.PATCH-PRERELEASE+BUILD

``MAJOR``, ``MINOR`` and ``PATCH`` are decimal integers without a leading
zero. The pre-release and build identifiers are dot separated alphanumeric
identifiers, as defined by Semantic Versioning 2.0.0.

Safety note
-----------
This script validates a string. It never builds, publishes or contacts any
external service.
"""

from __future__ import annotations

import argparse
import re
import sys

__all__ = [
    "RELEASE_VERSION_PATTERN",
    "InvalidReleaseVersion",
    "main",
    "validate_release_version",
]


class InvalidReleaseVersion(ValueError):
    """Raised when a release version does not match the accepted format."""

    def __init__(self, raw: str, reason: str) -> None:
        super().__init__(f"Invalid release version '{raw}': {reason}")
        self.raw = raw
        self.reason = reason


#: The accepted release version format.
#:
#: The pre-release and build identifiers are dot separated lists of non-empty
#: alphanumeric identifiers, as defined by Semantic Versioning 2.0.0. An empty
#: identifier, such as the one in ``v1.0.0-rc..1``, is rejected.
RELEASE_VERSION_PATTERN = re.compile(
    r"^v"
    r"(?P<major>0|[1-9][0-9]*)"
    r"\.(?P<minor>0|[1-9][0-9]*)"
    r"\.(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)

_EXAMPLES = "v1.0.0, v1.2.3-rc.1, v2.0.0-beta.2+build.7"


def validate_release_version(raw: str) -> str:
    """Validate a release version and return its normalised form.

    Args:
        raw: The candidate version. Surrounding whitespace is ignored.

    Returns:
        The normalised version, that is the trimmed input.

    Raises:
        InvalidReleaseVersion: If the version does not match the accepted
            format.
    """
    candidate = raw.strip()
    if not candidate:
        raise InvalidReleaseVersion(raw, "the version is empty")

    match = RELEASE_VERSION_PATTERN.match(candidate)
    if match is None:
        raise InvalidReleaseVersion(
            raw,
            "the expected format is vMAJOR.MINOR.PATCH with an optional "
            f"-PRERELEASE and +BUILD suffix, for example {_EXAMPLES}",
        )

    # Semantic Versioning forbids a numeric pre-release identifier with a
    # leading zero, such as the ``01`` of ``v1.0.0-rc.01``.
    prerelease = match.group("prerelease")
    if prerelease is not None:
        for identifier in prerelease.split("."):
            if identifier.isdigit() and len(identifier) > 1 and identifier[0] == "0":
                msg = f"the numeric pre-release identifier '{identifier}' has a leading zero"
                raise InvalidReleaseVersion(raw, msg)

    return candidate


def main(argv: list[str] | None = None) -> int:
    """Validate the version supplied on the command line.

    Args:
        argv: Command line arguments. Defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` when the version is valid, ``1`` otherwise.
    """
    parser = argparse.ArgumentParser(description="Validate a PowerTwin release version.")
    parser.add_argument("version", help=f"The release version, for example {_EXAMPLES}.")
    args = parser.parse_args(argv)

    try:
        version = validate_release_version(args.version)
    except InvalidReleaseVersion as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
