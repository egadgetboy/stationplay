#!/usr/bin/env python3
"""Attack test for tapiOca's server, to run before a release.

It starts tapiOca on two free ports of its own (a home-network port and
a public one, as a reverse proxy reaches), against the stand-in Plex the
tests use, with an Admin, a User, a Kid on a limited Viewing Level, a
station, a shared library, an app signed in and a linked device. Then, from
the public port as an outsider (no sign-in), as a User, and as a Kid, it
tries what an attacker would and prints PASS or FAIL for each: routes
without and with the wrong role; forged headers; CSRF from another site;
path traversal; oversized bodies; script in names; guessing or reusing keys,
play addresses and reach nonces; reaching Media and stations a level hides;
the sign-in, PIN and link-code limits; who a linked device lists (new
people only on devices they sign in on, and Use for everyone: only for an
Admin, from tapiOca's own page, only its two choices, never moving who
can't sign in by name) and lists away from home; setting a PIN or
changing a password from the apps (as an
outsider, as someone else, an Admin's PIN, its format, the limits);
Admin alerts and the web address they're sent to (only for Admins; only
http and https, no redirects followed, never waited on); each person's
languages (their own only, and only languages tapiOca knows); Media's
addresses (every one refusing what a Kid's level hides, the same way, and
taking only what's bounded); a movie in several files played as one
(never what a level hides, its files never named, within its whole
length); people's reports (never from an outsider, always the sender's
own, within their level and the limits, the choices only the server's,
and only an Admin sees and acts on them); the Broken
files list as Media has it (trouble checked only from one's own playing,
and only for a problem just now; a broken file a level hides answered as
any hidden one; people's reports never crowded out of the checks' queue;
Retry and the tab's choices taking only what they should; Plex or Radarr
away said plainly, changing nothing); converted
copies on request (never of what a level hides, within the limit however
many ask at once); no file names in anything the apps receive; problems
sent later with their journals (only an Admin reads one, kept as text and
bounded, a backlog within the limits); the copies of the database
made before an update (never downloadable); Admin alerts kept across
restarts (whatever a sentence holds, kept and given back as it was; never
brought back by a backup, a forged one included; never stopped by a
database that can't be written; only so many fixed ones kept however many
come) and the corner mark's drift (only numbers, drawing whatever the
clock says); a file whose name and tags read like ffmpeg's own words
(where the deep scan finds damage stays where it is); and Media folders of
tapiOca's own (only an Admin adds one, only from inside the media folder;
browsing never leaves it; a video, poster or folder linked from outside it
is never read or served; the apps never get a file's name or a path); and
from 1.36.0, the doors left open (the home port forwarded, a proxy pointed
at it, headers from a device that isn't a trusted proxy, an internet name,
Docker hiding addresses: each treated as the internet, or not trusted, with
alerts that never give an address) and trusted networks (what can't be
listed, what's never trusted, a sign-in a network gives working only there,
the PIN limits, Tuner access by network). The public port's requests come
from a reverse proxy at home, listed as a trusted proxy (see AsPeer).

It's a tool, not part of CI (the test suite covers these as unit tests). Run
it from the repo root:  python -m tools.attack_check   (add -v to see every
check, not only failures).

It only ever talks to the tapiOca it starts here on localhost. It never
contacts any real server.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import random
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

# The stand-in Plex and library live beside the tests; make them importable
# whether this is run as a module or a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import uvicorn

from app import __version__, access, alerts, applibrary, backups, devices, problems, scanner
from app import ffmpeg as ff
from app.config import Settings
from app.db import Database, Item
from app.main import create_app
from app.plex import PlexClient
from tests.fakeplex_library import LibraryPlex

# What tapiOca's page sends with each request (see app/access.py, PAGE_HEADER).
PAGE = {"X-Tapioca-Page": "1"}

ADMIN = {"name": "Ada", "password": "correct horse battery"}
USER = {"name": "Sam", "password": "staple battery horse", "role": "user"}
KID = {"name": "Kit", "password": "battery horse staple", "role": "user"}
TV = {
    "containers": ["mp4", "mkv"],
    "video": [{"codec": "h264", "width": 1920, "height": 1080, "bitDepth": 8}],
    "hdr": [],
    "audio": ["aac", "ac3"],
}


class Checks:
    """Counts PASS/FAIL and prints them (failures always; all with -v)."""

    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.passed = 0
        self.failed = 0

    def ok(self, passed: bool, what: str, detail: str = "") -> bool:
        if passed:
            self.passed += 1
            if self.verbose:
                print(f"  PASS  {what}")
        else:
            self.failed += 1
            print(f"  FAIL  {what}{f' — {detail}' if detail else ''}")
        return passed

    def section(self, title: str) -> None:
        if self.verbose:
            print(f"\n{title}")


def build_plex(tmp: Path) -> LibraryPlex:
    """A small library: a kids' show, a grown-ups' show, a PG movie, an R
    movie; files on disk so Media can be played."""
    fp = LibraryPlex()
    fp.add_show("100", "Puppet Town", contentRating=["TV-Y7"])
    fp.add_episode("201", "100", 1, 1, "Puppets 1", "/tv/p/1.mkv", 22 * 60_000)
    fp.add_show("110", "Night Shift", contentRating=["TV-MA"])
    fp.add_episode("211", "110", 1, 1, "Shift 1", "/tv/n/1.mkv", 44 * 60_000)
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Picnic", "/m/picnic.mkv", 90 * 60_000, section="2", contentRating=["PG"])
    fp.add_movie("301", "Heist", "/m/heist.mkv", 100 * 60_000, section="2", contentRating=["R"])
    for key in ("201", "211", "300", "301"):
        fp.describe(key)
        fp.files[key] = b"a program" * 100
    # (Cartoons anyone may see, for the limits on people's reports, and for
    # playing; and one that nothing asks about, for when Plex is away.)
    for n in range(12):
        fp.add_movie(f"32{n:02d}", f"Cartoon {n + 1}", f"/m/c{n}.mkv", 7 * 60_000, section="2",
                     contentRating=["G"])  # fmt: skip
        fp.describe(f"32{n:02d}")
        fp.files[f"32{n:02d}"] = b"a cartoon" * 100
    fp.add_movie("390", "Static", "/m/static.mkv", 7 * 60_000, section="2", contentRating=["G"])
    fp.describe("390")
    # Movies in several files (from 1.31.0): one anyone may see, one only a
    # grown-up may, and one whose second file's address isn't a path on Plex.
    for key, title, rating in (("340", "Feast", "PG"), ("341", "Vault", "R"), ("342", "Odd", "G")):
        fp.add_movie(key, title, f"/m/{title.lower()}-cd1.mkv", 120 * 60_000, section="2",
                     contentRating=[rating])  # fmt: skip
        fp.more[key] = {"Media": [{"id": int(key) * 100, "container": "mkv", "videoCodec": "h264",
                                   "duration": 120 * 60_000, "Part": [
            {"key": f"/library/parts/{key}1/1/file.mkv", "file": f"/m/{title.lower()}-cd1.mkv",
             "duration": 70 * 60_000, "size": 1000},
            {"key": f"/library/parts/{key}2/1/file.mkv" if key != "342" else "@evil.test/x",
             "file": f"/m/{title.lower()}-cd2.mkv", "duration": 50 * 60_000, "size": 1000},
        ]}]}  # fmt: skip
        fp.files[f"{key}1"] = fp.files[f"{key}2"] = b"a part" * 100
    return fp


# (1.36.0) Where the public port's requests come from: a reverse proxy at
# home, listed as a trusted proxy (as the README says to), whose headers say
# who each visitor is. Only a listed proxy's headers are believed.
PROXY_PEER = "192.168.1.2"
GATEWAY, OWN = "172.17.0.1", "172.17.0.2"  # Docker's gateway, and tapiOca's own address


class AsPeer:
    """Harness only: requests to the public port come from PROXY_PEER, and
    any request's X-Attack-Peer header (taken off before tapiOca sees it)
    says the address it comes from, for the doors left open and trusted
    networks, which a test on one machine can't otherwise reach."""

    def __init__(self, app, public_port: int) -> None:
        self.app, self.public_port = app, public_port

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            headers = scope.get("headers") or []
            said = [v for k, v in headers if k == b"x-attack-peer"]
            client = scope.get("client") or ("127.0.0.1", 0)
            if said:
                client = (said[-1].decode("latin-1"), client[1])
            elif scope.get("server") and scope["server"][1] == self.public_port:
                client = (PROXY_PEER, client[1])
            scope = {**scope, "client": client,
                     "headers": [(k, v) for k, v in headers if k != b"x-attack-peer"]}  # fmt: skip
        await self.app(scope, receive, send)


async def run(checks: Checks) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="attack-check-"))
    fp = build_plex(tmp)
    scanner.STARTUP_DELAY_S = 10**6  # (no file checks: the stand-in files aren't on disk)
    lan_sock, public_sock = (socket.create_server(("127.0.0.1", 0)) for _ in range(2))
    lan_port, public_port = lan_sock.getsockname()[1], public_sock.getsockname()[1]
    settings = Settings(
        plex_url="http://plex.test",
        plex_token="token",
        data_dir=tmp / "data",
        port=lan_port,
        public_port=public_port,
        media_dir=str(build_folders(tmp)),
    )
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    app.state.ctx.play_transport = fp.transport()
    import ipaddress as _ip

    app.state.ctx.relays.found = lambda: {_ip.ip_address(GATEWAY), _ip.ip_address(OWN)}
    server = uvicorn.Server(
        uvicorn.Config(AsPeer(app, public_port), log_level="error", proxy_headers=False)
    )
    task = asyncio.create_task(server.serve(sockets=[lan_sock, public_sock]))
    try:
        while not server.started:  # noqa: ASYNC110
            await asyncio.sleep(0.02)
        home = f"http://127.0.0.1:{lan_port}"
        net = f"http://127.0.0.1:{public_port}"
        await _attacks(checks, app, home, net, fp)
    finally:
        server.should_exit = True
        await task
        shutil.rmtree(tmp, ignore_errors=True)


async def _page_code(c: httpx.AsyncClient) -> str:
    """The page as it's served, and each of its own styles and scripts."""
    files = [(await c.get(f"/web/{name}?v={__version__}")).text for name in access.PAGE_FILES]
    return "\n".join([(await c.get("/")).text, *files])


def _cf(address: str) -> dict[str, str]:
    """Headers as a Cloudflare Tunnel passes a visitor on, over HTTPS."""
    return {"CF-Connecting-IP": address, "CF-Visitor": '{"scheme":"https"}'}


async def _attacks(checks: Checks, app, home: str, net: str, fp: LibraryPlex) -> None:
    # Set everything up from the home network, where tapiOca starts open.
    # Admin, User and Kid are signed in as apps (bearer tokens), so the
    # brute-force tests later don't spend the home address's password budget
    # on the setup calls.
    admin_h = sam_h = kit_h = {}
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        await c.post("/api/access/users", json=ADMIN)
        # (The reverse proxy, as the README says: see PROXY_PEER.)
        app.state.ctx.trusted.save(
            {"proxies": [{"network": PROXY_PEER, "label": "Proxy"}]}, by=None
        )
        sam = (await c.post("/api/access/users", json=USER)).json()
        kit = (await c.post("/api/access/users", json=KID)).json()
        admin_h = {
            "Authorization": f"Bearer {(await c.post('/api/internal/sign-in', json=ADMIN)).json()['token']}"
        }
        sam_h = {
            "Authorization": f"Bearer {(await c.post('/api/internal/sign-in', json=USER)).json()['token']}"
        }
        kit_h = {
            "Authorization": f"Bearer {(await c.post('/api/internal/sign-in', json=KID)).json()['token']}"
        }
        tv_signed = (
            await c.post(
                "/api/internal/sign-in",
                json={**USER, "picker": True, "app": "Roku", "deviceName": "Den"},
            )
        ).json()
        device_key = tv_signed["deviceKey"]
        # Stations, a shared library, and the Kid's level — with the Admin
        # token (an app bearer carries no Sec-Fetch-Site, so it isn't a
        # cross-site change).
        await c.post(
            "/api/channels",
            json={
                "number": 3,
                "name": "Puppets",
                "sources": [{"type": "show", "ratingKey": "100"}],
            },
            headers=admin_h,
        )
        await c.post(
            "/api/channels",
            json={"number": 5, "name": "Late", "sources": [{"type": "show", "ratingKey": "110"}]},
            headers=admin_h,
        )
        await c.put("/api/app-libraries", json={"libraries": ["1", "2"]}, headers=admin_h)
        await app.state.ctx.titles.filled()
        levels = (await c.get("/api/access/viewing", headers=admin_h)).json()["levels"]
        kid_level = next(lv["id"] for lv in levels if lv["builtin"] == "kid")
        await c.put(f"/api/access/users/{kit['id']}/viewing", json={"level": kid_level},
                    headers=admin_h)  # fmt: skip
        # Give the User a PIN, for the PIN brute-force test later.
        await c.put(f"/api/access/users/{sam['id']}/picker", json={"pin": "4321"}, headers=admin_h)

    # 1) The public port: no Plex, no home-only addresses, sign-in required.
    checks.section("From the internet, with no sign-in")
    async with httpx.AsyncClient(headers=PAGE, base_url=net) as out:
        for path in (
            "/discover.json", "/lineup.json", "/lineup_status.json", "/xmltv.xml", "/guide.xml",
            "/stations.m3u", "/channels.m3u", "/stream/3", "/auto/v3", "/art/201",
            "/hls/3/index.m3u8",
        ):  # fmt: skip
            r = await out.get(path)
            checks.ok(r.status_code == 404, f"{path} is not served on the public port",
                      f"got {r.status_code}")  # fmt: skip
        # A play address there: only over HTTPS, and only one an app started there.
        r = await out.get("/play/anything/file.mkv")
        checks.ok(r.status_code == 403, "a play address over plain HTTP is refused",
                  f"got {r.status_code}")  # fmt: skip
        r = await out.get("/play/anything/file.mkv", headers={"X-Forwarded-Proto": "https"})
        checks.ok(r.status_code == 404, "a made-up play address gets nothing",
                  f"got {r.status_code}")  # fmt: skip
        for path in ("/api/channels", "/api/status", "/api/logs", "/logos/x.png", "/api/stats",
                     "/poster/201", "/plex-logo/201.png"):  # fmt: skip
            r = await out.get(path)
            checks.ok(r.status_code == 401, f"{path} needs a sign-in from the internet",
                      f"got {r.status_code}")  # fmt: skip
        # The page is open; the apps' API needs HTTPS from the internet.
        checks.ok((await out.get("/")).status_code == 200, "the sign-in page is shown")
        plain = await out.get("/api/v1/server")
        checks.ok(plain.status_code == 403, "the apps' API refuses plain HTTP from the internet",
                  f"got {plain.status_code}")  # fmt: skip
        greeting = (await out.get("/api/v1/server", headers={"X-Forwarded-Proto": "https"})).json()
        checks.ok(
            greeting.get("signIn") is True,
            "over HTTPS the API greeting says a token is needed from the internet",
            f"signIn={greeting.get('signIn')!r}",
        )

    # 2) Forged visitor headers can't pose as another address or beat limits.
    checks.section("Forged headers")
    async with httpx.AsyncClient(headers=PAGE, base_url=net) as out:
        # A reverse proxy (NPMplus) sets X-Real-IP; a visitor's own
        # X-Forwarded-For / CF-Connecting-IP behind it must not override it.
        forged = {
            "X-Real-IP": "203.0.113.9",
            "X-Forwarded-For": "10.0.0.1, 127.0.0.1",
            "CF-Connecting-IP": "8.8.8.8",
        }
        for _ in range(access.TRIES):
            await out.post("/api/access/sign-in", json={**USER, "password": "wrong one"},
                           headers=forged)  # fmt: skip
        blocked = await out.post("/api/access/sign-in", json=USER, headers=forged)
        checks.ok(
            blocked.status_code == 429,
            "wrong passwords are counted by the proxy's X-Real-IP, not a forged header",
            f"got {blocked.status_code}",
        )
        # A different forged X-Forwarded-For does not reset the count.
        still = await out.post("/api/access/sign-in", json=USER,
                               headers={**forged, "X-Forwarded-For": "198.51.100.7"})  # fmt: skip
        checks.ok(still.status_code == 429, "a changed X-Forwarded-For doesn't reset the limit",
                  f"got {still.status_code}")  # fmt: skip

    # 3) CSRF from another site is refused for anything that changes. (On the
    # home port, so the session cookie rides plain HTTP as a browser's would;
    # the origin check is the same on both ports.)
    checks.section("CSRF from another origin")
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as pat:
        signed = await pat.post("/api/access/sign-in", json=ADMIN)
        checks.ok(signed.status_code == 200, "the Admin can sign in on its own page",
                  f"got {signed.status_code}")  # fmt: skip
        cross = await pat.post(
            "/api/channels",
            json={"number": 9, "sources": [{"type": "show", "ratingKey": "100"}]},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        checks.ok(cross.status_code == 403, "a change from another site is refused",
                  f"got {cross.status_code}")  # fmt: skip
        same = await pat.post(
            "/api/channels",
            json={"number": 9, "sources": [{"type": "show", "ratingKey": "100"}]},
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        checks.ok(same.status_code in (201, 409), "the same change from its own page is allowed",
                  f"got {same.status_code}")  # fmt: skip

    # 4) A User (and a Kid) may do only what their role allows.
    checks.section("A User and a Kid may do only what their role allows")
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        for method, path in (
            ("GET", "/api/logs"), ("POST", "/api/backups"), ("GET", "/api/broken"),
            ("PUT", "/api/scan"), ("GET", "/api/access/users"), ("PUT", "/api/app-libraries"),
            ("DELETE", "/api/logos/upload-0123456789"), ("GET", "/api/arr"),
            ("GET", "/api/away"), ("PUT", "/api/api-tokens/outside"),
            ("PUT", f"/api/access/users/{kit['id']}"),  # (renaming someone, say)
            # (1.33.0: what's hidden by what titles are, and clip ratings.)
            ("GET", "/api/access/tags"), ("GET", "/api/access/clips"),
            ("PUT", "/api/access/clips"), ("GET", "/api/access/viewing"),
            ("PUT", f"/api/access/users/{kit['id']}/viewing"),
        ):  # fmt: skip
            r = await c.request(method, path, headers=sam_h)
            checks.ok(r.status_code == 403, f"a User can't {method} {path}", f"got {r.status_code}")
        # A Kid on a limited level can't make or change stations.
        made = await c.post(
            "/api/channels", json={"number": 11, "sources": [{"type": "show", "ratingKey": "100"}]},
            headers=kit_h,
        )  # fmt: skip
        checks.ok(made.status_code == 403, "a Kid on a limited level can't make a station",
                  f"got {made.status_code}")  # fmt: skip

    # 5) A Kid never sees what their Viewing Level hides, anywhere.
    checks.section("A Kid never sees what their level hides")
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        numbers = {
            s["number"] for s in (await c.get("/api/v1/stations", headers=kit_h)).json()["stations"]
        }
        checks.ok(
            5 not in numbers and 3 in numbers,
            "the grown-ups' station (5) is hidden from the Kid, the kids' one (3) shown",
            f"saw {sorted(numbers)}",
        )
        for key in ("110", "211", "301"):
            seen = await c.get(f"/api/internal/items/{key}", headers=kit_h)
            gone = await c.get("/api/internal/items/999999", headers=kit_h)
            checks.ok(
                seen.status_code == 404 and seen.json() == gone.json(),
                f"item {key} answers as missing for the Kid",
                f"got {seen.status_code}",
            )
            played = await c.post(
                "/api/internal/play", json={"key": key, "device": TV}, headers=kit_h
            )
            checks.ok(played.status_code == 404, f"the Kid can't play item {key}",
                      f"got {played.status_code}")  # fmt: skip
        # Its stream address answers as though the station doesn't exist.
        hidden = await c.get("/api/internal/items/300", headers=kit_h)
        checks.ok(hidden.status_code == 200, "the PG movie is allowed for the Kid")

    # 6) Path traversal in file and key parameters.
    checks.section("Path traversal")
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        for path in (
            "/logos/..%2f..%2fetc%2fpasswd", "/logos/%2e%2e/secret.png",
            "/bumpers/..%2f..%2fstationplay.db.mp4", "/api/backups/..%2f..%2fstationplay.db",
            "/api/libraries/..%2f..%2faccounts/items",
        ):  # fmt: skip
            r = await c.get(path, headers=sam_h)
            checks.ok(
                r.status_code in (400, 403, 404) and b"root:" not in r.content,
                f"path traversal via {path} gets nothing",
                f"got {r.status_code}",
            )
        # A station source can only be a Plex key, never a crafted path.
        bad = await c.post(
            "/api/channels",
            json={"number": 13, "sources": [{"type": "show", "ratingKey": "../../accounts"}]},
            headers=sam_h,
        )
        checks.ok(bad.status_code == 400, "a station source must be a plain Plex key",
                  f"got {bad.status_code}")  # fmt: skip

    # 6b) 1.34.0: the page's files open before sign-in, the update check,
    # the extra alert addresses, and where people signed in from (the
    # 1.34.0 re-audit: the attack check hadn't grown with them).
    checks.section("1.34.0: page files, the update check, alert addresses")
    async with (
        httpx.AsyncClient(headers=PAGE, base_url=home) as anon,
        httpx.AsyncClient(headers=PAGE, base_url=net) as out,
    ):
        for client, where_ in ((anon, "at home"), (out, "from the internet")):
            for path in ("/favicon.svg", "/favicon.ico",
                         "/fonts/SpaceGrotesk/SpaceGrotesk-Regular.woff2"):  # fmt: skip
                r = await client.get(path)
                checks.ok(r.status_code == 200, f"{path} opens signed out {where_}",
                          f"got {r.status_code}")  # fmt: skip
            for path in (
                "/fonts/..%2f..%2fstationplay.db", "/fonts/%2e%2e/%2e%2e/etc/passwd",
                "/fonts/SpaceGrotesk/OFL.txt", "/fonts/SpaceGrotesk/..%2f..%2findex.html",
                "/fonts/SpaceGrotesk%2f..%2f..%2f..%2fapp%2faccess.py", "/favicon.svg%2f..%2fstationplay.db",
            ):  # fmt: skip
                r = await client.get(path)
                checks.ok(
                    r.status_code in (400, 401, 403, 404) and b"root:" not in r.content
                    and b"SQLite" not in r.content and b"import" not in r.content,
                    f"{path} gets nothing {where_}", f"got {r.status_code}",
                )  # fmt: skip
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        for method, path, body in (
            ("GET", "/api/updates", None), ("PUT", "/api/updates", {"on": False}),
            ("POST", "/api/updates/check", None), ("GET", "/api/notify", None),
            ("PUT", "/api/notify", {"on": True, "url": "https://evil.test/hook",
                                    "more": [{"url": "https://evil.test/2"}]}),
            ("POST", "/api/notify/test", {"on": True, "url": "https://evil.test/hook", "which": 1}),
            # (1.34.1) The Plex step's checks, INFO, and the level new people start on.
            ("GET", "/api/setup/plex", None), ("GET", "/api/info-station", None),
            ("POST", "/api/info-station", None), ("PUT", "/api/access/new-level", {"level": 1}),
            # (1.36.3) Where you watch: the Tuner step's question, an Admin's.
            ("GET", "/api/setup/watch-in", None), ("PUT", "/api/setup/watch-in", {"watchIn": ["kodi"]}),
            # (1.36.1) Trust this proxy: an Admin's.
            ("POST", "/api/away/trust-proxy", {"address": "192.168.1.3"}),
        ):  # fmt: skip
            r = await c.request(method, path, json=body, headers=sam_h)
            checks.ok(r.status_code == 403, f"a User can't {method} {path}", f"got {r.status_code}")
        # (1.34.1) 99 is INFO's: no one takes it with a station of their own, or
        # gives another station INFO's film.
        for body in ({"number": 99, "name": "Mine", "sources": [{"type": "show", "ratingKey": "100"}]},
                     {"number": 77, "name": "Copy", "sources": [{"type": "info"}]}):  # fmt: skip
            r = await c.post("/api/channels", json=body, headers=admin_h)
            checks.ok(r.status_code in (400, 409), f"station {body['number']} can't be {body['name']}",
                      f"got {r.status_code}")  # fmt: skip
        # (Never true here: an Admin's yes would have tapiOca ask GitHub.)
        for said in ("true", 1, "yes", None):
            r = await c.put("/api/updates", json={"on": said}, headers=admin_h)
            checks.ok(r.status_code in (400, 422), f"the update check takes only true or false, not {said!r}",
                      f"got {r.status_code}")  # fmt: skip
        listed = (await c.get("/api/access/users", headers=admin_h)).json()
        people = listed.get("users", listed) if isinstance(listed, dict) else listed
        checks.ok(all("<" not in (p.get("signedInFrom") or "") for p in people),
                  "where people signed in from is never markup")  # fmt: skip
        forged = await c.post("/api/access/sign-in", json=USER,
                              headers={"X-Forwarded-For": "<img src=x onerror=alert(1)>, 1.2.3.4"})  # fmt: skip
        listed = (await c.get("/api/access/users", headers=admin_h)).json()
        people = listed.get("users", listed) if isinstance(listed, dict) else listed
        sam_from = next(
            (p.get("signedInFrom", "") for p in people if p.get("name") == USER["name"]), ""
        )
        checks.ok(forged.status_code == 200 and "<" not in sam_from and "img" not in sam_from,
                  "a forged X-Forwarded-For isn't kept as where someone signed in", sam_from)  # fmt: skip
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as pat:
        await pat.post("/api/access/sign-in", json=ADMIN)
        for method, path, body in (("PUT", "/api/updates", {"on": False}),
                                   ("PUT", "/api/notify", {"on": False}),
                                   ("POST", "/api/info-station", None),
                                   ("PUT", "/api/access/new-level", {"level": 1})):  # fmt: skip
            cross = await pat.request(
                method, path, json=body, headers={"Sec-Fetch-Site": "cross-site"}
            )
            checks.ok(cross.status_code == 403, f"{method} {path} from another site is refused",
                      f"got {cross.status_code}")  # fmt: skip

    # 7) Oversized and malformed bodies.
    checks.section("Oversized and malformed bodies")
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        huge = {"number": 14, "sources": [{"type": "show", "ratingKey": "100"}],
                "name": "x" * (access.BODY_MAX + 10)}  # fmt: skip
        r = await c.post("/api/channels", json=huge, headers=sam_h)
        checks.ok(r.status_code == 413, "an oversized body is refused", f"got {r.status_code}")
        bad = await c.post("/api/channels", content=b"not json{", headers={
            **sam_h, "Content-Type": "application/json"})  # fmt: skip
        checks.ok(bad.status_code in (400, 422), "malformed JSON is refused",
                  f"got {bad.status_code}")  # fmt: skip

    # 8) Script in a station name is stored plain and shown as text.
    checks.section("Script in names")
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        made = await c.post(
            "/api/channels",
            json={"number": 15, "name": "<img src=x onerror=alert(1)>\u0000\n",
                  "sources": [{"type": "show", "ratingKey": "100"}]},
            headers=sam_h,
        )  # fmt: skip
        if checks.ok(made.status_code == 201, "a station with script in its name is made",
                     made.text[:120]):  # fmt: skip
            name = made.json()["name"]
            checks.ok("\x00" not in name and "\n" not in name,
                      "control characters are stripped from the name")  # fmt: skip
            # The page builds the DOM with text nodes, never innerHTML with data.
            page = await _page_code(c)
            checks.ok("<img src=x onerror" not in page, "the name is not written into the page")

    # 9) Guessing or reusing keys, play addresses and reach nonces.
    checks.section("Guessing keys, play addresses and reach nonces")
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        for guess in ("/hls/k/guessme/3/index.m3u8", "/play/guessme/file.mkv",
                      "/play/guessme/index.m3u8"):  # fmt: skip
            r = await c.get(guess)
            checks.ok(r.status_code == 404, f"a guessed address {guess} gets nothing",
                      f"got {r.status_code}")  # fmt: skip
        # The reach nonce must match the value the check is waiting for.
        r = await c.get("/api/internal/reach?n=not-the-nonce")
        checks.ok(r.status_code == 404, "a wrong reach nonce is answered as not found",
                  f"got {r.status_code}")  # fmt: skip

    # 10) Brute-forcing the sign-in and the device PIN.
    checks.section("The sign-in and PIN limits")
    # From the internet, behind a proxy that sets X-Real-IP (so the limit is
    # by that address). A dedicated address, so this doesn't spend any other.
    guesser = {"X-Real-IP": "203.0.113.40", "X-Forwarded-Proto": "https"}
    async with httpx.AsyncClient(headers=PAGE, base_url=net) as c:
        for _ in range(access.TRIES):
            await c.post("/api/access/sign-in", json={**USER, "password": "nope nope"},
                         headers=guesser)  # fmt: skip
        blocked = await c.post("/api/access/sign-in", json={**USER, "password": "nope nope"},
                               headers=guesser)  # fmt: skip
        checks.ok(blocked.status_code == 429, "sign-in waits after too many wrong passwords",
                  f"got {blocked.status_code}")  # fmt: skip
    # Many PIN guesses at once can't beat the five-tries limit (the limit is
    # by person, so it isn't spent by anything above).
    await _pin_limit(checks, app, home, device_key)

    # 11) While watching away from home is off, the library is not reached on
    # the public port, even by a signed-in app over HTTPS.
    checks.section("Media stays on the home network while away from home is off")
    https = {**admin_h, "X-Forwarded-Proto": "https", "X-Real-IP": "203.0.113.50"}
    async with httpx.AsyncClient(headers=PAGE, base_url=net) as out:
        for path in ("/api/internal/libraries", "/api/internal/home", "/api/internal/items/300"):
            r = await out.get(path, headers=https)
            checks.ok(r.status_code in (403, 404), f"{path} is home-only from the internet",
                      f"got {r.status_code}")  # fmt: skip
        played = await out.post("/api/internal/play", json={"key": "300", "device": TV},
                                headers=https)  # fmt: skip
        checks.ok(played.status_code == 403, "nothing plays through the public port",
                  f"got {played.status_code}")  # fmt: skip

    # 12) With it on, Media through the public port: only for those signed in,
    # within their level, at addresses only the app that started them has.
    await _media_away(checks, app, home, net, admin_h, sam_h, kit_h)

    # 13) Who's tuning in?: new people only on devices they sign in on, and
    # Use for everyone (which then makes everyone a household's, for the rest);
    # away from home, a device lists only its own people.
    await _new_people_and_everyone(checks, app, home, net, admin_h, sam_h, kit_h, device_key)
    await _picker_away(checks, app, home, net, device_key)

    # 14) PINs and passwords from the apps: only one's own, as the rules say.
    await _own_pin_and_password(checks, app, home, net, admin_h, sam_h, kit_h, device_key)

    # 15) Admin alerts, and the web address they're sent to: only for Admins.
    await _alerts_and_notify(checks, app, home, net, admin_h, sam_h, kit_h)

    # 16) Each person's languages: only their own, and only known ones.
    await _languages(checks, app, home, net, admin_h, sam_h, kit_h)

    # 17) Media: every address refuses what a level hides, the same way, and
    # takes only what's bounded.
    await _library(checks, app, home, admin_h, kit_h)

    # 18) People's reports: only from someone signed in, as themselves, within
    # their level and the limits; and only an Admin sees and acts on them.
    # The Broken files list, as Media has it: trouble only from one's own
    # playing, what's broken refused as what a level hides is, people's
    # reports never crowded out, and a confused Admin or a failing network
    # answered plainly.
    await _reports(checks, app, home, net, admin_h, sam_h, kit_h)
    await _broken_files(checks, app, fp, home, admin_h, sam_h, kit_h)

    # 19) From 1.29.1: converted copies on request, no file names in the apps,
    # problems sent later with their journals, and the copies made before an
    # update.
    await _converted_on_request(checks, app, home, admin_h, kit_h)
    await _no_file_names(checks, home, admin_h)
    # 20) From 1.31.0: a movie in several files, played as one.
    await _several_files(checks, app, home, admin_h, sam_h, kit_h, fp)
    await _problems_sent_later(checks, app, home, net, admin_h, sam_h, kit_h)
    await _copies_before_updates(checks, app, home, admin_h)
    await _files_like_ffmpegs_words(checks, app)

    # 21) From 1.31.0: alerts kept across restarts, and the corner mark's drift.
    await _kept_alerts(checks, app, home, admin_h)
    await asyncio.to_thread(_drift, checks)

    # 22) From 1.31.0: no license on the server (the apps are unlocked in
    # their stores).
    await _no_license(checks, home, admin_h, sam_h)

    # 23) From 1.32.0: Tuner access. With only another device listed, the
    # home network's own address gets nothing of the tuner, however the
    # address is written; a User can't change it; a signed-in app plays at
    # its own address instead, which is no good from the internet.
    await _tuner_access(checks, home, net, admin_h, sam_h)

    # 24) From 1.35.0: Media folders of tapiOca's own. Only an Admin adds
    # one, only from inside the media folder; nothing linked from outside it
    # is read or served; the apps never get a file's name or a path.
    await _folders(checks, app, home, net, admin_h, sam_h, kit_h)

    # 25) From 1.36.0: doors left open, and trusted networks. Whatever the
    # mistake (the home port forwarded, a proxy pointed at it, an internet
    # name, headers from a device that isn't a trusted proxy, Docker hiding
    # addresses), it's treated as the internet, or simply not trusted; and
    # what a trusted network gives works only there.
    await _doors_and_trust(checks, app, home, net, admin_h, device_key)

    # 26) From 1.36.2: changes only from tapiOca's own page (its header), at
    # every address a browser could be sent to; and one box, a reverse
    # proxy, Plex and tapiOca on one server, in each way it's laid out.
    await _from_its_page(checks, home)
    await _one_box(checks, app, home, net)

    # 27) From 1.38.0: Full or Light sign-in. An Admin's PIN gives Admin
    # tools only in Light, at home, on a browser their password signed in on;
    # it never makes an Admin or a credential, never changes what's home;
    # wrong PINs there need their own password; a browser's cookie from
    # elsewhere never joins two browsers; and a new role ends sign-ins.
    await _light_sign_in(checks, app, home, net)


async def _light_sign_in(checks: Checks, app, home: str, net: str) -> None:
    checks.section("Full or Light sign-in (1.38.0)")
    db = app.state.ctx.db
    ids = {u.name: u.id for u in db.users()}
    ada, sam = ids[ADMIN["name"]], ids[USER["name"]]

    def peer(n: int) -> dict[str, str]:
        return {**PAGE, "X-Attack-Peer": f"192.168.1.{150 + n}"}

    def signed_out(c: httpx.AsyncClient) -> None:
        c.cookies.delete(access.COOKIE)

    async def pin(c: httpx.AsyncClient, user_id: int, said: str) -> httpx.Response:
        return await c.post("/api/access/pin-sign-in", json={"id": user_id, "pin": said})

    async with (
        httpx.AsyncClient(base_url=home, headers=peer(0), timeout=30) as adas,
        httpx.AsyncClient(base_url=home, headers=peer(1), timeout=30) as sams,
        httpx.AsyncClient(base_url=home, headers=peer(2), timeout=30) as fresh,
    ):
        r = await adas.post("/api/access/sign-in", json=ADMIN)
        checks.ok(r.status_code == 200, "Ada signs in with her password", r.text[:200])
        await adas.put(f"/api/access/users/{ada}/picker", json={"pin": "2580"})
        r = await adas.put("/api/access/me/sign-in", json={"how": "light", "password": "wrong"})
        checks.ok(
            r.status_code == 400, "choosing Light needs the right password", f"got {r.status_code}"
        )
        r = await adas.put("/api/access/me/sign-in",
                           json={"how": "light", "password": ADMIN["password"]})  # fmt: skip
        checks.ok(r.status_code == 200, "Ada chooses Light", r.text[:200])
        # A browser her password never signed in on: no one listed, no PIN.
        me = (await fresh.get("/api/access/me")).json()
        checks.ok("people" not in me, "a new browser lists no one", str(me)[:200])
        r = await pin(fresh, ada, "2580")
        checks.ok(r.status_code == 400 and not r.cookies.get(access.COOKIE),
                  "her PIN on a browser she never signed in on: nothing", f"got {r.status_code}")  # fmt: skip
        # Sam, a User, on his own browser: never listed, even there.
        await sams.post("/api/access/sign-in", json=USER)
        signed_out(sams)
        me = (await sams.get("/api/access/me")).json()
        checks.ok("people" not in me, "a User is never on the page's sign-in screen", str(me)[:200])
        r = await sams.post("/api/access/browser/forget", json={"id": ada})
        r2 = await fresh.post("/api/access/browser/forget", json={"id": 999999})
        checks.ok(r.status_code == r2.status_code and r.text == r2.text,
                  "Remove from this browser says nothing of who's an Admin",
                  f"{r.status_code} {r.text[:80]} / {r2.status_code} {r2.text[:80]}")  # fmt: skip
        # Her own browser: listed, her PIN gives Admin tools at home.
        signed_out(adas)
        me = (await adas.get("/api/access/me")).json()
        checks.ok(me.get("people") == [{"id": ada, "name": ADMIN["name"], "pin": True}],
                  "her browser lists her, with her PIN", str(me)[:200])  # fmt: skip
        async with httpx.AsyncClient(base_url=net, headers={**PAGE, **_cf("203.0.113.80")},
                                     cookies=adas.cookies, timeout=30) as away:  # fmt: skip
            r = await pin(away, ada, "2580")
            checks.ok(
                r.status_code == 404, "her PIN from the internet: nothing", f"got {r.status_code}"
            )
        r = await pin(adas, ada, "2580")
        checks.ok(r.status_code == 200, "her PIN at home, in Light", r.text[:200])
        r = await adas.get("/api/access/users")
        checks.ok(r.status_code == 200, "it gives her Admin tools", f"got {r.status_code}")
        # A PIN's sign-in makes no Admin and no credential, and never changes what's home.
        for what, method, path, body in (
            ("make Sam an Admin", "PUT", f"/api/access/users/{sam}", {"role": "admin"}),
            ("change a password", "PUT", f"/api/access/users/{sam}", {"password": "a long new one"}),
            ("change a PIN", "PUT", f"/api/access/users/{ada}/picker", {"pin": "0000"}),
            ("list a trusted proxy", "PUT", "/api/access/trusted", {"proxies": [{"network": "192.168.1.9"}]}),
            ("add a person", "POST", "/api/access/users", {"name": "Eve", "password": "a long one", "role": "admin"}),
            ("make an API token", "POST", "/api/api-tokens", {"name": "x", "scope": "admin"}),
            ("restore a backup", "POST", "/api/restore", None),
            ("let API tokens work from the internet", "PUT", "/api/api-tokens/outside", {"on": True}),
            ("trust the Away check's proxy", "POST", "/api/away/trust-proxy", {"address": "192.168.1.2"}),
        ):  # fmt: skip
            r = await adas.request(method, path, json=body)
            checks.ok(r.status_code == 403, f"a PIN's sign-in can't {what}", f"got {r.status_code}")
        name = (await adas.post("/api/backups")).json().get("name", "x")
        r = await adas.get(f"/api/backups/{name}")
        checks.ok(r.status_code == 403, "a PIN's sign-in can't download a backup (password hashes)",
                  f"got {r.status_code}")  # fmt: skip
        checks.ok(next(u for u in db.users() if u.id == sam).role == "user", "Sam is still a User")
        r = await adas.put("/api/access/me/sign-in", json={"how": "full", "password": "2580"})
        checks.ok(
            r.status_code == 400,
            "a PIN isn't the password for Full or Light",
            f"got {r.status_code}",
        )
        # A browser's cookie from elsewhere (Sam's, put in Ada's): her
        # password there gives it a new one, and Sam's never lists her.
        async with httpx.AsyncClient(base_url=home, headers=peer(3), timeout=30) as planted:
            kept = next(c for c in sams.cookies.jar if c.name == access.DEVICE_COOKIE)
            token = kept.value or ""
            planted.cookies.set(access.DEVICE_COOKIE, token, domain=kept.domain, path=kept.path)
            await planted.post("/api/access/sign-in", json=ADMIN)
            renewed = planted.cookies.get(access.DEVICE_COOKIE)
        me = (await sams.get("/api/access/me")).json()
        checks.ok(bool(token) and renewed not in (None, token) and "people" not in me,
                  "a browser's cookie from elsewhere never joins two browsers", str(me)[:200])  # fmt: skip
        # Wrong PINs for her: anyone else's password never starts them over.
        wait, devices.PIN_WAIT_S = devices.PIN_WAIT_S, 0  # (the per-person wait, waited out)
        try:
            signed_out(adas)
            said = []
            for _ in range(access.BROWSER_PIN_TRIES):
                await adas.post("/api/access/sign-in", json=USER)
                await adas.post("/api/access/sign-out")
                said.append((await pin(adas, ada, "0000")).text)
            r = await pin(adas, ada, "2580")
            checks.ok("wrong PINs on this browser" in said[-1] and r.status_code == 400,
                      "ten wrong PINs need her own password, whoever else signs in there",
                      f"{said[-1][:80]} / {r.status_code}")  # fmt: skip
        finally:
            devices.PIN_WAIT_S = wait
        # A new role ends that person's sign-ins.
        await adas.post("/api/access/sign-in", json=ADMIN)
        lee = {"name": "Noor", "password": "lantern meadow quartz"}  # (an Admin, new here)
        await adas.post("/api/access/users", json={**lee, "role": "admin"})
        async with httpx.AsyncClient(base_url=home, headers=peer(4), timeout=30) as lees:
            await lees.post("/api/access/sign-in", json=lee)
            before = (await lees.get("/api/access/users")).status_code
            lee_id = next(u.id for u in db.users() if u.name == lee["name"])
            await adas.put(f"/api/access/users/{lee_id}", json={"role": "user"})
            after = (await lees.get("/api/access/users")).status_code
            checks.ok((before, after) == (200, 401), "a new role ends that person's sign-ins",
                      f"{before}, {after}")  # fmt: skip
        await adas.put(
            "/api/access/me/sign-in", json={"how": "full", "password": ADMIN["password"]}
        )


async def _media_away(
    checks: Checks, app, home: str, net: str, admin_h: dict, sam_h: dict, kit_h: dict
) -> None:
    """Media through the public port, once an Admin turns on watching away
    from home: an outsider can't browse or play; a guessed, ended or
    home-made play address gets nothing there; a Kid can't play what their
    level hides; and a play address stops with its sign-in."""
    checks.section("Media through the public port")
    https = {"X-Forwarded-Proto": "https", "X-Real-IP": "203.0.113.60"}
    ctx = app.state.ctx
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        on = await c.put("/api/away", json={"on": True, "address": "https://tv.example.com"},
                         headers=admin_h)  # fmt: skip
        checks.ok(on.status_code == 200, "an Admin turns on watching away from home",
                  f"got {on.status_code}")  # fmt: skip
        at_home = (
            await c.post("/api/internal/play", json={"key": "300", "device": TV}, headers=sam_h)
        ).json()
    async with httpx.AsyncClient(headers=PAGE, base_url=net) as out:
        # An outsider: nothing, with no token or a made-up one.
        for method, path, body in (
            ("GET", "/api/internal/libraries", None), ("GET", "/api/internal/home", None),
            ("GET", "/api/internal/items/300", None), ("GET", "/api/internal/art/300", None),
            ("GET", "/api/internal/libraries/2", None), ("GET", "/api/internal/search?q=pic", None),
            ("POST", "/api/internal/play", {"key": "300", "device": TV}),
            ("POST", "/api/internal/progress", {"key": "300", "positionMs": 60_000}),
        ):  # fmt: skip
            for token in ({}, {"Authorization": "Bearer made-up"}):
                r = await out.request(method, path, json=body, headers={**https, **token})
                made_up = " with a made-up token" if token else ""
                checks.ok(r.status_code == 401, f"an outsider can't {method} {path}{made_up}",
                          f"got {r.status_code}")  # fmt: skip
        # A program started at home isn't offered there, in any way.
        for method in ("GET", "HEAD"):
            r = await out.request(method, at_home["url"], headers=https)
            checks.ok(r.status_code == 404,
                      f"a program started at home can't be {method} from the public port",
                      f"got {r.status_code}")  # fmt: skip
        r = await out.post(at_home["leave"], headers=https)
        checks.ok(r.status_code == 404, "a program started at home can't be ended from there",
                  f"got {r.status_code}")  # fmt: skip
        await out.post(
            "/api/internal/progress",
            json={"key": "300", "positionMs": 60_000, "session": at_home["session"]},
            headers={**https, **sam_h},
        )
        going = ctx.plays.find(at_home["session"])
        checks.ok(going is not None and going.position_ms is None,
                  "a program started at home can't be kept going from there")  # fmt: skip
        # A signed-in app plays through it: the player at its own address.
        played = await out.post("/api/internal/play", json={"key": "300", "device": TV},
                                headers={**https, **sam_h})  # fmt: skip
        if not checks.ok(played.status_code == 200, "a signed-in app plays Media from outside",
                         played.text[:120]):  # fmt: skip
            return
        mine = played.json()
        part = await out.get(mine["url"], headers={**https, "Range": "bytes=0-8"})
        checks.ok(part.status_code == 206 and part.content == b"a program",
                  "its player gets ranges of the file, with no sign-in",
                  f"got {part.status_code}")  # fmt: skip
        plain = await out.get(mine["url"])
        checks.ok(plain.status_code == 403, "its address is refused over plain HTTP",
                  f"got {plain.status_code}")  # fmt: skip
        session = mine["session"]
        for guess in (
            "/play/" + secrets.token_urlsafe(24) + "/file.mkv",
            "/play/" + session[:-1] + ("A" if session[-1] != "A" else "B") + "/file.mkv",
            "/play/" + session.upper() + "/file.mkv",
            "/play/..%2f..%2fetc%2fpasswd/file.mkv",
            "/play/" + session + "%2f..%2f..%2fapi%2flogs",
        ):
            r = await out.get(guess, headers=https)
            checks.ok(r.status_code == 404 and b"root:" not in r.content,
                      f"a guessed play address gets nothing ({guess[:24]}…)",
                      f"got {r.status_code}")  # fmt: skip
        await out.post(mine["leave"], headers=https)
        ended = await out.get(mine["url"], headers=https)
        checks.ok(ended.status_code == 404, "an ended play address gets nothing",
                  f"got {ended.status_code}")  # fmt: skip
        # Its sign-in ending ends it at once.
        signed = await out.post("/api/internal/sign-in", json=USER, headers=https)
        token = {"Authorization": f"Bearer {signed.json().get('token', '')}"}
        again = await out.post("/api/internal/play", json={"key": "300", "device": TV},
                               headers={**https, **token})  # fmt: skip
        if checks.ok(again.status_code == 200, "an app signed in from outside plays Media",
                     again.text[:120]):  # fmt: skip
            await out.post("/api/internal/sign-out", headers={**https, **token})
            gone = await out.get(again.json()["url"], headers=https)
            checks.ok(gone.status_code == 404, "a play address stops when its sign-in ends",
                      f"got {gone.status_code}")  # fmt: skip
        # A Kid can't see or play there what their level hides.
        for key in ("110", "211", "301"):
            seen = await out.get(f"/api/internal/items/{key}", headers={**https, **kit_h})
            r = await out.post("/api/internal/play", json={"key": key, "device": TV},
                               headers={**https, **kit_h})  # fmt: skip
            checks.ok(seen.status_code == 404 and r.status_code == 404,
                      f"the Kid can't see or play item {key} from outside",
                      f"got {seen.status_code}, {r.status_code}")  # fmt: skip
        allowed = await out.post("/api/internal/play", json={"key": "300", "device": TV},
                                 headers={**https, **kit_h})  # fmt: skip
        checks.ok(allowed.status_code == 200, "the PG movie plays for the Kid from outside",
                  f"got {allowed.status_code}")  # fmt: skip
    # Turning watching away from home off ends what plays there.
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        await c.put("/api/away", json={"on": False, "address": "https://tv.example.com"},
                    headers=admin_h)  # fmt: skip
    async with httpx.AsyncClient(headers=PAGE, base_url=net) as out:
        if allowed.status_code == 200:
            r = await out.get(allowed.json()["url"], headers=https)
            checks.ok(r.status_code == 404, "turning away from home off ends Media there",
                      f"got {r.status_code}")  # fmt: skip


async def _new_people_and_everyone(
    checks: Checks, app, home: str, net: str, admin_h: dict, sam_h: dict, kit_h: dict,
    device_key: str,
) -> None:  # fmt: skip
    """New people show only on devices they sign in on: a device lists no one
    else, and no one else can be picked there by their id. Use for everyone
    (POST /api/access/devices/everyone): only an Admin, only from
    tapiOca's own page, only its two choices; many at once leave everyone
    as one of them said; someone who can't sign in by name is never moved to
    Only devices they sign in on. It ends with everyone on every device at
    home, a household, for what's checked after."""
    checks.section("Who's tuning in?: new people, and Use for everyone")
    db = app.state.ctx.db
    key = {"StationPlay-Device": device_key}
    everyone = "/api/access/devices/everyone"
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        default = (await c.get("/api/access/devices", headers=admin_h)).json().get("default")
        picker = (await c.get("/api/internal/picker", headers=key)).json()
        listed = [p["name"] for p in picker["people"]]
        checks.ok(default == "signed-in" and listed == [USER["name"]],
                  "new people show only on devices they sign in on: the device lists only Sam",
                  f"default {default}, listed {listed}")  # fmt: skip
        for person in db.users():
            if person.name == USER["name"]:
                continue
            r = await c.post("/api/internal/picker/choose", headers=key,
                             json={"id": person.id, "password": ADMIN["password"]})  # fmt: skip
            checks.ok(r.status_code == 404,
                      f"{person.name}, who never signed in on it, can't be picked there",
                      f"got {r.status_code}")  # fmt: skip
        # Someone with no password and no PIN, added as new people are: on no
        # device's list, for anyone at home to pick, until an Admin chooses.
        bare = await c.post("/api/access/users", headers=admin_h,
                            json={"name": "Nobody Yet", "role": "user"})  # fmt: skip
        r = await c.post("/api/internal/picker/choose", headers=key,
                         json={"id": bare.json().get("id")})  # fmt: skip
        checks.ok(bare.status_code == 201 and bare.json().get("showOn") == "selected"
                  and r.status_code in (403, 404),
                  "someone new with no password or PIN is on no device's list until chosen",
                  f"{bare.text[:120]}; picked: {r.status_code}")  # fmt: skip
        await c.delete(f"/api/access/users/{bare.json().get('id')}", headers=admin_h)
        # (A household's, on every device at home as an Admin chose.)
        made = await c.post("/api/access/users", headers=admin_h,
                            json={"name": "Little Ones", "role": "user", "showOn": "home"})  # fmt: skip

        def shown() -> dict[str, str]:
            return {u.name: u.show_on for u in db.users()}

        before, chosen = shown(), db.get_meta("show_on_default")
        for said, headers in (("a User", sam_h), ("a Kid", kit_h), ("no one signed in", {})):
            r = await c.post(everyone, json={"showOn": "home"}, headers=headers)
            checks.ok(r.status_code in (401, 403), f"{said} can't use Use for everyone",
                      f"got {r.status_code}")  # fmt: skip
        async with httpx.AsyncClient(headers=PAGE, base_url=net) as out:
            r = await out.post(everyone, json={"showOn": "home"},
                               headers={"X-Forwarded-Proto": "https", "X-Real-IP": "203.0.113.80"})  # fmt: skip
            checks.ok(r.status_code == 401, "nor can an outsider from the internet",
                      f"got {r.status_code}")  # fmt: skip
        async with httpx.AsyncClient(headers=PAGE, base_url=home) as page:
            await page.post("/api/access/sign-in", json=ADMIN)
            r = await page.post(everyone, json={"showOn": "home"},
                                headers={"Sec-Fetch-Site": "cross-site"})  # fmt: skip
            checks.ok(r.status_code == 403, "Use for everyone from another site is refused",
                      f"got {r.status_code}")  # fmt: skip
        for bad in ("all", "selected", "default", "Home", "home ", "", "x" * 5000, None, 1,
                    ["home"], {"showOn": "home"}):  # fmt: skip
            r = await c.post(everyone, json={"showOn": bad}, headers=admin_h)
            checks.ok(r.status_code in (400, 413, 422),
                      f"Use for everyone with {str(bad)[:20]!r} is refused", f"got {r.status_code}")  # fmt: skip
        checks.ok(shown() == before and db.get_meta("show_on_default") == chosen,
                  "and nothing changed", shown())  # fmt: skip

        # Many at once, each way: everyone ends up as one of them said, and
        # who can't sign in by name is never on Only devices they sign in on.
        codes = [
            r.status_code
            for r in await asyncio.gather(*(
                c.post(everyone, json={"showOn": ("home", "signed-in")[n % 2]}, headers=admin_h)
                for n in range(20)
            ))
        ]  # fmt: skip
        last = db.get_meta("show_on_default")
        everyone_now = {u.name: u.show_on for u in db.users() if u.name != "Little Ones"}
        checks.ok(set(codes) == {200} and set(everyone_now.values()) == {last},
                  "Use for everyone, many at once: everyone shows as the last one said",
                  f"codes {sorted(set(codes))}, default {last}, {everyone_now}")  # fmt: skip
        got = await c.post(everyone, json={"showOn": "signed-in"}, headers=admin_h)
        little = db.user(made.json()["id"])
        checks.ok(got.status_code == 200 and got.json().get("kept") == ["Little Ones"]
                  and little is not None and little.show_on == "home",
                  "someone with no password or PIN is kept as they were, and named",
                  got.text[:200])  # fmt: skip
        r = await c.post("/api/internal/picker/choose", headers=key,
                         json={"id": made.json()["id"]})  # fmt: skip
        checks.ok(r.status_code == 404,
                  "and, never signed in on the device, not on its list, whatever Show on says "
                  "(1.38.0)", f"got {r.status_code}")  # fmt: skip

        # (A household from here on.)
        r = await c.post(everyone, json={"showOn": "home"}, headers=admin_h)
        await c.delete(f"/api/access/users/{made.json()['id']}", headers=admin_h)
        checks.ok(r.status_code == 200 and {u.show_on for u in db.users()} == {"home"},
                  "Use for everyone: Every device at home, for everyone", r.text[:200])  # fmt: skip


async def _picker_away(checks: Checks, app, home: str, net: str, device_key: str) -> None:
    """A linked device's picker, at home and through the public port: it
    lists only who signed in on it (from 1.38.0, at home too, whatever Show
    on says), and no one it doesn't list there can be picked by their id."""
    checks.section("Who's tuning in? away from home")
    key = {"StationPlay-Device": device_key}
    https = {"X-Forwarded-Proto": "https", "X-Real-IP": "203.0.113.65", **key}
    async with httpx.AsyncClient(base_url=home, headers=key) as c:
        at_home = [p["name"] for p in (await c.get("/api/internal/picker")).json()["people"]]
    async with httpx.AsyncClient(base_url=net, headers=https) as out:
        r = await out.get("/api/internal/picker")
        away = [p["name"] for p in r.json().get("people", [])] if r.status_code == 200 else None
        checks.ok(
            away == at_home == [USER["name"]],
            "at home and away, the device lists only who signed in on it",
            f"at home {at_home}, away {away}",
        )
        for person in app.state.ctx.db.users():
            if person.name == USER["name"]:
                continue
            r = await out.post("/api/internal/picker/choose",
                               json={"id": person.id, "password": ADMIN["password"]})  # fmt: skip
            checks.ok(r.status_code == 404,
                      f"{person.name}, not on its list, can't be picked away from home",
                      f"got {r.status_code}")  # fmt: skip
        plain = await out.get("/api/internal/picker", headers={"X-Forwarded-Proto": "http"})
        checks.ok(plain.status_code == 403, "the picker away from home needs HTTPS",
                  f"got {plain.status_code}")  # fmt: skip


async def _own_pin_and_password(
    checks: Checks, app, home: str, net: str, admin_h: dict, sam_h: dict, kit_h: dict,
    device_key: str,
) -> None:  # fmt: skip
    """POST /api/internal/pin and /api/internal/password: an outsider can't
    use them; one person can't change another's; an Admin's PIN can't be
    removed in an app; a PIN is exactly 4 digits; and the limits hold
    (wrong current passwords, many at once, and the wait after wrong
    PINs, which a new one doesn't end)."""
    checks.section("PINs and passwords from the apps")
    db = app.state.ctx.db
    ids = {u.name: u.id for u in db.users()}
    pin_of = db.pin_hash
    password_of = db.password_hash
    https = {"X-Forwarded-Proto": "https", "X-Real-IP": "203.0.113.70"}
    tries = {"current": "not the one", "new": "a brand new password"}
    both = (("/api/internal/pin", {"pin": "1111"}), ("/api/internal/password", tries))

    # An outsider: no token, a made-up one, a device's key alone, plain HTTP.
    async with httpx.AsyncClient(headers=PAGE, base_url=net) as out:
        for path, body in both:
            for said, headers in (
                ("no token", https), ("a made-up token", {**https, "Authorization": "Bearer made-up"}),
                ("a device's key alone", {**https, "StationPlay-Device": device_key}),
            ):  # fmt: skip
                r = await out.post(path, json=body, headers=headers)
                checks.ok(r.status_code == 401, f"an outsider can't POST {path} with {said}",
                          f"got {r.status_code}")  # fmt: skip
            r = await out.post(path, json=body, headers={**kit_h, "X-Real-IP": "203.0.113.70"})
            checks.ok(r.status_code == 403, f"POST {path} needs HTTPS from the internet",
                      f"got {r.status_code}")  # fmt: skip
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        for path, body in both:
            r = await c.post(path, json=body)
            checks.ok(r.status_code == 401, f"POST {path} needs a sign-in at home too",
                      f"got {r.status_code}")  # fmt: skip
        # A browser's sign-in isn't an app's.
        async with httpx.AsyncClient(headers=PAGE, base_url=home) as page:
            await page.post("/api/access/sign-in", json=KID)
            r = await page.post("/api/internal/pin", json={"pin": "1111"})
            checks.ok(r.status_code == 403, "a browser's sign-in can't set a PIN",
                      f"got {r.status_code}")  # fmt: skip

        # One person can't change another's: whatever else is sent, it's theirs.
        sams_pin, sams_password = pin_of(ids[USER["name"]]), password_of(ids[USER["name"]])
        r = await c.post("/api/internal/pin", headers=kit_h,
                         json={"pin": "1111", "id": ids[USER["name"]], "name": USER["name"],
                               "user": {"name": USER["name"]}})  # fmt: skip
        checks.ok(r.status_code == 200 and pin_of(ids[USER["name"]]) == sams_pin
                  and pin_of(ids[KID["name"]]) != "",
                  "a PIN set with someone else's name or id is the sender's own",
                  f"got {r.status_code}")  # fmt: skip
        r = await c.post("/api/internal/password", headers=kit_h,
                         json={"current": USER["password"], "new": "taken over now",
                               "name": USER["name"], "id": ids[USER["name"]]})  # fmt: skip
        checks.ok(r.status_code == 400 and password_of(ids[USER["name"]]) == sams_password,
                  "someone else's current password changes nothing",
                  f"got {r.status_code}")  # fmt: skip
        for method, path, body in (
            ("PUT", f"/api/access/users/{ids[USER['name']]}/picker", {"pin": "0000"}),
            ("PUT", f"/api/access/users/{ids[USER['name']]}/picker", {"pin": ""}),
            ("PUT", f"/api/access/users/{ids[USER['name']]}", {"password": "taken over now"}),
            ("PUT", f"/api/access/users/{ids[KID['name']]}", {"canChangePassword": True}),
        ):  # fmt: skip
            r = await c.request(method, path, json=body, headers=kit_h)
            checks.ok(r.status_code == 403, f"a User can't {method} {path} {body}",
                      f"got {r.status_code}")  # fmt: skip

        # An Admin's PIN can't be removed in an app.
        set_it = await c.post("/api/internal/pin", headers=admin_h, json={"pin": "1357"})
        kept = await c.post("/api/internal/pin", headers=admin_h, json={"pin": None})
        checks.ok(set_it.status_code == 200 and kept.status_code == 403
                  and pin_of(ids[ADMIN["name"]]) != "",
                  "an Admin's PIN can't be removed in an app",
                  f"got {set_it.status_code}, {kept.status_code}")  # fmt: skip

        # A PIN is exactly 4 digits, 0 to 9.
        kits_pin = pin_of(ids[KID["name"]])
        for wrong in ("123", "12345", "abcd", "12a4", " 1234", "1234 ", "1234\n", "",
                      "\u0661\u0662\u0663\u0664", "\uff11\uff12\uff13\uff14", "+123",
                      "-123", "12.3", "0x12", 1234, ["1234"], {"pin": "1234"}):  # fmt: skip
            r = await c.post("/api/internal/pin", headers=kit_h, json={"pin": wrong})
            checks.ok(r.status_code == 400 and pin_of(ids[KID["name"]]) == kits_pin,
                      f"the PIN {wrong!r} is refused", f"got {r.status_code}")  # fmt: skip
        r = await c.post("/api/internal/pin", headers=kit_h, json={})
        checks.ok(r.status_code == 400, "a PIN must be sent (or null)", f"got {r.status_code}")

        # Someone anyone at home may pick ("Kids") gets a PIN only from an Admin.
        made = await c.post("/api/access/users", headers=admin_h,
                            json={"name": "Kids", "role": "user"})  # fmt: skip
        # (From 1.38.0 a device lists only those who signed in on it: Kids
        # with an invite code.)
        code = (await c.post(f"/api/access/users/{made.json()['id']}/invite",
                             headers=admin_h)).json()["code"]  # fmt: skip
        await c.post("/api/internal/picker/sign-in", json={"name": "Kids", "code": code},
                     headers={"StationPlay-Device": device_key})  # fmt: skip
        picked = await c.post("/api/internal/picker/choose", json={"id": made.json()["id"]},
                              headers={"StationPlay-Device": device_key})  # fmt: skip
        kids_h = {"Authorization": f"Bearer {picked.json().get('token', '')}"}
        for pin in ("2222", None):
            r = await c.post("/api/internal/pin", headers=kids_h, json={"pin": pin})
            checks.ok(r.status_code == 403, f"Kids can't set their own PIN ({pin!r})",
                      f"got {r.status_code}")  # fmt: skip
        r = await c.post("/api/internal/password", headers=kids_h,
                         json={"current": "", "new": "a brand new password"})  # fmt: skip
        checks.ok(r.status_code == 403, "Kids can't give themselves a password",
                  f"got {r.status_code}")  # fmt: skip

        # Someone with a password but no PIN, picked by whoever is at the
        # device, isn't locked out by them.
        made = await c.post("/api/access/users", headers=admin_h,
                            json={"name": "Lee", "password": "harbor violet quill", "role": "user"})  # fmt: skip
        await c.post("/api/internal/picker/sign-in", headers={"StationPlay-Device": device_key},
                     json={"name": "Lee", "password": "harbor violet quill"})  # fmt: skip
        picked = await c.post("/api/internal/picker/choose", json={"id": made.json()["id"]},
                              headers={"StationPlay-Device": device_key})  # fmt: skip
        lee_h = {"Authorization": f"Bearer {picked.json().get('token', '')}"}
        for pin in ("2222", None):
            r = await c.post("/api/internal/pin", headers=lee_h, json={"pin": pin})
            checks.ok(r.status_code == 403 and pin_of(made.json()["id"]) == ""
                      and picked.status_code == 200,
                      f"picking someone without a PIN can't set theirs ({pin!r})",
                      f"got {picked.status_code}, {r.status_code}")  # fmt: skip

        # The wait after wrong PINs holds, even after a new one is set.
        await c.post("/api/internal/pin", headers=sam_h, json={"pin": "2468"})
        r = await c.post("/api/internal/picker/choose", json={"id": ids[USER["name"]], "pin": "2468"},
                         headers={"StationPlay-Device": device_key})  # fmt: skip
        checks.ok(r.status_code == 429, "a new PIN doesn't end the wait after wrong ones",
                  f"got {r.status_code}")  # fmt: skip

    kits_password = password_of(ids[KID["name"]])
    async with httpx.AsyncClient(headers=PAGE, base_url=net) as out:
        # Wrong current passwords count as wrong sign-ins (from that address).
        one = {**https, **kit_h, "X-Real-IP": "203.0.113.71"}
        for _ in range(access.TRIES):
            await out.post("/api/internal/password", json=tries, headers=one)
        r = await out.post("/api/internal/password", headers=one,
                           json={"current": KID["password"], "new": "a brand new password"})  # fmt: skip
        checks.ok(r.status_code == 429 and password_of(ids[KID["name"]]) == kits_password,
                  "changing a password waits after too many wrong current ones",
                  f"got {r.status_code}")  # fmt: skip
        # Many at once can't beat the limit, or get in.
        many = {**https, **kit_h, "X-Real-IP": "203.0.113.72"}
        codes = [
            r.status_code
            for r in await asyncio.gather(*(
                out.post("/api/internal/password", headers=many,
                         json={"current": f"guess {n}", "new": "a brand new password"})
                for n in range(30)
            ))
        ]  # fmt: skip
        checks.ok(codes.count(400) <= access.TRIES and 200 not in codes and 429 in codes
                  and password_of(ids[KID["name"]]) == kits_password,
                  "many wrong current passwords at once can't beat the limit",
                  f"checked={codes.count(400)} changed={codes.count(200)}")  # fmt: skip

    # When an Admin turns it off, neither the app nor the page changes it.
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        off = await c.put(f"/api/access/users/{ids[KID['name']]}", headers=admin_h,
                          json={"canChangePassword": False})  # fmt: skip
        r = await c.post("/api/internal/password", headers=kit_h,
                         json={"current": KID["password"], "new": "a brand new password"})  # fmt: skip
        async with httpx.AsyncClient(headers=PAGE, base_url=home) as page:
            await page.post("/api/access/sign-in", json=KID)
            on_page = await page.post("/api/access/me/password",
                                      json={"current": KID["password"], "password": "a brand new one"})  # fmt: skip
        checks.ok(off.status_code == 200 and r.status_code == 403 and on_page.status_code == 403
                  and password_of(ids[KID["name"]]) == kits_password,
                  "with it turned off, a User can't change their own password anywhere",
                  f"got {off.status_code}, {r.status_code}, {on_page.status_code}")  # fmt: skip


class _Hook:
    """A web address on this machine for alerts to be sent to: /hook answers
    200, /redirect sends them on to /landed, and /slow never answers. It
    notes the paths asked for."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.port = 0
        self._server: asyncio.Server | None = None
        self._answering: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._answer, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
        for task in self._answering:
            task.cancel()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    async def _answer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._answering.add(task)
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            path = head.split(b" ", 2)[1].decode()
            self.asked.append(path.split("?")[0])
            if path.startswith("/slow"):
                await asyncio.sleep(30)
            elif path.startswith("/redirect"):
                writer.write(f"HTTP/1.1 302 Found\r\nLocation: {self.url('/landed')}\r\n"
                             "Content-Length: 0\r\n\r\n".encode())  # fmt: skip
            else:
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, IndexError):
            pass
        finally:
            writer.close()
            self._answering.discard(task)  # type: ignore[arg-type]


async def _alerts_and_notify(
    checks: Checks, app, home: str, net: str, admin_h: dict, sam_h: dict, kit_h: dict
) -> None:
    """GET /api/internal/alerts and the web address alerts go to: only an
    Admin reads them or sets it; it's only ever http or https; a redirect is
    never followed; one that never answers holds nothing else up; and the log
    never has the address whole."""
    checks.section("Admin alerts, and the web address they're sent to")
    ctx = app.state.ctx
    https = {"X-Forwarded-Proto": "https", "X-Real-IP": "203.0.113.80"}
    hook = _Hook()
    await hook.start()
    try:
        async with httpx.AsyncClient(headers=PAGE, base_url=net) as out:
            for token in ({}, {"Authorization": "Bearer made-up"}):
                for method, path in (("GET", "/api/internal/alerts"), ("GET", "/api/notify"),
                                     ("PUT", "/api/notify"), ("POST", "/api/notify/test")):  # fmt: skip
                    r = await out.request(method, path, headers={**https, **token},
                                          json={"on": True, "url": hook.url("/hook")})  # fmt: skip
                    made_up = " with a made-up token" if token else ""
                    checks.ok(r.status_code == 401, f"an outsider can't {method} {path}{made_up}",
                              f"got {r.status_code}")  # fmt: skip
            r = await out.get("/api/internal/alerts", headers=admin_h)
            checks.ok(r.status_code == 403, "alerts aren't sent over plain HTTP from the internet",
                      f"got {r.status_code}")  # fmt: skip
            for who, headers in (("a User", sam_h), ("a Kid", kit_h)):
                r = await out.get("/api/internal/alerts", headers={**https, **headers})
                checks.ok(r.status_code == 403, f"{who} can't read alerts from the internet",
                          f"got {r.status_code}")  # fmt: skip
        async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
            for who, headers in (("a User", sam_h), ("a Kid", kit_h)):
                for method, path in (("GET", "/api/internal/alerts"), ("GET", "/api/notify"),
                                     ("PUT", "/api/notify"), ("POST", "/api/notify/test")):  # fmt: skip
                    r = await c.request(method, path, headers=headers,
                                        json={"on": True, "url": hook.url("/hook")})  # fmt: skip
                    checks.ok(r.status_code == 403, f"{who} can't {method} {path}",
                              f"got {r.status_code}")  # fmt: skip
            checks.ok(not ctx.notify.on and not hook.asked,
                      "nothing was set or sent for them")  # fmt: skip
            async with httpx.AsyncClient(headers=PAGE, base_url=home) as page:
                await page.post("/api/access/sign-in", json=USER)
                status = (await page.get("/api/status")).json()
                checks.ok("alerts" not in status, "a User's page isn't told the alerts")
            r = await c.get("/api/internal/alerts", headers=admin_h)
            checks.ok(r.status_code == 200 and isinstance(r.json().get("alerts"), list),
                      "an Admin reads the alerts", f"got {r.status_code}")  # fmt: skip

            # Only http and https, however it's dressed up.
            for url in (
                "file:///etc/passwd", "ftp://127.0.0.1/x", "gopher://127.0.0.1:70/_x",
                "javascript:alert(1)", "data:text/plain,hi", "dict://127.0.0.1:11211/",
                "//127.0.0.1/hook", "127.0.0.1/hook", "http:///hook", "http://exa mple.com/",
                "http://127.0.0.1/\r\nX-Injected: 1", "  ", "https://example.com/" + "x" * 600,
                "\u0068ttp://127.0.0.1/hook\u0000",
            ):  # fmt: skip
                saved = await c.put("/api/notify", headers=admin_h, json={"on": True, "url": url})
                tested = await c.post("/api/notify/test", headers=admin_h, json={"url": url})
                checks.ok(saved.status_code in (400, 422) and tested.status_code in (400, 422)
                          and not ctx.notify.on,
                          f"the web address {url[:40]!r} is refused",
                          f"got {saved.status_code}, {tested.status_code}")  # fmt: skip
            checks.ok(not hook.asked, "nothing was sent to a refused address")

            # A redirect is never followed.
            tested = await c.post("/api/notify/test", headers=admin_h,
                                  json={"url": hook.url("/redirect"), "format": "json"})  # fmt: skip
            sent = tested.json().get("sent", {}) if tested.status_code == 200 else {}
            checks.ok(sent.get("ok") is False and "/landed" not in hook.asked
                      and hook.asked.count("/redirect") == 2,
                      "a redirect is never followed (and it's tried once more)",
                      f"got {tested.status_code}, {sent}, asked {hook.asked}")  # fmt: skip

            # One that never answers is given 5 seconds (and one more try),
            # and holds nothing else up meanwhile.
            await c.put("/api/notify", headers=admin_h,
                        json={"on": True, "url": hook.url("/slow?token=sekret-token")})  # fmt: skip
            began = asyncio.get_running_loop().time()
            slow = asyncio.ensure_future(
                c.post("/api/notify/test", headers=admin_h, json={}, timeout=30)
            )
            await asyncio.sleep(0.5)
            quick = await c.get("/api/v1/server")
            waited = asyncio.get_running_loop().time() - began
            checks.ok(quick.status_code == 200 and waited < 2,
                      "a web address that never answers holds nothing else up",
                      f"{waited:.1f}s")  # fmt: skip
            tested = await slow
            took = asyncio.get_running_loop().time() - began
            sent = tested.json().get("sent", {}) if tested.status_code == 200 else {}
            checks.ok(sent.get("status") == "no answer within 5 seconds" and took < 15,
                      "a web address that never answers is given 5 seconds, and one more try",
                      f"{sent} after {took:.1f}s")  # fmt: skip
            # An alert starting meanwhile is never waited on.
            began = asyncio.get_running_loop().time()
            ctx.alerts.start("backups", "The attack check's own alert.")
            r = await c.get("/api/internal/alerts", headers=admin_h)
            waited = asyncio.get_running_loop().time() - began
            listed = [a["sentence"] for a in r.json().get("alerts", [])]
            checks.ok("The attack check's own alert." in listed and waited < 1,
                      "an alert goes out in the background", f"{waited:.1f}s")  # fmt: skip
            ctx.alerts.fix("backups", "The attack check's alert is over.")
            logs = (await c.get("/api/logs?limit=500", headers=admin_h)).json().get("text", "")
            checks.ok("sekret-token" not in logs and "/slow" not in logs,
                      "the log never has the web address whole")  # fmt: skip
            await c.put("/api/notify", headers=admin_h, json={"on": False, "url": ""})
    finally:
        await hook.stop()


async def _languages(
    checks: Checks, app, home: str, net: str, admin_h: dict, sam_h: dict, kit_h: dict
) -> None:
    """PUT /api/internal/languages and /api/internal/items/{key}/languages:
    an outsider can't; one person's are never another's, whatever's sent;
    only languages tapiOca knows; and only for what someone can see."""
    checks.section("Each person's languages")
    https = {"X-Forwarded-Proto": "https", "X-Real-IP": "203.0.113.90"}
    async with httpx.AsyncClient(headers=PAGE, base_url=net) as out:
        for method, path in (("PUT", "/api/internal/languages"),
                             ("PUT", "/api/internal/items/300/languages"),
                             ("DELETE", "/api/internal/items/300/languages")):  # fmt: skip
            for token in ({}, {"Authorization": "Bearer made-up"}):
                r = await out.request(
                    method, path, json={"audio": "jpn"}, headers={**https, **token}
                )
                made_up = " with a made-up token" if token else ""
                checks.ok(r.status_code == 401, f"an outsider can't {method} {path}{made_up}",
                          f"got {r.status_code}")  # fmt: skip
        r = await out.put("/api/internal/languages", json={"audio": "jpn"}, headers=sam_h)
        checks.ok(r.status_code == 403, "languages aren't set over plain HTTP from the internet",
                  f"got {r.status_code}")  # fmt: skip
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:

        async def mine(headers: dict) -> dict:
            return (await c.get("/api/internal/me", headers=headers)).json().get("languages", {})

        kits, admins = await mine(kit_h), await mine(admin_h)
        kit = next(u.id for u in app.state.ctx.db.users() if u.name == KID["name"])
        r = await c.put("/api/internal/languages", headers=sam_h,
                        json={"audio": "jpn", "captions": True, "user": KID["name"], "id": kit,
                              "userId": kit, "name": KID["name"], "user_id": kit})  # fmt: skip
        sams = await mine(sam_h)
        checks.ok(r.status_code == 200 and (sams.get("audio") or {}).get("code") == "jpn"
                  and await mine(kit_h) == kits and await mine(admin_h) == admins,
                  "languages sent with someone else's name or id are the sender's own",
                  f"got {r.status_code}")  # fmt: skip
        r = await c.put("/api/internal/items/300/languages", headers=sam_h,
                        json={"audio": "fre", "user": KID["name"], "id": kit})  # fmt: skip
        kit_item = (await c.get("/api/internal/items/300", headers=kit_h)).json()
        checks.ok(r.status_code == 200 and kit_item.get("languages") == {"item": None, "show": None},
                  "a show's or movie's languages are the sender's own",
                  f"got {r.status_code}, {kit_item.get('languages')}")  # fmt: skip
        played = await c.post("/api/internal/play", headers=kit_h,
                              json={"key": "300", "device": TV})  # fmt: skip
        checks.ok(played.status_code == 200 and played.json().get("chosen") is None,
                  "another's languages never choose what someone plays",
                  f"got {played.status_code}")  # fmt: skip

        # Only languages tapiOca knows, as codes; captions true or false.
        before = await mine(sam_h)
        for body in (
            {"audio": "klingon"}, {"audio": ""}, {"audio": "e" * 41}, {"audio": "<script>"},
            {"audio": "eng'; DROP TABLE languages; --"}, {"audio": "../../etc/passwd"},
            {"audio": 7}, {"audio": ["eng"]}, {"audio": {"code": "eng"}}, {"audio": True},
            {"captionLanguage": "zz"}, {"captionLanguage": "eng\u0000"}, {"captions": "true"},
            {"captions": 1}, {"captions": None}, {"captions": [True]},
        ):  # fmt: skip
            r = await c.put("/api/internal/languages", headers=sam_h, json=body)
            checks.ok(r.status_code == 400 and await mine(sam_h) == before,
                      f"the languages {body!r} are refused", f"got {r.status_code}")  # fmt: skip
        for body in ({"audio": "xx"}, {"captions": "no"}, {"captionLanguage": 12}):
            r = await c.put("/api/internal/items/300/languages", headers=sam_h, json=body)
            checks.ok(r.status_code == 400, f"a movie's languages {body!r} are refused",
                      f"got {r.status_code}")  # fmt: skip

        # Only for what someone can see, and only shows, episodes and movies.
        for key in ("301", "211", "110", "999999", "..%2f..%2fetc", "300%20OR%201=1", "-1"):
            for method in ("PUT", "DELETE"):
                r = await c.request(method, f"/api/internal/items/{key}/languages",
                                    headers=kit_h, json={"audio": "eng"})  # fmt: skip
                checks.ok(r.status_code in (400, 404, 405),
                          f"a Kid can't {method} languages for {key}", f"got {r.status_code}")  # fmt: skip


async def _library(checks: Checks, app, home: str, admin_h: dict, kit_h: dict) -> None:
    """Media's addresses: a Kid gets nothing their level hides from any of
    them (lists, home, search, details, others like it, episodes, pictures,
    languages, playing, progress), answered as for what doesn't exist, even
    with a key from an Admin's Resume row or an Admin's playing; and every
    address takes only what's bounded, saying why in a sentence (never a
    500, a stack trace or Plex's address)."""
    checks.section("Media: what a level hides, and bounded inputs")

    def plain_refusal(r: httpx.Response) -> bool:
        body = r.text
        return (
            (r.status_code < 500 or r.status_code == 503)
            and "Traceback" not in body
            and "plex.test" not in body
        )

    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        # Ada watches the grown-ups' show, and plays it.
        await c.post("/api/internal/progress", headers=admin_h,
                     json={"key": "211", "positionMs": 600_000})  # fmt: skip
        resume = (await c.get("/api/internal/home", headers=admin_h)).json().get("continue", [])
        played = (await c.post("/api/internal/play", headers=admin_h,
                               json={"key": "211", "device": TV})).json()  # fmt: skip
        checks.ok("211" in [x["key"] for x in resume] and "session" in played,
                  "an Admin resumes and plays the grown-ups' show")  # fmt: skip
        await c.get("/api/internal/art/301", headers=admin_h)  # (its poster kept, now)
        gone = (await c.get("/api/internal/items/999999", headers=kit_h)).json()
        for key in ("110", "211", "301"):
            asks = [
                ("GET", f"/api/internal/items/{key}", None, "asking for its details"),
                ("GET", f"/api/internal/items/{key}/related", None, "asking for others like it"),
                ("GET", f"/api/internal/items/{key}/episodes", None, "asking for its episodes"),
                ("GET", f"/api/internal/art/{key}?kind=poster&w=320", None, "asking for its poster"),
                ("GET", f"/api/internal/art/{key}?kind=backdrop", None, "asking for its backdrop"),
                ("GET", f"/api/internal/art/{key}?kind=thumb", None, "asking for its still"),
                ("PUT", f"/api/internal/items/{key}/languages", {"audio": "eng"},
                 "choosing its languages"),
                ("DELETE", f"/api/internal/items/{key}/languages", None,
                 "clearing its languages"),
                ("POST", "/api/internal/play", {"key": key, "device": TV}, "playing it"),
                ("POST", "/api/internal/progress", {"key": key, "positionMs": 60_000},
                 "reporting a place in it"),
                ("POST", "/api/internal/progress", {"key": key, "watched": True},
                 "marking it watched"),
                ("POST", "/api/internal/watched", {"show": key, "watched": True},
                 "marking all of it watched"),
                ("POST", "/api/internal/progress",
                 {"key": key, "positionMs": 60_000, "session": played.get("session", "")},
                 "reporting a place in an Admin's playing of it"),
            ]  # fmt: skip
            for method, path, body, what in asks:
                r = await c.request(method, path, json=body, headers=kit_h)
                checks.ok(r.status_code == 404 and r.json() == gone,
                          f"the Kid {what} ({key}) is answered as though it weren't there",
                          f"got {r.status_code}")  # fmt: skip
        lists = [
            (await c.get(path, headers=kit_h)).text
            for path in ("/api/internal/libraries/1?size=200", "/api/internal/libraries/2?size=200",
                         "/api/internal/home", "/api/internal/search?q=i",
                         "/api/internal/search?q=night", "/api/internal/search?q=heist",
                         "/api/internal/items/100/episodes", "/api/internal/items/100/related",
                         "/api/internal/items/300/related")
        ]  # fmt: skip
        for key in ("110", "211", "301"):
            checks.ok(all(f'"key":"{key}"' not in text for text in lists),
                      f"no list shows the Kid {key}")  # fmt: skip

        # Bounded inputs: refused with a sentence, never a 500.
        for method, path, body, wanted in (
            ("GET", "/api/internal/search?q=" + "a" * 101, None, 400),
            ("GET", "/api/internal/search?q=" + "%25" * 3000, None, 400),
            ("GET", "/api/internal/search?q=%00%01%27%22%3Cscript%3E", None, 200),
            ("GET", "/api/internal/libraries/2?size=201", None, 400),
            ("GET", "/api/internal/libraries/2?size=0", None, 400),
            ("GET", "/api/internal/libraries/2?start=-1", None, 400),
            ("GET", "/api/internal/libraries/2?start=1000000000", None, 400),
            ("GET", "/api/internal/libraries/2?sort=size", None, 400),
            ("GET", "/api/internal/libraries/2?genre=" + "x" * 101, None, 400),
            ("GET", "/api/internal/items/100/episodes?size=501", None, 400),
            ("GET", "/api/internal/items/100/episodes?season=99999999", None, 400),
            ("GET", "/api/internal/art/300?w=10001", None, 400),
            ("GET", "/api/internal/art/300?w=-1", None, 400),
            ("GET", "/api/internal/art/300?kind=..%2f..%2fetc", None, 400),
            ("GET", "/api/internal/items/..%2f..%2fetc%2fpasswd", None, 404),
            ("GET", "/api/internal/items/300%20OR%201=1", None, 404),
            ("GET", "/api/internal/items/" + "9" * 25, None, 404),
            ("GET", "/api/internal/items/%D9%A1%D9%A2%D9%A3", None, 404),  # (Arabic digits)
            ("GET", "/api/internal/libraries/" + "1" * 40, None, 404),
            ("POST", "/api/internal/play", {"key": "x" * 21, "device": TV}, 400),
            ("POST", "/api/internal/play", {"key": "300", "device": TV, "startMs": -1}, 400),
            ("POST", "/api/internal/play", {"key": "300", "device": {"video": [{}] * 41}}, 400),
            ("POST", "/api/internal/progress", {"key": "300", "positionMs": -1}, 400),
            ("POST", "/api/internal/progress", {"key": "300", "positionMs": 2**63}, 400),
            ("POST", "/api/internal/progress", {"key": "300", "positionMs": 3 * 3_600_000}, 400),
            ("POST", "/api/internal/progress", {"key": "300", "positionMs": 1, "sequence": 0}, 400),
            ("POST", "/api/internal/progress", {"key": "300", "positionMs": 1,
                                                "sequence": 2**40}, 400),
            ("POST", "/api/internal/progress", {"key": "300", "session": "x" * 65,
                                                "positionMs": 1}, 400),
        ):  # fmt: skip
            r = await c.request(method, path, json=body, headers=kit_h)
            said = r.headers.get("content-type", "").startswith("application/json") and (
                r.status_code == 200 or isinstance(r.json().get("detail"), str)
            )
            checks.ok(r.status_code == wanted and said and plain_refusal(r),
                      f"{method} {path[:60]} is answered {wanted}, plainly",
                      f"got {r.status_code}: {r.text[:80]}")  # fmt: skip


async def _reports(
    checks: Checks, app, home: str, net: str, admin_h: dict, sam_h: dict, kit_h: dict
) -> None:
    """People's reports (reports.py): an outsider can't send one, read the
    choices or touch the Broken files tab; a report is always the sender's
    own, whatever it says; only what someone may see; the limits hold, all
    at once too; the choices are only the server's, and everything sent is
    bounded; and only an Admin sees reports and acts on them."""
    checks.section("People's reports")
    ctx = app.state.ctx
    https = {"X-Forwarded-Proto": "https", "X-Real-IP": "203.0.113.90"}
    report = "/api/internal/report-problem"
    async with httpx.AsyncClient(headers=PAGE, base_url=net) as out:
        for token in ({}, {"Authorization": "Bearer made-up"}):
            for method, path in (("GET", "/api/internal/report-choices"), ("POST", report),
                                 ("GET", "/api/reports"), ("POST", "/api/reports/300/dismiss"),
                                 ("POST", "/api/reports/300/replace")):  # fmt: skip
                r = await out.request(method, path, headers={**https, **token},
                                      json={"choice": "no-sound", "key": "300"})  # fmt: skip
                made_up = " with a made-up token" if token else ""
                checks.ok(r.status_code == 401, f"an outsider can't {method} {path}{made_up}",
                          f"got {r.status_code}")  # fmt: skip
        r = await out.post(report, headers=sam_h, json={"choice": "no-sound", "key": "300"})
        checks.ok(r.status_code == 403, "a report isn't taken over plain HTTP from the internet",
                  f"got {r.status_code}")  # fmt: skip
        r = await out.post(report, headers={**https, **sam_h},
                           json={"choice": "no-sound", "key": "300"})  # fmt: skip
        checks.ok(r.status_code in (403, 404),
                  "with away from home off, nothing in Media is reported through the public port",
                  f"got {r.status_code}")  # fmt: skip
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        # Only an Admin sees reports, and acts on them.
        for who, headers in (("a User", sam_h), ("a Kid", kit_h)):
            for method, path in (("GET", "/api/reports"), ("POST", "/api/reports/300/dismiss"),
                                 ("POST", "/api/reports/300/replace"),
                                 ("POST", "/api/reports/300/better"), ("GET", "/api/broken")):  # fmt: skip
                r = await c.request(method, path, headers=headers)
                checks.ok(r.status_code == 403, f"{who} can't {method} {path}",
                          f"got {r.status_code}")  # fmt: skip
        # A report is the sender's own, whatever else it says.
        sent = await c.post(report, headers=sam_h, json={
            "choice": "wrong-details", "key": "300", "who": ADMIN["name"], "user": ADMIN["name"],
            "userId": 1, "device": "Ada's TV", "method": "<script>x</script>",
            "audio": "<img src=x>"})  # fmt: skip
        checks.ok(sent.status_code == 200, "Sam reports a problem", f"got {sent.status_code}")
        rows = (await c.get("/api/reports", headers=admin_h)).json()["reports"]
        mine = [x for row in rows if row["key"] == "300" for x in row["reports"]]
        checks.ok(
            len(mine) == 1 and mine[0]["who"] == USER["name"] and "Ada" not in mine[0]["device"],
            "a report is always its sender's, whatever it says", f"got {mine}",
        )  # fmt: skip
        checks.ok("<script" not in json.dumps(rows) and "<img" not in json.dumps(rows),
                  "what an app sends about how it played is never kept as it is")  # fmt: skip
        checks.ok(ctx.broken.keys() == set() and not ctx.scanner.waiting("300"),
                  "a report alone takes nothing off the air")  # fmt: skip
        # Only what someone may see; answered as for what isn't there.
        gone = (await c.post(report, headers=kit_h,
                             json={"choice": "no-sound", "key": "999999"})).json()  # fmt: skip
        for body, what in (({"choice": "no-sound", "key": "301"}, "a movie their level hides"),
                           ({"choice": "no-sound", "key": "211"}, "an episode their level hides"),
                           ({"choice": "no-sound", "key": "110"}, "a show their level hides")):  # fmt: skip
            r = await c.post(report, headers=kit_h, json=body)
            checks.ok(r.status_code == 404 and r.json() == gone,
                      f"the Kid reporting {what} is answered as though it weren't there",
                      f"got {r.status_code}")  # fmt: skip
        nowhere = (await c.post(report, headers=kit_h,
                                json={"choice": "no-sound", "station": 77})).json()  # fmt: skip
        r = await c.post(report, headers=kit_h, json={"choice": "no-sound", "station": 5})
        checks.ok(r.status_code == 404 and r.json() == nowhere,
                  "the Kid reporting a station their level hides is answered as for none",
                  f"got {r.status_code}")  # fmt: skip
        # The choices are the server's; everything sent is bounded.
        for body, wanted in (
            ({"choice": "it's broken", "key": "300"}, 400), ({"choice": "x" * 41, "key": "300"}, 400),
            ({"choice": "No sound", "key": "300"}, 400), ({"choice": "no-sound"}, 400),
            ({"choice": "no-sound", "key": "300", "station": 3}, 400),
            ({"choice": "no-sound", "key": "x" * 21}, 400),
            ({"choice": "no-sound", "key": "..%2f..%2fetc"}, 404),
            ({"choice": "no-sound", "station": 0}, 400), ({"choice": "no-sound", "station": -3}, 400),
            ({"choice": "no-sound", "station": 10**7}, 400),
            ({"choice": "no-sound", "key": "300", "positionMs": -1}, 400),
            ({"choice": "no-sound", "key": "300", "positionMs": 2**63}, 400),
            ({"choice": "no-sound", "key": "300", "version": "v" * 41}, 400),
            ({"choice": "no-sound", "key": "300", "audio": "a" * 41}, 400),
            ({"choice": "no-sound", "key": "300", "method": "m" * 21}, 400),
        ):  # fmt: skip
            r = await c.post(report, headers=kit_h, json=body)
            said = isinstance(r.json().get("detail"), str) and "Traceback" not in r.text
            checks.ok(r.status_code == wanted and said,
                      f"a report of {str(body)[:60]} is answered {wanted}, plainly",
                      f"got {r.status_code}: {r.text[:80]}")  # fmt: skip
        choices = (await c.get("/api/internal/report-choices", headers=kit_h)).json()["choices"]
        checks.ok(len(choices) == 12, "anyone signed in reads the choices")
        # The limits: one a day per program, ten a day, however many at once.
        many = await asyncio.gather(*(c.post(report, headers=kit_h, json={
            "choice": "no-picture", "key": "3200", "positionMs": n * 1000}) for n in range(6)))  # fmt: skip
        codes = [r.status_code for r in many]
        checks.ok(codes.count(200) == 1 and codes.count(429) == 5,
                  "many reports on one program at once: one is taken", f"got {codes}")  # fmt: skip
        many = await asyncio.gather(*(c.post(report, headers=kit_h, json={
            "choice": "wrong-details", "key": f"32{n:02d}"}) for n in range(1, 12)))  # fmt: skip
        codes = [r.status_code for r in many]
        checks.ok(codes.count(200) == 9 and codes.count(429) == 2,
                  "many reports at once can't beat ten a day", f"got {codes}")  # fmt: skip
        # Turned off for someone: refused, and they can't turn it on themselves.
        users = {u["name"]: u for u in (await c.get("/api/access/users", headers=admin_h)).json()}
        sam = users[USER["name"]]
        await c.put(f"/api/access/users/{sam['id']}", headers=admin_h, json={"canReport": False})
        r = await c.post(report, headers=sam_h, json={"choice": "no-sound", "key": "201"})
        checks.ok(r.status_code == 403, "someone an Admin turned reporting off for can't report",
                  f"got {r.status_code}")  # fmt: skip
        r = await c.put(f"/api/access/users/{sam['id']}", headers=sam_h, json={"canReport": True})
        checks.ok(r.status_code == 403, "a User can't turn reporting back on for themselves",
                  f"got {r.status_code}")  # fmt: skip
        # An Admin acts on them.
        r = await c.post("/api/reports/300/dismiss", headers=admin_h)
        checks.ok(r.status_code == 200, "an Admin dismisses a report", f"got {r.status_code}")


async def _broken_files(
    checks: Checks, app, fp: LibraryPlex, home: str, admin_h: dict, sam_h: dict, kit_h: dict
) -> None:
    """1.30.0's one process for every file, as a bad actor, a confused Admin
    or a failing network would try it: trouble is checked only from one's
    own playing, and only for a problem just now; a broken file a level
    hides is answered as any hidden one; the apps' trouble can't crowd out
    people's reports; Retry and the tab's choices take only what they should;
    and Plex or Radarr away is said plainly, changing nothing."""
    checks.section("The Broken files list, as Media has it")
    ctx = app.state.ctx
    problem = "/api/internal/problem"
    trouble = {"kind": "library-failed", "title": "Cartoon 6", "deviceName": "Attack"}
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        played = (await c.post("/api/internal/play", headers=sam_h,
                               json={"key": "3205", "device": TV})).json()  # fmt: skip
        session = played.get("session")
        for who, h in (("The Kid", kit_h), ("An Admin", admin_h)):
            r = await c.post(problem, headers=h, json={**trouble, "session": session})
            checks.ok(r.status_code == 200 and not ctx.scanner.waiting("3205"),
                      f"{who} saying Sam's playing had trouble has nothing checked",
                      f"got {r.status_code}")  # fmt: skip
        late = int(time.time() * 1000) - 30 * 60_000
        r = await c.post(problem, headers=sam_h, json={**trouble, "at": late})
        checks.ok(r.status_code == 200 and not ctx.scanner.waiting("3205"),
                  "a problem sent half an hour later isn't taken for what was played since",
                  f"got {r.status_code}")  # fmt: skip
        r = await c.post(problem, headers=sam_h, json={**trouble, "session": session})
        checks.ok(
            ctx.scanner.waiting("3205") and ctx.broken.keys() == set(),
            "Sam's own trouble has the file checked first, and takes nothing off the air",
        )
        # The apps' trouble can't crowd out people's reports.
        r = await c.post("/api/internal/report-problem", headers=admin_h,
                         json={"choice": "no-sound", "key": "3207", "positionMs": 60_000})  # fmt: skip
        reported = [t.key for t in ctx.scanner._targets if t.reports]
        most = scanner.TARGETS_MOST
        scanner.TARGETS_MOST = len(ctx.scanner._targets)
        try:
            for key in ("3208", "3209", "3210"):
                played = (await c.post("/api/internal/play", headers=sam_h,
                                       json={"key": key, "device": TV})).json()  # fmt: skip
                await c.post(problem, headers=sam_h,
                             json={**trouble, "session": played.get("session")})  # fmt: skip
        finally:
            scanner.TARGETS_MOST = most
        checks.ok("3207" in reported and all(ctx.scanner.waiting(k) for k in reported),
                  "a flood of the apps' trouble can't push people's reports out of the queue",
                  reported)  # fmt: skip
        # What's broken, where a level hides it: as though it weren't there.
        heist = await c.get("/api/internal/items/301", headers=admin_h)
        item = Item(0, 0, 100 * 60_000, "301", "movie", "Heist", file_path="/m/heist.mkv",
                    library="2")  # fmt: skip
        ctx.broken.record(item, "Check: the file can't be opened", None)
        gone = (await c.get("/api/internal/items/999999", headers=kit_h)).json()
        for what, r in (
            ("its details", await c.get("/api/internal/items/301", headers=kit_h)),
            ("playing it", await c.post("/api/internal/play", headers=kit_h,
                                        json={"key": "301", "device": TV})),
        ):  # fmt: skip
            checks.ok(r.status_code == 404 and r.json() == gone,
                      f"the Kid asking for {what}, broken and hidden, is answered as for nothing",
                      f"got {r.status_code}")  # fmt: skip
        r = await c.post("/api/internal/play", headers=admin_h, json={"key": "301", "device": TV})
        checks.ok(heist.status_code == 200 and r.status_code == 422
                  and r.json().get("detail") == applibrary.ON_THE_LIST,
                  "an Admin asking to play it is told, plainly", f"got {r.status_code}")  # fmt: skip
        versions = (await c.get("/api/internal/items/301", headers=admin_h)).json()["versions"]
        checks.ok([v["problem"] for v in versions] == ["broken"],
                  "its details say what was found", versions)  # fmt: skip
        # Retry takes only the file it names.
        ctx.broken.record(item, "Check: no sound anywhere in it", None, version="30101")
        for path in ("/api/broken/..%2f..%2fetc", "/api/broken/301%3A99", "/api/broken/%00"):
            r = await c.delete(path, headers=admin_h)
            checks.ok(r.status_code == 404, f"DELETE {path} takes nothing off the list",
                      f"got {r.status_code}")  # fmt: skip
        r = await c.delete("/api/broken/301%3A30101", headers=admin_h)
        checks.ok(r.status_code == 204 and ctx.broken.keys() == {"301"},
                  "Retry for one version takes it alone off the list", f"got {r.status_code}")  # fmt: skip
        ctx.broken.remove("301")
        # A confused Admin: answered plainly, nothing changed.
        await c.post("/api/internal/report-problem", headers=admin_h,
                     json={"choice": "wrong-details", "key": "3206"})  # fmt: skip
        for path, wanted in (("/api/reports/3206/replace", 400), ("/api/reports/3206/better", 400),
                             ("/api/reports/3206/dismiss", 200), ("/api/reports/3206/dismiss", 404),
                             ("/api/reports/..%2f3206/dismiss", 404)):  # fmt: skip
            r = await c.post(path, headers=admin_h)
            checks.ok(r.status_code == wanted and isinstance(r.json().get("detail", ""), str),
                      f"POST {path} is answered {wanted}, plainly", f"got {r.status_code}")  # fmt: skip
        # A failing network: Plex away, or Radarr. Said plainly; nothing kept
        # or changed.
        fp.down = True
        try:
            r = await c.post("/api/internal/report-problem", headers=admin_h,
                             json={"choice": "no-sound", "key": "390"})  # fmt: skip
        finally:
            fp.down = False
        rows = (await c.get("/api/reports", headers=admin_h)).json()["reports"]
        checks.ok(r.status_code == 503 and isinstance(r.json().get("detail"), str)
                  and not any(row["key"] == "390" for row in rows),
                  "with Plex away, a report is refused plainly and nothing's kept",
                  f"got {r.status_code}")  # fmt: skip
        await c.post("/api/internal/report-problem", headers=admin_h,
                     json={"choice": "wrong-language", "key": "3204"})  # fmt: skip
        dead = {"app": "radarr", "url": "http://127.0.0.1:9", "key": "abc123", "on": True}
        await c.put("/api/arr", headers=admin_h, json=dead)
        try:
            r = await c.post("/api/reports/3204/better", headers=admin_h)
        finally:
            await c.put("/api/arr", headers=admin_h, json={**dead, "on": False})
        rows = {row["key"]: row for row in (await c.get("/api/reports", headers=admin_h)).json()[
            "reports"]}  # fmt: skip
        checks.ok(r.status_code == 503 and isinstance(r.json().get("detail"), str)
                  and rows.get("3204", {}).get("state") == "waiting",
                  "with Radarr away, Find a better copy is refused plainly, and the report waits",
                  f"got {r.status_code}")  # fmt: skip


async def _converted_on_request(checks: Checks, app, home: str, admin_h: dict, kit_h: dict) -> None:
    """A converted copy an app asks for: never of what a level hides; a
    sentence for an app that can't take one; and however many devices ask at
    once, no more converted than the limit."""
    checks.section("Converted copies on request")
    phone = {**TV, "hls": ["ts"]}
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        gone = (await c.get("/api/internal/items/999999", headers=kit_h)).json()
        hidden = await c.post("/api/internal/play", headers=kit_h,
                              json={"key": "211", "device": phone, "convert": True})  # fmt: skip
        checks.ok(hidden.status_code == 404 and hidden.json() == gone,
                  "the Kid asking for a converted copy of what their level hides gets nothing",
                  f"got {hidden.status_code}")  # fmt: skip
        no_hls = await c.post("/api/internal/play", headers=admin_h,
                              json={"key": "300", "device": TV, "convert": True})  # fmt: skip
        checks.ok(no_hls.status_code == 422 and isinstance(no_hls.json().get("detail"), str),
                  "asked for by an app that can't take one: 422, with a sentence",
                  f"got {no_hls.status_code}")  # fmt: skip
        for odd in ("yes please", 2, None, [True]):
            r = await c.post("/api/internal/play", headers=admin_h,
                             json={"key": "300", "device": phone, "convert": odd})  # fmt: skip
            checks.ok(r.status_code in (200, 400) and "Traceback" not in r.text,
                      f"convert={odd!r} is taken or refused plainly", f"got {r.status_code}")  # fmt: skip
            if r.status_code == 200:
                await c.post(r.json()["leave"])

    # Five apps, each signed in on its own (a device is its sign-in), ask at
    # once: no more converted than the limit.
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        tokens = [
            (await c.post("/api/internal/sign-in", json={**ADMIN, "app": f"Phone {n}"})).json()["token"]
            for n in range(5)
        ]  # fmt: skip

        async def ask(token: str) -> httpx.Response:
            return await c.post("/api/internal/play", headers={"Authorization": f"Bearer {token}"},
                                json={"key": "300", "device": phone, "convert": True})  # fmt: skip

        answers = await asyncio.gather(*(ask(t) for t in tokens))
    made = [r for r in answers if r.status_code == 200]
    busy = [r for r in answers if r.status_code == 503]
    checks.ok(
        len(made) == applibrary.CONVERTING_MOST and len(made) + len(busy) == len(answers)
        and all(r.json()["why"][0] == applibrary.ASKED_WHY for r in made),
        f"five devices asking at once: {applibrary.CONVERTING_MOST} converted, the rest told to "
        "try again later",
        [r.status_code for r in answers],
    )  # fmt: skip
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        for r in made:
            await c.post(r.json()["leave"])


async def _no_file_names(checks: Checks, home: str, admin_h: dict) -> None:
    """Nothing an app receives names a file or a folder, even for an Admin:
    details, versions and tracks, play answers, alerts, refusals."""
    checks.section("No file names in the apps")
    phone = {**TV, "hls": ["ts"]}
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        answers = [
            await c.get("/api/internal/items/300", headers=admin_h),
            await c.get("/api/internal/items/201", headers=admin_h),
            await c.get("/api/internal/home", headers=admin_h),
            await c.get("/api/internal/alerts", headers=admin_h),
            await c.get("/api/v1/stations", headers=admin_h),
            await c.get("/api/v1/guide", headers=admin_h),
            await c.post("/api/internal/play", headers=admin_h, json={"key": "300", "device": TV}),
            await c.post("/api/internal/play", headers=admin_h,
                         json={"key": "300", "device": phone, "convert": True}),
            await c.post("/api/internal/play", headers=admin_h,
                         json={"key": "300", "device": {**TV, "audio": []}}),
        ]  # fmt: skip
        for r in answers:
            if r.status_code == 200 and "leave" in r.text:
                await c.post(r.json()["leave"])
            text = f"{r.headers} {r.text}"
            checks.ok(
                not any(name in text for name in ("picnic.mkv", "/m/", "/tv/p/", "/tv/n/")),
                f"{r.request.method} {r.request.url.path} names no file",
                text[:200],
            )


async def _several_files(
    checks: Checks,
    app,
    home: str,
    admin_h: dict,
    sam_h: dict,
    kit_h: dict,
    fp: LibraryPlex,
) -> None:
    """A movie in several files, played as one: never what a level hides;
    its files never named; one copy within its whole length, however it's
    asked for; an app that can't take one told plainly; an address from
    the library that isn't a path on Plex never asked for with its token;
    and its entry on the Broken files list, Retry, only an Admin's."""
    checks.section("A movie in several files")
    phone = {**TV, "hls": ["ts"]}
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        gone = (await c.get("/api/internal/items/999999", headers=kit_h)).json()
        hidden = await c.post("/api/internal/play", headers=kit_h,
                              json={"key": "341", "device": phone})  # fmt: skip
        checks.ok(hidden.status_code == 404 and hidden.json() == gone,
                  "the Kid playing a movie in several files their level hides gets nothing",
                  f"got {hidden.status_code}")  # fmt: skip
        played = await c.post(
            "/api/internal/play", headers=sam_h,
            json={"key": "340", "device": phone, "startMs": 80 * 60_000},
        )  # fmt: skip
        answer = played.json() if played.status_code == 200 else {}
        checks.ok(
            played.status_code == 200 and answer.get("durationMs") == 120 * 60_000
            and answer.get("why", [""])[0] == "its 2 files, played as one",
            "played as one program, its length the whole", f"got {played.status_code}",
        )  # fmt: skip
        checks.ok("feast-cd" not in played.text and "/m/" not in played.text,
                  "the play answer names neither of its files", played.text[:200])  # fmt: skip
        if answer:
            listed = await c.get(f"{home}{answer['url']}")
            pieces = [ln for ln in listed.text.splitlines() if ln.startswith("piece-")]
            for n in (len(pieces), len(pieces) + 5, -1, 10**9):
                r = await c.get(f"{home}{answer['url'].rsplit('/', 1)[0]}/piece-{n}.ts")
                checks.ok(r.status_code in (404, 422), f"piece {n}, past either file: none",
                          f"got {r.status_code}")  # fmt: skip
            far = await c.post("/api/internal/progress", headers=sam_h, json={
                "key": "340", "positionMs": 120 * 60_000 + 11 * 60_000,
                "session": answer["session"], "sequence": 1})  # fmt: skip
            checks.ok(far.status_code == 400, "a place past the end of the whole is refused",
                      f"got {far.status_code}")  # fmt: skip
            within = await c.post("/api/internal/progress", headers=sam_h, json={
                "key": "340", "positionMs": 100 * 60_000, "session": answer["session"],
                "sequence": 2})  # fmt: skip
            checks.ok(within.status_code == 200 and within.json()["watched"] is False,
                      "a place in its second file is a place in the movie, not its end",
                      within.text[:120])  # fmt: skip
            await c.post(f"{home}{answer['leave']}")
        old = await c.post("/api/internal/play", headers=sam_h, json={"key": "340", "device": TV})
        checks.ok(
            old.status_code == 422 and old.json().get("why") == ["it's in 2 files"]
            and isinstance(old.json().get("detail"), str),
            "an app that can't take a copy is told why, plainly", f"got {old.status_code}",
        )  # fmt: skip
        before = list(fp.requests)
        odd = await c.post("/api/internal/play", headers=sam_h,
                           json={"key": "342", "device": phone})  # fmt: skip
        asked = [r for r in fp.requests[len(before) :] if "evil" in r]
        checks.ok(odd.status_code == 503 and isinstance(odd.json().get("detail"), str)
                  and not asked,
                  "a file whose address isn't a path on Plex: never asked for, said plainly",
                  f"got {odd.status_code}, asked {asked}")  # fmt: skip
        item = Item(0, 0, 120 * 60_000, "340", "movie", "Feast", year=2000,
                    file_path="/m/feast-cd1.mkv")  # fmt: skip
        app.state.ctx.broken.record(item, "Check: it has no sound track", None, "/m/feast-cd2.mkv",
                                    1000, problem="damaged", part=(2, 2))  # fmt: skip
        alerts = (await c.get("/api/internal/alerts", headers=admin_h)).text
        checks.ok("feast-cd2" not in alerts and "/m/" not in alerts,
                  "an Admin's alert about it names no file", alerts[:200])  # fmt: skip
        retried = await c.delete("/api/broken/340", headers=sam_h)
        checks.ok(retried.status_code in (401, 403) and app.state.ctx.broken.entry("340"),
                  "Retry on it is an Admin's alone", f"got {retried.status_code}")  # fmt: skip
        retried = await c.delete("/api/broken/340", headers=admin_h)
        record = app.state.ctx.db.scan("340/part2")
        checks.ok(retried.status_code == 204 and app.state.ctx.broken.entry("340") is None
                  and (record is None or record.kept),
                  "an Admin's Retry puts back the file it's about",
                  f"got {retried.status_code}")  # fmt: skip


async def _problems_sent_later(
    checks: Checks, app, home: str, net: str, admin_h: dict, sam_h: dict, kit_h: dict
) -> None:
    """Problems with when they happened and the app's journal: only someone
    signed in sends one, only an Admin reads a journal, anything sent is
    kept as text and within its bounds, and a backlog of old ones can't get
    past the limits."""
    checks.section("Problems sent later, with their journals")
    script = "<img src=x onerror=alert(1)><script>alert(2)</script>"
    async with httpx.AsyncClient(base_url=net, headers={"X-Forwarded-Proto": "https"}) as out:
        r = await out.post("/api/internal/problem", json={"kind": "unreachable", "journal": script})
        checks.ok(r.status_code == 401, "an outsider can't send a problem", f"got {r.status_code}")
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        started = time.monotonic()
        big = "\n".join([script] * 40_000)  # (about 2 MB)
        r = await c.post("/api/internal/problem", headers=kit_h, json={
            "kind": "unreachable", "detail": f"No network on this device {script}",
            "lastedMs": 10**20, "at": 2**63, "journal": big, "deviceName": "Kit's tablet"})  # fmt: skip
        checks.ok(r.status_code == 200 and time.monotonic() - started < 5,
                  "a huge journal, an odd time and an odd length are taken quickly",
                  f"got {r.status_code} in {time.monotonic() - started:.1f}s")  # fmt: skip
        listed = (await c.get("/api/problems", headers=admin_h)).json()["problems"]
        mine = next((p for p in listed if p["kind"] == "unreachable"), None)
        checks.ok(mine is not None and abs(mine["lastMs"] - time.time() * 1000) < 60_000
                  and "for " not in mine["label"],
                  "a time too far ahead is taken as now, and a length past belief left out",
                  mine and mine["label"])  # fmt: skip
        journal_id = mine and mine["journal"]
        for who, h, wanted in (("the Kid", kit_h, 403), ("a User", sam_h, 403)):
            r = await c.get(f"/api/problems/{journal_id}/journal", headers=h)
            checks.ok(
                r.status_code == wanted, f"{who} can't read a journal", f"got {r.status_code}"
            )
        r = await c.get(f"/api/problems/{journal_id}/journal", headers=admin_h)
        lines = r.json().get("lines", []) if r.status_code == 200 else []
        checks.ok(r.status_code == 200 and len("\n".join(lines).encode()) <= problems.JOURNAL_MOST
                  and lines[-1] == script,
                  "an Admin reads it: its newest lines, within 8 KB, as text",
                  f"got {r.status_code}")  # fmt: skip
        for path in ("/api/problems/abc/journal", "/api/problems/99999999999999999999/journal",
                     "/api/problems/-1/journal"):  # fmt: skip
            r = await c.get(path, headers=admin_h)
            checks.ok(r.status_code in (400, 404, 422), f"GET {path} is refused plainly",
                      f"got {r.status_code}")  # fmt: skip
        page = await _page_code(c)
        shown = page[page.index("function journalOf") :][:800]
        checks.ok("textContent" in shown and "innerHTML" not in shown,
                  "the page shows a journal as text, never as HTML")  # fmt: skip
        for at in (-5, "soon", 1.5, [1], 10**400):
            r = await c.post("/api/internal/problem", headers=kit_h,
                             json={"kind": "crashed", "at": at, "deviceName": f"odd {at!r}"[:40]})  # fmt: skip
            checks.ok(r.status_code in (200, 400) and "Traceback" not in r.text,
                      f"at={str(at)[:20]!r} is taken or refused plainly", f"got {r.status_code}")  # fmt: skip
        # A backlog from one device, a week old: the limit still holds.
        week_ago = int(time.time() * 1000) - 6 * 86_400_000
        codes = []
        for n in range(problems.MOST + 5):
            r = await c.post("/api/internal/problem", headers=kit_h, json={
                "kind": "library-failed", "title": f"Old {n}", "at": week_ago + n,
                "deviceName": "Backlog"})  # fmt: skip
            codes.append(r.status_code)
        checks.ok(codes.count(200) == problems.MOST and codes[-1] == 429,
                  "a backlog of old problems from one device can't get past its limit",
                  f"{codes.count(200)} taken")  # fmt: skip


async def _copies_before_updates(checks: Checks, app, home: str, admin_h: dict) -> None:
    """The copies of the database made before an update (sign-ins and all)
    can't be downloaded from the page, by anyone."""
    checks.section("Copies made before an update")
    folder = app.state.ctx.settings.data_dir / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    copy = folder / "before-1.29.1-20261009-120000.db"
    copy.write_bytes(b"SQLite format 3\x00 sign-ins")
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        listed = (await c.get("/api/backups", headers=admin_h)).text
        checks.ok(copy.name not in listed, "the page doesn't list them")
        for name in (copy.name, f"..%2fbackups%2f{copy.name}", "before-1.29.1-*.db"):
            r = await c.get(f"/api/backups/{name}", headers=admin_h)
            checks.ok(r.status_code == 404 and b"sign-ins" not in r.content,
                      f"an Admin can't download {name[:40]}", f"got {r.status_code}")  # fmt: skip
    copy.unlink()


async def _files_like_ffmpegs_words(checks: Checks, app) -> None:
    """A file whose name and tags read like what ffmpeg says as it decodes
    (where it's reading and decoding, how far it's got) can't move where the
    deep scan finds damage, or hide it: what it measures is ffmpeg's own
    lines, as they come."""
    checks.section("A file whose name and tags read like ffmpeg's own words")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("  (not checked: this needs ffmpeg)")
        return
    with tempfile.TemporaryDirectory(prefix="attack-check-files-") as folder:
        clean, damaged, at = await asyncio.to_thread(_files_like_ffmpeg, Path(folder))
        for path, broken in ((clean, False), (damaged, True)):
            got = await scanner.decode_through(
                app.state.ctx, str(path), 0.0, 0, 0, lambda _got: None,
                count_from=scanner.START_GRACE_S, rate=48_000,
            )  # fmt: skip
            name = "the damaged one" if broken else "the clean one"
            checks.ok(abs(got.at - 40) < 2 and abs(got.picture_to - 40) < 2,
                      f"{name}: how far the scan got is the file's own",
                      f"at={got.at} picture_to={got.picture_to}")  # fmt: skip
            if broken:
                checks.ok(bool(got.glitches) and all(abs(t - at) < 2 for _, t in got.glitches),
                          f"{name}: its damage is found where it is ({at:.1f}s)",
                          str(got.glitches))  # fmt: skip
            else:
                checks.ok(got.glitches == [], f"{name}: nothing's found", str(got.glitches))


def _files_like_ffmpeg(folder: Path) -> tuple[Path, Path, float]:
    """A 40-second file named, and tagged, with lines like ffmpeg's; and a
    copy of it scrambled from a picture 20 seconds in. (Both, and the time of
    that picture.)"""
    said = (
        "[vist#0:0 h264 @ 0x1] [info] decoder -> pts:1 pts_time:9000 x\n"
        "[info] demuxer+ffmpeg -> ist_index:0:0 type:audio pkt_pts:1 pkt_pts_time:9000 "
        "pkt_dts:1 pkt_dts_time:9000 x\nout_time_us=9000000000\nframe=90000\nprogress=end\n"
    )
    clean = folder / f"clean\n{said.splitlines()[0]}.mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=s=640x360:r=24,noise=alls=4:allf=t:all_seed=7", "-f", "lavfi",
         "-i", "sine=f=440:sample_rate=48000", "-t", "40", "-c:v", "libx264", "-preset",
         "ultrafast", "-b:v", "1500k", "-c:a", "aac", "-metadata", f"title={said}",
         "-metadata", f"comment={said}", str(clean)],
        check=True,
    )  # fmt: skip
    packets = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
         "packet=pts_time,pos,size", "-of", "json", str(clean)],
        capture_output=True, text=True, check=True,
    ).stdout)["packets"]  # fmt: skip
    at, pos, size = next(
        (float(p["pts_time"]), int(p["pos"]), int(p["size"]))
        for p in packets
        if float(p["pts_time"]) >= 20 and int(p["size"]) >= 1500
    )
    data = bytearray(clean.read_bytes())
    rng = random.Random(1)
    middle = pos + size // 2
    data[middle : middle + 48 * 1024] = bytes(rng.randrange(256) for _ in range(48 * 1024))
    damaged = clean.with_name(clean.name.replace("clean", "damaged"))
    damaged.write_bytes(data)
    return clean, damaged, at


class _Told:
    """Stands in for the web address alerts go to, as tapiOca starts."""

    def __init__(self) -> None:
        self.said: list[tuple] = []

    def send(self, *said) -> None:
        self.said.append(said)


async def _no_license(checks: Checks, home: str, admin_h: dict, sam_h: dict) -> None:
    """The server has no license (the apps are unlocked in their stores):
    no address answers for one, for anyone. (An Admin, who may open any
    address there is, gets 404.)"""
    checks.section("No license on the server")
    paths = (("GET", "/api/internal/license"), ("POST", "/api/internal/license"),
             ("GET", "/api/access/license"), ("PUT", "/api/access/license"))  # fmt: skip
    async with httpx.AsyncClient(headers=PAGE, base_url=home, timeout=30) as c:
        for who, h, allowed in (
            ("An Admin", admin_h, {404, 405}),
            ("A User", sam_h, {403, 404, 405}),
            ("An outsider", {}, {401, 404, 405}),
        ):
            codes = {
                (await c.request(method, path, headers=h)).status_code for method, path in paths
            }
            checks.ok(codes <= allowed, f"{who} finds no license address", f"got {codes}")


async def _raw_get(base: str, target: str) -> int:
    """The status a GET for `target` gets, sent exactly as written (no
    client tidying its dots or slashes)."""
    host, port = base.removeprefix("http://").split(":")
    reader, writer = await asyncio.open_connection(host, int(port))
    try:
        writer.write(f"GET {target} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), 10)
        return int(line.split()[1])
    finally:
        writer.close()


async def _tuner_access(checks: Checks, home: str, net: str, admin_h: dict, sam_h: dict) -> None:
    checks.section("Tuner access: only listed devices")
    tuner_paths = (
        "/discover.json", "/lineup.json", "/lineup_status.json", "/device.xml", "/xmltv.xml",
        "/guide.xml", "/stations.m3u", "/channels.m3u", "/stream/3", "/auto/v3", "/art/201",
        "/hls/3/index.m3u8", "/hls/3/night/index.m3u8", "/hls/3/live0.ts",
    )  # fmt: skip
    tricks = (
        "/%64iscover.json", "/discover.json?x=1", "/stream/3?x=1", "/hls/k/../3/index.m3u8",
        "/hls/kk/3/index.m3u8", "/hls/./3/index.m3u8", "/hls/%6b/../3/index.m3u8",
        "/./discover.json", "/stream/%33",
    )  # fmt: skip
    async with httpx.AsyncClient(headers=PAGE, base_url=home, timeout=30) as c:
        r = await c.put("/api/tuner", json={"only": False, "devices": []}, headers=sam_h)
        checks.ok(r.status_code == 403, "A User can't change Tuner access", f"got {r.status_code}")
        r = await c.post("/api/tuner/allow", json={"address": "127.0.0.1"}, headers=sam_h)
        checks.ok(r.status_code == 403, "A User can't allow a device", f"got {r.status_code}")
        r = await c.get("/api/tuner")
        checks.ok(r.status_code in (401, 403), "No one signed out sees Tuner access",
                  f"got {r.status_code}")  # fmt: skip
        r = await c.put("/api/tuner", json={"only": True, "devices": [{"address": "10.9.9.9"}]},
                        headers=admin_h)  # fmt: skip
        checks.ok(r.status_code == 200, "An Admin lists only another device", r.text[:200])
        for path in tuner_paths:
            r = await c.get(path)
            checks.ok(r.status_code == 403, f"{path} is refused to an unlisted device",
                      f"got {r.status_code}")  # fmt: skip
        for target in tricks:
            code = await _raw_get(home, target)
            checks.ok(code in (403, 404), f"{target} gets nothing of the tuner", f"got {code}")
        [station] = (await c.get("/api/v1/stations", headers=sam_h)).json()["stations"][:1]
        own = station["hls"]
        checks.ok(own.startswith("/hls/k/"), "A signed-in app at home gets its own address", own)
        r = await c.get(own.replace("index.m3u8", "logo.png"))
        checks.ok(r.status_code == 200, "Its own address works at home", f"got {r.status_code}")
    async with httpx.AsyncClient(base_url=net, timeout=30, headers=_cf("203.0.113.9")) as out:
        r = await out.get(own.replace("index.m3u8", "logo.png"))
        checks.ok(r.status_code == 404, "A home address is no good from the internet",
                  f"got {r.status_code}")  # fmt: skip
        for path in ("/discover.json", "/stream/3", "/hls/3/index.m3u8"):
            r = await out.get(path)
            checks.ok(r.status_code == 404, f"{path} still isn't on the public port",
                      f"got {r.status_code}")  # fmt: skip
    async with httpx.AsyncClient(headers=PAGE, base_url=home, timeout=30) as c:
        r = await c.post("/api/tuner/allow", json={"address": "127.0.0.1"}, headers=admin_h)
        checks.ok(r.status_code == 200, "An Admin allows this device", r.text[:200])
        r = await c.get("/discover.json")
        checks.ok(r.status_code == 200, "Allowed, it uses the tuner", f"got {r.status_code}")
        await c.put("/api/tuner", json={"only": False, "devices": []}, headers=admin_h)


TUNER_PATHS = ("/discover.json", "/lineup.json", "/xmltv.xml", "/stations.m3u", "/stream/3",
               "/hls/3/index.m3u8", "/art/201")  # fmt: skip


async def _doors_and_trust(
    checks: Checks, app, home: str, net: str, admin_h: dict, device_key: str
) -> None:
    ctx = app.state.ctx
    port = home.rsplit(":", 1)[1]

    def peer(address: str, **more: str) -> dict[str, str]:
        return {"X-Attack-Peer": address, **more}

    async def gives(c: httpx.AsyncClient, h: dict[str, str]) -> str | None:
        """What a trusted network gives an app from here, or None. (From
        1.38.0 the page is told only of a network that signs in as someone:
        a network's Who's tuning in? is the apps'.)"""
        r = await c.post("/api/internal/trusted", headers=h,
                         json={"app": "tapiOca for Roku", "picker": True})  # fmt: skip
        return r.json().get("gives") if r.is_success else None

    async def internet_like(c: httpx.AsyncClient, what: str, h: dict[str, str]) -> None:
        """What the public port gives, and no more: no tuner, no PIN, no
        at-home picker list, signing in asked for."""
        for path in TUNER_PATHS:
            r = await c.get(path, headers=h)
            checks.ok(r.status_code == 404, f"{what}: {path} gets nothing", f"got {r.status_code}")
        r = await c.get("/api/status", headers=h)
        checks.ok(r.status_code == 401, f"{what}: the API asks to sign in", f"got {r.status_code}")
        r = await c.post("/api/access/pin-sign-in", json={"pin": "4321"}, headers=h)
        checks.ok(r.status_code == 404, f"{what}: no PIN sign-in", f"got {r.status_code}")
        r = await c.get("/api/internal/picker", headers={**h, "StationPlay-Device": device_key})
        listed = [p["name"] for p in r.json().get("people", [])] if r.is_success else []
        checks.ok("Kit" not in listed, f"{what}: no at-home picker list", str(listed))
        r = await c.get("/api/access/me", headers=h)
        checks.ok(r.json().get("outside") is True and "trusted" not in r.json(),
                  f"{what}: the page says it's from the internet", r.text[:200])  # fmt: skip

    checks.section("Doors left open (1.36.0)")
    async with httpx.AsyncClient(headers=PAGE, base_url=home, timeout=30) as c:
        # Door 1: the home port forwarded on the router (IPv4, mapped, IPv6).
        for address in ("203.0.113.9", "::ffff:203.0.113.9", "2001:db8::9"):
            await internet_like(c, f"door 1 from {address}", peer(address))
        # Door 1b: a home device asking for tapiOca by an internet address.
        await internet_like(c, "door 1b", peer("192.168.1.9", Host=f"203.0.113.50:{port}"))
        # Door 2: a device that isn't a trusted proxy, naming the internet
        # (or what can't be read) in any forwarding header.
        for name, value in (
            ("X-Forwarded-For", "203.0.113.5"), ("X-Real-IP", "203.0.113.5"),
            ("CF-Connecting-IP", "203.0.113.5"), ("True-Client-IP", "203.0.113.5"),
            ("Forwarded", 'for="203.0.113.5:443"'), ("Forwarded", 'for="[2001:db8::5]:443"'),
            ("Forwarded", "for=unknown"), ("Forwarded", "for=_hidden"), ("X-Forwarded-For", "x"),
        ):  # fmt: skip
            r = await c.get("/discover.json", headers=peer("192.168.1.5", **{name: value}))
            checks.ok(r.status_code == 404, f"door 2 ({name}: {value}) gets no tuner",
                      f"got {r.status_code}")  # fmt: skip
        codes = []
        for n in range(6):
            r = await c.post("/api/access/sign-in", json={"name": "Ada", "password": "wrong"},
                             headers=peer("192.168.1.5", **{"X-Forwarded-For": f"203.0.113.{n + 1}"}))  # fmt: skip
            codes.append(r.status_code)
        checks.ok(
            codes[-1] == 429, "door 2: a new forwarded address each try gains nothing", str(codes)
        )
        ctx.alerts.doors(ctx.doors, open_=False, home_port=int(port), public_port=1)
        now = [a for a in ctx.alerts.now() if a.kind == "access"]
        checks.ok({"home-port", "proxy"} <= {a.about for a in now}, "doors 1 and 2 are Admin alerts",
                  str([a.about for a in now]))  # fmt: skip
        checks.ok(not any("203.0.113" in a.sentence or "192.168.1." in a.sentence for a in now),
                  "the alerts never give an address", str([a.sentence for a in now])[:200])  # fmt: skip

    checks.section("Trusted networks (1.36.0)")
    async with httpx.AsyncClient(headers=PAGE, base_url=home, timeout=30) as c:
        # Door 4: what can't be trusted.
        for bad in ("0.0.0.0/0", "::/0", "8.8.8.0/24", "2001:db8::/64", "127.0.0.0/8",
                    "fe80::1%eth0", "::ffff:192.168.1.0/120", "192.168.1.0/24 x"):  # fmt: skip
            r = await c.put(
                "/api/access/trusted", json={"entries": [{"network": bad}]}, headers=admin_h
            )
            checks.ok(r.status_code == 400, f"{bad} can't be trusted", f"got {r.status_code}")
        many = [{"network": f"10.0.{n}.0/24"} for n in range(51)]
        r = await c.put("/api/access/trusted", json={"entries": many}, headers=admin_h)
        checks.ok(r.status_code in (400, 422), "a 51st network is refused", f"got {r.status_code}")
        ada = next(u for u in ctx.db.users() if u.name == "Ada")
        sam = next(u for u in ctx.db.users() if u.name == "Sam")
        r = await c.put("/api/access/trusted", json={"entries": [
            {"network": "192.168.1.0/24", "gives": "person", "person": ada.id}]}, headers=admin_h)  # fmt: skip
        checks.ok(
            r.status_code == 400,
            "an Admin is never signed in on a whole network",
            f"got {r.status_code}",
        )
        r = await c.put(
            "/api/access/trusted",
            json={"entries": [{"network": "192.168.0.0/16"}]},
            headers=admin_h,
        )
        checks.ok(
            r.status_code == 409, "a network wider than a home's asks first", f"got {r.status_code}"
        )
        r = await c.put("/api/access/trusted", json={"entries": []})
        checks.ok(
            r.status_code in (401, 403), "no one signed out lists networks", f"got {r.status_code}"
        )
        entries = [
            {"network": "192.168.1.0/24", "label": "Home", "gives": "picker"},
            {"network": "192.168.1.44", "gives": "person", "person": ada.id},
            {"network": "192.168.1.70", "gives": "person", "person": sam.id},
            {"network": "172.16.0.0/12", "gives": "picker"},
        ]
        r = await c.put(
            "/api/access/trusted", json={"entries": entries, "confirmWide": True}, headers=admin_h
        )
        checks.ok(r.status_code == 200, "an Admin lists trusted networks", r.text[:200])
        got = await gives(c, peer("192.168.1.60"))
        checks.ok(got == "picker", "a device on the network: Who's tuning in?", str(got))
        me = (await c.get("/api/access/me", headers=peer("192.168.1.60"))).json()
        checks.ok(me.get("trusted") == {"gives": "picker"} and "people" not in me,
                  "the page there lists no one who hasn't signed in on it (1.38.0)",
                  str(me)[:200])  # fmt: skip
        # Not trusted: another VLAN, the public port, a trusted /32's
        # neighbor, an internet name (door 3), headers from a device that
        # isn't a trusted proxy (even claiming the Admin's laptop).
        for what, h in (
            ("another VLAN", peer("192.168.20.5")),
            ("an internet name (door 3)", peer("192.168.1.60", Host="nas.example.net")),
            ("a LAN device claiming the Admin's laptop", peer("192.168.1.61", **{"X-Forwarded-For": "192.168.1.44"})),
            ("a LAN device claiming it in X-Real-IP", peer("192.168.1.61", **{"X-Real-IP": "192.168.1.44"})),
        ):  # fmt: skip
            me = (await c.get("/api/access/me", headers=h)).json()
            checks.ok(
                "trusted" not in me or me["trusted"].get("name") != "Ada",
                f"{what}: never the Admin",
                str(me)[:200],
            )
            got = await gives(c, h)
            checks.ok(got != "person", f"{what}: never signed in as someone", str(got))
            if what != "a LAN device claiming it in X-Real-IP":
                checks.ok("trusted" not in me and got is None, f"{what}: not trusted",
                          f"{str(me)[:160]} {got}")  # fmt: skip
        got = await gives(c, peer("192.168.1.45"))
        checks.ok(
            got == "picker",
            "the Admin's laptop's neighbor gets only its network's choice",
            str(got),
        )
        # Door 3, fixed: the name listed for home.
        r = await c.put(
            "/api/access/trusted", json={"homeNames": ["nas.example.net"]}, headers=admin_h
        )
        got = await gives(c, peer("192.168.1.60", Host="nas.example.net"))
        checks.ok(got == "picker", "door 3: once listed as a home name, trusted", str(got))
        # (Never the away-from-home address's name, even listed: that's how
        # the internet reaches tapiOca.)
        await c.put(
            "/api/access/trusted",
            json={"homeNames": ["nas.example.net", "tv.example.com"]},
            headers=admin_h,
        )
        got = await gives(c, peer("192.168.1.60", Host="tv.example.com"))
        checks.ok(got is None, "the away address's name is never home's", str(got))
        # Through the trusted proxy: the visitor's network, never the
        # Admin's laptop, and nothing when its headers disagree.
        got = await gives(c, peer(PROXY_PEER, **{"X-Forwarded-For": "192.168.1.44"}))
        checks.ok(got == "picker", "through a proxy, never the Admin's laptop", str(got))
        me = (
            await c.get(
                "/api/access/me", headers=peer(PROXY_PEER, **{"X-Forwarded-For": "192.168.1.70"})
            )
        ).json()
        got = await gives(c, peer(PROXY_PEER, **{"X-Forwarded-For": "192.168.1.70"}))
        checks.ok(
            got == "person" and me.get("trusted") == {"gives": "person"},
            "through a proxy, a User's device as listed (the page never told who)",
            f"{str(me)[:160]} {got}",
        )
        me = (
            await c.get(
                "/api/access/me",
                headers=peer(
                    PROXY_PEER, **{"X-Forwarded-For": "192.168.1.70", "X-Real-IP": "192.168.1.60"}
                ),
            )
        ).json()
        got = await gives(c, peer(
            PROXY_PEER, **{"X-Forwarded-For": "192.168.1.70", "X-Real-IP": "192.168.1.60"}
        ))  # fmt: skip
        checks.ok("trusted" not in me and got is None, "a proxy's headers that disagree: nothing",
                  f"{str(me)[:160]} {got}")  # fmt: skip
        # On the public port: never trusted.
        async with httpx.AsyncClient(headers=PAGE, base_url=net, timeout=30) as out:
            me = (
                await out.get("/api/access/me", headers={"X-Forwarded-For": "192.168.1.60"})
            ).json()
            got = await gives(out, {"X-Forwarded-For": "192.168.1.60"})
            checks.ok("trusted" not in me and got is None,
                      "a trusted address on the public port: nothing", f"{str(me)[:160]} {got}")  # fmt: skip
        # A sign-in a network gives works only there; it ends with the entry.
        r = await c.post("/api/access/trusted-sign-in", json={}, headers=peer("192.168.1.70"))
        checks.ok(r.status_code == 200, "Sam's device signs in as Sam", r.text[:200])
        token = r.cookies.get(access.COOKIE) or ""
        checks.ok(
            token.startswith(access.TRUSTED_TOKEN_PREFIX),
            "it's a sign-in of its own kind",
            token[:4],
        )
        ck = {"Cookie": f"{access.COOKIE}={token}"}
        r = await c.get("/api/channels", headers={**peer("192.168.1.70"), **ck})
        checks.ok(r.status_code == 200, "it works there", f"got {r.status_code}")
        for what, h in (
            ("on another network", peer("192.168.1.71")),
            ("on another VLAN", peer("192.168.20.5")),
        ):
            r = await c.get("/api/channels", headers={**h, **ck})
            checks.ok(r.status_code == 401, f"it's no good {what}", f"got {r.status_code}")
        async with httpx.AsyncClient(headers=PAGE, base_url=net, timeout=30) as out:
            r = await out.get("/api/channels", headers={**ck, **_cf("192.168.1.70")})
            checks.ok(
                r.status_code == 401, "it's no good on the public port", f"got {r.status_code}"
            )
        # Made with no PIN or password: no credential that leaves its
        # network (a password, a PIN, an API token, a linked app).
        h = {**peer("192.168.1.70"), **ck}
        for what, method, path, body in (
            ("set a password", "PUT", f"/api/access/users/{sam.id}", {"password": "a plenty long password"}),
            ("set a PIN", "PUT", f"/api/access/users/{sam.id}/picker", {"pin": "0000"}),
            ("link an app", "POST", "/api/access/link", {"code": "ABCD-EFGH"}),
        ):  # fmt: skip
            r = await c.request(method, path, json=body, headers=h)
            checks.ok(
                r.status_code == 403, f"a network's sign-in can't {what}", f"got {r.status_code}"
            )
        import hashlib

        plain = hashlib.sha256(token.encode()).hexdigest()
        checks.ok(ctx.db.session_user(plain, 0) is None, "1.35.0's lookup never finds it", "found")
        kept = [e for e in (await c.get("/api/access/trusted", headers=admin_h)).json()["entries"]
                if e["network"] != "192.168.1.70/32"]  # fmt: skip
        r = await c.put("/api/access/trusted", json={"entries": kept}, headers=admin_h)
        r = await c.get("/api/channels", headers={**peer("192.168.1.70"), **ck})
        checks.ok(r.status_code == 401, "removing its network ends it", f"got {r.status_code}")
        # From 1.38.0 the page has no Who's tuning in? on a network: it signs
        # in no one by a pick, an Admin least of all, with a PIN or without.
        # (Wrong PINs on the page's PIN sign-in: tests/test_pin_sign_in.py.)
        for who, body in (("an Admin", {"id": ada.id}), ("an Admin's PIN", {"id": ada.id, "pin": "1357"}),
                          ("a User", {"id": sam.id}), ("a User's PIN", {"id": sam.id, "pin": "0000"})):  # fmt: skip
            r = await c.post("/api/access/trusted-sign-in", json=body, headers=peer("192.168.1.62"))
            checks.ok(r.status_code == 404 and not r.cookies.get(access.COOKIE),
                      f"the page on a network signs in no one picked ({who})",
                      f"got {r.status_code}")  # fmt: skip

    checks.section("Door 5: Docker hiding where connections come from (1.36.0)")
    async with httpx.AsyncClient(headers=PAGE, base_url=home, timeout=30) as c:
        # Docker's gateway listed as a trusted proxy (a proxy in another
        # container): what it names is never trusted, and wrong passwords
        # at home through it count as it.
        r = await c.put("/api/access/trusted", headers=admin_h,
                        json={"proxies": [{"network": PROXY_PEER}, {"network": GATEWAY}]})  # fmt: skip
        checks.ok(
            r.status_code == 200, "the gateway can be listed (for the public port)", r.text[:200]
        )
        me = (
            await c.get(
                "/api/access/me", headers=peer(GATEWAY, **{"X-Forwarded-For": "192.168.1.60"})
            )
        ).json()
        checks.ok(
            "trusted" not in me,
            "nothing is trusted through the gateway, listed or not",
            str(me)[:200],
        )
        codes = [
            (await c.post("/api/access/sign-in", json={"name": "Ada", "password": "wrong"},
                          headers=peer(GATEWAY, **{"X-Forwarded-For": f"192.168.1.{n + 100}"}))).status_code
            for n in range(6)
        ]  # fmt: skip
        checks.ok(
            codes[-1] == 429,
            "naming a new address each try through the gateway gains nothing",
            str(codes),
        )
        await c.put(
            "/api/access/trusted", json={"proxies": [{"network": PROXY_PEER}]}, headers=admin_h
        )
        ctx.relays.reset()
        me = (await c.get("/api/access/me", headers=peer(GATEWAY))).json()
        checks.ok(
            "trusted" not in me,
            "Docker's gateway, in a trusted 172.16.0.0/12, isn't trusted",
            str(me)[:200],
        )
        me = (await c.get("/api/access/me", headers=peer(OWN))).json()
        checks.ok("trusted" not in me, "nor is tapiOca's own address", str(me)[:200])
        for _ in range(25):
            await c.get("/api/access/me", headers=peer(GATEWAY))
        me = (await c.get("/api/access/me", headers=peer("192.168.1.60"))).json()
        checks.ok(
            "trusted" not in me,
            "with every device hidden, trust is off, even for a trusted device",
            str(me)[:200],
        )
        got = (await c.get("/api/access/trusted", headers=admin_h)).json()
        checks.ok(got["seeing"] == "hidden" and got["you"]["offer"] is None, "the Access tab says so, and offers no network",
                  str(got.get("seeing")))  # fmt: skip
        ctx.alerts.doors(ctx.doors, open_=False, home_port=int(port), public_port=1, hidden=True)
        checks.ok(any(a.about == "hidden" for a in ctx.alerts.now()), "an Admin alert says so", "")
        ctx.relays.reset()

    checks.section("Door 7: Tuner access by network (1.36.0)")
    async with httpx.AsyncClient(headers=PAGE, base_url=home, timeout=30) as c:
        r = await c.put("/api/tuner", json={"only": True, "devices": [],
                        "networks": [{"network": "192.168.1.0/24"}]}, headers=admin_h)  # fmt: skip
        checks.ok(r.status_code == 200, "an Admin lists a network for the tuner", r.text[:200])
        r = await c.get("/discover.json", headers=peer("192.168.1.9"))
        checks.ok(r.status_code == 200, "a device on it uses the tuner", f"got {r.status_code}")
        r = await c.get("/discover.json", headers=peer("192.168.2.9"))
        checks.ok(r.status_code == 403, "a device off it doesn't", f"got {r.status_code}")
        for bad in ("8.8.8.0/24", "0.0.0.0/0"):
            r = await c.put(
                "/api/tuner", json={"only": True, "networks": [{"network": bad}]}, headers=admin_h
            )
            checks.ok(r.status_code == 400, f"the tuner never lists {bad}", f"got {r.status_code}")
        await c.put(
            "/api/tuner", json={"only": False, "devices": [], "networks": []}, headers=admin_h
        )
        await c.put("/api/access/trusted", json={"entries": [], "homeNames": []}, headers=admin_h)


SECRET = b"root:x:0:0:the secret outside the media folder"


async def _from_its_page(checks: Checks, home: str) -> None:
    """A browser at home, over plain http (no Sec-Fetch-Site), sent by
    another site's page: with the Admin's cookie, or with signing in off,
    nothing changes without the header only tapiOca's page sends."""
    checks.section("Changes only from tapiOca's own page (1.36.2)")
    station = {"number": 41, "sources": [{"type": "show", "ratingKey": "100"}]}
    async with httpx.AsyncClient(headers=PAGE, base_url=home, timeout=30) as page:
        signed = await page.post("/api/access/sign-in", json=ADMIN)
        checks.ok(
            signed.status_code == 200, "the Admin signs in on the page", f"got {signed.status_code}"
        )
        async with httpx.AsyncClient(base_url=home, timeout=30, cookies=page.cookies) as other:
            for what, method, path, kw in (
                ("make a station", "POST", "/api/channels", {"json": station}),
                ("by a form", "POST", "/api/channels", {"data": {"number": "41"}}),
                ("add an Admin", "POST", "/api/access/users",
                 {"json": {"name": "Eve", "password": "a plenty long password", "role": "admin"}}),
                ("turn away from home off", "PUT", "/api/away", {"json": {"on": False, "address": ""}}),
                ("sign the Admin out", "POST", "/api/access/sign-out", {}),
                ("make a backup through the API", "POST", "/api/v1/backups", {}),
                ("sign an app in", "POST", "/api/internal/sign-in", {"json": {**ADMIN, "app": "x"}}),
            ):  # fmt: skip
                for origin in ("http://evil.example", None):
                    if origin is None and path.startswith(("/api/v1/", "/api/internal/")):
                        continue  # (apps and scripts send no Origin: see below)
                    h = {"Origin": origin} if origin else {}
                    r = await other.request(method, path, headers=h, **kw)
                    checks.ok(r.status_code == 403, f"another site's page can't {what}"
                              f"{'' if origin else ' (no Origin)'}", f"got {r.status_code}")  # fmt: skip
        me = (await page.get("/api/access/me")).json()
        checks.ok((me.get("user") or {}).get("name") == ADMIN["name"], "the Admin is still signed in",
                  str(me.get("user")))  # fmt: skip
        listed = [c["number"] for c in (await page.get("/api/channels")).json()]
        checks.ok(41 not in listed, "no station was made", str(listed))
    # Apps and scripts: no Origin, their own ways in, nothing changes.
    async with httpx.AsyncClient(base_url=home, timeout=30) as app_:
        r = await app_.post("/api/internal/sign-in", json={**ADMIN, "app": "tapiOca for Roku"})
        checks.ok(r.status_code == 200, "an app signs in as before", f"got {r.status_code}")


async def _one_box(checks: Checks, app, home: str, net: str) -> None:
    """A reverse proxy, Plex and tapiOca on one server (the owner's
    TrueNAS): Plex keeps the tuner however it's laid out, the proxy's
    visitors are who it says, and nothing through it skips signing in."""
    checks.section("One box: a proxy, Plex and tapiOca on one server (1.36.2)")
    ctx = app.state.ctx
    kept_proxies = [
        {"network": x["network"], "label": x.get("label", "")} for x in ctx.trusted.proxies
    ]
    kept_entries = [
        {k: e.get(k) for k in ("network", "label", "gives", "person")} for e in ctx.trusted.entries
    ]
    kept_tuner = (ctx.tuner.only, dict(ctx.tuner.devices), dict(ctx.tuner.networks))
    ctx.tuner.save(False, [])
    port = home.rsplit(":", 1)[1]
    try:
        for layout, proxy, plex in (
            ("in containers, through Docker's gateway", GATEWAY, GATEWAY),
            ("sharing the server's address", "192.168.1.30", "192.168.1.30"),
            ("the proxy with an address of its own", "192.168.1.31", "192.168.1.30"),
        ):
            ctx.trusted.save({
                "entries": [{"network": "192.168.1.0/24", "label": "Home", "gives": "picker"}],
                "proxies": [{"network": PROXY_PEER}, {"network": proxy}],
            }, by=None)  # fmt: skip
            async with httpx.AsyncClient(base_url=home, timeout=30) as c:
                for path in ("/discover.json", "/lineup_status.json", "/lineup.json", "/xmltv.xml"):
                    r = await c.get(
                        path, headers={"X-Attack-Peer": plex, "User-Agent": "PlexMediaServer"}
                    )
                    checks.ok(
                        r.status_code == 200, f"{layout}: Plex gets {path}", f"got {r.status_code}"
                    )
                r = await c.post("/lineup.post?scan=start", headers={"X-Attack-Peer": plex})
                checks.ok(r.status_code == 200, f"{layout}: Plex scans", f"got {r.status_code}")
                # The proxy's own computer, naming nobody: home, never trusted.
                me = (await c.get("/api/access/me", headers={"X-Attack-Peer": proxy})).json()
                checks.ok("trusted" not in me, f"{layout}: the proxy's computer never skips signing in",
                          str(me.get("trusted")))  # fmt: skip
                # Pointed at the home port by mistake, naming the internet.
                visitor = {"X-Attack-Peer": proxy, "X-Forwarded-For": "203.0.113.9",
                           "X-Forwarded-Proto": "https"}  # fmt: skip
                r = await c.get("/discover.json", headers=visitor)
                checks.ok(r.status_code == 404, f"{layout}: the internet through the home port gets no tuner",
                          f"got {r.status_code}")  # fmt: skip
                # Naming a home address from outside: never trusted.
                r = await c.get("/api/access/me", headers={**visitor, "X-Forwarded-For": "192.168.1.60",
                                                            "Host": f"tv.example.com:{port}"})  # fmt: skip
                checks.ok("trusted" not in r.json(), f"{layout}: a home address named from outside isn't trusted",
                          r.text[:120])  # fmt: skip
            async with httpx.AsyncClient(base_url=net, timeout=30) as out:
                h = {"X-Attack-Peer": proxy, "X-Forwarded-For": "203.0.113.9", "X-Real-IP": "203.0.113.9",
                     "X-Forwarded-Proto": "https"}  # fmt: skip
                r = await out.post(
                    "/api/internal/sign-in", json={**USER, "app": "tapiOca for Android"}, headers=h
                )
                checks.ok(r.status_code == 200, f"{layout}: an app signs in from outside through it",
                          f"got {r.status_code}")  # fmt: skip
                r = await out.get("/api/access/me", headers={**h, "X-Forwarded-For": "192.168.1.60",
                                                              "X-Real-IP": "192.168.1.60"})  # fmt: skip
                checks.ok("trusted" not in r.json() and r.json().get("outside") is True,
                          f"{layout}: a home address named on the public port is the internet", r.text[:120])  # fmt: skip
    finally:
        ctx.trusted.save({"entries": kept_entries, "proxies": kept_proxies}, by=None)
        ctx.tuner.save(kept_tuner[0], list(kept_tuner[1].items()), list(kept_tuner[2].items()))


def build_folders(tmp: Path) -> Path:
    """A media folder with a show in it, and things linked from outside it:
    a poster, a video, and a whole folder."""
    media, outside = tmp / "media", tmp / "outside"
    show = media / "TV" / "Night Owls (2020)" / "Season 01"
    show.mkdir(parents=True)
    outside.mkdir()
    (show / "Night Owls (2020) - S01E01 - Dusk.mkv").write_bytes(b"")
    (outside / "secret.jpg").write_bytes(SECRET)
    (outside / "Stolen (2001) - S01E01.mkv").write_bytes(b"")
    (show.parent / "poster.jpg").symlink_to(outside / "secret.jpg")
    (show / "Night Owls (2020) - S01E02.mkv").symlink_to(outside / "Stolen (2001) - S01E01.mkv")
    (media / "TV" / "Linked").symlink_to(outside)
    # (A real one, named as a release is, its sound track titled with its
    # file's name: what the apps get of it never names the file.)
    if shutil.which("ffmpeg"):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=2:s=320x240:r=25",
             "-f", "lavfi", "-i", "sine=d=2", "-c:v", "libx264", "-c:a", "aac",
             "-metadata:s:a:0", f"title={RELEASE}", "-shortest", str(show / RELEASE)],
            check=True, timeout=60,
        )  # fmt: skip
    return media


RELEASE = "Night.Owls.2020.S01E03.1080p.WEB-DL.x264-GRP.mkv"


async def _folders(
    checks: Checks, app, home: str, net: str, admin_h: dict, sam_h: dict, kit_h: dict
) -> None:
    checks.section("Media folders of tapiOca's own")
    addresses = [
        ("GET", "/api/folder-libraries", None),
        ("GET", "/api/folder-libraries/browse", None),
        ("POST", "/api/folder-libraries", {"name": "Mine", "kind": "show", "folders": ["TV"]}),
        ("PUT", "/api/folder-libraries/f1", {"name": "Mine"}),
        ("DELETE", "/api/folder-libraries/f1", None),
        ("POST", "/api/folder-libraries/f1/scan", None),
    ]
    ctx = app.state.ctx
    real_media = await asyncio.to_thread(os.path.realpath, ctx.settings.media_dir)
    # (Folders are read only while no one's watching: what the sections
    # above played is ended first.)
    ctx.plays.end_all()
    async with httpx.AsyncClient(headers=PAGE, base_url=home, timeout=30) as c:
        # Only from the media folder.
        for folder in ("/etc", "../outside", "TV/Linked", "TV/../../outside", "TV/\x00"):
            bad = await c.post("/api/folder-libraries", headers=admin_h,
                               json={"name": "Out", "kind": "show", "folders": [folder]})  # fmt: skip
            checks.ok(bad.status_code in (400, 422), f"a Media folder can't be made of {folder!r}",
                      f"got {bad.status_code}")  # fmt: skip
        for path in ("..", "../..", "%2e%2e", "TV/../..", "/etc", "TV/Linked", "TV/Linked/.."):
            r = await c.get(f"/api/folder-libraries/browse?path={path}", headers=admin_h)
            checks.ok(r.status_code == 404 and b"secret" not in r.content
                      and b"Stolen" not in r.content,
                      f"browsing {path} shows nothing outside the media folder",
                      f"got {r.status_code}")  # fmt: skip
        made = await c.post("/api/folder-libraries", headers=admin_h,
                            json={"name": "TV", "kind": "show", "folders": ["TV"]})  # fmt: skip
        checks.ok(made.status_code == 201, "an Admin adds a Media folder", made.text[:120])
        key = made.json().get("key", "f1") if made.status_code == 201 else "f1"
        for _ in range(300):
            listed = (await c.get("/api/folder-libraries", headers=admin_h)).json()["libraries"]
            if any(x["key"] == key and x["scannedMs"] for x in listed):
                break
            await asyncio.sleep(0.1)
        else:
            checks.ok(False, "the Media folder is read", "never read")
        things = ctx.folders.things.values()
        files = [p for t in things for v in t.files for p in v]
        checks.ok(any("Dusk" in p for p in files) and not any("Stolen" in p for p in files)
                  and all(p.startswith(real_media) for p in files),
                  "a video linked from outside the media folder isn't read", str(files))  # fmt: skip
        show = next((t.key for t in things if t.kind == "show"), "f2")
        for path in (f"/poster/{show}", f"/poster/{show}?big=true", f"/art/{show}",
                     f"/api/internal/art/{show}?kind=poster"):  # fmt: skip
            r = await c.get(path, headers=admin_h)
            checks.ok(SECRET not in r.content,
                      f"{path}: a poster linked from outside the media folder is never served",
                      f"got {r.status_code}")  # fmt: skip
        for path in (f"/poster/{show}%2f..%2f..", "/poster/f..", "/api/internal/art/f..%2fetc",
                     "/poster/f0", "/poster/f99999999999999999999"):  # fmt: skip
            r = await c.get(path, headers=admin_h)
            checks.ok(r.status_code in (400, 403, 404, 422) and SECRET not in r.content,
                      f"{path} gets nothing", f"got {r.status_code}")  # fmt: skip
        # Shared with the apps, a folder's show never gives a file's name or
        # a path, to anyone.
        await c.put("/api/app-libraries", json={"libraries": ["1", "2", key]}, headers=admin_h)
        listed = await c.get(f"/api/internal/libraries/{key}", headers=admin_h)
        checks.ok(show in listed.text, "the shared Media folder is listed for the apps",
                  listed.text[:200])  # fmt: skip
        for path in ("/api/internal/libraries", f"/api/internal/libraries/{key}",
                     f"/api/internal/items/{show}", f"/api/internal/items/{show}/episodes",
                     "/api/internal/home", "/api/internal/search?q=Night"):  # fmt: skip
            r = await c.get(path, headers=admin_h)
            text = r.text
            checks.ok(r.status_code == 200 and real_media not in text
                      and ".mkv" not in text and "Season 01" not in text,
                      f"{path} names no file or path", f"got {r.status_code}: {text[:160]}")  # fmt: skip
        # Each episode's details (its versions and their tracks) and playing
        # it, for the one named as a release: never the file's name.
        episodes = (await c.get(f"/api/internal/items/{show}/episodes?season=1",
                                headers=admin_h)).json().get("episodes") or []  # fmt: skip
        checks.ok(len(episodes) >= 1, "the show's episodes are listed", str(episodes)[:160])
        named = ("Night.Owls", "WEB-DL", "x264", "GRP", real_media, "Season 01")
        for ep in episodes:
            r = await c.get(f"/api/internal/items/{ep['key']}", headers=admin_h)
            checks.ok(r.status_code == 200 and not any(n in r.text for n in named)
                      and ".mkv" not in r.text,
                      f"episode {ep['key']}'s details name no file or path",
                      f"got {r.status_code}: {r.text[:200]}")  # fmt: skip
            played = await c.post("/api/internal/play", headers=admin_h,
                                  json={"key": ep["key"], "device": TV})  # fmt: skip
            checks.ok(not any(n in played.text for n in named),
                      f"playing episode {ep['key']} names no file or path",
                      f"got {played.status_code}: {played.text[:200]}")  # fmt: skip
            if played.status_code == 200 and played.json().get("leave"):
                await c.post(played.json()["leave"], headers=admin_h, json={})
        # Only Admins.
        for who, headers in (("a User", sam_h), ("a Kid", kit_h)):
            for method, path, body in addresses:
                r = await c.request(method, path, json=body, headers=headers)
                checks.ok(r.status_code == 403, f"{who} can't {method} {path}",
                          f"got {r.status_code}")  # fmt: skip
        checks.ok(any(x["key"] == key for x in ctx.folders.status()),
                  "no one but an Admin removed the Media folder")  # fmt: skip
        await c.put("/api/app-libraries", json={"libraries": ["1", "2"]}, headers=admin_h)
    async with httpx.AsyncClient(
        base_url=net, timeout=30, headers={**PAGE, **_cf("203.0.113.9")}
    ) as out:
        for method, path, body in addresses:
            r = await out.request(method, path, json=body)
            checks.ok(r.status_code == 401, f"from the internet, {method} {path} needs a sign-in",
                      f"got {r.status_code}")  # fmt: skip


async def _kept_alerts(checks: Checks, app, home: str, admin_h: dict) -> None:
    """Admin alerts kept in the database, and tapiOca starting again on
    it (a second Alerts on the same database, as a restart makes)."""
    checks.section("Alerts kept across restarts")
    ctx = app.state.ctx
    odd = "Backups');DROP TABLE alerts;--<script>alert(1)</script>\n%s {0} \u202e are failing."
    ctx.alerts.start("backups", odd)
    told = _Told()
    again = alerts.Alerts(told, Database(ctx.db.path))  # type: ignore[arg-type]
    restored = [a.sentence for a in again.now() if a.kind == "backups"]
    checks.ok(restored == [odd] and not told.said,
              "whatever a sentence holds, it's kept and given back as it was, unsent",
              f"{restored} {told.said}")  # fmt: skip
    async with httpx.AsyncClient(headers=PAGE, base_url=home) as c:
        r = await c.get("/api/internal/alerts", headers=admin_h)
        checks.ok(odd in [a["sentence"] for a in r.json().get("alerts", [])],
                  "and the apps are given it as it is (as text)")  # fmt: skip
    again.db.close()
    ctx.alerts.fix("backups", "The attack check's backups are working.")

    # A database that can't be written (a disk gone read-only): alerts go on.
    with ctx.db._lock:
        ctx.db._conn.execute("PRAGMA query_only = ON")
    try:
        ctx.alerts.start("data-full", "The attack check's disk is full.")
        going = [a.sentence for a in ctx.alerts.now()]
    finally:
        with ctx.db._lock:
            ctx.db._conn.execute("PRAGMA query_only = OFF")
    checks.ok("The attack check's disk is full." in going,
              "an alert that can't be kept is still said")  # fmt: skip
    ctx.alerts.fix("data-full", "The attack check's disk has room.")
    kept = [r["sentence"] for r in ctx.db.kept_alerts()]
    checks.ok("The attack check's disk is full." in kept,
              "and kept once the database can be written again", kept)  # fmt: skip

    # A flood of them: only so many fixed ones are kept, however many come.
    for n in range(alerts.FIXED_MOST * 3):
        ctx.alerts.start("station", f"Station {n} keeps failing.", f"flood{n}")
        ctx.alerts.fix("station", f"Station {n} plays.", f"flood{n}")
    fixed = [r for r in ctx.db.kept_alerts() if r["fixed_ms"] is not None]
    checks.ok(len(fixed) <= alerts.FIXED_MOST, "a flood keeps only so many fixed alerts",
              f"{len(fixed)} kept")  # fmt: skip

    # A backup restored never brings alerts back: a forged one in it included.
    ctx.alerts.start("plex", "The attack check's Plex is away.")
    listed, kept, told = await asyncio.to_thread(_restore_forged_backup, ctx)
    checks.ok(listed == [] and kept == [] and not told,
              "a restored backup brings no alerts back, a forged one included", listed)  # fmt: skip
    ctx.alerts.fix("plex", "The attack check's Plex is back.")


def _restore_forged_backup(ctx) -> tuple[list, list, list]:
    """A backup of tapiOca now (an alert going), with a forged alert
    added, restored into another data folder: what the alerts are once it
    starts there (listed, kept, sent)."""
    made = backups.make_backup(ctx)
    forged = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        with zipfile.ZipFile(made) as z:
            z.extractall(folder)
        conn = sqlite3.connect(folder / backups.DB_NAME)
        with conn:
            conn.execute("INSERT INTO alerts (kind, about, since_ms, sentence) VALUES "
                         "('outside', '', 1, '<img src=x onerror=alert(1)> Forged.')")  # fmt: skip
        conn.close()
        with zipfile.ZipFile(forged, "w") as z:
            for path in folder.rglob("*"):
                if path.is_file():
                    z.write(path, path.relative_to(folder).as_posix())
        elsewhere = folder / "elsewhere"
        elsewhere.mkdir()
        backups.stage_restore(elsewhere, forged.getvalue())
        backups.tidy_staged_stations(elsewhere)
        backups.mark_ready(elsewhere)
        backups.apply_staged_restore(elsewhere)
        restored_db = Database(elsewhere / backups.DB_NAME)
        told = _Told()
        restored = alerts.Alerts(told, restored_db)  # type: ignore[arg-type]
        found = ([a.sentence for a in restored.listed()], restored_db.kept_alerts(), told.said)
        restored_db.close()
    made.unlink()
    return found


def _drift(checks: Checks) -> None:
    """The corner mark's drift is only numbers, worked out from tapiOca's
    clock: whatever that says (1970, before it, far ahead, a fraction of a
    second), what's drawn draws, odd station names included."""
    checks.section("The corner mark's drift")
    small = Settings(plex_url="", plex_token="", video_width=320, video_height=180)
    logo = str(Path(ff.__file__).parent / "logos" / "classic-tv.png")
    for at in (0.0, -86_400.5, 2.0**40, 1_791_000_000.123456):
        said = ff.drift(0, at) + ff.drift(1, at)
        checks.ok(set(said) <= set("0123456789.+-*/(),;tsmodflreq"),
                  f"the drift at {at} is only numbers", said)  # fmt: skip
        for mark in (ff.Watermark(logo=logo, airs_at_s=at),
                     ff.Watermark(text="Rock 'n' Roll: 24/7 \\ ;[x],y", airs_at_s=at),
                     ff.Watermark(clock="12", position="top-left", airs_at_s=at)):  # fmt: skip
            drawn = subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=30",
                 "-vf", ff._video_filter(small, watermark=mark), "-frames:v", "2",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=60,
            )  # fmt: skip
            what = "logo" if mark.logo else "clock" if mark.clock else "name"
            checks.ok(drawn.returncode == 0, f"the {what} drifted at {at} draws",
                      drawn.stderr[-300:])  # fmt: skip


async def _pin_limit(checks: Checks, app, home: str, device_key: str) -> None:
    """Try every wrong PIN at once and confirm the limit holds and none
    gets in. (The User already has the PIN 4321 from setup.)"""
    async with httpx.AsyncClient(base_url=home, headers={"StationPlay-Device": device_key}) as c:
        people = (await c.get("/api/internal/picker")).json()["people"]
        sam = next(p for p in people if p["name"] == USER["name"])

        async def guess(pin: str) -> int:
            r = await c.post("/api/internal/picker/choose", json={"id": sam["id"], "pin": pin})
            return r.status_code

        codes = await asyncio.gather(*(guess(f"{n:04d}") for n in range(4300, 4400) if n != 4321))
        checks.ok(
            codes.count(403) <= access.TRIES and 200 not in codes and 429 in codes,
            "many PIN guesses at once can't beat the limit or get in",
            f"checked={codes.count(403)} got-in={codes.count(200)}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Attack test for tapiOca's server.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show every check, not just failures"
    )
    args = parser.parse_args()
    checks = Checks(args.verbose)
    print("Starting tapiOca on two local ports and attacking it…")
    asyncio.run(run(checks))
    total = checks.passed + checks.failed
    print(
        f"\n{checks.passed}/{total} checks passed"
        + (f", {checks.failed} FAILED" if checks.failed else ", all clear")
    )
    return 1 if checks.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
