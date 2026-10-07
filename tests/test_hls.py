"""Stations as HLS, for StationPlay's apps: real ffmpeg and a fake Plex."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import time

import httpx
import pytest
import uvicorn

from app import hls
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .test_e2e import (
    CLIP_S,
    assert_clean_stream,
    make_channel,
    media,
    media_seconds,
    record,
    start_server,
)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

__all__ = ["media"]  # (the fixture, shared with the end-to-end tests)


def pieces(playlist: str) -> list[str]:
    return [line for line in playlist.splitlines() if line and not line.startswith("#")]


def sequence(playlist: str) -> int:
    found = re.search(r"#EXT-X-MEDIA-SEQUENCE:(\d+)", playlist)
    assert found, playlist
    return int(found.group(1))


def starts_on_a_keyframe(path) -> bool:
    # (As JSON: a frame with side data, such as the first one of an encode,
    # which carries the encoder's settings, has more than its fields in CSV.)
    frames = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1",
         "-show_entries", "frame=key_frame", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout).get("frames") or []  # fmt: skip
    return bool(frames) and frames[0].get("key_frame") == 1


def video_start(path, what: str) -> str:
    """The first few video packets or frames of a piece, for a failure's message."""
    entries = {"packet": "packet=pts_time,flags,size", "frame": "frame=key_frame,pict_type,pts_time"}[what]
    got = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#4",
         "-show_entries", entries, "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )  # fmt: skip
    return " ".join(got.stdout.split()) + (f" ({got.stderr.strip()[:120]})" if got.stderr.strip() else "")


def two_episode_show(media) -> FakePlex:
    plex = FakePlex()
    plex.add_show("100", "Test Show")
    for n, name in enumerate(("good1", "good2", "good3"), start=1):
        plex.add_episode(str(200 + n), "100", 1, n, name, str(media[name]), CLIP_S * 1000)
    return plex


async def test_an_app_watches_a_station_as_hls(tmp_path, media, monkeypatch):
    monkeypatch.setattr(hls, "IDLE_S", 3.0)
    monkeypatch.setattr(hls, "IDLE_CHECK_S", 0.5)
    base, app, settings, srv, task = await start_server(tmp_path, two_episode_show(media))
    try:
        channel = await make_channel(base)
        ctx = app.state.ctx
        async with httpx.AsyncClient(base_url=base, timeout=60) as client:
            first = await client.get("/hls/7/index.m3u8")
            assert first.status_code == 200, first.text
            assert first.headers["content-type"].startswith("application/vnd.apple.mpegurl")
            assert first.headers["access-control-allow-origin"] == "*"
            assert len(pieces(first.text)) >= hls.READY_PIECES

            # Play along as a player does: ask for the playlist again every
            # second, and fetch each new piece.
            got: dict[str, bytes] = {}
            playlist = first.text
            deadline = time.monotonic() + 14
            while time.monotonic() < deadline:
                for name in pieces(playlist):
                    if name not in got:
                        piece = await client.get(f"/hls/7/{name}")
                        assert piece.status_code == 200, f"{name}: {piece.status_code}"
                        assert piece.headers["content-type"] == "video/mp2t"
                        got[name] = piece.content
                await asyncio.sleep(1)
                playlist = (await client.get("/hls/7/index.m3u8")).text
            assert sequence(playlist) > sequence(first.text)  # it moves along

            # A real HLS player (ffmpeg's own) watches it live, reloading the
            # playlist as it goes.
            watched = tmp_path / "player.ts"
            player = await asyncio.create_subprocess_exec(
                "ffmpeg", "-v", "error", "-y", "-i", f"{base}/hls/7/index.m3u8",
                "-t", "8", "-c", "copy", str(watched),
                stderr=asyncio.subprocess.PIPE,
            )  # fmt: skip
            _, said = await asyncio.wait_for(player.communicate(), 60)
            assert player.returncode == 0, said
            assert media_seconds(watched) > 7

            # One stream for the station, shared: the apps are one viewer.
            b = ctx.broadcasters[channel["id"]]
            assert b.running and len(b.viewers) == 1
            status = (await client.get("/api/status")).json()
            assert [s["viewers"] for s in status["streams"]] == [1]

            for odd in ("..%2Fstationplay.db", "stationplay.db", "s1.ts.tmp", "index.m3u8.tmp"):
                assert (await client.get(f"/hls/7/{odd}")).status_code in (404, 405), odd
            assert (await client.get("/hls/7/s999999.ts")).status_code == 404
            assert (await client.get("/hls/9/index.m3u8")).status_code == 404

        # Each piece starts on a keyframe, and together they play cleanly.
        ordered = sorted(got, key=lambda name: int(name[1:-3]))
        for name in ordered:
            (tmp_path / name).write_bytes(got[name])
        for before, name in zip(ordered, ordered[1:]):
            path = tmp_path / name
            assert starts_on_a_keyframe(path), (
                f"{name} doesn't start on a keyframe. Its packets: {video_start(path, 'packet')}; "
                f"frames: {video_start(path, 'frame')}; {before} began: {video_start(tmp_path / before, 'packet')}; "
                f"pieces {ordered}"
            )
        joined = tmp_path / "joined.ts"
        joined.write_bytes(b"".join(got[name] for name in ordered))
        assert_clean_stream(joined)

        # Once no app asks, it stops and tidies up, and so does the station.
        stream = ctx.hls_streams.get(channel["id"])
        assert stream is not None
        folder = stream.folder
        await asyncio.sleep(hls.IDLE_S + 1 + settings.idle_grace_seconds + 1.5)
        assert ctx.hls_streams.get(channel["id"]) is None
        assert not folder.exists()
        assert not b.running
    finally:
        srv.should_exit = True
        await task


async def test_apps_share_tuners_with_everyone_else(tmp_path, media):
    base, app, _settings, srv, task = await start_server(tmp_path, two_episode_show(media))
    try:
        await make_channel(base, 7)
        await make_channel(base, 8)
        async with httpx.AsyncClient(base_url=base, timeout=60) as client:
            assert (await client.put("/api/playback", json={"tuners": 1})).status_code == 200

            async def apps() -> tuple[httpx.Response, httpx.Response]:
                await asyncio.sleep(2)  # (once Plex is watching station 7)
                return (
                    await client.get("/hls/8/index.m3u8"),
                    await client.get("/hls/7/index.m3u8"),
                )

            watched, (other, same) = await asyncio.gather(record(f"{base}/stream/7", 10), apps())
        assert len(watched) > 100_000
        # Another station would need a second tuner: the app is told why.
        assert other.status_code == 503
        assert other.json() == {"detail": "All tuners in use", "onNow": [7]}
        assert other.headers["access-control-allow-origin"] == "*"
        # The station Plex is watching: the app joins it, on the same tuner.
        assert same.status_code == 200, same.text
        assert [b.channel_id for b in app.state.ctx.broadcasters.values() if b.running] == [1]
    finally:
        await app.state.ctx.hls_streams.stop_all("the test is over")
        srv.should_exit = True
        await task


async def test_an_app_that_tunes_away_frees_its_tuner(tmp_path, media):
    """Flipping stations in an app: it says when it leaves one, and that
    station's tuner is free for the next straight away, rather than when the
    app's stream notices no one's asking. Another device saying it left
    changes nothing."""
    base, app, _settings, srv, task = await start_server(tmp_path, two_episode_show(media))
    try:
        await make_channel(base, 7)
        await make_channel(base, 8)
        elsewhere = httpx.AsyncHTTPTransport(local_address="127.0.0.2")
        async with (
            httpx.AsyncClient(base_url=base, timeout=60) as client,
            httpx.AsyncClient(base_url=base, timeout=60, transport=elsewhere) as other_device,
        ):
            assert (await client.put("/api/playback", json={"tuners": 1})).status_code == 200
            assert (await client.get("/hls/7/index.m3u8")).status_code == 200
            busy = await client.get("/hls/8/index.m3u8")
            assert busy.status_code == 503 and busy.json()["onNow"] == [7]
            # (Someone else saying they left station 7 doesn't stop it.)
            assert (await other_device.post("/hls/7/leave")).status_code == 204
            assert app.state.ctx.hls_streams.get(1) is not None
            assert (await client.post("/hls/7/leave")).status_code == 204
            assert app.state.ctx.hls_streams.get(1) is None
            assert (await client.get("/hls/8/index.m3u8")).status_code == 200
            # Leaving what isn't playing, or isn't a station, is fine too.
            assert (await client.post("/hls/7/leave")).status_code == 204
            assert (await client.post("/hls/99/leave")).status_code == 204
    finally:
        await app.state.ctx.hls_streams.stop_all("the test is over")
        srv.should_exit = True
        await task


async def start_with_public_port(tmp_path, plex: FakePlex):
    """StationPlay on its home-network port and its public one: (the home
    network's address, the internet's), and the app, server and its task."""
    lan, public = (socket.create_server(("127.0.0.1", 0)) for _ in range(2))
    ports = lan.getsockname()[1], public.getsockname()[1]
    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
        video_width=640, video_height=360, video_bitrate_kbps=800, idle_grace_seconds=1,
        ffmpeg_path=os.environ.get("FFMPEG_PATH", "ffmpeg"), hw_accel="cpu",
        port=ports[0], public_port=ports[1],
    )  # fmt: skip
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=plex.transport()))
    srv = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    task = asyncio.create_task(srv.serve(sockets=[lan, public]))
    while not srv.started:
        await asyncio.sleep(0.05)
    return tuple(f"http://127.0.0.1:{port}" for port in ports), app, srv, task


PAT = {"name": "Pat", "password": "correct horse"}


async def test_an_app_away_from_home_watches_through_the_public_port(tmp_path, media):
    """Off until an Admin turns it on; then an app signed in from the
    internet plays each station at an address of its own, which ends with
    its sign-in, or when it's turned off. Plex's addresses stay home."""
    (home, internet), app, srv, task = await start_with_public_port(
        tmp_path, two_episode_show(media)
    )
    try:
        await make_channel(home, 7)
        async with (
            httpx.AsyncClient(base_url=home, timeout=60) as inside,
            httpx.AsyncClient(
                base_url=internet,
                timeout=60,
                headers={"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-Proto": "https"},
            ) as phone,
        ):
            assert (await inside.post("/api/access/users", json=PAT)).status_code == 201

            async def sign_in() -> dict[str, str]:
                signed = await phone.post("/api/v1/sign-in", json=PAT)
                assert signed.status_code == 200, signed.text
                return {"Authorization": f"Bearer {signed.json()['token']}"}

            async def hls_of(auth: dict[str, str]) -> str:
                [station] = (await phone.get("/api/v1/stations", headers=auth)).json()["stations"]
                return station["hls"]

            auth = await sign_in()
            server = (await phone.get("/api/v1/server", headers=auth)).json()
            assert server["outside"] and server["awayAddress"] is None
            assert server["features"] == ["hls"]
            # Off: from outside, nothing to play.
            assert await hls_of(auth) == "/hls/7/index.m3u8"
            assert (await phone.get("/hls/7/index.m3u8")).status_code == 404

            bad = await inside.put("/api/away", json={"on": True, "address": "tv.example.com"})
            assert bad.status_code == 400 and "https://" in bad.json()["detail"]
            on = await inside.put(
                "/api/away", json={"on": True, "address": " https://tv.example.com/ "}
            )
            assert on.status_code == 200 and on.json()["address"] == "https://tv.example.com"
            server = (await phone.get("/api/v1/server", headers=auth)).json()
            assert server["awayAddress"] == "https://tv.example.com"
            assert server["features"] == ["hls", "away"]
            at_home = (await inside.get("/api/v1/server")).json()
            assert not at_home["outside"] and at_home["awayAddress"] == "https://tv.example.com"
            assert (await inside.get("/api/v1/stations")).json()["stations"][0]["hls"] == (
                "/hls/7/index.m3u8"
            )

            hls_url = await hls_of(auth)
            assert re.fullmatch(r"/hls/k/[\w-]{20,}/7/index\.m3u8", hls_url)
            assert await hls_of(auth) == hls_url  # (one address per sign-in)
            # The logo too, for the app's guide.
            [station] = (await phone.get("/api/v1/stations", headers=auth)).json()["stations"]
            logo = station["logo"]
            assert logo.startswith(hls_url.replace("index.m3u8", "logo.png?v="))
            got = await phone.get(logo)
            assert got.status_code == 200 and got.headers["content-type"] == "image/png"
            assert (
                (await inside.get("/api/v1/stations"))
                .json()["stations"][0]["logo"]
                .startswith("/channel-icon/7.png?v=")
            )
            playlist = await phone.get(hls_url)
            assert playlist.status_code == 200, playlist.text
            first = hls_url.replace("index.m3u8", pieces(playlist.text)[0])
            piece = await phone.get(first)
            assert piece.status_code == 200 and len(piece.content) > 10_000
            # Plex's addresses, and anyone else's, still aren't there.
            assert (await phone.get("/hls/7/index.m3u8")).status_code == 404
            assert (await phone.get("/hls/k/not-a-key/7/index.m3u8")).status_code == 404
            assert (await phone.post(hls_url.replace("index.m3u8", "leave"))).status_code == 204
            assert app.state.ctx.hls_streams.get(1) is None

            log = (await inside.get("/api/logs?access_log=true")).json()["text"]
            assert "Pat is watching station 7 away from home, from 203.0.113.7" in log
            # Signing out ends that app's address.
            assert (await phone.post("/api/v1/sign-out", headers=auth)).status_code == 200
            assert (await phone.get(hls_url)).status_code == 404
            assert (await phone.get(logo)).status_code == 404
            # And turning it off ends every one.
            auth = await sign_in()
            hls_url = await hls_of(auth)
            assert hls_url != "/hls/7/index.m3u8"
            assert (await inside.put("/api/away", json={"on": False})).status_code == 200
            assert (await phone.get(hls_url)).status_code == 404
            assert (await phone.get(hls_url.replace("index.m3u8", "s0.ts"))).status_code == 404
    finally:
        await app.state.ctx.hls_streams.stop_all("the test is over")
        srv.should_exit = True
        await task
