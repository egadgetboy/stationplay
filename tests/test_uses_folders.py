"""Media folders of tapiOca's own, without Plex (1.37.0): episodes with no
season, as the apps ask for them; Tag filters from NFO files (<tag>); and
what's said when a collection is gone, by where it was."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .folderlib import Clips, movie_nfo, put, sonarr_tv

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


@pytest.fixture(scope="module")
def clips(tmp_path_factory) -> Clips:
    return Clips(tmp_path_factory.mktemp("clips"))


@pytest.fixture
def media(tmp_path, clips) -> dict[str, Path]:
    root = tmp_path / "media"
    out = {**sonarr_tv(root / "TV", clips), "root": root}
    # Two episodes with nothing to say which season they're in.
    out["loose1"] = put(out["show"] / "Northbound - Making Of.mkv", clips.plain)
    out["loose2"] = put(out["show"] / "Northbound - Bloopers.mkv", clips.plain)
    movies = root / "Movies"
    for title, year, tag in (("Snow Day", 1998, "Christmas"), ("Heat Wave", 2001, "Summer")):
        folder = movies / f"{title} ({year})"
        put(folder / f"{title} ({year}).mkv", clips.plain)
        nfo = movie_nfo(title, year).replace("</movie>", f"  <tag>{tag}</tag>\n</movie>")
        put(folder / f"{title} ({year}).nfo", text=nfo)
    return out


@pytest.fixture
def app(tmp_path, media):
    return create_app(
        Settings(data_dir=tmp_path / "data", media_dir=str(media["root"])), PlexClient("", "")
    )


def add_library(home: TestClient, name: str, kind: str, folder: str) -> str:
    made = home.post(
        "/api/folder-libraries", json={"name": name, "kind": kind, "folders": [folder]}
    )
    assert made.status_code == 201, made.text
    key = made.json()["key"]
    for _ in range(400):
        found = {x["key"]: x for x in home.get("/api/folder-libraries").json()["libraries"]}
        if found[key]["scannedMs"]:
            return key
        time.sleep(0.05)
    raise AssertionError("the folder library wasn't scanned")


def test_episodes_with_no_season(app):
    with TestClient(app) as home:
        tv = add_library(home, "TV", "show", "TV")
        assert home.put("/api/app-libraries", json={"libraries": [tv]}).status_code == 200
        shows = {x["title"]: x["key"] for x in home.get(f"/api/internal/libraries/{tv}").json()["items"]}
        show = shows["Northbound"]
        seasons = home.get(f"/api/internal/items/{show}").json()["seasons"]
        loose = [s for s in seasons if s["season"] is None]
        assert loose and loose[0]["title"] == "Episodes"
        got = home.get(f"/api/internal/items/{show}/episodes?season=none").json()
        assert got["season"] == "none" and got["total"] == loose[0]["episodes"] == 2
        assert len(got["episodes"]) == 2
        first = home.get(f"/api/internal/items/{show}/episodes?season=1").json()
        assert first["season"] == 1 and first["total"] == 4  # (as before)
        assert home.get(f"/api/internal/items/{show}/episodes?season=x").status_code == 400


def test_a_tag_filter_for_your_own_folders(app):
    with TestClient(app) as home:
        movies = add_library(home, "Movies", "movie", "Movies")
        fields = home.get(f"/api/filter/fields?kind=movie&libraries={movies}").json()
        tag = next(f for f in fields["fields"] if f["field"] == "label")
        assert tag["title"] == "Tag" and tag["choices"] == ["Christmas", "Summer"]
        christmas = {"type": "filter", "kind": "movie", "libraries": [movies],
                     "tags": {"label": ["Christmas"]}}  # fmt: skip
        preview = home.post("/api/filter/preview", json=christmas).json()
        assert preview["examples"] == ["Snow Day (1998)"]


def test_a_gone_collection_is_said_by_where_it_was(app):
    """Not "Plex no longer has the collection" for a folder of your own."""
    with TestClient(app) as home:
        add_library(home, "Movies", "movie", "Movies")
        gone = home.post("/api/collections/stations", json={"ratingKeys": ["f9"]})
        assert gone.status_code == 400
        assert gone.json()["detail"] == "Its Media folder no longer has the collection 'f9'"
