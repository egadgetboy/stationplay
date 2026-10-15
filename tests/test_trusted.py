"""Trusted networks and trusted proxies (trusted.py, 1.36.0): what an Admin
may list, how it's kept, and that a mistake in it stays safe (the owner,
October 13: "we are also focusing on how security works if we accidentally
leave doors open")."""

from __future__ import annotations

import hashlib
import ipaddress
import json

import httpx
import pytest

from app import access, trusted, trustedapi
from app.db import Database

ADMIN, USER = 1, 2


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "t.db")
    roles = {ADMIN: "admin", USER: "user"}
    return trusted.Trusted(db, lambda: roles)


def entry(network, **more):
    return {"network": network, "label": "", "gives": "picker", "person": None, **more}


def test_nothing_is_trusted_until_an_admin_lists_it(store):
    assert store.entries == [] and store.proxies == [] and store.home_names == []
    assert store.entry_for(ipaddress.ip_address("192.168.1.5")) is None
    assert not store.is_proxy(ipaddress.ip_address("192.168.1.2"))


def test_networks_and_single_devices(store):
    store.save({"entries": [
        entry("192.168.1.0/24", label="Home Wi-Fi"),
        entry("192.168.1.44", gives="person", person=ADMIN, label="Pat's laptop"),
        entry("10.8.0.0/24", label="My WireGuard"),
        entry("fd00:1:2:3::/64"),
    ]}, by=ADMIN)  # fmt: skip
    nets = [e["network"] for e in store.entries]
    assert nets == ["192.168.1.0/24", "192.168.1.44/32", "10.8.0.0/24", "fd00:1:2:3::/64"]
    # The longest prefix wins: the laptop is itself, its neighbor the network.
    assert store.entry_for(ipaddress.ip_address("192.168.1.44"))["label"] == "Pat's laptop"
    assert store.entry_for(ipaddress.ip_address("192.168.1.45"))["label"] == "Home Wi-Fi"
    assert store.entry_for(ipaddress.ip_address("10.8.1.1")) is None  # (the friends' VPN)
    assert store.entry_for(ipaddress.ip_address("192.168.20.5")) is None  # (another VLAN)
    # Kept as written, normalized; who added each, and when.
    kept = json.loads(store.db.get_meta(trusted.META))
    assert kept["v"] == 1 and all(e["addedBy"] == ADMIN and e["addedMs"] for e in kept["entries"])


@pytest.mark.parametrize(
    ("network", "said"),
    [
        ("0.0.0.0/0", trusted.INTERNET), ("::/0", trusted.INTERNET),
        ("8.8.8.0/24", trusted.INTERNET), ("2001:db8::/64", trusted.INTERNET),
        ("203.0.113.9", trusted.INTERNET), ("127.0.0.0/8", trusted.INTERNET),
        ("10.0.0.0/7", trusted.INTERNET),  # (wider than a home range: part is the internet)
        ("fe80::1%eth0", trusted.NOT_AN_ADDRESS), ("::ffff:192.168.1.0/120", trusted.NOT_AN_ADDRESS),
        ("192.168.1", trusted.NOT_AN_ADDRESS), ("", trusted.NOT_AN_ADDRESS),
        ("192.168.1.0/24 ; x", trusted.NOT_AN_ADDRESS), ("x" * 51, trusted.NOT_AN_ADDRESS),
    ],
)  # fmt: skip
def test_what_cant_be_trusted(store, network, said):
    with pytest.raises(trusted.Refused) as refused:
        store.save({"entries": [entry(network)]}, by=ADMIN)
    assert str(refused.value) == said
    assert store.entries == []


def test_wide_networks_are_trusted_only_when_the_admin_says_so(store):
    with pytest.raises(trusted.Wide) as wide:
        store.save({"entries": [entry("192.168.0.0/16")]}, by=ADMIN)
    assert str(wide.value) == (
        "192.168.0.0/16 is 65,536 addresses. That's wider than one home network, and often "
        "takes in guest networks too. Trust it anyway?"
    )
    store.save({"entries": [entry("192.168.0.0/16")], "confirmWide": True}, by=ADMIN)
    assert store.entries[0]["network"] == "192.168.0.0/16"


def test_a_wide_network_is_asked_about_once(store):
    """Confirmed once, it stays listed without asking again as others are
    added or changed (each save sends the whole list)."""
    store.save({"entries": [entry("192.168.0.0/16")], "confirmWide": True}, by=ADMIN)
    store.save({"entries": [entry("192.168.0.0/16"), entry("10.0.0.5")]}, by=ADMIN)
    assert [e["network"] for e in store.entries] == ["192.168.0.0/16", "10.0.0.5/32"]
    with pytest.raises(trusted.Wide):
        store.save({"entries": [entry("192.168.0.0/16"), entry("10.0.0.0/8")]}, by=ADMIN)


def test_an_admin_is_signed_in_only_on_one_device(store):
    with pytest.raises(trusted.Refused) as refused:
        store.save({"entries": [entry("192.168.1.0/24", gives="person", person=ADMIN)]}, by=ADMIN)
    assert str(refused.value) == (
        "An Admin can be signed in only on one device. Enter one address, such as 192.168.1.44."
    )
    # A User may be a network's (a family room's TV network, say).
    store.save({"entries": [entry("192.168.30.0/24", gives="person", person=USER)]}, by=ADMIN)
    with pytest.raises(trusted.Refused):
        store.save({"entries": [entry("192.168.1.9", gives="person", person=99)]}, by=ADMIN)


def test_the_list_is_limited(store):
    with pytest.raises(trusted.Refused) as refused:
        store.save({"entries": [entry(f"10.0.{n}.0/24") for n in range(51)]}, by=ADMIN)
    assert str(refused.value) == "List 50 networks at most."
    with pytest.raises(trusted.Refused) as refused:
        store.save({"entries": [entry("192.168.1.0/24"), entry("192.168.1.7/24")]}, by=ADMIN)
    assert str(refused.value) == "192.168.1.0/24 is already on the list."


def test_trusted_proxies_are_listed_by_an_admin_only(store):
    """(The owner, October 13: "Trusted proxies"; "Don't just assume its
    your reverse proxy because it has the headers.")"""
    store.save({"proxies": [{"network": "172.16.39.1", "label": "NPM"}]}, by=ADMIN)
    assert store.is_proxy(ipaddress.ip_address("172.16.39.1"))
    assert not store.is_proxy(ipaddress.ip_address("172.16.39.2"))
    assert [str(n) for n in store.proxy_networks()] == ["172.16.39.1/32"]
    with pytest.raises(trusted.Refused):
        store.save({"proxies": [{"network": "104.16.0.0/13"}]}, by=ADMIN)  # (Cloudflare's own)
    # (A proxy on this same machine, with host networking, comes from
    # 127.0.0.1: a trusted proxy may be that; a trusted network never.)
    store.save({"proxies": [{"network": "127.0.0.1"}]}, by=ADMIN)
    assert store.is_proxy(ipaddress.ip_address("127.0.0.1"))
    with pytest.raises(trusted.Refused) as refused:
        store.save({"proxies": [{"network": f"10.0.0.{n}"} for n in range(11)]}, by=ADMIN)
    assert str(refused.value) == "List 10 trusted proxies at most."
    # More than one address asks first: every device there could say who a
    # visitor is (the cold audit of 1.36.0).
    with pytest.raises(trusted.Wide) as wide:
        store.save({"proxies": [{"network": "192.168.1.0/30"}]}, by=ADMIN)
    assert str(wide.value).startswith("192.168.1.0/30 is 4 addresses. Every device there")
    store.save({"proxies": [{"network": "192.168.1.0/30"}], "confirmWide": True}, by=ADMIN)
    store.save({"proxies": [{"network": "192.168.1.0/30"}, {"network": "10.0.0.2"}]}, by=ADMIN)


def test_names_for_tapioca_at_home(store):
    store.save({"homeNames": ["TV.Example.com.", "tv.example.com", "nas.example.net"]}, by=ADMIN)
    assert store.home_names == ["tv.example.com", "nas.example.net"]
    for bad in ("192.168.1.5", "bad name!", "x" * 254):
        with pytest.raises(trusted.Refused):
            store.save({"homeNames": [bad]}, by=ADMIN)


def test_what_cant_be_read_trusts_nothing(store, caplog):
    store.db.set_meta(trusted.META, "{not json")
    fresh = trusted.Trusted(store.db, dict)
    assert fresh.entries == [] and fresh.proxies == [] and fresh.home_names == []
    assert "Trusted networks couldn't be read" in caplog.text


def test_a_person_who_goes_takes_their_trust_with_them(store):
    store.save({"entries": [
        entry("192.168.1.44", gives="person", person=USER),
        entry("192.168.1.0/24"),
    ]}, by=ADMIN)  # fmt: skip
    gone = store.reconcile({ADMIN: "admin"})
    assert [e["network"] for e in gone] == ["192.168.1.44/32"]
    assert [e["network"] for e in store.entries] == ["192.168.1.0/24"]
    # Someone made an Admin keeps only single-address entries as themselves.
    store.save({"entries": [entry("192.168.30.0/24", gives="person", person=USER)]}, by=ADMIN)
    store.reconcile({ADMIN: "admin", USER: "admin"})
    [kept] = store.entries
    assert (kept["gives"], kept["person"]) == ("picker", None)


# Signing in on a trusted network -------------------------------------------------

PAT = {"name": "Pat", "password": "correct horse"}


@pytest.fixture
def home(tmp_path):
    """tapiOca, started, with Pat (an Admin, PIN 1234) and Kid (a User with
    no password or PIN) shown on every device at home; 192.168.1.0/24 opens
    on Who's tuning in?, and 192.168.1.44 signs in as Pat. The client: Pat,
    at 192.168.1.50."""
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
        port=3310, public_port=3311,
    )  # fmt: skip
    made = create_app(
        settings, PlexClient("http://plex.test", "token", transport=FakePlex().transport())
    )
    with TestClient(made, base_url="http://192.168.1.20:3310") as pat:
        pat_id = pat.post("/api/access/users", json=PAT).json()["id"]
        assert pat.put(
            f"/api/access/users/{pat_id}/picker", json={"showOn": "home", "pin": "1234"}
        ).is_success
        kid = pat.post("/api/access/users", json={"name": "Kid", "role": "user", "showOn": "home"})
        assert kid.status_code == 201, kid.text
        made.state.ctx.trusted.save({"entries": [
            {"network": "192.168.1.0/24", "label": "Home Wi-Fi", "gives": "picker"},
            {"network": "192.168.1.44", "gives": "person", "person": pat_id},
        ]}, by=pat_id)  # fmt: skip
        made.state.pat, made.state.kid = pat_id, kid.json()["id"]
        yield made


def device_at(app, address: str, host: str = "192.168.1.20:3310", **headers):
    from fastapi.testclient import TestClient

    named = {k.replace("_", "-"): v for k, v in headers.items()}
    return TestClient(app, base_url=f"http://{host}", client=(address, 5000), headers=named or None)


def test_a_trusted_network_opens_on_whos_tuning_in(home):
    tv = device_at(home, "192.168.1.60")
    me = tv.get("/api/access/me").json()
    assert me["user"] is None
    people = {p["name"]: p for p in me["trusted"]["people"]}
    assert me["trusted"]["gives"] == "picker" and set(people) == {"Pat", "Kid"}
    assert people["Pat"]["admin"] and people["Pat"]["pin"] and not people["Kid"]["pin"]
    # Kid picks themselves: no PIN, no password; Kid's limits are Kid's.
    picked = tv.post("/api/access/trusted-sign-in", json={"id": home.state.kid})
    assert picked.status_code == 200, picked.text
    assert tv.get("/api/access/me").json()["user"]["name"] == "Kid"
    # An Admin always gives their PIN (or password).
    other = device_at(home, "192.168.1.61")
    assert other.post("/api/access/trusted-sign-in", json={"id": home.state.pat}).status_code == 403
    signed = other.post("/api/access/trusted-sign-in", json={"id": home.state.pat, "pin": "1234"})
    assert signed.status_code == 200 and other.get("/api/access/me").json()["user"]["name"] == "Pat"


def test_what_a_trusted_network_gives_works_only_there(home):
    tv = device_at(home, "192.168.1.60")
    assert tv.post("/api/access/trusted-sign-in", json={"id": home.state.kid}).status_code == 200
    assert tv.get("/api/channels").status_code == 200
    cookies = dict(tv.cookies)
    # The same sign-in, taken to another VLAN, or the internet: nothing.
    vlan = device_at(home, "192.168.20.5")
    vlan.cookies.update(cookies)
    assert vlan.get("/api/channels").status_code == 401
    away = device_at(home, "192.168.1.60", "192.168.1.20:3311")
    away.cookies.update(cookies)
    assert away.get("/api/channels").status_code == 401
    # Kept so 1.35.0 never finds it: rolled back, it signs in nowhere.
    token = (
        cookies["stationplay_session"]
        if "stationplay_session" in cookies
        else next(iter(cookies.values()))
    )
    assert home.state.ctx.db.session_user(hashlib.sha256(token.encode()).hexdigest(), 0) is None


def test_off_a_trusted_network_nothing_is_skipped(home):
    for c in (
        device_at(home, "192.168.20.5"),  # (another VLAN)
        device_at(home, "192.168.1.60", "tv.example.com:3310"),  # (an internet name)
        device_at(home, "192.168.1.60", x_forwarded_for="192.168.1.7"),  # (not a trusted proxy)
        device_at(home, "192.168.1.60", "192.168.1.20:3311"),  # (the public port)
    ):
        assert "trusted" not in c.get("/api/access/me").json()
        refused = c.post("/api/access/trusted-sign-in", json={"id": home.state.kid})
        assert refused.status_code == 403


def test_an_app_without_whos_tuning_in_is_told_so(home):
    """On a network that opens on Who's tuning in?, an app that hasn't got it
    is told that, not that it isn't on a trusted network (the cold audit of
    1.36.0)."""
    from app import trustedapi

    said = device_at(home, "192.168.1.60").post("/api/internal/trusted", json={"app": "Roku"})
    assert said.status_code == 403 and said.json()["detail"] == trustedapi.NO_PICKER


def test_a_device_signed_in_as_someone(home):
    laptop = device_at(home, "192.168.1.44")
    assert laptop.get("/api/access/me").json()["trusted"] == {"gives": "person", "name": "Pat"}
    assert laptop.post("/api/access/trusted-sign-in", json={}).status_code == 200
    assert laptop.get("/api/access/me").json()["user"]["name"] == "Pat"
    # Its neighbor is the network's: Who's tuning in?.
    assert (
        device_at(home, "192.168.1.45").get("/api/access/me").json()["trusted"]["gives"] == "picker"
    )


def test_an_admins_device_is_never_signed_in_through_a_proxy(home):
    """A proxy's headers say who only as far as it's set up right; a TCP
    forward, or a proxy passing a visitor's own header through, would let
    anyone be the Admin's laptop. So an entry signing in an Admin never
    applies through a proxy: its network's choice does, if any."""
    home.state.ctx.trusted.save({"proxies": [{"network": "192.168.1.2"}]}, by=home.state.pat)
    via = device_at(home, "192.168.1.2", x_forwarded_for="192.168.1.44")
    assert via.get("/api/access/me").json()["trusted"]["gives"] == "picker"
    assert via.post("/api/access/trusted-sign-in", json={}).status_code == 404
    # (Straight from the laptop: as listed.)
    laptop = device_at(home, "192.168.1.44")
    assert laptop.get("/api/access/me").json()["trusted"] == {"gives": "person", "name": "Pat"}
    # (Someone else's device, through the proxy: as listed.)
    pat = admin_at_home(home)
    kid_entry = {"network": "192.168.1.70", "gives": "person", "person": home.state.kid}
    entries = [*pat.get("/api/access/trusted").json()["entries"], kid_entry]
    assert pat.put("/api/access/trusted", json={"entries": entries}).status_code == 200
    via = device_at(home, "192.168.1.2", x_forwarded_for="192.168.1.70")
    assert via.get("/api/access/me").json()["trusted"] == {"gives": "person", "name": "Kid"}


def admin_at_home(home):
    from fastapi.testclient import TestClient

    c = TestClient(home, base_url="http://192.168.1.20:3310", client=("192.168.1.50", 5000))
    assert c.post("/api/access/sign-in", json=PAT).status_code == 200
    return c


def test_admins_list_them_and_what_changes_ends_what_it_gave(home):
    pat = admin_at_home(home)
    got = pat.get("/api/access/trusted").json()
    assert [e["network"] for e in got["entries"]] == ["192.168.1.0/24", "192.168.1.44/32"]
    assert got["entries"][0]["addresses"] == 256
    # (Pat is on the Home Wi-Fi network: the network to offer is shown.)
    assert got["you"]["offer"] == "192.168.1.0/24" and got["you"]["entry"]
    # Kid picks themselves on the TV; then the network goes, and so does that.
    tv = device_at(home, "192.168.1.60")
    assert tv.post("/api/access/trusted-sign-in", json={"id": home.state.kid}).status_code == 200
    assert tv.get("/api/channels").status_code == 200
    kept = [e for e in got["entries"] if e["network"] != "192.168.1.0/24"]
    assert pat.put("/api/access/trusted", json={"entries": kept}).status_code == 200
    assert tv.get("/api/channels").status_code == 401
    # Too wide asks first; public addresses never.
    wide = pat.put("/api/access/trusted", json={"entries": [{"network": "192.168.0.0/16"}]})
    assert wide.status_code == 409 and "65,536 addresses" in wide.json()["detail"]
    sure = {"entries": [{"network": "192.168.0.0/16"}], "confirmWide": True}
    assert pat.put("/api/access/trusted", json=sure).status_code == 200
    public = pat.put("/api/access/trusted", json={"entries": [{"network": "8.8.8.0/24"}]})
    assert public.status_code == 400 and public.json()["detail"] == trusted.INTERNET


def test_only_admins_see_or_change_them(home):
    pat = admin_at_home(home)
    assert pat.post("/api/access/users", json={"name": "Sam", "password": "battery staple",
                                                 "role": "user"}).status_code == 201  # fmt: skip
    sam = device_at(home, "192.168.20.5")
    assert sam.post(
        "/api/access/sign-in", json={"name": "Sam", "password": "battery staple"}
    ).is_success
    assert sam.get("/api/access/trusted").status_code == 403
    assert sam.put("/api/access/trusted", json={"entries": []}).status_code == 403


def test_a_person_removed_or_made_an_admin_takes_their_trust_with_them(home):
    pat = admin_at_home(home)
    sam = pat.post("/api/access/users", json={"name": "Sam", "password": "battery staple",
                                               "role": "user"}).json()  # fmt: skip
    entries = [*pat.get("/api/access/trusted").json()["entries"],
               {"network": "192.168.30.0/24", "gives": "person", "person": sam["id"]}]  # fmt: skip
    assert pat.put("/api/access/trusted", json={"entries": entries}).status_code == 200
    den = device_at(home, "192.168.30.9")
    assert den.post("/api/access/trusted-sign-in", json={}).status_code == 200
    assert den.get("/api/access/me").json()["user"]["name"] == "Sam"
    # Made an Admin: a network can't sign in as an Admin, so it's Who's
    # tuning in? now, and the sign-in it gave ends.
    assert pat.put(f"/api/access/users/{sam['id']}", json={"role": "admin"}).status_code == 200
    assert den.get("/api/access/me").json()["user"] is None
    [kept] = [e for e in pat.get("/api/access/trusted").json()["entries"]
              if e["network"] == "192.168.30.0/24"]  # fmt: skip
    assert (kept["gives"], kept["person"]) == ("picker", None)


def test_wrong_pins_on_a_trusted_picker_are_limited_here_and_an_admins_lock_is_an_alert(home):
    """Each person's PIN: 5 tries, then 15 minutes (as on the apps). From
    one device (by its address, never a cookie a guesser can change):
    BROWSER_PIN_TRIES, then a password there. An Admin's PIN locked is an
    Admin alert (no name, no address), fixed once it's unlocked."""
    from app import alerts, devices

    ctx = home.state.ctx
    pat = admin_at_home(home)
    ids = {}
    for name, pin in (("Ann", "1111"), ("Bo", "2222")):
        made = pat.post("/api/access/users", json={"name": name, "role": "user", "showOn": "home"})
        ids[name] = made.json()["id"]
        assert pat.put(f"/api/access/users/{ids[name]}/picker", json={"pin": pin}).is_success
    tv = device_at(home, "192.168.1.60")

    def pick(c, who, **said):
        return c.post("/api/access/trusted-sign-in", json={"id": who, **said})

    for _ in range(devices.PIN_TRIES):
        assert pick(tv, home.state.pat, pin="0000").status_code == 403
    assert pick(tv, home.state.pat, pin="1234").status_code == 429  # (Pat waits)
    [locked] = [a for a in ctx.alerts.now() if a.about == "pin"]
    assert locked.kind == "access" and locked.sentence == alerts.PIN_LOCKED
    assert f"{devices.PIN_TRIES} times" in locked.sentence
    assert f"{devices.PIN_WAIT_S // 60} minutes" in locked.sentence
    # Others' PINs from the same TV: 10 wrong there in all, then a password.
    for _ in range(access.BROWSER_PIN_TRIES - devices.PIN_TRIES - 1):
        assert pick(tv, ids["Ann"], pin="0000").status_code == 403
    last = pick(tv, ids["Ann"], pin="0000")
    assert last.status_code == 403 and last.json()["detail"] == trustedapi.PASSWORD_NOW
    assert pick(tv, ids["Bo"], pin="2222").json()["detail"] == trustedapi.PASSWORD_NOW
    # (Another device, and the right PIN: fine.)
    assert pick(device_at(home, "192.168.1.61"), ids["Bo"], pin="2222").status_code == 200
    # A password on the TV: right, and PINs work there again.
    assert pick(tv, home.state.pat, password="wrong one").status_code == 401
    assert pick(tv, home.state.pat, password=PAT["password"]).status_code == 200
    assert pick(tv, ids["Bo"], pin="2222").status_code == 200
    # 15 minutes on, Pat's PIN is unlocked: the alert is fixed.
    assert ctx.devices.admins_locked()
    for wrong in ctx.devices._wrong.values():  # (as if 15 minutes went by)
        wrong.extend([t - devices.PIN_WAIT_S - 1 for t in wrong])
        for _ in range(len(wrong) // 2):
            wrong.popleft()
    assert not ctx.devices.admins_locked()
    ctx.alerts.doors(ctx.doors, open_=False, home_port=3310, public_port=3311,
                     pin_locked=ctx.devices.admins_locked())  # fmt: skip
    assert not [a for a in ctx.alerts.now() if a.about == "pin"]


def test_reset_access_takes_what_signed_in_someone_with_it(home, tmp_path):
    """The reset-access file removes everyone; at the next start, an entry
    that signed someone in goes too (and a network's choice stays, for when
    signing in is on again)."""
    from app import access
    from app.config import Settings
    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    (tmp_path / "data" / access.RESET_FILE).write_text("")
    again = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
    )
    left = again.state.ctx.trusted.entries
    assert [(e["network"], e["gives"]) for e in left] == [("192.168.1.0/24", "picker")]


def test_reset_access_clears_trusted_proxies_too(home, tmp_path):
    """The cold audit of 1.36.1: a trusted proxy listed by mistake (the
    Admin's own computer, say) keeps the page from them at home, and the
    reset-access file didn't clear it."""
    from fastapi.testclient import TestClient

    from app import access
    from app.config import Settings
    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    home.state.ctx.trusted.save({"proxies": [{"network": "192.168.1.50"}]}, by=None)
    (tmp_path / "data" / access.RESET_FILE).write_text("")
    again = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
    )
    assert again.state.ctx.trusted.proxies == []
    with TestClient(again, client=("192.168.1.50", 5)) as me:
        assert me.get("/api/status").status_code == 200


def test_a_sign_in_made_without_a_secret_mints_nothing_that_leaves_its_network(home):
    """A trusted network's sign-in made with no PIN or password (Signed in
    as, or Who's tuning in? for someone with neither) can't change anyone's
    password or PIN, add people, make API tokens or invite codes; and no
    sign-in a network gives can link an app (which would sign it in
    anywhere). The cold audit of 1.36.0."""
    laptop = device_at(home, "192.168.1.44")  # (Signed in as Pat, an Admin)
    assert laptop.post("/api/access/trusted-sign-in", json={}).status_code == 200
    pat, kid = home.state.pat, home.state.kid
    for method, path, body in (
        ("PUT", f"/api/access/users/{pat}", {"password": "a brand new one"}),
        ("PUT", f"/api/access/users/{kid}", {"password": "a brand new one"}),
        ("PUT", f"/api/access/users/{kid}/picker", {"pin": "0000"}),
        (
            "POST",
            "/api/access/users",
            {"name": "Eve", "password": "a plenty long password", "role": "admin"},
        ),
        ("POST", f"/api/access/users/{kid}/invite", None),
        ("POST", "/api/api-tokens", {"name": "Mine", "scope": "admin"}),
    ):
        said = laptop.request(method, path, json=body)
        assert said.status_code == 403, (path, said.text)
        # (For an Admin, the Gate asks for their password first: see the
        # next test. STEP_UP is the handlers' own refusal, behind it.)
        assert said.json()["detail"] in (access.ADMIN_PASSWORD_NEEDED, access.STEP_UP)
    # Linking an app: never from a sign-in a network gave.
    phone = device_at(home, "192.168.20.9")
    code = phone.post("/api/internal/link", json={"app": "tapiOca for Android"}).json()["code"]
    tv = device_at(home, "192.168.1.60")
    assert tv.post("/api/access/trusted-sign-in", json={"id": kid}).status_code == 200
    for c in (tv, laptop):
        said = c.post("/api/access/link", json={"code": code})
        assert said.status_code == 403 and said.json()["detail"] == access.LINK_BOUND, said.text
    # (With a password, as ever.)
    pc = admin_at_home(home)
    assert pc.post("/api/access/link", json={"code": code}).status_code == 200


def test_made_an_admin_their_sign_ins_without_a_secret_end(home):
    """An Admin always gives a PIN or password: someone made an Admin loses
    what was signed in for them with neither (picked on Who's tuning in?,
    or a device a network signs in as them, which becomes Who's tuning in?
    until an Admin chooses Signed in as them again). The cold audit of
    1.36.0."""
    pat = admin_at_home(home)
    sam = pat.post("/api/access/users", json={"name": "Sam", "password": "battery staple",
                                              "role": "user", "showOn": "home"}).json()  # fmt: skip
    entries = [*pat.get("/api/access/trusted").json()["entries"],
               {"network": "192.168.1.70", "gives": "person", "person": sam["id"]}]  # fmt: skip
    assert pat.put("/api/access/trusted", json={"entries": entries}).status_code == 200
    tv = device_at(home, "192.168.1.60")
    assert tv.post("/api/access/trusted-sign-in", json={"id": sam["id"]}).status_code == 200
    phone = device_at(home, "192.168.1.70")
    assert phone.post("/api/access/trusted-sign-in", json={}).status_code == 200
    assert pat.put(f"/api/access/users/{sam['id']}", json={"role": "admin"}).status_code == 200
    for c in (tv, phone):
        assert c.get("/api/access/trusted").status_code == 401
        assert c.get("/api/access/me").json()["user"] is None
    assert phone.get("/api/access/me").json()["trusted"]["gives"] == "picker"
    # (Chosen again, deliberately: as listed.)
    again = [e if e["network"] != "192.168.1.70/32" else {**e, "gives": "person", "person": sam["id"]}
             for e in pat.get("/api/access/trusted").json()["entries"]]  # fmt: skip
    assert pat.put("/api/access/trusted", json={"entries": again}).status_code == 200
    assert phone.get("/api/access/me").json()["trusted"] == {"gives": "person", "name": "Sam"}


def test_a_network_cant_be_used_to_sign_people_out_or_unlink_devices(home, monkeypatch):
    """Asking a trusted network for sign-ins and devices is limited for each
    address; its sign-ins never push out someone's others (an Admin's
    phone, say), and a full network refuses a new device rather than
    unlinking one in use. The cold audit of 1.36.0."""
    from app import devices, trustedapi

    pat = admin_at_home(home)
    sam = pat.post("/api/access/users", json={"name": "Sam", "password": "battery staple",
                                              "role": "user", "showOn": "home"}).json()  # fmt: skip
    entries = [*pat.get("/api/access/trusted").json()["entries"],
               {"network": "192.168.30.0/24", "gives": "person", "person": sam["id"]}]  # fmt: skip
    assert pat.put("/api/access/trusted", json={"entries": entries}).status_code == 200
    phone = device_at(home, "192.168.20.5")
    assert phone.post(
        "/api/access/sign-in", json={"name": "Sam", "password": "battery staple"}
    ).is_success
    for n in range(access.SESSIONS_KEPT + 5):
        asked = device_at(home, f"192.168.30.{n + 1}").post(
            "/api/internal/trusted", json={"app": "TV"}
        )
        assert asked.status_code == 200, asked.text
    assert phone.get("/api/channels").status_code == 200
    # One address: so many, then a wait.
    den = device_at(home, "192.168.30.200")
    said = [den.post("/api/internal/trusted", json={"app": "TV"}).status_code
            for _ in range(trustedapi.ASKS_MOST + 1)]  # fmt: skip
    assert said[:-1] == [200] * trustedapi.ASKS_MOST and said[-1] == 429
    tv = device_at(home, "192.168.1.200")
    said = [tv.post("/api/access/trusted-sign-in", json={"id": home.state.kid}).status_code
            for _ in range(trustedapi.ASKS_MOST + 1)]  # fmt: skip
    assert said[-1] == 429
    # A full network: a new device takes the place of one never used
    # (asked for, then not used: what a flood of asks makes), never of one
    # in use; with every one in use, no new device.
    monkeypatch.setattr(devices, "TRUSTED_DEVICES_MOST", 2)

    def link(n: int) -> httpx.Response:
        return device_at(home, f"192.168.1.{80 + n}").post(
            "/api/internal/trusted", json={"app": "TV", "picker": True}
        )

    def use(n: int, key: str) -> int:
        return (
            device_at(home, f"192.168.1.{80 + n}", stationplay_device=key)
            .get("/api/internal/picker")
            .status_code
        )

    def pick(n: int, key: str) -> int:
        return (
            device_at(home, f"192.168.1.{80 + n}", stationplay_device=key)
            .post("/api/internal/picker/choose", json={"id": home.state.kid})
            .status_code
        )

    first, second = link(0).json()["deviceKey"], link(1).json()["deviceKey"]
    assert pick(0, first) == 200
    for _ in range(3):
        assert use(1, second) == 200  # (asking isn't using: no one was picked on it)
    third = link(2)
    assert third.status_code == 200, third.text
    assert use(0, first) == 200 and use(1, second) == 401  # (the one never used went)
    assert pick(2, third.json()["deviceKey"]) == 200
    full = link(3)
    assert full.status_code == 403 and full.json()["detail"] == devices.NETWORK_FULL
    assert use(0, first) == 200


def test_a_password_on_a_device_a_network_linked_makes_it_ordinary(home):
    """Signing in by name on Who's tuning in? (a password or invite code),
    as signing in in the app does: the device then works anywhere, as any
    linked device; and removing the network signs out whoever's on its
    devices."""
    tablet = device_at(home, "192.168.1.61")
    key = tablet.post("/api/internal/trusted", json={"app": "Tablet", "picker": True}).json()[
        "deviceKey"
    ]
    away = device_at(home, "192.168.20.5", stationplay_device=key)
    assert away.get("/api/internal/picker").status_code == 403
    on = device_at(home, "192.168.1.61", stationplay_device=key)
    signed = on.post(
        "/api/internal/picker/sign-in", json={"name": "Pat", "password": PAT["password"]}
    )
    assert signed.status_code == 200, signed.text
    assert away.get("/api/internal/picker").status_code == 200
    # (Another, still the network's: removing the network signs out who's on it.)
    other = device_at(home, "192.168.1.62")
    key2 = other.post("/api/internal/trusted", json={"app": "TV", "picker": True}).json()[
        "deviceKey"
    ]
    tv = device_at(home, "192.168.1.62", stationplay_device=key2)
    token = tv.post("/api/internal/picker/choose", json={"id": home.state.kid}).json()["token"]
    pat = admin_at_home(home)
    kept = [e for e in pat.get("/api/access/trusted").json()["entries"]
            if e["network"] != "192.168.1.0/24"]  # fmt: skip
    assert pat.put("/api/access/trusted", json={"entries": kept}).status_code == 200
    gone = device_at(home, "192.168.1.62", authorization=f"Bearer {token}")
    assert gone.get("/api/channels").status_code == 401


def test_the_away_address_name_is_never_a_name_for_home(home):
    """It's how the internet reaches tapiOca, so the Gate never takes it for
    home: listing it is refused, saying so (the cold audit of 1.36.0)."""
    pat = admin_at_home(home)
    assert pat.put("/api/away", json={"on": False, "address": "https://tv.example.com"}).is_success
    said = pat.put("/api/access/trusted", json={"homeNames": ["TV.example.com."]})
    assert said.status_code == 400 and said.json()["detail"].startswith("TV.example.com is your")
    assert pat.put("/api/access/trusted", json={"homeNames": ["nas.example.com"]}).is_success
    # (The other way about: a name listed first, then made the away address.)
    assert pat.put("/api/away", json={"on": False, "address": "https://nas.example.com"}).is_success
    assert pat.get("/api/access/trusted").json()["homeNames"] == []


def test_wrong_pins_from_one_device_are_counted_for_an_hour(home, monkeypatch):
    """Not forever: a device's wrong PINs on Who's tuning in? stop counting
    after WRONG_PINS_WINDOW_S, so a PIN-only kid isn't told to use a
    password for good (the cold audit of 1.36.0). Here, as if each were an
    hour old already."""
    from app import trustedapi

    monkeypatch.setattr(trustedapi, "WRONG_PINS_WINDOW_S", 0.0)
    pat = admin_at_home(home)
    ids = []
    for n, name in enumerate(("Ann", "Bo", "Cy")):
        made = pat.post("/api/access/users", json={"name": name, "role": "user", "showOn": "home"})
        ids.append(made.json()["id"])
        assert pat.put(f"/api/access/users/{ids[-1]}/picker", json={"pin": f"111{n}"}).is_success
    tv = device_at(home, "192.168.1.66")
    for who in (ids[0],) * 4 + (ids[1],) * 4 + (ids[2],) * 2:
        said = tv.post("/api/access/trusted-sign-in", json={"id": who, "pin": "9999"})
        assert said.status_code == 403 and said.json()["detail"] != trustedapi.PASSWORD_NOW
    assert (
        tv.post("/api/access/trusted-sign-in", json={"id": ids[2], "pin": "1112"}).status_code
        == 200
    )


def test_a_networks_sign_in_streams_only_there(home):
    """A stream address made for a sign-in a trusted network gave works
    only on that network, as the sign-in does (the cold audit of 1.36.0:
    it worked on any home VLAN)."""
    ctx = home.state.ctx
    entry = ctx.trusted.entry_for(ipaddress.ip_address("192.168.1.60"))
    kid = ctx.db.user(home.state.kid)
    token = ctx.access.start_session(kid, "TV", unlocked=True, trusted=entry["id"])
    key = ctx.away.key_for(access.session_hash(token), kid, home=True)
    assert ctx.away.user_of(key, recheck=True, outside=False, where=entry["id"]) is not None
    assert ctx.away.user_of(key, recheck=True, outside=False, where="") is None
    assert ctx.away.user_of(key, recheck=True, outside=False, where="tnother") is None
    # (Over HTTP: from another VLAN, the stream's own address is gone.)
    vlan = device_at(home, "192.168.20.5")
    assert vlan.get(f"/hls/k/{key}/1/index.m3u8").status_code == 404


def test_a_networks_sign_in_plays_media_only_there(home):
    """The same for a program started in Media: its play address works
    only on the network whose sign-in started it (the cold audit of 1.36.0)."""
    from types import SimpleNamespace

    ctx = home.state.ctx
    entry = ctx.trusted.entry_for(ipaddress.ip_address("192.168.1.60"))
    kid = ctx.db.user(home.state.kid)
    token = ctx.access.start_session(kid, "TV", unlocked=True, trusted=entry["id"])
    play = ctx.plays.start(
        user_id=kid.id, user=kid.name, sign_in=access.session_hash(token),
        entry=SimpleNamespace(key="300", show_key=None), media=None, path=None, plex=None,
        client="192.168.1.60", away=False,
    )  # fmt: skip
    vlan = device_at(home, "192.168.20.5")
    for path in ("file.mkv", "index.m3u8"):
        gone = vlan.get(f"/play/{play.id}/{path}")
        assert gone.status_code == 404, path


def test_an_admin_signed_in_by_a_network_gives_their_password_for_admin_tasks(home):
    """A network's sign-in for an Admin (Signed in as, or picked with a PIN)
    is for watching: anything only an Admin may do (Access, Setup, backups,
    restoring, roles, the trusted lists) asks for their password, and it
    makes no credential at all. An address isn't a password, nor is a
    4-digit PIN typed on a shared screen. Picking themselves with their
    password is an ordinary sign-in. The cold audit of 1.36.0, again."""
    pat_id, kid = home.state.pat, home.state.kid
    laptop = device_at(home, "192.168.1.44")  # (Signed in as Pat)
    assert laptop.post("/api/access/trusted-sign-in", json={}).status_code == 200
    tv = device_at(home, "192.168.1.60")
    assert tv.post("/api/access/trusted-sign-in", json={"id": pat_id, "pin": "1234"}).is_success
    for c in (laptop, tv):
        me = c.get("/api/access/me").json()["user"]
        assert me["role"] == "admin" and me["byNetwork"] is True
        for method, path, body in (
            ("GET", "/api/access/trusted", None),
            ("PUT", "/api/access/trusted", {"entries": []}),
            ("PUT", f"/api/access/users/{kid}", {"role": "admin"}),
            ("PUT", f"/api/access/users/{pat_id}", {"password": "a brand new one"}),
            ("POST", "/api/backups", None),
            ("GET", "/api/access/users", None),
            ("POST", "/api/api-tokens", {"name": "Mine", "scope": "admin"}),
        ):
            said = c.request(method, path, json=body)
            assert said.status_code == 403, (path, said.text)
            assert said.json()["detail"] in (access.ADMIN_PASSWORD_NEEDED, access.STEP_UP)
        # (Watching, as anyone can.)
        assert c.get("/api/channels").status_code == 200
    # With their password, on the same TV: an ordinary sign-in, an Admin's.
    other = device_at(home, "192.168.1.61")
    signed = other.post(
        "/api/access/trusted-sign-in", json={"id": pat_id, "password": PAT["password"]}
    )
    assert signed.status_code == 200
    assert other.get("/api/access/me").json()["user"].get("byNetwork") is False
    assert other.get("/api/access/trusted").status_code == 200
    away = device_at(home, "192.168.20.5")
    away.cookies.update(dict(other.cookies))
    assert away.get("/api/channels").status_code == 200


def test_an_admin_by_network_is_a_user_and_their_own_devices_are_as_before(home):
    """A network's sign-in for an Admin acts as a User's everywhere (who
    watched what, how the server is set up, others' stations), as the page
    shows it; an app's /me says so, so it doesn't ask for Admin alerts. But
    an Admin with no PIN picking themselves on their own linked device (as
    1.35.0 allowed) is an Admin as before, and so is one who gives their
    password on a network's device. A network's PIN sign-in can't change
    that PIN. The cold audit of 1.36.0, third round."""
    pat_id = home.state.pat
    laptop = device_at(home, "192.168.1.44")
    assert laptop.post("/api/access/trusted-sign-in", json={}).status_code == 200
    assert "people" not in laptop.get("/api/stats").json()
    assert "devices" not in laptop.get("/api/status").json()
    pc = admin_at_home(home)
    assert "people" in pc.get("/api/stats").json()
    # An app the network signed in as Pat: a User, by network.
    signed = laptop.post("/api/internal/trusted", json={"app": "Phone"}).json()
    assert signed["user"] == {"name": "Pat", "role": "user", "byNetwork": True}
    token = signed["token"]
    app = device_at(home, "192.168.1.44", authorization=f"Bearer {token}")
    me = app.get("/api/internal/me").json()["user"]
    assert (me["role"], me["byNetwork"]) == ("user", True)
    # Jo, an Admin with no PIN, picked with nothing on her own linked phone
    # (1.35.0's way, where only she is on it: an unlocked sign-in, not a
    # network's): an Admin as before.
    jo = pc.post(
        "/api/access/users",
        json={"name": "Jo", "password": "a plenty long password", "role": "admin"},
    )
    ctx = home.state.ctx
    picked = ctx.access.start_session(ctx.db.user(jo.json()["id"]), "Phone", unlocked=True)
    mine = device_at(home, "192.168.20.7", authorization=f"Bearer {picked}")
    assert mine.get("/api/internal/alerts").status_code == 200
    assert "byNetwork" not in mine.get("/api/internal/me").json()["user"]
    # Pat with his PIN on a network's TV app: for watching; his PIN stays.
    tv_key = device_at(home, "192.168.1.60").post(
        "/api/internal/trusted", json={"app": "TV", "picker": True}).json()["deviceKey"]  # fmt: skip
    tv = device_at(home, "192.168.1.60", stationplay_device=tv_key)
    by_pin = tv.post("/api/internal/picker/choose", json={"id": pat_id, "pin": "1234"}).json()
    assert by_pin["user"] == {"name": "Pat", "role": "user", "byNetwork": True}  # (as /me says)
    pins = device_at(home, "192.168.1.60", authorization=f"Bearer {by_pin['token']}")
    said = pins.post("/api/internal/pin", json={"pin": "4321"})
    assert said.status_code == 403 and said.json()["detail"] == access.STEP_UP
    assert pins.get("/api/internal/alerts").status_code == 403
    # Jo with her password on the same TV: an ordinary sign-in, an Admin's.
    assert pc.put(f"/api/access/users/{jo.json()['id']}/picker", json={"showOn": "home"}).is_success
    by_password = tv.post(
        "/api/internal/picker/choose",
        json={"id": jo.json()["id"], "password": "a plenty long password"},
    )
    assert by_password.status_code == 200, by_password.text
    hers = device_at(home, "192.168.20.7", authorization=f"Bearer {by_password.json()['token']}")
    assert hers.get("/api/internal/alerts").status_code == 200  # (anywhere: not the network's)


def test_a_proxy_trusted_since_is_no_longer_a_door(home):
    """(1.36.2) The owner, October 14: the Access tab still said "isn't a
    trusted proxy" beside the proxy he'd just trusted, and its alert stayed.
    Listing it ends both."""
    ctx = home.state.ctx
    device_at(home, "192.168.1.2", x_forwarded_for="192.168.1.60").get("/api/access/me")
    assert [d["about"] for d in ctx.doors.listed()] == ["proxy-unknown"]
    pat = admin_at_home(home)
    assert pat.put("/api/access/trusted", json={"proxies": [{"network": "192.168.1.2"}]}).is_success
    assert ctx.doors.listed() == []


def test_a_browser_its_person_signed_in_on_lists_them_for_their_pin(home):
    """(The owner, October 15: signed out after an hour without activity, on
    a trusted network, the page's picker listed no one and asked only for a
    password, though he'd signed in on that browser with his password, so
    his PIN should do, as it does on a browser at home.) Someone shown only
    on devices they've signed in on: on a browser they signed in on with
    their password, the page's picker lists them, with their PIN; on
    another browser, or after signing out on purpose, it doesn't."""
    pat = admin_at_home(home)
    made = pat.post("/api/access/users", json={
        "name": "Lee", "password": "harbor violet quill", "role": "user", "showOn": "signed-in"})  # fmt: skip
    assert made.status_code == 201, made.text
    lee = made.json()["id"]
    assert pat.put(f"/api/access/users/{lee}/picker", json={"pin": "4242"}).is_success

    def listed(c) -> dict:
        return {p["name"]: p for p in c.get("/api/access/me").json()["trusted"]["people"]}

    laptop = device_at(home, "192.168.1.70")
    signed = laptop.post("/api/access/sign-in", json={"name": "Lee", "password": "harbor violet quill"})
    assert signed.status_code == 200, signed.text
    # An hour without activity: signed out (the sign-in's cookie gone, the browser's kept).
    laptop.cookies.delete(access.COOKIE)
    assert "Lee" in listed(laptop) and listed(laptop)["Lee"]["pin"]
    # Another browser on the same network: not listed, and can't pick Lee.
    other = device_at(home, "192.168.1.71")
    assert "Lee" not in listed(other)
    assert other.post("/api/access/trusted-sign-in", json={"id": lee, "pin": "4242"}).status_code == 404
    # Picked on the laptop: Lee's PIN signs Lee in; a wrong one doesn't.
    assert laptop.post("/api/access/trusted-sign-in", json={"id": lee, "pin": "0000"}).status_code == 403
    picked = laptop.post("/api/access/trusted-sign-in", json={"id": lee, "pin": "4242"})
    assert picked.status_code == 200, picked.text
    assert laptop.get("/api/access/me").json()["user"]["name"] == "Lee"
    # Signed out on purpose: the password first, next time.
    assert laptop.post("/api/access/sign-out").status_code == 200
    assert "Lee" not in listed(laptop)
