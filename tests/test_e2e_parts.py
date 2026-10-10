"""End to end, with real ffmpeg: a movie in several files (Plex's stacked
parts) played as one program, on a station across the join and in Media
from a start inside its second file; and a missing part handled as a
broken file is, and Plex unreachable, never black for the rest of its
slot."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import converting
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .fakeplex_library import LibraryPlex
from .test_e2e import assert_clean_stream, ff, media_seconds, packet_times, record, start_server
from .test_parts import stack

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg"
)

PART_S = 8  # each file's length: tiny


def make(
    path: Path, picture: str, tone: int, video: str = "libx264", seconds: int = PART_S
) -> Path:
    """A small file of PART_S seconds: a test picture and a tone of its own,
    a keyframe every second."""
    ff(
        "-f", "lavfi", "-i", f"{picture}=s=320x180:r=25", "-f", "lavfi", "-i",
        f"sine=f={tone}:sample_rate=48000", "-t", str(seconds),
        "-c:v", video, *(["-preset", "ultrafast"] if video == "libx264" else []),
        "-g", "25", "-c:a", "aac", "-shortest", str(path),
    )  # fmt: skip
    return path


@pytest.fixture(scope="module")
def parts(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("parts")
    return {
        "cd1": make(d / "Long Movie-cd1.mkv", "testsrc2", 440),
        "cd2": make(d / "Long Movie-cd2.mkv", "smptehdbars", 660),
        # (The same movie's second file, made another way: its picture's
        # format isn't the first's.)
        "cd2-mpeg4": make(d / "Long Movie-cd2.mpeg4.mkv", "smptehdbars", 660, "mpeg4"),
        # (Long enough to stand in for the whole of it.)
        "other": make(d / "Stand In.mkv", "rgbtestsrc", 550, seconds=3 * PART_S),
    }


def black_stretches(path: Path) -> list[tuple[float, float]]:
    """Where a recording's picture is black for a second or more."""
    said = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-vf", "blackdetect=d=1:pix_th=0.05",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr  # fmt: skip
    found = []
    for line in said.splitlines():
        if "black_start:" in line:
            fields = dict(f.split(":", 1) for f in line.split("]")[-1].split())
            found.append((float(fields["black_start"]), float(fields["black_end"])))
    return found


# A station --------------------------------------------------------------------------------


async def test_a_station_plays_a_movie_in_two_files_across_the_join(tmp_path, parts, caplog):
    """Tuned in during its second file, it starts there at the right place;
    then the next showing plays the first file and the second straight on,
    with the corner mark and the Up Next Banner over the join, and no black
    between them."""
    caplog.set_level(logging.INFO)
    plex = FakePlex()
    plex.add_section("2", "Movies", "movie")
    plex.add_movie("300", "Long Movie", str(parts["cd1"]), 2 * PART_S * 1000, section="2")
    stack(plex, "300", (str(parts["cd1"]), PART_S * 1000), (str(parts["cd2"]), PART_S * 1000))
    base, _app, settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={"number": 8, "name": "Movie TV", "orderMode": "rotate",
                      "sources": [{"type": "movie", "ratingKey": "300"}],
                      "introSeconds": 3, "upNextSeconds": 5},
            )  # fmt: skip
            assert made.status_code == 201, made.text
        started = time.time()
        data = await record(f"{base}/stream/8", 3 + PART_S + 2 * PART_S + 2)
        elapsed = time.time() - started
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "movie.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert elapsed - 3 <= media_seconds(out) <= elapsed + 20
    said = caplog.text
    # (Joined after the 3-second Intro Bumper: in its first file, or by then
    # its second; either way, then on to the second, and the next showing.)
    assert "“Long Movie” (2000)" in said and "part 1 of 2" in said, said
    assert "goes on to its next file, part 2 of 2" in said
    assert "Long Movie-cd2.mkv" in said
    assert "Still opening" not in said and "can't play" not in said
    assert (
        not (settings.data_dir / "broken-files.json").exists()
        or json.loads((settings.data_dir / "broken-files.json").read_text())["files"] == []
    )
    # Nothing black, anywhere: the second file follows the first at once.
    assert black_stretches(out) == []
    # (Both files' sound is in it: the first's tone and the second's.)
    assert len(packet_times(out, "a:0")) > 0


async def test_a_station_tuned_in_during_the_second_file_starts_there(tmp_path, parts, caplog):
    caplog.set_level(logging.INFO)
    plex = FakePlex()
    plex.add_section("2", "Movies", "movie")
    plex.add_movie("300", "Long Movie", str(parts["cd1"]), 2 * PART_S * 1000, section="2")
    stack(plex, "300", (str(parts["cd1"]), PART_S * 1000), (str(parts["cd2"]), PART_S * 1000))
    base, app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={"number": 8, "name": "Movie TV", "orderMode": "rotate",
                      "sources": [{"type": "movie", "ratingKey": "300"}], "introSeconds": 0},
            )  # fmt: skip
            assert made.status_code == 201, made.text
            # Into its second file, by the schedule.
            ctx = app.state.ctx
            station = ctx.station(made.json()["id"])
            now = int(time.time() * 1000)
            slot = station.locate(now)
            wait_s = (slot.start_ms + (PART_S + 2) * 1000 - now) / 1000
            if wait_s > 0:
                await asyncio.sleep(wait_s)
        data = await record(f"{base}/stream/8", 4)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "joined.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    said = caplog.text
    assert "joining “Long Movie” (2000)" in said and ", part 2 of 2 (" in said, said
    assert "Long Movie-cd2.mkv" in said.split("joining", 1)[1].splitlines()[0]


async def test_a_missing_part_is_a_broken_file_and_a_stand_in_plays_the_rest(
    tmp_path, parts, caplog
):
    caplog.set_level(logging.INFO)
    plex = FakePlex()
    plex.add_section("2", "Movies", "movie")
    plex.add_movie("300", "Long Movie", str(parts["cd1"]), 2 * PART_S * 1000, section="2")
    stack(
        plex, "300", (str(parts["cd1"]), PART_S * 1000), ("/gone/Long Movie-cd2.mkv", PART_S * 1000)
    )
    plex.add_movie("301", "Stand In", str(parts["other"]), 3 * PART_S * 1000, section="2")
    base, _app, settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={"number": 8, "name": "Movie TV", "orderMode": "rotate", "introSeconds": 0,
                      "sources": [{"type": "movie", "ratingKey": "300"},
                                  {"type": "movie", "ratingKey": "301"}]},
            )  # fmt: skip
            assert made.status_code == 201, made.text
        data = await record(f"{base}/stream/8", 2 * PART_S + 4)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "missing.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    listed = json.loads((settings.data_dir / "broken-files.json").read_text())["files"]
    assert [(e["ratingKey"], e["part"], e["parts"]) for e in listed] == [("300", 2, 2)]
    assert listed[0]["reason"].endswith(", in part 2 of 2"), listed[0]
    assert listed[0]["file"] == "/gone/Long Movie-cd2.mkv"
    assert "plays in its place" in caplog.text
    # Never black for the rest of its slot: a stand-in fills it.
    assert all(b - a < 4 for a, b in black_stretches(out)), black_stretches(out)


async def test_with_plex_unreachable_a_stand_in_plays_after_the_first_file(
    tmp_path, parts, caplog, monkeypatch
):
    """Plex down, StationPlay plays the file it knew (the first): when that
    ends long before the movie's time, it can't tell whether there's more,
    so a stand-in plays the rest, not black; and nothing's called broken."""
    from app import broadcaster

    monkeypatch.setattr(broadcaster, "MORE_FILES_S", 4.0)  # (the files are tiny)
    caplog.set_level(logging.INFO)
    plex = FakePlex()
    plex.add_section("2", "Movies", "movie")
    plex.add_movie("300", "Long Movie", str(parts["cd1"]), 2 * PART_S * 1000, section="2")
    stack(plex, "300", (str(parts["cd1"]), PART_S * 1000), (str(parts["cd2"]), PART_S * 1000))
    plex.add_movie("301", "Stand In", str(parts["other"]), 3 * PART_S * 1000, section="2")
    base, _app, settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={"number": 8, "name": "Movie TV", "orderMode": "rotate", "introSeconds": 0,
                      "sources": [{"type": "movie", "ratingKey": "300"},
                                  {"type": "movie", "ratingKey": "301"}]},
            )  # fmt: skip
            assert made.status_code == 201, made.text
        plex.down = True
        data = await record(f"{base}/stream/8", 2 * PART_S + 4)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "unreachable.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    said = caplog.text
    assert "before its time, and Plex couldn't say whether it has another" in said, said
    assert "plays in its place" in said
    assert (
        not (settings.data_dir / "broken-files.json").exists()
        or json.loads((settings.data_dir / "broken-files.json").read_text())["files"] == []
    )
    assert all(b - a < 4 for a, b in black_stretches(out)), black_stretches(out)


# Media ------------------------------------------------------------------------------------


PHONE = {"containers": ["mkv", "mp4"], "video": [{"codec": "h264"}], "hdr": [],
         "audio": ["aac"], "hls": ["ts"]}  # fmt: skip


def library(cd2: Path, cd1: Path) -> LibraryPlex:
    fp = LibraryPlex()
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Long Movie", str(cd1), 2 * PART_S * 1000, section="2")
    probed = [json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(p)],
        capture_output=True, check=True, text=True,
    ).stdout)["streams"] for p in (cd1, cd2)]  # fmt: skip

    def streams(found: list[dict], base: int) -> list[dict]:
        return [
            {"id": base + n, "streamType": 1 if s["codec_type"] == "video" else 2,
             "codec": s["codec_name"], "width": s.get("width"), "height": s.get("height"),
             "channels": s.get("channels"), "index": n, "default": n == 1}
            for n, s in enumerate(found)
        ]  # fmt: skip

    fp.more["300"] = {"Media": [{
        "id": 3000, "container": "mkv", "videoCodec": "h264", "duration": 2 * PART_S * 1000,
        "Part": [
            {"key": "/library/parts/3001/1/file.mkv", "file": str(cd1), "container": "mkv",
             "duration": PART_S * 1000, "size": cd1.stat().st_size, "Stream": streams(probed[0], 10)},
            {"key": "/library/parts/3002/1/file.mkv", "file": str(cd2), "container": "mkv",
             "duration": PART_S * 1000, "size": cd2.stat().st_size, "Stream": streams(probed[1], 20)},
        ],
    }]}  # fmt: skip
    return fp


def copy_of(home: TestClient, played: dict, first: int = 0) -> tuple[bytes, list[str]]:
    """The copy's pieces from `first` on, one after the other."""
    listed = home.get(played["url"]).text
    names = [line for line in listed.splitlines() if line.startswith("piece-")]
    here = played["url"].rsplit("/", 1)[0]
    data = b""
    for name in names[first:]:
        got = home.get(f"{here}/{name}")
        assert got.status_code == 200, (name, got.text)
        data += got.content
    return data, names


@pytest.mark.parametrize(("second", "method"), [("cd2", "repackage"), ("cd2-mpeg4", "convert")])
def test_media_plays_a_movie_in_two_files_from_inside_the_second(
    tmp_path, parts, second, method, caplog
):
    """From a start in its second file, as one program: the copy's playlist
    is the whole movie (its length both files), the pieces from there on
    play straight on to its end, with the program's own times; and the
    whole of it plays across the join. Its files' pictures alike, the
    picture's kept as it is; not, converted."""
    caplog.set_level(logging.INFO)
    fp = library(parts[second], parts["cd1"])
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        start_ms = (PART_S + 3) * 1000
        played = home.post(
            "/api/internal/play", json={"key": "300", "device": PHONE, "startMs": start_ms}
        )
        assert played.status_code == 200, played.text
        answer = played.json()
        assert answer["method"] == method, answer
        assert answer["durationMs"] == 2 * PART_S * 1000
        assert answer["why"][0] == "its 2 files, played as one"
        listed = home.get(answer["url"]).text
        assert f"#EXT-X-START:TIME-OFFSET={start_ms / 1000:.3f}" in listed
        lengths = [float(x.split(",")[0]) for x in listed.split("#EXTINF:")[1:]]
        assert sum(lengths) == pytest.approx(2 * PART_S, abs=0.01)
        starts = [sum(lengths[:n]) for n in range(len(lengths))]
        assert PART_S in [round(s, 3) for s in starts]  # (a piece starts at the join)
        here = next(n for n, s in reversed(list(enumerate(starts))) if s <= start_ms / 1000)
        later, _names = copy_of(home, answer, here)
        out = tmp_path / "from-the-second.ts"
        out.write_bytes(later)
        video = packet_times(out, "v:0")
        assert video[0][0] == pytest.approx(starts[here] + converting.TS_OFFSET_S, abs=0.1)
        assert video[-1][0] == pytest.approx(2 * PART_S + converting.TS_OFFSET_S, abs=0.3)
        assert_clean_stream(out)
        # Watched by the whole: past the first file isn't the end.
        kept = home.post("/api/internal/progress", json={
            "key": "300", "positionMs": PART_S * 1000 + 1000, "session": answer["session"],
            "sequence": 1}).json()  # fmt: skip
        assert kept["watched"] is False
        assert home.post(answer["leave"]).status_code == 204
        # The whole of it, from the start, across the join: one stream, no
        # gap, no overlap, nothing taken as damaged.
        again = home.post(
            "/api/internal/play", json={"key": "300", "device": PHONE, "startMs": 0}
        ).json()
        whole, _ = copy_of(home, again)
        out = tmp_path / "whole.ts"
        out.write_bytes(whole)
        assert_clean_stream(out)
        assert media_seconds(out) == pytest.approx(2 * PART_S, abs=0.3)
        assert home.post(again["leave"]).status_code == 204
    assert "joining its 2 files" in caplog.text


# Found by the cold audit of 1.31.0 ------------------------------------------------


def _length_ms(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return int(float(json.loads(out)["format"]["duration"]) * 1000)


def _streams(path: Path, base: int) -> list[dict]:
    found = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True, check=True, text=True,
    ).stdout)["streams"]  # fmt: skip
    return [
        {"id": base + n, "streamType": 1 if s["codec_type"] == "video" else 2,
         "codec": s["codec_name"], "width": s.get("width"), "height": s.get("height"),
         "channels": s.get("channels"), "index": n, "default": n == 1}
        for n, s in enumerate(found)
    ]  # fmt: skip


def test_a_converted_copy_carries_on_past_a_first_file_whose_sound_runs_longer(tmp_path, parts):
    """A file whose sound runs on after its picture ends (common in old
    disc rips): Plex gives its length as the longer of the two. A converted
    copy joining it to the next file has every piece the plan lists,
    rather than giving up at the join."""
    cd1 = tmp_path / "Long Movie-cd1.mkv"
    # (Picture 7 seconds, sound 14.)
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=7", "-f", "lavfi", "-i",
       "sine=f=440:sample_rate=48000:d=14", "-c:v", "libx264", "-preset", "ultrafast",
       "-g", "25", "-c:a", "aac", str(cd1))  # fmt: skip
    cd2 = parts["cd2-mpeg4"]  # (its picture's format differs: the copy is converted)
    l1, l2 = _length_ms(cd1), _length_ms(cd2)
    fp = LibraryPlex()
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Long Movie", str(cd1), l1 + l2, section="2")
    fp.more["300"] = {"Media": [{
        "id": 3000, "container": "mkv", "videoCodec": "h264", "duration": l1 + l2,
        "Part": [
            {"key": "/library/parts/3001/1/file.mkv", "file": str(cd1), "container": "mkv",
             "duration": l1, "size": cd1.stat().st_size, "Stream": _streams(cd1, 10)},
            {"key": "/library/parts/3002/1/file.mkv", "file": str(cd2), "container": "mkv",
             "duration": l2, "size": cd2.stat().st_size, "Stream": _streams(cd2, 20)},
        ],
    }]}  # fmt: skip
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        played = home.post("/api/internal/play", json={"key": "300", "device": PHONE, "startMs": 0})
        assert played.status_code == 200, played.text
        answer = played.json()
        assert answer["method"] == "convert", answer
        names = [ln for ln in home.get(answer["url"]).text.splitlines() if ln.startswith("piece-")]
        here = answer["url"].rsplit("/", 1)[0]
        got = [(name, home.get(f"{here}/{name}").status_code) for name in names]
        assert len(got) >= 3 and all(code == 200 for _, code in got), got


def test_an_app_that_takes_no_copies_isnt_offered_a_version_in_several_files(tmp_path, parts):
    """An app that plays files only as they are (no `device.hls`) is told a
    version in several files isn't playable: it plays only as a copy that
    joins them."""
    fp = library(parts["cd2"], parts["cd1"])
    whole = parts["cd1"]
    fp.more["300"]["Media"].append({
        "id": 3100, "container": "mkv", "videoCodec": "h264", "duration": PART_S * 1000,
        "Part": [{"key": "/library/parts/3101/1/file.mkv", "file": str(whole), "container": "mkv",
                  "duration": PART_S * 1000, "size": whole.stat().st_size}],
    })  # fmt: skip
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    no_copies = {k: v for k, v in PHONE.items() if k != "hls"}
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        played = home.post("/api/internal/play", json={"key": "300", "device": no_copies})
        assert played.status_code == 200, played.text
        listed = {v["id"]: v["playable"] for v in played.json()["versions"]}
        assert played.json()["version"] == "3100"
        assert listed == {"3000": False, "3100": True}, played.json()["versions"]
