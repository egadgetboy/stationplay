"""Shuffle on a show's page (1.37.0, the owner, October 14: "Shuffle all",
then "Shuffle unwatched"): GET /api/internal/items/{key}/shuffle, the show's
episodes in a random order, those the person may see, specials aside, each
file once."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import applibrary

from .test_mark_show import app, mark, plex  # noqa: F401  (the fixtures)
from .test_who_sees_what import ADA, KIT, kid_level, sign_in_app


def shuffled(client: TestClient, show: str, unwatched: bool = False, **kw):
    return client.get(
        f"/api/internal/items/{show}/shuffle" + ("?unwatched=1" if unwatched else ""), **kw
    )


def test_every_episode_once_specials_aside_in_a_new_order_each_time(app, plex):  # noqa: F811
    plex.add_episode("290", "100", 0, 1, "Behind the Puppets", "/tv/p/s0-1.mkv", 22 * 60_000)
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        got = shuffled(home, "100")
        assert got.status_code == 200, got.text
        body = got.json()
        keys = [c["key"] for c in body["items"]]
        # (203 and 204 are one file: it plays once. The special stays out.)
        assert sorted(keys) == ["201", "202", "203", "205", "206"]
        assert body["total"] == 5 and body["unwatched"] is False
        assert all(c["kind"] == "episode" for c in body["items"])
        orders = {tuple(c["key"] for c in shuffled(home, "100").json()["items"]) for _ in range(30)}
        assert len(orders) > 1  # (a new order each time: 120 possible)


def test_shuffle_unwatched_leaves_out_what_was_watched(app):  # noqa: F811
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        assert mark(home, {"show": "100", "season": 1, "watched": True}).status_code == 200
        left = shuffled(home, "100", unwatched=True).json()
        assert (
            sorted(c["key"] for c in left["items"]) == ["205", "206"] and left["unwatched"] is True
        )
        assert mark(home, {"show": "100", "watched": True}).status_code == 200
        assert shuffled(home, "100", unwatched=True).json()["items"] == []
        assert len(shuffled(home, "100").json()["items"]) == 5  # (Shuffle all: still every one)


def test_only_a_show_someone_may_see(app):  # noqa: F811
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        admin.put(f"/api/access/users/{kit['id']}/viewing", json={"level": kid_level(admin)})
        admin.portal.call(admin.app.state.ctx.titles.filled)
        admin.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        as_kit = sign_in_app(app, KIT)
        phone = TestClient(app)
        hidden = shuffled(phone, "110", headers=as_kit)
        assert hidden.status_code == 404
        assert hidden.json() == shuffled(phone, "999", headers=as_kit).json()
        assert shuffled(phone, "100", headers=as_kit).status_code == 200
        assert shuffled(admin, "300").status_code == 400  # (a movie)


def test_at_most_shuffle_most(app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(applibrary, "SHUFFLE_MOST", 2)
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        assert len(shuffled(home, "100").json()["items"]) == 2


def test_only_a_show_and_only_from_a_shared_media_folder(app):  # noqa: F811
    # (The cold audit, 1.37.0: an episode's key is refused, and a show in a
    # Media folder that isn't shared is as though it weren't there.)
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        assert shuffled(home, "100").status_code == 404
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        assert shuffled(home, "201").status_code == 400  # (an episode)


def test_unwatched_keeps_a_file_whose_other_episode_is_unwatched(app):  # noqa: F811
    # (The cold audit, 1.37.0: 203 and 204 are one file. Marking one marks
    # both, but one alone can be watched, as kept from before the two were
    # one file. The file still has 204 to watch: it plays once, as 204.)
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        home.app.state.ctx.db.save_progress(0, "203", "100", 0, 22 * 60_000, True, 1)
        left = shuffled(home, "100", unwatched=True).json()
        keys = sorted(c["key"] for c in left["items"])
        assert keys == ["201", "202", "204", "205", "206"], keys
