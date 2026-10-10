"""The Intro Bumper and the Station ID card: animated cards about a station.

The Intro Bumper plays when someone tunes in. It shows the station's logo,
"You're tuning in to", its name, its description and what's on, for 3, 5,
10 or 15 seconds, over the sound of an old TV's dial being flipped (static,
the knob clicking, snippets of other shows) to make people look up and read
it. The show keeps its place on the schedule underneath, so the guide stays
right: the viewer joins it that many seconds in.

The Station ID card plays between programs (after any commercials): the
same look, with the station's logo and name and what's up next, for 3, 5
or 10 seconds, over a short jingle.

The sounds are made in advance (tools/bumper/sound.py and jingles.py),
several versions of each, one picked at random each time. A card is drawn
when it's needed, once, as three still pictures (the station alone, then
with its name, then with everything); the moving part only wipes between
them, moves the logo, and (for the Intro Bumper) adds a light layer of
static that flickers when the knob clicks, so it's lighter work than
playing a program.
"""

from __future__ import annotations

import asyncio
import colorsys
import contextlib
import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from . import ffmpeg as ff
from .markers import across, pieces
from .sources import part_starts

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import Settings
    from .db import Item
    from .main import AppContext
    from .schedule import StationSchedule

LENGTHS = (0, 3, 5, 10, 15)  # the Intro Bumper's, in seconds; 0 is off
ID_LENGTHS = (3, 5, 10)  # the Station ID card's, in seconds
DESCRIPTION_MAX = 140
ASSETS = Path(__file__).resolve().parent / "assets"
FONTS = ASSETS / "fonts"
SOUNDS = ASSETS / "bumper"
LANDING = SOUNDS / "landing.m4a"
JINGLES = ASSETS / "ident"
BOLD = FONTS / "Montserrat-ExtraBold.ttf"
SEMI = FONTS / "Montserrat-SemiBold.ttf"
MEDIUM = FONTS / "Montserrat-Medium.ttf"
FPS = f"{ff.FPS_NUM}/{ff.FPS_DEN}"
# Without a logo to take colours from: deep blue, with teal.
PLAIN_COLOURS = ("0A1426", "1A2C4E", "4CCFBF")


# The pictures a card is drawn as (the last two only with a logo).
PICTURES = ("base", "title", "full", "logo", "shine")
INTRO: Final = "intro"  # the Intro Bumper
IDENT: Final = "id"  # the Station ID card
FEATURE: Final = "feature"  # the Feature Presentation card (see specials.py)


@dataclass(frozen=True)
class Card:
    """What a card says."""

    name: str
    number: int
    description: str = ""
    logo: str | None = None
    # What's on: a heading ("NOW PLAYING", "UP NEXT"), the show or movie,
    # and the episode or year. Empty if it isn't known.
    now: tuple[str, str, str] = ("", "", "")
    kind: str = INTRO  # or IDENT or FEATURE


@dataclass(frozen=True)
class Sound:
    path: Path
    clicks: tuple[float, ...]  # when the knob clicks over
    static: tuple[tuple[float, float], ...]  # stretches of plain static


# ------------------------------------------------------------------ sounds


def _dial() -> dict[str, list[dict]]:
    try:
        return json.loads((SOUNDS / "dial.json").read_text())
    except (OSError, ValueError):
        return {}


_DIAL = _dial()


def sounds(length: int) -> list[Sound]:
    """The versions of the sound for `length` seconds."""
    out = []
    for v in _DIAL.get(str(length), []):
        path = SOUNDS / v["file"]
        if not path.is_file():
            continue
        stops = v["stops"]
        ends = [s[0] for s in stops[1:]] + [float(length)]
        static = tuple(
            (float(at), float(end))
            for (at, what), end in zip(stops, ends, strict=True)
            if what == "static"
        )
        out.append(Sound(path, tuple(float(c) for c in v["clicks"]), static))
    return out


def sound(length: int, rng: random.Random | None = None) -> Sound | None:
    """One of the sounds for `length` seconds, picked at random."""
    choices = sounds(length)
    return (rng or random).choice(choices) if choices else None


def jingles() -> list[Path]:
    """The Station ID card's jingles (each fades out in time for the card)."""
    return sorted(JINGLES.glob("jingle-*.m4a"))


def jingle(rng: random.Random | None = None) -> Path | None:
    """One of the jingles, picked at random."""
    choices = jingles()
    return (rng or random).choice(choices) if choices else None


# ------------------------------------------------------------------ colours


def palette(rgba: bytes) -> tuple[str, str, str]:
    """(dark background, lighter background, accent) as hex, from a logo's
    pixels. The background takes the logo's main colour that darkens well
    (not yellows and oranges, which turn olive and brown); the accent is its
    liveliest bright colour, a different hue if it has one."""
    counts: dict[tuple[int, int, int], int] = {}
    for i in range(0, len(rgba) - 3, 4):
        if rgba[i + 3] >= 200:
            key = (rgba[i] // 20, rgba[i + 1] // 20, rgba[i + 2] // 20)
            counts[key] = counts.get(key, 0) + 1
    cands = []
    for (r, g, b), n in counts.items():
        hue, light, sat = colorsys.rgb_to_hls(
            (r * 20 + 10) / 255, (g * 20 + 10) / 255, (b * 20 + 10) / 255
        )
        cands.append((hue, light, sat, n))
    if not cands:
        return PLAIN_COLOURS

    def warm(h: float) -> bool:
        return 0.06 < h < 0.2

    bgs = [c for c in cands if c[2] > 0.22 and 0.08 < c[1] < 0.75 and not warm(c[0])]
    bg = max(bgs, key=lambda c: c[3] * (0.4 + c[2])) if bgs else (0.6, 0.3, 0.3, 0)

    def lively(c: tuple[float, float, float, int]) -> float:
        apart = min(abs(c[0] - bg[0]), 1 - abs(c[0] - bg[0]))
        return c[3] * c[2] * (1.8 if apart > 0.08 else 1.0)

    accs = [c for c in cands if c[2] > 0.4 and 0.35 < c[1] < 0.85]
    acc = max(accs, key=lively) if accs else (bg[0], 0.65, 0.5, 0)

    def hexc(hue: float, light: float, sat: float) -> str:
        r, g, b = colorsys.hls_to_rgb(hue, light, sat)
        return f"{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"

    return (
        hexc(bg[0], 0.085, min(0.75, bg[2] * 0.9 + 0.1)),
        hexc((bg[0] + 0.02) % 1, 0.2, min(0.7, bg[2] * 0.8 + 0.1)),
        hexc(acc[0], min(0.7, max(0.58, acc[1])), max(0.55, min(0.95, acc[2]))),
    )


# Each logo's colours, by its file (its path, and when it last changed):
# worked out once, rather than for every card.
_COLOURS: dict[tuple[str, int, int], tuple[str, str, str]] = {}
_COLOURS_KEPT = 512


async def colours(settings: Settings, logo: str | None) -> tuple[str, str, str]:
    """The card's colours, from its logo (read small by ffmpeg)."""
    if not ff.usable_picture(logo):
        return PLAIN_COLOURS
    try:
        stat = await asyncio.to_thread(os.stat, str(logo))
    except OSError:
        return PLAIN_COLOURS
    key = (str(logo), stat.st_mtime_ns, stat.st_size)
    if key in _COLOURS:
        return _COLOURS[key]
    size = 48
    try:
        proc = await asyncio.create_subprocess_exec(
            settings.ffmpeg_path, "-hide_banner", "-nostdin", "-loglevel", "error",
            "-i", str(logo), "-frames:v", "1",
            "-vf", f"scale={size}:{size}:flags=area,format=rgba", "-f", "rawvideo", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )  # fmt: skip
    except OSError:
        return PLAIN_COLOURS
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 10)
    except TimeoutError:
        return PLAIN_COLOURS
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
    if len(out) != size * size * 4:
        return PLAIN_COLOURS
    if len(_COLOURS) >= _COLOURS_KEPT:
        _COLOURS.clear()
    _COLOURS[key] = palette(out)
    return _COLOURS[key]


def whats_on(station, at_ms: int) -> tuple[tuple[str, str, str], str | None]:
    """What the card says is on at `at_ms` on a station's schedule (or up
    next, if that's a break): (heading, show or movie, episode or year), and
    the program's rating key."""
    slot = station.locate(at_ms)
    heading = "NOW PLAYING"
    if slot is not None and at_ms >= slot.start_ms + slot.item.program_end_ms:
        slot, heading = station.locate(slot.end_ms), "UP NEXT"
    if slot is None:
        return ("", "", ""), None
    return (heading, *describe(slot.item)), slot.item.rating_key


def describe(item: Item) -> tuple[str, str]:
    """A program as a card shows it: the show and the episode (its season,
    number and title), or the movie and its year."""
    if item.kind == "episode" and item.show_title:
        detail = item.title
        if item.season is not None and item.episode is not None:
            detail = f"Season {item.season}, Episode {item.episode} \u00b7 {item.title}"
        return item.show_title, detail
    return item.title, str(item.year or "")


# ------------------------------------------------------------ fitting text


def _widths() -> dict[str, dict]:
    try:
        return json.loads((FONTS / "widths.json").read_text())
    except (OSError, ValueError):
        return {}


_WIDTHS = _widths()
_FONT_KEYS = {BOLD: "ExtraBold", SEMI: "SemiBold", MEDIUM: "Medium"}


def text_width(text: str, font: Path, size: float) -> float:
    table = _WIDTHS.get(_FONT_KEYS.get(font, ""), {})
    widths, other = table.get("widths", {}), table.get("other", 700)
    return size * sum(widths.get(c, other) for c in text) / 1000


def fit(
    text: str, font: Path, room: float, largest: int, smallest: int, most: int
) -> tuple[list[str], int]:
    """`text` as at most `most` lines no wider than `room`, at the largest
    size that fits; if even the smallest won't, the last line is cut short."""
    words = " ".join(text.split()).split(" ")
    if not text.strip():
        return [], smallest
    for size in range(largest, smallest - 1, -1):
        lines: list[str] = []
        for word in words:
            if lines and text_width(f"{lines[-1]} {word}", font, size) <= room:
                lines[-1] += f" {word}"
            else:
                lines.append(word)
        if len(lines) <= most and all(text_width(x, font, size) <= room for x in lines):
            return lines, size
    # Even the smallest size won't do: what's left over goes on the last
    # line, and any line too wide is cut short with an ellipsis.
    kept = lines[:most]
    overflow = len(lines) > most
    if overflow:
        kept[-1] = " ".join(lines[most - 1 :])
    out = []
    for i, line in enumerate(kept):
        if (overflow and i == len(kept) - 1) or text_width(line, font, smallest) > room:
            while line and text_width(line + "…", font, smallest) > room:
                line = line[:-1].rstrip()
            line += "…"
        out.append(line)
    return out, smallest


def fit_tidy(
    text: str, font: Path, room: float, largest: int, smallest: int, most: int
) -> tuple[list[str], int]:
    """Like fit, but one line if it fits at three quarters of the largest
    size or more: a short title reads better on one line than two."""
    one = " ".join(text.split())
    for size in range(largest, max(smallest, largest * 3 // 4) - 1, -1):
        if one and text_width(one, font, size) <= room:
            return [one], size
    return fit(text, font, room, largest, smallest, most)


# ------------------------------------------------------------- the card


def drawtext(text: str, font: Path, size: int, colour: str, x: int, y: int, extra: str = "") -> str:
    return (
        f"drawtext=fontfile='{font}':text='{ff.escape_text(text)}':expansion=none"
        f":fontsize={size}:fontcolor=0x{colour}:x={x}:y={y}{extra}"
    )


def _logo_place(settings: Settings) -> tuple[int, int, int]:
    """Where the logo goes: its centre (x, y) and its size (a square)."""
    w, h = settings.video_width, settings.video_height
    return round(w * 0.258), round(h * 0.467), round(380 * h / 720) // 2 * 2


def stills_command(
    settings: Settings, card: Card, palette_: tuple[str, str, str], folder: Path
) -> list[str]:
    """ffmpeg arguments that draw the card as pictures in `folder`: base.png
    (the background), title.png (with the station's name) and full.png (with
    everything), and for the logo, which moves: logo.png, and shine.png (a
    band of light that sweeps across it). Laid out for 1280x720 and scaled
    to the stream's size."""
    w, h = settings.video_width, settings.video_height
    k = h / 720

    def s(v: float) -> int:
        return round(v * k)

    dark, light, accent = palette_
    logo = ff.usable_picture(card.logo)
    lx, ly, ls = _logo_place(settings)
    tx = round(w * 0.461) if logo else round(w * 0.09)
    room = (w - tx - round(w * 0.06)) * 0.97
    # (A gradient's points must be inside the picture: ffmpeg picks one at
    # random for any that isn't, and every card would look different.)
    g = [
        f"gradients=s={w}x{h}:r={FPS}:c0=0x{dark}:c1=0x{light}:c2=0x{dark}:nb_colors=3"
        f":x0=0:y0=0:x1={w - 1}:y1={h - 1}:type=linear:speed=0.00001,format=rgba[bg]",
        f"gradients=s={s(820)}x{s(820)}:r={FPS}:c0=0x{accent}50:c1=0x{accent}00:nb_colors=2"
        f":type=radial:x0={s(410)}:y0={s(410)}:x1={s(410)}:y1=0:speed=0.00001,format=rgba[glow]",
        f"[bg][glow]overlay=x={lx - s(410)}:y={ly - s(410)}:format=auto[b1]",
        # the channel number, huge and faint, bottom right
        f"[b1]drawtext=fontfile='{BOLD}':text='{card.number}':expansion=none:fontsize={s(560)}"
        f":fontcolor=0xFFFFFF@0.05:x=w-text_w+{s(40)}:y=h-text_h+{s(10)}[b2]",
    ]
    if logo:
        g.append(
            f"movie='{logo}',scale={ls}:{ls}:force_original_aspect_ratio=decrease,format=rgba,"
            f"pad={ls}:{ls}:(ow-iw)/2:(oh-ih)/2:color=black@0[logo]"
        )
        # A soft diagonal band of light in the middle of a strip five logos
        # wide: sliding a logo-sized window along it sweeps the band across,
        # and parked at the strip's start the window is well clear of it.
        g.append(
            f"gradients=s={5 * ls}x{ls}:r={FPS}:c0=0xFFFFFF00:c1=0xFFFFFFA0:c2=0xFFFFFF00"
            f":nb_colors=3:type=linear:x0={round(2.34 * ls)}:y0={round(0.35 * ls)}"
            f":x1={round(2.66 * ls)}:y1={round(0.65 * ls)}:speed=0.00001,format=rgba[shine]"
        )
    g.append(
        f"[b2]drawgrid=w=iw:h={max(2, s(3))}:t=1:c=black@0.12,vignette=angle=0.28,"
        "format=rgb24,split[base][b4]"
    )
    if card.kind in (IDENT, FEATURE):
        words = "NOW SHOWING" if card.kind == FEATURE else "YOU\u2019RE WATCHING"
        title, rest = _ident_text(card, accent, tx, room, ly, s, words)
    else:
        title, rest = _intro_text(card, accent, tx, room, s)
    g.append("[b4]" + ",".join(title) + ",split[title][b5]")
    g.append("[b5]" + (",".join(rest) if rest else "null") + "[full]")
    args = [
        settings.ffmpeg_path, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-filter_complex", ";".join(g),
    ]  # fmt: skip
    for name in PICTURES if logo else PICTURES[:3]:
        args += ["-map", f"[{name}]", "-frames:v", "1", "-update", "1", str(folder / f"{name}.png")]
    return args


_SHADOW = ":shadowcolor=0x000000@0.35:shadowx=0:shadowy={}"


def _label(card: Card, words: str) -> str:
    return words + (f"  \u00b7  CHANNEL {card.number}" if card.number else "")


def _intro_text(
    card: Card, accent: str, tx: int, room: float, s: Callable[[float], int]
) -> tuple[list[str], list[str]]:
    """The Intro Bumper's words, laid out for 720 lines: (the label and the
    name, then the description and what's on)."""
    title = []
    y = s(196)
    title.append(drawtext(_label(card, "YOU\u2019RE TUNING IN TO"), SEMI, s(22), accent, tx, y))
    y += s(40)
    lines, size = fit(card.name, BOLD, room, s(76), s(46), 2)
    for line in lines:
        title.append(drawtext(line, BOLD, size, "FFFFFF", tx, y, _SHADOW.format(s(3))))
        y += round(size * 1.12)
    y += s(14)
    title.append(f"drawbox=x={tx}:y={y}:w={s(300)}:h={max(2, s(5))}:c=0x{accent}:t=fill")
    y += s(34)
    rest = []
    heading, show, detail = card.now
    now_y = s(548)
    if card.description.strip():
        most = max(1, min(3, (now_y - s(24) - y) // s(42) if show else 3))
        lines, size = fit(card.description[:DESCRIPTION_MAX], MEDIUM, room, s(32), s(24), most)
        for line in lines:
            rest.append(drawtext(line, MEDIUM, size, "D9DEE6", tx, y))
            y += round(size * 1.38)
    if show:
        now_y = max(now_y, y + s(16))
        if heading:
            rest.append(drawtext(heading, SEMI, s(20), accent, tx, now_y))
        lines, size = fit(show, BOLD, room, s(34), s(26), 1)
        rest.append(drawtext(lines[0], BOLD, size, "FFFFFF", tx, now_y + s(32)))
        if detail:
            lines, dsize = fit(detail, MEDIUM, room, s(24), s(20), 1)
            rest.append(
                drawtext(lines[0], MEDIUM, dsize, "AEB6C2", tx, now_y + s(32) + round(size * 1.3))
            )
    return title, rest


# How the Station ID card's "up next" is set, roomiest first: the show's
# largest and smallest size and most lines, then the same for the episode.
_UP_NEXT_SIZES = (
    (54, 36, 2, 30, 24, 2),
    (46, 32, 2, 26, 22, 1),
    (40, 28, 1, 24, 20, 1),
)


def _ident_text(
    card: Card,
    accent: str,
    tx: int,
    room: float,
    middle: int,
    s: Callable[[float], int],
    words: str = "YOU\u2019RE WATCHING",
) -> tuple[list[str], list[str]]:
    """The Station ID card's words, laid out for 720 lines and centred
    beside the logo: (the label and the station's name, then what's up next
    in large type, the show and the episode on up to two lines each). The
    Feature Presentation card is laid out the same, with "Feature
    Presentation" for the name and the movie for what's up next."""
    names, name_size = fit_tidy(card.name, BOLD, room, s(64), s(40), 2)
    top_h = s(40) + round(name_size * 1.12) * len(names) + s(14) + s(5) + s(40)
    heading, show, detail = card.now
    for show_big, show_small, show_most, detail_big, detail_small, detail_most in _UP_NEXT_SIZES:
        shows, show_size = fit_tidy(show, BOLD, room, s(show_big), s(show_small), show_most)
        details, detail_size = fit(
            detail, MEDIUM, room, s(detail_big), s(detail_small), detail_most
        )
        next_h = (s(36) if heading else 0) + round(show_size * 1.1) * len(shows)
        next_h += (s(8) + round(detail_size * 1.3) * len(details)) if details else 0
        if top_h + next_h <= s(620):
            break
    y = max(s(50), min(middle - (top_h + next_h) // 2, s(690) - top_h - next_h))
    title = [drawtext(_label(card, words), SEMI, s(22), accent, tx, y)]
    y += s(40)
    for line in names:
        title.append(drawtext(line, BOLD, name_size, "FFFFFF", tx, y, _SHADOW.format(s(3))))
        y += round(name_size * 1.12)
    y += s(14)
    title.append(f"drawbox=x={tx}:y={y}:w={s(300)}:h={max(2, s(5))}:c=0x{accent}:t=fill")
    y += s(5) + s(40)
    rest = []
    if heading:
        rest.append(drawtext(heading, SEMI, s(24), accent, tx, y))
        y += s(36)
    for line in shows:
        rest.append(drawtext(line, BOLD, show_size, "FFFFFF", tx, y, _SHADOW.format(s(2))))
        y += round(show_size * 1.1)
    if details:
        y += s(8)
    for line in details:
        rest.append(drawtext(line, MEDIUM, detail_size, "C4CBD6", tx, y))
        y += round(detail_size * 1.3)
    return title, rest


# --------------------------------------------------------------- the reel


@dataclass(frozen=True)
class Timing:
    title_at: float  # the name wipes in
    rest_at: float  # then everything else
    wipe_s: float
    fade_s: float  # into the show


def timing(length: float) -> Timing:
    if length <= 3:
        return Timing(0.06, 0.34, 0.3, 0.25)
    if length <= 5:
        return Timing(0.1, 0.45, 0.4, 0.3)
    return Timing(0.12, 0.55, 0.5, 0.35)


def snow(
    length: float, clicks: tuple[float, ...], static: tuple[tuple[float, float], ...], t: float
) -> float:
    """How much static lies over the card at time t: a flash as it starts, a
    flicker at each click of the knob, a little more while the sound is only
    static, and a light layer otherwise, so the card always reads."""
    level = 0.05
    if t < 0.3:
        level = max(level, 0.45 * (1 - t / 0.3))
    for a, b in static:
        if a <= t < b:
            level = max(level, 0.1)
    for c in clicks:
        if c <= t < c + 0.18:
            level = max(level, 0.05 + 0.17 * (1 - (t - c) / 0.18))
    return round(level, 3)


def snow_commands(length: float, sound: Sound | None, target: str) -> str:
    clicks, static = (sound.clicks, sound.static) if sound else ((), ())
    out, last = [], None
    n = 0
    fps = ff.FPS_NUM / ff.FPS_DEN
    while n / fps < length:
        at = n / fps
        v = snow(length, clicks, static, at)
        if v != last:
            out.append(f"{at:.3f} {target} all_opacity {v}")
            last = v
        n += 1
    return ";".join(out)


def _jitter(clicks: tuple[float, ...]) -> str:
    """The picture jumps sideways a few pixels for a moment at each click."""
    if not clicks:
        return "0"
    return "+".join(
        f"4*between(t,{c:.3f},{c + 0.034:.3f})-2*between(t,{c + 0.034:.3f},{c + 0.067:.3f})"
        for c in clicks
    )


@dataclass(frozen=True)
class ShowAudio:
    """The show's own sound, for the bumper's last third: its file, where
    in it that starts, which audio track, and whether it's evened out."""

    source: str
    start_s: float
    audio_index: int
    normalize: bool


# Where someone tuning in joins a station: where it is, as on real TV
# ("now", the bumper's sound fading into the show's), or the program on now
# from its beginning ("start": the bumper keeps its own sound to the end,
# and the program starts on its first frame; see broadcaster.py).
TUNE_IN = ("now", "start")


def land_at(length: float) -> float:
    """When the dial lands on the station and the show's sound comes in."""
    return round(length * 2 / 3, 3)


# How long finding and opening the show's file may take before the bumper
# keeps the dial's sound to the end instead.
SHOW_AUDIO_WAIT_S = 2.5


async def find_show_audio(
    ctx: AppContext,
    station: StationSchedule,
    start_ms: int,
    length: float,
    skipped: Callable[[str], bool] = lambda _key: False,
) -> ShowAudio | None:
    """The show's own sound for the last third of a bumper starting at
    `start_ms` on the schedule, if it can carry straight on into the show:
    the same program airs from the landing to past the bumper's end (not a
    break, not an intro or credits being skipped), and its file opens in
    time and has sound. None otherwise."""
    land_ms = start_ms + round(land_at(length) * 1000)
    end_ms = start_ms + round(length * 1000)
    slot = station.locate(land_ms)
    if slot is None:
        return None
    item = slot.item
    into_ms = land_ms - slot.start_ms - item.lead_ms  # (not while a card plays before it)
    if into_ms < 0 or end_ms + 1500 > slot.start_ms + item.program_end_ms:
        return None
    if skipped(item.rating_key):
        return None
    plan = pieces(item.segments, into_ms / 1000, (end_ms - land_ms) / 1000)
    if len(plan) != 1:
        return None

    async def open_it() -> ShowAudio | None:
        resolved = await ctx.resolve_source(item)
        if resolved.error or not resolved.source:
            return None
        source, at_s = resolved.source, plan[0][0]
        if resolved.parts:
            # (A movie in several files: in the one it lands in, and only if
            # it doesn't go on to the next before the bumper ends.)
            starts = await part_starts(
                ctx.settings, ctx.library, item.rating_key, resolved.parts, ctx.media_access
            )
            found = across(plan, starts) if starts else []
            if len(found) != 1:
                return None
            n, at_s, _ = found[0]
            if n:
                here = await ctx.locate(item.rating_key, resolved.parts[n])
                if here.error or not here.source:
                    return None
                source = here.source
        probed = await ff.probe(ctx.settings, source, timeout=SHOW_AUDIO_WAIT_S)
        if not probed.ok or probed.audio_index is None:
            return None
        return ShowAudio(source, at_s, probed.audio_index, item.kind == "episode")

    try:
        return await asyncio.wait_for(open_it(), SHOW_AUDIO_WAIT_S)
    except (TimeoutError, OSError):
        return None


def _card_video(settings: Settings, length: float, folder: Path, how: Motion) -> list[str]:
    """The card drawn in `folder`, moving, for `length` seconds: the name
    wiping in, then everything else, and the logo arriving and moving.
    Graph lines ending in [card]."""
    tm = timing(length)
    o1, o2 = tm.title_at, max(tm.rest_at, tm.title_at + tm.wipe_s)

    def still(name: str, seconds: float) -> str:
        return (
            f"movie='{folder / name}.png',loop=loop=-1:size=1,setpts=N/({FPS})/TB,fps={FPS},"
            f"format=yuv420p,setsar=1,trim=duration={seconds:.3f}"
        )

    g = [
        still("base", o1 + tm.wipe_s) + "[s0]",
        still("title", o2 + tm.wipe_s - o1) + "[s1]",
        still("full", length - o2 + 1) + "[s2]",
        f"[s0][s1]xfade=transition=wiperight:duration={tm.wipe_s}:offset={o1}[x1]",
        f"[x1][s2]xfade=transition=wiperight:duration={tm.wipe_s}:offset={o2}[card0]",
    ]
    if (folder / "logo.png").is_file() and (folder / "shine.png").is_file():
        g += _moving_logo(settings, length, folder, how)
    else:
        g.append("[card0]null[card]")
    return g


_STEREO = "aformat=sample_rates=48000:channel_layouts=stereo"
_SILENCE = ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]


def _reel_inputs(
    settings: Settings,
    length: float,
    burst_s: float | None,
    folder: Path,
    sound: Sound | None,
    how: Motion,
    show: ShowAudio | None,
) -> list[str]:
    """The Intro Bumper: the card under a light layer of static that
    flickers as the knob clicks, over `sound` (or silence), with the show's
    own sound coming in for the last third if `show` is given."""
    w, h = settings.video_width, settings.video_height
    tm = timing(length)
    pad = max(4, round(4 * h / 720))
    # When the show's own sound comes in (with the knob landing on the
    # station, if the dial's sound plays).
    land = land_at(length) if show else None
    landing = sound is not None and land is not None and LANDING.is_file()
    if sound and land is not None:
        # The dial stops at the station: the picture flickers with the
        # clicks before then, and with the landing's.
        sound = Sound(
            sound.path,
            (*(c for c in sound.clicks if c < land - 0.1), *((land,) if landing else ())),
            tuple((a, min(b, land)) for a, b in sound.static if a < land),
        )
    clicks = sound.clicks if sound else ()
    g = [
        *_card_video(settings, length, folder, how),
        f"color=c=0x808080:s={w // 4}x{h // 2}:r={FPS},noise=c0s=100:c0f=t+u,"
        f"scale={w}:{h}:flags=bicubic,setsar=1,eq=contrast=1.2,format=yuv420p,"
        f"sendcmd=c='{snow_commands(length, sound, 'blend@tv')}'[snow]",
        "[snow][card]blend@tv=all_mode=normal:all_opacity=0.45[tv]",
        f"[tv]pad={w + 2 * pad}:{h}:{pad}:0,crop={w}:{h}:x='{pad}-({_jitter(clicks)})':y=0,"
        f"fade=out:st={length - tm.fade_s:.3f}:d={tm.fade_s - 0.04:.3f},setsar=1,format=yuv420p[out0]",
    ]
    args = [*ff.common_prefix(settings)]
    if burst_s is not None:
        args += ff.paced(burst_s)
    args += ["-f", "lavfi", "-i", ";".join(g)]
    args += ["-i", str(sound.path)] if sound else _SILENCE
    if land is None or show is None:
        return [*args, "-map", "0:v:0", "-map", "1:a:0", "-t", f"{length:.3f}"]
    # The last third: the show's own sound comes in (as the knob lands on
    # the station), from exactly where the schedule has got to, so it
    # carries straight on into the show.
    if show.source.startswith(("http://", "https://")):
        args += ["-reconnect", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "5"]
    args += ["-ss", f"{show.start_s:.3f}", "-t", f"{length - land + 0.5:.3f}", "-i", show.source]
    delay = round(land * 1000)
    level = f",loudnorm={ff.LOUDNESS_TARGET}" if show.normalize else ""
    mix = (
        f"[1:a]{_STEREO},atrim=0:{land + 0.2:.3f},afade=t=out:st={land - 0.05:.3f}:d=0.25[dial];"
        f"[2:a:{show.audio_index}]aresample=48000{level},{_STEREO},"
        f"afade=t=in:st=0:d=0.5,adelay={delay}|{delay}[show];"
    )
    if landing:
        args += ["-i", str(LANDING)]
        mix += f"[3:a]{_STEREO},adelay={delay}|{delay}[landing];[dial][landing][show]amix=inputs=3"
    else:
        mix += "[dial][show]amix=inputs=2"
    mix += f":duration=longest:normalize=0,{_STEREO},apad[aout]"
    return [
        *args, "-filter_complex", mix, "-map", "0:v:0", "-map", "[aout]", "-t", f"{length:.3f}",
    ]  # fmt: skip


# The Station ID card fades in from the program before and out to the next.
IDENT_FADE_IN_S = 0.25
IDENT_FADE_OUT_S = 0.3


def _ident_inputs(
    settings: Settings,
    length: float,
    burst_s: float | None,
    folder: Path,
    jingle_: Path | None,
    how: Motion,
) -> list[str]:
    """The Station ID card: the card fading in and out, over `jingle_`
    (or silence), the jingle faded out as the card ends."""
    g = [
        *_card_video(settings, length, folder, how),
        f"[card]fade=in:st=0:d={IDENT_FADE_IN_S},"
        f"fade=out:st={length - IDENT_FADE_OUT_S:.3f}:d={IDENT_FADE_OUT_S - 0.03:.3f},"
        "setsar=1,format=yuv420p[out0]",
    ]
    args = [*ff.common_prefix(settings)]
    if burst_s is not None:
        args += ff.paced(burst_s)
    args += ["-f", "lavfi", "-i", ";".join(g)]
    if jingle_ is None:
        return [*args, *_SILENCE, "-map", "0:v:0", "-map", "1:a:0", "-t", f"{length:.3f}"]
    fade = max(0.2, min(0.6, length / 6))
    return [
        *args, "-i", str(jingle_),
        "-filter_complex", f"[1:a]{_STEREO},afade=t=out:st={length - fade:.3f}:d={fade:.3f},apad[aout]",
        "-map", "0:v:0", "-map", "[aout]", "-t", f"{length:.3f}",
    ]  # fmt: skip


# How the logo arrives (one picked at random each time).
ENTRANCES = (
    "pop", "fade", "spin", "swing", "flip", "vibrate",
    "shimmer", "glow", "materialize", "zap", "drop", "slide",
)  # fmt: skip
# Which entrances suit which lengths: a short bumper gets the quick, crisp
# ones; the ones that need time to read wait for the longer bumpers.
QUICK = ("pop", "fade", "zap", "slide", "glow")
_ENTRANCES_FOR = {3: QUICK, 5: (*QUICK, "flip", "swing", "shimmer", "drop")}
# How long an entrance takes at each length (the slow, showy ones a quarter
# longer): tight at 3 seconds, with room to breathe at 15.
_ENTRANCE_S = {3: 0.5, 5: 0.75, 10: 0.95, 15: 1.2}
SLOW = ("shimmer", "glow", "materialize")


def _band(length: float) -> int:
    """The bumper length (3, 5, 10 or 15) a card of `length` seconds moves
    like: a card cut short (joined partway) moves like a shorter one."""
    return 3 if length < 4 else 5 if length < 7.5 else 10 if length < 12.5 else 15


def entrances_for(length: float) -> tuple[str, ...]:
    return _ENTRANCES_FOR.get(_band(length), ENTRANCES)


def idles_for(length: float) -> tuple[str, ...]:
    return ("still",) if _band(length) == 3 else ("gleam", "float")


@dataclass(frozen=True)
class Motion:
    entrance: str = "pop"
    idle: str = "gleam"


def motion(length: float, rng: random.Random | None = None) -> Motion:
    """How the logo moves in a bumper of `length` seconds, picked at random
    from what suits that length."""
    r = rng or random
    return Motion(r.choice(entrances_for(length)), r.choice(idles_for(length)))


def _moving_logo(settings: Settings, length: float, folder: Path, how: Motion) -> list[str]:
    """The logo, moving: its entrance, a band of light sweeping across it
    (again halfway through a longer bumper), and then a slow grow or a
    gentle float while the card is up. Only the logo's own small square is
    worked on, so it costs little."""
    lx, ly, ls = _logo_place(settings)
    k = settings.video_height / 720
    m = max(2, round(ls / 8) // 2 * 2)  # room around the logo, for its glow and turns
    c = ls + 2 * m
    until = f"trim=duration={length + 1:.3f}"
    e = how.entrance if how.entrance in ENTRANCES else "pop"
    d = _ENTRANCE_S[_band(length)] * (1.25 if e in SLOW else 1)
    long = _band(length) == 15

    def still(name: str) -> str:
        return (
            f"movie='{folder / name}',loop=loop=-1:size=1,setpts=N/({FPS})/TB,fps={FPS},"
            f"format=rgba,{until}"
        )

    def plain(colour: str, size: int, fmt: str = "rgba") -> str:
        return f"color=c={colour}:s={size}x{size}:r={FPS},format={fmt},{until}"

    p = f"clip(t/{d},0,1)"
    eo = f"(1-pow(1-{p},3))"  # eases out
    back = f"(1+2.70158*pow({p}-1,3)+1.70158*pow({p}-1,2))"  # overshoots a little

    # The gleam: a band of light across the logo after it has arrived (or,
    # for "shimmer", riding the edge as it's revealed), once more halfway
    # through a 10-second bumper, and twice more in a 15-second one. None
    # in a 3-second bumper: the logo just settles.
    sweep_s = 0.75 if _band(length) <= 5 else 0.9
    first, first_s = (0.0, d) if e == "shimmer" else (d + 0.15, sweep_s)
    later = {10: [0.55], 15: [0.45, 0.75]}.get(_band(length), [])
    sweeps = [] if how.idle == "still" and e != "shimmer" else [first]
    sweeps += [round(length * f, 2) for f in later if how.idle != "still"]
    window = (
        "+".join(
            f"between(t,{t0},{t0 + span})*({3.3 * ls:.0f}-{2.6 * ls:.0f}*clip((t-{t0})/{span},0,1))"
            for t0, span in ((t0, first_s if t0 == first else sweep_s) for t0 in sweeps)
        )
        or "0"
    )
    g = [
        still("logo.png") + ",split[lgA][lgB]",
        still("shine.png") + f",crop={ls}:{ls}:x='{window}':y=0,alphaextract[band]",
        "[lgB]alphaextract[lgMask]",
        "[band][lgMask]blend=all_mode=multiply[shineMask]",
        plain("white", ls) + "[white]",
        "[white][shineMask]alphamerge[gleam]",
        f"[lgA][gleam]overlay=format=auto,pad={c}:{c}:{m}:{m}:color=black@0[lgP]",
    ]
    grow = f"(1+0.035*t/{length})" if how.idle == "gleam" else "1"  # a slow drift larger
    size = grow  # the logo's size as a share of its own
    x_off, y_off = "0", "0"
    steps: list[str] = []  # filters on the logo before it's sized
    fade_s = 0.2
    if e == "pop":
        size = f"(0.72+0.28*{back})*{grow}"
    elif e == "fade":
        size, fade_s = f"(0.94+0.06*{eo})*{grow}", d
    elif e == "spin":
        turns = 1.5 if long else 1  # one and a half turns when there's time
        steps.append(
            f"rotate=a='-{2 * turns}*PI*(1-{eo})':c=none:ow='hypot(iw,ih)':oh='hypot(iw,ih)'"
        )
        size = f"(0.3+0.7*{eo})*{grow}"
    elif e == "swing":
        steps.append(
            "rotate=a='-0.45*exp(-4.5*t)*cos(10*t)':c=none:ow='hypot(iw,ih)':oh='hypot(iw,ih)'"
        )
        size = f"(0.9+0.1*{eo})*{grow}"
    elif e == "vibrate":
        calm = 3.2 * 0.95 / d  # shakes for longer in a longer bumper
        x_off = f"{14 * k:.1f}*sin(2*PI*17*t)*exp(-{calm:.2f}*t)"
        y_off = f"{5 * k:.1f}*sin(2*PI*23*t)*exp(-{calm:.2f}*t)"
        size, fade_s = f"(0.88+0.12*{back})*{grow}", 0.12
    elif e == "drop":
        y_off = (
            f"if(lt(t,{d}),-({ly}+{c})*pow(1-{p},2),"
            f"-{(34 if long else 26) * k:.0f}*exp(-7*(t-{d}))*abs(sin(11*(t-{d}))))"
        )
        fade_s = 0.1
    elif e == "slide":
        # Travels a long way, so it barely overshoots (a pixel or ten).
        soft = f"(1+1.5*pow({p}-1,3)+0.5*pow({p}-1,2))"
        x_off = f"-({lx}+{c})*(1-{soft})"
        fade_s = 0.15
    elif e == "shimmer":
        # Revealed left to right behind a soft edge, the gleam riding it.
        g += [
            f"gradients=s={3 * c}x{c}:r={FPS}:c0=0xFFFFFFFF:c1=0xFFFFFF00:nb_colors=2:type=linear"
            f":x0={round(1.45 * c)}:y0=0:x1={round(1.6 * c)}:y1=0:speed=0.00001,format=rgba,{until},"
            f"crop={c}:{c}:x='{1.6 * c:.0f}-{1.15 * c:.0f}*{p}':y=0,alphaextract[reveal]",
            "[lgP]split[shA][shB]",
            "[shB]alphaextract[shMask]",
            "[shMask][reveal]blend=all_mode=multiply[shNew]",
            "[shA][shNew]alphamerge[lgP2]",
        ]
        size, fade_s = f"(0.97+0.03*{eo})*{grow}", 0
    elif e == "glow":
        # A halo and a flash of light that fade as it settles.
        g += [
            "[lgP]split=3[gwA][gwB][gwC]",
            f"[gwB]alphaextract,gblur=sigma={max(2, c / 18):.1f}[haloMask]",
            plain("white", c) + "[wHalo]",
            "[wHalo][haloMask]alphamerge,colorchannelmixer=aa=0.9,"
            f"fade=out:st=0.2:d={d + 0.2:.2f}:alpha=1[halo]",
            "[gwC]alphaextract[flashMask]",
            plain("white", c) + "[wFlash]",
            "[wFlash][flashMask]alphamerge,colorchannelmixer=aa=0.85,"
            f"fade=out:st=0.05:d={d * 0.7:.2f}:alpha=1[flash]",
            "[halo][gwA]overlay=format=auto[gw1]",
            "[gw1][flash]overlay=format=auto[lgP2]",
        ]
        size, fade_s = f"(0.95+0.05*{eo})*{grow}", 0.3
    elif e == "materialize":
        # The reverse of a dissolve: it gathers from specks.
        n = max(8, c // 4)
        g += [
            f"color=c=black:s={n}x{n}:r={FPS}:d=0.1,format=gray,geq=lum='random(1)*255',"
            f"scale={c}:{c}:flags=neighbor,loop=loop=-1:size=1,setpts=N/({FPS})/TB,{until}[specks]",
            plain("white", c, "gray") + f",fade=out:st=0:d={d}[level]",
            plain("black", c, "gray") + "[lo]",
            plain("white", c, "gray") + "[hi]",
            "[specks][level][lo][hi]threshold[gather]",
            "[lgP]split[mtA][mtB]",
            "[mtB]alphaextract[mtMask]",
            "[mtMask][gather]blend=all_mode=multiply[mtNew]",
            "[mtA][mtNew]alphamerge[lgP2]",
        ]
        fade_s = 0
    elif e == "zap":
        # Like an old set switching on: a line, then the picture, in a flash.
        z = min(1.3, max(0.7, d / 0.95))  # a touch quicker or slower with the length
        g += [
            "[lgP]split[zpA][zpB]",
            "[zpB]alphaextract[zpMask]",
            plain("white", c) + "[wZap]",
            "[wZap][zpMask]alphamerge,colorchannelmixer=aa=0.9,"
            f"fade=out:st={0.1 * z:.3f}:d={0.45 * z:.3f}:alpha=1[zap]",
            "[zpA][zap]overlay=format=auto[lgP2]",
        ]
        x_off = f"{5 * k:.1f}*sin(97*t)*exp(-6*t)"
        fade_s = 0
    source = "[lgP2]" if any(line.endswith("[lgP2]") for line in g) else "[lgP]"
    if e == "flip":
        # Turns to face you, like a card.
        steps.append(
            f"scale=w='max(2,trunc(iw*sin(PI/2*{eo})*{grow}/2)*2)':h='trunc(ih*{grow}/2)*2':eval=frame"
        )
        fade_s = 0.15
    elif e == "zap":
        z = min(1.3, max(0.7, d / 0.95))
        steps.append(
            f"scale=w='max(2,trunc(iw*clip(t/{0.1 * z:.3f},0.03,1)/2)*2)'"
            f":h='max(2,trunc(ih*if(lt(t,{0.1 * z:.3f}),0.03,clip((t-{0.1 * z:.3f})/{0.22 * z:.3f},0.03,1))*{grow}/2)*2)'"
            ":eval=frame"
        )
    else:
        steps.append(f"scale=w='trunc(iw*{size}/2)*2':h=-2:eval=frame")
    if fade_s:
        steps.append(f"fade=in:st=0:d={fade_s}:alpha=1")
    if how.idle == "float":
        y_off = f"({y_off})+{5 * k:.1f}*sin(2*PI*0.3*(t-{d}))*clip((t-{d})/0.6,0,1)"
    g.append(source + ",".join(steps) + "[lg]")
    g.append(
        f"[card0][lg]overlay=x='{lx}-overlay_w/2+({x_off})':y='{ly}-overlay_h/2+({y_off})'"
        ":eval=frame:format=auto[card]"
    )
    return g


def reel_command(
    settings: Settings,
    length: float,
    ts_offset_s: float,
    burst_s: float,
    channel_name: str,
    folder: Path,
    sound: Sound | None,
    how: Motion | None = None,
    show: ShowAudio | None = None,
) -> list[str]:
    """ffmpeg arguments for the Intro Bumper on the air, from the pictures
    stills_command drew in `folder`, with `sound` (or silence), the logo
    moving `how`, and the show's own sound for the last third if given."""
    return _reel_inputs(
        settings, length, burst_s, folder, sound, how or Motion(), show
    ) + ff.output_args(settings, ts_offset_s, channel_name)


def ident_command(
    settings: Settings,
    length: float,
    ts_offset_s: float,
    burst_s: float,
    channel_name: str,
    folder: Path,
    jingle_: Path | None,
    how: Motion | None = None,
) -> list[str]:
    """ffmpeg arguments for the Station ID card on the air, from the
    pictures stills_command drew in `folder`, over `jingle_` (or silence)."""
    return _ident_inputs(
        settings, length, burst_s, folder, jingle_, how or Motion()
    ) + ff.output_args(settings, ts_offset_s, channel_name)


_MP4 = [
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", "-y",
]  # fmt: skip


def preview_command(
    settings: Settings,
    length: float,
    folder: Path,
    sound: Sound | None,
    out: Path,
    how: Motion | None = None,
    show: ShowAudio | None = None,
) -> list[str]:
    """The Intro Bumper as a small MP4 file to watch in the station editor."""
    return [
        *_reel_inputs(settings, length, None, folder, sound, how or Motion(), show),
        *_MP4, str(out),
    ]  # fmt: skip


def ident_preview_command(
    settings: Settings,
    length: float,
    folder: Path,
    jingle_: Path | None,
    out: Path,
    how: Motion | None = None,
) -> list[str]:
    """The Station ID card as a small MP4 file to watch in the station editor."""
    return [
        *_ident_inputs(settings, length, None, folder, jingle_, how or Motion()),
        *_MP4,
        str(out),
    ]
