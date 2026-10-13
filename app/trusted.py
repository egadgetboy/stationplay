"""Trusted networks and trusted proxies (1.36.0): what an Admin lists, and
how it's kept. The rest (who a request is from, and what trust it gets) is
networks.py's and access.py's.

- Trusted networks: addresses or networks (CIDR: 192.168.1.0/24, one device
  as 192.168.1.44) whose devices skip signing in. Each gives "Who's tuning
  in?" (the default: each person picks themselves, kids get their own
  limits, and an Admin is always asked for their PIN or password) or
  "Signed in as" a person (an Admin only on one device's address).
- Trusted proxies: the reverse proxies whose forwarding headers say who a
  request is for. Only an Admin lists them: a device is never taken for a
  proxy because it sends such headers (the owner, October 13: "Don't just
  assume its your reverse proxy because it has the headers").
- Names for tapiOca at home: DNS names a home's own devices use for it, so
  they aren't taken for a tunnel pointed at the home port.

Nothing is trusted until an Admin lists it. Only home addresses can be
listed (never the internet's), a network wider than one home network only
when the Admin says so, and what can't be read trusts nothing (the owner:
"we are also focusing on how security works if we accidentally leave doors
open").
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import secrets
import time
from collections.abc import Callable
from typing import Any

from . import networks
from .db import Database
from .text import plain

log = logging.getLogger("stationplay.access")

META = "trusted_networks"
ENTRIES_MOST = 50
PROXIES_MOST = 10
HOME_NAMES_MOST = 10
LABEL_MOST = 40
NETWORK_TEXT_MOST = 50
# Wider than this (one home network) only when an Admin says so.
WIDEST = {4: 24, 6: 64}
GIVES = ("picker", "person")

INTERNET = (
    "That's an internet address. Only home network addresses can be trusted, such as "
    "192.168.x.x, 10.x.x.x, 172.16.x.x to 172.31.x.x, and VPN addresses like 100.64.x.x."
)
NOT_AN_ADDRESS = "Enter an address, such as 192.168.1.44, or a network, such as 192.168.1.0/24."
ADMIN_ONE_DEVICE = (
    "An Admin can be signed in only on one device. Enter one address, such as 192.168.1.44."
)
NO_SUCH_PERSON = "That person isn't on tapiOca any more."
BAD_NAME = "Enter a name such as tv.example.com."
_NAME = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
)


class Refused(ValueError):
    """What an Admin listed can't be kept (a sentence for them)."""


class Wide(Refused):
    """A network wider than one home network, kept only when the Admin says
    so (confirmWide)."""


def network_of(text: Any, loopback: bool = False) -> networks.Network:
    """A network as an Admin wrote it: an address (one device) or a network
    in CIDR form, at home. Refused otherwise. `loopback`: this machine's own
    addresses may be listed (a trusted proxy on the same machine, with host
    networking; never a trusted network)."""
    if not isinstance(text, str):
        raise Refused(NOT_AN_ADDRESS)
    text = text.strip()
    if (
        not text
        or len(text) > NETWORK_TEXT_MOST
        or "%" in text
        or not re.fullmatch(r"[0-9a-fA-F:./]+", text)
        or (":" in text and "." in text)  # (IPv4 in IPv6 forms)
    ):
        raise Refused(NOT_AN_ADDRESS)
    try:
        net = ipaddress.ip_network(text, strict=False)
    except ValueError:
        raise Refused(NOT_AN_ADDRESS) from None
    home = [h for h in networks.HOME_NETWORKS if h.version == net.version]
    if (net.network_address.is_loopback and not loopback) or not any(
        net.subnet_of(h)
        for h in home  # type: ignore[arg-type]
    ):
        raise Refused(INTERNET)
    return net


def _wide(net: networks.Network) -> str | None:
    """The question for a network wider than one home network."""
    if net.prefixlen >= WIDEST[net.version]:
        return None
    return (
        f"{net} is {net.num_addresses:,} addresses. That's wider than one home network, and "
        "often takes in guest networks too. Trust it anyway?"
    )


def _label(text: Any) -> str:
    return plain(str(text or ""))[:LABEL_MOST]


class Trusted:
    """What's trusted, as an Admin listed it. `roles`: each person's role,
    by id (for "Signed in as", and reconcile)."""

    def __init__(self, db: Database, roles: Callable[[], dict[int, str]]) -> None:
        self.db = db
        self.roles = roles
        self._kept: dict[str, Any] = {}
        self._nets: list[tuple[networks.Network, dict[str, Any]]] = []
        self._proxies: list[networks.Network] = []
        self._load()

    # Reading -----------------------------------------------------------------

    def _load(self) -> None:
        raw = self.db.get_meta(META, "")
        kept: dict[str, Any] = {}
        if raw:
            try:
                kept = json.loads(raw)
                if not isinstance(kept, dict):
                    raise ValueError("not an object")
                nets = [(network_of(e["network"]), e) for e in kept.get("entries", [])]
                proxies = [network_of(p["network"], True) for p in kept.get("proxies", [])]
            except (ValueError, KeyError, TypeError) as e:
                # (What can't be read trusts nothing.)
                log.warning("Trusted networks couldn't be read, so nothing is trusted (%s)", e)
                kept, nets, proxies = {}, [], []
        else:
            nets, proxies = [], []
        self._kept = kept
        # (Longest prefix first: the most particular entry wins.)
        self._nets = sorted(nets, key=lambda ne: -ne[0].prefixlen)
        self._proxies = proxies
        # The entries that sign in an Admin (never through a proxy: see
        # entry_for). If who's an Admin can't be read, every "Signed in as".
        people = [e for _, e in nets if e.get("gives") == "person"]
        try:
            roles = self.roles()
        except Exception:
            log.warning("Couldn't read who's an Admin for trusted networks", exc_info=True)
            roles = None
        self._admins = {
            e["id"] for e in people if roles is None or roles.get(e.get("person")) == "admin"
        }

    @property
    def entries(self) -> list[dict[str, Any]]:
        return [dict(e) for e in self._kept.get("entries", [])] if self._nets else []

    @property
    def proxies(self) -> list[dict[str, Any]]:
        return [dict(p) for p in self._kept.get("proxies", [])] if self._proxies else []

    @property
    def home_names(self) -> list[str]:
        return list(self._kept.get("homeNames", []))

    def proxy_networks(self) -> list[networks.Network]:
        return list(self._proxies)

    def is_proxy(self, ip: networks.IP | None) -> bool:
        return ip is not None and any(ip.version == n.version and ip in n for n in self._proxies)

    def entry_for(
        self, ip: networks.IP | None, through_proxy: bool = False
    ) -> dict[str, Any] | None:
        """The trusted network an address is on (the longest prefix), if any.
        Through a proxy, never one that signs in an Admin (a proxy's headers
        say who only as far as it's set up right): the next one, if any."""
        if ip is None:
            return None
        for net, entry in self._nets:
            if through_proxy and entry["id"] in self._admins:
                continue
            if ip.version == net.version and ip in net:
                return dict(entry)
        return None

    # Changing --------------------------------------------------------------

    def save(self, given: dict[str, Any], by: int | None) -> None:
        """Replaces what's listed (entries, proxies, home names: each only if
        given) with `given`, checked as a whole. Refused or Wide, keeping
        what was there, if any of it can't be kept."""
        roles = self.roles()
        now = int(time.time() * 1000)
        confirm = given.get("confirmWide") is True
        old = {e["network"]: e for e in self._kept.get("entries", [])}
        kept = dict(self._kept)
        if "entries" in given:
            entries = given["entries"] or []
            if not isinstance(entries, list) or len(entries) > ENTRIES_MOST:
                raise Refused(f"List {ENTRIES_MOST} networks at most.")
            out: list[dict[str, Any]] = []
            seen: set[str] = set()
            for e in entries:
                if not isinstance(e, dict):
                    raise Refused(NOT_AN_ADDRESS)
                net = network_of(e.get("network"))
                if str(net) in seen:
                    raise Refused(f"{net} is already on the list.")
                seen.add(str(net))
                gives = e.get("gives", "picker")
                if gives not in GIVES:
                    raise Refused("Choose Who's tuning in? or Signed in as.")
                person = e.get("person") if gives == "person" else None
                if gives == "person":
                    if not isinstance(person, int) or person not in roles:
                        raise Refused(NO_SUCH_PERSON)
                    if roles[person] == "admin" and net.num_addresses != 1:
                        raise Refused(ADMIN_ONE_DEVICE)
                # (Asked once: one already listed was confirmed then.)
                if (question := _wide(net)) and not confirm and str(net) not in old:
                    raise Wide(question)
                was = old.get(str(net), {})
                out.append({
                    "id": was.get("id") or "tn" + secrets.token_hex(4),
                    "network": str(net), "label": _label(e.get("label")), "gives": gives,
                    "person": person, "addedMs": was.get("addedMs") or now,
                    "addedBy": was.get("addedBy") or by,
                    # (Their role as listed: made an Admin later, it's Who's
                    # tuning in? until an Admin chooses them again. reconcile.)
                    "role": roles[person] if person is not None else None,
                })  # fmt: skip
            kept["entries"] = out
        if "proxies" in given:
            proxies = given["proxies"] or []
            if not isinstance(proxies, list) or len(proxies) > PROXIES_MOST:
                raise Refused(f"List {PROXIES_MOST} trusted proxies at most.")
            listed: list[dict[str, Any]] = []
            for p in proxies:
                if not isinstance(p, dict):
                    raise Refused(NOT_AN_ADDRESS)
                net = network_of(p.get("network"), loopback=True)
                if any(q["network"] == str(net) for q in listed):
                    raise Refused(f"{net} is already on the list.")
                was_listed = any(q["network"] == str(net) for q in self._kept.get("proxies", []))
                if net.num_addresses > 1 and not confirm and not was_listed:
                    # (One address, as a proxy has: more asks first. The cold
                    # audit of 1.36.0.)
                    raise Wide(
                        f"{net} is {net.num_addresses:,} addresses. Every device there could say "
                        "who a visitor is. List only your proxy's own address, unless it moves "
                        "around. List it anyway?"
                    )
                if (question := _wide(net)) and not confirm and not was_listed:
                    raise Wide(question)
                listed.append({"network": str(net), "label": _label(p.get("label"))})
            kept["proxies"] = listed
        if "homeNames" in given:
            names = given["homeNames"] or []
            if not isinstance(names, list) or len(names) > HOME_NAMES_MOST:
                raise Refused(f"List {HOME_NAMES_MOST} names at most.")
            out_names: list[str] = []
            for n in names:
                name = str(n or "").strip().lower().rstrip(".")
                if (
                    len(name) > 253
                    or networks.parse_ip(name) is not None
                    or not _NAME.fullmatch(name)
                ):
                    raise Refused(BAD_NAME)
                if name not in out_names:
                    out_names.append(name)
            kept["homeNames"] = out_names
        kept["v"] = 1
        self.db.set_meta(META, json.dumps(kept))
        self._load()

    def reconcile(self, roles: dict[int, str] | None = None) -> list[dict[str, Any]]:
        """Never a dangling trust: an entry whose person is gone goes, and
        one that signs in someone made an Admin (since it was listed, or
        wider than one device) becomes Who's tuning in?. The entries that went, or changed (as they
        were), whose sign-ins and devices end (see trustedapi.py)."""
        roles = self.roles() if roles is None else roles
        changed: list[dict[str, Any]] = []
        out: list[dict[str, Any]] = []
        for e in self._kept.get("entries", []):
            if e.get("gives") == "person":
                person = e.get("person")
                if person not in roles:
                    changed.append(dict(e))
                    continue
                net = ipaddress.ip_network(e["network"])
                made_admin = roles[person] == "admin" and e.get("role") != "admin"
                if roles[person] == "admin" and (net.num_addresses != 1 or made_admin):
                    changed.append(dict(e))
                    e = {**e, "gives": "picker", "person": None, "role": None}
            out.append(e)
        if changed:
            self.db.set_meta(META, json.dumps({**self._kept, "entries": out, "v": 1}))
        self._load()  # (and who's an Admin now)
        return changed
