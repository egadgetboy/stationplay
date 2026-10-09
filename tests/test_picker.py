"""Linked devices and their "Who's tuning in?" picker (see devices.py): who's
on a device's list, picking yourself (with a PIN, or an Admin's password),
signing in by name with an invite code or a password, taking yourself off,
and an Admin unlinking a device."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import access, devices
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

ADA = {"name": "Ada", "password": "correct horse"}
TV = {"app": "StationPlay for Roku", "deviceName": "Living Room Roku", "picker": True}
PUBLIC_PORT = 8443


@pytest.fixture
def app(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep", "/x/1.mkv", 22 * 60_000)
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    return create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))


def two_ports(tmp_path):
    """StationPlay with a public port, as a reverse proxy reaches it from
    the internet."""
    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
        public_port=PUBLIC_PORT,
    )  # fmt: skip
    return create_app(
        settings, PlexClient("http://plex.test", "token", transport=FakePlex().transport())
    )


def away_from_home(app) -> TestClient:
    """A device away from home: through the public port, over HTTPS, as
    the reverse proxy in front says."""
    return TestClient(
        app,
        base_url=f"http://testserver:{PUBLIC_PORT}",
        headers={"X-Forwarded-Proto": "https", "X-Real-IP": "203.0.113.5"},
    )


def device(key: str) -> dict[str, str]:
    return {"StationPlay-Device": key}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def people(tv: TestClient, key: str) -> list[str]:
    got = tv.get("/api/internal/picker", headers=device(key))
    assert got.status_code == 200, got.text
    return [p["name"] for p in got.json()["people"]]


def test_a_household_tv(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        # Kids: no password, no PIN, on every device. Tia: a password and a
        # PIN, only where she signs in.
        kids = admin.post("/api/access/users", json={"name": "Kids", "role": "user"})
        assert kids.status_code == 201, kids.text
        assert not kids.json()["hasPassword"] and kids.json()["showOn"] == "home"
        tia = admin.post(
            "/api/access/users",
            json={"name": "Tia", "password": "teen password", "role": "user", "pin": "4321",
                  "showOn": "signed-in"},
        )  # fmt: skip
        assert tia.status_code == 201 and tia.json()["pin"], tia.text
        tv = TestClient(app)

        # Ada links the TV by signing in on it.
        signed = tv.post("/api/internal/sign-in", json={**ADA, **TV}).json()
        key = signed["deviceKey"]
        assert key and signed["user"]["name"] == "Ada"
        assert people(tv, key) == ["Ada", "Kids"]
        listed = admin.get("/api/access/devices").json()["devices"]
        assert [(x["name"], x["linkedBy"], x["people"]) for x in listed] == [
            ("StationPlay for Roku on Living Room Roku", "Ada", ["Ada", "Kids"])
        ]
        # Signing in again with the key: the same device.
        again = tv.post("/api/internal/sign-in", json={**ADA, **TV, "deviceKey": key}).json()
        assert (
            again["deviceKey"] is None
            and len(admin.get("/api/access/devices").json()["devices"]) == 1
        )

        # Kids: picked, no PIN. Ada: an Admin, so her password.
        kids_id = kids.json()["id"]
        picked = tv.post("/api/internal/picker/choose", json={"id": kids_id}, headers=device(key))
        assert picked.status_code == 200 and picked.json()["user"]["name"] == "Kids"
        as_kids = bearer(picked.json()["token"])
        assert tv.get("/api/v1/stations", headers=as_kids).status_code == 200
        ada_id = next(u["id"] for u in admin.get("/api/access/users").json() if u["name"] == "Ada")
        refused = tv.post("/api/internal/picker/choose", json={"id": ada_id}, headers=device(key))
        assert refused.status_code == 403 and "password" in refused.json()["detail"]
        ada = tv.post(
            "/api/internal/picker/choose",
            json={"id": ada_id, "password": ADA["password"]},
            headers=device(key),
        )
        assert ada.status_code == 200
        # (Picking someone ends whoever was signed in on the TV before.)
        assert tv.get("/api/v1/stations", headers=as_kids).status_code == 401

        # Kids can't sign in by name; Tia can, then switches with her PIN.
        no = tv.post(
            "/api/internal/picker/sign-in",
            json={"name": "Kids", "password": ""},
            headers=device(key),
        )
        assert no.status_code == 403
        tia_in = tv.post(
            "/api/internal/picker/sign-in",
            json={"name": "Tia", "password": "teen password"},
            headers=device(key),
        )
        assert tia_in.status_code == 200, tia_in.text
        assert people(tv, key) == ["Ada", "Kids", "Tia"]
        tia_id = tia.json()["id"]
        for _ in range(devices.PIN_TRIES):
            wrong = tv.post(
                "/api/internal/picker/choose",
                json={"id": tia_id, "pin": "0000"},
                headers=device(key),
            )
            assert wrong.status_code == 403 and wrong.json()["detail"] == "That PIN isn't right"
        waits = tv.post(
            "/api/internal/picker/choose", json={"id": tia_id, "pin": "4321"}, headers=device(key)
        )
        assert waits.status_code == 429 and "15 minutes" in waits.json()["detail"]
        app.state.ctx.devices._wrong.clear()  # (15 minutes later)
        right = tv.post(
            "/api/internal/picker/choose", json={"id": tia_id, "pin": "4321"}, headers=device(key)
        )
        assert right.status_code == 200

        # Tia takes herself off the TV.
        gone = tv.post(
            "/api/internal/picker/remove",
            headers={**device(key), **bearer(right.json()["token"])},
        )
        assert gone.status_code == 200 and people(tv, key) == ["Ada", "Kids"]

        # Ada unlinks it: it's signed out, and its key no longer works.
        assert admin.delete(f"/api/access/devices/{listed[0]['id']}").status_code == 204
        assert tv.get("/api/internal/picker", headers=device(key)).status_code == 401
        assert tv.get("/api/v1/stations", headers=bearer(ada.json()["token"])).status_code == 401
        log = admin.get("/api/logs?access_log=true").json()["text"]
        assert "Ada unlinked StationPlay for Roku on Living Room Roku" in log
        assert "Too many wrong PINs for Tia: they wait 15 minutes" in log


def test_an_invite_code_works_once(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        lu = admin.post(
            "/api/access/users",
            json={"name": "Lu", "role": "user", "pin": "1111", "showOn": "signed-in"},
        ).json()
        tv = TestClient(app)
        key = tv.post("/api/internal/sign-in", json={**ADA, **TV}).json()["deviceKey"]
        assert people(tv, key) == ["Ada"]
        made = admin.post(f"/api/access/users/{lu['id']}/invite").json()
        assert len(made["code"]) == 9 and made["code"][4] == "-"
        signed = tv.post(
            "/api/internal/picker/sign-in",
            json={"name": "Lu", "secret": made["code"].lower()},  # (typed in one box)
            headers=device(key),
        )
        assert signed.status_code == 200, signed.text
        assert people(tv, key) == ["Ada", "Lu"]
        again = tv.post(
            "/api/internal/picker/sign-in",
            json={"name": "Lu", "code": made["code"]},
            headers=device(key),
        )
        assert again.status_code == 403
        # A code is no use without a linked device.
        assert (
            TestClient(app)
            .post("/api/internal/picker/sign-in", json={"name": "Lu", "code": made["code"]})
            .status_code
            == 401
        )


def test_who_can_be_shown_where(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        # No password, no PIN, only where they sign in: they never could.
        refused = admin.post(
            "/api/access/users", json={"name": "Kids", "role": "user", "showOn": "signed-in"}
        )
        assert refused.status_code == 400 and "PIN or a password" in refused.json()["detail"]
        assert [u["name"] for u in admin.get("/api/access/users").json()] == ["Ada"]
        # An Admin always has a password.
        assert (
            admin.post("/api/access/users", json={"name": "Al", "role": "admin"}).status_code == 400
        )
        kids = admin.post("/api/access/users", json={"name": "Kids", "role": "user"}).json()
        made_admin = admin.put(f"/api/access/users/{kids['id']}", json={"role": "admin"})
        assert made_admin.status_code == 400 and "password" in made_admin.json()["detail"]
        # Nor on devices away from home that no one chose for them.
        everywhere = admin.put(f"/api/access/users/{kids['id']}/picker", json={"showOn": "all"})
        assert everywhere.status_code == 400 and "away from home" in everywhere.json()["detail"]
        assert admin.post(
            "/api/access/sign-in", json={"name": "Kids", "password": ""}
        ).status_code in (401, 422)

        # A larger server: new people shown only where they sign in (those
        # already added stay where they are).
        assert (
            admin.put("/api/access/devices/default", json={"showOn": "signed-in"}).status_code
            == 200
        )
        tv = TestClient(app)
        key = tv.post("/api/internal/sign-in", json={**ADA, **TV}).json()["deviceKey"]
        assert people(tv, key) == ["Ada", "Kids"]
        bo = admin.post(
            "/api/access/users", json={"name": "Bo", "password": "bo password", "role": "user"}
        )
        assert bo.json()["showOn"] == "signed-in"
        assert (
            admin.post("/api/access/users", json={"name": "Cy", "role": "user"}).status_code == 400
        )
        # An Admin chooses devices for Kids.
        tv_id = admin.get("/api/access/devices").json()["devices"][0]["id"]
        chose = admin.put(
            f"/api/access/users/{kids['id']}/picker",
            json={"showOn": "selected", "devices": [tv_id]},
        )
        assert chose.status_code == 200, chose.text
        assert people(tv, key) == ["Ada", "Kids"]
        assert admin.get("/api/access/devices").json()["chosen"] == {str(kids["id"]): [tv_id]}
        assert (
            admin.put(f"/api/access/users/{kids['id']}/picker", json={"pin": "12"}).json()["detail"]
            == "A PIN is 4 digits"
        )


def test_an_admin_alone_on_a_device_needs_no_password_to_pick_themselves(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        tv = TestClient(app)
        key = tv.post("/api/internal/sign-in", json={**ADA, **TV}).json()["deviceKey"]
        [ada] = tv.get("/api/internal/picker", headers=device(key)).json()["people"]
        picked = tv.post("/api/internal/picker/choose", json={"id": ada["id"]}, headers=device(key))
        assert picked.status_code == 200


def test_an_admin_on_someone_elses_device_still_needs_their_password(app):
    """A device another user linked and uses is not the Admin's own, even
    once that user takes themselves off its list: the Admin still needs their
    password to pick themselves there, so no one links a TV and taps the
    Admin to become one."""
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        sam = admin.post(
            "/api/access/users", json={"name": "Sam", "password": "battery staple", "role": "user"}
        )
        assert sam.status_code == 201, sam.text
        tv = TestClient(app)
        signed = tv.post(
            "/api/internal/sign-in",
            json={"name": "Sam", "password": "battery staple", "picker": True},
        ).json()
        key = signed["deviceKey"]
        # Sam takes himself off, leaving the Admin alone on the picker.
        tv.post("/api/internal/picker/remove", headers={**device(key), **bearer(signed["token"])})
        [ada] = tv.get("/api/internal/picker", headers=device(key)).json()["people"]
        assert ada["name"] == "Ada"
        refused = tv.post(
            "/api/internal/picker/choose", json={"id": ada["id"]}, headers=device(key)
        )
        assert refused.status_code == 403 and "password" in refused.json()["detail"]
        with_password = tv.post(
            "/api/internal/picker/choose",
            json={"id": ada["id"], "password": ADA["password"]},
            headers=device(key),
        )
        assert with_password.status_code == 200


def test_pins_cant_be_brute_forced_with_many_guesses_at_once(app):
    """Many PIN guesses sent together can't slip past the five-tries limit:
    each counts as wrong until it's found right, so most are turned away."""
    import asyncio

    import httpx

    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        tia = admin.post(
            "/api/access/users",
            json={"name": "Tia", "password": "teen password", "role": "user", "pin": "4321"},
        ).json()
        tv = TestClient(app)
        key = tv.post("/api/internal/sign-in", json={**ADA, **TV}).json()["deviceKey"]

        async def guesses() -> list[int]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://sp") as c:

                async def guess(pin: str):
                    return await c.post(
                        "/api/internal/picker/choose",
                        json={"id": tia["id"], "pin": pin},
                        headers=device(key),
                    )

                # Every wrong PIN but the right one, all at once.
                pins = [f"{n:04d}" for n in range(4300, 4400) if n != 4321]
                return [r.status_code for r in await asyncio.gather(*(guess(p) for p in pins))]

        codes = admin.portal.call(guesses)
        # At most five were ever checked; the rest were told to wait.
        assert codes.count(403) <= devices.PIN_TRIES
        assert 429 in codes and 200 not in codes


def test_a_sign_in_from_a_picker_lasts_a_day_unused(app):
    ctx = app.state.ctx
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        kids = admin.post("/api/access/users", json={"name": "Kids", "role": "user"}).json()
        tv = TestClient(app)
        key = tv.post("/api/internal/sign-in", json={**ADA, **TV}).json()["deviceKey"]
        token = tv.post(
            "/api/internal/picker/choose", json={"id": kids["id"]}, headers=device(key)
        ).json()["token"]
        assert tv.get("/api/v1/stations", headers=bearer(token)).status_code == 200
        day_ago = access._now() - access.PICKED_MS - 60_000
        ctx.db._conn.execute("UPDATE sessions SET seen_ms = ?", (day_ago,))
        ctx.db._conn.commit()
        assert tv.get("/api/v1/stations", headers=bearer(token)).status_code == 401
        # (The device is still linked: pick again.)
        assert people(tv, key) == ["Ada", "Kids"]


def test_an_app_without_a_picker_signs_in_as_before(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        phone = TestClient(app)
        signed = phone.post(
            "/api/internal/sign-in", json={**ADA, "app": "StationPlay for Android"}
        ).json()
        assert signed["deviceKey"] is None and signed["token"]
        assert admin.get("/api/access/devices").json()["devices"] == []
        assert phone.get("/api/internal/picker", headers=device("nope")).status_code == 401


def test_devices_at_home_list_the_household_and_away_only_their_own(tmp_path):
    app = two_ports(tmp_path)
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        made = {
            name: admin.post("/api/access/users", json={"name": name, "role": "user", **more}).json()
            for name, more in (
                ("Kids", {}), ("Tia", {"password": "teen password"}),
                ("Bo", {"password": "bo password"}),
            )
        }  # fmt: skip
        # Devices at home: the household's default, for everyone.
        assert {u["showOn"] for u in admin.get("/api/access/users").json()} == {"home"}
        assert admin.get("/api/access/devices").json()["default"] == "home"
        home = TestClient(app)
        key = home.post("/api/internal/sign-in", json={**ADA, **TV}).json()["deviceKey"]
        assert people(home, key) == ["Ada", "Bo", "Kids", "Tia"]

        # The same device away from home: only Ada, who signed in on it.
        away = away_from_home(app)
        assert people(away, key) == ["Ada"]
        for name in ("Kids", "Tia"):
            picked = away.post(
                "/api/internal/picker/choose", json={"id": made[name]["id"]}, headers=device(key)
            )
            assert picked.status_code == 404, name
        # (Back home, they're there.)
        kids = home.post(
            "/api/internal/picker/choose", json={"id": made["Kids"]["id"]}, headers=device(key)
        )
        assert kids.status_code == 200

        # All devices: away from home too.
        tv_id = admin.get("/api/access/devices").json()["devices"][0]["id"]
        bo = admin.put(f"/api/access/users/{made['Bo']['id']}/picker", json={"showOn": "all"})
        assert bo.status_code == 200 and bo.json()["showOn"] == "all"
        assert people(away, key) == ["Ada", "Bo"]
        # An Admin chooses the device for Kids, away from home too (the family
        # iPad that travels); and Tia signs in on it away from home.
        chose = admin.put(
            f"/api/access/users/{made['Kids']['id']}/picker",
            json={"showOn": "home", "devices": [tv_id]},
        )
        assert chose.status_code == 200 and chose.json()["showOn"] == "home"
        tia = away.post(
            "/api/internal/picker/sign-in",
            json={"name": "Tia", "password": "teen password"},
            headers=device(key),
        )
        assert tia.status_code == 200, tia.text
        assert people(away, key) == ["Ada", "Bo", "Kids", "Tia"]
        kids = away.post(
            "/api/internal/picker/choose", json={"id": made["Kids"]["id"]}, headers=device(key)
        )
        assert kids.status_code == 200
        # Selected devices: only there, at home and away.
        admin.put(
            f"/api/access/users/{made['Kids']['id']}/picker",
            json={"showOn": "selected", "devices": []},
        )
        assert "Kids" not in people(home, key) and "Kids" not in people(away, key)
        admin.put(f"/api/access/users/{made['Bo']['id']}/picker", json={"showOn": "home"})
        [listed] = admin.get("/api/access/devices").json()["devices"]
        assert (listed["people"], listed["peopleAway"]) == (["Ada", "Bo", "Tia"], ["Ada", "Tia"])
        log = admin.get("/api/logs?access_log=true").json()["text"]
        assert "Ada set Bo to show on all devices, away from home too" in log
        assert "Ada set Bo to show on devices at home" in log


def test_everyone_on_all_devices_moves_to_devices_at_home_once(tmp_path):
    app = two_ports(tmp_path)
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        for name, more in (
            ("Kids", {}), ("Tia", {"password": "teen password", "showOn": "signed-in"}),
            ("Lu", {"password": "lu password", "showOn": "selected"}),
            ("Bo", {"password": "bo password"}),
        ):  # fmt: skip
            assert admin.post(
                "/api/access/users", json={"name": name, "role": "user", **more}
            ).status_code == 201  # fmt: skip
    # As 1.27 left it: Ada added before there were pickers, Kids and Bo on
    # every device, and every device the server's default.
    db = sqlite3.connect(tmp_path / "data" / "stationplay.db")
    with db:
        db.execute("UPDATE users SET show_on = '' WHERE name = 'Ada'")
        db.execute("UPDATE users SET show_on = 'all' WHERE name IN ('Kids', 'Bo')")
        db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('show_on_default', 'all')")
        db.execute("DELETE FROM meta WHERE key = 'show_on_home'")
    db.close()

    def started() -> tuple[dict[str, str], str, str]:
        with TestClient(two_ports(tmp_path)) as admin:
            admin.post("/api/access/sign-in", json=ADA)
            users = {u["name"]: u["showOn"] for u in admin.get("/api/access/users").json()}
            default = admin.get("/api/access/devices").json()["default"]
            return users, default, admin.get("/api/logs?access_log=true").json()["text"]

    users, default, log = started()
    assert users == {"Ada": "home", "Bo": "home", "Kids": "home", "Lu": "selected",
                     "Tia": "signed-in"}  # fmt: skip
    assert default == "home"
    said = (
        "Who's tuning in?: 3 people now show on devices at home only; away from home, a device "
        "lists only who signed in on it or was chosen for it."
    )
    assert log.count(said) == 1
    # Once: started again, nothing more moves, or is said.
    assert started()[2].count(said) == 1
