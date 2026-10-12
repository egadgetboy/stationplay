"""People's reports (reports.py): picked from a list in the apps, never
typed; what each does (a check at once, or the Admin's choice); the limits;
Can report problems; Viewing Levels; and that a report never takes anything
off the air by itself."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest
from fastapi.testclient import TestClient

from app import jobs, reports
from app import scanner as sc
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex
from .test_replacing import calls_like, world  # noqa: F401  (Sonarr's and Radarr's world)
from .test_who_sees_what import kid_level, sign_in_app

ADA = {"name": "Ada", "password": "correct horse"}
TIA = {"name": "Tia", "password": "battery staple"}
KIT = {"name": "Kit", "password": "staple battery"}


@pytest.fixture
def plex():
    fp = LibraryPlex()
    fp.add_show("100", "Northbound", contentRating=["TV-PG"])
    for n in range(1, 5):
        fp.add_episode(f"20{n}", "100", 2, n, f"North {n}", f"/tv/n/{n}.mkv", 44 * 60_000)
        fp.describe(f"20{n}")
    fp.add_episode("205", "100", 2, 5, "Short One", "/tv/n/5.mkv", 22 * 60_000)
    fp.describe("205", width=720, height=480)
    fp.add_subtitles("205", "srt", "Spanish")
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Heist", "/m/heist.mkv", 100 * 60_000, section="2", contentRating=["R"])
    fp.describe("300")
    for n in range(1, 12):  # (for the limits)
        fp.add_movie(f"31{n:02d}", f"Film {n}", f"/m/{n}.mkv", 90 * 60_000, section="2",
                     contentRating=["G"])  # fmt: skip
    return fp


@pytest.fixture
def app(plex, tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=plex.transport()))
    app.state.ctx.play_transport = plex.transport()
    return app


def start(admin: TestClient) -> dict:
    """Ada (an Admin), Tia (a User), Kit (on Kid's level), a station, and
    both libraries shared."""
    made = admin.post("/api/channels", json={"number": 4, "name": "North", "sources": [
        {"type": "show", "ratingKey": "100"}]})  # fmt: skip
    assert made.status_code == 201
    admin.portal.call(admin.app.state.ctx.titles.filled)
    assert admin.put("/api/app-libraries", json={"libraries": ["1", "2"]}).status_code == 200
    admin.post("/api/access/users", json=ADA)
    tia = admin.post("/api/access/users", json={**TIA, "role": "user"}).json()
    kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
    admin.put(f"/api/access/users/{kit['id']}/viewing", json={"level": kid_level(admin)})
    assert admin.post("/api/access/sign-in", json=ADA).status_code == 200
    return {"tia": tia, "kit": kit, "station": made.json()}


def report(phone: TestClient, headers: dict, **body):
    return phone.post("/api/internal/report-problem", json=body, headers=headers)


def test_the_choices_come_from_the_server(app):
    with TestClient(app) as client:
        got = client.get("/api/internal/report-choices").json()["choices"]
    assert [(c["group"], c["id"], c["label"]) for c in got] == [
        ("Picture", "no-picture", "No picture"),
        ("Picture", "picture-breaks", "The picture breaks up or freezes"),
        ("Picture", "poor-quality", "Poor picture quality"),
        ("Sound", "no-sound", "No sound"),
        ("Sound", "sound-cuts", "The sound cuts out"),
        ("Sound", "out-of-sync", "The sound is out of sync"),
        ("Sound", "wrong-language", "Wrong language"),
        ("Subtitles", "subtitles", "Subtitles are missing or wrong"),
        ("The program", "wont-play", "It won't play"),
        ("The program", "stops-early", "It stops before the end"),
        ("The program", "wrong-program", "Wrong episode or movie"),
        ("Details", "wrong-details", "Wrong title, details or artwork"),
    ]
    assert set(reports.LABELS) == reports.CHECKED | reports.LOOKED | reports.DETAILS


def test_what_can_be_checked_is_checked_at_once(app, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as admin:
        start(admin)
        ctx = app.state.ctx
        tia = sign_in_app(app, TIA)
        phone = TestClient(app)
        sent = report(phone, tia, choice="no-sound", key="202", positionMs=754_000,
                      method="direct", audio="2022")  # fmt: skip
        assert sent.status_code == 200 and sent.json() == {
            "detail": "Thanks. An Admin will take a look."
        }
        assert "Tia reported No sound in Northbound · S2 E2, at 12:34" in caplog.text
        # At the front of the queue: around 12:34, then the quick check,
        # then (as it says where) the deep scan if those find nothing.
        [target] = ctx.scanner._targets
        assert (target.key, target.at_s, target.full, target.why) == (
            "202", 754.0, True, "Tia reported No sound",
        )  # fmt: skip
        [row] = admin.get("/api/reports").json()["reports"]
        assert (row["key"], row["name"], row["state"], row["needs"]) == (
            "202", "Northbound S2 E2", "checking", False,
        )  # fmt: skip
        assert [s["number"] for s in row["on"]] == [4] and row["media"] is True
        [one] = row["reports"]
        assert (one["who"], one["label"], one["positionMs"]) == ("Tia", "No sound", 754_000)
        assert one["how"] == {"method": "as it is", "audio": "English · AAC · 5.1"}
        assert one["device"] == "A StationPlay app"
        # It found nothing: the report waits, saying so, for an Admin to
        # dismiss. Nothing came off the air.
        ctx.scanner._done_with(target, sc.NOTHING, "StationPlay gave it the quick check, and "
                               "found nothing wrong.")  # fmt: skip
        [row] = admin.get("/api/reports").json()["reports"]
        assert row["state"] == "nothing" and row["needs"] and row["actions"] == ["dismiss"]
        assert row["notes"] == ["StationPlay gave it the quick check, and found nothing wrong."]
        assert ctx.broken.keys() == set()
        assert admin.get("/api/status").json()["filesCount"] == 1
        assert admin.post("/api/reports/202/dismiss").status_code == 200
        assert admin.get("/api/reports").json()["reports"] == []
        assert admin.post("/api/reports/202/dismiss").status_code == 404


def test_what_a_check_finds_puts_the_file_on_the_list(app):
    with TestClient(app) as admin:
        start(admin)
        ctx = app.state.ctx
        phone = TestClient(app)
        tia = sign_in_app(app, TIA)
        assert report(phone, tia, choice="stops-early", key="203").status_code == 200
        [target] = ctx.scanner._targets
        assert target.at_s is None and not target.full  # (it didn't say where)
        item = sc.item_of(*_first_version(ctx, admin, "203"))
        ctx.broken.record(item, "Check: no picture from 30:00 on", 4, item.file_path, 1000)
        ctx.scanner._done_with(target, sc.FOUND, "Check: no picture from 30:00 on")
        assert admin.get("/api/reports").json()["reports"] == []
        [entry] = admin.get("/api/broken").json()
        [by] = entry["reports"]
        assert (by["who"], by["label"], by["state"]) == ("Tia", "It stops before the end", "found")


def test_a_report_of_what_has_no_file_to_check_waits_for_an_admin(app, plex):
    plex.add_episode("206", "100", 2, 6, "Nowhere", "/tv/n/6.mkv", 44 * 60_000)
    plex.episodes["206"]["Media"] = []
    with TestClient(app) as admin:
        start(admin)
        ctx = app.state.ctx
        tia = sign_in_app(app, TIA)
        sent = report(TestClient(app), tia, choice="wont-play", key="206", positionMs=1000)
        assert sent.status_code == 200
        assert ctx.scanner._targets == []  # (nothing to check)
        [row] = admin.get("/api/reports").json()["reports"]
        assert (row["state"], row["needs"], row["actions"]) == ("couldn't", True, ["dismiss"])
        assert row["notes"] == ["Plex has no file for it to check."]


def _first_version(ctx, client, key):
    entry = client.portal.call(ctx.library.entry, key, True)
    return entry, entry.media[0]


def test_what_a_machine_cant_judge_waits_for_an_admin(app):
    with TestClient(app) as admin:
        start(admin)
        ctx = app.state.ctx
        phone = TestClient(app)
        tia = sign_in_app(app, TIA)
        for choice, key in (("wrong-language", "201"), ("out-of-sync", "201"),
                            ("wrong-program", "205"), ("poor-quality", "204"),
                            ("subtitles", "300"), ("wrong-details", "203")):  # fmt: skip
            # (One a day per person per program: Tia's second about 201 is Ada's.)
            who = tia if (choice, key) != ("out-of-sync", "201") else sign_in_app(app, ADA)
            assert report(phone, who, choice=choice, key=key).status_code == 200, (choice, key)
        rows = {r["key"]: r for r in admin.get("/api/reports").json()["reports"]}
        assert ctx.scanner._targets == []  # (nothing to check)
        assert ctx.broken.keys() == set()  # (nothing off the air)
        # Several reports on one program: one row, each under it.
        two = rows["201"]
        assert [r["label"] for r in two["reports"]] == [
            "The sound is out of sync",
            "Wrong language",
        ]
        assert two["state"] == "waiting" and two["needs"]
        assert two["actions"] == ["replace", "better", "dismiss"] and two["arr"] is None
        # Beside each, what StationPlay can tell.
        assert two["facts"] == ["Its sound: English"]
        assert rows["205"]["facts"] == [
            "It runs 22 min; the show's other episodes run about 44 min"
        ]
        assert rows["204"]["facts"] == ["Its picture: 1080p (1920×1080), 8 Mbps"]
        assert rows["300"]["facts"] == ["It has no subtitles"]
        details = rows["203"]
        assert details["actions"] == ["dismiss"]
        assert details["notes"] == [
            "Fix its title, details or artwork in Plex (Fix Match, or Edit, on its page there), "
            "then choose Dismiss."
        ]
        assert admin.get("/api/status").json()["filesCount"] == 5
        # Without Sonarr and Radarr, there's nothing to replace with.
        refused = admin.post("/api/reports/201/replace")
        assert refused.status_code == 400 and "Sonarr isn't turned on" in refused.json()["detail"]
        assert admin.post("/api/reports/203/replace").status_code == 400


def test_the_limits_and_who_may_report(app):
    with TestClient(app) as admin:
        ids = start(admin)
        phone = TestClient(app)
        tia = sign_in_app(app, TIA)
        assert report(phone, tia, choice="no-picture", key="3101").status_code == 200
        again = report(phone, tia, choice="no-sound", key="3101")
        assert (
            again.status_code == 429
            and again.json()["detail"] == "You've reported this one today. Thanks."
        )
        for n in range(2, 11):
            assert report(phone, tia, choice="wrong-details", key=f"31{n:02d}").status_code == 200
        enough = report(phone, tia, choice="wrong-details", key="3111")
        assert enough.status_code == 429
        assert enough.json()["detail"] == "That's all the reports for today. Thanks for your help."
        # Choices from the list only, about one thing.
        for bad in ({"choice": "it's bad", "key": "300"}, {"choice": "no-sound"},
                    {"choice": "no-sound", "key": "300", "station": 4},
                    {"choice": "no-sound", "key": "100"}):  # fmt: skip
            assert report(phone, sign_in_app(app, ADA), **bad).status_code == 400, bad
        # An Admin turns it off for Kit: refused, with a sentence.
        kit = ids["kit"]
        me = phone.get("/api/internal/me", headers=sign_in_app(app, KIT)).json()["user"]
        assert me["canReport"] is True
        changed = admin.put(f"/api/access/users/{kit['id']}", json={"canReport": False})
        assert changed.status_code == 200 and changed.json()["canReport"] is False
        as_kit = sign_in_app(app, KIT)
        assert phone.get("/api/internal/me", headers=as_kit).json()["user"]["canReport"] is False
        off = report(phone, as_kit, choice="no-sound", key="3101")
        assert off.status_code == 403
        assert off.json()["detail"] == "An Admin has turned off reporting problems for you."
        users = {u["name"]: u for u in admin.get("/api/access/users").json()}
        assert users["Kit"]["canReport"] is False and users["Tia"]["canReport"] is True
        # An Admin always can.
        ada = next(u for u in users.values() if u["name"] == "Ada")
        admin.put(f"/api/access/users/{ada['id']}", json={"canReport": False})
        assert (
            report(phone, sign_in_app(app, ADA), choice="no-sound", key="3111").status_code == 200
        )
        # A User can't turn it on or off.
        assert phone.put(f"/api/access/users/{kit['id']}", headers=tia,
                         json={"canReport": True}).status_code == 403  # fmt: skip


def test_only_what_someone_may_see(app):
    with TestClient(app) as admin:
        ids = start(admin)
        phone = TestClient(app)
        kit = sign_in_app(app, KIT)
        # Heist is rated R: beyond Kid, so it's as though it weren't there.
        hidden = report(phone, kit, choice="no-sound", key="300")
        assert hidden.status_code == 404
        assert (
            hidden.json()["detail"]
            == report(phone, kit, choice="no-sound", key="999").json()["detail"]
        )
        assert report(phone, kit, choice="no-sound", key="3101").status_code == 200
        # A station they can't see: as though there weren't one.
        admin.put(f"/api/access/users/{ids['kit']['id']}/viewing",
                  json={"level": kid_level(admin), "stations": {str(ids["station"]["id"]): False}})  # fmt: skip
        assert report(phone, kit, choice="no-sound", station=4).status_code == 404
        assert report(phone, kit, choice="no-sound", station=77).status_code == 404
        # The tab is an Admin's alone.
        assert phone.get("/api/reports", headers=kit).status_code == 403
        assert phone.post("/api/reports/3101/dismiss", headers=kit).status_code == 403


def test_whats_on_a_station_now(app):
    with TestClient(app) as admin:
        ids = start(admin)
        ctx = app.state.ctx
        phone = TestClient(app)
        tia = sign_in_app(app, TIA)
        now = int(time.time() * 1000)
        slot = ctx.station(ids["station"]["id"]).locate(now)
        sent = report(phone, tia, choice="picture-breaks", station=4)
        assert sent.status_code == 200
        [row] = admin.get("/api/reports").json()["reports"]
        [one] = row["reports"]
        assert row["key"] == slot.item.rating_key and one["station"] == 4
        assert one["how"] == {"station": 4} and one["version"] == ""
        into = one["positionMs"] - (now - slot.start_ms)
        assert -2000 <= into <= 2000  # (where it is now, as the station plays it)
        [target] = ctx.scanner._targets
        assert target.key == slot.item.rating_key and target.station == 4


def test_replace_and_find_a_better_copy(world, caplog):  # noqa: F811
    """With Radarr on: Find a better copy only searches, keeping the file;
    Replace blocklists the release and fetches another, as for a broken
    file. Only an Admin's choice does either."""
    caplog.set_level(logging.INFO)
    c, ctx, r = world.client, world.ctx, world.radarr
    ctx.shared.save(["2"])
    world.plex.add_movie("302", "Alien", "/movies/Alien (1979)/Alien (1979).mkv", 117 * 60_000,
                         year=1979, section="2")  # fmt: skip
    world.plex.episodes["302"]["Guid"] = [{"id": "tmdb://348"}]
    world.plex.episodes["302"]["librarySectionID"] = 2
    r.add_movie(10, "Alien", 1979, 348)
    r.give_file(9, "Dune (1984).mkv", 1000, downloaded="Dune.1984.720p.BluRay-OLD")
    r.releases[9] = ["Dune.1984.720p.BluRay-OLD", "Dune.1984.1080p.BluRay-NEW"]
    assert c.put("/api/arr/when", json={"when": "ask"}).status_code == 200
    for choice, key in (("poor-quality", "302"), ("out-of-sync", "301")):
        sent = c.post("/api/internal/report-problem", json={"choice": choice, "key": key})
        assert sent.status_code == 200, sent.text
    world.go()
    assert not r.commands and ctx.broken.keys() == set()  # (a report alone does nothing)
    rows = {row["key"]: row for row in c.get("/api/reports").json()["reports"]}
    assert rows["302"]["arr"] == "Radarr"
    assert rows["302"]["actions"] == ["replace", "better", "dismiss"]
    # Set to replace only missing files: neither is offered.
    assert c.put("/api/arr/what", json={"what": "missing"}).status_code == 200
    assert {row["arr"] for row in c.get("/api/reports").json()["reports"]} == {None}
    assert c.post("/api/reports/302/better").status_code == 400
    assert c.post("/api/reports/301/replace").status_code == 400
    assert c.put("/api/arr/what", json={"what": "both"}).status_code == 200
    better = c.post("/api/reports/302/better")
    assert better.status_code == 200, better.text
    assert better.json()["said"] == "Radarr is searching for a better copy of Alien (1979)"
    [kept] = [row for row in ctx.db.reports_in(("better",)) if row["rating_key"] == "302"]
    assert (
        kept["note"] == "An Admin chose Find a better copy: Radarr is searching for a better copy"
    )
    assert [(x["name"], x["body"]["movieIds"]) for x in r.commands] == [("MoviesSearch", [10])]
    assert not r.blocklist and not calls_like(r, "DELETE moviefile/")
    assert [row["key"] for row in c.get("/api/reports").json()["reports"]] == ["301"]
    # Reports an Admin dealt with while Plex was being asked about the file
    # aren't replaced after all.
    real = ctx.reports._version

    async def meanwhile(report):
        got = await real(report)
        ctx.reports.dismiss("301", "Bo")
        return got

    ctx.reports._version = meanwhile
    assert c.post("/api/reports/301/replace").status_code == 404
    assert ctx.broken.keys() == set() and not r.blocklist and not jobs._trying
    ctx.reports._version = real
    ctx.db.set_reports([row["id"] for row in ctx.db.reports_in(("dismissed",))], "waiting", "",
                       None)  # fmt: skip
    # Replace: off the air until its new file comes, and Radarr fetches one.
    replaced = c.post("/api/reports/301/replace")
    assert replaced.status_code == 200, replaced.text
    if jobs._trying:  # (Radarr's part goes on in the background)
        c.portal.call(asyncio.wait, set(jobs._trying))
    entry = ctx.broken.entry("301")
    assert entry["foundBy"] == "report" and entry["problem"] == "damaged"
    assert entry["reason"] == "Reported: The sound is out of sync. An Admin chose Replace"
    assert r.blocklist == ["Dune.1984.720p.BluRay-OLD"]
    assert [x["body"]["movieIds"] for x in r.commands] == [[10], [9]]
    [listed] = [e for e in c.get("/api/broken").json() if e["key"] == "301"]
    assert listed["section"] == "being replaced"
    assert c.get("/api/reports").json()["reports"] == []


def test_an_admin_is_told_what_needs_them(app):
    """Through what Admins already get (Admin alerts, and a web address): one
    alert, saying how many and the newest."""
    with TestClient(app) as admin:
        start(admin)
        ctx = app.state.ctx
        phone = TestClient(app)
        tia = sign_in_app(app, TIA)
        assert report(phone, tia, choice="no-sound", key="204").status_code == 200
        ctx.alerts.files(ctx.reports.needing())
        assert ctx.alerts.now() == []  # (being checked: nothing for an Admin yet)
        episode, media = _first_version(ctx, admin, "202")
        ctx.broken.record(sc.item_of(episode, media), "Deep scan: the sound drops out around "
                          "3:00", 4, media.file, media.size, problem="damaged")  # fmt: skip
        assert report(phone, tia, choice="wrong-language", key="201").status_code == 200
        ctx.alerts.files(ctx.reports.needing())
        [alert] = admin.get("/api/internal/alerts").json()["alerts"]
        assert alert["kind"] == "files" and alert["sentence"] == (
            "There are 2 files to look at on the Broken files tab: Tia reported Wrong language "
            "on Northbound S2 E1."
        )
        assert admin.get("/api/status").json()["filesCount"] == 2
        # Dismissed, and the file put back on the air: nothing needs an Admin.
        admin.post("/api/reports/201/dismiss")
        assert admin.delete("/api/broken/202").status_code == 204
        ctx.alerts.files(ctx.reports.needing())
        [fixed] = admin.get("/api/internal/alerts").json()["alerts"]
        assert fixed["fixed"] and fixed["kind"] == "files"
