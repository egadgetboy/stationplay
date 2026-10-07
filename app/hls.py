"""Stations as HLS, for StationPlay's own apps (and AirPlay and Chromecast).

A station's HLS comes from the very stream everyone else watching it gets:
StationPlay watches it as one more viewer, and ffmpeg cuts it into short
pieces as it arrives (copying them, not converting, so it costs almost
nothing). Every safeguard that keeps a station on the air applies as it is.

It runs only while an app is asking for it. Players ask for the playlist
every few seconds; once nothing has asked for IDLE_S, it stops, and so does
the station (after its usual grace) if no one else is watching. An app that
tunes away says so (leave), and if no other app is watching, it stops then,
rather than holding a tuner until it notices. All the apps
watching one station share one HLS stream, so a station takes one tuner
however it's watched.

The pieces are files in a folder of their own under the system's temporary
folder, deleted as they fall out of the playlist and when the stream stops.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .broadcaster import Broadcaster, Viewer

log = logging.getLogger(__name__)

# How long each piece is: one keyframe apart (the stations' encoders put one
# every 2 seconds), so a player starts and changes stations quickly.
PIECE_S = 2
# Pieces in the playlist, and pieces kept a little longer for players that
# are behind (ffmpeg deletes the rest).
LISTED = 6
KEPT_AFTER = 4
# A player is given the playlist once it has this many pieces (players start
# a few pieces back from the newest), waiting at most READY_WAIT_S for them.
READY_PIECES = 3
READY_WAIT_S = 25.0
# How long the stream runs after the last time an app asked for it.
IDLE_S = 30.0
# How often that's checked.
IDLE_CHECK_S = 2.0
PLAYLIST = "index.m3u8"
PIECE = re.compile(r"s\d{1,9}\.ts")
# What every answer to a player carries: Chromecasts fetch HLS the way a web
# page does, so they need to be told any page may.
HEADERS = {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache, no-store"}


def command(ffmpeg: str, folder: Path) -> list[str]:
    """ffmpeg reading the station's stream on its input and writing it as HLS
    in `folder`. (It starts at the first keyframe it sees, and writes each
    file under another name first, so a player never reads half of one.)"""
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
        "-f", "mpegts", "-i", "pipe:0",
        "-map", "0", "-c", "copy",
        "-f", "hls",
        "-hls_time", str(PIECE_S),
        "-hls_list_size", str(LISTED),
        "-hls_delete_threshold", str(KEPT_AFTER),
        "-hls_flags", "delete_segments+omit_endlist+independent_segments+temp_file",
        "-hls_segment_filename", str(folder / "s%d.ts"),
        str(folder / PLAYLIST),
    ]  # fmt: skip


class HlsStream:
    """One station's HLS, for as long as apps are watching it."""

    def __init__(self, streams: HlsStreams, b: Broadcaster, number: int) -> None:
        self.streams = streams
        self.b = b
        self.number = number
        self.folder = Path(tempfile.mkdtemp(prefix=f"stationplay-hls-{number}-"))
        self.last_asked = time.monotonic()
        # Who's been watching (by address), and when each last asked; and
        # which of them are away from home.
        self.clients: dict[str, float] = {}
        self.away: set[str] = set()
        self.ended = False
        self.ended_because = ""
        self._stopping = False
        self._left = False
        self._proc: asyncio.subprocess.Process | None = None
        self._viewer: Viewer = b.subscribe(f"app viewers on {number}")
        self._task = asyncio.create_task(self._run(), name=f"hls-{number}")

    def asked_by(self, client: str | None, away: bool = False) -> None:
        """A player asked for the playlist or a piece."""
        now = time.monotonic()
        self.last_asked = now
        if client is None:
            return
        if client not in self.clients:
            log.info("An app on %s is watching station %d", client, self.number)
        self.clients[client] = now
        if away:
            self.away.add(client)

    def left_by(self, client: str) -> None:
        """An app said it stopped watching: the stream stops now if no other
        app has asked for it lately. (An address that wasn't watching changes
        nothing, so one device can't stop another's.)"""
        self.away.discard(client)
        if self.clients.pop(client, None) is None:
            return
        log.info("An app on %s stopped watching station %d", client, self.number)
        if self.watching() == 0:
            self.stop("the last app watching it tuned away")

    @property
    def over(self) -> bool:
        """Whether it has ended, or is ending."""
        return self.ended or self._stopping

    def watching(self) -> int:
        """How many apps (by address) asked for it in the last IDLE_S."""
        return len(self.watchers())

    def watchers(self) -> dict[str, bool]:
        """The apps that asked for it in the last IDLE_S, and whether each is
        away from home."""
        now = time.monotonic()
        return {c: c in self.away for c, at in self.clients.items() if now - at < IDLE_S}

    async def playlist(self) -> str | None:
        """The playlist, once it has enough pieces for a player to start; None
        if it doesn't in time, or the stream has ended."""
        path = self.folder / PLAYLIST
        deadline = time.monotonic() + READY_WAIT_S
        while not self.ended:
            text = await asyncio.to_thread(_read_text, path)
            if text is not None and text.count("#EXTINF") >= READY_PIECES:
                return text
            if time.monotonic() > deadline:
                return None
            await asyncio.sleep(0.25)
        return None

    async def piece(self, name: str) -> bytes | None:
        """One piece of the stream, if it's still there."""
        if not PIECE.fullmatch(name) or self.ended:
            return None
        return await asyncio.to_thread(_read_bytes, self.folder / name)

    def stop(self, because: str) -> None:
        """Ends the stream: the viewer it watches the station as goes, and so
        does ffmpeg (what it was making is thrown away anyway)."""
        if not self.ended_because:
            self.ended_because = because
        self._stopping = True
        self._leave()
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.kill()

    def _leave(self) -> None:
        """Stops watching the station (once: that's what its viewing
        statistics count)."""
        if not self._left:
            self._left = True
            self.b.unsubscribe(self._viewer)

    async def wait(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.shield(self._task)

    async def _run(self) -> None:
        said: deque[str] = deque(maxlen=5)
        idle = asyncio.create_task(self._stop_when_idle())
        listening: asyncio.Task | None = None
        try:
            self._proc = proc = await asyncio.create_subprocess_exec(
                *command(self.b.ctx.settings.ffmpeg_path, self.folder),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            listening = asyncio.create_task(_collect(proc, said))
            assert proc.stdin is not None
            while True:
                chunk = await self._viewer.next_chunk()
                if chunk is None:
                    self.ended_because = (
                        self.ended_because or self._viewer.ended_because or "the station stopped"
                    )
                    break
                proc.stdin.write(chunk)
                await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            if not self._stopping:
                # ffmpeg stopped by itself: say what it said.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self._proc.wait(), 5)  # type: ignore[union-attr]
                last = " / ".join(said) or "no message"
                self.ended_because = f"ffmpeg stopped making it ({last})"
                log.warning("Station %d's stream for apps stopped: %s", self.number, last)
        except OSError as e:
            self.ended_because = f"ffmpeg couldn't start ({e})"
            log.error("Station %d's stream for apps couldn't start: %s", self.number, e)
        finally:
            self.ended = True
            idle.cancel()
            self._leave()
            await self._end_ffmpeg()
            if listening is not None:
                listening.cancel()
            await asyncio.to_thread(shutil.rmtree, self.folder, True)
            self.streams.forget(self)
            log.info("Stopped station %d's stream for apps: %s", self.number, self.ended_because)

    async def _end_ffmpeg(self) -> None:
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        if proc.stdin is not None:
            with contextlib.suppress(Exception):
                proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()

    async def _stop_when_idle(self) -> None:
        while True:
            await asyncio.sleep(IDLE_CHECK_S)
            if time.monotonic() - self.last_asked > IDLE_S:
                self.stop(f"no app asked for it for {IDLE_S:.0f} seconds")
                return


class HlsStreams:
    """The stations being sent as HLS, by station."""

    def __init__(self) -> None:
        self._by_station: dict[int, HlsStream] = {}

    def get(self, channel_id: int) -> HlsStream | None:
        stream = self._by_station.get(channel_id)
        return None if stream is None or stream.over else stream

    def start(self, b: Broadcaster, number: int) -> HlsStream:
        stream = self._by_station[b.channel_id] = HlsStream(self, b, number)
        log.info("Started station %d's stream for apps", number)
        return stream

    def forget(self, stream: HlsStream) -> None:
        if self._by_station.get(stream.b.channel_id) is stream:
            del self._by_station[stream.b.channel_id]

    def watching(self, channel_id: int) -> int:
        stream = self.get(channel_id)
        return stream.watching() if stream else 0

    def watchers(self) -> dict[str, bool]:
        """Every device watching any station through the apps (see
        HlsStream.watchers), each once."""
        out: dict[str, bool] = {}
        for stream in self._by_station.values():
            if not stream.over:
                out.update(stream.watchers())
        return out

    async def stop_all(self, because: str) -> None:
        streams = list(self._by_station.values())
        for stream in streams:
            stream.stop(because)
        for stream in streams:
            await stream.wait()


async def _collect(proc: asyncio.subprocess.Process, said: deque[str]) -> None:
    """Keeps the last few things ffmpeg said (for when it stops)."""
    assert proc.stderr is not None
    async for line in proc.stderr:
        text = line.decode(errors="replace").strip()
        if text:
            said.append(text[:200])


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None
