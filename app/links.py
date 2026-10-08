"""Signing in an app with a code, for TVs (and anything else without a
handy keyboard): no password typed on a remote, or sent by the TV.

The app asks for a code and shows it (with where to enter it: the page's
/link). Someone signed in on StationPlay's page enters the code, sees which
app on which device it is, and links it to their account. The app, which has
been checking every few seconds with a secret only it holds (`poll`), then
gets its own sign-in, as if that person had signed in on it.

Codes are 8 letters and digits (no 0, O, 1 or I), last LINK_S, work once,
and can be guessed at only from a signed-in account, WRONG_CODES times in
TRIES_WINDOW_S. Nothing about them is kept on disk.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import User

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
LINK_S = 600.0  # how long a code lasts
POLL_S = 3  # how often an app is asked to check
PENDING_MAX = 50  # codes waiting at once, at most
STARTS = 10  # codes one address may ask for in TRIES_WINDOW_S
WRONG_CODES = 10  # wrong codes one account may enter in TRIES_WINDOW_S
TRIES_WINDOW_S = 15 * 60.0


class Refused(Exception):
    """Too many codes asked for, or entered wrong: the sentence says which."""


@dataclass
class Pending:
    code: str
    poll_hash: str
    app: str  # which app, on what device, as it said
    address: str  # where it asked from
    expires: float
    user: User | None = None  # who linked it, once someone has
    token: str | None = None  # its sign-in, until it collects it
    # An app with a picker (see devices.py): the device key it already has,
    # if any, and a new one made for it when it's linked, until it collects it.
    picker: bool = False
    device_key: str | None = None
    new_key: str | None = None


@dataclass
class Links:
    _pending: dict[str, Pending] = field(default_factory=dict)  # by code
    _starts: dict[str, deque[float]] = field(default_factory=dict)  # by address
    _wrong: dict[int, deque[float]] = field(default_factory=dict)  # by user id

    def start(
        self, app: str, address: str, picker: bool = False, device_key: str | None = None
    ) -> tuple[str, str]:
        """A new code for an app (one with a picker, and the device key it
        has: see devices.py), and the secret it checks back with."""
        now = time.monotonic()
        self._forget_old(now)
        starts = _recent(self._starts.setdefault(address, deque()), now)
        if len(starts) >= STARTS or len(self._pending) >= PENDING_MAX:
            raise Refused("Too many codes have been asked for. Try again in a few minutes.")
        starts.append(now)
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        while code in self._pending:
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        poll = secrets.token_urlsafe(32)
        self._pending[code] = Pending(
            code, _hash(poll), app, address, now + LINK_S, picker=picker, device_key=device_key
        )
        return show(code), poll

    def find(self, typed: str, user: User) -> Pending:
        """The app waiting with a code someone typed in. Refused after too
        many wrong ones from their account; LookupError if it's wrong."""
        now = time.monotonic()
        self._forget_old(now)
        wrong = _recent(self._wrong.setdefault(user.id, deque()), now)
        if len(wrong) >= WRONG_CODES:
            raise Refused("Too many wrong codes. Try again in a few minutes.")
        found = self._pending.get(_plain(typed))
        if found is None or found.user is not None:
            wrong.append(now)
            raise LookupError("That code isn't right, or it has run out. Check the code on the TV.")
        return found

    def link(self, pending: Pending, user: User, token: str, new_key: str | None = None) -> None:
        """Gives a waiting app its sign-in, as `user` (and a new device
        key, for an app with a picker that didn't have one)."""
        pending.user, pending.token, pending.new_key = user, token, new_key

    def check(self, poll: str) -> Pending | None:
        """The link an app is waiting on (by its secret), while it lasts. Its
        sign-in, once linked, is handed over once: then the link is gone."""
        self._forget_old(time.monotonic())
        wanted = _hash(poll)
        for code, pending in self._pending.items():
            if hmac.compare_digest(pending.poll_hash, wanted):
                if pending.token is not None:
                    del self._pending[code]
                return pending
        return None

    def _forget_old(self, now: float) -> None:
        for code in [c for c, p in self._pending.items() if p.expires <= now]:
            del self._pending[code]
        for address in [a for a, d in self._starts.items() if not _recent(d, now)]:
            del self._starts[address]
        for user_id in [u for u, d in self._wrong.items() if not _recent(d, now)]:
            del self._wrong[user_id]


def show(code: str) -> str:
    """A code as it's shown: "K7QM-4DPX"."""
    half = CODE_LENGTH // 2
    return f"{code[:half]}-{code[half:]}"


def _plain(typed: str) -> str:
    return "".join(c for c in typed.upper() if c.isalnum())[: CODE_LENGTH + 2]


def _hash(poll: str) -> str:
    return hashlib.sha256(poll.encode()).hexdigest()


def _recent(tries: deque[float], now: float) -> deque[float]:
    while tries and now - tries[0] > TRIES_WINDOW_S:
        tries.popleft()
    return tries
