"""Relays (relays.py, 1.36.0): addresses that carry other people's
connections (Docker's gateway and userland proxy, Docker Desktop, a router's
hairpin, tapiOca's own addresses), never trusted; and when every connection
seems to come from one, tapiOca can't tell devices apart, so trust is off
(door 5: the owner, October 13, "how security works if we accidentally leave
doors open")."""

from __future__ import annotations

import ipaddress

from fastapi.testclient import TestClient

from app import relays

ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
eth0\t00000000\t010011AC\t0003\t0\t0\t0\t00000000\t0\t0\t0
eth0\t000011AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
"""
FIB_TRIE = """Main:
  +-- 0.0.0.0/0 3 0 5
     |-- 0.0.0.0
        /0 universe UNICAST
     +-- 172.17.0.0/16 2 0 2
           |-- 172.17.0.2
              /32 host LOCAL
           |-- 127.0.0.1
              /32 host LOCAL
"""
IF_INET6 = "fe80000000000000004200fffeac1102 02 40 20 80     eth0\n"
IPV6_ROUTE = (
    "00000000000000000000000000000000 00 00000000000000000000000000000000 00 "
    "fe800000000000000000000000000001 00000400 00000001 00000000 00000003 eth0\n"
)


def ip(text: str):
    return ipaddress.ip_address(text)


def test_reading_whats_a_relay():
    found = relays.read(ROUTE, FIB_TRIE, IF_INET6, IPV6_ROUTE)
    assert {ip("172.17.0.1"), ip("172.17.0.2"), ip("127.0.0.1"), ip("::1"),
            ip("fe80::42:ff:feac:1102"), ip("fe80::1")} <= found  # fmt: skip
    assert ip("172.17.0.3") not in found
    assert relays.read("", "", "", "") == {ip("127.0.0.1"), ip("::1")}


def test_what_cant_be_read_turns_trust_off(monkeypatch):
    """No routing table (tapiOca run from source off Linux, say): it can't
    tell a relay from a device, so trusted networks are off."""
    monkeypatch.setattr(relays, "_proc", lambda name: "")
    assert relays.read_proc() is None
    r = relays.Relays(relays.read_proc)
    assert r.state() == "unreadable" and r.trust_off()
    assert relays.Relays(lambda: {ip("172.17.0.1")}).trust_off() is False


def test_hidden_when_every_connection_comes_from_a_relay():
    r = relays.Relays(lambda: {ip("172.17.0.1")})
    for _ in range(relays.HIDDEN_AFTER - 1):
        r.note(ip("172.17.0.1"))
    assert r.state() == "seen"
    r.note(ip("172.17.0.1"))
    assert r.state() == "hidden"
    # A few from anything else (a container on Docker's network, say) don't
    # show that devices are seen as themselves: still hidden. More do: then
    # it's partly hidden (what comes from the relay is still never trusted).
    for _ in range(relays.SEEN_AGAIN - 1):
        r.note(ip("192.168.1.50"))
    assert r.state() == "hidden"
    r.note(ip("192.168.1.50"))
    assert r.state() == "partial"
    # (Loopback, the image's health check, counts for neither.)
    fresh = relays.Relays(lambda: {ip("172.17.0.1")})
    for _ in range(50):
        fresh.note(ip("127.0.0.1"))
    assert fresh.state() == "seen"


def test_hidden_stays_hidden_through_a_quiet_hour(monkeypatch):
    """Nothing coming shows nothing: only devices seen as themselves end it
    (or else the alert would say trusted networks are back on, wrongly)."""
    now = [1000.0]
    monkeypatch.setattr(relays.time, "monotonic", lambda: now[0])
    r = relays.Relays(lambda: {ip("172.17.0.1")})
    for _ in range(relays.HIDDEN_AFTER):
        r.note(ip("172.17.0.1"))
    assert r.state() == "hidden"
    now[0] += relays.WINDOW_S * 3
    assert r.state() == "hidden"
    for _ in range(relays.SEEN_AGAIN):
        r.note(ip("192.168.1.50"))
    assert r.state() == "seen"  # (the relay's requests are an hour old)
    r.reset()
    assert r.state() == "seen"


def test_a_relay_is_never_trusted_and_hidden_turns_trust_off(tmp_path):
    from app.config import Settings
    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
    )
    ctx = app.state.ctx
    ctx.relays.found = lambda: {ip("172.17.0.1")}
    with TestClient(app, base_url="http://192.168.1.20:3310") as pat:
        assert pat.post(
            "/api/access/users", json={"name": "Pat", "password": "a plenty long password"}
        ).is_success
        ctx.trusted.save({"entries": [{"network": "172.16.0.0/12", "gives": "picker"},
                                      {"network": "192.168.1.0/24", "gives": "picker"}],
                          "confirmWide": True}, by=None)  # fmt: skip
        gateway = TestClient(app, base_url="http://192.168.1.20:3310", client=("172.17.0.1", 5))
        assert "trusted" not in gateway.get("/api/access/me").json()  # (a relay, never)
        device = TestClient(app, base_url="http://192.168.1.20:3310", client=("192.168.1.60", 5))
        assert "trusted" in device.get("/api/access/me").json()
        # Every connection from the gateway, none from anything else: hidden.
        ctx.relays.reset()
        for _ in range(relays.HIDDEN_AFTER):
            gateway.get("/api/access/me")
        assert ctx.relays.state() == "hidden"
        assert "trusted" not in device.get("/api/access/me").json()
        # Devices seen as themselves again: as listed (the relay, never).
        for _ in range(relays.SEEN_AGAIN):
            device.get("/api/access/me")
        assert ctx.relays.state() == "partial"
        assert "trusted" in device.get("/api/access/me").json()
        assert "trusted" not in gateway.get("/api/access/me").json()
        # (The tuner's requests, the stations' icons and logos, and
        # loopback's, count for neither: Plex or Jellyfin in Docker reach
        # tapiOca from the gateway. The cold audit of 1.36.0.)
        ctx.relays.reset()
        for path in ("/discover.json", "/channel-icon/1", "/logos/x.png", "/xmltv.xml"):
            for _ in range(relays.HIDDEN_AFTER):
                gateway.get(path)
        assert ctx.relays.state() == "seen"
        # A reverse proxy on the same machine reaches tapiOca from Docker's
        # gateway, which carries others' connections too (IPv6 through
        # Docker's userland proxy, other containers): listed as a trusted
        # proxy, what it names is never trusted, nor seen as itself, and
        # wrong passwords at home through it count as it, whoever it names.
        # (The cold audit of 1.36.0: before, anyone it carried could name a
        # trusted address.)
        ctx.trusted.save({"proxies": [{"network": "172.17.0.1"}]}, by=None)
        for n in range(relays.HIDDEN_AFTER):
            named = {"X-Forwarded-For": f"192.168.1.{60 + n}", "X-Real-IP": f"192.168.1.{60 + n}"}
            assert "trusted" not in gateway.get("/api/access/me", headers=named).json()
        assert ctx.relays.state() == "hidden"
        ctx.relays.reset()
        app_asks = gateway.post(
            "/api/internal/trusted", json={"app": "tapiOca", "picker": True}, headers=named
        )
        assert app_asks.status_code == 403
        wrong = {"name": "Pat", "password": "wrong"}
        tries = [
            gateway.post("/api/access/sign-in", json=wrong,
                         headers={"X-Forwarded-For": f"192.168.1.{100 + n}"}).status_code
            for n in range(6)
        ]  # fmt: skip
        assert tries == [401] * 5 + [429]
        logged = pat.get("/api/logs?access_log=true").json()["text"]
        # (The access log names the relay, never "via" itself.)
        assert "from 172.17.0.1" in logged and "(via 172.17.0.1)" not in logged
        # (Naming nobody, it's taken as from the internet: never trusted.)
        assert "trusted" not in gateway.get("/api/access/me").json()


def test_the_access_tab_never_offers_a_relays_network_and_marks_a_relay_proxy(tmp_path):
    """Trusting Docker's gateway's network from the setup offer would trust
    everyone it carries: no offer from a relay, nor while relays hide every
    device. A relay listed as a trusted proxy is marked, for the tab's
    warning (right only for a reverse proxy on this same machine)."""
    from app.config import Settings
    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
    )
    ctx = app.state.ctx
    ctx.relays.found = lambda: {ip("172.17.0.1")}
    with TestClient(app, base_url="http://192.168.1.20:3310", client=("192.168.1.50", 5)) as pat:
        assert pat.post(
            "/api/access/users", json={"name": "Pat", "password": "a plenty long password"}
        ).is_success
        got = pat.get("/api/access/trusted").json()
        assert got["you"]["offer"] == "192.168.1.0/24" and got["seeing"] == "seen"
        gateway = TestClient(app, base_url="http://192.168.1.20:3310", client=("172.17.0.1", 5))
        gateway.cookies = pat.cookies
        assert gateway.get("/api/access/trusted").json()["you"]["offer"] is None
        for _ in range(relays.HIDDEN_AFTER):
            gateway.get("/api/access/me")
        got = pat.get("/api/access/trusted").json()
        assert got["you"]["offer"] is None and got["seeing"] == "hidden"
        assert got["relayAddress"] == "172.17.0.1"  # (for the tab's notice)
        ctx.trusted.save(
            {"proxies": [{"network": "172.17.0.1"}, {"network": "192.168.1.2"},
                         {"network": "127.0.0.1"}]}, by=None,
        )  # fmt: skip
        marks = {p["network"]: p["relay"] for p in pat.get("/api/access/trusted").json()["proxies"]}
        assert marks == {"172.17.0.1/32": True, "192.168.1.2/32": False, "127.0.0.1/32": False}
