"""How stations play: each one's picture size, how many can play at once
(its tuners), and how much the server can manage.

A station is one continuous stream in one fixed format, like a TV channel:
every program, commercial and card on it is converted to that format as it
plays (H.264 at the station's picture size, in standard colour, with stereo
sound: see ff.PICTURES), so each follows the last without a seam, in any
player. 4K and HDR programs play too, at the station's size, their HDR made
ordinary (ff.to_sdr).

What new stations start with: their picture size, and the other settings in
NEW_STATION_CHOICES, as chosen in the welcome (or db.NEW_STATION's).

Tuners: StationPlay plays at most `tuners` different stations at once,
across Plex and every other app, since each is converted as it plays;
everyone watching one station shares its stream. Plex is told of more
tuners than that (announced), since it may count each person watching a
station as one. So when all of StationPlay's are in use, someone tuning in
to another station gets StationPlay's own card saying so (busy_stream),
rather than Plex's error.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import ffmpeg as ff
from . import intro, subtitles, upnext
from .config import Settings
from .db import STATION_SETTINGS, Database

if TYPE_CHECKING:
    from .broadcaster import Broadcaster
    from .main import AppContext

log = logging.getLogger(__name__)

META_PICTURE = "default_picture"  # new stations' picture size
META_TUNERS = "tuners"
META_NEW_STATION = "new_station"  # what new stations start with, as chosen (JSON)
# The welcome that came before the setup (until 1.22.3): the version of it
# last seen, which the setup reads once, to know what's been answered (see
# setup.start). "1": 1.14's; "2": 1.15's, with what new stations start with,
# who can use StationPlay, and the overnight file checks; "3": with which
# corner.
META_WELCOMED = "welcomed"
WELCOME = "3"
# What new stations start with that's chosen here (besides the picture
# size), by their stored names (see db.STATION_SETTINGS), and the choices.
NEW_STATION_CHOICES: dict[str, tuple] = {
    "subtitles": subtitles.MODES,
    "breaks": (0, 1, 2, 3),
    "station_id": (False, True),
    "id_seconds": intro.ID_LENGTHS,
    "intro_seconds": intro.LENGTHS,
    "up_next_seconds": upnext.LENGTHS,
    "watermark": ff.WATERMARK_MODES,
    "watermark_position": ff.WATERMARK_POSITIONS,
}
TUNERS = 4  # unless set (or TUNER_COUNT said otherwise)
MOST_TUNERS = 20
BUSY_S = 30.0  # how long the "all tuners in use" card plays
BUSY_AT_ONCE = 3  # people shown it at once (more are turned away)
SPEED_TEST_S = 5.0  # of a 1080p picture, made into each size in turn
# Of what a speed test finds the server can do, how much stations should
# use (the rest: the GPU or CPU's other work, and harder files than the
# test's, such as 4K).
HEADROOM = 0.7


@dataclass
class Playback:
    picture: str  # new stations' picture size
    tuners: int
    # What else new stations start with, as chosen (stored names).
    new_station: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "picture": self.picture,
            "pictures": list(ff.PICTURES),
            "tuners": self.tuners,
            "mostTuners": MOST_TUNERS,
            "announced": announced(self.tuners),
            "newStation": {API_NAMES[k]: v for k, v in self.new_station.items()},
        }


# The settings' names on the page, by their stored names.
API_NAMES = {column: api for column, api, _ in STATION_SETTINGS if column in NEW_STATION_CHOICES}


def _allowed(column: str, value: Any) -> bool:
    """Whether `value` is one of the choices for `column` (True isn't 1)."""
    choices = NEW_STATION_CHOICES.get(column, ())
    return any(type(value) is type(c) and value == c for c in choices)


def new_station_from_page(given: dict[str, Any]) -> dict[str, Any]:
    """What new stations start with, by their page names, as stored names;
    ValueError if any isn't one of its choices."""
    columns = {api: column for column, api in API_NAMES.items()}
    out = {}
    for api, value in given.items():
        column = columns.get(api)
        if column is None:
            raise ValueError(f"{api!r} isn't a setting for new stations")
        if not _allowed(column, value):
            choices = ", ".join(map(str, NEW_STATION_CHOICES[column]))
            raise ValueError(f"{api} must be one of {choices}")
        out[column] = value
    return out


def load(db: Database) -> Playback:
    picture = db.get_meta(META_PICTURE, ff.STANDARD_PICTURE)
    try:
        tuners = int(db.get_meta(META_TUNERS, str(TUNERS)))
    except ValueError:
        tuners = TUNERS
    try:
        chosen = json.loads(db.get_meta(META_NEW_STATION, "{}") or "{}")
    except ValueError:
        chosen = {}
    return Playback(
        picture if picture in ff.PICTURES else ff.STANDARD_PICTURE,
        max(1, min(MOST_TUNERS, tuners)),
        {k: v for k, v in chosen.items() if _allowed(k, v)} if isinstance(chosen, dict) else {},
    )


def save(
    db: Database,
    picture: str | None = None,
    tuners: int | None = None,
    new_station: dict[str, Any] | None = None,
) -> Playback:
    """Saves what's given (new_station by stored names: see
    new_station_from_page)."""
    if picture is not None:
        if picture not in ff.PICTURES:
            raise ValueError(f"The picture size must be one of {', '.join(ff.PICTURES)}")
        db.set_meta(META_PICTURE, picture)
    if tuners is not None:
        if not 1 <= tuners <= MOST_TUNERS:
            raise ValueError(f"Tuners must be between 1 and {MOST_TUNERS}")
        db.set_meta(META_TUNERS, str(tuners))
    if new_station is not None:
        if not all(_allowed(k, v) for k, v in new_station.items()):
            raise ValueError("Those aren't valid choices for new stations")
        db.set_meta(META_NEW_STATION, json.dumps({**load(db).new_station, **new_station}))
    return load(db)


def start(db: Database, settings: Settings) -> None:
    """At startup: settings older versions took from the environment
    (TUNER_COUNT, VIDEO_HEIGHT) are where these start from, the first time;
    after that, the page's are what count."""
    if not db.get_meta(META_TUNERS, ""):
        db.set_meta(META_TUNERS, str(max(1, min(MOST_TUNERS, settings.tuner_count or TUNERS))))
    elif settings.tuner_count and str(settings.tuner_count) != db.get_meta(META_TUNERS):
        log.warning(
            "TUNER_COUNT (%d) is no longer used. Set the number of tuners on StationPlay's "
            "Add to Plex tab (currently %s).",
            settings.tuner_count,
            db.get_meta(META_TUNERS),
        )
    if not db.get_meta(META_PICTURE, ""):
        picture = settings.picture or ff.STANDARD_PICTURE
        db.set_meta(META_PICTURE, picture)
        if picture != ff.STANDARD_PICTURE:
            # The stations there were played this size before; they still do.
            db.set_every_picture(picture)
            log.info("Every station now plays at %s, as set by VIDEO_HEIGHT", picture)
    elif settings.picture:
        log.warning(
            "VIDEO_WIDTH, VIDEO_HEIGHT and VIDEO_BITRATE_KBPS are no longer used. Set each "
            "station's picture size in its editor."
        )


def announced(tuners: int) -> int:
    """How many tuners Plex is told of: more than StationPlay plays at once,
    so Plex lets it say when they're all in use (and in case Plex counts
    each person watching one station as a tuner)."""
    return max(tuners + 1, 2 * tuners)


def on_air(ctx: AppContext) -> list[int]:
    """The numbers of the stations someone is watching, in order."""
    numbers = []
    for channel_id, b in ctx.broadcasters.items():
        if b.viewers and (channel := ctx.db.get_channel(channel_id)) is not None:
            numbers.append(channel.number)
    return sorted(numbers)


def all_in_use(ctx: AppContext, b: Broadcaster) -> list[int] | None:
    """If tuning in to `b`'s station would be one station too many: the
    stations on now. None if it can play (it's on already, or a tuner's
    free)."""
    if b.viewers:
        return None
    numbers = on_air(ctx)
    return numbers if len(numbers) >= load(ctx.db).tuners else None


def make_room(ctx: AppContext, b: Broadcaster) -> None:
    """Before `b`'s station starts: stations kept running only so flipping
    back to them is instant (nobody's watching them) stop now, if they'd
    make more stations running than there are tuners."""
    if b.running:
        return
    idle = [x for x in ctx.broadcasters.values() if x is not b and x.running and not x.viewers]
    if idle and len(on_air(ctx)) + len(idle) >= load(ctx.db).tuners:
        for x in idle:
            task = asyncio.create_task(x.stop("another station needed its tuner"))
            _stopping.add(task)
            task.add_done_callback(_stopping.discard)


_stopping: set[asyncio.Task] = set()  # (kept until done)


def busy_lines(tuners: int, numbers: list[int]) -> list[str]:
    """What the "all tuners in use" card says."""
    if len(numbers) == 1:
        on = f"Station {numbers[0]}"
    else:
        on = f"Stations {', '.join(map(str, numbers[:-1]))} and {numbers[-1]}"
    return [
        "All tuners in use",
        f"StationPlay can play only {tuners} {'station' if tuners == 1 else 'stations'} at a time",
        f"On now: {on}. Try again soon, or ask whoever runs StationPlay to add more tuners.",
    ]


async def busy_stream(
    settings: Settings, logo: Path | None, name: str, lines: list[str]
) -> AsyncGenerator[bytes, None]:
    """The "all tuners in use" card, as a stream BUSY_S long (drawn on the
    CPU: it takes little)."""
    args = ff.card_command(settings, BUSY_S, 10.0, 2.0, name, str(logo) if logo else None, lines)
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    try:
        while chunk := await proc.stdout.read(64 * 1024):
            yield chunk
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        await proc.wait()


# Speed test ---------------------------------------------------------------


async def speed_test(ctx: AppContext) -> dict:
    """How many stations the server could play at once at each picture
    size, roughly: a few seconds of an ordinary 1080p program made into each
    size the way a station plays it (on the GPU, if one is in use), as fast
    as it can be, at a low priority so stations playing now aren't held up.
    {"480p": {"speed": 4.2, "stations": 2}, ...}, and what was used."""
    settings = ctx.settings
    folder = settings.data_dir / "speedtest"
    clip = folder / "1080p.mkv"
    if not clip.is_file():
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        made = folder / ".1080p.mkv"
        code, said = await ff.run_to_end(
            [
                *ff.low_priority(idle_io=False), settings.ffmpeg_path, "-hide_banner",
                "-nostdin", "-v", "error", "-y",
                "-f", "lavfi", "-i", f"testsrc2=s=1920x1080:r=24000/1001:d={SPEED_TEST_S}",
                "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", f"{SPEED_TEST_S}",
                "-c:v", "libx264", "-preset", "veryfast", "-b:v", "8M", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(made),
            ],
            120,
        )  # fmt: skip
        if code != 0:
            raise RuntimeError(f"couldn't make the test video ({said[-200:]})")
        await asyncio.to_thread(made.rename, clip)
    encoder = ctx.gpu.encoder_for(False) if ctx.gpu else ff.CPU
    playing = len(on_air(ctx))
    results: dict[str, dict] = {}
    for picture in ff.PICTURES:
        args = ff.program_command(
            ff.sized(settings, picture), str(clip), 0.0, SPEED_TEST_S, 10.0, 1000.0, 0,
            "Speed test", encoder,
        )  # fmt: skip
        started = time.monotonic()
        code, said = await ff.run_to_end([*ff.low_priority(idle_io=False), *args], 120)
        took = time.monotonic() - started
        if code != 0:
            raise RuntimeError(f"the {picture} test failed ({ff.redact(said)[-200:]})")
        speed = SPEED_TEST_S / max(took, 0.01)
        results[picture] = {
            "speed": round(speed, 1),
            "stations": max(0, min(MOST_TUNERS, math.floor(speed * HEADROOM))),
        }
    log.info(
        "Speed test on the %s%s. Stations this server can play at once: %s",
        encoder.label,
        f", with {playing} {'station' if playing == 1 else 'stations'} already playing"
        if playing
        else "",
        ", ".join(f"about {r['stations']} at {p}" for p, r in results.items()),
    )
    return {"pictures": results, "encoder": encoder.label, "playing": playing}
