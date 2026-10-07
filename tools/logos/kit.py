"""The drawing kit for StationPlay's logo library: SVG helpers, and a
renderer (Chromium, through Playwright) that turns each logo's SVG into a
512x512 PNG with a clear background.

Fonts are open-licensed (SIL Open Font License or Apache 2.0), installed
from npm into node_modules/ here by `npm ci`; they're only used to draw the
PNGs, which are what StationPlay ships.
"""

from __future__ import annotations

import io
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONTS = HERE / "node_modules" / "@fontsource"
SIZE = 512
SCALE = 2  # drawn at twice the size, then reduced, for clean edges
C = 256  # the middle


@dataclass
class Logo:
    id: str
    name: str
    category: str
    draw: Callable[[], str]
    tags: list[str] = field(default_factory=list)


def font_css() -> str:
    """@font-face rules for every font installed (Latin letters only)."""
    rules = []
    for pkg in sorted(FONTS.iterdir()):
        meta = json.loads((pkg / "metadata.json").read_text())
        for weight in meta["weights"]:
            for style in meta["styles"]:
                f = pkg / "files" / f"{meta['id']}-latin-{weight}-{style}.woff2"
                if f.exists():
                    rules.append(
                        f"@font-face{{font-family:'{meta['family']}';font-style:{style};"
                        f"font-weight:{weight};src:url('/fonts/{pkg.name}/files/{f.name}') format('woff2');}}"
                    )
    return "\n".join(rules)


_FAMILIES: dict[str, str] = {}


def measure(s: str, family: str, weight: int = 400, style: str = "normal", size: float = 100):
    """(advance width, (x0, y0, x1, y1) ink box from the baseline) of `s`
    in a font, at `size` - for placing things beside a word."""
    from PIL import ImageFont

    if not _FAMILIES:
        for pkg in FONTS.iterdir():
            meta = json.loads((pkg / "metadata.json").read_text())
            _FAMILIES[meta["family"]] = meta["id"]
    fid = _FAMILIES[family]
    f = ImageFont.truetype(str(FONTS / fid / "files" / f"{fid}-latin-{weight}-{style}.woff"), 1000)
    k = size / 1000
    x0, y0, x1, y1 = f.getbbox(s, anchor="ls")
    return f.getlength(s) * k, (x0 * k, y0 * k, x1 * k, y1 * k)


# ---------------------------------------------------------------- SVG pieces


def svg(body: str, defs: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{SIZE}" height="{SIZE}" viewBox="0 0 {SIZE} {SIZE}">'
        f"<defs>{defs}</defs>{body}</svg>"
    )


def fit(
    inner: str, x: float, y: float, w: float, h: float, anchor: str = "", most: float | None = None
) -> str:
    """`inner` scaled (keeping its shape) and centred to fill the box, by
    what it actually draws. anchor: top/bottom/left/right pins it to a side."""
    extra = f' data-anchor="{anchor}"' if anchor else ""
    if most:
        extra += f' data-max="{most}"'
    return f'<g class="fit" data-box="{x} {y} {w} {h}"{extra}>{inner}</g>'


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(
    s: str,
    font: str,
    size: float = 100,
    weight: int = 400,
    fill: str = "#fff",
    x: float = 0,
    y: float = 0,
    anchor: str = "middle",
    ls: float = 0,
    style: str = "normal",
    stroke: str | None = None,
    sw: float = 0,
    extra: str = "",
) -> str:
    st = (
        f' stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round" paint-order="stroke"'
        if stroke
        else ""
    )
    spacing = f' letter-spacing="{ls}"' if ls else ""
    return (
        f'<text x="{x}" y="{y}" font-family="\'{font}\'" font-size="{size}" font-weight="{weight}" '
        f'font-style="{style}" text-anchor="{anchor}" fill="{fill}"{spacing}{st} {extra}>{esc(s)}</text>'
    )


def arc_text(
    s: str,
    font: str,
    cx: float,
    cy: float,
    r: float,
    size: float,
    weight: int = 400,
    fill: str = "#fff",
    ls: float = 0,
    bottom: bool = False,
    pid: str = "arc",
    stroke: str | None = None,
    sw: float = 0,
    start: float = 50,
) -> tuple[str, str]:
    """Text along a circle (over the top, or under the bottom reading left
    to right); returns (defs, body)."""
    if bottom:
        d = f"M{cx - r},{cy} A{r},{r} 0 0 0 {cx + r},{cy}"
    else:
        d = f"M{cx - r},{cy} A{r},{r} 0 0 1 {cx + r},{cy}"
    st = (
        f' stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round" paint-order="stroke"'
        if stroke
        else ""
    )
    spacing = f' letter-spacing="{ls}"' if ls else ""
    hang = ' dominant-baseline="hanging"' if bottom else ""
    body = (
        f'<text font-family="\'{font}\'" font-size="{size}" font-weight="{weight}" fill="{fill}"{spacing}{st}>'
        f'<textPath href="#{pid}" startOffset="{start}%" text-anchor="middle"{hang}>{esc(s)}</textPath></text>'
    )
    return f'<path id="{pid}" d="{d}" fill="none"/>', body


def pts(points) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def star(cx, cy, r_out, r_in, n=5, rot=-90) -> str:
    out = []
    for k in range(n * 2):
        r = r_out if k % 2 == 0 else r_in
        a = math.radians(rot + k * 180 / n)
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts(out)


def poly(cx, cy, r, n, rot=-90) -> str:
    return pts(
        (
            cx + r * math.cos(math.radians(rot + k * 360 / n)),
            cy + r * math.sin(math.radians(rot + k * 360 / n)),
        )
        for k in range(n)
    )


def lin(id_: str, stops, x1=0, y1=0, x2=0, y2=1, user=False) -> str:
    s = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in stops)
    units = ' gradientUnits="userSpaceOnUse"' if user else ""
    return f'<linearGradient id="{id_}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"{units}>{s}</linearGradient>'


def rad(id_: str, stops, cx=0.5, cy=0.5, r=0.5, fx=None, fy=None, user=False) -> str:
    s = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in stops)
    f = f' fx="{fx}" fy="{fy}"' if fx is not None else ""
    units = ' gradientUnits="userSpaceOnUse"' if user else ""
    return f'<radialGradient id="{id_}" cx="{cx}" cy="{cy}" r="{r}"{f}{units}>{s}</radialGradient>'


def shadow(id_: str = "sh", dx=0, dy=6, blur=6, opacity=0.45, color="#000") -> str:
    return (
        f'<filter id="{id_}" x="-30%" y="-30%" width="160%" height="160%">'
        f'<feDropShadow dx="{dx}" dy="{dy}" stdDeviation="{blur}" flood-color="{color}" flood-opacity="{opacity}"/></filter>'
    )


def glow(id_: str, color: str, blur=8, strength=2) -> str:
    merges = "".join('<feMergeNode in="g"/>' for _ in range(strength))
    return (
        f'<filter id="{id_}" x="-50%" y="-50%" width="200%" height="200%">'
        f'<feGaussianBlur in="SourceAlpha" stdDeviation="{blur}" result="b"/>'
        f'<feFlood flood-color="{color}"/><feComposite in2="b" operator="in" result="g"/>'
        f'<feMerge>{merges}<feMergeNode in="SourceGraphic"/></feMerge></filter>'
    )


def rough(id_: str, amount=3, freq=0.9, seed=3) -> str:
    """Worn, stamped edges (for ink stamps and old print)."""
    return (
        f'<filter id="{id_}" x="-5%" y="-5%" width="110%" height="110%">'
        f'<feTurbulence type="fractalNoise" baseFrequency="{freq}" numOctaves="2" seed="{seed}" result="n"/>'
        f'<feDisplacementMap in="SourceGraphic" in2="n" scale="{amount}" xChannelSelector="R" yChannelSelector="G"/></filter>'
    )


def worn(id_: str, freq=0.05, cut=0.62, seed=5) -> str:
    """Patchy ink: bits of the shape missing, like a rubber stamp."""
    return (
        f'<filter id="{id_}" x="0" y="0" width="100%" height="100%">'
        f'<feTurbulence type="fractalNoise" baseFrequency="{freq}" numOctaves="3" seed="{seed}" result="n"/>'
        f'<feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -2.2 {cut * 2.2 + 0.4}" result="m"/>'
        f'<feComposite in="SourceGraphic" in2="m" operator="in"/></filter>'
    )


def solid(inner: str, color: str) -> str:
    """`inner` with every fill and stroke made `color` (for shadows and
    block extrusions)."""
    return re.sub(r'(fill|stroke)="(?!none)[^"]*"', lambda m: f'{m.group(1)}="{color}"', inner)


def extrude(inner: str, dx: float, dy: float, steps: int, color: str) -> str:
    """A solid block shadow behind `inner`: its shape repeated, stepping away."""
    shape = solid(inner, color)
    return "".join(
        f'<g transform="translate({dx * k / steps:.2f} {dy * k / steps:.2f})">{shape}</g>'
        for k in range(steps, 0, -1)
    )


def tilt(inner: str, deg: float) -> str:
    return f'<g transform="rotate({deg})">{inner}</g>'


def skew(inner: str, deg: float) -> str:
    return f'<g transform="skewX({deg})">{inner}</g>'


def at(inner: str, x: float, y: float, s: float = 1, rot: float = 0) -> str:
    r = f" rotate({rot})" if rot else ""
    return f'<g transform="translate({x} {y}){r} scale({s})">{inner}</g>'


def ribbon(x1, x2, y, h, fill, edge="none", tail=None, tail_fill=None, sw=0, notch=18) -> str:
    """A banner from x1 to x2 (height h, top at y), with forked tails."""
    t = tail if tail is not None else h * 0.9
    tf = tail_fill or fill
    y + h / 2
    body = ""
    if t:
        body += (
            f'<path d="M{x1 - t} {y + h * 0.28} L{x1 + 6} {y + h * 0.28} L{x1 + 6} {y + h * 1.28} L{x1 - t} {y + h * 1.28} L{x1 - t + notch} {y + h * 0.78} Z" fill="{tf}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
            f'<path d="M{x2 + t} {y + h * 0.28} L{x2 - 6} {y + h * 0.28} L{x2 - 6} {y + h * 1.28} L{x2 + t} {y + h * 1.28} L{x2 + t - notch} {y + h * 0.78} Z" fill="{tf}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
        )
    body += f'<rect x="{x1}" y="{y}" width="{x2 - x1}" height="{h}" fill="{fill}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
    return body


def banner(x1, x2, y, h, fill, edge="none", sw=0, cut=16) -> str:
    """A flat banner with notched ends."""
    m = y + h / 2
    return (
        f'<path d="M{x1} {y} L{x2} {y} L{x2 - cut} {m} L{x2} {y + h} L{x1} {y + h} L{x1 + cut} {m} Z" '
        f'fill="{fill}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
    )


# ---------------------------------------------------------------- rendering

READY_JS = """async () => {
  document.body.offsetHeight;
  await document.fonts.ready;
  const bad = [];
  document.fonts.forEach(f => { if (f.status === 'error') bad.push(f.family + ' ' + f.weight); });
  return [bad, document.querySelectorAll('g.fit').length];
}"""

# Shows one fitted group on its own, big and centred, to measure what it draws.
ALONE_JS = """(i) => {
  const g = document.querySelectorAll('g.fit')[i];
  const svg = document.querySelector('svg');
  svg.style.visibility = 'hidden';
  g.style.visibility = 'visible';
  g.removeAttribute('transform');
  const b = g.getBBox();
  const s = Math.min(330 / b.width, 330 / b.height);
  const tx = 256 - (b.x + b.width / 2) * s, ty = 256 - (b.y + b.height / 2) * s;
  // Drawn big and upright on the page whatever its parents do (rotate,
  // scale), so what it draws can be measured in its own units.
  const T = svg.createSVGMatrix().translate(tx, ty).scale(s);
  const P = g.parentNode === svg ? svg.createSVGMatrix() : g.parentNode.getCTM();
  const M = P.inverse().multiply(T);
  g.setAttribute('transform', `matrix(${M.a} ${M.b} ${M.c} ${M.d} ${M.e} ${M.f})`);
  return [tx, ty, s];
}"""

PLACE_JS = """([i, ink]) => {
  const g = document.querySelectorAll('g.fit')[i];
  document.querySelector('svg').style.visibility = '';
  g.style.visibility = '';
  const [x, y, w, h] = g.dataset.box.split(' ').map(Number);
  const [x0, y0, x1, y1] = ink;
  const bw = x1 - x0, bh = y1 - y0;
  let s = Math.min(w / bw, h / bh);
  if (g.dataset.max) s = Math.min(s, Number(g.dataset.max));
  const a = g.dataset.anchor || '';
  let tx = x + (w - bw * s) / 2 - x0 * s;
  let ty = y + (h - bh * s) / 2 - y0 * s;
  if (a.includes('bottom')) ty = y + h - y1 * s;
  if (a.includes('top')) ty = y - y0 * s;
  if (a.includes('left')) tx = x - x0 * s;
  if (a.includes('right')) tx = x + w - x1 * s;
  g.setAttribute('transform', `translate(${tx} ${ty}) scale(${s})`);
}"""


SYSTEM_FONTS = {"Noto Sans CJK JP", "DejaVu Sans"}


def families() -> set[str]:
    return {
        json.loads((p / "metadata.json").read_text())["family"] for p in FONTS.iterdir()
    } | SYSTEM_FONTS


class Renderer:
    def __init__(self) -> None:
        from playwright.sync_api import sync_playwright

        self._p = sync_playwright().start()
        self._browser = self._p.chromium.launch()
        self._css = font_css()
        self._families = families()
        self._html = ""
        self._page = self._new_page(SIZE, SIZE, SCALE)

    def _new_page(self, w: int, h: int, scale: int):
        page = self._browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)

        def serve(route):
            path = route.request.url.split("logo.local", 1)[1].split("?")[0]
            if path.startswith("/fonts/"):
                route.fulfill(path=str(FONTS / path[len("/fonts/") :]), content_type="font/woff2")
            else:
                route.fulfill(body=self._html, content_type="text/html; charset=utf-8")

        page.route("https://logo.local/**", serve)
        return page

    def _show(self, page, html: str) -> None:
        self._html = html
        page.goto("https://logo.local/page")

    def png(self, svg_text: str) -> bytes:
        """The logo as a 512x512 RGBA PNG (uncompressed palette-wise)."""
        from PIL import Image

        page = self._page
        used = set(re.findall(r"font-family=\"'?([^\"']+)'?\"", svg_text))
        unknown = used - self._families
        if unknown:
            raise RuntimeError(f"fonts not installed: {sorted(unknown)}")
        self._show(
            page,
            f'<html><head><meta charset="utf-8"><style>{self._css} html,body{{margin:0;background:transparent}}'
            f"svg{{display:block}}</style></head><body>{svg_text}</body></html>",
        )
        bad, count = page.evaluate(READY_JS)
        if bad:
            raise RuntimeError(f"fonts didn't load: {bad}")
        clip = {"x": 0, "y": 0, "width": SIZE, "height": SIZE}
        for i in reversed(range(count)):
            tx, ty, s = page.evaluate(ALONE_JS, i)
            shot = Image.open(io.BytesIO(page.screenshot(omit_background=True, clip=clip)))
            box = shot.getchannel("A").point(lambda a: 255 if a > 24 else 0).getbbox()
            if box is None:
                raise RuntimeError("a fitted group draws nothing")
            k = shot.size[0] / SIZE
            ink = [
                (box[0] / k - tx) / s,
                (box[1] / k - ty) / s,
                (box[2] / k - tx) / s,
                (box[3] / k - ty) / s,
            ]
            page.evaluate(PLACE_JS, [i, ink])
        im = Image.open(io.BytesIO(page.screenshot(omit_background=True, clip=clip))).convert(
            "RGBA"
        )
        if im.size != (SIZE, SIZE):
            im = im.resize((SIZE, SIZE), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "PNG")
        return out.getvalue()

    def html_png(self, html: str, w: int, h: int, scale: int = 1) -> bytes:
        page = self._new_page(w, h, scale)
        self._show(
            page,
            f'<html><head><meta charset="utf-8"><style>{self._css} html,body{{margin:0}}</style></head><body>{html}</body></html>',
        )
        page.evaluate("async () => { document.body.offsetHeight; await document.fonts.ready; }")
        page.wait_for_timeout(150)
        raw = page.screenshot(full_page=True)
        page.close()
        return raw

    def close(self) -> None:
        self._browser.close()
        self._p.stop()


def compress(png: bytes) -> bytes:
    """A much smaller PNG that looks the same: a palette of up to 256
    colours with transparency, lightly dithered."""
    import imagequant
    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGBA")
    q = imagequant.quantize_pil_image(im, dithering_level=1.0, max_quality=95, min_quality=70)
    out = io.BytesIO()
    q.save(out, "PNG", optimize=True)
    return out.getvalue()
