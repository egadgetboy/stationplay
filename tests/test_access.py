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
from app.db import Database
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


def test_changing_your_password_in_an_app(pat, app):
    pat.post("/api/access/users", json={**SAM, "role": "user"})
    phone = {"app": "StationPlay for Android", "deviceName": "Sam’s phone"}
    signed = browser(app).post("/api/internal/sign-in", json={**SAM, **phone}).json()
    tablet = browser(app).post("/api/internal/sign-in", json={**SAM, "app": "On a tablet"})
    page = browser(app)
    assert page.post("/api/access/sign-in", json=SAM).status_code == 200
    sams = {"Authorization": f"Bearer {signed['token']}"}
    app_ = browser(app)
    me = app_.get("/api/internal/me", headers=sams).json()["user"]
    assert me["canChangePassword"] is True

    # As on the page: the current one, and a new one long enough.
    wrong = app_.post(
        "/api/internal/password", json={"current": "guess", "new": "a new one!"}, headers=sams
    )
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "Your current password isn't right"
    short = app_.post(
        "/api/internal/password", json={"current": SAM["password"], "new": "short"}, headers=sams
    )
    assert short.status_code == 400 and "8 characters" in short.json()["detail"]
    changed = app_.post(
        "/api/internal/password", json={"current": SAM["password"], "new": "a new one!"},
        headers=sams,
    )  # fmt: skip
    assert changed.status_code == 200, changed.text
    # This app carries on, with its new token; every other sign-in of Sam's ends.
    now = {"Authorization": f"Bearer {changed.json()['token']}"}
    assert app_.get("/api/internal/me", headers=now).json()["user"]["name"] == "Sam"
    assert app_.get("/api/internal/me", headers=sams).status_code == 401
    other = {"Authorization": f"Bearer {tablet.json()['token']}"}
    assert app_.get("/api/internal/me", headers=other).status_code == 401
    assert page.get("/api/channels").status_code == 401
    new_one = {**SAM, "password": "a new one!"}
    assert browser(app).post("/api/access/sign-in", json=new_one).is_success
    apps = [a["app"] for a in pat.get("/api/access/apps").json() if a["user"] == "Sam"]
    assert apps == ["StationPlay for Android on Sam’s phone"]
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "Sam changed their password in StationPlay for Android on Sam’s phone" in log

    # An Admin turns it off for Sam: refused in the app and on the page.
    sam_id = next(u["id"] for u in pat.get("/api/access/users").json() if u["name"] == "Sam")
    off = pat.put(f"/api/access/users/{sam_id}", json={"canChangePassword": False})
    assert off.status_code == 200 and off.json()["canChangePassword"] is False
    assert app_.get("/api/internal/me", headers=now).json()["user"]["canChangePassword"] is False
    refused = app_.post(
        "/api/internal/password", json={"current": "a new one!", "new": "another one"},
        headers=now,
    )  # fmt: skip
    assert refused.status_code == 403 and refused.json()["detail"] == access.OWN_PASSWORD_OFF
    on_page = browser(app)
    on_page.post("/api/access/sign-in", json=new_one)
    refused = on_page.post(
        "/api/access/me/password", json={"current": "a new one!", "password": "another one"}
    )
    assert refused.status_code == 403 and refused.json()["detail"] == access.OWN_PASSWORD_OFF
    assert browser(app).post("/api/access/sign-in", json=new_one).is_success
    # (A User can't turn it back on; an Admin can.)
    back_on = {"canChangePassword": True}
    assert on_page.put(f"/api/access/users/{sam_id}", json=back_on).status_code == 403
    assert pat.put(f"/api/access/users/{sam_id}", json=back_on).is_success
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "Pat stopped Sam from changing their own password" in log
    assert "Pat let Sam change their own password" in log

    # An Admin can always change their own.
    pat_id = pat.get("/api/access/me").json()["user"]["id"]
    assert pat.put(f"/api/access/users/{pat_id}", json={"canChangePassword": False}).is_success
    mine = pat.post(
        "/api/access/me/password", json={"current": PAT["password"], "password": "pat's new one"}
    )
    assert mine.status_code == 200


def test_no_password_to_change_and_the_limit_on_wrong_ones(pat, app):
    # (Kids, on every device at home, as a household has them.)
    kids = pat.post(
        "/api/access/users", json={"name": "Kids", "role": "user", "showOn": "home"}
    ).json()
    pat.post("/api/access/users", json={**SAM, "role": "user"})
    tv = browser(app)
    key = tv.post(
        "/api/internal/sign-in", json={**PAT, "app": "StationPlay for Roku", "picker": True}
    ).json()["deviceKey"]
    picked = tv.post(
        "/api/internal/picker/choose", json={"id": kids["id"]},
        headers={"StationPlay-Device": key},
    )  # fmt: skip
    as_kids = {"Authorization": f"Bearer {picked.json()['token']}"}
    assert tv.get("/api/internal/me", headers=as_kids).json()["user"]["canChangePassword"] is False
    refused = tv.post(
        "/api/internal/password", json={"current": "", "new": "a new one!"}, headers=as_kids
    )
    assert refused.status_code == 403 and refused.json()["detail"] == access.NO_PASSWORD
    # Only from an app: not a browser's sign-in.
    from_page = {"current": PAT["password"], "new": "a new one!"}
    assert pat.post("/api/internal/password", json=from_page).status_code == 403
    # Wrong current passwords count as wrong sign-ins do.
    signed = tv.post("/api/internal/sign-in", json=SAM).json()
    sams = {"Authorization": f"Bearer {signed['token']}"}
    for _ in range(access.TRIES):
        wrong = tv.post(
            "/api/internal/password", json={"current": "guess", "new": "a new one!"}, headers=sams
        )
        assert wrong.status_code == 400
    waits = tv.post(
        "/api/internal/password", json={"current": SAM["password"], "new": "a new one!"},
        headers=sams,
    )  # fmt: skip
    assert waits.status_code == 429


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


# A visitor's address on the public port (see access.address) -----------------------

PROXY = "172.16.39.1"  # NPMplus, as its Docker network's gateway
CLOUDFLARE_EDGE, CLOUDFLARE_EDGE_6 = "172.70.42.9", "2a06:98c0:3600::103"


def coming(headers: dict[str, str] | list[tuple[str, str]], *, public: bool = True) -> dict:
    """A request as it reaches StationPlay from the proxy, with these headers:
    on the public port, or the home port."""
    pairs = headers.items() if isinstance(headers, dict) else headers
    return {
        "type": "http", "client": (PROXY, 51234), "state": {"outside": public},
        "headers": [(name.lower().encode(), value.encode()) for name, value in pairs],
    }  # fmt: skip


VISITORS = [
    # (what reaches StationPlay, the visitor's address)
    # NPMplus (and Nginx Proxy Manager) say who in X-Real-IP and X-Forwarded-For.
    ({"X-Real-IP": "203.0.113.5", "X-Forwarded-For": "203.0.113.5",
      "X-Forwarded-Proto": "https"}, "203.0.113.5"),
    # A visitor's own CF-Connecting-IP (and X-Forwarded-For) through NGINX.
    ({"CF-Connecting-IP": "198.51.100.7", "X-Real-IP": "203.0.113.5",
      "X-Forwarded-For": "198.51.100.7, 203.0.113.5"}, "203.0.113.5"),
    ({"CF-Connecting-IP": "198.51.100.7", "X-Forwarded-For": "198.51.100.7, 203.0.113.5"},
     "203.0.113.5"),
    # Only X-Forwarded-For (as Caddy sends it), and in more than one line.
    ({"X-Forwarded-For": "203.0.113.5"}, "203.0.113.5"),
    ([("X-Forwarded-For", "198.51.100.7"), ("X-Forwarded-For", "203.0.113.5")], "203.0.113.5"),
    # Cloudflare in front of NGINX: NGINX saw Cloudflare, which says who.
    ({"CF-Connecting-IP": "203.0.113.5", "X-Real-IP": CLOUDFLARE_EDGE,
      "X-Forwarded-For": f"203.0.113.5, {CLOUDFLARE_EDGE}"}, "203.0.113.5"),
    ({"CF-Connecting-IP": "203.0.113.5", "X-Forwarded-For": f"198.51.100.7, {CLOUDFLARE_EDGE}"},
     "203.0.113.5"),
    ({"CF-Connecting-IP": "2001:db8::5", "X-Real-IP": CLOUDFLARE_EDGE_6}, "2001:db8::5"),
    # A Cloudflare Tunnel straight to StationPlay.
    ({"CF-Connecting-IP": "203.0.113.5", "CF-Visitor": '{"scheme":"https"}'}, "203.0.113.5"),
    ({"CF-Connecting-IP": "203.0.113.5", "X-Forwarded-For": "203.0.113.5"}, "203.0.113.5"),
    # IPv6, and IPv4 in IPv6's form.
    ({"X-Real-IP": "2001:DB8::5"}, "2001:db8::5"),
    ({"X-Forwarded-For": "203.0.113.9, 2001:db8::5"}, "2001:db8::5"),
    ({"X-Real-IP": "::ffff:203.0.113.5"}, "203.0.113.5"),
    # Anything but an IP address: where the request came from, then.
    ({"X-Real-IP": "not an address", "X-Forwarded-For": "203.0.113.5"}, PROXY),
    ({"X-Forwarded-For": "203.0.113.5, unknown"}, PROXY),
    ({"X-Forwarded-For": "203.0.113.5:4711"}, PROXY),
    ({"X-Forwarded-For": "203.0.113.5,"}, PROXY),
    ({"X-Real-IP": "[2001:db8::5]"}, PROXY),
    ({"X-Real-IP": "fe80::1%eth0 is me"}, PROXY),
    ({"X-Real-IP": ""}, PROXY),
    ({"CF-Connecting-IP": "203.0.113.5<b>"}, PROXY),
    ({"CF-Connecting-IP": "garbage", "X-Real-IP": CLOUDFLARE_EDGE}, PROXY),
    ({}, PROXY),
]  # fmt: skip


@pytest.mark.parametrize(("headers", "visitor"), VISITORS)
def test_a_visitors_address_is_the_one_the_nearest_proxy_saw(headers, visitor):
    request = coming(headers)
    assert access.address(request) == visitor
    assert access.where(request) == f"{visitor} (over the internet)"
    # The home port never takes a header's word for it.
    at_home = coming(headers, public=False)
    assert access.address(at_home) == PROXY


def test_the_access_log_names_visitors_through_a_reverse_proxy(tmp_path):
    public_port = 3311
    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
        public_port=public_port,
    )  # fmt: skip
    app = create_app(
        settings, PlexClient("http://plex.test", "token", transport=FakePlex().transport())
    )

    def through_npmplus(address: str, **more: str) -> TestClient:
        said = {"X-Real-IP": address, "X-Forwarded-For": address, "X-Forwarded-Proto": "https"}
        return TestClient(app, base_url=f"http://testserver:{public_port}", headers=said | more)

    with TestClient(app) as home:
        assert home.post("/api/access/users", json=PAT).status_code == 201
        guesser = through_npmplus("198.51.100.7")
        for _ in range(access.TRIES):
            wrong = guesser.post("/api/access/sign-in", json={**PAT, "password": "nope nope"})
            assert wrong.status_code == 401
        assert guesser.post("/api/access/sign-in", json=PAT).status_code == 429
        # Saying it's someone else, as Cloudflare would, doesn't help.
        forged = through_npmplus("198.51.100.7", **{"CF-Connecting-IP": "203.0.113.99"})
        assert forged.post("/api/access/sign-in", json=PAT).status_code == 429
        # Others aren't held up by it.
        signed = through_npmplus("203.0.113.5").post("/api/access/sign-in", json=PAT)
        assert signed.status_code == 200
        # At home, the proxy's word isn't taken.
        lying = TestClient(app, headers={"X-Real-IP": "203.0.113.5"})
        wrong = lying.post("/api/access/sign-in", json={**PAT, "password": "nope nope"})
        assert wrong.status_code == 401
        log = home.get("/api/logs?access_log=true").json()["text"]
    assert "Failed sign-in as 'Pat' from 198.51.100.7 (over the internet)" in log
    assert "Pat (Admin) signed in from 203.0.113.5 (over the internet)" in log
    assert "Failed sign-in as 'Pat' from testclient" in log
    assert "203.0.113.99" not in log


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
    for bad in (2, 26, -1):
        assert pat.put(f"/api/access/users/{sid}", json={"maxStations": bad}).status_code == 400
    # None: they only watch.
    assert pat.put(f"/api/access/users/{sid}", json={"maxStations": 0}).status_code == 200
    refused = station(sam, 16)
    assert refused.status_code == 403
    assert (
        refused.json()["detail"] == "You can watch stations, but an Admin hasn't let you make any"
    )
    pat.put(f"/api/access/users/{sid}", json={"maxStations": None})
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


# Signed out after an hour without activity (see access.IDLE_SIGN_OUT_S) -------------

HOUR_MS = access.IDLE_SIGN_OUT_S * 1000
IDLE_LINE = "Pat was signed out after an hour without activity"


@pytest.fixture
def clock(monkeypatch):
    """StationPlay's clock for sign-ins, as a test moves it on: [now, in ms]."""
    now = [access._now()]
    monkeypatch.setattr(access, "_now", lambda: now[0])
    return now


def test_a_browser_is_signed_out_after_an_hour_without_activity(clock, pat, app):
    assert pat.get("/api/access/me").json()["idleLeftMs"] == HOUR_MS
    # The page's polling only reads: however often, it doesn't count.
    for minutes in range(5, 60, 5):
        clock[0] += 5 * 60_000
        polled = pat.get("/api/access/me").json()
        assert polled["user"]["name"] == "Pat"
        assert polled["idleLeftMs"] == HOUR_MS - minutes * 60_000
        assert pat.get("/api/status").status_code == 200
        assert pat.get("/api/channels").status_code == 200
    clock[0] += 5 * 60_000 + 1
    # Its next request ends it, and the page is told why.
    assert pat.get("/api/access/me").json() == {"required": True, "user": None, "idle": True}
    # It's over: nothing brings it back, and each request is told why.
    for _ in range(3):
        refused = pat.get("/api/channels")
        assert refused.status_code == 401 and refused.json()["detail"] == access.IDLE_SIGNED_OUT
        assert pat.post("/api/access/active").status_code == 401
        assert pat.get("/api/access/me").json() == {"required": True, "user": None, "idle": True}
    # The access log says so, once.
    assert pat.post("/api/access/sign-in", json=PAT).status_code == 200
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert log.count(IDLE_LINE) == 1


def test_the_page_is_told_why_even_when_loading_it_ends_the_sign_in(clock, pat, app):
    clock[0] += HOUR_MS + 1
    page = pat.get("/")
    assert page.status_code == 200 and access.IDLE_SIGNED_OUT in page.text
    assert pat.get("/api/access/me").json() == {"required": True, "user": None, "idle": True}
    # Another browser that's been used meanwhile isn't.
    other = browser(app)
    assert other.post("/api/access/sign-in", json=PAT).status_code == 200
    assert other.get("/api/access/me").json()["idleLeftMs"] == HOUR_MS


def test_using_the_page_keeps_a_browser_signed_in(clock, pat, app):
    assert pat.post("/api/access/users", json={**SAM, "role": "user"}).status_code == 201
    sam = browser(app)
    assert sam.post("/api/access/sign-in", json=SAM).status_code == 200
    for _ in range(3):
        clock[0] += 50 * 60_000
        for someone in (pat, sam):
            used = someone.post("/api/access/active")
            assert used.status_code == 200 and used.json() == {"idleLeftMs": HOUR_MS}
    # A change sent from the page counts too (and its polling still doesn't).
    clock[0] += 50 * 60_000
    assert station(pat, 1).status_code == 201
    assert sam.get("/api/channels").status_code == 200
    clock[0] += 50 * 60_000
    assert pat.get("/api/access/me").json()["idleLeftMs"] == 10 * 60_000
    assert sam.get("/api/channels").status_code == 401  # (Sam only read)
    # A change that comes too late is turned away, and says why.
    clock[0] += 10 * 60_000 + 1
    late = station(pat, 2)
    assert late.status_code == 401 and late.json()["detail"] == access.IDLE_SIGNED_OUT
    assert pat.post("/api/access/sign-in", json=PAT).status_code == 200
    assert [c["number"] for c in pat.get("/api/channels").json()] == [1]  # (not 2)
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert log.count(IDLE_LINE) == 1
    assert log.count("Sam was signed out after an hour without activity") == 1


def test_apps_stay_signed_in_however_long_theyre_unused(clock, pat, app):
    signed = browser(app).post("/api/internal/sign-in", json={**PAT, "app": "StationPlay for Roku"})
    the_app = {"Authorization": f"Bearer {signed.json()['token']}"}
    made = pat.post("/api/api-tokens", json={"name": "Script", "scope": "viewer", "days": None})
    script = {"Authorization": f"Bearer {made.json()['token']}"}
    clock[0] += 3 * HOUR_MS
    assert browser(app).get("/api/v1/stations", headers=the_app).status_code == 200
    assert browser(app).get("/api/v1/stations", headers=script).status_code == 200
    assert pat.get("/api/channels").status_code == 401  # (the browser isn't)


def test_a_restart_doesnt_bring_back_a_browser_left_unused(clock, pat, app, tmp_path):
    busy = browser(app)
    assert busy.post("/api/access/sign-in", json=PAT).status_code == 200
    clock[0] += 30 * 60_000
    assert busy.post("/api/access/active").status_code == 200
    clock[0] += 40 * 60_000
    again = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
    )
    with TestClient(again) as restarted:

        def me(signed_in: TestClient) -> dict:
            cookie = f"stationplay_session={signed_in.cookies['stationplay_session']}"
            return restarted.get("/api/access/me", headers={"Cookie": cookie}).json()

        assert me(pat) == {"required": True, "user": None, "idle": True}
        used = me(busy)
        assert used["user"]["name"] == "Pat" and used["idleLeftMs"] == 20 * 60_000


def test_with_sign_in_off_no_one_is_signed_out(clock, app):
    with TestClient(app) as client:
        clock[0] += 3 * HOUR_MS
        assert client.get("/api/access/me").json() == {"required": False, "user": None}
        assert station(client, 1).status_code == 201
        assert client.post("/api/access/active").json() == {"idleLeftMs": None}


def test_browsers_signed_in_before_count_as_used_when_last_seen(tmp_path):
    path = tmp_path / "old.db"
    old = Database(path)
    user = old.add_user("Pat", access.hash_password(PAT["password"]), "admin", 1, None)
    old.add_session("browser", user.id, 1000, 20)
    old._conn.execute("ALTER TABLE sessions DROP COLUMN active_ms")  # (as before 1.26)
    old._conn.execute("UPDATE sessions SET seen_ms = 5000")
    old._conn.commit()
    old.close()
    upgraded = Database(path)
    found = upgraded.session_user("browser", 0)
    upgraded.close()
    assert found is not None and found.active_ms == 5000
