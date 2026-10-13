"""The library: everything tapiOca reads about your shows and movies,
whichever source they come from (see docs/library.md).

Everything that reads the media library goes through `Library`, never
through a source directly. Its sources are Plex, and folders of your own
(folders.py, from 1.35.0): tapiOca with or without Plex.

One program belongs to no source: the INFO station's (see infostation.py),
whose key, infostation.KEY, the library answers for itself, from the film in
the image, without asking Plex.

Every program, show, movie, collection and library has a key, a short string
the rest of tapiOca treats as opaque. Plex's keys are digits (as they
always were, so nothing stored changes); folder libraries' keys are "f"
followed by digits, so the two can never collide ("f0" is INFO's alone). A
key's shape says which source it belongs to.

What's about Plex the server rather than a library (the tuner's guide
refresh, who's watching, blocking, Plex accounts) stays on the Plex client.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING, Any

from . import infostation

if TYPE_CHECKING:
    from .catalog import Entry, Media
    from .db import Item
    from .folders import FolderSource
    from .plex import Lookups, PlexClient

PLEX_AWAY = "Plex isn't answering"


class LibraryError(Exception):
    """A library couldn't answer. `status` is the HTTP status its server
    answered with, if it answered (404: no such thing)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class NoPicture(LibraryError):
    """There's no such picture (a folder library's: Plex's say so with
    httpx.HTTPStatusError)."""

    def __init__(self, what: str = "") -> None:
        super().__init__(f"There's no picture{f' ({what})' if what else ''}", 404)


FOLDER_PREFIX = "f"
# How long a key may be (Plex's are well under this).
KEY_MAX = 20


def is_plex_key(key: str) -> bool:
    return key.isascii() and key.isdigit() and len(key) <= KEY_MAX


def is_folder_key(key: str) -> bool:
    return (
        key.startswith(FOLDER_PREFIX)
        and is_plex_key(key[len(FOLDER_PREFIX) :])
        and len(key) <= KEY_MAX
    )


def source_name(key: str) -> str:
    """Where a title is, as the page and the log say it: Plex, or a Media
    folder of tapiOca's own (1.35.0)."""
    return "its Media folder" if is_folder_key(key) else "Plex"


def is_key(key: object) -> bool:
    """Whether `key` is a library key of any source (digits, or "f" and
    digits): what's accepted anywhere a program, show, movie, collection
    or library is named."""
    if isinstance(key, int) and not isinstance(key, bool):
        key = str(key)
    return isinstance(key, str) and (is_plex_key(key) or is_folder_key(key))


NO_FOLDERS = "There's no such Media folder"


class Library:
    """The library, whichever sources it has. Each call goes to the source
    that owns the key it's about; calls about every library ask each source
    and put their answers together (Plex's first).

    `plex`: the Plex client, or what gives it (looked up on each call, so
    whatever the app holds at the time is what's used); `folders`: the
    folder libraries (folders.py), or what gives them."""

    def __init__(
        self,
        plex: PlexClient | Callable[[], PlexClient],
        folders: FolderSource | Callable[[], FolderSource | None] | None = None,
    ) -> None:
        self._plex: Callable[[], PlexClient] = plex if callable(plex) else (lambda: plex)
        self._folders: Callable[[], FolderSource | None] = (
            folders if callable(folders) else (lambda: folders)
        )

    @property
    def plex(self) -> PlexClient:
        return self._plex()

    @property
    def folders(self) -> FolderSource | None:
        return self._folders()

    def _folder_source(self) -> FolderSource:
        found = self.folders
        if found is None:
            raise LibraryError(NO_FOLDERS, 404)
        return found

    @property
    def plex_on(self) -> bool:
        """Whether Plex is set up (PLEX_URL and PLEX_TOKEN)."""
        return self.plex.configured

    @property
    def folders_on(self) -> bool:
        """Whether there's a folder library."""
        found = self.folders
        return found is not None and found.configured

    # Status ----------------------------------------------------------------

    @property
    def configured(self) -> bool:
        """Whether any library is set up."""
        return self.plex_on or self.folders_on

    async def check(self) -> None:
        """Raises LibraryError unless every library can be reached now.
        (Folder libraries are on this machine: a share that's gone is said
        for each of its programs, never for them all.)"""
        if self.plex_on or not self.folders_on:
            await self.plex.identity()

    # Libraries -------------------------------------------------------------

    async def libraries(self) -> list[dict[str, Any]]:
        """Every library: key, title, type ("show" or "movie") and the
        folders it's made of (`locations`). Plex's first. LibraryError if
        Plex can't list its own (see listed)."""
        found = await self.plex.sections() if self.plex_on else []
        if self.folders is not None:
            found += await self.folders.libraries_list()
        return found

    async def listed(
        self, plex_wait: float | None = None
    ) -> tuple[list[dict[str, Any]], LibraryError | None]:
        """The libraries that can be listed now, as libraries() has them,
        and why Plex's can't be, if they can't (None if they are): with
        Plex away, folder libraries are still listed (for Media in the
        apps, and the page's lists). `plex_wait`: how long Plex is waited
        for, at most."""
        try:
            ask = self.libraries()
            return await (asyncio.wait_for(ask, plex_wait) if plex_wait else ask), None
        except TimeoutError:
            away = LibraryError(PLEX_AWAY, 503)
        except LibraryError as e:
            away = e
        mine = await self.folders.libraries_list() if self.folders is not None else []
        return mine, away

    async def library_items(self, library: str) -> list[dict[str, Any]]:
        """The shows or movies in one library."""
        if is_folder_key(library):
            return await self._folder_source().library_items(library)
        return await self.plex.section_items(library)

    async def counts(self, keys: Collection[str] | None = None) -> tuple[int, int, int, int]:
        """How many movies, shows and episodes there are in these libraries
        (by key; None: every one), and how many movies and episodes were
        added in the last week (for INFO: see infostation.py)."""
        since_s = int(time.time()) - 7 * 86400
        plex_keys = None if keys is None else [k for k in keys if is_plex_key(k)]
        folder_keys = None if keys is None else [k for k in keys if is_folder_key(k)]
        totals = [0, 0, 0, 0]
        if self.plex_on and plex_keys != []:
            totals = list(await self.plex.counts(since_s, plex_keys))
        if self.folders is not None and folder_keys != []:
            got = self.folders.totals(since_s, folder_keys)
            totals = [a + b for a, b in zip(totals, got, strict=True)]
        return totals[0], totals[1], totals[2], totals[3]

    async def fingerprint(self) -> str:
        """Changes whenever anything in any library may have."""
        plex = await self.plex.library_fingerprint() if self.plex_on else ""
        folders = self.folders.fingerprint() if self.folders is not None else ""
        return f"{plex}|folders:{folders}" if folders else plex

    async def fingerprint_here(self) -> str:
        """As fingerprint, for what can be listed now (Media in the apps):
        with Plex away, folder libraries still have theirs, so they can be
        browsed while it is. (Stations follow fingerprint, which waits for
        Plex.)"""
        try:
            return await self.fingerprint()
        except LibraryError:
            if not self.folders_on or self.folders is None:
                raise
            return f"plex-away|folders:{self.folders.fingerprint()}"

    # Filters ---------------------------------------------------------------

    async def filter_fields(self, library: str, kind: str) -> list[dict[str, str]]:
        if is_folder_key(library):
            return await self._folder_source().filter_fields(library, kind)
        return await self.plex.filter_fields(library, kind)

    async def choices(self, library: str, field: str, kind: str) -> list[dict[str, str]]:
        if is_folder_key(library):
            return await self._folder_source().choices(library, field, kind)
        return await self.plex.choices(library, field, kind)

    def _split(self, source: dict[str, Any]) -> tuple[dict | None, dict | None]:
        """A filter's libraries, as one filter for Plex's and one for the
        folder libraries (None for either that has none)."""
        libraries = [str(k) for k in source.get("libraries") or []]
        plex = [k for k in libraries if is_plex_key(k)]
        folders = [k for k in libraries if is_folder_key(k)]
        return (
            {**source, "libraries": plex} if plex else None,
            {**source, "libraries": folders} if folders and self.folders is not None else None,
        )

    async def filter_matches(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        plex, folders = self._split(source)
        found = await self.plex.filter_matches(plex) if plex else []
        if folders:
            found += await self._folder_source().filter_matches(folders)
        return found

    async def filter_episodes(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        plex, folders = self._split(source)
        found = await self.plex.filter_episodes(plex) if plex else []
        if folders:
            found += await self._folder_source().filter_episodes(folders)
        return found

    # Collections -----------------------------------------------------------

    async def collections(self) -> list[dict[str, Any]]:
        found = await self.plex.collections() if self.plex_on else []
        if self.folders is not None:
            found += await self.folders.collections()
        return found

    def followed_collection(
        self, source: dict[str, Any], collections: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Which of `collections` a station's collection source follows."""
        if is_folder_key(str(source.get("ratingKey") or "")):
            mine = [c for c in collections if is_folder_key(str(c["ratingKey"]))]
            return self._folder_source().followed_collection(source, mine)
        plex = [c for c in collections if not is_folder_key(str(c["ratingKey"]))]
        return self.plex.followed_collection(source, plex)

    # Building stations -----------------------------------------------------

    async def items_for_source(self, source: dict[str, Any]) -> list[Item]:
        """The programs one of a station's sources stands for."""
        if infostation.is_info_source(source):
            return [infostation.program()]
        kind = source.get("type")
        if kind == "filter":
            plex, folders = self._split(source)
            found = await self.plex.items_for_source(plex) if plex else []
            if folders:
                found += await self._folder_source().items_for_source(folders)
            return found
        key = str((source.get("key") if kind == "section" else source.get("ratingKey")) or "")
        if is_folder_key(key):
            return await self._folder_source().items_for_source(source)
        return await self.plex.items_for_source(source)

    async def find_again(self, item: Item, looked: Lookups | None = None) -> str | None:
        """The key a program has now, if its library has it again under
        another one (re-added, rematched or moved)."""
        if item.rating_key == infostation.KEY:
            return None
        if is_folder_key(item.rating_key):
            return await self.folders.find_again(item) if self.folders is not None else None
        return await self.plex.find_again(item, looked)

    # Playing ---------------------------------------------------------------

    async def current_files(self, key: str) -> tuple[Media, ...]:
        """The files a program has now, in order: one, or several for a
        movie on two discs, say, played one after the other as one (see
        catalog.Media); () if the library has it without a file."""
        if key == infostation.KEY:
            return (infostation.media(),)
        if is_folder_key(key):
            return await self._folder_source().current_files(key)
        return await self.plex.current_files(key)

    def stream_url(self, key: str, part_key: str) -> str | None:
        """An address to stream a program's file from, for when tapiOca
        can't read it directly (None: there's no such address; a folder
        library's files are only ever read from disk)."""
        if is_folder_key(key):
            return None
        return self.plex.stream_url(part_key)

    def resolution(self, key: str) -> str | None:
        """A program's picture size as its library lists it ("4K", "1080p",
        "720p" or "SD"), if it's been said."""
        if is_folder_key(key):
            return self.folders.resolution(key) if self.folders is not None else None
        return self.plex.resolutions.get(key)

    # Markers ---------------------------------------------------------------

    async def markers(self, key: str) -> list[dict[str, Any]]:
        return (await self.markers_and_added(key))[0]

    async def markers_and_added(self, key: str) -> tuple[list[dict[str, Any]], int | None]:
        """A program's intro and credits markers, and when it was added
        (folder libraries have no markers yet)."""
        if key == infostation.KEY:
            return [], None
        if is_folder_key(key):
            return await self._folder_source().markers_and_added(key)
        return await self.plex.markers_and_added(key)

    # Artwork ---------------------------------------------------------------

    async def art(self, key: str) -> tuple[bytes, str]:
        """A program's picture: (bytes, content type)."""
        if key == infostation.KEY:
            return infostation.LOGO_FILE.read_bytes(), "image/png"
        if is_folder_key(key):
            return await self._folder_source().art(key)
        return await self.plex.get_bytes(f"/library/metadata/{key}/thumb")

    async def poster(self, key: str, width: int, height: int) -> tuple[bytes, str]:
        if key == infostation.KEY:
            return infostation.LOGO_FILE.read_bytes(), "image/png"
        if is_folder_key(key):
            return await self._folder_source().poster(key, width, height)
        return await self.plex.poster(key, width, height)

    async def clear_logo(self, key: str) -> tuple[str, str] | None:
        """A show's or movie's title artwork: (its title, where to fetch
        it), if it has one."""
        if is_folder_key(key):
            return await self._folder_source().clear_logo(key)
        return await self.plex.clear_logo(key)

    async def logo_bytes(self, key: str, where: str) -> bytes:
        if is_folder_key(key):
            return await self._folder_source().logo_bytes(where)
        return await self.plex.logo_bytes(where)

    # For tapiOca's apps (see docs/on-demand.md) ------------------------

    async def browse(
        self, library: str, kind: str, sort: str, start: int, size: int, genre: str | None = None
    ) -> tuple[int, list[Entry]]:
        """A page of a library's shows or movies (sort: "title", "added" or
        "released"; `genre`: only those with it, by its id from `genres`):
        (how many in all, the page)."""
        if is_folder_key(library):
            return await self._folder_source().browse(library, kind, sort, start, size, genre)
        return await self.plex.browse(library, kind, sort, start, size, genre)

    async def genres(self, library: str, kind: str) -> list[dict[str, str]]:
        """A library's genres: [{"id", "title"}] (none if it has none)."""
        return await self.choices(library, "genre", kind)

    async def recently_added(self, library: str, kind: str, count: int) -> list[Entry]:
        if is_folder_key(library):
            return await self._folder_source().recently_added(library, kind, count)
        return await self.plex.recently_added(library, kind, count)

    async def added_files(
        self, library: str, kind: str, start: int, size: int
    ) -> tuple[int, list[Entry]]:
        """A page of a library's episodes or movies, the newest first, with
        their versions' files: (how many in all, the page)."""
        if is_folder_key(library):
            return await self._folder_source().added_files(library, kind, start, size)
        return await self.plex.added_files(library, kind, start, size)

    async def entry(self, key: str, details: bool = False) -> Entry | None:
        """A show, movie or episode; None if there's no such thing."""
        if is_folder_key(key):
            return await self.folders.entry_of(key, details) if self.folders is not None else None
        return await self.plex.entry(key, details)

    async def entries(self, keys: list[str]) -> list[Entry]:
        """Several at once, in the order asked (those gone are left out)."""
        plex = [k for k in keys if is_plex_key(k)]
        folders = [k for k in keys if is_folder_key(k)]
        found = {e.key: e for e in (await self.plex.entries(plex) if plex else [])}
        if folders and self.folders is not None:
            found.update((e.key, e) for e in await self.folders.entries(folders))
        return [found[k] for k in dict.fromkeys(keys) if k in found]

    async def show_episodes(self, show: str) -> list[Entry]:
        if is_folder_key(show):
            return await self.folders.show_episodes(show) if self.folders is not None else []
        return await self.plex.show_episodes(show)

    async def picture(self, key: str, which: str, width: int, height: int) -> tuple[bytes, str]:
        """A picture of a show, movie or episode: "thumb" (a poster, or an
        episode's still) or "art" (a backdrop). NoPicture (or for Plex's,
        httpx.HTTPStatusError) if it has none."""
        if is_folder_key(key):
            return await self._folder_source().picture(key, which, width, height)
        return await self.plex.picture(key, which, width, height)

    # Sonarr and Radarr -----------------------------------------------------

    async def ids(self, key: str) -> dict[str, str]:
        """A show's or movie's IDs elsewhere (tvdb, tmdb, imdb) and its
        library (`section`)."""
        if is_folder_key(key):
            return await self._folder_source().ids(key)
        return await self.plex.ids(key)

    async def scan_folder(self, library: str, folder: str) -> None:
        """Asks a library to look for new files in one of its folders."""
        if is_folder_key(library):
            return await self._folder_source().scan_folder(library, folder)
        return await self.plex.scan_folder(library, folder)
