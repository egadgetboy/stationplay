"""What Plex sees: an HDHomeRun network tuner with a lineup and a guide.

Plex's Live TV & DVR talks to HDHomeRun tuners over a few small JSON
endpoints (discover, lineup, lineup status) and plays each channel from a
plain HTTP MPEG-TS URL. Guide data comes from an XMLTV file.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from . import specials
from .db import Channel, Item
from .logos import LIBRARY_VERSION
from .schedule import StationSchedule


def device_id_valid(device_id: str) -> bool:
    """An eight-digit hex ID, the form HDHomeRun tuners use."""
    try:
        int(device_id, 16)
    except ValueError:
        return False
    return len(device_id) == 8


def new_device_id() -> str:
    """A random ID for this installation, kept in the data folder so Plex
    keeps recognising the same tuner across restarts."""
    return f"{secrets.randbits(32):08X}"


def discover(name: str, device_id: str, base_url: str, tuner_count: int) -> dict:
    return {
        "FriendlyName": name,
        "Manufacturer": "StationPlay",
        "ManufacturerURL": base_url,
        "ModelNumber": "HDTC-2US",
        "FirmwareName": "hdhomeruntc_atsc",
        "FirmwareVersion": "20200101",
        "DeviceID": device_id,
        "DeviceAuth": "stationplay",
        "BaseURL": base_url,
        "LineupURL": f"{base_url}/lineup.json",
        "TunerCount": tuner_count,
    }


LINEUP_STATUS = {
    "ScanInProgress": 0,
    "ScanPossible": 1,
    "Source": "Cable",
    "SourceList": ["Cable"],
}


def lineup(channels: list[Channel], base_url: str) -> list[dict]:
    return [
        {
            "GuideNumber": str(c.number),
            "GuideName": c.name,
            "URL": f"{base_url}/stream/{c.number}",
            "HD": 1,
        }
        for c in channels
    ]


def device_xml(name: str, device_id: str, base_url: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <URLBase>{escape(base_url)}</URLBase>
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaServer:1</deviceType>
    <friendlyName>{escape(name)}</friendlyName>
    <manufacturer>StationPlay</manufacturer>
    <modelName>HDTC-2US</modelName>
    <modelNumber>HDTC-2US</modelNumber>
    <serialNumber>{escape(device_id)}</serialNumber>
    <UDN>uuid:{escape(device_id)}</UDN>
  </device>
</root>
"""


def icon_url(base_url: str, channel: Channel) -> str:
    """The station's logo. The version in the address changes with the logo
    (and with the logo library), so Plex fetches a new one rather than
    showing the one it cached."""
    return f"{base_url}/channel-icon/{channel.number}.png?v={LIBRARY_VERSION}-{channel.logo or 'number'}"


def _xmltv_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y%m%d%H%M%S +0000")


# What XML can't hold: control characters other than tab and new lines, and
# halves of characters (some programs' details in Plex have them). They're
# left out, so one program's details can never spoil the guide.
_NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _text(value: object) -> str:
    """Text for the guide: what XML can hold, trimmed and escaped."""
    return escape(_NOT_XML.sub("", str(value or "")).strip())


def _programme(
    item: Item, channel: Channel, start_ms: int, end_ms: int, base_url: str, special: str = ""
) -> str:
    """One program in the guide. Every part of it is checked, so a program
    with odd details in Plex (no title, an episode 0, stray characters)
    is still one Plex reads."""
    lines = [
        f"  <programme start={quoteattr(_xmltv_time(start_ms))} "
        f"stop={quoteattr(_xmltv_time(end_ms))} channel={quoteattr(str(channel.number))}>"
    ]
    name = _text(item.title)
    if item.kind == "episode":
        show = _text(item.show_title) or name
        lines.append(f'    <title lang="en">{show or "Untitled"}</title>')
        if name:
            lines.append(f'    <sub-title lang="en">{name}</sub-title>')
    else:
        lines.append(f'    <title lang="en">{name or "Untitled"}</title>')
    # (Part of a special, first: "Leave It to Beaver Marathon (1 of 3).",
    # "Feature Presentation.", or a block's name.)
    if special and special[-1] not in ".!?":
        special += "."
    summary = " ".join(p for p in (_text(special), _text(item.summary)) if p)
    if summary:
        lines.append(f'    <desc lang="en">{summary}</desc>')
    if isinstance(item.year, int) and 1800 <= item.year <= 2200:
        lines.append(f"    <date>{item.year}</date>")
    lines.append(
        f'    <category lang="en">{"Series" if item.kind == "episode" else "Movie"}</category>'
    )
    art_key = quote(str(item.show_key or item.rating_key), safe="")
    lines.append(f"    <icon src={quoteattr(f'{base_url}/art/{art_key}')} />")
    season, episode = item.season, item.episode
    if item.kind == "episode" and isinstance(season, int) and isinstance(episode, int):
        # xmltv_ns counts from 0 (season 1 episode 1 is "0.0."): only for
        # numbers it can show. An episode 0 still gets its S01E00.
        if season >= 1 and episode >= 1:
            lines.append(
                f'    <episode-num system="xmltv_ns">{season - 1}.{episode - 1}.</episode-num>'
            )
        if season >= 0 and episode >= 0:
            lines.append(
                f'    <episode-num system="onscreen">S{season:02d}E{episode:02d}</episode-num>'
            )
    lines.append("  </programme>")
    return "\n".join(lines)


def xmltv(
    channels: list[tuple[Channel, StationSchedule]],
    base_url: str,
    from_ms: int,
    to_ms: int,
) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE tv SYSTEM "xmltv.dtd">',
        '<tv generator-info-name="StationPlay">',
    ]
    for channel, _ in channels:
        out.append(f"  <channel id={quoteattr(str(channel.number))}>")
        out.append(f"    <display-name>{_text(channel.name)}</display-name>")
        out.append(f"    <display-name>{channel.number}</display-name>")
        out.append(f"    <icon src={quoteattr(icon_url(base_url, channel))} />")
        out.append("  </channel>")
    for channel, schedule in channels:
        out.extend(
            _programme(
                slot.item,
                channel,
                slot.start_ms,
                slot.end_ms,
                base_url,
                specials.label(schedule.special(slot), slot.index),
            )
            for slot in schedule.between(from_ms, to_ms)
        )
    out.append("</tv>")
    return "\n".join(out) + "\n"


def m3u(channels: list[Channel], base_url: str) -> str:
    # (url-tvg for most apps, x-tvg-url for Kodi's IPTV Simple Client.)
    guide = f"{base_url}/guide.xml"
    lines = [f'#EXTM3U url-tvg="{guide}" x-tvg-url="{guide}"']
    for c in channels:
        # A quote in a name would end the attribute; line breaks, the entry.
        name = " ".join(c.name.replace('"', "'").split())
        lines.append(
            f'#EXTINF:-1 tvg-id="{c.number}" tvg-chno="{c.number}" '
            f'tvg-name="{name}" tvg-logo="{icon_url(base_url, c)}",{name}'
        )
        lines.append(f"{base_url}/stream/{c.number}")
    return "\n".join(lines) + "\n"
