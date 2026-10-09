"""StationPlay's API (/api/v1: the server, its stations and their guide,
documented in docs/api.md, with an OpenAPI spec; see api.py for the rest of
it), and what StationPlay's own apps ask besides (/api/internal: signing in
and connection tests, documented for the apps alone in
docs/internal-api.md). tests/test_app_api.py checks both documents against
the server.

It's a thin layer over what the server already does (stations, their
schedules, signing in, HLS): nothing here plays or schedules anything.
Version 1 only grows; a change that would break a client becomes version 2,
served beside it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import (
    __version__,
    access,
    api,
    capacity,
    devices,
    hdhr,
    intro,
    links,
    playing,
    problems,
    specials,
)
from .broadcaster import now_ms
from .text import plain

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from .db import Channel, Item, SignedIn, User
    from .main import AppContext
    from .schedule import Slot, StationSchedule

VERSION = 1
PREFIX = "/api/v1/"
# What only StationPlay's own apps use: not part of the public API (no
# OpenAPI, no promise it stays the same; see docs/internal-api.md).
INTERNAL = "/api/internal/"
HEADER = (b"stationplay-api", str(VERSION).encode())
FEATURES = ("hls", "speed-test", "reports", "night", "problems")

GUIDE_DEFAULT_MS = 6 * 3600_000
GUIDE_MAX_MS = 2 * 86_400_000
GUIDE_REACH_MS = 7 * 86_400_000  # how far from now a guide may start
COLOURS_AT_ONCE = 4  # logos read for their colors at once (each by ffmpeg)


class ApiHeader:
    """Adds `StationPlay-API: 1` to every answer under /api/v1 and
    /api/internal, refusals included: a plain ASGI layer, outside the
    others."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(
        self, scope: dict, receive: Callable[[], Awaitable[Any]], send: Callable
    ) -> None:
        if scope["type"] != "http" or not scope["path"].startswith((PREFIX, INTERNAL)):
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
    # An app with a picker (see devices.py): it's linked as a device, and
    # sends the key it has, if any.
    picker: bool = False
    deviceKey: str | None = Field(default=None, max_length=100)


class LinkStart(BaseModel):
    app: str = Field(default="", max_length=APP_MAX)
    deviceName: str = Field(default="", max_length=APP_MAX)
    picker: bool = False
    deviceKey: str | None = Field(default=None, max_length=100)


class PickerChoice(BaseModel):
    id: int
    pin: str | None = Field(default=None, max_length=10)
    password: str | None = Field(default=None, max_length=access.PASSWORD_MAX)


class PickerSignIn(BaseModel):
    name: str = Field(max_length=100)
    code: str | None = Field(default=None, max_length=20)
    password: str | None = Field(default=None, max_length=access.PASSWORD_MAX)
    secret: str | None = Field(default=None, max_length=access.PASSWORD_MAX)  # (either)


class LinkCheck(BaseModel):
    poll: str = Field(max_length=100)


class PinChange(BaseModel):
    pin: str | None = Field(max_length=10)  # (4 digits; null: no passcode)


class SpeedTested(BaseModel):
    mbps: float
    app: str = Field(default="", max_length=APP_MAX)
    deviceName: str = Field(default="", max_length=APP_MAX)


class LinkCode(BaseModel):
    code: str = Field(max_length=20)


# Problem reports from the apps: what goes in the Logs tab, at most.
REPORT_MAX = 24_000
REPORT_LINES = 400
REPORT_EVERY_S = 30  # one from each address at most this often


class Report(BaseModel):
    text: str = Field(max_length=REPORT_MAX * 8)  # (what is kept: report_text)
    app: str = Field(default="", max_length=APP_MAX)
    deviceName: str = Field(default="", max_length=APP_MAX)


class Problem(BaseModel):
    """A problem an app ran into, sent as it happens (see problems.py)."""

    kind: str = Field(max_length=40)
    detail: str = Field(default="", max_length=problems.TEXT_MOST * 4)
    station: int | None = None
    title: str = Field(default="", max_length=problems.NAME_MOST * 4)
    app: str = Field(default="", max_length=APP_MAX)
    version: str = Field(default="", max_length=APP_MAX)
    device: str = Field(default="", max_length=problems.NAME_MOST * 4)
    deviceName: str = Field(default="", max_length=APP_MAX)


def report_text(text: str) -> str:
    """A report as the Logs tab shows it: each line plain, and no more than
    REPORT_LINES of them or REPORT_MAX characters (the rest left off, and
    said so)."""
    lines = [plain(line) for line in text.splitlines()]
    kept: list[str] = []
    size = 0
    for line in lines:
        if len(kept) >= REPORT_LINES or size + len(line) > REPORT_MAX:
            more = len(lines) - len(kept)
            kept.append(f"(and {more} more {'line' if more == 1 else 'lines'}, left off)")
            break
        kept.append(line)
        size += len(line) + 1
    return "\n".join(kept).strip()


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
    """A program, as the API describes one (see "A program" in
    docs/api.md). Text is made plain: one program's odd details in
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


def slot_program(station: StationSchedule, slot: Slot | None) -> dict[str, Any] | None:
    """A station's program, as the API describes one (None for none)."""
    if slot is None:
        return None
    special = specials.label(station.special(slot), slot.index)
    return program(slot.item, slot.start_ms, slot.end_ms, special)


def routes(app: FastAPI, ctx: AppContext) -> None:
    """The API's addresses for the server, its stations and guide, and the
    apps' own for signing in and connection tests."""
    app.add_middleware(ApiHeader)
    settings = ctx.settings

    @app.exception_handler(RequestValidationError)
    async def not_understood(request: Request, e: RequestValidationError):
        """For apps, a sentence (as every refusal is); for the page, as
        FastAPI says it."""
        if not request.url.path.startswith((PREFIX, INTERNAL)):
            return await request_validation_exception_handler(request, e)
        errors = list(e.errors())
        where = tuple(errors[0].get("loc", ())) if errors else ()
        if len(where) == 2 and where[0] in ("query", "path"):
            detail = f"StationPlay didn't understand {where[1]!r} in that request"
        else:
            detail = "StationPlay didn't understand that request"
        return JSONResponse({"detail": detail}, 400)

    @app.get(
        "/api/v1/server",
        response_model=api.Server,
        operation_id="getServer",
        summary="What this server is",
        description="Asked first: its name and version, whether requests need a token, and "
        "what it offers here. Needs no token.",
    )
    async def server(request: Request):
        not_set_up = (
            access.NOT_SET_UP if access.outside(request.scope) and not ctx.access.required else None
        )
        away = ctx.away.address if ctx.away.on else None
        # (Your library: at home, or through a VPN; and through the public
        # port while watching away from home is on.)
        media = ctx.media_here(access.outside(request.scope))
        return {
            "name": settings.friendly_name,
            "id": ctx.device_id,
            "version": __version__,
            "api": VERSION,
            "signIn": ctx.access.required or not_set_up is not None,
            "notSetUp": not_set_up,
            "outside": access.outside(request.scope),
            "awayAddress": away,
            "features": [
                *FEATURES,
                *(["away"] if away else []),
                *(["library"] if media else []),
                # (Copies of what a device can't play as it is: see converting.py.)
                *(["convert"] if media else []),
                # (Even sound for a show's episodes, while it's on: see applibrary.py.)
                *(["even-sound"] if media and ctx.shared.even_sound else []),
            ],
        }

    @app.post("/api/internal/sign-in")
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
        device = None if known else ctx.access.remember_device(user)
        if body.picker:
            linked, new_key = linked_device(body.deviceKey, label, user)
            token = ctx.access.start_session(user, linked.name, linked.id)
        else:
            new_key, token = None, ctx.access.start_session(user, label)
        ctx.access.record(
            logging.INFO,
            f"{user.name} ({access.role_name(user.role)}) signed in to {in_sentence(label)} "
            f"from {access.where(request.scope)}" + (" (and linked it)" if new_key else ""),
        )
        return {
            "token": token,
            "device": device,
            "deviceKey": new_key,
            "user": {"name": user.name, "role": user.role},
            "askPin": ctx.devices.asks_for_pin(user),
        }

    def linked_device(key: str | None, label: str, user: User) -> tuple[devices.Device, str | None]:
        """The device an app with a picker is: the one its key says, or a
        new one, linked now (and its key). Whoever signed in is on its
        picker from now on."""
        found = ctx.devices.device(key, label)
        new_key = None
        if found is None:
            found, new_key = ctx.devices.link(label, user)
        ctx.devices.note_signed_in(found, user)
        return found, new_key

    # Signing in with a code (see links.py) --------------------------------

    @app.post("/api/internal/link")
    async def link_start(body: LinkStart, request: Request):
        if not ctx.access.required:
            raise HTTPException(400, "Signing in to StationPlay is off, so there's no need to")
        try:
            code, poll = ctx.links.start(
                app_label(body.app, body.deviceName),
                access.address(request.scope),
                body.picker,
                body.deviceKey,
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

    @app.post("/api/internal/link/check")
    async def link_check(body: LinkCheck):
        pending = ctx.links.check(body.poll)
        if pending is None:
            raise HTTPException(404, "That code has run out. Ask for a new one.")
        if pending.token is None or pending.user is None:
            return JSONResponse({"detail": "Waiting for the code to be entered"}, 202)
        user = pending.user
        return {
            "token": pending.token,
            "deviceKey": pending.new_key,
            "user": {"name": user.name, "role": user.role},
            "askPin": ctx.devices.asks_for_pin(user),
        }

    @app.get("/api/internal/me")
    async def me(request: Request):
        """Who this app is signed in as now (for its Options): their name, as
        an Admin may have changed it since they signed in, their role, and
        whether they have a PIN. Null while signing in is off."""
        user = access.signed_in(request)
        if user is None:
            return {"user": None}
        return {"user": {"name": user.name, "role": user.role, "pin": user.has_pin}}

    def own_app(request: Request) -> tuple[User, SignedIn]:
        """Who an app is signed in as, and its sign-in, for what someone
        changes of their own in it. Not a browser's sign-in: StationPlay's
        page has its own."""
        if not ctx.access.required:
            raise HTTPException(400, "Signing in to StationPlay is off, so there's no need to")
        user = access.signed_in(request)
        token = access.bearer(request.scope)
        found = ctx.db.session_user(access.session_hash(token), 0) if token and user else None
        if user is None or found is None or not found.app:
            raise HTTPException(403, "Only StationPlay's apps can do that")
        return user, found

    @app.post("/api/internal/pin")
    async def own_pin(body: PinChange, request: Request):
        """Someone chooses their own PIN (a passcode, as the apps say), or
        says they want none (see devices.set_own_pin): when an app asks,
        after they sign in with their password or an invite code (`askPin`),
        or in its Options."""
        user, signed = own_app(request)
        try:
            has = await ctx.devices.set_own_pin(user, body.pin)
        except devices.Refused as e:
            raise HTTPException(e.status, str(e)) from None
        chose = "set a passcode" if has else "chose no passcode"
        ctx.access.record(logging.INFO, f"{user.name} {chose} in {in_sentence(signed.app)}")
        return {"pin": has}

    @app.post("/api/internal/sign-out")
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

    # Who's tuning in? A linked device's picker (see devices.py) ------------

    def this_device(request: Request) -> devices.Device:
        if not ctx.access.required:
            raise HTTPException(400, "Signing in to StationPlay is off, so there's no need to")
        found = ctx.devices.device(request.headers.get(devices.DEVICE_HEADER))
        if found is None:
            raise HTTPException(401, "This device isn't linked to StationPlay. Sign in again.")
        return found

    def person_json(user: User) -> dict[str, Any]:
        return {
            "id": user.id,
            "name": user.name,
            "pin": user.has_pin,
            "admin": user.role == access.ADMIN,
        }

    @app.get("/api/internal/picker")
    async def picker(request: Request):
        """Who's on this device's picker where it is now: at home (on the
        home port, through a VPN too), or away from home (the public port),
        where it lists only who's on every device, signed in on it or was
        chosen for it."""
        device = this_device(request)
        at_home = not access.outside(request.scope)
        return {
            "device": device.name,
            "people": [person_json(u) for u in ctx.devices.people(device, at_home)],
        }

    @app.post("/api/internal/picker/choose")
    async def picker_choose(body: PickerChoice, request: Request):
        device = this_device(request)
        try:
            user, token = await ctx.devices.choose(
                device,
                body.id,
                body.pin,
                body.password,
                access.address(request.scope),
                public=access.outside(request.scope),
            )
        except devices.Refused as e:
            raise HTTPException(e.status, str(e)) from None
        except access.Busy as e:
            raise HTTPException(429, str(e)) from None
        log.info("%s is watching on %s", user.name, device.name)
        return {"token": token, "user": {"name": user.name, "role": user.role}}

    @app.post("/api/internal/picker/sign-in")
    async def picker_sign_in(body: PickerSignIn, request: Request):
        device = this_device(request)
        try:
            user, token = await ctx.devices.sign_in_by_name(
                device,
                body.name,
                body.code,
                body.password,
                access.address(request.scope),
                public=access.outside(request.scope),
                secret=body.secret,
            )
        except devices.Refused as e:
            raise HTTPException(e.status, str(e)) from None
        except access.Busy as e:
            raise HTTPException(429, str(e)) from None
        ctx.access.record(
            logging.INFO,
            f"{user.name} ({access.role_name(user.role)}) signed in on {device.name} "
            f"from {access.where(request.scope)}",
        )
        return {
            "token": token,
            "user": {"name": user.name, "role": user.role},
            "askPin": ctx.devices.asks_for_pin(user),
        }

    @app.post("/api/internal/picker/remove")
    async def picker_remove(request: Request):
        device = this_device(request)
        user = access.signed_in(request)
        if user is None:
            raise HTTPException(401, "Sign in to StationPlay")
        ctx.devices.remove(device, user)
        token = access.bearer(request.scope)
        if token:
            ctx.access.end_session(token)
        ctx.access.record(logging.INFO, f"{user.name} took themselves off {device.name}")
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
        if pending.picker:
            linked, new_key = linked_device(pending.device_key, pending.app, user)
            ctx.links.link(
                pending, user, ctx.access.start_session(user, linked.name, linked.id), new_key
            )
        else:
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

    def note_app(request: Request, key: str | None) -> None:
        """Whose app this is, at its address at home (or at its own stream
        address away from home): asked for the stations, it's about to
        watch one, and its player asks for it without signing in (see
        playing.py). Not for an API token's script."""
        user = access.signed_in(request)
        token = access.bearer(request.scope) or request.cookies.get(access.COOKIE)
        app = ctx.db.session_app(access.session_hash(token)) if token and user else None
        if user is None or app is None:
            return
        if key:
            where = access.address(request.scope)
            ctx.apps.saw(f"k:{key}", playing.Watcher(where, True, user.name, user.id, app, key[:6]))
        elif not access.outside(request.scope):
            where = request.client.host if request.client else "?"
            ctx.apps.saw(where, playing.Watcher(where, False, user.name, user.id, app))

    def hls_address(number: int, key: str | None) -> str:
        """Where an app plays a station: at home, its HLS; from outside, its
        HLS at the app's own address."""
        return f"/hls/k/{key}/{number}/index.m3u8" if key else f"/hls/{number}/index.m3u8"

    def night_address(number: int, key: str | None) -> str:
        """The same, with night mode's sound (see hls.py)."""
        return hls_address(number, key).replace("/index.m3u8", "/night/index.m3u8")

    def logo_address(channel: Channel, key: str | None) -> str:
        """A station's logo: at home, where Plex gets it; from outside, at
        the app's own address (with the same version, which changes with it)."""
        home = hdhr.icon_url("", channel)
        if not key:
            return home
        return f"/hls/k/{key}/{channel.number}/logo.png?{home.partition('?')[2]}"

    @app.get(
        "/api/v1/stations",
        response_model=api.Stations,
        operation_id="getStations",
        summary="The stations",
        description="Every station, with what's on now and next, and where to play it.",
    )
    async def stations(request: Request):
        key = away_key(request)
        note_app(request, key)
        channels = ctx.stations_for(access.signed_in(request))
        now = now_ms()

        def on_now() -> list[tuple[dict | None, dict | None]]:  # (a big shuffle takes a moment)
            out = []
            for channel in channels:
                station = ctx.station(channel.id)
                slot = station.locate(now)
                out.append(
                    (
                        slot_program(station, slot),
                        slot_program(station, slot and station.after(slot)),
                    )
                )
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
                    "nightHls": night_address(c.number, key),
                    "now": now_on,
                    "next": next_on,
                }
                for c, palette, (now_on, next_on) in zip(channels, palettes, airing, strict=True)
            ]
        }

    # Connection tests (see capacity.py) ------------------------------------

    @app.get("/api/internal/speed-test")
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

    @app.post("/api/internal/speed-test")
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

    # Problem reports (see the apps' Options: Send a report) ----------------------

    reported: dict[str, float] = {}

    @app.post("/api/internal/report")
    async def report(body: Report, request: Request):
        """A report from an app, in the Logs tab (and StationPlay's log), for
        whoever is looking into a problem: what the app did lately, and on
        what device. One from each address every REPORT_EVERY_S at most."""
        now = time.monotonic()
        address = access.address(request.scope)
        if now - reported.get(address, -REPORT_EVERY_S) < REPORT_EVERY_S:
            raise HTTPException(429, "A report was just sent from here. Try again in a minute.")
        for at, when in list(reported.items()):
            if now - when >= REPORT_EVERY_S:
                del reported[at]
        text = report_text(body.text)
        if not text:
            raise HTTPException(400, "The report is empty")
        reported[address] = now
        user = access.signed_in(request)
        by = f" ({user.name})" if user else ""
        log.warning("Report from %s%s:\n%s", app_label(body.app, body.deviceName), by, text)
        return {"ok": True}

    @app.post("/api/internal/problem")
    async def problem(body: Problem, request: Request):
        """A problem an app ran into, as it happened (from 1.23.0, when
        `features` lists `problems`): kept for the Logs tab, with which app
        and what kind of device, so an Admin can tell whose problem it is."""
        user = access.signed_in(request)
        sent = problems.Sent(
            body.kind, body.detail, body.station, body.title, body.app, body.version,
            body.device, body.deviceName,
        )  # fmt: skip
        try:
            ctx.problems.note(
                sent,
                user.id if user else None,
                access.outside(request.scope),
                access.address(request.scope),
            )
        except problems.Refused as e:
            raise HTTPException(e.status, str(e)) from None
        return {"ok": True}

    @app.get(
        "/api/v1/guide",
        response_model=api.Guide,
        operation_id="getGuide",
        summary="The guide",
        description="Each station's programs between two times: 6 hours from now unless asked; "
        "at most 2 days, starting within 7 days of now.",
    )
    async def guide(
        request: Request,
        start: int | None = Query(None, alias="from", description="Where it starts (ms)"),
        end: int | None = Query(None, alias="to", description="Where it ends (ms)"),
    ):
        now = now_ms()
        from_ms = now if start is None else start
        to_ms = from_ms + GUIDE_DEFAULT_MS if end is None else end
        if abs(from_ms - now) > GUIDE_REACH_MS:
            raise HTTPException(400, "The guide can start at most 7 days from now")
        if not 0 < to_ms - from_ms <= GUIDE_MAX_MS:
            raise HTTPException(400, "The guide can cover at most 2 days, after its start")
        channels = ctx.stations_for(access.signed_in(request))

        def listing() -> list[dict]:  # (on a worker thread, as on_now)
            out = []
            for channel in channels:
                station = ctx.station(channel.id)
                programs = [slot_program(station, slot) for slot in station.between(from_ms, to_ms)]
                out.append({"number": channel.number, "programs": programs})
            return out

        return {"from": from_ms, "to": to_ms, "stations": await asyncio.to_thread(listing)}
