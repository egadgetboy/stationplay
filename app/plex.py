"""A small async client for the parts of the Plex API this app needs."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from . import catalog
from .catalog import Entry, Media, Track
from .db import Item
from .library import LibraryError

log = logging.getLogger(__name__)

# Plex's numeric metadata types, used for whole-library queries.
TYPE_MOVIE = 1
TYPE_EPISODE = 4
TYPE_SHOW = 2
TYPE_COLLECTION = 18
# Entries per request when listing a whole library or show.
PAGE_SIZE = 1000
# Background requests (building and checking stations) StationPlay has in
# flight to Plex at once, at most. Lookups for programs about to play don't
# wait behind them.
BULK_REQUESTS = 6
# Requests about programs' intro and credits markers in flight at once, at
# most; separate from BULK_REQUESTS so browsing Plex never waits behind them.
MARKER_REQUESTS = 6
# The kinds of tag filters saved before 1.6 kept at the top level of a
# filter (1.6 keeps every kind under "tags").
TAG_FIELDS = ("genre", "director", "actor", "collection", "label")
# What a library can be filtered on if Plex doesn't say (older servers).
DEFAULT_FIELDS = (
    ("genre", "Genre"),
    ("collection", "Collection"),
    ("label", "Label"),
    ("director", "Director"),
    ("actor", "Actor"),
)
# Filters with thousands of names: searched as you type rather than listed.
PEOPLE_FIELDS = frozenset({"director", "actor", "writer", "producer"})
# Plex filters StationPlay handles itself (decade, title) or that describe
# someone's viewing rather than the program (unwatched...).
OWN_FIELDS = frozenset({"decade", "year", "title", "unwatched", "inProgress", "unmatched"})
# Plex's lists of genres, directors and so on are kept this long.
CHOICES_TTL_S = 600


class PlexError(LibraryError):
    """Plex couldn't answer (`status`: the HTTP status it answered with, if it
    did). Plex is a library, so this is a LibraryError too."""


# What every address StationPlay asks Plex for looks like: names and numbers
# (Plex's keys) between slashes, never "..", a query or anything escaped.
# Keys come partly from what people send StationPlay, and the token makes
# every request the server owner's, so nothing else is ever sent.
_PLEX_PATH = re.compile(r"(/[A-Za-z0-9_:-]+)+")
# (And several shows, movies or episodes at once, by their keys.)
_KEYS_PATH = re.compile(r"/library/metadata/\d+(,\d+)+")


def _checked(path: str) -> str:
    # (/: the server's own details.)
    if path != "/" and not _PLEX_PATH.fullmatch(path) and not _KEYS_PATH.fullmatch(path):
        raise PlexError(f"That isn't a Plex address StationPlay uses: {path[:80]!r}", 400)
    return path


# Where Plex keeps a show's or movie's logo (its "clear logo"), and the
# largest one StationPlay fetches (as large as an upload may be).
_CLEAR_LOGO = re.compile(r"/library/metadata/\d+/clearLogo/\d+")
MAX_LOGO_BYTES = 10 * 1024 * 1024


async def gather_all(aws) -> list:
    """Runs requests together; if one fails, the rest are cancelled and the
    first PlexError is raised."""
    tasks: list[asyncio.Task] = []
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(a) for a in aws]
    except* PlexError as errors:
        raise errors.exceptions[0] from None
    return [t.result() for t in tasks]


@dataclass
class MediaPart:
    file: str | None
    key: str | None
    size: int | None
    duration_ms: int | None


@dataclass
class Lookups:
    """What Plex said, kept while going through a list (see find_again):
    shows' episodes by key, and shows and movies by title."""

    episodes: dict[str, list[Item]] = dataclasses.field(default_factory=dict)
    titles: dict[tuple[str, str], list[dict[str, Any]]] = dataclasses.field(default_factory=dict)


class PlexClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.AsyncClient(
            base_url=self.base_url or "http://plex.invalid",
            timeout=timeout,
            transport=transport,
            headers={
                "Accept": "application/json",
                "X-Plex-Token": token,
                "X-Plex-Product": "StationPlay",
                "X-Plex-Client-Identifier": "stationplay-live-channels",
            },
        )
        self._bulk = asyncio.Semaphore(BULK_REQUESTS)
        self._marker_slots = asyncio.Semaphore(MARKER_REQUESTS)
        self._choices: dict[tuple[str, str, int], tuple[float, list[dict[str, str]]]] = {}
        # Collections Plex made again, and shows and movies Plex added again
        # (removed and found again, or matched afresh): the rating key a
        # station has, and the new one.
        self._moved_collections: dict[str, str] = {}
        self._moved_titles: dict[str, str] = {}
        # The library each show or movie a station has was last found in
        # (kept between restarts, through `remember_libraries`, if set).
        self.libraries: dict[str, str] = {}
        self.remember_libraries: Callable[[dict[str, str]], None] | None = None
        # The file names stations have for a show (by its key) or a movie, for
        # telling apart shows or movies of one title when one's followed
        # (casefolded; set by the app).
        self.known_files: Callable[[str], set[str]] | None = None
        # Each program's picture size as Plex lists it ("4K", "1080p",
        # "720p" or "SD"), by rating key: noted whenever stations' programs
        # are fetched (for the stations' cards; nothing depends on it).
        self.resolutions: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(
        self, path: str, params: dict | None = None, bulk: bool = False
    ) -> dict[str, Any]:
        if not bulk:
            return await self._request(path, params)
        async with self._bulk:
            return await self._request(path, params)

    async def _request(self, path: str, params: dict | None) -> dict[str, Any]:
        if not self.configured:
            raise PlexError("PLEX_URL and PLEX_TOKEN aren't set")
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self._client.get(_checked(path), params=params)
                if resp.status_code == 401:
                    raise PlexError("Plex didn't accept the token in PLEX_TOKEN", 401)
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    # Asking again won't change the answer.
                    raise PlexError(
                        f"Plex returned HTTP {resp.status_code} for {path}", resp.status_code
                    )
                resp.raise_for_status()
                return resp.json().get("MediaContainer", {})
            except PlexError:
                raise
            except (httpx.HTTPError, ValueError) as e:
                last_error = e
                await asyncio.sleep(0.5 * (attempt + 1))
        raise PlexError(f"Plex request for {path} failed ({self._quiet(last_error)})")

    async def _get_all(self, path: str, params: dict | None = None) -> list[dict[str, Any]]:
        """Every entry at `path`, fetched a page at a time, so a library of
        tens of thousands of episodes never has to arrive (or time out) as
        one response."""
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        start = 0
        while True:
            page = {
                **(params or {}),
                "X-Plex-Container-Start": start,
                "X-Plex-Container-Size": PAGE_SIZE,
            }
            data = await self._get(path, params=page, bulk=True)
            batch = data.get("Metadata", [])
            new = [m for m in batch if str(m.get("ratingKey")) not in seen]
            seen.update(str(m.get("ratingKey")) for m in new)
            out.extend(new)
            start += len(batch)
            total = data.get("totalSize")
            # Stop at the last page, or if Plex sent everything at once or
            # nothing new (an old server that ignores paging).
            if len(batch) != PAGE_SIZE or not new:
                return out
            if isinstance(total, int) and start >= total:
                return out

    async def _post(self, path: str) -> None:
        if not self.configured:
            raise PlexError("PLEX_URL and PLEX_TOKEN aren't set")
        try:
            resp = await self._client.post(_checked(path))
        except httpx.HTTPError as e:
            raise PlexError(f"Plex request for {path} failed ({self._quiet(e)})") from e
        if resp.status_code == 401:
            raise PlexError("Plex didn't accept the token in PLEX_TOKEN", 401)
        if resp.status_code >= 400:
            raise PlexError(f"Plex returned HTTP {resp.status_code} for {path}", resp.status_code)

    def _quiet(self, error: Exception | None) -> str:
        """An error, without Plex's address (it's passed on to the page)."""
        return str(error).replace(self.base_url, "Plex") if self.base_url else str(error)

    async def get_bytes(self, path: str, params: dict | None = None) -> tuple[bytes, str]:
        resp = await self._client.get(_checked(path), params=params, headers={"Accept": "image/*"})
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "image/jpeg")

    async def poster(self, rating_key: str, width: int, height: int) -> tuple[bytes, str]:
        """A show's or movie's poster, made small by Plex (or as it is, if
        Plex won't). httpx.HTTPError if there's none."""
        thumb = _checked(f"/library/metadata/{rating_key}/thumb")  # (Plex fetches it)
        try:
            return await self.get_bytes(
                "/photo/:/transcode",
                {"url": thumb, "width": width, "height": height, "minSize": 1, "upscale": 1},
            )
        except httpx.HTTPStatusError:
            return await self.get_bytes(thumb)

    async def clear_logo(self, rating_key: str) -> tuple[str, str] | None:
        """(title, Plex's address for the picture) of a show's or movie's
        logo; None if Plex has none for it (or no such show or movie)."""
        try:
            data = await self._get(f"/library/metadata/{rating_key}")
        except PlexError as e:
            if e.status in (400, 404):
                return None
            raise
        for m in data.get("Metadata") or []:
            for image in m.get("Image") or []:
                if not isinstance(image, dict) or image.get("type") != "clearLogo":
                    continue
                url = image.get("url")
                # (Only ever a picture Plex keeps itself.)
                if isinstance(url, str) and _CLEAR_LOGO.fullmatch(url):
                    return str(m.get("title") or ""), url
        return None

    async def logo_bytes(self, path: str) -> bytes:
        """A logo's picture from Plex (at most MAX_LOGO_BYTES)."""
        data = bytearray()
        try:
            async with self._client.stream(
                "GET", _checked(path), headers={"Accept": "image/*"}
            ) as resp:
                if resp.status_code >= 400:
                    raise PlexError(
                        f"Plex returned HTTP {resp.status_code} for {path}", resp.status_code
                    )
                async for chunk in resp.aiter_bytes():
                    data += chunk
                    if len(data) > MAX_LOGO_BYTES:
                        raise PlexError("That logo is too big to use")
        except httpx.HTTPError as e:
            raise PlexError(f"Plex request for {path} failed ({self._quiet(e)})") from e
        return bytes(data)

    def stream_url(self, part_key: str) -> str:
        """A direct URL to a media file, used when it isn't on local disk."""
        return f"{self.base_url}{part_key}?X-Plex-Token={self.token}"

    # Browsing -----------------------------------------------------------

    async def identity(self) -> dict[str, Any]:
        return await self._get("/identity")

    async def sections(self) -> list[dict[str, Any]]:
        data = await self._get("/library/sections")
        return [
            {
                "key": d["key"],
                "title": d.get("title", ""),
                "type": d.get("type"),
                # The library's folders, as Plex sees them.
                "locations": [
                    loc["path"]
                    for loc in d.get("Location") or []
                    if isinstance(loc.get("path"), str)
                ],
            }
            for d in data.get("Directory", [])
            if d.get("type") in ("show", "movie")
        ]

    async def section_items(self, section_key: str) -> list[dict[str, Any]]:
        """Shows or movies in a library, for the channel editor."""
        out = []
        for m in await self._get_all(f"/library/sections/{section_key}/all"):
            kind = m.get("type")
            if kind not in ("show", "movie"):
                continue
            out.append(
                {
                    "ratingKey": str(m["ratingKey"]),
                    "type": kind,
                    "title": m.get("title", ""),
                    "year": m.get("year"),
                    "episodes": m.get("leafCount"),
                    "durationMs": m.get("duration"),
                    "genres": genres(m),
                    "poster": bool(m.get("thumb")),
                }
            )
        return out

    async def library_fingerprint(self) -> str:
        """Changes whenever anything in any library does (Plex updates these
        timestamps as it adds, removes or re-tags things)."""
        data = await self._get("/library/sections")
        return "|".join(
            f"{d.get('key')}:{d.get('updatedAt')}:{d.get('scannedAt')}:{d.get('contentChangedAt')}"
            for d in sorted(data.get("Directory", []), key=lambda d: str(d.get("key")))
        )

    # Filters --------------------------------------------------------------

    async def filter_fields(self, section_key: str, kind: str) -> list[dict[str, str]]:
        """What Plex can filter a library's movies or shows on, as
        [{"field", "title"}]: genre, content rating, network, studio,
        country... whatever this Plex offers."""
        type_num = TYPE_SHOW if kind == "show" else TYPE_MOVIE
        key = (section_key, "#fields", type_num)
        cached = self._choices.get(key)
        if cached is not None and time.monotonic() - cached[0] < CHOICES_TTL_S:
            return cached[1]
        params = {"includeMeta": 1, "type": type_num}
        params |= {"X-Plex-Container-Start": 0, "X-Plex-Container-Size": 0}
        try:
            data = await self._get(f"/library/sections/{section_key}/all", params, bulk=True)
        except PlexError as e:
            if e.status not in (400, 404):
                raise
            data = {}
        out = []
        for t in (data.get("Meta") or {}).get("Type") or []:
            if t.get("type") != kind:
                continue
            for f in t.get("Filter") or []:
                field = str(f.get("filter") or "")
                if (
                    field.isalpha()
                    and field not in OWN_FIELDS
                    and f.get("filterType") in ("string", "tag")
                ):
                    out.append({"field": field, "title": str(f.get("title") or field)})
        if not out:
            out = [{"field": f, "title": t} for f, t in DEFAULT_FIELDS]
        self._choices[key] = (time.monotonic(), out)
        return out

    async def choices(self, section_key: str, field: str, kind: str) -> list[dict[str, str]]:
        """What a library offers for one kind of tag (its genres, directors,
        content ratings...), as [{"id", "title"}]. Empty if the library
        doesn't have that kind of tag. (Only for what Plex says the library
        can be filtered on, and decades: a field is part of the address
        asked for, and some of Plex's addresses do things, such as scan.)"""
        offered = {f["field"] for f in await self.filter_fields(section_key, kind)}
        if field != "decade" and field not in offered:
            return []
        type_num = TYPE_SHOW if kind == "show" else TYPE_MOVIE
        key = (section_key, field, type_num)
        cached = self._choices.get(key)
        if cached is not None and time.monotonic() - cached[0] < CHOICES_TTL_S:
            return cached[1]
        try:
            data = await self._get(
                f"/library/sections/{section_key}/{field}", {"type": type_num}, bulk=True
            )
        except PlexError as e:
            if e.status not in (400, 404):
                raise  # Plex unreachable or unhappy: try again later; don't remember it
            data = {}  # this library has no such kind of tag
        out = []
        for d in data.get("Directory", []):
            tag_id = _tag_id(d, field)
            if tag_id and d.get("title"):
                out.append({"id": tag_id, "title": str(d["title"])})
        self._choices[key] = (time.monotonic(), out)
        return out

    async def filter_matches(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        """The movies or shows a filter source matches, across its libraries,
        less those it leaves out ("exclude": their rating keys). (For TV,
        "added in the last N days" is about episodes, and is applied when
        the shows are turned into episodes.)"""
        kind = "show" if source.get("kind") == "show" else "movie"
        type_num = TYPE_SHOW if kind == "show" else TYPE_MOVIE
        decades = {int(d) for d in source.get("decade") or []}
        words = str(source.get("titleContains") or "").strip().lower()
        min_rating = float(source.get("minRating") or 0)
        added_since = added_since_s(source) if kind == "movie" else None
        left_out = {str(k) for k in source.get("exclude") or []}
        out: list[dict[str, Any]] = []
        for section_key in source.get("libraries") or []:
            params: dict[str, Any] = {"type": type_num}
            # Values with a comma in them (a studio like "Warner Bros., Inc.")
            # can't go in Plex's comma-separated list: matched here instead.
            here: dict[str, set[str]] = {}
            usable = True
            for field, values in filter_tags(source).items():
                wanted = {str(t).lower() for t in values}
                ids = [
                    c["id"]
                    for c in await self.choices(str(section_key), field, kind)
                    if c["title"].lower() in wanted
                ]
                if not ids:
                    usable = False  # nothing in this library can match
                    break
                if any("," in i for i in ids):
                    here[field] = wanted
                else:
                    params[field] = ",".join(ids)
            if not usable:
                continue
            for m in await self._get_all(f"/library/sections/{section_key}/all", params):
                if m.get("type") != kind:
                    continue
                if any(not _has_tag(m, f, wanted) for f, wanted in here.items()):
                    continue
                year = m.get("year")
                if decades and not (isinstance(year, int) and year // 10 * 10 in decades):
                    continue
                if words and words not in str(m.get("title", "")).lower():
                    continue
                if min_rating and not _number(m.get("audienceRating")) >= min_rating:
                    continue  # no audience rating in Plex counts as too low
                if added_since and not _number(m.get("addedAt")) >= added_since:
                    continue
                if str(m.get("ratingKey")) in left_out:
                    continue  # you left it out
                out.append(m)
        return out

    async def recent_episodes(self, libraries: list[str], since_s: float) -> list[dict[str, Any]]:
        """Episodes added to these TV libraries since `since_s` (a Unix time),
        newest first: read a page at a time, stopping at the first older one."""
        out: list[dict[str, Any]] = []
        for section_key in libraries:
            start = 0
            while True:
                page = {
                    "type": TYPE_EPISODE,
                    "sort": "addedAt:desc",
                    "X-Plex-Container-Start": start,
                    "X-Plex-Container-Size": PAGE_SIZE,
                }
                data = await self._get(f"/library/sections/{section_key}/all", page, bulk=True)
                batch = data.get("Metadata", [])
                recent = [e for e in batch if _number(e.get("addedAt")) >= since_s]
                out.extend(recent)
                start += len(batch)
                if len(recent) < len(batch) or len(batch) < PAGE_SIZE:
                    break
        return out

    async def filter_episodes(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        """The episodes a TV filter stands for."""
        matches = await self.filter_matches(source)
        since = added_since_s(source)
        if since is None:
            shows = await gather_all(
                self._get_all(f"/library/metadata/{m['ratingKey']}/allLeaves") for m in matches
            )
            return [e for episodes in shows for e in episodes]
        wanted = {str(m.get("ratingKey")) for m in matches}
        return [
            e
            for e in await self.recent_episodes(source.get("libraries") or [], since)
            if str(e.get("grandparentRatingKey")) in wanted
        ]

    # Collections -----------------------------------------------------------

    async def collections(self) -> list[dict[str, Any]]:
        """Every collection in the TV and movie libraries, in the order Plex
        lists its libraries, as [{"ratingKey", "title", "library",
        "libraryTitle", "kind" (what it holds: movie, show, season or
        episode), "count", "smart", "updatedAt"}]."""
        sections = await self.sections()
        lists = await gather_all(self._section_collections(s["key"]) for s in sections)
        return [
            {
                "ratingKey": str(c["ratingKey"]),
                "title": str(c.get("title") or ""),
                "library": str(section["key"]),
                "libraryTitle": section["title"],
                "kind": str(c.get("subtype") or section["type"]),
                "count": _count(c.get("childCount")),
                "smart": str(c.get("smart", "0")) in ("1", "True", "true"),
                "updatedAt": _count(c.get("updatedAt")),
            }
            for section, entries in zip(sections, lists, strict=True)
            for c in entries
        ]

    async def _section_collections(self, section_key: str) -> list[dict[str, Any]]:
        """A library's collections, as Plex lists them (asked for the way
        older and newer servers answer)."""
        for path, params in (
            (f"/library/sections/{section_key}/collections", None),
            (f"/library/sections/{section_key}/all", {"type": TYPE_COLLECTION}),
        ):
            try:
                found = await self._get_all(path, params)
            except PlexError as e:
                if e.status not in (400, 404):
                    raise
                continue
            return [c for c in found if c.get("type") == "collection" and c.get("ratingKey")]
        return []  # a library without collections

    def followed_collection(
        self, source: dict[str, Any], collections: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Which of `collections` a station's collection source follows: the
        one with its rating key (or the key Plex gave it when it made the
        collection again), or failing that, the one with its name in its
        library."""
        first = str(source.get("ratingKey") or "")
        key = self._moved_collections.get(first, first)
        for c in collections:
            if str(c["ratingKey"]) == key:
                return c
        title = collection_key(str(source.get("title") or ""))
        library = str(source.get("library") or "")
        for c in collections:
            if c["library"] == library and collection_key(c["title"]) == title:
                return c
        return None

    async def collection_entries(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        """What a collection holds, as movies and episodes: its movies, and
        every episode of its shows and seasons. If Plex has made the
        collection again (tools that manage collections often do, and its
        rating key changes), it's found by its name in its library, and
        that's remembered; if it's gone, it holds nothing."""
        first = str(source.get("ratingKey") or "")
        key = self._moved_collections.get(first, first)
        children = await self._collection_children(key)
        if not children:
            # Empty, or gone: only if Plex no longer lists it is it looked
            # for by name (an empty collection is just empty).
            library = str(source.get("library") or "")
            entries = [
                {
                    "ratingKey": str(c["ratingKey"]),
                    "title": str(c.get("title") or ""),
                    "library": library,
                }
                for c in await self._section_collections(library)
            ]
            if not any(c["ratingKey"] == key for c in entries):
                again = self.followed_collection(source, entries)
                if again is not None:
                    self._moved_collections[first] = again["ratingKey"]
                    children = await self._collection_children(again["ratingKey"])
        out = [c for c in children or () if c.get("type") in ("movie", "episode")]
        groups = [c for c in children or () if c.get("type") in ("show", "season")]
        for episodes in await gather_all(
            self._get_all(f"/library/metadata/{c['ratingKey']}/allLeaves") for c in groups
        ):
            out.extend(episodes)
        return out

    async def _collection_children(self, key: str) -> list[dict[str, Any]] | None:
        """What's in a collection (asked for the way older and newer servers
        answer); None if Plex has no such collection."""
        for what in ("children", "items"):
            try:
                return await self._get_all(f"/library/collections/{key}/{what}")
            except PlexError as e:
                if e.status != 404:
                    raise
        return None

    # Resolving channel sources into playable items ---------------------

    async def _show_or_movie(self, source: dict[str, Any], kind: str) -> list[dict[str, Any]]:
        """A show's episodes, or a movie. If Plex no longer has it under the
        station's rating key but has it under another (it was removed and
        added again, matched afresh, or moved to another folder, drive or
        library), that's followed: found by its title, when exactly one show
        or movie has it, or exactly one in the library it was in (a show can
        be in more than one library: one for teens, say, and one for
        parents), or else the one with the station's own files (see
        _with_files)."""
        first = str(source["ratingKey"])
        title = str(source.get("title") or "").strip()
        tried: set[str] = set()
        while True:
            key = self._moved_titles.get(first, first)
            tried.add(key)
            try:
                if kind == "show":
                    found = await self._get_all(f"/library/metadata/{key}/allLeaves")
                else:
                    data = await self._get(f"/library/metadata/{key}", bulk=True)
                    found = data.get("Metadata", [])
                # (Which library it's in, for if it's ever followed.)
                section = next((m.get("librarySectionID") for m in found), None)
                if section is not None and self.libraries.get(first) != str(section):
                    self.libraries[first] = str(section)
                    if self.remember_libraries is not None:
                        self.remember_libraries(dict(self.libraries))
                return found
            except PlexError as e:
                if e.status != 404:
                    raise
            # (Never one tried already: Plex can say a key it hasn't any more.)
            named = (
                [m for m in await self._by_title(title, kind) if str(m["ratingKey"]) not in tried]
                if title
                else []
            )
            if len(named) > 1 and first in self.libraries:
                named = [m for m in named if m["_section"] == self.libraries[first]] or named
            how = ""
            if len(named) > 1 and self.known_files is not None:
                theirs = self.known_files(first)
                chosen = await self._with_files(named, theirs, kind) if theirs else []
                if len(chosen) == 1:
                    how = f" (of {len(named)} with that title, the one with the station's files)"
                    named = chosen
            if len(named) != 1 or not title:
                found_text = f"{len(named)} {kind}s" if named else f"no other {kind}"
                raise PlexError(
                    f"Plex no longer has the {kind} {title or first!r} under its key, and has "
                    f"{found_text} with that title. Edit the station to choose it again.",
                    404,
                )
            log.info(
                "Plex has the %s %r under a new key now%s; using the new key", kind, title, how
            )
            self._moved_titles[first] = str(named[0]["ratingKey"])

    async def _with_files(
        self, named: list[dict[str, Any]], theirs: set[str], kind: str
    ) -> list[dict[str, Any]]:
        """Of shows or movies with one title, the one whose files (by name)
        are the station's: most of them, and only if no other has as many,
        unless those that do have the very same files (the same show in two
        libraries over one folder), when any of them will do (the first).
        [] if none has any, or those that have them differ."""
        found: list[tuple[int, frozenset[str], dict[str, Any]]] = []
        for m in named:
            key = str(m["ratingKey"])
            try:
                if kind == "show":
                    entries = await self._get_all(f"/library/metadata/{key}/allLeaves")
                else:
                    entries = (await self._get(f"/library/metadata/{key}")).get("Metadata", [])
            except PlexError as e:
                if e.status == 404:
                    continue
                raise
            files = frozenset(
                _file_name(str(part.get("file") or "")).casefold()
                for entry in entries
                for media in entry.get("Media") or []
                for part in media.get("Part") or []
                if part.get("file")
            )
            found.append((len(files & theirs), files, m))
        best = max((n for n, _, _ in found), default=0)
        if not best:
            return []
        top = [(files, m) for n, files, m in found if n == best]
        if len({files for files, _ in top}) != 1:
            return []  # (they differ: not for StationPlay to choose)
        return [min((m for _, m in top), key=lambda m: (int(m["_section"]), str(m["ratingKey"])))]

    async def _by_title(
        self, title: str, kind: str, looked: Lookups | None = None
    ) -> list[dict[str, Any]]:
        """The shows or movies (`kind`) with this title, across the
        libraries of that kind (kept in `looked`, if given)."""
        type_num = TYPE_SHOW if kind == "show" else TYPE_MOVIE
        wanted = title.casefold()
        if looked is not None and (kind, wanted) in looked.titles:
            return looked.titles[(kind, wanted)]
        found: list[dict[str, Any]] = []
        for section in await self.sections():
            if section["type"] != kind or not str(section["key"]).isdigit():
                continue
            data = await self._get(
                f"/library/sections/{section['key']}/all",
                {"type": type_num, "title": title, "includeGuids": 1},
            )
            found += [
                {**m, "_section": str(section["key"])}
                for m in data.get("Metadata", [])
                if str(m.get("title", "")).casefold() == wanted and m.get("ratingKey")
            ]
        if looked is not None:
            looked.titles[(kind, wanted)] = found
        return found

    async def find_again(self, item: Item, looked: Lookups | None = None) -> str | None:
        """For a program Plex no longer has under its key: the key it has
        the same program under now, if it was added again (a file renamed,
        replaced, or moved to another folder, drive or library) or matched
        afresh; None if it has no such program (it was removed).

        An episode is looked for in its own show first (followed to a new
        key too, as a station does), by Plex's season and episode for it;
        then in any other show of the same title, in any library, in the
        same place but only with proof it's the same program: the same file
        name (its capital letters aside), a show matched to the same TVDB
        show as its own, or the same episode title (one that tells episodes
        apart: not "Episode 5" or "Pilot") from the same year. (A file
        replaced by a better one, under another name, in a show its own has
        gone from, still has its title.) One Plex gives no season and
        episode (a show by air date, say) is found anywhere only with proof
        of the first or last kind. File names are never read for any of
        it: the season, episode and title are Plex's.
        A movie
        is the one with the same title and year. `looked`, if given, keeps
        what Plex said for the next time (going through a list). Raises
        PlexError if Plex can't say."""
        if item.kind != "episode":
            if item.year is None or not item.title:
                return None
            again = [
                str(m["ratingKey"])
                for m in await self._by_title(item.title, "movie", looked)
                if m.get("year") == item.year and str(m["ratingKey"]) != item.rating_key
            ]
            return again[0] if again else None
        name = _file_name(item.file_path)
        title = item.title.strip().casefold() if telling_title(item.title, item.show_title) else ""
        # Plex's season and episode for it (a show by air date may have
        # none: then only proof says which episode it is).
        numbered = item.season is not None and item.episode is not None

        def same_slot(episode: Item) -> bool:
            return (
                episode.rating_key != item.rating_key
                and episode.season == item.season
                and episode.episode == item.episode
            )

        def proof(episode: Item, same_show: bool) -> int | None:
            """How it's proven the same program (best first), if it is."""
            if episode.rating_key == item.rating_key:
                return None
            if name and _file_name(episode.file_path) == name:
                return 0
            if same_show and numbered and same_slot(episode):
                return 1
            if (
                title
                and episode.title.strip().casefold() == title
                and (not numbered or same_slot(episode))
                and (item.year is None or episode.year is None or item.year == episode.year)
            ):
                return 2
            return None

        def best(found: list[tuple[int, str]]) -> str | None:
            return min(found)[1] if found else None

        if item.show_key:
            own = await self._episodes_of(item.show_key, item.show_title, looked)
            if numbered:
                # (Its own show's episode in its place is it.)
                slot = [e.rating_key for e in own if same_slot(e)]
                if slot:
                    return slot[0]
            else:
                proven = best([(p, e.rating_key) for e in own if (p := proof(e, True)) is not None])
                if proven:
                    return proven
        if not item.show_title:
            return None
        # Another show of its title (a library with the same show in it,
        # or the files moved to another folder Plex sees as another show).
        named = await self._by_title(item.show_title, "show", looked)
        own_tvdb = next(
            (guid_ids(m).get("tvdb") for m in named if str(m["ratingKey"]) == item.show_key),
            None,
        )
        found: list[tuple[int, str]] = []
        for show in sorted(named, key=lambda m: str(m["ratingKey"])):
            key = str(show["ratingKey"])
            if key == item.show_key:
                continue
            same_show = own_tvdb is not None and guid_ids(show).get("tvdb") == own_tvdb
            for episode in await self._episodes_of(key, None, looked):
                p = proof(episode, same_show)
                if p is not None and (not numbered or same_slot(episode)):
                    found.append((p, episode.rating_key))
        return best(found)

    async def _episodes_of(
        self, show_key: str, title: str | None, looked: Lookups | None
    ) -> list[Item]:
        """A show's episodes as Plex has them now ([] if it's gone, or
        several have its title), kept in `looked` if given."""
        episodes = looked.episodes.get(show_key) if looked is not None else None
        if episodes is None:
            try:
                found = await self._show_or_movie(
                    {"ratingKey": show_key, "title": title or ""}, "show"
                )
            except PlexError as e:
                if e.status != 404:
                    raise
                found = []  # the show's gone too (or Plex has several by its name)
            episodes = [i for i in (to_item(m) for m in found) if i]
            if looked is not None:
                looked.episodes[show_key] = episodes
        return episodes

    async def items_for_source(self, source: dict[str, Any]) -> list[Item]:
        """Expands a channel source into episodes or movies.

        Sources are {"type": "show"|"movie"|"section", "ratingKey"/"key": ...},
        filters, and collections: {"type": "collection", "ratingKey", "title",
        "library", "kind"}.
        """
        kind = source.get("type")
        if kind in ("show", "movie"):
            entries = await self._show_or_movie(source, kind)
        elif kind == "section":
            section_type = TYPE_EPISODE if source.get("sectionType") == "show" else TYPE_MOVIE
            entries = await self._get_all(
                f"/library/sections/{source['key']}/all",
                params={"type": section_type},
            )
        elif kind == "filter":
            if source.get("kind") == "show":
                entries = await self.filter_episodes(source)
            else:
                entries = await self.filter_matches(source)
        elif kind == "collection":
            entries = await self.collection_entries(source)
        else:
            raise PlexError(f"Unknown source type {kind!r}")
        for m in entries:
            found = resolution(m)
            if found and m.get("ratingKey"):
                self.resolutions[str(m["ratingKey"])] = found
        return [i for i in (to_item(m) for m in entries) if i]

    # Live TV ------------------------------------------------------------

    async def dvrs(self) -> list[dict[str, Any]]:
        """Plex's Live TV & DVR setups."""
        data = await self._get("/livetv/dvrs")
        # "Dvr", as Plex names them; some descriptions of its API say "DVR".
        return list(data.get("Dvr") or data.get("DVR") or [])

    async def reload_guide(self, dvr_key: str) -> None:
        """Presses Plex's "Refresh Guide" for one DVR."""
        await self._post(f"/livetv/dvrs/{dvr_key}/reloadGuide")

    async def markers(self, rating_key: str) -> list[dict[str, Any]]:
        """Plex's markers (intro, credits...) for one program, as Plex gives
        them. Plex leaves markers out of whole-library and whole-show lists
        even when asked, so this asks about one program at a time."""
        return (await self.markers_and_added(rating_key))[0]

    async def markers_and_added(self, rating_key: str) -> tuple[list[dict[str, Any]], int | None]:
        """A program's markers, and when it was added to Plex (Unix time;
        Plex finds a new program's markers a while after it's added)."""
        try:
            async with self._marker_slots:
                data = await self._request(f"/library/metadata/{rating_key}", {"includeMarkers": 1})
        except PlexError as e:
            if e.status in (400, 404):
                return [], None  # gone from Plex since it was listed
            raise
        metadata = data.get("Metadata") or []
        if not metadata:
            return [], None
        added = metadata[0].get("addedAt")
        return list(metadata[0].get("Marker") or []), added if isinstance(added, int) else None

    async def ids(self, rating_key: str) -> dict[str, str]:
        """What a show or movie is known as elsewhere, as Plex matched it
        ("tvdb", "tmdb", "imdb"), and its library ("section"). Raises
        PlexError (404 if Plex has no such thing)."""
        data = await self._get(f"/library/metadata/{rating_key}", {"includeGuids": 1})
        metadata = data.get("Metadata") or [{}]
        return guid_ids(metadata[0])

    async def scan_folder(self, section: str, folder: str) -> None:
        """Asks Plex to look in one folder of a library for what's new there
        (as Sonarr and Radarr's own Plex connections do). Raises PlexError."""
        await self._get_once(f"/library/sections/{section}/refresh", {"path": folder})

    async def sessions(self) -> list[dict[str, Any]]:
        """What Plex is playing now, and to whom: its sessions (each with
        "User", "Session" and, for Live TV, "live"). Raises PlexError."""
        data = await self._get("/status/sessions")
        return [m for m in data.get("Metadata") or [] if isinstance(m, dict)]

    async def accounts(self) -> list[dict[str, str]]:
        """The Plex users this server knows (you, Plex Home members and
        friends it's shared with), as {"id", "name"}: the ids its sessions'
        "User" has. Raises PlexError."""
        data = await self._get("/accounts")
        out = []
        for a in data.get("Account") or []:
            if not isinstance(a, dict):
                continue
            uid, name = str(a.get("id", "")).strip(), str(a.get("name") or "").strip()
            # (Account 0 is Plex's own, with no name.)
            if uid.isdigit() and uid != "0" and name:
                out.append({"id": uid, "name": name})
        return out

    async def plex_pass(self) -> bool | None:
        """Whether Plex says the server's owner has Plex Pass; None if it
        doesn't say. Raises PlexError."""
        given = (await self._get("/")).get("myPlexSubscription")
        if given is None:
            return None
        return str(given).lower() in ("1", "true")

    async def stop_session(self, session_id: str, reason: str) -> None:
        """Stops a session's playback, with the reason shown to whoever was
        watching (Plex's "stop playback": it needs Plex Pass). Asked once,
        never again by itself. Raises PlexError."""
        await self._get_once(
            "/status/sessions/terminate", {"sessionId": session_id, "reason": reason}
        )

    async def _get_once(self, path: str, params: dict) -> None:
        """A request that's made once (not again if it seems to fail)."""
        if not self.configured:
            raise PlexError("PLEX_URL and PLEX_TOKEN aren't set")
        try:
            resp = await self._client.get(_checked(path), params=params)
        except httpx.HTTPError as e:
            raise PlexError(f"Plex request for {path} failed ({self._quiet(e)})") from e
        if resp.status_code == 401:
            raise PlexError("Plex didn't accept the token in PLEX_TOKEN", 401)
        if resp.status_code >= 400:
            raise PlexError(f"Plex returned HTTP {resp.status_code} for {path}", resp.status_code)

    async def newest_files(self, most: int = 3) -> list[str]:
        """The newest file in each library of shows or movies (up to
        `most`), where Plex has it: for checking StationPlay can read them."""
        out: list[str] = []
        for section in await self.sections():
            data = await self._get(
                f"/library/sections/{section['key']}/all",
                {
                    "type": TYPE_EPISODE if section["type"] == "show" else TYPE_MOVIE,
                    "sort": "addedAt:desc",
                    "X-Plex-Container-Start": 0,
                    "X-Plex-Container-Size": 1,
                },
            )
            for m in data.get("Metadata") or []:
                part = first_part(m)
                if part and part.file:
                    out.append(part.file)
            if len(out) >= most:
                break
        return out

    async def current_part(self, rating_key: str) -> MediaPart | None:
        """The file Plex currently has for an item.

        Asked at play time so a file Sonarr/Radarr upgraded or renamed is
        found without rebuilding the channel.
        """
        data = await self._get(f"/library/metadata/{rating_key}")
        metadata = data.get("Metadata", [])
        if not metadata:
            return None
        return first_part(metadata[0])

    # For StationPlay's apps (see docs/on-demand.md) -------------------------

    async def browse(
        self, section: str, kind: str, sort: str, start: int, size: int
    ) -> tuple[int, list[Entry]]:
        """A page of a library's shows or movies: (how many in all, the page)."""
        data = await self._get(
            f"/library/sections/{section}/all",
            {
                "type": TYPE_SHOW if kind == catalog.SHOW else TYPE_MOVIE,
                "sort": _SORTS[sort],
                "X-Plex-Container-Start": start,
                "X-Plex-Container-Size": size,
            },
        )
        page = [e for m in data.get("Metadata") or [] if (e := to_entry(m, section))]
        total = data.get("totalSize")
        return (total if isinstance(total, int) else start + len(page)), page

    async def recently_added(self, section: str, kind: str, count: int) -> list[Entry]:
        """A library's newest movies, or the shows with the newest episodes."""
        if kind == catalog.MOVIE:
            return (await self.browse(section, kind, "added", 0, count))[1]
        data = await self._get(
            f"/library/sections/{section}/all",
            {
                "type": TYPE_EPISODE,
                "sort": "addedAt:desc",
                "X-Plex-Container-Start": 0,
                "X-Plex-Container-Size": count * 4,
            },
        )
        shows: list[str] = []
        for m in data.get("Metadata") or []:
            show = str(m.get("grandparentRatingKey") or "")
            if show.isdigit() and show not in shows:
                shows.append(show)
        return [e for e in await self.entries(shows[:count]) if e.kind == catalog.SHOW]

    async def search(self, section: str, kind: str, words: str, count: int) -> list[Entry]:
        """A library's shows or movies whose titles contain `words`."""
        data = await self._get(
            f"/library/sections/{section}/all",
            {
                "type": TYPE_SHOW if kind == catalog.SHOW else TYPE_MOVIE,
                "title": words,
                "sort": "titleSort",
                "X-Plex-Container-Start": 0,
                "X-Plex-Container-Size": count,
            },
        )
        return [e for m in data.get("Metadata") or [] if (e := to_entry(m, section))]

    async def entry(self, key: str, details: bool = False) -> Entry | None:
        """A show, movie or episode (None if Plex has no such thing). With
        `details`, its intro and credits and what its files hold too."""
        try:
            data = await self._get(
                f"/library/metadata/{key}", {"includeMarkers": 1} if details else None
            )
        except PlexError as e:
            if e.status in (400, 404):
                return None
            raise
        section = str(data.get("librarySectionID") or "")
        found = [
            x for m in data.get("Metadata") or [] if (x := to_entry(m, section, details=details))
        ]
        return found[0] if found else None

    async def entries(self, keys: list[str]) -> list[Entry]:
        """Several shows, movies or episodes at once, in the order asked
        (those Plex no longer has are left out)."""
        wanted = list(dict.fromkeys(k for k in keys if k.isascii() and k.isdigit()))
        found: dict[str, Entry] = {}
        for at in range(0, len(wanted), ENTRIES_AT_ONCE):
            batch = wanted[at : at + ENTRIES_AT_ONCE]
            try:
                data = await self._get(f"/library/metadata/{','.join(batch)}")
            except PlexError as e:
                if e.status not in (400, 404):
                    raise
                if len(batch) == 1:
                    continue
                # (One of them gone may be why: each on its own, then.)
                for key in batch:
                    if (x := await self.entry(key)) is not None:
                        found[x.key] = x
                continue
            # (Each says which library it's in; the answer as a whole only
            # when it's about one.)
            section = str(data.get("librarySectionID") or "") if len(batch) == 1 else ""
            for m in data.get("Metadata") or []:
                if (x := to_entry(m, section)) is not None:
                    found[x.key] = x
        return [found[k] for k in wanted if k in found]

    async def show_episodes(self, show_key: str) -> list[Entry]:
        """A show's episodes, in order (specials last). None of Plex's: []."""
        try:
            data = await self._get(f"/library/metadata/{show_key}/allLeaves", bulk=True)
        except PlexError as e:
            if e.status in (400, 404):
                return []
            raise
        section = str(data.get("librarySectionID") or "")
        found = [
            x
            for m in data.get("Metadata") or []
            if (x := to_entry(m, section)) and x.kind == catalog.EPISODE
        ]
        return sorted(found, key=episode_order)

    async def picture(self, key: str, which: str, width: int, height: int) -> tuple[bytes, str]:
        """A show's, movie's or episode's picture (`which`: "thumb", its
        poster or still, or "art", its backdrop), made the size asked for by
        Plex (or as it is, if Plex won't). httpx.HTTPError if there's none."""
        path = _checked(f"/library/metadata/{key}/{which}")
        try:
            return await self.get_bytes(
                "/photo/:/transcode",
                {"url": path, "width": width, "height": height, "minSize": 1, "upscale": 1},
            )
        except httpx.HTTPStatusError:
            return await self.get_bytes(path)


# For StationPlay's apps: how a library's shows and movies can be sorted.
_SORTS = {"title": "titleSort", "added": "addedAt:desc", "released": "originallyAvailableAt:desc"}
# Shows, movies and episodes asked for in one request, at most.
ENTRIES_AT_ONCE = 50


def episode_order(e: Entry) -> tuple[bool, int, int, str]:
    """Seasons in order with specials (season 0) last, then episodes."""
    season = e.season if e.season is not None else 10_000
    return (season == 0, season, e.episode if e.episode is not None else 10_000, e.title)


def to_entry(m: dict[str, Any], section: str = "", details: bool = False) -> Entry | None:
    """Plex's description of a show, movie or episode, as the apps are told
    it (see catalog.py); None for anything else. `details`: Plex was asked
    about it alone, so its markers and streams are there."""
    kind = m.get("type")
    key = str(m.get("ratingKey") or "")
    if kind not in (catalog.SHOW, catalog.MOVIE, catalog.EPISODE) or not key.isdigit():
        return None
    episode = kind == catalog.EPISODE
    duration = _int(m.get("duration"))
    added = _int(m.get("addedAt"))
    library = str(m.get("librarySectionID") or section or "")
    show_key = str(m.get("grandparentRatingKey") or "") if episode else ""
    media = tuple(to_media(m)) if details and kind != catalog.SHOW else ()
    intro = credits = None
    if details and episode:  # (movies have no Skip buttons)
        intro, credits = _skips(duration, m.get("Marker"), [x.duration_ms for x in media])
    return Entry(
        key=key,
        kind=kind,
        title=str(m.get("title") or ""),
        year=_int(m.get("year")),
        summary=str(m.get("summary") or ""),
        library=library if library.isdigit() else "",
        show_key=show_key if show_key.isdigit() else None,
        show_title=str(m.get("grandparentTitle") or "") if episode else "",
        season=_int(m.get("parentIndex")) if episode else None,
        episode=_int(m.get("index")) if episode else None,
        duration_ms=duration,
        added_ms=added * 1000 if added is not None else None,
        released=str(m.get("originallyAvailableAt") or "")[:10],
        episodes=_int(m.get("leafCount")) if kind == catalog.SHOW else None,
        seasons=_int(m.get("childCount")) if kind == catalog.SHOW else None,
        genres=tuple(genres(m)),
        content_rating=str(m.get("contentRating") or ""),
        studio=str(m.get("studio") or ""),
        has_thumb=bool(m.get("thumb")),
        has_art=bool(m.get("art")),
        intro=intro,
        credits=credits,
        media=media,
    )


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# Skip intro and Skip credits (episodes only; see _skips).
# A marker ending more than this past the end of an episode's file was found
# in another file (one since replaced).
MARKER_SLACK_MS = 2_000
# Versions of an episode more than this apart in length may not line up with
# its markers (Plex finds them in one file).
VERSIONS_SLACK_MS = 1_000


def _skips(
    duration: int | None, raw: Any, lengths: list[int | None] | None = None
) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """An episode's intro and closing credits, from Plex's markers, for the
    apps' Skip intro and Skip credits buttons. A button in the wrong place is
    worse than none, so markers are used only where they fit the episode's
    file, by the rules stations use (see markers.py) and these:
      * a marker ending past the end of the file, or ending before it
        starts, means Plex's markers don't fit this file (it was found in
        another, since replaced): none are used;
      * nor when the episode has versions of different lengths (Plex finds
        markers in one of them, and the others may not line up);
      * the intro must end before the credits start (otherwise neither is
        used), and at least a minute before the episode ends;
      * a scrap of under five seconds before the intro, or after the
        credits, goes with it: Skip intro shows from the very start, and
        Skip credits goes on to what's next rather than a second of black.
    """
    from . import markers  # (markers.py uses this module)

    if not duration or not isinstance(raw, list):
        return None, None
    if any(n is not None and abs(n - duration) > VERSIONS_SLACK_MS for n in lengths or []):
        return None, None
    found = markers.parse_markers(raw)
    if any(m.end_ms > duration + MARKER_SLACK_MS or m.end_ms < m.start_ms for m in found):
        return None, None
    intros, closing = [], []
    for m in found:
        start, end = max(0, m.start_ms), min(duration, m.end_ms)
        if end - start < markers.MIN_MARKER_MS:
            continue
        if m.kind == markers.INTRO and start < duration / 2:
            if end - start <= markers.MAX_INTRO_MS:
                intros.append((start, end))
        elif m.kind == markers.CREDITS and start >= duration / 2:
            closing.append((m.final, start, duration if m.final else end))
    # The first intro; the credits Plex says are final, or else the last.
    intro = min(intros, default=None)
    last = max(closing, default=None)
    credits = (last[1], last[2]) if last else None
    if intro and credits and intro[1] > credits[0]:
        return None, None
    if intro and intro[1] > duration - markers.MIN_PROGRAM_MS:
        intro = None
    if intro and intro[0] < markers.MIN_KEEP_MS:
        intro = (0, intro[1])
    if credits and duration - credits[1] < markers.MIN_KEEP_MS:
        credits = (credits[0], duration)
    return intro, credits


def to_media(m: dict[str, Any]) -> list[Media]:
    """The versions of a program's file, as Plex describes them."""
    out = []
    for media in m.get("Media") or []:
        if not isinstance(media, dict):
            continue
        parts = [p for p in media.get("Part") or [] if isinstance(p, dict)]
        part = parts[0] if parts else {}
        streams = [s for s in part.get("Stream") or [] if isinstance(s, dict)]
        video = next((s for s in streams if s.get("streamType") == 1), {})
        trc = str(video.get("colorTrc") or "").lower()
        hdr = catalog.HDR10 if trc == "smpte2084" else catalog.HLG if trc == "arib-std-b67" else ""
        dv = (_int(video.get("DOVIProfile")) or 0) if video.get("DOVIPresent") else None
        out.append(
            Media(
                container=catalog.container(part.get("container") or media.get("container")),
                video=catalog.video_codec(video.get("codec") or media.get("videoCodec")),
                width=_int(video.get("width")) or _int(media.get("width")) or 0,
                height=_int(video.get("height")) or _int(media.get("height")) or 0,
                bit_depth=_int(video.get("bitDepth")) or 8,
                hdr=hdr,
                dv_profile=dv,
                bitrate_kbps=_int(media.get("bitrate")),
                parts=max(1, len(parts)),
                file=part.get("file") if isinstance(part.get("file"), str) else None,
                part_key=part.get("key") if isinstance(part.get("key"), str) else None,
                size=_int(part.get("size")),
                duration_ms=_int(part.get("duration")) or _int(media.get("duration")),
                id=str(media.get("id") or ""),
                audio=tuple(
                    _track(s, catalog.audio_codec) for s in streams if s.get("streamType") == 2
                ),
                subtitles=tuple(
                    _track(s, catalog.subtitle_codec) for s in streams if s.get("streamType") == 3
                ),
            )
        )
    return out


def _track(s: dict[str, Any], codec: Callable[[str | None], str]) -> Track:
    return Track(
        id=str(s.get("id") or ""),
        codec=codec(s.get("codec")),
        language=str(s.get("language") or ""),
        title=str(s.get("title") or ""),
        channels=_int(s.get("channels")),
        default=bool(s.get("default")),
        forced=bool(s.get("forced")),
        external=bool(s.get("key")) and s.get("index") is None,
        index=_int(s.get("index")),
    )


# Plex's names for what a show or movie was matched to: its own ("tvdb://"),
# and older agents' ("com.plexapp.agents.thetvdb://81189?lang=en", and
# HAMA's "com.plexapp.agents.hama://tvdb-81189").
_GUID = re.compile(r"(tvdb|tmdb|imdb)://([A-Za-z0-9]+)")
_OLD_GUID = re.compile(
    r"com\.plexapp\.agents\.(thetvdb|themoviedb|imdb|hama)://(?:(tvdb|tmdb)-)?([A-Za-z0-9]+)"
)
_OLD_NAMES = {"thetvdb": "tvdb", "themoviedb": "tmdb", "imdb": "imdb"}


def guid_ids(metadata: dict[str, Any]) -> dict[str, str]:
    """A show's or movie's ids elsewhere (see PlexClient.ids)."""
    out: dict[str, str] = {}
    for g in metadata.get("Guid") or []:
        found = _GUID.fullmatch(str(g.get("id", "")))
        if found:
            out.setdefault(found.group(1), found.group(2))
    old = _OLD_GUID.match(str(metadata.get("guid", "")))
    if old:
        agent, prefix, value = old.groups()
        name = prefix if agent == "hama" else _OLD_NAMES.get(agent)
        if name:
            out.setdefault(name, value)
    section = metadata.get("librarySectionID")
    if section is not None and str(section).isdigit():
        out["section"] = str(section)
    return out


# Episode titles that don't tell one show's episodes from another's: none,
# a number, or "Episode 5", "Pilot", "Part 2" and the like.
_UNTELLING = re.compile(r"(?:episode|ep|chapter|part|pilot|show|tba|tbd)?[\s.#:-]*\d*", re.I)


def telling_title(title: str | None, show: str | None = None) -> bool:
    """Whether an episode's title tells it apart (see find_again)."""
    t = (title or "").strip()
    return bool(t) and not _UNTELLING.fullmatch(t) and t.casefold() != (show or "").casefold()


def _file_name(path: str | None) -> str:
    """A file's name, its capital letters aside ("" for none)."""
    return (path or "").replace("\\", "/").rsplit("/", 1)[-1].casefold()


def filter_tags(source: dict[str, Any]) -> dict[str, list[str]]:
    """A filter's tag conditions, {field: [titles]}: those under "tags",
    and those a filter saved before 1.6 kept at the top level."""
    out: dict[str, list[str]] = {}
    for field in TAG_FIELDS:
        if source.get(field):
            out[field] = list(source[field])
    for field, values in (source.get("tags") or {}).items():
        if values:
            out[field] = list(values)
    return out


def added_since_s(source: dict[str, Any]) -> float | None:
    """The Unix time "added in the last N days" starts from, if it's set."""
    days = int(source.get("addedWithinDays") or 0)
    return time.time() - days * 86400 if days > 0 else None


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def collection_key(title: str) -> str:
    """How collections are matched by name: ignoring case and spacing."""
    return " ".join(title.split()).lower()


def _count(value: Any) -> int:
    n = _number(value)
    return int(n) if 0 <= n < 10**9 else 0


def genres(m: dict[str, Any]) -> list[str]:
    """A movie's or show's genres, as Plex lists them (its first few)."""
    return [str(t["tag"]) for t in m.get("Genre") or [] if isinstance(t, dict) and t.get("tag")][:3]


def _has_tag(m: dict[str, Any], field: str, wanted: set[str]) -> bool:
    """Whether a movie or show has one of `wanted` (lowercase) as `field`:
    a plain value (studio, contentRating) or a list of tags (Genre...)."""
    value = m.get(field)
    if isinstance(value, str):
        return value.lower() in wanted
    tags = m.get(field[:1].upper() + field[1:]) or []
    return any(isinstance(t, dict) and str(t.get("tag", "")).lower() in wanted for t in tags)


def _tag_id(entry: dict[str, Any], field: str) -> str | None:
    """The id Plex filters a tag by: the entry's key, or failing that the
    value in its fastKey (".../all?genre=87")."""
    key = str(entry.get("key", ""))
    if key.isdigit():
        return key
    fast = entry.get("fastKey") or key
    values = parse_qs(urlparse(str(fast)).query).get(field)
    return values[0] if values else None


def resolution(m: dict[str, Any]) -> str | None:
    """A program's picture size as Plex lists it ("4K", "1080p", "720p" or
    "SD"), from its first file; None if Plex doesn't say (or says something
    else)."""
    for media in m.get("Media") or []:
        said = str(media.get("videoResolution") or "").strip().lower()
        if said in ("4k", "8k"):
            return "4K"
        if said == "sd":
            return "SD"
        if said.isdigit():  # the picture's height: 1080, 720, 576, 480...
            lines = int(said)
            return (
                "4K"
                if lines >= 2000
                else "1080p"
                if lines >= 1000
                else "720p"
                if lines >= 700
                else "SD"
            )
        return None
    return None


def first_part(m: dict[str, Any]) -> MediaPart | None:
    for media in m.get("Media", []) or []:
        for part in media.get("Part", []) or []:
            return MediaPart(
                file=part.get("file"),
                key=part.get("key"),
                size=part.get("size"),
                duration_ms=part.get("duration") or media.get("duration"),
            )
    return None


def to_item(m: dict[str, Any]) -> Item | None:
    """Converts Plex metadata into a playlist item, or None if unusable."""
    kind = m.get("type")
    if kind not in ("episode", "movie"):
        return None
    part = first_part(m)
    duration = m.get("duration") or (part.duration_ms if part else None)
    if not duration or duration < 1000:
        return None
    season = m.get("parentIndex")
    # Specials (season 0) are rarely what anyone wants on a channel.
    if kind == "episode" and season == 0:
        return None
    return Item(
        position=0,
        start_ms=0,
        duration_ms=int(duration),
        rating_key=str(m["ratingKey"]),
        kind=kind,
        title=m.get("title", ""),
        show_title=m.get("grandparentTitle") if kind == "episode" else None,
        show_key=str(m["grandparentRatingKey"])
        if kind == "episode" and m.get("grandparentRatingKey")
        else None,
        season=season if kind == "episode" else None,
        episode=m.get("index") if kind == "episode" else None,
        year=m.get("year"),
        summary=m.get("summary"),
        file_path=part.file if part else None,
        part_key=part.key if part else None,
        rating=str(m.get("contentRating") or "") or None,
        library=str(m.get("librarySectionID") or "") or None,
    )
