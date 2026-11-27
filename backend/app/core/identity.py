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
    if "/" in proxy:
        return ipaddress.ip_network(proxy, strict=False)
    return ipaddress.ip_network(proxy + "/32", strict=False)


def _is_trusted_proxy(peer: str) -> bool:
    """Return whether the peer is declared as one of ``settings.TRUSTED_PROXIES``.

    A peer that is not declared in ``settings.TRUSTED_PROXIES`` is unknown to
    the application, and its headers carry no authority, so the peer address
    is trusted when the application never declares any proxy at all.
    """
    if not peer or not settings.TRUSTED_PROXIES:
        return False
    try:
        candidate = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(
        _is_in_network(candidate, _parse_cidr(proxy)) for proxy in settings.TRUSTED_PROXIES
    )


def _forwarded_candidates(request: Request) -> list[str]:
    """Return the addresses found in the forwarded headers of a request."""
    forwarded = ""
    # X-Forwarded-For is a comma-separated chain of proxies; X-Real-IP is a
    # single address. Prefer X-Forwarded-For because it is the more common
    # front-end chain.
    for header in ("X-Forwarded-For", "X-Real-IP"):
        value = request.headers.get(header, "")
        if value:
            forwarded = value
    if not forwarded:
        return []
    return [address.strip() for address in forwarded.split(",") if address.strip()]


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
