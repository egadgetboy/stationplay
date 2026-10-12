"""DVD picture subtitles for tests, made by hand (ffmpeg can't make
picture subtitles from text): a VobSub pair (.idx and .sub) with one
white bar on screen at each time given."""

from __future__ import annotations

import struct
from pathlib import Path

SIZE = (720, 480)
# Where the bar is drawn (DVD subtitles sit near the bottom of the picture).
BAR = (100, 380, 200, 40)  # x, y, width, height


def _pts(seconds: float) -> bytes:
    """A PES header's PTS (90 kHz)."""
    t = round(seconds * 90000)
    return bytes(
        [
            0x21 | ((t >> 29) & 0x0E),
            (t >> 22) & 0xFF,
            0x01 | ((t >> 14) & 0xFE),
            (t >> 7) & 0xFF,
            0x01 | ((t << 1) & 0xFE),
        ]
    )


def _spu(seconds: float) -> bytes:
    """A subtitle picture: the bar in colour 1, shown for `seconds`."""
    x, y, w, h = BAR
    line = struct.pack(">H", (w << 2) | 1)  # one run of w pixels of value 1
    top = line * ((h + 1) // 2)  # (even lines)
    bottom = line * (h // 2)  # (odd lines)
    pixels_at = 4
    top_at, bottom_at = pixels_at, pixels_at + len(top)
    first = 4 + len(top) + len(bottom)
    area = (x << 36) | ((x + w - 1) << 24) | (y << 12) | (y + h - 1)
    show = (
        b"\x01"  # start showing
        + b"\x03"
        + bytes([0x00, 0x10])  # colours: pixel value 1 is palette entry 1
        + b"\x04"
        + bytes([0x00, 0xF0])  # opacity: value 1 solid, value 0 clear
        + b"\x05"
        + area.to_bytes(6, "big")
        + b"\x06"
        + struct.pack(">HH", top_at, bottom_at)
        + b"\xff"
    )
    second = first + 4 + len(show)
    stop = b"\x02\xff"
    delay = round(seconds * 90000 / 1024)
    body = (
        top
        + bottom
        + struct.pack(">HH", 0, second)
        + show
        + struct.pack(">HH", delay, second)
        + stop
    )
    return struct.pack(">HH", 4 + len(body), first) + body


def _pack(seconds: float, spu: bytes) -> bytes:
    """One 2048-byte MPEG program stream pack carrying `spu` at `seconds`."""
    header = bytes.fromhex("000001BA4400040004010189C3F8")
    payload = b"\x81\x80\x05" + _pts(seconds) + b"\x20" + spu
    pes = b"\x00\x00\x01\xbd" + struct.pack(">H", len(payload)) + payload
    room = 2048 - len(header) - len(pes)
    if room < 6:
        raise ValueError("subtitle too big for one pack")
    padding = b"\x00\x00\x01\xbe" + struct.pack(">H", room - 6) + b"\xff" * (room - 6)
    return header + pes + padding


def write(stem: Path, cues: list[tuple[float, float]], language: str = "en") -> Path:
    """`stem`.idx and `stem`.sub: the bar shown during each (from, to), in
    seconds. Returns the .idx (what ffmpeg reads)."""
    sub, entries = b"", []
    for start, end in cues:
        entries.append((start, len(sub)))
        sub += _pack(start, _spu(end - start))
    stem.with_suffix(".sub").write_bytes(sub)
    palette = ", ".join(["000000", "ffffff"] + ["808080"] * 14)
    lines = [
        "# VobSub index file, v7 (do not modify this line!)",
        f"size: {SIZE[0]}x{SIZE[1]}",
        "org: 0, 0",
        "scale: 100%, 100%",
        "alpha: 100%",
        f"palette: {palette}",
        f"id: {language}, index: 0",
    ]
    for start, at in entries:
        h, rest = divmod(start, 3600)
        m, s = divmod(rest, 60)
        stamp = f"{int(h):02d}:{int(m):02d}:{int(s):02d}:{round((s % 1) * 1000):03d}"
        lines.append(f"timestamp: {stamp}, filepos: {at:09x}")
    idx = stem.with_suffix(".idx")
    idx.write_text("\n".join(lines) + "\n")
    return idx
