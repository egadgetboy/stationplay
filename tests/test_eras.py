"""Eras: how a station takes in new and removed programs without changing
anything already in a guide, and carries on from where it was."""

from __future__ import annotations

import itertools
import random
import sqlite3

import pytest

from app.db import Database, Item
from app.schedule import (
    MAX_IN_A_ROW,
    EraSchedule,
    StationSchedule,
    build_playlist,
    fresh_window,
    plan_era,
    show_key,
    station_schedule,
)

from .helpers import LegacyChannel, Schedule

MIN = 60_000
DAY = 24 * 60 * MIN


def ep(key: str, show: str, number: int, minutes: float = 22) -> Item:
    return Item(
        0,
        0,
        int(minutes * MIN),
        key,
        "episode",
        f"{show} {number}",
        show_title=show,
        show_key=f"show-{show}",
        season=1,
        episode=number,
    )


def library(rng: random.Random, shows: int, prefix: str = "") -> list[Item]:
    return [
        ep(f"{prefix}{s}-{e:02d}", f"Show{s}", e + 1, rng.choice([11, 22, 30]))
        for s in range(shows)
        for e in range(rng.randint(2, 14))
    ]


def era(items, order, era_id, start=None, chained=False, plan=None, seed="s") -> EraSchedule:
    if plan is None:
        return EraSchedule(
            build_playlist(items, order),
            epoch_ms=start or 0,
            seed=seed,
            order_mode=order,
            start_ms=start,
            chained=chained,
            era_id=era_id,
        )
    return EraSchedule(
        plan.items,
        epoch_ms=plan.epoch_ms,
        seed=seed,
        order_mode=plan.order_mode,
        start_ms=plan.start_ms,
        chained=False,
        first_pass=plan.first_pass,
        tail=plan.tail,
        era_id=era_id,
    )


def keys(slots) -> list[str]:
    return [s.item.rating_key for s in slots]


def assert_contiguous(slots) -> None:
    for a, b in itertools.pairwise(slots):
        assert a.end_ms == b.start_ms, (a, b)


def test_an_update_never_changes_what_airs_before_it():
    rng = random.Random(1)
    for order in ("rotate", "shuffle"):
        old_items = library(rng, 6)
        old = era(old_items, order, 1, start=0)
        before = StationSchedule([old])
        at = before.next_break(3 * DAY + 5 * MIN)
        new_items = old_items[3:] + library(rng, 2, prefix="new")
        plan = plan_era(before, at, new_items, order)
        after = StationSchedule([old, era(None, order, 2, plan=plan)])
        assert keys(before.between(0, at)) == keys(after.between(0, at))
        assert after.locate(at).start_ms == at
        assert_contiguous(list(after.between(at - DAY, at + 3 * DAY)))


def test_new_episodes_join_episode_order_where_it_left_off():
    """2 Jetsons episodes, then Plex gets the other 23."""
    jetsons = [ep(f"j{n:02d}", "Jetsons", n) for n in range(1, 3)]
    flint = [ep(f"f{n:02d}", "Flintstones", n) for n in range(1, 4)]
    old = era(jetsons + flint, "rotate", 1, start=0)
    before = StationSchedule([old])
    at = before.next_break(5 * 60 * MIN)
    due = before.locate(at).item.rating_key
    more = [ep(f"j{n:02d}", "Jetsons", n) for n in range(1, 26)]
    plan = plan_era(before, at, more + flint, "rotate")
    assert plan.added == 23 and plan.removed == 0
    after = StationSchedule([old, era(None, "rotate", 2, plan=plan)])
    assert after.locate(at).item.rating_key == due  # carries on, no restart
    one_loop = list(after.between(at, at + plan.items[-1].start_ms + 60 * MIN))
    aired = set(keys(one_loop))
    assert {f"j{n:02d}" for n in range(3, 26)} <= aired  # all 23 new ones air
    jet = [s.item.episode for s in one_loop if s.item.show_title == "Jetsons"]
    wraps = sum(1 for a, b in itertools.pairwise(jet) if b < a)
    assert wraps <= 1  # still in episode order (wrapping round once at most)


def test_shuffle_finishes_its_pass_with_new_programs_then_starts_fresh():
    rng = random.Random(7)
    for trial in range(60):
        old_items = library(rng, rng.randint(3, 9))
        old = era(old_items, "shuffle", 1, start=0, seed=f"t{trial}")
        before = StationSchedule([old])
        at = before.next_break(rng.randint(1, 20) * 60 * MIN)
        slot = before.locate(at)
        in_progress, _ = old.pass_order(slot.cycle)
        aired_this_pass = {i.rating_key for i in in_progress[: slot.index]}
        gone = set(rng.sample([i.rating_key for i in old_items], 2))
        added = library(rng, 1, prefix=f"new{trial}-")
        new_items = [i for i in old_items if i.rating_key not in gone] + added
        plan = plan_era(before, at, new_items, "shuffle")
        after = StationSchedule([old, era(None, "shuffle", 2, plan=plan, seed=f"n{trial}")])

        first_pass = plan.first_pass or []
        still_due = {i.rating_key for i in in_progress[slot.index :]} - gone
        new_keys = {i.rating_key for i in added}
        upcoming = keys(itertools.islice(after.between(at, at + 100 * DAY), len(first_pass)))
        # The rest of the pass that was in progress, plus as many of the new
        # programs as can be spread out; the rest follow in the next pass.
        assert set(upcoming) == set(first_pass)
        assert still_due <= set(upcoming) <= still_due | new_keys
        assert not set(upcoming) & aired_this_pass
        full = keys(
            itertools.islice(after.between(at, at + 100 * DAY), len(first_pass) + len(new_items))
        )
        assert new_keys <= set(full)
        later = keys(itertools.islice(after.between(at, at + 100 * DAY), 3 * len(new_items)))
        assert not set(later) & gone


def test_shuffle_rules_hold_across_every_handover():
    rng = random.Random(11)
    for trial in range(80):
        items = library(rng, rng.randint(4, 10))
        eras = [era(items, "shuffle", 1, start=0, seed=f"a{trial}")]
        at = 0
        for n in range(2, 5):
            station = StationSchedule(eras)
            at = station.next_break(at + rng.randint(2, 30) * 60 * MIN)
            items = [i for i in items if rng.random() > 0.1] + library(rng, 1, f"{trial}.{n}-")
            plan = plan_era(station, at, items, "shuffle", fresh=rng.random() < 0.3)
            eras.append(era(None, "shuffle", n, plan=plan, seed=f"{trial}:{n}"))
        station = StationSchedule(eras)
        slots = list(station.between(0, at + 2 * DAY))
        assert_contiguous(slots)
        spreadable = {}
        for e in eras:
            counts: dict[str, int] = {}
            for i in e.items:
                counts[show_key(i)] = counts.get(show_key(i), 0) + 1
            biggest = max(counts.values())
            spreadable[e.era_id] = biggest <= MAX_IN_A_ROW * (len(e.items) - biggest)
        run = 1
        for a, b in itertools.pairwise(slots):
            run = run + 1 if show_key(a.item) == show_key(b.item) else 1
            if spreadable[b.era_id]:  # otherwise the card says "mostly one show"
                assert run <= MAX_IN_A_ROW, (trial, a, b)


def test_nothing_that_just_aired_opens_a_new_era_when_it_can_be_helped():
    rng = random.Random(3)
    for trial in range(40):
        items = library(rng, 8)
        old = era(items, "shuffle", 1, start=0, seed=f"r{trial}")
        before = StationSchedule([old])
        at = before.next_break(rng.randint(1, 40) * 60 * MIN)
        plan = plan_era(before, at, items, "shuffle", fresh=True)
        after = StationSchedule([old, era(None, "shuffle", 2, plan=plan, seed=f"f{trial}")])
        window = fresh_window(len(items))
        just_aired = set(keys(before.recent(at, window)))
        opening = keys(itertools.islice(after.between(at, at + DAY), window))
        assert not set(opening) & just_aired


def test_a_reshuffle_starts_a_new_order_but_keeps_the_past():
    rng = random.Random(5)
    items = library(rng, 6)
    old = era(items, "shuffle", 1, start=0)
    before = StationSchedule([old])
    at = before.next_break(2 * DAY)
    plan = plan_era(before, at, items, "shuffle", fresh=True)
    assert plan.first_pass is None and plan.added == plan.removed == 0
    after = StationSchedule([old, era(None, "shuffle", 2, plan=plan, seed="other")])
    assert keys(before.between(0, at)) == keys(after.between(0, at))
    assert keys(before.between(at, at + DAY)) != keys(after.between(at, at + DAY))


def test_a_program_airing_at_the_handover_is_never_cut_short():
    rng = random.Random(9)
    items = library(rng, 5)
    old = era(items, "rotate", 1, start=0)
    before = StationSchedule([old])
    t = 90 * MIN + 17_000
    slot = before.locate(t)
    assert before.next_break(t) == slot.end_ms
    assert before.next_break(slot.start_ms) == slot.start_ms


def test_stations_from_before_eras_keep_exactly_the_same_schedule(tmp_path):
    """Upgrading turns each station's playlist into its first era without
    changing a single airing."""
    path = tmp_path / "stationplay.db"
    rng = random.Random(2)
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE channels (id INTEGER PRIMARY KEY AUTOINCREMENT, number INTEGER NOT NULL
            UNIQUE, name TEXT NOT NULL, order_mode TEXT NOT NULL DEFAULT 'shuffle',
            sources TEXT NOT NULL DEFAULT '[]', epoch_ms INTEGER NOT NULL DEFAULT 0,
            total_ms INTEGER NOT NULL DEFAULT 0, built_at_ms INTEGER NOT NULL DEFAULT 0,
            aspect_mode TEXT NOT NULL DEFAULT 'fit');
        CREATE TABLE channel_items (channel_id INTEGER NOT NULL, position INTEGER NOT NULL,
            start_ms INTEGER NOT NULL, duration_ms INTEGER NOT NULL, rating_key TEXT NOT NULL,
            kind TEXT NOT NULL, title TEXT NOT NULL, show_title TEXT, show_key TEXT,
            season INTEGER, episode INTEGER, year INTEGER, summary TEXT, file_path TEXT,
            part_key TEXT, PRIMARY KEY (channel_id, position));
        """
    )
    legacy = {}
    for cid, order in ((1, "shuffle"), (2, "rotate")):
        playlist = build_playlist(library(rng, 7), order)
        epoch, built = 1_700_000_000_000 + cid, 1_700_000_000_500 + cid
        total = sum(i.duration_ms for i in playlist)
        conn.execute(
            "INSERT INTO channels (id, number, name, order_mode, epoch_ms, total_ms, built_at_ms)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid, cid, f"S{cid}", order, epoch, total, built),
        )
        conn.executemany(
            "INSERT INTO channel_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    cid,
                    i.position,
                    i.start_ms,
                    i.duration_ms,
                    i.rating_key,
                    i.kind,
                    i.title,
                    i.show_title,
                    i.show_key,
                    i.season,
                    i.episode,
                    i.year,
                    None,
                    None,
                    None,
                )
                for i in playlist
            ],
        )
        channel = LegacyChannel(cid, cid, f"S{cid}", order, [], epoch, total, built)
        legacy[cid] = keys(Schedule(channel, playlist).between(epoch - DAY, epoch + 30 * DAY))
    conn.commit()
    conn.close()

    db = Database(path)
    for cid, expected in legacy.items():
        eras = db.eras(cid)
        assert len(eras) == 1 and eras[0].start_ms is None and eras[0].chained
        epoch = eras[0].epoch_ms
        station = station_schedule(eras)
        assert keys(station.between(epoch - DAY, epoch + 30 * DAY)) == expected
    db.close()
    # Opening it again changes nothing.
    db = Database(path)
    assert [len(db.eras(c)) for c in (1, 2)] == [1, 1]
    db.close()


def test_eras_are_saved_and_read_back(tmp_path):
    db = Database(tmp_path / "s.db")
    channel = db.create_channel(1, "One", [], order_mode="shuffle")
    items = build_playlist(library(random.Random(4), 4), "shuffle")
    first = db.add_era(
        channel.id, items, start_ms=0, epoch_ms=0, seed="a", order_mode="shuffle",
        created_ms=1, reason="created",
    )  # fmt: skip
    second = db.add_era(
        channel.id, items[2:], start_ms=5 * MIN, epoch_ms=5 * MIN, seed="b",
        order_mode="shuffle", created_ms=2, reason="update",
        first_pass=[items[3].rating_key], tail=[(items[0].rating_key, "x")], removed=2,
    )  # fmt: skip
    db.close()
    db = Database(tmp_path / "s.db")
    eras = db.eras(channel.id)
    assert [e.id for e in eras] == [first.id, second.id]
    assert eras[1].first_pass == [items[3].rating_key]
    assert eras[1].tail == [(items[0].rating_key, "x")]
    assert eras[1].items == items[2:]  # every field, as saved
    assert eras[0].items == items
    assert db.latest_items(channel.id) == eras[1].items
    db.delete_eras(channel.id, [first.id])
    assert [e.id for e in db.eras(channel.id)] == [second.id]
    db.delete_channel(channel.id)
    assert db.eras(channel.id) == []


@pytest.mark.parametrize("order", ["rotate", "shuffle"])
def test_before_a_new_station_existed_nothing_was_on(order):
    items = library(random.Random(8), 3)
    station = StationSchedule([era(items, order, 1, start=10 * DAY)])
    assert station.locate(10 * DAY - 1) is None
    first = next(station.between(9 * DAY, 11 * DAY))
    assert first.start_ms == 10 * DAY
