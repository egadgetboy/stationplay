"""Watching away from home in StationPlay's own apps: optional, off unless
an Admin turns it on in the Access tab. Setups that use only Plex, Jellyfin
or other IPTV apps never see a difference.

What Plex and IPTV apps use stays on the home network (see access.py). An
app away from home reaches StationPlay one of two ways:

- Through a VPN (Tailscale, WireGuard), straight to the home port: as far as
  StationPlay can tell, it's at home, and everything works as it does there.
- Through the public port (PUBLIC_PORT, behind a reverse proxy), signed in.
  A player can't sign in, so there a station's stream has an address of its
  own for each signed-in app: /hls/k/<key>/<number>/... The key belongs to
  that app's sign-in. It stops working when the sign-in does (signing out, a
  new password, the user being removed), when this is turned off, and when
  StationPlay restarts (the app then asks for the stations again and gets a
  new one). Nothing about it is kept on disk.

The address set here (what the apps reach StationPlay at from outside) is
told to the apps (/api/v1/server), so an app set up at home remembers it and
uses it when home doesn't answer. Whether it really reaches StationPlay is
checked while this is on (see reach.py).

Media plays through the public port too, while this is on (see
applibrary.py), as fast as the Admin allows: Original (the file as it would
play at home), or up to a number of Mbps (MEDIA_MBPS_MOST at most), above
which a program is converted down to fit.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from .playing import station

if TYPE_CHECKING:
    from .access import Access
    from .db import Database, User

log = logging.getLogger(__name__)

META = "away"
KEY_BYTES = 24
# How long a key's sign-in is taken as still good, for the stream's pieces
# (the playlist, asked for every couple of seconds, checks every time).
RECHECK_S = 60.0
KEYS_KEPT = 1000  # app sign-ins with a key at once, at most (the oldest go)
SEEN_KEPT = 1000  # (who's watching what, for the access log)
SEEN_AGAIN_S = 3600.0  # a viewing is logged again after this long
ADDRESS_MAX = 200
MEDIA_MBPS_MOST = 200  # the highest the Admin's cap on Media away from home can be


def client(key: str) -> str:
    """Which app it is, away from home, among the devices watching (see
    capacity.py): by its key, not its address, so apps behind one reverse
    proxy are told apart; and the same for its stations and its Media. It's
    never shown."""
    return f"away {key}"


@dataclass
class _Key:
    session: str  # the sign-in's token hash
    user: User
    checked: float  # when the sign-in was last found good


def normalize_address(text: str) -> str:
    """The address the apps reach StationPlay at from outside, as typed:
    "https://tv.example.com", "http://nas.tailnet.ts.net:3310". ValueError
    if it isn't one."""
    text = text.strip()
    problem = (
        "Enter the whole address, starting with https:// or http:// (such as "
        "https://tv.example.com)"
    )
    if not text or len(text) > ADDRESS_MAX or any(c.isspace() for c in text):
        raise ValueError(problem)
    parts = urlsplit(text)
    try:
        port = parts.port
    except ValueError:
        raise ValueError(problem) from None
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise ValueError(problem)
    host = parts.hostname if ":" not in parts.hostname else f"[{parts.hostname}]"
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


def _a_cap(mbps: int) -> bool:
    return 1 <= mbps <= MEDIA_MBPS_MOST


def check_cap(mbps: int | None) -> None:
    """ValueError unless `mbps` is a cap Media away from home can have (None:
    Original)."""
    if mbps is not None and not _a_cap(mbps):
        raise ValueError(
            f"For Media away from home, choose Original, or up to 1 to {MEDIA_MBPS_MOST} Mbps"
        )


def port_problem(address: str, port: int, public_port: int) -> str:
    """What's wrong with an https:// address on one of StationPlay's own
    ports ("" if nothing is): StationPlay never speaks HTTPS itself, so that
    can't reach it through a reverse proxy. It's saved all the same, and the
    page says so."""
    parts = urlsplit(address)
    if parts.scheme != "https" or not parts.hostname:
        return ""
    try:
        given = parts.port
    except ValueError:
        return ""
    if given is None or given not in {port, public_port} - {0}:
        return ""
    host = parts.hostname if ":" not in parts.hostname else f"[{parts.hostname}]"
    return (
        f"Leave the port out: StationPlay never speaks HTTPS itself, so an https:// address "
        f"with port {given} can't reach it. Use your reverse proxy's address alone, "
        f"https://{host}."
    )


class Away:
    """Whether apps may watch away from home, where they reach StationPlay
    then, and the keys of the apps' streams."""

    def __init__(self, db: Database, access: Access) -> None:
        self.db = db
        self.access = access
        self.on = False
        self.address = ""
        self.media_mbps: int | None = None  # the cap on Media away from home (None: Original)
        self._keys: dict[str, _Key] = {}  # key -> whose
        self._by_session: dict[str, str] = {}  # sign-in's token hash -> key
        self._seen: dict[tuple[str, int], float] = {}  # (key, station) -> when logged
        self._load()

    def _load(self) -> None:
        try:
            got = json.loads(self.db.get_meta(META) or "{}")
        except ValueError:
            got = {}
        if not isinstance(got, dict):
            got = {}
        self.on = got.get("on") is True
        try:
            self.address = normalize_address(str(got.get("address") or ""))
        except ValueError:
            self.address = ""
        if not self.address:
            self.on = False
        cap = got.get("mediaMbps")
        self.media_mbps = (
            cap if isinstance(cap, int) and not isinstance(cap, bool) and _a_cap(cap) else None
        )

    def save(self, on: bool, address: str) -> None:
        """Turns it on or off, with the address apps use from outside.
        ValueError if that won't do."""
        address = normalize_address(address) if address.strip() or on else ""
        self.on, self.address = on, address
        self._keep()
        if not on:
            self._keys.clear()
            self._by_session.clear()

    def save_media(self, mbps: int | None) -> None:
        """How fast Media away from home may play: up to `mbps` (None:
        Original, as at home). ValueError if that won't do."""
        check_cap(mbps)
        self.media_mbps = mbps
        self._keep()

    @property
    def media_kbps(self) -> int | None:
        """The cap on Media away from home, in kilobits a second (None:
        Original)."""
        return self.media_mbps * 1000 if self.media_mbps else None

    def _keep(self) -> None:
        self.db.set_meta(
            META,
            json.dumps({"on": self.on, "address": self.address, "mediaMbps": self.media_mbps}),
        )

    @property
    def apps(self) -> int:
        """How many app sign-ins have a key now."""
        return len(self._keys)

    def key_for(self, session: str, user: User) -> str | None:
        """The key of a signed-in app's streams (`session`: its sign-in's
        token hash), made the first time it's asked for; None while this is
        off."""
        if not self.on:
            return None
        key = self._by_session.get(session)
        if key is not None and key in self._keys:
            return key
        while len(self._keys) >= KEYS_KEPT:
            oldest = next(iter(self._keys))
            self._by_session.pop(self._keys.pop(oldest).session, None)
        key = secrets.token_urlsafe(KEY_BYTES)
        self._keys[key] = _Key(session, user, time.monotonic())
        self._by_session[session] = key
        return key

    def user_of(self, key: str, *, recheck: bool) -> User | None:
        """Whose a key is, while it's good; None if it isn't (anymore).
        `recheck`: ask whether its sign-in is still good now, rather than
        within RECHECK_S."""
        if not self.on:
            return None
        found = self._keys.get(key)
        if found is None:
            return None
        now = time.monotonic()
        if recheck or now - found.checked > RECHECK_S:
            user = self.access.session_user_hashed(found.session)
            if user is None:
                self.forget(key)
                return None
            found.user, found.checked = user, now
        return found.user

    def forget(self, key: str) -> None:
        found = self._keys.pop(key, None)
        if found is not None:
            self._by_session.pop(found.session, None)

    def watching(self, key: str, user: User, number: int, where: str, name: str = "") -> None:
        """Logs (once an hour) that someone's watching a station (`name`: its
        name) away from home, in the access log."""
        now = time.monotonic()
        last = self._seen.get((key, number))
        if last is not None and now - last < SEEN_AGAIN_S:
            return
        if len(self._seen) >= SEEN_KEPT:
            self._seen = {k: t for k, t in self._seen.items() if now - t < SEEN_AGAIN_S}
            while len(self._seen) >= SEEN_KEPT:
                del self._seen[next(iter(self._seen))]
        self._seen[(key, number)] = now
        self.access.record(
            logging.INFO,
            f"{user.name} is watching {station(number, name, mid=True)} away from home, "
            f"from {where}",
        )
