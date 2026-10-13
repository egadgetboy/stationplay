"""Folder libraries' pictures (see folders.py): where each show's, movie's
and episode's picture comes from. In this order, the first that has one:

  1. Pictures beside the videos: a show's or movie's poster.jpg, folder.jpg
     or cover.jpg; fanart, backdrop or background; logo or clearlogo;
     banner; a season's season01-poster.jpg, or poster.jpg or folder.jpg in
     its folder; an episode's <file>-thumb.jpg or <file>.jpg; a movie's
     <file>-poster.jpg and <file>-fanart.jpg (JPEG, PNG or WebP).
  2. Pictures inside the files: a cover attached to an MKV, an MP4's cover.

Nothing else yet: tapiOca's own pictures (made for titles that have none)
come later. A title without one shows as tapiOca's apps show any title
without a picture.

Pictures are only ever read from inside the media folder: every path is
resolved first (symbolic links followed), and one that ends up outside it
is refused, as is anything that isn't a file or is too big to be a picture.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
import hashlib
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from . import ffmpeg as ff
from .library import NoPicture

log = logging.getLogger(__name__)

PICTURE_MOST = 20 << 20  # a picture's bytes, at most
FOLDER = "folder-art"  # in the data folder: covers taken out of files
# The names of pictures beside the videos, by what they are.
POSTER_NAMES = ("poster", "folder", "cover")
BACKDROP_NAMES = ("fanart", "backdrop", "background")
LOGO_NAMES = ("clearlogo", "logo")
BANNER_NAMES = ("banner",)
TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
MAKE_S = 30.0  # taking one picture out of a file, at most
# Pictures taken out at once, at most (the rest wait their turn).
MAKING_AT_ONCE = 2
_making = asyncio.Semaphore(MAKING_AT_ONCE)
# Reading the media folder (walking it, its pictures and NFO files, browsing
# it) happens on threads of its own: a share that hangs ties up only these,
# never the ones everything else uses (finding a station's next file, say).
DISK_AT_ONCE = 4
_disk = concurrent.futures.ThreadPoolExecutor(DISK_AT_ONCE, thread_name_prefix="tapioca-media")
T = TypeVar("T")


async def on_disk(do: Callable[..., T], *args: Any) -> T:
    """`do(*args)` on the media folder's own threads."""
    return await asyncio.get_running_loop().run_in_executor(_disk, functools.partial(do, *args))


# Reading pictures safely ----------------------------------------------------------


def inside(path: str, media_dir: str) -> str | None:
    """`path`, resolved (symbolic links followed), if it's a file inside
    `media_dir`; None otherwise."""
    try:
        real = os.path.realpath(path)
        root = os.path.realpath(media_dir)
    except (OSError, ValueError):
        return None
    if not root or os.path.commonpath([real, root]) != root or real == root:
        return None
    return real if os.path.isfile(real) else None


def read_picture(path: str, media_dir: str) -> tuple[bytes, str]:
    """A picture beside the videos: (its bytes, its type). NoPicture if it
    isn't a picture inside the media folder (or can't be read)."""
    real = inside(path, media_dir)
    kind = TYPES.get(os.path.splitext(path)[1].lower())
    if real is None or kind is None:
        raise NoPicture(path)
    try:
        with open(real, "rb") as f:
            data = f.read(PICTURE_MOST + 1)
    except OSError:
        raise NoPicture(path) from None
    if not data or len(data) > PICTURE_MOST:
        raise NoPicture(path)
    return data, kind


def find(names: dict[str, str], wanted: tuple[str, ...], folder: str) -> str:
    """The first of the `wanted` pictures in a folder (`names`: its file
    names, by their casefolded names), as a path; "" if it has none."""
    for name in wanted:
        for ext in TYPES:
            found = names.get(f"{name}{ext}")
            if found:
                return os.path.join(folder, found)
    return ""


# Taken out of files ------------------------------------------------------------------


def _kept(data_dir: Path, what: str, key: str, ext: str) -> Path:
    digest = hashlib.sha1(key.encode()).hexdigest()[:24]
    return data_dir / FOLDER / what / f"{digest}{ext}"


async def _run(args: list[str], timeout: float = MAKE_S) -> bytes | None:
    """ffmpeg at the lowest priority: what it wrote to its output, or None."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *ff.low_priority(), *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
    except OSError:
        return None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        return None
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
    return out if proc.returncode == 0 else None


def _kept_bytes(target: Path) -> bytes | None:
    try:
        return target.read_bytes() if target.is_file() else None
    except OSError:
        return None


def _keep(part: Path, target: Path) -> bool:
    """Moves what ffmpeg made into place: False if it made nothing."""
    try:
        if not part.is_file() or not part.stat().st_size:
            return False
        os.replace(part, target)
        return True
    finally:
        with contextlib.suppress(OSError):
            part.unlink()


async def _made(target: Path, args: list[str]) -> bytes | None:
    """A picture ffmpeg writes to `target` (kept there), made once."""
    kept = await asyncio.to_thread(_kept_bytes, target)
    if kept is not None:
        return kept
    async with _making:
        kept = await asyncio.to_thread(_kept_bytes, target)  # (made while this one waited)
        if kept is not None:
            return kept
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        part = target.with_name(f".{target.name}.{os.getpid()}")
        made = await _run([*args, str(part)])
        if made is None or not await asyncio.to_thread(_keep, part, target):
            with contextlib.suppress(OSError):
                await asyncio.to_thread(part.unlink)
            return None
    return await asyncio.to_thread(_kept_bytes, target)


async def cover(
    ffmpeg: str, data_dir: Path, file: str, stream: int, codec: str, size: int
) -> tuple[bytes, str]:
    """A cover inside a file (stream `stream`: an MKV's attached picture, or
    an MP4's cover), taken out once and kept. NoPicture if it can't be."""
    ext = ".png" if codec == "png" else ".jpg"
    target = _kept(data_dir, "covers", f"{file}|{size}|{stream}", ext)
    data = await _made(
        target,
        [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", file,
         "-map", f"0:{stream}", "-frames:v", "1", "-c", "copy", "-f", "image2"],
    )  # fmt: skip
    if not data or len(data) > PICTURE_MOST:
        raise NoPicture(file)
    return data, TYPES[ext]


async def sized(
    ffmpeg: str, picture: tuple[bytes, str], width: int, height: int
) -> tuple[bytes, str]:
    """A picture made no wider than `width` and no taller than `height`
    (as it is, if it's that small already or can't be made smaller)."""
    data, _ = picture
    out = await _scaled(ffmpeg, data, width, height)
    return (out, "image/jpeg") if out else picture


async def _scaled(ffmpeg: str, data: bytes, width: int, height: int) -> bytes | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *ff.low_priority(nice=10, idle_io=False), ffmpeg, "-hide_banner", "-nostdin",
            "-loglevel", "error", *ff.UPLOADED_PICTURE, "-i", "pipe:0", "-frames:v", "1",
            "-vf", f"scale='min({width},iw)':'min({height},ih)':force_original_aspect_ratio=decrease",
            "-q:v", "3", "-f", "image2", "-c:v", "mjpeg", "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
    except OSError:
        return None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(data), MAKE_S)
    except TimeoutError:
        return None
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
    return out if proc.returncode == 0 and out else None
