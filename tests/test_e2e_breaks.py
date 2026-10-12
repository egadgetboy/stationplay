"""End to end: commercials, the Station ID card and the corner logo, with
real ffmpeg.

Programs and commercials are solid colours, so what a viewer receives can be
read back frame by frame; the Station ID card is dark.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from .fakeplex import FakePlex
from .test_e2e import assert_clean_stream, ff, record, start_server
from .test_e2e_skipping import UV, assert_runs

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

S = 1000
FRAME_S = 1001 / 30000
UV = {**UV, "red": (90, 240)}


def solid(path: Path, colour: str, seconds: float, tone: int = 440) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ff(
        "-f", "lavfi", "-i", f"color=c={colour}:s=640x360:r=30:d={seconds}",
        "-f", "lavfi", "-i", f"sine=f={tone}:sample_rate=48000", "-t", str(seconds),
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path),
    )  # fmt: skip


def frames(path: Path, crop: str) -> list[tuple[float, float, float]]:
    """(average Y, U, V) of one area of every frame."""
    out = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path), "-vf",
            f"crop={crop},signalstats,metadata=print:file=-", "-f", "null", "-",
        ],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    got: list[tuple[float, float, float]] = []
    y = u = 0.0
    for line in out.splitlines():
        if "signalstats.YAVG=" in line:
            y = float(line.split("=")[1])
        elif "signalstats.UAVG=" in line:
            u = float(line.split("=")[1])
        elif "signalstats.VAVG=" in line:
            got.append((y, u, float(line.split("=")[1])))
    return got


def colour_of(y: float, u: float, v: float) -> str:
    if y < 40:
        return "dark"
    return min(UV, key=lambda c: (UV[c][0] - u) ** 2 + (UV[c][1] - v) ** 2)


def runs(path: Path) -> list[tuple[str, float]]:
    # The top left: well clear of the cards' writing and of the corner logo,
    # and where the Station ID card's background is darkest.
    out: list[list] = []
    for y, u, v in frames(path, "48:36:8:8"):
        colour = colour_of(y, u, v)
        if out and out[-1][0] == colour:
            out[-1][1] += 1
        else:
            out.append([colour, 1])
    return [(c, n * FRAME_S) for c, n in out]


def media(tmp_path: Path, commercials: dict[str, tuple[str, float]]) -> FakePlex:
    root = tmp_path / "media"
    plex = FakePlex()
    plex.set_locations("1", "/data/tv")  # Plex's own path for the TV library
    plex.add_show("100", "Colours")
    for n, colour in enumerate(("yellow", "cyan"), start=1):
        path = root / "tv" / "Colours" / f"{n}.mkv"
        solid(path, colour, 6)
        plex.add_episode(f"20{n}", "100", 1, n, f"Episode {n}", str(path), 6 * S)
    for name, (colour, seconds) in commercials.items():
        solid(root / "tv" / "commercials" / name, colour, seconds, tone=880)
    (root / "tv" / "commercials").mkdir(parents=True, exist_ok=True)
    (root / "tv" / "commercials" / ".plexignore").write_text("*\n")
    return plex


async def make_station(base: str, **settings) -> dict:
    async with httpx.AsyncClient(base_url=base, timeout=60) as client:
        made = await client.post(
            "/api/channels",
            json={
                "number": 5,
                "name": "Breaks TV",
                "orderMode": "rotate",
                "sources": [{"type": "show", "ratingKey": "100"}],
                **settings,
            },
        )
        assert made.status_code == 201, made.text
        return made.json()


async def watch_status(base: str, seconds: float) -> set[str]:
    """What the status said was on between programs, while watching."""
    seen: set[str] = set()
    deadline = time.monotonic() + seconds
    async with httpx.AsyncClient(base_url=base, timeout=10) as client:
        while time.monotonic() < deadline:
            for stream in (await client.get("/api/status")).json()["streams"]:
                if stream["between"]:
                    seen.add(stream["between"]["kind"])
                    assert stream["between"]["after"]["title"].startswith("Episode")
            await asyncio.sleep(0.4)
    return seen


async def test_commercials_and_the_station_id_card_follow_each_program(tmp_path, caplog):
    plex = media(tmp_path, {"one.mp4": ("magenta", 3.5), "two.mp4": ("orange", 3.5)})
    base, _app, _settings, srv, task = await start_server(
        tmp_path, plex, media_dir=str(tmp_path / "media")
    )
    try:
        # (The commercials are found in the background as StationPlay starts:
        # a station made before then has none until its next update.)
        async with httpx.AsyncClient(base_url=base) as client:
            for _ in range(100):
                found = (await client.get("/api/status")).json()["fillers"]["commercials"]
                if found == 2:
                    break
                await asyncio.sleep(0.1)
        station = await make_station(
            base,
            breaks=2,
            stationId=True,
            watermark="logo",
            logo="classic-tv",
            watermarkPosition="bottom-right",  # (where it's looked for below)
        )
        assert (station["breaks"], station["stationId"], station["watermark"]) == (2, True, "logo")
        async with httpx.AsyncClient(base_url=base) as client:
            status = (await client.get("/api/status")).json()
            guide = (await client.get(f"/api/channels/{station['id']}/guide?hours=1")).json()
        assert status["fillers"]["commercials"] == 2
        assert status["fillers"]["commercialFolders"] == [str(tmp_path / "media/tv/commercials")]
        # Each program's time includes what follows it: 6 + 3.5 + 3.5, and
        # the Station ID card's 5 seconds.
        assert [g["end"] - g["start"] for g in guide[:3]] == [18 * S] * 3
        data, seen = await asyncio.gather(record(f"{base}/stream/5", 50), watch_status(base, 48))
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "breaks.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert "falling behind" not in caplog.text
    assert "a plain card plays instead" not in caplog.text  # the real card each time
    got = runs(out)
    # Both commercials in every break, in either order, then the card.
    assert [c for c, _ in got[:4]] == ["yellow", got[1][0], got[2][0], "dark"]
    assert {got[1][0], got[2][0]} == {"magenta", "orange"}
    assert {got[5][0], got[6][0]} == {"magenta", "orange"}
    assert_runs(
        got,
        [
            ("yellow", 6),
            (got[1][0], 3.5),
            (got[2][0], 3.5),
            ("dark", 5),
            ("cyan", 6),
            (got[5][0], 3.5),
            (got[6][0], 3.5),
            ("dark", 5),
        ],
    )
    assert seen >= {"commercials", "station id"}, seen
    # The logo is in the corner during programs, never during commercials.
    centre = frames(out, "40:40:300:160")
    corner = frames(out, "30:30:580:305")
    marked = {"yellow": [], "cyan": [], "magenta": [], "orange": []}
    for (cy, cu, cv), (ky, ku, kv) in zip(centre, corner, strict=True):
        colour = colour_of(cy, cu, cv)
        if colour in marked:
            marked[colour].append(abs(cy - ky) + abs(cu - ku) + abs(cv - kv))
    print({c: (min(d), max(d)) for c, d in marked.items() if d})
    for colour in ("yellow", "cyan"):
        on = [d for d in marked[colour] if d > 12]
        assert len(on) > 0.95 * len(marked[colour]), colour
    for colour in ("magenta", "orange"):
        assert max(marked[colour]) < 6, colour


async def test_a_commercial_that_stops_short_is_covered_and_left_out(tmp_path, caplog):
    plex = media(tmp_path, {"good.mp4": ("magenta", 4)})
    # A file that says it's 4 seconds long but was cut off after about 1.5.
    whole = tmp_path / "whole.mkv"
    solid(whole, "lime", 4)
    cut = tmp_path / "media" / "tv" / "commercials" / "cut.mkv"
    cut.write_bytes(whole.read_bytes()[: int(whole.stat().st_size * 0.4)])
    base, _app, _settings, srv, task = await start_server(
        tmp_path, plex, media_dir=str(tmp_path / "media")
    )
    try:
        station = await make_station(base, breaks=1, logo="")
        async with httpx.AsyncClient(base_url=base) as client:
            status = (await client.get("/api/status")).json()
        assert status["fillers"]["commercials"] == 2  # it opens fine, so it's used
        data = await record(f"{base}/stream/5", 44)
        async with httpx.AsyncClient(base_url=base) as client:
            status = (await client.get("/api/status")).json()
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "short.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    got = runs(out)
    print(got)
    # (On GitHub this has now and then found nothing wrong: what played says why.)
    assert "cut.mkv didn't play" in caplog.text, (status["fillers"], got)
    assert status["fillers"]["unplayable"] == [str(cut)]
    assert not (tmp_path / "data" / "broken-files.json").exists()  # no program blamed
    colours = [c for c, _ in got]
    # Programs keep their places whatever happens in the breaks.
    programs = [(c, s) for c, s in got if c in ("yellow", "cyan")]
    assert [c for c, _ in programs][:3] == ["yellow", "cyan", "yellow"]
    assert all(abs(s - 6) < 0.3 for _, s in programs[1:3]), programs
    # The cut clip plays what it has, the card covers the rest; next time
    # round the card covers all of it.
    if "lime" in colours:
        at = colours.index("lime")
        assert got[at][1] < 2.0 and got[at + 1][0] == "dark"
        assert abs(got[at][1] + got[at + 1][1] - 4.0) < 0.3
    dark = [s for c, s in got if c == "dark"]
    assert any(abs(s - 4.0) < 0.3 for s in dark), got
    assert station["breaks"] == 1


async def test_a_corner_logo_that_cant_be_drawn_doesnt_stop_a_program(tmp_path, caplog):
    plex = media(tmp_path, {})
    base, app, _settings, srv, task = await start_server(
        tmp_path, plex, media_dir=str(tmp_path / "media")
    )
    app.state.ctx.logos.path = lambda logo_id: Path("/gone/logo.png")  # vanished
    try:
        await make_station(base, watermark="logo", logo="classic-tv")
        data = await record(f"{base}/stream/5", 14)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "nologo.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert "trying it again with nothing drawn over it" in caplog.text
    assert [c for c, _ in runs(out)][:2] == ["yellow", "cyan"]
    assert not (tmp_path / "data" / "broken-files.json").exists()
