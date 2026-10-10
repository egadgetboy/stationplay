"""Problems the apps send as they happen (see problems.py): kept for the Logs
tab, counted when the same one comes again, and summed up so an Admin can
tell whether a problem is one kind of device's or everyone's."""

from __future__ import annotations

import logging
import time

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


# From 1.29.1: when each happened, the app's journal, trouble reaching
# StationPlay, and what error codes mean ------------------------------------------


def sent(client: TestClient, **fields):
    answer = client.post("/api/internal/problem", json={**PHONE, "deviceName": "Den", **fields})
    assert answer.status_code == 200, answer.text
    return answer


def test_problems_sent_later_go_by_when_they_happened(app, caplog):
    caplog.set_level(logging.WARNING, logger="stationplay.problems")
    now = int(time.time() * 1000)
    with TestClient(app) as tv:
        sent(tv, kind="library-failed", title="Older", at=now - 3 * 3_600_000)
        sent(tv, kind="library-failed", title="Newest", at=now - 60_000)
        sent(tv, kind="library-failed", title="A week and more", at=now - 8 * 86_400_000)
        sent(tv, kind="library-failed", title="Ahead", at=now + 10 * 60_000)
        sent(tv, kind="library-failed", title="Slightly ahead", at=now + 2 * 60_000)
        rows = {p["title"]: p for p in tv.get("/api/problems").json()["problems"]}
        assert abs(rows["Older"]["lastMs"] - (now - 3 * 3_600_000)) < 1000
        # (Too old, or too far ahead: when it came.)
        for title in ("A week and more", "Ahead"):
            assert abs(rows[title]["lastMs"] - now) < 5_000, title
        assert rows["Slightly ahead"]["lastMs"] == now + 2 * 60_000
        order = [p["title"] for p in tv.get("/api/problems").json()["problems"]]
        assert order.index("Newest") < order.index("Older")
        assert "Problem in StationPlay for Android 0.9.0 on Pixel 8, Android 15 (Den): Older " \
               "didn't play (3 hours ago)" in caplog.text  # fmt: skip
        # The same one again within 10 minutes of when it happened counts on its row,
        # whenever it's sent; further apart, it's another.
        sent(tv, kind="library-failed", title="Older", at=now - 3 * 3_600_000 - 5 * 60_000)
        sent(tv, kind="library-failed", title="Older", at=now - 5 * 3_600_000)
        older = [p for p in tv.get("/api/problems").json()["problems"] if p["title"] == "Older"]
        assert [p["times"] for p in older] == [3]  # (grouped: two rows)
        assert older[0]["firstMs"] == now - 5 * 3_600_000


def test_a_flood_of_old_problems_never_pushes_out_newer_ones(app, monkeypatch):
    monkeypatch.setattr(problems, "KEEP", 5)
    monkeypatch.setattr(problems, "MOST", 1000)
    now = int(time.time() * 1000)
    with TestClient(app) as tv:
        for n in range(3):
            sent(tv, kind="library-failed", title=f"New {n}", at=now - n * 1000)
        for n in range(20):
            sent(tv, kind="crashed", detail=f"old {n}", at=now - 86_400_000 - n * 60 * 60_000)
        titles = [p["title"] for p in tv.get("/api/problems").json()["problems"]]
        assert {"New 0", "New 1", "New 2"} <= set(titles)
        crashed = [p for p in tv.get("/api/problems").json()["problems"] if p["kind"] == "crashed"]
        assert [p["details"] for p in crashed] == [["old 0", "old 1"]]  # (the newest two)


def test_the_journal_before_a_problem(app, monkeypatch):
    with TestClient(app) as tv:
        tv.post("/api/access/users", json=ADA)
        tv.post("/api/access/sign-in", json=ADA)
        lines = [f"line {n}: <script>alert({n})</script>\tend" for n in range(400)]
        sent(tv, kind="library-stopped", title="Northbound", journal="\n".join(lines),
             detail="ERROR_CODE_DECODING_FAILED")  # fmt: skip
        [row] = tv.get("/api/problems").json()["problems"]
        assert row["journal"] is not None
        journal = tv.get(f"/api/problems/{row['journal']}/journal").json()
        # Its newest lines, within 8 KB, each whole and plain (kept as text).
        kept = journal["lines"]
        assert kept[-1] == "line 399: <script>alert(399)</script> end"
        assert len("\n".join(kept).encode()) <= problems.JOURNAL_MOST
        assert kept[0].startswith("line ") and len(kept) > 100
        for nothing in ("999", "0", "-1", "99999999999999999999"):
            assert tv.get(f"/api/problems/{nothing}/journal").status_code == 404, nothing
        # A newest line too long alone is kept, cut; an empty journal is none.
        sent(tv, kind="crashed", journal="x" * 20_000)
        crash = next(
            p for p in tv.get("/api/problems").json()["problems"] if p["kind"] == "crashed"
        )
        [only] = tv.get(f"/api/problems/{crash['journal']}/journal").json()["lines"]
        assert only == "x" * problems.JOURNAL_MOST
        sent(tv, kind="library-failed", title="No journal")
        none = next(
            p for p in tv.get("/api/problems").json()["problems"] if p["title"] == "No journal"
        )
        assert none["journal"] is None
        # Only an Admin reads them.
        assert TestClient(app).get(f"/api/problems/{row['journal']}/journal").status_code == 401
    assert problems.cleaned_journal("a\r\nb\x00c\n\n d") == "a\nb c\nd"
    assert problems.cleaned_journal("é" * 5000).encode() == ("é" * 4096).encode()


def test_only_the_newest_journals_are_kept(app, monkeypatch):
    monkeypatch.setattr(problems, "JOURNALS_KEPT", 2)
    now = int(time.time() * 1000)
    with TestClient(app) as tv:
        for n in range(4):
            sent(
                tv, kind="library-failed", title=f"T{n}", journal=f"j{n}", at=now - (4 - n) * 60_000
            )
        kept = {p["title"]: p["journal"] for p in tv.get("/api/problems").json()["problems"]}
        assert [t for t, j in sorted(kept.items()) if j is not None] == ["T2", "T3"]


def test_trouble_reaching_stationplay_reads_plainly(app, caplog):
    caplog.set_level(logging.WARNING, logger="stationplay.problems")
    now = int(time.time() * 1000)
    with TestClient(app) as tv:
        sent(tv, kind="unreachable", detail="No network on this device", lastedMs=12 * 60_000,
             at=now - 20 * 60_000, station=5, title="ignored")  # fmt: skip
        [row] = tv.get("/api/problems").json()["problems"]
        assert (
            row["label"]
            == "Den couldn't reach StationPlay for 12 minutes · No network on this device"
        )
        assert row["station"] is None and row["means"] == [problems.TROUBLES[0][1]]
        assert (
            "Problem in StationPlay for Android 0.9.0 on Pixel 8, Android 15 (Den): Den couldn't "
            "reach StationPlay for 12 minutes · No network on this device (20 minutes ago)"
        ) in caplog.text
        # As StationPlay for Android says it, how long in its detail: read from there.
        detail = "StationPlay didn't answer for 1 hr 5 min. The device was on Wi-Fi."
        for minutes in (0, 30):
            sent(tv, kind="unreachable", detail=detail, at=now - (90 + minutes) * 60_000)
        rows = {p["label"]: p for p in tv.get("/api/problems").json()["problems"]}
        both = rows["Den couldn't reach StationPlay for 2 hours 10 minutes in all · StationPlay "
                    "didn't answer"]  # fmt: skip
        assert (both["times"], both["details"]) == (2, [detail])
        # An error answered: the status kept; a device with no name, by its model.
        tv.post("/api/internal/problem", json={**PHONE, "kind": "unreachable",
                "detail": "StationPlay answered with an error (503) for 2 min.", "lastedMs": 125_000})  # fmt: skip
        assert any(p["label"] == "Pixel 8 couldn't reach StationPlay for 2 minutes · StationPlay "
                   "answered with an error (503)" for p in tv.get("/api/problems").json()["problems"])  # fmt: skip
    assert problems.lasted(30_000) == "less than a minute"
    assert problems.lasted(61 * 60_000) == "1 hour 1 minute"


def test_what_the_error_codes_the_apps_send_mean(app):
    with TestClient(app) as tv:
        for title, detail in (
            ("Android", "ERROR_CODE_DECODING_FAILED (MediaCodecVideoDecoderException: Decoder "
             "failed: c2.exynos.hevc.decoder); format video/hevc, 3840×2160"),
            ("Apple", "The operation couldn't be completed (AVFoundationErrorDomain -11821)"),
            ("Offline", "The Internet connection appears to be offline. (NSURLErrorDomain -1009)"),
            ("Roku", "Unable to load stream (Roku error -5)"),
            ("New", "ERROR_CODE_SOMETHING_NEW"),
        ):  # fmt: skip
            sent(tv, kind="library-failed", title=title, detail=detail)
        means = {p["title"]: p["means"] for p in tv.get("/api/problems").json()["problems"]}
        assert means["Android"] == [
            "The device couldn't decode the picture or sound of this file. StationPlay makes a "
            "converted copy when the app asks for one (StationPlay for Android 0.3.1 does)."
        ]
        assert means["Apple"] == means["Android"]
        assert means["Offline"][0].startswith("The device lost its connection")
        assert means["Roku"][0].startswith("The device doesn't play this file's")
        assert means["New"] == []
    # (Every code the apps were promised has a meaning.)
    for code in ("DECODING_FAILED", "DECODER_INIT_FAILED", "DECODING_FORMAT_UNSUPPORTED",
                 "DECODING_FORMAT_EXCEEDS_CAPABILITIES", "AUDIO_TRACK_INIT_FAILED",
                 "BEHIND_LIVE_WINDOW", "IO_NETWORK_CONNECTION_FAILED",
                 "IO_NETWORK_CONNECTION_TIMEOUT", "IO_BAD_HTTP_STATUS",
                 "PARSING_CONTAINER_MALFORMED", "PARSING_MANIFEST_MALFORMED"):  # fmt: skip
        assert problems.meanings([f"ERROR_CODE_{code}"], "library-failed"), code
    assert problems.meanings(["ERROR_CODE_DECODING_FAILED_TOO"], "library-failed") == []
