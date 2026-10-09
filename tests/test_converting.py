"""Copies StationPlay makes for a device that can't play a file as it is
(converting.py, keyframes.py, and playing them through applibrary.py):
where the pieces start, reading a file's keyframes from its index,
repackaged and converted copies played from the start and from anywhere,
and converting on the GPU, with the CPU behind it."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import applibrary, converting, hls, ondemand
from app import ffmpeg as ff
from app import gpu as gpu_module
from app.catalog import Media, Track
from app.config import Settings
from app.ffmpeg import CPU, Encoder, Subtitles
from app.gpu import GpuManager
from app.keyframes import keyframes
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg"
)
# A phone that plays MP4 and Matroska, H.264 and AAC only, and takes copies.
PHONE = {
    "containers": ["mp4", "mkv"],
    "video": [{"codec": "h264", "width": 1920, "height": 1080, "bitDepth": 8}],
    "hdr": [],
    "audio": ["aac"],
    "hls": ["ts"],
}
LENGTH_S = 20.0


# Where pieces start ---------------------------------------------------------------------


def test_a_repackaged_copys_pieces_start_at_keyframes():
    keys = [0.0, 2.0, 5.5, 6.0, 9.0, 13.0, 14.0, 19.5]
    assert converting.pieces_at(keys, 20.0) == (0.0, 6.0, 13.0)  # (19.5: a last half second)
    assert converting.pieces_at(keys, 25.0) == (0.0, 6.0, 13.0, 19.5)
    assert converting.pieces_at([0.04, 7.0], 30.0) == (0.04, 7.0)
    assert converting.pieces_every(20.0) == (0.0, 6.0, 12.0, 18.0)
    assert converting.pieces_every(18.5) == (0.0, 6.0, 12.0)  # (half a second: with the last)
    assert converting.lengths((0.04, 7.0), 30.0) == [7.0, 23.0]  # (the first from the start)
    assert converting.piece_for((0.0, 6.0, 13.0), 12.9) == 1


def test_the_playlist_lists_the_whole_program():
    plan = converting.Plan(
        method=converting.REPACKAGE, why=(), starts=(0.0, 6.0, 13.0), duration_s=20.0,
        audio=None, audio_codec="aac",
    )  # fmt: skip
    text = converting.playlist(plan, 41.5)
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in text and text.rstrip().endswith("#EXT-X-ENDLIST")
    assert "#EXT-X-START:TIME-OFFSET=41.500,PRECISE=YES" in text
    assert "#EXT-X-TARGETDURATION:7" in text
    assert [line for line in text.splitlines() if line.startswith("#EXTINF")] == [
        "#EXTINF:6.000,", "#EXTINF:7.000,", "#EXTINF:7.000,"
    ]  # fmt: skip
    assert "#EXT-X-START" not in converting.playlist(plan)


def test_how_a_copys_sound_and_size_are_chosen():
    dts = Track("1", "dts", "English", channels=6, default=True, index=1)
    aac = Track("2", "aac", "English", channels=2, index=2)
    assert converting.sound_for(aac, frozenset({"aac"}), False) == ("copy", 2)
    assert converting.sound_for(dts, frozenset({"aac", "ac3"}), False) == ("ac3", 6)
    assert converting.sound_for(dts, frozenset({"aac"}), False) == ("aac", 2)
    assert converting.sound_for(aac, frozenset({"aac"}), True) == ("aac", 2)  # (night mode)
    four_k = Media(container="mkv", video="hevc", width=3840, height=2160)
    assert converting.convert_size(four_k, 2160, None) == (1080, 8_000)
    assert converting.convert_size(four_k, 2160, 9_000) == (720, 4_000)
    assert converting.convert_size(four_k, 2160, 1_200) == (480, 1_000)
    small = Media(container="mkv", video="h264", width=640, height=360)
    assert converting.convert_size(small, 1080, None) == (360, 2_000)
    hevc = Media(container="mkv", video="hevc", width=1920, height=1080)
    assert converting.picture_copyable(hevc, [], frozenset({"ts", "ts-hevc"}))
    assert not converting.picture_copyable(hevc, [], frozenset({"ts"}))
    assert not converting.picture_copyable(hevc, ["its 10-bit picture"], frozenset({"ts-hevc"}))


# Real files ----------------------------------------------------------------------------


def make(path, *args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"testsrc2=size=320x180:rate=24:duration={LENGTH_S}", "-f", "lavfi", "-i",
         f"sine=frequency=440:sample_rate=48000:duration={LENGTH_S}", *args, str(path)],
        check=True,
    )  # fmt: skip


def first_times(data: bytes) -> tuple[float | None, float | None]:
    """The first picture's and sound's times in an MPEG-TS piece."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "packet=codec_type,pts_time",
         "-of", "json", "-"],
        input=data, capture_output=True, check=True,
    ).stdout  # fmt: skip
    packets = json.loads(out)["packets"]
    video = next((float(p["pts_time"]) for p in packets if p["codec_type"] == "video"), None)
    audio = next((float(p["pts_time"]) for p in packets if p["codec_type"] == "audio"), None)
    return video, audio


def picture_of(data: bytes) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,height", "-of", "json", "-"],
        input=data, capture_output=True, check=True,
    ).stdout  # fmt: skip
    return json.loads(out)["streams"][0]


@needs_ffmpeg
async def test_keyframes_come_from_the_files_own_index(tmp_path):
    kf = "0,2.5,4,7.5,11,12,16"
    make(tmp_path / "a.mkv", "-c:v", "libx264", "-x264-params", "keyint=500:scenecut=0",
         "-force_key_frames", kf, "-c:a", "aac")  # fmt: skip
    make(tmp_path / "a.mp4", "-c:v", "libx264", "-bf", "2", "-x264-params",
         "keyint=500:scenecut=0", "-force_key_frames", kf, "-c:a", "aac")  # fmt: skip
    for name, container in (("a.mkv", "mkv"), ("a.mp4", "mp4")):
        path = tmp_path / name

        async def read(offset: int, size: int, path=path) -> bytes:
            return path.read_bytes()[offset : offset + size]

        found = await keyframes(read, container)
        assert found is not None, name
        assert [round(t, 2) for t in found] == [0, 2.5, 4, 7.5, 11, 12, 16], name
    (tmp_path / "junk.mkv").write_bytes(b"not a video" * 100)

    async def junk(offset: int, size: int) -> bytes:
        return (tmp_path / "junk.mkv").read_bytes()[offset : offset + size]

    assert await keyframes(junk, "mkv") is None
    assert await keyframes(junk, "avi") is None  # (no index it can read)


@pytest.fixture
def library(tmp_path):
    fp = LibraryPlex()
    fp.add_section("2", "Movies", "movie")
    if shutil.which("ffmpeg"):
        movie = tmp_path / "movie.mkv"
        (tmp_path / "subs.srt").write_text("1\n00:00:01,000 --> 00:00:09,000\nHello there\n")
        make(movie, "-i", str(tmp_path / "subs.srt"), "-map", "0", "-map", "1", "-map", "2",
             "-c:v", "libx264", "-x264-params", "keyint=500:scenecut=0", "-force_key_frames",
             "0,3,7,9.5,14,17", "-c:a", "ac3", "-ac", "6", "-c:s", "srt")  # fmt: skip
        fp.add_movie("400", "A Copy", str(movie), int(LENGTH_S * 1000), section="2")
        fp.describe("400", audio="ac3", width=320, height=180)
        fp.add_subtitles("400", "srt", "English")
        # An episode whose sound is far quieter than the stations' (about -42 LUFS).
        episode = tmp_path / "episode.mkv"
        make(episode, "-c:v", "libx264", "-x264-params", "keyint=48:scenecut=0", "-c:a", "aac",
             "-af", "volume=-20dB")  # fmt: skip
        fp.add_show("500", "Quiet Show")
        fp.add_episode("501", "500", 1, 1, "Pilot", str(episode), int(LENGTH_S * 1000))
        fp.describe("501", width=320, height=180)
        # The same file again: a movie, which even sound never touches.
        fp.add_movie("402", "A Quiet Movie", str(episode), int(LENGTH_S * 1000), section="2")
        fp.describe("402", width=320, height=180)
    fp.add_show("510", "Another Show")
    fp.add_episode("511", "510", 1, 1, "In HEVC", "/tv/hevc.mkv", 60_000)
    fp.describe("511", video="hevc", width=1920, height=1080)
    fp.add_movie("401", "Dolby Vision", "/films/dv.mkv", 60_000, section="2")
    fp.describe("401", video="hevc", width=3840, height=2160, bitDepth=10,
                DOVIPresent=True, DOVIProfile=5)  # fmt: skip
    return fp


@pytest.fixture
def app(library, tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(
        settings, PlexClient("http://plex.test", "token", transport=library.transport())
    )
    app.state.ctx.play_transport = library.transport()
    return app


@needs_ffmpeg
def test_a_repackaged_copy_plays_from_the_start_and_from_anywhere(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        assert "convert" in home.get("/api/v1/server").json()["features"]
        # An app that doesn't take copies is told why it can't play it, as before.
        old = {k: v for k, v in PHONE.items() if k != "hls"}
        refused = home.post("/api/internal/play", json={"key": "400", "device": old})
        assert refused.status_code == 422
        played = home.post(
            "/api/internal/play", json={"key": "400", "device": PHONE, "startMs": 12_000}
        )
        assert played.status_code == 200, played.text
        answer = played.json()
        assert answer["method"] == "repackage"
        assert answer["why"] == ["its sound's format (Dolby Digital)"]
        assert answer["url"].endswith("/index.m3u8") and answer["audioTrack"] == "4002"
        listed = home.get(answer["url"])
        assert listed.headers["content-type"] == "application/vnd.apple.mpegurl"
        text = listed.text
        assert "#EXT-X-START:TIME-OFFSET=12.000" in text
        pieces = [line for line in text.splitlines() if line.startswith("piece-")]
        # (Its keyframes are at 0, 3, 7, 9.5, 14 and 17: pieces from 0, 7 and 14.)
        assert pieces == ["piece-0.ts", "piece-1.ts", "piece-2.ts"]
        here = answer["url"].rsplit("/", 1)[0]
        later = home.get(f"{here}/piece-2.ts")  # (a jump: made from there)
        assert later.status_code == 200 and later.content[:1] == b"\x47"
        video, audio = first_times(later.content)
        assert video == pytest.approx(14 + converting.TS_OFFSET_S, abs=0.01)
        assert audio is not None
        first = home.get(f"{here}/piece-0.ts")  # (and back to the start)
        assert first_times(first.content)[0] == pytest.approx(converting.TS_OFFSET_S, abs=0.05)
        assert picture_of(first.content)["codec_name"] == "h264"
        assert home.get(f"{here}/piece-9.ts").status_code == 404  # (past its end)
        assert home.post(answer["leave"]).status_code == 204
        assert home.get(f"{here}/piece-1.ts").status_code == 404


@needs_ffmpeg
def test_subtitles_drawn_in_and_a_smaller_picture_are_converted(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        played = home.post(
            "/api/internal/play", json={"key": "400", "device": PHONE, "subtitle": "4005"}
        )
        assert played.status_code == 200, played.text
        answer = played.json()
        assert (answer["method"], answer["drawnSubtitle"]) == ("convert", "4005")
        assert "its subtitles, drawn into the picture" in answer["why"]
        here = answer["url"].rsplit("/", 1)[0]
        text = home.get(answer["url"]).text
        assert "#EXT-X-INDEPENDENT-SEGMENTS" in text
        assert [line for line in text.splitlines() if line.startswith("#EXTINF")] == [
            "#EXTINF:6.000,", "#EXTINF:6.000,", "#EXTINF:6.000,", "#EXTINF:2.000,"
        ]  # fmt: skip
        piece = home.get(f"{here}/piece-1.ts")
        assert piece.status_code == 200
        assert picture_of(piece.content) == {"codec_name": "h264", "height": 180}
        assert first_times(piece.content)[0] == pytest.approx(16.0, abs=0.05)
        home.post(answer["leave"])
        smaller = home.post(
            "/api/internal/play",
            json={"key": "400", "device": PHONE, "maxKbps": 1500, "fit": True},
        ).json()
        assert smaller["method"] == "convert"
        assert smaller["why"][-1] == "a smaller picture, to fit the connection"
        assert smaller["bitrateKbps"] <= 1500
        home.post(smaller["leave"])


def test_what_cant_be_copied_says_why(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        tv = {**PHONE, "video": [{"codec": "hevc", "width": 3840, "height": 2160,
                                  "bitDepth": 10}, *PHONE["video"]]}  # fmt: skip
        refused = home.post("/api/internal/play", json={"key": "401", "device": tv})
        assert refused.status_code == 422
        assert refused.json()["why"] == ["its Dolby Vision profile 5 picture"]
        assert "can't make a copy" in refused.json()["detail"]


# Making copies: restarts, jumps back, failures and odd files ------------------------------


def converted(starts: int, length_s: float) -> converting.Plan:
    return converting.Plan(
        method=converting.CONVERT, why=(), starts=converting.pieces_every(length_s)[:starts],
        duration_s=length_s, audio=None, audio_codec="aac", height=180, kbps=800,
    )  # fmt: skip


async def test_only_the_newest_request_starts_ffmpeg_again(tmp_path, monkeypatch):
    """Two players' requests far apart don't keep restarting each other's
    ffmpeg: the older one waits out its time."""
    monkeypatch.setattr(converting, "WAIT_S", 2.0)
    starts = tmp_path / "starts"
    fake = tmp_path / "ffmpeg"
    fake.write_text(f"#!/bin/sh\necho start >> {starts}\nexec sleep 30\n")
    fake.chmod(0o755)
    copy = converting.Copy(str(fake), "file.mkv", converted(20, 120.0))
    try:
        first, far = await asyncio.gather(copy.piece(0), copy.piece(15))
        assert (first, far) == (None, None)
        assert len(starts.read_text().split()) <= 2
    finally:
        await copy.close()


async def test_a_copy_that_cant_be_made_is_given_up_on(tmp_path):
    copy = converting.Copy("ffmpeg", str(tmp_path / "gone.mkv"), converted(3, 18.0))
    try:
        for _ in range(converting.FAILURES_MOST + 1):
            assert await copy.piece(0) is None
        assert copy.broken and copy.failures == converting.FAILURES_MOST
        assert await copy.piece(1) is None  # (at once)
        assert not copy.active
    finally:
        await copy.close()


@needs_ffmpeg
async def test_jumping_back_past_whats_kept_makes_it_again(tmp_path):
    source = tmp_path / "long.mkv"
    await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc2=size=320x180:rate=24:duration=60", "-c:v", "libx264", "-preset",
         "ultrafast", str(source)],
        check=True,
    )  # fmt: skip
    copy = converting.Copy("ffmpeg", str(source), converted(10, 60.0))
    try:
        for n in range(9):
            assert await copy.piece(n) is not None, n
        assert 1 not in copy.ready  # (deleted, well behind)
        again = await copy.piece(1)
        assert again is not None
        assert first_times(again.read_bytes())[0] == pytest.approx(16.0, abs=0.05)
    finally:
        await copy.close()


@needs_ffmpeg
async def test_odd_files_still_make_whole_pieces(tmp_path):
    """An MPEG-TS recording (its times starting at 1.4 seconds), a picture
    starting late, and a picture shorter than the file's planned length."""
    ts = tmp_path / "recording.ts"
    await asyncio.to_thread(make, ts, "-c:v", "mpeg2video", "-c:a", "ac3")
    late = tmp_path / "late.mkv"
    await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc2=size=320x180:rate=24:duration=20", "-f", "lavfi", "-i",
         "sine=duration=20", "-filter_complex", "[0:v]setpts=PTS+0.6/TB[v]", "-map", "[v]",
         "-map", "1", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(late)],
        check=True,
    )  # fmt: skip
    for source, length in ((ts, LENGTH_S), (late, LENGTH_S), (late, 30.0)):
        copy = converting.Copy("ffmpeg", str(source), converted(10, length))
        try:
            for n in (0, 2):
                piece = await copy.piece(n)
                assert piece is not None, (source.name, n)
                assert first_times(piece.read_bytes())[0] == pytest.approx(
                    max(n * 6.0, 0.6 if source == late and n == 0 else 0) + 10, abs=0.1
                ), (source.name, n)
            if length > LENGTH_S:
                assert await copy.piece(3) is not None  # (the last, to the file's end)
                assert await copy.piece(4) is None and copy.end == 4
        finally:
            await copy.close()


# Converting on the GPU ------------------------------------------------------------------

VAAPI = Encoder("vaapi", "/dev/dri/renderD128")
NVENC = Encoder("nvidia", "1")
FAKE_GPU = str(Path(__file__).with_name("fake_gpu_ffmpeg.py"))


def part_at(part: list[str], args: list[str]) -> int:
    """Where `part` is in `args`, just as it is (-1: it isn't)."""
    return next(
        (i for i in range(len(args) - len(part) + 1) if args[i : i + len(part)] == part), -1
    )


def test_the_command_each_encoder_gets():
    """The CPU's as before. A GPU's set up and encoding as the stations' are
    (their proven command), but for the level and how often keyframes come;
    the CPU's filters first, and keyframes forced where the pieces start."""
    plan = replace(converted(4, 24.0), height=720, kbps=4_000, tone_map="tonemap=hable")
    keys = ["-force_key_frames", "12.000,18.000"]  # (from piece 1: where pieces 2 and 3 start)
    cpu = converting.command("ffmpeg", "/films/a.mkv", plan, 1)
    assert cpu == converting.command("ffmpeg", "/films/a.mkv", plan, 1, encoder=CPU)
    assert part_at(["-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
                    "-pix_fmt", "yuv420p", "-b:v", "4000k", "-maxrate", "4000k",
                    "-bufsize", "8000k", "-sc_threshold", "0", *keys], cpu) > 0  # fmt: skip
    assert not {"-init_hw_device", "-hwaccel", "-bf"} & set(cpu)
    assert cpu[cpu.index("-vf") + 1].endswith(",tonemap=hable,format=yuv420p")
    for encoder in (VAAPI, NVENC):
        gpu = converting.command("ffmpeg", "/films/a.mkv", plan, 1, encoder=encoder)
        # Set up as for the stations, before the file.
        assert 0 < part_at(ff.hw_input_args(encoder), gpu) < gpu.index("-i")
        # The stations' encoding at the copy's bitrate (VBR, with a most and
        # a buffer), no B-frames; then the keyframes where pieces start.
        station = ff._video_encoder_args(replace(Settings(), video_bitrate_kbps=4_000), encoder)
        at = station.index("-level:v")
        del station[at : at + 2]
        station[station.index("-g") + 1] = str(converting.GPU_GOP)
        assert part_at([*station, *keys], gpu) > 0, gpu
        assert part_at(["-bf", "0"], gpu) > 0
        chain = gpu[gpu.index("-vf") + 1]
        if encoder is VAAPI:
            # Up to the GPU once the CPU's filters are done (scaled, made
            # ordinary), as the stations' picture goes.
            assert chain.endswith(",tonemap=hable,format=yuv420p,format=nv12,hwupload")
            assert part_at(["-init_hw_device", "vaapi=gpu:/dev/dri/renderD128",
                            "-filter_hw_device", "gpu"], gpu) > 0  # fmt: skip
            assert "-forced-idr" not in gpu  # (VA-API's forced keyframes are IDR ones)
        else:
            assert chain.endswith(",tonemap=hable,format=yuv420p") and "hwupload" not in chain
            assert part_at(["-forced-idr", "1", "-gpu", "1", *keys], gpu) > 0
            assert part_at(["-hwaccel", "cuda", "-hwaccel_device", "1"], gpu) > 0
    # Subtitles are drawn in before the picture goes up to the GPU.
    text = converting.command("ffmpeg", "/films/a.mkv", replace(plan, subtitles=Subtitles(
        path="/data/subtitles.ass", styled=True)), 0, encoder=VAAPI)  # fmt: skip
    chain = text[text.index("-vf") + 1]
    assert chain.index(",subtitles=filename=") < chain.index(",format=nv12,hwupload")
    assert chain.endswith(",format=nv12,hwupload")
    assert part_at(["-force_key_frames", "6.000,12.000,18.000"], text) > 0
    drawn = converting.command("ffmpeg", "/films/a.mkv", replace(plan, subtitles=Subtitles(
        stream=2, image=True)), 0, encoder=VAAPI)  # fmt: skip
    graph = drawn[drawn.index("-filter_complex") + 1]
    assert graph.endswith("overlay=(W-w)/2:(H-h)/2:eof_action=pass:format=auto,format=yuv420p,"
                          "format=nv12,hwupload[vout]")  # fmt: skip
    assert part_at(["-map", "[vout]"], drawn) > 0
    # A repackaged copy's picture isn't encoded at all: nothing changes.
    kept = replace(plan, method=converting.REPACKAGE, picture="h264")
    assert converting.command("ffmpeg", "/films/a.mkv", kept, 1, encoder=VAAPI) == (
        converting.command("ffmpeg", "/films/a.mkv", kept, 1)
    )


# ffmpeg with a stand-in GPU (fake_gpu_ffmpeg.py: a GPU's command made on the
# CPU, each run written down), and the trouble GPU_TROUBLE says on it: it
# "fails" at once, makes "no keyframes" where the pieces start, or "stalls"
# (nothing comes).
STAND_IN_GPU = """\
import os
import sys

args = sys.argv[1:]
trouble = os.environ.get("GPU_TROUBLE", "")
if "h264_vaapi" in args or "h264_nvenc" in args:
    if trouble == "fails":
        os.environ["FAKE_GPU_BROKEN"] = "1"
    elif trouble == "no keyframes":
        at = args.index("-force_key_frames")
        args[at : at + 2] = ["-sc_threshold", "0"]
    elif trouble == "stalls":
        os.environ["REAL_FFMPEG"] = os.environ["STALLED_FFMPEG"]
os.execv(sys.executable, [sys.executable, os.environ["FAKE_GPU"], *args])
"""


async def stand_in_gpu(tmp_path, monkeypatch, trouble: str) -> tuple[str, str, Path]:
    """A file to copy, ffmpeg with a stand-in GPU (see STAND_IN_GPU), and
    where its runs are written down."""
    source = tmp_path / "movie.mkv"
    await asyncio.to_thread(make, source, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac")
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text(f"#!{sys.executable}\n{STAND_IN_GPU}")
    stalled = tmp_path / "stalled"
    stalled.write_text("#!/bin/sh\nexec sleep 30\n")
    for script in (ffmpeg, stalled):
        script.chmod(0o755)
    runs = tmp_path / "runs"
    for key, value in {
        "FAKE_GPU": FAKE_GPU, "REAL_FFMPEG": shutil.which("ffmpeg") or "ffmpeg",
        "FAKE_GPU_LOG": str(runs), "STALLED_FFMPEG": str(stalled), "GPU_TROUBLE": trouble,
    }.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    return str(source), str(ffmpeg), runs


def runs_in(runs: Path) -> list[tuple[str, float]]:
    """Each run: ("gpu" or "cpu", where it started)."""
    return [(line.split()[0], float(line.split()[-1])) for line in runs.read_text().splitlines()]


@needs_ffmpeg
@pytest.mark.parametrize("encoder", [VAAPI, NVENC], ids=["vaapi", "nvenc"])
@pytest.mark.parametrize(
    ("trouble", "said", "counted"),
    [
        ("", "", (0, 0, 0)),  # (made fine on the GPU throughout: the strike before is cleared)
        ("fails", "GPU encoding failed (ffmpeg 187: Failed to initialise VAAPI", (1, 1, 2)),
        ("no keyframes", "GPU encoding failed (no keyframe where piece 2 starts)", (1, 1, 2)),
        # (A stall may as well be the disk's, so it never counts against the GPU.)
        ("stalls", "Playback stalled on the GPU (nothing came for 3 seconds)", (1, 0, 1)),
    ],  # (counted: GPU failures, CPU rescues, and the copies' strikes; the stations' stay put)
)
async def test_the_gpu_never_makes_a_copy_fail(
    tmp_path, monkeypatch, caplog, encoder, trouble, said, counted
):
    """A copy converted on the GPU that goes wrong there carries on from
    where it was on the CPU, and stays there: its pieces are served, it
    isn't counted as failing, and GpuManager hears of it as of a station's
    program. Fine on the GPU, it's made there throughout."""
    source, ffmpeg, runs = await stand_in_gpu(tmp_path, monkeypatch, trouble)
    monkeypatch.setattr(converting, "STALL_S", 3.0)
    caplog.set_level(logging.INFO)
    gpu = GpuManager(Settings(), active=encoder, state="gpu", strikes=1, copy_strikes=1)
    copy = converting.Copy(ffmpeg, source, converted(4, LENGTH_S), gpu=gpu, name="A Copy (2024)")
    assert copy.encoder == encoder
    try:
        piece = await copy.piece(1)  # (the player starts 6 seconds in)
        assert piece is not None
        assert first_times(piece.read_bytes())[0] == pytest.approx(16.0, abs=0.05)
        for n in (2, 3, 0):
            assert await copy.piece(n) is not None, n
    finally:
        await copy.close()
    made = runs_in(runs)
    if trouble:
        # On the GPU first; then on the CPU from where it was, and there on.
        assert made[:2] == [("gpu", 6.0), ("cpu", 6.0)], made
        assert {kind for kind, _ in made[1:]} == {"cpu"} and copy.encoder == CPU, made
    else:
        assert {kind for kind, _ in made} == {"gpu"}, made
    assert copy.failures == 0 and not copy.broken
    assert (gpu.gpu_failures, gpu.cpu_rescues, gpu.copy_strikes) == counted
    assert gpu.strikes == 1 and gpu.state == "gpu" and not gpu.copies_off
    lines = [r.getMessage() for r in caplog.records]
    assert lines.count(f"Converting a copy of A Copy (2024) on {encoder.label}") == 1
    moved = [m for m in lines if m.endswith("; continuing the copy of A Copy (2024) on the CPU")]
    assert [m.startswith(said) for m in moved] == ([True] if trouble else []), moved


@needs_ffmpeg
async def test_only_making_where_the_gpu_failed_rescues_a_copy(tmp_path, monkeypatch):
    """The CPU rescued a copy once it makes the piece the GPU failed at; a
    piece further on, after a jump, proves nothing."""
    source, ffmpeg, runs = await stand_in_gpu(tmp_path, monkeypatch, "fails")
    gpu = GpuManager(Settings(), active=VAAPI, state="gpu")
    copy = converting.Copy(ffmpeg, source, converted(4, LENGTH_S), gpu=gpu)
    asked = 0

    async def gone() -> bool:  # (the player leaves once piece 1 is being made)
        nonlocal asked
        asked += 1
        return asked > 1

    try:
        assert await copy.piece(1, gone) is None
        assert await copy.piece(3) is not None  # (a jump ahead: made on the CPU)
        assert (gpu.gpu_failures, gpu.cpu_rescues) == (1, 0)
        assert await copy.piece(1) is not None  # (and back)
        assert (gpu.gpu_failures, gpu.cpu_rescues) == (1, 1)
    finally:
        await copy.close()
    assert runs_in(runs) == [("gpu", 6.0), ("cpu", 18.0), ("cpu", 6.0)]
    assert copy.failures == 0


@needs_ffmpeg
async def test_a_copy_leaves_a_gpu_turned_off_meanwhile(tmp_path, monkeypatch, caplog):
    source, ffmpeg, runs = await stand_in_gpu(tmp_path, monkeypatch, "")
    caplog.set_level(logging.INFO)
    gpu = GpuManager(Settings(), active=VAAPI, state="gpu", strikes=1)
    copy = converting.Copy(ffmpeg, source, converted(4, LENGTH_S), gpu=gpu, name="A Copy (2024)")
    try:
        assert await copy.piece(2) is not None
        # Turned off, after programs failed on it (see gpu.py): the next run
        # is on the CPU, with nothing counted for the copy.
        gpu.state, gpu.active = "disabled", CPU
        assert await copy.piece(0) is not None
    finally:
        await copy.close()
    assert runs_in(runs) == [("gpu", 12.0), ("cpu", 0.0)]
    assert copy.encoder == CPU and copy.failures == 0
    assert (gpu.gpu_failures, gpu.cpu_rescues, gpu.strikes) == (0, 0, 1)
    assert "The GPU was turned off; continuing the copy of A Copy (2024) on the CPU" in [
        r.getMessage() for r in caplog.records
    ]


@needs_ffmpeg
def test_three_converted_at_once_or_six_on_a_gpu(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        ctx = app.state.ctx
        smaller = {"key": "400", "device": PHONE, "maxKbps": 1500, "fit": True}

        def play() -> int:
            answer = home.post("/api/internal/play", json=smaller)
            if answer.status_code == 200:
                assert answer.json()["method"] == "convert"
                session = ctx.plays.get(answer.json()["session"])
                assert session.copy.encoder == ctx.gpu.encoder_for_copies()
            return answer.status_code

        ctx.gpu = GpuManager(ctx.settings)  # (while it's tested at startup: the CPU)
        most = applibrary.CONVERTING_MOST
        assert [play() for _ in range(most + 1)] == [200] * most + [503]
        ctx.gpu = GpuManager(ctx.settings, active=VAAPI, state="gpu")
        more = applibrary.CONVERTING_MOST_GPU - most
        assert [play() for _ in range(more + 1)] == [200] * more + [503]


def test_copies_failing_on_the_gpu_never_take_it_from_the_stations(caplog):
    """Copies in a row that fail on the GPU but are made fine on the CPU send
    copies to the CPU, and only copies: the stations keep the GPU."""
    gpu = GpuManager(Settings(), active=VAAPI, state="gpu")
    for _ in range(gpu_module.COPY_STRIKES_LIMIT - 1):
        gpu.copy_rescued()
    gpu.copy_succeeded()  # (one made fine on the GPU clears them)
    for _ in range(gpu_module.COPY_STRIKES_LIMIT):
        assert gpu.encoder_for_copies() == VAAPI
        gpu.copy_rescued()
    assert gpu.encoder_for_copies() == CPU and gpu.copies_off
    assert gpu.encoder_for(False) == VAAPI and gpu.state == "gpu" and gpu.strikes == 0
    assert gpu.as_dict()["copiesOnCpu"] is True
    assert any("Stations keep using it" in r.getMessage() for r in caplog.records)


# Even sound for a show's episodes ---------------------------------------------------------

# (The phone plays the quiet episode's file as it is, and takes copies.)
PLAYS_IT = PHONE


def loudness(data: bytes) -> float:
    """A piece's loudness (integrated, LUFS), as ffmpeg's EBU R128 meter
    reads it."""
    said = subprocess.run(
        ["ffmpeg", "-nostats", "-i", "-", "-af", "ebur128", "-f", "null", "-"],
        input=data, capture_output=True, check=True,
    ).stderr.decode()  # fmt: skip
    return float(said.rsplit("I:", 1)[1].split()[0])


def test_the_stations_loudness_is_as_it_was():
    """Even sound in Media uses the stations' own normalization, which is
    unchanged: -24 LUFS, one pass, for episodes only."""
    assert ff.LOUDNESS_TARGET == "I=-24:TP=-2:LRA=11"
    assert ff._audio_filter(True) == (
        "aresample=48000:async=1:first_pts=0,loudnorm=I=-24:TP=-2:LRA=11,aresample=48000,apad"
    )
    assert ff._audio_filter(False) == "aresample=48000:async=1:first_pts=0,apad"
    assert converting.EVEN_SOUND.startswith(f"loudnorm={ff.LOUDNESS_TARGET},")


def test_how_even_sound_is_made():
    """The sound the device would get anyway, made again rather than copied,
    the normalization first and night mode's after it."""
    aac = Track("1", "aac", channels=2)
    ac3 = Track("2", "ac3", channels=6)
    truehd = Track("3", "truehd", channels=8)
    assert converting.sound_for(aac, frozenset({"aac"}), False, even=True) == ("aac", 2)
    assert converting.sound_for(ac3, frozenset({"aac", "ac3"}), False, even=True) == ("ac3", 6)
    assert converting.sound_for(truehd, frozenset({"truehd", "ac3"}), False, even=True) == (
        "ac3", 6
    )  # fmt: skip
    assert converting.sound_for(ac3, frozenset({"aac", "ac3"}), True, even=True) == ("aac", 2)
    assert converting.sound_for(ac3, frozenset({"aac", "ac3"}), False) == ("copy", 6)
    plan = converting.Plan(
        method=converting.REPACKAGE, why=(), starts=(0.0, 6.0), duration_s=12.0, audio=ac3,
        audio_codec="ac3", audio_channels=6, picture="h264", even=True,
    )  # fmt: skip
    args = converting.command("ffmpeg", "/tv/a.mkv", plan, 0)
    assert part_at(["-c:v", "copy"], args) > 0
    assert part_at(["-af", converting.EVEN_SOUND, "-c:a", "ac3", "-b:a", "640k", "-ac", "6"],
                   args) > 0  # fmt: skip
    both = converting.command("ffmpeg", "/tv/a.mkv", replace(plan, night=True, audio_codec="aac",
                                                            audio_channels=2), 0)  # fmt: skip
    chain = both[both.index("-af") + 1]
    assert chain == f"{converting.EVEN_SOUND},{hls.NIGHT_SOUND}"
    assert chain.index("loudnorm=I=-24") < chain.index("acompressor")
    # Night mode's alone, as before.
    night = converting.command("ffmpeg", "/tv/a.mkv", replace(plan, even=False, night=True,
                                                             audio_codec="aac"), 0)  # fmt: skip
    assert part_at(["-af", hls.NIGHT_SOUND, "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar",
                    "48000"], night) > 0  # fmt: skip
    plain = converting.command("ffmpeg", "/tv/a.mkv", replace(plan, even=False), 0)
    assert "-af" not in plain and not any("loudnorm" in a for a in plain)


@needs_ffmpeg
def test_an_episode_comes_at_the_stations_loudness(app, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        assert home.get("/api/app-libraries").json()["evenSound"] is True  # (on, to start)
        assert "even-sound" in home.get("/api/v1/server").json()["features"]
        played = home.post("/api/internal/play", json={"key": "501", "device": PLAYS_IT})
        assert played.status_code == 200, played.text
        answer = played.json()
        # The picture as it is, and only the sound made: the device plays the file.
        assert answer["method"] == "repackage" and answer["why"] == [applibrary.EVEN_WHY]
        assert answer["why"] == ["even sound for the show's episodes"]
        assert all(v["playable"] for v in answer["versions"])
        copy = app.state.ctx.plays.find(answer["session"]).copy
        assert copy.plan.even and copy.plan.audio_codec == "aac"
        args = converting.command("ffmpeg", copy.source, copy.plan, 0)
        assert args[args.index("-af") + 1] == f"loudnorm={ff.LOUDNESS_TARGET},aresample=48000"
        assert "repackaged, its sound made AAC stereo, with even sound" in caplog.text
        here = answer["url"].rsplit("/", 1)[0]
        source = (copy.source and Path(copy.source).read_bytes()) or b""
        assert loudness(source) < -35  # (as the file is)
        for n in (0, 2):  # (from the start, and from anywhere)
            piece = home.get(f"{here}/piece-{n}.ts")
            assert piece.status_code == 200
            assert loudness(piece.content) == pytest.approx(-24, abs=1.5), n
            assert picture_of(piece.content)["codec_name"] == "h264"
        home.post(answer["leave"])
        # A movie isn't touched: the same file plays as it is.
        movie = home.post("/api/internal/play", json={"key": "402", "device": PLAYS_IT}).json()
        assert (movie["method"], movie["why"]) == ("direct", None)
        # Nor is a movie's copy made for another reason.
        copied = home.post("/api/internal/play", json={"key": "400", "device": PHONE}).json()
        assert copied["why"] == ["its sound's format (Dolby Digital)"]
        assert not app.state.ctx.plays.find(copied["session"]).copy.plan.even
        # An app that doesn't take copies gets the episode as before.
        older = {k: v for k, v in PLAYS_IT.items() if k != "hls"}
        before = home.post("/api/internal/play", json={"key": "501", "device": older}).json()
        assert (before["method"], before["why"]) == ("direct", None)


@needs_ffmpeg
def test_even_sound_with_night_mode_and_other_copies(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        night = home.post(
            "/api/internal/play", json={"key": "501", "device": PLAYS_IT, "night": True}
        ).json()
        assert night["method"] == "repackage"
        assert night["why"] == ["even sound for the show's episodes", "night mode's sound"]
        plan = app.state.ctx.plays.find(night["session"]).copy.plan
        assert converting.sound_chain(plan) == f"{converting.EVEN_SOUND},{hls.NIGHT_SOUND}"
        home.post(night["leave"])
        # A copy converted for another reason has even sound too (an episode's).
        fit = home.post(
            "/api/internal/play",
            json={"key": "501", "device": PLAYS_IT, "maxKbps": 1_500, "fit": True},
        ).json()
        assert fit["method"] == "convert" and fit["why"] == [
            "a smaller picture, to fit the connection", "even sound for the show's episodes"
        ]  # fmt: skip
        home.post(fit["leave"])
        # Where the picture can't be kept as it is (HEVC, for a player that takes
        # only H.264 in a copy), the episode plays as it is: even sound never
        # costs a picture made again.
        tv = {**PLAYS_IT, "video": [*PLAYS_IT["video"], {"codec": "hevc", "width": 1920,
                                                           "height": 1080, "bitDepth": 8}]}  # fmt: skip
        hevc = home.post("/api/internal/play", json={"key": "511", "device": tv}).json()
        assert (hevc["method"], hevc["why"]) == ("direct", None)


@needs_ffmpeg
def test_even_sound_can_be_turned_off(app, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as home:
        home.post("/api/access/users", json={"name": "Pat", "password": "correct horse"})
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        off = home.put("/api/app-libraries", json={"libraries": ["1", "2"], "evenSound": False})
        assert off.status_code == 200 and off.json()["evenSound"] is False
        assert (
            "Even sound for a show's episodes in StationPlay's apps: off (each episode's sound as "
            "it is) (set by Pat)" in caplog.text
        )
        assert "even-sound" not in home.get("/api/v1/server").json()["features"]
        played = home.post("/api/internal/play", json={"key": "501", "device": PLAYS_IT}).json()
        assert (played["method"], played["why"]) == ("direct", None)
        # (Kept, as it was set; saving without it leaves it as it is.)
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        assert app.state.ctx.shared.even_sound is False
        assert ondemand.Shared(app.state.ctx.db).even_sound is False
        home.put("/api/app-libraries", json={"libraries": ["1", "2"], "evenSound": True})
        assert "even-sound" in home.get("/api/v1/server").json()["features"]
