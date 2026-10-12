"""The update check (releases.py, from 1.34.0): once a day, whether a newer
StationPlay is out, from GitHub's list of releases; on to start, an Admin's
setting; what the banner says for each kind of install; and nothing asked,
downloaded or followed beyond that one answer."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import __version__, releases
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex


class GitHub:
    """Stands in for GitHub: answers each request as `answer` says, and
    keeps what it was asked."""

    def __init__(self, status: int = 200, body: object = None, headers: dict | None = None):
        self.status, self.body, self.headers = status, body, headers or {}
        self.asked: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def answer(request: httpx.Request) -> httpx.Response:
            self.asked.append(request)
            return httpx.Response(self.status, json=self.body, headers=self.headers)

        return httpx.MockTransport(answer)


def bump(by: int = 1) -> str:
    major, minor, _patch = releases.as_tuple(__version__)
    return f"{major}.{minor + by}.0"


@pytest.fixture
def made(tmp_path, monkeypatch):
    def make(github: GitHub, install: str = "") -> releases.Releases:
        monkeypatch.setattr(releases.Releases, "transport", github.transport())
        return releases.Releases(Database(tmp_path / "db.sqlite"), install)

    return make


def test_versions_compare_as_numbers():
    assert releases.as_tuple("v1.34.0") == (1, 34, 0)
    assert releases.as_tuple("1.9.10") == (1, 9, 10)
    for bad in ("", "v1.34", "1.34.0-beta", "latest", "v1.34.0.1", "x1.2.3"):
        assert releases.as_tuple(bad) is None, bad
    assert releases.newer("1.10.0", "1.9.9") and not releases.newer("1.9.9", "1.10.0")
    assert not releases.newer("1.34.0", "1.34.0") and not releases.newer("nonsense", "1.0.0")


def test_a_newer_release_is_found_and_said(made):
    version = bump()
    github = GitHub(body={"tag_name": f"v{version}",
                          "html_url": f"{releases.RELEASES}/tag/v{version}"})  # fmt: skip
    check = made(github, "truenas")
    assert check.on  # (on to start)
    seen = asyncio.run(check.check())
    assert (seen.version, seen.problem) == (version, "")
    said = check.as_json()
    assert said["latest"] == {"version": version, "url": f"{releases.RELEASES}/tag/v{version}"}
    assert said["current"] == __version__ and said["install"] == "TrueNAS"
    # One request: GitHub's latest release, saying who's asking, and nothing else.
    [asked] = github.asked
    assert str(asked.url) == releases.LATEST and asked.method == "GET"
    assert asked.headers["user-agent"] == f"StationPlay/{__version__}"
    assert not asked.content


def test_nothing_newer_is_nothing_to_say(made):
    check = made(GitHub(body={"tag_name": f"v{__version__}", "html_url": releases.RELEASES}))
    asyncio.run(check.check())
    assert check.as_json()["latest"] is None


def test_only_stationplay_s_own_release_page_is_linked(made):
    version = bump()
    check = made(GitHub(body={"tag_name": f"v{version}", "html_url": "https://elsewhere.test/x"}))
    asyncio.run(check.check())
    assert check.as_json()["latest"]["url"] == f"{releases.RELEASES}/tag/v{version}"


@pytest.mark.parametrize(
    ("github", "problem"),
    [
        (GitHub(status=404, body={"message": "Not Found"}), "GitHub answered 404"),
        (
            GitHub(status=301, headers={"Location": "https://elsewhere.test/"}),
            "GitHub answered 301",
        ),
        (GitHub(body={"tag_name": "nightly"}), "GitHub's answer named no version"),
        (GitHub(body=["not", "a", "release"]), "GitHub's answer named no version"),
    ],
)
def test_a_look_that_fails_keeps_what_was_known(made, github, problem):
    version = bump()
    check = made(GitHub(body={"tag_name": f"v{version}", "html_url": releases.RELEASES}))
    asyncio.run(check.check())
    check.transport = github.transport()
    seen = asyncio.run(check.check())
    assert seen.problem == problem and seen.version == version
    assert len(github.asked) == 1  # (no redirect followed)
    assert check.as_json()["latest"]["version"] == version


def test_github_out_of_reach(made):
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    check = made(GitHub())
    check.transport = httpx.MockTransport(unreachable)
    seen = asyncio.run(check.check())
    assert seen.problem == "GitHub couldn't be reached" and seen.version == ""


def test_turned_off_it_asks_nothing_and_says_nothing(made, monkeypatch):
    version = bump()
    github = GitHub(body={"tag_name": f"v{version}", "html_url": releases.RELEASES})
    check = made(github)
    asyncio.run(check.check())
    check.save(False)
    assert check.as_json()["latest"] is None
    # (The daily look, run a while: nothing asked while it's off.)
    monkeypatch.setattr(releases, "FIRST_S", 0)
    monkeypatch.setattr(releases, "EVERY_S", 0.01)

    async def a_while():
        task = asyncio.create_task(check.run_forever())
        await asyncio.sleep(0.1)
        task.cancel()

    asyncio.run(a_while())
    assert len(github.asked) == 1
    # Kept: off after a restart too.
    assert releases.Releases(check.db).on is False
    assert json.loads(check.db.get_meta(releases.META, "")) == {"on": False}


def test_each_kind_of_install_has_its_steps():
    for install in ("truenas", "compose", "docker-desktop", "unraid", "synology", "docker-run"):
        said = releases.steps(install)
        assert said["install"] and said["steps"], install
    assert releases.steps("compose")["command"] == "docker compose pull && docker compose up -d"
    assert releases.steps("docker-run")["command"].startswith(
        "docker pull ghcr.io/egadgetboy/stationplay:latest"
    )
    unknown = releases.steps("something else")
    assert unknown["install"] == "" and "README" in unknown["steps"][0]
    assert unknown["readme"] == releases.README


def test_the_page_s_addresses_are_admins_only(tmp_path, monkeypatch):
    version = bump()
    github = GitHub(body={"tag_name": f"v{version}", "html_url": releases.RELEASES})
    monkeypatch.setattr(releases.Releases, "transport", github.transport())
    monkeypatch.setenv("STATIONPLAY_INSTALL", "Compose")
    settings = Settings.from_env()
    settings.plex_url, settings.plex_token, settings.data_dir = (
        "http://plex.test", "token", tmp_path / "data",
    )  # fmt: skip
    app = create_app(settings, PlexClient("http://plex.test", "token",
                                          transport=FakePlex().transport()))  # fmt: skip
    with TestClient(app) as admin:
        said = admin.get("/api/updates").json()
        assert said["on"] is True and said["install"] == "Docker Compose"
        assert said["latest"] is None
        checked = admin.post("/api/updates/check").json()
        assert checked["latest"]["version"] == version
        assert admin.put("/api/updates", json={"on": False}).json()["on"] is False
        refused = admin.post("/api/updates/check")
        assert refused.status_code == 400 and "Turn on the update check" in refused.json()["detail"]
        assert admin.put("/api/updates", json={"on": "yes"}).status_code == 422
        assert admin.post("/api/access/users", json={"name": "Pat", "password": "correct horse"})
        assert admin.post("/api/access/users", json={"name": "Sam", "password": "battery staple",
                                                     "role": "user"}).status_code == 201  # fmt: skip
        sam = TestClient(app)
        assert sam.post("/api/access/sign-in", json={"name": "Sam", "password": "battery staple"})
        assert sam.get("/api/updates").status_code == 403
        assert sam.post("/api/updates/check").status_code == 403
