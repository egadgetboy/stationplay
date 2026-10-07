"""Regression tests for problems found in review: races between checks and
edits, Plex hiccups, and changes queued far in the future."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import updates
from app.config import Settings
from app.main import create_app
from app.plex import BULK_REQUESTS, PlexClient, PlexError

from .fakeplex import FakePlex

MIN = 60_000


class GatedPlex:
    """The fake Plex, but requests for chosen paths wait until let through."""

    def __init__(self, fp: FakePlex) -> None:
        self.fp = fp
        self.hold: set[str] = set()
        self.gate = asyncio.Event()
        self.fail: set[str] = set()

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if any(request.url.path.startswith(p) for p in self.fail):
            return httpx.Response(500)
        if any(request.url.path.startswith(p) for p in self.hold):
            await self.gate.wait()
        return self.fp.handler(request)


@pytest.fixture
def setup(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Jetsons")
    fp.add_show("300", "Top Cat")
    for n in (1, 2, 3):
        fp.add_episode(f"10{n}", "100", 1, n, f"Jetsons {n}", f"/tv/j{n}.mkv", 22 * MIN)
        fp.add_episode(f"30{n}", "300", 1, n, f"Top Cat {n}", f"/tv/t{n}.mkv", 22 * MIN)
    gated = GatedPlex(fp)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=httpx.MockTransport(gated.handler)),
    )
    with TestClient(app) as client:
        sources = [{"type": "show", "ratingKey": "100"}, {"type": "show", "ratingKey": "300"}]
        station = client.post("/api/channels", json={"number": 1, "sources": sources}).json()
        yield client, fp, gated, station


def test_a_check_that_overlaps_an_edit_doesnt_undo_it(setup):
    client, fp, gated, station = setup
    ctx = client.app.state.ctx
    fp.add_episode("304", "300", 1, 4, "Top Cat 4", "/tv/t4.mkv", 22 * MIN)
    gated.hold = {"/library/metadata/300/allLeaves"}
    gated.gate = client.portal.call(asyncio.Event)
    checking = client.portal.start_task_soon(ctx.updater.check, True)
    time.sleep(0.3)  # the check is now waiting on Plex, with the old sources
    gated.hold = set()
    edited = client.put(
        f"/api/channels/{station['id']}",
        json={"number": 1, "sources": [{"type": "show", "ratingKey": "100"}]},
    )
    assert edited.json()["itemCount"] == 3  # Top Cat is gone
    client.portal.call(gated.gate.set)
    checking.result(timeout=10)
    # The check's answer was about the old line-up: it's dropped, not queued
    # to bring Top Cat back at the next guide download.
    assert ctx.updater.pending.get(station["id"]) is None


def test_a_plex_hiccup_on_a_filter_isnt_mistaken_for_removed_programs(tmp_path):
    fp = FakePlex()
    fp.add_section("2", "Movies", "movie")
    fp.add_section("3", "More Movies", "movie")
    fp.add_movie("501", "Die Hard", "/m/1.mkv", 130 * MIN, section="2", labels=["Christmas"])
    fp.add_movie("502", "Elf", "/m/2.mkv", 97 * MIN, section="3", labels=["Christmas"])
    gated = GatedPlex(fp)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=httpx.MockTransport(gated.handler)),
    )
    source = {"type": "filter", "kind": "movie", "libraries": ["2", "3"], "label": ["Christmas"]}
    with TestClient(app) as client:
        made = client.post("/api/channels", json={"number": 2, "sources": [source]}).json()
        assert made["itemCount"] == 2
        client.app.state.ctx.plex._choices.clear()
        gated.fail = {"/library/sections/3/label"}
        client.portal.call(client.app.state.ctx.updater.check, True)
        assert client.app.state.ctx.updater.pending.get(made["id"]) is None  # Elf stays
        gated.fail = set()
        client.portal.call(client.app.state.ctx.updater.check, True)
        assert client.app.state.ctx.updater.pending.get(made["id"]) is None


def test_a_change_you_make_isnt_queued_behind_a_future_update(setup):
    """An update waiting for the last guide to run out (up to two days
    away) mustn't hold up a change you make now."""
    client, fp, _gated, station = setup
    ctx = client.app.state.ctx
    client.get("/guide.xml")  # someone has the guide for two days
    fp.add_episode("104", "100", 1, 4, "Jetsons 4", "/tv/j4.mkv", 22 * MIN)
    client.portal.call(ctx.updater.check, True)
    client.portal.call(ctx.updater.apply_overdue)
    far = ctx.db.eras(station["id"])[-1]
    assert far.start_ms > time.time() * 1000 + 40 * 3600_000
    fp.add_episode("105", "100", 1, 5, "Jetsons 5", "/tv/j5.mkv", 22 * MIN)
    now = time.time() * 1000
    updated = client.post(f"/api/channels/{station['id']}/update").json()
    starts = updated["lastChange"]["startsAt"]
    assert now + updates.MARGIN_MS - 1000 <= starts < now + 3 * 3600_000
    assert far.id not in [e.id for e in ctx.db.eras(station["id"])]  # replaced, never aired
    assert updated["itemCount"] == 8


async def test_lookups_for_programs_about_to_play_never_wait_behind_background_work():
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep", "/x.mkv", 22 * MIN)
    client = PlexClient("http://plex.test", "token", transport=fp.transport())
    for _ in range(BULK_REQUESTS):
        await client._bulk.acquire()  # background work has every slot
    part = await asyncio.wait_for(client.current_part("201"), 2)
    assert part is not None and part.file == "/x.mkv"
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(client.section_items("1"), 0.5)


async def test_one_failed_request_cancels_the_rest():
    from app.plex import gather_all

    finished = []

    async def slow():
        await asyncio.sleep(0.5)
        finished.append(1)

    async def fails():
        raise PlexError("down")

    with pytest.raises(PlexError):
        await gather_all([slow(), fails(), slow()])
    await asyncio.sleep(0.7)
    assert finished == []
