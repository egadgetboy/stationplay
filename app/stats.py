"""Viewing statistics for the Stats tab: how much each station is watched.

Each time someone stops watching a station, the viewing is kept (when it
started and ended), with what aired meanwhile: the seconds of each show or
movie, by day. Viewings shorter than MIN_VIEW_S (flicking past a station)
aren't kept.

StationPlay sees what Plex asks it for, not who's watching in Plex: several
people watching a station together in Plex (or Plex recording it) may be
one viewing. Who's watching comes from Plex itself (WhoWatches): while a
station has viewers, Plex is asked every POLL_S what it's playing to whom,
and each Live TV session is matched to the one station airing what it
shows (watching.py); the time counts for that Plex user, station, and show
or movie. A session that can't be told apart (two stations airing the same
thing at once) counts for no one, and watching through other apps isn't
seen. The same look stops what's kept from some Plex users (limits.py).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request

from . import access, limits
from .plex import PlexError
from .watching import session_station, user_of

if TYPE_CHECKING:
    from .db import Database, Item
    from .main import AppContext
    from .schedule import StationSchedule

log = logging.getLogger(__name__)

MIN_VIEW_S = 60
KEEP_DAYS = 400
PERIODS = (1, 7, 30, 0)  # days; 0 is everything kept
TOP_PROGRAMS = 15
# The most slots of a station's schedule a single viewing is followed
# through (several days of short programs).
MOST_SLOTS = 5000
# Who's watching: how often Plex is asked while a station has viewers; the
# most time one look counts (if looks were held up); how long to wait
# after Plex said its token can't see who's watching; and how many of each
# user's stations and shows the Stats tab shows.
POLL_S = 30
MOST_COUNTED_S = 90
REFUSED_WAIT_S = 600
TOP_PER_USER = 3


def day_of(ms: float) -> str:
    """The local date of a moment, as YYYY-MM-DD."""
    return time.strftime("%Y-%m-%d", time.localtime(ms / 1000))


def next_midnight(ms: float) -> int:
    """The local midnight after a moment."""
    t = time.localtime(ms / 1000)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 0, 0, 0, 0, 0, -1)) * 1000)


def what_aired(
    station: StationSchedule, start_ms: int, end_ms: int
) -> list[tuple[str, str, str, float]]:
    """What a station played between two moments, as (day, show or movie,
    kind, seconds): programs only, not the breaks after them. A program
    that runs past midnight counts on both days."""
    out: dict[tuple[str, str, str], float] = {}
    at = start_ms
    for _ in range(MOST_SLOTS):
        if at >= end_ms:
            break
        slot = station.locate(at)
        if slot is None:
            break
        program_end = slot.start_ms + slot.item.program_end_ms
        if at >= program_end:  # in the break after it
            at = max(slot.end_ms, at + 1)
            continue
        upto = min(end_ms, program_end, next_midnight(at))
        key = (day_of(at), slot.item.display_title, slot.item.kind)
        out[key] = out.get(key, 0.0) + (upto - at) / 1000
        at = upto
    return [(*key, round(seconds, 1)) for key, seconds in out.items()]


@dataclass
class Stats:
    db: Database
    _pruned_day: str = ""  # (the day old viewings were last forgotten)

    def record(
        self,
        channel_id: int,
        station: StationSchedule,
        start_ms: int,
        end_ms: int,
        behind_ms: int = 0,
    ) -> None:
        """Keeps a viewing of a station, unless it was too short to count:
        when it was, and what aired meanwhile (`behind_ms` behind the
        schedule, if someone tuned in from the beginning)."""
        if end_ms - start_ms < MIN_VIEW_S * 1000:
            return
        aired = what_aired(station, start_ms - behind_ms, end_ms - behind_ms)
        self.db.add_view(channel_id, start_ms, end_ms, aired)
        today = day_of(end_ms)
        if today != self._pruned_day:
            self._pruned_day = today
            oldest = end_ms - KEEP_DAYS * 86_400_000
            self.db.forget_views_before(oldest, day_of(oldest))


# Who's watching, as Plex says -------------------------------------------------------


class WhoWatches:
    """Asks Plex who's watching, while a station has viewers (see above)."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._last_ms: int | None = None  # when Plex was last asked
        self._refused_until = 0.0
        self.problem = ""  # why Plex can't say, if it can't
        self._watched: dict[int, Item] = {}

    def playing(self, now_ms: int) -> dict[int, tuple[int, Item]]:
        """Each station with viewers: its number, and what its schedule (and
        so Plex's guide) has on. (What they're watching, if they tuned in
        from the beginning and it's running behind, is kept in _watched.)"""
        out: dict[int, tuple[int, Item]] = {}
        self._watched = {}
        for cid, broadcaster in list(self.ctx.broadcasters.items()):
            if not broadcaster.viewers:
                continue
            channel = self.ctx.db.get_channel(cid)
            station = self.ctx.station(cid) if channel else None
            slot = station.locate(now_ms) if station else None
            if channel is None or station is None or slot is None:
                continue
            out[cid] = (channel.number, slot.item)
            if broadcaster.behind_ms:
                shown = station.locate(now_ms - broadcaster.behind_ms)
                if shown is not None:
                    self._watched[cid] = shown.item
        return out

    async def look(self, now_ms: int) -> int:
        """Asks Plex once, and counts the time since the last look for each
        Live TV session matched to a station. How many were counted."""
        playing = await asyncio.to_thread(self.playing, now_ms)
        if not playing:
            self._last_ms = None
            return 0
        if time.monotonic() < self._refused_until:
            return 0
        try:
            sessions = await self.ctx.plex.sessions()
        except PlexError as e:
            if e.status in (401, 403):
                self._refused_until = time.monotonic() + REFUSED_WAIT_S
                self._say(
                    "Plex won't say who's watching because StationPlay's Plex token isn't "
                    "allowed to see what's playing"
                )
            return 0
        self._say("")
        seconds = POLL_S if self._last_ms is None else (now_ms - self._last_ms) / 1000
        seconds = max(0.0, min(float(seconds), MOST_COUNTED_S))
        self._last_ms = now_ms
        rows = []
        for session in sessions:
            uid, name = user_of(session)
            cid = session_station(session, playing)
            if cid is None or not name:
                continue
            item = self._watched.get(cid) or playing[cid][1]
            rows.append(
                (uid or name, name, cid, day_of(now_ms), item.display_title, item.kind, seconds)
            )
        if rows and seconds:
            self.ctx.db.add_user_watching(rows)
        # Stations kept from some Plex users (limits.py).
        await self.ctx.limits.enforce(self.ctx, sessions, playing)
        return len(rows)

    def _say(self, problem: str) -> None:
        if problem and problem != self.problem:
            log.info("%s", problem)
        self.problem = problem

    async def run_forever(self) -> None:
        """Asks Plex every POLL_S while a station has viewers, and every
        limits.FAST_S while a station kept from someone has (see limits.py)."""
        asked = time.monotonic()
        while True:
            await asyncio.sleep(limits.FAST_S)
            if not self.ctx.plex.configured:
                continue
            now = time.monotonic()
            if now - asked < POLL_S - limits.FAST_S / 2 and not self.ctx.limits.watched(
                self.ctx.broadcasters
            ):
                continue
            asked = now
            try:
                await self.look(int(time.time() * 1000))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Asking Plex who's watching failed")


def since_ms(days: int, now_ms: int) -> int:
    """When the last `days` days began: local midnight, today's (1) or that
    many days ago including today. 0 (everything kept) for 0."""
    if not days:
        return 0
    t = time.localtime(now_ms / 1000)
    # (mktime takes a day of the month below 1 as the month before.)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday - days + 1, 0, 0, 0, 0, 0, -1)) * 1000)


def summary(ctx: AppContext, days: int, now_ms: int) -> dict:
    """The Stats tab: for the last `days` days (0: everything kept), each
    station's viewings (most watched first), the most watched shows and
    movies, and when in the day people watch."""
    since = since_ms(days, now_ms)
    views = ctx.db.views_since(since)
    stations = ctx.db.list_channels()
    per: dict[int, dict] = {
        c.id: {
            "id": c.id,
            "number": c.number,
            "name": c.name,
            "logo": c.logo,
            "views": 0,
            "seconds": 0.0,
            "lastMs": 0,
            "top": None,
        }
        for c in stations
    }
    by_hour = [0.0] * 24
    for channel_id, start, end in views:
        start = max(start, since)
        entry = per.get(channel_id)
        if entry is None or end <= start:
            continue
        entry["views"] += 1
        entry["seconds"] += (end - start) / 1000
        entry["lastMs"] = max(entry["lastMs"], end)
        _spread(by_hour, start, end)
    programs: dict[tuple[str, str], dict] = {}
    best: dict[int, tuple[float, str]] = {}
    for channel_id, title, kind, seconds in ctx.db.watched_since(day_of(since) if since else ""):
        if channel_id not in per:
            continue
        p = programs.setdefault(
            (title, kind), {"title": title, "kind": kind, "seconds": 0.0, "stations": set()}
        )
        p["seconds"] += seconds
        p["stations"].add(per[channel_id]["number"])
        if seconds > best.get(channel_id, (0.0, ""))[0]:
            best[channel_id] = (seconds, title)
    for channel_id, (_, title) in best.items():
        per[channel_id]["top"] = title
    ranked = sorted(per.values(), key=lambda e: (-e["seconds"], -e["views"], e["number"]))
    for e in ranked:
        seconds = e.pop("seconds")
        e["hours"] = round(seconds / 3600, 2)
        e["averageMinutes"] = round(seconds / 60 / e["views"], 1) if e["views"] else 0
    top = sorted(programs.values(), key=lambda p: -p["seconds"])[:TOP_PROGRAMS]
    return {
        "watchingNow": sum(len(b.viewers) for b in ctx.broadcasters.values()),
        "totals": {
            "views": sum(e["views"] for e in ranked),
            "hours": round(sum(e["hours"] for e in ranked), 2),
            "watched": sum(1 for e in ranked if e["views"]),
        },
        "stations": ranked,
        "programs": [
            {
                "title": p["title"],
                "kind": p["kind"],
                "hours": round(p["seconds"] / 3600, 2),
                "stations": sorted(p["stations"]),
            }
            for p in top
        ],
        "byHour": [round(h / 3600, 2) for h in by_hour],
    }


def users(ctx: AppContext, days: int, now_ms: int) -> list[dict]:
    """Who watched, as Plex said (see WhoWatches), most first: each Plex
    user's hours, and the stations and shows or movies they watched most."""
    since = since_ms(days, now_ms)
    numbers = {c.id: (c.number, c.name) for c in ctx.db.list_channels()}
    per: dict[str, dict] = {}
    for uid, name, channel_id, title, kind, seconds in ctx.db.user_watched_since(
        day_of(since) if since else ""
    ):
        if channel_id not in numbers:
            continue
        u = per.setdefault(uid, {"name": name, "seconds": 0.0, "stations": {}, "programs": {}})
        u["seconds"] += seconds
        u["stations"][channel_id] = u["stations"].get(channel_id, 0.0) + seconds
        u["programs"][(title, kind)] = u["programs"].get((title, kind), 0.0) + seconds
    out = []
    for u in sorted(per.values(), key=lambda u: (-u["seconds"], u["name"].casefold())):
        stations = sorted(u["stations"].items(), key=lambda kv: -kv[1])[:TOP_PER_USER]
        programs = sorted(u["programs"].items(), key=lambda kv: -kv[1])[:TOP_PER_USER]
        out.append(
            {
                "name": u["name"],
                "hours": round(u["seconds"] / 3600, 2),
                "stations": [
                    {
                        "number": numbers[cid][0],
                        "name": numbers[cid][1],
                        "hours": round(sec / 3600, 2),
                    }
                    for cid, sec in stations
                ],
                "programs": [
                    {"title": title, "kind": kind, "hours": round(sec / 3600, 2)}
                    for (title, kind), sec in programs
                ],
            }
        )
    return out


def _spread(by_hour: list[float], start: int, end: int) -> None:
    """Adds a viewing's seconds to the hours of the (local) day they fell in."""
    at = start
    while at < end:
        t = time.localtime(at / 1000)
        hour_end = (at // 1000 - t.tm_min * 60 - t.tm_sec + 3600) * 1000
        upto = min(end, hour_end)
        by_hour[t.tm_hour] += (upto - at) / 1000
        at = upto


def routes(app: FastAPI, ctx: AppContext) -> None:
    @app.get("/api/stats")
    async def stats(request: Request, days: int = 7):
        if days not in PERIODS:
            raise HTTPException(400, f"Days must be one of {', '.join(map(str, PERIODS))}")
        now = int(time.time() * 1000)
        out = summary(ctx, days, now)
        # Who watched what is for Admins (or anyone, while signing in is off).
        if ctx.access.sees_everything(access.signed_in(request)):
            out["users"] = users(ctx, days, now)
            out["usersProblem"] = ctx.who_watches.problem
        return out
