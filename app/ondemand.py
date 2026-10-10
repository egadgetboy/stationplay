"""Your library in StationPlay's apps (see docs/on-demand.md): which
libraries an Admin shares with them, what the apps are told about shows,
movies and episodes, deciding whether a device can play a file as it is,
play sessions, and where each person is in what they watch.

Off until an Admin shares a library on the Access tab: until then the apps
see no library at all, and nothing here asks Plex anything. Stations don't
change either way.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from . import catalog
from .catalog import Entry, Media, Track
from .text import plain

if TYPE_CHECKING:
    from .db import Database
    from .library import Library

log = logging.getLogger(__name__)

META = "app_libraries"
# When playing can't keep up (see docs/on-demand.md, "Keeping up"): offer a
# smaller version of the title, or switch to it on its own; at home, and
# away from home.
SLOW_META = "app_when_slow"
WHEN_SLOW = ("offer", "switch")
SLOW_DEFAULTS = {"home": "offer", "away": "switch"}
# Even sound for a show's episodes (see applibrary.py): on unless an Admin
# turns it off ("0").
EVEN_META = "app_even_sound"
LIBRARIES_MOST = 100
NOT_SHARED = "That isn't in a library shared with StationPlay's apps"
UNREACHABLE = "StationPlay can't reach Plex right now. Try again in a moment."

# Requests to the library for the apps at once, at most (the rest wait).
LIBRARY_AT_ONCE = 6
# What an app asks waits this long for the library, at most, then is told
# it can't be reached (503), well before an app gives up waiting itself.
# What was being fetched carries on, so asking again soon finds it ready.
LIBRARY_WAIT_S = 8.0
# What's remembered of the library, and for how long.
WHERE_KEPT = 5000  # which library each show, movie and episode is in
ENTRIES_KEPT = 500  # shows', movies' and episodes' details
ENTRY_S = 600.0
LIBRARIES_S = 60.0  # the libraries themselves
SHOWS_KEPT = 50  # shows' lists of episodes
EPISODES_KEPT = 40_000  # (and their episodes, in all, at most)
EPISODES_S = 120.0
# Whole libraries (and their genres), for sorting, filtering, jumping to a
# letter, searching and finding others like a title: kept this long, then
# while the library hasn't changed (as its fingerprint says, asked at most
# every FINGERPRINT_S), up to WHOLE_MOST_S; this many (and their shows and
# movies, in all, at most).
WHOLE_S = 120.0
WHOLE_MOST_S = 1800.0
FINGERPRINT_S = 20.0
WHOLES_KEPT = 8
WHOLE_ENTRIES_KEPT = 40_000
WHOLE_PAGE = 500  # asked for this many at a time
GENRES_S = 600.0
GENRE_LONGEST = 100
RELATED_MOST = 12

# Lists: shows or movies per page (and at most), a show's episodes per page
# (at most, and unless asked for fewer), search results and home rows.
PAGE_DEFAULT = 50
PAGE_MOST = 200
EPISODES_MOST = 500
SEARCH_MOST = 50
SEARCH_LONGEST = 100  # characters searched for
ADDED_MOST = 20  # each library's recently added
ADDED_S = 60.0  # (kept this long)
CONTINUE_MOST = 20
SHOW_ROWS = 20  # a show's latest progress looked through for what's next

# Pictures are made one of these widths (the next one up from what's asked
# for), so a few sizes of each are kept rather than one of every width.
WIDTHS = (160, 320, 480, 720, 1280, 1920)
PICTURE_KINDS = ("poster", "backdrop", "thumb")
PICTURE_BYTES_KEPT = 48 << 20
PICTURES_AT_ONCE = 8  # (asked of the library at once, at most: the rest wait their turn)

# Progress: less than this far in counts as not started; a program is
# watched once its credits start (Plex's marker) or, without one, this far.
STARTED_MS = 60_000
WATCHED_SHARE = 0.9

# Play sessions (see PlaySessions).
# (32 characters: 192 random bits, from secrets, so no one can guess one,
# even through the public port.)
SESSION_ID_BYTES = 24
SESSION_IDLE_S = 4 * 3600.0  # ended once unused this long
COPY_RESTING_S = 600.0  # a copy unused this long has its pieces deleted
WATCHING_S = 180.0  # counts as a device watching until unheard from this long
SESSIONS_MOST = 500
RECHECK_S = 60.0  # how often a session's sign-in is checked again
# The same program played again on the same device this soon after is the
# same play (another sound track, a smaller version: see PlaySessions.start),
# and the sessions ended lately kept for telling (at most this many).
AGAIN_S = 600.0
ENDED_KEPT = 200


# Sharing libraries -------------------------------------------------------------


class Shared:
    """Which of the libraries the apps may see: none until an Admin chooses."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.keys: tuple[str, ...] = self._load()
        self.when_slow: dict[str, str] = self._load_slow()
        # Every episode played brought to the stations' loudness, so a show's
        # episodes match (see applibrary.py); movies never are.
        self.even_sound: bool = db.get_meta(EVEN_META) != "0"

    def save_even_sound(self, on: bool) -> None:
        self.even_sound = on
        self.db.set_meta(EVEN_META, "1" if on else "0")

    def _load_slow(self) -> dict[str, str]:
        try:
            got = json.loads(self.db.get_meta(SLOW_META) or "{}")
        except ValueError:
            got = {}
        if not isinstance(got, dict):
            got = {}
        return {
            where: got[where] if got.get(where) in WHEN_SLOW else default
            for where, default in SLOW_DEFAULTS.items()
        }

    def save_when_slow(self, home: str | None, away: str | None) -> dict[str, str]:
        """What the apps do when playing can't keep up, at home and away
        (None leaves one as it is). ValueError for anything else."""
        chosen = dict(self.when_slow)
        for where, value in (("home", home), ("away", away)):
            if value is None:
                continue
            if value not in WHEN_SLOW:
                raise ValueError("Choose Offer or Switch")
            chosen[where] = value
        self.when_slow = chosen
        self.db.set_meta(SLOW_META, json.dumps(chosen))
        return chosen

    def _load(self) -> tuple[str, ...]:
        try:
            got = json.loads(self.db.get_meta(META) or "[]")
        except ValueError:
            return ()
        if not isinstance(got, list):
            return ()
        return tuple(dict.fromkeys(str(k) for k in got if _a_key(k)))

    @property
    def on(self) -> bool:
        return bool(self.keys)

    def save(self, keys: Iterable[Any]) -> tuple[str, ...]:
        """Shares these libraries (by key), and only these. ValueError if one
        isn't a library's key."""
        chosen = tuple(dict.fromkeys(str(k) for k in keys))
        if len(chosen) > LIBRARIES_MOST or not all(_a_key(k) for k in chosen):
            raise ValueError("Choose libraries from the list")
        self.keys = chosen
        self.db.set_meta(META, json.dumps(list(chosen)))
        return chosen


def _a_key(value: Any) -> bool:
    text = str(value)
    return isinstance(value, (str, int)) and text.isascii() and text.isdigit() and len(text) < 20


# What the apps are shown ---------------------------------------------------------


class NotShared(LookupError):
    """What was asked about isn't in a shared library (or doesn't exist:
    the apps are told the same either way)."""


def listed(e: Entry) -> Entry:
    """A show, movie or episode as a list keeps it: without its summary
    (lists never show it, and it's most of what they'd keep)."""
    return replace(e, summary="") if e.summary else e


class Whole:
    """A whole library's shows or movies (or one genre's of them), as
    fetched, and as sorted and searched (each made as it's first asked for,
    and kept with it). Kept WHOLE_S as it is, then while the library's
    fingerprint is the same, up to WHOLE_MOST_S. (A show's episodes are kept
    the same way.)"""

    def __init__(self, entries: list[Entry], fingerprint: str) -> None:
        self.entries = entries
        self.fingerprint = fingerprint
        self.made = self.checked = time.monotonic()
        self._sorted: dict[str, list[Entry]] = {}
        self._words: list[tuple[str, str, tuple, Entry]] | None = None

    def sorted(self, sort: str) -> list[Entry]:
        found = self._sorted.get(sort)
        if found is None:
            found = self._sorted[sort] = sorted_by(self.entries, sort)
        return found

    def words(self) -> list[tuple[str, str, tuple, Entry]]:
        """Each one's title and sort title as they're searched (see
        searchable), and its place by title: (title, sort title, place, it)."""
        if self._words is None:
            self._words = [
                (searchable(e.title), searchable(sort_text(e)), title_order(e), e)
                for e in self.sorted("title")
            ]
        return self._words


class Catalog:
    """The library as the apps see it: only shared libraries, with what's
    been asked lately kept a while so browsing doesn't ask the library about
    the same things over and over."""

    def __init__(self, library: Library, shared: Shared) -> None:
        self.library = library
        self.shared = shared
        self._where: OrderedDict[str, str] = OrderedDict()  # key -> its library
        self._entries: OrderedDict[str, tuple[float, Entry]] = OrderedDict()  # (in detail)
        self._cards: OrderedDict[str, tuple[float, Entry]] = OrderedDict()  # (as lists have them)
        self._episodes: OrderedDict[str, Whole] = OrderedDict()  # (shows' episodes)
        self._wholes: OrderedDict[tuple[str, str], Whole] = OrderedDict()
        self._genres: dict[str, tuple[float, list[dict[str, str]]]] = {}
        self._libraries: tuple[float, list[dict[str, Any]]] | None = None
        self._fingerprint: tuple[float, str] | None = None
        self._added: dict[str, tuple[float, list[Entry]]] = {}  # (by library)
        self._turns = asyncio.Semaphore(LIBRARY_AT_ONCE)
        self._fetching: dict[tuple[str, ...], asyncio.Future] = {}

    async def _once(self, key: tuple[str, ...], fetch: Callable[[], Awaitable[Any]]) -> Any:
        """What `fetch` fetches, fetched once however many ask for it at
        once, and carried on to the end even when they stop waiting (an app
        told the library is slow asks again, and finds it ready)."""
        task = self._fetching.get(key)
        if task is None:
            task = self._fetching[key] = asyncio.ensure_future(fetch())

            def done(t: asyncio.Future) -> None:
                if self._fetching.get(key) is t:
                    del self._fetching[key]
                if not t.cancelled():
                    t.exception()  # (told to whoever's waiting; otherwise, no matter)

            task.add_done_callback(done)
        return await asyncio.shield(task)

    def learn(self, entries: Iterable[Entry]) -> None:
        """Remembers which library each of these is in."""
        for e in entries:
            if not e.library:
                continue
            for key in (e.key, e.show_key):
                if key:
                    self._where[key] = e.library
                    self._where.move_to_end(key)
        while len(self._where) > WHERE_KEPT:
            self._where.popitem(last=False)

    def shared_library(self, entry: Entry) -> bool:
        return bool(entry.library) and entry.library in self.shared.keys

    async def libraries(self) -> list[dict[str, str]]:
        """The shared libraries, in the library's own order (what the library
        has is kept LIBRARIES_S)."""
        if not self.shared.on:
            return []
        now = time.monotonic()
        if self._libraries is not None and now - self._libraries[0] < LIBRARIES_S:
            found = self._libraries[1]
        else:

            async def fetch() -> list[dict[str, Any]]:
                async with self._turns:
                    return await self.library.libraries()

            found = await self._once(("libraries",), fetch)
            self._libraries = (now, found)
        return [
            {"key": str(s["key"]), "title": plain(str(s.get("title") or "")), "kind": s["type"]}
            for s in found
            if str(s["key"]) in self.shared.keys and s.get("type") in (catalog.SHOW, catalog.MOVIE)
        ]

    async def library_kind(self, key: str) -> tuple[str, str]:
        """A shared library's (title, kind). NotShared if it isn't one."""
        for lib in await self.libraries():
            if lib["key"] == key:
                return lib["title"], lib["kind"]
        raise NotShared(key)

    async def entry(self, key: str) -> Entry:
        """A show, movie or episode in a shared library, in detail. NotShared
        if it isn't in one (LibraryError if the library can't be reached)."""
        if not (key.isascii() and key.isdigit() and len(key) < 20) or not self.shared.on:
            raise NotShared(key)
        now = time.monotonic()
        kept = self._entries.get(key)
        if kept is not None and now - kept[0] < ENTRY_S:
            self._entries.move_to_end(key)
            found: Entry | None = kept[1]
        else:

            async def fetch() -> Entry | None:
                async with self._turns:
                    found = await self.library.entry(key, details=True)
                if found is not None:
                    self._entries[key] = (time.monotonic(), found)
                    self._entries.move_to_end(key)
                    while len(self._entries) > ENTRIES_KEPT:
                        self._entries.popitem(last=False)
                    self.learn([found])
                return found

            found = await self._once(("entry", key), fetch)
        if found is None or not self.shared_library(found):
            raise NotShared(key)
        return found

    async def check(self, key: str) -> None:
        """NotShared unless `key` is in a shared library (asking the library
        only about keys not seen lately)."""
        where = self._where.get(key)
        if where is None:
            await self.entry(key)
        elif where not in self.shared.keys:
            raise NotShared(key)

    def kept_episodes(self, show: str) -> list[Entry]:
        """A show's episodes, if they're kept (never asking the library)."""
        kept = self._episodes.get(show)
        return kept.entries if kept is not None else []

    async def episodes(self, show: str) -> list[Entry]:
        """A shared show's episodes, in order (specials last): kept
        EPISODES_S, then while the library hasn't changed (as a Whole is)."""
        await self.check(show)
        kept = self._episodes.get(show)
        now = time.monotonic()
        if (
            kept is not None
            and now - kept.checked >= EPISODES_S
            and now - kept.made < WHOLE_MOST_S
            and await self.fingerprint() == kept.fingerprint
        ):
            kept.checked = now  # (the library hasn't changed since)
        if kept is not None and now - kept.checked < EPISODES_S:
            self._episodes.move_to_end(show)
            return kept.entries

        async def fetch() -> list[Entry]:
            fingerprint = await self.fingerprint()
            async with self._turns:
                found = [listed(e) for e in await self.library.show_episodes(show)]
            self.learn(found)
            self._episodes[show] = Whole(found, fingerprint)
            self._episodes.move_to_end(show)
            while len(self._episodes) > SHOWS_KEPT or (
                len(self._episodes) > 1
                and sum(len(x.entries) for x in self._episodes.values()) > EPISODES_KEPT
            ):
                self._episodes.popitem(last=False)
            return found

        found: list[Entry] = await self._once(("episodes", show), fetch)
        return found

    async def genres(self, library: str) -> list[dict[str, str]]:
        """A shared library's genres, A to Z: [{"id", "title"}]."""
        _, kind = await self.library_kind(library)
        now = time.monotonic()
        kept = self._genres.get(library)
        if kept is None or now - kept[0] > GENRES_S:
            async with self._turns:
                found = await self.library.genres(library, kind)
            named = [
                {"id": g["id"], "title": plain(g["title"])} for g in found if plain(g["title"])
            ]
            named.sort(key=lambda g: g["title"].casefold())
            kept = self._genres[library] = (now, named)
        return kept[1]

    async def fingerprint(self) -> str:
        """What changes whenever anything in the libraries may have (asked
        of the library at most every FINGERPRINT_S)."""
        now = time.monotonic()
        if self._fingerprint is not None and now - self._fingerprint[0] < FINGERPRINT_S:
            return self._fingerprint[1]

        async def fetch() -> str:
            async with self._turns:
                return await self.library.fingerprint()

        found: str = await self._once(("fingerprint",), fetch)
        self._fingerprint = (now, found)
        return found

    async def whole(self, library: str, sort: str, genre: str = "") -> tuple[str, str, list[Entry]]:
        """All of a shared library's shows or movies, sorted (see sorted_by;
        and only those with `genre`, by its name): (its title, kind, them).
        Kept a while (see Whole), so paging through it, filtering it, and
        searching it ask the library once."""
        title, kind = await self.library_kind(library)
        found = await self._whole(library, kind, genre)
        return title, kind, found.sorted(sort)

    async def _whole(self, library: str, kind: str, genre: str) -> Whole:
        key = (library, genre)
        kept = self._wholes.get(key)
        now = time.monotonic()
        if (
            kept is not None
            and now - kept.checked >= WHOLE_S
            and now - kept.made < WHOLE_MOST_S
            and await self.fingerprint() == kept.fingerprint
        ):
            kept.checked = now  # (the library hasn't changed since)
        if kept is not None and now - kept.checked < WHOLE_S:
            self._wholes.move_to_end(key)
            return kept

        async def fetch() -> Whole:
            fingerprint = await self.fingerprint()  # (a change while fetching: fetched again)
            genre_id = None
            if genre:
                wanted = genre.casefold()
                ids = [
                    g["id"] for g in await self.genres(library) if g["title"].casefold() == wanted
                ]
                if not ids:
                    return Whole([], fingerprint)  # (no such genre here)
                genre_id = ids[0]

            async def page(start: int) -> tuple[int, list[Entry]]:
                async with self._turns:
                    return await self.library.browse(
                        library, kind, "title", start, WHOLE_PAGE, genre_id
                    )

            # The first page says how many there are; the rest come at once.
            total, first = await page(0)
            rest = range(len(first), total, WHOLE_PAGE) if first else range(0)
            pages = await asyncio.gather(*(page(start) for start in rest))
            together = first + [e for _, p in pages for e in p]
            # (Each once, and without what lists never show: their summaries.)
            entries = list({e.key: listed(e) for e in together}.values())
            self.learn(entries)
            whole = self._wholes[key] = Whole(entries, fingerprint)
            self._wholes.move_to_end(key)
            while len(self._wholes) > WHOLES_KEPT or (
                len(self._wholes) > 1
                and sum(len(x.entries) for x in self._wholes.values()) > WHOLE_ENTRIES_KEPT
            ):
                self._wholes.popitem(last=False)
            return whole

        found: Whole = await self._once(("whole", *key), fetch)
        return found

    async def recently_added(self) -> list[tuple[dict[str, str], list[Entry]]]:
        """Each shared library's newest shows or movies (kept ADDED_S, as
        the home screen is opened often)."""
        libs = await self.libraries()

        async def newest(lib: dict[str, str]) -> list[Entry]:
            kept = self._added.get(lib["key"])
            if kept is not None and time.monotonic() - kept[0] < ADDED_S:
                return kept[1]

            async def fetch() -> list[Entry]:
                async with self._turns:
                    found = await self.library.recently_added(lib["key"], lib["kind"], ADDED_MOST)
                self.learn(found)
                self._added[lib["key"]] = (time.monotonic(), found)
                return found

            found: list[Entry] = await self._once(("added", lib["key"]), fetch)
            return found

        found = await asyncio.gather(*(newest(lib) for lib in libs))
        return [
            (lib, [e for e in entries if self.shared_library(e)])
            for lib, entries in zip(libs, found, strict=True)
        ]

    async def search(self, words: str) -> list[Entry]:
        """Shows and movies whose titles have `words` in them, in every
        shared library, case and accents aside (see match): the best
        matches first (a title that's just that, then those starting with
        it, then with a word starting with it, then the rest), each kind of
        match in the order of their titles. All of them: the caller keeps
        those someone may see, then the first few."""
        wanted = searchable(words)
        if not wanted:
            return []
        libs = await self.libraries()
        wholes = await asyncio.gather(*(self._whole(lib["key"], lib["kind"], "") for lib in libs))
        found = [
            (how, order, e)
            for whole in wholes
            for title, sort, order, e in whole.words()
            if (how := match(wanted, title, sort)) is not None
        ]
        found.sort(key=lambda x: x[:2])
        return [e for _, _, e in found]

    async def entries(self, keys: list[str]) -> list[Entry]:
        """Several shows, movies or episodes, in the order asked, leaving out
        those gone or not shared: those kept (in detail, or as a list has
        them) from what's kept, and the rest asked of the library (and kept,
        as lists have them, ENTRY_S)."""
        now = time.monotonic()
        kept: dict[str, Entry] = {}
        for key in keys:
            for place in (self._entries, self._cards):
                found = place.get(key)
                if found is not None and now - found[0] < ENTRY_S:
                    kept[key] = found[1]
                    break
        if missing := [key for key in keys if key not in kept]:
            async with self._turns:
                fetched = await self.library.entries(missing)
            self.learn(fetched)
            for e in fetched:
                kept[e.key] = listed(e)
                self._cards[e.key] = (now, kept[e.key])
                self._cards.move_to_end(e.key)
            while len(self._cards) > ENTRIES_KEPT:
                self._cards.popitem(last=False)
        return [x for key in keys if (x := kept.get(key)) is not None and self.shared_library(x)]


# Sorting, jumping to a letter, searching, and others like a title ------------------

_ARTICLES = ("the ", "a ", "an ")
# Letters that don't come apart into a plain letter and an accent.
_LETTERS = str.maketrans(
    {"æ": "ae", "œ": "oe", "ø": "o", "đ": "d", "ð": "d", "ł": "l", "þ": "th", "ı": "i"}
)


def folded(text: str) -> str:
    """Text as titles are compared and sorted: case and accents set aside
    ("Amélie" is "amelie", "Æon Flux" is "aeon flux")."""
    apart = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in apart if not unicodedata.combining(c)).translate(_LETTERS)


def sort_text(e: Entry) -> str:
    """What a show or movie is sorted by: the library's own sort title
    (Plex's sorts "The Orbit Room" as "Orbit Room"), or else its title
    without a leading "The", "A" or "An"."""
    if e.sort_title.strip():
        return e.sort_title.strip()
    title = e.title.strip()
    lowered = title.casefold()
    for article in _ARTICLES:
        if lowered.startswith(article) and len(title) > len(article):
            return title[len(article) :].lstrip()
    return title


def _sorted_as(e: Entry) -> str:
    """A show's or movie's sort title as it's compared (see folded), from
    its first letter or digit ("¡Three Amigos!" as "three amigos!")."""
    text = folded(sort_text(e))
    at = next((i for i, c in enumerate(text) if c.isalnum()), 0)
    return text[at:]


def letter_of(e: Entry) -> str:
    """The letter a show or movie is listed under ("The Orbit Room" under
    O; "Élan" under E); "#" for a digit, or anything that isn't A to Z."""
    first = _sorted_as(e)[:1].upper()
    return first if "A" <= first <= "Z" else "#"


def _numbers_in_order(text: str) -> tuple:
    """`text`, with its numbers compared as numbers ("Saw 2" before "Saw
    10"), however long."""
    parts = re.split(r"(\d+)", text)
    return tuple((len(p.lstrip("0")), p.lstrip("0")) if i % 2 else p for i, p in enumerate(parts))


def key_order(key: str) -> tuple[int, str]:
    """Keys in order (a longer number is a larger one): what breaks ties."""
    return len(key), key


def title_order(e: Entry) -> tuple:
    """Where a show or movie is listed by title: "#" (digits, and anything
    that isn't A to Z) first, then A to Z by its sort title from its first
    letter or digit, case and accents aside, numbers as numbers; titles
    alike in order of their keys, so the order is always the same."""
    text = _sorted_as(e)
    return (letter_of(e) != "#", _numbers_in_order(text), key_order(e.key))


def sorted_by(entries: Iterable[Entry], sort: str) -> list[Entry]:
    """Shows or movies as listed: by `title` (see title_order), `added`
    (newest first) or `released` (newest first, those without a date last);
    ties in the order of their titles."""
    by_title = sorted(entries, key=title_order)
    if sort == "added":
        return sorted(by_title, key=lambda e: e.added_ms or 0, reverse=True)
    if sort == "released":

        def released(e: Entry) -> tuple[bool, str]:
            when = e.released or (str(e.year) if e.year else "")
            return bool(when), when

        return sorted(by_title, key=released, reverse=True)
    return by_title


def letters(entries: list[Entry]) -> list[dict[str, Any]]:
    """Where each letter starts among `entries` (sorted by title), for
    jumping to it: [{"letter", "start"}], each letter once, in order ("#"
    first). How many each has is where the next starts, less its own."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, e in enumerate(entries):
        letter = letter_of(e)
        if letter not in seen:
            seen.add(letter)
            out.append({"letter": letter, "start": i})
    return out


def searchable(text: str) -> str:
    """Text as it's searched: folded (see folded), anything but letters and
    digits as spaces, single-spaced."""
    return " ".join("".join(c if c.isalnum() else " " for c in folded(text)).split())


# How well a title matches what's searched for (the lower, the better).
EXACT, STARTS, WORD, INSIDE = 0, 1, 2, 3


def match(wanted: str, title: str, sort: str = "") -> int | None:
    """How well a title matches `wanted` (all three searchable): EXACT (its
    title, or sort title, is just that), STARTS (it starts with it), WORD
    (a word in it does), INSIDE (it's in it somewhere, or is with its spaces
    left out: "spiderman" finds "Spider-Man"); None if it doesn't."""
    titles = (title, sort) if sort and sort != title else (title,)
    if wanted in titles:
        return EXACT
    if any(t.startswith(wanted) for t in titles):
        return STARTS
    if any(f" {wanted}" in t for t in titles):
        return WORD
    if any(wanted in t for t in titles):
        return INSIDE
    joined = wanted.replace(" ", "")
    if any(joined in t.replace(" ", "") for t in titles):
        return EXACT if any(joined == t.replace(" ", "") for t in titles) else INSIDE
    return None


def related(entry: Entry, pool: Iterable[Entry], most: int = RELATED_MOST) -> list[Entry]:
    """Others like `entry` (a show or movie) among `pool`: those sharing the
    most of its genres first, then the nearest in years, then by title.
    None without genres to go by."""
    mine = {g.casefold() for g in entry.genres}
    if not mine:
        return []
    scored = []
    for e in pool:
        shared = len(mine & {g.casefold() for g in e.genres})
        if e.key != entry.key and e.kind == entry.kind and shared:
            apart = abs((e.year or 0) - (entry.year or 0)) if e.year and entry.year else 1000
            scored.append((-shared, apart, e.title.casefold(), e))
    scored.sort(key=lambda s: s[:3])
    return [s[3] for s in scored[:most]]


# Can a device play a file as it is? --------------------------------------------------


@dataclass(frozen=True)
class Device:
    """What a device says it can play."""

    containers: frozenset[str]
    video: dict[str, tuple[int, int, int]]  # codec -> the largest (width, height, bit depth)
    hdr: frozenset[str]
    audio: frozenset[str]


def device(
    containers: Iterable[str],
    video: Iterable[tuple[str, int, int, int]],
    hdr: Iterable[str],
    audio: Iterable[str],
) -> Device:
    """A device's abilities, its names for things made StationPlay's."""
    most: dict[str, tuple[int, int, int]] = {}
    for codec, width, height, depth in video:
        name = catalog.video_codec(codec)
        have = most.get(name, (0, 0, 0))
        most[name] = (max(have[0], width), max(have[1], height), max(have[2], depth))
    return Device(
        containers=frozenset(catalog.container(c) for c in containers),
        video=most,
        hdr=frozenset(h.strip().lower() for h in hdr),
        audio=frozenset(catalog.audio_codec(a) for a in audio),
    )


# How formats are named to people.
_LABELS = {
    "mkv": "MKV", "mp4": "MP4", "mov": "MOV", "avi": "AVI", "ts": "MPEG-TS", "m2ts": "M2TS",
    "wmv": "WMV", "asf": "WMV", "webm": "WebM", "flv": "FLV", "ogg": "Ogg",
    "h264": "H.264", "hevc": "HEVC", "av1": "AV1", "vp9": "VP9", "vp8": "VP8",
    "mpeg2video": "MPEG-2", "mpeg4": "MPEG-4", "vc1": "VC-1",
    "aac": "AAC", "ac3": "Dolby Digital", "eac3": "Dolby Digital Plus", "truehd": "Dolby TrueHD",
    "dts": "DTS", "flac": "FLAC", "mp3": "MP3", "mp2": "MP2", "opus": "Opus", "vorbis": "Vorbis",
    "alac": "ALAC",
    "srt": "SRT", "ass": "ASS", "vtt": "WebVTT", "pgs": "PGS", "vobsub": "VobSub",
    "mov_text": "MP4 text",
}  # fmt: skip
_HDR_LABELS = {catalog.HDR10: "HDR10", catalog.HLG: "HLG"}


def label(name: str) -> str:
    """A format's name as people know it ("Dolby Digital", "HEVC")."""
    if name.startswith("pcm"):
        return "PCM"
    return _LABELS.get(name, name.upper())


def hdr_label(media: Media) -> str | None:
    """Its HDR, as people know it: "Dolby Vision", "HDR10" or "HLG" (None for
    a picture that isn't HDR)."""
    if media.dv_profile is not None:
        return "Dolby Vision"
    return _HDR_LABELS.get(media.hdr)


def needs_dolby_vision(media: Media) -> bool:
    """Whether only a Dolby Vision device shows the picture right: profile 5,
    which has nothing else beneath it (nor does Dolby Vision of a profile the
    library didn't say, unless it said there's HDR10 or HLG beneath). Other
    profiles play as their HDR10, HLG or ordinary picture elsewhere."""
    profile = media.dv_profile
    return profile == 5 or (profile == 0 and not media.hdr)


def unplayable(media: Media, dev: Device) -> list[str]:
    """Why a device can't play a version of a file as it is, in words ([]:
    it can). What the library didn't say isn't held against it. (A version
    in several files plays its first: see applibrary.py.)"""
    why = []
    if media.container and media.container not in dev.containers:
        why.append(f"its file type ({label(media.container)})")
    if media.video:
        most = dev.video.get(media.video)
        if most is None:
            why.append(f"its picture's format ({label(media.video)})")
        else:
            width, height, depth = most
            if media.width > width or media.height > height:
                size = media.size_label or f"{media.width}×{media.height}"
                why.append(f"its picture size ({size})")
            if media.bit_depth > depth:
                why.append(f"its {media.bit_depth}-bit picture")
        dolby_vision = catalog.DOLBY_VISION in dev.hdr and media.dv_profile is not None
        if needs_dolby_vision(media):
            if not dolby_vision:
                profile = f" profile {media.dv_profile}" if media.dv_profile else ""
                why.append(f"its Dolby Vision{profile} picture")
        elif media.hdr and media.hdr not in dev.hdr and not dolby_vision:
            why.append(f"its {_HDR_LABELS[media.hdr]} picture")
    sound = media.default_audio
    if sound is not None and sound.codec and sound.codec not in dev.audio:
        why.append(f"its sound's format ({label(sound.codec)})")
    return why


def best_first(media: Iterable[Media]) -> list[Media]:
    """A program's versions, the best first: the biggest picture, HDR before
    not, then the most detail (bitrate)."""
    return sorted(
        media,
        key=lambda m: (
            -(m.width * m.height),
            0 if (m.hdr or m.dv_profile is not None) else 1,
            -(m.bitrate_kbps or 0),
        ),
    )


# A version fits a connection when the connection carries this much more
# than the version needs on average (busy scenes need more).
FIT_HEADROOM = 1.5


def fits(media: Media, max_kbps: int | None) -> bool | None:
    """Whether a connection carrying `max_kbps` keeps up with a version
    (None when either isn't known)."""
    if not max_kbps or not media.bitrate_kbps:
        return None
    return media.bitrate_kbps * FIT_HEADROOM <= max_kbps


def needs_kbps(media: Media) -> int | None:
    """What a version needs, in kilobits a second: as the library says, or
    else from its file's size and length (None if neither is known)."""
    if media.bitrate_kbps:
        return media.bitrate_kbps
    if media.size and media.duration_ms:
        return max(1, round(media.size * 8 / media.duration_ms))
    return None


def over_cap(media: Media, cap_kbps: int | None) -> bool:
    """Whether a version needs more than the Admin's cap on Media away from
    home (`cap_kbps`; None: Original). What isn't known isn't held against
    it."""
    need = needs_kbps(media)
    return bool(cap_kbps and need and need > cap_kbps)


def choose(
    entry: Entry,
    dev: Device,
    version: str | None = None,
    max_kbps: int | None = None,
    cap_kbps: int | None = None,
) -> tuple[Media | None, list[str]]:
    """The version of a program's file to play as it is on a device: the one
    asked for; or else the best the device can play that the connection
    keeps up with (as the app measured it: `max_kbps`), or with none that
    does, the smallest it can play. Away from home, with the Admin's cap
    (`cap_kbps`), only those within it, or with none within it, the smallest
    (which is then converted down to fit: see applibrary.py). None, and why
    not, if it can't play any. A version that's gone counts as not asked
    for."""
    asked = next((m for m in entry.media if version and m.id == version), None)
    if asked is not None:
        why = unplayable(asked, dev)
        return (asked, []) if not why else (None, why)
    first_why: list[str] = []
    playable = []
    for media in best_first(entry.media):
        why = unplayable(media, dev)
        if why:
            first_why = first_why or why
        else:
            playable.append(media)
    if not playable:
        return None, first_why
    if cap_kbps:
        playable = [m for m in playable if not over_cap(m, cap_kbps)] or playable[-1:]
    if max_kbps:
        fitting = [m for m in playable if fits(m, max_kbps) is not False]
        return (fitting[0] if fitting else playable[-1]), []
    return playable[0], []


def version_labels(media: Iterable[Media]) -> dict[int, str]:
    """How each version is named, by its place: "4K · HDR10", "1080p"; where
    two would be named the same, their formats ("1080p · HEVC") or how much
    detail they carry ("1080p · 12 Mbps") tell them apart."""
    found = list(media)

    def base(m: Media) -> str:
        return " · ".join(x for x in (m.size_label, hdr_label(m)) if x) or label(m.container)

    names = [base(m) for m in found]
    out = {}
    for i, m in enumerate(found):
        same = [x for j, x in enumerate(found) if names[j] == names[i]]
        name = names[i]
        if len(same) > 1:
            if len({x.video for x in same}) == len(same):
                name += f" · {label(m.video)}"
            elif m.bitrate_kbps:
                name += f" · {round(m.bitrate_kbps / 1000)} Mbps"
        out[i] = name
    return out


def cant_play(why: list[str]) -> str:
    """What a device that can't play a file as it is is told, when its app
    doesn't take the copies StationPlay makes."""
    return (
        f"This device can't play this file as it is ({and_list(why)}), and this app can't "
        "take a copy made for it. Update the app to play it."
    )


def and_list(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


# A track title that's a file's name or a path, as some tools write into a
# file ("Northbound.S02E04.1080p.mkv"): the apps never show one (an Admin's
# page and the log may name files; nothing an app receives does).
_FILE_NAME = re.compile(
    r"[\\/]|\.(mkv|mp4|m4v|mov|avi|ts|m2ts|mts|wmv|webm|mpe?g|vob|iso|srt|ass|ssa|vtt|sub|idx"
    r"|sup|mka|mks|ac3|eac3|dts|aac|flac|mp3|ogg|opus|wav)$",
    re.IGNORECASE,
)


def file_like(title: str) -> bool:
    """Whether a track's title looks like a file's name or a path: with a
    slash, ending with a media file's extension, or words joined by dots or
    underscores, as a file's name has them ("Northbound.S02E04.1080p")."""
    return bool(_FILE_NAME.search(title)) or (
        " " not in title and max(title.count("."), title.count("_")) >= 2
    )


def track_name(track: Track, audio: bool) -> str:
    """How a track is listed in the apps: "English · Commentary · AAC ·
    Stereo", "Spanish · Forced"."""
    parts = [plain(track.language) or "Unknown language"]
    title = plain(track.title)
    if title and title.casefold() != parts[0].casefold() and not file_like(title):
        parts.append(title)
    if audio:
        if track.codec:
            parts.append(label(track.codec))
        channels = {1: "Mono", 2: "Stereo", 6: "5.1", 8: "7.1"}.get(track.channels or 0)
        if channels:
            parts.append(channels)
    elif track.forced:
        parts.append("Forced")
    return " · ".join(parts)


# Progress ---------------------------------------------------------------------------


def length_of(entry: Entry, media: Media | None = None) -> int | None:
    """How long a program is as it plays: the version playing (`media`), if
    it's known; a movie in several files plays its first (see applibrary.py),
    so it's that file's length; otherwise its own."""
    if media is not None and media.duration_ms:
        return media.duration_ms
    best = next(iter(best_first(entry.media)), None)
    if best is not None and best.parts > 1 and best.duration_ms:
        return best.duration_ms
    return entry.duration_ms


def is_watched(position_ms: int, entry: Entry, length_ms: int | None = None) -> bool:
    """Whether someone this far into a program has watched it: into its
    closing credits (Plex's marker), or 90% of the way through (of
    `length_ms`, how long it is as it plays: see length_of)."""
    if entry.credits is not None and position_ms >= entry.credits[0]:
        return True
    length = length_ms or entry.duration_ms or 0
    return length > 0 and position_ms >= length * WATCHED_SHARE


def resume_at(row: tuple[int, bool] | None) -> int:
    """Where to start a program again, from someone's progress in it
    (position, watched): the start if they'd barely started it, or finished
    it (which leaves its position at 0)."""
    if row is None:
        return 0
    position, _watched = row
    return position if position >= STARTED_MS else 0


def progressed(
    old: tuple[int, bool] | None, position_ms: int, entry: Entry, length_ms: int | None = None
) -> tuple[int, bool]:
    """Someone's progress in a program once they're `position_ms` into it:
    (where they are, watched). Reaching its credits, or 90% of the way,
    finishes it (and starts it from the beginning next time); watched stays
    watched, even while they watch it again."""
    if is_watched(position_ms, entry, length_ms):
        return 0, True
    return position_ms, bool(old and old[1])


PARTWAY, STARTED, FINISHED, MARKED = "partway", "started", "finished", "marked"


def where_they_are(position_ms: int, watched: bool) -> str:
    """What someone's progress in a program says: PARTWAY through it,
    barely STARTED, FINISHED it, or only MARKED unwatched from a menu (which
    says nothing about where they are)."""
    if position_ms >= STARTED_MS:
        return PARTWAY
    if position_ms > 0:
        return STARTED
    return FINISHED if watched else MARKED


# What's next in a show (see next_up): why it's the one.
GOING, AFTER, FIRST = "going", "after", "first"


def next_up(
    episodes: list[Entry], rows: Iterable[tuple[str, str]], watched: set[str]
) -> tuple[Entry, str] | None:
    """The episode of a show to play next, and why (the one place it's
    decided: see "Up next" in docs/on-demand.md). `episodes`: the show's, in
    order; `rows`: someone's progress in them, newest first, as (key,
    where_they_are); `watched`: the keys of those they've watched.

    The newest that says where they are decides, marks of "not watched" from
    a menu aside: an episode they're partway through, or barely started (a
    special too), is GOING; after a regular episode they finished (or marked
    watched), it's the first one AFTER it (across seasons, specials aside,
    and past any in the same file as it) that they haven't watched, and
    with none, the show is finished (None), whatever they skipped before
    it. A special they finished is passed over. With nothing yet, it's the
    FIRST episode (specials aside, unless there's nothing else)."""
    by_key = {e.key: e for e in episodes}
    regular = [e for e in episodes if e.season != 0] or list(episodes)
    places = {e.key: i for i, e in enumerate(regular)}
    for key, state in rows:
        found = by_key.get(key)
        if found is None or state == MARKED:
            continue
        if state in (PARTWAY, STARTED):
            return found, GOING
        at = places.get(key)
        if at is None:
            continue  # (a special: they're where they were before it)
        later = (
            e
            for e in regular[at + 1 :]
            if e.key not in watched and not (found.file and e.file == found.file)
        )
        upcoming = next(later, None)
        return (upcoming, AFTER) if upcoming is not None else None
    return (regular[0], FIRST) if regular else None


# Play sessions ------------------------------------------------------------------------


@dataclass
class PlaySession:
    """A program being played in an app: what, by whom, from where."""

    id: str
    user_id: int  # (0 while signing in is off)
    user: str  # their name ("" while signing in is off)
    sign_in: str | None  # the sign-in's token hash (None while signing in is off)
    entry: Entry
    media: Media
    path: str | None  # the file, where StationPlay can read it itself
    plex: str | None  # otherwise, where Plex streams it from
    client: str  # which device (as for stations' streams)
    away: bool  # (started through the public port: only then is it offered there)
    # Subtitle files of their own: track id -> (where they're fetched, codec).
    subtitles: dict[str, tuple[str, str]] = field(default_factory=dict)
    # A copy StationPlay makes of it (converting.Copy), if it doesn't play
    # as it is; and where the player starts it.
    copy: Any = None
    start_s: float = 0.0
    app: str = ""  # which app on which device (appapi.app_label), "" if it didn't say
    # Away from home: the start of its app's own address (see away.py), which
    # tells apps behind one reverse proxy apart in Stats, as for stations.
    tag: str = ""
    started: float = field(default_factory=time.monotonic)
    started_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    seen: float = field(default_factory=time.monotonic)
    checked: float = field(default_factory=time.monotonic)
    # What the stats count (see stats.Stats.played): how long it's been
    # watched (the time between its requests, but for gaps longer than
    # WATCHING_S: paused, or gone), how much of that is counted, and whether
    # it's counted as a play; and the place in it its app last said.
    watched_s: float = 0.0
    counted_s: float = 0.0
    played: bool = False
    position_ms: int | None = None
    sequence: int = 0  # (the newest progress report's, if the app numbers them)

    def used(self, now: float) -> None:
        """Something asked for it (`now`, time.monotonic())."""
        gap = now - self.seen
        if 0 < gap <= WATCHING_S:
            self.watched_s += gap
        self.seen = max(self.seen, now)


class PlaySessions:
    """The programs being played in the apps. Each has an address of its own
    (a player can't sign in), which ends when the app says it stopped, when
    it's unused for SESSION_IDLE_S, when its sign-in ends, and when
    StationPlay restarts. Nothing about them is kept on disk.

    What's watched counts in the stats as it's played (`count`, every
    minute or so) and as each session ends, by `count_with` (see
    stats.Stats.played)."""

    def __init__(self) -> None:
        self._sessions: dict[str, PlaySession] = {}
        self.count_with: Callable[[PlaySession], None] | None = None
        # Sessions ended lately, by who played what on which device.
        self._ended: OrderedDict[tuple[int, str, str], PlaySession] = OrderedDict()

    def start(self, **details: Any) -> PlaySession:
        self._tidy()
        while len(self._sessions) >= SESSIONS_MOST:
            oldest = min(self._sessions.values(), key=lambda s: s.seen)
            self.end(oldest.id)
        session = PlaySession(id=secrets.token_urlsafe(SESSION_ID_BYTES), **details)
        before = self.before(session.user_id, session.entry.key, session.client)
        if before is not None:
            # The same play, going on: what was watched before counts as it was.
            self._count(before)
            session.played = before.played
        self._sessions[session.id] = session
        return session

    def before(
        self, user_id: int, key: str, client: str, within_s: float = AGAIN_S
    ) -> PlaySession | None:
        """The last session of the same program for the same person on the
        same device, if it was used in the last `within_s` (going still, or
        ended)."""
        now = time.monotonic()
        found = [
            s
            for s in (*self._sessions.values(), self._ended.get((user_id, key, client)))
            if s is not None
            and (s.user_id, s.entry.key, s.client) == (user_id, key, client)
            and now - s.seen <= within_s
        ]
        return max(found, key=lambda s: s.started, default=None)

    def get(self, session_id: str) -> PlaySession | None:
        """A session that's still going, now marked as used."""
        session = self.find(session_id)
        if session is not None:
            session.used(time.monotonic())
        return session

    def ended(self, session_id: str) -> PlaySession | None:
        """A session that ended lately (one of the last ENDED_KEPT)."""
        return next((s for s in self._ended.values() if s.id == session_id), None)

    def find(self, session_id: str) -> PlaySession | None:
        """A session that's still going, without marking it as used."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if time.monotonic() - session.seen > SESSION_IDLE_S:
            self.end(session_id)
            return None
        return session

    def end(self, session_id: str) -> PlaySession | None:
        """Ends a session (and stops its copy being made); what was watched
        of it counts."""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return None
        if session.copy is not None:
            session.copy.stop()
        self._count(session)
        key = (session.user_id, session.entry.key, session.client)
        self._ended.pop(key, None)
        self._ended[key] = session
        while len(self._ended) > ENDED_KEPT:
            self._ended.popitem(last=False)
        return session

    def count(self) -> None:
        """Counts what's been watched of each session so far."""
        for session in list(self._sessions.values()):
            self._count(session)

    def _count(self, session: PlaySession) -> None:
        if self.count_with is not None:
            self.count_with(session)

    def now(self) -> list[PlaySession]:
        """The sessions being watched now (used in the last WATCHING_S)."""
        now = time.monotonic()
        return [s for s in self._sessions.values() if now - s.seen <= WATCHING_S]

    def newer(self, session: PlaySession) -> bool:
        """Whether a newer session of the same program is going on the same
        device for the same person (it took over: another sound track, or a
        smaller version)."""
        return any(
            s is not session
            and (s.user_id, s.entry.key, s.client)
            == (session.user_id, session.entry.key, session.client)
            and s.started > session.started
            for s in self._sessions.values()
        )

    def end_all(self, away: bool = False) -> None:
        """Ends every session (`away`: those started through the public
        port, as watching away from home is turned off)."""
        for session_id, session in list(self._sessions.items()):
            if session.away or not away:
                self.end(session_id)

    def on_device(self, sign_in: str | None, client: str) -> list[PlaySession]:
        """What one device is playing: an app's sign-in's (its own), or
        while signing in is off, its address's. (A device plays one program
        at a time: see applibrary.py.)"""
        return [
            s
            for s in self._sessions.values()
            if (s.sign_in == sign_in if sign_in else s.sign_in is None and s.client == client)
        ]

    def copies(self, on_gpu: bool = False, besides: list[PlaySession] | None = None) -> int:
        """Copies being converted (their pictures made) now, or asked for
        lately (`on_gpu`: those on the GPU), but for those of `besides`."""
        return sum(
            1
            for s in self._sessions.values()
            if s.copy is not None
            and not s.copy.plan.copies_picture
            and s.copy.active
            and (not on_gpu or s.copy.encoder.is_gpu)
            and s not in (besides or ())
        )

    def tidy(self) -> None:
        """Ends the sessions unused for SESSION_IDLE_S, and deletes the pieces
        of copies unused for COPY_RESTING_S (an app gone without leaving: its
        pieces are made again if it comes back)."""
        self._tidy()
        for s in self._sessions.values():
            if s.copy is not None:
                s.copy.rest(COPY_RESTING_S)

    def watching(self) -> dict[str, bool]:
        """The devices playing something now: client -> away from home."""
        now = time.monotonic()
        out: dict[str, bool] = {}
        for s in self._sessions.values():
            if now - s.seen <= WATCHING_S:
                out[s.client] = out.get(s.client, False) or s.away
        return out

    def _tidy(self) -> None:
        now = time.monotonic()
        for s in list(self._sessions.values()):
            if now - s.seen > SESSION_IDLE_S:
                self.end(s.id)

    def __len__(self) -> int:
        return len(self._sessions)


class PictureCache:
    """Pictures for the apps, the most recently used kept up to a size, each
    with its ETag (from what's in it), so an app asking again for one it has
    is told it has it (304)."""

    def __init__(self, most_bytes: int = PICTURE_BYTES_KEPT) -> None:
        self.most_bytes = most_bytes
        self._kept: OrderedDict[tuple[str, str, int], tuple[bytes, str, str]] = OrderedDict()
        self._bytes = 0

    def clear(self) -> None:
        self._kept.clear()
        self._bytes = 0

    def get(self, key: tuple[str, str, int]) -> tuple[bytes, str, str] | None:
        """(the picture, its type, its ETag), if it's kept."""
        found = self._kept.get(key)
        if found is not None:
            self._kept.move_to_end(key)
        return found

    def put(self, key: tuple[str, str, int], picture: tuple[bytes, str]) -> tuple[bytes, str, str]:
        """Keeps a picture (unless it's too big to): (it, its type, its ETag)."""
        data, kind = picture
        found = (data, kind, f'"{hashlib.sha1(data).hexdigest()[:24]}"')
        if len(data) > self.most_bytes // 8:
            return found  # (one huge picture doesn't push out everything else)
        old = self._kept.pop(key, None)
        if old is not None:
            self._bytes -= len(old[0])
        self._kept[key] = found
        self._bytes += len(data)
        while self._bytes > self.most_bytes:
            _, gone = self._kept.popitem(last=False)
            self._bytes -= len(gone[0])
        return found


def width_for(asked: int) -> int:
    """The width a picture is made at: the next of WIDTHS up from what's
    asked for (the largest, for anything larger)."""
    return next((w for w in WIDTHS if w >= asked), WIDTHS[-1])


# The Resume row and what's next -------------------------------------------------


async def up_next(
    cat: Catalog, db: Database, user_id: int, show: str
) -> tuple[Entry, int, str] | None:
    """The episode of a show someone would play next (see next_up), where
    in it to start, and why; None once they've finished the show."""
    episodes = await cat.episodes(show)
    progress = db.progress_of(user_id, [e.key for e in episodes])
    rows = [
        (row["rating_key"], where_they_are(row["position_ms"], bool(row["watched"])))
        for row in db.recent_progress_of_show(user_id, show, SHOW_ROWS)
    ]
    found = next_up(episodes, rows, {k for k, (_, w) in progress.items() if w})
    if found is None:
        return None
    episode, why = found
    return episode, resume_at(progress.get(episode.key)), why


async def continue_watching(cat: Catalog, db: Database, user_id: int) -> list[tuple[Entry, int]]:
    """The Resume row: movies someone is partway through (a minute or more),
    and for each show they've watched lately, what's next in it (see next_up:
    an episode going, or the one after the last they finished; never a
    show they've finished, or one they haven't started): (the program, where
    to start it), newest first, one per show. Up to twice CONTINUE_MOST: the
    caller keeps those someone may see, then CONTINUE_MOST."""
    picks: list[tuple[str, str]] = []  # (a movie's key, or "", a show's key, or "")
    seen: set[str] = set()
    for row in db.recent_progress(user_id, CONTINUE_MOST * 10):
        show = row["show_key"]
        state = where_they_are(row["position_ms"], bool(row["watched"]))
        if state == MARKED or (show and show in seen):
            continue
        if show:
            seen.add(show)
            picks.append(("", show))
        elif state == PARTWAY:
            picks.append((row["rating_key"], ""))
        if len(picks) >= CONTINUE_MOST * 2:  # (some shows have nothing next)
            break

    async def next_in(show: str) -> str:
        try:
            found = await up_next(cat, db, user_id, show)
        except NotShared:
            return ""
        return found[0].key if found is not None and found[2] != FIRST else ""

    nexts = iter(await asyncio.gather(*(next_in(show) for _, show in picks if show)))
    keys: list[str] = []
    for key, show in picks:
        found = key or (next(nexts) if show else "")
        if found and found not in keys:
            keys.append(found)
    progress = db.progress_of(user_id, keys)
    # (All of them: the caller keeps those the person may see, then the first few.)
    return [(e, resume_at(progress.get(e.key))) for e in await cat.entries(keys)]
