"""Content ratings, read as the youngest age each suits (see docs/users.md).

Plex writes a rating as the agent gave it: "PG-13" or "TV-14" for the US,
and for other countries usually with the country first, "gb/15", "de/12",
"au/MA15+". Each is read here as an age, so a Viewing Level's limit (an age)
can be compared with any of them. What can't be read (blank, "NR", "Not
Rated", a code not known here) is unrated: None.
"""

from __future__ import annotations

import re

# The United States: films (MPA) and television (TV Parental Guidelines).
US = {
    "G": 0,
    "PG": 10,
    "PG-13": 13,
    "R": 17,
    "NC-17": 18,
    "X": 18,
    "TV-Y": 0,
    "TV-G": 0,
    "TV-Y7": 7,
    "TV-Y7-FV": 7,
    "TV-Y7FV": 7,
    "TV-PG": 10,
    "TV-14": 14,
    "TV-MA": 17,
}

# Other countries' ratings that aren't simply the age they name (those, such
# as Germany's "12" or France's "-16", are read from their number).
COUNTRIES = {
    "gb": {"U": 0, "UC": 0, "PG": 10, "12A": 12, "R18": 18},
    "ie": {"G": 0, "PG": 10, "12A": 12, "15A": 15},
    "au": {"G": 0, "PG": 10, "M": 15, "MA15+": 15, "R18+": 18, "X18+": 18, "R": 18},
    "nz": {"G": 0, "PG": 10, "M": 16, "RP13": 13, "RP16": 16, "RP18": 18},
    "ca": {"G": 0, "PG": 10, "14A": 14, "18A": 18, "R": 18, "A": 18, "C": 0, "C8": 8},
    "fr": {"U": 0, "TP": 0},
    "nl": {"AL": 0},
    "br": {"L": 0, "ER": 0},
    "es": {"A": 0, "APTA": 0, "TP": 0},
    "jp": {"G": 0, "PG12": 12, "R15+": 15, "R18+": 18},
}

# A rating that names its age: "12", "16+", "-16", "FSK 12", "R18+", "MA15+".
_AGE = re.compile(r"^(?:FSK|BBFC|R|MA|M|A|K|N|PG|RP)?\s*[-]?\s*(\d{1,2})\s*\+?$")
# Ratings that say plainly that there's no rating.
_UNRATED = {
    "",
    "NR",
    "N/A",
    "NA",
    "UR",
    "UNRATED",
    "NOT RATED",
    "APPROVED",
    "PASSED",
    "E",
    "EXEMPT",
}

# What a Viewing Level's ages are shown as on the page (US ratings).
MOVIE_AT = {0: "G", 10: "PG", 13: "PG-13", 17: "R", 18: "NC-17"}
TV_AT = {0: "TV-G", 7: "TV-Y7", 10: "TV-PG", 14: "TV-14", 17: "TV-MA"}


def age(rating: str | None) -> int | None:
    """The youngest age a rating suits, or None if it's unrated (or can't be
    read)."""
    text = (rating or "").strip()
    country = ""
    if "/" in text:
        country, _, text = text.partition("/")
        country = country.strip().lower()
        text = text.strip()
    code = text.upper()
    if code in _UNRATED:
        return None
    if country and country != "us":
        known = COUNTRIES.get(country, {})
        if code in known:
            return known[code]
    elif code in US:
        return US[code]
    found = _AGE.match(code)
    if found:
        years = int(found.group(1))
        return years if years <= 21 else None
    # (A US rating with another country's mark.)
    return US.get(code)


def stricter(a: int | None, b: int | None) -> int | None:
    """The older of two ages: an episode's own rating, if stricter than its
    show's. Unrated (None) gives way to a rating."""
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def named(age: int, tv: bool) -> str:
    """An age as a US rating ("TV-14", "PG-13"), or "rated for ages 15 and
    up" when no US rating is that age."""
    found = (TV_AT if tv else MOVIE_AT).get(age)
    return f"rated {found}" if found else f"rated for ages {age} and up"
