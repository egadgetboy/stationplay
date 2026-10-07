"""The permanent list of programs that failed to play.

Stored as a readable JSON file in the data folder so it doubles as a to-do
list. A program on the list is never attempted again; its slots are filled
by a replacement instead. Deleting an entry (in the web page, or by editing
the file) puts the program back into rotation.
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
    "Programs StationPlay skips because they failed to play or failed a file check. "
    "To put one back on the air, fix or replace its file, then delete its entry "
    "here (or choose Retry on the Broken files tab). StationPlay also rechecks "
    "this list on its own. An entry clears when Plex has the program again under "
    "a new key, when its file is missing (or it was removed from Plex) and no "
    "station has it anymore, when a new file for it passes the quick check, or "
    "when it now passes the quick check that took it off the air."
)

# How a problem was found: the quick check, the deep scan, opening the file
# to play it (it couldn't be found or opened), or playing it. What opening
# or the quick check found can be looked at again (a share may have been
# down); what the deep scan or playing found stays until the file changes.
CHECK, DEEP_SCAN, OPENING, PLAYING = "check", "deep scan", "opening", "playing"
FOUND_BY = (CHECK, DEEP_SCAN, OPENING, PLAYING)


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
        self._load()
        with self._lock:
            return rating_key in self._entries

    def keys(self) -> set[str]:
        self._load()
        with self._lock:
            return set(self._entries)

    def entries(self) -> list[dict[str, Any]]:
        self._load()
        with self._lock:
            return _sorted(self._entries.values())

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
    ) -> None:
        """Takes a program off the air. `problem` is "broken" (it won't play),
        "damaged" (it plays, but the picture or sound breaks up) or
        "unsupported" (it plays, but can't be shown right: see
        ff.DOLBY_VISION_ONLY); `found`, how (see FOUND_BY)."""
        self._load(force=True)
        with self._lock:
            existing = self._entries.get(item.rating_key, {})
            stations = set(existing.get("stations", []))
            if channel_number is not None:
                stations.add(channel_number)
            now = _now_iso()
            self._entries[item.rating_key] = {
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
            # (Replacing it with Sonarr or Radarr carries on: see replacing.py.)
            if existing.get("replace"):
                self._entries[item.rating_key]["replace"] = existing["replace"]
            self._write()
        log.warning(
            "%s is %s — %s. It stays off the air until it's cleared from the Broken files list",
            item.label,
            problem,
            redact(reason),
        )

    def remove(self, rating_key: str) -> bool:
        self._load(force=True)
        with self._lock:
            if self._entries.pop(rating_key, None) is None:
                return False
            self._write()
            return True

    def settle(
        self, seen: dict[str, Any], cleared: set[str], still: dict[str, dict[str, Any]]
    ) -> list[str]:
        """What going through the list again found, in one write: entries
        `cleared` come off it; those in `still` stay, with what's in it (a
        new reason, say) and when they were looked at. Only entries as they
        were when looked at (`seen`: their lastFailed, by key) are touched:
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
        by key: (the entry's lastFailed when looked at, its state; {} for
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
                    str(f["ratingKey"]): _upgrade_entry(f)
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
