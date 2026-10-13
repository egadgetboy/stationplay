"""The Access tab's list of people (the owner, October 12): Change PIN for
anyone with a PIN, however they set it (in an app too); and where each
person last signed in from, under when, as the access log says it: from
the internet, marked so, as a visitor can send any X-Real-IP there (the
audit of 1.34.0); and for an app linked with a code, the device's own
address, not the browser's that entered the code."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .helpers import list_proxy

PAT = {"name": "Pat", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple", "role": "user"}
PUBLIC_PORT = 3311
PHONE = {"app": "tapiOca for Android", "deviceName": "Sam's phone"}
ACCESS_JS = Path(__file__).parent.parent / "app" / "web" / "js" / "access.js"


@pytest.fixture
def app(tmp_path):
    fp = FakePlex()
    return create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
                 public_port=PUBLIC_PORT),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )  # fmt: skip


def person(admin: TestClient, name: str) -> dict:
    return next(u for u in admin.get("/api/access/users").json() if u["name"] == name)


def test_a_pin_set_in_an_app_shows_as_change_pin(app):
    with TestClient(app) as admin:
        assert admin.post("/api/access/users", json=PAT).status_code == 201
        assert admin.post("/api/access/users", json=SAM).status_code == 201
        assert person(admin, "Sam")["pin"] is False  # (Set PIN)
        phone = TestClient(app)
        signed = phone.post("/api/internal/sign-in", json={**SAM, **PHONE}).json()
        hers = {"Authorization": f"Bearer {signed['token']}"}
        assert phone.post("/api/internal/pin", json={"pin": "2468"}, headers=hers).json() == {
            "pin": True
        }
        assert person(admin, "Sam")["pin"] is True  # (Change PIN)
        assert "u.pin ? 'Change PIN' : 'Set PIN'" in ACCESS_JS.read_text(encoding="utf-8")


def test_where_each_person_last_signed_in_from(app):
    with TestClient(app) as admin:
        assert admin.post("/api/access/users", json=PAT).status_code == 201
        assert admin.post("/api/access/users", json=SAM).status_code == 201
        assert person(admin, "Sam")["signedInFrom"] == ""  # (never)
        # From an app at home: the address it came from.
        TestClient(app, client=("192.168.1.40", 5000)).post(
            "/api/internal/sign-in", json={**SAM, **PHONE}
        )
        assert person(admin, "Sam")["signedInFrom"] == "192.168.1.40"
        # From the internet, through a proxy: the visitor's, as it saw them,
        # marked as from the internet.
        list_proxy(app, "172.18.0.2")  # (a trusted proxy, as an Admin listed it: 1.36.0)
        away = TestClient(app, base_url=f"https://testserver:{PUBLIC_PORT}",
                          client=("172.18.0.2", 5000))  # fmt: skip
        signed = away.post("/api/access/sign-in", json=SAM, headers={"X-Real-IP": "203.0.113.9"})
        assert signed.status_code == 200, signed.text
        assert person(admin, "Sam")["signedInFrom"] == "203.0.113.9 (over the internet)"
        # A wrong password changes nothing.
        TestClient(app, client=("192.168.1.99", 5000)).post(
            "/api/access/sign-in", json={**SAM, "password": "wrong"}
        )
        assert person(admin, "Sam")["signedInFrom"] == "203.0.113.9 (over the internet)"
        # A visitor saying they're at home (X-Real-IP can be anything there):
        # still marked as from the internet.
        signed = away.post("/api/access/sign-in", json=SAM, headers={"X-Real-IP": "192.168.1.5"})
        assert signed.status_code == 200, signed.text
        assert person(admin, "Sam")["signedInFrom"] == "192.168.1.5 (over the internet)"
        # At home, a device that isn't a trusted proxy is shown as itself,
        # whatever its X-Forwarded-For says (1.36.0: before, it was shown
        # as the address that header named first, an address only, the
        # 1.34.0 re-audit); one naming the internet, or anything that isn't
        # an address, is from the internet.
        door = "192.168.1.66 (from the internet, on the home port)"
        home = TestClient(app, client=("192.168.1.66", 5000))
        for said, shown in (
            ("Admin laptop in the kitchen, 1.2.3.4", door),
            ("<b>1.2.3.4</b>", door),
            ("192.168.1.23, 10.0.0.1", "192.168.1.66"),
            ("2001:db8::5", door),
        ):
            signed = home.post("/api/access/sign-in", json=SAM, headers={"X-Forwarded-For": said})
            assert signed.status_code == 200, signed.text
            assert person(admin, "Sam")["signedInFrom"] == shown, said
        # Through a trusted proxy at home: the visitor it added (the last
        # address: those before it are anything a visitor sent), via it.
        list_proxy(app, "192.168.1.66")
        signed = home.post(
            "/api/access/sign-in", json=SAM, headers={"X-Forwarded-For": "192.168.1.23, 10.0.0.1"}
        )
        assert signed.status_code == 200, signed.text
        assert person(admin, "Sam")["signedInFrom"] == "10.0.0.1 (via 192.168.1.66)"
        # Only Admins see the list.
        sam = TestClient(app)
        assert sam.post("/api/access/sign-in", json=SAM).status_code == 200
        assert sam.get("/api/access/users").status_code == 403
        # The page shows it under when.
        assert "u.signedInFrom" in ACCESS_JS.read_text(encoding="utf-8")


def test_an_app_linked_with_a_code_is_where_the_device_is(app):
    """(The audit of 1.34.0: the address kept was the browser's, where the
    code was entered.)"""
    with TestClient(app) as admin:
        assert admin.post("/api/access/users", json=PAT).status_code == 201
        assert admin.post("/api/access/users", json=SAM).status_code == 201
        browser = TestClient(app, client=("192.168.1.10", 5000))
        assert browser.post("/api/access/sign-in", json=SAM).status_code == 200
        assert person(admin, "Sam")["signedInFrom"] == "192.168.1.10"
        tv = TestClient(app, client=("192.168.1.77", 5000))
        started = tv.post("/api/internal/link", json={"app": "tapiOca for Roku",
                                                      "deviceName": "Den Roku"}).json()  # fmt: skip
        assert browser.post("/api/access/link", json={"code": started["code"]}).status_code == 200
        assert person(admin, "Sam")["signedInFrom"] == "192.168.1.77"
        # A TV away from home, asking through the public port: marked so.
        list_proxy(app, "172.18.0.2")  # (a trusted proxy, as an Admin listed it: 1.36.0)
        away = TestClient(app, base_url=f"https://testserver:{PUBLIC_PORT}",
                          client=("172.18.0.2", 5000))  # fmt: skip
        started = away.post("/api/internal/link", headers={"X-Real-IP": "198.51.100.4"},
                            json={"app": "tapiOca for Roku", "deviceName": "Cabin"}).json()  # fmt: skip
        assert browser.post("/api/access/link", json={"code": started["code"]}).status_code == 200
        assert person(admin, "Sam")["signedInFrom"] == "198.51.100.4 (over the internet)"
