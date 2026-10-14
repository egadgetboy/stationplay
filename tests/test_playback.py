"""How stations play: picture sizes, the tuners (how many stations play at
once, and the card shown when they're all in use), and the speed test."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sqlite3
import subprocess
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import ffmpeg as ff
from app import jobs, playback
from app.config import Settings, _picture
from app.db import Database
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .helpers import PAGE
from .test_e2e import assert_clean_stream, start_server
from .test_e2e import ff as make

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def test_picture_sizes():
    sizes = {p: ff.sized(Settings(), p) for p in ff.PICTURES}
    assert [(s.video_width, s.video_height, s.video_bitrate_kbps) for s in sizes.values()] == [
        (854, 480, 1500),
        (1280, 720, 3500),
        (1920, 1080, 6000),
    ]
    # Anything else is the standard size.
    assert ff.sized(Settings(), "4K").video_height == 720
    # The old VIDEO_HEIGHT says which size to start from.
    assert [_picture(h) for h in ("", "x", "480", "576", "720", "1080", "2160")] == [
        "", "", "480p", "480p", "720p", "1080p", "1080p",
    ]  # fmt: skip


def test_playback_settings_are_kept_and_checked(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    playback.start(db, Settings())
    got = playback.load(db)
    assert (got.picture, got.tuners) == ("720p", 4)
    got = playback.save(db, picture="1080p", tuners=6)
    assert (got.picture, got.tuners) == ("1080p", 6)
    for bad in ({"picture": "4K"}, {"tuners": 0}, {"tuners": playback.MOST_TUNERS + 1}):
        with pytest.raises(ValueError):
            playback.save(db, **bad)
    assert playback.load(db).tuners == 6
    # Plex is told of more, so tapiOca can say when they're all in use.
    assert [playback.announced(n) for n in (1, 2, 4, 10)] == [2, 4, 8, 20]


def test_the_old_settings_are_where_they_start(tmp_path, caplog):
    db = Database(tmp_path / "db.sqlite")
    made = db.create_channel(5, "Five", [])
    playback.start(db, Settings(tuner_count=7, picture="1080p"))
    got = playback.load(db)
    assert (got.picture, got.tuners) == ("1080p", 7)
    # Stations there were already played at that size; they still are.
    assert db.get_channel(made.id).picture == "1080p"
    # From then on, the page's settings count.
    playback.save(db, picture="480p", tuners=3)
    with caplog.at_level(logging.WARNING):
        playback.start(db, Settings(tuner_count=7, picture="1080p"))
    got = playback.load(db)
    assert (got.picture, got.tuners) == ("480p", 3)
    assert db.get_channel(made.id).picture == "1080p"
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "TUNER_COUNT (7) is no longer used" in said and "VIDEO_HEIGHT" in said


def test_what_the_all_tuners_card_says():
    assert playback.busy_lines(1, [3]) == [
        "All tuners in use",
        "tapiOca can play only 1 station at a time",
        "On now: Station 3. Try again soon, or ask whoever runs tapiOca to add more tuners.",
    ]
    assert "On now: Stations 3, 7 and 12." in playback.busy_lines(3, [3, 7, 12])[2]


@pytest.fixture
def client(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * 60_000)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    with TestClient(app) as c:
        yield c


def station(client, number: int, **extra):
    body = {"number": number, "sources": [{"type": "show", "ratingKey": "100"}], **extra}
    return client.post("/api/channels", json=body)


def test_new_stations_take_the_picture_size_set_for_them(client, monkeypatch):
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", False)
    got = client.get("/api/playback").json()
    assert got["picture"] == "720p" and got["tuners"] == 4 and got["announced"] == 8
    assert got["pictures"] == ["480p", "720p", "1080p"] and got["speedTest"] is None
    assert station(client, 1).json()["picture"] == "720p"
    assert client.put("/api/playback", json={"picture": "1080p"}).json()["picture"] == "1080p"
    assert station(client, 2).json()["picture"] == "1080p"
    # The page's new stations start with it too.
    assert '"picture": "1080p"' in client.get("/").text
    # A station can have its own.
    made = station(client, 3, picture="480p").json()
    assert made["picture"] == "480p"
    edited = client.put(
        f"/api/channels/{made['id']}",
        json={"number": 3, "sources": [{"type": "show", "ratingKey": "100"}], "picture": "720p"},
    )
    assert edited.status_code == 200 and edited.json()["picture"] == "720p"
    assert station(client, 4, picture="2160p").status_code == 400
    assert client.put("/api/playback", json={"tuners": 50}).status_code == 400
    assert client.put("/api/playback", json={"tuners": 2}).json()["tuners"] == 2
    assert client.get("/discover.json").json()["TunerCount"] == 4
    assert client.get("/api/status").json()["tuners"] == 2


def test_new_stations_start_with_what_the_setup_chose(client, monkeypatch):
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", False)
    got = client.get("/api/playback").json()
    assert got["newStation"] == {}
    chosen = {
        "subtitles": "forced", "breaks": 2, "stationId": True, "idSeconds": 5,
        "introSeconds": 0, "upNextSeconds": 3, "watermark": "clock", "watermarkPosition": "top-right",
    }  # fmt: skip
    saved = client.put("/api/playback", json={"newStation": chosen}).json()
    assert saved["newStation"] == chosen
    made = station(client, 1).json()
    assert {k: made[k] for k in chosen} == chosen
    # What a station is given itself still counts.
    assert station(client, 2, breaks=0, watermark="logo").json()["breaks"] == 0
    # The page's new stations start with them too.
    page = client.get("/").text
    assert '"subtitles": "forced"' in page and '"watermark": "clock"' in page
    # Only these settings, and only their choices (true isn't 1).
    for bad in (
        {"breaks": 4},
        {"stationId": 1},
        {"breaks": True},
        {"subtitles": "sometimes"},
        {"orderMode": "shuffle"},
        {"idSeconds": "5"},
        {"watermarkPosition": "middle"},
        {"watermarkSize": "small"},
    ):
        assert client.put("/api/playback", json={"newStation": bad}).status_code == 400, bad
    # Given in part, the rest stay.
    again = client.put("/api/playback", json={"newStation": {"breaks": 1}}).json()
    assert again["newStation"] == {**chosen, "breaks": 1}


def test_odd_settings_for_new_stations_are_left_out(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    db.set_meta(playback.META_NEW_STATION, '{"breaks": 9, "subtitles": "always"}')
    assert playback.load(db).new_station == {"subtitles": "always"}
    db.set_meta(playback.META_NEW_STATION, "[not json")
    assert playback.load(db).new_station == {}


@needs_ffmpeg
def test_the_speed_test_says_how_many_stations_could_play(client, monkeypatch):
    monkeypatch.setattr(playback, "SPEED_TEST_S", 1.0)
    got = client.post("/api/playback/speed-test")
    assert got.status_code == 200, got.text
    tested = got.json()["speedTest"]
    assert set(tested["pictures"]) == {"480p", "720p", "1080p"} and tested["encoder"]
    for result in tested["pictures"].values():
        assert result["speed"] > 0 and 0 <= result["stations"] <= playback.MOST_TUNERS
    # (Bigger pictures take longer.)
    assert tested["pictures"]["480p"]["speed"] >= tested["pictures"]["1080p"]["speed"] * 0.8
    assert client.get("/api/playback").json()["speedTest"]["at"] == tested["at"]


def video_size(data: bytes, tmp_path) -> tuple[int, int]:
    path = tmp_path / "probe.ts"
    path.write_bytes(data)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    stream = json.loads(out)["streams"][0]
    return stream["width"], stream["height"]


async def read_for(url: str, seconds: float) -> bytes:
    """What a stream sends in `seconds` (from when it starts sending)."""
    data = bytearray()
    loop = asyncio.get_running_loop()
    async with (
        httpx.AsyncClient(headers=PAGE, timeout=30) as client,
        client.stream("GET", url) as response,
    ):
        assert response.status_code == 200
        started = None
        async for chunk in response.aiter_bytes():
            data += chunk
            started = started or loop.time()
            if loop.time() - started > seconds:
                break
    return bytes(data)


@needs_ffmpeg
async def test_when_every_tuner_is_in_use_a_card_says_so(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", False)
    d = tmp_path / "media"
    d.mkdir()
    make(
        "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=20",
        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", "20",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(d / "a.mkv"),
    )  # fmt: skip
    plex = FakePlex()
    plex.add_show("100", "Show")
    plex.add_episode("201", "100", 1, 1, "One", str(d / "a.mkv"), 20_000)
    base, app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(headers=PAGE, base_url=base, timeout=30) as client:
            assert (await client.put("/api/playback", json={"tuners": 1})).status_code == 200
            for number, picture in ((1, "480p"), (2, "720p")):
                made = await client.post(
                    "/api/channels",
                    json={
                        "number": number, "introSeconds": 0, "upNextSeconds": 0,
                        "watermark": "off", "picture": picture,
                        "sources": [{"type": "show", "ratingKey": "100"}],
                    },
                )  # fmt: skip
                assert made.status_code == 201, made.text
        # Station 1 plays, at its own size; station 2 has to wait, and a
        # card says why.
        watching = asyncio.create_task(read_for(f"{base}/stream/1", 8))
        await asyncio.sleep(3)
        with caplog.at_level(logging.WARNING):
            card = await read_for(f"{base}/stream/2", 3)
        first = await watching
        assert video_size(first, tmp_path) == (426, 240)
        out = tmp_path / "card.ts"
        out.write_bytes(card)
        assert_clean_stream(out)
        assert video_size(card, tmp_path) == (640, 360)
        assert any("No tuners are free (1 in use" in r.getMessage() for r in caplog.records)
        assert not app.state.ctx.broadcasters.get(2) or not app.state.ctx.broadcasters[2].running
        # Once station 1 is left (and its moment for flipping back is over),
        # station 2 plays.
        await asyncio.sleep(2.5)
        second = await read_for(f"{base}/stream/2", 3)
        assert video_size(second, tmp_path) == (640, 360)
        assert app.state.ctx.broadcasters[2].running
    finally:
        srv.should_exit = True
        await task


def test_stations_made_before_the_date_was_kept_get_the_earliest_known(tmp_path):
    """Upgrading to 1.15: a station whose first era is still kept gets that
    as when it was made; one whose isn't, the earliest it's known to have
    been on the air (and says it's not exact)."""
    path = tmp_path / "db.sqlite"
    db = Database(path)
    first = db.create_channel(1, "One", [])
    second = db.create_channel(2, "Two", [])
    for channel, reason, made in ((first, "created", 1000), (second, "update", 5000)):
        db.add_era(
            channel.id, [], start_ms=made, epoch_ms=made, seed="s", order_mode="rotate",
            created_ms=made, reason=reason,
        )  # fmt: skip
    db.add_view(second.id, 3000, 4000, [])
    db.close()
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE channels DROP COLUMN created_exact")
    conn.execute("ALTER TABLE channels DROP COLUMN created_ms")
    conn.commit()
    conn.close()
    again = Database(path)
    one, two = again.get_channel(first.id), again.get_channel(second.id)
    assert (one.created_ms, one.created_exact) == (1000, True)
    assert (two.created_ms, two.created_exact) == (3000, False)
    again.close()
    # One left without a date for any other reason gets one at the next start.
    conn = sqlite3.connect(path)
    conn.execute("UPDATE channels SET created_ms = 0 WHERE id = ?", (first.id,))
    conn.commit()
    conn.close()
    assert Database(path).get_channel(first.id).created_ms == 1000


# A program with no sound of its own --------------------------------------


def test_silence_added_for_a_file_with_no_sound_isnt_evened_out():
    """Silence added for a file with no sound has no loudness to even out.
    With FFmpeg 7, evening out sound from a second input (the silence)
    under -shortest holds back the whole stream until the program ends, so
    an episode or break with no sound stalled and was taken off the air."""

    def command(audio_index: int | None) -> str:
        return " ".join(
            ff.program_command(
                Settings(), "/x/film.mkv", 0.0, 12.0, 0.0, 1.0, audio_index, "Test",
                normalize_audio=True,
            )
        )  # fmt: skip

    assert "loudnorm" in command(0)
    assert "loudnorm" not in command(None)


def test_silence_is_made_with_the_picture():
    """The silence under a card, or under a file with no sound, comes from
    the same input or filter graph as the picture, never from an input of
    its own. With FFmpeg 7, a second input of silence under -shortest held
    back a card's stream for seconds at a time, or all of it, so a card or
    a program with no sound could stall and be taken off the air."""
    settings = Settings()
    commands = [
        ff.slate_command(settings, 30.0, 0.0, 0.0, "Test", "Off the air"),
        ff.card_command(settings, 5.0, 0.0, 0.0, "Test", None, ["Up next", "A show", "An episode"]),
        ff.program_command(settings, "/x/film.mkv", 0.0, 12.0, 0.0, 1.0, None, "Test"),
        ff.program_command(
            settings, "/x/film.mkv", 0.0, 12.0, 0.0, 1.0, None, "Test",
            subtitles=ff.Subtitles(stream=0, image=True),
        ),
    ]  # fmt: skip
    for args in commands:
        assert args.count("-i") == 1, args
        assert "anullsrc=channel_layout=stereo:sample_rate=48000" in " ".join(args)


def pictures_sent(data: bytes) -> int:
    """How many video frames start in a stream's bytes."""
    count = 0
    for pos in range(0, len(data) - 187, 188):
        flags = data[pos + 3]
        if data[pos] != 0x47 or not data[pos + 1] & 0x40 or not flags & 0x10:
            continue
        p = pos + 4 + (1 + data[pos + 4] if flags & 0x20 else 0)
        count += data[p : p + 4] in (b"\x00\x00\x01\xe0",)
    return count


async def sent_in(args: list[str], seconds: float) -> bytes:
    """What an ffmpeg sends in its first `seconds`."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    got = b""
    until = time.monotonic() + seconds
    try:
        while (left := until - time.monotonic()) > 0:
            try:
                chunk = await asyncio.wait_for(proc.stdout.read(65536), left)
            except TimeoutError:
                break
            if not chunk:
                break
            got += chunk
    finally:
        proc.kill()
        await proc.wait()
    return got


async def pictures_each_second(args: list[str], seconds: int) -> list[int]:
    """How many pictures an ffmpeg sends in each of its first `seconds`."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    began = time.monotonic()
    counts, sent = [0] * seconds, bytearray()
    try:
        while (left := began + seconds - time.monotonic()) > 0:
            try:
                chunk = await asyncio.wait_for(proc.stdout.read(65536), left)
            except TimeoutError:
                break
            if not chunk:
                break
            whole = len(sent) - len(sent) % 188
            sent += chunk
            second = min(seconds - 1, int(time.monotonic() - began))
            counts[second] += pictures_sent(bytes(sent[whole : len(sent) - len(sent) % 188]))
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
    return counts


@needs_ffmpeg
async def test_a_card_streams_as_it_plays():
    """A card played at real time (no burst: the stream's cushion is full)
    sends its picture from the start, a second's worth every second."""
    settings = Settings(plex_url="", plex_token="", video_width=640, video_height=360)
    args = ff.slate_command(settings, 30.0, 0.0, 0.0, "Test", "This station is off the air.")
    assert pictures_sent(await sent_in(args, 4.0)) >= 60


@needs_ffmpeg
async def test_an_episode_with_no_sound_streams_as_it_plays(tmp_path):
    """An episode with no sound (its sound evened out, as every episode's
    is) sends its stream as it plays, not all at the end."""
    film = tmp_path / "silent.mp4"
    make(
        "-f", "lavfi", "-i", "smptebars=s=640x360:r=25", "-t", "12",
        "-c:v", "libx264", "-preset", "ultrafast", str(film),
    )  # fmt: skip
    settings = Settings(plex_url="", plex_token="", video_width=640, video_height=360)
    probe = await ff.probe(settings, str(film))
    assert probe.ok and probe.audio_index is None
    args = ff.program_command(
        settings, str(film), 0.0, 12.0, 0.0, 0.3, None, "Test", normalize_audio=True,
    )  # fmt: skip
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        # (Played at real time: 12 seconds in all.)
        first = await asyncio.wait_for(proc.stdout.read(188), 6)
        assert first, "nothing was sent"
    finally:
        proc.kill()
        await proc.wait()


# Programs whose sound has a gap, or starts late --------------------------


def test_a_programs_picture_and_sound_are_made_in_one_filter_graph():
    """A program's picture and sound are made in one filter graph, so
    FFmpeg schedules them together. Each in its own (-vf and -af, the sound
    padded with apad under -shortest), FFmpeg 7 hung for good on a file
    whose sound has a gap, or starts a few seconds after its picture. The
    sound comes from a second, unpaced reading of the file."""
    settings = Settings()
    for audio_index in (0, None):
        for subs in (None, ff.Subtitles(stream=0, image=True)):
            args = ff.program_command(
                settings, "/x/film.mkv", 0.0, 12.0, 0.0, 1.0, audio_index, "Test",
                normalize_audio=True, subtitles=subs,
            )  # fmt: skip
            assert "-vf" not in args and "-af" not in args, args
            assert args.count("-filter_complex") == 1
            graph = args[args.index("-filter_complex") + 1]
            assert "[vout]" in graph and "[aout]" in graph
            # The file is read for the picture, paced, and again for its
            # sound, unpaced: sound that's missing never holds the picture
            # back (see the next tests).
            inputs = [n for n, arg in enumerate(args) if arg == "-i"]
            assert [args[n + 1] for n in inputs] == ["/x/film.mkv"] * (
                1 if audio_index is None else 2
            )
            assert args.count("-readrate") == 1 and args.index("-readrate") < inputs[0]
            assert "-discard" not in args
    # A recording, a DVD, or a file from Plex's server: read once. (A
    # recording's or DVD's every stream counted, for where it starts.)
    for source in (
        "/x/news.ts",
        "/x/disc.M2TS",
        "/x/dvd.vob",
        "http://plex/library/parts/1/2/file.mkv?x=1",
    ):
        args = ff.program_command(settings, source, 9.0, 12.0, 0.0, 1.0, 0, "Test")
        assert args.count("-i") == 1 and "[0:a:0]" in args[args.index("-filter_complex") + 1]
        assert ("-discard" in args) == (not source.startswith("http")), source
    assert ff.one_clock("http://plex/library/parts/1/2/file.ts?download=1")
    assert not ff.one_clock("/x/film.mkv") and not ff.one_clock("/x/the.ts.mkv")
    # By what the probe says it is, whatever its name (Plex also lists .vdr recordings).
    assert ff.one_clock("/x/show.vdr", "mpegts") and ff.one_clock("/x/dvd.mkv", "mpeg")
    assert not ff.one_clock("/x/odd.ts", "matroska,webm")
    # A recording's seek, on its own clock where its start is known.
    assert ff.seek_args("/x/news.ts", 7.3, "mpegts", 5001.4) == [
        "-seek_timestamp",
        "1",
        "-ss",
        "5008.700000",
    ]
    assert ff.seek_args("/x/news.ts", 0.0, "mpegts", 5001.4) == []
    assert ff.seek_args("/x/news.ts", 7.3) == ["-discard", "none", "-ss", "7.300"]
    assert ff.seek_args("/x/film.mkv", 7.3, "matroska,webm", 0.0) == ["-ss", "7.300"]
    # (A program ends with its picture, decided as FFmpeg decides it: with a buffer of a
    # second, a commercial cut short left a gap of 1.5 seconds in the picture.)
    assert "-shortest" in args and "-shortest_buf_duration" not in args


async def picture_waits(args: list[str], limit_s: float) -> tuple[float, int, bytes]:
    """Runs an ffmpeg to its end (or for `limit_s`): the longest it went
    without sending a new picture (from its start), how many it sent, and
    what it sent."""
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    began = last = time.monotonic()
    longest, pictures, sent = 0.0, 0, bytearray()
    try:
        while (left := began + limit_s - time.monotonic()) > 0:
            try:
                chunk = await asyncio.wait_for(proc.stdout.read(65536), left)
            except TimeoutError:
                break
            if not chunk:
                break
            whole = len(sent) - len(sent) % 188
            sent += chunk
            more = pictures_sent(bytes(sent[whole : len(sent) - len(sent) % 188]))
            if more:
                now = time.monotonic()
                longest, last, pictures = max(longest, now - last), now, pictures + more
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
    return max(longest, time.monotonic() - last if pictures == 0 else 0.0), pictures, bytes(sent)


@needs_ffmpeg
@pytest.mark.parametrize(
    "sound", ["ends 8 seconds early", "has a 9-second gap", "starts 7 seconds late"]
)
async def test_a_programs_picture_never_waits_for_missing_sound(tmp_path, sound):
    """Played at real time, as a station plays once its cushion is full, a
    program's picture keeps coming while its sound is missing, and the gap is
    silence. (For a file read twice: not a recording, a DVD or a file from
    Plex's server, which are read once: see the next test.) (With FFmpeg 7.1, the image's, the picture waited as long as the
    sound was missing: 8 seconds or more and the station's watchdog took the
    program off the air as stalled.)"""
    film = tmp_path / "film.mkv"
    picture = ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=12"]
    cut: list[str] = []
    if sound.startswith("ends"):
        tone = ["-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=4"]
    elif sound.startswith("has"):
        tone = ["-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=12"]
        cut = ["-af", "aselect='not(between(t,2,11))'"]
    else:
        tone = ["-itsoffset", "7", "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=5"]
    make(
        *picture, *tone, "-map", "0:v", "-map", "1:a", *cut,
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(film),
    )  # fmt: skip
    settings = Settings(plex_url="", plex_token="", video_width=320, video_height=180)
    probe = await ff.probe(settings, str(film))
    assert probe.ok and probe.audio_index is not None
    args = ff.program_command(
        settings, str(film), 0.0, 12.0, 0.0, 0.0, probe.audio_index, "Test", normalize_audio=True,
    )  # fmt: skip
    longest, pictures, sent = await picture_waits(args, 40.0)
    assert longest < 3.0, f"no picture for {longest:.1f} seconds"
    assert pictures >= 330, pictures  # (12 seconds of them)
    out = tmp_path / "out.ts"
    out.write_bytes(sent)
    assert_clean_stream(out)
    probed = await asyncio.to_thread(
        subprocess.run,
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "packet=pts_time",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    times = [float(t.strip(",")) for t in probed.stdout.split()]
    assert times[-1] - times[0] > 11.5, "the sound doesn't run the whole program"


@needs_ffmpeg
@pytest.mark.parametrize("sound", ["a gap", "a late start"])
async def test_a_program_whose_sound_has_a_gap_or_starts_late_plays_to_the_end(tmp_path, sound):
    """Sound with half a second missing at 5 seconds, or starting 4 seconds
    after the picture, is filled with silence, and the program plays to its
    end. (FFmpeg 7 hung at the gap, or before the first frame.)"""
    film = tmp_path / "film.mkv"
    picture = ["-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=12"]
    if sound == "a gap":
        tone = ["-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=12"]
        cut = ["-af", "aselect='not(between(t,5,5.5))'"]
    else:
        tone = ["-itsoffset", "4", "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=8"]
        cut = []
    make(
        *picture, *tone, "-map", "0:v", "-map", "1:a", *cut,
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(film),
    )  # fmt: skip
    settings = Settings(plex_url="", plex_token="", video_width=320, video_height=180)
    probe = await ff.probe(settings, str(film))
    assert probe.ok and probe.audio_index is not None
    out = tmp_path / "out.ts"
    args = ff.program_command(
        settings, str(film), 0.0, 12.0, 0.0, 20.0, probe.audio_index, "Test", normalize_audio=True,
    )  # fmt: skip
    args[args.index("pipe:1")] = str(out)
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        await asyncio.wait_for(proc.wait(), 60)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise AssertionError("it hung") from None
    assert proc.returncode == 0
    assert_clean_stream(out)
    for stream in ("v", "a"):
        probed = await asyncio.to_thread(
            subprocess.run,
            ["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries",
             "packet=pts_time", "-of", "csv=p=0", str(out)],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        times = probed.stdout.split()
        played = float(times[-1].strip(",")) - float(times[0].strip(","))
        assert played > 11.5, (stream, played)


@needs_ffmpeg
async def test_a_recordings_sound_gap_holds_its_picture_no_longer_than_the_gap(tmp_path):
    """A recording (read once: see ff.program_command) whose sound is missing
    for 6 seconds holds its picture back for as long, and for the 3 seconds
    its sound's evening out looks ahead, then catches up and plays to its
    end. (A known limit: a gap over about 5 seconds trips the station's
    8-second stall check, and the program is skipped. 1.31.0 stopped for
    good.)"""
    film = tmp_path / "recording.ts"
    make(
        "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=12",
        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=12",
        "-map", "0:v", "-map", "1:a", "-af", "aselect='not(between(t,3,9))'",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "ac3", str(film),
    )  # fmt: skip
    settings = Settings(plex_url="", plex_token="", video_width=320, video_height=180)
    probe = await ff.probe(settings, str(film))
    args = ff.program_command(
        settings, str(film), 0.0, 12.0, 0.0, 0.0, probe.audio_index, "Test", normalize_audio=True,
        container=probe.container, file_start_s=probe.start_s,
    )  # fmt: skip
    assert args.count("-i") == 1
    longest, pictures, _ = await picture_waits(args, 40.0)
    assert longest < 10.0, f"no picture for {longest:.1f} seconds"
    assert pictures >= 330, pictures


# Recordings (MPEG-TS) and DVDs (MPEG-PS): sound and picture together ----

# A flash every 2 seconds from 0.5 s, flash k (from 1, at 2k - 1.5 s) 40 + 10k
# bright, and a beep with each, beep k 0.05 + 0.04k s long, so each flash is
# matched to its own beep.
_FLASHES = (
    "color=c=black:s=320x180:r=30000/1001:d={d},format=yuv420p,"
    "geq=lum='if(lt(mod(T+1.5,2),0.15),40+10*floor((T+1.5)/2),16)':cb=128:cr=128"
)
_BEEPS = (
    "sine=f=1000:sample_rate=48000:d={d},"
    "volume=volume=0:eval=frame:enable='gte(mod(t+1.5,2),0.05+0.04*floor((t+1.5)/2))'"
)
_X264 = ["-c:v", "libx264", "-preset", "ultrafast", "-bf", "3", "-g", "60", "-sc_threshold", "0"]


def marked(path, seconds: float, sound: str = "", out: list[str] | tuple = ()) -> None:
    """A file of flashes and beeps (see _FLASHES), `sound` applied to its
    beeps (atrim to start them late, say), written with `out`'s options."""
    graph = f"{_FLASHES.format(d=seconds)}[v];{_BEEPS.format(d=seconds)}{sound}[a]"
    make("-filter_complex", graph, "-map", "[v]", "-map", "[a]", *_X264, *out, str(path))


def _flashes(path) -> dict[int, float]:
    run = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-copyts", "-i", str(path), "-map", "0:v:0",
         "-vf", "signalstats,metadata=mode=print:key=lavfi.signalstats.YAVG:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    at, before, found = 0.0, 16.0, {}
    for line in run.stdout.splitlines():
        if "pts_time:" in line:
            at = float(line.split("pts_time:")[1].split()[0])
        elif "YAVG=" in line:
            bright = float(line.split("YAVG=")[1])
            if bright > 30 >= before:
                found.setdefault(round((bright - 40) / 10), at)
            before = bright
    return found


def _beeps(path) -> dict[int, float]:
    run = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-copyts", "-i", str(path), "-map", "0:a:0",
         "-af", "silencedetect=n=-30dB:d=0.02,ametadata=mode=print:file=-", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    ends = [float(x.split("=")[1]) for x in run.stdout.split() if "silence_end=" in x]
    starts = [float(x.split("=")[1]) for x in run.stdout.split() if "silence_start=" in x]
    found = {}
    for end in ends:
        after = [s for s in starts if s > end]
        if after:
            found.setdefault(round((after[0] - end - 0.05) / 0.04), end)
    return found


def first_picture_s(path) -> float:
    run = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
         "-of", "csv=p=0", "-read_intervals", "%+#1", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(run.stdout.split()[0].strip(","))


async def played_as(settings, film, offset_s: float, seconds: float, out) -> None:
    """`seconds` of `film` from `offset_s`, as a station plays it, into `out`."""
    probe = await ff.probe(settings, str(film))
    assert probe.ok and probe.audio_index is not None
    args = ff.program_command(
        settings, str(film), offset_s, seconds, 0.0, 100.0, probe.audio_index, "Test",
        video_index=probe.video_index, container=probe.container, file_start_s=probe.start_s,
    )  # fmt: skip
    args[args.index("pipe:1")] = str(out)
    done = await asyncio.to_thread(subprocess.run, args, capture_output=True, timeout=120)
    assert done.returncode == 0, done.stderr[-400:]


@needs_ffmpeg
@pytest.mark.parametrize(
    "recording",
    [
        "its picture starts first",
        "a second sound track starts first",
        "its sound starts first",
    ],
)
async def test_a_recording_joined_part_way_starts_at_once_with_its_sound_together(
    tmp_path, recording
):
    """A recording (MPEG-TS, its clock far from zero, as a tuner's is) joined
    7.3 seconds in, as when someone tunes in or a station comes back from a
    break: its picture starts at once, and each flash comes with its own beep.
    (With its sound read apart from its picture, FFmpeg misplaced where one of
    them starts: the picture waited 8 seconds, then ran 7 seconds behind the
    sound. Read once, a second sound track starting first made both late.)"""
    film = tmp_path / "recording.ts"
    clock = ["-output_ts_offset", "5000", "-c:a", "ac3"]
    if recording == "its picture starts first":
        marked(film, 20, ",atrim=start=0.3", clock)
    elif recording == "its sound starts first":
        graph = (
            f"{_FLASHES.format(d=20)},trim=start=0.4,setpts=PTS-STARTPTS+0.4/TB[v];"
            f"{_BEEPS.format(d=20)}[a]"
        )
        make("-filter_complex", graph, "-map", "[v]", "-map", "[a]", *_X264, *clock, str(film))
    else:
        graph = (
            f"{_FLASHES.format(d=20)}[v];{_BEEPS.format(d=20)},asplit[a][b];"
            "[a]atrim=start=0.2[late]"
        )
        make(
            "-filter_complex", graph, "-map", "[v]", "-map", "[late]", "-map", "[b]",
            *_X264, *clock, str(film),
        )  # fmt: skip
    settings = Settings(plex_url="", plex_token="", video_width=320, video_height=180)
    out = tmp_path / "out.ts"
    await played_as(settings, film, 7.3, 10.0, out)
    flashes, beeps = _flashes(out), _beeps(out)
    # Flash 5, at 8.5 s in the file, comes 1.2 s into the program.
    assert 5 in flashes and abs(flashes[5] - first_picture_s(out) - 1.2) < 0.1, (
        flashes,
        first_picture_s(out),
    )
    together = {k: round((beeps[k] - flashes[k]) * 1000) for k in flashes if k in beeps}
    assert len(together) >= 4, (flashes, beeps)
    assert all(abs(ms) <= 60 for ms in together.values()), together


@needs_ffmpeg
@pytest.mark.parametrize("offset_s", [0.0, 5.0, 7.3])
async def test_a_recording_whose_subtitles_start_first_plays_from_where_its_joined(
    tmp_path, offset_s
):
    """A recording whose subtitle stream starts 1.5 seconds before its
    picture and sound (as DVB subtitles and teletext can) plays from where
    it's joined, at once. (Counting every stream for where it starts, FFmpeg
    took a start its own reading ignores, and dropped the join: the whole
    program a frozen picture and silence.)"""
    from . import vobsub

    subs = vobsub.write(tmp_path / "early", [(0.5, 1.5), (7.5, 8.5)])
    film = tmp_path / "recording.ts"
    graph = f"{_FLASHES.format(d=20)},setpts=PTS+2/TB[v];{_BEEPS.format(d=20)},asetpts=PTS+2/TB[a]"
    make(
        "-i", str(subs), "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-map", "0:s",
        *_X264, "-c:a", "ac3", "-c:s", "dvbsub", "-output_ts_offset", "5000", str(film),
    )  # fmt: skip
    settings = Settings(plex_url="", plex_token="", video_width=320, video_height=180)
    out = tmp_path / "out.ts"
    await played_as(settings, film, offset_s, 10.0, out)
    flashes, beeps = _flashes(out), _beeps(out)
    # The first flash after the join: flash k is 2k - 1.5 s into the picture and sound,
    # where the recording starts (its subtitles, starting earlier, don't count).
    k = next(k for k in range(1, 12) if 2 * k - 1.5 >= offset_s + 0.2)
    due = 2 * k - 1.5 - offset_s
    assert k in flashes and abs(flashes[k] - first_picture_s(out) - due) < 0.1, (k, due, flashes)
    together = {n: round((beeps[n] - flashes[n]) * 1000) for n in flashes if n in beeps}
    assert len(together) >= 3 and all(abs(ms) <= 60 for ms in together.values()), together


@needs_ffmpeg
async def test_a_recording_with_a_jump_in_its_clock_keeps_its_sound_with_its_picture(tmp_path):
    """A spliced recording whose clock jumps 50,000 seconds part-way, its
    picture ending a moment before its sound in the first part, keeps each
    flash with its beep after the jump. (Read twice, FFmpeg mended the jump
    differently for the picture and for the sound: half a second apart.)"""
    first, second, film = tmp_path / "1.ts", tmp_path / "2.ts", tmp_path / "recording.ts"
    graph = f"{_FLASHES.format(d=24)},trim=end=9.5[v];{_BEEPS.format(d=24)},atrim=end=10[a]"
    make("-filter_complex", graph, "-map", "[v]", "-map", "[a]", *_X264, "-c:a", "ac3", str(first))
    graph = (
        f"{_FLASHES.format(d=24)},trim=start=10,setpts=PTS-STARTPTS[v];"
        f"{_BEEPS.format(d=24)},atrim=start=10,asetpts=PTS-STARTPTS[a]"
    )
    make(
        "-filter_complex", graph, "-map", "[v]", "-map", "[a]", *_X264, "-c:a", "ac3",
        "-output_ts_offset", "50000", str(second),
    )  # fmt: skip
    film.write_bytes(first.read_bytes() + second.read_bytes())
    settings = Settings(plex_url="", plex_token="", video_width=320, video_height=180)
    out = tmp_path / "out.ts"
    await played_as(settings, film, 0.0, 23.0, out)
    flashes, beeps = _flashes(out), _beeps(out)
    # (Flash 6, at 10.5 s, is the first after the jump.)
    after = {k: round((beeps[k] - flashes[k]) * 1000) for k in flashes if k >= 6 and k in beeps}
    assert len(after) >= 4, (flashes, beeps)
    assert all(abs(ms) <= 150 for ms in after.values()), after
