"""Test files that say they're Dolby Vision: an ordinary HEVC MP4 with a
Dolby Vision configuration record (the box players read to learn a file's
profile) put into its video track. Only the record is real: the picture is
plain HEVC, which is all StationPlay's checks look at."""

from __future__ import annotations

import struct
from pathlib import Path

# Boxes that only hold other boxes, down to the video's sample entry.
_PARENTS = (b"moov", b"trak", b"mdia", b"minf", b"stbl")


def _boxes(data: bytes, start: int, end: int) -> list[tuple[bytes, int, int]]:
    """The boxes in data[start:end]: (type, offset, size)."""
    out = []
    at = start
    while at + 8 <= end:
        size, kind = struct.unpack(">I4s", data[at : at + 8])
        if size < 8:
            raise ValueError("unexpected box size")
        out.append((kind, at, size))
        at += size
    return out


def _entry(
    data: bytes, path: list[int], start: int, end: int, parents: tuple[bytes, ...]
) -> tuple[list[int], int, int] | None:
    """The HEVC sample entry under data[start:end], through boxes of the
    types `parents` in turn: (the boxes it's inside, its offset, its size)."""
    if not parents:
        for kind, at, size in _boxes(data, start, end):
            if kind in (b"hvc1", b"hev1"):
                return path, at, size
        return None
    for kind, at, size in _boxes(data, start, end):
        if kind == parents[0]:
            # (Inside stsd: its version, flags and entry count come first.)
            inner = at + 8 + (8 if kind == b"stsd" else 0)
            found = _entry(data, [*path, at], inner, at + size, parents[1:])
            if found is not None:
                return found
    return None


def _record(profile: int, compatibility: int) -> bytes:
    """A Dolby Vision configuration record (24 bytes), level 6, with an RPU
    and a base layer."""
    bits = (profile << 9) | (6 << 3) | (1 << 2) | (0 << 1) | 1
    return struct.pack(">BBHI16x", 1, 0, bits, compatibility << 28)


def add_dolby_vision(mp4: Path, profile: int, compatibility: int) -> None:
    """Gives `mp4` (an HEVC MP4 with its index at the end, as ffmpeg writes
    one by default) a Dolby Vision record: `profile` (5, 8...) and the
    base layer's compatibility (0: none, 1: HDR10, 2: SDR, 4: HLG)."""
    data = bytearray(mp4.read_bytes())
    kind = b"dvcC" if profile <= 7 else b"dvvC"
    box = struct.pack(">I4s", 32, kind) + _record(profile, compatibility)
    # Find the HEVC sample entry (in whichever track has it), noting the
    # boxes it's inside.
    found = _entry(bytes(data), [], 0, len(data), (*_PARENTS, b"stsd"))
    if found is None:
        raise ValueError("no HEVC video")
    path, entry, entry_size = found
    # Inside the sample entry: 78 bytes of its own, then boxes (hvcC...).
    data[entry + entry_size : entry + entry_size] = box
    for at in (*path, entry):
        (size,) = struct.unpack(">I", data[at : at + 4])
        data[at : at + 4] = struct.pack(">I", size + len(box))
    # The index must come after the media for this to leave offsets alone.
    mdat = [b for b in _boxes(bytes(data), 0, len(data)) if b[0] == b"mdat"]
    if not mdat or mdat[0][1] > path[0]:
        raise ValueError("the index must be at the end of the file")
    mp4.write_bytes(bytes(data))
