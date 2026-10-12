"""Station logos: StationPlay's own library (drawn by tools/logos/build.py),
and your own: ones you upload, and shows' and movies' logos from Plex."""

from __future__ import annotations

import asyncio
import json
import random
import re
import secrets
import time
from pathlib import Path

from .db import Database
from .ffmpeg import UPLOADED_PICTURE
from .text import name_from_file

LOGO_DIR = Path(__file__).parent / "logos"
# Uploaded logos are made the same size and shape as the library's: a
# 512x512 PNG, the picture fitted inside with a transparent background.
SIZE = 512
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MOST_UPLOADED = 500  # logos of your own, at most (each is tens of KB)
UPLOAD_PREFIX = "upload-"
YOURS = "Your logos"
# Letters and numbers say nothing on their own, so they're never handed out
# at random (a new station 1-50 gets its own number instead).
LETTERING = {"Letters", "Numbers", "Retro letters", "Retro numbers"}
NUMBERED = range(1, 51)
# The logo stations made from Plex collections start with (never handed out
# at random either).
COLLECTION_LOGO = "collection"
UNREADABLE = (
    "StationPlay can't read that picture. Use a PNG, JPEG, WebP, GIF, or BMP (under 40 megapixels)."
)


def _load(directory: Path) -> tuple[int, list[dict], dict[str, str]]:
    """(version, logos, {old logo: the logo that replaced it}) from the
    library's catalog.json. (Before 1.7 it was just the list of logos.)"""
    try:
        data = json.loads((directory / "catalog.json").read_text())
    except (OSError, ValueError):
        return 1, [], {}
    if isinstance(data, list):
        return 1, data, {}
    return int(data.get("version", 1)), list(data.get("logos", [])), dict(data.get("replaced", {}))


# The library's version: part of each logo's address, so browsers and Plex
# fetch new pictures when the library changes instead of showing old ones.
LIBRARY_VERSION = _load(LOGO_DIR)[0]


class LogoError(Exception):
    """An upload that can't be used as a logo."""


class LogoLibrary:
    def __init__(
        self,
        directory: Path = LOGO_DIR,
        uploads: Path | None = None,
        db: Database | None = None,
    ) -> None:
        self.directory = directory
        self.uploads = uploads  # where uploaded logos are kept (the data folder's logos/)
        self.db = db
        self.version, self._catalog, self.replaced = _load(directory)
        self._ids = {logo["id"] for logo in self._catalog}

    def _uploaded(self) -> list[tuple[str, str]]:
        return self.db.custom_logos() if self.db is not None and self.uploads else []

    def catalog(self) -> list[dict]:
        """Your logos first, then the library's."""
        mine = [{"id": i, "name": n, "category": YOURS} for i, n in self._uploaded()]
        return mine + self._catalog

    def resolve(self, logo_id: str) -> str:
        """The logo to use for `logo_id`: itself, or, for a logo from the
        library before 1.7, the new one that replaced it."""
        return self.replaced.get(logo_id, logo_id)

    def url(self, logo_id: str) -> str:
        """Where the page fetches a logo from (with the library's version,
        so it isn't shown from an old copy)."""
        if logo_id.startswith(UPLOAD_PREFIX):
            return f"/logos/{logo_id}.png"
        return f"/logos/{self.resolve(logo_id)}.png?v={self.version}"

    def path(self, logo_id: str) -> Path | None:
        logo_id = self.resolve(logo_id)
        if logo_id in self._ids:
            return self.directory / f"{logo_id}.png"
        if logo_id.startswith(UPLOAD_PREFIX) and self.uploads is not None:
            path = self.uploads / f"{logo_id}.png"
            if any(i == logo_id for i, _ in self._uploaded()) and path.is_file():
                return path
        return None

    def exists(self, logo_id: str) -> bool:
        return self.path(logo_id) is not None

    def pick(
        self, taken: set[str], rng: random.Random | None = None, number: int | None = None
    ) -> str:
        """A logo for a new station: its own number (stations 1-50), or else
        a random picture from the library, one no other station has if
        possible. Your own logos are only ever used if you choose them."""
        if number in NUMBERED and f"number-{number}-modern" in self._ids:
            return f"number-{number}-modern"
        rng = rng or random.Random()
        pool = [
            logo["id"]
            for logo in self._catalog
            if logo["category"] not in LETTERING and logo["id"] != COLLECTION_LOGO
        ]
        free = [logo_id for logo_id in pool if logo_id not in taken]
        return rng.choice(free or pool) if pool else ""

    async def add(self, data: bytes, name: str, ffmpeg_path: str) -> dict:
        """Adds an uploaded picture as a logo; returns its catalog entry."""
        if self.uploads is None or self.db is None:
            raise LogoError("Uploading logos isn't available")
        if not data:
            raise LogoError("That file is empty")
        if len(data) > MAX_UPLOAD_BYTES:
            raise LogoError(f"That file is too big (the limit is {MAX_UPLOAD_BYTES // 2**20} MB)")
        self.check_room()
        png = await to_logo_png(data, ffmpeg_path)
        return self.keep(png, name_from_file(name, "My logo"))

    def keep(self, png: bytes, name: str, logo_id: str | None = None) -> dict:
        """Keeps a PNG StationPlay made as one of your logos, called `name`;
        returns its catalog entry. With `logo_id` (one that's always the same
        for the same picture), a logo you have already is just returned."""
        if self.uploads is None or self.db is None:
            raise LogoError("Adding logos isn't available")
        if logo_id is None:
            logo_id = UPLOAD_PREFIX + secrets.token_hex(5)
        else:
            for have, have_name in self._uploaded():
                if have == logo_id and (self.uploads / f"{logo_id}.png").is_file():
                    return {"id": logo_id, "name": have_name, "category": YOURS}
        self.check_room()
        self.uploads.mkdir(parents=True, exist_ok=True)
        (self.uploads / f"{logo_id}.png").write_bytes(png)
        if not any(have == logo_id for have, _ in self._uploaded()):
            self.db.add_custom_logo(logo_id, name, int(time.time() * 1000))
        return {"id": logo_id, "name": name, "category": YOURS}

    def check_room(self) -> None:
        """LogoError if there are as many logos of your own as can be."""
        if len(self._uploaded()) >= MOST_UPLOADED:
            raise LogoError(
                f"You already have {MOST_UPLOADED} logos of your own. Delete one to add another."
            )

    def remove(self, logo_id: str) -> bool:
        """Deletes an uploaded logo (even one whose picture has gone missing);
        False if there's no such logo."""
        if not any(i == logo_id for i, _ in self._uploaded()):
            return False
        assert self.db is not None and self.uploads is not None
        self.db.delete_custom_logo(logo_id)
        (self.uploads / f"{logo_id}.png").unlink(missing_ok=True)
        return True


async def to_logo_png(data: bytes, ffmpeg_path: str) -> bytes:
    """A PNG, JPEG, WebP, GIF or BMP picture as a logo: a SIZE x SIZE PNG,
    fitted in and centred on a transparent background. Re-drawing it means
    only a clean PNG StationPlay made is ever kept."""
    fit = (
        f"scale={SIZE}:{SIZE}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"format=rgba,pad={SIZE}:{SIZE}:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
    )
    return await _redrawn(data, ffmpeg_path, fit)


# A show's or movie's logo from Plex (its "clear logo": usually a wide
# wordmark) keeps its own shape, so it can be shown as large as the
# library's square logos look (see ffmpeg.logo_box). It's trimmed to what's
# drawn, with the room around it a library logo typically has (what's drawn
# is about FILLED of its width and height), and made no larger than
# WIDEST x SIZE, nor SIZE tall. Nor more than MAX_STRETCH times as wide
# as it's tall (or the other way): a thinner one gets more room above and
# below (or at the sides), so it's never drawn too thin to show.
FILLED = 0.855
WIDEST = 2 * SIZE
MAX_STRETCH = 8
# How see-through a pixel may be and still count as drawn (out of 255):
# fainter than this is a soft glow's edge, or nothing.
DRAWN_FROM = 10
_DRAWN = re.compile(rb"^\[Parsed_bbox_\d+ @ [^\]]*\] .*crop=(\d+):(\d+):(\d+):(\d+)", re.M)


async def to_trimmed_logo_png(data: bytes, ffmpeg_path: str) -> bytes:
    """A logo from Plex as a PNG in its own shape (see FILLED)."""
    measure = [
        ffmpeg_path, "-hide_banner", "-nostats", "-loglevel", "info",
        *UPLOADED_PICTURE, "-i", "pipe:0", "-frames:v", "1",
        "-vf", f"format=rgba,alphaextract,bbox=min_val={DRAWN_FROM}", "-f", "null", "-",
    ]  # fmt: skip
    code, _, said = await _ffmpeg(measure, data)
    if code != 0:
        raise LogoError(UNREADABLE)
    found = _DRAWN.findall(said)
    if not found:
        raise LogoError("That logo looks blank. There's nothing in it to show.")
    w, h, x, y = (int(v) for v in found[-1])
    if w < 4 or h < 4:
        raise LogoError("That logo looks blank. There's nothing in it to show.")
    # The whole picture: what's drawn with room around it, fitted in WIDEST
    # x SIZE; then what's drawn at that scale (at least a pixel narrower
    # than the whole, each way).
    whole_w, whole_h = w / FILLED, h / FILLED
    whole_w, whole_h = (
        max(whole_w, whole_h / MAX_STRETCH),
        max(whole_h, whole_w / MAX_STRETCH),
    )
    scale = min(WIDEST / whole_w, SIZE / whole_h)
    out_w, out_h = max(2, round(whole_w * scale)), max(2, round(whole_h * scale))
    drawn_w = max(1, min(out_w - 1, round(w * scale)))
    drawn_h = max(1, min(out_h - 1, round(h * scale)))
    fit = (
        f"format=rgba,crop={w}:{h}:{x}:{y},scale={drawn_w}:{drawn_h}:flags=lanczos,"
        f"format=rgba,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
    )
    return await _redrawn(data, ffmpeg_path, fit)


async def to_kept_logo_png(data: bytes, ffmpeg_path: str) -> bytes:
    """A logo of yours from a backup, drawn again as it was kept: square (as
    an upload is), or in its own shape (as a logo from Plex is), and no
    larger or more stretched than either."""
    fit = (
        f"scale=w='min(iw,{WIDEST})':h='min(ih,{SIZE})':force_original_aspect_ratio=decrease"
        f":flags=lanczos,format=rgba,pad=w='max(iw,ceil(ih/{MAX_STRETCH}))'"
        f":h='max(ih,ceil(iw/{MAX_STRETCH}))':x=(ow-iw)/2:y=(oh-ih)/2:color=0x00000000"
    )
    return await _redrawn(data, ffmpeg_path, fit)


async def _redrawn(data: bytes, ffmpeg_path: str, fit: str) -> bytes:
    """A picture drawn again by ffmpeg through `fit`, as a PNG; LogoError if
    it can't be read."""
    args = [
        ffmpeg_path, "-hide_banner", "-v", "error",
        *UPLOADED_PICTURE, "-i", "pipe:0", "-frames:v", "1", "-vf", fit,
        "-f", "image2", "-c:v", "png", "pipe:1",
    ]  # fmt: skip
    code, out, _ = await _ffmpeg(args, data)
    if code != 0 or not out.startswith(b"\x89PNG"):
        raise LogoError(UNREADABLE)
    return out


async def _ffmpeg(args: list[str], data: bytes) -> tuple[int, bytes, bytes]:
    """Runs ffmpeg with `data` as its input: (exit code, output, messages)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        raise LogoError(f"StationPlay couldn't start ffmpeg to read that picture ({e})") from None
    try:
        out, said = await asyncio.wait_for(proc.communicate(data), 30)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise LogoError("That picture took too long to read") from None
    return proc.returncode or 0, out, said
