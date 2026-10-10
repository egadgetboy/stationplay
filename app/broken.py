"""The permanent list of files that failed to play, or failed a check.

Stored as a readable JSON file in the data folder so it doubles as a to-do
list. A program on the list is never attempted again; its slots are filled
by a replacement instead. Deleting an entry (in the web page, or by editing
the file) puts the program back into rotation.

One entry per file, whoever plays it: a station, or Media in StationPlay's
apps. A file is known by its program's key, for the file a station plays
(its library's first version of it), and by its key and the version's ID
for any other version of it (see version_key): the same file is the same
entry for the stations and for Media.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .db import Item
from .ffmpeg import redact

log = logging.getLogger(__name__)

ABOUT = (
    "Files StationPlay skips, on the stations and in Media, because they failed to play or "
    "failed a file check. To put one back on the air, fix or replace its file, then delete "
    "its entry here (or choose Retry on the Broken files tab). StationPlay also rechecks "
    "this list on its own. An entry clears when Plex has the program again under a new key, "
    "when its file is missing (or it was removed from Plex) and neither a station nor Media "
    "has it anymore, when a new file for it passes the quick check, or when it now passes "
    "the quick check that took it off the air. An entry with a version is about that "
    "version of the program's file alone."
)

# How a problem was found: the quick check, the deep scan, opening the file
# to play it (it couldn't be found or opened), playing it, checking the
# stretch of it where someone had trouble (see scanner.Target), or a
# person's report that an Admin chose to have it replaced for. What opening
# or the quick check found can be looked at again (a share may have been
# down); the rest stays until the file changes.
CHECK, DEEP_SCAN, OPENING, PLAYING = "check", "deep scan", "opening", "playing"
TARGETED, REPORTED = "targeted check", "report"
FOUND_BY = (CHECK, DEEP_SCAN, OPENING, PLAYING, TARGETED, REPORTED)
# Found so that checking the same file again finds the same thing: it stays
# until the file changes.
STAYS = (DEEP_SCAN, PLAYING, TARGETED, REPORTED)


def version_key(rating_key: str, version: str = "") -> str:
    """A file's key on the list, and in the checks' records: its program's
    key for the file a station plays (the library's first version of it),
    and its key and the version's ID ("1234:5678") for any other."""
    return f"{rating_key}:{version}" if version else rating_key


def file_key(entry: dict[str, Any]) -> str:
    """An entry's file key (see version_key)."""
    return version_key(str(entry["ratingKey"]), str(entry.get("version") or ""))


def found_by(entry: dict[str, Any]) -> str:
    """How an entry's problem was found (entries from before 1.15.6 don't
    say: their reason does, for the checks; anything else was playing)."""
    how = entry.get("foundBy")
    if how in FOUND_BY:
        return str(how)
    reason = str(entry.get("reason", ""))
    if reason.startswith("Check: "):
        return CHECK
    if reason.startswith("Deep scan: "):
        return DEEP_SCAN
    return PLAYING


# How often the file is re-read to pick up hand edits.
RELOAD_INTERVAL_S = 15.0


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class BrokenFiles:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._mtime: float | None = None
        self._checked_at = 0.0
        self._load(force=True)

    # Reading -------------------------------------------------------------

    def is_broken(self, rating_key: str) -> bool:
        """Whether a program's file (as a station plays it) is on the list."""
        self._load()
        with self._lock:
            return rating_key in self._entries

    def keys(self) -> set[str]:
        """The file keys on the list (see version_key)."""
        self._load()
        with self._lock:
            return set(self._entries)

    def entries(self) -> list[dict[str, Any]]:
        self._load()
        with self._lock:
            return _sorted(self._entries.values())

    def entry(self, key: str) -> dict[str, Any] | None:
        """A file's entry (by its file key), if it's on the list."""
        self._load()
        with self._lock:
            found = self._entries.get(key)
            return dict(found) if found is not None else None

    # Writing -------------------------------------------------------------

    def record(
        self,
        item: Item,
        reason: str,
        channel_number: int | None,
        file_path: str | None = None,
        file_size: int | None = None,
        problem: str = "broken",
        found: str = PLAYING,
        version: str = "",
        library: str | None = None,
    ) -> None:
        """Takes a program's file off the air. `problem` is "broken" (it won't
        play), "damaged" (it plays, but the picture or sound breaks up) or
        "unsupported" (it plays, but can't be shown right: see
        ff.DOLBY_VISION_ONLY); `found`, how (see FOUND_BY); `version`, the
        version's ID, for one that isn't the program's first (see
        version_key); `library`, the library it's in, if that's known (what's
        in a library shared with the apps is in Media)."""
        key = version_key(item.rating_key, version)
        self._load(force=True)
        with self._lock:
            existing = self._entries.get(key, {})
            stations = set(existing.get("stations", []))
            if channel_number is not None:
                stations.add(channel_number)
            now = _now_iso()
            entry: dict[str, Any] = {
                "ratingKey": item.rating_key,
                "title": item.title,
                "show": item.show_title,
                "season": item.season,
                "episode": item.episode,
                "year": item.year,
                "file": file_path or existing.get("file") or item.file_path,
                "fileSize": file_size if file_size is not None else existing.get("fileSize"),
                "firstFailed": existing.get("firstFailed", now),
                "lastFailed": now,
                "failures": int(existing.get("failures", 0)) + 1,
                "reason": redact(reason)[:500],
                "problem": problem,
                "foundBy": found,
                "stations": sorted(stations),
            }
            if version:
                entry["version"] = version
            # (What replacing it with Sonarr needs, for a program no station has.)
            show_key = item.show_key or existing.get("showKey")
            if show_key:
                entry["showKey"] = show_key
            library = library or item.library or existing.get("library")
            if library:
                entry["library"] = str(library)
            # (Replacing it with Sonarr or Radarr carries on: see replacing.py.)
            if existing.get("replace"):
                entry["replace"] = existing["replace"]
            self._entries[key] = entry
            self._write()
        log.warning(
            "%s is %s — %s. It stays off the air until it's cleared from the Broken files list",
            item.label,
            problem,
            redact(reason),
        )

    def remove(self, key: str) -> bool:
        """Takes a file off the list (by its file key)."""
        self._load(force=True)
        with self._lock:
            if self._entries.pop(key, None) is None:
                return False
            self._write()
            return True

    def settle(
        self, seen: dict[str, Any], cleared: set[str], still: dict[str, dict[str, Any]]
    ) -> list[str]:
        """What going through the list again found, in one write: entries
        `cleared` come off it; those in `still` stay, with what's in it (a
        new reason, say) and when they were looked at. Only entries as they
        were when looked at (`seen`: their lastFailed, by file key) are touched:
        one that failed again meanwhile stays as it now is. Returns the keys
        taken off."""
        self._load(force=True)
        now = _now_iso()
        taken: list[str] = []
        with self._lock:
            for key, last_failed in seen.items():
                entry = self._entries.get(key)
                if entry is None or entry.get("lastFailed") != last_failed:
                    continue
                if key in cleared:
                    del self._entries[key]
                    taken.append(key)
                elif key in still:
                    self._entries[key] = {**entry, **still[key], "lastChecked": now}
            if taken or still:
                self._write()
        return taken

    def replacing(self, states: dict[str, tuple[Any, dict[str, Any]]]) -> None:
        """What replacing entries with Sonarr or Radarr is doing (replacing.py),
        by file key: (the entry's lastFailed when looked at, its state; {} for
        none). An entry that failed again meanwhile is left as it is."""
        self._load(force=True)
        with self._lock:
            touched = False
            for key, (last_failed, state) in states.items():
                entry = self._entries.get(key)
                if entry is None or entry.get("lastFailed") != last_failed:
                    continue
                entry = dict(entry)
                if state:
                    entry["replace"] = state
                else:
                    entry.pop("replace", None)
                self._entries[key] = entry
                touched = True
            if touched:
                self._write()

    # File handling -------------------------------------------------------

    def _write(self) -> None:
        doc = {"about": ABOUT, "files": _sorted(self._entries.values())}
        tmp = self.path.with_suffix(".json.tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime

    def _load(self, force: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            if not force and now - self._checked_at < RELOAD_INTERVAL_S:
                return
            self._checked_at = now
            try:
                mtime = self.path.stat().st_mtime
            except FileNotFoundError:
                # Deleting the whole file clears the list.
                self._entries = {}
                self._mtime = None
                return
            if mtime == self._mtime:
                return
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
                files = doc.get("files", []) if isinstance(doc, dict) else []
                self._entries = {
                    file_key(f): _upgrade_entry(f)
                    for f in files
                    if isinstance(f, dict) and f.get("ratingKey") is not None
                }
            except (OSError, ValueError) as e:
                # A typo while hand-editing shouldn't un-skip everything.
                log.error("Couldn't read %s (%s); keeping the previous list", self.path, e)
            self._mtime = mtime


def _sorted(entries: Any) -> list[dict[str, Any]]:
    return sorted(
        (dict(e) for e in entries),
        key=lambda e: (
            (e.get("show") or e.get("title") or "").lower(),
            e.get("season") or 0,
            e.get("episode") or 0,
        ),
    )


def _upgrade_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Entries written by older versions listed "channels"; now "stations"."""
    if "channels" in entry and "stations" not in entry:
        entry = dict(entry)
        entry["stations"] = entry.pop("channels")
    return entry
