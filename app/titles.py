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
every week in case Plex's changed. Media asks for the tags of what it shows
someone a level or a person limits by them, as it goes (`ensure`).

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
from dataclasses import dataclass, field

from . import ratings
from .catalog import Tags
from .db import Database, Item

log = logging.getLogger("stationplay.titles")

MOVIE, SHOW, EPISODE = "movie", "show", "episode"
RECHECK_MS = 7 * 86_400_000  # how often Plex is asked about a title again
FILL_AT_ONCE = 200  # titles asked about in one go (Plex is asked 50 at a time)


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
        # asked about once from when that began (or StationPlay started).
        self._want_tags = False
        self._tags_since_ms = _now()
        # Bumped whenever anything here changes (so what's worked out from it
        # can tell it's out of date).
        self.version = 0
        self._filling: asyncio.Task | None = None

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

    def wanted(self, now: int | None = None) -> list[str]:
        """Shows never asked about (or not lately), and movies whose library
        isn't known; and, while anyone is limited by tags, every show and
        movie whose tags aren't known (or not lately): what `fill` asks Plex
        about, the longest waiting first."""
        now = _now() if now is None else now

        def due(t: Title) -> bool:
            stale = now - t.checked_ms >= RECHECK_MS
            if (t.kind == SHOW or (t.kind == MOVIE and not t.library)) and stale:
                return True
            if self._want_tags and t.kind in (SHOW, MOVIE):
                return stale or (t.tags is None and t.checked_ms < self._tags_since_ms)
            return False

        found = [(t.checked_ms, key) for key, t in self._known.items() if due(t)]
        return [key for _, key in sorted(found)]

    async def fill(self, ask: Asker) -> None:
        """Asks Plex about what `wanted` lists, a batch at a time."""
        while True:
            batch = self.wanted()[:FILL_AT_ONCE]
            if not batch:
                return
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

    async def ensure(self, wanted: dict[str, str]) -> None:
        """Asks Plex now about the shows and movies of `wanted` (key: kind)
        whose tags aren't known (for Media, whose lists don't carry them
        whole). One Plex doesn't answer about stays unknown."""
        missing = [
            k for k, kind in wanted.items()
            if kind in (SHOW, MOVIE) and (k not in self._known or self._known[k].tags is None)
        ]  # fmt: skip
        if not missing or self.asker is None:
            return
        found = await self.asker(missing)
        now = _now()
        changed = {}
        for key in missing:
            if key not in found:
                continue
            rating, library, *rest = found[key]
            tags = rest[0] if rest else None
            old = self._known.get(key)
            changed[key] = Title(
                wanted[key], rating, library or (old.library if old else ""), now, tags
            )
        if changed:
            self._save(changed, now)

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
