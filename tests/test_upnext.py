"""The Up Next Banner: when it's shown, drawing it, its settings and preview,
and seeing it on the air."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ffmpeg as ff
from app import intro, upnext
from app.config import Settings
from app.logos import LOGO_DIR
from app.main import create_app
from app.markers import trimmed
from app.plex import PlexClient

from .fakeplex import FakePlex
from .test_e2e import assert_clean_stream, record, start_server
from .test_e2e_breaks import frames, make_station
from .test_intro import media
from .test_skipping import EP, MIN, FakeRun, S, credits, item, play
from .test_skipping import intro as intro_marker

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
HD = Settings(plex_url="http://plex.test", plex_token="token")  # 1280x720
LOGO = str(LOGO_DIR / "classic-tv.png")
FRAME_S = 1001 / 30000


# When it's shown ----------------------------------------------------------------


def test_the_banner_is_shown_in_the_part_of_the_program_it_falls_in():
    # (Each part airs from part_from_s into the program for part_s.)
    assert upnext.when(0, 1320, 1140, 10) == 1140
    assert upnext.when(90, 1110, 1020, 10) == 930  # counted from the part's start
    assert upnext.when(0, 90, 1020, 10) is None  # not in this part
    assert upnext.when(1030, 170, 1020, 10) is None  # due before this part: missed
    # Too near the end of the part (where credits are skipped, say): a
    # little earlier, so it's gone before the part ends.
    assert upnext.when(0, 1000, 998, 10) == 1000 - 10 - upnext.END_CLEAR_S
    assert upnext.when(0, 8, 2, 10) is None  # a part too short for it


class Recorder(FakeRun):
    """FakeRun, also keeping the banner over each part."""

    def __init__(self) -> None:
        super().__init__()
        self.banners: list[ff.Banner | None] = []

    def command(self, *args, banner=None, **kw):
        self.banners.append(banner)
        return super().command(*args, **kw)


@needs_ffmpeg
async def test_the_engine_draws_the_banner_and_puts_it_where_it_falls(monkeypatch, tmp_path):
    """Three minutes before the program ends, in whichever part of it that
    falls in; drawn while the program starts, at most once."""
    # The intro skipped, and the final credits: it airs 90 seconds, then 1110.
    it = trimmed(item(), [intro_marker(90 * S, 150 * S), credits(21 * MIN, EP, final=True)])
    banner = upnext.UpNext("Cheers", LOGO, 10, "large")
    run = Recorder()
    result = await play(monkeypatch, tmp_path, it, 0.0, 1200.0, run, lead_s=10, up_next=banner)
    assert result.completed
    first, second = run.banners
    assert first is None and second is not None
    assert (second.at_s, second.seconds, second.slide) == (1200 - 180 - 90, 10, True)
    picture = tmp_path / "data" / "upnext" / "1.png"
    assert second.path == str(picture) and picture.stat().st_size > 1000
    # Joined after it was due (tuned in late, say): not drawn at all.
    picture.unlink()
    run = Recorder()
    await play(monkeypatch, tmp_path, it, 1030.0, 170.0, run, lead_s=10, up_next=banner)
    assert run.banners == [None] and not picture.exists()


async def test_a_banner_that_isnt_drawn_in_time_is_left_out(monkeypatch, tmp_path):
    """The program never waits long for it: it plays without it, and the
    drawing is stopped."""
    drawing = []

    async def slow(*_args):
        drawing.append("started")
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            drawing.append("stopped")
            raise
        return (0, 0)

    monkeypatch.setattr(upnext, "draw", slow)
    banner = upnext.UpNext("Cheers", None, 5, "large")
    run = Recorder()
    result = await play(monkeypatch, tmp_path, item(), 1100.0, 220.0, run, lead_s=1, up_next=banner)
    assert result.completed and run.banners == [None]
    assert drawing == ["started", "stopped"]


@needs_ffmpeg
async def test_a_banner_that_cant_be_drawn_is_left_out(monkeypatch, tmp_path, caplog):
    banner = upnext.UpNext("Cheers", "/gone/logo.png", 5, "large")
    run = Recorder()
    result = await play(
        monkeypatch, tmp_path, item(), 1100.0, 220.0, run, lead_s=10, up_next=banner
    )
    assert result.completed and run.banners == [None]
    assert "Drawing an Up Next Banner failed" in caplog.text


def test_only_a_corner_logo_there_all_along_is_taken_over():
    logo = ff.Watermark(logo="/app/logos/classic-tv.png", position="bottom-left", size="medium")
    assert upnext.corner_logo(HD, logo) == ff.mark_size(HD, logo) == round(720 * 0.13 * 0.75)
    for other in (
        replace(logo, until_s=30.0),  # at the start only: gone by then
        replace(logo, position="bottom-right"),
        replace(logo, logo=None, text="Rerun Road"),
        replace(logo, clock="12"),
        None,
    ):
        assert upnext.corner_logo(HD, other) is None


# Drawing it ---------------------------------------------------------------------


def pixels(path: Path) -> tuple[int, int, bytes]:
    """(width, height, RGBA bytes) of a picture."""
    probed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    info = json.loads(probed)["streams"][0]
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return info["width"], info["height"], raw


@needs_ffmpeg
def test_the_banner_is_drawn_in_the_logos_colours_at_each_size(tmp_path):
    colours = asyncio.run(intro.colours(HD, LOGO))
    dark = bytes.fromhex(colours[0])
    shapes = {}
    for size in upnext.SIZES:
        out = tmp_path / f"{size}.png"
        banner = upnext.UpNext("The Andy Griffith Show", LOGO, 10, size)
        args, (x, y) = upnext.banner_command(HD, banner, colours, out)
        subprocess.run(args, check=True)
        w, h, raw = pixels(out)
        shapes[size] = (w, h)

        def at(x: int, y: int, w: int = w, raw: bytes = raw) -> bytes:
            return raw[(y * w + x) * 4 : (y * w + x) * 4 + 4]

        room = upnext._shadow_room(HD, size)
        assert at(0, 0)[3] == 0 and at(room, room)[3] < 128  # see-through, rounded corners
        inside = at(room + 3, h // 2)  # the panel's left edge, beside the logo
        assert inside[3] > 200, size
        assert all(abs(a - b) < 24 for a, b in zip(inside[:3], dark, strict=True)), size
        # In the bottom-left corner, as far in as a corner logo would be.
        margin_x, margin_y = ff.corner_margins(HD)
        assert abs(x + room - margin_x) <= 1 and abs(y + h - room - (720 - margin_y)) <= 1
    assert shapes["small"] < shapes["medium"] < shapes["large"]
    # A long title takes two lines (the banner is taller), not the screen.
    out = tmp_path / "long.png"
    title = "The Lord of the Rings: The Fellowship of the Ring"
    banner = upnext.UpNext(title, LOGO, 10, "large")
    subprocess.run(upnext.banner_command(HD, banner, colours, out)[0], check=True)
    w, h, _ = pixels(out)
    room = upnext._shadow_room(HD, "large")
    assert h > shapes["large"][1] and w <= HD.video_width * 0.6 + 2 * room


def test_long_titles_are_set_on_two_even_lines_or_cut_short():
    def same(v: float) -> int:
        return round(v)

    assert upnext._title("Cheers", 500, same) == (["Cheers"], 32)
    lines, size = upnext._title("The Lord of the Rings: The Fellowship of the Ring", 500, same)
    assert lines == ["The Lord of the Rings:", "The Fellowship of the Ring"] and size <= 26
    lines, size = upnext._title(" ".join(["Supercalifragilistic"] * 12), 500, same)
    assert len(lines) == 2 and lines[1].endswith("…") and size == 21


def test_whats_in_the_bottom_left_corner_makes_way_for_the_banner():
    """Fading out as the banner comes in, and back as it goes."""
    banner = ff.Banner("/data/upnext/1.png", 30.0, 10, 13, 562, slide=False)
    starts, ends = ff.banner_times(banner)
    assert abs(starts - 30) < 0.02 and abs(ends - starts - 10) < 0.02
    logo = ff.Watermark(logo="/app/logos/classic-tv.png", position="bottom-left")
    corner = ff._video_filter(HD, watermark=logo, banner=banner).split("[wm]")[0]
    back = ends - ff.BANNER_OUT_S
    assert f"fade=t=out:st={starts:.3f}:d={ff.BANNER_IN_S}" in corner
    assert f"fade=t=in:st={back:.3f}:d={ff.BANNER_OUT_S}" in corner
    # Shown only at the start (and gone by then, here): the same, harmlessly.
    assert "fade=t=in" in ff._video_filter(HD, watermark=replace(logo, until_s=30.0), banner=banner)
    for elsewhere in ("bottom-right", "top-left"):
        moved = replace(logo, position=elsewhere)
        assert "fade" not in ff._video_filter(HD, watermark=moved, banner=banner).split("[wm]")[0]
    for mark in (ff.Watermark(text="Rerun Road"), ff.Watermark(clock="12")):
        written = ff._video_filter(
            HD, watermark=replace(mark, position="bottom-left"), banner=banner
        )
        assert f"clip(min((t-{starts:.3f})/{ff.BANNER_IN_S}" in written
    # Nothing in the corner, or no banner: as before.
    assert "fade" not in ff._video_filter(HD, watermark=logo)
    assert "movie=" not in ff._video_filter(HD)


def middle(path: Path, box: tuple[int, int, int, int], weight) -> tuple[float, float]:
    """Where something is in an area (x0, y0, x1, y1) of a picture: the
    middle of its pixels, each counted by weight(r, g, b) (so a fainter copy
    of the same shape in the same place has the same middle)."""
    w, _, raw = pixels(path)
    x0, y0, x1, y1 = box
    total = sx = sy = 0.0
    for y in range(y0, y1):
        for x in range(x0, x1):
            n = 4 * (y * w + x)
            counted = weight(raw[n], raw[n + 1], raw[n + 2])
            total, sx, sy = total + counted, sx + counted * x, sy + counted * y
    assert total, "nothing there"
    return sx / total, sy / total


def magenta(r: int, g: int, b: int) -> int:
    """How magenta a pixel is (the banner's panel, darkly tinted with the
    logo's colour, doesn't count)."""
    return max(0, min(r - g, b - g) - 100)


def block_logo(folder: Path, wide: bool = False) -> Path:
    """A logo: a magenta block in a see-through square (or, `wide`, in a
    picture four times as wide as it's tall, as a show's logo from Plex is
    kept: its middle a quarter and half of the way in)."""
    logo = folder / "logo.png"
    block, pad = ("448x160", "1024:256:32:48") if wide else ("256x192", "512:512:96:160")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=magenta:s={block},format=rgba",
         "-vf", f"pad={pad}:color=black@0", "-frames:v", "1", str(logo)],
        check=True,
    )  # fmt: skip
    return logo


def corner_box(mark: ff.Watermark) -> tuple[int, int, int, int]:
    """Where the corner logo is, with a little room around it."""
    margin_x, margin_y = ff.corner_margins(HD)
    assert mark.logo
    w, h = ff.logo_box(mark.logo, ff.mark_size(HD, mark))
    return margin_x - 4, 720 - margin_y - h - 4, margin_x + w + 4, 720 - margin_y + 4


def frames_of(graph: str, numbers: tuple[int, ...], folder: Path) -> list[Path]:
    """Those frames of a filter graph, as pictures."""
    picked = "+".join(f"eq(n,{n})" for n in numbers)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-filter_complex", f"{graph},select='{picked}'",
         "-fps_mode", "passthrough", "-frames:v", str(len(numbers)), str(folder / "f%d.png")],
        check=True,
    )  # fmt: skip
    return [folder / f"f{n}.png" for n in range(1, len(numbers) + 1)]


SCREEN = f"color=c={{}}:s=1280x720:r={ff.FPS_NUM}/{ff.FPS_DEN},format=yuv420p"


@needs_ffmpeg
@pytest.mark.parametrize("wide", [False, True], ids=["square", "wide"])
def test_the_banners_logo_lands_exactly_on_the_corner_logo(tmp_path, wide):
    """The corner logo fades into the banner's own logo, drawn the same size
    in exactly the same place, and back again: a square one, or one in its
    own shape."""
    logo = block_logo(tmp_path, wide)
    for mark_size, size in (("large", "large"), ("medium", "small"), ("small", "large")):
        mark = ff.Watermark(logo=str(logo), position="bottom-left", size=mark_size)
        banner = upnext.UpNext("Cheers", str(logo), 3, size, upnext.corner_logo(HD, mark))
        picture = tmp_path / "banner.png"
        where = asyncio.run(upnext.draw(HD, banner, picture, 30))
        assert where is not None
        on_air = upnext.on_air(banner, picture, where, 1.0)
        assert not on_air.slide
        # Before the banner, while it's up, and after.
        graph = ff.with_overlays(HD, SCREEN.format("gray"), mark, on_air)
        shots = frames_of(graph, (10, 75, 150), tmp_path)
        before, up, after = (middle(shot, corner_box(mark), magenta) for shot in shots)
        # Well within a pixel (one out would be 1 apart).
        assert abs(before[0] - up[0]) < 0.4 and abs(before[1] - up[1]) < 0.4, (mark_size, size)
        assert before == after
        # The block's middle, in the corner logo's box.
        x0, y0, x1, y1 = corner_box(mark)
        w, h = x1 - x0 - 8, y1 - y0 - 8
        across, down = (0.25, 0.5) if wide else (224 / 512, 256 / 512)
        assert abs(before[0] - (x0 + 4 + w * across)) < 1
        assert abs(before[1] - (y0 + 4 + h * down)) < 1
        if wide:
            assert (w, h) == (2 * ff.mark_size(HD, mark), round(ff.mark_size(HD, mark) / 2))


@needs_ffmpeg
def test_a_white_corner_logo_is_exactly_where_it_is_in_colour(tmp_path):
    """(So the banner's logo lands exactly on it too.)"""
    logo = block_logo(tmp_path)
    found = []
    for style in ("color", "white"):
        mark = ff.Watermark(logo=str(logo), position="bottom-left", style=style)
        # On black, where the white logo's dark edge doesn't show.
        (shot,) = frames_of(
            ff.with_overlays(HD, SCREEN.format("black"), mark, None), (0,), tmp_path
        )
        found.append(middle(shot, corner_box(mark), lambda r, g, b: r))
    (cx, cy), (wx, wy) = found
    assert abs(cx - wx) < 0.2 and abs(cy - wy) < 0.2


# Its settings and preview -------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * 60_000)
    fp.add_episode("202", "100", 1, 2, "Ep 2", "/x/2.mkv", 22 * 60_000)
    app = create_app(
        Settings(
            plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
            video_width=640, video_height=360,
        ),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )  # fmt: skip
    with TestClient(app) as c:
        yield c


def new(client, number, **extra):
    body = {"number": number, "sources": [{"type": "show", "ratingKey": "100"}], **extra}
    return client.post("/api/channels", json=body)


def test_the_banners_settings_are_kept_and_checked(client):
    assert new(client, 1, upNextSeconds=7).status_code == 400
    assert new(client, 1, upNextSize="huge").status_code == 400
    made = new(client, 1, upNextSeconds=5, upNextSize="small").json()
    assert (made["upNextSeconds"], made["upNextSize"]) == (5, "small")
    edited = client.put(
        f"/api/channels/{made['id']}",
        json={"number": 1, "sources": made["sources"], "upNextSeconds": 0},
    ).json()
    assert (edited["upNextSeconds"], edited["upNextSize"]) == (0, "small")


@needs_ffmpeg
def test_the_editor_can_preview_the_banner(client, tmp_path):
    made = new(client, 4, logo="classic-tv").json()
    body = {"channelId": made["id"], "logo": "classic-tv", "seconds": 3, "size": "large"}
    resp = client.post("/api/upnext/preview", json=body)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "video/mp4" and resp.content[4:8] == b"ftyp"
    video = tmp_path / "preview.mp4"
    video.write_bytes(resp.content)
    length = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert abs(float(length) - (3 + 2 * upnext.PREVIEW_LEAD_S)) < 0.1
    # In the bottom-left corner while it's up (the panel is dark), and not before.
    corner = [y for y, _, _ in frames(video, "6:20:24:308")]
    assert corner[3] > 80 and max(corner[50:95]) < 60  # (it comes in at 1s, out at 4s)
    for bad in ({"seconds": 0}, {"seconds": 4}, {"size": "huge"}, {"watermarkPosition": "mid"}):
        assert client.post("/api/upnext/preview", json={**body, **bad}).status_code == 400
    # With the logo in the bottom-left corner too (which makes way for it).
    corner = {"watermark": "logo", "watermarkPosition": "bottom-left", "watermarkSize": "small"}
    assert client.post("/api/upnext/preview", json={**body, **corner}).status_code == 200
    assert not list((tmp_path / "data" / "upnext").iterdir())  # nothing left behind


# On the air ---------------------------------------------------------------------


@needs_ffmpeg
async def test_the_banner_comes_up_before_the_program_ends(tmp_path, monkeypatch):
    """BEFORE_END_S before the end of the episode, for its length, over the
    program (here, 8 seconds before the end of a 20-second episode)."""
    monkeypatch.setattr(upnext, "BEFORE_END_S", 8.0)
    plex = media(tmp_path, 20)
    base, _app, _settings, srv, task = await start_server(
        tmp_path, plex, media_dir=str(tmp_path / "media")
    )
    try:
        station = await make_station(base, logo="classic-tv", upNextSeconds=3, upNextSize="large")
        assert (station["upNextSeconds"], station["upNextSize"]) == (3, "large")
        data = await record(f"{base}/stream/5", 22)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "upnext.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    # The picture's middle (yellow, then cyan: the next episode), and the
    # banner's left edge (dark while it's up).
    middle = [u for _, u, _ in frames(out, "40:40:300:160")]
    corner = [y for y, _, _ in frames(out, "6:20:24:308")]
    yellow_ends = next(n for n, u in enumerate(middle) if u > 100)  # cyan's U is high
    # Over the yellow episode, whose Y is 209:
    up = [n for n, y in enumerate(corner[:yellow_ends]) if y < 200]  # any of it
    assert up, "the banner never came up"
    assert up == list(range(up[0], up[-1] + 1))  # once, without a break
    assert abs(len(up) * FRAME_S - 3) < 0.2
    assert abs((yellow_ends - up[0]) * FRAME_S - 8) < 0.2
    shown = [n for n in up if corner[n] < 60]  # all of it, between its fades
    assert abs(len(shown) * FRAME_S - (3 - ff.BANNER_IN_S - ff.BANNER_OUT_S)) < 0.3
    assert (tmp_path / "data" / "upnext" / f"{station['id']}.png").is_file()
