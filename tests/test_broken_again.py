"""Going through the broken-files list again: telling a program Plex removed
from one it added again under a new key, and settling what was found. (The
whole of it, with real files and checks, is in test_e2e.py.)"""

from __future__ import annotations

import json

import pytest

from app.broken import CHECK, DEEP_SCAN, OPENING, PLAYING, BrokenFiles, found_by
from app.db import Item
from app.jobs import OnStations, same_program
from app.plex import Lookups, PlexClient, PlexError, telling_title
from tests.fakeplex import FakePlex
from tests.helpers import like_plex


def ep(key, show, season, episode, title="Ep", year=1965, path=None) -> Item:
    return Item(0, 0, 1_000, key, "episode", title, show, "100", season, episode, year,
                file_path=path)  # fmt: skip


def movie(key, title, year, path=None) -> Item:
    return Item(0, 0, 1_000, key, "movie", title, year=year, file_path=path)


def entry_for(item: Item, **more) -> dict:
    return {
        "ratingKey": item.rating_key,
        "title": item.title,
        "show": item.show_title,
        "season": item.season,
        "episode": item.episode,
        "year": item.year,
        "file": item.file_path,
        **more,
    }


def test_the_same_program_under_a_new_key():
    old = entry_for(ep("201", "Bonanza", 10, 29, "The Fence", 1969, "/tv/B - S10E29 - nodlabs.mkv"))
    # Renamed, only its capital letters changed: the same file.
    assert same_program(old, ep("901", "Other", 1, 1, "x", None, "/tv/B - S10E29 - NODLABS.mkv"))
    # The same episode of the same show, from the same year.
    assert same_program(old, ep("902", "bonanza", 10, 29, "The Fence", 1969, "/new/path.mkv"))
    # Another episode, another show, or another year (a remake) isn't.
    assert not same_program(old, ep("903", "Bonanza", 10, 30, "The Fence", 1969))
    assert not same_program(old, ep("904", "Bonanza (2025)", 10, 29, "The Fence", 1969))
    assert not same_program(old, ep("905", "Bonanza", 10, 29, "The Fence", 2026))
    # With no year on either side, the episode's title must match too.
    no_year = {**old, "year": None}
    assert same_program(no_year, ep("906", "Bonanza", 10, 29, "the fence", None))
    assert not same_program(no_year, ep("907", "Bonanza", 10, 29, "Rose", None))
    # A movie: the same title and year, both known.
    film = entry_for(movie("301", "Dune", 1984))
    assert same_program(film, movie("911", "DUNE", 1984))
    assert not same_program(film, movie("912", "Dune", 2021))
    assert not same_program({**film, "year": None}, movie("913", "Dune", 1984))
    assert not same_program(film, ep("914", "Dune", 1, 1, "Dune", 1984))


def test_on_stations_finds_it_again_but_never_itself():
    on = OnStations()
    for item in (
        ep("201", "Bonanza", 1, 1, path="/tv/a.mkv"),
        ep("202", "Bonanza", 1, 2, path="/tv/b.mkv"),
        movie("301", "Dune", 1984, "/movies/dune.mkv"),
    ):
        on.add(item)
    assert on.again(entry_for(ep("201", "Bonanza", 1, 1, path="/tv/a.mkv"))) is None
    assert on.again(entry_for(ep("291", "Bonanza", 1, 2))).rating_key == "202"
    assert on.again(entry_for(ep("292", "Bonanza", 1, 3, path="/TV/A.MKV"))).rating_key == "201"
    assert on.again(entry_for(movie("391", "dune", 1984))).rating_key == "301"
    assert on.again(entry_for(movie("392", "Dune", 2021))) is None


def test_how_a_problem_was_found(tmp_path):
    store = BrokenFiles(tmp_path / "broken.json")
    store.record(ep("201", "S", 1, 1), "no sound", 1, problem="damaged", found=CHECK)
    store.record(ep("202", "S", 1, 2), "file not found: /x", 1, found=OPENING)
    store.record(ep("203", "S", 1, 3), "ffmpeg failed", 1)
    got = {e["ratingKey"]: found_by(e) for e in store.entries()}
    assert got == {"201": CHECK, "202": OPENING, "203": PLAYING}
    # Entries from before it was written down: their reason says, for the
    # checks; anything else was playing.
    assert found_by({"reason": "Check: no longer in Plex"}) == CHECK
    assert found_by({"reason": "Deep scan: the picture breaks up"}) == DEEP_SCAN
    assert found_by({"reason": "cannot open file"}) == PLAYING
    assert found_by({"reason": "x", "foundBy": "something else"}) == PLAYING


def test_settling_what_was_found(tmp_path):
    path = tmp_path / "broken.json"
    store = BrokenFiles(path)
    for n in (1, 2, 3, 4):
        store.record(ep(f"20{n}", "S", 1, n), "bad", 1)
    seen = {e["ratingKey"]: e["lastFailed"] for e in store.entries()}
    # 204 failed again meanwhile: it's left as it now is.
    doc = json.loads(path.read_text())
    for f in doc["files"]:
        if f["ratingKey"] == "204":
            f["lastFailed"] = "2099-01-01T00:00:00+00:00"
    path.write_text(json.dumps(doc))
    taken = store.settle(
        seen,
        cleared={"201", "204"},
        still={"202": {"reason": "Check: removed from Plex"}, "203": {}},
    )
    assert taken == ["201"]
    left = {e["ratingKey"]: e for e in BrokenFiles(path).entries()}
    assert set(left) == {"202", "203", "204"}
    assert left["202"]["reason"] == "Check: removed from Plex" and left["202"]["lastChecked"]
    assert left["203"]["reason"] == "bad" and left["203"]["lastChecked"]
    assert "lastChecked" not in left["204"] and left["204"]["failures"] == 1
    # (Something gone from the list meanwhile is nothing to settle.)
    assert store.settle({"999": "x"}, {"999"}, {}) == []


async def test_plex_says_whether_a_program_was_removed_or_added_again():
    plex = FakePlex()
    plex.add_section("2", "Movies", "movie")
    plex.add_show("100", "Bonanza", year=1959)
    for n in (1, 2):
        plex.add_episode(f"20{n}", "100", 10, n, f"Ep {n}", f"/tv/b{n}-nodlabs.mkv", 60_000)
    plex.add_movie("301", "Dune", "/movies/dune.mkv", 60_000, year=1984, section="2")
    client = PlexClient("http://plex.test", "token", transport=like_plex(plex))
    old_201 = ep("201", "Bonanza", 10, 1, "Ep 1", 1965, "/tv/b1-nodlabs.mkv")
    old_202 = ep("202", "Bonanza", 10, 2, "Ep 2", 1965, "/tv/b2-nodlabs.mkv")
    old_dune = movie("301", "Dune", 1984)
    # 201's file renamed: Plex added it again under a new key. 202 removed.
    plex.remove("201")
    plex.add_episode("211", "100", 10, 1, "Ep 1", "/tv/b1-NODLABS.mkv", 60_000)
    plex.remove("202")
    shows = Lookups()
    assert await client.find_again(old_201, shows) == "211"
    assert await client.find_again(old_202, shows) is None
    asked = len(plex.requests)
    assert await client.find_again(old_201, shows) == "211"
    assert len(plex.requests) == asked  # (what Plex said, kept)
    # The show added again under a new key too: followed by its name.
    plex.add_show("110", "Bonanza", year=1959)
    plex.add_episode("212", "110", 10, 1, "Ep 1", "/tv/b1.mkv", 60_000)
    plex.remove("211")
    del plex.shows["100"]
    assert await client.find_again(old_201) == "212"
    # A movie: the same title and year.
    plex.remove("301")
    assert await client.find_again(old_dune) is None
    plex.add_movie("311", "Dune", "/movies/Dune (1984).mkv", 60_000, year=1984, section="2")
    plex.add_movie("312", "Dune", "/movies/Dune (2021).mkv", 60_000, year=2021, section="2")
    assert await client.find_again(old_dune) == "311"
    # Plex away: it can't say (not "removed").
    plex.down = True
    with pytest.raises(PlexError):
        await client.find_again(old_202)
    await client.close()


async def test_a_program_moved_to_another_show_of_its_title_is_found_there():
    """Files moved to another folder or drive that Plex sees as another show
    (the same show in another library, say): the program is found there, in
    any library, but only with proof it's the same one: the same file name
    (its capital letters aside), or a show matched to the same TVDB show."""
    plex = FakePlex()
    plex.add_section("3", "TV Parents", "show")
    teens = "/media/tv/tv-classics.teens/Bonanza (1959)"
    parents = "/media/tv/tv-classics/Bonanza (1959) {tvdb-73378}"
    name = "Bonanza (1959) - S01E01 - A Rose for Lotta [Bluray-1080p][FLAC 2.0][x264]-{}.mkv"
    # TV Teens' Bonanza, which still has S10E29; TV Parents' has the rest.
    plex.add_show("100", "Bonanza", year=1959)
    plex.add_episode("210", "100", 10, 29, "The Fence", f"{teens}/S10E29.mkv", 60_000)
    plex.add_show("500", "Bonanza", year=1959, section="3")
    plex.add_episode("501", "500", 1, 1, "A Rose for Lotta",
                     f"{parents}/{name.format('BROADCAST')}", 60_000)  # fmt: skip
    plex.add_episode("502", "500", 1, 2, "Death on Sun Mountain", f"{parents}/e2.mkv", 60_000)
    plex.add_episode("503", "500", 1, 3, "The Newcomers", f"{parents}/e3.mkv", 60_000)
    # Another show of that title, not the same one (a remake, say).
    plex.add_show("700", "Bonanza", year=2030, section="3")
    plex.add_episode("701", "700", 1, 3, "The Newcomers", "/media/remake/e3.mkv", 60_000)
    client = PlexClient("http://plex.test", "token", transport=like_plex(plex))

    def gone(key, season, episode, path):
        return Item(0, 0, 1_000, key, "episode", "Ep", "Bonanza", "100", season, episode, 1959,
                    file_path=path)  # fmt: skip

    # The same file name (only its capital letters changed): found.
    s01e01 = gone("201", 1, 1, f"{teens}/{name.format('broadcast')}")
    assert await client.find_again(s01e01) == "501"
    # A different name, and nothing says it's the same show: not found.
    s01e02 = gone("202", 1, 2, f"{teens}/Bonanza - S01E02 [DVD].mkv")
    assert await client.find_again(s01e02) is None
    # Both shows matched to the same TVDB show: found, whatever the name.
    plex.shows["100"]["Guid"] = [{"id": "tvdb://73378"}]
    plex.shows["500"]["Guid"] = [{"id": "tvdb://73378"}]
    plex.shows["700"]["Guid"] = [{"id": "tvdb://999999"}]
    assert await client.find_again(s01e02) == "502"
    # ...but never in a show matched to another one (the remake's S01E03).
    del plex.shows["500"]["Guid"]
    s01e03 = gone("203", 1, 3, f"{teens}/Bonanza - S01E03 [DVD].mkv")
    assert await client.find_again(s01e03) is None
    # The same file in two libraries (the same show in both): either will do.
    plex.add_show("800", "Bonanza", year=1959, section="3")
    plex.add_episode("801", "800", 1, 1, "A Rose for Lotta",
                     f"{parents}/{name.format('BROADCAST')}", 60_000)  # fmt: skip
    assert await client.find_again(s01e01) in ("501", "801")
    # What Plex said is kept while going through a list.
    looked = Lookups()
    assert await client.find_again(s01e01, looked) in ("501", "801")
    asked = len(plex.requests)
    assert await client.find_again(s01e02, looked) is None  # (no proof now)
    assert len(plex.requests) == asked
    await client.close()


async def test_a_station_follows_its_show_into_the_library_it_was_in():
    """A station's show gone from under its key is followed by its title:
    when more than one show has it (one in TV Teens and one in TV Parents,
    say), the one in the library the station's show was in."""
    plex = FakePlex()
    plex.add_section("3", "TV Parents", "show")
    plex.add_show("100", "Bonanza", year=1959)  # (TV Teens: library 1)
    plex.add_episode("201", "100", 1, 1, "A Rose for Lotta", "/teens/e1.mkv", 60_000)
    plex.add_show("500", "Bonanza", year=1959, section="3")
    plex.add_episode("501", "500", 1, 1, "A Rose for Lotta", "/parents/e1.mkv", 60_000)
    for key, section in (("201", "1"), ("501", "3")):
        plex.episodes[key]["librarySectionID"] = section
    client = PlexClient("http://plex.test", "token", transport=like_plex(plex))
    source = {"type": "show", "ratingKey": "100", "title": "Bonanza"}
    assert [i.rating_key for i in await client.items_for_source(source)] == ["201"]
    # TV Teens' Bonanza added again under a new key: followed there.
    plex.remove("201")
    del plex.shows["100"]
    plex.add_show("110", "Bonanza", year=1959)
    plex.add_episode("211", "110", 1, 1, "A Rose for Lotta", "/teens/e1.mkv", 60_000)
    plex.episodes["211"]["librarySectionID"] = "1"
    assert [i.rating_key for i in await client.items_for_source(source)] == ["211"]
    # Gone from TV Teens altogether: followed to the only one left.
    plex.remove("211")
    del plex.shows["110"]
    assert [i.rating_key for i in await client.items_for_source(source)] == ["501"]
    # Not knowing which library it was in, two of that title can't be told
    # apart: the station says so.
    plex.add_show("120", "Bonanza", year=1959)
    plex.add_episode("221", "120", 1, 1, "A Rose for Lotta", "/teens/e1.mkv", 60_000)
    fresh = PlexClient("http://plex.test", "token", transport=like_plex(plex))
    with pytest.raises(PlexError, match="2 shows with that title"):
        await fresh.items_for_source({"type": "show", "ratingKey": "100", "title": "Bonanza"})
    await client.close()
    await fresh.close()


async def test_a_moved_show_is_followed_by_the_stations_own_files():
    """Not knowing which library a station's show was in (it moved before
    that was kept), the one of its title with the station's files is
    followed; several with the very same files (one folder in two
    libraries) are the same show; ones that differ aren't chosen between."""
    plex = FakePlex()
    for key, name in (("3", "TV Parents"), ("4", "TV Others")):
        plex.add_section(key, name, "show")

    def bonanza(show: str, section: str, folder: str, episodes=(1, 2)) -> None:
        plex.add_show(show, "Bonanza", year=1959, section=section)
        for n in episodes:
            key = f"{show}{n}"
            plex.add_episode(key, show, 1, n, f"Ep {n}", f"{folder}/Bonanza - S01E0{n}.mkv", 60_000)
            plex.episodes[key]["librarySectionID"] = section

    bonanza("110", "1", "/media/tv-classics.teens/Bonanza")  # TV Teens
    bonanza("120", "3", "/media/tv-classics.teens/Bonanza")  # TV Parents, the same folder
    bonanza("130", "4", "/media/other/Bonanza", episodes=(7,))  # another copy
    theirs = {"bonanza - s01e01.mkv", "bonanza - s01e02.mkv"}  # (as at /media/tv-classics/...)
    source = {"type": "show", "ratingKey": "100", "title": "Bonanza"}  # (gone)

    client = PlexClient("http://plex.test", "token", transport=like_plex(plex))
    with pytest.raises(PlexError, match="3 shows with that title"):
        await client.items_for_source(source)  # (nothing to tell them apart by)
    client.known_files = lambda key: theirs if key == "100" else set()
    # TV Teens and TV Parents have the very same files: either will do.
    assert [i.rating_key for i in await client.items_for_source(source)] == ["1101", "1102"]
    assert client.libraries["100"] == "1"  # (and it's kept from now on)

    # Only one has the station's files.
    fresh = PlexClient("http://plex.test", "token", transport=like_plex(plex))
    fresh.known_files = client.known_files
    plex.remove("1101")
    plex.remove("1102")
    del plex.shows["110"]
    assert [i.rating_key for i in await fresh.items_for_source(source)] == ["1201", "1202"]

    # Two with the station's files that differ otherwise (TV Parents has
    # another season): not for StationPlay to choose.
    bonanza("140", "4", "/media/tv-classics.teens/Bonanza", episodes=(1, 2, 3))
    third = PlexClient("http://plex.test", "token", transport=like_plex(plex))
    third.known_files = client.known_files
    with pytest.raises(PlexError, match="shows with that title"):
        await third.items_for_source(source)
    for c in (client, fresh, third):
        await c.close()


def test_the_app_says_which_files_its_stations_have(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app, known_files

    fp = FakePlex()
    fp.add_show("100", "Bonanza", year=1959)
    fp.add_episode("201", "100", 1, 1, "Ep", "/tv/Bonanza/Bonanza - S01E01 - NODLABS.mkv", 60_000)
    fp.add_movie("301", "Dune", "/movies/Dune (1984).mkv", 60_000, year=1984)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=like_plex(fp)),
    )
    with TestClient(app) as c:
        made = c.post("/api/channels", json={"number": 5, "sources": [
            {"type": "show", "ratingKey": "100", "title": "Bonanza"},
            {"type": "movie", "ratingKey": "301", "title": "Dune"}]})  # fmt: skip
        assert made.status_code == 201, made.text
        ctx = app.state.ctx
        assert known_files(ctx, "100") == {"bonanza - s01e01 - nodlabs.mkv"}
        assert known_files(ctx, "301") == {"dune (1984).mkv"}
        assert known_files(ctx, "999") == set()
        assert ctx.plex.known_files("100") == known_files(ctx, "100")


async def test_a_replaced_file_in_another_show_is_found_by_its_episode_title():
    """A file replaced by a better one under another name, in a show of the
    same title (its own gone from Plex): found by its season, episode and
    episode title, from the same year; never by a title like "Episode 33",
    nor from another year."""
    plex = FakePlex()
    plex.add_section("3", "TV Parents", "show")
    plex.add_show("500", "Bonanza", year=1959, section="3")
    plex.add_show("600", "Bonanza", year=1959, section="3")  # (the same, in another library)
    new = "/tv/tv-classics/Bonanza (1959) {tvdb-73378}/Bonanza (1959) - S05E33 - Triangle [SDTV][AAC 1.0][x265].mp4"
    plex.add_episode("533", "500", 5, 33, "Triangle", new, 60_000)
    plex.add_episode("534", "500", 5, 34, "Episode 34", "/tv/e34.mp4", 60_000)
    plex.add_episode("633", "600", 5, 33, "Triangle", new, 60_000)
    for key in ("533", "534", "633"):
        plex.episodes[key]["year"] = 1964
    client = PlexClient("http://plex.test", "token", transport=like_plex(plex))
    old = "/tv/tv-classics.teens/Bonanza (1959)/Bonanza (1959) - S05E33 - Triangle [DVD][MP3 1.0][XviD]-nodlabs.avi"
    # (Its own show, 100, is gone from Plex.)
    s05e33 = Item(0, 0, 1_000, "233", "episode", "Triangle", "Bonanza", "100", 5, 33, 1964,
                  file_path=old)  # fmt: skip
    assert await client.find_again(s05e33) in ("533", "633")
    # A title that doesn't tell episodes apart is no proof.
    s05e34 = Item(0, 0, 1_000, "234", "episode", "Episode 34", "Bonanza", "100", 5, 34, 1964,
                  file_path="/tv/old/e34.avi")  # fmt: skip
    assert await client.find_again(s05e34) is None
    # Nor is the same title from another year.
    other_year = Item(0, 0, 1_000, "233", "episode", "Triangle", "Bonanza", "100", 5, 33, 2031,
                      file_path=old)  # fmt: skip
    assert await client.find_again(other_year) is None
    await client.close()


def test_titles_that_tell_episodes_apart():
    for title in ("Triangle", "The Fence", "Chapter 3: The Return", "Death on Sun Mountain"):
        assert telling_title(title, "Bonanza"), title
    for title in ("", "  ", "33", "Episode 33", "Ep. 5", "Pilot", "Part 2", "TBA", "Bonanza"):
        assert not telling_title(title, "Bonanza"), title


async def test_which_library_a_stations_show_was_in_is_kept_between_restarts():
    plex = FakePlex()
    plex.add_section("3", "TV Parents", "show")
    plex.add_show("100", "Bonanza", year=1959)
    plex.add_episode("201", "100", 1, 1, "A Rose for Lotta", "/teens/e1.mkv", 60_000)
    plex.add_show("500", "Bonanza", year=1959, section="3")
    plex.add_episode("501", "500", 1, 1, "A Rose for Lotta", "/parents/e1.mkv", 60_000)
    for key, section in (("201", "1"), ("501", "3")):
        plex.episodes[key]["librarySectionID"] = section
    saved: list[dict] = []
    client = PlexClient("http://plex.test", "token", transport=like_plex(plex))
    client.remember_libraries = saved.append
    source = {"type": "show", "ratingKey": "100", "title": "Bonanza"}
    await client.items_for_source(source)
    await client.items_for_source(source)
    assert saved == [{"100": "1"}]  # (said once: it hadn't changed)
    # Restarted, with the show added again in its library meanwhile.
    plex.remove("201")
    del plex.shows["100"]
    plex.add_show("110", "Bonanza", year=1959)
    plex.add_episode("211", "110", 1, 1, "A Rose for Lotta", "/teens/e1.mkv", 60_000)
    restarted = PlexClient("http://plex.test", "token", transport=like_plex(plex))
    restarted.libraries.update(saved[-1])
    assert [i.rating_key for i in await restarted.items_for_source(source)] == ["211"]
    await client.close()
    await restarted.close()


def test_the_app_keeps_which_library_each_show_was_in(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import META_PLEX_LIBRARIES, create_app

    plex = FakePlex()
    plex.add_show("100", "Bonanza", year=1959)
    plex.add_episode("201", "100", 1, 1, "A Rose for Lotta", "/teens/e1.mkv", 22 * 60_000)
    plex.episodes["201"]["librarySectionID"] = "1"
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=plex.transport()))
    with TestClient(app) as c:
        made = c.post("/api/channels", json={"number": 5, "sources": [
            {"type": "show", "ratingKey": "100", "title": "Bonanza"}]})  # fmt: skip
        assert made.status_code == 201, made.text
        assert json.loads(app.state.ctx.db.get_meta(META_PLEX_LIBRARIES)) == {"100": "1"}
    again = create_app(
        settings, PlexClient("http://plex.test", "token", transport=plex.transport())
    )
    assert again.state.ctx.plex.libraries == {"100": "1"}
    again.state.ctx.db.close()


async def test_an_episode_plex_gives_no_number_is_found_again_by_proof():
    """A show by air date: Plex gives its episodes a year for a season, and no
    episode number. One added again (its file renamed, or moved to another
    show of its title) is found by the same file name, or the same title
    from the same year; a show matched to the same TVDB show isn't enough
    (it doesn't say which episode)."""
    plex = FakePlex()
    plex.add_section("3", "TV Parents", "show")
    plex.add_show("100", "The Nightly News", year=1990)
    plex.add_show("500", "The Nightly News", year=1990, section="3")

    def dated(key, show, title, path):
        plex.add_episode(key, show, 2005, 0, title, path, 60_000)
        del plex.episodes[key]["index"]  # (no episode number)
        plex.episodes[key]["year"] = 2005

    dated("211", "100", "March 24, 2005", "/news/The Nightly News 2005-03-24 [HDTV].mkv")
    dated("511", "500", "March 25, 2005", "/parents/news/2005-03-25.mkv")
    dated("512", "500", "Episode", "/parents/news/2005-03-26.mkv")
    plex.shows["100"]["Guid"] = plex.shows["500"]["Guid"] = [{"id": "tvdb://12345"}]
    client = PlexClient("http://plex.test", "token", transport=like_plex(plex))

    def gone(key, title, path):
        return Item(0, 0, 1_000, key, "episode", title, "The Nightly News", "100", 2005, None,
                    2005, file_path=path)  # fmt: skip

    # In its own show, renamed: the same title, from the same year.
    assert await client.find_again(gone("201", "March 24, 2005", "/news/2005-03-24.ts")) == "211"
    # Moved to another show of its title: the same title.
    assert await client.find_again(gone("202", "March 25, 2005", "/news/old.ts")) == "511"
    # The same file name, even with a title that says nothing.
    assert await client.find_again(gone("203", "Episode", "/old/2005-03-26.MKV")) == "512"
    # The same TVDB show, but nothing says which episode: not found.
    assert await client.find_again(gone("204", "Episode", "/old/2005-03-27.mkv")) is None
    assert await client.find_again(gone("205", "March 29, 2005", "/old/x.mkv")) is None
    await client.close()


def test_a_station_program_with_no_number_is_matched_by_its_title():
    on = OnStations()
    for item in (
        Item(0, 0, 1_000, "511", "episode", "March 25, 2005", "The Nightly News", "500", 2005,
             None, 2005, file_path="/parents/news/2005-03-25.mkv"),
        Item(0, 0, 1_000, "512", "episode", "Episode", "The Nightly News", "500", 2005, None,
             2005, file_path="/parents/news/2005-03-26.mkv"),
    ):  # fmt: skip
        on.add(item)
    entry = {"ratingKey": "202", "title": "March 25, 2005", "show": "The Nightly News",
             "season": 2005, "episode": None, "year": 2005, "file": "/news/old.ts"}  # fmt: skip
    assert on.again(entry).rating_key == "511"
    vague = {**entry, "ratingKey": "203", "title": "Episode", "file": "/news/other.ts"}
    assert on.again(vague) is None  # (a title that says nothing)
    assert on.again({**entry, "year": 2006}) is None  # (another year)
