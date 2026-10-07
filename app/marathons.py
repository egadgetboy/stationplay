"""Marathons: now and then, a station plays three episodes of one of its
shows in a row, then carries on exactly where it left off.

A station with marathons on has them a few times a week: at random times
(any hour, on different days), or on the days and at the time you set. Each
is three episodes of one show, the one whose last marathon was longest ago:
the next three in order (picking up where its last marathon ended), or a
random stretch of three. A station needs at least MIN_SHOWS shows with
three or more episodes each (that play: broken files are left out).

They're planned with the station's other specials (see specials.py).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .db import Channel, Item, MarathonRecord
from .schedule import StationSchedule

log = logging.getLogger(__name__)

MODES = ("off", "random", "set")
EPISODE_CHOICES = ("next", "random")
MAX_A_WEEK = 4
EPISODES = 3  # in each marathon
MIN_SHOWS = 5  # a station needs this many shows (with EPISODES episodes each)
KIND = "marathon"


def valid_days(text: str) -> bool:
    """Whether `text` is days of the week as stored: "0,5" (Monday 0 to
    Sunday 6), at least one, each once."""
    days = text.split(",")
    return (
        bool(text)
        and all(d in "0123456" and len(d) == 1 for d in days)
        and len(set(days)) == len(days)
    )


def valid_time(text: str) -> bool:
    """Whether `text` is a time of day as HH:MM (24 hours)."""
    hours, _, minutes = text.partition(":")
    return (
        len(hours) == 2
        and len(minutes) == 2
        and hours.isdigit()
        and minutes.isdigit()
        and int(hours) < 24
        and int(minutes) < 60
    )


def _monday(ms: int) -> date:
    """The Monday of the (local) week `ms` falls in."""
    day = datetime.fromtimestamp(ms / 1000).date()
    return day - timedelta(days=day.weekday())


def at_minute(day: date, minute: int) -> int:
    """`minute` minutes into a (local) day, as ms."""
    return int(datetime(day.year, day.month, day.day, minute // 60, minute % 60).timestamp() * 1000)


def minute_of(text: str, default: int = 20 * 60) -> int:
    """A time of day as HH:MM, as minutes into the day (`default` if it
    isn't one)."""
    if not valid_time(text):
        return default
    hours, _, minutes = text.partition(":")
    return int(hours) * 60 + int(minutes)


def day_numbers(text: str) -> list[int]:
    """Days of the week as stored ("0,5"), as numbers (Monday 0)."""
    return sorted({int(d) for d in text.split(",") if d.isdigit() and 0 <= int(d) <= 6})


def weekly(days: str, time_of_day: str, from_ms: int, to_ms: int) -> list[int]:
    """When `time_of_day` (HH:MM) falls on `days` (as stored) from `from_ms`
    to `to_ms`, in order."""
    if to_ms <= from_ms:
        return []
    minute, out = minute_of(time_of_day), []
    monday = _monday(from_ms)
    while at_minute(monday, 0) < to_ms:
        out += [
            t
            for d in day_numbers(days)
            if from_ms <= (t := at_minute(monday + timedelta(days=d), minute)) < to_ms
        ]
        monday += timedelta(days=7)
    return out


def due_times(channel: Channel, from_ms: int, to_ms: int) -> list[int]:
    """When the station's marathons are due between `from_ms` and `to_ms`,
    in order. At random times, they're the same each time they're worked
    out (from the station and the week)."""
    if channel.marathon_mode not in ("random", "set") or to_ms <= from_ms:
        return []
    out: list[int] = []
    monday = _monday(from_ms)
    while at_minute(monday, 0) < to_ms:
        if channel.marathon_mode == "random":
            rng = random.Random(f"{channel.id}:{monday.isoformat()}")
            count = max(1, min(MAX_A_WEEK, channel.marathons_a_week))
            times = [
                at_minute(monday + timedelta(days=d), rng.randrange(24 * 60))
                for d in sorted(rng.sample(range(7), count))
            ]
        else:
            minute = minute_of(channel.marathon_time)
            times = [
                at_minute(monday + timedelta(days=d), minute)
                for d in day_numbers(channel.marathon_days)
            ]
        out += [t for t in times if from_ms <= t < to_ms]
        monday += timedelta(days=7)
    return sorted(out)


def nearest_break(station: StationSchedule, due_ms: int, earliest_ms: int) -> int | None:
    """The program break nearest `due_ms` that's no earlier than
    `earliest_ms` (the one before it or the one after it); None if there
    isn't one."""
    slot = station.locate(due_ms)
    if slot is None:
        return None
    breaks = [b for b in (slot.start_ms, slot.end_ms) if b >= earliest_ms]
    return min(breaks, key=lambda b: (abs(b - due_ms), b)) if breaks else None


@dataclass(frozen=True)
class Marathon:
    show_key: str
    title: str
    items: list[Item]  # in order


def _order(item: Item) -> tuple[int, int, str]:
    return item.season or 0, item.episode or 0, item.rating_key


def choose(
    channel: Channel,
    items: list[Item],
    due_ms: int,
    broken: set[str],
    history: list[MarathonRecord],
) -> Marathon | None:
    """The marathon due at `due_ms`, from the station's programs `items`
    (none of `broken`), given the marathons before it (`history`): a show
    with at least EPISODES episodes, the one whose last marathon was
    longest ago (never first), with its next episodes in order or a random
    stretch. The same each time it's worked out from the same things. None
    if the station hasn't MIN_SHOWS shows with enough episodes that play."""
    shows: dict[str, list[Item]] = {}
    for item in items:
        if item.kind == "episode" and item.show_key:
            shows.setdefault(item.show_key, []).append(item)
    playable = {
        key: sorted((i for i in episodes if i.rating_key not in broken), key=_order)
        for key, episodes in shows.items()
    }
    eligible = {key: episodes for key, episodes in playable.items() if len(episodes) >= EPISODES}
    if len(eligible) < MIN_SHOWS:
        return None

    earlier = [r for r in history if r.due_ms < due_ms]
    last_time: dict[str, int] = {}
    for record in earlier:
        last_time[record.show_key] = max(last_time.get(record.show_key, 0), record.due_ms)
    rng = random.Random(f"{channel.id}:{due_ms}")
    ties = {key: rng.random() for key in sorted(eligible)}
    show = min(eligible, key=lambda k: (last_time.get(k, -1), ties[k]))
    episodes = eligible[show]
    if channel.marathon_episodes == "random":
        start = rng.randrange(len(episodes) - EPISODES + 1)
    else:
        start = 0
        before = [r for r in earlier if r.show_key == show]
        if before:
            left_off = max(before, key=lambda r: r.due_ms).last
            later = [
                n for n, i in enumerate(episodes) if (i.season or 0, i.episode or 0) > left_off
            ]
            # From the next episode; from the start again once too few are left.
            if later and later[0] + EPISODES <= len(episodes):
                start = later[0]
    return Marathon(show, episodes[0].display_title, episodes[start : start + EPISODES])


def title(special: dict | None) -> str | None:
    """The show's title, if `special` is a marathon's: "Leave It to Beaver"."""
    if not special or special.get("kind") != KIND:
        return None
    return str(special.get("title") or "")


def label(special: dict | None, index: int) -> str:
    """How the guide says an episode is part of a marathon: "Leave It to
    Beaver Marathon (1 of 3)"; "" if it isn't."""
    show = title(special)
    return f"{show} Marathon ({index + 1} of {EPISODES})" if show is not None else ""
