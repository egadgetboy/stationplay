"""Where a request comes from (networks.py, 1.36.0): home addresses by an
explicit list, forwarding headers, the Host a request asks for, and the
verdict the Gate starts from. The rule (the owner, October 13: "we are also
focusing on how security works if we accidentally leave doors open"): when
tapiOca can't be sure, a request is from the internet."""

from __future__ import annotations

import ipaddress

import pytest

from app import networks as nw


@pytest.mark.parametrize(
    ("text", "home"),
    [
        ("10.1.2.3", True), ("172.16.0.1", True), ("172.31.255.254", True),
        ("192.168.50.2", True), ("127.0.0.1", True), ("169.254.1.1", True),
        ("100.64.0.1", True), ("100.127.255.254", True), ("::1", True),
        ("fd12:3456::1", True), ("fe80::1", True),
        ("172.32.0.1", False), ("192.169.0.1", False), ("100.128.0.1", False),
        ("8.8.8.8", False), ("203.0.113.9", False), ("2001:db8::9", False),
        ("2606:4700::1", False), ("0.0.0.0", False), ("224.0.0.1", False),
        ("240.0.0.1", False), ("64:ff9b::808:808", False), ("2002:c0a8:101::1", False),
        # (Teredo: private by Python 3.11's is_private, never home here.)
        ("2001::1", False),
    ],
)  # fmt: skip
def test_home_is_an_explicit_list(text, home):
    """Never ipaddress.is_private, which differs between Python 3.11 (here)
    and 3.13 (the image)."""
    assert nw.is_home(ipaddress.ip_address(text)) is home


def test_reading_an_address():
    assert nw.parse_ip(" 192.168.1.5 ") == ipaddress.ip_address("192.168.1.5")
    # (An IPv4 address in IPv6 form is itself.)
    assert nw.parse_ip("::ffff:203.0.113.9") == ipaddress.ip_address("203.0.113.9")
    assert nw.parse_ip("::FFFF:192.168.1.5") == ipaddress.ip_address("192.168.1.5")
    for bad in ("", "  ", "fe80::1%eth0", "[::1]", "192.168.1.5:80", "unknown", "x" * 46,
                "192.168.1", "1.2.3.4.5"):  # fmt: skip
        assert nw.parse_ip(bad) is None, bad


def headers(*pairs: tuple[str, str]) -> list[tuple[bytes, bytes]]:
    return [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in pairs]


def ips(*texts: str | None) -> list:
    return [None if t is None else ipaddress.ip_address(t) for t in texts]


def test_no_forwarding_headers_is_none():
    assert nw.forwarded(headers(("host", "tv.local"), ("user-agent", "x"))) is None


def test_x_forwarded_for_every_line_and_item():
    said = nw.forwarded(headers(
        ("X-Forwarded-For", "203.0.113.5, 10.0.0.1"), ("X-Forwarded-For", "192.168.1.7"),
    ))  # fmt: skip
    assert said == ips("203.0.113.5", "10.0.0.1", "192.168.1.7")
    # What can't be read is said to be there, unread (never skipped).
    for bad in ("1.2.3.4:80", "[::1]", "fe80::1%eth0", "", "nonsense"):
        assert nw.forwarded(headers(("X-Forwarded-For", f"192.168.1.7, {bad}"))) == ips(
            "192.168.1.7", None
        ), bad


def test_the_other_address_headers():
    for name in ("X-Real-IP", "CF-Connecting-IP", "True-Client-IP"):
        assert nw.forwarded(headers((name, "203.0.113.5"))) == ips("203.0.113.5"), name
        assert nw.forwarded(headers((name, "garbage"))) == ips(None), name


@pytest.mark.parametrize(
    ("value", "found"),
    [
        ("for=192.0.2.60;proto=http;by=203.0.113.43", ["192.0.2.60"]),
        ('For="[2001:db8:cafe::17]:4711"', ["2001:db8:cafe::17"]),
        ('for="[2001:db8:cafe::17]"', ["2001:db8:cafe::17"]),
        ("for=192.0.2.43, for=198.51.100.17", ["192.0.2.43", "198.51.100.17"]),
        ('for="192.0.2.60:8080"', ["192.0.2.60"]),
        ("FOR=192.168.1.9", ["192.168.1.9"]),
        ("for=unknown", [None]),
        ("for=_hidden", [None]),
        ("for=_x;proto=https", [None]),
        ("proto=https", [None]),
        ('for="garbage"', [None]),
        ('for="192.0.2.1, 10.0.0.1"', [None]),
        ('for=192.168.1.9;by="a;b", for=203.0.113.5', ["192.168.1.9", "203.0.113.5"]),
    ],
)
def test_forwarded_rfc_7239(value, found):
    assert nw.forwarded(headers(("Forwarded", value))) == ips(*found)


def test_too_much_is_one_unknown():
    """Past 64 addresses or 4 KB, what's there can't be told: one None."""
    many = ", ".join(f"10.0.{n // 250}.{n % 250 + 1}" for n in range(65))
    assert nw.forwarded(headers(("X-Forwarded-For", many))) == [None]
    big = "10.0.0.1, " + " " * 4100 + "10.0.0.2"
    assert nw.forwarded(headers(("X-Forwarded-For", big))) == [None]


@pytest.mark.parametrize(
    ("host", "kind"),
    [
        ("192.168.1.20:3310", "home"), ("192.168.1.20", "home"), ("[fd00::1]:3310", "home"),
        ("localhost:3310", "home"), ("tapioca", "home"), ("tapioca:3310", "home"),
        ("tv.local", "home"), ("tv.lan", "home"), ("tv.home", "home"),
        ("box.home.arpa", "home"), ("nas.internal", "home"), ("nas.localdomain", "home"),
        ("nas.tail1234.ts.net", "home"), ("TV.LOCAL.", "home"),
        ("tv.example.com", "public-name"), ("tv.example.com:3310", "public-name"),
        ("203.0.113.5", "public-ip"), ("203.0.113.5:3310", "public-ip"),
        ("[2001:db8::1]:3310", "public-ip"), ("", "none"), (None, "none"),
        ("bad host!", "none"),
    ],
)  # fmt: skip
def test_the_host_asked_for(host, kind):
    assert nw.host_kind(host) == kind


def test_names_an_admin_says_are_home():
    assert nw.host_kind("tv.example.com", home_names={"tv.example.com"}) == "home"
    assert nw.host_kind("TV.Example.com.:3310", home_names={"tv.example.com"}) == "home"
    # (BASE_URL's host, the address tapiOca gives for itself at home.)
    assert nw.host_kind("tapioca.example.net", also_home={"tapioca.example.net"}) == "home"
    # The Away from home address's host is never home: a request on the
    # home port by that name is a tunnel pointed at the wrong port.
    assert (
        nw.host_kind("tv.example.com", home_names={"tv.example.com"}, never_home={"tv.example.com"})
        == "public-name"
    )


def judge(**kw):
    kw.setdefault("public_port", False)
    kw.setdefault("peer", "192.168.1.50")
    kw.setdefault("host", "192.168.1.20:3310")
    kw.setdefault("headers", [])
    return nw.judge(**kw)


def test_the_public_port_is_the_internet():
    v = judge(public_port=True, peer="192.168.1.50")
    assert (v.outside, v.why) == (True, "public-port")


def test_a_peer_that_isnt_an_address_is_the_internet():
    for peer in (None, "testclient", ""):
        v = judge(peer=peer)
        assert (v.outside, v.why) == (True, "unknown"), peer


def test_a_link_local_peer_with_its_network_named_is_home():
    """(The audit of 1.32.0: a link-local IPv6 peer comes with its
    network's name, fe80::1%eth0.) The socket says it, so it's believed for
    the peer; never in a header."""
    v = judge(peer="fe80::1%eth0")
    assert (v.outside, v.peer) == (False, ipaddress.ip_address("fe80::1"))
    assert judge(peer="203.0.113.9%eth0").outside


def test_door_1_the_home_port_reached_from_the_internet():
    for peer in ("203.0.113.9", "::ffff:203.0.113.9", "2001:db8::9"):
        v = judge(peer=peer)
        assert (v.outside, v.why) == (True, "home-port"), peer


def test_door_1b_a_public_address_asked_for_on_the_home_port():
    v = judge(host="203.0.113.50:3310")
    assert (v.outside, v.why) == (True, "home-port")


def test_door_2_a_proxy_sending_the_internet_to_the_home_port():
    for h in (
        [("X-Forwarded-For", "203.0.113.5")],
        [("X-Real-IP", "203.0.113.5")],
        [("CF-Connecting-IP", "2606:4700::1")],
        [("True-Client-IP", "8.8.8.8")],
        [("Forwarded", "for=unknown")],
        [("Forwarded", "for=_hidden")],
        [("X-Forwarded-For", "192.168.1.7, garbage")],
    ):
        v = judge(headers=headers(*h))
        assert (v.outside, v.why) == (True, "proxy"), h


def test_at_home():
    v = judge()
    assert (v.outside, v.why, v.door3) == (False, "", False)
    assert v.peer == ipaddress.ip_address("192.168.1.50") and v.forwarded == []
    assert v.visitor == v.peer and not v.untrusted_headers


PROXY = [ipaddress.ip_network("192.168.1.2/32")]


def test_forwarding_headers_say_who_only_from_a_trusted_proxy():
    """(The owner, October 13: "I wouldn't rely on just headers to determine
    reverse proxy. Trusted proxies"; "Don't just assume its your reverse
    proxy because it has the headers.") A device that isn't a listed proxy
    is who it is, whatever its headers say: they can only take away."""
    said = headers(("X-Forwarded-For", "192.168.1.7"))
    v = judge(headers=said)
    assert (v.outside, v.visitor, v.untrusted_headers) == (
        False, ipaddress.ip_address("192.168.1.50"), True,
    )  # fmt: skip
    v = judge(peer="192.168.1.2", headers=said, proxies=PROXY)
    assert (v.outside, v.visitor, v.via_proxy, v.untrusted_headers) == (
        False, ipaddress.ip_address("192.168.1.7"), True, False,
    )  # fmt: skip
    # The address the proxy itself added: the last (those before it are
    # anything a visitor sent); and X-Real-IP, as NGINX-style proxies set it
    # (each kind sent must agree: see the next test).
    v = judge(peer="192.168.1.2", proxies=PROXY,
              headers=headers(("X-Forwarded-For", "192.168.1.44, 192.168.1.60")))  # fmt: skip
    assert v.visitor == ipaddress.ip_address("192.168.1.60")
    v = judge(peer="192.168.1.2", proxies=PROXY, headers=headers(
        ("X-Real-IP", "192.168.1.9"), ("X-Forwarded-For", "192.168.1.44, 192.168.1.9"),
    ))  # fmt: skip
    assert v.visitor == ipaddress.ip_address("192.168.1.9")
    v = judge(peer="192.168.1.2", proxies=PROXY,
              headers=headers(("Forwarded", "for=192.168.1.44, for=192.168.1.61")))  # fmt: skip
    assert v.visitor == ipaddress.ip_address("192.168.1.61")


def test_a_trusted_proxys_headers_must_agree():
    """Proxies differ in what they set: NGINX-style ones set X-Real-IP and
    add to X-Forwarded-For; Caddy adds to X-Forwarded-For and passes a
    visitor's own X-Real-IP (or Forwarded) through untouched; a proxy set to
    send only X-Real-IP passes a visitor's X-Forwarded-For through. So each
    kind a listed proxy sends must name the same visitor, or it can't be
    told who it's for: the internet (fails closed)."""
    ip = ipaddress.ip_address
    spoofs = [
        # (Through Caddy: the visitor's own X-Real-IP, Caddy's X-Forwarded-For.)
        headers(("X-Real-IP", "192.168.1.44"), ("X-Forwarded-For", "203.0.113.5")),
        headers(("X-Real-IP", "192.168.1.44"), ("X-Forwarded-For", "192.168.1.60")),
        # (Through a proxy sending only X-Real-IP: the visitor's own XFF.)
        headers(("X-Forwarded-For", "192.168.1.44"), ("X-Real-IP", "192.168.1.60")),
        # (A visitor's own Forwarded, passed through.)
        headers(("Forwarded", "for=192.168.1.44"), ("X-Forwarded-For", "192.168.1.60")),
    ]
    for said in spoofs:
        assert nw.proxied_visitor(said) is None, said
        v = judge(peer="192.168.1.2", proxies=PROXY, headers=said)
        assert (v.outside, v.why, v.visitor) == (True, "proxy", None), said
    # Agreeing (NGINX-style, NPMplus included): who it's for.
    agree = headers(("X-Real-IP", "192.168.1.60"), ("X-Forwarded-For", "10.0.0.9, 192.168.1.60"),
                    ("Forwarded", "for=192.168.1.60"))  # fmt: skip
    assert nw.proxied_visitor(agree) == ip("192.168.1.60")
    # (Cloudflare in front: what the proxy names is Cloudflare's edge, and
    # CF-Connecting-IP says who.)
    edge = [ipaddress.ip_network("173.245.48.0/20")]
    cf = headers(("X-Real-IP", "173.245.48.7"), ("X-Forwarded-For", "203.0.113.5, 173.245.48.7"),
                 ("CF-Connecting-IP", "203.0.113.5"))  # fmt: skip
    assert nw.proxied_visitor(cf, edge) == ip("203.0.113.5")


def test_a_trusted_proxy_naming_nobody_is_the_internet():
    """A listed proxy is a proxy even when it sends no headers: on the home
    port, with no visitor named (or one that can't be read), who it's for
    can't be told. (1.36.2: naming no one at all, not asked for by an
    internet name, it's marked `proxy_device`: the Gate lets the proxy's own
    computer, Plex there, have the tuner and guide, and nothing else. See
    test_one_box.py.)"""
    for said in ([], headers(("X-Forwarded-For", "garbage")), headers(("Forwarded", "for=_x"))):
        v = judge(peer="192.168.1.2", proxies=PROXY, headers=said)
        assert (v.outside, v.why) == (True, "proxy"), said
        assert v.proxy_device == (said == []), said
    v = judge(peer="192.168.1.2", proxies=PROXY, headers=headers(("X-Real-IP", "203.0.113.5")))
    assert (v.outside, v.why, v.proxy_device) == (True, "proxy", False)
    # (Saying it came over HTTPS, or asked for by an internet name: a
    # visitor passed on, never its computer.)
    v = judge(peer="192.168.1.2", proxies=PROXY, headers=headers(("X-Forwarded-Proto", "https")))
    assert (v.outside, v.proxy_device) == (True, False)
    v = judge(peer="192.168.1.2", host="tv.example.com:3310", proxies=PROXY)
    assert (v.outside, v.proxy_device) == (True, False)
    # (Not listed: at home, as ever.)
    v = judge(peer="192.168.1.2")
    assert (v.outside, v.proxy_device) == (False, False)


def test_loopback_listed_as_a_proxy_but_naming_nobody_is_this_machine():
    """A tunnel in tapiOca's own container (listed as 127.0.0.1) always
    names who; with no forwarding headers at all, loopback is this machine
    itself, such as the image's health check: at home, as before it was
    listed (never trusted: see relays.py), and not door 2 every 30 seconds."""
    loopback = [ipaddress.ip_network("127.0.0.1/32"), ipaddress.ip_network("::1/128")]
    for peer in ("127.0.0.1", "::1"):
        v = judge(peer=peer, host="127.0.0.1:3310", proxies=loopback)
        assert (v.outside, v.why, v.via_proxy, v.untrusted_headers) == (False, "", False, False)
        # (Naming someone: a proxy, as listed.)
        named = headers(("X-Forwarded-For", "203.0.113.5"))
        v = judge(peer=peer, host="tv.example.com", proxies=loopback, headers=named)
        assert (v.outside, v.why, v.via_proxy) == (True, "proxy", True)
        # (Sending headers that can't be read: still the internet.)
        v = judge(peer=peer, proxies=loopback, headers=headers(("X-Forwarded-For", "x")))
        assert (v.outside, v.why) == (True, "proxy")
    # (Any other proxy naming nobody stays the internet: above.)


def test_who_on_the_public_port():
    """On the public port, a listed proxy says who the visitor is (for the
    access log and the wrong-password limits); anyone else is their own
    address; Cloudflare's own addresses say who in CF-Connecting-IP."""
    real = headers(("X-Real-IP", "203.0.113.5"), ("X-Forwarded-For", "203.0.113.5"))
    v = judge(public_port=True, peer="192.168.1.2", proxies=PROXY, headers=real)
    assert v.visitor == ipaddress.ip_address("203.0.113.5")
    v = judge(public_port=True, peer="192.168.1.50", headers=real)
    assert v.visitor == ipaddress.ip_address("192.168.1.50") and v.untrusted_headers
    v = judge(public_port=True, peer="203.0.113.77", headers=real)
    assert v.visitor == ipaddress.ip_address("203.0.113.77")
    cf = headers(("CF-Connecting-IP", "198.51.100.4"))
    v = judge(public_port=True, peer="172.70.1.1", headers=cf, cloudflare=CLOUDFLARE)
    assert v.visitor == ipaddress.ip_address("198.51.100.4")
    v = judge(public_port=True, peer="198.51.100.9", headers=cf, cloudflare=CLOUDFLARE)
    assert v.visitor == ipaddress.ip_address("198.51.100.9")


CLOUDFLARE = [ipaddress.ip_network("172.64.0.0/13")]


def test_door_3_an_internet_name_on_the_home_port_is_only_noted():
    """Split-horizon DNS is common: a name is noted (an alert), never
    refused by itself."""
    v = judge(host="tv.example.com:3310")
    assert (v.outside, v.door3) == (False, True)
    assert not judge(host="tv.example.com", home_names={"tv.example.com"}).door3
    # (Through a trusted proxy at home, the headers say who: not door 3.)
    assert not judge(
        peer="192.168.1.2", proxies=PROXY, host="tv.example.com",
        headers=headers(("X-Forwarded-For", "192.168.1.7")),
    ).door3  # fmt: skip
