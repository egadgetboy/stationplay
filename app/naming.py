"""What folder and file names say about a show, an episode or a movie: the
third layer of a folder library's details (see folders.py), after NFO files
and the tags inside the files.

The names Sonarr, Radarr, Plex, Jellyfin and Emby use, and the scene's:

    Show (2010)/Season 01/Show - S01E02 - Title.mkv
    Show (2010)/Specials/Show - S00E01.mkv        (or Season 00)
    Show - S01E02E03.mkv, Show - S01E02-E03.mkv   (one file, two episodes)
    Show - 1x02.mkv
    Show/Show - 2024-03-15 - Title.mkv            (a daily show)
    Movie (1999)/Movie (1999).mkv
    Movie (1999)/Movie (1999) - 4K.mkv            (a version of it)
    Movie (1999)/Movie (1999) - cd1.mkv           (part of it: cd, part, pt, disc, disk, dvd)

and IDs anywhere in a name: {tmdb-12345}, [tmdbid-12345], {imdb-tt0012345},
[imdbid-tt0012345], {tvdb-67890}, [tvdbid-67890].

Nothing here reads a file: it's names in, what they say out.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from dataclasses import dataclass, field

VIDEO_EXTENSIONS = frozenset(
    {".mkv", ".mp4", ".m4v", ".mov", ".avi", ".ts", ".m2ts", ".webm", ".wmv", ".mpg", ".mpeg"}
)
PICTURE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
# Folders of extras beside a show or movie, never programs of their own.
EXTRAS = frozenset(
    {
        "extras", "featurettes", "behind the scenes", "deleted scenes", "interviews", "trailers",
        "shorts", "other", "scenes", "samples", "sample",
    }
)  # fmt: skip
# Other folders that never hold programs: a NAS's own (Synology's thumbnails,
# its recycle bin), discs copied as they are, and tapiOca's commercials.
NOT_PROGRAMS = frozenset({"@eadir", "#recycle", "$recycle.bin", "bdmv", "video_ts", "commercials"})
# Extras named as Plex names them beside a movie ("Movie (1999)-trailer.mkv").
_EXTRA_FILE = re.compile(
    r"-(?:trailer|behindthescenes|deleted|featurette|interview|scene|short|other|sample)$", re.I
)
_SAMPLE = re.compile(r"(?<![a-z0-9])sample(?![a-z0-9])", re.I)

# IDs in names, as Plex ({tmdb-12345}) and Jellyfin ([tmdbid-12345]) write them.
_ID = re.compile(r"[\[{]\s*(tmdb|imdb|tvdb)(?:id)?\s*[-=]\s*(tt\d{5,10}|\d{1,10})\s*[\]}]", re.I)
_EDITION = re.compile(r"\{\s*edition\s*-\s*([^}]{1,60})\}", re.I)
_YEAR_AT_END = re.compile(r"\s*[(\[](\d{4})[)\]]\s*$")
_SEASON = re.compile(
    r"(?:season|series|saison|staffel|temporada|stagione|seizoen|s)[\s._-]*(\d{1,4})", re.I
)
_SPECIALS = frozenset({"specials", "special", "season 00", "season 0"})
# S01E02, S01E02E03 (Sonarr's "Repeat"), S01E02-03 and S01E02-E03 (a range:
# one file, several episodes), S01E02-03-04 and S01E02-E03-E04.
_SXE = re.compile(
    r"(?<![a-z0-9])s(\d{1,4})[\s._-]*e(\d{1,4})((?:[\s._]?e\d{1,4})*)((?:-e?\d{1,4}(?![0-9a-z]))*)",
    re.I,
)
_XNN = re.compile(r"(?<![0-9a-z])(\d{1,2})x(\d{2,3})(?![0-9a-z])", re.I)
_DATE = re.compile(r"(?<![0-9])(\d{4})[-._ ](\d{2})[-._ ](\d{2})(?![0-9])")
# A movie in parts: "cd1", "part 2", "pt1", "disc1", "disk2", "dvd1".
_PART = re.compile(r"[\s._-]*[\[(]?(?:cd|dvd|part|pt|disc|disk)[\s._-]*(\d{1,2})[\])]?$", re.I)
# A year in a scene name ("Glass.Garden.1999.1080p.BluRay"), with the title before it.
_SCENE_YEAR = re.compile(r"(?<![0-9])((?:19|20)\d{2})(?![0-9])")
# What a release says of its quality, at the end of a name ("WEBDL-1080p").
_QUALITY = re.compile(
    r"[\s._-]*[\[(]?(?:(?:web[\s.-]?dl|webrip|hdtv|sdtv|blu-?ray|bdrip|brrip|dvdrip|dvd-r|remux|"
    r"raw-hd|hdrip)(?:[\s._-]*(?:\d{3,4}[pi]|4k|uhd))?|\d{3,4}[pi]|4k|uhd|x26[45]|h\.?26[45]|"
    r"hevc|10bit|hdr10\+?|hdr|proper|repack)[\])]?$",
    re.I,
)
_BRACKETS_AT_END = re.compile(r"\s*\[[^\]]*\]$")
# A release group's tag before a name ("[SubsPlease] Show - 01").
_GROUP_FIRST = re.compile(r"^\s*\[[^\]]{1,40}\]\s*")
# Where a scene name's release details start: what follows isn't a title.
_RELEASE = re.compile(
    r"(?<![a-z0-9])(?:\d{3,4}[pi]|4k|uhd|web[\s.-]?dl|webrip|hdtv|sdtv|blu-?ray|bdrip|brrip|"
    r"dvdrip|remux|x26[45]|h\.?26[45]|hevc)(?![a-z0-9])",
    re.I,
)
# The largest a range of episodes in one file is taken to be.
RANGE_MOST = 20
# An episode's number alone, in a season's folder: "E02", "Ep 2", "Episode 2",
# or a name that starts with it ("02 - Title", "02. Title").
_NUMBER_ONLY = re.compile(
    r"^(?:(?:episode|ep|e)[\s._-]*(\d{1,4})(?![0-9])|(\d{1,3})(?:[\s._-]+|$))", re.I
)


@dataclass(frozen=True)
class Named:
    """A show's or movie's folder, as its name says: its title, year and IDs."""

    title: str = ""
    year: int | None = None
    ids: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EpisodeName:
    """An episode's file, as its name says."""

    show: str = ""  # the show's title, if the name starts with it
    season: int | None = None
    episodes: tuple[int, ...] = ()  # (several: one file, several episodes)
    aired: str = ""  # YYYY-MM-DD, for a show named by date
    title: str = ""  # the episode's own title, if the name has it
    year: int | None = None  # the show's year, if the name has it
    ids: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MovieName:
    """A movie's file, as its name says."""

    title: str = ""
    year: int | None = None
    ids: dict[str, str] = field(default_factory=dict)
    part: int | None = None  # cd1 is 1
    label: str = ""  # a version's own name ("4K", "Director's Cut"), "" if none


# Names in general -------------------------------------------------------------


def stem(name: str) -> str:
    """A file's name without its extension."""
    dot = name.rfind(".")
    return name[:dot] if dot > 0 else name


def extension(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def is_video(name: str) -> bool:
    return extension(name) in VIDEO_EXTENSIONS and not name.startswith(".")


def skipped_folder(name: str, top: bool = False) -> bool:
    """Whether a folder never holds programs: hidden, a NAS's own, a disc,
    extras, samples, or a .trickplay folder (Jellyfin's scrubbing pictures).
    `top`: right inside a library's folder, where it's a show or a movie
    whatever its name ("Shorts"), never extras."""
    low = name.casefold().strip()
    return (
        name.startswith(".")
        or low in NOT_PROGRAMS
        or (low in EXTRAS and not top)
        or low.endswith(".trickplay")
    )


def is_extra(name: str) -> bool:
    """Whether a file is an extra by its name ("Movie (1999)-trailer.mkv")."""
    return bool(_EXTRA_FILE.search(stem(name)))


def named_sample(name: str) -> bool:
    return bool(_SAMPLE.search(stem(name)))


def spaced(text: str) -> str:
    """A name as words: dots and underscores between words (scene names,
    "Show.Name.S01E02") made spaces, and spacing tidied."""
    if " " not in text.strip() and re.search(r"[._]", text):
        text = re.sub(r"(?<=[^\s])[._](?=[^\s])", " ", text)
    return " ".join(text.replace("_", " ").split())


def folded(text: str) -> str:
    """A title as titles are compared: case, accents and punctuation aside."""
    plain = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in plain).split())


def ids_in(name: str) -> dict[str, str]:
    """The IDs a name holds: {"imdb": "tt0012345", "tmdb": "12345", "tvdb": "67890"}."""
    out: dict[str, str] = {}
    for kind, value in _ID.findall(name):
        kind = kind.lower()
        if (kind == "imdb") == value.lower().startswith("tt"):
            out.setdefault(kind, value.lower())
    return out


def without_ids(name: str) -> str:
    return " ".join(_EDITION.sub(" ", _ID.sub(" ", name)).split())


def title_from(name: str) -> str:
    """A title made from a file's name when nothing else says one: as
    words, its IDs and release details left out ("Coastline.2010.Special.
    1080p.WEB-DL.x264-GRP" is "Coastline 2010 Special"), never the name as
    it is."""
    return _tidy_title(without_ids(stem(name)))


def folder_title(name: str) -> str:
    """A title from a folder's name, as title_from: "Some Film (2004)" is
    "Some Film"."""
    return _tidy_title(show_folder(name).title)


def _year(text: str) -> int | None:
    year = int(text)
    return year if 1880 <= year <= 2100 else None


def _title_and_year(text: str) -> tuple[str, int | None]:
    """ "Show (2010)" is ("Show", 2010); "Harbor Lights (US)" is itself, no year."""
    found = _YEAR_AT_END.search(text)
    if found and (year := _year(found.group(1))) is not None:
        return text[: found.start()].strip(" -._"), year
    return text.strip(" -._"), None


def _tidy_title(text: str) -> str:
    """What's left of a name for a title: a release group's tag before it,
    and release details at its end, gone ("" if nothing's left)."""
    text = _GROUP_FIRST.sub("", text)
    release = _RELEASE.search(text)
    if release:
        text = text[: release.start()]
    text = text.strip(" -._([{")
    while True:
        cut = _QUALITY.sub("", text)
        cut = _BRACKETS_AT_END.sub("", cut).strip(" -._")
        if cut == text:
            return spaced(text)
        text = cut


# Shows ----------------------------------------------------------------------------


def show_folder(name: str) -> Named:
    """A show's folder: "Show (2010) {tvdb-67890}"."""
    ids = ids_in(name)
    title, year = _title_and_year(spaced(without_ids(name)))
    return Named(title, year, ids)


def season_folder(name: str) -> int | None:
    """The season a folder is: "Season 01", "S01", "Series 2"; "Specials" is 0."""
    low = " ".join(name.casefold().split())
    if low in _SPECIALS:
        return 0
    found = _SEASON.fullmatch(name.strip())
    return int(found.group(1)) if found else None


def episode_name(name: str) -> EpisodeName:
    """An episode's file name (with or without its extension)."""
    base = stem(name) if extension(name) in VIDEO_EXTENSIONS else name
    ids = ids_in(base)
    base = without_ids(base)
    for found in _SXE.finditer(base):
        season, first = int(found.group(1)), int(found.group(2))
        numbers = [first, *(int(n) for n in re.findall(r"\d+", found.group(3) or ""))]
        dashed = [int(n) for n in re.findall(r"\d+", found.group(4) or "")]
        if len(dashed) == 1 and len(numbers) == 1 and first < dashed[0] <= first + RANGE_MOST:
            numbers += range(first + 1, dashed[0] + 1)  # (a range)
        else:
            numbers += dashed
        return _episode(base, found, season, tuple(dict.fromkeys(numbers)), "", ids)
    found_x = _XNN.search(base)
    if found_x:
        season, number = int(found_x.group(1)), int(found_x.group(2))
        return _episode(base, found_x, season, (number,), "", ids)
    for found_d in _DATE.finditer(base):
        try:
            day = datetime.date(*(int(found_d.group(i)) for i in (1, 2, 3)))
        except ValueError:
            continue
        if not 1900 <= day.year <= 2100:
            continue
        return _episode(base, found_d, None, (), day.isoformat(), ids)
    return EpisodeName(ids=ids, title="")


def number_only(name: str) -> tuple[int | None, str]:
    """An episode's number when its name has only that (in a season's
    folder: "02 - Title.mkv", "E02.mkv"), and the title after it; (None, "")
    if it doesn't start with one."""
    base = stem(name) if extension(name) in VIDEO_EXTENSIONS else name
    base = without_ids(base).strip()
    found = _NUMBER_ONLY.match(base)
    if not found:
        return None, ""
    number = int(found.group(1) or found.group(2))
    return number, _tidy_title(base[found.end() :])


def looks_like_release(text: str) -> bool:
    """Whether a title is really a file's or a release's name
    ("Show.S01E02.720p.WEB-DL"), as tags inside files often are: never
    taken as a title."""
    return bool(_SXE.search(text) or _RELEASE.search(text) or _XNN.search(text))


def _episode(
    base: str,
    found: re.Match,
    season: int | None,
    numbers: tuple[int, ...],
    aired: str,
    ids: dict[str, str],
) -> EpisodeName:
    show, year = _title_and_year(spaced(base[: found.start()]).strip(" -._"))
    title = _tidy_title(base[found.end() :])
    return EpisodeName(show, season, numbers, aired, title, year, ids)


# Movies ---------------------------------------------------------------------------


def movie_name(name: str, folder: str = "") -> MovieName:
    """A movie's file name (with or without its extension); `folder`, the
    name of the folder it's in, if that's the movie's own (it may name the
    movie better than the file, and the rest of the file's name is then the
    version's label, as Jellyfin has it)."""
    base = stem(name) if extension(name) in VIDEO_EXTENSIONS else name
    ids = ids_in(base)
    edition = _EDITION.search(base)
    label = " ".join(edition.group(1).split()) if edition else ""
    base = without_ids(base)
    part = None
    found_part = _PART.search(base)
    if found_part and found_part.start() > 0:
        part = int(found_part.group(1))
        base = base[: found_part.start()]
    text = spaced(base)
    if folder:
        own = show_folder(folder)
        rest = _rest_after(text, spaced(without_ids(folder)))
        # (The folder's name, then nothing, or " - " or brackets and a label:
        # "Glass Garden Returns (2003)" in a folder "Glass Garden" is another movie.)
        if own.title and rest is not None and (not rest.strip() or rest.lstrip()[:1] in "-[({"):
            return MovieName(own.title, own.year, {**own.ids, **ids}, part, label or _label(rest))
    paren = re.search(r"[(\[](\d{4})[)\]]", text)
    if paren and (year := _year(paren.group(1))) is not None and paren.start() > 0:
        title = text[: paren.start()].strip(" -._")
        return MovieName(title, year, ids, part, label or _label(text[paren.end() :]))
    for found in _SCENE_YEAR.finditer(text):
        year = _year(found.group(1))
        title = text[: found.start()].strip(" -._")
        if year is not None and title:
            return MovieName(title, year, ids, part, label or _quality_label(text[found.end() :]))
    title, _, rest = text.partition(" - ")
    if rest and _QUALITY.fullmatch(" " + rest.strip()):
        return MovieName(title.strip(), None, ids, part, label or _label(rest))
    return MovieName(_tidy_title(text), None, ids, part, label)


def _rest_after(text: str, prefix: str) -> str | None:
    """What's after `prefix` at the start of `text`, comparing them folded
    (case, accents and punctuation aside); None if `text` doesn't start
    with it."""
    want = folded(prefix)
    if not want or not folded(text).startswith(want):
        return None
    # (Up to the prefix's last letter or bracket: what separates the rest
    # stays with it, " - 4K".)
    last = None
    for i in range(1, len(text) + 1):
        if folded(text[:i]) == want:
            if text[i - 1] not in " -._":
                last = i
        elif last is not None:
            break
    return text[last:] if last is not None else None


def _label(rest: str) -> str:
    """A version's label, from what follows the movie's name: " - 4K" is "4K",
    " [Director's Cut]" is "Director's Cut"."""
    text = rest.strip(" -._")
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return " ".join(text.split())[:60]


def _quality_label(rest: str) -> str:
    """A version's label from a scene name's release details: its picture
    size, if it says ("1080p")."""
    found = re.search(r"(?<![0-9a-z])(\d{3,4}p|4k|uhd)(?![0-9a-z])", rest, re.I)
    return found.group(1) if found else ""
