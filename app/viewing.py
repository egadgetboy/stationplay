"""What each user can see: Viewing Levels, and stations allowed or blocked
for someone (see docs/users.md).

Every user has a Viewing Level (Unrestricted unless an Admin chooses
another): the oldest age their movies and their TV may be rated for,
whether unrated titles are shown, and which libraries they can see.
Unrestricted, with no limits, comes with StationPlay and stays as it is;
so do Teen, Kid and Young Child, to start from, which an Admin can rename,
change or remove like the levels they add. Admins see everything, as does
everyone while signing in is off.

A title is judged by its rating, library and (from 1.33.0) what it is
(titles.Judged), in this order (docs/users.md, "The rules, in order"): a
title hidden for the person hides it; one allowed for them shows it, unless
its library isn't on their level; a library the level doesn't include hides
it; a rating above the level's age for its kind does (unrated: as the level
says); then a genre, tag, collection or studio the level or the person
hides, or the title itself hidden by the level (Blocks). A level or person
that hides by tags hides what's not known yet, as with ratings.

A station is one stream that everyone watching shares, so it's all or
nothing: allowed or blocked for someone by an Admin, or else seen only if
everything it plays passes their level. What it plays is its lineup from
the era airing now on, and the programs its specials draw on; what each
needs is worked out once (a Reach) and kept until the lineup or a rating
changes.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import access, ratings
from .access import ADMIN
from .catalog import EPISODE, MOVIE, SHOW, Entry, Tags
from .db import Database, Item, User
from .text import plain
from .titles import Judged, Titles

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .main import AppContext

log = logging.getLogger("stationplay.viewing")

UNRESTRICTED, TEEN, KID, YOUNG_CHILD = "unrestricted", "teen", "kid", "young-child"
# The levels StationPlay comes with: (builtin, name, movies' age, TV's age,
# unrated shown). Unrestricted is always there, and stays as it is; the
# others are made once, the first time, as a start.
BUILT_IN = (
    (UNRESTRICTED, "Unrestricted", None, None, True),
    (TEEN, "Teen", 13, 14, False),
    (KID, "Kid", 10, 10, False),
    (YOUNG_CHILD, "Young Child", 0, 0, False),
)
UNRESTRICTED_STAYS = (
    "Unrestricted shows everything, and stays as it is. To set limits, change another level "
    "or add one of your own."
)
LEVELS_MOST = 50
NAME_MAX = 40
AGE_MOST = 18


# What a level or a person can hide by (Blocks), as the page and the API name
# them: Plex's genres, tags (its labels), collections and studios.
TAG_KINDS = ("genres", "labels", "collections", "studios")
TAG_NAMES = {"genres": "genre", "labels": "tag", "collections": "collection", "studios": "studio"}
BLOCKS_MOST = 200  # of each kind
TITLES_MOST = 500
TAG_LONGEST = 100


def _fold(values: tuple[str, ...]) -> frozenset[str]:
    return frozenset(v.casefold() for v in values)


@dataclass(frozen=True)
class Blocks:
    """What's hidden by what a title is (1.33.0): genres, tags (Plex's
    labels), collections and studios, matched whatever their case, and
    titles by their key, with their names (key: name) for the page."""

    genres: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    collections: tuple[str, ...] = ()
    studios: tuple[str, ...] = ()
    titles: tuple[tuple[str, str], ...] = ()

    @cached_property
    def folded(self) -> dict[str, frozenset[str]]:
        return {kind: _fold(getattr(self, kind)) for kind in TAG_KINDS}

    @cached_property
    def title_keys(self) -> frozenset[str]:
        return frozenset(k for k, _ in self.titles)

    @property
    def by_tags(self) -> bool:
        return any(getattr(self, kind) for kind in TAG_KINDS)

    @property
    def empty(self) -> bool:
        return not self.by_tags and not self.titles

    def hit(self, key: str, tags: Tags | None) -> str | None:
        """What of these hides a title: "title", a kind of tag, or "unknown"
        (its tags aren't known yet, and these hide by them); None if
        nothing does."""
        if key and key in self.title_keys:
            return "title"
        if not self.by_tags:
            return None
        if tags is None:
            return "unknown"
        have = {
            "genres": _fold(tags.genres),
            "labels": _fold(tags.labels),
            "collections": _fold(tags.collections),
            "studios": _fold((tags.studio,)) if tags.studio else frozenset(),
        }
        for kind in TAG_KINDS:
            if have[kind] & self.folded[kind]:
                return kind
        return None

    def hides(self, key: str, tags: Tags | None) -> bool:
        return self.hit(key, tags) is not None

    def meets(self, reach: Reach) -> str | None:
        """What of these a station that needs `reach` plays, as `hit` says
        it ("unknown": what it plays isn't all known yet); None if nothing."""
        if reach.titles & self.title_keys:
            return "title"
        if not self.by_tags:
            return None
        if not reach.tagged:
            return "unknown"
        for kind in TAG_KINDS:
            if getattr(reach, kind) & self.folded[kind]:
                return kind
        return None

    def named(self, kind: str, reach: Reach) -> str:
        """The first of these of `kind` a station that needs `reach` plays,
        as the Admin wrote it (for saying why it's hidden)."""
        if kind == "title":
            return next((name for key, name in self.titles if key in reach.titles), "")
        found = getattr(reach, kind, frozenset())
        return next((v for v in getattr(self, kind) if v.casefold() in found), "")

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {kind: list(getattr(self, kind)) for kind in TAG_KINDS}
        out["titles"] = [{"key": k, "title": t} for k, t in self.titles]
        return out

    def to_text(self) -> str:
        """As kept ('' when empty)."""
        return "" if self.empty else json.dumps(self.as_json(), separators=(",", ":"))

    @staticmethod
    def from_json(got: Any) -> Blocks:
        """From what as_json makes (or the API is given). ValueError if it
        won't do."""
        if got is None:
            return Blocks()
        if not isinstance(got, dict):
            raise ValueError("Blocks are given as lists")
        lists: dict[str, tuple[str, ...]] = {}
        for kind in TAG_KINDS:
            values = got.get(kind) or []
            if not isinstance(values, list) or len(values) > BLOCKS_MOST:
                raise ValueError(f"Choose up to {BLOCKS_MOST} of each")
            seen: dict[str, str] = {}
            for v in values:
                text = plain(str(v)).strip()
                if not text or len(text) > TAG_LONGEST:
                    raise ValueError(f"Each {TAG_NAMES[kind]} is up to {TAG_LONGEST} characters")
                seen.setdefault(text.casefold(), text)
            lists[kind] = tuple(sorted(seen.values(), key=str.casefold))
        titles = got.get("titles") or []
        if not isinstance(titles, list) or len(titles) > TITLES_MOST:
            raise ValueError(f"Choose up to {TITLES_MOST} titles")
        keyed: dict[str, str] = {}
        for t in titles:
            key = str((t or {}).get("key", "")) if isinstance(t, dict) else ""
            if not _KEY.fullmatch(key):
                raise ValueError("Titles are given by their key")
            keyed[key] = plain(str(t.get("title") or "")).strip()[:200]
        return Blocks(
            lists["genres"], lists["labels"], lists["collections"], lists["studios"],
            tuple(sorted(keyed.items(), key=lambda kt: kt[1].casefold())),
        )  # fmt: skip

    @staticmethod
    def from_text(text: str) -> Blocks:
        """As kept. ValueError (or TypeError) if it can't be read."""
        if not text:
            return Blocks()
        return Blocks.from_json(json.loads(text))


# A title's key, as Plex has it (digits) or a folder library will.
_KEY = re.compile(r"[A-Za-z0-9:._-]{1,64}")


@dataclass(frozen=True)
class Person:
    """What's hidden or allowed for one person, whatever their level says
    (1.33.0): their own Blocks, and titles allowed for them (key: name)."""

    blocks: Blocks = Blocks()
    allowed: tuple[tuple[str, str], ...] = ()

    @property
    def empty(self) -> bool:
        return self.blocks.empty and not self.allowed

    def as_json(self) -> dict[str, Any]:
        return {
            "blocks": self.blocks.as_json(),
            "allowTitles": [{"key": k, "title": t} for k, t in self.allowed],
        }

    def to_text(self) -> str:
        return "" if self.empty else json.dumps(self.as_json(), separators=(",", ":"))

    @staticmethod
    def from_json(got: Any) -> Person:
        """ValueError if it won't do."""
        if not isinstance(got, dict):
            raise ValueError("Give what's hidden and allowed as lists")
        blocks = Blocks.from_json(got.get("blocks"))
        allowed = Blocks.from_json({"titles": got.get("allowTitles") or []}).titles
        return Person(blocks, allowed)

    @staticmethod
    def from_text(text: str) -> Person | None:
        """As kept; None if it can't be read (so the person sees nothing
        limits would decide, to be safe)."""
        if not text:
            return Person()
        try:
            return Person.from_json(json.loads(text))
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class Level:
    id: int
    name: str
    movie_age: int | None  # None: no limit
    tv_age: int | None
    unrated: bool  # whether unrated titles are shown
    libraries: frozenset[str] | None  # None: every library
    builtin: str = ""
    blocks: Blocks = Blocks()  # (from 1.33.0)

    @property
    def limited(self) -> bool:
        return (
            self.movie_age is not None
            or self.tv_age is not None
            or not self.unrated
            or self.libraries is not None
            or not self.blocks.empty
        )

    def allows(self, judged: Judged) -> bool:
        """Whether this level's users may see a title."""
        if not self.limited:
            return True
        if not judged.known:
            return False
        if self.libraries is not None and judged.library not in self.libraries:
            return False
        if judged.age is None:
            if not self.unrated:
                return False
        else:
            most = self.tv_age if judged.tv else self.movie_age
            if most is not None and judged.age > most:
                return False
        return not self.blocks.hides(judged.key, judged.tags)

    def allows_reach(self, reach: Reach) -> bool:
        """Whether this level's users may see a station that needs `reach`."""
        if not self.limited:
            return True
        if not reach.known:
            return False
        if self.libraries is not None and not reach.libraries <= self.libraries:
            return False
        if (reach.movie_unrated or reach.tv_unrated) and not self.unrated:
            return False
        if self.movie_age is not None and (reach.movie_age or 0) > self.movie_age:
            return False
        if self.tv_age is not None and (reach.tv_age or 0) > self.tv_age:
            return False
        return self.blocks.meets(reach) is None

    def why_not(self, reach: Reach) -> str | None:
        """Why this level's users don't see a station that needs `reach`,
        in a sentence; None if they do."""
        if self.allows_reach(reach):
            return None
        if not reach.known:
            return "StationPlay is still asking Plex about the ratings of what it plays"
        if self.libraries is not None and not reach.libraries <= self.libraries:
            return f"It plays programs from a Media folder {self.name} doesn’t include"
        if self.movie_age is not None and (reach.movie_age or 0) > self.movie_age:
            return f"It plays movies {ratings.named(reach.movie_age or 0, tv=False)}"
        if self.tv_age is not None and (reach.tv_age or 0) > self.tv_age:
            return f"It plays shows {ratings.named(reach.tv_age or 0, tv=True)}"
        if (reach.movie_unrated or reach.tv_unrated) and not self.unrated:
            return "It plays programs that aren’t rated"
        return (
            blocked_why(self.blocks, reach, f"which {self.name} hides")
            or "It plays programs that aren’t rated"
        )

    def as_json(self, users: int = 0) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "movieAge": self.movie_age,
            "tvAge": self.tv_age,
            "unrated": self.unrated,
            "libraries": None if self.libraries is None else sorted(self.libraries),
            "builtin": self.builtin,
            "users": users,
            "blocks": self.blocks.as_json(),
        }


def blocked_why(blocks: Blocks, reach: Reach, which: str) -> str | None:
    """Why `blocks` hide a station that needs `reach`, in a sentence ending
    with `which` ("which Kid hides", "hidden for Pat"); None if they don't."""
    met = blocks.meets(reach)
    if met is None:
        return None
    if met == "unknown":
        return "StationPlay is still asking Plex what its programs are"
    name = blocks.named(met, reach)
    if met == "title":
        return f"It plays {name or 'a title'}, {which}"
    return f"It plays programs with the {TAG_NAMES[met]} {name}, {which}"


@dataclass(frozen=True)
class Reach:
    """What a station needs of a level: the oldest age its movies and its TV
    are rated for (None: none rated), whether any is unrated, the libraries
    they're in, and whether all their ratings are known yet."""

    known: bool = True
    movie_age: int | None = None
    tv_age: int | None = None
    movie_unrated: bool = False
    tv_unrated: bool = False
    libraries: frozenset[str] = frozenset()
    # (From 1.33.0: what its shows and movies are, each kind of tag matched
    # whatever its case; their keys; and whether all their tags are known.
    # Compared, as before, by what ratings and libraries need.)
    tagged: bool = field(default=True, compare=False)
    genres: frozenset[str] = field(default=frozenset(), compare=False)
    labels: frozenset[str] = field(default=frozenset(), compare=False)
    collections: frozenset[str] = field(default=frozenset(), compare=False)
    studios: frozenset[str] = field(default=frozenset(), compare=False)
    titles: frozenset[str] = field(default=frozenset(), compare=False)


def reach_of(items: list[Item], titles: Titles) -> Reach:
    known = True
    tagged = True
    oldest: dict[bool, int | None] = {True: None, False: None}
    unrated = {True: False, False: False}
    libraries: set[str] = set()
    tags: dict[str, set[str]] = {kind: set() for kind in TAG_KINDS}
    keys: set[str] = set()
    for item in items:
        judged = titles.judge(item)
        if judged.key:
            keys.add(judged.key)
        if judged.tags is None:
            tagged = False
        else:
            tags["genres"] |= _fold(judged.tags.genres)
            tags["labels"] |= _fold(judged.tags.labels)
            tags["collections"] |= _fold(judged.tags.collections)
            if judged.tags.studio:
                tags["studios"].add(judged.tags.studio.casefold())
        if not judged.known:
            known = False
            continue
        libraries.add(judged.library)
        if judged.age is None:
            unrated[judged.tv] = True
        else:
            was = oldest[judged.tv]
            oldest[judged.tv] = judged.age if was is None else max(was, judged.age)
    return Reach(
        known, oldest[False], oldest[True], unrated[False], unrated[True], frozenset(libraries),
        tagged, frozenset(tags["genres"]), frozenset(tags["labels"]),
        frozenset(tags["collections"]), frozenset(tags["studios"]), frozenset(keys),
    )  # fmt: skip


def judge_entry(entry: Entry, show: Entry | None = None, tags: Tags | None = None) -> Judged:
    """How limits see a show, movie or episode from the library (an episode
    by its show's rating, or its own if that's stricter: `show`, if Plex
    has it; and by its show's tags). `tags`: the show's or movie's, whole
    (titles.Titles keeps them: lists carry only a few)."""
    if entry.kind == EPISODE:
        key = entry.show_key or ""
        if show is None:
            return Judged(True, None, entry.library, False, key, tags)
        age = ratings.stricter(ratings.age(show.content_rating), ratings.age(entry.content_rating))
        return Judged(True, age, show.library or entry.library, True, key, tags)
    return Judged(
        entry.kind == SHOW,
        ratings.age(entry.content_rating),
        entry.library,
        entry.kind in (SHOW, MOVIE),
        entry.key,
        tags,
    )


@dataclass(frozen=True)
class Viewer:
    """What one person may see: everything, or what their level and their
    stations allow."""

    level: Level
    everything: bool
    allowed: frozenset[int] = frozenset()  # stations
    blocked: frozenset[int] = frozenset()
    own: Person = Person()  # (what's hidden or allowed for them: 1.33.0)

    @property
    def by_tags(self) -> bool:
        """Whether a title's tags decide what they see (so Media must know
        them whole)."""
        return not self.everything and (self.level.blocks.by_tags or self.own.blocks.by_tags)

    def sees(self, judged: Judged) -> bool:
        if self.everything:
            return True
        # (The rules, in order: docs/users.md.)
        if judged.key and judged.key in self.own.blocks.title_keys:
            return False
        if judged.key and any(judged.key == k for k, _ in self.own.allowed):
            libraries = self.level.libraries
            return libraries is None or (judged.known and judged.library in libraries)
        return self.level.allows(judged) and not self.own.blocks.hides(judged.key, judged.tags)


EVERYONE = Viewer(Level(0, "Unrestricted", None, None, True, None, UNRESTRICTED), everything=True)
# Someone who sees nothing limits decide: gone, or whose own limits can't be
# read (to be safe).
NOTHING = Viewer(Level(0, "", 0, 0, False, frozenset()), everything=False)


class Viewing:
    def __init__(self, db: Database, titles: Titles) -> None:
        self.db = db
        self.titles = titles
        self._make_built_in()
        self._levels: dict[int, Level] = {}
        self._stations: dict[int, dict[int, bool]] = {}
        self._people: dict[int, Person | None] = {}  # (None: can't be read)
        # Whether signing in is on (set by main): while it's off, everyone sees
        # everything, so no one has limits.
        self.signing_in: Callable[[], bool] = lambda: True
        self._reaches: dict[int, tuple[tuple, Reach]] = {}
        self.reload()

    def _make_built_in(self) -> None:
        rows = self.db.levels()
        for r in rows:
            if r["builtin"] == "adult":
                # (1.23.0's test builds called Unrestricted "Adult".)
                self.db.make_level_builtin(r["id"], UNRESTRICTED, "Unrestricted")
        rows = self.db.levels()
        have = {r["builtin"] for r in rows}
        names = {r["name"].casefold() for r in rows}
        for builtin, name, movie_age, tv_age, unrated in BUILT_IN:
            if builtin in have or (rows and builtin != UNRESTRICTED):
                continue  # (Teen and the others only the first time: they can be removed)
            # (An Admin's own level may already have the name.)
            while name.casefold() in names:
                name += " (StationPlay)"
            self.db.add_level(name, movie_age, tv_age, unrated, None, builtin)
            names.add(name.casefold())

    def reload(self) -> None:
        self._levels = {r["id"]: _level(r) for r in self.db.levels()}
        self._stations = self.db.user_stations()
        self._people = {
            user_id: Person.from_text(text) for user_id, text in self.db.user_blocks().items()
        }
        # (Titles' tags are asked for only while someone is limited by them:
        # as soon as someone is, Plex is asked about what's on the stations.)
        wanted = any(lv.blocks.by_tags for lv in self._levels.values()) or any(
            p is None or p.blocks.by_tags for p in self._people.values()
        )
        began = wanted and not self.titles.want_tags
        self.titles.want_tags = wanted
        if began and self.titles.asker is not None:
            # (Not running yet, the Updater asks soon after starting.)
            with contextlib.suppress(RuntimeError):
                self.titles.fill_soon(self.titles.asker)

    # Levels ---------------------------------------------------------------------

    def levels(self) -> list[Level]:
        return list(self._levels.values())

    def level(self, level_id: int | None) -> Level:
        """A level by its id; Unrestricted for None (or one that's gone)."""
        found = self._levels.get(level_id) if level_id is not None else None
        return found or next(lv for lv in self._levels.values() if lv.builtin == UNRESTRICTED)

    def save_level(
        self,
        level_id: int | None,
        name: str,
        movie_age: int | None,
        tv_age: int | None,
        unrated: bool,
        libraries: list[str] | None,
        blocks: Blocks | None = None,
    ) -> Level:
        """Adds a level (level_id None) or changes one (`blocks` None: as
        it was). ValueError if it won't do."""
        name = plain(name).strip()
        if not name or len(name) > NAME_MAX:
            raise ValueError(f"Give the level a name, up to {NAME_MAX} characters")
        for age in (movie_age, tv_age):
            if age is not None and not 0 <= age <= AGE_MOST:
                raise ValueError("Choose a rating from the list")
        if libraries is not None:
            libraries = sorted({str(k) for k in libraries})
            if len(libraries) > 200:
                raise ValueError("That's too many Media folders")
        if level_id is None and len(self._levels) >= LEVELS_MOST:
            raise ValueError(f"StationPlay keeps at most {LEVELS_MOST} Viewing Levels")
        if level_id is not None and level_id not in self._levels:
            raise ValueError("That Viewing Level has been removed")
        if level_id is not None and self._levels[level_id].builtin == UNRESTRICTED:
            raise ValueError(UNRESTRICTED_STAYS)
        if blocks is None:
            blocks = self._levels[level_id].blocks if level_id is not None else Blocks()
        try:
            if level_id is None:
                level_id = self.db.add_level(
                    name, movie_age, tv_age, unrated, libraries, blocks=blocks.to_text()
                )
            else:
                self.db.update_level(
                    level_id, name, movie_age, tv_age, unrated, libraries, blocks.to_text()
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"There's already a Viewing Level called {name}") from None
        self.reload()
        return self._levels[level_id]

    def remove_level(self, level_id: int) -> None:
        """Removes a level, if no one's on it (but never Unrestricted). ValueError."""
        level = self._levels.get(level_id)
        if level is None:
            return
        if level.builtin == UNRESTRICTED:
            raise ValueError(UNRESTRICTED_STAYS)
        if any(u.level_id == level_id for u in self.db.users()):
            raise ValueError(f"Choose another level for everyone on {level.name} first")
        self.db.delete_level(level_id)
        self.reload()

    def users_on(self) -> dict[int, int]:
        """How many users each level has (Unrestricted counts those with none)."""
        unrestricted = self.level(None).id
        out: dict[int, int] = {}
        for u in self.db.users():
            key = u.level_id if u.level_id in self._levels else unrestricted
            out[key] = out.get(key, 0) + 1
        return out

    # Someone's level and stations ---------------------------------------------

    def set_user(
        self,
        user: User,
        level_id: int | None,
        stations: dict[int, bool] | None,
        person: Person | None = None,
    ) -> None:
        """A user's level, and (if given) the stations allowed or blocked
        for them, and what's hidden or allowed for them (`person`).
        ValueError."""
        if level_id is not None and level_id not in self._levels:
            raise ValueError("That Viewing Level has been removed")
        if self.level(level_id).builtin == UNRESTRICTED:
            level_id = None
        self.db.set_user_level(user.id, level_id)
        if stations is not None:
            self.db.set_user_stations(user.id, stations)
        if person is not None:
            self.db.set_user_blocks(user.id, person.to_text())
        self.reload()

    def stations_of(self, user_id: int) -> dict[int, bool]:
        return dict(self._stations.get(user_id, {}))

    def person(self, user_id: int) -> Person:
        """What's hidden or allowed for someone (nothing, if it can't be
        read: viewer() hides everything from them then)."""
        return self._people.get(user_id) or Person()

    # What someone sees ----------------------------------------------------------

    def watches_only(self, user: User) -> bool:
        """Whether a User is on a limited level: they watch what they can
        see, but don't make stations (whose editor shows the libraries as a
        whole)."""
        now = self.db.user(user.id)
        return now is not None and now.role != ADMIN and self.level(now.level_id).limited

    def viewer(self, user: User | None) -> Viewer:
        """What `user` may see (None: signing in is off, so everything). Read
        as they are now: their level may have changed since they signed in."""
        if user is None:
            return EVERYONE
        now = self.db.user(user.id)
        if now is None:
            return NOTHING
        if now.role == ADMIN:
            return EVERYONE
        level = self.level(now.level_id)
        own = self._people.get(now.id, Person())
        if own is None:
            return NOTHING
        stations = self._stations.get(now.id, {})
        blocked = frozenset(c for c, allowed in stations.items() if not allowed)
        return Viewer(
            level,
            everything=not level.limited and not blocked and own.blocks.empty,
            allowed=frozenset(c for c, allowed in stations.items() if allowed),
            blocked=blocked,
            own=own,
        )

    def sees_station(self, viewer: Viewer, channel_id: int) -> bool:
        if viewer.everything:
            return True
        if channel_id in viewer.blocked:
            return False
        if channel_id in viewer.allowed:
            return True
        reach = self.reach(channel_id)
        return viewer.level.allows_reach(reach) and viewer.own.blocks.meets(reach) is None

    @property
    def signature(self) -> str:
        """Changes whenever who might see what does (levels, who's on which,
        what's hidden or allowed for each, signing in): so stations' lineups
        are made again, their commercials and trailers chosen afresh."""
        levels = [
            (lv.id, lv.movie_age, lv.tv_age, lv.unrated,
             sorted(lv.libraries) if lv.libraries is not None else None, lv.blocks.to_text())
            for lv in self._levels.values()
        ]  # fmt: skip
        users = [(u.id, u.role, u.level_id) for u in self.db.users()]
        people = {str(k): (p.to_text() if p else "?") for k, p in self._people.items()}
        stations = {str(k): sorted(v.items()) for k, v in self._stations.items()}
        text = json.dumps([levels, users, people, stations, self.signing_in()], sort_keys=True)
        return hashlib.sha1(text.encode()).hexdigest()

    def limited_audience(self, channel_id: int, reach: Reach | None = None) -> bool:
        """Whether anyone with limits can see a station (as its lineup is now,
        or as `reach`, a lineup being made, says): what decides its
        commercials and trailers (see cliprules.py). While what it plays isn't
        all known yet, anyone with limits counts, to be safe."""
        if not self.signing_in():
            return False
        reach = reach if reach is not None else self.reach(channel_id)
        for user in self.db.users():
            viewer = self.viewer(user)
            if viewer.everything:
                continue
            if not reach.known or (viewer.by_tags and not reach.tagged):
                return True
            if channel_id in viewer.blocked:
                continue
            if channel_id in viewer.allowed:
                return True
            if viewer.level.allows_reach(reach) and viewer.own.blocks.meets(reach) is None:
                return True
        return False

    def reach(self, channel_id: int, now_ms: int | None = None) -> Reach:
        """What a station needs of a level, from what it plays from now on."""
        eras = self.db.eras(channel_id)
        sets = self.db.program_sets(channel_id)
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        current = 0
        for n, era in enumerate(eras):
            if era.start_ms is None or era.start_ms <= now_ms:
                current = n
        key = (self.titles.version, tuple(e.id for e in eras[current:]), self.db.sets_version)
        cached = self._reaches.get(channel_id)
        if cached and cached[0] == key:
            return cached[1]
        items = [i for e in eras[current:] for i in e.items]
        items += [i for programs in sets.values() for i in programs]
        found = reach_of(items, self.titles)
        self._reaches[channel_id] = (key, found)
        return found


def _level(row: sqlite3.Row) -> Level:
    libraries = None
    if row["libraries"] is not None:
        try:
            libraries = frozenset(str(k) for k in json.loads(row["libraries"]))
        except (TypeError, ValueError):
            libraries = frozenset()  # (can't be read: no library, to be safe)
    try:
        blocks = Blocks.from_text(row["blocks"])
    except (TypeError, ValueError):
        blocks = Blocks()
        libraries = frozenset()  # (as above)
    return Level(
        row["id"], row["name"], row["movie_age"], row["tv_age"], bool(row["unrated"]),
        libraries, row["builtin"], blocks,
    )  # fmt: skip


# The Access tab's addresses (for Admins only: see access.FOR_USERS) -----------


class LevelIn(BaseModel):
    name: str = Field(max_length=100)
    movieAge: int | None = None  # (null: no limit)
    tvAge: int | None = None
    unrated: bool = True
    libraries: list[str] | None = Field(default=None, max_length=500)  # (null: all)
    # What it hides by what a title is (1.33.0): {"genres", "labels",
    # "collections", "studios": [names], "titles": [{"key", "title"}]};
    # null or left out: as it was.
    blocks: dict[str, Any] | None = None


class UserViewing(BaseModel):
    """What's given changes: a level (null: Unrestricted), and the stations allowed
    (true) or blocked (false) for them, by id (any not listed are neither); and
    (1.33.0) what's hidden or allowed for them: {"blocks": as a level's,
    "allowTitles": [{"key", "title"}]}."""

    level: int | None = None
    stations: dict[str, bool] | None = Field(default=None, max_length=10_000)
    own: dict[str, Any] | None = None


def routes(app: FastAPI, ctx: AppContext) -> None:
    v = ctx.viewing

    def who(request: Request) -> str:
        user = access.signed_in(request)
        return user.name if user else "Someone"

    def described(level: Level) -> str:
        movies = (
            "any movie"
            if level.movie_age is None
            else f"movies up to {ratings.named(level.movie_age, tv=False).removeprefix('rated ')}"
        )
        tv = (
            "any show"
            if level.tv_age is None
            else f"shows up to {ratings.named(level.tv_age, tv=True).removeprefix('rated ')}"
        )
        unrated = "unrated shown" if level.unrated else "unrated hidden"
        libraries = (
            "every Media folder"
            if level.libraries is None
            else plural_libraries(len(level.libraries))
        )
        hidden = hides_said(level.blocks)
        return f"{movies}, {tv}, {unrated}, {libraries}{f', hiding {hidden}' if hidden else ''}"

    @app.get("/api/access/viewing")
    async def viewing_state() -> dict[str, Any]:
        on = v.users_on()
        return {
            "levels": [lv.as_json(on.get(lv.id, 0)) for lv in v.levels()],
            "users": {
                str(u.id): {
                    "level": v.level(u.level_id).id,
                    "stations": {str(c): a for c, a in v.stations_of(u.id).items()},
                    "own": v.person(u.id).as_json(),
                }
                for u in ctx.db.users()
            },
            "movieRatings": [[age, name] for age, name in ratings.MOVIE_AT.items()],
            "tvRatings": [[age, name] for age, name in ratings.TV_AT.items()],
        }

    def level_from(body: LevelIn, level_id: int | None) -> Level:
        try:
            blocks = None if body.blocks is None else Blocks.from_json(body.blocks)
            return v.save_level(
                level_id, body.name, body.movieAge, body.tvAge, body.unrated, body.libraries,
                blocks,
            )  # fmt: skip
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/access/levels", status_code=201)
    async def add_level(body: LevelIn, request: Request):
        level = level_from(body, None)
        ctx.access.record(
            logging.INFO,
            f"{who(request)} added the Viewing Level {level.name} ({described(level)})",
        )
        return level.as_json()

    @app.put("/api/access/levels/{level_id}")
    async def change_level(level_id: int, body: LevelIn, request: Request):
        before = v.level(level_id)
        level = level_from(body, level_id)
        if level != before:
            ctx.access.record(
                logging.INFO,
                f"{who(request)} changed the Viewing Level {level.name} ({described(level)})",
            )
        return level.as_json(v.users_on().get(level.id, 0))

    @app.delete("/api/access/levels/{level_id}", status_code=204)
    async def remove_level(level_id: int, request: Request):
        level = v.level(level_id)
        try:
            v.remove_level(level_id)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        if level.id == level_id:
            ctx.access.record(
                logging.INFO, f"{who(request)} removed the Viewing Level {level.name}"
            )

    @app.put("/api/access/users/{user_id}/viewing")
    async def set_user_viewing(user_id: int, body: UserViewing, request: Request):
        user = ctx.db.user(user_id)
        if user is None:
            raise HTTPException(404, "That user doesn't exist")
        before_level = v.level(user.level_id)
        before_stations = v.stations_of(user.id)
        before_own = v.person(user.id)
        level_id = body.level if "level" in body.model_fields_set else user.level_id
        stations = None
        if body.stations is not None:
            try:
                stations = {int(k): bool(a) for k, a in body.stations.items()}
            except ValueError:
                raise HTTPException(400, "Stations are given by their id") from None
        try:
            own = None if body.own is None else Person.from_json(body.own)
            v.set_user(user, level_id, stations, own)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        now_level = v.level(level_id)
        said = []
        if now_level.id != before_level.id:
            said.append(f"put {user.name} on the Viewing Level {now_level.name}")
        if stations is not None and stations != before_stations:
            names = {c.id: c.number for c in ctx.db.list_channels()}
            allowed = sorted(names[c] for c, a in stations.items() if a and c in names)
            blocked = sorted(names[c] for c, a in stations.items() if not a and c in names)
            what = []
            if allowed:
                what.append(f"allowed {_numbers(allowed)}")
            if blocked:
                what.append(f"blocked {_numbers(blocked)}")
            said.append(
                f"{' and '.join(what)} for {user.name}"
                if what
                else f"cleared {user.name}'s allowed and blocked stations"
            )
        if own is not None and own != before_own:
            hidden = hides_said(own.blocks)
            allowed = len(own.allowed)
            said.append(
                f"set what's hidden and allowed for {user.name} ("
                + (f"hiding {hidden}" if hidden else "hiding nothing more")
                + (f", {allowed} title{'' if allowed == 1 else 's'} allowed" if allowed else "")
                + ")"
            )
        if said:
            ctx.access.record(logging.INFO, f"{who(request)} {' and '.join(said)}")
        return {
            "level": now_level.id,
            "stations": {str(c): a for c, a in v.stations_of(user.id).items()},
            "own": v.person(user.id).as_json(),
        }

    @app.get("/api/access/tags")
    async def tags_offered() -> dict[str, list[str]]:
        """What levels and people can hide by: the genres, tags (Plex's
        labels), collections and studios the shows' and movies' Media
        folders have, each once, by name. (Those Plex can't list just now
        are left out: the page can still show what a level already hides.)"""
        found: dict[str, dict[str, str]] = {kind: {} for kind in TAG_KINDS}
        fields = {"genres": "genre", "labels": "label", "collections": "collection",
                  "studios": "studio"}  # fmt: skip
        try:
            libraries = [
                s for s in await ctx.library.libraries() if s.get("type") in ("show", "movie")
            ]
        except Exception as e:
            raise HTTPException(
                503, "Plex can’t be reached right now. Try again in a moment."
            ) from e
        for s in libraries:
            for kind, plex_field in fields.items():
                try:
                    got = await ctx.library.choices(str(s["key"]), plex_field, str(s["type"]))
                except Exception:  # (one library's list missing: the rest still)
                    continue
                for c in got:
                    name = plain(str(c.get("title") or "")).strip()
                    if name and len(name) <= TAG_LONGEST:
                        found[kind].setdefault(name.casefold(), name)
        return {kind: sorted(names.values(), key=str.casefold) for kind, names in found.items()}

    @app.get("/api/access/users/{user_id}/stations")
    async def user_stations(user_id: int):
        """Every station, and whether this user sees it (and if not, why)."""
        user = ctx.db.user(user_id)
        if user is None:
            raise HTTPException(404, "That user doesn't exist")
        viewer = v.viewer(user)
        chosen = v.stations_of(user.id)
        out = []
        for c in ctx.db.list_channels():
            why = None
            if not viewer.everything:
                reach = v.reach(c.id)
                why = viewer.level.why_not(reach) or blocked_why(
                    viewer.own.blocks, reach, f"hidden for {user.name}"
                )
            out.append(
                {
                    "id": c.id,
                    "number": c.number,
                    "name": c.name,
                    "chosen": "allowed"
                    if chosen.get(c.id) is True
                    else "blocked"
                    if chosen.get(c.id) is False
                    else "level",
                    "levelSees": why is None,
                    "why": why,
                }
            )
        return {"admin": user.role == access.ADMIN, "level": viewer.level.name, "stations": out}


def hides_said(blocks: Blocks) -> str:
    """What `blocks` hide, for the access log: "2 genres and 1 title"."""
    parts = []
    for kind in (*TAG_KINDS, "titles"):
        n = len(getattr(blocks, kind))
        if n:
            name = TAG_NAMES.get(kind, "title")
            parts.append(f"{n} {name}{'' if n == 1 else 's'}")
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"


def plural_libraries(n: int) -> str:
    return f"{n} Media folder{'' if n == 1 else 's'}"


def _numbers(numbers: list[int]) -> str:
    """Stations by number: "station 7", "stations 7 and 9", "stations 3, 7 and 9"."""
    if len(numbers) == 1:
        return f"station {numbers[0]}"
    listed = [str(n) for n in numbers]
    return f"stations {', '.join(listed[:-1])} and {listed[-1]}"
