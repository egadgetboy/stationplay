"""The Stats tab: viewings kept as people stop watching, and what they add up to."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import stats
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .test_e2e import record, start_server
from .test_intro import media as colours

MIN = 60_000


@pytest.fixture
def client(tmp_path):
    fp = FakePlex()
    fp.add_section("2", "Movies", "movie")
    fp.add_show("100", "Cheers")
    for n in range(1, 4):
        fp.add_episode(f"10{n}", "100", 1, n, f"Ep {n}", f"/tv/{n}.mkv", 30 * MIN)
    fp.add_movie("500", "Jaws", "/movies/jaws.mkv", 120 * MIN, section="2")
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    with TestClient(app) as c:
        yield c


def make(client, number: int, source: dict) -> int:
    made = client.post("/api/channels", json={"number": number, "sources": [source]})
    assert made.status_code == 201, made.text
    return made.json()["id"]


def test_stations_are_ranked_by_how_much_theyre_watched(client):
    ctx = client.app.state.ctx
    sitcoms = make(client, 1, {"type": "show", "ratingKey": "100"})
    movies = make(client, 2, {"type": "movie", "ratingKey": "500"})
    quiet = make(client, 3, {"type": "show", "ratingKey": "100"})
    now = int(time.time() * 1000)

    def watch(channel_id: int, from_min: float, minutes: float) -> None:
        # (Since the stations were made: they air nothing before then.)
        start = now + from_min * MIN
        ctx.stats.record(
            channel_id, ctx.station(channel_id), int(start), int(start + minutes * MIN)
        )

    watch(sitcoms, 0, 45)
    watch(sitcoms, 60, 20)
    watch(movies, 100, 90)
    watch(movies, 200, 0.5)  # flicking past: not counted
    got = client.get("/api/stats?days=7").json()
    ranked = [(s["number"], s["views"], s["hours"]) for s in got["stations"]]
    assert ranked == [(2, 1, 1.5), (1, 2, 1.08), (3, 0, 0.0)]  # least watched last
    by_number = {s["number"]: s for s in got["stations"]}
    assert by_number[1]["averageMinutes"] == 32.5 and by_number[1]["top"] == "Cheers"
    assert by_number[2]["top"] == "Jaws" and by_number[3]["top"] is None
    assert got["totals"] == {"views": 3, "hours": 2.58, "watched": 2}
    programs = {p["title"]: p for p in got["programs"]}
    assert set(programs) == {"Cheers", "Jaws"} and programs["Jaws"]["stations"] == [2]
    assert programs["Cheers"]["hours"] <= 65 / 60  # (programs only, not breaks)
    assert abs(sum(got["byHour"]) - 2.58) < 0.02
    assert client.get("/api/stats?days=3").status_code == 400
    # A deleted station's viewings go with it.
    client.delete(f"/api/channels/{movies}")
    assert [s["number"] for s in client.get("/api/stats?days=0").json()["stations"]] == [1, 3]
    assert quiet  # (made only to be least watched)


def test_today_and_the_last_7_days_begin_at_midnight():
    noon = time.mktime((2026, 3, 3, 12, 0, 0, 0, 0, -1)) * 1000
    assert stats.since_ms(1, noon) == noon - 12 * 3_600_000
    assert stats.day_of(stats.since_ms(7, noon)) == "2026-02-25"  # (back over a month end)
    assert stats.since_ms(0, noon) == 0
    assert stats.next_midnight(noon) == noon + 12 * 3_600_000


def test_what_aired_follows_the_schedule(client):
    ctx = client.app.state.ctx
    sitcoms = make(client, 1, {"type": "show", "ratingKey": "100"})
    station = ctx.station(sitcoms)
    slot = station.locate(int(time.time() * 1000))
    # From halfway through one episode to halfway through the next.
    start = slot.start_ms + 15 * MIN
    aired = stats.what_aired(station, start, start + 30 * MIN)
    assert sum(seconds for *_, seconds in aired) == pytest.approx(30 * 60)
    assert {(title, kind) for _, title, kind, _ in aired} == {("Cheers", "episode")}
    # Watched over midnight: some on each day.
    midnight = stats.next_midnight(start)
    aired = stats.what_aired(station, midnight - 10 * MIN, midnight + 10 * MIN)
    days = {day for day, *_ in aired}
    assert days == {stats.day_of(midnight - 1), stats.day_of(midnight)}
    assert sum(seconds for *_, seconds in aired) <= 20 * 60


async def test_watching_a_station_is_counted_when_you_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "MIN_VIEW_S", 1)
    plex = colours(tmp_path, 20)
    base, _app, _settings, srv, task = await start_server(
        tmp_path, plex, media_dir=str(tmp_path / "media")
    )
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={"number": 5, "sources": [{"type": "show", "ratingKey": "100"}]},
            )
            assert made.status_code == 201, made.text
            await record(f"{base}/stream/5", 3)
            for _ in range(50):  # (kept as the stream closes)
                got = (await client.get("/api/stats?days=1")).json()
                if got["totals"]["views"]:
                    break
                await asyncio.sleep(0.05)
    finally:
        srv.should_exit = True
        await task
    assert got["stations"][0]["views"] == 1 and got["stations"][0]["top"] == "Colours"
