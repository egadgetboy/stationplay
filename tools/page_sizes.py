"""tapiOca's page at every screen size, for checking before a release.

Starts tapiOca with stand-in data (the tests' stand-in Plex, from
tests/fakeplex_library.py, with shows, movies and collections; and
stations, people, linked devices, stats, logs, problems from the apps,
broken files and a person's report, devices that used the tuner, and Admin
alerts kept from before it last stopped), then, in Playwright's Chromium,
looks at every tab and every dialog and panel that opens, signed in as an
Admin and as a User, and the sign-in screen (from the internet, and its
PIN form at home), at each size, light and dark. It saves a screenshot of each into a folder
(one folder for each size), and says what's wrong with each: a page that
scrolls sideways, something cut off or sticking out of its panel, things
on top of each other, text smaller than the page's smallest (11px), a tap
target smaller than about 40px on a phone or tablet, or a dialog that
doesn't fit the screen. It also checks a few things the page does, and
says "check failed" for any that's wrong: Link an app's code getting its
dash as it's typed, Tuner access's controls, Alert notifications
choosing Discord's and Slack's formats for their webhooks, and the arrows
that say more is above or below (first-run setup's steps, a short dialog,
the log, a problem's journal and the page), and the name as it's drawn
(always tapiOca, never made "TAPIOCA" by a style). It's a tool, not a test:
the tests don't run it.

    pip install playwright pillow       (and: python -m playwright install chromium)
    python tools/page_sizes.py /tmp/page-sizes
    python tools/page_sizes.py /tmp/page-sizes --sizes 390x844,1280x800 --themes dark --only stations,editor
"""

from __future__ import annotations

import argparse
import asyncio
import colorsys
import io
import json
import logging
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from PIL import Image, ImageDraw
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import jobs, ondemand, scanner, stats  # noqa: E402
from app import main as server  # noqa: E402
from app import setup as setup_questions  # noqa: E402
from app.access import COOKIE as SESSION_COOKIE  # noqa: E402
from app.breaks import COMMERCIALS, TRAILERS, Clip  # noqa: E402
from app.broadcaster import Viewer  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import Database, Item  # noqa: E402
from app.plex import PlexClient  # noqa: E402
from app.releases import META as UPDATE_CHECK  # noqa: E402
from app.releases import RELEASES  # noqa: E402
from app.setup import META_ANSWERED as SETUP_ANSWERED  # noqa: E402
from tests.fakeplex_library import LibraryPlex  # noqa: E402
from tests.helpers import Proxy  # noqa: E402

# What tapiOca's page sends with each request (see app/access.py, PAGE_HEADER).
PAGE = {"X-Tapioca-Page": "1"}

# Phones (and one on its side), tablets and computers.
SIZES = {
    "phone": ["360x740", "390x844", "430x932", "844x390"],
    "tablet": ["768x1024", "1024x768", "820x1180"],
    "computer": ["1280x800", "1440x900", "1920x1080"],
}
THEMES = ("light", "dark")
ADMIN = {"name": "Pat", "password": "correct horse"}
USER = {"name": "Sam", "password": "battery staple", "role": "user", "maxStations": 3}
KID = {"name": "Robin", "password": "", "role": "user", "pin": "2468"}
JO = {"name": "Jo", "password": "lighthouse keeper", "role": "user"}
JO_PIN = "1357"  # (Jo signs in on the page with it: see the sign-in screen's PIN form)
# (1.37.0) Shown only on devices she's signed in on, with a PIN: on a trusted
# network, the page lists her where she signed in with her password.
ARI = {"name": "Ari", "password": "harbor violet quill", "role": "user", "showOn": "signed-in"}
ARI_PIN = "8642"
# (1.38.0) Pat's PIN: in Light sign-in, it gives his Admin tools at home, on a
# browser where he signed in with his password.
PAT_PIN = "9753"
# Tuner access: the devices listed, and who used the tuner lately (address,
# what it called itself, what it asked for, how many minutes ago, refused):
# Plex in Docker, at the Docker network's address (not listed: the warning),
# a listed one, a refused one, and one with no name.
TUNER_LISTED = [
    {"address": "192.168.1.41", "name": "Den PC"},
    {"address": "192.168.1.30", "name": ""},
]
TUNER_SEEN = [
    ("192.168.1.52", "", "/stations.m3u", 26 * 60, False),
    ("192.168.1.77", "Kodi/21.1 (Linux; Android 12)", "/xmltv.xml", 3 * 60, True),
    ("192.168.1.41", "VLC/3.0.21 LibVLC/3.0.21", "/stream/4", 15, False),
    ("172.17.0.5", "PlexMediaServer/1.41.3", "/lineup.json", 2, False),
]
# Trusted networks: a device on the home Wi-Fi (Who's tuning in?), and Sam's
# laptop (signed in as Sam), where the sign-in screen is looked at from (AsPeer).
TRUSTED_DEVICE, SAMS_LAPTOP = "192.168.1.60", "192.168.1.44"
# A Discord webhook's address, typed on the Logs tab (Format then says Discord).
DISCORD = "https://discord.com/api/webhooks/123456789012345678/abcDEF-ghi_jkl"
SLACK = "https://hooks.slack.com/services/T000/B000/example-key"
NTFY = "https://ntfy.sh/stationplay-alerts"

SHOWS = [
    # (title, year, genres, content rating, studio)
    ("Northbound", 2020, ["Drama", "Adventure"], "TV-14", "Harbor Pictures"),
    ("Harbor Lights", 1996, ["Drama", "Romance"], "TV-PG", "Lighthouse"),
    ("The Night Desk", 2011, ["Comedy"], "TV-14", "Late Hours"),
    ("Maple Street", 1988, ["Comedy", "Family"], "TV-G", "Elm Studios"),
    ("Rocket Rangers", 1979, ["Animation", "Science Fiction"], "TV-Y7", "Comet Toons"),
    ("Saturday Toons", 1983, ["Animation", "Kids"], "TV-Y", "Comet Toons"),
    ("Kitchen Rescue", 2015, ["Reality", "Food"], "TV-PG", "Skillet"),
    ("Lost Coast", 2004, ["Mystery", "Drama"], "TV-14", "Fogline"),
    ("Grand Central Mysteries", 1992, ["Mystery"], "TV-PG", "Lighthouse"),
    ("Space Patrol 3000", 1999, ["Science Fiction", "Action"], "TV-PG", "Orbit"),
    ("The Long Way Home", 2018, ["Documentary", "Travel"], "TV-G", "Wayfarer"),
    ("Fairweather Friends", 1994, ["Comedy"], "TV-PG", "Elm Studios"),
]
# Stations of shows: their numbers, names, shows and settings.
STATIONS: list[tuple[int, str, list[str], dict[str, Any]]] = [
    (2, "Cartoon Classics", ["104", "105"], {"orderMode": "shuffle", "breaks": 2,
     "description": "Saturday mornings, all week long."}),
    (4, "Prime Time", ["100", "101", "102", "107"], {"watermark": "logo", "skipIntros": True,
     "stationId": True, "idSeconds": 5}),
    (5, "Comedy Station", ["102", "103", "111"], {"marathonMode": "random"}),
    (7, "Mystery Hour", ["107", "108"], {"watermark": "clock", "tuneIn": "start"}),
    (9, "Station 9", ["106", "110"], {}),
]  # fmt: skip
MOVIES = [
    ("The Midnight Train", 1987, ["Thriller"], "R"),
    ("Summer at Willow Lake", 1994, ["Romance", "Comedy"], "PG"),
    ("Deep Water", 1975, ["Thriller", "Adventure"], "PG"),
    ("Cosmic Drift", 2003, ["Science Fiction"], "PG-13"),
    ("The Clockmaker", 1961, ["Drama"], "Not Rated"),
    ("Big City Lights", 1999, ["Comedy"], "PG-13"),
    ("A Very Snowy Holiday", 2008, ["Comedy", "Family", "Holiday"], "G"),
    ("Home for the Holidays Again", 2012, ["Family", "Holiday"], "PG"),
    ("The Last Lighthouse", 1983, ["Drama", "Mystery"], "PG"),
    ("Robot Summer", 1986, ["Science Fiction", "Family"], "PG"),
    ("Desert Run", 1991, ["Action"], "R"),
    ("The Great Bake-Off Mystery", 2016, ["Comedy", "Mystery"], "PG"),
]


class StandInPlex(LibraryPlex):
    """The tests' stand-in Plex, with posters: a plain picture in a color of
    its own for each show and movie."""

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/photo/:/transcode":
            url = request.url.params.get("url", "")
            key = url.split("/")[3] if url.startswith("/library/metadata/") else ""
            if key in self.shows or key in self.episodes:
                width = int(request.url.params.get("width", 64))
                height = int(request.url.params.get("height", 96))
                return httpx.Response(
                    200, content=poster(key, width, height), headers={"content-type": "image/png"}
                )
        return super().handler(request)


def poster(key: str, width: int, height: int) -> bytes:
    """A show's or movie's poster, as a PNG."""
    hue = zlib.crc32(key.encode()) % 360
    picture = Image.new("RGB", (width, height), hsl(hue, 0.45, 0.42))
    draw = ImageDraw.Draw(picture)
    draw.rectangle((0, int(height * 0.68), width, height), fill=hsl(hue, 0.5, 0.25))
    draw.ellipse(
        (width * 0.25, height * 0.2, width * 0.75, height * 0.2 + width * 0.5),
        fill=hsl((hue + 40) % 360, 0.6, 0.7),
    )
    out = io.BytesIO()
    picture.save(out, "PNG")
    return out.getvalue()


def hsl(hue: float, saturation: float, lightness: float) -> tuple[int, int, int]:
    red, green, blue = colorsys.hls_to_rgb(hue / 360, lightness, saturation)
    return round(red * 255), round(green * 255), round(blue * 255)


def library() -> StandInPlex:
    plex = StandInPlex()
    plex.add_section("2", "Movies", "movie")
    key = 1000
    for n, (title, year, genres, rating, studio) in enumerate(SHOWS):
        show = str(100 + n)
        plex.add_show(
            show, title, year=year, genres=genres, contentRating=[rating], studio=[studio],
            audience_rating=6.5 + n % 4 * 0.6,
        )  # fmt: skip
        folder = title.lower().replace(" ", ".")
        for season in (1, 2):
            for episode in range(1, 5):
                key += 1
                plex.add_episode(
                    str(key), show, season, episode, f"Episode {episode}",
                    f"/data/tv/{title}/Season {season}/{folder}.s{season:02}e{episode:02}.mkv",
                    (22 if n % 3 else 44) * 60_000,
                )  # fmt: skip
                plex.describe(str(key))
    for n, (title, year, genres, rating) in enumerate(MOVIES):
        plex.add_movie(
            str(300 + n), title, f"/data/movies/{title} ({year})/{title}.mkv",
            (88 + n * 7) * 60_000, year=year, section="2", genres=genres,
            contentRating=[rating], audience_rating=5.8 + n % 5 * 0.7,
        )  # fmt: skip
        plex.describe(str(300 + n))
    plex.add_collection("900", "Saturday Morning", "1", "104", "105")
    plex.add_collection("901", "Holiday Movies", "2", "306", "307")
    plex.add_collection("902", "80s Favorites", "2", "300", "308", "309")
    return plex


# tapiOca, running ----------------------------------------------------------------


# A newer tapiOca, as the stand-in for GitHub says (see Running), and
# the page's "Not now" for it (updates.js).
NEWER = "9.0.0"
NOT_NOW = "tapioca.updateNotNow"


def media_folder(data: Path) -> Path:
    """A media folder beside the data folder, with shows and movies laid
    out as Sonarr and Radarr lay them out (empty files: the page only
    lists them), for Media folders of tapiOca's own (1.35.0)."""
    media = data.parent / "media"
    for show, year in (("Harbor Lights", 2019), ("Saturday Toons", 1994)):
        season = media / "TV" / f"{show} ({year})" / "Season 01"
        season.mkdir(parents=True, exist_ok=True)
        for n in range(1, 4):
            (season / f"{show} ({year}) - S01E{n:02d} - Part {n}.mkv").touch()
    for movie, year in (("The Long Field", 1987), ("Paper Moons", 2004)):
        folder = media / "Movies" / f"{movie} ({year})"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{movie} ({year}).mkv").touch()
    (media / "Home Videos").mkdir(exist_ok=True)
    return media


class AsPeer:
    """Tool only: a request's X-Page-Peer header (taken off before tapiOca
    sees it) says the address it comes from, so the sign-in screen can be
    looked at from a device on a trusted network (1.36.0)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = scope.get("headers") or []
            said = [v for k, v in headers if k == b"x-page-peer"]
            if said:
                client = scope.get("client") or ("127.0.0.1", 0)
                scope = {**scope, "client": (said[-1].decode("latin-1"), client[1]),
                         "headers": [(k, v) for k, v in headers if k != b"x-page-peer"]}  # fmt: skip
        await self.app(scope, receive, send)


class Running:
    """tapiOca on its home-network port and its public one, in a thread
    of its own; `call` runs something on its event loop."""

    def __init__(self, data: Path, plex: StandInPlex) -> None:
        lan, public = (socket.create_server(("127.0.0.1", 0)) for _ in range(2))
        self.ports = lan.getsockname()[1], public.getsockname()[1]
        self.home, self.internet = (f"http://127.0.0.1:{port}" for port in self.ports)
        settings = Settings(
            plex_url="http://plex.test", plex_token="token", data_dir=data, hw_accel="cpu",
            port=self.ports[0], public_port=self.ports[1], media_dir=str(media_folder(data)),
        )  # fmt: skip
        self.app = server.create_app(
            settings, PlexClient("http://plex.test", "token", transport=plex.transport())
        )
        self.ctx = self.app.state.ctx
        # (The update check finds a newer tapiOca here, `newest`, never
        # asking GitHub.)
        self.newest = NEWER
        self.ctx.releases.transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={
                "tag_name": f"v{self.newest}", "html_url": f"{RELEASES}/tag/v{self.newest}"})
        )  # fmt: skip
        self.ctx.play_transport = plex.transport()
        config = uvicorn.Config(
            AsPeer(self.app), log_level="warning", lifespan="on", proxy_headers=False
        )
        self.server = uvicorn.Server(config)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self.loop.run_until_complete,
            args=(self.server.serve(sockets=[lan, public]),),
            daemon=True,
        )
        self.thread.start()
        while not self.server.started:
            time.sleep(0.05)

    def call(self, do: Callable[[], Any]) -> Any:
        async def done() -> Any:
            return do()

        return asyncio.run_coroutine_threadsafe(done(), self.loop).result(30)

    def newest_out(self, version: str) -> None:
        """The stand-in for GitHub says `version` is out, and the update
        check has looked."""
        self.newest = version
        asyncio.run_coroutine_threadsafe(self.ctx.releases.check(), self.loop).result(30)

    def unanswered(self) -> None:
        """As a tapiOca updated from before 1.34.0: no Admin has said
        whether the update check may look."""

        def forget() -> None:
            self.ctx.db.set_meta(UPDATE_CHECK, "")
            self.ctx.releases.on = None

        self.call(forget)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)


def kept_from_before(data: Path) -> None:
    """Admin alerts kept from before tapiOca last stopped, as it finds
    them when it starts (see alerts.py): the clock off since three hours
    ago, still going (the stand-in Plex doesn't say the time, so it stays),
    and the data folder's space, fixed an hour ago."""
    now = int(time.time() * 1000)
    db = Database(data / "stationplay.db")
    db.keep_alert(
        "clock", "", now - 3 * 3600_000,
        "tapiOca's clock is 7 minutes ahead of Plex's. The guide and the stations' clocks "
        "go by it: check the date and time on this server (and on Plex's, if it runs elsewhere).",
        None,
    )  # fmt: skip
    db.keep_alert(
        "data-full", "", now - 5 * 3600_000,
        "tapiOca's data folder has only 1.4 GB free (1% of its disk). Free up room on its "
        "disk, or tapiOca can't keep stations, backups and settings.",
        now - 3600_000,
    )  # fmt: skip
    db.close()


def fill(sp: Running, data: Path) -> None:
    """Everything the tabs show: stations (from shows and movies, smart ones
    and from collections), people, linked devices, signed-in apps, an API
    token, tapiOca's apps away from home, stats, logs, problems from the
    apps, a logo and an Intro Bumper of your own, a backup; and on the Broken
    files tab, people's reports (several on one program, one tapiOca
    checked and found nothing wrong in, one it found what's wrong in), files
    that need you, one being replaced, and the rest, with Sonarr and Radarr
    on, which sends an Admin's alert; and Tuner access, with two devices
    listed and four that used the tuner lately."""
    ctx = sp.ctx
    with httpx.Client(headers=PAGE, base_url=sp.home, timeout=60) as home:

        def ok(response: httpx.Response) -> Any:
            assert response.is_success, (response.request.url, response.status_code, response.text)
            return response.json() if response.content else None

        ok(home.post("/api/access/users", json={**ADMIN, "role": "admin", "maxStations": None}))
        ok(home.post("/api/access/users", json=USER))
        ok(home.post("/api/access/users", json={**JO, "pin": JO_PIN}))
        ok(home.post("/api/access/users", json={**ARI, "pin": ARI_PIN}))
        robin = ok(home.post("/api/access/users", json=KID))
        levels = {lv["name"]: lv["id"] for lv in ok(home.get("/api/access/viewing"))["levels"]}
        ok(home.put(f"/api/access/users/{robin['id']}/viewing", json={"level": levels["Kid"]}))
        # (1.35.0) Media folders of tapiOca's own, one of shows and one of
        # movies, read.
        for name, kind, folder in (("Our shows", "show", "TV"), ("Our movies", "movie", "Movies")):
            ok(home.post("/api/folder-libraries",
                         json={"name": name, "kind": kind, "folders": [folder]}))  # fmt: skip
        for _ in range(300):
            listed = ok(home.get("/api/folder-libraries"))["libraries"]
            if all(x["scannedMs"] for x in listed):
                break
            time.sleep(0.1)
        # What Kid hides by what a title is, and what's hidden or allowed for
        # Robin (1.33.0).
        kid = next(
            lv for lv in ok(home.get("/api/access/viewing"))["levels"] if lv["name"] == "Kid"
        )
        ok(home.put(f"/api/access/levels/{kid['id']}", json={
            "name": "Kid", "movieAge": kid["movieAge"], "tvAge": kid["tvAge"],
            "unrated": kid["unrated"], "libraries": kid["libraries"],
            "blocks": {"genres": ["Mystery", "Reality"], "studios": ["Fogline"]},
        }))  # fmt: skip
        ok(home.put(f"/api/access/users/{robin['id']}/viewing", json={"own": {
            "blocks": {"genres": ["Action"], "collections": ["80s Favorites"],
                       "titles": [{"key": "108", "title": "Grand Central Mysteries (1992)"}]},
            "allowTitles": [{"key": "302", "title": "Deep Water (1975)"}],
        }}))  # fmt: skip
        setup = ok(home.get("/api/setup"))
        ok(home.put("/api/setup", json={"answered": setup["questions"]}))
        ok(home.put("/api/app-libraries", json={"libraries": ["1", "2"]}))

        logos = [logo["id"] for logo in ok(home.get("/api/logos"))][::37]
        made = {}
        for n, (number, name, shows, more) in enumerate(STATIONS):
            sources = [{"type": "show", "ratingKey": key} for key in shows]
            body = {"number": number, "name": name, "sources": sources, **more}
            made[number] = ok(home.post("/api/channels", json={**body, "logo": logos[n]}))
        movies = [{"type": "movie", "ratingKey": str(300 + n)} for n in range(len(MOVIES))]
        made[12] = ok(home.post("/api/channels", json={
            "number": 12, "name": "Movie Night", "sources": movies, "featureMode": "on",
            "featureDays": "4,5", "featureTime": "20:00", "breaks": 1}))  # fmt: skip
        smart = {"type": "filter", "kind": "movie", "libraries": ["2"]}
        ok(home.post("/api/smart/stations", json={"firstNumber": 20, "stations": [
            {"name": "1980s Movies", "source": {**smart, "decade": [1980]}},
            {"name": "1990s Movies", "source": {**smart, "decade": [1990]}}]}))  # fmt: skip
        ok(home.post("/api/collections/stations", json={"ratingKeys": ["900", "901"]}))

        # Your own logo and Intro Bumper.
        mine = io.BytesIO()
        Image.new("RGB", (256, 256), (230, 120, 30)).save(mine, "PNG")
        ok(home.post("/api/logos?name=Our%20Den", content=mine.getvalue()))
        bumper = data / "bumper.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25",
             "-f", "lavfi", "-i", "sine=f=440", "-t", "3", "-c:v", "libx264", "-preset",
             "ultrafast", "-c:a", "aac", "-shortest", str(bumper)],
            check=True,
        )  # fmt: skip
        ok(home.post("/api/bumpers?name=Our%20Intro", content=bumper.read_bytes()))
        ok(home.post("/api/backups"))

        # Signed-in apps, problems they ran into, and a token for a script.
        tv = {"app": "tapiOca for Android TV", "deviceName": "Living Room TV"}
        signed = ok(home.post("/api/internal/sign-in", json={**ADMIN, **tv}))
        app_token = {"Authorization": f"Bearer {signed['token']}"}
        sams = ok(home.post("/api/internal/sign-in", json={
            **USER, "app": "tapiOca for iPhone", "deviceName": "Sam’s iPhone"}))  # fmt: skip
        sam_token = {"Authorization": f"Bearer {sams['token']}"}
        jos = ok(home.post("/api/internal/sign-in", json={
            **JO, "app": "tapiOca for Roku", "deviceName": "Bedroom"}))  # fmt: skip
        jo_token = {"Authorization": f"Bearer {jos['token']}"}
        roku = {"app": "tapiOca for Roku", "version": "0.5.0",
                "device": "Roku Ultra 4850X, Roku OS 14.0", "deviceName": "Bedroom"}  # fmt: skip
        phone = {"app": "tapiOca for Android", "version": "0.9.0",
                 "device": "Pixel 8, Android 15", "deviceName": "Pat’s phone"}  # fmt: skip
        for device in (roku, phone):
            ok(home.post("/api/internal/problem", headers=app_token, json={
                "kind": "station-stopped", "station": 4, "detail": "decoder error", **device}))  # fmt: skip
        ok(home.post("/api/internal/problem", headers=app_token, json={
            "kind": "library-failed", "title": "Cosmic Drift", "detail": "HTTP 500", **roku}))  # fmt: skip
        ok(home.post("/api/internal/problem", headers=app_token, json={"kind": "crashed", **phone}))
        # People's reports, for the Broken files tab: one waiting for an
        # Admin; three people's on one program; and two tapiOca checks
        # (one finds nothing wrong, the other what's wrong: see inside).
        ok(home.put("/api/arr", json={"app": "sonarr", "url": "http://nas:8989", "key": "abc123",
                                      "on": True}))  # fmt: skip
        ok(home.put("/api/arr", json={"app": "radarr", "url": "http://nas:7878", "key": "abc123",
                                      "on": True}))  # fmt: skip
        ok(home.post("/api/internal/report-problem", headers=app_token, json={
            "choice": "wrong-language", "key": "303", "positionMs": 92_000}))  # fmt: skip
        for who, choice, at in ((sam_token, "out-of-sync", 754_000), (jo_token, "wrong-language",
                                 1_201_000), (app_token, "poor-quality", None)):  # fmt: skip
            ok(home.post("/api/internal/report-problem", headers=who, json={
                "choice": choice, "key": "1026", "positionMs": at, "method": "direct",
                "audio": "10262"}))  # fmt: skip
        ok(home.post("/api/internal/report-problem", headers=sam_token, json={
            "choice": "no-sound", "key": "302", "positionMs": 3_120_000}))  # fmt: skip
        ok(home.post("/api/internal/report-problem", headers=jo_token, json={
            "choice": "picture-breaks", "key": "1050", "positionMs": 754_000}))  # fmt: skip
        ok(home.put(f"/api/access/users/{robin['id']}", json={"canReport": False}))
        # One sent later, with what led up to it (a long line too), and trouble
        # reaching tapiOca.
        journal = "\n".join([
            "10:41:02 Asked to play Cosmic Drift · S1 E2 (303), up to 42000 kbps",
            "10:41:03 Playing as it is: video/hevc 3840×2160, audio/eac3 6 channels",
            "10:52:40 Library player: ERROR_CODE_DECODING_FAILED (MediaCodecVideoDecoderException: "
            "Decoder failed: c2.exynos.hevc.decoder); format video/hevc, hvc1.2.4.L153.B0, "
            "3840×2160; decoder c2.exynos.hevc.decoder, at 11:37",
            "10:52:40 This device couldn't decode Cosmic Drift · S1 E2: asking for a converted copy",
        ])  # fmt: skip
        galaxy = {**phone, "device": "Galaxy S23, Android 14", "deviceName": "Kitchen tablet"}
        ok(home.post("/api/internal/problem", headers=app_token, json={
            "kind": "library-stopped", "title": "Cosmic Drift · S1 E2", "journal": journal,
            "detail": "ERROR_CODE_DECODING_FAILED (MediaCodecVideoDecoderException: Decoder "
            "failed: c2.exynos.hevc.decoder); format video/hevc, 3840×2160",
            "at": int(time.time() * 1000) - 2 * 3_600_000, **galaxy}))  # fmt: skip
        ok(home.post("/api/internal/problem", headers=app_token, json={
            "kind": "unreachable", "detail": "No network on this device for 12 min 4 s.",
            "lastedMs": 724_000, "journal": "10:12:30 Can't reach tapiOca: No network on "
            "this device\n10:24:34 tapiOca answered again", **galaxy}))  # fmt: skip
        ok(home.post("/api/api-tokens", json={"name": "Home Assistant", "scope": "viewer"}))
        ok(home.post("/api/internal/play", headers=app_token, json={"key": "303", "device": {
            "containers": ["mkv", "mp4"], "hdr": [], "audio": ["aac", "ac3"], "hls": ["ts"],
            "video": [{"codec": "h264", "width": 3840, "height": 2160, "bitDepth": 8}]}}))  # fmt: skip

        # A newer tapiOca is out (see Running), on Docker Compose, and
        # the Admin said yes to the update check.
        ctx.releases.install = "compose"
        ok(home.put("/api/updates", json={"on": True}))
        ok(home.post("/api/updates/check"))

        # Tuner access: any device on the home network, with two devices listed.
        ok(home.put("/api/tuner", json={"only": False, "devices": TUNER_LISTED}))

        # Trusted networks (1.36.0): the home Wi-Fi, on Who's tuning in? (Jo
        # shown there, with a PIN), and Sam's laptop, signed in as Sam (the
        # sign-in screen is looked at from them: see AsPeer); the reverse
        # proxy; a name for home. First, a device that isn't a trusted proxy
        # sends forwarding headers (seen lately, on the tab).
        ok(home.get("/api/status", headers={"X-Forwarded-For": "192.168.1.7"}))
        people = {u["name"]: u["id"] for u in ok(home.get("/api/access/users"))}
        ok(home.put(f"/api/access/users/{people[JO['name']]}/picker", json={"showOn": "home"}))
        ok(home.put("/api/access/trusted", json={
            "entries": [
                {"network": "192.168.1.0/24", "label": "Home Wi-Fi", "gives": "picker"},
                {"network": SAMS_LAPTOP, "label": "Sam’s laptop", "gives": "person",
                 "person": people[USER["name"]]},
            ],
            "proxies": [{"network": "192.168.1.2", "label": "Nginx Proxy Manager"}],
            "homeNames": ["tv.home.example.com"],
        }))  # fmt: skip

        # (1.38.0) Pat chooses Light sign-in, with a PIN.
        with httpx.Client(headers=PAGE, base_url=sp.home, timeout=60) as pat:
            ok(pat.post("/api/access/sign-in", json=ADMIN))
            ok(pat.put(f"/api/access/users/{people[ADMIN['name']]}/picker", json={"pin": PAT_PIN}))
            ok(pat.put("/api/access/me/sign-in",
                       json={"how": "light", "password": ADMIN["password"]}))  # fmt: skip

        # tapiOca's apps away from home, through a reverse proxy.
        ctx.reach.transport = Proxy(sp.app, sp.ports[1]).transport
        ok(home.put("/api/away", json={"on": True, "address": "https://tv.example.com"}))

    def inside() -> None:
        pat = next(u for u in ctx.db.users() if u.name == ADMIN["name"])
        ctx.devices.link("tapiOca for Android TV on Den", pat)
        # Stats: viewings over the last few weeks, by Plex users and in the apps.
        now = int(time.time() * 1000)
        ids = [made[n]["id"] for n in (2, 4, 5, 7, 12)]
        aired = ["Saturday Toons", "Northbound", "Maple Street", "Lost Coast", "Deep Water"]
        for day in range(24):
            for n, cid in enumerate(ids):
                if (day + n) % 3 == 0:
                    continue
                start = now - day * 86_400_000 - (n * 3 + 2) * 3_600_000
                end = start + (25 + n * 13) * 60_000
                kind = "movie" if n == 4 else "episode"
                watched = [(stats.day_of(start), aired[n], kind, (end - start) / 1000)]
                ctx.db.add_view(cid, start, end, watched)
        today = stats.day_of(now)
        ctx.db.add_user_watching([
            ("plex-1", "Grandma", ids[1], today, "Harbor Lights", "episode", 5400.0),
            ("plex-2", "Jordan", ids[0], today, "Saturday Toons", "episode", 2700.0),
        ])  # fmt: skip
        ctx.db.add_app_watching([(2, "Sam", ids[2], today, "Maple Street", "episode", 3600.0)])
        ctx.db.add_media_watching((1, "Pat", today, "Deep Water", "movie", 1, 4200.0))
        # Watching now: a station in Plex, and one in another player.
        for cid, viewer in (
            (ids[1], Viewer("192.168.1.30 on 4", client="192.168.1.30", agent="Lavf/60.16.100")),
            (ids[0], Viewer("192.168.1.41 on 2", client="192.168.1.41", agent="VLC/3.0.21")),
        ):
            b = ctx.broadcaster(cid)
            b.viewers.add(viewer)
            # (Said to be running, with nothing to play: for the header's count.)
            b._task = asyncio.get_running_loop().create_task(asyncio.Event().wait())
        ctx.who_watches.sessions = {ids[1]: [{
            "user": "Grandma", "app": "Plex for Roku on Living Room", "where": "home",
            "since": now - 1_800_000}]}  # fmt: skip
        ctx.who_watches.looked_ms = now
        # Broken files.
        for n, (show, problem, reason) in enumerate((
            ("Lost Coast", "broken", "ffmpeg couldn't open the file: Invalid data found"),
            ("Kitchen Rescue", "damaged", "the picture breaks up 18 min in (decoding errors)"),
            ("Northbound", "unsupported", "Dolby Vision profile 5, which can't be shown right"),
        )):  # fmt: skip
            key = str(2000 + n)
            item = Item(
                position=0, start_ms=0, duration_ms=44 * 60_000, rating_key=key,
                kind="episode", title=f"Episode {n + 2}", show_title=show, season=1,
                episode=n + 2, file_path=f"/data/tv/{show}/Season 1/{show.lower()}.s01e0{n + 2}.mkv",
            )  # fmt: skip
            ctx.broken.record(item, reason, 4, problem=problem, file_size=1_400_000_000,
                              library="1" if problem == "broken" else None)  # fmt: skip
        # What tapiOca's checks of what people reported came to: nothing
        # wrong in Deep Water; Kitchen Rescue's picture breaking up, found.
        for target in list(ctx.scanner._targets):
            if target.rating_key == "302":
                target.ran = ["from 51:40 to 52:40", "the quick check"]
                ctx.scanner._done_with(target, scanner.NOTHING, scanner._nothing_found(target))
            elif target.rating_key == "1050":
                reason = "Check from 12:14: the picture breaks up around 12:31"
                item = Item(0, 0, 22 * 60_000, "1050", "episode", "Episode 2",
                            show_title="Kitchen Rescue", show_key="106", season=1, episode=2,
                            file_path="/data/tv/Kitchen Rescue/Season 1/kitchen.rescue.s01e02.mkv",
                            library="1")  # fmt: skip
                ctx.broken.record(item, reason, 9, problem="damaged", found="targeted check",
                                  file_size=900_000_000)  # fmt: skip
                ctx.scanner._done_with(target, scanner.FOUND, reason)
        # Sonarr replacing one; and one it gave up on, for you.
        for key, title, show, season, state in (
            ("1013", "Episode 1", "Harbor Lights", 2, {
                "state": "downloading", "tries": 1,
                "note": "Sonarr is downloading Harbor.Lights.S02E01.1080p.WEB-DL"}),
            ("1089", "Episode 1", "Fairweather Friends", 1, {
                "state": "gave up", "tries": 3,
                "note": "Sonarr searched 3 times in about a day but didn't find a file that "
                "plays. Replace it yourself, or choose Try again."}),
        ):  # fmt: skip
            item = Item(0, 0, 22 * 60_000, key, "episode", title, show_title=show, season=season,
                        episode=1, library="1",
                        file_path=f"/data/tv/{show}/Season {season}/episode1.mkv")  # fmt: skip
            ctx.broken.record(item, "Deep scan: the sound drops out around 8:12", 4,
                              problem="damaged", found="deep scan", file_size=700_000_000)  # fmt: skip
            entry = ctx.broken.entry(key)
            ctx.broken.replacing(
                {key: (entry["lastFailed"], {"app": "sonarr", "at": now, **state})}
            )
        ctx.alerts.files(ctx.reports.needing())
        # Commercials and trailers, the trailers rated (and the alert for the
        # station Robin sees, which skips the commercials, as the checks find).
        ctx.fillers.clips = {
            COMMERCIALS: [Clip(f"/data/commercials/{n}.mkv", 30_000, 1, 1.0) for n in range(14)]
            + [Clip(f"/data/commercials/1980s/{n}.mkv", 30_000, 1, 1.0, decade=1980)
               for n in range(6)],
            TRAILERS: [Clip(f"/data/movies/trailers/{n}.mkv", 120_000, 1, 1.0) for n in range(9)],
        }  # fmt: skip
        ctx.clip_ratings.save({"trailers": 13})
        ctx.alerts.clips(1)  # (Cartoon Classics, which Robin sees)
        # Who used the tuner lately.
        for address, agent, path, minutes, refused in TUNER_SEEN:
            ctx.tuner.used(address, agent, path, refused)
            ctx.tuner.recent[address].last -= minutes * 60
        logging.getLogger("stationplay.broadcaster").error(
            "Station 7, Mystery Hour: ffmpeg stopped unexpectedly (exit code 1) while playing "
            "lost.coast.s02e03.mkv; the next program starts instead"
        )

    sp.call(inside)


# Looking at the page -----------------------------------------------------------------

# Measured in the page: what's wrong, in a few words each.
MEASURE = r"""
(touch) => {
  const said = [];
  const doc = document.documentElement;
  const W = doc.clientWidth, H = doc.clientHeight;  // (the screen, not a phone's zoomed-out view of a page too wide)
  if (doc.scrollWidth > W + 1) said.push(`the page scrolls sideways (${doc.scrollWidth}px in ${W}px)`);
  const dialog = [...document.querySelectorAll('dialog[open]')].pop();
  const scope = dialog || document.body;
  // What's in sight: drawn (not in a closed <details>, say), and not
  // scrolled out of a box that scrolls or clips (`seen` is the part in sight).
  const seen = new Map();
  const shown = el => {
    if (seen.has(el)) return !!seen.get(el);
    let r = null;
    if (el.checkVisibility({ opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true })) {
      const b = el.getBoundingClientRect();
      r = { left: b.left, right: b.right, top: b.top, bottom: b.bottom };
      for (let p = el.parentElement; p && r; p = p.parentElement) {
        const s = getComputedStyle(p);
        if (s.overflowX === 'visible' && s.overflowY === 'visible') continue;
        const c = p.getBoundingClientRect();
        r = { left: Math.max(r.left, c.left), right: Math.min(r.right, c.right), top: Math.max(r.top, c.top), bottom: Math.min(r.bottom, c.bottom) };
        if (r.right - r.left < 0.5 || r.bottom - r.top < 0.5) r = null;
      }
    }
    seen.set(el, r);
    return !!r;
  };
  const words = el => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 40);
  const named = el => {
    const cls = typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).join('.') : '';
    const id = el.id ? '#' + el.id : '';
    const w = words(el);
    return `${el.tagName.toLowerCase()}${id}${cls}${w ? ` “${w}”` : ''}`;
  };
  const ownText = el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  const all = [...scope.querySelectorAll('*')].filter(el => !el.closest('svg, .sprite, .toast, [hidden]') || el.matches('svg'));
  const atoms = all.filter(el => (ownText(el) || el.matches('button, a[href], select, input:not([type=hidden]), textarea, summary, img, video')) && shown(el));
  // Sideways scrolling inside the page (the tab bar's is on purpose).
  for (const el of all) {
    if (!shown(el) || el.matches('nav.tabs')) continue;
    const s = getComputedStyle(el);
    if (/(auto|scroll)/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 1) said.push(`${named(el)} scrolls sideways (${el.scrollWidth}px in ${el.clientWidth}px)`);
  }
  // Cut off by the screen, or sticking out of its panel.
  const boxes = 'dialog, .panel, .group, .picker, .reach, .block, .tile, .gauge, .btn, .seg, .sel, .chip, .pill, td';
  for (const el of atoms) {
    if (el.closest('nav.tabs, .mark-preview')) continue;
    const r = seen.get(el);
    if (r.right > W + 1 || r.left < -1) { said.push(`${named(el)} is cut off by the screen (${Math.round(r.left)} to ${Math.round(r.right)})`); continue; }
    const box = el.parentElement?.closest(boxes);
    if (!box) continue;
    const b = box.getBoundingClientRect();
    if (r.right > b.right + 1.5 || r.left < b.left - 1.5) said.push(`${named(el)} sticks out of ${named(box).split(' ')[0]} (${Math.round(r.left)}–${Math.round(r.right)} in ${Math.round(b.left)}–${Math.round(b.right)})`);
  }
  // Text overflowing its own box with nothing to say so.
  for (const el of atoms) {
    const s = getComputedStyle(el);
    if (!ownText(el) || s.textOverflow === 'ellipsis' || el.matches('input, select, textarea')) continue;
    if (/(hidden|clip)/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 1) said.push(`${named(el)}: its text is cut off`);
  }
  // Small text.
  for (const el of atoms) {
    const size = parseFloat(getComputedStyle(el).fontSize);
    if (ownText(el) && size < 11) said.push(`${named(el)}: ${size}px text`);
  }
  // Things on top of each other.
  // (Each line of a wrapped line of text on its own, the part in sight.)
  const lines = el => {
    const c = seen.get(el);
    return [...el.getClientRects()].map(r => ({ left: Math.max(r.left, c.left), right: Math.min(r.right, c.right), top: Math.max(r.top, c.top), bottom: Math.min(r.bottom, c.bottom) }))
      .filter(r => r.right - r.left > 0.5 && r.bottom - r.top > 0.5);
  };
  const meet = (ra, rb) => Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left) > 2 && Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top) > 2;
  const rects = atoms.filter(el => !el.closest('.mark-preview, .chart, .spark, .sel, .toast, .logo-grid .mine') && !el.matches('img, video')).map(el => [el, lines(el)]);
  for (let i = 0; i < rects.length; i++) {
    const [a, ra] = rects[i];
    for (let j = i + 1; j < rects.length; j++) {
      const [b, rb] = rects[j];
      if (a.contains(b) || b.contains(a)) continue;
      if (ra.some(x => rb.some(y => meet(x, y)))) said.push(`${named(a)} and ${named(b)} overlap`);
    }
  }
  // A dialog: on the screen, its buttons in sight, and only its body scrolls.
  if (dialog) {
    const r = dialog.getBoundingClientRect();
    if (r.top < -1 || r.left < -1 || r.bottom > H + 1 || r.right > W + 1) said.push(`the dialog doesn't fit the screen (${Math.round(r.width)}×${Math.round(r.height)} at ${Math.round(r.left)},${Math.round(r.top)})`);
    if (dialog.scrollHeight > dialog.clientHeight + 1) said.push('the dialog scrolls as a whole, not just its body');
    const foot = dialog.querySelector('.dlg-foot');
    if (foot && shown(foot)) {
      const f = foot.getBoundingClientRect();
      if (f.bottom > H + 1) said.push('the dialog’s buttons are below the screen');
    }
  }
  // Small tap targets, on a touch screen: a tap 18.5px above, below, left
  // and right of a target's middle still lands on it (an area it reaches
  // past its edges counts; the missing pixel and a half are for rounding).
  // Links in a sentence don't count. Each is scrolled into sight to try it;
  // then everything is scrolled back.
  if (touch) {
    const scrolled = [document.scrollingElement, ...all].filter(e => e.scrollTop || e.scrollLeft).map(e => [e, e.scrollTop, e.scrollLeft]);
    for (const el of atoms) {
      if (!el.matches('button, a[href], select, input:not([type=hidden]), textarea, summary') || el.disabled) continue;
      if (el.matches('a, .linkish, .linkbtn') && [...el.parentElement.childNodes].some(n => n !== el && n.nodeType === 3 && n.textContent.trim())) continue;
      const target = el.matches('input[type=checkbox], input[type=radio]') ? el.closest('label') || el : el;
      target.scrollIntoView({ block: 'center', inline: 'center' });
      const r = target.getBoundingClientRect();
      const x = (r.left + r.right) / 2, y = (r.top + r.bottom) / 2;
      // (A point a box scrolls out of sight can't be tapped: it doesn't count.)
      let clip = { left: -1e9, right: 1e9, top: -1e9, bottom: 1e9 };
      for (let q = target.parentElement; q && q !== document.body; q = q.parentElement) {
        const s = getComputedStyle(q);
        if (s.overflowX === 'visible' && s.overflowY === 'visible') continue;
        const c = q.getBoundingClientRect();
        clip = { left: Math.max(clip.left, c.left), right: Math.min(clip.right, c.right), top: Math.max(clip.top, c.top), bottom: Math.min(clip.bottom, c.bottom) };
      }
      const on = (px, py) => px < clip.left || px > clip.right || py < clip.top || py > clip.bottom || target.contains(document.elementFromPoint(px, py));
      if (!(on(x, y - 18.5) && on(x, y + 18.5) && on(x - 18.5, y) && on(x + 18.5, y))) {
        said.push(`${named(target)}: a ${Math.round(r.width)}×${Math.round(r.height)} tap target`);
      }
    }
    for (const e of [document.scrollingElement, ...all]) if (e.scrollTop || e.scrollLeft) { e.scrollTop = 0; e.scrollLeft = 0; }
    for (const [e, top, left] of scrolled) { e.scrollTop = top; e.scrollLeft = left; }
  }
  return [...new Set(said)];
}
"""


def size_of(text: str) -> tuple[int, int]:
    w, h = text.split("x")
    return int(w), int(h)


class Look:
    """Saves each view at one size, in one theme, as one person, and notes
    what's wrong with it."""

    def __init__(self, page: Page, folder: Path, prefix: str, touch: bool, said: list[str]):
        self.page, self.folder, self.prefix, self.touch, self.said = (
            page, folder, prefix, touch, said,
        )  # fmt: skip

    def __call__(self, name: str, full: bool = False) -> None:
        page = self.page
        page.wait_for_timeout(350)
        path = self.folder / f"{self.prefix}-{name}.png"
        if full:
            whole_page(page, path)
        else:
            page.screenshot(path=str(path))
        for problem in page.evaluate(MEASURE, self.touch):
            self.said.append(f"{path.relative_to(self.folder.parent)}: {problem}")
        # Words a program left by mistake ("null", "undefined", "[object
        # Object]"), anywhere in sight.
        stray = page.evaluate(
            """() => { const out = []; const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
              for (let n = walk.nextNode(); n; n = walk.nextNode()) {
                const t = n.textContent.trim();
                if (!n.parentElement || n.parentElement.closest('script, style, [hidden]')) continue;
                if (t === 'null' || t === 'undefined' || t.includes('[object ')) out.push(t);
              } return out; }"""
        )
        if stray:
            self.said.append(
                f"{path.relative_to(self.folder.parent)}: stray words on the page: {stray}"
            )
        # The name as it's shown: always tapiOca. innerText is the text as
        # drawn, so a text-transform that makes it "TAPIOCA" counts (the
        # audit of 1.34.0: setup's last step on a phone).
        misnamed = page.evaluate(
            r"""() => [...new Set(document.body.innerText.match(/(?<!\w)(?:TAPIOCA|Tapioca|TapiOca)(?!\w)/g) || [])]"""
        )
        if misnamed:
            self.said.append(
                f"{path.relative_to(self.folder.parent)}: check failed: the name as shown: "
                f"{misnamed}, not tapiOca"
            )
        # A dialog whose body scrolls: its end too.
        scrolled = page.evaluate(
            """() => { const b = [...document.querySelectorAll('dialog[open] .dlg-body')].pop();
                       if (!b || b.scrollHeight <= b.clientHeight + 1) return false;
                       b.scrollTop = b.scrollHeight; return true; }"""
        )
        if scrolled:
            page.wait_for_timeout(150)
            page.screenshot(path=str(self.folder / f"{self.prefix}-{name}-end.png"))
            page.evaluate(
                "() => { const b = [...document.querySelectorAll('dialog[open] .dlg-body')].pop(); b.scrollTop = 0; }"
            )

    def expect(self, what: str, got: Any, wanted: Any) -> None:
        """A check of what the page does: noted, with "check failed", unless
        `got` is `wanted`."""
        if got != wanted:
            self.said.append(
                f"{self.folder.name}/{self.prefix}: check failed: {what}: {got!r}, not {wanted!r}"
            )


def whole_page(page: Page, path: Path) -> None:
    """A screenshot of the whole page, a screen at a time. (Chromium's own
    whole-page screenshot forgets that it's a touch screen, from then on.)"""
    size = page.viewport_size
    assert size is not None
    # (The page's own arrows, at the window's edges, aren't part of the
    # page: without them, so the screens join up.)
    page.evaluate(
        "() => document.querySelector('.more-arrows.page')?.style.setProperty('display', 'none')"
    )
    height = page.evaluate("document.documentElement.scrollHeight")
    sheet = Image.new("RGB", (size["width"], height))
    top = 0
    while True:
        page.evaluate(f"window.scrollTo(0, {top})")
        page.wait_for_timeout(60)
        at = round(page.evaluate("window.scrollY"))  # (the last screen stops at the foot)
        sheet.paste(Image.open(io.BytesIO(page.screenshot())).convert("RGB"), (0, at))
        top = at + size["height"]
        if top >= height:
            break
    page.evaluate("window.scrollTo(0, 0)")
    page.evaluate(
        "() => document.querySelector('.more-arrows.page')?.style.removeProperty('display')"
    )
    sheet.save(path)


def close_dialogs(page: Page) -> None:
    page.evaluate("() => document.querySelectorAll('dialog[open]').forEach(d => d.close())")


def tab(page: Page, name: str) -> None:
    page.click(f".tab[data-tab='{name}']")
    page.wait_for_timeout(500)


def until(page: Page, script: str, arg: Any = None) -> bool:
    """Waits (up to 5 seconds) for `script` to be true in the page."""
    try:
        page.wait_for_function(script, arg=arg, timeout=5000)
    except PlaywrightTimeout:
        return False
    return True


def link_code(page: Page, look: Look) -> None:
    """Link an app, with the Link dialog open: the code's dash goes in by
    itself as it's typed, backspacing over it works, and so does pasting the
    code (inserted at once, in place of what's there)."""
    code = page.locator("#linkCode")
    code.press_sequentially("k7qm4dpx")
    look.expect("Link an app, k7qm4dpx typed", code.input_value(), "K7QM-4DPX")
    look("link-code")
    # (From K7QM-4D, three more: the 4's backspace takes the dash with it, as
    # nothing follows it, and the third takes the M.)
    for presses, wanted in ((2, "K7QM-4D"), (3, "K7Q")):
        for _ in range(presses):
            code.press("Backspace")
        look.expect(f"Link an app, then {presses} backspaces", code.input_value(), wanted)
    code.select_text()
    page.keyboard.insert_text("k7qm4dpx")
    look.expect("Link an app, k7qm4dpx pasted", code.input_value(), "K7QM-4DPX")
    # (The audit of 1.32.0: pasted with spaces around it, the box's length
    # cut its last letter off before the dash went in.)
    code.select_text()
    page.keyboard.insert_text(" K7QM-4DPX ")
    look.expect("Link an app, pasted with spaces", code.input_value(), "K7QM-4DPX")


TUNER_NONE = "List at least one device, or choose Plex server only."


def no_null(page: Page, look: Look, what: str) -> None:
    """Nothing in Tuner access shows "null" or "undefined" as words."""
    text = page.inner_text("#tunerBody")
    look.expect(
        f"{what}: no null or undefined shown", [w for w in ("null", "undefined") if w in text], []
    )


def no_toast(page: Page) -> None:
    """Puts away a message saying a change was saved (it goes by itself in a
    few seconds), so it doesn't cover what's looked at."""
    page.evaluate("() => { document.querySelector('#toast').hidden = true; }")


def tuner_views(page: Page, look: Look) -> None:
    """Tuner access, on the Access tab: open, with Any device on my home
    network chosen, then Only these devices (the list, the warning, Recent
    tuner connections), and with none listed; each control's change checked;
    then back as it was."""
    sum_is = "t => document.querySelector('#tunerSum').textContent === t"
    status = "#tunerBody [role=status]"
    page.evaluate(
        "() => document.querySelectorAll('#tab-access details.arr').forEach(d => d.open = d.id === 'tunerPanel')"
    )
    page.wait_for_selector("#tunerBody input[value=only]")
    look.expect(
        "Tuner access's summary", page.inner_text("#tunerSum"), "Any device on my home network"
    )
    no_null(page, look, "access-tuner")
    look("access-tuner", full=True)
    page.check("#tunerBody input[value=only]")
    until(page, sum_is, "Only 2 devices")
    look.expect("Tuner access, Only chosen", page.inner_text("#tunerSum"), "Only 2 devices")
    look.expect(
        "Tuner access's warning, Plex not listed",
        "172.17.0.5" in (page.text_content("#tunerBody .reach.down") or ""),
        True,
    )
    no_toast(page)
    no_null(page, look, "access-tuner-only")
    look("access-tuner-only", full=True)
    listed = page.locator("#tunerBody table").first

    def remove(name: str) -> None:
        listed.locator("tr", has_text=name).locator("button:has-text('Remove')").click()

    # Remove, down to the last (refused, and said why), then Add it back.
    remove("Den PC")
    until(page, sum_is, "Only 1 device")
    look.expect("Tuner access, Remove", page.inner_text("#tunerSum"), "Only 1 device")
    remove("192.168.1.30")
    page.wait_for_timeout(300)
    look.expect("Tuner access, Remove the last", page.inner_text(status), TUNER_NONE)
    look.expect("Tuner access, the last kept", page.inner_text("#tunerSum"), "Only 1 device")
    page.fill("#tunerAddress", "nas.local")
    page.click("#tunerBody button:has-text('Add')")
    not_an_address = "Enter a device's IP address, such as 192.168.1.20"
    until(
        page,
        "t => document.querySelector('#tunerBody [role=status]').textContent === t",
        not_an_address,
    )
    look.expect("Tuner access, Add a name, not an address", page.inner_text(status), not_an_address)
    page.fill("#tunerAddress", "192.168.1.41")
    page.fill("#tunerName", "Den PC")
    page.click("#tunerBody button:has-text('Add')")
    until(page, sum_is, "Only 2 devices")
    look.expect("Tuner access, Add", page.inner_text("#tunerSum"), "Only 2 devices")
    look.expect("Tuner access, Add empties its boxes", page.input_value("#tunerAddress"), "")
    # Allow, beside a recent connection; then Plex server only (it asks first).
    recent = page.locator("#tunerBody table").last
    recent.locator("tr", has_text="Unknown device").locator("button:has-text('Allow')").click()
    until(page, sum_is, "Only 3 devices")
    look.expect("Tuner access, Allow", page.inner_text("#tunerSum"), "Only 3 devices")
    asked: list[str] = []

    def accept(dialog) -> None:
        asked.append(dialog.message)
        dialog.accept()

    page.once("dialog", accept)
    page.click("#tunerBody button:has-text('Plex server only')")
    until(page, sum_is, "Only 1 device")
    look.expect("Tuner access, Plex server only", page.inner_text("#tunerSum"), "Only 1 device")
    look.expect(
        "Tuner access, Plex server only asks first, naming Plex's address",
        asked,
        ["Plex server only lists just Plex’s address, 172.17.0.5. 3 other devices can’t use the "
         "tuner then. Go ahead?"],
    )  # fmt: skip
    look.expect(
        "Tuner access, Plex server only lists Plex",
        page.inner_text("#tunerBody table >> nth=0 >> td >> nth=1"),
        "172.17.0.5",
    )
    look.expect("Tuner access, no warning then", page.locator("#tunerBody .reach.down").count(), 0)
    sign_in_off = "Sign-in is off, so anyone on your home network can open this page"
    look.expect(
        "Tuner access, sign-in on: no note", sign_in_off in page.inner_text("#tunerBody"), False
    )
    page.evaluate("async () => { me.required = false; renderTuner(await api('/api/tuner')); }")
    look.expect(
        "Tuner access, sign-in off: a note", sign_in_off in page.inner_text("#tunerBody"), True
    )
    page.evaluate("async () => { me.required = true; renderTuner(await api('/api/tuner')); }")
    # Only these devices, with none listed: nothing is saved.
    page.evaluate("() => api('/api/tuner', { method: 'PUT', body: { only: false, devices: [] } })")
    page.evaluate("() => loadTuner()")
    page.wait_for_selector("#tunerBody input[value=only]:not(:checked)")
    page.check("#tunerBody input[value=only]")
    page.wait_for_selector("#tunerAddress")
    look.expect("Tuner access, Only with none listed", page.inner_text(status), TUNER_NONE)
    look.expect(
        "Tuner access, Only with none listed saves nothing",
        page.evaluate("() => api('/api/tuner').then(t => t.only)"),
        False,
    )
    page.evaluate("() => document.querySelector('#tunerPanel').scrollIntoView()")
    no_toast(page)
    no_null(page, look, "access-tuner-none")
    look("access-tuner-none")
    # Any device again, as it was.
    page.check("#tunerBody input[value=any]")
    look.expect("Tuner access, Any again", page.locator("#tunerAddress").count(), 0)
    page.evaluate(
        "devices => api('/api/tuner', { method: 'PUT', body: { only: false, devices } })",
        TUNER_LISTED,
    )
    page.evaluate("() => loadTuner()")
    page.wait_for_timeout(300)
    no_toast(page)


def notify_addresses(page: Page, look: Look) -> None:
    """The Logs tab's Alert notifications, with 2 addresses: a Discord
    webhook's typed first (Format switches to Discord by itself), then an
    ntfy topic added (a Slack webhook's address, typed there first, switches
    it to Slack)."""
    page.evaluate(
        "() => { const p = document.querySelector('#notifyPanel'); p.open = true; p.scrollIntoView(); }"
    )
    page.wait_for_selector("#notifyUrl")
    look.expect("Alert notifications, Format to start", page.input_value("#notifyFormat"), "text")
    look.expect("Alert notifications, one address to start", page.locator("#notifyUrl2").count(), 0)
    page.fill("#notifyUrl", "")
    page.locator("#notifyUrl").press_sequentially(DISCORD)
    look.expect(
        "Alert notifications, Format once a Discord webhook's address is typed",
        page.input_value("#notifyFormat"),
        "discord",
    )
    page.get_by_role("button", name="Add an address").click()
    page.wait_for_selector("#notifyUrl2")
    page.locator("#notifyUrl2").press_sequentially(SLACK)
    look.expect(
        "Alert notifications, Format once a Slack webhook's address is typed",
        page.input_value("#notifyFormat2"),
        "slack",
    )
    page.fill("#notifyUrl2", NTFY)
    page.select_option("#notifyFormat2", "text")
    look.expect(
        "Alert notifications, the first address's Format kept",
        page.input_value("#notifyFormat"),
        "discord",
    )
    page.evaluate("() => document.querySelector('#notifyPanel').scrollIntoView()")
    look("logs-notify")
    page.evaluate(
        "() => document.querySelector('#notifyBody .btn.primary').scrollIntoView({ block: 'end' })"
    )
    look("logs-notify-end")


def signin_answer_lost(context: Any, base: str, look: Look) -> None:
    """The sign-in page from the internet, its first question of who's
    signed in lost: the PIN's note still comes, from the next answer. (From
    1.38.0 the page shows nothing it can't be sure of, so a lost first
    answer shows Try again, and the note comes with the next one.)"""
    lost = context.new_page()
    dropped: list[str] = []

    def drop_first(route: Any) -> None:
        if dropped:
            route.continue_()
        else:
            dropped.append(route.request.url)
            route.abort()

    lost.route("**/api/access/me", drop_first)
    lost.goto(base + "/")
    if until(lost, "() => !document.querySelector('#meProblem').hidden"):
        lost.click("#meRetry")
    shown = until(lost, "() => !document.querySelector('#signinWhere').hidden")
    look.expect("the internet's PIN note, its first answer lost", (bool(dropped), shown),
                (True, True))  # fmt: skip
    lost.close()


# The arrows over a box that scrolls (`sel`), or at the window's edges for
# the page itself (no `sel`): see core.js. Whether more of it is below and
# above what shows, worked out here on its own; whether each arrow shows;
# where it is; and what a tap at its middle lands on.
ARROWS = r"""
(sel) => {
  const page = !sel;
  const el = page ? document.scrollingElement : document.querySelector(sel);
  const layer = page ? document.querySelector('.more-arrows.page') : el?.nextElementSibling;
  if (!el || !layer || !layer.matches('.more-arrows')) return null;
  if (!page) el.scrollIntoView({ block: 'nearest' });  // (in sight, to tap)
  const r = el.getBoundingClientRect();
  const box = page ? { top: 0, bottom: innerHeight, left: 0, right: document.documentElement.clientWidth }
    : { top: r.top + el.clientTop, bottom: r.top + el.clientTop + el.clientHeight, left: r.left + el.clientLeft, right: r.left + el.clientLeft + el.clientWidth };
  const shown = page ? innerHeight : el.clientHeight;
  const up = layer.querySelector('.more-up'), down = layer.querySelector('.more-down');
  const arrow = a => {
    if (!a.checkVisibility()) return null;
    const c = a.querySelector('svg').getBoundingClientRect();
    const x = (c.left + c.right) / 2, y = (c.top + c.bottom) / 2;
    const hit = document.elementFromPoint(x, y);
    return {
      // (Its middle on its box's, and at that edge: inside it, by under half the chevron.)
      centered: Math.abs(x - (box.left + box.right) / 2) <= 1,
      edge: a === down ? box.bottom - c.bottom : c.top - box.top,
      size: [Math.round(c.width), Math.round(c.height)],
      // (Under it: what it's over, never the arrow.)
      through: !!hit && !layer.contains(hit) && (page || el.contains(hit)),
    };
  };
  // (The page: more below while the last footer that shows ends below the
  // window; the empty space under it is nothing more to see: 1.36.4.)
  const foot = page ? [...document.querySelectorAll('.foot')].filter(f => f.getClientRects().length).pop() : null;
  return {
    below: foot ? foot.getBoundingClientRect().bottom - innerHeight > 1 : el.scrollHeight - shown - el.scrollTop > 1,
    above: el.scrollTop > 1,
    footBottom: foot ? foot.getBoundingClientRect().bottom : null,
    hiddenBelow: el.scrollHeight - shown - el.scrollTop,
    up: arrow(up), down: arrow(down),
    hidden: layer.getAttribute('aria-hidden'), clicks: getComputedStyle(layer).pointerEvents,
    focusable: layer.querySelectorAll('[tabindex], a, button, input').length,
  };
}
"""


def arrows(page: Page, look: Look, what: str, sel: str | None = None) -> dict | None:
    """Checks the arrows over `sel` (or the page's): the down arrow just
    while more is below what shows, the up arrow just while more is above,
    each at its edge, centered, 32px, and a tap at its middle landing on
    what's under it; hidden from screen readers and never focused."""
    page.wait_for_timeout(120)  # (they're kept right once a frame)
    got = page.evaluate(ARROWS, sel)
    if got is None:
        look.expect(f"{what}: has its arrows", "none", "its arrows")
        return None
    look.expect(f"{what}: the down arrow just while more is below", bool(got["down"]), got["below"])
    look.expect(f"{what}: the up arrow just while more is above", bool(got["up"]), got["above"])
    for name in ("down", "up"):
        a = got[name]
        if not a:
            continue
        look.expect(f"{what}: the {name} arrow's middle on its box's", a["centered"], True)
        look.expect(f"{what}: the {name} arrow at its edge", 0 <= a["edge"] <= 16, True)
        look.expect(f"{what}: the {name} arrow 32px", a["size"], [32, 32])
        look.expect(
            f"{what}: a tap on the {name} arrow goes to what's under it", a["through"], True
        )
    look.expect(f"{what}: the arrows hidden from screen readers", got["hidden"], "true")
    look.expect(f"{what}: the arrows never clicked", got["clicks"], "none")
    look.expect(f"{what}: nothing in the arrows focused", got["focusable"], 0)
    return got


def scroll(page: Page, sel: str | None, to_end: bool) -> None:
    """Scrolls `sel` (or the page) to its end, or back to its top."""
    page.evaluate(
        """([sel, end]) => { const el = sel ? document.querySelector(sel) : document.scrollingElement;
                             el.scrollTop = end ? el.scrollHeight : 0; }""",
        [sel, to_end],
    )


def scrolled_arrows(page: Page, look: Look, what: str, sel: str | None = None) -> bool:
    """`sel`'s (or the page's) arrows, then scrolled to its end and back: at
    its end, the up arrow and no down arrow. Whether it ran past what shows."""
    got = arrows(page, look, what, sel)
    if not got or not got["below"]:
        return False
    scroll(page, sel, True)
    end = arrows(page, look, f"{what}, scrolled to its end", sel)
    if end:
        look.expect(
            f"{what}, scrolled to its end: the up arrow, no down arrow",
            (bool(end["up"]), bool(end["down"])),
            (True, False),
        )
    scroll(page, sel, False)
    return True


def short_dialog(page: Page, look: Look) -> None:
    """A dialog with a line of words: no arrows."""
    page.evaluate("() => notice('Saved', h('p', {}, 'Your changes are saved.'))")
    got = arrows(page, look, "a short dialog", "#noticeBody")
    if got:
        look.expect(
            "a short dialog: no arrows", (bool(got["up"]), bool(got["down"])), (False, False)
        )
    close_dialogs(page)


def footer_arrow(page: Page, look: Look, what: str) -> None:
    """(1.36.4, the owner in Safari: two stations, and the page's down arrow
    with nothing below the footer.) The page's down arrow only while
    something is below the window: at a window that hides only the page's
    empty space under the footer, none; at one that hides the footer, it
    shows. The window is put back as it was."""
    size = page.viewport_size
    assert size is not None
    page.evaluate("window.scrollTo(0, 0)")
    foot = page.evaluate(
        "() => { const f = [...document.querySelectorAll('.foot')].filter(f => f.getClientRects().length).pop();"
        " return f ? f.getBoundingClientRect().bottom + scrollY : null; }"
    )
    if foot is None:
        look.expect(f"{what}: a footer shows", False, True)
        return
    for name, height, down in (
        ("only the space under the footer out of sight", int(foot) + 8, False),
        ("the footer out of sight", int(foot) - 40, True),
    ):
        page.set_viewport_size({"width": size["width"], "height": height})
        page.evaluate("window.scrollTo(0, 0)")
        got = arrows(page, look, f"{what}, {name}")
        if got:
            if not down:
                look.expect(f"{what}, {name}: the footer in sight, space under it hidden",
                            (got["footBottom"] <= height, got["hiddenBelow"] > 1), (True, True))  # fmt: skip
            look.expect(f"{what}, {name}: the down arrow", bool(got["down"]), down)
    page.set_viewport_size(size)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(150)


def top_people_names(page: Page, look: Look) -> None:
    """(1.36.4, the owner: "User names are truncated in Server/Stats/Top
    People - no reason for this - plenty of room.") Names of an ordinary
    length show in full beside their bars."""
    page.evaluate(
        """() => renderTop(['egadgetboy', 'insertdisc', 'Grandma'].map((name, n) => ({
             name, plex: n < 2, hours: 3 - n, mediaHours: 0, programs: [],
             stations: [{ number: 4, name: 'Prime Time', hours: 3 - n }] })), [], null)"""
    )
    page.evaluate("() => document.querySelector('#statPeople').scrollIntoView({block: 'center'})")
    page.wait_for_timeout(150)
    cut = page.evaluate(
        "() => [...document.querySelectorAll('#statPeople .toprow .name')]"
        ".filter(n => n.scrollWidth > n.clientWidth + 1).map(n => n.textContent)"
    )
    look.expect("Top people: names of an ordinary length in full", cut, [])
    look("stats-top-people")
    page.evaluate("() => loadStats()")
    page.wait_for_timeout(300)


def log_search(page: Page, look: Look) -> None:
    """(1.37.0, the owner: "There is no SEARCH field in Logs - needs one.")
    The search box is with the log's switches, inside the page at every
    width. A word from the log narrows it to the lines that have it, in any
    case; a word that's nowhere in it says so. Cleared after."""
    box = page.locator("#logFind")
    look.expect("the log's search box shows", box.is_visible(), True)
    outside = page.evaluate(
        "() => { const r = document.querySelector('#logFind').getBoundingClientRect();"
        " return r.left < 0 || r.right > document.documentElement.clientWidth; }"
    )
    look.expect("the log's search box inside the page", outside, False)
    # (The cold audit, 1.37.0: the page's own rule for search boxes, full
    # width, won over its 260, so it took a row of its own at every width.)
    if (page.viewport_size or {}).get("width", 0) >= 768:
        wide = page.evaluate(
            "() => document.querySelector('#logFind').getBoundingClientRect().width"
        )
        look.expect("the log's search box at most 260 wide, beside the switches", wide <= 260, True)

    def lines() -> list[str]:
        return page.evaluate(
            "() => [...document.querySelectorAll('#logList .logline .msg')].map(m => m.textContent)"
        )

    def searched(q: str) -> None:
        box.fill(q)
        page.wait_for_timeout(300 + 700)  # (searched once typing pauses: logs.js)

    shown = lines()
    # (A word some lines have and others don't, so the search visibly narrows.)
    words = sorted(
        {w for line in shown for w in re.findall(r"[A-Za-z]{5,}", line)},
        key=lambda w: (sum(w.casefold() in line.casefold() for line in shown), w),
    )
    word = next(
        (w for w in words if sum(w.casefold() in s.casefold() for s in shown) < len(shown)), None
    )
    if word is None:
        look.expect("the log has words to search for", words, ["(some)"])
        return
    searched(word.upper())
    found = lines()
    look.expect(f"searching for {word.upper()!r} finds lines", bool(found), True)
    look.expect(
        f"every line found has {word!r}, in any case",
        [line for line in found if word.casefold() not in line.casefold()],
        [],
    )
    look("logs-searched")
    searched("zzqx nowhere")
    empty = page.locator("#logList").inner_text()
    look.expect("a search that finds nothing says so", "Nothing in the log has" in empty, True)
    searched("")
    look.expect("cleared, the log is back", bool(lines()), True)


def media_folder_switches(page: Page, look: Look, sp: Running) -> None:
    """(1.36.4, the owner: "Server just needs to know what folders it can
    see, and the option to toggle them on and off.") The Setup tab's Media
    folders: every one, each with its switch for tapiOca's apps, in the
    page's accent. Switching one off saves it at once (the server no longer
    shares it); on again shares it again. Sharing is put back as it was."""
    shared = sp.ctx.shared
    before = sp.call(lambda: (
        sp.ctx.db.get_meta(ondemand.META), sp.ctx.db.get_meta(ondemand.WAITING_META),
        shared.everything, shared._chosen, shared.waiting,
    ))  # fmt: skip
    media = page.evaluate("() => api('/api/app-libraries')")
    look.expect("Media folders lists every Media folder",
                page.locator("#foldersPanel tbody td:first-child strong").all_inner_texts(),
                [m["title"] for m in media["libraries"]])  # fmt: skip
    look.expect("Media folders: a switch for each, In tapiOca’s apps",
                page.locator("#foldersPanel tbody label.in-apps").all_inner_texts(),
                ["In tapiOca’s apps"] * len(media["libraries"]))  # fmt: skip
    look.expect("Media folders says nothing of Plex for a folder",
                "Plex" in page.inner_text("#foldersPanel"), False)  # fmt: skip
    look.expect("Media folders' switches in the page's accent",
                page.evaluate("""() => {
                  const accent = getComputedStyle(document.body).getPropertyValue('--accent').trim();
                  const probe = document.body.appendChild(Object.assign(document.createElement('i'), { style: `color:${accent}` }));
                  const want = getComputedStyle(probe).color; probe.remove();
                  return [...document.querySelectorAll('#foldersPanel input[type=checkbox]')]
                    .every(b => getComputedStyle(b).accentColor === want);
                }"""), True)  # fmt: skip
    first = media["libraries"][0]
    row = f"#foldersPanel tr[data-key='{first['key']}'] input[type=checkbox]"
    if not page.locator(row).is_checked():
        page.locator(row).check()
        page.wait_for_timeout(800)
    page.locator(row).uncheck()
    until(
        page, "() => [...document.querySelectorAll('.toast')].some(t => t.textContent === 'Saved')"
    )
    page.wait_for_timeout(800)
    look.expect(f"Media folders: {first['title']} switched off is no longer shared",
                sp.call(lambda: first["key"] in list(shared.keys)), False)  # fmt: skip
    look.expect(f"Media folders: {first['title']} shows switched off",
                page.locator(row).is_checked(), False)  # fmt: skip
    look("addtoplex-folders-off")
    page.locator(row).check()
    page.wait_for_timeout(800)
    look.expect(f"Media folders: {first['title']} switched on again is shared again",
                sp.call(lambda: first["key"] in list(shared.keys)), True)  # fmt: skip

    def restore() -> None:
        chosen, waits, everything, kept, was = before
        sp.ctx.db.set_metas({ondemand.WAITING_META: waits or "0"})
        if everything:
            with sp.ctx.db._lock, sp.ctx.db._conn:
                sp.ctx.db._conn.execute("DELETE FROM meta WHERE key = ?", (ondemand.META,))
        else:
            sp.ctx.db.set_meta(ondemand.META, chosen)
        shared.everything, shared._chosen, shared.waiting = everything, kept, was

    sp.call(restore)
    page.evaluate("() => loadFolderLibraries()")
    page.wait_for_timeout(500)


def signin_trusted(browser: Any, base: str, context_of: Callable[..., Any], look: Look) -> None:
    """The sign-in screen on a trusted network (1.36.0). From 1.38.0 (the
    owner, October 17: "No user appears on the server sign in page at all
    unless their user is set as Admin"), on a network that opens on Who's
    tuning in? the page is as at any home address: no one listed on a new
    browser, Jo (shown on the apps' at home) included, and no User even
    where she signed in with her password (Ari); on Sam's laptop, Continue
    on this device, never naming Sam (shown, not pressed: as after signing
    out on purpose)."""
    context = context_of({"X-Page-Peer": TRUSTED_DEVICE})
    page = context.new_page()
    page.goto(base + "/")
    until(page, "() => !document.querySelector('#signinView').hidden")
    look.page = page
    look("signin-trusted")
    look.expect("a new browser on the network: no one listed",
                (page.is_visible("#signinTrusted"), page.locator("#signinPeople .who").count()),
                (False, 0))  # fmt: skip
    look.expect("its name and password", page.is_visible("#signinName"), True)
    long_names(page, look)
    context.close()
    # Ari signs in with her password on this browser; an hour without
    # activity signs her out (her sign-in's cookie gone, the browser's kept).
    context = context_of({"X-Page-Peer": TRUSTED_DEVICE})
    signed = context.request.post(
        f"{base}/api/access/sign-in",
        data={"name": ARI["name"], "password": ARI["password"]},
        headers=PAGE,
    )  # fmt: skip
    look.expect("Ari signs in with her password", signed.ok, True)
    context.clear_cookies(name=SESSION_COOKIE)
    page = context.new_page()
    page.goto(base + "/")
    until(page, "() => !document.querySelector('#signinView').hidden")
    page.wait_for_timeout(300)
    look.page = page
    names = page.locator("#signinPeople .who-name").all_inner_texts()
    look.expect("a User is never listed, even where she signed in", names, [])
    context.close()
    context = context_of({"X-Page-Peer": SAMS_LAPTOP})
    context.add_init_script("try { sessionStorage.setItem('tapioca.signedOut', '1'); } catch {}")
    page = context.new_page()
    page.goto(base + "/")
    until(page, "() => !document.querySelector('#signinContinue').hidden")
    look.page = page
    look.expect(
        "Continue, never who",
        (page.inner_text("#signinContinue"), USER["name"] in page.inner_text("#signinView")),
        ("Continue on this device", False),
    )
    look("signin-trusted-person")
    context.close()


def long_names(page: Page, look: Look) -> None:
    """(1.37.0, the owner, October 15: "we need to accommodate longer names
    that won't get cut off", as "Bartholomew".) Who's signing in?'s cards
    grow to their names: a long one-word name on one line, never broken
    inside the word or cut; a long name of two words, whole. Put back as it
    was after."""
    page.evaluate(
        """() => showPeople([
             { id: 901, name: 'Bartholomew', pin: true },
             { id: 902, name: 'Maximiliana Fitzgerald-Worthington', pin: false },
             { id: 903, name: 'Jo', pin: true } ])"""
    )
    page.wait_for_timeout(100)
    got = page.evaluate(
        """() => [...document.querySelectorAll('#signinPeople .who-name')].map(el => {
             const r = document.createRange(); r.selectNodeContents(el);
             const box = el.closest('.who').getBoundingClientRect();
             const room = document.querySelector('#signinPeople').getBoundingClientRect();
             return { name: el.textContent, lines: r.getClientRects().length,
                      cut: el.scrollWidth > el.clientWidth + 1,
                      outside: box.left < room.left - 1 || box.right > room.right + 1 };
           })"""
    )
    by = {g["name"]: g for g in got}
    look.expect("Bartholomew on one line", by.get("Bartholomew", {}).get("lines"), 1)
    look.expect("no name cut", [g["name"] for g in got if g["cut"]], [])
    look.expect("every card inside the list", [g["name"] for g in got if g["outside"]], [])
    look("signin-trusted-long-names")
    page.evaluate("() => showPeople(me.people || [])")


def signin_by_pin(context_of: Callable[..., Any], base: str, look: Look) -> None:
    """The sign-in screen at home (1.38.0, the owner, October 17): on a
    browser where Jo (a User) and Pat (an Admin, in Light sign-in) signed in
    with their passwords (their sessions' cookies gone, the browser's kept),
    only Pat is listed, alone, so his PIN is asked at once; Use your
    password instead; Sign in with a password for anyone else; Remove from
    this browser; and his PIN gives his Admin tools."""
    context = context_of()
    for who in (JO, ADMIN):
        signed = context.request.post(f"{base}/api/access/sign-in", data=who, headers=PAGE)
        look.expect(f"{who['name']} signs in with a password", signed.ok, True)
        context.clear_cookies(name=SESSION_COOKIE)
    page = context.new_page()
    look.page = page
    page.goto(base + "/")
    if not until(page, "() => !document.querySelector('#pinForm').hidden"):
        look.expect("the sign-in screen's PIN form",
                    page.evaluate("() => location.href + ' ' + (document.body?.innerText || '').slice(0, 300)"),
                    "shown")  # fmt: skip
        context.close()
        return
    names = page.locator("#signinPeople .who-name").all_inner_texts()
    look.expect("only the Admin who signed in here is listed", names, [ADMIN["name"]])
    look.expect(
        "the PIN form's label", page.inner_text("#signinPinLabel"), f"PIN for {ADMIN['name']}"
    )
    look.expect("no Admin tab before signing in", page.locator(".tab.admin:visible").count(), 0)
    look("signin-pin")
    # His password instead: his name already there, out of sight.
    page.click("#signinOther")
    look.expect("Use your password instead",
                (page.is_visible("#signinPassword"), page.is_visible("#signinName"),
                 page.input_value("#signinName"), page.is_visible("#pinForm")),
                (True, False, ADMIN["name"], False))  # fmt: skip
    look.expect("the password's box has the focus",
                page.evaluate("() => document.activeElement.id"), "signinPassword")  # fmt: skip
    look("signin-pin-password")
    # Someone else at this browser: a name and password, the name empty.
    page.click("#signinSomeoneElse")
    look.expect("Sign in with a password: the name and password, the name empty",
                (page.is_visible("#signinName"), page.input_value("#signinName"),
                 page.is_visible("#pinForm")), (True, "", False))  # fmt: skip
    look("signin-switch")
    # His PIN: his Admin tools.
    page.locator("#signinPeople .who", has_text=ADMIN["name"]).click()
    page.fill("#signinPin", PAT_PIN)
    page.click("#pinGo")
    got = until(page, "() => !!(me && me.user && me.user.adminTools)")
    look.expect("in Light sign-in, his PIN gives his Admin tools",
                (got, page.locator(".tab.admin:visible").count() > 0), (True, True))  # fmt: skip
    context.close()
    # Remove from this browser: no one listed then.
    context = context_of()
    context.request.post(f"{base}/api/access/sign-in", data=ADMIN, headers=PAGE)
    context.clear_cookies(name=SESSION_COOKIE)
    page = context.new_page()
    look.page = page
    page.goto(base + "/")
    if until(page, "() => !document.querySelector('#signinForget').hidden"):
        page.click("#signinForget")
        until(page, "() => document.querySelector('#signinTrusted').hidden")
        look.expect("Remove from this browser",
                    (page.locator("#signinPeople .who").count(), page.inner_text("#signinStatus")),
                    (0, f"{ADMIN['name']} is no longer on this browser’s sign-in screen."))  # fmt: skip
        look("signin-forgotten")
    else:
        look.expect("Remove from this browser shows", False, True)
    context.close()


def first_paint(context_of: Callable[..., Any], base: str, look: Look) -> None:
    """(1.38.0, the owner, October 17: "they shouldn't flash for a second
    for a restricted [non Admin] user at all".) While tapiOca's answer of
    who's signed in is slow, nothing shows, an Admin tab least of all; for a
    User, no Admin tab ever shows; and when it can't be asked, the page says
    so, with Try again, and shows no tab."""
    seen = """() => ({ wrap: !document.querySelector('.wrap').hidden,
                       admin: document.querySelectorAll('.tab.admin:not([hidden])').length,
                       tabs: [...document.querySelectorAll('.tab')].filter(t => t.checkVisibility()).length,
                       problem: !document.querySelector('#meProblem').hidden })"""
    for who in (USER, ADMIN):
        context = context_of()
        signed = context.request.post(f"{base}/api/access/sign-in", data=who, headers=PAGE)
        look.expect(f"{who['name']} signs in", signed.ok, True)
        # (Any Admin tab that ever shows, noted as it happens.)
        context.add_init_script("""
          window.__adminShown = 0;
          new MutationObserver(() => {
            for (const t of document.querySelectorAll('.tab.admin'))
              if (t.checkVisibility()) window.__adminShown++;
          }).observe(document, { subtree: true, attributes: true, childList: true });""")
        # (tapiOca's answer of who's signed in, 1.5 seconds slow.)
        context.add_init_script("""
          const sent = window.fetch;
          window.fetch = (url, ...more) => String(url).includes('/api/access/me')
            ? new Promise(go => setTimeout(go, 1500)).then(() => sent(url, ...more))
            : sent(url, ...more);""")
        page = context.new_page()
        look.page = page
        page.goto(base + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(500)
        look.expect(f"{who['name']}: nothing shows before tapiOca answers",
                    page.evaluate(seen), {"wrap": False, "admin": 0, "tabs": 0, "problem": False})  # fmt: skip
        if who is USER:
            look("first-paint-waiting")
        until(page, "() => me.known")
        page.wait_for_timeout(300)
        after = page.evaluate(seen)
        if who is USER:
            look.expect("a User never sees an Admin tab",
                        (after["wrap"], after["admin"], page.evaluate("() => window.__adminShown")),
                        (True, 0, 0))  # fmt: skip
        else:
            look.expect("an Admin's tabs once tapiOca answers", (after["wrap"], after["admin"] > 0),
                        (True, True))  # fmt: skip
        context.close()
    # tapiOca can't be asked: the page says so, and shows no tab.
    context = context_of()
    context.request.post(f"{base}/api/access/sign-in", data=ADMIN, headers=PAGE)
    page = context.new_page()
    look.page = page
    page.route("**/api/access/me", lambda route: route.fulfill(status=502, body="Bad gateway"))
    page.goto(base + "/")
    until(page, "() => !document.querySelector('#meProblem').hidden")
    got = page.evaluate(seen)
    look.expect("when tapiOca can't be asked: Try again, and no tab",
                (got["problem"], got["tabs"], got["admin"], page.is_visible("#meRetry")),
                (True, 0, 0, True))  # fmt: skip
    look("first-paint-problem")
    context.close()


def plex_step(page: Page, look: Look) -> None:
    """(1.34.1, the owner) The setup's Plex step: its own checks (Plex, its
    files, tapiOca in Plex), and Copy copying the tuner's address, in the
    setup's window, at a home address (http: no clipboard to write to)."""
    page.wait_for_selector("#setupBody .copyrow button")
    until(page, "() => document.querySelectorAll('#setupBody .setup-check').length === 3")
    look.expect("the Plex step's checks",
                page.eval_on_selector_all("#setupBody .setup-check strong",
                                          "els => els.map(e => e.textContent)"),
                ["Plex", "Plex’s files", "tapiOca in Plex"])  # fmt: skip
    page.evaluate(
        """() => { window.copied = null; document.addEventListener('copy', e => {
             const t = e.target; window.copied = t && 'value' in t
               ? t.value.slice(t.selectionStart, t.selectionEnd) : String(getSelection()); }, { once: true }); }"""
    )
    page.locator("#setupBody .copyrow button").first.click()
    page.wait_for_timeout(200)
    look.expect("the Plex step's Copy copies the tuner address",
                page.evaluate("() => window.copied"),
                page.inner_text("#setupBody .copyrow code"))  # fmt: skip
    look.expect("Copied, said over the setup's window",
                page.evaluate("() => { const t = document.querySelector('#toast'); return !t.hidden && t.closest('dialog[open]') !== null && t.textContent; }"),
                "Copied")  # fmt: skip
    look("setup-plex")


def connection_test(page: Page, look: Look) -> None:
    """(1.34.1, the owner) The apps' connection test, run from the Access
    tab: its result kept with the apps' tests, and recommended from."""
    panel = page.locator("#appLimitsBody")
    panel.scroll_into_view_if_needed()
    panel.locator("button:has-text('Test the connection')").click()
    shown = until(
        page,
        "() => /Mbps at home: room for about/.test(document.querySelector('#toast').textContent)",
    )
    look.expect("Test the connection from the page: a result at home", shown, True)
    page.wait_for_timeout(500)
    look.expect("the page's test is kept with the apps' tests",
                page.locator("#appLimitsBody td", has_text="tapiOca’s page").count() > 0, True)  # fmt: skip
    look.expect("the limit away from home's label",
                page.inner_text("label[for=appLimitAway]"), "Away from home, at most")  # fmt: skip
    look("access-connection-test")


def setup_before_status(context: Any, base: str, look: Look, sp: Running) -> None:
    """(1.34.1, the owner) The setup opens for an Admin at once: never
    waiting on tapiOca's status, which asks Plex (it took 20 seconds with
    Plex down). Here the status never answers at all."""
    before = sp.call(lambda: sp.ctx.db.get_meta(SETUP_ANSWERED))
    sp.call(lambda: sp.ctx.db.set_meta(SETUP_ANSWERED, "{}"))
    early = context.new_page()
    early.route("**/api/status", lambda route: route.abort())
    early.goto(base + "/")
    opened = until(early, "() => document.querySelector('#setupDlg').open")
    look.expect("the setup opens without waiting on tapiOca's status", opened, True)
    early.close()
    sp.call(lambda: sp.ctx.db.set_meta(SETUP_ANSWERED, before))


def waiting_media_step(context: Any, base: str, look: Look, sp: Running) -> None:
    """(1.34.1, the audits) A tapiOca updated from before 1.34.1 whose
    Admin never chose its Media folders: setup's Media step offers every
    one, ticked, and going on shares them. While they can't be listed
    (Plex down), going on shares nothing, and the question stays to ask."""
    shared = sp.ctx.shared
    before = sp.call(lambda: (
        sp.ctx.db.get_meta(SETUP_ANSWERED), sp.ctx.db.get_meta(ondemand.META),
        sp.ctx.db.get_meta(ondemand.WAITING_META), shared.everything, shared._chosen, shared.waiting,
    ))  # fmt: skip
    answered = json.dumps({**setup_questions.QUESTIONS, "library": 1})

    def waiting() -> None:
        sp.ctx.db.set_metas(
            {SETUP_ANSWERED: answered, ondemand.META: "[]", ondemand.WAITING_META: "1"}
        )
        shared.everything, shared._chosen, shared.waiting = False, (), True

    def to_media_step(page: Page) -> None:
        page.goto(base + "/")
        until(page, "() => document.querySelector('#setupDlg').open")
        # (Next, step by step: on a phone the steps' list is hidden.)
        for _ in range(4):
            if "Media in tapiOca" in page.inner_text("#setupBody h4.wstep"):
                break
            page.locator("#setupFoot .btn.primary").click()
            page.wait_for_timeout(600)
        page.wait_for_selector("#setupBody .playback", timeout=10_000)

    # Plex down: nothing listed; going on shares nothing and asks again.
    sp.call(waiting)
    down = context.new_page()
    down.route("**/api/app-libraries", lambda route: route.fulfill(json={
        "libraries": [], "shared": [], "everything": False, "waiting": True,
        "problem": "Plex isn’t answering, so tapiOca can’t list your Media folders right now.",
        "whenSlow": {"home": "offer", "away": "switch"}, "evenSound": True, "playing": 0,
    }) if route.request.method == "GET" else route.continue_())  # fmt: skip
    to_media_step(down)
    until(
        down,
        "() => /can’t list your Media folders/.test(document.querySelector('#setupBody').textContent)",
    )
    down.locator("#setupFoot .btn.primary").click()
    down.wait_for_timeout(800)
    down.click("#closeSetup")  # (✕: what's shown counts as answered, but not this)
    down.wait_for_timeout(500)
    look.expect("Plex down at the waiting Media step: nothing shared",
                sp.call(lambda: (list(shared.keys), shared.waiting)), ([], True))  # fmt: skip
    look.expect("Plex down at the waiting Media step: asked again",
                "library" in sp.call(lambda: setup_questions.pending(sp.ctx.db)), True)  # fmt: skip
    down.close()
    # Listed: every one ticked, said so; Next shares them all.
    sp.call(waiting)
    page = context.new_page()
    to_media_step(page)
    boxes = page.locator(
        "#setupBody .playback input[type=checkbox]:not(#setupEvenSound)"
    )  # (folders only)
    look.expect("the waiting Media step ticks every folder",
                all(boxes.nth(n).is_checked() for n in range(boxes.count())) and boxes.count() > 0, True)  # fmt: skip
    look.expect("the waiting Media step says none are shared yet",
                "No Media folders are shared in tapiOca’s apps yet" in page.inner_text("#setupBody"), True)  # fmt: skip
    look("setup-media-waiting")
    ticked = boxes.count()
    page.locator("#setupFoot .btn.primary").click()
    page.wait_for_timeout(800)
    look.expect("going on from the waiting Media step shares every folder",
                sp.call(lambda: (len(list(shared.keys)), shared.waiting)), (ticked, False))  # fmt: skip
    page.close()

    def restore() -> None:
        answers, chosen, waits, everything, kept, was = before
        sp.ctx.db.set_metas({SETUP_ANSWERED: answers, ondemand.WAITING_META: waits or "0"})
        if everything:
            with sp.ctx.db._lock, sp.ctx.db._conn:
                sp.ctx.db._conn.execute("DELETE FROM meta WHERE key = ?", (ondemand.META,))
        else:
            sp.ctx.db.set_meta(ondemand.META, chosen)
        shared.everything, shared._chosen, shared.waiting = everything, kept, was

    sp.call(restore)

    # (1.36.4) Every Media folder shared, those added later too: Even sound turned off in
    # setup's step, and its words, tick its own box, and going on keeps every folder shared.
    def everything_shared() -> None:
        sp.ctx.db.set_metas({SETUP_ANSWERED: answered})  # (setup opens, at its Media step)
        shared.everything, shared.waiting = True, False

    sp.call(everything_shared)
    page = context.new_page()
    to_media_step(page)
    page.locator("label[for=setupEvenSound]").click()
    look.expect("Even sound's words in setup tick setup's own box",
                page.locator("#setupEvenSound").is_checked(), False)  # fmt: skip
    page.locator("#setupFoot .btn.primary").click()
    page.wait_for_timeout(800)
    look.expect("Even sound off in setup keeps every Media folder shared, those added later too",
                sp.call(lambda: (shared.everything, shared.even_sound)), (True, False))  # fmt: skip
    page.close()
    sp.call(lambda: shared.save_even_sound(True))
    # (1.36.4's third audit) Only "When playing can't keep up" changed on the Access tab:
    # every Media folder stays shared, those added later too.
    sp.call(everything_shared)
    page = context.new_page()
    page.goto(base + "/")
    page.wait_for_timeout(800)
    page.evaluate("document.querySelector('#closeSetup')?.click()")
    tab(page, "access")
    page.evaluate("document.querySelector('#appLibrariesPanel').open = true")
    page.wait_for_selector("#appLibrariesBody select")
    page.select_option("#appLibrariesBody select >> nth=0", "switch")
    page.locator("#appLibrariesBody .btn.primary").click()
    page.wait_for_timeout(800)
    look.expect("only When playing can't keep up changed keeps every Media folder shared",
                sp.call(lambda: (shared.everything, shared.when_slow["home"])), (True, "switch"))  # fmt: skip
    page.close()
    sp.call(lambda: shared.save_when_slow("offer", shared.when_slow["away"]))
    sp.call(restore)


def admin_views(page: Page, look: Look, only: set[str] | None, sp: Running) -> None:
    """What an Admin sees: every tab, and every dialog and panel they open."""

    def wanted(name: str) -> bool:
        return not only or name in only or name.split("-")[0] in only

    if wanted("stations"):
        page.evaluate(
            "() => document.querySelector('#channels details.more')?.setAttribute('open', '')"
        )
        look("stations", full=True)
        footer_arrow(page, look, "the Stations tab")
    if wanted("editor"):
        page.click("#newChannel")
        page.wait_for_selector("#libItems .pick")
        look("editor")
        page.evaluate(
            "() => document.querySelectorAll('#editor details.group').forEach(g => g.open = true)"
        )
        look("editor-groups")
        page.click("[data-introkind='video']")
        page.evaluate(
            "() => document.querySelector('#bumperSet').scrollIntoView({block: 'center'})"
        )
        look("editor-bumper")
        page.evaluate("() => document.querySelector('#editor .dlg-body').scrollTop = 0")
        page.click("[data-pick='filter']")
        page.wait_for_timeout(600)
        look("editor-filter")
        page.click("[data-pick='titles']")
        page.click("#chooseLogo")
        page.wait_for_selector("#logoGrid button")
        look("editor-logos")
        close_dialogs(page)
        page.click("#channels .channel .actions button:has-text('Edit')")
        page.wait_for_selector("#libItems .pick")
        look("editor-edit")
        close_dialogs(page)
    if wanted("guide"):
        page.click("#channels .channel .actions button:has-text('Guide')")
        page.wait_for_selector("#guideList .gitem")
        look("guide")
        close_dialogs(page)
    if wanted("smart"):
        page.click("#smartStations")
        page.wait_for_timeout(800)
        look("smart")
        page.click("[data-smart='split']")
        page.wait_for_timeout(800)
        look("smart-split")
        close_dialogs(page)
    if wanted("collections"):
        page.click("#fromCollections")
        page.wait_for_selector("#colList .pick")
        look("collections")
        close_dialogs(page)
    if wanted("notice"):
        page.evaluate(
            "() => madeNotice([{number: 30, name: 'Holiday Movies'}, {number: 31, name: 'Saturday Morning'}], ['80s Favorites: Plex didn’t answer'])"
        )
        look("notice")
        close_dialogs(page)
    if wanted("account"):
        page.click("#userPill")
        look("account")
        page.click("#openLink")
        look("link")
        link_code(page, look)
        close_dialogs(page)
    if wanted("setup"):
        # (As if no Admin had said whether the update check may look: its
        # box in the last step isn't ticked.)
        sp.unanswered()
        page.evaluate("() => runSetup()")
        page.wait_for_selector("#setupDlg[open] .setup-check, #setupDlg[open] .playback")
        page.wait_for_timeout(1500)
        steps = page.locator(".setup-nav button").count()
        ran_on = []
        for n in range(steps):
            look(f"setup-{n + 1}")
            if page.inner_text("#setupBody h4.wstep").endswith("· Plex"):
                plex_step(page, look)
            if scrolled_arrows(page, look, f"setup step {n + 1}", "#setupBody"):
                if not ran_on:
                    # The first that does, partway down: both arrows.
                    page.evaluate(
                        "() => { const b = document.querySelector('#setupBody'); b.scrollTop = (b.scrollHeight - b.clientHeight) / 2; }"
                    )
                    got = arrows(page, look, f"setup step {n + 1}, partway down", "#setupBody")
                    if got:
                        look.expect(
                            f"setup step {n + 1}, partway down: both arrows",
                            (bool(got["up"]), bool(got["down"])),
                            (True, True),
                        )
                    look(f"setup-{n + 1}-partway")
                    scroll(page, "#setupBody", False)
                ran_on.append(n + 1)
            if n < steps - 1:
                page.click("#setupFoot .btn.primary")
                page.wait_for_timeout(700)
        # (On a phone, some step runs past the screen: its arrows were checked.)
        if (page.viewport_size or {}).get("width", 0) <= 430:
            look.expect("setup on a phone: a step that runs past the screen", bool(ran_on), True)
        look.expect(
            "setup's last step: the update check isn't ticked before an Admin answers",
            page.is_checked("#setupBody label:has-text('Tell me when a new tapiOca') input"),
            False,
        )
        close_dialogs(page)
        sp.call(lambda: sp.ctx.releases.save(True))  # (as it was, for the other views)
        short_dialog(page, look)
    if wanted("addtoplex"):
        tab(page, "setup")
        look("addtoplex", full=True)
        # (1.34.1) The INFO station's panel: there's one, on 99.
        page.wait_for_selector("#infoPanel p")
        look.expect(
            "the INFO station's panel", "INFO is station 99" in page.inner_text("#infoPanel"), True
        )
        # (1.35.0) Your own folders: the two Media folders of tapiOca's own,
        # and adding one, its folders chosen from inside the media folder.
        # (1.36.4: among every Media folder, under Media folders; the rows
        # with Read again are tapiOca's own.)
        page.wait_for_selector("#foldersPanel table.folder-libs")
        page.evaluate(
            "() => document.querySelector('#foldersPanel').scrollIntoView({block: 'center'})"
        )
        own = "#foldersPanel tbody tr:has(button:text-is('Read again')) td:first-child"
        look.expect("Your own folders lists both",
                    page.locator(f"{own} strong").all_inner_texts(),
                    ["Our shows", "Our movies"])  # fmt: skip
        look.expect("Your own folders counts what's in them",
                    page.locator(f"{own} div.small").all_inner_texts(),
                    ["Shows · 2 shows, 6 episodes", "Movies · 2 movies"])  # fmt: skip
        look("addtoplex-folders")
        media_folder_switches(page, look, sp)
        page.click("#addFolderLibrary")
        page.wait_for_selector("#flFolders .pick")
        look.expect("Add a Media folder lists the media folder's folders",
                    page.locator("#flFolders .pick span:first-child").all_inner_texts(),
                    ["Home Videos", "Movies", "TV"])  # fmt: skip
        look("folder-dialog")
        page.click("#flFolders .pick:has-text('TV')")
        page.wait_for_selector("#flPath .here")
        page.click("#flPath button:has-text('Add this folder')")
        page.wait_for_selector("#flChosen .sel")
        look.expect("Add this folder chooses it", page.inner_text("#flChosen .sel"), "TV\n×")
        look("folder-dialog-chosen")
        page.click("#closeFolderLib")
        # The question a tapiOca updated from before 1.34.0 asks once,
        # then Yes: the New versions panel shows the answer, and the banner a
        # newer tapiOca brings (hidden, as Not now, in the other views)
        # shows what it says; Not now hides it, for that version only.
        sp.unanswered()
        page.evaluate(f"() => {{ localStorage.removeItem('{NOT_NOW}'); return loadUpdates(); }}")
        page.wait_for_selector("#updateBanner:not([hidden]) button:has-text('Yes, tell me')")
        page.evaluate("() => window.scrollTo(0, 0)")
        look.expect("the update check's question",
                    page.inner_text("#updateBanner .update-title strong"),
                    "Should tapiOca tell you when a new version is out?")  # fmt: skip
        look.expect("New versions, before an answer: not ticked", page.is_checked("#updateCheckOn"),
                    False)  # fmt: skip
        look("update-question")
        page.click("#updateBanner button:has-text('Yes, tell me')")
        page.wait_for_selector("#updateBanner .update-title strong:has-text('is available')")
        look.expect("Yes: New versions shows it", page.is_checked("#updateCheckOn"), True)
        page.evaluate("() => window.scrollTo(0, 0)")
        look.expect("the update banner", page.inner_text("#updateBanner .update-title strong"),
                    f"tapiOca {NEWER} is available.")  # fmt: skip
        look.expect("the update banner's steps", page.inner_text("#updateBanner .update-steps p"),
                    "To update with Docker Compose:")  # fmt: skip
        look.expect("the update banner's command", page.inner_text("#updateBanner code"),
                    "docker compose up -d --pull always")  # fmt: skip
        look("update-banner")
        page.click("#updateBanner button:has-text('Not now')")
        look.expect("Not now hides the banner", page.is_hidden("#updateBanner"), True)
        # (1.34.1, the owner) The header's pill stays, and brings it back.
        look.expect("after Not now, the header's pill says a newer one is out",
                    page.inner_text("#updatePill") if page.is_visible("#updatePill") else None,
                    f"tapiOca {NEWER} is out" if (page.viewport_size or {}).get("width", 0) > 560
                    else "Update")  # fmt: skip
        page.evaluate("() => window.scrollTo(0, 0)")
        look("update-pill")
        page.click("#updatePill")
        page.wait_for_selector("#updateBanner:not([hidden])")
        look.expect("the pill brings the banner back",
                    page.inner_text("#updateBanner .update-title strong"),
                    f"tapiOca {NEWER} is available.")  # fmt: skip
        page.click("#updateBanner button:has-text('Not now')")
        sp.newest_out("9.1.0")
        page.evaluate("() => loadUpdates()")
        page.wait_for_selector("#updateBanner:not([hidden])")
        look.expect("Not now is for that version only: a newer one shows the banner again",
                    page.inner_text("#updateBanner .update-title strong"),
                    "tapiOca 9.1.0 is available.")  # fmt: skip
        # (As it was, for the other views.)
        sp.newest_out(NEWER)
        page.evaluate(
            f"() => {{ localStorage.setItem('{NOT_NOW}', '{NEWER}'); return loadUpdates(); }}"
        )
    if wanted("access"):
        tab(page, "access")
        look("access", full=True)
        page.evaluate(
            "() => document.querySelectorAll('#tab-access details.arr').forEach(d => d.open = true)"
        )
        page.wait_for_timeout(800)
        look("access-panels", full=True)
        # (1.36.1) A reverse proxy the check came through, not trusted yet:
        # Trust this proxy, right there (Docker's own address, with its
        # warning, the longest words).
        page.evaluate("""() => { awayNow.reach = {...awayNow.reach, state: 'checking',
          detail: 'https://tv.example.com reaches tapiOca through a reverse proxy at 172.17.0.1, which isn’t a trusted proxy yet. Until it is, tapiOca can’t tell that the request came over HTTPS, so it turns apps away there. Choose Trust this proxy to fix it. Checking again in a minute to be sure.',
          trustProxy: {address: '172.17.0.1', relay: true}}; paintAway(); }""")
        page.evaluate(
            "() => document.querySelector('#awayBody .reach').scrollIntoView({block: 'center'})"
        )
        look.expect("Trust this proxy, in the away check", page.is_visible(
            "#awayBody .reach-trust button:has-text('Trust this proxy')"), True)  # fmt: skip
        look("access-away-trust")
        page.evaluate("() => loadAway()")
        page.click("#viewingBody button:has-text('Add a level')")
        page.wait_for_timeout(400)
        page.evaluate(
            "() => document.querySelector('.level-edit').scrollIntoView({block: 'center'})"
        )
        look("access-level")
        page.click(".level-edit button:has-text('Cancel')")
        # Kid, which hides some genres and a studio (1.33.0).
        page.locator("#viewingBody tr", has_text="Kid").locator("button:has-text('Edit')").click()
        page.wait_for_selector(".level-edit .sel")
        page.evaluate(
            "() => document.querySelector('.level-edit .name-pick').scrollIntoView({block: 'center'})"
        )
        look("access-level-hides")
        page.click(".level-edit button:has-text('Cancel')")
        page.evaluate(
            "() => document.querySelector('.clip-ratings').scrollIntoView({block: 'center'})"
        )
        look("access-clips")
        connection_test(page, look)
        look.expect("Viewing Levels: the level new people start on",
                    page.eval_on_selector("#newLevel", "s => s.selectedOptions[0]?.textContent"),
                    "Unrestricted")  # fmt: skip
        look.expect(
            "Add a user offers a Viewing Level", page.is_visible("#newUserLevelField"), True
        )
        row = page.locator("#userTable tr", has_text=USER["name"])
        row.locator("button:has-text('Devices')").click()
        look("access-devices")
        close_dialogs(page)
        row.locator("button:has-text('Set PIN')").click()
        look("access-pin")
        row.locator("button:has-text('Cancel')").click()
        page.wait_for_timeout(300)
        row.locator("button:has-text('What they see')").click()
        page.wait_for_selector("#userStations[open]")
        look("access-stations")
        close_dialogs(page)
        # Robin's: what's hidden and allowed for her, and finding a title.
        robin = page.locator("#userTable tr", has_text=KID["name"])
        robin.locator("button:has-text('What they see')").click()
        page.wait_for_selector("#userStations[open] .sees-part .sel")
        page.evaluate(
            "() => document.querySelectorAll('#userStations .sees-part')[1].scrollIntoView({block: 'start'})"
        )
        look("access-sees")
        search = page.locator("#userStations input[type=search]").last
        search.fill("light")
        page.wait_for_selector("#userStations .title-finds .chipbtn")
        search.scroll_into_view_if_needed()
        look("access-sees-find")
        close_dialogs(page)
        tuner_views(page, look)
    if wanted("stats"):
        tab(page, "stats")
        page.wait_for_selector("#healthTiles .gauge")
        look("stats", full=True)
        top_people_names(page, look)
    if wanted("logs"):
        tab(page, "logs")
        page.wait_for_selector("#logList .logline")
        look("logs", full=True)
        log_search(page, look)
        # The log: scrolled to its newest, at the bottom, so more is above.
        got = arrows(page, look, "the log", "#logList")
        if got:
            look.expect("the log runs past its box", got["above"], True)
            scroll(page, "#logList", False)
            arrows(page, look, "the log, scrolled to its top", "#logList")
            scroll(page, "#logList", True)
        # The page itself: at its top, more below; at its end, more above.
        page.evaluate("window.scrollTo(0, 0)")
        got = arrows(page, look, "the Logs tab")
        if got:
            look.expect("the Logs tab runs past the screen", got["below"], True)
        page.evaluate(
            "() => document.querySelector('#logList').scrollIntoView({ block: 'center' })"
        )
        page.wait_for_timeout(150)
        look("logs-arrows")
        page.evaluate("window.scrollTo(0, 0)")
        scrolled_arrows(page, look, "the Logs tab")
        page.click("#problemList details > summary")
        page.wait_for_selector("#problemList details[open] pre:not(:empty)")
        page.wait_for_timeout(300)
        look("logs-journal", full=True)
        scrolled_arrows(page, look, "a problem's journal", "#problemList details[open] pre.journal")
        notify_addresses(page, look)
    if wanted("alerts"):
        page.click("#alertsPill")
        page.wait_for_selector("#alertsDlg[open]")
        look("alerts")
        close_dialogs(page)
    if wanted("broken"):
        tab(page, "broken")
        page.evaluate(
            "() => ['#arrPanel', '#reportsPanel'].forEach(p => document.querySelector(p).open = true)"
        )
        page.wait_for_timeout(600)
        look("broken", full=True)


def user_views(page: Page, look: Look, only: set[str] | None) -> None:
    """What a User sees: the Stations and Stats tabs, and what they open."""

    def wanted(name: str) -> bool:
        return not only or name in only

    if wanted("stations"):
        look("stations", full=True)
    if wanted("editor"):
        page.click("#newChannel")
        page.wait_for_selector("#libItems .pick")
        look("editor")
        page.click("#chooseLogo")
        page.wait_for_selector("#logoGrid button")
        look("editor-logos")
        close_dialogs(page)
    if wanted("guide"):
        page.click("#channels .channel .actions button:has-text('Guide')")
        page.wait_for_selector("#guideList .gitem")
        look("guide")
        close_dialogs(page)
    if wanted("smart"):
        page.click("#smartStations")
        page.wait_for_timeout(800)
        look("smart")
        close_dialogs(page)
    if wanted("collections"):
        page.click("#fromCollections")
        page.wait_for_selector("#colList .pick")
        look("collections")
        close_dialogs(page)
    if wanted("account"):
        page.click("#userPill")
        look("account")
        page.click("#openLink")
        look("link")
        link_code(page, look)
        close_dialogs(page)
    if wanted("stats"):
        tab(page, "stats")
        look("stats", full=True)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("folder", type=Path, help="where the screenshots go")
    every = [s for group in SIZES.values() for s in group]
    ap.add_argument("--sizes", default=",".join(every), help="WxH, separated by commas")
    ap.add_argument("--themes", default=",".join(THEMES))
    ap.add_argument("--only", default="", help="views, separated by commas (stations, editor...)")
    ap.add_argument("--who", default="admin,user,signin,signin-pin,signin-trusted,first-paint")
    args = ap.parse_args()
    sizes = args.sizes.split(",")
    # Touch screens: phones and tablets (and any other size as small as a phone's).
    touch = {*SIZES["phone"], *SIZES["tablet"], *(s for s in sizes if min(size_of(s)) < 600)}
    only = set(args.only.split(",")) if args.only else None
    who = args.who.split(",")

    logging.getLogger().setLevel(logging.INFO)
    scanner.STARTUP_DELAY_S = 10**6  # (no file checks: the stand-in files aren't there)
    jobs.CHECK_NEW_STATIONS = False
    server.DISK_SPARE = 0  # (the stand-in uploads are tiny: a nearly full disk can take them)
    said: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        kept_from_before(data)
        sp = Running(data, library())
        try:
            print(f"tapiOca is at {sp.home} (and {sp.internet} for the internet)")
            fill(sp, Path(tmp))
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                for size in sizes:
                    width, height = size_of(size)
                    folder = args.folder / size
                    folder.mkdir(parents=True, exist_ok=True)
                    for theme in args.themes.split(","):
                        for person in who:

                            def context_of(headers=None, size=size, width=width, height=height,
                                           theme=theme):  # fmt: skip
                                return browser.new_context(
                                    viewport={"width": width, "height": height},
                                    device_scale_factor=1, is_mobile=size in touch,
                                    has_touch=size in touch, color_scheme=theme,
                                    extra_http_headers=headers,
                                )  # fmt: skip

                            if person in ("signin-trusted", "signin-pin", "first-paint"):
                                look = Look(None, folder, f"{person}-{theme}", size in touch, said)
                                if person == "signin-trusted":
                                    signin_trusted(browser, sp.home, context_of, look)
                                elif person == "signin-pin":
                                    signin_by_pin(context_of, sp.home, look)
                                else:
                                    first_paint(context_of, sp.home, look)
                                continue
                            context = context_of()
                            # (The update banner is shown in one view only.)
                            context.add_init_script(
                                f"try {{ localStorage.setItem('{NOT_NOW}', '{NEWER}'); }} catch {{}}"
                            )
                            if person in ("admin", "user"):
                                signed = context.request.post(
                                    f"{sp.home}/api/access/sign-in",
                                    data=ADMIN if person == "admin" else USER,
                                    headers=PAGE,
                                )
                                assert signed.ok, signed.text()
                            page = context.new_page()
                            base = sp.internet if person == "signin" else sp.home
                            page.goto(base + "/")
                            page.wait_for_timeout(900)
                            look = Look(page, folder, f"{person}-{theme}", size in touch, said)
                            if person == "admin":
                                admin_views(page, look, only, sp)
                                if only is None or "setup" in only:
                                    setup_before_status(context, base, look, sp)
                                    waiting_media_step(context, base, look, sp)
                            elif person == "user":
                                user_views(page, look, only)
                            else:
                                look("signin")
                                # (From the internet: where the PIN works, never
                                # the at-home note; and so even when the page's
                                # first answer is lost: 1.33.1's audit.)
                                look.expect("the internet's PIN note shows",
                                            page.is_visible("#signinWhere"), True)  # fmt: skip
                                look.expect("the at-home PIN note shows",
                                            page.is_visible("#signinHome"), False)  # fmt: skip
                                signin_answer_lost(context, base, look)
                                page.evaluate(
                                    "() => { const n = document.querySelector('#signinNote'); n.hidden = false; n.textContent = ACCESS.idleSignedOut; }"
                                )
                                look("signin-idle")
                            context.close()
                    print(f"{size}: done")
                browser.close()
        finally:
            sp.stop()
    report = args.folder / "report.txt"
    report.write_text("".join(f"{line}\n" for line in said))
    sideways = [line for line in said if "scrolls sideways" in line]
    failed = [line for line in said if "check failed" in line]
    print(f"\n{len(said)} things to look at (all in {report}); pages that scroll sideways:")
    print("\n".join(sideways) or "none")
    print("Checks of what the page does that failed:")
    print("\n".join(failed) or "none")


if __name__ == "__main__":
    main()
