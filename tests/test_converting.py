"""Copies StationPlay makes for a device that can't play a file as it is
(converting.py, keyframes.py, and playing them through applibrary.py):
where the pieces start, reading a file's keyframes from its index, and
repackaged and converted copies played from the start and from anywhere."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import converting
from app.catalog import Media, Track
from app.config import Settings
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
