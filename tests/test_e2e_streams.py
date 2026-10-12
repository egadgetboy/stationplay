"""End to end: a stream never just stops.

However the engine goes wrong, a viewer either keeps getting a stream or,
if the station really has ended, is disconnected at once (so the player
notices and tunes again) rather than left waiting on silence.
"""

from __future__ import annotations

import asyncio
import shutil
import time

import pytest

from app import broadcaster as bc

from .fakeplex import FakePlex
from .test_e2e import CLIP_S, assert_clean_stream, make_channel, media_seconds, record, start_server

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def three_episodes(media) -> FakePlex:
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    for n, name in enumerate(("good1", "good2", "good3"), start=1):
        plex.add_episode(f"20{n}", "100", 1, n, name, str(media[name]), CLIP_S * 1000)
    return plex


def test_a_viewer_is_only_dropped_once_far_behind():
    viewer = bc.Viewer("x")
    chunk = b"\x47" * 18_424  # a typical piece of stream
    for _ in range(3000):  # ~55 MB: a minute and a half at the default quality
        viewer.push(chunk)
    assert not viewer.closed
    for _ in range(1000):
        viewer.push(chunk)
    assert viewer.closed and "stopped reading" in (viewer.ended_because or "")


async def test_a_viewer_reading_normally_is_never_dropped():
    viewer = bc.Viewer("x")
    for _ in range(10):
        viewer.push(b"a" * 1000)
    assert viewer.queued_bytes == 10_000
    assert await viewer.next_chunk() == b"a" * 1000
    assert viewer.queued_bytes == 9000
    viewer.close()
    assert await viewer.next_chunk() is None and viewer.ended_because is None


async def test_a_stuck_engine_is_restarted_without_the_viewer_noticing(
    tmp_path, media, monkeypatch, caplog
):
    """Something in the engine waits forever (it never has, but if it
    did): the station notices the silence and restarts its engine, well
    within the stream's cushion."""
    monkeypatch.setattr(bc, "ENGINE_SILENCE_S", 5.0)
    base, _app, _settings, srv, task = await start_server(tmp_path, three_episodes(media))
    real = bc.Broadcaster._play_item
    calls = {"n": 0}

    async def hangs_once(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:  # the second program: the stream is ~10s ahead by then
            await asyncio.Event().wait()
        return await real(self, *args, **kwargs)

    monkeypatch.setattr(bc.Broadcaster, "_play_item", hangs_once)
    try:
        await make_channel(base)
        started = time.time()
        data = await record(f"{base}/stream/7", 2.3 * CLIP_S)
        elapsed = time.time() - started
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "stuck.ts"
    out.write_bytes(data)
    assert "sent nothing for" in caplog.text
    assert calls["n"] >= 3
    assert_clean_stream(out)
    assert media_seconds(out) >= elapsed - 3  # never ran dry


async def test_recovering_from_a_failure_can_fail_too_and_the_stream_carries_on(
    tmp_path, media, monkeypatch, caplog
):
    base, app, _settings, srv, task = await start_server(tmp_path, three_episodes(media))
    try:
        await make_channel(base)
        ctx = app.state.ctx
        real_station = ctx.station
        real_recover = bc.Broadcaster._recover
        state = {"station": 0, "recover": 0}

        def failing_once(channel_id):
            state["station"] += 1
            if state["station"] == 2:
                raise RuntimeError("simulated engine fault")
            return real_station(channel_id)

        async def recover_fails_once(self, failures):
            state["recover"] += 1
            if state["recover"] == 1:
                raise RuntimeError("simulated fault while recovering")
            return await real_recover(self, failures)

        monkeypatch.setattr(ctx, "station", failing_once)
        monkeypatch.setattr(bc.Broadcaster, "_recover", recover_fails_once)
        started = time.time()
        data = await record(f"{base}/stream/7", 2.2 * CLIP_S)
        elapsed = time.time() - started
    finally:
        srv.should_exit = True
        await task
    assert "recovery failed; trying again" in caplog.text
    out = tmp_path / "recover.ts"
    out.write_bytes(data)
    assert media_seconds(out) >= elapsed - 6


async def test_a_station_that_ends_disconnects_its_viewers_at_once(
    tmp_path, media, monkeypatch, caplog
):
    """If a station's engine ends while someone is watching (here the
    station vanishes from the database), the viewer is disconnected rather
    than left waiting on a stream that has stopped."""
    base, app, _settings, srv, task = await start_server(tmp_path, three_episodes(media))
    try:
        station = await make_channel(base)
        ctx = app.state.ctx

        async def vanish():
            await asyncio.sleep(4)
            with ctx.db._lock, ctx.db._conn:
                ctx.db._conn.execute("DELETE FROM channels WHERE id = ?", (station["id"],))

        vanishing = asyncio.create_task(vanish())
        started = time.monotonic()
        await record(f"{base}/stream/7", 60)
        ended_after = time.monotonic() - started
        await vanishing
    finally:
        srv.should_exit = True
        await task
    assert ended_after < 20, ended_after  # well before the 60s the viewer wanted
    assert "the station's stream ended" in caplog.text
