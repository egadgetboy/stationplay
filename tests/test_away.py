"""Watching away from home in StationPlay's apps (see away.py): the setting,
and the outside address it keeps. Playing through the public port is in
test_hls.py."""

from __future__ import annotations

import pytest

from app.away import Away, normalize_address
from app.db import Database


@pytest.mark.parametrize(
    ("typed", "kept"),
    [
        ("https://tv.example.com", "https://tv.example.com"),
        (" HTTPS://TV.example.com/ ", "https://tv.example.com"),
        ("http://nas.tailnet.ts.net:3310", "http://nas.tailnet.ts.net:3310"),
        ("http://100.101.102.103:3310/", "http://100.101.102.103:3310"),
        ("https://[fd7a:115c::1]:8443", "https://[fd7a:115c::1]:8443"),
    ],
)
def test_the_outside_address_as_typed(typed, kept):
    assert normalize_address(typed) == kept


@pytest.mark.parametrize(
    "typed",
    ["", "tv.example.com", "ftp://tv.example.com", "https://", "https://tv.example.com/stationplay",
     "https://user:pw@tv.example.com", "https://tv.example.com?x=1", "https://tv.example.com:99999",
     "https://tv example.com", "https://" + "a" * 200 + ".com"],
)  # fmt: skip
def test_what_isnt_an_address(typed):
    with pytest.raises(ValueError, match="https://"):
        normalize_address(typed)


class NoSignIns:
    """Access, as far as Away asks it: nobody's signed in."""

    def session_user_hashed(self, hashed: str):
        return None

    def record(self, level: int, message: str) -> None:
        pass


def test_off_until_its_turned_on_and_kept(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    away = Away(db, NoSignIns())  # type: ignore[arg-type]
    assert not away.on and away.address == ""
    with pytest.raises(ValueError):
        away.save(True, "")  # (on needs an address)
    away.save(True, "https://tv.example.com/")
    again = Away(db, NoSignIns())  # type: ignore[arg-type]
    assert again.on and again.address == "https://tv.example.com"
    again.save(False, "https://tv.example.com")
    assert not Away(db, NoSignIns()).on  # type: ignore[arg-type]
    # Off, no app gets a key; a key whose sign-in has ended is no one's.
    assert again.key_for("hash", object()) is None  # type: ignore[arg-type]
    again.save(True, "https://tv.example.com")
    key = again.key_for("hash", object())  # type: ignore[arg-type]
    assert key and again.key_for("hash", object()) == key  # type: ignore[arg-type]
    assert again.user_of(key, recheck=True) is None
    assert again.apps == 0
