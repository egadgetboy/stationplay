"""Burn-in protection (ffmpeg.NUDGES): each program on a station starts with
the corner logo, name or clock moved to the next of a few places within 6
px of where the station puts it, the same on the CPU and the GPU, and the Up
Next Banner's logo still lands on the corner logo."""

from __future__ import annotations

import itertools
import math
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import broadcaster, upnext
from app import ffmpeg as ff
from app.config import Settings
from app.ffmpeg import CPU, Encoder, Watermark
from app.schedule import Slot

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
LOGO = str(Path(ff.__file__).parent / "logos" / "classic-tv.png")
SMALL = Settings(plex_url="", plex_token="", video_width=640, video_height=360)


def test_the_places_cycle_and_stay_within_6_px():
    places = [ff.nudge(n) for n in range(27)]
    assert set(places[:9]) == set(ff.NUDGES) and len(set(places[:9])) == 9
    assert places[9:18] == places[:9] == places[18:]  # (round and round)
    for (dx, dy), (ex, ey) in itertools.pairwise(places):
        assert math.hypot(dx, dy) <= 6 and dx % 2 == dy % 2 == 0
        assert (dx, dy) != (ex, ey)  # (each program somewhere new)
    assert ff.Watermark().nudge == (0, 0)  # (nothing else is moved)


def test_the_corner_mark_moves_with_its_nudge():
    margin_x, margin_y = ff.corner_margins(SMALL)  # (22, 18)
    for nudge in ff.NUDGES:
        dx, dy = nudge
        for position in ff.WATERMARK_POSITIONS:
            left, top = position.endswith("left"), position.startswith("top")
            x = str(margin_x + dx) if left else f"-{margin_x - dx}"
            y = str(margin_y + dy) if top else f"-{margin_y - dy}"
            logo = ff._watermark(SMALL, Watermark(logo=LOGO, position=position, nudge=nudge))[1]
            assert f"overlay={'' if left else 'W-w'}{x}:{'' if top else 'H-h'}{y}:" in logo
            for mark in (
                Watermark(text="Hits", position=position, nudge=nudge),
                Watermark(clock="12", position=position, nudge=nudge),
            ):
                drawn = ff._watermark(SMALL, mark)[1]
                assert f":x={'' if left else 'w-tw'}{x}:y={'' if top else 'h-th'}{y}" in drawn


def test_the_cpu_and_the_gpu_move_it_alike():
    """The corner mark is drawn before the picture goes to the encoder, on
    every encoder, so a GPU's programs move it just as the CPU's do."""
    mark = Watermark(logo=LOGO, position="top-left", nudge=(-4, 4))
    graphs = set()
    for encoder in (CPU, Encoder("vaapi", "/dev/dri/renderD128"), Encoder("nvidia", "0")):
        args = ff.program_command(SMALL, "/tv/x.mkv", 0, 60, 10, 1, 0, "x", encoder, watermark=mark)
        graph = args[args.index("-vf") + 1]
        assert "overlay=18:22:" in graph, encoder
        graphs.add(graph.removesuffix(",format=nv12,hwupload"))
    assert len(graphs) == 1  # (the same drawing: only the upload to a GPU follows it)


@needs_ffmpeg
@pytest.mark.parametrize("nudge", [(4, 4), (-4, 0), (0, -4), (-4, 4)])
def test_drawn_for_real_it_moves_exactly_that_far(tmp_path, nudge):
    def frame(mark: Watermark | None) -> bytes:
        chain = ff._video_filter(SMALL, watermark=mark)
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x3050A0:s=640x360:r=30000/1001",
             "-vf", chain, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, check=True,
        ).stdout  # fmt: skip

    def box(img: bytes, plain: bytes) -> tuple[int, int, int, int]:
        """Where it differs from the plain picture: left, top, right, bottom."""
        found = [(i % 640, i // 640) for i, (a, b) in enumerate(zip(img, plain, strict=True))
                 if abs(a - b) > 24]  # fmt: skip
        xs, ys = [x for x, _ in found], [y for _, y in found]
        return min(xs), min(ys), max(xs), max(ys)

    plain = frame(None)
    for position in ("bottom-right", "top-left"):
        here = box(frame(Watermark(logo=LOGO, position=position)), plain)
        moved = box(frame(Watermark(logo=LOGO, position=position, nudge=nudge)), plain)
        shift = (moved[0] - here[0], moved[1] - here[1])
        assert shift == nudge and (moved[2] - here[2], moved[3] - here[3]) == nudge, position
        assert math.hypot(*shift) <= 6


def test_each_program_starts_with_it_in_the_next_place():
    b = broadcaster.Broadcaster(SimpleNamespace(), 1)  # type: ignore[arg-type]

    def slot(start_ms: int) -> Slot:
        return Slot(SimpleNamespace(), 0, 0, start_ms, start_ms + 60_000)  # type: ignore[arg-type]

    first = b._nudge_for(slot(0))
    assert b._nudge_for(slot(0)) == first  # (the same program: resumed, or replaced partway)
    places = [first] + [b._nudge_for(slot(n * 60_000)) for n in range(1, 18)]
    assert all(a != b for a, b in itertools.pairwise(places))
    assert set(places[:9]) == set(ff.NUDGES) and places[:9] == places[9:]


def test_the_up_next_banner_still_lands_on_the_corner_logo(tmp_path):
    colours = ("101820", "203040", "E0A030")
    size = ff.mark_size(SMALL, Watermark(logo=LOGO, position="bottom-left"))
    where = {}
    for nudge in ((0, 0), (4, -4)):
        banner = upnext.UpNext("Cheers", LOGO, 5, "large", size, nudge)
        where[nudge] = upnext.banner_command(SMALL, banner, colours, tmp_path / "b.png")[1]
    assert where[(4, -4)] == (where[(0, 0)][0] + 4, where[(0, 0)][1] - 4)
    # A station's banner takes its corner mark's place, wherever that is now.
    channel = SimpleNamespace(
        watermark="logo", logo="classic-tv", name="Hits", watermark_size="large",
        watermark_transparency="low", watermark_position="bottom-left", watermark_timing="always",
        watermark_style="color", clock_format="12", up_next_seconds=5, up_next_size="large",
    )  # fmt: skip
    ctx = SimpleNamespace(settings=SMALL, logos=SimpleNamespace(path=lambda logo: Path(LOGO)))
    mark = broadcaster.corner_mark(ctx, channel, (-4, 4))  # type: ignore[arg-type]
    assert mark is not None and mark.nudge == (-4, 4)
    banner = broadcaster.station_banner(ctx, channel, "Cheers", mark, SMALL)  # type: ignore[arg-type]
    assert banner.on_corner_logo and banner.nudge == (-4, 4)
