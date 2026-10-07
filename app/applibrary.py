"""Your library in StationPlay's apps: the app connection's addresses for
browsing and playing it (see docs/on-demand.md, and docs/app-api.md for the
contract), the play sessions' own addresses, and the Access tab's setting.

The deciding is in ondemand.py; this is the asking and answering.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import access, capacity, catalog, ondemand
from .appapi import APP_MAX, app_label, in_sentence, slot_program
from .broadcaster import now_ms
from .catalog import Entry, Track
from .library import LibraryError
from .ondemand import NotShared
from .sources import find_first, learn_mapping, local_candidates
from .text import plain

if TYPE_CHECKING:
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


class PlayAsk(BaseModel):
    key: str = Field(max_length=20)
    device: Abilities
    app: str = Field(default="", max_length=APP_MAX)
    deviceName: str = Field(default="", max_length=APP_MAX)


class ProgressReport(BaseModel):
    key: str = Field(max_length=20)
    positionMs: int | None = Field(default=None, ge=0, le=7 * 86_400_000)
    watched: bool | None = None
    session: str | None = Field(default=None, max_length=64)


class SharedLibraries(BaseModel):
    libraries: list[str] = Field(max_length=ondemand.LIBRARIES_MOST)


# What the apps are told ----------------------------------------------------------------


def art(key: str, kind: str) -> str:
    return f"/api/v1/art/{key}?kind={kind}"


def card(e: Entry, progress: dict[str, tuple[int, bool]], unwatched: int | None = None) -> dict:
    """A show, movie or episode in a list (see "A card" in docs/app-api.md)."""
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
        "genres": [plain(g) for g in e.genres],
        "contentRating": plain(e.content_rating) or None,
        "studio": plain(e.studio) or None,
        "released": e.released or None,
        "backdrop": art(e.key, "backdrop") if e.has_art else None,
    }


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

    def unwatched_of(user_id: int, shows: list[Entry]) -> dict[str, int]:
        done = ctx.db.watched_in_shows(user_id, [s.key for s in shows])
        return {s.key: max(0, (s.episodes or 0) - len(done.get(s.key, ()))) for s in shows}

    def cards(user_id: int, entries: list[Entry]) -> list[dict]:
        progress = ctx.db.progress_of(user_id, [e.key for e in entries if e.kind != catalog.SHOW])
        unwatched = unwatched_of(user_id, [e for e in entries if e.kind == catalog.SHOW])
        return [card(e, progress, unwatched.get(e.key)) for e in entries]

    # Browsing --------------------------------------------------------------

    @app.get("/api/v1/libraries")
    async def libraries(request: Request):
        shared_here(request)
        with Asking():
            return {"libraries": await cat.libraries()}

    @app.get("/api/v1/libraries/{key}")
    async def library_page(key: str, request: Request):
        shared_here(request)
        sort = request.query_params.get("sort", "title")
        if sort not in ("title", "added", "released"):
            raise HTTPException(400, "sort must be title, added or released")
        start = _whole(request.query_params.get("start"), 0, "start", 0, 1_000_000)
        size = _whole(
            request.query_params.get("size"), ondemand.PAGE_DEFAULT, "size", 1, ondemand.PAGE_MOST
        )
        user_id, _ = person(request)
        with Asking():
            title, kind, total, page = await cat.browse(key, sort, start, size)
        return {
            "key": key,
            "title": title,
            "kind": kind,
            "total": total,
            "start": start,
            "items": cards(user_id, page),
        }

    @app.get("/api/v1/home")
    async def home(request: Request):
        shared_here(request)
        user_id, _ = person(request)
        with Asking():
            going = await ondemand.continue_watching(cat, ctx.db, user_id)
            added = await cat.recently_added()
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

    def on_now(words: str) -> list[dict]:
        """The stations airing a show or movie whose title contains `words`
        right now, with what's on."""
        wanted, now, out = words.casefold(), now_ms(), []
        for channel in ctx.db.list_channels():
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

    @app.get("/api/v1/search")
    async def search(request: Request):
        """The one place your library and the stations meet: what's in the
        library, and which stations are airing it now."""
        words = " ".join(plain(request.query_params.get("q", "")).split())
        if not words:
            raise HTTPException(400, "Type something to search for")
        if len(words) > ondemand.SEARCH_LONGEST:
            raise HTTPException(400, "That's too long to search for")
        user_id, _ = person(request)
        found: list[Entry] = []
        if ctx.shared.on and not access.outside(request.scope):
            with Asking():
                found = await cat.search(words)
        return {"items": cards(user_id, found), "onNow": await asyncio.to_thread(on_now, words)}

    @app.get("/api/v1/items/{key}")
    async def item(key: str, request: Request):
        shared_here(request)
        user_id, _ = person(request)
        with Asking():
            e = await cat.entry(key)
            if e.kind == catalog.SHOW:
                episodes = await cat.episodes(key)
                upcoming = await ondemand.up_next(cat, ctx.db, user_id, key)
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
        media = e.media[0] if e.media else None
        out = {**card(e, progress), **details(e)}
        if e.kind == catalog.EPISODE and e.show_key and not e.has_art:
            out["backdrop"] = art(e.show_key, "backdrop")
        out.update(
            markers={"intro": _span(e.intro), "credits": _span(e.credits)},
            picture={"size": media.size_label or None, "hdr": ondemand.hdr_label(media)}
            if media
            else None,
            audio=tracks(media.audio, True) if media else [],
            subtitles=tracks(media.subtitles, False) if media else [],
        )
        return out

    @app.get("/api/v1/items/{key}/episodes")
    async def episodes_of(key: str, request: Request):
        shared_here(request)
        season_text = request.query_params.get("season")
        season = _whole(season_text, -1, "season", 0, 100_000) if season_text else None
        user_id, _ = person(request)
        with Asking():
            e = await cat.entry(key)
            if e.kind != catalog.SHOW:
                raise HTTPException(400, "That isn't a show")
            found = await cat.episodes(key)
        chosen = [x for x in found if season is None or x.season == season]
        return {"show": key, "season": season, "episodes": cards(user_id, chosen)}

    @app.get("/api/v1/art/{key}")
    async def picture(key: str, request: Request):
        shared_here(request)
        kind = request.query_params.get("kind", "poster")
        if kind not in ondemand.PICTURE_KINDS:
            raise HTTPException(400, "kind must be poster, backdrop or thumb")
        width = ondemand.width_for(_whole(request.query_params.get("w"), 320, "w", 1, 10_000))
        with Asking():
            await cat.check(key)  # (shared now, even if its picture was kept from before)
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

    @app.post("/api/v1/play")
    async def play(body: PlayAsk, request: Request):
        shared_here(request)
        user_id, name = person(request)
        with Asking():
            e = await cat.entry(body.key)
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
        media, why = ondemand.choose(e, dev)
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
            "leave": f"{here}/leave",
            "resumeMs": ondemand.resume_at(ctx.db.progress_of(user_id, [e.key]).get(e.key)),
            "durationMs": media.duration_ms or e.duration_ms,
            "markers": {"intro": _span(e.intro), "credits": _span(e.credits)},
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

    @app.post("/api/v1/progress")
    async def progress(body: ProgressReport, request: Request):
        shared_here(request)
        user_id, _ = person(request)
        if body.positionMs is None and body.watched is None:
            raise HTTPException(400, "Send positionMs, or watched")
        with Asking():
            e = await cat.entry(body.key)
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
            "problem": problem,
            "playing": len(ctx.plays.watching()),
        }

    @app.put("/api/app-libraries")
    async def share_libraries(body: SharedLibraries, request: Request):
        try:
            keys = ctx.shared.save(body.libraries)
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


def _span(span: tuple[int, int] | None) -> list[int] | None:
    return list(span) if span else None


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
