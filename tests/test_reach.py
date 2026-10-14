"""Whether tapiOca's apps can reach it from outside (see reach.py): the
address tapiOca checks itself at, what a check finds, the status from
the checks and the apps, and where the page gets it."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import shutil
import socket
import ssl
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
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
from .helpers import Proxy, through_proxy

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
    """This tapiOca answering a check that came in through the public
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
     ["Ready. Apps away from home reach tapiOca at https://tv.example.com."]),
    ("https://tv.example.com", lambda r: stationplay(r, outside=False, https=True), "Checking",
     ["Warning: your reverse proxy passes https://tv.example.com to port 3310", "home port",
      "never asks for a password", "public port, 8443"]),
    ("https://tv.example.com", lambda r: stationplay(r, outside=True, https=False), "Checking",
     ["reaches tapiOca's public port", "X-Forwarded-Proto"]),
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
    ("https://tv.example.com", lambda r: fails(connect_error(), unaccepted(23, "certificate revoked")),
     "Checking", ["has been revoked"]),
    # (As some systems say it, without OpenSSL's reason.)
    ("https://tv.example.com", lambda r: fails(connect_error(), ssl.SSLCertVerificationError(
        1, "certificate verify failed: certificate has expired")),
     "Checking", ["has expired"]),
    # tapiOca's own port with https:// is wrong wherever it's checked from.
    ("https://tv.example.com:8443", lambda r: fails(connect_error(), ssl.SSLError(
        1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")),
     "Checking", ["doesn't answer over HTTPS", "Leave the port out", "https://tv.example.com."]),
    ("https://tv.example.com", lambda r: answers(502), "Checking",
     ["The reverse proxy at https://tv.example.com answered with an error (502 Bad Gateway)",
      "couldn't reach tapiOca", "public port, 8443"]),
    ("https://tv.example.com", lambda r: answers(504), "Checking", ["504 Gateway Timeout"]),
    ("https://tv.example.com", lambda r: answers(522), "Checking", ["error (522)"]),
    # What may be the router (see ROUTER_LIKE): nothing from here has worked,
    # so it can't tell.
    ("https://tv.example.com", lambda r: fails(connect_error(), unaccepted(18, "self-signed certificate")),
     "Can't check from here",
     ["From here, https://tv.example.com answers with a self-signed certificate. That's likely "
      "your router itself", "apps away from home still work", "on a phone using mobile data",
      "add a DNS override in your router that points tv.example.com at your reverse proxy's "
      "address on your home network."]),
    ("http://tv.example.com", lambda r: lambda request: httpx.Response(
        301, headers={"Location": f"https://tv.example.com{request.url.raw_path.decode()}"}),
     "Can't check from here", ["From here, http://tv.example.com redirects to "
                               "https://tv.example.com. That's likely your router itself"]),
    ("https://tv.example.com", lambda r: fails(connect_error(), ConnectionRefusedError(111, "x")),
     "Can't check from here", ["Nothing answered at https://tv.example.com: the connection was "
                                "refused", "NAT loopback", "mobile data", "DNS override"]),
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
    ("http://100.101.102.103:3310", lambda r: answers(404), "Can't check from here",
     ["From here, http://100.101.102.103:3310 answers with 404 Not Found", "on a phone on the VPN"]),
]  # fmt: skip

# What may be the home's router answering for the outside address, from
# inside the home (it has no NAT loopback), as the owner's does: (what
# answers, what the address does, as it's said, and what the finding says
# once it counts).
ROUTER_LIKE = [
    # The router's own certificate: self-signed, and for another name.
    (lambda r: fails(connect_error(), unaccepted(18, "self-signed certificate")),
     "answers with a self-signed certificate", ["isn't trusted: it's self-signed"]),
    (lambda r: fails(connect_error(), unaccepted(
        62, "Hostname mismatch, certificate is not valid for 'tv.example.com'.")),
     "answers with a certificate for another name", ["is for another name, not tv.example.com"]),
    (lambda r: fails(connect_error(), unaccepted(20, "unable to get local issuer certificate")),
     "answers with a certificate devices don't trust",
     ["isn't trusted: devices don't know who issued it"]),
    # Its sign-in page, or a warning page in its place.
    (lambda r: answers(200, html="<h1>A potential DNS Rebind attack has been detected.</h1>"),
     "answers with a page that isn't tapiOca's",
     ["Something other than this tapiOca answered", "a page that isn't tapiOca's"]),
    (lambda r: answers(403, html="<h1>Login</h1>"),
     "answers with 403 Forbidden instead of tapiOca's answer",
     ["turned the check away", "(403 Forbidden)", "access list"]),
    (lambda r: answers(404), "answers with 404 Not Found instead of tapiOca's answer",
     ["Something other than this tapiOca answered at https://tv.example.com (404 Not Found)"]),
    # (Another tapiOca: it isn't waiting for this check.)
    (lambda r: answers(200, json={"stationplay": True}),
     "answers with a page that isn't tapiOca's",
     ["Something other than this tapiOca answered"]),
    # A redirect to it, or to a sign-in page.
    (lambda r: answers(302, headers={"Location": "https://192.168.1.1/index.php"}),
     "redirects to https://192.168.1.1/index.php",
     ["redirects to https://192.168.1.1/index.php instead of reaching tapiOca"]),
    (lambda r: answers(
        302, headers={"Location": "https://auth.example.com/login?rd=https%3A%2F%2Ftv"}),
     "redirects to https://auth.example.com/login",
     ["redirects to https://auth.example.com/login instead of reaching tapiOca"]),
    (lambda r: fails(connect_error(), ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number")),
     "doesn't answer over HTTPS",
     ["doesn't answer over HTTPS", "Check that the address leads to your reverse proxy"]),
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


async def test_with_sign_in_off_the_address_works_and_sign_in_is_the_next_step():
    """(1.36.2, by design: until then, "reaches tapiOca, but sign-in is off,
    so apps can't sign in through the public port", checked again each
    minute and then Down, which read as tapiOca broken. The owner, October
    14: "This seems to be process not error, but this comes across as an
    error.") The address works; turning on sign-in is the step left, said
    as one at once, never Down, and never an alert or a warning in the
    log."""
    clock = Clock()
    r = reach_at("https://tv.example.com", signed_in=False, clock=clock)
    answering(r, ready(r))
    status = await r.check_now()
    assert (status.state, status.short) == ("next-step", "Needs sign-in")
    assert status.detail == (
        "Your address works: https://tv.example.com reaches tapiOca. One step left: turn on "
        "sign-in. Apps sign in when they're away from home."
    )
    # Not a problem: checked again as usual, not in a minute, and never Down.
    assert r._due == clock() + reach.EVERY_S
    clock.now += reach.EVERY_S
    assert (await r.check_now()).state == "next-step"
    # Sign-in turned on: checked again at once (not minutes later), and Ready.
    r.access.required = True
    checking = r.status()
    assert checking.state == "checking" and checking.detail.startswith("Sign-in is on. Checking")
    assert r._due <= clock()
    assert (await r.check_now()).state == "up"
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
    assert "Something other than this tapiOca answered" in (await r.check_now()).detail


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
        ("WARNING", "tapiOca's apps can't reach it from outside. " + down.detail),
        ("INFO", "tapiOca's apps can reach it from outside again, at https://tv.example.com"),
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


@pytest.mark.parametrize(("there", "found", "says"), ROUTER_LIKE)
async def test_what_may_be_the_router_counts_only_once_a_check_from_here_has_worked(
    there, found, says, caplog
):
    caplog.set_level(logging.INFO, logger="app.reach")
    r = reach_at("https://tv.example.com")
    clock = r.clock
    answering(r, there(r))
    for _ in range(4):  # (never down, however long it goes on)
        cant = await r.check_now()
        assert cant.state == "cant-check" and cant.short == "Can't check from here"
        assert cant.detail.startswith(
            f"From here, https://tv.example.com {found}. That's likely your router itself: many "
            "routers answer for your home's own internet address when it's used from inside "
            "your home, while apps away from home still work."
        )
        assert cant.detail.endswith(
            "add a DNS override in your router that points tv.example.com at your reverse "
            "proxy's address on your home network."
        )
        clock.now += 300  # type: ignore[attr-defined]
    assert [rec.getMessage() for rec in caplog.records] == [cant.detail]  # (once)
    # An app came in from outside lately: apps get in.
    r.access.app_outside_at = clock.now  # type: ignore[attr-defined]
    up = r.status()
    assert up.state == "up" and up.short == "Apps are getting in"
    assert f"From here, https://tv.example.com {found}: likely your router" in up.detail
    r.access.app_outside_at = None  # type: ignore[attr-defined]
    # A check from here worked: the router lets checks through, so now it
    # counts (but one alone still doesn't make it down).
    answering(r, ready(r))
    assert (await r.check_now()).state == "up"
    answering(r, there(r))
    clock.now += 300  # type: ignore[attr-defined]
    once = await r.check_now()
    assert once.state == "checking" and once.detail.endswith("in a minute to be sure.")
    for words in says:
        assert words in once.detail, (words, once.detail)
    clock.now += 60  # type: ignore[attr-defined]
    down = await r.check_now()
    assert down.state == "down"
    assert "Checks from here got through earlier, so this isn't your router" in down.detail
    assert caplog.records[-1].levelname == "WARNING"


async def test_an_app_that_came_in_lately_makes_it_up():
    r = reach_at("https://tv.example.com")
    clock = r.clock
    answering(r, fails(connect_error(), ConnectionRefusedError(111, "x")))
    r.access.app_outside_at = clock.now - 5 * 60  # type: ignore[attr-defined]
    up = await r.check_now()
    assert up.state == "up" and up.short == "Apps are getting in"
    assert "Apps away from home are reaching tapiOca" in up.detail
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
    # But a problem that can't be the router isn't hidden by it.
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
        # Through a proxy that doesn't say HTTPS: tapiOca says what came.
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
        # Over HTTPS, but with sign-in off: the address works, and turning
        # on sign-in is the step left.
        ctx.reach.transport = Proxy(app, PUBLIC_PORT).transport
        step = home.post("/api/away/check").json()
        assert step["state"] == "next-step" and step["detail"].startswith("Your address works")
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
        internet = through_proxy(app, base_url=f"http://testserver:{PUBLIC_PORT}", headers=https)
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


class UnlistedProxy:
    """A reverse proxy in front of tapiOca's public port that isn't listed
    under Trusted proxies yet: it names the visitor (X-Forwarded-For), and
    says HTTPS (X-Forwarded-Proto) if `https`. From `peer`."""

    def __init__(
        self, app, https: bool = True, peer: str = "192.168.1.3", names: bool = True
    ) -> None:
        self.https, self.answers = https, []
        stationplay = httpx.ASGITransport(app=app, client=(peer, 123))

        async def handler(request: httpx.Request) -> httpx.Response:
            url = request.url.copy_with(scheme="http", host="testserver", port=PUBLIC_PORT)
            headers = {k: v for k, v in request.headers.items() if k != "host"}
            if names:
                headers["X-Forwarded-For"] = "203.0.113.9"
            if self.https:
                headers["X-Forwarded-Proto"] = "https"
            got = await stationplay.handle_async_request(
                httpx.Request(request.method, url, headers=headers)
            )
            await got.aread()
            self.answers.append(got)
            return httpx.Response(got.status_code, headers=got.headers, content=got.content)

        self.transport = httpx.MockTransport(handler)


def away_on(home) -> None:
    assert home.post("/api/access/users", json=PAT).status_code == 201
    home.put("/api/away", json={"on": True, "address": "https://tv.example.com"})


def trust(client, address: str = "192.168.1.3"):
    return client.post("/api/away/trust-proxy", json={"address": address})


def test_a_proxy_not_trusted_yet_is_trusted_right_there(app):
    """The owner, October 13 (1.36.1): the setup's check said to list the
    proxy on the Access tab, so an Admin had to leave the setup to fix it.
    Now it offers to trust the proxy the check came through, by itself."""
    ctx = app.state.ctx
    with TestClient(app) as home:
        away_on(home)
        # Nothing to trust before a check found one.
        assert trust(home).status_code == 409
        ctx.reach.transport = UnlistedProxy(app).transport
        found = home.post("/api/away/check").json()
        assert ctx.reach._latest.short == "Proxy not trusted yet"  # (the alert's words)
        assert found["detail"].startswith(
            "https://tv.example.com reaches tapiOca through a reverse proxy at 192.168.1.3, "
            "which isn't a trusted proxy yet, so tapiOca turns apps away there. To fix it, "
            "choose Trust this proxy."
        )
        assert "X-Forwarded-Proto" not in found["detail"]
        assert found["trustProxy"] == {"address": "192.168.1.3", "relay": False}
        assert home.get("/api/away").json()["reach"]["trustProxy"]["address"] == "192.168.1.3"
        # Only by an Admin, signed in.
        assert home.post("/api/access/users", json={**SAM, "role": "user"}).status_code == 201
        sam = TestClient(app)
        assert sam.post("/api/access/sign-in", json=SAM).status_code == 200
        assert trust(sam).status_code == 403
        assert trust(TestClient(app)).status_code == 401
        # Only the address the page showed: a stale page lists nothing, and
        # neither does a plain form from another site (no JSON).
        assert trust(home, "192.168.1.99").status_code == 409
        form = home.post("/api/away/trust-proxy", data={"address": "192.168.1.3"})
        assert form.status_code == 422
        assert ctx.trusted.proxies == []
        # Trusted: listed, by itself only, and checked again: ready.
        ready = trust(home)
        assert ready.status_code == 200, ready.text
        assert ready.json()["state"] == "up" and "trustProxy" not in ready.json()
        assert [p["network"] for p in ctx.trusted.proxies] == ["192.168.1.3/32"]
        logged = home.get("/api/logs?access_log=true").json()["text"]
        assert "Pat trusted the reverse proxy at 192.168.1.3 (Trust this proxy)" in logged
        # Nothing more to trust after that.
        assert trust(home).status_code == 409
        # And with watching away from home off, there's nothing to trust.
        home.put("/api/away", json={"on": False, "address": "https://tv.example.com"})
        off = trust(home)
        assert off.status_code == 400 and "no proxy to trust" in off.json()["detail"]


def test_what_a_proxy_that_doesnt_say_https_is_told(app):
    ctx = app.state.ctx
    with TestClient(app) as home:
        away_on(home)
        # Not listed, and not saying HTTPS: trust it, and send the header.
        ctx.reach.transport = UnlistedProxy(app, https=False).transport
        found = home.post("/api/away/check").json()
        assert found["trustProxy"]["address"] == "192.168.1.3"
        assert (
            "To fix it, choose Trust this proxy. Also set the proxy to send X-Forwarded-Proto: "
            "https." in found["detail"]
        )
        assert trust(home).json()["state"] == "checking"
        # Listed now, still not saying HTTPS: only the header is left.
        again = home.post("/api/away/check").json()
        assert "trustProxy" not in again
        assert again["detail"].startswith(
            "https://tv.example.com reaches tapiOca through your trusted proxy at 192.168.1.3, "
            "but the proxy doesn't say a request came over HTTPS, so tapiOca turns apps away "
            "there. Set the proxy to send X-Forwarded-Proto: https."
        )
        assert trust(home).status_code == 409


def test_docker_s_own_address_is_offered_with_a_warning_and_loopback_isnt_one(app):
    ctx = app.state.ctx
    with TestClient(app) as home:
        away_on(home)
        ctx.relays.found = lambda: {ipaddress.ip_address("172.17.0.1")}
        ctx.relays.refresh()
        # (Plex, through the same gateway, uses the tuner: the gateway is
        # offered all the same, as listing it never takes the tuner away.)
        plex = TestClient(app, client=("172.17.0.1", 5), headers={"User-Agent": "PlexMediaServer"})
        assert plex.get("/discover.json").status_code == 200
        ctx.reach.transport = UnlistedProxy(app, peer="172.17.0.1").transport
        assert home.post("/api/away/check").json()["trustProxy"] == {
            "address": "172.17.0.1", "relay": True,
        }  # fmt: skip
        # (A tunnel in tapiOca's own container: loopback, not Docker's.)
        ctx.reach.transport = UnlistedProxy(app, peer="127.0.0.1").transport
        assert home.post("/api/away/check").json()["trustProxy"] == {
            "address": "127.0.0.1", "relay": False,
        }  # fmt: skip


def test_a_listed_docker_gateway_leaves_plex_and_the_apps_at_home_alone(app):
    """The cold audit of 1.36.1, its first finding, a 1.36.0 bug: Docker's
    gateway listed as a trusted proxy (for a reverse proxy in another
    container, as the README says) turned everything through it that names
    nobody into the internet: Plex's tuner, tapiOca's apps at home, and,
    with signing in off, the page. A relay naming nobody is itself now;
    what it names is judged as before."""
    ctx = app.state.ctx
    with TestClient(app) as home:
        ctx.relays.found = lambda: {ipaddress.ip_address("172.17.0.1")}
        ctx.relays.refresh()
        ctx.trusted.save({"proxies": [{"network": "172.17.0.1"}]}, by=None)
        gateway = TestClient(app, client=("172.17.0.1", 5))
        # Signing in off: the page and the tuner, as from home.
        for path in ("/discover.json", "/lineup.json", "/xmltv.xml", "/api/status"):
            assert gateway.get(path).status_code == 200, path
        # What the proxy names from the internet, on the home port, is still
        # the internet (a proxy pointed at the home port).
        named = gateway.get("/api/status", headers={"X-Forwarded-For": "203.0.113.9"})
        assert named.status_code == 403
        # Signing in on: an app at home through the gateway signs in and
        # asks as before, and nothing is trusted through it.
        assert home.post("/api/access/users", json=PAT).status_code == 201
        signed = gateway.post("/api/internal/sign-in", json={**PAT, "app": "tapiOca"})
        assert signed.status_code == 200, signed.text
        token = bearer(signed.json()["token"])
        assert gateway.get("/api/internal/me", headers=token).status_code == 200
        assert "trusted" not in gateway.get("/api/access/me").json()
        # (1.36.2, by design: a proxy that isn't a relay is itself too when
        # it names nobody, as trusted proxies are everywhere, so Plex on its
        # computer keeps the tuner. Until then it was the internet, which
        # took the tuner and guide from the owner's Plex, October 14. What
        # it names from the internet is still the internet.)
        ctx.trusted.save({"proxies": [{"network": "192.168.1.3"}]}, by=None)
        box = TestClient(app, client=("192.168.1.3", 5))
        for path in ("/discover.json", "/lineup.json", "/xmltv.xml"):
            assert box.get(path).status_code == 200, path
        assert "trusted" not in box.get("/api/access/me").json()
        visitor = {"X-Forwarded-For": "203.0.113.9"}
        assert box.get("/discover.json", headers=visitor).status_code == 404


def test_what_cant_be_trusted_isnt_offered(app):
    ctx = app.state.ctx
    with TestClient(app) as home:
        away_on(home)
        # An internet address can't be a trusted proxy.
        ctx.reach.transport = UnlistedProxy(app, peer="198.51.100.7").transport
        found = home.post("/api/away/check").json()
        assert "trustProxy" not in found
        assert "That's an internet address, which can't be a trusted proxy" in found["detail"]
        # Nor an eleventh.
        ctx.trusted.save({"proxies": [{"network": f"192.168.9.{n}"} for n in range(10)]}, by=None)
        ctx.reach.transport = UnlistedProxy(app).transport
        found = home.post("/api/away/check").json()
        assert "trustProxy" not in found and "remove one on the Access tab" in found["detail"]
        ctx.trusted.save({"proxies": []}, by=None)
        # (1.36.2, by design: a computer that uses the tuner too, such as
        # Plex on the proxy's computer, is offered like any other now.
        # Listed, what it asks for itself, naming nobody, stays at home, so
        # Plex keeps the tuner: see test_networks.py.)
        plex = TestClient(app, client=("192.168.1.3", 5), headers={"User-Agent": "PlexMediaServer"})
        assert plex.get("/discover.json").status_code == 200
        found = home.post("/api/away/check").json()
        assert found["trustProxy"] == {"address": "192.168.1.3", "relay": False}
        assert trust(home).json()["state"] == "up"
        for path in ("/discover.json", "/lineup.json", "/xmltv.xml"):
            assert plex.get(path).status_code == 200, path


def test_only_the_newest_check_and_the_first_answer_count():
    """A slower, older check never overwrites a newer one; and a second
    device answering a check means no proxy is offered."""
    r = reach_at("https://tv.example.com")
    hop = {"address": "192.168.1.3", "sentHeaders": True, "unlisted": ""}
    gate = asyncio.Event()

    async def slow_then_ready(request: httpx.Request) -> httpx.Response:
        value = request.url.params["n"]
        if not gate.is_set():
            gate.set()
            await asyncio.sleep(0.2)  # (the older check, answered late)
            r.answer(value, True, False, hop)
        else:
            r.answer(value, True, True)
        return httpx.Response(200, json={"stationplay": True, "port": "public", "https": True})

    async def both() -> None:
        r.transport = httpx.MockTransport(slow_then_ready)
        older = asyncio.create_task(r.check_now())
        await gate.wait()
        await r.check_now()  # (the newer one: ready)
        await older

    asyncio.run(both())
    assert r.status().short == "Ready" and r.status().trust_proxy is None

    r = reach_at("https://tv.example.com")

    def two_devices(request: httpx.Request) -> httpx.Response:
        value = request.url.params["n"]
        r.answer(value, True, False, hop)
        r.answer(value, True, False, {**hop, "address": "192.168.1.66"})
        return httpx.Response(200, json={"stationplay": True, "port": "public", "https": False})

    answering(r, two_devices)
    asyncio.run(r.check_now())
    assert r.status().trust_proxy is None and r.proxy_to_trust() == ""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_says_what_trusting_the_proxy_does():
    script = (Path(__file__).resolve().parents[1] / "app/web/js/apps.js").read_text()
    start = script.index("function trustProxyWords(")
    code = script[start : script.index("\n}\n", start) + 3] + (
        "console.log(JSON.stringify([trustProxyWords({address: '192.168.1.3', relay: false}),"
        " trustProxyWords({address: '172.17.0.1', relay: true})]));"
    )
    done = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    plain, relay = json.loads(done.stdout)
    # (1.36.2: what the computer asks for itself keeps working, so the
    # words say that now, not that it's taken as the internet.)
    assert plain == (
        "This lists 192.168.1.3 under Trusted proxies, on the Access tab. tapiOca then believes "
        "what it says about each visitor: who they are, and that they came over HTTPS. Plex, or "
        "anything else on that computer, keeps working as before. Trust it only if it’s your "
        "reverse proxy."
    )
    # (1.36.2: said plainly, the owner, October 14: "Also over my head a bit.")
    assert relay == (
        "172.17.0.1 is Docker’s address on this server. Your reverse proxy in another container "
        "reaches tapiOca through it, and so do Plex and your other apps, which keep working. "
        "Trust it only if your proxy runs in a container on this server."
    )
    # (The button sends the address it showed.)
    assert "body: { address: awayNow?.reach?.trustProxy?.address || '' }" in script


def test_plexs_own_address_is_offered_and_plex_keeps_the_tuner(tmp_path):
    """(1.36.2, by design.) In 1.36.1, PLEX_URL's own address wasn't
    offered, since listed, Plex there would lose the tuner (its cold audit).
    Now a listed proxy naming nobody is the device itself, at home, so Plex
    on the proxy's computer keeps the tuner and guide: the owner's Plex DVR
    setup, October 14, "There was a problem fetching channel mappings."
    """
    fp = FakePlex()
    settings = Settings(
        plex_url="http://192.168.1.3:32400", plex_token="token", data_dir=tmp_path / "data",
        port=PORT, public_port=PUBLIC_PORT,
    )  # fmt: skip
    app = create_app(
        settings, PlexClient("http://192.168.1.3:32400", "token", transport=fp.transport())
    )
    with TestClient(app) as home:
        away_on(home)
        app.state.ctx.reach.transport = UnlistedProxy(app).transport
        found = home.post("/api/away/check").json()
        assert found["trustProxy"] == {"address": "192.168.1.3", "relay": False}
        assert trust(home).json()["state"] == "up"
        plex = TestClient(app, client=("192.168.1.3", 5), headers={"User-Agent": "PlexMediaServer"})
        for path in ("/discover.json", "/lineup.json", "/xmltv.xml"):
            assert plex.get(path).status_code == 200, path


def test_a_relay_saying_only_https_is_trusted_and_ready(app):
    """A proxy in another container that sends X-Forwarded-Proto but no
    visitor's address: listed, it's a proxy (not the relay itself), so its
    HTTPS is believed and the offer doesn't come back."""
    ctx = app.state.ctx
    with TestClient(app) as home:
        away_on(home)
        ctx.relays.found = lambda: {ipaddress.ip_address("172.17.0.1")}
        ctx.relays.refresh()
        ctx.reach.transport = UnlistedProxy(app, peer="172.17.0.1", names=False).transport
        assert home.post("/api/away/check").json()["trustProxy"]["address"] == "172.17.0.1"
        ready = trust(home, "172.17.0.1").json()
        assert ready["state"] == "up" and "trustProxy" not in ready


def test_the_click_checks_again_before_listing(app):
    """The proxy may have moved since the check (a container restarted):
    its old address, now maybe another device's, isn't listed."""
    ctx = app.state.ctx
    with TestClient(app) as home:
        away_on(home)
        ctx.reach.transport = UnlistedProxy(app).transport
        assert home.post("/api/away/check").json()["trustProxy"]["address"] == "192.168.1.3"
        ctx.reach.transport = UnlistedProxy(app, peer="192.168.1.4").transport
        moved = trust(home)
        assert moved.status_code == 409 and "isn't at that address now" in moved.json()["detail"]
        assert ctx.trusted.proxies == []
        assert home.get("/api/away").json()["reach"]["trustProxy"]["address"] == "192.168.1.4"
        # Trusted meanwhile (on the Access tab, say): the click just says how
        # it is now.
        ctx.reach.transport = UnlistedProxy(app).transport
        assert home.post("/api/away/check").json()["trustProxy"]["address"] == "192.168.1.3"
        ctx.trusted.save({"proxies": [{"network": "192.168.1.3"}]}, by=None)
        already = trust(home)
        assert already.status_code == 200 and already.json()["state"] == "up"
        assert [p["network"] for p in ctx.trusted.proxies] == ["192.168.1.3/32"]


def test_trusting_with_signing_in_off(app):
    """With signing in off, anyone at home may, by a home name (as every
    Admin setting then); never by another name, or from the internet."""
    ctx = app.state.ctx
    with TestClient(app, base_url="http://192.168.1.20:3310") as home:
        home.put("/api/away", json={"on": True, "address": "https://tv.example.com"})
        ctx.reach.transport = UnlistedProxy(app).transport
        assert home.post("/api/away/check").json()["trustProxy"]["address"] == "192.168.1.3"
        named = TestClient(app, base_url="http://tv.example.com:3310")
        assert trust(named).status_code == 403
        internet = TestClient(app, base_url=f"http://testserver:{PUBLIC_PORT}")
        assert trust(internet).status_code == 403
        assert ctx.trusted.proxies == []
        assert trust(home).status_code == 200
        assert [p["network"] for p in ctx.trusted.proxies] == ["192.168.1.3/32"]
