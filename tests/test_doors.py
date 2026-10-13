"""Doors left open (1.36.0): a mistake in how tapiOca is reached stays safe.
The owner, October 13: "we are also focusing on how security works if we
accidentally leave doors open."

Until 1.36.0, anything reaching the home port was home: a router's port
forward to it, or a reverse proxy pointed at it instead of the public port,
made the internet home, and with signing in off, an Admin. Now (see
networks.py) the home port is home only for a home address asking for a
home name, with nothing from a proxy saying it's the internet. Anything else
gets exactly what the public port gives."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

HOME = "http://192.168.1.20:3310"
INTERNET = "http://192.168.1.20:3311"
ME = "192.168.1.50"
TUNER = (
    "/discover.json", "/lineup.json", "/lineup_status.json", "/device.xml", "/xmltv.xml",
    "/guide.xml", "/stations.m3u", "/stream/1", "/hls/1/index.m3u8", "/art/1",
)  # fmt: skip
PAT = {"name": "Pat", "password": "correct horse"}


@pytest.fixture
def app(tmp_path):
    """tapiOca, started (its other clients share it: one start and stop)."""
    made = make(tmp_path)
    with TestClient(made, base_url=HOME, client=(ME, 50000)):
        yield made


def make(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/tv/s/1.mkv", 60_000)
    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
        port=3310, public_port=3311,
    )  # fmt: skip
    return create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))


def at(app, peer: str, base: str = HOME, **headers: str) -> TestClient:
    """A client of the started tapiOca, from `peer`, at `base`."""
    named = {k.replace("_", "-"): v for k, v in headers.items()}
    return TestClient(app, base_url=base, client=(peer, 50123), headers=named or None)


def treated_as_the_internet(c: TestClient) -> None:
    """What the public port gives while signing in is off: the page, and
    nothing else; never the tuner, guide, playlist or streams."""
    for path in TUNER:
        assert c.get(path).status_code == 404, path
    refused = c.get("/api/status")
    assert refused.status_code == 403 and refused.json()["detail"] == access.NOT_SET_UP
    assert c.get("/api/access/me").json()["notSetUp"] == access.NOT_SET_UP
    assert c.get("/").status_code == 200


def test_at_home_as_before(app):
    home = at(app, ME)
    assert home.get("/discover.json").status_code == 200
    assert home.get("/api/status").status_code == 200  # (signing in off: open at home)
    assert home.get("/api/access/me").json().get("notSetUp") is None
    # A proxy at home, for home devices (local HTTPS names): still home.
    assert at(app, ME, x_forwarded_for="192.168.1.7").get("/api/status").status_code == 200


def test_with_signing_in_off_only_a_home_name_opens_everything(app):
    """DNS rebinding: a web page elsewhere can point a name of its own at
    tapiOca's home address, and a browser at home then sends it what the
    page asks. With signing in off, asked for by a name that isn't home's
    (see networks.host_kind), tapiOca gives only its page (saying why), the
    tuner, and the outside check; once the name is listed, everything."""
    ctx = app.state.ctx
    for host in ("192.168.1.20:3310", "localhost:3310", "tapioca:3310", "nas.local:3310"):
        assert at(app, ME, f"http://{host}").get("/api/status").status_code == 200, host
    rebound = at(app, ME, "http://evil.example:3310")
    refused = rebound.get("/api/status")
    assert refused.status_code == 403 and refused.json()["detail"] == access.NAME_NOT_HOME
    assert rebound.post("/api/access/users", json=PAT).status_code == 403
    assert rebound.get("/api/access/me").json()["notSetUp"] == access.NAME_NOT_HOME
    assert rebound.get("/").status_code == 200
    assert rebound.get("/discover.json").status_code == 200
    assert rebound.get("/api/internal/reach").status_code != 403
    ctx.trusted.save({"homeNames": ["evil.example"]}, by=None)
    assert rebound.get("/api/status").status_code == 200


def test_the_public_port_as_before(app):
    treated_as_the_internet(at(app, ME, INTERNET))


def test_door_1_the_home_port_forwarded_to_the_internet(app):
    for peer in ("203.0.113.9", "::ffff:203.0.113.9"):
        treated_as_the_internet(at(app, peer))


def test_door_1b_an_internet_address_asked_for_on_the_home_port(app):
    treated_as_the_internet(at(app, ME, "http://203.0.113.50:3310"))


def test_door_2_a_proxy_on_the_home_port_sending_the_internet(app):
    for name, value in (
        ("x-forwarded-for", "203.0.113.5"),
        ("x-forwarded-for", "192.168.1.7, 203.0.113.5"),
        ("x-real-ip", "203.0.113.5"),
        ("cf-connecting-ip", "203.0.113.5"),
        ("true-client-ip", "203.0.113.5"),
        ("forwarded", "for=unknown"),
        ("forwarded", 'for="[2001:db8::5]:443"'),
        ("x-forwarded-for", "garbage"),
    ):
        treated_as_the_internet(at(app, ME, **{name: value}))


def test_a_peer_tapioca_cant_judge_is_the_internet(app):
    """(Fail closed: Starlette's test client's own peer, "testclient", is
    no address.)"""
    treated_as_the_internet(TestClient(app, base_url=HOME, client=("testclient", 50000)))


def test_wrong_passwords_through_a_proxy_on_the_home_port_are_counted_by_it(app):
    """A device at home that says it's someone else each try gains nothing:
    on the home port, tries are counted by where they really come from."""
    assert at(app, ME).post("/api/access/users", json=PAT).status_code in (200, 201)
    wrong = {"name": "Pat", "password": "wrong"}
    said = [
        at(app, ME, x_forwarded_for=f"203.0.113.{n + 1}").post("/api/access/sign-in", json=wrong)
        for n in range(6)
    ]
    assert [r.status_code for r in said[:5]] == [401] * 5 and said[5].status_code == 429


def test_a_visitor_a_trusted_proxy_cant_name_doesnt_lock_out_everyone_behind_it(app):
    """Through a listed proxy on the public port, a visitor who sends their
    own Forwarded or a garbled X-Forwarded-For (passed through by the proxy)
    can't be told apart: their wrong passwords count on their own, not as
    the proxy's address, which everyone through it would share."""
    ctx = app.state.ctx
    assert at(app, ME).post("/api/access/users", json=PAT).status_code in (200, 201)
    ctx.trusted.save({"proxies": [{"network": "192.168.1.2"}]}, by=None)
    wrong = {"name": "Pat", "password": "wrong"}
    for n in range(6):
        sneaky = at(app, "192.168.1.2", INTERNET, x_real_ip="203.0.113.7",
                    x_forwarded_for=f"203.0.113.7, 203.0.113.{n + 20}")  # fmt: skip
        last = sneaky.post("/api/access/sign-in", json=wrong)
    assert last.status_code == 429
    # (Someone else through the same proxy, named rightly: not held up.)
    other = at(app, "192.168.1.2", INTERNET, x_real_ip="203.0.113.8",
               x_forwarded_for="203.0.113.8")  # fmt: skip
    assert other.post("/api/access/sign-in", json=PAT).status_code == 200
    text = other.get("/api/logs?access_log=true").json()["text"]
    assert "an unnamed visitor via 192.168.1.2 (over the internet)" in text


def test_the_health_check_with_a_tunnel_listed_in_tapiocas_own_container(app):
    """A tunnel sharing tapiOca's container (cloudflared, say) is listed as
    127.0.0.1. The image's health check, from 127.0.0.1 with no forwarding
    headers, still works, and no door is noted for it."""
    ctx = app.state.ctx
    ctx.trusted.save({"proxies": [{"network": "127.0.0.1"}]}, by=None)
    health = at(app, "127.0.0.1", "http://127.0.0.1:3310")
    for _ in range(3):
        assert health.get("/api/v1/server").status_code == 200
    assert ctx.doors.listed() == []
    # (Through the tunnel, naming someone on the internet: the internet.)
    tunnel = at(app, "127.0.0.1", "http://tv.example.com", x_forwarded_for="203.0.113.5")
    treated_as_the_internet(tunnel)


def test_the_port_itself_stays_a_fact_of_its_own():
    """Whether a request came in on the public port (for the outside check,
    and an app's last time in from outside) isn't whether it's treated as
    from the internet: a proxy pointed at the home port must never make the
    outside check say all's well."""
    scope = {"state": {"outside": True, "port": "home"}}
    assert access.outside(scope) and not access.on_public_port(scope)
    scope = {"state": {"outside": True, "port": "public"}}
    assert access.on_public_port(scope)


def test_each_door_is_noted_and_logged_once_an_hour(app):
    """What reached tapiOca through a door left open is noted for Admins
    (its address, on the page) and in the access log, at most once an hour
    for each door; the alerts say it without any address (they go to web
    addresses an Admin chose: see notify.py)."""
    ctx = app.state.ctx
    for _ in range(3):
        at(app, "203.0.113.9").get("/api/status")
    at(app, ME, x_forwarded_for="203.0.113.5").get("/api/status")
    at(app, ME, "http://tv.example.com:3310").get("/api/access/me")
    at(app, ME, INTERNET, x_real_ip="203.0.113.6").get("/api/access/me")
    seen = {d["about"]: d["address"] for d in ctx.doors.listed()}
    assert seen == {
        "home-port": "203.0.113.9", "proxy": ME, "name": ME, "proxy-unknown": ME,
    }  # fmt: skip
    text = at(app, ME).get("/api/logs?access_log=true").json()["text"]
    assert text.count("203.0.113.9 reached tapiOca's home port from the internet") == 1


def test_the_doors_alerts_say_no_address(app):
    ctx = app.state.ctx
    at(app, "203.0.113.9").get("/api/status")
    at(app, ME, x_forwarded_for="203.0.113.5").get("/api/status")
    ctx.alerts.doors(ctx.doors, open_=False, home_port=3310, public_port=3311)
    now = {a.about: a.sentence for a in ctx.alerts.now() if a.kind == "access"}
    assert now["home-port"] == (
        "tapiOca is being reached from the internet on its home port. Close that port forward. "
        "Until then, tapiOca treats those connections as from the internet."
    )
    assert now["proxy"] == (
        "A reverse proxy or tunnel is sending internet visitors to tapiOca's home port, 3310. "
        "Point it at the public port, 3311, instead. Until then, tapiOca treats them as from "
        "the internet."
    )
    assert not any("203.0.113" in s or ME in s for s in now.values())
    # Signing in off, once setup has asked: said too.
    ctx.alerts.doors(ctx.doors, open_=True, home_port=3310, public_port=0)
    now = {a.about: a.sentence for a in ctx.alerts.now() if a.kind == "access"}
    assert now["open"].startswith("Signing in is off, so anyone on your home network can change")
    # Trusted networks off while every connection comes through a relay
    # (see test_relays.py), and back on once devices are seen again.
    ctx.alerts.doors(ctx.doors, open_=False, home_port=3310, public_port=0, hidden=True)
    now = {a.about: a.sentence for a in ctx.alerts.now() if a.kind == "access"}
    assert now["hidden"].startswith("tapiOca can't see where connections come from: they all")
    ctx.alerts.doors(ctx.doors, open_=False, home_port=3310, public_port=0, hidden=False)
    assert "hidden" not in {a.about for a in ctx.alerts.now() if a.kind == "access"}
    # (And when what's a relay can't be read at all, with networks listed.)
    ctx.alerts.doors(ctx.doors, open_=False, home_port=3310, public_port=0, unreadable=True)
    now = {a.about: a.sentence for a in ctx.alerts.now() if a.kind == "access"}
    assert now["unreadable"].startswith("tapiOca can't read this computer's network settings")
