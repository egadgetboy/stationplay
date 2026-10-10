"""Copies of a program that StationPlay makes for a device that can't play
its file as it is (see docs/on-demand.md): **repackaged**, the picture kept
as it is in a new package, the sound converted where the device needs it;
or **converted**, the picture made into H.264 too (smaller, ordinary rather
than HDR, or with subtitles drawn in). An episode's sound is also made again
for even sound across a show's episodes, and night mode's for an app that
can't make it (see sound_chain).

A copy is HLS: a playlist listing the whole program from its start, in
pieces of about PIECE_S seconds, so the player shows its whole length and
seeks anywhere. The pieces are made as they're asked for, by one ffmpeg at a
time, from where the player is; a jump far ahead or back starts it again
there. ffmpeg writes one MPEG-TS stream, and StationPlay cuts it into the
pieces itself, at the keyframes the playlist says each piece starts on: a
repackaged picture's own keyframes (read from the file's index: see
keyframes.py), or for a converted one, keyframes made every PIECE_S seconds.
Every piece has the program's own times in it, so pieces made by different
runs line up.

A converted picture is encoded where the stations' is: on the GPU while
GpuManager has one in use (see gpu.py), otherwise on the CPU. If a run fails
on the GPU, the copy carries on from there on the CPU and stays there; that
isn't counted against the copy (see FAILURES_MOST), and GpuManager is told.
Copies have strikes of their own there (gpu.COPY_STRIKES_LIMIT), so a
copy's trouble on the GPU never takes it from the stations. A copy also
moves to the CPU, with nothing counted, once the GPU is turned off.

Pieces are made a little ahead of the player and no further (ffmpeg simply
waits until they're wanted), kept a little behind it, and the rest deleted;
all are deleted when the copy stops. A copy stops when its play session
ends, and its ffmpeg stops when nothing has asked for a piece in IDLE_S
(it starts again where the player is, if it comes back).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from . import catalog
from .catalog import Media, Track
from .ffmpeg import (
    CPU,
    LOUDNESS_TARGET,
    SUBTITLE_STYLE,
    Encoder,
    Subtitles,
    filter_path,
    hw_input_args,
    redact,
)

if TYPE_CHECKING:
    from .gpu import GpuManager

log = logging.getLogger(__name__)

PIECE_S = 6.0  # how long a piece is meant to be (a repackaged one: to the next keyframe after)
SHORTEST_LAST_S = 1.0  # a last piece shorter than this goes with the one before
# Times in each piece are the program's own plus this (as written by ffmpeg:
# -output_ts_offset), so nothing is ever before zero.
TS_OFFSET_S = 10.0
VIDEO_PID = 0x100  # (-mpegts_start_pid: the picture is the first stream)
TS_PACKET = 188
# A keyframe starts a piece when it's this close to where the piece starts
# (a converted picture's keyframe is the first frame on or after it).
MATCH_BEFORE_S = 0.02
MATCH_AFTER_S = 0.25
AHEAD = 6  # pieces made ahead of the furthest one asked for
BEHIND = 4  # pieces kept behind the furthest one asked for
JUMP = 3  # a piece this far past the newest made starts ffmpeg again there
WAIT_S = 45.0  # how long a player waits for a piece being made
IDLE_S = 120.0  # ffmpeg stops when nothing has asked for a piece in this long
# A run that writes nothing, or nothing that starts a piece, for this long
# has stalled (a share gone quiet, say): it's stopped, as having failed.
STALL_S = 60.0
# After a run fails, the next waits this long; after this many in a row, the
# copy is given up on (the file can't be read, say).
RETRY_S = 2.0
FAILURES_MOST = 3
READ_TIMEOUT_US = 30_000_000  # (reading a file from Plex: ffmpeg's -rw_timeout)
# Converting the picture: H.264 High, at most this big, at these bitrates.
CONVERT_HEIGHTS = ((2160, 20_000), (1440, 12_000), (1080, 8_000), (720, 4_000), (480, 2_000))
CONVERT_MOST_HEIGHT = 1080
LEAST_KBPS = 1_000
# A picture made to fit the Admin's cap on Media away from home (see
# away.py) gets at least this, however low the cap.
LEAST_CAPPED_KBPS = 300
# On a GPU, frames between keyframes at most, besides the keyframe where each
# piece starts (as libx264 makes them on the CPU).
GPU_GOP = 250
AUDIO_KBPS = 192
SURROUND_KBPS = 640  # (Dolby Digital 5.1)
AAC_SURROUND_KBPS = 384
# Sound formats a device that takes surround sound lists (one asking for a
# converted copy gets its sound as AAC 5.1 then: see sound_for).
SURROUND = frozenset({"ac3", "eac3", "dts", "truehd"})
# Sound kept as it is in a copy, when the device plays it (MPEG-TS carries these).
TS_AUDIO = frozenset({"aac", "ac3", "eac3", "mp3", "mp2"})
# Even sound for a show's episodes (see applibrary.py): the stations' own
# loudness normalization (ffmpeg.LOUDNESS_TARGET, in one pass), which works
# at 192 kHz inside, so it's brought back to 48 kHz after.
EVEN_SOUND = f"loudnorm={LOUDNESS_TARGET},aresample=48000"

REPACKAGE = "repackage"
CONVERT = "convert"


class CantCopy(Exception):
    """A copy can't be made: the reasons, in words."""

    def __init__(self, why: list[str]) -> None:
        super().__init__("; ".join(why))
        self.why = why


@dataclass(frozen=True)
class Plan:
    """How a copy is made."""

    method: str  # REPACKAGE or CONVERT
    why: tuple[str, ...]  # why the file can't play as it is
    starts: tuple[float, ...]  # where each piece starts, in seconds
    duration_s: float
    audio: Track | None  # the sound track in the copy
    audio_codec: str  # "copy", "aac" or "ac3" (see sound_for)
    picture: str = ""  # the file's picture's format ("h264", "hevc")
    audio_channels: int = 2
    night: bool = False
    even: bool = False  # even sound for a show's episodes (see sound_chain)
    # Converting the picture:
    height: int = 0
    kbps: int = 0
    tone_map: str = ""  # filters making an HDR picture ordinary
    subtitles: Subtitles | None = None  # drawn into the picture
    drawn: str | None = None  # the subtitle track drawn in

    @property
    def copies_picture(self) -> bool:
        return self.method == REPACKAGE

    @property
    def kbps_needed(self) -> int | None:
        """What the copy needs, in kilobits a second (None: as the file)."""
        if self.method == REPACKAGE:
            return None
        return self.kbps + sound_kbps(self.audio_codec, self.audio_channels)


# Pieces and the playlist --------------------------------------------------------------


def pieces_at(keyframes: Iterable[float], duration_s: float) -> tuple[float, ...]:
    """Where a repackaged copy's pieces start: at the first keyframe, then at
    the first keyframe PIECE_S or more after each start; a last piece
    shorter than SHORTEST_LAST_S goes with the one before."""
    starts: list[float] = []
    for t in sorted(keyframes):
        if t >= duration_s:
            break
        if not starts or t >= starts[-1] + PIECE_S:
            starts.append(t)
    if len(starts) > 1 and duration_s - starts[-1] < SHORTEST_LAST_S:
        starts.pop()
    return tuple(starts)


def pieces_every(duration_s: float) -> tuple[float, ...]:
    """Where a converted copy's pieces start: every PIECE_S seconds."""
    count = max(1, math.ceil(duration_s / PIECE_S - 1e-9))
    starts = tuple(i * PIECE_S for i in range(count))
    if len(starts) > 1 and duration_s - starts[-1] < SHORTEST_LAST_S:
        starts = starts[:-1]
    return starts


def lengths(starts: tuple[float, ...], duration_s: float) -> list[float]:
    """Each piece's length (the first from the program's start)."""
    ends = [*starts[1:], duration_s]
    return [
        end - (start if i else 0.0) for i, (start, end) in enumerate(zip(starts, ends, strict=True))
    ]


def playlist(plan: Plan, start_s: float = 0.0) -> str:
    """The copy's playlist: every piece, from the start (a player starts at
    `start_s`)."""
    each = lengths(plan.starts, plan.duration_s)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{max(1, math.ceil(max(each)))}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]
    if plan.method == CONVERT:
        lines.append("#EXT-X-INDEPENDENT-SEGMENTS")
    if start_s > 0:
        lines.append(f"#EXT-X-START:TIME-OFFSET={start_s:.3f},PRECISE=YES")
    for n, length in enumerate(each):
        lines += [f"#EXTINF:{length:.3f},", f"piece-{n}.ts"]
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def piece_for(starts: tuple[float, ...], at_s: float) -> int:
    """The piece holding a time."""
    n = 0
    for i, start in enumerate(starts):
        if start <= at_s + 1e-6:
            n = i
        else:
            break
    return n


# The command -------------------------------------------------------------------------


def command(
    ffmpeg: str, source: str, plan: Plan, first: int, video_index: int = 0, encoder: Encoder = CPU
) -> list[str]:
    """ffmpeg making the copy from piece `first` on, as one MPEG-TS stream
    on its output, with the program's own times (plus TS_OFFSET_S). A
    converted picture is encoded on `encoder`."""
    args = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error"]
    if source.startswith(("http://", "https://")):
        args += [
            "-reconnect", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "10",
            "-rw_timeout", str(READ_TIMEOUT_US),
        ]  # fmt: skip
    if not plan.copies_picture:
        # (On a GPU, set up as the stations set it up: it decodes the file
        # too, where it can.)
        args += hw_input_args(encoder)
    start = plan.starts[first] if first else 0.0
    if plan.copies_picture:
        # (Somewhere before the piece's keyframe: what's before it is left
        # out when the stream is cut into pieces.)
        if start > 0:
            args += ["-ss", f"{max(0.0, start - 0.5):.3f}"]
    elif start > 0:
        args += ["-ss", f"{start:.3f}"]  # (exactly: the picture's made from here)
    if plan.subtitles is not None and plan.subtitles.image and plan.subtitles.forced_only:
        args += [f"-forced_subs_only:s:{plan.subtitles.stream}", "1"]
    args += ["-i", source]
    audio_map = (
        ["-map", f"0:{plan.audio.index}"]
        if plan.audio and plan.audio.index is not None
        else ["-map", "0:a:0?"]
    )
    if plan.copies_picture:
        video = ["-map", f"0:V:{video_index}", "-c:v", "copy"]
        if plan.picture == "h264":
            # (The picture's setup before every keyframe, not only the IDR
            # ones: a piece starting at any keyframe plays on its own.)
            video += ["-bsf:v", "h264_mp4toannexb,dump_extra=freq=keyframe"]
        times = []
    else:
        video = _converted_picture(plan, first, video_index, encoder)
        # (Converted: its times from the program's start, whatever the file's
        # own first time, as the pieces were planned.)
        times = ["-start_at_zero"]
    chain = sound_chain(plan)
    # (Sound that goes through filters is made again, never copied.)
    codec = "aac" if chain and plan.audio_codec == "copy" else plan.audio_codec
    if codec == "copy":
        sound = ["-c:a", "copy"]
    elif codec == "ac3":
        sound = ["-c:a", "ac3", "-b:a", f"{SURROUND_KBPS}k", "-ac", str(plan.audio_channels)]
    else:
        # (Night mode's sound is stereo; so is sound that would have been
        # copied as it is but for its filters, as before.)
        channels = plan.audio_channels if plan.audio_codec == "aac" and not plan.night else 2
        sound = ["-c:a", "aac", "-b:a", f"{sound_kbps('aac', channels)}k", "-ac", str(channels),
                 "-ar", "48000"]  # fmt: skip
    if chain:
        sound = ["-af", chain, *sound]
    return [
        *args, *video, *audio_map, *sound,
        "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
        # The program's own times, moved on by TS_OFFSET_S, whatever ffmpeg
        # starts from: pieces from different runs line up.
        "-copyts", *times,
        "-avoid_negative_ts", "disabled", "-muxdelay", "0", "-muxpreload", "0",
        "-output_ts_offset", f"{TS_OFFSET_S:g}",
        "-f", "mpegts", "-mpegts_start_pid", str(VIDEO_PID), "pipe:1",
    ]  # fmt: skip


def sound_chain(plan: Plan) -> str:
    """The filters a copy's sound goes through ("" for none): even sound
    for a show's episodes (EVEN_SOUND), then night mode's (hls.NIGHT_SOUND).
    Even sound comes first, so night mode's compressing works from the same
    loudness in every episode, and its limiter, last, keeps the peaks its
    lift makes in check."""
    from .hls import NIGHT_SOUND  # (hls.py's, the stations' night sound)

    return ",".join(
        filters for filters, on in ((EVEN_SOUND, plan.even), (NIGHT_SOUND, plan.night)) if on
    )


def _converted_picture(plan: Plan, first: int, video_index: int, encoder: Encoder) -> list[str]:
    """Converting the picture: deinterlaced where needed, square pixels,
    within a 16:9 picture plan.height lines high (so a wide film at 1080p is
    1920 wide, as H.264 decoders made for 1080p take, not 2592), ordinary
    (not HDR), subtitles drawn in last, and a keyframe at the start of every
    piece. All of that is done on the CPU with a GPU too, as for the
    stations: the GPU only decodes the file (where it can) and encodes the
    picture."""
    # (VA-API: the finished picture goes up to the GPU, as the stations' does.)
    upload = ",format=nv12,hwupload" if encoder.kind == "vaapi" else ""
    widest = plan.height * 16 // 9 // 2 * 2
    steps = [
        "bwdif=mode=send_frame:deint=interlaced",
        "scale=w='trunc(iw*sar/2)*2':h=ih,setsar=1",
        f"scale=w='min({widest},iw)':h='min({plan.height},ih)':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2:flags=bicubic",
        *([plan.tone_map] if plan.tone_map else []),
        "format=yuv420p",
    ]
    chain = ",".join(steps)
    subs = plan.subtitles
    if subs is not None and subs.image:
        # (The subtitles' own picture is the film's size: made the picture's.)
        graph = (
            f"[0:V:{video_index}]{chain}[pic];"
            f"[0:s:{subs.stream}][pic]scale2ref=w=main_w:h=main_h[subs][base];"
            "[base][subs]overlay=(W-w)/2:(H-h)/2:eof_action=pass:format=auto,format=yuv420p"
            f"{upload}[vout]"
        )
        video = ["-filter_complex", graph, "-map", "[vout]"]
    else:
        if subs is not None:
            options = f"filename={filter_path(subs.path)}"
            if subs.stream is not None:
                options += f":si={subs.stream}"
            if not subs.styled:
                options += f":force_style='{SUBTITLE_STYLE}'"
            # (The frames carry the program's own times, as the subtitles do.)
            chain += f",subtitles={options}"
        video = ["-map", f"0:V:{video_index}", "-vf", chain + upload]
    # A keyframe where each piece after the first starts (the first frame is
    # one anyway).
    keys = ",".join(f"{t:.3f}" for t in plan.starts[first + 1 :]) or f"{plan.duration_s:.3f}"
    return [*video, *_encoding(encoder, plan.kbps), "-force_key_frames", keys]


def _encoding(encoder: Encoder, kbps: int) -> list[str]:
    """H.264 High at `kbps`, at most, with two seconds' buffer. On the CPU,
    libx264. On a GPU, the stations' settings for it (see
    ffmpeg._video_encoder_args) but for two: no level set (the encoder
    picks the one the copy's size and frame rate need, as libx264 does; a
    copy keeps the file's frame rate), and a keyframe every GPU_GOP frames
    at most, as libx264 makes them. No B-frames there, as for the stations.
    The keyframes forced where pieces start are IDR frames on every
    encoder: libx264's and VA-API's are, and NVENC's with -forced-idr."""
    rate = ["-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k"]
    gop = ["-g", str(GPU_GOP), "-bf", "0"]
    if encoder.kind == "vaapi":
        return ["-c:v", "h264_vaapi", "-profile:v", "high", "-rc_mode", "VBR", *rate, *gop]
    if encoder.kind == "nvidia":
        return [
            "-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq", "-profile:v", "high",
            "-rc", "vbr", "-pix_fmt", "yuv420p", *rate, *gop, "-forced-idr", "1",
            *(["-gpu", encoder.device] if encoder.device else []),
        ]  # fmt: skip
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high",
        "-pix_fmt", "yuv420p", *rate, "-sc_threshold", "0",
    ]  # fmt: skip


# Deciding how ------------------------------------------------------------------------


def convert_size(
    media: Media,
    most_height: int,
    fit_kbps: int | None,
    cap_kbps: int | None = None,
    sound_kbps: int = AUDIO_KBPS,
) -> tuple[int, int]:
    """A converted picture's (height, kbps): as big as the file's, the
    device's and CONVERT_MOST_HEIGHT allow; with `fit_kbps` (what the
    connection carries), the biggest that needs no more than two-thirds of
    it; and away from home, with the Admin's cap (`cap_kbps`), never more
    than the cap, with the copy's sound (`sound_kbps`)."""
    height = min(media.height or CONVERT_MOST_HEIGHT, most_height or CONVERT_MOST_HEIGHT,
                 CONVERT_MOST_HEIGHT)  # fmt: skip
    rungs = [(h, k) for h, k in CONVERT_HEIGHTS if h <= max(height, CONVERT_HEIGHTS[-1][0])]
    for h, k in rungs:
        if (fit_kbps is None or k + AUDIO_KBPS <= fit_kbps * 2 // 3) and (
            cap_kbps is None or k + sound_kbps <= cap_kbps
        ):
            return min(height, h), k
    h, _ = rungs[-1]
    kbps = max(LEAST_KBPS, fit_kbps * 2 // 3 - AUDIO_KBPS) if fit_kbps else 2_000
    if cap_kbps is not None:
        kbps = min(kbps, max(LEAST_CAPPED_KBPS, cap_kbps - sound_kbps))
    return min(height, h), kbps


def sound_kbps(audio_codec: str, channels: int) -> int:
    """About what a copy's sound takes, as it's made (copied as it is:
    about what it would take made)."""
    if audio_codec == "ac3" or (audio_codec == "copy" and channels > 2):
        return SURROUND_KBPS
    if audio_codec == "aac" and channels > 2:
        return AAC_SURROUND_KBPS
    return AUDIO_KBPS


def sound_for(
    track: Track | None,
    device_audio: frozenset[str],
    night: bool,
    even: bool = False,
    asked: bool = False,
) -> tuple[str, int]:
    """How a copy's sound is made: ("copy" | "aac" | "ac3", channels). With
    even sound (`even`), it's what the device would get anyway, but made
    again rather than copied, since its loudness changes: Dolby Digital 5.1
    where the device plays it and the sound has more than two channels,
    otherwise AAC stereo. A converted copy an app asked for (`asked`: its
    decoder failed, so nothing it says it plays is trusted) has AAC: 5.1
    where the sound has more than two channels and the device takes
    surround sound, otherwise stereo."""
    if track is None or night:
        return "aac", 2
    surround = (track.channels or 2) > 2
    if asked:
        return "aac", 6 if surround and device_audio & SURROUND else 2
    if track.codec in device_audio and track.codec in TS_AUDIO and not even:
        return "copy", track.channels or 2
    if surround and "ac3" in device_audio:
        return "ac3", min(6, track.channels or 6)
    return "aac", 2


def picture_copyable(media: Media, why_not: list[str], hls: frozenset[str]) -> bool:
    """Whether a copy can keep the picture as it is: nothing about the
    picture keeps the device from playing it, and the copy's pieces carry
    it (H.264, or HEVC where the device takes HEVC in MPEG-TS pieces)."""
    picture_reasons = [
        w for w in why_not
        if w.startswith(("its picture", "its Dolby Vision", "its HDR", "its HLG", "its 1"))
        or "-bit picture" in w
    ]  # fmt: skip
    if picture_reasons or media.parts > 1:
        return False
    if media.video == "h264":
        return "ts" in hls
    if media.video == "hevc":
        return "ts-hevc" in hls
    return False


# Making it ---------------------------------------------------------------------------


@dataclass
class _Run:
    """One ffmpeg making pieces from `first` on, a converted picture encoded
    on `encoder`."""

    first: int
    proc: asyncio.subprocess.Process
    encoder: Encoder = CPU
    task: asyncio.Task | None = None
    newest: int = -1  # the newest piece finished
    said: list[str] = field(default_factory=list)
    done: bool = False


def new_folder() -> Path:
    """A folder of its own for a copy's pieces, in the system's temporary
    folder."""
    return Path(tempfile.mkdtemp(prefix="stationplay-copy-"))


class Copy:
    """One copy being made, for one play session."""

    def __init__(
        self,
        ffmpeg: str,
        source: str,
        plan: Plan,
        folder: Path | None = None,
        first: asyncio.Future | None = None,
        video_index: int = 0,
        gpu: GpuManager | None = None,
        name: str = "",
    ) -> None:
        """`folder`: where its pieces go (see new_folder; deleted when it
        stops). `first`: what has to be done before ffmpeg starts (subtitles
        read out of the file, or fetched, to be drawn in), if anything.
        `gpu`: the stations' GPU, to convert the picture on while it's in
        use. `name`: the program, as the log names it."""
        self.ffmpeg = ffmpeg
        self.source = source
        self.plan = plan
        self.video_index = video_index
        self.first = first
        self.gpu = gpu
        self.name = name or "a program"
        # Where a converted picture is encoded: on the GPU while it's in use
        # as the copy starts; on the CPU from the first run that fails there,
        # or once the GPU is turned off.
        self.encoder = (
            gpu.encoder_for_copies() if gpu is not None and plan.method == CONVERT else CPU
        )
        self._began = False  # (said in the log)
        self._made_on_gpu = False  # (a piece: see stop)
        # The piece a run on the GPU failed at (not a stall): once the CPU
        # makes it, the CPU rescued the copy (see _finished).
        self._rescue_at: int | None = None
        self.folder = folder or new_folder()
        self.ready: dict[int, Path] = {}  # pieces finished
        self.wanted = -1  # the furthest piece asked for
        self.asked = time.monotonic()
        self.stopped = False
        self.broken = False  # (given up on: see FAILURES_MOST)
        self.end = len(plan.starts)  # pieces from here on aren't coming (the file ended sooner)
        self.failures = 0
        self.failed_at = 0.0
        self._asks = 0  # (only the newest request starts ffmpeg again)
        self._run: _Run | None = None
        self._cutting: set[asyncio.Task] = set()  # (every run's, until it's gone)
        self._news = asyncio.Event()  # (set and replaced whenever anything changes)
        self._lock = asyncio.Lock()
        # Told when making it fails on the CPU (where in the file, in seconds,
        # and why), so the file can be checked there (see scanner.Target):
        # the failure may be the file's, or may not.
        self.trouble: Callable[[float, str], None] | None = None

    @property
    def active(self) -> bool:
        """Being made, or asked for lately (what counts toward the limit on
        converting at once)."""
        if self.stopped or self.broken:
            return False
        run = self._run
        return (run is not None and not run.done) or time.monotonic() - self.asked < IDLE_S

    def playlist(self, start_s: float = 0.0) -> str:
        return playlist(self.plan, start_s)

    async def piece(self, n: int, gone: Callable[[], Awaitable[bool]] | None = None) -> Path | None:
        """Piece `n`, once it's made; None if it can't be in WAIT_S, or the
        player has gone (`gone`), or the copy has stopped or given up."""
        if self.stopped or self.broken or not 0 <= n < self.end:
            return None
        self._asks += 1
        mine = self._asks
        self.asked = time.monotonic()
        # (Further on, or a jump back: what's wanted is from here.)
        self.wanted = max(self.wanted, n) if n >= self.wanted - BEHIND else n
        self._poke()
        deadline = time.monotonic() + WAIT_S
        first = self.first
        if first is not None:
            if not first.done():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(first), WAIT_S)
                if not first.done():
                    return None
            if self.first is first:
                self.first = None
                ok = not first.cancelled() and first.exception() is None and first.result()
                if not ok and self.plan.subtitles is not None:
                    # (They couldn't be had: it plays without them.)
                    self.plan = replace(self.plan, subtitles=None, drawn=None)
        while not self.stopped and not self.broken:
            news = self._news
            found = self.ready.get(n)
            if found is not None and found.exists():
                self._tidy()
                return found
            if n >= self.end or time.monotonic() >= deadline:
                return None
            if gone is not None and await gone():
                return None
            async with self._lock:
                run = self._run
                coming = (
                    run is not None
                    and not run.done
                    and max(run.first, run.newest + 1) <= n <= max(run.newest, run.first) + JUMP
                )
                # (Only the newest request starts ffmpeg again, and not
                # straight after a failure.)
                if (
                    not coming
                    and mine == self._asks
                    and time.monotonic() - self.failed_at >= RETRY_S
                    and not self.stopped
                ):
                    await self._start(n)
                    continue
            left = deadline - time.monotonic()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(news.wait(), max(0.05, min(left, 1.0)))
        return None

    def _poke(self) -> None:
        news, self._news = self._news, asyncio.Event()
        news.set()

    async def close(self) -> None:
        """Stops it (see stop), and waits for its ffmpegs to be gone."""
        self.stop()
        if self._cutting:
            await asyncio.wait(set(self._cutting), timeout=10.0)

    def rest(self, after_s: float) -> None:
        """Deletes its pieces if nothing has asked for one in `after_s` and
        nothing's being made (its player gone, as an app gone without
        leaving is): they're made again, from where the player is, if it
        comes back."""
        run = self._run
        if self.ready and (run is None or run.done) and time.monotonic() - self.asked >= after_s:
            for path in self.ready.values():
                with contextlib.suppress(OSError):
                    path.unlink()
            self.ready.clear()

    def stop(self) -> None:
        """Stops making it, and deletes its pieces."""
        if self.stopped:
            return
        self.stopped = True
        self._end_run()
        if self._made_on_gpu and self.encoder.is_gpu and self.gpu is not None:
            self.gpu.copy_succeeded()  # (made on the GPU, and never failed there)
        self._poke()
        shutil.rmtree(self.folder, ignore_errors=True)

    async def _start(self, n: int) -> None:
        self._end_run()
        if (
            self.encoder.is_gpu
            and self.gpu is not None
            and not self.gpu.encoder_for_copies().is_gpu
        ):
            self.encoder = CPU  # (the GPU was turned off meanwhile: see gpu.py)
            if self._began:
                log.info("The GPU was turned off; continuing the copy of %s on the CPU", self.name)
        encoder = self.encoder
        args = command(self.ffmpeg, self.source, self.plan, n, self.video_index, encoder)
        if not self._began and not self.plan.copies_picture:
            self._began = True
            on = encoder.label if encoder.is_gpu else "the CPU"
            log.info("Converting a copy of %s on %s", self.name, on)
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1 << 20,
        )
        if self.stopped:  # (stopped while it was starting)
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            return
        run = _Run(first=n, proc=proc, encoder=encoder, newest=n - 1)
        run.task = asyncio.create_task(self._cut(run))
        self._cutting.add(run.task)
        run.task.add_done_callback(self._cutting.discard)
        self._run = run
        self.wanted = max(self.wanted, n)

    def _end_run(self) -> None:
        run, self._run = self._run, None
        if run is None:
            return
        run.done = True
        if run.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                run.proc.kill()
        if run.task is not None:
            run.task.cancel()

    async def _cut(self, run: _Run) -> None:
        """Reads ffmpeg's stream and cuts it into pieces at their keyframes."""
        assert run.proc.stdout is not None and run.proc.stderr is not None
        errors = asyncio.create_task(_said(run.proc.stderr, run.said))
        # (On a GPU, a keyframe missing where a piece starts is a failure.)
        cutter = Cutter(self.plan.starts, run.first, strict=run.encoder.is_gpu)
        out = None
        current = -1
        failed = ""
        stalled = False
        began = time.monotonic()
        try:
            while True:
                # Ahead enough: wait (ffmpeg waits too, its output unread),
                # unless nothing has asked in a while, when it stops.
                while current > self.wanted + AHEAD and not self.stopped:
                    if time.monotonic() - self.asked > IDLE_S:
                        return
                    news = self._news
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(news.wait(), 5.0)
                try:
                    chunk = await asyncio.wait_for(run.proc.stdout.read(TS_PACKET * 2048), STALL_S)
                except TimeoutError:
                    failed, stalled = f"nothing came for {STALL_S:.0f} seconds", True
                    return
                if not chunk:
                    break
                for n, data in cutter.feed(chunk):
                    if n != current:
                        if out is not None:
                            out.close()
                            self._finished(run, current)
                        current = n
                        out = (self.folder / f"piece-{n}.ts.part").open("wb")
                        out.write(cutter.header)
                    if out is not None:
                        out.write(data)
                if cutter.missed is not None:
                    failed = f"no keyframe where piece {cutter.missed} starts"
                    return
                if current < 0 and time.monotonic() - began > STALL_S:
                    failed = "no piece started where it should"
                    return
            code = await run.proc.wait()
            if out is not None:
                out.close()
                out = None
                if code == 0 and current >= 0:
                    # (The end of the file: the piece being made is whole, and
                    # if the file ended before its planned length, no more
                    # are coming.)
                    self._finished(run, current)
                    self.end = min(self.end, current + 1)
            if code != 0 or current < 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(errors), 5.0)
                failed = f"ffmpeg {code}: " + (
                    redact(" ".join(run.said[-3:]))[-300:] or "nothing said"
                )
        except asyncio.CancelledError:
            raise
        except (OSError, TimeoutError) as e:
            failed = str(e) or type(e).__name__
        finally:
            if out is not None:
                out.close()
            errors.cancel()
            mine = self._run is run and not run.done
            run.done = True
            if run.proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    run.proc.kill()
            if failed and mine and not self.stopped:
                self._failed(run, failed, stalled)
            self._poke()
            with contextlib.suppress(Exception):  # (gone, not left behind)
                await asyncio.wait_for(run.proc.wait(), 10.0)

    def _failed(self, run: _Run, why: str, stalled: bool = False) -> None:
        """A run failed: tried again after RETRY_S, and given up on after
        FAILURES_MOST in a row. On the GPU, it may be the GPU's fault rather
        than the file's: the copy carries on from there on the CPU at once,
        and only failures there count."""
        if run.encoder.is_gpu:
            self.encoder = CPU
            # (A stall may as well be the disk's, so it never counts against
            # the GPU: see _finished.)
            self._rescue_at = None if stalled else max(run.first, run.newest + 1)
            if self.gpu is not None:
                self.gpu.gpu_failed(why, stalled=stalled, what=f"the copy of {self.name}")
            return
        self.failures += 1
        self.failed_at = time.monotonic()
        if self.failures == 1:
            log.warning("Making a copy for a StationPlay app stopped (%s)", why)
        if self.trouble is not None:
            starts = self.plan.starts
            piece = min(max(run.first, run.newest + 1), len(starts) - 1)
            self.trouble(starts[piece] if starts else 0.0, why)
        if self.failures >= FAILURES_MOST:
            self.broken = True
            log.warning(
                "StationPlay gave up making a copy for an app after %d tries (%s)",
                self.failures,
                why,
            )

    def _finished(self, run: _Run, n: int) -> None:
        part = self.folder / f"piece-{n}.ts.part"
        whole = self.folder / f"piece-{n}.ts"
        with contextlib.suppress(OSError):
            part.replace(whole)
            self.ready[n] = whole
            run.newest = max(run.newest, n)
            self.failures = 0
            if run.encoder.is_gpu:
                self._made_on_gpu = True
            elif n == self._rescue_at and self.gpu is not None:
                # (Made fine on the CPU where it failed on the GPU; a piece
                # further on, after a jump, proves nothing.)
                self._rescue_at = None
                self.gpu.copy_rescued()
        self._poke()

    def _tidy(self) -> None:
        """Deletes pieces well behind the player, and far ahead of it."""
        for n in [n for n in self.ready if n < self.wanted - BEHIND or n > self.wanted + 4 * AHEAD]:
            path = self.ready.pop(n)
            with contextlib.suppress(OSError):
                path.unlink()


async def _said(stream: asyncio.StreamReader, said: list[str]) -> None:
    with contextlib.suppress(Exception):
        async for line in stream:
            said.append(line.decode(errors="replace").strip())
            del said[:-20]


class Cutter:
    """Cuts an MPEG-TS stream into pieces at the keyframes starting them:
    feed it what ffmpeg writes, and it says which piece each part is for.
    What comes before the first piece's keyframe (ffmpeg starts at a
    keyframe before it) is left out. Each piece starts with the stream's
    tables (PAT and PMT), so it plays on its own.

    `strict`, for a picture made on a GPU: a frame just after where a piece
    starts, with no keyframe starting the piece before it, stops the cutting
    there (`missed`: that piece), rather than the piece being left out and
    its picture going with the one before. (Without B-frames, the frames
    come in the order they're shown.)"""

    def __init__(self, starts: tuple[float, ...], first: int, strict: bool = False) -> None:
        self.starts = starts
        self.first = first
        self.strict = strict
        self.piece = -1  # the piece being written (-1: none yet)
        self.missed: int | None = None  # (strict: the piece whose keyframe didn't come)
        self._rest = b""
        self._tables: dict[int, bytes] = {}
        self._pmt = -1

    @property
    def header(self) -> bytes:
        return self._tables.get(0, b"") + self._tables.get(self._pmt, b"")

    def feed(self, chunk: bytes) -> list[tuple[int, bytes]]:
        if self.missed is not None:
            return []
        data = self._rest + chunk
        whole = len(data) - len(data) % TS_PACKET
        self._rest = data[whole:]
        out: list[tuple[int, bytes]] = []
        run_start = 0
        end = whole
        for at in range(0, whole, TS_PACKET):
            if data[at] != 0x47:
                continue  # (out of step: skipped)
            b1 = data[at + 1]
            pid = ((b1 & 0x1F) << 8) | data[at + 2]
            if (pid == 0 or pid == self._pmt) and b1 & 0x40:
                self._tables[pid] = data[at : at + TS_PACKET]
                if pid == 0:
                    self._pmt = _pmt_pid(data[at : at + TS_PACKET])
                continue
            if pid != VIDEO_PID or not b1 & 0x40:
                continue
            packet = data[at : at + TS_PACKET]
            start = _keyframe_time(packet)
            n = None if start is None else self._piece_starting(start - TS_OFFSET_S)
            if n is None or n == self.piece:
                if self.strict and (missed := self._missed(packet)) is not None:
                    self.missed, end = missed, at
                    break
                continue
            if self.piece >= 0 and at > run_start:
                out.append((self.piece, data[run_start:at]))
            self.piece = n
            run_start = at
        if self.piece >= 0 and end > run_start:
            out.append((self.piece, data[run_start:end]))
        return out

    def _missed(self, packet: bytes) -> int | None:
        """The next piece, if this frame (one not starting it) comes just
        after where it starts: its keyframe should have come first. (A frame
        later than that, after a gap in the picture, is let be, as without
        `strict`; so is the first piece, which starts at the first keyframe
        however late.)"""
        n = max(self.first, self.piece + 1)
        t = _frame_time(packet)
        if n == 0 or n >= len(self.starts) or t is None:
            return None
        start = self.starts[n]
        return n if start + MATCH_BEFORE_S < t - TS_OFFSET_S <= start + MATCH_AFTER_S else None

    def _piece_starting(self, t: float) -> int | None:
        """The piece a keyframe at `t` starts, if it starts one (from the
        first piece on, never going back)."""
        low = max(self.first, self.piece + 1)
        for n in range(low, len(self.starts)):
            start = self.starts[n]
            if start - MATCH_BEFORE_S <= t <= start + MATCH_AFTER_S:
                return n
            if start > t:
                break
        # (The first piece starts at the program's start, whatever its first
        # keyframe's time: the first before the second piece's.)
        if (
            self.piece < 0
            and self.first == 0
            and (len(self.starts) == 1 or t < self.starts[1] - MATCH_BEFORE_S)
        ):
            return 0
        return None


def _pmt_pid(packet: bytes) -> int:
    """The PMT's PID, from a PAT packet (its first program); -1 if it
    can't be read."""
    at = 4
    if packet[3] & 0x20:  # (an adaptation field first)
        at += 1 + packet[4]
    if at >= TS_PACKET:
        return -1
    at += 1 + packet[at]  # (the pointer field)
    # The table: its id, length (2), stream id (2), version, section and
    # last section; then each program: its number (2) and PID (2).
    entry = at + 8
    while entry + 4 <= TS_PACKET:
        program = (packet[entry] << 8) | packet[entry + 1]
        if program != 0:  # (0: the network's PID)
            return ((packet[entry + 2] & 0x1F) << 8) | packet[entry + 3]
        entry += 4
    return -1


def _keyframe_time(packet: bytes) -> float | None:
    """A video packet starting a keyframe: its time (PTS) in seconds; None
    if it isn't one."""
    control = (packet[3] >> 4) & 3
    if not control & 2 or packet[4] == 0 or not packet[5] & 0x40:  # (random access)
        return None
    return _frame_time(packet)


def _frame_time(packet: bytes) -> float | None:
    """A video packet starting a frame: its time (PTS) in seconds; None if
    it has none."""
    control = (packet[3] >> 4) & 3
    at = 5 + packet[4] if control & 2 else 4  # (after the adaptation field)
    if not control & 1 or at + 14 > TS_PACKET or packet[at : at + 3] != b"\x00\x00\x01":
        return None
    if not packet[at + 7] & 0x80:
        return None
    b = packet[at + 9 : at + 14]
    pts = ((b[0] >> 1) & 7) << 30 | b[1] << 22 | (b[2] >> 1) << 15 | b[3] << 7 | b[4] >> 1
    return pts / 90000


def subtitle_track(media: Media, track_id: str) -> Track | None:
    return next((t for t in media.subtitles if t.id == track_id), None)


def audio_track(media: Media, track_id: str | None) -> Track | None:
    """The sound track asked for, or the file's default, or its first."""
    if track_id:
        found = next((t for t in media.audio if t.id == track_id), None)
        if found is not None:
            return found
    return media.default_audio


def picture_subtitles(track: Track) -> bool:
    return track.codec in catalog.PICTURE_SUBTITLES
