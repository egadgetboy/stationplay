"""ffmpeg and ffprobe command building, probing and progress parsing.

Every program, whatever its source format, is transcoded to the same
output (H.264 + stereo AAC in MPEG-TS at a fixed size and frame rate: the
station's picture size, see PICTURES). That uniformity is what lets one
program follow another in the same stream without the player noticing a
seam.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import shutil
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .config import Settings

log = logging.getLogger(__name__)

# The sizes a station's picture can be, from the standard one (Settings'
# video_width, video_height and video_bitrate_kbps: 1280x720 at 3.5 Mbps):
# (how much wider and taller, how much more data a second). 480p for light
# servers, 1080p for a sharper picture that takes about twice the work.
PICTURES: dict[str, tuple[float, float]] = {
    "480p": (2 / 3, 1500 / 3500),
    "720p": (1.0, 1.0),
    "1080p": (1.5, 6000 / 3500),
}
STANDARD_PICTURE = "720p"


def sized(settings: Settings, picture: str) -> Settings:
    """`settings` with the stream's picture `picture` (see PICTURES): 854x480
    at 1.5 Mbps, 1280x720 at 3.5 Mbps or 1920x1080 at 6 Mbps."""
    scale, data = PICTURES.get(picture, PICTURES[STANDARD_PICTURE])
    return replace(
        settings,
        video_width=2 * round(settings.video_width * scale / 2),
        video_height=2 * round(settings.video_height * scale / 2),
        video_bitrate_kbps=round(settings.video_bitrate_kbps * data),
    )


# Output frame rate, as an exact fraction. Frame counts from ffmpeg's
# progress output convert to exact output durations with it.
FPS_NUM = 30000
FPS_DEN = 1001
GOP_FRAMES = 60  # a keyframe every 2 seconds, so viewers can join quickly


@dataclass(frozen=True)
class Encoder:
    """How video is encoded: on the CPU, or on a GPU.

    kind is "cpu", "vaapi" (Intel and AMD) or "nvidia". For vaapi, device is
    the render node (e.g. /dev/dri/renderD128); for nvidia, the GPU index.
    """

    kind: str = "cpu"
    device: str | None = None

    @property
    def is_gpu(self) -> bool:
        return self.kind != "cpu"

    @property
    def label(self) -> str:
        if self.kind == "vaapi":
            return f"Intel/AMD GPU (VA-API, {self.device})"
        if self.kind == "nvidia":
            return "NVIDIA GPU (NVENC)" + (f" #{self.device}" if self.device else "")
        return "CPU"


CPU = Encoder()

PROGRESS_KEYS = {
    "frame",
    "fps",
    "bitrate",
    "total_size",
    "out_time_us",
    "out_time_ms",
    "out_time",
    "dup_frames",
    "drop_frames",
    "speed",
    "progress",
}


_TOKEN = re.compile(r"(X-Plex-Token=)[^&\s:'\"]+", re.IGNORECASE)


def low_priority(nice: int = 19, idle_io: bool = True) -> list[str]:
    """A command prefix for work that mustn't slow the streams down: by
    default the lowest CPU priority, and disk access only when nothing else
    wants it (checking files, making bumpers), where the system has the
    tools for it."""
    return [
        *(["nice", "-n", str(nice)] if shutil.which("nice") else []),
        *(
            ["ionice", "-c", "3", "-t"] if idle_io and shutil.which("ionice") else []
        ),  # -t: if allowed
    ]


async def run_to_end(args: list[str], timeout_s: float) -> tuple[int, str]:
    """Runs a command to the end: (its exit code, the end of what it said).
    TimeoutError if it takes longer than `timeout_s`. It never outlives the
    call: it's stopped if it times out or the caller is cancelled. OSError
    if it can't be started."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout_s)
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
    return proc.returncode or 0, err.decode(errors="replace")[-300:].strip()


def redact(text: str) -> str:
    """Hides Plex tokens in anything that might be logged or shown."""
    return _TOKEN.sub(r"\1<hidden>", text)


# A program may stop this much short of the length its file gives and still
# count as whole: files often end a few seconds (a long film, a minute or
# two) before it, and the rest of the slot is covered. Never more than a
# tenth of it, though (a short file a few seconds short is missing a lot).
# Playing a file and checking it judge this the same way.
SHORT_BY_S = 10.0
SHORT_BY_FRACTION = 0.02
SHORT_BY_MOST = 0.1


def shortfall_allowed(duration_s: float) -> float:
    """How much short of `duration_s` a program may stop and still count as
    complete."""
    return min(max(SHORT_BY_S, duration_s * SHORT_BY_FRACTION), duration_s * SHORT_BY_MOST)


def frames_to_seconds(frames: int) -> float:
    return frames * FPS_DEN / FPS_NUM


@dataclass(frozen=True)
class SubtitleTrack:
    """A subtitle stream in a file, as it describes itself."""

    index: int  # among the file's subtitle streams
    codec: str
    language: str  # as the file gives it ("" if it doesn't)
    title: str
    forced: bool  # only the lines meant to be read (a foreign language in the film)
    hearing_impaired: bool


@dataclass
class ProbeResult:
    ok: bool
    duration_s: float | None = None
    audio_index: int | None = None  # index among the file's audio streams
    # Shape of the picture as it's meant to be shown (width / height, with
    # non-square pixels accounted for): 1.33 for 4:3, 1.78 for 16:9.
    display_aspect: float | None = None
    width: int = 0
    height: int = 0
    sar: float = 1.0  # shape of one pixel; not 1 for many DVD rips
    video_index: int = 0  # index among the file's video streams
    video_duration_s: float | None = None  # how long the picture says it runs
    error: str | None = None
    timed_out: bool = False  # the share may be hung; says nothing about the file
    # An HDR picture: how its brightness is coded ("smpte2084" for HDR10, and
    # Dolby Vision with an HDR10 picture; "arib-std-b67" for HLG), and its
    # colours (see to_sdr). None for an ordinary (SDR) picture.
    hdr: str | None = None
    primaries: str = "bt2020"
    matrix: str = "bt2020nc"
    full_range: bool = False  # levels 0-255, not the usual 16-235
    # The Dolby Vision profile, if it says it has one (5, 7, 8...).
    dolby_vision: int | None = None
    # Dolby Vision with no ordinary picture inside (profile 5, or 10.0 in
    # AV1): only a Dolby Vision player can show its colours (anything else
    # shows greens and purples), so it isn't played (see DOLBY_VISION_ONLY).
    dolby_vision_only: bool = False
    subtitles: list[SubtitleTrack] = field(default_factory=list)
    # The (chosen) sound's format, as ffprobe names it ("ac3", "truehd"...),
    # and its sample rate: what losing a frame of it costs (see
    # scanner.what_it_costs).
    audio_codec: str = ""
    audio_rate: int = 0
    # How the Logs tab says what a program is (see playing.py): its
    # picture's format ("h264", "hevc"...) and its sound's channels.
    video_codec: str = ""
    audio_channels: int = 0


# Reading a file someone uploaded (a logo, an Intro Bumper): only the kinds
# of file and of picture and sound such files are, and only the file itself,
# never what it points to (a playlist naming other files or web addresses,
# say). Most of what could go wrong in ffmpeg is in the hundreds of formats
# it can read, so a file that's anything else isn't read at all.
UPLOADED_PICTURE = [
    "-max_pixels", str(40_000_000),  # (40 megapixels: bigger would only fill the memory)
    "-protocol_whitelist", "pipe",
    "-format_whitelist", "png_pipe,jpeg_pipe,webp_pipe,gif,gif_pipe,bmp_pipe",
    "-codec_whitelist", "png,mjpeg,webp,gif,bmp",
]  # fmt: skip
UPLOADED_VIDEO = [
    "-max_pixels", str(4096 * 2160),  # (4K at most: an Intro Bumper is shown at 720p)
    "-protocol_whitelist", "file",
    "-format_whitelist", "mov,matroska,avi,mpegts,mpeg,asf,ogg",
    "-codec_whitelist", ",".join((
        "h264", "hevc", "mpeg4", "mpeg2video", "mpeg1video", "vp8", "libvpx", "vp9", "libvpx-vp9",
        "av1", "libdav1d", "libaom-av1", "prores", "mjpeg", "dnxhd", "vc1", "wmv3", "theora",
        "aac", "aac_fixed", "mp3", "mp3float", "mp2", "mp2float", "ac3", "ac3_fixed", "eac3",
        "opus", "libopus", "vorbis", "libvorbis", "flac", "alac", "wmav2",
        "pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s24be", "pcm_s32le", "pcm_f32le", "pcm_u8",
    )),
]  # fmt: skip


# Brightness codings of HDR pictures (as ffprobe names them), and the
# colours they may say they're in (anything else: BT.2020, as HDR is).
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")
_PRIMARIES = ("bt2020", "bt709")
_MATRICES = ("bt2020nc", "bt709")  # (not constant-luminance BT.2020: no HDR uses it)
# Why a Dolby Vision file with no ordinary picture inside is left out.
DOLBY_VISION_ONLY = (
    "it's Dolby Vision profile {profile} with no HDR10 or standard picture inside, so its "
    "colors can't be shown correctly (a different version of it will play fine)"
)
_ENTRIES = (
    "format=duration:stream=index,codec_type,codec_name,width,height,sample_aspect_ratio,"
    "duration,color_transfer,color_primaries,color_space,color_range,channels"
    ":stream_tags=language,DURATION,title"
    ":stream_disposition=attached_pic,forced,hearing_impaired"
)
# The Dolby Vision record. (Asked for with the rest, unless this ffprobe
# doesn't know of it: then without.)
_DOLBY_VISION = ":stream_side_data=dv_profile,dv_bl_signal_compatibility_id"
_asks_dolby_vision = True


async def probe(
    settings: Settings, source: str, timeout: float = 30.0, options: list[str] | None = None
) -> ProbeResult:
    """Checks a file opens and has a video stream, and picks an audio track.
    `options`: for reading it (UPLOADED_VIDEO for an upload)."""
    global _asks_dolby_vision
    while True:
        entries = _ENTRIES + (_DOLBY_VISION if _asks_dolby_vision else "")
        args = [settings.ffprobe_path, "-v", "error", "-show_entries", entries, "-of", "json"]
        args += options or []
        if source.startswith(("http://", "https://")):
            args += ["-rw_timeout", str(int(timeout * 1_000_000))]
        args.append(source)
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return ProbeResult(ok=False, error=f"couldn't run ffprobe: {e}")
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ProbeResult(
                ok=False, error=f"the file took more than {timeout:.0f}s to open", timed_out=True
            )
        if proc.returncode != 0 and _asks_dolby_vision and b"No match for section" in err:
            # (Before it opens the file: nothing is wrong with it.)
            _asks_dolby_vision = False
            log.warning("This ffprobe can't detect Dolby Vision; continuing without that check")
            continue
        break
    if proc.returncode != 0:
        message = err.decode(errors="replace").strip().splitlines()
        return ProbeResult(
            ok=False,
            error=redact(
                "can't open the file: "
                + (message[-1] if message else f"ffprobe exit code {proc.returncode}")
            ),
        )
    try:
        data = json.loads(out or b"{}")
    except ValueError:
        return ProbeResult(ok=False, error="ffprobe returned unreadable output")

    streams = data.get("streams", [])
    # Cover art counts as a video stream in some files; it isn't the video.
    videos = [s for s in streams if s.get("codec_type") == "video"]
    pictures = [s for s in videos if not (s.get("disposition") or {}).get("attached_pic")]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    audio_index = None
    if audio:
        audio_index = 0
        wanted = settings.preferred_audio_language.lower()
        for n, s in enumerate(audio):
            if (s.get("tags", {}) or {}).get("language", "").lower() == wanted:
                audio_index = n
                break
    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None

    if not pictures:
        return ProbeResult(ok=False, error="the file has no video")
    video = pictures[0]
    width, height, sar = _frame(video)
    transfer = video.get("color_transfer")
    primaries = video.get("color_primaries")
    matrix = video.get("color_space")
    dolby_vision = None
    compatible = None
    for side in video.get("side_data_list") or []:
        if isinstance(side, dict) and isinstance(side.get("dv_profile"), int):
            dolby_vision = side["dv_profile"]
            compatible = side.get("dv_bl_signal_compatibility_id")
    subtitles = [
        SubtitleTrack(
            n,
            str(s.get("codec_name") or ""),
            str((s.get("tags") or {}).get("language") or ""),
            str((s.get("tags") or {}).get("title") or ""),
            bool((s.get("disposition") or {}).get("forced")),
            bool((s.get("disposition") or {}).get("hearing_impaired")),
        )
        for n, s in enumerate(x for x in streams if x.get("codec_type") == "subtitle")
    ]
    return ProbeResult(
        ok=True,
        duration_s=duration,
        audio_index=audio_index,
        subtitles=subtitles,
        display_aspect=width * sar / height if width and height else None,
        width=width,
        height=height,
        sar=sar,
        video_index=videos.index(video),
        video_duration_s=_stream_duration(video),
        hdr=transfer if transfer in HDR_TRANSFERS else None,
        primaries=primaries if primaries in _PRIMARIES else "bt2020",
        matrix=matrix if matrix in _MATRICES else "bt2020nc",
        full_range=video.get("color_range") == "pc",
        dolby_vision=dolby_vision,
        dolby_vision_only=dolby_vision == 5 or (dolby_vision == 10 and compatible == 0),
        audio_codec=str(audio[audio_index].get("codec_name") or "")
        if audio_index is not None
        else "",
        audio_rate=_rate(audio[audio_index]) if audio_index is not None else 0,
        video_codec=str(video.get("codec_name") or ""),
        audio_channels=_count(audio[audio_index].get("channels")) if audio_index is not None else 0,
    )


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _rate(stream: dict[str, Any]) -> int:
    try:
        return int(stream.get("sample_rate") or 0)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class Subtitles:
    """Subtitles to draw into a program's picture (see subtitles.py): from
    a subtitle file, `path` (a link to one beside the program, or a text
    stream read out of its file), or a picture stream (DVD, Blu-ray) of the
    program's file, `stream`."""

    path: str = ""  # for text subtitles
    stream: int | None = None  # among the file's subtitle streams
    image: bool = False
    forced_only: bool = False  # (picture subtitles: only their forced lines)
    styled: bool = False  # ASS and SSA: drawn as they're styled


# How plain subtitles (SRT and the like) are drawn: in the stream's font,
# a little larger than usual for a TV across the room, with an outline.
SUBTITLE_STYLE = "FontName=DejaVu Sans,FontSize=19,Outline=1.4,Shadow=0.6,MarginV=24"


def filter_path(path: str) -> str:
    """A file name as a filter's option, whatever is in it: escaped for the
    option (backslash, quote, colon), then quoted for the filter graph."""
    inner = path.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
    return "'" + inner.replace("'", "'\\''") + "'"


def _drawn_subtitles(subs: Subtitles, offset_s: float) -> str:
    """The filters that draw text subtitles on the picture. (They go by
    each frame's time in the file, so the picture's times are moved to
    the file's for them: it's played from `offset_s` in.)"""
    options = f"filename={filter_path(subs.path)}"
    if subs.stream is not None:
        options += f":si={subs.stream}"
    if not subs.styled:
        options += f":force_style='{SUBTITLE_STYLE}'"
    return f"setpts=PTS+{offset_s:.3f}/TB,subtitles={options},setpts=PTS-{offset_s:.3f}/TB"


async def subtitles_problem(settings: Settings, folder: Path) -> str | None:
    """Whether this ffmpeg can draw subtitles: None if it can, otherwise
    why not. A line of subtitles is drawn the way a program's would be."""
    test = folder / "test.srt"

    def write() -> None:
        folder.mkdir(parents=True, exist_ok=True)
        test.write_text("1\n00:00:00,000 --> 00:00:01,000\nStationPlay\n", encoding="utf-8")

    try:
        await asyncio.to_thread(write)
    except OSError as e:
        return f"can't write a test file ({e})"
    subs = Subtitles(path=str(test))
    args = [
        settings.ffmpeg_path, "-hide_banner", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=0.5",
        "-vf", _drawn_subtitles(subs, 0.0), "-f", "null", "-",
    ]  # fmt: skip
    try:
        code, said = await run_to_end(args, 30)
    except (OSError, TimeoutError) as e:
        return str(e) or "it took too long"
    return None if code == 0 else redact(said or f"exit code {code}")


def dolby_vision_reason(probe: ProbeResult) -> str:
    return DOLBY_VISION_ONLY.format(profile=probe.dolby_vision)


def to_sdr(probe: ProbeResult) -> str:
    """Filters that turn an HDR picture (see ProbeResult.hdr) into an
    ordinary one, the way the stream is (SDR, BT.709 colours), as a TV
    showing HDR in SDR would: its brightness brought into SDR's range, with
    the brightest parts eased in rather than cut off (the Mobius curve
    leaves most of the picture as it is), and its colours put into BT.709's.
    It works on the picture once it's the stream's size, where it's cheap.
    "" for an SDR picture."""
    if probe.hdr is None:
        return ""
    levels = "pc" if probe.full_range else "tv"
    colours = probe.primaries
    # (Every step says what it's given as well as what it makes, so nothing
    # rests on what a file's frames say about themselves.)
    return (
        f"zscale=tin={probe.hdr}:pin={colours}:min={probe.matrix}:rin={levels}"
        f":t=linear:p={colours}:npl=100,format=gbrpf32le,"
        f"zscale=tin=linear:pin={colours}:t=linear:p=bt709,"
        "tonemap=tonemap=mobius:desat=0,"
        "zscale=tin=linear:pin=bt709:t=bt709:p=bt709:m=bt709:r=tv"
    )


async def tone_mapping_problem(settings: Settings) -> str | None:
    """Whether this ffmpeg can turn HDR pictures into ordinary ones (see
    to_sdr): None if it can, otherwise why not. A moment's HDR picture is
    turned into an ordinary one exactly as a program's would be."""
    hdr = ProbeResult(ok=True, hdr="smpte2084")
    args = [
        settings.ffmpeg_path, "-hide_banner", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", "color=c=gray:s=128x72:r=10:d=0.5",
        "-vf", f"format=yuv420p10le,{to_sdr(hdr)},format=yuv420p", "-f", "null", "-",
    ]  # fmt: skip
    try:
        code, said = await run_to_end(args, 30)
    except (OSError, TimeoutError) as e:
        return str(e) or "it took too long"
    return None if code == 0 else redact(said or f"exit code {code}")


def _stream_duration(stream: dict) -> float | None:
    """How long a stream says it runs (as the container gives it, or as a
    Matroska file's DURATION tag, "0:22:31.459000000"); None if it doesn't."""
    with contextlib.suppress(KeyError, TypeError, ValueError):
        return float(stream["duration"])
    hours, _, rest = str((stream.get("tags") or {}).get("DURATION") or "").partition(":")
    minutes, _, seconds = rest.partition(":")
    with contextlib.suppress(ValueError):
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return None


def _frame(stream: dict) -> tuple[int, int, float]:
    """(width, height, pixel shape) of a video stream; zeros if unknown."""
    try:
        width, height = int(stream["width"]), int(stream["height"])
    except (KeyError, TypeError, ValueError):
        return 0, 0, 1.0
    if width <= 0 or height <= 0:
        return 0, 0, 1.0
    sar = 1.0
    num, _, den = str(stream.get("sample_aspect_ratio", "")).partition(":")
    with contextlib.suppress(ValueError, ZeroDivisionError):
        if int(num) > 0 and int(den) > 0:
            sar = int(num) / int(den)
    return width, height, sar


# A picture this narrow or narrower, inside a wider frame with black bars
# baked in at the sides, is a 4:3 show stored as widescreen video.
BOXED_MAX_ASPECT = 1.5
DETECT_POINTS = (0.2, 0.5, 0.8)
_CROP = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


class PictureUnknown(Exception):
    """The file couldn't be looked at in time; try again another time."""


async def find_picture(
    settings: Settings, source: str, probe: ProbeResult, timeout: float = 12.0
) -> tuple[int, int, int, int] | None:
    """Where a 4:3 picture sits inside a widescreen frame with black bars
    baked in, as (width, height, x, y) in the file's pixels; None if the
    picture fills the frame. Raises PictureUnknown if it couldn't tell.

    Looks at a dozen frames from each of three points in the file and takes
    the area that's ever not black, so a dark scene can't fool it.
    """
    if not probe.width or not probe.height:
        return None
    points = [probe.duration_s * f for f in DETECT_POINTS] if probe.duration_s else [0.0]
    left, top = probe.width, probe.height
    right = bottom = 0
    deadline = time.monotonic() + timeout
    for at in points:
        args = [
            settings.ffmpeg_path, "-hide_banner", "-nostdin", "-v", "info",
            "-ss", f"{at:.1f}", "-i", source,
            "-map", f"0:v:{probe.video_index}", "-frames:v", "12", "-an", "-sn",
            "-vf", "cropdetect=limit=0.1:round=2:reset=0", "-f", "null", "-",
        ]  # fmt: skip
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            raise PictureUnknown(str(e)) from e
        try:
            _, err = await asyncio.wait_for(
                proc.communicate(), max(1.0, deadline - time.monotonic())
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise PictureUnknown("timed out") from None
        found = _CROP.findall(err.decode(errors="replace"))
        if not found:
            continue
        w, h, x, y = (int(v) for v in found[-1])
        left, top = min(left, x), min(top, y)
        right, bottom = max(right, x + w), max(bottom, y + h)
    return boxed_picture(probe, (right - left, bottom - top, left, top))


def boxed_picture(
    probe: ProbeResult, box: tuple[int, int, int, int]
) -> tuple[int, int, int, int] | None:
    """`box` if it's a narrow picture centred between black side bars."""
    w, h, x, y = box
    if w < 64 or h < 64 or w > probe.width * 0.92:
        return None  # nothing found, or no real side bars
    if abs(x - (probe.width - x - w)) > probe.width * 0.04:
        return None  # not centred: probably a dark scene, not bars
    if w * probe.sar / h >= BOXED_MAX_ASPECT:
        return None  # a widescreen picture with some dark edges
    return w - w % 2, h - h % 2, x - x % 2, y - y % 2


def _video_encoder_args(settings: Settings, encoder: Encoder) -> list[str]:
    """Encoder settings. Every encoder produces the same stream shape: H.264
    High at level 4.1, a keyframe every 2 seconds, no B-frames. Matching
    shapes are what let GPU-encoded programs and CPU-encoded cards follow
    each other seamlessly in one stream."""
    vbr = settings.video_bitrate_kbps
    rate = ["-b:v", f"{vbr}k", "-maxrate", f"{vbr}k", "-bufsize", f"{vbr * 2}k"]
    gop = ["-g", str(GOP_FRAMES), "-bf", "0"]
    high = ["-profile:v", "high", "-level:v", "4.1"]
    if encoder.kind == "vaapi":
        return ["-c:v", "h264_vaapi", *high, "-rc_mode", "VBR", *rate, *gop]
    if encoder.kind == "nvidia":
        args = [
            "-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq", *high,
            "-rc", "vbr", "-pix_fmt", "yuv420p", *rate, *gop, "-forced-idr", "1",
        ]  # fmt: skip
        return args + (["-gpu", encoder.device] if encoder.device else [])
    return [
        "-c:v", "libx264", "-preset", "veryfast", *high, "-pix_fmt", "yuv420p", *rate, *gop,
        "-keyint_min", str(GOP_FRAMES), "-sc_threshold", "0",
    ]  # fmt: skip


def output_args(
    settings: Settings, ts_offset_s: float, channel_name: str, encoder: Encoder = CPU
) -> list[str]:
    return [
        *_video_encoder_args(settings, encoder),
        # The stream's rate, said here and not only by the filters: FFmpeg 7
        # forgets theirs after a filter that moves frames' times (setpts, for
        # subtitles), then encodes at the file's own rate.
        "-fps_mode", "cfr", "-r", f"{FPS_NUM}/{FPS_DEN}",
        "-c:a", "aac", "-b:a", f"{settings.audio_bitrate_kbps}k", "-ac", "2", "-ar", "48000",
        "-shortest",
        # Continue the stream's timeline from where the previous program
        # ended, so the viewer's player sees one unbroken stream.
        "-output_ts_offset", f"{ts_offset_s:.6f}",
        "-f", "mpegts", "-mpegts_service_type", "digital_tv",
        "-metadata", "service_provider=StationPlay", "-metadata", f"service_name={channel_name}",
        "-pat_period", "0.2",
        "pipe:1",
    ]  # fmt: skip


ASPECT_MODES = ("fit", "stretch", "zoom")
WATERMARK_MODES = ("off", "logo", "name", "clock")
# The corner clock: 12-hour (8:05 PM) or 24-hour (20:05).
CLOCK_FORMATS = ("12", "24")
CLOCK_FONT = Path(__file__).resolve().parent / "assets" / "fonts" / "Montserrat-SemiBold.ttf"
# Corner logo sizes and transparencies, as a share of the largest, most
# opaque one (how 1.6.0 drew it).
WATERMARK_SIZES = {"small": 0.55, "medium": 0.75, "large": 1.0}
WATERMARK_TRANSPARENCIES = {"high": 0.4, "medium": 0.65, "low": 1.0}
WATERMARK_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")
# Shown all the time, or only at the start of each program (for its first
# WATERMARK_START_S seconds, fading out over the last WATERMARK_FADE_S).
WATERMARK_TIMINGS = ("always", "start")
# The logo in its own colours, or all in white with a soft dark edge (the
# way real channels show theirs).
WATERMARK_STYLES = ("color", "white")
WATERMARK_START_S = 30.0
WATERMARK_FADE_S = 1.0
# Against burn-in on screens that keep a still picture too long: all through
# every program, the corner mark steps to the next of these places every
# DRIFT_S, (right, down) of where the station puts it, in the stream's
# pixels. A 3 by 3 grid 4 px apart, all within 6 px of it, each step to a
# neighbour. (Pictures go over the stream's at even pixels, so the steps are
# even, and exact.) The place goes by the time each frame airs (see drift).
NUDGES = ((0, 0), (4, 0), (4, 4), (0, 4), (-4, 4), (-4, 0), (-4, -4), (0, -4), (4, -4))
# Whole minutes, so a step comes as the corner clock's minutes change.
DRIFT_S = 240


@dataclass(frozen=True)
class Watermark:
    """The station's logo (a PNG) or name, drawn in a corner."""

    logo: str | None = None
    text: str | None = None
    size: str = "large"  # see WATERMARK_SIZES
    transparency: str = "low"  # see WATERMARK_TRANSPARENCIES
    position: str = "bottom-right"  # see WATERMARK_POSITIONS
    style: str = "color"  # see WATERMARK_STYLES
    # Shown for only this many seconds from the start of what's played (then
    # faded out); None: all the time.
    until_s: float | None = None
    # A clock instead (12 or 24 hours), showing the time each frame airs.
    clock: str | None = None
    # The time (seconds since 1970) the first frame of what's played airs:
    # what the clock tells from, and where the mark has drifted to (see drift).
    airs_at_s: float = 0.0


@dataclass(frozen=True)
class Banner:
    """The Up Next Banner over a part of a program, from `at_s` into the part
    for `seconds`: its picture, with its top-left corner at (x, y). It slides
    in, or (taking the corner logo's place) only fades in, and drifts as the
    logo does (see with_overlays)."""

    path: str
    at_s: float
    seconds: float
    x: int
    y: int
    slide: bool = True


# The banner comes in over BANNER_IN_S and fades out over BANNER_OUT_S.
BANNER_IN_S = 0.5
BANNER_OUT_S = 0.6


def drift(axis: int, airs_at_s: float) -> str:
    """How far the corner mark has moved from its place along `axis` (0:
    right, 1: down), as an expression of each frame's time t in what's
    played, which starts airing at `airs_at_s` (seconds since 1970): through
    the nth DRIFT_S since 1970, it's at the nth of NUDGES (going round), on
    every station alike. So it moves on all through a program however it's
    played, and a program starting, resuming or being tuned in to never
    moves it or holds it."""
    step, into = divmod(airs_at_s, DRIFT_S)
    # (Which of NUDGES, kept in st(0), then how far that one is along `axis`.)
    place = f"st(0,mod({int(step) % len(NUDGES)}+floor((t+{into:.3f})/{DRIFT_S}),{len(NUDGES)}))"
    far = "".join(f"{n[axis]:+d}*eq(ld(0),{i})" for i, n in enumerate(NUDGES) if n[axis])
    return f"({place};{far})"


def escape_text(text: str) -> str:
    """Text for drawtext (used with expansion=none, so % is just %), with
    the characters the filter's option syntax treats specially made safe."""
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")


_PLAIN_PATH = re.compile(r"[A-Za-z0-9_./-]+")


def usable_picture(path: str | None) -> str | None:
    """`path` if it can go in a filter as it is (logo paths always can: they're
    StationPlay's own names); None otherwise, so the name is shown instead."""
    return path if path and _PLAIN_PATH.fullmatch(path) else None


def corner_margins(settings: Settings) -> tuple[int, int]:
    """How far in from the picture's edges the corner mark and the Up Next
    Banner sit: (from the side, from the top or bottom)."""
    return round(settings.video_width * 0.035), round(settings.video_height * 0.05)


# A logo that isn't square (a show's or movie's logo from Plex, usually a
# wide wordmark) covers as much of the picture as a square one would, so
# it looks the same size beside the library's logos: but never more than
# this much wider, or taller, than the square.
LOGO_WIDEST = 2.4
LOGO_TALLEST = 1.25


def picture_size(path: str) -> tuple[int, int] | None:
    """A PNG's width and height, from its header; None if it isn't one (or
    can't be read)."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or not head.startswith(b"\x89PNG\r\n\x1a\n") or head[12:16] != b"IHDR":
        return None
    width, height = int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    return (width, height) if width > 0 and height > 0 else None


def logo_box(logo: str, size: int) -> tuple[int, int]:
    """The box (width, height) a logo is fitted in where a square logo gets
    `size` x `size`: a box of the same area, the logo's own shape."""
    found = picture_size(logo)
    if found is None or found[0] == found[1]:
        return size, size
    aspect = found[0] / found[1]
    width, height = size * aspect**0.5, size / aspect**0.5
    if width > LOGO_WIDEST * size:
        width, height = LOGO_WIDEST * size, LOGO_WIDEST * size / aspect
    if height > LOGO_TALLEST * size:
        width, height = LOGO_TALLEST * size * aspect, LOGO_TALLEST * size
    return max(1, round(width)), max(1, round(height))


def mark_size(settings: Settings, mark: Watermark) -> int:
    """The corner mark's size, which is about how tall it is: the logo's
    (fitted in a square that size, or a box of the same area: see
    logo_box), or the font size of the name or clock."""
    h, scale = settings.video_height, WATERMARK_SIZES.get(mark.size, 1.0)
    if mark.clock:
        return max(8, int(h / 22 * scale))
    if usable_picture(mark.logo):
        return max(8, round(h * 0.13 * scale))
    return max(8, int(h / 26 * scale))


# A still picture as a stream with a frame at each of the stream's frames
# (so it can fade), on the stream's timeline.
_EVERY_FRAME = f",loop=loop=-1:size=1,settb=expr={FPS_DEN}/{FPS_NUM},setpts=N"


def _watermark(
    settings: Settings, mark: Watermark, away: tuple[float, float] | None = None
) -> tuple[str, str]:
    """(filter chains that make [wm], how to put it on [base]) for a
    watermark; making way for the Up Next Banner between the times in
    `away`, if given."""
    opacity = WATERMARK_TRANSPARENCIES.get(mark.transparency, 1.0)
    vertical, _, horizontal = mark.position.partition("-")
    if mark.clock:
        return "", _clock(settings, mark, opacity, vertical, horizontal, away)
    logo = usable_picture(mark.logo)
    if logo:
        size = mark_size(settings, mark)
        box_w, box_h = logo_box(logo, size)
        source = (
            f"movie='{logo}',scale={box_w}:{box_h}:force_original_aspect_ratio=decrease,format=rgba"
        )
        if mark.style == "white":
            source += _WHITE.format(blur=max(1.0, size / 60))
        source += f",colorchannelmixer=aa={0.65 * opacity:.2f}"
        x, y = _corner(settings, mark, vertical, horizontal, "W-w", "H-h")
        put_on = f"[base][wm]overlay=x='{x}':y='{y}':format=auto"
        if mark.until_s is None and away is None:
            return source + "[wm]", put_on
        # The logo as a steady picture that can fade: gone after until_s,
        # and out of the way of the banner.
        source += _EVERY_FRAME
        put_on += ":shortest=1"
        if mark.until_s is not None:
            fade_at, until = _fade(mark.until_s)
            source += f",fade=t=out:st={fade_at:.2f}:d={until - fade_at:.2f}:alpha=1"
            put_on += f":enable='lt(t,{until:.2f})'"
        if away is not None:
            # Out as the banner comes in, and back as it goes.
            gone, back = away[0], away[1] - BANNER_OUT_S
            source += (
                f",fade=t=out:st={gone:.3f}:d={BANNER_IN_S}:alpha=1:enable='lt(t,{back:.3f})'"
                f",fade=t=in:st={back:.3f}:d={BANNER_OUT_S}:alpha=1:enable='gte(t,{back:.3f})'"
            )
        return source + "[wm]", put_on
    text = escape_text((mark.text or "")[:40])
    x, y = _corner(settings, mark, vertical, horizontal, "w-tw", "h-th")
    return "", (
        f"[base]drawtext=text='{text}':expansion=none:fontcolor=white@{0.7 * opacity:.2f}"
        f":fontsize={mark_size(settings, mark)}"
        f":shadowcolor=black@{0.6 * opacity:.2f}:shadowx=2:shadowy=2:x='{x}':y='{y}'"
        f"{_shown(mark, away)}"
    )


def _corner(
    settings: Settings, mark: Watermark, vertical: str, horizontal: str, right: str, bottom: str
) -> tuple[str, str]:
    """Where the corner mark goes, as a filter's x and y expressions: in its
    corner, drifted (see drift). `right` and `bottom` are the expressions
    for the far sides ("W-w" and "H-h" for an overlay)."""
    margin_x, margin_y = corner_margins(settings)
    x = str(margin_x) if horizontal == "left" else f"{right}-{margin_x}"
    y = str(margin_y) if vertical == "top" else f"{bottom}-{margin_y}"
    return f"{x}+{drift(0, mark.airs_at_s)}", f"{y}+{drift(1, mark.airs_at_s)}"


def _shown(mark: Watermark, away: tuple[float, float] | None) -> str:
    """drawtext options that show the corner name or clock only when it's
    shown: fading out after until_s, and making way for the Up Next Banner
    (as the corner logo does)."""
    alpha, enable = [], ""
    if mark.until_s is not None:
        fade_at, until = _fade(mark.until_s)
        alpha.append(f"if(lt(t,{fade_at:.2f}),1,max(0,({until:.2f}-t)/{until - fade_at:.2f}))")
        enable = f":enable='lt(t,{until:.2f})'"
    if away is not None:
        gone, back = away
        alpha.append(
            f"(1-clip(min((t-{gone:.3f})/{BANNER_IN_S},({back:.3f}-t)/{BANNER_OUT_S}),0,1))"
        )
    return (f":alpha='{'*'.join(alpha)}'" if alpha else "") + enable


def _clock(
    settings: Settings,
    mark: Watermark,
    opacity: float,
    vertical: str,
    horizontal: str,
    away: tuple[float, float] | None = None,
) -> str:
    """The corner clock: the time each frame airs, worked out from its
    timestamp (so it's right however far ahead of real time the stream is
    made), in the container's time zone (TZ)."""
    fmt = r"%H\\\:%M" if mark.clock == "24" else r"%-I\\\:%M %p"
    text = rf"%{{pts\:localtime\:{mark.airs_at_s:.3f}\:{fmt}}}"
    font = (
        f"fontfile='{CLOCK_FONT}':"
        if usable_picture(str(CLOCK_FONT)) and CLOCK_FONT.is_file()
        else ""
    )
    x, y = _corner(settings, mark, vertical, horizontal, "w-tw", "h-th")
    return (
        f"[base]drawtext={font}text='{text}':fontcolor=white@{0.8 * opacity:.2f}"
        f":fontsize={mark_size(settings, mark)}"
        f":shadowcolor=black@{0.6 * opacity:.2f}:shadowx=2:shadowy=2:x='{x}':y='{y}'"
        f"{_shown(mark, away)}"
    )


# The logo in white: its light parts solid, its dark parts faint (so its
# shapes still show), over a soft dark edge a pixel down and right. (The
# logo itself stays exactly where it is in colour.)
_WHITE = (
    ",split[wm_a][wm_b];"
    "[wm_a]geq=r=255:g=255:b=255"
    ":a='alpha(X,Y)*(0.28+0.72*pow((0.299*r(X,Y)+0.587*g(X,Y)+0.114*b(X,Y))/255,0.8))'[wm_face];"
    "[wm_b]geq=r=0:g=0:b=0:a='alpha(X,Y)*0.45',gblur=sigma={blur:.1f},"
    "pad=iw+1:ih+1:1:1:color=black@0,crop=iw-1:ih-1:0:0[wm_edge];"
    "[wm_edge][wm_face]overlay=format=rgb"
)


def _fade(until_s: float) -> tuple[float, float]:
    """(when to start fading out, when it's gone)."""
    return max(0.0, until_s - WATERMARK_FADE_S), until_s


def _frames(seconds: float) -> int:
    """`seconds` in the stream's frames."""
    return round(seconds * FPS_NUM / FPS_DEN)


def banner_times(banner: Banner) -> tuple[float, float]:
    """When the banner is up, (from, until), to the frame."""
    starts = _frames(banner.at_s) * FPS_DEN / FPS_NUM
    return starts, starts + max(1, _frames(banner.seconds)) * FPS_DEN / FPS_NUM


def banner_filter(
    settings: Settings, banner: Banner, drifts_from_s: float | None = None
) -> tuple[str, str]:
    """(the filter chain that makes [bn], how to put it on [under]) for the
    Up Next Banner; drifting as a corner mark that starts airing at
    `drifts_from_s` does, if given. (A corner logo where it goes makes way
    for it: see _watermark.)"""
    starts, _ = banner_times(banner)
    # Only the frames it's shown in, counted in the stream's frames: from
    # its start, after which the program shows through as if it weren't
    # there (eof_action=pass).
    fades_at = max(BANNER_IN_S, banner.seconds - BANNER_OUT_S)
    source = (
        f"movie='{banner.path}'{_EVERY_FRAME},"
        f"trim=end_frame={max(1, _frames(banner.seconds))},format=rgba,"
        f"fade=t=in:st=0:d={BANNER_IN_S}:alpha=1,"
        f"fade=t=out:st={fades_at:.3f}:d={BANNER_OUT_S}:alpha=1,"
        f"setpts=PTS+{_frames(banner.at_s)}[bn]"
    )
    x, y = str(banner.x), str(banner.y)
    if banner.slide:
        # From a little to the left, slowing as it arrives.
        travel = round(settings.video_height * 0.04)
        x += f"-{travel}*pow(1-clip((t-{starts:.3f})/{BANNER_IN_S},0,1),3)"
    if drifts_from_s is not None:
        x, y = f"{x}+{drift(0, drifts_from_s)}", f"{y}+{drift(1, drifts_from_s)}"
    return source, f"[under][bn]overlay=x='{x}':y='{y}':eval=frame:eof_action=pass:format=auto"


def with_overlays(
    settings: Settings, chain: str, watermark: Watermark | None, banner: Banner | None
) -> str:
    """The filter chain `chain` (a picture the stream's size, in yuv420p)
    with the corner mark and the Up Next Banner over it. A corner mark in
    the bottom-left corner makes way for the banner while it's up; a banner
    in the corner logo's place drifts with it."""
    if watermark is not None and (watermark.logo or watermark.text or watermark.clock):
        away = (
            banner_times(banner)
            if banner is not None and watermark.position == "bottom-left"
            else None
        )
        source, put_on = _watermark(settings, watermark, away)
        chain = ";".join(filter(None, [f"{chain}[base]", source, f"{put_on},format=yuv420p"]))
    if banner is not None:
        drifts = None if banner.slide or watermark is None else watermark.airs_at_s
        source, put_on = banner_filter(settings, banner, drifts)
        chain = ";".join([f"{chain}[under]", source, f"{put_on},format=yuv420p"])
    return chain


def _video_filter(
    settings: Settings,
    encoder: Encoder = CPU,
    aspect_mode: str = "fit",
    source_aspect: float | None = None,
    picture: tuple[int, int, int, int] | None = None,
    watermark: Watermark | None = None,
    banner: Banner | None = None,
    tone_map: str = "",
    subtitles: Subtitles | None = None,
    offset_s: float = 0.0,
    video_index: int = 0,
) -> str:
    """Scaling and padding stay on the CPU for every encoder: they're cheap
    at these sizes, and they behave identically on any file. So does
    turning an HDR picture into an ordinary one (`tone_map`: see to_sdr).
    Subtitles go on last, over everything, so they're always readable
    (picture subtitles take the file's own subtitle stream, so then the
    filters name their inputs: see program_command).

    aspect_mode decides how programs narrower than the output (4:3 shows)
    fill it: "fit" keeps their shape with black bars at the sides,
    "stretch" widens them to fill, "zoom" enlarges them to fill and trims
    the top and bottom. Programs as wide as the output or wider are always
    fitted, so widescreen movies are never distorted or cropped.

    `picture` is where a 4:3 show sits in a widescreen frame that has black
    bars baked in (see find_picture); it's cut out first, so zoom and
    stretch work on it like on any 4:3 show.
    """
    w, h = settings.video_width, settings.video_height
    narrow = source_aspect is not None and source_aspect < (w / h) * 0.97
    mode = aspect_mode if narrow else "fit"
    if mode == "stretch":
        fill = f"scale={w}:{h}"
    elif mode == "zoom":
        fill = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    else:
        fill = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    steps = [
        # Deinterlace only frames flagged as interlaced (old DVD rips etc.)
        "bwdif=mode=send_frame:deint=interlaced",
    ]
    if picture:
        steps.append("crop={}:{}:{}:{}".format(*picture))
    steps += [
        # Make pixels square first. Many DVD rips store widescreen video in
        # squeezed pixels; without this they'd come out squashed.
        "scale=w='trunc(iw*sar/2)*2':h=ih,setsar=1",
        fill,
        "setsar=1",
        *([tone_map] if tone_map else []),
        f"fps={FPS_NUM}/{FPS_DEN}",
        "format=yuv420p",
    ]
    # The corner mark and the banner go on after the picture is its final size.
    chain = with_overlays(settings, ",".join(steps), watermark, banner)
    if subtitles is not None and subtitles.image:
        # The subtitles' own picture fitted to the stream's (as the film's
        # was), and laid over it.
        chain = (
            f"[0:v:{video_index}]{chain}[pic];"
            f"[0:s:{subtitles.stream}]scale={w}:{h}:force_original_aspect_ratio=decrease[subs];"
            "[pic][subs]overlay=(W-w)/2:(H-h)/2:eof_action=pass:format=auto,format=yuv420p"
        )
    elif subtitles is not None:
        chain += "," + _drawn_subtitles(subtitles, offset_s)
    if encoder.kind == "vaapi":
        chain += ",format=nv12,hwupload"
    if subtitles is not None and subtitles.image:
        chain += "[vout]"
    return chain


# Loudness every TV episode is brought to: -24 LUFS, the level US broadcast
# TV uses (ATSC A/85), with peaks kept under -2 dBTP. LRA=11 leaves each
# episode's own range between quiet and loud scenes largely intact.
LOUDNESS_TARGET = "I=-24:TP=-2:LRA=11"


# Silence, for a card or a file with no sound (made where its picture is).
SILENCE = "anullsrc=channel_layout=stereo:sample_rate=48000"


def _audio_filter(normalize: bool) -> str:
    """Resampling keeps audio in step with video. For TV episodes, loudness
    normalization evens out volume from one episode to the next."""
    chain = "aresample=48000:async=1:first_pts=0"
    if normalize:
        # loudnorm works at 192 kHz internally; resample back afterwards.
        chain += f",loudnorm={LOUDNESS_TARGET},aresample=48000"
    return chain + ",apad"


def hw_input_args(encoder: Encoder) -> list[str]:
    """Hardware decoding for the program file. Decoded frames come back to
    system memory, and if the GPU can't decode a particular file's codec,
    ffmpeg quietly decodes it on the CPU instead. (Copies converted on the
    GPU use it too: see converting.py.)"""
    if encoder.kind == "vaapi":
        return [
            "-init_hw_device", f"vaapi=gpu:{encoder.device}", "-filter_hw_device", "gpu",
            "-hwaccel", "vaapi", "-hwaccel_device", "gpu",
        ]  # fmt: skip
    if encoder.kind == "nvidia":
        return ["-hwaccel", "cuda"] + (
            ["-hwaccel_device", encoder.device] if encoder.device else []
        )
    return []


def common_prefix(settings: Settings) -> list[str]:
    return [
        settings.ffmpeg_path, "-hide_banner", "-nostdin", "-loglevel", "error",
        "-progress", "pipe:2", "-stats_period", "1",
    ]  # fmt: skip


def paced(burst_s: float) -> list[str]:
    """Read at real-time speed, after a burst of `burst_s` seconds."""
    return ["-readrate", "1", "-readrate_initial_burst", f"{burst_s:.2f}"]


def program_command(
    settings: Settings,
    source: str,
    offset_s: float,
    duration_s: float,
    ts_offset_s: float,
    burst_s: float,
    audio_index: int | None,
    channel_name: str,
    encoder: Encoder = CPU,
    aspect_mode: str = "fit",
    source_aspect: float | None = None,
    normalize_audio: bool = False,
    picture: tuple[int, int, int, int] | None = None,
    video_index: int = 0,
    watermark: Watermark | None = None,
    banner: Banner | None = None,
    tone_map: str = "",
    subtitles: Subtitles | None = None,
) -> list[str]:
    """ffmpeg arguments to play `duration_s` of `source` from `offset_s`.
    `tone_map`: for an HDR picture, the filters that make it ordinary (see
    to_sdr). `subtitles`: to draw into the picture."""
    args = common_prefix(settings)
    if source.startswith(("http://", "https://")):
        args += [
            "-reconnect",
            "1",
            "-reconnect_on_network_error",
            "1",
            "-reconnect_delay_max",
            "10",
        ]
    args += ["-fflags", "+genpts+discardcorrupt", *paced(burst_s), *hw_input_args(encoder)]
    if subtitles is not None and subtitles.image and subtitles.forced_only:
        args += [f"-forced_subs_only:s:{subtitles.stream}", "1"]
    if offset_s > 0.05:
        args += ["-ss", f"{offset_s:.3f}"]
    args += ["-i", source]
    graph = _video_filter(
        settings, encoder, aspect_mode, source_aspect, picture, watermark, banner, tone_map,
        subtitles, offset_s if offset_s > 0.05 else 0.0, video_index,
    )  # fmt: skip
    image_subs = subtitles is not None and subtitles.image
    if audio_index is None:
        # No sound in the file: silence, made in the picture's filter graph
        # so every program has a track. (Not an input of its own: with
        # FFmpeg 7, that held back or stalled the stream. And not evened
        # out: silence has no loudness.)
        if not image_subs:
            graph = f"[0:v:{video_index}]{graph}[vout]"
        av = ["-filter_complex", f"{graph};{SILENCE}[aout]", "-map", "[vout]", "-map", "[aout]"]
    elif image_subs:
        av = ["-filter_complex", graph, "-map", "[vout]", "-map", f"0:a:{audio_index}"]
        av += ["-af", _audio_filter(normalize_audio)]
    else:
        av = ["-map", f"0:v:{video_index}", "-vf", graph, "-map", f"0:a:{audio_index}"]
        av += ["-af", _audio_filter(normalize_audio)]
    args += [*av, "-dn", "-sn", "-t", f"{duration_s:.3f}"]
    return args + output_args(settings, ts_offset_s, channel_name, encoder)


def _generated(
    settings: Settings,
    graph: str,
    duration_s: float,
    ts_offset_s: float,
    burst_s: float,
    channel_name: str,
) -> list[str]:
    """ffmpeg arguments for a picture drawn by `graph` (a filter graph ending
    in [out0]), with silence. Made inside ffmpeg and always encoded on the
    CPU, so it depends on neither a file nor a GPU. (The silence comes from
    the same input as the picture, read in step with it: as an input of its
    own, FFmpeg 7 held the card's stream back for seconds at a time.)"""
    args = [
        *common_prefix(settings), *paced(burst_s),
        "-f", "lavfi", "-i", f"{graph};{SILENCE}[out1]",
        "-map", "0:v:0", "-map", "0:a:0", "-t", f"{duration_s:.3f}",
    ]  # fmt: skip
    return args + output_args(settings, ts_offset_s, channel_name)


def _background(settings: Settings) -> str:
    return (
        f"color=c=0x101418:s={settings.video_width}x{settings.video_height}:r={FPS_NUM}/{FPS_DEN}"
    )


def _text(text: str, x: int | str, y: int | str, size: int, colour: str) -> str:
    return (
        f"drawtext=text='{escape_text(text)}':expansion=none:fontcolor={colour}"
        f":fontsize={size}:x={x}:y={y}"
    )


def slate_command(
    settings: Settings,
    duration_s: float,
    ts_offset_s: float,
    burst_s: float,
    channel_name: str,
    message: str | None,
) -> list[str]:
    """A plain card with silence, for time nothing else can fill: the one
    thing that must always work."""
    graph = _background(settings)
    if message:
        size = settings.video_height // 18
        graph += "," + _text(message, "(w-text_w)/2", "(h-text_h)/2", size, "0xE8E8E8")
    return _generated(settings, graph + "[out0]", duration_s, ts_offset_s, burst_s, channel_name)


def card_command(
    settings: Settings,
    duration_s: float,
    ts_offset_s: float,
    burst_s: float,
    channel_name: str,
    logo: str | None,
    lines: list[str],
) -> list[str]:
    """The Station ID card: the station's logo (or name) with a heading
    ("Up next"), a title (the show or movie) and a subtitle (the episode's
    title, or the year). Text is made smaller, then put on two lines, to
    fit; only what can't fit even then is cut short."""
    w, h = settings.video_width, settings.video_height
    heading, title, subtitle = [*lines, "", "", ""][:3]
    graph = _background(settings)
    left = round(w * 0.1)
    top = 0  # the text stays below this
    if usable_picture(logo):
        size = round(h * 0.42)
        graph += (
            f"[bg];movie='{logo}',scale={size}:{size}:force_original_aspect_ratio=decrease,"
            f"format=rgba[lg];[bg][lg]overlay=x={left}:y=(H-h)/2:format=auto"
        )
        text_x = left + size + round(w * 0.05)
    else:
        name, size = fit_lines(channel_name, w - 2 * left, h // 9, h // 16, 1)
        graph += "," + _text(name[0], left, round(h * 0.18), size, "0xF0F0F0")
        text_x, top = left, round(h * 0.18) + round(size * 1.6)
    # Measured text can come out a few percent wider when drawn: keep clear.
    room = round((w - text_x - round(w * 0.05)) * 0.96)
    # Each part as (lines, size, colour), stacked around the middle.
    parts = []
    for text, largest, smallest, most, colour in (
        (heading, h // 22, h // 22, 1, "0xE0A040"),
        (title, h // 13, h // 22, 2, "0xF4F4F4"),
        (subtitle, h // 20, h // 32, 2, "0xB8C0C8"),
    ):
        if text.strip():
            part_lines, size = fit_lines(text, room, largest, smallest, most)
            parts.append((part_lines, size, colour))
    height = sum(len(ls) * round(size * 1.25) for ls, size, _ in parts)
    height += sum(round(size * 0.6) for _, size, _ in parts[1:])
    y = max(top, (h - height) // 2)
    for n, (part_lines, size, colour) in enumerate(parts):
        if n:
            y += round(size * 0.6)
        for line in part_lines:
            graph += "," + _text(line, text_x, y, size, colour)
            y += round(size * 1.25)
    graph += ",format=yuv420p[out0]"
    return _generated(settings, graph, duration_s, ts_offset_s, burst_s, channel_name)


# How wide each printable ASCII character is in DejaVu Sans (the font in
# StationPlay's image, and the one drawtext uses), in hundredths of the font
# size. Anything else counts as ONE_WIDTH.
_WIDTHS = (
    32, 40, 46, 84, 64, 95, 78, 27, 39, 39, 50, 84, 32, 36, 32, 34,
    64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 34, 34, 84, 84, 84, 53,
    100, 68, 69, 70, 77, 63, 58, 77, 75, 29, 29, 66, 56, 86, 75, 79,
    60, 79, 69, 63, 61, 73, 68, 99, 69, 61, 69, 39, 34, 39, 84, 50,
    50, 61, 63, 55, 63, 62, 35, 63, 63, 28, 28, 58, 28, 97, 63, 61,
    63, 63, 41, 52, 39, 63, 59, 82, 59, 59, 52, 64, 34, 64, 84,
)  # fmt: skip
ONE_WIDTH = 70


def text_width(text: str, size: int) -> float:
    """How wide `text` is drawn at `size`, in pixels."""
    return size * sum(_WIDTHS[ord(c) - 32] if 32 <= ord(c) < 127 else ONE_WIDTH for c in text) / 100


def fit_lines(
    text: str, room: int, largest: int, smallest: int, most: int
) -> tuple[list[str], int]:
    """`text` as lines no wider than `room`, and the size to draw them at:
    the biggest size from `largest` to `smallest` on one line, or failing
    that on up to `most` lines (split between words). Only if it doesn't fit
    even then is the last line cut short."""
    text = " ".join(text.split())
    for lines in range(1, most + 1):
        # One line may shrink a quarter; beyond that, wrapping reads better.
        floor = smallest if lines == most else max(smallest, largest * 3 // 4)
        for size in range(largest, floor - 1, -1):
            wrapped = _wrap(text, room, size, lines)
            if wrapped is not None:
                return wrapped, size
    return _wrap(text, room, smallest, most, cut=True) or [""], smallest


def _wrap(text: str, room: int, size: int, most: int, cut: bool = False) -> list[str] | None:
    """`text` split between words into at most `most` lines that fit, or
    None if it won't go; with `cut`, the last line is cut short to fit."""
    lines: list[str] = []
    for word in text.split(" "):
        if lines and text_width(f"{lines[-1]} {word}", size) <= room:
            lines[-1] = f"{lines[-1]} {word}"
        elif len(lines) < most:
            lines.append(word)
        elif cut:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            return None
    if not cut:
        return lines if all(text_width(line, size) <= room for line in lines) else None
    last = lines[-1] if lines else ""
    while last and text_width(last, size) > room:
        last = last[:-2].rstrip() + "…"
    return [*lines[:-1], last] if lines else None


@dataclass
class Progress:
    frames: int = 0

    @property
    def seconds(self) -> float:
        return frames_to_seconds(self.frames)


def parse_progress_line(line: str, progress: Progress) -> str | None:
    """Updates `progress` from one stderr line; returns the line if it's a log message."""
    key, sep, value = line.partition("=")
    if sep and (key.strip() in PROGRESS_KEYS or key.startswith("stream_")):
        key = key.strip()
        if key == "frame":
            with contextlib.suppress(ValueError):
                progress.frames = int(value.strip())
        return None
    return redact(line)
