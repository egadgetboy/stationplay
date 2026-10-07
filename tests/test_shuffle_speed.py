"""The fast shuffle must give exactly the same order as the original, so
stations built before it changed keep the same schedule (and Plex's guide
stays right)."""

from __future__ import annotations

import itertools
import random
import time

import pytest

from app.db import Item
from app.schedule import MAX_IN_A_ROW, build_playlist, fresh_window, show_key, shuffle_spread


def reference_shuffle(
    pool: list[Item],
    rng: random.Random,
    previous: list[Item] | None = None,
    max_run: int = MAX_IN_A_ROW,
) -> list[Item]:
    """The shuffle as it was before it was made fast (the reference)."""
    groups: dict[str, list[Item]] = {}
    for item in sorted(pool, key=lambda i: i.rating_key):
        groups.setdefault(show_key(item), []).append(item)
    for group in groups.values():
        rng.shuffle(group)

    last: str | None = None
    run = 0
    recent: set[str] = set()
    opening = 0
    if previous:
        last = show_key(previous[-1])
        for item in reversed(previous):
            if show_key(item) != last:
                break
            run += 1
        opening = fresh_window(len(pool), max_run)
        recent = {item.rating_key for item in previous[-opening:]}

    out: list[Item] = []
    remaining = len(pool)
    while remaining:
        in_opening = len(out) < opening

        def fresh(key: str, in_opening: bool = in_opening) -> bool:
            return not in_opening or any(i.rating_key not in recent for i in groups[key])

        live = [k for k, g in groups.items() if g]
        not_too_many = [k for k in live if not (k == last and run >= max_run)]
        allowed = [k for k in not_too_many if fresh(k)] or not_too_many or live
        biggest = max(live, key=lambda k: len(groups[k]))
        others = remaining - len(groups[biggest])
        if biggest in allowed and len(groups[biggest]) > max_run * others:
            key = biggest
        else:
            key = rng.choices(allowed, weights=[len(groups[k]) for k in allowed])[0]
        group = groups[key]
        index = len(group) - 1
        if in_opening:
            # Prefer an episode that didn't just air.
            for n in range(len(group) - 1, -1, -1):
                if group[n].rating_key not in recent:
                    index = n
                    break
        out.append(group.pop(index))
        remaining -= 1
        run = run + 1 if key == last else 1
        last = key
    return out


def _library(rng: random.Random, shows: int, movies: int, skew: bool) -> list[Item]:
    items = []
    n = 0
    for s in range(shows):
        count = rng.randint(1, 60) if skew and s == 0 else rng.randint(1, 12)
        if skew and s == 0:
            count *= 5
        for e in range(count):
            n += 1
            items.append(
                Item(
                    0,
                    0,
                    60_000 * rng.randint(5, 60),
                    f"rk{n:05d}",
                    "episode",
                    f"Ep {e}",
                    f"Show {s}",
                    f"show{s}",
                    1,
                    e + 1,
                    1990,
                )
            )
    for _ in range(movies):
        n += 1
        items.append(Item(0, 0, 90 * 60_000, f"rk{n:05d}", "movie", f"Movie {n}", year=1980))
    rng.shuffle(items)
    return build_playlist(items, "shuffle")


@pytest.mark.parametrize("seed", range(400))
def test_fast_shuffle_matches_the_original(seed):
    rng = random.Random(seed)
    pool = _library(rng, rng.randint(1, 25), rng.choice([0, 0, 3]), skew=seed % 3 == 0)
    previous = None
    for cycle in range(4):  # chained passes, like a real station
        a = reference_shuffle(pool, random.Random(f"{seed}:{cycle}"), previous)
        b = shuffle_spread(pool, random.Random(f"{seed}:{cycle}"), previous)
        assert [i.rating_key for i in a] == [i.rating_key for i in b]
        previous = b


def test_fast_shuffle_matches_the_original_on_a_big_station():
    rng = random.Random(7)
    pool = _library(rng, 150, 20, skew=False)
    previous = None
    for cycle in range(3):
        a = reference_shuffle(pool, random.Random(cycle), previous)
        b = shuffle_spread(pool, random.Random(cycle), previous)
        assert [i.rating_key for i in a] == [i.rating_key for i in b]
        previous = b


def test_a_huge_station_shuffles_quickly():
    """3,000 shows and 60,000 episodes."""
    items = [
        Item(
            0, 0, 22 * 60_000, f"rk{s}-{e}", "episode", f"Ep {e}", f"Show {s}", f"show{s}", 1, e + 1
        )
        for s in range(3000)
        for e in range(20)
    ]
    pool = build_playlist(items, "shuffle")
    started = time.perf_counter()
    order = shuffle_spread(pool, random.Random(1), previous=shuffle_spread(pool, random.Random(0)))
    assert time.perf_counter() - started < 10
    assert len(order) == len(pool)
    run = 1
    for a, b in itertools.pairwise(order):
        run = run + 1 if show_key(a) == show_key(b) else 1
        assert run <= MAX_IN_A_ROW
    assert fresh_window(len(pool)) == 12
