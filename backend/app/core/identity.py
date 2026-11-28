"""Client identity resolution for the authentication rate limiter.

The rate limiter measures one identity per login attempt: the client identity
of the request combined with the username it attempts. The identity carried
by the request is the peer address by default, and can only be rewritten by
forwarded headers when the application declares its proxies.

How a forwarded chain is read
-----------------------------

``X-Forwarded-For`` is a chain, not an address. Every proxy that forwards a
request appends the address it observed to the end of the chain, so the
**rightmost** entry is the address of the hop closest to the application, and
the **leftmost** entry is the oldest claim in the chain — a claim the client
itself may have written.

The platform therefore never reads the chain from the left. It walks the chain
from the immediate peer towards the client and traverses a hop only while that
hop is a declared trusted proxy. The first hop that is not a declared proxy is
the client; everything to its left was written by that hop or by the client,
and is not used.

The consequence is the one that matters: a client that sends a
``X-Forwarded-For`` of its own cannot name itself. The value it wrote sits to
the left of the address the trusted proxy appended, and the walk stops at that
address.

What a trusted proxy has to do
------------------------------

A deployment that declares a proxy also declares how that proxy writes the
header. The platform relies on three things:

1. **The immediate peer is the declared proxy.** A request that arrives from
   any other peer is never awarded a forwarded address: the peer address stays
   the identity, whatever the headers claim.
2. **The proxy appends the address it observed to the end of the chain.** The
   platform reads the chain from the right, so the observation of the closest
   proxy is the entry that ends the walk.
3. **The proxy does not forward a client-supplied chain unchanged.** A proxy
   that passes the header of the client through has no observation of its own
   to append, and the platform would read the client's claim. A proxy that
   combines the received header lines into one chain and appends its own
   observation to that chain satisfies this.

Every ``X-Forwarded-For`` line of a request is read as one chain, in the order
the lines arrived. ``X-Real-IP`` carries a single address rather than a chain,
so it is read only while no ``X-Forwarded-For`` is present.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request

from backend.app.core.config import settings

#: The header that carries the chain of the proxies a request came through.
FORWARDED_FOR_HEADER = "x-forwarded-for"

#: The header that carries the single address the last hop claims.
REAL_IP_HEADER = "x-real-ip"

#: A network of either family.
Network = ipaddress.IPv4Network | ipaddress.IPv6Network

#: An address of either family.
Address = ipaddress.IPv4Address | ipaddress.IPv6Address


def _parse_address(value: str) -> Address | None:
    """Return the address ``value`` names, or ``None`` when it names none."""
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _parse_proxy_network(proxy: str) -> Network | None:
    """Return the network a declared proxy covers, or ``None`` on failure.

    A CIDR block is taken as it is written. A plain address covers **that
    address alone**: an IPv4 address is a ``/32`` and an IPv6 address is a
    ``/128``. The two are not interchangeable — reading a plain IPv6 address
    as an IPv4-sized block would declare a whole IPv6 prefix as trusted, which
    is a far larger grant than the operator wrote down.
    """
    candidate = proxy.strip()
    if not candidate:
        return None
    if "/" in candidate:
        try:
            return ipaddress.ip_network(candidate, strict=False)
        except ValueError:
            return None
    address = _parse_address(candidate)
    if address is None:
        return None
    # The prefix length of the family: 32 for IPv4, 128 for IPv6.
    return ipaddress.ip_network(f"{address}/{address.max_prefixlen}", strict=False)


def _trusted_networks() -> list[Network]:
    """Return the networks the deployment declares as trusted proxies.

    A declaration that names no network at all — a malformed address, a block
    with an impossible prefix length — is refused rather than guessed at, so a
    typo cannot widen the trust to everything.
    """
    networks: list[Network] = []
    for proxy in settings.TRUSTED_PROXIES:
        network = _parse_proxy_network(proxy)
        if network is not None:
            networks.append(network)
    return networks


def _is_trusted_proxy(address: Address, networks: list[Network]) -> bool:
    """Return whether the address is a declared trusted proxy.

    An address of one family is never a member of a network of the other, so
    an IPv4 declaration never trusts an IPv6 peer and the other way round.
    """
    return any(address in network for network in networks)


def _forwarded_chain(request: Request) -> list[str]:
    """Return the chain the forwarded headers of a request carry.

    ``X-Forwarded-For`` is a comma-separated chain, and every header line of
    it is a part of the same chain: a request may carry the field more than
    once, and the parts are read in the order they arrived. ``X-Real-IP`` is a
    single address claimed by the last hop, so it is read only while the chain
    is absent.
    """
    forwarded = request.headers.getlist(FORWARDED_FOR_HEADER)
    if forwarded:
        chain: list[str] = []
        for value in forwarded:
            chain.extend(address.strip() for address in value.split(",") if address.strip())
        return chain
    real_ip = request.headers.get(REAL_IP_HEADER, "")
    return [real_ip.strip()] if real_ip.strip() else []


def resolve_client_id(request: Request) -> str:
    """Resolve the client identity that the rate limiter throttles on.

    The identity is the peer address of the request, unless the peer is a
    declared trusted proxy. A trusted peer is followed through the forwarded
    chain towards the client, and the walk traverses a hop only while that hop
    is a declared proxy as well. The first hop that is not a declared proxy is
    the client the platform throttles on.

    A peer that is not declared carries no authority: its headers are ignored
    entirely and the peer address remains the identity, so a deployment with no
    ``TRUSTED_PROXIES`` never customizes the identity it watches.

    Returns:
        The client identity to report to the rate limiter and the audit log.
        It is the normalized form of the address, so that two spellings of one
        address are one identity and cannot be used to spread a throttle over
        several buckets.
    """
    peer = request.client.host if request.client else "unknown"

    networks = _trusted_networks()
    if not networks:
        return peer

    peer_address = _parse_address(peer)
    if peer_address is None or not _is_trusted_proxy(peer_address, networks):
        # An undeclared peer cannot rewrite the identity of the request.
        return peer

    for entry in reversed(_forwarded_chain(request)):
        address = _parse_address(entry)
        if address is None:
            # A hop the platform cannot read ends the chain: nothing to its
            # left can be attributed to anybody, so the identity the platform
            # observed itself — the peer — is used.
            return peer
        if _is_trusted_proxy(address, networks):
            # A declared proxy: the chain continues to its left.
            continue
        # The first hop that is not a declared proxy is the client.
        return str(address)

    # Every hop of the chain is a declared proxy, so the chain names no client
    # the platform can attribute. The peer address is used.
    return peer
