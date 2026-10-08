"""Who sees what, end to end (see docs/users.md): someone on the Kid Viewing
Level never sees a TV-MA show or an R movie anywhere StationPlay lists or
plays things, a station with one program above their level is hidden from
them unless an Admin allows it, and a StationPlay with no limits answers as
it always has."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex

ADA = {"name": "Ada", "password": "correct horse"}
KIT = {"name": "Kit", "password": "battery staple"}
TV = {"containers": ["mp4", "mkv"], "video": [{"codec": "h264", "width": 1920, "height": 1080,
      "bitDepth": 8}], "hdr": [], "audio": ["aac", "ac3"]}  # fmt: skip


@pytest.fixture
def plex(tmp_path):
    fp = LibraryPlex()
    fp.add_show("100", "Puppet Town", contentRating=["TV-Y7"])
    for n in range(1, 4):
        fp.add_episode(f"20{n}", "100", 1, n, f"Puppets {n}", f"/tv/p/{n}.mkv", 22 * 60_000)
    fp.add_show("110", "Night Shift", contentRating=["TV-MA"])
    for n in range(1, 3):
        fp.add_episode(f"21{n}", "110", 1, n, f"Shift {n}", f"/tv/n/{n}.mkv", 44 * 60_000)
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Picnic", "/m/picnic.mkv", 90 * 60_000, section="2", contentRating=["PG"])
    fp.add_movie("301", "Heist", "/m/heist.mkv", 100 * 60_000, section="2", contentRating=["R"])
    for key in ("201", "211", "300", "301"):
        fp.describe(key)
        fp.files[key] = b"a program" * 100
    return fp


@pytest.fixture
def app(plex, tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=plex.transport()))
    app.state.ctx.play_transport = plex.transport()
    return app


STATIONS = {
    3: ("Puppets", [{"type": "show", "ratingKey": "100"}]),
    5: ("Late Night", [{"type": "show", "ratingKey": "110"}]),
    7: ("Mixed", [{"type": "show", "ratingKey": "100"}, {"type": "movie", "ratingKey": "301"}]),
    9: ("Family Movies", [{"type": "movie", "ratingKey": "300"}]),
}


def set_up(admin: TestClient) -> dict[int, int]:
    """Ada, the stations, the libraries shared, and the ratings of what's on
    the stations asked for: each station's id, by number."""
    ids = {}
    for number, (name, sources) in STATIONS.items():
        made = admin.post(
            "/api/channels", json={"number": number, "name": name, "sources": sources}
        )
        assert made.status_code == 201, made.text
        ids[number] = made.json()["id"]
    admin.portal.call(admin.app.state.ctx.titles.filled)
    assert admin.put("/api/app-libraries", json={"libraries": ["1", "2"]}).status_code == 200
    return ids


def kid_level(admin: TestClient) -> int:
    levels = admin.get("/api/access/viewing").json()["levels"]
    return next(lv["id"] for lv in levels if lv["builtin"] == "kid")


def sign_in_app(app, who: dict) -> dict[str, str]:
    phone = TestClient(app)
    signed = phone.post("/api/internal/sign-in", json=who)
    assert signed.status_code == 200, signed.text
    return {"Authorization": f"Bearer {signed.json()['token']}"}


def test_a_kid_never_sees_whats_above_their_level(app):
    with TestClient(app) as admin:
        ids = set_up(admin)
        admin.post("/api/access/users", json=ADA)
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        changed = admin.put(
            f"/api/access/users/{kit['id']}/viewing", json={"level": kid_level(admin)}
        )
        assert changed.status_code == 200, changed.text
        as_kit = sign_in_app(app, KIT)
        phone = TestClient(app)

        # The stations: only those with nothing above Kid (station numbers stay).
        listed = phone.get("/api/v1/stations", headers=as_kit).json()["stations"]
        assert [s["number"] for s in listed] == [3, 9]
        now = int(time.time() * 1000)
        guide = phone.get(f"/api/v1/guide?from={now}", headers=as_kit).json()["stations"]
        assert [s["number"] for s in guide] == [3, 9]
        # Ada sees them all.
        assert len(admin.get("/api/v1/stations").json()["stations"]) == 4

        # The library: no TV-MA show, no R movie, in any list.
        def keys(cards):
            return {c["key"] for c in cards}

        shows = phone.get("/api/internal/libraries/1", headers=as_kit).json()
        assert keys(shows["items"]) == {"100"} and shows["total"] == 1
        movies = phone.get("/api/internal/libraries/2", headers=as_kit).json()
        assert keys(movies["items"]) == {"300"} and movies["total"] == 1
        home = phone.get("/api/internal/home", headers=as_kit).json()
        assert all(keys(row["items"]) <= {"100", "300"} for row in home["added"])
        found = phone.get("/api/internal/search?q=i", headers=as_kit).json()
        assert "110" not in keys(found["items"]) and "301" not in keys(found["items"])
        assert all(s["number"] in (3, 9) for s in found["onNow"])

        # Asked about directly: the same answer as for something that doesn't exist.
        for key in ("110", "211", "301"):
            refused = phone.get(f"/api/internal/items/{key}", headers=as_kit)
            assert refused.status_code == 404, key
            assert refused.json() == phone.get("/api/internal/items/999", headers=as_kit).json()
            assert phone.get(f"/api/internal/art/{key}", headers=as_kit).status_code == 404
            played = phone.post(
                "/api/internal/play", json={"key": key, "device": TV}, headers=as_kit
            )
            assert played.status_code == 404, key
        assert phone.get("/api/internal/items/110/episodes", headers=as_kit).status_code == 404
        assert phone.get("/api/internal/items/100", headers=as_kit).status_code == 200
        assert (
            phone.post(
                "/api/internal/play", json={"key": "300", "device": TV}, headers=as_kit
            ).status_code
            == 200
        )

        # On the page, as Kit: the same stations, and nothing to make or change.
        page = TestClient(app)
        page.post("/api/access/sign-in", json=KIT)
        assert [c["number"] for c in page.get("/api/channels").json()] == [3, 9]
        assert page.get(f"/api/channels/{ids[5]}/guide").status_code == 404
        assert page.get(f"/api/channels/{ids[3]}/guide").status_code == 200
        assert page.get("/api/libraries").status_code == 403
        refused = page.post("/api/channels", json={"number": 11, "name": "Mine", "sources": []})
        assert refused.status_code == 403 and "watch" in refused.json()["detail"]


def test_an_admin_can_allow_or_block_a_station_for_someone(app):
    with TestClient(app) as admin:
        ids = set_up(admin)
        admin.post("/api/access/users", json=ADA)
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        as_kit = sign_in_app(app, KIT)
        phone = TestClient(app)

        def numbers():
            return [
                s["number"]
                for s in phone.get("/api/v1/stations", headers=as_kit).json()["stations"]
            ]

        # On Adult, with Late Night blocked.
        admin.put(f"/api/access/users/{kit['id']}/viewing", json={"stations": {str(ids[5]): False}})
        assert numbers() == [3, 7, 9]
        # On Kid, with Mixed (one R movie) allowed after all.
        admin.put(
            f"/api/access/users/{kit['id']}/viewing",
            json={"level": kid_level(admin), "stations": {str(ids[7]): True}},
        )
        assert numbers() == [3, 7, 9]
        listed = admin.get(f"/api/access/users/{kit['id']}/stations").json()
        why = {s["number"]: (s["chosen"], s["why"]) for s in listed["stations"]}
        assert why[3] == ("level", None)
        assert why[5] == ("level", "It plays shows rated TV-MA")
        assert why[7] == ("allowed", "It plays movies rated R")
        # Logged, in plain words.
        logs = admin.get("/api/logs?access_log=true").json()["text"]
        assert "Ada put Kit on the Viewing Level Kid and allowed station 7 for Kit" in logs


def test_a_station_whose_ratings_arent_known_yet_is_hidden_from_a_limit(app):
    ctx = app.state.ctx
    with TestClient(app) as admin:
        set_up(admin)
        admin.post("/api/access/users", json=ADA)
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        admin.put(f"/api/access/users/{kit['id']}/viewing", json={"level": kid_level(admin)})
        # (As though the show's rating hadn't been asked for yet.)
        ctx.db.save_titles([("100", "show", "", "1", 0, 0)])
        ctx.titles.__init__(ctx.db)
        as_kit = sign_in_app(app, KIT)
        listed = TestClient(app).get("/api/v1/stations", headers=as_kit).json()["stations"]
        assert [s["number"] for s in listed] == [9]


def test_levels_are_kept_on_the_access_tab(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        state = admin.get("/api/access/viewing").json()
        assert [lv["name"] for lv in state["levels"]] == ["Adult", "Teen", "Kid", "Young Child"]
        assert state["movieRatings"][0] == [0, "G"] and state["tvRatings"][-1] == [17, "TV-MA"]
        made = admin.post(
            "/api/access/levels",
            json={
                "name": "Grandparents",
                "movieAge": 13,
                "tvAge": 14,
                "unrated": True,
                "libraries": ["2"],
            },
        )
        assert made.status_code == 201, made.text
        assert made.json()["libraries"] == ["2"]
        bad = admin.post("/api/access/levels", json={"name": "Odd", "movieAge": 40})
        assert bad.status_code == 400 and bad.json()["detail"] == "Choose a rating from the list"
        kid = kid_level(admin)
        assert admin.delete(f"/api/access/levels/{kid}").status_code == 400
        assert admin.delete(f"/api/access/levels/{made.json()['id']}").status_code == 204
        logs = admin.get("/api/logs?access_log=true").json()["text"]
        assert (
            "Ada added the Viewing Level Grandparents (movies up to PG-13, shows up to TV-14, "
            "unrated shown, 1 library)" in logs
        )


def test_with_no_limits_everything_is_as_it_was(app):
    with TestClient(app) as admin:
        set_up(admin)
        # Signing in off: everything, to everyone.
        assert len(admin.get("/api/v1/stations").json()["stations"]) == 4
        admin.post("/api/access/users", json=ADA)
        admin.post("/api/access/users", json={**KIT, "role": "user"})
        as_kit = sign_in_app(app, KIT)
        phone = TestClient(app)
        assert len(phone.get("/api/v1/stations", headers=as_kit).json()["stations"]) == 4
        movies = phone.get("/api/internal/libraries/2", headers=as_kit).json()
        assert {c["key"] for c in movies["items"]} == {"300", "301"}
        # A User on Adult still makes stations.
        page = TestClient(app)
        page.post("/api/access/sign-in", json=KIT)
        made = page.post("/api/channels", json={"number": 11, "name": "Mine", "sources": [
            {"type": "show", "ratingKey": "100"}]})  # fmt: skip
        assert made.status_code == 201, made.text
