"""Specials: now and then something takes over a station's schedule for a
while, and then the station carries on exactly where it left off.

  * A marathon (see marathons.py): three episodes of one of its shows.
  * A Feature Presentation: on the days and at the time you set, a movie
    from a movie library, a collection or the station's own movies, opened
    by a card saying so, in the station's colours. Each movie waits its
    turn: the one shown longest ago (or never) is next.
  * A time-of-day block: on the days you set, from its start to its end,
    shows of its own, in the station's order (episode order or shuffle).
    Each time, it carries on from where it got to the time before.

Each starts at the program break nearest its time and is two eras (see
schedule.py): its own, then one carrying on the station's schedule from the
moment it took over, so nothing is skipped and nothing airs twice. A block
ends at the break in its own programs nearest its end time. Specials are
planned up to PLAN_AHEAD_MS ahead, well before any guide shows them, so a
guide never has to change for one. A change to the station (or an update
from Plex) takes over after any special already under way, and the
specials after it are planned again the same way: the same programs for
the same times.

When two would overlap, a block comes first, then a Feature Presentation,
then a marathon: the other is left out that time. One that would start
more than LATE_MS after its time, because the one before it ran on, is left
out too.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from . import marathons
from .db import Channel, Database, Era, Item, MarathonRecord, NewEra, SpecialRun, show_key
from .playing import cap
from .playing import station as station_named
from .schedule import (
    TAIL,
    EraSchedule,
    Slot,
    StationSchedule,
    build_playlist,
    forget_eras,
    plan_era,
    station_schedule,
)

log = logging.getLogger(__name__)

MARATHON, FEATURE, BLOCK = "marathon", "feature", "block"
# Which wins when two would overlap.
PRIORITY = {BLOCK: 3, FEATURE: 2, MARATHON: 1}
FEATURE_MODES = ("off", "on")
PLAN_AHEAD_MS = 8 * 24 * 3600 * 1000
# Specials due this far past PLAN_AHEAD_MS are looked at too, so one near
# the end of the plan can't hold up a more important one just after it.
LOOK_PAST_MS = 24 * 3600 * 1000
LATE_MS = 15 * 60 * 1000
FEATURE_CARD_MS = 10_000  # the Feature Presentation card, before the movie
MAX_BLOCKS = 4
BLOCK_NAME_MAX = 40
BLOCK_MIN_MINUTES = 30
BLOCK_MAX_MINUTES = 12 * 60
# How much of a block's running order is kept for next time.
NEXT_KEPT = 20


def set_name(kind: str, block_id: str = "") -> str:
    """The name a special's own programs are kept under (see
    db.save_program_sets): "feature", or "block:<id>"."""
    return f"{BLOCK}:{block_id}" if kind == BLOCK else FEATURE


def has_specials(channel: Channel) -> bool:
    return (
        channel.marathon_mode in ("random", "set")
        or channel.feature_mode == "on"
        or bool(channel.blocks)
    )


def carries_on(era: Era) -> bool:
    """Whether `era` is a station carrying on after a special."""
    return era.reason.startswith("after ")


# When they're due -------------------------------------------------------------


@dataclass(frozen=True)
class Due:
    kind: str
    at_ms: int
    end_ms: int = 0  # (a block's) when it's due to end
    block: dict | None = None


def block_minutes(block: dict) -> int:
    """How long a block runs, in minutes (past midnight if it ends earlier
    in the day than it starts)."""
    start = marathons.minute_of(str(block.get("start", "")))
    end = marathons.minute_of(str(block.get("end", "")))
    return (end - start) % (24 * 60)


def due(channel: Channel, from_ms: int, to_ms: int) -> list[Due]:
    """The station's specials due from `from_ms` to `to_ms`, in order (and
    by priority, for any due at the same moment)."""
    out = [Due(MARATHON, t) for t in marathons.due_times(channel, from_ms, to_ms)]
    if channel.feature_mode == "on":
        out += [
            Due(FEATURE, t)
            for t in marathons.weekly(channel.feature_days, channel.feature_time, from_ms, to_ms)
        ]
    for block in channel.blocks:
        minutes = block_minutes(block)
        for t in marathons.weekly(
            str(block.get("days", "")), str(block.get("start", "")), from_ms, to_ms
        ):
            # (The end as the clock says, on a day the clocks change.)
            end_day = datetime.fromtimestamp((t + minutes * 60_000) / 1000).date()
            end = marathons.at_minute(end_day, marathons.minute_of(str(block.get("end", ""))))
            out.append(Due(BLOCK, t, end if end > t else t + minutes * 60_000, block))
    return sorted(out, key=lambda d: (d.at_ms, -PRIORITY[d.kind]))


# Checking settings ------------------------------------------------------------

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
WEEK = 7 * 24 * 60


def block_problem(block: dict) -> str | None:
    """Why a block's name, days or times aren't right, or None."""
    name = str(block.get("name") or "").strip()
    if not name:
        return "Give each block a name"
    if not marathons.valid_days(str(block.get("days", ""))):
        return f"Choose the days for the block \u201c{name}\u201d"
    if not (
        marathons.valid_time(str(block.get("start", "")))
        and marathons.valid_time(str(block.get("end", "")))
    ):
        return f"The block \u201c{name}\u201d needs a start time and an end time (HH:MM)"
    minutes = block_minutes(block)
    if not BLOCK_MIN_MINUTES <= minutes <= BLOCK_MAX_MINUTES:
        return (
            f"The block \u201c{name}\u201d must be {BLOCK_MIN_MINUTES} minutes to "
            f"{BLOCK_MAX_MINUTES // 60} hours long"
        )
    return None


def _spans(block: dict) -> list[tuple[int, int]]:
    """When a block runs in the week, as minutes from Monday 00:00."""
    start = marathons.minute_of(str(block.get("start", "")))
    length = block_minutes(block)
    return [
        (d * 24 * 60 + start, d * 24 * 60 + start + length)
        for d in marathons.day_numbers(str(block.get("days", "")))
    ]


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    # (A block on Sunday night can run into Monday morning.)
    return any(a[0] < b[1] + shift and b[0] + shift < a[1] for shift in (-WEEK, 0, WEEK))


def _in_block(blocks: list[dict], days: str, time_of_day: str) -> tuple[str, str] | None:
    """The first of `days` (and the block) where `time_of_day` falls within a
    block, if it does."""
    minute = marathons.minute_of(time_of_day)
    for d in marathons.day_numbers(days):
        at = d * 24 * 60 + minute
        for block in blocks:
            if any(_overlap((at, at + 1), span) for span in _spans(block)):
                return DAYS[d], str(block.get("name", ""))
    return None


def timing_problem(settings: dict[str, Any]) -> str | None:
    """Why a station's blocks, Feature Presentation and marathons at set
    times can't all happen as set (by their stored names), or None."""
    blocks = list(settings.get("blocks") or [])
    for n, a in enumerate(blocks):
        for b in blocks[n + 1 :]:
            for span in _spans(a):
                if any(_overlap(span, other) for other in _spans(b)):
                    day = DAYS[(span[0] // (24 * 60)) % 7]
                    return (
                        f"The blocks \u201c{a.get('name')}\u201d and \u201c{b.get('name')}\u201d "
                        f"overlap on {day}s"
                    )
    if settings.get("feature_mode") == "on":
        found = _in_block(blocks, settings["feature_days"], settings["feature_time"])
        if found:
            return (
                f"The Feature Presentation on {found[0]}s at {settings['feature_time']} falls "
                f"during the block \u201c{found[1]}\u201d"
            )
    if settings.get("marathon_mode") == "set":
        found = _in_block(blocks, settings["marathon_days"], settings["marathon_time"])
        if found:
            return (
                f"Marathons on {found[0]}s at {settings['marathon_time']} fall during the block "
                f"\u201c{found[1]}\u201d"
            )
    return None


# What each one is -------------------------------------------------------------


@dataclass
class Made:
    """A special, ready to add: its era (playlist, how it plays) and how
    long it runs, and what to remember about it."""

    items: list[Item]
    special: dict[str, Any]
    length_ms: int
    remember: SpecialRun | MarathonRecord
    # How its era plays (by default, its programs once each from its start).
    epoch_ms: int | None = None
    order_mode: str = "rotate"
    first_pass: list[str] | None = None
    tail: list[tuple[str, str]] | None = None


def _in_order(items: list[Item]) -> tuple[list[Item], int]:
    """`items` to play once each in this order, with their offsets, and how
    long they run."""
    out, length = [], 0
    for n, item in enumerate(items):
        out.append(replace(item, position=n, start_ms=length))
        length += item.duration_ms
    return out, length


def feature_movies(db: Database, channel: Channel, own: list[Item], broken: set[str]) -> list[Item]:
    """The movies a station's Feature Presentation picks from: from its
    movie library or collection, or its own movies (`own`: its programs);
    none that are broken."""
    pool = db.program_set(channel.id, FEATURE) if channel.feature_source else own
    seen: set[str] = set()
    out = []
    for item in pool:
        if item.kind != "movie" or item.rating_key in broken or item.rating_key in seen:
            continue
        seen.add(item.rating_key)
        out.append(item)
    return out


def choose_movie(
    channel: Channel, movies: list[Item], due_ms: int, history: list[SpecialRun]
) -> Item | None:
    """The movie for the Feature Presentation due at `due_ms`: the one shown
    longest ago (any never shown first), given the ones before it
    (`history`). The same each time it's worked out from the same things."""
    if not movies:
        return None
    last: dict[str, int] = {}
    for run in history:
        if run.due_ms < due_ms:
            last[run.key] = max(last.get(run.key, 0), run.due_ms)
    rng = random.Random(f"{channel.id}:{FEATURE}:{due_ms}")
    ties = {m.rating_key: rng.random() for m in sorted(movies, key=lambda m: m.rating_key)}
    return min(movies, key=lambda m: (last.get(m.rating_key, -1), ties[m.rating_key]))


def _marathon(db: Database, channel: Channel, d: Due, base: Era, broken: set[str]) -> Made | None:
    marathon = marathons.choose(channel, base.items, d.at_ms, broken, db.marathons(channel.id))
    if marathon is None:
        return None
    items, length = _in_order(marathon.items)
    last = marathon.items[-1]
    return Made(
        items,
        {"kind": MARATHON, "title": marathon.title, "show": marathon.show_key, "due": d.at_ms},
        length,
        MarathonRecord(d.at_ms, marathon.show_key, (last.season or 0, last.episode or 0)),
    )


def _feature(
    db: Database, channel: Channel, d: Due, base: Era, broken: set[str], room_ms: int | None
) -> Made | None:
    """The Feature Presentation due at `d`: of the movies that fit in
    `room_ms` with the card before them (all, if None), the one whose
    turn it is."""
    movies = [
        m
        for m in feature_movies(db, channel, base.items, broken)
        if room_ms is None or FEATURE_CARD_MS + m.duration_ms - m.lead_ms <= room_ms
    ]
    movie = choose_movie(channel, movies, d.at_ms, db.special_runs(channel.id, FEATURE))
    if movie is None:
        return None
    # The card, then the movie (and whatever follows it).
    shown = replace(
        movie,
        lead_ms=FEATURE_CARD_MS,
        duration_ms=FEATURE_CARD_MS + movie.duration_ms - movie.lead_ms,
    )
    items, length = _in_order([shown])
    return Made(
        items,
        {"kind": FEATURE, "title": movie.title, "year": movie.year, "due": d.at_ms},
        length,
        SpecialRun(d.at_ms, movie.rating_key),
    )


def block_programs(db: Database, channel: Channel, block_id: str, broken: set[str]) -> list[Item]:
    return [
        i
        for i in db.program_set(channel.id, set_name(BLOCK, block_id))
        if i.rating_key not in broken
    ]


def _block(
    db: Database, channel: Channel, d: Due, start: int, broken: set[str], seed: str
) -> Made | None:
    block = d.block or {}
    block_id = str(block.get("id", ""))
    programs = block_programs(db, channel, block_id, broken)
    if not programs:
        return None
    order = channel.order_mode
    playlist = build_playlist(programs, order)
    # Where it got to last time.
    before = [
        r for r in db.special_runs(channel.id, BLOCK) if r.key == block_id and r.due_ms < d.at_ms
    ]
    state = _state(before[-1].value) if before else {}
    offset, first_pass, tail = 0, None, None
    if order == "rotate":
        at = {i.rating_key: i.start_ms for i in playlist}
        offset = next((at[k] for k in state.get("next", []) if k in at), 0)
    else:
        keys = {i.rating_key for i in playlist}
        first_pass = [k for k in state.get("left", []) if k in keys] or None
        tail = [(str(k), str(s)) for k, s in state.get("tail", [])][-TAIL:] or None
    schedule = EraSchedule(
        playlist,
        epoch_ms=start - offset,
        seed=seed,
        order_mode=order,
        start_ms=start,
        chained=False,
        first_pass=first_pass,
        tail=tail,
    )
    alone = StationSchedule([schedule])
    end = marathons.nearest_break(alone, max(d.end_ms, start + 1), start + 1)
    following = alone.locate(end) if end is not None else None
    if end is None or following is None:
        return None
    # Where it gets to this time, for next time.
    if order == "rotate":
        upcoming, slot = [], following
        for _ in range(min(NEXT_KEPT, len(playlist))):
            upcoming.append(slot.item.rating_key)
            slot = schedule.after(slot)
        state = {"next": upcoming}
    else:
        in_pass, _ = schedule.pass_order(following.cycle)
        state = {
            "left": [i.rating_key for i in in_pass[following.index :]],
            "tail": [[s.item.rating_key, show_key(s.item)] for s in alone.recent(end, TAIL)],
        }
    return Made(
        playlist,
        {"kind": BLOCK, "id": block_id, "title": str(block.get("name", "")), "due": d.at_ms},
        end - start,
        SpecialRun(d.at_ms, block_id, json.dumps(state)),
        start - offset,
        order,
        first_pass,
        tail,
    )


def _state(value: str) -> dict:
    try:
        found = json.loads(value or "{}")
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def _could_air(db: Database, channel: Channel, d: Due, base: Era, broken: set[str]) -> bool:
    """Whether a special has anything to play (so it's worth making room for)."""
    if d.kind == BLOCK:
        return bool(block_programs(db, channel, str((d.block or {}).get("id", "")), broken))
    if d.kind == FEATURE:
        return bool(feature_movies(db, channel, base.items, broken))
    return True


# Planning them ----------------------------------------------------------------


def plan(
    db: Database,
    channel: Channel,
    broken: set[str],
    earliest_ms: int,
    now_ms: int,
) -> int:
    """Plans the station's specials due from `earliest_ms` (or a little
    before: one not planned yet that can still start in time) to
    PLAN_AHEAD_MS from now, as eras. None starts before `earliest_ms`, or
    once its newest era has begun; but one can start just as that era
    would (if it hasn't begun by `earliest_ms`), and that era then follows
    it instead. Returns how many it planned."""
    if not has_specials(channel):
        return 0
    eras = db.eras(channel.id)
    if not eras:
        return 0
    horizon = now_ms + PLAN_AHEAD_MS
    planned_before = {(MARATHON, r.due_ms) for r in db.marathons(channel.id)} | {
        (kind, r.due_ms) for kind in (FEATURE, BLOCK) for r in db.special_runs(channel.id, kind)
    }
    floor = earliest_ms
    dues = [
        d
        for d in due(channel, floor - LATE_MS, horizon + LOOK_PAST_MS)
        if (d.kind, d.at_ms) not in planned_before
    ]
    planned = 0
    for n, d in enumerate(dues):
        if d.at_ms >= horizon:
            break
        eras = db.eras(channel.id)
        base = eras[-1]
        if base.special:
            break  # (never so: a special's era is always saved with the one after it)
        joinable = base.start_ms is not None and base.start_ms >= floor
        earliest = max(floor, (base.start_ms or 0) + (0 if joinable else 1))
        station = station_schedule(eras)
        start = marathons.nearest_break(station, max(d.at_ms, earliest), earliest)
        if start is None or start >= horizon:
            continue
        if earliest > d.at_ms and start > d.at_ms + LATE_MS:
            _skip(channel, d, "what's on before it runs too far past its start time")
            continue
        if d.kind == BLOCK and start >= d.end_ms:
            _skip(channel, d, "the nearest program break comes after its end time")
            continue
        seed = f"{channel.id}:{now_ms}:{d.kind}:{start}"
        # A more important one due after it: this one has to be over by then
        # (a Feature Presentation picks a movie that is).
        ahead = next(
            (
                o
                for o in dues[n + 1 :]
                if PRIORITY[o.kind] > PRIORITY[d.kind] and _could_air(db, channel, o, base, broken)
            ),
            None,
        )
        room = ahead.at_ms + LATE_MS - start if ahead is not None else None
        if d.kind == MARATHON:
            made = _marathon(db, channel, d, base, broken)
        elif d.kind == FEATURE:
            made = _feature(db, channel, d, base, broken, room)
            if made is None and room is not None and ahead is not None:
                _skip(channel, d, f"no movie is short enough to finish before {_name(ahead)}")
        else:
            made = _block(db, channel, d, start, broken, seed)
        if made is None:
            continue
        if room is not None and ahead is not None and made.length_ms > room:
            _skip(channel, d, f"it would run into {_name(ahead)}")
            continue
        _add(db, channel, station, base, made, start, seed, now_ms)
        if isinstance(made.remember, MarathonRecord):
            db.remember_marathon(channel.id, made.remember)
        else:
            db.remember_special(channel.id, d.kind, made.remember)
        planned += 1
        floor = start + 1
        log.info(
            "%s: planned %s for %s",
            cap(station_named(channel.number, channel.name)),
            _name(d, made.special),
            datetime.fromtimestamp(start / 1000).strftime("%a %Y-%m-%d %H:%M"),
        )
    return planned


def _name(d: Due, special: dict | None = None) -> str:
    """A special as the log says it: "a Cheers marathon"."""
    if d.kind == MARATHON:
        return f"a {special['title']} marathon" if special else "a marathon"
    if d.kind == FEATURE:
        return (
            f"the Feature Presentation ({special['title']})"
            if special
            else "the Feature Presentation"
        )
    return f"the block {(d.block or {}).get('name', '')!r}"


# Specials left out that the log has said so about (planning looks at the
# same ones again each hour).
_said: set[tuple[int, str, int]] = set()


def _skip(channel: Channel, d: Due, why: str) -> None:
    said = (channel.id, d.kind, d.at_ms)
    if said in _said:
        return
    if len(_said) > 1000:
        _said.clear()
    _said.add(said)
    log.info(
        "%s: %s at %s won't air this time (%s)",
        cap(station_named(channel.number, channel.name)),
        _name(d),
        datetime.fromtimestamp(d.at_ms / 1000).strftime("%a %Y-%m-%d %H:%M"),
        why,
    )


def _add(
    db: Database,
    channel: Channel,
    station: StationSchedule,
    base: Era,
    made: Made,
    start: int,
    seed: str,
    now_ms: int,
) -> None:
    """The special's two eras, saved together: its own from `start`, then
    the station carrying on from where it was at `start`."""
    kind = made.special["kind"]
    own = NewEra(
        made.items,
        start,
        start if made.epoch_ms is None else made.epoch_ms,
        seed,
        made.order_mode,
        now_ms,
        kind,
        made.first_pass,
        made.tail,
        special=made.special,
    )
    end = start + made.length_ms
    playing = EraSchedule(
        own.items,
        epoch_ms=own.epoch_ms,
        seed=own.seed,
        order_mode=own.order_mode,
        start_ms=start,
        chained=False,
        first_pass=own.first_pass,
        tail=own.tail,
    )
    aired = [
        (s.item.rating_key, show_key(s.item))
        for s in StationSchedule([playing]).between(start, end)
    ]
    if start == base.start_ms:
        # It starts just as the newest era would have (which hasn't begun):
        # that era follows it instead, as it was.
        follows = NewEra(
            base.items,
            end,
            base.epoch_ms + made.length_ms,
            base.seed,
            base.order_mode,
            base.created_ms,
            base.reason,
            base.first_pass,
            [*base.tail, *aired][-TAIL:],
            base.added,
            base.removed,
        )
        db.replace_eras(channel.id, [base.id], [own, follows])
        forget_eras([base.id])
        return
    # What was due at `start` airs as soon as the special ends: the pass
    # through the station's programs it was in carries on from there.
    carry = plan_era(station, start, base.items, base.order_mode)
    follows = NewEra(
        carry.items,
        end,
        carry.epoch_ms + made.length_ms,
        f"{channel.id}:{now_ms}:after {kind}:{start}",
        carry.order_mode,
        now_ms,
        f"after {kind}",
        carry.first_pass,
        [*carry.tail, *aired][-TAIL:],
    )
    db.replace_eras(channel.id, [], [own, follows])


# How they're shown ------------------------------------------------------------


def label(special: dict | None, index: int) -> str:
    """How the guide says a program is part of a special: "Leave It to
    Beaver Marathon (1 of 3)", "Feature Presentation", or the block's name;
    "" if it isn't."""
    kind = (special or {}).get("kind")
    if kind == MARATHON:
        return marathons.label(special, index)
    if kind == FEATURE:
        return "Feature Presentation"
    if kind == BLOCK:
        return str((special or {}).get("title") or "")
    return ""


def starting(station: StationSchedule, slot: Slot) -> tuple[str, str] | None:
    """If `slot` opens a special, what to call it on a card or banner saying
    it's up next: ("Leave It to Beaver Marathon", "3 episodes in a row"),
    ("Feature Presentation", "Jaws (1975)"), or ("Saturday Cartoons",
    "Starting with The Flintstones"). None if it doesn't."""
    era = station.era_of(slot)
    special = era.special or {}
    if not special or slot.start_ms != era.start_ms:
        return None
    kind, title = special.get("kind"), str(special.get("title") or "")
    if kind == MARATHON:
        return f"{title} Marathon", f"{marathons.EPISODES} episodes in a row"
    if kind == FEATURE:
        year = special.get("year")
        return "Feature Presentation", f"{title} ({year})" if year else title
    if kind == BLOCK and title:
        return title, f"Starting with {slot.item.display_title}"
    return None
