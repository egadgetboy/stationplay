"""Signing in with a PIN on tapiOca's page (see access.py's
pin_sign_in): at home, on a browser its person signed in on with their
password; never from the internet. From 1.38.0 (the owner, October 17), only
an Admin's, in Light sign-in, which gives their Admin tools (Full, the
default, asks for the password every time: test_admin_sign_in.py); a User's
PIN never signs in on the page, nor does a User show on its sign-in screen.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

PAT = {"name": "Pat", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple"}
PUBLIC_PORT = 3311


@pytest.fixture
def app(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * 60_000)
    return create_app(
        Settings(
            plex_url="http://plex.test",
            plex_token="token",
            data_dir=tmp_path / "data",
            public_port=PUBLIC_PORT,
        ),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )


@pytest.fixture
def pat(app):
    """Pat, tapiOca's first user (an Admin, in Light sign-in), signed in,
    with PIN 4321; and Sam, a User, with PIN 1234."""
    with TestClient(app) as client:
        made = client.post("/api/access/users", json=PAT)
        assert made.status_code == 201, made.text
        assert (
            client.put(
                f"/api/access/users/{made.json()['id']}/picker", json={"pin": "4321"}
            ).status_code
            == 200
        )
        light = client.put("/api/access/me/sign-in", json={"how": "light", **without_name(PAT)})
        assert light.status_code == 200, light.text
        sam = client.post("/api/access/users", json={**SAM, "role": "user"})
        assert sam.status_code == 201, sam.text
        assert (
            client.put(
                f"/api/access/users/{sam.json()['id']}/picker", json={"pin": "1234"}
            ).status_code
            == 200
        )
        yield client


def without_name(who: dict) -> dict:
    return {"password": who["password"]}


def pin_for(browser: TestClient) -> list[str]:
    """Whose PIN the browser's sign-in screen takes (1.38.0: its Admins,
    each saying whether their PIN works there; access.browser_admins)."""
    return [p["name"] for p in browser.get("/api/access/me").json().get("people", []) if p["pin"]]


def pin_works(app, device: str | None) -> list[str]:
    """pin_for, as tapiOca has it for a browser's cookie."""
    return [u.name for u, ok in app.state.ctx.access.browser_admins(device) if ok]


def signed_in_with_password(app, who=PAT, base_url: str = "http://testserver") -> TestClient:
    browser = TestClient(app, base_url=base_url)
    assert browser.post("/api/access/sign-in", json=who).status_code == 200
    assert browser.cookies.get(access.DEVICE_COOKIE)
    return browser


def signed_out(browser: TestClient) -> TestClient:
    """As after an hour without using the page: its sign-in is over (the
    browser itself is still the one they signed in on)."""
    browser.cookies.delete(access.COOKIE)
    assert browser.get("/api/access/me").json()["user"] is None
    return browser


def test_a_pin_signs_in_again_at_home(pat, app):
    browser = signed_out(signed_in_with_password(app))
    assert pin_for(browser) == ["Pat"]
    pat_id = browser.get("/api/access/me").json()["people"][0]["id"]
    got = browser.post("/api/access/pin-sign-in", json={"id": pat_id, "pin": "4321"})
    assert got.status_code == 200, got.text
    assert got.json()["user"]["name"] == "Pat"
    me = browser.get("/api/access/me").json()
    assert me["user"]["name"] == "Pat" and "people" not in me
    assert me["user"]["adminTools"] is True
    assert browser.get("/api/logs").status_code == 200  # (an Admin, as with a password)
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "Pat (Admin) signed in with their PIN from 192.168.1.50" in log


def test_a_users_pin_never_signs_in_on_the_page(pat, app):
    """(1.37.0 to 1.37.1: a User's too, and their name showed on the sign-in
    screen. 1.38.0, the owner, October 17: "No user appears on the server
    sign in page at all unless their user is set as Admin".)"""
    browser = signed_out(signed_in_with_password(app, SAM))
    assert "people" not in browser.get("/api/access/me").json()
    sam_id = next(u["id"] for u in pat.get("/api/access/users").json() if u["name"] == "Sam")
    for body in ({"pin": "1234"}, {"id": sam_id, "pin": "1234"}):
        refused = browser.post("/api/access/pin-sign-in", json=body)
        assert refused.status_code == 400 and refused.json()["detail"] == (
            "Sign in with your name and password."
        )
    assert browser.get("/api/access/me").json()["user"] is None
    # (Sam's password still signs him in, for what a User may do there.)
    assert browser.post("/api/access/sign-in", json=SAM).status_code == 200
    assert browser.get("/api/stats").status_code == 200
    assert browser.get("/api/logs").status_code == 403


def test_only_on_a_browser_they_signed_in_on_with_their_password(pat, app):
    fresh = TestClient(app)
    assert "people" not in fresh.get("/api/access/me").json()
    refused = fresh.post("/api/access/pin-sign-in", json={"pin": "4321"})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Sign in with your name and password."
    # Another person's browser is theirs: Sam's PIN won't do on Pat's.
    browser = signed_out(signed_in_with_password(app))
    assert browser.post("/api/access/pin-sign-in", json={"pin": "1234"}).status_code == 403
    assert browser.get("/api/access/me").json()["user"] is None


def test_never_from_the_internet(pat, app):
    outside = f"http://testserver:{PUBLIC_PORT}"
    browser = TestClient(app, base_url=outside)
    browser.cookies.set(
        access.DEVICE_COOKIE, signed_in_with_password(app).cookies.get(access.DEVICE_COOKIE)
    )
    assert "people" not in browser.get("/api/access/me").json()
    assert browser.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 404


def test_wrong_pins_wait_15_minutes(pat, app):
    browser = signed_out(signed_in_with_password(app))
    for _ in range(5):
        wrong = browser.post("/api/access/pin-sign-in", json={"pin": "0000"})
        assert wrong.status_code == 403 and wrong.json()["detail"] == "That PIN isn't right"
    waits = browser.post("/api/access/pin-sign-in", json={"pin": "4321"})
    assert waits.status_code == 429
    assert waits.json()["detail"].startswith("Too many wrong PINs for Pat. Try again in")
    assert browser.get("/api/access/me").json()["user"] is None
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "Wrong PIN for Pat on tapiOca's page, from 192.168.1.50" in log
    assert "Too many wrong PINs for Pat: they wait 15 minutes" in log
    # Not a PIN at all counts as wrong too.
    assert (
        TestClient(app).post("/api/access/pin-sign-in", json={"pin": "x" * 21}).status_code == 422
    )


def test_signing_out_on_purpose_needs_the_password_next_time(pat, app):
    browser = signed_in_with_password(app)
    assert browser.post("/api/access/sign-out").status_code == 200
    # (Still on its sign-in screen, for the password: 1.38.0.)
    [pat_tile] = browser.get("/api/access/me").json()["people"]
    assert (pat_tile["name"], pat_tile["pin"]) == ("Pat", False)
    refused = browser.post("/api/access/pin-sign-in", json={"id": pat_tile["id"], "pin": "4321"})
    assert refused.status_code == 400 and refused.json()["detail"].startswith(
        "Sign in with your password on this browser first"
    )


def test_signing_out_keeps_the_browser_known_for_the_internets_limit(pat, app):
    """The audit of 1.32.0: signing out on purpose forgot the browser
    altogether, so from the internet, strangers' wrong passwords could keep
    its person out again (see access.py's DEVICE_COOKIE). Its PIN needs the
    password again; it's still theirs for the limit on tries."""
    browser = signed_in_with_password(app)
    assert browser.post("/api/access/sign-out").status_code == 200
    kept = browser.cookies.get(access.DEVICE_COOKIE)
    assert kept and app.state.ctx.access.known_device(kept, "Pat")
    assert pin_works(app, kept) == []
    assert browser.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 400
    # The password there again, and its PIN works there again.
    assert browser.post("/api/access/sign-in", json=PAT).status_code == 200
    assert pin_for(signed_out(browser)) == ["Pat"]


def test_a_new_password_keeps_other_browsers_known(pat, app):
    """The audit of 1.32.0: a new password forgot every browser its person
    had signed in on, for the internet's limit on tries too."""
    other = signed_out(signed_in_with_password(app))
    mine = signed_in_with_password(app)
    changed = mine.post(
        "/api/access/me/password", json={"current": PAT["password"], "password": "new horse staple"}
    )
    assert changed.status_code == 200, changed.text
    known = other.cookies.get(access.DEVICE_COOKIE)
    assert app.state.ctx.access.known_device(known, "Pat")
    assert pin_works(app, known) == []


def test_a_new_password_needs_the_new_one_first(pat, app):
    other = signed_out(signed_in_with_password(app))
    mine = signed_in_with_password(app)
    changed = mine.post(
        "/api/access/me/password", json={"current": PAT["password"], "password": "new horse staple"}
    )
    assert changed.status_code == 200, changed.text
    # Browsers that knew the old one: the new one first.
    assert pin_for(other) == []
    assert other.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 400
    # The browser it was changed on did, so its PIN works there.
    assert pin_for(signed_out(mine)) == ["Pat"]
    assert mine.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 200


def test_without_a_pin_its_the_password(pat, app):
    me = pat.get("/api/access/me").json()["user"]
    assert pat.put(f"/api/access/users/{me['id']}/picker", json={"pin": ""}).status_code == 200
    browser = signed_out(signed_in_with_password(app))
    assert pin_for(browser) == []
    assert browser.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 400


def test_ten_wrong_pins_on_a_browser_need_the_password(pat, app):
    """The audit of 1.32.0: five wrong PINs only meant a 15-minute wait, as
    often as wanted, so on a browser at home every PIN could be tried in
    about three weeks. After ten wrong ones on a browser, its PIN signs in
    there again only after the password."""
    browser = signed_out(signed_in_with_password(app))
    picker = app.state.ctx.access.picker
    said = []
    for _ in range(2):
        picker._wrong.clear()  # (15 minutes later)
        said.extend(browser.post("/api/access/pin-sign-in", json={"pin": "0000"}) for _ in range(5))
    assert [r.status_code for r in said] == [403] * 10
    assert all(r.json()["detail"] == "That PIN isn't right" for r in said[:9])
    assert said[9].json()["detail"] == (
        "That PIN isn't right, and that's 10 wrong PINs on this browser. Sign in with your "
        "password now."
    )
    assert pin_for(browser) == []
    picker._wrong.clear()
    assert browser.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 400
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "10 wrong PINs for Pat on a browser at 192.168.1.50: it needs the password now" in log
    # The password there again: its PIN works there again, with ten tries,
    # counted until the password signs in there again (a right PIN, perhaps
    # its person's, between someone else's guesses doesn't start them over).
    assert browser.post("/api/access/sign-in", json=PAT).status_code == 200
    signed_out(browser)
    for _ in range(9):
        picker._wrong.clear()
        assert browser.post("/api/access/pin-sign-in", json={"pin": "0000"}).status_code == 403
    assert browser.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 200
    signed_out(browser)
    last = browser.post("/api/access/pin-sign-in", json={"pin": "0000"})
    assert last.json()["detail"].startswith("That PIN isn't right, and that's 10 wrong PINs")
    assert pin_for(browser) == []


def test_browsers_known_before_1_32_need_the_password_once(tmp_path):
    """Upgrading: a browser someone signed in on before 1.32.0 is still
    theirs (for the internet's limit on tries), and their PIN signs in there
    once they've used their password there again. (From 1.38.0 a browser
    may be several people's: browser_people, which starts with devices'.)"""
    path = tmp_path / "old.db"
    old = Database(path)
    user = old.add_user("Pat", access.hash_password(PAT["password"]), "admin", 1, None, "x")
    old._conn.execute("DROP TABLE browser_people")  # (as before 1.38.0)
    old._conn.execute(
        "INSERT INTO devices (token_hash, user_id, created_ms, pin_ok) VALUES ('browser', ?, 1000, 1)",
        (user.id,),
    )
    old._conn.execute("ALTER TABLE devices DROP COLUMN pin_ok")  # (as before 1.32.0)
    old._conn.commit()
    old.close()
    upgraded = Database(path)
    try:
        assert upgraded.browser_people("browser") == [(user.id, False)]
        upgraded.add_browser_person("browser", user.id, 2000, 20, 10)
        assert upgraded.browser_people("browser") == [(user.id, True)]
    finally:
        upgraded.close()


def test_browsers_known_before_1_38_keep_their_person_and_pin(tmp_path):
    """Upgrading from 1.37.1: each browser someone signed in on is still
    theirs, and their PIN still works where it did (and, from 1.38.0, only
    in Light sign-in). devices is kept as it was, for going back."""
    path = tmp_path / "old.db"
    old = Database(path)
    pat = old.add_user("Pat", access.hash_password(PAT["password"]), "admin", 1, None, "x")
    sam = old.add_user("Sam", access.hash_password(SAM["password"]), "user", 1, None, "x")
    old._conn.execute("DROP TABLE browser_people")  # (as before 1.38.0)
    old._conn.executemany(
        "INSERT INTO devices (token_hash, user_id, created_ms, pin_ok) VALUES (?, ?, ?, ?)",
        [("pat's", pat.id, 1000, 1), ("pat's old", pat.id, 900, 0), ("sam's", sam.id, 1100, 1)],
    )
    old._conn.commit()
    old.close()
    upgraded = Database(path)
    try:
        assert upgraded.browser_people("pat's") == [(pat.id, True)]
        assert upgraded.browser_people("pat's old") == [(pat.id, False)]
        assert upgraded.browser_people("sam's") == [(sam.id, True)]
        assert upgraded.user(pat.id).admin_sign_in == "full"
        kept = upgraded._conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        assert kept == 3
    finally:
        upgraded.close()


def test_signing_out_on_purpose_still_needs_the_password_after_the_page_asked(pat, app):
    """Being signed in makes a browser theirs only while it is: signed out
    on purpose, it needs the password, however often the page asks."""
    browser = signed_in_with_password(app)
    assert browser.get("/api/access/me").json()["user"]["name"] == "Pat"
    assert browser.post("/api/access/sign-out").status_code == 200
    for _ in range(2):
        assert pin_for(browser) == []


def _cookie_from(response, name: str) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(name + "="):
            return header.split(";", 1)[0].split("=", 1)[1]
    return None


def test_a_copied_sign_in_never_makes_a_browser_for_the_pin(pat, app):
    """The audit of 1.33.1's first try (never shipped): a page sign-in
    copied to another browser made browsers there that took Pat's PIN, even
    after he signed out on purpose. Only a password typed on a browser makes
    it take the PIN."""
    victim = signed_in_with_password(app)
    thief = TestClient(app)
    thief.cookies.set(access.COOKIE, victim.cookies.get(access.COOKIE))
    for _ in range(3):
        got = thief.get("/api/access/me")
        assert got.json()["user"]["name"] == "Pat"
        assert _cookie_from(got, access.DEVICE_COOKIE) is None
    assert victim.post("/api/access/sign-out").status_code == 200
    thief.cookies.delete(access.COOKIE)
    assert "people" not in thief.get("/api/access/me").json()
    assert thief.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 400


def test_ten_wrong_pins_need_the_password_however_often_the_page_asks(pat, app):
    browser = signed_in_with_password(app)
    picker = app.state.ctx.access.picker
    for _ in range(2):
        picker._wrong.clear()
        for _ in range(5):
            browser.post("/api/access/pin-sign-in", json={"pin": "0000"})
    device = browser.cookies.get(access.DEVICE_COOKIE)
    assert pin_works(app, device) == []
    browser.get("/api/access/me")
    assert pin_works(app, device) == []


def test_the_sign_in_page_says_where_the_pin_works(pat, app):
    """The owner's report (October 12): at home, through his internet
    address (his proxy, so tapiOca's public port), the page asked for
    his password, not his PIN. From the internet it always does; the page
    now says the PIN works at tapiOca's home address."""
    home = signed_out(signed_in_with_password(app))
    assert "outside" not in home.get("/api/access/me").json()
    away = TestClient(app, base_url=f"http://testserver:{PUBLIC_PORT}")
    me = away.get("/api/access/me").json()
    assert me["user"] is None and me.get("outside") is True and "people" not in me


def test_from_the_internet_before_the_first_user_the_page_knows_its_the_internet(app):
    """1.33.1's audit: before there's a user, the public port's answer said
    nothing of where it was, so the page showed the at-home PIN note there
    (where the PIN never works)."""
    with TestClient(app):
        away = TestClient(app, base_url=f"http://testserver:{PUBLIC_PORT}")
        me = away.get("/api/access/me").json()
        assert me["notSetUp"] and me["user"] is None and me.get("outside") is True


def test_asking_who_is_signed_in_never_makes_a_browser_take_the_pin(pat, app):
    """The audit of 1.33.1: /api/access/me never remembers a browser or lets
    one take the PIN, at home or from the internet, with a page sign-in or
    an app's (Bearer) one, with or without a browser cookie: only a password
    typed on a browser does that."""
    ctx = app.state.ctx

    def devices() -> list[tuple]:
        return [tuple(r) for r in ctx.db._conn.execute(
            "SELECT token_hash, user_id, pin_ok FROM browser_people ORDER BY token_hash")]  # fmt: skip

    browser = signed_in_with_password(app)
    session = browser.cookies.get(access.COOKIE)
    ctx.db._conn.execute("UPDATE browser_people SET pin_ok = 0")
    ctx.db._conn.commit()
    app_token = (
        TestClient(app)
        .post("/api/internal/sign-in", json={**SAM, "app": "tapiOca for Roku", "deviceName": "TV"})
        .json()["token"]
    )
    before = devices()
    for base in ("http://testserver", f"http://testserver:{PUBLIC_PORT}"):
        for device in (browser.cookies.get(access.DEVICE_COOKIE), None):
            client = TestClient(app, base_url=base)
            client.cookies.set(access.COOKIE, session)
            if device:
                client.cookies.set(access.DEVICE_COOKIE, device)
            for headers in ({}, {"Authorization": f"Bearer {app_token}"}):
                got = client.get("/api/access/me", headers=headers)
                assert got.status_code == 200
                assert _cookie_from(got, access.DEVICE_COOKIE) is None
    assert devices() == before


def test_the_sign_in_page_shows_where_the_pin_works():
    """What the sign-in page shows, from the internet and at home (the
    owner's report, October 12; from 1.38.0, an Admin's PIN, in Light
    sign-in, the owner, October 17)."""
    from .test_web_app import PAGE, WEB_DIR

    assert (
        '<p class="hint" id="signinWhere" hidden>At this address, tapiOca always asks for your password, even at home.'
        in PAGE
    )
    assert (
        '<p class="hint" id="signinHome" hidden>An Admin with Light sign-in can use their PIN here after signing in once on this browser with their password.</p>'
        in PAGE
    )
    script = (WEB_DIR / "js" / "access.js").read_text(encoding="utf-8")
    assert "$('#signinWhere').hidden = !me.outside || !!me.notSetUp;" in script
    assert "$('#signinHome').hidden = !!me.outside || !me.required;" in script
    # (Hidden once Who's signing in? lists someone: see showPeople.)
    people = script.split("function showPeople(list) {", 1)[1].split("\n}\n", 1)[0]
    assert "$('#signinHome').hidden = true;" in people
