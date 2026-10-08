"""StationPlay's API, version 1 (/api/v1): for anyone's scripts, home
automation and apps, documented in docs/api.md with an OpenAPI spec
(docs/openapi-v1.json, served at /api/v1/openapi.json), which the tests
check against the server.

Reading needs a Viewer API token (or any sign-in); doing needs an Admin one
(see access.py). While signing in is off, nothing needs a token on the home
network, as with the rest of StationPlay.

Version 1 is a stable contract: it only grows. New fields and addresses may
be added; nothing is renamed, removed or changed in meaning. A change that
would break a client becomes version 2, served beside version 1, which is
then marked with Deprecation and Sunset headers (DEPRECATED) for at least
six months before it goes.

What only StationPlay's own apps use is under /api/internal instead (see
appapi.py and applibrary.py): not part of this API, and free to change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ConfigDict, Field

from . import access

if TYPE_CHECKING:
    from .main import AppContext

log = logging.getLogger(__name__)

PREFIX = "/api/v1/"
SPEC_PATH = "/api/v1/openapi.json"
# Addresses on their way out: path prefix -> (when they go, as an HTTP date,
# and where to read about it). None yet.
DEPRECATED: dict[str, tuple[str, str]] = {}
ADMIN_TAG = "Admin"
DESCRIPTION = (
    "StationPlay's API: the server, its stations, their guide and streams, and things an "
    "Admin can have it do. Send an API token (made on StationPlay's Access tab) as "
    "`Authorization: Bearer <token>`: a Viewer token reads, an Admin token also does what's "
    "marked Admin. Version 1 only grows; see docs/api.md."
)


# What the API answers (its OpenAPI spec is made from these) ----------------------------


class _Shape(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class Server(_Shape):
    name: str = Field(description="The server's name, as set when it was set up")
    id: str = Field(description="The server's own ID, the same for as long as it's set up")
    version: str = Field(description="StationPlay's version, such as 1.22.0")
    api: int = Field(description="The newest API version this server answers (1)")
    signIn: bool = Field(description="Whether requests need a token (signing in is on)")
    notSetUp: str | None = Field(
        description="Why the server can't be used from here yet (a sentence), or null"
    )
    outside: bool = Field(
        description="Whether this request came from the internet (the public port)"
    )
    awayAddress: str | None = Field(
        description="Where StationPlay's apps reach it from outside, when that's on"
    )
    features: list[str] = Field(
        description="What it offers here: hls, speed-test, away, library, reports (more may be "
        "added)"
    )


class Colors(_Shape):
    dark: str = Field(description="#RRGGBB")
    light: str = Field(description="#RRGGBB")
    accent: str = Field(description="#RRGGBB")


class Program(_Shape):
    start: int = Field(description="When it starts, in milliseconds since 1970 (UTC)")
    end: int = Field(description="When it ends (the commercials after it included)")
    kind: str = Field(description="episode or movie")
    title: str = Field(description="The show's title, or the movie's")
    episodeTitle: str | None = Field(description="The episode's title (null for a movie)")
    season: int | None
    episode: int | None
    year: int | None
    summary: str = Field(description="What it's about (may be empty)")
    art: str = Field(description="Its picture, on the home network: the show's, or the movie's")
    special: str | None = Field(
        description="What special it's part of: 'Feature Presentation', a block's name, or a "
        "marathon's"
    )


class Station(_Shape):
    number: int
    name: str
    description: str
    logo: str = Field(description="Its logo (an address on the server)")
    colors: Colors = Field(description="Colors from its logo, as its Intro Bumper uses them")
    hls: str = Field(
        description="Where to play it (HLS): an address on the server. From the internet (with "
        "watching away from home on), an address of the token's own, which needs no token itself"
    )
    nightHls: str = Field(
        description="The same with night mode's sound: loud scenes quieter and quiet voices "
        "clearer, made by the server (the picture is the same). From 1.23.0"
    )
    now: Program | None = Field(description="What's on now")
    next: Program | None = Field(description="What's on next")


class Stations(_Shape):
    stations: list[Station] = Field(description="Every station, in number order")


class GuideStation(_Shape):
    number: int
    programs: list[Program] = Field(description="Its programs in the time asked for, in order")


class Guide(_Shape):
    from_: int = Field(alias="from", description="Where the guide starts (ms)")
    to: int = Field(description="Where it ends (ms)")
    stations: list[GuideStation]


class Playing(_Shape):
    number: int = Field(description="The station's number")
    viewers: int = Field(description="Devices watching it")


class Status(_Shape):
    version: str = Field(description="StationPlay's version")
    plexConnected: bool = Field(description="Whether Plex answers")
    tuners: int = Field(description="How many stations can play at once")
    playing: list[Playing] = Field(description="The stations playing now")


class Updated(_Shape):
    number: int
    changed: bool = Field(description="Whether Plex had anything new for it")


class Check(_Shape):
    number: int
    running: bool = Field(description="Whether the check is still going")
    total: int = Field(description="Programs to check (0: no check yet)")
    done: int = Field(description="Programs checked so far")
    newlyBroken: int = Field(description="Programs it found problems in (now off the air)")
    skipped: int = Field(description="Programs that couldn't be checked")


class GuideRefreshed(_Shape):
    refreshed: bool = Field(description="Whether Plex said it would refresh its guide")


class Backup(_Shape):
    name: str = Field(description="The backup's file name, in the backups folder")


# The Admin's actions, from main.py (where the page's own do the same) ----------------------


@dataclass
class Actions:
    status: Callable[[], Awaitable[dict[str, Any]]]
    update_station: Callable[[int, Request], Awaitable[bool]]  # (channel id) -> changed
    check_station: Callable[[int], dict[str, Any]]  # (channel id) -> the check, so far
    refresh_guide: Callable[[], Awaitable[bool]]
    backup: Callable[[], Awaitable[str]]
    asking_plex: list[Any] = field(default_factory=list)  # (what limits asking Plex at once)


class NewToken(BaseModel):
    name: str = Field(max_length=access.API_TOKEN_NAME_MAX)
    scope: str = Field(max_length=10)
    days: int | None = Field(default=None, ge=1, le=3650)


class TokensOutside(BaseModel):
    on: bool


def routes(app: FastAPI, ctx: AppContext, actions: Actions) -> None:
    """The API's own addresses (the server, its stations and guide are in
    appapi.py), its spec, and the Access tab's API tokens."""
    app.add_middleware(Deprecations)

    def station_id(number: int) -> int:
        channel = ctx.db.get_channel_by_number(number)
        if channel is None:
            raise HTTPException(404, f"There's no station {number}")
        return channel.id

    @app.get(
        "/api/v1/status",
        response_model=Status,
        operation_id="getStatus",
        summary="How StationPlay is doing",
        description="Whether Plex answers, how many tuners there are, and what's playing.",
    )
    async def status():
        return await actions.status()

    @app.post(
        "/api/v1/stations/{number}/update",
        response_model=Updated,
        operation_id="updateStation",
        dependencies=actions.asking_plex,
        tags=[ADMIN_TAG],
        summary="Update a station from Plex now",
        description="Follows Plex straight away (as Update now does on the page): new and "
        "removed programs, with a held update applied. Admin.",
    )
    async def update_station(number: int, request: Request):
        changed = await actions.update_station(station_id(number), request)
        return {"number": number, "changed": changed}

    def check_json(number: int, job: dict[str, Any] | None) -> dict[str, Any]:
        job = job or {}
        return {
            "number": number,
            "running": bool(job.get("running")),
            "total": int(job.get("total") or 0),
            "done": int(job.get("done") or 0),
            "newlyBroken": int(job.get("newlyBroken") or 0),
            "skipped": int(job.get("skipped") or 0),
        }

    @app.post(
        "/api/v1/stations/{number}/check",
        response_model=Check,
        operation_id="checkStation",
        tags=[ADMIN_TAG],
        summary="Check a station's files",
        description="Starts the quick check of each of its programs' files, as Check files does "
        "on the page (or, while one is running, says how far it has got). Admin.",
    )
    async def check_station(number: int):
        channel_id = station_id(number)
        actions.check_station(channel_id)
        await asyncio.sleep(0)  # (the check's first step: counting what it checks)
        job = ctx.checks.get(channel_id)
        return check_json(number, job.as_dict() if job else None)

    @app.get(
        "/api/v1/stations/{number}/check",
        response_model=Check,
        operation_id="getStationCheck",
        tags=[ADMIN_TAG],
        summary="How a station's file check is going",
        description="Its last check, running or done, without starting one. Admin.",
    )
    async def station_checked(number: int):
        job = ctx.checks.get(station_id(number))
        return check_json(number, job.as_dict() if job else None)

    @app.post(
        "/api/v1/guide/refresh",
        response_model=GuideRefreshed,
        operation_id="refreshGuide",
        dependencies=actions.asking_plex,
        tags=[ADMIN_TAG],
        summary="Ask Plex to refresh its guide",
        description="As StationPlay does by itself after a change. Admin.",
    )
    async def refresh_guide():
        return {"refreshed": await actions.refresh_guide()}

    @app.post(
        "/api/v1/backups",
        response_model=Backup,
        operation_id="makeBackup",
        status_code=201,
        tags=[ADMIN_TAG],
        summary="Back StationPlay up now",
        description="Makes a backup, as StationPlay does every night. Admin.",
    )
    async def backup():
        return {"name": await actions.backup()}

    @app.get(SPEC_PATH, include_in_schema=False)
    async def openapi_json():
        return spec(app)

    # The Access tab: API tokens --------------------------------------------------

    def token_json(t: access.ApiToken) -> dict[str, Any]:
        return {
            "id": t.id,
            "name": t.name,
            "scope": t.scope,
            "by": t.owner.name,
            "createdMs": t.created_ms,
            "usedMs": t.used_ms or None,
            "expiresMs": t.expires_ms,
        }

    @app.get("/api/api-tokens")
    async def api_tokens():
        return {
            "tokens": [token_json(t) for t in ctx.access.api_tokens()],
            "outside": ctx.access.api_outside,
            "signIn": ctx.access.required,
        }

    @app.post("/api/api-tokens", status_code=201)
    async def make_api_token(body: NewToken, request: Request):
        who = access.signed_in(request)
        if who is None:
            raise HTTPException(
                400, "API tokens come with signing in: add the first user on the Access tab"
            )
        try:
            made, token = ctx.access.make_api_token(body.name, body.scope, who, body.days)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return {**token_json(made), "token": token}

    @app.delete("/api/api-tokens/{token_id}", status_code=204)
    async def revoke_api_token(token_id: int, request: Request):
        if not ctx.access.revoke_api_token(token_id, access.signed_in(request)):
            raise HTTPException(404, "There's no such API token")
        return Response(status_code=204)

    @app.put("/api/api-tokens/outside")
    async def tokens_outside(body: TokensOutside, request: Request):
        ctx.access.set_api_outside(body.on, access.signed_in(request))
        return await api_tokens()


def spec(app: FastAPI) -> dict[str, Any]:
    """The OpenAPI spec of version 1: its addresses, what each answers, and
    the token they take."""
    v1 = [r for r in app.routes if getattr(r, "path", "").startswith(PREFIX)]
    out = get_openapi(
        title="StationPlay API",
        version="1",
        description=DESCRIPTION,
        routes=v1,
        tags=[{"name": ADMIN_TAG, "description": "Needs an Admin token"}],
    )
    out["info"]["license"] = {"name": "GPL-3.0-only"}
    components = out.setdefault("components", {})
    components["securitySchemes"] = {
        "token": {
            "type": "http",
            "scheme": "bearer",
            "description": "An API token from the Access tab (or a StationPlay app's sign-in)",
        }
    }
    out["security"] = [{"token": []}]
    # Refusals are a sentence, as every one is (not FastAPI's 422s).
    schemas = components.setdefault("schemas", {})
    for name in ("HTTPValidationError", "ValidationError"):
        schemas.pop(name, None)
    schemas["Error"] = {
        "type": "object",
        "title": "Error",
        "properties": {"detail": {"type": "string", "description": "Why, as a sentence to show"}},
        "required": ["detail"],
    }
    for path, operations in out["paths"].items():
        for operation in operations.values():
            answers = operation["responses"]
            answers.pop("422", None)
            if operation.get("parameters"):
                answers["400"] = _error("Something in the request wasn't understood")
            if path == "/api/v1/server":
                operation["security"] = []  # (what a client asks first, before it has a token)
                continue
            answers["401"] = _error("No token, or one that isn't valid (while signing in is on)")
            answers["403"] = _error("The token may not do this, or isn't accepted from there")
            if "{number}" in path:
                answers["404"] = _error("There's no such station")
    return out


def _error(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    }


class Deprecations:
    """Marks answers from addresses on their way out (DEPRECATED) with
    Deprecation, Sunset and a link to read about it: a plain ASGI layer."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        going = None
        if scope["type"] == "http":
            path = scope["path"]
            going = next((v for k, v in DEPRECATED.items() if path.startswith(k)), None)
        if going is None:
            await self.app(scope, receive, send)
            return
        sunset, link = going

        async def sending(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (b"deprecation", b"true"),
                    (b"sunset", sunset.encode()),
                    (b"link", f'<{link}>; rel="deprecation"'.encode()),
                ]
                message = {**message, "headers": [*(message.get("headers") or ()), *headers]}
            await send(message)

        await self.app(scope, receive, sending)
