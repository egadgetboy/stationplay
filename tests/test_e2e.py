"""End to end: real ffmpeg, a fake Plex, and a channel full of bad files.

Plays about a minute of a channel whose episodes include a truncated file,
a file that won't open and a file with no audio, and checks what a viewer
actually receives.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .helpers import like_plex

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

CLIP_S = 12


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("media")
    ff(
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=640x480:r=24000/1001",
        "-f",
        "lavfi",
        "-i",
        "sine=f=440",
        "-t",
        str(CLIP_S),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-shortest",
        str(d / "good1.mkv"),
    )
    ff(
        "-f",
        "lavfi",
        "-i",
        "smptebars=s=1920x1080:r=25",
        "-t",
        str(CLIP_S),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        str(d / "noaudio.mp4"),
    )
    ff(
        "-f",
        "lavfi",
        "-i",
        "testsrc=s=1280x720:r=30",
        "-f",
        "lavfi",
        "-i",
        "sine=f=660",
        "-t",
        str(CLIP_S),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-shortest",
        str(d / "good2.mp4"),
    )
    ff(
        "-f",
        "lavfi",
        "-i",
        "mandelbrot=s=854x480:r=30",
        "-f",
        "lavfi",
        "-i",
        "sine=f=330",
        "-t",
        str(CLIP_S),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        "-shortest",
        str(d / "good3.mkv"),
    )
    # Same kind of content at very different volumes, for loudness tests.
    # (ffmpeg's test tone starts at -18 dBFS; these land near -42 and -10 LUFS.)
    for name, volume in (("quiet", "-20dB"), ("loud", "12dB"), ("loudmovie", "12dB")):
        ff(
            "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30",
            "-f", "lavfi", "-i", "sine=f=500:sample_rate=48000",
            "-af", f"volume={volume}", "-t", str(CLIP_S),
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
            str(d / f"{name}.mkv"),
        )  # fmt: skip
    # Claims 12s in its header but only the first second or two survives.
    data = (d / "good1.mkv").read_bytes()
    (d / "truncated.mkv").write_bytes(data[: len(data) // 8])
    # An MP4 cut before its index: won't open at all.
    data = (d / "good2.mp4").read_bytes()
    (d / "unopenable.mp4").write_bytes(data[: len(data) // 2])
    return {p.stem: p for p in d.iterdir()}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def start_server(tmp_path, plex: FakePlex, plex_base: str = "http://plex.test", **overrides):
    settings = Settings(
        plex_url=plex_base,
        plex_token="token",
        data_dir=tmp_path / "data",
        video_width=640,
        video_height=360,
        video_bitrate_kbps=800,
        idle_grace_seconds=1,
        # Lets the suite run against a different ffmpeg build.
        ffmpeg_path=os.environ.get("FFMPEG_PATH", "ffmpeg"),
        hw_accel="cpu",
    )
    for key, value in overrides.items():
        setattr(settings, key, value)
    app = create_app(settings, PlexClient(plex_base, "token", transport=plex.transport()))
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    srv = uvicorn.Server(config)
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.05)
    return f"http://127.0.0.1:{port}", app, settings, srv, task


@pytest.fixture
async def server(tmp_path, media):
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    episodes = ["good1", "truncated", "noaudio", "unopenable", "good2", "good3"]
    for n, name in enumerate(episodes, start=1):
        plex.add_episode(str(200 + n), "100", 1, n, name, str(media[name]), CLIP_S * 1000)
    base, app, settings, srv, task = await start_server(tmp_path, plex)
    yield base, app, plex, settings
    srv.should_exit = True
    await task


async def make_channel(base: str, number: int = 7) -> dict:
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        created = await client.post(
            "/api/channels",
            json={
                "number": number,
                "name": "Test TV",
                "orderMode": "rotate",
                "sources": [{"type": "show", "ratingKey": "100"}],
            },
        )
        assert created.status_code == 201, created.text
        return created.json()


def assert_clean_stream(path: Path) -> None:
    # (Decoded on the stream's own timestamps: rounded to the average frame
    # rate ffmpeg guesses from a recording, which joins between programs
    # lower, two frames can land on one tick and look out of order.)
    decode = subprocess.run(
        ["ffmpeg", "-v", "warning", "-i", str(path), "-enc_time_base", "demux", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    assert decode.returncode == 0
    assert decode.stderr.strip() == "", decode.stderr
    for stream in ("v:0", "a:0"):
        times = packet_times(path, stream)
        assert times, f"no {stream} packets"
        for (pts_a, dur_a), (pts_b, _) in itertools.pairwise(times):
            gap = pts_b - (pts_a + dur_a)
            assert gap > -0.001, f"{stream} overlap of {-gap:.3f}s at {pts_a:.3f}"
            assert gap < 0.2, f"{stream} gap of {gap:.3f}s at {pts_a:.3f}"


def media_seconds(path: Path) -> float:
    video = packet_times(path, "v:0")
    return video[-1][0] + video[-1][1] - video[0][0]


async def record(url: str, seconds: float) -> bytes:
    buf = bytearray()
    deadline = time.monotonic() + seconds
    async with httpx.AsyncClient(timeout=30) as client, client.stream("GET", url) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "video/mp2t"
        async for chunk in resp.aiter_bytes():
            buf += chunk
            if time.monotonic() > deadline:
                break
    return bytes(buf)


def packet_times(path: Path, stream: str) -> list[tuple[float, float]]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            stream,
            "-show_entries",
            "packet=pts_time,duration_time",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows = []
    for line in out.splitlines():
        parts = line.strip().rstrip(",").split(",")
        if parts and parts[0] not in ("", "N/A"):
            rows.append(
                (
                    float(parts[0]),
                    float(parts[1]) if len(parts) > 1 and parts[1] not in ("", "N/A") else 0.0,
                )
            )
    return sorted(rows)


async def test_channel_survives_bad_files_and_stays_on_schedule(server, tmp_path):
    base, app, _plex, settings = server
    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        # Plex's side of the handshake
        discover = (await client.get("/discover.json")).json()
        # (Twice StationPlay's 4: see playback.announced.)
        assert discover["TunerCount"] == 8
        assert discover["LineupURL"] == f"{base}/lineup.json"

        created = await client.post(
            "/api/channels",
            json={
                "number": 7,
                "name": "Test TV",
                "orderMode": "rotate",
                "sources": [{"type": "show", "ratingKey": "100"}],
            },
        )
        assert created.status_code == 201, created.text
        channel = created.json()
        assert channel["itemCount"] == 6
        lineup = (await client.get("/lineup.json")).json()
        assert lineup == [
            {"GuideNumber": "7", "GuideName": "Test TV", "URL": f"{base}/stream/7", "HD": 1}
        ]

    started = time.time()
    wall_s = 4.5 * CLIP_S  # through all the bad episodes
    data = await record(f"{base}/stream/7", wall_s)
    elapsed = time.time() - started
    out = tmp_path / "channel.ts"
    out.write_bytes(data)

    # 1. The bad files were caught and logged with reasons.
    broken = json.loads((settings.data_dir / "broken-files.json").read_text())
    by_title = {f["title"]: f for f in broken["files"]}
    assert set(by_title) == {"truncated", "unopenable"}, by_title
    assert by_title["truncated"]["reason"].startswith("the file ended at "), by_title["truncated"]
    assert "can't open the file" in by_title["unopenable"]["reason"]
    assert by_title["truncated"]["stations"] == [7]
    assert by_title["truncated"]["file"].endswith("truncated.mkv")

    # 2. The viewer got one clean stream: it decodes without a single
    #    warning, and timestamps never overlap or jump across any program
    #    change, including where a replacement took over mid-slot.
    assert_clean_stream(out)

    # 3. The stream kept pace with the clock: no stalls while bad files were
    #    replaced, and never more than the intended cushion ahead.
    media_s = media_seconds(out)
    assert elapsed - 3 <= media_s <= elapsed + 20, (media_s, elapsed)

    # 4. The guide stays right: what is on now is what the schedule says.
    engine = app.state.ctx.broadcasters.get(channel["id"])
    assert engine is not None and engine.now_playing is not None
    guide_now = (
        await httpx.AsyncClient(base_url=base).get(f"/api/channels/{channel['id']}/guide?hours=1")
    ).json()[0]
    assert engine.now_playing.slot_start_ms <= guide_now["end"]


class StallingServer:
    """Serves a file over HTTP, then stops sending partway, like a hung NAS."""

    def __init__(
        self, path: Path, stall_after_fraction: float, stall_on: set[int] | None = None
    ) -> None:
        self.data = path.read_bytes()
        self.cutoff = int(len(self.data) * stall_after_fraction)
        # Which requests (1, 2, ...) stall; all of them if None.
        self.stall_on = stall_on
        self.requests = 0
        self.port = free_port()
        self._server: asyncio.base_events.Server | None = None

    async def __aenter__(self):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", self.port)
        return self

    async def __aexit__(self, *exc):
        assert self._server is not None
        self._server.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while (await reader.readline()) not in (b"\r\n", b""):
                pass
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: video/x-matroska\r\n"
                + f"Content-Length: {len(self.data)}\r\n\r\n".encode()
            )
            self.requests += 1
            if self.stall_on is not None and self.requests not in self.stall_on:
                writer.write(self.data)
                await writer.drain()
                return
            writer.write(self.data[: self.cutoff])
            await writer.drain()
            await asyncio.sleep(3600)  # never sends the rest
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()


async def test_stalled_file_is_replaced_without_dropping_the_stream(tmp_path, media, monkeypatch):
    from app import broadcaster

    monkeypatch.setattr(broadcaster, "STALL_TIMEOUT_S", 4.0)
    async with StallingServer(media["good1"], 0.4) as stalling:
        plex = FakePlex()
        plex.add_show("100", "Test Show")
        # Not on local disk, so it's streamed from "Plex" (the stalling server).
        plex.add_episode("201", "100", 1, 1, "stalls", "/not/local/stalls.mkv", CLIP_S * 1000)
        plex.add_episode("202", "100", 1, 2, "good2", str(media["good2"]), CLIP_S * 1000)
        plex.add_episode("203", "100", 1, 3, "good3", str(media["good3"]), CLIP_S * 1000)
        base, _app, settings, srv, task = await start_server(
            tmp_path, plex, plex_base=f"http://127.0.0.1:{stalling.port}"
        )
        try:
            await make_channel(base)
            started = time.time()
            data = await record(f"{base}/stream/7", 2.2 * CLIP_S)
            elapsed = time.time() - started
        finally:
            srv.should_exit = True
            await task

    out = tmp_path / "stall.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    # A single stall is treated as the share's fault, not the file's.
    broken_path = settings.data_dir / "broken-files.json"
    assert not broken_path.exists() or json.loads(broken_path.read_text())["files"] == []
    # The stream never paused for long: the stall was covered by the cushion
    # and a replacement took over.
    assert media_seconds(out) >= elapsed - 3


async def test_channel_of_only_bad_files_keeps_streaming_a_card(tmp_path, media, caplog):
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    plex.add_episode("201", "100", 1, 1, "bad1", str(media["unopenable"]), CLIP_S * 1000)
    plex.add_episode("202", "100", 1, 2, "bad2", "/does/not/exist.mkv", CLIP_S * 1000)
    base, app, settings, srv, task = await start_server(tmp_path, plex)
    try:
        await make_channel(base)
        started = time.time()
        data = await record(f"{base}/stream/7", 2.5 * CLIP_S)
        elapsed = time.time() - started
        off_air = any(b.off_air for b in app.state.ctx.broadcasters.values())
    finally:
        srv.should_exit = True
        await task
    # Two slots running with nothing playable: the station says it's off
    # the air, and that's logged as an error for you to look into.
    assert off_air
    assert any(r.levelname == "ERROR" and "OFF THE AIR" in r.getMessage() for r in caplog.records)
    out = tmp_path / "cards.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert media_seconds(out) >= elapsed - 3
    titles = {
        f["title"]
        for f in json.loads((settings.data_dir / "broken-files.json").read_text())["files"]
    }
    assert titles == {"bad1", "bad2"}


async def test_two_viewers_share_a_channel_and_it_restarts_on_schedule(server, tmp_path):
    base, app, _plex, settings = server
    channel = await make_channel(base)
    first, second = await asyncio.gather(
        record(f"{base}/stream/7", 8), record(f"{base}/stream/7", 8)
    )
    assert len(first) > 100_000 and len(second) > 100_000
    engine = app.state.ctx.broadcasters[channel["id"]]
    await asyncio.sleep(settings.idle_grace_seconds + 1.5)
    assert not engine.running  # stopped once nobody was watching

    # Tuning back in picks up wherever the schedule is now.
    again = await record(f"{base}/stream/7", 4)
    assert len(again) > 50_000
    async with httpx.AsyncClient(base_url=base) as client:
        guide = (await client.get(f"/api/channels/{channel['id']}/guide?hours=1")).json()
    # The engine runs a few seconds ahead of the clock, so it may already be
    # on the next slot; either way it is playing a slot the guide shows now.
    assert engine.now_playing.slot_start_ms in {g["start"] for g in guide[:2]}


@pytest.mark.skipif(
    not __import__("os").environ.get("STATIONPLAY_SOAK"),
    reason="set STATIONPLAY_SOAK=1 for the long run",
)
async def test_soak_many_program_changes(tmp_path, media):
    """Minutes of short, mixed-format programs, with bad ones sprinkled in."""
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    names = [
        "good1",
        "noaudio",
        "good2",
        "truncated",
        "good3",
        "good1",
        "unopenable",
        "good2",
        "noaudio",
        "good3",
    ]
    for n, name in enumerate(names, start=1):
        # 6-second slots from 12-second files: every join is mid-file too.
        plex.add_episode(str(200 + n), "100", 1, n, f"{name}-{n}", str(media[name]), 6_000)
    base, _app, _settings, srv, task = await start_server(tmp_path, plex)
    minutes = float(__import__("os").environ.get("STATIONPLAY_SOAK_MINUTES", "8"))
    try:
        await make_channel(base)
        started = time.time()
        data = await record(f"{base}/stream/7", minutes * 60)
        elapsed = time.time() - started
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "soak.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert elapsed - 3 <= media_seconds(out) <= elapsed + 20


async def test_file_shorter_than_plex_says_is_not_broken(tmp_path, media):
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    # Plex thinks these run 14.5s; the files are 12s. Honest, just short.
    plex.add_episode("201", "100", 1, 1, "short1", str(media["good1"]), 14_500)
    plex.add_episode("202", "100", 1, 2, "short2", str(media["good2"]), 14_500)
    base, app, settings, srv, task = await start_server(tmp_path, plex)
    try:
        channel = await make_channel(base)
        started = time.time()
        data = await record(f"{base}/stream/7", 32)
        elapsed = time.time() - started
        engine = app.state.ctx.broadcasters[channel["id"]]
        playing_slot = engine.now_playing.slot_start_ms
        async with httpx.AsyncClient(base_url=base) as client:
            guide = (await client.get(f"/api/channels/{channel['id']}/guide?hours=1")).json()
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "short.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert not (settings.data_dir / "broken-files.json").exists()
    assert media_seconds(out) >= elapsed - 3
    assert playing_slot in {g["start"] for g in guide[:2]}


async def test_check_files_finds_truncated_and_unopenable(tmp_path, media):
    from app import jobs

    plex = FakePlex()
    plex.add_show("100", "Test Show")
    for n, name in enumerate(["good1", "truncated", "unopenable", "noaudio"], start=1):
        plex.add_episode(str(200 + n), "100", 1, n, name, str(media[name]), CLIP_S * 1000)
    base, app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        channel = await make_channel(base)
        ctx = app.state.ctx
        status = jobs.start_check(ctx, channel["id"])
        await status._task
        assert (status.total, status.done, status.newly_broken) == (4, 4, 2)
        broken = {e["title"]: e["reason"] for e in ctx.broken.entries()}
        assert set(broken) == {"truncated", "unopenable"}
        assert "cut short" in broken["truncated"]

        # Plex picks up a replacement file for the truncated episode...
        plex.episodes["202"]["Media"][0]["Part"][0]["file"] = str(media["good2"])
        plex.episodes["202"]["Media"][0]["Part"][0]["size"] = 999
        status = await jobs.look_again(ctx, jobs.ListCheck(running=True), everything=False)
        assert status.cleared == 1
        # ...and it's back in rotation; the unchanged one stays listed.
        assert {e["title"] for e in ctx.broken.entries()} == {"unopenable"}
    finally:
        srv.should_exit = True
        await task


class LikePlex:
    """FakePlex answering as Plex does for what it doesn't have (see
    helpers.like_plex), for start_server."""

    def __init__(self, plex: FakePlex) -> None:
        self.plex = plex

    def transport(self) -> httpx.MockTransport:
        return like_plex(self.plex)


async def test_the_broken_files_list_clears_itself(tmp_path, media):
    """A program Plex added again under a new key isn't broken; one it
    removed is, while a station has it; and the list is gone through again
    (every half hour for what's changed in Plex, and everything at night or
    when asked)."""
    from dataclasses import replace

    from app import jobs
    from app.broken import CHECK, DEEP_SCAN, OPENING
    from app.scanner import quick_check_item
    from app.sources import REMOVED

    plex = FakePlex()
    plex.add_show("100", "Bonanza", year=1959)
    tv = tmp_path / "tv"
    tv.mkdir()
    files = {}
    for n, name in enumerate(["good1", "good2", "good3", "good1", "good2", "good3", "good1"], 1):
        files[n] = tv / f"Bonanza - S10E{n:02d} [DVD]-nodlabs.mkv"
        shutil.copy(media[name], files[n])
        plex.add_episode(
            f"20{n}", "100", 10, n, f"Ep {n}", str(files[n]), CLIP_S * 1000, size=1000 + n
        )
    base, app, _settings, srv, task = await start_server(tmp_path, LikePlex(plex))
    try:
        channel = await make_channel(base, 55)
        ctx = app.state.ctx
        items = {i.rating_key: i for i in ctx.db.all_programs(channel["id"])}

        # S10E01's file renamed (only its capital letters): Plex adds it
        # again under a new key. S10E02 is removed from Plex.
        renamed = files[1].with_name(files[1].name.replace("nodlabs", "NODLABS"))
        files[1].rename(renamed)
        plex.remove("201")
        plex.add_episode("211", "100", 10, 1, "Ep 1", str(renamed), CLIP_S * 1000, size=1001)
        files[2].unlink()
        plex.remove("202")
        # Checked before the station's next update from Plex: S10E01 isn't
        # broken (it's checked, and plays, from its renamed file until
        # then); S10E02 is.
        assert (await ctx.resolve_source(items["201"])).source == str(renamed)
        verdict, _ = await quick_check_item(ctx, items["201"], 55)
        assert verdict.result == "ok"
        verdict, _ = await quick_check_item(ctx, items["202"], 55)
        assert verdict.result == "broken"
        assert {e["ratingKey"]: e["reason"] for e in ctx.broken.entries()} == {
            "202": f"Check: {REMOVED}"
        }

        # What older versions listed, and what's found otherwise:
        old = "Check: no longer in Plex (removed, or added again under a new key)"
        ctx.broken.record(items["201"], old, 55, str(files[1]))  # added again
        # The quick check found S10E03 missing (a share down); it's back.
        ctx.broken.record(items["203"], "Check: file not found", 55, str(files[3]), 1003,
                          found=CHECK)  # fmt: skip
        # The deep scan found S10E04 damaged: the same file.
        ctx.broken.record(items["204"], "Deep scan: errors in 3 minutes", 55, str(files[4]),
                          1004, problem="damaged", found=DEEP_SCAN)  # fmt: skip
        # S10E05 has a new file in Plex, cut short; S10E06 a new, good one.
        ctx.broken.record(items["205"], "Check: no sound", 55, "/old/5.mkv", 5,
                          problem="damaged", found=CHECK)  # fmt: skip
        ctx.broken.record(items["206"], "file ended early at 0:05 of 0:12", 55, "/old/6.mkv", 6)
        for key, name in (("205", "truncated"), ("206", "good2")):
            part = plex.episodes[key]["Media"][0]["Part"][0]
            part["file"], part["size"] = str(media[name]), 9_999
        # S10E07 couldn't be opened when it was to play; it can now.
        ctx.broken.record(items["207"], "cannot open file", 55, str(files[7]), 1007, found=OPENING)
        # Gone from Plex, and no station has it.
        gone = replace(items["207"], rating_key="299", episode=99, title="Gone")
        ctx.broken.record(gone, old, 55, "/tv/gone.mkv")

        # Every half hour: what's changed in Plex.
        status = await jobs.look_again(ctx, jobs.ListCheck(running=True), everything=False)
        left = {e["ratingKey"]: e for e in ctx.broken.entries()}
        assert set(left) == {"202", "203", "204", "205", "207"}, set(left)
        assert status.cleared == 3  # 201 (added again), 206 (a good new file), 299
        assert left["202"]["reason"] == f"Check: {REMOVED}"
        assert left["205"]["file"] == str(media["truncated"]) and left["205"]["foundBy"] == CHECK
        assert "cut short" in left["205"]["reason"] and left["205"]["lastChecked"]
        assert [k for k, e in left.items() if "lastChecked" in e] == ["205"]

        # Every night, or when asked: everything that can be looked at again.
        status = await jobs.look_again(ctx, jobs.ListCheck(running=True), everything=True)
        left = {e["ratingKey"]: e for e in ctx.broken.entries()}
        assert set(left) == {"202", "204", "205"}, set(left)  # 203 and 207 pass now
        assert (status.total, status.done, status.cleared) == (5, 5, 2)
        assert left["202"]["lastChecked"] and left["205"]["lastChecked"]
        assert "lastChecked" not in left["204"]  # (the same file: not checked again)

        # Plex away: nothing changes, and it says so.
        plex.down = True
        status = await jobs.look_again(ctx, jobs.ListCheck(running=True), everything=True)
        assert status.plex_away and set(e["ratingKey"] for e in ctx.broken.entries()) == set(left)
        plex.down = False

        # From the Broken files tab.
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            started = (await client.post("/api/broken/check")).json()
            assert started["running"]
            again = (await client.post("/api/broken/check")).json()  # (one at a time)
            assert again["startedAt"] == started["startedAt"]
            await ctx.list_check._task
            shown = (await client.get("/api/scan")).json()["list"]
        assert not shown["running"] and shown["total"] == 3 and shown["finishedAt"]
        assert jobs.ListCheck.last(ctx.db).total == 3  # (kept for after a restart)
    finally:
        srv.should_exit = True
        await task


async def test_a_new_stations_files_are_checked_straight_away(tmp_path, media, monkeypatch):
    from app import jobs

    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", True)  # (as outside the tests)
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    for n, name in enumerate(["good1", "truncated", "unopenable", "noaudio"], start=1):
        plex.add_episode(str(200 + n), "100", 1, n, name, str(media[name]), CLIP_S * 1000)
    base, app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        channel = await make_channel(base)
        assert channel["check"]["running"]  # the station's card shows it under way
        status = app.state.ctx.checks[channel["id"]]
        await status._task
        assert (status.total, status.done, status.newly_broken) == (4, 4, 2)
    finally:
        srv.should_exit = True
        await task


FAKE_GPU = str(Path(__file__).with_name("fake_gpu_ffmpeg.py"))


async def start_gpu_server(tmp_path, plex: FakePlex, monkeypatch, **fake_env):
    """A server whose "GPU" is the stand-in ffmpeg, set to misbehave as told."""
    device = tmp_path / "renderD128"
    device.write_bytes(b"")
    gpu_log = tmp_path / "gpu.log"
    monkeypatch.setenv("REAL_FFMPEG", os.environ.get("FFMPEG_PATH", "ffmpeg"))
    monkeypatch.setenv("FAKE_GPU_LOG", str(gpu_log))
    for key, value in fake_env.items():
        monkeypatch.setenv(key, value)
    server = await start_server(
        tmp_path, plex, ffmpeg_path=FAKE_GPU, hw_accel="intel", hw_device=str(device)
    )
    await server[1].state.ctx.gpu.wait_ready()
    return (*server, gpu_log)


def gpu_runs(gpu_log: Path) -> list[tuple[str, str, float]]:
    if not gpu_log.exists():
        return []
    runs = []
    for line in gpu_log.read_text().splitlines():
        kind, rest = line.split(" ", 1)
        source, seek = rest.rsplit(" ", 1)
        runs.append((kind, Path(source).stem, float(seek)))
    return runs


def three_episode_show(media, slot_ms: int = CLIP_S * 1000) -> FakePlex:
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    for n, name in enumerate(["good1", "good2", "good3"], start=1):
        plex.add_episode(str(200 + n), "100", 1, n, name, str(media[name]), slot_ms)
    return plex


async def test_gpu_failure_mid_program_continues_same_program_on_cpu(tmp_path, media, monkeypatch):
    plex = three_episode_show(media)
    base, app, settings, srv, task, gpu_log = await start_gpu_server(
        # Late enough that the episode is well under way (the loudness filter
        # holds back the first ~3 seconds of each episode while it measures).
        tmp_path,
        plex,
        monkeypatch,
        FAKE_GPU_FAIL_MATCH="good2",
        FAKE_GPU_FAIL_AFTER_S="6",
    )
    try:
        gpu = app.state.ctx.gpu
        assert gpu.state == "gpu", gpu.as_dict()
        await make_channel(base)
        started = time.time()
        data = await record(f"{base}/stream/7", 2.6 * CLIP_S)
        elapsed = time.time() - started
        async with httpx.AsyncClient(base_url=base) as client:
            status = (await client.get("/api/status")).json()
    finally:
        srv.should_exit = True
        await task

    out = tmp_path / "gpu-fail.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert media_seconds(out) >= elapsed - 3

    runs = gpu_runs(gpu_log)
    good2 = [r for r in runs if r[1] == "good2"]
    assert good2[0][0] == "gpu"
    # The same episode resumed on the CPU, part-way in, not from the start.
    assert good2[1][0] == "cpu" and good2[1][2] > 1.0, runs
    # The GPU stays in use for everything else.
    assert [r[0] for r in runs if r[1] == "good3"][:1] == ["gpu"], runs
    # The file isn't blamed for the GPU's failure.
    assert not (settings.data_dir / "broken-files.json").exists()
    encoding = status["encoding"]
    assert encoding["state"] == "gpu" and encoding["gpuFailures"] >= 1


async def test_repeated_gpu_failures_switch_everything_to_cpu(tmp_path, media, monkeypatch):
    plex = three_episode_show(media, slot_ms=6_000)
    base, app, settings, srv, task, gpu_log = await start_gpu_server(
        tmp_path, plex, monkeypatch, FAKE_GPU_FAIL_MATCH="good", FAKE_GPU_FAIL_AFTER_S="1.5"
    )
    try:
        await make_channel(base)
        started = time.time()
        data = await record(f"{base}/stream/7", 36)
        elapsed = time.time() - started
        gpu = app.state.ctx.gpu
    finally:
        srv.should_exit = True
        await task

    out = tmp_path / "gpu-off.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert media_seconds(out) >= elapsed - 3
    assert gpu.state == "disabled" and gpu.active.kind == "cpu", gpu.as_dict()
    assert "was turned off after" in gpu.note
    runs = gpu_runs(gpu_log)
    last_gpu = max(i for i, r in enumerate(runs) if r[0] == "gpu")
    assert len(runs) > last_gpu + 2  # kept playing on the CPU afterwards
    assert not (settings.data_dir / "broken-files.json").exists()


async def test_gpu_that_fails_its_startup_test_is_never_used(tmp_path, media, monkeypatch):
    plex = three_episode_show(media)
    base, app, _settings, srv, task, gpu_log = await start_gpu_server(
        tmp_path, plex, monkeypatch, FAKE_GPU_BROKEN="1"
    )
    try:
        gpu = app.state.ctx.gpu
        assert gpu.state == "cpu"
        assert "failed its encoding test" in gpu.note and "VAAPI" in gpu.note
        await make_channel(base)
        data = await record(f"{base}/stream/7", 10)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "gpu-broken.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    programs = [r for r in gpu_runs(gpu_log) if r[1] != "gpu-test"]
    assert programs and all(kind == "cpu" for kind, _, _ in programs), programs


def short_term_loudness(path: Path) -> list[tuple[float, float]]:
    """(time, short-term loudness in LUFS) through a recording."""
    out = subprocess.run(
        [
            "ffmpeg",
            "-nostats",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-af",
            "ebur128",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    ).stderr
    points = []
    for line in out.splitlines():
        if line.lstrip().startswith("[Parsed_ebur128") and " t: " in line and " S: " in line:
            t = float(line.split(" t: ")[1].split()[0])
            s = line.split(" S: ")[1].split()[0]
            if s not in ("-inf", "nan"):
                points.append((t, float(s)))
    return points


async def test_episodes_play_at_one_loudness_and_movies_keep_theirs(tmp_path, media):
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    plex.add_episode("201", "100", 1, 1, "quiet", str(media["quiet"]), CLIP_S * 1000)
    plex.add_episode("202", "100", 1, 2, "loud", str(media["loud"]), CLIP_S * 1000)
    plex.add_movie("300", "Loud Movie", str(media["loudmovie"]), CLIP_S * 1000, year=1999)
    base, _app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            created = await client.post(
                "/api/channels",
                json={
                    "number": 7,
                    "orderMode": "rotate",
                    "sources": [
                        {"type": "show", "ratingKey": "100"},
                        {"type": "movie", "ratingKey": "300"},
                    ],
                },
            )
            assert created.status_code == 201, created.text
            assert created.json()["name"] == "Station 7"
            order = [
                g["title"]
                for g in (await client.get(f"/api/channels/{created.json()['id']}/guide")).json()[
                    :3
                ]
            ]
        data = await record(f"{base}/stream/7", 3.2 * CLIP_S)
    finally:
        srv.should_exit = True
        await task

    out = tmp_path / "loudness.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    points = short_term_loudness(out)

    def level_during(program: int) -> float:
        # Middle of each 12-second program, once the 3-second window has
        # filled with just that program.
        start, end = program * CLIP_S + 5, program * CLIP_S + 11
        values = [v for t, v in points if start <= t <= end]
        assert values, (program, points[:5])
        return sum(values) / len(values)

    levels = {title: level_during(n) for n, title in enumerate(order)}
    # The sources differ by 32 dB; the episodes come out within a couple of
    # dB of each other, at the -24 LUFS broadcast level.
    assert abs(levels["quiet"] - levels["loud"]) < 2.5, levels
    assert all(abs(levels[t] + 24) < 2.5 for t in ("quiet", "loud")), levels
    # The movie is left as it was: much louder than the target.
    assert levels["Loud Movie"] > -15, levels


async def test_slow_to_open_file_is_covered_without_gaps(tmp_path, media, monkeypatch):
    """A file that takes 12 seconds to open (a sleeping drive): the stream is
    kept going with filler, and the program then plays where it should."""
    plex = three_episode_show(media)
    base, app, settings, srv, task = await start_server(tmp_path, plex)
    ctx = app.state.ctx
    original = ctx.resolve_source
    delayed: set[str] = set()

    async def slow_resolve(item):
        if item.title == "good2" and item.rating_key not in delayed:
            delayed.add(item.rating_key)
            await asyncio.sleep(12)
        return await original(item)

    monkeypatch.setattr(ctx, "resolve_source", slow_resolve)
    try:
        await make_channel(base)
        started = time.time()
        data = await record(f"{base}/stream/7", 3 * CLIP_S)
        elapsed = time.time() - started
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "slow.ts"
    out.write_bytes(data)
    assert delayed, "the slow path wasn't exercised"
    assert_clean_stream(out)
    assert media_seconds(out) >= elapsed - 3
    assert not (settings.data_dir / "broken-files.json").exists()


def frame_stats(path: Path, crop: str) -> list[tuple[float, float, float]]:
    """(time, average brightness, average blue-difference) of one area of
    every frame."""
    out = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path), "-vf",
            f"crop={crop},signalstats,metadata=print:file=-", "-f", "null", "-",
        ],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    frames: list[tuple[float, float, float]] = []
    t = y = 0.0
    for line in out.splitlines():
        if line.startswith("frame:"):
            t = float(line.split("pts_time:")[1])
        elif "signalstats.YAVG=" in line:
            y = float(line.split("=")[1])
        elif "signalstats.UAVG=" in line:
            frames.append((t, y, float(line.split("=")[1])))
    return frames


async def test_picture_setting_applies_from_the_next_program(tmp_path):
    """Changing a station from black bars to zoom while it's being watched:
    the program on screen keeps its bars, the next one is zoomed, the
    stream never breaks and the schedule doesn't change. A station nobody
    is watching uses the new setting from the moment it's tuned."""
    long_s = 30
    d = tmp_path / "media"
    d.mkdir()
    for name, colour in (("white", "white"), ("yellow", "yellow"), ("white2", "white")):
        ff(
            "-f", "lavfi", "-i", f"color=c={colour}:s=640x480:r=30",
            "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", str(long_s),
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
            str(d / f"{name}.mkv"),
        )  # fmt: skip
    plex = FakePlex()
    plex.add_show("100", "Old Show")
    for n, name in enumerate(("white", "yellow", "white2"), start=1):
        plex.add_episode(str(200 + n), "100", 1, n, name, str(d / f"{name}.mkv"), long_s * 1000)
    base, _app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        body = {
            "number": 4,
            "name": "Rerun TV",
            "orderMode": "rotate",
            "aspectMode": "fit",
            "sources": [{"type": "show", "ratingKey": "100"}],
        }
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            station = (await client.post("/api/channels", json=body)).json()

            async def change_mid_program() -> float:
                await asyncio.sleep(3)
                changed = await client.put(
                    f"/api/channels/{station['id']}", json={**body, "aspectMode": "zoom"}
                )
                assert changed.status_code == 200, changed.text
                assert changed.json()["builtAt"] == station["builtAt"]  # not rebuilt
                return time.monotonic()

            started = time.monotonic()
            changer = asyncio.create_task(change_mid_program())
            data = await record(f"{base}/stream/4", 40)
            changed_at = await changer - started
        watched = tmp_path / "watched.ts"
        watched.write_bytes(data)
        assert_clean_stream(watched)

        # Left edge (where black bars would be) and centre of each frame.
        edge = frame_stats(watched, "16:120:8:120")
        centre = frame_stats(watched, "64:64:288:148")
        t0 = edge[0][0]
        timeline = []
        for (t, edge_y, _), (_, _, centre_u) in zip(edge, centre, strict=True):
            episode = "yellow" if centre_u < 60 else "white"
            timeline.append((t - t0, episode, "bars" if edge_y < 30 else "full"))
        first_ep = [f for f in timeline if f[1] == "white"]
        second_ep = [f for f in timeline if f[1] == "yellow"]
        assert first_ep and second_ep
        switch = second_ep[0][0]
        print(
            f"\nsetting changed {changed_at:.1f}s into watching; the next program "
            f"started {switch:.1f}s into the stream"
        )
        print(f"first program:  {len(first_ep)} frames, { ({f[2] for f in first_ep}) }")
        print(f"second program: {len(second_ep)} frames, { ({f[2] for f in second_ep}) }")
        # The program that was on keeps black bars to the end; the next is zoomed.
        assert {f[2] for f in first_ep} == {"bars"}
        assert {f[2] for f in second_ep} == {"full"}
        assert changed_at < switch

        # Nobody watching now. Switch back to black bars, then tune in: the
        # new setting is there from the first frame.
        await asyncio.sleep(3)
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            back = await client.put(f"/api/channels/{station['id']}", json=body)
            assert back.json()["builtAt"] == station["builtAt"]
        retuned = tmp_path / "retuned.ts"
        retuned.write_bytes(await record(f"{base}/stream/4", 4))
        states = {"bars" if y < 30 else "full" for _, y, _ in frame_stats(retuned, "16:120:8:120")}
        print(f"idle station changed back, then tuned: {states}")
        assert states == {"bars"}
    finally:
        srv.should_exit = True
        await task


async def test_zoom_fills_every_kind_of_4x3_file(tmp_path):
    """4:3 shows come stored several ways. On a station set to zoom, every
    one fills the screen, including a 4:3 picture stored as 16:9 video
    with the black bars baked in. A widescreen program with dark edges is
    left alone."""
    clip_s = 7
    d = tmp_path / "media"
    d.mkdir()
    kinds = {
        # name: (colour, frame, extra filters)
        "baked-in bars": ("white", "1440x1080", "pad=1920:1080:240:0:black"),
        "bars all round": ("yellow", "960x720", "pad=1920:1080:480:180:black"),
        "dvd": ("cyan", "720x480", "setsar=8/9"),
        "plain 4:3": ("magenta", "640x480", "null"),
        "widescreen": ("lime", "1728x1080", "pad=1920:1080:96:0:black"),
    }
    plex = FakePlex()
    plex.add_show("100", "Mixed")
    for n, (name, (colour, size, vf)) in enumerate(kinds.items(), start=1):
        path = d / f"{n}.mkv"
        ff(
            "-f", "lavfi", "-i", f"color=c={colour}:s={size}:r=30",
            "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", str(clip_s),
            "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            "-shortest", str(path),
        )  # fmt: skip
        plex.add_episode(str(200 + n), "100", 1, n, name, str(path), clip_s * 1000)
    base, _app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            created = await client.post(
                "/api/channels",
                json={
                    "number": 5,
                    "orderMode": "rotate",
                    "aspectMode": "zoom",
                    "sources": [{"type": "show", "ratingKey": "100"}],
                },
            )
            assert created.status_code == 201, created.text
        out = tmp_path / "zoom.ts"
        out.write_bytes(await record(f"{base}/stream/5", len(kinds) * clip_s + 3))
    finally:
        srv.should_exit = True
        await task
    assert_clean_stream(out)

    colours = {
        "baked-in bars": (128, 128),
        "bars all round": (16, 146),
        "dvd": (166, 16),
        "plain 4:3": (202, 222),
        "widescreen": (54, 34),
    }
    edge = frame_stats(out, "16:120:8:120")
    seen: dict[str, set[str]] = {}
    order: list[str] = []
    for (t, edge_y, _), (_, y, u, v) in zip(edge, _frame_yuv(out), strict=True):
        if y < 40:
            continue  # black filler while a file opens
        kind = min(colours, key=lambda k: (colours[k][0] - u) ** 2 + (colours[k][1] - v) ** 2)
        seen.setdefault(kind, set()).add("bars" if edge_y < 30 else "full")
        if not order or order[-1] != kind:
            order.append(kind)
            print(f"{t:6.2f}s {kind}")
    print("\n" + "\n".join(f"{k}: {sorted(v)}" for k, v in seen.items()))
    for kind in ("baked-in bars", "bars all round", "dvd", "plain 4:3"):
        assert seen.get(kind) == {"full"}, (kind, seen)
    assert seen.get("widescreen") == {"bars"}, seen


def _frame_yuv(path: Path) -> list[tuple[float, float, float, float]]:
    """(time, average Y, U and V) of the centre of every frame."""
    out = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path), "-vf",
            "crop=64:64:288:148,signalstats,metadata=print:file=-", "-f", "null", "-",
        ],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    frames: list[tuple[float, float, float, float]] = []
    t = y = u = 0.0
    for line in out.splitlines():
        if line.startswith("frame:"):
            t = float(line.split("pts_time:")[1])
        elif "signalstats.YAVG=" in line:
            y = float(line.split("=")[1])
        elif "signalstats.UAVG=" in line:
            u = float(line.split("=")[1])
        elif "signalstats.VAVG=" in line:
            frames.append((t, y, u, float(line.split("=")[1])))
    return frames


async def test_an_update_takes_over_seamlessly_while_watching(tmp_path, monkeypatch):
    """New episodes join a station someone is watching: the stream never
    breaks, and the new episode airs when the guide says it will."""
    from app import main, updates

    monkeypatch.setattr(updates, "MARGIN_MS", 8000)
    monkeypatch.setattr(main, "MARGIN_MS", 8000)
    clip_s = 6
    d = tmp_path / "media"
    d.mkdir()
    colours = ["white", "yellow", "cyan", "magenta"]
    for n, colour in enumerate(colours, start=1):
        ff(
            "-f", "lavfi", "-i", f"color=c={colour}:s=640x360:r=30",
            "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", str(clip_s),
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
            str(d / f"{n}.mkv"),
        )  # fmt: skip
    plex = FakePlex()
    plex.add_show("100", "Colours")
    for n in (1, 2, 3):
        plex.add_episode(f"20{n}", "100", 1, n, colours[n - 1], str(d / f"{n}.mkv"), clip_s * 1000)
    base, _app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            station = (
                await client.post(
                    "/api/channels",
                    json={"number": 8, "sources": [{"type": "show", "ratingKey": "100"}]},
                )
            ).json()

            async def add_an_episode() -> dict:
                await asyncio.sleep(2)
                plex.add_episode("204", "100", 1, 4, "magenta", str(d / "4.mkv"), clip_s * 1000)
                return (await client.post(f"/api/channels/{station['id']}/update")).json()

            updating = asyncio.create_task(add_an_episode())
            data = await record(f"{base}/stream/8", 36)
            updated = await updating
            guide = (await client.get(f"/api/channels/{station['id']}/guide?hours=1")).json()
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "update.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert updated["lastChange"]["added"] == 1
    starts = updated["lastChange"]["startsAt"]
    uv = {"white": (128, 128), "yellow": (16, 146), "cyan": (166, 16), "magenta": (202, 222)}
    shown = []
    for _t, y, u, v in _frame_yuv(out):
        if y < 40:
            continue
        colour = min(uv, key=lambda c: (uv[c][0] - u) ** 2 + (uv[c][1] - v) ** 2)
        if not shown or shown[-1] != colour:
            shown.append(colour)
    print("\naired:", " → ".join(shown))
    assert "magenta" in shown  # the new episode aired while watching
    first_new = (
        next(g for g in guide if g["title"] == "magenta")
        if any(g["title"] == "magenta" for g in guide)
        else None
    )
    assert first_new is None or first_new["start"] >= starts


async def test_a_hiccup_mid_program_resumes_the_same_program(tmp_path, media, monkeypatch, caplog):
    """The share hangs once partway through an episode: StationPlay picks
    the same episode up again from where it stopped rather than skipping it,
    and doesn't blame the file."""
    from app import broadcaster

    monkeypatch.setattr(broadcaster, "STALL_TIMEOUT_S", 3.0)
    # Request 1 is the check that the file opens; request 2, playing it, hangs.
    async with StallingServer(media["good1"], 0.4, stall_on={2}) as share:
        plex = FakePlex()
        plex.add_show("100", "Test Show")
        plex.add_episode("201", "100", 1, 1, "hiccup", "/not/local/1.mkv", CLIP_S * 1000)
        plex.add_episode("202", "100", 1, 2, "good2", str(media["good2"]), CLIP_S * 1000)
        base, _app, settings, srv, task = await start_server(
            tmp_path, plex, plex_base=f"http://127.0.0.1:{share.port}"
        )
        try:
            await make_channel(base)
            data = await record(f"{base}/stream/7", CLIP_S + 4)
        finally:
            srv.should_exit = True
            await task
    out = tmp_path / "hiccup.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    text = caplog.text
    assert "Resuming it (attempt 1 of 2)" in text
    assert "hiccup can't play" not in text and "can't play;" not in text  # never replaced
    broken = settings.data_dir / "broken-files.json"
    assert not broken.exists() or json.loads(broken.read_text())["files"] == []


async def test_a_failing_engine_goes_off_the_air_and_keeps_streaming(
    tmp_path, media, monkeypatch, caplog
):
    """If the station's engine itself keeps failing, viewers get the
    off-air card instead of a dead stream, and it tries again later."""
    from app import broadcaster

    monkeypatch.setattr(broadcaster, "OFF_AIR_PAUSE_S", 60.0)
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    plex.add_episode("201", "100", 1, 1, "good1", str(media["good1"]), CLIP_S * 1000)
    base, app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        await make_channel(base)

        def broken_schedule(channel_id):
            raise RuntimeError("simulated engine fault")

        monkeypatch.setattr(app.state.ctx, "station", broken_schedule)
        started = time.time()
        data = await record(f"{base}/stream/7", 14)
        elapsed = time.time() - started
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "offair.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert media_seconds(out) >= elapsed - 6  # three quick restarts, then the card
    assert "OFF THE AIR" in caplog.text


async def test_an_engine_failure_between_programs_doesnt_jump_the_stream(
    tmp_path, media, monkeypatch
):
    """The engine fails right after a program ends: it restarts and carries
    on with the next program, with no jump or overlap in the stream and
    still in step with the guide."""
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    for n, name in enumerate(("good1", "good2", "good3"), start=1):
        plex.add_episode(f"20{n}", "100", 1, n, name, str(media[name]), CLIP_S * 1000)
    base, app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        await make_channel(base)
        ctx = app.state.ctx
        real_station = ctx.station
        calls = {"n": 0}

        def failing_once(channel_id):
            calls["n"] += 1
            if calls["n"] == 2:  # just after the first program
                raise RuntimeError("simulated engine fault")
            return real_station(channel_id)

        monkeypatch.setattr(ctx, "station", failing_once)
        started = time.time()
        data = await record(f"{base}/stream/7", 2.2 * CLIP_S)
        elapsed = time.time() - started
        engine = ctx.broadcasters[next(iter(ctx.broadcasters))]
        playing = engine.now_playing
        guide_now = real_station(engine.channel_id).locate(int(time.time() * 1000))
    finally:
        srv.should_exit = True
        await task
    assert calls["n"] >= 3
    out = tmp_path / "restart.ts"
    out.write_bytes(data)
    assert_clean_stream(out)  # no timestamp jump or overlap at the restart
    assert elapsed - 3 <= media_seconds(out) <= elapsed + 20
    # Still airing what the guide says (not a whole program ahead).
    assert playing is not None and guide_now is not None
    assert abs(playing.slot_start_ms - guide_now.start_ms) <= CLIP_S * 1000
