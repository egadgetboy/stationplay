"""Your library in StationPlay's apps: the apps' own addresses for browsing
and playing it (under /api/internal; see docs/on-demand.md, and
docs/internal-api.md for the contract), the play sessions' own addresses,
and the Access tab's setting.

The deciding is in ondemand.py; this is the asking and answering.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import access, capacity, catalog, converting, keyframes, ondemand, subtitles, viewing
from .appapi import APP_MAX, app_label, in_sentence, slot_program
from .broadcaster import now_ms
from .catalog import Entry, Media, Track
from .ffmpeg import ProbeResult, Subtitles, to_sdr
from .library import LibraryError
from .ondemand import NotShared
from .sources import find_first, learn_mapping, local_candidates
from .text import plain

if TYPE_CHECKING:
    from .db import User
    from .main import AppContext

log = logging.getLogger(__name__)

NONE_SHARED = "No libraries are shared with StationPlay's apps"
AT_HOME = (
    "Your library can be watched in StationPlay's apps on your home network (or through a "
    "VPN) for now."
)
PLAY_ENDED = "That program's address has ended. Choose it again to play it."
NOT_PLAYABLE = "Choose an episode or a movie to play"
NO_FILE = "StationPlay can't reach this program's file right now. Try again in a moment."
COPY_FAILED = "StationPlay couldn't make this ready to play here. Try again, or choose another."
KEYFRAMES_WAIT_S = 20.0  # reading a file's index, at most
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


class WhenSlow(BaseModel):
    home: str | None = Field(default=None, max_length=10)
    away: str | None = Field(default=None, max_length=10)


class SharedLibraries(BaseModel):
    libraries: list[str] = Field(max_length=ondemand.LIBRARIES_MOST)
    whenSlow: WhenSlow | None = None


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


def versions(e: Entry) -> list[dict]:
    """An episode's or movie's versions, the best first (see `versions` in
    docs/internal-api.md)."""
    best = ondemand.best_first(e.media)
    names = ondemand.version_labels(best)
    return [
        {
            "id": m.id,
            "name": names[i],
            "size": m.size_label or None,
            "hdr": ondemand.hdr_label(m),
            "bitrateKbps": m.bitrate_kbps,
        }
        for i, m in enumerate(best)
        if m.id
    ]


def playable_versions(e: Entry, dev: ondemand.Device, max_kbps: int | None) -> list[dict]:
    """Its versions, each saying whether this device can play it as it is,
    and whether the connection keeps up with it."""
    out = []
    best = [m for m in ondemand.best_first(e.media) if m.id]
    for v, m in zip(versions(e), best, strict=True):
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
            "codec": t.codec,
            "default": t.default,
            **({} if audio else {"forced": t.forced, "external": t.external}),
            "index": t.index,
        }
        for t in found
        if t.id
    ]


def describe(e: Entry) -> str:
    """A program, as the log names it."""
    if e.kind == catalog.EPISODE and e.season is not None and e.episode is not None:
        return f"{e.show_title} S{e.season:02}E{e.episode:02}"
    return f"{e.title} ({e.year})" if e.year else e.title


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
        if access.outside(request.scope):
            raise HTTPException(403, AT_HOME)
        if not ctx.shared.on:
            raise HTTPException(404, NONE_SHARED)

    class Asking:
        """Answers for what the library says: not shared (404), or the
        library unreachable (503)."""

        def __enter__(self) -> None:
            return None

        def __exit__(self, kind: Any, e: Any, tb: Any) -> None:
            if isinstance(e, NotShared):
                raise HTTPException(404, ondemand.NOT_SHARED) from None
            if isinstance(e, LibraryError):
                log.warning("A StationPlay app couldn't be shown your library (%s)", e)
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
        with Asking():
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
        with Asking():
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
        with Asking():
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
        title contains `words` right now, with what's on."""
        wanted, now, out = words.casefold(), now_ms(), []
        for channel in ctx.stations_for(user):
            station = ctx.station(channel.id)
            slot = station.locate(now)
            if slot is None:
                continue
            item = slot.item
            title = (
                item.show_title if item.kind == catalog.EPISODE and item.show_title else item.title
            )
            if wanted in plain(title or "").casefold():
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
        if ctx.shared.on and not access.outside(request.scope):
            with Asking():
                found = await seen_only(viewer, await cat.search(words))
            found = [e for e in found if library_seen(viewer, e.library)]
        return {
            "items": cards(user_id, found),
            "onNow": await asyncio.to_thread(on_now, words, user),
        }

    @app.get("/api/internal/items/{key}")
    async def item(key: str, request: Request):
        shared_here(request)
        user_id, _ = person(request)
        viewer = viewer_of(request)
        with Asking():
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
                ep, start = upcoming
                nxt = card(ep, {ep.key: (start, ep.key in done)})
            return {
                **card(e, {}, max(0, (e.episodes or len(episodes)) - len(done))),
                **details(e),
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
            versions=versions(e),
        )
        return out

    @app.get("/api/internal/items/{key}/related")
    async def related_to(key: str, request: Request):
        """Others like a show or movie, from its own library (an episode's:
        its show's)."""
        shared_here(request)
        user_id, _ = person(request)
        viewer = viewer_of(request)
        with Asking():
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
        season_text = request.query_params.get("season")
        season = _whole(season_text, -1, "season", 0, 100_000) if season_text else None
        user_id, _ = person(request)
        viewer = viewer_of(request)
        with Asking():
            e = await cat.entry(key)
            await must_see(viewer, e)
            if e.kind != catalog.SHOW:
                raise HTTPException(400, "That isn't a show")
            found = await seen_only(viewer, await cat.episodes(key))
        chosen = [x for x in found if season is None or x.season == season]
        return {"show": key, "season": season, "episodes": cards(user_id, chosen)}

    @app.get("/api/internal/art/{key}")
    async def picture(key: str, request: Request):
        shared_here(request)
        kind = request.query_params.get("kind", "poster")
        if kind not in ondemand.PICTURE_KINDS:
            raise HTTPException(400, "kind must be poster, backdrop or thumb")
        width = ondemand.width_for(_whole(request.query_params.get("w"), 320, "w", 1, 10_000))
        viewer = viewer_of(request)
        with Asking():
            await cat.check(key)  # (shared now, even if its picture was kept from before)
            if not viewer.everything:
                await must_see(viewer, await cat.entry(key))
        kept = ctx.app_pictures.get((key, kind, width))
        if kept is None:
            with Asking():
                e = await cat.entry(key)
            # (An episode's poster is its show's; a show's still, its poster.)
            target = e.show_key if e.kind == catalog.EPISODE and kind != "thumb" else e.key
            which = "art" if kind == "backdrop" else "thumb"
            height = width * 3 // 2 if kind == "poster" else width * 9 // 16
            try:
                with Asking():
                    kept = await ctx.library.picture(target or e.key, which, width, height)
            except httpx.HTTPError:
                raise HTTPException(404, "There's no such picture") from None
            ctx.app_pictures.put((key, kind, width), kept)
        data, content_type = kept
        return Response(
            data, media_type=content_type, headers={"Cache-Control": "private, max-age=86400"}
        )

    # Playing ---------------------------------------------------------------

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

    async def play_copy(body: PlayAsk, request: Request, e: Entry, dev: ondemand.Device,
                        hls: frozenset[str]) -> Any:  # fmt: skip
        """Playing a copy StationPlay makes (see converting.py), for a device
        that can't play the file as it is, or for subtitles drawn in, a
        smaller picture made to fit, or night mode's sound."""
        user_id, name = person(request)
        versions = [m for m in ondemand.best_first(e.media) if m.id] or list(e.media)
        asked = [m for m in versions if body.version and m.id == body.version]
        smaller = body.fit and body.maxKbps is not None

        def refuse(why: list[str]) -> JSONResponse:
            log.info("StationPlay can't make a copy of %s for an app (%s)", describe(e),
                     ondemand.and_list(why))  # fmt: skip
            return JSONResponse({"detail": cant_copy(why), "why": why}, status_code=422)

        # The version: the one asked for; or the best one whose picture can
        # be kept; or for converting, the smallest that's still big enough.
        media = asked[0] if asked else None
        if media is None:
            keepable = [m for m in versions
                        if converting.picture_copyable(m, ondemand.unplayable(m, dev), hls)]  # fmt: skip
            if keepable and not (body.subtitle or smaller):
                media = keepable[0]
            else:
                tall = [m for m in versions if m.height >= converting.CONVERT_MOST_HEIGHT]
                media = tall[-1] if tall else versions[0]
        if media.parts > 1:
            return refuse([f"it's split into {media.parts} files"])
        why = ondemand.unplayable(media, dev)
        sound = converting.audio_track(media, body.audio)
        if sound is not None and sound.codec and sound.codec not in dev.audio:
            label = f"its sound's format ({ondemand.label(sound.codec)})"
            if label not in why:
                why.append(label)
        shown = next((t for t in media.subtitles if t.id == body.subtitle), None)
        if shown is not None:
            why.append("its subtitles, drawn into the picture")
        if smaller:
            why.append("a smaller picture, to fit the connection")
        if body.night:
            why.append("night mode's sound")
        duration_s = (media.duration_ms or e.duration_ms or 0) / 1000
        if duration_s <= 0:
            return refuse(["how long it is isn't known"])
        path, stream = await source_of(e, media)
        source = path or stream
        if source is None:
            raise HTTPException(503, NO_FILE)
        # Keeping the picture as it is, where it can be (its keyframes
        # known from the file's index); otherwise converting it.
        starts: tuple[float, ...] = ()
        if converting.picture_copyable(media, why, hls) and shown is None and not smaller:
            try:
                found = await asyncio.wait_for(
                    keyframes.keyframes(reader(path, stream), media.container), KEYFRAMES_WAIT_S
                )
            except TimeoutError:
                found = None
            if found:
                starts = converting.pieces_at(found, duration_s)
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
            if ctx.plays.copies() >= (CONVERTING_MOST_GPU if on_gpu else CONVERTING_MOST):
                raise HTTPException(503, BUSY_CONVERTING)
            height, kbps = converting.convert_size(
                media, dev.video["h264"][1], body.maxKbps if smaller else None
            )
            starts = converting.pieces_every(duration_s)
        audio_codec, channels = converting.sound_for(sound, dev.audio, body.night)
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
                await asyncio.to_thread(job.target.parent.mkdir, parents=True, exist_ok=True)
                drawn = job.ready()
                if not job.target.exists():
                    first = subtitles.extract(settings, job)
            else:
                return refuse(["its subtitles"])
        client = request.client.host if request.client else "?"
        if (over := ctx.capacity.refusal(ctx.app_watchers(), client, False)) is not None:
            limit, most = over
            return JSONResponse(
                {"detail": capacity.refused_because(limit, most), "limit": limit, "most": most},
                status_code=503,
            )
        folder = converting.new_folder()
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
            night=body.night, height=height,
            kbps=kbps, tone_map=tone_map, subtitles=drawn, drawn=shown.id if shown else None,
        )  # fmt: skip
        token = access.bearer(request.scope) or request.cookies.get(access.COOKIE)
        task = asyncio.ensure_future(first) if first is not None else None
        session = ctx.plays.start(
            user_id=user_id, user=name,
            sign_in=access.session_hash(token) if name and token else None,
            entry=e, media=media, path=path, plex=stream, client=client, away=False,
            subtitles={
                t.id: (url, t.codec)
                for t in media.subtitles
                if t.external and t.id.isdigit()
                and (url := ctx.library.stream_url(e.key, f"/library/streams/{t.id}"))
            },
        )  # fmt: skip
        session.copy = converting.Copy(settings.ffmpeg_path, source, plan, folder, first=task,
                                       gpu=ctx.gpu, name=describe(e))  # fmt: skip
        resume = ondemand.resume_at(ctx.db.progress_of(user_id, [e.key]).get(e.key))
        session.start_s = (body.startMs if body.startMs is not None else resume) / 1000
        label = app_label(body.app, body.deviceName)
        log.info(
            "%s started %s in %s, %s (%s)%s",
            name or "Someone",
            describe(e),
            in_sentence(label),
            "repackaged" if method == converting.REPACKAGE else f"converted to {height}p",
            ondemand.and_list(why),
            "" if path else " (from Plex)",
        )
        here = f"/play/{session.id}"
        return {
            "session": session.id,
            "method": method,
            "url": f"{here}/index.m3u8",
            "why": why,
            "audioTrack": sound.id if sound else None,
            "drawnSubtitle": shown.id if shown else None,
            "leave": f"{here}/leave",
            "resumeMs": resume,
            "durationMs": media.duration_ms or e.duration_ms,
            "bitrateKbps": plan.kbps_needed or media.bitrate_kbps,
            "version": media.id or None,
            "versions": playable_versions(e, dev, body.maxKbps),
            "whenSlow": ctx.shared.when_slow["home"],
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

    @app.post("/api/internal/play")
    async def play(body: PlayAsk, request: Request):
        shared_here(request)
        user_id, name = person(request)
        with Asking():
            e = await cat.entry(body.key)
            await must_see(viewer_of(request), e)
        if e.kind not in (catalog.EPISODE, catalog.MOVIE):
            raise HTTPException(400, NOT_PLAYABLE)
        if not e.media:
            raise HTTPException(404, "This program has no file to play")
        dev = ondemand.device(
            body.device.containers,
            [(v.codec, v.width, v.height, v.bitDepth) for v in body.device.video],
            body.device.hdr,
            body.device.audio,
        )
        media, why = ondemand.choose(e, dev, body.version, body.maxKbps)
        hls = frozenset(h.strip().lower() for h in body.device.hls)
        sound = converting.audio_track(media, body.audio) if media is not None else None
        as_it_is = (
            media is not None
            and not (body.subtitle or body.fit or body.night)
            and (sound is None or not sound.codec or sound.codec in dev.audio)
        )
        if not as_it_is and "ts" in hls:
            return await play_copy(body, request, e, dev, hls)
        if media is None:
            log.info(
                "A StationPlay app can't play %s as it is (%s)", describe(e), ondemand.and_list(why)
            )
            return JSONResponse({"detail": ondemand.cant_play(why), "why": why}, status_code=422)
        client = request.client.host if request.client else "?"
        if (over := ctx.capacity.refusal(ctx.app_watchers(), client, False)) is not None:
            limit, most = over
            log.warning(
                "The limit of %s watching at once (set on the Access tab) was reached, so an "
                "app on %s couldn't play %s",
                capacity.devices(most),
                client,
                describe(e),
            )
            return JSONResponse(
                {"detail": capacity.refused_because(limit, most), "limit": limit, "most": most},
                status_code=503,
            )
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
        token = access.bearer(request.scope) or request.cookies.get(access.COOKIE)
        session = ctx.plays.start(
            user_id=user_id,
            user=name,
            sign_in=access.session_hash(token) if name and token else None,
            entry=e,
            media=media,
            path=path,
            plex=stream,
            client=client,
            away=False,
            subtitles={
                t.id: (url, t.codec)
                for t in media.subtitles
                if t.external
                and t.id.isdigit()
                and (url := ctx.library.stream_url(e.key, f"/library/streams/{t.id}"))
            },
        )
        label = app_label(body.app, body.deviceName)
        log.info(
            "%s started %s in %s, playing its file as it is%s",
            name or "Someone",
            describe(e),
            in_sentence(label),
            "" if path else " (from Plex)",
        )
        here = f"/play/{session.id}"
        return {
            "session": session.id,
            "method": "direct",
            "url": f"{here}/file.{media.container or 'mkv'}",
            "why": None,
            "audioTrack": None,
            "drawnSubtitle": None,
            "leave": f"{here}/leave",
            "resumeMs": ondemand.resume_at(ctx.db.progress_of(user_id, [e.key]).get(e.key)),
            "durationMs": media.duration_ms or e.duration_ms,
            "bitrateKbps": media.bitrate_kbps,
            "version": media.id or None,
            "versions": playable_versions(e, dev, body.maxKbps),
            "whenSlow": ctx.shared.when_slow["home"],
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
        shared_here(request)
        user_id, _ = person(request)
        if body.positionMs is None and body.watched is None:
            raise HTTPException(400, "Send positionMs, or watched")
        with Asking():
            e = await cat.entry(body.key)
            await must_see(viewer_of(request), e)
        if e.kind not in (catalog.EPISODE, catalog.MOVIE):
            raise HTTPException(400, NOT_PLAYABLE)
        if body.session:
            ctx.plays.get(body.session)  # (still watching)
        old = ctx.db.progress_of(user_id, [e.key]).get(e.key)
        if body.watched is not None:
            position, watched = 0, body.watched
        else:
            position, watched = ondemand.progressed(old, body.positionMs or 0, e)
        ctx.db.save_progress(
            user_id,
            e.key,
            e.show_key,
            position,
            e.duration_ms or 0,
            watched,
            int(time.time() * 1000),
        )
        return {"positionMs": ondemand.resume_at((position, watched)), "watched": watched}

    # The play sessions' own addresses (a player can't sign in) ---------------

    def session_or_404(session_id: str) -> ondemand.PlaySession:
        """A play session that's still good: its library still shared, and
        its sign-in (if signing in is on) still good."""
        session = ctx.plays.get(session_id)
        if session is None:
            raise HTTPException(404, PLAY_ENDED)
        now = time.monotonic()
        ended = not cat.shared_library(session.entry) or (
            ctx.access.required and session.sign_in is None
        )
        if not ended and session.sign_in and now - session.checked > ondemand.RECHECK_S:
            ended = ctx.access.session_user_hashed(session.sign_in) is None
            session.checked = now
        if ended:
            ctx.plays.end(session_id)
            raise HTTPException(404, PLAY_ENDED)
        return session

    @app.api_route("/play/{session_id}/file.{ext}", methods=["GET", "HEAD"])
    async def play_file(session_id: str, ext: str, request: Request):
        session = session_or_404(session_id)
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
    async def copy_playlist(session_id: str):
        session = session_or_404(session_id)
        if session.copy is None:
            raise HTTPException(404, PLAY_ENDED)
        return Response(
            session.copy.playlist(session.start_s),
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/play/{session_id}/piece-{n}.ts")
    async def copy_piece(session_id: str, n: int, request: Request):
        session = session_or_404(session_id)
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
    async def play_subtitles(session_id: str, track: str, ext: str):
        session = session_or_404(session_id)
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
    async def play_leave(session_id: str):
        session = ctx.plays.end(session_id)
        if session is not None:
            log.info("%s stopped %s", session.user or "Someone", describe(session.entry))
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
        ctx.app_pictures.clear()  # (programs playing from one unshared stop at their next ask)
        try:
            names = {str(s["key"]): s.get("title") or "" for s in await ctx.library.libraries()}
        except LibraryError:
            names = {}
        who = access.signed_in(request)
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


def cant_copy(why: list[str]) -> str:
    """Why StationPlay can't make a copy for a device, in a sentence."""
    return (
        f"This device can't play this file as it is ({ondemand.and_list(why)}), and StationPlay "
        "can't make a copy of it that the device can."
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
