"""Signing in on a trusted network (1.36.0; see trusted.py for what an Admin
lists, and access.Gate for when a request comes from one).

On a network that opens on Who's tuning in?, the page lists who may pick
themselves (those shown on every device at home, or every device), and an
app gets a device key that works only there, for its picker (see
devices.py). Picking someone with a PIN asks for it; an Admin always gives
their PIN or password. On a network that signs in as someone, the page and
apps are signed in as them. Either way, what's made works only on that
network (a token of its own kind: see access.session_hash), and anyone can
still sign in as someone else.
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
WRONG_PASSWORD = "That password isn't right."
PASSWORD_NOW = (
    f"That's {access.BROWSER_PIN_TRIES} wrong PINs on this device. Sign in with a password, or "
    "try a PIN again later."
)
WRONG_PINS_WINDOW_S = 3600.0  # (wrong PINs from one address are counted this long)


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

    def listed(user: User) -> bool:
        """On a trusted network's list: shown on every device at home, or
        every device (as on a linked device at home, before anyone signs in
        on it)."""
        return ctx.devices.on_picker(user, None, at_home=True)

    def person_of(entry: dict[str, Any]) -> User:
        user = ctx.db.user(entry["person"]) if entry.get("person") else None
        if user is None:
            raise HTTPException(403, NOT_TRUSTED)
        return user

    def browsers_own(request: Request) -> User | None:
        """Whose PIN may sign in on this browser (tapiOca's page, at home):
        someone who signed in on it with their password, since it last
        changed and they last signed out there (see access.pin_browser)."""
        return ctx.access.pin_browser(request.cookies.get(access.DEVICE_COOKIE))

    def info(entry: dict[str, Any], own: User | None = None) -> dict[str, Any]:
        """What a trusted network gives the page: the person it signs in as,
        or the picker's people: those shown at home, and this browser's own
        person (`own`, see browsers_own), so their PIN does here as it does
        on any browser at home (1.37.0, the owner, October 15: signed out
        after an hour, no one was listed, and only a password would do)."""
        if entry["gives"] == "person":
            user = ctx.db.user(entry["person"]) if entry.get("person") else None
            return {"gives": "person", "name": user.name} if user else {"gives": "none"}
        return {
            "gives": "picker",
            "people": [
                {"id": u.id, "name": u.name, "pin": u.has_pin,
                 "password": u.has_password, "admin": u.role == access.ADMIN}
                for u in ctx.db.users() if listed(u) or (own is not None and u.id == own.id)
            ],
        }  # fmt: skip

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

    # Wrong PINs on a trusted network's Who's tuning in?, by the address
    # they came from (never a cookie: a guesser can send a new one each
    # time): BROWSER_PIN_TRIES in WRONG_PINS_WINDOW_S, then a password there
    # (or a wait); on top of each person's own limit (see devices.PIN_TRIES).
    wrong_pins: dict[str, deque[float]] = {}

    def pins_wrong_here(here: str) -> int:
        kept = wrong_pins.get(access.counted_as(here))
        now = time.monotonic()
        while kept and now - kept[0] > WRONG_PINS_WINDOW_S:
            kept.popleft()
        return len(kept or ())

    def pin_wrong_here(here: str) -> bool:
        key = access.counted_as(here)
        wrong_pins.setdefault(key, deque()).append(time.monotonic())
        while len(wrong_pins) > 1000:  # (the oldest go)
            del wrong_pins[next(iter(wrong_pins))]
        return pins_wrong_here(here) >= access.BROWSER_PIN_TRIES

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
        """Signs tapiOca's page in on a trusted network: as the person it
        signs in as, or as someone picked from its list."""
        entry = entry_of(request)
        unlocked, by_password = True, False
        if entry["gives"] == "person":
            user = person_of(entry)
        else:
            user = ctx.db.user(body.id) if body.id is not None else None
            own = browsers_own(request)
            if user is None or not (listed(user) or (own is not None and own.id == user.id)):
                raise HTTPException(404, NOT_LISTED)
            here = access.address(request.scope)
            try:
                if body.password is not None and user.has_password:
                    # (Anyone with a password may give it instead: after
                    # too many wrong PINs here, it's the only way.)
                    right = body.password and await ctx.access.check_password(
                        user.name, body.password, here, known=True
                    )
                    if not right:
                        raise devices.Refused(WRONG_PASSWORD, 401)
                    wrong_pins.pop(access.counted_as(here), None)
                    unlocked, by_password = False, True
                elif user.has_pin:
                    if pins_wrong_here(here) >= access.BROWSER_PIN_TRIES:
                        raise devices.Refused(PASSWORD_NOW)
                    try:
                        await ctx.devices.check_pin(user, body.pin or "")
                    except devices.Refused as e:
                        # (This browser's own person, not listed otherwise: wrong
                        # PINs count against the browser too, as on the page's own
                        # PIN form, so after BROWSER_PIN_TRIES only their password
                        # will do there, which can't be waited out. The audit of
                        # 1.37.0.)
                        token = request.cookies.get(access.DEVICE_COOKIE) or ""
                        theirs = own is not None and own.id == user.id and not listed(user)
                        if e.status != 429 and theirs and ctx.access.pin_wrong_on(token):
                            ctx.access.record(
                                logging.WARNING,
                                f"{access.BROWSER_PIN_TRIES} wrong PINs for {user.name} on a "
                                f"browser at {access.where(request.scope)}: it needs the "
                                "password now",
                            )
                            raise devices.Refused(PASSWORD_NOW) from None
                        if e.status != 429 and pin_wrong_here(here):
                            ctx.access.record(
                                logging.WARNING,
                                f"{access.BROWSER_PIN_TRIES} wrong PINs on a trusted network's "
                                f"Who's tuning in?, from {access.where(request.scope)}: it "
                                "needs a password there now",
                            )
                            raise devices.Refused(PASSWORD_NOW) from None
                        raise
                    unlocked = False
                elif user.role == access.ADMIN:
                    raise devices.Refused(devices.ADMIN_PASSWORD)
            except devices.Refused as e:
                raise HTTPException(e.status, str(e)) from None
            except access.Busy as e:
                raise HTTPException(429, str(e)) from None
        # (With their password: an ordinary sign-in, as by name. Otherwise
        # one that works only here, and only for watching: access.STEP_UP.)
        token = ctx.access.start_session(
            user, unlocked=unlocked, trusted="" if by_password else entry["id"]
        )
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
