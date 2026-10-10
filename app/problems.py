"""Problems StationPlay's apps run into, sent by the apps themselves as they
happen (not a person's report, which says what the app did lately: see
appapi.py): a station that didn't start or stopped playing, something from
the library that didn't play or stopped, playing that couldn't keep up, the
app closing unexpectedly, and (from 1.29.1) the app not reaching StationPlay
for a minute or more.

Each one says which app, which version, and what kind of device (its model
and system), so an Admin can tell from the Logs tab whether a problem is one
device's, one kind of device's, or everyone's. The same problem from the
same device soon after counts on the same row, and each one is said once in
StationPlay's log, as a warning, naming the station as the log does (see
playing.station). Kept 30 days, the newest 5,000 at most.

From 1.29.1 an app says when each happened (`at`): it keeps those it
couldn't send (StationPlay out of reach, say) and sends them once it's back.
Rows go by when each happened, so the oldest go first when there are too
many: a device sending a backlog can't push out what's newer. Each may come
with the app's last lines before it (its journal), kept with the newest
JOURNALS_KEPT; and the Logs tab says what the error codes the apps send
mean, in plain words (MEANINGS).

What an app says about playing that couldn't keep up ("kept-up") is also
why it went to a smaller version, and what it says about something from the
library that didn't play is why it asked for a converted copy, which the log
says as it does (see applibrary.py): kept a little while for that, in memory
only.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

from .db import Database
from .playing import ago, cap
from .playing import station as station_named
from .text import plain

log = logging.getLogger("stationplay.problems")

# What the apps send, and how the Logs tab says it ({what}: the station or title).
KINDS = {
    "station-failed": "{what} didn't start",
    "station-stopped": "{what} stopped playing",
    "library-failed": "{what} didn't play",
    "library-stopped": "{what} stopped playing",
    "kept-up": "{what} couldn't keep up, so a smaller version played",
    "crashed": "The app closed unexpectedly",
    "unreachable": "{what} couldn't reach StationPlay",
}
STATION_KINDS = ("station-failed", "station-stopped")
UNREACHABLE = "unreachable"
# What's said about why a smaller version played, and about something from
# the library that didn't play (why an app asked for a converted copy).
KEPT_UP = ("kept-up",)
FAILED_KINDS = ("library-failed", "library-stopped")

KEEP = 5000
KEEP_DAYS = 30
SAME_MS = 10 * 60_000  # the same problem again within this long counts on its row
# From one app on one device, at most this many in this long (the rest are left out).
MOST = 30
MOST_IN_S = 10 * 60
TEXT_MOST = 300
NAME_MOST = 120
SAID_KEPT_S = 300  # how long what an app said lately is kept (see said_lately)
# When one happened, as the app says: up to this long ago, or this far ahead
# (a device's clock a little off); otherwise when it came.
AT_PAST_MS = 7 * 86_400_000
AT_AHEAD_MS = 5 * 60_000
# The app's journal before one: its newest lines, this many bytes at most;
# kept with the newest JOURNALS_KEPT problems.
JOURNAL_MOST = 8 * 1024
JOURNALS_KEPT = 500
LASTED_MOST_MS = 30 * 86_400_000  # (an outage longer than this isn't believed)

# What the error codes the apps send mean, in plain words, for the Logs tab:
# Media3's (Android), Apple's (AVFoundation, Core Media and URL loading, as
# "<domain> <code>") and Roku's ("Roku error <code>"). Unknown codes say
# nothing more.
_CONVERTS = (
    " StationPlay makes a converted copy when the app asks for one (StationPlay for Android "
    "0.3.1 does)."
)
_SECURE = (
    "A secure (HTTPS) connection to StationPlay couldn't be made. Check the certificate of the "
    "reverse proxy in front of it."
)
MEANINGS: tuple[tuple[str, str], ...] = (
    (r"ERROR_CODE_DECODING_FAILED|AVFoundationErrorDomain -11821|AVErrorDecodeFailed",
     "The device couldn't decode the picture or sound of this file." + _CONVERTS),
    (r"ERROR_CODE_DECODER_INIT_FAILED|AVFoundationErrorDomain -11839",
     "The device's decoder for this file's picture or sound couldn't start, often because the "
     "file is more than it can handle, or another app is using it." + _CONVERTS),
    (r"ERROR_CODE_DECODER_QUERY_FAILED",
     "The device couldn't find out which decoders it has. Restarting the app or the device "
     "usually fixes this."),
    (r"ERROR_CODE_DECODING_FORMAT_EXCEEDS_CAPABILITIES",
     "This file's picture or sound is more than the device can play, such as a 4K or 10-bit "
     "picture on a device made for 1080p." + _CONVERTS),
    (r"ERROR_CODE_DECODING_FORMAT_UNSUPPORTED|AVFoundationErrorDomain -11833|Roku error -5",
     "The device doesn't play this file's picture or sound format." + _CONVERTS),
    (r"ERROR_CODE_AUDIO_TRACK_INIT_FAILED",
     "The device couldn't start the sound, often a surround format (such as Dolby Digital "
     "Plus) that its speakers, soundbar or receiver don't take." + _CONVERTS),
    (r"ERROR_CODE_BEHIND_LIVE_WINDOW",
     "Playing fell too far behind the live station, usually after waiting to load on a slow "
     "connection, so the app had to jump ahead."),
    (r"ERROR_CODE_IO_NETWORK_CONNECTION_FAILED|NSURLErrorDomain -100[3459]|Roku error -1",
     "The device lost its connection to StationPlay: its network dropped, or StationPlay "
     "couldn't be reached."),
    (r"ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT|NSURLErrorDomain -1001|Roku error -2",
     "StationPlay took too long to answer the device, often because of a slow or busy "
     "network."),
    (r"ERROR_CODE_IO_BAD_HTTP_STATUS|NSURLErrorDomain -1011|CoreMediaErrorDomain -12(938|660)",
     "StationPlay, or a reverse proxy in front of it, answered with an error. StationPlay's "
     "log around that time may say why."),
    (r"ERROR_CODE_PARSING_CONTAINER_(MALFORMED|UNSUPPORTED)|AVFoundationErrorDomain -1182[89]",
     "The device couldn't read the file: it may be damaged, or a kind of file the device "
     "doesn't handle." + _CONVERTS),
    (r"ERROR_CODE_PARSING_MANIFEST_(MALFORMED|UNSUPPORTED)|CoreMediaErrorDomain -12642",
     "The device couldn't read the playlist StationPlay sent it. If it keeps happening, "
     "StationPlay's log around that time may say why."),
    (r"NSURLErrorDomain -12(00|01|02|03|04|05|06)", _SECURE),
)  # fmt: skip
_MEANINGS = tuple((re.compile(rf"\b(?:{pattern})\b"), said) for pattern, said in MEANINGS)
# What an app says kept it from reaching StationPlay, and what that means.
TROUBLES: tuple[tuple[str, str], ...] = (
    ("No network on this device",
     "The device itself had no network (Wi-Fi off, or no signal), so StationPlay wasn't at "
     "fault."),
    ("StationPlay's address couldn't be found",
     "The device couldn't look up StationPlay's address (DNS). Check the address the app "
     "uses, and your DNS or reverse proxy."),
    ("StationPlay didn't answer",
     "Nothing answered at StationPlay's address: StationPlay, the server it's on, or the "
     "connection to it may have been down."),
    ("A secure connection couldn't be made", _SECURE),
    ("StationPlay answered with an error",
     "Something answered for StationPlay with an error, often a reverse proxy while "
     "StationPlay was stopped or starting."),
)  # fmt: skip
# How long it lasted, as an app may say it in its detail ("for 3 min 20 s").
_LASTED = re.compile(r"\bfor (?:(\d+) hr\b)? ?(?:(\d+) min\b)? ?(?:(\d+) s\b)?")


class Refused(Exception):
    """Not taken, with a sentence saying why (and the HTTP status)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Sent:
    """What an app sends about one problem: from 1.29.1, also when it
    happened (`at`, ms), its journal's last lines before it, and for
    `unreachable`, how long it lasted (`lasted_ms`)."""

    kind: str
    detail: str = ""
    station: int | None = None
    title: str = ""
    app: str = ""
    version: str = ""
    device: str = ""
    device_name: str = ""
    at: int | None = None
    journal: str = ""
    lasted_ms: int | None = None


def subject(kind: str, number: int | None, title: str, name: str = "") -> str:
    """What a problem was about, as the Logs tab says it (`name`: the
    station's; for `unreachable`, `title` is the device)."""
    if kind in STATION_KINDS or (kind == "kept-up" and number is not None and not title):
        return cap(station_named(number, name, mid=True)) if number is not None else "A station"
    if kind == UNREACHABLE:
        return title or "A device"
    return title or "Something"


def label(
    kind: str,
    number: int | None,
    title: str,
    name: str = "",
    lasted_ms: int = 0,
    trouble: str = "",
    times: int = 1,
) -> str:
    """ "Station 5, Cartoon Classics, didn't start", "Northbound didn't
    play", "Den couldn't reach StationPlay for 12 minutes · No network on
    this device" (for 40 minutes in all, `times` over 1)."""
    said = KINDS.get(kind, "A problem").format(what=subject(kind, number, title, name))
    if kind != UNREACHABLE:
        return said
    if lasted_ms:
        said += f" for {lasted(lasted_ms)}{' in all' if times > 1 else ''}"
    return f"{said} · {trouble}" if trouble else said


def lasted(ms: int) -> str:
    """How long, as the Logs tab says it: "12 minutes", "1 hour 5 minutes"."""
    whole = round(ms / 60_000)
    if whole < 1:
        return "less than a minute"
    hours, rest = divmod(whole, 60)
    parts = [(hours, "hour"), (rest, "minute")]
    return " ".join(f"{n} {word}{'' if n == 1 else 's'}" for n, word in parts if n)


def who_couldnt(device_name: str, device: str) -> str:
    """The device that couldn't reach StationPlay: its own name, or else
    its model ("Galaxy S23", from "Galaxy S23, Android 14")."""
    return device_name or device.split(",")[0].strip()


def trouble_of(detail: str) -> str:
    """The kind of trouble an app had reaching StationPlay, from its
    detail: one of TROUBLES as it said it ("StationPlay answered with an
    error (503)"), or else its first sentence."""
    for known, _ in TROUBLES:
        if detail.startswith(known):
            found = re.match(rf"{re.escape(known)}( \(\d{{3}}\))?", detail)
            return found.group(0) if found else known
    return detail.split(". ")[0].rstrip(".")


def lasted_in(detail: str) -> int:
    """How long an app says trouble lasted in its detail ("for 3 min 20
    s"), in ms; 0 if it doesn't say."""
    found = next((m for m in _LASTED.finditer(detail) if any(m.groups())), None)
    if found is None:
        return 0
    hours, minutes, seconds = (int(n or 0) for n in found.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000


def meanings(details: list[str], kind: str) -> list[str]:
    """What the error codes in what an app said mean, in plain words (and
    for `unreachable`, what its trouble means); none for codes not known."""
    out: list[str] = []
    for detail in details:
        found = [said for pattern, said in _MEANINGS if pattern.search(detail)]
        if kind == UNREACHABLE:
            found += [said for known, said in TROUBLES if detail.startswith(known)]
        out += [said for said in found if said not in out]
    return out


def cleaned_journal(text: str) -> str:
    """An app's journal as it's kept: each line plain, and its newest lines
    within JOURNAL_MOST bytes (a line cut short at the start is left out)."""
    raw = text[-JOURNAL_MOST:]  # (no more than that many bytes can be kept)
    lines = [plain(line) for line in raw.split("\n")]
    if len(raw) < len(text) and len(lines) > 1:
        lines = lines[1:]  # (cut short; but a newest line too long alone is kept, cut)
    joined = "\n".join(line for line in lines if line)
    data = joined.encode()
    if len(data) <= JOURNAL_MOST:
        return joined
    kept = data[-JOURNAL_MOST:].decode(errors="ignore")
    return kept.split("\n", 1)[1] if "\n" in kept else kept


def device_kind(app: str, version: str, device: str) -> str:
    """ "StationPlay for Roku 0.5.0 on Roku Ultra 4850X, Roku OS 14.0"."""
    who = " ".join(p for p in (app or "An app", version) if p)
    return f"{who} on {device}" if device else who


class Problems:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._recent: dict[str, deque[float]] = {}
        self._forgot_ms = 0
        self._said: dict[str, tuple[float, str, str]] = {}  # address -> (when, kind, what)

    def said_lately(self, address: str, within_s: float, kinds: tuple[str, ...]) -> str:
        """What an app at `address` last said, in the last `within_s`, about
        a problem of one of `kinds` ("" if nothing)."""
        when, kind, what = self._said.get(address, (0.0, "", ""))
        return what if kind in kinds and time.monotonic() - when <= within_s else ""

    def note(self, sent: Sent, user_id: int | None, away: bool, address: str) -> None:
        """Keeps a problem an app sent (from `address`). Refused if it isn't one
        StationPlay knows, or the app has sent too many lately."""
        if sent.kind not in KINDS:
            raise Refused("That isn't a kind of problem StationPlay knows")
        if sent.station is not None and not 0 < sent.station < 1_000_000:
            raise Refused("That isn't a station's number")
        unreachable = sent.kind == UNREACHABLE
        detail = plain(sent.detail)[:TEXT_MOST]
        lasted_ms = sent.lasted_ms if unreachable and sent.lasted_ms is not None else 0
        if unreachable and not 0 < lasted_ms <= LASTED_MOST_MS:
            lasted_ms = lasted_in(detail)  # (as the app said it, if it did)
        fields: dict[str, Any] = {
            "kind": sent.kind,
            # (Trouble reaching StationPlay is the device's, not a station's
            # or a title's.)
            "station": None if unreachable else sent.station,
            "title": "" if unreachable else plain(sent.title)[:NAME_MOST],
            "detail": detail,
            "app": plain(sent.app)[:NAME_MOST],
            "version": plain(sent.version)[:NAME_MOST],
            "device": plain(sent.device)[:NAME_MOST],
            "device_name": plain(sent.device_name)[:NAME_MOST],
            "user_id": user_id,
            "away": away,
            "journal": cleaned_journal(sent.journal),
            "lasted_ms": min(lasted_ms, LASTED_MOST_MS),
        }
        who = f"{address} {fields['app']} {fields['device_name']}"
        now = time.monotonic()
        times = self._recent.setdefault(who, deque())
        while times and now - times[0] > MOST_IN_S:
            times.popleft()
        if len(times) >= MOST:
            raise Refused("This app has sent a lot of problems lately. Try again later.", 429)
        times.append(now)
        for key in [k for k, v in self._recent.items() if not v or now - v[-1] > MOST_IN_S]:
            del self._recent[key]
        if sent.kind in KEPT_UP + FAILED_KINDS and fields["detail"]:
            self._said = {a: s for a, s in self._said.items() if now - s[0] <= SAID_KEPT_S}
            self._said[address] = (now, sent.kind, fields["detail"])
        now_ms = int(time.time() * 1000)
        at = sent.at if sent.at is not None else now_ms
        if not now_ms - AT_PAST_MS <= at <= now_ms + AT_AHEAD_MS:
            at = now_ms
        self._forget_old(now_ms)
        if self.db.add_problem(at, fields, SAME_MS, KEEP, JOURNALS_KEPT):
            number = fields["station"]
            channel = self.db.get_channel_by_number(number) if number is not None else None
            what = label(
                fields["kind"], number,
                who_couldnt(fields["device_name"], fields["device"]) if unreachable
                else fields["title"],
                channel.name if channel else "", fields["lasted_ms"], trouble_of(detail),
            )  # fmt: skip
            why = f": {detail}" if detail and not unreachable else ""
            on = device_kind(fields["app"], fields["version"], fields["device"])
            named = f" ({fields['device_name']})" if fields["device_name"] else ""
            # (Sent later, as an app does once it can: when it happened.)
            when = f" ({ago((now_ms - at) / 1000)})" if now_ms - at >= 90_000 else ""
            log.warning("Problem in %s%s: %s%s%s", on, named, what, why, when)

    def journal(self, problem_id: int) -> dict[str, Any] | None:
        """A problem's journal: what its app did before it (None if there's
        no such problem, or it has none)."""
        found = self.db.problem_journal(problem_id)
        if found is None:
            return None
        at, text = found
        return {"atMs": at, "lines": text.split("\n")}

    def _forget_old(self, now_ms: int) -> None:
        if now_ms - self._forgot_ms < 3_600_000:
            return
        self._forgot_ms = now_ms
        self.db.forget_problems(now_ms - KEEP_DAYS * 86_400_000)

    def forget(self) -> None:
        """An Admin's Clear: every problem is forgotten."""
        self.db.forget_problems()

    def summary(self, days: int, names: dict[int, str]) -> dict[str, Any]:
        """The problems of the last `days` days, for the Logs tab: each one
        with how often, on how many devices, for how many people, and on
        what kinds of device (`only`: all on one kind)."""
        since = int(time.time() * 1000) - days * 86_400_000
        stations = {c.number: c.name for c in self.db.list_channels()}
        # (Trouble reaching StationPlay is grouped by the device, and the
        # kind of trouble.)
        groups: dict[tuple[str, int | None, str, str], list[dict[str, Any]]] = {}
        for row in self.db.problems_since(since):
            kind = row["kind"]
            station = row["station"] if kind != "crashed" else None
            title, trouble = row["title"], ""
            if kind == "crashed":
                title = row["app"]
            elif kind == UNREACHABLE:
                title = who_couldnt(row["device_name"], row["device"])
                trouble = trouble_of(row["detail"])
            groups.setdefault((kind, station, title, trouble), []).append(row)
        out = []
        for (kind, station, title, trouble), rows in groups.items():
            kinds: Counter[str] = Counter()
            for r in rows:
                kinds[device_kind(r["app"], r["version"], r["device"])] += r["times"]
            details = []
            for r in rows:  # (newest first)
                if r["detail"] and r["detail"] not in details:
                    details.append(r["detail"])
            people = {names.get(r["user_id"], "") for r in rows if r["user_id"] is not None}
            journal = next((r for r in rows if r["has_journal"]), None)  # (the newest)
            out.append(
                {
                    "kind": kind,
                    "label": label(
                        kind,
                        station,
                        "" if kind == "crashed" else title,
                        stations.get(station, "") if station is not None else "",
                        sum(r["lasted_ms"] for r in rows),
                        trouble,
                        sum(r["times"] for r in rows),
                    ),
                    "station": station,
                    "title": title,
                    "times": sum(r["times"] for r in rows),
                    "devices": len({(r["app"], r["device_name"], r["device"]) for r in rows}),
                    "people": sorted(p for p in people if p),
                    "away": any(r["away"] for r in rows),
                    "firstMs": min(r["first_ms"] for r in rows),
                    "lastMs": max(r["last_ms"] for r in rows),
                    "on": [{"device": k, "times": n} for k, n in kinds.most_common()],
                    "only": len(kinds) == 1,
                    "details": details[:3],
                    "means": meanings(details[:3], kind),
                    "journal": journal["id"] if journal else None,
                }
            )
        out.sort(key=lambda g: g["lastMs"], reverse=True)
        return {"days": days, "problems": out}
