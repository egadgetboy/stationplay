"""Changes only from tapiOca's own page (1.36.2): the custom request header
every request from the page carries (X-Tapioca-Page, see access.PAGE_HEADER
and core.js's api), the standard defense against another site's page (or
another app's on the same NAS) asking a browser at home to change tapiOca.

Until 1.36.2 the page's addresses relied on Sec-Fetch-Site alone, which
browsers send only over HTTPS (or to localhost): at home, over plain http,
a form on another site could make changes, with signing in off or with an
Admin signed in. A page elsewhere can't send a header of its own to
tapiOca: a form can't, and fetch needs tapiOca's leave, which it never
gives. The owner, October 14: "industry-standard, commercial way".

The tests' own clients send the header as the page does (see conftest.py
and helpers.PAGE); these send their own, or none."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import access
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

HOME = "http://192.168.1.20:3310"
ME = ("192.168.1.50", 50000)
PAT = {"name": "Pat", "password": "correct horse"}
STATION = {"number": 7, "sources": [{"type": "show", "ratingKey": "100"}]}
WEB = Path(__file__).resolve().parents[1] / "app" / "web"


@pytest.fixture
def app(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/tv/s/1.mkv", 22 * 60_000)
    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
        port=3310, public_port=3311,
    )  # fmt: skip
    made = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    with TestClient(made, base_url=HOME, client=ME):
        yield made


def without(app, client: tuple[str, int] = ME, **headers: str) -> TestClient:
    """A browser at home sending no page header: another site's page, or a
    form (with `headers`, such as its Origin). Or an app or a script."""
    named = {k.replace("_", "-"): v for k, v in headers.items()}
    c = TestClient(app, base_url=HOME, client=client, headers=named or None)
    c.headers.pop("X-Tapioca-Page", None)  # (the tests' clients send it: see conftest.py)
    return c


def refused(r) -> bool:
    return r.status_code == 403 and r.json()["detail"] == access.FROM_ITS_PAGE


def test_with_signing_in_off_a_change_needs_the_pages_header(app):
    """Signing in off: everyone at home may change anything, so this header
    is all that tells the page from another site's (over plain http)."""
    other = without(app, origin="http://evil.example")
    assert refused(other.post("/api/channels", json=STATION))
    # A plain form: no JSON, no header.
    form = other.post("/api/channels", data={"number": "7"})
    assert refused(form)
    assert refused(other.put("/api/away", json={"on": True, "address": "https://x.example"}))
    assert refused(other.delete("/api/channels/1"))
    # With no Origin at all (a form posted from a file, or a privacy
    # setting): the same.
    assert refused(without(app).post("/api/channels", json=STATION))
    # Reading is unchanged (a page elsewhere can't read the answer).
    assert without(app).get("/api/channels").status_code == 200
    # Nothing was made; the page itself (its header) makes it.
    assert TestClient(app, base_url=HOME, client=ME).get("/api/channels").json() == []
    page = TestClient(app, base_url=HOME, client=ME, headers={"X-Tapioca-Page": "1"})
    made = page.post("/api/channels", json=STATION)
    assert made.status_code == 201, made.text
    # (Only "1": what the page sends.)
    for said in ("", "yes", "0"):
        assert refused(without(app, x_tapioca_page=said).post("/api/channels", json=STATION))


def test_with_an_admin_signed_in_their_cookie_alone_changes_nothing(app):
    page = TestClient(app, base_url=HOME, client=ME, headers={"X-Tapioca-Page": "1"})
    assert page.post("/api/access/users", json=PAT).status_code == 201
    cookies = dict(page.cookies)
    other = without(app, origin="http://evil.example")
    other.cookies.update(cookies)
    assert other.get("/api/access/me").json()["user"]["name"] == "Pat"  # (signed in)
    for r in (
        other.post("/api/channels", json=STATION),
        other.post("/api/access/users", json={"name": "Eve", "password": "a plenty long password"}),
        other.post("/api/access/sign-out"),
        other.delete("/api/access/users/1"),
    ):
        assert refused(r), r.text
    assert page.get("/api/access/me").json()["user"]["name"] == "Pat"  # (not signed out)
    assert [u["name"] for u in page.get("/api/access/users").json()] == ["Pat"]
    # Signing in from another site's page: refused too.
    assert refused(without(app).post("/api/access/sign-in", json=PAT))


def test_tokens_apps_scripts_and_players_dont_send_it(app):
    """API tokens, tapiOca's apps, scripts and players have their own ways
    in, and send no Origin: nothing changes for them."""
    page = TestClient(app, base_url=HOME, client=ME, headers={"X-Tapioca-Page": "1"})
    # Signing in off: a script, with no token and no header.
    script = without(app, ("192.168.1.60", 5))
    assert script.post("/api/v1/guide/refresh").status_code != 403
    assert script.post("/api/v1/backups").status_code == 201
    # A player leaving a station, Plex asking for a scan: not under /api/.
    assert script.post("/hls/99/leave").status_code == 204
    assert page.post("/api/access/users", json=PAT).status_code == 201
    # An app signing in, and asking with its token.
    app_ = without(app, ("192.168.1.61", 5))
    signed = app_.post("/api/internal/sign-in", json={**PAT, "app": "tapiOca for Roku"})
    assert signed.status_code == 200, signed.text
    token = {"Authorization": f"Bearer {signed.json()['token']}"}
    assert app_.post("/api/internal/sign-out", headers=token).status_code < 400
    # An API token, at the API.
    made = page.post("/api/api-tokens", json={"name": "Script", "scope": "admin", "days": None})
    api = {"Authorization": f"Bearer {made.json()['token']}"}
    assert script.post("/api/v1/backups", headers=api).status_code == 201
    # (A token at the page's addresses is refused, as ever: but not for this.)
    assert not refused(script.post("/api/channels", json=STATION, headers=api))


def test_a_browser_at_the_apps_and_apis_addresses_needs_it_too(app):
    """With signing in off, the API and the apps' sign-in need no token at
    home: a page elsewhere could ask for those as well. A browser always
    says where it's from (Origin) when it sends a change, and apps and
    scripts never do, so what a browser sends there needs the header too."""
    other = without(app, origin="http://evil.example")
    assert refused(other.post("/api/v1/backups"))
    assert refused(other.post("/api/internal/sign-in", json={**PAT, "app": "x"}))
    # (Even naming tapiOca itself: tapiOca's page sends the header.)
    same = without(app, origin=HOME)
    assert refused(same.post("/api/v1/backups"))
    # tapiOca's page, testing the connection: it sends it.
    page = TestClient(
        app, base_url=HOME, client=ME, headers={"X-Tapioca-Page": "1", "Origin": HOME}
    )
    assert not refused(page.post("/api/internal/speed-test", json={"mbps": 50, "app": "page"}))
    # Over HTTPS, a browser says another site's page sent it: refused, as before.
    cross = TestClient(app, base_url=HOME, client=ME,
                       headers={"X-Tapioca-Page": "1", "Sec-Fetch-Site": "cross-site"})  # fmt: skip
    assert refused(cross.post("/api/channels", json=STATION))


def test_tapiocas_own_page_sends_it_with_every_change():
    """Every request the page makes goes through api() (core.js), which
    sends the header, or names it itself."""
    core = (WEB / "js" / "core.js").read_text(encoding="utf-8")
    api = core[core.index("async function api(") :]
    api = api[: api.index("\n}\n")]
    assert "headers: { 'X-Tapioca-Page': '1'" in api
    assert "...opts,\n    headers:" in api  # (a caller's own headers are added to it)
    for path in sorted((WEB / "js").glob("*.js")):
        code = path.read_text(encoding="utf-8")
        for call in re.finditer(r"\bfetch\((.*)", code):
            line = call.group(1)
            if path.name == "core.js" and line.startswith("path,"):
                continue  # (api() itself)
            if "method:" in line:
                assert "'X-Tapioca-Page': '1'" in line, f"{path.name}: {line}"
    html = (WEB / "index.html").read_text(encoding="utf-8")
    # (No form posts itself: a dialog's form only closes it.)
    assert re.findall(r"<form[^>]*\bmethod=\"?(\w+)", html, re.I) == ["dialog"]
    assert not re.search(r"<form[^>]*\baction=", html, re.I)
