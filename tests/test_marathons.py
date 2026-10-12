"""Marathons: when they're due, which show and episodes, and how the station
carries on exactly where it left off after one."""

from __future__ import annotations

import itertools
import time
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import marathons
from app import specials as specials_
from app.config import Settings
from app.db import NEW_STATION, Channel, Item, MarathonRecord
from app.main import create_app
from app.plex import PlexClient
from app.schedule import StationSchedule

from .fakeplex import FakePlex

MIN = 60_000
HOUR = 60 * MIN
DAY = 24 * HOUR


def channel(**settings) -> Channel:
    values = {**NEW_STATION, **settings}
    return Channel(1, 5, "Westerns", [], "", **values)  # type: ignore[arg-type]


def episodes(show: str, count: int, ms: int = 30 * MIN) -> list[Item]:
    return [
        Item(0, 0, ms, f"{show}{n}", "episode", f"{show} {n}", show.title(), show, 1, n)
        for n in range(1, count + 1)
    ]


# When they're due -------------------------------------------------------------


def test_at_random_times_so_many_a_week_on_different_days_the_same_each_time():
    ch = channel(marathon_mode="random", marathons_a_week=3)
    start = int(datetime(2026, 10, 5).timestamp() * 1000)  # a Monday
    week = marathons.due_times(ch, start, start + 7 * DAY)
    assert len(week) == 3 and week == sorted(week)
    assert len({datetime.fromtimestamp(t / 1000).date() for t in week}) == 3
    assert marathons.due_times(ch, start, start + 7 * DAY) == week  # worked out again
    # Any hour, and each week its own times.
    later = marathons.due_times(ch, start + 7 * DAY, start + 14 * DAY)
    assert len(later) == 3 and [t - 7 * DAY for t in later] != week
    # Part of a week: only those in it.
    assert marathons.due_times(ch, week[1], start + 7 * DAY) == week[1:]
    assert marathons.due_times(channel(marathon_mode="off"), start, start + 30 * DAY) == []


def test_at_set_times_on_the_days_chosen():
    ch = channel(marathon_mode="set", marathon_days="1,5", marathon_time="20:30")
    start = int(datetime(2026, 10, 5).timestamp() * 1000)  # Monday 5 October 2026
    due = [
        datetime.fromtimestamp(t / 1000) for t in marathons.due_times(ch, start, start + 14 * DAY)
    ]
    assert due == [
        datetime(2026, 10, 6, 20, 30),  # Tuesday
        datetime(2026, 10, 10, 20, 30),  # Saturday
        datetime(2026, 10, 13, 20, 30),
        datetime(2026, 10, 17, 20, 30),
    ]


def test_settings_are_checked():
    assert marathons.valid_days("0,5") and marathons.valid_days("6")
    for bad in ("", "7", "1,1", "a", "1,", "0, 5", "12"):
        assert not marathons.valid_days(bad), bad
    assert marathons.valid_time("20:00") and marathons.valid_time("00:05")
    for bad in ("", "8:00", "24:00", "20:60", "2000", "aa:bb", "20:00:00"):
        assert not marathons.valid_time(bad), bad


def test_at_the_program_break_nearest_its_time():
    items = episodes("a", 4, 30 * MIN)
    playlist = [replace(i, position=n, start_ms=n * 30 * MIN) for n, i in enumerate(items)]
    from app.schedule import EraSchedule

    station = StationSchedule(
        [EraSchedule(playlist, epoch_ms=0, seed="s", order_mode="rotate", start_ms=0)]
    )
    assert marathons.nearest_break(station, 40 * MIN, 0) == 30 * MIN  # 10 minutes before
    assert marathons.nearest_break(station, 50 * MIN, 0) == 60 * MIN  # 10 minutes after
    assert marathons.nearest_break(station, 40 * MIN, 31 * MIN) == 60 * MIN  # not before then


# Which show and episodes ------------------------------------------------------


def station_items(shows: int = 5, each: int = 6) -> list[Item]:
    return [i for s in "abcdefgh"[:shows] for i in episodes(s, each)]


def test_a_station_needs_five_shows_with_three_episodes():
    ch = channel(marathon_mode="random")
    assert marathons.choose(ch, station_items(4), 0, set(), []) is None
    assert marathons.choose(ch, station_items(5), 0, set(), []) is not None
    # Five shows, but only four with three episodes or more: none.
    assert marathons.choose(ch, station_items(4) + episodes("e", 2), 0, set(), []) is None
    # Shows with too few episodes (or too few that play) are left out.
    few = [i for i in station_items(5, 6) if i.show_key != "a"] + episodes("a", 2)
    broken = {f"{s}{n}" for s in "bcde" for n in range(1, 5)}
    assert marathons.choose(ch, few, 0, broken, []) is None
    movies = [Item(0, 0, 90 * MIN, f"m{n}", "movie", f"Movie {n}") for n in range(9)]
    assert marathons.choose(ch, movies, 0, set(), []) is None


def test_each_show_takes_its_turn_with_its_next_episodes():
    ch = channel(marathon_mode="random", marathon_episodes="next")
    items = station_items(5, 7)
    history: list[MarathonRecord] = []
    seen = []
    for n in range(10):
        m = marathons.choose(ch, items, n * DAY, set(), history)
        assert m is not None and len(m.items) == 3
        assert len({i.show_key for i in m.items}) == 1
        history.append(MarathonRecord(n * DAY, m.show_key, (1, m.items[-1].episode or 0)))
        seen.append((m.show_key, [i.episode for i in m.items]))
    # Every show before any again, in the same order the second time round.
    assert sorted(s for s, _ in seen[:5]) == list("abcde")
    assert [s for s, _ in seen[5:]] == [s for s, _ in seen[:5]]
    # Its next three, then from the start once too few are left (7 episodes).
    assert all(eps == [1, 2, 3] for _, eps in seen[:5])
    assert all(eps == [4, 5, 6] for _, eps in seen[5:])
    third = marathons.choose(
        ch,
        items,
        11 * DAY,
        set(),
        history + [MarathonRecord(10 * DAY + n, s, (1, 6)) for n, s in enumerate("abcde")],
    )
    assert third is not None and [i.episode for i in third.items] == [1, 2, 3]
    # The same when worked out again.
    again = marathons.choose(ch, items, 4 * DAY, set(), history[:4])
    assert again is not None and again.show_key == seen[4][0]


def test_a_random_stretch_is_three_in_a_row_and_skips_broken_files():
    ch = channel(marathon_mode="random", marathon_episodes="random")
    items = station_items(5, 12)
    broken = {"a5", "b5", "c5", "d5", "e5"}
    for n in range(20):
        m = marathons.choose(ch, items, n * DAY, broken, [])
        assert m is not None
        assert not {i.rating_key for i in m.items} & broken
        # Three in a row, of those that play.
        playing = [i for i in items if i.show_key == m.show_key and i.rating_key not in broken]
        keys = [i.rating_key for i in playing]
        first = keys.index(m.items[0].rating_key)
        assert [i.rating_key for i in m.items] == keys[first : first + 3]


def test_the_guide_says_its_a_marathon():
    special = {"kind": "marathon", "title": "Leave It to Beaver", "show": "s"}
    assert marathons.label(special, 0) == "Leave It to Beaver Marathon (1 of 3)"
    assert marathons.label(None, 0) == "" and marathons.label({"kind": "other"}, 0) == ""


# On a station ---------------------------------------------------------------------


SHOWS = ("Bonanza", "Gunsmoke", "Rawhide", "Wagon Train", "Maverick", "Lawman")


@pytest.fixture
def plex() -> FakePlex:
    fp = FakePlex()
    for s, title in enumerate(SHOWS, start=1):
        fp.add_show(str(s * 100), title)
        for n in range(1, 7):
            key = str(s * 100 + n)
            fp.add_episode(
                key, str(s * 100), 1, n, f"{title} {n}", f"/tv/{key}.mkv", (20 + s) * MIN
            )
    return fp


@pytest.fixture
def client(plex, tmp_path):
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=plex.transport()),
    )
    with TestClient(app) as c:
        yield c


def in_a_day() -> tuple[str, str]:
    """A day and time (as the settings have them) a day from now: within the guide."""
    at = datetime.now() + timedelta(days=1)
    return str(at.weekday()), at.strftime("%H:%M")


def make(client, order: str = "rotate", **settings) -> dict:
    day, at = in_a_day()
    body = {
        "number": 9,
        "orderMode": order,
        "sources": [{"type": "show", "ratingKey": str(s * 100)} for s in range(1, len(SHOWS) + 1)],
        "marathonMode": "set",
        "marathonDays": day,
        "marathonTime": at,
        **settings,
    }
    made = client.post("/api/channels", json=body)
    assert made.status_code == 201, made.text
    return made.json()


def specials(client, channel_id: int):
    return [e for e in client.app.state.ctx.db.eras(channel_id) if e.special]


@pytest.mark.parametrize("order", ["rotate", "shuffle"])
def test_a_marathon_then_the_station_carries_on_where_it_left_off(client, order):
    made = make(client, order)
    ctx = client.app.state.ctx
    eras = ctx.db.eras(made["id"])
    special = specials(client, made["id"])[0]  # (and the same day next week)
    assert special.special["kind"] == "marathon" and special.reason == "marathon"
    # Three episodes of one show, in order, at the break nearest the time.
    shows = {i.show_key for i in special.items}
    assert len(shows) == 1 and [i.episode for i in special.items] == [1, 2, 3]
    (due,) = marathons.due_times(
        ctx.db.get_channel(made["id"]), special.start_ms - DAY, special.start_ms + DAY
    )
    assert abs(special.start_ms - due) <= 30 * MIN  # (the longest program is under an hour)
    # Then the station carries on, from the program that was due when it began.
    after = eras[eras.index(special) + 1]
    assert after.reason == "after marathon" and not after.special
    assert after.start_ms == special.start_ms + sum(i.duration_ms for i in special.items)
    station = ctx.station(made["id"])
    before = [e for e in eras if e.start_ms is None or e.start_ms < special.start_ms]
    from app.schedule import station_schedule

    without = station_schedule(before)
    due_then = without.locate(special.start_ms)
    assert due_then.start_ms == special.start_ms  # (a program break)
    slots = list(station.between(special.start_ms - 2 * HOUR, after.start_ms + 6 * HOUR))
    # No gaps and no overlaps, all the way through.
    for a, b in itertools.pairwise(slots):
        assert a.end_ms == b.start_ms
    marathon = [s for s in slots if station.special(s)]
    assert [s.item.rating_key for s in marathon] == [i.rating_key for i in special.items]
    following = station.locate(after.start_ms)
    if order == "rotate":
        assert following.item.rating_key == due_then.item.rating_key
        # And on in the same order as without the marathon.
        ours = [
            s.item.rating_key for s in station.between(after.start_ms, after.start_ms + 5 * HOUR)
        ]
        theirs = [
            s.item.rating_key
            for s in without.between(special.start_ms, special.start_ms + 5 * HOUR)
        ]
        assert ours[:8] == theirs[:8]
    else:
        # The rest of the pass that was under way, then on.
        in_pass, _ = without.era_of(due_then).pass_order(due_then.cycle)
        rest = {i.rating_key for i in in_pass[due_then.index :]}
        aired = [
            s.item.rating_key for s in station.between(after.start_ms, after.start_ms + 40 * HOUR)
        ]
        assert set(aired[: len(rest)]) == rest
    # The guide says so, and the card says when the next one is.
    guide = client.get("/xmltv.xml").text
    title = special.special["title"]
    assert f"{title} Marathon (1 of 3)." in guide and f"{title} Marathon (3 of 3)." in guide
    card = client.get("/api/channels").json()[0]
    assert card["nextMarathon"] == {"title": title, "at": special.start_ms}
    assert card["lastChange"]["reason"] == "created" and card["itemCount"] == 36
    listed = client.get(f"/api/channels/{made['id']}/guide?hours=48").json()
    assert [g["special"] for g in listed if g["special"]] == [
        f"{title} Marathon ({n} of 3)" for n in (1, 2, 3)
    ]


def test_a_broken_marathon_episode_is_replaced_from_the_whole_station(client):
    made = make(client)
    station = client.app.state.ctx.station(made["id"])
    special = specials(client, made["id"])[0]
    first = station.locate(special.start_ms)
    assert len(station.items_for(first)) == 36  # not just the marathon's three
    assert len(station.items_for(station.locate(special.start_ms - 1))) == 36


def test_the_program_before_announces_it(client):
    made = make(client)
    station = client.app.state.ctx.station(made["id"])
    special = specials(client, made["id"])[0]  # (and the same day next week)
    first = station.locate(special.start_ms)
    before = station.locate(special.start_ms - 1)
    title = special.special["title"]
    assert specials_.starting(station, first) == (f"{title} Marathon", "3 episodes in a row")
    assert specials_.starting(station, before) is None
    assert specials_.starting(station, station.locate(first.end_ms)) is None


def test_a_station_with_too_few_shows_has_none(client):
    day, at = in_a_day()
    made = client.post(
        "/api/channels",
        json={
            "number": 3,
            "sources": [{"type": "show", "ratingKey": "100"}, {"type": "show", "ratingKey": "200"}],
            "marathonMode": "set",
            "marathonDays": day,
            "marathonTime": at,
        },
    ).json()
    assert not specials(client, made["id"]) and made["nextMarathon"] is None


def test_changes_wait_for_a_marathon_under_way_and_marathons_follow_them(client, monkeypatch):
    made = make(client)
    ctx = client.app.state.ctx
    special = specials(client, made["id"])[0]  # (and the same day next week)
    # Halfway through the marathon, the station is changed.
    halfway = special.start_ms + 40 * MIN
    from app import updates

    monkeypatch.setattr(updates, "now_ms", lambda: halfway - updates.MARGIN_MS)
    body = {**{k: v for k, v in made.items() if k in ("number",)}, "sources": made["sources"][:5]}
    changed = client.put(f"/api/channels/{made['id']}", json=body)
    assert changed.status_code == 200, changed.text
    eras = ctx.db.eras(made["id"])
    edit = next(e for e in eras if e.reason == "edit")
    # It takes over only after the marathon (and the program after it).
    end = special.start_ms + sum(i.duration_ms for i in special.items)
    assert edit.start_ms > end
    assert next(e.id for e in specials(client, made["id"])) == special.id


def test_turning_them_off_or_changing_them_plans_again(client):
    made = make(client)
    ctx = client.app.state.ctx
    first = specials(client, made["id"])[0]
    body = {"number": 9, "sources": made["sources"]}
    # Every day instead: one each day for the next week or so.
    daily = client.put(
        f"/api/channels/{made['id']}", json={**body, "marathonDays": "0,1,2,3,4,5,6"}
    ).json()
    planned = specials(client, made["id"])
    assert 7 <= len(planned) <= 9 and daily["nextMarathon"] is not None
    # Each show takes its turn.
    shows = [e.special["show"] for e in planned]
    assert len(set(shows[:6])) == 6
    # Off: none coming any more, and nothing left behind.
    off = client.put(f"/api/channels/{made['id']}", json={**body, "marathonMode": "off"}).json()
    assert not [
        e for e in specials(client, made["id"]) if e.start_ms > time.time() * 1000 + 2 * MIN
    ]
    assert off["nextMarathon"] is None and off["marathonMode"] == "off"
    assert ctx.db.marathons(made["id"]) == [] or all(
        r.due_ms <= time.time() * 1000 for r in ctx.db.marathons(made["id"])
    )
    # Bad settings are refused.
    for bad in (
        {"marathonMode": "sometimes"},
        {"marathonsAWeek": 5},
        {"marathonDays": "8"},
        {"marathonTime": "25:00"},
        {"marathonEpisodes": "best"},
    ):
        assert client.put(f"/api/channels/{made['id']}", json={**body, **bad}).status_code == 400, (
            bad
        )
    assert first.id not in [e.id for e in ctx.db.eras(made["id"])]
