"""Signing in to StationPlay's page, which is optional.

A new StationPlay is open: anyone who can reach its page can use it. Adding
the first user in the Access tab turns signing in on, and that first user is
always an Admin. There are two roles:

  Admin  Everything: every station, Add to Plex (and backups), Broken files,
         Logs, Stats, and Access (who can sign in).
  User   Stations: watching their guides, making new ones (as many as an
         Admin lets them: 3 to start with), and changing or deleting only the
         stations they made. Adding logos (their own, or from Plex) and Intro
         Bumper videos (Admins delete them). Stats.

What Plex and IPTV apps use (the tuner, its guide and streams, pictures for
the guide) stays open on the network, as they can't sign in.

Passwords are kept as scrypt hashes, and a browser is signed in by a random
token in a cookie that's kept only as a hash. StationPlay's apps sign in the
same way and send their token in a header instead (Authorization: Bearer;
see appapi.py). Signing in is logged (who and from where) in the access log,
which the Logs tab shows.

Scripts and other apps use StationPlay's API (/api/v1, see api.py) with an
API token an Admin makes on the Access tab: a Viewer token reads; an Admin
token does what an Admin may there too. A token works only under /api/v1,
and from the internet only once an Admin allows that. It's kept as a hash,
shown once, and can be revoked; removing the Admin who made it removes it.

Locked out? Create an empty file called reset-access in the data folder and
restart StationPlay: every user is removed, and it's open again.

Whether a request may go ahead is decided as it arrives, and again once its
body has (which may take a while), so a request can't start while it's
allowed and finish after it no longer is. Changes coming from another site's
page (a browser says which site a request is from) are refused, signed in or
not.

From the internet (through a Cloudflare Tunnel, or another reverse proxy),
StationPlay is reached on its public port (PUBLIC_PORT), never the one Plex
uses. There, what Plex and IPTV apps use isn't offered at all, signing in is
always needed (until there's a user, nothing but the sign-in page is shown:
the first user is added on the home network), each visitor's address is the
one the tunnel passes on (CF-Connecting-IP), and wrong passwords from the
internet as a whole are limited too (but not on a browser you've signed in
on before, so strangers' wrong passwords can't keep you out).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .db import Channel, Database, User
from .text import plain

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from pathlib import Path

log = logging.getLogger("stationplay.access")

ADMIN, USER = "admin", "user"
ROLES = (ADMIN, USER)
COOKIE = "stationplay_session"
SESSION_DAYS = 30
# A browser someone has signed in on is remembered (DEVICE_COOKIE): from it,
# signing in from the internet never waits for PUBLIC_TRIES, so strangers'
# wrong passwords can't keep you out.
DEVICE_COOKIE = "stationplay_device"
DEVICE_DAYS = 400
DEVICES_KEPT = 20
SESSIONS_KEPT = 20  # browsers signed in as one user at once, at most (the newest)
SEEN_EVERY_MS = 5 * 60_000  # how often a session's "last seen" is saved
PICKED_MS = 24 * 3600_000  # a sign-in from a linked device's picker lasts this long unused
PASSWORD_MIN, PASSWORD_MAX = 8, 200
NAME = re.compile(r"[\w .@-]{1,40}")
RESET_FILE = "reset-access"
LOG_KEEP = 2000
# How many stations a User may make (counting those of theirs still there):
# one of these, or None for any number.
STATION_LIMITS = (0, 1, 3, 5, 10, 25)  # (0: they only watch)
NEW_USER_STATIONS = 3
# Wrong passwords from one address, at most, in a while, before it has to wait.
TRIES = 5
TRIES_WINDOW_S = 15 * 60
ADDRESSES_KEPT = 10_000  # the most addresses whose wrong passwords are counted
# Wrong passwords on the public port, from every address together, before
# signing in from the internet waits (the home network doesn't).
PUBLIC_TRIES = 100
# Passwords checked at once, at most: each check takes a moment and memory,
# deliberately, and StationPlay has streams to serve.
CHECKS_AT_ONCE = 2
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# The most a request may send, but for uploads (which have limits of their own).
BODY_MAX = 4 * 1024 * 1024
UPLOADS = frozenset({"/api/logos", "/api/bumpers", "/api/restore"})
# Sent with every answer but what's open to Plex on the home network
# (streams, and pictures): no other site may show StationPlay's page in a
# frame, guess a file's type, or learn its addresses.
SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"same-origin"),
)
# scrypt: about 16 MB and a few tens of milliseconds a check.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
ADMINS_ONLY = "Only an Admin can do that"
NOT_HTTPS = (
    "From outside your home, StationPlay's apps connect only over HTTPS. Use an https:// "
    "address, through a reverse proxy with HTTPS (see StationPlay's README)."
)
NOT_SET_UP = (
    "Signing in to StationPlay isn't set up yet. Add the first user from your home network."
)

# API tokens (see the module's notes, and api.py): "spk_" and 43 random
# characters; what each may do (its scope).
API_TOKEN_PREFIX = "spk_"
VIEWER = "viewer"
SCOPES = (VIEWER, ADMIN)
API_TOKENS_MOST = 100
API_TOKEN_NAME_MAX = 60
API_OUTSIDE_META = "api_outside"  # whether tokens are taken from the internet
BAD_TOKEN = "That API token isn't valid. It may have expired or been revoked."
TOKEN_API_ONLY = "API tokens work only with StationPlay's API, under /api/v1"
TOKEN_NOT_OUTSIDE = (
    "API tokens aren't accepted from the internet. An Admin can allow them on the Access tab."
)
TOKEN_READS_ONLY = "This API token can only read (its scope is Viewer)"

# What Plex and IPTV apps use: the tuner, its guide, streams and pictures for
# the guide (and the stations as HLS, for StationPlay's apps). Open on the
# home network (they can't sign in); never offered on the public port.
FOR_PLEX = frozenset({
    "/discover.json", "/lineup_status.json", "/lineup.json", "/lineup.post", "/device.xml",
    "/xmltv.xml", "/guide.xml", "/stations.m3u", "/channels.m3u",
})  # fmt: skip
FOR_PLEX_UNDER = ("/stream/", "/auto/", "/art/", "/hls/")
# Stations as HLS for StationPlay's apps away from home, when that's on: on
# the public port too, each signed-in app's at an address of its own, which
# is what lets it in (a player can't sign in; see away.py).
AWAY_UNDER = "/hls/k/"
# Open to anyone, signed in or not: the page itself (it asks you to sign
# in), and signing in.
# (And what StationPlay's apps ask first: see appapi.py.)
PAGE = frozenset({"/", "/link", "/apple-touch-icon.png", "/api/access/me", "/api/v1/server"})
# Where StationPlay checks that its apps can reach it from outside (see
# reach.py): open on both ports, to anyone, before there's a user, and over
# plain HTTP too. It says nothing unless it's asked with the value a check
# is waiting for.
REACH = "/api/internal/reach"
OPEN = (
    PAGE
    | {REACH}
    | {"/api/access/sign-in", "/api/access/sign-out"}
    | {"/api/internal/sign-in", "/api/internal/link", "/api/internal/link/check"}
    # (A linked device's picker: its key, not a sign-in, says who may ask.)
    | {"/api/internal/picker", "/api/internal/picker/choose", "/api/internal/picker/sign-in"}
    | FOR_PLEX
)
# Programs played on demand in StationPlay's apps: each at an address of its
# own, which is what lets a player in (see ondemand.py). On the home network
# only, for now.
PLAY_UNDER = "/play/"
# What StationPlay's apps use, and the API: from the internet, only over
# HTTPS (passwords, sign-ins, tokens and stream addresses must never cross it
# in the clear).
API_UNDER = "/api/v1/"
INTERNAL_UNDER = "/api/internal/"
FOR_APPS_UNDER = (API_UNDER, INTERNAL_UNDER, "/hls/k/", PLAY_UNDER)
# Also open on the home network: the stations' logos (Plex shows them).
OPEN_UNDER = (*FOR_PLEX_UNDER, "/channel-icon/", "/logos/")
# What a User may do; everything else is for Admins. (A path ending in "/"
# covers what's under it. Which stations a User may change is up to the
# station: see may_change.)
FOR_USERS = {
    "GET": (
        "/api/channels", "/api/channels/", "/api/bumpers", "/api/logos", "/api/collections",
        "/api/filter/", "/api/libraries", "/api/libraries/", "/api/stats", "/api/status",
        "/poster/", "/logos/", "/bumpers/", "/plex-logo/", "/api/v1/stations", "/api/v1/guide",
        "/api/v1/status", "/api/access/link/", "/api/internal/speed-test",
        "/api/internal/libraries", "/api/internal/libraries/", "/api/internal/home",
        "/api/internal/search", "/api/internal/items/", "/api/internal/art/",
    ),
    "POST": (
        "/api/access/me/password", "/api/channels", "/api/channels/", "/api/collections/stations",
        "/api/filter/preview", "/api/intro/preview", "/api/upnext/preview", "/api/logos",
        "/api/logos/plex", "/api/bumpers", "/api/smart/split", "/api/smart/stations",
        "/api/internal/sign-out", "/api/internal/speed-test", "/api/access/link",
        "/api/internal/play", "/api/internal/progress", "/api/internal/report",
        "/api/internal/problem", "/api/internal/picker/remove",
    ),
    "PUT": ("/api/channels/",),
    "DELETE": ("/api/channels/",),
}  # fmt: skip
# What a User on a limited Viewing Level may do (see viewing.py): watch what
# they can see, in StationPlay's apps and on its page, and look after their
# own sign-in. Nothing that shows the libraries as a whole, or makes or
# changes stations.
FOR_WATCHERS = {
    "GET": (
        "/api/channels", "/api/channels/", "/api/logos", "/api/status", "/logos/",
        "/api/v1/stations", "/api/v1/guide", "/api/v1/status", "/api/access/link/",
        "/api/internal/speed-test", "/api/internal/libraries", "/api/internal/libraries/",
        "/api/internal/home", "/api/internal/search", "/api/internal/items/",
        "/api/internal/art/",
    ),
    "POST": (
        "/api/access/me/password", "/api/internal/sign-out", "/api/internal/speed-test",
        "/api/access/link", "/api/internal/play", "/api/internal/progress",
        "/api/internal/report", "/api/internal/problem", "/api/internal/picker/remove",
    ),
}  # fmt: skip
WATCHES_ONLY = "Your Viewing Level lets you watch, but not make or change stations"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${_b64(salt)}${_b64(digest)}"


def password_matches(password: str, stored: str) -> bool:
    try:
        kind, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        made = hashlib.scrypt(password.encode(), salt=_unb64(salt), **_SCRYPT)
    except ValueError:
        return False
    return hmac.compare_digest(made, _unb64(digest))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode(), validate=True)


# (What's checked when there's no user by the name given: see check_password.)
_DUMMY_HASH = hash_password(secrets.token_urlsafe(12))


def session_hash(token: str) -> str:
    """What a session's token is kept as."""
    return _token_hash(token)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def role_name(role: str) -> str:
    return "Admin" if role == ADMIN else "User"


def a_role(role: str) -> str:
    """The role with its article: "an Admin" or "a User"."""
    return "an Admin" if role == ADMIN else "a User"


def address(scope: dict) -> str:
    """The address a request came from: on the home network, the address
    it came from (a reverse proxy's, if it came through one), as that can't
    be faked; on the public port, the visitor's, as the tunnel says."""
    if outside(scope):
        for name, value in scope.get("headers") or ():
            if name == b"cf-connecting-ip":
                with contextlib.suppress(ValueError):
                    return str(ipaddress.ip_address(value.decode("latin-1").strip()))
    client = scope.get("client")
    return client[0] if client else "unknown"


def outside(scope: dict) -> bool:
    """Whether a request came in on the public port (see Gate)."""
    return bool(scope.get("state", {}).get("outside"))


def counted_as(address_: str) -> str:
    """What wrong passwords are counted by: the address, or for IPv6 its /64
    network (one device can use any number of addresses in it)."""
    try:
        ip = ipaddress.ip_address(address_)
    except ValueError:
        return address_
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network(f"{ip}/64", strict=False))
    return str(ip)


def where(scope: dict) -> str:
    """Where a request came from, for the access log: its address, and the
    address it says it came from first when it came through a proxy (as a
    reverse proxy says; anyone could say so, so it's only for reading)."""
    address_ = address(scope)
    if outside(scope):
        return f"{address_} (over the internet)"
    for name, value in scope.get("headers") or ():
        if name == b"x-forwarded-for":
            first = value.decode("latin-1").split(",")[0].strip()[:60]
            if first and first != address_:
                return f"{first} (via {address_})"
    return address_


class Busy(Exception):
    """A password that wasn't checked: too many wrong ones from there lately,
    or too many being checked at once."""


class NotAllowed(Exception):
    """Something only an Admin may do."""


class NoRoom(Exception):
    """Another station a User may not make: they've made as many as they may."""


@dataclass
class Access:
    """Who can sign in, and who's signed in."""

    db: Database
    _users_exist: bool = field(init=False, default=False)
    # Recent tries by address (see counted_as): when, and the name tried;
    # and from the internet, all together.
    _tries: dict[str, deque[tuple[float, str]]] = field(init=False, default_factory=dict)
    _public_tries: deque[tuple[float, str]] = field(init=False, default_factory=deque)
    _checking: int = field(init=False, default=0)
    _watches_only: Callable[[User], bool] | None = field(init=False, default=None)
    # Someone's PIN and where they're shown on the apps' pickers (devices.py,
    # which sets this).
    picker: Any = field(init=False, default=None)
    # When a signed-in app last came in through the public port over HTTPS
    # (time.monotonic(); None: not since StationPlay started), as proof that
    # apps reach StationPlay from outside (see reach.py). In memory only.
    app_outside_at: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._users_exist = self.db.has_users()

    def judge_watching_by(self, watches_only: Callable[[User], bool]) -> None:
        """How to tell whether a User only watches (see watches_only)."""
        self._watches_only = watches_only

    def watches_only(self, user: User) -> bool:
        """Whether a User only watches: they're on a limited Viewing Level
        (see viewing.py)."""
        return user.role != ADMIN and bool(self._watches_only and self._watches_only(user))

    @property
    def required(self) -> bool:
        """Whether signing in is on (there are users)."""
        return self._users_exist

    def reset_if_asked(self, data_dir: Path) -> None:
        """Turns signing in off if the reset-access file is there (and
        removes the file), for when you're locked out."""
        flag = data_dir / RESET_FILE
        if not flag.exists():
            return
        self.db.delete_all_users()
        self._users_exist = False
        flag.unlink(missing_ok=True)
        self.record(
            logging.WARNING,
            "The reset-access file turned off sign-in and removed every user. "
            "Add a user in the Access tab to turn sign-in back on.",
        )

    def app_came_from_outside(self) -> None:
        """A signed-in app came in through the public port, over HTTPS."""
        self.app_outside_at = time.monotonic()

    def record(self, level: int, message: str) -> None:
        """Logs a sign-in or a change to who can sign in, and keeps it."""
        log.log(level, message)
        self.db.add_access_entry(
            int(time.time() * 1000), logging.getLevelName(level), message, LOG_KEEP
        )

    # Users ------------------------------------------------------------------
    # Passwords are hashed off the event loop, and only then is it checked who
    # may make the change and is it made, with nothing waited for in between:
    # so it's decided on how things are as it's made.

    async def add_user(
        self,
        name: str,
        password: str,
        role: str,
        by: User | None,
        max_stations: int | None = NEW_USER_STATIONS,
    ) -> User:
        """Adds a user, if `by` may (anyone while signing in is off; then an
        Admin). The first user is always an Admin. A User may have no password
        (""): they use only the apps' pickers (see devices.py). ValueError if
        the name, password or station limit won't do; NotAllowed."""
        name = plain(name)
        _check_name(name)
        if role not in ROLES:
            raise ValueError("The role must be Admin or User")
        if password or role == ADMIN or not self._users_exist:
            if not password:
                raise ValueError("An Admin needs a password")
            _check_password(password)
        _check_limit(max_stations)
        hashed = await asyncio.to_thread(hash_password, password) if password else ""
        if self._users_exist and not self.is_admin(by):
            raise NotAllowed
        if not self._users_exist:
            role = ADMIN
        try:
            user = self.db.add_user(name, hashed, role, _now(), max_stations)
        except sqlite3.IntegrityError:
            raise ValueError(f"There's already a user called {name}") from None
        self._users_exist = True
        return user

    def sees_everything(self, user: User | None) -> bool:
        """Whether someone may see how StationPlay is set up: an Admin, or
        anyone while signing in is off."""
        return not self.required or (user is not None and user.role == ADMIN)

    def is_admin(self, user: User | None) -> bool:
        """Whether someone is an Admin now (their role may have changed since
        their request came in)."""
        now = self.db.user(user.id) if user else None
        return now is not None and now.role == ADMIN

    def set_max_stations(self, user: User, by: User | None, limit: int | None) -> None:
        """Sets how many stations a User may make (None: any number), if `by`
        is an Admin. ValueError; NotAllowed."""
        _check_limit(limit)
        if not self.is_admin(by):
            raise NotAllowed
        self.db.set_max_stations(user.id, limit)

    def check_room(self, user: User | None) -> None:
        """Raises NoRoom if someone may not make another station: a User who
        has made as many as they may. (Anyone may while signing in is off.)"""
        if user is None:
            return
        now = self.db.user(user.id)
        if now is None:
            raise NoRoom("Your account was removed, so you can't make stations")
        if now.role == ADMIN:
            return
        if self.watches_only(now):
            raise NoRoom(WATCHES_ONLY)
        if now.max_stations is None:
            return
        if now.max_stations == 0:
            raise NoRoom("You can watch stations, but an Admin hasn't let you make any")
        made = self.db.stations_made().get(now.id, 0)
        if made >= now.max_stations:
            raise NoRoom(
                f"Your limit is {_stations(now.max_stations)}, and you've made {made}. "
                "Delete one of yours, or ask an Admin to raise your limit."
            )

    def remove_user(self, user: User) -> None:
        """Removes a user; ValueError if they're the last Admin and others
        remain (removing the very last user turns signing in off)."""
        others = [u for u in self.db.users() if u.id != user.id]
        if user.role == ADMIN and others and self._last_admin(user):
            raise ValueError(
                "StationPlay needs at least one Admin. Make someone else an Admin first."
            )
        self.db.delete_user(user.id)
        self._users_exist = bool(others)

    async def change_user(
        self, user: User, by: User | None, *, password: str | None, role: str | None
    ) -> None:
        """Changes a user's password or role, if `by` may: an Admin, or (their
        password only) the user themselves. ValueError; NotAllowed."""
        if password is not None:
            _check_password(password)
        if role is not None and role not in ROLES:
            raise ValueError("The role must be Admin or User")
        hashed = await asyncio.to_thread(hash_password, password) if password is not None else None
        themselves = by is not None and by.id == user.id and role is None
        if not (themselves or self.is_admin(by)):
            raise NotAllowed
        current = self.db.user(user.id)
        if current is None:
            raise ValueError("That user has been removed")
        if role == ADMIN and password is None and not current.has_password:
            raise ValueError(f"Give {current.name} a password before making them an Admin")
        if current.role == ADMIN and role not in (None, ADMIN) and self._last_admin(current):
            raise ValueError(
                "StationPlay needs at least one Admin. Make someone else an Admin first."
            )
        self.db.update_user(user.id, password_hash=hashed, role=role)

    def _last_admin(self, user: User) -> bool:
        return not any(u.role == ADMIN and u.id != user.id for u in self.db.users())

    # Signing in ---------------------------------------------------------------

    async def check_password(
        self, name: str, password: str, address_: str, *, public: bool = False, known: bool = False
    ) -> User | None:
        """The user, if that's their password. Busy, without checking, after
        TRIES wrong ones from that address within TRIES_WINDOW_S (or, from
        the internet, PUBLIC_TRIES from anywhere, unless it's a browser
        they've signed in on before: `known`), or while CHECKS_AT_ONCE are
        being checked.

        Each try counts as wrong until it's found right (so many sent at once
        can't get past the limit), and a right one clears only the wrong ones
        for that name: signing in as yourself doesn't make more guesses at
        someone else's password possible."""
        name = plain(name)
        tries = self._recent_tries(counted_as(address_))
        everyone = _recent(self._public_tries) if public else None
        if len(tries) >= TRIES:
            raise Busy("Too many wrong passwords. Try again in a few minutes.")
        if everyone is not None and len(everyone) >= PUBLIC_TRIES and not known:
            raise Busy(
                "Too many wrong passwords from the internet recently. Try again in a few minutes."
            )
        if self._checking >= CHECKS_AT_ONCE:
            raise Busy("StationPlay is busy checking other sign-ins. Try again in a moment.")
        this = (time.monotonic(), name.casefold())
        tries.append(this)
        if everyone is not None:
            everyone.append(this)
        self._checking += 1
        try:
            found = self.db.user_named(name)
            # An unknown name takes the same work as a known one, so how long
            # it takes doesn't tell anyone whether there's a user by that name.
            # (Someone without a password, who signs in only from a picker,
            # takes the same work, and is never signed in this way.)
            stored = found[1] if found and found[1] else _DUMMY_HASH
            right = await asyncio.to_thread(password_matches, password, stored)
            right = right and bool(found and found[1])
        finally:
            self._checking -= 1
        if not (found and right):
            return None
        for t in [t for t in tries if t[1] == this[1]]:
            tries.remove(t)
        if everyone is not None:
            everyone.remove(this)
        return found[0]

    def _recent_tries(self, key: str) -> deque[tuple[float, str]]:
        tries = self._tries.get(key)
        if tries is None:
            if len(self._tries) >= ADDRESSES_KEPT:
                self._forget_tries(time.monotonic())
            tries = self._tries[key] = deque()
        return _recent(tries)

    def _forget_tries(self, now: float) -> None:
        """Makes room: forgets addresses with no recent tries, then the
        earliest counted."""
        for key in [k for k, t in self._tries.items() if not t or now - t[-1][0] > TRIES_WINDOW_S]:
            del self._tries[key]
        while len(self._tries) >= ADDRESSES_KEPT:
            del self._tries[next(iter(self._tries))]

    def start_session(self, user: User, app: str = "", device_id: int | None = None) -> str:
        """A new token for a browser (or `app`, one of StationPlay's: which,
        on what device; `device_id`: a linked device, from its picker: see
        devices.py) that's signed in as `user`."""
        token = secrets.token_urlsafe(32)
        self.db.add_session(_token_hash(token), user.id, _now(), SESSIONS_KEPT, app, device_id)
        return token

    def remember_device(self, user: User) -> str:
        """A new token for a browser `user` has signed in on."""
        token = secrets.token_urlsafe(32)
        self.db.add_device(_token_hash(token), user.id, _now(), DEVICES_KEPT)
        return token

    def known_device(self, token: str | None, name: str) -> bool:
        """Whether a browser is one the user called `name` has signed in on."""
        if not token:
            return False
        found = self.db.user_named(plain(name))
        return found is not None and self.db.device_user(_token_hash(token)) == found[0].id

    def end_session(self, token: str) -> None:
        self.db.end_session(_token_hash(token))

    def session_user(self, token: str) -> User | None:
        """Who a browser is signed in as, if anyone (signed in within the
        last SESSION_DAYS)."""
        return self.session_user_hashed(session_hash(token))

    def session_user_hashed(self, hashed: str) -> User | None:
        """session_user, for a session known by its token's hash (an API
        token's too)."""
        now = _now()
        found = self.db.session_user(hashed, now - SESSION_DAYS * 86_400_000)
        if found is None:
            token = self._api_token_hashed(hashed)
            return token.as_user() if token else None
        user, seen_ms, device_id = found
        if device_id is not None and now - seen_ms > PICKED_MS:
            return None  # (a sign-in from a device's picker lasts a day unused)
        if now - seen_ms > SEEN_EVERY_MS:
            self.db.seen(hashed, now)
        return user

    def forget_old_sessions(self) -> None:
        self.db.forget_sessions_before(_now() - SESSION_DAYS * 86_400_000)

    # API tokens --------------------------------------------------------------

    def make_api_token(
        self, name: str, scope: str, by: User, days: int | None
    ) -> tuple[ApiToken, str]:
        """A new API token, made by the Admin `by`: the token (shown this
        once) and what it is. ValueError if that won't do."""
        name = plain(name).strip()
        if not name or len(name) > API_TOKEN_NAME_MAX:
            raise ValueError(f"Give the token a name, up to {API_TOKEN_NAME_MAX} characters")
        if scope not in SCOPES:
            raise ValueError("Choose Viewer or Admin")
        if days is not None and not 1 <= days <= 3650:
            raise ValueError("A token can last from 1 day to 10 years, or never expire")
        if len(self.db.api_tokens()) >= API_TOKENS_MOST:
            raise ValueError(f"StationPlay keeps at most {API_TOKENS_MOST} API tokens")
        token = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
        now = _now()
        expires = now + days * 86_400_000 if days else None
        token_id = self.db.add_api_token(_token_hash(token), name, scope, by.id, now, expires)
        made = ApiToken(token_id, name, scope, by, now, 0, expires)
        what = "Admin" if scope == ADMIN else "Viewer"
        self.record(logging.INFO, f"{by.name} made the API token \u201c{name}\u201d ({what})")
        return made, token

    def api_tokens(self) -> list[ApiToken]:
        return [_api_token(row, owner) for row, owner in self.db.api_tokens()]

    def revoke_api_token(self, token_id: int, by: User | None) -> bool:
        found = next((t for t in self.api_tokens() if t.id == token_id), None)
        if found is None or not self.db.delete_api_token(token_id):
            return False
        who = by.name if by else "Someone"
        self.record(logging.INFO, f"{who} revoked the API token \u201c{found.name}\u201d")
        return True

    def api_token(self, token: str) -> ApiToken | None:
        """The API token a request was made with, while it's good."""
        if not token.startswith(API_TOKEN_PREFIX):
            return None
        return self._api_token_hashed(_token_hash(token))

    def _api_token_hashed(self, hashed: str) -> ApiToken | None:
        found = self.db.api_token(hashed)
        if found is None:
            return None
        token = _api_token(*found)
        now = _now()
        if token.expires_ms is not None and now >= token.expires_ms:
            return None
        if now - token.used_ms > SEEN_EVERY_MS:
            self.db.api_token_used(token.id, now)
        return token

    @property
    def api_outside(self) -> bool:
        """Whether API tokens are taken from the internet (the public port)."""
        return self.db.get_meta(API_OUTSIDE_META) == "1"

    def set_api_outside(self, on: bool, by: User | None) -> None:
        if on == self.api_outside:
            return
        self.db.set_meta(API_OUTSIDE_META, "1" if on else "0")
        who = by.name if by else "Someone"
        self.record(
            logging.WARNING if on else logging.INFO,
            f"{who} {'allowed' if on else 'stopped'} API tokens from the internet",
        )


def _api_token(row: dict, owner: User) -> ApiToken:
    return ApiToken(
        row["id"], row["name"], row["scope"], owner, row["created_ms"], row["used_ms"],
        row["expires_ms"],
    )  # fmt: skip


def _recent(tries: deque[tuple[float, str]]) -> deque[tuple[float, str]]:
    """`tries`, without those older than TRIES_WINDOW_S."""
    now = time.monotonic()
    while tries and now - tries[0][0] > TRIES_WINDOW_S:
        tries.popleft()
    return tries


def _check_limit(max_stations: int | None) -> None:
    if max_stations is not None and max_stations not in STATION_LIMITS:
        choices = ", ".join(map(str, STATION_LIMITS))
        raise ValueError(f"A User's station limit must be {choices}, or no limit")


def _check_name(name: str) -> None:
    if not NAME.fullmatch(name):
        raise ValueError(
            "A name can have up to 40 characters: letters, numbers, spaces, and . _ - @"
        )


def _check_password(password: str) -> None:
    if len(password) < PASSWORD_MIN:
        raise ValueError(f"A password needs at least {PASSWORD_MIN} characters")
    if len(password) > PASSWORD_MAX:
        raise ValueError("That password is too long")


def _now() -> int:
    return int(time.time() * 1000)


# Who may do what ---------------------------------------------------------------


@dataclass(frozen=True)
class ApiToken:
    """An API token (never the token itself: that's shown once, when it's made)."""

    id: int
    name: str
    scope: str  # VIEWER or ADMIN
    owner: User  # the Admin who made it
    created_ms: int
    used_ms: int  # when it was last used; 0 if never
    expires_ms: int | None  # None: never

    @property
    def admin(self) -> bool:
        """Whether it may do what an Admin may: an Admin token, while the
        Admin who made it still is one (it never does more than they may)."""
        return self.scope == ADMIN and self.owner.role == ADMIN

    def as_user(self) -> User:
        """Who a request made with it is, for what it may do and the log:
        an Admin for an Admin token (see admin), a User otherwise."""
        return User(
            id=self.owner.id,
            name=f"API token \u201c{self.name}\u201d",
            role=ADMIN if self.admin else USER,
            created_ms=self.created_ms,
            signed_in_ms=self.used_ms,
            max_stations=0,
        )


def may_change(user: User | None, channel: Channel) -> bool:
    """Whether someone may change or delete a station: anyone while signing
    in is off, an Admin, or the User who made it."""
    return user is None or user.role == ADMIN or channel.created_by == user.id


def signed_in(request: Request) -> User | None:
    """Who made a request (None while signing in is off)."""
    return getattr(request.state, "user", None)


def _for_users(path: str, method: str, paths: dict[str, tuple[str, ...]] = FOR_USERS) -> bool:
    allowed = paths.get("GET" if method == "HEAD" else method, ())
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in allowed)


class Gate:
    """Lets a request through only if whoever made it may (see the module's
    notes): a plain ASGI layer, so streams pass through it untouched.
    `public_port`: the port the internet reaches StationPlay on (0: none)."""

    def __init__(self, app: Callable, access: Access, public_port: int = 0) -> None:
        self.app = app
        self.access = access
        self.public_port = public_port

    async def __call__(
        self, scope: dict, receive: Callable[[], Awaitable[Any]], send: Callable
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        server = scope.get("server")
        public = bool(self.public_port and server and server[1] == self.public_port)
        scope.setdefault("state", {})["outside"] = public
        if not public and path.startswith(OPEN_UNDER):
            await self.app(scope, receive, send)  # (streams, and pictures for Plex)
            return
        send = _with_security_headers(send)
        if (
            public
            and (path in FOR_PLEX or path.startswith((*FOR_PLEX_UNDER, PLAY_UNDER)))
            and not path.startswith(AWAY_UNDER)
        ):
            await _refuse(send, 404, "Not Found")
        elif public and path.startswith(FOR_APPS_UNDER) and path != REACH and not over_https(scope):
            await _refuse(send, 403, NOT_HTTPS)
        elif scope["method"] not in SAFE_METHODS and _from_another_site(scope):
            await _refuse(send, 403, "StationPlay can only be changed from its own page")
        elif path not in UPLOADS and _length(scope) > BODY_MAX:
            await _refuse(send, 413, "That request is too big for StationPlay")
        elif refused := self._decide(scope):
            await _refuse(send, *refused)
        elif scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
        else:
            await self._deciding_again(scope, receive, send)

    def _decide(self, scope: dict) -> tuple[int, str] | None:
        """Why a request is refused (a status and a reason), if it is; and who
        made it, for the request's handler (signed_in)."""
        state = scope["state"]
        state["user"] = None
        path = scope["path"]
        if not self.access.required:
            if state["outside"] and path not in PAGE and path != REACH:
                return 403, NOT_SET_UP
            return None
        if path.startswith((AWAY_UNDER, PLAY_UNDER)):
            return None  # (its address says whose it is)
        app_token = bearer(scope)
        token = app_token or _cookie(scope, COOKIE)
        if token and token.startswith(API_TOKEN_PREFIX):
            refused = self._api_token(scope, token)
            return None if path in OPEN else refused
        user = state["user"] = self.access.session_user(token) if token else None
        if user is not None and app_token and state["outside"] and over_https(scope):
            self.access.app_came_from_outside()
        if path in OPEN:
            return None
        if user is None:
            return 401, "Sign in to StationPlay"
        if user.role != ADMIN and not _for_users(path, scope["method"]):
            return 403, ADMINS_ONLY
        if (
            user.role != ADMIN
            and self.access.watches_only(user)
            and not _for_users(path, scope["method"], FOR_WATCHERS)
        ):
            return 403, WATCHES_ONLY
        return None

    def _api_token(self, scope: dict, token: str) -> tuple[int, str] | None:
        """_decide, for a request made with an API token."""
        state = scope["state"]
        found = self.access.api_token(token)
        if found is None:
            return 401, BAD_TOKEN
        if not scope["path"].startswith(API_UNDER):
            return 403, TOKEN_API_ONLY
        if state["outside"] and not self.access.api_outside:
            return 403, TOKEN_NOT_OUTSIDE
        state["user"] = user = found.as_user()
        state["api_token"] = found
        if found.scope != ADMIN and scope["method"] not in SAFE_METHODS:
            return 403, TOKEN_READS_ONLY
        if user.role != ADMIN and not _for_users(scope["path"], scope["method"]):
            return 403, ADMINS_ONLY
        return None

    async def _deciding_again(
        self, scope: dict, receive: Callable[[], Awaitable[Any]], send: Callable
    ) -> None:
        """Passes a request on, deciding again once its body has arrived:
        if it's refused then, the handler is told the browser went away
        (before it has done anything), and the refusal is sent instead."""
        refused: tuple[int, str] | None = None
        received = 0
        limited = scope["path"] not in UPLOADS

        async def receive_decided() -> Any:
            nonlocal refused, received
            message = await receive()
            if message["type"] != "http.request":
                return message
            received += len(message.get("body", b""))
            if limited and received > BODY_MAX:
                refused = 413, "That request is too big for StationPlay"
            elif not message.get("more_body"):
                refused = self._decide(scope)
            return {"type": "http.disconnect"} if refused else message

        async def send_unless_refused(message: dict) -> None:
            if refused is None:
                await send(message)

        try:
            await self.app(scope, receive_decided, send_unless_refused)
        except Exception:
            if refused is None:
                raise
        if refused is not None:
            await _refuse(send, *refused)


def _with_security_headers(send: Callable) -> Callable:
    async def sending(message: dict) -> None:
        if message["type"] == "http.response.start":
            have = {name for name, _ in message.get("headers") or ()}
            extra = [(name, value) for name, value in SECURITY_HEADERS if name not in have]
            message = {**message, "headers": [*(message.get("headers") or ()), *extra]}
        await send(message)

    return sending


def _length(scope: dict) -> int:
    """The body's length, as the request says (0 if it doesn't)."""
    for name, value in scope.get("headers") or ():
        if name == b"content-length":
            with contextlib.suppress(ValueError):
                return int(value)
    return 0


def over_https(scope: dict) -> bool:
    """Whether a request came over HTTPS: itself, or to the reverse proxy or
    Cloudflare in front of StationPlay, as it says (X-Forwarded-Proto,
    CF-Visitor)."""
    if scope.get("scheme") == "https":
        return True
    for name, value in scope.get("headers") or ():
        if name == b"x-forwarded-proto" and value.split(b",")[0].strip() == b"https":
            return True
        if name == b"cf-visitor" and b'"https"' in value:
            return True
    return False


def _from_another_site(scope: dict) -> bool:
    """Whether a browser says another site's page made the request (another
    web site, or another app on the same NAS)."""
    for name, value in scope.get("headers") or ():
        if name == b"sec-fetch-site":
            return value not in (b"same-origin", b"none")
    return False


def bearer(scope: dict) -> str | None:
    """The token an app signed in with sends (Authorization: Bearer), if
    any: where a browser sends its cookie."""
    for header, value in scope.get("headers") or ():
        if header == b"authorization":
            scheme, _, token = value.decode("latin-1").strip().partition(" ")
            if scheme.casefold() == "bearer" and token.strip():
                return token.strip()
    return None


def _cookie(scope: dict, name: str) -> str | None:
    for header, value in scope.get("headers") or ():
        if header != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            key, _, val = part.strip().partition("=")
            if key == name and val:
                return val
    return None


async def _refuse(send: Callable, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start", "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store")],
    })  # fmt: skip
    await send({"type": "http.response.body", "body": body})


# The Access tab's API -------------------------------------------------------------


class SignIn(BaseModel):
    name: str = Field(max_length=100)
    password: str = Field(max_length=PASSWORD_MAX)


class NewUser(BaseModel):
    name: str = Field(max_length=100)
    password: str = Field(default="", max_length=PASSWORD_MAX)  # ("": a User with none)
    role: str = USER
    maxStations: int | None = NEW_USER_STATIONS  # (null: no limit)
    # On the apps' pickers (see devices.py): a PIN, and where they're shown
    # ("default": the server's default), and the devices for "selected".
    pin: str | None = Field(default=None, max_length=10)
    showOn: str = "default"
    devices: list[int] | None = Field(default=None, max_length=1000)


class UserChange(BaseModel):
    """What's given changes (maxStations null: no limit)."""

    password: str | None = Field(default=None, max_length=PASSWORD_MAX)
    role: str | None = None
    maxStations: int | None = None


class PasswordChange(BaseModel):
    current: str = Field(max_length=PASSWORD_MAX)
    password: str = Field(max_length=PASSWORD_MAX)


def _user_json(user: User, made: dict[int, int]) -> dict:
    """A user, for the page; `made`: how many stations each user has made."""
    return {
        "id": user.id, "name": user.name, "role": user.role, "signedInMs": user.signed_in_ms,
        "maxStations": user.max_stations, "stationsMade": made.get(user.id, 0),
        "hasPassword": user.has_password, "pin": user.has_pin, "showOn": user.show_on or "all",
    }  # fmt: skip


@contextlib.contextmanager
def _refusing() -> Iterator[None]:
    """Turns a change that won't do (ValueError) or isn't someone's to make
    (NotAllowed) into the answer the page shows."""
    try:
        yield
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except NotAllowed:
        raise HTTPException(403, ADMINS_ONLY) from None


def _stations(n: int) -> str:
    return f"{n} station{'' if n == 1 else 's'}"


def _stations_text(limit: int | None) -> str:
    if limit == 0:
        return "no stations: they only watch"
    return "any number of stations" if limit is None else f"up to {_stations(limit)}"


def _set_cookie(
    response: Response, request: Request, token: str, name: str = COOKIE, days: int = SESSION_DAYS
) -> None:
    """Sets a cookie only StationPlay's page can see (not its script), sent
    only over https when the page is reached that way: as a reverse proxy
    or Cloudflare (CF-Visitor) says."""
    secure = over_https(request.scope)
    response.set_cookie(
        name, token, max_age=days * 86_400, httponly=True, samesite="lax", secure=secure, path="/"
    )


def routes(app: FastAPI, access: Access) -> None:
    """The Access tab's API, and signing in and out."""

    def user_or_404(user_id: int) -> User:
        user = access.db.user(user_id)
        if user is None:
            raise HTTPException(404, "That user doesn't exist")
        return user

    async def password_or_refuse(
        name: str, password: str, request: Request, known: bool = False
    ) -> User | None:
        try:
            return await access.check_password(
                name, password, address(request.scope), public=outside(request.scope), known=known
            )
        except Busy as e:
            raise HTTPException(429, str(e)) from None

    @app.get("/api/access/me")
    async def me(request: Request, response: Response):
        user = signed_in(request)
        token = request.cookies.get(COOKIE)
        if user and token:
            # (The page asks every few seconds: a sign-in lasts SESSION_DAYS
            # from when it was last used.)
            _set_cookie(response, request, token)
        if outside(request.scope) and not access.required:
            # From the internet, it's never open: until there's a user,
            # there's only this to say.
            return {"required": True, "user": None, "notSetUp": NOT_SET_UP}
        return {
            "required": access.required,
            "user": _user_json(user, access.db.stations_made()) if user else None,
        }

    @app.post("/api/access/sign-in")
    async def sign_in(body: SignIn, request: Request, response: Response):
        known = access.known_device(request.cookies.get(DEVICE_COOKIE), body.name)
        user = await password_or_refuse(body.name, body.password, request, known)
        if user is None:
            access.record(
                logging.WARNING,
                f"Failed sign-in as {body.name[:40]!r} from {where(request.scope)}",
            )
            raise HTTPException(401, "That name or password isn't right")
        _set_cookie(response, request, access.start_session(user))
        if not known:
            token = access.remember_device(user)
            _set_cookie(response, request, token, DEVICE_COOKIE, DEVICE_DAYS)
        access.record(
            logging.INFO,
            f"{user.name} ({role_name(user.role)}) signed in from {where(request.scope)}",
        )
        return {"user": _user_json(user, access.db.stations_made())}

    @app.post("/api/access/sign-out")
    async def sign_out(request: Request, response: Response):
        token = request.cookies.get(COOKIE)
        user = signed_in(request)
        if token:
            access.end_session(token)
        response.delete_cookie(COOKIE, path="/")
        if user:
            access.record(logging.INFO, f"{user.name} signed out from {where(request.scope)}")
        return {"ok": True}

    @app.post("/api/access/me/password")
    async def change_my_password(body: PasswordChange, request: Request, response: Response):
        user = signed_in(request)
        if user is None:
            raise HTTPException(400, "Sign-in is off, so there's no password to change")
        if await password_or_refuse(user.name, body.current, request, known=True) is None:
            raise HTTPException(400, "Your current password isn't right")
        with _refusing():
            await access.change_user(user, user, password=body.password, role=None)
        # (Every other browser is signed out; this one carries on.)
        _set_cookie(response, request, access.start_session(user))
        access.record(logging.INFO, f"{user.name} changed their password")
        return {"ok": True}

    @app.get("/api/access/users")
    async def list_users():
        made = access.db.stations_made()
        return [_user_json(u, made) for u in access.db.users()]

    @app.post("/api/access/users", status_code=201)
    async def add_user(body: NewUser, request: Request, response: Response):
        by = signed_in(request)
        with _refusing():
            user = await access.add_user(body.name, body.password, body.role, by, body.maxStations)
            if access.picker is not None:
                try:
                    if body.pin:
                        await access.picker.set_pin(user, body.pin)
                    access.picker.set_show_on(user, body.showOn, body.devices)
                except ValueError:
                    access.remove_user(user)  # (all or nothing)
                    raise
            user = access.db.user(user.id) or user
        if by is None:
            # The first user (signing in was off): whoever turned signing in
            # on is signed in as its first Admin.
            _set_cookie(response, request, access.start_session(user))
            access.record(
                logging.WARNING,
                f"Sign-in was turned on, with {user.name} as the first Admin "
                f"(from {where(request.scope)})",
            )
        else:
            access.record(
                logging.INFO,
                f"{by.name} added {user.name} as {a_role(user.role)}"
                + ("" if user.role == ADMIN else f" ({_stations_text(user.max_stations)})"),
            )
        return _user_json(user, access.db.stations_made())

    @app.put("/api/access/users/{user_id}")
    async def change_user(user_id: int, body: UserChange, request: Request, response: Response):
        user = user_or_404(user_id)
        by = signed_in(request)
        limit_given = "maxStations" in body.model_fields_set
        with _refusing():
            if limit_given:
                _check_limit(body.maxStations)  # (before anything changes)
            await access.change_user(user, by, password=body.password, role=body.role)
            if limit_given:
                access.set_max_stations(user, by, body.maxStations)
        if by is not None and by.id == user.id and body.password is not None:
            # A new password signs them out everywhere: but not here.
            _set_cookie(response, request, access.start_session(user))
        what = []
        if body.role is not None and body.role != user.role:
            what.append(f"made {user.name} {a_role(body.role)}")
        if body.password is not None:
            what.append(f"changed {user.name}'s password")
        if limit_given and body.maxStations != user.max_stations:
            what.append(f"let {user.name} make {_stations_text(body.maxStations)}")
        if what:
            access.record(logging.INFO, f"{by.name if by else 'Someone'} {' and '.join(what)}")
        return _user_json(user_or_404(user_id), access.db.stations_made())

    @app.delete("/api/access/users/{user_id}", status_code=204)
    async def remove_user(user_id: int, request: Request, response: Response):
        user = user_or_404(user_id)
        with _refusing():
            access.remove_user(user)
        by = signed_in(request)
        if not access.required:
            response.delete_cookie(COOKIE, path="/")
            access.record(
                logging.WARNING,
                f"Sign-in was turned off because {by.name if by else 'someone'} "
                "removed the last user",
            )
        else:
            access.record(logging.INFO, f"{by.name if by else 'Someone'} removed {user.name}")
