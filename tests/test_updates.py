"""Automatic updates from Plex, and filters, through the web app."""

from __future__ import annotations

import itertools
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import updates
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .helpers import add_again, like_plex

MIN = 60_000
PLEX = {"user-agent": "PlexMediaServer/1.41.3.9314-a0bfb8370"}
BROWSER = {"user-agent": "Mozilla/5.0 (Macintosh) Safari/605.1.15"}


def make_client(tmp_path, fp: FakePlex) -> TestClient:
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    return TestClient(app)


def programmes(xml: str) -> list[tuple[int, str]]:
    """(start in ms, title/sub-title) of every programme in a guide."""
    out = []
    for p in ET.fromstring(xml).findall("programme"):
        start = datetime.strptime(p.get("start"), "%Y%m%d%H%M%S %z").timestamp() * 1000
        out.append((int(start), p.findtext("sub-title") or p.findtext("title")))
    return out


@pytest.fixture
def tv(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "The Jetsons")
    for n in (1, 2):
        fp.add_episode(f"2{n:02d}", "100", 1, n, f"Jetsons {n}", f"/tv/j{n}.mkv", 22 * MIN)
    fp.add_show("300", "The Flintstones")
    for n in (1, 2, 3):
        fp.add_episode(f"3{n:02d}", "300", 1, n, f"Flintstones {n}", f"/tv/f{n}.mkv", 22 * MIN)
    with make_client(tmp_path, fp) as client:
        created = client.post(
            "/api/channels",
            json={
                "number": 2,
                "orderMode": "rotate",
                "sources": [
                    {"type": "show", "ratingKey": "100"},
                    {"type": "show", "ratingKey": "300"},
                ],
            },
        )
        assert created.status_code == 201, created.text
        yield client, fp, created.json()


def check(client: TestClient, force: bool = True) -> None:
    client.portal.call(client.app.state.ctx.updater.check, force)


def test_new_episodes_wait_for_plex_then_join_after_its_guide(tv):
    client, fp, _station = tv
    before = programmes(client.get("/xmltv.xml", headers=BROWSER).text)
    for n in range(3, 26):
        fp.add_episode(f"2{n:02d}", "100", 1, n, f"Jetsons {n}", f"/tv/j{n}.mkv", 22 * MIN)
    check(client)
    card = client.get("/api/channels").json()[0]
    assert card["pending"] == {
        "added": 23,
        "removed": 0,
        "foundAt": card["pending"]["foundAt"],
        "held": False,
        "lostSkips": 0,
        "specials": False,
    }

    # Other apps, and people looking at the guide in a browser, don't
    # trigger it: Plex's copy of the guide is the one that matters.
    client.get("/guide.xml", headers=PLEX)
    client.get("/xmltv.xml", headers=BROWSER)
    assert client.get("/api/channels").json()[0]["pending"] is not None

    asked = int(time.time() * 1000)
    after = programmes(client.get("/xmltv.xml", headers=PLEX).text)
    card = client.get("/api/channels").json()[0]
    assert card["pending"] is None
    change = card["lastChange"]
    assert change["reason"] == "update" and change["added"] == 23
    starts = change["startsAt"]
    assert starts >= asked + updates.MARGIN_MS
    assert starts // 1000 * 1000 in {s for s, _ in before}  # at a program break
    # Everything before the change is exactly what Plex was told before.
    assert [p for p in after if p[0] < starts] == [p for p in before if p[0] < starts]
    assert {t for s, t in after if s >= starts} & {f"Jetsons {n}" for n in range(3, 26)}


def test_nothing_changes_when_plex_has_nothing_new(tv):
    client, _fp, _station = tv
    check(client)
    assert client.get("/api/channels").json()[0]["pending"] is None
    client.get("/xmltv.xml", headers=PLEX)
    assert client.get("/api/channels").json()[0]["lastChange"]["reason"] == "created"


def test_an_unchanged_library_is_not_read_again(tv):
    client, fp, _station = tv
    check(client, force=True)
    fp.requests.clear()
    check(client, force=False)
    assert fp.requests == ["/library/sections"]  # just the quick look


def test_an_update_removing_most_programs_waits_for_you(tv):
    client, fp, station = tv
    for n in range(3, 13):
        fp.add_episode(f"2{n:02d}", "100", 1, n, f"Jetsons {n}", f"/tv/j{n}.mkv", 22 * MIN)
    assert client.post(f"/api/channels/{station['id']}/update").json()["changed"] is True
    for n in range(1, 13):
        fp.remove(f"2{n:02d}")
    check(client)
    pending = client.get("/api/channels").json()[0]["pending"]
    assert pending["held"] and pending["removed"] == 12
    client.get("/xmltv.xml", headers=PLEX)
    assert client.get("/api/channels").json()[0]["pending"]["held"]
    # Update now applies it anyway.
    updated = client.post(f"/api/channels/{station['id']}/update").json()
    assert updated["pending"] is None and updated["itemCount"] == 3
    # The earlier update hadn't started airing, so this one replaces it:
    # counted against what's on air, 2 Jetsons episodes go.
    assert updated["lastChange"]["removed"] == 2


@pytest.fixture
def readded(tmp_path):
    """A station of two shows, its sources named as the editor saves them,
    with Plex answering "not found" as it does."""
    fp = FakePlex()
    fp.add_show("100", "The Jetsons")
    for n in (1, 2):
        fp.add_episode(f"2{n:02d}", "100", 1, n, f"Jetsons {n}", f"/tv/j{n}.mkv", 22 * MIN)
    fp.add_show("300", "The Flintstones")
    for n in range(1, 12):
        fp.add_episode(f"3{n:02d}", "300", 1, n, f"Flintstones {n}", f"/tv/f{n}.mkv", 22 * MIN)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=like_plex(fp)),
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/channels",
            json={
                "number": 2,
                "orderMode": "rotate",
                "sources": [
                    {"type": "show", "ratingKey": "100", "title": "The Jetsons"},
                    {"type": "show", "ratingKey": "300", "title": "The Flintstones"},
                ],
            },
        )
        assert created.status_code == 201, created.text
        yield client, fp, created.json()


def test_a_show_plex_added_again_is_followed_by_its_title(readded):
    """Plex adding a show again gives its episodes new keys: they're the
    same programs, so nothing is added or removed (and nothing is held,
    though every Flintstones key changed), and the station plays them
    under their new keys."""
    client, fp, station = readded
    moved = add_again(fp, "300", "310")
    check(client)
    card = client.get("/api/channels").json()[0]
    assert card["pending"] is not None
    assert (card["pending"]["added"], card["pending"]["removed"]) == (0, 0)
    assert not card["pending"]["held"]

    client.get("/xmltv.xml", headers=PLEX)
    assert client.get("/api/channels").json()[0]["pending"] is None
    keys = {i.rating_key for i in client.app.state.ctx.db.latest_items(station["id"])}
    assert keys == {"201", "202", *moved.values()}

    # The new key is remembered: asked for straight away from then on.
    fp.requests.clear()
    check(client)
    assert "/library/metadata/310/allLeaves" in fp.requests
    assert "/library/metadata/300/allLeaves" not in fp.requests
    assert client.get("/api/channels").json()[0]["pending"] is None


def test_a_station_whose_show_plex_added_again_can_still_be_edited(readded):
    client, fp, station = readded
    add_again(fp, "300", "310")
    body = {"number": 2, "orderMode": "shuffle", "sources": station["sources"]}
    edited = client.put(f"/api/channels/{station['id']}", json=body)
    assert edited.status_code == 200, edited.text
    assert edited.json()["orderMode"] == "shuffle"


def test_a_show_gone_from_plex_is_named_and_the_station_left_as_it_is(readded, caplog):
    caplog.set_level(logging.INFO)
    client, fp, station = readded
    add_again(fp, "300", "310")
    # Another of that title, with the station's files and one more: the two
    # differ, so which one is anyone's guess. (One without the station's
    # files would be told apart: see test_broken_again.)
    fp.add_show("320", "The Flintstones")
    for e in [e for e in list(fp.episodes.values()) if e.get("grandparentRatingKey") == "310"]:
        part = e["Media"][0]["Part"][0]
        fp.add_episode(str(int(e["ratingKey"]) + 5000), "320", e["parentIndex"], e["index"],
                       e["title"], part["file"], e["duration"])  # fmt: skip
    fp.add_episode("9999", "320", 9, 1, "Extra", "/tv/flintstones-extra.mkv", 22 * MIN)
    check(client)
    assert client.get("/api/channels").json()[0]["pending"] is None
    assert "no longer has the show 'The Flintstones' under its key, and has 2 shows" in caplog.text
    fp.shows.pop("310")
    fp.shows.pop("320")
    check(client)
    assert client.get("/api/channels").json()[0]["pending"] is None
    assert "and has no other show with that title" in caplog.text
    assert len(client.app.state.ctx.db.latest_items(station["id"])) == 13


def test_if_plex_stops_downloading_the_guide_updates_start_after_it_runs_out(tv):
    client, fp, _station = tv
    ctx = client.app.state.ctx
    client.get("/guide.xml")  # someone has the guide for the next two days
    published = ctx.updater.published_until_ms
    fp.add_episode("203", "100", 1, 3, "Jetsons 3", "/tv/j3.mkv", 22 * MIN)
    check(client)
    client.portal.call(ctx.updater.apply_overdue)
    card = client.get("/api/channels").json()[0]
    assert card["pending"] is None
    assert card["lastChange"]["startsAt"] >= published


def test_updates_wait_for_plex_while_it_downloads_the_guide_daily(tv):
    client, fp, _station = tv
    ctx = client.app.state.ctx
    client.get("/xmltv.xml", headers=PLEX)
    fp.add_episode("203", "100", 1, 3, "Jetsons 3", "/tv/j3.mkv", 22 * MIN)
    check(client)
    client.portal.call(ctx.updater.apply_overdue)
    assert client.get("/api/channels").json()[0]["pending"] is not None


def test_stationplay_asks_plex_to_reload_its_guide(tv):
    client, fp, _station = tv
    ctx = client.app.state.ctx
    fp.dvr_device = ctx.device_id  # Live TV set up in Plex after the station was made
    ctx.updater._dvr_checked_ms -= updates.DVR_MISSING_RECHECK_MS
    fp.add_episode("203", "100", 1, 3, "Jetsons 3", "/tv/j3.mkv", 22 * MIN)
    check(client)
    assert fp.posts == ["/livetv/dvrs/16/reloadGuide"]
    # The download that follows counts as Plex's, whatever it calls itself.
    client.get("/xmltv.xml", headers={"user-agent": "Lavf/61"})
    assert client.get("/api/channels").json()[0]["pending"] is None
    assert client.get("/api/status").json()["guide"]["canRefreshPlexGuide"] is True


def test_stationplay_finds_its_tuner_as_plex_lists_it(tv, monkeypatch, caplog):
    """Plex lists a tuner by the DeviceID it gave, in its uuid. What's
    found (or not) is logged once, not at every look."""
    caplog.set_level(logging.INFO)
    client, _fp, _station = tv
    ctx = client.app.state.ctx
    hdhomerun = "device://tv.plex.grabbers.hdhomerun/"
    other = {
        "key": "3",
        "Device": [
            {"key": "4", "uuid": hdhomerun + "1053C0CA", "uri": "http://nas:3310", "status": "dead"}
        ],
    }
    ours = {
        "key": "16",
        "Device": [{"key": "17", "uuid": hdhomerun + ctx.device_id.upper(), "status": "alive"}],
    }
    listed = [other]

    async def dvrs():
        return listed

    monkeypatch.setattr(ctx.plex, "dvrs", dvrs)

    def find():
        ctx.updater._dvr_checked_ms = 0  # look again now
        return client.portal.call(ctx.updater.find_dvr)

    assert find() is None
    assert f"doesn't list StationPlay's tuner ({ctx.device_id})" in caplog.text
    assert f"Plex lists {hdhomerun}1053C0CA at http://nas:3310 (dead)" in caplog.text
    listed.append(ours)
    assert find() == "16" and find() == "16"
    assert caplog.text.count("Found StationPlay's tuner") == 1
    ours["Device"][0]["status"] = "dead"
    assert find() == "16"
    assert "has StationPlay's tuner but can't reach it" in caplog.text
    assert client.get("/api/status").json()["guide"]["canRefreshPlexGuide"] is True

    client.get("/xmltv.xml", headers=PLEX)
    client.get("/xmltv.xml", headers=PLEX)
    assert "Plex downloaded the guide" in caplog.text


def test_edits_carry_on_and_a_new_order_starts_afresh(tv):
    client, fp, station = tv
    ctx = client.app.state.ctx
    fp.add_show("400", "Top Cat")
    fp.add_episode("401", "400", 1, 1, "Top Cat 1", "/tv/t1.mkv", 22 * MIN)
    body = {"number": 2, "orderMode": "rotate", "sources": station["sources"]}
    added = {**body, "sources": [*station["sources"], {"type": "show", "ratingKey": "400"}]}
    edited = client.put(f"/api/channels/{station['id']}", json=added).json()
    assert edited["lastChange"]["reason"] == "edit" and edited["lastChange"]["added"] == 1
    assert edited["lastChange"]["startsAt"] >= int(time.time() * 1000) + updates.MARGIN_MS - 5000
    assert len(ctx.db.eras(station["id"])) == 2
    shuffled = client.put(f"/api/channels/{station['id']}", json={**added, "orderMode": "shuffle"})
    assert shuffled.json()["orderMode"] == "shuffle"
    assert ctx.db.eras(station["id"])[-1].first_pass is None  # a fresh start
    # The first edit hadn't started airing yet, so the new order replaced it.
    assert len(ctx.db.eras(station["id"])) == 2
    renamed = client.put(
        f"/api/channels/{station['id']}", json={**added, "orderMode": "shuffle", "name": "Toons"}
    ).json()
    assert len(ctx.db.eras(station["id"])) == 2 and renamed["name"] == "Toons"
    reshuffled = client.post(f"/api/channels/{station['id']}/reshuffle").json()
    assert reshuffled["lastChange"]["reason"] == "reshuffle"


def test_a_shuffled_station_put_in_episode_order_plays_it_from_the_next_break(tv):
    client, _fp, station = tv
    body = {"number": 2, "orderMode": "shuffle", "sources": station["sources"]}
    assert client.put(f"/api/channels/{station['id']}", json=body).status_code == 200
    changed = client.put(f"/api/channels/{station['id']}", json={**body, "orderMode": "rotate"})
    starts = changed.json()["lastChange"]["startsAt"] // 1000 * 1000
    guide = programmes(client.get("/xmltv.xml", headers=PLEX).text)
    after = [title for start, title in guide if start >= starts]
    assert after[:5] == [
        "Flintstones 1", "Jetsons 1", "Flintstones 2", "Jetsons 2", "Flintstones 3",
    ]  # fmt: skip


def test_the_guide_never_has_gaps_across_changes(tv):
    client, fp, station = tv
    for n in range(3, 6):
        fp.add_episode(f"2{n:02d}", "100", 1, n, f"Jetsons {n}", f"/tv/j{n}.mkv", 7 * MIN)
        client.post(f"/api/channels/{station['id']}/update")
    guide = client.get(f"/api/channels/{station['id']}/guide?hours=48").json()
    for a, b in itertools.pairwise(guide):
        assert a["end"] == b["start"]


def test_old_eras_are_cleared_away(tv):
    client, _fp, station = tv
    ctx = client.app.state.ctx
    now = int(time.time() * 1000)
    items = ctx.db.latest_items(station["id"])
    for start in (now - 30 * 3600_000, now - 20 * 3600_000, now - 30 * MIN):
        ctx.db.add_era(
            station["id"], items, start_ms=start, epoch_ms=start, seed=str(start),
            order_mode="rotate", created_ms=start, reason="update",
        )  # fmt: skip
    ctx.updater.prune_all()
    starts = [e.start_ms for e in ctx.db.eras(station["id"])]
    # Kept: the era that was on 3 hours ago (for the guide's past) and later.
    assert starts[:2] == [now - 20 * 3600_000, now - 30 * MIN] and len(starts) == 3


# Filters ------------------------------------------------------------------


@pytest.fixture
def films(tmp_path):
    fp = FakePlex()
    fp.add_section("2", "Movies", "movie")
    fp.add_section("3", "Kids Movies", "movie")
    catalogue = [
        ("501", "Jaws", 1975, ["Thriller"], ["Steven Spielberg"], [], "2"),
        ("502", "E.T.", 1982, ["Family", "Sci-Fi"], ["Steven Spielberg"], [], "2"),
        ("502", "E.T.", 1982, ["Family", "Sci-Fi"], ["Steven Spielberg"], [], "3"),
        ("503", "Die Hard", 1988, ["Action"], ["John McTiernan"], ["Christmas"], "2"),
        ("504", "Elf", 2003, ["Comedy"], ["Jon Favreau"], ["Christmas"], "3"),
        ("505", "Home Alone", 1990, ["Comedy", "Family"], ["Chris Columbus"], ["Christmas"], "2"),
        ("506", "Speed", 1994, ["Action"], ["Jan de Bont"], [], "2"),
    ]
    for n, (key, title, year, genres, directors, labels, section) in enumerate(catalogue):
        # E.T. is in both libraries: the same file under two entries.
        fp.add_movie(
            str(int(key) + 100 * n), title, f"/movies/{key}.mkv", 110 * MIN, year=year,
            section=section, genres=genres, directors=directors, labels=labels,
        )  # fmt: skip
    fp.add_show("600", "I Love Lucy", year=1951, genres=["Comedy"])
    fp.add_show("700", "The Twilight Zone", year=1959, genres=["Sci-Fi"])
    fp.add_show("800", "Seinfeld", year=1989, genres=["Comedy"])
    for show, n in (("600", 1), ("600", 2), ("700", 1), ("800", 1)):
        fp.add_episode(f"{show}{n}", show, 1, n, f"{show} ep {n}", f"/tv/{show}-{n}.mkv", 25 * MIN)
    with make_client(tmp_path, fp) as client:
        yield client, fp


def movie_filter(**rules) -> dict:
    return {"type": "filter", "kind": "movie", "libraries": ["2", "3"], **rules}


def test_filter_choices_come_from_the_chosen_libraries(films):
    client, _fp = films
    both = client.get("/api/filter/fields?kind=movie&libraries=2,3").json()
    fields = {f["field"]: f for f in both["fields"]}
    assert fields["genre"]["choices"] == ["Action", "Comedy", "Family", "Sci-Fi", "Thriller"]
    assert fields["label"]["choices"] == ["Christmas"]
    assert fields["director"] == {"field": "director", "title": "Director", "search": True}
    assert both["decade"] == [1970, 1980, 1990, 2000]
    only_kids = client.get("/api/filter/fields?kind=movie&libraries=3").json()
    assert {f["field"]: f for f in only_kids["fields"]}["genre"]["choices"] == [
        "Comedy",
        "Family",
        "Sci-Fi",
    ]
    people = client.get("/api/filter/search?kind=movie&libraries=2,3&field=director&q=spiel")
    assert people.json() == ["Steven Spielberg"]
    tv = client.get("/api/filter/fields?kind=show&libraries=1").json()
    assert tv["decade"] == [1950, 1980]


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        ({"label": ["Christmas"]}, ["Die Hard", "Elf", "Home Alone"]),
        ({"genre": ["Action"]}, ["Die Hard", "Speed"]),
        ({"genre": ["Comedy", "Thriller"]}, ["Elf", "Home Alone", "Jaws"]),  # either
        ({"director": ["Steven Spielberg"]}, ["E.T.", "Jaws"]),  # E.T. once
        ({"genre": ["Family"], "label": ["Christmas"]}, ["Home Alone"]),  # both
        ({"decade": [1980]}, ["Die Hard", "E.T."]),
        ({"titleContains": "hard"}, ["Die Hard"]),
        ({"genre": ["Western"]}, []),
    ],
)
def test_movie_filters(films, rules, expected):
    client, _fp = films
    preview = client.post("/api/filter/preview", json=movie_filter(**rules)).json()
    assert [t.split(" (")[0] for t in preview["examples"]] == expected
    assert preview["matches"] == len(expected)


def test_a_station_made_from_a_filter(films):
    client, fp = films
    created = client.post(
        "/api/channels",
        json={"number": 25, "orderMode": "shuffle", "sources": [movie_filter(label=["Christmas"])]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["itemCount"] == 3
    # A new Christmas movie joins it at the next update.
    fp.add_movie(
        "900", "Scrooged", "/movies/900.mkv", 101 * MIN, year=1988, section="3",
        labels=["Christmas"],
    )  # fmt: skip
    check(client)
    assert client.get("/api/channels").json()[0]["pending"]["added"] == 1


def test_a_classic_tv_station_by_decade(films):
    client, _fp = films
    source = {"type": "filter", "kind": "show", "libraries": ["1"], "decade": [1950]}
    preview = client.post("/api/filter/preview", json=source).json()
    assert preview["examples"] == ["I Love Lucy (1951)", "The Twilight Zone (1959)"]
    assert preview["episodes"] == 3
    created = client.post("/api/channels", json={"number": 50, "sources": [source]}).json()
    assert created["itemCount"] == 3


def test_the_editor_lists_each_titles_genres_and_poster(films):
    client, fp = films
    items = {i["title"]: i for i in client.get("/api/libraries/2/items").json()}
    assert items["Home Alone"]["genres"] == ["Comedy", "Family"] and items["Home Alone"]["poster"]
    key = items["Jaws"]["ratingKey"]
    got = client.get(f"/poster/{key}")
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    assert got.content == f"poster {key}".encode()  # made small by Plex
    fp.requests.clear()
    assert client.get(f"/poster/{key}").content == got.content
    assert not fp.requests  # the second time, without asking Plex
    # Larger, for the list zoomed in: asked for (and kept) on its own.
    big = client.get(f"/poster/{key}?big=1")
    assert big.status_code == 200 and fp.requests == ["/photo/:/transcode"]
    assert client.get(f"/poster/{key}?big=1").content == big.content and len(fp.requests) == 1
    assert client.app.state.ctx.big_posters and client.app.state.ctx.posters
    fp.no_poster.add(items["Speed"]["ratingKey"])
    assert client.get(f"/poster/{items['Speed']['ratingKey']}").status_code == 404
    assert client.get("/poster/not-a-key").status_code == 404


def test_a_filter_can_leave_some_matches_out(films):
    """Every match is listed, to choose from; those left out stay out (and
    stay listed, to put back), and new matches still join."""
    client, fp = films
    christmas = movie_filter(label=["Christmas"])
    preview = client.post("/api/filter/preview", json=christmas).json()
    items = {i["title"]: i for i in preview["items"]}
    assert list(items) == ["Die Hard", "Elf", "Home Alone"]
    assert all(i["included"] for i in items.values()) and preview["leftOut"] == 0
    assert items["Home Alone"]["genres"] == ["Comedy", "Family"]
    left = {**christmas, "exclude": items["Die Hard"]["ratingKeys"]}
    preview = client.post("/api/filter/preview", json=left).json()
    assert (preview["matches"], preview["leftOut"]) == (2, 1)
    assert [i["included"] for i in preview["items"]] == [False, True, True]
    assert [t.split(" (")[0] for t in preview["examples"]] == ["Elf", "Home Alone"]
    created = client.post("/api/channels", json={"number": 26, "sources": [left]}).json()
    assert created["itemCount"] == 2
    fp.add_movie(
        "900", "Scrooged", "/movies/900.mkv", 101 * MIN, year=1988, section="3",
        labels=["Christmas"],
    )  # fmt: skip
    check(client)
    assert client.get("/api/channels").json()[0]["pending"]["added"] == 1
    # E.T. is in both libraries: leaving it out leaves it out of both.
    spielberg = movie_filter(director=["Steven Spielberg"])
    found = client.post("/api/filter/preview", json=spielberg).json()["items"]
    et = next(i for i in found if i["title"] == "E.T.")
    assert len(et["ratingKeys"]) == 2
    without = {**spielberg, "exclude": et["ratingKeys"]}
    assert (
        client.post("/api/channels", json={"number": 27, "sources": [without]}).json()["itemCount"]
        == 1
    )


def test_a_tv_filter_can_leave_shows_out(films):
    client, _fp = films
    source = {"type": "filter", "kind": "show", "libraries": ["1"], "decade": [1950]}
    zone = next(
        i for i in client.post("/api/filter/preview", json=source).json()["items"]
        if i["title"] == "The Twilight Zone"
    )  # fmt: skip
    assert zone["episodes"] == 1
    source["exclude"] = zone["ratingKeys"]
    preview = client.post("/api/filter/preview", json=source).json()
    assert (preview["matches"], preview["episodes"], preview["leftOut"]) == (1, 2, 1)
    created = client.post("/api/channels", json={"number": 51, "sources": [source]}).json()
    assert created["itemCount"] == 2


def test_a_station_from_two_overlapping_libraries_plays_each_film_once(films):
    client, _fp = films
    sources = [
        {"type": "section", "key": "2", "sectionType": "movie"},
        {"type": "section", "key": "3", "sectionType": "movie"},
    ]
    created = client.post("/api/channels", json={"number": 9, "sources": sources}).json()
    assert created["itemCount"] == 6  # 7 entries, E.T. twice


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "filter", "kind": "music", "libraries": ["2"]},
        {"type": "filter", "kind": "movie", "libraries": []},
        {"type": "filter", "kind": "movie", "libraries": ["2"], "genre": "Action"},
        {"type": "filter", "kind": "movie", "libraries": ["2"], "decade": ["1980s"]},
        {"type": "filter", "kind": "movie", "libraries": ["2"], "exclude": "501"},
        {"type": "filter", "kind": "movie", "libraries": ["2"], "exclude": ["Jaws"]},
        {"type": "podcast"},
    ],
)
def test_bad_filters_are_refused(films, bad):
    client, _fp = films
    resp = client.post("/api/channels", json={"number": 30, "sources": [bad]})
    assert resp.status_code == 400


# Every filter Plex offers (1.6) -------------------------------------------------


@pytest.fixture
def plex_library(tmp_path):
    now = int(time.time())
    fp = FakePlex()
    fp.add_section("2", "Movies", "movie")
    films = [
        # key, title, year, rating, studio, contentRating, audience rating, added days ago
        ("501", "Jaws", 1975, "PG", "Universal", 8.0, 400),
        ("502", "E.T.", 1982, "PG", "Universal", 7.9, 3),
        ("503", "Die Hard", 1988, "R", "Fox", 8.2, 20),
        ("504", "Elf", 2003, "PG", "New Line", 6.9, 2),
        ("505", "Cats", 2019, "PG", "Universal", None, 1),
    ]
    for key, title, year, rating, studio, audience, days in films:
        fp.add_movie(
            key, title, f"/m/{key}.mkv", 100 * MIN, year=year, section="2",
            contentRating=[rating], studio=[studio], audience_rating=audience,
            added_at=now - days * 86400,
        )  # fmt: skip
    fp.add_show("600", "Cheers", year=1982, network=["NBC"], contentRating=["TV-PG"])
    fp.add_show("700", "M*A*S*H", year=1972, network=["CBS"], contentRating=["TV-PG"])
    for show, n, days in (("600", 1, 500), ("600", 2, 5), ("700", 1, 2), ("700", 2, 900)):
        fp.add_episode(
            f"{show}{n}", show, 1, n, f"{show}-{n}", f"/tv/{show}-{n}.mkv", 25 * MIN,
            added_at=now - days * 86400,
        )  # fmt: skip
    with make_client(tmp_path, fp) as client:
        yield client, fp


def titles(client, source) -> list[str]:
    preview = client.post("/api/filter/preview", json=source)
    assert preview.status_code == 200, preview.text
    return [t.split(" (")[0] for t in preview.json()["examples"]]


def test_every_filter_plex_offers_is_offered(plex_library):
    client, fp = plex_library
    movies = client.get("/api/filter/fields?kind=movie&libraries=2").json()
    offered = [f["field"] for f in movies["fields"]]
    # Filters with nothing to choose from here (no genres or countries) aren't
    # offered; people are searched for, so they always are.
    assert offered == ["director", "actor", "writer", "contentRating", "studio"]
    by_field = {f["field"]: f for f in movies["fields"]}
    assert by_field["contentRating"]["choices"] == ["PG", "R"]
    assert by_field["studio"]["choices"] == ["Fox", "New Line", "Universal"]
    assert by_field["writer"]["search"] is True
    assert not {"year", "decade", "unwatched"} & set(
        offered
    )  # handled separately, or not about programs
    tv = client.get("/api/filter/fields?kind=show&libraries=1").json()
    assert {f["field"]: f for f in tv["fields"]}["network"]["choices"] == ["CBS", "NBC"]
    # An older Plex that doesn't list its filters still gets the usual ones.
    fp.meta = False
    client.app.state.ctx.plex._choices.clear()
    old = client.get("/api/filter/fields?kind=movie&libraries=2").json()
    # (the usual genre, collection and label have nothing to choose from here)
    assert {f["field"] for f in old["fields"]} == {"director", "actor"}


def test_filters_on_content_rating_studio_and_network(plex_library):
    client, _fp = plex_library
    movie = {"type": "filter", "kind": "movie", "libraries": ["2"]}
    assert titles(client, {**movie, "tags": {"contentRating": ["R"]}}) == ["Die Hard"]
    assert titles(
        client, {**movie, "tags": {"studio": ["Universal"], "contentRating": ["PG"]}}
    ) == [
        "Cats",
        "E.T.",
        "Jaws",
    ]
    tv = {"type": "filter", "kind": "show", "libraries": ["1"], "tags": {"network": ["NBC"]}}
    assert titles(client, tv) == ["Cheers"]
    made = client.post("/api/channels", json={"number": 3, "sources": [tv]}).json()
    assert made["itemCount"] == 2


def test_minimum_audience_rating(plex_library):
    client, _fp = plex_library
    movie = {"type": "filter", "kind": "movie", "libraries": ["2"], "minRating": 7.9}
    # Cats has no audience rating in Plex, so it's left out.
    assert titles(client, movie) == ["Die Hard", "E.T.", "Jaws"]


def test_new_arrivals_movies_and_episodes(plex_library):
    client, _fp = plex_library
    movies = {"type": "filter", "kind": "movie", "libraries": ["2"], "addedWithinDays": 7}
    assert titles(client, movies) == ["Cats", "E.T.", "Elf"]
    # For TV it's episodes: new episodes of any show, not shows that are new.
    tv = {"type": "filter", "kind": "show", "libraries": ["1"], "addedWithinDays": 7}
    preview = client.post("/api/filter/preview", json=tv).json()
    assert (preview["matches"], preview["episodes"]) == (2, 2)
    assert preview["examples"] == ["Cheers", "M*A*S*H"]
    assert [i["episodes"] for i in preview["items"]] == [1, 1]  # their new episodes
    made = client.post("/api/channels", json={"number": 4, "sources": [tv]}).json()
    items = client.app.state.ctx.db.latest_items(made["id"])
    assert sorted(i.rating_key for i in items) == ["6002", "7001"]
    # Combined with another condition, both apply.
    nbc = {**tv, "tags": {"network": ["NBC"]}}
    assert client.post("/api/filter/preview", json=nbc).json()["episodes"] == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"tags": {"genre": "Action"}},
        {"tags": ["genre"]},
        {"tags": {"../x": ["a"]}},
        {"addedWithinDays": -1},
        {"addedWithinDays": "7"},
        {"minRating": 11},
    ],
)
def test_bad_new_filters_are_refused(plex_library, bad):
    client, _fp = plex_library
    source = {"type": "filter", "kind": "movie", "libraries": ["2"], **bad}
    assert client.post("/api/filter/preview", json=source).status_code == 400


def test_a_value_with_a_comma_in_it(tmp_path):
    """Plex takes several values as a comma-separated list, so one that has a
    comma in it is matched by StationPlay itself."""
    fp = FakePlex()
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("901", "Grim", "/m/1.mkv", 90 * MIN, section="2", contentRating=["R, Violent"])
    fp.add_movie("902", "Nice", "/m/2.mkv", 90 * MIN, section="2", contentRating=["PG"])
    fp.add_movie(
        "903", "Also grim", "/m/3.mkv", 90 * MIN, section="2", contentRating=["R, Violent"]
    )
    with make_client(tmp_path, fp) as client:
        source = {"type": "filter", "kind": "movie", "libraries": ["2"],
                  "tags": {"contentRating": ["R, Violent"]}}  # fmt: skip
        preview = client.post("/api/filter/preview", json=source).json()
        assert preview["matches"] == 2 and preview["examples"] == [
            "Also grim (2000)",
            "Grim (2000)",
        ]
        source["tags"] = {"contentRating": ["R, Violent", "PG"]}
        assert client.post("/api/filter/preview", json=source).json()["matches"] == 3


def test_a_new_station_id_card_length_reaches_the_station_like_an_edit(tmp_path):
    """Choosing a longer Station ID card changes how long each slot is: it
    takes over at a break a minute or more away, like any edit."""
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "One", "/tv/1.mkv", 22 * MIN)
    with make_client(tmp_path, fp) as client:
        body = {"number": 2, "orderMode": "rotate", "stationId": True, "idSeconds": 5,
                "sources": [{"type": "show", "ratingKey": "100"}]}  # fmt: skip
        made = client.post("/api/channels", json=body).json()
        assert made["loopMs"] == 22 * MIN + 5000
        edited = client.put(f"/api/channels/{made['id']}", json={**body, "idSeconds": 10})
        assert edited.status_code == 200 and edited.json()["changed"]
        items = client.app.state.ctx.db.latest_items(made["id"])
        assert items[0].breaks == (("@id", 10_000),)
        # Turning the card off takes it away; its length is kept for next time.
        off = client.put(f"/api/channels/{made['id']}", json={**body, "stationId": False})
        assert off.json()["idSeconds"] == 5 and off.json()["changed"]
        assert client.app.state.ctx.db.latest_items(made["id"])[0].breaks is None
