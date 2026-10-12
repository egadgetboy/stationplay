"""Automatic subtitles, Sticky Subtitles and Sticky Audio (from 1.34.0;
languages.py, and through appapi.py and applibrary.py).

Automatic subtitles: someone who hasn't turned subtitles on or off gets
them in their language when the sound is in another (their language: their
Subtitles language, else the device's). Sticky Subtitles and Sticky Audio:
what they choose in the player for a show holds for every episode, and the
answer's reasons say so.

The audit of 1.34.0 (the lead developer's decision): Automatic only when
the play asks with the device's `language`, as newer apps do; without it,
exactly as 1.33.1 (subtitles nobody turned on are off). And a person's
Audio language is never taken as their language: someone who watches with
Japanese sound doesn't get Japanese subtitles on an English movie."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import languages
from app.catalog import EPISODE, Entry, Media
from app.db import Database
from app.languages import Languages

from .test_languages import EP, FILE, FILM, SAM, TIA, TV, app, bearer, play, track  # noqa: F401

SECOND = Entry("202", EPISODE, "Second", show_key="100", media=(FILE,))
# Japanese sound, as a file without its language says it.
NAMELESS = replace(
    track("a9", "aac", "jpn", default=True, index=1), language="", language_code=None
)


@pytest.fixture
def chosen(tmp_path) -> Languages:
    return Languages(Database(tmp_path / "db.sqlite"))


def picked(wanted: languages.Wanted | None, media: Media = FILE) -> tuple[str | None, str, str]:
    assert wanted is not None
    found = languages.pick(media, wanted)
    return (found.subtitle.id if found.subtitle else None), found.audio_why, found.subtitle_why


def test_automatic_subtitles_are_in_your_language_when_the_sound_is_in_another(chosen):
    # Nothing chosen anywhere, and the device says English: the file's
    # default sound (Japanese), and English subtitles (the full ones).
    assert picked(chosen.wanted(1, EP, "eng")) == (
        "s2", "The file's default", "English subtitles, as the sound is Japanese"
    )  # fmt: skip
    assert picked(chosen.wanted(1, FILM, "eng"))[0] == "s2"
    # English sound: no full subtitles, but the forced ones still show.
    chosen.change(1, languages.OWN, {"audio": "eng"})
    assert picked(chosen.wanted(1, EP, "eng")) == (
        "s1", "English, as you chose", "Forced English subtitles, for the parts in another language"
    )  # fmt: skip
    # Without the device's language (an older app): as 1.33.1, subtitles
    # off, so only the forced ones.
    assert picked(chosen.wanted(1, EP)) == (
        "s1", "English, as you chose", "Forced English subtitles, for the parts in another language"
    )  # fmt: skip
    # Nothing chosen and no language known: nothing chosen, as before.
    assert chosen.wanted(2, EP) is None


def test_your_language_is_your_subtitles_language_then_the_devices(chosen):
    spanish = Media(
        container="mkv", video="h264", audio=FILE.audio,
        subtitles=(*FILE.subtitles, track("s5", "srt", "spa")),
    )  # fmt: skip
    # Japanese sound for someone whose Audio language is Japanese: the
    # device's English is their language.
    chosen.change(1, languages.OWN, {"audio": "jpn"})
    assert picked(chosen.wanted(1, EP, "eng"), spanish)[0] == "s2"
    # Without the device's language: as 1.33.1 (their Audio language isn't
    # taken as theirs).
    assert picked(chosen.wanted(1, EP), spanish) == (
        None, "Japanese, as you chose", "Subtitles are off"
    )  # fmt: skip
    # Their Subtitles language comes before the device's.
    chosen.change(1, languages.OWN, {"caption_language": "spa"})
    assert picked(chosen.wanted(1, EP, "eng"), spanish) == (
        "s5", "Japanese, as you chose", "Spanish subtitles, as the sound is Japanese"
    )  # fmt: skip
    # None in their language: none (or the sound's forced ones).
    assert picked(chosen.wanted(1, EP, "eng")) == (
        None, "Japanese, as you chose", "No subtitles: it has none in Spanish"
    )  # fmt: skip


def test_subtitles_turned_on_or_off_stay_so(chosen):
    chosen.change(1, languages.OWN, {"captions": False})
    assert picked(chosen.wanted(1, EP, "eng"))[::2] == (None, "Subtitles are off, as you chose")
    chosen.change(1, languages.OWN, {"captions": True})
    # On, with no Subtitles language: the sound's, as before.
    assert picked(chosen.wanted(1, EP, "eng"))[::2] == ("s4", "Japanese subtitles, as you chose")
    # Back to automatic.
    chosen.change(1, languages.OWN, {"captions": None})
    assert picked(chosen.wanted(1, EP, "eng"))[0] == "s2"


def test_when_the_sounds_language_isnt_known_the_file_says(chosen):
    plain = Media(container="mkv", video="h264", audio=(NAMELESS,), subtitles=FILE.subtitles)
    assert picked(chosen.wanted(1, EP, "eng"), plain) == (
        None, "The file's default", "No subtitles: the sound's language isn't known"
    )  # fmt: skip
    marked = Media(
        container="mkv", video="h264", audio=(NAMELESS,),
        subtitles=(FILE.subtitles[0], track("s2", "srt", "eng", default=True, index=5)),
    )  # fmt: skip
    assert picked(chosen.wanted(1, EP, "eng"), marked)[::2] == (
        "s2", "English subtitles, as the file has them on"
    )  # fmt: skip


def test_your_language_unknown_with_something_chosen(chosen):
    chosen.change(1, "100", {"audio": "jpn"})
    # (The device's language sent, but not one tapiOca knows.)
    assert picked(chosen.wanted(1, EP, "Klingon")) == (
        None, "Japanese, kept for this show by Sticky Audio", "No subtitles: your language isn't known"
    )  # fmt: skip
    # None sent (an older app): as 1.33.1.
    assert picked(chosen.wanted(1, EP)) == (
        None, "Japanese, kept for this show by Sticky Audio", "Subtitles are off"
    )  # fmt: skip


# An English movie: English sound only, with Japanese subtitles (and English
# forced ones).
ENGLISH = Media(
    container="mkv", video="h264", audio=(track("a5", "aac", "eng", default=True, index=1),),
    subtitles=(track("s1", "pgs", "eng", forced=True, index=2), track("s6", "srt", "jpn", index=3)),
)  # fmt: skip


def test_audio_japanese_on_an_english_movie_gets_no_japanese_subtitles(chosen):
    """(The audit of 1.34.0: someone who chose Japanese sound, subtitles
    never turned on or off, got Japanese subtitles on every English movie,
    their Audio language taken as theirs.)"""
    chosen.change(1, languages.OWN, {"audio": "jpn"})
    movie = replace(FILM, media=(ENGLISH,))
    # An older app, sending no language: exactly as 1.33.1.
    assert picked(chosen.wanted(1, movie), ENGLISH) == (
        "s1", "The file's default: it has no Japanese sound",
        "Forced English subtitles, for the parts in another language",
    )  # fmt: skip
    # A newer one, on an English device: the sound is in their language.
    assert picked(chosen.wanted(1, movie, "en-US"), ENGLISH) == (
        "s1", "The file's default: it has no Japanese sound",
        "Forced English subtitles, for the parts in another language",
    )  # fmt: skip
    # On a Japanese device, Japanese subtitles: their language is the device's.
    assert picked(chosen.wanted(1, movie, "ja-JP"), ENGLISH)[::2] == (
        "s6", "Japanese subtitles, as the sound is English"
    )  # fmt: skip


def as_1_33_1(wanted: languages.Wanted | None) -> tuple:
    """What 1.33.1 chose with what's kept (its Wanted: subtitles on or off,
    None counting as off)."""
    assert wanted is not None and not wanted.automatic
    return (wanted.audio, wanted.audio_from, wanted.captions, wanted.caption_language)


@pytest.mark.parametrize(
    "own",
    [
        {"audio": "jpn"},
        {"caption_language": "spa"},
        {"audio": "eng", "caption_language": "jpn"},
        {"captions": True},
        {"captions": False, "caption_language": "eng"},
    ],
)
def test_partly_chosen_languages_without_the_devices_are_as_1_33_1(chosen, own):
    """Someone's own languages, some chosen and subtitles never turned on or
    off (or turned on or off), with an older app: what 1.33.1 chose."""
    chosen.change(1, languages.OWN, own)
    got = chosen.wanted(1, EP)
    assert as_1_33_1(got) == (
        own.get("audio"), "you" if own.get("audio") else "", bool(own.get("captions")),
        own.get("caption_language"),
    )  # fmt: skip
    assert got.captions_from == ("you" if "captions" in own else "")


def test_partly_chosen_languages_with_the_devices_are_automatic(chosen):
    spanish = Media(
        container="mkv", video="h264", audio=FILE.audio,
        subtitles=(*FILE.subtitles, track("s5", "srt", "spa")),
    )  # fmt: skip
    # Only a Subtitles language: theirs, before the device's.
    chosen.change(1, languages.OWN, {"caption_language": "spa"})
    assert picked(chosen.wanted(1, EP, "en-US"), spanish) == (
        "s5", "The file's default", "Spanish subtitles, as the sound is Japanese"
    )  # fmt: skip
    # Only an Audio language: the device's is theirs.
    chosen.clear(1, languages.OWN)
    chosen.change(1, languages.OWN, {"audio": "eng"})
    assert picked(chosen.wanted(1, EP, "ja"), spanish)[::2] == (
        "s4", "Japanese subtitles, as the sound is English"
    )  # fmt: skip


def test_sticky_subtitles_and_sticky_audio_hold_for_every_episode(chosen):
    chosen.change(1, "100", {"audio": "jpn", "captions": True, "caption_language": "jpn"})
    for episode in (EP, SECOND):
        assert picked(chosen.wanted(1, episode, "eng")) == (
            "s4",
            "Japanese, kept for this show by Sticky Audio",
            "Japanese subtitles, kept for this show by Sticky Subtitles",
        )
    chosen.change(1, "100", {"captions": False})
    assert picked(chosen.wanted(1, SECOND, "eng"))[2] == (
        "Subtitles are off, kept for this show by Sticky Subtitles"
    )
    # One episode's own still comes first.
    chosen.change(1, "202", {"captions": True, "caption_language": "eng"})
    assert picked(chosen.wanted(1, SECOND, "eng"))[::2] == (
        "s2", "English subtitles, as chosen for this episode"
    )  # fmt: skip


def test_what_an_app_sends_for_subtitles_is_checked():
    assert languages.changes({"subtitles": "automatic"}, own=True) == {"captions": None}
    assert languages.changes({"subtitles": "on"}, own=True) == {"captions": True}
    assert languages.changes({"subtitles": "off"}, own=True) == {"captions": False}
    for bad in ("yes", "", None, True, "ON"):
        with pytest.raises(ValueError, match="Automatic, On or Off"):
            languages.changes({"subtitles": bad}, own=True)
    with pytest.raises(ValueError, match="not both"):
        languages.changes({"subtitles": "on", "captions": True}, own=True)
    with pytest.raises(ValueError, match="captions"):
        languages.changes({"subtitles": "on"}, own=False)


def test_the_apps_choose_automatic_on_or_off_and_send_the_devices_language(app):  # noqa: F811
    with TestClient(app) as home:
        assert home.post("/api/access/users", json=TIA).status_code == 201
        assert home.post("/api/access/users", json=SAM).status_code == 201
        assert home.put("/api/app-libraries", json={"libraries": ["1", "2"]}).status_code == 200
        tia, sam = bearer(home, TIA), bearer(home, SAM)
        mine = home.get("/api/internal/me", headers=tia).json()["languages"]
        assert (mine["subtitles"], mine["captions"]) == ("automatic", False)
        # The device's language: English subtitles for the Japanese sound.
        answer = play(home, "201", sam, language="en-US")
        assert answer["chosen"] == {
            "audio": "2012", "audioWhy": "The file's default",
            "subtitle": "2016", "subtitleWhy": "English subtitles, as the sound is Japanese",
        }  # fmt: skip
        # Without it (an older app), as before.
        assert play(home, "201", sam)["chosen"] is None
        # A language tapiOca doesn't know is no language.
        assert play(home, "201", sam, language="Klingon")["chosen"] is None
        assert home.post("/api/internal/play", headers=sam,
                         json={"key": "201", "device": TV, "language": "e" * 41}
                         ).status_code == 400  # fmt: skip
        # Off, then on, then automatic again, as the apps choose them.
        for said, captions in (("off", False), ("on", True), ("automatic", False)):
            saved = home.put("/api/internal/languages", headers=tia, json={"subtitles": said})
            assert saved.status_code == 200, saved.text
            assert (saved.json()["subtitles"], saved.json()["captions"]) == (said, captions)
            again = home.get("/api/internal/me", headers=tia).json()["languages"]
            assert again["subtitles"] == said
        # An older app's on and off still work.
        saved = home.put("/api/internal/languages", headers=tia, json={"captions": True})
        assert "subtitles" not in saved.json()  # (the answer it always had)
        assert home.get("/api/internal/me", headers=tia).json()["languages"]["subtitles"] == "on"
        refused = home.put("/api/internal/languages", headers=tia, json={"subtitles": "maybe"})
        assert refused.status_code == 400 and "Automatic, On or Off" in refused.json()["detail"]
        # Sticky Subtitles, from the player: every episode of the show.
        home.put("/api/internal/items/100/languages", headers=sam,
                 json={"captions": True, "captionLanguage": "jpn"})  # fmt: skip
        for key in ("201", "202"):
            answer = play(home, key, sam, language="en-US")
            assert answer["chosen"]["subtitleWhy"] == (
                "Japanese subtitles, kept for this show by Sticky Subtitles"
            )
