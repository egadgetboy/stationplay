"""How many devices may watch through StationPlay's apps at once, and the
connection tests the apps run (capacity.py)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import capacity
from app.capacity import Capacity, ConnectionTest, Limits
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

DAY_MS = 86_400_000


@pytest.fixture
def cap(tmp_path):
    return Capacity(Database(tmp_path / "db.sqlite"))


def test_limits_are_kept_and_checked(cap, tmp_path):
    assert cap.limits == Limits(0, 0)
    assert cap.save(5, 2) == Limits(5, 2)
    assert Capacity(cap.db).limits == Limits(5, 2)  # (kept)
    for devices, away in ((-1, 0), (0, capacity.MOST + 1), (3, 4)):
        with pytest.raises(ValueError):
            cap.save(devices, away)
    assert cap.save(0, 3) == Limits(0, 3)  # (away alone is fine)
    assert cap.limits == Limits(0, 3)


def test_one_more_device_is_turned_away(cap):
    cap.save(2, 1)
    # Below the limits: anyone may start.
    assert cap.refusal({}, "10.0.0.5", away=False) is None
    assert cap.refusal({"10.0.0.5": False}, "phone", away=True) is None
    # At the limit in all: one more is turned away; a device already
    # watching (changing station) isn't.
    watching = {"10.0.0.5": False, "phone": True}
    assert cap.refusal(watching, "10.0.0.6", away=False) == ("devices", 2)
    assert cap.refusal(watching, "phone", away=True) is None
    assert cap.refusal(watching, "10.0.0.5", away=False) is None
    # At the limit away from home: one more away is turned away, one at home isn't.
    cap.save(5, 1)
    assert cap.refusal(watching, "tablet", away=True) == ("away", 1)
    assert cap.refusal(watching, "10.0.0.6", away=False) is None
    cap.save(0, 0)
    assert cap.refusal({f"d{n}": True for n in range(50)}, "more", away=True) is None


def test_what_someone_over_a_limit_is_told():
    assert capacity.refused_because("devices", 5) == (
        "An Admin has limited StationPlay to 5 devices watching at once, so it runs smoothly "
        "for everyone. Please try again later."
    )
    assert "to 1 device watching away from home at once" in capacity.refused_because("away", 1)


def test_connection_tests_and_what_they_have_room_for(cap):
    now = 100 * DAY_MS
    cap.record("away", 18.44, "StationPlay for Android on Pixel", "Pat", now - 3 * DAY_MS)
    cap.record("away", 9.0, "StationPlay for Android on Pixel", "Pat", now)
    cap.record("home", 240.0, "StationPlay for Android TV on Den", "", now)
    cap.record("away", 400.0, "Old phone", "Sam", now - (capacity.TEST_DAYS + 1) * DAY_MS)
    # The fastest recent test counts (the slow one ran while the connection was busy).
    best = cap.best("away", now)
    assert best is not None and best.mbps == 18.4 and best.user == "Pat"
    assert cap.best("home", now).mbps == 240.0
    assert capacity.room(best, 3.9) == 3  # (18.4 x 0.7 / 3.9)
    assert capacity.room(ConnectionTest("away", 2.0, now, "", ""), 3.9) == 0
    assert [t.mbps for t in cap.tests()][:3] == [400.0, 240.0, 9.0]  # newest first
    assert len(Capacity(cap.db).tests()) == 4  # (kept)
    for where, mbps in (("moon", 5.0), ("home", 0.0), ("home", capacity.FASTEST_MBPS * 2)):
        with pytest.raises(ValueError):
            cap.record(where, mbps, "", "", now)
    for n in range(capacity.TESTS_KEPT + 3):
        cap.record("home", 50.0 + n, "", "", now)
    assert len(cap.tests()) == capacity.TESTS_KEPT


def test_one_test_from_an_address_at_a_time(cap):
    assert cap.may_test("10.0.0.5", now=100.0)
    assert not cap.may_test("10.0.0.5", now=101.0)
    assert cap.may_test("10.0.0.6", now=101.0)
    assert cap.may_test("10.0.0.5", now=100.0 + capacity.TEST_EVERY_S)


def test_what_one_device_watching_takes(tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="t", data_dir=tmp_path)
    station = lambda picture: SimpleNamespace(picture=picture)  # noqa: E731
    # (The biggest picture the stations use: 1080p is 6 Mbps of picture, plus sound.)
    assert capacity.stream_mbps(settings, [station("480p"), station("1080p")]) == (6.7, "1080p")
    assert capacity.stream_mbps(settings, [station("720p")])[1] == "720p"
    assert capacity.stream_mbps(settings, []) == capacity.stream_mbps(settings, [station("720p")])


@pytest.fixture
def client(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    for n in range(1, 4):
        fp.add_episode(f"20{n}", "100", 1, n, f"Ep {n}", f"/x/{n}.mkv", 22 * 60_000)
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    with TestClient(app) as client:
        made = client.post(
            "/api/channels",
            json={"number": 5, "name": "Five", "sources": [{"type": "show", "ratingKey": "100"}]},
        )
        assert made.status_code == 201, made.text
        yield client


def test_an_app_over_the_limit_is_told_why(client):
    ctx = client.app.state.ctx
    assert client.put("/api/app-limits", json={"devices": 1, "away": 0}).status_code == 200
    # Someone else is watching, so this one is the device too many (and no
    # station is started for it).
    ctx.hls_streams.watchers = lambda: {"10.0.0.9": False}
    refused = client.get("/hls/5/index.m3u8")
    assert refused.status_code == 503
    assert refused.json() == {
        "detail": capacity.refused_because("devices", 1),
        "limit": "devices",
        "most": 1,
    }
    assert refused.headers["access-control-allow-origin"] == "*"
    assert ctx.hls_streams.get(ctx.db.get_channel_by_number(5).id) is None
    log = client.get("/api/logs").json()["text"]
    assert (
        "The limit of 1 device watching at once (set on the Access tab) was reached, "
        "so an app on testclient couldn't tune to station 5" in log
    )


def test_the_access_tab_sets_the_limits_and_shows_the_tests(client, caplog):
    caplog.set_level(logging.INFO)
    got = client.get("/api/app-limits").json()
    assert (got["devices"], got["away"], got["most"]) == (0, 0, capacity.MOST)
    assert got["room"] == {"home": None, "away": None} and got["tests"] == []
    assert got["watching"] == {"devices": 0, "away": 0}
    assert (got["eachMbps"], got["picture"]) == (4.0, "720p")
    bad = client.put("/api/app-limits", json={"devices": 2, "away": 3})
    assert bad.status_code == 400 and "can't be higher" in bad.json()["detail"]
    saved = client.put("/api/app-limits", json={"devices": 6, "away": 2}).json()
    assert (saved["devices"], saved["away"]) == (6, 2)
    assert "at once in StationPlay's apps: 6; away from home: 2" in caplog.text

    # A connection test: the data, then what the app found.
    data = client.get("/api/internal/speed-test?mb=3")
    assert data.status_code == 200 and len(data.content) == 3 << 20
    assert data.headers["content-length"] == str(3 << 20)
    assert data.headers["stationplay-api"] == "1"
    again = client.get("/api/internal/speed-test")
    assert again.status_code == 429 and "just ran" in again.json()["detail"]
    for mb in ("0", "65", "lots"):
        assert client.get(f"/api/internal/speed-test?mb={mb}").status_code == 400
    found = client.post(
        "/api/internal/speed-test",
        json={"mbps": 87.5, "app": "StationPlay for Android", "deviceName": "Pixel"},
    )
    assert found.json() == {"mbps": 87.5, "where": "home", "eachMbps": 4.0, "room": 15}
    assert client.post("/api/internal/speed-test", json={"mbps": -1}).status_code == 400
    got = client.get("/api/app-limits").json()
    [test] = got["tests"]
    assert (test["where"], test["device"], test["mbps"]) == (
        "home",
        "StationPlay for Android on Pixel",
        87.5,
    )
    assert got["room"]["home"]["devices"] == 15 and got["room"]["away"] is None
