"""Renders some of the logos (with a cache, so only changed ones are drawn
again) and lays them out on contact sheets for checking.

    python review.py OUT_DIR MODULE [FILTER] [--light] [--cols N] [--cell PX]

MODULE is networks, genres, themes, letters or symbol_sheet; FILTER keeps
the logos whose id contains any of its comma-separated words.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

from kit import Renderer
from PIL import Image, ImageDraw, ImageFont

CACHE = Path(__file__).resolve().parent / ".cache" / "review"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def render(logos, renderer=None) -> dict[str, Path]:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    r = renderer
    for logo in logos:
        s = logo.draw()
        key = hashlib.sha1(s.encode()).hexdigest()[:16]
        path = CACHE / f"{key}.png"
        if not path.exists():
            if r is None:
                r = Renderer()
            path.write_bytes(r.png(s))
        out[logo.id] = path
    if r is not None and renderer is None:
        r.close()
    return out


def sheet(logos, paths, dest: Path, bg=(24, 26, 32), fg=(200, 200, 210), cols=8, cell=160) -> None:
    rows = (len(logos) + cols - 1) // cols
    im = Image.new("RGB", (cols * cell, rows * (cell + 22)), bg)
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(FONT, 12)
    for i, logo in enumerate(logos):
        x, y = (i % cols) * cell, (i // cols) * (cell + 22)
        lg = Image.open(paths[logo.id]).resize((cell - 12, cell - 12), Image.LANCZOS)
        im.paste(lg, (x + 6, y + 6), lg)
        name = logo.name if len(logo.name) < 26 else logo.name[:25] + "…"
        d.text((x + cell // 2, y + cell + 3), name, fill=fg, font=font, anchor="mt")
    im.save(dest)


def main() -> None:
    flags = sys.argv[1:]
    args, skip = [], False
    for a in flags:
        if skip:
            skip = False
        elif a in ("--cols", "--cell"):
            skip = True
        elif not a.startswith("--"):
            args.append(a)
    out = Path(args[0])
    out.mkdir(parents=True, exist_ok=True)
    mod = importlib.import_module(args[1])
    logos = mod.logos()
    if len(args) > 2:
        wanted = args[2].split(",")
        logos = [l for l in logos if any(w in l.id for w in wanted)]
    cols = int(flags[flags.index("--cols") + 1]) if "--cols" in flags else 8
    cell = int(flags[flags.index("--cell") + 1]) if "--cell" in flags else 160
    paths = render(logos)
    per = cols * 6
    for n in range(0, len(logos), per):
        chunk = logos[n : n + per]
        sheet(chunk, paths, out / f"{args[1]}_{n // per + 1}.png", cols=cols, cell=cell)
        if "--light" in flags:
            sheet(
                chunk,
                paths,
                out / f"{args[1]}_{n // per + 1}_light.png",
                bg=(236, 236, 232),
                fg=(50, 50, 50),
                cols=cols,
                cell=cell,
            )
    print(len(logos), "logos")


if __name__ == "__main__":
    main()
