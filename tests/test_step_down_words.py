"""A step down in quality, said in the log only when there is one, and the
connection named as why only when it is (the owner, October 14: "switched
… to a smaller version … to fit its connection (about 908.8 Mbps)" when an
episode went from a converted copy back to its own 2.6 Mbps file)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex
from .test_languages import TIA, TV, bearer


@pytest.fixture
def app(tmp_path):
    fp = LibraryPlex()
    fp.add_show("100", "Orbit Room")
    fp.add_episode("201", "100", 1, 1, "Pilot", "/x/1.mkv", 22 * 60_000)
    fp.describe("201")
    fp.media["201"]["bitrate"] = 2600  # (1080p at 2.6 Mbps, as the owner's episode)
    fp.streams["201"][1:] = [
        {"id": 2012, "streamType": 2, "codec": "aac", "channels": 2, "language": "English",
         "languageCode": "eng", "default": True, "index": 1},
        {"id": 2015, "streamType": 3, "codec": "pgs", "language": "English",
         "languageCode": "eng", "index": 2},
    ]  # fmt: skip
    fp.files["201"] = b"a program, as it is" * 100
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "A Film", "/x/film.mkv", 90 * 60_000, section="2")
    fp.describe("300")  # (1080p at 8 Mbps)
    fp.add_version("300", 1280, 720, bitrate=4000)
    fp.files["300"] = b"a program, as it is" * 100
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "d")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    app.state.ctx.play_transport = fp.transport()
    return app


def said(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if " switched " in r.getMessage()
            or " started " in r.getMessage()]  # fmt: skip


def test_back_to_its_own_file_is_no_step_down(app, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as home:
        home.post("/api/access/users", json=TIA)
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        tia = bearer(home, TIA)
        # Subtitles this TV can't show (pictures), drawn in: a converted copy, at 8 Mbps.
        drawn = home.post("/api/internal/play", headers=tia, json={
            "key": "201", "device": TV, "subtitle": "2015", "maxKbps": 908_800})  # fmt: skip
        assert drawn.status_code == 200 and drawn.json()["method"] == "convert", drawn.text
        caplog.clear()
        # Subtitles off: its own file, as it is. (Every app sends the
        # connection it measured with every play, `maxKbps`.)
        off = home.post("/api/internal/play", headers=tia, json={
            "key": "201", "device": TV, "maxKbps": 908_800})  # fmt: skip
        assert off.status_code == 200 and off.json()["method"] == "direct", off.text
        # Not smaller: the copy was made from this file, and holds no more than it.
        assert said(caplog) == [
            "Tia started Orbit Room · S1 E1 in a tapiOca app, at home: 1.mkv (1080p H.264, "
            "stereo AAC) from Plex, playing as it is"
        ]


def test_the_connection_is_why_only_when_it_is(app, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as home:
        home.post("/api/access/users", json=TIA)
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        tia = bearer(home, TIA)
        first = home.post("/api/internal/play", headers=tia, json={
            "key": "300", "device": TV, "maxKbps": 908_800})  # fmt: skip
        assert first.status_code == 200, first.text
        caplog.clear()
        # The 720p version, chosen in the app: the connection carries far more.
        smaller = home.post("/api/internal/play", headers=tia, json={
            "key": "300", "device": TV, "version": "30001", "maxKbps": 908_800})  # fmt: skip
        assert smaller.status_code == 200, smaller.text
        assert said(caplog) == [
            "Tia's tapiOca app at home (192.168.1.50) switched A Film (2000) to a smaller version, "
            "from 1080p at 8 Mbps to 720p at 4 Mbps: the app asked for it"
        ]


@pytest.fixture
def copied_film(tmp_path):
    """A 1080p film at 2.6 Mbps with a picture subtitle (drawn in, so it plays as an 8 Mbps
    converted copy), and its 720p version at 4 Mbps."""
    fp = LibraryPlex()
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "A Film", "/x/film.mkv", 90 * 60_000, section="2")
    fp.describe("300")
    fp.media["300"]["bitrate"] = 2600
    fp.streams["300"].append(
        {"id": 3005, "streamType": 3, "codec": "pgs", "language": "English",
         "languageCode": "eng", "index": 2}
    )  # fmt: skip
    fp.add_version("300", 1280, 720, bitrate=4000)
    fp.files["300"] = b"a program, as it is" * 100
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "d")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    app.state.ctx.play_transport = fp.transport()
    return app


def test_a_step_down_from_a_copy_says_the_connection_when_its_why(copied_film, caplog):
    """1.36.4's second audit, with the owner's yes (October 14): a converted copy sends what
    it's made at (8 Mbps here), whatever its file holds (2.6 Mbps). Stepping down from it
    on a 6 Mbps connection is to fit the connection, as 1.36.3 said; the handoff's fix,
    taking the copy as its file's 2.6 Mbps, said "the app asked for it"."""
    caplog.set_level(logging.INFO)
    with TestClient(copied_film) as home:
        home.post("/api/access/users", json=TIA)
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        tia = bearer(home, TIA)
        drawn = home.post("/api/internal/play", headers=tia, json={
            "key": "300", "device": TV, "subtitle": "3005", "maxKbps": 6_000})  # fmt: skip
        assert drawn.status_code == 200 and drawn.json()["method"] == "convert", drawn.text
        caplog.clear()
        smaller = home.post("/api/internal/play", headers=tia, json={
            "key": "300", "device": TV, "version": "30001", "maxKbps": 6_000})  # fmt: skip
        assert smaller.status_code == 200, smaller.text
        [line] = [m for m in said(caplog) if " switched " in m]
        assert " to a smaller version, from 1080p H.264 at 8 Mbps " in line, line
        assert line.endswith(": to fit its connection (about 6 Mbps)"), line
