"""The setup (see setup.py): which questions an Admin is asked (all of them
on a new StationPlay; after an update, just the new or changed ones; once
each), and the checks that say whether what's set up is working."""

from __future__ import annotations

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import playback, setup
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex


def make(tmp_path, fp: FakePlex | None = None, **settings) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                plex_url="http://plex.test",
                plex_token="token",
                data_dir=tmp_path / "data",
                **settings,
            ),
            PlexClient("http://plex.test", "token", transport=(fp or FakePlex()).transport()),
        )
    )


def test_a_new_stationplay_asks_everything_and_each_answer_once(tmp_path):
    with make(tmp_path) as c:
        got = c.get("/api/setup").json()
        assert got == {
            "questions": list(setup.QUESTIONS),
            "pending": list(setup.QUESTIONS),
            "fresh": True,
        }
        left = c.put("/api/setup", json={"answered": ["playback", "newStation"]}).json()
        assert left["pending"] == ["signIn", "away", "library", "fileChecks", "plex"]
        assert not left["fresh"]
        assert c.put("/api/setup", json={"answered": ["nightMode"]}).status_code == 400
        c.put("/api/setup", json={"answered": left["pending"]})
        assert c.get("/api/setup").json()["pending"] == []


def test_a_question_that_changes_is_asked_again(tmp_path, monkeypatch):
    db = Database(tmp_path / "db.sqlite")
    setup.mark(db, list(setup.QUESTIONS))
    assert setup.pending(db) == []
    monkeypatch.setitem(setup.QUESTIONS, "away", 2)
    assert setup.pending(db) == ["away"]
    setup.mark(db, ["away"])
    assert setup.pending(db) == []
    # (What can't be read counts as unanswered.)
    db.set_meta(setup.META_ANSWERED, "[not json")
    assert setup.pending(db) == list(setup.QUESTIONS)


@pytest.mark.parametrize(
    ("welcomed", "stations", "away_on", "sharing", "left"),
    [
        # A new StationPlay: everything.
        ("", 0, False, False, list(setup.QUESTIONS)),
        # Set up with the last welcome: the apps' questions, new to the setup.
        (playback.WELCOME, 3, False, False, ["away", "library"]),
        # ...unless they're already on.
        (playback.WELCOME, 3, True, True, []),
        # An earlier welcome: what new stations start with, again.
        ("2", 3, False, True, ["newStation", "away"]),
        # Stations made without a welcome seen.
        ("", 2, True, False, ["newStation", "library"]),
    ],
)
def test_a_stationplay_set_up_before_is_asked_only_whats_new(
    tmp_path, welcomed, stations, away_on, sharing, left
):
    db = Database(tmp_path / "db.sqlite")
    if welcomed:
        db.set_meta(playback.META_WELCOMED, welcomed)
    setup.start(db, stations, away_on, sharing)
    assert setup.pending(db) == left
    # Once: what's answered since then stays answered.
    setup.mark(db, left)
    setup.start(db, stations, False, False)
    assert setup.pending(db) == []


def test_the_checks_when_plex_isnt_set_up(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data"), PlexClient("", ""))
    with TestClient(app) as c:
        checks = {x["id"]: x for x in c.get("/api/setup/checks").json()["checks"]}
    assert list(checks) == ["plex", "media", "encoding", "clock", "backups", "dvr"]
    assert checks["plex"]["state"] == "bad"
    assert "PLEX_URL and PLEX_TOKEN aren’t set" in checks["plex"]["lines"][0]
    assert checks["media"]["state"] == checks["dvr"]["state"] == "wait"
    assert checks["backups"]["state"] == "wait"  # (just started)


def test_the_media_check_finds_plexs_newest_file_where_stationplay_looks(tmp_path):
    media = tmp_path / "media"
    (media / "TV" / "Show").mkdir(parents=True)
    (media / "TV" / "Show" / "S01E02.mkv").write_bytes(b"\x1aE\xdf\xa3 a file")
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/data/media/TV/Show/S01E01.mkv", 60_000, added_at=1)
    fp.add_episode("202", "100", 1, 2, "Ep 2", "/data/media/TV/Show/S01E02.mkv", 60_000, added_at=2)
    with make(tmp_path, fp, media_dir=str(media)) as c:
        check = next(x for x in c.get("/api/setup/checks").json()["checks"] if x["id"] == "media")
        assert check["state"] == "good"
        assert check["lines"] == [
            f"StationPlay reads your files straight from disk: it found S01E02.mkv at {media}/TV/Show/S01E02.mkv."
        ]
        # (And what it learned is used when programs play.)
        assert c.app.state.ctx.media_access.learned == {"/data/media": str(media)}
        # Plex's newest file not there: streamed from Plex, and how to fix it.
        (media / "TV" / "Show" / "S01E02.mkv").unlink()
        check = next(x for x in c.get("/api/setup/checks").json()["checks"] if x["id"] == "media")
        assert check["state"] == "warn"
        assert check["lines"][0].startswith("StationPlay couldn’t find S01E02.mkv")


def test_the_media_check_when_nothing_is_mounted(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/data/media/TV/Show/S01E01.mkv", 60_000)
    with make(tmp_path, fp, media_dir=str(tmp_path / "nowhere")) as c:
        checks = {x["id"]: x for x in c.get("/api/setup/checks").json()["checks"]}
    assert checks["media"]["state"] == "warn"
    assert (
        checks["media"]["lines"][0]
        == f"Nothing is mounted at {tmp_path / 'nowhere'}, so StationPlay streams files from Plex."
    )
    assert checks["plex"]["state"] == "good"
    assert checks["dvr"]["state"] == "info"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_the_media_check_says_when_a_file_isnt_allowed_to_be_read(tmp_path):
    media = tmp_path / "media"
    (media / "TV" / "Show").mkdir(parents=True)
    locked = media / "TV" / "Show" / "S01E01.mkv"
    locked.write_bytes(b"a file")
    locked.chmod(0)
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/data/media/TV/Show/S01E01.mkv", 60_000)
    try:
        with make(tmp_path, fp, media_dir=str(media)) as c:
            check = next(
                x for x in c.get("/api/setup/checks").json()["checks"] if x["id"] == "media"
            )
    finally:
        locked.chmod(0o644)
    assert check["state"] == "warn" and "isn’t allowed to read it" in check["lines"][0]


def test_the_encoding_check():
    gpu = {"state": "gpu", "active": "NVIDIA GPU (NVENC)", "note": "", "tested": [{"ok": True}]}
    assert setup.encoding_check(gpu, True, True).state == "good"
    plain = {"state": "cpu", "active": "CPU", "note": "StationPlay can't see a GPU.", "tested": []}
    assert setup.encoding_check(plain, True, True).state == "info"
    # A GPU it isn't allowed to use is something to fix.
    denied = {
        **plain,
        "note": "StationPlay isn't allowed to use /dev/dri/renderD128, which belongs to group 107. Add \"107\" under group_add in the app's YAML.",
    }
    got = setup.encoding_check(denied, True, True)
    assert got.state == "warn" and "group_add" in got.lines[0]
    off = {"state": "disabled", "active": "CPU", "note": "It was turned off.", "tested": []}
    assert setup.encoding_check(off, True, True).state == "bad"
    assert setup.encoding_check({"state": "starting"}, True, True).state == "wait"
    # What ffmpeg can't do, said too.
    got = setup.encoding_check(gpu, False, False)
    assert got.state == "warn" and len(got.lines) == 3


def test_the_clock_check(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        assert setup.clock_check(0, "Europe/London").state == "good"
        got = setup.clock_check(-300, "America/Chicago")
        assert got.state == "warn"
        assert got.lines[0] == (
            "StationPlay’s clock is set to UTC, but this browser’s is America/Chicago, 5 hours apart. "
            "Schedules, blocks and the guide follow StationPlay’s clock."
        )
        assert "such as America/Chicago" in got.lines[1]
        assert "5.5 hours apart" in setup.clock_check(330, "Asia/Kolkata").lines[0]
        assert setup.clock_check(None, "").state == "info"
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_the_backups_check():
    now = int(time.time() * 1000)
    assert setup.backups_check([], 60, now).state == "wait"
    assert setup.backups_check([], 3600, now).state == "bad"
    recent = [{"name": "b.zip", "size": 1, "made": now - 3 * 3600 * 1000}]
    got = setup.backups_check(recent, 3600, now)
    assert got.state == "good" and "3 hours ago" in got.lines[0]
    old = [{"name": "b.zip", "size": 1, "made": now - 5 * 86400 * 1000}]
    assert setup.backups_check(old, 3600, now).state == "warn"


def test_the_plex_check_says_what_plex_pass_means():
    connected = {"configured": True, "ok": True, "version": "1.41.0"}
    assert setup.plex_check(connected, None).lines == ["StationPlay is connected to Plex 1.41.0."]
    assert setup.plex_check(connected, True).state == "good"
    got = setup.plex_check(connected, False)
    assert got.state == "warn" and "Plex Pass" in got.lines[1]
    down = setup.plex_check(
        {"configured": True, "ok": False, "error": "Plex isn't responding"}, None
    )
    assert down.state == "bad" and down.lines[0] == "Plex isn’t responding."


def test_the_setup_is_for_admins(tmp_path):
    with make(tmp_path) as c:
        c.post(
            "/api/access/users",
            json={"name": "Ada", "password": "correct horse", "role": "admin", "maxStations": None},
        )
        c.post(
            "/api/access/users",
            json={"name": "Bo", "password": "battery staple", "role": "user", "maxStations": None},
        )
        c.post("/api/access/sign-out")
        assert c.get("/api/setup").status_code == 401
        c.post("/api/access/sign-in", json={"name": "Bo", "password": "battery staple"})
        assert c.get("/api/setup").status_code == 403
        assert c.put("/api/setup", json={"answered": ["away"]}).status_code == 403
        assert c.get("/api/setup/checks").status_code == 403
        assert json.loads(c.app.state.ctx.db.get_meta(setup.META_ANSWERED) or "{}") == {}
