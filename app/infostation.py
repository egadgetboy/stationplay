"""The INFO station (1.34.1, the owner): station 99, on every new tapiOca.

Plex's Live TV & DVR won't take a tuner whose guide has no stations, and a
new tapiOca had none until someone made one: so setup couldn't get tapiOca
into Plex. A new tapiOca now starts with station 99, INFO, with tapiOca's
mark as its logo, playing a film made for it (pearls flying through the
ring of tapiOca's logo, to a light tune; tools/info makes it, and it's in
the image, so it plays without Plex). Over it, as it plays (see
ffmpeg.info_text): the time and date, and a panel that changes every 15
seconds, each in turn:

  * What's new in tapiOca: this version's highlights (assets/info/news.json,
    written with each release). Never the server's state, such as a newer
    version being out: that's for Admins, on the page;
  * tapiOca's apps, in beta: their newest versions, and what's new in them
    (bundled with each release, in assets/info/apps.json);
  * By the numbers: stations (INFO aside), and the movies, shows and
    episodes in the Media folders shared with tapiOca's apps, and how many
    were added this week (counts only, never titles: everyone sees INFO,
    whatever their Viewing Level, in Plex too);
  * A tip for tapiOca's apps, a new one each hour.

Nothing on it costs an outside request: it's what tapiOca knows already,
and Plex's counts, asked once an hour. The pearls fly over all of it (the
film's second video stream is where they are in front: see
ffmpeg.info_pearls).

INFO is always station 99 (the owner): it can be renamed, and its settings
changed, but not renumbered, and no other station can be 99. A tapiOca
whose station 99 is another one gets INFO only once that one moves. It's made once, on a new
tapiOca's first start; deleted, it stays deleted until an Admin brings it
back (Add the INFO station, on the Setup tab). An update never adds
it by itself. What it plays comes from no library: its one source is
{"type": "info"}, and its one program has the key KEY, which the library
answers for itself (see library.py).

Setup counts stations without it: a tapiOca with only INFO is still new.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import __version__
from .catalog import Media, Track
from .db import Item

if TYPE_CHECKING:
    from .db import Channel, Database
    from .main import AppContext

log = logging.getLogger(__name__)

FOLDER = Path(__file__).parent / "assets" / "info"
FILE = FOLDER / "tapioca-info.mp4"
LOGO = "tapioca"  # its logo, as the logo library knows it (see logos.py)
LOGO_FILE = FOLDER / "logo.png"
APPS_FILE = FOLDER / "apps.json"
NEWS_FILE = FOLDER / "news.json"  # what's new in this version (see highlights)
# Its one program's key: a folder library's shape (see library.py), with a
# number no folder library is given, so no library is ever asked about it.
KEY = "f0"
TITLE = "tapiOca INFO"
SOURCE: dict[str, Any] = {"type": "info", "title": TITLE}
META = "info_station"  # the INFO station's id, once it's been made
NUMBER = 99
NAME = "INFO"
DESCRIPTION = "The date and time, what's new in tapiOca, and tips for watching."
SUMMARY = (
    "The date and time, what's new in tapiOca and its apps, your stations and Media by the "
    "numbers, and tips for watching."
)
# The film's length (tools/info/render.py: 4 loops of 30 seconds), and what
# it holds: a test keeps these the same as the file. Its second video
# stream is the pearls in front (see ffmpeg.info_pearls).
LENGTH_MS = 120_000
WIDTH, HEIGHT = 1280, 720
# What INFO starts with: nothing between programs or over them, so the film
# plays as it is, with what's drawn over it.
SETTINGS: dict[str, Any] = {
    "order_mode": "shuffle",
    "breaks": 0,
    "station_id": False,
    "intro_seconds": 0,
    "up_next_seconds": 0,
    "watermark": "off",
    "skip_intros": False,
    "subtitles": "off",
    "marathon_mode": "off",
    "feature_mode": "off",
    "description": DESCRIPTION,
}
NOT_ITS_NUMBER = "INFO is always station 99"
TAKEN = "Station 99 is kept for INFO"
NOT_ITS_SOURCE = "INFO always plays its own film"
ONLY_ON_INFO = "INFO's film plays only on INFO"
ONLY_ITS_FILM = "INFO plays only its own film: no blocks, Feature Presentation or marathons"

# The panels: each shows for PANEL_S seconds, in turn (fading in and out
# over FADE_S), so they come round every CYCLE_S seconds, by the time each
# frame airs (so a program starting, or someone tuning in, never moves
# them on or holds them back).
PANELS = 4
PANEL_S = 15.0  # (the owner: 5 seconds longer than the first 10)
FADE_S = 0.8
CYCLE_S = PANELS * PANEL_S
LINE_MOST = 62  # characters a line, about (the panel's width)
LINES_MOST = 4
COUNT_EVERY_S = 3600.0  # Plex's counts, asked this often
WRITE_EVERY_S = 300.0  # the panels, written again this often (or when asked)
TIPS = (
    "Type a station's number to jump straight to it.",
    "Press OK, or Select, to see what's on now and next.",
    "The guide shows what's on every station, hours ahead.",
    "Media has your movies and shows, to watch whenever you like.",
    "Resume picks up where you left off, on any of your devices.",
    "CC turns subtitles on or off, for the station you're watching.",
    "Each person's Resume row and Watched marks are their own.",
    "A station plays like TV: tune in, and it's already on.",
    "Back takes you to the last station you watched.",
    "The Sleep timer turns the TV off for you, when you choose.",
)


def is_info_source(source: dict[str, Any]) -> bool:
    return source.get("type") == "info"


def is_info(channel: Channel) -> bool:
    """Whether a station is INFO (it plays INFO's film, and nothing else)."""
    return bool(channel.sources) and all(is_info_source(s) for s in channel.sources)


def others(channels: list[Channel]) -> int:
    """How many stations there are besides INFO (what setup counts: one with
    only INFO is new)."""
    return sum(1 for c in channels if not is_info(c))


def program() -> Item:
    """INFO's one program."""
    return Item(
        0, 0, LENGTH_MS, KEY, "movie", TITLE, summary=SUMMARY, year=2026,
        file_path=str(FILE), rating="G",
    )  # fmt: skip


def media() -> Media:
    """Its file, as a library would describe it."""
    return Media(
        container="mp4",
        video="h264",
        width=WIDTH,
        height=HEIGHT,
        file=str(FILE),
        size=FILE.stat().st_size if FILE.is_file() else None,
        duration_ms=LENGTH_MS,
        id=KEY,
        audio=(Track(id="1", codec="aac", language="", title="", channels=2, default=True),),
    )


def wanted(db: Database, new: bool) -> bool:
    """Whether to make INFO now, by itself: a new tapiOca (`new`: nothing set
    up yet, no stations) whose image has the film, that hasn't had it."""
    return new and not db.get_meta(META) and not db.list_channels() and FILE.is_file()


def made(db: Database, channel_id: int) -> None:
    db.set_meta(META, str(channel_id))
    log.info("Made the INFO station, station 99")


def find(channels: list[Channel]) -> Channel | None:
    return next((c for c in channels if is_info(c)), None)


def number_problem(
    channel: Channel | None, number: int, sources: list[dict[str, Any]]
) -> str | None:
    """Why a station can't have this number and these sources (`channel`:
    the station as it is, or None for a new one); None if it can."""
    info_now = channel is not None and is_info(channel)
    info_after = bool(sources) and all(is_info_source(s) for s in sources)
    if not info_after and any(is_info_source(s) for s in sources):
        return ONLY_ON_INFO  # (beside other sources)
    if info_now and not info_after:
        return NOT_ITS_SOURCE
    if info_now and number != NUMBER:
        return NOT_ITS_NUMBER
    # (A station that was 99 before INFO was keeps it till it's moved.)
    kept = channel is not None and channel.number == NUMBER
    if number == NUMBER and not info_now and not kept:
        return TAKEN
    if info_after and not info_now:
        return NOT_ITS_SOURCE  # (made only as INFO itself: see Add the INFO station)
    return None


# The panels ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Panel:
    title: str
    body: str


def wrap(text: str, most: int = LINE_MOST) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > most:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


def _lines(items: list[str], most: int = LINES_MOST) -> str:
    out: list[str] = []
    for item in items:
        wrapped = wrap(item)
        if len(out) + len(wrapped) > most:
            break
        out.extend(wrapped)
    return "\n".join(out)


def highlights(path: Path | None = None) -> list[str]:
    """What's new in this version, in a few words each (assets/info/news.json,
    written with each release's notes: a test keeps it this version's)."""
    try:
        got = json.loads((path or NEWS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(got, dict) or got.get("version") != __version__:
        return []
    return [str(h) for h in got.get("new") or [] if isinstance(h, str) and h.strip()]


def apps(path: Path = APPS_FILE) -> list[dict[str, Any]]:
    """The newest tapiOca apps, as this release knows them: [{"name",
    "version", "new"}]."""
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [a for a in got if isinstance(a, dict) and a.get("name") and a.get("version")]


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


@dataclass
class Counts:
    stations: int = 0
    movies: int | None = None
    shows: int | None = None
    episodes: int | None = None
    this_week: int | None = None


def panels(counts: Counts, hour: int) -> list[Panel]:
    """The four panels, as they read now."""
    new = highlights()
    whats_new = [f"• {h}" for h in new[:3]] or ["• Small fixes and improvements"]
    app_lines = [
        f"{a['name']} {a['version']}: {a['new']}" if a.get("new") else f"{a['name']} {a['version']}"
        for a in apps()
    ]
    # (None of a kind is left out: a new tapiOca's reads as what to do.)
    numbers = [
        _count(n, one)
        for n, one in (
            (counts.stations, "station"), (counts.movies, "movie"),
            (counts.shows, "show"), (counts.episodes, "episode"),
        )
        if n
    ]  # fmt: skip
    by_numbers = [" · ".join(numbers[:2]), " · ".join(numbers[2:])]
    if not numbers:
        by_numbers = ["Make your first station on tapiOca's page."]
    if counts.this_week:
        by_numbers.append(
            f"{_count(counts.this_week, 'new movie or episode', 'new movies and episodes')} this week"
        )
    return [
        Panel(f"What's new in tapiOca {__version__}", _lines(whats_new)),
        Panel(
            "tapiOca's apps, in beta",
            _lines(app_lines) or "Coming to Android, Apple devices and Roku.",
        ),
        Panel("By the numbers", _lines([n for n in by_numbers if n])),
        Panel("A tip for tapiOca's apps", _lines([TIPS[hour % len(TIPS)]])),
    ]


def files(folder: Path) -> list[tuple[Path, Path]]:
    """Where each panel's title and body are kept, for drawing (see
    ffmpeg.info_text)."""
    return [
        (folder / f"panel-{n}-title.txt", folder / f"panel-{n}-body.txt") for n in range(PANELS)
    ]


def lines(body: Path) -> int:
    """How many lines a panel's body has, as written (see files): its place
    on the screen depends on it, so its last line is at the bottom margin."""
    try:
        return min(max(len(body.read_text(encoding="utf-8").splitlines()), 1), LINES_MOST)
    except OSError:
        return 1


def _put(path: Path, text: str) -> None:
    """Written whole, then put in place, so the drawing never reads half."""
    text = text.replace("'", "’")
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    spare = path.with_suffix(".new")
    spare.write_text(text, encoding="utf-8")
    os.replace(spare, path)


def write(folder: Path, shown: list[Panel]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for (title, body), panel in zip(files(folder), shown, strict=True):
        _put(title, panel.title)
        _put(body, panel.body or " ")


class Panels:
    """Keeps INFO's panels written, while there's an INFO station."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.folder = ctx.settings.data_dir / "info"
        self.counts = Counts()
        self._counted = -COUNT_EVERY_S
        self._counted_for: tuple[str, ...] | None = None
        self.wake = asyncio.Event()

    async def count(self) -> None:
        """The library's counts (once an hour at most, or when what's shared
        changes): what the Media folders shared with tapiOca's apps have,
        and what they added in the last week. None shared: none counted."""
        shared = self.ctx.shared
        keys = None if shared.everything else tuple(shared.keys)  # (None: every one)
        if keys == self._counted_for and time.monotonic() - self._counted < COUNT_EVERY_S:
            return
        if keys != self._counted_for:
            # (What was counted for other Media folders is never shown for
            # these: the second audit.)
            self.counts.movies = self.counts.shows = self.counts.episodes = None
            self.counts.this_week = None
        self._counted = time.monotonic()
        if keys == ():
            self._counted_for = keys
            return
        try:
            got = await asyncio.wait_for(self.ctx.library.counts(keys), 60)
        except Exception as e:  # (counts are a nicety: never more than a log line)
            log.info("Couldn't count what's in Plex for INFO now (%s)", e)
            return
        self.counts.movies, self.counts.shows, self.counts.episodes, self.counts.this_week = got
        self._counted_for = keys

    def ensure(self) -> None:
        """The panels written, if they aren't yet (they're drawn from these
        files: one missing would stop the picture)."""
        if not all(t.is_file() and b.is_file() for t, b in files(self.folder)):
            self.write_now()

    def write_now(self) -> None:
        self.counts.stations = others(self.ctx.db.list_channels())
        write(self.folder, panels(self.counts, int(time.time() // 3600)))

    async def run_forever(self) -> None:
        while True:
            try:
                if find(self.ctx.db.list_channels()) is not None:
                    await self.count()
                    # (On the event loop, not a thread: it's a few small files,
                    # and a thread could still be at the database as tapiOca
                    # stops and closes it.)
                    self.write_now()
            except Exception:
                log.exception("Couldn't write INFO's panels")
            self.wake.clear()
            # (Each hour for the tip, at least.)
            wait = min(WRITE_EVERY_S, 3600 - time.time() % 3600 + 1)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), wait)
