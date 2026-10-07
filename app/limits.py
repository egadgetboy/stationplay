"""Keeping stations from some Plex users: optional, off unless it's set up
on the Access tab. It's done through Plex alone, and needs Plex Pass.

Plex can't hide one channel from one person: every station is in the guide
of everyone with Live TV on this server. So instead, while a station kept
from someone has viewers, Plex is asked every FAST_S seconds what it's
playing to whom (by stats.WhoWatches, which asks anyway for the Stats tab),
and a Plex user's Live TV session watching a station kept from them is
stopped, with a message saying why. That's Plex's own "stop playback",
which works only with Plex Pass on the server owner's account. They can
tune in again; it's stopped again.

It's stopped only when StationPlay is sure which station that is
(sure_station): the one station of those with viewers airing what the
session shows, nothing Plex says about it naming another channel, and
either that very program (its show and episode, or movie) or Plex naming
the station's channel number. Anything less, and it's left playing (and
the log says why, once).

It covers anyone watching through Plex on this server, as Plex names them:
you, Plex Home members (managed users too), and friends you've shared Live
TV with. Watching through other apps (the M3U playlist) isn't seen.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from .plex import PlexError
from .watching import sure_station, user_of

if TYPE_CHECKING:
    from .db import Database, Item
    from .main import AppContext

log = logging.getLogger(__name__)

META = "plex_limits"
# How often Plex is asked while a station kept from someone has viewers.
FAST_S = 5
# A session that's been stopped and is still playing is stopped again after
# this long (Plex takes a moment to end it).
AGAIN_S = 30
STOPS_KEPT = 20
REASON = "This station isn't available on your Plex account."
NAME_MAX = 100


class Limits:
    """Which stations are kept from which Plex users, and what was stopped."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.on = False
        self.kept: dict[str, set[int]] = {}  # Plex user's id -> station ids
        self.names: dict[str, str] = {}  # (their names, as last seen)
        self.stops: deque[dict[str, Any]] = deque(maxlen=STOPS_KEPT)  # newest last
        self.problem = ""  # why the last stop failed, if it did
        self._stopped: dict[str, float] = {}  # session id -> when it was stopped
        self._unsure: set[str] = set()  # sessions whose "not sure" was logged
        self._load()

    def _load(self) -> None:
        try:
            got = json.loads(self.db.get_meta(META) or "{}")
        except ValueError:
            got = {}
        if not isinstance(got, dict):
            got = {}
        self.on = got.get("on") is True
        kept = got.get("kept")
        names = got.get("names")
        self.kept = {
            str(uid): {int(c) for c in cids if isinstance(c, int)}
            for uid, cids in (kept.items() if isinstance(kept, dict) else ())
            if str(uid).isdigit() and isinstance(cids, list)
        }
        self.kept = {uid: cids for uid, cids in self.kept.items() if cids}
        self.names = {
            str(uid): str(name)[:NAME_MAX]
            for uid, name in (names.items() if isinstance(names, dict) else ())
            if str(uid) in self.kept
        }

    def save(self, on: bool, kept: dict[str, list[int]], names: dict[str, str]) -> None:
        """Sets it: who's kept from which stations (stations that aren't there
        are left out), and their names. ValueError if a Plex user's id isn't
        one."""
        stations = {c.id for c in self.db.list_channels()}
        clean: dict[str, set[int]] = {}
        for uid, cids in kept.items():
            uid = str(uid).strip()
            if not uid.isdigit() or uid == "0":
                raise ValueError(f"{uid[:20]!r} isn't a Plex user ID")
            chosen = {c for c in cids if c in stations}
            if chosen:
                clean[uid] = chosen
        self.on = bool(on)
        self.kept = clean
        self.names = {
            uid: str(names.get(uid) or self.names.get(uid) or "")[:NAME_MAX].strip()
            for uid in clean
        }
        self.db.set_meta(
            META,
            json.dumps(
                {
                    "on": self.on,
                    "kept": {uid: sorted(cids) for uid, cids in self.kept.items()},
                    "names": self.names,
                }
            ),
        )

    def kept_now(self) -> dict[str, set[int]]:
        """Who's kept from which stations, while it's on."""
        return self.kept if self.on else {}

    def watched(self, broadcasters: dict[int, Any]) -> bool:
        """Whether a station kept from someone has viewers now."""
        kept = set().union(*self.kept_now().values()) if self.on and self.kept else set()
        return any(cid in kept and b.viewers for cid, b in list(broadcasters.items()))

    async def enforce(
        self,
        ctx: AppContext,
        sessions: list[dict[str, Any]],
        playing: dict[int, tuple[int, Item]],
    ) -> int:
        """Stops each Live TV session of a Plex user watching a station kept
        from them (see above). How many were stopped."""
        kept = self.kept_now()
        if not kept:
            return 0
        now = time.monotonic()
        self._stopped = {s: t for s, t in self._stopped.items() if now - t < 600}
        if len(self._unsure) > 1000:
            self._unsure.clear()
        stopped = 0
        for session in sessions:
            uid, name = user_of(session)
            if uid not in kept:
                continue
            cid, why = sure_station(session, playing)
            sid = _session_id(session)
            if cid is None:
                if why and sid and sid not in self._unsure:
                    self._unsure.add(sid)
                    log.info("Didn't stop %s's Plex Live TV session: %s", name, why)
                continue
            if cid not in kept[uid]:
                continue
            number = playing[cid][0]
            channel = ctx.db.get_channel(cid)
            station = f"{number} {channel.name}" if channel else str(number)
            if not sid:
                if f"no id {uid} {cid}" not in self._unsure:
                    self._unsure.add(f"no id {uid} {cid}")
                    log.warning(
                        "%s is watching station %s, which is blocked for them, but Plex gave no "
                        "session ID to stop",
                        name,
                        station,
                    )
                continue
            if now - self._stopped.get(sid, -AGAIN_S) < AGAIN_S:
                continue
            self._stopped[sid] = now
            try:
                await ctx.plex.stop_session(sid, REASON)
            except PlexError as e:
                if e.status in (401, 403):
                    self.problem = (
                        f"Plex wouldn't stop {name} from watching station {station}. Stopping "
                        "playback needs Plex Pass on the server owner's account."
                    )
                else:
                    self.problem = (
                        f"Plex couldn't stop {name} from watching station {station} ({e})"
                    )
                log.warning("%s", self.problem)
                continue
            self.problem = ""
            self.names[uid] = name
            stopped += 1
            self.stops.append(
                {
                    "name": name,
                    "number": number,
                    "station": station,
                    "atMs": int(time.time() * 1000),
                }
            )
            log.info(
                "Stopped %s from watching station %s in Plex (blocked for them)", name, station
            )
        return stopped


def _session_id(session: dict[str, Any]) -> str:
    """The id Plex stops a session by (its "Session"'s)."""
    given = session.get("Session")
    if isinstance(given, list):
        given = next((s for s in given if isinstance(s, dict)), None)
    return str(given.get("id") or "").strip() if isinstance(given, dict) else ""
