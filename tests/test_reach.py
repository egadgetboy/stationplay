"""Whether StationPlay's apps can reach it from outside (see reach.py): the
address StationPlay checks itself at, what a check finds, the status from
the checks and the apps, and where the page gets it."""

from __future__ import annotations

import asyncio
import logging
import socket
import ssl
import time
from collections.abc import Callable
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import reach
from app.away import port_problem
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient
from app.reach import Reach

from .fakeplex import FakePlex
from .helpers import Proxy

PORT, PUBLIC_PORT = 3310, 8443
PAT = {"name": "Pat", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple"}
# What names lead to, as a check looks them up (anything else isn't found).
NAMES = {"tv.example.com": ["93.184.216.34"], "nas.myhome.example": ["10.0.0.5"]}


@pytest.fixture(autouse=True)
def looked_up(monkeypatch):
    async def addresses(host: str) -> list[str]:
        if host in NAMES:
            return NAMES[host]
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(reach, "_addresses", addresses)


class Clock:
    """time.monotonic, as a test moves it on."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def reach_at(
    address: str,
    *,
    signed_in: bool = True,
    public_port: int = PUBLIC_PORT,
    clock: Callable[[], float] | None = None,
) -> Reach:
    """Reach on its own, with watching away from home on at `address`, and
    a clock of the test's (`.clock`) unless one is given."""
    away = SimpleNamespace(on=True, address=address)
    access = SimpleNamespace(required=signed_in, app_outside_at=None)
    settings = Settings(port=PORT, public_port=public_port)
    return Reach(away, access, settings, clock=clock or Clock())  # type: ignore[arg-type]


def answering(r: Reach, handler) -> None:
    r.transport = httpx.MockTransport(handler)


def stationplay(r: Reach, *, outside: bool, https: bool):
    """This StationPlay answering a check that came in through the public
    port (`outside`) or not, over HTTPS or not."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/internal/reach"
        r.answer(request.url.params["n"], outside, https)
        port = "public" if outside else "home"
        return httpx.Response(200, json={"stationplay": True, "port": port, "https": https})

    return handler


def answers(status: int, **kwargs):
    return lambda request: httpx.Response(status, **kwargs)


def fails(error: Exception, cause: BaseException | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error from cause

    return handler


def unaccepted(code: int, words: str) -> ssl.SSLCertVerificationError:
    """A certificate OpenSSL didn't accept, as Python reports it."""
    e = ssl.SSLCertVerificationError(
        1, f"[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: {words} (_ssl.c:1000)"
    )
    e.verify_code, e.verify_message = code, words
    return e


def connect_error() -> httpx.ConnectError:
    return httpx.ConnectError("[Errno 111] Connect call failed ('203.0.113.9', 443)")


# What a check finds ---------------------------------------------------------------


def ready(r):
    return stationplay(r, outside=True, https=True)


FINDINGS = [
    # (the address, what answers there, the status's words, what its sentence says)
    ("https://tv.example.com", ready, "Ready",
     ["Ready. Apps away from home reach StationPlay at https://tv.example.com."]),
    ("https://tv.example.com", lambda r: stationplay(r, outside=False, https=True), "Checking",
     ["Warning: your reverse proxy passes https://tv.example.com to port 3310", "home port",
      "never asks for a password", "public port, 8443"]),
    ("https://tv.example.com", lambda r: stationplay(r, outside=True, https=False), "Checking",
     ["reaches StationPlay's public port", "X-Forwarded-Proto"]),
    ("http://tv.example.com", lambda r: stationplay(r, outside=True, https=False), "Checking",
     ["Warning: http://tv.example.com doesn't use HTTPS", "only over HTTPS"]),
    ("http://tv.example.com:8080", lambda r: stationplay(r, outside=False, https=False), "Checking",
     ["Warning: http://tv.example.com:8080 doesn't use HTTPS", "unencrypted", "port 3310",
      "public port, 8443"]),
    ("http://tv.example.com", lambda r: stationplay(r, outside=True, https=True), "Checking",
     ["Warning: http://tv.example.com doesn't use HTTPS", "unencrypted"]),
    # Through a VPN, or at home: plain HTTP to the home port is how it's done.
    ("http://nas.tailnet.ts.net:3310", lambda r: stationplay(r, outside=False, https=False),
     "Ready", ["Ready."]),
    ("http://100.101.102.103:3310", lambda r: stationplay(r, outside=False, https=False),
     "Ready", ["Ready."]),
    ("http://nas.myhome.example:3310", lambda r: stationplay(r, outside=False, https=False),
     "Ready", ["Ready."]),
    ("http://100.101.102.103:8443", lambda r: stationplay(r, outside=True, https=False),
     "Checking", ["only over HTTPS", "http://100.101.102.103:3310"]),
    ("https://tv.example.com", lambda r: fails(connect_error(), socket.gaierror(socket.EAI_NONAME, "x")),
     "Checking", ["The name tv.example.com isn't found"]),
    ("https://tv.example.com", lambda r: fails(connect_error(), unaccepted(10, "certificate has expired")),
     "Checking", ["The HTTPS certificate for tv.example.com has expired"]),
    ("https://tv.example.com", lambda r: fails(connect_error(), unaccepted(9, "certificate is not yet valid")),
     "Checking", ["isn't valid yet"]),
    ("https://tv.example.com", lambda r: fails(connect_error(), unaccepted(
        62, "Hostname mismatch, certificate is not valid for 'tv.example.com'.")),
     "Checking", ["is for another name, not tv.example.com"]),
    ("https://tv.example.com", lambda r: fails(connect_error(), unaccepted(18, "self-signed certificate")),
     "Checking", ["isn't trusted: it's self-signed"]),
    ("https://tv.example.com", lambda r: fails(connect_error(), unaccepted(
        20, "unable to get local issuer certificate")),
     "Checking", ["isn't trusted: devices don't know who issued it"]),
    # (As some systems say it, without OpenSSL's reason.)
    ("https://tv.example.com", lambda r: fails(connect_error(), ssl.SSLCertVerificationError(
        1, "certificate verify failed: certificate has expired")),
     "Checking", ["has expired"]),
    ("https://tv.example.com:8443", lambda r: fails(connect_error(), ssl.SSLError(
        1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")),
     "Checking", ["doesn't answer over HTTPS", "Leave the port out", "https://tv.example.com."]),
    ("https://tv.example.com", lambda r: answers(502), "Checking",
     ["The reverse proxy at https://tv.example.com answered with an error (502 Bad Gateway)",
      "couldn't reach StationPlay", "public port, 8443"]),
    ("https://tv.example.com", lambda r: answers(504), "Checking", ["504 Gateway Timeout"]),
    ("https://tv.example.com", lambda r: answers(522), "Checking", ["error (522)"]),
    ("https://tv.example.com", lambda r: answers(404), "Checking",
     ["Something other than this StationPlay answered at https://tv.example.com (404 Not Found)"]),
    ("https://tv.example.com", lambda r: answers(200, html="<h1>Router login</h1>"), "Checking",
     ["Something other than this StationPlay answered", "a page that isn't StationPlay's"]),
    # Another StationPlay: it isn't waiting for this check.
    ("https://tv.example.com", lambda r: answers(200, json={"stationplay": True}), "Checking",
     ["Something other than this StationPlay answered"]),
    ("https://tv.example.com", lambda r: answers(403), "Checking",
     ["turned the check away", "(403 Forbidden)", "access list"]),
    ("http://tv.example.com", lambda r: lambda request: httpx.Response(
        301, headers={"Location": f"https://tv.example.com{request.url.raw_path.decode()}"}),
     "Checking", ["http://tv.example.com redirects to https://tv.example.com. Use "
                  "https://tv.example.com as the address instead."]),
    ("https://tv.example.com", lambda r: answers(
        302, headers={"Location": "https://auth.example.com/login?rd=https%3A%2F%2Ftv"}),
     "Checking", ["redirects to https://auth.example.com/login instead of reaching StationPlay"]),
    # Couldn't connect: nothing from here has worked, so it can't tell.
    ("https://tv.example.com", lambda r: fails(connect_error(), ConnectionRefusedError(111, "x")),
     "Can't check from here", ["Nothing answered at https://tv.example.com: the connection was "
                                "refused", "NAT loopback", "mobile data"]),
    ("https://tv.example.com", lambda r: fails(httpx.ConnectTimeout("timed out")),
     "Can't check from here", ["Nothing answered at https://tv.example.com within 10 seconds"]),
    ("https://tv.example.com", lambda r: fails(httpx.RemoteProtocolError("closed")),
     "Can't check from here", ["closed the connection without answering"]),
    ("https://tv.example.com", lambda r: fails(connect_error(), socket.gaierror(socket.EAI_AGAIN, "x")),
     "Can't check from here", ["couldn't look up tv.example.com just now"]),
    # A VPN's name that only its devices can look up.
    ("http://nas.tailnet.ts.net:3310", lambda r: fails(
        connect_error(), socket.gaierror(socket.EAI_NONAME, "x")),
     "Can't check from here", ["couldn't look up nas.tailnet.ts.net", "Tailscale"]),
    ("http://100.101.102.103:3310", lambda r: fails(connect_error(), ConnectionRefusedError(111, "x")),
     "Can't check from here", ["on a phone on the VPN"]),
]  # fmt: skip


@pytest.mark.parametrize(("address", "there", "short", "says"), FINDINGS)
async def test_what_a_check_finds(address, there, short, says):
    r = reach_at(address)
    asked: list[httpx.Request] = []
    handler = there(r)

    def recorded(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return handler(request)

    answering(r, recorded)
    status = await r.check_now()
    [request] = asked
    assert request.method == "GET" and request.url.path == "/api/internal/reach"
    assert str(request.url).startswith(f"{address}/api/internal/reach?n=")
    value = request.url.params["n"]
    assert len(value) >= 20
    problem = short not in ("Ready", "Can't check from here")
    states = {"Ready": "up", "Checking": "checking", "Can't check from here": "cant-check"}
    assert status.short == short and status.state == states[short]
    for words in says:
        assert words in status.detail, (words, status.detail)
    if problem:  # (once: it's checked again before it counts)
        assert status.detail.endswith("Checking again in a minute to be sure.")
    # Never the check's value, or what an error says (it can name addresses).
    assert value not in status.detail and "203.0.113.9" not in status.detail
    assert status.checked_ms is not None and status.app_ms is None


async def test_a_check_waits_10_seconds_at_most(monkeypatch):
    monkeypatch.setattr(reach, "WAIT_S", 0.2)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    r = reach_at("https://tv.example.com")
    answering(r, slow)
    status = await asyncio.wait_for(r.check_now(), 2)
    assert status.state == "cant-check" and "within 0.2 seconds" in status.detail


async def test_with_sign_in_off_apps_cant_get_in_through_the_public_port():
    r = reach_at("https://tv.example.com", signed_in=False)
    answering(r, ready(r))
    status = await r.check_now()
    assert status.state == "checking" and "sign-in is off" in status.detail
    # Through a VPN, to the home port, they don't sign in at all.
    r = reach_at("http://nas.tailnet.ts.net:3310", signed_in=False)
    answering(r, stationplay(r, outside=False, https=False))
    assert (await r.check_now()).state == "up"


async def test_without_a_public_port_the_proxy_is_told_to_use_one():
    r = reach_at("https://tv.example.com", public_port=0)
    answering(r, stationplay(r, outside=False, https=True))
    assert "Set PUBLIC_PORT (3311" in (await r.check_now()).detail


async def test_a_value_is_answered_only_while_its_check_waits():
    r = reach_at("https://tv.example.com")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["n"])
        assert r.answer(seen[-1], True, True)
        return httpx.Response(200, json={"stationplay": True, "port": "public", "https": True})

    answering(r, handler)
    await r.check_now()
    assert not r.answer(seen[0], True, True)  # (its check is over)
    assert not r.answer("", True, True) and not r.answer("guess", True, True)
    # And a minute at most, even if its check never ends.

    def late(request: httpx.Request) -> httpx.Response:
        r.clock.now += reach.VALUE_S + 1  # type: ignore[attr-defined]
        assert not r.answer(request.url.params["n"], True, True)
        return httpx.Response(404)

    answering(r, late)
    assert "Something other than this StationPlay answered" in (await r.check_now()).detail


# The status -----------------------------------------------------------------------


async def test_one_problem_isnt_down_two_a_minute_apart_are(caplog):
    caplog.set_level(logging.INFO, logger="app.reach")
    r = reach_at("https://tv.example.com")
    clock = r.clock
    assert r.status().state == "checking" and r.status().checked_ms is None
    answering(r, ready(r))
    up = await r.check_now()
    assert up.state == "up" and up.short == "Ready"
    answering(r, answers(502))
    clock.now += 300  # type: ignore[attr-defined]
    once = await r.check_now()
    assert once.state == "checking" and "502 Bad Gateway" in once.detail
    clock.now += 30  # type: ignore[attr-defined]
    assert (await r.check_now()).state == "checking"  # (not a minute apart yet)
    clock.now += 30  # type: ignore[attr-defined]
    down = await r.check_now()
    assert down.state == "down" and down.short == "Proxy error"
    assert down.detail.startswith("The reverse proxy at https://tv.example.com answered")
    assert down.since_ms >= once.since_ms
    for _ in range(5):
        clock.now += 300  # type: ignore[attr-defined]
        assert (await r.check_now()).state == "down"
    answering(r, ready(r))
    back = await r.check_now()
    assert back.state == "up" and back.since_ms >= down.since_ms
    lines = [(rec.levelname, rec.getMessage()) for rec in caplog.records]
    assert lines == [
        ("WARNING", "StationPlay's apps can't reach it from outside. " + down.detail),
        ("INFO", "StationPlay's apps can reach it from outside again, at https://tv.example.com"),
    ]


async def test_not_connecting_is_down_only_once_a_check_from_here_has_worked(caplog):
    caplog.set_level(logging.INFO, logger="app.reach")
    r = reach_at("https://tv.example.com")
    clock = r.clock
    answering(r, fails(httpx.ConnectTimeout("timed out")))
    for _ in range(4):
        cant = await r.check_now()
        assert cant.state == "cant-check" and "NAT loopback" in cant.detail
        clock.now += 300  # type: ignore[attr-defined]
    assert [rec.getMessage() for rec in caplog.records] == [cant.detail]  # (once)
    # A check from here worked: the router lets checks through, so now it
    # counts (but one alone still doesn't make it down).
    answering(r, ready(r))
    assert (await r.check_now()).state == "up"
    answering(r, fails(httpx.ConnectTimeout("timed out")))
    clock.now += 300  # type: ignore[attr-defined]
    once = await r.check_now()
    assert once.state == "checking" and once.detail.endswith("in a minute to be sure.")
    clock.now += 60  # type: ignore[attr-defined]
    down = await r.check_now()
    assert down.state == "down" and down.short == "Couldn't connect"
    assert "Checks from here got through earlier" in down.detail
    assert caplog.records[-1].levelname == "WARNING"


async def test_an_app_that_came_in_lately_makes_it_up():
    r = reach_at("https://tv.example.com")
    clock = r.clock
    answering(r, fails(connect_error(), ConnectionRefusedError(111, "x")))
    r.access.app_outside_at = clock.now - 5 * 60  # type: ignore[attr-defined]
    up = await r.check_now()
    assert up.state == "up" and up.short == "Apps are getting in"
    assert "Apps away from home are reaching StationPlay" in up.detail
    assert abs(up.app_ms - (up.checked_ms - 5 * 60_000)) < 2000
    # 15 minutes after it, it's back to what checks from here can tell.
    clock.now += 10 * 60 + 1  # type: ignore[attr-defined]
    assert r.status().state == "cant-check"
    # It says so even after a check from here worked (and then didn't).
    answering(r, ready(r))
    await r.check_now()
    answering(r, fails(httpx.ConnectTimeout("timed out")))
    r.access.app_outside_at = clock.now  # type: ignore[attr-defined]
    for _ in range(3):
        clock.now += 60  # type: ignore[attr-defined]
        assert (await r.check_now()).state == "up"
    # But a problem that isn't about connecting isn't hidden by it.
    answering(r, ready(r))
    await r.check_now()
    answering(r, answers(502))
    assert (await r.check_now()).state == "checking"
    clock.now += 60  # type: ignore[attr-defined]
    assert (await r.check_now()).state == "down"


async def test_a_new_address_starts_afresh_and_off_is_off():
    r = reach_at("https://tv.example.com")
    answering(r, fails(connect_error(), unaccepted(10, "certificate has expired")))
    await r.check_now()
    r.clock.now += 60  # type: ignore[attr-defined]
    assert (await r.check_now()).state == "down"
    r.away.address = "https://stationplay.example.com"  # type: ignore[attr-defined]
    r.saved()
    fresh = r.status()
    assert fresh.state == "checking" and fresh.checked_ms is None
    assert "https://stationplay.example.com" in fresh.detail
    r.away.on = False  # type: ignore[attr-defined]
    r.saved()
    off = await r.check_now()
    assert off.state == "off" and off.short == "Off" and off.checked_ms is None


async def test_checks_come_again_a_minute_after_a_problem_and_otherwise_every_5_minutes(
    monkeypatch,
):
    monkeypatch.setattr(reach, "FIRST_S", 0.0)
    monkeypatch.setattr(reach, "AGAIN_S", 0.15)
    monkeypatch.setattr(reach, "EVERY_S", 30.0)

    async def counting(r: Reach, handler, wait: float) -> int:
        asked = 0

        def counted(request: httpx.Request) -> httpx.Response:
            nonlocal asked
            asked += 1
            return handler(request)

        answering(r, counted)
        task = asyncio.create_task(r.run_forever())
        try:
            await asyncio.sleep(wait)
            if r.status().state == "down":
                asked_then = asked
                await asyncio.sleep(0.4)  # (down: 5 minutes until the next)
                assert asked == asked_then
            r.saved()  # (and at once when it's saved)
            await asyncio.sleep(0.05)
        finally:
            task.cancel()
        return asked

    r = reach_at("https://tv.example.com", clock=time.monotonic)
    assert await counting(r, ready(r), 0.5) == 2  # (when it starts, and when it's saved)
    r = reach_at("https://tv.example.com", clock=time.monotonic)
    asked = await counting(r, answers(502), 0.6)
    assert r.status().state == "down" and asked in (3, 4)


# Where the page gets it -------------------------------------------------------------


@pytest.fixture
def app(tmp_path):
    fp = FakePlex()
    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
        port=PORT, public_port=PUBLIC_PORT,
    )  # fmt: skip
    return create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_stationplay_answers_its_own_check_on_both_ports(app):
    ctx = app.state.ctx
    with TestClient(app) as home:
        internet = TestClient(app, base_url=f"http://testserver:{PUBLIC_PORT}")
        # Anything else is 404, on both ports, over plain HTTP too, and
        # before there's a user (when the public port has nothing else).
        for client in (home, internet):
            for asked in ("/api/internal/reach", "/api/internal/reach?n=guess"):
                got = client.get(asked)
                assert got.status_code == 404 and got.json() == {"detail": "Not Found"}
        assert internet.get("/api/v1/stations").status_code == 403
        # Through a proxy that doesn't say HTTPS: StationPlay says what came.
        proxy = Proxy(app, PUBLIC_PORT, https=False)
        ctx.reach.transport = proxy.transport
        on = home.put("/api/away", json={"on": True, "address": "https://tv.example.com"})
        assert on.status_code == 200
        checked = home.post("/api/away/check")
        assert checked.status_code == 200 and checked.json()["state"] == "checking"
        assert "X-Forwarded-Proto" in checked.json()["detail"]
        said = proxy.answers[-1]
        assert said.status_code == 200 and said.headers["stationplay-api"] == "1"
        assert said.json() == {"stationplay": True, "port": "public", "https": False}
        # Over HTTPS, but with sign-in off: apps can't sign in there.
        ctx.reach.transport = Proxy(app, PUBLIC_PORT).transport
        assert "sign-in is off" in home.post("/api/away/check").json()["detail"]
        assert home.post("/api/access/users", json=PAT).status_code == 201
        proxy = Proxy(app, PUBLIC_PORT)
        ctx.reach.transport = proxy.transport
        ready = home.post("/api/away/check").json()
        assert ready["state"] == "up" and ready["short"] == "Ready"
        assert proxy.answers[-1].json() == {"stationplay": True, "port": "public", "https": True}
        # The proxy pointed at the home port: a warning.
        proxy = Proxy(app, PORT)
        ctx.reach.transport = proxy.transport
        wrong = home.post("/api/away/check").json()
        assert wrong["state"] == "checking" and wrong["detail"].startswith("Warning:")
        assert proxy.answers[-1].json() == {"stationplay": True, "port": "home", "https": True}


def test_check_now_is_for_admins(app):
    with TestClient(app) as home:
        off = home.post("/api/away/check")
        assert off.status_code == 400 and "off" in off.json()["detail"]
        assert home.post("/api/access/users", json=PAT).status_code == 201
        assert home.post("/api/access/users", json={**SAM, "role": "user"}).status_code == 201
        home.put("/api/away", json={"on": True, "address": "https://tv.example.com"})
        sam = TestClient(app)
        assert sam.post("/api/access/sign-in", json=SAM).status_code == 200
        assert sam.post("/api/away/check").status_code == 403
        assert sam.get("/api/away").status_code == 403
        assert "away" not in sam.get("/api/status").json()
        stranger = TestClient(app)
        assert stranger.post("/api/away/check").status_code == 401
        checked = home.post("/api/away/check")
        assert checked.status_code == 200
        assert set(checked.json()) == {"state", "detail", "short", "checkedAt", "since", "lastApp"}
        assert checked.json()["state"] == "cant-check"  # (nothing answers in the tests)


def test_the_page_gets_the_status_with_the_setting_and_in_its_header(app):
    with TestClient(app) as home:
        off = home.get("/api/away").json()
        assert off["reach"]["state"] == "off" and off["portProblem"] is None
        assert home.get("/api/status").json()["away"] is None  # (no pill)
        home.put("/api/away", json={"on": True, "address": "https://tv.example.com"})
        got = home.post("/api/away/check").json()
        away = home.get("/api/away").json()
        shown = ("state", "short", "detail", "lastApp")
        assert {k: away["reach"][k] for k in shown} == {k: got[k] for k in shown}
        assert got["state"] == "cant-check" and got["lastApp"] is None
        assert all(isinstance(away["reach"][k], int) for k in ("checkedAt", "since"))
        header = home.get("/api/status").json()["away"]
        assert (header["on"], header["address"]) == (True, "https://tv.example.com")
        assert {k: header["reach"][k] for k in shown} == {k: got[k] for k in shown}


@pytest.mark.parametrize(
    ("address", "warned"),
    [
        ("https://tv.example.com:8443", True),
        ("https://tv.example.com:3310", True),
        ("https://[fd7a:115c::1]:8443", True),
        ("https://tv.example.com", False),
        ("https://tv.example.com:443", False),
        ("https://tv.example.com:9443", False),
        ("http://nas.tailnet.ts.net:3310", False),
        ("http://tv.example.com:8443", False),
    ],
)
def test_an_https_address_on_stationplays_own_port(address, warned):
    problem = port_problem(address, PORT, PUBLIC_PORT)
    assert bool(problem) == warned
    if warned:
        assert problem.startswith("Leave the port out") and "never speaks HTTPS" in problem
    assert port_problem(address, PORT, 0) == ("" if ":8443" in address else problem)


def test_an_https_address_on_stationplays_own_port_is_saved_with_a_warning(app):
    with TestClient(app) as home:
        saved = home.put("/api/away", json={"on": True, "address": "https://tv.example.com:8443"})
        assert saved.status_code == 200 and saved.json()["address"] == "https://tv.example.com:8443"
        problem = saved.json()["portProblem"]
        assert "Leave the port out" in problem and problem.endswith("https://tv.example.com.")
        assert home.get("/api/away").json()["portProblem"] == problem
        fixed = home.put("/api/away", json={"on": True, "address": "https://tv.example.com"})
        assert fixed.json()["portProblem"] is None


def test_an_apps_own_requests_from_outside_count_as_getting_in(app):
    ctx = app.state.ctx
    https = {"X-Forwarded-Proto": "https"}
    with TestClient(app) as home:
        assert home.post("/api/access/users", json=PAT).status_code == 201
        home.put("/api/away", json={"on": True, "address": "https://tv.example.com"})
        internet = TestClient(app, base_url=f"http://testserver:{PUBLIC_PORT}", headers=https)
        signed = internet.post("/api/internal/sign-in", json=PAT)
        token = bearer(signed.json()["token"])
        # Not an app's sign-in itself, a browser signed in through the public
        # port, or an app at home.
        browser = TestClient(app, base_url=f"http://testserver:{PUBLIC_PORT}", headers=https)
        session = browser.post("/api/access/sign-in", json=PAT).cookies["stationplay_session"]
        cookie = {"Cookie": f"stationplay_session={session}"}  # (secure: sent as it says)
        assert browser.get("/api/channels", headers=cookie).status_code == 200
        assert home.get("/api/v1/stations", headers=token).status_code == 200
        assert ctx.access.app_outside_at is None
        assert home.get("/api/away").json()["reach"]["lastApp"] is None
        # An app with its token, from outside.
        assert internet.get("/api/v1/stations", headers=token).status_code == 200
        assert ctx.access.app_outside_at is not None
        last = home.get("/api/away").json()["reach"]["lastApp"]
        assert isinstance(last, int) and abs(last - time.time() * 1000) < 5000
        # (Nothing answers checks in the tests: an app that came in lately
        # says apps get in all the same.)
        assert home.post("/api/away/check").json()["state"] == "up"
