"""Makes the icons for installing StationPlay's page as an app (listed in
app/web/manifest.webmanifest): StationPlay's mark at 192 and 512 pixels on
white, as apple-touch-icon.png has it, and a 512-pixel maskable one on the
page's dark background, with the mark well inside the maskable safe zone
(a circle 80% as wide as the icon), so any shape a phone cuts it to shows
all of it. Chromium draws them (through Playwright), so the mark's curves
are the page's own, at the exact sizes.

    pip install playwright pillow       (and: python -m playwright install chromium)
    python tools/app_icons.py
"""

from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

WEB = Path(__file__).resolve().parent.parent / "app" / "web"

# StationPlay's mark, as in the page's favicon: its outline, and the green inside.
VIEW_W, VIEW_H = 85.55, 100
OUTLINE = (
    "M3.14 87.74L3.14 12.26A9.12 9.12 0 0 1 17.06 4.5L78.09 42.24A9.12 9.12 0 0 1 78.09 57.76"
    "L17.06 95.5A9.12 9.12 0 0 1 3.14 87.74Z"
)
INSIDE = (
    "M12.56 82.53L12.56 17.47A2.61 2.61 0 0 1 16.53 15.25L69.15 47.78A2.61 2.61 0 0 1 69.15 52.22"
    "L16.53 84.75A2.61 2.61 0 0 1 12.56 82.53Z"
)
OUTLINE_WIDTH = 6.28
GREEN = "#0ea609"  # (--brand)
# How far the mark reaches from its middle, at most (its outline's two
# left-hand corners): 12.26 from each corner's center, which is 30.515 and
# 37.74 from the middle.
REACH = math.hypot(VIEW_W / 2 - 12.26, VIEW_H / 2 - 12.26) + 12.26

# (file, size, background, outline, the mark's height as a share of the icon)
ICONS = (
    # As apple-touch-icon.png: black on white, the mark 118 of 180 pixels high.
    ("icon-192.png", 192, "#ffffff", "#000000", 118 / 180),
    ("icon-512.png", 512, "#ffffff", "#000000", 118 / 180),
    # On the page's dark background (--bg), in its dark ink (--ink).
    ("icon-maskable-512.png", 512, "#11161b", "#e9ecef", 1 / 2),
)


def svg(size: int, background: str, outline: str, share: float) -> str:
    """The icon, the mark's height a whole number of pixels and its corner
    on a whole pixel, so its edges are crisp."""
    height = round(size * share)
    scale = height / VIEW_H
    x, y = round((size - VIEW_W * scale) / 2), round((size - height) / 2)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}"><rect width="{size}" height="{size}" fill="{background}"/>'
        f'<g transform="translate({x} {y}) scale({scale})">'
        f'<path d="{OUTLINE}" fill="none" stroke="{outline}" stroke-width="{OUTLINE_WIDTH}"/>'
        f'<path d="{INSIDE}" fill="{GREEN}"/></g></svg>'
    )


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(device_scale_factor=1)
        for name, size, background, outline, share in ICONS:
            if name.startswith("icon-maskable"):
                assert REACH * size * share / VIEW_H <= 0.4 * size, "outside the safe zone"
            page.set_viewport_size({"width": size, "height": size})
            page.set_content(
                f"<body style='margin:0'>{svg(size, background, outline, share)}</body>"
            )
            shot = page.screenshot(clip={"x": 0, "y": 0, "width": size, "height": size})
            icon = Image.open(io.BytesIO(shot)).convert("RGB")
            assert icon.size == (size, size)
            icon.save(WEB / name, optimize=True)
            print(f"Wrote app/web/{name}")
        browser.close()


if __name__ == "__main__":
    main()
