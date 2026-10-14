"""Marking a whole show, or one of its seasons, watched or not at once
(1.36.3, POST /api/internal/watched): one request, all of it or none, only
what the person may see. Before, an app sent one request for each episode,
and one failing partway left a season half marked."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import applibrary, db
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex
from .test_who_sees_what import ADA, KIT, kid_level, sign_in_app


@pytest.fixture
def plex():
    fp = LibraryPlex()
    fp.add_show("100", "Puppet Town", contentRating=["TV-Y7"])
    for n in range(1, 4):
        fp.add_episode(f"20{n}", "100", 1, n, f"Puppets {n}", f"/tv/p/1-{n}.mkv", 22 * 60_000)
    # (Season 2's first episode is in one file with season 1's last.)
    fp.add_episode("204", "100", 2, 1, "Puppets 4", "/tv/p/1-3.mkv", 22 * 60_000)
    fp.add_episode("205", "100", 2, 2, "Puppets 5", "/tv/p/2-2.mkv", 22 * 60_000)
    fp.add_episode("206", "100", 2, 3, "Puppets 6", "/tv/p/2-3.mkv", 22 * 60_000)
    fp.add_show("110", "Night Shift", contentRating=["TV-MA"])
    fp.add_episode("211", "110", 1, 1, "Shift 1", "/tv/n/1.mkv", 44 * 60_000)
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Picnic", "/m/picnic.mkv", 90 * 60_000, section="2", contentRating=["PG"])
    return fp


@pytest.fixture
def app(plex, tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    return create_app(settings, PlexClient("http://plex.test", "token", transport=plex.transport()))


def unwatched(client: TestClient, show: str = "100", **kw) -> tuple[int, list[tuple]]:
    got = client.get(f"/api/internal/items/{show}", **kw).json()
    return got["unwatched"], [(s["season"], s["unwatched"]) for s in got["seasons"]]


def mark(client: TestClient, body: dict, **kw):
    return client.post("/api/internal/watched", json=body, **kw)


def test_a_season_then_the_whole_show_then_none_of_it(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        assert unwatched(home) == (6, [(1, 3), (2, 3)])
        # Partway into one: marking puts it back to the start, as marking one does.
        home.post("/api/internal/progress", json={"key": "205", "positionMs": 5 * 60_000})

        got = mark(home, {"show": "100", "season": 1, "watched": True})
        assert got.status_code == 200, got.text
        # (Season 2's first episode is in season 1's last file: it goes with it.)
        assert got.json() == {"watched": True, "marked": 4}
        assert unwatched(home) == (2, [(1, 0), (2, 2)])

        assert mark(home, {"show": "100", "watched": True}).json() == {"watched": True, "marked": 6}
        assert unwatched(home) == (0, [(1, 0), (2, 0)])
        assert home.get("/api/internal/home").json()["continue"] == []

        assert mark(home, {"show": "100", "watched": False}).json()["marked"] == 6
        assert unwatched(home) == (6, [(1, 3), (2, 3)])
        assert home.get("/api/internal/items/205").json()["positionMs"] == 0
        # A season with nothing in it marks nothing.
        assert mark(home, {"show": "100", "season": 9, "watched": True}).json()["marked"] == 0


def test_only_a_shared_show_and_never_a_movie_or_an_episode(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        hidden = mark(home, {"show": "100", "watched": True})
        assert hidden.status_code == 404
        assert hidden.json() == mark(home, {"show": "999", "watched": True}).json()
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        assert mark(home, {"show": "300", "watched": True}).status_code == 400
        assert mark(home, {"show": "201", "watched": True}).status_code == 400
        assert mark(home, {"show": "100"}).status_code == 400
        assert mark(home, {"show": "100", "season": -1, "watched": True}).status_code == 400
        assert unwatched(home) == (6, [(1, 3), (2, 3)])


def test_too_many_at_once_marks_none_of_them(app, monkeypatch):
    # (Never more than half of what's kept for each person, so marking
    # never pushes out what it marked.)
    assert applibrary.MARK_MOST * 2 <= db.PROGRESS_KEPT
    monkeypatch.setattr(applibrary, "MARK_MOST", 5)
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        refused = mark(home, {"show": "100", "watched": True})
        assert refused.status_code == 400
        assert applibrary.TOO_MANY_TO_MARK in refused.text
        assert unwatched(home) == (6, [(1, 3), (2, 3)])
        assert mark(home, {"show": "100", "season": 2, "watched": True}).json()["marked"] == 4


def test_a_kid_cant_mark_a_show_above_their_level(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        level = {"level": kid_level(admin)}
        assert admin.put(f"/api/access/users/{kit['id']}/viewing", json=level).status_code == 200
        admin.portal.call(admin.app.state.ctx.titles.filled)
        admin.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        as_kit = sign_in_app(app, KIT)
        phone = TestClient(app)
        refused = mark(phone, {"show": "110", "watched": True}, headers=as_kit)
        assert refused.status_code == 404
        allowed = mark(phone, {"show": "100", "watched": True}, headers=as_kit)
        assert allowed.json() == {"watched": True, "marked": 6}
        # Each person's own: Ada's are as they were.
        assert unwatched(admin)[0] == 6
