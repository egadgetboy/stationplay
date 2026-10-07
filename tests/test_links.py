"""Signing in an app with a code (see links.py): codes are hard to guess,
work once, run out, and can't be asked for or guessed at without end."""

from __future__ import annotations

import pytest

from app import links
from app.db import User

PAT = User(id=1, name="Pat", role="admin", created_ms=0, signed_in_ms=0, max_stations=None)


def test_a_code_works_once_and_runs_out(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(links.time, "monotonic", lambda: clock[0])
    found = links.Links()
    code, poll = found.start("StationPlay for Roku on Den Roku", "192.168.1.30")
    assert len(code) == 9 and code[4] == "-"
    assert not set(code.replace("-", "")) & set("01IO")
    pending = found.find(code.lower(), PAT)
    assert pending.app == "StationPlay for Roku on Den Roku"
    assert found.check(poll) is pending and pending.token is None  # (waiting)
    found.link(pending, PAT, "the-token")
    with pytest.raises(LookupError):
        found.find(code, PAT)  # (linked: not again)
    assert found.check(poll).token == "the-token"
    assert found.check(poll) is None  # (handed over once)
    # Codes run out.
    code, poll = found.start("An app", "192.168.1.30")
    clock[0] += links.LINK_S + 1
    assert found.check(poll) is None
    with pytest.raises(LookupError):
        found.find(code, PAT)


def test_codes_cant_be_asked_for_or_guessed_without_end(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(links.time, "monotonic", lambda: clock[0])
    found = links.Links()
    for _ in range(links.STARTS):
        found.start("An app", "203.0.113.9")
    with pytest.raises(links.Refused):
        found.start("An app", "203.0.113.9")
    found.start("An app", "198.51.100.4")  # (another address)
    for _ in range(links.WRONG_CODES):
        with pytest.raises(LookupError):
            found.find("AAAA-AAAA", PAT)
    code, _poll = found.start("An app", "198.51.100.5")
    with pytest.raises(links.Refused):
        found.find(code, PAT)  # (even the right one, for a while)
    clock[0] += links.TRIES_WINDOW_S + 1
    assert found.find(found.start("An app", "198.51.100.5")[0], PAT)
