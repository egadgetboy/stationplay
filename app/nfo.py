"""NFO files, Kodi's format, as Sonarr, Radarr, Jellyfin, Emby and
tinyMediaManager write them: the first layer of a folder library's details
(see folders.py).

    tvshow.nfo                 a show
    season.nfo                 a season (its folder's)
    <episode's file>.nfo       an episode (or several, for a file of several)
    movie.nfo, <file>.nfo      a movie

Read safely: an NFO is text someone else wrote. At most MOST_BYTES; any
DOCTYPE or entity declaration and it isn't read at all (nothing an XML
parser could be led to fetch or expand); one that can't be read is skipped
(and the caller says so on the Logs tab once). Only the details tapiOca
uses are taken, each cut to a sensible length.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from . import ratings

MOST_BYTES = 1 << 20
TEXT_MOST = 4000  # a plot's characters, at most
NAME_MOST = 200  # a title's, a person's or a genre's
LIST_MOST = 50  # genres, studios, people
# What a file holds besides an NFO's XML: a web address naming what it is
# (some tools write only that, or that after the XML).
_IMDB = re.compile(r"(?<![a-z0-9])(tt\d{5,10})(?![0-9])", re.I)
_TMDB = re.compile(r"themoviedb\.org/(?:movie|tv)/(\d{1,10})", re.I)
# (TheTVDB's addresses are found whole first, then read: every search here
# takes time in step with the text, whatever it holds.)
_TVDB = re.compile(r"thetvdb\.com/[^\s<>\"']*", re.I)
_TVDB_ID = re.compile(r"[?&]id=(\d{1,10})|/series/(\d{1,10})")
_UNSAFE = (b"<!doctype", b"<!entity")
ROOTS = ("tvshow", "season", "episodedetails", "movie")


class NfoError(ValueError):
    """Why an NFO can't be read."""


def parse(data: bytes) -> list[dict[str, Any]]:
    """What an NFO says: one dict of details for each show, season, episode
    or movie in it (a file of several episodes has several), each with its
    "kind" (tvshow, season, episodedetails or movie). NfoError if it can't
    be read."""
    if len(data) > MOST_BYTES:
        raise NfoError("it's over 1 MB")
    low = data.lower()
    if any(word in low for word in _UNSAFE):
        raise NfoError("it declares a DOCTYPE or entities, which tapiOca doesn't read")
    text = data.decode("utf-8-sig", errors="replace")
    # (Its XML declaration goes: several roots are read inside one of ours.)
    body = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    try:
        root = _xml("<nfo>" + _xml_only(body) + "</nfo>")
    except NfoError:
        # (Only a web address, with an & that isn't XML's: read as one.)
        ids = _ids_in_text(text)
        if ids:
            return [{"kind": "", "ids": ids}]
        raise
    found = [_details(e) for e in root if e.tag.lower() in ROOTS]
    if found:
        return found
    ids = _ids_in_text(text)
    if ids:
        return [{"kind": "", "ids": ids}]
    raise NfoError("it isn't an NFO tapiOca can read")


def _xml_only(body: str) -> str:
    """The XML of an NFO, without a web address after it (or anything else
    after its last element), as some tools write them."""
    closing = list(re.finditer(r"</(tvshow|season|episodedetails|movie)\s*>", body, re.I))
    return body[: closing[-1].end()] if closing else body


def _xml(text: str) -> ET.Element:
    try:
        return ET.fromstring(text)
    except ET.ParseError as e:
        raise NfoError(f"its XML can't be read ({e})") from None


# Countries as tools write them before a rating ("UK:18", "Germany:16"), as
# Plex writes them ("gb/18", "de/16": see ratings.py).
_COUNTRY = {
    "us": "", "usa": "", "united states": "", "uk": "gb", "gb": "gb", "united kingdom": "gb",
    "great britain": "gb", "ireland": "ie", "australia": "au", "new zealand": "nz",
    "canada": "ca", "france": "fr", "germany": "de", "netherlands": "nl", "brazil": "br",
    "spain": "es", "japan": "jp", "italy": "it", "sweden": "se", "norway": "no",
    "denmark": "dk", "finland": "fi", "austria": "at", "switzerland": "ch",
}  # fmt: skip
_RATED = re.compile(r"^rated\s+", re.I)
# Countries' two-letter codes, as ratings.py knows them.
_CODES = {
    code: code for code in (*ratings.COUNTRIES, "de", "it", "se", "no", "dk", "fi", "at", "ch")
}


def read_rating(text: str) -> str:
    """A rating as Plex writes it ("R", "gb/18"), however a tool wrote it:
    "Rated R", "US:R", "UK:18", "R (for violence)", "PG-13 for language".
    What can't be read is left as it was (and is unrated: see ratings.py)."""
    text = " ".join(text.split())
    country = ""
    for mark in (":", "/"):
        before, said, after = text.partition(mark)
        if said and before.strip().casefold() in _COUNTRY | {c: c for c in _COUNTRY.values() if c}:
            country = _COUNTRY.get(before.strip().casefold(), before.strip().casefold())
            text = after.strip()
            break
        if said and len(before.strip()) == 2 and before.strip().isalpha():
            country, text = before.strip().casefold(), after.strip()
            break
    # ("GB-15", "DE-16": a country's code, a dash, its rating; never a US
    # rating such as "TV-14" or "PG-13".)
    dashed = re.match(r"^([A-Za-z]{2})-(.+)$", text)
    if (
        not country
        and dashed
        and dashed.group(1).casefold() in _COUNTRY | _CODES
        and text.upper() not in ratings.US
    ):
        code = dashed.group(1).casefold()
        country, text = _COUNTRY.get(code, code), dashed.group(2).strip()
    text = _RATED.sub("", re.sub(r"\s*\(.*$", "", text)).strip()
    if text.upper() not in _WHOLE and " " in text:
        first = text.split(" ", 1)[0]
        text = text if first.upper() in ("FSK", "BBFC") else first
    return f"{country}/{text}" if country and text else text


# (Ratings of more than one word, read whole.)
_WHOLE = {"NOT RATED", "FSK 0", "FSK 6", "FSK 12", "FSK 16", "FSK 18"}


def _ids_in_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for kind, pattern in (("imdb", _IMDB), ("tmdb", _TMDB)):
        found = pattern.search(text)
        if found:
            out[kind] = found.group(1).lower()
    for address in _TVDB.finditer(text):
        found = _TVDB_ID.search(address.group())
        if found:
            out["tvdb"] = found.group(1) or found.group(2)
            break
    return out


def _text(e: ET.Element | None, most: int = NAME_MOST) -> str:
    if e is None:
        return ""
    return " ".join("".join(e.itertext()).split())[:most]


def _child(e: ET.Element, name: str) -> ET.Element | None:
    for c in e:
        if c.tag.lower() == name:
            return c
    return None


def _children(e: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in e if c.tag.lower() == name]


def _number(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.isascii() and text.isdigit() and len(text) < 7 else None


def _rating(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return round(value, 1) if 0 < value <= 10 else None


def _date(text: str) -> str:
    found = re.match(r"(\d{4})-(\d{2})-(\d{2})", text.strip())
    return found.group(0) if found else ""


def _names(e: ET.Element, tag: str) -> list[str]:
    out: list[str] = []
    for c in _children(e, tag):
        # (A few tools write several in one, separated by " / ".)
        for name in _text(c).split(" / "):
            name = name.strip()
            if name and name not in out:
                out.append(name)
    return out[:LIST_MOST]


def _details(e: ET.Element) -> dict[str, Any]:
    """One show's, season's, episode's or movie's details, by tapiOca's
    names for them (see folders.FIELDS); only those it has."""
    kind = e.tag.lower()
    out: dict[str, Any] = {"kind": kind}
    for field, tag in (
        ("title", "title"),
        ("original_title", "originaltitle"),
        ("sort_title", "sorttitle"),
        ("tagline", "tagline"),
        ("content_rating", "mpaa"),
    ):
        value = _text(_child(e, tag))
        if field == "content_rating":
            value = read_rating(value)
        if value:
            out[field] = value
    summary = _text(_child(e, "plot"), TEXT_MOST) or _text(_child(e, "outline"), TEXT_MOST)
    if summary:
        out["summary"] = summary
    year = _number(_text(_child(e, "year")))
    released = _date(_text(_child(e, "premiered"))) or _date(_text(_child(e, "aired")))
    if released:
        out["released"] = released
    if year is None and released:
        year = int(released[:4])
    if year is not None and 1880 <= year <= 2100:
        out["year"] = year
    runtime = _number(_text(_child(e, "runtime")))
    if runtime:
        out["runtime_min"] = runtime
    for field, tag in (
        ("season", "season"),
        ("episode", "episode"),
        ("display_season", "displayseason"),
        ("display_episode", "displayepisode"),
    ):
        number = _number(_text(_child(e, tag)))
        if number is not None:
            out[field] = number
    for field, tag in (
        ("genres", "genre"),
        ("labels", "tag"),
        ("studios", "studio"),
        ("directors", "director"),
        ("writers", "credits"),
    ):
        names = _names(e, tag)
        if names:
            out[field] = names
    cast = _cast(e)
    if cast:
        out["cast"] = cast
    sets = _sets(e)
    if sets:
        out["collections"] = sets
    rating = _audience_rating(e)
    if rating is not None:
        out["audience_rating"] = rating
    ids = _ids(e)
    if ids:
        out["ids"] = ids
    return out


def _cast(e: ET.Element) -> list[list[str]]:
    """Who's in it, as billed (by each actor's <order>, then as listed):
    [[name, role]]."""
    found = []
    for n, actor in enumerate(_children(e, "actor")):
        name = _text(_child(actor, "name"))
        if not name:
            continue
        order = _number(_text(_child(actor, "order")))
        found.append(
            (order if order is not None else 10_000 + n, n, name, _text(_child(actor, "role")))
        )
    found.sort()
    return [[name, role] for _, _, name, role in found[:LIST_MOST]]


def _sets(e: ET.Element) -> list[str]:
    """The collections a movie is in: <set>Name</set>, or as newer tools
    write it, <set><name>Name</name></set>."""
    out = []
    for s in _children(e, "set"):
        name = _text(_child(s, "name")) or _text(s)
        if name and name not in out:
            out.append(name)
    return out


def _audience_rating(e: ET.Element) -> float | None:
    """Its rating out of 10: the default of <ratings>, or <rating>."""
    ratings = _child(e, "ratings")
    if ratings is not None:
        chosen = [r for r in _children(ratings, "rating") if r.get("default") == "true"]
        for r in chosen or _children(ratings, "rating"):
            value = _rating(_text(_child(r, "value")))
            if value is not None:
                return value
    return _rating(_text(_child(e, "rating")))


def _ids(e: ET.Element) -> dict[str, str]:
    """Its IDs elsewhere: <uniqueid type="imdb">, and the older <imdbid>,
    <tmdbid>, <tvdbid> and <id>."""
    out: dict[str, str] = {}
    for u in _children(e, "uniqueid"):
        kind = (u.get("type") or "").strip().lower()
        value = _text(u)
        kind = {"themoviedb": "tmdb", "thetvdb": "tvdb"}.get(kind, kind)
        if kind in ("imdb", "tmdb", "tvdb") and _usable(kind, value):
            out.setdefault(kind, value.lower())
    for kind in ("imdb", "tmdb", "tvdb"):
        value = _text(_child(e, f"{kind}id"))
        if _usable(kind, value):
            out.setdefault(kind, value.lower())
    plain = _text(_child(e, "id"))
    if _usable("imdb", plain):
        out.setdefault("imdb", plain.lower())
    return out


def _usable(kind: str, value: str) -> bool:
    if kind == "imdb":
        return bool(re.fullmatch(r"tt\d{5,10}", value, re.I))
    return value.isascii() and value.isdigit() and 0 < len(value) <= 10 and value != "0"
