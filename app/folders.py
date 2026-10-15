"""Folder libraries: shows and movies from folders of your own, with or
without Plex (1.35.0; see docs/library.md, Phase 3). An Admin adds one on
the Setup tab, under Your own folders: a name, Shows or Movies, and
one or more folders in the media folder. It's shared for Media and used
for stations exactly as a Plex library is: the library layer (library.py)
sends each call about a folder key here.

Keys: libraries are "f1", "f2"...; shows, episodes, movies and collections
"f" followed by digits too (their ids, from 1: "f0" is the INFO station's),
never used twice, and kept across rescans: a file moved or renamed keeps
its key when it's recognizably the same (the same size and the same show,
season and episode, or the same movie).

Scanning walks the folders at the lowest priority, never while anyone is
watching: soon after tapiOca starts, every 6 hours, when an Admin asks, and
when Sonarr or Radarr brings a replacement tapiOca asked for (scan_folder).
Only what's new or
changed (by size and time) is read again. A folder that's gone (an
unmounted share) never empties a library: its programs are kept, and said
to be missing until it's back.

Each detail comes from the first layer that has it: the NFO files beside
the videos, the tags inside the files, then the folders' and files' names
(folderscan.py says how they're read). The online sources, matching and
Needs a match come later. A title tapiOca can't be sure of is listed by
what its names say.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import itertools
import json
import logging
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import access, catalog, folderart, folderscan, languages, naming, nfo, setup
from .catalog import Entry, Media, Track
from .db import Item
from .library import FOLDER_PREFIX, LibraryError, NoPicture, is_folder_key
from .plex import collection_key, episode_order, filter_tags

if TYPE_CHECKING:
    from .config import Settings
    from .db import Database
    from .main import AppContext

log = logging.getLogger(__name__)

SHOW, EPISODE, MOVIE, COLLECTION = "show", "episode", "movie", "collection"
SCAN_EVERY_S = 6 * 3600
STARTUP_DELAY_S = 30.0
WATCHING_WAIT_S = 10.0  # while anyone's watching, scanning looks again this often
DISK_WAIT_S = 10.0  # a picture or a folder's list, waited for at most
LOOK_EVERY_S = 300.0  # how often what's due is looked for
PROBES_AT_ONCE = 2
# Scanning a big library never holds everything else up (playing, the page,
# the apps): it works through this many titles, files or rows at a time, and
# lets everything else have its turn between (1.35.0's check: 50,000
# episodes).
SLICE = 500
FOLDERS_MOST = 20  # one library's folders, at most
NAME_MAX = 60
LIBRARIES_MOST = 50
FORGET_UNSEEN_S = 30 * 86_400  # what was read from a file no longer seen is kept this long
# What tapiOca's apps are told of a show's or movie's people, at most.
CAST_MOST = 20
CREW_MOST = 5
NOT_FOUND = "There’s no such Media folder"
CANT_READ = "It couldn’t be read. The Logs tab says why."
NO_SUCH = "There’s no such show, episode or movie in the Media folders tapiOca reads itself"


class NotFolder(ValueError):
    """Why a folder can't be one of a library's."""


@dataclass
class FolderLibrary:
    id: int
    name: str
    kind: str  # "show" or "movie"
    folders: list[str]
    created_ms: int
    scanned_ms: int = 0
    changed_ms: int = 0
    missing: list[str] = field(default_factory=list)
    problem: str = ""  # (the last scan's, for the page: not saved)
    tried_ms: int = 0  # (when a scan last failed: the next waits its turn)

    @property
    def key(self) -> str:
        return f"{FOLDER_PREFIX}{self.id}"


@dataclass
class Thing:
    """A show, an episode, a movie or a collection in a folder library."""

    id: int
    library: int
    kind: str
    path: str
    root: str = ""
    show: int | None = None  # an episode's show (its id)
    files: list[list[str]] = field(default_factory=list)  # versions, each its parts
    slot: list = field(default_factory=list)  # (an episode's place: see folderscan)
    local: dict[str, list] = field(default_factory=dict)  # layers 1 to 3
    art: dict[str, str] = field(default_factory=dict)
    needs: list[str] = field(default_factory=list)  # (what the layers disagree on: kept for later)
    added_ms: int = 0
    missing: bool = False
    details: dict[str, list] = field(default_factory=dict)  # (worked out: see merged)

    @property
    def key(self) -> str:
        return f"{FOLDER_PREFIX}{self.id}"

    def get(self, name: str, otherwise: Any = None) -> Any:
        got = self.details.get(name)
        return got[0] if got else otherwise

    def row(self) -> tuple:
        return (
            self.id, self.library, self.kind, self.show, self.path, self.root,
            json.dumps(self.files), json.dumps(self.slot), json.dumps(self.local, sort_keys=True),
            json.dumps(self.art, sort_keys=True), json.dumps(self.needs),
            self.added_ms, int(self.missing),
        )  # fmt: skip


_ROW = "id,library,kind,show_id,path,root,files,slot,local,art,needs,added_ms,missing"


def _fields(t: Thing) -> tuple:
    """What's saved of a thing (its row), to tell whether it changed."""
    return (
        t.library, t.kind, t.show, t.path, t.root, t.files, list(t.slot), t.local, t.art,
        t.needs, t.added_ms, t.missing,
    )  # fmt: skip


def merged(thing: Thing) -> dict[str, list]:
    """A thing's details, each from the first layer that has it (as the
    scan put them together: see folderscan.Layers). {field: [value, layer,
    where]}."""
    return dict(thing.local)


class FolderSource:
    """Every folder library, answering for the library layer (library.py)
    about folder keys, and scanning them."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.libraries: dict[int, FolderLibrary] = {}
        self.things: dict[int, Thing] = {}
        self._by_path: dict[tuple[int, str, str], Thing] = {}
        self._episodes: dict[int, list[Thing]] = {}  # each show's (its id)
        self._members_of: dict[tuple[int, str], list[Thing]] = {}  # (library, collection)
        self._collections: dict[int, list[Thing]] = {}  # each library's
        self._resolutions: dict[str, str | None] = {}  # (see resolution)
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._asked: set[int] = set()
        self._tasks: set[asyncio.Task] = set()
        self._waiting: set[int] = set()  # libraries with a scan waiting its turn
        self._said_missing: set[str] = set()
        self.scanning: dict[str, Any] | None = None  # what's being scanned now, for the page
        # Set by the app: whether anyone's watching (scanning waits), and
        # what to tell when a library's programs change.
        self.watching: Callable[[], bool] = lambda: False
        self.changed: Callable[[list[int]], None] = lambda libraries: None
        self._load()

    # Storage ---------------------------------------------------------------------

    def _load(self) -> None:
        with self.db.using() as conn:
            libs = conn.execute("SELECT * FROM folder_libraries ORDER BY id").fetchall()
            rows = conn.execute(f"SELECT {_ROW} FROM folder_items WHERE kind != ''").fetchall()
        for r in libs:
            self.libraries[r["id"]] = FolderLibrary(
                r["id"], r["name"], r["kind"], _json(r["folders"], []), r["created_ms"],
                r["scanned_ms"], r["changed_ms"], _json(r["missing"], []),
            )  # fmt: skip
        for r in rows:
            t = Thing(
                r["id"], r["library"], r["kind"], r["path"], r["root"], r["show_id"],
                _json(r["files"], []), _json(r["slot"], []), _json(r["local"], {}),
                _json(r["art"], {}), _json(r["needs"], []), r["added_ms"], bool(r["missing"]),
            )  # fmt: skip
            self.things[t.id] = t
        self.refresh_details()
        self._index()

    def _index(self) -> None:
        """The lookups by path, by show and by collection, made afresh (then
        put in place at once, so nothing ever sees them half made); what was
        kept of their files is asked again."""
        self._resolutions = {}
        by_path: dict[tuple[int, str, str], Thing] = {}
        episodes: dict[int, list[Thing]] = {}
        members: dict[tuple[int, str], list[Thing]] = {}
        collections: dict[int, list[Thing]] = {}
        for t in self.things.values():
            by_path[(t.library, t.kind, t.path)] = t
            if t.kind == EPISODE and t.show is not None:
                episodes.setdefault(t.show, []).append(t)
            elif t.kind in (SHOW, MOVIE):
                for name in {collection_key(c) for c in _strings(t.get("collections"))}:
                    members.setdefault((t.library, name), []).append(t)
            elif t.kind == COLLECTION:
                collections.setdefault(t.library, []).append(t)
        self._by_path, self._episodes = by_path, episodes
        self._members_of, self._collections = members, collections

    def refresh_details(self, things: Iterable[Thing] | None = None) -> None:
        """Works out details again (after a scan)."""
        for t in self.things.values() if things is None else things:
            t.details = merged(t)

    def _save_library(self, lib: FolderLibrary) -> None:
        with self.db.using() as conn, conn:
            conn.execute(
                "UPDATE folder_libraries SET name = ?, folders = ?, scanned_ms = ?, "
                "changed_ms = ?, missing = ? WHERE id = ?",
                (lib.name, json.dumps(lib.folders), lib.scanned_ms, lib.changed_ms,
                 json.dumps(lib.missing), lib.id),
            )  # fmt: skip

    def save_things(self, things: Iterable[Thing]) -> None:
        rows = [t.row() for t in things]
        if not rows:
            return
        with self.db.using() as conn, conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO folder_items ({_ROW}) VALUES "
                f"({', '.join('?' * len(rows[0]))})",
                rows,
            )

    def _new_id(self, conn: Any) -> int:
        """A key never used before (AUTOINCREMENT never gives one twice)."""
        cur = conn.execute(
            "INSERT INTO folder_items (library, kind, path, added_ms) VALUES (0, '', '', 0)"
        )
        return int(cur.lastrowid)

    async def _new_ids(self, count: int) -> list[int]:
        """`count` keys never used before, SLICE at a time (each kept as a
        placeholder until its row is saved: see _take_in)."""
        out: list[int] = []
        while len(out) < count:
            with self.db.using() as conn, conn:
                out += [self._new_id(conn) for _ in range(min(SLICE, count - len(out)))]
            await asyncio.sleep(0)
        return out

    async def _known(self, table: str, columns: str, paths: list[str]) -> dict[str, Any]:
        """The rows of `table` (folder_files or folder_nfos) for these paths,
        by path: asked SLICE at a time, so the database is never held long."""
        out: dict[str, Any] = {}
        for n in range(0, len(paths), SLICE):
            chunk = paths[n : n + SLICE]
            with self.db.using() as conn:
                found = conn.execute(
                    f"SELECT {columns} FROM {table} WHERE path IN ({', '.join('?' * len(chunk))})",
                    chunk,
                ).fetchall()
            out.update((r["path"], r) for r in found)
            await asyncio.sleep(0)
        return out

    async def _write(self, sql: str, items: list[Any], row: Callable[[Any], tuple]) -> None:
        """A row for each of `items`, made and written SLICE at a time,
        letting everything else have its turn between."""
        for n in range(0, len(items), SLICE):
            rows = [row(x) for x in items[n : n + SLICE]]
            with self.db.using() as conn, conn:
                conn.executemany(sql, rows)
            await asyncio.sleep(0)

    # Libraries -------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.libraries)

    def library(self, key: str) -> FolderLibrary:
        if is_folder_key(key):
            lib = self.libraries.get(int(key[len(FOLDER_PREFIX) :]))
            if lib is not None:
                return lib
        raise LibraryError(NOT_FOUND, 404)

    def checked_folders(self, folders: list[str]) -> list[str]:
        """Folders as a library keeps them: each a folder under the media
        folder (its real path, links followed), each once. NotFolder if one
        isn't."""
        media = os.path.realpath(self.settings.media_dir)
        out: list[str] = []
        for given in folders:
            text = str(given).strip()
            if not text or "\x00" in text or len(text) > 1000:
                raise NotFolder("Choose a folder in the media folder")
            path = os.path.normpath(text if os.path.isabs(text) else os.path.join(media, text))
            real = os.path.realpath(path)
            if os.path.commonpath([real, media]) != media:
                raise NotFolder(f"{text} isn’t in the media folder ({self.settings.media_dir})")
            if not os.path.isdir(real):
                raise NotFolder(f"There’s no folder {text} in the media folder")
            if real not in out:
                out.append(real)
        if not out:
            raise NotFolder("Choose at least one folder")
        if len(out) > FOLDERS_MOST:
            raise NotFolder(f"A Media folder can have at most {FOLDERS_MOST} folders")
        for inner in out:
            for outer in out:
                if inner != outer and os.path.commonpath([inner, outer]) == outer:
                    shown = [os.path.relpath(x, media) for x in (inner, outer)]
                    raise NotFolder(
                        f"{shown[0]} is inside {shown[1]}, so its titles would be listed twice. "
                        f"Choose one of them."
                    )
        return out

    def add_library(
        self, name: str, kind: str, folders: list[str], checked: bool = False
    ) -> FolderLibrary:
        """A new library (`checked`: its folders are as checked_folders
        gives them already)."""
        if kind not in (SHOW, MOVIE):
            raise NotFolder("Choose Shows or Movies")
        if len(self.libraries) >= LIBRARIES_MOST:
            raise NotFolder(f"tapiOca can read at most {LIBRARIES_MOST} Media folders itself")
        name = _name(name)
        folders = folders if checked else self.checked_folders(folders)
        now = _now()
        with self.db.using() as conn, conn:
            cur = conn.execute(
                "INSERT INTO folder_libraries (name, kind, folders, created_ms) VALUES (?, ?, ?, ?)",
                (name, kind, json.dumps(folders), now),
            )
            lib = FolderLibrary(int(cur.lastrowid or 0), name, kind, folders, now)
        self.libraries[lib.id] = lib
        return lib

    def change_library(
        self, key: str, name: str | None, folders: list[str] | None, checked: bool = False
    ) -> FolderLibrary:
        """A library's name or folders changed: both checked before either
        is (`checked`: its folders are as checked_folders gives them)."""
        lib = self.library(key)
        new_name = _name(name) if name is not None else lib.name
        if folders is not None and not checked:
            folders = self.checked_folders(folders)
        lib.name = new_name
        if folders is not None:
            lib.folders = folders
        self._save_library(lib)
        return lib

    def remove_library(self, key: str) -> FolderLibrary:
        lib = self.library(key)
        with self.db.using() as conn, conn:
            conn.execute("DELETE FROM folder_items WHERE library = ?", (lib.id,))
            conn.execute("DELETE FROM folder_libraries WHERE id = ?", (lib.id,))
        del self.libraries[lib.id]
        self.things = {i: t for i, t in self.things.items() if t.library != lib.id}
        self._index()
        return lib

    async def libraries_list(self) -> list[dict[str, Any]]:
        return [
            {"key": lib.key, "title": lib.name, "type": lib.kind, "locations": list(lib.folders)}
            for lib in self.libraries.values()
        ]

    def fingerprint(self) -> str:
        return ",".join(
            f"{lib.key}:{lib.changed_ms}:{lib.scanned_ms and 1}" for lib in self.libraries.values()
        )

    # Scanning --------------------------------------------------------------------

    def ask(self, library: int | None = None) -> None:
        """Scan a library soon (all of them, if None)."""
        self._asked.update([library] if library is not None else self.libraries)
        self._wake.set()

    def scan_soon(self, library: int) -> None:
        """Scans a library now, in the background (its turn after any scan
        going on). Asked again while one waits its turn, that one does."""
        if library in self._waiting:
            return
        self._waiting.add(library)
        task = asyncio.ensure_future(self.scan(library))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def stop(self) -> None:
        """Scans asked for and not done stop (tapiOca is shutting down)."""
        for task in list(self._tasks):
            task.cancel()

    async def run_forever(self) -> None:
        await asyncio.sleep(STARTUP_DELAY_S)
        while True:
            now = _now()
            due = [
                lib.id
                for lib in list(self.libraries.values())
                if lib.id in self._asked
                or now - max(lib.scanned_ms, lib.tried_ms) >= SCAN_EVERY_S * 1000
            ]
            for lib_id in due:
                self._asked.discard(lib_id)
                try:
                    await self.scan(lib_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception(
                        "Reading one of the Media folders tapiOca reads itself failed; trying again later"
                    )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), LOOK_EVERY_S)
            self._wake.clear()

    async def _wait_turn(self) -> None:
        """Waits while anyone's watching (scanning never reads then)."""
        for _ in itertools.count():
            if not self.watching():
                return
            await asyncio.sleep(WATCHING_WAIT_S)

    async def scan(self, library: int) -> bool:
        """Scans one library: True if anything in it changed."""
        async with self._lock:
            self._waiting.discard(library)
            lib = self.libraries.get(library)
            if lib is None:
                return False
            try:
                changed = await self._scan(lib)
            except Exception:
                log.exception(
                    "Reading the Media folder “%s” failed; tapiOca tries again in 6 hours, "
                    "or when you choose Read again", lib.name,
                )  # fmt: skip
                lib.problem = CANT_READ
                lib.tried_ms = _now()
                return False
            lib.problem = ""
            return changed

    async def _scan(self, lib: FolderLibrary) -> bool:
        started = time.monotonic()
        self.scanning = {"library": lib.key, "read": 0, "toRead": 0}
        unreadable: list[str] = []
        try:
            walked: list[folderscan.Walked] = []
            for root in lib.folders:
                await self._wait_turn()
                walked.append(
                    await folderart.on_disk(folderscan.walk, root, self.settings.media_dir)
                )
            videos = {p: (s, m) for w in walked for p, s, m in w.videos}
            probes = await self._read_files(videos)
            nfos = await self._read_nfos(walked)

            def nfo_of(path: str) -> list[dict[str, Any]] | None:
                return nfos.get(path)

            gone_roots: list[str] = []
            found: list[folderscan.Found] = []
            bad = [name for w in walked for name in w.bad_names]
            if bad:
                log.warning(
                    "tapiOca skipped %s in the Media folder “%s” because their names aren’t "
                    "UTF-8, such as %s. Rename them, and tapiOca will read them.",
                    _many(len(bad), "file or folder", "files or folders"), lib.name, bad[0],
                )  # fmt: skip
            for w in walked:
                had = any(t.root == w.root for t in self.things.values() if t.library == lib.id)
                if not w.reachable or (w.empty and had):
                    gone_roots.append(w.root)
                    continue
                # (Off to one side: a big library's take seconds.)
                found += await asyncio.to_thread(folderscan.build, lib.kind, w, probes, nfo_of)
            # (What's under a folder that can't be read now stays as it was.)
            unreadable = [u for w in walked for u in w.unreadable]
            kept = [*gone_roots, *unreadable]
            changed = await self._take_in(lib, found, kept)
        finally:
            self.scanning = None
        for root in gone_roots:
            if root not in self._said_missing:
                self._said_missing.add(root)
                log.warning(
                    "The folder %s can't be reached (is its share mounted?), so the Media "
                    "folder “%s” keeps its programs; they're missing until it's back",
                    root, lib.name,
                )  # fmt: skip
        for folder in unreadable:
            if folder not in self._said_missing:
                self._said_missing.add(folder)
                log.warning(
                    "tapiOca can't read the folder %s in the Media folder “%s” (can tapiOca's "
                    "user open it?), so what was read from it before is kept, missing, until it "
                    "can",
                    folder, lib.name,
                )  # fmt: skip
        for folder in [
            f
            for f in self._said_missing
            if f not in gone_roots
            and f not in unreadable
            and any(f == r or f.startswith(r.rstrip("/") + "/") for r in lib.folders)
        ]:
            self._said_missing.discard(folder)
            log.info("The folder %s can be read again", folder)
        lib.missing = [*gone_roots, *unreadable]
        lib.scanned_ms = _now()
        if changed:
            lib.changed_ms = lib.scanned_ms
        self._save_library(lib)
        took = time.monotonic() - started
        counts = self.counts(lib.id)
        if changed or took > 30:
            log.info(
                "Read the Media folder “%s” in %.0fs: %s",
                lib.name, took, _counted(lib.kind, counts),
            )  # fmt: skip
        if changed:
            self.changed([lib.id])
        return changed

    async def _read_files(self, videos: dict[str, tuple[int, int]]) -> dict[str, dict[str, Any]]:
        """What each video holds (`videos`: path -> size and time): as read
        before, unless it's new or changed (its size or time), when it's
        read again."""
        known = await self._known("folder_files", "path, size, mtime_ns, probe", list(videos))
        out: dict[str, dict[str, Any]] = {}
        to_read: list[str] = []
        for n, (path, (size, mtime)) in enumerate(videos.items(), 1):
            r = known.get(path)
            probe = _json(r["probe"], {}) if r is not None else {}
            if (
                r is not None
                and r["size"] == size
                and r["mtime_ns"] == mtime
                and not probe.get("slow")
            ):
                out[path] = probe
            else:
                to_read.append(path)
            if n % SLICE == 0:
                await asyncio.sleep(0)
        if self.scanning is not None:
            self.scanning["toRead"] = len(to_read)
        now = _now()
        waiting = iter(to_read)  # (shared by the readers: each file read once)

        async def reader() -> None:
            for path in waiting:
                await self._wait_turn()
                out[path] = await folderscan.read_file(self.settings.ffprobe_path, path)
                if self.scanning is not None:
                    self.scanning["read"] += 1

        await asyncio.gather(*(reader() for _ in range(PROBES_AT_ONCE)))
        fresh = set(to_read)
        await self._write(
            "INSERT OR REPLACE INTO folder_files (path, size, mtime_ns, probe, seen_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            to_read,
            lambda p: (p, *videos[p], json.dumps(out[p]), now),
        )
        await self._write(
            "UPDATE folder_files SET seen_ms = ? WHERE path = ?",
            [p for p in out if p not in fresh],
            lambda p: (now, p),
        )
        # (What was read of a file no longer seen is forgotten after a while,
        # unless a title still has it: one under a share that's away.)
        with self.db.using() as conn:
            old = [
                r["path"]
                for r in conn.execute(
                    "SELECT path FROM folder_files WHERE seen_ms < ?",
                    (now - FORGET_UNSEEN_S * 1000,),
                )
            ]
        if old:
            kept = {p for t in self.things.values() for v in t.files for p in v}
            await self._write(
                "DELETE FROM folder_files WHERE path = ?",
                [p for p in old if p not in kept],
                lambda p: (p,),
            )
        return out

    async def _read_nfos(self, walked: list[folderscan.Walked]) -> dict[str, list[dict[str, Any]]]:
        """Every NFO's details: as read before, unless it changed. One that
        can't be read is said on the Logs tab (once, until it changes)."""
        sigs = {p: s for w in walked for p, s in w.nfos.items()}
        known = await self._known("folder_nfos", "path, sig, parsed", list(sigs))
        out: dict[str, list[dict[str, Any]]] = {}
        fresh: list[tuple[str, str, str | None]] = []
        for n, (path, sig) in enumerate(sigs.items(), 1):
            r = known.get(path)
            if r is not None and r["sig"] == sig:
                if r["parsed"] is not None:
                    out[path] = _json(r["parsed"], [])
            else:
                parsed = await folderart.on_disk(self._nfo, path)
                if parsed is not None:
                    out[path] = parsed
                fresh.append((path, sig, json.dumps(parsed) if parsed is not None else None))
            if n % SLICE == 0:
                await asyncio.sleep(0)
        now = _now()
        await self._write(
            "INSERT OR REPLACE INTO folder_nfos (path, sig, parsed, seen_ms) VALUES (?, ?, ?, ?)",
            fresh,
            lambda x: (*x, now),
        )
        await self._write(
            "UPDATE folder_nfos SET seen_ms = ? WHERE path = ?",
            [p for p in sigs if p in known],
            lambda p: (now, p),
        )
        with self.db.using() as conn, conn:
            conn.execute(
                "DELETE FROM folder_nfos WHERE seen_ms < ?", (now - FORGET_UNSEEN_S * 1000,)
            )
        return out

    def _nfo(self, path: str) -> list[dict[str, Any]] | None:
        """An NFO's details; None (said once) if it can't be read."""
        if folderart.inside(path, self.settings.media_dir) is None:
            return None
        try:
            with open(path, "rb") as f:
                data = f.read(nfo.MOST_BYTES + 1)
            return nfo.parse(data)
        except (OSError, nfo.NfoError) as e:
            log.warning("tapiOca skipped the NFO file %s: %s", path, e)
            return None

    async def _take_in(
        self,
        lib: FolderLibrary,
        found: list[folderscan.Found],
        gone: list[str],
    ) -> bool:
        """What a scan found, given keys (see the module's docstring), kept
        and saved. True if anything changed. (`gone`: folders that can't be
        read now, under which everything stays as it was, missing.)

        The library's titles are worked out afresh, as new objects, a SLICE
        at a time, then put in place all at once; only then saved, a SLICE
        at a time. So nothing ever sees them half done, and a big library
        never holds everything else up. A library removed meanwhile is left
        removed."""
        old = [t for t in self.things.values() if t.library == lib.id and t.kind != COLLECTION]
        # (Under a folder that's gone, everything stays as it was, missing;
        # under one no longer the library's, it goes.)
        kept_whole = [t for t in old if t.root in gone or (gone and _under(t, gone))]
        kept_ids = {t.id for t in kept_whole}
        live = [t for t in old if t.id not in kept_ids]
        taken: set[int] = set()
        now = _now()
        by_path = {(t.kind, t.path): t for t in live}
        live_shows: dict[tuple, list[Thing]] = {}  # (by _show_keys)
        for t in live:
            if t.kind == SHOW:
                for key in _show_keys(t.local):
                    live_shows.setdefault(key, []).append(t)
        paths_now = {p for f in found if f.kind != SHOW for v in f.files for p in v}
        ticks = itertools.count(1)

        async def tick() -> None:
            if next(ticks) % SLICE == 0:
                await asyncio.sleep(0)

        # Shows: by folder; else one gone with the same title and year, or
        # an ID in common.
        shows: dict[str, Thing | None] = {}
        for f in (f for f in found if f.kind == SHOW):
            t = by_path.get((SHOW, f.path))
            if t is None or t.id in taken:
                t = self._same_show(f, live_shows, taken)
            if t is not None:
                taken.add(t.id)
            shows[f.path] = t
            await tick()
        # Episodes and movies: by file; else one whose files are all gone
        # (renamed, moved, or replaced with a better copy, as Sonarr and
        # Radarr do), in the same place in the same show, or the same movie.
        by_file: dict[str, list[Thing]] = {}
        orphans: dict[tuple, list[Thing]] = {}  # (see _orphan_keys)
        for t in live:
            if t.kind != SHOW:
                files = [p for v in t.files for p in v]
                for p in files:
                    by_file.setdefault(p, []).append(t)
                if not any(p in paths_now for p in files):
                    for key in _orphan_keys(t.kind, t.show, t.slot, t.local):
                        orphans.setdefault(key, []).append(t)
            await tick()
        pairs: list[tuple[folderscan.Found, Thing | None]] = []
        for f in (f for f in found if f.kind != SHOW):
            was_show = shows.get(f.show) if f.kind == EPISODE else None
            show_id = was_show.id if was_show is not None else None
            t = self._same_file(f, by_file, taken, show_id)
            if t is None:
                t = self._renamed(f, orphans, taken, show_id)
            if t is not None:
                taken.add(t.id)
            pairs.append((f, t))
            await tick()
        # Keys for what's new.
        new_shows = [path for path, t in shows.items() if t is None]
        ids = iter(await self._new_ids(len(new_shows) + sum(t is None for _, t in pairs)))
        show_ids = {path: (t.id if t is not None else next(ids)) for path, t in shows.items()}

        def made(f: folderscan.Found, t: Thing | None, key: int, show: int | None) -> Thing:
            got = Thing(
                key, lib.id, f.kind, f.path, f.root, show, f.files, list(f.slot), f.local,
                f.art, f.needs, t.added_ms if t is not None else now,
            )  # fmt: skip
            got.details = merged(got)
            return got

        result: list[Thing] = []
        for f, t in pairs:
            show = show_ids[f.show] if f.kind == EPISODE else None
            result.append(made(f, t, t.id if t is not None else next(ids), show))
            await tick()
        for f in (f for f in found if f.kind == SHOW):
            result.append(made(f, shows[f.path], show_ids[f.path], None))
            await tick()
        whole = [dataclasses.replace(t, missing=True) for t in kept_whole]
        # (A show whose folder holds one that can't be read now is kept, as
        # its episodes there are, even when nothing of it was found.)
        held = [
            t
            for t in (live if gone else [])
            if t.kind == SHOW
            and t.id not in taken
            and any(g.startswith(t.path.rstrip("/") + "/") for g in gone)
        ]
        whole += [dataclasses.replace(t, missing=True) for t in held]
        held_ids = {t.id for t in held}
        gone_now = [t for t in live if t.id not in taken and t.id not in held_ids]
        collections, new_collections, gone_collections = await self._collections_of(
            lib, [*result, *whole]
        )
        # What changed, to save.
        before = {t.id: t for t in old}
        changed_rows = []
        for t in [*result, *whole]:
            if before.get(t.id) is None or _fields(before[t.id]) != _fields(t):
                changed_rows.append(t)
            await tick()
        # Put in place, all at once (unless the library was removed meanwhile).
        if lib.id not in self.libraries:
            with self.db.using() as conn, conn:
                conn.execute("DELETE FROM folder_items WHERE library = 0 AND kind = ''")
            return False
        things = {i: t for i, t in self.things.items() if t.library != lib.id}
        for t in [*result, *whole, *collections]:
            things[t.id] = t
        self.things = things
        self._index()
        # Saved, a SLICE at a time (stopping if the library is removed meanwhile).
        rows = [*changed_rows, *new_collections]
        dropped = [(t.id,) for t in [*gone_now, *gone_collections]]
        for n in range(0, max(len(rows), len(dropped)), SLICE):
            if lib.id not in self.libraries:
                break
            with self.db.using() as conn, conn:
                chunk = [t.row() for t in rows[n : n + SLICE]]
                if chunk:
                    conn.executemany(
                        f"INSERT OR REPLACE INTO folder_items ({_ROW}) VALUES "
                        f"({', '.join('?' * len(chunk[0]))})",
                        chunk,
                    )
                conn.executemany("DELETE FROM folder_items WHERE id = ?", dropped[n : n + SLICE])
            await asyncio.sleep(0)
        # (Placeholders for keys made but not used: none are left.)
        with self.db.using() as conn, conn:
            conn.execute("DELETE FROM folder_items WHERE library = 0 AND kind = ''")
            if lib.id not in self.libraries:
                conn.execute("DELETE FROM folder_items WHERE library = ?", (lib.id,))
        return bool(rows or gone_now or gone_collections)

    async def _sizes_of(self, paths: list[str]) -> dict[str, int]:
        """Each file's size as last read (a file no longer there included,
        for a while: see FORGET_UNSEEN_S)."""
        return {
            p: r["size"]
            for p, r in (await self._known("folder_files", "path, size", paths)).items()
        }

    def _sizes(self, paths: set[str]) -> dict[str, int]:
        """The same, for a few files at once."""
        listed = sorted(paths)
        if not listed:
            return {}
        with self.db.using() as conn:
            return {
                r["path"]: r["size"]
                for r in conn.execute(
                    f"SELECT path, size FROM folder_files WHERE path IN ({', '.join('?' * len(listed))})",
                    listed,
                )
            }

    @staticmethod
    def _same_show(
        f: folderscan.Found, shows: dict[tuple, list[Thing]], taken: set[int]
    ) -> Thing | None:
        """The one show (`shows`: by _show_keys) with an ID in common with
        `f`, or its title and year; None if none, or several, have."""
        found = {
            t.id: t for key in _show_keys(f.local) for t in shows.get(key, []) if t.id not in taken
        }
        return next(iter(found.values())) if len(found) == 1 else None

    @staticmethod
    def _same_file(
        f: folderscan.Found, by_file: dict[str, list[Thing]], taken: set[int], show: int | None
    ) -> Thing | None:
        """The one that had one of these files: in the same place, if there
        were several (a file of two episodes), or the only one."""
        had = {
            t.id: t
            for v in f.files
            for p in v
            for t in by_file.get(p, [])
            if t.id not in taken and t.kind == f.kind
        }
        same = [t for t in had.values() if list(t.slot) == list(f.slot)]
        if same:
            return same[0]
        own = [t for t in had.values() if t.path == f.path]
        return own[0] if len(own) == 1 and len(had) == 1 else None

    @staticmethod
    def _renamed(
        f: folderscan.Found,
        orphans: dict[tuple, list[Thing]],
        taken: set[int],
        show: int | None,
    ) -> Thing | None:
        """One whose files are all gone (`orphans`), recognizably the same as
        `f`: the same show, season and episode; or the same movie (with an
        ID in common, else with the same title and year). Only when exactly
        one is, by the first of these that tells."""
        for key in _orphan_keys(f.kind, show, f.slot, f.local):
            found = {t.id: t for t in orphans.get(key, []) if t.id not in taken}
            if len(found) == 1:
                return next(iter(found.values()))
        return None

    async def _collections_of(
        self, lib: FolderLibrary, things: list[Thing]
    ) -> tuple[list[Thing], list[Thing], list[Thing]]:
        """The library's collections (a <set> in an NFO), from its titles as
        they are now: each kept under its key while it has anything in it.
        Its collections now, those new or renamed among them (to save), and
        those it no longer has."""
        names: dict[str, str] = {}
        for t in things:
            if t.kind in (SHOW, MOVIE):
                for name in _strings(_value(t, "collections")):
                    names.setdefault(collection_key(name), name)
        existing = {
            t.path: t for t in self.things.values() if t.library == lib.id and t.kind == COLLECTION
        }
        wanted = [key for key in names if key not in existing]
        ids = iter(await self._new_ids(len(wanted)))
        out: list[Thing] = []
        changed: list[Thing] = []
        for key, name in names.items():
            had = existing.pop(key, None)
            t = (
                dataclasses.replace(had)
                if had is not None
                else Thing(next(ids), lib.id, COLLECTION, key, added_ms=_now())
            )
            if had is None or t.local.get("title", [None])[0] != name:
                t.local = {"title": [name, folderscan.NFO, ""]}
                changed.append(t)
            t.details = merged(t)
            out.append(t)
        return out, changed, list(existing.values())

    def totals(self, since_s: int, keys: list[str] | None = None) -> tuple[int, int, int, int]:
        """How many movies, shows and episodes these libraries have (by key;
        None: every one), and how many movies and episodes they've had from
        `since_s` (seconds since 1970) on: for INFO's numbers."""
        wanted = None if keys is None else {k for k in keys if is_folder_key(k)}
        movies = shows = episodes = added = 0
        for t in self.things.values():
            lib = self.libraries.get(t.library)
            if lib is None or (wanted is not None and lib.key not in wanted):
                continue
            if t.kind == MOVIE:
                movies += 1
            elif t.kind == SHOW:
                shows += 1
            elif t.kind == EPISODE:
                episodes += 1
            if t.kind in (MOVIE, EPISODE) and t.added_ms >= since_s * 1000:
                added += 1
        return movies, shows, episodes, added

    def counts(self, library: int) -> dict[str, int]:
        """How many shows, episodes and movies a library has, and how many
        of its programs (episodes and movies) are missing."""
        out = {SHOW: 0, EPISODE: 0, MOVIE: 0, "missing": 0}
        for t in self.things.values():
            if t.library == library and t.kind in out:
                out[t.kind] += 1
                out["missing"] += t.missing and t.kind != SHOW
        return out

    # Things ---------------------------------------------------------------------------

    def thing(self, key: str) -> Thing:
        if is_folder_key(key):
            t = self.things.get(int(key[len(FOLDER_PREFIX) :]))
            if t is not None and t.kind != COLLECTION:
                return t
        raise LibraryError(NO_SUCH, 404)

    # What things are -----------------------------------------------------------------

    def show_of(self, t: Thing) -> Thing | None:
        return self.things.get(t.show) if t.show is not None else None

    def episodes_of(self, show: Thing) -> list[Thing]:
        return self._episodes.get(show.id, [])

    def _probe(self, path: str) -> dict[str, Any]:
        with self.db.using() as conn:
            r = conn.execute("SELECT probe FROM folder_files WHERE path = ?", (path,)).fetchone()
        return _json(r["probe"], {}) if r else {}

    def _probes(self, paths: list[str]) -> dict[str, dict[str, Any]]:
        if not paths:
            return {}
        out: dict[str, dict[str, Any]] = {}
        with self.db.using() as conn:
            for at in range(0, len(paths), 500):
                batch = paths[at : at + 500]
                for r in conn.execute(
                    f"SELECT path, probe FROM folder_files WHERE path IN ({','.join('?' * len(batch))})",
                    batch,
                ):
                    out[r["path"]] = _json(r["probe"], {})
        return out

    async def _probes_sliced(self, paths: list[str]) -> dict[str, dict[str, Any]]:
        """The same, for a whole library's (letting everything else have its
        turn between each SLICE)."""
        out: dict[str, dict[str, Any]] = {}
        for at in range(0, len(paths), SLICE):
            out.update(self._probes(paths[at : at + SLICE]))
            await asyncio.sleep(0)
        return out

    def title_of(self, t: Thing) -> str:
        title = str(t.get("title") or "")
        if title or t.kind != EPISODE:
            return title or _named(t.path)
        if isinstance(t.get("episode"), int):
            return f"Episode {t.get('episode')}"
        if t.get("released"):
            return str(t.get("released"))
        return _named(t.path)

    def _duration(self, t: Thing, probes: dict[str, dict[str, Any]]) -> int | None:
        if not t.files:
            return None
        first = probes.get(t.files[0][0]) or {}
        return first.get("durationMs") or None

    def entry(self, t: Thing, probes: dict[str, dict[str, Any]], details: bool = False) -> Entry:
        """A show, movie or episode as the apps are told it."""
        lib = self.libraries.get(t.library)
        show = self.show_of(t)
        episodes = self.episodes_of(t) if t.kind == SHOW else []
        media = tuple(self._media(t, probes)) if details and t.kind != SHOW else ()
        studios = _strings(t.get("studios"))
        rating = t.get("content_rating")
        return Entry(
            key=t.key,
            kind=t.kind,
            title=self.title_of(t),
            year=_number(t.get("year")) or (_number(show.get("year")) if show else None),
            summary=str(t.get("summary") or ""),
            library=lib.key if lib else "",
            show_key=show.key if show else None,
            show_title=self.title_of(show) if show else "",
            season=_number(t.get("season")) if t.kind == EPISODE else None,
            episode=_number(t.get("episode")) if t.kind == EPISODE else None,
            duration_ms=self._duration(t, probes) if t.kind != SHOW else None,
            added_ms=t.added_ms,
            released=str(t.get("released") or "")[:10],
            episodes=len(episodes) if t.kind == SHOW else None,
            seasons=len({e.get("season") for e in episodes}) if t.kind == SHOW else None,
            genres=tuple(_strings(t.get("genres") or (show.get("genres") if show else None))[:10]),
            content_rating=str(rating or (show.get("content_rating") if show else "") or ""),
            studio=studios[0] if studios else "",
            has_thumb=bool(self._poster_of(t)),
            has_art=bool(self._backdrop_of(t)),
            media=media,
            sort_title=str(t.get("sort_title") or ""),
            file=t.files[0][0] if t.files else "",
            tagline=str(t.get("tagline") or "") if details else "",
            cast=tuple((str(n), str(r)) for n, r in _cast(t.get("cast"))[:CAST_MOST])
            if details
            else (),
            directors=tuple(_strings(t.get("directors"))[:CREW_MOST]) if details else (),
            writers=tuple(_strings(t.get("writers"))[:CREW_MOST]) if details else (),
            tags=_tags(t) if t.kind in (SHOW, MOVIE) else None,
        )

    def _file(self, path: str, probe: dict[str, Any], size: int | None, vid: str) -> Media:
        """One file, as a version's (or a version's part) is described."""
        video = probe.get("video") or {}
        return Media(
            container=catalog.container(probe.get("container") or naming.extension(path)[1:]),
            video=catalog.video_codec(video.get("codec")),
            width=int(video.get("width") or 0),
            height=int(video.get("height") or 0),
            bit_depth=int(video.get("bitDepth") or 8),
            hdr=video.get("hdr") or "",
            dv_profile=video.get("dv"),
            bitrate_kbps=probe.get("bitrateKbps"),
            file=path,
            part_key=None,
            size=size,
            duration_ms=probe.get("durationMs") or None,
            id=vid,
            audio=tuple(_track(a, catalog.audio_codec) for a in probe.get("audio") or []),
            subtitles=tuple(
                _track(x, catalog.subtitle_codec) for x in probe.get("subtitles") or []
            ),
        )

    def _media(self, t: Thing, probes: dict[str, dict[str, Any]]) -> list[Media]:
        """Its versions (those whose first file opens), each in one file or
        in several, played one after the other as one (catalog.Media)."""
        out = []
        sizes = self._sizes({p for parts in t.files for p in parts})
        for parts in t.files:
            probe = probes.get(parts[0]) or {}
            if not probe.get("ok"):
                continue
            # (A version's id stays the same while its first file does, however
            # many others come and go: never its place in the list.)
            vid = _version_id(parts[0])
            if len(parts) == 1:
                out.append(self._file(parts[0], probe, sizes.get(parts[0]), vid))
                continue
            each = [self._file(p, probes.get(p) or {}, sizes.get(p), vid) for p in parts]
            lengths = [m.duration_ms for m in each]
            got = [m.size for m in each]
            out.append(
                dataclasses.replace(
                    each[0],
                    duration_ms=sum(x for x in lengths if x) if all(lengths) else None,
                    size=sum(x for x in got if x) if all(got) else None,
                    parts=tuple(each),
                )
            )
        return out

    def item(self, t: Thing, probes: dict[str, dict[str, Any]]) -> Item | None:
        """An episode or movie as a station has it; None if it can't be one
        (no file that opens, or a special)."""
        if t.kind not in (EPISODE, MOVIE) or not t.files:
            return None
        duration = self._duration(t, probes)
        if not duration or duration < 1000:
            return None
        season = _number(t.get("season"))
        if t.kind == EPISODE and season == 0:
            return None  # (specials are rarely what anyone wants on a station)
        show = self.show_of(t)
        lib = self.libraries.get(t.library)
        rating = t.get("content_rating") or (show.get("content_rating") if show else None)
        return Item(
            position=0,
            start_ms=0,
            duration_ms=int(duration),
            rating_key=t.key,
            kind=t.kind,
            title=self.title_of(t),
            show_title=self.title_of(show) if show else None,
            show_key=show.key if show else None,
            season=season if t.kind == EPISODE else None,
            episode=_number(t.get("episode")) if t.kind == EPISODE else None,
            year=_number(t.get("year")) or (_number(show.get("year")) if show else None),
            summary=str(t.get("summary") or "") or None,
            file_path=t.files[0][0],
            part_key=None,
            rating=str(rating) if rating else None,
            library=lib.key if lib else None,
        )

    # For the library layer -------------------------------------------------------------

    def _of_library(self, library: str, kinds: tuple[str, ...]) -> list[Thing]:
        lib = self.library(library)
        return [t for t in self.things.values() if t.library == lib.id and t.kind in kinds]

    async def library_items(self, library: str) -> list[dict[str, Any]]:
        lib = self.library(library)
        things = self._of_library(library, (lib.kind,))
        probes = await self._probes_sliced([t.files[0][0] for t in things if t.files])
        return [
            {
                "ratingKey": t.key,
                "type": t.kind,
                "title": self.title_of(t),
                "year": _number(t.get("year")),
                "episodes": len(self.episodes_of(t)) if t.kind == SHOW else None,
                "durationMs": self._duration(t, probes) if t.kind == MOVIE else None,
                "genres": _strings(t.get("genres"))[:3],
                "poster": True,
            }
            for t in sorted(things, key=lambda t: _sort_title(self.title_of(t), t))
        ]

    async def filter_fields(self, library: str, kind: str) -> list[dict[str, str]]:
        self.library(library)
        return [
            {"field": "genre", "title": "Genre"},
            {"field": "collection", "title": "Collection"},
            {"field": "studio", "title": "Network" if kind == SHOW else "Studio"},
            {"field": "contentRating", "title": "Content rating"},
            {"field": "director", "title": "Director"},
            {"field": "actor", "title": "Actor"},
        ]

    async def choices(self, library: str, field_name: str, kind: str) -> list[dict[str, str]]:
        things = self._of_library(library, (SHOW if kind == SHOW else MOVIE,))
        if field_name == "decade":
            decades = sorted({y // 10 * 10 for t in things if (y := _number(t.get("year")))})
            return [{"id": str(d), "title": f"{d}s"} for d in decades]
        names: dict[str, str] = {}
        for t in things:
            for v in _values_of(t, field_name):
                names.setdefault(v.casefold(), v)
        return [{"id": v, "title": v} for v in sorted(names.values(), key=str.casefold)]

    def _matches(self, source: dict[str, Any]) -> list[Thing]:
        kind = SHOW if source.get("kind") == SHOW else MOVIE
        decades = {int(d) for d in source.get("decade") or []}
        words = str(source.get("titleContains") or "").strip().casefold()
        min_rating = float(source.get("minRating") or 0)
        days = int(source.get("addedWithinDays") or 0)
        since = _now() - days * 86_400_000 if days > 0 and kind == MOVIE else None
        left_out = {str(k) for k in source.get("exclude") or []}
        tags = {f: {str(v).casefold() for v in vs} for f, vs in filter_tags(source).items()}
        out = []
        for library in source.get("libraries") or []:
            if not is_folder_key(str(library)):
                continue
            try:
                things = self._of_library(str(library), (kind,))
            except LibraryError:
                continue
            for t in things:
                year = _number(t.get("year"))
                if decades and not (year and year // 10 * 10 in decades):
                    continue
                if words and words not in self.title_of(t).casefold():
                    continue
                rating = t.get("audience_rating")
                if min_rating and not (isinstance(rating, (int, float)) and rating >= min_rating):
                    continue
                if since and t.added_ms < since:
                    continue
                if any(
                    not {v.casefold() for v in _values_of(t, f)} & wanted
                    for f, wanted in tags.items()
                ):
                    continue
                if t.key in left_out:
                    continue
                out.append(t)
        return out

    def _as_plex(self, t: Thing) -> dict[str, Any]:
        """A show or movie described the way Plex's lists describe one, for
        what reads those (filters' previews, smart stations)."""
        lib = self.libraries.get(t.library)
        out: dict[str, Any] = {
            "ratingKey": t.key,
            "type": t.kind,
            "title": self.title_of(t),
            "year": _number(t.get("year")),
            "addedAt": t.added_ms // 1000,
            "librarySectionID": lib.key if lib else "",
            "Genre": [{"tag": g} for g in _strings(t.get("genres"))],
            "Collection": [{"tag": c} for c in _strings(t.get("collections"))],
            "Director": [{"tag": d} for d in _strings(t.get("directors"))],
            "Role": [{"tag": n} for n, _ in _cast(t.get("cast"))],
        }
        studios = _strings(t.get("studios"))
        if studios:
            out["studio"] = studios[0]
        if t.get("content_rating"):
            out["contentRating"] = str(t.get("content_rating"))
        if isinstance(t.get("audience_rating"), (int, float)):
            out["audienceRating"] = t.get("audience_rating")
        if t.kind == SHOW:
            out["leafCount"] = len(self.episodes_of(t))
        return out

    async def filter_matches(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        return [self._as_plex(t) for t in self._matches(source)]

    def _filter_episode_things(self, source: dict[str, Any]) -> list[Thing]:
        days = int(source.get("addedWithinDays") or 0)
        since = _now() - days * 86_400_000 if days > 0 else None
        return [
            e
            for show in self._matches(source)
            for e in self.episodes_of(show)
            if since is None or e.added_ms >= since
        ]

    async def filter_episodes(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        for e in self._filter_episode_things(source):
            show = self.show_of(e)
            out.append({
                "ratingKey": e.key, "type": EPISODE, "title": self.title_of(e),
                "grandparentRatingKey": show.key if show else "",
                "grandparentTitle": self.title_of(show) if show else "",
                "addedAt": e.added_ms // 1000,
            })  # fmt: skip
        return out

    async def collections(self) -> list[dict[str, Any]]:
        out = []
        for lib in self.libraries.values():
            for t in sorted(
                self._collections.get(lib.id, []),
                key=lambda t: str(t.get("title") or "").casefold(),
            ):
                members = self._members(t)
                out.append({
                    "ratingKey": t.key, "title": str(t.get("title") or ""), "library": lib.key,
                    "libraryTitle": lib.name, "kind": lib.kind, "count": len(members),
                    "smart": False, "updatedAt": lib.changed_ms // 1000,
                })  # fmt: skip
        return out

    def _members(self, collection: Thing) -> list[Thing]:
        return self._members_of.get((collection.library, collection.path), [])

    @staticmethod
    def followed_collection(
        source: dict[str, Any], collections: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        key = str(source.get("ratingKey") or "")
        for c in collections:
            if str(c["ratingKey"]) == key:
                return c
        title = collection_key(str(source.get("title") or ""))
        library = str(source.get("library") or "")
        for c in collections:
            if c["library"] == library and collection_key(c["title"]) == title:
                return c
        return None

    async def items_for_source(self, source: dict[str, Any]) -> list[Item]:
        kind = source.get("type")
        things: list[Thing]
        if kind in (SHOW, MOVIE):
            t = self._followed(source, kind)
            things = self.episodes_of(t) if kind == SHOW else [t]
        elif kind == "section":
            lib = self.library(str(source.get("key") or ""))
            want = EPISODE if lib.kind == SHOW else MOVIE
            things = [t for t in self.things.values() if t.library == lib.id and t.kind == want]
        elif kind == "filter":
            if source.get("kind") == SHOW:
                things = self._filter_episode_things(source)
            else:
                things = self._matches(source)
        elif kind == COLLECTION:
            found = self.followed_collection(source, await self.collections())
            members = self._members(self.things[int(found["ratingKey"][1:])]) if found else []
            things = [e for m in members for e in (self.episodes_of(m) if m.kind == SHOW else [m])]
        else:
            raise LibraryError(f"Unknown source type {kind!r}")
        things = sorted(things, key=_in_order)
        probes = await self._probes_sliced([t.files[0][0] for t in things if t.files])
        out: list[Item] = []
        for n, t in enumerate(things, 1):
            if (got := self.item(t, probes)) is not None:
                out.append(got)
            if n % SLICE == 0:
                await asyncio.sleep(0)
        return out

    def _wanted(self, key: str, kind: str) -> Thing:
        t = self.thing(key)
        if t.kind != kind:
            raise LibraryError(NO_SUCH, 404)
        return t

    def _followed(self, source: dict[str, Any], kind: str) -> Thing:
        """A station's show or movie; if it's no longer under its key (taken
        out of its folder and put back, say), the one with its title, when
        exactly one has it, as Plex's are followed (see plex._show_or_movie)."""
        key = str(source.get("ratingKey") or "")
        try:
            return self._wanted(key, kind)
        except LibraryError:
            title = naming.folded(str(source.get("title") or ""))
            if not title or not is_folder_key(key):
                raise
        named = [
            t
            for t in self.things.values()
            if t.kind == kind and naming.folded(self.title_of(t)) == title
        ]
        if len(named) != 1:
            raise LibraryError(
                f"Your own Media folders no longer have the {kind} “{source.get('title')}” under "
                f"its key, and have {len(named) or 'no other'} with that title. Edit the station "
                "to choose it again.",
                404,
            )
        log.info(
            "The %s “%s” is under a new key in the Media folders tapiOca reads itself now; using it",
            kind, source.get("title"),
        )  # fmt: skip
        return named[0]

    async def find_again(self, item: Item) -> str | None:
        """The key a program has now, if its library has it under another:
        an episode in the same place in its show, or the same movie."""
        if item.kind == EPISODE:
            if not item.show_key or item.season is None or item.episode is None:
                return None
            try:
                show = self.thing(item.show_key)
            except LibraryError:
                return None
            for e in self.episodes_of(show):
                if e.key != item.rating_key and (e.get("season"), e.get("episode")) == (
                    item.season,
                    item.episode,
                ):
                    return e.key
            return None
        if not item.title or item.year is None:
            return None
        wanted = naming.folded(item.title)
        for t in self.things.values():
            if (
                t.kind == MOVIE
                and t.key != item.rating_key
                and naming.folded(self.title_of(t)) == wanted
                and _number(t.get("year")) == item.year
            ):
                return t.key
        return None

    async def current_files(self, key: str) -> tuple[Media, ...]:
        """The files a program has now (its first version's: one, or a movie
        on two discs' two), in order; () if it has none. LibraryError while
        its folder can't be reached."""
        t = self.thing(key)
        if not t.files:
            return ()
        if t.missing:
            # (A passing trouble: never a broken file.)
            raise LibraryError("its folder can't be reached right now")
        paths = [p for parts in t.files for p in parts]
        versions = self._media(t, self._probes(paths))
        return versions[0].files if versions else ()

    async def markers_and_added(self, key: str) -> tuple[list[dict[str, Any]], int | None]:
        try:
            t = self.thing(key)
        except LibraryError:
            return [], None
        return [], t.added_ms // 1000

    async def ids(self, key: str) -> dict[str, str]:
        t = self.thing(key)
        lib = self.libraries.get(t.library)
        out = {k: str(v) for k, v in (t.get("ids") or {}).items() if k in ("tvdb", "tmdb", "imdb")}
        if lib is not None:
            out["section"] = lib.key
        return out

    def resolution(self, key: str) -> str | None:
        """A program's picture size ("4K", "1080p", "720p" or "SD"), from
        its first file, as read."""
        try:
            t = self.thing(key)
        except LibraryError:
            return None
        if not t.files:
            return None
        if key in self._resolutions:  # (kept: the station list asks of every program)
            return self._resolutions[key]
        video = self._probe(t.files[0][0]).get("video") or {}
        size = catalog.size_label(int(video.get("width") or 0), int(video.get("height") or 0))
        found = "SD" if size in ("576p", "480p") else size or None
        self._resolutions[key] = found
        return found

    # For tapiOca's apps --------------------------------------------------------------

    async def browse(
        self, library: str, kind: str, sort: str, start: int, size: int, genre: str | None = None
    ) -> tuple[int, list[Entry]]:
        things = self._of_library(library, (SHOW if kind == catalog.SHOW else MOVIE,))
        if genre:
            wanted = genre.casefold()
            things = [
                t for t in things if wanted in {g.casefold() for g in _strings(t.get("genres"))}
            ]
        if sort == "added":
            things.sort(key=lambda t: self._added(t), reverse=True)
        elif sort == "released":
            things.sort(key=lambda t: str(t.get("released") or t.get("year") or ""), reverse=True)
        else:
            things.sort(key=lambda t: _sort_title(self.title_of(t), t))
        page = things[start : start + size]
        probes = self._probes([t.files[0][0] for t in page if t.files])
        return len(things), [self.entry(t, probes) for t in page]

    def _added(self, t: Thing) -> int:
        if t.kind == SHOW:
            return max((e.added_ms for e in self.episodes_of(t)), default=t.added_ms)
        return t.added_ms

    async def recently_added(self, library: str, kind: str, count: int) -> list[Entry]:
        return (await self.browse(library, kind, "added", 0, count))[1]

    async def added_files(
        self, library: str, kind: str, start: int, size: int
    ) -> tuple[int, list[Entry]]:
        """A page of a library's episodes (of a library of shows) or movies,
        the most recently added first, each with its versions' files (for
        checking them: see scanner.py): (how many in all, the page)."""
        want = EPISODE if kind == catalog.SHOW else MOVIE
        things = sorted(
            self._of_library(library, (want,)), key=lambda t: (t.added_ms, t.id), reverse=True
        )
        page = things[start : start + size]
        probes = self._probes([p for t in page for v in t.files for p in v])
        return len(things), [self.entry(t, probes, details=True) for t in page]

    async def entry_of(self, key: str, details: bool = False) -> Entry | None:
        try:
            t = self.thing(key)
        except LibraryError:
            return None
        paths = [p for v in t.files for p in v] if details else [t.files[0][0]] if t.files else []
        return self.entry(t, self._probes(paths), details)

    async def entries(self, keys: list[str]) -> list[Entry]:
        found = []
        for key in dict.fromkeys(keys):
            with contextlib.suppress(LibraryError):
                found.append(self.thing(key))
        probes = self._probes([t.files[0][0] for t in found if t.files])
        return [self.entry(t, probes) for t in found]

    async def show_episodes(self, show: str) -> list[Entry]:
        try:
            t = self.thing(show)
        except LibraryError:
            return []
        if t.kind != SHOW:
            return []
        episodes = self.episodes_of(t)
        probes = self._probes([e.files[0][0] for e in episodes if e.files])
        return sorted((self.entry(e, probes) for e in episodes), key=episode_order)

    # Pictures ------------------------------------------------------------------------------

    def _backdrop_of(self, t: Thing) -> str:
        return t.art.get("backdrop", "")

    def _poster_of(self, t: Thing) -> str:
        """Where a show's or movie's poster is, or an episode's still (its
        show's poster, if it has none); "" for none."""
        if t.kind == EPISODE:
            show = self.show_of(t)
            return t.art.get("thumb", "") or (show.art.get("poster", "") if show else "")
        return t.art.get("poster", "")

    async def picture(self, key: str, which: str, width: int, height: int) -> tuple[bytes, str]:
        """A show's, movie's or episode's picture ("thumb": its poster, or an
        episode's still; "art": its backdrop), no bigger than asked.
        NoPicture if there's none."""
        t = self.thing(key)
        got = await self._picture(t, which)
        return await folderart.sized(self.settings.ffmpeg_path, got, width, height)

    async def _picture(self, t: Thing, which: str) -> tuple[bytes, str]:
        """Beside the videos, or inside a file (folderart.py); NoPicture if
        there's none. (An episode with no still has its show's poster.)"""
        where = self._backdrop_of(t) if which == "art" else self._poster_of(t)
        if not where:
            raise NoPicture(t.key)
        return await self._from(where)

    async def _from(self, where: str) -> tuple[bytes, str]:
        """A picture: beside the videos, or inside a file."""
        media = self.settings.media_dir
        try:
            if where.startswith("cover:"):
                _, stream, codec, path = where.split(":", 3)
                real = await asyncio.wait_for(
                    folderart.on_disk(folderart.inside, path, media), DISK_WAIT_S
                )
                if real is None or not stream.isdigit():
                    raise NoPicture(where)
                size = self._sizes({path}).get(path) or 0
                return await folderart.cover(
                    self.settings.ffmpeg_path,
                    self.settings.data_dir,
                    real,
                    int(stream),
                    codec,
                    size,
                )
            return await asyncio.wait_for(
                folderart.on_disk(folderart.read_picture, where, media), DISK_WAIT_S
            )
        except TimeoutError:
            raise NoPicture(where) from None  # (its disk isn't answering: no picture for now)

    async def poster(self, key: str, width: int, height: int) -> tuple[bytes, str]:
        t = self.thing(key)
        if t.kind == EPISODE and (show := self.show_of(t)) is not None:
            t = show
        return await folderart.sized(
            self.settings.ffmpeg_path, await self._picture(t, "thumb"), width, height
        )

    async def art(self, key: str) -> tuple[bytes, str]:
        """A program's picture for Plex's guide."""
        return await self.picture(key, "thumb", 640, 640)

    async def clear_logo(self, key: str) -> tuple[str, str] | None:
        try:
            t = self.thing(key)
        except LibraryError:
            return None
        where = t.art.get("logo", "")
        return (self.title_of(t), f"{t.key}:logo") if where else None

    async def logo_bytes(self, where: str) -> bytes:
        key, _, _ = where.partition(":")
        t = self.thing(key)
        found = t.art.get("logo", "")
        if not found:
            raise LibraryError("There's no such logo", 404)
        try:
            return (await self._from(found))[0]
        except NoPicture:
            raise LibraryError("That logo can't be read", 404) from None

    # Rescans -------------------------------------------------------------------------------

    async def scan_folder(self, library: str, folder: str) -> None:
        """Sonarr or Radarr brought a replacement: the library is scanned soon
        (only what's new or changed is read)."""
        lib = self.library(library)
        self.scan_soon(lib.id)

    def status(self) -> list[dict[str, Any]]:
        """Each folder library, for the page."""
        out = []
        for lib in self.libraries.values():
            counts = self.counts(lib.id)
            out.append({
                "key": lib.key, "name": lib.name, "kind": lib.kind, "folders": lib.folders,
                "scannedMs": lib.scanned_ms or None, "missingFolders": lib.missing,
                "problem": lib.problem or None,
                "shows": counts[SHOW], "episodes": counts[EPISODE], "movies": counts[MOVIE],
                "missing": counts["missing"],
                "scanning": self.scanning if self.scanning and self.scanning["library"] == lib.key else None,
            })  # fmt: skip
        return out


# Helpers ------------------------------------------------------------------------------


def _json(text: str | None, otherwise: Any) -> Any:
    try:
        got = json.loads(text) if text else otherwise
    except ValueError:
        return otherwise
    return got if isinstance(got, type(otherwise)) else otherwise


def _now() -> int:
    return int(time.time() * 1000)


def _name(name: str) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise NotFolder("Give it a name")
    if len(text) > NAME_MAX:
        raise NotFolder(f"A name can be at most {NAME_MAX} characters")
    return text


def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str) and v]
    return []


def _cast(value: Any) -> list[tuple[str, str]]:
    out = []
    for c in value or []:
        if isinstance(c, list) and c and isinstance(c[0], str):
            out.append((c[0], str(c[1]) if len(c) > 1 and c[1] else ""))
        elif isinstance(c, str):
            out.append((c, ""))
    return out


def _value(t: Thing, name: str) -> Any:
    return t.get(name)


def _values_of(t: Thing, field_name: str) -> list[str]:
    if field_name == "genre":
        return _strings(t.get("genres"))
    if field_name == "collection":
        return _strings(t.get("collections"))
    if field_name == "studio":
        return _strings(t.get("studios"))
    if field_name == "contentRating":
        return _strings(t.get("content_rating"))
    if field_name == "director":
        return _strings(t.get("directors"))
    if field_name == "actor":
        return [n for n, _ in _cast(t.get("cast"))]
    return []


def _show_keys(local: dict[str, list]) -> list[tuple]:
    """How a show is found again in another folder: each of its IDs, and
    its title and year."""
    ids = (local.get("ids") or [{}])[0]
    keys = [("id", k, str(v)) for k, v in sorted(ids.items())] if isinstance(ids, dict) else []
    title = naming.folded(str((local.get("title") or [""])[0]))
    if title:
        keys.append(("title", title, (local.get("year") or [None])[0]))
    return keys


def _orphan_keys(kind: str, show: int | None, slot: list, local: dict[str, list]) -> list[tuple]:
    """How an episode or movie whose files are gone is found again (see
    _renamed), most certain first."""
    if kind == EPISODE:
        return [("episode", show, json.dumps(slot))] if show is not None and slot else []
    # (Never by its folder alone: another movie in a folder of several isn't
    # it. A movie's own folder names it, so its title says the same.)
    keys: list[tuple] = []
    ids = (local.get("ids") or [{}])[0]
    keys += [("id", k, str(v)) for k, v in sorted(ids.items())] if isinstance(ids, dict) else []
    title = naming.folded(str((local.get("title") or [""])[0]))
    if title:
        keys.append(("title", title, (local.get("year") or [None])[0]))
    return keys


def _same_movie(a: dict[str, list], b: dict[str, list]) -> bool:
    ids_a = (a.get("ids") or [{}])[0]
    ids_b = (b.get("ids") or [{}])[0]
    if ids_a and ids_b and set(ids_a.items()) & set(ids_b.items()):
        return True
    return (
        naming.folded(str(a.get("title", [""])[0])) == naming.folded(str(b.get("title", [""])[0]))
        and a.get("year", [None])[0] == b.get("year", [None])[0]
    )


def _sort_title(title: str, t: Thing) -> tuple:
    text = str(t.get("sort_title") or title).casefold()
    for article in ("the ", "a ", "an "):
        if text.startswith(article):
            text = text[len(article) :]
            break
    return (text, t.id)


def _in_order(t: Thing) -> tuple:
    season = _number(t.get("season"))
    episode = _number(t.get("episode"))
    return (
        t.show or 0,
        season if season is not None else 10_000,
        episode if episode is not None else 10_000,
        str(t.get("released") or ""),
        t.id,
    )


def _track(t: dict[str, Any], codec: Callable[[str | None], str]) -> Track:
    code = languages.code(t.get("language")) or ""
    return Track(
        id=str(t.get("index")),
        codec=codec(t.get("codec")),
        language=languages.name(code) if code else "",
        title=str(t.get("title") or ""),
        channels=t.get("channels") if isinstance(t.get("channels"), int) else None,
        default=bool(t.get("default")),
        forced=bool(t.get("forced")),
        external=False,
        index=t.get("index") if isinstance(t.get("index"), int) else None,
        language_code=code,
    )


def _named(path: str) -> str:
    """A title from a file's (or folder's) name, else its folder's, else
    "Untitled": never a name as it is (see naming.title_from)."""
    return (
        naming.title_from(os.path.basename(path))
        or naming.folder_title(os.path.basename(os.path.dirname(path)))
        or "Untitled"
    )


def _version_id(path: str) -> str:
    """A version's id, from its first file (digits, as Plex's are; the
    file's name never shows in it)."""
    return str(int(hashlib.sha256(path.encode("utf-8", "surrogateescape")).hexdigest()[:9], 16))


def _tags(t: Thing) -> catalog.Tags:
    """A show's or movie's tags for limits (see catalog.Tags), from its
    details: every genre, tag (<tag> in its NFO, as Plex's labels),
    collection and its studio, each once."""

    def every(name: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(_strings(t.get(name))))[: catalog.TAGS_MOST]

    studios = _strings(t.get("studios"))
    return catalog.Tags(
        every("genres"), every("labels"), every("collections"), studios[0] if studios else ""
    )


def _many(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _under(t: Thing, folders: list[str]) -> bool:
    """Whether a thing (its folder, or a file of it) is in one of `folders`."""
    paths = [t.path, *(p for v in t.files for p in v)]
    return any(p == f or p.startswith(f.rstrip("/") + "/") for p in paths for f in folders)


def _counted(kind: str, counts: dict[str, int]) -> str:
    def n(count: int, what: str) -> str:
        return f"{count} {what}{'' if count == 1 else 's'}"

    if kind == SHOW:
        text = f"{n(counts[SHOW], 'show')} and {n(counts[EPISODE], 'episode')}"
    else:
        text = n(counts[MOVIE], "movie")
    return text + (f" ({counts['missing']} missing)" if counts["missing"] else "")


# The page's addresses (Admins only: see access.py) ------------------------------------


class FolderLibraryIn(BaseModel):
    name: str = Field(max_length=NAME_MAX * 2)
    kind: str = Field(max_length=10)
    folders: list[str] = Field(min_length=1, max_length=FOLDERS_MOST)


class FolderLibraryChange(BaseModel):
    name: str | None = Field(default=None, max_length=NAME_MAX * 2)
    folders: list[str] | None = Field(default=None, min_length=1, max_length=FOLDERS_MOST)


def _folders_in(media_dir: str, path: str) -> dict[str, Any] | None:
    """The folders in one under the media folder (`path`, from it): None
    if it isn't one."""
    media = os.path.realpath(media_dir)
    here = os.path.realpath(os.path.join(media, path.lstrip("/"))) if path else media
    if os.path.commonpath([here, media]) != media or not os.path.isdir(here):
        return None
    try:
        with os.scandir(here) as found:
            names = sorted(
                (e.name for e in found
                 if not e.name.startswith(".") and folderscan.utf8(e.name) and e.is_dir()
                 and folderscan.inside_dir(e.path, media)),
                key=str.casefold,
            )[:2000]  # fmt: skip
    except OSError:
        names = []
    rel = os.path.relpath(here, media)
    return {"path": "" if rel == "." else rel, "full": here, "folders": names}


def routes(app: FastAPI, ctx: AppContext) -> None:
    folders = ctx.folders

    def who(request: Request) -> str:
        user = access.signed_in(request)
        return f" (by {user.name})" if user else ""

    def plex_overlaps(lib_folders: list[str], plex: list[dict[str, Any]]) -> list[str]:
        """Plex's libraries with one of these folders (tapiOca sees Plex's
        folders under its own media folder: see sources.py)."""
        from .sources import local_candidates

        out = []
        for section in plex:
            for location in section.get("locations") or []:
                seen = {c.path for c in local_candidates(ctx.settings, ctx.media_access, location)}
                seen.add(location)
                if any(
                    s == f or s.startswith(f.rstrip("/") + "/") or f.startswith(s.rstrip("/") + "/")
                    for s in seen
                    for f in lib_folders
                ):
                    out.append(str(section.get("title") or ""))
                    break
        return out

    async def plex_libraries() -> tuple[list[dict[str, Any]], str | None]:
        if not ctx.plex.configured:
            return [], None
        try:
            return await asyncio.wait_for(ctx.plex.sections(), setup.PLEX_ASK_S), None
        except (LibraryError, TimeoutError) as e:
            return [], str(e) or "Plex didn't answer"

    async def checked_folders(chosen: list[str]) -> list[str]:
        """Folders as a library keeps them (see FolderSource.checked_folders),
        checked off to one side: they're on the media folder's disks."""
        try:
            return await asyncio.wait_for(
                folderart.on_disk(folders.checked_folders, chosen), DISK_WAIT_S
            )
        except TimeoutError:
            raise NotFolder("The media folder isn’t answering right now. Try again soon.") from None

    @app.get("/api/folder-libraries")
    async def folder_libraries():
        plex, problem = await plex_libraries()
        listed = folders.status()
        for lib in listed:
            lib["alsoInPlex"] = plex_overlaps(lib["folders"], plex)
        return {
            "libraries": listed,
            "plex": [{"key": s["key"], "title": s["title"], "type": s["type"]} for s in plex],
            "plexProblem": problem,
            "mediaDir": ctx.settings.media_dir,
            "mediaReal": await folderart.on_disk(os.path.realpath, ctx.settings.media_dir),
        }

    @app.get("/api/folder-libraries/browse")
    async def browse_folders(path: str = ""):
        """The folders in a folder under the media folder, for choosing a
        library's (never anything outside it)."""
        if len(path) > 1000 or "\x00" in path:
            raise HTTPException(404, "There’s no such folder in the media folder")
        try:
            found = await asyncio.wait_for(
                folderart.on_disk(_folders_in, ctx.settings.media_dir, path), DISK_WAIT_S
            )
        except TimeoutError:
            raise HTTPException(503, "The media folder isn’t answering right now") from None
        if found is None:
            raise HTTPException(404, "There’s no such folder in the media folder")
        plex, _ = await plex_libraries()
        found["inPlex"] = plex_overlaps([found["full"]], plex)
        return found

    @app.post("/api/folder-libraries", status_code=201)
    async def add_folder_library(body: FolderLibraryIn, request: Request):
        try:
            checked = await checked_folders(body.folders)
            lib = folders.add_library(body.name, body.kind, checked, checked=True)
        except NotFolder as e:
            raise HTTPException(400, str(e)) from None
        log.info(
            "Added the Media folder “%s” (%s) from %s%s",
            lib.name, "shows" if lib.kind == SHOW else "movies", ", ".join(lib.folders), who(request),
        )  # fmt: skip
        folders.scan_soon(lib.id)
        return next(x for x in folders.status() if x["key"] == lib.key)

    @app.put("/api/folder-libraries/{key}")
    async def change_folder_library(key: str, body: FolderLibraryChange, request: Request):
        try:
            folders.library(key)
            checked = await checked_folders(body.folders) if body.folders is not None else None
            lib = folders.change_library(key, body.name, checked, checked=True)
        except LibraryError:
            raise HTTPException(404, NOT_FOUND) from None
        except NotFolder as e:
            raise HTTPException(400, str(e)) from None
        log.info("Changed the Media folder “%s”%s", lib.name, who(request))
        if body.folders is not None:
            folders.scan_soon(lib.id)
        return next(x for x in folders.status() if x["key"] == lib.key)

    @app.delete("/api/folder-libraries/{key}", status_code=204)
    async def remove_folder_library(key: str, request: Request):
        try:
            lib = folders.remove_library(key)
        except LibraryError:
            raise HTTPException(404, NOT_FOUND) from None
        log.info("Removed the Media folder “%s”%s", lib.name, who(request))
        folders.changed([lib.id])

    @app.post("/api/folder-libraries/{key}/scan", status_code=202)
    async def scan_folder_library(key: str):
        try:
            lib = folders.library(key)
        except LibraryError:
            raise HTTPException(404, NOT_FOUND) from None
        folders.scan_soon(lib.id)
        return {"scanning": True}
