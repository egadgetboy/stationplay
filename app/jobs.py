"""Background jobs: checking a station's files ahead of time, and going
through the broken-files list again."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import replacing
from .broken import CHECK, STAYS, file_key, found_by
from .db import Item
from .ffmpeg import redact
from .library import LibraryError
from .playing import cap
from .playing import station as station_named
from .plex import Lookups, MediaPart, telling_title
from .scanner import quick_check_item, quick_verdict, someone_watching
from .sources import FIND_AGAIN_S, REMOVED, VERSION_GONE

if TYPE_CHECKING:
    from .main import AppContext

log = logging.getLogger(__name__)

# Files checked at once, across every station's check (so checking several
# new stations at once doesn't swamp the NAS).
CHECK_CONCURRENCY = 2
# While anyone's watching (a station, or Media in the apps), checks that read
# files (a station's Check files, going through the broken-files list) go
# one at a time, with this rest between: a lower disk priority isn't
# honoured by ZFS and most NAS disks, and fewer reads at once is what keeps
# the streams' reads quick.
WATCHING_REST_S = 5.0
# A new station's files are checked as soon as it's made. (Tests that aren't
# about checking files turn it off, so they don't wait for ffmpeg.)
CHECK_NEW_STATIONS = True
CLEAR_INTERVAL_S = 30 * 60


@dataclass
class CheckStatus:
    running: bool = False
    total: int = 0
    done: int = 0
    newly_broken: int = 0
    skipped: int = 0
    started_at: float = 0
    finished_at: float = 0
    _task: asyncio.Task | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "total": self.total,
            "done": self.done,
            "newlyBroken": self.newly_broken,
            "skipped": self.skipped,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }


async def check_item(ctx: AppContext, item, channel_number: int) -> str:
    """The quick check of one program (see scanner.py): "ok", "broken"
    (broken or damaged, and now off the air) or "skipped" (couldn't tell)."""
    record = ctx.db.scan(item.rating_key)
    verdict, record = await quick_check_item(ctx, item, channel_number, record)
    if record is not None:
        ctx.db.save_quick(record)
    return {"ok": "ok", "skipped": "skipped"}.get(verdict.result, "broken")


@contextlib.asynccontextmanager
async def check_turn(ctx: AppContext):
    """A turn to read a file for a check: one of CHECK_CONCURRENCY, or while
    anyone's watching, the only one, and a rest after it."""
    async with ctx.check_slots:
        if not someone_watching(ctx):
            yield
            return
        async with ctx.watching_checks:
            yield
            await asyncio.sleep(WATCHING_REST_S)


async def run_check(ctx: AppContext, channel_id: int, status: CheckStatus) -> None:
    channel = ctx.db.get_channel(channel_id)
    if channel is None:
        return
    seen: set[str] = set()
    items = []
    for item in ctx.db.all_programs(channel_id):
        if item.rating_key in seen or ctx.broken.is_broken(item.rating_key):
            continue
        seen.add(item.rating_key)
        items.append(item)
    status.total = len(items)

    async def one(item) -> None:
        async with check_turn(ctx):
            try:
                result = await check_item(ctx, item, channel.number)
            except Exception:
                log.exception("Quick check of Plex item %s failed", item.rating_key)
                result = "skipped"
            status.done += 1
            if result == "broken":
                status.newly_broken += 1
            elif result == "skipped":
                status.skipped += 1

    try:
        await asyncio.gather(*(one(i) for i in items))
    finally:
        status.running = False
        status.finished_at = time.time()
        log.info(
            "%s: checked %d files (%d with problems, %d couldn't be checked)",
            cap(station_named(channel.number, channel.name)),
            status.total,
            status.newly_broken,
            status.skipped,
        )


def start_check(ctx: AppContext, channel_id: int) -> CheckStatus:
    status = ctx.checks.get(channel_id)
    if status and status.running:
        return status
    status = CheckStatus(running=True, started_at=time.time())
    ctx.checks[channel_id] = status
    status._task = asyncio.create_task(run_check(ctx, channel_id, status))
    return status


# Going through the broken-files list again --------------------------------
#
# Every half hour, for what's changed in Plex:
#   * a program whose file is missing (gone from disk, or from Plex) comes
#     off the list once no station has it (taken off its stations on
#     purpose, say) and it isn't in Media, unless Sonarr or Radarr is
#     replacing it; a broken or damaged one stays, so it's never put on a
#     station again unnoticed;
#   * a version of a program (not the one a station plays) comes off the
#     list once Plex no longer has it;
#   * a program Plex no longer has under its key comes off the list if it's
#     in Plex again under a new key (added again: a file renamed, say), or
#     if no station has it any more; one removed from Plex that a station
#     still has stays, as broken ("removed from Plex");
#   * a new file for a program gets the quick check, and the program comes
#     off the list if it passes (otherwise its entry says what's wrong with
#     the new file).
# Every night, as the overnight checks' hours begin, and when you ask,
# besides those: a program the quick check, or opening its file, took off
# the air gets the quick check again (a share may have been down), and comes
# off the list if it passes. One the deep scan or playing it found a problem
# in stays until its file changes: checking the same file again finds the
# same thing.

# How often what Plex has anew is looked for.
CLEAR_INTERVAL_S = 30 * 60
# How often it's seen whether tonight's look has been had.
NIGHT_LOOK_S = 5 * 60
# How long Plex has to say what it has for one program.
PLEX_WAIT_S = 10.0
# Entries looked at between saving what was found.
SETTLE_EVERY = 20
META_LIST_NIGHT = "broken_list_night"  # the night the list was last gone through
META_LIST_LAST = "broken_list_last"  # what that found (JSON)


class PlexAway(Exception):
    """Plex couldn't be asked: going through the list stops, for later."""


@dataclass
class ListCheck:
    """Going through the broken-files list again, everything (at night, or
    when asked): how far it's got, and what it found."""

    running: bool = False
    total: int = 0
    done: int = 0
    cleared: int = 0  # back on the air
    plex_away: bool = False  # it stopped: Plex couldn't be asked
    started_ms: int = 0
    finished_ms: int = 0
    _task: asyncio.Task | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "total": self.total,
            "done": self.done,
            "cleared": self.cleared,
            "plexAway": self.plex_away,
            "startedAt": self.started_ms,
            "finishedAt": self.finished_ms,
        }

    def save(self, db) -> None:
        db.set_meta(
            META_LIST_LAST, json.dumps({k: v for k, v in self.as_dict().items() if k != "running"})
        )

    @classmethod
    def last(cls, db) -> ListCheck:
        """What the last time found (nothing, if never)."""
        try:
            got = json.loads(db.get_meta(META_LIST_LAST, "") or "{}")
            return cls(
                total=int(got.get("total", 0)),
                done=int(got.get("done", 0)),
                cleared=int(got.get("cleared", 0)),
                plex_away=bool(got.get("plexAway", False)),
                started_ms=int(got.get("startedAt", 0)),
                finished_ms=int(got.get("finishedAt", 0)),
            )
        except (ValueError, TypeError, AttributeError):
            return cls()


def same_program(entry: dict[str, Any], item: Item) -> bool:
    """Whether a program on a station is the one a broken-files entry is
    about (under another key: Plex added it again): the same file, its
    name's capital letters aside; or the same episode of the same show, or
    the same movie, from the same year. (An episode with no year on either
    side must have the same title too, so a remake's episode isn't taken
    for the original's; a movie needs its year on both.)"""
    file = entry.get("file")
    if isinstance(file, str) and file and (item.file_path or "").casefold() == file.casefold():
        return True
    year = entry.get("year")
    years_known = year is not None and item.year is not None
    if years_known and year != item.year:
        return False
    title = str(entry.get("title") or "").casefold()
    show = entry.get("show")
    if show:
        season, episode = entry.get("season"), entry.get("episode")
        if item.kind != "episode" or (item.show_title or "").casefold() != str(show).casefold():
            return False
        if season is None or episode is None:
            # (Plex gave it no season and episode, a show by air date, say:
            # its title, if that tells episodes apart.)
            return telling_title(entry.get("title"), str(show)) and item.title.casefold() == title
        return (
            item.season == season
            and item.episode == episode
            and (years_known or item.title.casefold() == title)
        )
    return item.kind == "movie" and years_known and item.title.casefold() == title


@dataclass
class OnStations:
    """Every program on a station, or in an update waiting to start on one,
    found by what could show it's one on the broken-files list again."""

    by_key: dict[str, Item] = field(default_factory=dict)
    by_file: dict[str, list[Item]] = field(default_factory=dict)
    by_episode: dict[tuple[str, Any, Any], list[Item]] = field(default_factory=dict)
    by_movie: dict[str, list[Item]] = field(default_factory=dict)
    by_title: dict[tuple[str, str], list[Item]] = field(default_factory=dict)

    def add(self, item: Item) -> None:
        if item.rating_key in self.by_key:
            return
        self.by_key[item.rating_key] = item
        if item.file_path:
            self.by_file.setdefault(item.file_path.casefold(), []).append(item)
        if item.kind == "episode":
            show = (item.show_title or "").casefold()
            self.by_episode.setdefault((show, item.season, item.episode), []).append(item)
            self.by_title.setdefault((show, item.title.casefold()), []).append(item)
        else:
            self.by_movie.setdefault(item.title.casefold(), []).append(item)

    def again(self, entry: dict[str, Any]) -> Item | None:
        """The program an entry is about, on a station under another key."""
        key = str(entry.get("ratingKey"))
        file = entry.get("file")
        show = entry.get("show")
        found = [
            *(self.by_file.get(file.casefold(), []) if isinstance(file, str) and file else []),
            *(
                self.by_episode.get(
                    (str(show).casefold(), entry.get("season"), entry.get("episode")), []
                )
                if show
                else self.by_movie.get(str(entry.get("title") or "").casefold(), [])
            ),
            *(
                self.by_title.get(
                    (str(show).casefold(), str(entry.get("title") or "").casefold()), []
                )
                if show
                else []
            ),
        ]
        return next((i for i in found if i.rating_key != key and same_program(entry, i)), None)


def on_stations(ctx: AppContext) -> OnStations:
    on = OnStations()
    for channel in ctx.db.list_channels():
        pending = ctx.updater.pending.get(channel.id)
        coming = (
            [*pending.items, *itertools.chain(*(pending.sets or {}).values())] if pending else []
        )
        for item in [*ctx.db.all_programs(channel.id), *coming]:
            on.add(item)
    return on


def stations_having(ctx: AppContext, keys: set[str]) -> dict[str, list[dict[str, Any]]]:
    """The stations that have each of these programs now (on the air, or in
    what their specials draw on), by key: {"id", "number", "name"}."""
    out: dict[str, list[dict[str, Any]]] = {}
    for channel in ctx.db.list_channels():
        for item in ctx.db.all_programs(channel.id):
            if item.rating_key in keys:
                out.setdefault(item.rating_key, []).append(
                    {"id": channel.id, "number": channel.number, "name": channel.name}
                )
    return out


def used_by(ctx: AppContext, entries: list[dict[str, Any]]) -> dict[str, bool]:
    """Whether a station or Media plays each entry's file, by its file key
    (a station plays a program's first version, never another)."""
    keys = {str(e["ratingKey"]) for e in entries if not e.get("version")}
    on = stations_having(ctx, keys) if keys else {}
    return {
        file_key(e): (not e.get("version") and str(e["ratingKey"]) in on) or ctx.in_media(e)
        for e in entries
    }


def _label(entry: dict[str, Any]) -> str:
    if entry.get("show"):
        season, episode = entry.get("season"), entry.get("episode")
        if isinstance(season, int) and isinstance(episode, int):
            return f"{entry['show']} S{season:02d}E{episode:02d}"
        return str(entry["show"])
    return str(entry.get("title") or entry.get("ratingKey"))


async def _version_part(ctx: AppContext, key: str, version: str) -> MediaPart | None:
    """The file a version of a program has now (LibraryError 404 if the
    program's gone; LookupError if the version is, or it's the program's
    first now, and known by its key alone)."""
    entry = await ctx.library.entry(key, details=True)
    if entry is None:
        raise LibraryError("no longer in Plex", 404)
    media = next((m for m in entry.media[1:] if m.id == version), None)
    if media is None:
        raise LookupError(version)
    return MediaPart(media.file, media.part_key, media.size, media.duration_ms)


def _item_for(entry: dict[str, Any], part: MediaPart) -> Item:
    """A program on the list that's on no station now (or a version of one
    that isn't the one a station plays), to check its file."""

    def number(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return Item(
        position=0,
        start_ms=0,
        duration_ms=0,
        rating_key=str(entry["ratingKey"]),
        kind="episode" if entry.get("show") else "movie",
        title=str(entry.get("title") or ""),
        show_title=str(entry["show"]) if entry.get("show") else None,
        show_key=str(entry["showKey"]) if entry.get("showKey") else None,
        season=number(entry.get("season")),
        episode=number(entry.get("episode")),
        year=number(entry.get("year")),
        file_path=part.file or entry.get("file"),
        part_key=part.key,
        library=str(entry["library"]) if entry.get("library") else None,
    )


# What looking at one entry found: it comes off the list; it stays (with
# anything that's changed about it, and when it was looked at); or it
# wasn't looked at (left as it is).
CLEARED, STILL = "cleared", "still"


async def look_at(
    ctx: AppContext,
    entry: dict[str, Any],
    on: OnStations,
    everything: bool,
    shows: Lookups,
) -> tuple[str, dict[str, Any]] | None:
    """Looks at one entry on the broken-files list again (see above).
    `shows`: what Plex said about shows and movies, kept for the next entry."""
    key = str(entry["ratingKey"])
    version = str(entry.get("version") or "")
    # (A station plays a program's first version: never another.)
    on_a_station = not version and (key in on.by_key or on.again(entry) is not None)
    if (
        replacing.missing(entry)
        and not on_a_station
        and not ctx.in_media(entry)
        and not replacing.held(ctx.db, entry)
    ):
        log.info(
            "Removed %s from the Broken files list: its file is missing, and neither a station "
            "nor Media has it now",
            _label(entry),
        )
        return CLEARED, {}
    try:
        if version:
            part = await asyncio.wait_for(_version_part(ctx, key, version), PLEX_WAIT_S)
        else:
            part = await asyncio.wait_for(ctx.library.current_part(key), PLEX_WAIT_S)
    except LibraryError as e:
        if e.status != 404:
            raise PlexAway(str(e)) from e
        return await _gone(ctx, entry, on, everything, shows)
    except TimeoutError as e:
        raise PlexAway("Plex didn't answer") from e
    except LookupError:
        log.info("Removed %s from the Broken files list: %s", _label(entry), VERSION_GONE)
        return CLEARED, {}
    if part is None or not part.file:
        return (STILL, {}) if everything else None  # Plex has it, with no file
    old_file, old_size = entry.get("file"), entry.get("fileSize")
    changed = bool(
        (old_file and part.file != old_file) or (old_size and part.size and part.size != old_size)
    )
    if not changed and (
        not everything or entry.get("problem") == "unsupported" or found_by(entry) in STAYS
    ):
        return None
    # The quick check, of the file Plex has now: a new one, or the same one
    # again.
    item = (on.by_key.get(key) if not version else None) or _item_for(entry, part)
    async with check_turn(ctx):
        verdict, record, resolved = await quick_verdict(
            ctx, item, ctx.db.scan(file_key(entry)), version
        )
    if verdict.result == "skipped":
        return None  # couldn't tell (a slow share, say): another time
    if record is not None:
        ctx.db.save_quick(record)
    if verdict.result == "ok":
        log.info(
            "Removed %s from the Broken files list: it passes the quick check%s",
            _label(entry),
            " with its new file" if changed else " now",
        )
        return CLEARED, {}
    found: dict[str, Any] = {
        "reason": redact(f"Check: {verdict.reason}")[:500],
        "problem": verdict.result,
        "foundBy": CHECK,
    }
    if changed:
        found["file"] = resolved.plex_file or part.file
        found["fileSize"] = resolved.size if resolved.size is not None else part.size
    return STILL, found


async def _gone(
    ctx: AppContext,
    entry: dict[str, Any],
    on: OnStations,
    everything: bool,
    shows: Lookups,
) -> tuple[str, dict[str, Any]] | None:
    """An entry Plex no longer has under its key. Added again under a new
    key, it isn't broken; removed, it is while a station still has it."""
    key = str(entry["ratingKey"])
    if entry.get("version"):
        log.info("Removed %s from the Broken files list: it's no longer in Plex", _label(entry))
        return CLEARED, {}
    if on.again(entry) is not None:
        log.info(
            "Removed %s from the Broken files list: Plex has it again under a new key, and a "
            "station has it",
            _label(entry),
        )
        return CLEARED, {}
    expected = on.by_key.get(key)
    # (One Sonarr or Radarr is replacing, or tried to, stays till it's back.)
    being_replaced = replacing.held(ctx.db, entry)
    if expected is None and not being_replaced:
        log.info(
            "Removed %s from the Broken files list: it's no longer in Plex, and no station has it "
            "now",
            _label(entry),
        )
        return CLEARED, {}
    asked = expected or replacing.entry_item(entry)
    if asked is None:
        return (STILL, {}) if everything else None
    try:
        again = await asyncio.wait_for(ctx.library.find_again(asked, shows), FIND_AGAIN_S)
    except LibraryError as e:
        raise PlexAway(str(e)) from e
    except TimeoutError as e:
        raise PlexAway("Plex didn't answer") from e
    if again is not None:
        log.info(
            "Removed %s from the Broken files list: Plex has it again under a new key (its "
            "station switches to the new key at its next update from Plex)",
            _label(entry),
        )
        return CLEARED, {}
    reason = str(entry.get("reason", ""))
    removed = ("Check: " if reason.startswith("Check: ") else "") + REMOVED
    if reason != removed:
        return STILL, {"reason": removed, "problem": "broken"}
    return (STILL, {}) if everything else None


async def go_through(ctx: AppContext, status: ListCheck, everything: bool, on: OnStations) -> None:
    """Goes through the broken-files list once (see above), saving what it
    finds as it goes (`on`: the programs on stations). Stops if Plex can't be
    asked (PlexAway)."""
    entries = ctx.broken.entries()
    status.total = len(entries)
    shows = Lookups()
    seen: dict[str, Any] = {}  # the lastFailed of each entry looked at
    cleared: set[str] = set()
    still: dict[str, dict[str, Any]] = {}

    def settle() -> None:
        if seen:
            taken = ctx.broken.settle(seen, cleared, still)
            for key in taken:
                ctx.stall_counts.pop(key, None)
            status.cleared += len(taken)
        seen.clear()
        cleared.clear()
        still.clear()

    try:
        for entry in entries:
            key = file_key(entry)
            try:
                got = await look_at(ctx, entry, on, everything, shows)
            except PlexAway:
                raise
            except Exception:
                log.exception("Rechecking %s on the Broken files list failed", key)
                got = None
            status.done += 1
            if got is not None:
                seen[key] = entry.get("lastFailed")
                outcome, found = got
                if outcome == CLEARED:
                    cleared.add(key)
                else:
                    still[key] = found
            if len(seen) >= SETTLE_EVERY:
                settle()
    finally:
        settle()


async def look_again(ctx: AppContext, status: ListCheck, everything: bool) -> ListCheck:
    """Goes through the list once, one at a time (a wait while another is
    under way)."""
    async with ctx.list_lock:
        status.started_ms = status.started_ms or int(time.time() * 1000)
        on: OnStations | None = None
        try:
            on = await asyncio.to_thread(on_stations, ctx)
            await go_through(ctx, status, everything, on)
        except PlexAway as e:
            status.plex_away = True
            log.info("Stopped rechecking the Broken files list: Plex isn't available (%s)", e)
        finally:
            status.running = False
            status.finished_ms = int(time.time() * 1000)
        # Then what Sonarr and Radarr can do about what's left (if they're
        # set up: see replacing.py), even if Plex was too slow to answer for
        # all of the list: each entry that needs Plex waits for it then.
        if on is not None:
            try:
                await replacing.replace_all(ctx, on.by_key)
            except Exception:
                log.exception("Replacing broken files with Sonarr or Radarr failed")
    if everything:
        status.save(ctx.db)
        log.info(
            "Rechecked the Broken files list: %d of %d back on the air",
            status.cleared,
            status.total,
        )
    elif status.cleared:
        log.info("Programs removed from the Broken files list: %d", status.cleared)
    return status


def start_looking_again(ctx: AppContext) -> ListCheck:
    """Goes through everything on the list again now (unless it's under way)."""
    if ctx.list_check.running:
        return ctx.list_check
    status = ListCheck(running=True, started_ms=int(time.time() * 1000))
    ctx.list_check = status
    status._task = asyncio.create_task(look_again(ctx, status, everything=True))
    return status


async def try_again(ctx: AppContext, key: str) -> None:
    """Try again (on the Broken files tab): Sonarr or Radarr tries that
    entry afresh, now."""
    async with ctx.list_lock:
        entry = ctx.broken.entry(key)
        if entry is None:
            return
        replacing.try_again(ctx, entry)
        on = await asyncio.to_thread(on_stations, ctx)
        await replacing.replace_all(ctx, on.by_key, only=key)


_trying: set[asyncio.Task] = set()


def start_try_again(ctx: AppContext, key: str) -> None:
    task = asyncio.create_task(try_again(ctx, key))
    _trying.add(task)
    task.add_done_callback(_trying.discard)


def tonight() -> str:
    """The night it is (as the deep scan counts them: from noon to noon)."""
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - 12 * 3600))


async def look_again_forever(ctx: AppContext) -> None:
    """What Plex has anew, every half hour; everything, once a night, as the
    overnight checks' hours begin (whether or not the deep scan is on)."""
    last = time.monotonic()
    while True:
        await asyncio.sleep(NIGHT_LOOK_S)
        if not ctx.library.configured:
            continue
        try:
            await asyncio.wait_for(ctx.library.check(), PLEX_WAIT_S)
        except (LibraryError, TimeoutError):
            continue  # Plex is away: later
        try:
            night = tonight()
            if ctx.scanner.in_hours() and ctx.db.get_meta(META_LIST_NIGHT, "") != night:
                status = start_looking_again(ctx)
                if status._task is not None:
                    await status._task
                if not status.plex_away:
                    ctx.db.set_meta(META_LIST_NIGHT, night)
                last = time.monotonic()
            elif time.monotonic() - last >= CLEAR_INTERVAL_S:
                await look_again(ctx, ListCheck(running=True), everything=False)
                last = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Rechecking the Broken files list failed")
