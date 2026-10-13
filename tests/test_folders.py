"""Folder libraries (see folders.py and folderscan.py, 1.35.0): scanning
folders laid out as Sonarr, Radarr, Jellyfin and Plex lay them out, each
layer of details and the order between them, keys kept across renames,
what can't be placed, pictures, and reading only what's safe."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app import folderart, folderscan, nfo
from app.config import Settings
from app.db import Database
from app.folders import FolderSource, NotFolder
from app.library import LibraryError, NoPicture

from .folderlib import Clips, jellyfin_movies, plex_tv, put, radarr_movies, remove, sonarr_tv

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


@pytest.fixture(scope="session")
def clips(tmp_path_factory) -> Clips:
    return Clips(tmp_path_factory.mktemp("clips"))


def make_source(tmp_path: Path) -> FolderSource:
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    settings = Settings(media_dir=str(media), data_dir=tmp_path / "data")
    return FolderSource(Database(tmp_path / "data" / "stationplay.db"), settings)


def real(path: Path) -> str:
    return os.path.realpath(path)


def by_title(source: FolderSource, kind: str) -> dict[str, object]:
    return {source.title_of(t): t for t in source.things.values() if t.kind == kind}


def episodes(source: FolderSource, show_title: str) -> dict[tuple, object]:
    show = by_title(source, "show")[show_title]
    return {
        (e.get("season"), e.get("episode") or e.get("released")): e
        for e in source.episodes_of(show)
    }


async def test_a_sonarr_library_is_read_with_every_layer(tmp_path, clips):
    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    files = sonarr_tv(tv, clips)
    lib = source.add_library("TV", "show", [str(tv)])
    assert lib.key == "f1"
    assert await source.scan(lib.id)
    shows = by_title(source, "show")
    assert set(shows) == {"Northbound", "The Daily Hour"}
    north = shows["Northbound"]
    # The show's NFO first: its title, year, plot, genres, network and cast
    # as billed, and its IDs (with the one in its folder's name).
    assert north.details["title"] == ["Northbound", "nfo", "tvshow.nfo"]
    assert north.get("year") == 2019 and north.get("summary") == "A ship goes north."
    assert north.get("genres") == ["Drama", "Mystery"]
    assert north.get("studios") == ["Northern Network"]
    assert north.get("cast") == [["Bo Diaz", "Pilot"], ["Ana Lee", "Captain"]]
    assert north.get("ids") == {"tvdb": "90001", "imdb": "tt9000001"}
    eps = episodes(source, "Northbound")
    assert set(eps) == {(1, 1), (1, 2), (1, 3), (1, 4), (0, 1)}
    # An episode's own NFO, then its name.
    assert eps[1, 1].details["title"][:2] == ["Pilot From NFO", "nfo"]
    assert eps[1, 1].get("summary") == "It begins."
    assert eps[1, 4].details["title"][:2] == ["Dark Water", "names"]
    # One file, two episodes: each its own, the same file.
    assert eps[1, 2].files == eps[1, 3].files == [[str(files["e23"])]]
    assert (eps[1, 2].get("title"), eps[1, 3].get("title")) == ("Part One", "Part Two")
    assert eps[1, 2].key != eps[1, 3].key
    # A daily show, by its dates.
    daily = episodes(source, "The Daily Hour")
    assert set(daily) == {(2024, "2024-03-15"), (2024, "2024-03-18")}
    assert daily[2024, "2024-03-15"].get("title") == "First Guest"
    assert source.title_of(daily[2024, "2024-03-18"]) == "2024-03-18"
    # Extras, a NAS's own folders and hidden files are never programs.
    paths = {p for t in source.things.values() for v in t.files for p in v}
    assert not any("Featurettes" in p or "@eaDir" in p or "/." in p for p in paths)
    # Keys are "f" and digits, never the library's own.
    assert all(t.key[0] == "f" and t.key[1:].isdigit() for t in source.things.values())
    entry = await source.entry_of(eps[1, 1].key, details=True)
    assert entry is not None and entry.show_title == "Northbound" and entry.library == "f1"
    assert entry.duration_ms and 2500 <= entry.duration_ms <= 3500
    media = entry.media[0]
    assert (media.width, media.height, media.video) == (320, 180, "h264")
    assert media.audio[0].language_code == "eng" and media.audio[0].codec == "aac"


async def test_tags_inside_the_files_come_before_names(tmp_path, clips):
    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    plex_tv(tv, clips)
    lib = source.add_library("TV", "show", [str(tv)])
    await source.scan(lib.id)
    eps = episodes(source, "Orbit Room")
    assert set(eps) == {(1, 1), (1, 2)}  # (and the sample beside one isn't an episode)
    one = eps[1, 1]
    assert one.details["title"][:2] == ["The Title Inside", "tags"]
    assert one.get("summary") == "A description from the file's own tags, long enough."
    assert one.get("released") == "2011-04-02" and one.get("genres") == ["Drama", "Mystery"]
    # (A title in the tags that's a file's name never counts.)
    assert folderscan.from_tags({"title": "Orbit.Room.S01E02.720p.WEB-DL"}).get("title") is None
    assert "title" not in eps[1, 2].details and source.title_of(eps[1, 2]) == "Episode 2"


async def test_an_episode_that_cant_be_placed_is_kept_by_its_names(tmp_path, clips):
    """Neither its name nor an NFO says which episode it is: it's kept, by
    what its names say (its season, and its file's name as its title), and
    why is kept for Needs a match, later. An NFO saying so places it."""
    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    files = plex_tv(tv, clips)
    lib = source.add_library("TV", "show", [str(tv)])
    await source.scan(lib.id)
    odd = next(t for t in source.things.values() if t.files and t.files[0][0] == str(files["odd"]))
    assert odd.get("season") == 2 and odd.get("episode") is None
    assert "can't tell which episode" in odd.needs[0]
    put(
        files["odd"].with_suffix(".nfo"),
        text="<episodedetails><title>The Recording</title><episode>7</episode></episodedetails>",
    )
    await source.scan(lib.id)
    again = source.things[odd.id]
    assert again.get("title") == "The Recording" and (
        again.get("season"),
        again.get("episode"),
    ) == (2, 7)
    assert not again.needs


async def test_an_nfo_that_disagrees_with_the_name_is_listed(tmp_path, clips):
    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    show = tv / "Coastline"
    put(show / "Season 01" / "Coastline - S01E04.mkv", clips.plain)
    put(
        show / "Season 01" / "Coastline - S01E04.nfo",
        text="<episodedetails><title>T</title><season>2</season><episode>5</episode></episodedetails>",
    )
    put(show / "Season 01" / "Coastline - S01E05.mkv", clips.plain)
    lib = source.add_library("TV", "show", [str(tv)])
    await source.scan(lib.id)
    eps = episodes(source, "Coastline")
    # (The NFO, the first layer, says which; why is kept for Needs a match.)
    assert (2, 5) in eps and (1, 5) in eps
    assert "Its NFO says S02E05, and its name says S01E04" in eps[2, 5].needs
    assert not eps[1, 5].needs


async def test_a_radarr_library_with_versions_parts_extras_and_samples(tmp_path, clips):
    source = make_source(tmp_path)
    movies = Path(source.settings.media_dir) / "Movies"
    files = radarr_movies(movies, clips)
    lib = source.add_library("Movies", "movie", [str(movies)])
    await source.scan(lib.id)
    found = by_title(source, "movie")
    assert set(found) == {
        "The Glass Garden",
        "Dry Season",
        "Long Movie",
        "Émilie",
        "Loose Movie",
        "Tall Tale",
    }
    matrix = found["The Glass Garden"]
    assert matrix.details["title"][:2] == ["The Glass Garden", "nfo"]
    assert matrix.get("ids") == {"imdb": "tt9100001", "tmdb": "91603"}
    assert matrix.get("tagline") == "The tagline" and matrix.get("content_rating") == "R"
    assert matrix.files == [[str(files["matrix"])]]  # (its sample isn't a version)
    heat = found["Dry Season"]
    assert sorted(heat.files) == [[str(files["heat1080"])], [str(files["heat4k"])]]
    assert found["Long Movie"].files == [[str(files["cd1"]), str(files["cd2"])]]
    entry = await source.entry_of(found["Long Movie"].key, details=True)
    assert entry is not None and len(entry.media[0].parts) == 2
    # (Each part described, and the whole as long as both.)
    first, second = entry.media[0].parts
    assert first.duration_ms and second.duration_ms and second.audio
    assert entry.media[0].duration_ms == first.duration_ms + second.duration_ms
    assert found["Tall Tale"].files == [
        [str(files["big"])]
    ]  # (and its small sample isn't anything)
    assert found["Émilie"].get("year") == 2001
    paths = {p for t in source.things.values() for v in t.files for p in v}
    assert not any(
        n in p
        for p in paths
        for n in ("trailer", "Featurettes", "Behind The Scenes", "sample", "smpl")
    )
    # Its NFO's set is a collection, with a key of its own.
    collections = await source.collections()
    assert [(c["title"], c["count"], c["kind"]) for c in collections] == [
        ("The Glass Garden Collection", 1, "movie")
    ]
    assert collections[0]["ratingKey"].startswith("f")


async def test_jellyfin_and_plex_names_for_ids_and_versions(tmp_path):
    source = make_source(tmp_path)
    movies = Path(source.settings.media_dir) / "Movies"
    jellyfin_movies(movies)
    lib = source.add_library("Movies", "movie", [str(movies)])
    await source.scan(lib.id)
    found = by_title(source, "movie")
    assert set(found) == {"Neon Rain", "Far Station"}
    assert found["Neon Rain"].get("ids") == {"tmdb": "90078"}
    assert len(found["Neon Rain"].files) == 2
    assert found["Far Station"].get("year") == 1979


async def test_keys_stay_the_same_across_renames_and_moves(tmp_path, clips):
    source = make_source(tmp_path)
    media = Path(source.settings.media_dir)
    tv, movies = media / "TV", media / "Movies"
    files = sonarr_tv(tv, clips)
    mfiles = radarr_movies(movies, clips)
    tv_lib = source.add_library("TV", "show", [str(tv)])
    movie_lib = source.add_library("Movies", "movie", [str(movies)])
    await source.scan(tv_lib.id)
    await source.scan(movie_lib.id)
    eps = episodes(source, "Northbound")
    keys = {slot: e.key for slot, e in eps.items()}
    show_key = by_title(source, "show")["Northbound"].key
    matrix_key = by_title(source, "movie")["The Glass Garden"].key
    # Renamed and moved: the same size, the same place in the show.
    moved = files["show"] / "Season 1" / "Northbound S01E04 renamed.mkv"
    moved.parent.mkdir()
    os.rename(files["e4"], moved)
    # A movie's folder renamed, and its file with it.
    new_folder = movies / "Glass Garden, The (1999)"
    os.rename(mfiles["matrix"].parent, new_folder)
    os.rename(new_folder / mfiles["matrix"].name, new_folder / "The Glass Garden (1999).mkv")
    # A show's folder renamed.
    os.rename(files["show"], tv / "Northbound")
    await source.scan(tv_lib.id)
    await source.scan(movie_lib.id)
    eps_after = episodes(source, "Northbound")
    assert {slot: e.key for slot, e in eps_after.items()} == keys
    assert by_title(source, "show")["Northbound"].key == show_key
    assert by_title(source, "movie")["The Glass Garden"].key == matrix_key
    # Replaced by a better copy (another size, another name), as Sonarr
    # and Radarr upgrade: the same key, as Plex keeps its. (Until 1.35.0's
    # audit it was a new key, which lost what people had watched of it and
    # let a title hidden by its key be seen again.)
    s1 = tv / "Northbound" / "Season 01"
    os.remove(s1 / files["e1"].name)
    put(s1 / "Northbound (2019) - S01E01 - Pilot WEBDL.mkv", clips.tagged)
    await source.scan(tv_lib.id)
    assert episodes(source, "Northbound")[1, 1].key == keys[1, 1]
    # A file changed where it is keeps its key, and is read again.
    heat = mfiles["heat1080"]
    heat_key = by_title(source, "movie")["Dry Season"].key
    shutil.copyfile(clips.dark_start, heat)
    await source.scan(movie_lib.id)
    assert by_title(source, "movie")["Dry Season"].key == heat_key
    # What was found is what's kept, through a restart (moved files and all).
    kept = {t.id: (t.path, t.files, t.slot) for t in source.things.values()}
    again = FolderSource(source.db, source.settings)
    assert {t.id: (t.path, t.files, t.slot) for t in again.things.values()} == kept
    assert again.libraries[tv_lib.id].name == "TV"
    assert again.things[eps_after[1, 4].id].path.endswith("Northbound/Season 1/" + moved.name)


async def test_only_new_or_changed_files_are_read_again(tmp_path, clips, monkeypatch):
    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    files = sonarr_tv(tv, clips)
    lib = source.add_library("TV", "show", [str(tv)])
    read: list[str] = []
    real = folderscan.read_file

    async def counting(ffprobe, path, timeout=60.0):
        read.append(path)
        return await real(ffprobe, path, timeout)

    monkeypatch.setattr(folderscan, "read_file", counting)
    await source.scan(lib.id)
    assert len(read) == 6
    read.clear()
    assert not await source.scan(lib.id)  # (nothing changed)
    assert read == []
    shutil.copyfile(clips.tagged, files["e1"])
    await source.scan(lib.id)
    assert read == [str(files["e1"])]


async def test_scanning_waits_while_anyone_is_watching(tmp_path, clips, monkeypatch):
    import asyncio

    from app import folders

    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    sonarr_tv(tv, clips)
    lib = source.add_library("TV", "show", [str(tv)])
    watching = [True]
    source.watching = lambda: watching[0]
    monkeypatch.setattr(folders, "WATCHING_WAIT_S", 0.05)
    task = asyncio.ensure_future(source.scan(lib.id))
    await asyncio.sleep(0.3)
    assert not task.done() and not source.things
    watching[0] = False
    assert await task
    assert source.things


async def test_a_folder_thats_gone_never_empties_a_library(tmp_path, clips, caplog):
    source = make_source(tmp_path)
    media = Path(source.settings.media_dir)
    files = sonarr_tv(media / "TV A", clips)
    plex_tv(media / "TV B", clips)
    lib = source.add_library("TV", "show", [str(media / "TV A"), str(media / "TV B")])
    await source.scan(lib.id)
    before = {t.id for t in source.things.values()}
    north = by_title(source, "show")["Northbound"]
    os.rename(media / "TV A", media / "unmounted")
    caplog.set_level(logging.INFO)
    await source.scan(lib.id)
    await source.scan(lib.id)
    assert {t.id for t in source.things.values()} == before
    assert source.libraries[lib.id].missing == [str(media / "TV A")]
    gone = [t for t in source.things.values() if t.missing]
    assert gone and all(t.root == str(media / "TV A") for t in gone)
    assert sum("can't be reached" in r.message for r in caplog.records) == 1
    episode = source.episodes_of(north)[0]
    with pytest.raises(LibraryError) as e:
        await source.current_files(episode.key)
    assert e.value.status is None  # (not "no such thing": it's away)
    # An empty mount point is a share that's gone too.
    (media / "TV A").mkdir()
    await source.scan(lib.id)
    assert {t.id for t in source.things.values()} == before
    os.rmdir(media / "TV A")
    os.rename(media / "unmounted", media / "TV A")
    await source.scan(lib.id)
    assert not any(t.missing for t in source.things.values())
    assert {t.id for t in source.things.values()} == before
    [part] = await source.current_files(episode.key)
    assert part.file in (str(files["e1"]), str(files["e23"]), str(files["e4"]))


async def test_pictures_beside_and_inside_the_files(tmp_path, clips):
    source = make_source(tmp_path)
    media = Path(source.settings.media_dir)
    tv, movies = media / "TV", media / "Movies"
    sonarr_tv(tv, clips)
    put(movies / "Covered (2010)" / "Covered (2010).mkv", clips.covered)
    put(movies / "Plain (2011)" / "Plain (2011).mkv", clips.plain)
    put(movies / "Plain (2011)" / "Plain (2011)-fanart.jpg", clips.wide)
    tv_lib = source.add_library("TV", "show", [str(tv)])
    movie_lib = source.add_library("Movies", "movie", [str(movies)])
    await source.scan(tv_lib.id)
    await source.scan(movie_lib.id)
    north = by_title(source, "show")["Northbound"]
    eps = episodes(source, "Northbound")
    poster = (tv / "Northbound (2019) {tvdb-90001}" / "poster.jpg").read_bytes()
    assert (await source._picture(north, "thumb"))[0] == poster
    assert north.art["backdrop"].endswith("fanart.jpg") and north.art["logo"].endswith(
        "clearlogo.png"
    )
    assert '"1"' in north.art["seasons"]
    thumb = (await source._picture(eps[1, 1], "thumb"))[0]
    assert (
        thumb
        == (
            tv
            / "Northbound (2019) {tvdb-90001}"
            / "Season 01"
            / "Northbound (2019) - S01E01 - Pilot-thumb.jpg"
        ).read_bytes()
    )
    found = by_title(source, "movie")
    # A cover inside the file.
    data, kind = await source._picture(found["Covered"], "thumb")
    assert kind == "image/jpeg" and data[:2] == b"\xff\xd8"
    assert data == clips.picture.read_bytes()
    # No poster: none (tapiOca's own pictures come later), and the apps are
    # told so, so they never ask.
    with pytest.raises(NoPicture):
        await source._picture(found["Plain"], "thumb")
    assert (await source.entry_of(found["Plain"].key)).has_thumb is False
    assert (await source._picture(found["Plain"], "art"))[0] == clips.wide.read_bytes()
    with pytest.raises(NoPicture):
        await source._picture(found["Covered"], "art")
    # No thumbnail: its show's poster.
    assert (await source._picture(eps[1, 4], "thumb"))[0] == poster
    # Made smaller, as asked.
    small, _ = await source.picture(found["Covered"].key, "thumb", 30, 45)
    assert size_of(small, tmp_path) == (30, 45)


def size_of(data: bytes, tmp_path: Path) -> tuple[int, int]:
    path = tmp_path / "probe.jpg"
    path.write_bytes(data)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


async def test_nothing_is_read_from_outside_the_media_folder(tmp_path, clips):
    source = make_source(tmp_path)
    media = Path(source.settings.media_dir)
    outside = tmp_path / "outside"
    put(outside / "Secret (2000).mkv", clips.plain)
    put(outside / "secret.jpg", clips.picture)
    movies = media / "Movies"
    put(movies / "Plain (2011)" / "Plain (2011).mkv", clips.plain)
    # A link to a video outside, a picture linked from outside, and a
    # folder linked from outside.
    os.symlink(outside / "Secret (2000).mkv", movies / "Secret (2000).mkv")
    os.symlink(outside / "secret.jpg", movies / "Plain (2011)" / "poster.jpg")
    os.symlink(outside, movies / "Linked")
    lib = source.add_library("Movies", "movie", [str(movies)])
    await source.scan(lib.id)
    assert set(by_title(source, "movie")) == {"Plain"}
    plain = by_title(source, "movie")["Plain"]
    with pytest.raises(NoPicture):  # (not the picture outside)
        await source._picture(plain, "thumb")
    with pytest.raises(NoPicture):
        folderart.read_picture(str(outside / "secret.jpg"), str(media))
    with pytest.raises(NoPicture):
        folderart.read_picture(
            str(media / "Movies" / ".." / ".." / "outside" / "secret.jpg"), str(media)
        )
    with pytest.raises(NoPicture):
        await source._from(f"cover:0:mjpeg:{outside / 'Secret (2000).mkv'}")
    # A library's folders: only under the media folder.
    for bad in (str(outside), "../outside", str(movies / "Linked"), "/etc", str(media / "nothing")):
        with pytest.raises(NotFolder):
            source.checked_folders([bad])
    assert source.checked_folders(["Movies"]) == [real(movies)]


async def test_nfo_files_are_read_safely(tmp_path, clips, caplog):
    assert nfo.parse(b"<movie><title>Fine</title><year>1999</year></movie>")[0]["title"] == "Fine"
    for bad in (
        b'<!DOCTYPE movie [<!ENTITY x SYSTEM "file:///etc/passwd">]><movie><title>&x;</title></movie>',
        b'<!ENTITY lol "lol"><movie><title>x</title></movie>',
        b"<movie><title>Never closed",
        b"x" * (nfo.MOST_BYTES + 1),
    ):
        with pytest.raises(nfo.NfoError):
            nfo.parse(bad)
    # Only a web address is still worth reading: its ID.
    assert nfo.parse(b"https://www.imdb.com/title/tt9100001/")[0]["ids"] == {"imdb": "tt9100001"}
    source = make_source(tmp_path)
    movies = Path(source.settings.media_dir) / "Movies"
    put(movies / "Odd (2001)" / "Odd (2001).mkv", clips.plain)
    put(
        movies / "Odd (2001)" / "movie.nfo",
        text='<!DOCTYPE x [<!ENTITY a "b">]><movie><title>&a;</title></movie>',
    )
    lib = source.add_library("Movies", "movie", [str(movies)])
    caplog.set_level(logging.WARNING)
    await source.scan(lib.id)
    await source.scan(lib.id)
    said = [r for r in caplog.records if "skipped the NFO" in r.message]
    assert len(said) == 1  # (once, until it changes)
    odd = by_title(source, "movie")["Odd"]
    assert odd.details["title"][1] == "names"


async def test_libraries_are_kept_and_changed(tmp_path, clips):
    source = make_source(tmp_path)
    media = Path(source.settings.media_dir)
    sonarr_tv(media / "TV", clips)
    lib = source.add_library("  My   TV ", "show", ["TV"])
    assert lib.name == "My TV" and lib.folders == [real(media / "TV")]
    with pytest.raises(NotFolder):
        source.add_library("", "show", ["TV"])
    with pytest.raises(NotFolder):
        source.add_library("Clips", "clips", ["TV"])
    await source.scan(lib.id)
    assert (await source.libraries_list())[0] == {
        "key": "f1", "title": "My TV", "type": "show", "locations": [real(media / "TV")],
    }  # fmt: skip
    print_before = source.fingerprint()
    source.remove_library("f1")
    assert not source.things and not source.configured
    assert source.fingerprint() != print_before
    with pytest.raises(LibraryError):
        source.library("f1")
    remove(media / "TV")


async def _worst_stall(work):
    """How long `work` kept everything else waiting, at worst (the time an
    other task, waking every 10 ms, waited past its turn), and its result."""
    import asyncio
    import time

    stalls = [0.0]
    done = asyncio.Event()

    async def watch() -> None:
        while not done.is_set():
            t = time.monotonic()
            await asyncio.sleep(0.01)
            stalls.append(time.monotonic() - t - 0.01)

    watcher = asyncio.ensure_future(watch())
    try:
        result = await work
    finally:
        done.set()
        await watcher
    return max(stalls), result


def _many_shows(tv: Path, shows: int, episodes: int) -> None:
    """Shows of empty episodes, each file its own size (for renames)."""
    for s in range(shows):
        season = tv / f"Show {s:03d} (2010)" / "Season 01"
        season.mkdir(parents=True)
        for e in range(1, episodes + 1):
            with open(season / f"Show {s:03d} (2010) - S01E{e:02d}.mkv", "wb") as f:
                f.truncate(10_000 + s * 100 + e)


def _renamed_shows(tv: Path, shows: int) -> None:
    for s in range(shows):
        (tv / f"Show {s:03d} (2010)").rename(tv / f"Show {s:03d} (2010) {{tvdb-{90000 + s}}}")


def _many_movies(movies: Path, count: int, sets: int) -> None:
    for n in range(count):
        folder = movies / f"Film {n:04d} ({1950 + n % 70})"
        folder.mkdir(parents=True)
        with open(folder / f"Film {n:04d} ({1950 + n % 70}).mkv", "wb") as f:
            f.truncate(20_000 + n)
        (folder / "movie.nfo").write_text(
            f"<movie><title>Film {n:04d}</title><set><name>Set {n % sets:03d}</name></set></movie>"
        )


def _renamed(path: str) -> str:
    old = Path(path)
    new = old.with_name(old.stem + " - Renamed.mkv")
    old.rename(new)
    return str(new)


async def test_a_big_library_never_holds_everything_else_up(tmp_path, monkeypatch):
    """Reading a big Media folder (20,000 episodes here) never keeps tapiOca
    from everything else it does (playing, its page, the apps) for long: not
    the first scan, not a scan that finds nothing new, not one that finds
    hundreds of files renamed. (1.35.0's check at 50,000 episodes found its
    first scan holding everything up for 35 seconds, and every rescan for
    7.)"""
    import asyncio

    probed = folderscan._small({
        "format": {"duration": "1320.0", "format_name": "matroska,webm"},
        "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264",
                     "width": 1280, "height": 720}],
    })  # fmt: skip

    async def read(ffprobe, path, timeout=60.0):
        await asyncio.sleep(0)
        return dict(probed)

    monkeypatch.setattr(folderscan, "read_file", read)
    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    _many_shows(tv, 400, 50)
    lib = source.add_library("TV", "show", [str(tv)])
    stall, changed = await _worst_stall(source.scan(lib.id))
    assert changed and source.counts(lib.id)["episode"] == 20_000
    assert stall < 1.0, f"the first scan held everything up for {stall:.1f}s"
    stall, changed = await _worst_stall(source.scan(lib.id))
    assert not changed
    assert stall < 1.0, f"a scan finding nothing new held everything up for {stall:.1f}s"
    # Every episode of 10 shows renamed: each keeps its key.
    renamed = {}
    for t in list(source.things.values()):
        show = source.things.get(t.show) if t.kind == "episode" else None
        if show is not None and show.path.endswith(
            tuple(f"Show {s:03d} (2010)" for s in range(10))
        ):
            renamed[_renamed(t.files[0][0])] = t.id
    assert len(renamed) == 500
    stall, changed = await _worst_stall(source.scan(lib.id))
    assert changed and source.counts(lib.id)["episode"] == 20_000
    assert {p: t.id for t in source.things.values() for v in t.files for p in v
            if p in renamed} == renamed  # fmt: skip
    assert stall < 1.0, f"a scan finding renamed files held everything up for {stall:.1f}s"
    # A station of the whole library: its programs worked out the same way.
    stall, items = await _worst_stall(
        source.items_for_source({"type": "section", "key": lib.key, "sectionType": "show"})
    )
    assert len(items) == 20_000
    assert stall < 1.0, f"a station of every episode held everything up for {stall:.1f}s"
    # Every show's folder renamed (as when Sonarr renames them all): found
    # again by title and year, each episode in its place.
    keys = {t.id for t in source.things.values()}
    _renamed_shows(tv, 400)
    stall, changed = await _worst_stall(source.scan(lib.id))
    assert changed and {t.id for t in source.things.values()} == keys
    assert stall < 1.0, f"a scan finding every show renamed held everything up for {stall:.1f}s"
    # 3,000 movies in 400 collections (each movie.nfo's <set>): the
    # collections listed, as the station editor and the hourly check do.
    movies = Path(source.settings.media_dir) / "Movies"
    _many_movies(movies, 3000, 400)
    films = source.add_library("Movies", "movie", [str(movies)])
    await source.scan(films.id)
    stall, collections = await _worst_stall(source.collections())
    assert len(collections) == 400 and sum(c["count"] for c in collections) == 3000
    assert stall < 1.0, f"listing collections held everything up for {stall:.1f}s"


async def test_a_library_removed_while_its_being_read_stays_removed(tmp_path, clips, monkeypatch):
    """An Admin removes a Media folder while tapiOca is reading it: when the
    reading ends, nothing of it comes back, in tapiOca or in its database."""
    import asyncio
    import sqlite3

    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    sonarr_tv(tv, clips)
    lib = source.add_library("TV", "show", [str(tv)])
    reading = asyncio.Event()
    go_on = asyncio.Event()
    real_read = folderscan.read_file

    async def slow(ffprobe, path, timeout=60.0):
        reading.set()
        await go_on.wait()
        return await real_read(ffprobe, path, timeout)

    monkeypatch.setattr(folderscan, "read_file", slow)
    scan = asyncio.ensure_future(source.scan(lib.id))
    await reading.wait()
    source.remove_library(lib.key)
    go_on.set()
    assert not await scan
    assert source.things == {} and source.libraries == {}
    with sqlite3.connect(tmp_path / "data" / "stationplay.db") as db:
        assert db.execute("SELECT COUNT(*) FROM folder_items").fetchone() == (0,)
    again = make_source(tmp_path)  # (as after a restart)
    assert again.things == {} and again.libraries == {}


async def test_read_again_many_times_reads_once_more(tmp_path, clips, monkeypatch):
    """Read again chosen over and over (or Sonarr saying files arrived, one
    after another) while a Media folder is being read: it's read once more
    when that's done, not once for each."""
    import asyncio

    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    sonarr_tv(tv, clips)
    lib = source.add_library("TV", "show", [str(tv)])
    go_on = asyncio.Event()
    real_read = folderscan.read_file

    async def slow(ffprobe, path, timeout=60.0):
        await go_on.wait()
        return await real_read(ffprobe, path, timeout)

    monkeypatch.setattr(folderscan, "read_file", slow)
    scans = []
    real_scan = source._scan

    async def counted(lib_):
        scans.append(lib_.id)
        return await real_scan(lib_)

    monkeypatch.setattr(source, "_scan", counted)
    source.scan_soon(lib.id)
    await asyncio.sleep(0.05)
    for _ in range(5):
        source.scan_soon(lib.id)
        await source.scan_folder(lib.key, str(tv))
    go_on.set()
    while source._tasks:
        await asyncio.gather(*list(source._tasks))
    assert scans == [lib.id, lib.id]


def test_a_link_back_into_the_folder_is_walked_once(tmp_path):
    """A link inside the media folder to a folder already being walked (its
    own folder, or one above it) isn't walked again: no title twice, and no
    going round and round."""
    media = tmp_path / "media"
    season = media / "TV" / "Show (2010)" / "Season 01"
    season.mkdir(parents=True)
    (season / "Show (2010) - S01E01.mkv").touch()
    os.symlink(media / "TV", season / "Back to TV")
    os.symlink(media / "TV" / "Show (2010)", media / "TV" / "Show Again")
    walked = folderscan.walk(str(media / "TV"), str(media))
    assert [os.path.basename(p) for p, _, _ in walked.videos] == ["Show (2010) - S01E01.mkv"]


def test_a_folder_inside_another_of_its_own_isnt_taken(tmp_path):
    """One Media folder's folders never hold one another (its titles would
    be listed twice); a folder in two Media folders is fine, as in Plex."""
    source = make_source(tmp_path)
    media = Path(source.settings.media_dir)
    (media / "TV" / "Kids").mkdir(parents=True)
    (media / "Cartoons").mkdir()
    for nested in (["TV", "TV/Kids"], ["TV/Kids", "TV"]):
        with pytest.raises(NotFolder) as refused:
            source.checked_folders(nested)
        assert "TV/Kids is inside TV" in str(refused.value)
    assert source.checked_folders(["TV", "Cartoons"]) == [
        real(media / "TV"),
        real(media / "Cartoons"),
    ]
    source.add_library("TV", "show", ["TV"])
    source.add_library("Kids", "show", ["TV/Kids"])


async def test_a_name_that_isnt_utf8_is_skipped_and_said(tmp_path, clips, caplog):
    """A file whose name isn't UTF-8 (a Latin-1 "é", as on older NAS shares
    and SMB copies) is skipped, and the Logs tab says so: the rest of the
    Media folder is read as ever."""
    source = make_source(tmp_path)
    movies = Path(source.settings.media_dir) / "Movies"
    put(movies / "Plain (2011)" / "Plain (2011).mkv", clips.plain)
    odd = os.fsencode(str(movies)) + b"/Am\xe9lie (2001).mkv"
    shutil.copyfile(os.fsencode(str(clips.plain)), odd)
    os.mkdir(os.fsencode(str(movies)) + b"/Caf\xe9 (2003)")
    lib = source.add_library("Movies", "movie", [str(movies)])
    with caplog.at_level(logging.WARNING):
        assert await source.scan(lib.id)
    assert set(by_title(source, "movie")) == {"Plain"}
    said = [r.getMessage() for r in caplog.records if "UTF-8" in r.getMessage()]
    assert said == [
        "tapiOca skipped 2 files or folders in the Media folder “Movies” because their names "
        "aren’t UTF-8, such as Am\N{REPLACEMENT CHARACTER}lie (2001).mkv. Rename them, and "
        "tapiOca will read them."
    ]


async def test_a_scan_that_fails_is_said_and_shown(tmp_path, clips, monkeypatch, caplog):
    """Reading a Media folder that fails for any reason is said on the Logs
    tab, and its row on the page says so, instead of "Not read yet" for good."""
    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    sonarr_tv(tv, clips)
    lib = source.add_library("TV", "show", [str(tv)])

    def broken(*_args, **_kwargs):
        raise RuntimeError("the disk said no")

    monkeypatch.setattr(folderscan, "build", broken)
    with caplog.at_level(logging.ERROR):
        assert not await source.scan(lib.id)
    assert any("Reading the Media folder “TV” failed" in r.getMessage() for r in caplog.records)
    [row] = source.status()
    assert row["problem"] == "It couldn’t be read. The Logs tab says why."
    monkeypatch.undo()
    assert await source.scan(lib.id)
    [row] = source.status()
    assert row["problem"] is None and row["scannedMs"]


async def test_an_upgraded_movie_keeps_its_key(tmp_path, clips):
    """Radarr upgrades a movie: a better file (another name and size) in its
    folder, and the old one deleted. It keeps its key, as in Plex: a title
    hidden by its key stays hidden, and a station made of it still is."""
    from app.viewing import Blocks

    from .folderlib import movie_nfo

    source = make_source(tmp_path)
    movies = Path(source.settings.media_dir) / "Movies"
    folder = movies / "Tidewater Night (1975)"
    old = put(folder / "Tidewater Night (1975) - WEBDL-720p.mkv", clips.plain)
    put(folder / "movie.nfo", text=movie_nfo("Tidewater Night", 1975, "A night.", tmdb="99"))
    lib = source.add_library("Movies", "movie", [str(movies)])
    await source.scan(lib.id)
    key = by_title(source, "movie")["Tidewater Night"].key
    hidden = Blocks.from_json({"titles": [{"key": key, "title": "Tidewater Night"}]})
    put(folder / "Tidewater Night (1975) - Bluray-1080p.mkv", clips.tagged)
    remove(old)
    await source.scan(lib.id)
    assert by_title(source, "movie")["Tidewater Night"].key == key
    assert hidden.hides(key, None)
    [item] = await source.items_for_source({"type": "movie", "ratingKey": key})
    assert item.file_path.endswith("Bluray-1080p.mkv")


async def test_a_folder_that_cant_be_read_for_a_moment_keeps_its_keys(tmp_path, clips, monkeypatch):
    """One show's folder can't be read during one scan (a network share's
    hiccup on that folder alone): it's kept as it was, missing, not deleted,
    and keeps its keys when it can be read again."""
    import errno

    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    files = sonarr_tv(tv, clips)
    lib = source.add_library("TV", "show", [str(tv)])
    await source.scan(lib.id)
    show = by_title(source, "show")["Northbound"]
    keys = {t.id for t in source.things.values() if t.kind != "collection"}
    real_scandir = os.scandir

    def flaky(path="."):
        if str(path) == str(files["show"]):
            raise OSError(errno.ESTALE, "Stale file handle")
        return real_scandir(path)

    monkeypatch.setattr(folderscan.os, "scandir", flaky)
    await source.scan(lib.id)
    assert by_title(source, "show")["Northbound"].missing
    monkeypatch.setattr(folderscan.os, "scandir", real_scandir)
    await source.scan(lib.id)
    assert by_title(source, "show")["Northbound"].key == show.key
    assert not by_title(source, "show")["Northbound"].missing
    assert {t.id for t in source.things.values() if t.kind != "collection"} == keys
    assert await source.items_for_source({"type": "show", "ratingKey": show.key})


async def test_a_long_unmounted_share_keeps_its_programs_on_stations(tmp_path, clips, monkeypatch):
    """A share unmounted for longer than tapiOca keeps what it read of files
    no longer seen (30 days): its programs, kept, stay on stations."""
    import asyncio

    from app import folders

    source = make_source(tmp_path)
    media = Path(source.settings.media_dir)
    sonarr_tv(media / "TV", clips)
    lib = source.add_library("TV", "show", [str(media / "TV")])
    await source.scan(lib.id)
    section = {"type": "section", "key": lib.key, "sectionType": "show"}
    before = len(await source.items_for_source(section))
    os.rename(media / "TV", media / "unmounted")
    await asyncio.sleep(0.01)
    monkeypatch.setattr(folders, "FORGET_UNSEEN_S", 0)  # (as if 30 days went by)
    await source.scan(lib.id)
    assert before and len(await source.items_for_source(section)) == before


def test_a_link_to_another_show_doesnt_take_it_over(tmp_path):
    """A link inside one show's folder to another show's folder: the other
    show is its own, and the link adds nothing."""
    media = tmp_path / "media"
    for show in ("Alpha Show", "Beta Show"):
        season = media / "TV" / show / "Season 01"
        season.mkdir(parents=True)
        (season / f"{show} - S01E01.mkv").touch()
    os.symlink(media / "TV" / "Beta Show", media / "TV" / "Alpha Show" / "See also Beta")
    walked = folderscan.walk(str(media / "TV"), str(media))
    found = folderscan.build("show", walked, {}, lambda p: None)
    shows = sorted(os.path.basename(f.path) for f in found if f.kind == "show")
    assert shows == ["Alpha Show", "Beta Show"]
    for f in found:
        if f.kind == "episode":
            assert len(f.files) == 1 and "See also" not in f.files[0][0]


def test_a_specials_folder_among_shows_is_its_own(tmp_path):
    """A Shows Media folder holding many shows and one folder named like a
    season ("Specials", "Season 1"): each show stays its own."""
    media = tmp_path / "media"
    tv = media / "TV"
    for path in (
        "Northbound (2019)/Season 01/Northbound (2019) - S01E01.mkv",
        "Orbit Room/Season 01/Orbit Room - S01E01.mkv",
        "Specials/Holiday Hour - S00E01.mkv",
    ):
        (tv / path).parent.mkdir(parents=True, exist_ok=True)
        (tv / path).touch()
    found = folderscan.build("show", folderscan.walk(str(tv), str(media)), {}, lambda p: None)
    shows = sorted(os.path.basename(f.path) for f in found if f.kind == "show")
    assert "Northbound (2019)" in shows and "Orbit Room" in shows
    assert all(len(f.files) == 1 for f in found if f.kind == "episode")


def test_programs_named_sample_or_shorts_are_kept(tmp_path):
    """A full-size episode with "Sample" in its title, and a show whose
    folder is named "Shorts", are programs; a small file named a sample, and
    a Shorts folder inside a show's, aren't."""
    from app import folderscan as fs

    media = tmp_path / "media"
    tv = media / "TV"
    big = tv / "Northbound (2019)" / "Season 02" / "Northbound (2019) - S02E05 - Free Sample.mkv"
    small = tv / "Northbound (2019)" / "Season 02" / "Northbound (2019) - S02E06-sample.mkv"
    shorts = tv / "Shorts" / "Season 01" / "Shorts - S01E01.mkv"
    extra = tv / "Northbound (2019)" / "Shorts" / "Behind it.mkv"
    for path in (big, small, shorts, extra):
        path.parent.mkdir(parents=True, exist_ok=True)
    for path, size in ((big, fs.NAMED_SAMPLE_BYTES), (small, 10), (shorts, 10), (extra, 10)):
        with open(path, "wb") as f:
            f.truncate(size)
    walked = folderscan.walk(str(tv), str(media))
    assert sorted(os.path.basename(p) for p, _, _ in walked.videos) == [big.name, shorts.name]


async def test_a_stations_show_put_back_under_a_new_key_is_followed(tmp_path, clips):
    """A show taken out of its Media folder and put back later has a new
    key: a station made of it finds it again by its title, as with Plex."""
    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    files = sonarr_tv(tv, clips)
    lib = source.add_library("TV", "show", [str(tv)])
    await source.scan(lib.id)
    old = by_title(source, "show")["Northbound"].key
    source_ = {"type": "show", "ratingKey": old, "title": "Northbound"}
    before = [i.title for i in await source.items_for_source(source_)]
    os.rename(files["show"], tmp_path / "away")
    await source.scan(lib.id)
    assert "Northbound" not in by_title(source, "show")
    os.rename(tmp_path / "away", files["show"])
    await source.scan(lib.id)
    assert by_title(source, "show")["Northbound"].key != old
    assert [i.title for i in await source.items_for_source(source_)] == before
    with pytest.raises(LibraryError) as gone:
        await source.items_for_source({"type": "show", "ratingKey": old, "title": "Nothing"})
    assert gone.value.status == 404


def test_an_nfo_full_of_addresses_is_read_quickly():
    """An NFO that's just a web address written over and over (anything that
    can write into the media folder could leave one) is read in moments, not
    minutes: reading it never holds tapiOca up."""
    import time

    for data in (b"thetvdb.com/" * 80_000, b"https://thetvdb.com/x" * 40_000):
        began = time.monotonic()
        with pytest.raises(nfo.NfoError):
            nfo.parse(data[: nfo.MOST_BYTES])
        assert time.monotonic() - began < 0.5
    said = nfo.parse(b"https://thetvdb.com/?tab=series&id=81111\n")
    assert said == [{"kind": "", "ids": {"tvdb": "81111"}}]
    said = nfo.parse(b"https://www.thetvdb.com/series/81112-northbound\n")
    assert said[0]["ids"] == {"tvdb": "81112"}


@pytest.mark.parametrize(
    ("written", "age"),
    [
        ("R", 17), ("Rated R", 17), ("rated PG-13", 13), ("US:R", 17), ("US:PG-13", 13),
        ("US:TV-MA", 17), ("UK:18", 18), ("UK:PG", 10), ("gb/15", 15), ("de:FSK 12", 12),
        ("Germany:16", 16), ("R (for violence)", 17), ("PG-13 for some language", 13),
        ("GB-15", 15), ("DE-16", 16), ("gb-18", 18), ("AU-MA15+", 15),
        ("Rated NC-17", 18), ("TV-14", 14), ("Not Rated", None), ("NR", None),
        ("Unrated", None), ("", None),
    ],
)  # fmt: skip
def test_ratings_in_nfo_files_are_read_as_plexs_are(written, age):
    """(1.35.0's audit) Kodi and other tools write a rating many ways:
    each is read as the age it means, so a Viewing Level judges it as it
    would Plex's, never as unrated when it's rated."""
    from app import ratings

    data = f"<movie><title>Tidewater</title><mpaa>{written}</mpaa></movie>".encode()
    got = nfo.parse(data)[0].get("content_rating")
    assert ratings.age(got) == age, (written, got)


def test_titles_from_names_are_titles_not_file_names(tmp_path):
    """When nothing but a file's name says what it is, its title is made
    from it, as words, its release details left out: tapiOca's apps never get
    a file's name as it is."""
    media = tmp_path / "media"
    tv = media / "TV"
    for rel in (
        "Coastline/Season 01/Coastline.2010.Special.1080p.WEB-DL.x264-GRP.mkv",
        "dad_bday_party_2019-final.mkv",
    ):
        (tv / rel).parent.mkdir(parents=True, exist_ok=True)
        (tv / rel).touch()
    source = FolderSource(
        Database(tmp_path / "data" / "stationplay.db"),
        Settings(media_dir=str(media), data_dir=tmp_path / "data"),
    )
    titles = []
    for f in folderscan.build("show", folderscan.walk(str(tv), str(media)), {}, lambda p: None):
        t = folders_thing(f)
        titles.append(source.title_of(t))
    assert "Coastline 2010 Special" in titles and "dad bday party 2019-final" in titles
    for title in titles:
        assert not any(bit in title for bit in ("1080p", "WEB-DL", "x264", "_", ".mkv")), title
    # A name that's nothing but a release's details, or starts with a release
    # group's tag: no title from it (its folder's, then), and no tag.
    from app import naming

    assert naming.title_from("1080p.WEB-DL.x264-GRP.mkv") == ""
    assert naming.title_from("[SubsPlease] Harbor Lights - 01 (1080p) [ABCD].mkv") == (
        "Harbor Lights - 01"
    )
    from app.folders import _named

    assert _named("/media/Movies/Some Film (2004)/1080p.WEB-DL.x264-GRP.mkv") == "Some Film"
    assert _named("/media/Movies/x264/1080p.mkv") == "Untitled"


def folders_thing(f):
    from app.folders import Thing

    t = Thing(1, 1, f.kind, f.path, local=f.local)
    t.details = dict(f.local)
    return t


async def test_a_versions_id_stays_when_another_comes(tmp_path, clips):
    """A movie's versions keep their ids when another version is added
    (and sorts before them): what an app chose, or a broken file noted, is
    still the same file."""
    source = make_source(tmp_path)
    movies = Path(source.settings.media_dir) / "Movies"
    folder = movies / "Low Tide (1995)"
    put(folder / "Low Tide (1995) - 1080p.mkv", clips.plain)
    put(folder / "Low Tide (1995) - 720p.mkv", clips.plain)
    lib = source.add_library("Movies", "movie", [str(movies)])
    await source.scan(lib.id)
    movie = by_title(source, "movie")["Low Tide"]

    def ids() -> dict[str, str]:
        t = source.things[movie.id]
        return {os.path.basename(m.file): m.id for m in source._media(t, source._probes(
            [p for v in t.files for p in v]))}  # fmt: skip

    before = ids()
    put(folder / "Low Tide (1995) - 4K.mkv", clips.tagged)
    await source.scan(lib.id)
    after = ids()
    assert len(after) == 3 and all(after[name] == vid for name, vid in before.items())
    assert all(vid.isdigit() and "Low" not in vid for vid in after.values())


async def test_a_file_swapped_for_a_link_out_is_never_played(tmp_path, clips):
    """A video swapped for a link to a file outside the media folder after
    it was read: it's never played (the scan never reads one, and playing
    checks again)."""
    source = make_source(tmp_path)
    movies = Path(source.settings.media_dir) / "Movies"
    video = put(movies / "Low Tide (1995)" / "Low Tide (1995).mkv", clips.plain)
    secret = put(tmp_path / "outside" / "secret.mkv", clips.plain)
    lib = source.add_library("Movies", "movie", [str(movies)])
    await source.scan(lib.id)
    from app import sources
    from app.library import Library
    from app.plex import PlexClient

    library = Library(PlexClient("", ""), source)
    [item] = await source.items_for_source({"type": "movie", "ratingKey": by_title(
        source, "movie")["Low Tide"].key})  # fmt: skip
    found = await sources.resolve_source(source.settings, library, item)
    assert found.source == real(video)
    remove(video)
    os.symlink(secret, video)
    found = await sources.resolve_source(source.settings, library, item)
    assert found.source is None and found.error
    access = sources.MediaAccess()
    assert await sources.find_file(source.settings, access, item.rating_key, str(video)) == (
        None, False
    )  # fmt: skip


async def test_a_season_folder_that_cant_be_read_for_a_moment_keeps_its_show(
    tmp_path, clips, monkeypatch, caplog
):
    """A show's only season folder can't be read during one scan (a share's
    hiccup): the show and its episodes are kept, missing, with their keys;
    the Logs tab and the page say which folder; playing one meanwhile is
    a passing trouble, never a broken file; and once the folder can be read
    again, all is as it was."""
    import errno

    from app import sources
    from app.library import Library
    from app.plex import PlexClient

    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    season = tv / "Harbor Lights (2015)" / "Season 01"
    put(season / "Harbor Lights (2015) - S01E01.mkv", clips.plain)
    put(tv / "Other Show" / "Season 01" / "Other Show - S01E01.mkv", clips.plain)
    lib = source.add_library("TV", "show", [str(tv)])
    await source.scan(lib.id)
    keys = {t.id for t in source.things.values()}
    show = by_title(source, "show")["Harbor Lights"]
    [item] = await source.items_for_source({"type": "show", "ratingKey": show.key})
    real_scandir = os.scandir

    def flaky(path="."):
        if str(path) == str(season):
            raise OSError(errno.ESTALE, "Stale file handle")
        return real_scandir(path)

    monkeypatch.setattr(folderscan.os, "scandir", flaky)
    with caplog.at_level(logging.WARNING):
        await source.scan(lib.id)
    assert {t.id for t in source.things.values()} == keys
    assert by_title(source, "show")["Harbor Lights"].missing
    assert any(str(season) in r.getMessage() for r in caplog.records)
    [row] = source.status()
    assert str(season) in row["missingFolders"]
    assert await source.items_for_source({"type": "show", "ratingKey": show.key})
    os.rename(season, tmp_path / "away")  # (and its files can't be opened either)
    played = await sources.resolve_source(
        source.settings, Library(PlexClient("", ""), source), item
    )
    assert played.source is None and played.transient
    assert "Plex" not in (played.error or "")
    os.rename(tmp_path / "away", season)
    monkeypatch.setattr(folderscan.os, "scandir", real_scandir)
    await source.scan(lib.id)
    assert {t.id for t in source.things.values()} == keys
    assert not any(t.missing for t in source.things.values())
    [row] = source.status()
    assert row["missingFolders"] == []


async def test_a_different_movie_in_a_shared_folder_gets_a_key_of_its_own(tmp_path, clips):
    """Movies loose in one folder: one deleted and another added before the
    next scan. The new one is another movie, with a key of its own (the same
    key always means the same title); a movie upgraded there keeps its own."""
    source = make_source(tmp_path)
    movies = Path(source.settings.media_dir) / "Movies"
    alpha = put(movies / "Alpha Dawn (2001).mkv", clips.plain)
    beta = put(movies / "Beta Dusk (2002) WEBDL-720p.mkv", clips.plain)
    lib = source.add_library("Movies", "movie", [str(movies)])
    await source.scan(lib.id)
    before = {title: t.key for title, t in by_title(source, "movie").items()}
    remove(alpha)
    put(movies / "Gamma Night (2003).mkv", clips.plain)
    remove(beta)
    put(movies / "Beta Dusk (2002) Bluray-1080p.mkv", clips.dark_start)
    await source.scan(lib.id)
    after = {title: t.key for title, t in by_title(source, "movie").items()}
    assert set(after) == {"Beta Dusk", "Gamma Night"}
    assert after["Gamma Night"] not in before.values()
    assert after["Beta Dusk"] == before["Beta Dusk"]


def test_browsing_a_folder_with_a_name_that_isnt_utf8(tmp_path):
    """Choosing folders: one holding a name that isn't UTF-8 is listed
    without it (it can't be read), never an error."""
    from app.folders import _folders_in

    media = tmp_path / "media"
    (media / "Movies" / "Plain").mkdir(parents=True)
    os.mkdir(os.fsencode(str(media / "Movies")) + b"/Caf\xe9")
    found = _folders_in(str(media), "Movies")
    assert found is not None and found["folders"] == ["Plain"]
    import json

    json.dumps(found)


def test_a_short_film_beside_a_feature_isnt_a_sample(tmp_path):
    """Movies loose in one folder: a short film beside a feature is a movie
    of its own, not the feature's sample (that's a small file of the same
    movie)."""
    media = tmp_path / "media"
    movies = media / "Movies"
    movies.mkdir(parents=True)
    for name, size in (
        ("Long Feature (1999).mkv", 1500 << 20),
        ("Little Rabbit Cartoon (1941).mkv", 40 << 20),
        ("Other Feature (2001)/Other Feature (2001).mkv", 1500 << 20),
        ("Other Feature (2001)/Other Feature (2001) - preview.mkv", 20 << 20),
    ):
        (movies / name).parent.mkdir(parents=True, exist_ok=True)
        with open(movies / name, "wb") as f:
            f.truncate(size)
    found = folderscan.build("movie", folderscan.walk(str(movies), str(media)), {}, lambda p: None)
    titles = sorted(f.local["title"][0] for f in found)
    assert titles == ["Little Rabbit Cartoon", "Long Feature", "Other Feature"]
    other = next(f for f in found if f.local["title"][0] == "Other Feature")
    assert len(other.files) == 1  # (its preview is its sample)


async def test_a_media_folder_that_cant_be_read_waits_its_turn(tmp_path, clips, monkeypatch):
    """A Media folder whose reading fails is tried again in 6 hours (or on
    Read again), as the Logs tab says: not every few minutes."""
    from app import folders

    source = make_source(tmp_path)
    tv = Path(source.settings.media_dir) / "TV"
    sonarr_tv(tv, clips)
    source.add_library("TV", "show", [str(tv)])
    tries = []

    def broken(*_args, **_kwargs):
        tries.append(1)
        raise RuntimeError("the disk said no")

    monkeypatch.setattr(folderscan, "build", broken)
    monkeypatch.setattr(folders, "STARTUP_DELAY_S", 0)
    monkeypatch.setattr(folders, "LOOK_EVERY_S", 0.05)
    task = asyncio.ensure_future(source.run_forever())
    try:
        await asyncio.sleep(1.0)
    finally:
        task.cancel()
    assert len(tries) == 1


def test_one_files_nfo_names_at_most_so_many_episodes(tmp_path):
    """An NFO beside one file can't make it thousands of episodes: as many
    as a file's name can (RANGE_MOST), at most."""
    from app import naming

    media = tmp_path / "media"
    season = media / "TV" / "Show" / "Season 01"
    season.mkdir(parents=True)
    (season / "Show - S01E01.mkv").touch()
    many = "".join(
        f"<episodedetails><title>E{n}</title><season>1</season><episode>{n}</episode></episodedetails>"
        for n in range(1, 2000)
    )
    (season / "Show - S01E01.nfo").write_text(many)

    def nfos(path):
        return nfo.parse(open(path, "rb").read())

    found = folderscan.build("show", folderscan.walk(str(media / "TV"), str(media)), {}, nfos)
    assert 1 <= sum(f.kind == "episode" for f in found) <= naming.RANGE_MOST


async def test_a_hung_share_is_checked_once_at_a_time_for_own_folders(tmp_path, monkeypatch):
    """Where pictures cut is looked for on a share that hangs: for a Media
    folder of your own's program, as for Plex's, one check of the share is
    left waiting at a time, never one more each time."""
    import threading

    from app import sources
    from app.db import Item

    release = threading.Event()
    started = []

    def hung(*_args, **_kwargs):
        started.append(1)
        release.wait(30)

    monkeypatch.setattr(sources, "_own_file", hung)
    monkeypatch.setattr(sources, "SHARE_WAIT_S", 0.2)
    settings = Settings(media_dir=str(tmp_path / "media"), data_dir=tmp_path / "data")
    item = Item(position=0, start_ms=0, duration_ms=1000, rating_key="f12", kind="movie",
                title="Tidewater", file_path=str(tmp_path / "media" / "T.mkv"))  # fmt: skip

    class NoLibrary:
        configured = False

    check = sources.ShareCheck()
    try:
        for _ in range(4):
            found = await sources.readable(
                settings, NoLibrary(), item, sources.MediaAccess(), check
            )
            assert found.source is None and found.transient
        assert len(started) == 1
    finally:
        release.set()
