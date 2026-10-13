"""Tuner access: which devices may use tapiOca's tuner.

The tuner is what Plex, Jellyfin and other apps use, and none of them can
sign in: the HDHomeRun tuner itself (discover.json, lineup.json and the
rest), the guide (xmltv.xml), the list of stations (stations.m3u), the
stations' streams (/stream/, /auto/, and /hls/ at home) and pictures for the
guide (/art/). It's only ever on the home port (see access.py). An Admin
chooses, on the Access tab:

  * Any device on my home network (the default, as before): anything that
    reaches the home port.
  * Only these devices: only the addresses listed. **Plex server only**
    lists Plex's own address with one click.

tapiOca's own apps, signed in, never need listing: each signed-in app at
home gets its stations at an address of its own (see away.py's keys), as it
does away from home, whichever is chosen, so changing it never stops one.
With signing in off, an app is a device like any other.

**Recent tuner connections** lists who used the tuner lately (by address:
what it called itself, what it asked for, when, and whether it was
refused), each refused one with **Allow**. A refused request is logged in
plain words (once an hour for each address, ten addresses an hour at most),
and while only listed devices may use it, the Access tab warns when Plex
can't (Plex in Docker often reaches tapiOca from the Docker network's
address, not the server's).

Anything can call itself Plex. So Plex's address is PLEX_URL's when Plex
was let in there, or else where something calling itself Plex was let in
lately; what was turned away is never taken for Plex's address, and the
Access tab says only that something calling itself Plex was turned away.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from . import networks as networks_module
from . import trusted

if TYPE_CHECKING:
    from .db import Database

log = logging.getLogger(__name__)

META = "tuner_access"
DEVICES_MOST = 50
NAME_MAX = 60
# Who used the tuner lately: kept this long, at most this many addresses.
RECENT_S = 7 * 24 * 3600.0
RECENT_MOST = 50
# A refused address is logged again after this long; this many an hour at most.
LOGGED_AGAIN_S = 3600.0
LOGGED_MOST = 10
# Plex is taken to use an address it was seen at this lately.
PLEX_SEEN_S = 2 * 24 * 3600.0

# The tuner's paths (see access.py: what Plex, Jellyfin and other apps use).
EXACT = frozenset({
    "/discover.json", "/lineup_status.json", "/lineup.json", "/lineup.post", "/device.xml",
    "/xmltv.xml", "/guide.xml", "/stations.m3u", "/channels.m3u",
})  # fmt: skip
UNDER = ("/stream/", "/auto/", "/art/", "/hls/")
OWN_ADDRESS = "/hls/k/"  # (an app's own address: its key says whose it is)

ADDRESS_PROBLEM = "Enter a device's IP address, such as 192.168.1.20"
PLEX = "Plex Media Server"


def is_tuner(path: str) -> bool:
    """Whether a request for `path` uses the tuner."""
    return path in EXACT or (path.startswith(UNDER) and not path.startswith(OWN_ADDRESS))


def asked_for(path: str) -> str:
    """What a request for `path` asked of the tuner, in plain words."""
    if path in ("/xmltv.xml", "/guide.xml") or path.startswith("/art/"):
        return "the guide"
    if path in ("/stations.m3u", "/channels.m3u"):
        return "the list of stations"
    if path.startswith(("/stream/", "/auto/", "/hls/")):
        return "a station"
    return "the tuner"


def normalize(text: str) -> str:
    """A device's address as kept: an IP address (an IPv4 address written as
    IPv6, as itself). ValueError if it isn't one."""
    text = text.strip()
    if not text or len(text) > 60 or "%" in text or "/" in text:
        raise ValueError(ADDRESS_PROBLEM)
    try:
        ip = ipaddress.ip_address(text.strip("[]"))
    except ValueError:
        raise ValueError(ADDRESS_PROBLEM) from None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ip)


def as_kept(address: str) -> str:
    """A request's address, as addresses are kept (unchanged if it isn't an
    IP address). A link-local IPv6 address comes with its network's name
    after a % (fe80::1%eth0): it's kept without it, as it's listed."""
    if ":" in address:
        address = address.partition("%")[0]
    try:
        return normalize(address)
    except ValueError:
        return address


def named(user_agent: str) -> str:
    """What a device called itself (its user agent), in a few words: "Plex
    Media Server", "VLC", "Jellyfin"."""
    agent = user_agent or ""
    lowered = agent.lower()
    for word, name in (
        ("plexmediaserver", PLEX), ("plex", "Plex"), ("jellyfin", "Jellyfin"), ("emby", "Emby"),
        ("vlc", "VLC"), ("kodi", "Kodi"), ("channels", "Channels"), ("lavf", "FFmpeg"),
        ("stationplay", "tapiOca"),
    ):  # fmt: skip
        if word in lowered:
            return name
    first = re.match(r"[A-Za-z][A-Za-z0-9 ._-]{0,29}", agent)
    return first.group(0).strip() if first else ""


def plex_address(plex_url: str) -> str | None:
    """Plex's address, when Plex's own address (PLEX_URL) is written as an
    IP address."""
    try:
        host = urlsplit(plex_url).hostname or ""
        return normalize(host)
    except ValueError:
        return None


@dataclass
class Seen:
    """A device that used the tuner lately."""

    address: str
    name: str
    asked: str  # what it asked for last ("the guide", "a station"...)
    last: float  # when (time.time())
    refused: bool  # whether that was refused


class TunerAccess:
    """Which devices may use the tuner, and who did lately."""

    def __init__(self, db: Database, plex_url: str = "") -> None:
        self.db = db
        self.plex_url = plex_url
        self.only = False
        self.devices: dict[str, str] = {}  # address -> its name ("" if none given)
        # Networks too (1.36.0): CIDR -> its name. Kept apart from devices,
        # which 1.35.0 reads (and would drop these from).
        self.networks: dict[str, str] = {}
        self.recent: OrderedDict[str, Seen] = OrderedDict()
        # Where something calling itself Plex was let in, and turned away, lately.
        self._plex_seen: dict[str, float] = {}
        self._plex_turned: dict[str, float] = {}
        self._logged: dict[str, float] = {}
        self._said_more = 0.0  # (when "more were turned away" was logged)
        self._load()

    def _load(self) -> None:
        try:
            got = json.loads(self.db.get_meta(META) or "{}")
        except ValueError:
            got = {}
        if not isinstance(got, dict):
            got = {}
        devices: dict[str, str] = {}
        for d in got.get("devices") or []:
            if not isinstance(d, dict):
                continue
            try:
                address = normalize(str(d.get("address") or ""))
            except ValueError:
                continue
            devices[address] = str(d.get("name") or "")[:NAME_MAX]
        self.devices = dict(list(devices.items())[:DEVICES_MOST])
        networks_: dict[str, str] = {}
        for n in got.get("networks") or []:
            if not isinstance(n, dict):
                continue
            try:
                net = trusted.network_of(n.get("network"))
            except trusted.Refused:
                continue  # (what can't be read allows nothing)
            networks_[str(net)] = str(n.get("name") or "")[:NAME_MAX]
        self.networks = dict(list(networks_.items())[: max(0, DEVICES_MOST - len(self.devices))])
        # (Only listed devices, with none listed, would shut everything out:
        # it's never kept that way.)
        self.only = got.get("only") is True and bool(self.devices or self.networks)

    def _keep(self) -> None:
        self.db.set_meta(
            META,
            json.dumps({
                "only": self.only,
                "devices": [{"address": a, "name": n} for a, n in self.devices.items()],
                "networks": [{"network": k, "name": n} for k, n in self.networks.items()],
            }),
        )  # fmt: skip

    # Who may ----------------------------------------------------------------

    def allows(self, address: str) -> bool:
        """Whether a device at `address` may use the tuner: listed, or on a
        listed network."""
        if not self.only or as_kept(address) in self.devices:
            return True
        ip = networks_module.parse_peer(address)
        return ip is not None and any(
            ip.version == net.version and ip in net
            for net in map(ipaddress.ip_network, self.networks)
        )

    def save(
        self,
        only: bool,
        devices: list[tuple[str, str]],
        networks: list[tuple[str, str]] | None = None,
    ) -> None:
        """Any device on the home network (`only` False), or only `devices`
        (address, name) and those on `networks` (CIDR, name: home addresses
        only, 1.36.0; None keeps them as they are). ValueError if one isn't
        an address or a home network, or there are too many, or none while
        only they may."""
        kept: dict[str, str] = {}
        for address, name in devices:
            kept[normalize(address)] = name.strip()[:NAME_MAX]
        nets: dict[str, str] = dict(self.networks) if networks is None else {}
        for network, name in networks or []:
            try:
                nets[str(trusted.network_of(network))] = name.strip()[:NAME_MAX]
            except trusted.Refused as e:
                raise ValueError(str(e)) from None
        if len(kept) + len(nets) > DEVICES_MOST:
            raise ValueError(f"List {DEVICES_MOST} devices and networks at most")
        if only and not (kept or nets):
            raise ValueError("List at least one device, or choose Any device on my home network")
        self.only, self.devices, self.networks = only, kept, nets
        self._keep()

    def allow(self, address: str) -> None:
        """Lists the device at `address` (by the name it gave, if it used
        the tuner lately). ValueError if it isn't an address, or the list is
        full."""
        address = normalize(address)
        if address in self.devices:
            return
        if len(self.devices) >= DEVICES_MOST:
            raise ValueError(f"List {DEVICES_MOST} devices at most")
        seen = self.recent.get(address)
        self.devices[address] = seen.name if seen else ""
        self._keep()

    def plex_only(self) -> None:
        """Only Plex may use the tuner. ValueError if Plex's address isn't
        known (it hasn't been let in lately, and PLEX_URL isn't an IP
        address)."""
        addresses = self.plex_addresses()
        if not addresses and self.only:
            raise ValueError(
                "tapiOca doesn't know Plex's address yet. If Plex was turned away, choose "
                "Allow beside it under Recent tuner connections."
            )
        if not addresses:
            raise ValueError(
                "tapiOca doesn't know Plex's address yet. Open Live TV & DVR in Plex "
                "(so it uses tapiOca's tuner), then try again."
            )
        self.save(True, [(a, PLEX) for a in addresses], networks=[])  # (just Plex's)

    # Who did ----------------------------------------------------------------

    def used(self, address: str, user_agent: str, path: str, refused: bool) -> None:
        """A request for `path` from `address` (calling itself `user_agent`)
        used the tuner, or was refused (and is logged, once an hour)."""
        address = as_kept(address)
        now = time.time()
        name = named(user_agent)
        if name in (PLEX, "Plex"):
            # (Anything can call itself Plex: what was turned away is only
            # ever said to have been, never taken for Plex's address.)
            claims = self._plex_turned if refused else self._plex_seen
            claims[address] = now
            if len(claims) > RECENT_MOST:
                del claims[min(claims, key=lambda a: claims[a])]
        if address in self._plex_seen:
            name = PLEX  # (its streams say they're FFmpeg)
        before = self.recent.pop(address, None)
        if not name and before is not None:
            name = before.name
        self.recent[address] = Seen(address, name, asked_for(path), now, refused)
        while len(self.recent) > RECENT_MOST:
            self.recent.popitem(last=False)
        if refused and now - self._logged.get(address, 0.0) >= LOGGED_AGAIN_S:
            self._logged = {a: t for a, t in self._logged.items() if now - t < LOGGED_AGAIN_S}
            if len(self._logged) >= LOGGED_MOST:
                # (A device changing its IPv6 address for each request, say.)
                if now - self._said_more >= LOGGED_AGAIN_S:
                    self._said_more = now
                    log.warning(
                        "Turned more devices away from tapiOca's tuner this hour. Recent "
                        "tuner connections, on the Access tab, lists them."
                    )
                return
            self._logged[address] = now
            log.warning(
                "Turned away %s%s, which asked tapiOca's tuner for %s. Only the devices "
                "listed under Tuner access may use it: to let this one, choose Allow beside it "
                "on the Access tab.",
                address,
                f" ({name})" if name else "",
                asked_for(path),
            )

    def lately(self) -> list[Seen]:
        """Who used the tuner lately, the latest first."""
        since = time.time() - RECENT_S
        return [s for s in reversed(self.recent.values()) if s.last >= since]

    @staticmethod
    def _lately(claims: dict[str, float]) -> list[str]:
        """The addresses in `claims` seen lately, the latest first."""
        since = time.time() - PLEX_SEEN_S
        return [a for a, t in sorted(claims.items(), key=lambda at: -at[1]) if t >= since]

    def plex_addresses(self) -> list[str]:
        """Plex's addresses: its own (PLEX_URL), if that's an IP address and
        it was let in there lately, or nothing calling itself Plex was let
        in anywhere; or else where something calling itself Plex was let in
        lately. Never where one was turned away."""
        seen = self._lately(self._plex_seen)
        own = plex_address(self.plex_url)
        if own and (own in seen or not seen):
            return [own]
        return seen

    def warning(self) -> str:
        """Why Plex may not be able to use the tuner, while only listed
        devices may ("" if it can, or nothing says it can't)."""
        if not self.only:
            return ""
        own = plex_address(self.plex_url)
        seen = self._lately(self._plex_seen)
        if own and own in self.devices and own in seen:
            return ""  # (Plex was let in lately where PLEX_URL says it is)
        let_in = max((self._plex_seen[a] for a in seen if a in self.devices), default=0.0)
        turned = [
            a
            for a in self._lately(self._plex_turned)
            if a not in self.devices and self._plex_turned[a] > let_in
        ]
        if turned:
            return (
                f"Something calling itself Plex was turned away from {', '.join(turned)}. If "
                "that's your Plex server, choose Allow beside it below."
            )
        if let_in or (own and own in self.devices):
            return ""
        shut_out = [a for a in self.plex_addresses() if a not in self.devices]
        if not shut_out:
            return ""
        return (
            f"Plex uses tapiOca's tuner from {', '.join(shut_out)}, which isn't on the list, "
            "so Plex can't show your stations. Allow it below."
        )

    def as_dict(self) -> dict:
        """For the Access tab."""
        return {
            "only": self.only,
            "devices": [{"address": a, "name": n} for a, n in self.devices.items()],
            "networks": [{"network": k, "name": n} for k, n in self.networks.items()],
            "recent": [
                {
                    "address": s.address,
                    "name": s.name,
                    "asked": s.asked,
                    "lastMs": int(s.last * 1000),
                    "refused": s.refused,
                    "listed": s.address in self.devices,
                }
                for s in self.lately()
            ],
            "plex": self.plex_addresses(),
            "warning": self.warning(),
        }
