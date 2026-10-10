"""The server's license (licensing.py): its server ID, a license an Admin
installs (from an app or the page), and the apps' device slots."""

from __future__ import annotations

import base64
import json
import socket
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import licensing
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

ADA = {"name": "Ada", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple", "role": "user"}
APP = {"app": "StationPlay for Android", "picker": True}


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def made(server_id: str, signature: bytes = b"\x07" * 64, **payload) -> dict:
    """A license file for `server_id` (the server never checks signatures:
    the apps do)."""
    body = {"license_id": "lic-0001", "server_id": server_id, "tier": "lifetime",
            "device_limit": 15, "issued_at": 1_791_000_000, "format_version": 1, **payload}  # fmt: skip
    body = {k: v for k, v in body.items() if v is not ...}
    return {"payload": b64(json.dumps(body).encode()), "signature": b64(signature), "key": "k1"}


def app_for(data_dir) -> object:
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep", "/x/1.mkv", 22 * 60_000)
    built = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=data_dir),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    built.state.ctx.restart = lambda: None  # (a test mustn't stop itself)
    return built


@pytest.fixture
def app(tmp_path):
    return app_for(tmp_path / "data")


def linked(client: TestClient, name: str) -> dict:
    """An app signing in as Ada on a new device: its token and key."""
    signed = client.post("/api/internal/sign-in", json={**ADA, **APP, "deviceName": name})
    assert signed.status_code == 200, signed.text
    return {"Authorization": f"Bearer {signed.json()['token']}"}


def test_a_server_id_made_once_and_kept(tmp_path):
    """Made at random on the first start, the same on every start after; a
    fresh install has its own."""
    with TestClient(app_for(tmp_path / "a")) as first:
        first.post("/api/access/users", json=ADA)
        ours = first.get("/api/access/license").json()["serverId"]
    assert len(ours) == 36
    with TestClient(app_for(tmp_path / "a")) as again:
        again.post("/api/access/sign-in", json=ADA)
        assert again.get("/api/access/license").json()["serverId"] == ours
    with TestClient(app_for(tmp_path / "b")) as other:
        other.post("/api/access/users", json=ADA)
        assert other.get("/api/access/license").json()["serverId"] != ours


def test_installing_and_removing_a_license(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        server = admin.get("/api/access/license").json()
        assert server["license"] is None
        lic = made(server["serverId"])
        got = admin.put("/api/access/license", json={"license": json.dumps(lic)})
        assert got.status_code == 200, got.text
        assert got.json()["license"] == {"licenseId": "lic-0001", "tier": "lifetime",
                                         "deviceLimit": 15, "issuedAt": 1_791_000_000}  # fmt: skip
        # A license code is the same file, on one line.
        code = licensing.code_of(lic)
        assert code.startswith("SPL1.") and "\n" not in code
        assert admin.put("/api/access/license", json={"license": f"  {code}\n"}).status_code == 200
        log = admin.get("/api/logs?access_log=true").json()["text"]
        assert "Ada installed a license for 15 devices (license lic-0001)" in log
        assert admin.delete("/api/access/license").json()["license"] is None
        assert "Ada removed the license" in admin.get("/api/logs?access_log=true").json()["text"]


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda s: "not a license at all", licensing.NOT_A_LICENSE),
        (lambda s: "SPL1.%%%%", licensing.NOT_A_LICENSE),
        (lambda s: json.dumps(made("another-server")), licensing.OTHER_SERVER),
        (lambda s: json.dumps(made(s, format_version=2)), licensing.NEWER),
        (lambda s: json.dumps(made(s, format_version=0)), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps(made(s, device_limit=True)), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps(made(s, device_limit=0)), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps(made(s, device_limit="15")), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps(made(s, issued_at=-1)), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps(made(s, tier=...)), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps(made(s, extra="x")), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps(made(s, license_id="../../x")), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps(made(s, license_id="<b>x</b>")), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps(made(s, signature=b"short")), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps({**made(s), "key": "a key"}), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps({**made(s), "more": 1}), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps({**made(s), "payload": b64(b"[1, 2]")}), licensing.NOT_A_LICENSE),
        (lambda s: json.dumps({**made(s), "payload": "!!!"}), licensing.NOT_A_LICENSE),
    ],
)
def test_what_isnt_a_license_for_this_server_is_refused(app, change, said):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        server = admin.get("/api/access/license").json()["serverId"]
        got = admin.put("/api/access/license", json={"license": change(server)})
        assert got.status_code == 400 and got.json()["detail"] == said
        assert admin.get("/api/access/license").json()["license"] is None


def test_a_license_too_big_is_refused(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        got = admin.put("/api/access/license", json={"license": "x" * (licensing.LICENSE_MOST + 1)})
        assert got.status_code == 422


def test_only_an_admin_installs_or_removes_one_or_removes_devices(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        admin.post("/api/access/users", json=SAM)
        server = admin.get("/api/access/license").json()["serverId"]
        lic = json.dumps(made(server))
        sam = TestClient(app)
        sam.post("/api/access/sign-in", json=SAM)
        app_sam = sam.post("/api/internal/sign-in", json={**SAM, **APP}).json()
        as_sam = {"Authorization": f"Bearer {app_sam['token']}"}
        stranger = TestClient(app)
        for client, headers, code in ((sam, {}, 403), (sam, as_sam, 403), (stranger, {}, 401)):
            assert client.put("/api/access/license", json={"license": lic},
                              headers=headers).status_code == code  # fmt: skip
            assert client.post("/api/internal/license", json={"license": lic},
                               headers=headers).status_code == code  # fmt: skip
            assert client.delete("/api/internal/license", headers=headers).status_code == code
            assert client.delete("/api/access/license", headers=headers).status_code == code
            assert client.get("/api/access/license", headers=headers).status_code == code
        tv = admin.get("/api/access/devices").json()["devices"][0]["id"]
        assert sam.delete(f"/api/access/devices/{tv}").status_code == 403
        # (A User's app reads it, though: see the next test.)
        assert sam.get("/api/internal/license", headers=as_sam).status_code == 200
        assert stranger.get("/api/internal/license").status_code == 401
        # From another site, never.
        cross = admin.put("/api/access/license", json={"license": lic},
                          headers={"Sec-Fetch-Site": "cross-site"})  # fmt: skip
        assert cross.status_code == 403


def test_an_admin_installs_one_from_an_app(app):
    with TestClient(app) as home:
        home.post("/api/access/users", json=ADA)
        ada = linked(TestClient(app), "Ada's iPhone")
        server = home.get("/api/internal/license", headers=ada).json()["serverId"]
        got = home.post("/api/internal/license", json={"license": json.dumps(made(server))},
                        headers=ada)  # fmt: skip
        assert got.status_code == 200, got.text
        assert home.get("/api/internal/license", headers=ada).json()["license"] == made(server)
        assert home.delete("/api/internal/license", headers=ada).json()["license"] is None


def test_devices_take_slots_in_the_order_they_were_linked(app):
    """Each app on a linked device is told its slot (and how many are
    linked); the first 15 are covered; removing one lets the next move up.
    The page shows them in that order."""
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        server = admin.get("/api/access/license").json()["serverId"]
        admin.put("/api/access/license", json={"license": json.dumps(made(server))})
        apps = [linked(TestClient(app), f"Phone {n}") for n in range(1, 17)]

        def slot(headers: dict) -> dict:
            return admin.get("/api/internal/license", headers=headers).json()["device"]

        assert [slot(a)["slot"] for a in apps] == list(range(1, 17))
        assert {slot(a)["linked"] for a in apps} == {16}
        listed = admin.get("/api/access/license").json()["devices"]
        assert [(d["name"], d["slot"], d["covered"]) for d in listed][-2:] == [
            ("StationPlay for Android on Phone 15", 15, True),
            ("StationPlay for Android on Phone 16", 16, False),
        ]
        # The third removed: the 16th is covered now.
        assert admin.delete(f"/api/access/devices/{listed[2]['id']}").status_code == 204
        assert slot(apps[15]) == {"slot": 15, "linked": 15}
        assert admin.get("/api/internal/license", headers=apps[2]).status_code == 401
        listed = admin.get("/api/access/license").json()["devices"]
        assert all(d["covered"] for d in listed) and len(listed) == 15


def test_tuners_and_the_page_never_take_a_slot(app):
    """Plex, Jellyfin and other tuner apps, and StationPlay's page, aren't
    devices; nor is an app that doesn't link (no picker)."""
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        for path in ("/discover.json", "/lineup.json", "/lineup_status.json", "/stations.m3u",
                     "/xmltv.xml"):  # fmt: skip
            assert TestClient(app).get(path).status_code == 200, path
        browser = TestClient(app)
        browser.post("/api/access/sign-in", json=ADA)
        assert browser.get("/api/internal/license").json()["device"] is None
        plain = TestClient(app).post("/api/internal/sign-in", json={**ADA, "app": "Some app"})
        bare = {"Authorization": f"Bearer {plain.json()['token']}"}
        assert admin.get("/api/internal/license", headers=bare).json()["device"] is None
        assert admin.get("/api/access/license").json()["devices"] == []


def test_unlicensed_the_apps_are_told_so(app):
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        ada = linked(TestClient(app), "TV")
        got = admin.get("/api/internal/license", headers=ada).json()
        assert got["license"] is None and got["device"] == {"slot": 1, "linked": 1}


def test_a_backup_restored_onto_a_fresh_install_keeps_the_id_license_and_slots(tmp_path):
    first = app_for(tmp_path / "old")
    with TestClient(first) as admin:
        admin.post("/api/access/users", json=ADA)
        server = admin.get("/api/access/license").json()["serverId"]
        admin.put("/api/access/license", json={"license": json.dumps(made(server))})
        for n in (1, 2):
            linked(TestClient(first), f"Phone {n}")
        before = admin.get("/api/access/license").json()
        name = admin.post("/api/backups").json()["name"]
        backup = admin.get(f"/api/backups/{name}").content
    fresh = tmp_path / "new"
    with TestClient(app_for(fresh)) as new:
        new.post("/api/access/users", json={"name": "Temp", "password": "temporary one"})
        assert new.get("/api/access/license").json()["serverId"] != server
        assert new.post("/api/restore", content=backup).status_code == 200
    with TestClient(app_for(fresh)) as restored:
        restored.post("/api/access/sign-in", json=ADA)
        after = restored.get("/api/access/license").json()
        assert after == before


def test_no_outside_calls(app, monkeypatch):
    """Installing a license, and the apps reading it, call nothing outside."""

    def no(*args, **kwargs):
        raise AssertionError("an outside call")

    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        ada = linked(TestClient(app), "TV")
        monkeypatch.setattr(socket, "create_connection", no)
        monkeypatch.setattr(httpx.AsyncClient, "send", no)
        server = admin.get("/api/access/license").json()["serverId"]
        assert admin.put("/api/access/license",
                         json={"license": json.dumps(made(server))}).status_code == 200  # fmt: skip
        assert admin.get("/api/internal/license", headers=ada).status_code == 200
    source = Path(licensing.__file__).read_text()
    assert "httpx" not in source and "socket" not in source and "urllib" not in source
