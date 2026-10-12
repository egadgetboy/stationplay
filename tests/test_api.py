"""StationPlay's API (/api/v1, see api.py): its tokens, what each may do and
from where, its OpenAPI spec (against docs/openapi-v1.json and docs/api.md),
and the headers on addresses on their way out. (Each address, field by
field: test_app_api.py.)"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import access, api
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_PORT = 8443
PAT = {"name": "Pat", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple"}
DAY_MS = 86_400_000


@pytest.fixture
def app(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * 60_000)
    settings = Settings(
        plex_url="http://plex.test",
        plex_token="token",
        data_dir=tmp_path / "data",
        public_port=PUBLIC_PORT,
    )
    return create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make(page: TestClient, name: str, scope: str, days: int | None = None) -> str:
    made = page.post("/api/api-tokens", json={"name": name, "scope": scope, "days": days})
    assert made.status_code == 201, made.text
    return made.json()["token"]


def test_api_tokens_read_or_do_as_their_scope_says(app):
    with TestClient(app) as page:
        # While signing in is off, the API needs no token, and there are none.
        assert page.get("/api/v1/status").status_code == 200
        refused = page.post("/api/api-tokens", json={"name": "Script", "scope": "viewer"})
        assert refused.status_code == 400 and "first user" in refused.json()["detail"]

        assert page.post("/api/access/users", json=PAT).status_code == 201  # (signed in)
        assert page.post("/api/channels", json={"number": 4, "sources": [
            {"type": "show", "ratingKey": "100"}]}).status_code == 201  # fmt: skip
        viewer, admin = make(page, "Wall clock", "viewer"), make(page, "Home Assistant", "admin")
        assert viewer.startswith("spk_") and len(viewer) == 4 + 43
        listed = page.get("/api/api-tokens").json()
        assert [(t["name"], t["scope"], t["by"]) for t in listed["tokens"]] == [
            ("Home Assistant", "admin", "Pat"), ("Wall clock", "viewer", "Pat")
        ]  # fmt: skip
        assert listed["tokens"][0]["usedMs"] is None and not listed["outside"]
        assert viewer not in json.dumps(listed)  # (shown once, when it's made)
        for wrong in ({"name": " ", "scope": "viewer"}, {"name": "x", "scope": "root"}):
            assert page.post("/api/api-tokens", json=wrong).status_code == 400

        script = TestClient(app)  # (no cookies)
        assert script.get("/api/v1/stations").status_code == 401
        assert script.get("/api/v1/stations", headers=bearer(viewer)).status_code == 200
        assert script.get("/api/v1/status", headers=bearer(viewer)).status_code == 200
        assert page.get("/api/api-tokens").json()["tokens"][1]["usedMs"] > 0
        # A Viewer token only reads, and only Users' reading.
        read_only = script.post("/api/v1/backups", headers=bearer(viewer))
        assert (
            read_only.status_code == 403 and read_only.json()["detail"] == access.TOKEN_READS_ONLY
        )
        assert page.get("/api/v1/stations/4/check", headers=bearer(viewer)).status_code == 403
        # Tokens are for the API alone: not the page, nor the apps' own addresses.
        for path in ("/api/channels", "/api/logs", "/api/api-tokens", "/api/internal/home"):
            elsewhere = script.get(path, headers=bearer(admin))
            assert elsewhere.status_code == 403, path
            assert elsewhere.json()["detail"] == access.TOKEN_API_ONLY
        assert page.post("/api/v1/backups", headers=bearer(admin)).status_code == 201
        assert page.post("/api/v1/stations/4/update", headers=bearer(admin)).status_code == 200
        # One that isn't valid is refused, but not where nothing's needed.
        bad = script.get("/api/v1/stations", headers=bearer("spk_" + "x" * 43))
        assert bad.status_code == 401 and bad.json()["detail"] == access.BAD_TOKEN
        assert script.get("/api/v1/server", headers=bearer("spk_nope")).status_code == 200

        # Revoked: refused at once, and gone from the list.
        [ha] = [t for t in page.get("/api/api-tokens").json()["tokens"] if t["scope"] == "admin"]
        assert page.delete(f"/api/api-tokens/{ha['id']}").status_code == 204
        assert page.delete(f"/api/api-tokens/{ha['id']}").status_code == 404
        assert script.get("/api/v1/status", headers=bearer(admin)).status_code == 401
        log = page.get("/api/logs?access_log=true").json()["text"]
        assert "Pat made the API token “Home Assistant” (Admin)" in log
        assert "Pat revoked the API token “Home Assistant”" in log


def test_api_tokens_expire_and_go_with_the_admin_who_made_them(app, monkeypatch):
    with TestClient(app) as page:
        assert page.post("/api/access/users", json=PAT).status_code == 201
        made = page.post("/api/access/users", json={**SAM, "role": "admin"})
        assert made.status_code == 201
        sam_id = made.json()["id"]
        sam = TestClient(app)
        assert sam.post("/api/access/sign-in", json=SAM).status_code == 200
        sams = make(sam, "Sam's script", "admin")
        brief = make(page, "Brief", "viewer", days=1)
        script = TestClient(app)
        assert script.post("/api/v1/backups", headers=bearer(sams)).status_code == 201

        # Sam made a User: the token reads, but does no more than Sam may now.
        changed = page.put(f"/api/access/users/{sam_id}", json={"role": "user"})
        assert changed.status_code == 200, changed.text
        assert script.get("/api/v1/status", headers=bearer(sams)).status_code == 200
        demoted = script.post("/api/v1/backups", headers=bearer(sams))
        assert demoted.status_code == 403 and demoted.json()["detail"] == access.ADMINS_ONLY
        # Users don't manage tokens.
        assert sam.get("/api/api-tokens").status_code == 403
        # Sam removed: Sam's token goes too.
        assert page.delete(f"/api/access/users/{sam_id}").status_code == 204
        assert script.get("/api/v1/status", headers=bearer(sams)).status_code == 401
        assert [t["name"] for t in page.get("/api/api-tokens").json()["tokens"]] == ["Brief"]

        # A day later, the day-long one has expired.
        assert script.get("/api/v1/status", headers=bearer(brief)).status_code == 200
        later = access._now() + DAY_MS + 1
        monkeypatch.setattr(access, "_now", lambda: later)
        assert script.get("/api/v1/status", headers=bearer(brief)).status_code == 401


def test_api_tokens_from_the_internet_only_once_allowed_and_over_https(app):
    with TestClient(app) as page:
        assert page.post("/api/access/users", json=PAT).status_code == 201
        assert page.post("/api/channels", json={"number": 4, "sources": [
            {"type": "show", "ratingKey": "100"}]}).status_code == 201  # fmt: skip
        token = bearer(make(page, "Away", "viewer"))
        internet = TestClient(
            app, base_url=f"http://testserver:{PUBLIC_PORT}", headers={"X-Forwarded-Proto": "https"}
        )
        refused = internet.get("/api/v1/stations", headers=token)
        assert refused.status_code == 403 and refused.json()["detail"] == access.TOKEN_NOT_OUTSIDE
        allowed = page.put("/api/api-tokens/outside", json={"on": True})
        assert allowed.status_code == 200 and allowed.json()["outside"]
        assert internet.get("/api/v1/stations", headers=token).status_code == 200
        plain_http = TestClient(app, base_url=f"http://testserver:{PUBLIC_PORT}")
        assert plain_http.get("/api/v1/stations", headers=token).status_code == 403
        # Watching away from home on: the stream addresses are the token's own.
        on = page.put("/api/away", json={"on": True, "address": "https://tv.example.com"})
        assert on.status_code == 200, on.text
        [four] = internet.get("/api/v1/stations", headers=token).json()["stations"]
        assert re.fullmatch(r"/hls/k/[^/]+/4/index\.m3u8", four["hls"]), four["hls"]
        log = page.get("/api/logs?access_log=true").json()["text"]
        assert "Pat allowed API tokens from the internet" in log
        assert page.put("/api/api-tokens/outside", json={"on": False}).json()["outside"] is False
        assert internet.get("/api/v1/stations", headers=token).status_code == 403


def test_the_openapi_spec_matches_the_server_and_its_document(app):
    """docs/openapi-v1.json is the server's spec (tools/openapi_spec.py writes
    it), and each answer's fields are the ones docs/api.md lists."""
    sys.path.insert(0, str(ROOT / "tools"))
    import openapi_spec

    spec = api.spec(app)
    committed = json.loads((ROOT / "docs" / "openapi-v1.json").read_text())
    assert spec == committed, "docs/openapi-v1.json is out of date: run tools/openapi_spec.py"
    with TestClient(app) as client:
        assert client.get(api.SPEC_PATH).json() == spec
    assert json.loads(openapi_spec.written()) == spec

    from .test_app_api import API_DOC, documented

    tables = documented(API_DOC)
    schemas = spec["components"]["schemas"]
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            name = f"{method.upper()} {path}"
            [answer] = [a for code, a in operation["responses"].items() if code < "300"]
            ref = answer["content"]["application/json"]["schema"]["$ref"]
            fields = set(schemas[ref.rsplit("/", 1)[1]]["properties"])
            top = {f for f in tables[name] if "." not in f and "[]" not in f}
            assert fields == top, name
            assert operation["operationId"] and operation["summary"], name
    program = set(schemas["Program"]["properties"])
    assert program == set(tables["A program"])
    assert spec["paths"]["/api/v1/server"]["get"]["security"] == []


def test_addresses_on_their_way_out_say_so(app, monkeypatch):
    with TestClient(app) as client:
        assert "deprecation" not in client.get("/api/v1/guide").headers
        sunset = "Sat, 01 May 2027 00:00:00 GMT"
        monkeypatch.setattr(api, "DEPRECATED", {"/api/v1/guide": (sunset, "https://x.test/v2")})
        going = client.get("/api/v1/guide")
        assert going.status_code == 200
        assert going.headers["deprecation"] == "true" and going.headers["sunset"] == sunset
        assert going.headers["link"] == '<https://x.test/v2>; rel="deprecation"'
        assert "deprecation" not in client.get("/api/v1/stations").headers
