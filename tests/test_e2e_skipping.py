"""End to end: skipping intros and credits, with real ffmpeg.

Each test episode is made of solid-colour stretches (cold open, intro,
program, credits), so what a viewer receives can be read back frame by
frame: which stretches aired, in what order, and for how long.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

import httpx
import pytest

from app import markers as mk

from .fakeplex import FakePlex
from .test_e2e import _frame_yuv, assert_clean_stream, ff, record, start_server

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

S = 1000
FRAME_S = 1001 / 30000
# Average U and V of each colour in the stream (black is told apart by brightness).
UV = {
    "yellow": (16, 146),
    "lime": (54, 34),
    "cyan": (166, 16),
    "magenta": (202, 222),
    "orange": (42, 179),
    "white": (128, 128),
}
# Episode 1: a cold open, the intro, the program, the credits.
EP1 = [("yellow", 6), ("lime", 4), ("cyan", 10), ("magenta", 4)]
# Episode 2: straight into the intro, then the program and credits.
EP2 = [("lime", 4), ("orange", 10), ("magenta", 4)]
# Episode 3: Plex hasn't marked it, so it all plays.
EP3 = [("yellow", 3), ("lime", 3), ("white", 6), ("magenta", 3)]


def sectioned(path: Path, sections: list[tuple[str, float]]) -> None:
    chains = [f"color=c={c}:s=640x360:r=30:d={d}[s{n}]" for n, (c, d) in enumerate(sections)]
    joined = "".join(f"[s{n}]" for n in range(len(sections)))
    graph = ";".join(chains) + f";{joined}concat=n={len(sections)}:v=1:a=0[out0]"
    total = sum(d for _, d in sections)
    ff(
        "-f", "lavfi", "-i", graph,
        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", str(total),
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path),
    )  # fmt: skip


def runs(path: Path) -> list[tuple[str, float]]:
    """(colour, seconds) of each stretch of one colour, in order."""
    out: list[list] = []
    for _t, y, u, v in _frame_yuv(path):
        colour = (
            "black" if y < 40 else min(UV, key=lambda c: (UV[c][0] - u) ** 2 + (UV[c][1] - v) ** 2)
        )
        if out and out[-1][0] == colour:
            out[-1][1] += 1
        else:
            out.append([colour, 1])
    return [(c, n * FRAME_S) for c, n in out]


@pytest.fixture
def episodes(tmp_path, monkeypatch) -> FakePlex:
    # The test episodes are seconds long; real ones must keep a minute.
    monkeypatch.setattr(mk, "MIN_PROGRAM_MS", 5 * S)
    d = tmp_path / "media"
    d.mkdir()
    plex = FakePlex()
    plex.add_show("100", "Colours")
    for n, sections in enumerate((EP1, EP2, EP3), start=1):
        sectioned(d / f"{n}.mkv", sections)
        length = sum(s for _, s in sections) * S
        plex.add_episode(f"20{n}", "100", 1, n, f"Episode {n}", str(d / f"{n}.mkv"), length)
    plex.set_markers("201", ("intro", 6 * S, 10 * S), ("credits", 20 * S, 24 * S, True))
    plex.set_markers("202", ("intro", 0, 4 * S), ("credits", 14 * S, 18 * S, True))
    return plex


async def make_station(base: str, skip: bool = True) -> dict:
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        made = await client.post(
            "/api/channels",
            json={
                "number": 9,
                "name": "Binge TV",
                "orderMode": "rotate",
                "skipIntros": skip,
                "sources": [{"type": "show", "ratingKey": "100"}],
            },
        )
        assert made.status_code == 201, made.text
        return made.json()


def assert_runs(got: list[tuple[str, float]], want: list[tuple[str, float]], first_tol=1.0):
    print("\naired: " + ", ".join(f"{c} {s:.2f}s" for c, s in got))
    colours = [c for c, _ in got]
    assert colours[: len(want)] == [c for c, _ in want], colours
    for n, ((colour, seconds), (_, expected)) in enumerate(zip(got, want, strict=False)):
        tolerance = first_tol if n == 0 else 0.3
        assert abs(seconds - expected) <= tolerance, (n, colour, seconds, expected)


async def test_intros_and_credits_never_air_and_programs_follow_straight_on(
    tmp_path, episodes, caplog
):
    base, _app, _settings, srv, task = await start_server(tmp_path, episodes)
    try:
        station = await make_station(base)
        assert station["trimmedCount"] == 2
        async with httpx.AsyncClient(base_url=base) as client:
            guide = (await client.get(f"/api/channels/{station['id']}/guide?hours=1")).json()
        assert [g["end"] - g["start"] for g in guide[:3]] == [16 * S, 10 * S, 15 * S]
        data = await record(f"{base}/stream/9", 44)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "binge.ts"
    out.write_bytes(data)
    assert_clean_stream(out)  # no glitch where a part is skipped
    assert "falling behind" not in caplog.text  # nor while the stream got going
    # Episode 1: cold open, then straight to the program (no intro, no
    # credits). Episode 2 starts with its program. Episode 3 has no markers
    # and plays in full. Each lasts exactly as long as the guide says.
    assert_runs(
        runs(out),
        [
            ("yellow", 6),
            ("cyan", 10),
            ("orange", 10),
            ("yellow", 3),
            ("lime", 3),
            ("white", 6),
            ("magenta", 3),
        ],
    )


async def test_tuning_in_part_way_starts_at_the_right_moment(tmp_path, episodes):
    base, _app, _settings, srv, task = await start_server(tmp_path, episodes)
    try:
        station = await make_station(base)
        await asyncio.sleep(9)
        tuned = time.time() * 1000
        data = await record(f"{base}/stream/9", 12)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "tuned.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    # 9 seconds into the 16-second episode 1 is 3 seconds into its program
    # (13 seconds into the file, past the intro): the rest of it, then episode 2.
    into = (tuned - station["now"]["start"]) / 1000
    assert_runs(runs(out), [("cyan", 16 - into), ("orange", 10)], first_tol=0.7)


async def test_a_hiccup_after_a_skip_resumes_in_the_right_place(
    tmp_path, episodes, monkeypatch, caplog
):
    """ffmpeg stops early once, in the part after the intro: StationPlay
    carries on from where it got to, in the same part."""
    from app import ffmpeg as ff_mod

    real = ff_mod.program_command
    tripped = {"done": False}

    def once_short(settings, source, offset_s, duration_s, *args, **kwargs):
        if not tripped["done"] and source.endswith("1.mkv") and offset_s >= 9.5:
            tripped["done"] = True
            duration_s = 3.0  # as if the share went away three seconds in
        return real(settings, source, offset_s, duration_s, *args, **kwargs)

    monkeypatch.setattr(ff_mod, "program_command", once_short)
    base, _app, settings, srv, task = await start_server(tmp_path, episodes)
    try:
        await make_station(base)
        data = await record(f"{base}/stream/9", 30)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "hiccup.ts"
    out.write_bytes(data)
    assert tripped["done"]
    assert "Resuming it (attempt 1 of 2)" in caplog.text
    assert_clean_stream(out)
    # Nothing replayed, nothing skipped: the program part still totals 10s.
    assert_runs(runs(out), [("yellow", 6), ("cyan", 10), ("orange", 10)])
    assert not (settings.data_dir / "broken-files.json").exists()


async def test_turning_skipping_on_while_watching_starts_at_the_next_program(
    tmp_path, episodes, monkeypatch
):
    from app import main, updates

    monkeypatch.setattr(updates, "MARGIN_MS", 8000)
    monkeypatch.setattr(main, "MARGIN_MS", 8000)
    base, _app, _settings, srv, task = await start_server(tmp_path, episodes)
    try:
        station = await make_station(base, skip=False)
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:

            async def turn_on() -> dict:
                await asyncio.sleep(3)
                resp = await client.put(
                    f"/api/channels/{station['id']}",
                    json={
                        "number": 9,
                        "name": "Binge TV",
                        "orderMode": "rotate",
                        "skipIntros": True,
                        "sources": station["sources"],
                    },
                )
                assert resp.status_code == 200, resp.text
                return resp.json()

            turning = asyncio.create_task(turn_on())
            data = await record(f"{base}/stream/9", 38)
            changed = await turning
    finally:
        srv.should_exit = True
        await task
    assert changed["changed"] and changed["lastChange"]["startsAt"] == station["now"]["end"]
    out = tmp_path / "toggle.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    # The episode on air when the setting changed plays in full; from the
    # next one on, intros and credits are skipped.
    assert_runs(
        runs(out),
        [("yellow", 6), ("lime", 4), ("cyan", 10), ("magenta", 4), ("orange", 10)],
    )


async def test_a_corner_mark_at_the_start_shows_when_someone_tunes_in(
    tmp_path, episodes, monkeypatch
):
    """Tuning in partway through a program is a start too: the mark shows
    for its stretch from there, then goes until the next program."""
    from app import ffmpeg as ff_mod

    from .test_e2e_breaks import frames

    monkeypatch.setattr(ff_mod, "WATERMARK_START_S", 5.0)  # 30 seconds, shortened
    base, _app, _settings, srv, task = await start_server(tmp_path, episodes)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={
                    "number": 9, "name": "Late Join TV", "orderMode": "rotate",
                    "watermark": "logo", "logo": "classic-tv", "watermarkTiming": "start",
                    "watermarkPosition": "bottom-right",  # (where it's looked for below)
                    "sources": [{"type": "show", "ratingKey": "100"}],
                },
            )  # fmt: skip
            assert made.status_code == 201, made.text
        # Into the first episode (24 seconds), well past its first 5.
        await asyncio.sleep(9)
        data = await record(f"{base}/stream/9", 12)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "joined.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    middle = frames(out, "40:40:300:160")
    corner = frames(out, "24:24:590:318")
    frame_s = 1001 / 30000
    for n, ((my, mu, mv), (cy, cu, cv)) in enumerate(zip(middle, corner, strict=True)):
        t, is_marked = n * frame_s, abs(cy - my) + abs(cu - mu) + abs(cv - mv) > 12
        if 0.3 < t < 4.5:
            assert is_marked, t  # shown as they tune in
        elif 5.8 < t < 11:
            assert not is_marked, t  # then gone (the episode runs to about 15s)


async def test_a_corner_mark_at_the_start_spans_the_skipped_intro(tmp_path, episodes, monkeypatch):
    """Shown for the first stretch of each program as it airs: carried on
    across the cut where the intro is skipped, then gone until the next."""
    from app import ffmpeg as ff_mod

    from .test_e2e_breaks import frames

    monkeypatch.setattr(ff_mod, "WATERMARK_START_S", 8.0)  # 30 seconds, shortened
    base, _app, _settings, srv, task = await start_server(tmp_path, episodes)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={
                    "number": 9, "name": "Binge TV", "orderMode": "rotate", "skipIntros": True,
                    "watermark": "logo", "logo": "classic-tv", "watermarkTiming": "start",
                    "watermarkPosition": "bottom-right",  # (where it's looked for below)
                    "sources": [{"type": "show", "ratingKey": "100"}],
                },
            )  # fmt: skip
            assert made.status_code == 201, made.text
            assert made.json()["watermarkTiming"] == "start"
        data = await record(f"{base}/stream/9", 36)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "start.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    # The picture's colour in the middle, and whether the corner differs from it.
    middle = frames(out, "40:40:300:160")
    corner = frames(out, "24:24:590:318")
    marked = [
        abs(cy - my) + abs(cu - mu) + abs(cv - mv) > 12
        for (my, mu, mv), (cy, cu, cv) in zip(middle, corner, strict=True)
    ]
    colours = [c for c, _ in runs(out)]
    lengths = [s for _, s in runs(out)]
    # Programs: yellow (cold open) + cyan (after the skipped intro), then
    # orange, then yellow, lime, white, magenta (no markers).
    assert colours[:4] == ["yellow", "cyan", "orange", "yellow"], colours
    ep1, ep2, ep3 = sum(lengths[:2]), lengths[2], sum(lengths[3:7])
    starts = [0.0, ep1, ep1 + ep2, ep1 + ep2 + ep3]  # then episode 1 again
    frame_s = 1001 / 30000
    assert len(colours) > 7 and abs(ep3 - 15) < 0.3  # the recording reaches episode 1 again
    for n, is_marked in enumerate(marked):
        t = n * frame_s
        since = t - max(s for s in starts if s <= t + 1e-6)
        if 0.3 < since < 6.7:
            assert is_marked, (t, since)  # shown, across the yellow-to-cyan cut too
        elif since > 8.3:
            assert not is_marked, (t, since)  # gone until the next program
