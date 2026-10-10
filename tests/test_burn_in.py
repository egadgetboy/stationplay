"""Burn-in protection (ffmpeg.NUDGES and ffmpeg.drift): all through every
program, the corner logo, name or clock steps to the next of 9 places within
6 px of where the station puts it every few minutes, by the time each frame
airs (so starting, resuming or tuning in to a program never moves it or
holds it), the same on the CPU and the GPU; and the Up Next Banner's logo
still lands on the corner logo, wherever that is."""

from __future__ import annotations

import asyncio
import itertools
import math
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from app import ffmpeg as ff
from app import upnext
from app.config import Settings
from app.ffmpeg import CPU, DRIFT_S, NUDGES, Encoder, Watermark
from app.markers import trimmed

from .fakeplex import FakePlex
from .test_e2e import assert_clean_stream, record, start_server
from .test_e2e import ff as make_media
from .test_e2e_breaks import make_station
from .test_skipping import FakeRun, S, item, play
from .test_skipping import intro as intro_marker
from .test_upnext import SCREEN, block_logo, frames_of, magenta, middle

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
LOGO = str(Path(ff.__file__).parent / "logos" / "classic-tv.png")
SMALL = Settings(plex_url="", plex_token="", video_width=640, video_height=360)
HD = Settings(plex_url="", plex_token="")  # 1280x720
FRAME_S = ff.FPS_DEN / ff.FPS_NUM


def place_at(at_s: float) -> tuple[int, int]:
    """Where the mark should be on a frame that airs at `at_s`."""
    return NUDGES[math.floor(at_s / DRIFT_S) % len(NUDGES)]


def test_the_places_go_round_in_short_steps_within_6_px():
    assert len(set(NUDGES)) == 9 and NUDGES[0] == (0, 0)
    for (dx, dy), (ex, ey) in itertools.pairwise((*NUDGES, NUDGES[0])):
        assert math.hypot(dx, dy) <= 6 and dx % 2 == dy % 2 == 0
        assert (dx, dy) != (ex, ey) and max(abs(ex - dx), abs(ey - dy)) == 4  # (a neighbour)
    # Every few minutes, as the clock's minutes change.
    assert 180 <= DRIFT_S <= 300 and DRIFT_S % 60 == 0


def test_the_drift_is_only_numbers_and_the_frames_time():
    """(Nothing of a station's goes into it, however odd the time.)"""
    for at in (0.0, 1791000000.25, -5.0, 1e12):
        for axis in (0, 1):
            said = ff.drift(axis, at)
            assert set(said) <= set("0123456789.+-*/(),;t") | set("stmodflreqd"), said
            assert "nan" not in said and "inf" not in said


def corner_box(img: bytes, plain: bytes, width: int) -> tuple[int, int, int, int]:
    """Where a picture differs from the plain one: left, top, right, bottom."""
    found = [(i % width, i // width) for i, (a, b) in enumerate(zip(img, plain, strict=True))
             if abs(a - b) > 24]  # fmt: skip
    assert found, "nothing drawn"
    xs, ys = [x for x, _ in found], [y for _, y in found]
    return min(xs), min(ys), max(xs), max(ys)


def drawn(mark: Watermark | None, frames: int = 1) -> list[bytes]:
    """The first `frames` frames of a plain picture with `mark` over it."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x3050A0:s=640x360:r=30000/1001",
         "-vf", ff._video_filter(SMALL, watermark=mark), "-frames:v", str(frames),
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    size = 640 * 360
    return [out[n * size : (n + 1) * size] for n in range(frames)]


@needs_ffmpeg
@pytest.mark.parametrize("position", ["bottom-right", "top-left"])
def test_drawn_for_real_it_is_where_the_time_it_airs_says(position):
    """The logo, at each of the 9 places in turn, and a real day's time; the
    same place for the same moment, whatever's playing."""
    [plain] = drawn(None)

    def where(at_s: float) -> tuple[int, int]:
        [img] = drawn(Watermark(logo=LOGO, position=position, airs_at_s=at_s))
        left, top, _, _ = corner_box(img, plain, 640)
        return left, top

    home = where(0.0)  # (NUDGES[0]: where the station puts it)
    for at in [n * DRIFT_S + 7.5 for n in range(1, 10)] + [1791000000.25, 1791000000.25 + 3600]:
        x, y = where(at)
        assert (x - home[0], y - home[1]) == place_at(at), at


@needs_ffmpeg
def test_it_steps_to_the_next_place_on_the_frame_its_due():
    """Moving on all through what's played, one step at a time, exactly when
    each frame's time says: here half a second in."""
    [plain] = drawn(None)
    at = 1791000000.0 // DRIFT_S * DRIFT_S + DRIFT_S - 0.5  # (a step due 0.5s in)
    frames = drawn(Watermark(logo=LOGO, airs_at_s=at), 30)
    boxes = [corner_box(img, plain, 640) for img in frames]
    before, after = place_at(at), place_at(at + 1)
    assert before != after
    due = math.ceil(0.5 / FRAME_S)
    assert len(set(boxes[:due])) == 1 and len(set(boxes[due:])) == 1, boxes
    (x0, y0, *_), (x1, y1, *_) = boxes[0], boxes[-1]
    assert (x1 - x0, y1 - y0) == (after[0] - before[0], after[1] - before[1])


@needs_ffmpeg
def test_the_name_and_the_clock_drift_too(monkeypatch):
    """Drawn as writing, they move by the same steps. (The clock's at 10:00
    to 10:35, UTC, so its first digit, and where it starts, are the same.)"""
    monkeypatch.setenv("TZ", "UTC")
    [plain] = drawn(None)
    ten = 10 * 3600.0
    for mark in (Watermark(text="Hits", position="top-left"),
                 Watermark(clock="24", position="top-left")):  # fmt: skip
        found = {}
        for n in range(9):
            at = ten + n * DRIFT_S + 30
            [img] = drawn(replace(mark, airs_at_s=at))
            left, top, _, _ = corner_box(img, plain, 640)
            found[place_at(at)] = (left, top)
        assert set(found) == set(NUDGES)
        hx, hy = found[(0, 0)]
        assert all((x - hx, y - hy) == place for place, (x, y) in found.items()), (mark, found)


def test_the_cpu_and_the_gpu_move_it_alike():
    """The corner mark is drawn before the picture goes to the encoder, on
    every encoder, so a GPU's programs move it just as the CPU's do."""
    mark = Watermark(logo=LOGO, position="top-left", airs_at_s=1791000000.0)
    graphs = set()
    for encoder in (CPU, Encoder("vaapi", "/dev/dri/renderD128"), Encoder("nvidia", "0")):
        args = ff.program_command(SMALL, "/tv/x.mkv", 0, 60, 10, 1, 0, "x", encoder, watermark=mark)
        graph = args[args.index("-vf") + 1]
        assert (
            f"overlay=x='22+{ff.drift(0, mark.airs_at_s)}':y='18+{ff.drift(1, mark.airs_at_s)}'"
            in graph
        )
        graphs.add(graph.removesuffix(",format=nv12,hwupload"))
    assert len(graphs) == 1  # (the same drawing: only the upload to a GPU follows it)


@needs_ffmpeg
def test_the_up_next_banner_drifts_with_the_corner_logo(tmp_path):
    """The banner takes the corner logo's place and moves with it: its logo
    lands on the corner logo before a step that comes while it's up, and
    after it, and the corner logo comes back where the banner's logo is."""
    logo = block_logo(tmp_path)
    at = 1791000000.0 // DRIFT_S * DRIFT_S + DRIFT_S - 2.0  # (a step due 2s in)
    mark = Watermark(logo=str(logo), position="bottom-left", size="large", airs_at_s=at)
    banner = upnext.UpNext("Cheers", str(logo), 3, "large", upnext.corner_logo(HD, mark))
    picture = tmp_path / "banner.png"
    where = asyncio.run(upnext.draw(HD, banner, picture, 30))
    assert where is not None
    shown = upnext.on_air(banner, picture, where, 1.0)  # (up from 1s to 4s)
    graph = ff.with_overlays(HD, SCREEN.format("gray"), mark, shown)
    # The corner logo, the banner before the step and after it, the corner logo.
    shots = frames_of(graph, (10, 50, 75, 150), tmp_path)
    margin_x, margin_y = ff.corner_margins(HD)
    size = ff.mark_size(HD, mark)
    box = (margin_x - 10, 720 - margin_y - size - 10, margin_x + size + 10, 720 - margin_y + 10)
    before, up, moved, after = (middle(shot, box, magenta) for shot in shots)
    step = tuple(b - a for a, b in zip(place_at(at), place_at(at + 3), strict=True))
    assert step != (0, 0)
    # Well within a pixel (one out would be 1 apart).
    assert abs(up[0] - before[0]) < 0.4 and abs(up[1] - before[1]) < 0.4
    assert abs(moved[0] - before[0] - step[0]) < 0.4 and abs(moved[1] - before[1] - step[1]) < 0.4
    assert abs(after[0] - moved[0]) < 0.4 and abs(after[1] - moved[1]) < 0.4


class Marks(FakeRun):
    """FakeRun, also keeping the corner mark over each part, and where in
    the stream the part starts."""

    def __init__(self) -> None:
        super().__init__()
        self.marks: list[tuple[float, Watermark | None]] = []

    def command(self, settings, source, offset_s, duration_s, ts, burst, *a, watermark=None, **kw):
        self.marks.append((ts, watermark))
        return super().command(settings, source, offset_s, duration_s, ts, burst, *a, **kw)


async def test_each_part_drifts_by_when_it_airs(monkeypatch, tmp_path):
    """Each part of a program (here, either side of a skipped intro) is
    drawn from when it airs, so the mark carries on through the cut; and a
    program resumed, or tuned in to, goes by when it airs too."""
    it = trimmed(item(), [intro_marker(90 * S, 150 * S)])
    mark = Watermark(logo=LOGO)
    run = Marks()
    began = time.time()
    result = await play(monkeypatch, tmp_path, it, 0.0, 1260.0, run, lead_s=10, watermark=mark)
    assert result.completed
    (ts1, first), (ts2, second) = run.marks
    assert first is not None and second is not None
    assert abs(first.airs_at_s - (began + 10)) < 2  # (the stream's 10s ahead)
    assert second.airs_at_s - first.airs_at_s == pytest.approx(ts2 - ts1, abs=0.002)
    # Resumed 10 minutes in, or tuned in to then: when that airs, never a
    # place of its own.
    run = Marks()
    await play(monkeypatch, tmp_path, it, 600.0, 660.0, run, lead_s=3, watermark=mark)
    [(_, resumed)] = run.marks
    assert resumed is not None and abs(resumed.airs_at_s - (time.time() + 3)) < 2
    assert {first.logo, second.logo, resumed.logo} == {LOGO}


# On the air ---------------------------------------------------------------------


def corner_places(path: Path) -> list[tuple[int, int]]:
    """Where the logo is in the bottom-right corner of each frame of a
    recording, in programs of one colour."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "crop=110:100:530:260",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    size = 110 * 100
    places = []
    for n in range(len(raw) // size):
        img = raw[n * size : (n + 1) * size]
        if any(abs(a - img[0]) > 24 for a in img[size - 110 * 8 :]):
            continue  # (not a program: nothing to look at)
        places.append(corner_box(img, bytes([img[0]]) * size, 110)[:2])
    return places


async def test_on_the_air_it_steps_all_through_programs_and_across_them(tmp_path, monkeypatch):
    """Real streaming, with the steps made 2 seconds apart: the logo moves
    to the next place every 2 seconds, through each program and across the
    change to the next, one place at a time and steady in between."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    from app import markers

    monkeypatch.setattr(ff, "DRIFT_S", 2)
    monkeypatch.setattr(markers, "MIN_PROGRAM_MS", 5 * S)
    media = tmp_path / "media"
    media.mkdir()
    plex = FakePlex()
    plex.add_show("100", "Plain")
    for n in (1, 2):
        make_media(
            "-f", "lavfi", "-i", "color=c=0x3050A0:s=640x360:r=30", "-f", "lavfi",
            "-i", "sine=f=440:sample_rate=48000", "-t", "7", "-c:v", "libx264",
            "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(media / f"{n}.mkv"),
        )  # fmt: skip
        plex.add_episode(f"20{n}", "100", 1, n, f"Episode {n}", str(media / f"{n}.mkv"), 7 * S)
    base, _app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        await make_station(base, watermark="logo", logo="classic-tv",
                           watermarkPosition="bottom-right")  # fmt: skip
        data = await record(f"{base}/stream/5", 16)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "drift.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    places = corner_places(out)
    assert len(places) * FRAME_S > 14  # (two programs' worth: across a change)
    runs = [(place, len(list(same))) for place, same in itertools.groupby(places)]
    print("\nplaces: " + ", ".join(f"{p} x{n}" for p, n in runs))
    assert len(runs) >= 6, runs
    # Steady between steps, 2 seconds apart (to a frame or two: each part's
    # frames start on its own timeline).
    for _, frames in runs[1:-1]:
        assert abs(frames * FRAME_S - 2) <= 2.5 * FRAME_S, runs
    # One step at a time, round the places in order.
    steps = [(b[0] - a[0], b[1] - a[1]) for (a, _), (b, _) in itertools.pairwise(runs)]
    order = [(b[0] - a[0], b[1] - a[1]) for a, b in itertools.pairwise((*NUDGES, NUDGES[0]))]
    assert any(
        steps == [order[(start + k) % 9] for k in range(len(steps))] for start in range(9)
    ), steps
