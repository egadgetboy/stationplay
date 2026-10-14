"""What tapiOca uses (1.37.0): where your shows and movies come from (Plex,
Media folders of your own, or both), and where you watch (tapiOca's apps,
Plex, Jellyfin, Emby, Kodi, other apps). An Admin chooses them in the
setup (Your shows and movies, Where you watch) or under What you use on the
Setup tab.

They change only what tapiOca's page shows: the steps for each place, and
which apps its sentences name. Never what the tuner, playlist or guide give
any app, Tuner access, limits, updates or Plex's guide refresh ("Never limit
Plex, Jellyfin or other clients"). So only main.py reads them, and a test
keeps it so.

Until an Admin saves them, nothing is chosen and the page is as it was in
1.36.0. What's set up always counts as chosen: Plex while PLEX_URL and
PLEX_TOKEN are set, your own folders while there's one. So a choice can add
what isn't set up yet, never hide what is. Kept in one `meta` row: no table
changes."""

from __future__ import annotations

import json
from typing import Any

META = "uses"  # {"sources": [...], "watchIn": [...]} (JSON)
SOURCES = ("plex", "folders")
PLACES = ("tapioca", "plex", "jellyfin", "emby", "kodi", "other")
SOURCE_NAMES = {"plex": "Plex", "folders": "Media folders of your own"}
PLACE_NAMES = {
    "tapioca": "tapiOca's apps", "plex": "Plex", "jellyfin": "Jellyfin", "emby": "Emby",
    "kodi": "Kodi", "other": "other apps",
}  # fmt: skip
NO_SOURCE = "Choose Plex, Media folders of your own, or both."
NO_PLACE = "Choose at least one place you'll watch."


def _known(values: Any, known: tuple[str, ...]) -> list[str] | None:
    """`values` in canonical order, without repeats; None unless it's a
    list of known values."""
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        return None
    if any(v not in known for v in values):
        return None
    return [k for k in known if k in values]


def load(db: Any) -> tuple[list[str] | None, list[str] | None]:
    """What's stored: (sources, watchIn), each None if never saved (or
    unreadable)."""
    try:
        got = json.loads(db.get_meta(META) or "{}")
    except ValueError:
        return None, None
    if not isinstance(got, dict):
        return None, None
    sources = _known(got.get("sources"), SOURCES)
    places = _known(got.get("watchIn"), PLACES)
    return sources or None, places or None


def reality(plex_set_up: bool, own_folders: bool) -> list[str]:
    """The sources that are set up."""
    return [s for s, on in (("plex", plex_set_up), ("folders", own_folders)) if on]


def save(
    db: Any,
    sources: list[str] | None = None,
    watch_in: list[str] | None = None,
    *,
    plex_set_up: bool,
    own_folders: bool,
) -> tuple[list[str] | None, list[str] | None]:
    """Saves what's given (None leaves it as it is); what's stored then.
    Sources are stored with what's set up added. ValueError, with the
    sentence to show, for an empty choice or an unknown value."""
    stored_sources, stored_places = load(db)
    if sources is not None:
        chosen = _known(sources, SOURCES)
        if chosen is None:
            raise ValueError(NO_SOURCE)
        chosen = [s for s in SOURCES if s in chosen or s in reality(plex_set_up, own_folders)]
        if not chosen:
            raise ValueError(NO_SOURCE)
        stored_sources = chosen
    if watch_in is not None:
        places = _known(watch_in, PLACES)
        if not places:
            raise ValueError(NO_PLACE)
        stored_places = places
    kept: dict[str, list[str]] = {}
    if stored_sources:
        kept["sources"] = stored_sources
    if stored_places:
        kept["watchIn"] = stored_places
    db.set_meta(META, json.dumps(kept))
    return stored_sources, stored_places


def sources_now(stored: list[str] | None, plex_set_up: bool, own_folders: bool) -> list[str]:
    """The sources in effect: what's chosen and what's set up. With nothing
    chosen, 1.36.0's rule: Plex unless there's a Media folder of your own
    and no Plex."""
    if stored is None:
        plex = plex_set_up or not own_folders
        return [s for s, on in (("plex", plex), ("folders", own_folders)) if on]
    return [s for s in SOURCES if s in stored or s in reality(plex_set_up, own_folders)]


def plex_used(stored: list[str] | None, plex_set_up: bool, own_folders: bool) -> bool:
    """Whether tapiOca uses Plex as a source: it's set up, or chosen, or
    (nothing chosen) there's nothing else."""
    return "plex" in sources_now(stored, plex_set_up, own_folders)


def said(values: list[str] | None, names: dict[str, str]) -> str:
    """Values as the log says them: "Plex, Jellyfin"."""
    return ", ".join(names[v] for v in values or [])
