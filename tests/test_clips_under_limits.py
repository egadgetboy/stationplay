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
        # (As StationPlay starts: no folder looked in yet.)
        ctx.fillers.clips = {COMMERCIALS: [], TRAILERS: []}
        ctx.fillers._known.clear()
        ctx.fillers.refreshed_ms = 0
        playing = SimpleNamespace(ctx=ctx)
        slot = SimpleNamespace(item=SimpleNamespace(kind="episode"))
        channel = ctx.db.get_channel(ids[3])  # (TV-Y7, which Kit sees)
        assert Broadcaster._clip_allowed(playing, channel, slot, COMMERCIAL.path)
        assert not Broadcaster._clip_allowed(playing, channel, slot, SIXTIES.path)  # (TV-14)
        assert not Broadcaster._clip_allowed(playing, channel, slot, "/tv/elsewhere/x.mkv")
        # (The first commercials folder in its path is the clips' own: one
        # inside a decade's is still that decade's.)
        nested = "/tv/commercials/1960s/commercials/fizz.mkv"
        assert not Broadcaster._clip_allowed(playing, channel, slot, nested)
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


def test_a_decades_rating_counts_for_clips_found_in_the_folders(app, plex, tmp_path, monkeypatch):
    """The re-check of 1.33.0's audit: the clips found on disk were kept,
    for the check as each plays, without their decade, so a 1960s
    commercial rated TV-14 was judged by commercials' own rating (all ages)
    and played on a TV-Y7 station Kit sees, dealt there because the new
    station's show wasn't known yet."""
    from app import ffmpeg as ff

    plex.add_show("110", "Barn Dance", contentRating=["TV-Y7"])
    for n in range(1, 3):
        plex.add_episode(f"21{n}", "110", 1, n, f"Dance {n}", f"/tv/b/{n}.mkv", 22 * 60_000)
        plex.episodes[f"21{n}"]["year"] = 1965
    folder = tmp_path / "tv" / "commercials"
    (folder / "1960s").mkdir(parents=True)
    for f in (folder / "soap.mkv", folder / "1960s" / "cola.mkv"):
        f.write_bytes(b"a clip")

    async def probe(settings, path, timeout=None, **kw):
        return ff.ProbeResult(ok=True, duration_s=30.0)

    monkeypatch.setattr(ff, "probe", probe)
    with TestClient(app) as admin:
        set_up(admin)
        ctx = admin.app.state.ctx
        fillers = ctx.fillers
        fillers._known.clear()
        found = admin.portal.call(fillers._clips, [str(folder)])  # (as the folders are looked in)
        fillers.clips = {COMMERCIALS: found, TRAILERS: []}
        fillers.refreshed_ms = 1
        admin.put(
            "/api/access/clips", json={"ratings": {"commercials": 0, "commercials/1960s": 14}}
        )
        made = admin.post("/api/channels", json={"number": 12, "sources": [
            {"type": "show", "ratingKey": "110"}], "breaks": 2})  # fmt: skip
        assert made.status_code == 201, made.text
        channel = ctx.db.get_channel(made.json()["id"])
        admin.portal.call(ctx.titles.filled)
        listed = TestClient(app).get("/api/v1/stations", headers=sign_in_app(app, KIT)).json()
        assert 12 in [s["number"] for s in listed["stations"]]
        playing = SimpleNamespace(ctx=ctx)
        slot = SimpleNamespace(item=SimpleNamespace(kind="episode"))
        sixties, soap = str(folder / "1960s" / "cola.mkv"), str(folder / "soap.mkv")
        assert not Broadcaster._clip_allowed(playing, channel, slot, sixties)
        assert Broadcaster._clip_allowed(playing, channel, slot, soap)
        # (A decade rated on its own, its kind not: it plays, the rest don't.)
        admin.put(
            "/api/access/clips", json={"ratings": {"commercials": None, "commercials/1960s": 0}}
        )
        assert Broadcaster._clip_allowed(playing, channel, slot, sixties)
        assert not Broadcaster._clip_allowed(playing, channel, slot, soap)


def test_a_new_stations_feature_presentation_is_judged_with_it(app, plex):
    """The re-check of 1.33.0's audit: as a station was made (or changed),
    its Feature Presentation was judged with the station as kept, which was
    nothing yet: a G feature on a station of an R movie, which only Ada can
    see, lost its unrated trailers as if Kit could see it."""
    plex.add_section("3", "Family", "movie")
    plex.add_movie("303", "Kite Day", "/f/kite.mkv", 80 * 60_000, section="3", contentRating=["G"])
    with TestClient(app) as admin:
        set_up(admin)
        ctx = admin.app.state.ctx
        made = admin.post("/api/channels", json={
            "number": 5, "sources": [{"type": "movie", "ratingKey": "301"}], "breaks": 2,
            "featureMode": "on", "featureDays": "0", "featureTime": "20:00",
            "featureSource": {"type": "section", "key": "3", "sectionType": "movie",
                              "title": "Family"}})  # fmt: skip
        assert made.status_code == 201, made.text
        sets = ctx.db.program_sets(made.json()["id"])
        assert sets
        for programs in sets.values():
            assert {p for i in programs for p, _ in i.breaks or () if p != ID_CARD} == {
                TRAILER.path
            }


def test_a_lineup_is_judged_with_its_stations_specials_as_kept(app):
    """Station 9's PG movie, which Kit could see, with a Feature
    Presentation of the R movie: the whole station is hidden from Kit, so
    its own lineup plays every trailer too."""
    with TestClient(app) as admin:
        ids = set_up(admin)
        ctx = admin.app.state.ctx
        assert chosen(ctx, ids[9]) == set()
        heist = [replace(i, breaks=None) for i in ctx.db.latest_items(ids[7])]
        ctx.db.save_program_sets(ids[9], {"feature": heist})
        assert chosen(ctx, ids[9]) == {TRAILER.path}


def test_clips_are_dealt_while_whats_hidden_by_tags_isnt_known(app):
    """While someone hides by genre and a station's titles' genres aren't
    known yet, every clip is dealt (as while its ratings aren't), and each
    is judged as it plays."""
    with TestClient(app) as admin:
        ids = set_up(admin)
        ctx = admin.app.state.ctx
        kid = kid_level(admin)
        put = admin.put(f"/api/access/levels/{kid}", json={
            "name": "Kid", "movieAge": 10, "tvAge": 10, "unrated": False,
            "blocks": {"genres": ["Westerns"]}})  # fmt: skip
        assert put.status_code == 200, put.text
        admin.portal.call(ctx.titles.filled)
        assert chosen(ctx, ids[9]) == set()  # (known: Kit sees it, trailers unrated)
        titles = ctx.titles
        old = titles.get("300")
        titles._save({"300": replace(old, tags=None)}, old.checked_ms)  # (not known yet)
        assert chosen(ctx, ids[9]) == {TRAILER.path}


def test_the_alert_counts_trailers_after_anything_but_episodes(app):
    with TestClient(app) as admin:
        ids = set_up(admin)
        ctx = admin.app.state.ctx
        admin.put("/api/access/clips", json={"ratings": {"commercials": 0}})
        assert alerts.skipping_unrated(ctx) == 1  # (station 9's trailers)
        other = [replace(i, kind="clip") for i in ctx.db.latest_items(ids[3])]
        ctx.db.save_program_sets(ids[3], {"feature": other})
        assert alerts.skipping_unrated(ctx) == 2  # (and station 3's special, trailers after it)


def feature(section: str, title: str) -> dict:
    return {"featureMode": "on", "featureDays": "0", "featureTime": "20:00",
            "featureSource": {"type": "section", "key": section, "sectionType": "movie",
                              "title": title}}  # fmt: skip


def trailers_of(items) -> set[str]:
    return {p for i in items for p, _ in i.breaks or () if p != ID_CARD}


@pytest.fixture
def specials(plex):
    """A Media folder of a G movie, and one of an R movie, for Feature
    Presentations."""
    plex.add_section("3", "Family", "movie")
    plex.add_movie("303", "Kite Day", "/f/kite.mkv", 80 * 60_000, section="3", contentRating=["G"])
    plex.add_section("4", "Late Show", "movie")
    plex.add_movie("304", "Night Run", "/l/run.mkv", 95 * 60_000, section="4", contentRating=["R"])
    return plex


def test_a_station_is_judged_whole_when_made_or_changed(app, specials):
    """The final check of 1.33.0: a new station's lineup was judged without
    its new Feature Presentation; a changed station's specials, with its
    lineup as it was; an edit of the specials alone left the lineup's
    breaks as they were. Kit sees PG at most; trailers aren't rated."""
    with TestClient(app) as admin:
        set_up(admin)
        ctx = admin.app.state.ctx

        def edit(movie: str, section: str, title: str) -> None:
            put = admin.put(f"/api/channels/{six}", json={
                "number": 6, "sources": [{"type": "movie", "ratingKey": movie}], "breaks": 2,
                **feature(section, title)})  # fmt: skip
            assert put.status_code == 200, put.text

        def lineup() -> set[str]:
            return trailers_of(ctx.db.latest_items(six))

        def features() -> list[set[str]]:
            sets = ctx.db.program_sets(six)
            assert sets
            return [trailers_of(programs) for programs in sets.values()]

        # Made: a PG movie with an R feature, which only Ada can see: every trailer.
        made = admin.post("/api/channels", json={
            "number": 6, "sources": [{"type": "movie", "ratingKey": "300"}], "breaks": 2,
            **feature("4", "Late Show")})  # fmt: skip
        assert made.status_code == 201, made.text
        six = made.json()["id"]
        assert lineup() == {TRAILER.path} and features() == [{TRAILER.path}]
        # The feature alone changed, to G: Kit can see it all now, so the
        # lineup's breaks are dealt again too: no trailers anywhere.
        edit("300", "3", "Family")
        assert lineup() == set() and features() == [set()]
        # The lineup alone changed, to the R movie: only Ada sees it, so the
        # G feature (judged with the new lineup) plays every trailer too.
        edit("301", "3", "Family")
        assert lineup() == {TRAILER.path} and features() == [{TRAILER.path}]


def test_a_station_is_judged_whole_as_it_follows_plex(app, specials):
    """The final check of 1.33.0: Update now, and the checks for Plex's
    changes, judged a station's specials with its lineup as it was. Station
    8 plays a collection holding an R movie, with a G feature; then the
    collection holds a PG movie instead, so Kit can see the station, and
    neither keeps its unrated trailers."""
    specials.add_collection("950", "Picks", "2", "301")
    with TestClient(app) as admin:
        set_up(admin)
        ctx = admin.app.state.ctx
        picks = {"type": "collection", "ratingKey": "950", "title": "Picks", "library": "2",
                 "kind": "movie"}  # fmt: skip
        made = admin.post("/api/channels", json={
            "number": 8, "sources": [picks], "breaks": 2, **feature("3", "Family")})  # fmt: skip
        assert made.status_code == 201, made.text
        eight = made.json()["id"]
        sets = ctx.db.program_sets(eight)
        assert sets and all(trailers_of(s) == {TRAILER.path} for s in sets.values())
        specials.collections["950"]["children"] = ["300"]
        specials.collections["950"]["updatedAt"] += 1
        admin.portal.call(ctx.updater.check, True)
        update = ctx.updater.pending[eight]
        assert update.sets and trailers_of(update.items) == set()
        assert all(trailers_of(s) == set() for s in update.sets.values())
        ctx.updater.pending.pop(eight)
        now = admin.post(f"/api/channels/{eight}/update")
        assert now.status_code == 200, now.text
        assert trailers_of(ctx.db.latest_items(eight)) == set()
        sets = ctx.db.program_sets(eight)
        assert sets and all(trailers_of(s) == set() for s in sets.values())
