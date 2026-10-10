"""Stitching separate MPEG-TS outputs into one seamless stream.

Each program is encoded by its own ffmpeg process. Two things would make
the joins visible to a player, and both are handled here as the bytes pass
through:

* Continuity counters. Every ffmpeg process numbers its packets from zero,
  which a player reads as lost or corrupt packets at each program change.
  They are renumbered so the channel looks like one unbroken mux.
* Timestamps. Each program's timeline is shifted to follow the previous
  one. The exact end of each program's audio and video is read from the
  stream itself, so the next program can start precisely after it: no
  overlap, and no gap beyond a millisecond.

A program's output is held back until its picture starts, so one that
ends without any picture sends nothing (see begin_segment).
"""

from __future__ import annotations

PACKET_SIZE = 188
SYNC_BYTE = 0x47
PTS_HZ = 90_000
PTS_WRAP = 1 << 33

# Duration of one frame in PTS ticks, for estimating where a stream ends.
VIDEO_FRAME_TICKS = 3003  # 29.97 fps
AUDIO_FRAME_TICKS = 1920  # 1024 AAC samples at 48 kHz


def count_adts_frames(payload: bytes | bytearray) -> int:
    """Number of AAC frames in a run of ADTS data (at least 1)."""
    frames = 0
    i = 0
    n = len(payload)
    while i + 7 <= n:
        if payload[i] == 0xFF and (payload[i + 1] & 0xF6) == 0xF0:
            length = ((payload[i + 3] & 0x03) << 11) | (payload[i + 4] << 3) | (payload[i + 5] >> 5)
            frames += (payload[i + 6] & 0x03) + 1
            i += length if length >= 7 else 1
        else:
            i += 1
    return max(frames, 1)


def _read_pts(b: bytearray, p: int) -> int:
    return (
        ((b[p] >> 1) & 0x07) << 30
        | b[p + 1] << 22
        | (b[p + 2] >> 1) << 15
        | b[p + 3] << 7
        | b[p + 4] >> 1
    )


class TsStitcher:
    def __init__(self) -> None:
        self._counters: dict[int, int] = {}
        self._partial = b""
        self._reference = 0
        self.segment_start: int | None = None  # earliest PTS in this program
        self.segment_end: int | None = None  # where this program's last frame ends
        # Audio PES packets can carry several AAC frames (the muxer bundles
        # small ones, like silence), so their payload is collected until the
        # next packet starts and the frames counted.
        self._audio_pes: dict[int, tuple[int, bytearray]] = {}
        # A program's packets, held until its picture starts (begin_segment).
        self._held: bytes | None = None

    def begin_segment(self, ts_offset_s: float) -> None:
        """Called before each program; `ts_offset_s` is where it was asked
        to start. Nothing of the program is sent until its first picture:
        one that ends with sound and no picture sends nothing. (FFmpeg 7
        pads the sound of a file that ends just as it starts, which would
        leave a hole in the station's picture.)"""
        self._reference = round(ts_offset_s * PTS_HZ)
        self.segment_start = None
        self.segment_end = None
        self._audio_pes.clear()
        self._held = b""

    @property
    def segment_offset_s(self) -> float:
        """Where the current program was asked to start on the timeline."""
        return self._reference / PTS_HZ

    def end_segment(self) -> None:
        """Called after a program's output is fully fed; settles its end
        time. A program that never showed a picture is dropped."""
        self._held = None
        for pid in list(self._audio_pes):
            self._finish_audio(pid)

    def _unwrap(self, pts: int) -> int:
        # PTS values are 33-bit and wrap about every 26.5 hours; keep them on
        # the same (unbounded) timeline as the offsets we hand to ffmpeg.
        return pts + PTS_WRAP * round((self._reference - pts) / PTS_WRAP)

    def feed(self, data: bytes) -> bytes:
        """Returns whole, fixed-up packets; keeps any trailing partial packet."""
        if self._held is not None:
            # Waiting for the program's picture: hold everything until then,
            # then send it all, in order.
            held = self._held + data
            # (Only the packets not looked at yet.)
            if not _has_picture(held, len(self._held) // PACKET_SIZE * PACKET_SIZE):
                self._held = held
                return b""
            self._held = None
            data = held
        buf = self._partial + data
        # Drop anything before the first sync byte (never expected from
        # ffmpeg, but a stitcher shouldn't wedge on it).
        if buf and buf[0] != SYNC_BYTE:
            idx = buf.find(bytes([SYNC_BYTE]))
            buf = buf[idx:] if idx >= 0 else b""
        usable = len(buf) - (len(buf) % PACKET_SIZE)
        self._partial = buf[usable:]
        if not usable:
            return b""
        out = bytearray(buf[:usable])
        counters = self._counters
        for pos in range(0, usable, PACKET_SIZE):
            if out[pos] != SYNC_BYTE:
                continue
            pid = ((out[pos + 1] & 0x1F) << 8) | out[pos + 2]
            if pid == 0x1FFF:  # null packets carry no counter
                continue
            flags = out[pos + 3]
            has_payload = flags & 0x10
            last = counters.get(pid)
            if has_payload:
                cc = 0 if last is None else (last + 1) & 0x0F
            else:
                # Adaptation-only packets repeat the previous counter.
                cc = 0 if last is None else last
            counters[pid] = cc
            out[pos + 3] = (flags & 0xF0) | cc

            if has_payload:
                if out[pos + 1] & 0x40:  # start of a PES packet
                    self._track_pts(out, pos, pid, flags)
                elif pid in self._audio_pes:
                    self._audio_pes[pid][1].extend(
                        out[self._payload_start(out, pos, flags) : pos + PACKET_SIZE]
                    )
        return bytes(out)

    @staticmethod
    def _payload_start(out: bytearray, pos: int, flags: int) -> int:
        p = pos + 4
        if flags & 0x20:  # skip the adaptation field
            p += 1 + out[p]
        return p

    def _extend_end(self, end: int) -> None:
        if self.segment_end is None or end > self.segment_end:
            self.segment_end = end

    def _finish_audio(self, pid: int) -> None:
        pending = self._audio_pes.pop(pid, None)
        if pending is not None:
            pts, payload = pending
            self._extend_end(pts + AUDIO_FRAME_TICKS * count_adts_frames(payload))

    def _track_pts(self, out: bytearray, pos: int, pid: int, flags: int) -> None:
        if pid in self._audio_pes:
            self._finish_audio(pid)
        p = self._payload_start(out, pos, flags)
        if p + 14 > pos + PACKET_SIZE or out[p : p + 3] != b"\x00\x00\x01":
            return
        stream_id = out[p + 3]
        is_video = 0xE0 <= stream_id <= 0xEF
        is_audio = 0xC0 <= stream_id <= 0xDF
        if not (is_video or is_audio) or not out[p + 7] & 0x80:  # no PTS
            return
        pts = self._unwrap(_read_pts(out, p + 9))
        if self.segment_start is None or pts < self.segment_start:
            self.segment_start = pts
        if is_video:
            self._extend_end(pts + VIDEO_FRAME_TICKS)
        else:
            header_end = p + 9 + out[p + 8]
            self._audio_pes[pid] = (pts, bytearray(out[header_end : pos + PACKET_SIZE]))

    def flush_partial(self) -> None:
        """Drops a trailing partial packet at the end of a program."""
        self._partial = b""


def _has_picture(data: bytes, start: int = 0) -> bool:
    """Whether a video PES packet starts in `data` (TS packets from its
    beginning) at or after `start`, a packet boundary."""
    for pos in range(start, len(data) - PACKET_SIZE + 1, PACKET_SIZE):
        flags = data[pos + 3]
        if data[pos] != SYNC_BYTE or not data[pos + 1] & 0x40 or not flags & 0x10:
            continue
        p = pos + 4 + (1 + data[pos + 4] if flags & 0x20 else 0)
        if (
            p + 4 <= pos + PACKET_SIZE
            and data[p : p + 3] == b"\x00\x00\x01"
            and 0xE0 <= data[p + 3] <= 0xEF
        ):
            return True
    return False
