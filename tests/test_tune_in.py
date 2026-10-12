"""Tuning in from the beginning (a station's tune_in "start"): how far back
the stream goes, and when it doesn't. (Played for real, with ffmpeg, in
test_e2e_tune_in.py.)"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import broadcaster as bc
from app import updates
from app.broadcaster import Broadcaster
from app.db import Item
from app.schedule import Slot

MIN = 60_000
NOW = 1_800_000_000_000


def station_airing(start_ms: int, program_ms: int, breaks_ms: int = 0):
    item = Item(0, 0, program_ms + breaks_ms, "1", "episode", "Pilot", "Cheers", "s1", 1, 1)
    if breaks_ms:
        item.breaks = [("@id", breaks_ms)]
    slot = Slot(item, 0, 0, start_ms, start_ms + program_ms + breaks_ms)
    return SimpleNamespace(locate=lambda at: slot)


def tuned_in(intro_seconds: int = 0) -> tuple[Broadcaster, SimpleNamespace]:
    b = Broadcaster(ctx=SimpleNamespace(), channel_id=1)
    b._session_start = NOW
    channel = SimpleNamespace(
        number=5, intro_video="", intro_seconds=intro_seconds, has_intro=intro_seconds > 0
    )
    return b, channel


@pytest.mark.parametrize("intro_s", [0, 10])
async def test_it_goes_back_to_the_programs_beginning_less_the_bumper(intro_s):
    b, channel = tuned_in(intro_s)
    await b._back_to_start(channel, station_airing(NOW - 20 * MIN, 30 * MIN))
    assert b._cursor(bc.TS_BASE_S) == NOW - 20 * MIN - intro_s * 1000
    assert b.behind_ms == 20 * MIN + intro_s * 1000
    assert b._start_at == NOW - 20 * MIN


async def test_not_in_the_break_after_a_program():
    b, channel = tuned_in(5)
    # 30 minutes of program, then a minute of break: tuned in 30.5 minutes in.
    await b._back_to_start(channel, station_airing(NOW - 30 * MIN - 30_000, 30 * MIN, MIN))
    assert (b._cursor(bc.TS_BASE_S), b.behind_ms, b._start_at) == (NOW, 0, None)


async def test_not_for_a_program_that_began_long_ago():
    b, channel = tuned_in(5)
    await b._back_to_start(channel, station_airing(NOW - 150 * MIN, 240 * MIN))
    assert (b._cursor(bc.TS_BASE_S), b.behind_ms, b._start_at) == (NOW, 0, None)
    # (Its schedule that far back, and Plex's guide, are always kept.)
    assert bc.MOST_BEHIND_MS <= updates.GUIDE_PAST_MS < updates.KEEP_PAST_MS
