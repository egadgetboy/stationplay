"""Smart stations: stations made from a filter (as in the station editor:
movies or TV shows from some libraries, with the genres, decades, studios
and so on Plex has for them), one of them, or one for each decade, genre,
studio... the filter's matches fall into ("Split by").

Each station made is an ordinary station whose one source is the filter
with its own decade or tag added, so it follows Plex like any filter: new
matches join it on their own. Everything comes from Plex: the choices are
the ones Plex lists for those libraries, and the counts are Plex's answers.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from .library import Library
from .plex import PEOPLE_FIELDS, filter_tags, gather_all

MAX_STATIONS = 50  # made at once
# Values a split is counted for, at most (the most common first): Plex is
# asked once for each.
MAX_GROUPS = 40
ASKED_AT_ONCE = 4


def _label(m: dict[str, Any]) -> tuple[str, Any]:
    """A movie or show as one title (one in two libraries is still one)."""
    return str(m.get("title", "")).casefold(), m.get("year")


def _count(matches: list[dict[str, Any]]) -> tuple[int, int]:
    """How many titles, and (for TV) episodes."""
    seen: dict[tuple, int] = {}
    for m in matches:
        seen[_label(m)] = max(seen.get(_label(m), 0), int(m.get("leafCount") or 0))
    return len(seen), sum(seen.values())


def _values(m: dict[str, Any], field: str) -> list[str]:
    """What a movie or show has as `field`, as Plex lists it: a plain value
    (studio, content rating) or tags (genres...). Plex lists only the
    first few of some tags in a library's list, so this is a guide to which
    are most common, not a count."""
    value = m.get(field)
    if isinstance(value, str):
        return [value]
    # (Plex lists a program's cast as its Roles.)
    name = field[:1].upper() + field[1:]
    tags = m.get(_LISTED_AS.get(field, name)) or m.get(name) or []
    return [str(t["tag"]) for t in tags if isinstance(t, dict) and t.get("tag")]


_LISTED_AS = {"actor": "Role"}


class SplitProblem(ValueError):
    """Why a filter can't be split that way."""


def with_value(source: dict[str, Any], field: str, value: Any) -> dict[str, Any]:
    """`source` narrowed to one decade or one tag value."""
    out = {**source}
    if field == "decade":
        out["decade"] = [int(value)]
    else:
        out["tags"] = {**(source.get("tags") or {}), field: [str(value)]}
    return out


async def split(
    library: Library, source: dict[str, Any], field: str
) -> tuple[list[dict[str, Any]], bool]:
    """What `source` (a filter) matches for each value of `field` ("decade",
    or a tag: genre, studio...), as [{"value", "matches", "episodes"}],
    leaving out values nothing matches; and whether only the first
    MAX_GROUPS values were asked about. Decades in order; tags the most
    matches first, or in the order chosen when the filter already names
    some (then each of those is a group). SplitProblem if it can't be
    split that way."""
    kind = "show" if source.get("kind") == "show" else "movie"
    if field == "decade":
        chosen = {int(d) for d in source.get("decade") or []}
        groups: dict[int, list[dict]] = {}
        for m in await library.filter_matches(source):
            year = m.get("year")
            if isinstance(year, int) and (not chosen or year // 10 * 10 in chosen):
                groups.setdefault(year // 10 * 10, []).append(m)
        return [_group(d, groups[d]) for d in sorted(groups)], False
    chosen_values = list(filter_tags(source).get(field) or [])
    limited = len(chosen_values) > MAX_GROUPS
    if chosen_values:
        candidates = chosen_values[:MAX_GROUPS]
    else:
        offered: dict[str, str] = {}
        for key in source.get("libraries") or []:
            for c in await library.choices(str(key), field, kind):
                offered.setdefault(c["title"].casefold(), c["title"])
        common = Counter(
            v.casefold() for m in await library.filter_matches(source) for v in _values(m, field)
        )
        if field in PEOPLE_FIELDS and not any(common.get(v) for v in offered):
            # Plex's lists don't say who's in what for this: no telling
            # which of thousands to ask about.
            raise SplitProblem(f"In the filter above, choose which {field}s to make stations for")
        ranked = sorted(offered, key=lambda v: (-common.get(v, 0), v))
        limited = len(ranked) > MAX_GROUPS
        candidates = [offered[v] for v in ranked[:MAX_GROUPS]]
    slots = asyncio.Semaphore(ASKED_AT_ONCE)

    async def matches(value: str) -> list[dict]:
        async with slots:
            return await library.filter_matches(with_value(source, field, value))

    found = await gather_all(matches(v) for v in candidates)
    out = [_group(v, f) for v, f in zip(candidates, found, strict=True) if f]
    if not chosen_values:
        out.sort(key=lambda g: (-g["matches"], str(g["value"]).casefold()))
    return out, limited


def _group(value: Any, matches: list[dict]) -> dict[str, Any]:
    titles, episodes = _count(matches)
    return {"value": value, "matches": titles, "episodes": episodes}
