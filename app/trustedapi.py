"""Signing in on a trusted network (1.36.0; see trusted.py for what an Admin
lists, and access.Gate for when a request comes from one).

On a network that opens on Who's tuning in?, an app gets a device key that
works only there, for its picker (see devices.py), which lists only those
who signed in on that device (1.38.0). The page's sign-in screen there is
as at any home address. On a network that signs in as someone, the page
and apps are signed in as them, for watching. Either way, what's made works
only on that network (a token of its own kind: see access.session_hash),
and anyone can still sign in as someone else.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import access, devices, networks, trusted
from .appapi import app_label
from .db import User

if TYPE_CHECKING:
    from .main import AppContext
    from .relays import Relays

log = logging.getLogger(__name__)

NOT_TRUSTED = "This device isn't on a trusted network. Sign in to tapiOca."
# (An app without Who's tuning in?, on a network that opens on it.)
NO_PICKER = (
    "On this network, each person picks themselves on Who's tuning in?, which this app "
    "doesn't have. Sign in to tapiOca."
)
NOT_LISTED = "That person isn't on this network's list"
# Asking a trusted network for a sign-in or a device: so many from one
# address in ASKS_WINDOW_S (the cold audit of 1.36.0).
ASKS_MOST = 20
ASKS_WINDOW_S = 15 * 60
TOO_MANY = "Too many sign-ins from this device lately. Try again in a few minutes."
AWAY_NAME = (
    "{name} is your away-from-home address's name, which is how the internet reaches tapiOca, "
    "so it can't be a name for home. Use another name for tapiOca at home."
)


class TrustedSignIn(BaseModel):
    """Picking someone on a trusted network's list, on tapiOca's page."""

    id: int | None = None
    pin: str | None = Field(default=None, max_length=8)
    password: str | None = Field(default=None, max_length=access.PASSWORD_MAX)


class TrustedLists(BaseModel):
    """What an Admin lists (each only if sent): trusted networks, trusted
    proxies, names for tapiOca at home."""

    entries: list[dict[str, Any]] | None = Field(default=None, max_length=trusted.ENTRIES_MOST + 1)
    proxies: list[dict[str, Any]] | None = Field(default=None, max_length=trusted.PROXIES_MOST + 1)
    homeNames: list[str] | None = Field(default=None, max_length=trusted.HOME_NAMES_MOST + 1)
    confirmWide: bool = False


def changed_entries(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    """The entries that went, or now give something else (another network,
    behavior or person): the ids whose sign-ins and devices end."""
    now = {e["id"]: e for e in after}
    keys = ("network", "gives", "person")
    return [
        e["id"] for e in before
        if e["id"] not in now or any(e.get(k) != now[e["id"]].get(k) for k in keys)
    ]  # fmt: skip


def offer_for(verdict: networks.Verdict | None, seen: Relays | None = None) -> str | None:
    """The network an Admin is on now, to offer as a trusted one: the /24
    (or /64) around the address tapiOca sees them at, at home only. Never
    a relay's (Docker's gateway's, say: it would trust everyone it carries),
    and nothing while relays hide every device (see relays.py)."""
    if verdict is None or verdict.outside or verdict.untrusted_headers:
        return None
    ip = verdict.visitor if verdict.via_proxy else verdict.peer
    if ip is None or not networks.is_home(ip) or ip.is_loopback:
        return None
    if seen is not None and (seen.trust_off() or seen.is_relay(ip)):
        return None
    prefix = 24 if ip.version == 4 else 64
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))


class TrustedApp(BaseModel):
    """An app on a trusted network, asking what it gets there."""

    app: str = Field(max_length=80)
    deviceName: str = Field(default="", max_length=80)
    picker: bool = False  # it has Who's tuning in?
    deviceKey: str | None = Field(default=None, max_length=100)


def routes(app: FastAPI, ctx: AppContext) -> None:
    asked: dict[str, deque[float]] = {}

    def entry_of(request: Request) -> dict[str, Any]:
        """The trusted network a request comes from, counted against its
        address's ASKS_MOST (HTTPException otherwise)."""
        entry = request.scope.get("state", {}).get("trusted")
        if entry is None:
            raise HTTPException(403, NOT_TRUSTED)
        now = time.monotonic()
        here = asked.setdefault(access.counted_as(access.address(request.scope)), deque())
        while here and now - here[0] > ASKS_WINDOW_S:
            here.popleft()
        if len(here) >= ASKS_MOST:
            raise HTTPException(429, TOO_MANY)
        here.append(now)
        while len(asked) > 1000:  # (the oldest go)
            del asked[next(iter(asked))]
        return entry

    def person_of(entry: dict[str, Any]) -> User:
        user = ctx.db.user(entry["person"]) if entry.get("person") else None
        if user is None:
            raise HTTPException(403, NOT_TRUSTED)
        return user

    def info(entry: dict[str, Any]) -> dict[str, Any] | None:
        """What a trusted network tells the page, signed out: that it signs
        in as someone, never who (the owner, October 17: "No user appears on
        the server sign in page at all unless their user is set as Admin");
        or that it opens on Who's tuning in?, never its people (from 1.38.0
        that list is the apps', of those who signed in on each device; the
        page's sign-in screen has only the Admins who signed in on that
        browser, as at any home address)."""
        if entry["gives"] == "picker":
            return {"gives": "picker"}
        if entry["gives"] != "person":
            return None
        user = ctx.db.user(entry["person"]) if entry.get("person") else None
        return {"gives": "person"} if user else {"gives": "none"}

    ctx.access.trusted_info = info

    def relays_in(network: str) -> list[networks.IP]:
        """This machine's relays inside a listed proxy's network (but
        loopback: a tunnel in tapiOca's own container, see networks.judge)."""
        net = ipaddress.ip_network(network, strict=False)
        return [
            r for r in ctx.relays.relays()
            if r.version == net.version and r in net and not r.is_loopback
        ]  # fmt: skip

    def end_for(ids: list[str], why: str) -> None:
        """Ends what these entries gave (sign-ins, linked devices)."""
        if ids and (ended := ctx.db.end_trusted(ids)):
            ctx.access.record(
                logging.INFO, f"{why}: {ended} sign-in(s) and device(s) it gave ended"
            )

    def people_changed() -> None:
        """Someone removed, or their role changed: never a dangling trust."""
        gone = ctx.trusted.reconcile()
        if gone:
            end_for([e["id"] for e in gone], "A trusted network's person changed")

    ctx.access.on_people_changed = people_changed
    # (And at each start: after reset-access, which removes everyone, or a
    # backup restored from before someone was added.)
    people_changed()

    def you_at(verdict: networks.Verdict | None, request: Request) -> str:
        """Where an Admin is, as the Access tab says it."""
        if verdict is not None and verdict.via_proxy and verdict.visitor is None:
            return f"{verdict.peer}, a trusted proxy that didn't say who you are"
        if verdict is not None and verdict.via_proxy:
            return str(verdict.visitor)
        return (
            str(verdict.peer)
            if verdict is not None and verdict.peer
            else access.address(request.scope)
        )

    @app.get("/api/access/trusted")
    async def lists(request: Request):
        """For Admins: what's listed, where they are now (and the network
        to offer them), and what came through a door left open."""
        state = request.scope.get("state", {})
        entry = state.get("trusted")
        verdict = state.get("verdict")
        mine = {}
        for row in ctx.db.linked_devices():
            if row["trusted"]:
                mine[row["trusted"]] = mine.get(row["trusted"], 0) + 1
        return {
            "entries": [
                {**e, "addresses": ipaddress.ip_network(e["network"]).num_addresses,
                 "devices": mine.get(e["id"], 0)}
                for e in ctx.trusted.entries
            ],
            # (A proxy that's a relay is right only for a reverse proxy on
            # this same machine: everything else it carries, with no one
            # named, is taken as from the internet. The tab says so.)
            "proxies": [
                {**p, "relay": bool(relays_in(p["network"]))}
                for p in ctx.trusted.proxies
            ],
            "homeNames": ctx.trusted.home_names,
            "you": {
                "address": you_at(verdict, request),
                "entry": entry["id"] if entry else None,
                "offer": offer_for(verdict, ctx.relays),
            },
            # (hidden: trusted networks are off, see relays.py; partial:
            # some connections come through a relay, never trusted.)
            "seeing": ctx.relays.state(),
            "relayAddress": ctx.relays.last_relay,
            "doors": ctx.doors.listed(),
        }  # fmt: skip

    @app.put("/api/access/trusted")
    async def change_lists(body: TrustedLists, request: Request):
        # (What's home decides where a PIN gives Admin tools, and who a
        # network signs in: only with a password. The cold audit of 1.38.0.)
        ctx.access.refuse_without_secret(request)
        before = ctx.trusted.entries
        given = body.model_dump(exclude_none=True)
        # (Never the Away from home address's name, which is how the internet
        # reaches tapiOca: the Gate never takes it for home. The cold audit
        # of 1.36.0: it was kept, and did nothing.)
        hosts = getattr(ctx, "gate_hosts", None)
        never = {h.lower() for h in hosts()[1]} if hosts else set()
        for name in body.homeNames or []:
            shown = str(name).strip().rstrip(".")
            if shown.lower() in never:
                raise HTTPException(400, AWAY_NAME.format(name=shown))
        try:
            ctx.trusted.save(given, by=(u.id if (u := access.signed_in(request)) else None))
        except trusted.Wide as e:
            raise HTTPException(409, str(e)) from None
        except trusted.Refused as e:
            raise HTTPException(400, str(e)) from None
        if ctx.doors is not None:
            ctx.doors.forget_listed(ctx.trusted.is_proxy)
        who = u.name if (u := access.signed_in(request)) else "Someone"
        ctx.access.record(
            logging.INFO, f"{who} changed the trusted networks, proxies or names for home"
        )
        end_for(changed_entries(before, ctx.trusted.entries), "A trusted network changed or went")
        return await lists(request)

    @app.post("/api/access/trusted-sign-in")
    async def trusted_sign_in(body: TrustedSignIn, request: Request, response: Response):
        """Signs tapiOca's page in on a trusted network as the person it signs
        in as, for watching. (Its list of people is the apps' only, from
        1.38.0: see info.)"""
        entry = entry_of(request)
        if entry["gives"] != "person":
            raise HTTPException(404, NOT_LISTED)
        user = person_of(entry)
        # (One that works only here, and only for watching: access.STEP_UP.)
        token = ctx.access.start_session(user, unlocked=True, trusted=entry["id"])
        access.set_sign_in_cookie(response, request, token)
        ctx.access.record(
            logging.INFO,
            f"{user.name} signed in on the trusted network "
            f"{entry.get('label') or entry['network']}, from {access.where(request.scope)}",
        )
        return {"user": {"name": user.name, "role": user.role}}

    @app.post("/api/internal/trusted")
    async def trusted_app(body: TrustedApp, request: Request):
        """What an app gets on a trusted network: a device key for Who's
        tuning in? (only for an app that has it), or a sign-in as the
        person the network signs in as. Both work only there."""
        entry = entry_of(request)
        label = app_label(body.app, body.deviceName)
        if entry["gives"] == "person":
            user = person_of(entry)
            token = ctx.access.start_session(user, label, unlocked=True, trusted=entry["id"])
            ctx.access.record(
                logging.INFO,
                f"{label} was signed in as {user.name} by the trusted network "
                f"{entry.get('label') or entry['network']}",
            )
            # (For watching: an Admin is a User here, as /api/internal/me says.)
            return {
                "gives": "person", "token": token,
                "user": {"name": user.name, "role": access.USER, "byNetwork": True},
                "askPin": False,
            }  # fmt: skip
        if not body.picker:
            raise HTTPException(403, NO_PICKER)
        try:
            known = ctx.devices.device(body.deviceKey, label, where=entry["id"])
        except devices.Refused:
            known = None
        if known is not None and known.trusted == entry["id"]:
            return {"gives": "picker", "deviceKey": None}
        try:
            _, key = ctx.devices.link_trusted(label, entry)
        except devices.Refused as e:
            raise HTTPException(e.status, str(e)) from None
        ctx.access.record(
            logging.INFO,
            f"{label} was linked by the trusted network {entry.get('label') or entry['network']}",
        )
        return {"gives": "picker", "deviceKey": key}
