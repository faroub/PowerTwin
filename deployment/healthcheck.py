"""Container health probe for the PowerTwin backend image.

The probe is deliberately implemented with the Python standard library alone.
The container image therefore ships no HTTP client of its own, which keeps the
runtime layer free of an extra package and of the vulnerabilities that package
carries.

The script exits with status ``0`` when the probed endpoint answers with a
``2xx`` status code and with a non-zero status otherwise. It never raises:
a failed probe is reported through the exit status, which is what the
container runtime reads.

The probe is read-only. It issues a plain ``GET`` request and sends no
command, setpoint or configuration to the service.

Usage::

    python deployment/healthcheck.py [/health/readiness]
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

DEFAULT_PATH = "/health/readiness"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
TIMEOUT_SECONDS = 4.0


def build_url(path: str, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    """Build the absolute URL of the endpoint to probe."""
    if not path.startswith("/"):
        path = "/" + path
    return f"http://{host}:{port}{path}"


def probe(url: str, timeout: float = TIMEOUT_SECONDS) -> bool:
    """Return ``True`` when the endpoint answers with a ``2xx`` status code.

    A connection error, a timeout or a non-``2xx`` answer all mean the
    container is not healthy. The reason is written to stderr so that the
    container runtime log explains why the probe failed.
    """
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        print(f"healthcheck: {url} returned HTTP {exc.code}", file=sys.stderr)
        return False
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"healthcheck: {url} is unreachable: {exc}", file=sys.stderr)
        return False

    if 200 <= status < 300:
        print(f"healthcheck: {url} returned HTTP {status}")
        return True

    print(f"healthcheck: {url} returned HTTP {status}", file=sys.stderr)
    return False


def main(argv: list[str]) -> int:
    """Run the probe and return the process exit status."""
    path = argv[1] if len(argv) > 1 else DEFAULT_PATH
    return 0 if probe(build_url(path)) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
