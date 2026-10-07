"""How stations play: picture sizes, the tuners (how many stations play at
once, and the card shown when they're all in use), and the speed test."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sqlite3
import subprocess

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
    assert (got.picture, got.tuners, got.welcomed) == ("720p", 4, False)
    got = playback.save(db, picture="1080p", tuners=6, welcomed=True)
    assert (got.picture, got.tuners, got.welcomed) == ("1080p", 6, True)
    for bad in ({"picture": "4K"}, {"tuners": 0}, {"tuners": playback.MOST_TUNERS + 1}):
        with pytest.raises(ValueError):
            playback.save(db, **bad)
    assert playback.load(db).tuners == 6
    # Plex is told of more, so StationPlay can say when they're all in use.
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
        "StationPlay can play only 1 station at a time",
        "On now: Station 3. Try again soon, or ask whoever runs StationPlay to add more tuners.",
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


def test_new_stations_start_with_what_the_welcome_chose(client, monkeypatch):
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", False)
    got = client.get("/api/playback").json()
    assert got["newStation"] == {} and not got["welcomed"] and not got["welcomedBefore"]
    chosen = {
        "subtitles": "forced", "breaks": 2, "stationId": True, "idSeconds": 5,
        "introSeconds": 0, "upNextSeconds": 3, "watermark": "clock", "watermarkPosition": "top-right",
    }  # fmt: skip
    saved = client.put("/api/playback", json={"newStation": chosen, "welcomed": True}).json()
    assert saved["newStation"] == chosen and saved["welcomed"]
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


def test_the_welcome_comes_back_once_when_it_has_new_choices(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    db.set_meta(playback.META_WELCOMED, "1")  # (1.14's)
    got = playback.load(db)
    assert not got.welcomed and got.welcomed_before
    assert playback.save(db, welcomed=True).welcomed
    assert db.get_meta(playback.META_WELCOMED) == playback.WELCOME
    # Something odd in what new stations start with is left out.
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
    async with httpx.AsyncClient(timeout=30) as client, client.stream("GET", url) as response:
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
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
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
