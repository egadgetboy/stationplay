"""Linked devices, and the "Who's tuning in?" picker on them (see
docs/users.md).

A device is one of StationPlay's apps on a TV, phone or tablet. It's linked
once, by someone signing in on it (with their password, or a code entered on
StationPlay's page), and keeps a long-lived key, kept here only as a hash; an
Admin can unlink it on the Access tab, which signs it out at once. Whoever
is using it picks themselves from its picker, and gets a sign-in on that
device that lasts a day from when it was last used (picking again starts a
new one, and ends whoever was signed in there before).

Who's on a device's picker is each person's Show on: only devices they
sign in on (where new people start, unless an Admin chose otherwise), every
device at home (its picker is asked on the home port, which a VPN reaches
too), every device at home and away, or only devices an Admin chooses. Away
from home (the public port), a device lists only who's on every device, and
who signed in on it or was chosen for it. The picker always has Sign in, by
name: the first time on a device with an invite code (made by an Admin,
once, for 7 days) or a password, never just a PIN; after that, they're
on that device's picker. Anyone can take themselves off a device's picker.

A PIN (4 digits, kept as a hash) is asked for when someone
picks themselves, if they have one; an Admin without one gives their
password. Five wrong PINs for someone means a 15-minute wait for them,
on every device. Someone with neither a password nor a PIN (a "Kids"
user, say) can't sign in by name, so they're on every device at home or
chosen ones only (and start on every device at home): no one can get in
from anywhere by guessing a name, and no device away from home lists them
unless an Admin chose it.
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
from .text import and_list, plain

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .main import AppContext

log = logging.getLogger("stationplay.devices")

HOME, ALL, SELECTED, SIGNED_IN = "home", "all", "selected", "signed-in"
SHOW_ON = (HOME, ALL, SELECTED, SIGNED_IN)
SHOW_ON_META = "show_on_default"  # where new people are shown, if an Admin chose: HOME or SIGNED_IN
MOVED_HOME_META = "show_on_home"  # (set once everyone on ALL was moved to HOME: 1.28)
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
# Someone's own PIN, in an app: see set_own_pin.
PIN_DIGITS = "A PIN is 4 digits"
ADMIN_KEEPS_PIN = (
    "An Admin needs a PIN, or their password on a device others use too, so an Admin "
    "can't remove their PIN here. Choose a new one instead."
)
PIN_ONLY = (
    "Your PIN is how you sign in, as you don't have a password, so you can't remove it "
    "here. An Admin can, on StationPlay's Access tab."
)
NO_SECRET = (
    "You don't have a password or a PIN, so only an Admin can give you a PIN, on "
    "StationPlay's Access tab."
)
PICKED_UNLOCKED = (
    "To set a PIN, sign in on this device with your password or an invite code first."
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
    linked_by: str  # who linked it, by name (kept if they're removed)
    linked_by_id: int | None = None  # and by id, which is what says it's theirs


@dataclass
class Devices:
    db: Database
    access: Access
    # Wrong PINs lately, by person, and wrong sign-ins by name, by device: when.
    _wrong: dict[int, deque[float]] = field(default_factory=dict)
    _wrong_here: dict[int, deque[float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._move_home()

    def _move_home(self) -> None:
        """From 1.28, once: everyone shown on every device (All devices, the
        household's default until then, and everyone added before there were
        pickers) is shown on devices at home instead, and so are new people
        where that was the server's default. Said in the access log."""
        if self.db.get_meta(MOVED_HOME_META):
            return
        moved = self.db.move_show_on((ALL, ""), HOME)
        if self.db.get_meta(SHOW_ON_META) == ALL:
            self.db.set_meta(SHOW_ON_META, HOME)
        self.db.set_meta(MOVED_HOME_META, "1")
        if moved:
            self.access.record(
                logging.INFO,
                f"Who's tuning in?: {moved} {'person now shows' if moved == 1 else 'people now show'} "
                "on every device at home; away from home, a device lists only who signed in on it "
                "or was chosen for it. An Admin can choose Every device, at home and away, for "
                "anyone on the Access tab.",
            )

    # Linking ------------------------------------------------------------------

    def link(self, name: str, by: User) -> tuple[Device, str]:
        """Links a new device (`name`: which app, on what device): it and its
        key (shown once)."""
        key = secrets.token_urlsafe(KEY_BYTES)
        now = _now()
        name = plain(name)[:NAME_MOST] or "A StationPlay app"
        device_id = self.db.add_linked_device(access.session_hash(key), name, now, by.name, by.id)
        return Device(device_id, name, now, now, by.name, by.id), key

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
        return Device(
            row["id"], name or row["name"], row["created_ms"], now, row["linked_by"],
            row["linked_by_id"],
        )  # fmt: skip

    def devices(self) -> list[Device]:
        return [
            Device(r["id"], r["name"], r["created_ms"], r["seen_ms"], r["linked_by"],
                   r["linked_by_id"])
            for r in self.db.linked_devices()
        ]  # fmt: skip

    def unlink(self, device_id: int) -> str | None:
        return self.db.unlink_device(device_id)

    # Who's on a picker -----------------------------------------------------------

    @property
    def default_show_on(self) -> str:
        """Where new people are shown: as an Admin chose, or (from 1.30.1,
        if they never chose) only on devices they sign in on."""
        return HOME if self.db.get_meta(SHOW_ON_META) == HOME else SIGNED_IN

    def set_default_show_on(self, show_on: str) -> None:
        if show_on not in (HOME, SIGNED_IN):
            raise ValueError("Choose Only devices they sign in on or Every device at home")
        self.db.set_meta(SHOW_ON_META, show_on)

    def new_show_on(self, name: str, by_name: bool, show_on: str | None) -> str:
        """Where someone new is shown: `show_on` as asked, or ("default") the
        server's default. Someone who can't sign in by name (`by_name`
        False: no password, no PIN) can't be shown only where they sign in,
        so on such a server they start on Only devices you choose, with none
        chosen yet: on no device's list until an Admin chooses one, never on
        every device at home by themselves. ValueError."""
        if show_on in (None, "default"):
            show_on = self.default_show_on
            if not by_name and show_on == SIGNED_IN:
                return SELECTED
        if show_on not in SHOW_ON:
            raise ValueError("Choose where they're shown")
        if not by_name and (why := _needs_one(name, show_on)):
            raise ValueError(
                f"{why} Give them one, or choose Every device at home or Only devices you choose."
            )
        return show_on

    async def new_pin_hash(self, pin: str | None) -> str:
        """A new person's PIN, hashed ("" for none), worked out before
        they're added. ValueError."""
        if not pin:
            return ""
        if not PIN.fullmatch(pin):
            raise ValueError(PIN_DIGITS)
        return await asyncio.to_thread(hash_password, pin)

    def show_everyone_on(self, show_on: str) -> tuple[int, list[User]]:
        """Use for everyone: everyone already added is shown this way (HOME
        or SIGNED_IN), and so is anyone added from now on. How many changed,
        and who was kept as they were: anyone who can't sign in by name, either
        way (they stay where an Admin put them). ValueError."""
        self.set_default_show_on(show_on)
        changing, kept = [], []
        for user in self.db.users():
            if self.show_on(user) == show_on:
                continue
            if self.signs_in_by_name(user):
                changing.append(user.id)
            else:
                kept.append(user)
        self.db.set_show_on(changing, show_on)
        self.end_unlisted(changing)
        return len(changing), kept

    def end_unlisted(self, user_ids: list[int]) -> None:
        """Ends the sign-ins these people have on linked devices whose lists
        they're no longer on (picking yourself somewhere is only good while
        you're on its list)."""
        if not user_ids:
            return
        here = self.db.device_people()
        for user_id, device_id in self.db.picker_sessions():
            if user_id not in user_ids:
                continue
            user = self.db.user(user_id)
            if user is None or not self.on_picker(
                user, here.get(device_id, {}).get(user_id), at_home=True
            ):
                self.db.end_device_sessions(user_id, device_id)

    def show_on(self, user: User) -> str:
        """Where someone is shown (on every device at home, for someone
        added before there were pickers)."""
        return user.show_on if user.show_on in SHOW_ON else HOME

    def signs_in_by_name(self, user: User) -> bool:
        """Whether someone can sign in by name: with a password or a PIN (as
        `user` was read)."""
        return user.has_pin or user.has_password

    def on_picker(self, user: User, how: str | None, at_home: bool) -> bool:
        """Whether someone is on a device's picker, as they are on it (`how`:
        see device_people), where the device is now (`at_home`: its request
        came in on the home port)."""
        if how == REMOVED:
            return False
        if how == CHOSEN:
            return True
        if how == SIGNED_IN_HERE and self.signs_in_by_name(user):
            # (Someone who can no longer sign in by name isn't listed where
            # they once did: only at home, as their Show on says, or where
            # an Admin chose.)
            return True
        show_on = self.show_on(user)
        return show_on == ALL or (show_on == HOME and at_home)

    def people(self, device: Device, at_home: bool = True) -> list[User]:
        """Who's on a device's picker, by name: at home, or away from home
        (`at_home` False: its request came in on the public port)."""
        here = self.db.device_people().get(device.id, {})
        return [u for u in self.db.users() if self.on_picker(u, here.get(u.id), at_home)]

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
        """Signs in on a device as someone on its picker, where it is now
        (`public`: away from home): their PIN if they have one, or (an Admin
        without one, on a device others use too) their password. The person
        and the sign-in's token. Refused, or access.Busy."""
        user = self.db.user(user_id)
        here = self.db.device_people().get(device.id, {})
        if user is None or not self.on_picker(user, here.get(user.id), at_home=not public):
            raise Refused("That person isn't on this device's list", 404)
        unlocked = False
        if user.has_pin:
            await self._check_pin(user, pin or "")
        elif user.role == ADMIN and self._shared(device, user, here):
            right = password and await self.access.check_password(
                user.name, password, address, public=public, known=True
            )
            if not right:
                raise Refused(ADMIN_PASSWORD)
        else:
            # (Anyone at the device may pick them, so the sign-in says nothing
            # about who's there: see set_own_pin.)
            unlocked = True
        return user, self.access.start_session(user, device.name, device.id, unlocked)

    def _shared(self, device: Device, user: User, here: dict[int, str]) -> bool:
        """Whether a device is one others use too, for an Admin picking
        themselves on it: anyone else on its list, or who has been (someone
        who took themselves off it still has it), or someone else linked it
        (by who they are, not their name, which can change or be someone
        else's later). Only on a device of their own may an Admin without a
        PIN pick themselves without their password. (Its list is the one it
        has at home, the longer, wherever it is now.)"""
        return (
            len(self.people(device)) > 1
            or any(user_id != user.id for user_id in here)
            or device.linked_by_id != user.id
        )

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
        # Each try counts as wrong until it's found right, so many sent at
        # once can't get past the limit (as with passwords: see access.py).
        wrong.append(now)
        tries = len(wrong)
        stored = self.db.pin_hash(user.id)
        right = bool(PIN.fullmatch(pin)) and await asyncio.to_thread(password_matches, pin, stored)
        if not right:
            if tries == PIN_TRIES:
                self.access.record(
                    logging.WARNING,
                    f"Too many wrong PINs for {user.name}: they wait 15 minutes",
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

    # Someone's own PIN, in an app ------------------------------------------------------------

    def asks_for_pin(self, user: User) -> bool:
        """Whether an app asks someone who just signed in on it (with their
        password or an invite code) to choose a PIN: they have none, and
        haven't said they want none."""
        now = self.db.user(user.id) or user
        return not now.has_pin and not now.no_pin

    async def set_own_pin(self, user: User, pin: str | None, *, unlocked: bool) -> bool:
        """Someone sets their own PIN, in an app they're signed in on: 4
        digits, or None for none (any they have is removed, and they're not
        asked for one again, on any device). Whether they have one now.
        Refused.

        A sign-in made with their password, an invite code or their PIN says
        it's them, so a new PIN needs nothing more. One made by picking them
        without a PIN (`unlocked`) doesn't: anyone at that device could have,
        and could lock them out. An Admin keeps theirs (on a device others
        use too, an Admin needs a PIN or their password), and so does
        someone without a password, whose PIN is how they sign in; and
        someone with neither (whom anyone at home may pick, such as "Kids")
        gets one only from an Admin. Wrong PINs for them lately still count
        against the new one."""
        if pin is not None and not PIN.fullmatch(pin):
            raise Refused(PIN_DIGITS, 400)
        self._may_set_own_pin(user, pin, unlocked)  # (before the work of hashing it)
        hashed = await asyncio.to_thread(hash_password, pin) if pin is not None else ""
        self._may_set_own_pin(user, pin, unlocked)  # (and as things are now)
        self.db.set_pin(user.id, hashed, no_pin=pin is None)
        return pin is not None

    def _may_set_own_pin(self, user: User, pin: str | None, unlocked: bool) -> None:
        now = self.db.user(user.id) or user
        password = bool(self.db.password_hash(user.id))
        if not password and not now.has_pin:
            raise Refused(NO_SECRET)
        if unlocked:
            raise Refused(PICKED_UNLOCKED)
        if pin is None and now.role == ADMIN and now.has_pin:
            raise Refused(ADMIN_KEEPS_PIN)
        if pin is None and not password:
            raise Refused(PIN_ONLY)

    # An Admin's choices for someone ------------------------------------------------------

    async def set_pin(self, user: User, pin: str | None) -> None:
        """Sets someone's PIN (None or "": none). ValueError."""
        if pin:
            if not PIN.fullmatch(pin):
                raise ValueError(PIN_DIGITS)
            hashed = await asyncio.to_thread(hash_password, pin)
        else:
            hashed = ""
            now = self.db.user(user.id) or user
            why = _needs_one(now.name, self.show_on(now))
            if why and not self.db.password_hash(user.id):
                raise ValueError(
                    f"{why} Choose Every device at home or Only devices you choose for them first."
                )
        self.db.set_pin(user.id, hashed)
        self._wrong.pop(user.id, None)
        if not hashed:
            self.end_unlisted([user.id])

    def set_show_on(self, user: User, show_on: str, devices: list[int] | None) -> None:
        """Where someone is shown ("default": as a new person is, now), and
        (for Only devices you choose, or away from home for Every device at
        home) which devices. ValueError."""
        if show_on not in (*SHOW_ON, "default"):
            raise ValueError("Choose where they're shown")
        now = self.db.user(user.id) or user
        show_on = self.new_show_on(now.name, self.signs_in_by_name(now), show_on)
        self.db.set_show_on([user.id], show_on)
        if devices is not None:
            self.db.set_chosen_devices(user.id, devices)
        self.end_unlisted([user.id])

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


def _needs_one(name: str, show_on: str) -> str | None:
    """Why someone with neither a password nor a PIN can't be shown this
    way, if they can't: they'd sign in by name, or be on devices away from
    home that no one chose for them, for anyone there to pick."""
    if show_on == SIGNED_IN:
        return f"{name} needs a PIN or a password to sign in by name."
    if show_on == ALL:
        return f"{name} needs a PIN or a password to show on devices away from home."
    return None


def looks_like_code(text: str) -> bool:
    raw = text.replace("-", "").replace(" ", "").upper()
    return len(raw) == 8 and all(c in CODE_LETTERS for c in raw)


def _now() -> int:
    return int(time.time() * 1000)


# The Access tab's addresses (for Admins only: see access.FOR_USERS) -----------


class PickerChange(BaseModel):
    """What's given changes: a PIN ("" for none), where they're shown
    ("default": the server's default), and the devices chosen for them (for
    "selected", or away from home for "home")."""

    pin: str | None = Field(default=None, max_length=10)
    showOn: str | None = None
    devices: list[int] | None = Field(default=None, max_length=1000)


class ShowOnDefault(BaseModel):
    showOn: str = Field(max_length=20)


SHOW_ON_WORDS = {
    SIGNED_IN: "only devices they sign in on",
    HOME: "every device at home",
    ALL: "every device, at home and away",
    SELECTED: "only devices an Admin chooses",
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
        away = {dev.id: [u.name for u in d.people(dev, at_home=False)] for dev in found}
        names = {u.id: u.name for u in ctx.db.users()}  # (as they're named now)
        return {
            "default": d.default_show_on,
            "devices": [
                {
                    "id": dev.id,
                    "name": dev.name,
                    "linkedBy": names.get(dev.linked_by_id or 0, dev.linked_by),
                    "linkedMs": dev.created_ms,
                    "seenMs": dev.seen_ms,
                    "people": people[dev.id],  # (at home)
                    "peopleAway": away[dev.id],
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

    @app.post("/api/access/devices/everyone")
    async def show_everyone_on(body: ShowOnDefault, request: Request):
        try:
            changed, kept = d.show_everyone_on(body.showOn)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        said = (
            f"{who(request)} set everyone to show on {SHOW_ON_WORDS[body.showOn]}: "
            f"{changed} {'person' if changed == 1 else 'people'} changed"
        )
        if kept:
            said += (
                f", and {and_list([u.name for u in kept])} kept as they were "
                "(no password or PIN)"
            )
        ctx.access.record(logging.INFO, said)
        return {"default": d.default_show_on, "changed": changed, "kept": [u.name for u in kept]}

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
                was = d.show_on(user)
                d.set_show_on(user, body.showOn or was, body.devices)
                now = d.show_on(user_or_404(user_id))
                if now != was:
                    said.append(f"set {user.name} to show on {SHOW_ON_WORDS[now]}")
                elif body.devices is not None:
                    said.append(f"chose the devices {user.name} shows on")
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        if said:
            ctx.access.record(logging.INFO, f"{who(request)} {' and '.join(said)}")
        found = user_or_404(user_id)
        return {"pin": found.has_pin, "showOn": d.show_on(found)}

    @app.post("/api/access/users/{user_id}/invite")
    async def invite(user_id: int, request: Request):
        user = user_or_404(user_id)
        code, expires = d.make_invite(user)
        ctx.access.record(logging.INFO, f"{who(request)} made an invite code for {user.name}")
        return {"code": code, "expiresMs": expires}
