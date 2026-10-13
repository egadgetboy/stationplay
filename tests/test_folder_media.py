"""Folder libraries in Media and on stations (library.py routing each key
to its source): every library route works for folder items as for Plex's,
with watched status and places kept per person, and stations are built
from folder libraries as from Plex's, with no Plex at all."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Item
from app.library import Library, LibraryError
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .folderlib import Clips, radarr_movies, sonarr_tv
from .helpers import like_plex

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

TV = {
    "containers": ["mkv", "mp4"],
    "video": [{"codec": "h264", "width": 1920, "height": 1080, "bitDepth": 8}],
    "hdr": [],
    "audio": ["aac", "ac3"],
}


@pytest.fixture(scope="session")
def clips(tmp_path_factory) -> Clips:
    return Clips(tmp_path_factory.mktemp("clips"))


@pytest.fixture
def media(tmp_path, clips) -> dict[str, Path]:
    root = tmp_path / "media"
    return {**sonarr_tv(root / "TV", clips), **radarr_movies(root / "Movies", clips), "root": root}


@pytest.fixture
def app(tmp_path, media):
    settings = Settings(data_dir=tmp_path / "data", media_dir=str(media["root"]))
    return create_app(settings, PlexClient("", ""))  # (no Plex at all)


def add_library(home: TestClient, name: str, kind: str, folder: str) -> str:
    made = home.post(
        "/api/folder-libraries", json={"name": name, "kind": kind, "folders": [folder]}
    )
    assert made.status_code == 201, made.text
    key = made.json()["key"]
    for _ in range(300):
        found = {x["key"]: x for x in home.get("/api/folder-libraries").json()["libraries"]}
        if found[key]["scannedMs"]:
            return key
        time.sleep(0.05)
    raise AssertionError("the folder library wasn't scanned")


def keys_by_title(home: TestClient, library: str) -> dict[str, str]:
    page = home.get(f"/api/internal/libraries/{library}").json()
    return {x["title"]: x["key"] for x in page["items"]}


def test_folder_libraries_in_media(app, media):
    with TestClient(app) as home:
        tv = add_library(home, "TV", "show", "TV")
        movies = add_library(home, "Movies", "movie", "Movies")
        assert (tv, movies) == ("f1", "f2")
        assert home.put("/api/app-libraries", json={"libraries": [tv, movies]}).status_code == 200
        assert "library" in home.get("/api/v1/server").json()["features"]
        libs = home.get("/api/internal/libraries").json()["libraries"]
        assert [(x["key"], x["title"], x["kind"]) for x in libs] == [
            ("f1", "TV", "show"), ("f2", "Movies", "movie")
        ]  # fmt: skip
        shows = keys_by_title(home, tv)
        assert list(shows) == ["The Daily Hour", "Northbound"]
        show = home.get(f"/api/internal/items/{shows['Northbound']}").json()
        assert show["summary"] == "A ship goes north." and show["year"] == 2019
        assert show["genres"] == ["Drama", "Mystery"] and show["contentRating"] == "TV-14"
        assert [(s["season"], s["title"], s["episodes"]) for s in show["seasons"]] == [
            (1, "Season 1", 4), (0, "Specials", 1)
        ]  # fmt: skip
        assert show["next"]["episodeTitle"] == "Pilot From NFO"
        assert [c["name"] for c in show["cast"]] == ["Bo Diaz", "Ana Lee"]
        episodes = home.get(f"/api/internal/items/{shows['Northbound']}/episodes?season=1").json()
        assert [(e["season"], e["episode"]) for e in episodes["episodes"]] == [
            (1, 1), (1, 2), (1, 3), (1, 4)
        ]  # fmt: skip
        pilot = episodes["episodes"][0]
        detail = home.get(f"/api/internal/items/{pilot['key']}").json()
        assert detail["summary"] == "It begins." and detail["showKey"] == shows["Northbound"]
        assert detail["picture"]["size"] == "SD" and detail["audio"][0]["languageCode"] == "eng"
        assert detail["markers"] == {"intro": None, "credits": None, "creditsToEnd": False}
        found = keys_by_title(home, movies)
        matrix = home.get(f"/api/internal/items/{found['The Glass Garden']}").json()
        assert (matrix["tagline"], matrix["contentRating"], matrix["year"]) == (
            "The tagline",
            "R",
            1999,
        )
        assert matrix["directors"] == ["Dee Rector"] and matrix["backdrop"]
        heat = home.get(f"/api/internal/items/{found['Dry Season']}").json()
        assert len(heat["versions"]) == 2
        # Search, home, related.
        assert [x["title"] for x in home.get("/api/internal/search?q=glass").json()["items"]] == [
            "The Glass Garden"
        ]
        added = home.get("/api/internal/home").json()["added"]
        assert [row["library"] for row in added] == [tv, movies]
        assert home.get(f"/api/internal/items/{found['Dry Season']}/related").status_code == 200
        # Pictures: beside the videos, or inside them (tapiOca's own come
        # later: a title without one has none).
        for key, kind in (
            (shows["Northbound"], "poster"), (shows["Northbound"], "backdrop"),
            (pilot["key"], "thumb"), (found["The Glass Garden"], "poster"),
        ):  # fmt: skip
            got = home.get(f"/api/internal/art/{key}?kind={kind}&w=160")
            assert got.status_code == 200, (key, kind)
            assert got.headers["content-type"] == "image/jpeg" and got.content[:2] == b"\xff\xd8"
        for kind in ("poster", "backdrop"):
            assert (
                home.get(f"/api/internal/art/{found['Loose Movie']}?kind={kind}").status_code == 404
            )
        # Keys that aren't anything's.
        for bad in ("f999", "fx", "f", "f1x", "../f1"):
            assert home.get(f"/api/internal/items/{bad}").status_code == 404, bad


def test_playing_and_progress_for_folder_items(app, media, monkeypatch):
    from app import ondemand

    monkeypatch.setattr(ondemand, "STARTED_MS", 500)  # (the test's files are 3 seconds long)
    with TestClient(app) as home:
        tv = add_library(home, "TV", "show", "TV")
        movies = add_library(home, "Movies", "movie", "Movies")
        home.put("/api/app-libraries", json={"libraries": [tv, movies]})
        found = keys_by_title(home, movies)
        played = home.post(
            "/api/internal/play", json={"key": found["The Glass Garden"], "device": TV}
        )
        assert played.status_code == 200, played.text
        played = played.json()
        assert played["method"] == "direct" and played["url"].endswith("/file.mkv")
        whole = media["matrix"].read_bytes()
        part = home.get(played["url"], headers={"Range": "bytes=10-99"})
        assert part.status_code == 206 and part.content == whole[10:100]
        assert played["durationMs"] and played["audio"][0]["codec"] == "aac"
        # Places and watched, kept by StationPlay per person.
        report = home.post(
            "/api/internal/progress", json={"key": found["The Glass Garden"], "positionMs": 1500}
        )
        assert report.json() == {"positionMs": 1500, "watched": False}
        going = home.get("/api/internal/home").json()["continue"]
        assert [c["key"] for c in going] == [found["The Glass Garden"]]
        assert home.post(
            "/api/internal/progress", json={"key": found["The Glass Garden"], "watched": True}
        ).json()["watched"]
        # One file, two episodes: watching it watches both.
        north = keys_by_title(home, tv)["Northbound"]
        eps = home.get(f"/api/internal/items/{north}/episodes").json()["episodes"]
        two = [e for e in eps if e["episode"] in (2, 3) and e["season"] == 1]
        home.get(f"/api/internal/items/{north}/episodes")  # (kept, as the apps have it)
        assert (
            home.post(
                "/api/internal/progress", json={"key": two[0]["key"], "watched": True}
            ).status_code
            == 200
        )
        eps = home.get(f"/api/internal/items/{north}/episodes").json()["episodes"]
        assert [e["watched"] for e in eps if e["key"] in {two[0]["key"], two[1]["key"]}] == [
            True,
            True,
        ]
        assert home.get(f"/api/internal/items/{north}").json()["unwatched"] == 3


def test_stations_from_folder_libraries(app, media):
    with TestClient(app) as home:
        tv = add_library(home, "TV", "show", "TV")
        movies = add_library(home, "Movies", "movie", "Movies")
        listed = home.get("/api/libraries").json()
        assert [(x["key"], x["type"]) for x in listed] == [(tv, "show"), (movies, "movie")]
        items = home.get(f"/api/libraries/{movies}/items").json()
        assert {x["title"] for x in items} >= {"The Glass Garden", "Dry Season", "Émilie"}
        shows = {x["title"]: x["ratingKey"] for x in home.get(f"/api/libraries/{tv}/items").json()}
        made = home.post(
            "/api/channels",
            json={
                "number": 5,
                "name": "North",
                "sources": [{"type": "show", "ratingKey": shows["Northbound"]}],
            },
        )
        assert made.status_code == 201, made.text
        # Its episodes, once each (a file of two is one program), and no specials.
        assert made.json()["itemCount"] == 3
        whole = home.post(
            "/api/channels",
            json={"number": 6, "sources": [{"type": "section", "key": tv, "sectionType": "show"}]},
        )
        assert whole.status_code == 201 and whole.json()["itemCount"] == 5
        # Filters, on what the layers say.
        fields = home.get(f"/api/filter/fields?kind=movie&libraries={movies}").json()
        genre = next(f for f in fields["fields"] if f["field"] == "genre")
        assert "Action" in genre["choices"] and 1990 in fields["decade"]
        action = {
            "type": "filter",
            "kind": "movie",
            "libraries": [movies],
            "tags": {"genre": ["Action"]},
        }
        preview = home.post("/api/filter/preview", json=action).json()
        assert preview["examples"] == ["The Glass Garden (1999)"]
        assert (
            home.post("/api/channels", json={"number": 7, "sources": [action]}).status_code == 201
        )
        # Collections, from an NFO's set.
        collections = home.get("/api/collections").json()
        assert [c["title"] for c in collections] == ["The Glass Garden Collection"]
        made = home.post(
            "/api/collections/stations", json={"ratingKeys": [collections[0]["ratingKey"]]}
        )
        assert made.status_code == 201 and made.json()["made"][0]["itemCount"] == 1
        # What's on: a folder library's program.
        guide = home.get("/api/channels/1/guide?hours=1").json()
        assert guide and guide[0]["ratingKey"].startswith("f")
        # A folder key that isn't anything is refused, as a Plex one is.
        bad = home.post(
            "/api/channels", json={"number": 9, "sources": [{"type": "show", "ratingKey": "f999"}]}
        )
        assert bad.status_code in (400, 404, 502)
        assert (
            home.post(
                "/api/channels",
                json={"number": 9, "sources": [{"type": "show", "ratingKey": "fx"}]},
            ).status_code
            == 400
        )


async def test_the_library_sends_each_key_to_its_source(tmp_path, clips):
    """Plex's keys to Plex, folder keys to the folder libraries, and calls
    about every library to both (Plex's first)."""
    from app.db import Database
    from app.folders import FolderSource

    fp = FakePlex()
    fp.add_show("100", "Plex Show")
    fp.add_episode("201", "100", 1, 1, "Pilot", "/tv/Show/S01E01.mkv", 60_000)
    media = tmp_path / "media"
    sonarr_tv(media / "TV", clips)
    folders = FolderSource(
        Database(tmp_path / "db.sqlite"), Settings(media_dir=str(media), data_dir=tmp_path)
    )
    lib = folders.add_library("Folders", "show", ["TV"])
    await folders.scan(lib.id)
    library = Library(PlexClient("http://plex.test", "token", transport=like_plex(fp)), folders)
    assert [x["key"] for x in await library.libraries()] == ["1", "f1"]
    plex_items = await library.items_for_source({"type": "show", "ratingKey": "100"})
    show = next(
        t
        for t in folders.things.values()
        if t.kind == "show" and folders.title_of(t) == "Northbound"
    )
    folder_items = await library.items_for_source({"type": "show", "ratingKey": show.key})
    assert [i.rating_key for i in plex_items] == ["201"]
    assert folder_items and all(
        i.rating_key.startswith("f") and i.library == "f1" for i in folder_items
    )
    [part] = await library.current_files(folder_items[0].rating_key)
    assert part.file == folder_items[0].file_path and part.part_key is None
    assert library.stream_url(folder_items[0].rating_key, "/x") is None
    both = await library.entries(["201", folder_items[0].rating_key, "f999"])
    assert [e.key for e in both] == ["201", folder_items[0].rating_key]
    assert (await library.fingerprint()).endswith(folders.fingerprint())
    assert await library.markers(folder_items[0].rating_key) == []
    ids = await library.ids(show.key)
    assert ids == {"tvdb": "90001", "imdb": "tt9000001", "section": "f1"}
    # A program whose file was replaced (a new key) is found again.
    gone = Item(0, 0, 1000, "f999", "episode", "Old", "Northbound", show.key, 1, 4)
    again = await library.find_again(gone)
    assert again is not None and again.startswith("f")
    with pytest.raises(LibraryError) as e:
        await library.current_files("f999")
    assert e.value.status == 404
    # With no Plex at all, folder libraries are the library.
    alone = Library(PlexClient("", ""), folders)
    assert alone.configured
    await alone.check()
    assert [x["key"] for x in await alone.libraries()] == ["f1"]


def test_viewing_levels_hide_folder_titles_as_plexs(app, media):
    """A Media folder of your own's ratings come from its NFO files, and a
    level hides what's above it, and what's unrated where it hides those,
    exactly as for Plex's: in every list, asked for directly, as a picture,
    played, and on stations."""
    ada = {"name": "Ada", "password": "correct horse battery"}
    tess = {"name": "Tess", "password": "staple battery horse", "role": "user"}
    with TestClient(app) as home:
        tv = add_library(home, "TV", "show", "TV")
        movies = add_library(home, "Movies", "movie", "Movies")
        shows = keys_by_title(home, tv)
        films = keys_by_title(home, movies)
        assert home.put("/api/app-libraries", json={"libraries": [tv, movies]}).status_code == 200
        # Stations: one of the TV-14 show, one of the R movie.
        for number, key in ((4, shows["Northbound"]), (5, films["The Glass Garden"])):
            kind = "show" if key == shows["Northbound"] else "movie"
            made = home.post(
                "/api/channels",
                json={"number": number, "sources": [{"type": kind, "ratingKey": key}]},
            )
            assert made.status_code == 201, made.text
        home.post("/api/access/users", json=ada)
        made = home.post("/api/access/users", json=tess)
        assert made.status_code in (200, 201), made.text
        tess_id = made.json()["id"]
        levels = home.get("/api/access/viewing").json()["levels"]
        teen = next(lv["id"] for lv in levels if lv["builtin"] == "teen")
        changed = home.put(f"/api/access/users/{tess_id}/viewing", json={"level": teen})
        assert changed.status_code == 200, changed.text
        phone = TestClient(app)
        signed = phone.post("/api/internal/sign-in", json=tess)
        assert signed.status_code == 200, signed.text
        as_tess = {"Authorization": f"Bearer {signed.json()['token']}"}
        # TV-14 is within Teen; R, and anything unrated, aren't.
        seen = phone.get(f"/api/internal/libraries/{tv}", headers=as_tess).json()
        assert [x["key"] for x in seen["items"]] == [shows["Northbound"]]
        seen = phone.get(f"/api/internal/libraries/{movies}", headers=as_tess).json()
        assert seen["items"] == [] and seen["total"] == 0
        hidden = [
            films["The Glass Garden"],
            films["Loose Movie"],
            films["Dry Season"],
            shows["The Daily Hour"],
        ]
        found = phone.get("/api/internal/search?q=e", headers=as_tess).json()
        assert not {x["key"] for x in found["items"]} & set(hidden)
        for row in phone.get("/api/internal/home", headers=as_tess).json()["added"]:
            assert not {x["key"] for x in row["items"]} & set(hidden)
        nothing = phone.get("/api/internal/items/f999", headers=as_tess)
        for key in hidden:
            refused = phone.get(f"/api/internal/items/{key}", headers=as_tess)
            assert refused.status_code == 404 and refused.json() == nothing.json(), key
            assert phone.get(f"/api/internal/art/{key}", headers=as_tess).status_code == 404
            played = phone.post(
                "/api/internal/play", json={"key": key, "device": TV}, headers=as_tess
            )
            assert played.status_code == 404, (key, played.text)
        assert phone.get(f"/api/internal/items/{shows['Northbound']}", headers=as_tess).is_success
        # The R movie's station is hidden; the TV-14 show's isn't.
        listed = phone.get("/api/v1/stations", headers=as_tess).json()["stations"]
        assert [s["number"] for s in listed if s["number"] in (4, 5)] == [4]


def test_media_folders_of_your_own_stay_while_plex_is_away(tmp_path, media, monkeypatch):
    """Plex set up but not answering (restarting, its machine off): Media
    folders of tapiOca's own, which don't need it, are still listed in the
    apps' Media and the station editor; Media in the apps says Plex's
    can't be listed, and the page changes nothing about sharing meanwhile."""
    import asyncio

    from app import setup

    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
        media_dir=str(media["root"]),
    )  # fmt: skip
    fp = FakePlex()
    fp.add_show("100", "Plex Show")
    away = create_app(settings, PlexClient("http://plex.test", "token", transport=like_plex(fp)))
    with TestClient(away) as home:
        tv = add_library(home, "TV", "show", "TV")
        assert home.put("/api/app-libraries", json={"libraries": ["1", tv]}).status_code == 200

        async def never(*_args, **_kwargs):
            await asyncio.sleep(60)

        monkeypatch.setattr(away.state.ctx.plex, "sections", never)
        monkeypatch.setattr(setup, "PLEX_ASK_S", 0.3)
        listed = home.get("/api/app-libraries").json()
        assert [x["key"] for x in listed["libraries"]] == [tv]
        assert listed["shared"] == ["1", tv]
        assert listed["problem"] == (
            "Plex isn’t answering, so tapiOca can’t list Plex’s Media folders right now. "
            "What’s shared stays as it is until it can."
        )

        async def refused(*_args, **_kwargs):
            from app.plex import PlexError

            raise PlexError("Plex isn't answering", 503)

        monkeypatch.setattr(away.state.ctx.plex, "sections", refused)
        away.state.ctx.catalog.forget()
        apps = home.get("/api/internal/libraries")
        assert apps.status_code == 200 and [x["key"] for x in apps.json()["libraries"]] == [tv]
        assert [x["key"] for x in home.get("/api/libraries").json()] == [tv]

        async def plex_away(*_args, **_kwargs):
            from app.plex import PlexError

            raise PlexError("Plex isn't answering", 503)

        monkeypatch.setattr(away.state.ctx.plex, "library_fingerprint", plex_away)
        away.state.ctx.catalog.forget()
        # (Browsed, a show opened and its episodes listed, while Plex is away.)
        listed = home.get(f"/api/internal/libraries/{tv}")
        assert listed.status_code == 200, listed.text
        show = listed.json()["items"][0]["key"]
        assert home.get(f"/api/internal/items/{show}").status_code == 200
        assert home.get(f"/api/internal/items/{show}/episodes?season=1").status_code == 200


def test_levels_that_hide_by_tags_judge_folder_titles_by_theirs(app, media):
    """A level that hides a genre, a tag, a collection or a studio hides a
    Media folder of your own's titles that have it (from their NFO files),
    and only those, as for Plex's: never every title, as if none were known."""
    tess = {"name": "Tess", "password": "staple battery horse", "role": "user"}
    with TestClient(app) as home:
        tv = add_library(home, "TV", "show", "TV")
        movies = add_library(home, "Movies", "movie", "Movies")
        shows = keys_by_title(home, tv)
        films = keys_by_title(home, movies)
        assert home.put("/api/app-libraries", json={"libraries": [tv, movies]}).status_code == 200
        home.post("/api/access/users", json={"name": "Ada", "password": "correct horse battery"})
        tess_id = home.post("/api/access/users", json=tess).json()["id"]
        phone = TestClient(app)
        as_tess = {
            "Authorization": f"Bearer {phone.post('/api/internal/sign-in', json=tess).json()['token']}"
        }
        for blocks, hidden_show, hidden_film in (
            ({"genres": ["Horror"]}, False, False),
            ({"genres": ["mystery"]}, True, False),
            ({"studios": ["Northern Network"]}, True, False),
            ({"genres": ["Action"]}, False, True),
            ({"collections": ["The Glass Garden Collection"]}, False, True),
        ):
            made = home.post("/api/access/levels", json={
                "name": f"Level {len(str(blocks))}{hidden_show}{hidden_film}", "movieAge": None,
                "tvAge": None, "unrated": True, "blocks": blocks,
            })  # fmt: skip
            assert made.status_code == 201, made.text
            changed = home.put(f"/api/access/users/{tess_id}/viewing",
                               json={"level": made.json()["id"]})  # fmt: skip
            assert changed.status_code == 200, changed.text
            for _ in range(2):  # (the second time, every title's tags are known)
                seen_tv = phone.get(f"/api/internal/libraries/{tv}", headers=as_tess).json()
                seen_films = phone.get(f"/api/internal/libraries/{movies}", headers=as_tess).json()
            tv_keys = [x["key"] for x in seen_tv["items"]]
            film_keys = [x["key"] for x in seen_films["items"]]
            assert (shows["Northbound"] not in tv_keys) == hidden_show, blocks
            assert (films["The Glass Garden"] not in film_keys) == hidden_film, blocks
            assert films["Dry Season"] in film_keys and shows["The Daily Hour"] in tv_keys, blocks
