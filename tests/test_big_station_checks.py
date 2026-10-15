"""A big new station's file checks (1.37.1, the owner, October 15: making
smart stations of 10,000 to 40,000 episodes hung tapiOca). A new station's
automatic check covered every file at once, one task per program; now it
checks what airs in its next 24 hours, and the scanner takes the rest, in
its own order. Check files on a station's card still checks everything,
with CHECK_CONCURRENCY workers rather than a task per program."""

from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from app import jobs
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex

DAY_MS = 24 * 3600 * 1000


def make(tmp_path, episodes: int, minutes: int = 22):
    fp = LibraryPlex()
    fp.add_show("100", "Long Runner")
    for n in range(episodes):
        fp.add_episode(
            str(10_000 + n), "100", 1 + n // 100, 1 + n % 100, f"Episode {n}", f"/x/{n}.mkv",
            minutes * 60_000,
        )  # fmt: skip
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "d")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    return TestClient(app)


def checking(monkeypatch) -> list[str]:
    checked: list[str] = []

    async def check_item(ctx, item, channel_number):
        checked.append(item.rating_key)
        await asyncio.sleep(0)
        return "ok"

    monkeypatch.setattr(jobs, "check_item", check_item)
    return checked


def finished(client: TestClient, channel_id: int) -> dict:
    ctx = client.app.state.ctx
    for _ in range(500):
        status = ctx.checks.get(channel_id)
        if status is not None and not status.running:
            return status.as_dict()
        time.sleep(0.01)
    raise AssertionError("the check never finished")


def keys_airing(ctx, channel_id: int, from_ms: int, to_ms: int) -> set[str]:
    return {s.item.rating_key for s in ctx.station(channel_id).between(from_ms, to_ms)}


def test_a_new_stations_check_covers_its_next_day_and_the_scanner_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", True)
    checked = checking(monkeypatch)
    # Three days of programs: 200 episodes of 22 minutes.
    with make(tmp_path, 200) as client:
        ctx = client.app.state.ctx
        before = int(time.time() * 1000)
        made = client.post(
            "/api/channels", json={"number": 4, "sources": [{"type": "show", "ratingKey": "100"}]}
        )
        assert made.status_code == 201, made.text
        station = made.json()["id"]
        status = finished(client, station)
        after = int(time.time() * 1000)
        # What airs in its next 24 hours, and no more (a minute either side,
        # for the time the test itself takes).
        surely = keys_airing(ctx, station, after + 60_000, before + DAY_MS - 60_000)
        at_most = keys_airing(ctx, station, before - 60_000, after + DAY_MS + 60_000)
        assert surely <= set(checked) <= at_most
        assert len(checked) == len(set(checked)) == status["total"] == status["done"]
        assert 50 < len(checked) < 80
        # The rest are the scanner's: never checked, so new to it.
        rest = {i.rating_key for i in ctx.db.all_programs(station)} - set(checked)
        assert len(rest) == 200 - len(checked)
        due = {p.key for p in ctx.scanner._due(ctx.scanner.programs(), ctx.db.scans())}
        assert rest <= due


def test_a_small_new_station_is_checked_whole_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", True)
    checked = checking(monkeypatch)
    with make(tmp_path, 5) as client:
        made = client.post(
            "/api/channels", json={"number": 4, "sources": [{"type": "show", "ratingKey": "100"}]}
        )
        assert made.status_code == 201, made.text
        status = finished(client, made.json()["id"])
        assert sorted(checked) == [str(10_000 + n) for n in range(5)]
        assert status["total"] == status["done"] == 5


def test_check_files_checks_everything_with_a_few_workers(tmp_path, monkeypatch):
    checked: list[str] = []
    most_tasks = 0
    progress: list[int] = []
    with make(tmp_path, 2000) as client:
        ctx = client.app.state.ctx
        made = client.post(
            "/api/channels", json={"number": 4, "sources": [{"type": "show", "ratingKey": "100"}]}
        )
        assert made.status_code == 201, made.text
        station = made.json()["id"]
        status = jobs.CheckStatus(running=True, started_at=time.time())

        async def check_item(ctx, item, channel_number):
            nonlocal most_tasks
            most_tasks = max(most_tasks, len(asyncio.all_tasks()))
            progress.append(status.done)
            checked.append(item.rating_key)
            await asyncio.sleep(0)
            return "ok"

        monkeypatch.setattr(jobs, "check_item", check_item)
        asyncio.run(jobs.run_check(ctx, station, status))
    # Every program, once; the card's progress counting up to 2,000.
    assert sorted(checked) == sorted(str(10_000 + n) for n in range(2000))
    assert status.total == status.done == 2000 and not status.running
    assert progress == sorted(progress) and progress[-1] >= 2000 - jobs.CHECK_CONCURRENCY
    # The check itself, and at most CHECK_CONCURRENCY workers: never a task
    # per program (it was 2,001).
    assert most_tasks <= 1 + jobs.CHECK_CONCURRENCY
