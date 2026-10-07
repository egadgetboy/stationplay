"""How much StationPlay's apps take on at once, so the server stays steady:
the limits an Admin sets (devices watching at once, and of those, how many
away from home), the connection tests the apps run, and what StationPlay
recommends from those tests.

Each device watching through StationPlay's apps (or another player using
the HLS addresses) gets its own copy of the station's stream: at home over
the home network, and away from home over the home internet connection's
upload. However many watch, a station still takes just one tuner (see
playback.py, whose speed test covers the CPU or GPU), so these limits are
about the network. Plex, Jellyfin and IPTV apps aren't counted here: they
have limits of their own, and the tuners cover them.

The server can't measure its own internet upload without a speed-test
service somewhere else, and StationPlay depends on no outside service. So
the apps measure it, the way viewers use it: an app times data sent to it
by StationPlay (GET /api/v1/speed-test) and says what it found. From away
from home, that's the upload as a viewer away from home gets it.

A device already watching may always change station (it's still one
device); the limits only turn away one more. 0 is no limit.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from . import ffmpeg as ff

if TYPE_CHECKING:
    from .config import Settings
    from .db import Channel, Database

log = logging.getLogger(__name__)

META_LIMITS = "app_limits"  # {"devices": n, "away": n}
META_TESTS = "connection_tests"  # the latest connection tests, newest first
MOST = 200  # the largest either limit can be
TESTS_KEPT = 12
TEST_DAYS = 60  # older tests aren't recommended from
# Of what a connection test found, how much the stations' streams should
# use (the rest: everything else on the connection, and its ups and downs).
HEADROOM = 0.7
# HLS and MPEG-TS on top of the stations' picture and sound.
OVERHEAD = 1.08
# The test's data: random, so no proxy along the way can shrink it.
TEST_BLOCK = os.urandom(1 << 20)
TEST_MB = 20  # sent, unless the app asks for another amount
TEST_MB_MOST = 64
TEST_EVERY_S = 10.0  # one test from one address at a time, at most this often
FASTEST_MBPS = 100_000.0  # (a result above this isn't believed)
WHERE = ("home", "away")


@dataclass
class Limits:
    devices: int = 0  # devices watching at once (0: no limit)
    away: int = 0  # of those, away from home


@dataclass
class ConnectionTest:
    """A connection test an app ran: how fast StationPlay's data reached it."""

    where: str  # "home" or "away"
    mbps: float
    at_ms: int
    device: str  # the app and device, as it named them
    user: str  # who was signed in ("" with signing in off)

    def as_dict(self) -> dict:
        return {"where": self.where, "mbps": self.mbps, "at": self.at_ms, "device": self.device,
                "user": self.user}  # fmt: skip


def stream_mbps(settings: Settings, channels: list[Channel]) -> tuple[float, str]:
    """How much one device watching takes (Mbps), at the biggest picture size
    the stations use; and that size."""
    pictures = {c.picture for c in channels if c.picture in ff.PICTURES} or {ff.STANDARD_PICTURE}
    biggest = max(pictures, key=lambda p: ff.sized(settings, p).video_bitrate_kbps)
    sized = ff.sized(settings, biggest)
    return round(
        (sized.video_bitrate_kbps + settings.audio_bitrate_kbps) * OVERHEAD / 1000, 1
    ), biggest


def room(test: ConnectionTest, mbps_each: float) -> int:
    """How many devices a connection as fast as `test`'s has room for."""
    return max(0, math.floor(test.mbps * HEADROOM / mbps_each))


def devices(n: int) -> str:
    return f"{n} device" if n == 1 else f"{n} devices"


def refused_because(limit: str, most: int) -> str:
    """What someone over a limit is told."""
    where = " away from home" if limit == "away" else ""
    return (
        f"An Admin has limited StationPlay to {devices(most)} watching{where} at once, "
        "so it runs smoothly for everyone. Please try again later."
    )


class Capacity:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.limits = self._load_limits()
        self._tests = self._load_tests()
        self._tested_at: dict[str, float] = {}  # (by address)

    def _load_limits(self) -> Limits:
        try:
            got = json.loads(self.db.get_meta(META_LIMITS, "{}") or "{}")
            return Limits(
                max(0, min(MOST, int(got.get("devices", 0)))),
                max(0, min(MOST, int(got.get("away", 0)))),
            )
        except (ValueError, TypeError, AttributeError):
            return Limits()

    def _load_tests(self) -> list[ConnectionTest]:
        try:
            got = json.loads(self.db.get_meta(META_TESTS, "[]") or "[]")
            return [ConnectionTest(**t) for t in got][:TESTS_KEPT]
        except (ValueError, TypeError):
            return []

    def save(self, devices_: int, away: int) -> Limits:
        if not (0 <= devices_ <= MOST and 0 <= away <= MOST):
            raise ValueError(f"Each limit must be between 0 (no limit) and {MOST}")
        if devices_ and away > devices_:
            raise ValueError("The limit away from home can't be higher than the overall limit")
        self.limits = Limits(devices_, away)
        self.db.set_meta(META_LIMITS, json.dumps(asdict(self.limits)))
        return self.limits

    def refusal(self, watching: dict[str, bool], client: str, away: bool) -> tuple[str, int] | None:
        """Whether `client` may start watching, given who's watching now
        (each device, and whether it's away from home): None if it may;
        otherwise the limit it would go over ("devices" or "away") and that
        limit."""
        if client in watching:
            return None  # (already watching: changing station)
        if self.limits.devices and len(watching) >= self.limits.devices:
            return "devices", self.limits.devices
        if away and self.limits.away and sum(watching.values()) >= self.limits.away:
            return "away", self.limits.away
        return None

    # Connection tests ----------------------------------------------------------

    def may_test(self, address: str, now: float | None = None) -> bool:
        """Whether a test may start from `address` (and if so, it's started)."""
        now = time.monotonic() if now is None else now
        for known, at in list(self._tested_at.items()):
            if now - at >= TEST_EVERY_S:
                del self._tested_at[known]
        if address in self._tested_at:
            return False
        self._tested_at[address] = now
        return True

    def record(
        self, where: str, mbps: float, device: str, user: str, now_ms: int
    ) -> ConnectionTest:
        if where not in WHERE:
            raise ValueError(f"where must be one of {', '.join(WHERE)}")
        if not 0 < mbps <= FASTEST_MBPS:
            raise ValueError("That isn't a speed StationPlay can accept")
        test = ConnectionTest(where, round(mbps, 1), now_ms, device, user)
        self._tests = [test, *self._tests][:TESTS_KEPT]
        self.db.set_meta(META_TESTS, json.dumps([asdict(t) for t in self._tests]))
        log.info(
            "Connection test from %s%s, %s: %.1f Mbps",
            device or "an app",
            f" ({user})" if user else "",
            "away from home" if where == "away" else "at home",
            test.mbps,
        )
        return test

    def tests(self) -> list[ConnectionTest]:
        return list(self._tests)

    def best(self, where: str, now_ms: int) -> ConnectionTest | None:
        """The fastest recent test from there: what the connection can do,
        rather than one that ran while something else was using it."""
        recent = [
            t
            for t in self._tests
            if t.where == where and now_ms - t.at_ms <= TEST_DAYS * 86_400_000
        ]
        return max(recent, key=lambda t: t.mbps, default=None)
