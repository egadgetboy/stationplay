"""Who's watching, as Plex says (app/watching.py, stats.WhoWatches): each
Plex Live TV session matched to the one station airing what it shows, the
time counted for that Plex user; and stations kept from some Plex users
(app/limits.py), stopped through Plex only when it's sure which station it
is, and never for anyone else."""

from __future__ import annotations

import json
import logging
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import limits, stats
from app.config import Settings
from app.db import Database, Item
from app.main import create_app
from app.plex import PlexClient, PlexError
from app.schedule import Slot
from app.watching import session_station, sure_station

from .fakeplex import FakePlex
from .helpers import like_plex

KID, PARENT, FRIEND = ("12345", "Kid"), ("1", "Pat"), ("67890", "Sam")


def episode(show: str, title: str, key: str) -> Item:
    return Item(0, 0, 1_800_000, key, "episode", title, show, f"s{key}", 1, 1)


def movie(title: str, key: str) -> Item:
    return Item(0, 0, 7_200_000, key, "movie", title, year=1975)


def session(
    user=KID, show: str | None = "Cheers", title: str = "Pilot", sid: str = "s1", number=None
) -> dict:
    out: dict = {"live": "1", "title": title, "User": {"id": user[0], "title": user[1]}}
    if show:
        out["grandparentTitle"] = show
    if sid:
        out["Session"] = {"id": sid, "bandwidth": 4000, "location": "lan"}
    if number is not None:
        out["Media"] = [{"channelIdentifier": str(number), "channelVcn": str(number)}]
    return out


# Matching a session to a station ---------------------------------------------------


def test_a_session_is_the_one_station_airing_what_it_shows():
    playing = {1: (5, episode("Cheers", "Pilot", "1")), 2: (7, movie("Jaws", "2"))}
    assert session_station(session(), playing) == 1
    assert session_station(session(show=None, title="Jaws"), playing) == 2
    assert session_station(session(show="Taxi"), playing) is None
    assert session_station({**session(), "live": "0"}, playing) is None  # (not Live TV)


def test_the_episode_tells_apart_two_stations_airing_one_show():
    playing = {
        1: (5, episode("Cheers", "Pilot", "1")),
        2: (7, episode("Cheers", "Sam at Eleven", "2")),
    }
    assert session_station(session(title="Sam at Eleven"), playing) == 2
    # The same episode on both: only Plex's channel number tells them apart.
    playing[2] = (7, episode("Cheers", "Pilot", "1"))
    assert session_station(session(), playing) is None
    assert session_station(session(number=7), playing) == 2
    assert session_station(session(number="0007"), playing) == 2


def test_a_channel_that_isnt_a_stations_is_never_taken_for_it():
    """The same program on another tuner's channel (an antenna's 4.1)."""
    playing = {1: (5, episode("Cheers", "Pilot", "1"))}
    assert session_station(session(number="4.1"), playing) is None
    assert session_station(session(number=5), playing) == 1


def test_stopping_needs_the_very_program_or_the_channel_number():
    playing = {1: (5, episode("Cheers", "Pilot", "1"))}
    assert sure_station(session(), playing) == (1, "")
    # Only the show matches (Plex's guide has another episode): not sure...
    cid, why = sure_station(session(title="Endless Slumper"), playing)
    assert cid is None and "can't be sure" in why
    # ...unless Plex names the station's channel.
    assert sure_station(session(title="Endless Slumper", number=5), playing) == (1, "")
    assert sure_station({**session(), "live": "0"}, playing) == (None, "")


# Counting, and stopping, with a stand-in Plex ----------------------------------------


class Sessions:
    """Plex's /status/sessions and "stop playback", as Plex answers."""

    def __init__(self) -> None:
        self.now: list[dict] = []
        self.stopped: list[tuple[str, str]] = []
        self.refuse: int | None = None
        self.configured = True

    async def sessions(self) -> list[dict]:
        return self.now

    async def stop_session(self, session_id: str, reason: str) -> None:
        if self.refuse:
            raise PlexError("refused", self.refuse)
        self.stopped.append((session_id, reason))
        self.now = [s for s in self.now if s.get("Session", {}).get("id") != session_id]


def world(tmp_path, *airing: Item):
    """Stations 5, 7... each airing one program, each with a viewer."""
    db = Database(tmp_path / "stationplay.db")
    ids, stations = [], {}
    for n, item in enumerate(airing):
        channel = db.create_channel(5 + 2 * n, f"Station {5 + 2 * n}", [])
        ids.append(channel.id)

        def locate(at: int, item: Item = item) -> Slot:
            return Slot(item, 0, 0, at - 600_000, at + 1_200_000)

        stations[channel.id] = SimpleNamespace(locate=locate)
    ctx = SimpleNamespace(
        db=db,
        broadcasters={cid: SimpleNamespace(viewers={object()}, behind_ms=0) for cid in ids},
        station=lambda cid: stations[cid],
        plex=Sessions(),
        limits=limits.Limits(db),
    )
    ctx.who_watches = stats.WhoWatches(ctx)
    return ctx, ids


async def test_time_is_counted_for_each_plex_user(tmp_path):
    ctx, _ = world(tmp_path, episode("Cheers", "Pilot", "1"), movie("Jaws", "2"))
    ctx.plex.now = [
        session(KID, sid="a"),
        session(PARENT, show=None, title="Jaws", sid="b"),
        session(FRIEND, show="Taxi", sid="c"),  # (another tuner's channel)
    ]
    now = int(time.time() * 1000)
    assert await ctx.who_watches.look(now) == 2
    assert await ctx.who_watches.look(now + 60_000) == 2
    users = stats.users(ctx, 1, now + 60_000)
    assert [u["name"] for u in users] == ["Kid", "Pat"]
    # The first look counts POLL_S, the next the minute since.
    assert users[0]["hours"] == round((stats.POLL_S + 60) / 3600, 2)
    assert users[0]["stations"][0]["number"] == 5
    assert users[0]["programs"] == [
        {"title": "Cheers", "kind": "episode", "hours": users[0]["hours"]}
    ]
    assert users[1]["programs"][0]["title"] == "Jaws"
    assert ctx.plex.stopped == []  # (nothing's kept from anyone)


async def test_a_station_running_behind_counts_what_it_shows(tmp_path):
    """Tuned in from the beginning: Plex's guide (what's matched) is ahead
    of what's on screen (what's counted)."""
    ctx, (cid,) = world(tmp_path, episode("Cheers", "Pilot", "1"))
    ctx.broadcasters[cid].behind_ms = 600_000
    earlier = movie("Jaws", "2")
    on_time = ctx.station(cid).locate
    ctx.station(cid).locate = lambda at: (
        on_time(at) if at > time.time() * 1000 - 60_000 else Slot(earlier, 0, 0, at, at + 1)
    )
    ctx.plex.now = [session(KID)]
    now = int(time.time() * 1000)
    assert await ctx.who_watches.look(now) == 1
    assert stats.users(ctx, 1, now)[0]["programs"][0]["title"] == "Jaws"


async def test_a_station_kept_from_someone_is_stopped_for_them_only(tmp_path, monkeypatch):
    ctx, (cheers, _jaws) = world(tmp_path, episode("Cheers", "Pilot", "1"), movie("Jaws", "2"))
    ctx.limits.save(True, {KID[0]: [cheers]}, {KID[0]: "Kid"})
    ctx.plex.now = [
        session(KID, sid="kid-cheers"),
        session(PARENT, sid="pat-cheers"),
        session(FRIEND, sid="sam-cheers"),
    ]
    await ctx.who_watches.look(int(time.time() * 1000))
    assert ctx.plex.stopped == [("kid-cheers", limits.REASON)]
    assert [s["name"] for s in ctx.limits.stops] == ["Kid"]
    assert ctx.limits.stops[0]["station"] == "5 Station 5"
    # Kid watching another station: left alone.
    ctx.plex.now = [session(KID, show=None, title="Jaws", sid="kid-jaws")]
    await ctx.who_watches.look(int(time.time() * 1000))
    assert len(ctx.plex.stopped) == 1
    # Tuned in again: stopped again. Still listed a moment after being
    # stopped (Plex ending it): not asked again till AGAIN_S has passed.
    ctx.plex.now = [session(KID, sid="kid-again")]
    ctx.plex.stop_session = _keeps_listing(ctx.plex)
    await ctx.who_watches.look(int(time.time() * 1000))
    await ctx.who_watches.look(int(time.time() * 1000))
    assert [s for s, _ in ctx.plex.stopped] == ["kid-cheers", "kid-again"]
    later = time.monotonic() + limits.AGAIN_S + 1
    monkeypatch.setattr(limits.time, "monotonic", lambda: later)
    await ctx.who_watches.look(int(time.time() * 1000))
    assert [s for s, _ in ctx.plex.stopped] == ["kid-cheers", "kid-again", "kid-again"]


def _keeps_listing(plex: Sessions):
    async def stop(session_id: str, reason: str) -> None:
        plex.stopped.append((session_id, reason))

    return stop


async def test_nothing_is_stopped_unless_its_sure(tmp_path, caplog):
    ctx, (cheers,) = world(tmp_path, episode("Cheers", "Pilot", "1"))
    ctx.limits.save(True, {KID[0]: [cheers]}, {})
    now = int(time.time() * 1000)
    caplog.set_level(logging.INFO, "app.limits")
    # The show, but not that episode, and no channel number.
    ctx.plex.now = [session(KID, title="Endless Slumper", sid="x")]
    await ctx.who_watches.look(now)
    await ctx.who_watches.look(now)
    assert ctx.plex.stopped == []
    assert caplog.text.count("Didn't stop Kid's Plex Live TV session") == 1  # (said once)
    # The same program on another tuner's channel.
    ctx.plex.now = [session(KID, sid="y", number="4.1")]
    await ctx.who_watches.look(now)
    assert ctx.plex.stopped == []
    # Plex naming the station's channel makes it sure.
    ctx.plex.now = [session(KID, title="Endless Slumper", sid="z", number=5)]
    await ctx.who_watches.look(now)
    assert ctx.plex.stopped == [("z", limits.REASON)]
    # No session id to stop it by: left, and said.
    ctx.plex.now = [session(KID, sid="")]
    await ctx.who_watches.look(now)
    assert len(ctx.plex.stopped) == 1
    assert "gave no session ID to stop" in caplog.text


async def test_off_stops_nothing_and_isnt_watched_faster(tmp_path):
    ctx, (cheers,) = world(tmp_path, episode("Cheers", "Pilot", "1"))
    ctx.limits.save(False, {KID[0]: [cheers]}, {})
    assert not ctx.limits.watched(ctx.broadcasters)
    ctx.plex.now = [session(KID)]
    await ctx.who_watches.look(int(time.time() * 1000))
    assert ctx.plex.stopped == []
    ctx.limits.save(True, {KID[0]: [cheers]}, {})
    assert ctx.limits.watched(ctx.broadcasters)
    ctx.broadcasters[cheers].viewers = set()
    assert not ctx.limits.watched(ctx.broadcasters)


async def test_plex_refusing_says_plex_pass(tmp_path):
    ctx, (cheers,) = world(tmp_path, episode("Cheers", "Pilot", "1"))
    ctx.limits.save(True, {KID[0]: [cheers]}, {})
    ctx.plex.refuse = 403
    ctx.plex.now = [session(KID, sid="a")]
    await ctx.who_watches.look(int(time.time() * 1000))
    assert "Plex Pass" in ctx.limits.problem and not ctx.limits.stops
    ctx.plex.refuse = None
    ctx.plex.now = [session(KID, sid="b")]
    await ctx.who_watches.look(int(time.time() * 1000))
    assert ctx.limits.problem == "" and len(ctx.limits.stops) == 1


def test_whats_kept_from_whom_is_kept_and_checked(tmp_path):
    db = Database(tmp_path / "stationplay.db")
    a = db.create_channel(5, "A", []).id
    b = db.create_channel(7, "B", []).id
    kept = limits.Limits(db)
    with pytest.raises(ValueError):
        kept.save(True, {"Kid": [a]}, {})
    with pytest.raises(ValueError):
        kept.save(True, {"0": [a]}, {})  # (Plex's own account)
    kept.save(True, {KID[0]: [a, b, 999], FRIEND[0]: [999]}, {KID[0]: "Kid", FRIEND[0]: "Sam"})
    again = limits.Limits(db)
    assert again.on and again.kept == {KID[0]: {a, b}}  # (no station 999)
    assert again.names == {KID[0]: "Kid"}
    db.set_meta(limits.META, "not json")
    assert limits.Limits(db).kept == {}


# The page ----------------------------------------------------------------------------


def plex_with_users(fp: FakePlex, plex_pass: bool = True) -> httpx.MockTransport:
    base = like_plex(fp)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/accounts":
            accounts = [
                {"id": 0, "key": "/accounts/0", "name": ""},
                {"id": 1, "key": "/accounts/1", "name": "Pat"},
                {"id": int(KID[0]), "key": f"/accounts/{KID[0]}", "name": "Kid"},
            ]
            return httpx.Response(
                200, content=json.dumps({"MediaContainer": {"Account": accounts}})
            )
        if request.url.path == "/":
            body = {"MediaContainer": {"myPlexSubscription": plex_pass, "friendlyName": "NAS"}}
            return httpx.Response(200, content=json.dumps(body))
        return base.handle_request(request)

    return httpx.MockTransport(handler)


@pytest.fixture
def app(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Cheers")
    fp.add_episode("201", "100", 1, 1, "Pilot", "/x/1.mkv", 22 * 60_000)
    return create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=plex_with_users(fp)),
    )


def test_the_access_tab_sets_it_for_admins_only(app):
    with TestClient(app) as admin:
        made = admin.post(
            "/api/channels", json={"number": 5, "sources": [{"type": "show", "ratingKey": "100"}]}
        )
        cid = made.json()["id"]
        got = admin.get("/api/plex-limits").json()
        assert got["plexPass"] is True and not got["on"]
        assert [(u["name"], u["owner"]) for u in got["users"]] == [("Pat", True), ("Kid", False)]
        saved = admin.put(
            "/api/plex-limits", json={"on": True, "kept": {KID[0]: [cid]}, "names": {KID[0]: "Kid"}}
        )
        assert saved.status_code == 200, saved.text
        kid = next(u for u in saved.json()["users"] if u["name"] == "Kid")
        assert saved.json()["on"] and kid["kept"] == [cid]
        assert admin.put("/api/plex-limits", json={"kept": {"x": [cid]}}).status_code == 400
        # Per-user stats are for Admins (while signing in is off: anyone).
        assert "users" in admin.get("/api/stats").json()
        sign_up = {"name": "Pat", "password": "correct horse", "role": "admin"}
        assert admin.post("/api/access/users", json=sign_up).status_code == 201
        sam = {"name": "Sam", "password": "battery staple", "role": "user"}
        assert admin.post("/api/access/users", json=sam).status_code == 201
        user = TestClient(app)
        assert user.post("/api/access/sign-in", json=sam).status_code == 200
        assert user.get("/api/plex-limits").status_code == 403
        assert user.put("/api/plex-limits", json={"on": False}).status_code == 403
        assert "users" not in user.get("/api/stats").json()
        assert "users" in admin.get("/api/stats").json()
