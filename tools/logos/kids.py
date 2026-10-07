"""Kids' and family channels: preschool, big kids, kids' movies and family
nights. Invented brands, bright and rounded but finished like real kids'
networks (clean shapes, depth, confident lettering); none borrows a real
network's name, mark, character or lettering."""

from __future__ import annotations

import math
import random
import re

import symbols as S
from kit import (
    Logo,
    arc_text,
    extrude,
    fit,
    lin,
    measure,
    pts,
    rad,
    rough,
    shadow,
    star,
    svg,
    text,
)
from symbols import P, centred

SH = shadow("sh", dy=6, blur=6, opacity=0.45)
SOFT = shadow("soft", dy=3, blur=3, opacity=0.35)
KIDS = "Kids & family"
KIDS_LOGOS: list[tuple[str, str, str, list[str], object]] = []  # (id, name, category, tags, draw)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", "and")).strip("-")


def kid(name: str, *tags: str):
    def add(fn):
        KIDS_LOGOS.append((slug(name), name, KIDS, list(tags), fn))
        return fn

    return add


# ======================================================================= helpers


def pop(
    s: str,
    font: str,
    fill: str,
    edge: str,
    *,
    sw: float = 14,
    weight: int = 400,
    ls: float = 0,
    style: str = "normal",
    depth: float = 0,
    slant: float = 0.0,
    deep: str | None = None,
    outer: str | None = None,
    osw: float = 10,
    x: float = 0,
    y: float = 0,
    anchor: str = "middle",
) -> str:
    """A kids'-network word: outlined, with an optional block extrusion
    (`depth` down, `slant` of it sideways) and an optional outer sticker
    outline (`outer`) around the whole thing."""
    kw = {"weight": weight, "ls": ls, "style": style, "x": x, "y": y, "anchor": anchor}
    core = text(s, font, 100, fill=fill, stroke=edge, sw=sw, **kw)
    steps = max(4, min(10, int(depth)))
    out = ""
    if outer:
        o = text(s, font, 100, fill=outer, stroke=outer, sw=sw + 2 * osw, **kw)
        if depth:
            out += extrude(o, slant * depth, depth, steps, outer)
        out += o
    if depth:
        out += extrude(core, slant * depth, depth, steps, deep or edge)
    return out + core


def shine(i: str, light: str, base: str, dark: str, horizontal: bool = False) -> str:
    """A glossy three-stop gradient (light top, main middle, darker foot)."""
    if horizontal:
        return lin(i, [(0, light), (0.5, base), (1, dark)], x2=1, y2=0)
    return lin(i, [(0, light), (0.55, base), (1, dark)])


def smooth(points, t: float = 1 / 6) -> str:
    """A closed smooth path through the points (Catmull-Rom)."""
    n = len(points)
    d = f"M{points[0][0]:.1f} {points[0][1]:.1f}"
    for i in range(n):
        p0, p1, p2, p3 = points[i - 1], points[i], points[(i + 1) % n], points[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) * t, p1[1] + (p2[1] - p0[1]) * t)
        c2 = (p2[0] - (p3[0] - p1[0]) * t, p2[1] - (p3[1] - p1[1]) * t)
        d += f" C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} {p2[0]:.1f} {p2[1]:.1f}"
    return d + "Z"


def blob(cx, cy, r, n=12, amp=0.12, seed=1, sx=1.0, sy=1.0) -> str:
    rng = random.Random(seed)
    p = []
    for k in range(n):
        a = 2 * math.pi * k / n
        rr = r * (1 + rng.uniform(-amp, amp))
        p.append((cx + rr * math.cos(a) * sx, cy + rr * math.sin(a) * sy))
    return smooth(p)


def puff(circles, fill: str, edge: str, sw: float = 8, rects=()) -> str:
    """Overlapping circles (and rounded rects) read as one puffy shape with
    a single outline: a cloud, a pillow edge, a bouncy castle."""
    s = "".join(
        f'<circle cx="{x}" cy="{y}" r="{r}" fill="{edge}" stroke="{edge}" stroke-width="{sw * 2}"/>'
        for x, y, r in circles
    )
    s += "".join(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{edge}" stroke="{edge}" stroke-width="{sw * 2}"/>'
        for x, y, w, h, rx in rects
    )
    s += "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}"/>' for x, y, r in circles)
    s += "".join(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"/>'
        for x, y, w, h, rx in rects
    )
    return s


def sparkle(x, y, r, fill="#fff", edge=None, sw=0) -> str:
    """A four-point twinkle."""
    k = r * 0.28
    d = (
        f"M{x} {y - r} Q{x + k} {y - k} {x + r} {y} Q{x + k} {y + k} {x} {y + r} "
        f"Q{x - k} {y + k} {x - r} {y} Q{x - k} {y - k} {x} {y - r} Z"
    )
    st = f' stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"' if edge else ""
    return f'<path d="{d}" fill="{fill}"{st}/>'


def starp(x, y, r, fill, edge, sw=5, inner=0.48, rot=-90) -> str:
    return f'<polygon points="{star(x, y, r, r * inner, 5, rot)}" fill="{fill}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'


def gleam(x, y, rx, ry, rot=-20, op=0.45) -> str:
    """A soft white highlight (the gloss on a plastic toy)."""
    return f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="#fff" opacity="{op}" transform="rotate({rot} {x} {y})"/>'


def pill(x, y, w, h, fill, edge, sw=8, rx=None) -> str:
    r = h / 2 if rx is None else rx
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{edge}" stroke-width="{sw}"/>'


def ribbon(x1, x2, y, h, fill, dark, edge, sw=6, tail=46, drop=22) -> str:
    """A banner with folded, forked tails behind each end."""
    m = y + drop + h / 2
    s = ""
    for side in (-1, 1):
        xo = x1 if side < 0 else x2
        xt = xo + side * tail
        s += (
            f'<path d="M{xo - side * 30} {y + drop} L{xt} {y + drop} L{xt - side * 18} {m} L{xt} {y + drop + h} '
            f'L{xo - side * 30} {y + drop + h} Z" fill="{dark}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
        )
        s += f'<path d="M{xo} {y + h} L{xo - side * 30} {y + drop + h} L{xo - side * 30} {y + h} Z" fill="{edge}" opacity=".55"/>'
    s += f'<rect x="{x1}" y="{y}" width="{x2 - x1}" height="{h}" rx="6" fill="{fill}" stroke="{edge}" stroke-width="{sw}"/>'
    return s


def crescent_path(cx, cy, r, ox, oy, r2) -> str:
    """The part of circle (cx,cy,r) outside circle (cx+ox, cy+oy, r2)."""
    d = math.hypot(ox, oy)
    a = (r * r - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r * r - a * a, 0))
    ux, uy = ox / d, oy / d
    px, py = cx + a * ux, cy + a * uy
    i1 = (px - h * uy, py + h * ux)
    i2 = (px + h * uy, py - h * ux)
    return (
        f"M{i1[0]:.1f} {i1[1]:.1f} A{r} {r} 0 1 1 {i2[0]:.1f} {i2[1]:.1f} "
        f"A{r2} {r2} 0 0 0 {i1[0]:.1f} {i1[1]:.1f} Z"
    )


def word_row(s: str, font: str, fills, edge, *, weight=400, sw=12, dy=None, gap=0.0, depth=0):
    """Letters placed one by one (each its own colour, optional bounce)."""
    out, x = "", 0.0
    for i, ch in enumerate(s):
        adv, _ = measure(ch, font, weight)
        if ch == " ":
            x += adv
            continue
        y = dy[i % len(dy)] if dy else 0
        out += pop(
            ch,
            font,
            fills[i % len(fills)],
            edge,
            sw=sw,
            weight=weight,
            x=x + adv / 2,
            y=y,
            depth=depth,
        )
        x += adv + gap
    return out


# ======================================================================= drawings (200 box)


def sippy(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"'
    s = ""
    for side in (-1, 1):
        d = f"M{100 + side * 44} 96 C{100 + side * 94} 92 {100 + side * 94} 156 {100 + side * 40} 152"
        s += f'<path d="{d}" fill="none" stroke="{p.k}" stroke-width="28" stroke-linecap="round"/>'
        s += f'<path d="{d}" fill="none" stroke="{p.b}" stroke-width="16" stroke-linecap="round"/>'
        s += f'<path d="{d}" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" opacity=".6" transform="translate(0 -4)"/>'
    cup = "M48 76 L152 76 L142 178 Q140 194 122 194 L78 194 Q60 194 58 178 Z"
    s += f'<clipPath id="cupc"><path d="{cup}"/></clipPath>'
    s += f'<path d="{cup}" fill="{p.l}"/>'
    s += (
        f'<g clip-path="url(#cupc)"><path d="M40 124 Q70 112 100 124 T160 124 L160 200 L40 200 Z" fill="{p.a}"/>'
        f'<path d="M40 124 Q70 112 100 124 T160 124" fill="none" stroke="#fff" stroke-width="4" opacity=".6"/>'
        '<rect x="64" y="86" width="13" height="96" rx="6.5" fill="#fff" opacity=".7"/>'
        '<circle cx="118" cy="150" r="6" fill="#fff" opacity=".6"/><circle cx="104" cy="170" r="4" fill="#fff" opacity=".6"/></g>'
    )
    s += f'<path d="{cup}" fill="none" {o}/>'
    s += f'<path d="M86 44 L90 10 Q100 2 110 10 L114 44 Z" fill="{p.c}" {o}/>'
    s += f'<path d="M50 64 Q100 22 150 64 Z" fill="{p.c}" {o}/>'
    s += f'<rect x="40" y="58" width="120" height="26" rx="12" fill="{p.c}" {o}/>'
    s += '<rect x="52" y="63" width="60" height="7" rx="3.5" fill="#fff" opacity=".45"/>'
    s += '<path d="M72 50 Q90 36 112 36" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".45"/>'
    return s


def boot(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round"'
    b = "M40 30 L104 30 L106 128 Q150 130 162 158 L164 172 L34 172 L36 30 Z"
    s = f'<path d="{b}" fill="{p.a}" {o}/>'
    s += f'<rect x="30" y="18" width="82" height="26" rx="10" fill="{p.b}" {o}/>'
    s += f'<path d="M30 172 L166 172 L166 180 Q166 190 156 190 L40 190 Q30 190 30 180 Z" fill="{p.c}" {o}/>'
    s += '<rect x="50" y="52" width="12" height="96" rx="6" fill="#fff" opacity=".55"/>'
    s += '<path d="M118 142 Q142 144 150 158" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity=".5"/>'
    return s


def bear_head(p: P) -> str:
    """A stitched plush bear's head (a, main fur; b, muzzle; c, ear felt)."""
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round"'
    s = ""
    for x in (40, 160):
        s += f'<circle cx="{x}" cy="46" r="32" fill="url(#fur)" {o}/><circle cx="{x}" cy="48" r="17" fill="{p.c}"/>'
    s += f'<circle cx="100" cy="108" r="82" fill="url(#fur)" {o}/>'
    s += '<path d="M100 28 L100 70" fill="none" stroke="#000" stroke-opacity=".25" stroke-width="3" stroke-dasharray="6 5"/>'
    s += gleam(66, 62, 26, 14, -30, 0.28)
    s += f'<ellipse cx="100" cy="140" rx="44" ry="34" fill="{p.b}" {o}/>'
    s += f'<path d="M86 124 Q100 116 114 124 Q116 136 100 142 Q84 136 86 124 Z" fill="{p.k}"/>'
    s += '<ellipse cx="96" cy="124" rx="6" ry="3" fill="#fff" opacity=".6"/>'
    s += f'<path d="M100 142 L100 152 M86 156 Q100 166 114 156" fill="none" stroke="{p.k}" stroke-width="5" stroke-linecap="round"/>'
    for x in (66, 134):
        s += f'<circle cx="{x}" cy="102" r="11" fill="{p.k}"/><circle cx="{x - 3}" cy="98" r="3.5" fill="#fff"/>'
    for x in (50, 150):
        s += f'<ellipse cx="{x}" cy="130" rx="13" ry="8" fill="#ff7a8a" opacity=".45"/>'
    return s


# ======================================================================= preschool


@kid("Sippy Cup", "preschool", "kids", "toddlers")
def sippy_cup():
    E = "#10345a"
    d = (
        SH
        + rad("tile", [(0, "#9ff0f5"), (0.6, "#3fc3e0"), (1, "#1f8fc4")], cx=0.4, cy=0.3, r=0.8)
        + shine("band", "#ff9aa8", "#ff5d73", "#d8344f")
    )
    body = f'<g filter="url(#sh)"><rect x="58" y="22" width="396" height="376" rx="120" fill="url(#tile)" stroke="{E}" stroke-width="8"/></g>'
    body += '<path d="M120 52 Q256 20 392 52" fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" opacity=".35"/>'
    for x, y, r in ((122, 118, 13), (400, 150, 10), (110, 250, 8), (396, 262, 14)):
        body += sparkle(x, y, r, "#fff")
    body += f'<g filter="url(#sh)">{centred(sippy(P(a="#ff9b3d", b="#ffd23f", c="#8c5cf0", l="#f4fbff", k=E)), 256, 196, 290)}</g>'
    body += f'<g filter="url(#sh)">{pill(30, 330, 452, 118, "url(#band)", E, 8)}</g>'
    body += '<rect x="64" y="342" width="384" height="16" rx="8" fill="#fff" opacity=".28"/>'
    body += fit(pop("SIPPY CUP", "Lilita One", "#fff", E, sw=12, depth=6, ls=2), 66, 346, 380, 86)
    return svg(body, d)


@kid("Naptime", "preschool", "kids", "bedtime")
def naptime():
    E = "#231f5c"
    d = (
        SH
        + lin("cl", [(0, "#ffffff"), (1, "#cfc4ff")])
        + shine("nw", "#6d63e6", "#3d33b8", "#231f7a")
    )
    circles = ((140, 272, 92), (250, 222, 118), (360, 250, 100), (426, 318, 56), (86, 330, 56))
    cloud = puff(circles, "url(#cl)", E, 8, rects=((70, 280, 380, 130, 64),))
    body = f'<g filter="url(#sh)">{cloud}</g>'
    body += gleam(210, 150, 60, 18, -12, 0.7)
    body += f'<g filter="url(#sh)">{centred(S.crescent(P(l="#ffe28a", b="#e9b53c", k=E)), 142, 136, 150)}</g>'
    for i, (x, y, sz) in enumerate(((356, 104, 60), (408, 62, 46), (448, 30, 34))):
        body += fit(
            pop("z", "Baloo 2", "#8c7bff" if i % 2 else "#fff", E, sw=10, weight=800),
            x - sz / 2,
            y - sz / 2,
            sz,
            sz,
        )
    for x, y, r in ((62, 170, 10), (300, 72, 9), (470, 176, 11)):
        body += sparkle(x, y, r, "#ffe28a", E, 3)
    body += fit(
        pop("naptime", "Baloo 2", "url(#nw)", "#fff", sw=12, weight=800, outer=E, osw=6, depth=6),
        70,
        262,
        372,
        120,
    )
    return svg(body, d)


@kid("Peekaboo", "preschool", "kids", "toddlers")
def peekaboo():
    E = "#3a1760"
    d = (
        SH
        + lin("wall", [(0, "#35d2c2"), (1, "#138f9a")])
        + lin("bl", [(0, "#ff8fb8"), (1, "#e2517f")])
        + shine("pk", "#fff7b0", "#ffd23f", "#f5a300")
        + "<clipPath id='pn'><rect x='28' y='92' width='456' height='328' rx='72'/></clipPath>"
    )
    body = f'<g filter="url(#sh)"><rect x="28" y="92" width="456" height="328" rx="72" fill="url(#wall)" stroke="{E}" stroke-width="8"/></g>'
    body += '<g clip-path="url(#pn)">'
    body += '<path d="M28 312 Q90 290 150 312 T272 312 T394 312 T516 312 L516 430 L28 430 Z" fill="url(#bl)"/>'
    rng = random.Random(3)
    for x in range(52, 480, 44):
        body += f'<circle cx="{x + rng.uniform(-6, 6):.0f}" cy="{362 + rng.uniform(-12, 22):.0f}" r="8" fill="#fff" opacity=".75"/>'
    body += '<path d="M28 312 Q90 290 150 312 T272 312 T394 312 T516 312" fill="none" stroke="#3a1760" stroke-width="6"/>'
    body += "</g>"
    body += f'<rect x="28" y="92" width="456" height="328" rx="72" fill="none" stroke="{E}" stroke-width="8"/>'
    body += '<path d="M90 116 Q256 100 422 116" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round" opacity=".3"/>'
    font = "Titan One"
    adv, _ = measure("PEEKAB", font)
    r = 34
    word = pop("PEEKAB", font, "url(#pk)", E, sw=12, anchor="start", depth=7)
    eyes = ""
    for k in range(2):
        cx = adv + 6 + r + k * (2 * r + 8)
        eyes += f'<g transform="translate(0 7)"><circle cx="{cx}" cy="-35" r="{r}" fill="{E}" stroke="{E}" stroke-width="12"/></g>'
        eyes += f'<circle cx="{cx}" cy="-35" r="{r}" fill="#fff" stroke="{E}" stroke-width="12"/>'
        eyes += f'<circle cx="{cx + 10}" cy="-30" r="15" fill="{E}"/><circle cx="{cx + 15}" cy="-36" r="5" fill="#fff"/>'
        eyes += f'<path d="M{cx - r - 2} -60 Q{cx} -84 {cx + r + 2} -60" fill="none" stroke="{E}" stroke-width="7" stroke-linecap="round"/>'
    body += f'<g filter="url(#sh)">{fit(word + eyes, 60, 168, 392, 140)}</g>'
    for x, y, rr in ((78, 148, 12), (440, 160, 10), (436, 270, 8)):
        body += sparkle(x, y, rr, "#fff")
    return svg(body, d)


@kid("Fingerpaint", "preschool", "kids", "arts and crafts")
def fingerpaint():
    E = "#2a1240"
    d = (
        SH
        + shine("sp", "#ff7ad0", "#e3218f", "#a3126a")
        + shine("fp", "#fff6a8", "#ffd83a", "#ffae00")
    )
    body = f'<path d="{blob(270, 238, 200, 18, 0.09, 4, 1.0, 0.86)}" fill="#ffd23f" stroke="{E}" stroke-width="7" transform="rotate(14 256 256)" filter="url(#sh)"/>'
    body += f'<path d="{blob(236, 262, 186, 16, 0.08, 9, 1.02, 0.84)}" fill="#29b6f6" stroke="{E}" stroke-width="7" filter="url(#sh)"/>'
    main = blob(256, 240, 176, 16, 0.07, 2, 1.12, 0.82)
    drips = ""
    for x, h, w in ((150, 70, 26), (214, 106, 30), (300, 58, 24), (360, 88, 28)):
        drips += f'<rect x="{x - w / 2}" y="330" width="{w}" height="{h}" rx="{w / 2}"/>'
    body += f'<g filter="url(#sh)"><g fill="{E}" stroke="{E}" stroke-width="14" stroke-linejoin="round"><path d="{main}"/>{drips}</g>'
    body += f'<g fill="url(#sp)"><path d="{main}"/>{drips}</g></g>'
    body += gleam(180, 130, 70, 20, -18, 0.35)
    for x, y, r in ((70, 90, 16), (450, 110, 12), (440, 420, 18), (72, 420, 11), (412, 58, 8)):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#e3218f" stroke="{E}" stroke-width="5"/>'
    body += fit(pop("FINGER", "Chango", "#fff", E, sw=12, depth=7), 84, 150, 344, 86)
    body += fit(pop("PAINT", "Chango", "url(#fp)", E, sw=12, depth=7), 104, 246, 304, 96)
    return svg(body, d)


@kid("Storytime", "preschool", "kids", "stories", "reading")
def storytime():
    E = "#2b1a3f"
    d = (
        SH
        + lin("pgL", [(0, "#e9dcc0"), (0.25, "#fffaf0"), (1, "#fff6e2")], x2=1, y2=0)
        + lin("pgR", [(0, "#fff6e2"), (0.75, "#fffaf0"), (1, "#e9dcc0")], x2=1, y2=0)
        + shine("cv", "#ff6b6b", "#d62839", "#8f1022")
    )
    cover = "M256 196 Q170 164 32 178 L32 420 Q170 408 256 440 Q342 408 480 420 L480 178 Q342 164 256 196 Z"
    left = "M256 184 Q166 146 44 162 L44 404 Q166 390 256 424 Z"
    right = "M256 184 Q346 146 468 162 L468 404 Q346 390 256 424 Z"
    body = f'<g filter="url(#sh)"><path d="{cover}" fill="url(#cv)" stroke="{E}" stroke-width="8" stroke-linejoin="round"/></g>'
    for k in (1, 2):
        body += f'<path d="M44 {404 + k * 5} Q166 {390 + k * 5} 256 {424 + k * 5} Q346 {390 + k * 5} 468 {404 + k * 5}" fill="none" stroke="#fff6e2" stroke-width="3"/>'
    body += (
        f'<path d="{left}" fill="url(#pgL)" stroke="{E}" stroke-width="6" stroke-linejoin="round"/>'
    )
    body += f'<path d="{right}" fill="url(#pgR)" stroke="{E}" stroke-width="6" stroke-linejoin="round"/>'
    body += f'<line x1="256" y1="186" x2="256" y2="422" stroke="{E}" stroke-width="4"/>'
    # a burst of story magic rising from the spine
    for i, (a, r, col, sz) in enumerate(
        (
            (-150, 128, "#ffd23f", 30),
            (-118, 150, "#4cc9f0", 24),
            (-90, 160, "#ff8fb8", 34),
            (-62, 150, "#7bd389", 24),
            (-30, 128, "#ffd23f", 30),
        )
    ):
        x = 256 + r * math.cos(math.radians(a))
        y = 176 + r * math.sin(math.radians(a))
        body += f'<path d="M256 176 L{x:.0f} {y:.0f}" stroke="{col}" stroke-width="5" stroke-dasharray="2 10" stroke-linecap="round" opacity=".9"/>'
        body += starp(x, y, sz, col, E, 5, rot=-90 + i * 8)
    body += f'<g filter="url(#soft)">{fit(pop("STORY", "Carter One", "#e63946", E, sw=10, depth=5), 62, 220, 176, 120)}</g>'
    body += f'<g filter="url(#soft)">{fit(pop("TIME", "Carter One", "#1d7bd8", E, sw=10, depth=5), 280, 220, 170, 120)}</g>'
    for y in (362, 380):
        body += f'<line x1="84" y1="{y}" x2="220" y2="{y + 6}" stroke="#d9c8a8" stroke-width="4" stroke-linecap="round"/><line x1="292" y1="{y + 6}" x2="428" y2="{y}" stroke="#d9c8a8" stroke-width="4" stroke-linecap="round"/>'
    return svg(body, d + SOFT)


@kid("Puddle Jump", "preschool", "kids", "outdoors")
def puddle_jump():
    E = "#0f2d57"
    d = (
        SH
        + rad("pd", [(0, "#8ee7ff"), (0.7, "#2fa6e8"), (1, "#1566b8")], cy=0.4, r=0.7)
        + shine("jp", "#fff6a8", "#ffd23f", "#f0a202")
        + "<clipPath id='pc'><ellipse cx='256' cy='404' rx='216' ry='66'/></clipPath>"
    )
    body = f'<g filter="url(#sh)"><path d="{blob(256, 404, 216, 14, 0.05, 3, 1, 0.3)}" fill="url(#pd)" stroke="{E}" stroke-width="8"/></g>'
    jump = pop("JUMP", "Lilita One", "url(#jp)", E, sw=12, depth=8)
    body += '<g clip-path="url(#pc)">'
    flipped = text("JUMP", "Lilita One", 96, fill="#fff", x=256, y=404, ls=4)
    body += f'<g opacity=".28" transform="translate(0 808) scale(1 -1)">{flipped}</g>'
    for rx, ry in ((70, 14), (130, 26), (190, 40)):
        body += f'<ellipse cx="256" cy="400" rx="{rx}" ry="{ry}" fill="none" stroke="#fff" stroke-width="3" opacity=".45"/>'
    body += "</g>"
    for a, dist, sz in (
        (-160, 190, 22),
        (-140, 200, 16),
        (-20, 190, 22),
        (-40, 204, 16),
        (-112, 176, 14),
        (-68, 176, 14),
    ):
        x = 256 + dist * math.cos(math.radians(a))
        y = 400 + dist * 0.62 * math.sin(math.radians(a))
        rot = a + 90
        body += f'<path d="M0 {-sz * 1.5} Q{sz} 0 0 {sz} Q{-sz} 0 0 {-sz * 1.5} Z" transform="translate({x:.0f} {y:.0f}) rotate({rot:.0f})" fill="#5cc8f5" stroke="{E}" stroke-width="4" stroke-linejoin="round"/>'
    body += f'<g filter="url(#sh)">{fit(pop("PUDDLE", "Lilita One", "#6fd0ff", E, sw=12, depth=6, ls=4), 96, 36, 320, 104)}</g>'
    body += f'<g filter="url(#sh)">{fit(jump, 56, 150, 400, 190)}</g>'
    return svg(body, d)


@kid("Bubble Wand", "preschool", "kids")
def bubble_wand():
    E = "#2b1b5c"
    d = (
        SH
        + rad(
            "bb",
            [(0, "#ffffff"), (0.62, "#eef9ff"), (0.86, "#dcd0ff"), (1, "#bfeaff")],
            cx=0.42,
            cy=0.38,
            r=0.62,
        )
        + lin(
            "ir", [(0, "#ff7eb6"), (0.33, "#7afcff"), (0.66, "#fffb7d"), (1, "#b28dff")], x2=1, y2=1
        )
        + shine("bw", "#b98cff", "#7a3ce0", "#4b1a9e")
        + lin("stk", [(0, "#ff8fb8"), (1, "#d6336c")], x2=1, y2=0)
    )
    body = ""
    for x, y, r in ((438, 80, 34), (470, 170, 18), (60, 360, 26), (74, 440, 14)):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="url(#bb)" stroke="{E}" stroke-width="5"/><circle cx="{x}" cy="{y}" r="{r - 5}" fill="none" stroke="url(#ir)" stroke-width="4"/>'
        body += f'<path d="M{x - r * 0.6} {y - r * 0.2} A{r * 0.65} {r * 0.65} 0 0 1 {x - r * 0.1} {y - r * 0.62}" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round"/>'
    body += f'<g filter="url(#sh)"><circle cx="246" cy="232" r="196" fill="url(#bb)" stroke="{E}" stroke-width="8"/></g>'
    body += '<circle cx="246" cy="232" r="184" fill="none" stroke="url(#ir)" stroke-width="12"/>'
    body += '<path d="M104 200 A150 150 0 0 1 200 88" fill="none" stroke="#fff" stroke-width="16" stroke-linecap="round"/>'
    body += '<circle cx="224" cy="72" r="8" fill="#fff"/>'
    # the wand: a ring on a stick
    body += '<g filter="url(#sh)">'
    body += f'<line x1="404" y1="388" x2="476" y2="490" stroke="{E}" stroke-width="26" stroke-linecap="round"/><line x1="404" y1="388" x2="476" y2="490" stroke="url(#stk)" stroke-width="14" stroke-linecap="round"/>'
    body += f'<circle cx="382" cy="356" r="44" fill="none" stroke="{E}" stroke-width="26"/><circle cx="382" cy="356" r="44" fill="none" stroke="#ff5d8f" stroke-width="13"/>'
    body += '<path d="M346 338 A40 40 0 0 1 380 314" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" opacity=".7"/></g>'
    body += fit(
        pop("BUBBLE", "Fredoka", "url(#bw)", "#fff", sw=12, weight=700, outer=E, osw=5, depth=5),
        92,
        150,
        308,
        96,
    )
    body += fit(
        pop("WAND", "Fredoka", "url(#bw)", "#fff", sw=12, weight=700, outer=E, osw=5, depth=5),
        126,
        250,
        240,
        90,
    )
    return svg(body, d)


def pillow(x, y, w, h, fill, edge, sw=7, tuft=True) -> str:
    """A plump pillow: pinched corners, puffed sides, a button tuft."""
    px, py = w * 0.07, h * 0.1
    d = (
        f"M{x} {y} Q{x + w / 2} {y + py} {x + w} {y} Q{x + w - px} {y + h / 2} {x + w} {y + h} "
        f"Q{x + w / 2} {y + h - py} {x} {y + h} Q{x + px} {y + h / 2} {x} {y} Z"
    )
    s = f'<path d="{d}" fill="{fill}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
    s += f'<ellipse cx="{x + w * 0.36}" cy="{y + h * 0.28}" rx="{w * 0.22}" ry="{h * 0.1}" fill="#fff" opacity=".3"/>'
    if tuft:
        cx, cy = x + w / 2, y + h / 2
        s += f'<path d="M{cx - 14} {cy - 10} L{cx + 14} {cy + 10} M{cx + 14} {cy - 10} L{cx - 14} {cy + 10}" stroke="{edge}" stroke-opacity=".3" stroke-width="3"/>'
        s += f'<circle cx="{cx}" cy="{cy}" r="7" fill="{edge}" opacity=".45"/>'
    return s


@kid("Pillow Fort", "preschool", "kids", "sleepover")
def pillow_fort():
    E = "#2a1d4f"
    d = (
        SH + "<pattern id='ging' width='36' height='36' patternUnits='userSpaceOnUse'>"
        "<rect width='36' height='36' fill='#ffd7e6'/><rect width='18' height='36' fill='#ff9ec4' opacity='.6'/>"
        "<rect width='36' height='18' fill='#ff9ec4' opacity='.6'/></pattern>"
        + rad("tglow", [(0, "#fff3b0"), (1, "#f0a202")], cy=0.7, r=0.7)
    )
    tent = "M256 54 L470 360 L42 360 Z"
    body = f'<g filter="url(#sh)"><path d="{tent}" fill="url(#ging)" stroke="{E}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += f'<path d="M256 120 L340 360 L172 360 Z" fill="url(#tglow)" stroke="{E}" stroke-width="6" stroke-linejoin="round"/>'
    body += f'<path d="M256 120 Q236 240 172 360 M256 120 Q276 240 340 360" fill="none" stroke="{E}" stroke-width="4" opacity=".4"/>'
    for i in range(9):
        t = (i + 0.5) / 9
        for sx in (-1, 1):
            x = 256 + sx * 214 * t
            y = 54 + 306 * t + 10
            c = ("#ff5d8f", "#ffd23f", "#5fd6ae", "#6db6ff")[i % 4]
            body += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="8" fill="{c}" stroke="{E}" stroke-width="3"/>'
    body += f'<line x1="256" y1="54" x2="256" y2="24" stroke="{E}" stroke-width="6" stroke-linecap="round"/>'
    body += f'<path d="M259 24 L306 36 L259 48 Z" fill="#ffd23f" stroke="{E}" stroke-width="4" stroke-linejoin="round"/>'
    body += f'<g filter="url(#sh)">{pill(40, 344, 432, 136, "#7a5bd0", E)}</g>'
    body += fit(pop("PILLOW FORT", "Titan One", "#fff", E, sw=12, depth=6), 70, 366, 372, 92)
    return svg(body, d)


@kid("Hopscotch", "preschool", "kids", "playground")
def hopscotch():
    E = "#1f2250"
    d = SH + shine("sc", "#ffffff", "#f3f0ff", "#c9c3f0")
    tiles = (
        ("H", "#ff5d73", "#ff9aa8", "1", 42, 130, -5),
        ("O", "#ffc233", "#ffe08a", "2", 188, 100, 3),
        ("P", "#27c2b0", "#8eeadf", "3", 334, 130, -3),
    )
    body = '<path d="M64 110 Q150 20 256 70 Q362 20 448 110" fill="none" stroke="#fff" stroke-width="6" stroke-dasharray="4 14" stroke-linecap="round" opacity=".9"/>'
    for ch, col, light, n, x, y, rot in tiles:
        c = x + 68
        g = f'<rect x="{x}" y="{y + 10}" width="136" height="136" rx="22" fill="{E}"/>'
        g += f'<rect x="{x}" y="{y}" width="136" height="136" rx="22" fill="{col}" stroke="{E}" stroke-width="7"/>'
        g += f'<rect x="{x + 12}" y="{y + 12}" width="112" height="112" rx="14" fill="none" stroke="{light}" stroke-width="5" stroke-dasharray="14 6"/>'
        g += text(n, "Lilita One", 26, fill="#fff", x=x + 118, y=y + 34, anchor="end")
        g += text(ch, "Lilita One", 104, fill="#fff", stroke=E, sw=10, x=c, y=y + 110)
        body += f'<g filter="url(#sh)" transform="rotate({rot} {c} {y + 68})">{g}</g>'
    body += (
        f'<ellipse cx="256" cy="62" rx="22" ry="14" fill="#ff7b39" stroke="{E}" stroke-width="5"/>'
    )
    body += f'<g filter="url(#sh)">{fit(pop("SCOTCH", "Lilita One", "url(#sc)", E, sw=12, depth=9, ls=3), 40, 300, 432, 150)}</g>'
    return svg(body, d)


@kid("Sidewalk Chalk", "preschool", "kids", "arts and crafts")
def sidewalk_chalk():
    E = "#1b1e26"
    d = (
        SH
        + lin("ash", [(0, "#5a6170"), (1, "#353a45")])
        + rough("ch", amount=4, freq=1.4, seed=6)
        + "<filter id='dust' x='-10%' y='-10%' width='120%' height='120%'><feTurbulence type='fractalNoise' baseFrequency='1.6' numOctaves='2' seed='3' result='n'/>"
        + "<feColorMatrix in='n' type='matrix' values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -1.6 1.45' result='m'/>"
        + "<feComposite in='SourceGraphic' in2='m' operator='in' result='c'/><feDisplacementMap in='c' in2='n' scale='4' xChannelSelector='R' yChannelSelector='G'/></filter>"
        + "<clipPath id='sw'><rect x='30' y='36' width='452' height='440' rx='56'/></clipPath>"
    )
    body = f'<g filter="url(#sh)"><rect x="30" y="36" width="452" height="440" rx="56" fill="url(#ash)" stroke="{E}" stroke-width="8"/></g>'
    body += '<g clip-path="url(#sw)">'
    rng = random.Random(8)
    for _ in range(140):
        body += f'<circle cx="{rng.uniform(30, 482):.0f}" cy="{rng.uniform(36, 476):.0f}" r="{rng.uniform(1, 2.6):.1f}" fill="{"#7a8190" if rng.random() < 0.6 else "#2a2e36"}"/>'
    body += '<line x1="30" y1="300" x2="482" y2="292" stroke="#2a2e36" stroke-width="5"/><line x1="30" y1="303" x2="482" y2="295" stroke="#6b7282" stroke-width="2"/>'
    body += "</g>"
    art = '<g fill="none" stroke-linecap="round" stroke-width="9">'
    art += '<circle cx="400" cy="110" r="30" stroke="#ffe066"/>'
    for k in range(8):
        a = math.radians(k * 45)
        art += f'<line x1="{400 + 44 * math.cos(a):.0f}" y1="{110 + 44 * math.sin(a):.0f}" x2="{400 + 60 * math.cos(a):.0f}" y2="{110 + 60 * math.sin(a):.0f}" stroke="#ffe066"/>'
    art += f'<polygon points="{star(104, 104, 40, 18)}" stroke="#ff9ecf" stroke-linejoin="round"/>'
    art += "</g>"
    body += f'<g filter="url(#dust)">{art}</g>'
    w1 = text("SIDEWALK", "Fredoka", 100, weight=700, fill="#ff9ecf", stroke="#ff9ecf", sw=5)
    w2 = text("CHALK", "Fredoka", 100, weight=700, fill="#8fd8ff", stroke="#8fd8ff", sw=5)
    body += f'<g filter="url(#dust)">{fit(w1, 62, 172, 388, 86)}{fit(w2, 84, 260, 344, 118)}</g>'
    for i, (col, dark) in enumerate(
        (("#ff9ecf", "#d45f96"), ("#ffe066", "#d9b01c"), ("#8fd8ff", "#3d9fd6"))
    ):
        x, y = 140 + i * 90, 412 + (i % 2) * 14
        g = f'<rect x="-44" y="-15" width="88" height="30" rx="15" fill="{col}" stroke="{E}" stroke-width="5"/>'
        g += f'<rect x="-36" y="-9" width="60" height="7" rx="3.5" fill="#fff" opacity=".55"/><ellipse cx="44" cy="0" rx="7" ry="15" fill="{dark}" stroke="{E}" stroke-width="5"/>'
        body += (
            f'<g filter="url(#soft)" transform="translate({x} {y}) rotate({-14 + i * 12})">{g}</g>'
        )
    return svg(body, d + SOFT)


@kid("Crayon Box", "preschool", "kids", "arts and crafts")
def crayon_box():
    E = "#131a4a"
    d = (
        SH
        + shine("bx", "#4f86ff", "#2457e0", "#15319a")
        + shine("lb", "#ff8a5c", "#ff5a36", "#d93a1a")
        + shine("cb", "#fff2a8", "#ffd23f", "#f5a300")
    )
    cols = ["#e63946", "#ff9f1c", "#ffd23f", "#2ec46d", "#29a6ff", "#8e5cf0"]
    body = '<g filter="url(#sh)">'
    for i, c in enumerate(cols):
        x = 108 + i * 60
        top = 92 + (18 if i % 2 else 0) - (14 if i in (2, 3) else 0)
        body += f'<path d="M{x} {top + 44} L{x + 24} {top} L{x + 48} {top + 44} Z" fill="{c}" stroke="{E}" stroke-width="6" stroke-linejoin="round"/>'
        body += f'<rect x="{x}" y="{top + 42}" width="48" height="160" fill="{c}" stroke="{E}" stroke-width="6"/>'
        body += f'<rect x="{x}" y="{top + 58}" width="48" height="10" fill="{E}" opacity=".35"/><rect x="{x}" y="{top + 76}" width="48" height="10" fill="{E}" opacity=".35"/>'
        body += f'<rect x="{x + 8}" y="{top + 48}" width="8" height="90" rx="4" fill="#fff" opacity=".4"/>'
    front = "M56 200 L200 200 Q256 236 312 200 L456 200 L444 470 L68 470 Z"
    body += (
        f'<path d="{front}" fill="url(#bx)" stroke="{E}" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += "</g>"
    body += '<path d="M72 216 L196 216 Q256 252 316 216 L440 216" fill="none" stroke="#fff" stroke-width="5" opacity=".3"/>'
    body += f'<rect x="84" y="262" width="344" height="184" rx="22" fill="url(#lb)" stroke="{E}" stroke-width="6"/>'
    for x, y in ((104, 280), (408, 280), (104, 428), (408, 428)):
        body += f'<circle cx="{x}" cy="{y}" r="5" fill="#ffd23f"/>'
    body += fit(pop("CRAYON", "Bowlby One", "#fff", E, sw=12, depth=5), 104, 272, 304, 74)
    body += fit(pop("BOX", "Bowlby One", "url(#cb)", E, sw=12, depth=6), 150, 350, 212, 84)
    return svg(body, d)


def cube(x, y, s, main, light, dark, edge, sw=6, face="") -> str:
    """A toy block drawn in three-quarter view; `face` is drawn on the front."""
    dx, dy = s * 0.28, s * 0.24
    g = f'<polygon points="{pts([(x, y), (x + dx, y - dy), (x + s + dx, y - dy), (x + s, y)])}" fill="{light}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
    g += f'<polygon points="{pts([(x + s, y), (x + s + dx, y - dy), (x + s + dx, y + s - dy), (x + s, y + s)])}" fill="{dark}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
    g += f'<rect x="{x}" y="{y}" width="{s}" height="{s}" fill="{main}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
    g += f'<rect x="{x + s * 0.1}" y="{y + s * 0.1}" width="{s * 0.8}" height="{s * 0.8}" rx="{s * 0.08}" fill="none" stroke="#fff" stroke-width="{max(3, s * 0.03):.1f}" opacity=".55"/>'
    return g + face


def slab(x, y, w, h, main, light, dark, edge, sw=7) -> str:
    """A long building block (a plank) in three-quarter view."""
    dx, dy = 26, 22
    g = f'<polygon points="{pts([(x, y), (x + dx, y - dy), (x + w + dx, y - dy), (x + w, y)])}" fill="{light}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
    g += f'<polygon points="{pts([(x + w, y), (x + w + dx, y - dy), (x + w + dx, y + h - dy), (x + w, y + h)])}" fill="{dark}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
    g += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{main}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
    g += f'<rect x="{x + 10}" y="{y + 10}" width="{w - 20}" height="{h - 20}" rx="8" fill="none" stroke="#fff" stroke-width="4" opacity=".5"/>'
    return g


@kid("Stacking Blocks", "preschool", "kids", "learning")
def stacking_blocks():
    E = "#1d1b3a"
    d = SH
    body = '<g filter="url(#sh)">'
    body += slab(24, 330, 438, 128, "#e63946", "#ff7b84", "#a3162a", E)
    body += slab(62, 210, 362, 112, "#1f8ff0", "#7cc2ff", "#1256a8", E)
    heart = S.heart(P(a="#ff5d8f", l="#fff", k=E))
    body += cube(196, 90, 104, "#ffc233", "#ffe28a", "#d48b00", E, 7, centred(heart, 248, 142, 70))
    body += "</g>"
    body += fit(pop("STACKING", "Baloo 2", "#fff", E, sw=12, weight=800, depth=4), 84, 222, 318, 88)
    body += fit(
        pop("BLOCKS", "Baloo 2", "#ffe066", E, sw=12, weight=800, depth=4), 50, 342, 386, 104
    )
    for x, y, r in ((96, 150, 14), (420, 130, 16), (360, 60, 10)):
        body += sparkle(x, y, r, "#ffe066", E, 3)
    return svg(body, d)


@kid("Lullaby Lane", "preschool", "kids", "bedtime", "music")
def lullaby_lane():
    E = "#1a1745"
    d = (
        SH
        + rad("nt", [(0, "#3d3a9e"), (1, "#15123f")], cy=0.35, r=0.7)
        + shine("pl", "#e3d6ff", "#b39cf5", "#8a6fe0")
        + lin("post", [(0, "#cfd6e6"), (0.5, "#8d97ad"), (1, "#5b6478")], x2=1, y2=0)
    )
    body = f'<g filter="url(#sh)"><circle cx="256" cy="256" r="226" fill="url(#nt)" stroke="{E}" stroke-width="8"/></g>'
    rng = random.Random(5)
    for _ in range(18):
        x, y = rng.uniform(80, 430), rng.uniform(60, 170)
        body += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rng.uniform(1.5, 3.2):.1f}" fill="#fff" opacity=".85"/>'
    body += sparkle(118, 96, 14, "#ffe9a0") + sparkle(318, 70, 10, "#ffe9a0")
    body += centred(S.crescent(P(l="#ffe28a", b="#e0a93a", k=E)), 380, 116, 120)
    for x, y, rot in ((170, 128, -10), (236, 100, 8)):
        body += centred(S.notes(P(a="#ff9ecf", k=E)), x, y, 54).replace(
            "<g ", f'<g opacity=".95" data-r="{rot}" ', 1
        )
    body += f'<g filter="url(#sh)"><rect x="244" y="300" width="24" height="190" rx="6" fill="url(#post)" stroke="{E}" stroke-width="6"/></g>'
    body += f'<g filter="url(#sh)"><rect x="28" y="172" width="456" height="130" rx="26" fill="url(#pl)" stroke="{E}" stroke-width="8"/>'
    body += '<rect x="42" y="186" width="428" height="102" rx="16" fill="none" stroke="#fff" stroke-width="4"/>'
    body += f'<rect x="170" y="310" width="172" height="62" rx="16" fill="#ffd166" stroke="{E}" stroke-width="7"/></g>'
    body += fit(pop("Lullaby", "Pacifico", "#fff", E, sw=12), 70, 184, 372, 108)
    body += fit(text("LANE", "Fredoka", 100, weight=700, fill=E, ls=14), 196, 322, 120, 38)
    return svg(body, d)


@kid("Rain Boots", "preschool", "kids", "outdoors")
def rain_boots():
    E = "#0e2750"
    d = (
        SH
        + lin("dr", [(0, "#8fd6ff"), (1, "#2170d8")])
        + shine("rb", "#ff8a8d", "#ef3e4a", "#b81d2a")
        + "<clipPath id='dc'><path d='M256 30 C290 104 440 196 440 304 A184 184 0 1 1 72 304 C72 196 222 104 256 30 Z'/></clipPath>"
    )
    drop = "M256 30 C290 104 440 196 440 304 A184 184 0 1 1 72 304 C72 196 222 104 256 30 Z"
    body = f'<g filter="url(#sh)"><path d="{drop}" fill="url(#dr)" stroke="{E}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += '<g clip-path="url(#dc)">'
    for x, y in (
        (120, 200),
        (170, 150),
        (340, 170),
        (390, 230),
        (220, 110),
        (300, 120),
        (110, 280),
        (408, 300),
    ):
        body += f'<line x1="{x}" y1="{y}" x2="{x - 8}" y2="{y + 26}" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".5"/>'
    body += '<ellipse cx="256" cy="440" rx="160" ry="30" fill="#1a5fb8" opacity=".6"/>'
    body += "</g>"
    body += '<path d="M232 76 Q206 120 170 150" fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" opacity=".45"/>'
    bp = P(a="#ffd23f", b="#fff1a8", c="#e0501b", k=E)
    body += f'<g filter="url(#sh)">{centred(boot(bp), 214, 212, 150)}{centred(boot(bp), 300, 222, 150)}</g>'
    body += f'<g filter="url(#sh)">{ribbon(52, 460, 300, 82, "url(#rb)", "#a3172a", E, 7)}</g>'
    body += fit(pop("RAIN BOOTS", "Lilita One", "#fff", E, sw=10, depth=4, ls=2), 76, 312, 360, 58)
    return svg(body, d)


@kid("Teddy Bear", "preschool", "kids", "bedtime")
def teddy_bear():
    E = "#3d2210"
    d = (
        SH
        + rad("fur", [(0, "#f2b872"), (0.7, "#d98c45"), (1, "#b56a2a")], cx=0.4, cy=0.35, r=0.75)
        + shine("tb", "#ff7ea0", "#e8366a", "#b01848")
    )
    body = '<circle cx="256" cy="210" r="196" fill="#ffe7c2" opacity=".0"/>'
    body += f'<g filter="url(#sh)">{centred(bear_head(P(b="#fff0d8", c="#f7a0b4", k=E)), 256, 176, 300)}</g>'
    body += f'<g filter="url(#sh)">{ribbon(58, 454, 318, 92, "url(#tb)", "#8e1236", E, 7)}</g>'
    body += '<rect x="70" y="330" width="372" height="10" rx="5" fill="#fff" opacity=".3"/>'
    body += fit(pop("TEDDY BEAR", "Carter One", "#fff", E, sw=10, depth=4), 82, 330, 348, 66)
    body += '<path d="M256 470 C232 450 214 436 214 420 C214 408 226 400 236 402 C246 404 252 412 256 418 C260 412 266 404 276 402 C286 400 298 408 298 420 C298 436 280 450 256 470 Z" fill="#e8366a" stroke="#3d2210" stroke-width="6" stroke-linejoin="round" transform="translate(0 6) scale(1)"/>'
    return svg(body, d)


@kid("Seedlings", "preschool", "kids", "nature", "learning")
def seedlings():
    E = "#123a1f"
    d = (
        SH
        + shine("gw", "#b6f27a", "#4cc34a", "#23872f")
        + shine("pot", "#ff9a6b", "#e0643a", "#a8421f")
        + lin("sun", [(0, "#fff3b0"), (1, "#ffd166")])
        + lin("lf", [(0, "#9be15d"), (1, "#2fa84f")], x2=1, y2=1)
    )
    body = '<circle cx="256" cy="190" r="170" fill="url(#sun)" opacity=".95" filter="url(#sh)"/>'
    for k in range(12):
        a = math.radians(-180 + k * 15 + 7.5)
        if -180 < math.degrees(a) < 0:
            body += f'<line x1="{256 + 184 * math.cos(a):.0f}" y1="{190 + 184 * math.sin(a):.0f}" x2="{256 + 214 * math.cos(a):.0f}" y2="{190 + 214 * math.sin(a):.0f}" stroke="#ffd166" stroke-width="9" stroke-linecap="round"/>'
    # planter box
    body += '<g filter="url(#sh)">'
    body += f'<path d="M40 300 L472 300 L446 462 L66 462 Z" fill="url(#pot)" stroke="{E}" stroke-width="8" stroke-linejoin="round"/>'
    body += f'<rect x="26" y="286" width="460" height="40" rx="12" fill="#ff8a57" stroke="{E}" stroke-width="7"/></g>'
    body += '<rect x="44" y="294" width="300" height="8" rx="4" fill="#fff" opacity=".35"/>'
    body += fit(
        text("GROWING UP GREEN", "Fredoka", 40, weight=700, fill="#fff3e0", ls=4), 110, 400, 292, 34
    )
    # the word, with a sprout for the i
    font, wt = "Fredoka", 700
    a1, _ = measure("seedl", font, wt)
    a2, _ = measure("ı", font, wt)
    x0 = a1 + 4
    stem = f'<rect x="{x0}" y="-52" width="{a2 - 8}" height="52" rx="{(a2 - 8) / 2}" fill="url(#gw)" stroke="{E}" stroke-width="12" paint-order="stroke"/>'
    mid = x0 + (a2 - 8) / 2
    sprout = f'<path d="M{mid} -52 Q{mid - 4} -84 {mid} -104" fill="none" stroke="{E}" stroke-width="16" stroke-linecap="round"/><path d="M{mid} -52 Q{mid - 4} -84 {mid} -104" fill="none" stroke="#3fae44" stroke-width="7" stroke-linecap="round"/>'
    sprout += f'<path d="M{mid} -96 Q{mid - 50} -118 {mid - 62} -150 Q{mid - 10} -150 {mid} -96 Z" fill="url(#lf)" stroke="{E}" stroke-width="7" stroke-linejoin="round"/>'
    sprout += f'<path d="M{mid} -104 Q{mid + 44} -134 {mid + 70} -140 Q{mid + 60} -98 {mid} -104 Z" fill="url(#lf)" stroke="{E}" stroke-width="7" stroke-linejoin="round"/>'
    w = pop("seedl", font, "url(#gw)", E, sw=12, weight=wt, anchor="start", depth=5)
    w += sprout + f'<g transform="translate(0 5)">{stem.replace("url(#gw)", E)}</g>' + stem
    w += pop("ngs", font, "url(#gw)", E, sw=12, weight=wt, anchor="start", x=a1 + a2, depth=5)
    body += f'<g filter="url(#sh)">{fit(w, 44, 70, 424, 216, anchor="bottom")}</g>'
    return svg(body, d)


@kid("Alphabet Soup", "preschool", "kids", "learning")
def alphabet_soup():
    E = "#2a1433"
    d = (
        SH
        + shine("bowl", "#56d0ff", "#1c8fe0", "#0f5aa8")
        + rad("soup", [(0, "#ffb070"), (1, "#f0602a")], r=0.6)
        + shine("ab", "#fff5a0", "#ffd23f", "#f3a100")
    )
    t_defs, t_body = arc_text(
        "ALPHABET",
        "Titan One",
        256,
        312,
        212,
        86,
        fill="url(#ab)",
        stroke=E,
        sw=12,
        pid="abc",
        ls=2,
    )
    d += t_defs
    ex = (
        t_body.replace("<text ", '<text transform="translate(0 7)" ', 1)
        .replace('fill="url(#ab)"', f'fill="{E}"')
        .replace(f'stroke="{E}"', f'stroke="{E}"')
    )
    body = f'<g filter="url(#sh)">{fit(ex + t_body, 34, 26, 444, 150)}</g>'
    for x in (200, 256, 312):
        body += f'<path d="M{x} 236 Q{x - 16} 214 {x} 196 Q{x + 16} 178 {x} 160" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity=".7"/>'
    bowl = "M40 262 L472 262 Q470 410 300 450 L212 450 Q42 410 40 262 Z"
    body += '<g filter="url(#sh)">'
    body += f'<rect x="380" y="150" width="22" height="130" rx="11" fill="#d7dde8" stroke="{E}" stroke-width="6" transform="rotate(28 390 216)"/>'
    body += f'<path d="{bowl}" fill="url(#bowl)" stroke="{E}" stroke-width="8" stroke-linejoin="round"/>'
    body += f'<ellipse cx="256" cy="262" rx="216" ry="34" fill="#e8f7ff" stroke="{E}" stroke-width="8"/>'
    body += '<ellipse cx="256" cy="264" rx="194" ry="24" fill="url(#soup)"/>'
    body += "</g>"
    for ch, x, y, r in (
        ("A", 150, 262, -12),
        ("B", 214, 268, 8),
        ("C", 300, 260, -6),
        ("1", 360, 266, 10),
        ("Z", 112, 270, 14),
    ):
        body += text(
            ch,
            "Titan One",
            26,
            fill="#fff3d6",
            stroke="#b84a1a",
            sw=3,
            x=x,
            y=y + 8,
            extra=f'transform="rotate({r} {x} {y})"',
        )
    body += '<path d="M70 300 Q256 340 442 300" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity=".35"/>'
    body += fit(pop("SOUP", "Titan One", "#fff", E, sw=12, depth=6, ls=6), 132, 316, 248, 106)
    return svg(body, d)


@kid("Giggles", "preschool", "kids", "comedy")
def giggles():
    E = "#2b1650"
    d = (
        SH
        + shine("gb", "#fff7b8", "#ffdf3a", "#ffb000")
        + shine("gg", "#ff9ed2", "#f0368f", "#b8126a")
    )
    bub = "M256 60 C400 60 480 130 480 226 C480 322 400 380 270 384 L150 452 L170 372 C84 352 32 296 32 226 C32 130 112 60 256 60 Z"
    body = f'<g filter="url(#sh)"><path d="{bub}" fill="#e89a00" stroke="{E}" stroke-width="8" stroke-linejoin="round" transform="translate(10 12)"/>'
    body += f'<path d="{bub}" fill="url(#gb)" stroke="{E}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += '<path d="M110 118 Q180 82 256 80" fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" opacity=".55"/>'
    wob = [8, -6, 6, -8, 6, -6, 8]
    letters = word_row("GIGGLES", "Chango", ["url(#gg)"], E, sw=12, dy=wob, gap=-2, depth=6)
    body += fit(f'<g transform="rotate(-5)">{letters}</g>', 58, 150, 396, 150)
    for x1, y1, x2, y2 in (
        (62, 78, 82, 104),
        (40, 124, 72, 132),
        (448, 70, 432, 98),
        (474, 118, 444, 128),
    ):
        body += f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{E}" stroke-width="7" stroke-linecap="round"/>'
    return svg(body, d)


# ======================================================================= registry


# ======================================================================= big kids


@kid("Monkey Bars", "kids", "playground", "adventure")
def monkey_bars():
    E = "#1f2a44"
    d = SH + shine("mbw", "#fff6a8", "#ffd23f", "#f0a202")
    body = '<g filter="url(#sh)">'
    for x in (60, 452):
        body += f'<line x1="{x}" y1="70" x2="{x}" y2="460" stroke="{E}" stroke-width="34" stroke-linecap="round"/><line x1="{x}" y1="70" x2="{x}" y2="460" stroke="#ef4444" stroke-width="20" stroke-linecap="round"/>'
    for y in (70, 140):
        body += f'<line x1="60" y1="{y}" x2="452" y2="{y}" stroke="{E}" stroke-width="30" stroke-linecap="round"/><line x1="60" y1="{y}" x2="452" y2="{y}" stroke="#ef4444" stroke-width="16" stroke-linecap="round"/>'
    for x in range(110, 420, 50):
        body += f'<line x1="{x}" y1="70" x2="{x}" y2="140" stroke="{E}" stroke-width="20" stroke-linecap="round"/><line x1="{x}" y1="70" x2="{x}" y2="140" stroke="#ffd23f" stroke-width="9" stroke-linecap="round"/>'
    body += "</g>"
    body += fit(pop("MONKEY", "Titan One", "url(#mbw)", E, sw=12, depth=7), 96, 196, 320, 104)
    body += fit(pop("BARS", "Titan One", "#fff", E, sw=12, depth=7), 136, 314, 240, 104)
    return svg(body, d)


@kid("Tire Swing", "kids", "playground", "outdoors")
def tire_swing():
    E = "#1c1917"
    d = (
        SH
        + rad("tire", [(0.6, "#57534e"), (1, "#1c1917")])
        + shine("tsr", "#9ae6b4", "#22c55e", "#15803d")
    )
    body = '<path d="M40 40 Q256 70 472 30" fill="none" stroke="#6b4423" stroke-width="22" stroke-linecap="round"/>'
    for x in (200, 312):
        body += f'<line x1="{x}" y1="52" x2="{256 + (x - 256) * 0.6:.0f}" y2="150" stroke="#d6b47a" stroke-width="7"/>'
    body += f'<g filter="url(#sh)"><circle cx="256" cy="280" r="150" fill="url(#tire)" stroke="{E}" stroke-width="8"/></g>'
    body += f'<circle cx="256" cy="280" r="78" fill="#fde68a" stroke="{E}" stroke-width="8"/>'
    for k in range(24):
        a = math.radians(k * 15)
        body += f'<line x1="{256 + 92 * math.cos(a):.0f}" y1="{280 + 92 * math.sin(a):.0f}" x2="{256 + 138 * math.cos(a):.0f}" y2="{280 + 138 * math.sin(a):.0f}" stroke="#78716c" stroke-width="5"/>'
    body += f'<g filter="url(#sh)">{ribbon(64, 448, 244, 76, "url(#tsr)", "#15803d", E, sw=6, tail=40, drop=18)}</g>'
    body += fit(pop("TIRE SWING", "Lilita One", "#fff", E, sw=10, depth=5), 92, 254, 328, 56)
    return svg(body, d)


@kid("Jungle Gym", "kids", "playground", "adventure")
def jungle_gym():
    E = "#14361f"
    d = SH + shine("jg", "#b8f5a0", "#4ade80", "#15803d")
    body = '<g filter="url(#sh)" fill="none">'
    for r in (180, 130, 80):
        body += f'<path d="M{256 - r} 300 A{r} {r} 0 0 1 {256 + r} 300" stroke="{E}" stroke-width="22"/>'
        body += f'<path d="M{256 - r} 300 A{r} {r} 0 0 1 {256 + r} 300" stroke="#facc15" stroke-width="12"/>'
    for a in (180, 216, 252, 288, 324, 360):
        x, y = 256 + 180 * math.cos(math.radians(a)), 300 + 180 * math.sin(math.radians(a))
        body += (
            f'<line x1="256" y1="300" x2="{x:.0f}" y2="{y:.0f}" stroke="{E}" stroke-width="20"/>'
        )
        body += f'<line x1="256" y1="300" x2="{x:.0f}" y2="{y:.0f}" stroke="#38bdf8" stroke-width="10"/>'
    body += "</g>"
    body += f'<g filter="url(#sh)">{pill(36, 286, 440, 150, "url(#jg)", E)}</g>'
    body += fit(pop("JUNGLE GYM", "Titan One", "#fff", E, sw=12, depth=6), 66, 312, 380, 98)
    return svg(body, d)


@kid("Tree Fort", "kids", "adventure", "outdoors")
def tree_fort():
    E = "#1f2a14"
    d = (
        SH
        + shine("leaf", "#a3e635", "#4d9a2a", "#2f6b1a")
        + shine("wood", "#d6a368", "#a0703c", "#6b4423")
    )
    body = '<g filter="url(#sh)">'
    body += f'<rect x="228" y="250" width="56" height="210" fill="url(#wood)" stroke="{E}" stroke-width="7"/>'
    body += puff(
        [(160, 170, 90), (256, 120, 110), (352, 170, 90), (206, 230, 80), (306, 230, 80)],
        "url(#leaf)",
        E,
        7,
    )
    body += "</g>"
    body += f'<g filter="url(#sh)"><path d="M186 150 L256 96 L326 150 Z" fill="#dc2626" stroke="{E}" stroke-width="7" stroke-linejoin="round"/>'
    body += f'<rect x="196" y="150" width="120" height="86" fill="url(#wood)" stroke="{E}" stroke-width="7"/></g>'
    body += f'<rect x="240" y="180" width="32" height="56" rx="4" fill="{E}"/>'
    body += f'<g filter="url(#sh)"><rect x="56" y="318" width="400" height="110" rx="12" fill="url(#wood)" stroke="{E}" stroke-width="8" transform="rotate(-3 256 373)"/></g>'
    body += f'<g transform="rotate(-3 256 373)">{fit(pop("TREE FORT", "Titan One", "#fff7e0", E, sw=10, depth=5), 86, 336, 340, 74)}</g>'
    return svg(body, d)


@kid("Treasure Chest", "kids", "adventure", "pirates")
def treasure_chest():
    E = "#2b1408"
    d = (
        SH
        + shine("tcw", "#d6a368", "#a0703c", "#6b4423")
        + rad("tcg", [(0, "#fff7c2"), (1, "#f59e0b")], cy=0.8, r=0.7)
        + shine("tcb", "#fff3c4", "#e2b13c", "#a8741a")
    )
    body = '<circle cx="256" cy="230" r="190" fill="url(#tcg)" opacity=".45"/>'
    for k in range(12):
        a = math.radians(-180 + k * 15)
        body += f'<line x1="256" y1="210" x2="{256 + 220 * math.cos(a):.0f}" y2="{210 + 220 * math.sin(a):.0f}" stroke="#fde68a" stroke-width="10" stroke-linecap="round" opacity=".55"/>'
    body += '<g filter="url(#sh)">'
    body += f'<path d="M86 210 Q86 120 256 120 Q426 120 426 210 Z" fill="url(#tcw)" stroke="{E}" stroke-width="8"/>'
    body += f'<rect x="86" y="210" width="340" height="230" rx="10" fill="url(#tcw)" stroke="{E}" stroke-width="8"/>'
    for x in (120, 380):
        body += f'<rect x="{x - 14}" y="124" width="28" height="316" fill="url(#tcb)" stroke="{E}" stroke-width="5"/>'
    body += "</g>"
    body += f'<rect x="226" y="196" width="60" height="60" rx="8" fill="url(#tcb)" stroke="{E}" stroke-width="6"/><circle cx="256" cy="220" r="8" fill="{E}"/><rect x="252" y="222" width="8" height="18" fill="{E}"/>'
    body += f'<g filter="url(#sh)">{ribbon(40, 472, 290, 88, "#dc2626", "#991b1b", E, sw=6, tail=36, drop=18)}</g>'
    body += fit(pop("TREASURE CHEST", "Lilita One", "#ffd23f", E, sw=10, depth=5), 70, 302, 372, 62)
    return svg(body, d)


@kid("Dino Dig", "kids", "dinosaurs", "learning")
def dino_dig():
    E = "#3b2410"
    d = SH + rad("sand", [(0, "#fde68a"), (1, "#d6a35c")])
    body = f'<g filter="url(#sh)"><path d="{blob(256, 236, 210, 14, 0.06, 4, 1.05, 0.95)}" fill="url(#sand)" stroke="{E}" stroke-width="8"/></g>'
    rng = random.Random(2)
    for _ in range(26):
        body += f'<circle cx="{rng.uniform(90, 420):.0f}" cy="{rng.uniform(70, 400):.0f}" r="{rng.uniform(2, 5):.1f}" fill="#b07a3e" opacity=".5"/>'
    foot = ""
    for ang in (-32, 0, 32):
        foot += f'<ellipse cx="100" cy="58" rx="22" ry="52" fill="#8b5a2b" stroke="{E}" stroke-width="6" transform="rotate({ang} 100 150)"/>'
    foot += (
        f'<ellipse cx="100" cy="150" rx="52" ry="44" fill="#8b5a2b" stroke="{E}" stroke-width="6"/>'
    )
    body += centred(foot, 256, 150, 170)
    body += fit(pop("DINO", "Titan One", "#22c55e", E, sw=12, depth=7), 136, 240, 240, 88)
    body += fit(pop("DIG", "Titan One", "#f97316", E, sw=12, depth=7), 176, 334, 160, 80)
    return svg(body, d)


@kid("Bug Jar", "kids", "nature", "outdoors")
def bug_jar():
    E = "#1e293b"
    d = (
        SH
        + lin("jar", [(0, "#e0f2fe"), (0.5, "#bae6fd"), (1, "#7dd3fc")], x2=1, y2=0)
        + shine("lid", "#fecaca", "#ef4444", "#991b1b")
    )
    body = f'<g filter="url(#sh)"><path d="M126 120 L386 120 L396 160 Q420 180 420 230 L420 420 Q420 466 374 466 L138 466 Q92 466 92 420 L92 230 Q92 180 116 160 Z" fill="url(#jar)" fill-opacity=".85" stroke="{E}" stroke-width="8"/></g>'
    body += f'<g filter="url(#sh)"><rect x="110" y="70" width="292" height="62" rx="14" fill="url(#lid)" stroke="{E}" stroke-width="8"/></g>'
    for x in (170, 220, 270, 320):
        body += f'<circle cx="{x + 10}" cy="100" r="7" fill="{E}"/>'
    body += gleam(140, 260, 16, 70, 0, 0.6)
    for x, y in ((180, 200), (330, 220), (300, 400), (150, 410)):
        body += f'<circle cx="{x}" cy="{y}" r="16" fill="#fef08a" opacity=".55"/><circle cx="{x}" cy="{y}" r="7" fill="#facc15"/>'
    body += f'<g filter="url(#sh)"><rect x="112" y="250" width="288" height="126" rx="12" fill="#fff7e0" stroke="{E}" stroke-width="6"/></g>'
    body += fit(pop("BUG JAR", "Titan One", "#16a34a", E, sw=10, depth=5), 132, 270, 248, 86)
    return svg(body, d)


@kid("Lemonade Stand", "kids", "comedy", "summer")
def lemonade_stand():
    E = "#3b2a05"
    d = SH + shine("lw", "#d6a368", "#b07a3e", "#7a4d1f")
    body = '<g filter="url(#sh)">'
    for i in range(8):
        x = 40 + i * 54
        c = "#facc15" if i % 2 == 0 else "#fff"
        body += f'<path d="M{x} 70 L{x + 54} 70 L{x + 54} 150 Q{x + 27} 176 {x} 150 Z" fill="{c}" stroke="{E}" stroke-width="5"/>'
    body += f'<rect x="34" y="56" width="444" height="20" rx="8" fill="#f59e0b" stroke="{E}" stroke-width="5"/>'
    body += f'<rect x="60" y="300" width="392" height="160" rx="8" fill="url(#lw)" stroke="{E}" stroke-width="7"/>'
    body += "</g>"
    for x in (76, 436):
        body += f'<rect x="{x - 8}" y="150" width="16" height="152" fill="url(#lw)" stroke="{E}" stroke-width="4"/>'
    body += f'<g filter="url(#sh)"><rect x="96" y="186" width="320" height="104" rx="14" fill="#fff7e0" stroke="{E}" stroke-width="6"/></g>'
    body += fit(pop("LEMONADE", "Lilita One", "#facc15", E, sw=10, depth=5), 116, 200, 280, 74)
    body += fit(pop("STAND", "Lilita One", "#fff7e0", E, sw=10, depth=5), 156, 330, 200, 90)
    return svg(body, d)


@kid("Ice Cream Truck", "kids", "summer", "comedy")
def ice_cream_truck():
    E = "#3b1d2a"
    d = (
        SH
        + lin("cone", [(0, "#f6c27a"), (1, "#b7742e")])
        + shine("scoop", "#fff0f6", "#f9a8d4", "#ec4899")
    )
    body = '<g filter="url(#sh)">'
    body += f'<path d="M176 210 L336 210 L256 470 Z" fill="url(#cone)" stroke="{E}" stroke-width="8" stroke-linejoin="round"/>'
    body += puff(
        [(196, 196, 50), (256, 160, 66), (316, 196, 50), (256, 210, 50)], "url(#scoop)", E, 7
    )
    body += "</g>"
    for i in range(4):
        body += f'<line x1="{196 + i * 30}" y1="216" x2="{246 + i * 12}" y2="400" stroke="#8a5a2b" stroke-width="3" opacity=".5"/>'
    body += f'<circle cx="262" cy="96" r="18" fill="#ef4444" stroke="{E}" stroke-width="5"/>'
    for x, y, c in (
        (220, 150, "#22d3ee"),
        (290, 140, "#facc15"),
        (250, 190, "#a3e635"),
        (310, 190, "#a78bfa"),
    ):
        body += f'<rect x="{x}" y="{y}" width="16" height="6" rx="3" fill="{c}" transform="rotate(30 {x} {y})"/>'
    body += f'<g filter="url(#sh)">{ribbon(40, 472, 270, 84, "#38bdf8", "#0369a1", E, sw=6, tail=36, drop=18)}</g>'
    body += fit(pop("ICE CREAM TRUCK", "Lilita One", "#fff", E, sw=10, depth=5), 68, 282, 376, 60)
    return svg(body, d)


@kid("Bouncy Castle", "kids", "party", "comedy")
def bouncy_castle():
    E = "#1e1b4b"
    d = (
        SH
        + shine("bc1", "#93c5fd", "#3b82f6", "#1d4ed8")
        + shine("bc2", "#fecaca", "#ef4444", "#b91c1c")
        + shine("bc3", "#fef08a", "#facc15", "#ca8a04")
    )
    body = '<g filter="url(#sh)">'
    body += puff(
        [(80, 150, 46), (432, 150, 46)],
        "url(#bc2)",
        E,
        7,
        rects=((50, 150, 60, 240, 30), (402, 150, 60, 240, 30)),
    )
    body += puff([(256, 120, 52)], "url(#bc3)", E, 7, rects=((216, 120, 80, 120, 30),))
    body += puff([], "url(#bc1)", E, 7, rects=((90, 210, 332, 230, 46),))
    body += "</g>"
    for x in (80, 256, 432):
        body += f'<path d="M{x} {72 if x == 256 else 104} l0 -30 l26 10 l-26 10" fill="#ef4444" stroke="{E}" stroke-width="4"/>'
    for x in range(122, 400, 60):
        body += f'<line x1="{x}" y1="230" x2="{x}" y2="420" stroke="#fff" stroke-width="4" opacity=".3"/>'
    body += fit(pop("BOUNCY", "Titan One", "#fff", E, sw=12, depth=6), 120, 236, 272, 86)
    body += fit(pop("CASTLE", "Titan One", "#facc15", E, sw=12, depth=6), 130, 330, 252, 86)
    return svg(body, d)


@kid("Kazoo", "kids", "music", "comedy")
def kazoo():
    E = "#1c1917"
    d = SH + shine("kz", "#fda4af", "#f43f5e", "#be123c")
    body = '<g filter="url(#sh)" transform="rotate(-10 256 256)">'
    body += f'<path d="M40 210 L380 186 Q470 186 470 256 Q470 326 380 326 L40 302 Q24 256 40 210 Z" fill="url(#kz)" stroke="{E}" stroke-width="8"/>'
    body += f'<rect x="250" y="166" width="70" height="34" rx="10" fill="#facc15" stroke="{E}" stroke-width="6"/>'
    body += "</g>"
    body += f'<g transform="rotate(-10 256 256)">{fit(pop("KAZOO", "Titan One", "#fff", E, sw=12, depth=6), 70, 214, 330, 96)}</g>'
    for x, y in ((440, 160), (476, 120), (460, 210)):
        body += f'<path d="M{x} {y} q10 -14 20 0 t20 0" fill="none" stroke="#facc15" stroke-width="6" stroke-linecap="round"/>'
    body += fit(
        text("TOOT-TOOT TUNES", "Fredoka", 40, weight=700, fill="#fde68a", stroke=E, sw=6, ls=6),
        136,
        366,
        240,
        30,
    )
    return svg(body, d)


@kid("Field Trip", "kids", "learning", "adventure")
def field_trip():
    E = "#1e3a2b"
    d = SH + shine("ft", "#fef3c7", "#fde68a", "#e7c46a")
    body = f'<g filter="url(#sh)"><path d="M40 90 L180 60 L330 100 L472 70 L472 420 L330 450 L180 410 L40 440 Z" fill="url(#ft)" stroke="{E}" stroke-width="7" stroke-linejoin="round"/></g>'
    body += (
        f'<path d="M180 60 L180 410 M330 100 L330 450" stroke="{E}" stroke-width="3" opacity=".3"/>'
    )
    body += '<path d="M80 380 Q140 300 220 330 T360 220 T420 140" fill="none" stroke="#dc2626" stroke-width="7" stroke-dasharray="14 12" stroke-linecap="round"/>'
    body += f'<path d="M420 92 C400 92 388 108 388 124 C388 148 420 176 420 176 C420 176 452 148 452 124 C452 108 440 92 420 92 Z" fill="#dc2626" stroke="{E}" stroke-width="5"/><circle cx="420" cy="124" r="10" fill="#fff"/>'
    body += f'<g filter="url(#sh)">{pill(56, 200, 340, 120, "#16a34a", E)}</g>'
    body += fit(pop("FIELD TRIP", "Titan One", "#fff", E, sw=10, depth=5), 82, 222, 288, 76)
    return svg(body, d)


@kid("Show & Tell", "kids", "learning", "comedy")
def show_and_tell():
    E = "#1e1b4b"
    d = SH + shine("st", "#c4b5fd", "#8b5cf6", "#6d28d9")
    bub = "M70 90 L442 90 Q472 90 472 120 L472 330 Q472 360 442 360 L210 360 L140 430 L150 360 L70 360 Q40 360 40 330 L40 120 Q40 90 70 90 Z"
    body = f'<g filter="url(#sh)"><path d="{bub}" fill="url(#st)" stroke="{E}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += gleam(120, 130, 50, 14, -8, 0.35)
    body += fit(pop("SHOW", "Titan One", "#facc15", E, sw=12, depth=6), 70, 120, 230, 100)
    body += starp(380, 170, 52, "#f472b6", E, 6)
    body += fit(text("&", "Titan One", 100, fill="#fff"), 362, 148, 36, 44)
    body += fit(pop("TELL", "Titan One", "#fff", E, sw=12, depth=6), 196, 230, 246, 100)
    return svg(body, d)


@kid("Snow Cone", "kids", "summer", "comedy")
def snow_cone():
    E = "#1e1b4b"
    d = SH
    body = '<defs><clipPath id="scd"><circle cx="256" cy="200" r="150"/></clipPath></defs>'
    body += f'<g filter="url(#sh)"><circle cx="256" cy="200" r="158" fill="{E}"/></g>'
    body += '<g clip-path="url(#scd)">'
    for i, c in enumerate(("#f472b6", "#a78bfa", "#38bdf8")):
        body += f'<rect x="{106 + i * 100}" y="40" width="100" height="320" fill="{c}"/>'
    rng = random.Random(4)
    for _ in range(40):
        body += f'<circle cx="{rng.uniform(110, 400):.0f}" cy="{rng.uniform(60, 300):.0f}" r="{rng.uniform(3, 7):.1f}" fill="#fff" opacity=".55"/>'
    body += "</g>"
    body += f'<g filter="url(#sh)"><path d="M116 250 L396 250 L320 476 L192 476 Z" fill="#fff" stroke="{E}" stroke-width="8" stroke-linejoin="round"/></g>'
    for x in (150, 196, 242, 288, 334, 370):
        body += f'<line x1="{x}" y1="252" x2="{256 + (x - 256) * 0.45:.0f}" y2="474" stroke="#93c5fd" stroke-width="5"/>'
    body += f'<g filter="url(#sh)">{pill(60, 290, 392, 100, "#ef4444", E)}</g>'
    body += fit(pop("SNOW CONE", "Titan One", "#fff", E, sw=10, depth=5), 88, 306, 336, 66)
    return svg(body, d)


@kid("Gumdrop", "kids", "candy", "comedy")
def gumdrop():
    E = "#3b0764"
    d = SH
    drops = (
        ("#ef4444", "#fca5a5", 130, 210, 80),
        ("#22c55e", "#86efac", 382, 210, 80),
        ("#f59e0b", "#fde68a", 256, 170, 100),
    )
    body = ""
    for c, lc, x, y, r in drops:
        body += f'<g filter="url(#sh)"><path d="M{x - r} {y + r * 0.7} Q{x - r} {y - r} {x} {y - r} Q{x + r} {y - r} {x + r} {y + r * 0.7} Q{x} {y + r * 0.95} {x - r} {y + r * 0.7} Z" fill="{c}" stroke="{E}" stroke-width="7"/></g>'
        body += gleam(x - r * 0.4, y - r * 0.4, r * 0.25, r * 0.12, -30, 0.7)
        rng = random.Random(x)
        for _ in range(10):
            body += f'<rect x="{x + rng.uniform(-r * 0.7, r * 0.7):.0f}" y="{y + rng.uniform(-r * 0.6, r * 0.5):.0f}" width="5" height="5" fill="{lc}" opacity=".9" transform="rotate(45 {x} {y})"/>'
    body += fit(
        pop("GUMDROP", "Titan One", "#fff", E, sw=12, depth=7, outer="#f9a8d4", osw=8),
        50,
        296,
        412,
        130,
    )
    return svg(body, d)


def _swirl(p: P) -> str:
    s = f'<circle cx="100" cy="100" r="92" fill="{p.l}" stroke="{p.k}" stroke-width="10"/>'
    path = "M100 100"
    for k in range(1, 60):
        a = k * 0.32
        r = 4 + k * 1.45
        path += f" L{100 + r * math.cos(a):.1f} {100 + r * math.sin(a):.1f}"
    s += f'<path d="{path}" fill="none" stroke="{p.a}" stroke-width="16" stroke-linecap="round"/>'
    s += f'<path d="{path}" fill="none" stroke="{p.b}" stroke-width="6" stroke-linecap="round" transform="rotate(40 100 100)"/>'
    return s


@kid("Lollipop", "kids", "candy", "comedy")
def lollipop():
    E = "#4a044e"
    d = SH
    body = f'<line x1="256" y1="250" x2="256" y2="470" stroke="{E}" stroke-width="26" stroke-linecap="round"/><line x1="256" y1="250" x2="256" y2="470" stroke="#fff" stroke-width="14" stroke-linecap="round"/>'
    body += f'<g filter="url(#sh)">{centred(_swirl(P(a="#ec4899", b="#22d3ee", c="#fff", k=E, l="#fff")), 256, 170, 300)}</g>'
    body += gleam(196, 96, 40, 18, -30, 0.6)
    body += f'<g filter="url(#sh)">{pill(46, 300, 420, 110, "#facc15", E)}</g>'
    body += fit(pop("LOLLIPOP", "Titan One", "#ec4899", E, sw=10, depth=6), 76, 316, 360, 78)
    return svg(body, d)


@kid("Secret Clubhouse", "kids", "adventure", "comedy")
def secret_clubhouse():
    E = "#2b1408"
    d = SH + lin("door", [(0, "#a0703c"), (0.5, "#c08a4d"), (1, "#8b5a2b")], x2=1, y2=0)
    body = f'<g filter="url(#sh)"><path d="M120 470 L120 130 Q120 50 256 50 Q392 50 392 130 L392 470 Z" fill="url(#door)" stroke="{E}" stroke-width="8"/></g>'
    for x in (180, 256, 332):
        body += f'<line x1="{x}" y1="60" x2="{x}" y2="470" stroke="{E}" stroke-width="3" opacity=".35"/>'
    body += '<circle cx="256" cy="128" r="22" fill="#1c1917" stroke="#facc15" stroke-width="6"/>'
    body += f'<circle cx="360" cy="320" r="12" fill="#facc15" stroke="{E}" stroke-width="4"/>'
    body += f'<g filter="url(#sh)"><rect x="40" y="186" width="432" height="120" rx="10" fill="#fff7e0" stroke="{E}" stroke-width="7" transform="rotate(-4 256 246)"/></g>'
    body += f'<g transform="rotate(-4 256 246)">{fit(text("SECRET", "Permanent Marker", 100, fill="#dc2626"), 76, 196, 360, 56)}'
    body += (
        fit(text("CLUBHOUSE", "Permanent Marker", 100, fill="#1e3a8a"), 76, 250, 360, 46) + "</g>"
    )
    body += f'<g filter="url(#sh)"><rect x="150" y="366" width="212" height="54" rx="6" fill="#dc2626" stroke="{E}" stroke-width="5" transform="rotate(3 256 393)"/></g>'
    body += f'<g transform="rotate(3 256 393)">{fit(text("MEMBERS ONLY", "Oswald", 40, weight=700, fill="#fff", ls=4), 166, 376, 180, 34)}</g>'
    return svg(body, d)


@kid("Paper Airplane", "kids", "adventure", "arts and crafts")
def paper_airplane():
    E = "#1e3a8a"
    d = SH
    body = '<path d="M50 300 Q140 200 230 250 T380 170" fill="none" stroke="#93c5fd" stroke-width="7" stroke-dasharray="4 16" stroke-linecap="round"/>'
    body += '<g filter="url(#sh)">'
    body += f'<polygon points="470,60 250,170 330,190" fill="#fff" stroke="{E}" stroke-width="6" stroke-linejoin="round"/>'
    body += f'<polygon points="470,60 330,190 340,260" fill="#dbeafe" stroke="{E}" stroke-width="6" stroke-linejoin="round"/>'
    body += f'<polygon points="470,60 340,260 300,210" fill="#bfdbfe" stroke="{E}" stroke-width="6" stroke-linejoin="round"/>'
    body += "</g>"
    body += fit(pop("PAPER", "Titan One", "#38bdf8", E, sw=12, depth=6), 60, 290, 240, 80)
    body += fit(pop("AIRPLANE", "Titan One", "#fff", E, sw=12, depth=6), 60, 376, 392, 90)
    return svg(body, d)


@kid("Scooter", "kids", "sports", "outdoors")
def scooter():
    E = "#111827"
    d = SH + shine("sco", "#a5f3fc", "#06b6d4", "#0e7490")
    body = '<g filter="url(#sh)">'
    body += f'<path d="M400 330 L380 90" stroke="{E}" stroke-width="24" stroke-linecap="round"/><path d="M400 330 L380 90" stroke="#94a3b8" stroke-width="12" stroke-linecap="round"/>'
    body += f'<line x1="334" y1="88" x2="430" y2="82" stroke="{E}" stroke-width="22" stroke-linecap="round"/><line x1="334" y1="88" x2="430" y2="82" stroke="#ef4444" stroke-width="12" stroke-linecap="round"/>'
    body += f'<rect x="40" y="290" width="380" height="60" rx="30" fill="url(#sco)" stroke="{E}" stroke-width="7"/>'
    for cx in (96, 404):
        body += f'<circle cx="{cx}" cy="384" r="40" fill="#1f2937" stroke="{E}" stroke-width="6"/><circle cx="{cx}" cy="384" r="16" fill="#facc15"/>'
    body += "</g>"
    body += fit(pop("SCOOTER", "Titan One", "#facc15", E, sw=12, depth=6), 56, 160, 300, 110)
    return svg(body, d)


@kid("Science Fair", "kids", "science", "learning")
def science_fair():
    E = "#1e293b"
    d = SH + shine("sfr", "#fecaca", "#ef4444", "#b91c1c")
    body = '<g filter="url(#sh)">'
    body += f'<polygon points="30,100 140,120 140,420 30,440" fill="#bfdbfe" stroke="{E}" stroke-width="6" stroke-linejoin="round"/>'
    body += f'<polygon points="482,100 372,120 372,420 482,440" fill="#bfdbfe" stroke="{E}" stroke-width="6" stroke-linejoin="round"/>'
    body += f'<rect x="140" y="120" width="232" height="300" fill="#eff6ff" stroke="{E}" stroke-width="6"/>'
    body += "</g>"
    for x, y in ((50, 160), (50, 300), (392, 160), (392, 300)):
        body += f'<rect x="{x}" y="{y}" width="72" height="90" rx="4" fill="#fff" stroke="#93c5fd" stroke-width="3"/>'
    body += (
        '<path d="M228 150 L228 196 L196 262 Q190 276 206 276 L306 276 Q322 276 316 262 L284 196 L284 150 Z" fill="#a3e635" stroke="'
        + E
        + '" stroke-width="6" stroke-linejoin="round"/>'
    )
    body += (
        '<rect x="220" y="140" width="72" height="16" rx="4" fill="#94a3b8" stroke="'
        + E
        + '" stroke-width="4"/>'
    )
    for x, y, r in ((238, 240, 8), (262, 226, 6), (276, 252, 7)):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" opacity=".8"/>'
    body += fit(pop("SCIENCE", "Titan One", "#2563eb", E, sw=10, depth=5), 150, 290, 212, 56)
    body += fit(pop("FAIR", "Titan One", "#ef4444", E, sw=10, depth=5), 186, 350, 140, 56)
    body += f'<g filter="url(#sh)"><circle cx="420" cy="90" r="40" fill="#2563eb" stroke="{E}" stroke-width="6"/><path d="M400 120 L392 180 L414 166 L424 186 L432 124 Z" fill="#2563eb" stroke="{E}" stroke-width="5"/></g>'
    body += fit(text("1st", "Titan One", 100, fill="#fff"), 400, 72, 40, 34)
    return svg(body, d)


@kid("Magic Wand", "kids", "fantasy", "magic")
def magic_wand():
    E = "#2e1065"
    d = SH + shine("mw", "#fff6a8", "#ffd23f", "#f0a202")
    body = f'<line x1="120" y1="250" x2="300" y2="100" stroke="{E}" stroke-width="30" stroke-linecap="round"/>'
    body += '<line x1="120" y1="250" x2="300" y2="100" stroke="#a855f7" stroke-width="16" stroke-linecap="round"/>'
    body += f'<g filter="url(#sh)">{starp(320, 84, 64, "url(#mw)", E, 7)}</g>'
    for x, y, r in ((420, 60, 18), (400, 160, 12), (220, 60, 14), (452, 110, 9), (360, 200, 8)):
        body += sparkle(x, y, r, "#facc15")
    body += fit(
        pop("MAGIC", "Titan One", "#c084fc", E, sw=12, depth=7, outer="#fff", osw=6),
        66,
        270,
        380,
        100,
    )
    body += fit(pop("WAND", "Titan One", "#facc15", E, sw=12, depth=7), 136, 376, 240, 90)
    return svg(body, d)


@kid("Pirate Cove", "kids", "pirates", "adventure")
def pirate_cove():
    E = "#1c1917"
    d = (
        SH
        + rad("sea", [(0, "#67e8f9"), (1, "#0e7490")])
        + shine("helm", "#d6a368", "#a0703c", "#6b4423")
    )
    body = f'<g filter="url(#sh)"><circle cx="256" cy="210" r="186" fill="url(#sea)" stroke="{E}" stroke-width="8"/></g>'
    for k in range(8):
        a = math.radians(k * 45)
        body += f'<line x1="{256 + 40 * math.cos(a):.0f}" y1="{210 + 40 * math.sin(a):.0f}" x2="{256 + 164 * math.cos(a):.0f}" y2="{210 + 164 * math.sin(a):.0f}" stroke="{E}" stroke-width="22" stroke-linecap="round"/>'
        body += f'<line x1="{256 + 40 * math.cos(a):.0f}" y1="{210 + 40 * math.sin(a):.0f}" x2="{256 + 164 * math.cos(a):.0f}" y2="{210 + 164 * math.sin(a):.0f}" stroke="url(#helm)" stroke-width="12" stroke-linecap="round"/>'
    body += f'<circle cx="256" cy="210" r="118" fill="none" stroke="{E}" stroke-width="30"/><circle cx="256" cy="210" r="118" fill="none" stroke="url(#helm)" stroke-width="18"/>'
    body += f'<circle cx="256" cy="210" r="40" fill="url(#helm)" stroke="{E}" stroke-width="7"/>'
    body += f'<g filter="url(#sh)">{ribbon(40, 472, 320, 92, "#dc2626", "#991b1b", E, sw=6, tail=36, drop=18)}</g>'
    body += fit(pop("PIRATE COVE", "Pirata One", "#facc15", E, sw=8, depth=4), 70, 330, 372, 72)
    return svg(body, d)


@kid("Rocket Club", "kids", "space", "science")
def rocket_club():
    E = "#0f172a"
    d = SH + rad("rcb", [(0, "#1e3a8a"), (1, "#0b1026")])
    body = f'<g filter="url(#sh)"><circle cx="256" cy="256" r="226" fill="#f97316" stroke="{E}" stroke-width="8"/></g>'
    body += f'<circle cx="256" cy="256" r="160" fill="url(#rcb)" stroke="{E}" stroke-width="6"/>'
    rng = random.Random(1)
    for _ in range(20):
        a, r = rng.uniform(0, 6.28), rng.uniform(20, 150)
        body += f'<circle cx="{256 + r * math.cos(a):.0f}" cy="{256 + r * math.sin(a):.0f}" r="2.5" fill="#fff"/>'
    body += f'<circle cx="256" cy="256" r="60" fill="#22c55e" stroke="{E}" stroke-width="6"/>'
    body += '<path d="M120 300 A140 50 -20 0 0 400 200" fill="none" stroke="#fde68a" stroke-width="5" stroke-dasharray="10 10"/>'
    rk = S.rocket(P(a="#ef4444", b="#facc15", c="#7dd3fc", k=E, l="#f8fafc"))
    body += f'<g transform="rotate(50 360 170)">{centred(rk, 360, 170, 110)}</g>'
    a1, b1 = arc_text(
        "ROCKET CLUB", "Titan One", 256, 256, 192, 46, fill="#fff", ls=6, pid="rct", stroke=E, sw=8
    )
    a2, b2 = arc_text(
        "MEMBERS · SINCE · LIFTOFF",
        "Fredoka",
        256,
        256,
        192,
        22,
        weight=700,
        fill=E,
        ls=4,
        pid="rcb2",
        bottom=True,
    )
    return svg(body + b1 + b2, d + a1 + a2)


@kid("Kite String", "kids", "outdoors", "adventure")
def kite_string():
    E = "#1e1b4b"
    d = SH
    body = '<path d="M256 260 Q200 330 240 380 T200 470" fill="none" stroke="#475569" stroke-width="4"/>'
    for i, (x, y) in enumerate(((236, 312), (222, 350), (236, 392))):
        c = ("#f472b6", "#facc15", "#22d3ee")[i]
        body += f'<path d="M{x} {y} l-18 -12 l0 24 Z M{x} {y} l18 -12 l0 24 Z" fill="{c}" stroke="{E}" stroke-width="3"/>'
    body += '<g filter="url(#sh)">'
    body += f'<polygon points="256,20 360,140 256,260 152,140" fill="#ef4444" stroke="{E}" stroke-width="7" stroke-linejoin="round"/>'
    body += '<polygon points="256,20 360,140 256,140" fill="#facc15"/><polygon points="152,140 256,140 256,260" fill="#3b82f6"/>'
    body += f'<polygon points="256,20 360,140 256,260 152,140" fill="none" stroke="{E}" stroke-width="7" stroke-linejoin="round"/>'
    body += f'<line x1="256" y1="20" x2="256" y2="260" stroke="{E}" stroke-width="4"/><line x1="152" y1="140" x2="360" y2="140" stroke="{E}" stroke-width="4"/>'
    body += "</g>"
    body += fit(pop("KITE", "Titan One", "#22d3ee", E, sw=12, depth=6), 290, 250, 190, 90)
    body += fit(pop("STRING", "Titan One", "#fff", E, sw=12, depth=6), 270, 350, 220, 80)
    return svg(body, d)


@kid("Marble Run", "kids", "toys", "science")
def marble_run():
    E = "#1e293b"
    d = SH + shine("track", "#fde68a", "#f59e0b", "#b45309")
    body = '<g filter="url(#sh)">'
    for x1, y1, x2, y2 in ((40, 70, 400, 120), (472, 170, 110, 220), (40, 270, 400, 320)):
        body += f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{E}" stroke-width="30" stroke-linecap="round"/><line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="url(#track)" stroke-width="18" stroke-linecap="round"/>'
    body += "</g>"
    marbles = (
        (120, 64, "#ef4444"),
        (300, 88, "#3b82f6"),
        (380, 170, "#22c55e"),
        (180, 228, "#a855f7"),
        (330, 286, "#f472b6"),
    )
    for x, y, c in marbles:
        body += f'<circle cx="{x}" cy="{y}" r="22" fill="{c}" stroke="{E}" stroke-width="5"/>{gleam(x - 7, y - 8, 7, 4, -30, 0.8)}'
    body += fit(pop("MARBLE RUN", "Titan One", "#fff", E, sw=12, depth=6), 40, 350, 432, 110)
    return svg(body, d)


def _panel_k(x, y, w, h, fill, rx, edge, sw=7):
    return f'<g filter="url(#sh)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{edge}" stroke-width="{sw}"/></g>'


# ======================================================================= kids' movies & family


@kid("Kiddie Matinee", "kids", "movies", "family")
def kiddie_matinee():
    E = "#3b0764"
    d = SH + shine("km", "#fda4af", "#f43f5e", "#be123c")
    body = '<g filter="url(#sh)">'
    body += f'<path d="M110 150 Q110 50 256 50 Q402 50 402 150 Z" fill="url(#km)" stroke="{E}" stroke-width="8"/>'
    body += f'<rect x="40" y="150" width="432" height="250" rx="22" fill="url(#km)" stroke="{E}" stroke-width="8"/>'
    body += "</g>"
    for k in range(9):
        a = math.radians(180 + k * 22.5)
        body += f'<circle cx="{256 + 126 * math.cos(a):.0f}" cy="{150 + 86 * math.sin(a):.0f}" r="8" fill="#fef9c3" stroke="#b45309" stroke-width="2"/>'
    for x in range(66, 460, 30):
        for y in (172, 378):
            body += f'<circle cx="{x}" cy="{y}" r="7" fill="#fef9c3" stroke="#b45309" stroke-width="2"/>'
    body += fit(pop("KIDDIE", "Titan One", "#fff", E, sw=10, depth=5), 166, 76, 180, 64)
    body += f'<rect x="74" y="196" width="364" height="160" rx="10" fill="#fff7e0" stroke="{E}" stroke-width="6"/>'
    body += fit(text("MATINEE", "Oswald", 100, weight=700, fill=E, ls=10), 96, 216, 320, 92)
    body += fit(
        text("SATURDAYS AT NOON", "Oswald", 40, weight=600, fill="#be123c", ls=6), 140, 318, 232, 24
    )
    body += f'<rect x="236" y="400" width="40" height="64" fill="{E}"/>'
    return svg(body, d)


@kid("Pajama Premiere", "kids", "movies", "bedtime")
def pajama_premiere():
    E = "#1e1b4b"
    d = (
        SH
        + lin("ppn", [(0, "#312e81"), (1, "#1e1b4b")])
        + shine("ppg", "#fff6a8", "#ffd23f", "#f0a202")
    )
    body = '<defs><clipPath id="ppc"><rect x="36" y="56" width="440" height="400" rx="40"/></clipPath></defs>'
    body += _panel_k(36, 56, 440, 400, "url(#ppn)", 40, E)
    body += '<g clip-path="url(#ppc)">'
    for x, ang in ((100, 24), (412, -24)):
        body += f'<polygon points="{x - 16},470 {x + 16},470 {x + 16 + 420 * math.sin(math.radians(ang)):.0f},40 {x - 16 + 420 * math.sin(math.radians(ang)) - 60:.0f},40" fill="#fef9c3" opacity=".16"/>'
    body += '<path d="M150 470 L362 470 L300 330 L212 330 Z" fill="#dc2626"/>'
    body += "</g>"
    body += f'<path d="{crescent_path(380, 120, 36, 16, -10, 32)}" fill="#fde68a"/>'
    for x, y in ((100, 110), (170, 90), (300, 80), (440, 200)):
        body += sparkle(x, y, 10, "#fff")
    body += fit(
        pop("PAJAMA", "Fredoka", "#c4b5fd", E, sw=10, depth=5, weight=700), 76, 150, 360, 90
    )
    body += fit(
        pop("PREMIERE", "Fredoka", "url(#ppg)", E, sw=10, depth=5, weight=700), 76, 246, 360, 80
    )
    return svg(body, d)


@kid("Family Flicks", "kids", "family", "movies")
def family_flicks():
    E = "#3b0a0a"
    d = SH
    body = '<g filter="url(#sh)">'
    for x, y, r in (
        (170, 120, 44),
        (226, 92, 50),
        (290, 96, 48),
        (344, 128, 42),
        (256, 140, 50),
        (196, 160, 40),
        (320, 166, 40),
    ):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff7e0" stroke="{E}" stroke-width="6"/>'
    body += "</g>"
    body += '<defs><clipPath id="ffb"><path d="M120 170 L392 170 L362 470 L150 470 Z"/></clipPath></defs>'
    body += f'<g filter="url(#sh)"><path d="M120 170 L392 170 L362 470 L150 470 Z" fill="#fff" stroke="{E}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += '<g clip-path="url(#ffb)">'
    for i in range(7):
        x = 120 + i * 44
        if i % 2 == 0:
            body += (
                f'<polygon points="{x},170 {x + 44},170 {x + 34},470 {x - 6},470" fill="#dc2626"/>'
            )
    body += "</g>"
    body += f'<path d="M120 170 L392 170 L362 470 L150 470 Z" fill="none" stroke="{E}" stroke-width="8" stroke-linejoin="round"/>'
    body += f'<g filter="url(#sh)">{pill(40, 254, 432, 140, "#facc15", E)}</g>'
    body += fit(pop("FAMILY", "Titan One", "#dc2626", E, sw=10, depth=5), 96, 262, 320, 66)
    body += fit(pop("FLICKS", "Titan One", "#fff", E, sw=10, depth=5), 126, 328, 260, 56)
    return svg(body, d)


@kid("Tiny Theater", "kids", "movies", "puppets")
def tiny_theater():
    E = "#1e1b4b"
    d = SH + shine("tt", "#93c5fd", "#3b82f6", "#1d4ed8")
    body = '<g filter="url(#sh)">'
    body += f'<rect x="70" y="80" width="372" height="380" rx="14" fill="url(#tt)" stroke="{E}" stroke-width="8"/>'
    body += "</g>"
    for i in range(7):
        x = 70 + i * 53.1
        c = "#facc15" if i % 2 == 0 else "#fff"
        body += f'<path d="M{x:.0f} 80 L{x + 53:.0f} 80 L{x + 53:.0f} 120 Q{x + 26.5:.0f} 150 {x:.0f} 120 Z" fill="{c}" stroke="{E}" stroke-width="4"/>'
    body += '<rect x="120" y="160" width="272" height="160" rx="8" fill="#1e1b4b"/>'
    body += '<path d="M120 160 Q170 240 140 320 L120 320 Z M392 160 Q342 240 372 320 L392 320 Z" fill="#dc2626"/>'
    body += f'<g filter="url(#sh)">{pill(56, 336, 400, 100, "#f472b6", E)}</g>'
    body += fit(pop("TINY THEATER", "Titan One", "#fff", E, sw=10, depth=5), 80, 352, 352, 66)
    body += fit(text("SHOW TIME!", "Fredoka", 100, weight=700, fill="#fde68a"), 170, 210, 172, 60)
    return svg(body, d)


@kid("Movie Fort", "kids", "movies", "family")
def movie_fort():
    E = "#3b2410"
    d = (
        SH
        + shine("box", "#e8c18e", "#c8955a", "#9a6a35")
        + rad("scr", [(0, "#e0f2fe"), (1, "#38bdf8")])
    )
    top = "M50 140 L50 90 L100 90 L100 120 L150 120 L150 90 L200 90 L200 120 L250 120 L250 90 L300 90 L300 120 L350 120 L350 90 L400 90 L400 120 L462 120 L462 90 L462 460 L50 460 Z"
    body = f'<g filter="url(#sh)"><path d="{top}" fill="url(#box)" stroke="{E}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += f'<line x1="50" y1="300" x2="462" y2="300" stroke="{E}" stroke-width="3" opacity=".3"/>'
    body += f'<rect x="150" y="150" width="212" height="128" rx="10" fill="url(#scr)" stroke="{E}" stroke-width="6"/>'
    body += '<polygon points="236,184 236,244 290,214" fill="#fff"/>'
    body += fit(text("MOVIE", "Permanent Marker", 100, fill="#1e3a8a"), 100, 300, 312, 80)
    body += fit(text("FORT", "Permanent Marker", 100, fill="#dc2626"), 160, 378, 192, 70)
    body += (
        f'<path d="M420 90 L420 40 L460 52 L420 64" fill="#facc15" stroke="{E}" stroke-width="4"/>'
    )
    return svg(body, d)


@kid("Saturday Flicks", "kids", "movies", "saturday morning")
def saturday_flicks():
    E = "#1c1917"
    d = SH + rad("sfs", [(0, "#fde68a"), (1, "#f97316")])
    body = f'<g filter="url(#sh)"><circle cx="256" cy="210" r="170" fill="url(#sfs)" stroke="{E}" stroke-width="8"/></g>'
    for k in range(16):
        a = math.radians(k * 22.5)
        body += f'<line x1="{256 + 180 * math.cos(a):.0f}" y1="{210 + 180 * math.sin(a):.0f}" x2="{256 + 226 * math.cos(a):.0f}" y2="{210 + 226 * math.sin(a):.0f}" stroke="#f97316" stroke-width="10" stroke-linecap="round"/>'
    body += fit(pop("SATURDAY", "Titan One", "#fff", E, sw=10, depth=6), 106, 140, 300, 90)
    strip = '<g filter="url(#sh)" transform="rotate(-4 256 360)"><rect x="30" y="300" width="452" height="120" rx="8" fill="#1c1917"/>'
    for x in range(42, 480, 30):
        strip += f'<rect x="{x}" y="310" width="16" height="12" rx="3" fill="#fef3c7"/><rect x="{x}" y="398" width="16" height="12" rx="3" fill="#fef3c7"/>'
    body += strip + "</g>"
    body += f'<g transform="rotate(-4 256 360)">{fit(text("FLICKS", "Titan One", 100, fill="#facc15", ls=10), 116, 330, 280, 62)}</g>'
    return svg(body, d)


@kid("Family Room", "family", "comedy", "sitcoms")
def family_room():
    E = "#3b2410"
    d = SH + shine("fr", "#fde68a", "#f59e0b", "#d97706")
    body = f'<g filter="url(#sh)"><path d="M256 40 L480 210 L432 210 L432 460 L80 460 L80 210 L32 210 Z" fill="#fff7e0" stroke="{E}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += f'<path d="M256 40 L480 210 L32 210 Z" fill="#dc2626" stroke="{E}" stroke-width="8" stroke-linejoin="round"/>'
    body += f'<rect x="226" y="110" width="60" height="60" rx="6" fill="url(#fr)" stroke="{E}" stroke-width="5"/><line x1="256" y1="110" x2="256" y2="170" stroke="{E}" stroke-width="4"/><line x1="226" y1="140" x2="286" y2="140" stroke="{E}" stroke-width="4"/>'
    body += fit(pop("FAMILY", "Titan One", "#f59e0b", E, sw=10, depth=6), 110, 236, 292, 96)
    body += fit(pop("ROOM", "Titan One", "#dc2626", E, sw=10, depth=6), 150, 342, 212, 86)
    return svg(body, d)


@kid("Minivan", "family", "comedy", "road trip")
def minivan():
    E = "#0f172a"
    d = SH + shine("mv", "#a5f3fc", "#06b6d4", "#0e7490")
    van = "M40 330 L40 210 Q40 150 100 140 L300 120 Q360 118 400 170 L460 230 Q478 248 478 270 L478 330 Q478 350 458 350 L60 350 Q40 350 40 330 Z"
    body = f'<g filter="url(#sh)"><path d="{van}" fill="url(#mv)" stroke="{E}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += f'<path d="M80 160 L190 148 L190 210 L80 210 Z M210 146 L300 138 Q340 138 370 180 L380 210 L210 210 Z" fill="#e0f2fe" stroke="{E}" stroke-width="5" stroke-linejoin="round"/>'
    body += f'<rect x="56" y="104" width="300" height="20" rx="6" fill="#475569" stroke="{E}" stroke-width="4"/>'
    for cx in (130, 380):
        body += f'<circle cx="{cx}" cy="352" r="48" fill="#1f2937" stroke="{E}" stroke-width="6"/><circle cx="{cx}" cy="352" r="20" fill="#cbd5e1"/>'
    body += fit(pop("MINIVAN", "Titan One", "#fff", E, sw=10, depth=5), 80, 226, 360, 80)
    body += fit(
        text("ARE WE THERE YET?", "Fredoka", 40, weight=700, fill="#fde68a", stroke=E, sw=6, ls=4),
        136,
        420,
        240,
        30,
    )
    return svg(body, d)


@kid("Carpool", "family", "comedy", "road trip")
def carpool():
    E = "#111827"
    d = SH
    body = f'<g filter="url(#sh)"><rect x="76" y="40" width="360" height="432" rx="24" fill="#fff" stroke="{E}" stroke-width="10"/></g>'
    body += f'<rect x="96" y="60" width="320" height="392" rx="14" fill="none" stroke="{E}" stroke-width="5"/>'
    body += f'<polygon points="256,86 330,160 256,234 182,160" fill="none" stroke="{E}" stroke-width="14" stroke-linejoin="round"/>'
    body += fit(text("CARPOOL", "Oswald", 100, weight=700, fill=E, ls=4), 116, 256, 280, 90)
    body += f'<rect x="136" y="364" width="240" height="64" rx="8" fill="{E}"/>'
    body += fit(text("LANE", "Oswald", 100, weight=700, fill="#fff", ls=20), 166, 374, 180, 44)
    return svg(body, d)


@kid("Cookout", "family", "summer", "food")
def cookout():
    E = "#3b0a0a"
    d = (
        SH
        + "<pattern id='gng' width='40' height='40' patternUnits='userSpaceOnUse'><rect width='40' height='40' fill='#fff'/><rect width='20' height='40' fill='#ef4444' opacity='.55'/><rect width='40' height='20' fill='#ef4444' opacity='.55'/></pattern>"
    )
    d += shine("grill", "#4b5563", "#1f2937", "#030712")
    body = f'<g filter="url(#sh)"><circle cx="256" cy="226" r="206" fill="url(#gng)" stroke="{E}" stroke-width="8"/></g>'
    body += f'<g filter="url(#sh)"><path d="M146 170 L366 170 Q366 270 256 270 Q146 270 146 170 Z" fill="url(#grill)" stroke="{E}" stroke-width="6"/>'
    body += f'<rect x="136" y="156" width="240" height="18" rx="6" fill="#6b7280" stroke="{E}" stroke-width="5"/>'
    body += f'<line x1="200" y1="262" x2="176" y2="330" stroke="{E}" stroke-width="8"/><line x1="312" y1="262" x2="336" y2="330" stroke="{E}" stroke-width="8"/></g>'
    for x in (210, 256, 302):
        body += f'<path d="M{x} 140 q-10 -20 0 -40 t0 -40" fill="none" stroke="#94a3b8" stroke-width="6" stroke-linecap="round" opacity=".8"/>'
    body += f'<g filter="url(#sh)">{ribbon(40, 472, 320, 92, "#facc15", "#ca8a04", E, sw=6, tail=36, drop=18)}</g>'
    body += fit(pop("COOKOUT", "Titan One", "#dc2626", E, sw=10, depth=5), 90, 332, 332, 68)
    return svg(body, d)


@kid("Porch Swing", "family", "drama", "comfort tv")
def porch_swing():
    E = "#2b1408"
    d = SH + lin("dusk", [(0, "#fdba74"), (0.6, "#fca5a5"), (1, "#c4b5fd")])
    body = '<defs><clipPath id="psc"><rect x="36" y="56" width="440" height="400" rx="30"/></clipPath></defs>'
    body += _panel_k(36, 56, 440, 400, "url(#dusk)", 30, E)
    body += '<g clip-path="url(#psc)">'
    body += '<rect x="36" y="56" width="440" height="34" fill="#7c4a21"/>'
    for x in (56, 456):
        body += f'<rect x="{x - 12}" y="56" width="24" height="400" fill="#fff7e0" stroke="{E}" stroke-width="4"/>'
    body += '<rect x="36" y="390" width="440" height="66" fill="#7c4a21"/>'
    for x in range(80, 440, 24):
        body += f'<rect x="{x}" y="342" width="10" height="48" fill="#fff7e0" stroke="{E}" stroke-width="2"/>'
    body += f'<rect x="36" y="334" width="440" height="12" fill="#fff7e0" stroke="{E}" stroke-width="3"/>'
    body += "</g>"
    for x in (150, 362):
        body += f'<line x1="{x}" y1="90" x2="{x}" y2="270" stroke="#57534e" stroke-width="4"/>'
    body += f'<g filter="url(#sh)"><rect x="130" y="270" width="252" height="22" rx="4" fill="#7c4a21" stroke="{E}" stroke-width="5"/><rect x="134" y="232" width="244" height="14" rx="4" fill="#7c4a21" stroke="{E}" stroke-width="4"/></g>'
    body += f'<g filter="url(#sh)">{fit(text("Porch Swing", "Lobster", 100, fill="#fff", stroke=E, sw=8), 70, 120, 372, 100)}</g>'
    return svg(body, d)


@kid("Family Album", "family", "drama", "nostalgia")
def family_album():
    E = "#1c1917"
    d = SH
    body = ""
    for x, y, rot, c1, c2 in (
        (60, 70, -12, "#93c5fd", "#fde68a"),
        (260, 60, 10, "#fca5a5", "#bbf7d0"),
        (160, 110, -2, "#c4b5fd", "#fed7aa"),
    ):
        body += f'<g filter="url(#sh)" transform="rotate({rot} {x + 96} {y + 110})"><rect x="{x}" y="{y}" width="192" height="220" fill="#fff" stroke="#d6d3d1" stroke-width="2"/>'
        body += f'<rect x="{x + 14}" y="{y + 14}" width="164" height="150" fill="{c1}"/><circle cx="{x + 130}" cy="{y + 60}" r="18" fill="{c2}"/>'
        body += f'<path d="M{x + 14} {y + 164} L{x + 70} {y + 100} L{x + 110} {y + 140} L{x + 140} {y + 116} L{x + 178} {y + 164} Z" fill="#fff" opacity=".6"/></g>'
    body += '<rect x="230" y="98" width="70" height="22" fill="#fef3c7" opacity=".85" transform="rotate(-6 265 109)"/>'
    body += f'<g filter="url(#sh)">{ribbon(40, 472, 330, 96, "#7c2d12", "#431407", E, sw=6, tail=36, drop=18)}</g>'
    body += fit(text("Family Album", "Lobster", 100, fill="#fef3c7"), 80, 340, 352, 74)
    return svg(body, d)


def logos() -> list[Logo]:
    return [Logo(lid, name, cat, fn, tags) for lid, name, cat, tags, fn in KIDS_LOGOS]
