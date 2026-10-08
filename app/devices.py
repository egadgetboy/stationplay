"""Linked devices, and the "Who's tuning in?" picker on them (see
docs/users.md).

A device is one of StationPlay's apps on a TV, phone or tablet. It's linked
once, by someone signing in on it (with their password, or a code entered on
StationPlay's page), and keeps a long-lived key, kept here only as a hash; an
Admin can unlink it on the Access tab, which signs it out at once. Whoever
is using it picks themselves from its picker, and gets a sign-in on that
device that lasts a day from when it was last used (picking again starts a
new one, and ends whoever was signed in there before).

Who's on a device's picker is each person's Show on: every device (a
household), the devices an Admin chose for them, or only where they've
signed in (a larger server; the server's default for new people says which
they start with). The picker always has Sign in, by name: the first time on
a device with an invite code (made by an Admin, once, for 7 days) or a
password, never just a PIN; after that, they're on that device's picker.
Anyone can take themselves off a device's picker.

A PIN (4 digits, kept as a hash) is asked for when someone picks themselves,
if they have one; an Admin without one gives their password. Five wrong
PINs for someone means a 15-minute wait for them, on every device. Someone
with neither a password nor a PIN (a "Kids" user, say) can't sign in by
name, so they're on every device or chosen ones only: no one can get in from
anywhere by guessing a name.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import access
from .access import ADMIN, Access, hash_password, password_matches
from .db import Database, User
from .text import plain

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .main import AppContext

log = logging.getLogger("stationplay.devices")

ALL, SELECTED, SIGNED_IN = "all", "selected", "signed-in"
SHOW_ON = (ALL, SELECTED, SIGNED_IN)
SHOW_ON_META = "show_on_default"  # where new people are shown: ALL or SIGNED_IN
SIGNED_IN_HERE, CHOSEN, REMOVED = "signed-in", "chosen", "removed"
KEY_BYTES = 32
SIGN_INS_WRONG = 10  # wrong sign-ins by name on one device before it waits...
SIGN_INS_WAIT_S = 15 * 60  # ...this long
PIN = re.compile(r"[0-9]{4}")
PIN_TRIES = 5
PIN_WAIT_S = 15 * 60
INVITE_MS = 7 * 86_400_000
# Invite codes: 8 letters and digits that can't be mistaken for each other.
CODE_LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
NAME_MOST = 120
DEVICE_HEADER = "stationplay-device"
WRONG_PIN = "That PIN isn't right"
ADMIN_PASSWORD = (
    "Enter your password: on a device others use too, an Admin needs a PIN or their password"
)
# (The same whether or not there's anyone by that name: it isn't said who
# has a sign-in, or had one.)
WRONG_SIGN_IN = (
    "That name, code or password isn't right. If you should have access here, ask an Admin."
)


class Refused(Exception):
    """Not allowed, with a sentence saying why (and the HTTP status)."""

    def __init__(self, message: str, status: int = 403) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Device:
    id: int
    name: str
    created_ms: int
    seen_ms: int
    linked_by: str


@dataclass
class Devices:
    db: Database
    access: Access
    # Wrong PINs lately, by person, and wrong sign-ins by name, by device: when.
    _wrong: dict[int, deque[float]] = field(default_factory=dict)
    _wrong_here: dict[int, deque[float]] = field(default_factory=dict)

    # Linking ------------------------------------------------------------------

    def link(self, name: str, by: User) -> tuple[Device, str]:
        """Links a new device (`name`: which app, on what device): it and its
        key (shown once)."""
        key = secrets.token_urlsafe(KEY_BYTES)
        now = _now()
        name = plain(name)[:NAME_MOST] or "A StationPlay app"
        device_id = self.db.add_linked_device(access.session_hash(key), name, now, by.name)
        return Device(device_id, name, now, now, by.name), key

    def device(self, key: str | None, name: str | None = None) -> Device | None:
        """The linked device with this key (noting that it was used, and its
        name if it says a new one), or None."""
        if not key:
            return None
        row = self.db.linked_device(access.session_hash(key))
        if row is None:
            return None
        now = _now()
        name = plain(name)[:NAME_MOST] if name else None
        if now - row["seen_ms"] > access.SEEN_EVERY_MS or (name and name != row["name"]):
            self.db.device_seen(row["id"], now, name if name != row["name"] else None)
        return Device(row["id"], name or row["name"], row["created_ms"], now, row["linked_by"])

    def devices(self) -> list[Device]:
        return [
            Device(r["id"], r["name"], r["created_ms"], r["seen_ms"], r["linked_by"])
            for r in self.db.linked_devices()
        ]

    def unlink(self, device_id: int) -> str | None:
        return self.db.unlink_device(device_id)

    # Who's on a picker -----------------------------------------------------------

    @property
    def default_show_on(self) -> str:
        return SIGNED_IN if self.db.get_meta(SHOW_ON_META) == SIGNED_IN else ALL

    def set_default_show_on(self, show_on: str) -> None:
        if show_on not in (ALL, SIGNED_IN):
            raise ValueError("Choose All devices or Only where they sign in")
        self.db.set_meta(SHOW_ON_META, show_on)

    def show_on(self, user: User) -> str:
        """Where someone is shown (on every device, for someone added
        before there were pickers)."""
        return user.show_on if user.show_on in SHOW_ON else ALL

    def signs_in_by_name(self, user: User) -> bool:
        """Whether someone can sign in by name: with a password or a PIN."""
        return user.has_pin or bool(self.db.password_hash(user.id))

    def on_picker(self, device: Device, user: User, how: str | None) -> bool:
        if how == REMOVED:
            return False
        if how in (SIGNED_IN_HERE, CHOSEN):
            return True
        return self.show_on(user) == ALL

    def people(self, device: Device) -> list[User]:
        """Who's on a device's picker, by name."""
        here = self.db.device_people().get(device.id, {})
        return [u for u in self.db.users() if self.on_picker(device, u, here.get(u.id))]

    def chosen_devices(self) -> dict[int, list[int]]:
        """The devices an Admin chose for each person (Selected devices)."""
        out: dict[int, list[int]] = {}
        for device_id, people in self.db.device_people().items():
            for user_id, how in people.items():
                if how == CHOSEN:
                    out.setdefault(user_id, []).append(device_id)
        return out

    def note_signed_in(self, device: Device, user: User) -> None:
        """Someone signed in on a device: they're on its picker from now on
        (as they were, if an Admin chose it for them)."""
        how = self.db.device_people().get(device.id, {}).get(user.id)
        if how != CHOSEN:
            self.db.set_device_person(device.id, user.id, SIGNED_IN_HERE)

    def remove(self, device: Device, user: User) -> None:
        """Someone takes themselves off a device's picker."""
        self.db.set_device_person(device.id, user.id, REMOVED)

    # Picking someone ---------------------------------------------------------------

    async def choose(
        self,
        device: Device,
        user_id: int,
        pin: str | None,
        password: str | None,
        address: str = "",
        public: bool = False,
    ) -> tuple[User, str]:
        """Signs in on a device as someone on its picker: their PIN if they
        have one, or (an Admin without one, on a device others use too) their
        password. The person and the sign-in's token. Refused, or
        access.Busy."""
        user = self.db.user(user_id)
        here = self.db.device_people().get(device.id, {})
        if user is None or not self.on_picker(device, user, here.get(user.id)):
            raise Refused("That person isn't on this device's list", 404)
        if user.has_pin:
            await self._check_pin(user, pin or "")
        elif user.role == ADMIN and len(self.people(device)) > 1:
            right = password and await self.access.check_password(
                user.name, password, address, public=public, known=True
            )
            if not right:
                raise Refused(ADMIN_PASSWORD)
        return user, self.access.start_session(user, device.name, device.id)

    async def _check_pin(self, user: User, pin: str) -> None:
        wrong = self._wrong.setdefault(user.id, deque())
        now = time.monotonic()
        while wrong and now - wrong[0] > PIN_WAIT_S:
            wrong.popleft()
        if len(wrong) >= PIN_TRIES:
            minutes = max(1, round((PIN_WAIT_S - (now - wrong[0])) / 60))
            raise Refused(
                f"Too many wrong PINs for {user.name}. Try again in {minutes} minute"
                f"{'' if minutes == 1 else 's'}.",
                429,
            )
        stored = self.db.pin_hash(user.id)
        right = bool(PIN.fullmatch(pin)) and await asyncio.to_thread(password_matches, pin, stored)
        if not right:
            wrong.append(now)
            if len(wrong) >= PIN_TRIES:
                self.access.record(
                    logging.WARNING, f"Too many wrong PINs for {user.name}: they wait 15 minutes"
                )
            raise Refused(WRONG_PIN)
        wrong.clear()

    async def sign_in_by_name(
        self,
        device: Device,
        name: str,
        code: str | None,
        password: str | None,
        address: str,
        public: bool = False,
        secret: str | None = None,
    ) -> tuple[User, str]:
        """Signs in on a device by name, with an invite code or a password:
        the person (now on this device's picker) and the sign-in's token.
        Refused, or access.Busy."""
        wrong = self._wrong_here.setdefault(device.id, deque())
        now = time.monotonic()
        while wrong and now - wrong[0] > SIGN_INS_WAIT_S:
            wrong.popleft()
        if len(wrong) >= SIGN_INS_WRONG:
            raise Refused(
                "Too many wrong sign-ins on this device. Try again in a few minutes.", 429
            )
        try:
            return await self._sign_in_by_name(
                device, name, code, password, address, public, secret
            )
        except Refused as e:
            if str(e) == WRONG_SIGN_IN:
                wrong.append(now)
            raise

    async def _sign_in_by_name(
        self,
        device: Device,
        name: str,
        code: str | None,
        password: str | None,
        address: str,
        public: bool,
        secret: str | None,
    ) -> tuple[User, str]:
        found = self.db.user_named(plain(name))
        if secret is not None and not code and password is None:
            # (Typed in one box: an invite code if it is one, else a password.)
            if found and looks_like_code(secret) and self._invite_matches(found[0], secret):
                code = secret
            else:
                password = secret
        if code:
            user = found[0] if found else None
            if user is None or not self._invite_matches(user, code):
                self.access.record(
                    logging.WARNING,
                    f"Failed sign-in as {name[:40]!r} with an invite code on {device.name}",
                )
                raise Refused(WRONG_SIGN_IN)
            self.db.end_invite(user.id)  # (once)
        else:
            user = await self.access.check_password(name, password or "", address, public=public)
            if user is None:
                self.access.record(
                    logging.WARNING, f"Failed sign-in as {name[:40]!r} on {device.name}"
                )
                raise Refused(WRONG_SIGN_IN)
        if not self.signs_in_by_name(user):
            raise Refused(
                f"{user.name} can't sign in by name. If they should be on this device's list, "
                "ask an Admin.",
            )
        self.note_signed_in(device, user)
        return user, self.access.start_session(user, device.name, device.id)

    # An Admin's choices for someone ------------------------------------------------------

    async def set_pin(self, user: User, pin: str | None) -> None:
        """Sets someone's PIN (None or "": none). ValueError."""
        if pin:
            if not PIN.fullmatch(pin):
                raise ValueError("A PIN is 4 digits")
            hashed = await asyncio.to_thread(hash_password, pin)
        else:
            hashed = ""
            now = self.db.user(user.id) or user
            if self.show_on(now) == SIGNED_IN and not self.db.password_hash(user.id):
                raise ValueError(
                    f"{user.name} needs a PIN or a password to sign in by name. Choose All "
                    "devices or Selected devices for them first."
                )
        self.db.set_pin(user.id, hashed)
        self._wrong.pop(user.id, None)

    def set_show_on(self, user: User, show_on: str, devices: list[int] | None) -> None:
        """Where someone is shown ("default": the server's default for new
        people, as it is now), and (for Selected devices) which devices.
        ValueError."""
        if show_on not in (*SHOW_ON, "default"):
            raise ValueError("Choose where they're shown")
        now = self.db.user(user.id) or user
        if show_on == "default":
            show_on = self.default_show_on
        if show_on == SIGNED_IN and not self.signs_in_by_name(now):
            raise ValueError(
                f"{user.name} needs a PIN or a password to sign in by name. Give them one, or "
                "choose All devices or Selected devices."
            )
        self.db.set_show_on(user.id, show_on)
        if devices is not None:
            self.db.set_chosen_devices(user.id, devices)

    def make_invite(self, user: User) -> tuple[str, int]:
        """A new invite code for someone (any earlier one ends): the code and
        when it runs out."""
        raw = "".join(secrets.choice(CODE_LETTERS) for _ in range(8))
        expires = _now() + INVITE_MS
        self.db.set_invite(user.id, access.session_hash(raw), expires)
        return f"{raw[:4]}-{raw[4:]}", expires

    def _invite_matches(self, user: User, code: str) -> bool:
        found = self.db.invite(user.id)
        raw = code.replace("-", "").replace(" ", "").upper()
        if found is None or _now() >= found[1]:
            return False
        return secrets.compare_digest(access.session_hash(raw), found[0])


def looks_like_code(text: str) -> bool:
    raw = text.replace("-", "").replace(" ", "").upper()
    return len(raw) == 8 and all(c in CODE_LETTERS for c in raw)


def _now() -> int:
    return int(time.time() * 1000)


# The Access tab's addresses (for Admins only: see access.FOR_USERS) -----------


class PickerChange(BaseModel):
    """What's given changes: a PIN ("" for none), where they're shown
    ("default": the server's default), and the devices for "selected"."""

    pin: str | None = Field(default=None, max_length=10)
    showOn: str | None = None
    devices: list[int] | None = Field(default=None, max_length=1000)


class ShowOnDefault(BaseModel):
    showOn: str


SHOW_ON_WORDS = {
    ALL: "every device",
    SELECTED: "the devices chosen for them",
    SIGNED_IN: "only where they sign in",
    "default": "the server's default",
}


def routes(app: FastAPI, ctx: AppContext) -> None:
    d = ctx.devices

    def who(request: Request) -> str:
        user = access.signed_in(request)
        return user.name if user else "Someone"

    def user_or_404(user_id: int) -> User:
        user = ctx.db.user(user_id)
        if user is None:
            raise HTTPException(404, "That user doesn't exist")
        return user

    @app.get("/api/access/devices")
    async def linked_devices() -> dict[str, Any]:
        found = d.devices()
        people = {dev.id: [u.name for u in d.people(dev)] for dev in found}
        return {
            "default": d.default_show_on,
            "devices": [
                {
                    "id": dev.id,
                    "name": dev.name,
                    "linkedBy": dev.linked_by,
                    "linkedMs": dev.created_ms,
                    "seenMs": dev.seen_ms,
                    "people": people[dev.id],
                }
                for dev in found
            ],
            "chosen": {str(u): ids for u, ids in d.chosen_devices().items()},
        }

    @app.delete("/api/access/devices/{device_id}", status_code=204)
    async def unlink(device_id: int, request: Request):
        name = d.unlink(device_id)
        if name is None:
            raise HTTPException(404, "That device isn't linked")
        ctx.access.record(logging.INFO, f"{who(request)} unlinked {name}")

    @app.put("/api/access/devices/default")
    async def set_default(body: ShowOnDefault, request: Request):
        try:
            d.set_default_show_on(body.showOn)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        ctx.access.record(
            logging.INFO, f"{who(request)} set new people to show on {SHOW_ON_WORDS[body.showOn]}"
        )
        return {"default": d.default_show_on}

    @app.put("/api/access/users/{user_id}/picker")
    async def change_picker(user_id: int, body: PickerChange, request: Request):
        user = user_or_404(user_id)
        said = []
        try:
            if body.pin is not None:
                await d.set_pin(user, body.pin)
                said.append(f"{'set' if body.pin else 'removed'} {user.name}'s PIN")
                user = user_or_404(user_id)
            if body.showOn is not None or body.devices is not None:
                show_on = body.showOn or d.show_on(user)
                d.set_show_on(user, show_on, body.devices)
                if body.showOn is not None and body.showOn != d.show_on(user):
                    said.append(f"set {user.name} to show on {SHOW_ON_WORDS[body.showOn]}")
                elif body.devices is not None:
                    said.append(f"chose the devices {user.name} shows on")
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        if said:
            ctx.access.record(logging.INFO, f"{who(request)} {' and '.join(said)}")
        now = user_or_404(user_id)
        return {"pin": now.has_pin, "showOn": d.show_on(now)}

    @app.post("/api/access/users/{user_id}/invite")
    async def invite(user_id: int, request: Request):
        user = user_or_404(user_id)
        code, expires = d.make_invite(user)
        ctx.access.record(logging.INFO, f"{who(request)} made an invite code for {user.name}")
        return {"code": code, "expiresMs": expires}
