"""Commercials and trailers under limits (1.33.0, see cliprules.py and
docs/users.md): on a station someone with limits can see, a clip plays only
if its folder is rated at or below the station's highest-rated program; on
one only people without limits can see, every clip plays as before; and a
clip never changes who can see a station."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import alerts, cliprules
from app.breaks import COMMERCIALS, ID_CARD, TRAILERS, Clip
from app.broadcaster import Broadcaster
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex
from .test_who_sees_what import KIT, kid_level, sign_in_app

ADA = {"name": "Ada", "password": "correct horse"}
COMMERCIAL = Clip("/tv/commercials/soap.mkv", 30_000, 1, 1.0)
SIXTIES = Clip("/tv/commercials/1960s/cola.mkv", 30_000, 1, 1.0, decade=1960)
TRAILER = Clip("/movies/trailers/coming-soon.mkv", 120_000, 1, 1.0)


def test_a_clips_rating_is_its_decade_folders_or_its_kinds(tmp_path):
    from app.db import Database

    rated = cliprules.ClipRatings(Database(tmp_path / "db.sqlite"))
    assert rated.age(COMMERCIALS, COMMERCIAL) is None and rated.age(COMMERCIALS, SIXTIES) is None
    rated.save({"commercials": 0})
    assert rated.age(COMMERCIALS, SIXTIES) == 0  # (its kind's, while the 1960s aren't rated)
    rated.save({"commercials": 0, "commercials/1960s": 14})
    assert rated.age(COMMERCIALS, SIXTIES) == 14 and rated.age(COMMERCIALS, COMMERCIAL) == 0
    assert rated.age(TRAILERS, TRAILER) is None
    for bad in ({"ads": 0}, {"commercials": 99}, {"commercials/sixties": 0}, {"trailers": "R"},
                {"trailers": True}, {"trailers": 17, "ads": 0}):  # fmt: skip
        with pytest.raises(ValueError):
            rated.save(bad)
    assert rated.age(TRAILERS, TRAILER) is None  # (nothing saved from a list that won't do)
    # A folder not given keeps its rating; one given as None isn't rated.
    rated.save({"trailers": 17})
    assert rated.age(COMMERCIALS, SIXTIES) == 14 and rated.age(TRAILERS, TRAILER) == 17
    rated.save({"trailers": None})
    assert rated.age(TRAILERS, TRAILER) is None and rated.age(COMMERCIALS, SIXTIES) == 14
    # (Kept; and what can't be read is nothing rated, so nothing plays where it counts.)
    again = cliprules.ClipRatings(rated.db)
    assert again.age(COMMERCIALS, SIXTIES) == 14
    rated.db.set_meta(cliprules.META, "not json")
    assert cliprules.ClipRatings(rated.db).age(COMMERCIALS, COMMERCIAL) is None
    assert not cliprules.allowed(None, 17) and not cliprules.allowed(0, None)
    assert cliprules.allowed(10, 10) and not cliprules.allowed(13, 10)


@pytest.fixture
def plex():
    fp = LibraryPlex()
    fp.add_show("100", "Puppet Town", contentRating=["TV-Y7"])
    for n in range(1, 4):
        fp.add_episode(f"20{n}", "100", 1, n, f"Puppets {n}", f"/tv/p/{n}.mkv", 22 * 60_000)
    # (The first two aired in 1965, so they get the 1960s commercials; see breaks.decade_of.)
    fp.episodes["201"]["year"] = fp.episodes["202"]["year"] = 1965
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Picnic", "/m/picnic.mkv", 90 * 60_000, section="2", contentRating=["PG"])
    fp.add_movie("301", "Heist", "/m/heist.mkv", 100 * 60_000, section="2", contentRating=["R"])
    return fp


@pytest.fixture
def app(plex, tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    return create_app(settings, PlexClient("http://plex.test", "token", transport=plex.transport()))


def set_up(admin: TestClient) -> dict[int, int]:
    """Stations 3 (a TV-Y7 show), 9 (a PG movie) and 7 (an R movie), each
    with 2 commercials or trailers after each program; Kit on Kid; and the
    clips found: each station's id, by number."""
    ids = {}
    for number, source in ((3, {"type": "show", "ratingKey": "100"}),
                           (9, {"type": "movie", "ratingKey": "300"}),
                           (7, {"type": "movie", "ratingKey": "301"})):  # fmt: skip
        made = admin.post(
            "/api/channels", json={"number": number, "sources": [source], "breaks": 2}
        )
        assert made.status_code == 201, made.text
        ids[number] = made.json()["id"]
    ctx = admin.app.state.ctx
    admin.portal.call(ctx.titles.filled)
    admin.post("/api/access/users", json=ADA)
    kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
    assert (
        admin.put(
            f"/api/access/users/{kit['id']}/viewing", json={"level": kid_level(admin)}
        ).status_code
        == 200
    )
    fillers = ctx.fillers
    fillers.clips = {COMMERCIALS: [COMMERCIAL, SIXTIES], TRAILERS: [TRAILER]}
    for clip in (COMMERCIAL, SIXTIES, TRAILER):
        fillers._known[clip.path] = clip
    return ids


def chosen(ctx, channel_id: int) -> set[str]:
    """The clips a lineup made now would have after each program."""
    channel = ctx.db.get_channel(channel_id)
    programs = [
        replace(i, breaks=None, duration_ms=i.program_end_ms)
        for i in ctx.db.latest_items(channel_id)
    ]
    made = ctx.updater.with_breaks(channel, programs)
    return {path for i in made for path, _ in i.breaks or () if path != ID_CARD}


def test_unrated_clips_never_play_where_someone_with_limits_can_see(app):
    with TestClient(app) as admin:
        ids = set_up(admin)
        ctx = admin.app.state.ctx
        as_kit = sign_in_app(app, KIT)
        seen = [
            s["number"]
            for s in TestClient(app).get("/api/v1/stations", headers=as_kit).json()["stations"]
        ]
        assert seen == [3, 9]  # (and clips don't change that)

        # Nothing rated: Kit's stations get none; the R station, which only
        # Ada sees, every one, as before.
        assert chosen(ctx, ids[3]) == set() and chosen(ctx, ids[9]) == set()
        assert chosen(ctx, ids[7]) == {TRAILER.path}
        assert alerts.skipping_unrated(ctx) == 2

        # Rated: commercials for all ages, trailers R. Station 3 (TV-Y7) gets
        # its commercials; station 9's movie is PG, so no R trailer there.
        put = admin.put("/api/access/clips", json={"ratings": {"commercials": 0, "trailers": 17}})
        assert put.status_code == 200, put.text
        folders = {f["key"]: f for f in put.json()["folders"]}
        assert folders["commercials/1960s"] == {"key": "commercials/1960s", "kind": "commercials",
                                                 "decade": 1960, "clips": 1, "age": None}  # fmt: skip
        assert chosen(ctx, ids[3]) == {COMMERCIAL.path, SIXTIES.path}
        assert chosen(ctx, ids[9]) == set() and chosen(ctx, ids[7]) == {TRAILER.path}
        assert alerts.skipping_unrated(ctx) == 0

        # The 1960s rated TV-14: above station 3's TV-Y7, so they're left out there.
        admin.put("/api/access/clips", json={"ratings": {"commercials": 0, "commercials/1960s": 14,
                                                         "trailers": 17}})  # fmt: skip
        assert chosen(ctx, ids[3]) == {COMMERCIAL.path}
        logs = admin.get("/api/logs?access_log=true").json()["text"]
        assert "Ada rated the clip folders: commercials/1960s TV-14" in logs

        # Who sees a station never changes with its clips.
        seen = [
            s["number"]
            for s in TestClient(app).get("/api/v1/stations", headers=as_kit).json()["stations"]
        ]
        assert seen == [3, 9]


def test_a_clip_chosen_before_isnt_played_where_it_no_longer_may(app):
    """A lineup made while only Ada could see station 7 has its trailer;
    once Kit is allowed station 7, the trailer isn't played there (a plain
    card covers its time) until the lineup is made again."""
    with TestClient(app) as admin:
        ids = set_up(admin)
        ctx = admin.app.state.ctx
        channel = ctx.db.get_channel(ids[7])
        playing = SimpleNamespace(ctx=ctx)
        slot = SimpleNamespace(item=SimpleNamespace(kind="movie"))
        assert Broadcaster._clip_allowed(playing, channel, slot, TRAILER.path)
        kit = next(u for u in ctx.db.users() if u.name == "Kit")
        admin.put(f"/api/access/users/{kit.id}/viewing", json={"stations": {str(ids[7]): True}})
        assert not Broadcaster._clip_allowed(playing, channel, slot, TRAILER.path)
        # Rated R, at the station's R: it plays again.
        admin.put("/api/access/clips", json={"ratings": {"trailers": 17}})
        assert Broadcaster._clip_allowed(playing, channel, slot, TRAILER.path)
        # A clip that's gone from the folders isn't played where it counts.
        assert not Broadcaster._clip_allowed(playing, channel, slot, "/movies/trailers/gone.mkv")


def test_with_signing_in_off_no_one_has_limits(app):
    with TestClient(app) as admin:
        ids = set_up(admin)
        ctx = admin.app.state.ctx
        ctx.viewing.signing_in = lambda: False
        assert chosen(ctx, ids[3]) == {COMMERCIAL.path, SIXTIES.path}
        assert alerts.skipping_unrated(ctx) == 0


def test_an_alert_says_how_many_stations_skip_unrated_clips(tmp_path):
    from app.alerts import Alerts
    from app.db import Database

    from .test_alerts import Told

    told = Told()
    found = Alerts(told, Database(tmp_path / "db.sqlite"))  # type: ignore[arg-type]
    found.clips(0)
    assert found.now() == [] and told.said == []
    found.clips(2)
    [alert] = found.now()
    assert alert.kind == alerts.CLIPS
    assert alert.sentence == (
        "2 stations people with limits can see skip commercials or trailers that aren't "
        "rated. Rate their folders under Viewing Levels on the Access tab."
    )
    found.clips(0)
    assert found.now() == []
    assert told.said[-1][0] == (
        "Every station people with limits can see has its commercials and trailers rated."
    )


def test_a_feature_presentation_is_judged_with_its_station(app):
    """The audit of 1.33.0: a station's specials (its Feature Presentation's
    and blocks' programs) were judged on their own. A PG feature on station
    7, which plays an R movie only Ada can see, lost its unrated trailers as
    if Kit could see the station."""
    with TestClient(app) as admin:
        ids = set_up(admin)
        ctx = admin.app.state.ctx
        picnic = [
            replace(i, breaks=None, duration_ms=i.program_end_ms)
            for i in ctx.db.latest_items(ids[9])
        ]
        made = admin.portal.call(
            ctx.updater.sets_as_aired, ctx.db.get_channel(ids[7]), {"feature": picnic}
        )
        assert {p for i in made["feature"] for p, _ in i.breaks or () if p != ID_CARD} == {
            TRAILER.path
        }
        # (On a station Kit sees, it's judged with that station: none.)
        made = admin.portal.call(
            ctx.updater.sets_as_aired, ctx.db.get_channel(ids[9]), {"feature": picnic}
        )
        assert {p for i in made["feature"] for p, _ in i.breaks or () if p != ID_CARD} == set()


def test_a_new_stations_clips_are_dealt_before_its_ratings_are_known(app, plex):
    """The audit of 1.33.0: a station made from a show not asked about yet
    got no commercials at all, rated or not, until the next full check. Now
    every clip is dealt while what it plays isn't known, and each is judged
    as it's about to play."""
    plex.add_show("110", "Barn Dance", contentRating=["TV-G"])
    for n in range(1, 3):
        plex.add_episode(f"21{n}", "110", 1, n, f"Dance {n}", f"/tv/b/{n}.mkv", 22 * 60_000)
    with TestClient(app) as admin:
        set_up(admin)
        ctx = admin.app.state.ctx
        assert (
            admin.put("/api/access/clips", json={"ratings": {"commercials": 0}}).status_code == 200
        )
        made = admin.post("/api/channels", json={"number": 12, "sources": [
            {"type": "show", "ratingKey": "110"}], "breaks": 2})  # fmt: skip
        assert made.status_code == 201, made.text
        channel = ctx.db.get_channel(made.json()["id"])
        dealt = {
            p for i in ctx.db.latest_items(channel.id) for p, _ in i.breaks or () if p != ID_CARD
        }
        assert dealt == {COMMERCIAL.path, SIXTIES.path} or dealt == {COMMERCIAL.path}
        playing = SimpleNamespace(ctx=ctx)
        slot = SimpleNamespace(item=SimpleNamespace(kind="episode"))
        # (Once it's known, TV-G, Kit sees it: rated for all ages, played.)
        admin.portal.call(ctx.titles.filled)
        assert Broadcaster._clip_allowed(playing, channel, slot, COMMERCIAL.path)


def test_rated_clips_play_while_stationplay_is_starting(app):
    """The audit of 1.33.0: until the clip folders had been looked in (as
    StationPlay starts, or longer if Plex didn't answer), every commercial
    on a station someone with limits sees was a plain card, rated or not.
    Then, a clip is rated by the folder its path is in."""
    with TestClient(app) as admin:
        ids = set_up(admin)
        ctx = admin.app.state.ctx
        admin.put(
            "/api/access/clips", json={"ratings": {"commercials": 0, "commercials/1960s": 14}}
        )
        ctx.fillers._known.clear()
        ctx.fillers.refreshed_ms = 0
        playing = SimpleNamespace(ctx=ctx)
        slot = SimpleNamespace(item=SimpleNamespace(kind="episode"))
        channel = ctx.db.get_channel(ids[3])  # (TV-Y7, which Kit sees)
        assert Broadcaster._clip_allowed(playing, channel, slot, COMMERCIAL.path)
        assert not Broadcaster._clip_allowed(playing, channel, slot, SIXTIES.path)  # (TV-14)
        assert not Broadcaster._clip_allowed(playing, channel, slot, "/tv/elsewhere/x.mkv")
        ctx.fillers.refreshed_ms = 1  # (looked in: one not found is gone)
        assert not Broadcaster._clip_allowed(playing, channel, slot, COMMERCIAL.path)


def test_the_alert_counts_specials_too(app):
    """The audit of 1.33.0: a station Kit sees whose Feature Presentation
    skips unrated trailers wasn't counted."""
    with TestClient(app) as admin:
        ids = set_up(admin)
        ctx = admin.app.state.ctx
        admin.put("/api/access/clips", json={"ratings": {"commercials": 0}})
        assert alerts.skipping_unrated(ctx) == 1  # (station 9's trailers)
        picnic = ctx.db.latest_items(ids[9])
        ctx.db.save_program_sets(ids[3], {"feature": picnic})
        assert alerts.skipping_unrated(ctx) == 2


def test_clip_ratings_take_only_folders_and_ratings(app):
    """The audit of 1.33.0: true was taken as 1, "commercials/" and a decade
    in other digits as folders."""
    with TestClient(app) as admin:
        set_up(admin)
        for ratings in ({"trailers": True}, {"trailers": "13"}):
            assert admin.put("/api/access/clips", json={"ratings": ratings}).status_code == 422
        for key in ("commercials/", "commercials/١٩٦٠s", "commercials/" + "1" * 50 + "0s",
                    "commercials/1960s/x", "commercials/1910s"):  # fmt: skip
            put = admin.put("/api/access/clips", json={"ratings": {key: 0}})
            assert put.status_code == 400, key
        assert admin.get("/api/access/clips").json()["folders"][0]["age"] is None


def test_new_ratings_make_the_stations_lineups_again(app):
    """Rating the clip folders makes lineups again with what may play (the
    check for Plex's changes counts the ratings, and who might see what)."""
    with TestClient(app) as admin:
        ids = set_up(admin)
        ctx = admin.app.state.ctx

        def dealt(number: int) -> set[str] | None:
            """What the update waiting for the station deals (None: no update)."""
            update = ctx.updater.pending.get(ids[number])
            if update is None:
                return None
            return {p for i in update.items for p, _ in i.breaks or () if p != ID_CARD}

        admin.portal.call(ctx.updater.check)
        assert dealt(3) is None  # (nothing changed: Kit sees it, and nothing's rated)
        admin.put("/api/access/clips", json={"ratings": {"commercials": 0}})
        admin.portal.call(ctx.updater.check)
        assert dealt(3) == {COMMERCIAL.path, SIXTIES.path}
