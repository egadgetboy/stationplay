"""The Up Next Banner: three minutes before a show or movie ends, a banner in
the bottom-left corner says what's on next. It shows the station's logo,
"UP NEXT" and the next show or movie for 3, 5 or 10 seconds, sliding in and
then fading away. If the station's corner logo is in that corner, the banner
takes its place: its own logo is drawn the same size in exactly the same
place, and the corner logo fades into it and back.

It's drawn once per program as a picture, in the logo's colours like the
Station ID card, while the program's file is being opened. On the air it's
laid over the program (see ffmpeg.Banner).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import ffmpeg as ff
from . import intro

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import Settings

log = logging.getLogger(__name__)

LENGTHS = (0, 3, 5, 10)  # how long it's shown, in seconds; 0 is off
# Its sizes, as shares of the largest.
SIZES = {"small": 0.7, "medium": 0.85, "large": 1.0}
BEFORE_END_S = 180.0  # it's shown this long before the program ends
# Kept clear between the banner's end and the end of the part of the
# program it's in (a part ends where a skipped stretch of credits begins).
END_CLEAR_S = 1.0
# The space around the banner in its picture, for its shadow (at 720 lines,
# the largest size).
SHADOW_ROOM = 16


@dataclass(frozen=True)
class UpNext:
    """A banner to show near the end of a program: what's on next, the
    station's logo (None for none), and how long and how big it is. If the
    station's corner logo is in the bottom-left corner, `corner_logo` is its
    size, and the banner's logo takes its exact place (`nudge`: where the
    corner logo is moved to for this program, against burn-in: see
    ffmpeg.NUDGES)."""

    title: str
    logo: str | None
    seconds: int
    size: str
    corner_logo: int | None = None
    nudge: tuple[int, int] = (0, 0)

    @property
    def on_corner_logo(self) -> bool:
        return self.corner_logo is not None and ff.usable_picture(self.logo) is not None


def corner_logo(settings: Settings, mark: ff.Watermark | None) -> int | None:
    """The corner logo's size, if `mark` is a logo in the bottom-left
    corner (where the banner goes) all through programs; None otherwise.
    (One shown only at their start is long gone three minutes before the
    end. If someone tunes in late enough to see both, it makes way.)"""
    if mark is None or mark.clock or mark.position != "bottom-left" or mark.until_s is not None:
        return None
    return ff.mark_size(settings, mark) if ff.usable_picture(mark.logo) else None


def _scale(settings: Settings, size: str) -> float:
    """From the layout's 720 lines to the stream's, at `size`."""
    return settings.video_height / 720 * SIZES.get(size, 1.0)


def _shadow_room(settings: Settings, size: str) -> int:
    """The space around the banner in its picture: where it sits is that
    much in from the picture's edges."""
    return max(2, round(SHADOW_ROOM * _scale(settings, size)))


def when(part_from_s: float, part_s: float, due_s: float, seconds: float) -> float | None:
    """When the banner starts in a part of a program that airs from
    `part_from_s` into it for `part_s` seconds, if it's shown in that part:
    `due_s` into the program, or earlier if the part ends too soon after.
    None if it isn't shown in that part."""
    at = due_s - part_from_s
    if not 0 <= at < part_s:
        return None
    at = min(at, part_s - seconds - END_CLEAR_S)
    return at if at >= 0 else None


def banner_command(
    settings: Settings, banner: UpNext, colours: tuple[str, str, str], out: Path
) -> tuple[list[str], tuple[int, int]]:
    """(ffmpeg arguments that draw `banner` in `out`, where the picture's
    top-left corner goes on the screen). The picture is a PNG with
    see-through edges and a soft shadow: a rounded panel in the logo's
    colours with the logo, a bar in its accent colour, "UP NEXT" and the
    title (on two lines, or cut short, if it's very long). It's laid out for
    720 lines, scaled to the stream's size and the banner's, and goes in the
    bottom-left corner; on the corner logo, its logo exactly where that is."""
    k = _scale(settings, banner.size)

    def s(v: float) -> int:
        return max(1, round(v * k))

    def even(v: int) -> int:
        """(Pictures go over the program at even pixels: with the picture's
        own offsets even, its logo lands exactly on the corner logo.)"""
        return v + v % 2

    dark, light, accent = colours
    logo = ff.usable_picture(banner.logo)
    room = even(_shadow_room(settings, banner.size))
    pad = even(s(16))
    corner = banner.corner_logo if banner.on_corner_logo else None
    logo_s = corner or s(68)
    # (A logo that isn't square gets a box of the same area: as the corner
    # logo does, so it's still exactly where that is.)
    logo_w, logo_h = ff.logo_box(logo, logo_s) if logo else (logo_s, logo_s)
    bar_x = pad + logo_w + s(16) if logo else s(22)
    bar_w = max(2, s(3))
    text_x = bar_x + bar_w + s(16)
    widest = round(settings.video_width * 0.6 * SIZES.get(banner.size, 1.0))
    text_room = widest - text_x - s(24)

    label = "UP NEXT"
    label_size = s(17)
    lines, title_size = _title(" ".join(banner.title.split()) or "Stay tuned", text_room, s)
    # (A little extra, as the fonts' real widths can round up.)
    text_w = max(
        intro.text_width(label, intro.SEMI, label_size),
        *(intro.text_width(line, intro.BOLD, title_size) for line in lines),
    )
    width = text_x + round(text_w * 1.02) + s(24)
    # The writing, centred top to bottom by its capitals (Montserrat's are
    # 0.7 of its size): "UP NEXT", then the title's lines.
    leading = round(title_size * 1.14)
    block = round(0.7 * label_size) + s(10) + round(0.7 * title_size) + leading * (len(lines) - 1)
    height = max(s(92), block + 2 * s(24), logo_h + 2 * s(12) if logo else 0)
    logo_y = even((height - logo_h) // 2)
    top = (height - block) // 2
    label_y = top + round(0.7 * label_size)
    title_y = label_y + s(10) + round(0.7 * title_size)

    def rounded(alpha: float) -> str:
        """A grey mask of the panel's shape, `alpha` opaque, its corners
        rounded and smoothed."""
        r = s(14)
        cx, cy = width / 2, height / 2
        shape = (
            f"clip({r}+0.5-hypot(max(0,abs(X+0.5-{cx})-{cx - r}),"
            f"max(0,abs(Y+0.5-{cy})-{cy - r})),0,1)"
        )
        return (
            f"color=c=black:s={width}x{height},format=gray,geq=lum='{round(255 * alpha)}*{shape}'"
        )

    full_w, full_h = width + 2 * room, height + 2 * room
    g = [
        # The shadow, a little below the panel
        rounded(0.5) + "[shMask]",
        f"color=c=black:s={width}x{height},format=rgba[shInk]",
        "[shInk][shMask]alphamerge,"
        f"pad={full_w}:{full_h}:{room}:{room + s(3)}:color=black@0,"
        f"gblur=sigma={max(1.0, 5 * k):.1f}[shadow]",
        # The panel: the logo's dark colour lightening towards the right
        f"gradients=s={width}x{height}:c0=0x{dark}:c1=0x{light}:nb_colors=2"
        f":x0=0:y0=0:x1={width - 1}:y1=0:speed=0.00001,format=rgba[ink]",
        rounded(0.9) + "[mask]",
        "[ink][mask]alphamerge[panel]",
        f"[shadow][panel]overlay={room}:{room}:format=auto[b1]",
    ]
    last = "[b1]"
    if logo:
        # Sized and placed in its box as the corner logo is in its own.
        g.append(
            f"movie='{logo}',scale={logo_w}:{logo_h}:force_original_aspect_ratio=decrease,"
            "format=rgba[logo]"
        )
        g.append(
            f"[b1][logo]overlay=x={room + pad}:y='{room + logo_y + logo_h}-overlay_h'"
            ":format=auto[b2]"
        )
        last = "[b2]"
    bar_h = round(height * 0.52)
    words = [
        f"drawbox=x={room + bar_x}:y={room + (height - bar_h) // 2}:w={bar_w}:h={bar_h}"
        f":c=0x{accent}:t=fill",
        intro.drawtext(
            label,
            intro.SEMI,
            label_size,
            accent,
            room + text_x,
            room + label_y,
            ":y_align=baseline",
        ),
    ]
    for n, line in enumerate(lines):
        words.append(
            intro.drawtext(
                line,
                intro.BOLD,
                title_size,
                "FFFFFF",
                room + text_x,
                room + title_y + n * leading,
                f":y_align=baseline:shadowcolor=0x000000@0.35:shadowx=0:shadowy={max(1, s(2))}",
            )
        )
    g.append(last + ",".join(words) + ",format=rgba[out]")
    args = [
        settings.ffmpeg_path, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-filter_complex", ";".join(g),
        "-map", "[out]", "-frames:v", "1", "-update", "1", str(out),
    ]  # fmt: skip
    margin_x, margin_y = ff.corner_margins(settings)
    if banner.on_corner_logo:
        dx, dy = banner.nudge
        where = (margin_x - pad + dx, settings.video_height - margin_y - logo_h - logo_y + dy)
    else:
        where = (margin_x, settings.video_height - margin_y - height)
    return args, (where[0] - room, where[1] - room)


def _title(title: str, room: float, s: Callable[[float], int]) -> tuple[list[str], int]:
    """The title's lines and size: one line, as large as fits; if it's too
    long for that, two lines about as wide as each other (broken after a
    colon or dash if that's nearly as even), a little smaller; failing
    that, cut short."""
    lines, size = intro.fit(title, intro.BOLD, room, s(32), s(24), 1)
    if lines[0] == title:
        return lines, size
    words = title.split(" ")
    for size in range(s(26), s(21) - 1, -1):
        best: tuple[float, list[str]] | None = None
        for n in range(1, len(words)):
            first, second = " ".join(words[:n]), " ".join(words[n:])
            wide = max(
                intro.text_width(first, intro.BOLD, size),
                intro.text_width(second, intro.BOLD, size),
            )
            score = wide * (0.85 if first[-1] in ":-–—" else 1.0)
            if wide <= room and (best is None or score < best[0]):
                best = (score, [first, second])
        if best:
            return best[1], size
    return intro.fit(title, intro.BOLD, room, s(26), s(21), 2)


@functools.cache
def _cant_draw_in(folder: Path) -> None:
    """Says (once) that a folder's path can't be given to ffmpeg."""
    log.warning(
        "Up Next Banners can't be drawn: the path of StationPlay's data folder (%s) has "
        "characters ffmpeg can't handle. Use a path with only letters, numbers, and - _ . /",
        folder,
    )


async def draw(
    settings: Settings, banner: UpNext, out: Path, timeout_s: float
) -> tuple[int, int] | None:
    """Draws `banner` as the picture `out` within `timeout_s`: where the
    picture goes on the screen, or None if it couldn't be drawn (which is
    logged)."""
    if not ff.usable_picture(str(out)):
        _cant_draw_in(out.parent)
        return None
    started = time.monotonic()
    try:
        colours = await asyncio.wait_for(intro.colours(settings, banner.logo), timeout_s / 2)
    except TimeoutError:
        colours = intro.PLAIN_COLOURS
    args, where = banner_command(settings, banner, colours, out)
    try:
        await asyncio.to_thread(out.parent.mkdir, parents=True, exist_ok=True)
        code, said = await ff.run_to_end(args, max(0.1, timeout_s - (time.monotonic() - started)))
    except TimeoutError:
        log.warning("Drawing an Up Next Banner took too long (over %.0fs)", timeout_s)
        return None
    except OSError as e:
        log.warning("Couldn't draw an Up Next Banner: %s", e)
        return None
    if code != 0:
        log.warning("Drawing an Up Next Banner failed: %s", said)
        return None
    return where if await asyncio.to_thread(out.is_file) else None


def on_air(banner: UpNext, picture: Path, where: tuple[int, int], at_s: float) -> ff.Banner:
    """`banner`, drawn as `picture` to go at `where`, over a program from
    `at_s` into it. On the corner logo it fades in where that is (which
    fades out meanwhile); otherwise it slides in."""
    return ff.Banner(str(picture), at_s, banner.seconds, *where, slide=not banner.on_corner_logo)


# The editor's preview: the banner (and what's in the corner) over a plain
# picture, with a moment either side of it.
PREVIEW_LEAD_S = 1.0


def preview_command(
    settings: Settings,
    banner: UpNext,
    picture: Path,
    where: tuple[int, int],
    mark: ff.Watermark | None,
    out: Path,
) -> list[str]:
    """ffmpeg arguments for `banner`, drawn as `picture` to go at `where`, as
    a short MP4 for the station editor: as it looks on the air, with the
    corner mark `mark` (if any), over a plain picture."""
    w, h = settings.video_width, settings.video_height
    length = banner.seconds + 2 * PREVIEW_LEAD_S
    backdrop = (
        f"gradients=s={w}x{h}:r={intro.FPS}:c0=0x5B7088:c1=0x9AA5B1:c2=0x3A4656:nb_colors=3"
        f":x0=0:y0=0:x1={w - 1}:y1={h - 1}:speed=0.00001,format=yuv420p"
    )
    shown = on_air(banner, picture, where, PREVIEW_LEAD_S)
    return [
        settings.ffmpeg_path, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-filter_complex", ff.with_overlays(settings, backdrop, mark, shown),
        "-t", f"{length:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(out),
    ]  # fmt: skip


class Drawing:
    """The banner for a program, drawn as the program starts (into
    `picture`) and shown `due_s` into it."""

    def __init__(
        self, settings: Settings, banner: UpNext, due_s: float, picture: Path, timeout_s: float
    ) -> None:
        self.settings = settings
        self.banner = banner
        self.due_s = due_s
        self.picture = picture
        self._task = asyncio.create_task(self._draw(timeout_s))

    async def _draw(self, timeout_s: float) -> tuple[int, int] | None:
        try:
            return await draw(self.settings, self.banner, self.picture, timeout_s)
        except Exception:
            # Whatever goes wrong, the program plays: just without the banner.
            log.exception("Drawing an Up Next Banner failed")
            return None

    async def for_part(self, part_from_s: float, part_s: float, wait_s: float) -> ff.Banner | None:
        """The banner over a part of the program that airs from `part_from_s`
        into it for `part_s` seconds, if it's shown in that part and has
        been drawn (waiting up to `wait_s` for that); None otherwise."""
        at = when(part_from_s, part_s, self.due_s, self.banner.seconds)
        if at is None:
            return None
        try:
            where = await asyncio.wait_for(asyncio.shield(self._task), wait_s)
        except TimeoutError:
            log.info("The Up Next Banner wasn't drawn in time; the program plays without it")
            return None
        return on_air(self.banner, self.picture, where, at) if where else None

    async def close(self) -> None:
        """Stops drawing it, if it's still being drawn."""
        if not self._task.done():
            self._task.cancel()
            await asyncio.wait([self._task])
