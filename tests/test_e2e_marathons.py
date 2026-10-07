"""A marathon on the air: watched straight through, the stream never breaks,
three episodes of one show play back to back, and the station then carries
on with the program that was due when the marathon began."""

from __future__ import annotations

import shutil
import time

import httpx
import pytest

from app import marathons

from .fakeplex import FakePlex
from .test_e2e import assert_clean_stream, ff, record, start_server
from .test_e2e_skipping import UV, runs

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

CLIP_S = 4
# One colour for each show (each of its episodes looks the same).
SHOWS = ("yellow", "lime", "cyan", "magenta", "orange")


async def test_a_marathon_airs_and_the_station_carries_on(tmp_path, monkeypatch):
    from app import main, updates

    monkeypatch.setattr(updates, "MARGIN_MS", 6000)
    monkeypatch.setattr(main, "MARGIN_MS", 6000)
    assert set(SHOWS) <= set(UV)
    d = tmp_path / "media"
    d.mkdir()
    plex = FakePlex()
    for s, colour in enumerate(SHOWS, start=1):
        ff(
            "-f", "lavfi", "-i", f"color=c={colour}:s=640x360:r=30",
            "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", str(CLIP_S),
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
            str(d / f"{colour}.mkv"),
        )  # fmt: skip
        plex.add_show(str(s * 100), colour.title())
        for n in (1, 2, 3):
            # (A file of its own each: the same file twice is one program.)
            shutil.copy(d / f"{colour}.mkv", d / f"{colour}{n}.mkv")
            plex.add_episode(
                str(s * 100 + n), str(s * 100), 1, n, f"{colour} {n}", str(d / f"{colour}{n}.mkv"),
                CLIP_S * 1000,
            )  # fmt: skip
    # The marathon is due 14 seconds after the station is made.
    made_at = time.time() * 1000
    monkeypatch.setattr(
        marathons,
        "due_times",
        lambda channel, a, b: [t for t in [int(made_at + 14_000)] if a <= t < b],
    )
    base, app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = (
                await client.post(
                    "/api/channels",
                    json={
                        "number": 4,
                        "orderMode": "rotate",
                        "introSeconds": 0,
                        "upNextSeconds": 0,
                        "watermark": "off",
                        "marathonMode": "random",
                        "sources": [
                            {"type": "show", "ratingKey": str(s * 100)} for s in (1, 2, 3, 4, 5)
                        ],
                    },
                )
            ).json()
            eras = app.state.ctx.db.eras(made["id"])
            (special,) = [e for e in eras if e.special]
            carry = eras[eras.index(special) + 1]
            station = app.state.ctx.station(made["id"])
            due_then = station.locate(carry.start_ms)
            data = await record(f"{base}/stream/4", 30)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "marathon.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    shown = [(c, s) for c, s in runs(out) if c != "black" and s > 0.5]
    print("\naired:", " → ".join(f"{c} {s:.1f}s" for c, s in shown))
    marathon_colour = SHOWS[int(special.special["show"]) // 100 - 1]
    after = SHOWS[int(due_then.item.show_key) // 100 - 1]
    # One stretch of the marathon's show three episodes long (longer by a
    # program when the one before or after is of the same show), then the
    # program that was due when it began.
    long_runs = [n for n, (c, s) in enumerate(shown) if s > 2.5 * CLIP_S]
    assert len(long_runs) == 1, shown
    n = long_runs[0]
    colour, seconds = shown[n]
    assert colour == marathon_colour
    extra = seconds - 3 * CLIP_S
    assert min(abs(extra), abs(extra - CLIP_S)) < 1.0, shown
    assert n + 1 < len(shown), "the recording ends before the station carries on"
    if after != marathon_colour:
        assert shown[n + 1][0] == after, shown
