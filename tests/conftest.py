"""Fixtures shared between test files."""

import pytest

from app import db, jobs, scanner

from .test_e2e import media  # noqa: F401  (the test media files the end-to-end tests play)


@pytest.fixture(autouse=True)
def no_background_scans(monkeypatch):
    """Checking files in the background would get in the way of other tests;
    the scanner's own tests run it by hand, and the tests of checking a new
    station's files turn that on."""
    monkeypatch.setattr(scanner, "STARTUP_DELAY_S", 10**6)
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", False)


@pytest.fixture(autouse=True)
def daytime(monkeypatch):
    """The tests run outside the overnight checks' hours, whatever the time
    is where they run (a test of those hours passes the time it means, and
    the tests of the overnight checks say when it's night)."""
    real = scanner.Scanner.in_window
    monkeypatch.setattr(
        scanner.Scanner, "in_window", lambda self, now=None: now is not None and real(self, now)
    )


@pytest.fixture(autouse=True)
def plain_new_stations(monkeypatch):
    """New stations start plain in tests (no Intro Bumper, nothing in the
    corner, no Up Next Banner, episode order), so streams start with their
    programs and nothing is drawn over them; the tests of those features
    turn them on, and test_intro checks what new stations really start with."""
    for setting, value in (
        ("intro_seconds", 0),
        ("watermark", "off"),
        ("up_next_seconds", 0),
        ("order_mode", "rotate"),
    ):
        monkeypatch.setitem(db.NEW_STATION, setting, value)
