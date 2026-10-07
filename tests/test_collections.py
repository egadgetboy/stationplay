"""Stations from Plex's collections: one per collection, each following
its collection as it changes in Plex."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .fakeplex import FakePlex
from .test_updates import check, make_client

MIN = 60_000


@pytest.fixture
def plex():
    """TV and movies, with a Christmas collection in each library, a
    Westerns collection of movies, and one of old sitcoms."""
    fp = FakePlex()
    fp.add_section("2", "Movies", "movie")
    for n in range(1, 9):
        fp.add_movie(f"50{n}", f"Movie {n}", f"/movies/{n}.mkv", 90 * MIN, section="2")
    fp.add_show("100", "Holiday Special Show")
    fp.add_show("101", "Old Sitcom")
    for show, eps in (("100", 3), ("101", 4)):
        for n in range(1, eps + 1):
            fp.add_episode(f"{show}{n}", show, 1, n, f"Ep {n}", f"/tv/{show}/{n}.mkv", 22 * MIN)
    fp.add_collection("900", "Christmas", "2", "501", "502", "503")
    fp.add_collection("901", "Christmas ", "1", "100")  # the same name, near enough
    fp.add_collection("902", "Westerns", "2", "504", "505")
    fp.add_collection("903", "Sitcoms", "1", "101")
    return fp


@pytest.fixture
def client(tmp_path, plex):
    with make_client(tmp_path, plex) as c:
        # Station 1 is taken already: collection stations start at 2.
        made = c.post(
            "/api/channels", json={"number": 1, "sources": [{"type": "show", "ratingKey": "101"}]}
        )
        assert made.status_code == 201, made.text
        yield c


def make(client, *keys: str):
    return client.post("/api/collections/stations", json={"ratingKeys": list(keys)})


def test_each_collection_is_listed_and_repeated_names_are_numbered(client):
    listed = {c["name"]: c for c in client.get("/api/collections").json()}
    # Numbered in the order Plex lists its libraries (TV Shows, then Movies).
    assert list(listed) == ["Christmas1", "Christmas2", "Sitcoms", "Westerns"]
    assert (listed["Christmas1"]["libraryTitle"], listed["Christmas1"]["kind"]) == (
        "TV Shows", "show",
    )  # fmt: skip
    assert (listed["Christmas2"]["libraryTitle"], listed["Christmas2"]["count"]) == ("Movies", 3)
    assert all(c["station"] is None for c in listed.values())


def test_a_station_for_each_collection(client, plex):
    made = make(client, "900", "901", "902")
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["problems"] == []
    stations = {s["name"]: s for s in body["made"]}
    assert {s["number"] for s in stations.values()} == {2, 3, 4}  # the next free numbers
    # Not combined: the movies in one station, the show's episodes in another.
    assert stations["Christmas2"]["itemCount"] == 3
    assert stations["Christmas1"]["itemCount"] == 3
    assert stations["Westerns"]["itemCount"] == 2
    christmas = stations["Christmas2"]
    assert [s["type"] for s in christmas["sources"]] == ["collection"]
    assert christmas["orderMode"] == "rotate"  # what new stations start with (in the tests)
    listed = {c["name"]: c["station"] for c in client.get("/api/collections").json()}
    assert listed == {
        "Christmas1": stations["Christmas1"]["number"],
        "Christmas2": christmas["number"],
        "Sitcoms": None,
        "Westerns": stations["Westerns"]["number"],
    }
    # Asking for one Plex doesn't have says so.
    again = make(client, "999")
    assert again.status_code == 400 and "no longer has the collection" in again.json()["detail"]


def station(client, name: str) -> dict:
    return next(c for c in client.get("/api/channels").json() if c["name"] == name)


def test_a_collection_station_follows_its_collection(client, plex):
    make(client, "902")
    # Added to the collection in Plex (its library's timestamps don't
    # change): the hourly check notices and the station gets them.
    check(client, force=True)
    plex.collect("902", "506", "507")
    check(client, force=False)
    pending = station(client, "Westerns")["pending"]
    assert pending is not None and (pending["added"], pending["removed"]) == (2, 0)
    updated = client.post(f"/api/channels/{station(client, 'Westerns')['id']}/update").json()
    assert updated["itemCount"] == 4
    # Plex makes the collection again (a new rating key): followed by name.
    plex.collections["990"] = plex.collections.pop("902")
    check(client)
    assert station(client, "Westerns")["pending"] is None
    # And if it's gone, that waits for you rather than emptying the station.
    del plex.collections["990"]
    check(client)
    pending = station(client, "Westerns")["pending"]
    assert pending["held"] and pending["removed"] == 4


def test_collection_sources_are_checked(client):
    for bad in (
        {"type": "collection", "title": "Westerns", "library": "2", "kind": "movie"},
        {"type": "collection", "ratingKey": "902", "title": "", "library": "2", "kind": "movie"},
        {"type": "collection", "ratingKey": "902", "title": "W", "library": "2", "kind": "song"},
    ):
        made = client.post("/api/channels", json={"number": 9, "sources": [bad]})
        assert made.status_code == 400, bad


def test_other_stations_update_when_plex_cant_list_its_collections(client, plex):
    """Asking Plex about collections failing never holds up the hourly
    check: the other stations still get their new episodes."""
    make(client, "902")
    check(client, force=True)
    plex.collections_down = True
    plex.add_episode("1015", "101", 1, 5, "Ep 5", "/tv/101/5.mkv", 22 * MIN)
    check(client, force=False)
    pending = station(client, "Station 1")["pending"]
    assert pending is not None and pending["added"] == 1
    assert station(client, "Westerns")["pending"] is None  # nothing changed there


def test_a_collection_made_again_is_remembered(client, plex):
    make(client, "902")
    plex.collections["990"] = plex.collections.pop("902")
    check(client)
    plex.requests.clear()
    check(client)
    # Straight to the collection's new key: not the old one, then a search.
    asked = [r for r in plex.requests if "/collections" in r]
    assert "/library/collections/990/children" in asked
    assert "/library/collections/902/children" not in asked


def test_a_renamed_collection_is_still_followed(client, plex):
    westerns = make(client, "902").json()["made"][0]
    check(client, force=True)
    plex.collections["902"]["title"] = "Wild West"
    plex.collect("902", "506")
    check(client, force=False)
    pending = station(client, "Westerns")["pending"]
    assert pending is not None and (pending["added"], pending["removed"]) == (1, 0)
    listed = {c["name"]: c["station"] for c in client.get("/api/collections").json()}
    assert listed["Wild West"] == westerns["number"]


def test_two_collections_with_one_name_in_a_library_are_told_apart(client, plex):
    plex.add_collection("904", "Westerns", "2", "506", "507", "508")
    listed = {c["name"]: c for c in client.get("/api/collections").json()}
    assert (listed["Westerns1"]["ratingKey"], listed["Westerns2"]["ratingKey"]) == ("902", "904")
    made = make(client, "904").json()["made"][0]
    assert (made["name"], made["itemCount"]) == ("Westerns2", 3)
    listed = {c["name"]: c["station"] for c in client.get("/api/collections").json()}
    assert listed["Westerns1"] is None and listed["Westerns2"] == made["number"]


def test_an_emptied_collection_is_just_empty(client, plex):
    """Not taken for one Plex made again (and swapped for another of the
    same name): the station waits for you, with nothing added."""
    plex.add_collection("904", "Westerns", "2", "506", "507", "508")
    make(client, "902")
    plex.collections["902"]["children"] = []
    check(client)
    pending = station(client, "Westerns1")["pending"]
    assert (pending["added"], pending["removed"], pending["held"]) == (0, 2, True)


def test_a_newer_plex_that_lists_collections_another_way(client, plex):
    plex.newer_collections = True
    listed = {c["name"]: c for c in client.get("/api/collections").json()}
    assert listed["Westerns"]["count"] == 2
    made = make(client, "902").json()["made"][0]
    assert made["itemCount"] == 2
    # A newer Plex that has made it again: found by name the newer way too.
    plex.collections["990"] = plex.collections.pop("902")
    plex.collect("990", "506")
    check(client)
    assert station(client, "Westerns")["pending"]["added"] == 1


def test_numbered_names_stay_readable():
    from app.main import NAME_MAX, _numbered

    assert _numbered("Sunshine", 2) == "Sunshine2"
    assert _numbered("Top 10", 1) == "Top 10 (1)"
    long = _numbered("x" * 70, 12)
    assert len(long) == NAME_MAX and long.endswith("x12")


def test_a_user_makes_stations_from_collections_only_as_far_as_they_may(client):
    # Signing in on (whoever's using `client` is its Admin), and Sam, a User
    # who may make one station.
    client.post("/api/access/users", json={"name": "Pat", "password": "correct horse"})
    sam = {"name": "Sam", "password": "battery staple"}
    assert client.post("/api/access/users", json={**sam, "maxStations": 1}).status_code == 201
    browser = TestClient(client.app)
    assert browser.post("/api/access/sign-in", json=sam).status_code == 200
    got = make(browser, "900", "902", "903")
    assert got.status_code == 201, got.text
    assert len(got.json()["made"]) == 1
    problems = got.json()["problems"]
    assert len(problems) == 2
    assert all(p.split(": ", 1)[1].startswith("Your limit is 1 station, and") for p in problems)
    # And none at all once they've made theirs.
    assert make(browser, "901").status_code == 400
