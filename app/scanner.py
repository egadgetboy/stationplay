"""Checking files for problems before anyone plays them: the stations'
programs, and what's shared for Media in StationPlay's apps (the libraries
an Admin shared with them). One record per file, whoever plays it (see
broken.version_key): a file checked for a station isn't checked again for
Media, or the other way around, unless it changes.

One queue, at the lowest priority, and none of it while anyone's watching,
a station or Media (a lower disk priority isn't honoured by ZFS and most
NAS disks: fewer reads is what keeps the streams' own reads quick). In
this order:

  1. A station's program airing soon (in an update that hasn't started
     yet, or on within SOON_S) that's due a check.
  2. A file someone just had trouble with (see Target): a copy of it that
     failed to be made or stopped, a problem an app sent as it happened, or
     a person's report. The stretch of it where that happened is decoded as
     the deep scan decodes, then it gets the quick check (and for a report
     that says where, the deep scan, if those find nothing). Only what
     StationPlay finds puts it on the list: trouble that was the network's
     or the app's changes nothing about the file.
  3. Arrival check: a program new to a station (or whose file changed),
     then what's newly added to a library shared for Media, gets a quick
     check within minutes. The file must open, and picture and sound must
     decode at five points: the start, a quarter, halfway, three quarters
     and the end.
  4. Weekly sweep: every program on a station gets the quick check again
     once a week, in case a file went missing or a share changed. (Media's
     files are checked when they arrive, and when someone has trouble with
     one.)
  5. Overnight deep scan: in a window you choose (1-6 AM unless you change
     it), files are decoded in full, picture and sound, timed the way
     StationPlay plays them: the stations' programs first, whatever airs
     soonest first; then Media's: what's in someone's Continue Watching,
     the next episode of a show someone is watching, then the rest by most
     recently added (each with its quick check first, if it hasn't had
     one). It stops the moment anyone starts watching and carries on where
     it left off later. A file is deep-scanned once, and again only if it
     changes.

What counts is what stops a program airing whole and as it should. What
StationPlay plays through without anyone minding (a pause, a file a few
seconds short of its length, a decoder's complaint about nothing seen or
heard) doesn't.

  * Broken: the file won't open, has no picture, nothing decodes somewhere
    in it, its picture stops before the end (it's cut short), or it can't
    be read (a disk error).
  * Damaged: it plays, but not properly:
      - the picture breaks up (a picture ffmpeg couldn't decode, or had to
        patch up and that stays on screen), the sound drops out
        (SOUND_HEARD_S or more of it lost at one spot), or it skips (part of
        the file garbled), anywhere but its first two seconds and its last
        five;
      - no sound (or no picture and no sound) for GAP_S or more partway:
        not a silence before the sound starts or after it ends, in the end
        credits, or before a closing logo;
      - no sound track, or sound that's silent all the way through (in a
        program from 1930 on); or a picture black all the way through;
      - sound that stops before the picture does, unless nothing's lost
        (it stops during the end credits, over a black picture, or after
        fading out in the last minute);
      - it plays on well past the length it gives, so its end never airs.
    A picture held still while the sound plays on is fine: some files hold
    one frame a long time (an anime's end credits over one drawing, say).

Both go on the broken-files list, so they're off the air until the file is
replaced or you choose Retry (which also means "put it back on the air": a
file is never deep-scanned twice). In Media, a damaged file still plays; a
broken one doesn't (another version of it plays, if there's one that isn't
on the list).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import re
import signal
import time
import zlib
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field, fields, replace
from typing import TYPE_CHECKING

from . import catalog, ondemand
from . import ffmpeg as ff
from .broadcaster import fmt_offset, played_whole
from .broken import CHECK, DEEP_SCAN, TARGETED, file_key, version_key
from .catalog import Entry, Media
from .db import Item, ScanRecord
from .library import LibraryError
from .markers import CREDITS, parse_markers
from .sources import ResolvedSource, resolve_version

if TYPE_CHECKING:
    from .main import AppContext

log = logging.getLogger(__name__)

# The quick check: how much is decoded at each point. Where there's no
# picture or sound there, it looks GAP_S further on (a damaged stretch ends
# at the next whole picture; past the end of a file nothing comes).
POINT_S = 2.0
# No sound (or no picture and no sound) for this long partway through a
# program is damage. Anything shorter is a glitch at worst, and a silence
# this short is often meant (a pause, a cut to silence). A picture that's
# still while the sound goes on is left be: some files hold one frame for
# a long time (an anime's end credits over one picture, say).
GAP_S = 30.0
# Sound this quiet (dB below full scale) is silence: what a dropout leaves,
# quieter than any microphone records.
SILENCE_DB = -80
# The picture is black all the way through if this much of it is.
ALL_BLACK = 0.95
# Films before 1930 may have no sound track; after, it's missing.
SOUND_FROM_YEAR = 1930
# Sound that stops before the picture does loses nothing when it stops
# during the end credits, over a picture this much black (checked for up to
# BLACK_TAIL_CHECKED_S), or within FADED_TAIL_S of the end, with its last
# second this quiet (it faded out, or stopped in a pause).
BLACK_TAIL = 0.9
BLACK_TAIL_CHECKED_S = 180.0
BLACK_PIXELS = 90  # a frame this much black (percent) is: say, credits on black
FADED_TAIL_S = 60.0
FADED_DB = -45.0
# Plex's credits can begin a little after the sound stops (the music ends
# as they start).
CREDITS_LEEWAY_S = 5.0
# A silence with only this much sound after it, to the end (a closing
# logo's sting, a channel's sign-off), isn't a dropout.
CLOSING_SOUND_S = 20.0
# Plex finds a new program's credits a while after it's added (overnight,
# unless it's set to on arrival): until this long after, none marked may
# only mean it hasn't looked yet.
CREDITS_PENDING_S = 2 * 86_400
# The deep scan has the picture come out at this many frames a second, as
# StationPlay plays it (at a steady rate), so how far it went is its frames.
PICTURE_RATE = 10
# Programs are quick-checked again after this long.
RECHECK_S = 7 * 24 * 3600
# A station's program airs soon when it's on within this long (or it's in
# an update that hasn't started yet): it's checked before anything else.
SOON_S = 3 * 3600
# Quick checks between looks at what's new (so arrivals never wait long).
QUICK_BATCH = 20
# A quick check that couldn't tell (a slow share, Plex not answering) is
# tried again after this long, doubling each time up to the most.
SKIPPED_RETRY_S = 15 * 60
SKIPPED_RETRY_MOST_S = 12 * 3600
# The deep scan's record says which minutes of a file its glitches are in.
MINUTE_S = 60.0
# Errors this close to the start of a file are ignored: files often begin
# mid-stream, and players shrug it off. The same goes for the first seconds
# after jumping into a file (to carry on a scan): decoders complain
# harmlessly until they reach a whole picture. So a scan carries on from a
# little before where it stopped.
START_GRACE_S = 2.0
SEEK_GRACE_S = 5.0
RESUME_BACK_S = 10.0
# What an error decoding a file costs is judged by what it does, as ffmpeg
# itself says of each frame of picture or sound it decoded (see
# what_it_costs), not by what the decoders say along the way: lines of
# detail, several for one frame or none at all, and some about nothing seen
# or heard (TrueHD's "quant_step_size larger than huff_lsbs", say, or what
# they say after a jump into a file). The picture breaks up where ffmpeg
# couldn't decode a picture, or had to patch one up (some of it was missing
# or garbled) that stays on screen: one later pictures are built on, so the
# damage lasts till the next whole picture (seconds, often). Any one is a
# glitch. A patched picture shown for an instant (a B-frame, which nothing
# is built on) isn't: decoders patch from the pictures around it, and tests
# of damaged files against their clean decodes found any trace of it gone
# within a frame or two. Sound is a glitch where what's lost of it at one
# spot (within SPOT_S) is heard: SOUND_HEARD_S or more, a click or a
# dropout. A frame of sound is one block of its format: in samples (or, for
# TrueHD's, seconds: 1/1200s whatever the rate).
SOUND_HEARD_S = 0.02
SPOT_S = 1.0
_SOUND_BLOCKS: dict[str, int | float] = {
    "aac": 1024, "aac_latm": 1024, "ac3": 1536, "eac3": 1536, "dts": 512, "dca": 512,
    "mp3": 1152, "mp2": 1152, "mp1": 384, "opus": 960, "vorbis": 1024, "flac": 4096,
    "alac": 4096, "wmav1": 2048, "wmav2": 2048, "wmapro": 2048,
    "truehd": 1 / 1200, "mlp": 1 / 1200,
}  # fmt: skip
_SOUND_BLOCK = 1024  # (a format not listed)
# The sound formats' names as people know them, for the list.
SOUND_NAMES = {
    "aac": "AAC", "ac3": "Dolby Digital", "eac3": "Dolby Digital Plus", "dts": "DTS",
    "truehd": "Dolby TrueHD", "mlp": "MLP", "mp3": "MP3", "mp2": "MP2", "flac": "FLAC",
    "opus": "Opus", "vorbis": "Vorbis", "alac": "ALAC",
}  # fmt: skip
# ffmpeg's word on a frame: "[vist#0:0/h264 @ 0x...] [warning] corrupt
# decoded frame" (patched up; ffmpeg 7 adds "[dec:h264 @ 0x...] " before the
# level), or that a packet of the stream couldn't be decoded at all.
_FRAME_HURT = re.compile(
    r"\[([va])ist#[^/\]]*/([^ @\]]+) @ [^\]]+\] (?:\[[^\]]+\] )*\[(?:warning|error|fatal)\] "
    r"(corrupt decoded frame|Error submitting packet to decoder|Decoding error)"
)
# What kind of picture a decoder is patching up, as it does (before ffmpeg
# says the picture's patched): "concealing 729 DC, 729 AC, 729 MV errors in
# P frame". B (b: BI) pictures are shown for an instant: nothing's built on
# them. Said of a picture ffmpeg hasn't said is patched within PATCH_S, it's
# about one that wasn't shown.
_PATCHING = re.compile(r"\] \[info\] concealing \d+ DC, \d+ AC, \d+ MV errors in (\w) frame")
PATCH_S = 3.0
# Part of a file garbled where the demuxer reads it, so it skips ahead to
# where it can carry on (picture and sound skip; the decoders may not
# notice): in Matroska's words, or MP4's.
_SKIPS = re.compile(
    r"invalid as first byte of an EBML number|exceeds max length|exceeds containing master "
    r"element|^Invalid length 0x|considered as invalid data|inside parent with finite size|"
    r": partial file"
)
# Glitches this near each other are told as one (scanning on from a little
# before where it stopped can find one twice, a second or so apart).
NEAR_S = 5.0
# Nothing in a file's last seconds counts: the tool that made a file often
# cut its last frame short, and nothing's lost that anyone would see.
END_GRACE_S = 5.0
# Where each glitch is kept, at most (it's the first few that are shown).
MOST_GLITCHES = 200
# Read errors on this many different nights mean the file can't be read (a
# share can drop out for a while; a bad disk block stays bad).
READ_FAILURES = 2
# How long one decode may take before it's stopped (the share hung).
QUICK_TIMEOUT_S = 60.0
# Decoding threads for a quick check (it's at the lowest priority either way).
QUICK_THREADS = 2
# A deep scan making no progress for this long has hit a hung share.
STALL_S = 120.0
# How often an unfinished deep scan's progress is saved.
SAVE_EVERY_S = 30.0
# How often the scanner looks for work, and for a viewer while deep-scanning.
IDLE_S = 60.0
WATCH_POLL_S = 2.0
STARTUP_DELAY_S = 90.0
DEFAULT_WINDOW = ("01:00", "06:00")
META_WINDOW = "scan_window"  # "on|01:00|06:00"
# Which checks files have had. When they change, every file is checked
# again (and what the quick check found before is looked at afresh).
CHECKS = "3"  # (3: Dolby Vision files with no ordinary picture inside)
META_CHECKS = "scan_checks"
META_FIRST = "scan_first"  # JSON: rating keys to quick-check before others
# How the deep scan judges what it finds. When that changes, the files it
# may judge differently are deep-scanned again (see _rules_changed).
DEEP_RULES = "2"  # (2: glitches judged by what they do, in 1.16.3)
META_DEEP_RULES = "deep_rules"
META_AGAIN = "deep_again"  # JSON: rating keys of programs off the air to judge again
# Media (the libraries shared with the apps). What's newly added is looked
# for when the libraries change, and at least every MEDIA_LOOK_S, newest
# first, MEDIA_PAGE at a time (MEDIA_NEW_MOST at most): what was added since
# the checks reached Media (META_MEDIA_FROM, seconds since 1970) is an
# arrival; what was there before is the overnight deep scan's.
MEDIA_LOOK_S = 1800.0
MEDIA_PAGE = 100
MEDIA_NEW_MOST = 500
META_MEDIA_FROM = "media_checks_from"
# For the deep scan: Media's whole list, newest first, is fetched at most
# this often (MEDIA_ALL_PAGE at a time); what people are watching, this often.
MEDIA_ALL_S = 3600.0
MEDIA_ALL_PAGE = 500
MEDIA_WATCHED_S = 600.0
# A file someone had trouble with (see Target): the stretch decoded is from
# STRETCH_BEFORE_S before where it went wrong, for STRETCH_S. A check that
# can't tell (a slow share, Plex away) is tried again, TARGET_TRIES times
# in all; at most TARGETS_MOST wait at once (the oldest go first).
STRETCH_BEFORE_S = 20.0
STRETCH_S = 60.0
TARGET_TRIES = 4
TARGETS_MOST = 200
META_TARGETS = "scan_targets"  # JSON: the targets waiting (see Target)
# What's next for a target: its stretch, its quick check, its deep scan.
STRETCH, QUICK, FULL = "stretch", "quick", "full"
# What a target's check came to (for the reports that asked for it: see
# reports.py): a problem found (and the file on the list); one found in a
# file an Admin put back on the air; nothing; the program gone; or it
# couldn't be checked.
FOUND, KEPT, NOTHING, GONE, COULDNT = "found", "kept", "nothing", "gone", "couldn't"
# What took programs off the air that's judged anew: the deep scan's
# counting of decoders' errors (before 1.16.3).
_JUDGED_ANEW = "Deep scan: the picture or sound breaks up"
# A program that ended early as it played (broadcaster; "file ended early at
# X of Y" before 1.16.4).
_ENDED_EARLY = re.compile(r"^(?:the file ended|file ended early) at ([\d:]+) of ([\d:]+)")
# What ffmpeg says about its own output (decoding to nowhere), not the file.
_NOT_THE_FILE = (
    "[null @", "[out#", "[vost#", "[aost#", "[wrapped_avframe @", "[pcm_",
    "Application provided invalid", "Last message repeated",
)  # fmt: skip
# How bad a line ffmpeg logs is ("-loglevel level+info" tags each line).
_LEVEL = re.compile(r"^(?:\[[^\]]+\] )*\[(debug|verbose|info|warning|error|fatal|panic)\] ")
_PROBLEM_LEVELS = ("error", "fatal", "panic")
_SILENCE_START = re.compile(r"silence_start: (-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end: (-?[\d.]+)")
_SILENCE_LASTED = re.compile(r"silence_duration: (-?[\d.]+)")
_BLACK = re.compile(r"black_start:\s*(-?[\d.]+)\s+black_end:\s*(-?[\d.]+)")
_BLACK_FRAME = re.compile(r"pblack:(\d+) .*?\bt:(-?[\d.]+)")
_MEAN_VOLUME = re.compile(r"mean_volume: (-?(?:[\d.]+|inf)) dB")


class Unknown(Exception):
    """Something a check needs can't be found out now (Plex didn't answer)."""


@dataclass
class Decoded:
    frames: int = 0  # video frames decoded
    seconds: float = 0.0  # how much was decoded
    failed: str = ""  # why nothing decoded, if nothing did
    timed_out: bool = False
    unreadable: bool = False  # a read error (disk or share)
    not_run: bool = False  # ffmpeg couldn't be started

    @property
    def inconclusive(self) -> bool:
        """Says nothing about the file: the share or ffmpeg let it down."""
        return self.timed_out or self.unreadable or self.not_run


@dataclass
class Verdict:
    # "ok", "broken", "damaged", "unsupported" (it plays, but can't be shown
    # right: see ff.DOLBY_VISION_ONLY), or "skipped" (couldn't tell).
    result: str
    reason: str = ""


def _decode_args(
    ctx: AppContext,
    source: str,
    start_s: float,
    seconds: float | None,
    video_index: int | None,
    audio_index: int | None,
    threads: int,
    progress: str,
    filters: list[str] | None = None,
    keyframes_only: bool = False,
) -> list[str]:
    """ffmpeg, at the lowest CPU and disk priority (so checking files never
    slows anything else down), decoding part of a file (to the end if
    `seconds` is None) without showing it anywhere. With `filters`, every
    line it logs is tagged with how bad it is, and the filters' own
    findings are among them."""
    args = [
        *ff.low_priority(),
        ctx.settings.ffmpeg_path, "-hide_banner", "-nostdin", "-nostats",
        "-loglevel", "level+info" if filters else "error",
        "-threads", str(threads),
    ]  # fmt: skip
    if source.startswith(("http://", "https://")):
        args += ["-rw_timeout", "30000000"]
    if start_s > 0:
        args += ["-ss", f"{start_s:.3f}"]
    if keyframes_only:
        args += ["-skip_frame", "nokey"]
    args += ["-i", source]
    if seconds is not None:
        args += ["-t", f"{seconds:.3f}"]
    for kind, index in (("v", video_index), ("a", audio_index)):
        if index is not None:
            args += ["-map", f"0:{kind}:{index}"]
    return [*args, *(filters or []), "-f", "null", "-", "-progress", progress]


def _read_error(line: str) -> bool:
    return "input/output error" in line.lower()


def _problem(line: str) -> bool:
    """Whether a line ffmpeg logged (tagged with its level) is about
    something wrong in the file."""
    level = _LEVEL.match(line)
    if level is None or line.startswith(_NOT_THE_FILE):
        return False
    return level.group(1) in _PROBLEM_LEVELS


def what_it_costs(line: str, rate: int = 0) -> tuple[str, float] | None:
    """What a line ffmpeg logged decoding a file says was lost: ("picture",
    0) for a picture that couldn't be decoded, ("patched", 0) for one patched
    up (see Scanned.lost); ("sound", seconds) for a frame of sound (at `rate`
    samples a second: the file's); ("skip", 0) for part of the file skipped;
    None for anything else."""
    hurt = _FRAME_HURT.match(line)
    if hurt is None:
        level = _LEVEL.match(line)
        if _problem(line) and level and _SKIPS.search(line[level.end() :]):
            return "skip", 0.0
        return None
    if hurt.group(1) == "v":
        return ("patched" if hurt.group(3) == "corrupt decoded frame" else "picture"), 0.0
    block = _SOUND_BLOCKS.get(hurt.group(2), _SOUND_BLOCK)
    return "sound", block if isinstance(block, float) else block / (rate or 48_000)


async def _run(args: list[str], timeout: float) -> tuple[int | None, str, str, Decoded | None]:
    """Runs ffmpeg to the end: (exit code, its output, its log), or a
    Decoded saying why it couldn't be done."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        return None, "", "", Decoded(failed=f"couldn't run ffmpeg: {e}", not_run=True)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        return None, "", "", Decoded(failed=f"timed out after {timeout:.0f}s", timed_out=True)
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace"), None


async def decode(
    ctx: AppContext,
    source: str,
    start_s: float,
    seconds: float,
    video_index: int | None,
    audio_index: int | None,
    timeout: float = QUICK_TIMEOUT_S,
    threads: int = QUICK_THREADS,
) -> Decoded:
    """Decodes `seconds` of a file from `start_s`: how much decoded."""
    args = _decode_args(ctx, source, start_s, seconds, video_index, audio_index, threads, "pipe:1")
    code, out, err, failed = await _run(args, timeout)
    if failed is not None:
        return failed
    got = Decoded()
    for line in out.splitlines():
        key, _, value = line.partition("=")
        with contextlib.suppress(ValueError):
            if key == "frame":
                got.frames = int(value)
            elif key == "out_time_us":
                got.seconds = max(0.0, int(value) / 1_000_000)
    errors = [
        ff.redact(line.strip())
        for line in err.splitlines()
        if line.strip() and not line.startswith(_NOT_THE_FILE)
    ]
    if any(_read_error(e) for e in errors):
        got.unreadable = True
        got.failed = "the file couldn't be read (a disk or share error)"
    elif code != 0 and not got.frames and not got.seconds:
        got.failed = errors[-1] if errors else f"ffmpeg exit code {code}"
    return got


async def mean_level(
    ctx: AppContext, source: str, start_s: float, seconds: float, audio_index: int
) -> float | None:
    """How loud (dB below full scale) a stretch of a file's sound is on
    average; None if that can't be told now."""
    args = _decode_args(
        ctx, source, start_s, seconds, None, audio_index, QUICK_THREADS, "pipe:1",
        ["-af", "volumedetect"],
    )  # fmt: skip
    _code, _out, err, failed = await _run(args, QUICK_TIMEOUT_S)
    if failed is not None:
        return None
    levels = _MEAN_VOLUME.findall(err)
    return float(levels[-1]) if levels else None


async def black_share(
    ctx: AppContext, source: str, start_s: float, seconds: float, video_index: int
) -> float | None:
    """How much of a stretch of a file's picture is black (0 to 1), by its
    keyframes (quick, even for 4K): each stands for the time to the next.
    By every frame, if it has few keyframes. None if that can't be told now."""
    for keyframes_only in (True, False):
        args = _decode_args(
            ctx, source, start_s, seconds, video_index, None, QUICK_THREADS, "pipe:1",
            ["-vf", "blackframe=amount=0:threshold=26"],
            keyframes_only=keyframes_only,
        )  # fmt: skip
        _code, _out, err, failed = await _run(args, QUICK_TIMEOUT_S * 2)
        if failed is not None:
            return None
        frames = [(float(t), int(black)) for black, t in _BLACK_FRAME.findall(err)]
        if len(frames) >= 3 or not keyframes_only:
            return black_part(frames, seconds)
    return None


def black_part(frames: list[tuple[float, int]], end: float) -> float | None:
    """How much of the time from the first frame to `end` is black, given
    each frame's time and how much of it is black (percent): each frame
    stands for the time to the next. None without frames."""
    frames = sorted(f for f in frames if f[0] < end)
    if not frames:
        return None
    ends = [t for t, _ in frames[1:]] + [end]
    black = sum(e - t for (t, part), e in zip(frames, ends, strict=True) if part >= BLACK_PIXELS)
    return min(1.0, black / (end - frames[0][0]))


@dataclass
class Scanned:
    at: float  # how far into the file decoding got
    # Where the picture broke up, the sound dropped out or the file skipped:
    # [kind, at] (see what_it_costs).
    glitches: list[list] = field(default_factory=list)
    # Sound lost in the last SPOT_S: (where, how much).
    sound_lost: deque[tuple[float, float]] = field(default_factory=deque)
    # Pictures being patched up: (where, what kind of picture; see _PATCHING).
    patching: deque[tuple[float, str]] = field(default_factory=deque)
    unreadable: bool = False
    stalled: bool = False
    picture_to: float = 0.0  # how far into the file the picture went
    # Where (from, to, in the file) the sound was silent for a second or
    # more, and the picture was black.
    silences: list[tuple[float, float]] = field(default_factory=list)
    silent_since: float | None = None  # silent from here, and still
    blacks: list[tuple[float, float]] = field(default_factory=list)

    def patches(self, picture: str) -> None:
        """A picture a decoder is patching up, of this kind (I, P, B...)."""
        self.patching.append((self.at, picture))

    def lost(self, kind: str, seconds: float) -> None:
        """Takes in a frame of picture or sound lost (see what_it_costs)
        where decoding is: a glitch, if it's seen or heard."""
        at = self.at
        if kind == "patched":
            while self.patching and self.patching[0][0] < at - PATCH_S:
                self.patching.popleft()
            if self.patching and self.patching.popleft()[1] in "Bb":
                return  # (shown for an instant)
            kind = "picture"  # (one others are built on; or it's not known which)
        if kind == "sound":
            self.sound_lost.append((at, seconds))
            while self.sound_lost[0][0] < at - SPOT_S:
                self.sound_lost.popleft()
            if sum(s for _, s in self.sound_lost) < SOUND_HEARD_S - 1e-9:
                return
        last = next((g for g in reversed(self.glitches) if g[0] == kind), None)
        if last is not None and at - last[1] < SPOT_S:
            return  # (the same glitch)
        if len(self.glitches) < MOST_GLITCHES:
            self.glitches.append([kind, round(at, 1)])


def _analysis(sound: bool) -> list[str]:
    """What the deep scan has ffmpeg do besides decoding, as StationPlay
    plays a program: the picture at a steady rate (so how far it went is
    its frames counted), and the sound kept in step with it (silence where
    the file has none) and padded to the picture's end. It notes black
    stretches of picture and silent stretches of sound."""
    out = ["-vf", "blackdetect=d=1:pix_th=0.10"]
    if sound:
        out += [
            "-af", f"aresample=async=1:first_pts=0,apad,silencedetect=n={SILENCE_DB}dB:d=1",
            "-shortest",
        ]  # fmt: skip
    return [*out, "-fps_mode", "cfr", "-r", str(PICTURE_RATE)]


def _note(line: str, got: Scanned, start_s: float) -> None:
    """Takes in what the silence and black detectors found. (Looked for
    anywhere in a line: ffmpeg writes a line in pieces, and its progress
    report, written meanwhile, can land between them.)"""
    if m := _SILENCE_END.search(line):
        # Where it began, from how long it lasted: the line saying where it
        # began may have been one of those split up.
        ended = start_s + float(m.group(1))
        lasted = _SILENCE_LASTED.search(line)
        began = ended - float(lasted.group(1)) if lasted else got.silent_since
        got.silences.append((ended if began is None else began, ended))
        got.silent_since = None
    elif m := _SILENCE_START.search(line):
        got.silent_since = start_s + float(m.group(1))
    elif m := _BLACK.search(line):
        got.blacks.append((start_s + float(m.group(1)), start_s + float(m.group(2))))


async def decode_through(
    ctx: AppContext,
    source: str,
    start_s: float,
    video_index: int,
    audio_index: int | None,
    on_progress: Callable[[Scanned], None],
    count_from: float,
    rate: int = 0,
    seconds: float | None = None,
) -> Scanned:
    """Decodes a file from `start_s` to the end as it plays (or `seconds`
    of it), noting where the picture broke up or the sound dropped out (not
    before `count_from`, just after the start or a seek; `rate`: the sound's
    sample rate), silences and black stretches, and how far the picture
    went. Cancelling stops it, after what it was in the middle of noting is
    noted."""
    # Progress on the same pipe as the log, so each line lands in order.
    args = _decode_args(
        ctx, source, start_s, seconds, video_index, audio_index, 0, "pipe:2",
        _analysis(audio_index is not None),
    )  # fmt: skip
    got = Scanned(at=start_s, picture_to=start_s)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, "-stats_period", "0.05",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            limit=1024 * 1024,
        )  # fmt: skip
    except OSError:
        got.stalled = True  # ffmpeg couldn't start: says nothing about the file
        return got
    moved = time.monotonic()

    async def read() -> None:
        nonlocal moved
        assert proc.stderr is not None
        while True:
            try:
                raw = await proc.stderr.readline()
            except ValueError:
                continue  # a line too long to hold (say, a file's whole tags): skipped
            if not raw:
                break
            line = raw.decode(errors="replace").strip()
            key, sep, value = line.partition("=")
            if sep and (key in ff.PROGRESS_KEYS or key.startswith("stream_")):
                with contextlib.suppress(ValueError):
                    if key == "out_time_us":
                        at = start_s + int(value) / 1_000_000
                        if at > got.at:
                            got.at, moved = at, time.monotonic()
                    elif key == "frame":
                        got.picture_to = start_s + int(value) / PICTURE_RATE
                    elif key == "progress":
                        on_progress(got)
            elif _read_error(line) and _problem(line):
                got.unreadable = True
            elif (cost := what_it_costs(line, rate)) is not None:
                if got.at >= count_from:
                    got.lost(*cost)
            elif patched := _PATCHING.search(line):
                got.patches(patched.group(1))
            elif "silence_" in line or "black_start" in line:
                _note(line, got, start_s)

    reader = asyncio.create_task(read())
    try:
        while not reader.done():
            await asyncio.wait({reader}, timeout=5)
            if not reader.done() and time.monotonic() - moved > STALL_S:
                got.stalled = True
                break
    finally:
        try:
            if proc.returncode is None and not got.stalled:
                # Stopped partway (someone tuned in): asked to stop, ffmpeg
                # reports the silence or black stretch it was in the middle of.
                with contextlib.suppress(ProcessLookupError):
                    proc.send_signal(signal.SIGINT)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(asyncio.shield(reader), 5)
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
            await proc.wait()
            if not reader.done():
                reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader
            on_progress(got)  # (what it said after its last progress report)
    if not reader.cancelled() and (error := reader.exception()) is not None:
        raise error  # (what it found says nothing about the file)
    return got


# The quick check ------------------------------------------------------------------


def last_point(duration_s: float) -> float:
    """The latest moment a file must have picture at, not to count as cut
    short."""
    return max(0.0, duration_s - ff.shortfall_allowed(duration_s) - POINT_S)


def check_points(duration_s: float) -> list[float]:
    """Where the quick check looks: the start, a quarter, half, three
    quarters and the end."""
    if duration_s <= POINT_S * 4:
        return [0.0]
    points = [0.0, duration_s * 0.25, duration_s * 0.5, duration_s * 0.75, last_point(duration_s)]
    out: list[float] = []
    for p in sorted(points):
        if not out or p - out[-1] >= POINT_S:
            out.append(p)
    return out


async def quick_check(
    ctx: AppContext,
    source: str,
    probe: ff.ProbeResult,
    year: int | None = None,
    credits_from: Callable[[], Awaitable[list[tuple[float, float]]]] | None = None,
) -> Verdict:
    """Picture and sound at five points of a file that opens, and how the
    sound ends. Only what stops a file playing as it should counts here:
    jumping into the middle of a file makes some decoders complain
    harmlessly, so decoding errors are left to the deep scan, which reads
    files straight through. `year`: the program's (for films that may have
    no sound); `credits_from`: where Plex says its end credits begin."""
    if probe.dolby_vision_only:
        return Verdict("unsupported", ff.dolby_vision_reason(probe))
    duration = probe.duration_s or 0.0
    points = check_points(duration)

    async def there(at: float, video: bool) -> Decoded | None:
        """Whether there's picture (or sound) at `at`: None if there is.
        If two seconds have none, it looks GAP_S further."""
        v, a = (probe.video_index, None) if video else (None, probe.audio_index)
        for seconds in (POINT_S, GAP_S):
            got = await decode(ctx, source, at, seconds, v, a)
            present = got.frames > 0 if video else got.seconds >= seconds / 4
            if present or got.inconclusive:
                return got if got.inconclusive else None
        return got

    async def found(video: bool) -> list[bool] | Verdict:
        """Picture (or sound) at each point, or why that can't be told."""
        out = []
        for at in points:
            missing = await there(at, video)
            if missing is not None and missing.inconclusive:
                # Can't tell now (a share hiccup, or ffmpeg couldn't start):
                # the file isn't blamed; it's checked again later.
                return Verdict("skipped", missing.failed)
            out.append(missing is None)
        return out

    picture = await found(video=True)
    if isinstance(picture, Verdict):
        return picture
    if not all(picture) and not any(picture[picture.index(False) + 1 :]):
        gone = picture.index(False)
        held = gone == len(points) - 1 and await _held_to_the_end(ctx, source, probe, points[gone])
        if isinstance(held, Verdict):
            return held
        if not held:
            cut = fmt_offset(points[gone])
            return Verdict("broken", f"no picture from {cut} on (the file is cut short or damaged)")
    if probe.audio_index is None:
        if year is not None and year >= SOUND_FROM_YEAR:
            return Verdict("damaged", "it has no sound track")
        return Verdict("ok")  # (a silent film; or who knows, without a year)
    sound = await found(video=False)
    if isinstance(sound, Verdict):
        return sound
    for at, seen, heard in zip(points, picture, sound, strict=True):
        # No picture where the sound plays on is a still picture, held: fine.
        if not seen and not heard:
            return Verdict(
                "damaged",
                f"no picture or sound for {GAP_S:.0f} seconds or more, starting at "
                f"{fmt_offset(at)}",
            )
    if all(sound):
        return Verdict("ok")
    gone = sound.index(False)
    if any(sound[gone + 1 :]):
        return Verdict(
            "damaged",
            f"no sound for {GAP_S:.0f} seconds or more, starting at {fmt_offset(points[gone])}",
        )
    if gone == 0:
        return Verdict("damaged", "no sound anywhere in it")
    stops = await _sound_stops(ctx, source, probe, points[gone - 1], points[gone])
    if stops is None:
        return Verdict("skipped", "couldn't tell where the sound stops")
    return await _after_the_sound(ctx, source, probe, stops, credits_from)


async def _held_to_the_end(
    ctx: AppContext, source: str, probe: ff.ProbeResult, at: float
) -> bool | Verdict:
    """No new picture from `at`, the last point, on: whether that's a
    picture held still to the end (some files hold their last frame a long
    time), with the sound playing and the picture saying it runs to the
    end, rather than the picture cut short."""
    duration = probe.duration_s or 0.0
    runs = probe.video_duration_s
    if (
        probe.audio_index is None
        or runs is None
        or runs < duration - ff.shortfall_allowed(duration)
    ):
        return False
    got = await decode(ctx, source, at, POINT_S, None, probe.audio_index)
    if got.inconclusive:
        return Verdict("skipped", got.failed)
    return got.seconds >= POINT_S / 4


async def _sound_stops(
    ctx: AppContext, source: str, probe: ff.ProbeResult, heard: float, missing: float
) -> float | None:
    """Where the sound stops for good, between `heard` (it's there) and
    `missing` (it's not), to within a second (exactly, once a look lands in
    its last two seconds). None if that can't be told now."""
    assert probe.audio_index is not None
    while missing - heard > 1.0:
        middle = (heard + missing) / 2
        got = await decode(ctx, source, middle, POINT_S, None, probe.audio_index)
        if got.inconclusive:
            return None
        if got.seconds <= 0:
            missing = middle
        elif got.seconds < POINT_S - 0.1:
            return middle + got.seconds  # it stops within these two seconds: there
        else:
            heard = middle + got.seconds
    return heard


async def _after_the_sound(
    ctx: AppContext,
    source: str,
    probe: ff.ProbeResult,
    stops: float,
    credits_from: Callable[[], Awaitable[list[tuple[float, float]]]] | None,
) -> Verdict:
    """The sound stops at `stops`, before the picture does: whether anything
    is lost."""
    assert probe.audio_index is not None
    duration = probe.duration_s or 0.0
    left = duration - stops
    lost = Verdict(
        "damaged",
        f"the sound stops at {fmt_offset(round(stops))}, {fmt_offset(round(left))} before the end",
    )
    if left <= ff.shortfall_allowed(duration):
        return Verdict("ok")
    if left <= FADED_TAIL_S:
        level = await mean_level(ctx, source, max(0.0, stops - 1.0), 1.0, probe.audio_index)
        if level is None:
            return Verdict("skipped", "couldn't tell how the sound ends")
        if level <= FADED_DB:
            return Verdict("ok")
    black = await black_share(
        ctx, source, stops, min(left, BLACK_TAIL_CHECKED_S), probe.video_index
    )
    if black is None:
        return Verdict("skipped", "couldn't tell what's on after the sound stops")
    if black >= BLACK_TAIL:
        return Verdict("ok")
    if credits_from is not None:
        try:
            rolls = await credits_from()
        except Unknown as e:
            return Verdict("skipped", str(e))
        # It stops in the last end credits (not an earlier roll, with a
        # scene after it).
        if rolls and stops >= rolls[-1][0] - CREDITS_LEEWAY_S:
            return Verdict("ok")
    return lost


async def quick_check_item(
    ctx: AppContext,
    item: Item,
    station: int | None,
    record: ScanRecord | None = None,
    version: str = "",
    library: str | None = None,
) -> tuple[Verdict, ScanRecord | None]:
    """Quick-checks a program's file (`version`: one that isn't its first,
    by its ID), and takes it off the air if it's broken or damaged.
    Returns the verdict and the updated scan record (None if the file
    couldn't be looked at: Plex or the share down)."""
    verdict, record, resolved = await quick_verdict(ctx, item, record, version)
    if verdict.result in ("ok", "skipped"):
        return verdict, record
    if record is not None and record.kept:
        log.info(
            "Quick check found a problem in %s (%s), but you put it back on the air, so it "
            "stays on",
            item.label,
            verdict.reason,
        )
        return verdict, record
    ctx.broken.record(
        item,
        f"Check: {verdict.reason}",
        station,
        resolved.plex_file,
        resolved.size if record is not None else None,
        problem=verdict.result,
        found=CHECK,
        version=version,
        library=library,
    )
    return verdict, record


async def resolve(ctx: AppContext, item: Item, version: str = "") -> ResolvedSource:
    """Where a program's file is read from: the one a station plays, or
    another version of it (`version`: its ID)."""
    if not version:
        return await ctx.resolve_source(item)
    return await resolve_version(ctx.settings, ctx.library, item, version, ctx.media_access)


async def quick_verdict(
    ctx: AppContext, item: Item, record: ScanRecord | None = None, version: str = ""
) -> tuple[Verdict, ScanRecord | None, ResolvedSource]:
    """The quick check of a program's file (`version`: one that isn't its
    first, by its ID), taking nothing off the air: the verdict ("ok",
    "broken", "damaged" or "skipped": couldn't tell), the updated scan
    record (None if the file couldn't be looked at), and where the file was
    found."""
    resolved = await resolve(ctx, item, version)
    if resolved.error or not resolved.source:
        if resolved.transient:
            return Verdict("skipped", resolved.error or ""), None, resolved
        return Verdict("broken", resolved.error or "file not found"), None, resolved
    file = resolved.plex_file or resolved.source
    size = resolved.size or 0
    if record is None or record.file != file or (size and record.size and record.size != size):
        # A new file: start afresh.
        record = ScanRecord(version_key(item.rating_key, version), file, size)
    record.size = size or record.size
    probe = await ff.probe(ctx.settings, resolved.source)
    streamed = resolved.source.startswith(("http://", "https://"))
    if probe.timed_out or (not probe.ok and streamed):
        # Through Plex, a failure may well be Plex's or the share's (a pool
        # offline); playing it will tell.
        return Verdict("skipped", probe.error or ""), None, resolved
    if not probe.ok:
        verdict = Verdict("broken", probe.error or "the file can't be opened")
    else:

        async def credits_from() -> list[tuple[float, float]]:
            return await credits_of(ctx, item)

        verdict = await quick_check(ctx, resolved.source, probe, item.year, credits_from)
    if verdict.result == "skipped":
        return verdict, None, resolved
    record.quick_ms = int(time.time() * 1000)
    record.quick = verdict.result
    return verdict, record, resolved


async def check_stretch(
    ctx: AppContext, source: str, probe: ff.ProbeResult, at_s: float
) -> tuple[Verdict, float]:
    """The stretch of a file around `at_s`, where someone had trouble with
    it, decoded as the deep scan decodes it (see decode_through): from
    STRETCH_BEFORE_S before it, for STRETCH_S. "damaged" where the picture
    breaks up, the sound drops out or it skips there, as the deep scan
    judges it; "skipped" if nothing of it could be read; "ok" otherwise.
    (What only decoding a whole file tells, such as how long a silence
    lasts, is the deep scan's to judge.) Also where the stretch starts."""
    duration = probe.duration_s or 0.0
    start = max(0.0, at_s - STRETCH_BEFORE_S)
    if duration:
        start = min(start, max(0.0, duration - STRETCH_S))
    got = await decode_through(
        ctx, source, start, probe.video_index, probe.audio_index, lambda _got: None,
        count_from=start + (SEEK_GRACE_S if start else START_GRACE_S),
        rate=probe.audio_rate, seconds=STRETCH_S,
    )  # fmt: skip
    if got.stalled or got.unreadable or max(got.at, got.picture_to) <= start + 1.0:
        return Verdict("skipped", "that part of the file couldn't be read"), start
    end = (duration or got.picture_to) - END_GRACE_S
    glitches = [g for g in got.glitches if g[1] < end]
    if glitches:
        return Verdict("damaged", glitch_reason(glitches, probe.audio_codec)), start
    return Verdict("ok"), start


async def credits_of(ctx: AppContext, item: Item) -> list[tuple[float, float]]:
    """The end credits Plex marks in a program, as (from, to) in seconds, in
    order. Raises Unknown if Plex can't be asked now, or marks none in a
    program added lately (it may not have looked yet)."""
    try:
        raw, added = await asyncio.wait_for(ctx.library.markers_and_added(item.rating_key), 30)
    except (LibraryError, TimeoutError) as e:
        raise Unknown("Plex didn't say where the end credits are") from e
    rolls = sorted(
        (m.start_ms / 1000, m.end_ms / 1000) for m in parse_markers(raw) if m.kind == CREDITS
    )
    if not rolls and added is not None and time.time() - added < CREDITS_PENDING_S:
        raise Unknown("Plex hasn't looked for its end credits yet")
    return rolls


def glitch_reason(glitches: list[list], sound: str = "") -> str:
    """Where the picture breaks up, the sound drops out (`sound`: its
    format, as ffprobe names it) and the file skips, for the list: "the
    picture breaks up around 12:31 and 48:02; the sound (Dolby Digital)
    drops out around 1:02:10". (Around: ffmpeg's word on a frame comes as
    what it's made of the file so far gets a few seconds past it. And where
    it skips, that's what's said: the picture and sound break up there
    because of it.)"""
    skips = _spots(glitches, "skip")
    glitches = [
        [kind, at]
        for kind, at in glitches
        if kind == "skip" or all(abs(at - s) > NEAR_S for s in skips)
    ]
    said = []
    for kind, what, why in (
        ("picture", "the picture breaks up", ""),
        ("sound", f"the sound ({SOUND_NAMES[sound]}) drops out" if sound in SOUND_NAMES
         else "the sound drops out", ""),
        ("skip", "it skips", " (part of the file is garbled there)"),
    ):  # fmt: skip
        spots = _spots(glitches, kind)
        if spots:
            said.append(f"{what} around {_listed([fmt_offset(int(at)) for at in spots])}{why}")
    return "; ".join(said)


def _spots(glitches: list[list], kind: str) -> list[float]:
    """Where glitches of a kind are, those NEAR_S apart or less as one."""
    spots: list[float] = []
    for at in sorted(at for k, at in glitches if k == kind):
        if not spots or at - spots[-1] > NEAR_S:
            spots.append(at)
    return spots


def _listed(places: list[str], most: int = 3) -> str:
    if len(places) > most:
        return f"{', '.join(places[:most])} and {len(places) - most} more places"
    if len(places) > 1:
        return f"{', '.join(places[:-1])} and {places[-1]}"
    return places[0]


def _glitches_together(earlier: list[list], now: list[list]) -> list[list]:
    """Glitches found by scans of a file, together: one found twice (a scan
    carries on from a little before where the last stopped) is kept once."""
    out: list[list] = []
    for kind, at in sorted((*earlier, *now), key=lambda g: g[1]):
        if any(k == kind and abs(at - a) < SPOT_S for k, a in out[-4:]):
            continue
        if len(out) < MOST_GLITCHES:
            out.append([kind, at])
    return out


def take_in(record: ScanRecord, before: ScanRecord, got: Scanned, seek: float) -> None:
    """Puts what a deep scan from `seek` has found so far together with
    what earlier scans of the file found (`before`), in `record`."""
    record.deep_at_s = max(before.deep_at_s, got.at)
    record.glitches = _glitches_together(before.glitches, got.glitches)
    record.bad_minutes = sorted({int(at // MINUTE_S) for _, at in record.glitches})
    record.picture_to_s = max(before.picture_to_s, got.picture_to)
    silences = list(got.silences)
    if got.silent_since is not None:
        silences.append((got.silent_since, got.at))
    heard = _heard(seek, got.at, silences)
    if heard is not None:
        first, last = heard
        record.sound_from_s = first if before.sound_from_s < 0 else min(before.sound_from_s, first)
        record.sound_to_s = max(before.sound_to_s, last)
    # Silences long enough to matter; and any that may be part of a longer
    # one, cut by a pause in the scan: one going on where it stopped, or
    # where it carried on (it goes back a little; they're joined up).
    long = [(a, b) for a, b in silences if b - a >= GAP_S or b >= got.at - 0.5 or a <= seek + 0.5]
    record.gaps = _merged([*before.gaps, *(["sound", a, b] for a, b in long)])
    # Black from where the scan had got to before (it goes back a little).
    record.black_s = before.black_s + sum(
        max(0.0, b - max(a, before.deep_at_s)) for a, b in got.blacks
    )


def _heard(
    start: float, end: float, silences: list[tuple[float, float]]
) -> tuple[float, float] | None:
    """The first and last moments with sound between `start` and `end`,
    given the silences in it; None if it's silent throughout."""
    first = last = None
    at = start
    for a, b in [*sorted(silences), (end, end)]:
        if a - at >= 0.5:
            first = at if first is None else first
            last = a
        at = max(at, b)
    return None if first is None or last is None else (first, last)


def _merged(gaps: list[list]) -> list[list]:
    """Gaps of one kind that overlap (found twice, as a scan carried on from
    a little before where it stopped) as one."""
    out: list[list] = []
    for kind, a, b in sorted(gaps, key=lambda g: (g[0], g[1])):
        if out and out[-1][0] == kind and a <= out[-1][2]:
            out[-1][2] = max(out[-1][2], b)
        else:
            out.append([kind, a, b])
    return out


def dropouts(
    record: ScanRecord, credits: list[tuple[float, float]] | None = None
) -> list[tuple[float, float]]:
    """Silences of GAP_S or more between sound: not before it starts or
    after it ends (how the sound ends is the quick check's to judge), nor
    in end credits (`credits`, as Plex marks them), nor before a closing
    logo or sign-off."""

    def in_credits(at: float) -> bool:
        return any(begin - CREDITS_LEEWAY_S <= at < end for begin, end in credits or ())

    return [
        (a, b)
        for kind, a, b in record.gaps
        if kind == "sound"
        and b - a >= GAP_S
        and a > record.sound_from_s
        and b < record.sound_to_s - CLOSING_SOUND_S
        and not in_credits(a)
    ]


def judge(
    record: ScanRecord,
    probe: ff.ProbeResult,
    year: int | None = None,
    credits: list[tuple[float, float]] | None = None,
) -> Verdict:
    """What a finished deep scan of a file found. `year`: the program's (a
    film before 1930 may have a silent sound track); `credits`: its end
    credits, as Plex marks them."""
    duration = probe.duration_s or 0.0
    picture = record.picture_to_s
    allowed = ff.shortfall_allowed(duration)
    if duration and picture < duration - allowed:
        return Verdict(
            "broken",
            f"the picture stops at {fmt_offset(round(picture))} of "
            f"{fmt_offset(round(duration))} (the file is cut short or damaged)",
        )
    if duration and picture > duration + allowed:
        return Verdict(
            "damaged",
            f"it plays to {fmt_offset(round(picture))}, past its stated length of "
            f"{fmt_offset(round(duration))}, so its ending would be cut off",
        )
    if picture > 0 and record.black_s >= ALL_BLACK * picture:
        return Verdict("damaged", "the picture is black all the way through")
    silent_film = year is not None and year < SOUND_FROM_YEAR
    if probe.audio_index is not None and not silent_film:
        if record.sound_from_s < 0:
            return Verdict("damaged", "the sound track is silent all the way through")
        for a, b in dropouts(record, credits)[:1]:
            return Verdict(
                "damaged", f"no sound from {fmt_offset(round(a))} to {fmt_offset(round(b))}"
            )
    glitches = [g for g in record.glitches if g[1] < picture - END_GRACE_S]
    if glitches:
        return Verdict("damaged", glitch_reason(glitches, probe.audio_codec))
    return Verdict("ok")


# The scanner ----------------------------------------------------------------------


@dataclass
class Program:
    """A file to check: a program's, as a station plays it (its library's
    first version), or another version of it, in Media."""

    item: Item
    station: int | None  # the number of a station it's on (None: only in Media)
    version: str = ""  # the version's ID, for one that isn't the program's first
    library: str | None = None  # the library it's in, if that's known

    @property
    def key(self) -> str:
        """Its file key (see broken.version_key)."""
        return version_key(self.item.rating_key, self.version)


def item_of(entry: Entry, media: Media) -> Item:
    """A version of a show's episode or a movie, as the checks take it."""
    return Item(
        position=0,
        start_ms=0,
        duration_ms=media.duration_ms or entry.duration_ms or 0,
        rating_key=entry.key,
        kind="episode" if entry.kind == catalog.EPISODE else "movie",
        title=entry.title,
        show_title=entry.show_title or None,
        show_key=entry.show_key,
        season=entry.season,
        episode=entry.episode,
        year=entry.year,
        file_path=media.file,
        part_key=media.part_key,
        library=entry.library or None,
    )


def versions_of(entry: Entry) -> list[Program]:
    """An episode's or a movie's files: its first version (the one a
    station plays), and any others with an ID (in Media)."""
    return [
        Program(item_of(entry, media), None, "" if n == 0 else media.id, entry.library or None)
        for n, media in enumerate(entry.media)
        if n == 0 or media.id
    ]


def version_of(entry: Entry, media: Media) -> str:
    """A version's ID, as its file key has it: "" for the first."""
    return "" if entry.media and media == entry.media[0] else media.id


def trouble(ctx: AppContext, entry: Entry, media: Media, at_s: float | None, why: str) -> None:
    """Someone had trouble playing a version of an episode or a movie in
    Media (`at_s`: where, if it's known): its file is checked first, there
    (see Target). Nothing about the file changes unless that finds what's
    wrong."""
    if entry.kind not in (catalog.EPISODE, catalog.MOVIE):
        return
    ctx.scanner.target(
        entry.key, version_of(entry, media), at_s, why, label=item_of(entry, media).label
    )


@dataclass
class Target:
    """A file someone just had trouble with (see the module's notes), to
    check before anything but what airs soon. Kept (META_TARGETS), in case
    of a restart."""

    key: str  # its file key (see broken.version_key)
    rating_key: str
    version: str = ""
    at_s: float | None = None  # where it went wrong, if that's known
    # A report that says where: the deep scan too, if the rest find nothing.
    full: bool = False
    why: str = ""  # what happened, as the log says it ("Tia reported No sound")
    station: int | None = None  # the station it was on, if it was
    reports: list[int] = field(default_factory=list)  # the reports waiting on it
    stage: str = STRETCH  # what's next
    tries: int = 0  # times it couldn't tell
    wait_until: float = 0.0  # (time.time(): not before, after one that couldn't)
    ran: list[str] = field(default_factory=list)  # what was checked, for the reports
    label: str = ""  # the program, as the log names it


class Scanner:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._wake = asyncio.Event()
        # idle, checking (quick checks), scanning, paused (someone's watching)
        self.state = "idle"
        self.current: str | None = None  # what's being deep-scanned
        self.current_pct = 0.0
        # Tonight's deep scan: files finished, and problems found.
        self._night = ""
        self.tonight = {"scanned": 0, "problems": 0}
        self._paused_logged = False
        # Files whose quick check couldn't tell lately: when to try again,
        # and how many times it couldn't (by file key).
        self._retry_at: dict[str, float] = {}
        self._skips: dict[str, int] = {}
        # Programs to quick-check before anything else (kept, in case of a
        # restart before they're checked; read at the first round).
        self._first: set[str] = set()
        self._first_read = False
        # Programs off the air for what the deep scan now judges anew: they
        # stay off it until scanned again (first of all), and come back on
        # if they're fine (kept, like _first).
        self._again: set[str] = set()
        self._again_read = False
        # The stations' programs that air soon (see SOON_S), as programs()
        # last found them.
        self.soon: set[str] = set()
        # Files someone had trouble with (see Target), oldest first.
        self._targets: list[Target] = []
        self._targets_read = False
        # Media: what's newly added (as last looked for: the libraries'
        # fingerprint then, and when), and the whole of it for the deep scan
        # (newest first: when it was fetched, and the file keys in it); and
        # what people are watching (when it was looked at).
        self._media_new: list[Program] = []
        self._media_print = ""
        self._media_looked = 0.0
        self._media_all: list[Program] = []
        self._media_all_at: float | None = None
        self._media_all_print = ""
        self.media_keys: set[str] = set()
        self._media_watched: list[Program] = []
        self._media_watched_at: float | None = None
        # Told what a target's check came to, for the reports waiting on it
        # (see reports.py): (their IDs, the outcome, a sentence about it).
        self.on_checked: Callable[[list[int], str, str], None] | None = None

    # Settings ---------------------------------------------------------------

    @property
    def window(self) -> tuple[bool, str, str]:
        """(deep scan on, start, end), as HH:MM local time."""
        on, _, rest = self.ctx.db.get_meta(META_WINDOW, "").partition("|")
        start, _, end = rest.partition("|")
        if not (_valid_time(start) and _valid_time(end)):
            return True, *DEFAULT_WINDOW
        return on != "off", start, end

    def set_window(self, on: bool, start: str, end: str) -> None:
        if not (_valid_time(start) and _valid_time(end)) or start == end:
            raise ValueError("Enter two different times for start and end, in HH:MM format")
        self.ctx.db.set_meta(META_WINDOW, f"{'on' if on else 'off'}|{start}|{end}")
        self._wake.set()

    def in_window(self, now: float | None = None) -> bool:
        """Whether the deep scan may run now: it's on, and in its hours."""
        return self.window[0] and self.in_hours(now)

    def in_hours(self, now: float | None = None) -> bool:
        """Whether it's within the overnight checks' hours (whether or not
        the deep scan is on: going through the broken-files list again
        starts then too)."""
        _, start, end = self.window
        t = time.localtime(time.time() if now is None else now)
        minute = t.tm_hour * 60 + t.tm_min
        a, b = _minutes(start), _minutes(end)
        return a <= minute < b if a < b else minute >= a or minute < b

    def wake(self) -> None:
        """Something changed (a station was saved): look for new programs now."""
        self._wake.set()

    def watching(self) -> bool:
        """Whether anyone's watching: a station, or Media in the apps."""
        return someone_watching(self.ctx)

    def _make_way(self) -> bool:
        """Whether checks wait now: while anyone's watching (said once)."""
        if self.watching():
            if not self._paused_logged:
                log.info("File checks paused while someone's watching")
                self._paused_logged = True
            self.state = "paused"
            return True
        if self._paused_logged:
            log.info("File checks resumed")
            self._paused_logged = False
        return False

    # What to check -----------------------------------------------------------

    def programs(self) -> list[Program]:
        """Every program on a station, once each: those in updates that
        haven't started yet first (they're about to arrive), then whatever
        airs soonest, then the rest. (And which of them air soon: see
        SOON_S.)"""
        db = self.ctx.db
        now = int(time.time() * 1000)
        arriving: dict[str, Program] = {}
        airs: dict[str, int] = {}
        rest: dict[str, Program] = {}
        for channel in db.list_channels():
            pending = self.ctx.updater.pending.get(channel.id)
            coming = (
                [*pending.items, *itertools.chain(*(pending.sets or {}).values())]
                if pending
                else []
            )
            for item in coming:
                arriving.setdefault(item.rating_key, Program(item, channel.number))
            for slot in self.ctx.station(channel.id).between(now, now + 24 * 3600 * 1000):
                key = slot.item.rating_key
                if slot.start_ms < airs.get(key, 1 << 62):
                    airs[key] = slot.start_ms
            # (With what its specials draw on: see specials.py.)
            for item in db.all_programs(channel.id):
                rest.setdefault(item.rating_key, Program(item, channel.number))
        ordered = sorted(rest, key=lambda k: (airs.get(k, 1 << 62), k))
        self.soon = set(arriving) | {k for k, at in airs.items() if at < now + SOON_S * 1000}
        return [*arriving.values(), *(rest[k] for k in ordered if k not in arriving)]

    def _due(self, programs: list[Program], scans: dict[str, ScanRecord]) -> list[Program]:
        """Programs that need a quick check: new, a new file, or not checked
        for a week."""
        broken = self.ctx.broken.keys()
        now = time.time() * 1000
        due = []
        for p in programs:
            key = p.key
            if key in broken or self._retry_at.get(key, 0) > now / 1000:
                continue
            record = scans.get(key)
            if (
                record is None
                or not record.quick_ms
                or now - record.quick_ms > (RECHECK_S + _spread(key)) * 1000
            ):
                due.append(p)
        return due

    # Running --------------------------------------------------------------------

    async def run_forever(self) -> None:
        await asyncio.sleep(STARTUP_DELAY_S)  # let everything else get going first
        while True:
            more = False
            try:
                more = await self.round()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Checking files failed; trying again shortly")
            if not more:
                await self._sleep(IDLE_S)

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), seconds)
        self._wake.clear()

    async def round(self) -> bool:
        """Checks a batch of what's due, in the queue's order (see the
        module's notes); then, with nothing else to do, deep-scans one file
        if it may. True if there's more to do straight away."""
        if not self.ctx.library.configured or self._make_way():
            return False
        try:
            # Files are looked up through Plex: no point while it's away.
            await asyncio.wait_for(self.ctx.library.check(), 10)
        except (LibraryError, TimeoutError):
            return False
        self._check_again_if_the_checks_changed()
        self._rules_changed()
        self._read_targets()
        programs = await asyncio.to_thread(self.programs)
        scans = self.ctx.db.scans()
        due = self._due(programs, scans)
        due.sort(key=lambda p: p.key not in self._first)  # (a stable sort)
        first = [p for p in due if p.key in self._first or p.key in self.soon]
        rest = [p for p in due if p not in first]
        new = [p for p in rest if (r := scans.get(p.key)) is None or not r.quick_ms]
        weekly = [p for p in rest if p not in new]
        media = await self._media_arrivals({p.key for p in programs}, scans)
        now = time.time()
        targets = [t for t in self._targets if t.wait_until <= now]
        queue: list[Program | Target] = [*first, *targets, *new, *media, *weekly]
        more = len(queue) > QUICK_BATCH
        skipped = 0  # in a row
        for job in queue[:QUICK_BATCH]:
            if self._make_way():
                return False  # (someone's started watching)
            self.state = "checking"
            if isinstance(job, Target):
                try:
                    await self._targeted(job)
                except Exception:
                    log.exception("Checking %s failed", _target_label(job))
                    self._later(job, "the check failed")
                continue
            key = job.key
            verdict = await self._quick(job, scans.get(key))
            if key in self._first:
                self._first.discard(key)
                self.ctx.db.set_meta(META_FIRST, json.dumps(sorted(self._first)))
            if not self._skipped(key, verdict):
                skipped = 0
                continue
            # Two in a row that couldn't tell: Plex or the share is likely down.
            skipped += 1
            if skipped == 2:
                more = False
                break
        self.state = "idle"
        if self.in_window() and not more:
            more = await self._deep_one(programs)
        elif not self.in_window():
            self._paused_logged = False
        if not more:
            self._forget_old(scans, programs)
        return more

    def _skipped(self, key: str, verdict: Verdict) -> bool:
        """Whether a quick check couldn't tell (the file was slow to read, or
        Plex or the share didn't answer): then it waits a while, so it can't
        hold up the rest, longer each time."""
        if verdict.result != "skipped":
            self._retry_at.pop(key, None)
            self._skips.pop(key, None)
            return False
        self._skips[key] = self._skips.get(key, 0) + 1
        wait = SKIPPED_RETRY_S * 2 ** (self._skips[key] - 1)
        self._retry_at[key] = time.time() + min(SKIPPED_RETRY_MOST_S, wait)
        return True

    # Media ------------------------------------------------------------------------

    def _media_from(self) -> float:
        """When the checks reached Media (seconds since 1970): what was
        added since is an arrival."""
        db = self.ctx.db
        try:
            return float(db.get_meta(META_MEDIA_FROM, ""))
        except ValueError:
            now = time.time()
            db.set_meta(META_MEDIA_FROM, str(int(now)))
            return now

    async def _media_arrivals(
        self, on_stations: set[str], scans: dict[str, ScanRecord]
    ) -> list[Program]:
        """What's newly added to the libraries shared for Media that's due
        its quick check, the newest first (not what a station has: that's
        the stations'). Looked for when the libraries change, and every
        MEDIA_LOOK_S."""
        ctx = self.ctx
        if not ctx.shared.on:
            return []
        since_ms = self._media_from() * 1000
        try:
            fingerprint = await asyncio.wait_for(ctx.library.fingerprint(), 10)
            if fingerprint != self._media_print or (
                time.monotonic() - self._media_looked >= MEDIA_LOOK_S
            ):
                found: list[Entry] = []
                for lib in await asyncio.wait_for(ctx.catalog.libraries(), 10):
                    start = 0
                    while start < MEDIA_NEW_MOST:
                        total, page = await asyncio.wait_for(
                            ctx.library.added_files(lib["key"], lib["kind"], start, MEDIA_PAGE), 30
                        )
                        newer = [e for e in page if (e.added_ms or 0) >= since_ms]
                        found += newer
                        start += len(page)
                        if len(newer) < len(page) or not page or start >= total:
                            break
                found.sort(key=lambda e: -(e.added_ms or 0))
                self._media_new = [p for e in found for p in versions_of(e)]
                self._media_print, self._media_looked = fingerprint, time.monotonic()
        except (LibraryError, TimeoutError) as e:
            log.info("Couldn't look for what's new in Media now (%s)", e or "Plex didn't answer")
        return [p for p in self._media_new if self._media_due(p, scans, on_stations)]

    def _media_due(self, p: Program, scans: dict[str, ScanRecord], on_stations: set[str]) -> bool:
        """Whether a file of Media's needs its quick check: never checked, or
        its file has changed since (not one a station has, or on the list,
        or one whose check is waiting to try again)."""
        key = p.key
        if key in on_stations or self.ctx.broken.is_broken(key):
            return False
        if self._retry_at.get(key, 0) > time.time():
            return False
        return _unchecked(scans.get(key), p.item)

    async def _media_watching(self) -> list[Program]:
        """Media's files people are watching, for the deep scan: what's in
        someone's Continue Watching, then the next episode of a show someone
        is watching (kept MEDIA_WATCHED_S)."""
        now = time.monotonic()
        if self._media_watched_at is not None and now - self._media_watched_at < MEDIA_WATCHED_S:
            return self._media_watched
        ctx = self.ctx
        cat = ctx.catalog
        going: list[Entry] = []
        for user_id in [0, *(u.id for u in ctx.db.users())]:
            with contextlib.suppress(LibraryError, ondemand.NotShared, TimeoutError):
                going += [e for e, _ in await ondemand.continue_watching(cat, ctx.db, user_id)]
        keys = list(dict.fromkeys(e.key for e in going))
        after: list[str] = []
        for e in going:
            if e.kind != catalog.EPISODE or not e.show_key:
                continue
            with contextlib.suppress(LibraryError, ondemand.NotShared, TimeoutError):
                episodes = [x for x in await cat.episodes(e.show_key) if x.season != 0]
                at = next((n for n, x in enumerate(episodes) if x.key == e.key), None)
                if at is not None and at + 1 < len(episodes):
                    after.append(episodes[at + 1].key)
        found: list[Program] = []
        for key in dict.fromkeys([*keys, *after]):
            with contextlib.suppress(LibraryError, ondemand.NotShared, TimeoutError):
                found += versions_of(await cat.entry(key))
        self._media_watched, self._media_watched_at = found, now
        return found

    async def _media_everything(self) -> list[Program]:
        """Media's files the deep scan may have to do, the most recently
        added first. Fetched again when the libraries have changed, looked
        at most every MEDIA_ALL_S; only those not yet done are kept (each is
        looked at again as its turn comes), and the file keys of all of
        them (media_keys)."""
        now = time.monotonic()
        if self._media_all_at is not None and now - self._media_all_at < MEDIA_ALL_S:
            return self._media_all
        ctx = self.ctx
        fingerprint = await asyncio.wait_for(ctx.library.fingerprint(), 10)
        if self._media_all_at is not None and fingerprint == self._media_all_print:
            self._media_all_at = now
            return self._media_all
        entries: list[Entry] = []
        for lib in await asyncio.wait_for(ctx.catalog.libraries(), 10):
            start, total = 0, 1
            while start < total:
                total, page = await asyncio.wait_for(
                    ctx.library.added_files(lib["key"], lib["kind"], start, MEDIA_ALL_PAGE), 60
                )
                entries += page
                start += len(page)
                if not page:
                    break
        entries.sort(key=lambda e: -(e.added_ms or 0))
        every = [p for e in entries for p in versions_of(e)]
        scans = ctx.db.scans()
        self.media_keys = {p.key for p in every}
        self._media_all = [p for p in every if _deep_due(scans.get(p.key), p.item)]
        self._media_all_at, self._media_all_print = now, fingerprint
        return self._media_all

    async def _media_deep_order(self, on_stations: set[str]) -> list[Program]:
        """Media's files in the deep scan's order (see the module's notes),
        each once, but for what a station has (that's the stations')."""
        try:
            watching = await self._media_watching()
            rest = await self._media_everything()
        except (LibraryError, TimeoutError) as e:
            log.info(
                "Couldn't list Media's files for the deep scan now (%s)", e or "Plex didn't answer"
            )
            return []
        out: dict[str, Program] = {}
        for p in [*watching, *rest]:
            if p.key not in on_stations:
                out.setdefault(p.key, p)
        return list(out.values())

    # Files someone had trouble with ------------------------------------------------

    def _read_targets(self) -> None:
        if self._targets_read:
            return
        self._targets_read = True
        names = {f.name for f in fields(Target)}
        for got in _json_list(self.ctx.db.get_meta(META_TARGETS, "[]")):
            if isinstance(got, dict) and got.get("key") and got.get("rating_key"):
                with contextlib.suppress(TypeError, ValueError):
                    self._targets.append(Target(**{k: v for k, v in got.items() if k in names}))

    def _save_targets(self) -> None:
        self.ctx.db.set_meta(META_TARGETS, json.dumps([asdict(t) for t in self._targets]))

    def target(
        self,
        rating_key: str,
        version: str = "",
        at_s: float | None = None,
        why: str = "",
        station: int | None = None,
        report: int | None = None,
        full: bool = False,
        label: str = "",
    ) -> Target:
        """A file someone just had trouble with, to check at the front of
        the queue (see Target): one already waiting takes in what's new."""
        self._read_targets()
        key = version_key(rating_key, version)
        found = next((t for t in self._targets if t.key == key), None)
        if found is None:
            found = Target(key, rating_key, version, at_s, full, why, station, label=label)
            self._targets.append(found)
        else:
            if at_s is not None and (found.at_s is None or abs(found.at_s - at_s) > STRETCH_S / 2):
                # (Somewhere else in it: that stretch is checked, then the rest again.)
                found.at_s, found.stage = at_s, STRETCH
            found.full = found.full or full
            found.why = why or found.why
            found.station = found.station or station
            found.label = found.label or label
            found.wait_until = 0.0
        if report is not None and report not in found.reports:
            found.reports.append(report)
        if len(self._targets) > TARGETS_MOST:
            # (Too many waiting: the oldest goes, one no one reported if there's
            # one, so trouble the apps send can't crowd out people's reports.)
            dropped = next((t for t in self._targets if not t.reports), self._targets[0])
            self._done_with(
                dropped, COULDNT, "StationPlay had too many files to check at once, so it let "
                "this one go."
            )  # fmt: skip
        self._save_targets()
        log.info("Checking %s first: %s", _target_label(found), why)
        self._wake.set()
        return found

    def waiting(self, key: str) -> bool:
        """Whether a file's check is waiting (see Target)."""
        self._read_targets()
        return any(t.key == key for t in self._targets)

    def _done_with(self, target: Target, outcome: str, note: str = "") -> None:
        """A target's check came to `outcome` (FOUND, KEPT, NOTHING, GONE or
        COULDNT): it's done with, and the reports waiting on it are told."""
        if target in self._targets:
            self._targets.remove(target)
            self._save_targets()
        if target.reports and self.on_checked is not None:
            self.on_checked(target.reports, outcome, note)
        if outcome == NOTHING:
            log.info(
                "%s: StationPlay found nothing wrong with its file (%s), so it stays as it is",
                _target_label(target),
                target.why,
            )

    def _later(self, target: Target, why: str) -> None:
        """A target's check couldn't tell now: tried again in a while, up to
        TARGET_TRIES times in all."""
        target.tries += 1
        if target.tries >= TARGET_TRIES:
            self._done_with(target, COULDNT, f"StationPlay couldn't check its file ({why}).")
            return
        target.wait_until = time.time() + min(
            SKIPPED_RETRY_MOST_S, SKIPPED_RETRY_S * 2 ** (target.tries - 1)
        )
        self._save_targets()

    async def _targeted(self, target: Target) -> None:
        """Checks a file someone had trouble with, a stage at a time (see
        Target), until what StationPlay finds says what's to be done."""
        ctx = self.ctx
        try:
            entry = await asyncio.wait_for(ctx.library.entry(target.rating_key, details=True), 30)
        except (LibraryError, TimeoutError) as e:
            self._later(target, str(e) or "Plex didn't answer")
            return
        versions = list(entry.media) if entry is not None else []
        media = next(
            (m for n, m in enumerate(versions) if (m.id if n else "") == target.version), None
        )
        if entry is None or media is None or entry.kind not in (catalog.EPISODE, catalog.MOVIE):
            self._done_with(target, GONE, "It's no longer in Plex")
            return
        program = Program(item_of(entry, media), target.station, target.version, entry.library)
        target.label = program.item.label
        listed = ctx.broken.entry(target.key)
        if listed is not None:
            self._done_with(target, FOUND, str(listed.get("reason") or ""))
            return
        if target.stage == STRETCH:
            if target.at_s is not None and await self._stretch(program, target):
                return
            target.stage = QUICK
            self._save_targets()
        record = ctx.db.scan(target.key)
        if target.stage == FULL and (record is None or record.quick != "ok"):
            target.stage = QUICK  # (a new file since: its quick check comes first)
        if target.stage == QUICK:
            verdict, record, resolved = await quick_verdict(
                ctx, program.item, record, target.version
            )
            if verdict.result == "skipped":
                self._later(target, verdict.reason or "the file couldn't be read")
                return
            target.ran.append("the quick check")
            if record is not None:
                ctx.db.save_quick(record)
            if verdict.result != "ok":
                self._found(target, program, record, f"Check: {verdict.reason}", verdict.result,
                            CHECK, resolved)  # fmt: skip
                return
            if record is not None and record.kept and record.deep in ("broken", "damaged"):
                # (Its deep scan found something before, and you put it back on the air.)
                self._done_with(target, KEPT, f"Deep scan: {record.note}")
                return
            if not target.full or record is None or record.deep_ms:
                self._done_with(target, NOTHING, _nothing_found(target))
                return
            target.stage = FULL
            self._save_targets()
        if record is None or record.deep_ms:
            self._done_with(target, NOTHING, _nothing_found(target))
            return
        if not await self.deep_scan(program, record, anytime=True):
            if not self.watching():  # (stopped for a viewer: it carries on later)
                self._later(target, "the file couldn't be read now")
            return
        record = ctx.db.scan(target.key)
        if record is None or not record.deep_ms:
            self._later(target, (record.note if record is not None else "") or "it can't be read")
            return
        target.ran.append("the deep scan")
        if record.deep not in ("broken", "damaged"):
            self._done_with(target, NOTHING, _nothing_found(target))
        elif record.kept:
            self._done_with(target, KEPT, f"Deep scan: {record.note}")
        else:
            self._done_with(target, FOUND, f"Deep scan: {record.note}")

    async def _stretch(self, program: Program, target: Target) -> bool:
        """The stretch of a file where someone had trouble with it (see
        check_stretch). True if it found what's wrong (and the target's
        done with)."""
        assert target.at_s is not None
        record = self.ctx.db.scan(target.key)
        resolved = await resolve(self.ctx, program.item, program.version)
        if resolved.error or not resolved.source:
            return False  # (the quick check says what's what)
        probe = await ff.probe(self.ctx.settings, resolved.source)
        if not probe.ok:
            return False
        verdict, start = await check_stretch(self.ctx, resolved.source, probe, target.at_s)
        if verdict.result == "skipped":
            return False
        stretch = f"{fmt_offset(start)} to {fmt_offset(start + STRETCH_S)}"
        target.ran.append(f"from {stretch}")
        if verdict.result == "ok":
            return False
        reason = f"Check from {fmt_offset(start)}: {verdict.reason}"
        self._found(target, program, record, reason, verdict.result, TARGETED, resolved)
        return True

    def _found(
        self,
        target: Target,
        program: Program,
        record: ScanRecord | None,
        reason: str,
        problem: str,
        how: str,
        resolved: ResolvedSource,
    ) -> None:
        """A target's check found what's wrong: the file goes on the list
        (unless an Admin put it back on the air before)."""
        if record is not None and record.kept and record.file == resolved.plex_file:
            log.info(
                "Checking %s found a problem (%s), but you put it back on the air, so it stays on",
                _target_label(target),
                reason,
            )
            self._done_with(target, KEPT, reason)
            return
        self.ctx.broken.record(
            program.item, reason, program.station, resolved.plex_file, resolved.size,
            problem=problem, found=how, version=program.version, library=program.library,
        )  # fmt: skip
        self._done_with(target, FOUND, reason)

    def _check_again_if_the_checks_changed(self) -> None:
        """When the checks change, every program's file is checked again by
        the new ones; and what the quick check (or playing it, for ending a
        few seconds early) took off the air before is looked at afresh: it's
        checked again first, and goes back off the air if it's still a
        problem."""
        db = self.ctx.db
        if not self._first_read:
            self._first.update(_json_list(db.get_meta(META_FIRST, "[]")))
            self._first_read = True
        if db.get_meta(META_CHECKS, "") == CHECKS:
            return
        # Due now, as if checked a week and a day ago (not never: records of
        # programs on no station are forgotten a month after their check).
        db.check_all_again(int((time.time() - RECHECK_S - 86_400 - 1) * 1000))
        again = [file_key(e) for e in self.ctx.broken.entries() if _judged_again(e)]
        self._first.update(again)
        db.set_meta(META_FIRST, json.dumps(sorted(self._first)))
        for key in again:
            self.ctx.broken.remove(key)
        db.set_meta(META_CHECKS, CHECKS)
        if db.scans():
            log.info(
                "The file checks have changed, so every program's file will be checked again%s",
                f". Programs taken off the air under the old rules ({len(again)}) are back on "
                "the air and will be checked first"
                if again
                else "",
            )

    def _rules_changed(self) -> None:
        """When how the deep scan judges files changes, the files it may judge
        differently are deep-scanned again: those it found any glitches in
        (fine or not), unless you put them back on the air. Those it took
        off the air for them stay off it until they're judged again."""
        db = self.ctx.db
        if not self._again_read:
            self._again.update(_json_list(db.get_meta(META_AGAIN, "[]")))
            self._again_read = True
        if db.get_meta(META_DEEP_RULES, "") == DEEP_RULES:
            return
        broken = {file_key(e): e for e in self.ctx.broken.entries()}
        again = {k for k, e in broken.items() if str(e.get("reason", "")).startswith(_JUDGED_ANEW)}
        scans = db.scans()
        anew = sorted(
            k
            for k, r in scans.items()
            if k in again or (r.bad_minutes and not r.kept and k not in broken)
        )
        db.deep_scan_again(anew)
        self._again.update(again)
        db.set_meta(META_AGAIN, json.dumps(sorted(self._again)))
        db.set_meta(META_DEEP_RULES, DEEP_RULES)
        if anew:
            log.info(
                "Deep scan rules changed: %d file%s with glitches will be rescanned%s",
                len(anew),
                "" if len(anew) == 1 else "s",
                f". Files off the air for glitches ({len(again)}) are rescanned first and stay "
                "off the air until then"
                if again
                else "",
            )

    def _judged_anew(self, key: str, result: str, reason: str) -> bool:
        """What scanning a file again found, for its entry on the list (if
        it's still there for what's judged anew): off the list if it's fine
        now, or what's wrong with it now. True if the entry was there."""
        self._again.discard(key)
        self.ctx.db.set_meta(META_AGAIN, json.dumps(sorted(self._again)))
        entry = self.ctx.broken.entry(key)
        if entry is None or not str(entry.get("reason", "")).startswith(_JUDGED_ANEW):
            return False
        seen = {key: entry.get("lastFailed")}
        if result == "ok":
            return bool(self.ctx.broken.settle(seen, {key}, {}))
        now = {"reason": f"Deep scan: {reason}"[:500], "problem": result}
        self.ctx.broken.settle(seen, set(), {key: now})
        return True

    async def _quick(self, program: Program, record: ScanRecord | None) -> Verdict:
        verdict, record = await quick_check_item(
            self.ctx, program.item, program.station, record, program.version, program.library
        )
        if record is not None:
            self.ctx.db.save_quick(record)
        return verdict

    async def _deep_one(self, programs: list[Program]) -> bool:
        """Deep-scans the next file that needs it: the stations' programs
        first, then Media's (see the module's notes; one of Media's that
        hasn't had its quick check has that first). True if there may be
        more to do now."""
        night = time.strftime("%Y-%m-%d", time.localtime(time.time() - 12 * 3600))
        if self._night != night:
            self._night, self.tonight = night, {"scanned": 0, "problems": 0}
        scans = self.ctx.db.scans()
        broken = self.ctx.broken.keys()
        if self._again - broken:  # (cleared meanwhile)
            self._again &= broken
            self.ctx.db.set_meta(META_AGAIN, json.dumps(sorted(self._again)))
        for program in sorted(programs, key=lambda p: p.key not in self._again):
            key = program.key
            record = scans.get(key)
            if (
                record is None
                or record.quick != "ok"
                or record.deep_ms
                or (key in broken and key not in self._again)
                or self._retry_at.get(key, 0) > time.time()  # its quick check is waiting
                or record.note.endswith(_night_note(night))  # tried tonight: another night
            ):
                continue
            if self._make_way():
                return False
            return await self.deep_scan(program, record)
        if not self.ctx.shared.on:
            return False
        for program in await self._media_deep_order({p.key for p in programs}):
            key = program.key
            record = scans.get(key)
            if (
                key in broken
                or self._retry_at.get(key, 0) > time.time()
                or self.waiting(key)  # (someone had trouble with it: that's checked first)
                or (record is not None and not _unchecked(record, program.item) and (
                    record.quick != "ok"
                    or record.deep_ms
                    or record.note.endswith(_night_note(night))
                ))
            ):  # fmt: skip
                continue
            if self._make_way():
                return False
            if record is None or _unchecked(record, program.item):
                self.state = "checking"
                self._skipped(key, await self._quick(program, record))
                self.state = "idle"
                return True
            return await self.deep_scan(program, record)
        return False

    async def deep_scan(self, program: Program, record: ScanRecord, anytime: bool = False) -> bool:
        """Decodes a program's whole file, from where an earlier scan got
        to. True if it finished with the file; False if it stopped (the
        window ended, or someone started watching) and will carry on later.
        `anytime`: in or out of the window (for someone's report: see
        Target)."""
        item = program.item
        resolved = await resolve(self.ctx, item, program.version)
        if resolved.error or not resolved.source:
            return False  # Plex or the share is down; the quick check handles gone files
        if (resolved.plex_file or resolved.source) != record.file:
            # A new file since its quick check: that comes first.
            record.quick_ms, record.quick = 0, ""
            self.ctx.db.save_scan(record)
            return True
        probe = await ff.probe(self.ctx.settings, resolved.source)
        if not probe.ok:
            self._another_night(record, f"couldn't be opened ({probe.error})")
            return True
        duration = probe.duration_s or 0.0
        start = record.deep_at_s
        log.info(
            "Deep-scanning %s%s",
            item.label,
            f", resuming at {fmt_offset(start)}" if start else "",
        )
        self.state, self.current = "scanning", item.label
        saved = time.monotonic()
        seek = max(0.0, start - RESUME_BACK_S) if start else 0.0
        before = replace(
            record,
            bad_minutes=list(record.bad_minutes),
            gaps=list(record.gaps),
            glitches=list(record.glitches),
        )
        over = False  # this scan's done with: nothing more is taken in

        def progress(got: Scanned) -> None:
            nonlocal saved
            if over:
                return
            self.current_pct = min(99.0, 100 * got.at / duration) if duration else 0.0
            take_in(record, before, got, seek)
            if time.monotonic() - saved > SAVE_EVERY_S:
                saved = time.monotonic()
                self.ctx.db.save_scan(record)  # so a restart carries on from here

        task = asyncio.create_task(
            decode_through(
                self.ctx,
                resolved.source,
                seek,
                probe.video_index,
                probe.audio_index,
                progress,
                count_from=seek + (SEEK_GRACE_S if seek else START_GRACE_S),
                rate=probe.audio_rate,
            )
        )
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=WATCH_POLL_S)
                if not task.done() and (self.watching() or not (anytime or self.in_window())):
                    self.state = "paused" if self.watching() else "idle"
                    task.cancel()  # kills ffmpeg
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    return False
            got = task.result()
            progress(got)
        except Exception:
            log.exception("Deep scan of %s failed; trying again another night", item.label)
            self._another_night(record, "the scan failed")
            return True
        finally:
            task.cancel()  # if this was stopped from outside
            self.current, self.current_pct = None, 0.0
            self.ctx.db.save_scan(record)  # so it carries on from here
            over = True
            if self.state == "scanning":
                self.state = "idle"
        if got.stalled:
            log.info(
                "Deep scan of %s stalled at %s; trying again another night",
                item.label,
                fmt_offset(got.at),
            )
            self._another_night(record, f"stalled at {fmt_offset(got.at)}")
            return True
        if got.unreadable:
            return self._read_failure(program, record, resolved, got.at)
        if max(got.at, got.picture_to) <= seek + 1.0:
            if seek:
                # Carrying on, it landed at the end (jumping into some files
                # is rough): from the start, then, next time.
                self.ctx.db.save_scan(
                    ScanRecord(
                        program.key,
                        record.file,
                        record.size,
                        record.quick_ms,
                        record.quick,
                        kept=record.kept,
                    )
                )
                return True
            # Nothing decoded at all, though the quick check found picture
            # and sound: the share let it down (it can say so in more ways
            # than a read error), not the file.
            self._another_night(record, "nothing could be read")
            return True
        credits = None
        if dropouts(record):
            try:
                credits = await credits_of(self.ctx, item)
            except Unknown as e:
                self._another_night(record, str(e))
                return True
        verdict = judge(record, probe, item.year, credits)
        self._finish(program, record, resolved, verdict.result, verdict.reason)
        return True

    def _read_failure(
        self,
        program: Program,
        record: ScanRecord,
        resolved: ResolvedSource,
        at: float,
    ) -> bool:
        """Nothing could be read at `at`: tried again another night before
        the file counts as broken there (a share can drop out)."""
        record.tries += 1
        record.deep_at_s = at
        if record.tries < READ_FAILURES:
            self._another_night(record, f"couldn't be read at {fmt_offset(at)}")
            log.info(
                "Deep scan couldn't read %s at %s; trying again another night",
                program.item.label,
                fmt_offset(at),
            )
            return True
        why = f"the file can't be read at {fmt_offset(at)} (a disk or share error)"
        self._finish(program, record, resolved, "broken", why)
        return True

    def _another_night(self, record: ScanRecord, why: str) -> None:
        """This file's deep scan waits for another night."""
        record.note = f"{why}{_night_note(self._night)}"
        self.ctx.db.save_scan(record)

    def _finish(
        self,
        program: Program,
        record: ScanRecord,
        resolved: ResolvedSource,
        result: str,
        reason: str,
    ) -> None:
        record.deep, record.note = result, reason
        record.deep_ms = int(time.time() * 1000)
        self.ctx.db.save_scan(record)
        self.tonight["scanned"] += 1
        key = program.key
        again = key in self._again
        anew = again and self._judged_anew(key, result, reason)
        if result == "ok":
            if anew:
                log.info(
                    "Deep scan: %s passed its rescan and is back on the air", program.item.label
                )
            return
        self.tonight["problems"] += 1
        if record.kept:
            log.info(
                "Deep scan found a problem in %s (%s), but you put it back on the air, so it "
                "stays on",
                program.item.label,
                reason,
            )
            return
        if again:
            # (Its entry says so now; or it went meanwhile: a new file came, say.)
            if anew:
                log.info(
                    "Deep scan: %s failed its rescan (%s) and stays off the air",
                    program.item.label,
                    reason,
                )
            return
        self.ctx.broken.record(
            program.item,
            f"Deep scan: {reason}",
            program.station,
            resolved.plex_file,
            resolved.size,
            problem=result,
            found=DEEP_SCAN,
            version=program.version,
            library=program.library,
        )

    def _forget_old(self, scans: dict[str, ScanRecord], programs: list[Program]) -> None:
        """Records of files on no station, and not in Media, that haven't
        been checked for a month. (Not while Media's files aren't all known:
        they're checked once, and their records are kept.)"""
        if self.ctx.shared.on and self._media_all_at is None:
            return
        current = {p.key for p in programs} | self.media_keys
        cutoff = time.time() * 1000 - 30 * 24 * 3600 * 1000
        old = [
            k
            for k, r in scans.items()
            if k not in current and r.quick_ms < cutoff and not self.waiting(k)
        ]
        if old:
            self.ctx.db.forget_scans(old)

    def as_dict(self) -> dict:
        db = self.ctx.db
        programs = {i.rating_key for c in db.list_channels() for i in db.all_programs(c.id)}
        scans = db.scans()
        now = time.time() * 1000
        fresh = (RECHECK_S + 86_400) * 1000
        on, start, end = self.window
        return {
            "programs": len(programs),
            "quickChecked": sum(
                1
                for k in programs
                if (r := scans.get(k)) is not None and r.quick_ms and now - r.quick_ms < fresh
            ),
            "deepScanned": sum(
                1 for k in programs if (r := scans.get(k)) is not None and r.deep_ms
            ),
            # Media's files, while a library is shared with the apps (how
            # many, once they're all known: see _media_everything).
            "media": (
                {
                    "files": len(self.media_keys),
                    "quickChecked": sum(
                        1 for k in self.media_keys if (r := scans.get(k)) is not None and r.quick_ms
                    ),
                    "deepScanned": sum(
                        1 for k in self.media_keys if (r := scans.get(k)) is not None and r.deep_ms
                    ),
                }
                if self._media_all_at is not None
                else {"files": None, "quickChecked": None, "deepScanned": None}
            )
            if self.ctx.shared.on
            else None,
            "checking": len(self._targets),  # (files someone had trouble with)
            "window": {"on": on, "start": start, "end": end},
            "inWindow": self.in_window(),
            "state": self.state,
            "current": self.current,
            "currentPct": round(self.current_pct),
            "tonight": self.tonight,
        }


def someone_watching(ctx: AppContext) -> bool:
    """Whether anyone's watching now: a station, or Media in the apps."""
    return any(b.viewers for b in list(ctx.broadcasters.values())) or bool(ctx.plays.now())


def _unchecked(record: ScanRecord | None, item: Item) -> bool:
    """Whether a file hasn't had its quick check: never, or not since it
    changed (as the library says it is now)."""
    if record is None or not record.quick_ms:
        return True
    return bool(item.file_path) and record.file != item.file_path


def _deep_due(record: ScanRecord | None, item: Item) -> bool:
    """Whether a file may still need the deep scan: its quick check first,
    or it passed that and hasn't been deep-scanned."""
    if record is None or _unchecked(record, item):
        return True
    return record.quick == "ok" and not record.deep_ms


def _target_label(target: Target) -> str:
    return target.label or f"Plex item {target.rating_key}"


def _nothing_found(target: Target) -> str:
    """What a target's check did, finding nothing, as its reports say it:
    "StationPlay checked it from 12:11 to 13:11, then gave it the quick
    check and the deep scan, and found nothing wrong."."""
    stretches = [r for r in target.ran if r.startswith("from ")]
    checks = [r for r in target.ran if not r.startswith("from ")]
    did = f"checked it {' and '.join(stretches)}" if stretches else ""
    if checks:
        gave = f"gave it {' and '.join(checks)}"
        did = f"{did}, then {gave}" if did else gave
    return f"StationPlay {did or 'checked it'}, and found nothing wrong."


def _judged_again(entry: dict) -> bool:
    """Whether new checks judge again what took this program off the air:
    the quick check, or playing it, for ending a few seconds early (now
    that playing and checking agree on how short a file may end, see
    ff.shortfall_allowed). Not a program that stopped well before the end
    of its file."""
    reason = str(entry.get("reason", ""))
    if reason.startswith("Check: "):
        return True
    ended = _ENDED_EARLY.match(reason)
    if ended is None:
        return False
    at, of = (_seconds(t) for t in ended.groups())
    return played_whole(at, of)


def _seconds(text: str) -> float:
    """Seconds from "1:02:03" or "2:03"."""
    total = 0.0
    for part in text.split(":"):
        total = total * 60 + float(part)
    return total


def _json_list(text: str) -> list:
    try:
        value = json.loads(text)
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def _valid_time(text: str) -> bool:
    h, sep, m = text.partition(":")
    return bool(sep) and h.isdigit() and m.isdigit() and len(m) == 2 and int(h) < 24 and int(m) < 60


def _minutes(text: str) -> int:
    h, _, m = text.partition(":")
    return int(h) * 60 + int(m)


def _night_note(night: str) -> str:
    return f", on the night of {night}"


def _spread(key: str) -> float:
    """Up to a day, different for each program, so weekly checks don't all
    come due at once."""
    return float(zlib.crc32(key.encode()) % 86_400)
