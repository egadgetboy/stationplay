"""Recovering from a stall (a disk being reset, say, or the GPU hanging):
a killed ffmpeg that's slow to go isn't waited for; the next program reads
ahead far enough to build the cushion back; "falling behind" is said only
when the stream is losing ground, not while it catches up; and a stall
isn't held against the GPU, as it may as well be the disk's doing."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import broadcaster as bc
from app import ffmpeg as ff
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient
from app.sources import ResolvedSource
from app.tsstitch import TsStitcher

from .fakeplex import FakePlex
from .test_skipping import FakeGpu, item

# Stand-ins for ffmpeg: frames for half a second, then nothing (hung); and
# frames steadily for about four seconds.
HANGS = [sys.executable, "-c", (
    "import sys, time\n"
    "for n in range(1, 6):\n"
    "    print(f'frame={n * 30}', file=sys.stderr, flush=True); time.sleep(0.1)\n"
    "time.sleep(60)\n"
)]  # fmt: skip
STEADY = [sys.executable, "-c", (
    "import sys, time\n"
    "for n in range(20):\n"
    "    print(f'frame={400 + n * 6}', file=sys.stderr, flush=True); time.sleep(0.2)\n"
)]  # fmt: skip


def engine() -> bc.Broadcaster:
    b = bc.Broadcaster(SimpleNamespace(), 1)  # type: ignore[arg-type]
    b._session_start = int(time.time() * 1000)
    return b


async def test_a_killed_ffmpeg_slow_to_go_isnt_waited_for(monkeypatch, caplog):
    monkeypatch.setattr(bc, "STALL_TIMEOUT_S", 1.0)
    monkeypatch.setattr(bc, "KILL_GRACE_S", 0.5)
    b = engine()
    # As if stuck in the kernel (waiting on a disk being reset): killing it
    # doesn't make it go.
    monkeypatch.setattr(b, "_kill", lambda: None)
    started = time.monotonic()
    result = await b._run_ffmpeg(HANGS, TsStitcher(), bc.TS_BASE_S, first_frame_timeout=5)
    took = time.monotonic() - started
    assert result.stalled and not result.completed
    assert took < 6, took  # (not the minute it would hang for)
    assert "slow to stop" in caplog.text
    # It's killed for good, and reaped, meanwhile.
    reaping = list(bc._REAPING)
    assert reaping
    await asyncio.wait_for(asyncio.gather(*reaping), 10)


async def test_a_stall_reads_ahead_enough_to_build_the_cushion_back():
    b = engine()
    # Half a minute behind real time (a disk reset held it up): the next
    # program reads ahead the half minute and the cushion.
    b._session_start = int(time.time() * 1000) - 30_000
    assert b._burst_at(bc.TS_BASE_S) == pytest.approx(bc.TARGET_LEAD_S + 30, abs=0.5)
    assert bc.MAX_BURST_S >= bc.TARGET_LEAD_S + 30
    b._session_start = int(time.time() * 1000) + 10_000  # (a full cushion)
    assert b._burst_at(bc.TS_BASE_S) == pytest.approx(0, abs=0.5)


@pytest.mark.parametrize(
    ("leads", "warned"),
    [
        (lambda n: -10 + n, False),  # catching up after a stall
        (lambda n: -3.0, True),  # not gaining
        (lambda n: 0.5 - n * 0.2, True),  # losing ground
    ],
    ids=["catching-up", "stuck", "losing"],
)
async def test_falling_behind_is_said_only_when_its_losing_ground(
    monkeypatch, caplog, leads, warned
):
    monkeypatch.setattr(bc, "LOSING_S", 2.0)
    caplog.set_level(logging.WARNING, "app.broadcaster")
    b = engine()
    b._cushion_built = True
    calls = iter(range(1000))
    monkeypatch.setattr(b, "_lead_s", lambda ts: leads(next(calls)))
    result = await b._run_ffmpeg(STEADY, TsStitcher(), bc.TS_BASE_S, 5, on_air=True, what="X")
    assert result.completed
    assert ("falling behind" in caplog.text) is warned


class Runs:
    """Stands in for ffmpeg: the first run on the GPU stalls (or fails
    otherwise); the rest play."""

    def __init__(self, how: str) -> None:
        self.how = how
        self.encoders: list[str] = []

    def command(self, settings, source, offset_s, duration_s, ts, burst, *a, **kw):
        encoder = next((x for x in (*a, *kw.values()) if isinstance(x, ff.Encoder)), ff.CPU)
        self.encoders.append(encoder.kind)
        return ["ffmpeg", str(duration_s)]

    async def run(self, args, stitcher, ts, first_frame_timeout, on_air=False, what=""):
        duration = float(args[1])
        if len(self.encoders) == 1:
            return bc.PlayResult(
                duration / 2,
                completed=False,
                stalled=self.how == "stall",
                reason="playback stalled" if self.how == "stall" else "boom",
                next_ts=ts + duration / 2,
            )
        return bc.PlayResult(duration, completed=True, next_ts=ts + duration + bc.JOIN_GAP_S)


@pytest.mark.parametrize(("how", "events"), [
    ("stall", ["stalled"]),
    ("fail", ["failed", "rescued"]),
])  # fmt: skip
def test_a_stall_isnt_held_against_the_gpu(monkeypatch, tmp_path, how, events):
    fp = FakePlex()
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    gpu = FakeGpu()
    runs = Runs(how)
    with TestClient(app) as client:
        ctx = app.state.ctx
        ctx.gpu = gpu
        b = bc.Broadcaster(ctx, 1)
        b._session_start = int(time.time() * 1000)

        async def prepare(it, aspect_mode):
            probe = ff.ProbeResult(ok=True, duration_s=1320.0, audio_index=0)
            return bc.Opened(ResolvedSource("/tv/x.mkv", "/tv/x.mkv", 1), probe)

        monkeypatch.setattr(b, "_prepare", prepare)
        monkeypatch.setattr(b, "_run_ffmpeg", runs.run)
        monkeypatch.setattr(ff, "program_command", runs.command)
        it = item()
        first = client.portal.call(b._play_item, it, 0.0, 600.0, 10.0, 0.0, b._stitcher, "S")
        assert first.gpu_retry
        # The engine carries on with it on the CPU, from where it stopped.
        then = client.portal.call(
            b._play_item, it, first.produced_s, 600.0 - first.produced_s, 10.0, 0.0,
            b._stitcher, "S",
        )  # fmt: skip
        assert then.completed
    assert runs.encoders == ["vaapi", "cpu"]
    # A stall may be the disk's: no strike against the GPU.
    assert gpu.events == events
