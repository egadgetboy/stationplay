"""Limits by what a title is (1.33.0, see docs/users.md): a Viewing Level, or
one person, hides titles by their genres, tags (Plex's labels), collections
and studio, or by name; a title can be allowed for one person. Hidden
everywhere StationPlay lists or plays things, judged by a title's tags
whole (lists carry only a few genres), and what isn't known yet is hidden
from anyone limited by tags. A StationPlay where no one hides by them
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
        "StationPlay is still asking Plex what its programs are"
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
