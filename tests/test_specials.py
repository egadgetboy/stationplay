"""Feature Presentations and time-of-day blocks: when they're due, what they
play, how they share a station's time with marathons, and how the station
carries on exactly where it left off after each."""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import marathons, specials
from app.config import Settings
from app.db import NEW_STATION, Channel, Item, SpecialRun
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

MIN = 60_000
HOUR = 60 * MIN
DAY = 24 * HOUR


def channel(**settings) -> Channel:
    values = {**NEW_STATION, **settings}
    return Channel(1, 5, "Movies", [], "", **values)  # type: ignore[arg-type]


def block(name="Cartoons", days="5", start="08:00", end="11:00", **kw) -> dict:
    return {"id": kw.pop("id", "b1"), "name": name, "days": days, "start": start, "end": end,
            "sources": kw.pop("sources", [{"type": "show", "ratingKey": "900"}]), **kw}  # fmt: skip


# Checking settings ---------------------------------------------------------------


def test_a_block_needs_a_name_days_and_a_sensible_length():
    assert specials.block_problem(block()) is None
    assert specials.block_problem(block(start="22:00", end="02:00")) is None  # past midnight
    assert "name" in specials.block_problem(block(name="  "))
    assert "days" in specials.block_problem(block(days="9"))
    assert "HH:MM" in specials.block_problem(block(end="25:00"))
    assert "30 minutes to 12 hours" in specials.block_problem(block(start="08:00", end="08:15"))
    assert "30 minutes to 12 hours" in specials.block_problem(block(start="08:00", end="21:00"))
    assert "30 minutes to 12 hours" in specials.block_problem(block(start="08:00", end="08:00"))


def test_blocks_the_feature_and_set_marathons_cant_fall_over_each_other():
    ok = {"blocks": [block(), block("Evening", "5", "18:00", "20:00", id="b2")]}
    assert specials.timing_problem(ok) is None
    clash = {"blocks": [block(), block("Morning", "4,5", "10:30", "12:00", id="b2")]}
    assert specials.timing_problem(clash) == (
        "The blocks “Cartoons” and “Morning” overlap on Saturdays"
    )
    # Sunday night into Monday morning.
    late = {"blocks": [block("Late", "6", "23:00", "02:00"), block("Early", "0", "01:00", "03:00")]}
    assert "overlap" in specials.timing_problem(late)
    feature = {
        "blocks": [block()],
        "feature_mode": "on",
        "feature_days": "1,5",
        "feature_time": "09:00",
    }
    assert specials.timing_problem(feature) == (
        "The Feature Presentation on Saturdays at 09:00 falls during the block “Cartoons”"
    )
    assert specials.timing_problem({**feature, "feature_time": "11:00"}) is None  # (as it ends)
    assert specials.timing_problem({**feature, "feature_mode": "off"}) is None
    marathon = {
        "blocks": [block()],
        "marathon_mode": "set",
        "marathon_days": "5",
        "marathon_time": "08:00",
    }
    assert "Marathons on Saturdays at 08:00" in specials.timing_problem(marathon)


# When they're due ----------------------------------------------------------------


def test_feature_and_blocks_are_due_on_their_days_at_their_times():
    ch = channel(
        feature_mode="on",
        feature_days="4",
        feature_time="20:00",
        blocks=[block(days="5,6", start="23:00", end="01:30")],
    )
    monday = datetime(2026, 3, 2)
    start = int(monday.timestamp() * 1000)
    found = specials.due(ch, start, start + 7 * DAY)
    assert [
        (d.kind, datetime.fromtimestamp(d.at_ms / 1000).strftime("%a %H:%M")) for d in found
    ] == [
        ("feature", "Fri 20:00"),
        ("block", "Sat 23:00"),
        ("block", "Sun 23:00"),
    ]
    sat = found[1]
    assert sat.end_ms - sat.at_ms == 150 * MIN and sat.block["name"] == "Cartoons"
    # At the same moment, the more important first.
    both = channel(
        marathon_mode="set", marathon_days="4", marathon_time="20:00",
        feature_mode="on", feature_days="4", feature_time="20:00",
    )  # fmt: skip
    assert [d.kind for d in specials.due(both, start, start + 7 * DAY)] == ["feature", "marathon"]
    assert specials.due(channel(), start, start + 7 * DAY) == []


def test_each_movie_waits_its_turn():
    ch = channel()
    movies = [Item(0, 0, 90 * MIN, f"m{n}", "movie", f"Movie {n}") for n in range(5)]
    history: list[SpecialRun] = []
    shown = []
    for n in range(10):
        movie = specials.choose_movie(ch, movies, n * DAY, history)
        assert movie is not None
        shown.append(movie.rating_key)
        history.append(SpecialRun(n * DAY, movie.rating_key))
    # Every movie once before any comes round again, in the same order.
    assert sorted(shown[:5]) == [m.rating_key for m in movies] and shown[5:] == shown[:5]
    # Worked out again, the same.
    assert specials.choose_movie(ch, movies, 3 * DAY, history[:3]).rating_key == shown[3]
    assert specials.choose_movie(ch, [], 0, []) is None


# On a station ----------------------------------------------------------------------


@pytest.fixture
def plex() -> FakePlex:
    fp = FakePlex()
    for s, title in enumerate(("Bonanza", "Gunsmoke", "Rawhide"), start=1):
        fp.add_show(str(s * 100), title)
        for n in range(1, 7):
            key = str(s * 100 + n)
            fp.add_episode(key, str(s * 100), 1, n, f"{title} {n}", f"/tv/{key}.mkv", 30 * MIN)
    # Cartoons, for a block.
    for s, title in ((900, "Toons"), (950, "Funnies")):
        fp.add_show(str(s), title)
        for n in range(1, 13):
            key = str(s + n)
            fp.add_episode(key, str(s), 1, n, f"{title} {n}", f"/tv/{key}.mkv", 11 * MIN)
    fp.add_section("2", "Movies", "movie")
    for n in range(1, 6):
        fp.add_movie(str(500 + n), f"Film {n}", f"/movies/{n}.mkv", (90 + n) * MIN, 1950 + n, "2")
    fp.add_collection("600", "Noir", "2", "501", "503")
    return fp


@pytest.fixture
def client(plex, tmp_path):
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=plex.transport()),
    )
    with TestClient(app) as c:
        yield c


SHOWS = [{"type": "show", "ratingKey": str(s * 100)} for s in (1, 2, 3)]
MOVIES = {"type": "section", "key": "2", "sectionType": "movie", "title": "Movies"}


def in_a_day(hours: float = 24) -> tuple[str, str]:
    """A day and time (as the settings have them) this long from now."""
    at = datetime.now() + timedelta(hours=hours)
    return str(at.weekday()), at.strftime("%H:%M")


def make(client, **settings) -> dict:
    body = {"number": 7, "orderMode": "rotate", "sources": SHOWS, **settings}
    made = client.post("/api/channels", json=body)
    assert made.status_code == 201, made.text
    return made.json()


def aired_in(station, era) -> list:
    """The slots of `era` (a special's) as they air."""
    return [
        s
        for s in station.between(era.start_ms, era.start_ms + 13 * HOUR)
        if station.era_of(s).era_id == era.id
    ]


def eras_of(client, channel_id: int, kind: str):
    return [
        e for e in client.app.state.ctx.db.eras(channel_id) if (e.special or {}).get("kind") == kind
    ]


def test_a_feature_presentation_then_the_station_carries_on(client):
    day, at = in_a_day()
    made = make(client, featureMode="on", featureDays=day, featureTime=at, featureSource=MOVIES)
    ctx = client.app.state.ctx
    (feature,) = eras_of(client, made["id"], "feature")[:1]
    (movie,) = feature.items
    # The card, then the movie.
    assert movie.kind == "movie" and movie.lead_ms == specials.FEATURE_CARD_MS
    assert movie.program_ms in {(90 + n) * MIN for n in range(1, 6)}
    assert movie.duration_ms == movie.lead_ms + movie.program_ms + sum(
        ms for _, ms in movie.breaks or ()
    )
    assert movie.program_end_ms == movie.lead_ms + movie.program_ms
    # At the break nearest its time (the station's programs are 30 minutes).
    (due,) = marathons.weekly(day, at, feature.start_ms - DAY, feature.start_ms + DAY)
    assert abs(feature.start_ms - due) <= 15 * MIN
    eras = ctx.db.eras(made["id"])
    after = eras[eras.index(feature) + 1]
    assert (
        after.reason == "after feature" and after.start_ms == feature.start_ms + movie.duration_ms
    )
    station = ctx.station(made["id"])
    for a, b in itertools.pairwise(
        station.between(feature.start_ms - 2 * HOUR, after.start_ms + 3 * HOUR)
    ):
        assert a.end_ms == b.start_ms
    # The station carries on with what was due when it began.
    before = [e for e in eras if e.start_ms is None or e.start_ms < feature.start_ms]
    from app.schedule import station_schedule

    due_then = station_schedule(before).locate(feature.start_ms)
    assert station.locate(after.start_ms).item.rating_key == due_then.item.rating_key
    # The guide, the card, and the cards announcing it.
    assert '<title lang="en">Film' in client.get("/xmltv.xml").text
    assert '<desc lang="en">Feature Presentation. Film' in client.get("/xmltv.xml").text
    card = client.get("/api/channels").json()[0]
    assert card["nextFeature"] == {"title": movie.title, "at": feature.start_ms}
    first = station.locate(feature.start_ms)
    assert specials.starting(station, first) == (
        "Feature Presentation",
        f"{movie.title} ({movie.year})",
    )
    assert specials.starting(station, station.locate(feature.start_ms - 1)) is None
    # A movie that can't play is replaced from the station's programs.
    assert len(station.items_for(first)) == 18


def test_each_day_a_different_movie_from_a_collection_or_the_stations_own(client):
    week = "0,1,2,3,4,5,6"
    _, at = in_a_day()
    noir = {
        "type": "collection",
        "ratingKey": "600",
        "title": "Noir",
        "library": "2",
        "kind": "movie",
    }
    made = make(client, featureMode="on", featureDays=week, featureTime=at, featureSource=noir)
    titles = [e.items[0].title for e in eras_of(client, made["id"], "feature")]
    assert len(titles) >= 7 and set(titles) == {"Film 1", "Film 3"}
    assert all(a != b for a, b in itertools.pairwise(titles))  # (each waits its turn)
    # The station's own movies: it has none, so that's refused.
    body = {"number": 7, "sources": SHOWS, "featureSource": {}}
    own = client.put(f"/api/channels/{made['id']}", json=body)
    assert own.status_code == 400 and "no movies of its own" in own.text
    # With movies of its own, they take their turns.
    body["sources"] = [*SHOWS, MOVIES]
    mixed = client.put(f"/api/channels/{made['id']}", json=body).json()
    assert mixed["nextFeature"] is not None
    coming = [
        e.items[0].title
        for e in eras_of(client, made["id"], "feature")
        if e.start_ms > mixed["lastChange"]["startsAt"]
    ]
    assert len(set(coming[:5])) == 5


def test_a_block_plays_its_own_shows_and_carries_on_from_where_it_got_to(client):
    _, at = in_a_day()
    end = (datetime.strptime(at, "%H:%M") + timedelta(hours=1)).strftime("%H:%M")
    toons = [{"type": "show", "ratingKey": "900"}, {"type": "show", "ratingKey": "950"}]
    every = "0,1,2,3,4,5,6"
    made = make(
        client,
        blocks=[
            {"name": "Saturday Cartoons", "days": every, "start": at, "end": end, "sources": toons}
        ],
    )
    ctx = client.app.state.ctx
    (saved,) = made["blocks"]
    assert len(saved["id"]) == 8 and saved["name"] == "Saturday Cartoons"
    assert sorted(ctx.db.program_set_names(made["id"])) == [f"block:{saved['id']}"]
    runs = eras_of(client, made["id"], "block")
    assert len(runs) >= 7
    station = ctx.station(made["id"])
    order = []
    for era in runs:
        # About an hour of 11-minute cartoons, from the break nearest its
        # start to the break nearest its end.
        mine = aired_in(station, era)
        assert all(s.item.show_key in ("900", "950") for s in mine)
        assert abs(mine[0].start_ms - era.special["due"]) <= 15 * MIN
        assert abs(mine[-1].end_ms - (era.special["due"] + HOUR)) <= 6 * MIN
        order += [s.item.rating_key for s in mine]
    # Day after day, it carries on in episode order: every cartoon once
    # before any comes round again, each show's in order.
    assert len(set(order[:24])) == 24
    for show in ("90", "95"):
        theirs = [int(k) for k in order[:24] if k.startswith(show)]
        assert theirs == sorted(theirs)
    # The guide names it.
    guide = client.get("/xmltv.xml").text
    assert '<desc lang="en">Saturday Cartoons. Toons' in guide
    card = client.get("/api/channels").json()[0]
    assert card["nextBlock"] == {"title": "Saturday Cartoons", "at": runs[0].start_ms}
    # Renamed: the same block (it carries on); a new one gets its own id.
    body = {
        "number": 7,
        "sources": SHOWS,
        "blocks": [
            {**saved, "name": "Cartoon Time!"},
            {"name": "Late", "days": "6", "start": "23:00", "end": "23:45", "sources": toons},
        ],
    }
    renamed = client.put(f"/api/channels/{made['id']}", json=body).json()
    ids = [b["id"] for b in renamed["blocks"]]
    assert ids[0] == saved["id"] and ids[1] != saved["id"] and len(ids[1]) == 8
    guide = client.get("/xmltv.xml").text
    assert "Cartoon Time! Toons" in guide and "Cartoon Time!." not in guide


@pytest.mark.parametrize("order", ["rotate", "shuffle"])
def test_a_blocks_programs_dont_repeat_from_day_to_day(client, order):
    _, at = in_a_day()
    end = (datetime.strptime(at, "%H:%M") + timedelta(minutes=45)).strftime("%H:%M")
    toons = [{"type": "show", "ratingKey": "900"}, {"type": "show", "ratingKey": "950"}]
    made = make(
        client,
        orderMode=order,
        blocks=[
            {"name": "Toons", "days": "0,1,2,3,4,5,6", "start": at, "end": end, "sources": toons}
        ],
    )
    station = client.app.state.ctx.station(made["id"])
    aired = []
    for era in eras_of(client, made["id"], "block")[:5]:
        aired += [s.item.rating_key for s in aired_in(station, era)]
    assert len(aired) >= 18
    assert len(set(aired[:24])) == len(aired[:24])  # (24 cartoons in all)


def test_a_block_comes_first_then_a_feature_then_a_marathon(client, monkeypatch):
    block_at = (datetime.now() + timedelta(hours=24)).replace(second=0, microsecond=0)
    feature_at = block_at - timedelta(minutes=30)  # its movie would run into the block
    ms = lambda t: int(t.timestamp() * 1000)  # noqa: E731
    # A marathon well before the block, one due as it starts, one during it.
    marathons_at = [
        ms(block_at - timedelta(hours=5)),
        ms(block_at),
        ms(block_at + timedelta(minutes=30)),
    ]
    monkeypatch.setattr(
        marathons, "due_times", lambda channel, a, b: [t for t in marathons_at if a <= t < b]
    )
    toons = [{"type": "show", "ratingKey": "900"}, {"type": "show", "ratingKey": "950"}]
    made = make(
        client,
        sources=[*SHOWS, *toons],  # (five shows, for marathons)
        marathonMode="random",
        featureMode="on",
        featureDays=str(feature_at.weekday()),
        featureTime=feature_at.strftime("%H:%M"),
        featureSource=MOVIES,
        blocks=[{
            "name": "Toons", "days": str(block_at.weekday()), "start": block_at.strftime("%H:%M"),
            "end": (block_at + timedelta(hours=2)).strftime("%H:%M"), "sources": toons,
        }],
    )  # fmt: skip
    planned = [e.special for e in client.app.state.ctx.db.eras(made["id"]) if e.special]
    assert [(p["kind"], p["due"]) for p in planned if p["due"] <= ms(block_at) + HOUR] == [
        ("marathon", marathons_at[0]),
        ("block", ms(block_at)),
    ]


def test_bad_specials_are_refused(client):
    made = make(client)
    url = f"/api/channels/{made['id']}"
    base = {"number": 7, "sources": SHOWS}
    tv = {"type": "section", "key": "1", "sectionType": "show", "title": "TV Shows"}
    toons = [{"type": "show", "ratingKey": "900"}]
    for bad in (
        {"featureMode": "sometimes"},
        {"featureDays": "7"},
        {"featureTime": "8pm"},
        {"featureSource": tv},
        {"featureSource": {"type": "show", "ratingKey": "100"}},
        {"blocks": [{"name": "", "days": "5", "start": "08:00", "end": "09:00", "sources": toons}]},
        {"blocks": [{"name": "A", "days": "5", "start": "08:00", "end": "08:10", "sources": toons}]},
        {"blocks": [{"name": "A", "days": "5", "start": "08:00", "end": "09:00", "sources": [{"type": "nope"}]}]},
        {"blocks": [
            {"name": "A", "days": "5", "start": "08:00", "end": "10:00", "sources": toons},
            {"name": "B", "days": "5", "start": "09:00", "end": "11:00", "sources": toons},
        ]},
        {"featureMode": "on", "featureDays": "5", "featureTime": "08:30",
         "blocks": [{"name": "A", "days": "5", "start": "08:00", "end": "10:00", "sources": toons}]},
    ):  # fmt: skip
        assert client.put(url, json={**base, **bad}).status_code == 400, bad
    five = [
        {"name": f"B{n}", "days": str(n), "start": "08:00", "end": "09:00", "sources": toons}
        for n in range(5)
    ]
    assert client.put(url, json={**base, "blocks": five}).status_code == 422
    assert client.get("/api/channels").json()[0]["blocks"] == []


def test_new_programs_in_a_block_join_with_an_update_from_plex(client, plex):
    day, at = in_a_day()
    end = (datetime.strptime(at, "%H:%M") + timedelta(hours=1)).strftime("%H:%M")
    toons = [{"type": "show", "ratingKey": "900"}]
    made = make(
        client, blocks=[{"name": "Toons", "days": day, "start": at, "end": end, "sources": toons}]
    )
    ctx = client.app.state.ctx
    name = f"block:{made['blocks'][0]['id']}"
    assert len(ctx.db.program_set(made["id"], name)) == 12
    plex.add_episode("913", "900", 1, 13, "Toons 13", "/tv/913.mkv", 11 * MIN)
    updated = client.post(f"/api/channels/{made['id']}/update").json()
    assert updated["changed"] is True
    assert len(ctx.db.program_set(made["id"], name)) == 13
    # Nothing new: nothing changes.
    assert client.post(f"/api/channels/{made['id']}/update").json()["changed"] is False


def test_a_block_losing_all_its_programs_is_held(client, plex):
    import asyncio

    day, at = in_a_day()
    end = (datetime.strptime(at, "%H:%M") + timedelta(hours=1)).strftime("%H:%M")
    made = make(
        client,
        blocks=[
            {
                "name": "Toons",
                "days": day,
                "start": at,
                "end": end,
                "sources": [{"type": "show", "ratingKey": "900"}],
            }
        ],
    )
    for n in range(1, 13):
        plex.remove(str(900 + n))
    update = asyncio.run(client.app.state.ctx.updater.check_station(made["id"]))
    assert update is not None and update.held and update.sets is not None
    assert update.as_dict()["specials"] is True and update.added == update.removed == 0


def test_the_block_state_is_kept_as_json(client):
    day, at = in_a_day()
    end = (datetime.strptime(at, "%H:%M") + timedelta(hours=1)).strftime("%H:%M")
    made = make(
        client,
        blocks=[
            {
                "name": "Toons",
                "days": day,
                "start": at,
                "end": end,
                "sources": [{"type": "show", "ratingKey": "900"}],
            }
        ],
    )
    runs = client.app.state.ctx.db.special_runs(made["id"], "block")
    assert runs and all(json.loads(r.value)["next"] for r in runs)


# Specials meeting, and changes made just before one -------------------------------


def test_a_special_right_after_another_starts_as_it_ends(client):
    """A Feature Presentation due as a block ends starts at the block's end:
    nothing of the station's comes between them."""
    block_at = (datetime.now() + timedelta(hours=24)).replace(second=0, microsecond=0)
    ends = block_at + timedelta(hours=1)
    toons = [{"type": "show", "ratingKey": "900"}, {"type": "show", "ratingKey": "950"}]
    made = make(
        client,
        featureMode="on",
        featureDays=str(ends.weekday()),
        featureTime=ends.strftime("%H:%M"),
        featureSource=MOVIES,
        blocks=[{
            "name": "Toons", "days": str(block_at.weekday()), "start": block_at.strftime("%H:%M"),
            "end": ends.strftime("%H:%M"), "sources": toons,
        }],
    )  # fmt: skip
    eras = client.app.state.ctx.db.eras(made["id"])
    block = next(e for e in eras if (e.special or {}).get("kind") == "block")
    feature = eras[eras.index(block) + 1]
    assert (feature.special or {}).get("kind") == "feature"
    # The station carrying on after the block now comes after the feature.
    carrying_on = eras[eras.index(feature) + 1]
    assert carrying_on.reason == "after block" and not carrying_on.special
    assert carrying_on.start_ms == feature.start_ms + feature.items[0].duration_ms
    station = client.app.state.ctx.station(made["id"])
    slots = list(station.between(block.start_ms, carrying_on.start_ms + HOUR))
    for a, b in itertools.pairwise(slots):
        assert a.end_ms == b.start_ms
    # The block's last cartoon, then the feature straight away.
    at_end = station.locate(feature.start_ms - 1)
    assert station.special(at_end)["kind"] == "block"
    # And after the feature, what was due when the block began.
    due_then = [e for e in eras if e.start_ms is not None and e.start_ms < block.start_ms]
    from app.schedule import station_schedule

    expected = station_schedule(due_then).locate(block.start_ms)
    assert station.locate(carrying_on.start_ms).item.rating_key == expected.item.rating_key


def test_a_change_just_before_a_feature_keeps_it(client, monkeypatch):
    from app import updates

    day, at = in_a_day()
    made = make(client, featureMode="on", featureDays=day, featureTime=at, featureSource=MOVIES)
    ctx = client.app.state.ctx
    feature = eras_of(client, made["id"], "feature")[0]
    due = feature.special["due"]
    # A minute before it's due, the station is changed.
    monkeypatch.setattr(updates, "now_ms", lambda: due - 2 * MIN)
    body = {"number": 7, "sources": SHOWS[:2], "featureSource": MOVIES}
    assert client.put(f"/api/channels/{made['id']}", json=body).status_code == 200
    again = [e for e in eras_of(client, made["id"], "feature") if e.special["due"] == due]
    assert len(again) == 1 and abs(again[0].start_ms - due) <= specials.LATE_MS
    eras = ctx.db.eras(made["id"])
    edit = next(e for e in eras if e.reason == "edit")
    # The change follows it: it isn't lost or pushed back.
    assert edit.start_ms >= again[0].start_ms + again[0].items[0].duration_ms


def test_a_broken_block_program_is_replaced_from_the_block_first(client):
    from app.broadcaster import Broadcaster

    day, at = in_a_day()
    end = (datetime.strptime(at, "%H:%M") + timedelta(hours=1)).strftime("%H:%M")
    toons = [{"type": "show", "ratingKey": "900"}]
    made = make(
        client, blocks=[{"name": "T", "days": day, "start": at, "end": end, "sources": toons}]
    )
    ctx = client.app.state.ctx
    station = ctx.station(made["id"])
    era = eras_of(client, made["id"], "block")[0]
    slot = station.locate(era.start_ms)
    pools = Broadcaster(ctx, made["id"])._stand_ins(ctx.db.get_channel(made["id"]), station, slot)
    assert {i.show_key for i in pools[0]} == {"900"} and len(pools[1]) == 18


def test_a_specials_two_eras_are_saved_together(client, monkeypatch):
    from app import db as dbmod

    day, at = in_a_day()
    calls = []
    real = dbmod.Database._insert_era

    def failing(self, channel_id, new):
        calls.append(new.reason)
        if new.reason.startswith("after "):
            raise RuntimeError("disk full")
        return real(self, channel_id, new)

    monkeypatch.setattr(dbmod.Database, "_insert_era", failing)
    made = make(client, featureMode="on", featureDays=day, featureTime=at, featureSource=MOVIES)
    # Neither was saved (the trouble is logged); the station plays on as it was.
    eras = client.app.state.ctx.db.eras(made["id"])
    assert "feature" in calls and not [e for e in eras if e.special]
    assert not eras[-1].special


def test_a_feature_before_a_block_picks_a_movie_that_finishes_in_time(client, plex):
    plex.add_movie("510", "Short Film", "/movies/short.mkv", 40 * MIN, 1960, "2")
    block_at = (datetime.now() + timedelta(hours=24)).replace(second=0, microsecond=0)
    feature_at = block_at - timedelta(hours=1)  # (the others run 91 to 95 minutes)
    toons = [{"type": "show", "ratingKey": "900"}]
    made = make(
        client,
        featureMode="on",
        featureDays=str(feature_at.weekday()),
        featureTime=feature_at.strftime("%H:%M"),
        featureSource=MOVIES,
        blocks=[{
            "name": "Toons", "days": str(block_at.weekday()), "start": block_at.strftime("%H:%M"),
            "end": (block_at + timedelta(hours=1)).strftime("%H:%M"), "sources": toons,
        }],
    )  # fmt: skip
    eras = client.app.state.ctx.db.eras(made["id"])
    feature = next(e for e in eras if (e.special or {}).get("kind") == "feature")
    block = next(e for e in eras if (e.special or {}).get("kind") == "block")
    assert feature.items[0].title == "Short Film"
    assert feature.start_ms + feature.items[0].duration_ms <= block.start_ms + specials.LATE_MS
