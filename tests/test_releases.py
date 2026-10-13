"""The update check (releases.py, from 1.34.0): every 4 hours (once a day
before 1.34.1), whether a newer
tapiOca is out, from GitHub's list of releases; an Admin's setting;
what the banner says for each kind of install; and nothing asked,
downloaded or followed beyond that one answer.

The audit of 1.34.0: nothing is asked of GitHub until an Admin answers
whether to (new servers in setup's last step, updated ones in a question
on the page) and setup is done; GitHub is asked by the repository's
number, which a rename doesn't change; the page says what went wrong in
plain words, the status only in the log; no install's steps need &&,
which PowerShell hasn't got; and the first start after an update says so
in the log, once."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

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
    """The update check, with GitHub standing in, answered Yes and set up
    (as an Admin chose: see test_nothing_is_asked_until_an_admin_answers)."""

    def make(github: GitHub, install: str = "") -> releases.Releases:
        monkeypatch.setattr(releases.Releases, "transport", github.transport())
        check = releases.Releases(Database(tmp_path / "db.sqlite"), install)
        check.save(True)
        return check

    return make


async def a_while(check: releases.Releases, seconds: float = 0.1) -> None:
    """The daily look, run a while (with no waiting)."""
    task = asyncio.create_task(check.run_forever())
    await asyncio.sleep(seconds)
    task.cancel()


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
    assert check.on is True
    seen = asyncio.run(check.check())
    assert (seen.version, seen.problem) == (version, "")
    said = check.as_json()
    assert said["latest"] == {"version": version, "url": f"{releases.RELEASES}/tag/v{version}"}
    assert said["current"] == __version__ and said["install"] == "TrueNAS"
    # One request: GitHub's latest release, saying who's asking, and nothing else.
    [asked] = github.asked
    assert str(asked.url) == releases.LATEST and asked.method == "GET"
    assert asked.headers["user-agent"] == f"tapiOca/{__version__}"
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
    ("github", "problem", "logged"),
    [
        (GitHub(status=404, body={"message": "Not Found"}),
         "GitHub couldn't find tapiOca's releases", "GitHub answered 404"),
        (GitHub(status=403, body={"message": "rate limit"}),
         "GitHub asked tapiOca to wait, so it will look again later", "GitHub answered 403"),
        (GitHub(status=429), "GitHub asked tapiOca to wait, so it will look again later",
         "GitHub answered 429"),
        (GitHub(status=301, headers={"Location": "https://elsewhere.test/"}),
         "GitHub pointed somewhere else, which tapiOca doesn't follow",
         "GitHub answered 301"),
        (GitHub(status=503), "GitHub couldn't answer just then", "GitHub answered 503"),
        (GitHub(body={"tag_name": "nightly"}), "GitHub's answer named no version",
         "GitHub's answer named no version"),
        (GitHub(body=["not", "a", "release"]), "GitHub's answer named no version",
         "GitHub's answer named no version"),
    ],
)  # fmt: skip
def test_a_look_that_fails_keeps_what_was_known(made, github, problem, logged, caplog):
    caplog.set_level(logging.INFO, logger="app.releases")
    version = bump()
    check = made(GitHub(body={"tag_name": f"v{version}", "html_url": releases.RELEASES}))
    asyncio.run(check.check())
    check.transport = github.transport()
    seen = asyncio.run(check.check())
    assert seen.problem == problem and seen.version == version
    assert len(github.asked) == 1  # (no redirect followed)
    assert check.as_json()["latest"]["version"] == version
    # The page says it in words; the status is only in the log.
    assert not any(c.isdigit() for c in check.as_json()["checked"]["problem"])
    assert logged in caplog.text


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
    asyncio.run(a_while(check))
    assert len(github.asked) == 1
    # Kept: off after a restart too.
    assert releases.Releases(check.db).on is False
    assert json.loads(check.db.get_meta(releases.META, "")) == {"on": False}


def test_each_kind_of_install_has_its_steps():
    for install in ("truenas", "compose", "docker-desktop", "unraid", "synology", "docker-run"):
        said = releases.steps(install)
        assert said["install"] and said["steps"], install
        assert said["heading"].startswith("To update ") and said["heading"].endswith(":")
        # One command, with no && (PowerShell, in Docker Desktop on
        # Windows, hasn't got it), that fetches the newest image itself:
        # starting tapiOca never needs the internet.
        assert "&&" not in (said["command"] or ""), install
    for install in ("compose", "docker-desktop"):
        assert releases.steps(install)["command"] == "docker compose up -d --pull always"
    assert releases.steps("docker-run")["command"] == (
        "docker pull ghcr.io/egadgetboy/tapioca-server:latest"
    )
    assert releases.steps("docker-run")["heading"] == "To update with docker run:"
    assert releases.steps("synology")["command"] == "sudo docker compose up -d --pull always"
    assert releases.steps("truenas")["command"] == (
        "sudo docker pull ghcr.io/egadgetboy/tapioca-server:latest"
    )
    # Steps no one has confirmed yet say so, in plain words.
    for install in ("truenas", "synology"):
        assert "haven't been confirmed yet" in " ".join(releases.steps(install)["steps"]), install
    for install in ("compose", "docker-desktop", "unraid", "docker-run"):
        assert "confirmed" not in " ".join(releases.steps(install)["steps"]), install
    # Each names what the screen shows: the TrueNAS app and the Synology
    # project are named stationplay (TrueNAS app names are lowercase only),
    # and so is the container on Unraid's Docker tab (the audit of 1.34.0).
    truenas = " ".join(releases.steps("truenas")["steps"])
    assert "open Apps, then stationplay." in truenas
    assert "choose stationplay, and choose Edit" in truenas
    assert "choose the stationplay project" in " ".join(releases.steps("synology")["steps"])
    assert "When stationplay shows an update" in " ".join(releases.steps("unraid")["steps"])
    for install in ("truenas", "synology", "unraid"):
        said = " ".join(releases.steps(install)["steps"])
        assert "then tapiOca" not in said and "choose tapiOca" not in said, install
        assert "When tapiOca shows" not in said, install
    unknown = releases.steps("something else")
    assert unknown["install"] == "" and "README" in unknown["steps"][0]
    assert unknown["readme"] == releases.README
    assert unknown["heading"] == "To update:"


def test_github_is_asked_by_the_repository_s_number(made):
    """(A rename or move of the repository answers 301 at its old name,
    which isn't followed: its number stays.)"""
    assert releases.REPOSITORY_ID == 1414995565  # (gh api repos/egadgetboy/tapioca-server --jq .id)
    assert releases.LATEST == "https://api.github.com/repositories/1414995565/releases/latest"
    github = GitHub(body={"tag_name": f"v{bump()}", "html_url": releases.RELEASES})
    asyncio.run(made(github).check())
    [asked] = github.asked
    assert str(asked.url) == releases.LATEST


def test_nothing_is_asked_until_an_admin_answers(tmp_path, monkeypatch):
    """New and updated servers alike (1.33.1 had no update check): nothing
    asked until an Admin says yes, and setup is done."""
    version = bump()
    github = GitHub(body={"tag_name": f"v{version}", "html_url": releases.RELEASES})
    monkeypatch.setattr(releases.Releases, "transport", github.transport())
    monkeypatch.setattr(releases, "FIRST_S", 0)
    monkeypatch.setattr(releases, "EVERY_S", 0.01)
    monkeypatch.setattr(releases, "AGAIN_S", 0.01)
    monkeypatch.setattr(releases, "WAITING_S", 0.01)
    db = Database(tmp_path / "db.sqlite")
    set_up = [False]
    check = releases.Releases(db, "compose", set_up=lambda: set_up[0])
    said = check.as_json()
    assert (said["on"], said["ask"], said["latest"]) == (None, False, None)
    asyncio.run(a_while(check))
    assert not github.asked
    # Setup done, not answered yet: asked on the page, still nothing asked of GitHub.
    set_up[0] = True
    assert check.as_json()["ask"] is True
    asyncio.run(a_while(check))
    assert not github.asked
    with pytest.raises(releases.NotAsked):
        asyncio.run(check.check_now())
    # Yes, but setup isn't done (an update brought a question): still nothing.
    check.save(True)
    set_up[0] = False
    assert check.as_json()["ask"] is False
    asyncio.run(a_while(check))
    assert not github.asked
    with pytest.raises(releases.NotAsked):
        asyncio.run(check.check_now())
    # Done: it looks.
    set_up[0] = True
    asyncio.run(a_while(check))
    assert github.asked and check.as_json()["latest"]["version"] == version
    # Kept: answered after a restart too.
    assert releases.Releases(db).on is True


def test_check_now_is_at_most_once_a_minute(made):
    version = bump()
    github = GitHub(body={"tag_name": f"v{version}", "html_url": releases.RELEASES})
    check = made(github)
    asyncio.run(check.check_now())
    asyncio.run(check.check_now())
    assert len(github.asked) == 1  # (the second within the minute: what the first found)
    check._last_asked -= releases.SOONEST_S  # (a minute later)
    asyncio.run(check.check_now())
    assert len(github.asked) == 2


def test_an_update_is_said_once_in_the_log(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="app.releases")
    db = Database(tmp_path / "db.sqlite")
    # A new server: nothing to say.
    releases.note_version(db, fresh=True)
    assert "Updated" not in caplog.text
    db.set_meta(releases.VERSION_META, "1.33.9")
    releases.note_version(db, fresh=False)
    releases.note_version(db, fresh=False)
    assert caplog.text.count(f"Updated from 1.33.9 to {__version__}") == 1
    assert db.get_meta(releases.VERSION_META) == __version__
    # From before 1.34.0, which kept no version: said too, once.
    caplog.clear()
    other = Database(tmp_path / "other.sqlite")
    releases.note_version(other, fresh=False)
    releases.note_version(other, fresh=False)
    assert caplog.text.count(f"Updated to {__version__} from an earlier version") == 1


def test_the_page_s_addresses_are_admins_only(tmp_path, monkeypatch):
    version = bump()
    github = GitHub(body={"tag_name": f"v{version}", "html_url": releases.RELEASES})
    monkeypatch.setattr(releases.Releases, "transport", github.transport())
    monkeypatch.setenv("TAPIOCA_INSTALL", "Compose")
    settings = Settings.from_env()
    settings.plex_url, settings.plex_token, settings.data_dir = (
        "http://plex.test", "token", tmp_path / "data",
    )  # fmt: skip
    app = create_app(settings, PlexClient("http://plex.test", "token",
                                          transport=FakePlex().transport()))  # fmt: skip
    with TestClient(app) as admin:
        said = admin.get("/api/updates").json()
        assert said["on"] is None and said["install"] == "Docker Compose"
        assert said["latest"] is None and said["ask"] is False  # (setup isn't done)
        refused = admin.post("/api/updates/check")
        assert refused.status_code == 400 and not github.asked
        setup = admin.get("/api/setup").json()
        admin.put("/api/setup", json={"answered": setup["questions"]})
        assert admin.get("/api/updates").json()["ask"] is True
        answered = admin.put("/api/updates", json={"on": True}).json()
        assert answered["on"] is True and answered["ask"] is False
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


UPDATES_JS = Path(__file__).parent.parent / "app" / "web" / "js" / "updates.js"


def test_not_now_hides_the_banner_for_that_version_only():
    """(The page tool shows it, too: Not now hides the banner, and a newer
    version brings it back.) Not now keeps the version it was chosen for, in
    this browser, and the banner stays hidden only while that's the newest."""
    page = UPDATES_JS.read_text(encoding="utf-8")
    # (New in 1.34.0, so under tapiOca's own name: the audit of 1.34.0.)
    assert "const UPDATE_NOT_NOW = 'tapioca.updateNotNow';" in page
    assert "localStorage.setItem(UPDATE_NOT_NOW, u.latest.version)" in page
    assert (
        "if (!u.latest || notNowFor() === u.latest.version) { banner.hidden = true; return; }"
        in page
    )
    # The question comes before any banner, and only when the server asks it.
    assert page.index("if (u.ask) {") < page.index("notNowFor() === u.latest.version")
    # Nothing's ticked until an Admin says yes.
    assert "checked: u.on === true" in page


def test_the_update_check_looks_every_four_hours():
    """(1.34.1, the owner) Every 4 hours, as it costs next to nothing: one
    small request to GitHub's public API, well inside what GitHub allows
    an address without an account (60 an hour)."""
    assert releases.EVERY_S == 4 * 3600
    page = Path(__file__).resolve().parent.parent / "app" / "web" / "js" / "updates.js"
    assert "Every 4 hours, tapiOca asks GitHub" in page.read_text(encoding="utf-8")
