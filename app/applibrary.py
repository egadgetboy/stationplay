"""Your library in StationPlay's apps: the apps' own addresses for browsing
and playing it (under /api/internal; see docs/on-demand.md, and
docs/internal-api.md for the contract), the play sessions' own addresses,
and the Access tab's setting.

At home (and through a VPN, which looks like home), and through the public
port while watching away from home is on (see away.py): there, a signed-in
app does what it may at home, within the same Viewing Levels and limits, and
a program it starts plays at the Admin's quality away from home. A program's
own addresses (/play/<session>/...) are offered on the public port only for
a program an app started there, and only while it and that app's sign-in
last (see access.Access.play_outside, and session_or_404); one started at
home is never offered there.

The deciding is in ondemand.py; this is the asking and answering.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import (
    access,
    away,
    capacity,
    catalog,
    converting,
    keyframes,
    languages,
    ondemand,
    playing,
    subtitles,
    viewing,
)
from . import scanner as sc
from .appapi import APP_MAX, LanguagesIn, app_label, in_sentence, slot_program
from .broadcaster import now_ms
from .broken import version_key
from .catalog import Entry, Media, Track
from .ffmpeg import Encoder, ProbeResult, Subtitles, to_sdr
from .library import LibraryError
from .ondemand import NotShared
from .sources import find_first, learn_mapping, local_candidates
from .text import plain

if TYPE_CHECKING:
    from .db import User
    from .main import AppContext

log = logging.getLogger(__name__)

NONE_SHARED = "No libraries are shared with StationPlay's apps"
AWAY_OFF = (
    "Your library can be watched away from home once an Admin turns on StationPlay's apps "
    "away from home, on the Access tab."
)
PLAY_ENDED = "That program's address has ended. Choose it again to play it."
# Even sound for a show's episodes, as a copy's `why` says it (the apps show
# it in their player).
EVEN_WHY = "even sound for the show's episodes"
NOT_PLAYABLE = "Choose an episode or a movie to play"
NO_PICTURE = "There's no such picture"
PAST_END = "That's past the end of this program"
# A place reported this far past the end of what plays is refused (a little
# past it is the end: watched).
PAST_END_MS = 10 * 60_000
UNREACHABLE_SAID_S = 60.0  # (the log says the library can't be reached once a minute, at most)
NO_FILE = "StationPlay can't reach this program's file right now. Try again in a moment."
COPY_FAILED = "StationPlay couldn't make this ready to play here. Try again, or choose another."
# A program whose every version StationPlay found broken (see broken.py):
# what the app is told. (The Broken files tab has it, for an Admin.)
ON_THE_LIST = "This one can't play right now. An Admin has been told."
KEYFRAMES_WAIT_S = 20.0  # reading a file's index, at most
# A smaller version or copy of what a device was playing this soon after is
# a step down in quality (said in the log), and a reason an app sent this
# soon before it (a "kept-up" problem: see problems.py) is why.
STEP_S = 120.0
# Copies with their picture converted at once, at most (each takes a share of
# the server's processor; repackaging takes next to nothing). A few more
# while the stations' GPU is in use, which converts them (see converting.py):
# a copy converted there is light on the processor.
CONVERTING_MOST = 3
CONVERTING_MOST_GPU = 6
BUSY_CONVERTING = (
    "StationPlay is already converting as much as it can for other devices. Try again in a "
    "little while."
)

# A file's type, for players that go by it.
_TYPES = {
    "mkv": "video/x-matroska", "mp4": "video/mp4", "mov": "video/quicktime", "ts": "video/mp2t",
    "avi": "video/x-msvideo", "webm": "video/webm", "m2ts": "video/mp2t", "wmv": "video/x-ms-wmv",
}  # fmt: skip
_SUBTITLE_TYPES = {
    "srt": "application/x-subrip", "vtt": "text/vtt", "ass": "text/x-ssa", "ssa": "text/x-ssa",
}  # fmt: skip
# Asking Plex for a file on a player's behalf: how long to wait.
PROXY_TIMEOUT = httpx.Timeout(30.0, read=120.0)
SUBTITLES_MOST = 20 << 20  # a subtitle file's size, at most
PROXIED_HEADERS = ("content-type", "content-length", "content-range", "accept-ranges",
                   "last-modified", "etag")  # fmt: skip


class VideoAbility(BaseModel):
    codec: str = Field(max_length=20)
    width: int = Field(default=1920, ge=0, le=16384)
    height: int = Field(default=1080, ge=0, le=16384)
    bitDepth: int = Field(default=8, ge=8, le=16)


class Abilities(BaseModel):
    containers: list[str] = Field(default_factory=list, max_length=40)
    video: list[VideoAbility] = Field(default_factory=list, max_length=40)
    hdr: list[str] = Field(default_factory=list, max_length=10)
    audio: list[str] = Field(default_factory=list, max_length=40)
    hls: list[str] = Field(
        default_factory=list, max_length=10
    )  # (copies it takes: see converting.py)
    # The subtitle formats its player shows itself (from 1.29.0: see
    # languages.py; without them, a subtitle chosen for someone is drawn in).
    subtitles: list[str] = Field(default_factory=list, max_length=20)


class PlayAsk(BaseModel):
    key: str = Field(max_length=20)
    device: Abilities
    version: str | None = Field(default=None, max_length=40)
    maxKbps: int | None = Field(default=None, ge=100, le=10_000_000)
    app: str = Field(default="", max_length=APP_MAX)
    deviceName: str = Field(default="", max_length=APP_MAX)
    startMs: int | None = Field(default=None, ge=0, le=7 * 86_400_000)
    audio: str | None = Field(default=None, max_length=40)
    subtitle: str | None = Field(default=None, max_length=40)
    fit: bool = False
    night: bool = False


class ProgressReport(BaseModel):
    key: str = Field(max_length=20)
    positionMs: int | None = Field(default=None, ge=0, le=7 * 86_400_000)
    watched: bool | None = None
    session: str | None = Field(default=None, max_length=64)
    # Each report's place in its playing (1, 2, 3...), so one sent before
    # another but arriving after it is known (from 1.30.0).
    sequence: int | None = Field(default=None, ge=1, le=2**31)


class WhenSlow(BaseModel):
    home: str | None = Field(default=None, max_length=10)
    away: str | None = Field(default=None, max_length=10)


class SharedLibraries(BaseModel):
    libraries: list[str] = Field(max_length=ondemand.LIBRARIES_MOST)
    whenSlow: WhenSlow | None = None
    evenSound: bool | None = None  # (None: as it is)


# What the apps are told ----------------------------------------------------------------


def art(key: str, kind: str) -> str:
    return f"/api/internal/art/{key}?kind={kind}"


def card(e: Entry, progress: dict[str, tuple[int, bool]], unwatched: int | None = None) -> dict:
    """A show, movie or episode in a list (see "A card" in docs/internal-api.md)."""
    out: dict[str, Any] = {
        "key": e.key,
        "kind": e.kind,
        "title": plain(e.show_title or e.title) if e.kind == catalog.EPISODE else plain(e.title),
        "year": e.year,
        "poster": art(e.show_key or e.key, "poster")
        if e.kind == catalog.EPISODE and e.show_key
        else (art(e.key, "poster") if e.has_thumb else None),
    }
    if e.kind == catalog.SHOW:
        out["episodes"] = e.episodes
        out["unwatched"] = unwatched
        return out
    row = progress.get(e.key)
    out.update(
        durationMs=e.duration_ms,
        positionMs=ondemand.resume_at(row),
        watched=bool(row and row[1]),
    )
    if e.kind == catalog.EPISODE:
        out.update(
            episodeTitle=plain(e.title) or None,
            season=e.season,
            episode=e.episode,
            showKey=e.show_key,
            thumb=art(e.key, "thumb") if e.has_thumb else None,
        )
    return out


def details(e: Entry) -> dict:
    """What a details page adds to a card."""
    return {
        "summary": plain(e.summary),
        "tagline": plain(e.tagline) or None,
        "genres": [plain(g) for g in e.genres],
        "contentRating": plain(e.content_rating) or None,
        "studio": plain(e.studio) or None,
        "released": e.released or None,
        "backdrop": art(e.key, "backdrop") if e.has_art else None,
        "cast": [
            {"name": name, "role": plain(role)} for who, role in e.cast if (name := plain(who))
        ],
        "directors": [name for who in e.directors if (name := plain(who))],
        "writers": [name for who in e.writers if (name := plain(who))],
    }


def versions(e: Entry, problems: dict[str, str] | None = None) -> list[dict]:
    """An episode's or movie's versions, the best first (see `versions` in
    docs/internal-api.md); `problems`: what StationPlay found wrong with
    each one's file, if anything ("broken" or "damaged", by its ID)."""
    best = ondemand.best_first(e.media)
    names = ondemand.version_labels(best)
    return [
        {
            "id": m.id,
            "name": names[i],
            "size": m.size_label or None,
            "hdr": ondemand.hdr_label(m),
            "bitrateKbps": m.bitrate_kbps,
            "problem": (problems or {}).get(m.id),
        }
        for i, m in enumerate(best)
        if m.id
    ]


def playable_versions(
    e: Entry, dev: ondemand.Device, max_kbps: int | None, problems: dict[str, str] | None = None
) -> list[dict]:
    """Its versions, each saying whether this device can play it as it is,
    and whether the connection keeps up with it."""
    out = []
    best = [m for m in ondemand.best_first(e.media) if m.id]
    for v, m in zip(versions(e, problems), best, strict=True):
        why = ondemand.unplayable(m, dev)
        out.append(
            {**v, "playable": not why, "why": why or None, "fits": ondemand.fits(m, max_kbps)}
        )
    return out


def tracks(found: tuple[Track, ...], audio: bool) -> list[dict]:
    return [
        {
            "id": t.id,
            "name": ondemand.track_name(t, audio),
            "language": plain(t.language) or None,
            "languageCode": languages.track_code(t),
            "codec": t.codec,
            "default": t.default,
            **({} if audio else {"forced": t.forced, "external": t.external}),
            "index": t.index,
        }
        for t in found
        if t.id
    ]


def describe(e: Entry) -> str:
    """A program, as the log names it: "Northbound · S2 E4", "Jaws (1975)"."""
    return playing.title(e)


def sound_of(media: Media, track: Track | None) -> str:
    """A version's picture and sound, with the sound track playing: "1080p
    HEVC HDR10, 5.1 E-AC-3"."""
    return playing.picture_and_sound(
        media.width, media.height, media.video, ondemand.hdr_label(media) or "",
        track.channels if track else None, track.codec if track else "",
    )  # fmt: skip


def how_copied(
    plan: converting.Plan,
    cant: list[str],
    smaller: bool,
    encoder: Encoder,
    cap_kbps: int | None = None,
) -> str:
    """How a copy plays, for the log: "repackaged, its sound made AAC
    stereo, because this device can't play its sound's format (DTS)";
    "converted to 1080p H.264 at 8 Mbps on the Intel/AMD GPU, because...";
    "converted smaller to fit the connection: 720p H.264 at 4 Mbps on the
    CPU, with subtitles drawn in"; away from home, a file over the Admin's
    cap (`cap_kbps`): "converted smaller to fit the 10 Mbps allowed away from
    home: 1080p H.264 at 8 Mbps on the CPU"."""
    if plan.copies_picture:
        text = "repackaged"
        if plan.audio_codec != "copy" and not plan.night:
            text += (
                f", its sound made {playing.sound_name(plan.audio_codec)} "
                f"{playing.channels(plan.audio_channels)}"
            )
    else:
        made = (
            f"{playing.size(plan.height)} H.264 at {playing.mbps(plan.kbps)} on "
            f"{playing.encoder_name(encoder)}"
        )
        if smaller:
            text = f"converted smaller to fit the connection: {made}"
        elif cap_kbps:
            allowed = f"the {playing.mbps(cap_kbps)} allowed away from home"
            text = f"converted smaller to fit {allowed}: {made}"
        else:
            text = f"converted to {made}"
    extras = [
        what
        for what, on in (
            ("subtitles drawn in", plan.drawn is not None),
            ("even sound", plan.even),
            ("night mode's sound", plan.night),
        )
        if on
    ]
    if extras:
        text += f", with {ondemand.and_list(extras)}"
    if cant:
        text += f", because this device can't play {ondemand.and_list(cant)}"
    return text


def quality(session: ondemand.PlaySession) -> tuple[int, int, str]:
    """What a session sends, to compare with another: (its picture's
    height, its kilobits a second, in words: "1080p at 12 Mbps")."""
    copy = session.copy
    if copy is not None and not copy.plan.copies_picture:
        plan = copy.plan
        words = f"{playing.size(plan.height)} H.264 at {playing.mbps(plan.kbps)}"
        return plan.height, plan.kbps, words + f" on {playing.encoder_name(copy.encoder)}"
    m = session.media
    named = m.size_label or "its picture"
    words = f"{named} at {playing.mbps(m.bitrate_kbps)}" if m.bitrate_kbps else named
    return m.height, m.bitrate_kbps or 0, words


def stepped_down(before: ondemand.PlaySession, after: ondemand.PlaySession) -> bool:
    """Whether `after` sends less than `before` did: a smaller picture, or
    the same with clearly less detail."""
    was, now = quality(before), quality(after)
    return now[0] < was[0] or (now[0] == was[0] and 0 < now[1] < was[1] * 0.85)


def routes(app: FastAPI, ctx: AppContext) -> None:
    """The library's addresses for the apps, the play sessions' and the
    Access tab's."""
    cat = ctx.catalog
    settings = ctx.settings

    def proxy() -> httpx.AsyncClient:
        """The one client that fetches files and subtitles from Plex for
        players (made when first needed; closed as StationPlay stops)."""
        if ctx.play_client is None:
            ctx.play_client = httpx.AsyncClient(
                timeout=PROXY_TIMEOUT, transport=ctx.play_transport, follow_redirects=False
            )
        return ctx.play_client

    def person(request: Request) -> tuple[int, str]:
        """Who's asking: (their StationPlay user id, name); (0, "") while
        signing in is off."""
        user = access.signed_in(request)
        return (user.id, user.name) if user else (0, "")

    def shared_here(request: Request) -> None:
        if access.outside(request.scope) and not ctx.away.on:
            raise HTTPException(403, AWAY_OFF)
        if not ctx.shared.on:
            raise HTTPException(404, NONE_SHARED)

    def device_of(request: Request) -> tuple[str, str]:
        """Which device is playing, among those watching (see capacity.py),
        and its tag (see PlaySession.tag): at home, its address; through the
        public port, its app's own key, as for its stations (see away.py)."""
        if not access.outside(request.scope):
            return (request.client.host if request.client else "?"), ""
        token = access.bearer(request.scope) or request.cookies.get(access.COOKIE)
        user = access.signed_in(request)
        key = ctx.away.key_for(access.session_hash(token), user) if token and user else None
        if key is None:
            raise HTTPException(403, AWAY_OFF)
        return away.client(key), key[:6]

    def plays_outside(session_id: str) -> bool:
        """Whether a program's own addresses may be asked for on the public
        port (see access.Access.play_outside): it's going, a signed-in app
        started it there, and watching away from home is still on. (Its
        sign-in is checked as it's asked for: see session_or_404.)"""
        session = ctx.plays.find(session_id)
        return session is not None and session.away and session.sign_in is not None and ctx.away.on

    ctx.access.play_outside = plays_outside
    said_unreachable = [0.0]  # (when the log last said so: see unreachable)
    picture_turns = asyncio.Semaphore(ondemand.PICTURES_AT_ONCE)

    def unreachable(why: str) -> HTTPException:
        """The library can't be reached (503): said in the log, once a
        minute at most, however many apps ask meanwhile."""
        now = time.monotonic()
        if now - said_unreachable[0] >= UNREACHABLE_SAID_S:
            said_unreachable[0] = now
            log.warning("A StationPlay app couldn't be shown your library (%s)", why)
        return HTTPException(503, ondemand.UNREACHABLE)

    @contextlib.asynccontextmanager
    async def asking(request: Request) -> AsyncIterator[None]:
        """Asking the library for what a request needs, within
        LIBRARY_WAIT_S of its first ask, however many things it asks, so no
        request hangs on Plex. What isn't shared (or seen), or the library
        says isn't there, answers 404; the library slow, away or saying what
        can't be read, 503."""
        deadline = getattr(request.state, "library_by", None)
        if deadline is None:
            deadline = request.state.library_by = (
                asyncio.get_running_loop().time() + ondemand.LIBRARY_WAIT_S
            )
        waiting = asyncio.timeout_at(deadline)
        try:
            async with waiting:
                yield
        except NotShared:
            raise HTTPException(404, ondemand.NOT_SHARED) from None
        except LibraryError as e:
            if e.status == 404:  # (Plex's "no such thing" is ours)
                raise HTTPException(404, ondemand.NOT_SHARED) from None
            raise unreachable(str(e)) from None
        except TimeoutError:
            if not waiting.expired():
                raise
            raise unreachable(
                f"Plex didn't answer within {ondemand.LIBRARY_WAIT_S:g} seconds"
            ) from None
        except (KeyError, TypeError, AttributeError, ValueError):
            # (What the library said couldn't be read: as though it were
            # away, rather than a stack trace for the app.)
            log.exception("What Plex said for a StationPlay app couldn't be read")
            raise HTTPException(503, ondemand.UNREACHABLE) from None

    # What each person can see (see viewing.py) ------------------------------

    def viewer_of(request: Request) -> viewing.Viewer:
        return ctx.viewing.viewer(access.signed_in(request))

    async def shows_of(entries: list[Entry]) -> dict[str, Entry]:
        """The shows of the episodes among `entries` (each asked about once,
        and kept a while: see Catalog.entry)."""
        keys = sorted({e.show_key for e in entries if e.kind == catalog.EPISODE and e.show_key})

        async def one(key: str) -> Entry | None:
            try:
                return await cat.entry(key)
            except NotShared:
                return None

        found = await asyncio.gather(*(one(k) for k in keys))
        return {e.key: e for e in found if e is not None}

    async def seen_only(viewer: viewing.Viewer, entries: list[Entry]) -> list[Entry]:
        """Those of `entries` that `viewer` can see: shows and movies by
        their own rating and library, episodes by their show's."""
        if viewer.everything or not entries:
            return entries
        shows = await shows_of(entries)
        return [
            e for e in entries if viewer.sees(viewing.judge_entry(e, shows.get(e.show_key or "")))
        ]

    async def must_see(viewer: viewing.Viewer, entry: Entry) -> None:
        """NotShared (the same answer as for what isn't shared, or doesn't
        exist) unless `viewer` can see `entry`."""
        if not await seen_only(viewer, [entry]):
            raise NotShared(entry.key)

    def library_seen(viewer: viewing.Viewer, key: str) -> bool:
        libraries = viewer.level.libraries
        return viewer.everything or libraries is None or key in libraries

    def unwatched_of(user_id: int, shows: list[Entry]) -> dict[str, int]:
        done = ctx.db.watched_in_shows(user_id, [s.key for s in shows])
        return {s.key: max(0, (s.episodes or 0) - len(done.get(s.key, ()))) for s in shows}

    def cards(user_id: int, entries: list[Entry]) -> list[dict]:
        progress = ctx.db.progress_of(user_id, [e.key for e in entries if e.kind != catalog.SHOW])
        unwatched = unwatched_of(user_id, [e for e in entries if e.kind == catalog.SHOW])
        return [card(e, progress, unwatched.get(e.key)) for e in entries]

    # Browsing --------------------------------------------------------------

    @app.get("/api/internal/libraries")
    async def libraries(request: Request):
        shared_here(request)
        viewer = viewer_of(request)
        async with asking(request):
            found = await cat.libraries()
        return {"libraries": [lib for lib in found if library_seen(viewer, lib["key"])]}

    def unwatched_only(user_id: int, entries: list[Entry]) -> list[Entry]:
        """Those of `entries` this person hasn't finished: movies not watched,
        and shows with episodes not watched."""
        shows = [e for e in entries if e.kind == catalog.SHOW]
        left = unwatched_of(user_id, shows)
        done = ctx.db.progress_of(user_id, [e.key for e in entries if e.kind != catalog.SHOW])
        return [
            e
            for e in entries
            if (
                left.get(e.key, 1) > 0 if e.kind == catalog.SHOW else not done.get(e.key, (0, 0))[1]
            )
        ]

    @app.get("/api/internal/libraries/{key}")
    async def library_page(key: str, request: Request):
        shared_here(request)
        q = request.query_params
        sort = q.get("sort", "title")
        if sort not in ("title", "added", "released"):
            raise HTTPException(400, "sort must be title, added or released")
        start = _whole(q.get("start"), 0, "start", 0, 1_000_000)
        size = _whole(q.get("size"), ondemand.PAGE_DEFAULT, "size", 1, ondemand.PAGE_MOST)
        genre = " ".join(plain(q.get("genre", "")).split())
        if len(genre) > ondemand.GENRE_LONGEST:
            raise HTTPException(400, "That isn't one of this library's genres")
        unwatched = q.get("unwatched", "") in ("1", "true")
        user_id, _ = person(request)
        viewer = viewer_of(request)
        async with asking(request):
            if not library_seen(viewer, key):
                raise NotShared(key)
            title, kind, entries = await cat.whole(key, sort, genre)
            genres = await cat.genres(key)
            entries = await seen_only(viewer, entries)
        if unwatched:
            entries = unwatched_only(user_id, entries)
        return {
            "key": key,
            "title": title,
            "kind": kind,
            "total": len(entries),
            "start": start,
            "items": cards(user_id, entries[start : start + size]),
            "genres": [g["title"] for g in genres],
            "letters": ondemand.letters(entries) if sort == "title" else [],
        }

    @app.get("/api/internal/home")
    async def home(request: Request):
        shared_here(request)
        user_id, _ = person(request)
        viewer = viewer_of(request)
        async with asking(request):
            going = await ondemand.continue_watching(cat, ctx.db, user_id)
            added = await cat.recently_added()
            if not viewer.everything:
                seen = {e.key for e in await seen_only(viewer, [e for e, _ in going])}
                going = [(e, start) for e, start in going if e.key in seen]
                added = [
                    (lib, await seen_only(viewer, entries))
                    for lib, entries in added
                    if library_seen(viewer, lib["key"])
                ]
        going = going[: ondemand.CONTINUE_MOST]
        progress = dict(ctx.db.progress_of(user_id, [e.key for e, _ in going]))
        for e, start in going:  # (where to start, as worked out)
            progress[e.key] = (start, progress.get(e.key, (0, False))[1])
        return {
            "continue": [card(e, progress) for e, _ in going],
            "added": [
                {"library": lib["key"], "title": lib["title"], "items": cards(user_id, entries)}
                for lib, entries in added
                if entries
            ],
        }

    def on_now(words: str, user: User | None) -> list[dict]:
        """The stations (that `user` can see) airing a show or movie whose
        title has `words` in it right now (as search finds titles: see
        ondemand.match), with what's on."""
        wanted, now = ondemand.searchable(words), now_ms()
        out: list[dict] = []
        if not wanted:
            return out
        for channel in ctx.stations_for(user):
            station = ctx.station(channel.id)
            slot = station.locate(now)
            if slot is None:
                continue
            item = slot.item
            title = (
                item.show_title if item.kind == catalog.EPISODE and item.show_title else item.title
            )
            if ondemand.match(wanted, ondemand.searchable(plain(title or ""))) is not None:
                out.append(
                    {
                        "number": channel.number,
                        "name": plain(channel.name),
                        "now": slot_program(station, slot),
                    }
                )
        return out

    @app.get("/api/internal/search")
    async def search(request: Request):
        """The one place your library and the stations meet: what's in the
        library, and which stations are airing it now."""
        words = " ".join(plain(request.query_params.get("q", "")).split())
        if not words:
            raise HTTPException(400, "Type something to search for")
        if len(words) > ondemand.SEARCH_LONGEST:
            raise HTTPException(400, "That's too long to search for")
        user_id, _ = person(request)
        user = access.signed_in(request)
        viewer = viewer_of(request)
        found: list[Entry] = []
        if ctx.media_here(access.outside(request.scope)):
            async with asking(request):
                found = await seen_only(viewer, await cat.search(words))
            found = [e for e in found if library_seen(viewer, e.library)][: ondemand.SEARCH_MOST]
        return {
            "items": cards(user_id, found),
            "onNow": await asyncio.to_thread(on_now, words, user),
        }

    @app.get("/api/internal/items/{key}")
    async def item(key: str, request: Request):
        shared_here(request)
        user_id, _ = person(request)
        viewer = viewer_of(request)
        async with asking(request):
            e = await cat.entry(key)
            await must_see(viewer, e)
            if e.kind == catalog.SHOW:
                episodes = await seen_only(viewer, await cat.episodes(key))
                upcoming = await ondemand.up_next(cat, ctx.db, user_id, key)
                if upcoming is not None and not await seen_only(viewer, [upcoming[0]]):
                    upcoming = None
        if e.kind == catalog.SHOW:
            done = ctx.db.watched_in_shows(user_id, [key]).get(key, set())
            seasons: dict[int, list[Entry]] = {}
            for ep in episodes:
                seasons.setdefault(ep.season if ep.season is not None else -1, []).append(ep)
            nxt = None
            if upcoming is not None:
                ep, start, _why = upcoming
                nxt = card(ep, {ep.key: (start, ep.key in done)})
            return {
                **card(e, {}, max(0, (e.episodes or len(episodes)) - len(done))),
                **details(e),
                "languages": ctx.languages.for_item(user_id, e),
                "seasons": [
                    {
                        "season": n if n >= 0 else None,
                        "title": "Specials" if n == 0 else f"Season {n}" if n > 0 else "Episodes",
                        "episodes": len(eps),
                        "unwatched": sum(1 for x in eps if x.key not in done),
                    }
                    for n, eps in seasons.items()
                ],
                "next": nxt,
            }
        progress = ctx.db.progress_of(user_id, [key])
        media = next(iter(ondemand.best_first(e.media)), None)
        out = {**card(e, progress), **details(e)}
        if e.kind == catalog.EPISODE and e.show_key and not e.has_art:
            out["backdrop"] = art(e.show_key, "backdrop")
        out.update(
            markers=_markers(e),
            picture={"size": media.size_label or None, "hdr": ondemand.hdr_label(media)}
            if media
            else None,
            audio=tracks(media.audio, True) if media else [],
            subtitles=tracks(media.subtitles, False) if media else [],
            versions=versions(e, on_the_list(e)),
            languages=ctx.languages.for_item(user_id, e),
        )
        return out

    # Languages chosen for a show, an episode or a movie (see languages.py) ----

    async def chosen_for(key: str, request: Request) -> Entry:
        """A show, an episode or a movie someone may choose languages for:
        one in a shared library that they can see."""
        shared_here(request)
        async with asking(request):
            e = await cat.entry(key)
            await must_see(viewer_of(request), e)
        if e.kind not in languages.KINDS:
            raise HTTPException(400, "Choose languages for a show, an episode or a movie")
        return e

    @app.put("/api/internal/items/{key}/languages")
    async def set_item_languages(key: str, body: LanguagesIn, request: Request):
        """From the player: languages for a whole show, or an episode or a
        movie alone, for whoever's signed in (null clears one; what isn't
        sent stays)."""
        e = await chosen_for(key, request)
        user_id, _ = person(request)
        try:
            changes = languages.changes(body.given(), own=False)
        except ValueError as ex:
            raise HTTPException(400, str(ex)) from None
        ctx.languages.change(user_id, e.key, changes)
        return ctx.languages.for_item(user_id, e)

    @app.delete("/api/internal/items/{key}/languages")
    async def clear_item_languages(key: str, request: Request):
        e = await chosen_for(key, request)
        user_id, _ = person(request)
        ctx.languages.clear(user_id, e.key)
        return ctx.languages.for_item(user_id, e)

    @app.get("/api/internal/items/{key}/related")
    async def related_to(key: str, request: Request):
        """Others like a show or movie, from its own library (an episode's:
        its show's)."""
        shared_here(request)
        user_id, _ = person(request)
        viewer = viewer_of(request)
        async with asking(request):
            e = await cat.entry(key)
            await must_see(viewer, e)
            if e.kind == catalog.EPISODE and e.show_key:
                e = await cat.entry(e.show_key)
            found: list[Entry] = []
            if e.library and library_seen(viewer, e.library) and e.genres:
                _, _, pool = await cat.whole(e.library, "title")
                found = ondemand.related(e, await seen_only(viewer, pool))
        return {"items": cards(user_id, found)}

    @app.get("/api/internal/items/{key}/episodes")
    async def episodes_of(key: str, request: Request):
        shared_here(request)
        q = request.query_params
        season_text = q.get("season")
        season = _whole(season_text, -1, "season", 0, 100_000) if season_text else None
        start = _whole(q.get("start"), 0, "start", 0, 1_000_000)
        size = _whole(q.get("size"), ondemand.EPISODES_MOST, "size", 1, ondemand.EPISODES_MOST)
        user_id, _ = person(request)
        viewer = viewer_of(request)
        async with asking(request):
            e = await cat.entry(key)
            await must_see(viewer, e)
            if e.kind != catalog.SHOW:
                raise HTTPException(400, "That isn't a show")
            found = await seen_only(viewer, await cat.episodes(key))
        chosen = [x for x in found if season is None or x.season == season]
        return {
            "show": key,
            "season": season,
            "total": len(chosen),
            "start": start,
            "episodes": cards(user_id, chosen[start : start + size]),
        }

    @app.get("/api/internal/art/{key}")
    async def picture(key: str, request: Request):
        shared_here(request)
        kind = request.query_params.get("kind", "poster")
        if kind not in ondemand.PICTURE_KINDS:
            raise HTTPException(400, "kind must be poster, backdrop or thumb")
        width = ondemand.width_for(_whole(request.query_params.get("w"), 320, "w", 1, 10_000))
        viewer = viewer_of(request)
        async with asking(request):
            await cat.check(key)  # (shared now, even if its picture was kept from before)
            if not viewer.everything:
                await must_see(viewer, await cat.entry(key))
        kept = ctx.app_pictures.get((key, kind, width))
        if kept is None:
            # (An episode's poster is its show's; a show's still, its poster.)
            which = "art" if kind == "backdrop" else "thumb"
            async with asking(request):
                e = await cat.entry(key)
                target = e.show_key if e.kind == catalog.EPISODE and kind != "thumb" else e.key
                shown = e if not target or target == e.key else await cat.entry(target)
            if not (shown.has_art if which == "art" else shown.has_thumb):
                raise HTTPException(404, NO_PICTURE)  # (the library has none: no need to ask)
            height = width * 3 // 2 if kind == "poster" else width * 9 // 16
            try:
                async with asking(request), picture_turns:
                    got = await ctx.library.picture(shown.key, which, width, height)
            except httpx.HTTPStatusError:
                raise HTTPException(404, NO_PICTURE) from None
            except httpx.HTTPError as ex:
                raise unreachable(f"a picture didn't come: {type(ex).__name__}") from None
            kept = ctx.app_pictures.put((key, kind, width), got)
        data, content_type, tag = kept
        headers = {
            "Cache-Control": "private, max-age=86400",
            "ETag": tag,
            "X-Content-Type-Options": "nosniff",
        }
        if {tag, "*"} & _tags(request.headers.get("if-none-match", "")):
            return Response(status_code=304, headers=headers)  # (the app has it already)
        return Response(data, media_type=content_type, headers=headers)

    # Playing ---------------------------------------------------------------

    def found_in(e: Entry) -> list[tuple[Media, str]]:
        """The versions of a program whose files StationPlay found broken
        (it can't play) or damaged (it plays, but breaks up in places): see
        broken.py. (Unsupported is the stations' alone: the apps play by
        what each device shows.)"""
        out = []
        for m in e.media:
            found = ctx.broken.entry(version_key(e.key, sc.version_of(e, m)))
            if found is not None and found.get("problem") in ("broken", "damaged"):
                out.append((m, str(found["problem"])))
        return out

    def on_the_list(e: Entry) -> dict[str, str]:
        """What found_in says, by version ID."""
        return {m.id: problem for m, problem in found_in(e) if m.id}

    def trouble(session: ondemand.PlaySession, at_s: float, why: str) -> None:
        """Making a copy failed: the file's checked there (see
        scanner.trouble), in case it's the file's fault."""
        who = session.user or "someone"
        sc.trouble(
            ctx, session.entry, session.media, at_s, f"making a copy for {who} stopped ({why})"
        )

    async def source_of(e: Entry, media: Media) -> tuple[str | None, str | None]:
        """Where a version's file is read from: (its path, where StationPlay
        can read it itself; otherwise Plex's address for it)."""
        path = None
        if media.file:
            found, _timed_out = await find_first(
                local_candidates(settings, ctx.media_access, media.file)
            )
            if found is not None:
                learn_mapping(ctx.media_access, found)
                path = found.path
        stream = (
            ctx.library.stream_url(e.key, media.part_key)
            if path is None and media.part_key and ctx.library.configured
            else None
        )
        return path, stream

    def reader(path: str | None, stream: str | None) -> keyframes.Reader:
        """Reads part of a file: from disk, or from Plex a range at a time."""

        async def from_disk(offset: int, size: int) -> bytes:
            def read() -> bytes:
                with open(path or "", "rb") as f:
                    f.seek(offset)
                    return f.read(size)

            try:
                return await asyncio.to_thread(read)
            except OSError:
                return b""

        async def from_plex(offset: int, size: int) -> bytes:
            asked = {"range": f"bytes={offset}-{offset + size - 1}", "accept-encoding": "identity"}
            client = proxy()
            try:
                got = await client.send(
                    client.build_request("GET", stream or "", headers=asked), stream=True
                )
            except httpx.HTTPError:
                return b""
            try:
                if got.status_code != 206:  # (never the whole file, for a part of it)
                    return b""
                data = bytearray()
                async for part in got.aiter_bytes():
                    data += part
                    if len(data) >= size:
                        break
                return bytes(data[:size])
            except httpx.HTTPError:
                return b""
            finally:
                await got.aclose()

        return from_disk if path else from_plex

    async def fetch_subtitles(url: str, target: Path) -> bool:
        """A subtitle file of its own, fetched from Plex to be drawn in."""
        try:
            got = await proxy().get(url)
            got.raise_for_status()
            if len(got.content) > SUBTITLES_MOST:
                return False
            await asyncio.to_thread(target.write_bytes, got.content)
        except (httpx.HTTPError, OSError) as e:
            log.warning("Couldn't fetch a subtitle file to draw in (%s)", type(e).__name__)
            return False
        return True

    def app_of(body: PlayAsk, request: Request) -> str:
        """Which app on which device is playing: as it says, or else as its
        sign-in says."""
        if body.app or body.deviceName:
            return app_label(body.app, body.deviceName)
        token = access.bearer(request.scope) or request.cookies.get(access.COOKIE)
        known = ctx.db.session_app(access.session_hash(token)) if token else None
        return known or app_label("", "")

    def sign_in_of(request: Request, name: str) -> str | None:
        """The sign-in a program is played with (its token's hash), if
        signing in is on."""
        token = access.bearer(request.scope) or request.cookies.get(access.COOKIE)
        return access.session_hash(token) if name and token else None

    def said_stop(session: ondemand.PlaySession) -> None:
        """The log's line for something stopping in an app: who, what, where
        they stopped, and for how long they watched."""
        at = session.position_ms
        log.info(
            "%s stopped %s%s%s (watched %s)",
            session.user or "Someone",
            describe(session.entry),
            " away from home" if session.away else "",
            f" at {playing.clock(at / 1000)}" if at is not None else "",
            playing.minutes(session.watched_s),
        )

    def one_at_a_time(sign_in: str | None, client: str, e: Entry) -> None:
        """A device plays one program at a time: starting one ends what it
        was playing (said in the log as leaving it says it, unless it's the
        same program again: another sound track, or a smaller version), and
        the copy being made for it, if any."""
        for old in ctx.plays.on_device(sign_in, client):
            ctx.plays.end(old.id)
            if old.entry.key != e.key:
                said_stop(old)

    def said_start(
        session: ondemand.PlaySession, sound: Track | None, how: str, from_plex: bool
    ) -> None:
        """The log's line for something starting to play in an app: who,
        in which app, what, its file, and how it plays."""
        if session.media.parts > 1:
            # (Its files can't be played one after another as one yet.)
            log.info(
                "%s is split into %d files in Plex; StationPlay's apps play only the first",
                describe(session.entry),
                session.media.parts,
            )
        log.info(
            "%s started %s in %s, %s: %s (%s)%s, %s",
            session.user or "Someone",
            describe(session.entry),
            in_sentence(session.app or app_label("", "")),
            "away from home" if session.away else "at home",
            playing.file_name(session.media.file or ""),
            sound_of(session.media, sound),
            " from Plex" if from_plex else "",
            how,
        )

    def noted_away(session: ondemand.PlaySession, request: Request) -> None:
        """Something started playing through the public port: in the access
        log too, as a station watched away from home is (once a play: not
        again for another sound track, or a smaller version)."""
        if session.away:
            ctx.access.record(
                logging.INFO,
                f"{session.user or 'Someone'} is playing {describe(session.entry)} away from "
                f"home, from {access.where(request.scope)}",
            )

    def over_the_limit(
        over: tuple[str, int], body: PlayAsk, request: Request, e: Entry, tag: str
    ) -> JSONResponse:
        """One more device than an Admin's limits allow (see capacity.py):
        said in the log, and told why."""
        limit, most = over
        user_id, name = person(request)
        away_ = access.outside(request.scope)
        home = request.client.host if request.client else "?"
        where = access.address(request.scope) if away_ else home
        who = playing.Watcher(where, away_, name, user_id or None, app_of(body, request), tag)
        log.warning(
            "The limit of %s watching%s at once (set on the Access tab) was reached, so %s "
            "couldn't play %s",
            capacity.devices(most),
            " away from home" if limit == "away" else "",
            who.subject(start=False),
            describe(e),
        )
        return JSONResponse(
            {"detail": capacity.refused_because(limit, most), "limit": limit, "most": most},
            status_code=503,
        )

    def said_step_down(
        before: ondemand.PlaySession | None,
        after: ondemand.PlaySession,
        body: PlayAsk,
        request: Request,
        cap: int | None = None,
    ) -> bool:
        """Says in the log (and True) if a device just went to a smaller
        version or copy of what it was playing: from what to what, and why
        (the app's own reason, if it sent one: see problems.py; or away
        from home, the Admin's cap, `cap`, where a version is over it)."""
        if before is None or not stepped_down(before, after):
            return False
        who = playing.Watcher(
            access.address(request.scope) if after.away else after.client,
            after.away, after.user, after.user_id or None, after.app, after.tag,
        )  # fmt: skip
        fits = f" (about {playing.mbps(body.maxKbps)})" if body.maxKbps else ""
        if body.fit or body.maxKbps:
            why = f"to fit its connection{fits}"
        elif cap and any(ondemand.over_cap(m, cap) for m in after.entry.media):
            why = f"to fit the {playing.mbps(cap)} allowed away from home"
        else:
            why = "the app asked for it"
        said = ctx.problems.said_lately(access.address(request.scope), STEP_S)
        log.info(
            "%s switched %s to a smaller %s, from %s to %s: %s%s",
            who.subject(),
            describe(after.entry),
            "version" if after.copy is None or after.copy.plan.copies_picture else "copy",
            quality(before)[2],
            quality(after)[2],
            why,
            f"; the app said: {said}" if said else "",
        )
        return True

    def drawn_for(
        picked: languages.Picked | None, shows: frozenset[str], copy: bool
    ) -> Track | None:
        """The subtitle chosen for someone from their languages (see
        languages.py) that's drawn into the picture, as an app's `subtitle`
        is: one the player doesn't show itself (`shows`: the formats it
        does), and in a copy (`copy`), one inside the file too, as a copy
        holds none. Only one StationPlay can draw: otherwise none."""
        found = picked.subtitle if picked else None
        if found is None or (found.codec in shows and (found.external or not copy)):
            return None
        if converting.picture_subtitles(found):
            return None if found.external else found
        return found if ctx.subtitling and (not found.external or found.id.isdigit()) else None

    def shown_for(
        picked: languages.Picked | None, drawn: Track | None, shows: frozenset[str], copy: bool
    ) -> Track | None:
        """The subtitle chosen for someone that's shown: drawn in, or by the
        player itself (in a copy, only a file of its own, added beside it)."""
        found = picked.subtitle if picked else None
        if found is None or drawn is not None:
            return drawn
        return found if found.codec in shows and (found.external or not copy) else None

    async def play_copy(
        body: PlayAsk,
        request: Request,
        e: Entry,
        dev: ondemand.Device,
        hls: frozenset[str],
        client: str,
        tag: str,
        cap: int | None,
        even: bool,
        only_sound: Media | None = None,
        wanted: languages.Wanted | None = None,
        shows: frozenset[str] = frozenset(),
        passed_over: tuple[Media, ...] = (),
    ) -> Any:
        """Playing a copy StationPlay makes (see converting.py), for a device
        that can't play the file as it is, or for subtitles drawn in, a
        smaller picture made to fit, night mode's sound, or away from home,
        a file over the Admin's cap (`cap`, in kbps) converted down to fit
        it; with even sound for a show's episodes (`even`), whatever it's
        made for. (`client` and `tag`: the device, as device_of says.) Its
        sound and subtitles are the app's (`audio`, `subtitle`), or else
        chosen from what the person wants (`wanted`: see languages.py; with
        `shows`, the subtitle formats the player shows itself).

        `only_sound`: a version the device plays as it is, copied only for
        even sound: its picture kept as it is, and only its sound made. None
        (play it as it is, then) if its picture can't be kept.
        `passed_over`: versions StationPlay found broken, never made a copy
        of."""
        user_id, name = person(request)
        away_ = access.outside(request.scope)
        usable = [m for m in e.media if m not in passed_over]
        versions = [m for m in ondemand.best_first(usable) if m.id] or usable
        asked = [m for m in versions if body.version and m.id == body.version]
        smaller = body.fit and body.maxKbps is not None

        def refuse(why: list[str]) -> JSONResponse:
            log.info("StationPlay can't make a copy of %s for an app (%s)", describe(e),
                     ondemand.and_list(why))  # fmt: skip
            return JSONResponse({"detail": cant_copy(why), "why": why}, status_code=422)

        def draws(m: Media) -> Track | None:
            return drawn_for(languages.pick(m, wanted) if wanted else None, shows, copy=True)

        # The version: the one asked for; or the best one whose picture can
        # be kept (away from home, within the cap); or for converting, the
        # smallest that's still big enough.
        media = only_sound or (asked[0] if asked else None)
        if media is None:
            keepable = [m for m in versions
                        if converting.picture_copyable(m, ondemand.unplayable(m, dev), hls)
                        and not ondemand.over_cap(m, cap)]  # fmt: skip
            if keepable and not (body.subtitle or smaller or draws(keepable[0])):
                media = keepable[0]
            else:
                tall = [m for m in versions if m.height >= converting.CONVERT_MOST_HEIGHT]
                media = tall[-1] if tall else versions[0]
        picked = languages.pick(media, wanted) if wanted else None
        to_draw = draws(media)
        subtitle = body.subtitle if picked is None else to_draw.id if to_draw else None
        if only_sound and subtitle:
            return None  # (only the picture as it is will do: the file plays as it is)
        capped = ondemand.over_cap(media, cap)
        why = ondemand.unplayable(media, dev)
        sound = converting.audio_track(
            media, picked.audio.id if picked and picked.audio else body.audio
        )
        even = even and sound is not None  # (no sound, nothing to even)
        if only_sound and not even:
            return None
        if sound is not None and sound.codec and sound.codec not in dev.audio:
            label = f"its sound's format ({ondemand.label(sound.codec)})"
            if label not in why:
                why.append(label)
        shown = next((t for t in media.subtitles if t.id == subtitle), None)
        if shown is not None:
            why.append("its subtitles, drawn into the picture")
        if smaller:
            why.append("a smaller picture, to fit the connection")
        if capped and cap:
            why.append(f"a smaller copy, within the {playing.mbps(cap)} allowed away from home")
        if even:
            why.append(EVEN_WHY)
        if body.night:
            why.append("night mode's sound")
        duration_s = (media.duration_ms or e.duration_ms or 0) / 1000
        if duration_s <= 0:
            return None if only_sound else refuse(["how long it is isn't known"])
        path, stream = await source_of(e, media)
        source = path or stream
        if source is None:
            raise HTTPException(503, NO_FILE)
        # Keeping the picture as it is, where it can be (its keyframes
        # known from the file's index); otherwise converting it.
        starts: tuple[float, ...] = ()
        keep = converting.picture_copyable(media, why, hls) and not (shown or smaller or capped)
        if keep:
            try:
                found = await asyncio.wait_for(
                    keyframes.keyframes(reader(path, stream), media.container), KEYFRAMES_WAIT_S
                )
            except TimeoutError:
                found = None
            if found:
                starts = converting.pieces_at(found, duration_s)
        if only_sound and not starts:
            return None  # (only the picture as it is will do: the file plays as it is)
        audio_codec, channels = converting.sound_for(sound, dev.audio, body.night, even)
        if starts:
            method, height, kbps, tone_map = converting.REPACKAGE, 0, 0, ""
        else:
            method, tone_map = converting.CONVERT, ""
            if ondemand.needs_dolby_vision(media):
                return refuse(["its Dolby Vision profile 5 picture"])
            if media.hdr:
                if not ctx.tone_mapping:
                    return refuse([f"its {ondemand.hdr_label(media)} picture"])
                tone_map = to_sdr(ProbeResult(
                    ok=True, hdr="arib-std-b67" if media.hdr == catalog.HLG else "smpte2084"))  # fmt: skip
            if "h264" not in dev.video:
                return refuse(["this device doesn't play H.264"])
            on_gpu = ctx.gpu is not None and ctx.gpu.encoder_for_copies().is_gpu
            # (Not counting this device's own, which this one takes over from.)
            mine = ctx.plays.on_device(sign_in_of(request, name), client)
            if ctx.plays.copies(besides=mine) >= (
                CONVERTING_MOST_GPU if on_gpu else CONVERTING_MOST
            ):
                raise HTTPException(503, BUSY_CONVERTING)
            # (Away from home, never more than the cap, whatever it's converted for.)
            height, kbps = converting.convert_size(
                media, dev.video["h264"][1], body.maxKbps if smaller else None,
                cap, converting.sound_kbps(audio_codec, channels),
            )  # fmt: skip
            starts = converting.pieces_every(duration_s)
        # Subtitles drawn in: a picture track as it is; text in the file,
        # read out first; a file of its own, fetched first.
        drawn: Subtitles | None = None
        first: Any = None
        fetch_from: str | None = None  # (a subtitle file of its own, fetched to be drawn in)
        if shown is not None:
            inside = [t for t in sorted(media.subtitles, key=lambda t: t.index or 0)
                      if not t.external]  # fmt: skip
            nth = next((i for i, t in enumerate(inside) if t.id == shown.id), None)
            styled = shown.codec == "ass"
            if converting.picture_subtitles(shown) and nth is not None:
                drawn = Subtitles(stream=nth, image=True)
            elif converting.picture_subtitles(shown):
                return refuse(["its subtitles (a picture subtitle file of its own)"])
            elif not ctx.subtitling:
                return refuse(["its subtitles (StationPlay can't draw text subtitles)"])
            elif shown.external:
                fetch_from = ctx.library.stream_url(e.key, f"/library/streams/{shown.id}")
                if fetch_from is None or not shown.id.isdigit():
                    return refuse(["its subtitles"])
            elif nth is not None:
                key = f"{source.split('?')[0]}|{nth}|{media.size}|{media.id}"
                job = subtitles.Extraction(source, nth, settings.data_dir / subtitles.FOLDER
                                           / f"app-{hashlib.sha1(key.encode()).hexdigest()[:24]}.ass",
                                           styled)  # fmt: skip
                try:
                    await asyncio.to_thread(job.target.parent.mkdir, parents=True, exist_ok=True)
                except OSError as ex:
                    log.warning("A copy for a StationPlay app couldn't be made (%s)", ex)
                    raise HTTPException(503, COPY_FAILED) from None
                drawn = job.ready()
                if not job.target.exists():
                    first = subtitles.extract(settings, job)
            else:
                return refuse(["its subtitles"])
        if (over := ctx.capacity.refusal(ctx.app_watchers(), client, away_)) is not None:
            return over_the_limit(over, body, request, e, tag)
        try:
            folder = await asyncio.to_thread(converting.new_folder)
        except OSError as ex:  # (the disk full, say)
            log.warning("A copy for a StationPlay app couldn't be made (%s)", ex)
            raise HTTPException(503, COPY_FAILED) from None
        if fetch_from is not None and shown is not None:
            target = (
                folder
                / f"subtitles.{shown.codec if shown.codec in ('srt', 'ass', 'vtt') else 'srt'}"
            )
            drawn = Subtitles(path=str(target), styled=shown.codec == "ass")
            first = fetch_subtitles(fetch_from, target)
        plan = converting.Plan(
            method=method, why=tuple(why), starts=starts, duration_s=duration_s, audio=sound,
            audio_codec=audio_codec, audio_channels=channels, picture=media.video,
            night=body.night, even=even, height=height,
            kbps=kbps, tone_map=tone_map, subtitles=drawn, drawn=shown.id if shown else None,
        )  # fmt: skip
        task = asyncio.ensure_future(first) if first is not None else None
        label = app_of(body, request)
        before = ctx.plays.before(user_id, e.key, client, STEP_S)
        again = ctx.plays.before(user_id, e.key, client) is not None
        sign_in = sign_in_of(request, name)
        one_at_a_time(sign_in, client, e)
        session = ctx.plays.start(
            user_id=user_id, user=name, sign_in=sign_in,
            entry=e, media=media, path=path, plex=stream, client=client, away=away_, app=label,
            tag=tag,
            subtitles={
                t.id: (url, t.codec)
                for t in media.subtitles
                if t.external and t.id.isdigit()
                and (url := ctx.library.stream_url(e.key, f"/library/streams/{t.id}"))
            },
        )  # fmt: skip
        session.copy = converting.Copy(settings.ffmpeg_path, source, plan, folder, first=task,
                                       gpu=ctx.gpu, name=describe(e))  # fmt: skip
        session.copy.trouble = lambda at_s, why: trouble(session, at_s, why)
        resume = ondemand.resume_at(ctx.db.progress_of(user_id, [e.key]).get(e.key))
        session.start_s = (body.startMs if body.startMs is not None else resume) / 1000
        cant = ondemand.unplayable(media, dev)
        if sound is not None and sound.codec and sound.codec not in dev.audio:
            cant.append(f"its sound's format ({ondemand.label(sound.codec)})")
        how = how_copied(
            plan, list(dict.fromkeys(cant)), smaller, session.copy.encoder, cap if capped else None
        )
        if not said_step_down(before, session, body, request, cap):
            said_start(session, sound, how, path is None)
        if not again:
            noted_away(session, request)
        here = f"/play/{session.id}"
        return {
            "session": session.id,
            "method": method,
            "url": f"{here}/index.m3u8",
            "why": why,
            "audioTrack": sound.id if sound else None,
            "drawnSubtitle": shown.id if shown else None,
            "chosen": chosen(picked, sound, shown_for(picked, shown, shows, copy=True)),
            "leave": f"{here}/leave",
            "resumeMs": resume,
            "durationMs": media.duration_ms or e.duration_ms,
            "bitrateKbps": plan.kbps_needed or media.bitrate_kbps,
            "version": media.id or None,
            "versions": playable_versions(e, dev, body.maxKbps, on_the_list(e)),
            "whenSlow": ctx.shared.when_slow["away" if away_ else "home"],
            "markers": _markers(e),
            "audio": tracks(media.audio, True),
            "subtitles": [
                {
                    **t,
                    "url": f"{here}/subtitles/{t['id']}.{t['codec']}"
                    if t["external"] and t["id"] in session.subtitles
                    else None,
                }
                for t in tracks(media.subtitles, False)
            ],
        }

    def instead_of(
        e: Entry,
        broken: tuple[Media, ...],
        body: PlayAsk,
        dev: ondemand.Device,
        cap: int | None,
    ) -> str | None:
        """Why another version plays, when the one that would have (the one
        asked for, or else the one chosen for the device) is one StationPlay
        found broken; None when it isn't."""
        if not broken:
            return None
        best = ondemand.best_first(e.media)
        asked = next((m for m in best if body.version and m.id == body.version), None)
        would = asked or ondemand.choose(e, dev, None, body.maxKbps, cap)[0] or best[0]
        if would not in broken:
            return None
        name = ondemand.version_labels(best)[best.index(would)]
        log.info(
            "%s: another version plays in StationPlay's apps, as StationPlay found the %s one "
            "broken",
            describe(e),
            name,
        )
        return f"another version, as {name} can't play right now"

    def with_instead(answer: Any, instead: str | None) -> Any:
        """A copy's answer, its `why` saying another version plays (see
        instead_of), if one does."""
        if instead and isinstance(answer, dict):
            answer["why"] = [*(answer.get("why") or []), instead]
        return answer

    @app.post("/api/internal/play")
    async def play(body: PlayAsk, request: Request):
        shared_here(request)
        user_id, name = person(request)
        async with asking(request):
            e = await cat.entry(body.key)
            await must_see(viewer_of(request), e)
        if e.kind not in (catalog.EPISODE, catalog.MOVIE):
            raise HTTPException(400, NOT_PLAYABLE)
        if not e.media:
            raise HTTPException(404, "This program has no file to play")
        # What StationPlay found broken never plays: another version of it
        # does, if there's one it didn't (and the answer says so).
        broken = tuple(m for m, problem in found_in(e) if problem == "broken")
        if len(broken) >= len(e.media):
            log.info(
                "A StationPlay app asked to play %s, but StationPlay found its file broken (see "
                "the Broken files tab)",
                describe(e),
            )
            why = ["StationPlay found its file broken"]
            return JSONResponse({"detail": ON_THE_LIST, "why": why}, status_code=422)
        usable = replace(e, media=tuple(m for m in e.media if m not in broken)) if broken else e
        dev = ondemand.device(
            body.device.containers,
            [(v.codec, v.width, v.height, v.bitDepth) for v in body.device.video],
            body.device.hdr,
            body.device.audio,
        )
        # Away from home (through the public port), at the Admin's quality
        # there: a version within the cap plays as it would at home, and one
        # over it is converted down to fit (see away.py).
        away_ = access.outside(request.scope)
        client, tag = device_of(request)
        cap = ctx.away.media_kbps if away_ else None
        instead = instead_of(e, broken, body, dev, cap)
        media, why = ondemand.choose(usable, dev, body.version, body.maxKbps, cap)
        hls = frozenset(h.strip().lower() for h in body.device.hls)
        # The tracks this person wants (see languages.py), unless the app
        # says which itself: then exactly those, as before. A subtitle chosen
        # for them that the player doesn't show itself is drawn in, as the
        # app's `subtitle` is.
        told = bool({"audio", "subtitle"} & body.model_fields_set)
        wanted = None if told else ctx.languages.wanted(user_id, e)
        shows = frozenset(catalog.subtitle_codec(f) for f in body.device.subtitles)
        picked = languages.pick(media, wanted) if wanted and media is not None else None
        drawn = drawn_for(picked, shows, copy=False)
        audio = picked.audio.id if picked and picked.audio else body.audio
        sound = converting.audio_track(media, audio) if media is not None else None
        capped = media is not None and ondemand.over_cap(media, cap)
        as_it_is = (
            media is not None
            and not capped
            and not (body.subtitle or drawn or body.fit or body.night)
            and (sound is None or not sound.codec or sound.codec in dev.audio)
        )
        # Even sound for a show's episodes (as the stations' episodes have it,
        # whatever the order or the app), where an Admin has it on: never a
        # movie.
        even = ctx.shared.even_sound and e.kind == catalog.EPISODE
        if not as_it_is and "ts" in hls:
            copied = await play_copy(
                body, request, e, dev, hls, client, tag, cap, even, wanted=wanted, shows=shows,
                passed_over=broken,
            )  # fmt: skip
            return with_instead(copied, instead)
        if media is None:
            log.info(
                "A StationPlay app can't play %s as it is (%s)", describe(e), ondemand.and_list(why)
            )
            return JSONResponse({"detail": ondemand.cant_play(why), "why": why}, status_code=422)
        if capped and cap:
            # (An app that can't take a copy made to fit.)
            need = playing.mbps(ondemand.needs_kbps(media) or 0)
            why = [f"it needs {need}, more than the {playing.mbps(cap)} allowed away from home"]
            log.info("A StationPlay app can't play %s away from home (%s)", describe(e), why[0])
            return JSONResponse({"detail": too_fast(need, cap), "why": why}, status_code=422)
        # (A subtitle inside the file, chosen for them, that the player shows
        # itself: a copy would hold none, so the file plays as it is.)
        mine = shown_for(picked, None, shows, copy=False)
        inside = mine is not None and not mine.external
        if even and "ts" in hls and sound is not None and not inside:
            # (As night mode's sound is made for an app that can't make it:
            # the picture as it is, only the sound made. Where the picture
            # can't be kept as it is, the file plays as it is: even sound
            # never costs a picture made again.)
            copied = await play_copy(
                body, request, e, dev, hls, client, tag, cap, even, media, wanted, shows, broken
            )
            if copied is not None:
                return with_instead(copied, instead)
        if (over := ctx.capacity.refusal(ctx.app_watchers(), client, away_)) is not None:
            return over_the_limit(over, body, request, e, tag)
        path = None
        if media.file:
            found, _timed_out = await find_first(
                local_candidates(settings, ctx.media_access, media.file)
            )
            if found is not None:
                learn_mapping(ctx.media_access, found)
                path = found.path
        stream = (
            ctx.library.stream_url(e.key, media.part_key)
            if path is None and media.part_key and ctx.library.configured
            else None
        )
        if path is None and stream is None:
            raise HTTPException(503, NO_FILE)
        before = ctx.plays.before(user_id, e.key, client, STEP_S)
        again = ctx.plays.before(user_id, e.key, client) is not None
        sign_in = sign_in_of(request, name)
        one_at_a_time(sign_in, client, e)
        session = ctx.plays.start(
            user_id=user_id,
            user=name,
            sign_in=sign_in,
            entry=e,
            media=media,
            path=path,
            plex=stream,
            client=client,
            away=away_,
            app=app_of(body, request),
            tag=tag,
            subtitles={
                t.id: (url, t.codec)
                for t in media.subtitles
                if t.external
                and t.id.isdigit()
                and (url := ctx.library.stream_url(e.key, f"/library/streams/{t.id}"))
            },
        )
        if not said_step_down(before, session, body, request, cap):
            said_start(session, sound or media.default_audio, "playing as it is", path is None)
        if not again:
            noted_away(session, request)
        here = f"/play/{session.id}"
        return {
            "session": session.id,
            "method": "direct",
            "url": f"{here}/file.{media.container or 'mkv'}",
            "why": [instead] if instead else None,
            "audioTrack": None,
            "drawnSubtitle": None,
            "chosen": chosen(picked, sound, shown_for(picked, None, shows, copy=False)),
            "leave": f"{here}/leave",
            "resumeMs": ondemand.resume_at(ctx.db.progress_of(user_id, [e.key]).get(e.key)),
            "durationMs": media.duration_ms or e.duration_ms,
            "bitrateKbps": media.bitrate_kbps,
            "version": media.id or None,
            "versions": playable_versions(e, dev, body.maxKbps, on_the_list(e)),
            "whenSlow": ctx.shared.when_slow["away" if away_ else "home"],
            "markers": _markers(e),
            "audio": tracks(media.audio, True),
            "subtitles": [
                {
                    **t,
                    "url": f"{here}/subtitles/{t['id']}.{t['codec']}"
                    if t["external"] and t["id"] in session.subtitles
                    else None,
                }
                for t in tracks(media.subtitles, False)
            ],
        }

    @app.post("/api/internal/progress")
    async def progress(body: ProgressReport, request: Request):
        """Where someone is in an episode or a movie, or marked watched (or
        not) from a menu (see docs/on-demand.md, "Progress"). Nothing is
        sent on to Plex, and while it plays (`session`), Plex isn't asked."""
        shared_here(request)
        user_id, _ = person(request)
        if body.positionMs is None and body.watched is None:
            raise HTTPException(400, "Send positionMs, or watched")
        # Its own playing (or one just ended): still watching, and the order
        # of its reports. Through the public port, only one started there.
        playing_ = ctx.plays.find(body.session or "") or ctx.plays.ended(body.session or "")
        mine = (
            playing_ is not None
            and playing_.entry.key == body.key
            and playing_.user_id == user_id
            and (playing_.away or not access.outside(request.scope))
        )
        session = playing_ if mine else None
        async with asking(request):
            e = session.entry if session is not None else await cat.entry(body.key)
            if not cat.shared_library(e):
                raise NotShared(e.key)
            await must_see(viewer_of(request), e)
        if e.kind not in (catalog.EPISODE, catalog.MOVIE):
            raise HTTPException(400, NOT_PLAYABLE)
        kept = ctx.db.progress_of(user_id, [e.key]).get(e.key)
        if session is not None and body.sequence is not None:
            if body.sequence <= session.sequence:
                # (Sent before one already here: it never moves them back.)
                was = kept or (0, False)
                return {"positionMs": ondemand.resume_at(was), "watched": was[1]}
            session.sequence = body.sequence
        length = ondemand.length_of(e, session.media if session is not None else None)
        # (Past the end of what plays; without its playing, of its longest version.)
        longest = max([length or 0, *(m.duration_ms or 0 for m in e.media if session is None)])
        if body.positionMs is not None and longest and body.positionMs > longest + PAST_END_MS:
            raise HTTPException(400, PAST_END)
        if session is not None and ctx.plays.find(session.id) is session:
            ctx.plays.get(session.id)  # (still watching)
            if body.positionMs is not None:
                session.position_ms = body.positionMs
        if body.watched is not None:
            position, watched = 0, body.watched
        else:
            position, watched = ondemand.progressed(kept, body.positionMs or 0, e, length)
        now = int(time.time() * 1000)
        # An episode in one file with others ("S01E01-E02"): they're where it is.
        together = [
            x for x in cat.kept_episodes(e.show_key or "") if e.file and x.file == e.file
        ] or [e]
        for x in together:
            ctx.db.save_progress(user_id, x.key, x.show_key, position, e.duration_ms or 0,
                                 watched, now)  # fmt: skip
        return {"positionMs": ondemand.resume_at((position, watched)), "watched": watched}

    # The play sessions' own addresses (a player can't sign in) ---------------

    def session_or_404(session_id: str, request: Request) -> ondemand.PlaySession:
        """A play session that's still good, now marked as used: its library
        still shared, and its sign-in (if signing in is on) still good.
        Through the public port, only one an app started there, while
        watching away from home is on, with its sign-in checked every time
        (at home, every RECHECK_S)."""
        outside = access.outside(request.scope)
        session = ctx.plays.find(session_id)
        if session is None or (outside and not session.away):
            raise HTTPException(404, PLAY_ENDED)
        now = time.monotonic()
        ended = (
            not cat.shared_library(session.entry)
            or (ctx.access.required and session.sign_in is None)
            or (session.away and not ctx.away.on)
        )
        if (
            not ended
            and session.sign_in
            and (outside or now - session.checked > ondemand.RECHECK_S)
        ):
            ended = ctx.access.session_user_hashed(session.sign_in) is None
            session.checked = now
        if ended:
            ctx.plays.end(session_id)
            raise HTTPException(404, PLAY_ENDED)
        session.used(now)
        return session

    @app.api_route("/play/{session_id}/file.{ext}", methods=["GET", "HEAD"])
    async def play_file(session_id: str, ext: str, request: Request):
        session = session_or_404(session_id, request)
        kind = _TYPES.get(session.media.container, "application/octet-stream")
        if session.path is not None:
            if not await asyncio.to_thread(Path(session.path).is_file):
                raise HTTPException(503, NO_FILE)
            return FileResponse(
                session.path, media_type=kind, headers={"Cache-Control": "no-store"}
            )
        assert session.plex is not None
        if request.method == "HEAD" and session.media.size:
            return Response(
                headers={
                    "Content-Length": str(session.media.size),
                    "Accept-Ranges": "bytes",
                    "Content-Type": kind,
                    "Cache-Control": "no-store",
                }
            )
        return await _from_plex(proxy(), session.plex, request, kind)

    @app.get("/play/{session_id}/index.m3u8")
    async def copy_playlist(session_id: str, request: Request):
        session = session_or_404(session_id, request)
        if session.copy is None:
            raise HTTPException(404, PLAY_ENDED)
        return Response(
            session.copy.playlist(session.start_s),
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/play/{session_id}/piece-{n}.ts")
    async def copy_piece(session_id: str, n: int, request: Request):
        session = session_or_404(session_id, request)
        if session.copy is None:
            raise HTTPException(404, PLAY_ENDED)
        found = await session.copy.piece(n, request.is_disconnected)
        if found is None:
            if session.copy.stopped:
                raise HTTPException(404, PLAY_ENDED)
            if session.copy.broken or n >= session.copy.end:
                raise HTTPException(404, COPY_FAILED)
            raise HTTPException(503, "That part isn't ready yet. Try again in a moment.")
        ctx.plays.get(session_id)  # (still watching)
        return FileResponse(found, media_type="video/mp2t", headers={"Cache-Control": "no-store"})

    @app.get("/play/{session_id}/subtitles/{track}.{ext}")
    async def play_subtitles(session_id: str, track: str, ext: str, request: Request):
        session = session_or_404(session_id, request)
        found = session.subtitles.get(track)
        if found is None:
            raise HTTPException(404, "There's no such subtitle track")
        url, codec = found
        try:
            got = await proxy().get(url)
            got.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(503, NO_FILE) from None
        if len(got.content) > SUBTITLES_MOST:
            raise HTTPException(503, NO_FILE)
        # (Its type is the track's, never what the address says: a subtitle
        # file is text from elsewhere, and is never shown as a page.)
        return Response(
            got.content,
            media_type=_SUBTITLE_TYPES.get(codec, "text/plain"),
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.post("/play/{session_id}/leave", status_code=204)
    async def play_leave(session_id: str, request: Request):
        going = ctx.plays.find(session_id)
        if going is None or (access.outside(request.scope) and not going.away):
            return Response(status_code=204)  # (nothing of its own to end)
        session = ctx.plays.end(session_id)
        # (Not when a newer one took over: another sound track, a smaller version.)
        if session is not None and not ctx.plays.newer(session):
            said_stop(session)
        return Response(status_code=204)

    # The Access tab: which libraries the apps may see ------------------------

    @app.get("/api/app-libraries")
    async def shared_libraries():
        try:
            found = await ctx.library.libraries() if ctx.library.configured else []
            problem = None
        except LibraryError as e:
            found, problem = [], str(e)
        return {
            "libraries": [
                {"key": str(s["key"]), "title": s.get("title") or "", "kind": s.get("type")}
                for s in found
            ],
            "shared": list(ctx.shared.keys),
            "whenSlow": ctx.shared.when_slow,
            "evenSound": ctx.shared.even_sound,
            "problem": problem,
            "playing": len(ctx.plays.watching()),
        }

    @app.put("/api/app-libraries")
    async def share_libraries(body: SharedLibraries, request: Request):
        try:
            keys = ctx.shared.save(body.libraries)
            if body.whenSlow is not None:
                before = dict(ctx.shared.when_slow)
                after = ctx.shared.save_when_slow(body.whenSlow.home, body.whenSlow.away)
                if after != before:
                    log.info(
                        "When playing in StationPlay's apps can't keep up: at home, %s; away "
                        "from home, %s",
                        _slow_words(after["home"]),
                        _slow_words(after["away"]),
                    )
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        who = access.signed_in(request)
        if body.evenSound is not None and body.evenSound != ctx.shared.even_sound:
            ctx.shared.save_even_sound(body.evenSound)
            log.info(
                "Even sound for a show's episodes in StationPlay's apps: %s%s",
                "on" if body.evenSound else "off (each episode's sound as it is)",
                f" (set by {who.name})" if who else "",
            )
        ctx.app_pictures.clear()  # (programs playing from one unshared stop at their next ask)
        try:
            names = {str(s["key"]): s.get("title") or "" for s in await ctx.library.libraries()}
        except LibraryError:
            names = {}
        chosen = ", ".join(names.get(k, f"library {k}") for k in keys) or "none"
        log.info(
            "Libraries in StationPlay's apps: %s%s", chosen, f" (set by {who.name})" if who else ""
        )
        return await shared_libraries()


def _whole(text: str | None, otherwise: int, name: str, low: int, high: int) -> int:
    if text is None or text == "":
        return otherwise
    try:
        value = int(text)
    except ValueError:
        raise HTTPException(400, f"{name} must be a whole number") from None
    if not low <= value <= high:
        raise HTTPException(400, f"{name} must be from {low} to {high}")
    return value


def _tags(said: str) -> set[str]:
    """The ETags in an If-None-Match header (weak ones as strong ones)."""
    return {t.strip().removeprefix("W/") for t in said.split(",") if t.strip()}


def chosen(picked: languages.Picked | None, sound: Track | None, shown: Track | None) -> Any:
    """What was chosen for someone from their languages, as the play answer
    says it (`sound`: the track that plays; `shown`: the subtitle that's
    shown, if any); None when nothing was."""
    if picked is None:
        return None
    why = picked.subtitle_why
    if picked.subtitle is not None and shown is None:
        why += ". This device can't show them"
    return {
        "audio": sound.id if sound and sound.id else None,
        "audioWhy": picked.audio_why,
        "subtitle": shown.id if shown else None,
        "subtitleWhy": why,
    }


def cant_copy(why: list[str]) -> str:
    """Why StationPlay can't make a copy for a device, in a sentence."""
    return (
        f"This device can't play this file as it is ({ondemand.and_list(why)}), and StationPlay "
        "can't make a copy of it that the device can."
    )


def too_fast(need: str, cap_kbps: int) -> str:
    """Why an app that can't take a copy can't play a file away from home
    that's over the Admin's cap, in a sentence."""
    return (
        f"This file needs {need}, more than the {playing.mbps(cap_kbps)} an Admin allows for "
        "Media away from home, and this app can't take a copy made to fit. Watch it at home, "
        "or update the app."
    )


def _slow_words(choice: str) -> str:
    return "switch to a smaller version" if choice == "switch" else "offer a smaller version"


def _markers(e: Entry) -> dict[str, Any]:
    """Where an episode's intro and closing credits are (see plex._skips),
    for the Skip intro and Skip credits buttons; a movie has neither."""
    credits = e.credits
    return {
        "intro": list(e.intro) if e.intro else None,
        "credits": list(credits) if credits else None,
        # Nothing follows the credits: Skip credits goes on to what's next.
        "creditsToEnd": bool(credits and e.duration_ms and credits[1] >= e.duration_ms),
    }


class _Passed(StreamingResponse):
    """A file passed on from Plex as it comes. Plex's answer is closed
    however the player's request ends (finished, or gone partway, as a
    player that seeks does), so no connection to Plex is left open."""

    def __init__(self, got: httpx.Response, **kwargs: Any) -> None:
        super().__init__(got.aiter_bytes(), **kwargs)
        self.got = got

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.got.aclose()


async def _from_plex(client: httpx.AsyncClient, url: str, request: Request, kind: str) -> Response:
    """A file from Plex, passed on as it comes, ranges and all (so a player
    can seek in it)."""
    asked = {
        name: value
        for name in ("range", "if-range")
        if (value := request.headers.get(name)) is not None
    }
    asked["accept-encoding"] = "identity"  # (as it is: its length and ranges are the file's)
    try:
        got = await client.send(client.build_request("GET", url, headers=asked), stream=True)
    except httpx.HTTPError:
        raise HTTPException(503, NO_FILE) from None
    if got.status_code not in (200, 206):
        status, whole = got.status_code, got.headers.get("content-range")
        await got.aclose()
        if status == 416:
            return Response(status_code=416, headers={"Content-Range": whole or "bytes */*"})
        raise HTTPException(503, NO_FILE)
    headers = {k: v for k in PROXIED_HEADERS if (v := got.headers.get(k)) is not None}
    headers.setdefault("accept-ranges", "bytes")
    if not headers.get("content-type", "").startswith("multipart/"):
        headers["content-type"] = kind  # (several ranges at once keep Plex's type)
    headers["cache-control"] = "no-store"
    if request.method == "HEAD":
        await got.aclose()
        return Response(status_code=got.status_code, headers=headers)
    return _Passed(got, status_code=got.status_code, headers=headers)
