"""Where a request comes from (1.36.0): home addresses, forwarding headers,
the Host a request asks for, and the verdict the Gate starts from.

The rule (the owner, October 13: "we are also focusing on how security
works if we accidentally leave doors open"): when tapiOca can't be sure
where a request comes from, it's from the internet. Until 1.36.0, the port
alone said so: anything reaching the home port was home, a router's port
forward or a reverse proxy pointed at it included. Now the home port is
home only for a home address, asking for a home name, with no sign in what
came through a proxy that it's the internet:

- the public port: the internet;
- a peer that isn't an address (nothing tapiOca can judge): the internet;
- a peer outside the home ranges (door 1: the home port forwarded to the
  internet), or a Host that's an internet address (door 1b): the internet;
- forwarding headers naming an internet address, or anything that can't
  be read (door 2: a proxy pointed at the home port): the internet;
- otherwise at home. An internet name in the Host with no forwarding
  headers is noted (door 3: a tunnel, or a name the home's own DNS gives),
  never refused by itself.

Headers can only take away: nothing here, nor in what trusts a network
(see trust), ever grants more because of what a request says of itself.

No I/O here: everything is decided from the request and what's handed in.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

IP = ipaddress.IPv4Address | ipaddress.IPv6Address
Network = ipaddress.IPv4Network | ipaddress.IPv6Network

# Home: private, loopback, link-local, CGNAT (Tailscale's addresses, and
# other VPNs'), unique-local IPv6. An explicit list, never is_private,
# which differs between Python 3.11 and 3.13 (Teredo, 2001::/32, is private
# in one and not the other).
HOME_NETWORKS: tuple[Network, ...] = tuple(
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16",
        "100.64.0.0/10", "::1/128", "fc00::/7", "fe80::/10",
    )
)  # fmt: skip

# The headers that say whom a proxy passed a request on for.
ADDRESS_HEADERS = (
    b"x-forwarded-for", b"x-real-ip", b"forwarded", b"cf-connecting-ip", b"true-client-ip",
)  # fmt: skip
# Past this many addresses, or bytes across those headers, what's there
# can't be told.
FORWARDED_MOST = 64
FORWARDED_BYTES = 4096

# Names that are only ever home's own (the README's Tailscale names too).
HOME_SUFFIXES = (
    ".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain", ".ts.net",
)  # fmt: skip
_NAME = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*"
)


def parse_ip(text: str | None) -> IP | None:
    """An address as written, if that's all it is: no zone, brackets or
    port. An IPv4 address in IPv6 form is itself."""
    if text is None:
        return None
    text = text.strip()
    if not text or len(text) > 45 or "%" in text or "[" in text or "]" in text:
        return None
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


def parse_peer(text: str | None) -> IP | None:
    """The address a connection came from, as the socket gives it: a
    link-local IPv6 peer comes with its network's name (fe80::1%eth0),
    which the socket says, so it's taken off for a link-local address
    only."""
    if text and "%" in text:
        ip = parse_ip(text.split("%", 1)[0])
        return ip if isinstance(ip, ipaddress.IPv6Address) and ip.is_link_local else None
    return parse_ip(text)


def is_home(ip: IP) -> bool:
    return any(ip.version == n.version and ip in n for n in HOME_NETWORKS)


def _forwarded_for(value: str) -> list[str | None]:
    """RFC 7239: each element's for= value, as written (None: an element
    without one)."""
    out: list[str | None] = []
    element: dict[str, str] = {}
    name, text, quoted, escaped, in_value = "", "", False, False, False

    def end_pair() -> None:
        nonlocal name, text, in_value
        if name:
            element[name.strip().lower()] = text if in_value else ""
        name, text, in_value = "", "", False

    for ch in value:
        if quoted:
            if escaped:
                text += ch
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
            else:
                text += ch
        elif ch == '"' and in_value:
            quoted = True
        elif ch == "=" and not in_value:
            in_value = True
        elif ch == ";":
            end_pair()
        elif ch == ",":
            end_pair()
            out.append(element.get("for"))
            element = {}
        elif in_value:
            if not ch.isspace():
                text += ch
        else:
            name += ch
    end_pair()
    out.append(element.get("for"))
    return out


def _forwarded_address(text: str | None) -> IP | None:
    """A for= value's address: a.b.c.d, a.b.c.d:port, [v6] or [v6]:port.
    None for unknown, _obfuscated and anything else."""
    if not text:
        return None
    if text.startswith("["):
        end = text.find("]")
        if end < 0 or (end + 1 < len(text) and not re.fullmatch(r":\d{1,5}", text[end + 1 :])):
            return None
        return parse_ip(text[1:end])
    if re.fullmatch(r"[0-9.]+:\d{1,5}", text):
        text = text.rsplit(":", 1)[0]
    return parse_ip(text)


def forwarded(headers: Iterable[tuple[bytes, bytes]]) -> list[IP | None] | None:
    """Every address the forwarding headers name, in order, None for each
    that can't be read; None if there are no such headers at all. Too many,
    or too long, is a single None: it can't be told."""
    found: list[IP | None] = []
    size = 0
    any_header = False
    for name, raw in headers:
        if name not in ADDRESS_HEADERS:
            continue
        any_header = True
        size += len(raw)
        if size > FORWARDED_BYTES:
            return [None]
        value = raw.decode("latin-1")
        if name == b"forwarded":
            found += [_forwarded_address(f) for f in _forwarded_for(value)]
        elif name == b"x-forwarded-for":
            found += [parse_ip(item) for item in value.split(",")]
        else:
            found.append(parse_ip(value))
        if len(found) > FORWARDED_MOST:
            return [None]
    return found if any_header else None


def _host_name(host: str) -> str:
    """The Host, lowercased, without its port or a trailing dot."""
    host = host.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end > 0 else host
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def host_kind(
    host: str | None,
    home_names: Collection[str] = (),
    also_home: Collection[str] = (),
    never_home: Collection[str] = (),
) -> str:
    """What the Host a request asks for is: "home" (an address at home, a
    single label, a home-only name, BASE_URL's host or a name an Admin says
    is home's), "public-ip", "public-name" or "none" (missing or not a
    host). `never_home`: the Away from home address's host, never home."""
    if not host:
        return "none"
    name = _host_name(host)
    literal = parse_ip(name[1:-1] if name.startswith("[") and name.endswith("]") else name)
    if literal is not None:
        return "home" if is_home(literal) else "public-ip"
    if not name or not _NAME.fullmatch(name):
        return "none"
    if name in {n.rstrip(".").lower() for n in never_home}:
        return "public-name"
    if (
        name == "localhost"
        or "." not in name
        or name.endswith(HOME_SUFFIXES)
        or name in {n.rstrip(".").lower() for n in (*home_names, *also_home)}
    ):
        return "home"
    return "public-name"


@dataclass
class Verdict:
    """Where a request is from, as the Gate starts from it.

    `outside`: it's treated as from the internet (only what the public port
    gives); `why`: "public-port", "unknown", "home-port" (doors 1 and 1b) or
    "proxy" (door 2), "" at home; `visitor`: who it's for (a trusted
    proxy's visitor, Cloudflare's on the public port, otherwise the peer);
    `via_proxy`: it came through a trusted proxy; `untrusted_headers`:
    forwarding headers from a device that isn't a trusted proxy (never
    believed, and never trusted); `door3`: an internet name on the home port
    with no forwarding headers (noted, never refused by itself)."""

    outside: bool
    why: str = ""
    peer: IP | None = None
    forwarded: list[IP | None] = field(default_factory=list)
    host: str = "none"
    visitor: IP | None = None
    via_proxy: bool = False
    untrusted_headers: bool = False
    door3: bool = False
    # (1.36.2) A trusted proxy that isn't a relay, naming no one at all, not
    # asked for by an internet name: the proxy's own computer, perhaps (Plex
    # there). Still a proxy's, for the internet, but the Gate lets Plex's
    # tuner, guide and logos be asked for this way; never trusted.
    proxy_device: bool = False


def _in(ip: IP | None, networks: Collection[Network]) -> bool:
    return ip is not None and any(ip.version == n.version and ip in n for n in networks)


def proxied_visitor(
    headers: Iterable[tuple[bytes, bytes]], cloudflare: Collection[Network] = ()
) -> IP | None:
    """Who a trusted proxy says a request is for: the last address in each
    of X-Real-IP, X-Forwarded-For and Forwarded it sends (the one the proxy
    itself added: those before it can be anything a visitor sent), which
    must all agree. Proxies differ in what they set, and pass the rest
    through from the visitor (Caddy, a visitor's own X-Real-IP; a proxy set
    to send only X-Real-IP, a visitor's own X-Forwarded-For), so one that
    disagrees means it can't be told: None. CF-Connecting-IP when what's
    found is one of Cloudflare's own addresses (Cloudflare in front of the
    proxy), or there's nothing else (a Cloudflare Tunnel straight to
    tapiOca). None if it names nobody."""
    real: list[IP | None] = []
    chain: list[IP | None] = []
    given: list[IP | None] = []
    connecting: list[bytes] = []
    for name, raw in headers:
        if name == b"x-real-ip":
            real.append(parse_ip(raw.decode("latin-1")))
        elif name == b"x-forwarded-for":
            chain += [parse_ip(item) for item in raw.decode("latin-1").split(",")]
        elif name == b"forwarded":
            given += [_forwarded_address(f) for f in _forwarded_for(raw.decode("latin-1"))]
        elif name == b"cf-connecting-ip":
            connecting.append(raw)
    cf = parse_ip(connecting[-1].decode("latin-1")) if connecting else None
    named = [kind[-1] for kind in (real, chain, given) if kind]
    if not named:
        return cf
    found = named[0]
    if found is None or any(other != found for other in named[1:]):
        return None
    if connecting and _in(found, cloudflare):
        return cf
    return found


def judge(
    *,
    public_port: bool,
    peer: str | None,
    host: str | None,
    headers: Iterable[tuple[bytes, bytes]],
    proxies: Collection[Network] = (),
    cloudflare: Collection[Network] = (),
    home_names: Collection[str] = (),
    also_home: Collection[str] = (),
    never_home: Collection[str] = (),
    relays: Collection[IP] = (),
) -> Verdict:
    """Where a request is from (see the module's notes). `proxies`: the
    trusted proxies an Admin listed, the only devices whose forwarding
    headers say who a request is for (the owner, October 13: never assumed
    from the headers themselves); `cloudflare`: Cloudflare's own addresses,
    whose CF-Connecting-IP is believed on the public port; `relays`: this
    machine's relays (see relays.py)."""
    headers = list(headers)
    peer_ip = parse_peer(peer)
    said = forwarded(headers)
    kind = host_kind(host, home_names, also_home, never_home)
    through = said or []
    # (Loopback with no forwarding headers at all is this machine itself,
    # such as the image's health check, even when a tunnel in tapiOca's own
    # container is listed as 127.0.0.1: that tunnel always names who. So is
    # a relay, Docker's gateway, listed for a reverse proxy in another
    # container on this server: Plex, Jellyfin and tapiOca's apps reach
    # tapiOca through it too, and name nobody. 1.36.1: listed, it took the
    # tuner from Plex, the cold audit's first finding.)
    proto = any(k in (b"x-forwarded-proto", b"cf-visitor") for k, _ in headers)
    itself = (
        said is None
        and not proto
        and peer_ip is not None
        and (peer_ip.is_loopback or peer_ip in relays)
    )
    listed = _in(peer_ip, proxies) and not itself
    proxy_device = listed and said is None and not proto and kind != "public-name"
    untrusted = said is not None and not listed
    visitor: IP | None = peer_ip
    if listed and said is not None:
        visitor = None if None in through else proxied_visitor(headers, cloudflare)
    elif public_port and _in(peer_ip, cloudflare):
        cf = [v for k, v in headers if k == b"cf-connecting-ip"]
        if cf:
            visitor = parse_ip(cf[-1].decode("latin-1"))
            untrusted = False

    def verdict(outside: bool, why: str = "", door3: bool = False) -> Verdict:
        return Verdict(
            outside, why, peer_ip, through, kind, visitor, listed, untrusted, door3, proxy_device
        )

    if public_port:
        # (A trusted proxy naming nobody, or not clearly: who it's for can't
        # be told, visitor None. See access.address.)
        return verdict(True, "public-port")
    if peer_ip is None:
        return verdict(True, "unknown")
    if not is_home(peer_ip) or kind == "public-ip":
        return verdict(True, "home-port")
    if listed:
        # (A trusted proxy is a proxy even with no headers: who it's for
        # must be named, and at home.)
        if said is None or visitor is None or not is_home(visitor):
            return verdict(True, "proxy")
        return verdict(False)
    if any(a is None or not is_home(a) for a in through):
        return verdict(True, "proxy")  # (the tripwire: headers only take away)
    return verdict(False, door3=said is None and kind == "public-name")
