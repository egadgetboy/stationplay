"""HDR programs and Dolby Vision: an HDR picture is turned into an ordinary
one as it plays, so it isn't washed out; a Dolby Vision file with no
ordinary picture inside (profile 5) is kept off the air."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import ffmpeg as ff
from app import jobs
from app.breaks import FillerLibrary
from app.config import Settings
from app.db import Item
from app.main import create_app
from app.plex import PlexClient
from app.scanner import quick_check

from .dovi import add_dolby_vision
from .fakeplex import FakePlex
from .test_breaks import library
from .test_e2e import assert_clean_stream, record, start_server

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
needs_x265 = pytest.mark.skipif(
    "libx265" not in subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True
    ).stdout if shutil.which("ffmpeg") else True,
    reason="needs ffmpeg with libx265",
)  # fmt: skip

SMALL = Settings(plex_url="", plex_token="", video_width=320, video_height=180)
# The picture: colour bars and a moving gradient.
PICTURE = "testsrc2=s=320x180:r=10"


def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args], check=True)


def sdr_clip(path: Path, seconds: float = 1.0, sound: bool = True) -> Path:
    extra = ["-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-c:a", "aac"] if sound else []
    run(
        "-f", "lavfi", "-i", f"{PICTURE}:d={seconds}", *extra, "-t", str(seconds),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path),
    )  # fmt: skip
    return path


def hdr_clip(path: Path, transfer: str, seconds: float = 1.0, sound: bool = True) -> Path:
    """The same picture as sdr_clip's, as HDR the way it's usually made: its
    white at the brightness HDR puts ordinary white at (203 nits)."""
    tag = {"smpte2084": "smpte2084", "arib-std-b67": "arib-std-b67"}[transfer]
    extra = ["-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-c:a", "aac"] if sound else []
    run(
        "-f", "lavfi", "-i", f"{PICTURE}:d={seconds}", *extra, "-t", str(seconds),
        "-vf", "zscale=tin=bt709:pin=bt709:min=bt709:rin=tv:t=" + transfer
        + ":p=bt2020:m=bt2020nc:r=tv:npl=203,format=yuv420p10le",
        "-c:v", "libx265", "-preset", "ultrafast",
        "-x265-params", f"log-level=error:colorprim=bt2020:transfer={tag}:colormatrix=bt2020nc",
        "-tag:v", "hvc1", str(path),
    )  # fmt: skip
    return path


def dolby_vision_clip(path: Path, profile: int, compatibility: int) -> Path:
    """An HDR10 file that says it's Dolby Vision `profile` (an MP4, with its
    index at the end: see dovi.py)."""
    hdr_clip(path.with_suffix(".mkv"), "smpte2084")
    run("-i", str(path.with_suffix(".mkv")), "-c", "copy", "-tag:v", "hvc1", str(path))
    add_dolby_vision(path, profile, compatibility)
    return path


def looks(path: Path) -> tuple[float, float]:
    """(average brightness, average saturation) of a video's picture."""
    out = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path),
            "-vf", "scale=320:180,format=yuv420p,signalstats,metadata=print:file=-",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    y = [float(line.split("=")[1]) for line in out.splitlines() if "signalstats.YAVG=" in line]
    s = [float(line.split("=")[1]) for line in out.splitlines() if "signalstats.SATAVG=" in line]
    return sum(y) / len(y), sum(s) / len(s)


async def played(settings: Settings, source: Path, out: Path, tone_map: bool) -> Path:
    """`source` played as a station plays it, into `out` (MPEG-TS)."""
    probe = await ff.probe(settings, str(source))
    assert probe.ok, probe.error
    args = ff.program_command(
        settings, str(source), 0.0, 1.0, 10.0, 10.0, probe.audio_index, "Test",
        source_aspect=probe.display_aspect, video_index=probe.video_index,
        tone_map=ff.to_sdr(probe) if tone_map else "",
    )  # fmt: skip
    args[args.index("pipe:1")] = str(out)
    proc = await asyncio.create_subprocess_exec(*args, stderr=asyncio.subprocess.DEVNULL)
    assert await asyncio.wait_for(proc.wait(), 60) == 0
    return out


@needs_x265
async def test_the_probe_tells_hdr_and_dolby_vision_apart(tmp_path):
    sdr = await ff.probe(SMALL, str(sdr_clip(tmp_path / "sdr.mkv")))
    assert sdr.ok and sdr.hdr is None and sdr.dolby_vision is None and not sdr.dolby_vision_only
    pq = await ff.probe(SMALL, str(hdr_clip(tmp_path / "pq.mkv", "smpte2084")))
    assert pq.hdr == "smpte2084" and (pq.primaries, pq.matrix) == ("bt2020", "bt2020nc")
    assert not pq.full_range and not pq.dolby_vision_only
    hlg = await ff.probe(SMALL, str(hdr_clip(tmp_path / "hlg.mkv", "arib-std-b67")))
    assert hlg.hdr == "arib-std-b67"
    # Profile 5 has no ordinary picture inside; 8.1 has HDR10's, 8.4 HLG's.
    five = await ff.probe(SMALL, str(dolby_vision_clip(tmp_path / "dv5.mp4", 5, 0)))
    assert five.ok and five.dolby_vision == 5 and five.dolby_vision_only
    eight = await ff.probe(SMALL, str(dolby_vision_clip(tmp_path / "dv8.mp4", 8, 1)))
    assert eight.dolby_vision == 8 and not eight.dolby_vision_only and eight.hdr == "smpte2084"
    hlg8 = await ff.probe(SMALL, str(dolby_vision_clip(tmp_path / "dv84.mp4", 8, 4)))
    assert not hlg8.dolby_vision_only
    # AV1's profile 10 is like 5 only without a compatible picture.
    av1 = await ff.probe(SMALL, str(dolby_vision_clip(tmp_path / "dv10.mp4", 10, 0)))
    assert av1.dolby_vision == 10 and av1.dolby_vision_only
    av1_hdr10 = await ff.probe(SMALL, str(dolby_vision_clip(tmp_path / "dv101.mp4", 10, 1)))
    assert not av1_hdr10.dolby_vision_only
    assert "profile 5" in ff.dolby_vision_reason(five)


async def test_an_ffprobe_that_cant_ask_about_dolby_vision_still_works(tmp_path, monkeypatch):
    """An ffprobe that doesn't know the Dolby Vision record (older or newer
    than this one) refuses the whole question: the probe asks again without
    it, and from then on, so every file still opens."""
    real = shutil.which("ffprobe")
    fake = tmp_path / "ffprobe"
    fake.write_text(
        "#!/bin/sh\n"
        'case "$*" in *stream_side_data*) '
        "echo \"No match for section 'stream_side_data'\" >&2; exit 1;; esac\n"
        f'exec {real} "$@"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setattr(ff, "_asks_dolby_vision", True)
    settings = replace(SMALL, ffprobe_path=str(fake))
    clip = sdr_clip(tmp_path / "sdr.mkv")
    for _ in range(2):
        got = await ff.probe(settings, str(clip))
        assert got.ok and abs((got.duration_s or 0) - 1) < 0.2 and got.dolby_vision is None
    assert ff._asks_dolby_vision is False


async def test_tone_mapping_is_tried_before_its_used(tmp_path):
    assert await ff.tone_mapping_problem(SMALL) is None
    broken = tmp_path / "ffmpeg"
    broken.write_text("#!/bin/sh\necho \"No such filter: 'zscale'\" >&2\nexit 1\n")
    broken.chmod(0o755)
    problem = await ff.tone_mapping_problem(replace(SMALL, ffmpeg_path=str(broken)))
    assert problem and "zscale" in problem


def test_the_hdr_filters_come_after_the_picture_is_its_final_size():
    hdr = ff.ProbeResult(ok=True, hdr="arib-std-b67", primaries="bt709", matrix="bt709")
    chain = ff.to_sdr(hdr)
    assert chain.startswith("zscale=tin=arib-std-b67:pin=bt709:min=bt709:rin=tv:t=linear")
    assert "tonemap=tonemap=mobius" in chain and chain.endswith("r=tv")
    assert ff.to_sdr(ff.ProbeResult(ok=True)) == ""
    assert "rin=pc" in ff.to_sdr(replace(hdr, full_range=True))
    args = ff.program_command(SMALL, "/x.mkv", 0, 5, 10, 1, 0, "T", tone_map=chain)
    vf = args[args.index("-vf") + 1]
    assert vf.index("pad=") < vf.index(chain) < vf.index("fps=")
    plain = ff.program_command(SMALL, "/x.mkv", 0, 5, 10, 1, 0, "T")
    assert "zscale" not in plain[plain.index("-vf") + 1]


@needs_x265
@pytest.mark.parametrize("transfer", ["smpte2084", "arib-std-b67"])
async def test_an_hdr_program_plays_in_its_true_colours(tmp_path, transfer):
    reference = await played(SMALL, sdr_clip(tmp_path / "sdr.mkv"), tmp_path / "sdr.ts", False)
    hdr = hdr_clip(tmp_path / "hdr.mkv", transfer)
    fixed = await played(SMALL, hdr, tmp_path / "fixed.ts", True)
    as_was = await played(SMALL, hdr, tmp_path / "as_was.ts", False)
    assert_clean_stream(fixed)
    (y, s), (y_hdr, s_hdr), (y_was, s_was) = looks(reference), looks(fixed), looks(as_was)
    print(
        f"\nSDR {y:.0f}/{s:.0f}, HDR made ordinary {y_hdr:.0f}/{s_hdr:.0f}, as was {y_was:.0f}/{s_was:.0f}"
    )
    # Shown as it is, an HDR picture is washed out: its colours faded.
    assert s_was < 0.65 * s
    # Made ordinary, it looks like the SDR picture it was made from.
    assert abs(y_hdr - y) < 0.12 * y and s_hdr > 0.75 * s


@needs_x265
async def test_the_file_checks_take_dolby_vision_5_off_the_air(tmp_path):
    five = await ff.probe(SMALL, str(dolby_vision_clip(tmp_path / "dv5.mp4", 5, 0)))
    verdict = await quick_check(None, str(tmp_path / "dv5.mp4"), five)  # type: ignore[arg-type]
    assert verdict.result == "unsupported" and "Dolby Vision profile 5" in verdict.reason


@needs_x265
async def test_a_dolby_vision_5_commercial_is_left_out(tmp_path):
    ctx, _plex = library(tmp_path)
    folder = tmp_path / "tv/commercials"
    folder.mkdir(parents=True)
    sdr_clip(folder / "fine.mkv", 4)
    hdr_clip(tmp_path / "long.mkv", "smpte2084", 4)
    run("-i", str(tmp_path / "long.mkv"), "-c", "copy", "-tag:v", "hvc1", str(folder / "dv5.mp4"))
    add_dolby_vision(folder / "dv5.mp4", 5, 0)
    fillers = FillerLibrary(ctx)
    await fillers.refresh()
    assert [Path(c.path).name for c in fillers.pool("commercials")] == ["fine.mkv"]


@pytest.fixture
def client(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * 60_000)
    app = create_app(
        Settings(
            plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
            video_width=640, video_height=360,
        ),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )  # fmt: skip
    with TestClient(app) as c:
        yield c


@needs_x265
def test_a_dolby_vision_5_bumper_is_turned_away(client, tmp_path):
    clip = dolby_vision_clip(tmp_path / "dv5.mp4", 5, 0)
    got = client.post("/api/bumpers?name=Mine.mp4", content=clip.read_bytes())
    assert got.status_code == 400 and "Dolby Vision profile 5" in got.json()["detail"]


@needs_x265
def test_an_hdr_bumper_is_made_ordinary(client, tmp_path):
    clip = hdr_clip(tmp_path / "pq.mkv", "smpte2084", 3)
    made = client.post("/api/bumpers?name=Mine.mkv", content=clip.read_bytes())
    assert made.status_code == 201, made.text
    copy = tmp_path / "copy.mp4"
    copy.write_bytes(client.get(f"/bumpers/{made.json()['id']}.mp4").content)
    reference = tmp_path / "sdr.mkv"
    sdr_clip(reference, 3)
    (y, s), (y_hdr, s_hdr) = looks(reference), looks(copy)
    assert s_hdr > 0.75 * s and abs(y_hdr - y) < 0.12 * y


def test_retry_puts_a_dolby_vision_5_program_back_on_the_air(client):
    ctx = client.app.state.ctx
    item = Item(0, 0, 1000, "201", "episode", "Ep 1", file_path="/x/1.mkv")
    ctx.broken.record(item, "it's Dolby Vision profile 5", 1, "/x/1.mkv", 123, "unsupported")
    assert ctx.db.scan("201") is None  # (taken off as it played: never checked)
    assert client.delete("/api/broken/201").status_code == 204
    record = ctx.db.scan("201")
    assert record is not None and record.kept and record.file == "/x/1.mkv"
    # A broken file put back on the air isn't left alone by the checks.
    other = Item(1, 1000, 1000, "202", "episode", "Ep 2", file_path="/x/2.mkv")
    ctx.broken.record(other, "it won't open", 1, "/x/2.mkv", 5)
    assert client.delete("/api/broken/202").status_code == 204
    assert ctx.db.scan("202") is None


@needs_x265
async def test_a_dolby_vision_5_program_is_replaced_as_it_comes_up(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", False)  # (no checks first)
    d = tmp_path / "media"
    d.mkdir()
    plex = FakePlex()
    plex.add_show("100", "Show")
    dolby_vision_clip(d / "dv5.mp4", 5, 0)
    # (Long enough that tuning in finds it on: it's never played anyway.)
    plex.add_episode("201", "100", 1, 1, "Vision", str(d / "dv5.mp4"), 5000)
    sdr_clip(d / "fine.mkv", 6)
    plex.add_episode("202", "100", 1, 2, "Fine", str(d / "fine.mkv"), 6000)
    base, app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={
                    "number": 5, "orderMode": "rotate", "introSeconds": 0, "upNextSeconds": 0,
                    "watermark": "off", "sources": [{"type": "show", "ratingKey": "100"}],
                },
            )  # fmt: skip
            assert made.status_code == 201, made.text
            data = await record(f"{base}/stream/5", 6)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "out.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    entries = app.state.ctx.broken.entries()
    assert [(e["ratingKey"], e["problem"]) for e in entries] == [("201", "unsupported")]
    assert "Dolby Vision profile 5" in entries[0]["reason"] and entries[0]["failures"] == 1
    # It wasn't tried again first (playing it again would change nothing).
    assert not [r for r in caplog.records if "resuming it" in r.getMessage()]
