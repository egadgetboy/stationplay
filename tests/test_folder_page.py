"""The page's addresses for folder libraries (folders.py, 1.35.0):
adding, changing, scanning and removing one, and choosing its folders
(never outside the media folder), all for Admins only."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .folderlib import Clips, plex_tv, put, sonarr_tv

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
PAT = {"name": "Pat", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple"}


@pytest.fixture(scope="session")
def clips(tmp_path_factory) -> Clips:
    return Clips(tmp_path_factory.mktemp("clips"))


@pytest.fixture
def app(tmp_path, clips):
    media = tmp_path / "media"
    sonarr_tv(media / "TV", clips)
    plex_tv(media / "TV", clips)
    put(media / "Outside link target" / "x.mkv")
    settings = Settings(data_dir=tmp_path / "data", media_dir=str(media))
    return create_app(settings, PlexClient("", ""))


def scanned(home: TestClient, key: str) -> dict:
    for _ in range(300):
        found = {x["key"]: x for x in home.get("/api/folder-libraries").json()["libraries"]}
        if found[key]["scannedMs"]:
            return found[key]
        time.sleep(0.05)
    raise AssertionError("not scanned")


def test_adding_changing_and_removing_a_folder_library(app, tmp_path):
    media = Path(app.state.ctx.settings.media_dir)
    with TestClient(app) as home:
        top = home.get("/api/folder-libraries/browse").json()
        assert top["path"] == "" and "TV" in top["folders"]
        inside = home.get("/api/folder-libraries/browse?path=TV").json()
        assert set(inside["folders"]) >= {"Northbound (2019) {tvdb-90001}", "Orbit Room"}
        for bad in ("..", "../..", "/etc", "TV/../../..", "nothing here"):
            assert home.get(f"/api/folder-libraries/browse?path={bad}").status_code == 404, bad
        for body in (
            {"name": "", "kind": "show", "folders": ["TV"]},
            {"name": "TV", "kind": "clips", "folders": ["TV"]},
            {"name": "TV", "kind": "show", "folders": ["../"]},
            {"name": "TV", "kind": "show", "folders": [str(tmp_path)]},
            {"name": "TV", "kind": "show", "folders": []},
            {"name": "x" * 61, "kind": "show", "folders": ["TV"]},
        ):
            assert home.post("/api/folder-libraries", json=body).status_code in (400, 422), body
        made = home.post(
            "/api/folder-libraries", json={"name": "TV", "kind": "show", "folders": ["TV"]}
        )
        assert made.status_code == 201 and made.json()["key"] == "f1"
        lib = scanned(home, "f1")
        assert lib["shows"] == 4 and lib["folders"] == [os.path.realpath(media / "TV")]
        changed = home.put("/api/folder-libraries/f1", json={"name": "Shows"})
        assert changed.status_code == 200 and changed.json()["name"] == "Shows"
        assert home.put("/api/folder-libraries/f9", json={"name": "x"}).status_code == 404
        assert home.post("/api/folder-libraries/f1/scan").status_code == 202
        assert home.get("/api/libraries").json() == [
            {"key": "f1", "title": "Shows", "type": "show"}
        ]
        assert home.delete("/api/folder-libraries/f1").status_code == 204
        assert home.get("/api/folder-libraries").json()["libraries"] == []
        assert home.delete("/api/folder-libraries/f1").status_code == 404


def test_folder_libraries_are_for_admins_only(app):
    with TestClient(app) as pat:
        assert pat.post("/api/access/users", json=PAT).status_code == 201
        pat.post("/api/folder-libraries", json={"name": "TV", "kind": "show", "folders": ["TV"]})
        scanned(pat, "f1")
        assert pat.post("/api/access/users", json={**SAM, "role": "user"}).status_code == 201
        sam = TestClient(app)
        assert sam.post("/api/access/sign-in", json=SAM).status_code == 200
        for method, path, body in (
            ("GET", "/api/folder-libraries", None),
            ("GET", "/api/folder-libraries/browse", None),
            ("POST", "/api/folder-libraries", {"name": "Mine", "kind": "show", "folders": ["TV"]}),
            ("PUT", "/api/folder-libraries/f1", {"name": "Mine"}),
            ("DELETE", "/api/folder-libraries/f1", None),
            ("POST", "/api/folder-libraries/f1/scan", None),
        ):
            got = sam.request(method, path, json=body)
            assert got.status_code == 403, (method, path, got.status_code)
        # (What a User may see of libraries, they still may: the editor's list.)
        assert [x["key"] for x in sam.get("/api/libraries").json()] == ["f1"]
        stranger = TestClient(app)
        assert stranger.get("/api/folder-libraries").status_code == 401


def test_reading_stops_when_tapioca_does(tmp_path, clips, monkeypatch):
    """A Media folder still being read when tapiOca stops: the reading
    stops with it, never left running."""
    import asyncio

    from app import folderscan

    async def slow(*_args, **_kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(folderscan, "read_file", slow)
    media = tmp_path / "media"
    sonarr_tv(media / "TV", clips)
    app = create_app(Settings(data_dir=tmp_path / "data", media_dir=str(media)), PlexClient("", ""))
    with TestClient(app) as home:
        made = home.post("/api/folder-libraries",
                         json={"name": "TV", "kind": "show", "folders": ["TV"]})  # fmt: skip
        assert made.status_code == 201
        tasks = list(app.state.ctx.folders._tasks)
        assert tasks and not any(t.done() for t in tasks)
    assert all(t.cancelled() for t in tasks)
