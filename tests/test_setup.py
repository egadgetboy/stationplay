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
    # (1.35.0: Plex is optional; with no Plex and no folder library,
    # there's nothing to play, and the step says both ways.)
    assert plex["plex"]["state"] == "bad"
    assert plex["plex"]["lines"][0] == (
        "tapiOca has nothing to play yet: it isn’t connected to Plex, and you haven’t "
        "added a Media folder for it to read itself."
    )
    assert any("PLEX_URL and PLEX_TOKEN" in line for line in plex["plex"]["lines"])
    assert (
        "Add one on the Setup tab, under Media folders, to use your folders without Plex."
        in plex["plex"]["lines"]
    )
    assert plex["plexFiles"]["state"] == plex["dvr"]["state"] == "wait"


def test_without_plex_a_folder_library_is_enough(tmp_path):
    """(1.35.0) tapiOca with or without Plex: with a Media folder of its
    own, the Plex step says tapiOca isn't using Plex, and that's fine."""
    media = tmp_path / "media"
    (media / "TV").mkdir(parents=True)
    app = create_app(Settings(data_dir=tmp_path / "data", media_dir=str(media)), PlexClient("", ""))
    with TestClient(app) as c:
        made = c.post(
            "/api/folder-libraries", json={"name": "TV", "kind": "show", "folders": ["TV"]}
        )
        assert made.status_code == 201, made.text
        plex = {x["id"]: x for x in c.get("/api/setup/plex").json()["checks"]}
        libs = c.get("/api/app-libraries").json()
        status = c.get("/api/status").json()
    assert plex["plex"]["state"] == "good"
    assert plex["plex"]["lines"][0].startswith("tapiOca isn’t using Plex")
    assert [x["key"] for x in libs["libraries"]] == ["f1"] and libs["problem"] is None
    assert status["plexUsed"] is False  # (the page says nothing about Plex)
    # (Plex's other checks aren't waiting for Plex: there's none to wait for.)
    for check in ("plexFiles", "dvr"):
        assert plex[check]["state"] == "info"
        assert plex[check]["lines"] == ["Not used: tapiOca isn’t using Plex."]


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
    assert got.lines[1] == "The Tuner step checks that tapiOca finds the files Plex lists."
    # Nothing mounted: how to fix it, and streamed from Plex meanwhile. (Until
    # 1.35.0 it said "Mount your media folder at <MEDIA_DIR>", which sent the
    # owner, October 13, to his server's own path: MEDIA_DIR is where tapiOca
    # sees it, inside its container.)
    nowhere = str(tmp_path / "nowhere")
    got = setup.folders_check([(nowhere, setup.look_at_folder(nowhere))], nowhere)
    assert got.state == "warn" and got.lines[0] == f"Nothing is at {nowhere} inside tapiOca."
    # ("The part after the colon" until the third audit of 1.35.0: the
    # example has two colons, so it could be read as /media:ro.)
    assert got.lines[1] == (
        "In tapiOca’s app settings (its YAML or Compose file), a line under volumes, such as "
        "/mnt/tank/media:/media:ro, mounts a folder on your server for tapiOca to see."
    )
    assert got.lines[2] == (
        "The middle part (/media here) is where tapiOca sees that folder. Set MEDIA_DIR to it, "
        "then restart tapiOca."
    )
    assert got.lines[3].startswith("Until then, tapiOca streams your files from Plex")
    # Without Plex, nothing streams from Plex meanwhile: what can't be read
    # is said instead (1.35.0's Media folders of your own).
    own = setup.folders_check(
        [(nowhere, setup.look_at_folder(nowhere))], nowhere, plex=False, own=True
    )
    assert own.lines[-1] == "Until then, tapiOca can’t reach its own Media folders."
    both = setup.folders_check(
        [(nowhere, setup.look_at_folder(nowhere))], nowhere, plex=True, own=True
    )
    assert both.lines[-1].startswith("Until then, tapiOca can’t reach its own Media folders, and ")
    neither = setup.folders_check(
        [(nowhere, setup.look_at_folder(nowhere))], nowhere, plex=False, own=False
    )
    assert neither.lines[-1].startswith("Until then, tapiOca can’t read your files itself.")
    assert not any("Plex where it can" in line for line in own.lines + neither.lines)
    # A whole volume line in MEDIA_DIR (the owner, October 13: 1.36.0 said
    # only "Nothing is at /mnt/hddpool/mediashare/media:/media:ro"): said
    # plainly, with what to set instead.
    line = "/mnt/pool/media:/media:ro"
    got = setup.folders_check([(line, setup.Folder("missing", [], 0))], line)
    assert got.lines[0] == f"Nothing is at {line} inside tapiOca."
    assert got.lines[1] == (
        "MEDIA_DIR holds a whole volume line, /mnt/pool/media:/media:ro. It should be only "
        "where tapiOca sees your media: /media."
    )
    assert got.lines[2] == (
        "In tapiOca’s app settings (its YAML or Compose file), set MEDIA_DIR to /media, and put "
        "/mnt/pool/media:/media:ro under volumes as your media line. Then restart tapiOca."
    )
    for pasted in ("D:/Media:/media", "C:\\Media:/media", "- /mnt/pool/media:/media:ro",
                   '"/mnt/pool/media:/media"'):  # fmt: skip
        said = setup.folders_check([(pasted, setup.Folder("missing", [], 0))], pasted).lines
        assert said[1].endswith("where tapiOca sees your media: /media."), pasted
    # (Never advice to mount the media at / or over tapiOca's data folder.)
    for wrong in ("/mnt/pool/media:/data:ro", "/mnt/pool/media:/"):
        said = setup.folders_check([(wrong, setup.Folder("missing", [], 0))], wrong).lines
        assert said[1].endswith("your media: /media.") and "/data:ro under" not in said[2], wrong
        assert "set MEDIA_DIR to /media, and put /mnt/pool/media:/media" in said[2], wrong
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
    assert got.lines[-1].startswith("Until then, tapiOca streams your files from Plex")
    # (Without Plex, nothing streams from it then either: the third audit.)
    for problem in (None, setup.Folder("error", [], 0, error="Stale file handle")):
        slow = setup.folders_check([(str(media), problem)], str(media), plex=False, own=True)
        assert slow.lines[-1] == "Until then, tapiOca can’t reach its own Media folders."
        assert not any("Plex" in line for line in slow.lines), slow.lines
    # All's well: the Plex step's check is mentioned only where Plex is used.
    fine = setup.folders_check([(str(media), looked)], str(media), plex=False, own=True)
    assert fine.state == "good" and not any("Plex" in line for line in fine.lines)
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
        "There are no Media folders to share yet. Add one on the Setup tab, under "
        "Media folders, or connect Plex (the Tuner step of the setup "
        "says how)."
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


def test_the_plex_step_with_path_mappings_and_nothing_at_media_dir(tmp_path):
    """(The third audit of 1.35.0) PATH_MAPPINGS names a folder that's
    there, MEDIA_DIR isn't, and Plex's file is in neither: the media folder
    check is good (it reads the mapped folder), so the Plex step says what
    to do itself, never "“Your media folder” says what to change"."""
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/data/media/TV/Show/S01E01.mkv", 60_000)
    mapped = tmp_path / "mapped"
    (mapped / "Movies").mkdir(parents=True)
    with make(
        tmp_path, fp, media_dir=str(tmp_path / "nowhere"),
        path_mappings=[("/data/media", str(mapped))],
    ) as c:  # fmt: skip
        checks = {x["id"]: x for x in c.get("/api/setup/plex").json()["checks"]}
        server = {x["id"]: x for x in c.get("/api/setup/checks").json()["checks"]}
    assert server["media"]["state"] == "good"
    said = checks["plexFiles"]["lines"]
    assert checks["plexFiles"]["state"] == "warn"
    # (Exactly: what it tried, and that Plex's file isn't there. Never
    # "mount it at MEDIA_DIR", which can be the server's own path, nor "set
    # PATH_MAPPINGS", which is set: the fourth audit of 1.35.0.)
    assert said == [
        f"tapiOca couldn’t find S01E01.mkv in the folders PATH_MAPPINGS names (Plex has it at "
        f"/data/media/TV/Show/S01E01.mkv, which PATH_MAPPINGS reads as {mapped}/TV/Show/"
        "S01E01.mkv), so it streams files from Plex.",
        "That works, but reading files from disk is faster and puts less load on Plex. Check "
        "that each pair in PATH_MAPPINGS ends with where tapiOca sees that folder, inside its "
        "container (see “How tapiOca reads your files” in the README).",
    ]


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
        == f"Nothing is at {tmp_path / 'nowhere'} inside tapiOca, so tapiOca streams files "
        "from Plex."
    )
    # (Not "Mount your media folder at <MEDIA_DIR>", which sent the owner,
    # October 13, to his server's own path: the media folder check says
    # what to change.)
    assert "Mount your media folder" not in checks["plexFiles"]["lines"][1]
    assert checks["plexFiles"]["lines"][1].endswith("“Your media folder” says what to change.")
    assert checks["plex"]["state"] == "good"
    assert checks["dvr"]["state"] == "info"
    # (And the first step says so too, on its own.)
    assert server["media"]["lines"][0] == f"Nothing is at {tmp_path / 'nowhere'} inside tapiOca."


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


def test_your_own_folders_dont_wait_long_for_plex(tmp_path, monkeypatch):
    """(1.35.0) Your own folders, on the Setup tab, asks Plex which of
    its Media folders hold the same folders: with Plex not answering, it
    says so within a few seconds, as the setup does."""
    (tmp_path / "media" / "TV").mkdir(parents=True)
    with make(tmp_path, media_dir=str(tmp_path / "media")) as c:
        hang_plex(c.app.state.ctx, monkeypatch)

        async def never(*_args, **_kwargs):
            await asyncio.sleep(60)

        monkeypatch.setattr(c.app.state.ctx.plex, "sections", never)
        monkeypatch.setattr(setup, "PLEX_ASK_S", 0.5)
        began = time.monotonic()
        listed = c.get("/api/folder-libraries")
        browsed = c.get("/api/folder-libraries/browse?path=")
        took = time.monotonic() - began
    assert listed.status_code == 200 and listed.json()["plexProblem"]
    assert browsed.status_code == 200 and browsed.json()["folders"] == ["TV"]
    assert took < 4, took


def test_media_dir_set_to_the_servers_own_path(tmp_path, monkeypatch):
    """(The owner, October 13) MEDIA_DIR set to where the media is on the
    server, while the YAML mounts it elsewhere inside tapiOca (/media): the
    check finds it where it's mounted, and says to set MEDIA_DIR to that."""
    media = tmp_path / "mounted"
    (media / "movies").mkdir(parents=True)
    (media / "tv").mkdir()
    (media / "tv" / "Show - S01E01.mkv").write_bytes(b"x")
    on_server = "/mnt/hddpool/mediashare/media"
    monkeypatch.setattr(setup, "mounts", lambda skip, mountinfo=None: [str(media)])
    with make(tmp_path, media_dir=on_server) as c:
        lines = next(x for x in c.get("/api/setup/checks").json()["checks"] if x["id"] == "media")[
            "lines"
        ]
    assert lines[0] == f"Nothing is at {on_server} inside tapiOca."
    assert lines[1] == f"Your media looks to be at {media} inside tapiOca: it holds movies and tv."
    assert f"Set MEDIA_DIR to {media} in tapiOca’s app settings" in lines[2]
    assert "not where it is on your server" in lines[2]


def test_where_the_media_looks_to_be():
    """(The third audit of 1.35.0) Nothing at MEDIA_DIR: the folder mounted
    into tapiOca that most likely holds the media, said plainly."""
    ok = setup.Folder("ok", ["movies", "tv"], 0, "/x/a.mkv")
    no_video = setup.Folder("ok", ["db"], 0)
    on_server = "/mnt/hddpool/mediashare/media"
    missing = [(on_server, setup.Folder("missing", [], 0))]
    # The owner's own case: /media, from the YAML.
    got = setup.folders_check(missing, on_server, [("/media", ok)])
    assert got.lines[1:3] == [
        "Your media looks to be at /media inside tapiOca: it holds movies and tv.",
        "MEDIA_DIR names your media folder as tapiOca sees it, inside its container, not where "
        "it is on your server. Set MEDIA_DIR to /media in tapiOca’s app settings (its YAML or "
        "Compose file). Then restart tapiOca.",
    ]
    # A folder with videos before one without (whatever their names).
    got = setup.folders_check(missing, on_server, [("/backups", no_video), ("/media", ok)])
    assert got.lines[1].startswith("Your media looks to be at /media inside tapiOca")
    # Several with videos: one media folder holds them all.
    got = setup.folders_check(missing, on_server, [("/movies", ok), ("/tv", ok)])
    assert got.lines[1] == "Your media looks to be at /movies and /tv inside tapiOca."
    assert got.lines[2] == (
        "tapiOca’s media folder must hold them all. In tapiOca’s app settings (its YAML or "
        "Compose file), mount them inside one, such as /media/movies and /media/tv, and set "
        "MEDIA_DIR to /media. Then restart tapiOca."
    )
    # (/media among them: the others go inside it. Names that are alike get
    # names of their own. The fourth audit of 1.35.0.)
    got = setup.folders_check(missing, on_server, [("/media", ok), ("/tv", ok)])
    assert got.lines[2] == (
        "tapiOca’s media folder must hold them all. In tapiOca’s app settings (its YAML or "
        "Compose file), mount the others inside /media, such as /media/tv, and set MEDIA_DIR "
        "to /media. Then restart tapiOca."
    )
    got = setup.folders_check(missing, on_server, [("/mnt/a/media", ok), ("/mnt/b/media", ok)])
    assert "such as /media/media and /media/media-2," in got.lines[2]
    # Your own Media folders, read from MEDIA_DIR: put the media back there,
    # never MEDIA_DIR elsewhere (they'd stay out of reach).
    got = setup.folders_check(
        [("/media", setup.Folder("missing", [], 0))], "/media", [("/mnt/media", ok)],
        plex=False, own=True, own_roots=["/media/TV"],
    )  # fmt: skip
    assert got.lines[1:3] == [
        "Your media looks to be at /mnt/media inside tapiOca now.",
        "tapiOca reads its Media folders from /media, so mount your media there again: in "
        "tapiOca’s app settings (its YAML or Compose file), its line under volumes must end in "
        ":/media or :/media:ro. Then restart tapiOca.",
    ]
    assert not any("Set MEDIA_DIR" in line for line in got.lines)
    # (Ranked first there too: one with videos, whatever the names. The
    # fourth audit of 1.35.0.)
    got = setup.folders_check(
        [("/media", setup.Folder("missing", [], 0))], "/media",
        [("/backups", no_video), ("/mnt/media", ok)], plex=False, own=True,
        own_roots=["/media/TV"],
    )  # fmt: skip
    assert got.lines[1] == "Your media looks to be at /mnt/media inside tapiOca now."
    # They're where it's mounted now: MEDIA_DIR is what changed.
    got = setup.folders_check(
        missing, on_server, [("/backups", ok), ("/media", ok)], own=True, own_roots=["/media/TV"]
    )
    assert got.lines[1].startswith("Your media looks to be at /media inside tapiOca")


def test_what_is_mounted_into_tapioca():
    """The folders mounted into tapiOca's container, from its mountinfo: not
    the system's own, nor its data folder."""
    mountinfo = "\n".join([
        "22 1 0:21 / / rw - overlay overlay rw",
        "23 22 0:22 / /proc rw - proc proc rw",
        "24 22 0:23 / /dev rw - tmpfs tmpfs rw",
        "25 22 0:24 / /sys ro - sysfs sysfs ro",
        "26 22 0:25 /apps/data /data rw - zfs hddpool/apps rw",
        "27 22 0:26 /mediashare/media /media ro - zfs hddpool/mediashare ro",
        "28 22 0:27 /a /mnt/two\\040words ro - zfs hddpool/x ro",
        "29 22 0:28 / /etc/hosts rw - ext4 /dev/sda1 rw",
    ])  # fmt: skip
    assert setup.mounts(["/data"], mountinfo) == ["/media", "/mnt/two words"]
    # (The third audit of 1.35.0) Whole names, not the start of one; every
    # escape mountinfo writes; files the system mounts (NVIDIA's firmware,
    # Docker's init); and a folder that holds the data folder.
    more = "\n".join([
        "30 22 0:29 / /devices ro - zfs a ro",
        "31 22 0:30 / /tmpmedia ro - zfs a ro",
        "32 22 0:31 / /processed ro - zfs a ro",
        "33 22 0:32 / /my\\134share ro - zfs a ro",
        "34 22 0:33 / /tab\\011name ro - zfs a ro",
        "35 22 0:34 /f /lib/firmware/nvidia/gsp.bin ro - ext4 a ro",
        "36 22 0:35 /i /sbin/docker-init ro - ext4 a ro",
        "37 22 0:36 / /config rw - zfs a rw",
        "38 22 0:37 / /opt/stationplay/x ro - zfs a ro",
    ])  # fmt: skip
    assert setup.mounts(["/config/data"], mountinfo + "\n" + more) == [
        "/media", "/data", "/devices", "/mnt/two words", "/my\\share", "/processed",
        "/tab\tname", "/tmpmedia",
    ]  # fmt: skip
