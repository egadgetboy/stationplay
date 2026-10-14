"""Doors left open (1.36.0): what reached tapiOca in a way that can't be
home (see networks.py), noted for Admins: the latest address for each, on
the Access tab, and the access log, at most once an hour for each; and the
alerts (see alerts.py), which never say an address (they go to the web
addresses an Admin chose).

  home-port      the home port reached from an internet address (a port
                 forward to it), or asked for by an internet address
  proxy          a proxy sending internet visitors (or ones it can't name)
                 to the home port
  name           the home port asked for by an internet name, with nothing
                 saying who it's for (a tunnel pointed at it, or a name the
                 home's own DNS gives: then an Admin says so)
  proxy-unknown  forwarding headers from a device that isn't a trusted
                 proxy (ignored: only an Admin lists a proxy)

Kept in memory only: a restart forgets them (the alerts say it again once
it happens again).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .networks import IP, Verdict, parse_peer
from .text import plain

HOME_PORT, PROXY, NAME, PROXY_UNKNOWN = "home-port", "proxy", "name", "proxy-unknown"
DOORS = (HOME_PORT, PROXY, NAME, PROXY_UNKNOWN)
LOG_EVERY_S = 3600.0  # each door in the access log at most this often
RECENT_S = 24 * 3600.0  # an alert is fixed once its door is this long unseen

_LOGGED = {
    HOME_PORT: "{address} reached tapiOca's home port from the internet. tapiOca treated it as "
    "from the internet: close that port forward.",
    PROXY: "{address} sent tapiOca's home port a visitor from the internet, or one it didn't "
    "name. tapiOca treated it as from the internet: point that proxy at the public port.",
    NAME: "{address} reached tapiOca's home port by the internet name {host}. If that's a name "
    "you use at home, add it under Names for tapiOca at home on the Access tab.",
    PROXY_UNKNOWN: "tapiOca ignored forwarding headers from {address}: it isn't a trusted proxy.",
}


class Doors:
    """What reached tapiOca through each door, and when (see the module's
    notes). `record`: the access log's (a level and a sentence)."""

    def __init__(self, record: Callable[[int, str], None] | None = None) -> None:
        self.record = record
        self._seen: dict[str, tuple[float, str, str]] = {}  # door: (when, address, host)
        self._logged: dict[str, float] = {}

    def note(self, verdict: Verdict, host: str | None = None) -> None:
        """A request, as judged: the doors it came through, if any."""
        if verdict.why == "home-port":
            self._saw(HOME_PORT, verdict, host)
        elif verdict.why == "proxy":
            self._saw(PROXY, verdict, host)
        if verdict.door3:
            self._saw(NAME, verdict, host)
        if verdict.untrusted_headers and verdict.why in ("", "public-port"):
            self._saw(PROXY_UNKNOWN, verdict, host)

    def _saw(self, door: str, verdict: Verdict, host: str | None) -> None:
        now = time.time()
        address = str(verdict.peer) if verdict.peer is not None else "an unknown address"
        shown_host = plain(host or "")[:100]
        self._seen[door] = (now, address, shown_host)
        if self.record is not None and now - self._logged.get(door, 0.0) >= LOG_EVERY_S:
            self._logged[door] = now
            self.record(logging.WARNING, _LOGGED[door].format(address=address, host=shown_host))

    def recent(self, door: str, within_s: float = RECENT_S) -> bool:
        seen = self._seen.get(door)
        return seen is not None and time.time() - seen[0] < within_s

    def forget_listed(self, is_proxy: Callable[[IP], bool]) -> None:
        """(1.36.2) A device that's a trusted proxy now: the headers it sent
        before aren't a door any more, and its alert ends at the next look
        (the owner, October 14, saw "isn't a trusted proxy" beside the proxy
        he'd just trusted)."""
        seen = self._seen.get(PROXY_UNKNOWN)
        ip = parse_peer(seen[1]) if seen is not None else None
        if ip is not None and is_proxy(ip):
            del self._seen[PROXY_UNKNOWN]

    def listed(self) -> list[dict[str, Any]]:
        """For Admins (the Access tab): each door's latest address, and when."""
        return [
            {"about": door, "address": address, "lastMs": int(when * 1000), "host": host}
            for door, (when, address, host) in sorted(self._seen.items())
        ]
