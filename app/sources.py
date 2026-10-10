"""Finding the actual file to play for a scheduled item.

Plex reports each file's path as Plex's own container sees it (for example
/data/media/TV/Show/S01E01.mkv). StationPlay usually sees the same files
under a different path (its media folder, /media by default). Rather than
make you configure the translation, StationPlay works it out: it looks for
the tail of Plex's path inside its media folder, and once it finds a file
it remembers the mapping and uses it for everything else.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field, replace

from .config import Settings
from .db import Item
from .library import Library, LibraryError

log = logging.getLogger(__name__)


@dataclass
class ResolvedSource:
    source: str | None
    plex_file: str | None = None
    size: int | None = None
    error: str | None = None
    # True when the failure says nothing about the file itself (Plex or the
    # media share unreachable), so it must not land on the broken list.
    transient: bool = False


@dataclass
class MediaAccess:
    """Learned path mappings plus counts, for the status page."""

    # Plex path prefix -> local path prefix, discovered automatically.
    learned: dict[str, str] = field(default_factory=dict)
    direct: int = 0  # files read straight from disk
    via_plex: int = 0  # files streamed from Plex because they weren't visible

    def as_dict(self, media_dir: str, present: bool) -> dict:
        return {
            "mediaDir": media_dir,
            "mediaDirPresent": present,
            "mappings": [{"plex": plex, "local": local} for plex, local in self.learned.items()],
            "direct": self.direct,
            "viaPlex": self.via_plex,
        }


@dataclass(frozen=True)
class Candidate:
    """A place a file might be, and the prefix swap that produced it."""

    path: str
    plex_prefix: str
    local_prefix: str


def _first_existing(candidates: list[Candidate]) -> Candidate | None:
    for candidate in candidates:
        if os.path.isfile(candidate.path):
            return candidate
    return None


async def find_first(
    candidates: list[Candidate], timeout: float = 8.0
) -> tuple[Candidate | None, bool]:
    """The first candidate that exists, checked off the event loop.

    Returns (candidate, timed_out). A stuck network mount can't hang the caller.
    """
    if not candidates:
        return None, False
    try:
        found = await asyncio.wait_for(asyncio.to_thread(_first_existing, candidates), timeout)
        return found, False
    except TimeoutError:
        return None, True


def local_candidates(settings: Settings, access: MediaAccess, plex_file: str) -> list[Candidate]:
    """Where a file Plex reports might be visible to this container, best first."""
    out: list[Candidate] = []
    for plex_prefix, local_prefix in access.learned.items():
        if plex_file.startswith(plex_prefix + "/"):
            out.append(
                Candidate(local_prefix + plex_file[len(plex_prefix) :], plex_prefix, local_prefix)
            )
    # Explicit PATH_MAPPINGS (or the path as-is, if the library is mounted
    # at the same place Plex has it).
    out.append(Candidate(settings.map_path(plex_file), "", ""))
    media_dir = settings.media_dir.rstrip("/")
    if media_dir:
        parts = plex_file.strip("/").split("/")
        # Longest tail first, so the most specific match wins.
        out.extend(
            Candidate(
                f"{media_dir}/{'/'.join(parts[i:])}",
                "/" + "/".join(parts[:i]) if i else "",
                media_dir,
            )
            for i in range(len(parts) - 1)
        )
    unique: dict[str, Candidate] = {}
    for candidate in out:
        unique.setdefault(candidate.path, candidate)
    return list(unique.values())


def learn_mapping(access: MediaAccess, candidate: Candidate) -> None:
    """Remembers a prefix swap that found a file, for all later lookups."""
    if not candidate.plex_prefix or candidate.plex_prefix in access.learned:
        return
    access.learned[candidate.plex_prefix] = candidate.local_prefix
    log.info(
        "Found Plex's %s at %s; reading files there directly",
        candidate.plex_prefix,
        candidate.local_prefix,
    )


# How long Plex has to say which file a program has now.
PLEX_LOOKUP_S = 10
# Programs already said to be gone from Plex (once each, not each time).
_said_gone: set[str] = set()
_said_moved: set[str] = set()


# A program Plex no longer has under its key has been removed from Plex
# (it's broken while a station still has it), or added again under a new
# key (it isn't: it plays from the file Plex has under the new key until
# the station's next update from Plex takes that up, or is skipped if that
# file can't be read now; see Plex.find_again).
REMOVED = "removed from Plex"
ADDED_AGAIN = "re-added to Plex under a new key, but its new file can't be read right now"
# How long Plex has to say which.
FIND_AGAIN_S = 30.0


def _say_once_its_moved(item: Item, again: str) -> None:
    if item.rating_key in _said_moved:
        return
    if len(_said_moved) > 10_000:
        _said_moved.clear()
    _said_moved.add(item.rating_key)
    log.info(
        "%s was re-added to Plex under a new key (%s); playing the file Plex has under that "
        "key until the station's next update from Plex",
        item.label,
        again,
    )


def _say_once_its_gone(item: Item) -> None:
    if item.rating_key in _said_gone:
        return
    if len(_said_gone) > 10_000:
        _said_gone.clear()
    _said_gone.add(item.rating_key)
    log.info(
        "%s is no longer in Plex under its key (it was removed, or re-added under a new key); "
        "playing its old file until the station's next update from Plex",
        item.label,
    )


async def resolve_source(
    settings: Settings,
    library: Library,
    item: Item,
    access: MediaAccess | None = None,
    *,
    follow: bool = True,
) -> ResolvedSource:
    """Works out where to read an item from.

    Plex is asked for the item's current file first, so episodes Sonarr
    upgraded or renamed since the channel was built are still found. The
    file is read straight from disk when this app can see it, and streamed
    from Plex otherwise.
    """
    access = access if access is not None else MediaAccess()
    plex_reachable = True
    # Plex answered that it has no such item: removed, or added again under
    # another key (the station follows that at its next update from Plex).
    gone = False
    part = None
    try:
        part = await asyncio.wait_for(library.current_part(item.rating_key), PLEX_LOOKUP_S)
    except (TimeoutError, LibraryError) as e:
        if isinstance(e, LibraryError) and e.status == 404:
            gone = True
        else:
            plex_reachable = False
            why = str(e) or f"Plex didn't answer within {PLEX_LOOKUP_S}s"
            log.warning(
                "Plex lookup for %s (%s) failed (%s); using the saved path",
                item.rating_key,
                item.label,
                why,
            )

    plex_file = (part.file if part else None) or item.file_path
    part_key = (part.key if part else None) or item.part_key
    size = part.size if part else None

    if plex_reachable and part is None and not gone:
        return ResolvedSource(
            None, plex_file, size, error="no longer in Plex (deleted or unmatched)"
        )

    if plex_file:
        found, timed_out = await find_first(local_candidates(settings, access, plex_file))
        if found:
            learn_mapping(access, found)
            access.direct += 1
            if gone:
                _say_once_its_gone(item)
            return ResolvedSource(found.path, plex_file, size)
        if timed_out:
            return ResolvedSource(
                None, plex_file, size, error="the media share isn't responding", transient=True
            )

    if gone:
        # Removed from Plex, or added again under a new key: Plex can say
        # which. Only a program it no longer has at all is broken.
        try:
            again = await asyncio.wait_for(library.find_again(item), FIND_AGAIN_S)
        except (TimeoutError, LibraryError) as e:
            return ResolvedSource(
                None,
                plex_file,
                size,
                error=f"not in Plex under its key, and Plex couldn't say whether it was "
                f"re-added ({e})",
                transient=True,
            )
        if again is not None:
            # (Followed once: Plex can't have moved it again meanwhile.)
            moved = (
                await resolve_source(
                    settings,
                    library,
                    replace(item, rating_key=again, file_path=None, part_key=None),
                    access,
                    follow=False,
                )
                if follow
                else None
            )
            if moved is not None and moved.source:
                _say_once_its_moved(item, again)
                return moved
            return ResolvedSource(None, plex_file, size, error=ADDED_AGAIN, transient=True)
        return ResolvedSource(None, plex_file, size, error=REMOVED)

    stream = (
        library.stream_url(item.rating_key, part_key)
        if part_key and plex_reachable and library.configured
        else None
    )
    if stream is not None:
        access.via_plex += 1
        return ResolvedSource(stream, plex_file, size)

    if not plex_reachable:
        return ResolvedSource(
            None,
            plex_file,
            size,
            error="Plex can't be reached, and StationPlay can't see the file directly",
            transient=True,
        )
    return ResolvedSource(None, plex_file, size, error=f"file not found: {plex_file}")


# A version of a program that's gone from its library: nothing offers it
# any more, so it isn't checked (or listed).
VERSION_GONE = "that version is no longer in Plex"


async def resolve_version(
    settings: Settings,
    library: Library,
    item: Item,
    version: str,
    access: MediaAccess | None = None,
) -> ResolvedSource:
    """Works out where to read one version of a program's file (`version`:
    its ID in the library), for one that isn't the program's first (which
    is resolve_source's). The library is asked what the program has now. A
    version that's gone is said to be (transient: it isn't the file's fault,
    and nothing offers it any more)."""
    access = access if access is not None else MediaAccess()
    try:
        entry = await asyncio.wait_for(library.entry(item.rating_key, details=True), PLEX_LOOKUP_S)
    except (TimeoutError, LibraryError) as e:
        why = str(e) or f"Plex didn't answer within {PLEX_LOOKUP_S}s"
        return ResolvedSource(None, item.file_path, None, error=why, transient=True)
    media = entry.version(version) if entry is not None else None
    if media is None:  # (gone; or it's the first now, and known by the program's key)
        return ResolvedSource(None, item.file_path, None, error=VERSION_GONE, transient=True)
    if media.file:
        found, timed_out = await find_first(local_candidates(settings, access, media.file))
        if found:
            learn_mapping(access, found)
            access.direct += 1
            return ResolvedSource(found.path, media.file, media.size)
        if timed_out:
            return ResolvedSource(
                None, media.file, media.size, error="the media share isn't responding",
                transient=True,
            )  # fmt: skip
    stream = (
        library.stream_url(item.rating_key, media.part_key)
        if media.part_key and library.configured
        else None
    )
    if stream is not None:
        access.via_plex += 1
        return ResolvedSource(stream, media.file, media.size)
    return ResolvedSource(None, media.file, media.size, error=f"file not found: {media.file}")
