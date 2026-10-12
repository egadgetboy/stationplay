"""Signing in with a PIN on StationPlay's page (see access.py's
pin_sign_in): at home, on a browser its person signed in on with their
password; never from the internet."""

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
    """Pat, StationPlay's first user (an Admin), signed in, with PIN 4321;
    and Sam, a User, with PIN 1234."""
    with TestClient(app) as client:
        made = client.post("/api/access/users", json=PAT)
        assert made.status_code == 201, made.text
        assert (
            client.put(
                f"/api/access/users/{made.json()['id']}/picker", json={"pin": "4321"}
            ).status_code
            == 200
        )
        sam = client.post("/api/access/users", json={**SAM, "role": "user"})
        assert sam.status_code == 201, sam.text
        assert (
            client.put(
                f"/api/access/users/{sam.json()['id']}/picker", json={"pin": "1234"}
            ).status_code
            == 200
        )
        yield client


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
    me = browser.get("/api/access/me").json()
    assert me["pinFor"] == "Pat"
    got = browser.post("/api/access/pin-sign-in", json={"pin": "4321"})
    assert got.status_code == 200, got.text
    assert got.json()["user"]["name"] == "Pat"
    me = browser.get("/api/access/me").json()
    assert me["user"]["name"] == "Pat" and "pinFor" not in me
    assert browser.get("/api/logs").status_code == 200  # (an Admin, as with a password)
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "Pat (Admin) signed in with their PIN from testclient" in log


def test_a_user_with_a_pin_too(pat, app):
    browser = signed_out(signed_in_with_password(app, SAM))
    assert browser.get("/api/access/me").json()["pinFor"] == "Sam"
    assert browser.post("/api/access/pin-sign-in", json={"pin": "1234"}).status_code == 200
    assert browser.get("/api/logs").status_code == 403  # (a User, as with a password)


def test_only_on_a_browser_they_signed_in_on_with_their_password(pat, app):
    fresh = TestClient(app)
    assert "pinFor" not in fresh.get("/api/access/me").json()
    refused = fresh.post("/api/access/pin-sign-in", json={"pin": "4321"})
    assert refused.status_code == 400
    assert refused.json()["detail"].startswith("Sign in with your password on this browser first")
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
    assert "pinFor" not in browser.get("/api/access/me").json()
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
    assert "Wrong PIN for Pat on StationPlay's page, from testclient" in log
    assert "Too many wrong PINs for Pat: they wait 15 minutes" in log
    # Not a PIN at all counts as wrong too.
    assert (
        TestClient(app).post("/api/access/pin-sign-in", json={"pin": "x" * 21}).status_code == 422
    )


def test_signing_out_on_purpose_needs_the_password_next_time(pat, app):
    browser = signed_in_with_password(app)
    assert browser.post("/api/access/sign-out").status_code == 200
    assert "pinFor" not in browser.get("/api/access/me").json()
    assert browser.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 400


def test_signing_out_keeps_the_browser_known_for_the_internets_limit(pat, app):
    """The audit of 1.32.0: signing out on purpose forgot the browser
    altogether, so from the internet, strangers' wrong passwords could keep
    its person out again (see access.py's DEVICE_COOKIE). Its PIN needs the
    password again; it's still theirs for the limit on tries."""
    browser = signed_in_with_password(app)
    assert browser.post("/api/access/sign-out").status_code == 200
    kept = browser.cookies.get(access.DEVICE_COOKIE)
    assert kept and app.state.ctx.access.known_device(kept, "Pat")
    assert app.state.ctx.access.pin_browser(kept) is None
    assert browser.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 400
    # The password there again, and its PIN works there again.
    assert browser.post("/api/access/sign-in", json=PAT).status_code == 200
    assert signed_out(browser).get("/api/access/me").json()["pinFor"] == "Pat"


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
    assert app.state.ctx.access.pin_browser(known) is None


def test_a_new_password_needs_the_new_one_first(pat, app):
    other = signed_out(signed_in_with_password(app))
    mine = signed_in_with_password(app)
    changed = mine.post(
        "/api/access/me/password", json={"current": PAT["password"], "password": "new horse staple"}
    )
    assert changed.status_code == 200, changed.text
    # Browsers that knew the old one: the new one first.
    assert "pinFor" not in other.get("/api/access/me").json()
    assert other.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 400
    # The browser it was changed on did, so its PIN works there.
    assert signed_out(mine).get("/api/access/me").json()["pinFor"] == "Pat"
    assert mine.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 200


def test_without_a_pin_its_the_password(pat, app):
    me = pat.get("/api/access/me").json()["user"]
    assert pat.put(f"/api/access/users/{me['id']}/picker", json={"pin": ""}).status_code == 200
    browser = signed_out(signed_in_with_password(app))
    assert "pinFor" not in browser.get("/api/access/me").json()
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
    assert "pinFor" not in browser.get("/api/access/me").json()
    picker._wrong.clear()
    assert browser.post("/api/access/pin-sign-in", json={"pin": "4321"}).status_code == 400
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "10 wrong PINs for Pat on a browser at testclient: it needs the password now" in log
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
    assert "pinFor" not in browser.get("/api/access/me").json()


def test_browsers_known_before_1_32_need_the_password_once(tmp_path):
    """Upgrading: a browser someone signed in on before 1.32.0 is still
    theirs (for the internet's limit on tries), and their PIN signs in there
    once they've used their password there again."""
    path = tmp_path / "old.db"
    old = Database(path)
    user = old.add_user("Pat", access.hash_password(PAT["password"]), "admin", 1, None, "x")
    old.add_device("browser", user.id, 1000, 20)
    old._conn.execute("ALTER TABLE devices DROP COLUMN pin_ok")  # (as before 1.32.0)
    old._conn.commit()
    old.close()
    upgraded = Database(path)
    try:
        assert upgraded.device_user("browser") == user.id
        assert upgraded.pin_device_user("browser") is None
        upgraded.device_password_used("browser")
        assert upgraded.pin_device_user("browser") == user.id
    finally:
        upgraded.close()
