"""Your library in StationPlay's apps (ondemand.py, applibrary.py): sharing
libraries, what the apps are shown, whether a device can play a file as it
is, playing, and each person's progress. The contract itself is checked in
test_app_api.py."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app import applibrary, catalog, converting, ondemand
from app import plex as plex_module
from app.catalog import Entry, Media, Track
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex

PUBLIC_PORT = 8443
ADMIN = {"name": "Pat", "password": "correct horse"}
# What a 4K HDR TV box says it plays (Android TV, say).
TV = {
    "containers": ["mkv", "mp4", "mov", "ts", "webm"],
    "video": [
        {"codec": "h264", "width": 3840, "height": 2160, "bitDepth": 8},
        {"codec": "hevc", "width": 3840, "height": 2160, "bitDepth": 10},
    ],
    "hdr": ["hdr10", "hlg"],
    "audio": ["aac", "ac3", "eac3", "mp3", "opus", "flac"],
}


# Can a device play it as it is? ---------------------------------------------------------


def media(**changes) -> Media:
    plain = {
        "container": "mkv",
        "video": "h264",
        "width": 1920,
        "height": 1080,
        "audio": (Track("1", "aac", "English", default=True),),
    }
    return Media(**{**plain, **changes})


TV_BOX = ondemand.device(
    TV["containers"],
    [(v["codec"], v["width"], v["height"], v["bitDepth"]) for v in TV["video"]],
    TV["hdr"],
    TV["audio"],
)


def test_a_file_the_device_can_play_plays_as_it_is():
    assert ondemand.unplayable(media(), TV_BOX) == []
    # (Whatever the library calls them.)
    assert (catalog.container("matroska"), catalog.video_codec("AVC")) == ("mkv", "h264")
    assert (catalog.audio_codec("dca"), catalog.subtitle_codec("subrip")) == ("dts", "srt")
    hdr = media(video="hevc", width=3840, height=2160, bit_depth=10, hdr=catalog.HDR10)
    assert ondemand.unplayable(hdr, TV_BOX) == []
    # Dolby Vision 8 has an HDR10 picture beneath it, which this TV shows.
    assert ondemand.unplayable(media(video="hevc", hdr=catalog.HDR10, dv_profile=8), TV_BOX) == []
    # What the library didn't say isn't held against it.
    assert ondemand.unplayable(Media(container="", video=""), TV_BOX) == []


def test_why_a_device_cant_play_a_file_as_it_is():
    cases = [
        (media(container="avi"), ["its file type (AVI)"]),
        (media(video="vc1"), ["its picture's format (VC-1)"]),
        (media(width=7680, height=4320), ["its picture size (4K)"]),
        (media(video="hevc", bit_depth=12), ["its 12-bit picture"]),
        (media(video="hevc", dv_profile=5), ["its Dolby Vision profile 5 picture"]),
        (media(audio=(Track("1", "dts", default=True),)), ["its sound's format (DTS)"]),
        (media(parts=2, container="avi"), ["its file type (AVI)"]),  # (its first file plays)
    ]
    for found, why in cases:
        assert ondemand.unplayable(found, TV_BOX) == why, found
    sdr = ondemand.device(["mkv"], [("h264", 1920, 1080, 8)], [], ["aac"])
    assert ondemand.unplayable(media(hdr=catalog.HLG), sdr) == ["its HLG picture"]
    assert ondemand.unplayable(media(hdr=catalog.HDR10, dv_profile=8), sdr) == ["its HDR10 picture"]
    # Dolby Vision 8 over an ordinary picture plays as that picture.
    assert ondemand.unplayable(media(dv_profile=8), sdr) == []
    # A Dolby Vision screen shows any Dolby Vision picture.
    dv_only = ondemand.device(["mkv"], [("hevc", 3840, 2160, 10)], ["dv"], ["aac"])
    assert ondemand.unplayable(media(video="hevc", hdr=catalog.HDR10, dv_profile=7), dv_only) == []
    assert ondemand.unplayable(media(video="hevc", dv_profile=5), dv_only) == []
    assert ondemand.unplayable(media(video="hevc", hdr=catalog.HLG), dv_only) == ["its HLG picture"]
    # The default sound track is the one that counts.
    two = (Track("1", "truehd"), Track("2", "ac3", default=True))
    assert ondemand.unplayable(media(audio=two), TV_BOX) == []
    assert ondemand.cant_play(
        ["its file type (AVI)", "its 12-bit picture", "its sound's format (DTS)"]
    ) == (
        "This device can't play this file as it is (its file type (AVI), its 12-bit picture and "
        "its sound's format (DTS)), and this app can't take a copy made for it. Update the app "
        "to play it."
    )


def test_the_best_version_the_device_can_play_is_chosen():
    entry = Entry("1", catalog.MOVIE, "Two Versions", media=(media(container="avi"), media()))
    chosen, why = ondemand.choose(entry, TV_BOX)
    assert chosen is entry.media[1] and why == []
    only = Entry("1", catalog.MOVIE, "One", media=(media(container="avi"),))
    assert ondemand.choose(only, TV_BOX) == (None, ["its file type (AVI)"])
    # The best first: the biggest picture, HDR before not, then the most detail.
    sd = media(id="sd", width=720, height=480, bitrate_kbps=2_000)
    hd = media(id="hd", bitrate_kbps=8_000)
    hd_more = media(id="hd2", bitrate_kbps=12_000)
    uhd = media(id="uhd", video="hevc", width=3840, height=2160, bit_depth=10, bitrate_kbps=40_000)
    hdr = media(id="hdr", video="hevc", width=3840, height=2160, bit_depth=10, hdr=catalog.HDR10)
    many = Entry("2", catalog.MOVIE, "Many", media=(sd, hd, uhd, hd_more, hdr))
    assert [m.id for m in ondemand.best_first(many.media)] == ["hdr", "uhd", "hd2", "hd", "sd"]
    names = ondemand.version_labels(ondemand.best_first(many.media))
    assert list(names.values()) == ["4K · HDR10", "4K", "1080p · 12 Mbps", "1080p · 8 Mbps", "480p"]
    assert ondemand.choose(many, TV_BOX)[0] is hdr
    # A 1080p screen without HDR gets the best it can play; one asked for plays if it can.
    hd_box = ondemand.device(["mkv"], [("h264", 1920, 1080, 8)], [], ["aac"])
    assert ondemand.choose(many, hd_box)[0] is hd_more
    assert ondemand.choose(many, hd_box, "sd")[0] is sd
    assert ondemand.choose(many, hd_box, "uhd") == (None, ["its picture's format (HEVC)"])
    assert ondemand.choose(many, hd_box, "gone")[0] is hd_more  # (a version since removed)
    # What the connection keeps up with, as the app measured it: the best that fits,
    # or the smallest it can play; one asked for plays regardless.
    rated = Entry("3", catalog.MOVIE, "Rated", media=(sd, hd, uhd, hd_more))
    assert ondemand.choose(rated, TV_BOX, max_kbps=20_000)[0] is hd_more
    assert ondemand.choose(rated, TV_BOX, max_kbps=1_000)[0] is sd
    assert ondemand.choose(rated, TV_BOX, "uhd", max_kbps=1_000)[0] is uhd
    assert ondemand.choose(rated, TV_BOX, max_kbps=90_000)[0] is uhd
    assert ondemand.fits(hdr, 1_000) is None  # (what it needs isn't known)
    codecs = [media(id="a"), media(id="b", video="hevc")]
    assert list(ondemand.version_labels(codecs).values()) == ["1080p · H.264", "1080p · HEVC"]
    assert catalog.size_label(720, 576) == "576p" and catalog.size_label(320, 240) == "SD"


def test_tracks_are_named_plainly():
    assert ondemand.track_name(Track("1", "ac3", "English", channels=6), True) == (
        "English · Dolby Digital · 5.1"
    )
    assert ondemand.track_name(Track("2", "aac", "English", "Commentary", 2), True) == (
        "English · Commentary · AAC · Stereo"
    )
    assert ondemand.track_name(Track("3", "srt", "Spanish", forced=True), False) == (
        "Spanish · Forced"
    )
    assert ondemand.track_name(Track("4", "pgs"), False) == "Unknown language"


# Progress -----------------------------------------------------------------------------------


def test_progress_resumes_and_finishes():
    movie = Entry("1", catalog.MOVIE, "M", duration_ms=100 * 60_000)
    assert ondemand.progressed(None, 30_000, movie) == (30_000, False)
    assert ondemand.resume_at((30_000, False)) == 0  # (barely started: from the start)
    assert ondemand.resume_at((20 * 60_000, False)) == 20 * 60_000
    # 90% of the way, without credits, is watched (and starts over next time).
    assert ondemand.progressed(None, 90 * 60_000, movie) == (0, True)
    # Watched stays watched while it's watched again.
    assert ondemand.progressed((0, True), 10 * 60_000, movie) == (10 * 60_000, True)
    with_credits = Entry(
        "2", catalog.EPISODE, "E", duration_ms=22 * 60_000, credits=(20 * 60_000, 22 * 60_000)
    )
    assert ondemand.progressed(None, 20 * 60_000, with_credits) == (0, True)
    assert ondemand.progressed(None, 19 * 60_000, with_credits) == (19 * 60_000, False)


def test_skip_buttons_only_where_an_episodes_markers_fit_its_file():
    def mark(kind, start, end, final=False):
        m = {"type": kind, "startTimeOffset": start, "endTimeOffset": end}
        return {**m, "final": "1"} if final else m

    skips = plex_module._skips
    minute, length = 60_000, 44 * 60_000
    intro, credits = (
        mark("intro", 90_000, 150_000),
        mark("credits", 42 * minute, length - 500, True),
    )
    # An intro after a cold open, and credits Plex says are final (to the end).
    assert skips(length, [intro, credits]) == ((90_000, 150_000), (42 * minute, length))
    # Scraps of a few seconds before the intro, or after the credits, go with them.
    tight = [mark("intro", 3_000, 60_000), mark("credits", 42 * minute, length - 4_000)]
    assert skips(length, tight) == ((0, 60_000), (42 * minute, length))
    # Credits with a scene after them: Skip credits goes to the scene.
    assert skips(length, [mark("credits", 40 * minute, 41 * minute)]) == (
        None, (40 * minute, 41 * minute)
    )  # fmt: skip
    # Markers that don't fit this file (found in another, since replaced).
    assert skips(length, [intro, mark("credits", 42 * minute, length + 30_000, True)]) == (
        None, None
    )  # fmt: skip
    assert skips(length, [intro, mark("credits", 43 * minute, 42 * minute)]) == (None, None)
    # Versions of the same length line up with the markers; others may not.
    assert skips(length, [intro], [length, length + 400]) == ((90_000, 150_000), None)
    assert skips(length, [intro], [length, length - 45_000]) == (None, None)
    # An intro running into the credits: neither. One ending in the last minute: no intro.
    short = 8 * minute
    overlapping = [mark("intro", 3 * minute, 7 * minute), mark("credits", 270_000, short, True)]
    assert skips(short, overlapping) == (None, None)
    assert skips(short, [mark("intro", 3 * minute, 450_000)]) == (None, None)
    # Stations' rules: an intro in the first half, under five minutes; credits
    # in the second half; nothing under two seconds.
    assert skips(length, [mark("intro", 23 * minute, 24 * minute)]) == (None, None)
    assert skips(length, [mark("intro", minute, 7 * minute)]) == (None, None)
    assert skips(length, [mark("credits", 10 * minute, 11 * minute)]) == (None, None)
    assert skips(length, [mark("intro", minute, minute + 1_500)]) == (None, None)


def test_movies_have_no_skip_buttons():
    raw = {"ratingKey": "1", "duration": 100 * 60_000, "Marker": [
        {"type": "intro", "startTimeOffset": 60_000, "endTimeOffset": 120_000},
        {"type": "credits", "startTimeOffset": 95 * 60_000, "endTimeOffset": 100 * 60_000, "final": 1},
    ]}  # fmt: skip
    movie = plex_module.to_entry({**raw, "type": "movie"}, details=True)
    episode = plex_module.to_entry({**raw, "type": "episode"}, details=True)
    assert movie and (movie.intro, movie.credits) == (None, None)
    assert episode and episode.intro == (60_000, 120_000)
    # So a movie is watched 90% of the way through, however long its credits.
    assert ondemand.progressed(None, 89 * 60_000, movie) == (89 * 60_000, False)
    assert ondemand.progressed(None, 90 * 60_000, movie) == (0, True)


def test_the_next_episode_skips_specials_and_whats_watched():
    eps = [
        Entry(k, catalog.EPISODE, k, season=s, episode=n)
        for k, s, n in (("a", 1, 1), ("b", 1, 2), ("c", 2, 1), ("x", 0, 1))
    ]

    def after(key, watched=()):
        rows = [(key, ondemand.FINISHED)] if key else []
        found = ondemand.next_up(eps, rows, set(watched))
        return found and found[0].key

    assert after(None) == "a"
    assert after("a") == "b"
    assert after("a", {"b"}) == "c"
    # After the last, the show is finished (specials aside), even with one
    # skipped before it: it's still unwatched in the show's list.
    assert after("c", {"a", "c"}) is None
    assert after("c", {"a", "b", "c"}) is None


def test_what_progress_says():
    assert ondemand.where_they_are(20 * 60_000, False) == ondemand.PARTWAY
    assert ondemand.where_they_are(20_000, True) == ondemand.STARTED
    assert ondemand.where_they_are(0, True) == ondemand.FINISHED
    assert ondemand.where_they_are(0, False) == ondemand.MARKED  # (marked unwatched)


def test_pictures_are_made_a_few_sizes_and_kept_up_to_a_limit():
    assert [ondemand.width_for(w) for w in (1, 160, 161, 700, 5000)] == [160, 160, 320, 720, 1920]
    kept = ondemand.PictureCache(most_bytes=800)
    kept.put(("1", "poster", 160), (b"x" * 90, "image/jpeg"))
    kept.put(("2", "poster", 160), (b"x" * 90, "image/jpeg"))
    kept.get(("1", "poster", 160))
    for n in range(3, 12):
        kept.put((str(n), "poster", 160), (b"x" * 90, "image/jpeg"))
    assert kept.get(("2", "poster", 160)) is None and kept.get(("11", "poster", 160))
    kept.put(("big", "poster", 1920), (b"x" * 500, "image/jpeg"))  # (too big to keep)
    assert kept.get(("big", "poster", 1920)) is None


def test_shared_libraries_are_kept(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    shared = ondemand.Shared(db)
    assert shared.keys == () and not shared.on
    assert shared.save(["2", "1", "2"]) == ("2", "1")
    assert ondemand.Shared(db).keys == ("2", "1")
    for bad in (["../1"], ["one"], [None]):
        with pytest.raises(ValueError):
            shared.save(bad)
    db.set_meta(ondemand.META, "not json")
    assert ondemand.Shared(db).keys == ()
    # When playing can't keep up: offer a smaller version at home, switch away from home.
    assert shared.when_slow == {"home": "offer", "away": "switch"}
    assert shared.save_when_slow("switch", None) == {"home": "switch", "away": "switch"}
    assert ondemand.Shared(db).when_slow["home"] == "switch"
    with pytest.raises(ValueError):
        shared.save_when_slow("sometimes", None)
    db.set_meta(ondemand.SLOW_META, '{"home": "never"}')
    assert ondemand.Shared(db).when_slow == {"home": "offer", "away": "switch"}


# Through the apps ------------------------------------------------------------------------------


@pytest.fixture
def plex(tmp_path):
    fp = LibraryPlex()
    fp.add_show("100", "Bonanza", year=1959)
    for n in range(1, 4):
        fp.add_episode(f"20{n}", "100", 1, n, f"Episode {n}", f"/tv/b/{n}.mkv", 50 * 60_000)
        fp.describe(f"20{n}")
    fp.add_episode("204", "100", 2, 1, "Season Two", "/tv/b/4.mkv", 50 * 60_000)
    fp.add_episode("209", "100", 0, 1, "A Special", "/tv/b/9.mkv", 50 * 60_000)
    fp.set_markers("201", ("credits", 48 * 60_000, 50 * 60_000, True))
    fp.add_section("2", "Movies", "movie")
    fp.add_section("3", "Home Videos", "movie")
    movie = tmp_path / "movie.mkv"
    movie.write_bytes(bytes(range(256)) * 40)
    fp.add_movie("300", "The Movie", str(movie), 100 * 60_000, year=1999, section="2")
    fp.describe("300", audio="ac3")
    fp.add_version("300", 1280, 720)
    fp.add_subtitles("300", "srt", "English", external=b"1\n00:00:01,000 --> 00:00:02,000\nHi\n")
    fp.add_movie("301", "Another Movie", "/films/other.avi", 90 * 60_000, section="2")
    fp.describe("301", container="avi", video="mpeg4", audio="mp3")
    fp.add_movie("302", "Birthday", "/home/bday.mp4", 10 * 60_000, section="3")
    fp.files["201"] = b"episode one, from Plex" * 50
    return fp


@pytest.fixture
def app(plex, tmp_path):
    settings = Settings(
        plex_url="http://plex.test",
        plex_token="token",
        data_dir=tmp_path / "data",
        public_port=PUBLIC_PORT,
    )
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=plex.transport()))
    app.state.ctx.play_transport = plex.transport()
    return app


def play(client: TestClient, key: str, device: dict | None = None, **headers):
    return client.post(
        "/api/internal/play", json={"key": key, "device": device or TV}, headers=headers
    )


def test_nothing_is_shown_until_an_admin_shares_a_library(app, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as home:
        assert "library" not in home.get("/api/v1/server").json()["features"]
        for address in ("/api/internal/libraries", "/api/internal/home", "/api/internal/items/300"):
            refused = home.get(address)
            assert refused.status_code == 404, address
            assert refused.json()["detail"] == "No libraries are shared with StationPlay's apps"
        listed = home.get("/api/app-libraries").json()
        assert [(x["key"], x["title"]) for x in listed["libraries"]] == [
            ("1", "TV Shows"), ("2", "Movies"), ("3", "Home Videos")
        ]  # fmt: skip
        assert listed["shared"] == []
        assert home.put("/api/app-libraries", json={"libraries": ["x"]}).status_code == 400
        assert home.put("/api/app-libraries", json={"libraries": ["1", "2"]}).json()["shared"] == [
            "1",
            "2",
        ]
        assert "Libraries in StationPlay's apps: TV Shows, Movies" in caplog.text
        assert "library" in home.get("/api/v1/server").json()["features"]
        # The library not shared stays out of sight: its movie is as good as
        # missing, by key, in search and in lists.
        assert [x["title"] for x in home.get("/api/internal/libraries").json()["libraries"]] == [
            "TV Shows",
            "Movies",
        ]
        hidden = home.get("/api/internal/items/302")
        assert hidden.status_code == 404 and hidden.json()["detail"] == ondemand.NOT_SHARED
        assert home.get("/api/internal/items/999").json() == hidden.json()
        assert home.get("/api/internal/libraries/3").status_code == 404
        assert home.get("/api/internal/art/302").status_code == 404
        assert home.get("/api/internal/search?q=birthday").json() == {"items": [], "onNow": []}
        assert play(home, "302").status_code == 404
        # Unsharing hides what was seen before too.
        assert home.get("/api/internal/items/300").status_code == 200
        home.put("/api/app-libraries", json={"libraries": ["1"]})
        assert home.get("/api/internal/items/300").status_code == 404


def test_browsing_a_library(app, plex):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        page = home.get("/api/internal/libraries/2?sort=title&size=1").json()
        assert (page["total"], page["kind"], page["title"]) == (2, "movie", "Movies")
        assert [m["title"] for m in page["items"]] == ["Another Movie"]
        rest = home.get("/api/internal/libraries/2?sort=title&size=1&start=1").json()
        assert [m["title"] for m in rest["items"]] == ["The Movie"]
        for bad in ("sort=size", "size=0", "size=201", "start=-1", "size=lots"):
            assert home.get(f"/api/internal/libraries/2?{bad}").status_code == 400, bad
        show = home.get("/api/internal/items/100").json()
        assert [(s["season"], s["title"], s["episodes"]) for s in show["seasons"]] == [
            (1, "Season 1", 3), (2, "Season 2", 1), (0, "Specials", 1)
        ]  # fmt: skip
        assert (show["unwatched"], show["next"]["key"]) == (5, "201")
        assert show["summary"] == "Bonanza summary" and show["year"] == 1959
        two = home.get("/api/internal/items/100/episodes?season=2").json()["episodes"]
        assert [(e["key"], e["episodeTitle"], e["title"]) for e in two] == [
            ("204", "Season Two", "Bonanza")
        ]
        assert len(home.get("/api/internal/items/100/episodes").json()["episodes"]) == 5
        assert home.get("/api/internal/items/300/episodes").status_code == 400
        movie = home.get("/api/internal/items/300").json()
        assert movie["audio"][0]["name"] == "English · Dolby Digital · 5.1"
        assert movie["markers"] == {"intro": None, "credits": None, "creditsToEnd": False}
        assert movie["picture"] == {"size": "1080p", "hdr": None}
        # Search: titles with the words in them, the best matches first ("The
        # Movie" sorts as "Movie", just what was typed).
        found = home.get("/api/internal/search?q=movie").json()["items"]
        assert [m["title"] for m in found] == ["The Movie", "Another Movie"]
        assert [m["title"] for m in home.get("/api/internal/search?q=the").json()["items"]] == [
            "The Movie",  # (starts with it)
            "Another Movie",
        ]
        assert home.get("/api/internal/search?q=%20").status_code == 400
        # Pictures, at a few sizes.
        poster = home.get("/api/internal/art/300?kind=poster&w=300")
        assert poster.status_code == 200 and poster.content == b"poster 300"
        still = home.get("/api/internal/art/201?kind=thumb&w=400")
        assert still.status_code == 200
        assert (
            home.get("/api/internal/art/201?kind=poster").content == b"poster 100"
        )  # (its show's)
        assert home.get("/api/internal/art/300?kind=banner").status_code == 400
        # (Kept: asked again, Plex isn't.)
        asked = len(plex.requests)
        assert home.get("/api/internal/art/300?kind=poster&w=320").status_code == 200
        assert len(plex.requests) == asked


def test_narrowing_a_library_jumping_to_a_letter_and_others_like_it(app, plex):
    plex.add_movie("303", "Élan", "/films/elan.mkv", 80 * 60_000, year=1990, section="2",
                   genres=["Drama", "Comedy"])  # fmt: skip
    plex.add_movie("304", "9 Lives", "/films/9.mkv", 80 * 60_000, year=2005, section="2",
                   genres=["Comedy"])  # fmt: skip
    plex.add_movie("305", "A Drama", "/films/drama.mkv", 80 * 60_000, year=1995, section="2",
                   genres=["Drama"])  # fmt: skip
    # (As Plex sorts them: without "The" or "A".)
    plex.episodes["305"]["titleSort"] = "Drama"
    plex.episodes["300"]["titleSort"] = "Movie"
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        page = home.get("/api/internal/libraries/2").json()
        assert [m["title"] for m in page["items"]] == [
            "9 Lives", "Another Movie", "A Drama", "Élan", "The Movie"
        ]  # fmt: skip
        assert page["genres"] == ["Comedy", "Drama"]
        assert [(x["letter"], x["start"]) for x in page["letters"]] == [
            ("#", 0), ("A", 1), ("D", 2), ("E", 3), ("M", 4)
        ]  # fmt: skip
        assert home.get("/api/internal/libraries/2?sort=added").json()["letters"] == []
        comedies = home.get("/api/internal/libraries/2?genre=comedy").json()
        assert [m["key"] for m in comedies["items"]] == ["304", "303"]
        assert comedies["letters"] == [{"letter": "#", "start": 0}, {"letter": "E", "start": 1}]
        home.post("/api/internal/progress", json={"key": "304", "watched": True})
        left = home.get("/api/internal/libraries/2?genre=Comedy&unwatched=1").json()
        assert (left["total"], [m["key"] for m in left["items"]]) == (1, ["303"])
        shows = home.get("/api/internal/libraries/1?unwatched=1").json()
        assert [s["key"] for s in shows["items"]] == ["100"]
        none = home.get("/api/internal/libraries/2?genre=Westerns")
        assert none.status_code == 200 and (none.json()["total"], none.json()["items"]) == (0, [])
        assert home.get("/api/internal/libraries/2?genre=" + "x" * 101).status_code == 400
        # Others like it: the most genres in common, then the nearest in years.
        like = home.get("/api/internal/items/303/related").json()["items"]
        assert [m["key"] for m in like] == ["305", "304"]
        assert [m["key"] for m in home.get("/api/internal/items/305/related").json()["items"]] == [
            "303"
        ]
        assert home.get("/api/internal/items/301/related").json() == {"items": []}  # (no genres)
        assert home.get("/api/internal/items/999/related").status_code == 404


def test_playing_a_file_as_it_is(app, plex, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        # From disk, where StationPlay can see the file: ranges and all.
        played = play(home, "300", app="StationPlay for Android TV", deviceName="Den").json()
        assert played["method"] == "direct" and played["url"].endswith("/file.mkv")
        whole = (tmp_path / "movie.mkv").read_bytes()
        part = home.get(played["url"], headers={"Range": "bytes=100-199"})
        assert part.status_code == 206 and part.content == whole[100:200]
        assert part.headers["content-type"] == "video/x-matroska"
        assert home.head(played["url"]).headers["content-length"] == str(len(whole))
        assert "Pat" not in caplog.text and "Someone started The Movie (1999) in " in caplog.text
        # From Plex, where it can't.
        episode = play(home, "201").json()
        data = plex.files["201"]
        part = home.get(episode["url"], headers={"Range": "bytes=10-"})
        assert part.status_code == 206 and part.content == data[10:]
        assert part.headers["content-range"] == f"bytes 10-{len(data) - 1}/{len(data)}"
        assert home.get(episode["url"]).content == data
        assert episode["markers"]["credits"] == [48 * 60_000, 50 * 60_000]
        assert episode["markers"]["creditsToEnd"] is True
        # A version chosen; and what the apps do when playing can't keep up.
        assert [(v["id"], v["name"]) for v in played["versions"]] == [
            ("30000", "1080p"),
            ("30001", "720p"),
        ]
        assert played["version"] == "30000" and played["whenSlow"] == "offer"
        home.put(
            "/api/app-libraries", json={"libraries": ["1", "2"], "whenSlow": {"home": "switch"}}
        )
        assert "at home, switch to a smaller version" in caplog.text
        slow = home.post("/api/internal/play", json={"key": "300", "device": TV, "maxKbps": 9_000})
        assert slow.json()["version"] == "30001"  # (8,000 kbps doesn't fit 9,000 with room)
        assert [v["fits"] for v in slow.json()["versions"]] == [False, True]
        smaller = home.post(
            "/api/internal/play", json={"key": "300", "device": TV, "version": "30001"}
        ).json()
        assert smaller["version"] == "30001" and smaller["whenSlow"] == "switch"
        assert home.get("/api/app-libraries").json()["whenSlow"] == {
            "home": "switch",
            "away": "switch",
        }
        bad = {"libraries": ["1", "2"], "whenSlow": {"home": "maybe"}}
        assert home.put("/api/app-libraries", json=bad).status_code == 400
        # A device that can't play a file as it is is told why.
        refused = play(home, "301")
        assert refused.status_code == 422
        assert refused.json()["why"] == ["its file type (AVI)", "its picture's format (MPEG-4)"]
        assert play(home, "100").status_code == 400  # (a show isn't played)
        # (A device plays one program at a time: each of those ended the one before.)
        assert home.get(played["url"]).status_code == 404
        # Subtitles in files of their own, as text whatever the address says.
        played = play(home, "300").json()
        [subs] = [t for t in played["subtitles"] if t["external"]]
        got = home.get(subs["url"].replace(".srt", ".html"))
        assert got.status_code == 200 and got.headers["content-type"] == "application/x-subrip"
        assert got.headers["content-security-policy"] == "sandbox"
        # Leaving ends it.
        assert home.post(played["leave"]).status_code == 204
        assert home.get(played["url"]).status_code == 404
        # So does its library no longer being shared.
        played = play(home, "300").json()
        assert home.get(played["url"]).status_code == 200
        home.put("/api/app-libraries", json={"libraries": ["1"]})
        assert home.get(played["url"]).status_code == 404


def test_one_more_device_than_the_limits_allow_is_told_why(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        assert home.put("/api/app-limits", json={"devices": 1, "away": 0}).status_code == 200
        app.state.ctx.hls_streams.watchers = lambda: {"10.0.0.9": False}
        refused = play(home, "300")
        assert refused.status_code == 503
        assert refused.json()["limit"] == "devices" and refused.json()["most"] == 1
        # The device already watching a station may play something instead.
        app.state.ctx.hls_streams.watchers = lambda: {"testclient": False}
        assert play(home, "300").status_code == 200


def test_progress_continue_watching_and_whats_next(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})

        def report(key: str, ms: int) -> dict:
            got = home.post("/api/internal/progress", json={"key": key, "positionMs": ms})
            assert got.status_code == 200, got.text
            return got.json()

        assert home.get("/api/internal/home").json()["continue"] == []
        assert report("300", 30 * 60_000) == {"positionMs": 30 * 60_000, "watched": False}
        assert play(home, "300").json()["resumeMs"] == 30 * 60_000
        # Into its credits: watched, and next is the following episode.
        assert report("201", 49 * 60_000) == {"positionMs": 0, "watched": True}
        going = home.get("/api/internal/home").json()["continue"]
        assert [(c["key"], c["positionMs"]) for c in going] == [("202", 0), ("300", 30 * 60_000)]
        show = home.get("/api/internal/items/100").json()
        assert show["next"]["key"] == "202" and show["unwatched"] == 4
        assert show["seasons"][0]["unwatched"] == 2
        listed = home.get("/api/internal/libraries/1").json()["items"]
        assert listed[0]["unwatched"] == 4
        # Partway into the next one: that's the one to carry on with.
        report("202", 10 * 60_000)
        assert home.get("/api/internal/items/100").json()["next"]["positionMs"] == 10 * 60_000
        # Marked from a menu.
        assert home.post("/api/internal/progress", json={"key": "300", "watched": True}).json() == {
            "positionMs": 0,
            "watched": True,
        }
        assert [c["key"] for c in home.get("/api/internal/home").json()["continue"]] == ["202"]
        # Marking an episode unwatched doesn't make it the one to watch next.
        home.post("/api/internal/progress", json={"key": "203", "watched": False})
        assert [c["key"] for c in home.get("/api/internal/home").json()["continue"]] == ["202"]
        assert home.get("/api/internal/items/100").json()["next"]["key"] == "202"
        assert home.post("/api/internal/progress", json={"key": "300"}).status_code == 400
        assert (
            home.post("/api/internal/progress", json={"key": "100", "watched": True}).status_code
            == 400
        )


def test_each_person_has_their_own_place(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        assert home.post("/api/access/users", json=ADMIN).status_code == 201
        sam = {"name": "Sam", "password": "battery staple", "role": "user"}
        assert home.post("/api/access/users", json=sam).status_code == 201
        phone = TestClient(app)
        token = phone.post("/api/internal/sign-in", json=sam).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        assert phone.get("/api/internal/libraries", headers=auth).status_code == 200  # (a User may)
        moved = phone.post(
            "/api/internal/progress", headers=auth, json={"key": "300", "positionMs": 1_800_000}
        )
        assert moved.status_code == 200
        assert home.get("/api/internal/items/300").json()["positionMs"] == 0  # (Pat's own)
        assert phone.get("/api/internal/items/300", headers=auth).json()["positionMs"] == 1_800_000
        # A program's own address needs no token, and ends with its sign-in.
        played = play(phone, "300", **auth).json()
        assert phone.get(played["url"]).status_code == 200
        phone.post("/api/internal/sign-out", headers=auth)
        app.state.ctx.plays.get(played["session"]).checked -= ondemand.RECHECK_S + 1
        assert phone.get(played["url"]).status_code == 404
        # Removing someone removes their progress.
        users = home.get("/api/access/users").json()
        sam_id = next(u["id"] for u in users if u["name"] == "Sam")
        assert home.delete(f"/api/access/users/{sam_id}").status_code == 204
        assert app.state.ctx.db.progress_of(sam_id, ["300"]) == {}


# Away from home, through the public port -------------------------------------------------

# A phone that takes copies (see test_converting.py).
PHONE = {
    "containers": ["mp4", "mkv"],
    "video": [{"codec": "h264", "width": 1920, "height": 1080, "bitDepth": 8}],
    "hdr": [],
    "audio": ["aac"],
    "hls": ["ts"],
}
AWAY = {"on": True, "address": "https://tv.example.com"}


def internet(app, **headers) -> TestClient:
    """An app away from home: through a reverse proxy with HTTPS, to the
    public port."""
    return TestClient(
        app,
        base_url=f"http://testserver:{PUBLIC_PORT}",
        headers={"X-Forwarded-Proto": "https", "X-Real-IP": "203.0.113.7", **headers},
    )


def signed_in(client: TestClient, who: dict, app: str = "Pixel") -> dict[str, str]:
    signed = client.post("/api/internal/sign-in", json={**who, "deviceName": app})
    assert signed.status_code == 200, signed.text
    return {"Authorization": f"Bearer {signed.json()['token']}"}


def test_media_away_from_home_waits_until_its_turned_on(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        assert home.post("/api/access/users", json=ADMIN).status_code == 201
        phone = internet(app)
        auth = signed_in(phone, ADMIN)
        assert "library" not in phone.get("/api/v1/server").json()["features"]
        for address in ("/api/internal/libraries", "/api/internal/home", "/api/internal/items/300",
                        "/api/internal/art/300"):  # fmt: skip
            refused = phone.get(address, headers=auth)
            assert refused.status_code == 403, address
            assert "Admin turns on StationPlay's apps away from home" in refused.json()["detail"]
        assert play(phone, "300", **auth).status_code == 403
        progress = {"key": "300", "positionMs": 600_000}
        assert phone.post("/api/internal/progress", json=progress, headers=auth).status_code == 403
        # Search still finds what's on the stations; the library, at home.
        assert phone.get("/api/internal/search?q=movie", headers=auth).json()["items"] == []
        assert len(home.get("/api/internal/search?q=movie").json()["items"]) == 2
        played = play(home, "300").json()  # (at home, where a cookie signs in)
        assert phone.get(played["url"]).status_code == 404
        # On: the apps get Media through the public port, as at home.
        assert home.put("/api/away", json=AWAY).status_code == 200
        features = phone.get("/api/v1/server").json()["features"]
        assert {"away", "library", "convert"} <= set(features)
        assert [x["key"] for x in phone.get("/api/internal/libraries", headers=auth).json()[
            "libraries"]] == ["2"]  # fmt: skip
        assert len(phone.get("/api/internal/search?q=movie", headers=auth).json()["items"]) == 2
        poster = phone.get("/api/internal/art/300?kind=poster&w=300", headers=auth)
        assert poster.status_code == 200 and poster.content == b"poster 300"
        # Without a library shared, there's no Media anywhere.
        home.put("/api/app-libraries", json={"libraries": []})
        assert "library" not in phone.get("/api/v1/server").json()["features"]
        assert phone.get("/api/internal/libraries", headers=auth).status_code == 404


def test_media_plays_away_from_home(app, plex, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    # (A play session's ID is its address's only secret: at least 128 random bits.)
    assert ondemand.SESSION_ID_BYTES * 8 >= 128
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        assert home.post("/api/access/users", json=ADMIN).status_code == 201
        home.put("/api/away", json=AWAY)
        phone = internet(app)
        auth = signed_in(phone, ADMIN)
        # From disk: ranges and all, through the proxy, with no sign-in for the player.
        played = phone.post(
            "/api/internal/play",
            json={"key": "300", "device": TV, "app": "StationPlay for Android",
                  "deviceName": "Pixel"},
            headers=auth,
        )  # fmt: skip
        assert played.status_code == 200, played.text
        movie = played.json()
        assert movie["method"] == "direct" and movie["whenSlow"] == "switch"  # (away's choice)
        assert len(movie["session"]) == 32
        player = internet(app)  # (no token)
        whole = (tmp_path / "movie.mkv").read_bytes()
        part = player.get(movie["url"], headers={"Range": "bytes=100-199"})
        assert part.status_code == 206 and part.content == whole[100:200]
        assert part.headers["content-range"] == f"bytes 100-199/{len(whole)}"
        assert player.head(movie["url"]).headers["content-length"] == str(len(whole))
        [subs] = [t for t in movie["subtitles"] if t["external"]]
        assert player.get(subs["url"]).text.endswith("Hi\n")
        # Only over HTTPS, as everything for the apps is there.
        plain_http = TestClient(app, base_url=f"http://testserver:{PUBLIC_PORT}")
        assert plain_http.get(movie["url"]).status_code == 403
        # From Plex, where StationPlay can't read the file (on another device:
        # one plays one program at a time).
        episode = play(phone, "201", **signed_in(phone, ADMIN, "Tablet")).json()
        data = plex.files["201"]
        part = player.get(episode["url"], headers={"Range": "bytes=10-"})
        assert part.status_code == 206 and part.content == data[10:]
        # Progress, from the session started there.
        moved = phone.post(
            "/api/internal/progress",
            json={"key": "300", "positionMs": 600_000, "session": movie["session"]},
            headers=auth,
        )
        assert moved.json() == {"positionMs": 600_000, "watched": False}
        assert app.state.ctx.plays.find(movie["session"]).position_ms == 600_000
        # The log and the access log say it's away from home; so does Stats.
        assert (
            "Pat started The Movie (1999) in StationPlay for Android on Pixel, away from home: "
            "movie.mkv" in caplog.text
        )
        log = home.get("/api/logs?access_log=true").json()["text"]
        assert (
            "Pat is playing The Movie (1999) away from home, from 203.0.113.7 (over the internet)"
            in log
        )
        watching = home.get("/api/stats/now").json()["watching"]
        row = next(r for r in watching if r["media"] and r["media"]["title"] == "The Movie (1999)")
        assert (row["who"], row["where"], len(row["address"])) == ("Pat", "away", 6)
        assert row["address"] != "testclient" and row["address"] in [
            k[:6] for k in app.state.ctx.away._keys
        ]
        # Leaving ends it; then its address is as good as never there.
        assert player.post(movie["leave"]).status_code == 204
        assert "Pat stopped The Movie (1999) away from home at 10:00" in caplog.text
        gone = player.get(movie["url"])
        assert gone.status_code == 404 and player.get("/play/" + "x" * 32 + "/file.mkv").json() == (
            gone.json()
        )


def test_a_program_away_from_home_ends_with_its_sign_in(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        assert home.post("/api/access/users", json=ADMIN).status_code == 201
        sam = {"name": "Sam", "password": "battery staple", "role": "user"}
        assert home.post("/api/access/users", json=sam).status_code == 201
        home.put("/api/away", json=AWAY)
        phone = internet(app)

        def playing(auth: dict[str, str]) -> str:
            got = play(phone, "300", **auth)
            assert got.status_code == 200, got.text
            assert phone.get(got.json()["url"]).status_code == 200
            return got.json()["url"]

        # Signing out ends it at once (checked every time, from outside).
        auth = signed_in(phone, sam)
        url = playing(auth)
        phone.post("/api/internal/sign-out", headers=auth)
        assert phone.get(url).status_code == 404
        # So does a new password.
        auth = signed_in(phone, sam)
        url = playing(auth)
        sam_id = next(u["id"] for u in home.get("/api/access/users").json() if u["name"] == "Sam")
        home.put(f"/api/access/users/{sam_id}", json={"password": "a new one, at last"})
        assert phone.get(url).status_code == 404
        # And an Admin signing the app out on the Access tab.
        sam["password"] = "a new one, at last"
        auth = signed_in(phone, sam, "Sam's Phone")
        url = playing(auth)
        [app_row] = [a for a in home.get("/api/access/apps").json() if a["app"].endswith("Phone")]
        assert home.delete(f"/api/access/apps/{app_row['id']}").status_code == 204
        assert phone.get(url).status_code == 404
        # And watching away from home being turned off.
        auth = signed_in(phone, sam)
        url = playing(auth)
        home.put("/api/away", json={**AWAY, "on": False})
        assert phone.get(url).status_code == 404
        home.put("/api/away", json=AWAY)
        assert phone.get(url).status_code == 404  # (ended: not back)


def test_a_program_started_at_home_isnt_offered_through_the_public_port(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        assert home.post("/api/access/users", json=ADMIN).status_code == 201
        home.put("/api/away", json=AWAY)
        at_home = play(home, "300").json()
        outsider = internet(app)
        assert outsider.get(at_home["url"]).status_code == 404
        assert outsider.head(at_home["url"]).status_code == 404
        # Nor can it be ended, or kept going, from there.
        assert outsider.post(at_home["leave"]).status_code == 404
        auth = signed_in(outsider, ADMIN)
        kept = {"key": "300", "positionMs": 900_000, "session": at_home["session"]}
        assert outsider.post("/api/internal/progress", json=kept, headers=auth).status_code == 200
        assert app.state.ctx.plays.find(at_home["session"]).position_ms is None
        assert home.get(at_home["url"]).status_code == 200  # (still going, at home)
        # A guessed address gets nothing, signed in or not.
        for guess in ("/play/guess/file.mkv", "/play/" + "A" * 32 + "/index.m3u8", "/play//leave"):
            assert outsider.get(guess, headers=auth).status_code == 404, guess
        # One started through the public port plays at home too (a VPN, say).
        away = play(outsider, "300", **auth).json()
        assert home.get(away["url"]).status_code == 200


def test_media_away_from_home_counts_against_the_limits(app):
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        assert home.post("/api/access/users", json=ADMIN).status_code == 201
        home.put("/api/away", json=AWAY)
        assert home.put("/api/app-limits", json={"devices": 0, "away": 1}).status_code == 200
        phone, tablet = internet(app), internet(app)
        on_phone, on_tablet = signed_in(phone, ADMIN), signed_in(tablet, ADMIN, "Tablet")
        assert play(phone, "300", **on_phone).status_code == 200
        # (The same app again: still one device. Its stations count as the same device too.)
        assert play(phone, "201", **on_phone).status_code == 200
        ctx = app.state.ctx
        assert sum(ctx.app_watchers().values()) == 1
        refused = play(tablet, "300", **on_tablet)
        assert refused.status_code == 503
        assert (refused.json()["limit"], refused.json()["most"]) == ("away", 1)
        assert "watching away from home at once" in refused.json()["detail"]
        # At home, the limit away from home doesn't apply.
        assert play(home, "300").status_code == 200
        # Copies converted away from home count with those at home (each
        # device's own: a device plays one program at a time).
        busy = home.put("/api/app-limits", json={"devices": 0, "away": 0})
        assert busy.status_code == 200
        for n in range(applibrary.CONVERTING_MOST):
            another = signed_in(tablet, ADMIN, f"Tablet {n}")
            got = tablet.post("/api/internal/play", json={"key": "301", "device": PHONE},
                              headers=another)  # fmt: skip
            assert got.status_code == 200 and got.json()["method"] == "convert", got.text
        assert ctx.plays.copies() == applibrary.CONVERTING_MOST
        one_more = home.post("/api/internal/play", json={"key": "301", "device": PHONE})
        assert one_more.status_code == 503 and one_more.json()["detail"] == (
            applibrary.BUSY_CONVERTING
        )


def test_the_quality_away_from_home(app, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app) as home:
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        assert home.post("/api/access/users", json=ADMIN).status_code == 201
        assert home.get("/api/away").json()["mediaMbps"] is None  # (Original, to start)
        home.put("/api/away", json=AWAY)
        phone = internet(app)
        auth = signed_in(phone, ADMIN)
        # The upload StationPlay's apps measured from outside, as a guide.
        phone.post("/api/internal/speed-test", json={"mbps": 23.4}, headers=auth)
        got = home.get("/api/away").json()
        assert (got["upload"]["mbps"], got["upload"]["where"]) == (23.4, "away")
        assert got["mediaMbpsMost"] == 200
        for wrong in (0, 201, -5):
            refused = home.put("/api/away", json={**AWAY, "mediaMbps": wrong})
            assert refused.status_code == 400, wrong
        assert home.get("/api/away").json()["mediaMbps"] is None  # (nothing changed)
        # Original: as at home (the 1080p version, at 8 Mbps).
        assert play(phone, "300", **auth).json()["version"] == "30000"
        # Up to 5 Mbps: the version within it, as it is.
        assert home.put("/api/away", json={**AWAY, "mediaMbps": 5}).json()["mediaMbps"] == 5
        log = home.get("/api/logs?access_log=true").json()["text"]
        assert "Media away from home in StationPlay's apps: up to 5 Mbps (set by Pat)" in log
        within = play(phone, "300", **auth).json()
        assert (within["method"], within["version"]) == ("direct", "30001")
        assert play(home, "300").json()["version"] == "30000"  # (at home, as before)
        # The setup's saving (without it) leaves it as it is.
        assert home.put("/api/away", json=AWAY).json()["mediaMbps"] == 5
        # Up to 3 Mbps: none is within it, so one is converted down to fit.
        home.put("/api/away", json={**AWAY, "mediaMbps": 3})
        down = phone.post("/api/internal/play", json={"key": "300", "device": PHONE},
                          headers=auth).json()  # fmt: skip
        assert down["method"] == "convert" and down["bitrateKbps"] <= 3000
        assert down["why"][-1] == "a smaller copy, within the 3 Mbps allowed away from home"
        assert (
            "switched The Movie (1999) to a smaller copy, from 720p at 4 Mbps to 480p H.264 at 2 "
            "Mbps on the CPU: to fit the 3 Mbps allowed away from home" in caplog.text
        )
        copy = app.state.ctx.plays.find(down["session"]).copy
        assert applibrary.how_copied(copy.plan, [], False, copy.encoder, 3_000) == (
            "converted smaller to fit the 3 Mbps allowed away from home: 480p H.264 at 2 Mbps on "
            "the CPU"
        )
        # An app that can't take a copy is told why.
        refused = play(phone, "300", **auth)
        assert refused.status_code == 422
        assert refused.json()["why"] == [
            "it needs 4 Mbps, more than the 3 Mbps allowed away from home"
        ]
        # The apps' own "can't keep up" goes further down still.
        slower = phone.post(
            "/api/internal/play",
            json={"key": "300", "device": PHONE, "maxKbps": 1_500, "fit": True},
            headers=auth,
        ).json()
        assert slower["method"] == "convert" and slower["bitrateKbps"] <= 1_000 + 192
        # A copy converted for another reason stays within it too.
        other = phone.post("/api/internal/play", json={"key": "301", "device": PHONE},
                           headers=auth).json()  # fmt: skip
        assert other["method"] == "convert" and other["bitrateKbps"] <= 3000
        # Original again.
        assert home.put("/api/away", json={**AWAY, "mediaMbps": None}).json()["mediaMbps"] is None
        assert play(phone, "300", **auth).json()["version"] == "30000"


def test_the_cap_converts_down_to_fit():
    four_k = Media(container="mkv", video="hevc", width=3840, height=2160)
    convert = converting.convert_size
    assert convert(four_k, 1080, None, 20_000) == (1080, 8_000)
    assert convert(four_k, 1080, None, 6_000) == (720, 4_000)
    assert convert(four_k, 1080, None, 6_000, 640) == (720, 4_000)
    assert convert(four_k, 1080, None, 4_500, 640) == (480, 2_000)
    assert convert(four_k, 1080, None, 2_000) == (480, 1_808)
    assert convert(four_k, 1080, None, 1_000) == (480, 808)
    assert convert(four_k, 1080, None, 300) == (480, 300)  # (however low)
    assert convert(four_k, 1080, 9_000, 20_000) == (720, 4_000)  # (the connection's lower)
    # What a version needs: as the library says, or from its size and length.
    assert ondemand.needs_kbps(Media(container="mkv", video="h264", bitrate_kbps=900)) == 900
    sized = Media(container="mkv", video="h264", size=75_000_000, duration_ms=60_000)
    assert ondemand.needs_kbps(sized) == 10_000 and ondemand.over_cap(sized, 9_000)
    assert not ondemand.over_cap(Media(container="mkv", video="h264"), 1_000)  # (not known)
    assert not ondemand.over_cap(sized, None)


def test_only_numbered_keys_go_to_plex_together():
    assert plex_module._checked("/library/metadata/1,22,333") == "/library/metadata/1,22,333"
    for wrong in ("/library/metadata/1,2/thumb", "/poster/1,2", "/library/metadata/1,../x"):
        with pytest.raises(plex_module.PlexError):
            plex_module._checked(wrong)
