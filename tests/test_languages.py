"""Each person's languages in StationPlay's apps (languages.py, and through
applibrary.py): codes as files and apps give them, choosing the sound and
captions in the order the apps are promised (the episode's or movie's, the
show's, the person's, the file's default), forced and full subtitles,
commentaries, playing what's chosen, and one person's choices never
another's."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import languages
from app.catalog import EPISODE, MOVIE, Entry, Media, Track
from app.config import Settings
from app.db import Database
from app.languages import Choice, Languages
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex

# A TV that plays this library's files as they are, and takes copies; its
# player shows text subtitles itself, but not pictures.
TV = {
    "containers": ["mkv"],
    "video": [{"codec": "h264", "width": 1920, "height": 1080, "bitDepth": 8}],
    "hdr": [],
    "audio": ["aac", "ac3"],
    "hls": ["ts"],
    "subtitles": ["srt", "ass", "vtt"],
}
TIA = {"name": "Tia", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple", "role": "user"}


def test_languages_as_files_and_apps_give_them():
    for given, code in (
        ("eng", "eng"), ("en", "eng"), ("EN-us", "eng"), ("English", "eng"), ("pt-BR", "por"),
        ("pt_BR", "por"), ("fra", "fre"), ("fre", "fre"), ("deu", "ger"), ("zh-Hant", "chi"),
        ("nob", "nor"), ("jpn", "jpn"), ("japanese", "jpn"),
    ):  # fmt: skip
        assert languages.code(given) == code, given
    for nothing in ("", "und", "zz", "klingon", "e", "x" * 50, None, 7, ["eng"]):
        assert languages.code(nothing) is None, nothing
    assert languages.name("jpn") == "Japanese"
    assert languages.as_json("ger") == {"code": "ger", "name": "German"}
    names = [c["name"] for c in languages.choices()]
    assert names == sorted(names, key=str.casefold) and "English" in names
    assert all(languages.code(c["code"]) == c["code"] for c in languages.choices())


def test_what_an_app_sends_is_checked():
    assert languages.changes({"audio": "en", "captionLanguage": None}, own=True) == {
        "audio": "eng", "caption_language": None
    }  # fmt: skip
    assert languages.changes({}, own=True) == {}
    with pytest.raises(ValueError, match="doesn't know the language “xx”"):
        languages.changes({"audio": "xx"}, own=False)
    with pytest.raises(ValueError, match="Subtitles must be on or off"):
        languages.changes({"captions": None}, own=True)
    assert languages.changes({"captions": None}, own=False) == {"captions": None}


# Choosing -----------------------------------------------------------------------------------


def track(id: str, codec: str, code: str, **more) -> Track:
    return Track(id, codec, languages.name(code), language_code=code, **more)


# A file with Japanese sound (its default), an English commentary before the
# English sound, and English subtitles: forced (a picture), full (text) and
# for the deaf and hard of hearing; and Japanese ones of their own.
FILE = Media(
    container="mkv",
    video="h264",
    id="1",
    audio=(
        track("a1", "aac", "jpn", default=True, index=1),
        track("a2", "aac", "eng", title="Commentary with the director", index=2),
        track("a3", "ac3", "eng", index=3),
    ),
    subtitles=(
        track("s1", "pgs", "eng", forced=True, index=4),
        track("s2", "srt", "eng", index=5),
        track("s3", "pgs", "eng", title="SDH", index=6),
        track("s4", "srt", "jpn", external=True),
    ),
)
EP = Entry("201", EPISODE, "Pilot", show_key="100", media=(FILE,))
FILM = Entry("300", MOVIE, "A Film", media=(FILE,))


@pytest.fixture
def chosen(tmp_path) -> Languages:
    return Languages(Database(tmp_path / "db.sqlite"))


def picked(langs: Languages, user_id: int, entry: Entry = EP) -> tuple[str | None, str | None]:
    wanted = langs.wanted(user_id, entry)
    assert wanted is not None
    found = languages.pick(FILE, wanted)
    return (found.audio.id if found.audio else None), (
        found.subtitle.id if found.subtitle else None
    )


def test_nothing_chosen_anywhere_chooses_nothing(chosen):
    assert chosen.wanted(1, EP) is None and chosen.wanted(1, FILM) is None


def test_the_episode_then_the_show_then_the_person_then_the_file(chosen):
    chosen.change(1, languages.OWN, {"captions": True, "caption_language": "eng"})
    # Their own: the file's default sound (Japanese), English captions (full).
    assert picked(chosen, 1) == ("a1", "s2")
    wanted = chosen.wanted(1, EP)
    found = languages.pick(FILE, wanted)
    assert (found.audio_why, found.subtitle_why) == (
        "The file's default", "English subtitles, as you chose"
    )  # fmt: skip
    # The show's: English sound (never the commentary, though it comes first).
    chosen.change(1, "100", {"audio": "eng"})
    assert picked(chosen, 1) == ("a3", "s2")
    assert (
        languages.pick(FILE, chosen.wanted(1, EP)).audio_why == "English, as chosen for this show"
    )
    # The episode's own: Japanese, and captions off, which leaves only a
    # forced track in the sound's language (none in Japanese).
    chosen.change(1, "201", {"audio": "jpn", "captions": False})
    assert picked(chosen, 1) == ("a1", None)
    found = languages.pick(FILE, chosen.wanted(1, EP))
    assert found.subtitle_why == "Subtitles are off, as chosen for this episode"
    # Cleared, one at a time: the show's sound again, and the person's captions.
    chosen.change(1, "201", {"audio": None})
    assert picked(chosen, 1) == ("a3", "s1")  # (captions off: the English forced ones)
    chosen.change(1, "201", {"captions": None})
    assert picked(chosen, 1) == ("a3", "s2")
    assert chosen.chosen_for(1, "201") is None  # (nothing left there)
    # A movie has no show: its own, then the person's.
    assert picked(chosen, 1, FILM) == ("a1", "s2")
    chosen.change(1, "300", {"audio": "eng", "captions": False})
    assert picked(chosen, 1, FILM) == ("a3", "s1")
    found = languages.pick(FILE, chosen.wanted(1, FILM))
    assert found.audio_why == "English, as chosen for this movie"
    assert found.subtitle_why == "Forced English subtitles, for the parts in another language"


def test_captions_in_the_sounds_language_and_what_isnt_there(chosen):
    chosen.change(1, languages.OWN, {"captions": True})
    assert picked(chosen, 1) == ("a1", "s4")  # (Japanese sound: Japanese captions)
    chosen.change(1, languages.OWN, {"audio": "spa", "caption_language": None})
    found = languages.pick(FILE, chosen.wanted(1, EP))
    assert found.audio.id == "a1"
    assert found.audio_why == "The file's default: it has no Spanish sound"
    chosen.change(1, languages.OWN, {"audio": None, "caption_language": "ger"})
    found = languages.pick(FILE, chosen.wanted(1, EP))
    assert found.subtitle is None and found.subtitle_why == "No subtitles: it has none in German"


def test_a_full_track_before_a_forced_one_and_the_files_default_first():
    wanted = languages.Wanted(None, "", True, languages.YOURS, "eng", languages.YOURS)
    forced_only = Media(
        container="mkv", video="h264", audio=FILE.audio, subtitles=FILE.subtitles[:1]
    )
    found = languages.pick(forced_only, wanted)
    assert found.subtitle.id == "s1" and "forced only" in found.subtitle_why
    marked = Media(
        container="mkv", video="h264", audio=FILE.audio,
        subtitles=(*FILE.subtitles[:2], replace(FILE.subtitles[2], default=True)),
    )  # fmt: skip
    assert languages.pick(marked, wanted).subtitle.id == "s3"  # (SDH is a full one)
    only_commentary = Media(container="mkv", video="h264", audio=FILE.audio[:2])
    english = languages.Wanted("eng", languages.YOURS, False, "", None, "")
    assert languages.pick(only_commentary, english).audio.id == "a2"  # (when there's no other)
    silent = Media(container="mkv", video="h264")
    assert languages.pick(silent, english) == languages.Picked(None, "It has no sound", None,
                                                               "Subtitles are off")  # fmt: skip


def test_one_persons_choices_are_theirs_alone(chosen):
    chosen.change(1, languages.OWN, {"audio": "eng"})
    chosen.change(1, "100", {"captions": True})
    assert chosen.wanted(2, EP) is None
    assert chosen.own(2) == Choice() and chosen.own(1).audio == "eng"
    chosen.clear(2, "100")
    assert chosen.chosen_for(1, "100") == Choice(captions=True)


def test_each_person_keeps_their_newest_choices(chosen, monkeypatch):
    monkeypatch.setattr(languages, "KEPT", 3)
    chosen.change(1, languages.OWN, {"audio": "jpn"})
    for n in range(5):
        chosen.change(1, str(500 + n), {"audio": "eng"})
    kept = chosen.db.languages_of(1, [languages.OWN, *(str(500 + n) for n in range(5))])
    assert set(kept) == {languages.OWN, "502", "503", "504"}


# Playing --------------------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path):
    fp = LibraryPlex()
    fp.add_show("100", "Orbit Room")
    fp.add_episode("201", "100", 1, 1, "Pilot", "/x/1.mkv", 22 * 60_000)
    fp.add_episode("202", "100", 1, 2, "Second", "/x/2.mkv", 22 * 60_000)
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "A Film", "/x/film.mkv", 90 * 60_000, section="2")
    for key in ("201", "202", "300"):
        fp.describe(key)
        k = int(key) * 10
        fp.streams[key][1:] = [
            {"id": k + 2, "streamType": 2, "codec": "aac", "channels": 2, "language": "日本語",
             "languageCode": "jpn", "default": True, "index": 1},
            {"id": k + 3, "streamType": 2, "codec": "aac", "channels": 2, "language": "English",
             "languageCode": "eng", "title": "Commentary", "index": 2},
            {"id": k + 4, "streamType": 2, "codec": "aac", "channels": 6, "language": "English",
             "languageCode": "eng", "index": 3},
            {"id": k + 5, "streamType": 3, "codec": "pgs", "language": "English",
             "languageCode": "eng", "forced": True, "index": 4},
            {"id": k + 6, "streamType": 3, "codec": "srt", "language": "English",
             "languageCode": "eng", "index": 5},
            {"id": k + 7, "streamType": 3, "codec": "pgs", "language": "Japanese",
             "languageTag": "ja", "index": 6},
        ]  # fmt: skip
        fp.files[key] = b"a program, as it is" * 100
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "d")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    app.state.ctx.play_transport = fp.transport()
    return app


def bearer(client: TestClient, who: dict) -> dict[str, str]:
    signed = client.post("/api/internal/sign-in", json=who)
    assert signed.status_code == 200, signed.text
    return {"Authorization": f"Bearer {signed.json()['token']}"}


def play(client: TestClient, key: str, headers: dict, **more) -> dict:
    played = client.post(
        "/api/internal/play", headers=headers, json={"key": key, "device": TV, **more}
    )
    assert played.status_code == 200, played.text
    answer = played.json()
    client.post(answer["leave"])
    return answer


def test_playing_what_each_person_chose(app):
    with TestClient(app) as home:
        assert home.post("/api/access/users", json=TIA).status_code == 201
        assert home.post("/api/access/users", json=SAM).status_code == 201
        assert home.put("/api/app-libraries", json={"libraries": ["1", "2"]}).status_code == 200
        tia, sam = bearer(home, TIA), bearer(home, SAM)
        # Nothing chosen: as before 1.29.0, the file as it is, nothing chosen.
        before = play(home, "201", tia)
        assert (before["method"], before["chosen"], before["drawnSubtitle"]) == (
            "direct", None, None
        )  # fmt: skip
        # Tia's own: English, captions on. Her player shows the text ones.
        mine = home.put("/api/internal/languages", headers=tia,
                        json={"audio": "eng", "captions": True})  # fmt: skip
        assert mine.json()["audio"] == {"code": "eng", "name": "English"}
        answer = play(home, "201", tia)
        assert answer["method"] == "direct" and answer["chosen"] == {
            "audio": "2014", "audioWhy": "English, as you chose",
            "subtitle": "2016", "subtitleWhy": "English subtitles, as you chose",
        }  # fmt: skip
        # Sam has chosen nothing: his plays are as before.
        assert play(home, "201", sam)["chosen"] is None
        # Japanese for the whole show, with Japanese captions: pictures,
        # which her player can't show, so they're drawn into a copy.
        show = home.put("/api/internal/items/100/languages", headers=tia,
                        json={"audio": "ja", "captionLanguage": "jpn"})  # fmt: skip
        assert show.json()["item"]["captionLanguage"] == {"code": "jpn", "name": "Japanese"}
        answer = play(home, "202", tia)
        assert (answer["method"], answer["drawnSubtitle"], answer["audioTrack"]) == (
            "convert", "2027", "2022"
        )  # fmt: skip
        assert "its subtitles, drawn into the picture" in answer["why"]
        assert answer["chosen"]["audioWhy"] == "Japanese, as chosen for this show"
        assert answer["chosen"]["subtitle"] == "2027"
        # Just this episode: captions off, so only English forced ones go
        # with English sound (drawn in: pictures).
        home.put("/api/internal/items/201/languages", headers=tia,
                 json={"audio": "eng", "captions": False})  # fmt: skip
        answer = play(home, "201", tia)
        assert (answer["chosen"]["audio"], answer["chosen"]["subtitle"]) == ("2014", "2015")
        assert answer["chosen"]["subtitleWhy"] == (
            "Forced English subtitles, for the parts in another language"
        )
        # Movies alike: hers, as she chose.
        answer = play(home, "300", tia)
        assert (answer["method"], answer["chosen"]["subtitle"]) == ("direct", "3006")
        # An app that says which tracks gets exactly those, as before.
        told = play(home, "202", tia, audio="2024")
        assert (told["method"], told["chosen"], told["drawnSubtitle"]) == ("direct", None, None)
        told = play(home, "202", tia, subtitle=None)
        assert told["chosen"] is None and told["method"] == "direct"
        # Without a way to draw them in (no copies), the file plays as it
        # is, and the app is told the captions can't be shown.
        no_copies = {**TV, "hls": []}
        played = home.post("/api/internal/play", headers=tia,
                           json={"key": "202", "device": no_copies}).json()  # fmt: skip
        assert played["method"] == "direct" and played["chosen"]["subtitle"] is None
        assert played["chosen"]["subtitleWhy"].endswith("This device can't show them")
        home.post(played["leave"])
        # Her choices are never Sam's, and his never hers.
        assert play(home, "202", sam)["chosen"] is None
        home.put("/api/internal/languages", headers=sam, json={"captions": True})
        assert play(home, "202", tia)["chosen"]["subtitle"] == "2027"
        details = home.get("/api/internal/items/202", headers=sam).json()["languages"]
        assert details == {"item": None, "show": None}
        whole = home.get("/api/internal/items/202", headers=tia).json()
        mine = whole["languages"]
        assert mine["item"] is None and mine["show"]["audio"]["code"] == "jpn"
        # Each track's code: what the player keeps when the viewer picks it.
        assert [t["languageCode"] for t in whole["audio"]] == ["jpn", "eng", "eng"]
        assert [t["languageCode"] for t in whole["subtitles"]] == ["eng", "eng", "jpn"]


def test_languages_that_wont_do_are_refused(app):
    with TestClient(app) as home:
        assert home.post("/api/access/users", json=TIA).status_code == 201
        home.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        tia = bearer(home, TIA)
        for body in (
            {"audio": "xx"}, {"captionLanguage": "Klingon"}, {"audio": 7}, {"audio": ["eng"]},
            {"captions": "yes"}, {"captions": 1}, {"captions": None}, {"audio": "e" * 41},
        ):  # fmt: skip
            refused = home.put("/api/internal/languages", headers=tia, json=body)
            assert refused.status_code == 400, body
            assert isinstance(refused.json()["detail"], str)
        assert home.get("/api/internal/me", headers=tia).json()["languages"]["audio"] is None
        refused = home.put("/api/internal/items/100/languages", headers=tia, json={"audio": "xx"})
        assert (
            refused.status_code == 400 and "doesn't know the language" in refused.json()["detail"]
        )
        # Only what's shared and seen; not a season (or anything but a show,
        # an episode or a movie).
        missing = home.put("/api/internal/items/999/languages", headers=tia, json={"audio": "eng"})
        assert missing.status_code == 404
        assert home.delete("/api/internal/items/999/languages", headers=tia).status_code == 404
        home.put("/api/app-libraries", json={"libraries": ["2"]})
        hidden = home.put("/api/internal/items/100/languages", headers=tia, json={"audio": "eng"})
        assert hidden.status_code == 404
        # Signing in is needed while it's on.
        stranger = TestClient(app)  # (no sign-in: the page's first Admin has a cookie)
        assert stranger.put("/api/internal/languages", json={"audio": "eng"}).status_code == 401
