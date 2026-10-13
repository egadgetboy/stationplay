"""Relays (1.36.0): addresses that carry other people's connections, never
trusted (see trusted.py): Docker's gateway (its userland proxy, Docker
Desktop), a router's hairpin, a VPN gateway that masquerades, tapiOca's own
addresses, and loopback.

When every connection seems to come from one (door 5: tapiOca can't see
where connections come from), trusted networks are off altogether, and the
Access tab says why and how to fix it: it fails closed (the owner, October
13: "how security works if we accidentally leave doors open"). What comes
from a relay and from devices seen as themselves is partly hidden: those
from the relay are never trusted, the rest are as listed.

  hidden   at least HIDDEN_AFTER page or API requests on the home port from
           relays in the last WINDOW_S, and fewer than SEEN_AGAIN from
           anything else (a few, from a container on Docker's network say,
           don't show that devices are seen as themselves)
  partial  some from relays, and at least SEEN_AGAIN from anything else
  seen     otherwise

Once hidden, it stays hidden through a quiet hour (nothing comes, so
nothing is shown): only SEEN_AGAIN requests from devices seen as themselves
end it, or a restart.

Loopback (the image's health check) counts for neither, and nor does the
tuner (Plex's and Jellyfin's requests: see tuner.py). Read from /proc at
most every REREAD_S, in place (a few small tables); what can't be read is
nothing, and if the routing table itself can't be (tapiOca run from source
off Linux, say), trust is off ("unreadable").
"""

from __future__ import annotations

import contextlib
import ipaddress
import socket
import struct
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from .networks import IP

WINDOW_S = 3600.0
HIDDEN_AFTER = 20  # requests from relays alone before it's hidden
SEEN_AGAIN = 5  # requests from anything else before it's no longer hidden
REREAD_S = 60.0
LOOPBACK = {ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1")}


def read(route: str, fib_trie: str, if_inet6: str, ipv6_route: str) -> set[IP]:
    """The relays /proc's tables name: every gateway, and this machine's own
    addresses (and loopback)."""
    found: set[IP] = set(LOOPBACK)
    for line in route.splitlines()[1:]:
        parts = line.split()
        if len(parts) > 2 and parts[2] != "00000000":
            with contextlib.suppress(ValueError, struct.error):
                found.add(
                    ipaddress.ip_address(socket.inet_ntoa(struct.pack("<L", int(parts[2], 16))))
                )
    last = ""
    for line in fib_trie.splitlines():
        text = line.strip()
        if text.startswith("|--"):
            last = text[3:].strip()
        elif text.startswith("/32 host LOCAL") and last:
            with contextlib.suppress(ValueError):
                found.add(ipaddress.ip_address(last))
    for line in if_inet6.splitlines():
        parts = line.split()
        if parts and len(parts[0]) == 32:
            with contextlib.suppress(ValueError):
                found.add(ipaddress.IPv6Address(int(parts[0], 16)))
    for line in ipv6_route.splitlines():
        parts = line.split()
        if len(parts) > 4 and len(parts[4]) == 32 and parts[4] != "0" * 32:
            with contextlib.suppress(ValueError):
                found.add(ipaddress.IPv6Address(int(parts[4], 16)))
    return found


def _proc(name: str) -> str:
    try:
        return Path("/proc/net", name).read_text(errors="replace")
    except OSError:
        return ""


def read_proc() -> set[IP] | None:
    """This machine's relays, from /proc; None if its routing table can't
    be read (then trust is off: see Relays.trust_off)."""
    route = _proc("route")
    if not route.strip():
        return None
    return read(route, _proc("fib_trie"), _proc("if_inet6"), _proc("ipv6_route"))


from_proc = read_proc  # (how tapiOca reads them: the tests' are fixed, see conftest.py)


class Relays:
    """The relays (see the module's notes), and whether connections seem
    to come only from them. `found`: how they're read (from_proc)."""

    def __init__(self, found: Callable[[], set[IP] | None] = from_proc) -> None:
        self.found = found
        self._relays: set[IP] = set(LOOPBACK)
        self._readable = False
        self._read_at = 0.0
        self._from_relays: deque[float] = deque()
        self._from_others: deque[float] = deque()
        self._hidden = False
        self.last_relay = ""  # the latest relay a request came from

    def refresh(self) -> None:
        """Reads the relays again."""
        got = self.found()
        self._readable = got is not None
        self._relays = (got or set()) | LOOPBACK
        self._read_at = time.monotonic()

    def relays(self) -> set[IP]:
        if time.monotonic() - self._read_at > REREAD_S:
            self.refresh()
        return self._relays

    def is_relay(self, ip: IP | None) -> bool:
        return ip is not None and ip in self.relays()

    def note(self, ip: IP | None) -> None:
        """A page or API request on the home port, from `ip`: as connected,
        or the visitor a trusted proxy names."""
        if ip is None or ip in LOOPBACK:
            return
        now = time.monotonic()
        if self.is_relay(ip):
            self._from_relays.append(now)
            self.last_relay = str(ip)  # (for the Access tab's notice, in memory only)
        else:
            self._from_others.append(now)
        self._tally(now)

    def _tally(self, now: float) -> None:
        for kept in (self._from_relays, self._from_others):
            while kept and now - kept[0] > WINDOW_S:
                kept.popleft()
            while len(kept) > 1000:
                kept.popleft()
        relayed, others = len(self._from_relays), len(self._from_others)
        # (Hidden stays hidden while nothing comes: a quiet hour shows
        # nothing. Only devices seen as themselves end it, or a restart.)
        if relayed >= HIDDEN_AFTER and others < SEEN_AGAIN:
            self._hidden = True
        elif others >= SEEN_AGAIN:
            self._hidden = False

    def state(self) -> str:
        """ "hidden", "partial" or "seen" (see the module's notes); or
        "unreadable": the routing table can't be read."""
        self.relays()
        if not self._readable:
            return "unreadable"
        self._tally(time.monotonic())
        if self._hidden:
            return "hidden"
        if self._from_relays and self._from_others:
            return "partial"
        return "seen"

    def trust_off(self) -> bool:
        """Whether trusted networks are off: relays hide every device, or
        what's a relay can't be told."""
        return self.state() in ("hidden", "unreadable")

    def reset(self) -> None:
        self._from_relays.clear()
        self._from_others.clear()
        self._hidden = False
