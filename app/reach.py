"""Whether StationPlay's apps can reach it from outside your home, at the
address set for watching away from home (see away.py). The Access tab, the
setup and the page's header show it, and the apps' Admin alerts will too:
Reach.status says what it is, in a sentence, and since when.

While watching away from home is on, StationPlay asks for itself at that
address, as an app away from home would: GET <address>/api/internal/reach,
with a random value it waits a minute for at most, the certificate checked,
no redirect followed, and 10 seconds at most. That address is open on both
ports, to anyone (see access.py). For a value a check is waiting for, it
answers that it's StationPlay, which port the request came in on, and
whether it came over HTTPS (as the reverse proxy says), and StationPlay
notes that; for anything else, it's 404. So a check knows it reached this
StationPlay, and how, not just that something answered.

It checks a few seconds after StationPlay starts, at once when the setting
is saved, every 5 minutes, and when an Admin chooses Check now. A check
finds one thing (a Finding): Ready (an https:// address reached the public
port over HTTPS, with sign-in on; an http:// one, a VPN's or the home
network's, reached StationPlay), or what's wrong: the reverse proxy points
at the home port, which never asks for a password; not over HTTPS; sign-in
is off; the name isn't found; the certificate; no HTTPS there; the proxy's
own error (it couldn't reach StationPlay); something else answering; a
redirect. Or it couldn't connect (or look up the name just then).

Some of those are problems wherever the check comes from: StationPlay's
own answer saying what's wrong, the proxy's error, a name that isn't found,
a certificate for this very name that has expired (or isn't valid yet, or
was revoked), and an https:// address on StationPlay's own port. The rest
may be the home's router: many don't let devices at home use the home's own
internet address (NAT loopback) and answer it themselves, with their own
sign-in page, certificate or redirect, or not at all, while apps away from
home still work. Those count only once a check from here has reached
StationPlay (since it started), which shows the router lets it through. A
DNS override in the router, pointing the name at the reverse proxy's
address at home, lets StationPlay check from here.

The apps have their say too: StationPlay notes when a signed-in app last
came in through the public port (access.py; main.py, for a station played
there). From both, one status:

  off         Watching away from home is off.
  checking    No result yet, or a problem found once and not yet confirmed.
  up          The latest check was Ready; or it found what may be the router
              (or couldn't look up the name), but an app came in through the
              public port in the last 15 minutes.
  down        Two checks in a row, at least a minute apart, found a problem
              that counts.
  cant-check  It found what may be the router (or couldn't look up the
              name), no check from here has reached StationPlay yet, and no
              app has come in lately: it can't tell from here.

One problem alone never makes it down: StationPlay checks again a minute
later. A line is logged when it goes down (with why) and when it's back,
and once when it can't check from here: never one for each check.

Media in the apps plays through the same address (see applibrary.py), so
Ready covers it too, with nothing more to check: the apps ask for it, and
their players for its programs, as they do for stations (through the same
proxy to the public port, over HTTPS, signed in, a program's own address
letting its player in). Ready says so while a library is shared.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import secrets
import socket
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.parse import urlsplit

import httpx

from . import __version__
from .access import REACH
from .away import port_problem

if TYPE_CHECKING:
    from .access import Access
    from .away import Away
    from .config import Settings

log = logging.getLogger(__name__)

WAIT_S = 10.0  # the longest a check waits for its answer
VALUE_S = 60.0  # the longest a check's value is waited for
VALUE_BYTES = 18
FIRST_S = 5.0  # the first check, after StationPlay starts
EVERY_S = 300.0
AGAIN_S = 60.0  # after a problem found once: checking again
APPS_S = 15 * 60.0  # an app that came in this recently shows apps get in

# The status.
OFF, CHECKING, UP, DOWN, CANT = "off", "checking", "up", "down", "cant-check"
# What a check finds.
READY = "ready"
WRONG_PORT, NOT_HTTPS, SIGN_IN_OFF = "wrong-port", "not-https", "sign-in-off"
NO_NAME, CERTIFICATE, NO_HTTPS = "no-name", "certificate", "no-https"
PROXY_ERROR, ELSEWHERE, REDIRECT = "proxy-error", "something-else", "redirect"
NO_CONNECT, NO_LOOKUP = "no-connect", "no-lookup"  # (these can't tell)
# A reverse proxy saying it couldn't reach what's behind it (and Cloudflare,
# in front of one).
PROXY_ERRORS = frozenset({502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530})
# Names only a VPN's or the home network's own DNS knows: Tailscale's
# (MagicDNS), and those kept for home networks.
LOCAL_NAMES = (".ts.net", ".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")
NOT_FOUND = frozenset(
    getattr(socket, n) for n in ("EAI_NONAME", "EAI_NODATA") if hasattr(socket, n)
)
# Why OpenSSL didn't accept a certificate (X509_V_ERR_...).
NOT_YET, EXPIRED, REVOKED = 9, 10, 23
WRONG_NAME = frozenset({62, 64})  # (a name, or an IP address)
SELF_SIGNED = frozenset({18, 19})
UNKNOWN_ISSUER = frozenset({2, 20, 21, 27})


@dataclass(frozen=True)
class Finding:
    """What a check found: its kind (READY, or what's wrong), a sentence or
    two for the page, a few words for summaries, and whether this
    StationPlay answered (which shows checks from here can reach it).

    A problem is `sure` when it's one wherever the check comes from.
    Otherwise it may be the home's router answering for the outside address
    (see _record), and `found` says what the address did, for a sentence:
    "answers with a self-signed certificate"."""

    kind: str
    detail: str
    short: str
    reached: bool = False
    sure: bool = False
    found: str = ""


@dataclass(frozen=True)
class Status:
    """Whether StationPlay's apps can reach it from outside, as the page
    shows it (and the apps' Admin alerts will)."""

    state: str  # OFF, CHECKING, UP, DOWN or CANT
    detail: str  # what it is, in a sentence or two
    short: str  # in a few words, for a summary: "Ready", "Wrong port"
    checked_ms: int | None  # when it was last checked (None: not yet)
    since_ms: int  # since when it's been what it is
    app_ms: int | None  # when an app last came in through the public port (None: not yet)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state, "detail": self.detail, "short": self.short,
            "checkedAt": self.checked_ms, "since": self.since_ms, "lastApp": self.app_ms,
        }  # fmt: skip


@dataclass
class _Waiting:
    """A check's value, waited for until `until` (on the clock): and once its
    request came, how (through the public port or not, over HTTPS or not)."""

    until: float
    seen: tuple[bool, bool] | None = None


class Reach:
    """Whether StationPlay's apps can reach it from outside (see the module's
    notes): what the checks found, and the status from them and the apps."""

    # In tests, what answers at the address (see tests/conftest.py).
    transport: httpx.AsyncBaseTransport | None = None
    # Whether Media is shared with the apps (it plays away from home too);
    # main.py sets this.
    media: Callable[[], bool] | None = None

    def __init__(
        self,
        away: Away,
        access: Access,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.away, self.access, self.settings, self.clock = away, access, settings, clock
        self._waiting: dict[str, _Waiting] = {}  # each check's value
        # The checks' loop (see run_forever), and how it's told to look again.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._due = clock() + FIRST_S  # when the next check is
        self._said_down = self._said_cant = False  # (what's been logged)
        self._forget()
        self._state, self._since_ms = self._state_now(), _now_ms()

    def _forget(self) -> None:
        """Starts afresh, with the address set now (if it's on)."""
        self._address = self.away.address if self.away.on else ""
        self._latest: Finding | None = None
        self._checked_at = 0.0  # (on the clock)
        self._checked_ms: int | None = None
        self._failures = 0  # checks in a row that found a problem
        self._failing_since = 0.0  # (the first of them, on the clock)
        self._reached = False  # whether a check from here has reached StationPlay

    # GET /api/internal/reach --------------------------------------------------

    def answer(self, value: str, outside: bool, https: bool) -> bool:
        """Whether `value` is one a check is waiting for; if it is, notes how
        its request came (`outside`: through the public port; `https`: over
        HTTPS, as the reverse proxy says)."""
        waiting = self._waiting.get(value)
        if waiting is None or self.clock() > waiting.until:
            return False
        waiting.seen = (outside, https)
        return True

    # Checking ------------------------------------------------------------------

    def saved(self) -> None:
        """Watching away from home was saved: it's checked at once (and a
        new address, or turning it on, starts afresh)."""
        self._settle()
        self._due = self.clock()
        self._wake_up()

    async def run_forever(self) -> None:
        """Checks when one is due: FIRST_S after StationPlay starts, then
        every EVERY_S (AGAIN_S after a problem found once), and at once when
        the setting is saved."""
        self._loop, self._wake = asyncio.get_running_loop(), asyncio.Event()
        self._due = max(self._due, self.clock() + FIRST_S)  # (once it's serving)
        while True:
            self._wake.clear()
            wait = self._due - self.clock()
            if wait > 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), wait)
                continue
            try:
                await self.check_now()
            except Exception:
                log.exception("Checking the address StationPlay's apps use away from home failed")
                self._due = self.clock() + EVERY_S

    async def check_now(self) -> Status:
        """Checks the address now (while watching away from home is on), and
        says the status after."""
        self._settle()
        address = self._address
        if not address:
            self._due = self.clock() + EVERY_S
            return self.status()
        value = secrets.token_urlsafe(VALUE_BYTES)
        waiting = self._waiting[value] = _Waiting(self.clock() + VALUE_S)
        try:
            finding = await self._look(address, value, waiting)
        finally:
            del self._waiting[value]
        self._settle()
        if address == self._address:  # (not if it changed meanwhile)
            self._record(finding)
        return self.status()

    def _record(self, finding: Finding) -> None:
        now = self.clock()
        # What may be the router counts only once a check from here has
        # reached StationPlay: the router lets checks from here through, then.
        problem = finding.kind not in (READY, NO_LOOKUP) and (finding.sure or self._reached)
        self._reached = self._reached or finding.reached
        if problem and not self._failures:
            self._failing_since = now
        self._failures = self._failures + 1 if problem else 0
        self._latest, self._checked_at, self._checked_ms = finding, now, _now_ms()
        self._due = now + (AGAIN_S if problem and not self._confirmed() else EVERY_S)
        self._wake_up()
        self._settle()

    def _confirmed(self) -> bool:
        """Whether the problems found count: two checks in a row, at least a
        minute apart, found one."""
        return self._failures >= 2 and self._checked_at - self._failing_since >= AGAIN_S

    def _wake_up(self) -> None:
        """Has the checks' loop look again at when the next check is due."""
        loop, wake = self._loop, self._wake
        if loop is None or wake is None:
            return
        try:
            here: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            here = None
        if here is loop:
            wake.set()
        else:
            with contextlib.suppress(RuntimeError):  # (its loop has closed)
                loop.call_soon_threadsafe(wake.set)

    # The status ----------------------------------------------------------------

    def status(self) -> Status:
        """What it is now: its state, a sentence or two, and since when."""
        self._settle()
        detail, short = self._words()
        app = self.access.app_outside_at
        app_ms = None if app is None else _now_ms() - int((self.clock() - app) * 1000)
        return Status(self._state, detail, short, self._checked_ms, self._since_ms, app_ms)

    def _settle(self) -> None:
        """Brings the state up to date (the setting may have changed, or an
        app's visit grown old), logging a change that matters."""
        if self._address != (self.away.address if self.away.on else ""):
            self._forget()
            self._said_cant = False
        state = self._state_now()
        if state == self._state:
            return
        self._state, self._since_ms = state, _now_ms()
        if state == OFF:
            self._said_down = False
        elif state == DOWN and not self._said_down:
            self._said_down = True
            log.warning("StationPlay's apps can't reach it from outside. %s", self._words()[0])
        elif state == UP and self._said_down:
            self._said_down = False
            log.info("StationPlay's apps can reach it from outside again, at %s", self._address)
        elif state == CANT and not self._said_cant:
            self._said_cant = True
            log.info("%s", self._words()[0])

    def _state_now(self) -> str:
        latest = self._latest
        if not self._address:
            return OFF
        if latest is None:
            return CHECKING
        if latest.kind == READY:
            return UP
        if not latest.sure and self._app_lately():
            return UP
        if self._confirmed():
            return DOWN
        return CHECKING if self._failures else CANT

    def _app_lately(self) -> bool:
        """Whether an app came in through the public port within APPS_S."""
        at = self.access.app_outside_at
        return at is not None and self.clock() - at <= APPS_S

    def _words(self) -> tuple[str, str]:
        """The status in a sentence or two, and in a few words."""
        state, latest, address = self._state, self._latest, self._address
        if state == OFF or not address:
            return "Watching away from home is off.", "Off"
        if latest is None:
            return f"Checking that apps can reach StationPlay at {address}…", "Checking"
        if state == CHECKING:
            return f"{latest.detail} Checking again in a minute to be sure.", "Checking"
        if state == UP and latest.kind == READY:
            return latest.detail, latest.short
        if state == UP:
            if latest.kind == NO_CONNECT:
                from_here = (
                    "Checking from here couldn't connect, which is common: many routers don't "
                    "let devices at home use the home's own internet address."
                )
            elif latest.kind == NO_LOOKUP:
                from_here = f"Checking from here couldn't look up {_host(address)}."
            else:
                from_here = (
                    f"From here, {address} {latest.found}: likely your router, answering for "
                    "your home's own internet address."
                )
            return (
                f"Apps away from home are reaching StationPlay. {from_here}",
                "Apps are getting in",
            )
        if state == DOWN and not latest.sure:
            return (
                f"{latest.detail} Checks from here got through earlier, so this isn't your "
                "router: apps away from home can't reach StationPlay either.",
                latest.short,
            )
        if state == DOWN:
            return latest.detail, latest.short
        return _cant_check(latest, address), "Can't check from here"

    # What a check finds -------------------------------------------------------

    async def _look(self, address: str, value: str, waiting: _Waiting) -> Finding:
        """Asks for this StationPlay at `address`, as an app away from home
        would, and says what that found."""
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=WAIT_S,
                follow_redirects=False,
                trust_env=False,  # (straight from here: no proxy the environment names)
                headers={"User-Agent": f"StationPlay/{__version__}"},
            ) as client:
                got = await asyncio.wait_for(
                    client.get(f"{address}{REACH}", params={"n": value}), WAIT_S
                )
        except (TimeoutError, httpx.TimeoutException):
            return _no_answer(f"Nothing answered at {address} within {WAIT_S:g} seconds.")
        except httpx.HTTPError as e:
            return self._failed(address, e)
        except (httpx.InvalidURL, ValueError):  # (a name it can't even ask for)
            return _no_answer(f"StationPlay couldn't connect to {address}.")
        if waiting.seen is not None and got.status_code == 200 and _from_stationplay(got):
            return await self._answered(address, *waiting.seen)
        return self._other(address, got)

    async def _answered(self, address: str, outside: bool, https: bool) -> Finding:
        """What a check that reached this StationPlay found (`outside`:
        through the public port; `https`: over HTTPS, as the proxy says)."""
        port, public = self.settings.port, self.settings.public_port
        secure = urlsplit(address).scheme == "https"
        if secure and not outside:
            detail = (
                f"Warning: your reverse proxy passes {address} to port {port}, StationPlay's "
                "home port. That's Plex's tuner, which never asks for a password, so it must "
                "never be reached from the internet. "
                + (
                    f"Point the proxy at StationPlay's public port, {public}, instead."
                    if public
                    else "Set PUBLIC_PORT (3311 in the YAML and Compose files), and point the "
                    "proxy at that port instead."
                )
            )
            return Finding(WRONG_PORT, detail, "Wrong port", reached=True, sure=True)
        if not secure and not await _local(_host(address)):
            # (An http:// address with a name on the internet.)
            if not outside:
                detail = (
                    f"Warning: {address} doesn't use HTTPS, so apps' sign-ins would cross the "
                    f"internet unencrypted, and it reaches port {port}, StationPlay's home port: "
                    "Plex's tuner, which never asks for a password. Use a reverse proxy with "
                    + (
                        f"HTTPS that points at StationPlay's public port, {public}, "
                        if public
                        else "HTTPS that points at StationPlay's public port (set PUBLIC_PORT), "
                    )
                    + "and its https:// address."
                )
            elif not https:
                detail = (
                    f"Warning: {address} doesn't use HTTPS. StationPlay takes apps from the "
                    "internet only over HTTPS, so they can't sign in there. Use your reverse "
                    "proxy's https:// address instead."
                )
            else:
                detail = (
                    f"Warning: {address} doesn't use HTTPS, so apps' sign-ins would cross the "
                    "internet unencrypted. Use your reverse proxy's https:// address instead."
                )
            return Finding(NOT_HTTPS, detail, "Not over HTTPS", reached=True, sure=True)
        if outside and not https:
            detail = (
                f"{address} reaches StationPlay's public port, but your reverse proxy doesn't "
                "say the request came over HTTPS, so StationPlay turns apps away there. Have the "
                "proxy send the X-Forwarded-Proto header."
                if secure
                else f"{address} reaches StationPlay's public port, which takes apps only over "
                f"HTTPS. Through a VPN, use the home port instead: {_with_port(address, port)}."
            )
            return Finding(NOT_HTTPS, detail, "Not over HTTPS", reached=True, sure=True)
        if outside and not self.access.required:
            detail = (
                f"{address} reaches StationPlay, but sign-in is off, so apps can't sign in "
                "through the public port. Add a user on the Access tab."
            )
            return Finding(SIGN_IN_OFF, detail, "Sign-in is off", reached=True, sure=True)
        detail = f"Ready. Apps away from home reach StationPlay at {address}" + (
            ", for your stations and Media." if self.media and self.media() else "."
        )
        return Finding(READY, detail, "Ready", reached=True)

    def _other(self, address: str, got: httpx.Response) -> Finding:
        """What a check found when something other than this StationPlay
        answered."""
        said = f"{got.status_code} {got.reason_phrase}".strip()
        found = (
            "answers with a page that isn't StationPlay's"
            if got.status_code == 200
            else f"answers with {said} instead of StationPlay's answer"
        )
        if got.is_redirect:
            return _redirect(address, got)
        if got.status_code in PROXY_ERRORS:
            public = self.settings.public_port
            where = (
                f"Check that it points at this server's public port, {public}."
                if public
                else "Check that it points at this server, at StationPlay's public port (set "
                "PUBLIC_PORT: 3311 in the YAML and Compose files)."
            )
            detail = (
                f"The reverse proxy at {address} answered with an error ({said}): it couldn't "
                f"reach StationPlay. {where}"
            )
            return Finding(PROXY_ERROR, detail, "Proxy error", sure=True)
        if got.status_code in (401, 403):
            detail = (
                f"Something in front of StationPlay turned the check away at {address} "
                f"({said}), such as an access list or a sign-in in your reverse proxy. Apps "
                "can't get past it: let this address through to StationPlay."
            )
            return Finding(ELSEWHERE, detail, "Blocked", found=found)
        what = "with a page that isn't StationPlay's" if got.status_code == 200 else said
        detail = (
            f"Something other than this StationPlay answered at {address} ({what}). Check "
            "that the address leads to this StationPlay, through your reverse proxy if you "
            "use one."
        )
        return Finding(ELSEWHERE, detail, "Something else answered", found=found)

    def _failed(self, address: str, e: httpx.HTTPError) -> Finding:
        """What a check found when nothing answered (never with what the
        error says itself, which can name addresses)."""
        host = _host(address)
        if (lookup := _cause(e, socket.gaierror)) is not None:
            if lookup.errno not in NOT_FOUND:
                return Finding(
                    NO_LOOKUP,
                    f"StationPlay couldn't look up {host} just now, so it can't check the "
                    "address from here.",
                    "Couldn't look up the name",
                )
            if _local_name(host):
                return Finding(
                    NO_LOOKUP,
                    f"StationPlay couldn't look up {host}. Names like it, on a VPN (such as "
                    "Tailscale's) or a home network, often work only on the devices there, so "
                    "StationPlay can't check the address from here.",
                    "Couldn't look up the name",
                )
            detail = (
                f"The name {host} isn't found. Check the address for typos, and that your "
                f"domain's DNS points {host} at your home's internet address."
            )
            return Finding(NO_NAME, detail, "Name not found", sure=True)
        if (unaccepted := _cause(e, ssl.SSLCertVerificationError)) is not None:
            return _certificate(address, host, unaccepted)
        if _cause(e, ssl.SSLError) is not None:
            problem = port_problem(address, self.settings.port, self.settings.public_port)
            detail = f"{address} doesn't answer over HTTPS. " + (
                problem or "Check that the address leads to your reverse proxy."
            )
            # (An https:// address on StationPlay's own port is wrong from anywhere.)
            found = "doesn't answer over HTTPS"
            return Finding(NO_HTTPS, detail, "No HTTPS there", sure=bool(problem), found=found)
        if _cause(e, ConnectionRefusedError) is not None:
            return _no_answer(f"Nothing answered at {address}: the connection was refused.")
        if isinstance(e, httpx.ConnectError):
            return _no_answer(f"StationPlay couldn't connect to {address}.")
        return _no_answer(f"{address} closed the connection without answering.")


def _cant_check(latest: Finding, address: str) -> str:
    """Why it can't check from here, in a few sentences: what it found,
    what that may be, and how to be sure."""
    host = _host(address)
    if latest.kind == NO_LOOKUP:
        return latest.detail  # (a name it couldn't look up says so itself)
    found = latest.detail if latest.kind == NO_CONNECT else f"From here, {address} {latest.found}."
    if _looks_local(host):
        return (
            f"{found} That can be a real problem, or this server may not reach that address "
            "itself, in which case apps on your VPN still work. StationPlay can't tell "
            f"which from here: to be sure, open {address} on a phone on the VPN, using "
            "mobile data."
        )
    maybe = (
        "That can be a real outage, or a router that doesn't let devices at home use your "
        "home's own internet address (called NAT loopback), in which case apps away from "
        "home still work. StationPlay can't tell which from here."
        if latest.kind == NO_CONNECT
        else "That's likely your router itself: many routers answer for your home's own "
        "internet address when it's used from inside your home, while apps away from home "
        "still work."
    )
    return (
        f"{found} {maybe} To be sure, open {address} on a phone using mobile data, not "
        "Wi-Fi. So StationPlay can check from here, add a DNS override in your router that "
        f"points {host} at your reverse proxy's address on your home network."
    )


def _no_answer(detail: str) -> Finding:
    return Finding(NO_CONNECT, detail, "Couldn't connect")


def _certificate(address: str, host: str, unaccepted: ssl.SSLCertVerificationError) -> Finding:
    """What a check found when the certificate wasn't accepted: why, from
    the error (OpenSSL's reason, or failing that, its words). OpenSSL checks
    who issued a certificate and the name it's for first, so one found
    expired, not valid yet or revoked is a trusted one for this very name:
    not the router's."""
    code = getattr(unaccepted, "verify_code", None)
    words = str(getattr(unaccepted, "verify_message", None) or unaccepted).lower()
    trust = "Use a certificate from Let's Encrypt in your reverse proxy."
    if code == EXPIRED or (code is None and "expired" in words):
        detail = f"The HTTPS certificate for {host} has expired. Renew it in your reverse proxy."
        return Finding(CERTIFICATE, detail, "Certificate expired", sure=True)
    if code == NOT_YET or (code is None and "not yet valid" in words):
        detail = (
            f"The HTTPS certificate for {host} isn't valid yet. Check the date and time on "
            "this server and on your reverse proxy's."
        )
        return Finding(CERTIFICATE, detail, "Certificate not valid yet", sure=True)
    if code in WRONG_NAME or (code is None and "mismatch" in words):
        detail = (
            f"The HTTPS certificate at {address} is for another name, not {host}. Get one for "
            f"{host} in your reverse proxy."
        )
        found = "answers with a certificate for another name"
        return Finding(CERTIFICATE, detail, "Certificate for another name", found=found)
    if code in SELF_SIGNED or (code is None and ("self-signed" in words or "self signed" in words)):
        detail = (
            f"The HTTPS certificate at {address} isn't trusted: it's self-signed, so apps "
            f"won't connect. {trust}"
        )
        found = "answers with a self-signed certificate"
        return Finding(CERTIFICATE, detail, "Certificate not trusted", found=found)
    if code in UNKNOWN_ISSUER or (code is None and "issuer" in words):
        detail = (
            f"The HTTPS certificate at {address} isn't trusted: devices don't know who issued "
            f"it (or the proxy doesn't send the whole chain), so apps won't connect. {trust}"
        )
        found = "answers with a certificate devices don't trust"
        return Finding(CERTIFICATE, detail, "Certificate not trusted", found=found)
    if code == REVOKED or (code is None and "revoked" in words):
        detail = f"The HTTPS certificate for {host} has been revoked. {trust}"
        return Finding(CERTIFICATE, detail, "Certificate revoked", sure=True)
    detail = f"The HTTPS certificate at {address} wasn't accepted, so apps won't connect. {trust}"
    found = "answers with a certificate that isn't accepted"
    return Finding(CERTIFICATE, detail, "Certificate problem", found=found)


def _redirect(address: str, got: httpx.Response) -> Finding:
    """What a check found when it was sent somewhere else: where, and (when
    it's StationPlay's own address there, over HTTPS) that the address
    should be that one."""
    try:
        to = got.url.join(got.headers["location"])
        there = _origin(to)
    except (httpx.InvalidURL, ValueError):
        detail = (
            f"{address} redirects somewhere else instead of reaching StationPlay. Apps can't "
            "follow that: the address must reach StationPlay itself."
        )
        return Finding(REDIRECT, detail, "Redirected", found="redirects somewhere else")
    if to.path == REACH and (to.scheme == "https" or urlsplit(address).scheme == "http"):
        shown = there
        detail = f"{address} redirects to {there}. Use {there} as the address instead."
    else:
        shown = there + (to.path[:80] if to.path not in ("", "/") else "")
        detail = (
            f"{address} redirects to {shown} instead of reaching StationPlay (a sign-in page, "
            "perhaps). Apps can't follow that: the address must reach StationPlay itself."
        )
    return Finding(REDIRECT, detail, "Redirected", found=f"redirects to {shown}")


def _from_stationplay(got: httpx.Response) -> bool:
    """Whether an answer is StationPlay's, from GET /api/internal/reach."""
    try:
        body = got.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("stationplay") is True


_E = TypeVar("_E", bound=BaseException)


def _cause(e: BaseException, kind: type[_E]) -> _E | None:
    """The error of `kind` behind `e` (or `e` itself), if there's one."""
    seen: set[int] = set()
    at: BaseException | None = e
    while at is not None and id(at) not in seen:
        if isinstance(at, kind):
            return at
        seen.add(id(at))
        at = at.__cause__ or at.__context__
    return None


def _host(address: str) -> str:
    return urlsplit(address).hostname or ""


def _with_port(address: str, port: int) -> str:
    """`address` on another port."""
    parts = urlsplit(address)
    host = parts.hostname or ""
    return f"{parts.scheme}://{f'[{host}]' if ':' in host else host}:{port}"


def _origin(url: httpx.URL) -> str:
    """An address's scheme, host and port (if it isn't the usual one)."""
    host = f"[{url.host}]" if ":" in url.host else url.host
    return f"{url.scheme}://{host}" + (f":{url.port}" if url.port else "")


def _local_name(host: str) -> bool:
    """Whether a name is one only a VPN's or the home network's own DNS
    knows."""
    name = host.lower().rstrip(".")
    return "." not in name or name.endswith(LOCAL_NAMES)


def _looks_local(host: str) -> bool:
    """Whether a host is a VPN's or the home network's by how it looks: an
    address no one on the internet can reach, or a name only their own DNS
    knows."""
    with contextlib.suppress(ValueError):
        return not ipaddress.ip_address(host).is_global
    return _local_name(host)


async def _local(host: str) -> bool:
    """Whether a host is a VPN's or the home network's: by how it looks, or
    for a name, when it leads only to such addresses. (Unknown, it counts as
    theirs: nothing is said without reason.)"""
    if _looks_local(host):
        return True
    try:
        found = await _addresses(host)
    except OSError:
        return True
    return not any(_global(a) for a in found)


async def _addresses(host: str) -> list[str]:
    """The addresses a name leads to, from here."""
    found = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(a[4][0]) for a in found]


def _global(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%")[0]).is_global
    except ValueError:
        return False


def _now_ms() -> int:
    return int(time.time() * 1000)
