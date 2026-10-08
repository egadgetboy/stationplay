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
import json
import logging
import secrets
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
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
LIBRARIES_MOST = 100
NOT_SHARED = "That isn't in a library shared with StationPlay's apps"
UNREACHABLE = "Your library can't be reached right now. Try again in a moment."

# Requests to the library for the apps at once, at most (the rest wait).
LIBRARY_AT_ONCE = 6
# What's remembered of the library, and for how long.
WHERE_KEPT = 5000  # which library each show, movie and episode is in
ENTRIES_KEPT = 500  # shows', movies' and episodes' details
ENTRY_S = 600.0
SHOWS_KEPT = 50  # shows' lists of episodes
EPISODES_S = 120.0
# Whole libraries (as sorted, and for one genre), for filtering, jumping to
# a letter and finding others like a title: kept this long, this many.
WHOLE_S = 120.0
WHOLES_KEPT = 8
WHOLE_PAGE = 500  # asked for this many at a time
GENRES_S = 600.0
GENRE_LONGEST = 100
RELATED_MOST = 12

# Lists: shows or movies per page (and at most), search results and home rows.
PAGE_DEFAULT = 50
PAGE_MOST = 200
SEARCH_MOST = 50
SEARCH_LONGEST = 100  # characters searched for
ADDED_MOST = 20  # each library's recently added
CONTINUE_MOST = 20
SHOW_ROWS = 20  # a show's latest progress looked through for what's next

# Pictures are made one of these widths (the next one up from what's asked
# for), so a few sizes of each are kept rather than one of every width.
WIDTHS = (160, 320, 480, 720, 1280, 1920)
PICTURE_KINDS = ("poster", "backdrop", "thumb")
PICTURE_BYTES_KEPT = 48 << 20

# Progress: less than this far in counts as not started; a program is
# watched once its credits start (Plex's marker) or, without one, this far.
STARTED_MS = 60_000
WATCHED_SHARE = 0.9

# Play sessions (see PlaySessions).
SESSION_ID_BYTES = 24  # (32 characters)
SESSION_IDLE_S = 4 * 3600.0  # ended once unused this long
WATCHING_S = 180.0  # counts as a device watching until unheard from this long
SESSIONS_MOST = 500
RECHECK_S = 60.0  # how often a session's sign-in is checked again


# Sharing libraries -------------------------------------------------------------


class Shared:
    """Which of the libraries the apps may see: none until an Admin chooses."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.keys: tuple[str, ...] = self._load()
        self.when_slow: dict[str, str] = self._load_slow()

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


class Catalog:
    """The library as the apps see it: only shared libraries, with what's
    been asked lately kept a while so browsing doesn't ask the library about
    the same things over and over."""

    def __init__(self, library: Library, shared: Shared) -> None:
        self.library = library
        self.shared = shared
        self._where: OrderedDict[str, str] = OrderedDict()  # key -> its library
        self._entries: OrderedDict[str, tuple[float, Entry]] = OrderedDict()
        self._episodes: OrderedDict[str, tuple[float, list[Entry]]] = OrderedDict()
        self._wholes: OrderedDict[tuple[str, str, str], tuple[float, list[Entry]]] = OrderedDict()
        self._genres: dict[str, tuple[float, list[dict[str, str]]]] = {}
        self._turns = asyncio.Semaphore(LIBRARY_AT_ONCE)

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
        """The shared libraries, in the library's own order."""
        if not self.shared.on:
            return []
        async with self._turns:
            found = await self.library.libraries()
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
            async with self._turns:
                found = await self.library.entry(key, details=True)
            if found is not None:
                self._entries[key] = (now, found)
                while len(self._entries) > ENTRIES_KEPT:
                    self._entries.popitem(last=False)
                self.learn([found])
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

    async def episodes(self, show: str) -> list[Entry]:
        """A shared show's episodes, in order (specials last)."""
        await self.check(show)
        now = time.monotonic()
        kept = self._episodes.get(show)
        if kept is not None and now - kept[0] < EPISODES_S:
            self._episodes.move_to_end(show)
            return kept[1]
        async with self._turns:
            found = await self.library.show_episodes(show)
        self.learn(found)
        self._episodes[show] = (now, found)
        while len(self._episodes) > SHOWS_KEPT:
            self._episodes.popitem(last=False)
        return found

    async def browse(
        self, library: str, sort: str, start: int, size: int
    ) -> tuple[str, str, int, list[Entry]]:
        """A page of a shared library: (its title, kind, total, the page)."""
        title, kind = await self.library_kind(library)
        async with self._turns:
            total, page = await self.library.browse(library, kind, sort, start, size)
        self.learn(page)
        return title, kind, total, page

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

    async def whole(self, library: str, sort: str, genre: str = "") -> tuple[str, str, list[Entry]]:
        """All of a shared library's shows or movies, sorted (and only those
        with `genre`, by its name): (its title, kind, them). Kept a little
        while, so paging through it, or filtering it, asks the library once."""
        title, kind = await self.library_kind(library)
        now = time.monotonic()
        key = (library, sort, genre)
        kept = self._wholes.get(key)
        if kept is not None and now - kept[0] < WHOLE_S:
            self._wholes.move_to_end(key)
            return title, kind, kept[1]
        genre_id = None
        if genre:
            wanted = genre.casefold()
            found = [g["id"] for g in await self.genres(library) if g["title"].casefold() == wanted]
            if not found:
                return title, kind, []  # (no such genre here)
            genre_id = found[0]
        entries: list[Entry] = []
        while True:
            async with self._turns:
                total, page = await self.library.browse(
                    library, kind, sort, len(entries), WHOLE_PAGE, genre_id
                )
            entries += page
            if not page or len(entries) >= total:
                break
        self.learn(entries)
        self._wholes[key] = (now, entries)
        while len(self._wholes) > WHOLES_KEPT:
            self._wholes.popitem(last=False)
        return title, kind, entries

    async def recently_added(self) -> list[tuple[dict[str, str], list[Entry]]]:
        """Each shared library's newest shows or movies."""
        libs = await self.libraries()

        async def newest(lib: dict[str, str]) -> list[Entry]:
            async with self._turns:
                return await self.library.recently_added(lib["key"], lib["kind"], ADDED_MOST)

        found = await asyncio.gather(*(newest(lib) for lib in libs))
        for entries in found:
            self.learn(entries)
        return [
            (lib, [e for e in entries if self.shared_library(e)])
            for lib, entries in zip(libs, found, strict=True)
        ]

    async def search(self, words: str) -> list[Entry]:
        """Shows and movies whose titles contain `words`, in every shared
        library, best matches (titles starting with them) first."""
        libs = await self.libraries()

        async def look(lib: dict[str, str]) -> list[Entry]:
            async with self._turns:
                return await self.library.search(lib["key"], lib["kind"], words, SEARCH_MOST)

        found = [
            e for entries in await asyncio.gather(*(look(lib) for lib in libs)) for e in entries
        ]
        self.learn(found)
        wanted = words.casefold()
        found.sort(key=lambda e: (not e.title.casefold().startswith(wanted), e.title.casefold()))
        return found[:SEARCH_MOST]

    async def entries(self, keys: list[str]) -> list[Entry]:
        """Several shows, movies or episodes, in the order asked, leaving out
        those gone or not shared."""
        if not keys:
            return []
        async with self._turns:
            found = await self.library.entries(keys)
        self.learn(found)
        return [e for e in found if self.shared_library(e)]


# Jumping to a letter, and others like a title ----------------------------------------

_ARTICLES = ("the ", "a ", "an ")


def letter_of(e: Entry) -> str:
    """The letter a show or movie is listed under, as the library sorts it
    ("The Orbit Room" under O; "Élan" under E); "#" for a digit or anything
    else."""
    title = (e.sort_title or e.title).strip()
    if not e.sort_title:
        lowered = title.casefold()
        for article in _ARTICLES:
            if lowered.startswith(article) and len(title) > len(article):
                title = title[len(article) :].lstrip()
                break
    first = unicodedata.normalize("NFKD", title[:1])[:1].upper()
    return first if "A" <= first <= "Z" else "#"


def letters(entries: list[Entry]) -> list[dict[str, Any]]:
    """Where each letter starts among `entries` (sorted by title), for
    jumping to it: [{"letter", "start"}], each letter once."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, e in enumerate(entries):
        letter = letter_of(e)
        if letter not in seen:
            seen.add(letter)
            out.append({"letter": letter, "start": i})
    return out


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
    it can). What the library didn't say isn't held against it."""
    why = []
    if media.parts > 1:
        why.append(f"it's split into {media.parts} files")
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


def choose(
    entry: Entry, dev: Device, version: str | None = None, max_kbps: int | None = None
) -> tuple[Media | None, list[str]]:
    """The version of a program's file to play as it is on a device: the one
    asked for; or else the best the device can play that the connection
    keeps up with (as the app measured it: `max_kbps`), or with none that
    does, the smallest it can play. None, and why not, if it can't play any.
    A version that's gone counts as not asked for."""
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
    """What a device that can't play a file as it is is told."""
    return (
        f"This device can't play this file as it is: {and_list(why)}. StationPlay can't "
        "convert video for its apps yet."
    )


def and_list(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def track_name(track: Track, audio: bool) -> str:
    """How a track is listed in the apps: "English · Commentary · AAC ·
    Stereo", "Spanish · Forced"."""
    parts = [plain(track.language) or "Unknown language"]
    title = plain(track.title)
    if title and title.casefold() != parts[0].casefold():
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


def is_watched(position_ms: int, entry: Entry) -> bool:
    """Whether someone this far into a program has watched it: into its
    credits, or without them, most of the way."""
    if entry.credits is not None:
        return position_ms >= entry.credits[0]
    duration = entry.duration_ms or 0
    return duration > 0 and position_ms >= duration * WATCHED_SHARE


def resume_at(row: tuple[int, bool] | None) -> int:
    """Where to start a program again, from someone's progress in it
    (position, watched): the start if they'd barely started it, or finished
    it (which leaves its position at 0)."""
    if row is None:
        return 0
    position, _watched = row
    return position if position >= STARTED_MS else 0


def progressed(old: tuple[int, bool] | None, position_ms: int, entry: Entry) -> tuple[int, bool]:
    """Someone's progress in a program once they're `position_ms` into it:
    (where they are, watched). Reaching its credits finishes it (and starts
    it from the beginning next time); watched stays watched, even while
    they watch it again."""
    if is_watched(position_ms, entry):
        return 0, True
    return position_ms, bool(old and old[1])


def next_episode(episodes: list[Entry], after: str | None, watched: set[str]) -> Entry | None:
    """The episode to watch next, specials aside: the first one not watched
    after `after` (or from the start); or, with none left after it, the
    first one missed before it."""
    regular = [e for e in episodes if e.season != 0]
    keys = [e.key for e in regular]
    start = keys.index(after) + 1 if after in keys else 0
    later = (e for e in regular[start:] if e.key not in watched)
    missed = (e for e in regular[:start] if e.key not in watched and e.key != after)
    return next(later, None) or next(missed, None)


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
    away: bool
    # Subtitle files of their own: track id -> (where they're fetched, codec).
    subtitles: dict[str, tuple[str, str]] = field(default_factory=dict)
    # A copy StationPlay makes of it (converting.Copy), if it doesn't play
    # as it is; and where the player starts it.
    copy: Any = None
    start_s: float = 0.0
    started: float = field(default_factory=time.monotonic)
    seen: float = field(default_factory=time.monotonic)
    checked: float = field(default_factory=time.monotonic)


class PlaySessions:
    """The programs being played in the apps. Each has an address of its own
    (a player can't sign in), which ends when the app says it stopped, when
    it's unused for SESSION_IDLE_S, when its sign-in ends, and when
    StationPlay restarts. Nothing about them is kept on disk."""

    def __init__(self) -> None:
        self._sessions: dict[str, PlaySession] = {}

    def start(self, **details: Any) -> PlaySession:
        self._tidy()
        while len(self._sessions) >= SESSIONS_MOST:
            oldest = min(self._sessions.values(), key=lambda s: s.seen)
            self.end(oldest.id)
        session = PlaySession(id=secrets.token_urlsafe(SESSION_ID_BYTES), **details)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> PlaySession | None:
        """A session that's still going, now marked as used."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        now = time.monotonic()
        if now - session.seen > SESSION_IDLE_S:
            self.end(session_id)
            return None
        session.seen = now
        return session

    def end(self, session_id: str) -> PlaySession | None:
        """Ends a session (and stops its copy being made)."""
        session = self._sessions.pop(session_id, None)
        if session is not None and session.copy is not None:
            session.copy.stop()
        return session

    def end_all(self) -> None:
        for session_id in list(self._sessions):
            self.end(session_id)

    def copies(self) -> int:
        """Copies being converted (their pictures made) now, or asked for
        lately."""
        return sum(
            1
            for s in self._sessions.values()
            if s.copy is not None and not s.copy.plan.copies_picture and s.copy.active
        )

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
    """Pictures for the apps, the most recently used kept up to a size."""

    def __init__(self, most_bytes: int = PICTURE_BYTES_KEPT) -> None:
        self.most_bytes = most_bytes
        self._kept: OrderedDict[tuple[str, str, int], tuple[bytes, str]] = OrderedDict()
        self._bytes = 0

    def clear(self) -> None:
        self._kept.clear()
        self._bytes = 0

    def get(self, key: tuple[str, str, int]) -> tuple[bytes, str] | None:
        found = self._kept.get(key)
        if found is not None:
            self._kept.move_to_end(key)
        return found

    def put(self, key: tuple[str, str, int], picture: tuple[bytes, str]) -> None:
        if len(picture[0]) > self.most_bytes // 8:
            return  # (one huge picture doesn't push out everything else)
        old = self._kept.pop(key, None)
        if old is not None:
            self._bytes -= len(old[0])
        self._kept[key] = picture
        self._bytes += len(picture[0])
        while self._bytes > self.most_bytes:
            _, gone = self._kept.popitem(last=False)
            self._bytes -= len(gone[0])


def width_for(asked: int) -> int:
    """The width a picture is made at: the next of WIDTHS up from what's
    asked for (the largest, for anything larger)."""
    return next((w for w in WIDTHS if w >= asked), WIDTHS[-1])


# The Resume row and what's next -------------------------------------------------


async def up_next(cat: Catalog, db: Database, user_id: int, show: str) -> tuple[Entry, int] | None:
    """The episode of a show someone would play next, and where in it: the
    one they're partway through (or barely started), or the one after the
    last they finished, or the first. None when they've watched it all."""
    episodes = await cat.episodes(show)
    keys = [e.key for e in episodes]
    progress = db.progress_of(user_id, keys)
    after = None
    for row in db.recent_progress_of_show(user_id, show, SHOW_ROWS):
        key = row["rating_key"]
        state = where_they_are(row["position_ms"], bool(row["watched"]))
        if key not in keys or state == MARKED:
            continue
        if state != FINISHED:
            return episodes[keys.index(key)], resume_at(progress.get(key))
        after = key
        break
    watched = {k for k, (_, w) in progress.items() if w}
    found = next_episode(episodes, after, watched)
    return (found, resume_at(progress.get(found.key))) if found is not None else None


async def continue_watching(cat: Catalog, db: Database, user_id: int) -> list[tuple[Entry, int]]:
    """What someone was partway through, and the next episodes of shows they
    finished one of lately: (the program, where to start it), newest first,
    one per show."""
    picks: list[str] = []
    nexts: dict[str, tuple[int, str]] = {}  # show -> (place in picks, the episode finished)
    seen: set[str] = set()
    for row in db.recent_progress(user_id, CONTINUE_MOST * 10):
        show = row["show_key"]
        state = where_they_are(row["position_ms"], bool(row["watched"]))
        if state == MARKED or (show and show in seen):
            continue
        if show:
            seen.add(show)
        if state == PARTWAY or (show and state == STARTED):
            picks.append(row["rating_key"])
        elif show and state == FINISHED:
            nexts[show] = (len(picks), row["rating_key"])
            picks.append("")  # (filled in below)
        if len(picks) >= CONTINUE_MOST:
            break

    async def after(show: str, finished: str) -> str:
        try:
            episodes = await cat.episodes(show)
        except NotShared:
            return ""
        watched = db.watched_in_shows(user_id, [show]).get(show, set())
        found = next_episode(episodes, finished, watched)
        return found.key if found else ""

    found = await asyncio.gather(*(after(s, k) for s, (_, k) in nexts.items()))
    for (place, _), key in zip(nexts.values(), found, strict=True):
        picks[place] = key
    keys = list(dict.fromkeys(k for k in picks if k))
    progress = db.progress_of(user_id, keys)
    return [(e, resume_at(progress.get(e.key))) for e in await cat.entries(keys)]
