#!/usr/bin/env python3
"""Attack test for StationPlay's server, to run before a release.

It starts StationPlay on two free ports of its own (a home-network port and
a public one, as a reverse proxy reaches), against the stand-in Plex the
tests use, with an Admin, a User, a Kid on a limited Viewing Level, a
station, a shared library, an app signed in and a linked device. Then, from
the public port as an outsider (no sign-in), as a User, and as a Kid, it
tries what an attacker would and prints PASS or FAIL for each: routes
without and with the wrong role; forged headers; CSRF from another site;
path traversal; oversized bodies; script in names; guessing or reusing keys,
play addresses and reach nonces; reaching Media and stations a level hides;
and the sign-in, PIN and link-code limits.

It's a tool, not part of CI (the test suite covers these as unit tests). Run
it from the repo root:  python -m tools.attack_check   (add -v to see every
check, not only failures).

It only ever talks to the StationPlay it starts here on localhost. It never
contacts any real server.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import socket
import sys
from pathlib import Path

# The stand-in Plex and library live beside the tests; make them importable
# whether this is run as a module or a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import uvicorn

from app import access
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient
from tests.fakeplex_library import LibraryPlex

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
    return fp


async def run(checks: Checks) -> None:
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="attack-check-"))
    fp = build_plex(tmp)
    lan_sock, public_sock = (socket.create_server(("127.0.0.1", 0)) for _ in range(2))
    lan_port, public_port = lan_sock.getsockname()[1], public_sock.getsockname()[1]
    settings = Settings(
        plex_url="http://plex.test",
        plex_token="token",
        data_dir=tmp / "data",
        port=lan_port,
        public_port=public_port,
    )
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    app.state.ctx.play_transport = fp.transport()
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", proxy_headers=False))
    task = asyncio.create_task(server.serve(sockets=[lan_sock, public_sock]))
    try:
        while not server.started:  # noqa: ASYNC110
            await asyncio.sleep(0.02)
        home = f"http://127.0.0.1:{lan_port}"
        net = f"http://127.0.0.1:{public_port}"
        await _attacks(checks, app, home, net)
    finally:
        server.should_exit = True
        await task


def _cf(address: str) -> dict[str, str]:
    """Headers as a Cloudflare Tunnel passes a visitor on, over HTTPS."""
    return {"CF-Connecting-IP": address, "CF-Visitor": '{"scheme":"https"}'}


async def _attacks(checks: Checks, app, home: str, net: str) -> None:
    # Set everything up from the home network, where StationPlay starts open.
    # Admin, User and Kid are signed in as apps (bearer tokens), so the
    # brute-force tests later don't spend the home address's password budget
    # on the setup calls.
    admin_h = sam_h = kit_h = {}
    async with httpx.AsyncClient(base_url=home) as c:
        await c.post("/api/access/users", json=ADMIN)
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
    async with httpx.AsyncClient(base_url=net) as out:
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
    async with httpx.AsyncClient(base_url=net) as out:
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
    async with httpx.AsyncClient(base_url=home) as pat:
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
    async with httpx.AsyncClient(base_url=home) as c:
        for method, path in (
            ("GET", "/api/logs"), ("POST", "/api/backups"), ("GET", "/api/broken"),
            ("PUT", "/api/scan"), ("GET", "/api/access/users"), ("PUT", "/api/app-libraries"),
            ("DELETE", "/api/logos/upload-0123456789"), ("GET", "/api/arr"),
            ("GET", "/api/away"), ("PUT", "/api/api-tokens/outside"),
            ("PUT", f"/api/access/users/{kit['id']}"),  # (renaming someone, say)
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
    async with httpx.AsyncClient(base_url=home) as c:
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
    async with httpx.AsyncClient(base_url=home) as c:
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

    # 7) Oversized and malformed bodies.
    checks.section("Oversized and malformed bodies")
    async with httpx.AsyncClient(base_url=home) as c:
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
    async with httpx.AsyncClient(base_url=home) as c:
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
            page = (await c.get("/")).text
            checks.ok("<img src=x onerror" not in page, "the name is not written into the page")

    # 9) Guessing or reusing keys, play addresses and reach nonces.
    checks.section("Guessing keys, play addresses and reach nonces")
    async with httpx.AsyncClient(base_url=home) as c:
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
    async with httpx.AsyncClient(base_url=net) as c:
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
    async with httpx.AsyncClient(base_url=net) as out:
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
    async with httpx.AsyncClient(base_url=home) as c:
        on = await c.put("/api/away", json={"on": True, "address": "https://tv.example.com"},
                         headers=admin_h)  # fmt: skip
        checks.ok(on.status_code == 200, "an Admin turns on watching away from home",
                  f"got {on.status_code}")  # fmt: skip
        at_home = (
            await c.post("/api/internal/play", json={"key": "300", "device": TV}, headers=sam_h)
        ).json()
    async with httpx.AsyncClient(base_url=net) as out:
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
    async with httpx.AsyncClient(base_url=home) as c:
        await c.put("/api/away", json={"on": False, "address": "https://tv.example.com"},
                    headers=admin_h)  # fmt: skip
    async with httpx.AsyncClient(base_url=net) as out:
        if allowed.status_code == 200:
            r = await out.get(allowed.json()["url"], headers=https)
            checks.ok(r.status_code == 404, "turning away from home off ends Media there",
                      f"got {r.status_code}")  # fmt: skip


async def _pin_limit(checks: Checks, app, home: str, device_key: str) -> None:
    """Try every wrong PIN at once and confirm the limit holds and none gets
    in. (The User already has the PIN 4321 from setup.)"""
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
    parser = argparse.ArgumentParser(description="Attack test for StationPlay's server.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show every check, not just failures"
    )
    args = parser.parse_args()
    checks = Checks(args.verbose)
    print("Starting StationPlay on two local ports and attacking it…")
    asyncio.run(run(checks))
    total = checks.passed + checks.failed
    print(
        f"\n{checks.passed}/{total} checks passed"
        + (f", {checks.failed} FAILED" if checks.failed else ", all clear")
    )
    return 1 if checks.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
