"""Notify a web address: StationPlay posts there when an Admin alert starts
and when it's fixed (see alerts.py), for ntfy, Gotify, Home Assistant and
the like. An Admin's setting, off to start, on the Logs tab.

The address is the Admin's own: StationPlay sends only this there, and
contacts nothing else on its own. It's http or https only. StationPlay
waits 5 seconds for an answer, tries once more when there's no good one,
follows no redirect, and keeps nothing of the answer but its status (for
the page's "Last sent"). Sending never holds anything else up: messages go
one at a time, in the background, and one that fails changes nothing else.
The address is shown to Admins only, and never written to the logs whole
(it can carry a token): only its host is.

Two formats: plain text (the message, with a Title header, as ntfy takes
it), or JSON, for Gotify, Home Assistant and others:
{"title": "StationPlay", "message": "...", "kind": "...", "state":
"started" or "fixed"}.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from . import __version__

if TYPE_CHECKING:
    from .db import Database

log = logging.getLogger(__name__)

META = "notify"  # the setting, as JSON: {"on", "url", "format"}
LAST_META = "notify_last"  # how the last one went, as JSON (see Sent)
TEXT, JSON = "text", "json"
FORMATS = (TEXT, JSON)
FORMAT_NAMES = {TEXT: "plain text", JSON: "JSON"}
ADDRESS_MAX = 500
WAIT_S = 5.0  # the longest an answer is waited for
AGAIN_S = 2.0  # before the one more try
WAITING_MOST = 50  # messages waiting to go, at most (more are left out, and said)
TITLE = "StationPlay"
STARTED, FIXED, TEST = "started", "fixed", "test"
TEST_MESSAGE = "A test from StationPlay: its alerts will come here."
NOT_HTTP = (
    "Enter a web address that starts with http:// or https://, such as https://ntfy.sh/your-topic"
)


@dataclass(frozen=True)
class Sent:
    """How sending one went: when, the answer's status ("200 OK") or why
    there was none, whether it went through, and whether it was a test."""

    at_ms: int
    status: str
    ok: bool
    test: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"at": self.at_ms, "status": self.status, "ok": self.ok, "test": self.test}


def check_address(url: str) -> str:
    """A web address to notify, as it's kept; ValueError (with a sentence)
    if it isn't an http:// or https:// one."""
    url = url.strip()
    if not url or len(url) > ADDRESS_MAX or any(c.isspace() or not c.isprintable() for c in url):
        raise ValueError(NOT_HTTP)
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        raise ValueError(NOT_HTTP) from None
    if parsed.scheme not in ("http", "https") or not parsed.host:
        raise ValueError(NOT_HTTP)
    return url


def shown(url: str) -> str:
    """An address as the log may show it: its scheme and host, never the
    rest (a path or query can carry a token)."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        return "the address"
    host = f"[{parsed.host}]" if ":" in parsed.host else parsed.host
    return f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "")


class Notify:
    """The web address to notify, and sending to it (see the module's notes)."""

    # In tests, what answers at the address.
    transport: httpx.AsyncBaseTransport | None = None

    def __init__(self, db: Database) -> None:
        self.db = db
        try:
            saved = json.loads(db.get_meta(META, "") or "{}")
        except ValueError:
            saved = {}
        saved = saved if isinstance(saved, dict) else {}
        self.on = saved.get("on") is True
        self.url = str(saved.get("url") or "")
        self.format: str = saved["format"] if saved.get("format") in FORMATS else TEXT
        self._waiting: asyncio.Queue[tuple[str, str, str]] | None = None
        self._said_full = False

    @property
    def last(self) -> Sent | None:
        """How the last message (or test) went, if one has gone."""
        try:
            got = json.loads(self.db.get_meta(LAST_META, "") or "null")
            return Sent(int(got["at"]), str(got["status"]), bool(got["ok"]), bool(got["test"]))
        except (ValueError, TypeError, KeyError):
            return None

    def save(self, on: bool, url: str, fmt: str) -> None:
        """The setting: on or off, the address (checked: see check_address)
        and the format. ValueError, with a sentence, if that won't do."""
        if fmt not in FORMATS:
            raise ValueError("Choose Plain text or JSON")
        url = url.strip()
        if url or on:
            url = check_address(url)
        self.on, self.url, self.format = on, url, fmt
        self.db.set_meta(META, json.dumps({"on": on, "url": url, "format": fmt}))

    def send(self, message: str, kind: str, state: str) -> None:
        """Sends a message in the background, if it's on (never waiting:
        see run_forever, which sends them)."""
        if not (self.on and self.url) or self._waiting is None:
            return
        try:
            self._waiting.put_nowait((message, kind, state))
            self._said_full = False
        except asyncio.QueueFull:
            if not self._said_full:
                self._said_full = True
                log.warning(
                    "Too many alerts are waiting to go to %s, so some were left out",
                    shown(self.url),
                )

    async def run_forever(self) -> None:
        """Sends what's waiting, one at a time, for as long as StationPlay
        runs."""
        self._waiting = asyncio.Queue(WAITING_MOST)
        while True:
            message, kind, state = await self._waiting.get()
            if not (self.on and self.url):
                continue
            url = self.url
            try:
                sent = await self.post(url, self.format, message, kind, state)
            except Exception:
                log.exception("Notifying %s failed", shown(url))
                continue
            if not sent.ok:
                log.warning("Couldn't notify %s of an alert: %s", shown(url), sent.status)

    async def test(self, url: str, fmt: str) -> Sent:
        """Send a test: a message to `url` in `fmt`, now (the page waits
        for it)."""
        if fmt not in FORMATS:
            raise ValueError("Choose Plain text or JSON")
        return await self.post(check_address(url), fmt, TEST_MESSAGE, TEST, STARTED, test=True)

    async def post(
        self, url: str, fmt: str, message: str, kind: str, state: str, test: bool = False
    ) -> Sent:
        """Posts one message, trying once more if it doesn't go through, and
        keeps how it went."""
        sent = await self._post_once(url, fmt, message, kind, state, test)
        if not sent.ok:
            await asyncio.sleep(AGAIN_S)
            sent = await self._post_once(url, fmt, message, kind, state, test)
        self.db.set_meta(LAST_META, json.dumps(sent.as_dict()))
        return sent

    async def _post_once(
        self, url: str, fmt: str, message: str, kind: str, state: str, test: bool
    ) -> Sent:
        headers = {"User-Agent": f"StationPlay/{__version__}"}
        if fmt == JSON:
            body = {"title": TITLE, "message": message, "kind": kind, "state": state}
            content = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        else:
            content = message.encode()
            headers.update({"Content-Type": "text/plain; charset=utf-8", "Title": TITLE})
        at = _now_ms()
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=WAIT_S,
                follow_redirects=False,
                trust_env=False,  # (straight from here: no proxy the environment names)
            ) as client:
                asked = client.build_request("POST", url, content=content, headers=headers)
                got = await asyncio.wait_for(client.send(asked, stream=True), WAIT_S)
                # (Nothing of the answer is read, or kept, but its status.)
                status, reason = got.status_code, got.reason_phrase
                await got.aclose()
        except (TimeoutError, httpx.TimeoutException):
            return Sent(at, f"no answer within {WAIT_S:g} seconds", False, test)
        except httpx.HTTPError as e:
            # (Never what the error says itself, which can name the address.)
            why = "couldn't connect" if isinstance(e, httpx.ConnectError) else "the request failed"
            return Sent(at, why, False, test)
        said = f"{status} {reason}".strip()
        if 300 <= status < 400:
            return Sent(at, f"{said}: a redirect, which StationPlay doesn't follow", False, test)
        return Sent(at, said, 200 <= status < 300, test)


def _now_ms() -> int:
    return int(time.time() * 1000)
