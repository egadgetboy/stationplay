"""Who's watching which station, as Plex says: its Live TV sessions
(/status/sessions), each matched to the station airing what it shows.

Plex's session for Live TV shows the program its guide has (StationPlay's
guide), the Plex user watching, and sometimes the channel's number. A
session is matched to one of the stations with viewers (`playing`: each
station's id -> its number, and what its schedule has on now): the one
airing that very program (its show and episode, or movie), else the one
airing that show; where Plex names a channel number, only a station with
that number. Two stations airing the same thing, with no number to tell
them apart, match neither.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .db import Item

Playing = dict[int, tuple[int, "Item"]]

_NUMBER = re.compile(r"0*(\d{1,6})")


def live(session: dict[str, Any]) -> bool:
    return str(session.get("live", "0")).lower() in ("1", "true")


def user_of(session: dict[str, Any]) -> tuple[str, str]:
    """The Plex user of a session: their id (Plex's account id; "1" is the
    server's owner) and name; ("", "") if Plex doesn't say."""
    given = session.get("User")
    user: dict[str, Any] = given if isinstance(given, dict) else {}
    name = str(user.get("title") or "").strip()
    uid = str(user.get("id") or "").strip()
    return (uid if uid.isdigit() else "", name)


def channel_numbers(session: dict[str, Any]) -> set[str]:
    """Any channel number Plex gives a Live TV session (StationPlay's guide
    and tuner both number a station's channel with the station's number)."""
    found: set[str] = set()
    for place in (session, *(session.get("Media") or [])):
        if isinstance(place, dict):
            for key in ("channelVcn", "channelIdentifier"):
                if place.get(key) not in (None, ""):
                    found.add(str(place[key]).strip())
    return found


def names(numbers: set[str], number: int) -> bool:
    """Whether one of the channel numbers is a station's number."""
    return any((m := _NUMBER.fullmatch(n)) and int(m.group(1)) == number for n in numbers)


def shows(session: dict[str, Any], item: Item, strictly: bool) -> bool:
    """Whether a Live TV session is showing a station's program: the same
    show (and, `strictly`, episode), or movie."""
    title = str(session.get("title") or "").strip().casefold()
    show = str(session.get("grandparentTitle") or "").strip().casefold()
    if item.kind == "episode":
        theirs = (item.show_title or "").casefold()
        if show:
            return show == theirs and (not strictly or title == item.title.casefold())
        return not strictly and title == theirs  # (the show's name alone)
    return title == item.title.casefold()


def session_station(session: dict[str, Any], playing: Playing) -> int | None:
    """The station a Plex session is watching (see above); None if it isn't
    Live TV, or can't be told."""
    if not live(session):
        return None
    numbers = channel_numbers(session)
    for strictly in (True, False):
        found = [cid for cid, (_, item) in playing.items() if shows(session, item, strictly)]
        if numbers:
            found = [cid for cid in found if names(numbers, playing[cid][0])]
        if len(found) == 1:
            return found[0]
        if found:
            return None  # (two stations airing it, and nothing to tell which)
    return None


def sure_station(session: dict[str, Any], playing: Playing) -> tuple[int | None, str]:
    """The station a session is watching, if that's sure enough to stop it
    (limits.py): matched (see above), and either by that very program or by
    the channel number Plex names. Else None, and why (if it's Live TV)."""
    if not live(session):
        return None, ""
    cid = session_station(session, playing)
    what = " / ".join(
        str(session.get(k) or "").strip() for k in ("grandparentTitle", "title") if session.get(k)
    )
    numbers = channel_numbers(session)
    if cid is None:
        on = ", ".join(sorted(numbers)) or "unknown"
        return None, f"can't tell which station it's watching ({what or 'no title'}, channel {on})"
    number, item = playing[cid]
    if shows(session, item, strictly=True) or names(numbers, number):
        return cid, ""
    return None, (
        f"it's showing the same show as station {number}, but StationPlay can't be sure it's "
        "that station"
    )
