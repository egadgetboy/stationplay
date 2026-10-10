"""StationPlay's page at every screen size, for checking before a release.

Starts StationPlay with stand-in data (the tests' stand-in Plex, from
tests/fakeplex_library.py, with shows, movies and collections; and
stations, people, linked devices, stats, logs, problems from the apps,
broken files and a person's report, and Admin alerts kept from before it
last stopped), then, in Playwright's Chromium, looks at every tab and
every dialog and panel that opens, signed in as an Admin and as a User, at
each size, light and dark. It saves a screenshot of each into a folder
(one folder for each size), and says what's wrong with each: a page that
scrolls sideways, something cut off or sticking out of its panel, things
on top of each other, text smaller than the page's smallest (11px), a tap
target smaller than about 40px on a phone or tablet, or a dialog that
doesn't fit the screen. It's a tool, not a test: the tests don't run it.

    pip install playwright pillow       (and: python -m playwright install chromium)
    python tools/page_sizes.py /tmp/page-sizes
    python tools/page_sizes.py /tmp/page-sizes --sizes 390x844,1280x800 --themes dark --only stations,editor
"""

from __future__ import annotations

import argparse
import asyncio
import colorsys
import io
import logging
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import jobs, scanner, stats  # noqa: E402
from app import main as server  # noqa: E402
from app.broadcaster import Viewer  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import Database, Item  # noqa: E402
from app.plex import PlexClient  # noqa: E402
from tests.fakeplex_library import LibraryPlex  # noqa: E402
from tests.helpers import Proxy  # noqa: E402

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
    (5, "Comedy Central Station", ["102", "103", "111"], {"marathonMode": "random"}),
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


# StationPlay, running ----------------------------------------------------------------


class Running:
    """StationPlay on its home-network port and its public one, in a thread
    of its own; `call` runs something on its event loop."""

    def __init__(self, data: Path, plex: StandInPlex) -> None:
        lan, public = (socket.create_server(("127.0.0.1", 0)) for _ in range(2))
        self.ports = lan.getsockname()[1], public.getsockname()[1]
        self.home, self.internet = (f"http://127.0.0.1:{port}" for port in self.ports)
        settings = Settings(
            plex_url="http://plex.test", plex_token="token", data_dir=data, hw_accel="cpu",
            port=self.ports[0], public_port=self.ports[1],
        )  # fmt: skip
        self.app = server.create_app(
            settings, PlexClient("http://plex.test", "token", transport=plex.transport())
        )
        self.ctx = self.app.state.ctx
        self.ctx.play_transport = plex.transport()
        config = uvicorn.Config(self.app, log_level="warning", lifespan="on", proxy_headers=False)
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

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)


def kept_from_before(data: Path) -> None:
    """Admin alerts kept from before StationPlay last stopped, as it finds
    them when it starts (see alerts.py): the clock off since three hours
    ago, still going (the stand-in Plex doesn't say the time, so it stays),
    and the data folder's space, fixed an hour ago."""
    now = int(time.time() * 1000)
    db = Database(data / "stationplay.db")
    db.keep_alert(
        "clock", "", now - 3 * 3600_000,
        "StationPlay's clock is 7 minutes ahead of Plex's. The guide and the stations' clocks "
        "go by it: check the date and time on this server (and on Plex's, if it runs elsewhere).",
        None,
    )  # fmt: skip
    db.keep_alert(
        "data-full", "", now - 5 * 3600_000,
        "StationPlay's data folder has only 1.4 GB free (1% of its disk). Free up room on its "
        "disk, or StationPlay can't keep stations, backups and settings.",
        now - 3600_000,
    )  # fmt: skip
    db.close()


def fill(sp: Running, data: Path) -> None:
    """Everything the tabs show: stations (from shows and movies, smart ones
    and from collections), people, linked devices, signed-in apps, an API
    token, StationPlay's apps away from home, stats, logs, problems from the
    apps, a logo and an Intro Bumper of your own, a backup; and on the Broken
    files tab, people's reports (several on one program, one StationPlay
    checked and found nothing wrong in, one it found what's wrong in), files
    that need you, one being replaced, and the rest, with Sonarr and Radarr
    on, which sends an Admin's alert."""
    ctx = sp.ctx
    with httpx.Client(base_url=sp.home, timeout=60) as home:

        def ok(response: httpx.Response) -> Any:
            assert response.is_success, (response.request.url, response.status_code, response.text)
            return response.json() if response.content else None

        ok(home.post("/api/access/users", json={**ADMIN, "role": "admin", "maxStations": None}))
        ok(home.post("/api/access/users", json=USER))
        ok(home.post("/api/access/users", json=JO))
        robin = ok(home.post("/api/access/users", json=KID))
        levels = {lv["name"]: lv["id"] for lv in ok(home.get("/api/access/viewing"))["levels"]}
        ok(home.put(f"/api/access/users/{robin['id']}/viewing", json={"level": levels["Kid"]}))
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
        tv = {"app": "StationPlay for Android TV", "deviceName": "Living Room TV"}
        signed = ok(home.post("/api/internal/sign-in", json={**ADMIN, **tv}))
        app_token = {"Authorization": f"Bearer {signed['token']}"}
        sams = ok(home.post("/api/internal/sign-in", json={
            **USER, "app": "StationPlay for iPhone", "deviceName": "Sam’s iPhone"}))  # fmt: skip
        sam_token = {"Authorization": f"Bearer {sams['token']}"}
        jos = ok(home.post("/api/internal/sign-in", json={
            **JO, "app": "StationPlay for Roku", "deviceName": "Bedroom"}))  # fmt: skip
        jo_token = {"Authorization": f"Bearer {jos['token']}"}
        roku = {"app": "StationPlay for Roku", "version": "0.5.0",
                "device": "Roku Ultra 4850X, Roku OS 14.0", "deviceName": "Bedroom"}  # fmt: skip
        phone = {"app": "StationPlay for Android", "version": "0.9.0",
                 "device": "Pixel 8, Android 15", "deviceName": "Pat’s phone"}  # fmt: skip
        for device in (roku, phone):
            ok(home.post("/api/internal/problem", headers=app_token, json={
                "kind": "station-stopped", "station": 4, "detail": "decoder error", **device}))  # fmt: skip
        ok(home.post("/api/internal/problem", headers=app_token, json={
            "kind": "library-failed", "title": "Cosmic Drift", "detail": "HTTP 500", **roku}))  # fmt: skip
        ok(home.post("/api/internal/problem", headers=app_token, json={"kind": "crashed", **phone}))
        # People's reports, for the Broken files tab: one waiting for an
        # Admin; three people's on one program; and two StationPlay checks
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
        # reaching StationPlay.
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
            "lastedMs": 724_000, "journal": "10:12:30 Can't reach StationPlay: No network on "
            "this device\n10:24:34 StationPlay answered again", **galaxy}))  # fmt: skip
        ok(home.post("/api/api-tokens", json={"name": "Home Assistant", "scope": "viewer"}))
        ok(home.post("/api/internal/play", headers=app_token, json={"key": "303", "device": {
            "containers": ["mkv", "mp4"], "hdr": [], "audio": ["aac", "ac3"], "hls": ["ts"],
            "video": [{"codec": "h264", "width": 3840, "height": 2160, "bitDepth": 8}]}}))  # fmt: skip

        # StationPlay's apps away from home, through a reverse proxy.
        ctx.reach.transport = Proxy(sp.app, sp.ports[1]).transport
        ok(home.put("/api/away", json={"on": True, "address": "https://tv.example.com"}))

    def inside() -> None:
        pat = next(u for u in ctx.db.users() if u.name == ADMIN["name"])
        ctx.devices.link("StationPlay for Android TV on Den", pat)
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
        # What StationPlay's checks of what people reported came to: nothing
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


def whole_page(page: Page, path: Path) -> None:
    """A screenshot of the whole page, a screen at a time. (Chromium's own
    whole-page screenshot forgets that it's a touch screen, from then on.)"""
    size = page.viewport_size
    assert size is not None
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
    sheet.save(path)


def close_dialogs(page: Page) -> None:
    page.evaluate("() => document.querySelectorAll('dialog[open]').forEach(d => d.close())")


def tab(page: Page, name: str) -> None:
    page.click(f".tab[data-tab='{name}']")
    page.wait_for_timeout(500)


def admin_views(page: Page, look: Look, only: set[str] | None) -> None:
    """What an Admin sees: every tab, and every dialog and panel they open."""

    def wanted(name: str) -> bool:
        return not only or name in only or name.split("-")[0] in only

    if wanted("stations"):
        page.evaluate(
            "() => document.querySelector('#channels details.more')?.setAttribute('open', '')"
        )
        look("stations", full=True)
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
        close_dialogs(page)
    if wanted("setup"):
        page.evaluate("() => runSetup()")
        page.wait_for_selector("#setupDlg[open] .setup-check, #setupDlg[open] .playback")
        page.wait_for_timeout(1500)
        steps = page.locator(".setup-nav button").count()
        for n in range(steps):
            look(f"setup-{n + 1}")
            if n < steps - 1:
                page.click("#setupFoot .btn.primary")
                page.wait_for_timeout(700)
        close_dialogs(page)
    if wanted("addtoplex"):
        tab(page, "setup")
        look("addtoplex", full=True)
    if wanted("access"):
        tab(page, "access")
        look("access", full=True)
        page.evaluate(
            "() => document.querySelectorAll('#tab-access details.arr').forEach(d => d.open = true)"
        )
        page.wait_for_timeout(800)
        look("access-panels", full=True)
        page.click("#viewingBody button:has-text('Add a level')")
        page.wait_for_timeout(400)
        page.evaluate(
            "() => document.querySelector('.level-edit').scrollIntoView({block: 'center'})"
        )
        look("access-level")
        page.click(".level-edit button:has-text('Cancel')")
        row = page.locator("#userTable tr", has_text=USER["name"])
        row.locator("button:has-text('Devices')").click()
        look("access-devices")
        close_dialogs(page)
        row.locator("button:has-text('Set PIN')").click()
        look("access-pin")
        row.locator("button:has-text('Cancel')").click()
        page.wait_for_timeout(300)
        row.locator("button:has-text('Stations')").click()
        page.wait_for_selector("#userStations[open]")
        look("access-stations")
        close_dialogs(page)
    if wanted("stats"):
        tab(page, "stats")
        page.wait_for_selector("#healthTiles .gauge")
        look("stats", full=True)
    if wanted("logs"):
        tab(page, "logs")
        page.wait_for_selector("#logList .logline")
        look("logs", full=True)
        page.click("#problemList details > summary")
        page.wait_for_selector("#problemList details[open] pre:not(:empty)")
        page.wait_for_timeout(300)
        look("logs-journal", full=True)
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
    ap.add_argument("--who", default="admin,user,signin")
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
            print(f"StationPlay is at {sp.home} (and {sp.internet} for the internet)")
            fill(sp, Path(tmp))
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                for size in sizes:
                    width, height = size_of(size)
                    folder = args.folder / size
                    folder.mkdir(parents=True, exist_ok=True)
                    for theme in args.themes.split(","):
                        for person in who:
                            context = browser.new_context(
                                viewport={"width": width, "height": height},
                                device_scale_factor=1, is_mobile=size in touch,
                                has_touch=size in touch, color_scheme=theme,
                            )  # fmt: skip
                            if person != "signin":
                                signed = context.request.post(
                                    f"{sp.home}/api/access/sign-in",
                                    data=ADMIN if person == "admin" else USER,
                                )
                                assert signed.ok, signed.text()
                            page = context.new_page()
                            base = sp.internet if person == "signin" else sp.home
                            page.goto(base + "/")
                            page.wait_for_timeout(900)
                            look = Look(page, folder, f"{person}-{theme}", size in touch, said)
                            if person == "admin":
                                admin_views(page, look, only)
                            elif person == "user":
                                user_views(page, look, only)
                            else:
                                look("signin")
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
    print(f"\n{len(said)} things to look at (all in {report}); pages that scroll sideways:")
    print("\n".join(sideways) or "none")


if __name__ == "__main__":
    main()
