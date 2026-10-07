"""Files like those in real Plex libraries through one station with
everything on: Blu-ray and DVD rips, 4K HDR, an old AVI, WebM, an MP4 with
its own subtitles, anime with styled subtitles and a Japanese and English
soundtrack. Each plays, the stream stays clean, and the subtitles inside
the files are read out and drawn. (A few minutes: set STATIONPLAY_REALWORLD=1.)"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from app import jobs

from .fakeplex import FakePlex
from .test_e2e import assert_clean_stream, media_seconds, record, start_server

pytestmark = pytest.mark.skipif(
    not os.environ.get("STATIONPLAY_REALWORLD"), reason="set STATIONPLAY_REALWORLD=1 for this run"
)
T = "20"


def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args], check=True)


def srt(path: Path, lines: list[tuple[str, str, str]]) -> Path:
    path.write_text("".join(f"{n}\n{a} --> {b}\n{t}\n\n" for n, (a, b, t) in enumerate(lines, 1)))
    return path


def pattern(size: str, rate: str) -> list[str]:
    return ["-f", "lavfi", "-i", f"testsrc2=s={size}:r={rate}"]


def tone(layout: str) -> list[str]:
    return ["-f", "lavfi", "-i", f"sine=f=330:sample_rate=48000,aformat=channel_layouts={layout}"]


STYLED = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,48,&H0000FFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,10,10,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:05.00,Default,,0,0,0,,{\\i1}Styled line{\\i0}
"""


def library(d: Path) -> list[tuple[str, str]]:
    """The files, as (file name, title)."""
    full = srt(d / "full.srt", [("00:00:02,000", "00:00:06,000", "Full subtitle line")])
    forced = srt(d / "forced.srt", [("00:00:04,000", "00:00:08,000", "FORCED line")])
    styled = d / "styled.ass"
    styled.write_text(STYLED)
    # Blu-ray rip: H.264 High 1080p 23.976, AC3 5.1 and DTS 5.1, full and forced SRT.
    run(*pattern("1920x1080", "24000/1001"), *tone("5.1"), "-i", str(full), "-i", str(forced),
        "-t", T, "-map", "0:v", "-map", "1:a", "-map", "1:a", "-map", "2", "-map", "3",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a:0", "ac3", "-c:a:1", "dca", "-strict", "-2", "-c:s", "srt",
        "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=eng",
        "-metadata:s:s:0", "language=eng", "-metadata:s:s:1", "language=eng",
        "-disposition:s:1", "forced", str(d / "Bluray Rip (2010).mkv"))  # fmt: skip
    # 4K HDR10: HEVC Main 10 2160p, PQ in BT.2020, E-AC3 5.1.
    run(*pattern("3840x2160", "24000/1001"), *tone("5.1"), "-t", "12", "-map", "0:v", "-map", "1:a",
        "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le",
        "-x265-params", "log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc",
        "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc",
        "-c:a", "eac3", str(d / "UHD HDR (2021).mkv"))  # fmt: skip
    # DVD: MPEG-2 480i, 16:9 anamorphic, AC3 2.0, in a program stream.
    run(*pattern("720x480", "30000/1001"), *tone("stereo"), "-t", T, "-map", "0:v", "-map", "1:a",
        "-vf", "setsar=32/27,interlace", "-c:v", "mpeg2video", "-b:v", "6M",
        "-flags", "+ilme+ildct", "-c:a", "ac3", "-f", "dvd", str(d / "DVD Episode.mpg"))  # fmt: skip
    # TV rip: MP4, H.264 720p, AAC, its own (mov_text) subtitles.
    run(*pattern("1280x720", "30000/1001"), *tone("stereo"), "-i", str(full), "-t", T,
        "-map", "0:v", "-map", "1:a", "-map", "2", "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
        str(d / "TV Rip S02E03.mp4"))  # fmt: skip
    # An old AVI: XviD, MP3.
    run(*pattern("640x480", "25"), *tone("stereo"), "-t", T, "-map", "0:v", "-map", "1:a",
        "-c:v", "mpeg4", "-vtag", "XVID", "-q:v", "4", "-c:a", "libmp3lame",
        str(d / "Old Show S01E02.avi"))  # fmt: skip
    # WebM: VP9, Opus.
    run(*pattern("1280x720", "30"), *tone("stereo"), "-t", T, "-map", "0:v", "-map", "1:a",
        "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "2M",
        "-c:a", "libopus", str(d / "Web Video (2019).webm"))  # fmt: skip
    # Anime: H.264 10-bit 1080p, Japanese then English sound, styled ASS.
    run(*pattern("1920x1080", "24000/1001"), *tone("stereo"), "-i", str(styled), "-t", T,
        "-map", "0:v", "-map", "1:a", "-map", "1:a", "-map", "2", "-c:v", "libx264",
        "-preset", "veryfast", "-pix_fmt", "yuv420p10le", "-c:a", "aac",
        "-metadata:s:a:0", "language=jpn", "-metadata:s:a:1", "language=eng", "-c:s", "ass",
        "-metadata:s:s:0", "language=eng", str(d / "Anime S01E01.mkv"))  # fmt: skip
    return [
        ("Anime S01E01.mkv", "Anime"), ("Bluray Rip (2010).mkv", "Bluray Rip"),
        ("DVD Episode.mpg", "DVD Episode"), ("Old Show S01E02.avi", "Old Show"),
        ("TV Rip S02E03.mp4", "TV Rip"), ("UHD HDR (2021).mkv", "UHD HDR"),
        ("Web Video (2019).webm", "Web Video"),
    ]  # fmt: skip


def duration_ms(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return int(float(json.loads(out)["format"]["duration"]) * 1000)


async def test_real_world_files_on_a_station_with_everything_on(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", False)
    d = tmp_path / "media"
    d.mkdir()
    files = library(d)
    plex = FakePlex()
    plex.add_section("2", "Movies", "movie")
    total_ms = 0
    for n, (name, title) in enumerate(files, start=1):
        ms = duration_ms(d / name)
        total_ms += ms + 3000  # (and its Station ID card)
        plex.add_movie(str(500 + n), title, str(d / name), ms, 2000 + n, "2")
    caplog.set_level(logging.INFO)
    base, app, settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=60) as client:
            made = await client.post(
                "/api/channels",
                json={
                    "number": 9, "orderMode": "rotate", "subtitles": "always", "introSeconds": 0,
                    "stationId": True, "idSeconds": 3, "upNextSeconds": 5, "watermark": "clock",
                    "sources": [{"type": "section", "key": "2", "sectionType": "movie", "title": "Movies"}],
                },
            )  # fmt: skip
            assert made.status_code == 201, made.text
            started = time.time()
            data = await record(f"{base}/stream/9", total_ms / 1000 + 5)
            elapsed = time.time() - started
            broken = app.state.ctx.broken.entries()
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "realworld.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert elapsed - 5 <= media_seconds(out) <= elapsed + 20
    assert broken == []
    warned = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warned, warned
    # The subtitles inside the files were read out: the Blu-ray's, the MP4's
    # and the anime's.
    said = " ".join(r.getMessage() for r in caplog.records)
    for name in ("Bluray Rip (2010).mkv", "TV Rip S02E03.mp4", "Anime S01E01.mkv"):
        assert f"Extracted the subtitles from {name}" in said, name
    assert len(list((settings.data_dir / "subtitles").glob("*.ass"))) == 3
