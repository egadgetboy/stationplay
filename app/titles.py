"""The rating and library of what's on each station (see docs/users.md).

Whether a user sees a station depends on everything it plays, so the rating
and library of each show and movie on a station is kept here (the `titles`
table, mirrored in memory). They're noted whenever a station's programs are
gathered from Plex (Updater.gather): a movie's rating comes with it, as does
an episode's own, when it has one. A show's rating comes only by asking Plex
about the show itself, and so does a movie's library when the list it came
from didn't say; that's done soon after (`fill`), in batches, and again every
week in case Plex's changed.

What isn't known yet counts as not allowed: a station with a show whose
rating hasn't been asked for is hidden from anyone with a limit until it is.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from . import ratings
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


@dataclass(frozen=True)
class Judged:
    """A program as limits see it: TV or a movie, its age (None: unrated),
    its library ("" if unknown), and whether its rating is known yet."""

    tv: bool
    age: int | None
    library: str
    known: bool


# Asks Plex about shows and movies: their keys → (rating, library) for each
# Plex has (a key Plex doesn't have is left out).
Asker = Callable[[list[str]], Awaitable[dict[str, tuple[str, str]]]]


class Titles:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._known: dict[str, Title] = {
            r["key"]: Title(r["kind"], r["rating"], r["library"], r["checked_ms"])
            for r in db.titles()
        }
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
                )
                if new != old:
                    changed[item.rating_key] = new
            elif item.kind == EPISODE and item.show_key:
                show = changed.get(item.show_key) or self._known.get(item.show_key)
                if show is None:
                    changed[item.show_key] = Title(SHOW, "", library)
                elif library and not show.library:
                    changed[item.show_key] = Title(SHOW, show.rating, library, show.checked_ms)
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
            [(key, t.kind, t.rating, t.library, now, t.checked_ms) for key, t in changed.items()]
        )
        self.version += 1

    # Asking Plex about the rest -----------------------------------------------

    def wanted(self, now: int | None = None) -> list[str]:
        """Shows never asked about (or not lately), and movies whose library
        isn't known: what `fill` asks Plex about, the longest waiting first."""
        now = _now() if now is None else now
        due = [
            (t.checked_ms, key)
            for key, t in self._known.items()
            if (t.kind == SHOW or (t.kind == MOVIE and not t.library))
            and now - t.checked_ms >= RECHECK_MS
        ]
        return [key for _, key in sorted(due)]

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
                rating, library = found.get(key, (old.rating, old.library))
                changed[key] = Title(old.kind, rating, library or old.library, now)
            self._save(changed, now)

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
                return Judged(True, None, show.library if show else "", False)
            mine = ratings.age(own.rating) if own else None
            return Judged(
                True, ratings.stricter(ratings.age(show.rating), mine), show.library, True
            )
        movie = self._known.get(item.rating_key)
        if movie is None:
            return Judged(False, None, "", False)
        return Judged(False, ratings.age(movie.rating), movie.library, True)


def _now() -> int:
    return int(time.time() * 1000)
