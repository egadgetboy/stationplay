"""What StationPlay's apps are shown about a library's shows, movies and
episodes, whichever source it comes from (see docs/on-demand.md): a source
turns its own data into these, as plex.to_entry does for Plex.

Codec and container names are made the same whatever a source calls them
("dca" is DTS, "subrip" is SRT), so deciding what a device can play
(ondemand.py) never depends on one source's spelling.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SHOW = "show"
MOVIE = "movie"
EPISODE = "episode"

# A source's names for the same thing, made one.
_CONTAINERS = {"matroska": "mkv", "mpegts": "ts", "mpeg2ts": "ts", "m4v": "mp4", "quicktime": "mov"}
_VIDEO = {
    "avc": "h264", "avc1": "h264", "x264": "h264", "h265": "hevc", "x265": "hevc",
    "hvc1": "hevc", "hev1": "hevc", "mpeg2": "mpeg2video", "wmv3": "vc1", "wvc1": "vc1",
    "xvid": "mpeg4", "divx": "mpeg4",
}  # fmt: skip
_AUDIO = {
    "dca": "dts", "dca-ma": "dts", "dca-hra": "dts", "dts-hd": "dts", "dtshd": "dts",
    "e-ac3": "eac3", "ac-3": "ac3",
}  # fmt: skip
_SUBTITLES = {
    "subrip": "srt", "ssa": "ass", "webvtt": "vtt", "hdmv_pgs_subtitle": "pgs",
    "dvd_subtitle": "vobsub", "dvdsub": "vobsub", "tx3g": "mov_text",
}  # fmt: skip
# Subtitles drawn as pictures (a player shows them as they are, or they're
# drawn into the picture when converting); the rest are text.
PICTURE_SUBTITLES = frozenset({"pgs", "vobsub", "dvb_subtitle"})

# HDR kinds, as devices list what they can show.
HDR10 = "hdr10"
HLG = "hlg"
DOLBY_VISION = "dv"


def container(name: str | None) -> str:
    """A container's one name: "mkv", "mp4", "ts"... ("" if unknown). A
    source listing several ("mov,mp4,m4a") counts as its first."""
    first = (name or "").strip().lower().split(",")[0]
    return _CONTAINERS.get(first, first)


def video_codec(name: str | None) -> str:
    n = (name or "").strip().lower()
    return _VIDEO.get(n, n)


def audio_codec(name: str | None) -> str:
    n = (name or "").strip().lower()
    return _AUDIO.get(n, n)


def subtitle_codec(name: str | None) -> str:
    n = (name or "").strip().lower()
    return _SUBTITLES.get(n, n)


@dataclass(frozen=True)
class Track:
    """One of a file's audio or subtitle tracks."""

    id: str  # the source's own id for it
    codec: str  # made one (see above)
    language: str = ""  # as people read it ("English"), "" if unknown
    title: str = ""  # what the file calls it ("Commentary"), "" if nothing
    channels: int | None = None  # (audio)
    default: bool = False
    forced: bool = False  # (subtitles: only the parts in another language)
    external: bool = False  # (subtitles) a file of its own, beside the video
    index: int | None = None  # its place among all the file's tracks (0: the first)

    @property
    def picture(self) -> bool:
        """Whether it's subtitles drawn as pictures."""
        return self.codec in PICTURE_SUBTITLES


@dataclass(frozen=True)
class Media:
    """One version of a program's file, as its source describes it."""

    container: str
    video: str  # its picture's codec ("" for none)
    width: int = 0
    height: int = 0
    bit_depth: int = 8
    hdr: str = ""  # its HDR: "", HDR10 or HLG (Dolby Vision's base, if any)
    dv_profile: int | None = None  # Dolby Vision's profile (0: unknown); None: none
    bitrate_kbps: int | None = None
    parts: int = 1  # files it's split into (a movie on two discs)
    file: str | None = None  # where the source has it
    part_key: str | None = None  # the source's address for it
    size: int | None = None
    duration_ms: int | None = None
    audio: tuple[Track, ...] = ()
    subtitles: tuple[Track, ...] = ()

    @property
    def default_audio(self) -> Track | None:
        return next((a for a in self.audio if a.default), self.audio[0] if self.audio else None)

    @property
    def size_label(self) -> str:
        """Its picture's size as people say it: "4K", "1080p", "720p", "SD"."""
        return size_label(self.width, self.height)


def size_label(width: int, height: int) -> str:
    """A picture's size as people say it (by width too: a 1920x800 movie is
    1080p, letterboxed)."""
    if width >= 3200 or height >= 1800:
        return "4K"
    if width >= 1600 or height >= 900:
        return "1080p"
    if width >= 1100 or height >= 650:
        return "720p"
    return "SD" if width or height else ""


@dataclass(frozen=True)
class Entry:
    """A show, movie or episode."""

    key: str
    kind: str  # SHOW, MOVIE or EPISODE
    title: str  # (an episode's own title)
    year: int | None = None
    summary: str = ""
    library: str = ""  # the library it's in, "" if the source didn't say
    show_key: str | None = None  # (an episode's show)
    show_title: str = ""
    season: int | None = None
    episode: int | None = None
    duration_ms: int | None = None
    added_ms: int | None = None
    released: str = ""  # YYYY-MM-DD, "" if unknown
    episodes: int | None = None  # (a show: how many)
    seasons: int | None = None  # (a show: how many)
    genres: tuple[str, ...] = ()
    content_rating: str = ""
    studio: str = ""
    has_thumb: bool = True
    has_art: bool = False
    intro: tuple[int, int] | None = None  # [start, end) in ms, when asked for
    credits: tuple[int, int] | None = None
    media: tuple[Media, ...] = field(default=())  # (episodes and movies, when asked for)
