"""Turning a station's content into a schedule that runs forever.

The schedule is pure arithmetic from fixed starting points, so what is on at
any moment (and the whole guide) can be computed without keeping any state.
That is what keeps the guide Plex downloaded in step with what actually
plays, even across restarts.

A station's schedule is a series of eras. Each era is a frozen playlist that
takes over from the one before at a program break; a new era is how new
episodes join a station (and removed ones leave) without disturbing
anything already in a guide. An era carries on where the last one left off:
episode order resumes with the program that was due next, and shuffle
finishes the pass it was in (with the new programs added) before starting
fresh passes.

Programs play back to back at their real lengths: nothing is padded or cut
to fit 15/30/60-minute slots, so a 7-minute cartoon is followed straight
away by the next one.

Episode order: one episode from each show in turn, each show in episode
order, like classic reruns. The whole run repeats when it reaches the end.

Shuffle: each pass through the station's library is shuffled afresh, so a
show doesn't come back at the same time of day, and no show plays more than
twice in a row (including where one pass hands over to the next), unless a
station is made up almost entirely of one show and there's no other way.
"""

from __future__ import annotations

import bisect
import random
import threading
from collections import Counter, OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass, replace

from .db import Era, Item, show_key

ORDER_MODES = ("shuffle", "rotate")
MAX_IN_A_ROW = 2
_CACHED_PASSES = 6
# Shuffled passes are worked out forward from this pass.
_CHAIN_START = -8
_CHECKPOINT_EVERY = 64


def build_playlist(items: list[Item], order_mode: str) -> list[Item]:
    """The station's programs, de-duplicated, with their offsets assigned.

    For episode order this is the running order. For shuffle it's the fixed
    base list that each pass is shuffled from.
    """
    unique: dict[str, Item] = {}
    for item in items:
        unique.setdefault(item.rating_key, item)
    pool = list(unique.values())
    ordered = _rotate(pool) if order_mode == "rotate" else sorted(pool, key=lambda i: i.rating_key)
    return _with_offsets(ordered)


def _with_offsets(ordered: list[Item]) -> list[Item]:
    out: list[Item] = []
    start = 0
    for position, item in enumerate(ordered):
        out.append(replace(item, position=position, start_ms=start))
        start += item.duration_ms
    return out


def _rotate(pool: list[Item]) -> list[Item]:
    groups: dict[str, list[Item]] = {}
    for item in pool:
        groups.setdefault(show_key(item), []).append(item)
    for group in groups.values():
        group.sort(key=lambda i: (i.season or 0, i.episode or 0, i.year or 0, i.title))
    queues = sorted(groups.values(), key=lambda g: (g[0].display_title.lower(), g[0].year or 0))
    out: list[Item] = []
    longest = max((len(q) for q in queues), default=0)
    for index in range(longest):
        out.extend(queue[index] for queue in queues if index < len(queue))
    return out


def fresh_window(size: int, max_run: int = MAX_IN_A_ROW) -> int:
    """How many programs at the end of one pass stay out of the opening of
    the next: about a third of a small station's library, up to 12."""
    return max(max_run + 1, min(size // 3, 12))


def shuffle_spread(
    pool: list[Item],
    rng: random.Random,
    previous: list[Item] | None = None,
    max_run: int = MAX_IN_A_ROW,
) -> list[Item]:
    """A random order in which no show appears more than `max_run` times in
    a row, whenever the mix of shows makes that possible.

    `previous` is the pass that aired just before. The rule carries across
    from it (if it ended with two episodes of a show, this pass doesn't open
    with a third), and nothing from the end of it is repeated near the start
    of this one.

    Picks one program at a time at random, each show weighted by how many
    programs it has left, except when the show with the most programs left
    needs every gap it can get: then it goes next, so the remaining
    programs can still be spread out.

    Shows are kept in a running-total tree, so each pick takes a few steps
    however many shows the station has, and a station of thousands of shows
    shuffles in about a second.
    """
    groups: dict[str, list[Item]] = {}
    for item in sorted(pool, key=lambda i: i.rating_key):
        groups.setdefault(show_key(item), []).append(item)
    for group in groups.values():
        rng.shuffle(group)
    keys = list(groups)
    lists = [groups[k] for k in keys]
    position = {k: n for n, k in enumerate(keys)}
    left = _ShowCounts([len(g) for g in lists])

    last: int | None = None
    run = 0
    recent: set[str] = set()
    opening = 0
    if previous:
        last_key = show_key(previous[-1])
        last = position.get(last_key)
        for item in reversed(previous):
            if show_key(item) != last_key:
                break
            run += 1
        opening = fresh_window(len(pool), max_run)
        recent = {item.rating_key for item in previous[-opening:]}

    out: list[Item] = []
    remaining = len(pool)
    while remaining:
        in_opening = len(out) < opening
        # The show that has just played max_run times in a row sits out,
        # unless it's the only one left.
        blocked = last if last is not None and run >= max_run else None
        if blocked is not None and left.size(blocked) == remaining:
            blocked = None
        allowed: list[int] | None = None
        if in_opening:
            # Near the start of a pass, also avoid what just aired.
            live = [n for n in range(len(lists)) if lists[n] and n != blocked]
            allowed = [n for n in live if _fresh(lists[n], recent)] or live
        # Only one show can have more than max_run times all the others.
        most = left.max_size
        needs_gaps = most > max_run * (remaining - most)
        biggest = left.biggest() if needs_gaps else None
        if biggest is not None and (
            biggest in allowed if allowed is not None else biggest != blocked
        ):
            pick = biggest
        elif allowed is not None:
            pick = rng.choices(allowed, weights=[len(lists[n]) for n in allowed])[0]
        else:
            pick = left.choose(rng, skip=blocked)
        group = lists[pick]
        index = len(group) - 1
        if in_opening:
            # Prefer an episode that didn't just air.
            for n in range(len(group) - 1, -1, -1):
                if group[n].rating_key not in recent:
                    index = n
                    break
        out.append(group.pop(index))
        left.take(pick)
        remaining -= 1
        run = run + 1 if pick == last else 1
        last = pick
    return out


def _fresh(group: list[Item], recent: set[str]) -> bool:
    return any(i.rating_key not in recent for i in group)


class _ShowCounts:
    """How many programs each show has left, kept as running totals (a
    Fenwick tree) so a weighted random pick takes a few steps however many
    shows there are, plus a tally of sizes so the biggest show is quick to
    find."""

    def __init__(self, sizes: list[int]) -> None:
        self.sizes = list(sizes)
        self.n = len(sizes)
        self.remaining = sum(sizes)
        self.tree = [0] * (self.n + 1)
        for i, size in enumerate(sizes):
            self._add(i, size)
        self.top = 1
        while self.top * 2 <= self.n:
            self.top *= 2
        self.max_size = max(sizes, default=0)
        self.with_size = [0] * (self.max_size + 1)  # shows with each size
        for size in sizes:
            self.with_size[size] += 1
        self._biggest = 0

    def _add(self, i: int, delta: int) -> None:
        i += 1
        while i <= self.n:
            self.tree[i] += delta
            i += i & -i

    def size(self, i: int) -> int:
        return self.sizes[i]

    def take(self, i: int) -> None:
        """One program of show `i` has been scheduled."""
        size = self.sizes[i]
        self.sizes[i] = size - 1
        self.remaining -= 1
        self._add(i, -1)
        self.with_size[size] -= 1
        self.with_size[size - 1] += 1
        if size == self.max_size and not self.with_size[size]:
            self.max_size -= 1

    def biggest(self) -> int:
        """The first show (in order) with the most programs left."""
        if self.sizes[self._biggest] != self.max_size or self.with_size[self.max_size] > 1:
            self._biggest = self.sizes.index(self.max_size)
        return self._biggest

    def _first_above(self, target: float) -> int:
        """The first show whose running total is above `target`."""
        pos, total, step = 0, 0, self.top
        while step:
            nxt = pos + step
            if nxt <= self.n and total + self.tree[nxt] <= target:
                pos = nxt
                total += self.tree[nxt]
            step //= 2
        return pos

    def choose(self, rng: random.Random, skip: int | None = None) -> int:
        """A show picked at random, weighted by programs left, leaving out
        `skip`. Gives the same pick as rng.choices(shows, weights) and uses
        the same one random number."""
        skipped = self.sizes[skip] if skip is not None else 0
        total = self.remaining - skipped
        if skip is not None and skipped:
            self._add(skip, -skipped)
        try:
            target = rng.random() * total
            # rng.choices takes the last show if rounding reaches the total.
            return self._first_above(min(target, total - 1))
        finally:
            if skip is not None and skipped:
                self._add(skip, skipped)


@dataclass(frozen=True)
class Slot:
    """One airing of a program: the program plus the times it airs."""

    item: Item
    cycle: int  # which pass through the era's library
    index: int  # position within that pass
    start_ms: int
    end_ms: int
    era_id: int = 0

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def _stub(rating_key: str, key: str) -> Item:
    """Just enough of a program to apply the shuffle rules to."""
    return Item(0, 0, 0, rating_key, "episode", "", show_key=key)


class EraSchedule:
    """What plays when during one era of a station.

    Episode order repeats the playlist from `epoch_ms`. Shuffle works in
    passes: each pass plays every program once, shuffled knowing how the
    pass before it ended so the rules hold where passes meet. Each pass
    depends on the one before, so passes are worked out forward from a fixed
    starting point, with checkpoints kept so this stays quick however long a
    station has been on the air.

    Two kinds of shuffle era exist. Stations built before eras existed
    (`chained`) work their passes out from eight passes before the epoch,
    exactly as they always have, so their schedule never changes. Newer eras
    start at `start_ms` with a first pass of `first_pass` (the programs that
    hadn't aired yet in the pass it took over from, plus new ones), shuffled
    to follow on from `tail`, what aired just before.
    """

    def __init__(
        self,
        items: list[Item],
        *,
        epoch_ms: int,
        seed: str,
        order_mode: str,
        start_ms: int | None = None,
        chained: bool = True,
        first_pass: list[str] | None = None,
        tail: list[tuple[str, str]] | None = None,
        era_id: int = 0,
        special: dict | None = None,
    ) -> None:
        self.items = items
        self.special = special  # (a marathon's: see marathons.py)
        self.epoch_ms = epoch_ms
        self.seed = seed
        self.order_mode = order_mode
        self.start_ms = start_ms
        self.chained = chained
        self.era_id = era_id
        self.total_ms = sum(i.duration_ms for i in items)
        self.shuffled = order_mode == "shuffle" and len(items) > 1
        pool0: list[Item] = []
        if first_pass:
            by_key = {i.rating_key: i for i in items}
            pool0 = [by_key[k] for k in first_pass if k in by_key]
        self.pool0 = pool0 or items
        self.first_ms = sum(i.duration_ms for i in self.pool0)
        self.tail = [_stub(k, show) for k, show in tail or []]
        self._passes: OrderedDict[int, tuple[list[Item], list[int]]] = OrderedDict()
        self._orders: OrderedDict[int, list[Item]] = OrderedDict()
        # Passes may be worked out ahead of time on another thread.
        self._lock = threading.Lock()

    @classmethod
    def from_era(cls, era: Era) -> EraSchedule:
        return cls(
            era.items,
            epoch_ms=era.epoch_ms,
            seed=era.seed,
            order_mode=era.order_mode,
            start_ms=era.start_ms,
            chained=era.chained,
            first_pass=era.first_pass,
            tail=era.tail,
            era_id=era.id,
            special=era.special,
        )

    @property
    def _passes_from_start(self) -> bool:
        return self.shuffled and not self.chained

    def _seed(self, cycle: int) -> str:
        return f"{self.seed}:{cycle}"

    def _pass_at(self, at_ms: int) -> tuple[int, int]:
        """The pass airing at `at_ms` and when that pass began."""
        if self._passes_from_start:
            assert self.start_ms is not None
            into = at_ms - self.start_ms
            if into < self.first_ms:
                return 0, self.start_ms
            cycle, _ = divmod(into - self.first_ms, self.total_ms)
            return cycle + 1, self.start_ms + self.first_ms + cycle * self.total_ms
        cycle, _ = divmod(at_ms - self.epoch_ms, self.total_ms)
        return cycle, self.epoch_ms + cycle * self.total_ms

    def _first_order(self, cycle: int) -> list[Item]:
        if self._passes_from_start:
            return shuffle_spread(
                self.pool0, random.Random(self._seed(0)), previous=self.tail or None
            )
        return shuffle_spread(self.items, random.Random(self._seed(cycle)))

    def _shuffled_pass(self, cycle: int) -> list[Item]:
        cached = self._orders.get(cycle)
        if cached is not None:
            return cached
        first = 0 if self._passes_from_start else _CHAIN_START
        if self._passes_from_start and cycle <= 0:
            order = self._first_order(0)
            self._remember(0, order)
            return order
        if cycle <= first:
            return self._first_order(cycle)
        known = [c for c in self._orders if c < cycle]
        from_cycle = max(known) if known else first
        order = self._orders.get(from_cycle) or self._first_order(from_cycle)
        if self._passes_from_start and from_cycle == 0:
            self._remember(0, order)
        for c in range(from_cycle + 1, cycle + 1):
            # A new era's first pass may be only a few programs long, so the
            # pass after it also looks back at what aired before the era.
            before = self.tail + order if self._passes_from_start and c == 1 else order
            order = shuffle_spread(self.items, random.Random(self._seed(c)), previous=before)
            self._remember(c, order)
        return order

    def _remember(self, cycle: int, order: list[Item]) -> None:
        self._orders[cycle] = order
        self._orders.move_to_end(cycle)
        # Keep recent passes, plus a checkpoint every _CHECKPOINT_EVERY.
        recent = [c for c in self._orders if c % _CHECKPOINT_EVERY != 0]
        while len(recent) > _CACHED_PASSES:
            del self._orders[recent.pop(0)]

    def pass_order(self, cycle: int) -> tuple[list[Item], list[int]]:
        """Programs in pass `cycle`, with their start offsets within it."""
        with self._lock:
            cached = self._passes.get(cycle)
            if cached is not None:
                self._passes.move_to_end(cycle)
                return cached
            order = _with_offsets(self._shuffled_pass(cycle)) if self.shuffled else self.items
            cached = (order, [i.start_ms for i in order])
            self._passes[cycle] = cached
            while len(self._passes) > _CACHED_PASSES:
                self._passes.popitem(last=False)
            return cached

    def locate(self, at_ms: int) -> Slot | None:
        """The slot airing at `at_ms`."""
        if not self.items or self.total_ms <= 0:
            return None
        if self.start_ms is not None and at_ms < self.start_ms:
            at_ms = self.start_ms
        cycle, pass_start = self._pass_at(at_ms)
        order, starts = self.pass_order(cycle)
        index = bisect.bisect_right(starts, at_ms - pass_start) - 1
        item = order[index]
        start = pass_start + item.start_ms
        return Slot(item, cycle, index, start, start + item.duration_ms, self.era_id)

    def after(self, slot: Slot) -> Slot:
        cycle, index = slot.cycle, slot.index + 1
        order, _ = self.pass_order(cycle)
        if index >= len(order):
            cycle, index = cycle + 1, 0
            order, _ = self.pass_order(cycle)
        item = order[index]
        return Slot(item, cycle, index, slot.end_ms, slot.end_ms + item.duration_ms, self.era_id)

    def before(self, slot: Slot) -> Slot | None:
        """The slot before `slot` in this era, or None at the era's start."""
        cycle, index = slot.cycle, slot.index - 1
        if index < 0:
            cycle -= 1
            if self._passes_from_start and cycle < 0:
                return None
            order, _ = self.pass_order(cycle)
            index = len(order) - 1
        else:
            order, _ = self.pass_order(cycle)
        item = order[index]
        start = slot.start_ms - item.duration_ms
        if self.start_ms is not None and start < self.start_ms:
            return None
        return Slot(item, cycle, index, start, slot.start_ms, self.era_id)

    def between(self, from_ms: int, to_ms: int) -> Iterator[Slot]:
        """Every slot overlapping [from_ms, to_ms), in order."""
        slot = self.locate(from_ms)
        while slot is not None and slot.start_ms < to_ms:
            yield slot
            slot = self.after(slot)


class StationSchedule:
    """What plays when on one station, across all of its eras."""

    def __init__(self, eras: list[EraSchedule]) -> None:
        self.eras = eras
        self._by_id = {e.era_id: n for n, e in enumerate(eras)}

    def _index_at(self, at_ms: int) -> int | None:
        found = None
        for n, era in enumerate(self.eras):
            if era.start_ms is None or era.start_ms <= at_ms:
                found = n
            else:
                break
        return found

    def _next_start(self, n: int) -> int | None:
        return self.eras[n + 1].start_ms if n + 1 < len(self.eras) else None

    def _within(self, slot: Slot | None, n: int) -> Slot | None:
        # Eras hand over at program breaks, so this only matters if one
        # somehow didn't: a program never runs into the next era.
        end = self._next_start(n)
        if slot is not None and end is not None and slot.end_ms > end:
            return replace(slot, end_ms=end)
        return slot

    def era_of(self, slot: Slot) -> EraSchedule:
        return self.eras[self._by_id.get(slot.era_id, len(self.eras) - 1)]

    def era_end(self, slot: Slot) -> int | None:
        """When the era `slot` airs in hands over to the next (None: it
        doesn't)."""
        n = self._by_id.get(slot.era_id)
        return self._next_start(n) if n is not None else None

    def special(self, slot: Slot) -> dict | None:
        """What's special about the era `slot` airs in (a marathon), if
        anything."""
        return self.era_of(slot).special

    def items_for(self, slot: Slot) -> list[Item]:
        """The programs of the era `slot` belongs to (replacements come from
        these): for a marathon's, the station's, from the era after it."""
        n = self._by_id.get(slot.era_id)
        if n is not None and self.eras[n].special and n + 1 < len(self.eras):
            return self.eras[n + 1].items
        return self.era_of(slot).items

    def locate(self, at_ms: int) -> Slot | None:
        """The slot airing at `at_ms`, or None before the station existed."""
        n = self._index_at(at_ms)
        if n is None:
            return None
        return self._within(self.eras[n].locate(at_ms), n)

    def after(self, slot: Slot) -> Slot | None:
        n = self._by_id.get(slot.era_id)
        if n is None:
            return self.locate(slot.end_ms)
        end = self._next_start(n)
        if end is not None and slot.end_ms >= end:
            return self._within(self.eras[n + 1].locate(end), n + 1)
        return self._within(self.eras[n].after(slot), n)

    def before(self, slot: Slot) -> Slot | None:
        n = self._by_id.get(slot.era_id)
        if n is None:
            return None
        earlier = self.eras[n].before(slot)
        if earlier is not None:
            return earlier
        start = self.eras[n].start_ms
        if n == 0 or start is None:
            return None
        return self._within(self.eras[n - 1].locate(start - 1), n - 1)

    def between(self, from_ms: int, to_ms: int) -> Iterator[Slot]:
        """Every slot overlapping [from_ms, to_ms), in order."""
        slot = self.locate(from_ms)
        if slot is None and self.eras and self.eras[0].start_ms is not None:
            slot = self.locate(max(from_ms, self.eras[0].start_ms))
        while slot is not None and slot.start_ms < to_ms:
            yield slot
            slot = self.after(slot)

    def next_break(self, at_ms: int) -> int:
        """The first program break at or after `at_ms`."""
        slot = self.locate(at_ms)
        if slot is None or slot.start_ms >= at_ms:
            return at_ms
        return slot.end_ms

    def recent(self, before_ms: int, count: int) -> list[Slot]:
        """Up to `count` slots that aired just before `before_ms`, oldest first."""
        out: list[Slot] = []
        slot = self.locate(before_ms - 1)
        while slot is not None and len(out) < count:
            out.append(slot)
            slot = self.before(slot)
        return out[::-1]


# How much of what aired before a new era its shuffle takes into account.
TAIL = 24


@dataclass
class EraPlan:
    """A new era, ready to be saved."""

    start_ms: int
    epoch_ms: int
    order_mode: str
    items: list[Item]
    first_pass: list[str] | None
    tail: list[tuple[str, str]]
    added: int
    removed: int


def plan_era(
    station: StationSchedule,
    at_ms: int,
    items: list[Item],
    order_mode: str,
    fresh: bool = False,
) -> EraPlan:
    """The era that takes over from `station` at `at_ms` (a program break)
    with the programs `items`.

    Unless `fresh`, it carries on from the station: in episode order it
    starts with the program that was due at `at_ms` (or the next one still
    on the station), and in shuffle it first finishes the pass that was in
    progress, playing the programs from that pass that haven't aired yet
    plus any new ones, before starting full passes.
    """
    playlist = build_playlist(items, order_mode)
    new_keys = {i.rating_key for i in playlist}
    slot = station.locate(at_ms)
    old = station.era_of(slot) if slot is not None else None
    old_keys = {i.rating_key for i in old.items} if old else set()
    added = len(new_keys - old_keys)
    removed = len(old_keys - new_keys)
    carry_on = not fresh and old is not None and slot is not None and old.order_mode == order_mode

    if order_mode == "rotate":
        offset = 0
        if carry_on and slot is not None:
            position = {i.rating_key: i.start_ms for i in playlist}
            due: Slot | None = slot
            for _ in range(len(old.items) if old else 0):
                if due is None:
                    break
                if due.item.rating_key in position:
                    offset = position[due.item.rating_key]
                    break
                due = station.after(due)
        return EraPlan(at_ms, at_ms - offset, order_mode, playlist, None, [], added, removed)

    tail = [(s.item.rating_key, show_key(s.item)) for s in station.recent(at_ms, TAIL)]
    first_pass: list[str] | None = None
    if carry_on and old is not None and slot is not None and old.shuffled:
        in_progress, _ = old.pass_order(slot.cycle)
        not_yet = {i.rating_key for i in in_progress[slot.index :]} & new_keys
        new = [i for i in playlist if i.rating_key not in old_keys]
        first_pass = sorted(not_yet | {i.rating_key for i in _spreadable(playlist, not_yet, new)})
        by_key = {i.rating_key: i for i in playlist}
        if not _can_spread([by_key[k] for k in first_pass], [show for _, show in tail]):
            # Removed programs can leave the rest of the pass impossible to
            # spread out (two episodes of a show that were kept apart by
            # one that's gone). A full pass can always be spread out.
            first_pass = []
    return EraPlan(at_ms, at_ms, order_mode, playlist, first_pass or None, tail, added, removed)


def _can_spread(items: list[Item], before: list[str]) -> bool:
    """Whether `items` can play with no show more than MAX_IN_A_ROW times in
    a row, following programs of the shows in `before`."""
    counts = Counter(show_key(item) for item in items)
    if not counts:
        return True
    biggest = max(counts, key=lambda k: counts[k])
    run = 0
    for show in reversed(before):
        if show != biggest:
            break
        run += 1
    others = len(items) - counts[biggest]
    return counts[biggest] <= MAX_IN_A_ROW * (others + 1) - run


def _spreadable(playlist: list[Item], not_yet: set[str], new: list[Item]) -> list[Item]:
    """The new programs that can join the pass in progress without one show
    swamping it. Say 23 new episodes of one show arrive near the end of a
    pass: squeezing them all in would mean that show three or more times in
    a row, so only as many as can be spread out join now (earliest episodes
    first) and the rest join from the next full pass."""
    by_key = {i.rating_key: i for i in playlist}
    counts = Counter(show_key(by_key[key]) for key in not_yet)
    joining: list[Item] = []
    new_by_show: dict[str, list[Item]] = {}
    for item in sorted(new, key=lambda i: (i.season or 0, i.episode or 0, i.rating_key)):
        new_by_show.setdefault(show_key(item), []).append(item)
    # Add new programs one per show at a time, as long as no show ends up
    # with more than MAX_IN_A_ROW times all the others put together.
    taken = dict.fromkeys(new_by_show, 0)
    total = sum(counts.values())
    while True:
        added_any = False
        for key, items in new_by_show.items():
            n = taken[key]
            if n == len(items):
                continue
            mine = counts.get(key, 0) + 1
            if mine > MAX_IN_A_ROW * (total + 1 - mine):
                continue
            counts[key] = mine
            total += 1
            joining.append(items[n])
            taken[key] = n + 1
            added_any = True
        if not added_any:
            return joining


# Schedules are cached per era: an era never changes once saved, and a
# shuffled era's passes are worth keeping.
_era_schedules: dict[int, EraSchedule] = {}


def station_schedule(eras: list[Era]) -> StationSchedule:
    schedules = []
    for era in eras:
        cached = _era_schedules.get(era.id)
        if cached is None or cached.items is not era.items:
            cached = _era_schedules[era.id] = EraSchedule.from_era(era)
        schedules.append(cached)
    return StationSchedule(schedules)


def forget_eras(era_ids: list[int]) -> None:
    for era_id in era_ids:
        _era_schedules.pop(era_id, None)


def prepare(station: StationSchedule, from_ms: int, to_ms: int) -> None:
    """Works out everything airing between `from_ms` and `to_ms` ahead of
    time. On a big shuffled station that takes a few seconds, so it's done
    on a worker thread rather than while a stream or a web page waits."""
    for _ in station.between(from_ms, to_ms):
        pass
