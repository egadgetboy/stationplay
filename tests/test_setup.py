"""The setup (see setup.py): which questions an Admin is asked (all of them
on a new tapiOca; after an update, just the new or changed ones; once
each), and the checks that say whether what's set up is working."""

from __future__ import annotations

import asyncio
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
        assert left["pending"] == ["signIn", "viewing", "away", "library", "fileChecks", "plex"]
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
    ("welcomed", "stations", "away_on", "sharing", "others", "left"),
    [
        # A new tapiOca: everything.
        ("", 0, False, False, False, list(setup.QUESTIONS)),
        # Set up with the last welcome: the apps' questions, new to the setup.
        (playback.WELCOME, 3, False, False, False, ["away", "library"]),
        # ...unless they're already on.
        (playback.WELCOME, 3, True, True, False, []),
        # An earlier welcome: what new stations start with, again.
        ("2", 3, False, True, False, ["newStation", "away"]),
        # Stations made without a welcome seen.
        ("", 2, True, False, False, ["newStation", "library"]),
        # With Users (not Admins): who sees what, too.
        (playback.WELCOME, 3, True, True, True, ["viewing"]),
    ],
)
def test_a_stationplay_set_up_before_is_asked_only_whats_new(
    tmp_path, welcomed, stations, away_on, sharing, others, left
):
    db = Database(tmp_path / "db.sqlite")
    if welcomed:
        db.set_meta(playback.META_WELCOMED, welcomed)
    setup.start(db, stations, away_on, sharing, others)
    assert setup.pending(db) == left
    # Once: what's answered since then stays answered.
    setup.mark(db, left)
    setup.start(db, stations, False, False)
    assert setup.pending(db) == []


def test_media_is_asked_again_once_after_it_came_on_to_start(tmp_path):
    """(1.34.1) Media is on to start: a tapiOca whose Admin never chose its
    Media folders is asked once (with every one ticked); one whose Admin
    chose isn't."""
    db = Database(tmp_path / "db.sqlite")
    answered_before = {**setup.QUESTIONS, "library": 1}
    db.set_meta(setup.META_ANSWERED, json.dumps(answered_before))
    setup.start(db, 3, False, False)
    assert setup.pending(db) == ["library"]
    db.set_meta(setup.META_ANSWERED, json.dumps(answered_before))
    setup.start(db, 3, False, True, chose=True)
    assert setup.pending(db) == []


def test_who_sees_what_is_asked_after_an_update_only_with_people_to_choose_for(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    answered_before = {q: v for q, v in setup.QUESTIONS.items() if q != "viewing"}
    db.set_meta(setup.META_ANSWERED, json.dumps(answered_before))
    setup.start(db, 3, False, False, others=True)
    assert setup.pending(db) == ["viewing"]
    db.set_meta(setup.META_ANSWERED, json.dumps(answered_before))
    setup.start(db, 3, False, False, others=False)
    assert setup.pending(db) == []


def test_the_checks_when_plex_isnt_set_up(tmp_path):
    """(1.34.1) The first step checks the server itself; Plex is checked in
    the Plex step, which says what's wrong there."""
    app = create_app(
        Settings(data_dir=tmp_path / "data", media_dir=str(tmp_path / "nowhere")),
        PlexClient("", ""),
    )
    with TestClient(app) as c:
        checks = {x["id"]: x for x in c.get("/api/setup/checks").json()["checks"]}
        plex = {x["id"]: x for x in c.get("/api/setup/plex").json()["checks"]}
    assert list(checks) == ["media", "encoding", "clock", "backups"]
    assert checks["backups"]["state"] == "wait"  # (just started)
    assert list(plex) == ["plex", "plexFiles", "dvr"]
    assert plex["plex"]["state"] == "bad"
    assert "PLEX_URL and PLEX_TOKEN aren’t set" in plex["plex"]["lines"][0]
    assert plex["plexFiles"]["state"] == plex["dvr"]["state"] == "wait"


def hang_plex(ctx, monkeypatch) -> list[str]:
    """Plex, as if it never answered: what was asked of it."""
    asked: list[str] = []

    def hanging(name):
        async def ask(*_args, **_kwargs):
            asked.append(name)
            await asyncio.sleep(60)

        return ask

    for name in ("identity", "newest_files", "plex_pass", "libraries"):
        monkeypatch.setattr(ctx.plex, name, hanging(name))
    monkeypatch.setattr(ctx.library, "libraries", hanging("libraries"))
    monkeypatch.setattr(ctx.updater, "find_dvr", hanging("find_dvr"))
    return asked


def test_the_first_step_checks_the_server_without_waiting_for_plex(tmp_path, monkeypatch):
    """(1.34.1, the owner) The first step said Plex was Not working on a new
    tapiOca, before there was any chance to connect it: it checks only the
    server itself now, and nothing in it waits on Plex."""
    media = tmp_path / "media"
    (media / "Movies").mkdir(parents=True)
    (media / "TV Shows").mkdir()
    with make(tmp_path, media_dir=str(media)) as c:
        asked = hang_plex(c.app.state.ctx, monkeypatch)
        began = time.monotonic()
        checks = {x["id"]: x for x in c.get("/api/setup/checks").json()["checks"]}
        took = time.monotonic() - began
    assert asked == []
    assert took < 4, took
    assert list(checks) == ["media", "encoding", "clock", "backups"]
    assert checks["media"]["title"] == "Your media folder"
    assert checks["media"]["state"] == "good"
    assert (
        checks["media"]["lines"][0] == f"tapiOca can read {media}, which holds Movies and TV Shows."
    )


def test_the_media_folder_check_reads_the_folder_itself(tmp_path):
    """MEDIA_DIR (and any folder PATH_MAPPINGS names), looked at directly,
    with or without Plex: whether it's there, can be read and holds
    something, and whether a video in it can be read."""
    media = tmp_path / "media"
    (media / "TV" / "Show").mkdir(parents=True)
    for name in ("Movies", "Music", "Kids", "Concerts", ".hidden", "@eaDir"):
        (media / name).mkdir()
    (media / "TV" / "Show" / "S01E01.mkv").write_bytes(b"\x1aE\xdf\xa3 a file")
    looked = setup.look_at_folder(str(media))
    assert looked.state == "ok" and looked.video and looked.video_problem is None
    got = setup.folders_check([(str(media), looked)], str(media))
    assert got.state == "good"
    assert got.lines[0] == (
        f"tapiOca can read {media}, which holds Concerts, Kids, Movies and 2 other folders."
    )
    assert got.lines[1] == "The Plex step checks that tapiOca finds the files Plex lists."
    # Nothing mounted: streamed from Plex, and how to fix it.
    nowhere = str(tmp_path / "nowhere")
    got = setup.folders_check([(nowhere, setup.look_at_folder(nowhere))], nowhere)
    assert got.state == "warn" and got.lines[0] == f"Nothing is mounted at {nowhere}."
    assert f"Mount your media folder at {nowhere}" in got.lines[1]
    # An empty folder: a share or disk that isn't mounted, most often.
    empty = tmp_path / "empty"
    (empty / "lost+found").mkdir(parents=True)
    got = setup.folders_check([(str(empty), setup.look_at_folder(str(empty)))], str(empty))
    assert got.state == "warn" and got.lines[0] == f"{empty} is empty."
    # Too slow to answer.
    got = setup.folders_check([(str(media), None)], str(media))
    assert got.state == "warn" and got.lines[0] == (
        f"Reading {media} took too long. A network share may be slow or out of reach."
    )
    # Files only.
    flat = tmp_path / "flat"
    flat.mkdir()
    for n in range(3):
        (flat / f"movie{n}.mp4").write_bytes(b"a movie")
    got = setup.folders_check([(str(flat), setup.look_at_folder(str(flat)))], str(flat))
    assert got.lines[0] == f"tapiOca can read {flat}, which holds 3 files."
    # A folder PATH_MAPPINGS names, with nothing at MEDIA_DIR: just that one.
    got = setup.folders_check(
        [(nowhere, setup.look_at_folder(nowhere)), (str(media), looked)], nowhere
    )
    assert got.state == "good" and got.title == "Your media folder"
    assert got.lines[0].startswith(f"tapiOca can read {media},")


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_the_media_folder_check_says_what_it_isnt_allowed_to_read(tmp_path):
    media = tmp_path / "media"
    (media / "TV").mkdir(parents=True)
    video = media / "TV" / "S01E01.mkv"
    video.write_bytes(b"a file")
    video.chmod(0)
    try:
        got = setup.folders_check([(str(media), setup.look_at_folder(str(media)))], str(media))
    finally:
        video.chmod(0o644)
    assert got.state == "warn"
    assert got.lines[0] == f"tapiOca can see {media} but isn’t allowed to read the videos in it."
    assert "permission to read your media" in got.lines[1]
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        got = setup.folders_check([(str(locked), setup.look_at_folder(str(locked)))], str(locked))
    finally:
        locked.chmod(0o755)
    assert got.state == "warn" and got.lines[0] == f"tapiOca isn’t allowed to read {locked}."


def test_the_plex_step_checks_plex_and_says_where_to_add_tapioca(tmp_path):
    with make(tmp_path, media_dir=str(tmp_path / "nowhere")) as c:
        got = c.get("/api/setup/plex").json()
    checks = {x["id"]: x for x in got["checks"]}
    assert list(checks) == ["plex", "plexFiles", "dvr"]
    assert checks["plex"]["state"] == "good"
    assert checks["dvr"]["state"] == "info"
    assert got["tunerUrl"] == "http://testserver"
    assert got["xmltvUrl"] == "http://testserver/xmltv.xml"


def test_with_plex_down_its_tuner_isnt_looked_for(tmp_path, monkeypatch):
    """(1.34.1) Whether Plex answers is asked first: with Plex down, Plex
    isn't asked anything more, so the page hears at once."""
    with make(tmp_path) as c:
        asked = hang_plex(c.app.state.ctx, monkeypatch)
        monkeypatch.setattr(setup, "PLEX_ASK_S", 0.5)
        began = time.monotonic()
        plex = c.get("/api/status").json()["plex"]
        checks = {x["id"]: x for x in c.get("/api/setup/plex").json()["checks"]}
        took = time.monotonic() - began
    assert asked.count("find_dvr") == 0 and "newest_files" not in asked
    assert plex == {"configured": True, "ok": False, "error": "Plex isn't answering"}
    assert checks["plex"]["state"] == "bad"
    assert checks["plex"]["lines"] == [
        "tapiOca can’t reach Plex at plex.test: nothing answered. Check that PLEX_URL is your "
        "Plex server’s address, and that Plex is running."
    ]
    assert took < 4, took


def test_media_in_the_apps_says_plainly_when_plex_isnt_answering(tmp_path, monkeypatch):
    """(1.34.1, the owner) Step 7 showed Loading… for a long time, then
    "Plex request for /library/sections failed ()": it answers within a
    few seconds now, in a plain sentence, and what's shared stays shared."""
    with make(tmp_path) as c:
        assert c.put("/api/app-libraries", json={"libraries": ["1"]}).status_code == 200
        hang_plex(c.app.state.ctx, monkeypatch)
        monkeypatch.setattr(setup, "PLEX_ASK_S", 0.5)
        began = time.monotonic()
        got = c.get("/api/app-libraries").json()
        took = time.monotonic() - began
    assert took < 4, took
    assert got["libraries"] == [] and got["shared"] == ["1"]
    assert got["problem"] == (
        "Plex isn’t answering, so tapiOca can’t list your Media folders right now. "
        "Those already shared stay shared."
    )


def test_media_in_the_apps_without_plex(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "data"), PlexClient("", ""))
    with TestClient(app) as c:
        got = c.get("/api/app-libraries").json()
    assert got["problem"] == (
        "tapiOca isn’t connected to Plex yet, so there are no Media folders to share. "
        "The Plex step of the setup says how to connect it."
    )


def test_the_media_check_finds_plexs_newest_file_where_stationplay_looks(tmp_path):
    media = tmp_path / "media"
    (media / "TV" / "Show").mkdir(parents=True)
    (media / "TV" / "Show" / "S01E02.mkv").write_bytes(b"\x1aE\xdf\xa3 a file")
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/data/media/TV/Show/S01E01.mkv", 60_000, added_at=1)
    fp.add_episode("202", "100", 1, 2, "Ep 2", "/data/media/TV/Show/S01E02.mkv", 60_000, added_at=2)
    with make(tmp_path, fp, media_dir=str(media)) as c:
        check = next(x for x in c.get("/api/setup/plex").json()["checks"] if x["id"] == "plexFiles")
        assert check["state"] == "good"
        assert check["lines"] == [
            f"tapiOca reads your files straight from disk: it found S01E02.mkv at {media}/TV/Show/S01E02.mkv."
        ]
        # (And what it learned is used when programs play.)
        assert c.app.state.ctx.media_access.learned == {"/data/media": str(media)}
        # Plex's newest file not there: streamed from Plex, and how to fix it.
        (media / "TV" / "Show" / "S01E02.mkv").unlink()
        check = next(x for x in c.get("/api/setup/plex").json()["checks"] if x["id"] == "plexFiles")
        assert check["state"] == "warn"
        assert check["lines"][0].startswith("tapiOca couldn’t find S01E02.mkv")


def test_the_media_check_when_nothing_is_mounted(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/data/media/TV/Show/S01E01.mkv", 60_000)
    with make(tmp_path, fp, media_dir=str(tmp_path / "nowhere")) as c:
        checks = {x["id"]: x for x in c.get("/api/setup/plex").json()["checks"]}
        server = {x["id"]: x for x in c.get("/api/setup/checks").json()["checks"]}
    assert checks["plexFiles"]["state"] == "warn"
    assert (
        checks["plexFiles"]["lines"][0]
        == f"Nothing is mounted at {tmp_path / 'nowhere'}, so tapiOca streams files from Plex."
    )
    assert checks["plex"]["state"] == "good"
    assert checks["dvr"]["state"] == "info"
    # (And the first step says so too, on its own.)
    assert server["media"]["lines"][0] == f"Nothing is mounted at {tmp_path / 'nowhere'}."


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
                x for x in c.get("/api/setup/plex").json()["checks"] if x["id"] == "plexFiles"
            )
    finally:
        locked.chmod(0o644)
    assert check["state"] == "warn" and "isn’t allowed to read it" in check["lines"][0]


def test_the_encoding_check():
    gpu = {"state": "gpu", "active": "NVIDIA GPU (NVENC)", "note": "", "tested": [{"ok": True}]}
    assert setup.encoding_check(gpu, True, True).state == "good"
    plain = {"state": "cpu", "active": "CPU", "note": "tapiOca can't see a GPU.", "tested": []}
    assert setup.encoding_check(plain, True, True).state == "info"
    # A GPU it isn't allowed to use is something to fix.
    denied = {
        **plain,
        "note": "tapiOca isn't allowed to use /dev/dri/renderD128, which belongs to group 107. Add \"107\" under group_add in the app's YAML.",
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
            "tapiOca’s clock is set to UTC, but this browser’s is America/Chicago, 5 hours apart. "
            "Schedules, blocks and the guide follow tapiOca’s clock."
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
    assert setup.plex_check(connected, None).lines == ["tapiOca is connected to Plex 1.41.0."]
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
        assert c.get("/api/setup/plex").status_code == 403
        assert json.loads(c.app.state.ctx.db.get_meta(setup.META_ANSWERED) or "{}") == {}
