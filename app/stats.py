"""Viewing statistics for the Stats tab: how much each station is watched,
by whom, and what's played on demand; and who's watching now.

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

StationPlay's own apps are counted one by one: each app watching a station
is a viewing of its own (see hls.py), and counts for the person signed in
on it (see playing.py), so who watched is known exactly. What's played on
demand (Media) counts in its own place: its plays and time, by show or
movie and by person, as it's watched (see ondemand.PlaySessions).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request

from . import access, catalog, limits, playing
from .plex import PlexError
from .watching import session_station, user_of

if TYPE_CHECKING:
    from .broadcaster import Broadcaster
    from .db import Database, Item
    from .main import AppContext
    from .ondemand import PlaySession
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
# The Stats tab's top people and top Media, at most; and how often what's
# being played on demand is counted.
TOP_PEOPLE = 20
TOP_MEDIA = 15
PLAYS_COUNT_S = 60


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
        person: tuple[int, str] | None = None,
    ) -> None:
        """Keeps a viewing of a station, unless it was too short to count:
        when it was, and what aired meanwhile (`behind_ms` behind the
        schedule, if someone tuned in from the beginning); and with a
        `person` (a StationPlay user's id and name, in its apps), what they
        watched."""
        if end_ms - start_ms < MIN_VIEW_S * 1000:
            return
        aired = what_aired(station, start_ms - behind_ms, end_ms - behind_ms)
        self.db.add_view(channel_id, start_ms, end_ms, aired)
        if person is not None:
            self.db.add_app_watching([(*person, channel_id, *a) for a in aired])
        self._prune(end_ms)

    def played(self, session: PlaySession) -> None:
        """Counts what's been watched of something played on demand since
        it was last counted: a play, once it's been watched MIN_VIEW_S (the
        same program again on the same device soon after is the same play:
        see ondemand.PlaySessions.start), and its time, on the day it's
        counted."""
        new = session.watched_s - session.counted_s
        if new <= 0 or (not session.played and session.watched_s < MIN_VIEW_S):
            return
        plays = 0 if session.played else 1
        session.played, session.counted_s = True, session.watched_s
        e = session.entry
        named = e.show_title if e.kind == catalog.EPISODE and e.show_title else e.title
        now = int(time.time() * 1000)
        self.db.add_media_watching(
            (session.user_id, session.user, day_of(now), named, e.kind, plays, round(new, 1))
        )
        self._prune(now)

    def _prune(self, now_ms: int) -> None:
        """Forgets what's older than KEEP_DAYS, once a day."""
        today = day_of(now_ms)
        if today != self._pruned_day:
            self._pruned_day = today
            oldest = now_ms - KEEP_DAYS * 86_400_000
            self.db.forget_views_before(oldest, day_of(oldest))


async def count_plays_forever(ctx: AppContext) -> None:
    """Counts what's being played on demand as it plays (every
    PLAYS_COUNT_S), so the stats are up to date while it's watched; and
    tidies what apps gone without leaving left behind (see
    ondemand.PlaySessions.tidy)."""
    while True:
        await asyncio.sleep(PLAYS_COUNT_S)
        try:
            ctx.plays.count()
            ctx.plays.tidy()  # (and what apps gone without leaving left behind)
        except Exception:
            log.exception("Counting what's played in the apps failed")


# Who's watching, as Plex says -------------------------------------------------------


class WhoWatches:
    """Asks Plex who's watching, while a station has viewers (see above)."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._last_ms: int | None = None  # when Plex was last asked
        self._refused_until = 0.0
        self.problem = ""  # why Plex can't say, if it can't
        self._watched: dict[int, Item] = {}
        # What Plex said at its last look: each station's Live TV sessions
        # (for Watching now), when that was, and when each session was
        # first seen.
        self.sessions: dict[int, list[dict]] = {}
        self.looked_ms = 0
        self._first_seen: dict[str, int] = {}

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
            self.sessions, self._first_seen = {}, {}
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
        seen: dict[int, list[dict]] = {}
        first_seen: dict[str, int] = {}
        for session in sessions:
            uid, name = user_of(session)
            cid = session_station(session, playing)
            if cid is None:
                continue
            sid = _session_id(session)
            first_seen[sid] = self._first_seen.get(sid, now_ms)
            seen.setdefault(cid, []).append(
                {**_player(session), "user": name, "since": first_seen[sid]}
            )
            if not name:
                continue
            item = self._watched.get(cid) or playing[cid][1]
            rows.append(
                (uid or name, name, cid, day_of(now_ms), item.display_title, item.kind, seconds)
            )
        self.sessions, self._first_seen, self.looked_ms = seen, first_seen, now_ms
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


def _session_id(session: dict) -> str:
    given = session.get("Session")
    found = given.get("id") if isinstance(given, dict) else None
    return str(found or session.get("sessionKey") or id(session))


def _player(session: dict) -> dict:
    """Which Plex app on which device a session is in, and whether it's at
    home, as Plex says: {"app", "where"} ("home", "away" or None)."""
    given = session.get("Player")
    player: dict = given if isinstance(given, dict) else {}
    product = str(player.get("product") or "").strip()
    device = str(player.get("title") or "").strip()
    app = f"{product} on {device}" if product and device else product or device
    given = session.get("Session")
    location = str((given if isinstance(given, dict) else {}).get("location") or "")
    local = str(player.get("local", ""))
    where = (
        "home"
        if location == "lan" or local in ("1", "true")
        else "away"
        if location == "wan" or local in ("0", "false")
        else None
    )
    return {"app": app or None, "where": where}


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
        "watchingNow": len(now(ctx, now_ms)),
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


def people(ctx: AppContext, days: int, now_ms: int) -> list[dict]:
    """Who watched most (TOP_PEOPLE), stations and Media together: each
    StationPlay user, by what they watched in its apps, and each Plex user,
    as Plex said (see WhoWatches); with their hours, and the stations and
    shows or movies they watched most."""
    since = since_ms(days, now_ms)
    day = day_of(since) if since else ""
    numbers = {c.id: (c.number, c.name) for c in ctx.db.list_channels()}
    per: dict[tuple[str, object], dict] = {}

    def person(plex: bool, uid: object, name: str) -> dict:
        return per.setdefault(
            ("plex" if plex else "app", uid),
            {"name": name, "plex": plex, "stations": 0.0, "media": 0.0,
             "byStation": {}, "byTitle": {}},
        )  # fmt: skip

    def add(p: dict, channel_id: int | None, title: str, kind: str, seconds: float) -> None:
        p["stations" if channel_id is not None else "media"] += seconds
        if channel_id is not None:
            p["byStation"][channel_id] = p["byStation"].get(channel_id, 0.0) + seconds
        p["byTitle"][(title, kind)] = p["byTitle"].get((title, kind), 0.0) + seconds

    for user_id, name, channel_id, title, kind, seconds in ctx.db.app_watched_since(day):
        if channel_id in numbers:
            add(person(False, user_id, name), channel_id, title, kind, seconds)
    for user_id, name, title, kind, _plays, seconds in ctx.db.media_watched_since(day):
        if user_id:  # (not while signing in is off: no one)
            add(person(False, user_id, name), None, title, kind, seconds)
    for plex_id, name, channel_id, title, kind, seconds in ctx.db.user_watched_since(day):
        if channel_id in numbers:
            add(person(True, plex_id, name), channel_id, title, kind, seconds)
    ranked = sorted(
        per.values(), key=lambda p: (-(p["stations"] + p["media"]), p["name"].casefold())
    )
    out = []
    for p in ranked[:TOP_PEOPLE]:
        stations = sorted(p["byStation"].items(), key=lambda kv: -kv[1])[:TOP_PER_USER]
        titles = sorted(p["byTitle"].items(), key=lambda kv: -kv[1])[:TOP_PER_USER]
        out.append(
            {
                "name": p["name"],
                "plex": p["plex"],
                "hours": _hours(p["stations"] + p["media"]),
                "stationHours": _hours(p["stations"]),
                "mediaHours": _hours(p["media"]),
                "stations": [
                    {"number": numbers[cid][0], "name": numbers[cid][1], "hours": _hours(sec)}
                    for cid, sec in stations
                ],
                "programs": [
                    {"title": title, "kind": kind, "hours": _hours(sec)}
                    for (title, kind), sec in titles
                ],
            }
        )
    return out


def media(ctx: AppContext, days: int, now_ms: int) -> list[dict]:
    """The shows and movies played on demand most (TOP_MEDIA): their hours
    and plays."""
    since = since_ms(days, now_ms)
    per: dict[tuple[str, str], list[float]] = {}
    for _uid, _name, title, kind, plays, seconds in ctx.db.media_watched_since(
        day_of(since) if since else ""
    ):
        got = per.setdefault((title, kind), [0.0, 0])
        got[0] += seconds
        got[1] += plays
    top = sorted(per.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0][0].casefold()))
    return [
        {"title": title, "kind": kind, "hours": _hours(seconds), "plays": int(plays)}
        for (title, kind), (seconds, plays) in top[:TOP_MEDIA]
    ]


def _hours(seconds: float) -> float:
    return round(seconds / 3600, 2)


# Who's watching now ------------------------------------------------------------------


def on_gpu(ctx: AppContext) -> int:
    """The stations and copies being made on the GPU now."""
    stations, copies = gpu_load(ctx)
    return stations + copies


def gpu_load(ctx: AppContext) -> tuple[int, int]:
    """(Stations, copies) being made on the GPU now."""
    stations = sum(
        1
        for b in ctx.broadcasters.values()
        if b.running and b.encoder_now is not None and b.encoder_now.is_gpu
    )
    return stations, ctx.plays.copies(on_gpu=True)


def now(ctx: AppContext, now_ms: int) -> list[dict]:
    """Everyone watching now, one row each (see "Watching now" on the Stats
    tab), the longest-watching first: Plex's viewers (each Plex user, when
    Plex says; otherwise each stream it asks for), other players, the apps
    watching stations, and what the apps are playing on demand."""
    rows: list[dict] = []
    fresh = now_ms - ctx.who_watches.looked_ms <= 2 * POLL_S * 1000
    names = {u.id: u.name for u in ctx.db.users()}  # (as they're named now)
    for cid, b in list(ctx.broadcasters.items()):
        channel = ctx.db.get_channel(cid)
        if channel is None or not b.viewers:
            continue
        what = _station_now(ctx, b, channel.number, channel.name, now_ms)
        how = _station_how(b)
        known = ctx.who_watches.sessions.get(cid, []) if fresh else []
        rows += [
            _row(s["user"], True, s["app"], s["where"], None, s["since"], how, station=what)
            for s in known
        ]
        if not known:
            rows += [
                _row(None, "plex" in v.agent.casefold(), v.agent, None, v.client, v.started_ms,
                     how, station=what)
                for v in b.viewers
                if v.counted
            ]  # fmt: skip
    for stream in ctx.hls_streams.streams():
        channel = ctx.db.get_channel(stream.b.channel_id)
        if channel is None:
            continue
        what = _station_now(ctx, stream.b, channel.number, channel.name, now_ms)
        how = _station_how(stream.b, night=stream.night)
        rows += [_app_row(who, since, how, names, station=what) for who, since in stream.viewing()]
    for session in ctx.plays.now():
        # (Away from home, told apart by its app's own address, as stations are.)
        who = playing.Watcher(
            session.client, session.away, session.user, session.user_id or None, session.app,
            session.tag,
        )  # fmt: skip
        rows.append(
            _app_row(who, session.started_ms, _media_how(session), names,
                     media={"title": playing.title(session.entry)})
        )  # fmt: skip
    rows.sort(key=lambda r: r["sinceMs"] or now_ms)
    return rows


def _row(
    who: str | None,
    plex: bool,
    app: str | None,
    where: str | None,
    address: str | None,
    since_ms: int,
    how: dict,
    station: dict | None = None,
    media: dict | None = None,
) -> dict:
    """One row of Watching now: who (a StationPlay user, or with `plex`, a
    Plex user), in which app on which device, at home or away, from where,
    since when, what (a station, or something from Media), and how it's
    sent."""
    return {
        "who": who or None,
        "plex": plex,
        "app": app or None,
        "where": where,
        "address": address or None,
        "sinceMs": since_ms,
        "station": station,
        "media": media,
        "how": how,
    }


def _app_row(
    who: playing.Watcher, since_ms: int, how: dict, names: dict[int, str], **what: dict | None
) -> dict:
    """A row for an app watching (`names`: StationPlay's users' names now,
    by id: someone renamed while watching shows by their new one)."""
    person = names.get(who.user_id, who.person) if who.user_id is not None else who.person
    return _row(
        person, False, who.app, "away" if who.away else "home", who.key or who.address,
        since_ms, how, **what,
    )  # fmt: skip


def _station_now(ctx: AppContext, b: Broadcaster, number: int, name: str, now_ms: int) -> dict:
    """A station, and what's on it now (as its viewers see it)."""
    slot = ctx.station(b.channel_id).locate(now_ms - b.behind_ms)
    return {"number": number, "name": name, "program": slot.item.label if slot else None}


def _station_how(b: Broadcaster, night: bool = False) -> dict:
    """How a station is sent: converted, at its picture size and bitrate,
    where its program is encoded."""
    encoder = b.encoder_now
    return {
        "method": "convert",
        "picture": playing.size(b.settings.video_height),
        "mbps": round(b.settings.video_bitrate_kbps / 1000, 1),
        "on": None if encoder is None else "GPU" if encoder.is_gpu else "CPU",
        "notes": ["night mode's sound"] if night else [],
    }


def _media_how(session: PlaySession) -> dict:
    """How something played on demand is sent: as it is, repackaged or
    converted, its picture's size and bitrate, and (converted) where."""
    copy = session.copy
    m = session.media
    if copy is None:
        return {"method": "direct", "picture": m.size_label or None,
                "mbps": _mbps(m.bitrate_kbps), "on": None, "notes": []}  # fmt: skip
    plan = copy.plan
    notes = [n for n, on in (("subtitles drawn in", plan.subtitles is not None),
                             ("even sound", plan.even), ("night mode's sound", plan.night))
             if on]  # fmt: skip
    if plan.copies_picture:
        return {"method": "repackage", "picture": m.size_label or None,
                "mbps": _mbps(m.bitrate_kbps), "on": None, "notes": notes}  # fmt: skip
    return {
        "method": "convert",
        "picture": playing.size(plan.height) if plan.height else None,
        "mbps": _mbps(plan.kbps_needed),
        "on": "GPU" if copy.encoder.is_gpu else "CPU",
        "notes": notes,
    }


def _mbps(kbps: int | None) -> float | None:
    return round(kbps / 1000, 1) if kbps else None


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
            out["people"] = people(ctx, days, now)
            out["media"] = media(ctx, days, now)
        return out

    @app.get("/api/stats/now")
    async def stats_now():
        """The server's health, and who's watching now (for Admins: see
        access.FOR_USERS), asked every few seconds while the Stats tab is
        open."""
        now_ms = int(time.time() * 1000)
        stations, copies = gpu_load(ctx)
        gpu = ctx.gpu
        return {
            "atMs": now_ms,
            "server": {
                **ctx.health.as_dict(),
                "gpu": {
                    "name": gpu.active.label if gpu.active.is_gpu else None,
                    "state": gpu.state,
                    "stations": stations,
                    "copies": copies,
                },
            },
            "watching": now(ctx, now_ms),
        }
