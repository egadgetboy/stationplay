"""Alert notifications: tapiOca posts to up to 3 web addresses when an
Admin alert starts and when it's fixed (see alerts.py), for ntfy, Gotify,
Home Assistant, Discord, Slack and the like. An Admin's setting, off to
start, on the Logs tab: one switch for them all, and a format for each.

The addresses are the Admin's own: tapiOca sends only this there, and
contacts nothing else on its own. Each is http or https only. For each one,
tapiOca waits 5 seconds for an answer, tries once more when there's no
good one, follows no redirect, and keeps nothing of the answer but its
status (for the page's "Last sent", kept only for an address that's saved:
a test of one typed but not saved keeps nothing). Sending never holds
anything else up: each message goes to every address, in the background,
and each address gets its messages one at a time, in a line of its own, by
the address, so one that fails (or is slow) never holds up or changes the
others, even as the list changes. The addresses are shown to Admins only,
and never written to the logs whole (they can carry a token): only their
hosts are.

An alert counts as told (see alerts.py's untold) once any address takes it,
so an address that's down never has the others told it again after a
restart; it's untold when none takes it.

Four formats: plain text (the message, with a Title header, as ntfy takes
it); JSON, for Gotify, Home Assistant and others: {"title": "tapiOca",
"message": "...", "kind": "...", "state": "started" or "fixed"}; Discord's
own: {"username": "tapiOca", "content": "...", "allowed_mentions":
{"parse": []}, "flags": 4} (the message with what Discord's markdown reads,
such as ** or a link, written as text, so a station's name shows as it is;
cut to Discord's 2000 characters; never pinging anyone; and no link
previews, flag 4); and Slack's: {"text": "..."} (with &, < and > written the
way Slack asks, so it never pings anyone either), which Mattermost and
Rocket.Chat take too. A Discord webhook's address always gets Discord's
format, and one on hooks.slack.com Slack's, whichever was chosen: they
refuse the others (400 Bad Request).

Kept as before 1.34.0, so an older tapiOca still notifies the first
address: META ({"on", "url", "format"}: the switch and the first address)
and LAST_META (how the first address's last message went). The others are
kept apart: META_MORE ([{"url", "format"}]) and LAST_MORE ({url: how its
last message went}). (An older tapiOca sends a first address set to
Slack plain text.)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from . import __version__

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TypeAlias

    from .db import Database

    Done: TypeAlias = Callable[[], None] | None  # (see Notify.send)

log = logging.getLogger(__name__)

META = "notify"  # the switch and the first address, as JSON: {"on", "url", "format"}
LAST_META = "notify_last"  # how the first address's last one went, as JSON (see Sent)
META_MORE = "notify_more"  # the other addresses, as JSON: [{"url", "format"}]
LAST_MORE = "notify_more_last"  # how each other address's last one went: {url: Sent}
TEXT, JSON, DISCORD, SLACK = "text", "json", "discord", "slack"
FORMATS = (TEXT, JSON, DISCORD, SLACK)
FORMAT_NAMES = {TEXT: "plain text", JSON: "JSON", DISCORD: "Discord", SLACK: "Slack"}
CHOOSE_FORMAT = "Choose a format: ntfy or plain text, JSON, Discord or Slack."
ADDRESSES_MOST = 3
TOO_MANY = f"tapiOca can send alerts to {ADDRESSES_MOST} web addresses at most."
TWICE = "Each web address can be listed only once."
# Discord: its webhooks' sites and addresses, and the longest message it takes.
DISCORD_HOSTS = frozenset({
    "discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com",
    "ptb.discordapp.com", "canary.discordapp.com",
})  # fmt: skip
DISCORD_PATH = re.compile(r"/api/(?:v\d+/)?webhooks/")
DISCORD_MOST = 2000
DISCORD_NO_PREVIEWS = 4  # (Discord's SUPPRESS_EMBEDS flag)
# What Discord's markdown reads: bold and the like, masked links, quotes,
# headings, lists, mentions and spoilers. (A web address is left as it is, so
# it still works, up to the first of them in it.)
DISCORD_MARKDOWN = re.compile(r"([\\*_`~|>\[\]()#<@\-])")
DISCORD_LINK = re.compile(r"https?://[^\s<>*_~`|()\[\]\\]+")
SLACK_HOSTS = frozenset({"hooks.slack.com"})  # (Slack's incoming webhooks)
ADDRESS_MAX = 500
WAIT_S = 5.0  # the longest an answer is waited for
AGAIN_S = 2.0  # before the one more try
WAITING_MOST = 50  # messages waiting to go, at most (more are left out, and said)
TITLE = "tapiOca"
STARTED, FIXED, TEST = "started", "fixed", "test"
TEST_MESSAGE = "A test from tapiOca: its alerts will come here."
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


def _sent(got: Any) -> Sent | None:
    try:
        return Sent(int(got["at"]), str(got["status"]), bool(got["ok"]), bool(got["test"]))
    except (ValueError, TypeError, KeyError):
        return None


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


def is_discord(url: str) -> bool:
    """Whether `url` is a Discord webhook's address."""
    try:
        parsed = httpx.URL(url.strip())
    except httpx.InvalidURL:
        return False
    return parsed.host.lower() in DISCORD_HOSTS and bool(DISCORD_PATH.match(parsed.path))


def is_slack(url: str) -> bool:
    """Whether `url` is on Slack's webhooks' site."""
    try:
        parsed = httpx.URL(url.strip())
    except httpx.InvalidURL:
        return False
    return parsed.host.lower() in SLACK_HOSTS


def format_for(url: str, fmt: str) -> str:
    """The format a message to `url` goes in: Discord's, for a Discord
    webhook, and Slack's, for a Slack one (they refuse the others);
    otherwise `fmt`."""
    return DISCORD if is_discord(url) else SLACK if is_slack(url) else fmt


def slack_text(message: str) -> str:
    """A message as Slack takes it: &, < and > written as Slack asks, so
    nothing in it is read as a link or a mention (such as <!channel>)."""
    return message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def discord_text(message: str) -> str:
    """A message as Discord shows it as it is: each character its markdown
    reads written as itself (with a \\ before it), but for web addresses,
    cut to Discord's 2000 characters, never in the middle of one so
    written."""
    parts, at = [], 0
    for link in DISCORD_LINK.finditer(message):
        parts += [DISCORD_MARKDOWN.sub(r"\\\1", message[at : link.start()]), link.group(0)]
        at = link.end()
    text = "".join([*parts, DISCORD_MARKDOWN.sub(r"\\\1", message[at:])])
    if len(text) > DISCORD_MOST:
        text = text[:DISCORD_MOST]
        if (len(text) - len(text.rstrip("\\"))) % 2:
            text = text[:-1]  # (half of one written as itself)
    return text


def shown(url: str) -> str:
    """An address as the log may show it: its scheme and host, never the
    rest (a path or query can carry a token)."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        return "the address"
    host = f"[{parsed.host}]" if ":" in parsed.host else parsed.host
    return f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "")


class _Message:
    """One message on its way to every address, and what's said of it:
    `done` once any address takes it; `failed` if none does, or if
    tapiOca stops before one does. (Left out of an address, as it's no
    longer one or too many wait there, counts neither way.)"""

    __slots__ = ("done", "failed", "kind", "left", "message", "missed", "over", "state")

    def __init__(self, message: str, kind: str, state: str, done: Done, failed: Done) -> None:
        self.message, self.kind, self.state = message, kind, state
        self.done, self.failed = done, failed
        self.left = 0  # addresses it's still on its way to
        self.missed = False  # an address didn't take it
        self.over = False  # done or failed was said (or neither will be)

    def went(self, ok: bool | None) -> None:
        """One address is through with it: it took it (True), it didn't
        (False), or it was left out (None)."""
        self.left -= 1
        if self.over:
            return
        if ok:
            self.over = True
            if self.done is not None:
                self.done()
            return
        self.missed = self.missed or ok is False
        if self.left <= 0:
            self.over = True
            if self.missed and self.failed is not None:
                self.failed()

    def stopped(self) -> None:
        """tapiOca stops before any address took it."""
        if not self.over:
            self.over = True
            if self.failed is not None:
                self.failed()


class Notify:
    """The web addresses to notify, and sending to them (see the module's
    notes)."""

    # In tests, what answers at the addresses.
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
        self.format: str = format_for(
            self.url, saved["format"] if saved.get("format") in FORMATS else TEXT
        )
        self.more: list[tuple[str, str]] = self._saved_more()
        self._waiting: asyncio.Queue[_Message] | None = None
        self._waiting_full = False  # (said once)
        # Each address's own, by the address (never its place on the list,
        # which changes): what waits to go there, what sends it, what's
        # being sent there now, and whether its being too full was said.
        self._queues: dict[str, asyncio.Queue[_Message]] = {}
        self._senders: dict[str, asyncio.Task[None]] = {}
        self._sending: dict[str, _Message] = {}
        self._said_full: set[str] = set()

    def _saved_more(self) -> list[tuple[str, str]]:
        """The other addresses, as kept (any that won't do left out)."""
        try:
            saved = json.loads(self.db.get_meta(META_MORE, "") or "[]")
        except ValueError:
            saved = []
        found: list[tuple[str, str]] = []
        for one in saved if isinstance(saved, list) else []:
            if not isinstance(one, dict) or len(found) >= ADDRESSES_MOST - 1:
                continue
            try:
                url = check_address(str(one.get("url") or ""))
            except ValueError:
                continue
            if url == self.url or any(url == u for u, _ in found):
                continue
            fmt = one["format"] if one.get("format") in FORMATS else TEXT
            found.append((url, format_for(url, fmt)))
        return found

    def addresses(self) -> list[tuple[str, str]]:
        """Each address to notify, with its format: the first, then the
        others."""
        return [*([(self.url, self.format)] if self.url else []), *self.more]

    @property
    def last(self) -> Sent | None:
        """How the first address's last message (or test) went, if one has
        gone."""
        try:
            return _sent(json.loads(self.db.get_meta(LAST_META, "") or "null"))
        except ValueError:
            return None

    def _more_last(self) -> dict[str, Any]:
        try:
            got = json.loads(self.db.get_meta(LAST_MORE, "") or "{}")
        except ValueError:
            return {}
        return got if isinstance(got, dict) else {}

    def last_of(self, url: str) -> Sent | None:
        """How the last message (or test) to one of the other addresses
        went, if one has gone."""
        return _sent(self._more_last().get(url))

    def save(self, on: bool, url: str, fmt: str, more: list[tuple[str, str]] | None = None) -> None:
        """The setting: on or off, the first address and its format, and the
        others (None: as they are; an empty address: none there). Each is
        checked (see check_address), and listed once, and there are
        ADDRESSES_MOST at most. ValueError, with a sentence, if that won't
        do."""
        if fmt not in FORMATS:
            raise ValueError(CHOOSE_FORMAT)
        given = [(url, fmt), *(self.more if more is None else more)]
        kept: list[tuple[str, str]] = []
        for n, (one, its) in enumerate(given, 1):
            one = one.strip()
            if not one:
                continue
            if its not in FORMATS:
                raise ValueError(CHOOSE_FORMAT)
            try:
                one = check_address(one)
            except ValueError as e:
                raise ValueError(f"Web address {n}: {e}" if n > 1 else str(e)) from None
            if any(one == u for u, _ in kept):
                raise ValueError(TWICE)
            kept.append((one, format_for(one, its)))
        if len(kept) > ADDRESSES_MOST:
            raise ValueError(TOO_MANY)
        if on and not kept:
            raise ValueError(NOT_HTTP)
        # (The first place left blank: the others move up.)
        first_url, first_fmt = kept[0] if kept else ("", fmt)
        self._keep_lasts(first_url, [u for u, _ in kept[1:]])
        self.on, self.url, self.format, self.more = on, first_url, first_fmt, kept[1:]
        self.db.set_meta(META, json.dumps({"on": on, "url": first_url, "format": first_fmt}))
        self.db.set_meta(META_MORE, json.dumps([{"url": u, "format": f} for u, f in self.more]))

    def _keep_lasts(self, first: str, more: list[str]) -> None:
        """How each address's last message went, kept with it as the list
        changes: one moving to or from the first place takes its own along."""
        known = self._more_last()
        first_last = self.db.get_meta(LAST_META, "") or ""
        if first and first != self.url and first in known:
            self.db.set_meta(LAST_META, json.dumps(known[first]))
        elif first != self.url and self.url in more:
            self.db.set_meta(LAST_META, "")  # (a new first: nothing sent to it yet)
        lasts = {}
        for url in more:
            if url in known:
                lasts[url] = known[url]
            elif url == self.url and first_last:
                with contextlib.suppress(ValueError):
                    lasts[url] = json.loads(first_last)
        self.db.set_meta(LAST_MORE, json.dumps(lasts))

    def send(
        self,
        message: str,
        kind: str,
        state: str,
        done: Callable[[], None] | None = None,
        failed: Callable[[], None] | None = None,
    ) -> None:
        """Sends a message to every address in the background, if it's on
        (never waiting: see run_forever, which sends them). `done` is called
        once an address takes it; `failed`, if none does, or if tapiOca
        stops before one does (see unsent)."""
        if not (self.on and self.addresses()) or self._waiting is None:
            return
        try:
            self._waiting.put_nowait(_Message(message, kind, state, done, failed))
            self._waiting_full = False
        except asyncio.QueueFull:
            if not self._waiting_full:
                self._waiting_full = True
                log.warning("Too many alerts are waiting to go out, so some were left out")

    async def run_forever(self) -> None:
        """Hands what's waiting to each address, which sends its own one at a
        time, for as long as tapiOca runs."""
        self._waiting = asyncio.Queue(WAITING_MOST)
        try:
            while True:
                self._hand_out(await self._waiting.get())
        finally:
            for task in self._senders.values():
                task.cancel()
            self._senders.clear()

    def _hand_out(self, message: _Message) -> None:
        """A message, to each address's own line (one too full leaves it
        out); and a line no longer needed, gone."""
        listed = [url for url, _ in (self.addresses() if self.on else [])]
        for url in [u for u in self._queues if u not in listed]:
            if self._queues[url].empty() and url not in self._sending:
                self._senders.pop(url).cancel()
                del self._queues[url]
                self._said_full.discard(url)
        going = []
        for url in listed:
            if url not in self._queues:
                self._queues[url] = asyncio.Queue(WAITING_MOST)
                self._senders[url] = asyncio.create_task(self._send_forever(url))
            if self._queues[url].full():
                if url not in self._said_full:
                    self._said_full.add(url)
                    log.warning(
                        "Too many alerts are waiting to go to %s, so some were left out",
                        shown(url),
                    )
                continue
            self._said_full.discard(url)
            going.append(url)
        message.left = len(going)
        for url in going:
            self._queues[url].put_nowait(message)

    async def _send_forever(self, url: str) -> None:
        """Sends what waits for one address, one at a time."""
        waiting = self._queues[url]
        while True:
            message = await waiting.get()
            fmt = dict(self.addresses()).get(url)
            if not self.on or fmt is None:
                message.went(None)  # (turned off, or that address removed, meanwhile)
                continue
            self._sending[url] = message
            try:
                sent = await self.post(url, fmt, message.message, message.kind, message.state)
            except Exception:
                log.exception("Notifying %s failed", shown(url))
                sent = None
            finally:
                self._sending.pop(url, None)
            if sent is not None and not sent.ok:
                log.warning("Couldn't notify %s of an alert: %s", shown(url), sent.status)
            message.went(sent is not None and sent.ok)

    def unsent(self) -> None:
        """As tapiOca stops: what no address took yet, being sent or
        still waiting, is said not to have been (each one's `failed`)."""
        left = list(self._sending.values())
        self._sending.clear()
        while self._waiting is not None and not self._waiting.empty():
            left.append(self._waiting.get_nowait())
        for waiting in self._queues.values():
            while not waiting.empty():
                left.append(waiting.get_nowait())
        for message in left:
            message.stopped()

    async def test(self, url: str, fmt: str) -> Sent:
        """Send a test: a message to `url` in `fmt`, now (the page waits for
        it). Its "Last sent" is kept with that address if it's saved (the
        first, or another, by the address, wherever it was typed on the
        page); for one not saved, nothing is kept."""
        if fmt not in FORMATS:
            raise ValueError(CHOOSE_FORMAT)
        url = check_address(url)
        return await self._post(url, fmt, TEST_MESSAGE, TEST, STARTED, True)

    async def post(
        self, url: str, fmt: str, message: str, kind: str, state: str, test: bool = False
    ) -> Sent:
        """Posts one message, trying once more if it doesn't go through, and
        keeps how it went (see test)."""
        return await self._post(url, fmt, message, kind, state, test)

    async def _post(
        self, url: str, fmt: str, message: str, kind: str, state: str, test: bool
    ) -> Sent:
        sent = await self._post_once(url, fmt, message, kind, state, test)
        if not sent.ok:
            await asyncio.sleep(AGAIN_S)
            sent = await self._post_once(url, fmt, message, kind, state, test)
        # (Kept only for a saved address, matched by the address: the first's
        # where 1.33.x keeps it, the others' apart.)
        if self.url and url == self.url:
            self.db.set_meta(LAST_META, json.dumps(sent.as_dict()))
        elif any(url == u for u, _ in self.more):
            now = {u for u, _ in self.more}
            lasts = {u: got for u, got in self._more_last().items() if u in now}
            lasts[url] = sent.as_dict()
            self.db.set_meta(LAST_MORE, json.dumps(lasts))
        return sent

    async def _post_once(
        self, url: str, fmt: str, message: str, kind: str, state: str, test: bool
    ) -> Sent:
        headers = {"User-Agent": f"StationPlay/{__version__}"}
        fmt = format_for(url, fmt)
        if fmt == DISCORD:
            body: dict[str, Any] = {
                "username": TITLE,
                "content": discord_text(message),
                "allowed_mentions": {"parse": []},
                "flags": DISCORD_NO_PREVIEWS,
            }
            content = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif fmt == SLACK:
            content = json.dumps({"text": slack_text(message)}).encode()
            headers["Content-Type"] = "application/json"
        elif fmt == JSON:
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
            return Sent(at, f"{said}: a redirect, which tapiOca doesn't follow", False, test)
        return Sent(at, said, 200 <= status < 300, test)


def _now_ms() -> int:
    return int(time.time() * 1000)
