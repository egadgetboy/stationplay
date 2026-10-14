"""One box (1.36.2): a reverse proxy, Plex and tapiOca on one server, as
most people run them (the owner's own TrueNAS: Nginx Proxy Manager, Plex and
tapiOca as apps on one machine). What each layout looks like to tapiOca,
with the proxy trusted, signing in on and the home network trusted:

- Plex keeps the tuner and guide (1.36.1 took them from Plex when Plex and
  the proxy shared an address that isn't Docker's: limit (b) in its report);
- apps come in from outside through the proxy, as who they are;
- nothing through the proxy skips signing in, whatever it says;
- a proxy pointed at the home port by mistake is still the internet.

The lead developer's process change (October 14), for the owner: each of
these layouts is tested here and in tools/attack_check.py."""

from __future__ import annotations

import ipaddress

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

SERVER = "192.168.50.2"
HOME = f"http://{SERVER}:3310"
PUBLIC = f"http://{SERVER}:3311"
PAT = {"name": "Pat", "password": "correct horse"}
LAPTOP = ("192.168.50.20", 5000)
TUNER = ("/discover.json", "/lineup_status.json", "/lineup.json", "/device.xml", "/xmltv.xml")

# (what tapiOca sees: Docker's gateway or this computer's own addresses it
# finds, the proxy's address, Plex's)
LAYOUTS = {
    # Each in a container of its own: both reach tapiOca through Docker's
    # gateway (the owner's: 172.16.39.1).
    "containers": ({"172.16.39.1"}, "172.16.39.1", "172.16.39.1"),
    # Plex on the host's network, the proxy in a container: the same.
    "plex on the host": ({"172.16.39.1"}, "172.16.39.1", "172.16.39.1"),
    # tapiOca on the host's network too: this computer's own address.
    "host networking": ({SERVER}, SERVER, SERVER),
    # Docker keeping where connections come from (no userland proxy):
    # both from the server's own address, which tapiOca in its container
    # doesn't have (1.36.1's case).
    "same address": (set(), SERVER, SERVER),
    # The proxy with an address of its own (macvlan), Plex on the server's.
    "proxy of its own": (set(), "192.168.50.3", SERVER),
}


@pytest.fixture(params=sorted(LAYOUTS))
def box(request, tmp_path):
    relays, proxy, plex = LAYOUTS[request.param]
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/tv/s/1.mkv", 22 * 60_000)
    settings = Settings(
        plex_url=f"http://{SERVER}:32400", plex_token="token", data_dir=tmp_path / "data",
        port=3310, public_port=3311,
    )  # fmt: skip
    made = create_app(
        settings, PlexClient(f"http://{SERVER}:32400", "token", transport=fp.transport())
    )
    with TestClient(made, base_url=HOME, client=LAPTOP) as laptop:
        ctx = made.state.ctx
        ctx.relays.found = lambda: {ipaddress.ip_address(a) for a in relays}
        ctx.relays.refresh()
        assert laptop.post("/api/access/users", json=PAT).status_code == 201
        assert laptop.put(
            "/api/away", json={"on": True, "address": "https://tv.example.com"}
        ).is_success
        ctx.trusted.save({
            "entries": [{"network": "192.168.50.0/24", "label": "Home", "gives": "picker"}],
            "proxies": [{"network": proxy}],
        }, by=None)  # fmt: skip
        made.state.proxy, made.state.plex = proxy, plex
        yield made


def at(app, peer: str, base: str = HOME, **headers: str) -> TestClient:
    named = {k.replace("_", "-"): v for k, v in headers.items()}
    c = TestClient(app, base_url=base, client=(peer, 40000), headers=named or None)
    if "x-tapioca-page" not in named:
        c.headers.pop("X-Tapioca-Page", None)  # (not tapiOca's page: see conftest.py)
    return c


def through_proxy(app, visitor: str, base: str = PUBLIC) -> TestClient:
    """A visitor, as the proxy passes them on (as Nginx Proxy Manager does)."""
    return at(app, app.state.proxy, base, x_forwarded_for=visitor, x_real_ip=visitor,
              x_forwarded_proto="https")  # fmt: skip


def test_plex_keeps_the_tuner_and_guide(box):
    plex = at(box, box.state.plex, user_agent="PlexMediaServer/1.43.4")
    for path in TUNER:
        assert plex.get(path).status_code == 200, path
    assert plex.post("/lineup.post?scan=start&source=Cable").status_code == 200
    assert box.state.ctx.doors.listed() == []  # (no door noted for Plex)


def test_apps_come_in_through_the_proxy_as_who_they_are(box):
    phone = through_proxy(box, "203.0.113.9")
    signed = phone.post("/api/internal/sign-in", json={**PAT, "app": "tapiOca for Android"})
    assert signed.status_code == 200, signed.text
    token = {"Authorization": f"Bearer {signed.json()['token']}"}
    assert phone.get("/api/internal/me", headers=token).status_code == 200
    log = at(box, LAPTOP[0], x_tapioca_page="1")
    assert log.post("/api/access/sign-in", json=PAT).status_code == 200
    text = log.get("/api/logs?access_log=true").json()["text"]
    assert "203.0.113.9 (over the internet)" in text
    # The tuner is never on the public port.
    for path in TUNER:
        assert phone.get(path).status_code == 404, path


def test_nothing_through_the_proxy_skips_signing_in(box):
    """Whatever the proxy says, and when it says nothing: never trusted."""
    for c in (
        through_proxy(box, "192.168.50.20"),  # (a home address, from outside)
        through_proxy(box, "203.0.113.9"),
        at(box, box.state.proxy),  # (the proxy's own computer, naming nobody)
    ):
        assert "trusted" not in c.get("/api/access/me").json()
        picked = c.post(
            "/api/access/trusted-sign-in", json={"id": 1}, headers={"X-Tapioca-Page": "1"}
        )
        assert picked.status_code in (403, 404)
        assert c.get("/api/channels").status_code in (401, 403)
    # (The laptop beside it, as listed.)
    assert at(box, LAPTOP[0]).get("/api/access/me").json()["trusted"]["gives"] == "picker"


def test_a_proxy_pointed_at_the_home_port_is_still_the_internet(box):
    visitor = through_proxy(box, "203.0.113.9", HOME)
    for path in TUNER:
        assert visitor.get(path).status_code == 404, path
    refused = visitor.get("/api/status")
    assert refused.status_code in (401, 403)
    assert any(d["about"] == "proxy" for d in box.state.ctx.doors.listed())
    # (Its own requests, naming nobody, are its computer's: the tuner, as Plex.)
    assert at(box, box.state.proxy).get("/discover.json").status_code == 200


def test_the_outside_check_through_the_proxy_is_ready(box):
    """The proxy, trusted, brings tapiOca's own outside check in over HTTPS,
    and Plex keeps the tuner after (the owner's order: setup, then Plex)."""
    ctx = box.state.ctx
    stationplay = httpx.ASGITransport(app=box, client=(box.state.proxy, 443))

    async def nginx(request: httpx.Request) -> httpx.Response:
        url = request.url.copy_with(scheme="http", host=SERVER, port=3311)
        headers = {k: v for k, v in request.headers.items() if k != "host"}
        headers |= {"X-Forwarded-For": "203.0.113.1", "X-Real-IP": "203.0.113.1",
                    "X-Forwarded-Proto": "https"}  # fmt: skip
        got = await stationplay.handle_async_request(
            httpx.Request(request.method, url, headers=headers)
        )
        await got.aread()
        return httpx.Response(got.status_code, headers=got.headers, content=got.content)

    ctx.reach.transport = httpx.MockTransport(nginx)
    page = at(box, LAPTOP[0], x_tapioca_page="1")
    assert page.post("/api/access/sign-in", json=PAT).status_code == 200
    ready = page.post("/api/away/check").json()
    assert ready["state"] == "up", ready
    for path in TUNER:
        assert at(box, box.state.plex).get(path).status_code == 200, path


@pytest.mark.parametrize("signing_in", [False, True])
def test_a_proxy_naming_no_one_gets_only_what_plex_does(tmp_path, signing_in):
    """The cold audit of 1.36.2, its first finding: a trusted proxy that sends
    no headers at all can't be told from its own computer. If it were taken
    as at home for everything, a proxy pointed at the home port by mistake,
    sending none (HAProxy without forwardfor, a TCP forward), would let the
    internet in as home: with signing in off, as an Admin. So only Plex's
    tuner, guide and logos are its computer's; the page and the API are a
    proxy's, for the internet, as in 1.36.1."""
    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
        port=3310, public_port=3311,
    )  # fmt: skip
    made = create_app(
        settings, PlexClient("http://plex.test", "token", transport=FakePlex().transport())
    )
    with TestClient(made, base_url=HOME, client=LAPTOP) as laptop:
        if signing_in:
            assert laptop.post("/api/access/users", json=PAT).status_code == 201
        made.state.ctx.trusted.save({"proxies": [{"network": "192.168.50.3"}]}, by=None)
        for host in ("localhost", SERVER, "tapioca"):
            box = TestClient(made, base_url=f"http://{host}:3310", client=("192.168.50.3", 5))
            for path in ("/api/access/users", "/api/status", "/api/channels"):
                assert box.get(path).status_code in (401, 403), (host, path)
            assert box.post("/api/channels", json={"number": 7, "sources": []}).status_code in (
                401,
                403,
            )
            assert box.get("/api/access/me").json().get("outside") is True
            # (What Plex asks for, from its computer: as at home.)
            assert box.get("/discover.json").status_code == 200
        assert any(d["about"] == "proxy" for d in made.state.ctx.doors.listed())
        # (The laptop beside it, at home, as before: signed in, or open.)
        assert laptop.get("/api/channels").status_code == 200
