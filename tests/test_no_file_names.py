"""Nothing StationPlay's apps receive names a file or a folder: not play
answers, item details, versions, tracks, problems echoed back, alerts or
errors, nor what's inside a copy or a station's stream. (An Admin's page and
the log may name them. A file played as it is is the file, as it is.)"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import ondemand
from app.catalog import Track
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .fakeplex_library import LibraryPlex
from .test_e2e import record, start_server

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
# In every name this test gives a file or a folder, and in what the files
# say about themselves.
MARK = "Hidden.Name"
PHONE = {
    "containers": ["mp4", "mkv"],
    "video": [{"codec": "h264", "width": 1920, "height": 1080, "bitDepth": 8}],
    "hdr": [],
    "audio": ["aac"],
    "hls": ["ts"],
    "subtitles": ["srt"],
}


def test_a_track_named_like_a_file_is_listed_without_it():
    named = Track("1", "aac", "English", title=f"{MARK}.2010.1080p.BluRay.mkv", channels=2)
    assert ondemand.track_name(named, True) == "English · AAC · Stereo"
    for title in (f"{MARK}.2010.1080p", f"/media/films/{MARK}", r"C:\films\a", "film_2010_1080p",
                  "en.forced.srt"):  # fmt: skip
        assert ondemand.track_name(Track("2", "srt", "English", title=title), False) == "English"
    # Titles people give tracks stay.
    for title in ("Commentary", "Director's Commentary", "SDH", "Dolby Digital 5.1", "Mr.Smith"):
        shown = ondemand.track_name(Track("3", "srt", "English", title=title), False)
        assert shown == f"English · {title}"


def make_film(folder: Path) -> Path:
    """A short film whose file, folder, title and tracks are all named
    MARK, as release tools name them."""
    folder.mkdir(parents=True)
    subs = folder / f"{MARK}.2010.en.srt"
    subs.write_text("1\n00:00:01,000 --> 00:00:04,000\nHello\n")
    film = folder / f"{MARK}.2010.1080p.mkv"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "testsrc2=size=320x180:rate=24:duration=8", "-f", "lavfi", "-i",
         "sine=frequency=440:sample_rate=48000:duration=8", "-i", str(subs),
         "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "ac3", "-c:s", "srt", "-metadata", f"title={film.name}",
         "-metadata:s:a:0", f"title={film.name}", "-metadata:s:s:0", f"title={subs.name}",
         "-metadata:s:v:0", f"title={film.stem}", str(film)],
        check=True,
    )  # fmt: skip
    return film


@pytest.fixture
def library(tmp_path):
    fp = LibraryPlex()
    fp.add_section("2", "Movies", "movie")
    if shutil.which("ffmpeg"):
        film = make_film(tmp_path / MARK)
        fp.add_movie("700", "A Quiet Film", str(film), 8_000, section="2")
        fp.describe("700", audio="ac3", width=320, height=180)
        fp.add_subtitles("700", "srt", "English")
        fp.add_subtitles(
            "700", "srt", "English", external=b"1\n00:00:01,000 --> 00:00:02,000\nHi\n"
        )
        # What Plex says of the tracks: the titles the file gives them.
        for stream in fp.streams["700"]:
            stream["title"] = f"{MARK}.2010.1080p.mkv"
        fp.files["700"] = film.read_bytes()
    fp.add_movie("701", "Gone Missing", str(tmp_path / MARK / f"{MARK}.gone.mkv"), 8_000,
                 section="2")  # fmt: skip
    fp.describe("701", width=320, height=180)
    return fp


@pytest.fixture
def app(library, tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(
        settings, PlexClient("http://plex.test", "token", transport=library.transport())
    )
    app.state.ctx.play_transport = library.transport()
    return app


def told(answer: httpx.Response) -> str:
    """Everything an app is told in an answer but a file played as it is:
    its status line's text, its headers and what it carries."""
    head = " ".join(f"{k}: {v}" for k, v in answer.headers.items())
    return f"{answer.reason_phrase} {head} {answer.content.decode('latin-1')}"


@needs_ffmpeg
def test_nothing_an_app_receives_names_a_file(app, library):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        answers = [
            home.get("/api/v1/server"),
            home.get("/api/internal/libraries"),
            home.get("/api/internal/libraries/2"),
            home.get("/api/internal/home"),
            home.get("/api/internal/search?q=quiet"),
            home.get("/api/internal/items/700"),
            home.get("/api/internal/items/701"),
            home.get("/api/internal/alerts"),
            home.get("/api/internal/me"),
            home.post("/api/internal/problem", json={"kind": "library-failed",
                                                     "title": "A Quiet Film", "detail": "x"}),
        ]  # fmt: skip
        details = answers[5].json()
        assert {t["name"] for t in details["audio"]} == {"English · Dolby Digital · 5.1"}
        assert {t["name"] for t in details["subtitles"]} == {"English"}
        # Played as it is: the play answer (its file's bytes are the file's own).
        direct = home.post("/api/internal/play", json={"key": "700", "device": {
            **PHONE, "audio": ["aac", "ac3"]}})  # fmt: skip
        assert direct.json()["method"] == "direct"
        answers.append(direct)
        answers.append(home.head(direct.json()["url"]))
        external = next(s for s in direct.json()["subtitles"] if s["url"])
        answers.append(home.get(external["url"]))
        # Copies: repackaged (its sound converted), converted (subtitles drawn
        # in), and converted as the app asked; their playlists and pieces.
        inside = next(s for s in direct.json()["subtitles"] if not s["external"])
        for asked in ({}, {"subtitle": inside["id"]}, {"convert": True}):
            copy = home.post("/api/internal/play", json={"key": "700", "device": PHONE, **asked})
            assert copy.status_code == 200, copy.text
            here = copy.json()["url"].rsplit("/", 1)[0]
            answers += [copy, home.get(copy.json()["url"]), home.get(f"{here}/piece-0.ts")]
            assert answers[-1].status_code == 200
        # A file only Plex has (from Plex, then), and refusals: nothing there,
        # not understood, an address that's ended.
        answers += [
            home.post("/api/internal/play", json={"key": "701", "device": PHONE, "convert": True}),
            home.post("/api/internal/play", json={"key": "999", "device": PHONE}),
            home.post("/api/internal/play", json={"key": "700", "device": "x"}),
            home.get("/play/nothing/file.mkv"),
        ]
        assert [a.status_code for a in answers[-3:]] == [404, 400, 404]
        for answer in answers:
            assert MARK not in told(answer), (answer.request.url, told(answer)[:400])


@needs_ffmpeg
async def test_a_stations_stream_never_names_its_files(tmp_path):
    film = make_film(tmp_path / MARK)
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    plex.add_episode("201", "100", 1, 1, "Pilot", str(film), 8_000)
    base, _app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post("/api/channels", json={
                "number": 7, "name": "Test TV", "sources": [{"type": "show", "ratingKey": "100"}]})  # fmt: skip
            assert made.status_code == 201, made.text
            stream = await record(f"{base}/stream/7", 6)
            assert len(stream) > 100_000
            assert MARK.encode() not in stream
            for path in ("/api/v1/stations", "/api/v1/guide", "/api/v1/server"):
                assert MARK not in (await client.get(path)).text, path
    finally:
        srv.should_exit = True
        await task
