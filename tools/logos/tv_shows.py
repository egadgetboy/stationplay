"""TV-show lingo channels (named after the way people talk about TV),
decade channels (a TV one and a movie one for each decade), and the old
local-station movie slots. Nothing here borrows a real channel's name,
symbol, colours or lettering."""

from __future__ import annotations

import itertools
import math
import random
import re

import layouts as L
import symbols as S
from kit import (
    Logo,
    banner,
    extrude,
    fit,
    glow,
    lin,
    pts,
    rad,
    ribbon,
    shadow,
    star,
    svg,
    text,
    tilt,
)
from symbols import P, centred

SH = shadow("sh", dy=6, blur=6, opacity=0.45)
SHOWS = "TV shows"
DECADES = "Decades"
OTA = "Over-the-air classics"
LOGOS: list[tuple[str, str, str, list[str], object]] = []  # (id, name, category, tags, draw)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", "and")).strip("-")


def net(name: str, category: str, *tags: str):
    def add(fn):
        LOGOS.append((slug(name), name, category, list(tags), fn))
        return fn

    return add


# ======================================================================= helpers


def _o(p: P, w: float = 6) -> str:
    return f'stroke="{p.k}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"'


def _panel(x, y, w, h, fill, rx=18, edge=None, sw=0):
    st = f' stroke="{edge}" stroke-width="{sw}"' if edge else ""
    return f'<g filter="url(#sh)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{st}/></g>'


def _bold(s, font, fill, edge, sw=12, weight=400, ls=0, style="normal", ext=None):
    """A word with an outline, and a solid block extrusion behind it when
    `ext` is (dx, dy, colour)."""
    w = text(s, font, 100, weight=weight, fill=fill, stroke=edge, sw=sw, ls=ls, style=style)
    if ext:
        dx, dy, col = ext
        return extrude(w, dx, dy, max(6, int(max(abs(dx), abs(dy)))), col) + w
    return w


_SEGS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abged",
    "3": "abgcd",
    "4": "fgbc",
    "5": "afgcd",
    "6": "afgedc",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
}


def seg7(s: str, x: float, y: float, h: float, on: str, off: str | None = None) -> str:
    """Seven-segment digits (and colons), top-left at x,y, `h` tall."""
    w, t = h * 0.52, h * 0.13
    gap = t * 0.22
    out = ""

    def hseg(x1, x2, yc):
        return pts(
            [
                (x1 + gap, yc),
                (x1 + gap + t / 2, yc - t / 2),
                (x2 - gap - t / 2, yc - t / 2),
                (x2 - gap, yc),
                (x2 - gap - t / 2, yc + t / 2),
                (x1 + gap + t / 2, yc + t / 2),
            ]
        )

    def vseg(xc, y1, y2):
        return pts(
            [
                (xc, y1 + gap),
                (xc + t / 2, y1 + gap + t / 2),
                (xc + t / 2, y2 - gap - t / 2),
                (xc, y2 - gap),
                (xc - t / 2, y2 - gap - t / 2),
                (xc - t / 2, y1 + gap + t / 2),
            ]
        )

    cx = x
    for ch in s:
        if ch == ":":
            out += f'<circle cx="{cx + t * 0.9:.1f}" cy="{y + h * 0.3:.1f}" r="{t * 0.6:.1f}" fill="{on}"/>'
            out += f'<circle cx="{cx + t * 0.9:.1f}" cy="{y + h * 0.7:.1f}" r="{t * 0.6:.1f}" fill="{on}"/>'
            cx += t * 2.4
            continue
        if ch == " ":
            cx += w + t * 1.6
            continue
        lit = _SEGS[ch]
        shapes = {
            "a": hseg(cx, cx + w, y),
            "g": hseg(cx, cx + w, y + h / 2),
            "d": hseg(cx, cx + w, y + h),
            "f": vseg(cx, y, y + h / 2),
            "b": vseg(cx + w, y, y + h / 2),
            "e": vseg(cx, y + h / 2, y + h),
            "c": vseg(cx + w, y + h / 2, y + h),
        }
        for k, poly in shapes.items():
            if k in lit:
                out += f'<polygon points="{poly}" fill="{on}"/>'
            elif off:
                out += f'<polygon points="{poly}" fill="{off}"/>'
        cx += w + t * 1.6
    return out


def bulbs(points, fill="#fff3b0", ring="#b36b00", r=7) -> str:
    return "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{ring}" stroke-width="1.5"/>'
        f'<circle cx="{x - r * 0.3:.1f}" cy="{y - r * 0.3:.1f}" r="{r * 0.35:.1f}" fill="#fff" opacity=".8"/>'
        for x, y in points
    )


def burst_lines(cx, cy, r, color, n=14, w=5, r0=0.3) -> str:
    """A firework: lines out from a centre with a dot at each end."""
    s = ""
    for k in range(n):
        a = math.radians(k * 360 / n + 7)
        x1, y1 = cx + r * r0 * math.cos(a), cy + r * r0 * math.sin(a)
        x2, y2 = cx + r * math.cos(a), cy + r * math.sin(a)
        s += f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{w}" stroke-linecap="round"/>'
        s += f'<circle cx="{cx + (r + w * 2.2) * math.cos(a):.1f}" cy="{cy + (r + w * 2.2) * math.sin(a):.1f}" r="{w * 0.8:.1f}" fill="{color}"/>'
    return s


# ======================================================================= drawings (200x200)


def calendar(p: P) -> str:
    """A wall-calendar page with one day circled."""
    s = f'<rect x="20" y="30" width="160" height="154" rx="14" fill="{p.l}" {_o(p)}/>'
    s += f'<path d="M20 76 L20 44 Q20 30 34 30 L166 30 Q180 30 180 44 L180 76 Z" fill="{p.a}" {_o(p)}/>'
    s += text("WEEK", "Oswald", 32, weight=700, fill=p.l, x=100, y=66, ls=8)
    for x in (58, 142):
        s += f'<rect x="{x - 7}" y="12" width="14" height="34" rx="7" fill="{p.b}" {_o(p, 4)}/>'
    for r in range(4):
        for c in range(7):
            x, y = 29 + c * 20.8, 88 + r * 23
            s += f'<rect x="{x:.1f}" y="{y}" width="16" height="16" rx="3" fill="{p.k}" opacity=".18"/>'
    cx, cy = 29 + 4 * 20.8 + 8, 88 + 2 * 23 + 8
    s += f'<ellipse cx="{cx:.1f}" cy="{cy}" rx="18" ry="14" fill="none" stroke="{p.c}" stroke-width="5" transform="rotate(-14 {cx:.1f} {cy})"/>'
    return s


def wingback(p: P) -> str:
    """A tufted wingback armchair (the reality-show interview chair)."""
    s = f'<path d="M44 150 L44 58 Q44 18 100 18 Q156 18 156 58 L156 150 Z" fill="{p.a}" {_o(p)}/>'
    for x, y in (
        (78, 52),
        (100, 44),
        (122, 52),
        (89, 80),
        (111, 80),
        (78, 106),
        (100, 100),
        (122, 106),
    ):
        s += f'<circle cx="{x}" cy="{y}" r="3.5" fill="{p.k}" opacity=".35"/>'
    s += f'<rect x="18" y="92" width="40" height="80" rx="18" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="142" y="92" width="40" height="80" rx="18" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="50" y="126" width="100" height="32" rx="10" fill="{p.b}" {_o(p)}/>'
    s += f'<rect x="26" y="152" width="148" height="26" rx="8" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="34" y="176" width="12" height="18" rx="3" fill="{p.k}"/><rect x="154" y="176" width="12" height="18" rx="3" fill="{p.k}"/>'
    s += f'<path d="M58 40 Q66 28 82 26" fill="none" stroke="{p.l}" stroke-width="5" stroke-linecap="round" opacity=".6"/>'
    return s


# ======================================================================= TV shows


@net("Case of the Week", SHOWS, "tv shows", "procedurals", "crime", "mystery")
def case_of_the_week():
    d = rad("dg", [(0, "#2d4474"), (1, "#121c34")], r=0.7)
    centre = centred(
        calendar(P(a="#c1121f", b="#f2c14e", c="#c1121f", k="#0b1224", l="#fbf7ea")), 222, 172, 236
    )
    centre += centred(
        S.magnifier(P(a="#f2c14e", b="#8a5a1c", c="#bde0fe", l="#fff", k="#0b1224")), 338, 206, 150
    )
    return L.roundel(
        centre,
        "CASE OF THE WEEK",
        font="Oswald",
        weight=700,
        ink="#fff",
        disc="url(#dg)",
        rim="#f2c14e",
        edge="#0b1224",
        bar="#c1121f",
        defs=d,
        ls=4,
    )


@net("Confessional", SHOWS, "tv shows", "reality")
def confessional():
    d = (
        SH
        + lin("bg", [(0, "#6a2ce0"), (1, "#e8207a")], x2=1, y2=1)
        + rad("spot", [(0, "#ffffff"), (0.45, "#ffffff55"), (1, "#ffffff00")])
        + "<clipPath id='pc'><rect x='28' y='36' width='456' height='440' rx='30'/></clipPath>"
    )
    body = _panel(28, 36, 456, 440, "url(#bg)", rx=30)
    rng = random.Random(11)
    body += '<g clip-path="url(#pc)">'
    for _ in range(14):
        body += f'<circle cx="{rng.uniform(40, 470):.0f}" cy="{rng.uniform(50, 300):.0f}" r="{rng.uniform(10, 34):.0f}" fill="#fff" opacity="{rng.uniform(0.06, 0.16):.2f}"/>'
    body += '<ellipse cx="256" cy="210" rx="190" ry="150" fill="url(#spot)" opacity=".55"/>'
    body += '<rect x="28" y="286" width="456" height="200" fill="#22062e" opacity=".35"/></g>'
    body += f'<g filter="url(#sh)">{centred(wingback(P(a="#16b5a8", b="#ffd166", l="#fff", k="#22062e")), 256, 190, 230)}</g>'
    body += '<circle cx="66" cy="76" r="11" fill="#ff2d3d" stroke="#fff" stroke-width="3"/>'
    body += text("REC", "Oswald", 26, weight=700, fill="#fff", x=86, y=86, anchor="start", ls=3)
    body += '<g filter="url(#sh)">'
    body += '<rect x="40" y="296" width="150" height="34" fill="#ffd166" stroke="#22062e" stroke-width="5"/>'
    body += '<rect x="24" y="326" width="464" height="86" rx="6" fill="#fff" stroke="#22062e" stroke-width="6"/>'
    body += '<rect x="24" y="326" width="22" height="86" fill="#e8207a" stroke="#22062e" stroke-width="6"/></g>'
    body += fit(text("REALITY", "Oswald", 40, weight=700, fill="#22062e", ls=8), 54, 302, 122, 22)
    body += fit(text("CONFESSIONAL", "Archivo Black", 100, fill="#22062e"), 62, 342, 406, 54)
    body += fit(
        text("IN THEIR OWN WORDS", "Oswald", 40, weight=600, fill="#fff", ls=8), 136, 428, 240, 26
    )
    return svg(body, d)


@net("Bonus Round", SHOWS, "tv shows", "game shows")
def bonus_round():
    d = (
        SH
        + rad("hx", [(0, "#ffb347"), (0.55, "#ff5e62"), (1, "#b0106a")], r=0.65)
        + lin("gold", [(0, "#fff6b0"), (0.5, "#ffd23f"), (1, "#f08a00")])
    )

    def hexa(r):
        return pts(
            (256 + r * math.cos(math.radians(a)), 256 + r * 0.9 * math.sin(math.radians(a)))
            for a in range(0, 360, 60)
        )

    d += f"<clipPath id='hc'><polygon points='{hexa(226)}'/></clipPath>"
    body = f'<g filter="url(#sh)"><polygon points="{hexa(244)}" fill="#2b0a3d" stroke="#2b0a3d" stroke-width="10" stroke-linejoin="round"/>'
    body += f'<polygon points="{hexa(226)}" fill="url(#hx)"/></g>'
    body += '<g clip-path="url(#hc)">'
    for k in range(18):
        a = math.radians(k * 20)
        b = math.radians(k * 20 + 9)
        body += f'<polygon points="256,256 {256 + 400 * math.cos(a):.0f},{256 + 400 * math.sin(a):.0f} {256 + 400 * math.cos(b):.0f},{256 + 400 * math.sin(b):.0f}" fill="#fff" opacity=".10"/>'
    body += "</g>"
    body += f'<polygon points="{hexa(206)}" fill="none" stroke="#ffd23f" stroke-width="5" stroke-linejoin="round"/>'
    corners = [
        (256 + 216 * math.cos(math.radians(a)), 256 + 216 * 0.9 * math.sin(math.radians(a)))
        for a in range(0, 420, 60)
    ]
    dots = []
    for (x1, y1), (x2, y2) in itertools.pairwise(corners):
        for t in range(6):
            dots.append((x1 + (x2 - x1) * t / 6, y1 + (y2 - y1) * t / 6))
    body += bulbs(dots, r=7)
    w = _bold("BONUS", "Bungee", "url(#gold)", "#2b0a3d", sw=12, ext=(0, 10, "#2b0a3d"))
    body += f'<g filter="url(#sh)">{fit(w, 92, 132, 328, 122)}</g>'
    body += '<g filter="url(#sh)"><rect x="126" y="276" width="260" height="84" rx="42" fill="#3d1273" stroke="#2b0a3d" stroke-width="7"/></g>'
    body += fit(text("ROUND", "Bungee Inline", 100, fill="#fff", ls=6), 156, 290, 200, 56)
    body += f'<g filter="url(#sh)"><polygon points="{star(392, 112, 44, 30, 12)}" fill="#18d6c8" stroke="#2b0a3d" stroke-width="5" stroke-linejoin="round"/></g>'
    body += fit(text("x2", "Bungee", 60, fill="#2b0a3d"), 370, 96, 44, 32)
    return svg(body, d)


@net("Grand Prize", SHOWS, "tv shows", "game shows")
def grand_prize():
    d = lin("g", [(0, "#fff3b0"), (0.5, "#f4c542"), (1, "#b7791f")]) + lin(
        "gd", [(0, "#f4c542"), (1, "#9c6a12")]
    )
    ed = "#0b0f1c"
    back = f'<path d="M206 300 L150 488 L186 468 L214 496 L262 316 Z" fill="#c1121f" stroke="{ed}" stroke-width="5" stroke-linejoin="round"/>'
    back += f'<path d="M306 300 L362 488 L326 468 L298 496 L250 316 Z" fill="#1d3557" stroke="{ed}" stroke-width="5" stroke-linejoin="round"/>'
    back += f'<polygon points="{star(256, 226, 214, 190, 36)}" fill="#c1121f" stroke="{ed}" stroke-width="6" stroke-linejoin="round"/>'
    back += f'<circle cx="256" cy="226" r="172" fill="url(#g)" stroke="{ed}" stroke-width="6"/>'
    back += '<circle cx="256" cy="226" r="150" fill="url(#gd)" stroke="#fff3b0" stroke-width="3"/>'
    back += f'<polygon points="{star(256, 138, 50, 22)}" fill="#fff3b0" stroke="{ed}" stroke-width="5" stroke-linejoin="round"/>'
    for x in (186, 326):
        back += f'<polygon points="{star(x, 162, 22, 10)}" fill="#fff3b0" stroke="{ed}" stroke-width="4" stroke-linejoin="round"/>'
    for x in (206, 256, 306):
        back += f'<polygon points="{star(x, 346, 16, 7)}" fill="#fff3b0"/>'
    rng = random.Random(4)
    for _ in range(16):
        x, y = rng.uniform(30, 480), rng.uniform(20, 130)
        if abs(x - 256) < 200 and y > 40:
            continue
        back += f'<rect x="{x:.0f}" y="{y:.0f}" width="14" height="7" rx="2" fill="{rng.choice(["#ffd23f", "#ff5d8f", "#4cc9f0", "#fff"])}" transform="rotate({rng.uniform(-60, 60):.0f} {x:.0f} {y:.0f})"/>'
    return L.ribbon_badge(
        back,
        "GRAND PRIZE",
        font="Ultra",
        ink="#ffd23f",
        band="#1d3557",
        band_dark="#0f1f38",
        edge=ed,
        defs=d,
        y=240,
        ls=2,
    )


@net("Box Set", SHOWS, "tv shows", "binge", "complete series")
def box_set():
    d = (
        SH
        + lin("blk", [(0, "#30333f"), (1, "#0b0c11")])
        + lin("gold", [(0, "#fff0c4"), (0.45, "#e2b85a"), (1, "#9c7424")])
        + lin("shine", [(0, "#ffffff30"), (1, "#ffffff00")], x2=1, y2=0.4)
    )
    ed = "#07080b"
    body = '<g filter="url(#sh)">'
    for i, (x, top, c) in enumerate(
        ((116, 74, "#1f8a8a"), (188, 54, "#c8553d"), (260, 84, "#e9b949"), (332, 64, "#6a4c93"))
    ):
        body += f'<rect x="{x}" y="{top}" width="64" height="{200 - top}" rx="6" fill="{c}" stroke="{ed}" stroke-width="6"/>'
        body += (
            f'<rect x="{x + 10}" y="{top + 44}" width="44" height="4" fill="#fff" opacity=".7"/>'
        )
        body += text(f"S{i + 1}", "Oswald", 30, weight=700, fill="#fff", x=x + 32, y=top + 34)
    body += f'<rect x="90" y="150" width="332" height="306" rx="16" fill="url(#blk)" stroke="{ed}" stroke-width="8"/>'
    body += '<rect x="104" y="150" width="304" height="18" fill="#000"/>'
    body += '<path d="M94 170 L418 170 L418 250 Q256 216 94 290 Z" fill="url(#shine)"/>'
    body += "</g>"
    body += '<rect x="112" y="190" width="288" height="244" rx="8" fill="none" stroke="url(#gold)" stroke-width="3"/>'
    body += fit(
        text("THE COMPLETE SERIES", "Cinzel", 40, weight=700, fill="#e2b85a", ls=6),
        140,
        204,
        232,
        22,
    )
    body += fit(text("BOX", "Cinzel", 100, weight=900, fill="url(#gold)", ls=12), 142, 240, 228, 86)
    body += fit(text("SET", "Cinzel", 100, weight=900, fill="url(#gold)", ls=12), 142, 336, 228, 86)
    return svg(body, d)


@net("Season Pass", SHOWS, "tv shows", "binge", "complete seasons")
def season_pass():
    d = SH + lin("lan", [(0, "#ff8a3d"), (1, "#e0501a")])
    ed = "#10243e"
    body = '<g filter="url(#sh)">'
    body += f'<polygon points="150,-10 184,-10 262,112 236,120" fill="url(#lan)" stroke="{ed}" stroke-width="4"/>'
    body += f'<polygon points="362,-10 328,-10 250,112 276,120" fill="url(#lan)" stroke="{ed}" stroke-width="4"/>'
    body += f'<rect x="232" y="104" width="48" height="44" rx="8" fill="#b8c1cc" stroke="{ed}" stroke-width="5"/>'
    body += "</g>"
    card = f'<rect x="96" y="132" width="320" height="344" rx="26" fill="#fff" stroke="{ed}" stroke-width="7"/>'
    card += '<path d="M99 252 L99 158 Q99 135 122 135 L390 135 Q413 135 413 158 L413 252 Z" fill="#0f9d8a"/>'
    card += f'<line x1="99" y1="252" x2="413" y2="252" stroke="{ed}" stroke-width="5"/>'
    card += f'<rect x="222" y="150" width="68" height="14" rx="7" fill="{ed}"/>'
    card += fit(text("SEASON", "Montserrat", 100, weight=900, fill="#fff", ls=4), 124, 178, 264, 58)
    card += fit(text("PASS", "Anton", 100, fill=ed, ls=10), 124, 266, 264, 118)
    card += fit(
        text("ALL EPISODES · ALL ACCESS", "Oswald", 40, weight=700, fill="#e0501a", ls=4),
        128,
        396,
        256,
        22,
    )
    rng = random.Random(3)
    x = 150
    while x < 362:
        w = rng.choice((3, 3, 5, 7))
        card += f'<rect x="{x}" y="430" width="{w}" height="30" fill="{ed}"/>'
        x += w + rng.choice((3, 4, 6))
    body += f'<g transform="rotate(-5 256 300)"><g filter="url(#sh)">{card}</g></g>'
    return svg(body, d)


@net("Next Episode", SHOWS, "tv shows", "binge")
def next_episode():
    ring = '<circle cx="0" cy="0" r="92" fill="none" stroke="#ffffff" stroke-opacity=".25" stroke-width="16"/>'
    a = math.radians(-90 + 290)
    ring += f'<path d="M0 -92 A92 92 0 1 1 {92 * math.cos(a):.1f} {92 * math.sin(a):.1f}" fill="none" stroke="#fff" stroke-width="16" stroke-linecap="round"/>'
    ring += '<polygon points="-34,-42 26,0 -34,42" fill="#fff" stroke="#fff" stroke-width="10" stroke-linejoin="round"/>'
    ring += '<rect x="30" y="-44" width="16" height="88" rx="5" fill="#fff"/>'
    return L.tile_word(
        ring,
        "NEXT EPISODE",
        font="Outfit",
        weight=900,
        ink="#fff",
        edge="#0a1330",
        tile="#3d8bff",
        tile2="#1737b8",
        sub="AUTOPLAY ON",
        sub_ink="#7fd8ff",
        ring="#9fd0ff",
        ls=2,
        mark_box=(172, 62, 168, 164),
    )


@net("Are You Still Watching?", SHOWS, "tv shows", "binge")
def are_you_still_watching():
    d = (
        SH
        + lin("scr", [(0, "#232b52"), (1, "#080b1a")])
        + lin("btn", [(0, "#ff5a92"), (1, "#d81b60")])
        + "<clipPath id='sc'><rect x='38' y='62' width='436' height='356' rx='26'/></clipPath>"
    )
    ed = "#080b1a"
    body = '<g filter="url(#sh)">'
    body += f'<rect x="206" y="430" width="100" height="40" rx="6" fill="#2b2e3a" stroke="{ed}" stroke-width="5"/>'
    body += f'<rect x="150" y="462" width="212" height="18" rx="9" fill="#2b2e3a" stroke="{ed}" stroke-width="5"/>'
    body += f'<rect x="18" y="42" width="476" height="396" rx="36" fill="#2b2e3a" stroke="{ed}" stroke-width="7"/>'
    body += '<rect x="38" y="62" width="436" height="356" rx="26" fill="url(#scr)"/></g>'
    body += '<g clip-path="url(#sc)">'
    for y in range(66, 420, 8):
        body += f'<rect x="38" y="{y}" width="436" height="2" fill="#fff" opacity=".04"/>'
    body += "</g>"
    body += f'<g filter="url(#sh)"><rect x="74" y="104" width="364" height="276" rx="24" fill="#f5f6fb" stroke="{ed}" stroke-width="5"/></g>'
    body += fit(text("ARE YOU STILL", "Sora", 100, weight=800, fill="#232b52"), 104, 130, 304, 52)
    body += fit(text("WATCHING?", "Sora", 100, weight=800, fill="#d81b60"), 98, 196, 316, 78)
    body += '<rect x="102" y="298" width="144" height="54" rx="27" fill="url(#btn)"/>'
    body += '<rect x="266" y="298" width="144" height="54" rx="27" fill="none" stroke="#232b52" stroke-width="5"/>'
    body += fit(text("YES!", "Sora", 60, weight=800, fill="#fff"), 136, 312, 76, 26)
    body += fit(text("zzz…", "Sora", 60, weight=800, fill="#232b52"), 300, 308, 76, 30)
    for x, y, s in ((410, 98, 40), (446, 64, 30)):
        body += f'<g filter="url(#sh)">{text("Z", "Sora", s, weight=800, fill="#9fd0ff", stroke=ed, sw=6, x=x, y=y)}</g>'
    return svg(body, d)


@net("The Narrator", SHOWS, "tv shows", "documentary", "nature")
def the_narrator():
    d = (
        SH
        + lin("pg", [(0, "#1f4d3c"), (1, "#0b211a")])
        + lin("brass", [(0, "#f6e1a6"), (0.5, "#d4a24c"), (1, "#8a5a1c")])
    )
    body = _panel(36, 36, 440, 440, "url(#pg)", rx=44, edge="#06140f", sw=6)
    body += '<rect x="54" y="54" width="404" height="404" rx="30" fill="none" stroke="url(#brass)" stroke-width="3"/>'
    mic = centred(S.mic_vintage(P(a="url(#brass)", l="#f6e7c1", k="#0b211a")), 256, 152, 176)
    for side in (-1, 1):
        for i, r in enumerate((70, 100)):
            x0 = 256 + side * r
            body += f'<path d="M{x0} {104 - i * 12} Q{x0 + side * (22 + i * 8)} 140 {x0} {176 + i * 12}" fill="none" stroke="#d4a24c" stroke-width="{7 - i * 2}" stroke-linecap="round" opacity="{1 - i * 0.35}"/>'
    body += f'<g filter="url(#sh)">{mic}</g>'
    body += f'<g filter="url(#sh)">{fit(text("The Narrator", "DM Serif Display", 100, fill="#f6e7c1", stroke="#0b211a", sw=6), 74, 264, 364, 100)}</g>'
    body += '<line x1="120" y1="384" x2="220" y2="384" stroke="#d4a24c" stroke-width="3"/><line x1="292" y1="384" x2="392" y2="384" stroke="#d4a24c" stroke-width="3"/>'
    body += f'<polygon points="{star(256, 384, 10, 4, 4)}" fill="#d4a24c"/>'
    body += fit(
        text("DOCUMENTARIES", "Oswald", 40, weight=600, fill="url(#brass)", ls=10),
        136,
        404,
        240,
        28,
    )
    return svg(body, d)


@net("True Story", SHOWS, "tv shows", "documentary", "true stories")
def true_story():
    d = (
        SH
        + lin("ph", [(0, "#ffcf87"), (0.5, "#f4845f"), (1, "#7a2e4a")])
        + "<clipPath id='pc'><rect x='108' y='58' width='296' height='294'/></clipPath>"
    )
    g = '<g filter="url(#sh)"><rect x="84" y="34" width="344" height="444" rx="6" fill="#fbfaf4" stroke="#cfc8b8" stroke-width="2"/></g>'
    g += '<rect x="108" y="58" width="296" height="294" fill="url(#ph)"/>'
    g += '<g clip-path="url(#pc)">'
    g += '<circle cx="300" cy="226" r="54" fill="#ffe8a3" opacity=".95"/>'
    g += '<path d="M100 300 Q200 236 300 276 Q360 300 420 270 L420 360 L100 360 Z" fill="#9c3d54"/>'
    g += '<path d="M100 330 Q220 280 420 316 L420 360 L100 360 Z" fill="#3b1f2b"/>'
    g += '<path d="M190 300 L190 222" stroke="#3b1f2b" stroke-width="8" stroke-linecap="round"/>'
    g += '<circle cx="190" cy="206" r="30" fill="#3b1f2b"/><circle cx="168" cy="224" r="20" fill="#3b1f2b"/><circle cx="212" cy="224" r="20" fill="#3b1f2b"/>'
    for x, y in ((150, 120), (178, 104), (330, 132)):
        g += f'<path d="M{x - 10} {y - 4} Q{x - 5} {y - 8} {x} {y} Q{x + 5} {y - 8} {x + 10} {y - 4}" fill="none" stroke="#3b1f2b" stroke-width="3" stroke-linecap="round"/>'
    g += "</g>"
    g += '<rect x="108" y="58" width="296" height="294" fill="none" stroke="#000" stroke-opacity=".25" stroke-width="2"/>'
    g += fit(
        tilt(text("True Story", "Permanent Marker", 100, fill="#1c1c24"), -2), 114, 366, 284, 92
    )
    g += '<rect x="200" y="16" width="112" height="40" fill="#f3e3a8" opacity=".85" transform="rotate(4 256 36)"/>'
    return svg(f'<g transform="rotate(-5 256 256)">{g}</g>', d)


@net("One More Episode", SHOWS, "tv shows", "binge")
def one_more_episode():
    d = SH + lin("n", [(0, "#2d1260"), (1, "#0d0624")]) + glow("led", "#ff2d3d", blur=6)
    ed = "#0d0624"
    body = _panel(30, 30, 452, 452, "url(#n)", rx=44, edge="#05020f", sw=6)
    rng = random.Random(8)
    for _ in range(24):
        body += f'<circle cx="{rng.uniform(50, 462):.0f}" cy="{rng.uniform(50, 460):.0f}" r="{rng.uniform(1, 2.4):.1f}" fill="#fff" opacity="{rng.uniform(0.2, 0.6):.2f}"/>'
    body += '<g filter="url(#sh)"><rect x="118" y="60" width="276" height="130" rx="26" fill="#1b1b22" stroke="#000" stroke-width="6"/></g>'
    body += '<rect x="136" y="78" width="240" height="94" rx="12" fill="#2a0508"/>'
    body += f'<g filter="url(#led)">{seg7("3:07", 158, 92, 66, "#ff3040")}</g>'
    body += '<rect x="340" y="92" width="22" height="10" rx="2" fill="#ff3040"/>'
    body += text("AM", "Oswald", 18, weight=700, fill="#ff3040", x=351, y=124)
    top = _bold("ONE MORE", "Lilita One", "#ffd23f", ed, sw=12, ext=(0, 9, "#05020f"))
    body += f'<g filter="url(#sh)">{fit(top, 48, 212, 416, 112)}</g>'
    bot = _bold("EPISODE", "Lilita One", "#fff", ed, sw=12, ext=(0, 7, "#05020f"))
    body += f'<g filter="url(#sh)">{fit(bot, 96, 334, 320, 82)}</g>'
    body += fit(
        text("…OK, JUST ONE MORE", "Oswald", 40, weight=600, fill="#c9b8ff", ls=6),
        150,
        428,
        212,
        24,
    )
    return svg(body, d)


@net("Pilot Season", SHOWS, "tv shows", "new series", "premieres")
def pilot_season():
    d = (
        SH
        + lin("wing", [(0, "#fff3c4"), (0.5, "#e7b64a"), (1, "#9c6a12")])
        + lin("nv", [(0, "#24406e"), (1, "#122544")])
    )
    ed = "#0a1428"
    wing = ""
    for i in range(5):
        y = 108 + i * 20
        tip = 34 + i * 30
        wing += (
            f'<path d="M214 {y} L{tip + 20} {y - 14 + i * 3} Q{tip} {y - 8 + i * 3} {tip + 8} {y + 10} '
            f'Q{tip + 16} {y + 22} {tip + 34} {y + 22} L214 {y + 30} Z" fill="url(#wing)" stroke="{ed}" stroke-width="4.5" stroke-linejoin="round"/>'
        )
    body = f'<g filter="url(#sh)">{wing}<g transform="translate(512 0) scale(-1 1)">{wing}</g>'
    body += f'<path d="M206 84 L306 84 L306 170 Q306 214 256 232 Q206 214 206 170 Z" fill="url(#nv)" stroke="{ed}" stroke-width="6"/>'
    body += '<path d="M218 96 L294 96 L294 168 Q294 202 256 218 Q218 202 218 168 Z" fill="none" stroke="#e7b64a" stroke-width="3"/>'
    body += centred(S.tv_set(P(a="#e7b64a", c="#7fd8ff", l="#fff3c4", k=ed)), 256, 150, 70)
    body += f'<polygon points="{star(256, 62, 22, 9)}" fill="url(#wing)" stroke="{ed}" stroke-width="4" stroke-linejoin="round"/>'
    body += "</g>"
    body += f'<g filter="url(#sh)">{ribbon(78, 434, 272, 88, "url(#nv)", ed, tail=48, tail_fill="#0e1d38", sw=6)}</g>'
    body += fit(
        text("PILOT SEASON", "Big Shoulders Display", 100, weight=900, fill="url(#wing)", ls=4),
        96,
        284,
        320,
        64,
    )
    body += fit(
        text(
            "NEW SHOWS TAKING OFF", "Oswald", 40, weight=700, fill="#e7b64a", stroke=ed, sw=7, ls=6
        ),
        132,
        406,
        248,
        30,
    )
    return svg(body, d)


@net("Spin-Off", SHOWS, "tv shows", "spin-offs")
def spin_off():
    d = (
        SH
        + rad("dk", [(0, "#44208a"), (1, "#190735")], r=0.7)
        + lin("lime", [(0, "#efff8a"), (1, "#7ed321")])
    )
    ed = "#0c0320"
    body = f'<g filter="url(#sh)"><circle cx="256" cy="256" r="228" fill="url(#dk)" stroke="{ed}" stroke-width="8"/></g>'
    body += '<circle cx="256" cy="256" r="206" fill="none" stroke="#ff3da5" stroke-width="3" stroke-dasharray="4 10" opacity=".7"/>'
    # the orbit the little show flies off: behind the word, then in front
    body += '<path d="M92 300 Q60 200 170 150 Q280 104 380 130" fill="none" stroke="#ff3da5" stroke-width="16" stroke-linecap="round"/>'
    w = _bold("SPIN-OFF", "Racing Sans One", "url(#lime)", ed, sw=12, ext=(6, 8, ed))
    body += f'<g filter="url(#sh)">{fit(tilt(w, -8), 58, 184, 396, 138)}</g>'
    body += '<path d="M92 300 Q130 360 230 360 Q330 360 400 318" fill="none" stroke="#ff3da5" stroke-width="16" stroke-linecap="round"/>'
    for i in range(3):
        body += f'<line x1="{330 - i * 8}" y1="{116 + i * 16}" x2="{370 - i * 8}" y2="{112 + i * 16}" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity="{0.8 - i * 0.2:.1f}"/>'
    tv = centred(S.tv_set(P(a="#ff3da5", c="#4cc9f0", l="#fff", k=ed)), 0, 0, 92)
    body += f'<g filter="url(#sh)" transform="translate(406 118) rotate(18)">{tv}</g>'
    body += fit(
        text("NEW SHOWS · OLD FRIENDS", "Oswald", 40, weight=700, fill="#fff", ls=6),
        136,
        382,
        240,
        28,
    )
    return svg(body, d)


@net("Season Finale", SHOWS, "tv shows", "cliffhangers", "drama")
def season_finale():
    d = (
        SH
        + lin("bg", [(0, "#1a1036"), (1, "#51102f")])
        + lin("gold", [(0, "#fff2c2"), (0.5, "#f4c54a"), (1, "#b7791f")])
        + "<clipPath id='pc'><rect x='28' y='40' width='456' height='432' rx='32'/></clipPath>"
    )
    ed = "#12061c"
    body = _panel(28, 40, 456, 432, "url(#bg)", rx=32, edge="#0b0514", sw=6)
    body += '<g clip-path="url(#pc)">'
    body += burst_lines(128, 116, 64, "#ff5d8f", n=16, w=5)
    body += burst_lines(388, 104, 74, "#f4c54a", n=18, w=5)
    body += burst_lines(262, 70, 40, "#7ae1ff", n=12, w=4)
    body += burst_lines(70, 420, 40, "#f4c54a", n=12, w=4)
    body += burst_lines(446, 430, 44, "#ff5d8f", n=12, w=4)
    body += "</g>"
    body += fit(
        text("SEASON", "Montserrat", 100, weight=800, fill="#fff", ls=24), 124, 184, 264, 42
    )
    w = _bold("FINALE", "Abril Fatface", "url(#gold)", ed, sw=8, ext=(0, 8, ed))
    body += f'<g filter="url(#sh)">{fit(w, 52, 238, 408, 124)}</g>'
    body += fit(
        text(
            "TO BE CONTINUED…", "Montserrat", 40, weight=700, style="italic", fill="#ff9ec0", ls=6
        ),
        126,
        382,
        260,
        28,
    )
    return svg(body, d)


@net("Cold Open", SHOWS, "tv shows", "comedy", "sketch")
def cold_open():
    d = (
        SH
        + glow("ice", "#2ec4ff", blur=9, strength=2)
        + glow("red", "#ff2d55", blur=9, strength=2)
        + glow("fr", "#9be7ff", blur=6, strength=2)
        + lin("frost", [(0, "#ffffff"), (1, "#b9e6fb")])
    )
    body = '<g filter="url(#sh)"><rect x="30" y="104" width="452" height="300" rx="34" fill="#0a1624" stroke="#02070d" stroke-width="6"/></g>'
    body += '<g filter="url(#fr)"><rect x="52" y="126" width="408" height="256" rx="22" fill="none" stroke="#9be7ff" stroke-width="6"/></g>'
    body += '<rect x="52" y="126" width="408" height="256" rx="22" fill="none" stroke="#fff" stroke-width="2" opacity=".8"/>'
    cold = text("COLD", "Tilt Neon", 100, fill="none", stroke="#5fdcff", sw=7, ls=6)
    core = text("COLD", "Tilt Neon", 100, fill="none", stroke="#f2fdff", sw=2.5, ls=6)
    body += fit(f'<g filter="url(#ice)">{cold}</g>{core}', 96, 146, 320, 106)
    op = text("OPEN", "Tilt Neon", 100, fill="none", stroke="#ff3b6b", sw=7, ls=6)
    opc = text("OPEN", "Tilt Neon", 100, fill="none", stroke="#ffe3ea", sw=2.5, ls=6)
    body += fit(f'<g filter="url(#red)">{op}</g>{opc}', 126, 266, 260, 94)
    body += fit(
        text("BEFORE THE TITLES", "Oswald", 40, weight=600, fill="#9be7ff", ls=10),
        156,
        418,
        200,
        22,
    )
    return svg(body, d)


@net("Ensemble", SHOWS, "tv shows", "drama", "ensemble casts")
def ensemble():
    d = SH
    cols = ["#ef4444", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6"]
    body = '<g filter="url(#sh)">'
    for i, c in enumerate(cols):
        cx = 96 + i * 80
        body += f'<circle cx="{cx}" cy="196" r="62" fill="{c}" opacity=".92" stroke="#0f172a" stroke-width="6"/>'
    body += "</g>"
    for i in range(5):
        cx = 96 + i * 80
        body += f'<circle cx="{cx - 18}" cy="176" r="12" fill="#fff" opacity=".35"/>'
    body += f'<g filter="url(#sh)">{fit(_bold("ENSEMBLE", "Montserrat", "#fff", "#0f172a", 14, weight=900, ls=4), 36, 290, 440, 96)}</g>'
    body += fit(
        text(
            "THE WHOLE CAST",
            "Oswald",
            40,
            weight=600,
            fill="#e2e8f0",
            stroke="#0f172a",
            sw=6,
            ls=12,
        ),
        146,
        404,
        220,
        26,
    )
    return svg(body, d)


@net("Showrunner", SHOWS, "tv shows", "drama", "prestige")
def showrunner():
    d = SH + lin("srg", [(0, "#fff3c4"), (0.5, "#d4a63a"), (1, "#8a6414")])
    body = _panel(56, 56, 400, 400, "#0b0b0d", rx=10, edge="#d4a63a", sw=4)
    body += '<rect x="76" y="76" width="360" height="360" rx="4" fill="none" stroke="#d4a63a" stroke-width="1.5" opacity=".7"/>'
    body += (
        '<g filter="url(#sh)"><rect x="176" y="110" width="160" height="160" fill="url(#srg)"/></g>'
    )
    body += '<rect x="186" y="120" width="140" height="140" fill="none" stroke="#0b0b0d" stroke-width="3"/>'
    body += fit(text("SR", "Playfair Display", 100, weight=900, fill="#0b0b0d"), 200, 146, 112, 88)
    body += fit(
        text("SHOWRUNNER", "Playfair Display", 100, weight=700, fill="url(#srg)", ls=10),
        96,
        300,
        320,
        50,
    )
    body += '<line x1="176" y1="372" x2="336" y2="372" stroke="#d4a63a" stroke-width="2"/>'
    body += fit(
        text("ORIGINAL SERIES", "Montserrat", 40, weight=600, fill="#e7e5e4", ls=12),
        156,
        388,
        200,
        18,
    )
    return svg(body, d)


@net("Writers' Room", SHOWS, "tv shows", "comedy", "drama")
def writers_room():
    d = SH
    body = '<g filter="url(#sh)"><path d="M88 40 L376 40 L424 88 L424 472 L88 472 Z" fill="#fbfaf5" stroke="#1f2937" stroke-width="5"/></g>'
    body += '<path d="M376 40 L376 88 L424 88 Z" fill="#e5e2d6" stroke="#1f2937" stroke-width="5" stroke-linejoin="round"/>'
    for y in (60, 256, 452):
        body += f'<circle cx="108" cy="{y}" r="7" fill="#1f2937" opacity=".75"/>'
    body += fit(
        text("FADE IN:", "Special Elite", 40, fill="#1f2937"), 136, 100, 120, 24, anchor="left"
    )
    body += fit(_bold("WRITERS'", "Special Elite", "#111827", "#111827", 2), 136, 158, 260, 76)
    body += fit(_bold("ROOM", "Special Elite", "#b91c1c", "#b91c1c", 2), 176, 244, 180, 80)
    body += '<rect x="132" y="346" width="248" height="4" fill="#111827"/>'
    for i, (w, x) in enumerate(((200, 156), (150, 180), (220, 146))):
        body += f'<rect x="{x}" y="{372 + i * 22}" width="{w}" height="8" rx="4" fill="#9ca3af"/>'
    return svg(body, d)


@net("Tape Delay", SHOWS, "tv shows", "reruns", "broadcast")
def tape_delay():
    d = SH + lin("tdp", [(0, "#1f2937"), (1, "#030712")])
    body = _panel(32, 108, 448, 296, "url(#tdp)", rx=24, edge="#000", sw=4)
    for cx in (124, 388):
        body += (
            f'<circle cx="{cx}" cy="190" r="54" fill="#111827" stroke="#9ca3af" stroke-width="6"/>'
        )
        body += f'<circle cx="{cx}" cy="190" r="16" fill="#9ca3af"/>'
        for k in range(3):
            a = math.radians(k * 120 - 90)
            body += f'<circle cx="{cx + 34 * math.cos(a):.1f}" cy="{190 + 34 * math.sin(a):.1f}" r="10" fill="#374151"/>'
    body += '<path d="M124 244 L180 268 L332 268 L388 244" fill="none" stroke="#78350f" stroke-width="7"/>'
    body += '<rect x="196" y="150" width="120" height="80" rx="8" fill="#0b0b0b" stroke="#374151" stroke-width="3"/>'
    body += '<rect x="212" y="186" width="18" height="8" rx="2" fill="#ef4444"/>'
    body += seg7("7", 240, 160, 60, "#ef4444", "#1f0707")
    body += fit(text("SEC", "Oswald", 40, weight=700, fill="#ef4444"), 278, 206, 30, 16)
    body += fit(_bold("TAPE DELAY", "Archivo Black", "#f9fafb", "#000", 8, ls=3), 64, 290, 384, 70)
    body += fit(
        text("ON THE AIR · A LITTLE LATER", "Oswald", 40, weight=600, fill="#f87171", ls=6),
        116,
        370,
        280,
        20,
    )
    return svg(body, d)


@net("Guest Star", SHOWS, "tv shows", "special guests")
def guest_star():
    d = SH + rad("gsg", [(0, "#fff7c2"), (0.6, "#facc15"), (1, "#ca8a04")], cx=0.45, cy=0.4)
    back = f'<polygon points="{star(256, 256, 226, 100)}" fill="url(#gsg)" stroke="#422006" stroke-width="9" stroke-linejoin="round"/>'
    back += f'<polygon points="{star(256, 256, 190, 84)}" fill="none" stroke="#fff7c2" stroke-width="3" opacity=".8"/>'
    return L.ribbon_badge(
        back,
        "GUEST STAR",
        font="Archivo Black",
        ink="#fff",
        band="#7c3aed",
        band_dark="#4c1d95",
        edge="#1e1b4b",
        defs=d.replace(SH, ""),
        y=226,
        ls=2,
    )


@net("Fan Favorite", SHOWS, "tv shows", "favorites", "most popular")
def fan_favorite():
    d = SH + lin("ffh", [(0, "#fb7185"), (1, "#be123c")])
    heart = "M256 452 C120 360 40 292 40 196 C40 120 100 66 168 66 C210 66 240 90 256 120 C272 90 302 66 344 66 C412 66 472 120 472 196 C472 292 392 360 256 452 Z"
    body = f'<g filter="url(#sh)"><path d="{heart}" fill="url(#ffh)" stroke="#4c0519" stroke-width="10" stroke-linejoin="round"/></g>'
    body += '<path d="M92 170 Q104 108 164 98" fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" opacity=".45"/>'
    body += fit(
        _bold("FAN", "Bowlby One", "#fff", "#4c0519", 10, ext=(0, 8, "#4c0519")), 156, 118, 200, 112
    )
    body += (
        '<g filter="url(#sh)">' + banner(34, 478, 250, 76, "#fde047", "#4c0519", 7, cut=22) + "</g>"
    )
    body += fit(text("FAVORITE", "Bowlby One", 100, fill="#4c0519", ls=4), 96, 262, 320, 52)
    body += fit(
        text("THE SHOWS YOU LOVE", "Oswald", 40, weight=700, fill="#fff", ls=6), 176, 348, 160, 20
    )
    return svg(body, d)


def _rewind(p: P) -> str:
    return (
        f'<polygon points="100,40 100,160 20,100" fill="{p.a}" {_o(p, 8)}/>'
        f'<polygon points="184,40 184,160 104,100" fill="{p.a}" {_o(p, 8)}/>'
    )


@net("Recap", SHOWS, "tv shows", "catch-up", "marathons")
def recap():
    return L.tile_word(
        _rewind(P(a="#fff", b="#fff", c="#fff", k="#0c4a6e", l="#fff")),
        "RECAP",
        font="Montserrat",
        weight=900,
        ink="#fff",
        edge="#0c4a6e",
        tile="#38bdf8",
        tile2="#0369a1",
        sub="CATCH UP ON EVERYTHING",
        sub_ink="#7dd3fc",
        shape="square",
        ls=6,
    )


def _tower_scene() -> str:
    g = '<rect x="0" y="0" width="512" height="512" fill="url(#synsky)"/>'
    g += '<g fill="none" stroke="#fde68a" stroke-linecap="round">'
    for r, o in ((48, 0.9), (86, 0.65), (124, 0.4)):
        g += f'<path d="M{256 - r} {120 - r * 0.2:.0f} A{r} {r} 0 0 1 {256 + r} {120 - r * 0.2:.0f}" stroke-width="9" opacity="{o}"/>'
    g += "</g>"
    g += '<path d="M256 112 L206 392 L306 392 Z" fill="none" stroke="#1e1b4b" stroke-width="10" stroke-linejoin="round"/>'
    for y in (170, 230, 290, 350):
        hw = (y - 112) * 50 / 280
        g += f'<line x1="{256 - hw:.0f}" y1="{y}" x2="{256 + hw:.0f}" y2="{y}" stroke="#1e1b4b" stroke-width="7"/>'
        g += f'<line x1="{256 - hw:.0f}" y1="{y}" x2="{256 + hw + 9:.0f}" y2="{y + 60}" stroke="#1e1b4b" stroke-width="4"/>'
    g += '<circle cx="256" cy="108" r="12" fill="#ef4444" stroke="#1e1b4b" stroke-width="5"/>'
    return g


@net("Syndicated", SHOWS, "tv shows", "reruns", "classic tv")
def syndicated():
    return L.emblem(
        _tower_scene(),
        "SYNDICATED",
        font="Oswald",
        weight=700,
        ink="#fff",
        band="#1e1b4b",
        rim="#fde68a",
        edge="#1e1b4b",
        defs=lin("synsky", [(0, "#f97316"), (1, "#fcd34d")]),
        ls=6,
        sub="COAST TO COAST",
        sub_font="Oswald",
    )


@net("Talk of the Town", SHOWS, "tv shows", "talk shows", "late night")
def talk_of_the_town():
    d = SH + lin("tts", [(0, "#0b1340"), (1, "#3b2a78")])
    rng = random.Random(4)
    body = '<defs><clipPath id="ttc"><rect x="34" y="70" width="444" height="372" rx="30"/></clipPath></defs>'
    body += _panel(34, 70, 444, 372, "url(#tts)", rx=30)
    body += '<g clip-path="url(#ttc)">'
    body += '<circle cx="396" cy="140" r="34" fill="#fef3c7" opacity=".9"/>'
    x = 34
    while x < 478:
        w = rng.uniform(26, 52)
        h = rng.uniform(70, 170)
        body += (
            f'<rect x="{x:.0f}" y="{442 - h:.0f}" width="{w:.0f}" height="{h:.0f}" fill="#0a0f2c"/>'
        )
        for wy in range(int(442 - h + 12), 432, 18):
            for wx in range(int(x + 6), int(x + w - 8), 12):
                if rng.random() < 0.35:
                    body += f'<rect x="{wx}" y="{wy}" width="5" height="7" fill="#fcd34d" opacity=".8"/>'
        x += w + 2
    body += '<rect x="34" y="372" width="444" height="70" fill="#0a0f2c" opacity=".85"/></g>'
    body += '<rect x="34" y="70" width="444" height="372" rx="30" fill="none" stroke="#fcd34d" stroke-width="6"/>'
    w = text("Talk of the Town", "Yellowtail", 100, fill="#fff", stroke="#0a0f2c", sw=12)
    body += f'<g filter="url(#sh)">{fit(w, 58, 196, 396, 120)}</g>'
    body += fit(
        text("TALK · LATE NIGHT · VARIETY", "Oswald", 40, weight=600, fill="#fcd34d", ls=8),
        116,
        392,
        280,
        22,
    )
    return svg(body, d)


@net("Couch Potato", SHOWS, "tv shows", "binge", "comfort tv")
def couch_potato():
    d = SH + lin("cpf", [(0, "#f97316"), (1, "#c2410c")])
    sofa = (
        "M62 140 Q62 104 98 104 L414 104 Q450 104 450 140 L450 236 "
        "Q488 236 488 272 L488 380 Q488 404 464 404 L48 404 Q24 404 24 380 L24 272 Q24 236 62 236 Z"
    )
    body = f'<g filter="url(#sh)"><path d="{sofa}" fill="url(#cpf)" stroke="#431407" stroke-width="10" stroke-linejoin="round"/></g>'
    body += '<path d="M62 236 L62 330 L450 330 L450 236" fill="none" stroke="#431407" stroke-width="6" opacity=".5"/>'
    body += (
        '<line x1="256" y1="330" x2="256" y2="404" stroke="#431407" stroke-width="6" opacity=".5"/>'
    )
    for x in (66, 446):
        body += f'<rect x="{x - 10}" y="404" width="20" height="30" rx="5" fill="#431407"/>'
    body += fit(
        _bold("COUCH", "Archivo Black", "#fff7ed", "#431407", 10, ext=(0, 7, "#431407")),
        92,
        130,
        328,
        92,
    )
    body += fit(
        text("POTATO", "Archivo Black", 100, fill="#fde68a", stroke="#431407", sw=8, ls=8),
        110,
        250,
        292,
        64,
    )
    body += fit(
        text("SETTLE IN", "Oswald", 40, weight=700, fill="#fff7ed", ls=10), 196, 350, 120, 34
    )
    return svg(body, d)


@net("Two-Parter", SHOWS, "tv shows", "cliffhangers", "drama")
def two_parter():
    d = SH
    body = '<defs><clipPath id="tpc"><rect x="40" y="96" width="432" height="320" rx="26"/></clipPath></defs>'
    body += _panel(40, 96, 432, 320, "#0f172a", rx=26)
    body += (
        '<g clip-path="url(#tpc)"><polygon points="40,96 296,96 216,416 40,416" fill="#dc2626"/>'
    )
    body += '<polygon points="296,96 472,96 472,416 216,416" fill="#1e3a8a"/>'
    body += '<line x1="296" y1="96" x2="216" y2="416" stroke="#f8fafc" stroke-width="10"/></g>'
    body += '<rect x="40" y="96" width="432" height="320" rx="26" fill="none" stroke="#0f172a" stroke-width="8"/>'
    body += fit(text("PART I", "Oswald", 40, weight=700, fill="#fecaca", ls=8), 70, 126, 120, 30)
    body += fit(text("PART II", "Oswald", 40, weight=700, fill="#bfdbfe", ls=8), 326, 356, 120, 30)
    body += f'<g filter="url(#sh)">{fit(_bold("TWO-PARTER", "Anton", "#fff", "#0f172a", 12, ls=4), 60, 192, 392, 126)}</g>'
    return svg(body, d)


@net("Very Special Episode", SHOWS, "tv shows", "sitcoms", "80s", "90s")
def very_special_episode():
    d = SH + lin("vse", [(0, "#c4b5fd"), (0.55, "#f9a8d4"), (1, "#fde68a")])
    body = _panel(36, 80, 440, 352, "url(#vse)", rx=180)
    body += '<rect x="56" y="100" width="400" height="312" rx="156" fill="none" stroke="#fff" stroke-width="4" opacity=".8"/>'
    body += f'<g filter="url(#sh)">{fit(text("Very Special", "Great Vibes", 100, fill="#4c1d95", stroke="#fff", sw=6), 82, 140, 348, 120)}</g>'
    body += fit(
        text("EPISODE", "Playfair Display", 100, weight=700, fill="#4c1d95", ls=18),
        136,
        276,
        240,
        54,
    )
    body += '<line x1="176" y1="350" x2="336" y2="350" stroke="#4c1d95" stroke-width="2.5"/>'
    body += fit(
        text("TONIGHT · A LESSON FOR EVERYONE", "Montserrat", 40, weight=600, fill="#4c1d95", ls=4),
        146,
        362,
        220,
        16,
    )
    for x, y, r in ((396, 138, 18), (116, 360, 13)):
        body += f'<path d="M{x} {y - r} Q{x + 3} {y - 3} {x + r} {y} Q{x + 3} {y + 3} {x} {y + r} Q{x - 3} {y + 3} {x - r} {y} Q{x - 3} {y - 3} {x} {y - r} Z" fill="#fff"/>'
    return svg(body, d)


@net("Sweeps Week", SHOWS, "tv shows", "event tv", "big episodes")
def sweeps_week():
    d = SH + lin("swb", [(0, "#22d3ee"), (1, "#0e7490")])
    body = _panel(36, 60, 440, 392, "#0b1120", rx=28)
    for i, h in enumerate((70, 112, 96, 156, 214)):
        x = 80 + i * 72
        body += f'<rect x="{x}" y="{300 - h}" width="52" height="{h}" rx="6" fill="url(#swb)" opacity=".9"/>'
    body += '<path d="M80 236 L176 186 L236 206 L330 120 L432 70" fill="none" stroke="#facc15" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>'
    body += '<polygon points="440,56 452,100 408,86" fill="#facc15"/>'
    body += '<rect x="36" y="300" width="440" height="152" rx="0" fill="#0b1120"/>'
    body += '<rect x="36" y="60" width="440" height="392" rx="28" fill="none" stroke="#22d3ee" stroke-width="6"/>'
    body += f'<g filter="url(#sh)">{fit(_bold("SWEEPS", "Anton", "#fff", "#000", 8, ls=6), 66, 312, 260, 100)}</g>'
    body += '<g filter="url(#sh)"><rect x="338" y="322" width="114" height="80" rx="10" fill="#facc15"/></g>'
    body += fit(text("WEEK", "Anton", 100, fill="#0b1120", ls=2), 350, 336, 90, 52)
    body += fit(
        text("THE BIG EPISODES", "Oswald", 40, weight=600, fill="#67e8f9", ls=10), 140, 416, 232, 20
    )
    return svg(body, d)


@net("Opening Credits", SHOWS, "tv shows", "drama", "prestige")
def opening_credits():
    d = SH + lin("ocw", [(0, "#ffffff"), (1, "#cbd5e1")])
    body = _panel(36, 96, 440, 320, "#050505", rx=8)
    body += '<rect x="36" y="96" width="440" height="320" rx="8" fill="none" stroke="#3f3f46" stroke-width="3"/>'
    body += fit(text("O P E N I N G", "Poiret One", 40, fill="#e5e5e5"), 146, 140, 220, 30)
    body += fit(
        text("CREDITS", "DM Serif Display", 100, fill="url(#ocw)", ls=10), 76, 186, 360, 100
    )
    body += '<line x1="196" y1="306" x2="316" y2="306" stroke="#e5e5e5" stroke-width="1.5"/>'
    for i, (a, b) in enumerate((("CREATED BY", "YOU"), ("STARRING", "EVERYONE"))):
        y = 324 + i * 32
        body += fit(text(a, "Montserrat", 40, weight=500, fill="#a1a1aa", ls=6), 116, y, 130, 16)
        body += fit(text(b, "Montserrat", 40, weight=800, fill="#fafafa", ls=6), 266, y, 130, 16)
    return svg(body, d)


@net("Theme Song", SHOWS, "tv shows", "sitcoms", "music")
def theme_song():
    d = SH + rad("tsr", [(0, "#3f3f46"), (1, "#09090b")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="236" r="196" fill="url(#tsr)" stroke="#000" stroke-width="6"/></g>'
    for r in range(100, 192, 10):
        body += f'<circle cx="256" cy="236" r="{r}" fill="none" stroke="#52525b" stroke-width="1.5" opacity=".6"/>'
    body += '<path d="M150 110 A150 150 0 0 1 300 92" fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" opacity=".18"/>'
    body += '<circle cx="256" cy="236" r="80" fill="#f43f5e"/><circle cx="256" cy="236" r="80" fill="none" stroke="#fde68a" stroke-width="4"/>'
    body += '<circle cx="256" cy="236" r="14" fill="#09090b"/>'
    body += (
        '<g filter="url(#sh)">' + banner(28, 484, 300, 90, "#fde68a", "#18181b", 7, cut=24) + "</g>"
    )
    body += fit(
        text("Theme Song", "Shrikhand", 100, fill="#e11d48", stroke="#18181b", sw=6),
        84,
        312,
        344,
        66,
    )
    body += fit(text("TV", "Archivo Black", 100, fill="#fde68a"), 236, 186, 40, 26)
    return svg(body, d)


# ======================================================================= decades


@net("50s TV", DECADES, "1950s", "classic tv", "black and white")
def tv_50s():
    return L.tv_screen(
        "Fifties",
        "50s TV",
        "SHOWS FROM THE FIFTIES",
        screen=("#5eead4", "#0f766e"),
        band="#dc2626",
        cabinet="#fef3c7",
        edge="#1c1917",
        ink="#fffbeb",
        script_font="Lobster",
        font="Archivo Black",
    )


@net("60s TV", DECADES, "1960s", "classic tv", "mod")
def tv_60s():
    d = SH
    body = '<defs><clipPath id="c60"><rect x="40" y="40" width="432" height="432" rx="20"/></clipPath></defs>'
    body += _panel(40, 40, 432, 432, "#0a0a0a", rx=20)
    body += '<g clip-path="url(#c60)">'
    for i in range(12):
        r = 300 - i * 26
        c = "#f5f5f4" if i % 2 == 0 else "#0a0a0a"
        body += f'<rect x="{256 - r}" y="{256 - r}" width="{2 * r}" height="{2 * r}" fill="{c}" transform="rotate({i * 4} 256 256)"/>'
    body += "</g>"
    body += '<g filter="url(#sh)"><rect x="96" y="176" width="320" height="160" rx="8" fill="#f97316" stroke="#0a0a0a" stroke-width="8"/></g>'
    body += fit(text("60s TV", "Anton", 100, fill="#0a0a0a", ls=4), 120, 196, 272, 120)
    body += '<rect x="40" y="40" width="432" height="432" rx="20" fill="none" stroke="#0a0a0a" stroke-width="8"/>'
    return svg(body, d)


@net("70s TV", DECADES, "1970s", "classic tv")
def tv_70s():
    d = SH + lin("wood70", [(0, "#7c4a21"), (0.5, "#5b3415"), (1, "#3f230d")], x2=1, y2=0)
    body = _panel(30, 96, 452, 320, "url(#wood70)", rx=36, edge="#1c0f05", sw=6)
    for i in range(9):
        y = 116 + i * 34
        body += f'<path d="M50 {y} Q256 {y + (10 if i % 2 else -8)} 462 {y}" fill="none" stroke="#2a1608" stroke-width="2" opacity=".35"/>'
    for i, c in enumerate(("#facc15", "#f97316", "#ea580c", "#b91c1c")):
        body += f'<rect x="30" y="{306 + i * 13}" width="452" height="13" fill="{c}"/>'
    w = _bold("70s TV", "Bowlby One", "#fff7ed", "#1c0f05", 12, ext=(6, 8, "#1c0f05"))
    body += f'<g filter="url(#sh)">{fit(w, 56, 140, 400, 140)}</g>'
    sub = text("THE SEVENTIES ON TV", "Oswald", 40, weight=700, fill="#fde68a", ls=8)
    body += fit(sub, 116, 372, 280, 24)
    return svg(body, d)


@net("80s TV", DECADES, "1980s", "classic tv", "retro")
def tv_80s():
    back = (
        '<rect x="20" y="92" width="472" height="328" rx="20" fill="url(#gr80)" filter="url(#sh)"/>'
    )
    back += '<defs><clipPath id="g80"><rect x="20" y="92" width="472" height="328" rx="20"/></clipPath></defs><g clip-path="url(#g80)">'
    back += '<circle cx="256" cy="330" r="96" fill="url(#sun80)"/>'
    for i in range(4):
        back += f'<rect x="140" y="{282 + i * 10}" width="232" height="{2 + i}" fill="#1a0b3a"/>'
    back += '<rect x="20" y="320" width="472" height="100" fill="#1a0b3a"/>'
    for i in range(-8, 9):
        back += f'<line x1="{256 + i * 18}" y1="320" x2="{256 + i * 70}" y2="430" stroke="#ff4fd8" stroke-width="2"/>'
    for y in (330, 344, 362, 386, 416):
        back += f'<line x1="20" y1="{y}" x2="492" y2="{y}" stroke="#ff4fd8" stroke-width="2"/>'
    back += "</g>"
    defs = lin("gr80", [(0, "#0b0326"), (1, "#3b0a5c")]) + lin(
        "sun80", [(0, "#fde047"), (1, "#f43f5e")]
    )
    return L.chrome("80s TV", None, back=back, defs=defs, box=(40, 112, 432, 140))


@net("90s TV", DECADES, "1990s", "classic tv")
def tv_90s():
    d = SH + lin("p90", [(0, "#7c3aed"), (1, "#0d9488")], x2=1, y2=1)
    body = '<g filter="url(#sh)" transform="rotate(-6 256 256)"><rect x="44" y="96" width="424" height="320" rx="10" fill="url(#p90)" stroke="#0a0a0a" stroke-width="8"/></g>'
    body += '<path d="M44 150 L110 120 L176 160 L242 118 L308 160 L374 120 L468 150" fill="none" stroke="#facc15" stroke-width="12" stroke-linejoin="round" transform="rotate(-6 256 256)"/>'
    w = _bold("90s", "Titan One", "#fff", "#0a0a0a", 12, ext=(10, 10, "#facc15"))
    body += f'<g filter="url(#sh)">{fit(w, 92, 166, 300, 160)}</g>'
    body += '<g filter="url(#sh)" transform="rotate(-6 256 256)"><rect x="300" y="300" width="140" height="80" fill="#ef4444" stroke="#0a0a0a" stroke-width="7"/></g>'
    body += f'<g transform="rotate(-6 370 340)">{fit(text("TV", "Titan One", 100, fill="#fff"), 320, 312, 100, 56)}</g>'
    return svg(body, d)


@net("2000s TV", DECADES, "2000s", "tv shows")
def tv_2000s():
    d = (
        SH
        + lin("bez", [(0, "#e5e7eb"), (0.5, "#9ca3af"), (1, "#4b5563")])
        + lin("scr00", [(0, "#0b1220"), (1, "#1e3a8a")])
    )
    d += lin(
        "sw00",
        [
            (
                0,
                "#38bdf8",
            ),
            (1, "#a5f3fc"),
        ],
    )
    body = '<g filter="url(#sh)"><rect x="24" y="96" width="464" height="280" rx="16" fill="url(#bez)" stroke="#111827" stroke-width="5"/></g>'
    body += '<rect x="42" y="112" width="428" height="240" rx="6" fill="url(#scr00)"/>'
    body += '<path d="M42 300 Q200 200 470 250 L470 352 L42 352 Z" fill="#38bdf8" opacity=".25"/>'
    body += '<path d="M42 330 Q240 250 470 290" fill="none" stroke="url(#sw00)" stroke-width="6" opacity=".9"/>'
    body += '<path d="M42 112 L300 112 L42 260 Z" fill="#fff" opacity=".08"/>'
    body += '<rect x="208" y="376" width="96" height="20" fill="#6b7280"/><rect x="156" y="396" width="200" height="16" rx="8" fill="#374151"/>'
    body += '<circle cx="256" cy="366" r="3.5" fill="#60a5fa"/>'
    w = text("2000s", "Sora", 100, weight=800, fill="#fff")
    body += f'<g filter="url(#sh)">{fit(w, 86, 140, 340, 104)}</g>'
    body += fit(text("TV", "Sora", 100, weight=300, fill="#7dd3fc", ls=24), 200, 262, 112, 60)
    return svg(body, d)


@net("50s Movies", DECADES, "1950s", "movies", "classic movies")
def movies_50s():
    return L.poster(
        "IN GLORIOUS COLOR",
        "50s",
        "MOVIES",
        font="Bevan",
        small_font="Oswald",
        ink="#b91c1c",
        seed=8,
        deco="rule",
    )


@net("60s Movies", DECADES, "1960s", "movies", "classic movies")
def movies_60s():
    d = SH
    body = _panel(40, 50, 432, 412, "#f97316", rx=4)
    body += '<rect x="78" y="88" width="116" height="250" fill="#0a0a0a"/>'
    body += '<rect x="214" y="88" width="56" height="250" fill="#0a0a0a"/>'
    body += '<rect x="290" y="88" width="144" height="120" fill="#0a0a0a"/>'
    body += '<rect x="290" y="228" width="144" height="110" fill="#fff7ed"/>'
    body += '<path d="M290 228 L434 338" stroke="#0a0a0a" stroke-width="10"/>'
    body += fit(text("60s", "Anton", 100, fill="#fff7ed"), 88, 130, 96, 170)
    body += fit(text("MOVIES", "Bebas Neue", 100, fill="#0a0a0a", ls=16), 78, 352, 356, 84)
    return svg(body, d)


@net("70s Movies", DECADES, "1970s", "movies")
def movies_70s():
    return L.film_frame(
        "70s MOVIES", "NEW HOLLYWOOD", font="Shrikhand", ink="#9a3412", frame_fill="#fde68a"
    )


@net("80s Movies", DECADES, "1980s", "movies", "vhs")
def movies_80s():
    d = SH + lin(
        "vhs",
        [(0, "#ef4444"), (0.25, "#f97316"), (0.5, "#facc15"), (0.75, "#22c55e"), (1, "#3b82f6")],
        x2=1,
        y2=0,
    )
    body = _panel(70, 40, 372, 432, "#0a0a0a", rx=12, edge="#000", sw=4)
    body += '<rect x="70" y="300" width="372" height="26" fill="url(#vhs)"/>'
    body += '<rect x="70" y="334" width="372" height="8" fill="url(#vhs)" opacity=".7"/>'
    body += '<rect x="96" y="70" width="320" height="200" rx="6" fill="#f8fafc"/>'
    body += '<rect x="96" y="70" width="320" height="34" rx="6" fill="#e11d48"/>'
    body += fit(
        text("FEATURE PRESENTATION", "Oswald", 40, weight=700, fill="#fff", ls=6), 120, 78, 272, 20
    )
    w = _bold("80s", "Racing Sans One", "#e11d48", "#0a0a0a", 6, style="italic")
    body += fit(w, 120, 112, 272, 100)
    body += fit(text("MOVIES", "Archivo Black", 100, fill="#0a0a0a", ls=12), 130, 218, 252, 40)
    body += fit(text("HI-FI · STEREO", "Michroma", 40, fill="#e5e7eb", ls=6), 150, 370, 212, 20)
    body += fit(
        text("BE KIND · REWIND", "Oswald", 40, weight=600, fill="#9ca3af", ls=8), 166, 412, 180, 20
    )
    return svg(body, d)


@net("90s Movies", DECADES, "1990s", "movies")
def movies_90s():
    d = SH
    ink, paper, edge, accent = "#6d28d9", "#fef9c3", "#1e1b4b", "#0d9488"
    tk = "M40 150 L472 150 L472 214 A42 42 0 0 0 472 298 L472 362 L40 362 L40 298 A42 42 0 0 0 40 214 Z"
    body = f'<g transform="rotate(-6 256 256)"><g filter="url(#sh)"><path d="{tk}" fill="{paper}" stroke="{edge}" stroke-width="7"/></g>'
    body += f'<path d="M66 172 L446 172 L446 222 A30 30 0 0 0 446 290 L446 340 L66 340 L66 290 A30 30 0 0 0 66 222 Z" fill="none" stroke="{accent}" stroke-width="4"/>'
    body += f'<line x1="372" y1="160" x2="372" y2="352" stroke="{edge}" stroke-width="4" stroke-dasharray="10 8"/>'
    body += fit(_bold("90s", "Titan One", ink, edge, 6), 122, 184, 220, 98)
    body += fit(text("MOVIES", "Titan One", 100, fill=accent, ls=8), 136, 288, 192, 38)
    body += f'<g transform="translate(409 256) rotate(-90)">{text("ADMIT ONE", "Oswald", 26, weight=700, fill=edge, ls=3, y=9)}</g>'
    body += "</g>"
    return svg(body, d)


@net("2000s Movies", DECADES, "2000s", "movies", "dvd")
def movies_2000s():
    d = SH + "<linearGradient id='irid' x1='0' y1='0' x2='1' y2='1'>"
    d += "".join(
        f"<stop offset='{o}' stop-color='{c}'/>"
        for o, c in (
            (0, "#e0f2fe"),
            (0.2, "#c4b5fd"),
            (0.4, "#f9a8d4"),
            (0.55, "#fde68a"),
            (0.7, "#a7f3d0"),
            (0.85, "#93c5fd"),
            (1, "#e0e7ff"),
        )
    )
    d += "</linearGradient>"
    body = '<g filter="url(#sh)"><circle cx="256" cy="220" r="190" fill="url(#irid)" stroke="#475569" stroke-width="5"/></g>'
    body += '<circle cx="256" cy="220" r="66" fill="#e2e8f0" stroke="#94a3b8" stroke-width="4"/><circle cx="256" cy="220" r="24" fill="#1a1a2e" stroke="#94a3b8" stroke-width="4"/>'
    body += '<path d="M120 120 A190 190 0 0 1 250 32" fill="none" stroke="#fff" stroke-width="16" opacity=".5" stroke-linecap="round"/>'
    body += (
        '<g filter="url(#sh)">' + banner(26, 486, 330, 92, "#111827", "#94a3b8", 5, cut=24) + "</g>"
    )
    body += fit(
        text("2000s MOVIES", "Sora", 100, weight=800, fill="#f8fafc", ls=2), 76, 344, 360, 62
    )
    body += fit(
        text("WIDESCREEN EDITION", "Oswald", 40, weight=600, fill="#e2e8f0", ls=8),
        146,
        438,
        220,
        26,
    )
    return svg(body, d)


@net("Y2K", DECADES, "2000s", "y2k", "late 90s")
def y2k():
    d = SH + lin(
        "y2kc",
        [(0, "#ffffff"), (0.45, "#c7d2fe"), (0.5, "#4338ca"), (0.62, "#a5b4fc"), (1, "#f5f3ff")],
    )
    d += lin("y2kp", [(0, "#cffafe"), (1, "#a5b4fc")], x2=1, y2=1)
    body = _panel(36, 70, 440, 372, "url(#y2kp)", rx=60, edge="#fff", sw=6)
    body += '<path d="M60 120 Q60 94 96 94 L300 94 Q140 140 70 220 Z" fill="#fff" opacity=".45"/>'
    w = text("Y2K", "Unbounded", 100, weight=900, fill="url(#y2kc)", stroke="#1e1b4b", sw=10)
    body += f'<g filter="url(#sh)">{fit(w, 66, 120, 380, 160)}</g>'
    body += '<rect x="136" y="310" width="240" height="88" rx="12" fill="#0b1026" stroke="#1e1b4b" stroke-width="5"/>'
    body += seg7("00:00", 160, 324, 60, "#22d3ee", "#0f2240")
    for x, y, r in ((428, 116, 22), (84, 396, 16), (440, 400, 12)):
        body += f'<path d="M{x} {y - r} Q{x + 3} {y - 3} {x + r} {y} Q{x + 3} {y + 3} {x} {y + r} Q{x - 3} {y + 3} {x - r} {y} Q{x - 3} {y - 3} {x} {y - r} Z" fill="#fff"/>'
    return svg(body, d)


def _atomic_star(cx, cy, r, c, n=8):
    s = ""
    for k in range(n):
        a = math.radians(k * 180 / n)
        rr = r if k % 2 == 0 else r * 0.6
        s += f'<line x1="{cx - rr * math.cos(a):.1f}" y1="{cy - rr * math.sin(a):.1f}" x2="{cx + rr * math.cos(a):.1f}" y2="{cy + rr * math.sin(a):.1f}" stroke="{c}" stroke-width="{max(2, r / 14):.1f}" stroke-linecap="round"/>'
    return s + f'<circle cx="{cx}" cy="{cy}" r="{r / 6:.1f}" fill="{c}"/>'


@net("Mid-Century", DECADES, "1950s", "1960s", "classic tv")
def mid_century():
    d = SH
    body = _panel(36, 86, 440, 340, "#f5ecd7", rx=24, edge="#2b2b2b", sw=5)
    body += '<path d="M60 380 Q140 300 250 330 Q190 360 150 410 Z" fill="#0f766e" opacity=".9"/>'
    body += '<path d="M330 120 Q400 110 450 150 Q400 150 360 190 Z" fill="#ea580c" opacity=".9"/>'
    body += '<circle cx="96" cy="140" r="30" fill="#eab308" opacity=".9"/>'
    body += (
        _atomic_star(410, 360, 40, "#2b2b2b")
        + _atomic_star(150, 140, 24, "#0f766e")
        + _atomic_star(380, 230, 16, "#ea580c")
    )
    body += f'<g filter="url(#sh)">{fit(text("Mid-Century", "Yellowtail", 100, fill="#2b2b2b", stroke="#f5ecd7", sw=8), 64, 170, 384, 120)}</g>'
    body += fit(
        text("MODERN CLASSICS", "Montserrat", 40, weight=700, fill="#ea580c", ls=14),
        112,
        300,
        288,
        30,
    )
    return svg(body, d)


# ======================================================================= over-the-air movie slots


@net("The 4:30 Movie", OTA, "movies", "afternoon movies", "local tv")
def the_430_movie():
    d = SH + lin("sky430", [(0, "#1e3a8a"), (1, "#0b1a3a")])
    body = _panel(34, 70, 444, 372, "url(#sky430)", rx=26, edge="#020617", sw=5)
    for i, c in enumerate(("#f97316", "#fb923c", "#fdba74")):
        body += f'<rect x="34" y="{282 + i * 18}" width="444" height="12" fill="{c}"/>'
    body += fit(text("THE", "Oswald", 40, weight=700, fill="#fdba74", ls=16), 206, 96, 100, 28)
    w = _bold("4:30", "Bebas Neue", "#fff", "#020617", 10, ext=(5, 7, "#020617"))
    body += f'<g filter="url(#sh)">{fit(w, 96, 128, 320, 150)}</g>'
    body += '<rect x="34" y="340" width="444" height="80" fill="#020617"/>'
    body += fit(text("MOVIE", "Bebas Neue", 100, fill="#fdba74", ls=28), 140, 350, 232, 62)
    return svg(body, d)


@net("The Late Movie", OTA, "movies", "late night", "local tv")
def the_late_movie():
    d = SH + rad("lmsky", [(0, "#312e81"), (1, "#020617")], cx=0.7, cy=0.25, r=0.9)
    body = _panel(34, 56, 444, 400, "url(#lmsky)", rx=200, edge="#020617", sw=5)
    body += '<circle cx="344" cy="140" r="52" fill="#fef3c7"/><circle cx="368" cy="124" r="50" fill="#1e1b4b"/>'
    for x, y in ((140, 120), (200, 96), (430, 220), (110, 210), (260, 82)):
        body += f'<circle cx="{x}" cy="{y}" r="3" fill="#fff"/>'
    body += fit(
        text("THE", "Playfair Display", 40, weight=700, fill="#c7d2fe", ls=16), 196, 176, 120, 24
    )
    body += f'<g filter="url(#sh)">{fit(text("Late", "Playfair Display", 100, weight=900, fill="#fef3c7", style="italic"), 120, 200, 272, 110)}</g>'
    body += fit(
        text("MOVIE", "Playfair Display", 100, weight=700, fill="#a5b4fc", ls=26), 130, 320, 252, 56
    )
    body += '<line x1="190" y1="396" x2="322" y2="396" stroke="#a5b4fc" stroke-width="2"/>'
    return svg(body, d)


@net("Sunday Night Movie", OTA, "movies", "sunday", "local tv")
def sunday_night_movie():
    return L.marquee(
        "MOVIE",
        "SUNDAY NIGHT",
        crest="TONIGHT",
        crest_ink="#fde68a",
        board="#fffbeb",
        letters="#111827",
        frame="#1e3a8a",
        edge="#0b1026",
        font="Oswald",
    )


@net("Afternoon Movie", OTA, "movies", "afternoon movies", "local tv")
def afternoon_movie():
    d = SH + lin("aft", [(0, "#fde68a"), (1, "#f59e0b")])
    body = '<defs><clipPath id="afc"><rect x="36" y="76" width="440" height="360" rx="26"/></clipPath></defs>'
    body += _panel(36, 76, 440, 360, "#fff7e6", rx=26, edge="#78350f", sw=6)
    body += '<g clip-path="url(#afc)">'
    for k in range(13):
        a1 = math.radians(180 + k * 15)
        a2 = math.radians(180 + k * 15 + 7.5)
        body += f'<polygon points="256,300 {256 + 600 * math.cos(a1):.0f},{300 + 600 * math.sin(a1):.0f} {256 + 600 * math.cos(a2):.0f},{300 + 600 * math.sin(a2):.0f}" fill="#fcd34d" opacity=".55"/>'
    body += '<circle cx="256" cy="300" r="96" fill="url(#aft)" stroke="#78350f" stroke-width="5"/>'
    body += '<rect x="36" y="300" width="440" height="136" fill="#78350f"/></g>'
    body += '<rect x="36" y="76" width="440" height="360" rx="26" fill="none" stroke="#78350f" stroke-width="6"/>'
    body += f'<g filter="url(#sh)">{fit(_bold("AFTERNOON", "Alfa Slab One", "#fff7e6", "#78350f", 10), 66, 196, 380, 84)}</g>'
    body += fit(text("MOVIE", "Alfa Slab One", 100, fill="#fcd34d", ls=20), 146, 320, 220, 60)
    body += fit(
        text("RIGHT AFTER LUNCH", "Oswald", 40, weight=600, fill="#fde68a", ls=8), 166, 394, 180, 20
    )
    return svg(body, d)


@net("Movie of the Week", OTA, "movies", "made for tv", "local tv")
def movie_of_the_week():
    d = SH + lin("mow", [(0, "#f43f5e"), (1, "#9f1239")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="226" r="190" fill="url(#mow)" stroke="#1c1917" stroke-width="8"/></g>'
    body += '<circle cx="256" cy="226" r="168" fill="none" stroke="#fde68a" stroke-width="3"/>'
    body += f'<polygon points="{star(256, 118, 34, 14)}" fill="#fde68a"/>'
    body += f'<g filter="url(#sh)">{fit(_bold("MOVIE", "Archivo Black", "#fff", "#1c1917", 10), 96, 166, 320, 96)}</g>'
    body += (
        '<g filter="url(#sh)">' + banner(30, 482, 300, 84, "#fde68a", "#1c1917", 7, cut=22) + "</g>"
    )
    body += fit(text("of the Week", "Lobster", 100, fill="#9f1239"), 110, 310, 292, 60)
    return svg(body, d)


@net("Weekend Movie", OTA, "movies", "weekend", "local tv")
def weekend_movie():
    d = SH
    body = _panel(36, 96, 440, 320, "#0e7490", rx=26, edge="#082f49", sw=6)
    body += '<rect x="36" y="300" width="440" height="116" fill="#082f49" rx="0"/>'
    body += '<rect x="36" y="384" width="440" height="32" rx="0" fill="#082f49"/>'
    body += '<path d="M36 390 Q36 416 62 416 L450 416 Q476 416 476 390 Z" fill="#082f49"/>'
    for i, (lab, c) in enumerate((("SAT", "#facc15"), ("SUN", "#fb923c"))):
        x = 150 + i * 120
        body += f'<g filter="url(#sh)"><rect x="{x}" y="120" width="92" height="50" rx="25" fill="{c}" stroke="#082f49" stroke-width="5"/></g>'
        body += fit(text(lab, "Bungee", 100, fill="#082f49"), x + 18, 130, 56, 30)
    body += f'<g filter="url(#sh)">{fit(_bold("WEEKEND", "Bungee", "#fff", "#082f49", 10), 66, 186, 380, 96)}</g>'
    body += fit(text("MOVIE", "Bungee", 100, fill="#facc15", ls=14), 156, 316, 200, 56)
    return svg(body, d)


@net("Morning Movie", OTA, "movies", "morning", "local tv")
def morning_movie():
    d = SH + lin("mm", [(0, "#bae6fd"), (0.6, "#fed7aa"), (1, "#fdba74")])
    body = '<defs><clipPath id="mmc"><rect x="36" y="80" width="440" height="352" rx="176"/></clipPath></defs>'
    body += _panel(36, 80, 440, 352, "url(#mm)", rx=176, edge="#7c2d12", sw=6)
    body += (
        '<g clip-path="url(#mmc)"><circle cx="256" cy="330" r="70" fill="#fde047" opacity=".9"/>'
    )
    body += '<rect x="36" y="330" width="440" height="110" fill="#7c2d12"/></g>'
    body += '<rect x="36" y="80" width="440" height="352" rx="176" fill="none" stroke="#7c2d12" stroke-width="6"/>'
    body += f'<g filter="url(#sh)">{fit(text("Morning", "Pacifico", 100, fill="#7c2d12", stroke="#fff7ed", sw=10), 96, 120, 320, 140)}</g>'
    body += fit(text("MOVIE", "Archivo Black", 100, fill="#fff7ed", ls=16), 156, 346, 200, 52)
    return svg(body, d)


# ================================================================== collections

ON_AIR = "On the air"


@net("Collection", ON_AIR, "collection", "library", "favorites")
def collection():
    """The logo a station made from a Plex collection starts with: a shelf
    of cases, one of each colour."""
    ink = "#0b1220"
    d = (
        SH
        + lin("cln", [(0, "#1e293b"), (1, "#0f172a")])
        + lin("clw", [(0, "#b45309"), (1, "#78350f")])
    )
    body = _panel(36, 48, 440, 416, "url(#cln)", rx=36, edge="#000", sw=5)
    spines = (
        (88, 44, 168, "#ef4444"), (136, 38, 190, "#f59e0b"), (178, 46, 176, "#14b8a6"),
        (228, 40, 200, "#8b5cf6"), (272, 44, 182, "#22c55e"), (320, 38, 194, "#f97316"),
    )  # fmt: skip
    for x, w, h, colour in spines:
        top = 300 - h
        body += f'<rect x="{x}" y="{top}" width="{w}" height="{h}" rx="5" fill="{colour}" stroke="{ink}" stroke-width="4"/>'
        body += f'<rect x="{x + 6}" y="{top + 18}" width="{w - 12}" height="22" rx="3" fill="#f8fafc" opacity=".9"/>'
        body += f'<line x1="{x + w / 2}" y1="{top + 58}" x2="{x + w / 2}" y2="{300 - 22}" stroke="#000" stroke-width="4" stroke-linecap="round" opacity=".22"/>'
    lean = '<rect x="0" y="-186" width="42" height="186" rx="5" fill="#3b82f6" stroke="#0b1220" stroke-width="4"/>'
    lean += '<rect x="6" y="-168" width="30" height="22" rx="3" fill="#f8fafc" opacity=".9"/>'
    body += f'<g transform="translate(368 300) rotate(16)">{lean}</g>'
    body += f'<g filter="url(#sh)"><rect x="64" y="298" width="384" height="20" rx="4" fill="url(#clw)" stroke="{ink}" stroke-width="4"/></g>'
    body += fit(text("COLLECTION", "Archivo Black", 100, fill="#f8fafc", ls=6), 72, 350, 368, 68)
    body += '<rect x="196" y="434" width="120" height="6" rx="3" fill="#f59e0b"/>'
    return svg(body, d)


def logos() -> list[Logo]:
    return [Logo(lid, name, cat, fn, tags) for lid, name, cat, tags, fn in LOGOS]
