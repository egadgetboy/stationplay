"""Skipping intros and credits: the rules for Plex's markers, how a program
maps onto its file, remembering markers, and the station setting."""

from __future__ import annotations

import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app import broadcaster as bc
from app import markers as mk
from app.config import Settings
from app.db import Database, Item
from app.library import Library
from app.main import create_app
from app.markers import Marker, MarkerFinder, parse_markers, pieces, segments_for, trimmed
from app.plex import PlexClient, PlexError
from app.updates import compare

from .fakeplex import FakePlex

S = 1000
MIN = 60 * S
EP = 22 * MIN  # a sitcom episode


def intro(start, end):
    return Marker("intro", start, end)


def credits(start, end, final=False):
    return Marker("credits", start, end, final)


def item(key="1", duration=EP, **kw) -> Item:
    return Item(0, 0, duration, key, "episode", f"Ep {key}", **kw)


# Reading Plex's markers ---------------------------------------------------------


def test_markers_are_read_however_plex_writes_final():
    raw = [
        {"id": 1, "type": "intro", "startTimeOffset": 990, "endTimeOffset": 28316},
        {"id": 2, "type": "credits", "startTimeOffset": 1_250_000, "endTimeOffset": 1_300_000},
        {"type": "credits", "startTimeOffset": 1, "endTimeOffset": 2, "final": True},
        {"type": "credits", "startTimeOffset": 1, "endTimeOffset": 2, "final": "1"},
        {"type": "credits", "startTimeOffset": 1, "endTimeOffset": 2, "final": 1},
        {"type": "credits", "startTimeOffset": 1, "endTimeOffset": 2, "final": "0"},
        {"type": "credits", "startTimeOffset": 1, "endTimeOffset": 2, "final": False},
        {"type": "commercial", "startTimeOffset": 5, "endTimeOffset": 9},
        {"type": "bookmark", "startTimeOffset": 5, "endTimeOffset": 9},
        {"type": "intro", "startTimeOffset": "bad", "endTimeOffset": 9},
        {"type": "intro", "endTimeOffset": 9},
    ]
    got = parse_markers(raw)
    assert got[:2] == [intro(990, 28316), credits(1_250_000, 1_300_000)]
    assert [m.final for m in got[2:]] == [True, True, True, False, False]
    assert parse_markers(None) == [] and parse_markers([]) == []


# Which parts of a program air ---------------------------------------------------


def test_a_cold_open_plays_then_the_intro_and_final_credits_are_skipped():
    got = segments_for(EP, [intro(90 * S, 150 * S), credits(21 * MIN, EP, final=True)])
    assert got == ((0, 90 * S), (150 * S, 21 * MIN))


def test_an_intro_at_the_very_start_leaves_no_flash_of_what_came_before():
    got = segments_for(EP, [intro(990, 28_316), credits(21 * MIN, EP, final=True)])
    assert got == ((28_316, 21 * MIN),)


def test_final_credits_end_the_program_even_if_plex_stops_them_early():
    # Plex's "Skip Credits" on the final credits goes to the next program.
    got = segments_for(EP, [credits(21 * MIN, 21 * MIN + 40 * S, final=True)])
    assert got == ((0, 21 * MIN),)


def test_a_scene_after_the_credits_still_plays():
    movie = 120 * MIN
    got = segments_for(
        movie,
        [credits(110 * MIN, 114 * MIN), credits(115 * MIN + 30 * S, movie, final=True)],
    )
    assert got == ((0, 110 * MIN), (114 * MIN, 115 * MIN + 30 * S))


def test_a_few_seconds_after_the_credits_are_skipped_too():
    got = segments_for(EP, [credits(21 * MIN, EP - 3 * S)])  # not marked final
    assert got == ((0, 21 * MIN),)
    # Enough to be a scene: kept.
    got = segments_for(EP, [credits(20 * MIN, 21 * MIN)])
    assert got == ((0, 20 * MIN), (21 * MIN, EP))


def test_markers_that_dont_look_right_are_ignored():
    assert segments_for(EP, []) is None
    assert segments_for(EP, [Marker("commercial", 0, MIN)]) is None
    assert segments_for(EP, [intro(15 * MIN, 16 * MIN)]) is None  # "intro" in the second half
    assert segments_for(EP, [intro(MIN, 7 * MIN)]) is None  # six-minute "intro"
    assert segments_for(EP, [credits(5 * MIN, 6 * MIN)]) is None  # "credits" in the first half
    assert segments_for(EP, [intro(MIN, MIN + 1500)]) is None  # too short to be real
    assert segments_for(EP, [intro(2 * MIN, MIN)]) is None  # ends before it starts
    # A second "intro" near the end (as some tools add) is ignored; the real one isn't.
    got = segments_for(EP, [intro(990, 28_316), intro(1_405_379 - 70_000, 1_441_234 - 70_000)])
    assert got == ((28_316, EP),)


def test_skipping_never_takes_most_of_a_program():
    # Credits said to start just after half way, and final: over half skipped.
    assert segments_for(EP, [intro(0, 4 * MIN), credits(11 * MIN, EP, final=True)]) is None
    # A short program must keep at least a minute.
    assert segments_for(100 * S, [credits(50 * S, 100 * S, final=True)]) is None
    assert segments_for(150 * S, [credits(90 * S, 150 * S, final=True)]) == ((0, 90 * S),)


def test_overlapping_and_out_of_range_markers():
    got = segments_for(
        EP,
        [
            intro(60 * S, 120 * S),
            intro(100 * S, 150 * S),  # overlaps the first
            credits(21 * MIN, EP + 5 * MIN, final=True),  # runs past the end
        ],
    )
    assert got == ((0, 60 * S), (150 * S, 21 * MIN))


def test_trimmed_programs_are_as_long_as_what_airs():
    full = item(file_path="/tv/a.mkv")
    got = trimmed(full, [intro(90 * S, 150 * S), credits(21 * MIN, EP, final=True)])
    assert got.segments == ((0, 90 * S), (150 * S, 21 * MIN))
    assert got.duration_ms == 20 * MIN
    assert got.file_path == "/tv/a.mkv" and full.duration_ms == EP  # original untouched
    untouched = trimmed(full, [])
    assert untouched.segments is None and untouched.duration_ms == EP


# Where in the file each moment of a program is ----------------------------------

PARTS = ((0, 60 * S), (90 * S, 1260 * S))  # a 60s cold open, then from 1:30 to 21:00


def test_a_whole_program_plays_its_parts_back_to_back():
    assert pieces(PARTS, 0.0, 1230.0) == [(0.0, 60.0), (90.0, 1170.0)]


def test_tuning_in_part_way():
    assert pieces(PARTS, 30.0, 1200.0) == [(30.0, 30.0), (90.0, 1170.0)]
    assert pieces(PARTS, 60.0, 1170.0) == [(90.0, 1170.0)]  # exactly at the join
    assert pieces(PARTS, 100.0, 1130.0) == [(130.0, 1130.0)]


def test_a_sliver_of_a_part_isnt_started():
    # A fraction of a second of the cold open left: go straight to the rest.
    assert pieces(PARTS, 59.8, 1170.2) == [(90.0, 1170.0)]


def test_a_stand_in_plays_only_as_long_as_it_needs_to():
    assert pieces(PARTS, 30.0, 100.0) == [(30.0, 30.0), (90.0, 70.0)]
    assert pieces(PARTS, 30.0, 20.0) == [(30.0, 20.0)]
    assert pieces(PARTS, 2000.0, 10.0) == []


def test_programs_without_skips_play_straight_through():
    assert pieces(None, 12.5, 300.0) == [(12.5, 300.0)]
    assert pieces(None, 0.0, 0.0) == []


# Asking Plex, and remembering the answers ---------------------------------------


def library() -> FakePlex:
    fp = FakePlex()
    fp.add_show("100", "Show")
    for n in (1, 2, 3):
        fp.add_episode(f"20{n}", "100", 1, n, f"Ep {n}", f"/tv/{n}.mkv", EP)
    fp.set_markers("201", ("intro", 90 * S, 150 * S), ("credits", 21 * MIN, EP, True))
    fp.set_markers("202", ("credits", 21 * MIN, EP, True))
    return fp


async def finder(tmp_path, fp: FakePlex, transport=None) -> tuple[MarkerFinder, PlexClient]:
    plex = PlexClient("http://plex.test", "token", transport=transport or fp.transport())
    items = await plex.items_for_source({"type": "show", "ratingKey": "100"})
    assert len(items) == 3
    return MarkerFinder(Database(tmp_path / "db.sqlite"), Library(plex)), plex


class Clock:
    """Stands in for the time the marker finder sees."""

    def __init__(self, monkeypatch) -> None:
        self.ms = mk.now_ms()
        monkeypatch.setattr(mk, "now_ms", lambda: self.ms)

    def advance(self, ms: int) -> None:
        self.ms += ms


HOUR = 3600 * S
DAY = 24 * HOUR


async def test_markers_are_asked_for_once_and_remembered(tmp_path, monkeypatch):
    clock = Clock(monkeypatch)
    fp = library()
    found, plex = await finder(tmp_path, fp)
    items = await plex.items_for_source({"type": "show", "ratingKey": "100"})
    assert fp.marker_requests == 0  # whole-show lists never carry markers
    got = await found.trim(items)
    assert [i.duration_ms for i in got] == [20 * MIN, 21 * MIN, EP]
    assert got[2].segments is None
    assert fp.marker_requests == 3
    clock.advance(4 * HOUR)
    await found.trim(items)
    assert fp.marker_requests == 3  # remembered

    # Plex finds the third episode's intro later. A new answer is checked
    # again after six hours.
    fp.set_markers("203", ("intro", 0, 45 * S))
    clock.advance(2 * HOUR + 1000)
    got = await found.trim(items)
    assert fp.marker_requests == 6
    assert got[2].segments == ((45 * S, EP),)


async def test_answers_that_stay_the_same_are_asked_about_less_and_less(tmp_path, monkeypatch):
    clock = Clock(monkeypatch)
    fp = library()
    found, plex = await finder(tmp_path, fp)
    items = await plex.items_for_source({"type": "show", "ratingKey": "100"})
    for _hour in range(14 * 24):
        await found.trim(items)
        clock.advance(HOUR)
    # Asked every six hours that would be 56 times each over two weeks.
    assert fp.marker_requests <= 3 * 10, fp.marker_requests
    assert mk.trust_ms("1", True, 0) <= mk.FIRST_TTL_MS
    assert mk.trust_ms("1", True, 30 * DAY) <= mk.FOUND_TTL_MS
    assert mk.trust_ms("1", False, 30 * DAY) <= mk.NONE_TTL_MS
    assert mk.trust_ms("1", False, 30 * DAY) >= 0.85 * mk.NONE_TTL_MS
    # Spread out, so a library's answers don't all come due at once.
    assert len({mk.trust_ms(str(k), True, 0) for k in range(50)}) > 20


async def test_a_new_answer_after_a_file_swap_is_checked_again_soon(tmp_path, monkeypatch):
    """Right after a file is replaced Plex may still report the old file's
    markers; the answer isn't trusted for long until it has held."""
    clock = Clock(monkeypatch)
    fp = library()
    found, plex = await finder(tmp_path, fp)
    for _day in range(10):  # long enough to be trusted for a week
        await found.trim(await plex.items_for_source({"type": "show", "ratingKey": "100"}))
        clock.advance(DAY)
    fp.episodes["201"]["duration"] = EP + 30 * S  # Sonarr upgraded it
    stale = await found.trim(await plex.items_for_source({"type": "show", "ratingKey": "100"}))
    assert stale[0].segments == ((0, 90 * S), (150 * S, 21 * MIN))  # Plex's old answer
    fp.set_markers("201", ("intro", 60 * S, 100 * S))  # Plex catches up
    clock.advance(6 * HOUR + 1000)
    got = await found.trim(await plex.items_for_source({"type": "show", "ratingKey": "100"}))
    assert got[0].segments == ((0, 60 * S), (100 * S, EP + 30 * S))


async def test_a_new_file_means_asking_again(tmp_path):
    fp = library()
    found, plex = await finder(tmp_path, fp)
    await found.trim(await plex.items_for_source({"type": "show", "ratingKey": "100"}))
    fp.episodes["201"]["duration"] = EP + 30 * S  # Sonarr upgraded it: a different cut
    fp.set_markers("201", ("intro", 60 * S, 100 * S))
    got = await found.trim(await plex.items_for_source({"type": "show", "ratingKey": "100"}))
    assert fp.marker_requests == 4
    assert got[0].segments == ((0, 60 * S), (100 * S, EP + 30 * S))


async def test_a_program_gone_from_plex_just_has_no_markers(tmp_path):
    fp = library()
    found, plex = await finder(tmp_path, fp)
    items = await plex.items_for_source({"type": "show", "ratingKey": "100"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/library/metadata/202":
            return httpx.Response(404)
        return fp.handler(request)

    plex404 = PlexClient("http://plex.test", "token", transport=httpx.MockTransport(handler))
    got = await MarkerFinder(found.db, Library(plex404)).trim(items)
    assert got[1].segments is None and got[1].duration_ms == EP
    assert got[0].segments is not None


def flaky_plex(fp: FakePlex, failing: set[str], status: int = 503) -> PlexClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.rsplit("/", 1)[-1] in failing and "includeMarkers" in str(request.url):
            return httpx.Response(status)
        return fp.handler(request)

    return PlexClient("http://plex.test", "token", transport=httpx.MockTransport(handler))


async def test_a_program_plex_wont_answer_about_doesnt_hold_up_the_rest(
    tmp_path, monkeypatch, caplog
):
    clock = Clock(monkeypatch)
    fp = library()
    found, plex = await finder(tmp_path, fp)
    items = await plex.items_for_source({"type": "show", "ratingKey": "100"})
    await found.trim(items)
    clock.advance(8 * HOUR)
    fp.set_markers("203", ("intro", 0, 45 * S))
    got = await MarkerFinder(found.db, Library(flaky_plex(fp, {"201"}))).trim(items)
    # Episode 1 keeps what Plex last said; the others are up to date.
    assert got[0].segments == ((0, 90 * S), (150 * S, 21 * MIN))
    assert got[2].segments == ((45 * S, EP),)
    assert "didn't answer about intros and credits for 1 program (such as" in caplog.text
    # A program never answered about yet just plays in full for now.
    fp.add_episode("204", "100", 1, 4, "Ep 4", "/tv/4.mkv", EP)
    fp.set_markers("204", ("intro", 0, 45 * S))
    items = await plex.items_for_source({"type": "show", "ratingKey": "100"})
    got = await MarkerFinder(found.db, Library(flaky_plex(fp, {"204"}))).trim(items)
    assert got[3].segments is None and got[3].duration_ms == EP
    assert "204" not in found.db.cached_markers(["204"])  # asked again next time


async def test_plex_failing_for_many_programs_raises_but_keeps_what_it_learned(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(mk, "BATCH", 2)
    fp = FakePlex()
    fp.add_show("100", "Show")
    for n in range(1, 13):
        fp.add_episode(f"2{n:02d}", "100", 1, n, f"Ep {n}", f"/tv/{n}.mkv", EP)
    plex = PlexClient("http://plex.test", "token", transport=fp.transport())
    items = await plex.items_for_source({"type": "show", "ratingKey": "100"})
    db = Database(tmp_path / "db.sqlite")
    down = {f"2{n:02d}" for n in range(5, 13)}  # Plex stops answering part-way
    with pytest.raises(PlexError):
        await MarkerFinder(db, Library(flaky_plex(fp, down))).trim(items)
    assert set(db.cached_markers([i.rating_key for i in items])) == {"201", "202", "203", "204"}
    with pytest.raises(PlexError):  # a refused token is never shrugged off
        await MarkerFinder(db, Library(flaky_plex(fp, {"205"}, status=401))).trim(items)


async def test_old_answers_are_forgotten(tmp_path, monkeypatch):
    fp = library()
    found, plex = await finder(tmp_path, fp)
    await found.trim(await plex.items_for_source({"type": "show", "ratingKey": "100"}))
    real = mk.now_ms
    monkeypatch.setattr(mk, "now_ms", lambda: real() + mk.FORGET_AFTER_MS + 1000)
    found.forget_old()
    assert found.db.cached_markers(["201", "202", "203"]) == {}


# Saving and comparing -------------------------------------------------------------


def test_skipped_parts_are_saved_with_the_schedule(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    ch = db.create_channel(1, "S", [], order_mode="rotate", skip_intros=True)
    assert ch.skip_intros
    a = item("1", 20 * MIN, segments=((0, 90 * S), (150 * S, 21 * MIN)))
    b = item("2")
    db.add_era(
        ch.id, [a, replace(b, position=1, start_ms=20 * MIN)], start_ms=0, epoch_ms=0,
        seed="s", order_mode="rotate", created_ms=0, reason="created",
    )  # fmt: skip
    db.close()
    again = Database(tmp_path / "db.sqlite")
    saved = again.eras(ch.id)[0].items
    assert saved[0].segments == ((0, 90 * S), (150 * S, 21 * MIN))
    assert saved[1].segments is None
    # Saving other settings leaves the choice alone unless it's given.
    again.update_channel(ch.id, name="S2")
    assert again.get_channel(ch.id).skip_intros
    again.update_channel(ch.id, skip_intros=False)
    with pytest.raises(TypeError):
        again.update_channel(ch.id, skip_intro=True)  # a typo is an error, not ignored
    assert not again.get_channel(ch.id).skip_intros


def test_a_database_from_1_3_is_brought_up_to_date(tmp_path):
    """The 1.3 tables, as 1.3 made them: stations keep their schedule and
    start with skipping off."""
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE channels (id INTEGER PRIMARY KEY AUTOINCREMENT, number INTEGER NOT NULL
          UNIQUE, name TEXT NOT NULL, order_mode TEXT NOT NULL DEFAULT 'shuffle', sources TEXT
          NOT NULL DEFAULT '[]', epoch_ms INTEGER NOT NULL DEFAULT 0, total_ms INTEGER NOT NULL
          DEFAULT 0, built_at_ms INTEGER NOT NULL DEFAULT 0, aspect_mode TEXT NOT NULL DEFAULT
          'fit', logo TEXT NOT NULL DEFAULT '');
        CREATE TABLE eras (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER NOT NULL
          REFERENCES channels(id) ON DELETE CASCADE, start_ms INTEGER, epoch_ms INTEGER NOT
          NULL, seed TEXT NOT NULL, order_mode TEXT NOT NULL, chained INTEGER NOT NULL DEFAULT
          0, first_pass TEXT, tail TEXT, created_ms INTEGER NOT NULL, reason TEXT NOT NULL
          DEFAULT '', added INTEGER NOT NULL DEFAULT 0, removed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE era_items (era_id INTEGER NOT NULL REFERENCES eras(id) ON DELETE CASCADE,
          position INTEGER NOT NULL, start_ms INTEGER NOT NULL, duration_ms INTEGER NOT NULL,
          rating_key TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, show_title TEXT,
          show_key TEXT, season INTEGER, episode INTEGER, year INTEGER, summary TEXT, file_path
          TEXT, part_key TEXT, PRIMARY KEY (era_id, position));
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO channels (number, name, order_mode, logo) VALUES (4, 'Reruns', 'rotate', 'tv');
        INSERT INTO eras (channel_id, start_ms, epoch_ms, seed, order_mode, created_ms, reason)
          VALUES (1, 5, 5, 'x', 'rotate', 5, 'created');
        INSERT INTO era_items VALUES (1, 0, 0, 1320000, '201', 'episode', 'Pilot', 'Show', '100',
          1, 1, NULL, NULL, '/tv/1.mkv', '/library/parts/1');
        """
    )
    conn.commit()
    conn.close()
    db = Database(path)
    ch = db.get_channel(1)
    assert ch is not None and ch.number == 4 and ch.logo == "tv" and not ch.skip_intros
    [era] = db.eras(1)
    assert era.items[0].rating_key == "201" and era.items[0].segments is None
    assert era.items[0].duration_ms == 1320000
    assert db.cached_markers(["201"]) == {}
    db.close()
    Database(path).close()  # and opening it again changes nothing


def test_a_skip_that_appears_moves_or_goes_is_a_change():
    plain = item("1")
    skipping = trimmed(plain, [intro(90 * S, 150 * S), credits(21 * MIN, EP, final=True)])
    assert compare([plain], [plain]) == (0, 0, False)
    assert compare([plain], [skipping])[2]
    assert compare([skipping], [plain])[2]
    moved = replace(skipping, segments=((0, 80 * S), (140 * S, 21 * MIN)))
    assert moved.duration_ms == skipping.duration_ms
    assert compare([skipping], [moved])[2]
    nudged = replace(skipping, segments=((0, 90_500), (150_500, 21 * MIN)))
    assert not compare([skipping], [nudged])[2]  # within a second: the same


# The station setting ------------------------------------------------------------


@pytest.fixture
def app_client(tmp_path):
    fp = library()
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    with TestClient(app) as client:
        yield client, fp


SOURCES = [{"type": "show", "ratingKey": "100"}]


def guide_lengths(client, station_id) -> list[int]:
    return [g["end"] - g["start"] for g in client.get(f"/api/channels/{station_id}/guide").json()]


def test_a_station_that_skips_them_shows_true_lengths_in_the_guide(app_client):
    client, _fp = app_client
    made = client.post(
        "/api/channels",
        json={"number": 3, "orderMode": "rotate", "skipIntros": True, "sources": SOURCES},
    ).json()
    assert made["skipIntros"] is True and made["trimmedCount"] == 2
    assert made["loopMs"] == 20 * MIN + 21 * MIN + EP
    assert guide_lengths(client, made["id"])[:3] == [20 * MIN, 21 * MIN, EP]
    # Plex's guide says the same.
    xml = client.get("/guide.xml").text
    progs = ET.fromstring(xml).findall("programme")
    fmt = "%Y%m%d%H%M%S %z"
    lengths = [
        datetime.strptime(p.get("stop"), fmt).timestamp() - datetime.strptime(p.get("start"), fmt).timestamp()
        for p in progs[:4]
    ]  # fmt: skip
    assert 20 * 60 in lengths and 21 * 60 in lengths


def test_stations_that_dont_skip_never_ask_about_markers(app_client):
    client, fp = app_client
    made = client.post("/api/channels", json={"number": 3, "sources": SOURCES}).json()
    assert made["skipIntros"] is False and made["trimmedCount"] == 0
    client.portal.call(client.app.state.ctx.updater.check, True)
    assert fp.marker_requests == 0


def test_turning_skipping_on_and_off_takes_over_at_the_next_break(app_client):
    client, _fp = app_client
    body = {"number": 3, "orderMode": "rotate", "sources": SOURCES}
    made = client.post("/api/channels", json=body).json()
    assert made["loopMs"] == 3 * EP
    before = time.time() * 1000
    on = client.put(f"/api/channels/{made['id']}", json={**body, "skipIntros": True}).json()
    assert on["changed"] and on["skipIntros"] and on["trimmedCount"] == 2
    assert on["lastChange"]["reason"] == "edit"
    # The program on now finishes as it was; the change starts at a break.
    assert on["lastChange"]["startsAt"] >= made["now"]["end"]
    assert on["lastChange"]["startsAt"] >= before + 60 * S
    # Episode order carries on: the next episode is the one that was due.
    eras = client.app.state.ctx.db.eras(made["id"])
    station = client.app.state.ctx.station(made["id"])
    nxt = station.locate(on["lastChange"]["startsAt"])
    assert nxt.item.rating_key == "202" and nxt.item.duration_ms == 21 * MIN
    assert len(eras) == 2

    # Saving other settings (not mentioning it) keeps it on, with no new era.
    kept = client.put(f"/api/channels/{made['id']}", json={**body, "name": "Reruns"}).json()
    assert kept["skipIntros"] and "changed" not in kept
    assert len(client.app.state.ctx.db.eras(made["id"])) == 2

    off = client.put(f"/api/channels/{made['id']}", json={**body, "skipIntros": False}).json()
    assert off["changed"] and not off["skipIntros"] and off["trimmedCount"] == 0
    assert off["loopMs"] == 3 * EP


def test_markers_plex_finds_later_arrive_as_an_update(app_client, monkeypatch):
    client, fp = app_client
    ctx = client.app.state.ctx
    made = client.post(
        "/api/channels", json={"number": 3, "skipIntros": True, "sources": SOURCES}
    ).json()
    client.portal.call(ctx.updater.check, True)
    assert ctx.updater.pending.get(made["id"]) is None  # nothing new

    fp.set_markers("203", ("intro", 30 * S, 75 * S), ("credits", 21 * MIN, EP, True))
    real = mk.now_ms
    monkeypatch.setattr(mk, "now_ms", lambda: real() + mk.NONE_TTL_MS + 1000)
    client.portal.call(ctx.updater.check, True)
    update = ctx.updater.pending[made["id"]]
    assert (update.added, update.removed, update.held) == (0, 0, False)
    applied = client.post(f"/api/channels/{made['id']}/update").json()
    assert applied["changed"] and applied["trimmedCount"] == 3


def test_a_plex_hiccup_while_asking_about_markers_changes_nothing(tmp_path, monkeypatch):
    fp = FakePlex()
    fp.add_show("100", "Show")
    for n in range(1, 13):
        fp.add_episode(f"2{n:02d}", "100", 1, n, f"Ep {n}", f"/tv/{n}.mkv", EP)
        fp.set_markers(f"2{n:02d}", ("intro", 60 * S, 90 * S), ("credits", 21 * MIN, EP, True))
    fail = {"status": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if fail["status"] and "includeMarkers" in str(request.url):
            return httpx.Response(fail["status"])
        return fp.handler(request)

    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=httpx.MockTransport(handler)),
    )
    with TestClient(app) as client:
        ctx = client.app.state.ctx
        made = client.post(
            "/api/channels", json={"number": 3, "skipIntros": True, "sources": SOURCES}
        ).json()
        assert made["trimmedCount"] == 12
        clock = Clock(monkeypatch)
        clock.advance(8 * HOUR)  # due to be asked again
        fail["status"] = 500  # Plex answers everything else, but not this
        client.portal.call(ctx.updater.check, True)
        assert ctx.updater.pending.get(made["id"]) is None  # not "all intros are gone"
        # Changing the station now fails cleanly rather than half-working.
        resp = client.post(f"/api/channels/{made['id']}/update")
        assert resp.status_code == 502
        assert client.get("/api/channels").json()[0]["trimmedCount"] == 12

        # Plex answers, but has lost the markers (say, it's redoing them):
        # held for you to decide, not applied at the next guide download.
        fail["status"] = 0
        fp.markers.clear()
        client.portal.call(ctx.updater.check, True)
        update = ctx.updater.pending[made["id"]]
        assert update.held and update.lost_skips == 12 and update.removed == 0
        card = client.get("/api/channels").json()[0]
        assert card["pending"]["held"] and card["pending"]["lostSkips"] == 12
        client.get("/xmltv.xml", headers={"user-agent": "PlexMediaServer/1.41"})
        assert client.get("/api/channels").json()[0]["trimmedCount"] == 12


def test_a_waiting_update_never_undoes_an_edit_made_meanwhile(app_client):
    """Updates are applied one station after another when Plex downloads the
    guide. One whose station you edit meanwhile is dropped, not applied on
    top of your edit."""
    client, fp = app_client
    ctx = client.app.state.ctx
    made = client.post("/api/channels", json={"number": 3, "sources": SOURCES}).json()
    fp.add_episode("204", "100", 1, 4, "Ep 4", "/tv/4.mkv", EP)
    client.portal.call(ctx.updater.check, True)
    stale = ctx.updater.pending[made["id"]]
    edited = client.put(
        f"/api/channels/{made['id']}",
        json={"number": 3, "orderMode": "rotate", "skipIntros": True, "sources": SOURCES},
    ).json()
    assert edited["trimmedCount"] == 2
    # The guide download that was already applying updates reaches it now.
    applied = client.portal.call(
        lambda: ctx.updater.apply(
            made["id"], stale.items, not_before_ms=0, reason="update", update=stale
        )
    )
    assert applied is None
    assert client.get("/api/channels").json()[0]["trimmedCount"] == 2


# The engine plays the parts back to back -----------------------------------------


class FakeRun:
    """Stands in for ffmpeg: records what each run was asked to play."""

    def __init__(self, fail_on: int | None = None) -> None:
        self.calls: list[tuple[float, float, float]] = []
        self.fail_on = fail_on

    def command(self, settings, source, offset_s, duration_s, ts, burst, *a, **kw):
        self.calls.append((round(offset_s, 3), round(duration_s, 3), round(ts, 3)))
        return ["ffmpeg", str(duration_s)]

    async def run(self, args, stitcher, ts, first_frame_timeout, on_air=False, what=""):
        n = len(self.calls)
        duration = float(args[1])
        if n == self.fail_on:
            return bc.PlayResult(
                duration / 2, completed=False, reason="boom", next_ts=ts + duration / 2
            )
        return bc.PlayResult(duration, completed=True, next_ts=ts + duration + bc.JOIN_GAP_S)


async def play(
    monkeypatch,
    tmp_path,
    it: Item,
    offset_s: float,
    remaining_s: float,
    run: FakeRun,
    file_s: float = EP / 1000,
    gpu=None,
    lead_s: float = 0.0,
    **play_kw,
):
    """Plays a program with ffmpeg stood in for by `run`, the stream
    `lead_s` ahead of real time; `play_kw` go to _play_item."""
    from app import ffmpeg as ff
    from app.sources import ResolvedSource

    fp = FakePlex()
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    ctx = app.state.ctx
    ctx.gpu = gpu
    engine = bc.Broadcaster(ctx, 1)
    engine._session_start = int((time.time() + lead_s) * 1000)

    async def prepare(item, aspect_mode):
        probe = ff.ProbeResult(ok=True, duration_s=file_s, audio_index=0)
        return ResolvedSource("/tv/x.mkv", "/tv/x.mkv", 1), probe, None

    async def gap(gap_s, ts, stitcher, name, result):
        result.produced_s += max(0.0, gap_s)
        return result

    monkeypatch.setattr(engine, "_prepare", prepare)
    monkeypatch.setattr(engine, "_run_ffmpeg", run.run)
    monkeypatch.setattr(engine, "_fill_gap", gap)
    monkeypatch.setattr(ff, "program_command", run.command)
    return await engine._play_item(
        it, offset_s, remaining_s, 10.0, 0.0, engine._stitcher, "S", **play_kw
    )


async def test_the_engine_plays_each_part_in_turn_on_one_timeline(monkeypatch, tmp_path):
    it = trimmed(item(), [intro(90 * S, 150 * S), credits(21 * MIN, EP, final=True)])
    run = FakeRun()
    result = await play(monkeypatch, tmp_path, it, 0.0, 1200.0, run)
    assert result.completed and not result.failure
    assert run.calls == [(0.0, 90.0, 10.0), (150.0, 1110.0, round(10.0 + 90 + bc.JOIN_GAP_S, 3))]
    assert result.next_ts == pytest.approx(10.0 + 1200 + 2 * bc.JOIN_GAP_S)


async def test_a_failure_in_a_later_part_reports_how_far_it_got(monkeypatch, tmp_path):
    it = trimmed(item(), [intro(90 * S, 150 * S), credits(21 * MIN, EP, final=True)])
    run = FakeRun(fail_on=2)
    result = await play(monkeypatch, tmp_path, it, 0.0, 1200.0, run)
    assert not result.completed and result.failure is not None
    assert result.produced_s == pytest.approx(90 + 555)
    # Picking up from there (as the engine does) continues in the same part.
    assert pieces(it.segments, result.produced_s, 1200 - result.produced_s) == [(705.0, 555.0)]


async def test_joining_part_way_starts_in_the_right_part(monkeypatch, tmp_path):
    it = trimmed(item(), [intro(90 * S, 150 * S), credits(21 * MIN, EP, final=True)])
    run = FakeRun()
    await play(monkeypatch, tmp_path, it, 300.0, 900.0, run)
    assert run.calls == [(360.0, 900.0, 10.0)]


async def test_a_file_shorter_than_its_markers_is_covered_not_blamed(monkeypatch, tmp_path):
    it = trimmed(item(), [intro(90 * S, 150 * S), credits(21 * MIN, EP, final=True)])
    run = FakeRun()
    # The file on disk stops at one minute.
    result = await play(monkeypatch, tmp_path, it, 0.0, 1200.0, run, file_s=60.0)
    assert result.completed and result.failure is None
    assert run.calls == [(0.0, 60.0, 10.0)]


class FakeGpu:
    def __init__(self) -> None:
        from app.ffmpeg import CPU, Encoder

        self.gpu, self.cpu = Encoder("vaapi", "/dev/dri/renderD128"), CPU
        self.events: list[str] = []

    def encoder_for(self, cpu_only: bool):
        return self.cpu if cpu_only else self.gpu

    def gpu_failed(self, reason: str, stalled: bool = False) -> None:
        self.events.append("stalled" if stalled else "failed")

    def gpu_succeeded(self) -> None:
        self.events.append("succeeded")

    def cpu_rescued(self) -> None:
        self.events.append("rescued")


async def test_a_gpu_failure_in_a_later_part_carries_on_on_the_cpu(monkeypatch, tmp_path):
    it = trimmed(item(), [intro(90 * S, 150 * S), credits(21 * MIN, EP, final=True)])
    gpu = FakeGpu()
    result = await play(monkeypatch, tmp_path, it, 0.0, 1200.0, FakeRun(fail_on=2), gpu=gpu)
    # Not the file's fault: the same program carries on (on the CPU) from
    # where it got to, and the file isn't blamed.
    assert result.gpu_retry and result.failure is None
    assert result.produced_s == pytest.approx(90 + 555)
    assert gpu.events == ["failed"]
