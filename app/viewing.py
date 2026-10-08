"""What each user can see: Viewing Levels, and stations allowed or blocked
for someone (see docs/users.md).

Every user has a Viewing Level (Adult unless an Admin chooses another): the
oldest age their movies and their TV may be rated for, whether unrated
titles are shown, and which libraries they can see. Four come with
StationPlay and can be changed; an Admin can add more. Admins see
everything, as does everyone while signing in is off.

A title is judged by its rating and library (titles.Judged), in this order:
a library the level doesn't include hides it; then a rating above the
level's age for its kind does (unrated: as the level says). (Allowing or
blocking a title for one person comes in a later version.)

A station is one stream that everyone watching shares, so it's all or
nothing: allowed or blocked for someone by an Admin, or else seen only if
everything it plays passes their level. What it plays is its lineup from
the era airing now on, and the programs its specials draw on; what each
needs is worked out once (a Reach) and kept until the lineup or a rating
changes.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import access, ratings
from .access import ADMIN
from .catalog import EPISODE, MOVIE, SHOW, Entry
from .db import Database, Item, User
from .text import plain
from .titles import Judged, Titles

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .main import AppContext

log = logging.getLogger("stationplay.viewing")

ADULT, TEEN, KID, YOUNG_CHILD = "adult", "teen", "kid", "young-child"
# The levels StationPlay comes with: (builtin, name, movies' age, TV's age,
# unrated shown).
BUILT_IN = (
    (ADULT, "Adult", None, None, True),
    (TEEN, "Teen", 13, 14, False),
    (KID, "Kid", 10, 10, False),
    (YOUNG_CHILD, "Young Child", 0, 0, False),
)
LEVELS_MOST = 50
NAME_MAX = 40
AGE_MOST = 18


@dataclass(frozen=True)
class Level:
    id: int
    name: str
    movie_age: int | None  # None: no limit
    tv_age: int | None
    unrated: bool  # whether unrated titles are shown
    libraries: frozenset[str] | None  # None: every library
    builtin: str = ""

    @property
    def limited(self) -> bool:
        return (
            self.movie_age is not None
            or self.tv_age is not None
            or not self.unrated
            or self.libraries is not None
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
            return self.unrated
        most = self.tv_age if judged.tv else self.movie_age
        return most is None or judged.age <= most

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
        return self.tv_age is None or (reach.tv_age or 0) <= self.tv_age

    def why_not(self, reach: Reach) -> str | None:
        """Why this level's users don't see a station that needs `reach`,
        in a sentence; None if they do."""
        if self.allows_reach(reach):
            return None
        if not reach.known:
            return "StationPlay is still asking Plex about the ratings of what it plays"
        if self.libraries is not None and not reach.libraries <= self.libraries:
            return f"It plays programs from a library {self.name} doesn’t include"
        if self.movie_age is not None and (reach.movie_age or 0) > self.movie_age:
            return f"It plays movies {ratings.named(reach.movie_age or 0, tv=False)}"
        if self.tv_age is not None and (reach.tv_age or 0) > self.tv_age:
            return f"It plays shows {ratings.named(reach.tv_age or 0, tv=True)}"
        return "It plays programs that aren’t rated"

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
        }


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


def reach_of(items: list[Item], titles: Titles) -> Reach:
    known = True
    oldest: dict[bool, int | None] = {True: None, False: None}
    unrated = {True: False, False: False}
    libraries: set[str] = set()
    for item in items:
        judged = titles.judge(item)
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
        known, oldest[False], oldest[True], unrated[False], unrated[True], frozenset(libraries)
    )


def judge_entry(entry: Entry, show: Entry | None = None) -> Judged:
    """How limits see a show, movie or episode from the library (an episode
    by its show's rating, or its own if that's stricter: `show`, if Plex
    has it)."""
    if entry.kind == EPISODE:
        if show is None:
            return Judged(True, None, entry.library, False)
        age = ratings.stricter(ratings.age(show.content_rating), ratings.age(entry.content_rating))
        return Judged(True, age, show.library or entry.library, True)
    return Judged(
        entry.kind == SHOW,
        ratings.age(entry.content_rating),
        entry.library,
        entry.kind in (SHOW, MOVIE),
    )


@dataclass(frozen=True)
class Viewer:
    """What one person may see: everything, or what their level and their
    stations allow."""

    level: Level
    everything: bool
    allowed: frozenset[int] = frozenset()  # stations
    blocked: frozenset[int] = frozenset()

    def sees(self, judged: Judged) -> bool:
        return self.everything or self.level.allows(judged)


EVERYONE = Viewer(Level(0, "Adult", None, None, True, None, ADULT), everything=True)


class Viewing:
    def __init__(self, db: Database, titles: Titles) -> None:
        self.db = db
        self.titles = titles
        self._make_built_in()
        self._levels: dict[int, Level] = {}
        self._stations: dict[int, dict[int, bool]] = {}
        self._reaches: dict[int, tuple[tuple, Reach]] = {}
        self.reload()

    def _make_built_in(self) -> None:
        have = {r["builtin"] for r in self.db.levels()}
        names = {r["name"].casefold() for r in self.db.levels()}
        for builtin, name, movie_age, tv_age, unrated in BUILT_IN:
            if builtin in have:
                continue
            # (An Admin's own level may already have the name.)
            while name.casefold() in names:
                name += " (StationPlay)"
            self.db.add_level(name, movie_age, tv_age, unrated, None, builtin)
            names.add(name.casefold())

    def reload(self) -> None:
        self._levels = {r["id"]: _level(r) for r in self.db.levels()}
        self._stations = self.db.user_stations()

    # Levels ---------------------------------------------------------------------

    def levels(self) -> list[Level]:
        return list(self._levels.values())

    def level(self, level_id: int | None) -> Level:
        """A level by its id; Adult for None (or one that's gone)."""
        found = self._levels.get(level_id) if level_id is not None else None
        return found or next(lv for lv in self._levels.values() if lv.builtin == ADULT)

    def save_level(
        self,
        level_id: int | None,
        name: str,
        movie_age: int | None,
        tv_age: int | None,
        unrated: bool,
        libraries: list[str] | None,
    ) -> Level:
        """Adds a level (level_id None) or changes one. ValueError if it
        won't do."""
        name = plain(name).strip()
        if not name or len(name) > NAME_MAX:
            raise ValueError(f"Give the level a name, up to {NAME_MAX} characters")
        for age in (movie_age, tv_age):
            if age is not None and not 0 <= age <= AGE_MOST:
                raise ValueError("Choose a rating from the list")
        if libraries is not None:
            libraries = sorted({str(k) for k in libraries})
            if len(libraries) > 200:
                raise ValueError("That's too many libraries")
        if level_id is None and len(self._levels) >= LEVELS_MOST:
            raise ValueError(f"StationPlay keeps at most {LEVELS_MOST} Viewing Levels")
        if level_id is not None and level_id not in self._levels:
            raise ValueError("That Viewing Level has been removed")
        try:
            if level_id is None:
                level_id = self.db.add_level(name, movie_age, tv_age, unrated, libraries)
            else:
                self.db.update_level(level_id, name, movie_age, tv_age, unrated, libraries)
        except sqlite3.IntegrityError:
            raise ValueError(f"There's already a Viewing Level called {name}") from None
        self.reload()
        return self._levels[level_id]

    def remove_level(self, level_id: int) -> None:
        """Removes an Admin's own level, if no one's on it. ValueError."""
        level = self._levels.get(level_id)
        if level is None:
            return
        if level.builtin:
            raise ValueError(
                f"{level.name} comes with StationPlay, so it can be changed but not removed"
            )
        if any(u.level_id == level_id for u in self.db.users()):
            raise ValueError(f"Choose another level for everyone on {level.name} first")
        self.db.delete_level(level_id)
        self.reload()

    def users_on(self) -> dict[int, int]:
        """How many users each level has (Adult counts those with none)."""
        adult = self.level(None).id
        out: dict[int, int] = {}
        for u in self.db.users():
            key = u.level_id if u.level_id in self._levels else adult
            out[key] = out.get(key, 0) + 1
        return out

    # Someone's level and stations ---------------------------------------------

    def set_user(self, user: User, level_id: int | None, stations: dict[int, bool] | None) -> None:
        """A user's level, and (if given) the stations allowed or blocked
        for them. ValueError."""
        if level_id is not None and level_id not in self._levels:
            raise ValueError("That Viewing Level has been removed")
        if self.level(level_id).builtin == ADULT:
            level_id = None
        self.db.set_user_level(user.id, level_id)
        if stations is not None:
            self.db.set_user_stations(user.id, stations)
        self.reload()

    def stations_of(self, user_id: int) -> dict[int, bool]:
        return dict(self._stations.get(user_id, {}))

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
            return Viewer(Level(0, "", 0, 0, False, frozenset()), everything=False)
        if now.role == ADMIN:
            return EVERYONE
        level = self.level(now.level_id)
        stations = self._stations.get(now.id, {})
        blocked = frozenset(c for c, allowed in stations.items() if not allowed)
        return Viewer(
            level,
            everything=not level.limited and not blocked,
            allowed=frozenset(c for c, allowed in stations.items() if allowed),
            blocked=blocked,
        )

    def sees_station(self, viewer: Viewer, channel_id: int) -> bool:
        if viewer.everything:
            return True
        if channel_id in viewer.blocked:
            return False
        if channel_id in viewer.allowed:
            return True
        return viewer.level.allows_reach(self.reach(channel_id))

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
    return Level(
        row["id"], row["name"], row["movie_age"], row["tv_age"], bool(row["unrated"]),
        libraries, row["builtin"],
    )  # fmt: skip


# The Access tab's addresses (for Admins only: see access.FOR_USERS) -----------


class LevelIn(BaseModel):
    name: str = Field(max_length=100)
    movieAge: int | None = None  # (null: no limit)
    tvAge: int | None = None
    unrated: bool = True
    libraries: list[str] | None = Field(default=None, max_length=500)  # (null: all)


class UserViewing(BaseModel):
    """What's given changes: a level (null: Adult), and the stations allowed
    (true) or blocked (false) for them, by id (any not listed are neither)."""

    level: int | None = None
    stations: dict[str, bool] | None = Field(default=None, max_length=10_000)


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
            "every library" if level.libraries is None else plural_libraries(len(level.libraries))
        )
        return f"{movies}, {tv}, {unrated}, {libraries}"

    @app.get("/api/access/viewing")
    async def viewing_state() -> dict[str, Any]:
        on = v.users_on()
        return {
            "levels": [lv.as_json(on.get(lv.id, 0)) for lv in v.levels()],
            "users": {
                str(u.id): {
                    "level": v.level(u.level_id).id,
                    "stations": {str(c): a for c, a in v.stations_of(u.id).items()},
                }
                for u in ctx.db.users()
            },
            "movieRatings": [[age, name] for age, name in ratings.MOVIE_AT.items()],
            "tvRatings": [[age, name] for age, name in ratings.TV_AT.items()],
        }

    def level_from(body: LevelIn, level_id: int | None) -> Level:
        try:
            return v.save_level(
                level_id, body.name, body.movieAge, body.tvAge, body.unrated, body.libraries
            )
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
        level_id = body.level if "level" in body.model_fields_set else user.level_id
        stations = None
        if body.stations is not None:
            try:
                stations = {int(k): bool(a) for k, a in body.stations.items()}
            except ValueError:
                raise HTTPException(400, "Stations are given by their id") from None
        try:
            v.set_user(user, level_id, stations)
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
        if said:
            ctx.access.record(logging.INFO, f"{who(request)} {' and '.join(said)}")
        return {
            "level": now_level.id,
            "stations": {str(c): a for c, a in v.stations_of(user.id).items()},
        }

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
            why = None if viewer.everything else viewer.level.why_not(v.reach(c.id))
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


def plural_libraries(n: int) -> str:
    return f"{n} librar{'y' if n == 1 else 'ies'}"


def _numbers(numbers: list[int]) -> str:
    """Stations by number: "station 7", "stations 7 and 9", "stations 3, 7 and 9"."""
    if len(numbers) == 1:
        return f"station {numbers[0]}"
    listed = [str(n) for n in numbers]
    return f"stations {', '.join(listed[:-1])} and {listed[-1]}"
