"""What's playing, and for whom, in words: how the Logs tab names stations,
files and the way they play, and who's watching through StationPlay's apps.

A station is named by its number and name, "station 2, Cartoon Classics"
(or its number alone, when its name says no more). A file's picture and
sound are said as a box would label them: "1080p H.264, 5.1 E-AC-3".

Who's watching through StationPlay's apps: a player can't sign in, so at
home a station's HLS is asked for by an address alone. It's put down to the
person whose app at that address last asked for the stations, signed in,
which is how an app starts watching one (see appapi.py). Away from home, a
stream's own address says whose it is (see away.py). Without signing in,
no one is known.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import catalog
from .text import plain

if TYPE_CHECKING:
    from .catalog import Entry
    from .ffmpeg import Encoder

APPS_KEPT = 1000  # addresses whose app is known, at most (the newest)

# Formats as the log names them: short, as a box labels them.
_NAMES = {
    "h264": "H.264", "hevc": "HEVC", "av1": "AV1", "vp9": "VP9", "vp8": "VP8",
    "mpeg2video": "MPEG-2", "mpeg1video": "MPEG-1", "mpeg4": "MPEG-4", "vc1": "VC-1",
    "prores": "ProRes", "mjpeg": "Motion JPEG",
    "aac": "AAC", "ac3": "AC-3", "eac3": "E-AC-3", "truehd": "TrueHD", "dts": "DTS",
    "flac": "FLAC", "mp3": "MP3", "mp2": "MP2", "opus": "Opus", "vorbis": "Vorbis",
    "alac": "ALAC", "wmav2": "WMA",
}  # fmt: skip
_CHANNELS = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}


def station(number: int | None, name: str = "", *, mid: bool = False) -> str:
    """A station as the log names it: "station 2, Cartoon Classics"; or
    "station 2" when its name says no more (it has none, or is "Station
    2"). `mid`: in the middle of a sentence, where a name is closed with a
    comma too ("station 2, Cartoon Classics, is back on the air")."""
    if number is None:
        return "a station"
    named = plain(name or "")
    if not named or named.casefold() == f"station {number}":
        return f"station {number}"
    return f"station {number}, {named}" + ("," if mid else "")


def cap(text: str) -> str:
    """`text` starting a sentence."""
    return text[:1].upper() + text[1:]


def video_name(codec: str) -> str:
    name = catalog.video_codec(codec)
    return _NAMES.get(name, name.upper())


def sound_name(codec: str) -> str:
    name = catalog.audio_codec(codec)
    if name.startswith("pcm"):
        return "PCM"
    return _NAMES.get(name, name.upper())


def channels(count: int | None) -> str:
    """ "5.1", "stereo"; "" if it isn't known."""
    if not count:
        return ""
    return _CHANNELS.get(count, f"{count}-channel")


def hdr_name(transfer: str | None, dolby_vision: int | None = None) -> str:
    """An HDR picture's kind, from how ffprobe says its brightness is coded
    ("" for an ordinary picture)."""
    if transfer == "smpte2084":
        return "Dolby Vision" if dolby_vision is not None else "HDR10"
    return "HLG" if transfer == "arib-std-b67" else ""


def picture_and_sound(
    width: int, height: int, video: str, hdr: str, sound_channels: int | None, sound: str
) -> str:
    """ "1080p H.264, 5.1 E-AC-3"; "4K HEVC HDR10, 7.1 TrueHD"; "480p
    MPEG-2, no sound"."""
    size = catalog.size_label(width, height)
    picture = " ".join(p for p in (size, video_name(video) if video else "", hdr) if p)
    heard = " ".join(p for p in (channels(sound_channels), sound_name(sound)) if p)
    return f"{picture or 'a picture'}, {heard if sound else 'no sound'}"


def encoder_name(encoder: Encoder) -> str:
    """Where a picture is made: "the CPU", "the Intel/AMD GPU"."""
    if encoder.kind == "vaapi":
        return "the Intel/AMD GPU"
    if encoder.kind == "nvidia":
        return "the NVIDIA GPU"
    return "the CPU"


def mbps(kbps: float) -> str:
    """ "3.5 Mbps", "12 Mbps"."""
    return f"{kbps / 1000:.1f}".removesuffix(".0") + " Mbps"


def file_name(path: str) -> str:
    """A file's name, without its folders (or, for an address, what's
    asked of it)."""
    found = re.split(r"[/\\]", path.split("?", 1)[0].rstrip("/\\"))[-1]
    return found or "its file"


def size(height: int) -> str:
    """A picture made `height` lines tall, as people say it: "720p"."""
    return f"{height}p"


def clock(seconds: float) -> str:
    """A place in a program: "42:10", "1:02:03"."""
    whole = max(0, int(seconds))
    h, rest = divmod(whole, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def minutes(seconds: float) -> str:
    """How long someone watched: "35 min", "1 hr 20 min", "less than a minute"."""
    whole = round(seconds / 60)
    if whole < 1:
        return "less than a minute"
    hours, rest = divmod(whole, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} hr {rest} min" if rest else f"{hours} hr"


def ago(seconds: float) -> str:
    """How long ago: "a moment ago", "12 minutes ago", "3 hours ago", "2
    days ago"."""
    if seconds < 90:
        return "a moment ago"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} minutes ago"
    if seconds < 36 * 3600:
        hours = round(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = round(seconds / 86400)
    return f"{days} days ago"


def title(entry: Entry) -> str:
    """Something from Media, as the log names it: "Northbound · S2 E4",
    "Jaws (1975)"."""
    if entry.kind == catalog.EPISODE:
        show = entry.show_title or "An episode"
        if entry.season is not None and entry.episode is not None:
            return f"{show} · S{entry.season} E{entry.episode}"
        return f"{show} · {entry.title}" if entry.title else show
    return f"{entry.title} ({entry.year})" if entry.year else entry.title


def own(app: str) -> str:
    """An app's label (see appapi.app_label) after someone's name: "Pat's
    StationPlay for Roku on Den", "Pat's StationPlay app on Den"."""
    if app.startswith("A StationPlay app"):
        return app[2:]
    return app or "app"


@dataclass(frozen=True)
class Watcher:
    """Who's watching through one of StationPlay's apps, as far as
    StationPlay knows."""

    address: str  # where it's watching from
    away: bool = False
    person: str = ""  # who's signed in on it ("" if not known)
    user_id: int | None = None  # (their StationPlay id)
    app: str = ""  # which app on which device (appapi.app_label), "" if not known
    key: str = ""  # away from home: the start of its stream's own address

    @property
    def where(self) -> str:
        """ "at home (192.168.1.20)", "away from home (HJ1mNj)"."""
        if self.away:
            return f"away from home ({self.key or self.address})"
        return f"at home ({self.address})"

    def subject(self, *, start: bool = True) -> str:
        """The app, starting a sentence (or not, `start`): "Pat's
        StationPlay for Roku on Den at home (192.168.1.20)"; "An app at home
        (192.168.1.20)"."""
        if not self.person:
            return f"{'An' if start else 'an'} app {self.where}"
        return f"{self.person}'s {own(self.app)} {self.where}"


class Apps:
    """Whose app is at each address on the home network, and at each
    stream address of its own away from home (by "k:" and its key): as each
    app last said when it asked for the stations, signed in. The newest
    APPS_KEPT are kept, in memory only."""

    def __init__(self) -> None:
        self._known: OrderedDict[str, Watcher] = OrderedDict()

    def saw(self, where: str, watcher: Watcher) -> None:
        self._known[where] = watcher
        self._known.move_to_end(where)
        while len(self._known) > APPS_KEPT:
            self._known.popitem(last=False)

    def at(self, where: str) -> Watcher | None:
        return self._known.get(where)

    def at_home(self, address: str) -> Watcher:
        """Who's watching from an address on the home network (no one known
        if no app signed in has asked for the stations from there)."""
        found = self._known.get(address)
        return found if found is not None and not found.away else Watcher(address)
