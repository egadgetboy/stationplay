"""Keeping stations up to date with Plex without contradicting a guide.

When Plex gains episodes for a show on a station, or loses some, or a new
movie matches a station's filter, or Plex finds a program's intro or credits
on a station that skips them, the station should follow. But Plex keeps
its own copy of the guide, downloaded about once a day, and changing what
airs during the stretch that copy covers would make it wrong.

So an update never changes anything already in a guide. Every hour
StationPlay asks Plex whether anything changed (skipping the work when no
library has changed) and gets the updated station ready. It then takes over
at the next program break after a moment when no guide could disagree:

  * when Plex downloads the guide, the update is applied just before the
    guide is generated, starting at a break a minute or more later, so the
    guide Plex receives already shows it. StationPlay asks Plex to reload
    its guide when it has an update ready, so this usually happens within
    the hour;
  * if Plex hasn't downloaded the guide for over a day (Live TV not set up,
    or Plex down), the update starts after the end of the last guide handed
    out to anyone.

Changes you make yourself (editing a station, Update now, Reshuffle) take
effect at the next break at least a minute away; StationPlay then asks Plex
to reload its guide straight away.

An update that would take away more than half of a station's programs is
held until you apply it yourself: that's more likely a Plex hiccup (a
library mid-rescan, a drive offline) than something you meant.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import specials
from .breaks import COMMERCIALS, TRAILERS, id_card_ms, with_breaks
from .db import Channel, Era, Item
from .library import LibraryError
from .plex import PlexError, gather_all
from .schedule import (
    StationSchedule,
    build_playlist,
    forget_eras,
    plan_era,
    prepare,
    station_schedule,
)

if TYPE_CHECKING:
    from .main import AppContext

log = logging.getLogger(__name__)

# What StationPlay's guide covers: the last two hours and the next two days.
# Plex re-reads the guide about once a day (its "Guide refresh time"), so
# the file covers two days; a shorter one would leave Plex's grid empty for
# part of each day.
GUIDE_PAST_MS = 2 * 3600 * 1000
GUIDE_FUTURE_MS = 48 * 3600 * 1000
# A change never starts sooner than this from when it's made, so it can't
# collide with a program a station has already started sending.
MARGIN_MS = 60 * 1000
# Plex downloads the guide daily; after this long without a download,
# updates wait for the last guide handed out to run out instead.
GUIDE_EXPECTED_MS = 26 * 3600 * 1000
CHECK_INTERVAL_S = 3600
FIRST_CHECK_DELAY_S = 60
# Stations are re-checked this often even if Plex's libraries look unchanged.
FULL_CHECK_MS = 6 * 3600 * 1000
# Eras that ended longer ago than this are deleted.
KEEP_PAST_MS = GUIDE_PAST_MS + 3600 * 1000
# Updates removing more than this share of a station's programs (or of the
# programs whose intro and credits it skips) are held.
HOLD_FRACTION = 0.5
HOLD_MIN_PROGRAMS = 10
# StationPlay asks Plex to reload its guide at most this often on its own.
RELOAD_EVERY_MS = 30 * 60 * 1000
# A guide download this soon after asking Plex for one is Plex's.
ASKED_WINDOW_MS = 3 * 60 * 1000
DVR_RECHECK_MS = 3600 * 1000
# Looked for again sooner if Plex has no DVR for StationPlay yet.
DVR_MISSING_RECHECK_MS = 5 * 60 * 1000

META_PUBLISHED_UNTIL = "guide_published_until"
META_PLEX_DOWNLOAD = "guide_plex_download"


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class PendingUpdate:
    items: list[Item]
    added: int
    removed: int
    found_ms: int
    held: bool
    # Programs whose intro and credits would no longer be skipped.
    lost_skips: int = 0
    # The programs its Feature Presentation and blocks draw on, if those
    # changed (see specials.py).
    sets: dict[str, list[Item]] | None = None

    @property
    def summary(self) -> str:
        """What it changes, for the log."""
        parts = [f"{self.added} added, {self.removed} removed"]
        if self.lost_skips:
            parts.append(f"intros and credits no longer skipped in {self.lost_skips}")
        if self.sets is not None:
            parts.append("its Feature Presentation or blocks changed")
        out = ", ".join(parts)
        return out + (
            ", held until you choose Update now because it changes so much at once"
            if self.held
            else ""
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "removed": self.removed,
            "foundAt": self.found_ms,
            "held": self.held,
            "lostSkips": self.lost_skips,
            "specials": self.sets is not None,
        }


def dedupe(items: list[Item]) -> list[Item]:
    """Each program once, even when overlapping Plex libraries list the same
    file under two different entries."""
    keys: set[str] = set()
    files: set[str] = set()
    out = []
    for item in items:
        if item.rating_key in keys or (item.file_path and item.file_path in files):
            continue
        keys.add(item.rating_key)
        if item.file_path:
            files.add(item.file_path)
        out.append(item)
    return out


# Lengths (and skipped parts) that differ by no more than this are the same.
SAME_WITHIN_MS = 2000


def compare(old: list[Item], new: list[Item]) -> tuple[int, int, bool]:
    """(programs added, programs removed, whether anything changed). A
    program whose length changed counts as a change, as does one whose
    skipped intro or credits moved, appeared or went, or one followed by
    different commercials or trailers; and one Plex has under a new key (a
    show or movie it added again), though it's still the same program."""
    before = {i.rating_key: i for i in old}
    after = {i.rating_key: i for i in new}
    kept = pair_up(old, new)
    added = len(after) - len(kept)
    removed = len(before) - len(kept)
    altered = any(a.rating_key != b.rating_key or _differs(a, b) for a, b in kept)
    return added, removed, bool(added or removed or altered)


def pair_up(old: list[Item], new: list[Item]) -> list[tuple[Item, Item]]:
    """Each program in both `old` and `new`, as (old, new). Matched by Plex's
    rating key; or, when Plex added a show or movie again and gave it new
    keys, by the show, season and episode (a movie by its title and year),
    where that leaves no doubt."""
    before = {i.rating_key: i for i in old}
    after = {i.rating_key: i for i in new}
    pairs = [(before[k], after[k]) for k in before.keys() & after.keys()]
    gone = _by_program([i for k, i in before.items() if k not in after])
    came = _by_program([i for k, i in after.items() if k not in before])
    pairs += [(gone[p], came[p]) for p in gone.keys() & came.keys()]
    return pairs


def _by_program(items: list[Item]) -> dict[tuple, Item]:
    """Items by which program they are (an episode by its show, season and
    number; a movie by its title and year), leaving out any that can't be
    told apart that way."""
    counts = Counter(_program(i) for i in items)
    return {p: i for i in items if (p := _program(i)) is not None and counts[p] == 1}


def _program(item: Item) -> tuple | None:
    if item.kind == "episode" and item.show_title and None not in (item.season, item.episode):
        return ("episode", item.show_title.casefold(), item.season, item.episode)
    if item.kind == "movie" and item.title:
        return ("movie", item.title.casefold(), item.year)
    return None


def _differs(a: Item, b: Item) -> bool:
    """Whether a program's length, what's skipped in it, or what follows it
    changed."""
    sa, sb = a.segments or (), b.segments or ()
    return (
        abs(a.duration_ms - b.duration_ms) > SAME_WITHIN_MS
        or [f for f, _ in a.breaks or ()] != [f for f, _ in b.breaks or ()]
        or len(sa) != len(sb)
        or any(
            abs(x - y) > SAME_WITHIN_MS
            for pa, pb in zip(sa, sb, strict=True)
            for x, y in zip(pa, pb, strict=True)
        )
    )


def _described(device: dict[str, Any]) -> str:
    """A tuner as Plex lists it: which tuner it is (Plex's name for it holds
    the tuner's DeviceID), where Plex looks for it, and whether it's there."""
    out = str(device.get("uuid") or device.get("deviceIdentifier") or "a tuner")
    if device.get("uri"):
        out += f" at {device['uri']}"
    if device.get("status"):
        out += f" ({device['status']})"
    return out


def from_plex(user_agent: str) -> bool:
    return "plex" in (user_agent or "").lower()


class Updater:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.pending: dict[int, PendingUpdate] = {}
        self.last_check_ms = 0
        self._lock = asyncio.Lock()
        self._fingerprint = ""
        self._last_full_ms = 0
        self._asked_ms = 0
        self._dvr_key: str | None = None
        self._dvr_checked_ms = 0
        self._dvr_said = ""
        self._agents_seen: set[str] = set()
        # Bumped whenever a station's schedule changes, so a check of Plex
        # that was already under way can tell its answer is out of date.
        self._versions: dict[int, int] = {}

    def _changed(self, channel_id: int) -> None:
        self._versions[channel_id] = self._versions.get(channel_id, 0) + 1

    # The station's schedule ----------------------------------------------

    def station(self, channel_id: int) -> StationSchedule:
        return station_schedule(self.ctx.db.eras(channel_id))

    async def gather(self, sources: list[dict], skip_intros: bool = False) -> list[Item]:
        """Every program `sources` stand for in Plex right now; with
        `skip_intros`, as they air without their intros and credits."""
        batches = await gather_all(self.ctx.library.items_for_source(s) for s in sources)
        items = dedupe([i for batch in batches for i in batch])
        # (Their ratings, for who can see the station: see titles.py.)
        self.ctx.titles.note(items)
        self.ctx.titles.fill_soon(self.ask_about_titles)
        if skip_intros:
            items = await self.ctx.markers.trim(items)
        return items

    async def ask_about_titles(self, keys: list[str]) -> dict[str, tuple[str, str]]:
        """Shows' and movies' ratings and libraries, as Plex has them now."""
        return {e.key: (e.content_rating, e.library) for e in await self.ctx.library.entries(keys)}

    def with_breaks(self, channel: Channel, items: list[Item]) -> list[Item]:
        """`items` with the station's commercials or trailers, and Station
        ID card, after each."""
        fillers = self.ctx.fillers
        return with_breaks(
            items,
            channel.breaks,
            id_card_ms(channel),
            fillers.pool(COMMERCIALS),
            fillers.pool(TRAILERS),
            seed=str(channel.id),
        )

    async def gather_for(self, channel: Channel) -> list[Item]:
        """Every program on `channel` as Plex has them right now, as they'd
        air there."""
        items = await self.gather(channel.sources, channel.skip_intros)
        if channel.breaks:
            await self.ctx.fillers.ready()
        return self.with_breaks(channel, items)

    async def gather_sets(self, channel: Channel) -> dict[str, list[Item]]:
        """The programs `channel`'s Feature Presentation (from a library or
        collection) and blocks draw on, as Plex has them right now, as
        they'd air there."""
        return await self.sets_as_aired(channel, await self.gather_set_programs(channel))

    async def sets_as_aired(
        self, channel: Channel, sets: dict[str, list[Item]]
    ) -> dict[str, list[Item]]:
        """`sets` with the station's commercials or trailers, and Station ID
        card, after each program."""
        if channel.breaks and sets:
            await self.ctx.fillers.ready()
        return {name: self.with_breaks(channel, items) for name, items in sets.items()}

    async def gather_set_programs(self, channel: Channel) -> dict[str, list[Item]]:
        """The programs `channel`'s Feature Presentation (from a library or
        collection) and blocks draw on, as Plex has them right now (as
        they'd air there, but for the breaks after each)."""
        wanted: dict[str, list[dict]] = {}
        if channel.feature_mode == "on" and channel.feature_source:
            wanted[specials.FEATURE] = [channel.feature_source]
        for block in channel.blocks:
            wanted[specials.set_name(specials.BLOCK, str(block.get("id", "")))] = list(
                block.get("sources") or []
            )
        found = await gather_all(
            self.gather(sources, channel.skip_intros) for sources in wanted.values()
        )
        return {
            name: [i for i in items if i.kind == "movie"] if name == specials.FEATURE else items
            for name, items in zip(wanted, found, strict=True)
        }

    def sets_changed(self, channel_id: int, sets: dict[str, list[Item]]) -> bool:
        db = self.ctx.db
        if set(db.program_set_names(channel_id)) != set(sets):
            return True
        return any(compare(db.program_set(channel_id, n), items)[2] for n, items in sets.items())

    async def create(
        self,
        channel_id: int,
        items: list[Item],
        order_mode: str,
        sets: dict[str, list[Item]] | None = None,
    ) -> None:
        """A new station's first era, starting now (and the programs its
        specials draw on, `sets`)."""

        def work() -> None:
            now = now_ms()
            self.ctx.db.save_program_sets(channel_id, sets or {})
            playlist = build_playlist(items, order_mode)
            self.ctx.db.add_era(
                channel_id,
                playlist,
                start_ms=now,
                epoch_ms=now,
                seed=f"{channel_id}:{now}",
                order_mode=order_mode,
                created_ms=now,
                reason="created",
                added=len(playlist),
            )
            self._plan_specials(channel_id, now + MARGIN_MS)
            prepare(self.station(channel_id), now, now + GUIDE_FUTURE_MS)

        async with self._lock:
            await asyncio.to_thread(work)
            self._changed(channel_id)

    async def apply(
        self,
        channel_id: int,
        items: list[Item],
        *,
        not_before_ms: int,
        reason: str,
        fresh: bool = False,
        update: PendingUpdate | None = None,
        sets: dict[str, list[Item]] | None = None,
    ) -> Era | None:
        """Starts a new era with `items` at the first program break at or
        after `not_before_ms` (and at least MARGIN_MS from now), with its
        specials planned again after it (from the programs in `sets`, if
        given). Worked out on a worker thread: for a big shuffled station
        that takes a moment. `update` is the pending update being applied,
        if it is one."""
        async with self._lock:
            if update is not None and self.pending.get(channel_id) is not update:
                # Replaced or dropped while waiting (say, you edited the
                # station): applying it now would undo the newer change.
                return None
            era = await asyncio.to_thread(
                self._apply, channel_id, items, not_before_ms, reason, fresh, sets
            )
            self._changed(channel_id)
        if update is None or self.pending.get(channel_id) is update:
            self.pending.pop(channel_id, None)
        return era

    def _apply(
        self,
        channel_id: int,
        items: list[Item],
        not_before_ms: int,
        reason: str,
        fresh: bool,
        sets: dict[str, list[Item]] | None,
    ) -> Era | None:
        db = self.ctx.db
        channel = db.get_channel(channel_id)
        if channel is None or not items:
            return None
        if (
            reason == "update"
            and not compare(db.latest_items(channel_id), items)[2]
            and (sets is None or not self.sets_changed(channel_id, sets))
        ):
            return None  # already applied
        now = now_ms()
        at = max(not_before_ms, now + MARGIN_MS)
        eras = db.eras(channel_id)
        # A special under way by then finishes first.
        whole = station_schedule(eras)
        airing = whole.locate(at)
        if airing is not None and whole.special(airing):
            at = max(at, whole.era_end(airing) or at)
        # Eras due to start after this point haven't aired, and weren't in
        # any guide this change has to respect: this change replaces them
        # (specials included: they're planned again after it).
        unaired = [e.id for e in eras if e.start_ms is not None and e.start_ms > at]
        cancelled = [
            (str(e.special.get("kind")), int(e.special["due"]))
            for e in eras
            if e.id in unaired and e.special and isinstance(e.special.get("due"), int)
        ]
        base = [e for e in eras if e.id not in unaired]
        if base and base[-1].start_ms is not None:
            # Always after the newest remaining era has begun.
            at = max(at, base[-1].start_ms + 1)
        station = station_schedule(base)
        start = station.next_break(at)
        plan = plan_era(station, start, items, channel.order_mode, fresh=fresh)
        db.delete_eras(channel_id, unaired)
        forget_eras(unaired)
        db.forget_marathons(
            channel_id, [due for kind, due in cancelled if kind == specials.MARATHON]
        )
        db.forget_specials(channel_id, [(k, due) for k, due in cancelled if k != specials.MARATHON])
        if sets is not None:
            db.save_program_sets(channel_id, sets)
        era = db.add_era(
            channel_id,
            plan.items,
            start_ms=plan.start_ms,
            epoch_ms=plan.epoch_ms,
            seed=f"{channel_id}:{now}:{len(eras)}",
            order_mode=plan.order_mode,
            created_ms=now,
            reason=reason,
            first_pass=plan.first_pass,
            tail=plan.tail,
            added=plan.added,
            removed=plan.removed,
        )
        # (A special due as the change starts can start with it, and the
        # change follows it.)
        self._plan_specials(channel_id, plan.start_ms)
        self._prune(channel_id, now)
        prepare(self.station(channel_id), now, now + GUIDE_FUTURE_MS)
        log.info(
            "Station %s: %s (%d added, %d removed), starting %s",
            channel.number,
            {"update": "updated from Plex", "reshuffle": "reshuffled"}.get(reason, "changed"),
            plan.added,
            plan.removed,
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(plan.start_ms / 1000)),
        )
        return era

    def _plan_specials(self, channel_id: int, earliest_ms: int) -> int:
        """Plans the station's specials due from `earliest_ms` on (see
        specials.py). Never lets a problem with them stop anything else."""
        channel = self.ctx.db.get_channel(channel_id)
        if channel is None or not specials.has_specials(channel):
            return 0
        try:
            return specials.plan(
                self.ctx.db, channel, self.ctx.broken.keys(), earliest_ms, now_ms()
            )
        except Exception:
            log.exception("Planning station %s's specials failed", channel.number)
            return 0

    async def plan_all_specials(self) -> None:
        """Plans every station's specials as far ahead as they go, after the
        guide already handed out (so it never has to change)."""
        for channel in self.ctx.db.list_channels():
            if not specials.has_specials(channel):
                continue
            async with self._lock:
                earliest = max(self.published_until_ms, now_ms() + MARGIN_MS)
                if await asyncio.to_thread(self._plan_specials, channel.id, earliest):
                    self._changed(channel.id)

    def _prune(self, channel_id: int, now: int) -> None:
        eras = self.ctx.db.eras(channel_id)
        old = [
            era.id
            for era, following in itertools.pairwise(eras)
            if following.start_ms is not None and following.start_ms < now - KEEP_PAST_MS
        ]
        if old:
            self.ctx.db.delete_eras(channel_id, old)
            forget_eras(old)

    # Checking Plex for changes ---------------------------------------------

    async def check_station(self, channel_id: int) -> PendingUpdate | None:
        """What would change on the station if it followed Plex now."""
        channel = self.ctx.db.get_channel(channel_id)
        if channel is None:
            return None
        items = await self.gather_for(channel)
        sets = await self.gather_sets(channel)
        current = self.ctx.db.latest_items(channel_id)
        added, removed, changed = compare(current, items)
        sets_changed = self.sets_changed(channel_id, sets)
        if not changed and not sets_changed:
            return None
        # Plex losing most of a station's programs, or most of its intros and
        # credits, at once is more likely a hiccup (a library mid-rescan, a
        # drive offline, markers being redone) than anything real.
        skipping = sum(1 for i in current if i.segments)
        # Programs still on the station that would no longer skip anything.
        lost_skips = sum(1 for a, b in pair_up(current, items) if a.segments and not b.segments)
        held = (
            not items
            or (len(current) >= HOLD_MIN_PROGRAMS and removed > HOLD_FRACTION * len(current))
            or (skipping >= HOLD_MIN_PROGRAMS and lost_skips > HOLD_FRACTION * skipping)
            or (sets_changed and self._sets_shrink(channel_id, sets))
        )
        return PendingUpdate(
            items, added, removed, now_ms(), held, lost_skips, sets if sets_changed else None
        )

    def _sets_shrink(self, channel_id: int, sets: dict[str, list[Item]]) -> bool:
        """Whether a block or Feature Presentation would lose all its
        programs, or most of a good many: more likely a Plex hiccup."""
        for name, items in sets.items():
            before = self.ctx.db.program_set(channel_id, name)
            removed = compare(before, items)[1]
            if before and (
                not items
                or (len(before) >= HOLD_MIN_PROGRAMS and removed > HOLD_FRACTION * len(before))
            ):
                return True
        return False

    async def _collections_fingerprint(self) -> str:
        """What's in the collections stations follow: what's in a collection
        can change while its library doesn't. (If Plex can't say right now,
        the stations are checked anyway.)"""
        sources = [
            source
            for channel in self.ctx.db.list_channels()
            for source in [
                *channel.sources,
                *(s for block in channel.blocks for s in block.get("sources") or []),
                *([channel.feature_source] if channel.feature_mode == "on" else []),
            ]
            if source.get("type") == "collection"
        ]
        if not sources:
            return ""
        try:
            found = await self.ctx.library.collections()
        except LibraryError as e:
            log.info("Can't ask Plex about its collections right now (%s)", e)
            return f"|collections unknown at {now_ms()}"
        followed = (self.ctx.library.followed_collection(source, found) for source in sources)
        return "|" + ",".join(
            sorted({f"{c['ratingKey']}:{c['updatedAt']}:{c['count']}" for c in followed if c})
        )

    async def check(self, force: bool = False) -> None:
        """Looks for changes on every station, unless no library (and no
        commercial or trailer) changed."""
        if not self.ctx.library.configured:
            return
        try:
            fingerprint = await self.ctx.library.fingerprint()
        except LibraryError as e:
            log.info("Can't check Plex for new episodes right now (%s)", e)
            return
        fingerprint += await self._collections_fingerprint()
        # New or removed commercials and trailers count as a change too.
        fingerprint += "|" + self.ctx.fillers.signature
        now = now_ms()
        if (
            not force
            and fingerprint == self._fingerprint
            and now - self._last_full_ms < FULL_CHECK_MS
        ):
            return
        failed = False
        for channel in self.ctx.db.list_channels():
            version = self._versions.get(channel.id, 0)
            try:
                update = await self.check_station(channel.id)
            except LibraryError as e:
                failed = True
                log.info("Can't check station %s against Plex (%s)", channel.number, e)
                continue
            except Exception:
                failed = True
                log.exception("Checking station %s against Plex failed", channel.number)
                continue
            if self._versions.get(channel.id, 0) != version:
                continue  # it changed while Plex was being asked; the next check sees it
            previous = self.pending.get(channel.id)
            if update is None:
                self.pending.pop(channel.id, None)
                continue
            self.pending[channel.id] = update
            if previous is None or previous.summary != update.summary:
                log.info("Station %s has an update from Plex (%s)", channel.number, update.summary)
        self.last_check_ms = now
        if not failed:
            self._fingerprint = fingerprint
            self._last_full_ms = now
        if (
            any(not u.held for u in self.pending.values())
            and now - self._asked_ms > RELOAD_EVERY_MS
        ):
            await self.ask_plex_to_reload_guide()

    # When updates take over ------------------------------------------------

    async def before_guide(self, user_agent: str, plex_address: bool = True) -> bool:
        """Called just before a guide is generated for someone. A download
        of the address given to Plex, by Plex, applies pending updates, so
        the guide Plex receives already shows them. Returns whether it was
        Plex."""
        now = now_ms()
        by_plex = plex_address and (from_plex(user_agent) or now - self._asked_ms < ASKED_WINDOW_MS)
        # What each app calls itself is said the first time it's seen.
        first = user_agent not in self._agents_seen and len(self._agents_seen) < 20
        if first:
            self._agents_seen.add(user_agent)
        if by_plex:
            log.info(
                "Plex downloaded the guide%s", f" (user agent {user_agent!r})" if first else ""
            )
            await self._apply_pending(now_ms)
        elif first:
            log.info("Guide downloaded by %r (not Plex)", user_agent)
        return by_plex

    def after_guide(self, until_ms: int, by_plex: bool) -> None:
        """Called once a guide covering up to `until_ms` has been handed out."""
        if by_plex:
            self.ctx.db.set_meta(META_PLEX_DOWNLOAD, str(now_ms()))
        published = max(self.published_until_ms, until_ms)
        self.ctx.db.set_meta(META_PUBLISHED_UNTIL, str(published))

    async def _apply_pending(self, not_before) -> None:
        """Applies every pending update that isn't held. `not_before` gives
        the earliest start for each, worked out as each is applied."""
        for channel_id, update in list(self.pending.items()):
            if update.held:
                continue
            try:
                await self.apply(
                    channel_id,
                    update.items,
                    not_before_ms=not_before(),
                    reason="update",
                    update=update,
                    sets=update.sets,
                )
            except Exception:
                # One station's trouble mustn't hold up the others, or the guide.
                log.exception("Couldn't apply the update for station id %s", channel_id)

    @property
    def published_until_ms(self) -> int:
        return int(self.ctx.db.get_meta(META_PUBLISHED_UNTIL, "0") or 0)

    @property
    def plex_download_ms(self) -> int:
        return int(self.ctx.db.get_meta(META_PLEX_DOWNLOAD, "0") or 0)

    async def apply_overdue(self) -> None:
        """Updates Plex hasn't come for: they start once the last guide
        handed out has run out."""
        if now_ms() - self.plex_download_ms < GUIDE_EXPECTED_MS:
            return
        await self._apply_pending(lambda: max(self.published_until_ms, now_ms() + MARGIN_MS))

    def prune_all(self) -> None:
        now = now_ms()
        for channel in self.ctx.db.list_channels():
            self._prune(channel.id, now)
        self.ctx.markers.forget_old()

    async def run_forever(self) -> None:
        await asyncio.sleep(FIRST_CHECK_DELAY_S)
        while True:
            try:
                await self.ctx.fillers.refresh()
                await self.check()
                await self.apply_overdue()
                await self.plan_all_specials()
                self.prune_all()
            except Exception:
                log.exception("Checking Plex for updates failed")
            await asyncio.sleep(CHECK_INTERVAL_S)

    # Asking Plex to reload its guide ----------------------------------------

    async def find_dvr(self) -> str | None:
        """Plex's DVR that uses this StationPlay, if there is one."""
        now = now_ms()
        recheck = DVR_RECHECK_MS if self._dvr_key else DVR_MISSING_RECHECK_MS
        if now - self._dvr_checked_ms < recheck:
            return self._dvr_key
        try:
            dvrs = await self.ctx.plex.dvrs()
        except PlexError as e:
            # Keep what was known; look again in a minute.
            self._dvr_checked_ms = now - recheck + 60_000
            self._say_once(f"Can't ask Plex about its Live TV & DVR ({e})")
            return self._dvr_key
        devices = [(dvr, d) for dvr in dvrs for d in dvr.get("Device") or []]
        mine = [(dvr, d) for dvr, d in devices if dvr.get("key") and self._is_mine(d)]
        self._dvr_key = str(mine[0][0]["key"]) if mine else None
        self._dvr_checked_ms = now_ms()
        if mine and mine[0][1].get("status", "alive") == "alive":
            self._say_once(
                "Found StationPlay's tuner in Plex's Live TV & DVR, so StationPlay will ask Plex "
                "to refresh its guide when a station changes"
            )
        elif mine:
            self._say_once(
                f"Plex's Live TV & DVR has StationPlay's tuner but can't reach it (Plex lists "
                f"{_described(mine[0][1])})"
            )
        else:
            listed = "; ".join(_described(d) for _, d in devices) or "none"
            self._say_once(
                f"Plex's Live TV & DVR doesn't list StationPlay's tuner ({self.ctx.device_id}). "
                f"Plex lists {listed}. Until it does, refresh the guide in Plex yourself after "
                "you change a station"
            )
        return self._dvr_key

    def _is_mine(self, device: dict[str, Any]) -> bool:
        """Whether a tuner in Plex's Live TV & DVR is this StationPlay. Plex
        knows a tuner by the DeviceID it gave, in the tuner's uuid
        ("device://tv.plex.grabbers.hdhomerun/<DeviceID>")."""
        wanted = self.ctx.device_id.lower()
        uuid = str(device.get("uuid") or "").lower()
        return uuid.rsplit("/", 1)[-1] == wanted or (
            str(device.get("deviceIdentifier") or "").lower() == wanted
        )

    def _say_once(self, message: str) -> None:
        """Logs what StationPlay found out about Plex's Live TV & DVR, when
        that's not what it found last time."""
        if message != self._dvr_said:
            self._dvr_said = message
            log.info("%s", message)

    async def ask_plex_to_reload_guide(self) -> bool:
        """Presses Plex's "Refresh Guide", so Plex downloads the guide (and
        with it any updates) now rather than at its daily refresh."""
        dvr = await self.find_dvr()
        if dvr is None:
            return False
        try:
            await self.ctx.plex.reload_guide(dvr)
        except PlexError as e:
            log.info("Couldn't ask Plex to reload its guide (%s)", e)
            self._dvr_checked_ms = 0
            return False
        self._asked_ms = now_ms()
        log.info("Asked Plex to reload its guide")
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "lastCheck": self.last_check_ms,
            "plexDownloadedGuide": self.plex_download_ms,
            "publishedUntil": self.published_until_ms,
            "canRefreshPlexGuide": self._dvr_key is not None,
        }
