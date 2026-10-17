"""Restricted Station access (1.39.0, the owner's D01, October 17): someone
with limits can tune in to a Station only while nothing it plays from now on
is above them. One shared broadcast for everyone; never a stand-in for one
viewer. A Station an Admin allowed for them by hand is blocked only while
something above them is in its published schedule (the next 48 hours, the
guides'), and comes back once that has aired (the owner, 12:58 PM: "The
station is blocked for kid while a restricted title is scheduled. Once the
title passes, then kid is allowed to resume watching the station").

What's checked: a title on now or coming up blocks; an episode rated above
its show; someone already watching is stopped when that changes, and
everyone else watches on; nothing of a blocked Station reaches its guide;
and a schedule that can't be read keeps it blocked."""

from __future__ import annotations

import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import schedule, viewing
from app.config import Settings
from app.db import NewEra
from app.main import create_app
from app.plex import PlexClient
from app.updates import GUIDE_FUTURE_MS

from .fakeplex_library import LibraryPlex
from .test_who_sees_what import ADA, KIT, kid_level, set_up, sign_in_app


@pytest.fixture
def app(tmp_path):
    """As tests/test_who_sees_what.py's: Puppet Town (TV-Y7), Night Shift
    (TV-MA), Picnic (PG) and Heist (R)."""
    fp = LibraryPlex()
    fp.add_show("100", "Puppet Town", contentRating=["TV-Y7"])
    for n in range(1, 4):
        fp.add_episode(f"20{n}", "100", 1, n, f"Puppets {n}", f"/tv/p/{n}.mkv", 22 * 60_000)
    fp.add_show("110", "Night Shift", contentRating=["TV-MA"])
    for n in range(1, 3):
        fp.add_episode(f"21{n}", "110", 1, n, f"Shift {n}", f"/tv/n/{n}.mkv", 44 * 60_000)
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Picnic", "/m/picnic.mkv", 90 * 60_000, section="2", contentRating=["PG"])
    fp.add_movie("301", "Heist", "/m/heist.mkv", 100 * 60_000, section="2", contentRating=["R"])
    for key in ("201", "211", "300", "301"):
        fp.describe(key)
        fp.files[key] = b"a program" * 100
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    made = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    made.state.ctx.play_transport = fp.transport()
    return made


HOUR = 3_600_000


def kid(admin: TestClient, stations: dict[str, bool] | None = None) -> int:
    """Ada (the Admin), and Kit, on the Kid level (with `stations` allowed
    or blocked by hand): Kit's id."""
    admin.post("/api/access/users", json=ADA)
    kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
    body: dict = {"level": kid_level(admin)}
    if stations:
        body["stations"] = stations
    assert admin.put(f"/api/access/users/{kit['id']}/viewing", json=body).status_code == 200
    return kit["id"]


def numbers(phone: TestClient, headers: dict) -> list[int]:
    return [s["number"] for s in phone.get("/api/v1/stations", headers=headers).json()["stations"]]


def only(ctx, channel_id: int, keys: set[str]) -> list:
    """The station's programs that are `keys`."""
    return [i for e in ctx.db.eras(channel_id) for i in e.items if i.rating_key in keys]


def loop(items: list) -> list:
    """`items`, one after another, as a station's loop."""
    out, at = [], 0
    for n, item in enumerate(items):
        out.append(replace(item, position=n, start_ms=at))
        at += item.duration_ms
    return out


def two_eras(ctx, channel_id: int, first: list, then: list, switch_ms: int) -> None:
    """The station plays `first` until `switch_ms`, then `then`."""
    first, then = loop(first), loop(then)
    old = [e.id for e in ctx.db.eras(channel_id)]
    now = int(time.time() * 1000)
    eras = [
        NewEra(first, None, now - HOUR, "a", "in-order", now, "test"),
        NewEra(then, switch_ms, switch_ms, "b", "in-order", now, "test"),
    ]
    ctx.db.replace_eras(channel_id, old, eras)


def test_the_window_is_the_guides():
    assert viewing.STATION_WINDOW_MS == GUIDE_FUTURE_MS == 48 * HOUR


def test_a_station_allowed_by_hand_is_blocked_while_something_above_them_is_scheduled(app):
    """Mixed plays Puppet Town and Heist (R), over and over: Heist is always
    in the next 48 hours, so the allowed Station is blocked for Kit, and the
    Access tab says why and until when (never what it is: that's on the
    Station's own schedule for the Admin)."""
    with TestClient(app) as admin:
        ids = set_up(admin)
        kit = kid(admin, {str(ids[7]): True})
        as_kit = sign_in_app(app, KIT)
        assert numbers(TestClient(app), as_kit) == [3, 9]
        listed = admin.get(f"/api/access/users/{kit}/stations").json()["stations"]
        seven = next(s for s in listed if s["number"] == 7)
        assert seven["chosen"] == "allowed" and seven["levelSees"] is False
        now = int(time.time() * 1000)
        assert now < seven["blockedUntilMs"] <= now + GUIDE_FUTURE_MS + 4 * HOUR
        # (A Station allowed that has nothing above them stays as it was.)
        assert next(s for s in listed if s["number"] == 3)["blockedUntilMs"] is None


def test_it_comes_back_once_the_title_has_aired(app):
    """Mixed plays Heist (R) and Puppet Town until three hours from now, then
    Puppet Town only: blocked for Kit until Heist's last airing ends, then
    back. The level's own rule (a Station not allowed by hand) stays as it
    was: blocked while anything it plays from now on is above them."""
    ctx = app.state.ctx
    with TestClient(app) as admin:
        ids = set_up(admin)
        kit_id = kid(admin, {str(ids[7]): True})
        mixed = ids[7]
        heist, puppets = only(ctx, mixed, {"301"}), only(ctx, mixed, {"201", "202", "203"})
        assert heist and puppets
        now = int(time.time() * 1000)
        switch = now + 3 * HOUR
        two_eras(ctx, mixed, heist + puppets, puppets, switch)
        v = ctx.viewing
        kit = v.viewer(ctx.db.user(kit_id))
        until = v.blocked_until(kit, mixed, now)
        assert until is not None and now < until <= switch
        assert not v.sees_station(kit, mixed, now)
        assert not v.sees_station(kit, mixed, until - 1)
        assert v.blocked_until(kit, mixed, until) is None
        assert v.sees_station(kit, mixed, until)
        assert v.sees_station(kit, mixed, switch + HOUR)
        # (Not allowed by hand: hidden while Heist is still to come, by the level.)
        admin.put(f"/api/access/users/{kit_id}/viewing", json={"stations": {str(mixed): None}})
        kit = v.viewer(ctx.db.user(kit_id))
        assert not v.sees_station(kit, mixed, now)


def test_an_episode_rated_above_its_show_blocks_too(app):
    """Puppet Town is TV-Y7, but one episode is TV-14: on an allowed
    Station, that episode coming up blocks it for Kit."""
    ctx = app.state.ctx
    with TestClient(app) as admin:
        ids = set_up(admin)
        now = int(time.time() * 1000)
        ctx.db.save_titles([("202", "episode", "TV-14", "1", now, now)])
        ctx.titles.__init__(ctx.db)
        kit_id = kid(admin, {str(ids[3]): True})
        kit = ctx.viewing.viewer(ctx.db.user(kit_id))
        assert ctx.viewing.titles.judge(only(ctx, ids[3], {"202"})[0]).age == 14
        assert not ctx.viewing.sees_station(kit, ids[3])


def test_someone_watching_is_stopped_when_it_changes_and_everyone_else_watches_on(app):
    """Kit watches Puppets (allowed by hand) in an app, at its own address.
    An Admin adds Heist (R) to it: Kit's next request there is refused, as
    for a Station that doesn't exist, and Ada's goes on."""
    with TestClient(app) as admin:
        ids = set_up(admin)
        kid(admin, {str(ids[3]): True})
        as_kit, as_ada = sign_in_app(app, KIT), sign_in_app(app, ADA)
        phone, tablet = TestClient(app), TestClient(app)

        def logo(client: TestClient, headers: dict) -> int:
            got = client.get("/api/v1/stations", headers=headers).json()["stations"]
            three = next(s for s in got if s["number"] == 3)
            return three["logo"]

        kits, adas = logo(phone, as_kit), logo(tablet, as_ada)
        assert "/hls/k/" in kits and "/hls/k/" in adas
        assert phone.get(kits).status_code == 200 and tablet.get(adas).status_code == 200
        changed = admin.put(f"/api/channels/{ids[3]}", json={
            "number": 3, "name": "Puppets",
            "sources": [{"type": "show", "ratingKey": "100"}, {"type": "movie", "ratingKey": "301"}],
        })  # fmt: skip
        assert changed.status_code == 200, changed.text
        assert phone.get(kits).status_code == 404
        playlist = kits.replace("/logo.png", "/index.m3u8").split("?")[0]
        assert phone.get(playlist).status_code == 404
        assert tablet.get(adas).status_code == 200


def test_nothing_of_a_blocked_station_reaches_its_guide(app):
    with TestClient(app) as admin:
        ids = set_up(admin)
        kid(admin, {str(ids[7]): True})
        as_kit = sign_in_app(app, KIT)
        phone = TestClient(app)
        now = int(time.time() * 1000)
        guide = phone.get(f"/api/v1/guide?from={now}", headers=as_kit).json()
        assert [s["number"] for s in guide["stations"]] == [3, 9]
        assert "Heist" not in phone.get(f"/api/v1/guide?from={now}", headers=as_kit).text
        page = TestClient(app)
        page.post("/api/access/sign-in", json=KIT)
        assert page.get(f"/api/channels/{ids[7]}/guide").status_code == 404


def test_a_schedule_that_cant_be_read_keeps_it_blocked(app, monkeypatch):
    ctx = app.state.ctx
    with TestClient(app) as admin:
        ids = set_up(admin)
        kit_id = kid(admin, {str(ids[3]): True})
        kit = ctx.viewing.viewer(ctx.db.user(kit_id))
        assert ctx.viewing.sees_station(kit, ids[3])

        def broken(eras):
            raise RuntimeError("the schedule couldn't be worked out")

        monkeypatch.setattr(schedule, "station_schedule", broken)
        ctx.viewing._windows.clear()
        assert not ctx.viewing.sees_station(kit, ids[3])
        # (And with nothing on it at all.)
        monkeypatch.undo()
        ctx.db.replace_eras(ids[3], [e.id for e in ctx.db.eras(ids[3])], [])
        ctx.viewing._windows.clear()
        assert not ctx.viewing.sees_station(kit, ids[3])


@pytest.mark.parametrize("who", ["admin", "nobody"])
def test_without_limits_its_as_it_was(app, who):
    """An Admin, and everyone while signing in is off: every Station."""
    with TestClient(app) as admin:
        ids = set_up(admin)
        if who == "admin":
            kid(admin, {str(ids[7]): True})
            assert numbers(TestClient(app), sign_in_app(app, ADA)) == [3, 5, 7, 9]
        else:
            assert [s["number"] for s in admin.get("/api/v1/stations").json()["stations"]] == [
                3, 5, 7, 9,
            ]  # fmt: skip


def test_a_guide_asked_for_later_never_shows_what_hasnt_been_judged(app):
    """(The hostile audit before building 1.39.0.) The apps' guide can be
    asked for up to 7 days ahead. Puppets, allowed for Kit by hand, plays
    Puppet Town now and adds Heist (R) in three days: Kit may watch it now,
    but Kit's guide stops 48 hours ahead, so Heist never shows in it.
    Ada's shows it all."""
    ctx = app.state.ctx
    with TestClient(app) as admin:
        ids = set_up(admin)
        kid(admin, {str(ids[3]): True})
        puppets = only(ctx, ids[3], {"201", "202", "203"})
        heist = [i for e in ctx.db.eras(ids[7]) for i in e.items if i.rating_key == "301"]
        now = int(time.time() * 1000)
        two_eras(ctx, ids[3], puppets, heist + puppets, now + 72 * HOUR)
        as_kit, as_ada = sign_in_app(app, KIT), sign_in_app(app, ADA)
        phone = TestClient(app)
        assert 3 in numbers(phone, as_kit)
        later = f"/api/v1/guide?from={now + 72 * HOUR}&to={now + 96 * HOUR}"

        def titles(headers: dict) -> set[str]:
            got = phone.get(later, headers=headers).json()["stations"]
            three = next(s for s in got if s["number"] == 3)
            return {p["title"] for p in three["programs"]}

        assert "Heist" in titles(as_ada)
        assert titles(as_kit) == set()
        soon = phone.get(f"/api/v1/guide?from={now}&to={now + 47 * HOUR}", headers=as_kit).json()
        three = next(s for s in soon["stations"] if s["number"] == 3)
        assert three["programs"] and all(p["title"] != "Heist" for p in three["programs"])


def test_the_page_never_tells_them_what_an_allowed_station_is_made_of(app):
    """(The hostile audit before building 1.39.0.) On the page, a Station
    allowed for Kit by hand comes without what it's made of (its shows and
    movies, its coming specials, a change waiting): those may name what's
    above Kit, beyond what's been judged for them. Ada's has it all, and a
    Station Kit's level shows is as it was."""
    with TestClient(app) as admin:
        ids = set_up(admin)
        kid(admin, {str(ids[3]): True})
        page = TestClient(app)
        page.post("/api/access/sign-in", json=KIT)
        mine = {c["number"]: c for c in page.get("/api/channels").json()}
        assert mine[3]["sources"] == [] and mine[3]["pending"] is None
        assert all(mine[3][k] is None for k in ("nextMarathon", "nextFeature", "nextBlock"))
        assert mine[9]["sources"]
        adas = {c["number"]: c for c in admin.get("/api/channels").json()}
        assert adas[3]["sources"]
