"""A big new station and the scanner (the owner, October 15: making smart
stations of 10,000 to 40,000 episodes hung tapiOca). Planning a round of
quick checks compared whole programs, list against list, on the event loop:
for 40,000 new programs, about two and a half minutes, every 20 checks."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import scanner as sc
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex

EPISODES = 2000


def test_planning_a_round_never_compares_whole_programs(tmp_path, monkeypatch):
    fp = LibraryPlex()
    fp.add_show("100", "Long Runner")
    for n in range(EPISODES):
        fp.add_episode(
            str(10_000 + n), "100", 1 + n // 100, 1 + n % 100, f"Episode {n}", f"/x/{n}.mkv",
            22 * 60_000,
        )  # fmt: skip
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "d")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    with TestClient(app) as client:
        ctx = app.state.ctx
        made = client.post(
            "/api/channels", json={"number": 4, "sources": [{"type": "show", "ratingKey": "100"}]}
        )
        assert made.status_code == 201, made.text
        checked: list[str] = []

        async def quick(program, record):
            checked.append(program.key)
            return sc.Verdict("ok")

        ctx.scanner._quick = quick
        compared = 0
        whole = sc.Program.__eq__

        def counted(self, other):
            nonlocal compared
            compared += 1
            return whole(self, other)

        monkeypatch.setattr(sc.Program, "__eq__", counted)
        client.portal.call(ctx.scanner.round)
        # Its first 20 checked, as before; and programs found by their keys, in
        # sets, never compared whole (it was EPISODES² / 2: about 2 million).
        assert len(checked) == sc.QUICK_BATCH
        assert compared == 0
