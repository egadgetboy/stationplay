"""A station's alert and an update (1.37.1, the owner, October 15: INFO's
"keeps failing to start: 3 times in the last 10 minutes", kept from 1.36.3,
where INFO couldn't find its film, was still said after the update to
1.37.0, which plays it). Kept from before an update, a station's alert ends,
said once; a real failure raises it again. Its sentence says when it began,
and INFO's never points to Plex or the files."""

from __future__ import annotations

import re
import time

import pytest

from app import __version__, infostation, releases
from app.alerts import Alerts
from app.db import Database

from .test_alerts import Told


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(tmp_path / "kept.db")


def info_failing(db: Database) -> tuple[int, Alerts, Told]:
    info = db.create_channel(infostation.NUMBER, infostation.NAME, [{"type": "info"}])
    told = Told()
    now = [0.0]
    found = Alerts(told, db, clock=lambda: now[0])  # type: ignore[arg-type]
    for at in (0.0, 60.0, 120.0):
        now[0] = at
        found.station_failed(info.id, info.number, info.name)
    assert len(found.now()) == 1
    return info.id, found, told


def test_a_stations_alert_from_before_an_update_ends_with_it(db):
    db.set_meta(releases.VERSION_META, "1.36.3")
    info, _, _ = info_failing(db)
    told = Told()
    again = Alerts(told, db)  # type: ignore[arg-type]
    assert again.now() == []
    [fixed] = [a for a in again.listed() if a.about == str(info)]
    assert fixed.fixed_sentence == (
        f"Station 99, INFO: its alert from before the update to {__version__} was cleared. "
        "It comes back if INFO fails again."
    )


def test_started_again_as_the_same_version_it_goes_on(db):
    db.set_meta(releases.VERSION_META, __version__)
    info_failing(db)
    again = Alerts(Told(), db)  # type: ignore[arg-type]
    assert [a.kind for a in again.now()] == ["station"]


def test_a_fresh_failure_after_the_update_raises_it_again_counting_afresh(db):
    db.set_meta(releases.VERSION_META, "1.36.3")
    info, _, _ = info_failing(db)
    now = [5_000.0]
    again = Alerts(Told(), db, clock=lambda: now[0])  # type: ignore[arg-type]
    for _ in range(2):
        again.station_failed(info, 99, "INFO")
    assert again.now() == []
    again.station_failed(info, 99, "INFO")
    [alert] = again.now()
    assert " 3 times in 10 minutes, from " in alert.sentence


def test_infos_alert_never_points_to_plex_or_the_files(db):
    _, found, _ = info_failing(db)
    [alert] = found.now()
    assert re.fullmatch(
        r"Station 99, INFO, keeps failing to start: 3 times in 10 minutes, from "
        r"\d{1,2}:\d\d [AP]M\. INFO's film is part of tapiOca, so Plex and your files "
        r"aren't the cause\. The Logs tab says why\.",
        alert.sentence,
    ), alert.sentence


def test_a_plex_stations_alert_says_when_it_began(db):
    channel = db.create_channel(5, "Cartoon Classics", [{"type": "show", "ratingKey": "1"}])
    now = [0.0]
    found = Alerts(Told(), db, clock=lambda: now[0])  # type: ignore[arg-type]
    for at in (0.0, 60.0, 120.0):
        now[0] = at
        found.station_failed(channel.id, 5, "Cartoon Classics")
    [alert] = found.now()
    assert re.fullmatch(
        r"Station 5, Cartoon Classics, keeps failing to start: 3 times in 10 minutes, from "
        r"\d{1,2}:\d\d [AP]M\. The Logs tab says why each time; check that Plex and the "
        r"station's files can be reached\.",
        alert.sentence,
    ), alert.sentence


def test_from_says_when_the_failures_began_not_the_oldest_of_the_last_ten_minutes(db, monkeypatch):
    """(The cold audit of 1.37.1: failing every minute for an hour from 6:38
    AM, the alert said "from 7:27 AM", moving on with each failure.)"""
    from app import alerts

    channel = db.create_channel(5, "Cartoon Classics", [{"type": "show", "ratingKey": "1"}])
    # (Long ago, so its log lines never pass for any other test's.)
    began = time.mktime((2020, 1, 6, 6, 38, 0, 0, 0, -1))
    now = [0.0]
    monkeypatch.setattr(alerts.time, "time", lambda: began + now[0])
    found = Alerts(Told(), db, clock=lambda: now[0])  # type: ignore[arg-type]
    for minute in range(60):
        now[0] = minute * 60.0
        found.station_failed(channel.id, 5, "Cartoon Classics")
    [alert] = found.now()
    assert " times in 10 minutes, from 6:38 AM." in alert.sentence, alert.sentence
    # Fine for longer than the window, then failing again: a new run, from then.
    found.station_played(channel.id, 5, "Cartoon Classics")
    for minute in range(3):
        now[0] = 7200.0 + minute * 60
        found.station_failed(channel.id, 5, "Cartoon Classics")
    [alert] = found.now()
    assert " 3 times in 10 minutes, from 8:38 AM." in alert.sentence, alert.sentence


def test_going_back_to_an_earlier_version_says_so(db):
    """(The cold audit of 1.37.1: started after a later version, the alert
    said it was cleared "before the update to" this one.)"""
    db.set_meta(releases.VERSION_META, "99.0.0")
    info, _, _ = info_failing(db)
    again = Alerts(Told(), db)  # type: ignore[arg-type]
    [fixed] = [a for a in again.listed() if a.about == str(info)]
    assert fixed.fixed_sentence == (
        f"Station 99, INFO: its alert from before going back to {__version__} was cleared. "
        "It comes back if INFO fails again."
    )
