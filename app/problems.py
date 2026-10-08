"""Problems StationPlay's apps run into, sent by the apps themselves as they
happen (not a person's report, which says what the app did lately: see
appapi.py): a station that didn't start or stopped playing, something from
the library that didn't play or stopped, playing that couldn't keep up, the
app closing unexpectedly.

Each one says which app, which version, and what kind of device (its model
and system), so an Admin can tell from the Logs tab whether a problem is one
device's, one kind of device's, or everyone's. The same problem from the
same device soon after counts on the same row, and each one is said once in
StationPlay's log. Kept 30 days, the newest 5,000 at most.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

from .db import Database
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
}
STATION_KINDS = ("station-failed", "station-stopped")

KEEP = 5000
KEEP_DAYS = 30
SAME_MS = 10 * 60_000  # the same problem again within this long counts on its row
# From one app on one device, at most this many in this long (the rest are left out).
MOST = 30
MOST_IN_S = 10 * 60
TEXT_MOST = 300
NAME_MOST = 120


class Refused(Exception):
    """Not taken, with a sentence saying why (and the HTTP status)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Sent:
    """What an app sends about one problem."""

    kind: str
    detail: str = ""
    station: int | None = None
    title: str = ""
    app: str = ""
    version: str = ""
    device: str = ""
    device_name: str = ""


def subject(kind: str, station: int | None, title: str) -> str:
    """What a problem was about, as the Logs tab says it."""
    if kind in STATION_KINDS or (kind == "kept-up" and station is not None and not title):
        return f"Station {station}" if station is not None else "A station"
    return title or "Something"


def label(kind: str, station: int | None, title: str) -> str:
    """ "Station 5 didn't start", "Northbound didn't play"."""
    return KINDS.get(kind, "A problem").format(what=subject(kind, station, title))


def device_kind(app: str, version: str, device: str) -> str:
    """ "StationPlay for Roku 0.5.0 on Roku Ultra 4850X, Roku OS 14.0"."""
    who = " ".join(p for p in (app or "An app", version) if p)
    return f"{who} on {device}" if device else who


class Problems:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._recent: dict[str, deque[float]] = {}
        self._forgot_ms = 0

    def note(self, sent: Sent, user_id: int | None, away: bool, address: str) -> None:
        """Keeps a problem an app sent (from `address`). Refused if it isn't one
        StationPlay knows, or the app has sent too many lately."""
        if sent.kind not in KINDS:
            raise Refused("That isn't a kind of problem StationPlay knows")
        if sent.station is not None and not 0 < sent.station < 1_000_000:
            raise Refused("That isn't a station's number")
        fields: dict[str, Any] = {
            "kind": sent.kind,
            "station": sent.station,
            "title": plain(sent.title)[:NAME_MOST],
            "detail": plain(sent.detail)[:TEXT_MOST],
            "app": plain(sent.app)[:NAME_MOST],
            "version": plain(sent.version)[:NAME_MOST],
            "device": plain(sent.device)[:NAME_MOST],
            "device_name": plain(sent.device_name)[:NAME_MOST],
            "user_id": user_id,
            "away": away,
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
        at = int(time.time() * 1000)
        self._forget_old(at)
        if self.db.add_problem(at, fields, at - SAME_MS, KEEP):
            what = label(fields["kind"], fields["station"], fields["title"])
            why = f": {fields['detail']}" if fields["detail"] else ""
            on = device_kind(fields["app"], fields["version"], fields["device"])
            named = f" ({fields['device_name']})" if fields["device_name"] else ""
            log.warning("Problem in %s%s: %s%s", on, named, what, why)

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
        groups: dict[tuple[str, int | None, str], list[dict[str, Any]]] = {}
        for row in self.db.problems_since(since):
            station = row["station"] if row["kind"] != "crashed" else None
            title = row["title"] if row["kind"] != "crashed" else row["app"]
            groups.setdefault((row["kind"], station, title), []).append(row)
        out = []
        for (kind, station, title), rows in groups.items():
            kinds: Counter[str] = Counter()
            for r in rows:
                kinds[device_kind(r["app"], r["version"], r["device"])] += r["times"]
            details = []
            for r in rows:  # (newest first)
                if r["detail"] and r["detail"] not in details:
                    details.append(r["detail"])
            people = {names.get(r["user_id"], "") for r in rows if r["user_id"] is not None}
            out.append(
                {
                    "kind": kind,
                    "label": label(kind, station, "" if kind == "crashed" else title),
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
                }
            )
        out.sort(key=lambda g: g["lastMs"], reverse=True)
        return {"days": days, "problems": out}
