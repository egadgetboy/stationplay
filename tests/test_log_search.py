"""Searching the log (1.37.0, the owner, October 15: "There is no SEARCH field
in Logs - needs one"): GET /api/logs?q= finds the entries with those words,
anywhere in what's kept (not only the newest 200), at the levels asked, and
in the access log too."""

from __future__ import annotations

import logging
import uuid

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex


def make(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
            PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
        )
    )


def test_the_log_is_searched_through_all_it_keeps(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    tag = uuid.uuid4().hex[:8]  # (the log is the whole process's: these lines are this test's)
    said = logging.getLogger("app.search_test")
    with make(tmp_path) as c:
        said.info("Pat started Jaws %s", tag)
        for n in range(300):  # (more than a page of the newest, after it)
            said.info("Something else %d", n)
        said.warning("JAWS stopped %s with a problem", tag)
        found = c.get(f"/api/logs?q={tag}").json()["entries"]
        assert [e["message"] for e in found] == [
            f"Pat started Jaws {tag}",
            f"JAWS stopped {tag} with a problem",
        ]
        # (Each word, in any case, anywhere in the line.)
        found = c.get(f"/api/logs?q=jaws%20{tag}").json()["entries"]
        assert len(found) == 2
        warned = c.get(f"/api/logs?q={tag}&levels=WARNING").json()["entries"]
        assert [e["level"] for e in warned] == ["WARNING"]
        # (Longer than 100 characters: a plain sentence, as other addresses
        # say what's wrong; the cold audit, 1.37.0. FastAPI's list before.)
        long = c.get("/api/logs?q=" + "x" * 101)
        assert long.status_code == 400
        assert long.json() == {"detail": "Search for 100 characters or fewer."}
        assert c.get("/api/logs?q=" + "x" * 100).status_code == 200


def test_the_access_log_is_searched_too(tmp_path):
    with make(tmp_path) as c:
        assert (
            c.post(
                "/api/access/users", json={"name": "Robin", "password": "purple elephant dance"}
            ).status_code
            == 201
        )
        found = c.get("/api/logs?q=robin&access_log=true").json()["entries"]
        assert found and all("robin" in e["message"].casefold() for e in found)
        assert c.get("/api/logs?q=nobody-here&access_log=true").json()["entries"] == []
