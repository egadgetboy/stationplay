"""What each user can see (see viewing.py, titles.py and ratings.py): ratings
read as ages, the ratings of what's on each station, Viewing Levels, and
whether a level allows a title or a station."""

from __future__ import annotations

import asyncio

import pytest

from app import ratings, viewing
from app.access import ADMIN, USER
from app.catalog import Entry
from app.db import Database, Item
from app.titles import RECHECK_MS, Judged, Titles


@pytest.mark.parametrize(
    ("rating", "age"),
    [
        ("G", 0), ("TV-Y", 0), ("TV-G", 0), ("TV-Y7", 7), ("TV-Y7-FV", 7), ("PG", 10),
        ("TV-PG", 10), ("PG-13", 13), ("TV-14", 14), ("R", 17), ("TV-MA", 17), ("NC-17", 18),
        ("us/PG-13", 13), ("gb/U", 0), ("gb/PG", 10), ("gb/12A", 12), ("gb/15", 15),
        ("gb/18", 18), ("de/0", 0), ("de/16", 16), ("fr/-12", 12), ("au/M", 15),
        ("au/MA15+", 15), ("au/R18+", 18), ("ca/14A", 14), ("ca/13+", 13), ("nl/AL", 0),
        ("FSK 12", 12), ("16+", 16), ("jp/R15+", 15),
        # Unrated: none at all, said plainly, or not known here.
        ("", None), (None, None), ("NR", None), ("Not Rated", None), ("Unrated", None),
        ("Approved", None), ("M", None), ("xx/Q", None), ("99", None),
    ],
)  # fmt: skip
def test_ratings_are_read_as_ages(rating, age):
    assert ratings.age(rating) == age


def test_an_episode_is_judged_by_the_stricter_rating():
    assert ratings.stricter(10, 14) == 14
    assert ratings.stricter(None, 14) == 14
    assert ratings.stricter(10, None) == 10
    assert ratings.stricter(None, None) is None


def episode(key, show, rating=None, library="1"):
    return Item(
        0,
        0,
        60_000,
        key,
        "episode",
        f"Ep {key}",
        show.title(),
        show,
        1,
        1,
        rating=rating,
        library=library,
    )


def movie(key, rating, library="2"):
    return Item(0, 0, 60_000, key, "movie", f"Movie {key}", rating=rating, library=library)


def asker(answers):
    asked = []

    async def ask(keys):
        asked.append(list(keys))
        return {k: answers[k] for k in keys if k in answers}

    return ask, asked


def test_titles_note_what_plex_sent_and_ask_about_shows(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    titles = Titles(db)
    titles.note([episode("e1", "s1"), episode("e2", "s1", rating="TV-MA"), movie("m1", "PG")])
    # A movie's rating came with it; a show's must be asked for.
    assert titles.judge(movie("m1", None)) == Judged(False, 10, "2", True)
    assert not titles.judge(episode("e1", "s1")).known
    assert titles.wanted() == ["s1"]
    ask, asked = asker({"s1": ("TV-PG", "1")})
    asyncio.run(titles.fill(ask))
    assert asked == [["s1"]]
    assert titles.judge(episode("e1", "s1")) == Judged(True, 10, "1", True)
    # (An episode with a stricter rating of its own.)
    assert titles.judge(episode("e2", "s1")) == Judged(True, 17, "1", True)
    assert titles.wanted() == []
    # Kept: a restart knows them.
    again = Titles(db)
    assert again.judge(episode("e2", "s1")).age == 17
    # Asked again a week later.
    assert again.wanted(now=titles.get("s1").checked_ms + RECHECK_MS) == ["s1"]


def test_a_movie_whose_library_isnt_known_is_asked_about(tmp_path):
    titles = Titles(Database(tmp_path / "db.sqlite"))
    titles.note([movie("m1", "R", library=None)])
    assert titles.wanted() == ["m1"]
    ask, _ = asker({"m1": ("R", "7")})
    asyncio.run(titles.fill(ask))
    assert titles.judge(movie("m1", None)).library == "7"
    # One Plex doesn't have any more is left as it was (and not asked about
    # again and again).
    titles.note([movie("m2", "G", library=None)])
    ask, asked = asker({})
    asyncio.run(titles.fill(ask))
    assert asked == [["m2"]] and titles.wanted() == []


def level(movie_age=None, tv_age=None, unrated=True, libraries=None):
    return viewing.Level(1, "Test", movie_age, tv_age, unrated, libraries)


def test_a_level_judges_titles_by_library_then_rating():
    kid = level(10, 10, unrated=False, libraries=frozenset({"1", "2"}))
    assert kid.allows(Judged(True, 10, "1", True))
    assert not kid.allows(Judged(True, 14, "1", True))  # TV-14
    assert kid.allows(Judged(False, 10, "2", True))  # PG
    assert not kid.allows(Judged(False, 13, "2", True))  # PG-13
    assert not kid.allows(Judged(True, None, "1", True))  # unrated
    assert not kid.allows(Judged(True, 0, "9", True))  # another library
    assert not kid.allows(Judged(True, 0, "1", False))  # not known yet
    # A level without limits allows everything, known or not.
    assert level().allows(Judged(True, None, "", False))


def test_a_station_needs_what_everything_on_it_needs(tmp_path):
    titles = Titles(Database(tmp_path / "db.sqlite"))
    titles.note([episode("e1", "s1"), movie("m1", "PG-13"), movie("m2", "NR")])
    reach = viewing.reach_of([episode("e1", "s1"), movie("m1", None)], titles)
    assert not reach.known  # (the show's rating hasn't been asked for)
    asyncio.run(titles.fill(asker({"s1": ("TV-Y7", "1"), "m1": ("PG-13", "2")})[0]))
    reach = viewing.reach_of([episode("e1", "s1"), movie("m1", None)], titles)
    assert reach == viewing.Reach(True, 13, 7, False, False, frozenset({"1", "2"}))
    assert level(13, 7).allows_reach(reach)
    assert not level(10, 14).allows_reach(reach)  # the movie's PG-13
    assert not level(None, None, libraries=frozenset({"1"})).allows_reach(reach)
    with_unrated = viewing.reach_of([movie("m2", None)], titles)
    assert with_unrated.movie_unrated
    assert not level(17, 17, unrated=False).allows_reach(with_unrated)
    assert level(None, None).allows_reach(viewing.Reach(known=False))


def test_an_episode_from_the_library_is_judged_by_its_show():
    show = Entry("s1", "show", "Show", library="1", content_rating="TV-14")
    ep = Entry("e1", "episode", "Ep", library="1", show_key="s1", content_rating="TV-PG")
    assert viewing.judge_entry(ep, show) == Judged(True, 14, "1", True)
    assert not viewing.judge_entry(ep).known
    assert viewing.judge_entry(show) == Judged(True, 14, "1", True)
    assert viewing.judge_entry(
        Entry("m1", "movie", "Movie", library="2", content_rating="R")
    ) == Judged(False, 17, "2", True)


def test_levels_come_with_stationplay_and_can_be_changed(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    v = viewing.Viewing(db, Titles(db))
    names = [lv.name for lv in v.levels()]
    assert names == ["Unrestricted", "Teen", "Kid", "Young Child"]
    kid = next(lv for lv in v.levels() if lv.builtin == viewing.KID)
    assert (kid.movie_age, kid.tv_age, kid.unrated, kid.libraries) == (10, 10, False, None)
    # Renamed and changed, kept, and not made again after a restart.
    v.save_level(kid.id, "Kids", 10, 7, False, ["1"])
    again = viewing.Viewing(db, Titles(db))
    assert [lv.name for lv in again.levels()] == ["Unrestricted", "Teen", "Kids", "Young Child"]
    assert again.level(kid.id).libraries == frozenset({"1"})
    # Unrestricted stays as it is.
    free = again.level(None)
    assert free.builtin == viewing.UNRESTRICTED and not free.limited
    with pytest.raises(ValueError, match="stays as it is"):
        again.save_level(free.id, "Adults", 13, 14, False, None)
    with pytest.raises(ValueError, match="stays as it is"):
        again.remove_level(free.id)
    # Teen can be removed (no one's on it), and isn't made again.
    teen = next(lv for lv in again.levels() if lv.builtin == viewing.TEEN)
    again.remove_level(teen.id)
    assert [lv.name for lv in viewing.Viewing(db, Titles(db)).levels()] == [
        "Unrestricted", "Kids", "Young Child"
    ]
    # An Admin's own: named once, and removed only when no one's on it.
    grand = again.save_level(None, "Grandparents", 13, 14, True, None)
    with pytest.raises(ValueError, match="already a Viewing Level called"):
        again.save_level(None, "grandparents", 0, 0, True, None)
    ada = db.add_user("Ada", "x", USER, 0, None)
    again.set_user(ada, grand.id, None)
    with pytest.raises(ValueError, match="Choose another level for everyone on Grandparents"):
        again.remove_level(grand.id)
    again.set_user(ada, None, None)
    again.remove_level(grand.id)
    assert "Grandparents" not in [lv.name for lv in again.levels()]


def test_what_someone_sees(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    titles = Titles(db)
    v = viewing.Viewing(db, titles)
    kid = next(lv for lv in v.levels() if lv.builtin == viewing.KID)
    admin = db.add_user("Ada", "x", ADMIN, 0, None)
    bo = db.add_user("Bo", "x", USER, 0, None)
    # Signing in off, an Admin, and anyone on Unrestricted: everything.
    assert v.viewer(None).everything and v.viewer(admin).everything and v.viewer(bo).everything
    v.set_user(admin, kid.id, None)
    assert v.viewer(admin).everything  # (an Admin always)
    v.set_user(bo, kid.id, None)
    seen = v.viewer(bo)
    assert not seen.everything and seen.level.id == kid.id
    assert seen.sees(Judged(True, 10, "1", True)) and not seen.sees(Judged(True, 17, "1", True))


def test_an_early_adult_level_becomes_unrestricted(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    db.add_level("Adult", None, None, True, None, "adult")
    db.add_level("Teen", 13, 14, False, None, "teen")
    v = viewing.Viewing(db, Titles(db))
    assert [(lv.name, lv.builtin) for lv in v.levels()] == [
        ("Unrestricted", "unrestricted"), ("Teen", "teen")
    ]
