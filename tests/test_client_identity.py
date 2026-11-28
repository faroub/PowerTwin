"""Tests for the client identity the rate limiter throttles on.

The identity is the peer address of the request, unless the peer is a
declared trusted proxy. A trusted peer is followed through the forwarded
chain towards the client, and the walk traverses a hop only while that hop is
a declared proxy as well. The first hop that is not a declared proxy is the
client.

Three properties are pinned down above all:

* a **plain IPv4 declaration covers one address** (``/32``) and a **plain IPv6
  declaration covers one address** (``/128``) — never an IPv4-sized block of
  IPv6 space;
* the chain is **walked from the peer**, so a value a client wrote at the
  left of the chain is never the identity;
* the headers of a peer that is **not declared** carry no authority at all.

The login path that consumes this resolver stays in
``tests/test_auth_security.py``.
"""

from __future__ import annotations

import pytest
from fastapi import Request

from backend.app.core.config import settings
from backend.app.core.identity import resolve_client_id


def _client_request(
    peer: str,
    headers: dict[str, str] | None = None,
    repeated: dict[str, list[str]] | None = None,
) -> Request:
    """Construct one request whose peer is ``peer`` and whose headers carry ``headers``.

    ``repeated`` adds header lines that carry the same name more than once,
    which is what a request that carries the chain in several lines looks
    like.
    """
    raw: list[tuple[bytes, bytes]] = [
        (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()
    ]
    for name, values in (repeated or {}).items():
        raw.extend((name.lower().encode(), value.encode()) for value in values)
    scope = {
        "type": "http",
        "client": (peer, 0),
        "headers": raw,
    }
    return Request(scope)


def _resolve(
    monkeypatch: pytest.MonkeyPatch,
    peer: str,
    headers: dict[str, str] | None = None,
    trusted: list[str] | None = None,
    repeated: dict[str, list[str]] | None = None,
) -> str:
    """Resolve the identity of one request under a declared set of proxies."""
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", trusted or [])
    return resolve_client_id(_client_request(peer, headers, repeated))


class TestTheDefault:
    """The deployment declares no proxy until an operator declares one."""

    def test_no_proxy_is_declared_by_default(self) -> None:
        assert settings.TRUSTED_PROXIES == []

    def test_the_peer_carries_the_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _resolve(monkeypatch, "10.0.0.1", {"X-Forwarded-For": "8.8.8.8"}) == "10.0.0.1"

    def test_the_peer_carries_the_identity_of_a_real_ip_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _resolve(monkeypatch, "10.0.0.1", {"X-Real-IP": "8.8.8.8"}) == "10.0.0.1"

    def test_a_request_without_a_peer_carries_the_unknown_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scope = {"type": "http", "headers": []}
        monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["10.0.0.1"])

        assert resolve_client_id(Request(scope)) == "unknown"


class TestAnUndeclaredPeer:
    """The headers of a peer that is not declared carry no authority."""

    def test_a_forwarded_address_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "8.8.8.8"},
                trusted=["192.168.1.0/24"],
            )
            == "10.0.0.1"
        )

    def test_a_chain_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "8.8.8.8, 7.7.7.7"},
                trusted=["192.168.1.0/24"],
            )
            == "10.0.0.1"
        )

    def test_a_peer_that_is_not_an_address_can_never_be_declared(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A unix socket or a name in the peer field is not an address, so no
        # declaration can name it.
        assert (
            _resolve(
                monkeypatch,
                "testclient",
                {"X-Forwarded-For": "8.8.8.8"},
                trusted=["10.0.0.1"],
            )
            == "testclient"
        )

    def test_a_malformed_declaration_declares_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A declaration that names no network at all trusts nothing: it is
        # refused rather than guessed at.
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "8.8.8.8"},
                trusted=["not-an-ip"],
            )
            == "10.0.0.1"
        )

    def test_a_declaration_with_an_impossible_prefix_declares_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "8.8.8.8"},
                trusted=["10.0.0.1/33"],
            )
            == "10.0.0.1"
        )


class TestAPlainIPv4Declaration:
    """A plain IPv4 address declares that one address."""

    def test_the_declared_peer_is_followed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "8.8.8.8"},
                trusted=["10.0.0.1"],
            )
            == "8.8.8.8"
        )

    def test_a_neighbouring_address_is_not_declared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.2",
                {"X-Forwarded-For": "8.8.8.8"},
                trusted=["10.0.0.1"],
            )
            == "10.0.0.2"
        )

    def test_a_real_ip_is_followed_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Real-IP": "8.8.8.8"},
                trusted=["10.0.0.1"],
            )
            == "8.8.8.8"
        )

    def test_a_cidr_block_declares_a_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "8.8.8.8"},
                trusted=["10.0.0.0/8"],
            )
            == "8.8.8.8"
        )


class TestAPlainIPv6Declaration:
    """A plain IPv6 address declares that one address — a ``/128``.

    A plain IPv6 address read as an IPv4-sized block would declare a whole
    IPv6 prefix as trusted, which is a far larger grant than the operator
    wrote down.
    """

    def test_the_declared_peer_is_followed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert (
            _resolve(
                monkeypatch,
                "2001:db8::1",
                {"X-Forwarded-For": "2001:db8::99"},
                trusted=["2001:db8::1"],
            )
            == "2001:db8::99"
        )

    def test_a_neighbouring_address_is_not_declared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The neighbour shares the first 32 bits with the declared address, so
        # a ``/32`` reading of the declaration would have trusted it.
        assert (
            _resolve(
                monkeypatch,
                "2001:db8::99",
                {"X-Forwarded-For": "2001:db8::1"},
                trusted=["2001:db8::1"],
            )
            == "2001:db8::99"
        )

    def test_a_neighbouring_address_is_not_declared_as_a_chain_hop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The same address in the chain: it is not a declared proxy, so the
        # walk stops there instead of walking past it.
        assert (
            _resolve(
                monkeypatch,
                "2001:db8::1",
                {"X-Forwarded-For": "2001:db8::99, 2001:db8::2"},
                trusted=["2001:db8::1"],
            )
            == "2001:db8::2"
        )

    def test_the_loopback_address_is_followed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert (
            _resolve(
                monkeypatch,
                "::1",
                {"X-Forwarded-For": "2001:db8::5"},
                trusted=["::1"],
            )
            == "2001:db8::5"
        )

    def test_an_explicit_128_block_declares_one_address(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (
            _resolve(
                monkeypatch,
                "2001:db8::1",
                {"X-Forwarded-For": "2001:db8::99"},
                trusted=["2001:db8::1/128"],
            )
            == "2001:db8::99"
        )

    def test_an_explicit_prefix_declares_a_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The client is outside the declared block, so it is not a proxy.
        assert (
            _resolve(
                monkeypatch,
                "2001:db8::1",
                {"X-Forwarded-For": "2001:db9::99"},
                trusted=["2001:db8::/32"],
            )
            == "2001:db9::99"
        )

    def test_an_address_inside_the_declared_range_is_a_proxy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Every address of the declared block is a proxy, so a chain hop
        # inside it is traversed rather than taken for the client.
        assert (
            _resolve(
                monkeypatch,
                "2001:db8::1",
                {"X-Forwarded-For": "2001:db8::99, 198.51.100.5"},
                trusted=["2001:db8::/32"],
            )
            == "198.51.100.5"
        )

    def test_an_ipv4_declaration_never_trusts_an_ipv6_peer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (
            _resolve(
                monkeypatch,
                "2001:db8::1",
                {"X-Forwarded-For": "8.8.8.8"},
                trusted=["10.0.0.0/8"],
            )
            == "2001:db8::1"
        )

    def test_an_ipv6_client_behind_an_ipv4_proxy_is_followed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "2001:db8::5"},
                trusted=["10.0.0.1"],
            )
            == "2001:db8::5"
        )


class TestTheChainIsWalkedFromThePeer:
    """The chain is read from the right, never from the left."""

    def test_the_hop_closest_to_the_application_is_the_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # One proxy: the rightmost entry is the address it observed.
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "8.8.8.8"},
                trusted=["10.0.0.1"],
            )
            == "8.8.8.8"
        )

    def test_an_attacker_supplied_leftmost_value_is_not_the_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The client wrote "6.6.6.6" into the header itself; the proxy
        # appended the address it observed. The walk stops at the address the
        # proxy observed.
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "6.6.6.6, 198.51.100.5"},
                trusted=["10.0.0.1"],
            )
            == "198.51.100.5"
        )

    def test_an_attacker_supplied_leftmost_value_is_not_the_client_behind_two_proxies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.9",
                {"X-Forwarded-For": "6.6.6.6, 198.51.100.5, 10.0.0.7"},
                trusted=["10.0.0.9", "10.0.0.7"],
            )
            == "198.51.100.5"
        )

    def test_the_chain_is_walked_through_a_declared_proxy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Two proxies, both declared: the walk traverses the nearer one and
        # stops at the client.
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.9",
                {"X-Forwarded-For": "198.51.100.5, 10.0.0.7"},
                trusted=["10.0.0.9", "10.0.0.7"],
            )
            == "198.51.100.5"
        )

    def test_the_chain_stops_at_a_hop_that_is_not_declared(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The nearer hop is not a declared proxy, so the walk stops there: what
        # it wrote to the left of itself is not attributed to anybody.
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.9",
                {"X-Forwarded-For": "198.51.100.5, 203.0.113.4"},
                trusted=["10.0.0.9"],
            )
            == "203.0.113.4"
        )

    def test_a_chain_of_declared_proxies_names_no_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.9",
                {"X-Forwarded-For": "10.0.0.7"},
                trusted=["10.0.0.9", "10.0.0.7"],
            )
            == "10.0.0.9"
        )

    def test_an_empty_chain_leaves_the_peer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": ""},
                trusted=["10.0.0.1"],
            )
            == "10.0.0.1"
        )

    def test_the_chain_is_read_over_the_real_ip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The chain says more than the single address, so the single address
        # is not read.
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "8.8.8.8", "X-Real-IP": "9.9.9.9"},
                trusted=["10.0.0.1"],
            )
            == "8.8.8.8"
        )

    def test_every_header_line_of_the_chain_is_read_in_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A request may carry the field more than once; the lines are one
        # chain, in the order they arrived.
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                trusted=["10.0.0.1"],
                repeated={"X-Forwarded-For": ["6.6.6.6, 198.51.100.5", "203.0.113.4"]},
            )
            == "203.0.113.4"
        )


class TestAMalformedChain:
    """A chain the platform cannot read names no client."""

    def test_a_malformed_address_is_the_peer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "not-an-ip"},
                trusted=["10.0.0.1"],
            )
            == "10.0.0.1"
        )

    def test_a_malformed_hop_ends_the_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The hop closest to the application cannot be read, so nothing to its
        # left can be attributed to anybody.
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "8.8.8.8, not-an-ip"},
                trusted=["10.0.0.1"],
            )
            == "10.0.0.1"
        )

    def test_a_malformed_hop_in_the_middle_ends_the_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.9",
                {"X-Forwarded-For": "198.51.100.5, not-an-ip, 10.0.0.7"},
                trusted=["10.0.0.9", "10.0.0.7"],
            )
            == "10.0.0.9"
        )

    def test_a_malformed_real_ip_is_the_peer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Real-IP": "not-an-ip"},
                trusted=["10.0.0.1"],
            )
            == "10.0.0.1"
        )


class TestTheIdentityIsNormalized:
    """One address is one identity, however it is written."""

    def test_two_spellings_of_one_address_are_one_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (
            _resolve(
                monkeypatch,
                "10.0.0.1",
                {"X-Forwarded-For": "2001:0db8:0000:0000:0000:0000:0000:0001"},
                trusted=["10.0.0.1"],
            )
            == "2001:db8::1"
        )

    def test_the_peer_address_is_returned_as_it_arrived(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The peer address is the platform's own observation and is reported
        # as it arrived.
        assert _resolve(monkeypatch, "10.0.0.1") == "10.0.0.1"
