"""Client identity resolution for the authentication rate limiter.

The rate limiter measures one identity per login attempt: the client identity
of the request combined with the username it attempts. The identity carried
by the request is the peer address by default, and can only be rewritten by
forwarded headers when the application declares its proxies.

"""

import ipaddress
from typing import Any

from fastapi import Request

from backend.app.core.config import settings


def _is_in_network(candidate: Any, network: ipaddress.IPv4Network | ipaddress.IPv6Network) -> bool:
    """Return whether the ``candidate`` address is a member of ``network``."""
    try:
        return ipaddress.ip_address(candidate) in network
    except ValueError:
        return False


def _parse_cidr(proxy: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """Parse a CIDR block or plain address into a network; ``None`` on failure."""
    proxy = proxy.strip()
    if not proxy:
        return None
    try:
        if "/" in proxy:
            return ipaddress.ip_network(proxy, strict=False)
        return ipaddress.ip_network(proxy + "/32", strict=False)
    except ValueError:
        return None


def _is_trusted_proxy(peer: str) -> bool:
    """Return whether the peer is declared as one of ``settings.TRUSTED_PROXIES``.

    A peer that is not declared in ``settings.TRUSTED_PROXIES`` is unknown to
    the application, and its headers carry no authority. An unidentified or
    non-IP peer is never awarded headers, so the peer address stays the
    identity the deployment actually sees.
    """
    if not peer or not settings.TRUSTED_PROXIES:
        return False
    try:
        candidate = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for proxy in settings.TRUSTED_PROXIES:
        network = _parse_cidr(proxy)
        if network is not None and _is_in_network(candidate, network):
            return True
    return False


def _forwarded_candidates(request: Request) -> list[str]:
    """Return the addresses found in the forwarded headers of a request.

    ``X-Forwarded-For`` is a comma-separated chain of proxies, and the first
    address of that chain is the client the chain started from. ``X-Real-IP`` is
    a single address claimed by the last hop, so it is awarded only while the
    chain is absent, never while the chain claims a broader path.
    """
    for header in ("X-Forwarded-For", "X-Real-IP"):
        value = request.headers.get(header, "")
        if not value:
            continue
        return [address.strip() for address in value.split(",") if address.strip()]
    return []


def resolve_client_id(request: Request) -> str:
    """Resolve the client identity that the rate limiter throttles on.

    The identity is the request peer address unless the peer is a trusted
    proxy, in which case the address it claims in the forwarded headers is
    trusted. A forwarded header chain from an unknown peer is ignored, so a
    deployment with no ``TRUSTED_PROXIES`` never customizes the identity it
    watches.

    Returns:
        The client identity to report to the rate limiter and the audit log.
    """
    peer = request.client.host if request.client else "unknown"

    if not _is_trusted_proxy(peer):
        return peer

    candidates = _forwarded_candidates(request)
    for candidate in candidates:
        # Only a well-formed address is accepted: a pollutant could not
        # otherwise write a path through the trusted boundary.
        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            continue

    return peer
