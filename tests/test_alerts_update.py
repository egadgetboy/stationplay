"""A station's alert and an update (1.37.1, the owner, October 15: INFO's
"keeps failing to start: 3 times in the last 10 minutes", kept from 1.36.3,
where INFO couldn't find its film, was still said after the update to
1.37.0, which plays it). Kept from before an update, a station's alert ends,
said once; a real failure raises it again. Its sentence says when it began,
and INFO's never points to Plex or the files."""

from __future__ import annotations

import re

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
