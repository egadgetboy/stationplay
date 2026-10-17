"""A station's file checks, found by the cold audit of 1.37.1 (fixed in
1.38.0): Check files pressed while a new station's first-day check runs
checks everything, not only that day; a check that fails before it starts
never stays "running"; and deleting a station stops its check."""

from __future__ import annotations

import asyncio
import time

from app import jobs

from .test_big_station_checks import finished, make

SHOW = {"type": "show", "ratingKey": "100"}


def slow_checks(monkeypatch) -> list[str]:
    checked: list[str] = []

    async def check_item(ctx, item, channel_number):
        checked.append(item.rating_key)
        await asyncio.sleep(0.005)
        return "ok"

    monkeypatch.setattr(jobs, "check_item", check_item)
    return checked


def test_check_files_while_a_new_stations_first_day_is_checked_checks_everything(
    tmp_path, monkeypatch
):
    """(1.37.1: the answer was the first-day check's own, 66 of 200, and
    the other 134 were never checked, though the notes say Check files
    checks everything.)"""
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", True)
    checked = slow_checks(monkeypatch)
    with make(tmp_path, 200) as client:
        ctx = client.app.state.ctx
        made = client.post("/api/channels", json={"number": 4, "sources": [SHOW]})
        assert made.status_code == 201, made.text
        station = made.json()["id"]
        assert ctx.checks[station].running
        asked = client.post(f"/api/channels/{station}/check")
        assert asked.status_code == 200, asked.text
        status = finished(client, station)
        everything = {i.rating_key for i in ctx.db.all_programs(station)}
        assert status["total"] == len(everything) == 200
        assert everything <= set(checked)


def test_a_check_that_fails_before_it_starts_isnt_left_running(tmp_path, monkeypatch):
    """(1.37.1: an error working out what airs soon, outside the check's
    try, left it "running" for good, and Check files gave that answer back
    until a restart.)"""
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", True)
    slow_checks(monkeypatch)

    def broken(ctx, channel_id, within_ms):
        raise RuntimeError("the schedule couldn't be worked out")

    monkeypatch.setattr(jobs, "airing_soon", broken)
    with make(tmp_path, 20) as client:
        made = client.post("/api/channels", json={"number": 4, "sources": [SHOW]})
        station = made.json()["id"]
        assert not finished(client, station)["running"]
        monkeypatch.undo()
        slow_checks(monkeypatch)
        again = client.post(f"/api/channels/{station}/check").json()
        assert again["running"] and again["startedAt"] > 0
        assert finished(client, station)["total"] == 20


def test_deleting_a_station_stops_its_check(tmp_path, monkeypatch):
    """(1.37.1: it ran on, holding the shared check slots, and filed results
    under a station no longer there.)"""
    checked = slow_checks(monkeypatch)
    with make(tmp_path, 300) as client:
        ctx = client.app.state.ctx
        made = client.post("/api/channels", json={"number": 4, "sources": [SHOW]})
        station = made.json()["id"]
        client.post(f"/api/channels/{station}/check")
        time.sleep(0.05)
        assert client.delete(f"/api/channels/{station}").status_code == 204
        at_delete = len(checked)
        time.sleep(0.3)
        assert len(checked) <= at_delete + jobs.CHECK_CONCURRENCY
        assert station not in ctx.checks
