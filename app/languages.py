"""Each person's languages in tapiOca's apps: the sound and subtitles
they want, kept by tapiOca so they follow them to every device (see
docs/internal-api.md, Languages).

A person has their own: a sound language (none: each file's default track),
subtitles Automatic, On or Off, and a subtitles language (the API calls
these `captions` and `captionLanguage`; `subtitles` says which of the
three). From the player, they can choose otherwise for a show (the whole
show: Sticky Audio and Sticky Subtitles, from 1.34.0), or for an episode or
a movie alone. When an app plays an episode or a movie without saying which
tracks (see applibrary.py), tapiOca chooses, each of the three on its
own: the episode's (or movie's) choice, else its show's, else the person's,
else the file's default.

Sound: the first track in that language (the file's default among them
first), never a commentary when there's another; with none in it, the
file's default. Subtitles On: a subtitle track in the subtitles language
(none: the sound's), a full one before a forced one (one for the deaf and
hard of hearing is a full one). Subtitles Off: only a forced track in the
language of the sound that plays, as forced subtitles are the parts in
another language, meant to be read. Subtitles Automatic (from 1.34.0; where
nothing turned them on or off, a person's own included): as On, in their
language, when the sound is in another; else as Off. Their language: their
subtitles language, else the device's (as the app says it, playing). When
the sound's language isn't known, a full track in their language the file
has on (its default) shows. Automatic is only for an app that sends the
device's language when it plays, as apps from tapiOca 1.34.0 do: for an
older one, nothing changes from 1.33.1 (subtitles nothing turned on are
off). A person's sound language is never taken as their language (the
audit of 1.34.0: Japanese sound chosen gave Japanese subtitles on every
English movie).

Languages are ISO 639-2 codes, as files carry them ("eng", "jpn"; for the
few with two, the one files use: "fre", "ger"). Two-letter codes ("en",
"pt-BR"), the other three-letter ones ("fra", "deu") and English names are
taken as them. Kept by tapiOca user (0 while signing in is off, when
everyone shares one), and never another's.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .catalog import EPISODE, MOVIE, SHOW

# What languages can be chosen for: a show (the whole show), an episode or
# a movie.
KINDS = (SHOW, EPISODE, MOVIE)

if TYPE_CHECKING:
    from .catalog import Entry, Media, Track
    from .db import Database

# The languages tapiOca knows, by code, as people read them.
NAMES = {
    "afr": "Afrikaans", "alb": "Albanian", "amh": "Amharic", "ara": "Arabic", "arm": "Armenian",
    "aze": "Azerbaijani", "baq": "Basque", "bel": "Belarusian", "ben": "Bengali",
    "bos": "Bosnian", "bul": "Bulgarian", "bur": "Burmese", "cat": "Catalan", "chi": "Chinese",
    "cze": "Czech", "dan": "Danish", "dut": "Dutch", "eng": "English", "epo": "Esperanto",
    "est": "Estonian", "fil": "Filipino", "fin": "Finnish", "fre": "French", "geo": "Georgian",
    "ger": "German", "gla": "Scottish Gaelic", "gle": "Irish", "glg": "Galician", "gre": "Greek",
    "guj": "Gujarati", "heb": "Hebrew", "hin": "Hindi", "hrv": "Croatian", "hun": "Hungarian",
    "ice": "Icelandic", "ind": "Indonesian", "ita": "Italian", "jpn": "Japanese",
    "kan": "Kannada", "kaz": "Kazakh", "khm": "Khmer", "kor": "Korean", "lao": "Lao",
    "lat": "Latin", "lav": "Latvian", "lit": "Lithuanian", "ltz": "Luxembourgish",
    "mac": "Macedonian", "mal": "Malayalam", "mar": "Marathi", "may": "Malay", "mlt": "Maltese",
    "mon": "Mongolian", "nep": "Nepali", "nor": "Norwegian", "pan": "Punjabi", "per": "Persian",
    "pol": "Polish", "por": "Portuguese", "rum": "Romanian", "rus": "Russian", "sin": "Sinhala",
    "slo": "Slovak", "slv": "Slovenian", "som": "Somali", "spa": "Spanish", "srp": "Serbian",
    "swa": "Swahili", "swe": "Swedish", "tam": "Tamil", "tel": "Telugu", "tgl": "Tagalog",
    "tha": "Thai", "tur": "Turkish", "ukr": "Ukrainian", "urd": "Urdu", "uzb": "Uzbek",
    "vie": "Vietnamese", "wel": "Welsh", "yor": "Yoruba", "zul": "Zulu",
}  # fmt: skip
# Two-letter codes (ISO 639-1), and the other three-letter ones (and old
# ones files still carry), as the codes above.
_ALIASES = {
    "af": "afr", "sq": "alb", "am": "amh", "ar": "ara", "hy": "arm", "az": "aze", "eu": "baq",
    "be": "bel", "bn": "ben", "bs": "bos", "bg": "bul", "my": "bur", "ca": "cat", "zh": "chi",
    "cs": "cze", "da": "dan", "nl": "dut", "en": "eng", "eo": "epo", "et": "est", "fi": "fin",
    "fr": "fre", "ka": "geo", "de": "ger", "gd": "gla", "ga": "gle", "gl": "glg", "el": "gre",
    "gu": "guj", "he": "heb", "iw": "heb", "hi": "hin", "hr": "hrv", "hu": "hun", "is": "ice",
    "id": "ind", "in": "ind", "it": "ita", "ja": "jpn", "kn": "kan", "kk": "kaz", "km": "khm",
    "ko": "kor", "lo": "lao", "la": "lat", "lv": "lav", "lt": "lit", "lb": "ltz", "mk": "mac",
    "ml": "mal", "mr": "mar", "ms": "may", "mt": "mlt", "mn": "mon", "ne": "nep", "no": "nor",
    "nb": "nor", "nn": "nor", "pa": "pan", "fa": "per", "pl": "pol", "pt": "por", "ro": "rum",
    "mo": "rum", "ru": "rus", "si": "sin", "sk": "slo", "sl": "slv", "so": "som", "es": "spa",
    "sr": "srp", "sw": "swa", "sv": "swe", "ta": "tam", "te": "tel", "tl": "tgl", "th": "tha",
    "tr": "tur", "uk": "ukr", "ur": "urd", "uz": "uzb", "vi": "vie", "cy": "wel", "yo": "yor",
    "zu": "zul",
    "sqi": "alb", "hye": "arm", "eus": "baq", "mya": "bur", "zho": "chi", "ces": "cze",
    "nld": "dut", "fra": "fre", "kat": "geo", "deu": "ger", "ell": "gre", "isl": "ice",
    "mkd": "mac", "msa": "may", "fas": "per", "ron": "rum", "slk": "slo", "cym": "wel",
    "nob": "nor", "nno": "nor", "mol": "rum", "scc": "srp", "scr": "hrv",
}  # fmt: skip
_NAMED = {name.casefold(): code for code, name in NAMES.items()}
LONGEST = 40  # a language as an app sends it, at most

# Where a choice was made, as the apps' players say why.
EPISODE_LEVEL, MOVIE_LEVEL, SHOW_LEVEL, YOURS = EPISODE, MOVIE, SHOW, "you"
# A show's choices, as people know them (from 1.34.0).
STICKY_AUDIO, STICKY_SUBTITLES = "Sticky Audio", "Sticky Subtitles"
# Subtitles, as the apps choose them (`subtitles`, from 1.34.0), and the
# `captions` each is kept as (a person's own: None is Automatic).
AUTOMATIC, ON, OFF = "automatic", "on", "off"
SUBTITLES = {AUTOMATIC: None, ON: True, OFF: False}
CHOOSE_SUBTITLES = "Choose subtitles Automatic, On or Off"
OWN = ""  # (the person's own, by the key they're kept under)
KEPT = 5000  # choices for shows, episodes and movies kept for each person (the newest)


def code(value: object) -> str | None:
    """A language as its code ("en", "en-US", "eng", "English": "eng"); None
    if it isn't one tapiOca knows (or isn't a language: "und")."""
    text = value.strip().casefold() if isinstance(value, str) else ""
    if not text or len(text) > LONGEST:
        return None
    if text in NAMES:
        return text
    if text in _NAMED:
        return _NAMED[text]
    main = text.replace("_", "-").split("-")[0]
    if main in NAMES:
        return main
    return _ALIASES.get(main)


def name(language: str) -> str:
    """A language's code as people read it: "Japanese"."""
    return NAMES.get(language, language)


def as_json(language: str | None) -> dict[str, str] | None:
    """A language, as the apps are told: its code and its name."""
    return {"code": language, "name": name(language)} if language else None


def choices() -> list[dict[str, str]]:
    """Every language tapiOca knows, A to Z by name, for the apps' Options."""
    return sorted(
        ({"code": c, "name": n} for c, n in NAMES.items()), key=lambda x: x["name"].casefold()
    )


def track_code(track: Track) -> str | None:
    """A track's language, as its code."""
    return track.language_code or code(track.language)


def commentary(track: Track) -> bool:
    return "commentary" in track.title.casefold()


def changes(given: dict[str, Any], own: bool) -> dict[str, Any]:
    """What an app sent to change (`given`: audio, captions, subtitles and
    captionLanguage, as it sent them), as Languages.change takes it: each
    language a code (two-letter codes and the like made one), or None.
    ValueError, with a sentence to show, for a language tapiOca doesn't
    know; and for a person's own (`own`), for captions that aren't true or
    false (for a show, an episode or a movie, null clears it), and
    subtitles that aren't automatic, on or off (only for a person's own,
    and never with captions)."""
    out: dict[str, Any] = {}
    for field, key in (("audio", "audio"), ("captionLanguage", "caption_language")):
        if field not in given:
            continue
        value = given[field]
        found = code(value) if value is not None else None
        if value is not None and found is None:
            shown = "".join(c for c in str(value) if c.isprintable())[:LONGEST]
            raise ValueError(
                f"tapiOca doesn't know the language \u201c{shown}\u201d. Send its code, such "
                "as eng or jpn."
            )
        out[key] = found
    if "subtitles" in given:
        if not own:
            raise ValueError("For a show, an episode or a movie, send captions")
        if "captions" in given:
            raise ValueError("Send subtitles or captions, not both")
        said = given["subtitles"]
        if not isinstance(said, str) or said not in SUBTITLES:
            raise ValueError(CHOOSE_SUBTITLES)
        out["captions"] = SUBTITLES[said]
    if "captions" in given:
        if given["captions"] is None and own:
            raise ValueError("Subtitles must be on or off")
        out["captions"] = given["captions"]
    return out


def subtitles(choice: Choice) -> str:
    """A person's own subtitles, as the apps choose them: automatic, on or
    off."""
    return AUTOMATIC if choice.captions is None else ON if choice.captions else OFF


@dataclass(frozen=True)
class Choice:
    """What's chosen in one place (a person's own, or for a show, an episode
    or a movie): each None where nothing is chosen there. (A person's own:
    None for the sound is each file's default; for captions, Automatic, with
    an app that sends the device's language, else off; for the captions
    language, the sound's with captions on, else the device's.)"""

    audio: str | None = None
    captions: bool | None = None
    caption_language: str | None = None

    @property
    def empty(self) -> bool:
        return self.audio is None and self.captions is None and self.caption_language is None

    def as_json(self) -> dict[str, Any]:
        return {
            "audio": as_json(self.audio),
            "captions": self.captions,
            "captionLanguage": as_json(self.caption_language),
        }


@dataclass(frozen=True)
class Wanted:
    """What a person wants for one episode or movie, each with where it was
    chosen (EPISODE_LEVEL, MOVIE_LEVEL, SHOW_LEVEL or YOURS; "" for nowhere).
    `automatic`: subtitles weren't turned on or off anywhere, so they show
    when the sound isn't in the person's language (`yours`; None: not
    known)."""

    audio: str | None
    audio_from: str
    captions: bool
    captions_from: str
    caption_language: str | None
    caption_from: str
    automatic: bool = False
    yours: str | None = None


@dataclass(frozen=True)
class Picked:
    """The tracks chosen in a version of a file, and why, in a few words."""

    audio: Track | None
    audio_why: str
    subtitle: Track | None
    subtitle_why: str


def _as(level: str, sticky: str) -> str:
    """Where a choice was made, ending a sentence: "as you chose"; for a
    show, kept by Sticky Audio or Sticky Subtitles (`sticky`)."""
    if level == SHOW_LEVEL:
        return f"kept for this show by {sticky}"
    return "as you chose" if level == YOURS else f"as chosen for this {level}"


def _first(tracks: list[Track]) -> Track:
    """The file's default among them, else the first."""
    return next((t for t in tracks if t.default), tracks[0])


def pick(media: Media, wanted: Wanted) -> Picked:
    """The tracks to play in a version of a file for what a person wants
    (see the module's notes)."""
    audio, audio_why = _pick_audio(media, wanted)
    sound = track_code(audio) if audio is not None else None
    subtitle, subtitle_why = _pick_subtitle(media, wanted, sound)
    return Picked(audio, audio_why, subtitle, subtitle_why)


def _pick_audio(media: Media, wanted: Wanted) -> tuple[Track | None, str]:
    default = media.default_audio
    if default is None:
        return None, "It has no sound"
    if wanted.audio is None:
        return default, "The file's default"
    found = [t for t in media.audio if track_code(t) == wanted.audio]
    if not found:
        return default, f"The file's default: it has no {name(wanted.audio)} sound"
    found = [t for t in found if not commentary(t)] or found
    return _first(found), f"{name(wanted.audio)}, {_as(wanted.audio_from, STICKY_AUDIO)}"


def _forced(media: Media, sound: str | None) -> tuple[Track | None, str]:
    """A forced track in the sound's language (the parts in another
    language, meant to be read), if there's one."""
    forced = [t for t in media.subtitles if t.forced and sound and track_code(t) == sound]
    if not forced:
        return None, ""
    return _first(
        forced
    ), f"Forced {name(sound or '')} subtitles, for the parts in another language"


def _in(media: Media, language: str, said: str) -> tuple[Track | None, str]:
    """A subtitle track in `language`, a full one before a forced one, with
    why (`said`, the reason it's in that language), if there's one."""
    found = [t for t in media.subtitles if track_code(t) == language]
    full = [t for t in found if not t.forced]
    if full:
        return _first(full), said
    if found:
        return _first(found), f"{said} (forced only: it has no others in {name(language)})"
    return None, ""


def _pick_subtitle(media: Media, wanted: Wanted, sound: str | None) -> tuple[Track | None, str]:
    if wanted.automatic:
        return _automatic(media, wanted.yours, sound)
    if not wanted.captions:
        forced, why = _forced(media, sound)
        if forced is not None:
            return forced, why
        off = "Subtitles are off"
        if not wanted.captions_from:
            return None, off
        return None, f"{off}, {_as(wanted.captions_from, STICKY_SUBTITLES)}"
    language = wanted.caption_language or sound
    if language is None:
        return None, "No subtitles: the sound's language isn't known"
    said = f"{name(language)} subtitles, {_as(wanted.captions_from, STICKY_SUBTITLES)}"
    found, why = _in(media, language, said)
    if found is not None:
        return found, why
    return None, f"No subtitles: it has none in {name(language)}"


def _automatic(media: Media, yours: str | None, sound: str | None) -> tuple[Track | None, str]:
    """Automatic subtitles: in the person's language (`yours`) when the
    sound is in another; else only the sound's forced ones (see the
    module's notes)."""
    if yours is None:
        none = "No subtitles: your language isn't known"
    elif sound is None:
        on = [t for t in media.subtitles
              if t.default and not t.forced and track_code(t) == yours]  # fmt: skip
        if on:
            return on[0], f"{name(yours)} subtitles, as the file has them on"
        none = "No subtitles: the sound's language isn't known"
    elif sound == yours:
        none = f"No subtitles: the sound is in {name(sound)}, your language"
    else:
        said = f"{name(yours)} subtitles, as the sound is {name(sound)}"
        found, why = _in(media, yours, said)
        if found is not None:
            return found, why
        none = f"No subtitles: it has none in {name(yours)}"
    forced, why = _forced(media, sound)
    return (forced, why) if forced is not None else (None, none)


class Languages:
    """Each person's languages, kept in the database (see the module's
    notes)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def own(self, user_id: int) -> Choice:
        return self.db.languages_of(user_id, [OWN]).get(OWN) or Choice()

    def chosen_for(self, user_id: int, key: str) -> Choice | None:
        return self.db.languages_of(user_id, [key]).get(key)

    def change(self, user_id: int, key: str, changes: dict[str, Any]) -> Choice:
        """Changes what's chosen (`changes`: audio, captions and
        caption_language, each a code or None, captions True, False or
        None) for a person's own (key OWN) or for a show, an episode or a
        movie; what isn't given stays. What's chosen now."""
        found = self.db.languages_of(user_id, [key]).get(key) or Choice()
        new = Choice(
            changes.get("audio", found.audio),
            changes.get("captions", found.captions),
            changes.get("caption_language", found.caption_language),
        )
        if key != OWN and new.empty:
            self.db.clear_languages(user_id, key)
        else:
            self.db.save_languages(user_id, key, new, _now(), KEPT)
        return new

    def clear(self, user_id: int, key: str) -> None:
        self.db.clear_languages(user_id, key)

    def wanted(self, user_id: int, entry: Entry, sent: str | None = None) -> Wanted | None:
        """What a person wants for an episode or a movie: each of the three
        from the most particular place it's chosen. `sent`: the device's
        language, as the app sent it playing (None: it sent none, as apps
        before tapiOca 1.34.0 don't). Only then are subtitles nothing
        turned on or off Automatic, in the person's language (their
        subtitles language, else the device's); otherwise they're off, as
        in 1.33.1. None when nothing is chosen anywhere and the device's
        language isn't known (then nothing is chosen for them: the file
        plays as it did before tapiOca 1.29.0)."""
        device = code(sent) if sent is not None else None
        level = EPISODE_LEVEL if entry.kind == EPISODE else MOVIE_LEVEL
        places = [(entry.key, level)]
        if entry.kind == EPISODE and entry.show_key:
            places.append((entry.show_key, SHOW_LEVEL))
        places.append((OWN, YOURS))
        found = self.db.languages_of(user_id, [key for key, _ in places])
        if not found and device is None:
            return None  # (as 1.33.1, with or without a language tapiOca doesn't know)
        said = [(found[key], where) for key, where in places if key in found]

        def first(field: str) -> tuple[Any, str]:
            for choice, where in said:
                value = getattr(choice, field)
                if value is not None:
                    return value, where
            return None, ""

        audio, audio_from = first("audio")
        captions, captions_from = first("captions")
        caption, caption_from = first("caption_language")
        if captions is None and sent is not None:
            yours = caption or device
            return Wanted(audio, audio_from, False, YOURS, caption, caption_from, True, yours)
        return Wanted(audio, audio_from, bool(captions), captions_from, caption, caption_from)

    def for_item(self, user_id: int, entry: Entry) -> dict[str, Any]:
        """What a person chose for a show, an episode or a movie (`item`),
        and for an episode's show (`show`), as its details say."""
        show_key = entry.show_key if entry.kind == EPISODE and entry.show_key else None
        found = self.db.languages_of(user_id, [entry.key, *([show_key] if show_key else [])])
        mine, show = found.get(entry.key), found.get(show_key or "")
        return {
            "item": mine.as_json() if mine else None,
            "show": show.as_json() if show and show_key else None,
        }


def _now() -> int:
    return int(time.time() * 1000)
