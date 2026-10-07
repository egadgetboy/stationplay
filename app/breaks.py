"""Commercials, trailers and Station ID cards between programs.

A station can play 1, 2 or 3 commercials after each episode, or trailers
after each movie, and a short Station ID card saying what's up next. They
come from folders you keep beside your media: a folder called
`commercials` at the top of each TV library's folder, and `trailers` at the
top of each movie library's folder (add a `.plexignore` file containing `*`
to each, so Plex doesn't add them to your libraries).

Clips in a folder named for a decade (`commercials/1960s`, or `60s`) play
after programs from that decade, and only those; the rest play after
anything (and after a decade's programs when it has none of its own).

What follows each program is decided when a station's schedule is worked
out and becomes part of the program's run, so a restart or a viewer tuning
in partway through always lands in the right place. The clips are shared
out evenly: each one plays about as often as the others.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from . import ffmpeg as ff
from .db import Channel, Item
from .sources import local_candidates

if TYPE_CHECKING:
    from .main import AppContext

log = logging.getLogger(__name__)

COMMERCIALS = "commercials"  # folder names, exactly (Linux names are case-sensitive)
TRAILERS = "trailers"
# The Station ID card, in a program's breaks.
ID_CARD = "@id"
MAX_BREAKS = 3
VIDEO_EXTENSIONS = frozenset(
    {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".ts", ".m2ts", ".webm", ".mpg", ".mpeg", ".wmv"}
)
# Clips shorter than this aren't worth a slot; longer ones aren't commercials.
MIN_CLIP_MS = 3_000
MAX_CLIP_MS = 10 * 60_000
# How long looking at a folder may take before the share counts as hung.
FOLDER_TIMEOUT_S = 20.0
# Files looked at in one refresh, at most, and new ones opened at once.
MAX_FILES = 5000
PROBES_AT_ONCE = 4
# Files that don't open in time before the share counts as hung.
PROBE_TIMEOUTS = 3
# A kind that had clips and is found empty this many hourly looks running
# is accepted as empty; before that it's taken for a share hiccup.
EMPTY_LOOKS = 3
META_BAD = "bad_clips"


@dataclass
class Clip:
    path: str
    duration_ms: int
    size: int
    mtime: float
    decade: int | None = None  # (from the folder it's in, e.g. 1960)


# A folder named for a decade: 1960s, or 60s (1930s to 2020s).
_DECADE = re.compile(r"(19[3-9]0|20[0-2]0|[0-9]0)s", re.IGNORECASE)


def decade_of(folder: str, path: str) -> int | None:
    """The decade a clip is for: the first folder between `folder` and it
    that's named for one; None for any."""
    for part in os.path.relpath(os.path.dirname(path), folder).split(os.sep):
        found = _DECADE.fullmatch(part)
        if found:
            year = int(found.group(1))
            return year if year >= 100 else (1900 + year if year >= 30 else 2000 + year)
    return None


class FillerLibrary:
    """The commercials and trailers found on disk."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.clips: dict[str, list[Clip]] = {COMMERCIALS: [], TRAILERS: []}
        self.folders: dict[str, list[str]] = {COMMERCIALS: [], TRAILERS: []}
        # Files that failed to play, by path, with (size, mtime) when they did:
        # left out until the file changes. Kept across restarts.
        self.bad: dict[str, tuple[int, float]] = _load_bad(ctx.db.get_meta(META_BAD, ""))
        self._known: dict[str, Clip] = {}
        self._lock = asyncio.Lock()
        self.refreshed_ms = 0
        self._tried = False
        self._empty_looks = {COMMERCIALS: 0, TRAILERS: 0}

    def pool(self, kind: str) -> list[Clip]:
        """The clips of a kind that can be used."""
        return [c for c in self.clips.get(kind, []) if not self.is_bad(c.path)]

    @property
    def signature(self) -> str:
        """Changes whenever the clips that can be used do."""
        text = "\n".join(
            f"{kind}:{c.path}:{c.duration_ms}"
            for kind in (COMMERCIALS, TRAILERS)
            for c in self.pool(kind)
        )
        return hashlib.sha1(text.encode()).hexdigest()

    def is_bad(self, path: str) -> bool:
        """Whether a clip failed to play and hasn't changed since."""
        mark = self.bad.get(path)
        if mark is None:
            return False
        known = self._known.get(path)
        return known is None or (known.size, known.mtime) == mark

    def mark_bad(self, path: str, reason: str) -> None:
        if self.is_bad(path):
            return
        known = self._known.get(path)
        self.bad[path] = (known.size, known.mtime) if known else (-1, -1.0)
        self._save_bad()
        log.warning("%s didn't play (%s); skipping it until the file changes", path, reason)

    def _save_bad(self) -> None:
        self.ctx.db.set_meta(META_BAD, json.dumps({p: list(m) for p, m in self.bad.items()}))

    async def ready(self) -> None:
        """Makes sure the folders have been looked in (or tried) once."""
        if not self._tried:
            await self.refresh()

    async def refresh(self) -> None:
        """Finds the folders (from Plex's library folders) and what's in them,
        checking each new or changed file opens and how long it is. If Plex
        or the share doesn't answer, what was known is kept: a hiccup mustn't
        take every commercial off the air."""
        async with self._lock:
            self._tried = True
            try:
                sections = await self.ctx.library.libraries()
            except Exception as e:
                log.info("Can't look for commercials and trailers right now (%s)", e)
                return
            try:
                found = await self._folders(sections)
                clips = {kind: await self._clips(folders) for kind, folders in found.items()}
            except TimeoutError:
                log.warning(
                    "Looking for commercials and trailers took too long (is the media share "
                    "responding?); keeping the ones already found"
                )
                return
            self._through_hiccups(clips, found)
            present = {c.path for kind in clips for c in clips[kind]}
            if any(p not in present for p in self.bad):  # files since removed
                self.bad = {p: m for p, m in self.bad.items() if p in present}
                self._save_bad()
            if clips != self.clips or not self.refreshed_ms:
                log.info(
                    "Found %d commercials and %d trailers",
                    len(clips[COMMERCIALS]),
                    len(clips[TRAILERS]),
                )
            self.clips, self.folders = clips, found
            self.refreshed_ms = int(time.time() * 1000)

    async def _folders(self, sections: list[dict]) -> dict[str, list[str]]:
        """The commercials folders beside TV libraries, trailers beside movies."""
        found: dict[str, list[str]] = {COMMERCIALS: [], TRAILERS: []}
        for section in sections:
            kind = COMMERCIALS if section.get("type") == "show" else TRAILERS
            for location in section.get("locations") or []:
                folder = await self._local_folder(f"{location.rstrip('/')}/{kind}")
                if folder and folder not in found[kind]:
                    found[kind].append(folder)
        return found

    async def _clips(self, folders: list[str]) -> list[Clip]:
        """The usable clips in some folders, a few opened at once."""
        slots = asyncio.Semaphore(PROBES_AT_ONCE)
        slow = [0]  # files that didn't open in time

        async def look(path: str, size: int, mtime: float) -> Clip | None:
            async with slots:
                return await self._clip(path, size, mtime, slow)

        out: list[Clip] = []
        for folder in folders:
            looked = await asyncio.gather(*(look(*f) for f in await _video_files(folder)))
            out += [replace(c, decade=decade_of(folder, c.path)) for c in looked if c is not None]
        return out

    def _through_hiccups(self, clips: dict[str, list[Clip]], found: dict[str, list[str]]) -> None:
        """None of a kind where there were some is more likely the share
        having a moment (or /media not mounted yet) than all of them deleted:
        what was there is kept until it's been that way EMPTY_LOOKS times."""
        for kind in clips:
            if clips[kind] or not self.clips[kind]:
                self._empty_looks[kind] = 0
                continue
            self._empty_looks[kind] += 1
            if self._empty_looks[kind] < EMPTY_LOOKS:
                log.warning(
                    "No %s found this time (there were %d before); keeping those for now",
                    kind,
                    len(self.clips[kind]),
                )
                clips[kind], found[kind] = self.clips[kind], self.folders[kind]

    async def _local_folder(self, plex_path: str) -> str | None:
        """Where Plex's folder is in this container, if it's there. Raises
        TimeoutError if the share doesn't answer."""
        paths = [
            c.path for c in local_candidates(self.ctx.settings, self.ctx.media_access, plex_path)
        ]
        # Last, straight inside the media folder: for a library that is the
        # whole media folder.
        media_dir = self.ctx.settings.media_dir.rstrip("/")
        if media_dir:
            paths.append(f"{media_dir}/{plex_path.rstrip('/').rsplit('/', 1)[-1]}")

        def first() -> str | None:
            return next((p for p in paths if os.path.isdir(p)), None)

        return await asyncio.wait_for(asyncio.to_thread(first), FOLDER_TIMEOUT_S)

    async def _clip(self, path: str, size: int, mtime: float, slow: list[int]) -> Clip | None:
        known = self._known.get(path)
        if known is not None and (known.size, known.mtime) == (size, mtime):
            return known if known.duration_ms else None
        probe = await ff.probe(self.ctx.settings, path, timeout=FOLDER_TIMEOUT_S)
        if probe.timed_out:
            # Left out this time, and looked at again next time. Several at
            # once means the share is hung.
            slow[0] += 1
            if slow[0] >= PROBE_TIMEOUTS:
                raise TimeoutError
            return None
        duration = int((probe.duration_s or 0) * 1000) if probe.ok else 0
        if not probe.ok:
            log.warning("%s can't be used as a commercial or trailer: %s", path, probe.error)
        elif probe.dolby_vision_only:
            log.warning("Skipping %s: %s", path, ff.dolby_vision_reason(probe))
            duration = 0
        elif not MIN_CLIP_MS <= duration <= MAX_CLIP_MS:
            log.info(
                "Skipping %s: its length (%.0fs) is outside the range allowed for a commercial "
                "or trailer",
                path,
                duration / 1000,
            )
            duration = 0
        clip = Clip(path, duration, size, mtime)
        self._known[path] = clip
        return clip if duration else None

    def as_dict(self) -> dict:
        return {
            "commercials": len(self.pool(COMMERCIALS)),
            "trailers": len(self.pool(TRAILERS)),
            "commercialFolders": self.folders[COMMERCIALS],
            "trailerFolders": self.folders[TRAILERS],
            # Clips that failed to play, left out until they change.
            "unplayable": sorted(
                c.path for kind in self.clips for c in self.clips[kind] if self.is_bad(c.path)
            ),
            "checked": self.refreshed_ms,
        }


def _load_bad(text: str) -> dict[str, tuple[int, float]]:
    try:
        return {str(p): (int(m[0]), float(m[1])) for p, m in json.loads(text or "{}").items()}
    except (ValueError, TypeError, IndexError, AttributeError):
        return {}


async def _video_files(folder: str) -> list[tuple[str, int, float]]:
    """(path, size, mtime) of the video files in a folder and its subfolders.
    Raises TimeoutError if the share doesn't answer."""

    def walk() -> list[tuple[str, int, float]]:
        out: list[tuple[str, int, float]] = []
        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(files):
                if (
                    name.startswith(".")
                    or os.path.splitext(name)[1].lower() not in VIDEO_EXTENSIONS
                ):
                    continue
                path = os.path.join(root, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                out.append((path, st.st_size, st.st_mtime))
                if len(out) >= MAX_FILES:
                    return out
        return out

    return await asyncio.wait_for(asyncio.to_thread(walk), FOLDER_TIMEOUT_S)


def id_card_ms(channel: Channel) -> int:
    """How long the station's ID card is after each program (0: it has none)."""
    return channel.id_seconds * 1000 if channel.station_id else 0


def with_breaks(
    items: list[Item],
    count: int,
    card_ms: int,
    commercials: list[Clip],
    trailers: list[Clip],
    seed: str,
) -> list[Item]:
    """`items` with what follows each one: `count` commercials after an
    episode or trailers after a movie, then the Station ID card, if it's
    wanted (`card_ms` long; 0 for none).
    Clips are dealt out in a shuffled order, a different one each time
    round, so each plays about equally often; the same items and clips
    always get the same breaks. A program from a decade that has clips of
    its own gets those (see decade_of)."""
    count = max(0, min(MAX_BREAKS, count))
    if not count and not card_ms:
        return [
            replace(i, breaks=None, duration_ms=i.program_end_ms) if i.breaks else i for i in items
        ]
    decks = {
        "episode": _Decks(commercials, f"{seed}:{COMMERCIALS}"),
        "movie": _Decks(trailers, f"{seed}:{TRAILERS}"),
    }
    by_key = {i.rating_key: i for i in items}
    breaks: dict[str, tuple[tuple[str, int], ...]] = {}
    for key in sorted(by_key):
        item = by_key[key]
        deck = decks["episode" if item.kind == "episode" else "movie"].for_year(item.year)
        clips = [(c.path, c.duration_ms) for c in deck.deal(count)]
        if card_ms:
            clips.append((ID_CARD, card_ms))
        breaks[key] = tuple(clips)
    out = []
    for item in items:
        after = breaks[item.rating_key]
        out.append(
            replace(
                item,
                breaks=after or None,
                duration_ms=item.program_end_ms + sum(ms for _, ms in after),
            )
        )
    return out


class _Decks:
    """A kind of clip, as a deck for each decade with clips of its own and
    one of the rest (all of them, if every clip is for some decade)."""

    def __init__(self, clips: list[Clip], seed: str) -> None:
        by_decade: dict[int, list[Clip]] = {}
        for clip in clips:
            if clip.decade is not None:
                by_decade.setdefault(clip.decade, []).append(clip)
        rest = [c for c in clips if c.decade is None] or clips
        # (The rest keep the seed they always had, so a station with no
        # decades' folders gets the very same breaks as before.)
        self.rest = _Deck(rest, seed)
        self.decades = {d: _Deck(c, f"{seed}:{d}") for d, c in by_decade.items()}

    def for_year(self, year: int | None) -> _Deck:
        if year is None:
            return self.rest
        return self.decades.get(year // 10 * 10, self.rest)


class _Deck:
    """Clips dealt in a shuffled order, reshuffled each time through, never
    the same clip twice in one break unless there are too few."""

    def __init__(self, clips: list[Clip], seed: str) -> None:
        self.clips = sorted(clips, key=lambda c: c.path)
        self.rng = random.Random(seed)
        self.order: list[Clip] = []

    def deal(self, n: int) -> list[Clip]:
        out: list[Clip] = []
        while len(out) < n and self.clips:
            if not self.order:
                self.order = self.clips[:]
                self.rng.shuffle(self.order)
            clip = self.order.pop()
            if clip in out and len(self.clips) >= n:
                self.order.insert(0, clip)  # save it for the next break
                continue
            out.append(clip)
        return out
