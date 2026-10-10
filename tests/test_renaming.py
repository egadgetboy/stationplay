"""Renaming people (see access.py): an Admin renames anyone on the Access
tab, themselves and other Admins too, with the rules a new name has;
signing in takes the new name from then on; everything of theirs, kept by
their id, stays theirs; and the apps show the new name the next time they
ask."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import access, stats
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex

PAT = {"name": "Pat", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple", "role": "user"}
ADA = {"name": "Ada", "password": "horse battery", "role": "admin"}
TV = {"app": "StationPlay for Roku", "deviceName": "Den", "picker": True}
BOX = {"containers": ["mkv"], "video": [{"codec": "h264", "width": 1920, "height": 1080}],
       "hdr": [], "audio": ["ac3", "aac"]}  # fmt: skip


@pytest.fixture
def app(tmp_path):
    fp = LibraryPlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * 60_000)
    fp.add_section("2", "Movies", "movie")
    movie = tmp_path / "movie.mkv"
    movie.write_bytes(b"a movie" * 100)
    fp.add_movie("300", "Jaws", str(movie), 100 * 60_000, year=1975, section="2")
    fp.describe("300", audio="ac3")
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    app.state.ctx.play_transport = fp.transport()
    return app


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ids(client: TestClient) -> dict[str, int]:
    return {u["name"]: u["id"] for u in client.get("/api/access/users").json()}


def rename(client: TestClient, user_id: int, name: str):
    return client.put(f"/api/access/users/{user_id}", json={"name": name})


def test_an_admin_renames_anyone_with_the_rules_a_new_name_has(app):
    with TestClient(app) as pat:
        assert pat.post("/api/access/users", json=PAT).status_code == 201
        assert pat.post("/api/access/users", json=SAM).status_code == 201
        assert pat.post("/api/access/users", json=ADA).status_code == 201
        who = ids(pat)
        renamed = rename(pat, who["Sam"], "  Samuel  ")
        assert renamed.status_code == 200 and renamed.json()["name"] == "Samuel"
        assert rename(pat, who["Ada"], "Ada Lovelace").json()["name"] == "Ada Lovelace"
        # Themselves too, and still signed in.
        assert rename(pat, who["Pat"], "Patricia").json()["name"] == "Patricia"
        assert pat.get("/api/access/me").json()["user"]["name"] == "Patricia"
        log = pat.get("/api/logs?access_log=true").json()["text"]
        assert "Pat renamed Sam to Samuel" in log
        assert "Pat renamed Ada to Ada Lovelace" in log
        assert "Pat renamed Pat to Patricia" in log
        # The rules a new name has: its length, its characters, and no one
        # else's, whatever its case.
        for wrong in ("", "   ", "x" * 41, "Sam/uel", "<b>Sam</b>"):
            refused = rename(pat, who["Sam"], wrong)
            assert refused.status_code == 400, wrong
            assert "up to 40 characters" in refused.json()["detail"]
        taken = rename(pat, who["Sam"], "ada lovelace")
        assert taken.status_code == 400
        assert taken.json()["detail"] == "There's already a user called ada lovelace"
        assert rename(pat, who["Sam"], "SAMUEL").json()["name"] == "SAMUEL"  # (its own)
        assert rename(pat, who["Sam"], "Samuel").json()["name"] == "Samuel"
        # The same name again changes nothing, and says nothing.
        before = pat.get("/api/logs?access_log=true").json()["text"].count("renamed")
        assert rename(pat, who["Sam"], "Samuel").status_code == 200
        assert pat.get("/api/logs?access_log=true").json()["text"].count("renamed") == before
        assert rename(pat, 999, "Nobody").status_code == 404
        # A User renames no one, themselves included.
        sam = TestClient(app)
        assert sam.post("/api/access/sign-in", json={**SAM, "name": "Samuel"}).status_code == 200
        assert rename(sam, who["Sam"], "Sammy").status_code == 403
        assert rename(sam, who["Pat"], "Pat").status_code == 403
        assert ids(pat).keys() == {"Ada Lovelace", "Patricia", "Samuel"}


async def test_only_an_admin_may_rename(app):
    with TestClient(app) as pat:
        pat.post("/api/access/users", json=PAT)
        pat.post("/api/access/users", json=SAM)
        ctx = app.state.ctx
        sam = ctx.db.user(ids(pat)["Sam"])
        with pytest.raises(access.NotAllowed):
            await ctx.access.change_user(sam, sam, password=None, role=None, name="Sammy")
        assert ctx.db.user(sam.id).name == "Sam"


def test_signing_in_takes_the_new_name(app):
    with TestClient(app) as pat:
        pat.post("/api/access/users", json=PAT)
        pat.post("/api/access/users", json=SAM)
        rename(pat, ids(pat)["Sam"], "Samuel")
        page = TestClient(app)
        assert page.post("/api/access/sign-in", json=SAM).status_code == 401
        assert page.post("/api/access/sign-in", json={**SAM, "name": "samuel"}).status_code == 200
        phone = TestClient(app)
        assert phone.post("/api/internal/sign-in", json=SAM).status_code == 401
        signed = phone.post("/api/internal/sign-in", json={**SAM, "name": "Samuel"})
        assert signed.status_code == 200 and signed.json()["user"]["name"] == "Samuel"


def test_everything_of_theirs_stays_theirs(app):
    with TestClient(app) as pat:
        pat.post("/api/access/users", json=PAT)
        pat.post("/api/access/users", json=SAM)
        pat.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        ctx = app.state.ctx
        sam_id = ids(pat)["Sam"]
        # Before: Sam signed in on the page and in an app, a station of his,
        # a Viewing Level, where he is in a movie, his viewing in the stats,
        # and a TV he linked.
        page = TestClient(app)
        assert page.post("/api/access/sign-in", json=SAM).status_code == 200
        phone = TestClient(app)
        token = phone.post("/api/internal/sign-in", json={**SAM, "deviceName": "Pixel"}).json()
        his = bearer(token["token"])
        made = page.post(
            "/api/channels", json={"number": 7, "sources": [{"type": "show", "ratingKey": "100"}]}
        )
        assert made.status_code == 201, made.text
        # (A level of the Admin's own, with no limits, so he still makes stations.)
        level = pat.post("/api/access/levels", json={"name": "Grown-ups"}).json()["id"]
        assert (
            pat.put(f"/api/access/users/{sam_id}/viewing", json={"level": level}).status_code == 200
        )
        progress = {"key": "300", "positionMs": 1_800_000}
        assert phone.post("/api/internal/progress", json=progress, headers=his).status_code == 200
        today = stats.day_of(int(time.time() * 1000))
        ctx.db.add_app_watching(
            [(sam_id, "Sam", made.json()["id"], today, "Show", "episode", 1800)]
        )
        ctx.db.add_media_watching((sam_id, "Sam", today, "Jaws", "movie", 1, 900.0))
        tv = TestClient(app)
        key = tv.post("/api/internal/sign-in", json={**SAM, **TV}).json()["deviceKey"]

        assert rename(pat, sam_id, "Samuel").status_code == 200

        # His sign-ins: the page's and the app's.
        assert page.get("/api/access/me").json()["user"] == {
            **page.get("/api/access/me").json()["user"], "id": sam_id, "name": "Samuel"
        }  # fmt: skip
        assert phone.get("/api/v1/stations", headers=his).status_code == 200
        apps = pat.get("/api/access/apps").json()
        assert [a["user"] for a in apps if a["app"].endswith("Pixel")] == ["Samuel"]
        # His station: still his to change, and counted as his.
        assert page.put(f"/api/channels/{made.json()['id']}", json={
            "number": 7, "name": "Sam's", "sources": [{"type": "show", "ratingKey": "100"}]
        }).status_code == 200  # fmt: skip
        users = {u["name"]: u for u in pat.get("/api/access/users").json()}
        assert users["Samuel"]["stationsMade"] == 1 and users["Samuel"]["id"] == sam_id
        # His Viewing Level, and where he is.
        assert pat.get("/api/access/viewing").json()["users"][str(sam_id)]["level"] == level
        movie = phone.get("/api/internal/items/300", headers=his).json()
        assert movie["positionMs"] == 1_800_000
        # His viewing in the stats, under his new name (one person, not two),
        # even what's counted after, from a play that began before.
        ctx.db.add_media_watching((sam_id, "Sam", today, "Jaws", "movie", 0, 900.0))
        [person] = pat.get("/api/stats?days=1").json()["people"]
        assert (person["name"], person["stationHours"], person["mediaHours"]) == (
            "Samuel", 0.5, 0.5
        )  # fmt: skip
        # The TV he linked: still his, under his new name.
        [linked] = pat.get("/api/access/devices").json()["devices"]
        assert linked["linkedBy"] == "Samuel" and linked["people"] == ["Pat", "Samuel"]
        assert ctx.devices.devices()[0].linked_by_id == sam_id
        listed = tv.get("/api/internal/picker", headers={"StationPlay-Device": key}).json()
        assert [p["name"] for p in listed["people"]] == ["Pat", "Samuel"]


def test_the_apps_show_the_new_name_the_next_time_they_ask(app):
    with TestClient(app) as pat:
        pat.post("/api/access/users", json=PAT)
        pat.post("/api/access/users", json=SAM)
        tv = TestClient(app)
        signed = tv.post("/api/internal/sign-in", json={**SAM, **TV}).json()
        key = {"StationPlay-Device": signed["deviceKey"]}
        his = bearer(signed["token"])
        assert tv.get("/api/internal/me", headers=his).json()["user"] == {
            "name": "Sam", "role": "user", "pin": False, "canChangePassword": True,
            "canReport": True,
        }  # fmt: skip
        rename(pat, ids(pat)["Sam"], "Samuel")
        # Who's tuning in?
        people = tv.get("/api/internal/picker", headers=key).json()["people"]
        assert [p["name"] for p in people] == ["Pat", "Samuel"]
        # Options: who this app is signed in as.
        assert tv.get("/api/internal/me", headers=his).json()["user"] == {
            "name": "Samuel", "role": "user", "pin": False, "canChangePassword": True,
            "canReport": True,
        }  # fmt: skip
        assert tv.get("/api/internal/me").status_code == 401  # (signing in is on)
        # Picking him gives a sign-in in his new name.
        sam = next(p for p in people if p["name"] == "Samuel")
        picked = tv.post("/api/internal/picker/choose", json={"id": sam["id"]}, headers=key)
        assert picked.json()["user"] == {"name": "Samuel", "role": "user"}


def test_a_device_is_its_linkers_by_who_they_are_not_their_name(app):
    """A device someone linked is theirs by their id: an Admin given the
    name of whoever linked it (since removed) still needs their password to
    pick themselves there; an Admin renamed keeps their own device."""
    with TestClient(app) as pat:
        pat.post("/api/access/users", json=PAT)
        eve = pat.post("/api/access/users", json={"name": "Eve", "password": "eve's password",
                                                  "role": "user"})  # fmt: skip
        tv = TestClient(app)
        key = {"StationPlay-Device": tv.post(
            "/api/internal/sign-in", json={"name": "Eve", "password": "eve's password", **TV}
        ).json()["deviceKey"]}  # fmt: skip
        assert pat.delete(f"/api/access/users/{eve.json()['id']}").status_code == 204
        rename(pat, ids(pat)["Pat"], "Eve")  # (the Admin, now named as Eve was)
        [admin] = tv.get("/api/internal/picker", headers=key).json()["people"]
        assert admin["name"] == "Eve" and admin["admin"]
        refused = tv.post("/api/internal/picker/choose", json={"id": admin["id"]}, headers=key)
        assert refused.status_code == 403 and "password" in refused.json()["detail"]
        # An Admin's own device stays theirs when they're renamed.
        own = TestClient(app)
        mine = {"StationPlay-Device": own.post(
            "/api/internal/sign-in", json={"name": "Eve", "password": PAT["password"], **TV}
        ).json()["deviceKey"]}  # fmt: skip
        rename(pat, admin["id"], "Patricia")
        picked = own.post("/api/internal/picker/choose", json={"id": admin["id"]}, headers=mine)
        assert picked.status_code == 200 and picked.json()["user"]["name"] == "Patricia"


def test_devices_linked_before_are_kept_by_whoever_linked_them(tmp_path):
    path = tmp_path / "old.db"
    old = Database(path)
    user = old.add_user("Pat", access.hash_password(PAT["password"]), "admin", 1, None)
    old.add_linked_device("key", "Den", 1000, "Pat", user.id)
    old.add_linked_device("gone", "Attic", 1000, "Someone Removed", 999)
    old._conn.execute("ALTER TABLE linked_devices DROP COLUMN linked_by_id")  # (as before 1.27)
    old._conn.commit()
    old.close()
    upgraded = Database(path)
    found = {r["name"]: r["linked_by_id"] for r in upgraded.linked_devices()}
    upgraded.close()
    assert found == {"Den": user.id, "Attic": None}
