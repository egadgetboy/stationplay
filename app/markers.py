"""Skipping intros and credits, using the markers Plex finds.

Plex works out where each episode's intro and each program's closing
credits are (its libraries' "Generate intro video markers" and "Generate
credits video markers" settings) and records them as markers. On a station
set to skip them, a program airs without them: whatever comes before the
intro (a cold open) plays, then the program carries on from the end of the
intro, and it ends where its final credits begin. Credits in the middle of
a program (a movie's credits with a scene after them) are skipped and the
scene still plays. This is what Plex's own players do with "Skip Intro" and
"Skip Credits".

The schedule uses each program's length without them, so the guide shows
when programs really start, and the next program follows straight on.

Markers are only trusted when they look right; otherwise the program plays
in full:
  * an intro must start in the first half of the program and be under five
    minutes long; credits must start in the second half;
  * skipping may not take away more than half of a program, or leave less
    than a minute of it;
  * scraps of under five seconds left between skipped parts (a logo before
    the intro, a second of black after the credits) are skipped too, so a
    program never flashes up for a moment.

Plex only includes markers when asked about one program at a time, so
they're asked for per program, and the answers are kept. A new answer is
checked again after six hours (Plex may not have got to a new episode yet,
or may still be working on a replaced file); each time it's the same, it's
trusted for longer, up to a week for programs with markers and three days
for programs without. A few programs Plex won't answer about don't hold a
station up: their last answer stands (or they play in full) until next time.
"""

from __future__ import annotations

import json
import logging
import time
import zlib
from dataclasses import dataclass, replace
from typing import Any

from .db import Database, Item, Segments
from .library import Library, LibraryError
from .plex import gather_all

log = logging.getLogger(__name__)

INTRO = "intro"
CREDITS = "credits"
# Markers shorter than this are ignored.
MIN_MARKER_MS = 2_000
MAX_INTRO_MS = 5 * 60_000
# Parts of a program shorter than this, left between skipped parts, are
# skipped as well.
MIN_KEEP_MS = 5_000
# Skipping never leaves a program shorter than this, or than this share of
# its full length.
MIN_PROGRAM_MS = 60_000
MIN_KEPT_SHARE = 0.5
# How long Plex's answer about a program's markers is trusted: at first
# FIRST_TTL_MS, then as long as it has already stayed the same, up to these.
FIRST_TTL_MS = 6 * 3600_000
FOUND_TTL_MS = 7 * 24 * 3600_000
NONE_TTL_MS = 3 * 24 * 3600_000
# Programs Plex won't answer about, per station check, before giving up on
# asking (Plex is probably down or restarting).
FAILURES_TOLERATED = 5
# Remembered markers of programs not asked about for this long are dropped.
FORGET_AFTER_MS = 60 * 24 * 3600_000
# Programs asked about at once (in parallel, within the Plex client's own
# limit), and saved, per batch.
BATCH = 200
# Parts of a program shorter than this aren't started (the rest of a part a
# viewer tuned in at its very end).
MIN_PIECE_S = 0.5


@dataclass(frozen=True)
class Marker:
    kind: str  # "intro" or "credits"
    start_ms: int
    end_ms: int
    final: bool = False  # the last credits: nothing worth keeping after them


def parse_markers(raw: list[dict[str, Any]] | None) -> list[Marker]:
    """Plex's intro and credits markers for one program."""
    out = []
    for m in raw or []:
        kind = str(m.get("type") or "")
        if kind not in (INTRO, CREDITS):
            continue  # commercials, bookmarks...
        try:
            start = int(m["startTimeOffset"])
            end = int(m["endTimeOffset"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(Marker(kind, start, end, _flag(m.get("final"))))
    return out


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true")
    return value is True or value == 1


def segments_for(duration_ms: int, markers: list[Marker]) -> Segments | None:
    """The parts of a program that air when its intro and credits are
    skipped, as (start, end) in ms; None if it plays in full."""
    half = duration_ms / 2
    skips: list[tuple[int, int]] = []
    for m in markers:
        start, end = max(0, m.start_ms), min(duration_ms, m.end_ms)
        if end - start < MIN_MARKER_MS:
            continue
        if m.kind == INTRO and start < half and end - start <= MAX_INTRO_MS:
            skips.append((start, end))
        elif m.kind == CREDITS and start >= half:
            skips.append((start, duration_ms if m.final else end))
    if not skips:
        return None
    kept: list[tuple[int, int]] = []
    pos = 0
    for start, end in sorted(skips):
        if start > pos:
            kept.append((pos, start))
        pos = max(pos, end)
    if pos < duration_ms:
        kept.append((pos, duration_ms))
    kept = [(a, b) for a, b in kept if b - a >= MIN_KEEP_MS]
    total = sum(b - a for a, b in kept)
    if total >= duration_ms or total < MIN_PROGRAM_MS or total < duration_ms * MIN_KEPT_SHARE:
        return None
    return tuple(kept)


def trimmed(item: Item, markers: list[Marker]) -> Item:
    """`item` (straight from Plex, at its full length) as it airs with its
    intro and credits skipped."""
    segments = segments_for(item.duration_ms, markers)
    if segments is None:
        return replace(item, segments=None)
    return replace(item, segments=segments, duration_ms=sum(b - a for a, b in segments))


def pieces(
    segments: Segments | None, offset_s: float, length_s: float
) -> list[tuple[float, float]]:
    """The stretches of the file to play, as (file position, length) in
    seconds, for `length_s` of a program starting `offset_s` into it (in the
    program's own time, which skips what isn't aired)."""
    if not segments:
        return [(offset_s, length_s)] if length_s > 0 else []
    out: list[tuple[float, float]] = []
    left = length_s
    program_s = 0.0  # where the current part starts, in program time
    for start_ms, end_ms in segments:
        part_s = (end_ms - start_ms) / 1000
        if offset_s < program_s + part_s and left > 0:
            into = max(0.0, offset_s - program_s)
            take = min(part_s - into, left)
            if take >= MIN_PIECE_S:
                out.append((start_ms / 1000 + into, take))
            left -= take  # time too short to start is covered as a gap
        program_s += part_s
    return out


def _encode(markers: list[Marker]) -> str:
    return json.dumps([[m.kind, m.start_ms, m.end_ms, m.final] for m in markers])


def _decode(text: str) -> list[Marker]:
    try:
        return [Marker(str(k), int(s), int(e), bool(f)) for k, s, e, f in json.loads(text)]
    except (TypeError, ValueError):
        return []


def now_ms() -> int:
    return int(time.time() * 1000)


def trust_ms(rating_key: str, found: bool, stable_ms: int) -> int:
    """How long an answer is trusted, given how long it had stayed the same
    when last confirmed. Spread out a little per program, so answers given
    together aren't all asked about again at once."""
    cap = FOUND_TTL_MS if found else NONE_TTL_MS
    base = min(cap, max(FIRST_TTL_MS, stable_ms))
    spread = (zlib.crc32(rating_key.encode()) % 1000) / 1000
    return int(base * (0.85 + 0.15 * spread))


class MarkerFinder:
    """Finds each program's markers in Plex, remembering the answers."""

    def __init__(self, db: Database, library: Library) -> None:
        self.db = db
        self.library = library

    async def markers(self, items: list[Item]) -> dict[str, list[Marker]]:
        """Each item's markers, asking Plex about those not known lately.
        Raises LibraryError if Plex can't be asked (more than a few programs
        fail, or the token is refused)."""
        now = now_ms()
        by_key = {i.rating_key: i for i in items}
        cached = self.db.cached_markers(list(by_key))
        known: dict[str, list[Marker]] = {}
        ask: list[Item] = []
        for key, item in by_key.items():
            row = cached.get(key)
            if row is not None and row.duration_ms == item.duration_ms:
                markers = _decode(row.markers)
                stable = row.checked_ms - row.first_ms
                if now - row.checked_ms < trust_ms(key, bool(markers), stable):
                    known[key] = markers
                    continue
            ask.append(item)
        failed: list[Item] = []

        async def ask_plex(item: Item) -> list[dict] | None:
            try:
                return await self.library.markers(item.rating_key)
            except LibraryError as e:
                failed.append(item)
                if e.status == 401 or len(failed) > FAILURES_TOLERATED:
                    raise
                return None  # this one waits for next time

        for start in range(0, len(ask), BATCH):
            batch = ask[start : start + BATCH]
            answers = await gather_all(ask_plex(i) for i in batch)
            checked = now_ms()
            rows = []
            for item, raw in zip(batch, answers, strict=True):
                key = item.rating_key
                row = cached.get(key)
                same_file = row is not None and row.duration_ms == item.duration_ms
                if raw is None:
                    # Plex wouldn't say. Its last answer about this file
                    # stands; with none, the program plays in full for now.
                    known[key] = _decode(row.markers) if row is not None and same_file else []
                    continue
                markers = parse_markers(raw)
                known[key] = markers
                text = _encode(markers)
                unchanged = row is not None and same_file and row.markers == text
                first = row.first_ms if unchanged and row is not None else checked
                rows.append((key, item.duration_ms, text, checked, first))
            # Saved batch by batch, so a Plex hiccup part-way loses little.
            self.db.save_markers(rows)
        if failed:
            log.warning(
                "Plex didn't answer about intros and credits for %d program%s (such as %s); "
                "asking again next time",
                len(failed),
                "" if len(failed) == 1 else "s",
                failed[0].label,
            )
        if ask:
            asked = len(ask) - len(failed)
            log.info(
                "Asked Plex about intros and credits for %d program%s (%d have them)",
                asked,
                "" if asked == 1 else "s",
                sum(1 for i in ask if known.get(i.rating_key)),
            )
        return known

    async def trim(self, items: list[Item]) -> list[Item]:
        """`items` as they air with intros and credits skipped."""
        known = await self.markers(items)
        return [trimmed(i, known.get(i.rating_key, [])) for i in items]

    def forget_old(self) -> None:
        self.db.forget_markers_before(now_ms() - FORGET_AFTER_MS)
