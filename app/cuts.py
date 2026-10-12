"""Where a program's picture cuts, near Plex's intro and credits markers, so
skipping them never cuts the program itself.

Plex finds an intro by its theme music, and credits by their text. The
music often starts under the cold open's last line, and runs on over the
program's first shot; credits often roll over the last scene. Skipped
exactly where the markers say, a station cut the end of the cold open and
the start of the program (the owner saw it on a station). So each skip is
moved to where the picture itself cuts (a change of shot, or a moment of
black), looked for close to the marker:

  * where the picture cuts right at the marker (within SAME_MS: Plex had it
    right), the skip stays there;
  * otherwise a skip starts at a cut after where Plex says it starts, and
    ends at a cut before where Plex says it ends. The music may run over
    more than one shot change: within UNSURE_MS of the marker, the cut
    furthest into the skip is taken, so what comes before it (or after it)
    plays whole, and at worst a moment of the titles shows. Past that, up
    to WINDOW_MS, the nearest cut is taken;
  * where the picture shows no cut that close (a dissolve, say), or hasn't
    been looked at yet, the skip is MARGIN_MS shorter at that end instead;
  * a skip left too short to keep (see markers.MIN_MARKER_MS) isn't made:
    the program plays in full, a few seconds of titles and all;
  * a skip starting within MIN_KEEP_MS of the start of the file, or ending
    within it of the end, stays there: what's left before or after it is
    skipped as well (see markers.py), and moved, it would flash up.

Cuts on the far side of a marker are never used: a skip only ever gets
shorter, and a cut just outside it says nothing about where the program
starts or ends.

Looking takes a few seconds of the file around each marker, read at low
priority, one program at a time, in the background. What's found is kept in
the data folder (cuts.json), by program, the file's length (a new file is
looked at again) and the marker; programs not scheduled for FORGET_DAYS are
dropped from it. Saving a station with no more than LOOK_NOW_MOST programs
to look at waits up to LOOK_NOW_S for them; the rest keep their margins
until they're looked at. What's found in the background reaches the
stations together, every SHOW_EVERY_S at most (the update from Plex that
follows brings it in), so their guides don't change every hour while a big
library is looked at. A file that can't be read now is tried again later;
after TRIES failures, its skips keep their margins, and it's tried again
after LEFT_FOR_S.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import ffmpeg as ff
from .config import Settings
from .db import Item
from .markers import CREDITS, INTRO, MIN_KEEP_MS, Marker
from .sources import ResolvedSource

log = logging.getLogger(__name__)

# How far from a marker a cut is looked for; within UNSURE_MS of it, the
# music may run over more than one shot change.
WINDOW_MS = 6_000
UNSURE_MS = 3_000
# Kept beyond a marker where the picture shows no cut near it.
MARGIN_MS = 2_000
# A cut this close to a marker is the marker's own: it's left where it is.
# (Within a frame or so: how far a file's clock starts from its picture.)
SAME_MS = 100
# How different a frame must be from the one before to be a new shot
# (FFmpeg's scene score, 0 to 1: a cut between two shots of much the same
# brightness scores 0.25, a still or steady shot near 0; a fast-moving shot
# taken for a cut only brings a skip back toward Plex's marker, never past
# it), and how long, and how dark, black must be.
SCENE = 0.15
BLACK_S = 0.05
BLACK_PIXELS = 0.10
# Reading starts this long before the first place a cut could be used: the
# first frame read can't be seen to be a cut (there's nothing before it to
# compare with), and FFmpeg's seek in a TV recording lands on the next
# keyframe after where it's asked to (and encoders put keyframes at cuts).
# If reading still starts too late (keyframes far apart), it's read again
# from LONG_LEAD_MS before.
LEAD_MS = 2_500
LONG_LEAD_MS = 12_000
# Read past the last place a cut could be used.
TAIL_MS = 400
# Saving a station waits this long, at most, for its programs to be looked
# at, when it has no more than LOOK_NOW_MOST to look at (more wouldn't be
# done in time); the rest are looked at afterwards.
LOOK_NOW_S = 10.0
LOOK_NOW_MOST = 3
# What's found in the background reaches the stations this often, at most.
SHOW_EVERY_S = 12 * 3600.0
# Opening a file, and one look (a few seconds of it), at most. (A 4K file
# with keyframes ten seconds apart takes over 15 s on a small server.)
OPEN_TIMEOUT_S = 15.0
LOOK_TIMEOUT_S = 60.0
# A file that can't be read is tried again after these waits, then left
# (its skips keep their margins) for LEFT_FOR_S (Plex, or the file, may be
# back by then).
RETRY_S = (300.0, 1800.0, 3 * 3600.0)
TRIES = len(RETRY_S) + 1
LEFT_FOR_S = 24 * 3600.0
# While the media share isn't answering, looking waits this long (doubling,
# up to PAUSE_MAX_S) before trying again.
PAUSE_S = 300.0
PAUSE_MAX_S = 3600.0
# As tapiOca stops, what's being read is waited for this long at most.
CLOSE_WAIT_S = 2.0
# Many stations made at once (smart stations, several collections): their
# programs go first, but none is waited for (each would wait in turn).
FIRST_NO_WAIT_S = 0.001
# What's found is saved at most this often, while looking goes on; and how
# far it's got is logged this often (when it starts and ends, too).
SAVE_EVERY_S = 60.0
PROGRESS_EVERY_S = 600.0
# Programs that couldn't be read are named in the log, each in a line of its
# own, up to this many a round; the rest are counted when it ends.
LEFT_NAMED = 3
# Programs not scheduled for this long are forgotten, and at most this many
# are kept (those scheduled longest ago go first; those scheduled in the
# last day are always kept, or they'd be looked at again and again).
FORGET_DAYS = 60
MOST_PROGRAMS = 50_000
FILE = "cuts.json"
VERSION = 1

# A time as FFmpeg prints it (6.1 prints a time near 0 as, say, 1.1e-05).
_TIME = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
_SHOWN = re.compile(r"pts_time:\s*" + _TIME)
_BLACK = re.compile(r"black_start:\s*" + _TIME + r"\s+black_end:\s*" + _TIME)

# How a look went.
DONE = "done"  # found what's there (or that there's nothing to find)
FAILED = "failed"  # this file couldn't be read: tried again later
BLOCKED = "blocked"  # the media share isn't answering: nothing can be read now


def start_cut(at_ms: int, cuts: list[int] | None) -> int | None:
    """The cut a skip Plex starts at `at_ms` starts at: Plex's start, with a
    cut right there; else the last cut in the UNSURE_MS after it (the cold
    open's last moments may change shot under the music: all of them play);
    else the first cut up to WINDOW_MS after it. None if there's none (or
    `cuts` is None: not looked for)."""
    if cuts is None:
        return None
    if any(abs(c - at_ms) <= SAME_MS for c in cuts):
        return at_ms
    unsure = [c for c in cuts if at_ms + SAME_MS < c <= at_ms + UNSURE_MS]
    if unsure:
        return max(unsure)
    after = [c for c in cuts if at_ms + UNSURE_MS < c <= at_ms + WINDOW_MS]
    return min(after) if after else None


def end_cut(at_ms: int, cuts: list[int] | None) -> int | None:
    """The cut a skip Plex ends at `at_ms` ends at: Plex's end, with a cut
    right there; else the first cut in the UNSURE_MS before it (the
    program's first moments may change shot under the music: all of them
    play); else the last cut from WINDOW_MS before it. None if there's none
    (or `cuts` is None: not looked for)."""
    if cuts is None:
        return None
    if any(abs(c - at_ms) <= SAME_MS for c in cuts):
        return at_ms
    unsure = [c for c in cuts if at_ms - UNSURE_MS <= c < at_ms - SAME_MS]
    if unsure:
        return min(unsure)
    before = [c for c in cuts if at_ms - WINDOW_MS <= c < at_ms - UNSURE_MS]
    return max(before) if before else None


def later_start(at_ms: int, cuts: list[int] | None) -> int:
    """Where a skip Plex starts at `at_ms` starts: at start_cut, or MARGIN_MS
    after it with none."""
    cut = start_cut(at_ms, cuts)
    return at_ms + MARGIN_MS if cut is None else cut


def earlier_end(at_ms: int, cuts: list[int] | None) -> int:
    """Where a skip Plex ends at `at_ms` ends: at end_cut, or MARGIN_MS
    before it with none."""
    cut = end_cut(at_ms, cuts)
    return at_ms - MARGIN_MS if cut is None else cut


def moves_start(marker: Marker) -> bool:
    """Whether where `marker`'s skip starts is moved to a cut: not for one
    starting so close to the start of the file that what's before it is
    skipped too (see markers.segments_for)."""
    return marker.kind in (INTRO, CREDITS) and marker.start_ms >= MIN_KEEP_MS


def moves_end(marker: Marker, length_ms: int) -> bool:
    """Whether where `marker`'s skip ends is moved to a cut: not for final
    credits (they run to the end), nor one ending so close to the end of the
    file that what's after it is skipped too."""
    return (
        marker.kind in (INTRO, CREDITS)
        and not (marker.kind == CREDITS and marker.final)
        and marker.end_ms <= length_ms - MIN_KEEP_MS
    )


def moved(
    marker: Marker, starts: list[int] | None, ends: list[int] | None, length_ms: int
) -> Marker:
    """`marker` moved to where the picture cuts (see later_start and
    earlier_end): `starts`, the cuts found around its start (where shots or
    black begin), and `ends`, around its end (where they begin after a cut,
    or black ends); None where not looked at. It only ever gets shorter."""
    at_start = start_cut(marker.start_ms, starts) if moves_start(marker) else marker.start_ms
    at_end = end_cut(marker.end_ms, ends) if moves_end(marker, length_ms) else marker.end_ms
    start = marker.start_ms + MARGIN_MS if at_start is None else at_start
    end = marker.end_ms - MARGIN_MS if at_end is None else at_end
    return replace(marker, start_ms=start, end_ms=max(start, end))


def edges(markers: list[Marker], length_ms: int) -> list[str]:
    """Where to look, for `markers` in a file `length_ms` long: each skip's
    start and end that's moved to a cut, as "start:<ms>" and "end:<ms>"."""
    out: list[str] = []
    for m in markers:
        if moves_start(m):
            out.append(f"start:{m.start_ms}")
        if moves_end(m, length_ms):
            out.append(f"end:{m.end_ms}")
    return list(dict.fromkeys(out))


def usable(edge: str) -> tuple[int, int]:
    """Where in the file (ms) a cut for `edge` could be used."""
    side, _, at = edge.partition(":")
    at_ms = int(at)
    if side == "start":
        return at_ms - SAME_MS, at_ms + WINDOW_MS
    return at_ms - WINDOW_MS, at_ms + SAME_MS


def program_key(item: Item) -> str:
    """Which program and file `item` is (a new file is looked at again)."""
    return f"{item.rating_key}:{item.duration_ms}"


def today() -> int:
    return int(time.time() // 86400)


def parsed(text: str) -> dict[str, dict[str, Any]]:
    """What cuts.json holds, as {program: {"used": day, "edges": {edge:
    cuts}}}: anything in it that isn't in that shape is left out."""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return {}
    programs = data.get("programs")
    if not isinstance(programs, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, entry in programs.items():
        if not isinstance(entry, dict):
            continue
        used, found = entry.get("used"), entry.get("edges")
        if not _whole(used) or not isinstance(found, dict):
            continue
        kept = {
            str(edge): sorted(set(cuts))
            for edge, cuts in found.items()
            if _edge(str(edge)) and isinstance(cuts, list) and all(_whole(c) for c in cuts)
        }
        out[str(key)] = {"used": used, "edges": kept}
    return out


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _edge(edge: str) -> bool:
    side, _, at = edge.partition(":")
    return side in ("start", "end") and at.lstrip("-").isdigit()


def saved_text(programs: dict[str, dict[str, Any]], day: int) -> tuple[str, set[str]]:
    """cuts.json's text for `programs` on `day`, and which of them it keeps:
    not those last scheduled more than FORGET_DAYS ago, and at most
    MOST_PROGRAMS (those scheduled longest ago go first; those scheduled in
    the last day always stay)."""
    recent = {k: v for k, v in programs.items() if v["used"] >= day - 1}
    older = sorted(
        ((k, v) for k, v in programs.items() if day - FORGET_DAYS <= v["used"] < day - 1),
        key=lambda kv: kv[1]["used"],
        reverse=True,
    )
    kept = {**recent, **dict(older[: max(0, MOST_PROGRAMS - len(recent))])}
    # (A program at a time: the event loop gets its turns meanwhile, as it
    # wouldn't during one json.dumps of them all.)
    each = [
        json.dumps(key) + ":" + json.dumps(kept[key], separators=(",", ":"), sort_keys=True)
        for key in sorted(kept)
    ]
    text = '{"programs":{' + ",".join(each) + '},"version":' + str(VERSION) + "}"
    return text, set(kept)


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_back(said: str, first_ms: int, starts: bool) -> tuple[int | None, list[int]]:
    """From what FFmpeg said (see CutFinder._read, reading from `first_ms` of
    the file): where reading began (its first frame, ms of the file; None if
    no frame was read), and where the picture cuts after that: each new
    shot, and where black begins (`starts`) or ends."""
    shown = [
        float(t)
        for line in said.splitlines()
        if "Parsed_showinfo" in line
        for t in _SHOWN.findall(line)[:1]
    ]
    if not shown:
        return None, []
    began = first_ms + round(shown[0] * 1000)
    found = {first_ms + round(t * 1000) for t in shown[1:]}
    for black_start, black_end in _BLACK.findall(said):
        found.add(first_ms + round(float(black_start if starts else black_end) * 1000))
    return began, sorted(c for c in found if c > began)


@dataclass
class _Round:
    """Looking, from when there's something to look at until there's
    nothing, tries again included: the programs (by program_key), those
    looked at, those left (and their names, for the log), and what was
    last said of it, when, and whether it's said it's only trying again."""

    keys: set[str]
    looked: set[str] = field(default_factory=set)
    left: dict[str, str] = field(default_factory=dict)  # program_key: its name
    named: int = 0  # how many left were named in a line of their own
    said: str = ""
    said_at: float = 0.0
    waited: bool = False


class CutFinder:
    """Finds where programs' pictures cut near their markers, in the
    background, and keeps what it finds."""

    def __init__(
        self,
        settings: Settings,
        folder: Path,
        resolve: Callable[[Item], Awaitable[ResolvedSource]],
    ) -> None:
        self.settings = settings
        self.path = folder / FILE
        self.resolve = resolve
        # Programs whose skips were last placed with their cuts all found
        # (by rating key): their skips are where they belong, to the frame.
        self.placed: set[str] = set()
        # What's been found, by program_key: {"used": day, "edges": {edge:
        # cuts}}. (Each entry is replaced, never changed, so a copy of the
        # dict can be saved on another thread.)
        self._programs: dict[str, dict[str, Any]] | None = None
        self._loading = asyncio.Lock()
        # Programs whose cuts reach the stations (what was in cuts.json, and
        # what's found since, every SHOW_EVERY_S); those found since then.
        self._shown: set[str] = set()
        self._unshown: set[str] = set()
        self._shown_at = time.monotonic()
        # Programs to look at, in order; the one being looked at; those to
        # try again later (when), and how often each has failed; those left.
        self._queue: dict[str, tuple[Item, list[Marker]]] = {}
        self._current: str | None = None
        self._later: dict[str, tuple[float, Item, list[Marker]]] = {}
        self._tries: dict[str, int] = {}
        self._replaced: set[str] = set()  # being looked at when its file was replaced
        self._left: dict[str, float] = {}
        self._paused_until = 0.0
        self._pause_s = PAUSE_S
        # Looking, from when there's something to look at until there's
        # nothing, tries again included (see _Round).
        self._round: _Round | None = None
        self._worker: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._looked = asyncio.Condition()
        # Changes made, as of the last save, and as of what's in the file.
        self._changes = 0
        self._saved = 0
        self._written = 0
        self._saving = asyncio.Lock()
        self._writing = threading.Lock()
        self._saver: asyncio.Task | None = None
        self._saved_at = 0.0

    # What's been found --------------------------------------------------------

    def _known(self) -> dict[str, dict[str, Any]]:
        if self._programs is None:
            return self._loaded(self._from_file())
        return self._programs

    def _loaded(self, programs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        self._programs = programs
        self._shown = set(programs)
        return programs

    def _from_file(self) -> dict[str, dict[str, Any]]:
        try:
            return parsed(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return {}

    def _cuts_for(self, item: Item) -> dict[str, list[int]]:
        entry = self._known().get(program_key(item))
        return entry["edges"] if entry else {}

    def ready(self, item: Item, markers: list[Marker]) -> bool:
        """Whether `item`'s cuts near `markers` have all been found."""
        found = self._cuts_for(item)
        return all(edge in found for edge in edges(markers, item.duration_ms))

    def adjusted(self, item: Item, markers: list[Marker]) -> list[Marker]:
        """`markers` moved to where `item`'s picture cuts, as far as is known
        (and the program noted as scheduled today)."""
        programs = self._known()
        key = program_key(item)
        entry = programs.get(key)
        if entry is not None and entry["used"] != today():
            programs[key] = {**entry, "used": today()}
            self._changes += 1
        found = entry["edges"] if entry is not None and key in self._shown else {}
        out = []
        for m in markers:
            if m.kind not in (INTRO, CREDITS):
                out.append(m)
                continue
            starts = found.get(f"start:{m.start_ms}")
            ends = found.get(f"end:{m.end_ms}")
            out.append(moved(m, starts, ends, item.duration_ms))
        if all(edge in found for edge in edges(markers, item.duration_ms)):
            self.placed.add(item.rating_key)
        else:
            self.placed.discard(item.rating_key)
        return out

    def _keep(self, item: Item, found: dict[str, list[int]]) -> None:
        programs = self._known()
        key = program_key(item)
        before = programs.get(key, {}).get("edges", {})
        programs[key] = {"used": today(), "edges": {**before, **found}}
        if key not in self._shown:
            self._unshown.add(key)
        self._save_soon()

    def due(self) -> bool:
        """Whether what's been found since the stations were last given it
        is due to reach them (every SHOW_EVERY_S at most)."""
        return bool(self._unshown) and time.monotonic() - self._shown_at >= SHOW_EVERY_S

    def show(self) -> None:
        """Gives the stations what's been found since they were last given
        it, if it's due (as a full update from Plex starts)."""
        if self.due():
            self._shown |= self._unshown
            self._unshown.clear()
            self._shown_at = time.monotonic()

    def _save_soon(self) -> None:
        self._changes += 1
        if self._saver is None or self._saver.done():
            self._saver = asyncio.create_task(self._save_later())

    async def _save_later(self) -> None:
        await asyncio.sleep(max(0.0, self._saved_at + SAVE_EVERY_S - time.monotonic()))
        await self.save()

    def _forget(self, snapshot: dict[str, dict[str, Any]], kept: set[str]) -> None:
        """Forgets what saving `snapshot` left out (unless found again since)."""
        programs = self._known()
        for key in snapshot.keys() - kept:
            if programs.get(key) is snapshot[key]:
                del programs[key]
                self._shown.discard(key)
                self._unshown.discard(key)

    def _write(self, changes: int, text: str) -> None:
        """Writes `text`, what was found as of `changes`, unless the file
        already has something newer (a save under way as tapiOca
        stops)."""
        with self._writing:
            if changes > self._written:
                _write(self.path, text)
                self._written = changes

    async def save(self) -> None:
        """Saves what's been found (if anything new), off the event loop."""
        async with self._saving:
            changes = self._changes
            if changes == self._saved:
                return
            snapshot = dict(self._known())
            try:
                text, kept = await asyncio.to_thread(saved_text, snapshot, today())
                await asyncio.to_thread(self._write, changes, text)
                self._saved = changes
                self._forget(snapshot, kept)
            except OSError as e:
                log.warning("Couldn't save where programs' pictures cut (%s)", e)
            self._saved_at = time.monotonic()

    def cancel(self) -> None:
        """Stops looking at once (tapiOca is stopping), without waiting
        (close, later, waits a moment and saves)."""
        for task in (self._worker, self._saver):
            if task is not None and not task.done():
                task.cancel()

    async def close(self) -> None:
        """Stops looking as tapiOca stops: what's being read stops with
        it (waited for CLOSE_WAIT_S at most), and what's new is saved."""
        going = [t for t in (self._worker, self._saver) if t is not None and not t.done()]
        for task in going:
            task.cancel()
        if going:
            await asyncio.wait(going, timeout=CLOSE_WAIT_S)
        self.stop()

    def stop(self) -> None:
        """Stops looking (tapiOca is stopping), and saves what's new."""
        for task in (self._worker, self._saver):
            if task is not None and not task.done():
                task.cancel()
        if self._changes > self._written:
            with contextlib.suppress(OSError):
                self._write(self._changes, saved_text(dict(self._known()), today())[0])

    # Looking ----------------------------------------------------------------

    async def refined(
        self, items: list[Item], known: dict[str, list[Marker]], look_s: float = 0.0
    ) -> dict[str, list[Marker]]:
        """Each item's markers (`known`), moved to where its picture cuts, as
        far as is known. Those not looked at yet are looked at in the
        background: first of all, and waited for up to `look_s`, with
        `look_s` (a station being saved)."""
        if self._programs is None:
            async with self._loading:  # (the first callers: read once)
                if self._programs is None:
                    loaded = await asyncio.to_thread(self._from_file)
                    if self._programs is None:
                        self._loaded(loaded)
        self._let_go_of_replaced(items)
        todo: dict[str, tuple[Item, list[Marker]]] = {}
        now = time.monotonic()
        for item in items:
            markers = known.get(item.rating_key) or []
            key = program_key(item)
            if not markers or self.ready(item, markers):
                continue
            if key in self._left:
                if now - self._left[key] < LEFT_FOR_S:
                    continue
                del self._left[key]  # (tried again)
                if self._round is not None:
                    self._round.left.pop(key, None)  # (no longer left, in a round still going)
            todo.setdefault(key, (item, markers))
        if todo:
            self._ask(todo, first=look_s > 0)
            if look_s > 0 and len(todo) <= LOOK_NOW_MOST:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._until_looked(set(todo)), look_s)
                # (Waited for: they reach this station now.)
                found_now = {k for k in todo if k in self._known()}
                self._shown |= found_now
                self._unshown -= found_now
        out = {}
        for item in items:
            if item.rating_key in known and item.rating_key not in out:
                out[item.rating_key] = self.adjusted(item, known[item.rating_key])
        if self._changes != self._saved:
            self._save_soon()
        return out

    def _ask(self, todo: dict[str, tuple[Item, list[Marker]]], first: bool) -> None:
        """Adds `todo` to what's to be looked at (`first`: before the rest)."""
        fresh = {k: v for k, v in todo.items() if k not in self._later and k != self._current}
        if self._round is not None:
            self._round.keys |= set(todo)
        if first:
            rest = {k: v for k, v in self._queue.items() if k not in fresh}
            self._queue = {**fresh, **rest}
        else:
            self._queue.update(fresh)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._work())
        self._wake.set()

    def _let_go_of_replaced(self, items: list[Item]) -> None:
        """Files replaced since they were asked about (a new length, so a new
        program key: Plex lists the new one, with or without its markers):
        the old one is let go wherever it is (to be looked at, waiting to be
        tried again, or left), and if it's being looked at, it isn't tried
        again. (Otherwise it was tried for hours at an address that's gone,
        holding the round open, then named unreadable.)"""
        listed = {item.rating_key: program_key(item) for item in items}

        def replaced(key: str) -> bool:
            rating_key = key.rsplit(":", 1)[0]
            return rating_key in listed and listed[rating_key] != key

        for gone in [k for k in self._queue if replaced(k)]:
            del self._queue[gone]
            self._let_go(gone)
        for gone in [k for k in self._later if replaced(k)]:
            del self._later[gone]
            self._let_go(gone)
        for gone in [k for k in self._left if replaced(k)]:
            del self._left[gone]
            self._let_go(gone)
        if self._current is not None and replaced(self._current):
            self._replaced.add(self._current)
        self._wake.set()  # (the worker sees what's left, and ends the round if that's nothing)

    def _let_go(self, key: str) -> None:
        self._tries.pop(key, None)
        if self._round is not None:
            self._round.keys.discard(key)
            self._round.looked.discard(key)
            self._round.left.pop(key, None)

    def _busy_with(self, keys: set[str]) -> bool:
        if time.monotonic() < self._paused_until:
            return False  # (nothing can be read now)
        return any(k in self._queue or k == self._current for k in keys)

    async def _until_looked(self, keys: set[str]) -> None:
        async with self._looked:
            await self._looked.wait_for(lambda: not self._busy_with(keys))

    async def _work(self) -> None:
        """Looks at what's asked, one program at a time."""
        while self._queue or self._later:
            now = time.monotonic()
            for key, (when, item, markers) in list(self._later.items()):
                if when <= now:
                    del self._later[key]
                    self._queue.setdefault(key, (item, markers))
            wait = self._paused_until - now
            if not self._queue or wait > 0:
                if wait <= 0:
                    wait = min(when for when, _, _ in self._later.values()) - now
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), max(0.05, wait))
                continue
            if self._round is None:
                self._began(set(self._queue) | set(self._later))
            key = next(iter(self._queue))
            item, markers = self._queue.pop(key)
            self._current = key
            try:
                how = await self._look(item, markers)
            except Exception:  # (one file's trouble never stops the rest)
                log.exception("Looking for where %s's picture cuts failed", item.label)
                how = FAILED
            finally:
                self._current = None
            counts = self._after(key, item, markers, how)
            if not counts:
                self._went_on(None)  # (replaced meanwhile: no longer one of the round's)
            elif how != BLOCKED:
                self._went_on(key)
            async with self._looked:
                self._looked.notify_all()
        self._ended()  # (a round whose last waiting program was let go)

    def _began(self, keys: set[str]) -> None:
        self._round = _Round(keys, said_at=time.monotonic())
        log.info(
            "Placing skipped intros and credits where the picture cuts: started, in the "
            "background (until a program is looked at, its skips keep a 2-second margin)"
        )

    def _ended(self) -> None:
        """The round's over: nothing left to look at or try again. Said, with
        how many programs were looked at (as the progress lines count them,
        those that couldn't be read included) and which couldn't be read; or,
        when every program it had was replaced, that nothing was left."""
        round_ = self._round
        if round_ is None:
            return
        self._round = None
        total = len(round_.keys)
        if total == 0:
            log.info(
                "Placing skipped intros and credits: done, with nothing left to look at "
                "(its files were replaced)."
            )
            return
        left = len(round_.left)
        said = f"{total} program{'' if total == 1 else 's'} looked at"
        if left:
            names = list(round_.left.values())
            shown = ", ".join(names[:LEFT_NAMED])
            more = f" and {left - LEFT_NAMED} more" if left > LEFT_NAMED else ""
            which = "it" if total == 1 else f"{left} of them"
            said += f", and {which} couldn't be read ({shown}{more}). " + (
                "Its skips keep a 2-second margin, and it'll be tried again in a day"
                if left == 1
                else "Their skips keep a 2-second margin, and they'll be tried again in a day"
            )
        log.info("Placing skipped intros and credits: done, %s.", said)

    def _went_on(self, key: str | None) -> None:
        """One more try (a program looked at, or not read this time): how far
        it's got is said now and then, and when there's nothing left to look
        at or try again. Counted by program, not by try."""
        round_ = self._round
        if round_ is None:
            return
        if key is not None:
            round_.keys.add(key)
        total = len(round_.keys)
        if not self._queue and not self._later and self._current is None:
            self._ended()
            return
        done = len(round_.looked | set(round_.left))
        waiting = len(self._later)
        line = (
            f"Placing skipped intros and credits: {done} of {total} program"
            f"{'' if total == 1 else 's'} looked at"
            + (f", {waiting} to try again" if waiting else "")
        )
        now = time.monotonic()
        # (Every PROGRESS_EVERY_S; and the first time all that's left is to
        # try again, which can be hours.)
        first_wait = not self._queue and not round_.waited
        if line != round_.said and (first_wait or now - round_.said_at >= PROGRESS_EVERY_S):
            round_.said, round_.said_at = line, now
            round_.waited = round_.waited or first_wait
            log.info("%s", line)

    def _after(self, key: str, item: Item, markers: list[Marker], how: str) -> bool:
        """What follows looking at `key` (`how` it went). False if it no
        longer counts: its file was replaced meanwhile."""
        round_ = self._round
        if key in self._replaced:
            self._replaced.discard(key)
            self._let_go(key)
            return False
        if how == DONE:
            self._tries.pop(key, None)
            self._pause_s = PAUSE_S
            if round_ is not None:
                round_.looked.add(key)
        elif how == BLOCKED:
            # (Nothing can be read until the share answers: this program goes
            # first when it does.)
            self._queue = {key: (item, markers), **self._queue}
            self._paused_until = time.monotonic() + self._pause_s
            log.info(
                "The media share isn't answering; looking for where programs' pictures cut "
                "again in %d minutes",
                round(self._pause_s / 60),
            )
            self._pause_s = min(PAUSE_MAX_S, self._pause_s * 2)
        else:
            tries = self._tries[key] = self._tries.get(key, 0) + 1
            if tries >= TRIES:
                self._tries.pop(key, None)
                self._left[key] = time.monotonic()
                said = round_ is None or round_.named < LEFT_NAMED
                if round_ is not None:
                    round_.left[key] = item.label
                    round_.named += said
                if said:
                    log.info(
                        "Couldn't read %s to see where its picture cuts. Its skipped intro and "
                        "credits keep a 2-second margin, and it'll be tried again in a day.",
                        item.label,
                    )
            else:
                self._later[key] = (time.monotonic() + RETRY_S[tries - 1], item, markers)
        return True

    async def _look(self, item: Item, markers: list[Marker]) -> str:
        """Looks at `item`'s picture around each of its markers not looked at
        yet, and keeps the cuts found."""
        found = self._cuts_for(item)
        wanted = [e for e in edges(markers, item.duration_ms) if e not in found]
        if not wanted:
            return DONE
        resolved = await self.resolve(item)
        source = resolved.source
        if source is None:
            if resolved.transient:
                return BLOCKED
            # (Nowhere to read it from: its skips keep their margins.)
            self._keep(item, {e: [] for e in wanted})
            return DONE
        probe = await ff.probe(self.settings, source, timeout=OPEN_TIMEOUT_S)
        if not probe.ok:
            return FAILED
        got: dict[str, list[int]] = {}
        how = DONE
        for edge in wanted:
            cuts = await self._cuts(source, probe, edge)
            if cuts is None:
                how = FAILED
                break
            got[edge] = cuts
        if got:
            self._keep(item, got)
        return how

    async def _cuts(self, source: str, probe: ff.ProbeResult, edge: str) -> list[int] | None:
        """Where the picture cuts near `edge` (see usable); None if it couldn't
        be read."""
        low, high = usable(edge)
        began: int | None = None
        cuts: list[int] = []
        for lead in (LEAD_MS, LONG_LEAD_MS):
            first = max(0, low - lead)
            read = await self._read(source, probe, first, high + TAIL_MS, edge.startswith("start"))
            if read is None:
                return None
            began, cuts = read
            if first == 0 or (began is not None and began < low):
                break  # (read from early enough)
        if began is None:
            return []  # (nothing there: past the end of the file)
        return [c for c in cuts if low <= c <= high]

    async def _read(
        self, source: str, probe: ff.ProbeResult, first: int, last: int, starts: bool
    ) -> tuple[int | None, list[int]] | None:
        """Reads the picture from `first` to `last` (ms of the file): see
        read_back. None if it couldn't be read."""
        chain = (
            f"scale=160:-2,blackdetect=d={BLACK_S}:pix_th={BLACK_PIXELS},"
            f"select='eq(n\\,0)+gt(scene\\,{SCENE})',showinfo"
        )
        args = [
            *ff.low_priority(), self.settings.ffmpeg_path, "-hide_banner", "-nostdin",
            "-v", "info", "-threads", "1",
            *ff.seek_args(source, first / 1000, probe.container, probe.start_s),
            "-t", f"{(last - first) / 1000:.3f}", "-i", source,
            "-map", f"0:v:{probe.video_index}", "-an", "-sn", "-dn", "-vf", chain, "-f", "null", "-",
        ]  # fmt: skip
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError:
            return None
        try:
            _, err = await asyncio.wait_for(proc.communicate(), LOOK_TIMEOUT_S)
        except TimeoutError:
            return None
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        if proc.returncode != 0:
            return None
        return read_back(err.decode(errors="replace"), first, starts)
