"""Intro Bumpers you make yourself: uploading them, choosing one for a
station, and what plays when someone tunes in."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .test_e2e import assert_clean_stream, record, start_server
from .test_e2e_breaks import colour_of, frames
from .test_intro import media

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
FRAME_S = 1001 / 30000


def video(path: Path, seconds: float, colour: str = "magenta", sound: bool = True) -> bytes:
    """A 4:3 video (so it needs black bars), with a tone or no sound."""
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={colour}:s=320x240:r=25"]
    if sound:
        args += ["-f", "lavfi", "-i", "sine=f=1000:sample_rate=44100", "-c:a", "aac"]
    args += ["-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", str(path)]
    subprocess.run(args, check=True)
    return path.read_bytes()


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return json.loads(out)


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


def upload(client, data: bytes, name: str = "My Bumper.mov"):
    return client.post(f"/api/bumpers?name={name}", content=data)


def station(client, number: int, **extra):
    body = {"number": number, "sources": [{"type": "show", "ratingKey": "100"}], **extra}
    return client.post("/api/channels", json=body)


def test_an_uploaded_video_becomes_a_bumper(client, tmp_path):
    made = upload(client, video(tmp_path / "in.mp4", 4))
    assert made.status_code == 201, made.text
    bumper = made.json()
    assert bumper["name"] == "My Bumper" and abs(bumper["seconds"] - 4) < 0.1
    assert client.get("/api/bumpers").json() == [bumper]
    got = client.get(f"/bumpers/{bumper['id']}.mp4")
    assert got.status_code == 200 and got.headers["content-type"] == "video/mp4"
    # Kept as a clean copy the size of the biggest picture a station can
    # have (1080p; here, the tests' smaller version of it), with black bars,
    # at the stream's frame rate, with stereo sound.
    kept = tmp_path / "data" / "bumpers" / f"{bumper['id']}.mp4"
    assert kept.read_bytes() == got.content
    info = probe(kept)
    streams = {s["codec_type"]: s for s in info["streams"]}
    v, a = streams["video"], streams["audio"]
    for length in (info["format"]["duration"], v["duration"], a["duration"]):
        assert abs(float(length) - bumper["seconds"]) < 0.05  # sound and picture alike
    assert (v["codec_name"], v["width"], v["height"], v["r_frame_rate"]) == (
        "h264", 960, 540, "30000/1001",
    )  # fmt: skip
    assert (a["codec_name"], a["channels"], a["sample_rate"]) == ("aac", 2, "48000")
    left_bar, middle = frames(kept, "40:40:20:160")[10], frames(kept, "40:40:300:160")[10]
    assert colour_of(*left_bar) == "dark" and colour_of(*middle) == "magenta"
    # Nothing's left behind from the upload.
    assert sorted(p.name for p in kept.parent.iterdir()) == [
        f"{bumper['id']}.json", f"{bumper['id']}.mp4",
    ]  # fmt: skip


def test_a_video_without_sound_gets_silence(client, tmp_path):
    bumper = upload(client, video(tmp_path / "in.mp4", 2, sound=False), "quiet").json()
    kept = tmp_path / "data" / "bumpers" / f"{bumper['id']}.mp4"
    info = probe(kept)
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}
    assert abs(float(info["format"]["duration"]) - 2) < 0.05
    assert bumper["name"] == "quiet"


def test_what_cant_be_a_bumper_is_turned_away(client, tmp_path):
    assert upload(client, b"").status_code == 400
    bad = upload(client, b"this is not a video" * 100)
    assert bad.status_code == 400 and "can't play that file" in bad.json()["detail"]
    long = upload(client, video(tmp_path / "long.mp4", 35))
    assert long.status_code == 400 and "35 seconds long" in long.json()["detail"]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1",
         str(tmp_path / "still.png")],
        check=True,
    )  # fmt: skip
    # A picture isn't a video (ffmpeg reads only videos from an upload).
    still = upload(client, (tmp_path / "still.png").read_bytes(), "still.png")
    assert still.status_code == 400 and "can't play that file" in still.json()["detail"]
    short = upload(client, video(tmp_path / "short.mp4", 0.5))
    assert short.status_code == 400 and "too short" in short.json()["detail"]
    assert client.get("/api/bumpers").json() == []
    assert [p.name for p in (tmp_path / "data" / "bumpers").iterdir()] == []


def test_a_station_plays_a_bumper_you_choose(client, tmp_path):
    bumper = upload(client, video(tmp_path / "in.mp4", 3)).json()
    assert station(client, 1, introVideo="bumper-0123456789").status_code == 400
    made = station(client, 1, introVideo=bumper["id"])
    assert made.status_code == 201, made.text
    assert made.json()["introVideo"] == bumper["id"]
    # Not while a station plays it.
    gone = client.delete(f"/api/bumpers/{bumper['id']}")
    assert gone.status_code == 409 and "station 1" in gone.json()["detail"]
    # If its files go missing, the station can still be saved as it is.
    folder = tmp_path / "data" / "bumpers"
    for p in folder.iterdir():
        p.unlink()
    assert client.get("/api/bumpers").json() == []
    cid = made.json()["id"]
    body = {"number": 1, "sources": made.json()["sources"], "introVideo": bumper["id"]}
    assert client.put(f"/api/channels/{cid}", json=body).status_code == 200
    body["introVideo"] = ""
    assert client.put(f"/api/channels/{cid}", json=body).json()["introVideo"] == ""
    assert client.delete(f"/api/bumpers/{bumper['id']}").status_code == 404
    assert client.get(f"/bumpers/{bumper['id']}.mp4").status_code == 404
    other = upload(client, video(tmp_path / "in.mp4", 3)).json()
    assert client.delete(f"/api/bumpers/{other['id']}").status_code == 204
    assert client.get("/api/bumpers").json() == []


async def test_tuning_in_plays_your_own_video(tmp_path, caplog):
    """Your video, then the show (where the schedule has got to by then);
    and if the video has gone missing or won't play, StationPlay's own
    bumper instead."""
    plex = media(tmp_path)
    base, _app, _settings, srv, task = await start_server(
        tmp_path, plex, media_dir=str(tmp_path / "media")
    )
    data_dir = tmp_path / "data"
    try:
        async with httpx.AsyncClient(base_url=base, timeout=60) as client:
            ids = []
            for n in range(3):
                made = await client.post(
                    f"/api/bumpers?name=mine-{n}", content=video(tmp_path / f"{n}.mp4", 4)
                )
                assert made.status_code == 201, made.text
                ids.append(made.json()["id"])
            for number, bumper in ((5, ids[0]), (6, ids[1]), (7, ids[2])):
                made = await client.post(
                    "/api/channels",
                    json={"number": number, "orderMode": "rotate", "introVideo": bumper,
                          "sources": [{"type": "show", "ratingKey": "100"}]},
                )  # fmt: skip
                assert made.status_code == 201, made.text
        for p in (data_dir / "bumpers").glob(f"{ids[1]}.*"):
            p.unlink()  # station 6's has gone missing
        (data_dir / "bumpers" / f"{ids[2]}.mp4").write_bytes(b"not a video" * 1000)  # 7's broke
        own = await record(f"{base}/stream/5", 10)
        stand_in = await record(f"{base}/stream/6", 10)
        broken = await record(f"{base}/stream/7", 10)
    finally:
        srv.should_exit = True
        await task
    shows = {"yellow", "cyan"}
    for name, data in (("own", own), ("stand-in", stand_in), ("broken", broken)):
        out = tmp_path / f"{name}.ts"
        out.write_bytes(data)
        assert_clean_stream(out)
    seen = [colour_of(*f) for f in frames(tmp_path / "own.ts", "64:48:300:150")]
    n = round(4 / FRAME_S)
    assert set(seen[: n - 3]) == {"magenta"}, seen[:n]
    assert seen[n + 3] in shows
    assert "Intro Bumper video is missing" in caplog.text and "wouldn't play" in caplog.text
    # StationPlay's own bumper (5 seconds) stands in, then the show.
    for name in ("stand-in", "broken"):
        seen = [colour_of(*f) for f in frames(tmp_path / f"{name}.ts", "64:48:20:20")]
        n = round(5 / FRAME_S)
        assert not (shows | {"magenta"}) & set(seen[: n - 3]), (name, seen[:n])
        assert seen[n + 3] in shows, name


def test_what_an_interrupted_upload_left_is_cleared(tmp_path):
    from app.bumpers import BumperLibrary

    folder = tmp_path / "bumpers"
    folder.mkdir()
    for name in (".upload-0123456789", ".bumper-0123456789.mp4", "bumper-0123456789.json"):
        (folder / name).write_text("x")
    BumperLibrary(folder).clear_leftovers()
    assert [p.name for p in folder.iterdir()] == ["bumper-0123456789.json"]
