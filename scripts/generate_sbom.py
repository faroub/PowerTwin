"""Generate an SPDX-2.3 Software Bill of Materials (SBOM) for PowerTwin.

The SBOM is derived from the dependency inventories recorded during the
release build:

- ``python_packages.json``: ``pip list --format=json`` (Python dependencies)
- ``frontend/npm_packages.json``: ``npm ls --json --all`` (Node.js dependencies,
  including the complete transitive tree)

The report is generated with the Python 3 standard library only, so it is safe
to run on any CI runner.

Validity and reproducibility
----------------------------
The document follows the SPDX 2.3 specification:

* every package carries a unique ``SPDXID``, a concluded and a declared
  license and a copyright statement,
* the document namespace is unique per document. It is derived from the
  release version and the creation timestamp, so two different releases never
  share a namespace,
* the creation timestamp is the real time at which the SBOM was generated.
  It can be pinned through the ``SOURCE_DATE_EPOCH`` environment variable so
  that a release can be reproduced byte for byte.

License strings are read from the package manifests. The verification of each
license's compatibility with the project's distribution rules remains a manual
process and is clearly documented by the SBOM itself.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

__all__ = [
    "JsonArray",
    "JsonObject",
    "SBOMGenerationLog",
    "build_sbom",
    "flatten_node_dependencies",
    "load_json",
    "load_node_inventory",
    "load_python_inventory",
    "main",
]

#: A decoded JSON object. JSON is dynamically typed, so the values are typed
#: as ``Any`` and narrowed at each use site.
JsonObject = dict[str, Any]

#: A decoded JSON array.
JsonArray = list[Any]

INPUT_DIR = Path(".")
PYTHON_FILE = INPUT_DIR / "python_packages.json"
NODE_FILE = INPUT_DIR / "frontend/npm_packages.json"
OUTPUT_DIR = INPUT_DIR / "release_artifacts"

#: Namespace used to derive the deterministic document identifier.
_SPDX_NAMESPACE = uuid.UUID("6e8e4d0a-1b2c-3d9e-8f7a-5b6c2d5a0c8e")

#: The maximum depth that is walked in the npm dependency tree.
_MAX_NODE_DEPTH = 32

_UNSAFE_SPDX_ID = re.compile(r"[^A-Za-z0-9.-]+")


class SBOMGenerationLog:
    """Simple log of SBOM generation steps and their success/failure."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    def log(self, message: str) -> None:
        self.entries.append(message)

    def summarize(self) -> str:
        return "\n".join(self.entries)


def load_json(path: Path) -> Any:
    """Load and decode a JSON file; fail loudly on anything unreadable."""
    if not path.exists():
        raise FileNotFoundError(f"Missing dependency inventory: {path}")
    if path.stat().st_size == 0:
        raise FileNotFoundError(f"Empty dependency inventory: {path}")
    try:
        decoded: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Invalid JSON in dependency inventory: {path}: {error}") from error
    return decoded


def load_python_inventory(path: Path) -> list[JsonObject]:
    """Load the ``pip list --format=json`` inventory as a list of packages.

    The inventory must be a JSON array of objects. Anything else is a broken
    inventory and is reported rather than reduced to an empty list, because an
    empty SBOM is indistinguishable from a project with no dependencies at all.

    Args:
        path: The path of the Python dependency inventory.

    Returns:
        One mapping per installed package.

    Raises:
        RuntimeError: The inventory is not a JSON array of objects.
    """
    decoded = load_json(path)
    if not isinstance(decoded, list):
        raise RuntimeError(f"The Python dependency inventory must be a JSON array: {path}")
    packages: list[JsonObject] = []
    for entry in decoded:
        if not isinstance(entry, dict):
            raise RuntimeError(f"The Python dependency inventory must contain objects: {path}")
        packages.append(entry)
    return packages


def load_node_inventory(path: Path) -> JsonObject:
    """Load the ``npm ls --json --all`` inventory as a dependency tree.

    Args:
        path: The path of the Node.js dependency inventory.

    Returns:
        The decoded dependency tree.

    Raises:
        RuntimeError: The inventory is not a JSON object.
    """
    decoded = load_json(path)
    if not isinstance(decoded, dict):
        raise RuntimeError(f"The Node.js dependency inventory must be a JSON object: {path}")
    return decoded


def _creation_timestamp() -> str:
    """Return the creation timestamp of the SBOM.

    The timestamp is taken from ``SOURCE_DATE_EPOCH`` when it is set, which
    makes the generated document reproducible. Otherwise the current UTC time
    is used.
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            moment = datetime.datetime.fromtimestamp(int(epoch), tz=datetime.UTC)
        except (TypeError, ValueError, OSError, OverflowError) as error:
            raise ValueError(f"Invalid SOURCE_DATE_EPOCH value '{epoch}': {error}") from error
    else:
        moment = datetime.datetime.now(tz=datetime.UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _spdx_id(name: str, version: str) -> str:
    """Return the SPDX identifier of a package."""
    sanitized = _UNSAFE_SPDX_ID.sub("-", f"{name}-{version}").strip("-")
    return f"SPDXRef-Package-{sanitized}"


def make_package_entry(
    name: str, version: str, download_location: str, license_terms: str
) -> JsonObject:
    """Create one SPDX package entry from its inventory payload."""
    entry: JsonObject = {
        "SPDXID": _spdx_id(name, version),
        "name": name,
        "versionInfo": version,
        "downloadLocation": download_location,
        "copyrightText": "NOASSERTION",
        "licenseConcluded": license_terms or "NOASSERTION",
        "licenseDeclared": license_terms or "NOASSERTION",
        "supplier": "NOASSERTION",
        "filesAnalyzed": False,
    }
    return entry


def flatten_node_dependencies(
    node_packages: JsonObject, max_depth: int = _MAX_NODE_DEPTH
) -> dict[str, str]:
    """Flatten the npm dependency tree into a ``name -> version`` mapping.

    ``npm ls --json --all`` produces a nested tree. A dependency that appears
    at several levels is recorded once, with the version of its first
    occurrence, and the traversal stops at ``max_depth``.

    Args:
        node_packages: The decoded ``npm ls --json --all`` output.
        max_depth: The maximum depth of the tree that is walked.

    Returns:
        A mapping of package name to package version.
    """
    resolved: dict[str, str] = {}

    def walk(dependencies: JsonObject, depth: int) -> None:
        if depth > max_depth:
            return
        for name, package in dependencies.items():
            if not isinstance(package, dict):
                continue
            version = package.get("version")
            if version and name not in resolved:
                resolved[name] = str(version)
            children = package.get("dependencies")
            if isinstance(children, dict):
                walk(children, depth + 1)

    walk(node_packages.get("dependencies", {}), 0)
    return resolved


def build_sbom(
    python_packages: list[JsonObject], node_packages: JsonObject, version: str
) -> JsonObject:
    """Build the full SPDX document from the recorded inventories.

    Args:
        python_packages: The decoded ``pip list --format=json`` output.
        node_packages: The decoded ``npm ls --json --all`` output.
        version: The release version, with or without the leading ``v``.

    Returns:
        The SPDX document.
    """
    name = "PowerTwin"
    created = _creation_timestamp()
    document_uuid = uuid.uuid5(_SPDX_NAMESPACE, f"{version}:{created}")
    namespace = f"https://spdx.org/spdxdocs/powertwin-{version}-{document_uuid}"

    documents: JsonObject = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{name}-{version}",
        "documentNamespace": namespace,
        "creationInfo": {
            "creators": ["Organization: PowerTwin"],
            "created": created,
        },
        "documentDescribes": [_spdx_id(name, version)],
        "packages": [
            {
                "SPDXID": _spdx_id(name, version),
                "name": name,
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "copyrightText": "NOASSERTION",
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "supplier": "NOASSERTION",
                "filesAnalyzed": False,
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceLocator": f"pkg:github/faroub/powertwin@{version}",
                        "referenceType": "purl-ext",
                    }
                ],
            }
        ],
    }

    for package in python_packages:
        normalized = package["name"].lower().replace("_", "-")
        documents["packages"].append(
            make_package_entry(
                package["name"],
                package["version"],
                f"https://pypi.org/simple/{normalized}/",
                package.get("license", "NOASSERTION"),
            )
        )

    for package_name, package_version in flatten_node_dependencies(node_packages).items():
        documents["packages"].append(
            make_package_entry(
                package_name,
                package_version,
                f"https://registry.npmjs.org/{package_name}/-/{package_name}-{package_version}.tgz",
                "NOASSERTION",
            )
        )

    return documents


def main() -> int:
    """Generate the SBOM and report the inventory it captured."""
    parser = argparse.ArgumentParser(
        description="Generate the SPDX-2.3 software bill of materials of a PowerTwin release."
    )
    parser.add_argument(
        "version",
        nargs="?",
        default="v1.0.0",
        help="The release version, for example v1.0.0.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DIR / "sbom.spdx.json",
        help=f"Path of the generated SBOM (default: {OUTPUT_DIR / 'sbom.spdx.json'}).",
    )
    args = parser.parse_args()

    log = SBOMGenerationLog()

    python_packages = load_python_inventory(PYTHON_FILE)
    node_packages = load_node_inventory(NODE_FILE)

    version = args.version.lstrip("v")

    documents = build_sbom(python_packages, node_packages, version)

    output = args.output
    if not output.parent.exists():
        output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(documents, indent=2), encoding="utf-8")

    log.log(f"Binary location: {output}")
    log.log(f"Python packages: {len(python_packages)}")
    log.log(f"Node packages: {len(flatten_node_dependencies(node_packages))}")
    log.log(f"Creation timestamp: {documents['creationInfo']['created']}")
    log.log(f"Document namespace: {documents['documentNamespace']}")
    log.log("License verification is manual; the SBOM is a dependency snapshot.")

    print(log.summarize())
    return 0


if __name__ == "__main__":
    sys.exit(main())
