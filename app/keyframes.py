"""Where a file's picture has its keyframes, read from the file's own index
without reading the file: a Matroska (MKV, WebM) file's Cues, or an MP4's
(or QuickTime's) sample tables. A copy that keeps the picture as it is can
only start its pieces at keyframes (see converting.py), so knowing them up
front is what lets its playlist list the whole program before it's made.

Only what's needed is read: a few small reads at the start of the file and
its index, wherever it is. Anything unexpected gives None (not known), and
the picture is converted instead.
"""

from __future__ import annotations

import struct
from collections.abc import Awaitable, Callable

# Reads `size` bytes at `offset` (fewer at the end of the file).
Reader = Callable[[int, int], Awaitable[bytes]]

INDEX_MOST = 64 << 20  # an index bigger than this isn't read
KEYFRAMES_MOST = 500_000
HEAD_READ = 256 << 10

# Matroska's element IDs (with their length bits, as written).
_EBML = 0x1A45DFA3
_SEGMENT = 0x18538067
_SEEK_HEAD = 0x114D9B74
_SEEK = 0x4DBB
_SEEK_ID = 0x53AB
_SEEK_POSITION = 0x53AC
_INFO = 0x1549A966
_TIMESTAMP_SCALE = 0x2AD7B1
_TRACKS = 0x1654AE6B
_TRACK_ENTRY = 0xAE
_TRACK_NUMBER = 0xD7
_TRACK_TYPE = 0x83
_CUES = 0x1C53BB6B
_CUE_POINT = 0xBB
_CUE_TIME = 0xB3
_CUE_TRACK_POSITIONS = 0xB7
_CUE_TRACK = 0xF7
_CLUSTER = 0x1F43B675
_VIDEO_TRACK = 1


class _Unknown(Exception):
    """The file isn't as expected: its keyframes aren't known."""


async def keyframes(read: Reader, container: str) -> list[float] | None:
    """The times (in seconds, from the file's start) of the keyframes of a
    file's first picture, in order; None if they can't be known from its
    index (or it has none)."""
    try:
        if container in ("mkv", "webm"):
            found = await _matroska(read)
        elif container in ("mp4", "mov"):
            found = await _mp4(read)
        else:
            return None
    except (_Unknown, struct.error, IndexError, ValueError, OverflowError):
        return None
    times = sorted({round(t, 6) for t in found if t >= 0})
    return times if times and len(times) <= KEYFRAMES_MOST else None


# Matroska ---------------------------------------------------------------------------


def _vint(data: bytes, at: int, keep_marker: bool) -> tuple[int, int]:
    """A variable-length number at `at`: (its value, where it ends)."""
    first = data[at]
    if first == 0:
        raise _Unknown("a number longer than 8 bytes")
    length = 1
    while not first & (0x80 >> (length - 1)):
        length += 1
    value = first if keep_marker else first & (0xFF >> length)
    for b in data[at + 1 : at + length]:
        value = (value << 8) | b
    if at + length > len(data):
        raise IndexError
    return value, at + length


def _element(data: bytes, at: int) -> tuple[int, int, int]:
    """An element's (ID, where its data starts, its size; -1 if unknown)."""
    ident, at = _vint(data, at, True)
    first = data[at]
    size, start = _vint(data, at, False)
    length = start - at
    if size == (1 << (7 * length)) - 1 and first != 0:  # (all ones: unknown size)
        size = -1
    return ident, start, size


def _children(data: bytes, start: int, end: int):
    """The elements in data[start:end]: (ID, where its data starts, size)."""
    at = start
    while at < end:
        ident, begin, size = _element(data, at)
        if size < 0:
            raise _Unknown("an element of unknown size inside another")
        yield ident, begin, size
        at = begin + size


def _uint(data: bytes, start: int, size: int) -> int:
    return int.from_bytes(data[start : start + size], "big") if size else 0


async def _matroska(read: Reader) -> list[float]:
    head = await read(0, HEAD_READ)
    ident, start, size = _element(head, 0)
    if ident != _EBML:
        raise _Unknown("not Matroska")
    ident, segment, _ = _element(head, start + size)
    if ident != _SEGMENT:
        raise _Unknown("no segment")
    scale = 1_000_000
    video_track: int | None = None
    cues_at: int | None = None
    # The segment's first elements, up to its first cluster: what's in them
    # is in the head read, or read on its own.
    at = segment
    while True:
        if at + 12 > len(head):
            head += await read(len(head), HEAD_READ)
            if at + 12 > len(head):
                break
        ident, begin, size = _element(head, at)
        if ident == _CLUSTER or size < 0:
            break
        if ident in (_SEEK_HEAD, _INFO, _TRACKS) and size > INDEX_MOST:
            raise _Unknown("an element too big")
        if ident in (_SEEK_HEAD, _INFO, _TRACKS) and begin + size > len(head):
            head += await read(len(head), begin + size - len(head))
        if ident == _SEEK_HEAD:
            for kind, seek_begin, seek_size in _children(head, begin, begin + size):
                if kind != _SEEK:
                    continue
                target = position = None
                for field, b, n in _children(head, seek_begin, seek_begin + seek_size):
                    if field == _SEEK_ID:
                        target = _uint(head, b, n)
                    elif field == _SEEK_POSITION:
                        position = _uint(head, b, n)
                if target == _CUES and position is not None:
                    cues_at = segment + position
        elif ident == _INFO:
            for field, b, n in _children(head, begin, begin + size):
                if field == _TIMESTAMP_SCALE:
                    scale = _uint(head, b, n) or scale
        elif ident == _TRACKS:
            for kind, b, n in _children(head, begin, begin + size):
                if kind != _TRACK_ENTRY:
                    continue
                number = kind_of = None
                for field, fb, fn in _children(head, b, b + n):
                    if field == _TRACK_NUMBER:
                        number = _uint(head, fb, fn)
                    elif field == _TRACK_TYPE:
                        kind_of = _uint(head, fb, fn)
                if kind_of == _VIDEO_TRACK and number is not None and video_track is None:
                    video_track = number
        elif ident == _CUES:
            cues_at = at
        at = begin + size
    if video_track is None or cues_at is None:
        raise _Unknown("no picture, or no index")
    top = await read(cues_at, 16)
    ident, begin, size = _element(top, 0)
    if ident != _CUES or not 0 < size <= INDEX_MOST:
        raise _Unknown("no index where it should be")
    cues = await read(cues_at + begin, size)
    if len(cues) < size:
        raise _Unknown("the index is cut short")
    out = []
    for kind, b, n in _children(cues, 0, size):
        if kind != _CUE_POINT:
            continue
        time = None
        tracks = set()
        for field, fb, fn in _children(cues, b, b + n):
            if field == _CUE_TIME:
                time = _uint(cues, fb, fn)
            elif field == _CUE_TRACK_POSITIONS:
                for part, pb, pn in _children(cues, fb, fb + fn):
                    if part == _CUE_TRACK:
                        tracks.add(_uint(cues, pb, pn))
        if time is not None and video_track in tracks:
            out.append(time * scale / 1e9)
    if not out:
        raise _Unknown("no keyframes in the index")
    return out


# MP4 and QuickTime --------------------------------------------------------------------


async def _box_at(read: Reader, at: int) -> tuple[bytes, int, int] | None:
    """The box at `at`: (its type, where its contents start, where it ends);
    None at the end of the file."""
    head = await read(at, 16)
    if len(head) < 8:
        return None
    size, kind = struct.unpack(">I4s", head[:8])
    begin = at + 8
    if size == 1:
        if len(head) < 16:
            return None
        size = struct.unpack(">Q", head[8:16])[0]
        begin = at + 16
    elif size == 0:
        raise _Unknown("a box running to the end of the file")  # (only mdat does, last)
    if size < begin - at:
        raise _Unknown("a broken box")
    return kind, begin, at + size


def _boxes(data: bytes, start: int, end: int):
    """The boxes in data[start:end]: (type, where its contents start, end)."""
    at = start
    while at + 8 <= end:
        size, kind = struct.unpack(">I4s", data[at : at + 8])
        begin = at + 8
        if size == 1:
            size = struct.unpack(">Q", data[at + 8 : at + 16])[0]
            begin = at + 16
        elif size == 0:
            size = end - at
        if size < begin - at or at + size > end:
            raise _Unknown("a broken box")
        yield kind, begin, at + size
        at += size


def _find(data: bytes, start: int, end: int, *path: bytes) -> tuple[int, int] | None:
    """The contents of the box at `path` under data[start:end]."""
    for kind, b, e in _boxes(data, start, end):
        if kind == path[0]:
            return (b, e) if len(path) == 1 else _find(data, b, e, *path[1:])
    return None


async def _mp4(read: Reader) -> list[float]:
    at = 0
    moov: bytes | None = None
    for _ in range(1000):
        box = await _box_at(read, at)
        if box is None:
            break
        kind, begin, end = box
        if kind == b"moov":
            if end - begin > INDEX_MOST:
                raise _Unknown("an index too big")
            moov = await read(begin, end - begin)
            break
        at = end
    if moov is None:
        raise _Unknown("no index")
    mvhd = _find(moov, 0, len(moov), b"mvhd")
    if mvhd is None:
        raise _Unknown("no movie header")
    version = moov[mvhd[0]]
    movie_scale = struct.unpack(">I", moov[mvhd[0] + (20 if version == 1 else 12) :][:4])[0]
    for kind, b, e in _boxes(moov, 0, len(moov)):
        if kind != b"trak":
            continue
        handler = _find(moov, b, e, b"mdia", b"hdlr")
        if handler is None or moov[handler[0] + 8 : handler[0] + 12] != b"vide":
            continue
        return _track_keyframes(moov, b, e, movie_scale)
    raise _Unknown("no picture")


def _track_keyframes(moov: bytes, start: int, end: int, movie_scale: int) -> list[float]:
    """A picture track's keyframe times, as players show them: each frame's
    composition offset added, and its edit list followed (where the track
    starts being shown, and any wait before it)."""
    mdhd = _find(moov, start, end, b"mdia", b"mdhd")
    stbl = _find(moov, start, end, b"mdia", b"minf", b"stbl")
    if mdhd is None or stbl is None:
        raise _Unknown("no sample tables")
    version = moov[mdhd[0]]
    scale = struct.unpack(">I", moov[mdhd[0] + (20 if version == 1 else 12) :][:4])[0]
    if not scale:
        raise _Unknown("no timescale")
    stss = _find(moov, *stbl, b"stss")
    stts = _find(moov, *stbl, b"stts")
    if stts is None:
        raise _Unknown("no sample times")
    # Each sample's decoding time.
    count = struct.unpack(">I", moov[stts[0] + 4 : stts[0] + 8])[0]
    decode: list[int] = []
    t = 0
    for i in range(count):
        n, delta = struct.unpack(">II", moov[stts[0] + 8 + 8 * i : stts[0] + 16 + 8 * i])
        if len(decode) + n > KEYFRAMES_MOST * 1000:
            raise _Unknown("too many samples")
        for _ in range(n):
            decode.append(t)
            t += delta
    if stss is None:  # (every sample a keyframe)
        keys = list(range(1, len(decode) + 1))
    else:
        count = struct.unpack(">I", moov[stss[0] + 4 : stss[0] + 8])[0]
        keys = list(struct.unpack(f">{count}I", moov[stss[0] + 8 : stss[0] + 8 + 4 * count]))
    # Composition offsets, where frames are shown in another order.
    shown = {}
    ctts = _find(moov, *stbl, b"ctts")
    if ctts is not None:
        version = moov[ctts[0]]
        count = struct.unpack(">I", moov[ctts[0] + 4 : ctts[0] + 8])[0]
        sample = 1
        wanted = set(keys)
        for i in range(count):
            n, offset = struct.unpack(
                ">Ii" if version == 1 else ">II", moov[ctts[0] + 8 + 8 * i : ctts[0] + 16 + 8 * i]
            )
            for s in range(sample, sample + n):
                if s in wanted:
                    shown[s] = offset
            sample += n
    # The edit list: where the track begins being shown, after any wait.
    first_shown = 0
    wait_s = 0.0
    elst = _find(moov, start, end, b"edts", b"elst")
    if elst is not None:
        version = moov[elst[0]]
        count = struct.unpack(">I", moov[elst[0] + 4 : elst[0] + 8])[0]
        at = elst[0] + 8
        for _ in range(count):
            if version == 1:
                duration, media_time = struct.unpack(">Qq", moov[at : at + 16])
                at += 20
            else:
                duration, media_time = struct.unpack(">Ii", moov[at : at + 8])
                at += 12
            if media_time >= 0:
                first_shown = media_time
                break
            if movie_scale:  # (an empty edit: a wait before the track starts)
                wait_s += duration / movie_scale
    return [
        wait_s + (decode[k - 1] + shown.get(k, 0) - first_shown) / scale
        for k in keys
        if 0 < k <= len(decode)
    ]
