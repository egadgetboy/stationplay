"""Tuner access (see tuner.py): which devices may use what Plex, Jellyfin and
other apps use; who did lately; and Plex's own address."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import access, tuner
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

ROOT = Path(__file__).resolve().parent.parent

# What the tuner is (none of them can sign in), and what it isn't.
TUNER_PATHS = [
    "/discover.json", "/lineup_status.json", "/lineup.json", "/lineup.post", "/device.xml",
    "/xmltv.xml", "/guide.xml", "/stations.m3u", "/channels.m3u", "/stream/7", "/auto/v7",
    "/art/201", "/hls/7/index.m3u8", "/hls/7/piece0.ts", "/hls/7/night/index.m3u8",
]  # fmt: skip
NOT_TUNER = ["/channel-icon/7.png", "/api/v1/server", "/", "/hls/k/some-key/7/index.m3u8"]
VLC = "VLC/3.0.20 LibVLC/3.0.20"
PLEX = "PlexMediaServer/1.41.3.9314-a0bfb8370"
PAT = {"name": "Pat", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple"}


def make(tmp_path, plex_url: str = "http://192.168.1.10:32400"):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * 60_000)
    return create_app(
        Settings(plex_url=plex_url, plex_token="token", data_dir=tmp_path / "data"),
        PlexClient(plex_url, "token", transport=fp.transport()),
    )


@pytest.fixture
def app(tmp_path):
    return make(tmp_path)


@pytest.fixture
def admin(app):
    """The page, at home, with signing in off (so open), and a station 7."""
    with TestClient(app) as client:
        body = {"number": 7, "sources": [{"type": "show", "ratingKey": "100"}]}
        assert client.post("/api/channels", json=body).status_code == 201
        yield client


def device(app, address: str, agent: str = VLC) -> TestClient:
    """A device on the home network at `address`, calling itself `agent`."""
    return TestClient(app, client=(address, 50000), headers={"user-agent": agent})


def refused(res) -> bool:
    return res.status_code == 403 and res.json() == {"detail": access.TUNER_REFUSED}


def test_what_the_tuner_is():
    assert all(tuner.is_tuner(p) for p in TUNER_PATHS)
    assert not any(tuner.is_tuner(p) for p in NOT_TUNER)
    assert tuner.normalize(" 192.168.1.20 ") == "192.168.1.20"
    assert tuner.normalize("::ffff:192.168.1.20") == "192.168.1.20"
    assert tuner.normalize("[fd7a:115c::1]") == "fd7a:115c::1"
    for bad in ("", "living room", "192.168.1.0/24", "fe80::1%eth0", "300.1.1.1"):
        with pytest.raises(ValueError, match="IP address"):
            tuner.normalize(bad)
    assert tuner.named(PLEX) == "Plex Media Server"
    assert tuner.named(VLC) == "VLC"
    assert tuner.named("Lavf/60.16.100") == "FFmpeg"
    assert tuner.named("<script>alert(1)</script>") == ""
    assert tuner.named("") == ""


def test_any_device_on_the_home_network_by_default(admin, app):
    tv = device(app, "10.0.0.3")
    assert tv.get("/discover.json").status_code == 200
    assert tv.get("/stations.m3u").status_code == 200
    assert not any(refused(tv.get(p)) for p in TUNER_PATHS[:9])
    got = admin.get("/api/tuner").json()
    assert got["only"] is False and got["devices"] == [] and got["warning"] == ""
    [seen] = [s for s in got["recent"] if s["address"] == "10.0.0.3"]
    assert (seen["name"], seen["refused"], seen["listed"]) == ("VLC", False, False)


def test_only_these_devices(admin, app):
    saved = admin.put(
        "/api/tuner", json={"only": True, "devices": [{"address": "10.0.0.2", "name": "Den TV"}]}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["devices"] == [{"address": "10.0.0.2", "name": "Den TV"}]
    listed, other = device(app, "10.0.0.2"), device(app, "10.0.0.3")
    assert listed.get("/discover.json").status_code == 200
    assert listed.get("/xmltv.xml").status_code == 200
    for path in TUNER_PATHS:
        assert refused(other.get(path)), path
    assert refused(other.post("/lineup.post"))
    for path in NOT_TUNER:
        assert not refused(other.get(path)), path
    # Kept: it's the same after a restart.
    again = tuner.TunerAccess(Database(app.state.ctx.settings.data_dir / "stationplay.db"))
    assert again.only and again.devices == {"10.0.0.2": "Den TV"}
    # Back to any device.
    assert admin.put("/api/tuner", json={"only": False, "devices": []}).status_code == 200
    assert other.get("/discover.json").status_code == 200


def test_a_refused_device_is_logged_once_an_hour_and_can_be_allowed(admin, app, caplog):
    caplog.set_level(logging.INFO)
    admin.put("/api/tuner", json={"only": True, "devices": [{"address": "10.0.0.2"}]})
    other = device(app, "10.0.0.3")
    for _ in range(3):
        assert refused(other.get("/stream/7"))
    said = [r.getMessage() for r in caplog.records if "tapiOca's tuner" in r.getMessage()]
    assert said == [
        "Turned away 10.0.0.3 (VLC), which asked tapiOca's tuner for a station. Only the "
        "devices listed under Tuner access may use it: to let this one, choose Allow beside it "
        "on the Access tab."
    ]
    [seen] = [s for s in admin.get("/api/tuner").json()["recent"] if s["address"] == "10.0.0.3"]
    assert (seen["name"], seen["asked"], seen["refused"], seen["listed"]) == (
        "VLC", "a station", True, False,
    )  # fmt: skip
    allowed = admin.post("/api/tuner/allow", json={"address": "10.0.0.3"})
    assert allowed.status_code == 200, allowed.text
    assert {"address": "10.0.0.3", "name": "VLC"} in allowed.json()["devices"]
    assert other.get("/discover.json").status_code == 200
    bad = admin.post("/api/tuner/allow", json={"address": "the den"})
    assert bad.status_code == 400 and "IP address" in bad.json()["detail"]
    log = admin.get("/api/logs?access_log=true").json()["text"]
    assert "Tuner access: 10.0.0.3 may use the tuner" in log


def test_plex_server_only_and_the_warning(admin, app):
    # Plex in Docker reaches tapiOca from the Docker network, not the server's address.
    plex = device(app, "172.17.0.1", PLEX)
    assert plex.get("/discover.json").status_code == 200
    assert admin.get("/api/tuner").json()["plex"] == ["172.17.0.1"]
    only = admin.post("/api/tuner/plex-only")
    assert only.status_code == 200, only.text
    assert only.json()["only"] is True
    assert only.json()["devices"] == [{"address": "172.17.0.1", "name": "Plex Media Server"}]
    assert only.json()["warning"] == ""
    assert plex.get("/lineup.json").status_code == 200
    # Its streams call themselves FFmpeg: it's still Plex.
    assert not refused(device(app, "172.17.0.1", "Lavf/60.16.100").get("/xmltv.xml"))
    [seen] = [s for s in admin.get("/api/tuner").json()["recent"] if s["address"] == "172.17.0.1"]
    assert seen["name"] == "Plex Media Server"
    assert refused(device(app, "10.0.0.3").get("/discover.json"))
    # Only another device listed: Plex is shut out, and the Access tab says so.
    admin.put("/api/tuner", json={"only": True, "devices": [{"address": "10.0.0.2"}]})
    assert admin.get("/api/tuner").json()["warning"] == (
        "Plex uses tapiOca's tuner from 172.17.0.1, which isn't on the list, so Plex can't "
        "show your stations. Allow it below."
    )


def test_plex_server_only_before_plex_has_used_the_tuner(tmp_path):
    # PLEX_URL with an IP address: that's Plex's.
    with TestClient(make(tmp_path / "a")) as admin:
        only = admin.post("/api/tuner/plex-only")
        assert only.status_code == 200 and only.json()["devices"][0]["address"] == "192.168.1.10"
    # With a name, it isn't known until Plex uses the tuner.
    with TestClient(make(tmp_path / "b", "http://plex.test")) as admin:
        unknown = admin.post("/api/tuner/plex-only")
        assert unknown.status_code == 400 and "Plex's address" in unknown.json()["detail"]
        assert admin.get("/api/tuner").json()["only"] is False


def test_saving_checks_what_it_keeps(admin):
    none = admin.put("/api/tuner", json={"only": True, "devices": []})
    assert none.status_code == 400 and "at least one device" in none.json()["detail"]
    bad = admin.put("/api/tuner", json={"only": True, "devices": [{"address": "den tv"}]})
    assert bad.status_code == 400 and bad.json()["detail"] == tuner.ADDRESS_PROBLEM
    mapped = admin.put(
        "/api/tuner", json={"only": True, "devices": [{"address": "::ffff:10.0.0.2"}]}
    )
    assert mapped.json()["devices"] == [{"address": "10.0.0.2", "name": ""}]
    too_many = [{"address": f"10.0.1.{n}"} for n in range(tuner.DEVICES_MOST + 1)]
    assert admin.put("/api/tuner", json={"only": True, "devices": too_many}).status_code == 400


def test_only_an_admin_sees_or_changes_it(app):
    with TestClient(app) as pat:
        assert pat.post("/api/access/users", json=PAT).status_code == 201
        assert pat.post("/api/access/users", json={**SAM, "role": "user"}).status_code == 201
        sam = TestClient(app)
        assert sam.post("/api/access/sign-in", json=SAM).status_code == 200
        assert sam.get("/api/tuner").status_code == 403
        assert sam.put("/api/tuner", json={"only": False, "devices": []}).status_code == 403
        assert sam.post("/api/tuner/allow", json={"address": "10.0.0.3"}).status_code == 403
        assert sam.post("/api/tuner/plex-only").status_code == 403
        assert pat.get("/api/tuner").status_code == 200


def test_signed_in_apps_at_home_needn_t_be_listed(app):
    """While only listed devices may use the tuner, a signed-in app at home
    gets its stations at an address of its own (as away from home), which
    plays from any device at home, never from the internet, and ends with
    its sign-in. Its home address, from an unlisted device, is refused."""
    with TestClient(app) as pat:
        assert pat.post("/api/access/users", json=PAT).status_code == 201
        body = {"number": 7, "sources": [{"type": "show", "ratingKey": "100"}]}
        assert pat.post("/api/channels", json=body).status_code == 201
        phone = device(app, "10.0.0.9", "StationPlay/0.4.0")
        token = phone.post("/api/internal/sign-in", json=PAT).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}

        def station() -> dict:
            [one] = phone.get("/api/v1/stations", headers=auth).json()["stations"]
            return one

        # (Its own even while any device may use the tuner: see the next test.)
        before = station()["hls"]
        listed = pat.put("/api/tuner", json={"only": True, "devices": [{"address": "10.0.0.2"}]})
        assert listed.status_code == 200
        own = station()
        assert own["hls"] == before
        assert own["hls"].startswith("/hls/k/") and own["hls"].endswith("/7/index.m3u8")
        assert own["nightHls"] == own["hls"].replace("index.m3u8", "night/index.m3u8")
        assert own["logo"].startswith(own["hls"].replace("index.m3u8", "logo.png?v="))
        assert station()["hls"] == own["hls"]  # (one address per sign-in)
        got = phone.get(own["logo"])
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        assert refused(phone.get("/hls/7/index.m3u8"))
        assert refused(phone.get("/stream/7"))
        # Not away from home: Watching away from home is off, and its key is home's.
        assert app.state.ctx.away.apps == 0
        # Signing out ends it (at once for the playlist, asked every few seconds,
        # which checks the sign-in each time).
        assert phone.post("/api/internal/sign-out", headers=auth).status_code == 200
        assert phone.get(own["hls"]).status_code == 404
        assert phone.get(own["logo"]).status_code == 404


def test_a_key_for_home_is_no_good_from_the_internet(tmp_path):
    db = Database(tmp_path / "db.sqlite")

    class SignedIn:
        def session_user_hashed(self, hashed: str, anywhere: bool = False):
            return "Pat"

        def record(self, level: int, message: str) -> None:
            pass

    from app.away import Away

    away = Away(db, SignedIn())  # type: ignore[arg-type]
    assert away.key_for("hash", "Pat") is None  # type: ignore[arg-type]  (away is off)
    home = away.key_for("hash", "Pat", home=True)  # type: ignore[arg-type]
    assert home and away.is_home(home)
    assert away.user_of(home, recheck=True, outside=False) == "Pat"
    assert away.user_of(home, recheck=True, outside=True) is None
    away.save(True, "https://tv.example.com")
    out = away.key_for("hash", "Pat")  # type: ignore[arg-type]
    assert out and out != home and not away.is_home(out)
    assert away.user_of(out, recheck=True, outside=True) == "Pat"
    # Turning away from home off ends its keys, not home's.
    away.save(False, "https://tv.example.com")
    assert away.user_of(out, recheck=True, outside=True) is None
    assert away.user_of(home, recheck=True, outside=False) == "Pat"


def test_the_images_health_check_isnt_the_tuner(tmp_path):
    """The audit of 1.32.0: Docker's health check asked for discover.json,
    which is the tuner's, so with only listed devices allowed, tapiOca's
    own check (from 127.0.0.1) was refused: the container showed as
    unhealthy, and 127.0.0.1 topped Recent tuner connections with Allow."""
    found = re.search(r"127\.0\.0\.1:\{[^}]*\}(/[^'\"]*)'", (ROOT / "Dockerfile").read_text())
    assert found, "the Dockerfile's HEALTHCHECK"
    path = found.group(1)
    assert not tuner.is_tuner(path), path
    app = make(tmp_path)
    with TestClient(app) as pat:
        assert pat.post("/api/access/users", json=PAT).status_code == 201  # (signing in on)
        only = pat.put("/api/tuner", json={"only": True, "devices": [{"address": "10.0.0.2"}]})
        assert only.status_code == 200
        check = device(app, "127.0.0.1", "Python-urllib/3.11")
        assert check.get(path).status_code == 200
        assert all(s["address"] != "127.0.0.1" for s in pat.get("/api/tuner").json()["recent"])


def test_something_calling_itself_plex_isnt_taken_for_plex(admin, app):
    """The audit of 1.32.0: anything whose user agent said Plex was taken
    for Plex, even when it was refused. The Access tab then said Plex used
    the tuner from there, and Plex server only listed it in place of the
    real Plex (PLEX_URL's address, 192.168.1.10 here)."""
    real = device(app, "192.168.1.10", PLEX)
    assert real.get("/discover.json").status_code == 200
    plex_only = [{"address": "192.168.1.10", "name": "Plex Media Server"}]
    assert admin.post("/api/tuner/plex-only").json()["devices"] == plex_only
    fake = device(app, "192.168.1.66", PLEX)
    assert refused(fake.get("/discover.json"))
    got = admin.get("/api/tuner").json()
    assert got["warning"] == "" and got["plex"] == ["192.168.1.10"]
    assert admin.post("/api/tuner/plex-only").json()["devices"] == plex_only
    # While any device may use it, saying so still doesn't make it Plex, when
    # Plex is where PLEX_URL says.
    assert admin.put("/api/tuner", json={"only": False, "devices": []}).status_code == 200
    assert fake.get("/discover.json").status_code == 200
    assert admin.get("/api/tuner").json()["plex"] == ["192.168.1.10"]
    assert admin.post("/api/tuner/plex-only").json()["devices"] == plex_only


def test_plex_turned_away_is_said_plainly(tmp_path):
    """Where Plex is can't be told from PLEX_URL (a name, here): what was
    turned away is never taken for Plex's address, and the Access tab says
    only what it knows."""
    app = make(tmp_path, "http://plex.test")
    with TestClient(app) as admin:
        assert (
            admin.put(
                "/api/tuner", json={"only": True, "devices": [{"address": "10.0.0.2"}]}
            ).status_code
            == 200
        )
        assert refused(device(app, "172.17.0.1", PLEX).get("/discover.json"))
        got = admin.get("/api/tuner").json()
        assert got["warning"] == (
            "Something calling itself Plex was turned away from 172.17.0.1. If that's your Plex "
            "server, choose Allow beside it below."
        )
        assert got["plex"] == []
        unknown = admin.post("/api/tuner/plex-only")
        assert unknown.status_code == 400
        assert unknown.json()["detail"] == (
            "tapiOca doesn't know Plex's address yet. If Plex was turned away, choose Allow "
            "beside it under Recent tuner connections."
        )
        assert admin.get("/api/tuner").json()["devices"] == [{"address": "10.0.0.2", "name": ""}]


def test_switching_to_only_these_devices_keeps_apps_playing(app):
    """The audit of 1.32.0: at home, while any device could use the tuner,
    a signed-in app was given the tuner's own addresses, so switching to
    Only these devices refused the station it was playing until it next
    asked for its stations (every 10 minutes). Its addresses are its own
    now, whatever the setting; a script's API token is as before."""
    with TestClient(app) as pat:
        assert pat.post("/api/access/users", json=PAT).status_code == 201
        body = {"number": 7, "sources": [{"type": "show", "ratingKey": "100"}]}
        assert pat.post("/api/channels", json=body).status_code == 201
        made = pat.post("/api/api-tokens", json={"name": "Script", "scope": "viewer"})
        assert made.status_code == 201, made.text
        script = {"Authorization": f"Bearer {made.json()['token']}"}
        phone = device(app, "10.0.0.9", "StationPlay/0.4.0")
        token = phone.post("/api/internal/sign-in", json=PAT).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        [seven] = phone.get("/api/v1/stations", headers=auth).json()["stations"]
        for address in (seven["hls"], seven["nightHls"], seven["logo"]):
            assert not tuner.is_tuner(address.partition("?")[0]), address
        [scripts] = phone.get("/api/v1/stations", headers=script).json()["stations"]
        assert scripts["hls"] == "/hls/7/index.m3u8"
        assert phone.get(seven["logo"]).status_code == 200
        only = pat.put("/api/tuner", json={"only": True, "devices": [{"address": "10.0.0.2"}]})
        assert only.status_code == 200
        got = phone.get(seven["logo"])
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        [again] = phone.get("/api/v1/stations", headers=auth).json()["stations"]
        assert (again["hls"], again["nightHls"]) == (seven["hls"], seven["nightHls"])


def test_refusals_are_logged_a_few_at_a_time(admin, app, caplog):
    """The audit of 1.32.0: a device changing its IPv6 address for each
    request could write a warning for every one. Ten devices an hour are
    logged; then one line says more were turned away."""
    caplog.set_level(logging.INFO)
    admin.put("/api/tuner", json={"only": True, "devices": [{"address": "10.0.0.2"}]})
    for n in range(15):
        assert refused(device(app, f"fd00::{n + 1:x}").get("/discover.json"))
    said = [r.getMessage() for r in caplog.records if r.name == "app.tuner"]
    assert len(said) == 11, said
    assert said[-1] == (
        "Turned more devices away from tapiOca's tuner this hour. Recent tuner connections, "
        "on the Access tab, lists them."
    )


def test_plex_from_the_docker_network_is_warned_about_with_plex_url_listed(admin, app):
    """The audit of 1.32.0's fixes: with PLEX_URL's address listed (Plex
    server only before Plex had used the tuner), Plex turned away from the
    Docker network's address went unmentioned."""
    only = admin.post("/api/tuner/plex-only")
    assert only.json()["devices"] == [{"address": "192.168.1.10", "name": "Plex Media Server"}]
    assert refused(device(app, "172.17.0.1", PLEX).get("/discover.json"))
    assert admin.get("/api/tuner").json()["warning"] == (
        "Something calling itself Plex was turned away from 172.17.0.1. If that's your Plex "
        "server, choose Allow beside it below."
    )


def test_a_link_local_address_can_be_allowed(admin, app):
    """The audit of 1.32.0: a link-local IPv6 address comes with its
    network's name after a % (fe80::1%eth0). It was listed that way under
    Recent tuner connections, and Allow beside it said it wasn't an IP
    address. It's kept and listed without it now."""
    admin.put("/api/tuner", json={"only": True, "devices": [{"address": "10.0.0.2"}]})
    near = device(app, "fe80::1%eth0")
    assert refused(near.get("/discover.json"))
    [seen] = [s for s in admin.get("/api/tuner").json()["recent"] if s["refused"]]
    assert seen["address"] == "fe80::1"
    allowed = admin.post("/api/tuner/allow", json={"address": seen["address"]})
    assert allowed.status_code == 200, allowed.text
    assert near.get("/discover.json").status_code == 200
    assert device(app, "fe80::1%eth1").get("/discover.json").status_code == 200


def test_a_tuner_path_with_dot_steps_is_the_tuners(tmp_path):
    """The attack check of 1.32.0: /./discover.json, sent as written (a
    client tidies its dots away), wasn't taken for the tuner's, so with
    sign-in on an unlisted device was told to sign in rather than refused.
    A path is taken for the tuner's however it's written now."""
    db = Database(tmp_path / "db.sqlite")
    reached: list[str] = []

    async def inner(scope, receive, send):
        reached.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    only = tuner.TunerAccess(db)
    only.save(True, [("10.0.0.2", "Den TV")])
    gate = access.Gate(inner, access.Access(db), tuner=only)

    async def status(path: str, client: str = "10.0.0.3") -> int:
        sent: list[dict] = []
        scope = {
            "type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
            "query_string": b"", "headers": [], "client": (client, 50000),
            "server": ("testserver", 3310), "scheme": "http", "http_version": "1.1",
        }  # fmt: skip

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            sent.append(message)

        await gate(scope, receive, send)
        return sent[0]["status"]

    for path in ("/./discover.json", "/hls/k/../3/index.m3u8", "/web/../stream/3", "/art/./201"):
        assert asyncio.run(status(path)) == 403, path
    assert reached == []
    assert asyncio.run(status("/./discover.json", "10.0.0.2")) == 200  # (listed)
    assert reached == ["/./discover.json"]


def test_only_these_devices_takes_networks_too(admin, app):
    """(1.36.0) A network, in CIDR form (a home network, or one VPN's), as
    well as single devices: a friend's VPN, or another VLAN, gets nothing.
    Only home addresses, as for trusted networks."""
    saved = admin.put(
        "/api/tuner",
        json={
            "only": True,
            "devices": [],
            "networks": [{"network": "192.168.1.0/24", "name": "Home"}],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["networks"] == [{"network": "192.168.1.0/24", "name": "Home"}]
    assert device(app, "192.168.1.9").get("/discover.json").status_code == 200
    assert refused(device(app, "192.168.2.9").get("/discover.json"))
    assert refused(device(app, "10.8.0.5").get("/discover.json"))
    for bad in ("8.8.8.0/24", "0.0.0.0/0", "192.168.1.0/24 x"):
        said = admin.put("/api/tuner", json={"only": True, "networks": [{"network": bad}]})
        assert said.status_code == 400, bad
    # Kept as it was by 1.35.0's reading too: the devices list has none.
    import json as json_

    kept = json_.loads(app.state.ctx.db.get_meta(tuner.META))
    assert kept["devices"] == [] and kept["networks"][0]["network"] == "192.168.1.0/24"
    # Plex server only lists just Plex's address: the networks go.
    assert device(app, "192.168.1.9", PLEX).get("/discover.json").status_code == 200
    only = admin.post("/api/tuner/plex-only")
    assert only.status_code == 200, only.text
    assert only.json()["networks"] == [] and only.json()["devices"][0]["address"] == "192.168.1.9"
    assert refused(device(app, "192.168.1.10").get("/discover.json"))


def test_the_internet_never_uses_the_tuner(admin, app):
    """(1.36.0) Even with Tuner access open to any device on the home
    network, an internet address on the home port (a port forward to it)
    gets nothing: not the tuner, guide, playlist or streams."""
    for address in ("203.0.113.9", "8.8.8.8"):
        assert device(app, address).get("/discover.json").status_code == 404
        assert device(app, address).get("/guide.xml").status_code == 404
