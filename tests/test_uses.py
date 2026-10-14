"""What tapiOca uses (uses.py, 1.37.0): where your shows and movies come from
(Plex, Media folders of your own, or both) and where you watch, chosen in
the setup or on the Setup tab. The owner, October 13: "a checkbox section in
server UI that matches all the options we support... if they are going to
have Emby or another, it gives them those instructions accordingly." They
change only what the page shows: never what any app can use."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import setup, updates, uses
from app.config import Settings
from app.db import Database
from app.folders import FolderLibrary
from app.main import create_app
from app.plex import EXAMPLE_TOKEN, EXAMPLE_URL, PlexClient

from .fakeplex import FakePlex

APP = Path(__file__).resolve().parents[1] / "app"
PAT = {"name": "Pat", "password": "correct horse battery"}
SAM = {"name": "Sam", "password": "another long password"}


def make(tmp_path, plex: bool = True, sample: bool = False):
    if sample:
        client = PlexClient(EXAMPLE_URL, EXAMPLE_TOKEN)
    elif plex:
        client = PlexClient("http://plex.test", "token", transport=FakePlex().transport())
    else:
        client = PlexClient("", "")
    return create_app(Settings(data_dir=tmp_path / "data"), client)


def own_folder(app, missing: bool = False) -> None:
    """A Media folder of tapiOca's own (as the folder libraries keep them)."""
    app.state.ctx.folders.libraries[1] = FolderLibrary(
        1, "Movies", "movie", ["Movies"], 0, missing=["Movies"] if missing else []
    )


def test_what_is_stored_and_what_counts(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    assert uses.load(db) == (None, None)
    # Kept in order, without repeats; what's set up is always among the sources.
    got = uses.save(db, ["folders", "folders"], ["kodi", "tapioca", "kodi"],
                    plex_set_up=True, own_folders=False)  # fmt: skip
    assert got == (["plex", "folders"], ["tapioca", "kodi"]) == uses.load(db)
    # None leaves a part as it is.
    assert uses.save(db, None, ["other"], plex_set_up=False, own_folders=False) == (
        ["plex", "folders"], ["other"]
    )  # fmt: skip
    for bad in ([], ["dvd"], "plex"):
        with pytest.raises(ValueError, match="Choose Plex, Media folders of your own, or both"):
            uses.save(db, bad, None, plex_set_up=False, own_folders=False)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Choose at least one place you'll watch"):
        uses.save(db, None, [], plex_set_up=False, own_folders=False)
    # What can't be read is nothing stored.
    db.set_meta(uses.META, "[not json")
    assert uses.load(db) == (None, None)
    # Whether Plex is used: set up, or chosen, or (nothing chosen) nothing else.
    for stored, plex, own, used in [
        (None, True, True, True),
        (None, False, False, True),  # (1.36.0: Plex, when there's nothing else)
        (None, False, True, False),  # (1.36.0: your own folders, without Plex)
        (["folders"], False, True, False),
        (["folders"], True, True, True),  # (what's set up counts)
        (["plex", "folders"], False, True, True),  # (chosen, PLEX_URL still to come)
    ]:
        assert uses.plex_used(stored, plex, own) is used, (stored, plex, own)


def test_the_setup_asks_them_once_and_saves_them(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="stationplay")
    app = make(tmp_path)
    with TestClient(app) as pat:
        assert pat.post("/api/access/users", json=PAT).is_success
        assert setup.pending(app.state.ctx.db)[:2] == ["sources", "watchIn"]
        got = pat.get("/api/setup/uses").json()
        assert got == {
            "sources": None,
            "watchIn": None,
            "suggested": {"sources": ["plex"], "watchIn": []},
            "locked": {"plex": True, "folders": False},
        }
        # Plex can't be left out while PLEX_URL and PLEX_TOKEN are set.
        saved = pat.put("/api/setup/uses", json={"sources": ["folders"]}).json()
        assert saved["sources"] == ["plex", "folders"]
        assert "sources" not in pat.get("/api/setup").json()["pending"]
        assert "watchIn" in pat.get("/api/setup").json()["pending"]
        empty = pat.put("/api/setup/uses", json={"watchIn": []})
        assert empty.status_code == 400
        assert empty.json()["detail"] == "Choose at least one place you'll watch."
        for bad in ({"watchIn": ["dvd"]}, {"watchIn": "plex"}, {"watchIn": ["plex"] * 7}):
            assert pat.put("/api/setup/uses", json=bad).status_code == 422, bad
        saved = pat.put("/api/setup/uses", json={"watchIn": ["jellyfin", "tapioca"]}).json()
        assert saved["watchIn"] == ["tapioca", "jellyfin"]
        assert not {"sources", "watchIn"} & set(pat.get("/api/setup").json()["pending"])
        logged = caplog.text
        assert "What tapiOca uses changed (by Pat): Plex, Media folders of your own; " \
               "watched in tapiOca's apps, Jellyfin" in logged  # fmt: skip


def test_the_sample_token_isnt_plex_set_up(tmp_path):
    app = make(tmp_path, sample=True)
    with TestClient(app) as pat:
        assert pat.post("/api/access/users", json=PAT).is_success
        assert pat.get("/api/setup/uses").json()["locked"]["plex"] is False


def test_what_the_status_says(tmp_path):
    app = make(tmp_path, plex=False)
    with TestClient(app) as pat:
        assert pat.post("/api/access/users", json=PAT).is_success
        st = pat.get("/api/status").json()
        # Nothing chosen, nothing set up: as 1.36.0 (Plex, with nothing else).
        assert st["plexUsed"] is True
        assert st["uses"] == {"sources": ["plex"], "watchIn": None, "saved": False}
        assert st["folders"] == {"count": 0, "missing": 0}
        assert st["guide"]["downloads"] == {}
        own_folder(app, missing=True)
        st = pat.get("/api/status").json()
        assert st["plexUsed"] is False and st["uses"]["sources"] == ["folders"]
        assert st["folders"] == {"count": 1, "missing": 1}
        assert pat.get("/api/setup/uses").json()["locked"] == {"plex": False, "folders": True}
        # Plex chosen, not set up yet: used (its steps show).
        pat.put("/api/setup/uses", json={"sources": ["plex"], "watchIn": ["plex"]})
        st = pat.get("/api/status").json()
        assert st["plexUsed"] is True
        assert st["uses"] == {"sources": ["plex", "folders"], "watchIn": ["plex"], "saved": True}
        # A User's status keeps only what it had, with Plex used as chosen.
        assert pat.post("/api/access/users", json={**SAM, "role": "user"}).status_code == 201
        sam = TestClient(app)
        assert sam.post("/api/access/sign-in", json=SAM).status_code == 200
        theirs = sam.get("/api/status").json()
        assert theirs["plex"]["used"] is True
        assert not {"uses", "folders", "plexUsed", "guide"} & set(theirs)
        # And they can't see or change what tapiOca uses.
        assert sam.get("/api/setup/uses").status_code == 403
        assert sam.put("/api/setup/uses", json={"watchIn": ["other"]}).status_code == 403


def test_the_choices_never_limit_any_app(tmp_path):
    """The tuner, playlist and guide answer the same whatever is chosen
    ("Never limit Plex, Jellyfin or other clients")."""
    app = make(tmp_path)
    paths = ("/discover.json", "/lineup.json", "/lineup_status.json", "/device.xml",
             "/stations.m3u", "/channels.m3u")  # fmt: skip
    with TestClient(app) as pat:
        assert pat.post("/api/access/users", json=PAT).is_success
        tv = TestClient(app, base_url="http://192.168.1.20:3310")
        before = {p: (r.status_code, r.text) for p in paths if (r := tv.get(p))}
        guide = tv.get("/xmltv.xml")
        pat.put("/api/setup/uses", json={"sources": ["folders"], "watchIn": ["tapioca"]})
        after = {p: (r.status_code, r.text) for p in paths if (r := tv.get(p))}
        assert after == before
        again = tv.get("/xmltv.xml")
        assert again.status_code == guide.status_code == 200
        assert tv.get("/guide.xml").status_code == 200


def test_only_the_page_reads_the_choices():
    """Nothing that decides what an app gets reads what's chosen."""
    readers = []
    for path in APP.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in (None, "") and any(
                a.name == "uses" for a in node.names
            ):
                readers.append(path.name)
            elif isinstance(node, ast.ImportFrom) and node.module == "uses":
                readers.append(path.name)
    assert sorted(set(readers)) == ["main.py"]


@pytest.mark.parametrize(
    ("agent", "kind"),
    [
        ("Jellyfin-Server/10.10.3", "jellyfin"),
        ("Kodi/21.1 (X11; Linux x86_64) App_Bitness/64 Version/21.1-(21.1.0)", "kodi"),
        ("Emby Server/4.8.10.0", "emby"),
        ("VLC/3.0.20 LibVLC/3.0.20", "other"),
        ("curl/8.5.0", "other"),
        ("StationPlay/1.36.0 (Android)", None),
        ("PlexMediaServer/1.41.3", None),
    ],
)
def test_when_each_app_last_downloaded_the_guide(tmp_path, agent, kind):
    app = make(tmp_path)
    with TestClient(app, base_url="http://192.168.1.20:3310") as tv:
        assert tv.get("/guide.xml", headers={"User-Agent": agent}).status_code == 200
        kept = app.state.ctx.updater.downloads()
        assert list(kept) == ([kind] if kind else [])


def test_a_guide_download_is_noted_at_most_every_ten_minutes_and_never_stops_the_guide(
    tmp_path, monkeypatch
):
    app = make(tmp_path)
    ctx = app.state.ctx
    with TestClient(app, base_url="http://192.168.1.20:3310") as tv:
        jellyfin = {"User-Agent": "Jellyfin-Server/10.10.3"}
        tv.get("/guide.xml", headers=jellyfin)
        first = ctx.updater.downloads()["jellyfin"]
        writes = []
        real = ctx.db.set_meta
        monkeypatch.setattr(ctx.db, "set_meta", lambda k, v: (writes.append(k), real(k, v)))
        tv.get("/guide.xml", headers=jellyfin)
        assert updates.META_DOWNLOADS not in writes
        assert ctx.updater.downloads()["jellyfin"] == first

        def fails(key, value):
            if key == updates.META_DOWNLOADS:
                raise OSError("disk full")
            real(key, value)

        monkeypatch.setattr(ctx.db, "set_meta", fails)
        assert tv.get("/guide.xml", headers={"User-Agent": "Kodi/21.1"}).status_code == 200


def test_a_ready_update_says_what_it_waits_for(tmp_path, monkeypatch):
    app = make(tmp_path)
    ctx = app.state.ctx
    now = 1_800_000_000_000
    monkeypatch.setattr(updates, "now_ms", lambda: now)
    hour = 3600 * 1000
    ctx.db.set_meta(updates.META_PLEX_DOWNLOAD, str(now - 2 * hour))
    assert ctx.updater.waits_for() == {"waitsFor": "plex"}
    ctx.db.set_meta(updates.META_PLEX_DOWNLOAD, str(now - 30 * hour))
    ctx.db.set_meta(updates.META_PUBLISHED_UNTIL, str(now + 20 * hour))
    assert ctx.updater.waits_for() == {"waitsFor": "guide", "after": now + 20 * hour}
    ctx.db.set_meta(updates.META_PLEX_DOWNLOAD, "0")
    ctx.db.set_meta(updates.META_PUBLISHED_UNTIL, "0")
    assert ctx.updater.waits_for() == {"waitsFor": "guide", "after": now}


def test_the_setups_plex_checks_follow_the_choices():
    gone = {"configured": False}
    # Nothing chosen: as 1.36.0.
    assert setup.plex_check(gone, None, 2).state == setup.GOOD
    assert setup.plex_check(gone, None, 0).state == setup.BAD
    # Plex chosen, not connected yet, with folders of your own: to do, not fine.
    chosen = setup.plex_check(gone, None, 2, wanted=True)
    assert chosen.state == setup.INFO
    assert chosen.lines[0] == "tapiOca isn’t connected to Plex yet."
    assert setup.plex_check(gone, None, 2, wanted=False).state == setup.GOOD
    # Plex Pass matters only for watching in Plex.
    connected = {"configured": True, "ok": True, "version": "1.41"}
    assert setup.plex_check(connected, False).state == setup.WARN
    assert setup.plex_check(connected, False, watch_plex=True).state == setup.WARN
    assert setup.plex_check(connected, False, watch_plex=False).state == setup.GOOD
    # The DVR: without PLEX_URL, only when Plex last downloaded the guide.
    now = 1_800_000_000_000
    no_url = setup.dvr_check(False, {"plexDownloadedGuide": now - 3600_000}, now, plex_url=False)
    assert no_url.state == setup.INFO
    assert no_url.lines[0] == "tapiOca can’t see Plex’s DVR without PLEX_URL and PLEX_TOKEN."
    assert no_url.lines[1].startswith("Plex last downloaded tapiOca’s guide")
    never = setup.dvr_check(False, {}, now, plex_url=False)
    assert never.lines[1] == "Plex hasn’t downloaded tapiOca’s guide yet."
    # The "you can skip them" aside only while where you watch isn't chosen.
    assert "you can skip them" in setup.dvr_check(True, {}, now).lines[0]
    assert "skip" not in setup.dvr_check(True, {}, now, saved=True).lines[0]
    assert setup.dvr_check(False, {}, now).state == setup.WAIT


def test_the_plex_step_with_plex_as_a_place_only(tmp_path):
    app = make(tmp_path, plex=False)
    with TestClient(app) as pat:
        assert pat.post("/api/access/users", json=PAT).is_success
        own_folder(app)
        first = pat.get("/api/setup/plex").json()["checks"]
        # (Plex's files and its DVR, not used without Plex: 1.35.0.)
        assert first[1]["state"] == first[2]["state"] == setup.not_used(setup.Check(
            "dvr", "", setup.INFO, [])).state  # fmt: skip
        pat.put("/api/setup/uses", json={"sources": ["folders"], "watchIn": ["plex"]})
        got = {c["id"]: c for c in pat.get("/api/setup/plex").json()["checks"]}
        assert got["dvr"]["lines"][0].startswith("tapiOca can’t see Plex’s DVR")
        assert got["plex"]["state"] == setup.GOOD


def test_the_choices_kept_are_only_known_ones(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    db.set_meta(uses.META, json.dumps({"sources": ["plex", "dvd"], "watchIn": ["kodi"]}))
    assert uses.load(db) == (None, ["kodi"])
