"""Commercials and trailers under limits (1.33.0; see docs/users.md,
"Commercials and trailers").

An Admin rates each clip folder: `commercials` and `trailers` (all of
them, from every Media folder), and each decade's folder in them
(`commercials/1960s`). A clip's rating is its decade folder's, or, if that
folder isn't rated, its kind's. Ratings are kept as ages, as levels keep
theirs (see ratings.py).

On a station someone with limits can see, a clip plays only if it's rated,
and at or below the highest-rated program on the station: unrated clips
are skipped until an Admin rates their folder (an Admin alert says how many
stations that affects). On a station only people without limits can see,
every clip plays, as before. A clip never changes who can see a station.

It's decided when a station's lineup is made (Updater.with_breaks), and
again as each clip is about to play (Broadcaster), so a station that
someone with limits can now see, since its lineup was made, shows a plain
card in a clip's place rather than the clip.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, StrictInt

from . import access, ratings
from .breaks import COMMERCIALS, TRAILERS, Clip

if TYPE_CHECKING:
    from .db import Database
    from .main import AppContext
    from .viewing import Reach

META = "clip_ratings"
# A decade's folder, as ratings name it: 1930s to 2020s (see breaks.decade_of).
_DECADE = re.compile(r"(19[3-9]0|20[0-2]0)s", re.ASCII)
AGE_MOST = 18


def folder_key(kind: str, decade: int | None) -> str:
    """A clip folder, as ratings name it: "commercials", "trailers/1990s"."""
    return kind if decade is None else f"{kind}/{decade}s"


def cap(reach: Reach) -> int | None:
    """The highest a station's clips may be rated, as an age: its highest-
    rated program's (None: none of its programs is rated)."""
    ages = [a for a in (reach.movie_age, reach.tv_age) if a is not None]
    return max(ages) if ages else None


def allowed(age: int | None, most: int | None) -> bool:
    """Whether a clip rated `age` (None: not rated) plays on a station
    someone with limits can see, whose clips may be rated up to `most`."""
    return age is not None and most is not None and age <= most


@dataclass(frozen=True)
class Folder:
    key: str
    kind: str
    decade: int | None
    clips: int
    age: int | None  # its own rating (None: not rated)


class ClipRatings:
    """The clip folders' ratings, as an Admin chose them."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._ages: dict[str, int] = _load(db.get_meta(META, ""))

    @property
    def signature(self) -> str:
        """Changes whenever a rating does (so lineups are made again)."""
        return json.dumps(self._ages, sort_keys=True)

    def own(self, key: str) -> int | None:
        return self._ages.get(key)

    def age(self, kind: str, clip: Clip) -> int | None:
        """A clip's rating: its decade folder's, or its kind's."""
        if clip.decade is not None:
            found = self._ages.get(folder_key(kind, clip.decade))
            if found is not None:
                return found
        return self._ages.get(kind)

    def rated(self, kind: str, clip: Clip, most: int | None) -> bool:
        return allowed(self.age(kind, clip), most)

    def save(self, ages: dict[str, int | None]) -> None:
        """Ratings for these folders (None: not rated); the rest keep
        theirs (so a decade folder Plex can't list just now keeps its
        rating). ValueError if one won't do, and then nothing changes."""
        cleaned = dict(self._ages)
        for key, age in ages.items():
            kind, slash, decade = str(key).partition("/")
            if kind not in (COMMERCIALS, TRAILERS) or (slash and not _DECADE.fullmatch(decade)):
                raise ValueError("Choose a commercials or trailers folder")
            if age is None:
                cleaned.pop(str(key), None)
                continue
            if not isinstance(age, int) or isinstance(age, bool) or not 0 <= age <= AGE_MOST:
                raise ValueError("Choose a rating from the list")
            cleaned[str(key)] = age
        self._ages = cleaned
        self.db.set_meta(META, json.dumps(cleaned, sort_keys=True))

    def folders(self, pools: dict[str, list[Clip]]) -> list[Folder]:
        """The clip folders there are (each kind, and its decades), with
        how many clips each has, and their own ratings."""
        out: list[Folder] = []
        for kind in (COMMERCIALS, TRAILERS):
            clips = pools.get(kind, [])
            out.append(Folder(kind, kind, None, len(clips), self._ages.get(kind)))
            decades = sorted({c.decade for c in clips if c.decade is not None})
            for d in decades:
                key = folder_key(kind, d)
                n = sum(1 for c in clips if c.decade == d)
                out.append(Folder(key, kind, d, n, self._ages.get(key)))
        return out

    def unrated(self, kind: str, clips: list[Clip]) -> int:
        """How many of `clips` aren't rated."""
        return sum(1 for c in clips if self.age(kind, c) is None)


def _load(text: str) -> dict[str, int]:
    try:
        got = json.loads(text or "{}")
        return {
            str(k): int(v)
            for k, v in got.items()
            if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= AGE_MOST
        }
    except (ValueError, TypeError, AttributeError):
        return {}


# The Access tab's addresses (for Admins only: see access.FOR_USERS) -----------


class RatingsIn(BaseModel):
    # Each folder's rating, as an age (null: not rated), by its key.
    ratings: dict[str, StrictInt | None] = Field(max_length=200)


def routes(app: FastAPI, ctx: AppContext) -> None:
    def said(age: int | None, kind: str) -> str:
        if age is None:
            return "not rated"
        return ratings.named(age, tv=kind == COMMERCIALS).removeprefix("rated ")

    def state() -> dict[str, Any]:
        pools = {kind: ctx.fillers.pool(kind) for kind in (COMMERCIALS, TRAILERS)}
        return {
            "folders": [
                {"key": f.key, "kind": f.kind, "decade": f.decade, "clips": f.clips, "age": f.age}
                for f in ctx.clip_ratings.folders(pools)
            ],
            "movieRatings": [[age, name] for age, name in ratings.MOVIE_AT.items()],
            "tvRatings": [[age, name] for age, name in ratings.TV_AT.items()],
        }

    @app.get("/api/access/clips")
    async def clip_ratings() -> dict[str, Any]:
        """The commercials and trailers folders, and their ratings."""
        return state()

    @app.put("/api/access/clips")
    async def rate_clips(body: RatingsIn, request: Request) -> dict[str, Any]:
        before = {k: ctx.clip_ratings.own(k) for k in body.ratings}
        try:
            ctx.clip_ratings.save(body.ratings)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        changed = [
            f"{key} {said(age, key.partition('/')[0])}"
            for key, age in sorted(body.ratings.items())
            if before.get(key) != age
        ]
        if changed:
            user = access.signed_in(request)
            ctx.access.record(
                logging.INFO,
                f"{user.name if user else 'Someone'} rated the clip folders: {', '.join(changed)}",
            )
        return state()
