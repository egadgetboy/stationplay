"""The library: everything StationPlay reads about your shows and movies,
whichever source they come from (see docs/library.md).

Everything that reads the media library goes through `Library`, never
through a source directly. Today its one source is Plex; folders of your own
come later, and nothing outside this module needs to change for them.

Every program, show, movie, collection and library has a key, a short string
the rest of StationPlay treats as opaque. Plex's keys are digits (as they
always were, so nothing stored changes); folder libraries' keys will be "f"
followed by digits, so the two can never collide. A key's shape says which
source it belongs to.

What's about Plex the server rather than a library (the tuner's guide
refresh, who's watching, blocking, Plex accounts) stays on the Plex client.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .catalog import Entry
    from .db import Item
    from .plex import Lookups, MediaPart, PlexClient


class LibraryError(Exception):
    """A library couldn't answer. `status` is the HTTP status its server
    answered with, if it answered (404: no such thing)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


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


def is_key(key: str) -> bool:
    """Whether `key` is a library key of any source."""
    return is_plex_key(key) or is_folder_key(key)


def _not_yet(key: str) -> LibraryError:
    return LibraryError(f"StationPlay doesn't read folder libraries yet ({key})", 404)


class Library:
    """The library, whichever sources it has. Each call goes to the source
    that owns the key it's about; calls about every library ask each source.

    `plex`: the Plex client, or what gives it (looked up on each call, so
    whatever the app holds at the time is what's used)."""

    def __init__(self, plex: PlexClient | Callable[[], PlexClient]) -> None:
        self._plex: Callable[[], PlexClient] = plex if callable(plex) else (lambda: plex)

    @property
    def plex(self) -> PlexClient:
        return self._plex()

    def _plex_for(self, key: str) -> PlexClient:
        if is_folder_key(key):
            raise _not_yet(key)
        return self.plex

    # Status ----------------------------------------------------------------

    @property
    def configured(self) -> bool:
        """Whether any library is set up."""
        return self.plex.configured

    async def check(self) -> None:
        """Raises LibraryError unless every library can be reached now."""
        await self.plex.identity()

    # Libraries -------------------------------------------------------------

    async def libraries(self) -> list[dict[str, Any]]:
        """Every library: key, title, type ("show" or "movie") and the
        folders it's made of (`locations`)."""
        return await self.plex.sections()

    async def library_items(self, library: str) -> list[dict[str, Any]]:
        """The shows or movies in one library."""
        return await self._plex_for(library).section_items(library)

    async def fingerprint(self) -> str:
        """Changes whenever anything in any library may have."""
        return await self.plex.library_fingerprint()

    # Filters ---------------------------------------------------------------

    async def filter_fields(self, library: str, kind: str) -> list[dict[str, str]]:
        return await self._plex_for(library).filter_fields(library, kind)

    async def choices(self, library: str, field: str, kind: str) -> list[dict[str, str]]:
        return await self._plex_for(library).choices(library, field, kind)

    async def filter_matches(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.plex.filter_matches(source)

    async def filter_episodes(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.plex.filter_episodes(source)

    # Collections -----------------------------------------------------------

    async def collections(self) -> list[dict[str, Any]]:
        return await self.plex.collections()

    def followed_collection(
        self, source: dict[str, Any], collections: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Which of `collections` a station's collection source follows."""
        return self.plex.followed_collection(source, collections)

    # Building stations -----------------------------------------------------

    async def items_for_source(self, source: dict[str, Any]) -> list[Item]:
        """The programs one of a station's sources stands for."""
        return await self.plex.items_for_source(source)

    async def find_again(self, item: Item, looked: Lookups | None = None) -> str | None:
        """The key a program has now, if its library has it again under
        another one (re-added, rematched or moved)."""
        if is_folder_key(item.rating_key):
            return None
        return await self.plex.find_again(item, looked)

    # Playing ---------------------------------------------------------------

    async def current_part(self, key: str) -> MediaPart | None:
        """The file a program has now (None: the library has it, without a
        file)."""
        return await self._plex_for(key).current_part(key)

    def stream_url(self, key: str, part_key: str) -> str | None:
        """An address to stream a program's file from, for when StationPlay
        can't read it directly (None: there's no such address)."""
        if is_folder_key(key):
            return None
        return self.plex.stream_url(part_key)

    # Markers ---------------------------------------------------------------

    async def markers(self, key: str) -> list[dict[str, Any]]:
        return await self._plex_for(key).markers(key)

    async def markers_and_added(self, key: str) -> tuple[list[dict[str, Any]], int | None]:
        return await self._plex_for(key).markers_and_added(key)

    # Artwork ---------------------------------------------------------------

    async def art(self, key: str) -> tuple[bytes, str]:
        """A program's picture: (bytes, content type)."""
        return await self._plex_for(key).get_bytes(f"/library/metadata/{key}/thumb")

    async def poster(self, key: str, width: int, height: int) -> tuple[bytes, str]:
        return await self._plex_for(key).poster(key, width, height)

    async def clear_logo(self, key: str) -> tuple[str, str] | None:
        """A show's or movie's title artwork: (its title, where to fetch
        it), if it has one."""
        return await self._plex_for(key).clear_logo(key)

    async def logo_bytes(self, key: str, where: str) -> bytes:
        return await self._plex_for(key).logo_bytes(where)

    # For StationPlay's apps (see docs/on-demand.md) ------------------------

    async def browse(
        self, library: str, kind: str, sort: str, start: int, size: int, genre: str | None = None
    ) -> tuple[int, list[Entry]]:
        """A page of a library's shows or movies (sort: "title", "added" or
        "released"; `genre`: only those with it, by its id from `genres`):
        (how many in all, the page)."""
        return await self._plex_for(library).browse(library, kind, sort, start, size, genre)

    async def genres(self, library: str, kind: str) -> list[dict[str, str]]:
        """A library's genres: [{"id", "title"}] (none if it has none)."""
        return await self._plex_for(library).choices(library, "genre", kind)

    async def recently_added(self, library: str, kind: str, count: int) -> list[Entry]:
        return await self._plex_for(library).recently_added(library, kind, count)

    async def search(self, library: str, kind: str, words: str, count: int) -> list[Entry]:
        return await self._plex_for(library).search(library, kind, words, count)

    async def entry(self, key: str, details: bool = False) -> Entry | None:
        """A show, movie or episode; None if there's no such thing."""
        if is_folder_key(key):
            return None
        return await self.plex.entry(key, details)

    async def entries(self, keys: list[str]) -> list[Entry]:
        """Several at once, in the order asked (those gone are left out)."""
        return await self.plex.entries([k for k in keys if is_plex_key(k)])

    async def show_episodes(self, show: str) -> list[Entry]:
        if is_folder_key(show):
            return []
        return await self.plex.show_episodes(show)

    async def picture(self, key: str, which: str, width: int, height: int) -> tuple[bytes, str]:
        """A picture of a show, movie or episode: "thumb" (a poster, or an
        episode's still) or "art" (a backdrop)."""
        return await self._plex_for(key).picture(key, which, width, height)

    # Sonarr and Radarr -----------------------------------------------------

    async def ids(self, key: str) -> dict[str, str]:
        """A show's or movie's IDs elsewhere (tvdb, tmdb, imdb) and its
        library (`section`)."""
        return await self._plex_for(key).ids(key)

    async def scan_folder(self, library: str, folder: str) -> None:
        """Asks a library to look for new files in one of its folders."""
        await self._plex_for(library).scan_folder(library, folder)
