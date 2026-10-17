"""How an Admin signs in (1.38.0, the owner, October 17), their own choice:
Full, their password for every sign-in that does Admin tasks; or Light, their
password once on a browser or device, then their PIN there, at home, for
their Admin tools. And the page's sign-in screen: only the Admins who signed
in on that browser with their password, never a User (the owner: "No user
appears on the server sign in page at all unless their user is set as Admin
(not just User)").

1.37.1 made an Admin's PIN on a trusted network's sign-in screen a sign-in for
watching, with no word of why the Admin tabs went, and listed everyone shown
at home there."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, devices
from app.db import Database

from .test_picker import TV, away_from_home, bearer, device, two_ports

PAT = {"name": "Pat", "password": "correct horse"}
LEE = {"name": "Lee", "password": "harbor violet quill"}
SAM = {"name": "Sam", "password": "battery staple"}
PUBLIC = "http://testserver:8443"


@pytest.fixture
def app(tmp_path):
    return two_ports(tmp_path)


@pytest.fixture
def pat(app):
    """Pat (an Admin, PIN 1234), signed in with his password; Lee (an
    Admin, PIN 4242); Sam (a User, PIN 5555); and Kids, shown on every device
    at home, as a household had them."""
    with TestClient(app) as client:
        ids = {"Pat": client.post("/api/access/users", json=PAT).json()["id"]}
        for who, role in ((LEE, "admin"), (SAM, "user")):
            made = client.post("/api/access/users", json={**who, "role": role, "showOn": "home"})
            assert made.status_code == 201, made.text
            ids[who["name"]] = made.json()["id"]
        kids = client.post("/api/access/users", json={"name": "Kids", "role": "user"})
        ids["Kids"] = kids.json()["id"]
        for name, pin in (("Pat", "1234"), ("Lee", "4242"), ("Sam", "5555")):
            assert client.put(f"/api/access/users/{ids[name]}/picker", json={"pin": pin}).is_success
        assert client.post("/api/access/devices/everyone", json={"showOn": "home"}).is_success
        client.ids = ids
        yield client


def browser(app, who=None) -> TestClient:
    c = TestClient(app)
    if who:
        assert c.post("/api/access/sign-in", json=who).status_code == 200
    return c


def idle(c: TestClient) -> TestClient:
    """An hour without activity: its sign-in over, the browser itself kept."""
    c.cookies.delete(access.COOKIE)
    assert c.get("/api/access/me").json()["user"] is None
    return c


def light(c: TestClient, who=PAT) -> None:
    chose = c.put("/api/access/me/sign-in", json={"how": "light", "password": who["password"]})
    assert chose.status_code == 200, chose.text


def tiles(c: TestClient) -> list[tuple[str, bool]]:
    return [(p["name"], p["pin"]) for p in c.get("/api/access/me").json().get("people", [])]


def pin(c: TestClient, user_id: int, said: str):
    return c.post("/api/access/pin-sign-in", json={"id": user_id, "pin": said})


ADMIN_ONLY = (("GET", "/api/logs"), ("GET", "/api/access/trusted"), ("GET", "/api/access/users"))


def admin_tools(c: TestClient, **kw) -> list[int]:
    return [c.request(m, path, **kw).status_code for m, path in ADMIN_ONLY]


# The page's sign-in screen ------------------------------------------------------------


def test_a_new_browser_lists_no_one(pat, app):
    """P01, P06: 2 Admins and 2 Users, shown on every device at home: a
    browser no one signed in on lists no one, and the password is offered."""
    me = browser(app).get("/api/access/me").json()
    assert me["required"] and me["user"] is None and "people" not in me


def test_only_the_admins_who_signed_in_on_it(pat, app):
    """P02, P04, P05: the Admins who signed in on this browser with their
    password, latest first; a User who did is never listed, though their
    password still signs them in there; another browser has none of them."""
    pc = browser(app, PAT)
    assert pc.post("/api/access/sign-in", json=SAM).status_code == 200
    assert pc.post("/api/access/sign-in", json=LEE).status_code == 200
    assert tiles(idle(pc)) == [("Lee", False), ("Pat", False)]  # (Full: the password each time)
    assert tiles(browser(app)) == []
    # Lee is a User now: off the sign-in screen at once.
    assert pat.put(f"/api/access/users/{pat.ids['Lee']}", json={"role": "user"}).is_success
    assert tiles(pc) == [("Pat", False)]
    # A tile is no sign-in: picking one asks for that Admin's password.
    assert pin(pc, pat.ids["Pat"], "1234").status_code == 400
    assert pc.get("/api/access/me").json()["user"] is None


def test_remove_from_this_browser(pat, app):
    """P17: Sign out ends the sign-in and keeps the Admin on the sign-in
    screen; Remove from this browser takes them off it, there only, until
    their password signs in there again."""
    pc, other = browser(app, PAT), browser(app, PAT)
    assert pc.post("/api/access/sign-out").status_code == 200
    assert tiles(pc) == [("Pat", False)]
    gone = pc.post("/api/access/browser/forget", json={"id": pat.ids["Pat"]})
    assert gone.status_code == 200
    assert tiles(pc) == [] and tiles(idle(other)) == [("Pat", False)]
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "Pat was removed from a browser's sign-in screen at 192.168.1.50" in log
    # (Anyone else, or no one: nothing said, nothing changed.)
    for who in (pat.ids["Lee"], 999):
        assert other.post("/api/access/browser/forget", json={"id": who}).status_code == 200
    assert tiles(other) == [("Pat", False)]
    assert browser(app).post("/api/access/browser/forget", json={"id": 1}).status_code == 200
    assert pc.post("/api/access/sign-in", json=PAT).status_code == 200
    assert tiles(idle(pc)) == [("Pat", False)]


def test_no_one_learns_who_chose_light(pat, app):
    """A15: only an Admin's own /me says how they sign in."""
    light(pat)
    assert "adminSignIn" not in browser(app, SAM).get("/api/access/me").json()["user"]
    assert pat.get("/api/access/me").json()["user"]["adminSignIn"] == "light"
    assert browser(app, LEE).get("/api/access/me").json()["user"]["adminSignIn"] == "full"
    users = pat.get("/api/access/users").json()
    assert all("adminSignIn" not in u for u in users)
    assert tiles(idle(browser(app, PAT))) == [("Pat", True)]  # (to that browser only: its PIN)


# Full and Light on the page ----------------------------------------------------------------


def test_full_is_the_password_every_time(pat, app):
    """A01, A14: Full, from the start: the sign-in screen lists Pat on his
    browser, for his password; his PIN never signs him in on the page."""
    pc = idle(browser(app, PAT))
    assert tiles(pc) == [("Pat", False)]
    refused = pin(pc, pat.ids["Pat"], "1234")
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Pat's sign-in is Full, so it needs the password every time."
    assert pc.get("/api/access/me").json()["user"] is None
    assert pc.post("/api/access/sign-in", json=PAT).status_code == 200
    assert admin_tools(pc) == [200, 200, 200]


def test_light_is_the_pin_for_admin_tools_on_that_browser(pat, app):
    """A03, P12: Light, then an hour without activity: Pat's PIN on the
    browser he signed in on with his password brings back Setup, Access, Logs
    and Broken files, and they work."""
    pc = browser(app, PAT)
    light(pc)
    idle(pc)
    assert tiles(pc) == [("Pat", True)]
    assert pin(pc, pat.ids["Pat"], "1234").status_code == 200
    me = pc.get("/api/access/me").json()["user"]
    assert (me["name"], me["role"], me["adminTools"], me["watching"]) == (
        "Pat",
        "admin",
        True,
        False,
    )
    assert admin_tools(pc) == [200, 200, 200]
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "Pat chose Light sign-in" in log
    assert "Pat (Admin) signed in with their PIN from 192.168.1.50" in log


def test_light_never_on_another_browser(pat, app):
    """A02, A04, P03: never on a browser Pat hasn't signed in on with his
    password, even knowing his name and id, on the same network."""
    light(pat)
    other = browser(app)
    for body in ({"id": pat.ids["Pat"], "pin": "1234"}, {"pin": "1234"}):
        refused = other.post("/api/access/pin-sign-in", json=body)
        assert refused.status_code == 400
    assert other.get("/api/access/me").json()["user"] is None
    # (Its cookie made up: the same.)
    other.cookies.set(access.DEVICE_COOKIE, "pat's, perhaps")
    assert pin(other, pat.ids["Pat"], "1234").status_code == 400


def test_light_gives_admin_tools_only_at_home(pat, app):
    """A11, P26: the PIN's sign-in, taken away from home (the public port):
    for watching, saying why; never Admin tools there."""
    pc = browser(app, PAT)
    light(pc)
    assert pin(idle(pc), pat.ids["Pat"], "1234").status_code == 200
    away = TestClient(app, base_url=PUBLIC, headers={"X-Forwarded-Proto": "https"})
    away.cookies.update(dict(pc.cookies))
    me = away.get("/api/access/me").json()["user"]
    assert (me["name"], me["adminTools"], me["watching"]) == ("Pat", False, True)
    said = away.get("/api/logs")
    assert said.status_code == 403 and said.json()["detail"] == access.WATCHING_ONLY
    assert away.get("/api/channels").status_code == 200
    # And from the internet, never the PIN at all.
    assert away.post("/api/access/pin-sign-in", json={"pin": "1234"}).status_code == 404


def test_a_pins_sign_in_makes_no_credential(pat, app):
    """A PIN's sign-in can't change passwords or PINs, add people, make API
    tokens or invite codes, or link an app: each would work where the PIN
    doesn't (as a trusted network's sign-in, access.STEP_UP). Nor can it
    make someone an Admin, or change where home is (trusted networks,
    proxies and names): the cold audit of 1.38.0 made Sam an Admin with
    Pat's PIN at home, and Sam's password then gave Admin tools from the
    internet."""
    pc = browser(app, PAT)
    light(pc)
    assert pin(idle(pc), pat.ids["Pat"], "1234").status_code == 200
    for method, path, body in (
        ("PUT", f"/api/access/users/{pat.ids['Sam']}", {"password": "a brand new one"}),
        ("PUT", f"/api/access/users/{pat.ids['Sam']}/picker", {"pin": "0000"}),
        (
            "POST",
            "/api/access/users",
            {"name": "Eve", "password": "a long password", "role": "admin"},
        ),
        ("POST", f"/api/access/users/{pat.ids['Kids']}/invite", None),
        ("POST", "/api/api-tokens", {"name": "Mine", "scope": "admin"}),
        ("PUT", f"/api/access/users/{pat.ids['Sam']}", {"role": "admin"}),
        ("PUT", "/api/access/trusted", {"proxies": [{"network": "192.168.1.9"}]}),
        ("PUT", "/api/access/trusted", {"homeNames": ["tv.example.net"]}),
        ("PUT", "/api/access/trusted", {"entries": [{"network": "192.168.1.0/24"}]}),
    ):
        said = pc.request(method, path, json=body)
        assert said.status_code == 403 and said.json()["detail"] == access.STEP_UP, (
            path,
            said.text,
        )
    phone = TestClient(app)
    code = phone.post("/api/internal/link", json={"app": "tapiOca for Android"}).json()["code"]
    said = pc.post("/api/access/link", json={"code": code})
    assert said.status_code == 403 and said.json()["detail"] == access.LINK_BOUND
    roles = {u["name"]: u["role"] for u in pat.get("/api/access/users").json()}
    assert roles["Sam"] == "user"
    away = TestClient(app, base_url=PUBLIC, headers={"X-Forwarded-Proto": "https"})
    assert away.post("/api/access/sign-in", json=SAM).status_code == 200
    assert away.get("/api/access/users").status_code == 403
    # (Everything else an Admin does, it does: a limit, say, or a User's
    # role taken away, which ends their sign-ins.)
    assert pc.put(f"/api/access/users/{pat.ids['Kids']}", json={"maxStations": 1}).is_success
    assert pc.put(f"/api/access/users/{pat.ids['Lee']}", json={"role": "user"}).is_success


def test_choosing_needs_the_password(pat, app):
    """A12: Full or Light, only with the password, never a PIN alone; a
    User has nothing to choose."""
    wrong = pat.put("/api/access/me/sign-in", json={"how": "light", "password": "nope"})
    assert wrong.status_code == 400 and wrong.json()["detail"] == "That password isn't right"
    for how in ("medium", "", "LIGHT"):
        assert (
            pat.put(
                "/api/access/me/sign-in", json={"how": how, "password": PAT["password"]}
            ).status_code
            == 400
        )
    assert pat.get("/api/access/me").json()["user"]["adminSignIn"] == "full"
    sam = browser(app, SAM)
    refused = sam.put("/api/access/me/sign-in", json={"how": "light", "password": SAM["password"]})
    assert refused.status_code == 403
    # From the PIN's own sign-in: with the password, as anywhere.
    light(pat)
    pc = browser(app, PAT)
    assert pin(idle(pc), pat.ids["Pat"], "1234").status_code == 200
    assert (
        pc.put("/api/access/me/sign-in", json={"how": "full", "password": "nope"}).status_code
        == 400
    )
    assert pc.get("/api/access/me").json()["user"]["adminSignIn"] == "light"


def test_back_to_full_ends_the_pins_sign_ins(pat, app):
    """A08: choosing Full ends the sign-ins Pat's PIN made, at once; his
    password's stay."""
    light(pat)
    pc = browser(app, PAT)
    assert pin(idle(pc), pat.ids["Pat"], "1234").status_code == 200
    assert pat.put(
        "/api/access/me/sign-in", json={"how": "full", "password": PAT["password"]}
    ).is_success
    assert pc.get("/api/access/me").json()["user"] is None
    assert pat.get("/api/access/me").json()["user"]["name"] == "Pat"
    assert tiles(pc) == [("Pat", False)]
    assert pin(pc, pat.ids["Pat"], "1234").status_code == 400


def test_a_new_pin_ends_the_old_ones_sign_ins(pat, app):
    """A10: an Admin's PIN changed (on the Access tab, by another Admin):
    the sign-ins the old one made end; the new one works where it did."""
    pc = browser(app, PAT)
    light(pc)
    assert pin(idle(pc), pat.ids["Pat"], "1234").status_code == 200
    lee = browser(app, LEE)
    assert lee.put(f"/api/access/users/{pat.ids['Pat']}/picker", json={"pin": "9876"}).is_success
    assert pc.get("/api/access/me").json()["user"] is None
    assert pin(pc, pat.ids["Pat"], "1234").status_code == 403
    assert pin(pc, pat.ids["Pat"], "9876").status_code == 200


def test_a_new_role_ends_their_sign_ins(pat, app):
    """A09, P15, P18: someone's role changed: every sign-in of theirs ends
    (but the change's own), so a User's PIN or password sign-in never
    becomes an Admin's, nor an Admin's stays one; they sign in again."""
    sam = browser(app, SAM)
    tv = TestClient(app)
    key = tv.post("/api/internal/sign-in", json={**SAM, **TV}).json()["deviceKey"]
    by_pin = tv.post(
        "/api/internal/picker/choose", json={"id": pat.ids["Sam"], "pin": "5555"},
        headers=device(key),
    ).json()["token"]  # fmt: skip
    assert pat.put(f"/api/access/users/{pat.ids['Sam']}", json={"role": "admin"}).is_success
    assert sam.get("/api/access/me").json()["user"] is None
    assert tv.get("/api/internal/me", headers=bearer(by_pin)).status_code == 401
    assert pat.get("/api/access/me").json()["user"]["name"] == "Pat"  # (the change's own)
    log = pat.get("/api/logs?access_log=true").json()["text"]
    assert "Sam is an Admin now: 2 sign-in(s) ended, to sign in again as one" in log
    # An Admin made a User: the same; and off every browser's sign-in screen.
    lee = browser(app, LEE)
    assert pat.put(f"/api/access/users/{pat.ids['Lee']}", json={"role": "user"}).is_success
    assert lee.get("/api/access/me").json()["user"] is None
    assert tiles(lee) == []


# Full and Light in the apps -------------------------------------------------------------


def test_on_an_app_full_makes_the_pin_for_watching(pat, app):
    """A01 in an app: Pat picked with his PIN on a device he signed in on:
    for watching (Admin tasks ask for his password); with his password, an
    Admin's sign-in."""
    tv = TestClient(app)
    key = tv.post("/api/internal/sign-in", json={**PAT, **TV}).json()["deviceKey"]
    by_pin = tv.post(
        "/api/internal/picker/choose", json={"id": pat.ids["Pat"], "pin": "1234"},
        headers=device(key),
    )  # fmt: skip
    assert by_pin.status_code == 200, by_pin.text
    mine = bearer(by_pin.json()["token"])
    said = tv.get("/api/internal/alerts", headers=mine)
    assert said.status_code == 403 and said.json()["detail"] == access.WATCHING_ONLY
    assert tv.get("/api/v1/stations", headers=mine).status_code == 200
    by_password = tv.post(
        "/api/internal/picker/choose", json={"id": pat.ids["Pat"], "password": PAT["password"]},
        headers=device(key),
    )  # fmt: skip
    assert by_password.status_code == 200
    assert (
        tv.get("/api/internal/alerts", headers=bearer(by_password.json()["token"])).status_code
        == 200
    )
    wrong = tv.post(
        "/api/internal/picker/choose", json={"id": pat.ids["Pat"], "password": "nope"},
        headers=device(key),
    )  # fmt: skip
    assert wrong.status_code == 401


def test_on_an_app_light_is_the_pin_where_his_password_signed_in(pat, app):
    """A03, A04, A11 in an app: Light, on a device Pat signed in on with his
    password: his PIN gives his Admin tools there, at home; away from home,
    or on a device he joined with only an invite code, it's for watching."""
    light(pat)
    tv = TestClient(app)
    key = tv.post("/api/internal/sign-in", json={**SAM, **TV}).json()["deviceKey"]
    signed = tv.post("/api/internal/picker/sign-in", json=PAT, headers=device(key))
    assert signed.status_code == 200, signed.text

    def picked(c) -> dict:
        got = c.post(
            "/api/internal/picker/choose", json={"id": pat.ids["Pat"], "pin": "1234"},
            headers=device(key),
        )  # fmt: skip
        assert got.status_code == 200, got.text
        return bearer(got.json()["token"])

    assert tv.get("/api/internal/alerts", headers=picked(tv)).status_code == 200
    away = away_from_home(app)
    assert away.get("/api/internal/alerts", headers=picked(away)).status_code == 403
    # A device he's on only by an invite code: his PIN is for watching there.
    pad = TestClient(app)
    pad_key = pad.post(
        "/api/internal/sign-in", json={**SAM, **TV, "deviceName": "Den tablet"}
    ).json()["deviceKey"]
    code = pat.post(f"/api/access/users/{pat.ids['Pat']}/invite").json()["code"]
    joined = pad.post(
        "/api/internal/picker/sign-in", json={"name": "Pat", "code": code}, headers=device(pad_key)
    )
    assert joined.status_code == 200, joined.text
    by_pin = pad.post(
        "/api/internal/picker/choose", json={"id": pat.ids["Pat"], "pin": "1234"},
        headers=device(pad_key),
    )  # fmt: skip
    assert by_pin.status_code == 200, by_pin.text
    assert (
        pad.get("/api/internal/alerts", headers=bearer(by_pin.json()["token"])).status_code == 403
    )


def test_on_an_app_an_admin_picked_with_nothing_is_for_watching(pat, app):
    """An Admin with no PIN, alone on a device they linked, picked with
    nothing (1.35.0 to 1.37.1: an Admin's sign-in): for watching from 1.38.0,
    as no password or PIN was given."""
    jo = pat.post(
        "/api/access/users",
        json={"name": "Jo", "password": "a plenty long password", "role": "admin"},
    )
    assert jo.status_code == 201
    phone = TestClient(app)
    key = phone.post(
        "/api/internal/sign-in",
        json={"name": "Jo", "password": "a plenty long password", **TV, "deviceName": "Jo's phone"},
    ).json()["deviceKey"]
    picked = phone.post(
        "/api/internal/picker/choose", json={"id": jo.json()["id"]}, headers=device(key)
    )
    assert picked.status_code == 200, picked.text
    said = phone.get("/api/internal/alerts", headers=bearer(picked.json()["token"]))
    assert said.status_code == 403 and said.json()["detail"] == access.WATCHING_ONLY


def test_anyone_elses_password_never_starts_the_wrong_pins_over(pat, app, monkeypatch):
    """(The cold audit of 1.38.0: Sam's own password on the family browser
    started its count of wrong PINs over, so Pat's PIN could be guessed
    there without end, waiting out the five-then-15-minutes limit.) Wrong
    PINs for Pat on a browser are counted until Pat's own password signs in
    there; the tenth needs it."""
    monkeypatch.setattr(devices, "PIN_WAIT_S", 0)  # (the per-person wait, waited out)
    pc = browser(app, PAT)
    light(pc)
    idle(pc)
    said = []
    for _ in range(access.BROWSER_PIN_TRIES):
        assert pc.post("/api/access/sign-in", json=SAM).status_code == 200
        assert pc.post("/api/access/sign-out").status_code == 200
        said.append(pin(pc, pat.ids["Pat"], "0000").json()["detail"])
    assert "wrong PINs on this browser" in said[-1], said[-1]
    assert not any("wrong PINs on this browser" in s for s in said[:-1])
    assert tiles(pc) == [("Pat", False)]
    assert pin(pc, pat.ids["Pat"], "1234").status_code == 400
    # Pat's own password, and his PIN works there again.
    assert pc.post("/api/access/sign-in", json=PAT).status_code == 200
    idle(pc)
    assert pin(pc, pat.ids["Pat"], "1234").status_code == 200


def test_an_apps_pin_sign_in_never_changes_an_admins_pin(pat, app):
    """(The cold audit of 1.38.0.) An Admin picked with their PIN on a
    device, for watching (Full) or with Admin tools (Light), can't change
    that PIN, at home or away: their password is needed for that, as on the
    page (access.STEP_UP)."""
    tv = TestClient(app)
    key = tv.post("/api/internal/sign-in", json={**PAT, **TV}).json()["deviceKey"]
    for how in ("full", "light"):
        if how == "light":
            light(pat)
        for where in (tv, away_from_home(app)):
            got = where.post(
                "/api/internal/picker/choose", json={"id": pat.ids["Pat"], "pin": "1234"},
                headers=device(key),
            )  # fmt: skip
            assert got.status_code == 200, got.text
            for new in ("0000", None):
                r = where.post("/api/internal/pin", json={"pin": new},
                               headers=bearer(got.json()["token"]))  # fmt: skip
                assert r.status_code == 403 and r.json()["detail"] == access.STEP_UP, (how, r.text)
    assert pin(idle(browser(app, PAT)), pat.ids["Pat"], "1234").status_code == 200


def test_a_browser_cookie_from_elsewhere_never_joins_two_browsers(pat, app):
    """(The cold audit of 1.38.0.) Sam's browser's cookie, put in Pat's (a
    page on the same host name can set it, on another port too): Pat's
    password there gives it a new one, so Sam's browser never lists Pat,
    and Pat's PIN never signs in there."""
    sams = browser(app, SAM)
    token = sams.cookies.get(access.DEVICE_COOKIE)
    assert token
    pats = TestClient(app)
    planted = next(c for c in sams.cookies.jar if c.name == access.DEVICE_COOKIE)
    pats.cookies.set(access.DEVICE_COOKIE, token, domain=planted.domain, path=planted.path)
    assert pats.post("/api/access/sign-in", json=PAT).status_code == 200
    light(pats)
    assert pats.cookies.get(access.DEVICE_COOKIE) not in (None, token)
    idle(sams)
    assert tiles(sams) == []
    assert pin(sams, pat.ids["Pat"], "1234").status_code == 400
    # Pat's own browser: his, with his PIN.
    idle(pats)
    assert tiles(pats) == [("Pat", True)]
    assert pin(pats, pat.ids["Pat"], "1234").status_code == 200


def test_a_pins_sign_in_ends_when_light_does_even_mid_way(pat, app):
    """(The cold audit of 1.38.0.) A PIN's sign-in gives Admin tools only
    while its Admin is still in Light with a PIN, checked on every request:
    one made while the Admin switched to Full (a PIN sign-in waits on its
    hash) has none."""
    pc = browser(app, PAT)
    light(pc)
    assert pin(idle(pc), pat.ids["Pat"], "1234").status_code == 200
    # (As if made just after the switch ended the PIN's sign-ins.)
    pat.app.state.ctx.db.set_admin_sign_in(pat.ids["Pat"], access.FULL)
    assert admin_tools(pc) == [403, 403, 403]
    assert pc.get("/api/access/me").json()["user"]["adminTools"] is False


def test_admins_sign_ins_from_before_1_38_are_for_watching(tmp_path):
    """(The cold audit of 1.38.0.) 1.37.1 didn't note which sign-ins a PIN
    made: after the update, each Admin starts on Full, so their sign-ins
    from before are for watching until their password signs in again.
    Users' are kept as they were."""
    path = tmp_path / "old.db"
    old = Database(path)
    pat = old.add_user("Pat", access.hash_password(PAT["password"]), "admin", 1, None, "x")
    sam = old.add_user("Sam", access.hash_password(SAM["password"]), "user", 1, None, "x")
    for name, user in (("pats", pat), ("sams", sam)):
        old._conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_ms, seen_ms) VALUES (?, ?, 1, 1)",
            (name, user.id),
        )
    for column in ("watching", "admin_pin"):
        old._conn.execute(f"ALTER TABLE sessions DROP COLUMN {column}")  # (as before 1.38.0)
    old._conn.commit()
    old.close()
    upgraded = Database(path)
    try:
        assert upgraded.session_user("pats", 0).watching
        assert not upgraded.session_user("sams", 0).watching
    finally:
        upgraded.close()


def test_signing_out_ends_a_pins_sign_in_and_rolled_back_it_signs_in_nowhere(pat, app):
    """A PIN's sign-in is kept as its own kind (as a trusted network's,
    1.36.0): 1.37.1, rolled back to without the copy put back, never finds it
    (it would take it for a password's: the cold audit of 1.38.0). And
    signing out ends it."""
    import hashlib

    pc = browser(app, PAT)
    light(pc)
    assert pin(idle(pc), pat.ids["Pat"], "1234").status_code == 200
    token = pc.cookies.get(access.COOKIE)
    assert token.startswith(access.PIN_TOKEN_PREFIX)
    db = pat.app.state.ctx.db
    assert db.session_user(hashlib.sha256(token.encode()).hexdigest(), 0) is None
    assert pc.post("/api/access/sign-out").status_code == 200
    assert db.session_user(access.session_hash(token), 0) is None
    again = TestClient(app)
    again.cookies.set(access.COOKIE, token)
    assert again.get("/api/access/users").status_code == 401


def test_a_pins_sign_in_never_takes_or_restores_a_backup(pat, app):
    """(The second cold audit of 1.38.0.) A backup holds everyone's password
    hashes and roles: a PIN's sign-in that could download one could crack
    them offline, and one that could restore an edited one could make Sam an
    Admin with a password of its choosing. It can make a backup (that's
    harmless), but downloading or restoring one needs the password. So do
    letting Admin API tokens work from the internet and trusting the
    reverse proxy from the Away from home check: each widens where things
    work."""
    pc = browser(app, PAT)
    light(pc)
    made = pc.post("/api/backups")
    assert made.status_code == 201, made.text
    name = made.json()["name"]
    assert pin(idle(pc), pat.ids["Pat"], "1234").status_code == 200
    assert pc.post("/api/backups").status_code == 201
    for method, path, kw in (
        ("GET", f"/api/backups/{name}", {}),
        ("POST", "/api/restore", {"content": b"PK\x03\x04"}),
        ("PUT", "/api/api-tokens/outside", {"json": {"on": True}}),
        ("POST", "/api/away/trust-proxy", {"json": {"address": "192.168.1.2"}}),
    ):
        said = pc.request(method, path, **kw)
        assert said.status_code == 403 and said.json()["detail"] == access.STEP_UP, (
            path,
            said.text,
        )
    # (With his password, as before.)
    assert pc.post("/api/access/sign-in", json=PAT).status_code == 200
    assert pc.get(f"/api/backups/{name}").status_code == 200


def test_a_pins_sign_in_never_turns_on_watching_away_from_home(pat, app):
    """(The last check of 1.38.0's cold audit.) Turning on watching away from
    home, or changing its address, widens where tapiOca's sign-ins work:
    only with the password. A PIN's sign-in can still turn it off."""
    pc = browser(app, PAT)
    light(pc)
    assert pin(idle(pc), pat.ids["Pat"], "1234").status_code == 200
    said = pc.put("/api/away", json={"on": True, "address": "https://tv.example.com"})
    assert said.status_code == 403 and said.json()["detail"] == access.STEP_UP, said.text
    assert pc.get("/api/away").json()["on"] is False
    assert pat.put("/api/away", json={"on": True, "address": "https://tv.example.com"}).is_success
    moved = pc.put("/api/away", json={"on": True, "address": "https://elsewhere.example.com"})
    assert moved.status_code == 403, moved.text
    assert pc.put("/api/away", json={"on": False, "address": "https://tv.example.com"}).is_success
    assert pc.get("/api/away").json()["on"] is False
