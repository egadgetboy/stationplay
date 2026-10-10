"""Replacing broken files with Sonarr and Radarr: optional, and off unless
it's set up on the Broken files tab. StationPlay itself only ever needs
Plex; this asks the apps you already use to fetch a better file.

Each time the broken-files list is gone through (see jobs.py), for each
file on it that's broken or damaged (not unsupported), whether a station
plays it, Media in StationPlay's apps does, or both, of the kind they're to
replace (what(): broken or damaged files, missing ones, or both), that
you've said to replace (when(): when you say so, with Replace on the list,
unless you've chosen Automatically, when you can say Leave this one to me
instead), found in Sonarr (an episode) or Radarr (a movie) as exactly one
show and episode, or movie, there, and only while the app is monitoring it
(Sonarr: the show and the episode, as its own searches go by; Radarr: the
movie), so what you've unmonitored, or removed on purpose, is left alone.
For a file that's one of a program's versions, only when the app's file is
that one:

  * A broken or damaged file: the release it came from is blocklisted
    first (its grab marked as failed, as History's "Mark as Failed" does),
    so the app won't download that file again; only then is the file
    removed (into the app's recycle bin, if it has one), and the app asked
    to search for another. Only if the app's file is the very one found
    broken (the same name and size), and only if the app has a record of
    downloading it: a file added by hand can't be blocklisted, so it's left
    for you, saying so.
  * A missing file (removed from Plex while a station has it, or not
    found): the app looks at what's on disk first, then searches for it.

An episode or movie gets at most three searches (TRIES), 8 hours apart
unless the last one brought a new file, so three in about a day; when
they're spent with nothing to show for it, it stays on the list, saying
so, and nothing more is tried until you choose Try again. While the app is
downloading, nothing else is done. When it has the new file, Plex is asked
to look in that folder; StationPlay checks the new file like any new one,
and the program comes off the list and is back on the air if it passes
(jobs.py). If it doesn't, its release is blocklisted in turn; unless it has
the same problem at the same places as the file it replaced (see
same_problem): then it may be how the program was made (an old film's
effects, say), not a bad file, so nothing more is tried, and it's left for
you to look at. Retry puts it back on the air; Try another has the app look
for another.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .arr import APPS, GRABBED, IMPORTED, NAMES, RADARR, SONARR, Arr, ArrError, clean_url
from .broken import file_key
from .db import Item
from .library import LibraryError
from .sources import REMOVED

if TYPE_CHECKING:
    from .main import AppContext

log = logging.getLogger(__name__)

TRIES = 3
TRY_GAP_MS = 8 * 3600 * 1000
# Asking Plex to look in a folder for the new file: at most this often.
NUDGE_GAP_MS = 3600 * 1000
# The app has a file Plex hasn't found for this long: it's left to you.
PLEX_FINDS_MS = 24 * 3600 * 1000
# How long the app has to look at what's on disk before a search.
RESCAN_WAIT_S = 120.0
RESCAN_POLL_S = 2.0
# Tries are remembered for this long after the last (so a program that
# comes back on the list soon after isn't tried afresh), and as long as an
# entry on the list is about that episode or movie.
KEEP_TRIES_MS = 7 * 86_400 * 1000
META_SETTINGS = "arr_settings"
# What they replace: broken or damaged files, missing ones, or both.
BROKEN, MISSING, BOTH = "broken", "missing", "both"
WHATS = (BOTH, BROKEN, MISSING)
# When: when you say so (each entry's Replace), or by themselves.
ASK, AUTO = "ask", "auto"
WHENS = (ASK, AUTO)
META_TRIES = "arr_tries"
# A new file's problem is the one the file it replaced had (see
# same_problem) when it's said in the same words, at the same places: most
# of them within this of one before (a new release of the same program
# can run a little differently).
SAME_PLACE_S = 30.0
_PLACE = re.compile(r"\b(\d+):(\d\d)(?::(\d\d))?\b")

# What's happening, as an entry on the list says (its "replace"): left to
# you, too, when you've said Leave this one to me, or a new file has the
# same problem in the same places as the one it replaced.
SEARCHING, DOWNLOADING, DOWNLOADED, GAVE_UP, CANT, SAME, LEFT = (
    "searching",
    "downloading",
    "downloaded",
    "gave up",
    "can't",
    "same",
    "left",
)
DONE = (GAVE_UP, CANT, SAME, LEFT)  # nothing more is tried until you say so
GOING = (SEARCHING, DOWNLOADING, DOWNLOADED)
# Where an entry on the list is on the Broken files tab (see tab_section).
NEEDS_YOU, BEING_REPLACED, FOUND_ONLY = "needs you", "being replaced", "found"
# What a missing file was found to be (the quick check's "Check: " aside).
_MISSING = (REMOVED, "file not found", "no longer in Plex")


def now_ms() -> int:
    return int(time.time() * 1000)


# Settings ----------------------------------------------------------------------------


def _saved(db) -> dict[str, Any]:
    try:
        saved = json.loads(db.get_meta(META_SETTINGS, "") or "{}")
    except ValueError:
        saved = {}
    return saved if isinstance(saved, dict) else {}


def settings(db) -> dict[str, dict[str, Any]]:
    """{app: {"url", "key", "on"}} as saved (the key is never sent to the page)."""
    saved = _saved(db)
    out = {}
    for app in APPS:
        got = saved.get(app)
        got = got if isinstance(got, dict) else {}
        out[app] = {
            "url": str(got.get("url") or ""),
            "key": str(got.get("key") or ""),
            "on": bool(got.get("on")) and bool(got.get("url")) and bool(got.get("key")),
        }
    return out


def shown(db) -> dict[str, dict[str, Any]]:
    """The settings, for the page: no keys."""
    return {
        app: {"url": s["url"], "on": s["on"], "hasKey": bool(s["key"])}
        for app, s in settings(db).items()
    }


def save(db, app: str, url: str, key: str | None, on: bool) -> None:
    """Saves one app's settings (`key` None: it stays as it was). ValueError
    if they won't do."""
    if app not in APPS:
        raise ValueError("That's neither Sonarr nor Radarr")
    current = settings(db)
    url = clean_url(url) if url.strip() else ""
    key = current[app]["key"] if key is None else key.strip()
    if key and not key.isalnum():
        raise ValueError(
            f"That isn't a valid API key ({NAMES[app]}'s has only letters and numbers)"
        )
    if on and not (url and key):
        raise ValueError(f"Enter {NAMES[app]}'s address and API key to turn it on")
    current[app] = {"url": url, "key": key, "on": on}
    _store(db, current)


def _store(db, changed: dict[str, Any]) -> None:
    """Saves the settings with what's `changed` in them."""
    db.set_meta(
        META_SETTINGS, json.dumps({**settings(db), "what": what(db), "when": when(db), **changed})
    )


def what(db) -> str:
    """What they replace (WHATS): both unless chosen otherwise."""
    chosen = _saved(db).get("what")
    return chosen if chosen in WHATS else BOTH


def save_what(db, chosen: str) -> None:
    if chosen not in WHATS:
        raise ValueError(f"What to replace must be one of: {', '.join(WHATS)}")
    _store(db, {"what": chosen})


def when(db) -> str:
    """When they replace (WHENS): when you say so unless chosen otherwise."""
    chosen = _saved(db).get("when")
    return chosen if chosen in WHENS else ASK


def save_when(db, chosen: str) -> None:
    if chosen not in WHENS:
        raise ValueError(f"When to replace must be one of: {', '.join(WHENS)}")
    _store(db, {"when": chosen})


def enabled(db, app: str) -> bool:
    return settings(db)[app]["on"]


def missing(entry: dict[str, Any]) -> bool:
    """Whether an entry is about a missing file (gone from disk, or from
    Plex), not a broken or damaged one."""
    reason = str(entry.get("reason", ""))
    reason = reason.removeprefix("Check: ")
    return reason.startswith(_MISSING)


def wanted(db, entry: dict[str, Any]) -> bool:
    """Whether an entry is of the kind they're to replace (see what())."""
    chosen = what(db)
    return chosen == BOTH or (chosen == MISSING) == missing(entry)


def app_for(entry: dict[str, Any]) -> str:
    return SONARR if entry.get("show") else RADARR


def held(db, entry: dict[str, Any]) -> bool:
    """Whether an entry is being replaced (or was tried, and wants your look),
    so it stays on the list even once no station has it; not one you've
    said to leave to you."""
    state = entry.get("replace") or {}
    return (
        bool(state)
        and state.get("state") != LEFT
        and enabled(db, app_for(entry))
        and wanted(db, entry)
    )


def tab_section(db, entry: dict[str, Any], used: bool) -> str:
    """Where an entry on the list is on the Broken files tab: waiting for you
    (a broken or damaged file a station or Media plays, `used`, that Sonarr
    or Radarr isn't replacing by itself, for you to choose Replace or see to
    it yourself; or one they couldn't replace); being replaced (what they're
    fetching now, or are about to: asked for, or by themselves, at the next
    look, for a file that's used); or only found (the rest: unsupported
    files, those you've said to leave to you, and those nothing plays now,
    which wait for no one: a missing one comes off the list by itself, and
    a broken one stays so a station never takes it up again unnoticed)."""
    if entry.get("problem") not in ("broken", "damaged"):
        return FOUND_ONLY
    state = entry.get("replace") or {}
    now = state.get("state")
    if now == LEFT:
        return FOUND_ONLY
    if now in GOING:
        return BEING_REPLACED
    if now in DONE:
        return NEEDS_YOU
    if (
        enabled(db, app_for(entry))
        and wanted(db, entry)
        and (state.get("asked") or (when(db) == AUTO and used))
    ):
        return BEING_REPLACED
    return NEEDS_YOU if used else FOUND_ONLY


def needs_you_said(entry: dict[str, Any], name: str) -> tuple[int, str, str]:
    """An entry waiting for you (see tab_section), as an Admin's alert says
    it (see alerts.py): (when, which, what), such as "StationPlay found
    Northbound S2 E5 broken" (`name`: the program, as the alert names it)."""
    state = entry.get("replace") or {}
    app = NAMES.get(str(state.get("app") or app_for(entry)), "Sonarr")
    said = {
        GAVE_UP: f"{app} couldn't find a file of {name} that plays",
        CANT: f"{app} can't replace {name}",
        SAME: f"the new file of {name} has the same problem as the old one",
    }.get(str(state.get("state")))
    if said is None:
        said = (
            f"{name}'s file is missing"
            if missing(entry)
            else f"StationPlay found {name} {entry.get('problem') or 'broken'}"
        )
    at = state.get("at") if state.get("state") in DONE else None
    if not isinstance(at, int):
        try:
            at = int(datetime.fromisoformat(str(entry.get("lastFailed"))).timestamp() * 1000)
        except ValueError:
            at = 0
    return at, f"file:{file_key(entry)}", said


async def better_copy(ctx: AppContext, entry: dict[str, Any]) -> str:
    """Find a better copy (for a person's report: see reports.py): Sonarr or
    Radarr searches for an upgrade of an episode or movie, keeping its file
    (it takes one only if its own quality settings say it's better). Only
    while the app monitors it, as for replacing. What it's doing, for the
    tab. Cant, ArrError or LibraryError if it can't."""
    app = app_for(entry)
    conf = settings(ctx.db)[app]
    if not conf["on"]:
        raise Cant(f"{NAMES[app]} isn't turned on")
    arr = Arr(app, conf["url"], conf["key"], transport=ctx.arr_transport)
    found = await _find(ctx, Round(arr), entry, {}, {})
    await _monitored(arr, found)
    await arr.search(found.item)
    log.info("%s: searching for a better copy of %s", arr.name, found.label)
    return f"{arr.name} is searching for a better copy"


def entry_item(entry: dict[str, Any]) -> Item | None:
    """An entry's program as it was, to ask Plex if it has it again (an
    episode needs its show's key, which replacing it remembers)."""
    show = entry.get("show")
    state = entry.get("replace") or {}
    if show and not (state.get("showKey") or entry.get("showKey")):
        return None

    def number(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return Item(
        position=0,
        start_ms=0,
        duration_ms=0,
        rating_key=str(entry["ratingKey"]),
        kind="episode" if show else "movie",
        title=str(entry.get("title") or ""),
        show_title=str(show) if show else None,
        show_key=str(state.get("showKey") or entry.get("showKey")) if show else None,
        season=number(entry.get("season")),
        episode=number(entry.get("episode")),
        year=number(entry.get("year")),
        file_path=entry.get("file") if isinstance(entry.get("file"), str) else None,
    )


# Tries, by episode or movie -----------------------------------------------------------


def _load_tries(db) -> dict[str, dict[str, Any]]:
    try:
        got = json.loads(db.get_meta(META_TRIES, "") or "{}")
    except ValueError:
        return {}
    return {k: v for k, v in got.items() if isinstance(v, dict)} if isinstance(got, dict) else {}


def _save_tries(db, tries: dict[str, dict[str, Any]], kept: set[str]) -> None:
    now = now_ms()
    db.set_meta(
        META_TRIES,
        json.dumps(
            {
                k: v
                for k, v in tries.items()
                if k in kept or now - max(v.get("tries") or [0]) < KEEP_TRIES_MS
            }
        ),
    )


def _may_try(tried: dict[str, Any], now: int) -> bool:
    tries = tried.get("tries") or []
    if tried.get("gaveUp") or len(tries) >= TRIES:
        return False
    return not tries or bool(tried.get("fetched")) or now - tries[-1] >= TRY_GAP_MS


def _spent(tried: dict[str, Any], now: int) -> bool:
    tries = tried.get("tries") or []
    return len(tries) >= TRIES and (bool(tried.get("fetched")) or now - tries[-1] >= TRY_GAP_MS)


def _next_try(tried: dict[str, Any]) -> str:
    when = (tried.get("tries") or [0])[-1] + TRY_GAP_MS
    return time.strftime("%-I:%M %p", time.localtime(when / 1000))


# Going through the list ------------------------------------------------------------------


@dataclass
class Found:
    """An entry's episode (in Sonarr) or movie (in Radarr)."""

    item: int  # the episode's or movie's id
    parent: int  # the show's id (Sonarr), or the movie's again (Radarr)
    label: str


class Cant(Exception):
    """It can't be replaced this way: why, for the list."""


@dataclass
class Round:
    """One time through the list, for one app: what's been asked already."""

    arr: Arr
    episodes: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    async def episodes_of(self, series_id: int) -> list[dict[str, Any]]:
        if series_id not in self.episodes:
            self.episodes[series_id] = await self.arr.episodes(series_id)
        return self.episodes[series_id]


async def replace_all(ctx: AppContext, by_key: dict[str, Item], only: str | None = None) -> None:
    """Does what's next for each file on the list (see above). `by_key`:
    the programs on a station (or in an update waiting to start), by key;
    `only`, just that entry (by its file key). Stops for an app it can't
    reach, till next time."""
    conf = settings(ctx.db)
    rounds = {
        app: Round(Arr(app, c["url"], c["key"], transport=ctx.arr_transport))
        for app, c in conf.items()
        if c["on"]
    }
    if not rounds:
        return
    tries = _load_tries(ctx.db)
    chosen = what(ctx.db)
    asking = when(ctx.db) == ASK
    changed: dict[str, tuple[Any, dict[str, Any]]] = {}
    try:
        for entry in ctx.broken.entries():
            key = file_key(entry)
            app = app_for(entry)
            r = rounds.get(app)
            if r is None or (only is not None and key != only):
                continue
            if entry.get("problem") not in ("broken", "damaged"):
                continue
            if chosen != BOTH and (chosen == MISSING) != missing(entry):
                # Not what they replace now: left to you (anything begun is
                # forgotten; its tries are remembered for a while).
                if entry.get("replace"):
                    changed[key] = (entry.get("lastFailed"), {})
                continue
            state = dict(entry.get("replace") or {})
            # (A station plays a program's first version: never another.)
            on_a_station = not entry.get("version") and str(entry["ratingKey"]) in by_key
            used = on_a_station or ctx.in_media(entry)
            if state.get("state") in DONE or (not used and not state):
                continue  # (left to you; or neither a station nor Media has it, and it wasn't begun)
            if asking and not state:
                continue  # (until you say so)
            # (What's found of it is kept even if it can't be replaced.)
            work = dict(state)
            try:
                after = await _one(ctx, r, entry, work, by_key, tries)
            except Cant as e:
                after = {**work, "state": CANT, "note": str(e), "at": now_ms()}
                log.info("%s can't replace %s: %s", r.arr.name, entry_label(entry), e)
            except ArrError as e:
                if e.status is not None and 400 <= e.status < 500 and e.status != 401:
                    log.info(
                        "%s: %s (for %s); trying again later", r.arr.name, e, entry_label(entry)
                    )
                    continue
                note(ctx, app, str(e))
                del rounds[app]  # (it's away, or the key's wrong: next time)
                continue
            except LibraryError as e:
                log.info(
                    "Replacing %s is on hold: Plex isn't available (%s)", entry_label(entry), e
                )
                continue
            note(ctx, app, "")
            if after != state:
                changed[key] = (entry.get("lastFailed"), after)
    finally:
        if changed:
            ctx.broken.replacing(changed)
        kept = {
            f"{app_for(e)}:{e['replace']['id']}"
            for e in ctx.broken.entries()
            if (e.get("replace") or {}).get("id") is not None
        }
        _save_tries(ctx.db, tries, kept)


def note(ctx: AppContext, app: str, problem: str) -> None:
    """How the last time asking the app went, for the page."""
    ctx.arr_status[app] = {"ok": not problem, "problem": problem, "at": now_ms()}


async def _one(
    ctx: AppContext,
    r: Round,
    entry: dict[str, Any],
    state: dict[str, Any],
    by_key: dict[str, Item],
    tries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """What's next for one entry; its replace state after."""
    arr = r.arr
    now = now_ms()
    found = await _find(ctx, r, entry, state, by_key)
    tried = tries.setdefault(f"{arr.app}:{found.item}", {"tries": [], "fetched": False})
    n = len(tried.get("tries") or [])

    def said(what: str, text: str) -> dict[str, Any]:
        return {**state, "state": what, "note": text, "tries": len(tried["tries"]), "at": now}

    queued = await arr.queue(found.item)
    if queued:
        title = str(queued[0].get("title") or "a new file")
        return said(DOWNLOADING, f"{arr.name} is downloading {title}")
    have = await _app_file(r, found)
    gone = missing(entry)
    if have is not None and gone and not state.get("rescanned"):
        # The app may not know the file's gone: it looks first.
        await _rescan(arr, found)
        state["rescanned"] = now
        have = await _app_file(r, found)
    if have is not None and not gone and _same_file(have, entry):
        # The app's file is the one found broken.
        reason = str(entry.get("reason") or "")
        if n and have["id"] != tried.get("removed"):
            tried["fetched"] = True  # (a new file came of the last search, and it's broken too)
            if same_problem(tried.get("problem"), reason):
                log.info(
                    "%s: the new file for %s has the same problem in the same places (%s), so it "
                    "needs your review",
                    arr.name,
                    found.label,
                    reason,
                )
                return said(
                    SAME,
                    "The new file has the same problem in the same places, so the problem may be "
                    "part of the program itself, not a bad file. If it looks fine, choose Retry "
                    "to put it back on the air, or choose Try another file to have "
                    f"{arr.name} find a different one.",
                )
        if not _may_try(tried, now):
            return _waiting(arr, tried, now, said)
        await _monitored(arr, found)
        history = await arr.history(found.item)
        grab = _grab_of(history, have["id"])
        if grab is None:
            raise Cant(
                f"{arr.name} has no record of downloading this file (it may have been added by "
                "hand), so the file can't be blocklisted. Replace it yourself."
            )
        await arr.mark_failed(int(grab["id"]))
        log.info(
            "%s: blocklisted %s, the release that %s's file came from",
            arr.name,
            grab.get("sourceTitle") or "the release",
            found.label,
        )
        await arr.delete_file(have["id"])
        log.info("%s: removed %s's broken file %s", arr.name, found.label, have["name"])
        await arr.search(found.item)
        tried["tries"].append(now)
        tried["fetched"] = False
        tried["removed"] = have["id"]
        tried["problem"] = reason
        log.info(
            "%s: searching for another file for %s (try %d of %d)",
            arr.name,
            found.label,
            len(tried["tries"]),
            TRIES,
        )
        return said(
            SEARCHING,
            f"{arr.name} blocklisted {grab.get('sourceTitle') or 'its release'}, removed the "
            f"file, and is searching for another (try {len(tried['tries'])} of {TRIES})",
        )
    if have is not None and entry.get("version") and not n:
        # (One version of several: the app's file is another of them.)
        raise Cant(
            f"{arr.name}'s file for it is another of its versions, not the one found broken, so "
            "StationPlay leaves this one to you"
        )
    if have is not None:
        # A file Plex hasn't been seen to have: Plex is asked to look.
        if n:
            tried["fetched"] = True
        since = state.get("waitingSince") if state.get("state") == DOWNLOADED else None
        state["waitingSince"] = since or now
        if now - state["waitingSince"] >= PLEX_FINDS_MS:
            raise Cant(f"{arr.name} has {have['name']}, but Plex still hasn't found it after a day")
        await _nudge(ctx, state, now)
        return said(
            DOWNLOADED,
            f"{arr.name} has {have['name']}. StationPlay will check it once Plex finds it.",
        )
    # No file: a search.
    if _may_try(tried, now):
        await _monitored(arr, found)
        await arr.search(found.item)
        tried["tries"].append(now)
        tried["fetched"] = False
        log.info(
            "%s: searching for %s, which is missing (try %d of %d)",
            arr.name,
            found.label,
            len(tried["tries"]),
            TRIES,
        )
        return said(
            SEARCHING, f"{arr.name} is searching for it (try {len(tried['tries'])} of {TRIES})"
        )
    return _waiting(arr, tried, now, said)


def _waiting(arr: Arr, tried: dict[str, Any], now: int, said) -> dict[str, Any]:
    """Tries spent (it's left to you), or the next one's later."""
    if _spent(tried, now):
        tried["gaveUp"] = True
        return said(
            GAVE_UP,
            f"{arr.name} searched {TRIES} times in about a day but didn't find a file that "
            "plays. Replace it yourself, or choose Try again.",
        )
    searched = len(tried.get("tries") or [])
    if searched >= TRIES:
        # (The last search may still bring a file: it's given until then.)
        return said(
            SEARCHING,
            f"{arr.name} has searched {TRIES} times. If it hasn't found a file that plays by "
            f"{_next_try(tried)}, StationPlay will stop trying",
        )
    return said(
        SEARCHING,
        f"{arr.name} has searched {searched} of {TRIES} times so far and will search again "
        f"after {_next_try(tried)}",
    )


async def _find(
    ctx: AppContext, r: Round, entry: dict[str, Any], state: dict[str, Any], by_key: dict[str, Item]
) -> Found:
    """The entry's episode or movie in the app (as found before, or found
    now: exactly one, or Cant)."""
    arr = r.arr
    label = entry_label(entry)
    if state.get("app") == arr.app and isinstance(state.get("id"), int):
        return Found(int(state["id"]), int(state.get("parent") or state["id"]), label)
    key = str(entry["ratingKey"])
    item = by_key.get(key)
    state["app"] = arr.app
    if arr.app == SONARR:
        show_key = (item.show_key if item else None) or state.get("showKey") or entry.get("showKey")
        ids = await _plex_ids(ctx, show_key) if show_key else {}
        tvdb = ids.get("tvdb")
        shows = [s for s in await arr.series(tvdb) if tvdb and str(s.get("tvdbId")) == tvdb]
        if not shows:
            wanted = str(entry.get("show") or "").casefold()
            shows = [s for s in await arr.series() if str(s.get("title", "")).casefold() == wanted]
        if len(shows) != 1:
            raise Cant(f"Sonarr has {_how_many(shows, 'show')} matching {entry.get('show')}")
        series_id = int(shows[0]["id"])
        episodes = [
            e
            for e in await r.episodes_of(series_id)
            if e.get("seasonNumber") == entry.get("season")
            and e.get("episodeNumber") == entry.get("episode")
        ]
        if len(episodes) != 1:
            raise Cant(f"Sonarr has {_how_many(episodes, 'episode')} matching {label}")
        found = Found(int(episodes[0]["id"]), series_id, label)
        state.update(showKey=show_key, section=ids.get("section"))
    else:
        ids = await _plex_ids(ctx, key)
        movies: list[dict[str, Any]] = []
        if ids.get("tmdb"):
            movies = [
                m for m in await arr.movies(ids["tmdb"]) if str(m.get("tmdbId")) == ids["tmdb"]
            ]
        if not movies:
            every = await arr.movies()
            if ids.get("imdb"):
                movies = [m for m in every if m.get("imdbId") == ids["imdb"]]
            if not movies and entry.get("year"):
                title = str(entry.get("title") or "").casefold()
                movies = [
                    m
                    for m in every
                    if str(m.get("title", "")).casefold() == title
                    and m.get("year") == entry["year"]
                ]
        if len(movies) != 1:
            raise Cant(f"Radarr has {_how_many(movies, 'movie')} matching {label}")
        found = Found(int(movies[0]["id"]), int(movies[0]["id"]), label)
        state.update(section=ids.get("section"))
    file = entry.get("file")
    folder = _folder(file) if isinstance(file, str) else ""
    state.update(app=arr.app, id=found.item, parent=found.parent, folder=folder or None)
    return found


async def _monitored(arr: Arr, found: Found) -> None:
    """Cant unless the app is monitoring it: Sonarr the show and the
    episode (as its own searches require), Radarr the movie. Unmonitored is
    how you tell them to leave something be; StationPlay does too."""
    if arr.app == SONARR:
        show = await arr.show(found.parent)
        if show.get("monitored") is not True:
            raise Cant(_unmonitored(arr, "this show"))
        episode = await arr.episode(found.item)
        if episode.get("monitored") is not True:
            raise Cant(_unmonitored(arr, "this episode"))
    elif (await arr.movie(found.item)).get("monitored") is not True:
        raise Cant(_unmonitored(arr, "this movie"))


def _unmonitored(arr: Arr, what: str) -> str:
    return (
        f"{arr.name} isn't monitoring {what}, so StationPlay leaves it alone. To replace the "
        f"file, monitor {what} in {arr.name}, then choose Try again."
    )


async def _plex_ids(ctx: AppContext, rating_key: str) -> dict[str, str]:
    try:
        return await ctx.library.ids(rating_key)
    except LibraryError as e:
        if e.status == 404:
            return {}  # (gone from Plex: found by its title instead)
        raise


async def _app_file(r: Round, found: Found) -> dict[str, Any] | None:
    """The file the app has for it: {"id", "name", "size"}, or None."""
    arr = r.arr
    file: Any
    if arr.app == SONARR:
        episode = await arr.episode(found.item)
        if not episode.get("hasFile") or not episode.get("episodeFileId"):
            return None
        file = await arr.episode_file(int(episode["episodeFileId"]))
    else:
        movie = await arr.movie(found.item)
        file = movie.get("movieFile") if movie.get("hasFile") else None
    if not isinstance(file, dict) or not isinstance(file.get("id"), int):
        return None
    name = _name(str(file.get("relativePath") or file.get("path") or ""))
    return {"id": int(file["id"]), "name": name, "size": file.get("size")}


def _grab_of(history: list[dict[str, Any]], file_id: int) -> dict[str, Any] | None:
    """The grab of the release a file came from: the import of that file
    (by its id) says which download it was."""
    for imported in history:
        if imported.get("eventType") != IMPORTED:
            continue
        data = imported.get("data") or {}
        download = imported.get("downloadId")
        if str(data.get("fileId")) != str(file_id) or not download:
            continue
        for grab in history:
            if (
                grab.get("eventType") == GRABBED
                and grab.get("downloadId") == download
                and isinstance(grab.get("id"), int)
            ):
                return grab
    return None


async def _rescan(arr: Arr, found: Found) -> None:
    """Has the app look at what's on disk, and waits for it to (a while)."""
    command = await arr.rescan(found.parent)
    waited = 0.0
    while waited < RESCAN_WAIT_S:
        status = await arr.command_status(command)
        if status not in ("queued", "started"):
            return
        await asyncio.sleep(RESCAN_POLL_S)
        waited += RESCAN_POLL_S


async def _nudge(ctx: AppContext, state: dict[str, Any], now: int) -> None:
    """Asks Plex to look in the program's folder (at most hourly)."""
    section, folder = state.get("section"), state.get("folder")
    if not section or not folder or now - int(state.get("nudged") or 0) < NUDGE_GAP_MS:
        return
    try:
        await ctx.library.scan_folder(str(section), str(folder))
        state["nudged"] = now
    except LibraryError as e:
        log.info("Couldn't ask Plex to scan %s (%s)", folder, e)


def same_problem(before: Any, now: str) -> bool:
    """Whether a file's problem (`now`: its entry's reason) is the one the
    file it replaced had (`before`): said in the same words, up to where it
    happens, and at the same places (at least half of them within
    SAME_PLACE_S of one before)."""
    if not isinstance(before, str) or not before:
        return False

    def told(reason: str) -> tuple[str, list[int]]:
        reason = reason.removeprefix("Deep scan: ").removeprefix("Check: ")
        first = _PLACE.search(reason)
        places = [
            int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            if m.group(3)
            else int(m.group(1)) * 60 + int(m.group(2))
            for m in _PLACE.finditer(reason)
        ]
        return (reason[: first.start()] if first else reason).strip(), places

    what, places = told(now)
    was, then = told(before)
    if what != was:
        return False
    if not places or not then:
        return not places and not then
    near = sum(1 for at in places if any(abs(at - b) <= SAME_PLACE_S for b in then))
    return 2 * near >= len(places)


def _same_file(have: dict[str, Any], entry: dict[str, Any]) -> bool:
    """Whether the app's file is the one found broken: the same name (the
    folders it's in can look different to Plex and to the app), and the same
    size if both know it."""
    file = entry.get("file")
    if not isinstance(file, str) or _name(file) != have["name"]:
        return False
    size, theirs = entry.get("fileSize"), have.get("size")
    return not (isinstance(size, int) and isinstance(theirs, int) and size and theirs) or (
        size == theirs
    )


def _name(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _folder(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def entry_label(entry: dict[str, Any]) -> str:
    if entry.get("show"):
        season, episode = entry.get("season"), entry.get("episode")
        if isinstance(season, int) and isinstance(episode, int):
            return f"{entry['show']} S{season:02d}E{episode:02d}"
        return str(entry["show"])
    year = entry.get("year")
    return f"{entry.get('title')}" + (f" ({year})" if year else "")


def _how_many(found: list, what: str) -> str:
    return f"no {what}" if not found else f"{len(found)} {what}s"


def try_again(ctx: AppContext, entry: dict[str, Any]) -> None:
    """You've said to replace it (Replace, Try again, or Try another, on the
    list): the tries for its episode or movie, and what it says, are
    forgotten, so it's tried afresh."""
    state = entry.get("replace") or {}
    if state.get("id") is not None:
        tries = _load_tries(ctx.db)
        tries.pop(f"{app_for(entry)}:{state['id']}", None)
        ctx.db.set_meta(META_TRIES, json.dumps(tries))
    # (What it is in the app is kept; and so it stays on the list.)
    kept = {k: state[k] for k in _IDENTITY if state.get(k) is not None}
    kept["asked"] = now_ms()
    ctx.broken.replacing({file_key(entry): (entry.get("lastFailed"), kept)})


def leave(ctx: AppContext, entry: dict[str, Any]) -> None:
    """Leave this one to me (on the list): nothing more is asked of the app
    for it, until you say Replace."""
    state = entry.get("replace") or {}
    app = app_for(entry)
    left = {k: state[k] for k in _IDENTITY if state.get(k) is not None}
    left.update(
        app=app,
        state=LEFT,
        note=f"StationPlay won't ask {NAMES[app]} to replace it",
        at=now_ms(),
    )
    ctx.broken.replacing({file_key(entry): (entry.get("lastFailed"), left)})


# What's kept of an entry's state when you say what's to be done: which
# episode or movie it is.
_IDENTITY = ("app", "id", "parent", "showKey", "section", "folder")
