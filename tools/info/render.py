"""The INFO station's film (1.34.1, the owner): 30 seconds, looping
without a seam, of tapioca pearls flying through the ring of tapiOca's
logo, on black: the INFO station's (see app/infostation.py), which tapiOca
draws the time and date, its panels and its web address over as it plays.
Its second video stream is where the pearls in front are, so tapiOca can
put them back over what it draws: the pearls always fly in front.

Black, the logo's white wordmark and ring, and pearls in its Signal Teal.
Each pearl comes from far behind the ring, passes through the gap around
the logo's own pearl, and flies past. Nothing stays still, so nothing burns
into a screen: the logo floats gently, closing its loop in the 30 seconds. Under it, music.py's tune, timed to the pearls.

Every part goes round in exactly 30 seconds, so the end runs straight into
the start, picture and sound. The file holds LOOPS of them, the music made
into AAC in one go (so no gap creeps in where one loop meets the next), and
the station plays the file over and over.

Drawn here, with Pillow and numpy (a tool's needs: neither is in the
server's image), from the page's own wordmark (index.html's tp-word) and
fonts, and made into H.264 with ffmpeg:

    python tools/info/render.py app/assets/info/tapioca-info.mp4
    python tools/info/render.py app/assets/info/logo.png --logo   (its station's logo)
    python tools/info/render.py /tmp/still.png --still 12.5     (one frame)
"""

from __future__ import annotations

import argparse
import math
import random
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent.parent
PAGE = ROOT / "app" / "web" / "index.html"
FONTS = ROOT / "app" / "web" / "fonts"

W, H, FPS, SECONDS = 1920, 1080, 30, 30
OUT_W, OUT_H = 1280, 720
LOOPS = 4  # in the file: 2 minutes
INK = np.array([10, 10, 10], dtype=np.float32)  # (the kit's Ink: "black")
WHITE = np.array([255, 255, 255], dtype=np.float32)
TEAL = np.array([0, 191, 166], dtype=np.float32)  # Signal Teal: the pearl

# The wordmark, as drawn: its width on screen, and its own pearl and ring
# (in the wordmark's units, as index.html's tp-word draws them).
WORD_PX = 860
RING = (281.6, 47.5)  # the ring's center
RING_OUT, RING_IN, PEARL = 36.0, 23.5, 12.6
GAP = (PEARL + RING_IN) / 2  # where the flying pearls pass, between the two

# The pearls: one every LEAVES seconds (in a 30-second loop), each flying
# FLIGHT seconds, from FAR times as far as the ring to NEAR (past it).
LEAVES = 0.375
FLIGHT = 5.2
FAR, NEAR = 10.0, 0.05
GOLDEN = math.pi * (3 - math.sqrt(5))


# The wordmark, from the page -----------------------------------------------------------


def _tokens(d: str) -> list[str]:
    return re.findall(r"[MmLlHhVvQqAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?", d)


def _arc(x0, y0, rx, ry, phi, large, sweep, x1, y1, steps=96):
    """Points along an SVG arc (the endpoint form, converted to its center)."""
    phi = math.radians(phi)
    cos, sin = math.cos(phi), math.sin(phi)
    dx, dy = (x0 - x1) / 2, (y0 - y1) / 2
    x1p, y1p = cos * dx + sin * dy, -sin * dx + cos * dy
    lam = (x1p**2) / (rx**2) + (y1p**2) / (ry**2)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    k = math.sqrt(max(0.0, num / den)) * (-1 if large == sweep else 1)
    cxp, cyp = k * rx * y1p / ry, -k * ry * x1p / rx
    cx = cos * cxp - sin * cyp + (x0 + x1) / 2
    cy = sin * cxp + cos * cyp + (y0 + y1) / 2

    def angle(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    t1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    out = []
    for i in range(1, steps + 1):
        t = t1 + dt * i / steps
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((cos * x - sin * y + cx, sin * x + cos * y + cy))
    return out


def subpaths(d: str) -> list[list[tuple[float, float]]]:
    """An SVG path's outlines, as points (the commands tp-word uses)."""
    tok = _tokens(d)
    i, cmd = 0, ""
    x = y = sx = sy = 0.0
    out: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []

    def num() -> float:
        nonlocal i
        i += 1
        return float(tok[i - 1])

    while i < len(tok):
        if re.fullmatch(r"[A-Za-z]", tok[i]):
            cmd = tok[i]
            i += 1
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            if cur:
                out.append(cur)
            cur = [(x, y)]
            sx, sy = x, y
            cmd = "l" if rel else "L"
        elif c == "L":
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            cur.append((x, y))
        elif c == "H":
            nx = num()
            x = x + nx if rel else nx
            cur.append((x, y))
        elif c == "V":
            ny = num()
            y = y + ny if rel else ny
            cur.append((x, y))
        elif c == "Q":
            qx, qy, nx, ny = num(), num(), num(), num()
            if rel:
                qx, qy, nx, ny = x + qx, y + qy, x + nx, y + ny
            for k in range(1, 17):
                t = k / 16
                cur.append(
                    (
                        (1 - t) ** 2 * x + 2 * (1 - t) * t * qx + t * t * nx,
                        (1 - t) ** 2 * y + 2 * (1 - t) * t * qy + t * t * ny,
                    )
                )
            x, y = nx, ny
        elif c == "A":
            rx, ry, phi, large, sweep, nx, ny = (num() for _ in range(7))
            if rel:
                nx, ny = x + nx, y + ny
            cur.extend(_arc(x, y, rx, ry, phi, int(large), int(sweep), nx, ny))
            x, y = nx, ny
        elif c == "Z":
            if cur:
                out.append(cur)
            cur = []
            x, y = sx, sy
        else:
            raise ValueError(f"Unknown path command {cmd}")
    if cur:
        out.append(cur)
    return out


def wordmark(scale: float, over: int = 4) -> tuple[Image.Image, tuple[float, float]]:
    """The wordmark's letters and ring in white (not its pearl, drawn with
    the flying ones), as an RGBA picture at `scale` pixels a unit; and where
    the ring's center is in it."""
    page = PAGE.read_text(encoding="utf-8")
    symbol = re.search(r'<symbol id="tp-word"[^>]*>(.*?)</symbol>', page, re.S)
    assert symbol, "index.html has no tp-word"
    tags = re.findall(r"<path [^>]*>", symbol[1])
    # (tp-word: translate(-0.6, 82.5); 472.7 by 99 units.)
    pad = 8
    size = (round(472.7 * scale) + 2 * pad, round(99 * scale) + 2 * pad)
    big = (size[0] * over, size[1] * over)
    filled = np.zeros((big[1], big[0]), dtype=bool)
    for tag in tags:
        if 'fill="currentColor"' not in tag:
            continue  # (the pearl: drawn with the flying ones)
        d = re.search(r'd="([^"]+)"', tag)
        assert d
        evenodd = 'fill-rule="evenodd"' in tag
        # Each outline's winding (+1 or -1 by its direction), added up: SVG's
        # nonzero rule, or its even-odd rule where the path asks for it.
        winding = np.zeros((big[1], big[0]), dtype=np.int16)
        for outline in subpaths(d[1]):
            points = [((px - 0.6) * scale * over + pad * over, (py + 82.5) * scale * over + pad * over)
                      for px, py in outline]  # fmt: skip
            one = Image.new("1", big, 0)
            ImageDraw.Draw(one).polygon(points, fill=1)
            area = sum(
                x0 * y1 - x1 * y0
                for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True)
            )
            winding += np.asarray(one, dtype=np.int16) * (1 if area > 0 else -1)
        filled |= (winding % 2 != 0) if evenodd else (winding != 0)
    mask = Image.fromarray((filled * 255).astype(np.uint8), "L")
    alpha = mask.resize(size, Image.Resampling.LANCZOS)
    art = Image.new("RGBA", size, (255, 255, 255, 0))
    art.putalpha(alpha)
    return art, (RING[0] * scale + pad, RING[1] * scale + pad)


# Drawing -----------------------------------------------------------------------------


def disc(
    frame: np.ndarray, cx: float, cy: float, r: float, color: np.ndarray, alpha: float
) -> None:
    """A filled circle, smooth at its edge, blended into `frame`."""
    if r <= 0 or alpha <= 0:
        return
    x0, x1 = max(0, int(cx - r - 2)), min(W, int(cx + r + 3))
    y0, y1 = max(0, int(cy - r - 2)), min(H, int(cy + r + 3))
    if x0 >= x1 or y0 >= y1:
        return
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    dist = np.sqrt((xs + 0.5 - cx) ** 2 + (ys + 0.5 - cy) ** 2)
    cover = np.clip(r + 0.5 - dist, 0.0, 1.0)[..., None] * alpha
    if r < 0.6:  # (smaller than a pixel: its area, not its edge)
        cover = cover * (r / 0.6) ** 2
    region = frame[y0:y1, x0:x1]
    region += (color - region) * cover


def blend(frame: np.ndarray, art: Image.Image, at: tuple[float, float], scale: float = 1.0) -> None:
    """`art` (RGBA), its top left at `at` (to the fraction of a pixel), scaled."""
    w, h = art.size
    sw, sh = math.ceil(w * scale) + 2, math.ceil(h * scale) + 2
    ox, oy = math.floor(at[0]), math.floor(at[1])
    fx, fy = at[0] - ox, at[1] - oy
    # (Inverse map: output pixel -> art pixel.)
    moved = art.transform(
        (sw, sh),
        Image.Transform.AFFINE,
        (1 / scale, 0, -fx / scale, 0, 1 / scale, -fy / scale),
        resample=Image.Resampling.BICUBIC,
    )
    rgba = np.asarray(moved, dtype=np.float32) / 255.0
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(W, ox + sw), min(H, oy + sh)
    if x0 >= x1 or y0 >= y1:
        return
    part = rgba[y0 - oy : y1 - oy, x0 - ox : x1 - ox]
    a = part[..., 3:4]
    region = frame[y0:y1, x0:x1]
    region += (part[..., :3] * 255.0 - region) * a


@dataclass
class Pearl:
    leaves: float  # when it starts its flight, in the loop
    angle: float  # where it passes the ring, around the logo's pearl
    drift: float  # how far across it travels, in the wordmark's units
    radius: float  # its size, in the wordmark's units, as it passes the ring


def pearls() -> list[Pearl]:
    rng = random.Random(1340)
    count = round(SECONDS / LEAVES)
    return [
        Pearl(i * LEAVES, i * GOLDEN, rng.uniform(13.0, 21.0), rng.uniform(3.6, 4.6))
        for i in range(count)
    ]


def ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


def frame_at(t: float, art: Image.Image, ring_at: tuple[float, float], scale: float,
             flying: list[Pearl]) -> tuple[np.ndarray, np.ndarray]:  # fmt: skip
    """The picture at `t`, and where the pearls in front are in it (0 to
    255: tapiOca puts them back over what it draws on the picture)."""
    frame = np.empty((H, W, 3), dtype=np.float32)
    frame[:] = INK
    front = np.zeros((H, W, 1), dtype=np.float32)
    turn = 2 * math.pi * t / SECONDS
    # The logo floats, gently (calm beside the text drawn over it: the
    # owner): a slow figure-eight, and breathes a little, each closing in
    # the loop.
    grow = 1.0 + 0.015 * math.sin(2 * turn + 0.6)
    cx = W / 2 + 50 * math.sin(turn)
    cy = 0.40 * H + 22 * math.sin(2 * turn + 0.9)
    s = scale * grow  # pixels a unit, at the ring
    ahead: list[tuple[float, float, float, float]] = []
    behind: list[tuple[float, float, float, float]] = []
    for p in flying:
        age = (t - p.leaves) % SECONDS
        if age >= FLIGHT:
            continue
        k = age / FLIGHT
        w = FAR * (NEAR / FAR) ** k  # how far it is, the ring's distance as 1
        ux, uy = math.cos(p.angle), math.sin(p.angle)
        # Its line through the gap: across from the far side to where it
        # passes the ring, then outward and past.
        lateral = (GAP + p.drift) / w - p.drift
        x, y = cx + s * lateral * ux, cy + s * lateral * uy
        r = s * p.radius / w
        fade = min(1.0, age / 0.7)
        # (Farther is dimmer, into the black.)
        near = min(1.0, 1.6 / w)
        color = INK + (TEAL - INK) * (0.18 + 0.82 * near)
        (behind if w > 1.0 else ahead).append((w, x, y, r, color, fade))  # type: ignore[arg-type]
    for _, x, y, r, color, fade in sorted(behind, key=lambda b: -b[0]):
        disc(frame, x, y, r, color, fade)
    blend(frame, art, (cx - ring_at[0] * grow, cy - ring_at[1] * grow), grow)
    disc(frame, cx, cy, s * PEARL, TEAL, 1.0)  # (the logo's own pearl)
    for _, x, y, r, color, fade in sorted(ahead, key=lambda b: -b[0]):
        disc(frame, x, y, r, color, fade)
        disc(front, x, y, r, np.array([255.0], dtype=np.float32), fade)
    # (The web address, bottom right, is drawn live with the time and date,
    # to line up with them: see app/ffmpeg.py's info_text. The owner.)
    return frame, front


def station_logo(path: Path, size: int = 512) -> None:
    """INFO's logo: tapiOca's mark (the ring and its pearl), on
    an Ink tile with round corners so it shows on light guides as on dark;
    512 pixels square, as the logo library's are."""
    over = 4
    big = size * over
    tile = Image.new("L", (big, big), 0)
    ImageDraw.Draw(tile).rounded_rectangle(
        (0, 0, big - 1, big - 1), radius=int(big * 0.22), fill=255
    )
    art = np.zeros((big, big, 4), dtype=np.float32)
    art[..., :3] = INK
    art[..., 3] = np.asarray(tile, dtype=np.float32) / 255.0
    yy, xx = np.mgrid[0:big, 0:big].astype(np.float32)
    dist = np.hypot(xx + 0.5 - big / 2, yy + 0.5 - big / 2)
    unit = big * 0.31 / RING_OUT  # (the ring's outside: 62% of the tile across)
    ring = (dist <= RING_OUT * unit) & (dist >= RING_IN * unit)
    art[ring, :3] = WHITE
    art[dist <= PEARL * unit, :3] = TEAL
    out = Image.fromarray(np.clip(art * [1, 1, 1, 255] + 0.5, 0, 255).astype(np.uint8), "RGBA")
    out.resize((size, size), Image.Resampling.LANCZOS).save(path, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--still", type=float, help="just this second, as a PNG")
    parser.add_argument("--seconds", type=float, default=SECONDS)
    parser.add_argument("--loops", type=int, default=LOOPS)
    parser.add_argument("--logo", action="store_true", help="the station's logo, as a PNG")
    args = parser.parse_args()
    if args.logo:
        station_logo(args.out)
        return
    scale = WORD_PX / 472.7
    art, ring_at = wordmark(scale)
    flying = pearls()
    if args.still is not None:
        frame, front = frame_at(args.still, art, ring_at, scale, flying)
        Image.fromarray(np.clip(frame + 0.5, 0, 255).astype(np.uint8)).save(args.out)
        Image.fromarray(np.clip(front[..., 0] + 0.5, 0, 255).astype(np.uint8), "L").save(
            args.out.with_name(args.out.stem + "-front.png")
        )
        return
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frames = round(args.seconds * FPS)
    import music  # (beside this: the tune, timed to the pearls)

    # (Drawn at 1080p, kept at 720p, the size stations start at: smoother
    # edges, and a smaller file. Its colors as bt709 says, so the teal stays
    # the logo's.)
    scaled = f"scale={OUT_W}:{OUT_H}:flags=lanczos"
    with tempfile.TemporaryDirectory() as tmp:
        one, where, tune = Path(tmp) / "one.mp4", Path(tmp) / "front.mp4", Path(tmp) / "tune.wav"
        music.write(tune)
        raw = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-s", f"{W}x{H}",
               "-r", str(FPS)]  # fmt: skip
        picture_args = [
            *raw, "-pix_fmt", "rgb24", "-i", "-",
            "-vf", f"{scaled}:out_color_matrix=bt709:out_range=tv",
            "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-tune", "animation",
            "-pix_fmt", "yuv420p", "-g", str(FPS * 2), "-colorspace", "bt709",
            "-color_primaries", "bt709", "-color_trc", "bt709", str(one),
        ]  # fmt: skip
        picture = subprocess.Popen(picture_args, stdin=subprocess.PIPE)
        # Where the pearls in front are: in gray, full range (white: a pearl).
        front_args = [
            *raw, "-pix_fmt", "gray", "-i", "-", "-vf", scaled,
            "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "gray",
            "-color_range", "pc", "-g", str(FPS * 2), str(where),
        ]  # fmt: skip
        in_front = subprocess.Popen(front_args, stdin=subprocess.PIPE)
        assert picture.stdin is not None and in_front.stdin is not None
        for n in range(frames):
            frame, front = frame_at(n / FPS, art, ring_at, scale, flying)
            picture.stdin.write(np.clip(frame + 0.5, 0, 255).astype(np.uint8).tobytes())
            in_front.stdin.write(np.clip(front + 0.5, 0, 255).astype(np.uint8).tobytes())
            if n % 150 == 0:
                print(f"{n}/{frames}", file=sys.stderr)
        picture.stdin.close()
        in_front.stdin.close()
        if picture.wait() or in_front.wait():
            raise SystemExit("ffmpeg couldn't make the picture")
        loops = args.loops
        mux = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-stream_loop", str(loops - 1), "-i", str(one),
            "-stream_loop", str(loops - 1), "-i", str(where),
            "-stream_loop", str(loops - 1), "-i", str(tune),
            "-map", "0:v", "-map", "1:v", "-map", "2:a", "-c:v", "copy",
            "-disposition:v:0", "default", "-disposition:v:1", "0",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-t", f"{loops * frames / FPS:.3f}", "-movflags", "+faststart", str(args.out),
        ]  # fmt: skip
        subprocess.run(mux, check=True)


if __name__ == "__main__":
    main()
