"""Signing in to StationPlay's page: open until the first user is added, then
Admins and Users, what each may do, and the access log."""

from __future__ import annotations

import asyncio
import sqlite3
import time
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from app import access, backups
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

PAT = {"name": "Pat", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple"}


@pytest.fixture
def app(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * 60_000)
    return create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )


@pytest.fixture
def pat(app):
    """StationPlay with signing in on: Pat, its first user (an Admin), signed in."""
    with TestClient(app) as client:
        made = client.post("/api/access/users", json={**PAT, "role": "user"})
        assert made.status_code == 201, made.text
        assert made.json()["role"] == "admin"  # the first is always an Admin
        yield client


def browser(app) -> TestClient:
    """Another browser, on StationPlay as it's running (not started again)."""
    return TestClient(app)


def station(client, number: int):
    body = {"number": number, "sources": [{"type": "show", "ratingKey": "100"}]}
    return client.post("/api/channels", json=body)


def test_its_open_until_the_first_user_is_added(app):
    with TestClient(app) as client:
        assert client.get("/api/access/me").json() == {"required": False, "user": None}
        assert station(client, 1).status_code == 201
        assert client.get("/api/logs").status_code == 200
        made = client.post("/api/access/users", json=PAT)
        assert "stationplay_session" in made.cookies  # signed in as Pat
        me = client.get("/api/access/me").json()
        assert me["required"] and me["user"]["name"] == "Pat"
        assert client.get("/api/channels").json()[0]["mayChange"]
        stranger = browser(app)
        assert stranger.get("/api/channels").status_code == 401
        assert stranger.get("/api/access/me").json() == {"required": True, "user": None}
        assert stranger.get("/").status_code == 200  # the page, to sign in on
        # What Plex and IPTV apps use stays open.
        for path in ("/discover.json", "/lineup.json", "/xmltv.xml", "/stations.m3u"):
            assert stranger.get(path).status_code == 200, path
        assert stranger.get("/api/bumpers").status_code == 401


def test_signing_in_and_out(pat, app):
    client = browser(app)
    wrong = client.post("/api/access/sign-in", json={**PAT, "password": "not it at all"})
    assert wrong.status_code == 401
    nobody = client.post("/api/access/sign-in", json={**SAM})
    assert nobody.status_code == 401 and nobody.json() == wrong.json()  # tells nothing
    right = client.post("/api/access/sign-in", json={"name": " pat ", "password": PAT["password"]})
    assert right.status_code == 200 and right.json()["user"]["name"] == "Pat"
    assert client.get("/api/channels").status_code == 200
    client.post("/api/access/sign-out")
    assert client.get("/api/channels").status_code == 401
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "Sign-in was turned on, with Pat as the first Admin" in log
    assert "Failed sign-in as 'Sam' from testclient" in log
    assert "Pat (Admin) signed in from testclient" in log and "Pat signed out" in log
    # Only the access log, when that's all that's asked for.
    assert all(
        e["source"] == "stationplay.access"
        for e in pat.get("/api/logs?access_log=true").json()["entries"]
    )


def test_too_many_wrong_passwords_have_to_wait(pat, app):
    client = browser(app)
    for _ in range(access.TRIES):
        assert (
            client.post("/api/access/sign-in", json={**PAT, "password": "nope nope"}).status_code
            == 401
        )
    assert client.post("/api/access/sign-in", json=PAT).status_code == 429
    # Saying it came through a proxy from elsewhere doesn't help.
    client = TestClient(app, headers={"X-Forwarded-For": "203.0.113.9"})
    assert client.post("/api/access/sign-in", json=PAT).status_code == 429


def test_a_user_changes_only_their_own_stations(pat, app):
    pats = station(pat, 1).json()
    assert pat.post("/api/access/users", json={**SAM, "role": "user"}).status_code == 201
    sam = browser(app)
    assert sam.post("/api/access/sign-in", json=SAM).status_code == 200
    sams = station(sam, 2)
    assert sams.status_code == 201, sams.text
    body = {"number": 2, "sources": sams.json()["sources"], "name": "Sam's"}
    assert sam.put(f"/api/channels/{sams.json()['id']}", json=body).status_code == 200
    listed = {c["number"]: c for c in sam.get("/api/channels").json()}
    assert (listed[1]["mayChange"], listed[2]["mayChange"]) == (False, True)
    assert (listed[1]["madeBy"], listed[2]["madeBy"]) == ("Pat", "Sam")
    assert all(
        c["createdExact"] and c["createdAt"] > time.time() * 1000 - 60_000 for c in listed.values()
    )
    # Pat's station: Sam can watch its guide, not change it.
    pid = pats["id"]
    assert sam.get(f"/api/channels/{pid}/guide").status_code == 200
    body = {"number": 1, "sources": pats["sources"], "name": "Mine now"}
    assert sam.put(f"/api/channels/{pid}", json=body).status_code == 403
    for action in ("update", "reshuffle", "check"):
        assert sam.post(f"/api/channels/{pid}/{action}").status_code == 403, action
    assert sam.delete(f"/api/channels/{pid}").status_code == 403
    # Nor what's for Admins.
    for path in ("/api/logs", "/api/broken", "/api/backups", "/api/scan", "/api/access/users"):
        assert sam.get(path).status_code == 403, path
    assert sam.delete("/api/logos/upload-0123456789").status_code == 403
    # A show's logo from Plex they may use (this Plex has none).
    assert sam.get("/plex-logo/100.png").status_code == 404
    assert sam.post("/api/logos/plex", json={"ratingKey": "100"}).status_code == 404
    assert browser(app).get("/plex-logo/100.png").status_code == 401  # but not signed out
    assert (
        sam.post("/api/access/users", json={"name": "Eve", "password": "x" * 12}).status_code == 403
    )
    # An Admin can change anyone's.
    assert pat.delete(f"/api/channels/{sams.json()['id']}").status_code == 204


def test_there_is_always_an_admin(pat, app):
    sam = pat.post("/api/access/users", json={**SAM, "role": "user"}).json()
    me = pat.get("/api/access/me").json()["user"]
    assert pat.put(f"/api/access/users/{me['id']}", json={"role": "user"}).status_code == 400
    assert pat.delete(f"/api/access/users/{me['id']}").status_code == 400
    assert pat.put(f"/api/access/users/{sam['id']}", json={"role": "admin"}).status_code == 200
    assert pat.put(f"/api/access/users/{me['id']}", json={"role": "user"}).status_code == 200
    for bad in ({"name": "", "password": "long enough"}, {"name": "Al", "password": "short"},
                {"name": "<script>", "password": "long enough"}, {**SAM, "name": "sam"}):  # fmt: skip
        assert pat.post("/api/access/users", json=bad).status_code in (400, 403), bad


def test_removing_the_last_user_turns_signing_in_off(pat):
    me = pat.get("/api/access/me").json()["user"]
    assert pat.delete(f"/api/access/users/{me['id']}").status_code == 204
    assert pat.get("/api/access/me").json() == {"required": False, "user": None}
    assert pat.get("/api/logs").status_code == 200


def test_a_new_password_signs_out_everywhere_else(pat, app):
    other = browser(app)
    assert other.post("/api/access/sign-in", json=PAT).status_code == 200
    changed = pat.post(
        "/api/access/me/password", json={"current": PAT["password"], "password": "a new one!"}
    )
    assert changed.status_code == 200
    assert pat.get("/api/channels").status_code == 200  # still signed in here
    assert other.get("/api/channels").status_code == 401  # but not there
    assert (
        other.post("/api/access/sign-in", json={**PAT, "password": "a new one!"}).status_code == 200
    )
    wrong = pat.post("/api/access/me/password", json={"current": "guess", "password": "whatever!"})
    assert wrong.status_code == 400


def test_locked_out_the_reset_file_opens_it_again(pat, app, tmp_path):
    (tmp_path / "data" / access.RESET_FILE).write_text("")
    fp = FakePlex()
    again = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    with TestClient(again) as client:
        assert client.get("/api/access/me").json()["required"] is False
        assert (
            "The reset-access file turned off sign-in"
            in client.get("/api/logs?access_log=true").json()["text"]
        )
    assert not (tmp_path / "data" / access.RESET_FILE).exists()


def test_its_decided_again_once_the_body_has_arrived(app):
    # A request that starts while StationPlay is open and finishes once
    # signing in is on doesn't get in.
    with TestClient(app):
        ctx = app.state.ctx

        async def slowly():
            yield b'{"name": "Eve", "password": "long enough", '
            await ctx.access.add_user(PAT["name"], PAT["password"], "admin", None)  # meanwhile
            yield b'"role": "admin"}'

        async def held():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://sp") as client:
                return await client.post(
                    "/api/access/users",
                    content=slowly(),
                    headers={"content-type": "application/json"},
                )

        assert asyncio.run(held()).status_code == 401
        assert [u.name for u in ctx.db.users()] == ["Pat"]


def test_many_wrong_passwords_at_once_still_have_to_wait(pat, app):
    checks = app.state.ctx.access

    async def at_once(n: int):
        return await asyncio.gather(
            *(checks.check_password("Pat", "a guess!", "192.0.2.7") for _ in range(n)),
            return_exceptions=True,
        )

    sent = asyncio.run(at_once(20))
    assert sum(r is None for r in sent) <= access.TRIES  # (the rest: Busy, unchecked)
    assert all(r is None or isinstance(r, access.Busy) for r in sent)
    # Signing in as yourself doesn't clear wrong guesses at someone else's password.
    pat.post("/api/access/users", json={**SAM, "role": "user"})
    here = "192.0.2.8"
    for _ in range(access.TRIES - 1):
        assert asyncio.run(checks.check_password("Pat", "a guess!", here)) is None
    assert asyncio.run(checks.check_password("Sam", SAM["password"], here)).name == "Sam"
    assert asyncio.run(checks.check_password("Pat", "a guess!", here)) is None  # the last
    with pytest.raises(access.Busy):
        asyncio.run(checks.check_password("Pat", PAT["password"], here))


def test_ipv6_addresses_are_counted_by_network():
    assert access.counted_as("2001:db8::1") == access.counted_as("2001:db8::abcd:1")
    assert access.counted_as("2001:db8::1") != access.counted_as("2001:db8:0:1::1")
    assert access.counted_as("::ffff:192.0.2.1") == "192.0.2.1"
    assert access.counted_as("192.0.2.1") == "192.0.2.1"


def test_changes_from_another_sites_page_are_refused(app):
    with TestClient(app) as client:
        body = {"number": 1, "sources": [{"type": "show", "ratingKey": "100"}]}
        other_site = {"Sec-Fetch-Site": "cross-site"}
        assert client.post("/api/channels", json=body, headers=other_site).status_code == 403
        assert client.get("/api/channels", headers=other_site).status_code == 200
        same = {"Sec-Fetch-Site": "same-origin"}
        assert client.post("/api/channels", json=body, headers=same).status_code == 201


def test_restoring_a_backup_with_no_users_asks_first(pat, app, tmp_path):
    app.state.ctx.restart = lambda: None  # a test mustn't stop itself
    data = tmp_path / "data"
    # A backup from before signing in was on.
    path = backups.make_backup(app.state.ctx)
    copy = tmp_path / "old.db"
    with zipfile.ZipFile(path) as z:
        copy.write_bytes(z.read(backups.DB_NAME))
    conn = sqlite3.connect(copy)
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    old = tmp_path / "old.zip"
    with zipfile.ZipFile(old, "w") as z:
        z.write(copy, backups.DB_NAME)
    asked = pat.post("/api/restore", content=old.read_bytes())
    assert asked.status_code == 409 and "turns off sign-in" in asked.json()["detail"]
    assert not (data / backups.RESTORE_DIR).exists()
    sure = pat.post("/api/restore?opening=true", content=old.read_bytes())
    assert sure.status_code == 200 and sure.json()["users"] == 0
    # Backups never hold who's signed in.
    with zipfile.ZipFile(path) as z:
        (tmp_path / "x.db").write_bytes(z.read(backups.DB_NAME))
    conn = sqlite3.connect(tmp_path / "x.db")
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    conn.close()


def test_a_user_makes_only_as_many_stations_as_they_may(pat, app):
    added = pat.post("/api/access/users", json={**SAM, "role": "user"}).json()
    assert added["maxStations"] == access.NEW_USER_STATIONS == 3
    sid = added["id"]
    sam = browser(app)
    sam.post("/api/access/sign-in", json=SAM)
    made = [station(sam, n) for n in (11, 12, 13)]
    assert [m.status_code for m in made] == [201, 201, 201]
    fourth = station(sam, 14)
    assert fourth.status_code == 403
    assert fourth.json()["detail"].startswith("Your limit is 3 stations, and you've made 3")
    me = sam.get("/api/access/me").json()["user"]
    assert (me["maxStations"], me["stationsMade"]) == (3, 3)
    assert all(c["mine"] for c in sam.get("/api/channels").json())
    # Deleting one makes room for another.
    assert sam.delete(f"/api/channels/{made[0].json()['id']}").status_code == 204
    assert station(sam, 14).status_code == 201
    # An Admin chooses: fewer than they've made (they keep those)...
    assert pat.put(f"/api/access/users/{sid}", json={"maxStations": 1}).json()["maxStations"] == 1
    assert (
        station(sam, 15).json()["detail"].startswith("Your limit is 1 station, and you've made 3")
    )
    # ...or any number; and changing something else leaves it as it is.
    assert pat.put(f"/api/access/users/{sid}", json={"maxStations": None}).status_code == 200
    assert pat.put(f"/api/access/users/{sid}", json={"role": "user"}).json()["maxStations"] is None
    assert station(sam, 15).status_code == 201
    for bad in (0, 2, 26, -1):
        assert pat.put(f"/api/access/users/{sid}", json={"maxStations": bad}).status_code == 400
    choosy = {"name": "Al", "password": "long enough", "maxStations": 7}
    assert pat.post("/api/access/users", json=choosy).status_code == 400
    assert sam.put(f"/api/access/users/{sid}", json={"maxStations": 25}).status_code == 403
    # Admins make any number.
    for n in range(20, 25):
        assert station(pat, n).status_code == 201
    listed = {u["name"]: u for u in pat.get("/api/access/users").json()}
    assert (listed["Sam"]["stationsMade"], listed["Pat"]["stationsMade"]) == (4, 5)
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "Pat added Sam as a User (up to 3 stations)" in log
    assert "Pat let Sam make up to 1 station" in log
    assert "Pat let Sam make any number of stations" in log


def test_two_stations_at_once_cant_both_take_the_last_place(pat, app):
    pat.post("/api/access/users", json={**SAM, "role": "user", "maxStations": 1})
    sam = browser(app)
    sam.post("/api/access/sign-in", json=SAM)

    async def both():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://sp", cookies=dict(sam.cookies)
        ) as client:
            return await asyncio.gather(*(
                client.post("/api/channels", json={"number": n, "sources": [{"type": "show", "ratingKey": "100"}]})
                for n in (31, 32)
            ))  # fmt: skip

    # (Run where StationPlay runs.)
    got = pat.portal.call(both)
    assert sorted(r.status_code for r in got) == [201, 403]


def test_only_so_many_browsers_are_signed_in_as_one_user(pat, app, monkeypatch):
    monkeypatch.setattr(access, "SESSIONS_KEPT", 2)
    browsers = [browser(app) for _ in range(3)]
    for b in browsers:
        assert b.post("/api/access/sign-in", json=PAT).status_code == 200
    # The newest two (and not the first, nor Pat's own from before).
    assert [b.get("/api/channels").status_code for b in browsers] == [401, 200, 200]
    assert pat.get("/api/channels").status_code == 401


def test_passwords_are_kept_only_as_hashes():
    stored = access.hash_password("correct horse")
    assert "correct horse" not in stored and stored.startswith("scrypt$")
    assert access.password_matches("correct horse", stored)
    assert not access.password_matches("correct horsE", stored)
    assert not access.password_matches("correct horse", "garbage")
    assert access.hash_password("correct horse") != stored  # salted
