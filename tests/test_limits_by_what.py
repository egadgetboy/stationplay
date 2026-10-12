"""Limits by what a title is (1.33.0, see docs/users.md): a Viewing Level, or
one person, hides titles by their genres, tags (Plex's labels), collections
and studio, or by name; a title can be allowed for one person. Hidden
everywhere tapiOca lists or plays things, judged by a title's tags
whole (lists carry only a few genres), and what isn't known yet is hidden
from anyone limited by tags. A tapiOca where no one hides by them
answers exactly as before."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.catalog import Tags
from app.config import Settings
from app.db import Database, Item
from app.main import create_app
from app.plex import PlexClient
from app.titles import Judged, Titles
from app.viewing import Blocks, Level, Person, Reach, Viewer, reach_of

from .fakeplex_library import LibraryPlex
from .test_who_sees_what import KIT, kid_level, sign_in_app

NO_TAGS = Tags()  # (known, and none of them)
HORROR = Tags(genres=("Comedy", "Mystery", "Thriller", "Horror"))


def level(**blocks) -> Level:
    return Level(9, "Kid", None, None, True, None, "", Blocks(**blocks))


def test_blocks_match_whatever_the_case_and_are_kept_as_written():
    got = Blocks.from_json(
        {"genres": ["horror", "Horror", " Gore "], "studios": ["Big Studio"],
         "titles": [{"key": "301", "title": "Heist"}]}
    )  # fmt: skip
    assert got.genres == ("Gore", "horror") and got.studios == ("Big Studio",)
    assert got.hit("1", HORROR) == "genres"
    assert got.hit("301", Tags()) == "title"
    assert got.hit("1", Tags(studio="BIG STUDIO")) == "studios"
    assert got.hit("1", Tags(genres=("Comedy",))) is None
    assert got.hit("1", None) == "unknown"  # (not known yet: hidden, to be safe)
    assert Blocks.from_text(got.to_text()) == got
    assert Blocks().to_text() == ""
    for bad in ({"genres": "Horror"}, {"genres": ["x" * 101]}, {"titles": [{"key": "../1"}]},
                {"labels": ["a"] * 201}):  # fmt: skip
        with pytest.raises(ValueError):
            Blocks.from_json(bad)


def test_a_level_hides_by_genre_tag_collection_studio_and_title():
    def judged(key: str = "1", tags: Tags | None = NO_TAGS, age: int | None = 0) -> Judged:
        return Judged(False, age, "2", True, key, tags)

    assert not level(genres=("Horror",)).allows(judged(tags=HORROR))
    assert not level(labels=("scary",)).allows(judged(tags=Tags(labels=("Scary",))))
    assert not level(collections=("Monsters",)).allows(judged(tags=Tags(collections=("Monsters",))))
    assert not level(studios=("Dread Pictures",)).allows(judged(tags=Tags(studio="Dread Pictures")))
    assert not level(titles=(("301", "Heist"),)).allows(judged(key="301"))
    assert level(genres=("Horror",)).allows(judged(tags=Tags(genres=("Comedy",))))
    # Not known yet: hidden from a level that hides by tags...
    assert not level(genres=("Horror",)).allows(judged(tags=None))
    # ...but a level that doesn't goes as before, known or not (an update
    # to 1.33.0, whose titles have no tags yet, changes no one's).
    teen = Level(2, "Teen", 13, 14, False, None)
    assert teen.limited and teen.allows(judged(tags=None))
    assert teen.allows(judged(tags=None, age=10)) and not teen.allows(judged(age=17))
    # Unrated: hidden as the level says, then by its tags too.
    shown = Level(3, "x", None, None, True, None, "", Blocks(genres=("Horror",)))
    assert not shown.allows(judged(age=None, tags=HORROR))
    assert shown.allows(judged(age=None, tags=Tags(genres=("Comedy",))))


def test_a_station_is_hidden_by_any_program_its_level_hides(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    titles = Titles(db)
    titles._save({
        "100": Titles_title("show", "TV-Y7", HORROR),
        "300": Titles_title("movie", "PG", Tags(genres=("Comedy",), studio="Sunny")),
        "301": Titles_title("movie", "PG", None),
    }, 1)  # fmt: skip
    episode = Item(0, 0, 1, "201", "episode", "", show_key="100")
    movie = Item(1, 1, 1, "300", "movie", "")
    reach = reach_of([episode, movie], titles)
    assert reach.titles == {"100", "300"} and reach.tagged
    assert reach.genres == {"comedy", "mystery", "thriller", "horror"}
    assert reach.studios == {"sunny"}
    kid = level(genres=("HORROR",))
    assert not kid.allows_reach(reach)
    assert kid.why_not(reach) == "It plays programs with the genre HORROR, which Kid hides"
    assert level(studios=("sunny",)).why_not(reach) == (
        "It plays programs with the studio sunny, which Kid hides"
    )
    assert level(genres=("Western",)).allows_reach(reach)
    # A program whose tags aren't known yet: hidden from a level that hides by
    # them, and said so.
    unknown = reach_of([movie, Item(2, 2, 1, "301", "movie", "")], titles)
    assert not unknown.tagged
    assert level(genres=("Western",)).why_not(unknown) == (
        "tapiOca is still asking Plex about the genres and tags of what it plays"
    )
    assert Level(2, "Teen", 13, 14, True, None).allows_reach(unknown)


def Titles_title(kind: str, rating: str, tags: Tags | None):
    from app.titles import Title

    return Title(kind, rating, "1", 1, tags)


def test_the_rules_in_order_for_one_person():
    """docs/users.md: a title hidden for the person, then one allowed for
    them (unless its Media folder isn't on their level), then their level,
    then what's hidden for them."""
    kid = Level(4, "Kid", 10, 10, False, frozenset({"1", "2"}), "", Blocks(genres=("Horror",)))
    own = Person(Blocks(genres=("Westerns",), titles=(("300", "Picnic"),)), (("301", "Heist"),))
    pat = Viewer(kid, everything=False, own=own)

    def judged(key: str, age: int | None = 0, tags: Tags | None = NO_TAGS, library="2") -> Judged:
        return Judged(False, age, library, True, key, tags)

    assert not pat.sees(judged("300"))  # (hidden for Pat, though Kid shows it)
    assert pat.sees(judged("301", age=17, tags=HORROR))  # (allowed for Pat: rating and genre aside)
    assert not pat.sees(judged("301", library="9"))  # (...but not from a Media folder Kid hides)
    assert not pat.sees(judged("302", tags=Tags(genres=("Westerns",))))  # (hidden for Pat)
    assert not pat.sees(judged("303", tags=HORROR))  # (hidden by Kid)
    assert pat.sees(judged("304", tags=Tags(genres=("Comedy",))))
    assert pat.by_tags
    # What's hidden for someone counts for stations too; what's allowed for
    # them doesn't widen one (an Admin allows the station instead).
    reach = Reach(titles=frozenset({"300"}))
    assert own.blocks.meets(reach) == "title"


@pytest.fixture
def plex():
    fp = LibraryPlex()
    fp.add_show("100", "Puppet Town", contentRating=["TV-Y7"], genres=["Kids"])
    for n in range(1, 4):
        fp.add_episode(f"20{n}", "100", 1, n, f"Puppets {n}", f"/tv/p/{n}.mkv", 22 * 60_000)
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Picnic", "/m/picnic.mkv", 90 * 60_000, section="2",
                 contentRating=["PG"], genres=["Comedy"])  # fmt: skip
    # A PG movie whose fourth genre, which lists don't carry, is Horror.
    fp.add_movie("302", "Creaky House", "/m/creaky.mkv", 95 * 60_000, section="2",
                 contentRating=["PG"], genres=["Comedy", "Mystery", "Family"])  # fmt: skip
    fp.more["302"] = {"Genre": [{"tag": g} for g in ("Comedy", "Mystery", "Family", "Horror")]}
    for key in ("201", "300", "302"):
        fp.describe(key)
        fp.files[key] = b"a program" * 100
    return fp


@pytest.fixture
def app(plex, tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=plex.transport()))
    app.state.ctx.play_transport = plex.transport()
    return app


def test_a_level_hiding_a_genre_hides_it_everywhere_by_its_whole_list(app):
    with TestClient(app) as admin:
        ids = {}
        for number, sources in ((3, [{"type": "show", "ratingKey": "100"}]),
                                (8, [{"type": "movie", "ratingKey": "302"}]),
                                (9, [{"type": "movie", "ratingKey": "300"}])):  # fmt: skip
            made = admin.post("/api/channels", json={"number": number, "sources": sources})
            assert made.status_code == 201, made.text
            ids[number] = made.json()["id"]
        admin.portal.call(admin.app.state.ctx.titles.filled)
        assert admin.put("/api/app-libraries", json={"libraries": ["1", "2"]}).status_code == 200
        admin.post("/api/access/users", json={"name": "Ada", "password": "correct horse"})
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        kid = kid_level(admin)
        assert (
            admin.put(f"/api/access/users/{kit['id']}/viewing", json={"level": kid}).status_code
            == 200
        )
        as_kit = sign_in_app(app, KIT)
        phone = TestClient(app)

        def stations() -> list[int]:
            return [
                s["number"]
                for s in phone.get("/api/v1/stations", headers=as_kit).json()["stations"]
            ]

        def movies() -> set[str]:
            got = phone.get("/api/internal/libraries/2", headers=as_kit).json()
            return {c["key"] for c in got["items"]}

        # Before: Kid sees every PG movie and its station.
        assert stations() == [3, 8, 9] and movies() == {"300", "302"}

        # Kid now hides Horror: the movie whose fourth genre it is goes, from
        # Media and search, and so does its station; the others stay.
        changed = admin.put(f"/api/access/levels/{kid}", json={
            "name": "Kid", "movieAge": 10, "tvAge": 10, "unrated": False,
            "blocks": {"genres": ["horror"]},
        })  # fmt: skip
        assert changed.status_code == 200, changed.text
        assert changed.json()["blocks"]["genres"] == ["horror"]
        assert movies() == {"300"}
        found = phone.get("/api/internal/search?q=creaky", headers=as_kit).json()
        assert "302" not in {c["key"] for c in found["items"]}
        assert phone.get("/api/internal/items/302", headers=as_kit).status_code == 404
        admin.portal.call(admin.app.state.ctx.titles.filled)
        assert stations() == [3, 9]
        why = admin.get(f"/api/access/users/{kit['id']}/stations").json()["stations"]
        hidden = next(s for s in why if s["number"] == 8)
        assert hidden["why"] == "It plays programs with the genre horror, which Kid hides"
        # The Admin sees it all, and the access log says what changed.
        assert len(admin.get("/api/v1/stations").json()["stations"]) == 3
        logs = admin.get("/api/logs?access_log=true").json()["text"]
        assert (
            "Ada changed the Viewing Level Kid (movies up to PG, shows up to TV-PG, unrated "
            "hidden, every Media folder, hiding 1 genre)" in logs
        )

        # Allowed for Kit alone: back for Kit (its station stays hidden: an
        # Admin allows the station itself).
        own = {"blocks": {}, "allowTitles": [{"key": "302", "title": "Creaky House"}]}
        put = admin.put(f"/api/access/users/{kit['id']}/viewing", json={"own": own})
        assert put.status_code == 200, put.text
        assert put.json()["own"]["allowTitles"] == [{"key": "302", "title": "Creaky House"}]
        assert movies() == {"300", "302"} and stations() == [3, 9]

        # Hidden for Kit alone, by name: gone, and its station.
        own = {"blocks": {"titles": [{"key": "300", "title": "Picnic"}]}}
        assert (
            admin.put(f"/api/access/users/{kit['id']}/viewing", json={"own": own}).status_code
            == 200
        )
        assert movies() == set() and stations() == [3]
        logs = admin.get("/api/logs?access_log=true").json()["text"]
        assert "Ada set what's hidden and allowed for Kit (hiding 1 title)" in logs


def test_nothing_changes_for_levels_that_dont_hide_by_tags(app, plex):
    """An update to 1.33.0: titles kept without their tags, and Plex not
    answering about them, change no one's stations or Media."""
    with TestClient(app) as admin:
        for number, key in ((8, "302"), (9, "300")):
            made = admin.post("/api/channels", json={"number": number, "sources": [
                {"type": "movie", "ratingKey": key}]})  # fmt: skip
            assert made.status_code == 201, made.text
        admin.portal.call(admin.app.state.ctx.titles.filled)
        assert admin.put("/api/app-libraries", json={"libraries": ["1", "2"]}).status_code == 200
        admin.post("/api/access/users", json={"name": "Ada", "password": "correct horse"})
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        admin.put(f"/api/access/users/{kit['id']}/viewing", json={"level": kid_level(admin)})
        ctx = admin.app.state.ctx
        # (As if kept by 1.32.0: no tags.)
        for key in ("300", "302"):
            old = ctx.titles.get(key)
            ctx.titles._save({key: type(old)(old.kind, old.rating, old.library, old.checked_ms, None)},
                             int(time.time() * 1000))  # fmt: skip
        plex.down = True
        as_kit = sign_in_app(app, KIT)
        plex.down = False
        listed = TestClient(app).get("/api/v1/stations", headers=as_kit).json()["stations"]
        assert [s["number"] for s in listed] == [8, 9]


def test_titles_without_tags_are_asked_about_once_after_starting(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    titles = Titles(db)
    titles._save({"100": Titles_title("show", "TV-G", None)}, 1)
    later = Titles(db)
    assert later.wanted() == ["100"]
    asked: list[list[str]] = []

    async def ask(keys):
        asked.append(keys)
        return {}  # (Plex doesn't have it any more)

    import asyncio

    asyncio.run(later.fill(ask))
    assert asked == [["100"]]  # (asked once, not again and again)
    assert later.wanted() == [] and later.tags("100") is None


def test_someone_with_their_own_limits_only_watches(app):
    """The audit of 1.33.0: on Unrestricted, with titles or a genre hidden
    for them, Kit could still list a Media folder whole and make stations
    from it on the page (the station editor's addresses), there and on the
    public port. Anything hidden for someone makes them watch only, as a
    level with limits does; and so does what's kept for them that can't be
    read."""
    with TestClient(app) as admin:
        admin.post("/api/access/users", json={"name": "Ada", "password": "correct horse"})
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        page = TestClient(app)
        page.post("/api/access/sign-in", json=KIT)
        assert page.get("/api/libraries/2/items").status_code == 200  # (no limits yet)
        own = {"blocks": {"titles": [{"key": "302", "title": "Creaky House"}]}}
        assert (
            admin.put(f"/api/access/users/{kit['id']}/viewing", json={"own": own}).status_code
            == 200
        )
        assert page.get("/api/libraries/2/items").status_code == 403
        assert page.get("/poster/302").status_code == 403
        refused = page.post("/api/channels", json={"number": 11, "name": "Mine", "sources": [
            {"type": "movie", "ratingKey": "302"}]})  # fmt: skip
        assert refused.status_code == 403 and "watch" in refused.json()["detail"]
        # Only titles allowed for them: nothing hidden, so nothing changes.
        own = {"blocks": {}, "allowTitles": [{"key": "302", "title": "Creaky House"}]}
        admin.put(f"/api/access/users/{kit['id']}/viewing", json={"own": own})
        assert page.get("/api/libraries/2/items").status_code == 200
        # What can't be read: watch only, and a warning says so.
        ctx = admin.app.state.ctx
        ctx.db.set_user_blocks(kit["id"], "{not json")
        ctx.viewing.reload()
        assert page.get("/api/libraries/2/items").status_code == 403
        users = admin.get("/api/access/viewing").json()["users"]
        assert users[str(kit["id"])]["ownUnreadable"] is True  # (the page says so)
        assert (
            "What's hidden or allowed for Kit can't be read"
            in admin.get("/api/logs").json()["text"]
        )


def test_names_match_however_unicode_and_spaces_write_them():
    """The audit of 1.33.0: an "Ä" written as A and a mark, as Plex may send
    it, didn't match one typed as a single letter; nor did a label with two
    spaces, since the page's names have one."""
    import unicodedata

    typed = Blocks.from_json({"genres": ["Ärger"], "labels": ["Late  Night"]})
    from_plex = Tags(genres=(unicodedata.normalize("NFD", "ärger"),))
    assert typed.hit("1", from_plex) == "genres"
    assert typed.hit("1", Tags(labels=("late   night",))) == "labels"
    reach = Reach(tagged=True, genres=frozenset({"ärger"}))
    assert typed.meets(reach) == "genres"


def test_odd_blocks_are_refused_not_turned_into_words():
    """The audit of 1.33.0: [null, true, {...}] were kept as the genres
    "None", "True" and "{'a': 1}"."""
    for bad in (
        {"genres": [None]},
        {"genres": [True]},
        {"studios": [{"a": 1}]},
        {"titles": [{"key": 301, "title": "Heist"}]},
        {"titles": [{"key": "301", "title": ["Heist"]}]},
    ):
        with pytest.raises(ValueError):
            Blocks.from_json(bad)


def test_a_level_hides_by_what_titles_are_not_by_title(app):
    """Shows and movies are hidden for one person (What they see), not for a
    level: a level given titles is refused, rather than hiding them where
    the page never shows it."""
    with TestClient(app) as admin:
        admin.post("/api/access/users", json={"name": "Ada", "password": "correct horse"})
        kid = kid_level(admin)
        refused = admin.put(f"/api/access/levels/{kid}", json={
            "name": "Kid", "movieAge": 10, "tvAge": 10, "unrated": False,
            "blocks": {"titles": [{"key": "300", "title": "Picnic"}]},
        })  # fmt: skip
        assert refused.status_code == 400
        assert "What they see" in refused.json()["detail"]


def test_who_might_see_what_changes_only_with_limits(app):
    """The audit of 1.33.0: adding someone who sees everything, or renaming
    someone, made every station's lineup be made again (Viewing.signature
    went by everyone)."""
    with TestClient(app) as admin:
        admin.post("/api/access/users", json={"name": "Ada", "password": "correct horse"})
        viewing = admin.app.state.ctx.viewing
        before = viewing.signature
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        assert viewing.signature == before
        admin.put(f"/api/access/users/{kit['id']}", json={"name": "Kitty"})
        assert viewing.signature == before
        admin.put(f"/api/access/users/{kit['id']}/viewing", json={"level": kid_level(admin)})
        assert viewing.signature != before


def test_new_names_to_hide_by_ask_plex_about_every_titles_tags_again(tmp_path):
    """The audit of 1.33.0: a label added in Plex to a title already asked
    about counted only a week later. Hiding a new name asks again at once,
    and while anyone hides by tags, they're asked again every day."""
    from app import titles as titles_module
    from app.titles import Title
    from app.viewing import Viewing

    db = Database(tmp_path / "db.sqlite")
    titles = Titles(db)
    now = int(time.time() * 1000)
    titles._save({"300": Title("movie", "PG", "1", now, NO_TAGS)}, now)
    viewing = Viewing(db, titles)
    assert titles.wanted() == []  # (no one hides by tags)
    kid = next(lv for lv in viewing.levels() if lv.name == "Kid")
    viewing.save_level(kid.id, "Kid", 10, 10, False, None, Blocks(labels=("Grown-ups",)))
    assert titles.want_tags and titles.wanted() == ["300"]  # (asked again: a new name)
    titles._known["300"] = Title("movie", "PG", "1", _now_ms() + 1, NO_TAGS)  # (asked)
    viewing.save_level(kid.id, "Kid", 10, 10, False, None, Blocks(labels=("Grown-ups",)))
    assert titles.wanted() == []  # (the same names: not again)
    time.sleep(0.01)
    viewing.save_level(kid.id, "Kid", 10, 10, False, None, Blocks(labels=("Grown-ups", "Gore")))
    assert titles.wanted() == ["300"]  # (a new name: asked again at once)
    titles._known["300"] = Title("movie", "PG", "1", _now_ms() + 1, NO_TAGS)  # (asked)
    a_day = _now_ms() + titles_module.TAGS_RECHECK_MS + 1
    assert titles.wanted(a_day) == ["300"]


def _now_ms() -> int:
    return int(time.time() * 1000)


def test_media_on_a_big_folder_answers_in_time_and_keeps_what_plex_said(tmp_path):
    """The audit of 1.33.0: for someone limited by tags, Media asked Plex
    about a whole folder 50 at a time within one 8-second answer, kept
    nothing until all of it was in, and so failed every time on a big
    folder. Now each batch is kept as it comes and carries on after the
    answer, which waits only so long; a title being asked about isn't asked
    about twice; Plex is asked a couple of batches at a time; and (the
    re-check) a big folder's batches beyond the first few wait their turn,
    so a small folder asked about meanwhile isn't held up behind them."""
    import asyncio

    from app import titles as titles_module

    titles = Titles(Database(tmp_path / "db.sqlite"))
    asked: list[list[str]] = []
    at_once = [0, 0]

    async def ask(keys):
        asked.append(keys)
        at_once[0] += 1
        at_once[1] = max(at_once[1], at_once[0])
        await asyncio.sleep(0.2)
        at_once[0] -= 1
        return {k: ("PG", "2", NO_TAGS) for k in keys if k != "599"}  # (Plex lost 599)

    titles.asker = ask
    big = {str(k): "movie" for k in range(600)}
    small = {f"s{k}": "movie" for k in range(30)}

    async def run():
        started = time.monotonic()
        await titles.ensure(big, wait_s=0.3)
        took = time.monotonic() - started
        partly = sum(titles.tags(k) is not None for k in big)
        await titles.ensure(big, wait_s=0.0)  # (a second answer meanwhile: nothing asked twice)
        started = time.monotonic()
        await titles.ensure(small, wait_s=0.8)
        small_took = time.monotonic() - started
        small_known = all(titles.tags(k) is not None for k in small)
        await asyncio.sleep(2.0)  # (the rest carries on, and is kept)
        return took, partly, small_took, small_known

    took, partly, small_took, small_known = asyncio.run(run())
    assert took < 0.38 and partly == 2 * titles_module.ENSURE_AT_ONCE  # (two batches back in time)
    # (Behind at most what was already going and one batch of the rest: the
    # same big folder asked for again didn't go ahead of it.)
    assert small_known and small_took < 0.55
    assert all(titles.tags(k) == NO_TAGS for k in big if k != "599")
    flat = [k for batch in asked for k in batch]
    assert sorted(flat) == sorted([*big, *small]) and len(flat) == len(set(flat))  # (each once)
    assert max(len(b) for b in asked) == titles_module.ENSURE_AT_ONCE
    assert at_once[1] <= titles_module.ENSURE_TURNS

    # Then, on the same event loop as tapiOca's: a title Plex didn't
    # have isn't asked about again for a while; one answer's asks share its
    # wait (Titles.ensure_until); and another big folder, after the first
    # was done, has its rest asked about too (the batches waiting their turn
    # start again).
    other = {f"o{k}": "movie" for k in range(400)}

    async def more():
        await titles.ensure({"599": "movie"}, wait_s=0.1)
        until = titles_module.ensure_until.set(asyncio.get_running_loop().time() + 0.05)
        try:
            started = time.monotonic()
            await titles.ensure({"t1": "movie"}, wait_s=3.0)
            waited = time.monotonic() - started
        finally:
            titles_module.ensure_until.reset(until)
        await titles.ensure(other, wait_s=0.0)
        await asyncio.sleep(1.8)
        return waited

    asked.clear()
    waited = asyncio.run(more())
    assert "599" not in [k for b in asked for k in b] and waited < 0.15
    assert all(titles.tags(k) == NO_TAGS for k in other)


def test_titles_plex_couldnt_answer_about_are_asked_again(tmp_path):
    """When Plex fails, what was being asked about isn't left marked as
    being asked (or it would stay unknown, and hidden, until a restart)."""
    import asyncio

    titles = Titles(Database(tmp_path / "db.sqlite"))
    calls = [0]

    async def ask(keys):
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("Plex is restarting")
        return {k: ("PG", "2", NO_TAGS) for k in keys}

    titles.asker = ask

    async def run():
        await titles.ensure({"300": "movie"}, wait_s=1.0)
        assert titles.tags("300") is None
        await titles.ensure({"300": "movie"}, wait_s=1.0)

    asyncio.run(run())
    assert calls[0] == 2 and titles.tags("300") == NO_TAGS


def test_whats_allowed_for_someone_and_whats_hidden_for_them(app):
    """docs/users.md's rules 2, 3 and 7: a show or movie hidden for someone
    wins over one allowed for them; one allowed for them is shown even if a
    genre hidden for them would hide it (the page says the same)."""
    kid = Level(4, "Kid", None, None, True, None, "", Blocks())
    own = Person(Blocks(genres=("Horror",), titles=(("301", "Heist"),)),
                 (("301", "Heist"), ("302", "Creaky House")))  # fmt: skip
    kit = Viewer(kid, everything=False, own=own)
    assert not kit.sees(Judged(False, 0, "2", True, "301", HORROR))
    assert kit.sees(Judged(False, 0, "2", True, "302", HORROR))
    assert not kit.sees(Judged(False, 0, "2", True, "303", HORROR))


def test_a_restart_doesnt_ask_plex_about_every_titles_tags_again(tmp_path, monkeypatch):
    """The re-check of 1.33.0's audit: while anyone hid by tags, every
    restart asked Plex about every show and movie kept; and if the clock
    stepped back, `fill` asked about the same titles again and again. Now a
    restart asks only about titles whose tags aren't known, and `fill` asks
    about each title once."""
    import asyncio

    from app import titles as titles_module
    from app.titles import Title

    db = Database(tmp_path / "db.sqlite")
    now = _now_ms()
    before = now - 1_000  # (asked about before the restart)
    Titles(db)._save({"300": Title("movie", "PG", "1", before, NO_TAGS),
                      "301": Title("movie", "R", "1", before, None)}, before)  # fmt: skip
    later = Titles(db)  # (tapiOca started again)
    later.want_tags = True
    assert later.wanted() == ["301"]

    clock = [now + 10_000]

    def backwards() -> int:
        clock[0] -= 1_000
        return clock[0]

    later.refresh_tags()  # (every title wanted again, as of now + 10 s)
    later._refresh_ms = now + 10_000
    monkeypatch.setattr(titles_module, "_now", backwards)
    asked: list[str] = []

    async def ask(keys):
        asked.extend(keys)
        await asyncio.sleep(0)
        return {k: ("PG", "1", NO_TAGS) for k in keys}

    asyncio.run(asyncio.wait_for(later.fill(ask), 2.0))
    assert sorted(asked) == ["300", "301"]
    assert later.wanted() == []  # (a refresh "later" than the clock counts as now)


def test_a_refresh_not_done_before_a_restart_still_happens(tmp_path):
    """The final check of 1.33.0: hiding a new name asked about every
    title's tags again, but a restart before that was done forgot it, and
    the old tags counted for up to a day."""
    from app.titles import Title

    db = Database(tmp_path / "db.sqlite")
    now = _now_ms()
    titles = Titles(db)
    titles._save({"300": Title("movie", "PG", "1", now - 10 * 3_600_000, NO_TAGS)}, now)
    titles.want_tags = True
    titles.refresh_tags()
    assert titles.wanted() == ["300"]
    later = Titles(db)  # (restarted)
    later.want_tags = True
    assert later.wanted() == ["300"]


def test_one_media_answer_shares_its_wait_for_plex(app, monkeypatch):
    """The re-check of 1.33.0's fixes: Home asked about each row's titles in
    turn, each waiting its own few seconds, and could run out of time (an
    answer of "can't reach Plex"). Now Home asks about all it shows at once,
    and every ask in one answer shares one deadline, within its own."""
    import asyncio

    from app import titles as titles_module

    seen: list[tuple[float | None, list[str], float]] = []
    real = titles_module.Titles.ensure

    async def ensure(self, wanted, wait_s=titles_module.ENSURE_S):
        seen.append((titles_module.ensure_until.get(), list(wanted),
                     asyncio.get_running_loop().time()))  # fmt: skip
        await real(self, wanted, wait_s)

    monkeypatch.setattr(titles_module.Titles, "ensure", ensure)
    with TestClient(app) as admin:
        assert admin.put("/api/app-libraries", json={"libraries": ["1", "2"]}).status_code == 200
        admin.post("/api/access/users", json={"name": "Ada", "password": "correct horse"})
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        kid = kid_level(admin)
        admin.put(f"/api/access/users/{kit['id']}/viewing", json={"level": kid})
        admin.put(f"/api/access/levels/{kid}", json={
            "name": "Kid", "movieAge": 10, "tvAge": 10, "unrated": False,
            "blocks": {"genres": ["horror"]}})  # fmt: skip
        as_kit = sign_in_app(app, KIT)
        seen.clear()
        home = TestClient(app).get("/api/internal/home", headers=as_kit)
        assert home.status_code == 200, home.text
        assert seen, "Home asks about its titles' tags"
        untils = {until for until, _, _ in seen}
        assert len(untils) == 1 and None not in untils  # (one deadline for the answer)
        (until,) = untils
        assert until <= seen[0][2] + titles_module.ENSURE_S + 0.1
        # (The first ask is everything Home shows: both rows' titles.)
        assert {"100", "300", "302"} <= set(seen[0][1])


def test_asking_again_for_a_folder_waiting_its_turn_shows_its_first_titles(tmp_path):
    """The last check of 1.33.0: a big Media folder whose rest was all
    waiting behind another folder's, asked for again, had nothing being
    asked about to wait for, and the answer failed ("can't reach Plex").
    Now its first batch, in the order it's shown, is asked about then."""
    import asyncio

    titles = Titles(Database(tmp_path / "db.sqlite"))

    async def ask(keys):
        await asyncio.sleep(0.1)
        return {k: ("PG", "2", NO_TAGS) for k in keys}

    titles.asker = ask
    movies = {f"m{k}": "movie" for k in range(1000)}
    shows = {f"s{k}": "show" for k in range(600)}

    async def run():
        await titles.ensure(movies, wait_s=0.0)
        await titles.ensure(shows, wait_s=0.0)
        # (Until the shows' first batches are back; their rest waits.)
        for _ in range(100):
            known = sum(titles.tags(k) is not None for k in shows)
            if known >= 200:
                break
            await asyncio.sleep(0.05)
        await titles.ensure(shows, wait_s=1.0)
        return known, sum(titles.tags(k) is not None for k in shows)

    before, after = asyncio.run(run())
    assert before == 200 and after >= before + 50


def test_a_clock_that_stepped_back_once_doesnt_keep_every_title_due(tmp_path, monkeypatch):
    """The last check of 1.33.0: with the clock an hour fast when a new name
    was hidden, then set right, every title was due at every look (and,
    kept, after a restart) until the clock caught up."""
    import asyncio

    from app import titles as titles_module
    from app.titles import Title

    db = Database(tmp_path / "db.sqlite")
    now = _now_ms()
    titles = Titles(db)
    titles._save({"300": Title("movie", "PG", "1", now - 60_000, NO_TAGS)}, now)
    titles.want_tags = True
    clock = [now + 3_600_000]  # (an hour fast)
    monkeypatch.setattr(titles_module, "_now", lambda: clock[0])
    titles.refresh_tags()
    clock[0] = now  # (set right)
    assert titles.wanted() == ["300"]

    async def ask(keys):
        clock[0] += 1_000
        return {k: ("PG", "1", NO_TAGS) for k in keys}

    asyncio.run(titles.fill(ask))
    clock[0] += 60_000
    assert titles.wanted() == []
    later = Titles(db)  # (restarted)
    later.want_tags = True
    assert later.wanted() == []
