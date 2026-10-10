"""Admin alerts (alerts.py) and notifying a web address of them (notify.py):
each alert starts once, after what it's about has held a while, and ends
once, after it has been right a while; GET /api/internal/alerts is for
Admins; and the web address gets plain text or JSON, waits 5 seconds at
most, follows no redirect, and never holds anything else up."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import shutil
import sqlite3
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import alerts, backups, notify, reach
from app.alerts import Alerts
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.notify import Notify
from app.plex import PlexClient, PlexError

from .fakeplex import FakePlex

ADA = {"name": "Ada", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple", "role": "user"}


class Told:
    """Stands in for the web address: what it was told."""

    def __init__(self) -> None:
        self.said: list[tuple[str, str, str]] = []

    def send(self, message: str, kind: str, state: str) -> None:
        self.said.append((message, kind, state))


class Plex:
    """Stands in for Plex, as the checks ask it: whether it answers, and the
    clock its answers say (seconds this machine is ahead)."""

    configured = True
    base_url = "http://192.168.1.10:32400"

    def __init__(self) -> None:
        self.down: int | None = None  # (an HTTP status, or 0: no answer)
        self.ahead: float | None = None
        self.clock_offset_s: float | None = None

    async def identity(self) -> dict:
        if self.down == 401:
            raise PlexError("Plex didn't accept the token in PLEX_TOKEN", 401)
        if self.down is not None:
            raise PlexError("Plex request for /identity failed (Plex is down)")
        self.clock_offset_s = self.ahead
        return {}


@pytest.fixture(autouse=True)
def plenty_of_room(monkeypatch):
    """The data folder's disk has room, whatever this machine's has (the
    data folder's own test says otherwise)."""
    monkeypatch.setattr(
        shutil, "disk_usage", lambda path: SimpleNamespace(total=100 * 1024**3, free=50 * 1024**3)
    )


@pytest.fixture
def db(tmp_path) -> Database:
    """Where the alerts are kept."""
    return Database(tmp_path / "kept.db")


def status(state: str, short: str = "Ready") -> reach.Status:
    return reach.Status(state, "", short, None, 0, None)


def checks(tmp_path, plex: Plex | None = None, outside: str = reach.OFF) -> SimpleNamespace:
    """What the checks look at: Plex, the data folder, the outside check,
    and the Broken files tab (nothing on it needs an Admin)."""
    folder = tmp_path / "data"
    folder.mkdir(exist_ok=True)
    return SimpleNamespace(
        plex=plex or Plex(),
        settings=SimpleNamespace(data_dir=folder),
        reach=SimpleNamespace(status=lambda: status(outside, "Proxy error")),
        away=SimpleNamespace(address="https://tv.example.com"),
        reports=SimpleNamespace(needing=list),
    )


async def test_an_alert_starts_once_and_is_fixed_once(tmp_path, caplog, db):
    caplog.set_level(logging.INFO)
    told = Told()
    found = Alerts(told, db)  # type: ignore[arg-type]
    plex = Plex()
    ctx = checks(tmp_path, plex)
    # Down, up, down, up: never long enough to say anything.
    for down in (0, None, 0, 0, None):
        plex.down = down
        await found.look(ctx)
    assert found.listed() == [] and told.said == []
    # Down five checks in a row: said once, however long it lasts.
    for _ in range(5):
        plex.down = 0
        await found.look(ctx)
    [alert] = found.now()
    sentence = "StationPlay can't reach Plex at 192.168.1.10:32400. Check that Plex is running."
    assert (alert.kind, alert.sentence, alert.fixed_ms) == ("plex", sentence, None)
    assert told.said == [(sentence, "plex", "started")]
    # Back once: not yet fixed (and its ID stays the same while it lasts).
    first_id = alert.id
    plex.down = None
    await found.look(ctx)
    assert [a.id for a in found.now()] == [first_id]
    plex.down = 0
    await found.look(ctx)
    for _ in range(3):
        plex.down = None
        await found.look(ctx)
    assert found.now() == [] and len(told.said) == 2
    assert told.said[1] == (
        "StationPlay can reach Plex at 192.168.1.10:32400 again.", "plex", "fixed"
    )  # fmt: skip
    [fixed] = found.listed()
    assert fixed.id == first_id and fixed.fixed_ms >= fixed.since_ms
    lines = [r.getMessage() for r in caplog.records if r.name == "app.alerts"]
    assert lines == [f"Alert: {sentence}", f"Alert fixed: {told.said[1][0]}"]
    # Plex refusing StationPlay's token says so.
    for _ in range(5):
        plex.down = 401
        await found.look(ctx)
    assert "doesn't accept StationPlay's token" in found.now()[0].sentence
    # Starting again later, it's a new alert, with an ID of its own.
    assert found.now()[0].id != first_id


async def test_the_clock_is_checked_by_plexs_own(tmp_path, db):
    told = Told()
    found = Alerts(told, db)  # type: ignore[arg-type]
    plex = Plex()
    ctx = checks(tmp_path, plex)
    for ahead in (None, None, None, None):  # (no Date from Plex: nothing to go by)
        plex.ahead = ahead
        await found.look(ctx)
    for ahead in (400.0, 30.0, 400.0, 400.0):
        plex.ahead = ahead
        await found.look(ctx)
    assert found.now() == []
    plex.ahead = 410.0
    await found.look(ctx)
    [alert] = found.now()
    assert alert.kind == "clock" and "is 7 minutes ahead of Plex's" in alert.sentence
    for ahead in (-90.0, 30.0):  # (still out by more than a minute, then right once)
        plex.ahead = ahead
        await found.look(ctx)
    assert found.now() != []
    plex.ahead = -5.0
    await found.look(ctx)
    assert found.now() == [] and told.said[-1][2] == "fixed"


async def test_the_data_folder(tmp_path, monkeypatch, db):
    told = Told()
    found = Alerts(told, db)  # type: ignore[arg-type]
    ctx = checks(tmp_path)
    free = {"bytes": 10 * 1024**3}
    total = 100 * 1024**3
    monkeypatch.setattr(
        shutil, "disk_usage", lambda path: SimpleNamespace(total=total, free=free["bytes"], used=0)
    )
    for got in (1.5, 1.5, 5.0, 1.0, 1.9):  # (GB: low, low, fine, then low again)
        free["bytes"] = int(got * 1024**3)
        await found.look(ctx)
    assert found.now() == []
    free["bytes"] = int(0.8 * 1024**3)
    await found.look(ctx)
    [alert] = found.now()
    assert alert.kind == "data-full" and "has only 819 MB free (1% of its disk)" in alert.sentence
    # Just over the line isn't room enough to be fixed: 3 GB is.
    for got in (2.2, 2.2, 3.1):
        free["bytes"] = int(got * 1024**3)
        await found.look(ctx)
    assert found.now() != []
    await found.look(ctx)
    assert found.now() == [] and told.said[-1] == (
        "StationPlay's data folder has room again (3.1 GB free).", "data-full", "fixed"
    )  # fmt: skip
    # A large pool with a small share free still has plenty: no alert.
    total, free["bytes"] = 20 * 1024**4, 300 * 1024**3
    for _ in range(4):
        await found.look(ctx)
    assert found.now() == []
    # A data folder that can't be written to.
    ctx.settings.data_dir = tmp_path / "gone"
    await found.look(ctx)
    await found.look(ctx)
    [alert] = found.now()
    assert alert.sentence == (
        "StationPlay can't write to its data folder (No such file or directory). Check the "
        "folder's permissions, and that its disk has room."
    )  # (never its path: the apps show alerts)
    assert alert.kind == "data-write" and str(tmp_path) not in alert.sentence
    ctx.settings.data_dir = tmp_path / "data"
    await found.look(ctx)
    await found.look(ctx)
    assert found.now() == [] and told.said[-1][1:] == ("data-write", "fixed")
    assert not (tmp_path / "data" / alerts.WRITE_TEST).exists()


async def test_the_outside_check_goes_by_its_own(tmp_path, db):
    told = Told()
    found = Alerts(told, db)  # type: ignore[arg-type]
    for state in (reach.CHECKING, reach.CANT, reach.DOWN, reach.CHECKING, reach.DOWN):
        await found.look(checks(tmp_path, outside=state))
    [alert] = found.now()
    assert alert.sentence.startswith(
        "StationPlay's apps can't reach it from outside at https://tv.example.com (proxy error)."
    )
    assert len(told.said) == 1
    await found.look(checks(tmp_path, outside=reach.UP))
    assert found.now() == [] and told.said[-1] == (
        "StationPlay's apps can reach it from outside again, at https://tv.example.com.",
        "outside",
        "fixed",
    )


def test_a_station_failing_to_start_and_backups_failing(db):
    told = Told()
    now = [0.0]
    found = Alerts(told, db, clock=lambda: now[0])  # type: ignore[arg-type]
    # Three times, but not within ten minutes: nothing.
    for at in (0.0, 400.0, 800.0):
        now[0] = at
        found.station_failed(7, 5, "Cartoon Classics")
    assert found.now() == []
    now[0] = 900.0
    found.station_failed(7, 5, "Cartoon Classics")
    [alert] = found.now()
    assert alert.sentence.startswith(
        "Station 5, Cartoon Classics, keeps failing to start: 3 times in the last 10 minutes."
    )
    found.station_failed(7, 5, "Cartoon Classics")  # (still the one alert)
    assert len(found.now()) == 1 and len(told.said) == 1
    found.station_played(7, 5, "Cartoon Classics")
    assert found.now() == []
    assert told.said[-1] == ("Station 5, Cartoon Classics, is playing again.", "station", "fixed")
    for _ in range(3):
        found.station_failed(8, 6, "")
    found.station_gone(8, 6, "")
    assert found.now() == [] and told.said[-1][0] == "Station 6 was deleted, so it no longer fails."
    # Backups: twice in a row.
    found.backup_failed()
    found.backup_made()
    found.backup_failed()
    assert found.now() == []
    found.backup_failed()
    assert [a.kind for a in found.now()] == ["backups"]
    found.backup_made()
    assert found.now() == [] and told.said[-1][1:] == ("backups", "fixed")


def test_whats_on_the_broken_files_tab_is_said_at_most_once_an_hour(db):
    told = Told()
    now = [0.0]
    found = Alerts(told, db, clock=lambda: now[0])  # type: ignore[arg-type]
    found.files([])
    assert found.now() == [] and told.said == []
    tia = (1_000, "report:204", "Tia reported No sound on Northbound S2 E4")
    found.files([tia])
    [alert] = found.now()
    said = (
        "There is 1 file to look at on the Broken files tab: Tia reported No sound on "
        "Northbound S2 E4."
    )
    assert (alert.kind, alert.sentence) == ("files", said)
    assert told.said == [(said, "files", "started")]
    first = alert.id
    # More within the hour: it says what it is now, but it's the same alert.
    now[0] = 1800.0
    found.files([tia, (2_000, "file:205", "StationPlay found Northbound S2 E5 broken")])
    [alert] = found.now()
    assert alert.id == first and len(told.said) == 1
    assert alert.sentence == (
        "There are 2 files to look at on the Broken files tab: StationPlay found Northbound S2 "
        "E5 broken."
    )
    # An hour after it was said, what came since is said: again, with a new
    # ID (the old one isn't said to be fixed).
    five = (2_000, "file:205", "StationPlay found Northbound S2 E5 broken")
    now[0] = 3600.0
    found.files([tia, five])
    [alert] = found.now()
    assert alert.id != first and alert.sentence.endswith("Northbound S2 E5 broken.")
    assert [s[2] for s in told.said] == ["started", "started"]
    assert [a.id for a in found.listed()] == [alert.id]
    second = alert.id
    # Something new that's gone again before it's said is never said.
    sonarr = (3_000, "file:206", "Sonarr couldn't find a file of Northbound S2 E6 that plays")
    now[0] = 4000.0
    found.files([tia, five, sonarr])
    now[0] = 4100.0
    found.files([tia, five])
    now[0] = 7200.0
    found.files([tia, five])
    assert found.now()[0].id == second and len(told.said) == 2
    # Something new more than an hour after it was said: said at once.
    now[0] = 7300.0
    found.files([tia, five, sonarr])
    [alert] = found.now()
    assert alert.id not in (first, second) and alert.sentence.endswith(
        "Sonarr couldn't find a file of Northbound S2 E6 that plays."
    )
    third = alert.id
    # Something new within the hour: said once the hour's up.
    seven = (4_000, "report:207", "Sam reported Wrong language on Northbound S2 E7")
    now[0] = 7400.0
    found.files([tia, five, sonarr, seven])
    assert found.now()[0].id == third and len(told.said) == 3
    now[0] = 7300.0 + 3600
    found.files([tia, five, sonarr, seven])
    [alert] = found.now()
    assert alert.id != third and alert.sentence == (
        "There are 4 files to look at on the Broken files tab: Sam reported Wrong language on "
        "Northbound S2 E7."
    )
    assert [s[2] for s in told.said] == ["started"] * 4
    # Nothing needs an Admin: fixed.
    found.files([])
    assert found.now() == []
    assert told.said[-1] == ("Nothing on the Broken files tab needs you now.", "files", "fixed")


def test_alerts_fixed_more_than_a_day_ago_arent_listed(monkeypatch, db):
    found = Alerts(Told(), db)  # type: ignore[arg-type]
    found.start("plex", "Plex is down.")
    found.fix("plex", "Plex is back.")
    assert len(found.listed()) == 1
    later = int((time.time() + alerts.FIXED_KEPT_S + 60) * 1000)
    monkeypatch.setattr(alerts, "_now_ms", lambda: later)
    assert found.listed() == []


# Kept across restarts ----------------------------------------------------------------------


def as_apps_see(found: Alerts) -> list[dict]:
    return [a.as_dict() for a in found.listed()]


async def test_an_alert_still_going_after_a_restart_isnt_said_again(tmp_path, db, caplog):
    """Its ID, sentence and start stay as they were (so the apps' pill
    doesn't count it as new), the log says it's still going, and it's
    fixed by its check's own rules, said once."""
    caplog.set_level(logging.INFO)
    plex = Plex()
    plex.down = 0
    ctx = checks(tmp_path, plex)
    told = Told()
    before = Alerts(told, db)  # type: ignore[arg-type]
    for _ in range(5):
        await before.look(ctx)
    [going] = as_apps_see(before)
    assert len(told.said) == 1
    # StationPlay starts again.
    told = Told()
    after = Alerts(told, Database(db.path))  # type: ignore[arg-type]
    assert as_apps_see(after) == [going]
    assert f"Alert still going: {going['sentence']}" in caplog.text
    for _ in range(6):  # (still down: never said again)
        await after.look(ctx)
    assert as_apps_see(after) == [going] and told.said == []
    plex.down = None
    await after.look(ctx)
    assert after.now() and told.said == []  # (Plex's 2 checks, as ever)
    await after.look(ctx)
    await after.look(ctx)
    [fixed] = as_apps_see(after)
    assert fixed["id"] == going["id"] and fixed["fixed"] is not None
    assert told.said == [
        ("StationPlay can reach Plex at 192.168.1.10:32400 again.", "plex", "fixed")
    ]


async def test_one_fixed_while_stationplay_was_down_is_said_once_its_check_finds_it(tmp_path, db):
    """The data folder fixed while StationPlay was stopped: said to be
    fixed, once, as soon as its check (2 in a row) finds it. Those that
    can't be checked yet stay as they were: the clock while Plex can't be
    reached, a station until it plays, the outside check while it's still
    checking."""
    told = Told()
    station = db.create_channel(5, "Cartoon Classics", []).id
    before = Alerts(told, db)  # type: ignore[arg-type]
    plex = Plex()
    plex.ahead = 600.0
    ctx = checks(tmp_path, plex, outside=reach.DOWN)
    ctx.settings.data_dir = tmp_path / "gone"
    for _ in range(3):
        await before.look(ctx)
    for _ in range(3):
        before.station_failed(station, 5, "Cartoon Classics")
    assert sorted(a.kind for a in before.now()) == ["clock", "data-write", "outside", "station"]
    ids = {a.kind: a.id for a in before.now()}
    # Back, with the folder there again, Plex away, and the outside check
    # checking afresh.
    told = Told()
    after = Alerts(told, Database(db.path))  # type: ignore[arg-type]
    plex.down = 0
    ctx = checks(tmp_path, plex, outside=reach.CHECKING)
    await after.look(ctx)
    assert {a.kind: a.id for a in after.now()} == ids and told.said == []
    for _ in range(3):
        await after.look(ctx)
    assert {a.kind for a in after.now()} == {"clock", "outside", "station"}
    assert told.said == [("StationPlay can write to its data folder again.", "data-write", "fixed")]
    # Each of the rest, once its check can tell.
    after.station_played(station, 5, "Cartoon Classics")
    plex.down, plex.ahead = None, 5.0
    await after.look(checks(tmp_path, plex, outside=reach.UP))
    await after.look(ctx)
    assert after.now() == []
    assert [(s[1], s[2]) for s in told.said] == [
        ("data-write", "fixed"), ("station", "fixed"), ("outside", "fixed"), ("clock", "fixed")
    ]  # fmt: skip
    assert {a.kind: a.id for a in after.listed()} == ids


def test_the_days_fixed_alerts_are_kept_across_a_restart(db, monkeypatch):
    ticks = itertools.count(int(time.time() * 1000), 1000)
    monkeypatch.setattr(alerts, "_now_ms", lambda: next(ticks))
    found = Alerts(Told(), db)  # type: ignore[arg-type]
    for n in range(3):
        found.start("station", f"Station {n} keeps failing.", str(n))
        found.fix("station", f"Station {n} is playing again.", str(n))
    found.start("backups", "Backups are failing.")
    kept = as_apps_see(found)
    again = Alerts(Told(), Database(db.path))  # type: ignore[arg-type]
    assert as_apps_see(again) == kept and len(kept) == 4
    # (Only as long as the list shows them: a day.)
    later = int((time.time() + alerts.FIXED_KEPT_S + 60) * 1000)
    monkeypatch.setattr(alerts, "_now_ms", lambda: later)
    again = Alerts(Told(), Database(db.path))  # type: ignore[arg-type]
    assert [a["kind"] for a in as_apps_see(again)] == ["backups"]


def test_only_so_many_fixed_alerts_are_kept(db, monkeypatch):
    ticks = itertools.count(int(time.time() * 1000), 1000)
    monkeypatch.setattr(alerts, "_now_ms", lambda: next(ticks))
    monkeypatch.setattr(alerts, "FIXED_MOST", 3)
    found = Alerts(Told(), db)  # type: ignore[arg-type]
    for n in range(5):
        found.start("station", "Failing.", str(n))
        found.fix("station", "Playing.", str(n))
    assert [r["about"] for r in db.kept_alerts()] == ["2", "3", "4"]


async def test_the_database_isnt_written_at_every_check(tmp_path, db):
    """Only when an alert starts, says something new, or is fixed."""
    plex = Plex()
    plex.down = 0
    ctx = checks(tmp_path, plex)
    found = Alerts(Told(), db)  # type: ignore[arg-type]

    def written() -> int:
        return db._conn.total_changes - base

    base = 0
    base = written()
    for _ in range(4):  # (not yet an alert)
        await found.look(ctx)
    assert written() == 0
    await found.look(ctx)
    assert written() == 1  # (it starts)
    for _ in range(10):
        await found.look(ctx)
        found.files([])
        found.station_played(7, 5, "Cartoon Classics")
        found.backup_made()
    assert written() == 1
    plex.down = 401  # (what it says changes)
    await found.look(ctx)
    await found.look(ctx)
    assert written() == 2
    plex.down = None
    for _ in range(5):
        await found.look(ctx)
    assert written() == 3  # (fixed)


def test_whats_on_the_broken_files_tab_after_a_restart(db, monkeypatch):
    """It keeps its ID, and its hour: what came before it was said isn't
    new after a restart, and what came after is said once the hour's up."""
    wall = [1_791_000_000_000]  # (ms: the time of day)
    monkeypatch.setattr(alerts, "_now_ms", lambda: wall[0])
    told = Told()
    before = Alerts(told, db, clock=lambda: 0.0)  # type: ignore[arg-type]
    tia = (wall[0] - 60_000, "report:204", "Tia reported No sound on Northbound S2 E4")
    before.files([tia])
    [first] = before.now()
    # Something new a second later, within the hour, so not said yet; then
    # StationPlay starts again ten seconds later, its clock anew.
    wall[0] += 1_000
    five = (wall[0], "file:205", "StationPlay found Northbound S2 E5 broken")
    before.files([tia, five])
    wall[0] += 10_000
    told = Told()
    clock = [50_000.0]
    after = Alerts(told, Database(db.path), clock=lambda: clock[0])  # type: ignore[arg-type]
    after.files([tia, five])
    assert [a.id for a in after.now()] == [first.id] and told.said == []
    # Its hour runs from when it was said, not from the restart.
    clock[0] += 3600 - 11 - 1
    after.files([tia, five])
    assert [a.id for a in after.now()] == [first.id] and told.said == []
    clock[0] += 1
    after.files([tia, five])
    [again] = after.now()
    assert again.id != first.id and told.said == [(again.sentence, "files", "started")]
    assert [(r["since_ms"], r["fixed_ms"]) for r in db.kept_alerts()] == [(again.since_ms, None)]
    # Nothing new since: never said again, however long ago it was said.
    wall[0] += 2 * 3600_000
    told = Told()
    later = Alerts(told, Database(db.path), clock=lambda: 10**6)  # type: ignore[arg-type]
    later.files([tia, five])
    assert [a.id for a in later.now()] == [again.id] and told.said == []


def test_whats_left_from_before_that_no_longer_applies(db, caplog):
    """A station alert kept for a station that's gone (its deletion said,
    but not kept) is let go; a kind this version doesn't know (a later
    version's, before going back to this one) is left for that version."""
    db.keep_alert("station", "99", 1_000, "Station 9 keeps failing.", None)
    db.keep_alert("gpu", "", 2_000, "The GPU keeps failing.", None)
    found = Alerts(Told(), db)  # type: ignore[arg-type]
    assert found.now() == []
    assert [r["kind"] for r in db.kept_alerts()] == ["gpu"]


def test_when_the_alerts_cant_be_kept_they_go_on(db, monkeypatch, caplog):
    """The database full or read-only: alerts are said as ever, and the log
    says (once) that they couldn't be kept."""
    told = Told()
    found = Alerts(told, db)  # type: ignore[arg-type]

    def full(*_args):
        raise sqlite3.OperationalError("database or disk is full")

    works = db.keep_alert
    monkeypatch.setattr(db, "keep_alert", full)
    found.start("data-full", "Only 300 MB free.")
    found.start("data-full", "Only 200 MB free.")
    found.fix("data-full", "Room again.")
    assert [s[2] for s in told.said] == ["started", "fixed"]
    assert caplog.text.count("Couldn't keep the alerts in the database") == 1
    monkeypatch.setattr(db, "keep_alert", works)
    found.start("backups", "Backups are failing.")
    assert [r["kind"] for r in db.kept_alerts()] == ["backups"]


# For Admins: the apps, the page, the Logs tab ----------------------------------------------


@pytest.fixture
def app(tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "d")
    return create_app(
        settings, PlexClient("http://plex.test", "token", transport=FakePlex().transport())
    )


def test_alerts_are_for_admins(app, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as home:
        ctx = app.state.ctx
        ctx.alerts.start("backups", "StationPlay's backups are failing.")
        # Signing in off, at home: everyone is an Admin.
        assert len(home.get("/api/internal/alerts").json()["alerts"]) == 1
        assert home.post("/api/access/users", json=ADA).status_code == 201
        assert home.post("/api/access/users", json=SAM).status_code == 201
        listed = home.get("/api/internal/alerts")
        assert listed.status_code == 200 and listed.headers["stationplay-api"] == "1"
        [alert] = listed.json()["alerts"]
        assert set(alert) == {"id", "kind", "sentence", "since", "fixed"}
        assert home.get("/api/status").json()["alerts"] == [alert]
        sam = TestClient(app)
        signed = sam.post("/api/internal/sign-in", json=SAM).json()
        refused = sam.get(
            "/api/internal/alerts", headers={"Authorization": f"Bearer {signed['token']}"}
        )
        assert refused.status_code == 403
        assert sam.get("/api/internal/alerts").status_code == 401  # (no sign-in)
        sam.post("/api/access/sign-in", json=SAM)
        assert "alerts" not in sam.get("/api/status").json()  # (the page, as a User)
        # The page's backups: failing twice is an alert; one made fixes it.
        ctx.alerts.fix("backups", "Backups are working again.")

        def broken(ctx):
            raise OSError(28, "No space left on device")

        works = backups.make_backup
        monkeypatch.setattr(backups, "make_backup", broken)
        for _ in range(2):
            with pytest.raises(OSError):
                home.post("/api/backups")
        assert [a["kind"] for a in home.get("/api/status").json()["alerts"]] == ["backups"]
        monkeypatch.setattr(backups, "make_backup", works)
        assert home.post("/api/backups").status_code == 201
        assert home.get("/api/status").json()["alerts"] == []
        lines = home.get("/api/logs").json()["text"]
        assert "Alert: StationPlay's backups are failing: the last 2 tries didn't work." in lines
        assert "Alert fixed: StationPlay made a backup again." in lines


def test_after_a_restart_the_apps_and_the_page_see_the_same_alerts(app, tmp_path, monkeypatch):
    """StationPlay stopped and started again: the same alerts, with the same
    IDs, for the apps and the page's header; none sent anywhere again; and
    the Logs tab says which are still going."""
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(notify.Notify, "send", lambda self, *said: sent.append(said))
    with TestClient(app) as home:
        ctx = app.state.ctx
        home.portal.call(ctx.alerts.start, "backups", "StationPlay's backups are failing.")
        home.portal.call(ctx.alerts.start, "plex", "StationPlay can't reach Plex.")
        home.portal.call(ctx.alerts.fix, "plex", "StationPlay can reach Plex again.")
        before = home.get("/api/internal/alerts").json()["alerts"]
        header = home.get("/api/status").json()["alerts"]
    assert len(before) == 2 and len(sent) == 3
    restarted = time.time()
    again = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "d"),
        PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
    )
    with TestClient(again) as home:
        assert home.get("/api/internal/alerts").json()["alerts"] == before
        assert home.get("/api/status").json()["alerts"] == header
        logged = home.get("/api/logs").json()["entries"]
        assert [
            e["message"] for e in logged if e["time"] >= restarted and "Alert" in e["message"]
        ] == ["Alert still going: StationPlay's backups are failing."]
    assert len(sent) == 3


# Notifying a web address -----------------------------------------------------------------------


class Address:
    """Stands in for the web address: what it was sent, and how it answers."""

    def __init__(self, answer: int = 200, wait_s: float = 0.0, location: str = "") -> None:
        self.answer, self.wait_s, self.location = answer, wait_s, location
        self.asked: list[httpx.Request] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        await asyncio.sleep(self.wait_s)
        headers = {"Location": self.location} if self.location else {}
        return httpx.Response(self.answer, headers=headers, content=b"what it says" * 1000)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


def notifier(tmp_path, address: Address) -> Notify:
    found = Notify(Database(tmp_path / "db.sqlite"))
    found.transport = address.transport
    return found


async def test_plain_text_and_json(tmp_path):
    address = Address()
    sender = notifier(tmp_path, address)
    url = "https://ntfy.example.com/stationplay-xyz?auth=secret"
    sent = await sender.post(url, notify.TEXT, "StationPlay can't reach Plex.", "plex", "started")
    assert (sent.ok, sent.status) == (True, "200 OK")
    [asked] = address.asked
    assert (str(asked.url), asked.method, asked.content) == (
        url,
        "POST",
        b"StationPlay can't reach Plex.",
    )
    assert asked.headers["title"] == "StationPlay"
    assert asked.headers["content-type"] == "text/plain; charset=utf-8"
    sent = await sender.post(url, notify.JSON, "Plex is back.", "plex", "fixed")
    assert json.loads(address.asked[1].content) == {
        "title": "StationPlay", "message": "Plex is back.", "kind": "plex", "state": "fixed"
    }  # fmt: skip
    assert address.asked[1].headers["content-type"] == "application/json"
    assert sender.last == sent  # (kept for the page: its status, nothing of the answer)


async def test_no_answer_in_time_one_more_try_and_no_redirects(tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "WAIT_S", 0.2)
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    slow = Address(wait_s=1.0)
    sent = await notifier(tmp_path, slow).post(
        "http://ha.local/hook", notify.JSON, "x", "plex", "started"
    )
    assert (sent.ok, sent.status, len(slow.asked)) == (False, "no answer within 0.2 seconds", 2)
    elsewhere = Address(answer=302, location="https://elsewhere.example.com/")
    sent = await notifier(tmp_path, elsewhere).post(
        "https://ntfy.example.com/t", notify.TEXT, "x", "plex", "started"
    )
    assert not sent.ok and "a redirect, which StationPlay doesn't follow" in sent.status
    assert [r.url.host for r in elsewhere.asked] == ["ntfy.example.com"] * 2
    failing = Address(answer=500)
    sent = await notifier(tmp_path, failing).post(
        "https://g.example.com/m", notify.JSON, "x", "k", "fixed"
    )
    assert (sent.ok, sent.status, len(failing.asked)) == (False, "500 Internal Server Error", 2)


def test_only_http_and_https():
    for url in (
        "ftp://ntfy.example.com/x", "file:///etc/passwd", "javascript:alert(1)", "gopher://x",
        "//ntfy.example.com/x", "ntfy.example.com/x", "http://", "https:///x", "http://exa mple.com",
        "https://exam\nple.com/", "https://example.com/" + "x" * 500, "",
    ):  # fmt: skip
        with pytest.raises(ValueError, match="starts with http:// or https://"):
            notify.check_address(url)
    assert notify.check_address(" https://ntfy.sh/topic ") == "https://ntfy.sh/topic"
    assert notify.shown("https://user:pw@ha.example.com:8123/api/webhook/abc?x=1") == (
        "https://ha.example.com:8123"
    )


def test_notify_on_the_page(app, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(notify, "WAIT_S", 0.5)
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    address = Address()
    url = "https://ntfy.example.com/stationplay-secret-topic"
    with TestClient(app) as home:
        ctx = app.state.ctx
        ctx.notify.transport = address.transport
        start = home.get("/api/notify").json()
        assert start == {"on": False, "url": "", "format": "text", "last": None}
        for bad in ({"on": True, "url": ""}, {"on": True, "url": "ftp://x.example.com"},
                    {"on": False, "url": "file:///etc/passwd"},
                    {"on": True, "url": url, "format": "xml"}):  # fmt: skip
            refused = home.put("/api/notify", json=bad)
            assert refused.status_code == 400, bad
        saved = home.put("/api/notify", json={"on": True, "url": url, "format": "json"})
        assert saved.json()["on"] and saved.json()["url"] == url
        tested = home.post("/api/notify/test", json={"url": url, "format": "json"}).json()
        assert tested["sent"]["ok"] and tested["last"]["test"]
        assert json.loads(address.asked[0].content)["kind"] == "test"
        # An alert starting goes there, in the background.
        home.portal.call(ctx.alerts.start, "plex", "StationPlay can't reach Plex.")
        for _ in range(50):
            if len(address.asked) == 2:
                break
            time.sleep(0.05)
        assert json.loads(address.asked[1].content)["state"] == "started"
        # Only an Admin sees it, or changes it.
        assert home.post("/api/access/users", json=ADA).status_code == 201
        assert home.post("/api/access/users", json=SAM).status_code == 201
        sam = TestClient(app)
        sam.post("/api/access/sign-in", json=SAM)
        assert sam.get("/api/notify").status_code == 403
        assert sam.put("/api/notify", json={"on": False}).status_code == 403
        assert sam.post("/api/notify/test", json={"url": url}).status_code == 403
        assert TestClient(app).get("/api/notify").status_code == 401
        # The log never has the address whole: only its host.
        logs = home.get("/api/logs").json()["text"]
        assert "https://ntfy.example.com" in logs and "secret-topic" not in logs


def test_a_failing_web_address_holds_nothing_up(app, monkeypatch):
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)

    async def hangs(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)
        return httpx.Response(200)

    def breaks(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("something odd")

    with TestClient(app) as home:
        ctx = app.state.ctx
        home.put("/api/notify", json={"on": True, "url": "https://hook.example.com/x"})
        many = notify.WAITING_MOST + 5  # (more than may wait: some are left out)
        for round_, transport in enumerate(
            (httpx.MockTransport(breaks), httpx.MockTransport(hangs))
        ):
            ctx.notify.transport = transport
            began = time.monotonic()
            for n in range(many):
                home.portal.call(
                    ctx.alerts.start, "station", f"Station {n} keeps failing.", f"{round_}{n}"
                )
            assert home.get("/api/internal/alerts").status_code == 200
            assert home.get("/api/status").status_code == 200
            assert time.monotonic() - began < 2
        assert len(ctx.alerts.now()) == 2 * many
