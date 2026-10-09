"""What's playing, in the Logs and on the Stats tab: the log's lines about
programs starting, stepping down and stopping (each station named, each
file and how it plays); the apps' viewing counted for whoever is signed in
on them, stations and Media alike; who's watching now; and the most watched
people and Media, for Admins only."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import applibrary, converting, playing, stats
from app.broadcaster import Broadcaster, NowPlaying, Viewer
from app.config import Settings
from app.db import Item
from app.ffmpeg import CPU, Encoder, ProbeResult, Subtitles
from app.main import create_app
from app.plex import PlexClient
from app.sources import ResolvedSource

from .fakeplex_library import LibraryPlex
from .test_e2e import make_channel, start_server
from .test_hls import two_episode_show

PAT = {"name": "Pat", "password": "correct horse"}
BO = {"name": "Bo", "password": "bo password", "role": "user"}
DEN = {"app": "StationPlay for Android TV", "deviceName": "Den"}
TV = {
    "containers": ["mkv", "mp4", "ts"],
    "video": [
        {"codec": "h264", "width": 3840, "height": 2160, "bitDepth": 8},
        {"codec": "hevc", "width": 3840, "height": 2160, "bitDepth": 10},
    ],
    "hdr": [],
    "audio": ["aac", "ac3", "eac3"],
    "hls": ["ts"],
}
PHONE = {
    "containers": ["mp4"],
    "video": [{"codec": "h264", "width": 1920, "height": 1080, "bitDepth": 8}],
    "hdr": [],
    "audio": ["aac"],
    "hls": ["ts"],
}


# How the log names things ----------------------------------------------------------


def test_a_station_is_named_with_its_number():
    assert playing.station(2, "Cartoon Classics") == "station 2, Cartoon Classics"
    assert playing.station(2, "Cartoon Classics", mid=True) == "station 2, Cartoon Classics,"
    # Its number alone, when its name says no more.
    assert playing.station(2, "Station 2", mid=True) == "station 2"
    assert playing.station(2, "  ") == "station 2"
    assert playing.picture_and_sound(1920, 1080, "h264", "", 6, "eac3") == "1080p H.264, 5.1 E-AC-3"
    assert playing.picture_and_sound(3840, 2160, "hevc", "HDR10", 8, "truehd") == (
        "4K HEVC HDR10, 7.1 TrueHD"
    )
    assert playing.picture_and_sound(720, 480, "mpeg2video", "", 0, "") == "480p MPEG-2, no sound"
    assert playing.file_name("/data/tv/Northbound/Season 2/northbound.s02e04.mkv") == (
        "northbound.s02e04.mkv"
    )
    assert playing.file_name("http://plex:32400/library/parts/7/1/file.mkv?X-Plex-Token=x") == (
        "file.mkv"
    )
    assert [playing.minutes(s) for s in (20, 35 * 60, 80 * 60, 120 * 60)] == [
        "less than a minute",
        "35 min",
        "1 hr 20 min",
        "2 hr",
    ]


def test_an_app_is_named_by_who_and_where():
    """(What the HLS lines say: "An app on <address> is watching..." read
    wrongly when the address was an app away from home's.)"""
    home = playing.Watcher("192.168.1.20", False, "Pat", 1, "StationPlay for Roku on Den")
    assert home.subject() == "Pat's StationPlay for Roku on Den at home (192.168.1.20)"
    away = playing.Watcher("203.0.113.7", True, "insertdisc", 2, "", "HJ1mNj")
    assert away.subject() == "insertdisc's app away from home (HJ1mNj)"
    unknown = playing.Watcher("192.168.1.30")
    assert unknown.subject() == "An app at home (192.168.1.30)"
    assert unknown.subject(start=False) == "an app at home (192.168.1.30)"
    nameless = playing.Watcher("10.0.0.5", False, "Kit", 3, "A StationPlay app on Bedroom")
    assert nameless.subject() == "Kit's StationPlay app on Bedroom at home (10.0.0.5)"


# A station's program starting ------------------------------------------------------


EPISODE = Item(0, 0, 3_000_000, "204", "episode", "Dead Reckoning", "Northbound", "100", 2, 4)
FILE = ResolvedSource(
    "/media/tv/Northbound/Season 2/northbound.s02e04.mkv",
    plex_file="/data/tv/Northbound/Season 2/northbound.s02e04.mkv",
)
HDR_FILE = ProbeResult(
    ok=True, width=3840, height=2160, video_codec="hevc", hdr="smpte2084",
    audio_codec="eac3", audio_channels=6,
)  # fmt: skip
FILE_1080 = ProbeResult(
    ok=True, width=1920, height=1080, video_codec="h264", audio_codec="ac3", audio_channels=6
)


def a_station(tone_mapping: bool = True) -> Broadcaster:
    ctx = SimpleNamespace(settings=Settings(), tone_mapping=tone_mapping)
    b = Broadcaster(ctx, 1)  # type: ignore[arg-type]
    b._number, b._name = 2, "Cartoon Classics"
    b.now_playing = NowPlaying(1_000, EPISODE, EPISODE, False)
    return b


def said(caplog, do) -> list[str]:
    caplog.clear()
    do()
    return [r.getMessage() for r in caplog.records if r.name == "app.broadcaster"]


def test_a_program_starting_says_its_file_and_how_it_plays(caplog):
    caplog.set_level(logging.INFO)
    b = a_station()
    b._tuned_in = False
    gpu = Encoder("vaapi", "/dev/dri/renderD128")
    assert said(caplog, lambda: b._announce(EPISODE, 0.4, FILE, HDR_FILE, None, gpu)) == [
        "Station 2, Cartoon Classics: Northbound S02E04 “Dead Reckoning” starts "
        "(northbound.s02e04.mkv: 4K HEVC HDR10, 5.1 E-AC-3), made 720p at 3.5 Mbps on the "
        "Intel/AMD GPU, HDR made ordinary"
    ]
    # Once for each program: not again as it goes on, but if it moves to the CPU.
    assert said(caplog, lambda: b._announce(EPISODE, 600, FILE, HDR_FILE, None, gpu)) == []
    assert said(caplog, lambda: b._announce(EPISODE, 610, FILE, HDR_FILE, None, CPU)) == [
        "Station 2, Cartoon Classics: Northbound S02E04 “Dead Reckoning” carries on from 10:10 "
        "(northbound.s02e04.mkv: 4K HEVC HDR10, 5.1 E-AC-3), made 720p at 3.5 Mbps on the CPU, "
        "HDR made ordinary"
    ]


def test_tuning_in_is_said_with_the_program_it_joins(caplog):
    caplog.set_level(logging.INFO)
    b = a_station()
    b._tuned_in = True  # (someone's just tuned in)
    subs = Subtitles(path="/data/subtitles/x.ass")
    # Joining where it is (the station's "now").
    assert said(caplog, lambda: b._announce(EPISODE, 754, FILE, FILE_1080, subs, CPU)) == [
        "Station 2, Cartoon Classics: joining Northbound S02E04 “Dead Reckoning” 12:34 in "
        "(northbound.s02e04.mkv: 1080p H.264, 5.1 AC-3), made 720p at 3.5 Mbps on the CPU, "
        "subtitles drawn in"
    ]
    # From the beginning: what was one line before the program is now in its line.
    b = a_station()
    b._joining = (
        "tuning in from the beginning of Northbound S02E04 “Dead Reckoning”, 3:10 behind the guide"
    )
    assert said(caplog, lambda: b._announce(EPISODE, 0, FILE, FILE_1080, None, CPU)) == [
        "Station 2, Cartoon Classics: tuning in from the beginning of Northbound S02E04 "
        "“Dead Reckoning”, 3:10 behind the guide (northbound.s02e04.mkv: 1080p H.264, 5.1 AC-3), "
        "made 720p at 3.5 Mbps on the CPU"
    ]
    assert b._joining == ""


# Something from Media playing in an app ------------------------------------------------


@pytest.fixture
def library():
    fp = LibraryPlex()
    fp.add_show("100", "Northbound", year=2020)
    fp.add_episode(
        "204", "100", 2, 4, "Dead Reckoning", "/tv/Northbound/Season 2/northbound.s02e04.mkv",
        50 * 60_000,
    )  # fmt: skip
    fp.describe("204", video="hevc", audio="eac3")
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Jaws", "/films/Jaws (1975)/jaws.mkv", 124 * 60_000, year=1975, section="2")
    fp.describe("300", audio="ac3")
    fp.add_version("300", 1280, 720, bitrate=4000)
    return fp


@pytest.fixture
def app(library, tmp_path):
    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data", hw_accel="cpu"
    )
    app = create_app(
        settings, PlexClient("http://plex.test", "token", transport=library.transport())
    )
    app.state.ctx.play_transport = library.transport()
    return app


def app_signed_in(client: TestClient, who: dict, device: dict) -> dict:
    signed = client.post("/api/internal/sign-in", json={**who, **device})
    assert signed.status_code == 200, signed.text
    return {"Authorization": f"Bearer {signed.json()['token']}"}


def lines(caplog, logger: str = "app.applibrary") -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == logger]


def test_media_playing_says_who_what_and_how(app, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as home:
        assert home.post("/api/access/users", json=PAT).status_code == 201
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        den = app_signed_in(home, PAT, DEN)
        caplog.clear()
        played = home.post("/api/internal/play", json={"key": "300", "device": TV}, headers=den)
        assert played.status_code == 200 and played.json()["method"] == "direct"
        assert lines(caplog) == [
            "Pat started Jaws (1975) in StationPlay for Android TV on Den, at home: jaws.mkv "
            "(1080p H.264, 5.1 AC-3) from Plex, playing as it is"
        ]
        phone = app_signed_in(home, PAT, {"app": "StationPlay for Android", "deviceName": "Pixel"})
        caplog.clear()
        copied = home.post(
            "/api/internal/play", json={"key": "204", "device": PHONE}, headers=phone
        )
        assert copied.status_code == 200 and copied.json()["method"] == "convert", copied.text
        assert lines(caplog) == [
            "Pat started Northbound · S2 E4 in StationPlay for Android on Pixel, at home: "
            "northbound.s02e04.mkv (1080p HEVC, 5.1 E-AC-3) from Plex, converted to 1080p H.264 "
            "at 8 Mbps on the CPU, with even sound, because this device can't play its file type "
            "(MKV), its picture's format (HEVC) and its sound's format (Dolby Digital Plus)"
        ]
        caplog.clear()
        night = home.post(
            "/api/internal/play",
            json={"key": "204", "device": PHONE, "fit": True, "maxKbps": 3_000, "night": True},
            headers=phone,
        )
        assert night.status_code == 200, night.text
        # (Just after the other: a step down, said as one.)
        assert lines(caplog) == [
            "Pat's StationPlay for Android on Pixel at home (testclient) switched Northbound · "
            "S2 E4 to a smaller copy, from 1080p H.264 at 8 Mbps on the CPU to 480p H.264 at 1.8 "
            "Mbps on the CPU: to fit its connection (about 3 Mbps)"
        ]
        plan = app.state.ctx.plays.get(night.json()["session"]).copy.plan
        assert applibrary.how_copied(plan, ["its file type (MKV)"], True, CPU) == (
            "converted smaller to fit the connection: 480p H.264 at 1.8 Mbps on the CPU, with "
            "even sound and night mode's sound, because this device can't play its file type "
            "(MKV)"
        )
        repackaged = replace(
            plan, method=converting.REPACKAGE, night=False, even=False, audio_codec="aac"
        )
        assert applibrary.how_copied(repackaged, ["its sound's format (DTS)"], False, CPU) == (
            "repackaged, its sound made AAC stereo, because this device can't play its sound's "
            "format (DTS)"
        )


def test_a_step_down_in_quality_and_stopping(app, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as home:
        home.post("/api/access/users", json=PAT)
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        den = app_signed_in(home, PAT, DEN)
        ctx = app.state.ctx
        first = home.post("/api/internal/play", json={"key": "300", "device": TV}, headers=den)
        old = first.json()["session"]
        ctx.plays.get(old).watched_s = 600  # (ten minutes in)
        # The app says why, then plays a smaller version from where the viewer is.
        sent = home.post(
            "/api/internal/problem",
            json={"kind": "kept-up", "title": "Jaws", "detail": "It kept stopping to load", **DEN},
            headers=den,
        )
        assert sent.status_code == 200
        caplog.clear()
        smaller = home.post(
            "/api/internal/play",
            json={"key": "300", "device": TV, "version": "30001", "maxKbps": 6_000},
            headers=den,
        )
        assert smaller.status_code == 200, smaller.text
        assert lines(caplog) == [
            "Pat's StationPlay for Android TV on Den at home (testclient) switched Jaws (1975) "
            "to a smaller version, from 1080p at 8 Mbps to 720p at 4 Mbps: to fit its connection "
            "(about 6 Mbps); the app said: It kept stopping to load"
        ]
        caplog.clear()
        # The old one's leave: not a stop (the new one took over).
        assert home.post(f"/play/{old}/leave").status_code == 204
        assert lines(caplog) == []
        new = smaller.json()["session"]
        home.post(
            "/api/internal/progress",
            json={"key": "300", "positionMs": 2_530_000, "session": new},
            headers=den,
        )
        ctx.plays.get(new).watched_s = 35 * 60
        assert home.post(f"/play/{new}/leave").status_code == 204
        assert lines(caplog) == ["Pat stopped Jaws (1975) at 42:10 (watched 35 min)"]
        # One play, all its time.
        got = home.get("/api/stats?days=1").json()
        assert got["media"] == [{"title": "Jaws", "kind": "movie", "hours": 0.75, "plays": 1}]
        [pat] = got["people"]
        assert (pat["name"], pat["plex"], pat["mediaHours"], pat["stationHours"]) == (
            "Pat",
            False,
            0.75,
            0,
        )
        assert pat["programs"] == [{"title": "Jaws", "kind": "movie", "hours": 0.75}]


def test_media_counts_as_its_watched_and_flicking_past_doesnt(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        ctx = app.state.ctx
        played = home.post("/api/internal/play", json={"key": "204", "device": TV}).json()
        session = ctx.plays.get(played["session"])
        session.watched_s = 30
        ctx.plays.count()  # (as every minute)
        assert home.get("/api/stats?days=1").json()["media"] == []  # (not yet a play)
        session.watched_s = 1800
        ctx.plays.count()
        assert home.get("/api/stats?days=1").json()["media"] == [
            {"title": "Northbound", "kind": "episode", "hours": 0.5, "plays": 1}
        ]
        session.watched_s = 2700
        home.post(f"/play/{played['session']}/leave")
        assert home.get("/api/stats?days=1").json()["media"] == [
            {"title": "Northbound", "kind": "episode", "hours": 0.75, "plays": 1}
        ]
        # Without signing in, it's no one's: not among the top people.
        assert home.get("/api/stats?days=1").json()["people"] == []
        # The time between an app's asks counts, but not a gap where it was gone.
        again = ctx.plays.get(
            home.post("/api/internal/play", json={"key": "300", "device": TV}).json()["session"]
        )
        start = again.seen
        for gap in (10, 10, 500, 10):
            again.used(start := start + gap)
        assert again.watched_s == pytest.approx(30, abs=0.5)


def test_the_apps_problems_are_warnings_naming_the_station(app, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as home:
        made = home.post("/api/channels", json={"number": 5, "name": "Five", "sources": [
            {"type": "show", "ratingKey": "100"}]})  # fmt: skip
        assert made.status_code == 201
        for kind, station in (("station-stopped", 5), ("kept-up", 5), ("station-failed", 9)):
            sent = home.post(
                "/api/internal/problem",
                json={"kind": kind, "station": station, "detail": "decoder error", **DEN},
            )
            assert sent.status_code == 200
        said = [
            (r.levelno, r.getMessage()) for r in caplog.records if r.name == "stationplay.problems"
        ]
        on = "Problem in StationPlay for Android TV (Den)"
        assert said == [
            (logging.WARNING, f"{on}: Station 5, Five, stopped playing: decoder error"),
            (
                logging.WARNING,
                f"{on}: Station 5, Five, couldn't keep up, so a smaller version played: "
                "decoder error",
            ),
            (logging.WARNING, f"{on}: Station 9 didn't start: decoder error"),  # (no such station)
        ]
        labels = {p["label"] for p in home.get("/api/problems").json()["problems"]}
        assert "Station 5, Five, stopped playing" in labels


# Who's watching now, and the most watched -------------------------------------------------


def test_whos_watching_now(app):
    with TestClient(app) as home:
        home.post("/api/access/users", json=PAT)
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        ctx = app.state.ctx
        made = home.post("/api/channels", json={"number": 5, "name": "Five", "sources": [
            {"type": "show", "ratingKey": "100"}]})  # fmt: skip
        assert made.status_code == 201, made.text
        cid = made.json()["id"]
        # A stream Plex asked for (StationPlay's own stream isn't played here).
        b = ctx.broadcaster(cid)
        b.viewers.add(Viewer("192.168.1.10 on 5", client="192.168.1.10", agent="Lavf/60.16.100"))
        den = app_signed_in(home, PAT, DEN)
        home.post("/api/internal/play", json={"key": "300", "device": TV}, headers=den)
        now = home.get("/api/stats/now").json()
        rows = {
            (r["station"] or r["media"])["title" if r["media"] else "name"]: r
            for r in now["watching"]
        }
        player = rows["Five"]
        assert (player["who"], player["plex"], player["app"], player["address"]) == (
            None,
            False,
            "Lavf/60.16.100",
            "192.168.1.10",
        )
        assert player["station"]["number"] == 5 and player["station"]["program"].startswith(
            "Northbound S02E04"
        )
        assert player["how"] == {"method": "convert", "picture": "720p", "mbps": 3.5, "on": None,
                                 "notes": []}  # fmt: skip
        movie = rows["Jaws (1975)"]
        assert (movie["who"], movie["app"], movie["where"], movie["address"]) == (
            "Pat",
            "StationPlay for Android TV on Den",
            "home",
            "testclient",
        )
        assert movie["how"] == {"method": "direct", "picture": "1080p", "mbps": 8.0, "on": None,
                                "notes": []}  # fmt: skip
        # When Plex says who it is (its last look, lately), that's who.
        ctx.who_watches.sessions = {
            cid: [{"user": "Kid", **stats._player(PLEX_SESSION), "since": 1}]
        }
        ctx.who_watches.looked_ms = int(time.time() * 1000)
        kid = next(r for r in home.get("/api/stats/now").json()["watching"] if r["station"])
        assert (kid["who"], kid["plex"], kid["app"], kid["where"]) == (
            "Kid",
            True,
            "Plex for Roku on Living Room",
            "home",
        )
        server = now["server"]
        assert set(server) >= {"processor", "memory", "network", "storage", "gpu", "history"}
        assert server["gpu"] == {"name": None, "state": "cpu", "stations": 0, "copies": 0}
        b.viewers.clear()


PLEX_SESSION = {
    "live": "1",
    "title": "Dead Reckoning",
    "User": {"id": "12345", "title": "Kid"},
    "Player": {"title": "Living Room", "product": "Plex for Roku", "local": "1"},
    "Session": {"id": "s1", "location": "lan"},
}


def test_the_most_watched_people_and_media(app):
    with TestClient(app) as home:
        home.post("/api/access/users", json=PAT)
        ctx = app.state.ctx
        cid = home.post("/api/channels", json={"number": 5, "name": "Five", "sources": [
            {"type": "show", "ratingKey": "100"}]}).json()["id"]  # fmt: skip
        today = stats.day_of(time.time() * 1000)
        ctx.db.add_app_watching([(1, "Pat", cid, today, "Northbound", "episode", 3600.0)])
        ctx.db.add_media_watching((1, "Pat", today, "Jaws", "movie", 1, 1800.0))
        ctx.db.add_media_watching((1, "Pat", today, "Northbound", "episode", 2, 5400.0))
        ctx.db.add_media_watching((0, "", today, "Jaws", "movie", 1, 600.0))  # (no one signed in)
        ctx.db.add_user_watching([("12345", "Kid", cid, today, "Northbound", "episode", 7200.0)])
        got = home.get("/api/stats?days=7").json()
        assert [(p["name"], p["plex"], p["hours"]) for p in got["people"]] == [
            ("Pat", False, 3.0),
            ("Kid", True, 2.0),
        ]
        pat = got["people"][0]
        assert (pat["stationHours"], pat["mediaHours"]) == (1.0, 2.0)
        assert pat["stations"] == [{"number": 5, "name": "Five", "hours": 1.0}]
        assert pat["programs"] == [
            {"title": "Northbound", "kind": "episode", "hours": 2.5},
            {"title": "Jaws", "kind": "movie", "hours": 0.5},
        ]
        assert got["media"] == [
            {"title": "Northbound", "kind": "episode", "hours": 1.5, "plays": 2},
            {"title": "Jaws", "kind": "movie", "hours": 0.67, "plays": 2},
        ]
        # Existing numbers stay as they were (Plex's users, alone).
        assert [u["name"] for u in got["users"]] == ["Kid"]


def test_users_dont_get_what_only_admins_see(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=PAT)
        assert admin.post("/api/access/users", json=BO).status_code == 201
        bo = TestClient(app)
        assert bo.post("/api/access/sign-in", json=BO).status_code == 200
        theirs = bo.get("/api/stats?days=7")
        assert theirs.status_code == 200
        assert {"people", "media", "users", "usersProblem"}.isdisjoint(theirs.json())
        assert {"stations", "programs", "byHour", "totals"} <= set(theirs.json())
        assert bo.get("/api/stats/now").status_code == 403
        assert {"people", "media"} <= set(admin.get("/api/stats?days=7").json())
        assert admin.get("/api/stats/now").status_code == 200


# An app watching a station, at home -------------------------------------------------------


async def test_an_apps_station_viewing_counts_for_whoever_is_signed_in(
    tmp_path, media, monkeypatch, caplog
):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(stats, "MIN_VIEW_S", 1)
    base, app, _settings, srv, task = await start_server(tmp_path, two_episode_show(media))
    try:
        await make_channel(base)  # (station 7, Test TV)
        async with (
            httpx.AsyncClient(base_url=base, timeout=60) as page,
            httpx.AsyncClient(base_url=base, timeout=60) as tv,
        ):
            assert (await page.post("/api/access/users", json=PAT)).status_code == 201
            signed = await tv.post("/api/internal/sign-in", json={**PAT, **DEN})
            auth = {"Authorization": f"Bearer {signed.json()['token']}"}
            [station] = (await tv.get("/api/v1/stations", headers=auth)).json()["stations"]
            playlist = await tv.get(station["hls"])  # (asked for as a player does: no token)
            assert playlist.status_code == 200, playlist.text
            await asyncio.sleep(2.5)
            assert (await tv.get(station["hls"])).status_code == 200
            now = (await page.get("/api/stats/now")).json()["watching"]
            [row] = [r for r in now if not r["plex"] and r["station"]]
            assert (row["who"], row["app"], row["where"], row["address"]) == (
                "Pat",
                "StationPlay for Android TV on Den",
                "home",
                "127.0.0.1",
            )
            assert row["how"] == {"method": "convert", "picture": "360p", "mbps": 0.8, "on": "CPU",
                                  "notes": []}  # fmt: skip
            assert (await tv.post("/hls/7/leave")).status_code == 204
            got = (await page.get("/api/stats?days=1")).json()
        # One viewing, the app's (the stream it watched through isn't another).
        assert got["stations"][0]["views"] == 1 and got["totals"]["views"] == 1
        [pat] = got["people"]
        assert pat["name"] == "Pat" and pat["stations"][0]["number"] == 7
        said = [r.getMessage() for r in caplog.records]
        who = "Pat's StationPlay for Android TV on Den at home (127.0.0.1)"
        assert f"{who} is watching station 7, Test TV" in said
        assert f"{who} stopped watching station 7, Test TV, after less than a minute" in said
        assert "Started the stream for apps of station 7, Test TV" in said
        starts = re.compile(
            r"Station 7, Test TV: (Test Show S01E0\d “good\d” starts|joining Test Show S01E0\d "
            r"“good\d” \d:\d\d in) \(good\d\.(mkv|mp4): (480p|720p) H\.264, mono AAC\), made 360p "
            r"at 0\.8 Mbps on the CPU"
        )
        assert any(starts.fullmatch(line) for line in said), [
            line for line in said if line.startswith("Station 7")
        ]
    finally:
        await app.state.ctx.hls_streams.stop_all("the test is over")
        srv.should_exit = True
        await task
