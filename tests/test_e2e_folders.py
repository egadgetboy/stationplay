"""End to end, with no Plex at all: folder libraries laid out as Sonarr and
Radarr lay them out are read with nothing guessed, and a station made from
them streams, with real ffmpeg, as a station from Plex does (the plan's
gate for Phase 3)."""

from __future__ import annotations

import asyncio
import os
import shutil

import httpx
import pytest
import uvicorn

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .folderlib import Clips, radarr_movies, sonarr_tv
from .helpers import PAGE
from .test_e2e import assert_clean_stream, free_port, record

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


@pytest.fixture(scope="session")
def clips(tmp_path_factory) -> Clips:
    return Clips(tmp_path_factory.mktemp("clips"))


async def scanned(client: httpx.AsyncClient, name: str, kind: str, folder: str) -> str:
    made = await client.post(
        "/api/folder-libraries", json={"name": name, "kind": kind, "folders": [folder]}
    )
    assert made.status_code == 201, made.text
    key = made.json()["key"]
    for _ in range(600):
        listed = (await client.get("/api/folder-libraries")).json()["libraries"]
        if next(x for x in listed if x["key"] == key)["scannedMs"]:
            return key
        await asyncio.sleep(0.05)
    raise AssertionError("the folder library wasn't scanned")


async def test_stations_run_from_folders_alone(tmp_path, clips):
    media = tmp_path / "media"
    sonarr_tv(media / "TV", clips)
    radarr_movies(media / "Movies", clips)
    settings = Settings(
        data_dir=tmp_path / "data",
        media_dir=str(media),
        video_width=640,
        video_height=360,
        video_bitrate_kbps=800,
        idle_grace_seconds=1,
        ffmpeg_path=os.environ.get("FFMPEG_PATH", "ffmpeg"),
        hw_accel="cpu",
    )
    app = create_app(settings, PlexClient("", ""))
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient(headers=PAGE, base_url=base, timeout=30) as client:
            tv = await scanned(client, "TV", "show", "TV")
            movies = await scanned(client, "Movies", "movie", "Movies")
            # Nothing guessed: every episode placed and every movie named by
            # its folders and NFOs, nothing left to match.
            folders = app.state.ctx.folders
            assert not [t for t in folders.things.values() if t.needs]
            for t in folders.things.values():
                if t.kind == "episode":
                    placed = t.details.get("episode") or t.details["released"]
                    assert placed[1] in ("nfo", "names")
                elif t.kind == "movie":
                    assert t.details["title"][1] in ("nfo", "names")
            shows = {
                x["title"]: x["ratingKey"]
                for x in (await client.get(f"/api/libraries/{tv}/items")).json()
            }
            made = await client.post(
                "/api/channels",
                json={
                    "number": 7, "name": "Northbound TV", "orderMode": "rotate",
                    "sources": [{"type": "show", "ratingKey": shows["Northbound"]}],
                },
            )  # fmt: skip
            assert made.status_code == 201, made.text
            assert made.json()["itemCount"] == 3
            movie_station = await client.post(
                "/api/channels",
                json={
                    "number": 8,
                    "sources": [{"type": "section", "key": movies, "sectionType": "movie"}],
                },
            )
            assert movie_station.status_code == 201, movie_station.text
            lineup = (await client.get("/lineup.json")).json()
            assert [s["GuideNumber"] for s in lineup] == ["7", "8"]
        data = await record(f"{base}/stream/7", 8)
        path = tmp_path / "recorded.ts"
        path.write_bytes(data)
        assert len(data) > 50_000
        assert_clean_stream(path)
    finally:
        srv.should_exit = True
        await task
