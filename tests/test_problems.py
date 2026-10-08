"""Problems the apps send as they happen (see problems.py): kept for the Logs
tab, counted when the same one comes again, and summed up so an Admin can
tell whether a problem is one kind of device's or everyone's."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app import problems
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

ADA = {"name": "Ada", "password": "correct horse"}
ROKU = {
    "app": "StationPlay for Roku",
    "version": "0.5.0",
    "device": "Roku Ultra 4850X, Roku OS 14.0",
}
PHONE = {"app": "StationPlay for Android", "version": "0.9.0", "device": "Pixel 8, Android 15"}


@pytest.fixture
def app(tmp_path):
    fp = FakePlex()
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    return create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))


def test_problems_from_one_kind_of_device_and_from_everyone(app, caplog):
    with TestClient(app) as tv:
        caplog.set_level(logging.WARNING, logger="stationplay.problems")
        assert "problems" in tv.get("/api/v1/server").json()["features"]
        for name in ("Den", "Bedroom"):
            for _ in range(2):  # (the second counts on the first's row)
                sent = tv.post(
                    "/api/internal/problem",
                    json={"kind": "station-stopped", "station": 5, "detail": "decoder error",
                          **ROKU, "deviceName": name},
                )  # fmt: skip
                assert sent.status_code == 200, sent.text
        for device in (ROKU, PHONE):
            tv.post(
                "/api/internal/problem",
                json={"kind": "library-failed", "title": "Northbound", "detail": "HTTP 500",
                      **device, "deviceName": "x"},
            )  # fmt: skip
        said = [r.getMessage() for r in caplog.records]
        assert (
            said.count(
                "Problem in StationPlay for Roku 0.5.0 on Roku Ultra 4850X, Roku OS 14.0 (Den): "
                "Station 5 stopped playing: decoder error"
            )
            == 1
        )  # (once, though it came twice)

        summary = tv.get("/api/problems?days=7").json()
        by_label = {p["label"]: p for p in summary["problems"]}
        stopped = by_label["Station 5 stopped playing"]
        assert (stopped["times"], stopped["devices"], stopped["only"]) == (4, 2, True)
        assert stopped["on"] == [
            {"device": "StationPlay for Roku 0.5.0 on Roku Ultra 4850X, Roku OS 14.0", "times": 4}
        ]
        assert stopped["details"] == ["decoder error"]
        failed = by_label["Northbound didn't play"]
        assert (failed["times"], failed["devices"], failed["only"]) == (2, 2, False)

        assert tv.delete("/api/problems").status_code == 204
        assert tv.get("/api/problems").json()["problems"] == []


def test_what_isnt_taken(app):
    with TestClient(app) as tv:
        assert tv.post("/api/internal/problem", json={"kind": "boredom"}).status_code == 400
        assert (
            tv.post(
                "/api/internal/problem", json={"kind": "station-failed", "station": -1}
            ).status_code
            == 400
        )
        for _ in range(problems.MOST):
            assert (
                tv.post(
                    "/api/internal/problem", json={"kind": "crashed", **PHONE, "deviceName": "Pat"}
                ).status_code
                == 200
            )
        too_many = tv.post(
            "/api/internal/problem", json={"kind": "crashed", **PHONE, "deviceName": "Pat"}
        )
        assert too_many.status_code == 429
        crashes = tv.get("/api/problems").json()["problems"]
        assert [(p["label"], p["times"]) for p in crashes] == [
            ("The app closed unexpectedly", problems.MOST)
        ]


def test_only_admins_see_them(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        admin.post(
            "/api/access/users", json={"name": "Bo", "password": "bo password", "role": "user"}
        )
        bo = TestClient(app)
        assert (
            bo.post(
                "/api/access/sign-in", json={"name": "Bo", "password": "bo password"}
            ).status_code
            == 200
        )
        # A signed-in User's app may send one; only an Admin reads them.
        assert (
            bo.post("/api/internal/problem", json={"kind": "crashed", **PHONE}).status_code == 200
        )
        assert bo.get("/api/problems").status_code == 403
        assert (
            TestClient(app).post("/api/internal/problem", json={"kind": "crashed"}).status_code
            == 401
        )
        signed = admin.post("/api/access/sign-in", json=ADA)
        assert signed.status_code == 200
        [crash] = admin.get("/api/problems").json()["problems"]
        assert crash["people"] == ["Bo"]
