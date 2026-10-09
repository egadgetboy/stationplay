"""The per-channel streaming engine.

One broadcaster runs per channel while anyone is watching it. It walks the
channel's schedule, starting one ffmpeg process per program (or, with its
intro and credits skipped, one per part of it that airs), and stitches their
output into a single continuous MPEG-TS stream that every viewer of that
channel shares.

Safeguards, in the order they apply:
  * Programs on the broken list are never attempted; their slot goes to a
    replacement.
  * Each file is probed before playing. A file that won't open is marked
    broken and replaced immediately.
  * A program that stops partway (the process dies, stalls, or the file
    ends early) is resumed from where it stopped, twice, after a brief
    pause: a hiccup on the share or in Plex often clears by itself. If it
    still won't play it's marked broken, and the rest of its slot goes to a
    replacement that joins at the same offset, so it ends when the slot
    does and the guide stays right.
  * A commercial or trailer that won't play is left out from then on, and
    the Station ID card covers its time. The program before it is never
    blamed, and nothing is resumed: a break simply carries on.
  * If nothing can fill a slot, a plain card covers only the time left.
    If that happens two slots running, the card says the station is off
    the air, and it's logged as an error.
  * If the engine itself hits an unexpected error, it restarts while viewers
    are still connected, carrying on the same stream timeline. If it keeps
    failing, the station shows the off-air card for a while, then tries
    again.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import time
import zlib
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from . import ffmpeg as ff
from . import intro, playing, specials, subtitles, upnext
from .breaks import ID_CARD
from .broken import OPENING, PLAYING
from .config import Settings
from .db import Channel, Item
from .markers import pieces
from .replacement import pick_replacement
from .schedule import Slot, StationSchedule
from .sources import ResolvedSource
from .tsstitch import PTS_HZ, TsStitcher

if TYPE_CHECKING:
    from .main import AppContext

log = logging.getLogger(__name__)

# The stream timeline starts here rather than at zero, so ffmpeg never has
# to shift the first program's timestamps (which would misalign it with
# the programs after it).
TS_BASE_S = 10.0
# Where a program's earliest timestamp lands relative to the offset it was
# given (the MPEG-TS muxer's start delay, less AAC's lead-in). Measured from
# the stream as it plays; this is only the starting estimate.
DEFAULT_PTS_LEAD_TICKS = 126_000 - 1_920
# Space between one program's measured end and the next one's start: one
# AAC frame. Anything shorter is swallowed by decoders' sample counting and
# shows up as an audio timestamp going backwards.
JOIN_GAP_S = 0.025
# How far ahead of real time the stream aims to run. This cushion covers
# the second or so it takes to start the next program.
TARGET_LEAD_S = 10.0
# The most a program reads ahead at full speed as it starts: enough to build
# the cushion back after a stall of half a minute (a disk being reset, say),
# rather than carrying on with none till the next program.
MAX_BURST_S = 40.0
# A program counts as complete if it ends this close to where it should.
SHORTFALL_TOLERANCE_S = 3.0
# A commercial or trailer counts as complete if it ends this close to the
# end, at least (see _clip_tolerance).
CLIP_SHORTFALL_S = 1.0
# Leftover slot time shorter than this is skipped rather than started.
MIN_PLAY_S = 1.5
# Replacements tried for one slot before falling back to the card.
MAX_ATTEMPTS_PER_SLOT = 4
# A program that stops partway is resumed this many times, after these
# pauses, before it's marked broken and replaced.
RESUME_PAUSES_S = (1.0, 2.0)
# How long looking for a program's subtitle files may take (a slow share):
# without them, it plays without subtitles.
SUBTITLES_WAIT_S = 5.0
# After this many slots in a row that nothing could fill, the station is
# off the air.
OFF_AIR_AFTER_SLOTS = 2
# The engine failing this many times within ENGINE_FAILURE_WINDOW_S puts
# the station off the air for OFF_AIR_PAUSE_S, then it tries again.
ENGINE_FAILURES_TO_OFF_AIR = 3
ENGINE_FAILURE_WINDOW_S = 300.0
OFF_AIR_PAUSE_S = 120.0
# Programs are read at real-time speed, so frames arrive steadily; this long
# without a new one means the source is stuck (e.g. a hung NAS read).
STALL_TIMEOUT_S = 8.0
# How long a killed ffmpeg has to go before the stream carries on without it.
KILL_GRACE_S = 2.0
FIRST_FRAME_TIMEOUT_S = 20.0
# While a file is being located and opened (a spun-down drive can take 10+
# seconds to wake), the stream is kept fed with short black filler so no
# viewer's connection ever goes quiet.
PREP_GRACE_S = 2.5
KEEPALIVE_MARGIN_S = 2.0
FILLER_CHUNK_S = 3.0
# Files whose picture position (for 4:3 shows in widescreen frames) is known.
PICTURE_CACHE_SIZE = 5000
# How long drawing an Intro Bumper or Station ID card may take, at most,
# before a plain card is used.
DRAW_TIMEOUT_S = 10.0
# The Intro Bumper's length when StationPlay's stands in for your own video.
DEFAULT_INTRO_S = 5
# Tuning in from the beginning goes back at most this far (a longer program
# that began earlier is joined where it is): the schedule that far back is
# kept (updates.KEEP_PAST_MS), and so is Plex's guide (GUIDE_PAST_MS).
MOST_BEHIND_MS = 2 * 3600 * 1000
# How long a program waits for its Up Next Banner to be drawn before it
# plays without it: as long as the stream's cushion allows, between these.
# (It's drawn while the file is opened, so it's nearly always ready; and
# someone just tuning in, when there's no cushion yet, is waiting for the
# picture to start anyway.)
BANNER_WAIT_S = (1.0, 2.0)
# Recent output kept so a new viewer starts instantly.
RECENT_BYTES = 3 * 1024 * 1024
# Stream waiting for a viewer that has stopped reading, at most (about two
# minutes at the default quality) before it's disconnected.
VIEWER_MAX_BYTES = 64 * 1024 * 1024
# A station that has sent nothing at all for this long while someone is
# watching is stuck (normally something is sent every second or so, even
# while a file is slow to open); its engine is restarted.
ENGINE_SILENCE_S = 45.0
# A program joined less than this far in is said to start.
STARTS_S = 2.0
# The stream running less than this far ahead of real time means this
# server isn't converting the program as fast as it plays; that's logged.
LOW_LEAD_S = 1.0
# The stream counts as falling behind only if it hasn't gained this much on
# real time over the last LOSING_S (after a stall it's catching up, faster
# than real time: no cause for alarm).
LOSING_S = 10.0
GAINING_S = 0.5

SLATE_MESSAGE = "We’ll be right back"
OFF_AIR_MESSAGE = "This station is off the air. Please report it."


def now_ms() -> int:
    return int(time.time() * 1000)


class Viewer:
    """One connected client. Chunks are queued for it by the broadcaster.
    `counted`: whether its viewing counts in the stats as it ends (not the
    HLS stream StationPlay's apps share, whose apps count one by one: see
    hls.py). `client` and `agent`: where it's watching from, and its player
    (for the Stats tab's Watching now)."""

    def __init__(self, ident: str, counted: bool = True, client: str = "", agent: str = "") -> None:
        self.ident = ident
        self.counted = counted
        self.client = client
        self.agent = agent
        self.started_ms = now_ms()
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.queued_bytes = 0
        self.closed = False
        # Why StationPlay ended this viewer's stream, if it did.
        self.ended_because: str | None = None

    def push(self, chunk: bytes) -> None:
        if self.closed:
            return
        if self.queued_bytes + len(chunk) > VIEWER_MAX_BYTES:
            # A client this far behind is gone or stuck. Dropping it keeps
            # memory bounded and never slows the channel for anyone else.
            self.close(
                "its player stopped reading the stream "
                f"({self.queued_bytes / 1e6:.0f} MB waiting to be sent)"
            )
            return
        self.queued_bytes += len(chunk)
        self.queue.put_nowait(chunk)

    async def next_chunk(self) -> bytes | None:
        """The next piece of stream, or None when the stream has ended."""
        chunk = await self.queue.get()
        if chunk:
            self.queued_bytes -= len(chunk)
        return chunk

    def close(self, because: str | None = None) -> None:
        if self.closed:
            return
        self.closed = True
        self.ended_because = because
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queued_bytes = 0
        self.queue.put_nowait(None)


class EngineStuck(Exception):
    """The engine stopped sending anything while someone was watching."""


@dataclass
class PlayResult:
    produced_s: float
    completed: bool
    stopped: bool = False  # we killed it because the channel is shutting down
    stalled: bool = False
    reason: str = ""
    # Where the next program should start on the stream timeline; None if
    # nothing was output.
    next_ts: float | None = None
    # Failed on the GPU: the same program resumes on the CPU; the file
    # isn't blamed.
    gpu_retry: bool = False
    # Why the program couldn't play, if it couldn't.
    failure: Failure | None = None
    # What went wrong had the corner mark or the Up Next Banner over it.
    drawn_over: bool = False
    # ...or subtitles (which a file's own subtitle stream could upset at any
    # point, not just at the start).
    subtitled: bool = False


@dataclass
class Failure:
    reason: str
    plex_file: str | None = None
    size: int | None = None
    transient: bool = False  # not the file's fault (Plex or the share unreachable)
    # "broken" (it won't play), or "unsupported" (it would, but can't be
    # shown right: playing it again changes nothing, so it isn't tried again).
    problem: str = "broken"
    # It couldn't be found or opened (rather than failing as it played):
    # going through the broken-files list again looks at it again.
    opening: bool = False


@dataclass
class NowPlaying:
    slot_start_ms: int
    scheduled: Item
    playing: Item | None
    replaced: bool


@dataclass
class Broadcaster:
    ctx: AppContext
    channel_id: int
    viewers: set[Viewer] = field(default_factory=set)
    now_playing: NowPlaying | None = None
    started_at_ms: int = 0
    _task: asyncio.Task | None = None
    _stop_task: asyncio.Task | None = None
    _stopping: bool = False
    _proc: asyncio.subprocess.Process | None = None
    _recent: deque = field(default_factory=deque)
    _recent_bytes: int = 0
    # Items that failed for reasons that aren't the file's fault (Plex or
    # the share unreachable). Skipped for this viewing session only.
    _session_skip: set[str] = field(default_factory=set)
    # Programs that failed on the GPU this session; they play on the CPU.
    _cpu_only: set[str] = field(default_factory=set)
    # Of those, the ones that stalled (which may be the disk's doing).
    _stalled_on_gpu: set[str] = field(default_factory=set)
    # Programs that play with nothing drawn over them (no corner logo or Up
    # Next Banner) this session (see _run).
    _bare: set[str] = field(default_factory=set)
    _pts_lead: int = DEFAULT_PTS_LEAD_TICKS
    _session_start: int = 0
    # Where the stream has got to: its position on its own timeline, and
    # schedule time skipped without output (tiny leftovers at the end of a
    # slot, kept separate so the stream's timeline stays gapless). Kept
    # across engine restarts so viewers see one continuous stream.
    _ts: float = TS_BASE_S
    _skew_ms: int = 0
    _stitcher: TsStitcher = field(default_factory=TsStitcher)
    _unfilled_slots: int = 0
    _last_unfilled: int | None = None
    _crashes: dict[str, int] = field(default_factory=dict)
    off_air: bool = False
    # Reading ahead for the next program's subtitles (see _look_ahead).
    _looked_at: int | None = None
    _side_tasks: set[asyncio.Task] = field(default_factory=set)
    # Why: "failing" (its stream keeps failing to start) or "nothing" (nothing
    # on it could play: usually Plex or the media can't be reached).
    off_air_why: str = ""
    _name: str = ""
    _number: int | None = None
    # Where the program playing now is encoded (None while nothing is), and
    # the last program said in the log: its slot and file, and where it was
    # encoded (see _announce). Someone tuning in from the beginning: what
    # the log says about it, with the program it starts (see _back_to_start).
    encoder_now: ff.Encoder | None = None
    _announced: tuple[tuple[int, str], str] | None = None
    _joining: str = ""
    # When the stream last sent anything (time.monotonic()).
    _last_output: float = 0.0
    # Whether the stream has got its cushion ahead of real time this session
    # (at the start it has none, and builds it up in the first seconds).
    _cushion_built: bool = False
    # The Intro Bumper is still to play this session (it opens each one).
    _intro_due: bool = False
    # Someone has just tuned in and no program has played yet: for them, the
    # program they join starts here (a corner mark shown at the start of
    # programs shows from here).
    _tuned_in: bool = False
    # Tuning in from the beginning (the station's tune_in "start"): where on
    # the schedule the program they join begins, until the Intro Bumper
    # before it has played; and how far behind the schedule (and the guide)
    # this session runs for it.
    _start_at: int | None = None
    behind_ms: int = 0
    # The last Station ID card couldn't be shown (so a run of them going
    # wrong is a warning once, not one at every break).
    _ident_failing: bool = False
    # The stream's format this session: the station's picture size (see
    # ff.sized), set as it starts and the same until it stops, since
    # everything in one stream must be the same size. A new size waits for
    # the next session.
    _settings: Settings | None = None

    @property
    def settings(self) -> Settings:
        return self._settings or self.ctx.settings

    # Viewers -------------------------------------------------------------

    def subscribe(
        self, ident: str, *, counted: bool = True, client: str = "", agent: str = ""
    ) -> Viewer:
        viewer = Viewer(ident, counted, client, agent)
        for chunk in self._recent:
            viewer.push(chunk)
        self.viewers.add(viewer)
        if self._stop_task:
            self._stop_task.cancel()
            self._stop_task = None
        if self._task is None or self._task.done():
            self._stopping = False
            self._task = asyncio.create_task(self._supervise(), name=f"channel-{self.channel_id}")
        return viewer

    def unsubscribe(self, viewer: Viewer) -> None:
        viewer.close()
        self.viewers.discard(viewer)
        if not self.viewers and self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop_after_grace())
        if not viewer.counted:
            return
        try:
            # (Unless the station has been deleted meanwhile.)
            if self.ctx.db.get_channel(self.channel_id) is not None:
                station = self.ctx.station(self.channel_id)
                self.ctx.stats.record(
                    self.channel_id, station, viewer.started_ms, now_ms(), self.behind_ms
                )
        except Exception:
            # Statistics never get in the way of watching.
            log.exception("%s: couldn't record a viewing for its statistics", self._named())

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _stop_after_grace(self) -> None:
        try:
            await asyncio.sleep(self.settings.idle_grace_seconds)
        except asyncio.CancelledError:
            return
        if not self.viewers:
            await self.stop()

    async def stop(self, because: str = "the station stopped") -> None:
        self._stopping = True
        self._kill()
        for task in list(self._side_tasks):
            task.cancel()
        for viewer in list(self.viewers):
            viewer.close(because)
        self.viewers.clear()
        if self._task:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), 10)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self._recent.clear()
        self._recent_bytes = 0
        self.now_playing = None
        self.encoder_now = None

    def _kill(self) -> None:
        proc = self._proc
        if proc and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()

    def _emit(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._last_output = time.monotonic()
        self._recent.append(chunk)
        self._recent_bytes += len(chunk)
        while self._recent_bytes > RECENT_BYTES and len(self._recent) > 1:
            self._recent_bytes -= len(self._recent.popleft())
        for viewer in list(self.viewers):
            viewer.push(chunk)
            if viewer.closed:
                log.warning(
                    "%s: disconnecting viewer %s because %s",
                    self._named(),
                    viewer.ident,
                    viewer.ended_because,
                )
                self.viewers.discard(viewer)

    # The engine ------------------------------------------------------------

    async def _supervise(self) -> None:
        """Keeps the engine running for as long as anyone is watching."""
        self._new_session()
        failures: deque[float] = deque()
        try:
            while not self._stopping:
                try:
                    await self._run_watched()
                    return  # the station was deleted, or it's stopping
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("%s: its stream engine failed; restarting it", self._named())
                try:
                    await self._recover(failures)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # Even recovering failed. Never let that end the stream:
                    # wait a moment and start the engine again.
                    log.exception("%s: recovery failed; trying again", self._named())
                    await asyncio.sleep(2)
        finally:
            self._kill()
            if not self._stopping and self.viewers:
                # The engine ended with viewers still connected. Close their
                # connections, so their players notice now and tune again,
                # rather than waiting on a stream that has stopped.
                log.warning(
                    "The stream of %s ended; disconnecting its viewers",
                    playing.station(self._number, self._name, mid=True),
                )
                for viewer in list(self.viewers):
                    viewer.close("the station's stream ended")
                self.viewers.clear()

    async def _run_watched(self) -> None:
        """Runs the engine, restarting it if it ever sends nothing for
        ENGINE_SILENCE_S while someone is watching (stuck on something)."""
        self._last_output = time.monotonic()
        run = asyncio.create_task(self._run())
        try:
            while True:
                done, _ = await asyncio.wait({run}, timeout=5)
                if done:
                    return run.result()
                silent = time.monotonic() - self._last_output
                if self.viewers and not self._stopping and silent > ENGINE_SILENCE_S:
                    raise EngineStuck(f"the stream sent nothing for {silent:.0f}s")
        finally:
            if not run.done():
                run.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await run

    async def _recover(self, failures: deque[float]) -> None:
        """After the engine failed: carry on the stream, and if it keeps
        failing, go off the air for a while."""
        self._kill()
        self._carry_on_timeline()
        self._blame_program()
        now = time.monotonic()
        failures.append(now)
        while failures and now - failures[0] > ENGINE_FAILURE_WINDOW_S:
            failures.popleft()
        if len(failures) >= ENGINE_FAILURES_TO_OFF_AIR:
            log.error(
                "%s keeps failing and is OFF THE AIR. Trying again in %.0f minutes. "
                'Its viewers see: "%s"',
                self._named(mid=True),
                OFF_AIR_PAUSE_S / 60,
                OFF_AIR_MESSAGE,
            )
            await self._off_air_for(OFF_AIR_PAUSE_S)
            failures.clear()
        else:
            await asyncio.sleep(1)

    def _blame_program(self) -> None:
        """If the same program was playing each time the engine failed,
        skip it for the rest of this viewing session."""
        np = self.now_playing
        if np is None or np.playing is None:
            return
        key = np.playing.rating_key
        self._crashes[key] = self._crashes.get(key, 0) + 1
        if self._crashes[key] >= 2 and key not in self._session_skip:
            log.warning(
                "%s: %s keeps crashing the stream; skipping it for now",
                self._named(),
                np.playing.label,
            )
            self._session_skip.add(key)

    def _new_session(self) -> None:
        channel = self.ctx.db.get_channel(self.channel_id)
        picture = channel.picture if channel is not None else ff.STANDARD_PICTURE
        if channel is not None:
            self._number, self._name = channel.number, channel.name
        self._settings = ff.sized(self.ctx.settings, picture)
        self._session_skip = set()
        self._cpu_only = set()
        self._stalled_on_gpu = set()
        self._bare = set()
        self._pts_lead = DEFAULT_PTS_LEAD_TICKS
        self.started_at_ms = self._session_start = now_ms()
        self._ts = TS_BASE_S
        self._skew_ms = 0
        self._stitcher = TsStitcher()
        self._unfilled_slots = 0
        self._last_unfilled: int | None = None
        self._crashes = {}
        self.off_air = False
        self._cushion_built = False
        self._intro_due = True
        self._tuned_in = True
        self._start_at = None
        self.behind_ms = 0
        self._announced = None
        self._joining = ""

    def _named(self, mid: bool = False) -> str:
        """This station, starting a sentence: "Station 2, Cartoon Classics"
        (see playing.station; `mid`, followed by more of the sentence)."""
        return playing.cap(playing.station(self._number, self._name, mid=mid))

    def _carry_on_timeline(self) -> None:
        """After the engine failed mid-program, continue the stream's
        timeline after whatever it had already sent."""
        stitcher = self._stitcher
        stitcher.flush_partial()
        stitcher.end_segment()
        # Whatever was last sent began at the segment's offset, which may be
        # behind self._ts (a finished program) or ahead of it (filler).
        next_ts = self._next_ts(stitcher, stitcher.segment_offset_s, 0.0)
        if next_ts is not None:
            self._ts = max(self._ts, next_ts)
        stitcher.begin_segment(self._ts)

    async def _off_air_for(self, seconds: float) -> None:
        """Shows the off-air card for `seconds`, in pieces (its stream keeps
        failing)."""
        self.off_air, self.off_air_why = True, "failing"
        until = time.monotonic() + seconds
        while not self._stopping and time.monotonic() < until:
            result = await self._play_slate(
                30.0, self._ts, self._burst(), self._stitcher, self._name, OFF_AIR_MESSAGE
            )
            self._ts = _advance(self._ts, result)
            if not result.completed and not result.stopped:
                await asyncio.sleep(5)  # not even the card will play
        self.off_air = False

    def _burst(self) -> float:
        return self._burst_at(self._ts)

    def _burst_at(self, ts: float) -> float:
        """How much faster than real time to start reading, to get the
        stream's cushion back to TARGET_LEAD_S."""
        return max(0.0, min(MAX_BURST_S, TARGET_LEAD_S - self._lead_s(ts)))

    async def _run(self) -> None:
        stitcher = self._stitcher
        attempts: dict[int, int] = {}
        resumes: dict[tuple[int, str], int] = {}

        while not self._stopping:
            ts = self._ts
            cursor = self._cursor(ts)
            channel = self.ctx.db.get_channel(self.channel_id)
            if channel is None:
                log.info("%s was deleted; ending its stream", self._named(mid=True))
                return
            self._number, self._name = channel.number, channel.name
            station = self.ctx.station(self.channel_id)
            burst = self._burst()
            if self._intro_due:
                # Someone's just tuned in: the Intro Bumper first. The
                # schedule carries on underneath it (from the beginning:
                # moved back, so the bumper ends as the program begins).
                self._intro_due = False
                if channel.tune_in == "start":
                    await self._back_to_start(channel, station)
                    cursor = self._cursor(ts)
                if channel.has_intro:
                    result = None
                    if channel.intro_video:
                        result = await self._play_own_bumper(channel, ts, burst)
                    if result is None:
                        result = await self._play_intro(channel, station, ts, burst)
                    self._ts = _advance(ts, result)
                    if result.stopped:
                        return
                    if self._start_at is not None:
                        # Exactly at the program's beginning, however long
                        # the bumper turned out.
                        self._skew_ms += self._start_at - self._cursor(self._ts)
                    self._start_at = None
                    continue
                self._start_at = None
            slot = station.locate(cursor)

            if slot is None:
                # Empty station: show the card in short pieces so content
                # added later starts promptly.
                result = await self._play_slate(
                    10.0, ts, burst, stitcher, channel.name, "This station has no programs yet"
                )
                self._ts = _advance(ts, result)
                continue

            # The card before it (a Feature Presentation's), the program,
            # then whatever follows it (commercials or trailers, and the
            # Station ID card), all within the slot.
            program_start = slot.start_ms + slot.item.lead_ms
            if cursor < program_start:
                await self._play_lead(channel, slot, cursor, program_start)
                continue
            program_end = slot.start_ms + slot.item.program_end_ms
            if cursor >= program_end:
                await self._play_break(channel, station, slot, cursor, program_end)
                continue
            remaining_s = (program_end - cursor) / 1000
            if remaining_s < MIN_PLAY_S:
                self._skew_ms += program_end - cursor
                continue

            offset_s = (cursor - program_start) / 1000
            attempt = attempts.get(slot.start_ms, 0)
            attempts = {slot.start_ms: attempt}  # only the current slot matters

            item, replaced = self._choose(
                slot,
                functools.partial(self._stand_ins, channel, station, slot),
                offset_s,
                remaining_s,
                attempt,
                channel.number,
            )
            self.now_playing = NowPlaying(slot.start_ms, slot.item, item, replaced)

            if item is None or attempt >= MAX_ATTEMPTS_PER_SLOT:
                await self._cover_unfilled_slot(
                    channel.number, slot, remaining_s, burst, item is None
                )
                continue

            bare = item.rating_key in self._bare
            self._look_ahead(channel, station, slot)
            mark = None if bare else corner_mark(self.ctx, channel)
            up_next = None if bare else self._banner_for(channel, station, slot, mark)
            result = await self._play_item(
                item,
                offset_s,
                remaining_s,
                ts,
                burst,
                stitcher,
                channel.name,
                channel.aspect_mode,
                mark,
                mark_from_s=offset_s if self._tuned_in else 0.0,
                up_next=up_next,
                subtitles_mode="off" if bare or not self.ctx.subtitling else channel.subtitles,
            )
            if self._joining:
                # (Tuning in, but the program didn't start: said on its own.)
                log.info("%s: %s", self._named(), self._joining)
                self._joining = ""
            if result.produced_s:
                self._tuned_in = False
            self._ts = _advance(ts, result)
            if result.stopped:
                return
            if (
                result.drawn_over
                and not result.completed
                and not result.gpu_retry
                and (
                    result.subtitled
                    or (not result.produced_s and result.reason.startswith("ffmpeg failed"))
                )
            ):
                # Nothing came out, or anything went wrong with subtitles
                # drawn: perhaps the corner logo, the Up Next Banner or the
                # subtitles couldn't be drawn. Before anything counts against
                # the program, it's tried without them.
                log.warning(
                    "%s: %s %s; trying it again with nothing drawn over it",
                    self._named(),
                    item.label,
                    "stopped" if result.produced_s else "didn't start",
                )
                self._bare.add(item.rating_key)
                continue
            if result.completed:
                # The program is done. Whatever sliver of it is left over
                # (frame rounding) is skipped on the schedule, never replayed.
                now_cursor = self._cursor(self._ts)
                if now_cursor < program_end:
                    self._skew_ms += program_end - now_cursor
                continue
            if result.gpu_retry:
                continue  # the same program carries on, on the CPU
            failure = result.failure or Failure(result.reason or "ffmpeg failed")
            key = (slot.start_ms, item.rating_key)
            tries = resumes.get(key, 0)
            resumes = {key: tries}
            if tries < len(RESUME_PAUSES_S) and failure.problem == "broken":
                # Try to carry on with the same program from where it stopped.
                resumes[key] = tries + 1
                log.warning(
                    "%s: %s stopped — %s. Resuming it (attempt %d of %d)",
                    self._named(),
                    item.label,
                    failure.reason,
                    tries + 1,
                    len(RESUME_PAUSES_S),
                )
                await self._pause(RESUME_PAUSES_S[tries])
                continue
            # It won't play: skip it. It goes on the broken list (or is just
            # skipped for now, if it wasn't the file's fault), and the next
            # time round a replacement takes over from this point.
            transient = failure.transient
            if result.stalled:
                # A stall is usually the share hanging, not the file. Only a
                # file that stalls in two separate viewings is marked broken.
                count = self.ctx.stall_counts.get(item.rating_key, 0) + 1
                self.ctx.stall_counts[item.rating_key] = count
                transient = transient or count < 2
            self._fail(
                item,
                failure.reason,
                channel.number,
                failure.plex_file,
                failure.size,
                transient,
                failure.problem,
                failure.opening,
            )
            attempts[slot.start_ms] = attempt + 1

    # Between programs -----------------------------------------------------

    def _banner_for(
        self,
        channel: Channel,
        station: StationSchedule,
        slot: Slot,
        mark: ff.Watermark | None,
    ) -> upnext.UpNext | None:
        """The station's Up Next Banner for the end of `slot`'s program, if
        it has one and what's on next is known (on the corner logo `mark`,
        if that's where the banner goes)."""
        if not channel.up_next_seconds:
            return None
        heading, show, detail = self._up_next(station, slot)
        if not heading:
            return None
        following = station.locate(slot.end_ms)
        if following is not None and specials.starting(station, following) is not None:
            show = f"{show}: {detail}"  # "Leave It to Beaver Marathon: 3 episodes in a row"
        return station_banner(self.ctx, channel, show, mark, self.settings)

    async def _play_break(
        self, channel: Channel, station: StationSchedule, slot: Slot, cursor: int, program_end: int
    ) -> None:
        """Plays what's due at `cursor` in the break after a program: a
        commercial or trailer, or the Station ID card."""
        found = _clip_at(slot.item, program_end, cursor)
        if found is None:
            # Nothing's there (rounding at the very end of the slot).
            self._skew_ms += max(1, slot.end_ms - cursor)
            return
        path, start, end = found
        remaining_s = (end - cursor) / 1000
        if remaining_s < MIN_PLAY_S:
            self._skew_ms += end - cursor
            return
        self.now_playing = NowPlaying(slot.start_ms, slot.item, None, False)
        ts, burst = self._ts, self._burst()
        if self.off_air:
            result = await self._play_slate(
                remaining_s, ts, burst, self._stitcher, channel.name, OFF_AIR_MESSAGE
            )
        elif path == ID_CARD:
            logo = self.ctx.logos.path(channel.logo) if channel.logo else None
            up_next = self._up_next(station, slot)
            card = intro.Card(
                channel.name,
                channel.number,
                logo=str(logo) if logo else None,
                now=(up_next[0], up_next[1], up_next[2]),
                kind=intro.IDENT,
            )
            result = await self._play_card(channel, card, up_next, remaining_s, ts, burst)
        else:
            result = await self._play_clip(
                channel,
                station,
                slot,
                path,
                (cursor - start) / 1000,
                remaining_s,
                (end - start) / 1000,
                ts,
                burst,
            )
        self._ts = _advance(ts, result)
        if result.completed:
            now_cursor = self._cursor(self._ts)
            if now_cursor < end:
                self._skew_ms += end - now_cursor
        elif not result.stopped and result.next_ts is None:
            await asyncio.sleep(2)  # not even a card will play; don't spin

    async def _play_clip(
        self,
        channel: Channel,
        station: StationSchedule,
        slot: Slot,
        path: str,
        offset_s: float,
        remaining_s: float,
        length_s: float,
        ts: float,
        burst: float,
    ) -> PlayResult:
        """A commercial or trailer, `offset_s` into it, `length_s` long when
        it was scheduled. If it won't play, it's left out from then on and
        a plain card covers the rest of its time."""
        fillers = self.ctx.fillers
        if fillers.is_bad(path):
            return await self._play_plain_card(
                channel, self._up_next(station, slot), remaining_s, ts, burst
            )
        # Don't wait longer than the stream's cushion lasts for it to open.
        wait_s = max(PREP_GRACE_S, self._lead_s(ts) - KEEPALIVE_MARGIN_S)
        probe = await ff.probe(self.settings, path, timeout=wait_s)
        if not probe.ok or probe.dolby_vision_only:
            if not probe.timed_out:
                why = ff.dolby_vision_reason(probe) if probe.ok else probe.error
                fillers.mark_bad(path, why or "it can't be opened")
            return await self._play_plain_card(
                channel, self._up_next(station, slot), remaining_s, ts, burst
            )
        if probe.duration_s is not None and probe.duration_s < length_s - _clip_tolerance(length_s):
            # A different, shorter file under the same name.
            fillers.mark_bad(path, "it's shorter now than when it was found")
            return await self._play_plain_card(
                channel, self._up_next(station, slot), remaining_s, ts, burst
            )
        play_s = remaining_s
        if probe.duration_s is not None:
            play_s = min(play_s, probe.duration_s - offset_s)
        if play_s < MIN_PLAY_S:
            # Only the last moment of it is left (its length rounds a little
            # differently): nothing to show.
            return PlayResult(0.0, completed=True)
        gpu = self.ctx.gpu
        encoder = gpu.encoder_for(False) if gpu else ff.CPU
        result = await self._clip_part(channel, path, probe, offset_s, play_s, ts, burst, encoder)
        failed = _clip_failed(result, play_s)
        if failed and not result.stopped and gpu and encoder.is_gpu:
            # Maybe the GPU's fault, not the file's: the rest of it on the CPU.
            gpu.gpu_failed(result.reason or "it ended early")
            done = result.produced_s
            if play_s - done >= MIN_PLAY_S:
                after = _advance(ts, result)
                rest = await self._clip_part(
                    channel, path, probe, offset_s + done, play_s - done, after,
                    self._burst_at(after), ff.CPU,
                )  # fmt: skip
                failed = _clip_failed(rest, play_s - done)
                if not failed:
                    gpu.cpu_rescued()
                result = _joined(result, rest)
        if result.stopped:
            return result
        if failed:
            fillers.mark_bad(path, result.reason or "it ended early")
        left_s = remaining_s - result.produced_s
        if left_s < MIN_PLAY_S:
            result.completed = True
            return result
        # The card covers the rest, catching up on the stream's cushion.
        after = _advance(ts, result)
        card = await self._play_plain_card(
            channel, self._up_next(station, slot), left_s, after, self._burst_at(after)
        )
        return _joined(result, card)

    async def _clip_part(
        self,
        channel: Channel,
        path: str,
        probe: ff.ProbeResult,
        offset_s: float,
        play_s: float,
        ts: float,
        burst: float,
        encoder: ff.Encoder,
    ) -> PlayResult:
        args = ff.program_command(
            self.settings,
            path,
            offset_s,
            play_s,
            ts,
            burst,
            probe.audio_index,
            channel.name,
            encoder,
            source_aspect=probe.display_aspect,
            # Commercials are notoriously loud: every clip is evened out.
            normalize_audio=True,
            video_index=probe.video_index,
            tone_map=ff.to_sdr(probe) if self.ctx.tone_mapping else "",
        )
        first_frame_timeout = min(FIRST_FRAME_TIMEOUT_S, max(4.0, self._lead_s(ts) - 1.0))
        return await self._run_ffmpeg(
            args, self._stitcher, ts, first_frame_timeout=first_frame_timeout
        )

    async def _draw_card(self, card: intro.Card, folder: Path, timeout_s: float) -> bool:
        """Draws `card`'s pictures into `folder` (in the logo's colours), all
        within `timeout_s`. The folder's earlier pictures go first, so
        nothing from an earlier card (its logo, say) turns up on this one."""
        if not ff.usable_picture(str(folder)):
            return False
        started = time.monotonic()
        await asyncio.to_thread(_clear_card_folder, folder)
        try:
            colours = await asyncio.wait_for(intro.colours(self.settings, card.logo), timeout_s / 2)
        except TimeoutError:
            colours = intro.PLAIN_COLOURS
        left = timeout_s - (time.monotonic() - started)
        args = intro.stills_command(self.settings, card, colours, folder)
        return left > 0 and await _draw(args, folder, left)

    async def _back_to_start(self, channel: Channel, station: StationSchedule) -> None:
        """Tuning in from the beginning: the program on now (with the card
        before it, if it has one) starts from its beginning, right after the
        Intro Bumper, and the station carries on from there for as long as
        anyone's watching, that far behind its schedule. Not in the break
        after a program (the next one starts soon, from its beginning), nor
        for a program that began more than MOST_BEHIND_MS ago."""
        cursor = self._cursor(self._ts)
        slot = station.locate(cursor)
        if slot is None or cursor >= slot.start_ms + slot.item.program_end_ms:
            return
        bumper_ms = round(await self._intro_length(channel) * 1000) if channel.has_intro else 0
        back_ms = cursor - (slot.start_ms - bumper_ms)
        # (Said with the program, as it starts: see _announce.)
        if back_ms > MOST_BEHIND_MS:
            self._joining = (
                f"{slot.item.label} began more than {fmt_offset(MOST_BEHIND_MS / 1000)} ago, "
                "so joining it in progress"
            )
            return
        self._skew_ms -= back_ms
        self.behind_ms += back_ms
        self._start_at = slot.start_ms
        self._joining = (
            f"tuning in from the beginning of {slot.item.label}, "
            f"{fmt_offset(back_ms / 1000)} behind the guide"
        )

    async def _intro_length(self, channel: Channel) -> float:
        """How long the station's Intro Bumper plays, in seconds."""
        if channel.intro_video:
            bumper = await asyncio.to_thread(self.ctx.bumpers.get, channel.intro_video)
            if bumper is not None:
                return float(bumper.seconds)
        return float(channel.intro_seconds or DEFAULT_INTRO_S)

    async def _play_own_bumper(
        self, channel: Channel, ts: float, burst: float
    ) -> PlayResult | None:
        """The station's Intro Bumper when it's a video you uploaded; None if
        that's gone or won't play, so StationPlay's own plays instead. (It's
        a copy StationPlay made, so what's in it is known.)"""
        bumper = await asyncio.to_thread(self.ctx.bumpers.get, channel.intro_video)
        if bumper is None:
            log.warning(
                "%s: its Intro Bumper video is missing, so StationPlay's own bumper plays "
                "instead. Choose another video in the station's settings.",
                self._named(),
            )
            return None
        args = ff.program_command(
            self.settings,
            str(self.ctx.bumpers.path(bumper)),
            0.0,
            bumper.seconds,
            ts,
            burst,
            0,
            channel.name,
            source_aspect=bumper.width / bumper.height,
        )
        result = await self._run_ffmpeg(args, self._stitcher, ts, first_frame_timeout=15)
        if result.completed or result.stopped or result.next_ts is not None:
            return result
        log.warning(
            "%s: its Intro Bumper video %r wouldn't play, so StationPlay's own bumper plays "
            "instead",
            self._named(),
            bumper.name,
        )
        return None

    async def _play_intro(
        self, channel: Channel, station: StationSchedule, ts: float, burst: float
    ) -> PlayResult:
        """The Intro Bumper: the station's logo, name, description and what's
        on, over the sound of a TV's dial being flipped (unless its sound is
        off). If it can't be drawn, a plain card saying the same takes its
        place."""
        settings = self.settings
        length = float(channel.intro_seconds or DEFAULT_INTRO_S)
        logo = self.ctx.logos.path(channel.logo) if channel.logo else None
        card = intro.Card(
            channel.name,
            channel.number,
            channel.description,
            str(logo) if logo else None,
            self._whats_on(station, self._cursor(ts) + int(length * 1000)),
        )
        folder = settings.data_dir / "intro" / str(self.channel_id)
        # The show's own sound for the last third is looked for while the
        # card is drawn. Not when the program starts from its beginning after
        # it: that sound would be its first seconds, heard but not seen, so
        # the bumper keeps its own sound to the end.
        finding = asyncio.create_task(
            intro.find_show_audio(self.ctx, station, self._cursor(ts), length, self._skipped)
            if self._start_at is None
            else _nothing()
        )
        try:
            if await self._draw_card(card, folder, DRAW_TIMEOUT_S):
                show = await finding
                sound = intro.sound(int(length)) if channel.intro_sound else None
                how = intro.motion(length)
                # With the show's sound, then (if its file wouldn't play)
                # without it.
                for with_show in (show, None) if show else (None,):
                    args = intro.reel_command(
                        settings, length, ts, burst, channel.name, folder, sound, how, with_show
                    )
                    result = await self._run_ffmpeg(
                        args, self._stitcher, ts, first_frame_timeout=15
                    )
                    if result.completed or result.stopped or result.next_ts is not None:
                        return result
        except OSError as e:
            log.warning("%s: couldn't prepare its Intro Bumper (%s)", self._named(), e)
        finally:
            if not finding.done():
                finding.cancel()
        log.warning(
            "%s: its Intro Bumper couldn't be drawn; a plain card plays instead", self._named()
        )
        args = ff.card_command(
            settings,
            length,
            ts,
            burst,
            channel.name,
            str(logo) if logo else None,
            ["YOU\u2019RE TUNING IN TO", channel.name, channel.description],
        )
        result = await self._run_ffmpeg(args, self._stitcher, ts, first_frame_timeout=15)
        if not result.completed and not result.stopped and result.next_ts is None:
            return await self._play_slate(length, ts, burst, self._stitcher, channel.name, None)
        return result

    async def _play_lead(
        self, channel: Channel, slot: Slot, cursor: int, program_start: int
    ) -> None:
        """Plays what's due at `cursor` of the card before a program: the
        Feature Presentation card, saying which movie it is."""
        remaining_s = (program_start - cursor) / 1000
        if remaining_s < MIN_PLAY_S:
            self._skew_ms += program_start - cursor
            return
        self.now_playing = NowPlaying(slot.start_ms, slot.item, None, False)
        ts, burst = self._ts, self._burst()
        if self.off_air:
            result = await self._play_slate(
                remaining_s, ts, burst, self._stitcher, channel.name, OFF_AIR_MESSAGE
            )
        else:
            movie = slot.item
            # (If the movie won't play, another takes its place: it isn't named.)
            title, year = ("", "") if self._skipped(movie.rating_key) else intro.describe(movie)
            logo = self.ctx.logos.path(channel.logo) if channel.logo else None
            card = intro.Card(
                "Feature Presentation",
                channel.number,
                logo=str(logo) if logo else None,
                now=("", title, year),
                kind=intro.FEATURE,
            )
            lines = ["NOW SHOWING", "Feature Presentation", title]
            result = await self._play_card(channel, card, lines, remaining_s, ts, burst)
        self._ts = _advance(ts, result)
        if result.completed:
            now_cursor = self._cursor(self._ts)
            if now_cursor < program_start:
                self._skew_ms += program_start - now_cursor
        elif not result.stopped and result.next_ts is None:
            await asyncio.sleep(2)  # not even a card will play; don't spin

    async def _play_card(
        self,
        channel: Channel,
        card: intro.Card,
        plain: list[str],
        duration_s: float,
        ts: float,
        burst: float,
    ) -> PlayResult:
        """The Station ID card or the Feature Presentation card: the
        station's logo and name (or "Feature Presentation") and what's next,
        over a jingle (unless the Station ID card's sound is off). It's
        drawn while the stream's cushion lasts; if it can't be, a plain card
        saying `plain` plays."""
        what = "Feature Presentation card" if card.kind == intro.FEATURE else "Station ID card"
        folder = self.settings.data_dir / "ident" / str(self.channel_id)
        wait_s = min(DRAW_TIMEOUT_S, max(PREP_GRACE_S, self._lead_s(ts) - KEEPALIVE_MARGIN_S))
        problem = "couldn't be drawn in time"
        try:
            if await self._draw_card(card, folder, wait_s):
                args = intro.ident_command(
                    self.settings,
                    duration_s,
                    ts,
                    burst,
                    channel.name,
                    folder,
                    intro.jingle() if channel.id_sound else None,
                    intro.motion(duration_s),
                )
                result = await self._run_ffmpeg(args, self._stitcher, ts, first_frame_timeout=15)
                if result.completed or result.stopped or result.next_ts is not None:
                    self._ident_failing = False
                    return result
                problem = "wouldn't play"
        except OSError as e:
            problem = f"couldn't be drawn ({e})"
        log.log(
            logging.INFO if self._ident_failing else logging.WARNING,
            "%s: its %s %s; a plain card plays instead",
            self._named(),
            what,
            problem,
        )
        self._ident_failing = True
        return await self._play_plain_card(channel, plain, duration_s, ts, burst)

    def _whats_on(self, station: StationSchedule, at_ms: int) -> tuple[str, str, str]:
        """For the Intro Bumper: what's on as it ends (nothing, if that
        program is being skipped)."""
        lines, key = intro.whats_on(station, at_ms)
        return ("", "", "") if key and self._skipped(key) else lines

    async def _play_plain_card(
        self,
        channel: Channel,
        lines: list[str],
        duration_s: float,
        ts: float,
        burst: float,
    ) -> PlayResult:
        """A plain card: the station's logo and `lines` (what's up next),
        drawn simply. It covers a commercial or trailer that won't play, and
        a Station ID or Feature Presentation card that couldn't be drawn."""
        logo = self.ctx.logos.path(channel.logo) if channel.logo else None
        args = ff.card_command(
            self.settings,
            duration_s,
            ts,
            burst,
            channel.name,
            str(logo) if logo else None,
            lines,
        )
        result = await self._run_ffmpeg(args, self._stitcher, ts, first_frame_timeout=15)
        if not result.completed and not result.stopped and result.next_ts is None:
            # The card couldn't be drawn (fonts missing?): a plain one works.
            return await self._play_slate(duration_s, ts, burst, self._stitcher, channel.name, None)
        return result

    def _up_next(self, station: StationSchedule, slot: Slot) -> list[str]:
        """What a card says is on after `slot`: a heading, the show and the
        episode (or the movie and its year; or a special starting, and what
        it is: see specials.starting); "Stay tuned" if that isn't known or
        is being skipped."""
        following = station.locate(slot.end_ms)
        if following is None:
            return ["", "Stay tuned", ""]
        skipped = self._skipped(following.item.rating_key)
        special = specials.starting(station, following)
        if special is not None:
            # (Not naming a program that won't play: another takes its place.)
            return ["UP NEXT", special[0], "" if skipped else special[1]]
        if skipped:
            return ["", "Stay tuned", ""]
        return ["UP NEXT", *intro.describe(following.item)]

    async def _cover_unfilled_slot(
        self, number: int, slot: Slot, remaining_s: float, burst: float, nothing_fits: bool
    ) -> None:
        """Shows the card for the rest of a slot nothing could fill."""
        if slot.start_ms != self._last_unfilled:
            self._unfilled_slots += 1
            self._last_unfilled = slot.start_ms
        if self._unfilled_slots >= OFF_AIR_AFTER_SLOTS:
            if not self.off_air:
                log.error(
                    "%s is OFF THE AIR: nothing on it could play for %d programs in a row. "
                    "Check the Broken files tab, and make sure Plex and your media can be "
                    'reached. Its viewers see: "%s"',
                    self._named(mid=True),
                    self._unfilled_slots,
                    OFF_AIR_MESSAGE,
                )
            self.off_air, self.off_air_why = True, "nothing"
        elif nothing_fits:
            log.warning(
                "%s: nothing can fill the rest of %s's time slot; showing a card instead",
                self._named(),
                slot.item.label,
            )
        message = OFF_AIR_MESSAGE if self.off_air else SLATE_MESSAGE
        result = await self._play_slate(
            remaining_s, self._ts, burst, self._stitcher, self._name, message
        )
        self._ts = _advance(self._ts, result)
        if not result.completed and not result.stopped:
            # Even the card failed (ffmpeg missing?). Back off rather than
            # spin, and try again.
            await asyncio.sleep(2)

    async def _pause(self, seconds: float) -> None:
        """A short wait before trying again, never so long that the stream's
        cushion runs out."""
        await asyncio.sleep(max(0.0, min(seconds, self._lead_s(self._ts) - 3.0)))

    def _stand_ins(
        self, channel: Channel, station: StationSchedule, slot: Slot
    ) -> list[list[Item]]:
        """What can take the place of `slot`'s program if it can't play,
        best first: a block's own programs, or the movies a Feature
        Presentation picks from; then the station's."""
        own = station.items_for(slot)
        kind = (station.special(slot) or {}).get("kind")
        if kind == specials.BLOCK:
            return [station.era_of(slot).items, own]
        if kind == specials.FEATURE:
            return [specials.feature_movies(self.ctx.db, channel, own, set()), own]
        return [own]

    def _choose(
        self,
        slot: Slot,
        stand_ins: Callable[[], list[list[Item]]],
        offset_s: float,
        remaining_s: float,
        attempt: int,
        number: int,
    ) -> tuple[Item | None, bool]:
        item = slot.item
        if not self._skipped(item.rating_key):
            return item, False
        required_ms = int((offset_s + remaining_s) * 1000)
        seed = zlib.crc32(f"{self.channel_id}:{slot.start_ms}:{attempt}".encode())
        excluded = self.ctx.broken.keys() | self._session_skip
        replacement = None
        for pool in stand_ins():
            replacement = pick_replacement(pool, item, required_ms, excluded, seed)
            if replacement is not None:
                break
        if replacement:
            log.info(
                "%s: %s can't play, so %s plays in its place from %s into the time slot",
                self._named(),
                item.label,
                replacement.label,
                fmt_offset(offset_s),
            )
        return replacement, True

    def _skipped(self, rating_key: str) -> bool:
        return rating_key in self._session_skip or self.ctx.broken.is_broken(rating_key)

    async def _subtitles(
        self, mode: str, source: str, probe: ff.ProbeResult, wait_s: float = SUBTITLES_WAIT_S
    ) -> ff.Subtitles | None:
        """The subtitles a program gets on a station set to `mode` (see
        subtitles.py), worked out within `wait_s`; None if none (or they
        can't be had in time: it plays without)."""
        if mode == "off":
            return None
        deadline = time.monotonic() + wait_s
        try:
            chosen = await asyncio.wait_for(
                asyncio.to_thread(
                    subtitles.for_program,
                    self.settings.data_dir,
                    mode,
                    self.settings.preferred_audio_language,
                    source,
                    probe,
                ),
                wait_s,
            )
            if not isinstance(chosen, subtitles.Extraction):
                return chosen
            # Text subtitles in the file: read out first (usually done
            # already, while the program before played: see _look_ahead).
            task = subtitles.extract(self.settings, chosen)
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError
            ready = await asyncio.wait_for(asyncio.shield(task), left)
            return chosen.ready() if ready else None
        except TimeoutError:
            log.info(
                "%s: this program's subtitles aren't ready yet; it plays without them this time",
                self._named(),
            )
            return None
        except Exception as e:  # (subtitles are never worth a program not playing)
            log.warning("%s: playing without subtitles this time (%s)", self._named(), e)
            return None

    def _look_ahead(self, channel: Channel, station: StationSchedule, slot: Slot) -> None:
        """While `slot`'s program plays, reads the next program's subtitles
        out of its file, if it has text subtitles in it (see subtitles.py),
        so they're ready when it starts."""
        if (
            channel.subtitles == "off"
            or not self.ctx.subtitling
            or self._looked_at == slot.start_ms
        ):
            return
        self._looked_at = slot.start_ms
        following = station.locate(slot.end_ms)
        if following is None or self._skipped(following.item.rating_key):
            return

        async def read_ahead(item: Item, mode: str) -> None:
            try:
                resolved = await self.ctx.resolve_source(item)
                if resolved.error or not resolved.source:
                    return
                probe = await ff.probe(self.settings, resolved.source)
                if not probe.ok:
                    return
                chosen = await asyncio.to_thread(
                    subtitles.for_program,
                    self.settings.data_dir,
                    mode,
                    self.settings.preferred_audio_language,
                    resolved.source,
                    probe,
                )
                if isinstance(chosen, subtitles.Extraction):
                    # (Shared: a station stopping doesn't stop it.)
                    await asyncio.shield(subtitles.extract(self.settings, chosen))
            except Exception as e:  # (only ever a head start)
                log.debug("Reading ahead for %s's subtitles: %s", item.label, e)

        task = asyncio.create_task(read_ahead(following.item, channel.subtitles))
        self._side_tasks.add(task)
        task.add_done_callback(self._side_tasks.discard)

    def _kept(self, item: Item, resolved: ResolvedSource) -> bool:
        """Whether you put this program's file back on the air (Retry on the
        Broken files tab) after it was taken off for something its file is."""
        record = self.ctx.db.scan(item.rating_key)
        return (
            record is not None
            and record.kept
            and record.file == (resolved.plex_file or resolved.source)
        )

    def _fail(
        self,
        item: Item,
        reason: str,
        channel_number: int,
        plex_file: str | None,
        size: int | None,
        transient: bool = False,
        problem: str = "broken",
        opening: bool = False,
    ) -> None:
        """Takes an item out of rotation after it failed to play (or couldn't
        be found or opened, `opening`)."""
        if transient:
            log.warning("Skipping %s for now: %s", item.label, reason)
            self._session_skip.add(item.rating_key)
            return
        self.ctx.broken.record(
            item,
            reason,
            channel_number,
            plex_file,
            size,
            problem=problem,
            found=OPENING if opening else PLAYING,
        )

    async def _play_item(
        self,
        item: Item,
        offset_s: float,
        remaining_s: float,
        ts: float,
        burst: float,
        stitcher: TsStitcher,
        channel_name: str,
        aspect_mode: str = "fit",
        watermark: ff.Watermark | None = None,
        mark_from_s: float = 0.0,
        up_next: upnext.UpNext | None = None,
        subtitles_mode: str = "off",
    ) -> PlayResult:
        """Plays `remaining_s` of a program from `offset_s` into it. A corner
        mark shown only at the start of programs counts from `mark_from_s`
        into it: its start, or where someone just tuned in. The Up Next
        Banner, if there is one, is shown upnext.BEFORE_END_S before the
        program ends, if that's in what's played; it's drawn meanwhile."""
        drawing = None
        due_s = offset_s + remaining_s - upnext.BEFORE_END_S
        if up_next is not None and due_s >= offset_s:
            drawn_as = self.settings.data_dir / "upnext" / f"{self.channel_id}.png"
            drawing = upnext.Drawing(self.settings, up_next, due_s, drawn_as, DRAW_TIMEOUT_S)
        try:
            return await self._play_program(
                item,
                offset_s,
                remaining_s,
                ts,
                burst,
                stitcher,
                channel_name,
                aspect_mode,
                watermark,
                mark_from_s,
                drawing,
                subtitles_mode,
            )
        finally:
            if drawing is not None:
                await drawing.close()

    async def _play_program(
        self,
        item: Item,
        offset_s: float,
        remaining_s: float,
        ts: float,
        burst: float,
        stitcher: TsStitcher,
        channel_name: str,
        aspect_mode: str,
        watermark: ff.Watermark | None,
        mark_from_s: float,
        drawing: upnext.Drawing | None,
        subtitles_mode: str = "off",
    ) -> PlayResult:
        """_play_item's work: the program's file opened, then played in parts."""
        # Locate and open the file, keeping the stream fed if that's slow.
        prep = asyncio.create_task(self._prepare(item, aspect_mode))
        filler_ts: float | None = None
        try:
            while True:
                wait_s = max(PREP_GRACE_S, self._lead_s(ts) - KEEPALIVE_MARGIN_S)
                try:
                    resolved, probe, picture = await asyncio.wait_for(asyncio.shield(prep), wait_s)
                    break
                except TimeoutError:
                    pass
                chunk = min(FILLER_CHUNK_S, remaining_s)
                if self._stopping or chunk < MIN_PLAY_S:
                    # Shutting down, or the slot ran out while we waited.
                    return PlayResult(
                        0.0, completed=not self._stopping, stopped=self._stopping, next_ts=filler_ts
                    )
                log.info(
                    "Still opening %s; filling %.0fs to keep the stream going", item.label, chunk
                )
                filler = await self._play_slate(chunk, ts, chunk, stitcher, channel_name, None)
                if filler.next_ts is not None:
                    filled = filler.next_ts - ts
                    ts = filler_ts = filler.next_ts
                    offset_s += filled
                    remaining_s -= filled
                if filler.stopped:
                    return PlayResult(0.0, completed=False, stopped=True, next_ts=filler_ts)
                burst = 0.0
        finally:
            if not prep.done():
                prep.cancel()

        if resolved.error or not resolved.source:
            reason = resolved.error or "file not found"
            return PlayResult(
                0.0,
                completed=False,
                reason=reason,
                next_ts=filler_ts,
                failure=Failure(
                    reason, resolved.plex_file, resolved.size, resolved.transient, opening=True
                ),
            )
        assert probe is not None
        if not probe.ok:
            reason = probe.error or "can't open the file"
            return PlayResult(
                0.0,
                completed=False,
                reason=reason,
                next_ts=filler_ts,
                failure=Failure(
                    reason, resolved.plex_file, resolved.size, probe.timed_out, opening=True
                ),
            )
        if probe.dolby_vision_only and not self._kept(item, resolved):
            reason = ff.dolby_vision_reason(probe)
            return PlayResult(
                0.0,
                completed=False,
                reason=reason,
                next_ts=filler_ts,
                failure=Failure(reason, resolved.plex_file, resolved.size, problem="unsupported"),
            )
        # (Not waiting for them longer than the stream's cushion allows.)
        subs_wait = min(SUBTITLES_WAIT_S, max(1.0, self._lead_s(ts) - KEEPALIVE_MARGIN_S - 1.0))
        subs = await self._subtitles(subtitles_mode, resolved.source, probe, subs_wait)

        # The stretches of the file to play: one, or with intros and credits
        # skipped, the parts that air, each joined straight onto the last.
        plan = pieces(item.segments, offset_s, remaining_s)
        gpu = self.ctx.gpu
        encoder = gpu.encoder_for(item.rating_key in self._cpu_only) if gpu else ff.CPU
        self._announce(item, offset_s, resolved, probe, subs, encoder)
        # What was sent for this program altogether, across its parts.
        total = PlayResult(0.0, completed=True, next_ts=filler_ts)
        piece_ts = ts
        played = False
        aired = offset_s  # how far into the program each part starts
        for n, (start_s, play_s) in enumerate(plan):
            mark = _mark_from(watermark, aired - mark_from_s)
            if mark and mark.clock:
                # The clock tells the time this part starts airing.
                mark = replace(mark, clock_at_s=self._cursor(piece_ts) / 1000)
            part_from_s = aired
            aired += play_s
            if probe.duration_s is not None:
                available = probe.duration_s - start_s
                if available < MIN_PLAY_S:
                    # The file ends before this (it's a little shorter than
                    # Plex recorded). Nothing wrong with the file; the rest
                    # of the slot is covered below.
                    break
                play_s = min(play_s, available)
            banner = None
            if drawing is not None:
                least, most = BANNER_WAIT_S
                wait_s = max(least, min(most, self._lead_s(piece_ts) - KEEPALIVE_MARGIN_S))
                banner = await drawing.for_part(part_from_s, play_s, wait_s)
            if n:
                burst = self._burst_at(piece_ts)
            args = ff.program_command(
                self.settings,
                resolved.source,
                start_s,
                play_s,
                piece_ts,
                burst,
                probe.audio_index,
                channel_name,
                encoder,
                aspect_mode=aspect_mode,
                source_aspect=picture[0] * probe.sar / picture[1]
                if picture
                else probe.display_aspect,
                # Episodes are brought to one loudness so volume doesn't jump
                # between them; movies keep their original sound.
                normalize_audio=item.kind == "episode",
                picture=picture,
                video_index=probe.video_index,
                watermark=mark,
                banner=banner,
                tone_map=ff.to_sdr(probe) if self.ctx.tone_mapping else "",
                subtitles=subs,
            )
            # Don't wait for a first frame longer than the stream's cushion lasts.
            first_frame_timeout = min(FIRST_FRAME_TIMEOUT_S, max(4.0, self._lead_s(piece_ts) - 1.0))
            result = await self._run_ffmpeg(
                args,
                stitcher,
                piece_ts,
                first_frame_timeout=first_frame_timeout,
                on_air=True,
                what=f"{item.label} ({encoder.label})",
            )
            played = True
            total.produced_s += result.produced_s
            if result.next_ts is not None:
                total.next_ts = result.next_ts
            if result.stopped:
                total.completed = False
                total.stopped = True
                return total

            short = result.produced_s < play_s - SHORTFALL_TOLERANCE_S
            whole = played_whole(start_s + result.produced_s, probe.duration_s)
            if result.completed and short and whole:
                break  # the file's whole; the rest of the slot is covered below
            if result.completed and not short:
                piece_ts = _advance(piece_ts, result)
                continue

            total.completed = False
            total.stalled = result.stalled
            total.reason = result.reason
            total.drawn_over = mark is not None or banner is not None or subs is not None
            total.subtitled = subs is not None
            if gpu and encoder.is_gpu and subs is None:
                # Whatever went wrong may be the GPU's fault rather than the
                # file's. Carry on with this same program on the CPU from
                # where it stopped; only a failure there counts against it.
                # (With subtitles drawn, it's first tried without them, on
                # the GPU: see _run.) A stall may as well be the disk's (a
                # read held up), so it never counts against the GPU.
                gpu.gpu_failed(result.reason or "ended early", stalled=result.stalled)
                if result.stalled:
                    self._stalled_on_gpu.add(item.rating_key)
                self._cpu_only.add(item.rating_key)
                total.gpu_retry = True
                return total
            reason = result.reason or "ffmpeg failed"
            if result.completed and short:
                reason = (
                    f"the file ended at {fmt_offset(start_s + result.produced_s)} "
                    f"of {fmt_offset(start_s + play_s)} (it may be cut short or damaged)"
                )
            total.reason = reason
            total.failure = Failure(reason, resolved.plex_file, resolved.size)
            return total

        if played and gpu and encoder.is_gpu:
            gpu.gpu_succeeded()
        elif played and gpu and item.rating_key in self._cpu_only:
            if item.rating_key not in self._stalled_on_gpu:
                gpu.cpu_rescued()
            self._cpu_only.discard(item.rating_key)
            self._stalled_on_gpu.discard(item.rating_key)
        # Finished. If the file is a little shorter than its slot, cover the
        # leftover so the next program starts on time.
        return await self._fill_gap(
            remaining_s - total.produced_s, ts, stitcher, channel_name, total
        )

    def _announce(
        self,
        item: Item,
        offset_s: float,
        resolved: ResolvedSource,
        probe: ff.ProbeResult,
        subs: ff.Subtitles | None,
        encoder: ff.Encoder,
    ) -> None:
        """Says in the log what's starting to play (once for each program,
        and again only if it moves to the CPU): its file, its picture and
        sound, and how the station makes it. Someone tuning in from the
        beginning is said with it."""
        self.encoder_now = encoder
        np = self.now_playing
        key = (np.slot_start_ms if np else 0, item.rating_key)
        last = self._announced
        again = last is not None and last[0] == key
        if last is not None and again and last[1] == encoder.kind:
            return
        self._announced = (key, encoder.kind)
        if self._joining and np is not None and np.replaced:
            # (Not the program the tuning in was about: another took its place.)
            log.info("%s: %s", self._named(), self._joining)
            self._joining = ""
        if self._joining:
            what = self._joining
        elif again:
            what = f"{item.label} carries on from {fmt_offset(offset_s)}"
        elif offset_s >= STARTS_S:
            what = (
                f"joining {item.label} {fmt_offset(offset_s)} in"
                if self._tuned_in
                else f"{item.label} plays from {fmt_offset(offset_s)}"
            )
        else:
            what = f"{item.label} starts"
        self._joining = ""
        made = [
            f"made {playing.size(self.settings.video_height)} at "
            f"{playing.mbps(self.settings.video_bitrate_kbps)} on {playing.encoder_name(encoder)}"
        ]
        if probe.hdr and self.ctx.tone_mapping:
            made.append("HDR made ordinary")
        if subs is not None:
            made.append("subtitles drawn in")
        log.info(
            "%s: %s (%s: %s), %s",
            self._named(),
            what,
            playing.file_name(resolved.plex_file or resolved.source or ""),
            playing.picture_and_sound(
                probe.width,
                probe.height,
                probe.video_codec,
                playing.hdr_name(probe.hdr, probe.dolby_vision),
                probe.audio_channels,
                probe.audio_codec,
            ),
            ", ".join(made),
        )

    async def _fill_gap(
        self, gap_s: float, ts: float, stitcher: TsStitcher, channel_name: str, result: PlayResult
    ) -> PlayResult:
        """Plays black for the rest of a slot after a program ends early."""
        if gap_s < MIN_PLAY_S:
            return result  # too small to bother; the schedule absorbs it
        slate = await self._play_slate(
            gap_s, _advance(ts, result), 0.0, stitcher, channel_name, None
        )
        result.produced_s += slate.produced_s
        result.next_ts = _advance(_advance(ts, result), slate)
        result.stopped = slate.stopped
        return result

    async def _prepare(
        self, item: Item, aspect_mode: str
    ) -> tuple[ResolvedSource, ff.ProbeResult | None, tuple[int, int, int, int] | None]:
        resolved = await self.ctx.resolve_source(item)
        if resolved.error or not resolved.source:
            return resolved, None, None
        probe = await ff.probe(self.settings, resolved.source)
        picture = None
        if aspect_mode != "fit" and probe.ok and (probe.display_aspect or 0) >= ff.BOXED_MAX_ASPECT:
            # A widescreen file may still be a 4:3 show with black bars
            # baked in; zoom and stretch need to know where the picture is.
            picture = await self._find_picture(resolved.source, probe)
        return resolved, probe, picture

    async def _find_picture(
        self, source: str, probe: ff.ProbeResult
    ) -> tuple[int, int, int, int] | None:
        key = f"{source}|{probe.width}x{probe.height}|{probe.duration_s}"
        cache = self.ctx.pictures
        if key not in cache:
            try:
                found = await ff.find_picture(self.settings, source, probe)
            except ff.PictureUnknown:
                return None  # play it as it is this time; look again next time
            if len(cache) >= PICTURE_CACHE_SIZE:
                cache.pop(next(iter(cache)))
            cache[key] = found
            if found:
                log.info(
                    "%s is a %dx%d picture with black bars baked in",
                    ff.redact(source),
                    found[0],
                    found[1],
                )
        return cache[key]

    def _cursor(self, ts: float) -> int:
        """The moment on the schedule that stream position `ts` stands for."""
        return self._session_start + int((ts - TS_BASE_S) * 1000) + self._skew_ms

    def _lead_s(self, ts: float) -> float:
        """How far the stream is ahead of real time at stream position `ts`."""
        return (self._session_start + (ts - TS_BASE_S) * 1000 - now_ms()) / 1000

    async def _play_slate(
        self,
        duration_s: float,
        ts: float,
        burst: float,
        stitcher: TsStitcher,
        channel_name: str,
        message: str | None,
    ) -> PlayResult:
        args = ff.slate_command(self.settings, duration_s, ts, burst, channel_name, message)
        result = await self._run_ffmpeg(args, stitcher, ts, first_frame_timeout=15)
        if not result.completed and not result.stopped and result.next_ts is None and message:
            # drawtext can fail if fonts are missing; a plain card still works.
            args = ff.slate_command(self.settings, duration_s, ts, burst, channel_name, None)
            result = await self._run_ffmpeg(args, stitcher, ts, first_frame_timeout=15)
        return result

    async def _run_ffmpeg(
        self,
        args: list[str],
        stitcher: TsStitcher,
        ts: float,
        first_frame_timeout: float,
        on_air: bool = False,
        what: str = "",
    ) -> PlayResult:
        """Runs one ffmpeg and sends its output. `on_air` is for programs:
        the station counts as back on the air as soon as one is sending.
        `what` names the program, for the log."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024 * 1024,
            )
        except OSError as e:
            return PlayResult(0.0, completed=False, reason=f"couldn't start ffmpeg: {e}")
        self._proc = proc
        stitcher.begin_segment(ts)
        progress = ff.Progress()
        messages: deque[str] = deque(maxlen=8)
        last_frames = -1
        last_change = time.monotonic()
        stalled = False
        stall_limit = STALL_TIMEOUT_S
        gave_up = False  # (killed, and too slow to go: carried on without it)

        async def read_stderr() -> None:
            assert proc.stderr is not None
            async for raw in proc.stderr:
                line = raw.decode(errors="replace").rstrip()
                message = ff.parse_progress_line(line, progress)
                if message:
                    messages.append(message)

        async def read_stdout() -> None:
            assert proc.stdout is not None
            while True:
                data = await proc.stdout.read(65536)
                if not data:
                    break
                if on_air and self._unfilled_slots:
                    if self.off_air:
                        log.info("%s is back on the air", self._named(mid=True))
                    self._unfilled_slots = 0
                    self._last_unfilled = None
                    self.off_air = False
                self._emit(stitcher.feed(data))

        async def watchdog() -> None:
            nonlocal last_frames, last_change, stalled, stall_limit, gave_up
            warned = False
            leads: deque[tuple[float, float]] = deque()  # (when, lead), the last LOSING_S
            while proc.returncode is None:
                await asyncio.sleep(1)
                if progress.frames != last_frames:
                    last_frames = progress.frames
                    last_change = now = time.monotonic()
                    lead = self._lead_s(ts + progress.seconds)
                    if lead >= TARGET_LEAD_S / 2:
                        self._cushion_built = True
                    leads.append((now, lead))
                    while now - leads[0][0] > LOSING_S:
                        leads.popleft()
                    # Only once this program has had time to catch up (it
                    # reads ahead to rebuild the cushion after a hiccup), and
                    # only if it isn't catching up now.
                    behind = (
                        lead < LOW_LEAD_S
                        and progress.seconds > 10
                        and (self._cushion_built or progress.seconds > 30)
                        and now - leads[0][0] >= LOSING_S - 1.5
                        and lead - leads[0][1] < GAINING_S
                    )
                    if on_air and not warned and behind:
                        # Viewers' players are about to run out of stream.
                        warned = True
                        log.warning(
                            "%s is falling behind real time (%.1fs of stream buffered): "
                            "this server can't convert %s as fast as it plays",
                            self._named(mid=True),
                            lead,
                            what or "the program",
                        )
                    continue
                limit = first_frame_timeout if progress.frames == 0 else STALL_TIMEOUT_S
                if time.monotonic() - last_change > limit:
                    stalled = True
                    stall_limit = limit
                    log.warning("ffmpeg made no progress for %.0fs; killing it", limit)
                    self._kill()
                    # One stuck in the kernel (waiting on a disk, or on the
                    # GPU) goes only once that's over, which can be half a
                    # minute: the stream carries on without it.
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(proc.wait()), KILL_GRACE_S)
                    if proc.returncode is None:
                        gave_up = True
                        log.warning(
                            "ffmpeg is slow to stop (probably waiting on the disk or the GPU); "
                            "continuing without it"
                        )
                        readers.cancel()
                    return

        readers = asyncio.gather(read_stderr(), read_stdout())
        watch = asyncio.create_task(watchdog())
        code: int | None = None
        try:
            try:
                await readers
            except asyncio.CancelledError:
                if not gave_up:
                    raise
            if not gave_up:
                code = await proc.wait()
        finally:
            watch.cancel()
            if not gave_up and proc.returncode is None:
                proc.kill()
                await proc.wait()
            elif proc.returncode is None:
                _reap_later(proc)
            self._proc = None
        stitcher.flush_partial()
        stitcher.end_segment()

        produced = progress.seconds
        if stitcher.segment_start is not None and stitcher.segment_end is not None:
            # ffmpeg's frame counter lags behind what it has already written
            # (the encoder buffers a little), which matters when a process
            # is killed mid-run. The stream's own timestamps don't lag.
            produced = max(produced, (stitcher.segment_end - stitcher.segment_start) / PTS_HZ)
        next_ts = self._next_ts(stitcher, ts, produced)
        if self._stopping:
            return PlayResult(produced, completed=False, stopped=True, next_ts=next_ts)
        if stalled:
            return PlayResult(
                produced,
                completed=False,
                stalled=True,
                next_ts=next_ts,
                reason=f"playback stalled at {fmt_offset(produced)} "
                f"(no new video for {stall_limit:.0f} seconds)",
            )
        if code != 0:
            detail = messages[-1] if messages else f"exit code {code}"
            return PlayResult(
                produced,
                completed=False,
                next_ts=next_ts,
                reason=f"ffmpeg failed after {fmt_offset(produced)}: {detail}",
            )
        return PlayResult(produced, completed=True, next_ts=next_ts)

    def _next_ts(self, stitcher: TsStitcher, ts: float, produced: float) -> float | None:
        """Where the next program must start so nothing overlaps this one."""
        if stitcher.segment_end is None:
            return None
        if stitcher.segment_start is not None:
            self._pts_lead = stitcher.segment_start - round(ts * PTS_HZ)
        after_audio = (stitcher.segment_end - self._pts_lead) / PTS_HZ
        return max(ts + produced, after_audio) + JOIN_GAP_S


def corner_mark(ctx: AppContext, channel: Channel) -> ff.Watermark | None:
    """A station's logo, name or a clock for the corner of its programs."""
    if channel.watermark not in ("logo", "name", "clock"):
        return None
    logo = ctx.logos.path(channel.logo) if channel.watermark == "logo" and channel.logo else None
    return ff.Watermark(
        logo=str(logo) if logo else None,
        text=channel.name,
        size=channel.watermark_size,
        transparency=channel.watermark_transparency,
        position=channel.watermark_position,
        until_s=ff.WATERMARK_START_S if channel.watermark_timing == "start" else None,
        style=channel.watermark_style,
        clock=channel.clock_format if channel.watermark == "clock" else None,
    )


def station_banner(
    ctx: AppContext,
    channel: Channel,
    title: str,
    mark: ff.Watermark | None,
    settings: Settings | None = None,
) -> upnext.UpNext:
    """A station's Up Next Banner saying `title` is on next, with its corner
    mark `mark`, for a stream of `settings`' size (by default, the standard
    size)."""
    logo = ctx.logos.path(channel.logo) if channel.logo else None
    return upnext.UpNext(
        title,
        str(logo) if logo else None,
        channel.up_next_seconds,
        channel.up_next_size,
        upnext.corner_logo(settings or ctx.settings, mark),
    )


async def _nothing() -> None:
    return None


# Killed ffmpegs that were slow to go, till they have (see _run_ffmpeg).
_REAPING: set[asyncio.Task] = set()


def _reap_later(proc: asyncio.subprocess.Process) -> None:
    async def reap() -> None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        started = time.monotonic()
        await proc.wait()
        log.info("The stuck ffmpeg process exited after %.0fs more", time.monotonic() - started)

    task = asyncio.create_task(reap())
    _REAPING.add(task)
    task.add_done_callback(_REAPING.discard)


def _clear_card_folder(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in intro.PICTURES:
        (folder / f"{name}.png").unlink(missing_ok=True)


async def _draw(args: list[str], folder: Path, timeout_s: float = DRAW_TIMEOUT_S) -> bool:
    """Runs an ffmpeg that draws a card's pictures into `folder`; True if it
    did within `timeout_s`."""
    try:
        code, said = await ff.run_to_end(args, timeout_s)
    except (OSError, TimeoutError):
        return False
    if code != 0:
        log.warning("Drawing a card failed: %s", said)
        return False
    return all((folder / f"{name}.png").is_file() for name in intro.PICTURES[:3])


def _advance(ts: float, result: PlayResult) -> float:
    return result.next_ts if result.next_ts is not None else ts


def _mark_from(mark: ff.Watermark | None, aired_s: float) -> ff.Watermark | None:
    """The corner mark for a part of a program that starts `aired_s` into
    it: one shown only at the start of programs is shown for what's left
    of that time, if any."""
    if mark is None or mark.until_s is None:
        return mark
    left = mark.until_s - aired_s
    return replace(mark, until_s=left) if left >= MIN_PLAY_S else None


def _joined(first: PlayResult, then: PlayResult) -> PlayResult:
    """Two things played one after the other, as one."""
    return PlayResult(
        first.produced_s + then.produced_s,
        completed=then.completed,
        stopped=then.stopped,
        next_ts=then.next_ts if then.next_ts is not None else first.next_ts,
        reason=then.reason,
    )


def _clip_failed(result: PlayResult, expected_s: float) -> bool:
    return not result.completed or result.produced_s < expected_s - _clip_tolerance(expected_s)


def played_whole(ended_at_s: float, duration_s: float | None) -> bool:
    """Whether a program that came to the end of its file at `ended_at_s`
    played all of it: files often end a little short of the length they
    give (see ff.shortfall_allowed; the file checks judge it the same way)."""
    return duration_s is not None and ended_at_s >= duration_s - ff.shortfall_allowed(duration_s)


def _clip_tolerance(seconds: float) -> float:
    """How much shorter than expected a commercial or trailer may play and
    still count as fine: a second, or more for longer ones (the sound often
    runs on a little past the picture), up to three."""
    return max(CLIP_SHORTFALL_S, min(SHORTFALL_TOLERANCE_S, seconds / 4))


def between(slot: Slot, at: int) -> str | None:
    """What's on at moment `at` if it's after the slot's program:
    "commercials", "trailers" or "station id"."""
    found = _clip_at(slot.item, slot.start_ms + slot.item.program_end_ms, at)
    if found is None:
        return None
    if found[0] == ID_CARD:
        return "station id"
    return "commercials" if slot.item.kind == "episode" else "trailers"


def _clip_at(item: Item, program_end: int, at: int) -> tuple[str, int, int] | None:
    """What's playing at moment `at` in the break after `item`, which begins
    at `program_end`: (the file or ID_CARD, when it starts, when it ends)."""
    if at < program_end:
        return None
    start = program_end
    for path, ms in item.breaks or ():
        if at < start + ms:
            return path, start, start + ms
        start += ms
    return None


def fmt_offset(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
