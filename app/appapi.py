"""The app connection: what StationPlay's own apps ask the server, under
/api/v1. docs/app-api.md is its contract, and tests/test_app_api.py checks
the two match.

It's a thin layer over what the server already does (stations, their
schedules, signing in, HLS): nothing here plays or schedules anything.
Version 1 only grows; a change that would break an app becomes version 2,
served beside it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import __version__, access, capacity, hdhr, intro, links, specials
from .broadcaster import now_ms
from .text import plain

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .db import Channel, Item, User
    from .main import AppContext
    from .schedule import Slot, StationSchedule

VERSION = 1
PREFIX = "/api/v1/"
HEADER = (b"stationplay-api", str(VERSION).encode())
FEATURES = ("hls", "speed-test")

GUIDE_DEFAULT_MS = 6 * 3600_000
GUIDE_MAX_MS = 2 * 86_400_000
GUIDE_REACH_MS = 7 * 86_400_000  # how far from now a guide may start
COLOURS_AT_ONCE = 4  # logos read for their colors at once (each by ffmpeg)


class ApiHeader:
    """Adds `StationPlay-API: 1` to every answer under /api/v1, refusals
    included: a plain ASGI layer, outside the others."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(
        self, scope: dict, receive: Callable[[], Awaitable[Any]], send: Callable
    ) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(PREFIX):
            await self.app(scope, receive, send)
            return

        async def sending(message: dict) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*(message.get("headers") or ()), HEADER]}
            await send(message)

        await self.app(scope, receive, sending)


APP_MAX = 60  # an app's name, or its device's, at most


class AppSignIn(BaseModel):
    name: str = Field(max_length=100)
    password: str = Field(max_length=access.PASSWORD_MAX)
    device: str | None = Field(default=None, max_length=100)
    app: str = Field(default="", max_length=APP_MAX)
    deviceName: str = Field(default="", max_length=APP_MAX)


class LinkStart(BaseModel):
    app: str = Field(default="", max_length=APP_MAX)
    deviceName: str = Field(default="", max_length=APP_MAX)


class LinkCheck(BaseModel):
    poll: str = Field(max_length=100)


class SpeedTested(BaseModel):
    mbps: float
    app: str = Field(default="", max_length=APP_MAX)
    deviceName: str = Field(default="", max_length=APP_MAX)


class LinkCode(BaseModel):
    code: str = Field(max_length=20)


def app_label(app: str, device: str) -> str:
    """Which app, on what device, as the access log and the Access tab say:
    "StationPlay for Roku on Living Room Roku"."""
    app, device = plain(app)[:APP_MAX], plain(device)[:APP_MAX]
    if app and device:
        return f"{app} on {device}"
    return app or (f"A StationPlay app on {device}" if device else "A StationPlay app")


def in_sentence(label: str) -> str:
    """An app_label in the middle of a sentence."""
    return "a" + label[1:] if label.startswith("A StationPlay app") else label


def program(item: Item, start_ms: int, end_ms: int, special: str) -> dict[str, Any]:
    """A program, as the app connection describes one (see "A program" in
    docs/app-api.md). Text is made plain: one program's odd details in
    Plex can't spoil a whole answer."""
    episode = item.kind == "episode"
    name = plain(item.title or "")
    show = plain(item.show_title or "") if episode else ""
    year = item.year if isinstance(item.year, int) and 1800 <= item.year <= 2200 else None
    return {
        "start": start_ms,
        "end": end_ms,
        "kind": "episode" if episode else "movie",
        "title": show or name or "Untitled",
        "episodeTitle": (name or None) if episode else None,
        "season": item.season if episode and isinstance(item.season, int) else None,
        "episode": item.episode if episode and isinstance(item.episode, int) else None,
        "year": year,
        "summary": plain(item.summary or ""),
        "art": f"/art/{item.show_key or item.rating_key}",
        "special": plain(special) or None,
    }


def _ms(text: str | None, otherwise: int, name: str) -> int:
    """A time given in the address, in milliseconds (`otherwise` if it
    isn't given)."""
    if text is None or text == "":
        return otherwise
    try:
        return int(text)
    except ValueError:
        raise HTTPException(400, f"The guide's {name!r} must be a time in milliseconds") from None


def _slot(station: StationSchedule, slot: Slot | None) -> dict[str, Any] | None:
    if slot is None:
        return None
    special = specials.label(station.special(slot), slot.index)
    return program(slot.item, slot.start_ms, slot.end_ms, special)


def routes(app: FastAPI, ctx: AppContext) -> None:
    """The app connection's addresses."""
    app.add_middleware(ApiHeader)
    settings = ctx.settings

    @app.exception_handler(RequestValidationError)
    async def not_understood(request: Request, e: RequestValidationError):
        """For apps, a sentence (as every refusal is); for the page, as
        FastAPI says it."""
        if not request.url.path.startswith(PREFIX):
            return await request_validation_exception_handler(request, e)
        return JSONResponse({"detail": "StationPlay didn't understand that request"}, 400)

    @app.get("/api/v1/server")
    async def server(request: Request):
        not_set_up = (
            access.NOT_SET_UP if access.outside(request.scope) and not ctx.access.required else None
        )
        away = ctx.away.address if ctx.away.on else None
        return {
            "name": settings.friendly_name,
            "id": ctx.device_id,
            "version": __version__,
            "api": VERSION,
            "signIn": ctx.access.required or not_set_up is not None,
            "notSetUp": not_set_up,
            "outside": access.outside(request.scope),
            "awayAddress": away,
            "features": [*FEATURES, *(["away"] if away else [])],
        }

    @app.post("/api/v1/sign-in")
    async def sign_in(body: AppSignIn, request: Request):
        if not ctx.access.required:
            raise HTTPException(400, "Signing in to StationPlay is off, so there's no need to")
        known = ctx.access.known_device(body.device, body.name)
        try:
            user = await ctx.access.check_password(
                body.name,
                body.password,
                access.address(request.scope),
                public=access.outside(request.scope),
                known=known,
            )
        except access.Busy as e:
            raise HTTPException(429, str(e)) from None
        if user is None:
            ctx.access.record(
                logging.WARNING,
                f"Failed sign-in as {body.name[:40]!r} in a StationPlay app, "
                f"from {access.where(request.scope)}",
            )
            raise HTTPException(401, "That name or password isn't right")
        label = app_label(body.app, body.deviceName)
        token = ctx.access.start_session(user, label)
        device = None if known else ctx.access.remember_device(user)
        ctx.access.record(
            logging.INFO,
            f"{user.name} ({access.role_name(user.role)}) signed in to {in_sentence(label)} "
            f"from {access.where(request.scope)}",
        )
        return {"token": token, "device": device, "user": {"name": user.name, "role": user.role}}

    # Signing in with a code (see links.py) --------------------------------

    @app.post("/api/v1/link")
    async def link_start(body: LinkStart, request: Request):
        if not ctx.access.required:
            raise HTTPException(400, "Signing in to StationPlay is off, so there's no need to")
        try:
            code, poll = ctx.links.start(
                app_label(body.app, body.deviceName), access.address(request.scope)
            )
        except links.Refused as e:
            raise HTTPException(429, str(e)) from None
        return {
            "code": code,
            "poll": poll,
            "expiresIn": int(links.LINK_S),
            "interval": links.POLL_S,
            "linkAt": "/link",
        }

    @app.post("/api/v1/link/check")
    async def link_check(body: LinkCheck):
        pending = ctx.links.check(body.poll)
        if pending is None:
            raise HTTPException(404, "That code has run out. Ask for a new one.")
        if pending.token is None or pending.user is None:
            return JSONResponse({"detail": "Waiting for the code to be entered"}, 202)
        user = pending.user
        return {"token": pending.token, "user": {"name": user.name, "role": user.role}}

    @app.post("/api/v1/sign-out")
    async def sign_out(request: Request):
        token = access.bearer(request.scope)
        user = access.signed_in(request)
        if token:
            ctx.access.end_session(token)
        if user:
            ctx.access.record(
                logging.INFO,
                f"{user.name} signed out of a StationPlay app from {access.where(request.scope)}",
            )
        return {"ok": True}

    # On StationPlay's page: entering an app's code, and the apps signed in.

    def linking(code: str, request: Request) -> tuple[User, links.Pending]:
        user = access.signed_in(request)
        if user is None:
            raise HTTPException(400, "Signing in to StationPlay is off, so apps don't need a code")
        try:
            return user, ctx.links.find(code, user)
        except links.Refused as e:
            raise HTTPException(429, str(e)) from None
        except LookupError as e:
            raise HTTPException(404, str(e)) from None

    @app.get("/api/access/link/{code}")
    async def link_preview(code: str, request: Request):
        """Which app on which device is waiting with a code: shown before
        it's linked, so no one links a stranger's TV by mistake."""
        _user, pending = linking(code, request)
        return {"app": pending.app}

    @app.post("/api/access/link")
    async def link_app(body: LinkCode, request: Request):
        user, pending = linking(body.code, request)
        ctx.links.link(pending, user, ctx.access.start_session(user, pending.app))
        ctx.access.record(
            logging.INFO,
            f"{user.name} ({access.role_name(user.role)}) linked {in_sentence(pending.app)} "
            f"(at {pending.address}) from {access.where(request.scope)}",
        )
        return {"app": pending.app}

    @app.get("/api/access/apps")
    async def signed_in_apps():
        since = int(time.time() * 1000) - access.SESSION_DAYS * 86_400_000
        return [
            {"id": a["id"], "user": a["user"], "app": a["app"], "signedInMs": a["created_ms"],
             "seenMs": a["seen_ms"]}
            for a in ctx.db.app_sessions(since)
        ]  # fmt: skip

    @app.delete("/api/access/apps/{session_id}", status_code=204)
    async def sign_out_app(session_id: int, request: Request):
        ended = ctx.db.end_app_session(session_id)
        if ended is None:
            raise HTTPException(404, "That app isn't signed in")
        by = access.signed_in(request)
        ctx.access.record(
            logging.INFO,
            f"{by.name if by else 'Someone'} signed out {ended} on the Access tab",
        )

    colour_turns = asyncio.Semaphore(COLOURS_AT_ONCE)

    async def colours(channel: Channel) -> dict[str, str]:
        logo = ctx.logos.path(channel.logo) if channel.logo else None
        async with colour_turns:
            dark, light, accent = await intro.colours(settings, str(logo) if logo else None)
        return {"dark": f"#{dark}", "light": f"#{light}", "accent": f"#{accent}"}

    def away_key(request: Request) -> str | None:
        """The key of this app's own addresses, from outside, when watching
        away from home is on (see away.py); None otherwise."""
        if not access.outside(request.scope):
            return None
        token = access.bearer(request.scope) or request.cookies.get(access.COOKIE)
        user = access.signed_in(request)
        return ctx.away.key_for(access.session_hash(token), user) if token and user else None

    def hls_address(number: int, key: str | None) -> str:
        """Where an app plays a station: at home, its HLS; from outside, its
        HLS at the app's own address."""
        return f"/hls/k/{key}/{number}/index.m3u8" if key else f"/hls/{number}/index.m3u8"

    def logo_address(channel: Channel, key: str | None) -> str:
        """A station's logo: at home, where Plex gets it; from outside, at
        the app's own address (with the same version, which changes with it)."""
        home = hdhr.icon_url("", channel)
        if not key:
            return home
        return f"/hls/k/{key}/{channel.number}/logo.png?{home.partition('?')[2]}"

    @app.get("/api/v1/stations")
    async def stations(request: Request):
        key = away_key(request)
        channels = ctx.db.list_channels()
        now = now_ms()

        def on_now() -> list[tuple[dict | None, dict | None]]:  # (a big shuffle takes a moment)
            out = []
            for channel in channels:
                station = ctx.station(channel.id)
                slot = station.locate(now)
                out.append((_slot(station, slot), _slot(station, slot and station.after(slot))))
            return out

        airing, palettes = await asyncio.gather(
            asyncio.to_thread(on_now), asyncio.gather(*(colours(c) for c in channels))
        )
        return {
            "stations": [
                {
                    "number": c.number,
                    "name": plain(c.name),
                    "description": plain(c.description),
                    "logo": logo_address(c, key),
                    "colors": palette,
                    "hls": hls_address(c.number, key),
                    "now": now_on,
                    "next": next_on,
                }
                for c, palette, (now_on, next_on) in zip(channels, palettes, airing, strict=True)
            ]
        }

    # Connection tests (see capacity.py) ------------------------------------

    @app.get("/api/v1/speed-test")
    async def speed_test(request: Request):
        """Data for an app to time: `?mb=` megabytes of it (TEST_MB unless
        asked), random so nothing along the way can shrink it. One test from
        an address at a time."""
        try:
            mb = int(request.query_params.get("mb", capacity.TEST_MB))
        except ValueError:
            raise HTTPException(400, "mb must be a number") from None
        if not 1 <= mb <= capacity.TEST_MB_MOST:
            raise HTTPException(400, f"mb must be between 1 and {capacity.TEST_MB_MOST}")
        if not ctx.capacity.may_test(access.address(request.scope)):
            raise HTTPException(
                429, "A connection test just ran from here. Try again in a few seconds."
            )

        async def data():
            for _ in range(mb):
                yield capacity.TEST_BLOCK

        return StreamingResponse(
            data(),
            media_type="application/octet-stream",
            headers={
                "Content-Length": str(mb * len(capacity.TEST_BLOCK)),
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/v1/speed-test")
    async def speed_tested(body: SpeedTested, request: Request):
        """What an app found: kept for the Access tab, where StationPlay
        recommends limits from it. Where it ran (at home, or away from home
        through the public port) is as StationPlay sees it."""
        user = access.signed_in(request)
        where = "away" if access.outside(request.scope) else "home"
        try:
            test = ctx.capacity.record(
                where,
                body.mbps,
                app_label(body.app, body.deviceName),
                user.name if user else "",
                now_ms(),
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        each, _ = capacity.stream_mbps(settings, ctx.db.list_channels())
        return {
            "mbps": test.mbps,
            "where": where,
            "eachMbps": each,
            "room": capacity.room(test, each),
        }

    @app.get("/api/v1/guide")
    async def guide(request: Request):
        now = now_ms()
        from_ms = _ms(request.query_params.get("from"), now, "from")
        to_ms = _ms(request.query_params.get("to"), from_ms + GUIDE_DEFAULT_MS, "to")
        if abs(from_ms - now) > GUIDE_REACH_MS:
            raise HTTPException(400, "The guide can start at most 7 days from now")
        if not 0 < to_ms - from_ms <= GUIDE_MAX_MS:
            raise HTTPException(400, "The guide can cover at most 2 days, after its start")
        channels = ctx.db.list_channels()

        def listing() -> list[dict]:  # (on a worker thread, as on_now)
            out = []
            for channel in channels:
                station = ctx.station(channel.id)
                programs = [_slot(station, slot) for slot in station.between(from_ms, to_ms)]
                out.append({"number": channel.number, "programs": programs})
            return out

        return {"from": from_ms, "to": to_ms, "stations": await asyncio.to_thread(listing)}
