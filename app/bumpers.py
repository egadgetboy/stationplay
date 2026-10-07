"""Intro Bumpers you make yourself: short videos uploaded in the station
editor, which a station can play when someone tunes in instead of the card
StationPlay draws.

Each upload is checked and made again as a clean MP4 the size of the stream,
its sound evened out (or silence, if it had none), so only a file StationPlay
made is ever played on the air. They're kept in the data folder's bumpers/
folder as <id>.mp4 and <id>.json (its name and length): the folder is the
library, and the database only says which one a station plays.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from . import ffmpeg as ff
from .config import Settings
from .text import name_from_file

MAX_UPLOAD_BYTES = 500 * 1024 * 1024
MOST = 50  # Intro Bumpers kept, at most (each is a few MB)
MIN_SECONDS = 1.0
MAX_SECONDS = 30.0
PREFIX = "bumper-"
_ID = re.compile(r"bumper-[0-9a-f]{10}")
# Making the clean copy, at low priority and on a few threads so streams
# never wait for it: a 30-second video takes seconds, a slow NAS longer.
CONVERT_TIMEOUT_S = 600
CONVERT_THREADS = 2


class BumperError(Exception):
    """An upload that can't be used as an Intro Bumper."""


@dataclass(frozen=True)
class Bumper:
    """A bumper in the library. Its copy has the picture as its first video
    stream and stereo sound as its first audio stream, `width` x `height`
    (the stream's size when it was made)."""

    id: str
    name: str
    seconds: float
    width: int
    height: int
    added_ms: int


class BumperLibrary:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._lock = asyncio.Lock()  # one upload is made at a time

    def get(self, bumper_id: str) -> Bumper | None:
        """The bumper, if it's there (its video and what it is)."""
        if not _ID.fullmatch(bumper_id) or not (self.folder / f"{bumper_id}.mp4").is_file():
            return None
        try:
            info = json.loads((self.folder / f"{bumper_id}.json").read_text())
            bumper = Bumper(
                bumper_id,
                str(info["name"]),
                float(info["seconds"]),
                int(info["width"]),
                int(info["height"]),
                int(info["added_ms"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return bumper if bumper.seconds > 0 and bumper.width > 0 and bumper.height > 0 else None

    def catalog(self) -> list[Bumper]:
        """Every bumper, newest first."""
        found = (self.get(p.stem) for p in self.folder.glob(f"{PREFIX}*.json"))
        return sorted((b for b in found if b), key=lambda b: b.added_ms, reverse=True)

    def path(self, bumper: Bumper) -> Path:
        return self.folder / f"{bumper.id}.mp4"

    def clear_leftovers(self) -> None:
        """Removes what an upload StationPlay was stopped in the middle of
        left behind (its hidden working files)."""
        if self.folder.is_dir():
            for leftover in self.folder.glob(".*"):
                leftover.unlink(missing_ok=True)

    async def add(
        self, upload: Path, name: str, settings: Settings, tone_map: bool = False
    ) -> Bumper:
        """Adds the video in `upload` (which is left where it is) as a bumper,
        its picture the size `settings` give. `tone_map`: whether an HDR
        picture can be made ordinary (see ff.to_sdr)."""
        self.check_room()
        probed = await ff.probe(settings, str(upload), timeout=60, options=ff.UPLOADED_VIDEO)
        if not probed.ok:
            raise BumperError(
                "StationPlay can't play that file. Use a video such as MP4, MOV, MKV, or WebM."
            )
        if probed.dolby_vision_only:
            raise BumperError(
                f"That video is Dolby Vision profile {probed.dolby_vision}, which StationPlay "
                "can't show in its true colors. Save it as HDR10 or standard video and try again."
            )
        if not tone_map:
            probed = replace(probed, hdr=None)
        # (Some files don't say how long they are: the copy's picture is
        # measured too.)
        if probed.duration_s is not None:
            _check_length(probed.duration_s)
        bumper_id = PREFIX + secrets.token_hex(5)
        picture = self.folder / f".{bumper_id}-picture.mp4"
        made = self.folder / f".{bumper_id}.mp4"
        async with self._lock:
            try:
                await asyncio.to_thread(self.folder.mkdir, parents=True, exist_ok=True)
                # The picture first, measured exactly; then the sound, made
                # exactly as long.
                await _make(_picture_command(settings, upload, probed, picture))
                seconds = (await ff.probe(settings, str(picture), timeout=30)).duration_s or 0.0
                _check_length(seconds)
                await _make(_sound_command(settings, upload, probed, picture, seconds, made))
                done = await ff.probe(settings, str(made), timeout=30)
                if not done.ok or done.audio_index is None:
                    raise BumperError(
                        "StationPlay couldn't convert that video into a format it can play"
                    )
                bumper = Bumper(
                    bumper_id,
                    name_from_file(name, "My bumper"),
                    round(seconds, 3),
                    settings.video_width,
                    settings.video_height,
                    int(time.time() * 1000),
                )
                await asyncio.to_thread(self._keep, bumper, made)
                return bumper
            finally:
                for leftover in (picture, made):
                    await asyncio.to_thread(leftover.unlink, missing_ok=True)

    def _keep(self, bumper: Bumper, made: Path) -> None:
        """Puts a finished copy in the library: what it is first, then the
        video, so a bumper is never there without its name and length."""
        info = {k: v for k, v in asdict(bumper).items() if k != "id"}
        tmp = self.folder / f".{bumper.id}.json"
        tmp.write_text(json.dumps(info))
        os.replace(tmp, self.folder / f"{bumper.id}.json")
        os.replace(made, self.folder / f"{bumper.id}.mp4")

    def check_room(self) -> None:
        """BumperError if there are as many Intro Bumpers as can be."""
        if len(self.catalog()) >= MOST:
            raise BumperError(
                f"You already have {MOST} Intro Bumper videos. Delete one to add another."
            )

    def remove(self, bumper_id: str) -> bool:
        """Deletes a bumper; False if there's no such bumper."""
        if not _ID.fullmatch(bumper_id) or not (self.folder / f"{bumper_id}.json").is_file():
            return False
        (self.folder / f"{bumper_id}.mp4").unlink(missing_ok=True)
        (self.folder / f"{bumper_id}.json").unlink(missing_ok=True)
        return True


def _check_length(seconds: float) -> None:
    if seconds < MIN_SECONDS:
        raise BumperError("That video is too short. A bumper must be at least 1 second long.")
    if seconds > MAX_SECONDS + 0.5:
        raise BumperError(
            f"That video is {seconds:.0f} seconds long. A bumper can be up to "
            f"{MAX_SECONDS:.0f} seconds long."
        )


# (-threads before the input limits decoding; the picture's command also
# limits encoding, after it.)
_START = ["-hide_banner", "-nostdin", "-v", "error", "-y", "-threads", str(CONVERT_THREADS)]


def _picture_command(
    settings: Settings, upload: Path, probed: ff.ProbeResult, out: Path
) -> list[str]:
    """ffmpeg arguments for the copy's picture: fitted to the stream's size
    (black bars if it's another shape), at the stream's frame rate. (Cut off
    a little past the longest a bumper can be, so a file that doesn't say
    how long it is can't run on.)"""
    w, h = settings.video_width, settings.video_height
    # (An HDR picture is made ordinary, as a program's is: see ff.to_sdr.)
    ordinary = ff.to_sdr(probed)
    fit = (
        f"scale=iw*sar:ih,scale={w}:{h}:force_original_aspect_ratio=decrease:flags=bicubic,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
        f"{ordinary + ',' if ordinary else ''}fps={ff.FPS_NUM}/{ff.FPS_DEN},format=yuv420p"
    )
    return [
        settings.ffmpeg_path, *_START, *ff.UPLOADED_VIDEO, "-i", str(upload),
        "-map", f"0:v:{probed.video_index}", "-vf", fit, "-an", "-sn", "-dn",
        "-t", f"{MAX_SECONDS + 1:.3f}",
        "-threads", str(CONVERT_THREADS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-f", "mp4", str(out),
    ]  # fmt: skip


def _sound_command(
    settings: Settings,
    upload: Path,
    probed: ff.ProbeResult,
    picture: Path,
    seconds: float,
    out: Path,
) -> list[str]:
    """ffmpeg arguments for the finished copy: the picture, and the sound in
    stereo, evened out to the programs' loudness, exactly as long as the
    picture (cut short, or run on in silence)."""
    args = [settings.ffmpeg_path, *_START, "-i", str(picture)]
    if probed.audio_index is None:
        args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        sound = "[1:a]anull[a]"
    else:
        args += [*ff.UPLOADED_VIDEO, "-i", str(upload)]
        sound = (
            f"[1:a:{probed.audio_index}]aresample=48000,loudnorm={ff.LOUDNESS_TARGET},"
            "aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,apad[a]"
        )
    return [
        *args, "-filter_complex", sound, "-map", "0:v:0", "-map", "[a]",
        "-t", f"{seconds:.3f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", "-f", "mp4", str(out),
    ]  # fmt: skip


async def _make(args: list[str]) -> None:
    try:
        code, said = await ff.run_to_end([*ff.low_priority(), *args], CONVERT_TIMEOUT_S)
    except TimeoutError:
        raise BumperError("That video took too long to prepare") from None
    except OSError as e:
        raise BumperError(f"Couldn't start ffmpeg: {e}") from None
    if code != 0:
        raise BumperError(f"StationPlay couldn't prepare that video ({said[-200:] or 'it failed'})")
