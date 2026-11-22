"""Generate an SPDX-2.3 Software Bill of Materials (SBOM) for PowerTwin.

The SBOM is derived from the dependency inventories recorded in this release build:

- `python_packages.json` : `pip list --format=json` (Python dependencies)
- `frontend/npm_packages.json`: `npm ls --json --all --depth=0` (Node.js dependencies)

The report is generated with Python 3 stdlib only, so it is safe to run on any
CI runner. License strings are read from the package manifests; verification of
each license's compatibility with the project's distribution rules is a manual
process and is clearly documented by the SBOM itself.

"""

from __future__ import annotations

import json
import sys
from pathlib import Path

INPUT_DIR = Path(".")
PYTHON_FILE = INPUT_DIR / "python_packages.json"
NODE_FILE = INPUT_DIR / "frontend/npm_packages.json"
OUTPUT_DIR = INPUT_DIR / "release_artifacts"


class SBOMGenerationLog:
    """Simple log of SBOM generation steps and their success/failure."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    def log(self, message: str) -> None:
        self.entries.append(message)

    def summarize(self) -> str:
        return "\n".join(self.entries)


def load_json(path: Path, log: SBOMGenerationLog) -> dict | list[str]:
    """Load a JSON file; fail loudly on anything unreadable."""
    if not path.exists():
        raise FileNotFoundError(f"Missing dependency inventory: {path}")
    if path.stat().st_size == 0:
        raise FileNotFoundError(f"Empty dependency inventory: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Invalid JSON in dependency inventory: {path}: {error}"
        ) from error


def make_package_entry(
    name: str, version: str, download_location: str, license_terms: str
) -> dict:
    """Create one SPDX package entry from its inventory payload."""
    return {
        "name": name,
        "versionInfo": version,
        "downloadLocation": download_location,
        "copyrightText": "NOASSERTION",
        "licenseConcluded": license_terms,
    }


def build_sbom(python_packages: list[dict], node_packages: dict, version: str) -> dict:
    """Build the full SPDX document from the recorded inventories."""
    name = "PowerTwin"
    namespace = "urn:uuid:6e8e4d0a-1b2c-3d9e-8f7a-5b6c2d5a0c8e"

    documents: dict = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "name": f"{name}-{version}",
        "documentNamespace": namespace,
        "creationInfo": {
            "creators": ["Organization: PowerTwin"],
            "created": "2026-11-22T00:00:00Z",
        },
        "packages": [
            {
                "name": name,
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "copyrightText": "NOASSERTION",
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

    for package_name, package in node_packages.get("dependencies", {}).items():
        documents["packages"].append(
            make_package_entry(
                package_name,
                package["version"],
                f"https://registry.npmjs.org/{package_name}",
                package.get("license", "NOASSERTION"),
            )
        )

    return documents


def main() -> int:
    """Generate the SBOM and report the inventory it captured."""
    log = SBOMGenerationLog()

    python_packages = load_json(PYTHON_FILE, log)
    node_packages = load_json(NODE_FILE, log)

    version = sys.argv[1] if len(sys.argv) > 1 else "v1.0.0"
    version = version.lstrip("v")

    documents = build_sbom(python_packages, node_packages, version)

    output = OUTPUT_DIR / "sbom.spdx.json"
    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(documents, indent=2), encoding="utf-8")

    log.log(f"Binary location: {output}")
    log.log(f"Python packages: {len(python_packages)}")
    log.log(f"Node packages: {len(node_packages.get('dependencies', {}))}")
    log.log("License verification is manual; the SBOM is a dependency snapshot.")

    print(log.summarize())
    return 0


if __name__ == "__main__":
    sys.exit(main())
