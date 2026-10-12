"""The rating, library and tags of what's on each station, and of what
Media shows people with limits (see docs/users.md).

Whether a user sees a station depends on everything it plays, so the rating
and library of each show and movie on a station is kept here (the `titles`
table, mirrored in memory). They're noted whenever a station's programs are
gathered from Plex (Updater.gather): a movie's rating comes with it, as does
an episode's own, when it has one. A show's rating comes only by asking Plex
about the show itself, and so do a show's or movie's tags (from 1.33.0: all
its genres, its labels, the collections it's in and its studio, whole, which
lists don't give); that's done soon after (`fill`), in batches, and again
every week in case Plex's changed (every day for tags, while someone is
limited by them, and at once when what's hidden changes). Media asks for the
tags of what it shows someone a level or a person limits by them, as it goes
(`ensure`): 50 titles at a time, each batch kept as it comes, a couple of
batches at once, waiting only a few seconds before answering (the rest stay
hidden until Plex has said, a moment later).

What isn't known yet counts as not allowed: a station with a show whose
rating hasn't been asked for is hidden from anyone with a limit until it is,
and one whose tags haven't been from anyone limited by tags.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass, field

from . import ratings
from .catalog import Tags
from .db import Database, Item

log = logging.getLogger("stationplay.titles")

# When the Media answer being made must stop waiting for Plex about tags (the
# event loop's time; set by applibrary.py for each answer, so the asks of one
# answer share ENSURE_S, and never run past its own deadline).
ensure_until: ContextVar[float | None] = ContextVar("ensure_until", default=None)

MOVIE, SHOW, EPISODE = "movie", "show", "episode"
RECHECK_MS = 7 * 86_400_000  # how often Plex is asked about a title again
TAGS_RECHECK_MS = 86_400_000  # ...and for its tags, while someone is limited by them
FILL_AT_ONCE = 200  # titles asked about in one go (Plex is asked 50 at a time)
META_REFRESH = "tags_refresh_ms"  # (when every title's tags were last wanted again)
ENSURE_AT_ONCE = 50  # Media's titles asked about in one batch
ENSURE_TURNS = 2  # Media's batches asked about at once
ENSURE_AHEAD = 4  # of one ask's batches, those asked about at once; the rest wait their turn
ENSURE_S = 3.0  # how long one Media answer waits for Plex about tags, in all
ABSENT_MS = 3_600_000  # a title Plex didn't have isn't asked about again for this long
SAY_EVERY_S = 60.0  # (Plex not answering Media is logged at most this often)


@dataclass(frozen=True)
class Title:
    kind: str
    rating: str
    library: str
    checked_ms: int = 0
    tags: Tags | None = None  # (a show's or movie's; None: not asked for yet)


@dataclass(frozen=True)
class Judged:
    """A program as limits see it: TV or a movie, its age (None: unrated),
    its library ("" if unknown), and whether its rating is known yet; and
    (from 1.33.0) the show or movie it is (an episode's show) and its tags
    (None: not known yet)."""

    tv: bool
    age: int | None
    library: str
    known: bool
    # (What it is: compared by what limits decide from, not by these, as
    # before 1.33.0.)
    key: str = field(default="", compare=False)
    tags: Tags | None = field(default=None, compare=False)


# Asks Plex about shows and movies: their keys → (rating, library, tags) for
# each Plex has (a key Plex doesn't have is left out).
Asker = Callable[[list[str]], Awaitable[dict[str, tuple[str, str, Tags | None]]]]


class Titles:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._known: dict[str, Title] = {
            r["key"]: Title(
                r["kind"], r["rating"], r["library"], r["checked_ms"], Tags.from_json(r["tags"])
            )
            for r in db.titles()
        }
        # What asks Plex (Updater.ask_about_titles), for Media's `ensure`.
        self.asker: Asker | None = None
        # Whether any level or person hides by tags (Viewing says): only then
        # are titles asked about for theirs. Titles kept without tags are
        # asked about once from when that began (or tapiOca started).
        self._want_tags = False
        self._tags_since_ms = _now()
        # (refresh_tags: every title asked about again since then; kept, so
        # a restart before it's done doesn't forget it.)
        self._refresh_ms = _int(db.get_meta(META_REFRESH, "0"))
        # Bumped whenever anything here changes (so what's worked out from it
        # can tell it's out of date).
        self.version = 0
        self._filling: asyncio.Task | None = None
        # Media's batches being asked about (by key), when Plex last didn't
        # have a title, and what limits Media's asking at once.
        self._asking: dict[str, asyncio.Task] = {}
        self._backlog: dict[str, str] = {}  # (key: kind; asked about one batch at a time)
        self._backlog_task: asyncio.Task | None = None
        self._absent: dict[str, int] = {}
        self._turns: asyncio.Semaphore | None = None
        self._turns_loop: asyncio.AbstractEventLoop | None = None
        self._said_s = 0.0

    def get(self, key: str) -> Title | None:
        return self._known.get(key)

    # Noting what Plex said ----------------------------------------------------

    def note(self, items: Iterable[Item]) -> None:
        """The ratings and libraries that came with `items` (programs just
        gathered from Plex)."""
        now = _now()
        changed: dict[str, Title] = {}
        for item in items:
            rating = (item.rating or "").strip()
            library = (item.library or "").strip()
            if item.kind == MOVIE:
                old = changed.get(item.rating_key) or self._known.get(item.rating_key)
                new = Title(
                    MOVIE,
                    rating,
                    library or (old.library if old else ""),
                    old.checked_ms if old else 0,
                    old.tags if old else None,
                )
                if new != old:
                    changed[item.rating_key] = new
            elif item.kind == EPISODE and item.show_key:
                show = changed.get(item.show_key) or self._known.get(item.show_key)
                if show is None:
                    changed[item.show_key] = Title(SHOW, "", library)
                elif library and not show.library:
                    changed[item.show_key] = Title(
                        SHOW, show.rating, library, show.checked_ms, show.tags
                    )
                old = self._known.get(item.rating_key)
                if rating and (old is None or old.rating != rating):
                    changed[item.rating_key] = Title(EPISODE, rating, "")
                elif not rating and old is not None and old.rating:
                    changed[item.rating_key] = Title(EPISODE, "", "")
        if changed:
            self._save(changed, now)

    def _save(self, changed: dict[str, Title], now: int) -> None:
        self._known.update(changed)
        self.db.save_titles(
            [
                (key, t.kind, t.rating, t.library, now, t.checked_ms,
                 t.tags.to_json() if t.tags else "")
                for key, t in changed.items()
            ]
        )  # fmt: skip
        self.version += 1

    # Asking Plex about the rest -----------------------------------------------

    @property
    def want_tags(self) -> bool:
        return self._want_tags

    @want_tags.setter
    def want_tags(self, wanted: bool) -> None:
        if wanted and not self._want_tags:
            self._tags_since_ms = _now()
        self._want_tags = wanted

    def refresh_tags(self) -> None:
        """Asks Plex about every show's and movie's tags again (what's hidden
        changed: a genre or label added in Plex lately counts at once)."""
        self._refresh_ms = _now()
        self.db.set_meta(META_REFRESH, str(self._refresh_ms))

    def wanted(self, now: int | None = None) -> list[str]:
        """Shows never asked about (or not lately), and movies whose library
        isn't known; and, while anyone is limited by tags, every show and
        movie whose tags aren't known and weren't asked for since that began
        (or tapiOca started), or not since `refresh_tags`, or not in the
        last day: what `fill` asks Plex about, the longest waiting first."""
        if now is None:
            now = _now()
            # (Never later than now: after a clock steps back, what's asked
            # about from then on counts as asked since, rather than every
            # title being due at every look until the clock catches up.)
            if self._tags_since_ms > now:
                self._tags_since_ms = now
            if self._refresh_ms > now:
                self._refresh_ms = now
                self.db.set_meta(META_REFRESH, str(now))
        since, refresh = self._tags_since_ms, self._refresh_ms

        def due(t: Title) -> bool:
            stale = now - t.checked_ms >= RECHECK_MS
            if (t.kind == SHOW or (t.kind == MOVIE and not t.library)) and stale:
                return True
            if self._want_tags and t.kind in (SHOW, MOVIE):
                return (
                    now - t.checked_ms >= TAGS_RECHECK_MS
                    or (t.tags is None and t.checked_ms < since)
                    or t.checked_ms < refresh
                )
            return False

        found = [(t.checked_ms, key) for key, t in self._known.items() if due(t)]
        return [key for _, key in sorted(found)]

    async def fill(self, ask: Asker) -> None:
        """Asks Plex about what `wanted` lists, a batch at a time (each once,
        whatever the clock does meanwhile)."""
        asked: set[str] = set()
        while True:
            batch = [k for k in self.wanted() if k not in asked][:FILL_AT_ONCE]
            if not batch:
                return
            asked.update(batch)
            found = await ask(batch)
            now = _now()
            changed = {}
            for key in batch:
                old = self._known[key]
                rating, library, *rest = found.get(key, (old.rating, old.library, old.tags))
                tags = rest[0] if rest else old.tags
                # (One Plex no longer has keeps what was known, with no tags
                # if none were: asked again next week.)
                changed[key] = Title(old.kind, rating, library or old.library, now, tags)
            self._save(changed, now)

    async def ensure(self, wanted: dict[str, str], wait_s: float = ENSURE_S) -> None:
        """Asks Plex about the shows and movies of `wanted` (key: kind) whose
        tags aren't known (for Media, whose lists don't carry them whole),
        waiting up to `wait_s` for what Plex says (or less: `ensure_until`).
        The first ENSURE_AHEAD batches (`wanted` in the order it's shown)
        are asked about at once; the rest wait their turn behind other
        answers' asks, a batch at a time, so one big Media folder doesn't
        hold up the rest. Each batch is kept as it comes, and carries on if
        this stops waiting (or is cancelled); one already being asked about
        isn't asked about twice; one Plex didn't have isn't asked about
        again for an hour. What's not known yet stays hidden from anyone
        limited by tags."""
        if self.asker is None:
            return
        now = _now()
        if len(self._absent) > 10_000:  # (forgetting the oldest)
            self._absent = {k: at for k, at in self._absent.items() if now - at < ABSENT_MS}
        missing = [
            k for k, kind in wanted.items()
            if kind in (SHOW, MOVIE)
            and (k not in self._known or self._known[k].tags is None)
            and now - self._absent.get(k, now - ABSENT_MS) >= ABSENT_MS
        ]  # fmt: skip
        if not missing:
            return
        loop = asyncio.get_running_loop()
        waits = {self._asking[k] for k in missing if k in self._asking}
        fresh = [k for k in missing if k not in self._asking]
        if len(fresh) <= ENSURE_AHEAD * ENSURE_AT_ONCE:
            ahead = fresh  # (a small ask goes ahead, even of what's waiting its turn)
        else:
            # (A big one: only its first few batches of what isn't waiting
            # already, so asking for the same big folder again, from another
            # device or sort, doesn't go ahead of everyone else.)
            ahead = [k for k in fresh if k not in self._backlog][: ENSURE_AHEAD * ENSURE_AT_ONCE]
            # (...but at least its first batch, in the order it's shown, so
            # what's on screen isn't left behind another folder's rest.)
            ahead = ahead or fresh[:ENSURE_AT_ONCE]
        going = set(ahead)
        later = [k for k in fresh if k not in going]
        for at in range(0, len(ahead), ENSURE_AT_ONCE):
            batch = {k: wanted[k] for k in ahead[at : at + ENSURE_AT_ONCE]}
            for key in batch:
                self._backlog.pop(key, None)  # (asked now, if it was waiting)
            waits.add(self._start_batch(batch, self.asker))
        for key in later:
            self._backlog.setdefault(key, wanted[key])
        if self._backlog and (self._backlog_task is None or self._backlog_task.done()):
            self._backlog_task = loop.create_task(self._work_backlog(self.asker))
        until = ensure_until.get()
        if until is not None:
            wait_s = min(wait_s, until - loop.time())
        if wait_s > 0 and waits:
            await asyncio.wait(waits, timeout=wait_s)

    def _start_batch(self, kinds: dict[str, str], ask: Asker) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(self._ask_batch(kinds, ask))
        for key in kinds:
            self._asking[key] = task
        return task

    async def _work_backlog(self, ask: Asker) -> None:
        """Media's asks beyond the first few batches, one batch at a time."""
        while self._backlog:
            keys = list(self._backlog)[:ENSURE_AT_ONCE]
            taken = {k: self._backlog.pop(k) for k in keys}
            batch = {
                k: kind
                for k, kind in taken.items()
                if k not in self._asking and (k not in self._known or self._known[k].tags is None)
            }
            if batch:
                await self._start_batch(batch, ask)

    async def _ask_batch(self, kinds: dict[str, str], ask: Asker) -> None:
        """One batch of Media's `ensure`, kept as it comes."""
        me = asyncio.current_task()
        try:
            loop = asyncio.get_running_loop()
            if self._turns is None or self._turns_loop is not loop:
                self._turns, self._turns_loop = asyncio.Semaphore(ENSURE_TURNS), loop
            async with self._turns:
                found = await ask(list(kinds))
            now = _now()
            changed = {}
            for key, kind in kinds.items():
                if key not in found:
                    self._absent[key] = now
                    continue
                rating, library, *rest = found[key]
                tags = rest[0] if rest else None
                old = self._known.get(key)
                changed[key] = Title(
                    kind, rating, library or (old.library if old else ""), now, tags
                )
            if changed:
                self._save(changed, now)
        except Exception as e:  # (unknown stays unknown: hidden, to be safe)
            if time.monotonic() - self._said_s >= SAY_EVERY_S:
                self._said_s = time.monotonic()
                log.info("Can't ask Plex about some titles in Media right now (%s)", e)
        finally:
            for key in kinds:
                if self._asking.get(key) is me:
                    del self._asking[key]

    def tags(self, key: str) -> Tags | None:
        """A show's or movie's tags, if known."""
        title = self._known.get(key)
        return title.tags if title else None

    def fill_soon(self, ask: Asker) -> None:
        """Starts `fill`, unless it's already under way."""
        if self._filling and not self._filling.done():
            return
        if not self.wanted():
            return

        async def work() -> None:
            try:
                await self.fill(ask)
            except Exception as e:  # (it's tried again next time)
                log.info("Can't ask Plex about the ratings of what's on the stations (%s)", e)

        self._filling = asyncio.get_running_loop().create_task(work())

    async def filled(self) -> None:
        """Waits for `fill_soon`'s work, if any (for tests)."""
        if self._filling:
            with contextlib.suppress(Exception):
                await self._filling

    # Judging a program ----------------------------------------------------------

    def judge(self, item: Item) -> Judged:
        """How limits see `item`, from what's known of it."""
        if item.kind == EPISODE:
            show = self._known.get(item.show_key or "")
            own = self._known.get(item.rating_key)
            if show is None or not show.checked_ms:
                return Judged(
                    True, None, show.library if show else "", False, item.show_key or "",
                    show.tags if show else None,
                )  # fmt: skip
            mine = ratings.age(own.rating) if own else None
            return Judged(
                True, ratings.stricter(ratings.age(show.rating), mine), show.library, True,
                item.show_key or "", show.tags,
            )  # fmt: skip
        movie = self._known.get(item.rating_key)
        if movie is None:
            return Judged(False, None, "", False, item.rating_key)
        return Judged(
            False, ratings.age(movie.rating), movie.library, True, item.rating_key, movie.tags
        )


def _now() -> int:
    return int(time.time() * 1000)


def _int(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        return 0
