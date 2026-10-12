"""Automatic subtitles, Sticky Subtitles and Sticky Audio (from 1.34.0;
languages.py, and through appapi.py and applibrary.py).

Automatic subtitles: someone who hasn't turned subtitles on or off gets
them in their language when the sound is in another (their language: their
Subtitles language, else the device's, else their Audio language). Sticky
Subtitles and Sticky Audio: what they choose in the player for a show holds
for every episode, and the answer's reasons say so."""

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
    # Without a device's language, their Audio language is theirs.
    assert picked(chosen.wanted(1, EP))[0] == "s1"
    # Nothing chosen and no language known: nothing chosen, as before.
    assert chosen.wanted(2, EP) is None


def test_your_language_is_your_subtitles_language_then_the_devices_then_your_audio(chosen):
    spanish = Media(
        container="mkv", video="h264", audio=FILE.audio,
        subtitles=(*FILE.subtitles, track("s5", "srt", "spa")),
    )  # fmt: skip
    # Japanese sound for someone whose Audio language is Japanese: the
    # device's English comes first.
    chosen.change(1, languages.OWN, {"audio": "jpn"})
    assert picked(chosen.wanted(1, EP, "eng"), spanish)[0] == "s2"
    assert picked(chosen.wanted(1, EP), spanish) == (
        None, "Japanese, as you chose", "No subtitles: the sound is in Japanese, your language"
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
    assert picked(chosen.wanted(1, EP)) == (
        None, "Japanese, kept for this show by Sticky Audio", "No subtitles: your language isn't known"
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
        # A language StationPlay doesn't know is no language.
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
