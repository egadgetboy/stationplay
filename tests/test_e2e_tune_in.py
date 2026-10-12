"""End to end: tuning in from the beginning (a station's tune_in "start"),
with real ffmpeg and the test episodes of test_e2e_skipping (solid-colour
stretches, so what aired can be read back frame by frame).

Episode 1: a cold open (yellow 6s), the intro (skipped), the program (cyan
10s), the credits (skipped). Episode 2: straight into the intro (skipped),
then the program (orange 10s). Every episode's sound is a 440 Hz tone.
"""

from __future__ import annotations

import asyncio
import shutil
import time

import httpx
import pytest

from .test_e2e import assert_clean_stream, record, start_server
from .test_e2e_skipping import assert_runs, episodes, runs  # noqa: F401 (a fixture)
from .test_intro import band_level

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


async def make_station(base: str, **settings) -> dict:
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        made = await client.post(
            "/api/channels",
            json={
                "number": 9,
                "orderMode": "rotate",
                "skipIntros": True,
                "tuneIn": "start",
                "sources": [{"type": "show", "ratingKey": "100"}],
                **settings,
            },
        )
        assert made.status_code == 201, made.text
        return made.json()


async def wait_till(at_ms: float) -> None:
    await asyncio.sleep(max(0.0, at_ms / 1000 - time.time()))


async def test_it_starts_from_the_beginning_and_runs_behind(tmp_path, episodes):  # noqa: F811
    base, app, _settings, srv, task = await start_server(tmp_path, episodes)
    try:
        station = await make_station(base, introSeconds=0)
        assert station["tuneIn"] == "start"
        began = station["now"]["start"]
        await wait_till(began + 9000)
        tuned = time.time() * 1000
        data = await record(f"{base}/stream/9", 20)
        behind = app.state.ctx.broadcasters[station["id"]].behind_ms
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "start.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    # Nine seconds into episode 1, it starts from its cold open: all of it.
    got = runs(out)
    assert_runs(got, [("yellow", 6), ("cyan", 10)], first_tol=0.4)
    assert got[2][0] == "orange"  # (then episode 2)
    assert abs(behind - (tuned - began)) < 1500, behind


async def test_the_bumper_ends_as_the_program_begins(tmp_path, episodes):  # noqa: F811
    """A silent bumper: before a cold open, nothing of the program comes in
    under it (there's nothing before it to borrow); the program then starts
    on its first frame."""
    base, _app, _settings, srv, task = await start_server(tmp_path, episodes)
    try:
        station = await make_station(base, introSeconds=3, introSound=False)
        await wait_till(station["now"]["start"] + 9000)
        data = await record(f"{base}/stream/9", 14)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "bumper.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    got = runs(out)
    first = next(n for n, (c, _) in enumerate(got) if c == "yellow")
    assert sum(s for _, s in got[:first]) == pytest.approx(3, abs=0.4)  # the bumper
    assert_runs(got[first:], [("yellow", 6)], first_tol=0.3)
    assert got[first + 1][0] == "cyan"
    assert band_level(out, 2.1, 2.8, 440) < -60  # silent to the end


async def test_no_fade_from_the_beginning_even_after_a_skipped_intro(
    tmp_path,
    episodes,  # noqa: F811
):
    """Episode 2 starts with its intro (skipped): the bumper keeps its own
    sound (here, silence) to the end, and the program starts on its first
    frame, its sound with it."""
    base, app, _settings, srv, task = await start_server(tmp_path, episodes)
    try:
        station = await make_station(base, introSeconds=3, introSound=False)
        schedule = app.state.ctx.station(station["id"])
        second = schedule.locate(station["now"]["start"] + 17_000)
        assert second.item.title == "Episode 2"
        await wait_till(second.start_ms + 3000)
        data = await record(f"{base}/stream/9", 14)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "skipped.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    got = runs(out)
    first_orange = next(n for n, (c, _) in enumerate(got) if c == "orange")
    assert sum(s for _, s in got[:first_orange]) == pytest.approx(3, abs=0.4)
    assert_runs(got[first_orange:], [("orange", 10)], first_tol=0.3)
    assert band_level(out, 0.3, 2.8, 440) < -60  # (no show sound under the bumper)
    assert band_level(out, 3.4, 5.0, 440) > -40  # (the program's, from its start)
