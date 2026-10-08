"""The web app: Plex's tuner endpoints, the streams, and the channel editor."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import secrets
import shutil
import signal
import socket
import tempfile
import time
from collections import Counter, OrderedDict
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from pydantic import AfterValidator, BaseModel, Field

from . import (
    __version__,
    access,
    api,
    appapi,
    applibrary,
    away,
    backups,
    capacity,
    devices,
    hdhr,
    hls,
    intro,
    jobs,
    limits,
    links,
    logbuffer,
    marathons,
    ondemand,
    playback,
    problems,
    replacing,
    setup,
    smart,
    specials,
    stats,
    subtitles,
    titles,
    upnext,
    viewing,
)
from .arr import NAMES as ARR_NAMES
from .arr import Arr, ArrError, clean_url
from .breaks import MAX_BREAKS, FillerLibrary, id_card_ms
from .broadcaster import Broadcaster, between, corner_mark, fmt_offset, now_ms, station_banner
from .broken import BrokenFiles
from .bumpers import MAX_UPLOAD_BYTES as MAX_BUMPER_BYTES
from .bumpers import Bumper, BumperError, BumperLibrary
from .config import Settings
from .db import NEW_STATION, SPECIAL_SETTINGS, STATION_SETTINGS, Channel, Database, Item, User
from .ffmpeg import (
    ASPECT_MODES,
    CLOCK_FORMATS,
    PICTURES,
    WATERMARK_MODES,
    WATERMARK_POSITIONS,
    WATERMARK_SIZES,
    WATERMARK_STYLES,
    WATERMARK_TIMINGS,
    WATERMARK_TRANSPARENCIES,
    low_priority,
    run_to_end,
    sized,
    subtitles_problem,
    tone_mapping_problem,
    usable_picture,
)
from .gpu import GpuManager
from .intro import DESCRIPTION_MAX, ID_LENGTHS
from .intro import LENGTHS as INTRO_LENGTHS
from .library import Library, LibraryError
from .logos import (
    COLLECTION_LOGO,
    MAX_UPLOAD_BYTES,
    UPLOAD_PREFIX,
    LogoError,
    LogoLibrary,
    to_kept_logo_png,
    to_trimmed_logo_png,
)
from .markers import MarkerFinder
from .plex import PEOPLE_FIELDS, TAG_FIELDS, PlexClient, PlexError, collection_key, genres
from .scanner import Scanner
from .schedule import ORDER_MODES, StationSchedule, forget_eras, prepare
from .sources import MediaAccess, ResolvedSource, resolve_source
from .text import plain
from .updates import GUIDE_FUTURE_MS, GUIDE_PAST_MS, MARGIN_MS, Updater, compare

log = logging.getLogger("stationplay")

WEB_DIR = Path(__file__).parent / "web"
# StationPlay's own guide covers the same two days as Plex's.
STATION_GUIDE_MAX_HOURS = GUIDE_FUTURE_MS / 3_600_000
SOURCE_TYPES = ("show", "movie", "section", "filter", "collection")
NAME_MAX = 60  # the longest a station's name can be
# The editor's posters: drawn at up to 64x96, so this is sharp on most
# screens; and larger ones, for when the list is zoomed in (drawn at 120x180).
POSTER_W, POSTER_H = 96, 144
POSTERS_KEPT = 2000  # a few MB
BIG_POSTER_W, BIG_POSTER_H = 240, 360
BIG_POSTERS_KEPT = 400  # (each is tens of KB)
ART_KEPT = 300
PLEX_LOGOS_KEPT = 50  # (each is tens of KB)
PLEX_LOGO_WAIT_S = 60  # the longest a logo may take to come from Plex
# What a collection in Plex can hold.
COLLECTION_KINDS = ("movie", "show", "season", "episode")
# The most matches a filter can leave out.
FILTER_EXCLUDE_MAX = 20_000
# The page's appearance, if one is chosen in a browser (otherwise the
# device's setting): kept in a cookie of that browser's own.
THEME_COOKIE = "stationplay_theme"
THEMES = ("light", "dark")
# What the page may load and run: its own script (by the nonce each time it's
# sent), from StationPlay only, and never inside another site's page.
PAGE_POLICY = (
    "default-src 'self'; script-src 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
SOURCES_MAX = 5000  # what one station can be made of (shows, movies, filters...)
LIBRARIES_MAX = 20  # libraries one filter looks in
PLEX_QUERIES_MAX = 50  # libraries, filters and collections one station is made of
DISK_SPARE = 2 * 1024**3  # room an upload always leaves on the data folder's disk
# Names and descriptions as people type them, made plain (see text.py).
PlainText = Annotated[str, AfterValidator(plain)]


class BlockIn(BaseModel):
    """A time-of-day block (see specials.py): its id ("" for a new one), its
    name, which days ("5,6": Monday 0 to Sunday 6), when it starts and ends
    (HH:MM; an end earlier in the day is the next day), and what it plays,
    chosen as a station's programs are."""

    id: str = Field(default="", max_length=16)
    name: PlainText = Field(default="", max_length=specials.BLOCK_NAME_MAX)
    days: str = Field(max_length=13)
    start: str = Field(max_length=5)
    end: str = Field(max_length=5)
    sources: list[dict] = Field(min_length=1, max_length=SOURCES_MAX)


class ChannelIn(BaseModel):
    """A station as the editor sends it. Settings left out (None) are, for a
    new station, what new stations start with (db.NEW_STATION), and for an
    existing one, unchanged."""

    number: int = Field(ge=1, le=9999)
    # Optional: a station with no name is called "Station <number>".
    name: PlainText = Field(default="", max_length=NAME_MAX)
    # A logo from the library, "" for the station's number, or left out to
    # keep the current one (a new station gets a random one).
    logo: str | None = None
    sources: list[dict] = Field(min_length=1, max_length=SOURCES_MAX)
    orderMode: str | None = None  # rotate (episode order) or shuffle
    aspectMode: str | None = None  # fit (black bars), stretch or zoom
    # Skip intros and credits where Plex has found them.
    skipIntros: bool | None = None
    # Commercials after each episode, or trailers after each movie: 0 to 3.
    breaks: int | None = Field(default=None, ge=0, le=MAX_BREAKS)
    # The Station ID card ("Up next") after each program, its length, and
    # whether its jingle plays.
    stationId: bool | None = None
    idSeconds: int | None = None
    idSound: bool | None = None
    # The station's logo, name or a clock in the corner: off, logo, name or
    # clock; its size (small, medium, large), transparency (high, medium,
    # low), corner (top-left ... bottom-right), timing (always, or start:
    # each program's first 30s) and style (color, or white).
    watermark: str | None = None
    watermarkSize: str | None = None
    watermarkTransparency: str | None = None
    watermarkPosition: str | None = None
    watermarkTiming: str | None = None
    watermarkStyle: str | None = None
    clockFormat: str | None = None  # the corner clock: 12 or 24 hours
    # The Intro Bumper when someone tunes in: 0 (off), 3, 5, 10 or 15
    # seconds, with the dial's sound or not, and the line it shows.
    introSeconds: int | None = None
    introSound: bool | None = None
    description: PlainText | None = Field(default=None, max_length=DESCRIPTION_MAX)
    # Or a video of your own instead: one of your bumpers, or "" for none.
    introVideo: str | None = None
    # Where someone tuning in joins: now (where it is) or start (the program
    # on now from its beginning).
    tuneIn: str | None = None
    # The Up Next Banner near the end of each program: 0 (off), 3, 5 or 10
    # seconds, and its size (small, medium or large).
    upNextSeconds: int | None = None
    upNextSize: str | None = None
    # Marathons (see marathons.py): off, random or set; how many a week at
    # random; or which days ("0,5": Monday 0 to Sunday 6) and when (HH:MM);
    # and each show's next episodes, or a random stretch.
    marathonMode: str | None = None
    marathonsAWeek: int | None = None
    marathonDays: str | None = Field(default=None, max_length=13)
    marathonTime: str | None = Field(default=None, max_length=5)
    marathonEpisodes: str | None = None
    # Its picture size (see ff.PICTURES), and subtitles (see subtitles.py).
    picture: str | None = None
    subtitles: str | None = None
    # A Feature Presentation (see specials.py): off or on, which days and
    # when, and where its movies come from (a movie library or collection,
    # as a source; {} for the station's own movies).
    featureMode: str | None = None
    featureDays: str | None = Field(default=None, max_length=13)
    featureTime: str | None = Field(default=None, max_length=5)
    featureSource: dict | None = None
    # Its time-of-day blocks (see specials.py).
    blocks: list[BlockIn] | None = Field(default=None, max_length=specials.MAX_BLOCKS)

    @property
    def display_name(self) -> str:
        return self.name.strip() or f"Station {self.number}"

    def settings(self) -> dict:
        """The settings given, by their stored names."""
        out = {
            column: getattr(self, api)
            for column, api, _ in STATION_SETTINGS
            if getattr(self, api) is not None
        }
        if self.blocks is not None:
            out["blocks"] = [b.model_dump() for b in self.blocks]
        return out


class SmartSplitIn(BaseModel):
    """A filter (as a station's source), and what to split it by: "decade",
    or a tag Plex has for its libraries (genre, studio...)."""

    filter: dict
    split: str = Field(max_length=40)


class SmartStationIn(BaseModel):
    name: PlainText = Field(default="", max_length=NAME_MAX)
    source: dict  # a filter


class SmartStationsIn(BaseModel):
    """Stations to make from filters, numbered from `firstNumber` (each the
    next free number from there)."""

    firstNumber: int = Field(ge=1, le=9999)
    stations: list[SmartStationIn] = Field(min_length=1, max_length=smart.MAX_STATIONS)


class CollectionStations(BaseModel):
    """Plex collections to make stations of, by their rating keys."""

    ratingKeys: list[str] = Field(min_length=1, max_length=200)


class CardPreview(BaseModel):
    """What the station editor shows, for a preview of its Intro Bumper,
    Station ID card or Feature Presentation card."""

    kind: Literal["intro", "id", "feature"] = intro.INTRO  # or intro.IDENT or intro.FEATURE
    channelId: int | None = None  # for what's on (an existing station)
    number: int = Field(ge=1, le=9999)
    name: PlainText = Field(default="", max_length=NAME_MAX)
    logo: str = ""
    description: PlainText = Field(default="", max_length=DESCRIPTION_MAX)
    seconds: int = 5
    sound: bool = True


class BannerPreview(BaseModel):
    """What the station editor shows, for a preview of its Up Next Banner:
    the banner, and what's in the corner (which makes way for it)."""

    channelId: int | None = None  # for what's up next (an existing station)
    number: int = Field(default=1, ge=1, le=9999)
    name: PlainText = Field(default="", max_length=NAME_MAX)
    logo: str = ""
    seconds: int = 10
    size: str = "large"
    # What's in the corner, as in ChannelIn.
    watermark: str = "off"
    watermarkSize: str = "large"
    watermarkTransparency: str = "low"
    watermarkPosition: str = "bottom-left"
    watermarkTiming: str = "always"
    watermarkStyle: str = "color"
    clockFormat: str = "12"


class PlexLogoIn(BaseModel):
    # The show or movie whose logo in Plex to add to your logos.
    ratingKey: str = Field(max_length=20)


class ArrIn(BaseModel):
    """Sonarr's or Radarr's settings (see replacing.py). `key` None: as it is."""

    app: Literal["sonarr", "radarr"]
    url: str = Field(default="", max_length=500)
    key: str | None = Field(default=None, max_length=100)
    on: bool = False


class ArrWhatIn(BaseModel):
    """What Sonarr and Radarr replace (see replacing.py)."""

    what: Literal["both", "broken", "missing"]


class ArrWhenIn(BaseModel):
    """When Sonarr and Radarr replace: when you say so, or by themselves."""

    when: Literal["ask", "auto"]


class AwayIn(BaseModel):
    on: bool
    address: str = Field(default="", max_length=away.ADDRESS_MAX)


class LimitsIn(BaseModel):
    """Stations kept from some Plex users (see limits.py): on or off, each
    Plex user's id and the ids of the stations kept from them, and their
    names (as the page shows them)."""

    on: bool = False
    kept: dict[str, list[int]] = Field(default_factory=dict, max_length=500)
    names: dict[str, PlainText] = Field(default_factory=dict, max_length=500)


class AppLimitsIn(BaseModel):
    """How many devices may watch through StationPlay's apps at once, and
    of those, away from home (0: no limit; see capacity.py)."""

    devices: int
    away: int


class PlaybackIn(BaseModel):
    """New stations' picture size, the tuners, and what else new stations
    start with, by the editor's names (see playback.py); what isn't given
    stays as it is."""

    picture: str | None = None
    tuners: int | None = None
    newStation: dict[str, Any] | None = Field(default=None, max_length=20)


class SetupIn(BaseModel):
    """Questions in the setup that have been answered (see setup.py)."""

    answered: list[str] = Field(default_factory=list, max_length=20)


class ScanWindow(BaseModel):
    """When the overnight deep scan runs (HH:MM, local time)."""

    on: bool
    start: str
    end: str


@dataclass
class AppContext:
    settings: Settings
    db: Database
    plex: PlexClient  # Plex the server: its tuner, guide, who's watching
    broken: BrokenFiles
    device_id: str
    gpu: GpuManager
    broadcasters: dict[int, Broadcaster] = field(default_factory=dict)
    # Stations being sent to StationPlay's apps (see hls.py).
    hls_streams: hls.HlsStreams = field(default_factory=hls.HlsStreams)
    # Apps waiting to be signed in with a code (see links.py).
    links: links.Links = field(default_factory=links.Links)
    stall_counts: dict[str, int] = field(default_factory=dict)
    checks: dict[int, jobs.CheckStatus] = field(default_factory=dict)
    # Pictures for Plex's guide, and small posters for the station editor's
    # lists: the most recently used.
    art: OrderedDict[str, tuple[bytes, str]] = field(default_factory=OrderedDict)
    posters: OrderedDict[str, tuple[bytes, str]] = field(default_factory=OrderedDict)
    big_posters: OrderedDict[str, tuple[bytes, str]] = field(default_factory=OrderedDict)
    # Shows' and movies' logos from Plex, made ready to use: by Plex's
    # address for each (which changes when the logo does).
    plex_logos: OrderedDict[str, bytes] = field(default_factory=OrderedDict)
    icon_cache: dict[int, bytes] = field(default_factory=dict)
    media_access: MediaAccess = field(default_factory=MediaAccess)
    logos: LogoLibrary = field(default_factory=LogoLibrary)  # with uploads: see create_app
    # Where the picture sits in files with black bars baked in, by file.
    pictures: dict[str, tuple[int, int, int, int] | None] = field(default_factory=dict)
    # Whether ffmpeg can turn HDR pictures into ordinary ones, and draw
    # subtitles (tested at startup: see ff.tone_mapping_problem and
    # ff.subtitles_problem). Without them, HDR plays as it is, and programs
    # without subtitles.
    tone_mapping: bool = False
    subtitling: bool = False
    # Files being checked at once, by any station's Check files.
    check_slots: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(jobs.CHECK_CONCURRENCY)
    )
    watching_checks: asyncio.Lock = field(default_factory=asyncio.Lock)  # (see jobs.check_turn)
    # Going through the broken-files list again: the last time everything
    # was (or now), and one at a time (see jobs.py).
    list_check: jobs.ListCheck = field(default_factory=jobs.ListCheck)
    list_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Sonarr and Radarr (optional: see replacing.py): how asking each went
    # last, for the page; and, in tests, what answers for them.
    arr_status: dict[str, dict] = field(default_factory=dict)
    arr_transport: Any = None
    play_transport: Any = None  # (in tests, what answers for Plex's files)
    play_client: Any = None  # fetches files from Plex for the apps' players (see applibrary.py)
    who_watches: stats.WhoWatches = field(init=False)  # who's watching, as Plex says
    limits: limits.Limits = field(init=False)  # stations kept from some Plex users
    bumpers: BumperLibrary = field(init=False)  # Intro Bumpers you've uploaded
    access: access.Access = field(init=False)  # who can sign in
    devices: devices.Devices = field(init=False)  # the apps linked, and their pickers
    away: away.Away = field(init=False)  # StationPlay's apps away from home
    capacity: capacity.Capacity = field(init=False)  # how many apps may watch at once
    # Your library in StationPlay's apps (see ondemand.py): which libraries
    # are shared with them, what they're shown, what's playing, pictures.
    shared: ondemand.Shared = field(init=False)
    catalog: ondemand.Catalog = field(init=False)
    plays: ondemand.PlaySessions = field(default_factory=ondemand.PlaySessions)
    app_pictures: ondemand.PictureCache = field(default_factory=ondemand.PictureCache)
    stats: stats.Stats = field(init=False)  # how much each station is watched
    titles: titles.Titles = field(init=False)  # the ratings of what's on the stations
    viewing: viewing.Viewing = field(init=False)  # what each user can see
    problems: problems.Problems = field(init=False)  # what the apps ran into
    # Your shows and movies, wherever they come from (see library.py).
    library: Library = field(init=False)
    updater: Updater = field(init=False)
    markers: MarkerFinder = field(init=False)
    fillers: FillerLibrary = field(init=False)
    scanner: Scanner = field(init=False)

    def restart(self) -> None:
        """Stops StationPlay; Docker starts it again."""
        os.kill(os.getpid(), signal.SIGTERM)

    def __post_init__(self) -> None:
        self.library = Library(lambda: self.plex)
        self.bumpers = BumperLibrary(self.settings.data_dir / "bumpers")
        self.access = access.Access(self.db)
        self.devices = devices.Devices(self.db, self.access)
        self.access.picker = self.devices
        self.away = away.Away(self.db, self.access)
        self.capacity = capacity.Capacity(self.db)
        self.shared = ondemand.Shared(self.db)
        self.catalog = ondemand.Catalog(self.library, self.shared)
        self.stats = stats.Stats(self.db)
        self.titles = titles.Titles(self.db)
        self.viewing = viewing.Viewing(self.db, self.titles)
        self.problems = problems.Problems(self.db)
        self.access.judge_watching_by(self.viewing.watches_only)
        self.updater = Updater(self)
        self.markers = MarkerFinder(self.db, self.library)
        self.fillers = FillerLibrary(self)
        self.scanner = Scanner(self)
        self.who_watches = stats.WhoWatches(self)
        self.limits = limits.Limits(self.db)

    def app_watchers(self) -> dict[str, bool]:
        """The devices watching in StationPlay's apps now, stations and the
        library alike: which -> whether it's away from home."""
        watching = dict(self.hls_streams.watchers())
        for client, away_ in self.plays.watching().items():
            watching[client] = watching.get(client, False) or away_
        return watching

    def station(self, channel_id: int) -> StationSchedule:
        """What plays when on a station, across its eras."""
        return self.updater.station(channel_id)

    def stations_for(self, user: User | None) -> list[Channel]:
        """The stations `user` can see (all of them for an Admin, or while
        signing in is off: see viewing.py)."""
        channels = self.db.list_channels()
        viewer = self.viewing.viewer(user)
        if viewer.everything:
            return channels
        return [c for c in channels if self.viewing.sees_station(viewer, c.id)]

    def sees_station(self, user: User | None, channel_id: int) -> bool:
        return self.viewing.sees_station(self.viewing.viewer(user), channel_id)

    async def resolve_source(self, item: Item) -> ResolvedSource:
        return await resolve_source(self.settings, self.library, item, self.media_access)

    def broadcaster(self, channel_id: int) -> Broadcaster:
        b = self.broadcasters.get(channel_id)
        if b is None:
            b = self.broadcasters[channel_id] = Broadcaster(self, channel_id)
        return b


def load_device_id(data_dir: Path) -> str:
    path = data_dir / "device.json"
    try:
        device_id = json.loads(path.read_text()).get("deviceId", "")
        if hdhr.device_id_valid(device_id):
            return device_id
    except (OSError, ValueError):
        pass
    device_id = hdhr.new_device_id()
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"deviceId": device_id}) + "\n")
    return device_id


class Turns:
    """Work done `at_once` at a time, with at most `most_waiting` waiting
    their turn; anyone else is told to try again later (HTTP 429, saying
    `busy`), rather than queueing without end."""

    def __init__(self, busy: str, *, at_once: int = 1, most_waiting: int = 0) -> None:
        self._slots = asyncio.Semaphore(at_once)
        self._waiting = 0
        self.most_waiting = most_waiting
        self.busy = busy

    @asynccontextmanager
    async def turn(self):
        if self._slots.locked() and self._waiting >= self.most_waiting:
            raise HTTPException(429, self.busy)
        self._waiting += 1
        try:
            await self._slots.acquire()
        finally:
            self._waiting -= 1
        try:
            yield
        finally:
            self._slots.release()


class AtOnce:
    """At most `most` of some requests at once from each person (a user, or
    an address while signing in is off); anyone asking for more is told to
    try again in a moment (HTTP 429, saying `busy`). A FastAPI dependency."""

    def __init__(self, most: int, busy: str) -> None:
        self.most = most
        self.busy = busy
        self._running: Counter[str] = Counter()

    async def __call__(self, request: Request):
        user = access.signed_in(request)
        who = f"user {user.id}" if user else access.address(request.scope)
        if self._running[who] >= self.most:
            raise HTTPException(429, self.busy)
        self._running[who] += 1
        try:
            yield
        finally:
            self._running[who] -= 1
            if not self._running[who]:
                del self._running[who]


def create_app(settings: Settings | None = None, plex: PlexClient | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    up_since = time.monotonic()  # (for the setup's check on backups)

    def prepare_schedules() -> None:
        """Works out what airs on each station over the guide's span, so
        nothing has to wait for it later. Runs on a worker thread."""
        started = time.monotonic()
        now = now_ms()
        for channel in ctx.db.list_channels():
            prepare(ctx.station(channel.id), now - GUIDE_PAST_MS, now + GUIDE_FUTURE_MS)
        took = time.monotonic() - started
        if took > 2:
            log.info("Prepared the station schedules in %.1fs", took)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("StationPlay %s is starting", __version__)
        playback.start(ctx.db, settings)
        setup.start(
            ctx.db,
            len(ctx.db.list_channels()),
            ctx.away.on,
            ctx.shared.on,
            any(u.role != access.ADMIN for u in ctx.db.users()),
        )
        await asyncio.to_thread(prepare_schedules)
        problem = await tone_mapping_problem(settings)
        ctx.tone_mapping = problem is None
        if problem:
            log.warning(
                "This ffmpeg can't tone-map HDR to SDR, so HDR programs will look washed out (%s)",
                problem,
            )
        await asyncio.to_thread(subtitles.tidy, settings.data_dir)
        problem = await subtitles_problem(settings, settings.data_dir / subtitles.FOLDER)
        ctx.subtitling = problem is None
        if problem:
            log.warning(
                "StationPlay can't draw subtitles, so programs will play without them (%s)",
                problem,
            )
        ctx.gpu.start()
        background = [
            asyncio.create_task(jobs.look_again_forever(ctx)),
            asyncio.create_task(ctx.who_watches.run_forever()),
            asyncio.create_task(ctx.updater.run_forever()),
            asyncio.create_task(ctx.fillers.refresh()),
            asyncio.create_task(backups.nightly_forever(ctx)),
            asyncio.create_task(ctx.scanner.run_forever()),
        ]
        yield
        for task in background:
            task.cancel()
        await ctx.hls_streams.stop_all("StationPlay is shutting down")
        for b in list(ctx.broadcasters.values()):
            await b.stop("StationPlay is shutting down")
        await ctx.plex.close()
        if ctx.play_client is not None:
            await ctx.play_client.aclose()
        ctx.db.close()

    logs = logbuffer.install()
    # The HTTP library logs every request to Plex; that drowns out what matters.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        if backups.apply_staged_restore(settings.data_dir):
            log.warning("StationPlay started from the backup you restored")
    except Exception:
        log.exception("Couldn't restore the backup, so StationPlay is keeping its current settings")
    db = Database(settings.data_dir / backups.DB_NAME)
    ctx = AppContext(
        settings=settings,
        db=db,
        plex=plex or PlexClient(settings.plex_url, settings.plex_token),
        broken=BrokenFiles(settings.data_dir / "broken-files.json"),
        device_id=load_device_id(settings.data_dir),
        gpu=GpuManager(settings),
        logos=LogoLibrary(uploads=settings.data_dir / "logos", db=db),
        list_check=jobs.ListCheck.last(db),
    )
    remember_plex_libraries(ctx)
    give_logos_to_older_stations(ctx)
    move_to_new_logos(ctx)
    ctx.bumpers.clear_leftovers()
    ctx.access.reset_if_asked(settings.data_dir)
    ctx.access.forget_old_sessions()
    app = FastAPI(
        title="StationPlay", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.ctx = ctx
    # Signing in, if it's on: in front of everything else (see access.py).
    app.add_middleware(access.Gate, access=ctx.access, public_port=settings.public_port)
    access.routes(app, ctx.access)
    viewing.routes(app, ctx)  # (who sees what: Viewing Levels)
    devices.routes(app, ctx)  # (linked devices, and their pickers)
    appapi.routes(app, ctx)  # (for StationPlay's apps)
    applibrary.routes(app, ctx)  # (your library in them)
    stats.routes(app, ctx)

    @app.exception_handler(LibraryError)
    async def library_unavailable(request: Request, e: LibraryError):
        """Anything that needed Plex (or another library) and couldn't reach
        it."""
        return JSONResponse({"detail": str(e)}, status_code=502)

    def channel_or_404(channel_id: int) -> Channel:
        channel = ctx.db.get_channel(channel_id)
        if channel is None:
            raise HTTPException(404)
        return channel

    def changeable(channel_id: int, request: Request) -> Channel:
        """A station that whoever's asking may change or delete (404 or 403
        otherwise)."""
        channel = channel_or_404(channel_id)
        if not access.may_change(access.signed_in(request), channel):
            raise HTTPException(
                403, "Only an Admin or the person who made this station can change it"
            )
        return channel

    def base_url(request: Request) -> str:
        """The address Plex reaches StationPlay at: as the request was made,
        unless BASE_URL says. (From the internet, where it can't be told, the
        Add to Plex tab shows where to put your NAS's address in.)"""
        if settings.base_url:
            return settings.base_url
        if access.outside(request.scope):
            return f"http://<your NAS>:{settings.port}"
        host = request.headers.get("host") or f"localhost:{settings.port}"
        return f"{request.url.scheme}://{host}"

    # Plex tuner endpoints -----------------------------------------------

    @app.get("/discover.json")
    async def discover(request: Request):
        tuners = playback.announced(playback.load(ctx.db).tuners)
        return hdhr.discover(settings.friendly_name, ctx.device_id, base_url(request), tuners)

    @app.get("/lineup_status.json")
    async def lineup_status():
        return hdhr.LINEUP_STATUS

    @app.get("/lineup.json")
    async def lineup(request: Request):
        return hdhr.lineup(ctx.db.list_channels(), base_url(request))

    @app.post("/lineup.post")
    async def lineup_post():
        return Response(status_code=200)

    @app.get("/device.xml")
    async def device_xml(request: Request):
        return Response(
            hdhr.device_xml(settings.friendly_name, ctx.device_id, base_url(request)),
            media_type="application/xml",
        )

    async def guide_xml(request: Request, for_plex: bool) -> Response:
        # Updates waiting for Plex take over now, so the guide Plex is about
        # to receive already includes them.
        by_plex = await ctx.updater.before_guide(
            request.headers.get("user-agent", ""), plex_address=for_plex
        )
        now = now_ms()
        stations = [(c, ctx.station(c.id)) for c in ctx.db.list_channels()]
        body = await asyncio.to_thread(
            hdhr.xmltv, stations, base_url(request), now - GUIDE_PAST_MS, now + GUIDE_FUTURE_MS
        )
        ctx.updater.after_guide(now + GUIDE_FUTURE_MS, by_plex)
        return Response(body, media_type="application/xml")

    @app.get("/xmltv.xml")
    async def xmltv(request: Request):
        """The guide address given to Plex."""
        return await guide_xml(request, for_plex=True)

    @app.get("/guide.xml")
    async def guide_for_other_apps(request: Request):
        """The same guide, for other apps (the M3U playlist points here)."""
        return await guide_xml(request, for_plex=False)

    @app.get("/stations.m3u")
    @app.get("/channels.m3u")
    async def m3u(request: Request):
        return PlainTextResponse(
            hdhr.m3u(ctx.db.list_channels(), base_url(request)),
            media_type="audio/x-mpegurl",
        )

    @app.get("/stream/{number}")
    @app.get("/auto/v{number}")  # the address a real HDHomeRun uses
    async def stream_channel(number: int, request: Request):
        channel = ctx.db.get_channel_by_number(number)
        if channel is None:
            raise HTTPException(404, f"There's no station {number}")
        b = ctx.broadcaster(channel.id)
        client = request.client.host if request.client else "?"
        on_now = playback.all_in_use(ctx, b)
        if on_now is not None:
            return all_tuners_in_use(channel, on_now, client)
        playback.make_room(ctx, b)
        viewer = b.subscribe(f"{client} on {number}")
        agent = request.headers.get("user-agent", "")
        log.info("Viewer %s tuned to station %s (%s)", client, number, agent or "no user agent")
        started = time.monotonic()

        async def body():
            sent = 0
            try:
                while True:
                    chunk = await viewer.next_chunk()
                    if chunk is None:
                        break
                    sent += len(chunk)
                    yield chunk
            finally:
                b.unsubscribe(viewer)
                watched = fmt_offset(time.monotonic() - started)
                if viewer.ended_because:
                    log.warning(
                        "Viewer %s was disconnected from station %s after %s (%.0f MB): %s",
                        client,
                        number,
                        watched,
                        sent / 1e6,
                        viewer.ended_because,
                    )
                else:
                    # The player closed the connection: stopped watching,
                    # changed station, or gave up on the stream.
                    log.info(
                        "Viewer %s left station %s after %s (%.0f MB)",
                        client,
                        number,
                        watched,
                        sent / 1e6,
                    )

        return StreamingResponse(
            body(),
            media_type="video/mp2t",
            headers={"Cache-Control": "no-cache, no-store", "Connection": "close"},
        )

    # StationPlay's apps (and AirPlay and Chromecast): stations as HLS ---------

    async def hls_playlist_for(
        number: int, client: str, away_: bool = False, night: bool = False
    ) -> Response:
        """A station's HLS playlist, for an app (`client`: which, for its
        stream's list of who's watching; `away_`: away from home; `night`:
        with night mode's sound). The first ask starts the station's stream
        for apps (see hls.py), and waits until a player has enough to start
        on. One more device than an Admin's limits allow is turned away (see
        capacity.py)."""
        channel = ctx.db.get_channel_by_number(number)
        if channel is None:
            raise HTTPException(404, f"There's no station {number}")
        watching = ctx.app_watchers()
        if (over := ctx.capacity.refusal(watching, client, away_)) is not None:
            limit, most = over
            log.warning(
                "The limit of %s watching%s at once (set on the Access tab) was reached, "
                "so an app on %s couldn't tune to station %s",
                capacity.devices(most),
                " away from home" if limit == "away" else "",
                client,
                channel.number,
            )
            return JSONResponse(
                {"detail": capacity.refused_because(limit, most), "limit": limit, "most": most},
                status_code=503,
                headers=hls.HEADERS,
            )
        stream = ctx.hls_streams.get(channel.id, night)
        if stream is None:
            b = ctx.broadcaster(channel.id)
            on_now = playback.all_in_use(ctx, b)
            if on_now is not None:
                tuners = playback.load(ctx.db).tuners
                log.warning(
                    "No tuners are free (%d in use, for stations %s), so an app on %s "
                    "couldn't tune to station %s",
                    tuners,
                    ", ".join(map(str, on_now)),
                    client,
                    channel.number,
                )
                return JSONResponse(
                    {"detail": playback.busy_lines(tuners, on_now)[0], "onNow": on_now},
                    status_code=503,
                    headers=hls.HEADERS,
                )
            playback.make_room(ctx, b)
            stream = ctx.hls_streams.start(b, channel.number, night)
        stream.asked_by(client, away_)
        playlist = await stream.playlist()
        if playlist is None:
            return JSONResponse(
                {"detail": "This station is starting. Try again in a moment."},
                status_code=503,
                headers=hls.HEADERS,
            )
        return Response(playlist, media_type="application/vnd.apple.mpegurl", headers=hls.HEADERS)

    async def hls_piece_of(number: int, piece: str, night: bool = False) -> Response:
        channel = ctx.db.get_channel_by_number(number)
        stream = ctx.hls_streams.get(channel.id, night) if channel else None
        if stream is None:
            raise HTTPException(404, "That station isn't being sent to apps")
        data = await stream.piece(piece)
        if data is None:
            raise HTTPException(404, "That piece of the stream is gone")
        stream.asked_by(None)
        return Response(data, media_type="video/mp2t", headers=hls.HEADERS)

    def hls_left(number: int, client: str, night: bool = False) -> Response:
        """An app tuned away from a station: its stream for apps stops now if
        no other app is watching it (see hls.py)."""
        channel = ctx.db.get_channel_by_number(number)
        stream = ctx.hls_streams.get(channel.id, night) if channel else None
        if stream is not None:
            stream.left_by(client)
        return Response(status_code=204, headers=hls.HEADERS)

    @app.get("/hls/{number}/index.m3u8")
    async def hls_playlist(number: int, request: Request):
        """A station's HLS playlist, on the home network."""
        return await hls_playlist_for(number, request.client.host if request.client else "?")

    @app.get("/hls/{number}/{piece}")
    async def hls_piece(number: int, piece: str):
        """One piece of a station's HLS stream."""
        return await hls_piece_of(number, piece)

    @app.post("/hls/{number}/leave", status_code=204)
    async def hls_leave(number: int, request: Request):
        return hls_left(number, request.client.host if request.client else "?")

    # Night mode's sound (see hls.py), beside each station's own.

    @app.get("/hls/{number}/night/index.m3u8")
    async def hls_night_playlist(number: int, request: Request):
        client = request.client.host if request.client else "?"
        return await hls_playlist_for(number, client, night=True)

    @app.get("/hls/{number}/night/{piece}")
    async def hls_night_piece(number: int, piece: str):
        return await hls_piece_of(number, piece, night=True)

    @app.post("/hls/{number}/night/leave", status_code=204)
    async def hls_night_leave(number: int, request: Request):
        return hls_left(number, request.client.host if request.client else "?", night=True)

    # The same, away from home through the public port: each signed-in app's
    # streams at an address of their own (see away.py).

    def away_user(key: str, number: int, *, recheck: bool = False) -> User:
        """Whose an address away from home is, while it's good and they can
        see the station (see viewing.py)."""
        user = ctx.away.user_of(key, recheck=recheck)
        if user is None:
            raise HTTPException(
                404, "That stream address has ended. Ask StationPlay for its stations again."
            )
        channel = ctx.db.get_channel_by_number(number)
        if channel is not None and not ctx.sees_station(user, channel.id):
            raise HTTPException(404, f"There's no station {number}")
        return user

    def away_client(key: str, user: User) -> str:
        # (By its key, not its address: apps behind one proxy are told apart.)
        return f"{user.name}'s app away from home ({key[:6]})"

    @app.get("/hls/k/{key}/{number}/index.m3u8")
    async def hls_playlist_away(key: str, number: int, request: Request):
        user = away_user(key, number, recheck=True)
        ctx.away.watching(key, user, number, access.where(request.scope))
        return await hls_playlist_for(number, away_client(key, user), away_=True)

    @app.get("/hls/k/{key}/{number}/logo.png")
    async def logo_away(key: str, number: int):
        """The station's logo, for the app's guide (a picture can't sign in
        either)."""
        away_user(key, number)
        return await channel_icon(number)

    @app.get("/hls/k/{key}/{number}/{piece}")
    async def hls_piece_away(key: str, number: int, piece: str):
        away_user(key, number)
        return await hls_piece_of(number, piece)

    @app.post("/hls/k/{key}/{number}/leave", status_code=204)
    async def hls_leave_away(key: str, number: int):
        user = ctx.away.user_of(key, recheck=False)
        if user is None:
            return Response(status_code=204, headers=hls.HEADERS)
        return hls_left(number, away_client(key, user))

    @app.get("/hls/k/{key}/{number}/night/index.m3u8")
    async def hls_night_playlist_away(key: str, number: int, request: Request):
        user = away_user(key, number, recheck=True)
        ctx.away.watching(key, user, number, access.where(request.scope))
        return await hls_playlist_for(number, away_client(key, user), away_=True, night=True)

    @app.get("/hls/k/{key}/{number}/night/{piece}")
    async def hls_night_piece_away(key: str, number: int, piece: str):
        away_user(key, number)
        return await hls_piece_of(number, piece, night=True)

    @app.post("/hls/k/{key}/{number}/night/leave", status_code=204)
    async def hls_night_leave_away(key: str, number: int):
        user = ctx.away.user_of(key, recheck=False)
        if user is None:
            return Response(status_code=204, headers=hls.HEADERS)
        return hls_left(number, away_client(key, user), night=True)

    @app.options("/hls/{rest:path}")
    async def hls_preflight():
        """For Chromecasts asking first whether they may fetch the stream."""
        return Response(
            status_code=204,
            headers={**hls.HEADERS, "Access-Control-Allow-Headers": "Range",
                     "Access-Control-Allow-Methods": "GET, POST, OPTIONS"},
        )  # fmt: skip

    # The "all tuners in use" cards being shown: when each began (one that
    # never finished is forgotten once it would have).
    busy_cards: dict[str, float] = {}

    def all_tuners_in_use(channel: Channel, on_now: list[int], client: str) -> Response:
        """Someone tuned in to `channel` while every tuner is in use: a card
        saying so (for a while), so they know it's StationPlay's limit."""
        tuners = playback.load(ctx.db).tuners
        log.warning(
            "No tuners are free (%d in use, for stations %s), so viewer %s got the "
            '"All tuners in use" card instead of station %s',
            tuners,
            ", ".join(map(str, on_now)),
            client,
            channel.number,
        )
        now = time.monotonic()
        for card, began in list(busy_cards.items()):
            if now - began > playback.BUSY_S + 30:
                del busy_cards[card]
        if len(busy_cards) >= playback.BUSY_AT_ONCE:
            raise HTTPException(503, "All of StationPlay's tuners are in use")
        card = secrets.token_hex(8)
        busy_cards[card] = now
        logo = ctx.logos.path(channel.logo) if channel.logo else None
        lines = playback.busy_lines(tuners, on_now)
        stream = playback.busy_stream(sized(settings, channel.picture), logo, channel.name, lines)

        async def body():
            try:
                async for chunk in stream:
                    yield chunk
            finally:
                busy_cards.pop(card, None)
                await stream.aclose()

        return StreamingResponse(
            body(),
            media_type="video/mp2t",
            headers={"Cache-Control": "no-cache, no-store", "Connection": "close"},
        )

    # Asking Plex on someone's behalf: a few requests at once from each person.
    asking_plex = Depends(AtOnce(4, "Too many requests to Plex at once. Try again in a moment."))
    # Pictures from Plex: a few fetched at a time (the rest wait their turn).
    plex_pictures = Turns(
        "Too many pictures are loading. Try again in a moment.", at_once=4, most_waiting=1000
    )

    async def picture(
        cache: OrderedDict[str, tuple[bytes, str]],
        rating_key: str,
        fetch: Callable[[], Awaitable[tuple[bytes, str]]],
        kept: int,
    ) -> Response:
        """A picture of a show or movie from Plex, kept in `cache` (the `kept`
        most recently used)."""
        if not rating_key.isdigit():
            raise HTTPException(404)
        cached = cache.get(rating_key)
        if cached is None:
            try:
                async with plex_pictures.turn():
                    cached = await fetch()
            except (httpx.HTTPError, LibraryError):
                raise HTTPException(404) from None
            cache[rating_key] = cached
            while len(cache) > kept:
                cache.popitem(last=False)
        cache.move_to_end(rating_key)
        data, content_type = cached
        return Response(data, media_type=content_type, headers={"Cache-Control": "max-age=86400"})

    @app.get("/art/{rating_key}")
    async def art(rating_key: str):
        """A program's picture, for Plex's guide."""
        return await picture(ctx.art, rating_key, lambda: ctx.library.art(rating_key), ART_KEPT)

    @app.get("/poster/{rating_key}")
    async def poster(rating_key: str, big: bool = False):
        """A show's or movie's poster, small (or not so small), for the
        station editor."""
        if big:
            return await picture(
                ctx.big_posters,
                rating_key,
                lambda: ctx.library.poster(rating_key, BIG_POSTER_W, BIG_POSTER_H),
                BIG_POSTERS_KEPT,
            )
        return await picture(
            ctx.posters,
            rating_key,
            lambda: ctx.library.poster(rating_key, POSTER_W, POSTER_H),
            POSTERS_KEPT,
        )

    @app.get("/logos/{logo_id}.png")
    async def logo_image(logo_id: str):
        path = ctx.logos.path(logo_id)
        if path is None:
            raise HTTPException(404)
        return FileResponse(
            path, media_type="image/png", headers={"Cache-Control": "max-age=604800"}
        )

    @app.get("/api/logos")
    async def logo_catalog():
        return ctx.logos.catalog()

    # A few at a time: each is held in memory while it's read.
    logo_uploads = Turns("Other logos are being added. Try again in a moment.", at_once=2)

    @app.post("/api/logos", status_code=201)
    async def upload_logo(request: Request, name: str = ""):
        """A logo of your own: the picture is the request's body."""
        async with logo_uploads.turn():
            try:
                ctx.logos.check_room()  # (before it's sent)
                data = bytearray()
                async for chunk in request.stream():
                    data += chunk
                    if len(data) > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "That file is too big (the limit is 10 MB)")
                logo = await ctx.logos.add(bytes(data), name, settings.ffmpeg_path)
            except LogoError as e:
                raise HTTPException(400, str(e)) from e
        log.info("Added your logo %r", logo["name"])
        return logo

    # A show's or movie's logo from Plex: looked up each time (it can change),
    # fetched and made ready once, a couple at a time.
    plex_logo_turns = Turns(
        "Other logos are being fetched from Plex. Try again in a moment.",
        at_once=2,
        most_waiting=8,
    )

    def plex_logo_id(url: str) -> str:
        """The id a logo from Plex has among your logos: always the same for
        the same picture (Plex's address for it changes when it does)."""
        return UPLOAD_PREFIX + hashlib.sha1(url.encode()).hexdigest()[:10]

    async def plex_logo(rating_key: str) -> tuple[str, str, bytes] | None:
        """(title, Plex's address, the logo as StationPlay keeps it) for a
        show or movie with a logo in Plex; None if it has none."""
        if not rating_key.isdigit():
            return None
        try:
            found = await ctx.library.clear_logo(rating_key)
            if found is None:
                return None
            title, url = found
            png = ctx.plex_logos.get(url)
            if png is None:
                async with plex_logo_turns.turn():
                    async with asyncio.timeout(PLEX_LOGO_WAIT_S):
                        data = await ctx.library.logo_bytes(rating_key, url)
                    png = await to_trimmed_logo_png(data, settings.ffmpeg_path)
                ctx.plex_logos[url] = png
                while len(ctx.plex_logos) > PLEX_LOGOS_KEPT:
                    ctx.plex_logos.popitem(last=False)
            ctx.plex_logos.move_to_end(url)
        except (LibraryError, LogoError, TimeoutError) as e:
            log.info(
                "Couldn't use the logo from Plex for rating key %s: %s",
                rating_key,
                str(e) or "it took too long",
            )
            return None
        return title, url, png

    @app.get("/plex-logo/{rating_key}.png", dependencies=[asking_plex])
    async def plex_logo_image(rating_key: str):
        """A show's or movie's logo from Plex, as it would be used (and the
        id it has, or would have, among your logos)."""
        found = await plex_logo(rating_key)
        if found is None:
            raise HTTPException(404)
        _, url, png = found
        return Response(
            png,
            media_type="image/png",
            # (Only for the browser that asked: never kept by a proxy on the way.)
            headers={"Cache-Control": "private, max-age=300", "X-Logo-Id": plex_logo_id(url)},
        )

    @app.post("/api/logos/plex", status_code=201, dependencies=[asking_plex])
    async def logo_from_plex(body: PlexLogoIn):
        """Adds a show's or movie's logo from Plex to your logos (or finds
        it there, if it was added before)."""
        found = await plex_logo(body.ratingKey)
        if found is None:
            raise HTTPException(404, "Couldn't get a logo for that show or movie from Plex")
        title, url, png = found
        try:
            logo = ctx.logos.keep(
                png, plain(title)[:NAME_MAX] or "Logo from Plex", plex_logo_id(url)
            )
        except LogoError as e:
            raise HTTPException(400, str(e)) from e
        log.info("Added the Plex logo for %r", logo["name"])
        return logo

    @app.delete("/api/logos/{logo_id}", status_code=204)
    async def delete_logo(logo_id: str):
        users = [c.number for c in ctx.db.list_channels() if c.logo == logo_id]
        if users:
            which = ", ".join(str(n) for n in users)
            raise HTTPException(
                409,
                "This logo is in use. First choose a different logo for "
                f"station{'' if len(users) == 1 else 's'} {which}.",
            )
        if not ctx.logos.remove(logo_id):
            raise HTTPException(404)
        return Response(status_code=204)

    def bumper_json(bumper: Bumper) -> dict:
        return {"id": bumper.id, "name": bumper.name, "seconds": bumper.seconds}

    @app.get("/bumpers/{bumper_id}.mp4")
    async def bumper_video(bumper_id: str):
        bumper = ctx.bumpers.get(bumper_id)
        if bumper is None:
            raise HTTPException(404)
        return FileResponse(ctx.bumpers.path(bumper), media_type="video/mp4")

    @app.get("/api/bumpers")
    async def bumper_catalog():
        return [bumper_json(b) for b in ctx.bumpers.catalog()]

    # One at a time (each is up to MAX_BUMPER_BYTES on the disk while it's
    # made into a bumper), and never onto a nearly full disk.
    bumper_uploads = Turns("Another Intro Bumper is being added. Try again in a minute.")

    @app.post("/api/bumpers", status_code=201)
    async def upload_bumper(request: Request, name: str = ""):
        """An Intro Bumper of your own: the video is the request's body. It's
        kept on disk as it arrives, not in memory."""
        too_big = f"That file is too big (the limit is {MAX_BUMPER_BYTES // 2**20} MB)"
        if int(request.headers.get("content-length") or 0) > MAX_BUMPER_BYTES:
            raise HTTPException(413, too_big)
        async with bumper_uploads.turn():
            return await add_bumper(request, name, too_big)

    async def add_bumper(request: Request, name: str, too_big: str) -> dict:
        try:
            ctx.bumpers.check_room()  # (before it's sent)
        except BumperError as e:
            raise HTTPException(400, str(e)) from e
        folder = ctx.bumpers.folder
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        free = (await asyncio.to_thread(shutil.disk_usage, folder)).free
        if free < MAX_BUMPER_BYTES + DISK_SPARE:
            raise HTTPException(507, "There isn't enough room on the disk for another video")
        upload = folder / f".upload-{secrets.token_hex(5)}"
        try:
            size = 0
            out = await asyncio.to_thread(upload.open, "wb")
            try:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_BUMPER_BYTES:
                        raise HTTPException(413, too_big)
                    await asyncio.to_thread(out.write, chunk)
            finally:
                await asyncio.to_thread(out.close)
            if not size:
                raise HTTPException(400, "That file is empty")
            # (At the biggest picture size: sharp on any station.)
            biggest = sized(settings, list(PICTURES)[-1])
            bumper = await ctx.bumpers.add(upload, name, biggest, ctx.tone_mapping)
        except BumperError as e:
            raise HTTPException(400, str(e)) from e
        finally:
            await asyncio.to_thread(upload.unlink, missing_ok=True)
        log.info("Added your Intro Bumper %r (%.1f seconds)", bumper.name, bumper.seconds)
        return bumper_json(bumper)

    @app.delete("/api/bumpers/{bumper_id}", status_code=204)
    async def delete_bumper(bumper_id: str):
        users = [c.number for c in ctx.db.list_channels() if c.intro_video == bumper_id]
        if users:
            which = ", ".join(str(n) for n in users)
            raise HTTPException(
                409,
                "This Intro Bumper is in use. First choose a different one for "
                f"station{'' if len(users) == 1 else 's'} {which}.",
            )
        if not ctx.bumpers.remove(bumper_id):
            raise HTTPException(404)
        return Response(status_code=204)

    @app.get("/channel-icon/{number}.png")
    async def channel_icon(number: int):
        """The station's logo, or a badge with its number."""
        channel = ctx.db.get_channel_by_number(number)
        if channel is None:
            raise HTTPException(404)
        path = ctx.logos.path(channel.logo) if channel.logo else None
        if path is not None:
            return FileResponse(
                path, media_type="image/png", headers={"Cache-Control": "max-age=86400"}
            )
        png = ctx.icon_cache.get(number)
        if png is None:
            png = await render_icon(settings, str(number))
            if png is None:
                raise HTTPException(404)
            ctx.icon_cache[number] = png
        return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=86400"})

    # Web page + JSON API -------------------------------------------------

    @app.get("/apple-touch-icon.png")
    async def home_screen_icon():
        """The page's icon on a phone's home screen (iPhones and iPads don't
        use the SVG one in the page)."""
        return FileResponse(
            WEB_DIR / "apple-touch-icon.png", headers={"Cache-Control": "max-age=86400"}
        )

    @app.get("/", response_class=HTMLResponse)
    @app.get("/link", response_class=HTMLResponse)  # (where an app's code is entered)
    async def index(request: Request):
        page = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        # Light or dark, as chosen in this browser (Appearance, at the foot of
        # the page); otherwise the device's own setting. Set here, so the page
        # is drawn in it from the start.
        theme = request.cookies.get(THEME_COOKIE)
        page = page.replace("__THEME__", f' data-theme="{theme}"' if theme in THEMES else "", 1)
        page = page.replace("__LOGO_VERSION__", str(ctx.logos.version))
        page = page.replace("__COLLECTION_LOGO__", COLLECTION_LOGO)
        pb = playback.load(ctx.db)
        starts = {**NEW_STATION, **pb.new_station, "picture": pb.picture}
        new_station = {api: starts[column] for column, api, _ in STATION_SETTINGS}
        page = page.replace("__NEW_STATION__", json.dumps(new_station))
        page = page.replace("__FEATURE_CARD_S__", str(specials.FEATURE_CARD_MS // 1000))
        rules = {
            "passwordMin": access.PASSWORD_MIN,
            "passwordMax": access.PASSWORD_MAX,
            "stationLimits": access.STATION_LIMITS,
            "newUserStations": access.NEW_USER_STATIONS,
            "apiTokenNameMax": access.API_TOKEN_NAME_MAX,
        }
        page = page.replace("__ACCESS__", json.dumps(rules))
        page = page.replace("__PASSWORD_MIN__", str(access.PASSWORD_MIN))
        page = page.replace("__PASSWORD_MAX__", str(access.PASSWORD_MAX))
        # Only the page's own script runs: none that found its way in some
        # other way (in a name, say) could.
        nonce = secrets.token_urlsafe(18)
        page = page.replace("<script>", f'<script nonce="{nonce}">', 1)
        return HTMLResponse(
            page,
            headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": PAGE_POLICY.format(nonce=nonce),
            },
        )

    async def plex_status(find_dvr: bool = True) -> dict:
        """Whether Plex answers; and (find_dvr) looks for StationPlay's tuner
        in Plex, for the Add to Plex tab."""
        if not ctx.plex.configured:
            return {"configured": False, "ok": False, "error": "PLEX_URL and PLEX_TOKEN aren't set"}
        if find_dvr:
            with contextlib.suppress(PlexError, TimeoutError):
                await asyncio.wait_for(ctx.updater.find_dvr(), 5)
        try:
            ident = await asyncio.wait_for(ctx.plex.identity(), 5)
        except PlexError as e:
            return {"configured": True, "ok": False, "error": str(e)}
        except TimeoutError:
            return {"configured": True, "ok": False, "error": "Plex isn't responding"}
        return {"configured": True, "ok": True, "version": ident.get("version")}

    media_check: dict[str, asyncio.Future] = {}

    async def media_dir_present() -> bool:
        """Checked off the event loop, so a hung share can't hold up streams,
        and one check at a time, so it can't use up the worker threads."""
        check = media_check.get("pending")
        if check is None or check.done():
            check = media_check["pending"] = asyncio.ensure_future(
                asyncio.to_thread(os.path.isdir, settings.media_dir)
            )
        try:
            return await asyncio.wait_for(asyncio.shield(check), 2)
        except TimeoutError:
            return False

    @app.get("/api/status")
    async def status(request: Request):
        if not ctx.access.sees_everything(access.signed_in(request)):
            # A User sees what the Stations tab shows: not how the server is
            # set up (its folders, addresses, devices).
            fillers = ctx.fillers.as_dict()
            return {
                "version": __version__,
                "plex": {"ok": (await plex_status(find_dvr=False))["ok"]},
                "streams": streams_now(access.signed_in(request)),
                "tuners": playback.load(ctx.db).tuners,
                "fillers": {k: fillers[k] for k in ("commercials", "trailers")},
            }
        plex_state, present = await asyncio.gather(plex_status(), media_dir_present())
        url = base_url(request)
        return {
            "version": __version__,
            "plex": plex_state,
            "tunerUrl": url,
            "xmltvUrl": f"{url}/xmltv.xml",
            "m3uUrl": f"{url}/stations.m3u",
            "guideUrl": f"{url}/guide.xml",
            "deviceId": ctx.device_id,
            "streams": streams_now(),
            "tuners": playback.load(ctx.db).tuners,
            "hdr": ctx.tone_mapping,
            "subtitles": ctx.subtitling,
            "mediaAccess": ctx.media_access.as_dict(settings.media_dir, present),
            "encoding": ctx.gpu.as_dict(),
            "brokenCount": len(ctx.broken.keys()),
            "brokenFile": str(ctx.broken.path),
            "guide": ctx.updater.as_dict(),
            "fillers": ctx.fillers.as_dict(),
        }

    def streams_now(user: User | None = None) -> list[dict]:
        """The stations being sent to Plex (or another player) right now
        (those `user` can see)."""
        streams = []
        now = now_ms()
        viewer = ctx.viewing.viewer(user)
        for cid, b in ctx.broadcasters.items():
            if not b.running or not ctx.viewing.sees_station(viewer, cid):
                continue
            channel = ctx.db.get_channel(cid)
            np = b.now_playing
            # (The apps watching a station share one viewer, and those with
            # night mode's sound another: count the apps.)
            viewers = len(b.viewers)
            for night in (False, True):
                if (for_apps := ctx.hls_streams.get(cid, night)) is not None:
                    viewers += for_apps.watching() - 1
            # What's on screen: the stream runs a few seconds ahead of it.
            slot = ctx.station(cid).locate(now)
            on_between = between(slot, now) if slot else None
            streams.append(
                {
                    "number": channel.number if channel else None,
                    "name": channel.name if channel else None,
                    "viewers": max(0, viewers),
                    "since": b.started_at_ms,
                    "playing": _item_json(np.playing) if np and np.playing else None,
                    "scheduled": _item_json(np.scheduled) if np else None,
                    "replaced": bool(np and np.replaced),
                    # "commercials", "trailers" or "station id" after a program
                    "between": {"kind": on_between, "after": _item_json(slot.item)}
                    if slot and on_between
                    else None,
                    "offAir": b.off_air,
                    "offAirWhy": b.off_air_why if b.off_air else "",
                }
            )
        return streams

    @app.get("/api/libraries", dependencies=[asking_plex])
    async def libraries():
        # (Not the folders Plex keeps them in: the page doesn't need to know.)
        return [
            {"key": s["key"], "title": s["title"], "type": s["type"]}
            for s in await ctx.library.libraries()
        ]

    @app.get("/api/libraries/{key}/items", dependencies=[asking_plex])
    async def library_items(key: str):
        if not key.isdigit():
            raise HTTPException(404)
        return await ctx.library.library_items(key)

    def picture_sizes(items: list[Item]) -> dict | None:
        """How large the station's pictures are, as Plex lists them:
        {"size": "4K", "1080p", "720p", "SD" or "Mixed", "counts": {size: n}};
        None until Plex has said for any of them."""
        counts = Counter(
            found for i in items if (found := ctx.plex.resolutions.get(i.rating_key)) is not None
        )
        if not counts:
            return None
        only = next(iter(counts)) if len(counts) == 1 else "Mixed"
        return {"size": only, "counts": dict(counts.most_common())}

    def channel_json(channel: Channel, **extra) -> dict:
        eras = ctx.db.eras(channel.id)
        latest = ctx.db.latest_era(channel.id)
        now = now_ms()
        # The latest change (not a special, nor the station carrying on
        # after one), and the next special of each kind.
        changed = next(
            (e for e in reversed(eras) if not e.special and not specials.carries_on(e)), None
        )
        coming: dict[str, dict] = {}
        for e in eras:
            special = e.special or {}
            kind = special.get("kind")
            if kind and kind not in coming and e.start_ms is not None and e.start_ms > now:
                coming[kind] = {"title": special.get("title") or "", "at": e.start_ms}
        station = ctx.station(channel.id)
        slot = station.locate(now)
        check = ctx.checks.get(channel.id)
        playing = ctx.broadcasters.get(channel.id)
        pending = ctx.updater.pending.get(channel.id)
        return {
            "id": channel.id,
            "number": channel.number,
            "name": channel.name,
            "logo": channel.logo,
            **{api: getattr(channel, column) for column, api, _ in STATION_SETTINGS},
            "sources": channel.sources,
            "itemCount": len(latest.items) if latest else 0,
            # Programs with an intro or credits being skipped.
            "trimmedCount": latest.trimmed_count if latest else 0,
            "loopMs": latest.total_ms if latest else 0,
            # The size of its programs' pictures, as Plex lists them (its
            # own picture size is "picture").
            "programPictures": picture_sizes(latest.items if latest else []),
            "builtAt": changed.created_ms if changed else 0,
            "nextMarathon": coming.get(specials.MARATHON),
            "nextFeature": coming.get(specials.FEATURE),
            "nextBlock": coming.get(specials.BLOCK),
            "lastChange": {
                "at": changed.created_ms,
                "startsAt": changed.start_ms,
                "reason": changed.reason,
                "added": changed.added,
                "removed": changed.removed,
            }
            if changed
            else None,
            "pending": pending.as_dict() if pending else None,
            "brokenCount": len(latest.rating_keys & ctx.broken.keys()) if latest else 0,
            # Nothing on it could play (see Broadcaster.off_air), just now.
            "offAir": bool(playing and playing.running and playing.off_air),
            "offAirWhy": playing.off_air_why if playing and playing.off_air else "",
            # When it was made (or, for a station made before 1.15, when it's
            # known to have been on the air by: createdExact false).
            "createdAt": channel.created_ms or None,
            "createdExact": channel.created_exact,
            "mostlyOneShow": bool(
                latest and channel.order_mode == "shuffle" and _mostly_one_show(latest.show_counts)
            ),
            "now": {
                **_item_json(slot.item),
                "start": slot.start_ms,
                "end": slot.end_ms,
                "special": specials.label(station.special(slot), slot.index),
            }
            if slot
            else None,
            "check": check.as_dict() if check else None,
            **extra,
        }

    async def gather_items(sources: list[dict], skip_intros: bool) -> list[Item]:
        try:
            items = await ctx.updater.gather(sources, skip_intros)
        except LibraryError as e:
            raise HTTPException(502, f"Couldn't read from Plex: {e}") from e
        if not items:
            raise HTTPException(400, "Those selections contain no playable episodes or movies")
        return items

    async def as_aired(channel: Channel, items: list[Item]) -> list[Item]:
        """The programs with the station's commercials or trailers, and
        Station ID card, after each."""
        if channel.breaks:
            await ctx.fillers.ready()
        return ctx.updater.with_breaks(channel, items)

    def check_logo(logo: str | None) -> None:
        if logo and not ctx.logos.exists(logo):
            raise HTTPException(400, "That logo isn't available. Choose another one.")

    def validate(body: ChannelIn, channel_id: int | None = None) -> None:
        if body.logo:
            body.logo = ctx.logos.resolve(body.logo)  # a logo from before 1.7: its new one
        for name, value, allowed in (
            ("orderMode", body.orderMode, ORDER_MODES),
            ("aspectMode", body.aspectMode, ASPECT_MODES),
            ("picture", body.picture, tuple(PICTURES)),
            ("subtitles", body.subtitles, subtitles.MODES),
            ("idSeconds", body.idSeconds, ID_LENGTHS),
            ("watermark", body.watermark, WATERMARK_MODES),
            ("watermarkSize", body.watermarkSize, WATERMARK_SIZES),
            ("watermarkTransparency", body.watermarkTransparency, WATERMARK_TRANSPARENCIES),
            ("watermarkPosition", body.watermarkPosition, WATERMARK_POSITIONS),
            ("watermarkTiming", body.watermarkTiming, WATERMARK_TIMINGS),
            ("watermarkStyle", body.watermarkStyle, WATERMARK_STYLES),
            ("clockFormat", body.clockFormat, CLOCK_FORMATS),
            ("introSeconds", body.introSeconds, INTRO_LENGTHS),
            ("tuneIn", body.tuneIn, intro.TUNE_IN),
            ("upNextSeconds", body.upNextSeconds, upnext.LENGTHS),
            ("upNextSize", body.upNextSize, upnext.SIZES),
            ("marathonMode", body.marathonMode, marathons.MODES),
            ("marathonsAWeek", body.marathonsAWeek, range(1, marathons.MAX_A_WEEK + 1)),
            ("marathonEpisodes", body.marathonEpisodes, marathons.EPISODE_CHOICES),
            ("featureMode", body.featureMode, specials.FEATURE_MODES),
        ):
            if value is not None and value not in allowed:
                raise HTTPException(400, f"{name} must be one of {', '.join(map(str, allowed))}")
        if body.marathonDays is not None and not marathons.valid_days(body.marathonDays):
            raise HTTPException(
                400, "marathonDays must be days of the week, like 0,5 (0 is Monday)"
            )
        if body.marathonTime is not None and not marathons.valid_time(body.marathonTime):
            raise HTTPException(400, "marathonTime must be a time of day in HH:MM format")
        if body.featureDays is not None and not marathons.valid_days(body.featureDays):
            raise HTTPException(400, "featureDays must be days of the week, like 0,5 (0 is Monday)")
        if body.featureTime is not None and not marathons.valid_time(body.featureTime):
            raise HTTPException(400, "featureTime must be a time of day in HH:MM format")
        if body.featureSource:
            problem = _feature_source_problem(body.featureSource)
            if problem:
                raise HTTPException(400, problem)
        check_sources(body.sources, "A station")
        current = ctx.db.get_channel(channel_id) if channel_id is not None else None
        ids = {str(b.get("id")) for b in current.blocks} if current else set()
        taken: set[str] = set()
        for block in body.blocks or []:
            problem = specials.block_problem(block.model_dump())
            if problem:
                raise HTTPException(400, problem)
            check_sources(block.sources, f"The block \u201c{block.name}\u201d")
            # A block keeps its id (and so where it got to); a new one gets one.
            if block.id not in ids or block.id in taken:
                block.id = secrets.token_hex(4)
            taken.add(block.id)
        check_logo(body.logo)
        if body.introVideo and ctx.bumpers.get(body.introVideo) is None:
            # (Unless it's the one the station has, even if it's gone missing:
            # it plays StationPlay's own bumper until you choose another.)
            current = ctx.db.get_channel(channel_id) if channel_id is not None else None
            if current is None or current.intro_video != body.introVideo:
                raise HTTPException(
                    400, "That Intro Bumper video isn't available. Choose another one."
                )
        check_number(body.number, channel_id)

    def check_sources(sources: list[dict], what: str) -> None:
        for source in sources:
            problem = _source_problem(source)
            if problem:
                raise HTTPException(400, problem)
        # Each of these is a whole library (or a query of one) to read from Plex.
        whole = sum(s.get("type") in ("section", "filter", "collection") for s in sources)
        if whole > PLEX_QUERIES_MAX:
            raise HTTPException(
                400,
                f"{what} can use at most {PLEX_QUERIES_MAX} libraries, filters, and collections",
            )
        if len({json.dumps(s, sort_keys=True) for s in sources}) != len(sources):
            raise HTTPException(400, "The same show, movie, library, or filter is listed twice")

    def check_timing(settings: dict[str, Any]) -> None:
        """That a station's blocks, Feature Presentation and marathons at set
        times don't fall over each other (settings by their stored names)."""
        problem = specials.timing_problem(settings)
        if problem:
            raise HTTPException(400, problem)

    async def gather_sets(channel: Channel, raw: bool = False) -> dict[str, list[Item]]:
        """The programs a station's Feature Presentation and blocks draw on
        (`raw`: without the breaks after each)."""
        try:
            if raw:
                return await ctx.updater.gather_set_programs(channel)
            return await ctx.updater.gather_sets(channel)
        except LibraryError as e:
            raise HTTPException(502, f"Couldn't read from Plex: {e}") from e

    def check_specials_play(
        channel: Channel, items: list[Item], sets: dict[str, list[Item]]
    ) -> None:
        """That a station's Feature Presentation has movies, and its blocks
        programs, to play (`items`: the station's own; `sets`: theirs)."""
        if channel.feature_mode == "on":
            own = not channel.feature_source
            pool = items if own else sets.get(specials.FEATURE, [])
            if not any(i.kind == "movie" for i in pool):
                raise HTTPException(
                    400,
                    "This station has no movies of its own for the Feature Presentation. "
                    "Choose a movie library or collection for it."
                    if own
                    else "That library or collection has no movies for the Feature Presentation",
                )
        for block in channel.blocks:
            if not sets.get(specials.set_name(specials.BLOCK, str(block.get("id")))):
                raise HTTPException(
                    400, f"The block \u201c{block.get('name')}\u201d has nothing to play"
                )

    def check_number(number: int, channel_id: int | None = None) -> None:
        clash = ctx.db.get_channel_by_number(number)
        if clash and clash.id != channel_id:
            raise HTTPException(409, f"Station {number} already exists ({clash.name})")

    async def after_change() -> bool:
        """Asks Plex to reload its guide after a change you made, so its
        guide catches up before the change starts."""
        try:
            return await asyncio.wait_for(ctx.updater.ask_plex_to_reload_guide(), 10)
        except TimeoutError:
            return False

    async def change(
        channel_id: int,
        items: list[Item],
        reason: str,
        fresh: bool,
        sets: dict[str, list[Item]] | None = None,
    ) -> dict:
        await ctx.updater.apply(
            channel_id,
            items,
            not_before_ms=now_ms() + MARGIN_MS,
            reason=reason,
            fresh=fresh,
            sets=sets,
        )
        ctx.scanner.wake()  # check anything new
        refreshed = await after_change()
        return channel_json(channel_or_404(channel_id), changed=True, plexGuideRefreshed=refreshed)

    @app.get("/api/channels")
    async def list_channels(request: Request):
        user = access.signed_in(request)
        names = {u.id: u.name for u in ctx.db.users()} if ctx.access.required else {}

        def made_by(c: Channel) -> str | None:
            """Who made a station, while signing in is on: their name, or that
            they've been removed (None: made while it was off, or unknown)."""
            if not names or c.created_by is None:
                return None
            return names.get(c.created_by, "a removed user")

        return [
            channel_json(
                c,
                mayChange=access.may_change(user, c),
                mine=user is not None and c.created_by == user.id,
                madeBy=made_by(c),
            )
            for c in ctx.stations_for(user)
        ]

    def room_for_one_more(user: User | None) -> None:
        try:
            ctx.access.check_room(user)
        except access.NoRoom as e:
            raise HTTPException(403, str(e)) from None

    async def make_station(body: ChannelIn, request: Request) -> Channel:
        """A new station: what it plays, gathered from Plex, and its schedule.
        It's whoever's asking's (if signing in is on), if they may make
        another."""
        user = access.signed_in(request)
        room_for_one_more(user)
        validate(body)
        pb = playback.load(ctx.db)
        settings = {**NEW_STATION, **pb.new_station, "picture": pb.picture, **body.settings()}
        check_timing(settings)
        items = await gather_items(body.sources, bool(settings["skip_intros"]))
        draft = Channel(0, body.number, body.display_name, body.sources, "", **settings)
        sets = await gather_sets(draft, raw=True)
        check_specials_play(draft, items, sets)
        logo = body.logo
        if logo is None:
            logo = ctx.logos.pick({c.logo for c in ctx.db.list_channels()}, number=body.number)
        # Again: while Plex was asked, the logo may have been deleted, another
        # station given the number, or another station made by them.
        check_logo(logo)
        check_number(body.number)
        room_for_one_more(user)
        channel = ctx.db.create_channel(
            body.number,
            body.display_name,
            body.sources,
            logo,
            created_by=user.id if user else None,
            **settings,
        )
        await ctx.updater.create(
            channel.id,
            await as_aired(channel, items),
            channel.order_mode,
            await ctx.updater.sets_as_aired(channel, sets),
        )
        # Its files are checked straight away (the station's card shows how
        # that's going), and the scanner looks out for new programs.
        if jobs.CHECK_NEW_STATIONS:
            jobs.start_check(ctx, channel.id)
        ctx.scanner.wake()
        ctx.icon_cache.pop(body.number, None)
        return channel_or_404(channel.id)

    @app.post("/api/channels", status_code=201, dependencies=[asking_plex])
    async def create_channel(body: ChannelIn, request: Request):
        channel = await make_station(body, request)
        refreshed = await after_change()
        return channel_json(channel, plexGuideRefreshed=refreshed)

    # Stations from Plex's collections ------------------------------------

    async def named_collections() -> list[dict]:
        """Plex's collections, in the order Plex lists its libraries, each
        with the name its station gets (the collection's own, numbered when
        several have the same name: Sunshine1, Sunshine2) and the station
        that already follows it, if one does."""
        found = [c for c in await ctx.library.collections() if collection_key(c["title"])]
        following: dict[str, int] = {}
        for channel in ctx.db.list_channels():
            for source in channel.sources:
                if source.get("type") == "collection":
                    followed = ctx.library.followed_collection(source, found)
                    if followed is not None:
                        following.setdefault(followed["ratingKey"], channel.number)
        names = Counter(collection_key(c["title"]) for c in found)
        seen: Counter[str] = Counter()
        for entry in found:
            key = collection_key(entry["title"])
            seen[key] += 1
            name = " ".join(entry["title"].split())
            entry["name"] = _numbered(name, seen[key]) if names[key] > 1 else name[:NAME_MAX]
            entry["station"] = following.get(entry["ratingKey"])
        return found

    @app.get("/api/collections", dependencies=[asking_plex])
    async def plex_collections():
        return sorted(await named_collections(), key=lambda c: c["name"].lower())

    @app.post("/api/collections/stations", status_code=201, dependencies=[asking_plex])
    async def collection_stations(body: CollectionStations, request: Request):
        """A station for each of these collections, from the next free
        numbers: named after it, with the Collection logo, and set up as new
        stations are (shuffled). Each follows its collection: what's added to
        it in Plex joins the station."""
        found = {c["ratingKey"]: c for c in await named_collections()}
        logo = COLLECTION_LOGO if ctx.logos.exists(COLLECTION_LOGO) else None
        made: list[dict] = []
        problems: list[str] = []
        for key in dict.fromkeys(body.ratingKeys):
            c = found.get(key)
            if c is None:
                problems.append(f"Plex no longer has the collection {key!r}")
                continue
            source = {
                "type": "collection", "ratingKey": c["ratingKey"], "title": c["title"],
                "library": c["library"], "kind": c["kind"],
            }  # fmt: skip
            used = {ch.number for ch in ctx.db.list_channels()}
            number = next(n for n in range(1, 10_000) if n not in used)
            made_from = ChannelIn(number=number, name=c["name"], logo=logo, sources=[source])
            try:
                channel = await make_station(made_from, request)
            except HTTPException as e:
                problems.append(f"{c['name']}: {e.detail}")
                continue
            log.info("Made station %s from the Plex collection %r", number, c["name"])
            made.append(channel_json(channel))
        if not made:
            raise HTTPException(400, "; ".join(problems) or "No collections were chosen")
        refreshed = await after_change()
        return {"made": made, "problems": problems, "plexGuideRefreshed": refreshed}

    # Smart stations (see smart.py) ----------------------------------------

    @app.post("/api/smart/split", dependencies=[asking_plex])
    async def smart_split(body: SmartSplitIn):
        """How many movies or shows a filter matches for each decade, genre,
        studio... (whatever it's split by), as Plex has them now."""
        source = {**body.filter, "type": "filter"}
        problem = _source_problem(source)
        if problem:
            raise HTTPException(400, problem)
        if body.split != "decade" and not body.split.isalpha():
            raise HTTPException(400, f"Can't split by {body.split!r}")
        try:
            groups, limited = await smart.split(ctx.library, source, body.split)
        except smart.SplitProblem as e:
            raise HTTPException(400, str(e)) from e
        except LibraryError as e:
            raise HTTPException(502, f"Couldn't read from Plex: {e}") from e
        return {"groups": groups, "limited": limited, "most": smart.MAX_GROUPS}

    @app.post("/api/smart/stations", status_code=201, dependencies=[asking_plex])
    async def smart_stations(body: SmartStationsIn, request: Request):
        """A station for each filter given, from the next free numbers from
        `firstNumber`, set up as new stations are."""
        made: list[dict] = []
        problems: list[str] = []
        for n, wanted in enumerate(body.stations):
            what = wanted.name or "A station"
            if wanted.source.get("type") != "filter":
                problems.append(f"{what}: its source isn't a filter")
                continue
            stop = None
            # The next free number (and the next again, if it's taken
            # while Plex is being asked).
            for _ in range(5):
                used = {c.number for c in ctx.db.list_channels()}
                number = next((x for x in range(body.firstNumber, 10_000) if x not in used), None)
                if number is None:
                    stop = f"there are no free station numbers at or above {body.firstNumber}"
                    break
                asked = ChannelIn(number=number, name=wanted.name, sources=[wanted.source])
                try:
                    channel = await make_station(asked, request)
                except HTTPException as e:
                    if e.status_code == 409:
                        continue  # (that number was just taken)
                    if e.status_code in (403, 502):
                        stop = str(e.detail)  # (no room for more; Plex can't be reached)
                    else:
                        problems.append(f"{what}: {e.detail}")
                    break
                log.info("Made station %s (%s) from a filter", number, channel.name)
                made.append(channel_json(channel))
                break
            else:
                problems.append(f"{what}: other new stations kept taking its number")
            if stop is not None:
                left = len(body.stations) - n
                problems.append(
                    f"{what}{f' and {left - 1} more' if left > 1 else ''} weren't made: {stop}"
                    if left > 1
                    else f"{what}: {stop}"
                )
                break
        if not made:
            raise HTTPException(400, "; ".join(problems) or "No stations were chosen")
        refreshed = await after_change()
        return {"made": made, "problems": problems, "plexGuideRefreshed": refreshed}

    @app.put("/api/channels/{channel_id}", dependencies=[asking_plex])
    async def update_channel(channel_id: int, body: ChannelIn, request: Request):
        channel = changeable(channel_id, request)
        validate(body, channel_id)
        settings = body.settings()
        after = replace(channel, **settings, sources=body.sources)
        order_changed = after.order_mode != channel.order_mode
        # What airs changes with the programs, their order, skipping, or the
        # breaks after each (commercials, trailers, the Station ID card).
        content_changed = (
            after.sources != channel.sources
            or order_changed
            or after.skip_intros != channel.skip_intros
            or after.breaks != channel.breaks
            or id_card_ms(after) != id_card_ms(channel)
        )
        check_timing({c: getattr(after, c) for c in SPECIAL_SETTINGS})
        # Specials are planned again from the next break (with the station
        # as it is, if that's all that changed), from the programs they draw
        # on as Plex has them now.
        specials_changed = any(
            getattr(after, c) != getattr(channel, c) for c in SPECIAL_SETTINGS
        ) and (specials.has_specials(after) or specials.has_specials(channel))
        items = await gather_items(body.sources, after.skip_intros) if content_changed else None
        sets = await gather_sets(after) if content_changed or specials_changed else None
        if sets is not None:
            check_specials_play(after, items or ctx.db.latest_items(channel_id), sets)
        # Again: while Plex was asked, the logo may have been deleted, or
        # another station given the number.
        check_logo(body.logo)
        check_number(body.number, channel_id)
        ctx.db.update_channel(
            channel_id,
            number=body.number,
            name=body.display_name,
            sources=body.sources,
            logo=body.logo,  # None: as it was
            **settings,
        )
        ctx.icon_cache.pop(channel.number, None)
        ctx.icon_cache.pop(body.number, None)
        if items is not None:
            # New content (or skipping intros and credits, or different
            # breaks) carries on from what's airing; a new order starts
            # afresh. Either way at the next break a minute or more away.
            items = await as_aired(channel_or_404(channel_id), items)
            return await change(channel_id, items, "edit", fresh=order_changed, sets=sets)
        if specials_changed:
            return await change(
                channel_id, ctx.db.latest_items(channel_id), "edit", fresh=False, sets=sets
            )
        return channel_json(channel_or_404(channel_id))

    # Made one at a time: each takes a few seconds of the processor.
    previews = Turns("Other previews are being made. Try again in a moment.", most_waiting=2)

    @app.post("/api/intro/preview")
    async def card_preview(body: CardPreview):
        """The Intro Bumper, Station ID card or Feature Presentation card as
        the editor has it, as a short MP4 with sound."""
        feature = body.kind == intro.FEATURE
        ident = body.kind == intro.IDENT or feature
        if feature:
            body.seconds = specials.FEATURE_CARD_MS // 1000  # (always this long)
        lengths = ID_LENGTHS if body.kind == intro.IDENT else INTRO_LENGTHS[1:]
        if not feature and body.seconds not in lengths:
            raise HTTPException(400, f"seconds must be one of {', '.join(map(str, lengths))}")
        logo = ctx.logos.path(ctx.logos.resolve(body.logo)) if body.logo else None
        station = None
        if body.channelId is not None and ctx.db.get_channel(body.channelId):
            station = ctx.station(body.channelId)
        if feature:
            now = SAMPLE_FEATURE
            coming = next(
                (
                    e.special
                    for e in (ctx.db.eras(body.channelId) if body.channelId and station else [])
                    if (e.special or {}).get("kind") == specials.FEATURE
                    and (e.start_ms or 0) > now_ms()
                ),
                None,
            )
            if coming:
                now = ("", str(coming.get("title") or ""), str(coming.get("year") or ""))
        elif ident:
            now = SAMPLE_UP_NEXT
            if station is not None:
                slot = station.locate(now_ms())
                following = station.locate(slot.end_ms) if slot else None
                if following is not None:
                    now = ("UP NEXT", *intro.describe(following.item))
        else:
            now = (
                intro.whats_on(station, now_ms() + body.seconds * 1000)[0]
                if station is not None
                else ("", "", "")
            )
        card = intro.Card(
            "Feature Presentation" if feature else body.name.strip() or f"Station {body.number}",
            body.number,
            "" if ident else " ".join(body.description.split()),
            str(logo) if logo else None,
            now,
            body.kind,
        )
        root = ctx.settings.data_dir / "intro"
        async with previews.turn():
            root.mkdir(parents=True, exist_ok=True)
            folder = Path(tempfile.mkdtemp(prefix="preview-", dir=root))
            try:
                if not usable_picture(str(folder)):
                    raise HTTPException(
                        500,
                        "Previews can't be made because the data folder's path has special "
                        "characters",
                    )
                # The pictures first: the reel is made from what was drawn.
                colours = await intro.colours(ctx.settings, card.logo)
                stills = intro.stills_command(ctx.settings, card, colours, folder)
                await _run_to_end(stills, "The preview")
                out = folder / "preview.mp4"
                how = intro.motion(body.seconds)
                if ident:
                    jingle = intro.jingle() if body.sound else None
                    reel = intro.ident_preview_command(
                        ctx.settings, body.seconds, folder, jingle, out, how
                    )
                else:
                    show = (
                        await intro.find_show_audio(ctx, station, now_ms(), body.seconds)
                        if station is not None
                        else None
                    )
                    sound = intro.sound(body.seconds) if body.sound else None
                    reel = intro.preview_command(
                        ctx.settings, body.seconds, folder, sound, out, how, show
                    )
                await _run_to_end(reel, "The preview")
                data = out.read_bytes()
            finally:
                shutil.rmtree(folder, ignore_errors=True)
        return Response(data, media_type="video/mp4", headers={"Cache-Control": "no-store"})

    @app.post("/api/upnext/preview")
    async def banner_preview(body: BannerPreview):
        """The Up Next Banner as the editor has it, with what's in the
        corner, over a plain picture, as a short MP4."""
        for name, value, allowed in (
            ("seconds", body.seconds, upnext.LENGTHS[1:]),
            ("size", body.size, upnext.SIZES),
            ("watermark", body.watermark, WATERMARK_MODES),
            ("watermarkSize", body.watermarkSize, WATERMARK_SIZES),
            ("watermarkTransparency", body.watermarkTransparency, WATERMARK_TRANSPARENCIES),
            ("watermarkPosition", body.watermarkPosition, WATERMARK_POSITIONS),
            ("watermarkTiming", body.watermarkTiming, WATERMARK_TIMINGS),
            ("watermarkStyle", body.watermarkStyle, WATERMARK_STYLES),
            ("clockFormat", body.clockFormat, CLOCK_FORMATS),
        ):
            if value not in allowed:
                raise HTTPException(400, f"{name} must be one of {', '.join(map(str, allowed))}")
        # The station as the editor has it.
        settings: dict[str, Any] = {
            **NEW_STATION,
            "up_next_seconds": body.seconds,
            "up_next_size": body.size,
            "watermark": body.watermark,
            "watermark_size": body.watermarkSize,
            "watermark_transparency": body.watermarkTransparency,
            "watermark_position": body.watermarkPosition,
            "watermark_timing": body.watermarkTiming,
            "watermark_style": body.watermarkStyle,
            "clock_format": body.clockFormat,
        }
        name = body.name.strip() or f"Station {body.number}"
        logo = ctx.logos.resolve(body.logo) if body.logo else ""
        channel = Channel(0, body.number, name, [], logo, **settings)
        title = SAMPLE_UP_NEXT[1]
        if body.channelId is not None and ctx.db.get_channel(body.channelId):
            station = ctx.station(body.channelId)
            slot = station.locate(now_ms())
            following = station.locate(slot.end_ms) if slot else None
            if following is not None:
                title = intro.describe(following.item)[0]
        mark = corner_mark(ctx, channel)
        banner = station_banner(ctx, channel, title, mark)
        if mark is not None and mark.until_s is not None:
            mark = None  # shown only at the start of programs: gone by then
        elif mark is not None and mark.clock:
            mark = replace(mark, clock_at_s=time.time())
        root = ctx.settings.data_dir / "upnext"
        async with previews.turn():
            root.mkdir(parents=True, exist_ok=True)
            folder = Path(tempfile.mkdtemp(prefix="preview-", dir=root))
            try:
                picture, out = folder / "banner.png", folder / "preview.mp4"
                where = await upnext.draw(ctx.settings, banner, picture, timeout_s=60)
                if where is None:
                    raise HTTPException(
                        500, "The preview couldn't be made. An Admin can see why on the Logs tab."
                    )
                await _run_to_end(
                    upnext.preview_command(ctx.settings, banner, picture, where, mark, out),
                    "The preview",
                )
                data = out.read_bytes()
            finally:
                shutil.rmtree(folder, ignore_errors=True)
        return Response(data, media_type="video/mp4", headers={"Cache-Control": "no-store"})

    @app.post("/api/channels/{channel_id}/update", dependencies=[asking_plex])
    async def update_from_plex(channel_id: int, request: Request):
        """Update now: follow Plex straight away, even with a held update."""
        channel = changeable(channel_id, request)
        items = await as_aired(channel, await gather_items(channel.sources, channel.skip_intros))
        sets = await gather_sets(channel)
        if not compare(ctx.db.latest_items(channel_id), items)[2] and not (
            ctx.updater.sets_changed(channel_id, sets)
        ):
            ctx.updater.pending.pop(channel_id, None)
            return channel_json(channel, changed=False)
        return await change(channel_id, items, "update", fresh=False, sets=sets)

    @app.post("/api/channels/{channel_id}/reshuffle", dependencies=[asking_plex])
    async def reshuffle(channel_id: int, request: Request):
        channel = changeable(channel_id, request)
        items = await as_aired(channel, await gather_items(channel.sources, channel.skip_intros))
        return await change(channel_id, items, "reshuffle", fresh=True)

    @app.delete("/api/channels/{channel_id}", status_code=204)
    async def delete_channel(channel_id: int, request: Request):
        changeable(channel_id, request)
        b = ctx.broadcasters.pop(channel_id, None)
        if b:
            await b.stop("the station was deleted")
        forget_eras([e.id for e in ctx.db.eras(channel_id)])
        ctx.db.delete_channel(channel_id)
        ctx.updater.pending.pop(channel_id, None)
        return Response(status_code=204)

    @app.get("/api/channels/{channel_id}/guide")
    async def channel_guide(
        channel_id: int, request: Request, hours: float = STATION_GUIDE_MAX_HOURS
    ):
        channel_or_404(channel_id)
        if not ctx.sees_station(access.signed_in(request), channel_id):
            raise HTTPException(404)  # (as one that doesn't exist)
        broken = ctx.broken.keys()
        now = now_ms()
        until = now + int(max(0.5, min(hours, STATION_GUIDE_MAX_HOURS)) * 3600 * 1000)

        def listing() -> list[dict]:  # on a worker thread: a big shuffle takes a moment
            station = ctx.station(channel_id)
            return [
                {
                    **_item_json(slot.item),
                    "start": slot.start_ms,
                    "end": slot.end_ms,
                    "broken": slot.item.rating_key in broken,
                    "special": specials.label(station.special(slot), slot.index),
                }
                for slot in station.between(now, until)
            ]

        return await asyncio.to_thread(listing)

    # Filters ----------------------------------------------------------------

    def library_keys(libraries: str) -> list[str]:
        keys = dict.fromkeys(k for k in libraries.split(",") if k.isdigit())
        return list(keys)[:LIBRARIES_MAX]

    @app.get("/api/filter/fields", dependencies=[asking_plex])
    async def filter_fields(kind: str, libraries: str):
        """What the chosen libraries can be filtered on (whatever this Plex
        offers: genre, content rating, network, studio...), each with its
        choices, and their decades. People (directors, actors...) can
        number tens of thousands, so they're searched instead."""
        kind = "show" if kind == "show" else "movie"
        keys = library_keys(libraries)
        titles: dict[str, str] = {}
        for key in keys:
            for f in await ctx.library.filter_fields(key, kind):
                titles.setdefault(f["field"], f["title"])
        fields = []
        for name, title in titles.items():
            if name in PEOPLE_FIELDS:
                fields.append({"field": name, "title": title, "search": True})
                continue
            names: set[str] = set()
            for key in keys:
                names.update(c["title"] for c in await ctx.library.choices(key, name, kind))
            if names:
                fields.append(
                    {"field": name, "title": title, "choices": sorted(names, key=str.lower)}
                )
        decades: set[int] = set()
        for key in keys:
            for c in await ctx.library.choices(key, "decade", kind):
                with contextlib.suppress(ValueError):
                    decades.add(int(c["id"]) // 10 * 10)
        return {"fields": fields, "decade": sorted(decades)}

    @app.get("/api/filter/search", dependencies=[asking_plex])
    async def filter_search(kind: str, libraries: str, field: str, q: str = ""):
        """Names for one filter (directors, actors...) that contain `q`."""
        kind = "show" if kind == "show" else "movie"
        words = q.strip().lower()
        if len(words) < 2:
            return []
        names: set[str] = set()
        for key in library_keys(libraries):
            names.update(
                c["title"]
                for c in await ctx.library.choices(key, field, kind)
                if words in c["title"].lower()
            )
        return sorted(names, key=lambda n: (not n.lower().startswith(words), n.lower()))[:20]

    @app.post("/api/filter/preview", dependencies=[asking_plex])
    async def filter_preview(source: dict):
        """What a filter matches right now: how many movies or shows (and
        episodes), some of their names, and all of them (each with whether
        it's left out), for choosing which to leave out. (The page counts
        from `items` itself, as people untick them.)"""
        problem = _source_problem({**source, "type": "filter"})
        if problem:
            raise HTTPException(400, problem)
        left_out = set(source.get("exclude") or [])
        everything = {**source, "exclude": []}
        # Each show or movie, by rating key, with its episodes (for TV).
        episodes: dict[str, int] | None = None
        if source.get("kind") == "show" and source.get("addedWithinDays"):
            # New episodes: the shows are the ones they belong to.
            eps = await ctx.library.filter_episodes(everything)
            episodes = Counter(str(e.get("grandparentRatingKey")) for e in eps)
            shows = {str(e.get("grandparentRatingKey")): e.get("grandparentTitle", "") for e in eps}
            matches = [{"ratingKey": key, "title": title} for key, title in shows.items()]
        else:
            matches = await ctx.library.filter_matches(everything)
            if source.get("kind") == "show":
                episodes = {str(m.get("ratingKey")): int(m.get("leafCount") or 0) for m in matches}
        # One entry per title (a movie in two libraries is one).
        found: dict[str, dict] = {}
        for m in sorted(matches, key=lambda m: str(m.get("title", "")).lower()):
            label = f"{m.get('title', '')}" + (f" ({m['year']})" if m.get("year") else "")
            key = str(m.get("ratingKey"))
            entry = found.setdefault(
                label,
                {"ratingKeys": [], "title": m.get("title", ""), "year": m.get("year"),
                 "genres": genres(m), "episodes": 0},
            )  # fmt: skip
            entry["ratingKeys"].append(key)
            entry["episodes"] = max(entry["episodes"], (episodes or {}).get(key, 0))
        items = list(found.values())
        for entry in items:
            entry["included"] = not left_out.intersection(entry["ratingKeys"])
        included = [(label, e) for label, e in found.items() if e["included"]]
        return {
            "matches": len(included),
            "episodes": sum(e["episodes"] for _, e in included) if episodes is not None else None,
            "examples": [label for label, _ in included[:12]],
            "leftOut": len(items) - len(included),
            "items": items,
        }

    @app.post("/api/channels/{channel_id}/check")
    async def check_channel(channel_id: int, request: Request):
        changeable(channel_id, request)
        return jobs.start_check(ctx, channel_id).as_dict()

    @app.get("/api/logs")
    async def recent_logs(levels: str = "", access_log: bool = False, limit: int = 200):
        """The newest log entries: all of them; or those at `levels` (e.g.
        "WARNING,ERROR"), and with `access_log`, the access log's (which is
        kept between restarts)."""
        limit = max(1, min(limit, logbuffer.KEEP))
        wanted = {v.strip().upper() for v in levels.split(",") if v.strip()}
        if not access_log:
            entries = logs.entries(wanted or None, limit)
        else:
            entries = (
                [e for e in logs.entries(wanted, limit) if e["source"] != access.log.name]
                if wanted
                else []
            )
            entries += [
                {"time": ms / 1000, "level": level, "source": access.log.name, "message": message}
                for ms, level, message in ctx.db.access_entries(limit)
            ]
            entries = sorted(entries, key=lambda e: e["time"])[-limit:]
        return {"entries": entries, "text": logbuffer.as_text(entries)}

    @app.get("/api/problems")
    async def recent_problems(days: int = 7):
        """What StationPlay's apps ran into lately (see problems.py), for the
        Logs tab: each problem, how often, and on what kinds of device."""
        names = {u.id: u.name for u in ctx.db.users()}
        return ctx.problems.summary(max(1, min(days, problems.KEEP_DAYS)), names)

    @app.delete("/api/problems", status_code=204)
    async def clear_problems():
        ctx.problems.forget()
        log.info("The apps' problems were cleared")

    # Backups ---------------------------------------------------------------

    @app.get("/api/backups")
    async def list_backups():
        return {"backups": backups.list_backups(settings.data_dir), "keep": backups.KEEP}

    @app.post("/api/backups", status_code=201)
    async def backup_now():
        path = await asyncio.to_thread(backups.make_backup, ctx)
        log.info("Backed up StationPlay to %s", path.name)
        return {"name": path.name}

    @app.get("/api/backups/{name}")
    async def download_backup(name: str):
        path = backups.backup_path(settings.data_dir, name)
        if path is None:
            raise HTTPException(404)
        return FileResponse(path, media_type="application/zip", filename=name)

    restores = Turns("A backup is already being restored")  # (they share restore/)

    @app.post("/api/restore")
    async def restore(request: Request, opening: bool = False):
        """Restores a backup (the request's body): it's checked and set aside,
        then StationPlay restarts and puts it in place on the way up. A backup
        with no users would turn signing in off, so restoring one while it's
        on needs `opening` (409 without)."""
        async with restores.turn():
            data = bytearray()
            async for chunk in request.stream():
                data += chunk
                if len(data) > backups.MAX_UPLOAD:
                    raise HTTPException(413, "That file is too big to be a StationPlay backup")
            try:
                found = await asyncio.to_thread(
                    backups.stage_restore, settings.data_dir, bytes(data)
                )
            except backups.BackupError as e:
                raise HTTPException(400, str(e)) from e
            # Only once all's well is it ready to be put in place: if anything
            # goes wrong (or the browser goes away), it's thrown away.
            try:
                if ctx.access.required and not found["users"] and not opening:
                    raise HTTPException(
                        409,
                        "That backup has no users, so restoring it turns off sign-in. Anyone "
                        "who can reach StationPlay can use it until you add a user again.",
                    )
                problem = await prepare_staged()
                if problem:
                    raise HTTPException(400, f"That backup can't be restored: {problem}")
                await asyncio.to_thread(backups.mark_ready, settings.data_dir)
            except BaseException:
                backups.discard_restore(settings.data_dir)
                raise
        log.warning(
            "Restarting StationPlay to restore a backup with %d stations",
            found["stations"],
        )
        restarts.add(asyncio.create_task(restart_soon()))
        return {**found, "restarting": True}

    async def prepare_staged() -> str | None:
        """Makes a backup set aside to be restored fit to put in place, or
        says why it isn't: it must hold only what StationPlay itself would
        have made. Its stations' names are made plain, and its logos are made
        again (as an uploaded one is), so only pictures StationPlay drew are
        ever put in place."""
        try:
            stations = await asyncio.to_thread(backups.tidy_staged_stations, settings.data_dir)
        except backups.BackupError as e:
            return str(e)
        for name, stored in stations:
            try:
                sources = json.loads(stored)
            except ValueError:
                return f"station {name[:40]!r} is damaged"
            for source in sources if isinstance(sources, list) else [None]:
                why = _source_problem(source) if isinstance(source, dict) else "unknown format"
                if why:
                    return f"station {name[:40]!r} has an invalid source ({why})"
        for path in await asyncio.to_thread(backups.staged_logos, settings.data_dir):
            try:
                png = await to_kept_logo_png(
                    await asyncio.to_thread(path.read_bytes), settings.ffmpeg_path
                )
            except LogoError:
                return f"the logo {path.name} isn't a picture"
            await asyncio.to_thread(path.write_bytes, png)
        return None

    restarts: set[asyncio.Task] = set()

    async def restart_soon() -> None:
        """Restarts StationPlay once the reply has gone. Streams are ended
        first: the web server waits for open connections before it stops,
        and a stream never ends by itself."""
        await asyncio.sleep(1.0)
        for b in list(ctx.broadcasters.values()):
            await b.stop("StationPlay is restarting to restore a backup")
        ctx.restart()

    # Checking files ------------------------------------------------------------

    # Playback: picture sizes, tuners, and what the server can manage --------

    META_SPEED_TEST = "speed_test"  # the last speed test's results, as JSON
    speed_testing = asyncio.Lock()

    def playback_json() -> dict:
        try:
            tested = json.loads(ctx.db.get_meta(META_SPEED_TEST, "null"))
        except ValueError:
            tested = None
        return {**playback.load(ctx.db).as_dict(), "speedTest": tested}

    @app.get("/api/playback")
    async def playback_get():
        return playback_json()

    @app.put("/api/playback")
    async def playback_put(body: PlaybackIn, request: Request):
        before = playback.load(ctx.db)
        try:
            chosen = playback.new_station_from_page(body.newStation or {})
            after = playback.save(
                ctx.db,
                body.picture,
                body.tuners,
                chosen if body.newStation is not None else None,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        user = access.signed_in(request)
        for what, old, new in (
            ("New stations' picture size", before.picture, after.picture),
            ("Tuner count", before.tuners, after.tuners),
        ):
            if old != new:
                log.info(
                    "%s changed from %s to %s%s",
                    what,
                    old,
                    new,
                    f" (by {user.name})" if user else "",
                )
        if after.new_station != before.new_station:
            log.info("New stations' settings changed%s", f" (by {user.name})" if user else "")
        return playback_json()

    # The setup: its questions, and its checks (see setup.py) ------------------

    @app.get("/api/setup")
    async def setup_get():
        return setup.state(ctx.db, len(ctx.db.list_channels()))

    @app.put("/api/setup")
    async def setup_put(body: SetupIn):
        try:
            setup.mark(ctx.db, body.answered)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return setup.state(ctx.db, len(ctx.db.list_channels()))

    @app.get("/api/setup/checks")
    async def setup_checks(offset: int | None = None, zone: str = ""):
        """Whether what's set up is working. `offset` and `zone`: the
        browser's clock (minutes ahead of UTC, and its time zone's name), to
        compare StationPlay's with."""
        if offset is not None and not -1080 <= offset <= 1080:
            offset = None
        plex_state, present = await asyncio.gather(plex_status(), media_dir_present())
        plex_ok = bool(plex_state["ok"])
        plex_pass = None
        if plex_ok:
            with contextlib.suppress(PlexError, TimeoutError):
                plex_pass = await asyncio.wait_for(ctx.plex.plex_pass(), 5)
        made = await asyncio.to_thread(backups.list_backups, settings.data_dir)
        now = now_ms()
        checks = [
            setup.plex_check(plex_state, plex_pass),
            await setup.media_check(ctx, plex_ok, present),
            setup.encoding_check(ctx.gpu.as_dict(), ctx.tone_mapping, ctx.subtitling),
            setup.clock_check(offset, zone[:80]),
            setup.backups_check(made, time.monotonic() - up_since, now),
            setup.dvr_check(plex_ok, ctx.updater.as_dict(), now),
        ]
        return {"checks": [c.as_dict() for c in checks]}

    @app.post("/api/playback/speed-test")
    async def playback_speed_test():
        """How many stations the server could play at once at each size."""
        if speed_testing.locked():
            raise HTTPException(409, "A speed test is already running")
        async with speed_testing:
            try:
                tested = await playback.speed_test(ctx)
            except (RuntimeError, OSError, TimeoutError) as e:
                raise HTTPException(500, f"The speed test didn't work: {e}") from None
        tested["at"] = now_ms()
        ctx.db.set_meta(META_SPEED_TEST, json.dumps(tested))
        return playback_json()

    # How many of StationPlay's apps may watch at once (see capacity.py) ----

    def app_limits_json() -> dict:
        now = now_ms()
        each, picture = capacity.stream_mbps(settings, ctx.db.list_channels())
        rooms = {}
        for where in capacity.WHERE:
            best = ctx.capacity.best(where, now)
            rooms[where] = (
                {"devices": capacity.room(best, each), "test": best.as_dict()} if best else None
            )
        watching = ctx.app_watchers()
        limits_ = ctx.capacity.limits
        return {
            "devices": limits_.devices,
            "away": limits_.away,
            "most": capacity.MOST,
            "eachMbps": each,
            "picture": picture,
            "room": rooms,
            "tests": [t.as_dict() for t in ctx.capacity.tests()],
            "watching": {"devices": len(watching), "away": sum(watching.values())},
        }

    @app.get("/api/app-limits")
    async def app_limits_get():
        return app_limits_json()

    @app.put("/api/app-limits")
    async def app_limits_put(body: AppLimitsIn, request: Request):
        before = ctx.capacity.limits
        try:
            after = ctx.capacity.save(body.devices, body.away)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        if after != before:
            user = access.signed_in(request)
            log.info(
                "Devices that can watch at once in StationPlay's apps: %s; away from home: %s%s",
                after.devices or "no limit",
                after.away or "no limit",
                f" (set by {user.name})" if user else "",
            )
        return app_limits_json()

    async def scan_json() -> dict:
        """How far the checks have got, and going through the broken-files
        list again."""
        return {**(await asyncio.to_thread(ctx.scanner.as_dict)), "list": ctx.list_check.as_dict()}

    @app.get("/api/scan")
    async def scan_status():
        return await scan_json()

    @app.put("/api/scan")
    async def scan_settings(body: ScanWindow):
        try:
            ctx.scanner.set_window(body.on, body.start, body.end)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return await scan_json()

    @app.post("/api/fillers/refresh")
    async def fillers_refresh():
        """Looks in the commercials and trailers folders again now."""
        await ctx.fillers.refresh()
        return ctx.fillers.as_dict()

    @app.get("/api/broken")
    async def broken_list():
        """The list, each entry saying whether its file is missing, and which
        stations have it now ("on")."""
        entries = ctx.broken.entries()
        keys = {str(e["ratingKey"]) for e in entries}
        having = await asyncio.to_thread(jobs.stations_having, ctx, keys) if keys else {}
        return [
            {**e, "missing": replacing.missing(e), "on": having.get(str(e["ratingKey"]), [])}
            for e in entries
        ]

    @app.delete("/api/broken/{rating_key}", status_code=204)
    async def broken_clear(rating_key: str):
        entry = next((e for e in ctx.broken.entries() if e.get("ratingKey") == rating_key), {})
        if not ctx.broken.remove(rating_key):
            raise HTTPException(404)
        ctx.stall_counts.pop(rating_key, None)
        # If a check took it off the air, checks leave this file be now; so
        # does playing it, if it was taken off for what its file is (Dolby
        # Vision with no ordinary picture: it may not have been checked yet).
        file = entry.get("file") if entry.get("problem") == "unsupported" else None
        size = entry.get("fileSize")
        ctx.db.keep_on_air(
            rating_key,
            file if isinstance(file, str) else None,
            size if isinstance(size, int) else 0,
        )
        return Response(status_code=204)

    @app.post("/api/broken/check")
    async def broken_check_again():
        """Goes through the broken-files list again now (see jobs.py)."""
        if not ctx.library.configured:
            raise HTTPException(400, "Plex isn't set up yet")
        return jobs.start_looking_again(ctx).as_dict()

    def arr_entry(rating_key: str) -> dict:
        """An entry on the list, for Sonarr or Radarr to do something about."""
        entry = next((e for e in ctx.broken.entries() if e.get("ratingKey") == rating_key), None)
        if entry is None:
            raise HTTPException(404)
        app_name = replacing.app_for(entry)
        if not replacing.enabled(ctx.db, app_name):
            raise HTTPException(400, f"{ARR_NAMES[app_name]} isn't turned on")
        return entry

    @app.post("/api/broken/{rating_key}/replace", status_code=202)
    async def broken_replace(rating_key: str):
        """Replace (or Try again, or Try another): Sonarr or Radarr tries
        replacing this one, afresh, now."""
        arr_entry(rating_key)
        jobs.start_try_again(ctx, rating_key)
        return Response(status_code=202)

    @app.post("/api/broken/{rating_key}/leave", status_code=204)
    async def broken_leave(rating_key: str):
        """Leave this one to me: Sonarr or Radarr isn't asked to replace it."""
        entry = arr_entry(rating_key)
        async with ctx.list_lock:  # (not while the list's being gone through)
            replacing.leave(ctx, entry)
        log.info(
            "%s: marked \"I'll handle it\", so StationPlay won't ask Sonarr or Radarr to "
            "replace it",
            replacing.entry_label(entry),
        )
        return Response(status_code=204)

    # Sonarr and Radarr (optional: see replacing.py) ----------------------------

    async def arr_json() -> dict:
        return {
            "apps": replacing.shown(ctx.db),
            "what": replacing.what(ctx.db),
            "when": replacing.when(ctx.db),
            "status": ctx.arr_status,
        }

    @app.get("/api/arr")
    async def arr_settings():
        return await arr_json()

    @app.put("/api/arr")
    async def arr_save(body: ArrIn):
        try:
            replacing.save(ctx.db, body.app, body.url, body.key, body.on)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        log.info(
            "Replacing files with %s is %s",
            ARR_NAMES[body.app],
            "on" if replacing.enabled(ctx.db, body.app) else "off",
        )
        return await arr_json()

    @app.put("/api/arr/what")
    async def arr_what(body: ArrWhatIn):
        """What Sonarr and Radarr replace: broken or damaged files, missing
        ones, or both."""
        try:
            replacing.save_what(ctx.db, body.what)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        log.info("Sonarr and Radarr replace %s", {
            replacing.BOTH: "broken, damaged, and missing files",
            replacing.BROKEN: "broken and damaged files (not missing ones)",
            replacing.MISSING: "missing files (not broken or damaged ones)",
        }[body.what])  # fmt: skip
        return await arr_json()

    @app.put("/api/arr/when")
    async def arr_when(body: ArrWhenIn):
        """When Sonarr and Radarr replace: when you say so (Replace, on each
        entry), or by themselves."""
        try:
            replacing.save_when(ctx.db, body.when)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        log.info(
            "Sonarr and Radarr replace files %s",
            "only when you ask" if body.when == replacing.ASK else "automatically",
        )
        return await arr_json()

    @app.post("/api/arr/test")
    async def arr_test(body: ArrIn):
        """Whether StationPlay can reach Sonarr or Radarr with these (or the
        saved address and key)."""
        saved = replacing.settings(ctx.db)[body.app]
        try:
            url = clean_url(body.url or saved["url"])
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        key = (body.key or "").strip() or saved["key"]
        if not key:
            raise HTTPException(400, f"Enter {ARR_NAMES[body.app]}'s API key")
        try:
            got = await Arr(body.app, url, key, transport=ctx.arr_transport).status()
        except ArrError as e:
            raise HTTPException(400, str(e)) from None
        return {"name": ARR_NAMES[body.app], "version": str(got.get("version") or "")}

    # Stations kept from some Plex users (optional: see limits.py) ------------------

    async def limits_json() -> dict:
        out: dict[str, Any] = {"plexPass": None, "plexProblem": ""}
        accounts: list[dict[str, str]] = []
        try:
            accounts = await ctx.plex.accounts()
            out["plexPass"] = await ctx.plex.plex_pass()
        except PlexError as e:
            out["plexProblem"] = f"Couldn't get the list of users from Plex: {e}"
        lim = ctx.limits
        users = {a["id"]: a["name"] for a in accounts}
        for uid, name in lim.names.items():
            users.setdefault(uid, name or f"Plex user {uid}")
        out.update(
            on=lim.on,
            users=[
                {
                    "id": uid,
                    "name": name,
                    "owner": uid == "1",
                    "kept": sorted(lim.kept.get(uid, ())),
                }
                for uid, name in sorted(users.items(), key=lambda u: (u[0] != "1", u[1].casefold()))
            ],
            stations=[
                {"id": c.id, "number": c.number, "name": c.name} for c in ctx.db.list_channels()
            ],
            stops=list(reversed(lim.stops)),
            problem=lim.problem or ctx.who_watches.problem,
        )
        return out

    @app.get("/api/plex-limits")
    async def limits_get():
        return await limits_json()

    @app.put("/api/plex-limits")
    async def limits_save(body: LimitsIn):
        try:
            ctx.limits.save(body.on, body.kept, body.names)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        kept = ctx.limits.kept
        log.info(
            "Blocking stations for some Plex users is %s (%d user%s with blocked stations)",
            "on" if ctx.limits.on else "off",
            len(kept),
            "" if len(kept) == 1 else "s",
        )
        return await limits_json()

    # StationPlay's apps away from home (see away.py) ----------------------

    def away_json() -> dict:
        return {
            "on": ctx.away.on,
            "address": ctx.away.address,
            "publicPort": settings.public_port,
            "apps": ctx.away.apps,
        }

    @app.get("/api/away")
    async def away_get():
        return away_json()

    @app.put("/api/away")
    async def away_save(body: AwayIn):
        try:
            ctx.away.save(body.on, body.address)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        ctx.access.record(
            logging.INFO,
            f"Watching away from home in StationPlay's apps is on, at {ctx.away.address}"
            if ctx.away.on
            else "Watching away from home in StationPlay's apps is off",
        )
        return away_json()

    @app.get("/api/broken/download")
    async def broken_download():
        path = ctx.broken.path
        if not path.exists():
            return JSONResponse({"files": []})
        return FileResponse(path, filename="broken-files.json", media_type="application/json")

    # StationPlay's API (see api.py): what an Admin's token can have it do, as
    # the page does it.

    async def api_status() -> dict[str, Any]:
        return {
            "version": __version__,
            "plexConnected": bool((await plex_status(find_dvr=False))["ok"]),
            "tuners": playback.load(ctx.db).tuners,
            "playing": [
                {"number": s["number"], "viewers": s["viewers"]}
                for s in streams_now()
                if s["number"] is not None
            ],
        }

    async def api_update(channel_id: int, request: Request) -> bool:
        answer = await update_from_plex(channel_id, request)
        return bool(answer.get("changed"))

    async def api_backup() -> str:
        return (await backup_now())["name"]

    api.routes(
        app,
        ctx,
        api.Actions(
            status=api_status,
            update_station=api_update,
            check_station=lambda channel_id: jobs.start_check(ctx, channel_id).as_dict(),
            refresh_guide=after_change,
            backup=api_backup,
            asking_plex=[asking_plex],
        ),
    )

    return app


META_PLEX_LIBRARIES = "plex_libraries"


def remember_plex_libraries(ctx: AppContext) -> None:
    """Which library each station's show or movie was in, kept between
    restarts: if Plex adds one again under a new key, and more than one has
    its title, the station follows the one in that library (see
    PlexClient._show_or_movie)."""
    try:
        saved = json.loads(ctx.db.get_meta(META_PLEX_LIBRARIES, "") or "{}")
    except ValueError:
        saved = {}
    if isinstance(saved, dict):
        ctx.plex.libraries.update(
            {str(k): str(v) for k, v in saved.items() if isinstance(v, (str, int))}
        )

    def remember(libraries: dict[str, str]) -> None:
        ctx.db.set_meta(META_PLEX_LIBRARIES, json.dumps(libraries))

    ctx.plex.remember_libraries = remember
    ctx.plex.known_files = lambda key: known_files(ctx, key)


def known_files(ctx: AppContext, key: str) -> set[str]:
    """The names of the files stations have for a show (by its key) or a
    movie, casefolded: what tells apart shows or movies of one title when
    one's followed (see PlexClient._with_files)."""
    out: set[str] = set()
    for channel in ctx.db.list_channels():
        for item in ctx.db.all_programs(channel.id):
            if item.file_path and key in (item.show_key, item.rating_key):
                out.add(item.file_path.replace("\\", "/").rsplit("/", 1)[-1].casefold())
    return out


def give_logos_to_older_stations(ctx: AppContext) -> None:
    """Stations made before logos existed get one, once. (Choosing "Station
    number" for one afterwards sticks.)"""
    if ctx.db.get_meta("logos_given"):
        return
    taken = {c.logo for c in ctx.db.list_channels() if c.logo}
    for c in ctx.db.list_channels():
        if not c.logo:
            logo = ctx.logos.pick(taken, number=c.number)
            taken.add(logo)
            ctx.db.update_channel(c.id, logo=logo)
    ctx.db.set_meta("logos_given", "1")


def move_to_new_logos(ctx: AppContext) -> None:
    """Stations using a logo from the library before 1.7 (or from a backup
    made then) get the new logo that replaced it."""
    moved = 0
    for c in ctx.db.list_channels():
        new = ctx.logos.resolve(c.logo) if c.logo else ""
        if new != c.logo:
            ctx.db.update_channel(c.id, logo=new)
            moved += 1
    if moved:
        log.info(
            "Replaced old built-in logos with their new versions on %d station%s",
            moved,
            "" if moved == 1 else "s",
        )


def _plex_key(value: object) -> bool:
    """Whether `value` is one of Plex's keys (a number, as text or not)."""
    return isinstance(value, int | str) and not isinstance(value, bool) and str(value).isdigit()


def _feature_source_problem(source: dict) -> str | None:
    """Why a Feature Presentation's movies can't come from `source` (a movie
    library or collection), or None."""
    if source.get("type") == "section" and source.get("sectionType") == "movie":
        return _source_problem(source)
    if source.get("type") == "collection" and source.get("kind") == "movie":
        return _source_problem(source)
    return "Choose a movie library or movie collection for the Feature Presentation"


def _source_problem(source: dict) -> str | None:
    """Why a station source isn't valid, or None."""
    kind = source.get("type")
    if kind not in SOURCE_TYPES:
        return f"Unknown source type {kind!r}"
    # Plex's keys are numbers: anything else isn't from Plex.
    key = {"show": "ratingKey", "movie": "ratingKey", "section": "key"}.get(kind)
    if key and not _plex_key(source.get(key)):
        return f"A {kind} needs its Plex {key}"
    if kind == "collection":
        for field in ("ratingKey", "title", "library"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                return f"A collection needs its {field}"
        if not (_plex_key(source["ratingKey"]) and _plex_key(source["library"])):
            return "A collection needs its Plex ratingKey and library"
        if source.get("kind") not in COLLECTION_KINDS:
            return "A collection must hold movies, shows, seasons, or episodes"
        return None
    if kind != "filter":
        return None
    if source.get("kind") not in ("movie", "show"):
        return "A filter must be for movies or TV shows"
    libraries = source.get("libraries")
    if not isinstance(libraries, list) or not libraries or not all(map(_plex_key, libraries)):
        return "A filter needs at least one library"
    if len(set(map(str, libraries))) != len(libraries) or len(libraries) > LIBRARIES_MAX:
        return f"A filter can use up to {LIBRARIES_MAX} libraries, each only once"
    tags = source.get("tags") or {}
    if not isinstance(tags, dict):
        return "Filter tags must be {kind: [names]}"
    for tag, values in [*((t, source.get(t) or []) for t in TAG_FIELDS), *tags.items()]:
        if not str(tag).isalpha():
            return f"Unknown filter {tag!r}"
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            return f"Filter {tag} must be a list of names"
    days = source.get("addedWithinDays") or 0
    if not isinstance(days, int) or not 0 <= days <= 3650:
        return "Added within must be a number of days (up to 3650)"
    rating = source.get("minRating") or 0
    if not isinstance(rating, int | float) or not 0 <= rating <= 10:
        return "Minimum rating must be between 0 and 10"
    decades = source.get("decade") or []
    if not isinstance(decades, list) or not all(isinstance(d, int) for d in decades):
        return "Filter decades must be a list of years like 1950"
    if len(str(source.get("titleContains") or "")) > 100:
        return "Filter text is too long"
    left_out = source.get("exclude") or []
    if (
        not isinstance(left_out, list)
        or len(left_out) > FILTER_EXCLUDE_MAX
        or not all(isinstance(k, str) and k.isdigit() for k in left_out)
    ):
        return "A filter's left-out programs must be a list of Plex rating keys"
    return None


# What a Station ID card's preview says is up next, before a station has a
# schedule to say.
SAMPLE_UP_NEXT = ("UP NEXT", "Your Next Show", "Season 1, Episode 2 \u00b7 The Second Episode")
SAMPLE_FEATURE = ("", "A Movie from Your Library", "")


async def _run_to_end(args: list[str], what: str, timeout_s: float = 120) -> None:
    """Runs an ffmpeg for the editor (a preview) to the end, below the
    streams' priority, though not so low that a busy server starves it; an
    HTTP error saying `what` failed if it doesn't finish."""
    try:
        code, said = await run_to_end([*low_priority(nice=10, idle_io=False), *args], timeout_s)
    except TimeoutError:
        raise HTTPException(500, f"{what} took too long") from None
    if code != 0:
        log.warning("%s failed: %s", what, said)
        raise HTTPException(500, f"{what} couldn't be made. An Admin can see why on the Logs tab.")


def _numbered(name: str, n: int) -> str:
    """A station's name for the nth of several collections with the same
    name: Sunshine1, Sunshine2 (Top 10 (1), Top 10 (2) when the name ends
    in a number), cut short if need be to keep the number."""
    suffix = f" ({n})" if name[-1:].isdigit() else str(n)
    return name[: NAME_MAX - len(suffix)].rstrip() + suffix


def _mostly_one_show(counts: Counter[str]) -> bool:
    """Whether one show makes up so much of a station (programs per show in
    `counts`) that shuffle can't always keep it to two in a row (more than
    twice everything else)."""
    total = sum(counts.values())
    if len(counts) < 2:
        return total > 2
    biggest = max(counts.values())
    return biggest > 2 * (total - biggest)


def _item_json(item: Item) -> dict:
    return {
        "ratingKey": item.rating_key,
        "kind": item.kind,
        "title": item.title,
        "show": item.show_title,
        "season": item.season,
        "episode": item.episode,
        "year": item.year,
        "durationMs": item.duration_ms,
    }


async def render_icon(settings: Settings, text: str) -> bytes | None:
    """A simple number badge for the guide, drawn with ffmpeg."""
    args = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x1d2a36:s=256x256",
        "-vf",
        f"drawtext=text='{text}':fontcolor=white:fontsize={150 if len(text) < 3 else 100}"
        ":x=(w-text_w)/2:y=(h-text_h)/2",
        "-frames:v",
        "1",
        "-f",
        "image2",
        "-c:v",
        "png",
        "pipe:1",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(proc.communicate(), 15)
    except (TimeoutError, OSError):
        return None
    return out if proc.returncode == 0 and out else None


def data_dir_problem(data_dir: Path) -> str | None:
    """None if StationPlay can write to its data folder, otherwise what's
    wrong and how to fix it."""
    user = f"{os.getuid()}:{os.getgid()}"
    fix = (
        "To fix it, run this on the server, with the path of the folder mapped to "
        f"{data_dir}: sudo chown -R {user} <that folder>"
    )
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write-test"
        probe.write_text("ok\n")
        probe.unlink()
    except OSError as e:
        return f"StationPlay runs as user {user} and can't write to {data_dir} ({e.strerror or e}). {fix}"
    # (The reset-access file only has to exist: StationPlay deletes it, which
    # the folder's write test above already covers, whoever made it.)
    locked = [
        p.name
        for p in data_dir.iterdir()
        if p.is_file() and p.name != access.RESET_FILE and not os.access(p, os.W_OK)
    ]
    if locked:
        return (
            f"StationPlay runs as user {user} and can't change {', '.join(sorted(locked))}. {fix}"
        )
    return None


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    problem = data_dir_problem(settings.data_dir)
    if problem:
        log.error(problem)
        raise SystemExit(1)

    class Server(uvicorn.Server):
        def handle_exit(self, sig, frame) -> None:
            """On being told to stop: end every stream first. The server
            waits for open connections before it stops, and a stream never
            ends by itself."""

            def end_streams() -> None:
                for b in list(app.state.ctx.broadcasters.values()):
                    for viewer in list(b.viewers):
                        viewer.close("StationPlay is stopping")

            # This runs as a signal handler: do it from the event loop.
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().call_soon_threadsafe(end_streams)
            super().handle_exit(sig, frame)

    if settings.public_port and settings.public_port == settings.port:
        log.error("PUBLIC_PORT must differ from PORT (%d, the port Plex uses)", settings.port)
        raise SystemExit(1)
    app = create_app(settings)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.port,
        log_level="warning",
        timeout_keep_alive=30,
        # Never wait long for connections to finish when stopping.
        timeout_graceful_shutdown=5,
        # Requests' own addresses, never what an X-Forwarded-For header
        # says: wrong passwords are counted by address (see access.py).
        proxy_headers=False,
    )
    # With a public port, both from one StationPlay: which one a request came
    # in on is what tells it whether it's from the internet (see access.py).
    ports = [settings.port, *([settings.public_port] if settings.public_port else [])]
    try:
        sockets = [socket.create_server(("0.0.0.0", port)) for port in ports]
    except OSError as e:
        log.error("StationPlay can't listen on port %s: %s", " or ".join(map(str, ports)), e)
        raise SystemExit(1) from None
    if settings.public_port:
        log.info(
            "Also serving StationPlay's page on port %d for the internet (without the Plex "
            "tuner endpoints)",
            settings.public_port,
        )
    Server(config).run(sockets=sockets)


if __name__ == "__main__":
    main()
