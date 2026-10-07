"""Holiday and seasonal logos: programming blocks and seasonal stations for
Christmas, New Year's, Easter, Thanksgiving, summer, winter, Halloween and
Valentine's Day. Invented brands throughout: no real channel's or block's
name, mark or lettering, and no famous characters."""

from __future__ import annotations

import math
import random
import re

import layouts as L
import symbols as S
from kit import (
    Logo,
    arc_text,
    banner,
    extrude,
    fit,
    glow,
    lin,
    measure,
    rad,
    rough,
    shadow,
    star,
    svg,
    text,
    tilt,
)
from symbols import P, centred

SH = shadow("sh", dy=6, blur=6, opacity=0.45)
SEASONS = "Holidays & seasons"
SEASON_LOGOS: list[tuple[str, str, str, list[str], object]] = []  # (id, name, category, tags, draw)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", "and")).strip("-")


def net(name: str, category: str, *tags: str):
    def add(fn):
        SEASON_LOGOS.append((slug(name), name, category, list(tags), fn))
        return fn

    return add


# ======================================================================= helpers


def _panel(x, y, w, h, fill, rx=18, edge=None, sw=0):
    st = f' stroke="{edge}" stroke-width="{sw}"' if edge else ""
    return f'<g filter="url(#sh)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{st}/></g>'


def _w(s, font, fill, edge=None, sw=0, weight=400, ls=0, style="normal"):
    """A word at size 100, to be fitted."""
    return text(s, font, 100, weight=weight, fill=fill, stroke=edge, sw=sw, ls=ls, style=style)


def _ex(t, dx, dy, color, steps=8):
    """A word with a solid block extrusion behind it."""
    return extrude(t, dx, dy, steps, color) + t


def _sh(inner):
    return f'<g filter="url(#sh)">{inner}</g>'


def _o(p, w=6):
    return f'stroke="{p.k}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"'


def _pix(rows, x, y, s, fill):
    """Pixel art (knitting, LED): '#' cells of size s from x,y."""
    out = ""
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == "#":
                out += f'<rect x="{x + i * s:.1f}" y="{y + j * s:.1f}" width="{s}" height="{s}" fill="{fill}"/>'
    return out


def _tongue(cx, by, w, h, lean=0.0):
    """One tongue of flame, its base centred at cx,by."""
    return (
        f"M{cx - w / 2:.1f} {by} C{cx - w / 2:.1f} {by - h * 0.5:.1f} {cx + lean - w * 0.2:.1f} {by - h * 0.62:.1f} {cx + lean:.1f} {by - h:.1f} "
        f"C{cx + lean + w * 0.12:.1f} {by - h * 0.55:.1f} {cx + w / 2:.1f} {by - h * 0.42:.1f} {cx + w / 2:.1f} {by} Z"
    )


def _holly(x, y, s=1.0, rot=0, leaf="#1f8a46", dark="#0b3d20", berry="#d62331"):
    """A holly sprig (two leaves, three berries) centred at x,y."""
    lf = "M0 0 Q10 -8 18 -4 Q22 -14 32 -12 Q34 -22 46 -20 Q48 -30 60 -26 Q54 -10 58 0 Q48 4 46 12 Q36 8 30 16 Q22 10 14 16 Q10 6 0 0 Z"
    g = f'<path d="{lf}" fill="{leaf}" stroke="{dark}" stroke-width="3" stroke-linejoin="round" transform="rotate(-24)"/>'
    g += f'<path d="{lf}" fill="{leaf}" stroke="{dark}" stroke-width="3" stroke-linejoin="round" transform="scale(-1 1) rotate(-24)"/>'
    g += f'<path d="M0 -2 Q2 -24 0 -28" stroke="{dark}" stroke-width="2" fill="none" transform="rotate(-24)" opacity=".5"/>'
    for bx, by in ((-7, 4), (7, 4), (0, -6)):
        g += f'<circle cx="{bx}" cy="{by}" r="8" fill="{berry}" stroke="{dark}" stroke-width="2.5"/><circle cx="{bx - 2.5}" cy="{by - 2.5}" r="2.4" fill="#fff" opacity=".7"/>'
    return f'<g transform="translate({x} {y}) rotate({rot}) scale({s})">{g}</g>'


def _scallop(cx, cy, r, n, bump, fill, edge=None, sw=0):
    """A circle with a scalloped (doily, bottle-cap) edge."""
    d = ""
    for k in range(n):
        a0 = math.radians(k * 360 / n)
        a1 = math.radians((k + 1) * 360 / n)
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        d += (f"M{x0:.1f} {y0:.1f} " if k == 0 else "") + f"A{bump} {bump} 0 0 1 {x1:.1f} {y1:.1f} "
    st = f' stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"' if edge else ""
    return f'<path d="{d}Z" fill="{fill}"{st}/>'


# ======================================================================= drawings (200x200)


def sleigh_bell(p: P) -> str:
    """A round sleigh bell on its loop."""
    s = f'<rect x="88" y="14" width="24" height="26" rx="6" fill="{p.b}" {_o(p, 5)}/>'
    s += f'<circle cx="100" cy="110" r="78" fill="{p.a}" {_o(p, 6)}/>'
    s += f'<path d="M34 96 Q100 70 166 96" fill="none" stroke="{p.k}" stroke-width="4" opacity=".35"/>'
    s += f'<path d="M44 132 L156 132" stroke="{p.k}" stroke-width="14" stroke-linecap="round"/>'
    s += f'<circle cx="44" cy="132" r="12" fill="{p.k}"/><circle cx="156" cy="132" r="12" fill="{p.k}"/>'
    s += f'<circle cx="100" cy="164" r="8" fill="{p.k}"/>'
    s += f'<ellipse cx="72" cy="72" rx="22" ry="14" fill="{p.l}" opacity=".55" transform="rotate(-30 72 72)"/>'
    return s


def mistletoe(p: P) -> str:
    """A sprig of mistletoe hanging from a bow."""
    s = ""
    stems = (
        (100, 40, 60, 120),
        (100, 40, 140, 118),
        (100, 40, 100, 150),
        (80, 84, 40, 104),
        (120, 84, 162, 100),
    )
    for x1, y1, x2, y2 in stems:
        s += f'<path d="M{x1} {y1} Q{(x1 + x2) / 2 + 6} {(y1 + y2) / 2} {x2} {y2}" fill="none" stroke="{p.b}" stroke-width="6" stroke-linecap="round"/>'
    leaves = (
        (60, 120, 210),
        (60, 120, 280),
        (140, 118, -30),
        (140, 118, 250),
        (100, 150, 240),
        (100, 150, 300),
        (40, 104, 170),
        (40, 104, 220),
        (162, 100, 10),
        (162, 100, -40),
    )
    for x, y, a in leaves:
        s += f'<ellipse cx="{x + 26}" cy="{y}" rx="28" ry="11" fill="{p.a}" {_o(p, 4)} transform="rotate({a} {x} {y})"/>'
    for x, y in ((58, 118), (68, 112), (138, 116), (148, 110), (98, 150), (106, 144), (92, 142)):
        s += f'<circle cx="{x}" cy="{y}" r="8" fill="{p.l}" {_o(p, 3)}/><circle cx="{x - 2}" cy="{y - 2}" r="2" fill="#fff"/>'
    # the bow
    s += f'<path d="M100 40 L62 18 Q54 40 62 58 Z" fill="{p.c}" {_o(p, 4)}/><path d="M100 40 L138 18 Q146 40 138 58 Z" fill="{p.c}" {_o(p, 4)}/>'
    s += f'<path d="M96 44 L84 80 L94 76 L98 86 L104 46 Z" fill="{p.c}" {_o(p, 3)}/><path d="M104 44 L116 80 L106 76 L102 86 L96 46 Z" fill="{p.c}" {_o(p, 3)}/>'
    s += f'<circle cx="100" cy="40" r="9" fill="{p.c}" {_o(p, 4)}/>'
    return s


def gift(p: P, bow: str | None = None) -> str:
    """A wrapped present with a ribbon and bow."""
    bw = bow or p.b
    s = f'<rect x="24" y="84" width="152" height="108" rx="6" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="14" y="60" width="172" height="34" rx="6" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="88" y="60" width="24" height="132" fill="{bw}" {_o(p, 4)}/>'
    s += f'<rect x="14" y="68" width="172" height="0" {_o(p, 4)}/>'
    s += f'<path d="M100 60 Q60 10 50 40 Q44 62 100 60 Z" fill="{bw}" {_o(p, 5)}/><path d="M100 60 Q140 10 150 40 Q156 62 100 60 Z" fill="{bw}" {_o(p, 5)}/>'
    s += f'<circle cx="100" cy="58" r="10" fill="{bw}" {_o(p, 4)}/>'
    s += '<rect x="30" y="98" width="40" height="8" rx="4" fill="#fff" opacity=".25"/>'
    return s


# ======================================================================= Christmas


@net("Yule Log", SEASONS, "christmas", "holiday", "fireplace", "ambient")
def yule_log():
    d = (
        SH
        + rad(
            "gl",
            [(0, "#ffb347"), (0.3, "#d9480f"), (0.7, "#3b1106"), (1, "#1a0804")],
            cx=0.5,
            cy=0.46,
            r=0.62,
        )
        + lin("bark", [(0, "#9a6a3e"), (0.45, "#6b4222"), (1, "#3a220f")])
        + rad("ring", [(0, "#f6e2b3"), (0.75, "#dcb97e"), (1, "#a8773f")])
        + glow("fg", "#ffb020", blur=12, strength=2)
        + lin("gold", [(0, "#fff0c4"), (0.5, "#f2c14e"), (1, "#b07a1e")])
    )
    body = _panel(28, 36, 456, 440, "url(#gl)", rx=44, edge="#140603", sw=8)
    body += '<rect x="44" y="52" width="424" height="408" rx="32" fill="none" stroke="url(#gold)" stroke-width="3" opacity=".8"/>'
    fl = ""
    for layer, (col, k) in enumerate((("#e8590c", 1.0), ("#ff9f1c", 0.74), ("#ffe066", 0.46))):
        for cx, w, h, lean in (
            (178, 104, 150, -18),
            (256, 140, 214, 4),
            (336, 104, 160, 20),
            (216, 80, 120, -8),
            (298, 80, 128, 10),
        ):
            fl += f'<path d="{_tongue(cx, 262, w * k, h * k, lean * k)}" fill="{col}"/>'
        if layer == 0:
            fl = f'<g filter="url(#fg)">{fl}</g>'
    body += fl
    for x, y, r in (
        (150, 96, 4),
        (372, 112, 3),
        (210, 70, 3),
        (318, 64, 4),
        (262, 44, 2.5),
        (120, 150, 3),
    ):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#ffd166"/>'
    # the log
    body += '<g filter="url(#sh)">'
    body += '<rect x="92" y="236" width="316" height="86" rx="43" fill="url(#bark)" stroke="#1e0e05" stroke-width="7"/>'
    for y, x0, x1 in ((258, 120, 300), (280, 150, 360), (302, 110, 250)):
        body += f'<path d="M{x0} {y} Q{(x0 + x1) / 2} {y - 6} {x1} {y}" fill="none" stroke="#2a1608" stroke-width="4" stroke-linecap="round" opacity=".55"/>'
    body += '<ellipse cx="404" cy="279" rx="34" ry="43" fill="url(#ring)" stroke="#1e0e05" stroke-width="7"/>'
    for rx, ry in ((24, 31), (15, 20), (6, 8)):
        body += f'<ellipse cx="404" cy="279" rx="{rx}" ry="{ry}" fill="none" stroke="#a0692e" stroke-width="3"/>'
    body += "</g>"
    body += _holly(150, 240, 1.25, -10)
    body += f'<g filter="url(#sh)">{fit(_ex(_w("YULE LOG", "Bevan", "#fff1d6", "#140603", 12, ls=4), 0, 6, "#140603", 6), 62, 338, 388, 80)}</g>'
    body += fit(
        text("THE FIREPLACE CHANNEL", "Oswald", 40, weight=700, fill="#f2c14e", ls=7),
        128,
        424,
        256,
        24,
    )
    return svg(body, d)


@net("Ugly Sweater", SEASONS, "christmas", "holiday", "comedy", "specials")
def ugly_sweater():
    edge = "#2a0a0e"
    sweater = (
        "M190 44 Q256 84 322 44 L420 78 Q452 90 462 126 L500 334 L436 350 L402 196 L402 392 "
        "L110 392 L110 196 L76 350 L12 334 L50 126 Q60 90 92 78 Z"
    )
    d = (
        SH
        + lin("knit", [(0, "#23a055"), (1, "#136b35")])
        + f"<clipPath id='sw'><path d='{sweater}'/></clipPath>"
        + "<pattern id='st' width='12' height='12' patternUnits='userSpaceOnUse'><path d='M1 2 L6 10 L11 2' fill='none' stroke='#000' stroke-width='1.6' opacity='.22'/></pattern>"
    )
    body = f'<g filter="url(#sh)"><path d="{sweater}" fill="url(#knit)" stroke="{edge}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += '<g clip-path="url(#sw)">'
    body += '<rect x="0" y="96" width="512" height="56" fill="#d62331"/>'
    body += '<rect x="0" y="92" width="512" height="6" fill="#fff6e6"/><rect x="0" y="150" width="512" height="6" fill="#fff6e6"/>'
    tree = ["..#..", ".###.", "#####", "..#.."]
    flake = ["#.#.#", ".###.", "##.##", ".###.", "#.#.#"]
    for i, x in enumerate(range(8, 512, 50)):
        body += _pix(flake if i % 2 else tree, x, 104 if i % 2 else 108, 8, "#fff6e6")
    for x in range(0, 512, 20):
        body += f'<rect x="{x}" y="166" width="10" height="10" fill="#ffd23f"/><rect x="{x + 10}" y="176" width="10" height="10" fill="#ffd23f"/>'
    body += '<rect x="0" y="330" width="512" height="10" fill="#fff6e6"/>'
    for x in range(0, 512, 20):
        body += f'<rect x="{x}" y="344" width="10" height="10" fill="#d62331"/><rect x="{x + 10}" y="354" width="10" height="10" fill="#d62331"/>'
    body += '<rect width="512" height="512" fill="url(#st)"/></g>'
    # collar, cuffs and hem: ribbing
    body += f'<path d="M184 40 Q256 90 328 40 Q256 110 184 40 Z" fill="#b51c28" stroke="{edge}" stroke-width="6" stroke-linejoin="round"/>'
    for cuff in ("M14 334 L76 348 L70 384 L6 370 Z", "M498 334 L436 348 L442 384 L506 370 Z"):
        body += f'<path d="{cuff}" fill="#b51c28" stroke="{edge}" stroke-width="6" stroke-linejoin="round"/>'
    body += f'<rect x="106" y="384" width="300" height="40" rx="6" fill="#b51c28" stroke="{edge}" stroke-width="6"/>'
    for x in range(120, 400, 12):
        body += f'<line x1="{x}" y1="390" x2="{x}" y2="418" stroke="{edge}" stroke-width="2" opacity=".35"/>'
    # a pom-pom and bells sewn on
    body += '<circle cx="256" cy="316" r="0"/>'
    body += f'<g filter="url(#sh)">{fit(_w("UGLY", "Press Start 2P", "#fff6e6", edge, 10), 136, 196, 240, 110)}</g>'
    body += banner(22, 490, 412, 76, "#ffd23f", edge, 6, cut=22)
    body += fit(_w("SWEATER", "Press Start 2P", "#b51c28"), 70, 428, 372, 46)
    return svg(body, d)


@net("Eggnog", SEASONS, "christmas", "holiday", "classic tv", "specials")
def eggnog():
    edge = "#10261a"
    d = (
        SH
        + rad("g", [(0, "#1f7a4d"), (1, "#0b3d26")], r=0.6)
        + lin("nog", [(0, "#fff6da"), (1, "#f0cf86")])
        + lin("gl", [(0, "#ffffff"), (1, "#d7eef5")], x2=1, y2=0)
    )
    body = _sh(_scallop(256, 250, 226, 30, 26, "#fff4dc", edge, 6))
    body += f'<circle cx="256" cy="250" r="200" fill="url(#g)" stroke="{edge}" stroke-width="5"/>'
    body += '<circle cx="256" cy="250" r="188" fill="none" stroke="#fff4dc" stroke-width="3" stroke-dasharray="2 10" stroke-linecap="round"/>'
    # the mug
    m = '<g filter="url(#sh)">'
    m += f'<path d="M306 110 Q362 110 360 160 Q358 212 306 212" fill="none" stroke="{edge}" stroke-width="30" stroke-linecap="round"/>'
    m += '<path d="M306 110 Q362 110 360 160 Q358 212 306 212" fill="none" stroke="#e9f6fa" stroke-width="18" stroke-linecap="round"/>'
    m += f'<path d="M184 84 L328 84 L318 238 Q316 256 298 256 L214 256 Q196 256 194 238 Z" fill="url(#gl)" stroke="{edge}" stroke-width="7" stroke-linejoin="round"/>'
    m += '<path d="M194 104 L318 104 L310 232 Q308 244 296 244 L216 244 Q204 244 202 232 Z" fill="url(#nog)"/>'
    m += '<rect x="206" y="112" width="14" height="118" rx="7" fill="#fff" opacity=".7"/>'
    m += f'<path d="M184 84 Q200 52 232 62 Q244 36 272 50 Q300 40 312 66 Q336 64 328 84 Z" fill="#fffaf0" stroke="{edge}" stroke-width="6" stroke-linejoin="round"/>'
    m += f'<g transform="rotate(18 290 50)"><rect x="280" y="4" width="22" height="92" rx="6" fill="#9a4a1a" stroke="{edge}" stroke-width="5"/><path d="M286 12 L286 88 M296 12 L296 88" stroke="#5a2a0c" stroke-width="2"/></g>'
    for x, y in ((226, 68), (250, 58), (268, 70), (292, 62), (240, 78), (306, 76)):
        m += f'<circle cx="{x}" cy="{y}" r="3" fill="#8a4a1a"/>'
    m += "</g>"
    body += m
    body += f'<g filter="url(#sh)">{fit(tilt(_ex(_w("Eggnog", "Lobster", "#fff4dc", edge, 14), 0, 7, "#b51c28", 7), -6), 78, 262, 356, 124)}</g>'
    body += fit(
        text("HOLIDAY CLASSICS", "Oswald", 40, weight=700, fill="#ffd166", ls=8), 160, 398, 192, 24
    )
    return svg(body, d)


@net("Candy Cane Lane", SEASONS, "christmas", "holiday", "family", "kids")
def candy_cane_lane():
    edge = "#0c2217"
    d = SH + lin("blade", [(0, "#12804a"), (1, "#0a5a33")])
    cane = "M256 486 L256 118 A62 62 0 0 1 380 118 L380 150"
    body = '<g filter="url(#sh)">'
    body += '<ellipse cx="256" cy="478" rx="150" ry="22" fill="#eef6ff" stroke="#9fb8cc" stroke-width="3"/>'
    body += (
        f'<path d="{cane}" fill="none" stroke="{edge}" stroke-width="48" stroke-linecap="round"/>'
    )
    body += (
        f'<path d="{cane}" fill="none" stroke="#fffaf2" stroke-width="36" stroke-linecap="round"/>'
    )
    body += f'<path d="{cane}" fill="none" stroke="#e02631" stroke-width="36" stroke-dasharray="16 20"/>'
    body += "</g>"
    body += f'<path d="{cane}" fill="none" stroke="#fff" stroke-width="6" opacity=".35" transform="translate(-9 0)"/>'
    for x, y, w, h in ((30, 184, 452, 104), (118, 302, 276, 88)):
        body += f'<g filter="url(#sh)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="url(#blade)" stroke="{edge}" stroke-width="6"/></g>'
        body += f'<rect x="{x + 9}" y="{y + 9}" width="{w - 18}" height="{h - 18}" rx="8" fill="none" stroke="#fff" stroke-width="4"/>'
        body += f'<path d="M{x + 4} {y + 4} Q{x + w * 0.25} {y - 18} {x + w * 0.5} {y - 6} Q{x + w * 0.75} {y - 20} {x + w - 4} {y + 4} Z" fill="#fff" stroke="#9fb8cc" stroke-width="2"/>'
        body += f'<circle cx="{x + 24}" cy="{y + h / 2}" r="5" fill="#cfd8dc" stroke="{edge}" stroke-width="2"/><circle cx="{x + w - 24}" cy="{y + h / 2}" r="5" fill="#cfd8dc" stroke="{edge}" stroke-width="2"/>'
    body += fit(_w("CANDY CANE", "Barlow Condensed", "#fff", weight=700, ls=3), 66, 202, 380, 68)
    body += fit(_w("LANE", "Barlow Condensed", "#fff", weight=700, ls=10), 156, 318, 200, 56)
    return svg(body, d)


@net("North Pole Network", SEASONS, "christmas", "holiday", "family", "movies")
def north_pole_network():
    edge = "#08142e"
    d = (
        SH
        + lin("sky", [(0, "#0b1d51"), (0.7, "#1d4e89"), (1, "#3b7dc4")])
        + lin("gold", [(0, "#fff3c2"), (0.5, "#e7bf5a"), (1, "#a87a1e")])
        + rad("ball", [(0, "#fff8d6"), (0.5, "#f2c14e"), (1, "#8a5a0e")], cx=0.35, cy=0.3, r=0.8)
        + "<clipPath id='disc'><circle cx='256' cy='182' r='150'/></clipPath>"
        + "<clipPath id='pole'><rect x='236' y='96' width='40' height='210' rx='6'/></clipPath>"
        + glow("aur", "#4dffc3", blur=10, strength=1)
    )
    body = f'<g filter="url(#sh)"><circle cx="256" cy="182" r="166" fill="url(#gold)" stroke="{edge}" stroke-width="7"/></g>'
    body += '<circle cx="256" cy="182" r="150" fill="url(#sky)"/>'
    body += '<g clip-path="url(#disc)">'
    body += '<g filter="url(#aur)" opacity=".85"><path d="M90 150 Q160 60 240 120 Q320 180 430 90" fill="none" stroke="#4dffc3" stroke-width="22" opacity=".55"/>'
    body += '<path d="M90 190 Q170 110 250 160 Q330 210 430 140" fill="none" stroke="#7df9ff" stroke-width="12" opacity=".5"/></g>'
    rng = random.Random(4)
    for _ in range(26):
        body += f'<circle cx="{rng.uniform(110, 400):.0f}" cy="{rng.uniform(50, 250):.0f}" r="{rng.uniform(1.2, 3):.1f}" fill="#fff"/>'
    body += (
        '<path d="M90 300 Q170 262 256 274 Q350 262 430 300 L430 360 L90 360 Z" fill="#f2f8ff"/>'
    )
    body += '<path d="M90 316 Q200 290 300 300 Q380 296 430 318" fill="none" stroke="#b8d4ec" stroke-width="4"/>'
    body += "</g>"
    body += '<circle cx="256" cy="182" r="150" fill="none" stroke="#fff" stroke-width="3" opacity=".35"/>'
    # the pole
    body += f'<g filter="url(#sh)"><rect x="232" y="92" width="48" height="216" rx="8" fill="{edge}"/></g>'
    body += '<g clip-path="url(#pole)"><rect x="236" y="96" width="40" height="210" fill="#fff"/>'
    for y in range(60, 320, 34):
        body += f'<polygon points="236,{y} 276,{y - 22} 276,{y - 4} 236,{y + 18}" fill="#e02631"/>'
    body += '<rect x="236" y="96" width="10" height="210" fill="#fff" opacity=".35"/><rect x="264" y="96" width="12" height="210" fill="#000" opacity=".15"/></g>'
    body += f'<circle cx="256" cy="76" r="26" fill="url(#ball)" stroke="{edge}" stroke-width="6"/>'
    body += (
        '<ellipse cx="256" cy="306" rx="54" ry="12" fill="#fff" stroke="#b8d4ec" stroke-width="3"/>'
    )
    body += f'<g filter="url(#sh)">{fit(_w("NORTH POLE", "Archivo Black", "#fff", edge, 12, ls=2), 30, 360, 452, 70)}</g>'
    body += '<line x1="96" y1="458" x2="172" y2="458" stroke="#e7bf5a" stroke-width="4"/><line x1="340" y1="458" x2="416" y2="458" stroke="#e7bf5a" stroke-width="4"/>'
    body += fit(
        text("NETWORK", "Archivo Black", 40, fill="#e7bf5a", ls=10, stroke=edge, sw=6),
        184,
        444,
        144,
        28,
    )
    return svg(body, d)


@net("Sleigh Bells", SEASONS, "christmas", "holiday", "music", "classic")
def sleigh_bells():
    edge = "#2a0508"
    d = (
        SH
        + lin("red", [(0, "#b3121f"), (1, "#5c0810")])
        + lin("gold", [(0, "#fff3c2"), (0.45, "#e7bf5a"), (1, "#9c6a14")])
        + lin("strap", [(0, "#8a4a22"), (1, "#5a2c10")])
    )
    body = _panel(30, 60, 452, 392, "url(#red)", rx=36, edge=edge, sw=8)
    body += '<rect x="46" y="76" width="420" height="360" rx="24" fill="none" stroke="url(#gold)" stroke-width="4"/>'
    body += '<rect x="56" y="86" width="400" height="340" rx="18" fill="none" stroke="url(#gold)" stroke-width="1.5"/>'
    strap = "M40 118 Q256 196 472 118"
    body += (
        f'<path d="{strap}" fill="none" stroke="{edge}" stroke-width="40" stroke-linecap="round"/>'
    )
    body += f'<path d="{strap}" fill="none" stroke="url(#strap)" stroke-width="30" stroke-linecap="round"/>'
    body += f'<path d="{strap}" fill="none" stroke="#f2d49b" stroke-width="2.5" stroke-dasharray="8 7" transform="translate(0 -8)"/>'
    body += f'<path d="{strap}" fill="none" stroke="#f2d49b" stroke-width="2.5" stroke-dasharray="8 7" transform="translate(0 8)"/>'
    bell = sleigh_bell(P(a="url(#gold)", b="#d9a93a", k=edge, l="#fff"))
    for x, y, s in ((130, 204, 96), (256, 226, 116), (382, 204, 96)):
        body += _sh(centred(bell, x, y, s))
    body += _holly(256, 150, 1.1)
    body += f'<g filter="url(#sh)">{fit(_w("SLEIGH BELLS", "Cinzel", "url(#gold)", edge, 10, weight=900, ls=4), 66, 290, 380, 74)}</g>'
    body += fit(
        text("SONGS OF THE SEASON", "Cinzel", 40, weight=700, fill="#f7e3b0", ls=6),
        136,
        378,
        240,
        24,
    )
    return svg(body, d)


@net("Mistletoe Movies", SEASONS, "christmas", "holiday", "movies", "romance")
def mistletoe_movies():
    edge = "#04150d"
    d = (
        SH
        + lin("g", [(0, "#135c3c"), (1, "#062a1a")])
        + lin("gold", [(0, "#fff3c2"), (0.5, "#e7bf5a"), (1, "#a87a1e")])
        + rad("halo", [(0, "#fff6d6"), (1, "#fff6d600")], r=0.5)
    )
    body = _panel(34, 34, 444, 444, "url(#g)", rx=40, edge=edge, sw=8)
    body += '<rect x="50" y="50" width="412" height="412" rx="28" fill="none" stroke="url(#gold)" stroke-width="3"/>'
    body += '<ellipse cx="256" cy="130" rx="150" ry="100" fill="url(#halo)" opacity=".35"/>'
    body += '<line x1="256" y1="50" x2="256" y2="82" stroke="#e7bf5a" stroke-width="4"/>'
    body += _sh(
        centred(
            mistletoe(P(a="#8fd694", b="#5a8a3a", c="#e02631", k=edge, l="#fbfbf2")), 256, 142, 196
        )
    )
    body += f'<g filter="url(#sh)">{fit(tilt(_w("Mistletoe", "Yellowtail", "#fff4e6", edge, 12), -5), 64, 214, 384, 124)}</g>'
    body += '<rect x="34" y="350" width="444" height="78" fill="#120a0c"/>'
    for x in range(50, 470, 30):
        body += f'<rect x="{x}" y="358" width="16" height="10" rx="2" fill="#f2ead8"/><rect x="{x}" y="410" width="16" height="10" rx="2" fill="#f2ead8"/>'
    body += fit(
        _w("MOVIES", "Playfair Display", "url(#gold)", weight=900, ls=18), 150, 372, 212, 36
    )
    return svg(body, d)


@net("Jingle", SEASONS, "christmas", "holiday", "music", "kids")
def jingle():
    edge = "#3a0508"
    d = (
        SH
        + lin("red", [(0, "#ef3b46"), (1, "#a4161a")])
        + rad("gold", [(0, "#fff6c9"), (0.45, "#f7c948"), (1, "#a8700e")], cx=0.38, cy=0.32, r=0.75)
    )
    body = _panel(36, 36, 440, 440, "url(#red)", rx=110, edge=edge, sw=8)
    for x, y, s in (
        (96, 104, 34),
        (420, 120, 26),
        (84, 300, 22),
        (428, 300, 30),
        (140, 60, 18),
        (380, 64, 16),
    ):
        body += centred(S.snowflake(P(l="#ffffff")), x, y, s).replace(
            "<g stroke", '<g opacity=".45" stroke'
        )
    for k, r in enumerate((104, 126)):
        for side in (-1, 1):
            a0, a1 = (-40, 40) if side == 1 else (140, 220)
            x0 = 256 + r * math.cos(math.radians(a0))
            y0 = 168 + r * math.sin(math.radians(a0))
            x1 = 256 + r * math.cos(math.radians(a1))
            y1 = 168 + r * math.sin(math.radians(a1))
            body += f'<path d="M{x0:.1f} {y0:.1f} A{r} {r} 0 0 1 {x1:.1f} {y1:.1f}" fill="none" stroke="#ffd23f" stroke-width="{8 - k * 2}" stroke-linecap="round" opacity="{0.9 - k * 0.3}"/>'
    bell = sleigh_bell(P(a="url(#gold)", b="#e7bf5a", k=edge, l="#fff"))
    body += _sh(f'<g transform="rotate(-10 256 168)">{centred(bell, 256, 162, 176)}</g>')
    body += f'<path d="M256 60 Q236 40 220 52 Q214 70 248 66 Z M256 60 Q276 40 292 52 Q298 70 264 66 Z" fill="#1f8a46" stroke="{edge}" stroke-width="4" stroke-linejoin="round" transform="rotate(-10 256 168)"/>'
    w = _w("JINGLE", "Titan One", "#fff", edge, 14, ls=2)
    body += f'<g filter="url(#sh)">{fit(tilt(_ex(w, 3, 9, edge, 8), -4), 56, 282, 400, 128)}</g>'
    return svg(body, d)


@net("Stocking Stuffers", SEASONS, "christmas", "holiday", "cartoons", "shorts", "kids")
def stocking_stuffers():
    edge = "#2a0508"
    stocking = (
        "M196 124 L336 124 L336 214 Q336 262 300 272 L222 280 Q176 284 172 250 Q170 226 196 216 Z"
    )
    d = (
        SH
        + lin("g", [(0, "#16733a"), (1, "#0b3d20")])
        + lin("sk", [(0, "#e8343f"), (1, "#a4161a")])
    )
    body = _panel(36, 70, 440, 400, "url(#g)", rx=40, edge="#062014", sw=8)
    rng = random.Random(3)
    for _ in range(22):
        x, y = rng.uniform(60, 450), rng.uniform(90, 450)
        body += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rng.uniform(2, 4.5):.1f}" fill="#fff" opacity=".35"/>'
    # peeking out of the top: a candy cane, a present, a star wand
    st = ""
    st += '<path d="M300 132 L300 60 A18 18 0 0 0 264 60" fill="none" stroke="#2a0508" stroke-width="20" stroke-linecap="round"/>'
    st += '<path d="M300 132 L300 60 A18 18 0 0 0 264 60" fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round"/>'
    st += '<path d="M300 132 L300 60 A18 18 0 0 0 264 60" fill="none" stroke="#e02631" stroke-width="12" stroke-dasharray="7 7"/>'
    st += centred(gift(P(a="#3aa0e8", b="#ffd23f", k=edge)), 238, 96, 84)
    st += f'<line x1="214" y1="130" x2="196" y2="54" stroke="{edge}" stroke-width="10" stroke-linecap="round"/><line x1="214" y1="130" x2="196" y2="54" stroke="#ffd23f" stroke-width="5" stroke-linecap="round"/>'
    st += f'<polygon points="{star(194, 44, 22, 10)}" fill="#ffd23f" stroke="{edge}" stroke-width="4" stroke-linejoin="round"/>'
    st += f'<path d="{stocking}" fill="url(#sk)" stroke="{edge}" stroke-width="7" stroke-linejoin="round"/>'
    st += f'<path d="M336 214 Q336 262 300 272 L286 274 Q300 244 300 214 Z" fill="#fff6e6" stroke="{edge}" stroke-width="5" stroke-linejoin="round"/>'
    st += f'<path d="M222 280 Q176 284 172 250 Q170 226 196 216 L200 244 Q206 266 222 280 Z" fill="#fff6e6" stroke="{edge}" stroke-width="5" stroke-linejoin="round"/>'
    for x, y in ((224, 170), (262, 190), (300, 164), (240, 222), (310, 214)):
        st += f'<polygon points="{star(x, y, 9, 4)}" fill="#fff6e6" opacity=".85"/>'
    st += f'<rect x="184" y="108" width="164" height="44" rx="22" fill="#fffaf2" stroke="{edge}" stroke-width="7"/>'
    for x in range(200, 340, 16):
        st += f'<circle cx="{x}" cy="{130 + (6 if x % 32 else -6)}" r="5" fill="#e8e0d4"/>'
    body += _sh(st)
    top = _w("STOCKING", "Luckiest Guy", "#fff", edge, 14, ls=2)
    bot = _w("STUFFERS", "Luckiest Guy", "#ffd23f", edge, 14, ls=2)
    body += f'<g filter="url(#sh)">{fit(_ex(top, 3, 7, edge, 6), 60, 292, 392, 80)}</g>'
    body += f'<g filter="url(#sh)">{fit(_ex(bot, 3, 7, edge, 6), 60, 376, 392, 80)}</g>'
    return svg(body, d)


@net("Christmas Eve", SEASONS, "christmas", "holiday", "movies", "family")
def christmas_eve():
    edge = "#050b1f"
    d = (
        SH
        + lin("sky", [(0, "#0a1440"), (0.6, "#1c2f7a"), (1, "#34489e")])
        + rad("moon", [(0, "#fffbe6"), (0.8, "#ffe9a8"), (1, "#f5cf6a")], r=0.55)
        + glow("mg", "#fff1b8", blur=16, strength=2)
        + "<clipPath id='pc'><rect x='34' y='34' width='444' height='444' rx='40'/></clipPath>"
    )
    body = _panel(34, 34, 444, 444, "url(#sky)", rx=40, edge=edge, sw=8)
    body += '<g clip-path="url(#pc)">'
    rng = random.Random(11)
    for _ in range(40):
        body += f'<circle cx="{rng.uniform(40, 470):.0f}" cy="{rng.uniform(40, 280):.0f}" r="{rng.uniform(1, 2.6):.1f}" fill="#fff" opacity="{rng.uniform(0.5, 1):.2f}"/>'
    body += '<g filter="url(#mg)"><circle cx="300" cy="170" r="112" fill="url(#moon)"/></g>'
    body += '<circle cx="262" cy="140" r="14" fill="#f0d88a" opacity=".5"/><circle cx="330" cy="206" r="20" fill="#f0d88a" opacity=".45"/><circle cx="340" cy="120" r="9" fill="#f0d88a" opacity=".5"/>'
    # the sleigh and team in the sky beside the moon
    sil = "#e0e7ff"
    team = ""
    for x, y in ((292, 180), (328, 168), (364, 156)):
        team += (
            f'<g transform="translate({x} {y}) rotate(-14)"><ellipse cx="0" cy="0" rx="17" ry="7" fill="{sil}"/>'
            f'<path d="M12 -2 L20 -14 L27 -13 L22 -6 Z" fill="{sil}"/>'
            f'<path d="M20 -14 L18 -24 M21 -18 L26 -24 M22 -14 L30 -20" stroke="{sil}" stroke-width="2.4" fill="none" stroke-linecap="round"/>'
            f'<path d="M10 4 L22 10 M6 4 L16 12 M-10 4 L-22 10 M-14 2 L-26 4" stroke="{sil}" stroke-width="3" stroke-linecap="round"/></g>'
        )
    body += '<g transform="translate(-100 -30) scale(.75)">' + team
    body += '<path d="M274 184 L256 190" stroke="#e0e7ff" stroke-width="2"/>'
    body += f'<g transform="translate(232 206) rotate(-14)"><path d="M-30 0 Q-30 -18 -14 -18 L22 -18 Q30 -26 34 -34 L38 -30 Q36 -14 26 0 Z" fill="{sil}"/>'
    body += f'<path d="M-36 8 L28 8 Q40 8 42 -2" fill="none" stroke="{sil}" stroke-width="3.5" stroke-linecap="round"/><path d="M-20 0 L-20 8 M16 0 L16 8" stroke="{sil}" stroke-width="3"/>'
    body += f'<circle cx="-6" cy="-24" r="9" fill="{sil}"/><path d="M-12 -30 L0 -44 L4 -30 Z" fill="{sil}"/><path d="M-20 -18 Q-26 -30 -14 -30 L8 -30 Q10 -18 8 -18 Z" fill="{sil}"/></g></g>'
    # rooftops with snow and lit windows
    roofs = "M34 318 L70 318 L70 290 L96 262 L122 290 L122 306 L150 306 L150 276 L186 244 L222 276 L222 312 L268 312 L268 296 L300 268 L332 296 L332 300 L372 300 L372 270 L408 238 L444 270 L444 310 L478 310 L478 478 L34 478 Z"
    body += f'<path d="{roofs}" fill="{edge}"/>'
    for path in (
        "M70 292 L96 264 L122 292 L116 294 L96 274 L76 294 Z",
        "M150 278 L186 246 L222 278 L214 280 L186 256 L158 280 Z",
        "M268 298 L300 270 L332 298 L324 300 L300 280 L276 300 Z",
        "M372 272 L408 240 L444 272 L436 274 L408 250 L380 274 Z",
    ):
        body += f'<path d="{path}" fill="#eef4ff"/>'
    body += '<rect x="194" y="226" width="14" height="30" fill="#050b1f"/><rect x="190" y="222" width="22" height="8" fill="#eef4ff"/>'
    for x, y in ((86, 300), (176, 290), (196, 290), (290, 312), (398, 284), (418, 284)):
        body += f'<rect x="{x}" y="{y}" width="12" height="14" fill="#ffd166"/>'
    body += "</g>"
    body += f'<g filter="url(#sh)">{fit(_w("Christmas Eve", "Playfair Display", "#fff6e0", edge, 10, weight=900, style="italic"), 62, 340, 388, 86)}</g>'
    body += fit(
        text("THE NIGHT BEFORE", "Playfair Display", 40, weight=700, fill="#f5cf6a", ls=8),
        156,
        432,
        200,
        22,
    )
    return svg(body, d)


@net("Fa La La", SEASONS, "christmas", "holiday", "music")
def fa_la_la():
    edge = "#0b0b10"
    d = (
        SH
        + rad("vin", [(0, "#2a2a33"), (0.6, "#15151c"), (1, "#0b0b10")])
        + rad("lab", [(0, "#e8343f"), (1, "#9c0f1a")])
    )
    body = f'<g filter="url(#sh)"><circle cx="256" cy="256" r="230" fill="url(#vin)" stroke="{edge}" stroke-width="4"/></g>'
    for r in range(120, 226, 7):
        body += f'<circle cx="256" cy="256" r="{r}" fill="none" stroke="#3a3a46" stroke-width="1.2" opacity=".7"/>'
    body += '<path d="M256 256 L120 60 A230 230 0 0 1 210 30 Z" fill="#fff" opacity=".07"/><path d="M256 256 L392 452 A230 230 0 0 1 302 482 Z" fill="#fff" opacity=".07"/>'
    body += f'<circle cx="256" cy="256" r="104" fill="url(#lab)" stroke="{edge}" stroke-width="4"/>'
    body += '<circle cx="256" cy="256" r="94" fill="none" stroke="#ffd23f" stroke-width="2.5"/>'
    t_defs, t_body = arc_text(
        "HOLIDAY HITS", "Oswald", 256, 256, 72, 20, weight=700, fill="#ffd23f", ls=5, pid="lt"
    )
    b_defs, b_body = arc_text(
        "33 1/3 · STEREO",
        "Oswald",
        256,
        256,
        74,
        16,
        weight=700,
        fill="#ffd23f",
        ls=4,
        bottom=True,
        pid="lb",
    )
    d += t_defs + b_defs
    body += t_body + b_body
    body += '<circle cx="256" cy="256" r="9" fill="#0b0b10"/>'
    for x, y, s, r in (
        (96, 110, 60, -14),
        (410, 104, 52, 12),
        (420, 388, 48, 10),
        (90, 392, 44, -8),
    ):
        body += f'<g transform="rotate({r} {x} {y})">{centred(S.notes(P(a="#ffd23f", k=edge)), x, y, s)}</g>'
    w = _w("Fa La La", "Shrikhand", "#fff6e6", edge, 14)
    body += (
        f'<g filter="url(#sh)">{fit(tilt(_ex(w, 3, 9, "#1f8a46", 8), -8), 40, 178, 432, 150)}</g>'
    )
    return svg(body, d)


XMAS = ("christmas", "holiday")


@net("Santa's Workshop", SEASONS, *XMAS, "kids", "family")
def santas_workshop():
    ink = "#3b1d0a"
    d = SH + lin("wsw", [(0, "#c08a4d"), (1, "#8b5a2b")])
    body = ""
    for x in (70, 442):
        body += f'<rect x="{x - 14}" y="120" width="28" height="350" fill="#fff" stroke="{ink}" stroke-width="5"/>'
        for y in range(130, 470, 36):
            body += f'<polygon points="{x - 14},{y} {x + 14},{y + 16} {x + 14},{y + 32} {x - 14},{y + 16}" fill="#dc2626"/>'
    body = _sh(body)
    body += _sh(
        f'<rect x="40" y="150" width="432" height="190" rx="18" fill="url(#wsw)" stroke="{ink}" stroke-width="8"/>'
    )
    body += '<path d="M40 168 Q40 140 70 140 L442 140 Q472 140 472 168 Q440 186 400 170 Q360 190 320 172 Q280 192 240 172 Q200 190 160 170 Q120 188 80 170 Q56 182 40 168 Z" fill="#fff"/>'
    body += fit(_w("SANTA'S", "Alfa Slab One", "#fff7e0", ink, 8), 90, 190, 332, 64)
    body += fit(_w("WORKSHOP", "Alfa Slab One", "#dc2626", ink, 8), 80, 262, 352, 60)
    body += _holly(256, 132, 1.0)
    return svg(body, d)


@net("Gingerbread", SEASONS, *XMAS, "kids", "baking")
def gingerbread():
    ink = "#3b1d0a"
    d = SH + lin("gb", [(0, "#c8823f"), (1, "#8b4f1d")])
    house = "M60 470 L60 230 L256 70 L452 230 L452 470 Z"
    body = _sh(
        f'<path d="{house}" fill="url(#gb)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += '<path d="M48 236 L256 60 L464 236" fill="none" stroke="#fff" stroke-width="22" stroke-linecap="round" stroke-linejoin="round"/>'
    for x in range(70, 450, 26):
        y = 236 - (196 - abs(x - 256)) * (166 / 196) if abs(x - 256) < 196 else 236
        body += f'<circle cx="{x}" cy="{y + 14:.0f}" r="7" fill="#fff"/>'
    for x, y, c in (
        (120, 290, "#ef4444"),
        (392, 290, "#22c55e"),
        (150, 430, "#facc15"),
        (362, 430, "#ec4899"),
    ):
        body += f'<circle cx="{x}" cy="{y}" r="12" fill="{c}" stroke="#fff" stroke-width="3"/>'
    body += _sh(
        f'<rect x="76" y="250" width="360" height="120" rx="14" fill="#fff7e0" stroke="{ink}" stroke-width="6"/>'
    )
    body += fit(_w("GINGERBREAD", "Lilita One", "#8b4f1d", ink, 6), 96, 270, 320, 80)
    body += '<path d="M226 470 L226 410 Q256 380 286 410 L286 470 Z" fill="#7c2d12" stroke="#fff" stroke-width="5"/>'
    return svg(body, d)


@net("Holiday Specials", SEASONS, *XMAS, "classic tv", "specials")
def holiday_specials():
    return L.tv_screen(
        "Holiday",
        "SPECIALS",
        "CLASSIC TV FOR THE SEASON",
        screen=("#1f8a46", "#0b3d20"),
        band="#d62331",
        cabinet="#fef3c7",
        edge="#2a1d14",
        ink="#fffbeb",
        script_font="Lobster",
        font="Archivo Black",
    )


@net("Twelve Days", SEASONS, *XMAS, "music", "specials")
def twelve_days():
    ink = "#0b3d20"
    d = SH + lin("tdg", [(0, "#fff3c4"), (0.5, "#e2b13c"), (1, "#a8741a")])
    ring = ""
    for k in range(24):
        a = math.radians(k * 15)
        ring += _holly(256 + 170 * math.cos(a), 220 + 170 * math.sin(a), 0.7, k * 15 + 90)
    body = _sh(ring)
    body += '<circle cx="256" cy="220" r="130" fill="#7f1d1d" stroke="url(#tdg)" stroke-width="7"/>'
    body += _sh(fit(_w("12", "Abril Fatface", "url(#tdg)", ink, 6), 186, 130, 140, 170))
    body += _sh(banner(36, 476, 370, 84, "#1f8a46", ink, 6, cut=22))
    body += fit(_w("TWELVE DAYS", "Abril Fatface", "#fff7e0", ink, 0, ls=4), 86, 384, 340, 56)
    return svg(body, d)


@net("Fruitcake", SEASONS, *XMAS, "comedy")
def fruitcake():
    ink = "#2b1408"
    d = SH + lin("fc", [(0, "#8b4f1d"), (1, "#4a2509")])
    body = _sh(
        f'<path d="M70 200 L360 160 L450 200 L450 380 L160 420 L70 380 Z" fill="url(#fc)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += f'<path d="M70 200 L360 160 L450 200 L160 240 Z" fill="#a0612b" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>'
    body += f'<path d="M160 240 L160 420" stroke="{ink}" stroke-width="5"/>'
    rng = random.Random(4)
    for _ in range(30):
        x = rng.uniform(170, 440)
        y = rng.uniform(250, 400) - (x - 160) * 0.12
        c = rng.choice(("#dc2626", "#16a34a", "#facc15", "#f97316"))
        body += f'<rect x="{x:.0f}" y="{y:.0f}" width="12" height="9" rx="2" fill="{c}" transform="rotate({rng.uniform(-30, 30):.0f} {x:.0f} {y:.0f})"/>'
    body += _sh(
        f'<path d="M40 270 L472 210 L472 290 L40 350 Z" fill="#dc2626" stroke="{ink}" stroke-width="6"/>'
    )
    body += f'<g transform="rotate(-8 256 280)">{fit(_w("FRUITCAKE", "Alfa Slab One", "#fff7e0", ink, 6), 80, 248, 352, 64)}</g>'
    return svg(body, d)


@net("Tacky Lights", SEASONS, *XMAS, "comedy", "family")
def tacky_lights():
    d = SH
    cols = ("#ef4444", "#22c55e", "#3b82f6", "#facc15", "#ec4899", "#f97316")
    for i, c in enumerate(cols):
        d += glow(f"tl{i}", c, blur=6, strength=2)
    body = _panel(30, 56, 452, 400, "#0b1026", rx=24, edge="#000", sw=5)
    for row, y0 in enumerate((96, 166, 380, 430)):
        body += f'<path d="M40 {y0} Q140 {y0 + 26} 256 {y0} T472 {y0}" fill="none" stroke="#1f2937" stroke-width="3"/>'
        for i in range(14):
            x = 50 + i * 30
            y = y0 + 12 * math.sin((x - 40) / 216 * math.pi) * (1 if row % 2 else -1) + 10
            k = (i + row) % 6
            body += f'<g filter="url(#tl{k})"><ellipse cx="{x}" cy="{y:.0f}" rx="7" ry="11" fill="{cols[k]}"/></g>'
    body += _sh(fit(_w("TACKY", "Bungee", "#fff", "#000", 8), 76, 196, 360, 96))
    body += _sh(fit(_w("LIGHTS", "Bungee", "#facc15", "#000", 8), 96, 296, 320, 70))
    return svg(body, d)


@net("Deck the Halls", SEASONS, *XMAS, "music", "family")
def deck_the_halls():
    d = (
        SH
        + lin("dth", [(0, "#7f1d1d"), (1, "#450a0a")])
        + lin("dtg", [(0, "#fff3c4"), (0.5, "#e2b13c"), (1, "#a8741a")])
    )
    body = _panel(36, 70, 440, 372, "url(#dth)", rx=20, edge="#1c0505", sw=6)
    swag = ""
    for k in range(17):
        t = k / 16
        x = 36 + 440 * t
        y = 96 + 50 * math.sin(t * math.pi * 2) ** 2
        swag += _holly(x, y, 0.8, k * 40)
    body += _sh(swag)
    body += _sh(
        fit(_w("Deck the Halls", "Great Vibes", "url(#dtg)", "#1c0505", 4), 66, 190, 380, 150)
    )
    body += fit(
        text("HOLIDAY FAVORITES", "Cinzel", 40, weight=700, fill="#fde68a", ls=8), 136, 360, 240, 26
    )
    return svg(body, d)


@net("Nutcracker", SEASONS, *XMAS, "ballet", "classic")
def nutcracker():
    ink = "#1c1917"
    d = (
        SH
        + lin("shako", [(0, "#dc2626"), (1, "#7f1d1d")])
        + lin("ng", [(0, "#fff3c4"), (0.5, "#e2b13c"), (1, "#a8741a")])
    )
    body = f'<path d="M232 76 Q214 30 256 18 Q298 30 280 76 Z" fill="#fff" stroke="{ink}" stroke-width="5"/>'
    body += _sh(
        f'<path d="M176 250 L184 80 Q256 64 328 80 L336 250 Z" fill="url(#shako)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += '<path d="M184 96 Q256 82 328 96" fill="none" stroke="url(#ng)" stroke-width="10"/>'
    body += '<path d="M196 150 Q256 196 316 150" fill="none" stroke="url(#ng)" stroke-width="6"/><path d="M196 176 Q256 222 316 176" fill="none" stroke="url(#ng)" stroke-width="6"/>'
    body += f'<polygon points="{star(256, 130, 26, 11)}" fill="url(#ng)" stroke="{ink}" stroke-width="3"/>'
    body += f'<path d="M150 252 Q256 236 362 252 Q370 278 340 286 Q256 270 172 286 Q142 278 150 252 Z" fill="#111" stroke="{ink}" stroke-width="5"/>'
    body += '<path d="M180 262 Q256 330 332 262" fill="none" stroke="url(#ng)" stroke-width="7"/>'
    body += _sh(banner(28, 484, 316, 96, "#1e3a8a", ink, 7, cut=26))
    body += fit(_w("NUTCRACKER", "Cinzel", "url(#ng)", ink, 0, weight=900, ls=4), 76, 332, 360, 62)
    body += fit(
        text("A HOLIDAY BALLET", "Cinzel", 40, weight=700, fill="#fde68a", ls=8), 156, 430, 200, 24
    )
    return svg(body, d)


@net("Christmas Morning", SEASONS, *XMAS, "family", "kids")
def christmas_morning():
    ink = "#1c1917"
    d = SH + lin("cmsky", [(0, "#fde68a"), (1, "#fecaca")])
    body = '<defs><clipPath id="cmc"><rect x="36" y="56" width="440" height="400" rx="24"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "url(#cmsky)", rx=24, edge=ink, sw=6)
    body += '<g clip-path="url(#cmc)">'
    for k in range(14):
        a1, a2 = math.radians(180 + k * 13), math.radians(186 + k * 13)
        body += f'<polygon points="256,300 {256 + 500 * math.cos(a1):.0f},{300 + 500 * math.sin(a1):.0f} {256 + 500 * math.cos(a2):.0f},{300 + 500 * math.sin(a2):.0f}" fill="#fff" opacity=".35"/>'
    body += "</g>"
    for x, y, sz, c, rb in (
        (150, 300, 120, "#dc2626", "#facc15"),
        (286, 270, 150, "#16a34a", "#fde68a"),
        (392, 330, 90, "#2563eb", "#f472b6"),
    ):
        body += _sh(centred(gift(P(a=c, b=rb, c=rb, k=ink, l="#fff")), x, y, sz))
    body += _sh(fit(_w("Christmas Morning", "Lobster", "#fff", ink, 10), 56, 372, 400, 76))
    return svg(body, d)


@net("Silent Night", SEASONS, *XMAS, "music", "classic")
def silent_night():
    d = (
        SH
        + lin("snsky", [(0, "#020617"), (1, "#1e3a8a")])
        + glow("sng", "#fef3c7", blur=12, strength=2)
    )
    body = '<defs><clipPath id="snc"><rect x="36" y="56" width="440" height="400" rx="24"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "url(#snsky)", rx=24, edge="#000", sw=5)
    body += '<g clip-path="url(#snc)">'
    rng = random.Random(3)
    for _ in range(36):
        body += f'<circle cx="{rng.uniform(40, 470):.0f}" cy="{rng.uniform(60, 300):.0f}" r="{rng.uniform(1, 2.2):.1f}" fill="#fff" opacity=".8"/>'
    body += '<path d="M36 360 Q160 300 280 350 T476 330 L476 456 L36 456 Z" fill="#e0e7ff"/><path d="M36 400 Q200 350 476 400 L476 456 L36 456 Z" fill="#f8fafc"/></g>'
    body += (
        f'<g filter="url(#sng)"><polygon points="{star(256, 130, 46, 10, 4)}" fill="#fef9c3"/></g>'
    )
    body += f'<polygon points="{star(256, 130, 30, 7, 4, rot=-45)}" fill="#fef9c3"/>'
    body += fit(
        text("Silent Night", "Playfair Display", 100, weight=700, style="italic", fill="#fef3c7"),
        76,
        210,
        360,
        90,
    )
    body += fit(
        text("ALL IS CALM", "Playfair Display", 40, weight=700, fill="#1e3a8a", ls=10),
        176,
        408,
        160,
        26,
    )
    return svg(body, d)


@net("Chestnuts", SEASONS, *XMAS, "classic", "cozy")
def chestnuts():
    ink = "#2b1408"
    d = SH + rad("nut", [(0, "#b45309"), (1, "#5b2a0a")], cx=0.4, cy=0.35)
    body = ""
    for x in (196, 256, 316):
        body += f'<path d="M{x} 150 q-14 -26 0 -52 t0 -52" fill="none" stroke="#d6d3d1" stroke-width="7" stroke-linecap="round" opacity=".7"/>'
    body += _sh(
        f'<path d="M110 200 L402 200 L300 470 L212 470 Z" fill="#fef3c7" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/>'
    )
    for i in range(4):
        body += f'<line x1="{140 + i * 70}" y1="200" x2="{232 + i * 16}" y2="470" stroke="#d6c08a" stroke-width="3"/>'
    for x, y in (
        (160, 196),
        (210, 176),
        (260, 190),
        (310, 172),
        (356, 196),
        (236, 214),
        (290, 218),
    ):
        body += f'<path d="M{x - 26} {y} Q{x - 26} {y - 30} {x} {y - 34} Q{x + 26} {y - 30} {x + 26} {y} Q{x} {y + 16} {x - 26} {y} Z" fill="url(#nut)" stroke="{ink}" stroke-width="4"/>'
        body += f'<path d="M{x - 18} {y - 2} Q{x} {y + 8} {x + 18} {y - 2}" fill="none" stroke="#f5deb3" stroke-width="4"/>'
    body += _sh(banner(28, 484, 290, 90, "#7f1d1d", ink, 6, cut=24))
    body += fit(_w("CHESTNUTS", "Abril Fatface", "#fef3c7", ink, 0, ls=8), 86, 304, 340, 62)
    return svg(body, d)


# ======================================================================= new year's

NYE = ("new year", "holiday", "party")


def _gold(id_="gold2"):
    return lin(id_, [(0, "#fff3c4"), (0.45, "#e2b13c"), (0.75, "#a8741a"), (1, "#f2d27a")])


def _confetti(
    x, y, w, h, n, seed, cols=("#f472b6", "#facc15", "#22d3ee", "#a3e635", "#a78bfa", "#fb923c")
):
    rng = random.Random(seed)
    out = ""
    for _ in range(n):
        cx, cy = x + rng.random() * w, y + rng.random() * h
        c = rng.choice(cols)
        if rng.random() < 0.5:
            out += f'<rect x="{cx:.0f}" y="{cy:.0f}" width="12" height="6" rx="2" fill="{c}" transform="rotate({rng.uniform(0, 180):.0f} {cx:.0f} {cy:.0f})"/>'
        else:
            out += f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="4" fill="{c}"/>'
    return out


def _row(word, font, fills, ink, sw=12, dy=8, rot=6, gap=4):
    out, x = "", 0.0
    for i, ch in enumerate(word):
        adv, _ = measure(ch, font, 400)
        out += f'<g transform="translate({x + adv / 2:.1f} {(-dy if i % 2 else dy)}) rotate({(-rot if i % 2 else rot)})">{_w(ch, font, fills[i % len(fills)], ink, sw)}</g>'
        x += adv + gap
    return out


@net("Countdown", SEASONS, *NYE)
def countdown():
    ink = "#020617"
    d = (
        SH
        + _gold()
        + rad("ball", [(0, "#ffffff"), (0.5, "#cbd5e1"), (1, "#475569")], cx=0.35, cy=0.3)
    )
    body = _panel(36, 40, 440, 432, "#0b1026", rx=24, edge="#000", sw=5)
    body += _confetti(50, 50, 410, 160, 30, 2)
    body += '<rect x="250" y="60" width="12" height="200" fill="#64748b"/>'
    body += _sh(
        f'<circle cx="256" cy="140" r="64" fill="url(#ball)" stroke="{ink}" stroke-width="5"/>'
    )
    for i in range(-3, 4):
        body += f'<line x1="{256 + i * 18}" y1="{140 - 62 * math.sqrt(1 - (i / 3.6) ** 2):.0f}" x2="{256 + i * 18}" y2="{140 + 62 * math.sqrt(1 - (i / 3.6) ** 2):.0f}" stroke="#94a3b8" stroke-width="2"/>'
        body += f'<line x1="{256 - 62 * math.sqrt(1 - (i / 3.6) ** 2):.0f}" y1="{140 + i * 18}" x2="{256 + 62 * math.sqrt(1 - (i / 3.6) ** 2):.0f}" y2="{140 + i * 18}" stroke="#94a3b8" stroke-width="2"/>'
    body += _sh(fit(_w("COUNTDOWN", "Bungee", "url(#gold2)", ink, 6), 56, 268, 400, 86))
    body += fit(_w("5 · 4 · 3 · 2 · 1", "Bungee", "#fff", ls=4), 116, 372, 280, 50)
    return svg(body, d)


@net("Midnight Toast", SEASONS, *NYE)
def midnight_toast():
    d = SH + _gold() + lin("bub", [(0, "#fef9c3"), (1, "#facc15")])
    body = _panel(36, 40, 440, 432, "#0a0a0a", rx=24, edge="#000", sw=5)
    for x, rot in ((222, -12), (290, 12)):
        g = '<path d="M-22 -130 L22 -130 L16 -20 Q0 -4 -16 -20 Z" fill="url(#bub)" stroke="#e2b13c" stroke-width="5"/>'
        g += '<path d="M-22 -130 L22 -130 L20 -108 L-20 -108 Z" fill="#fff" opacity=".5"/>'
        g += '<rect x="-3" y="-8" width="6" height="74" fill="#e2b13c"/><ellipse cx="0" cy="70" rx="26" ry="6" fill="#e2b13c"/>'
        body += _sh(f'<g transform="translate({x} 220) rotate({rot})">{g}</g>')
    for x, y, r in ((256, 70, 8), (240, 50, 5), (272, 40, 6), (226, 30, 4)):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="#fde68a" stroke-width="3"/>'
    body += _sparkle_s(256, 92, 22)
    body += _sh(fit(_w("MIDNIGHT", "Cinzel", "url(#gold2)", weight=900, ls=8), 66, 310, 380, 66))
    body += fit(_w("TOAST", "Cinzel", "#fef3c7", weight=700, ls=28), 146, 386, 220, 50)
    return svg(body, d)


def _sparkle_s(x, y, r, fill="#fff7c2"):
    return f'<polygon points="{star(x, y, r, r * 0.22, 4)}" fill="{fill}"/>'


@net("Confetti", SEASONS, *NYE, "celebration")
def confetti():
    ink = "#1e1b4b"
    d = SH
    body = _confetti(30, 40, 452, 430, 90, 7)
    cols = ("#f472b6", "#facc15", "#22d3ee", "#a3e635", "#a78bfa", "#fb923c", "#f472b6", "#22d3ee")
    spans = "".join(
        f'<tspan fill="{c}">{ch}</tspan>' for ch, c in zip("CONFETTI", cols, strict=True)
    )
    out = f'<text x="0" y="0" font-family="\'Titan One\'" font-size="100" text-anchor="middle" stroke="{ink}" stroke-width="12" stroke-linejoin="round" paint-order="stroke" letter-spacing="2">{spans}</text>'
    body += _sh(fit(out, 36, 170, 440, 170))
    return svg(body, d)


@net("Resolution", SEASONS, *NYE, "self-improvement")
def resolution():
    ink = "#1c1917"
    d = SH
    body = _sh(
        f'<rect x="96" y="60" width="320" height="380" rx="14" fill="#fff" stroke="{ink}" stroke-width="6"/>'
    )
    body += '<rect x="96" y="60" width="320" height="110" rx="14" fill="#dc2626"/><rect x="96" y="150" width="320" height="20" fill="#dc2626"/>'
    for x in (160, 352):
        body += f'<rect x="{x - 8}" y="36" width="16" height="50" rx="8" fill="#9ca3af" stroke="{ink}" stroke-width="4"/>'
    body += fit(_w("JANUARY", "Oswald", "#fff", weight=700, ls=10), 146, 86, 220, 56)
    body += fit(_w("1", "Abril Fatface", ink), 196, 180, 120, 180)
    body += _sh(banner(28, 484, 360, 84, "#1e3a8a", ink, 6, cut=22))
    body += fit(_w("RESOLUTION", "Archivo Black", "#fff", ls=4), 86, 374, 340, 56)
    return svg(body, d)


@net("Auld Lang Syne", SEASONS, *NYE, "music", "classic")
def auld_lang_syne():
    ink = "#1c1917"
    d = SH + _gold()
    tartan = "<pattern id='tart' width='48' height='48' patternUnits='userSpaceOnUse'><rect width='48' height='48' fill='#7f1d1d'/>"
    tartan += "<rect x='0' y='18' width='48' height='12' fill='#14532d' opacity='.8'/><rect x='18' y='0' width='12' height='48' fill='#14532d' opacity='.8'/>"
    tartan += "<rect x='0' y='23' width='48' height='2' fill='#facc15' opacity='.8'/><rect x='23' y='0' width='2' height='48' fill='#facc15' opacity='.8'/></pattern>"
    d += tartan
    body = _panel(36, 70, 440, 372, "#0b0b0b", rx=20, edge="#000", sw=5)
    body += _sh(
        f'<rect x="20" y="290" width="472" height="70" fill="url(#tart)" stroke="{ink}" stroke-width="5"/>'
    )
    body += _sh(fit(_w("Auld Lang Syne", "Great Vibes", "url(#gold2)"), 56, 120, 400, 160))
    body += '<rect x="166" y="376" width="180" height="40" rx="6" fill="#0b0b0b" stroke="url(#gold2)" stroke-width="3"/>'
    body += fit(_w("AT MIDNIGHT", "Cinzel", "#fef3c7", weight=700, ls=6), 180, 384, 152, 24)
    return svg(body, d)


@net("Party Hats", SEASONS, *NYE, "kids")
def party_hats():
    ink = "#1e1b4b"
    d = SH
    hats = (
        (140, 220, 130, "#f472b6", "#facc15"),
        (256, 190, 170, "#22d3ee", "#f472b6"),
        (372, 220, 130, "#a3e635", "#a78bfa"),
    )
    body = ""
    for cx, base, h, c, st in hats:
        w = h * 0.62
        hat = f'<polygon points="{cx},{base - h} {cx + w / 2},{base} {cx - w / 2},{base}" fill="{c}" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>'
        for k in range(1, 4):
            y = base - h + h * k / 4
            hw = w / 2 * k / 4
            hat += f'<line x1="{cx - hw:.0f}" y1="{y:.0f}" x2="{cx + hw:.0f}" y2="{y:.0f}" stroke="{st}" stroke-width="8"/>'
        hat += f'<circle cx="{cx}" cy="{base - h}" r="14" fill="#fff" stroke="{ink}" stroke-width="4"/>'
        body += _sh(hat)
    body += _confetti(40, 30, 432, 120, 24, 5)
    body += _sh(
        f'<rect x="40" y="270" width="432" height="140" rx="70" fill="#7c3aed" stroke="{ink}" stroke-width="7"/>'
    )
    body += fit(_w("PARTY HATS", "Titan One", "#fff", ink, 10), 80, 296, 352, 90)
    return svg(body, d)


# ======================================================================= easter

EASTER = ("easter", "holiday", "spring", "family")


def _egg(cx, cy, s, base, band, dots, ink="#3b0764"):
    path = f"M{cx} {cy - s} C{cx + s * 0.75} {cy - s} {cx + s * 0.8} {cy + s * 0.75} {cx} {cy + s * 0.75} C{cx - s * 0.8} {cy + s * 0.75} {cx - s * 0.75} {cy - s} {cx} {cy - s} Z"
    g = f'<path d="{path}" fill="{base}" stroke="{ink}" stroke-width="5"/>'
    g += f'<path d="M{cx - s * 0.66} {cy - s * 0.05} Q{cx} {cy - s * 0.3} {cx + s * 0.66} {cy - s * 0.05} L{cx + s * 0.7} {cy + s * 0.18} Q{cx} {cy - s * 0.05} {cx - s * 0.7} {cy + s * 0.18} Z" fill="{band}"/>'
    for dx, dy in ((-0.3, 0.4), (0, 0.48), (0.3, 0.4), (-0.15, -0.5), (0.18, -0.55)):
        g += f'<circle cx="{cx + dx * s:.0f}" cy="{cy + dy * s:.0f}" r="{s * 0.07:.1f}" fill="{dots}"/>'
    g += f'<ellipse cx="{cx - s * 0.3:.0f}" cy="{cy - s * 0.5:.0f}" rx="{s * 0.1:.0f}" ry="{s * 0.2:.0f}" fill="#fff" opacity=".6" transform="rotate(20 {cx - s * 0.3:.0f} {cy - s * 0.5:.0f})"/>'
    return g


@net("Egg Hunt", SEASONS, *EASTER, "kids")
def egg_hunt():
    ink = "#3b0764"
    d = SH + lin("eh", [(0, "#bae6fd"), (1, "#e0f2fe")])
    body = '<defs><clipPath id="ehc"><rect x="36" y="56" width="440" height="400" rx="30"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "url(#eh)", rx=30, edge=ink, sw=6)
    body += '<g clip-path="url(#ehc)">'
    body += (
        _egg(150, 330, 60, "#f9a8d4", "#a78bfa", "#fff")
        + _egg(380, 340, 54, "#fde68a", "#34d399", "#f472b6")
        + _egg(270, 360, 46, "#a5f3fc", "#f472b6", "#fde68a")
    )
    body += (
        '<path d="M36 380 '
        + "".join(f"L{36 + i * 10} {380 - (14 if i % 2 else 0)} " for i in range(45))
        + 'L476 456 L36 456 Z" fill="#22c55e"/>'
    )
    body += "</g>"
    body += _sh(fit(_w("EGG HUNT", "Titan One", "#fff", ink, 12), 66, 110, 380, 110))
    return svg(body, d)


@net("Bunny Hop", SEASONS, *EASTER, "kids")
def bunny_hop():
    ink = "#4a044e"
    d = SH
    ears = ""
    for x, rot in ((206, -12), (306, 12)):
        ears += f'<g transform="rotate({rot} {x} 250)"><ellipse cx="{x}" cy="150" rx="40" ry="110" fill="#fff" stroke="{ink}" stroke-width="7"/><ellipse cx="{x}" cy="160" rx="20" ry="82" fill="#f9a8d4"/></g>'
    body = _sh(ears)
    body += '<path d="M60 430 Q120 360 180 430 Q240 360 300 430 Q360 360 420 430" fill="none" stroke="#c084fc" stroke-width="6" stroke-dasharray="4 14" stroke-linecap="round"/>'
    body += _sh(
        f'<rect x="40" y="226" width="432" height="150" rx="75" fill="#c084fc" stroke="{ink}" stroke-width="7"/>'
    )
    body += fit(_w("BUNNY HOP", "Titan One", "#fff", ink, 10), 76, 252, 360, 100)
    return svg(body, d)


@net("Easter Basket", SEASONS, *EASTER)
def easter_basket():
    ink = "#3b2410"
    d = SH + lin("wv", [(0, "#d6a368"), (1, "#a0703c")])
    body = f'<path d="M110 250 Q110 60 256 60 Q402 60 402 250" fill="none" stroke="{ink}" stroke-width="26"/><path d="M110 250 Q110 60 256 60 Q402 60 402 250" fill="none" stroke="#d6a368" stroke-width="14"/>'
    body += (
        _egg(176, 236, 52, "#f9a8d4", "#a78bfa", "#fff")
        + _egg(256, 220, 58, "#fde68a", "#34d399", "#f472b6")
        + _egg(336, 236, 52, "#a5f3fc", "#f472b6", "#fde68a")
    )
    body += _sh(
        f'<path d="M70 250 L442 250 L410 460 L102 460 Z" fill="url(#wv)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    for y in range(270, 460, 22):
        body += f'<line x1="{70 + (y - 250) * 0.15:.0f}" y1="{y}" x2="{442 - (y - 250) * 0.15:.0f}" y2="{y}" stroke="{ink}" stroke-width="2" opacity=".35"/>'
    body += '<path d="M70 250 Q90 236 110 250 Q130 236 150 250 Q170 236 190 250 Q210 236 230 250 Q250 236 270 250 Q290 236 310 250 Q330 236 350 250 Q370 236 390 250 Q410 236 442 250" fill="#86efac" stroke="#15803d" stroke-width="4"/>'
    body += _sh(
        f'<rect x="90" y="300" width="332" height="110" rx="12" fill="#fdf2f8" stroke="{ink}" stroke-width="6"/>'
    )
    body += fit(_w("EASTER", "Lobster", "#db2777"), 120, 308, 272, 54)
    body += fit(_w("BASKET", "Archivo Black", "#7c3aed", ls=10), 140, 364, 232, 36)
    return svg(body, d)


@net("Chocolate Bunny", SEASONS, *EASTER, "candy")
def chocolate_bunny():
    ink = "#2b1408"
    d = SH + lin("choc", [(0, "#7c4a21"), (1, "#3b1d0a")])
    body = _sh(
        f'<rect x="56" y="60" width="400" height="392" rx="20" fill="url(#choc)" stroke="{ink}" stroke-width="7"/>'
    )
    drip = "M56 120 L56 80 Q56 60 76 60 L436 60 Q456 60 456 80 L456 120 "
    for i in range(10):
        x = 456 - i * 40
        drip += f"Q{x - 10} {150 + (i % 3) * 20} {x - 20} 120 Q{x - 30} 110 {x - 40} 120 "
    body += f'<path d="{drip}Z" fill="#4a2509"/>'
    for i in range(3):
        for j in range(2):
            body += f'<rect x="{96 + i * 112}" y="{340 + j * 52}" width="96" height="44" rx="6" fill="#5b2a0a" stroke="#2b1408" stroke-width="3"/>'
    body += _sh(
        f'<rect x="76" y="170" width="360" height="140" rx="16" fill="#fce7f3" stroke="{ink}" stroke-width="6"/>'
    )
    body += fit(_w("Chocolate", "Lobster", "#7c2d12"), 106, 180, 300, 76)
    body += fit(_w("BUNNY", "Archivo Black", "#db2777", ls=14), 156, 258, 200, 40)
    return svg(body, d)


@net("Easter Bonnet", SEASONS, *EASTER)
def easter_bonnet():
    ink = "#3b2410"
    d = SH + rad("straw", [(0, "#fde68a"), (1, "#d6a35c")])
    body = _sh(
        f'<ellipse cx="256" cy="230" rx="220" ry="70" fill="url(#straw)" stroke="{ink}" stroke-width="7"/>'
    )
    body += _sh(
        f'<path d="M150 230 Q150 100 256 100 Q362 100 362 230 Z" fill="url(#straw)" stroke="{ink}" stroke-width="7"/>'
    )
    body += f'<path d="M152 200 Q256 220 360 200 L362 230 Q256 250 150 230 Z" fill="#a78bfa" stroke="{ink}" stroke-width="5"/>'
    for x, c in ((180, "#f472b6"), (214, "#facc15"), (300, "#f9a8d4"), (334, "#fb923c")):
        for k in range(5):
            a = math.radians(k * 72)
            body += f'<circle cx="{x + 12 * math.cos(a):.0f}" cy="{196 + 12 * math.sin(a):.0f}" r="9" fill="{c}" stroke="{ink}" stroke-width="2"/>'
        body += f'<circle cx="{x}" cy="196" r="6" fill="#fef3c7"/>'
    body += '<path d="M346 236 Q380 300 350 340 M360 236 Q410 290 400 330" fill="none" stroke="#a78bfa" stroke-width="12" stroke-linecap="round"/>'
    body += fit(_w("EASTER", "Lobster", "#db2777", "#fff", 6), 96, 320, 280, 80)
    body += fit(_w("BONNET", "Archivo Black", "#7c3aed", "#fff", 6, ls=12), 116, 404, 280, 52)
    return svg(body, d)


@net("Spring Chick", SEASONS, *EASTER, "spring")
def spring_chick():
    ink = "#3b2410"
    d = SH + rad("chick", [(0, "#fef9c3"), (1, "#facc15")], cx=0.4, cy=0.35)
    body = _sh(
        f'<circle cx="256" cy="200" r="190" fill="#a7f3d0" stroke="{ink}" stroke-width="7"/>'
    )
    body += _sh(
        f'<circle cx="256" cy="180" r="74" fill="url(#chick)" stroke="{ink}" stroke-width="6"/>'
    )
    body += f'<circle cx="232" cy="166" r="8" fill="{ink}"/><circle cx="280" cy="166" r="8" fill="{ink}"/><polygon points="244,188 268,188 256,204" fill="#f97316" stroke="{ink}" stroke-width="3"/>'
    body += f'<path d="M256 108 Q246 86 256 76 Q266 86 256 108" fill="#facc15" stroke="{ink}" stroke-width="3"/>'
    shell = "M150 220 L180 200 L206 226 L232 202 L256 228 L280 202 L306 226 L332 200 L362 220 Q362 330 256 330 Q150 330 150 220 Z"
    body += _sh(
        f'<path d="{shell}" fill="#fff" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>'
    )
    body += _sh(banner(28, 484, 336, 92, "#f472b6", ink, 6, cut=24))
    body += fit(_w("SPRING CHICK", "Titan One", "#fff", ink, 8), 76, 350, 360, 62)
    return svg(body, d)


# ======================================================================= thanksgiving

THANKS = ("thanksgiving", "holiday", "family", "autumn")


@net("Turkey Day", SEASONS, *THANKS)
def turkey_day():
    ink = "#2b1408"
    d = SH
    cols = ("#b91c1c", "#ea580c", "#f59e0b", "#a16207", "#7c2d12")
    fan = ""
    for k in range(11):
        a = math.radians(180 + k * 18)
        c = cols[k % 5]
        fan += f'<path d="M256 300 L{256 + 230 * math.cos(a - 0.12):.0f} {300 + 230 * math.sin(a - 0.12):.0f} Q{256 + 250 * math.cos(a):.0f} {300 + 250 * math.sin(a):.0f} {256 + 230 * math.cos(a + 0.12):.0f} {300 + 230 * math.sin(a + 0.12):.0f} Z" fill="{c}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>'
    body = _sh(fan)
    body += _sh(
        f'<rect x="40" y="250" width="432" height="150" rx="20" fill="#fff7ed" stroke="{ink}" stroke-width="7"/>'
    )
    body += fit(_w("TURKEY", "Alfa Slab One", "#b91c1c", ink, 4), 80, 262, 352, 80)
    body += fit(_w("DAY", "Alfa Slab One", "#ea580c", ls=20), 186, 344, 140, 46)
    return svg(body, d)


@net("Gobble Gobble", SEASONS, *THANKS, "comedy")
def gobble_gobble():
    ink = "#2b1408"
    d = SH
    body = _sh(
        f'<path d="M60 90 L452 90 Q480 90 480 118 L480 330 Q480 358 452 358 L190 358 L130 430 L140 358 L60 358 Q32 358 32 330 L32 118 Q32 90 60 90 Z" fill="#ea580c" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += fit(
        _ex(_w("GOBBLE", "Bowlby One", "#fef3c7", ink, 10), 0, 7, ink, 6), 70, 112, 372, 104
    )
    body += fit(
        _ex(_w("GOBBLE!", "Bowlby One", "#facc15", ink, 10), 0, 7, ink, 6), 80, 230, 352, 104
    )
    return svg(body, d)


@net("Kids' Table", SEASONS, *THANKS, "kids")
def kids_table():
    ink = "#1c1917"
    d = SH
    body = _sh(
        f'<rect x="40" y="80" width="432" height="300" rx="6" fill="#e7c98a" stroke="{ink}" stroke-width="6" transform="rotate(-3 256 230)"/>'
    )
    body += '<path d="M90 330 q30 -30 60 0 t60 0" fill="none" stroke="#22c55e" stroke-width="6" stroke-linecap="round"/>'
    body += '<path d="M396 300 l12 26 28 4 -20 20 5 28 -25 -14 -25 14 5 -28 -20 -20 28 -4 Z" fill="none" stroke="#f59e0b" stroke-width="5" stroke-linejoin="round"/>'
    body += '<circle cx="110" cy="130" r="26" fill="none" stroke="#3b82f6" stroke-width="5"/>'
    body += fit(_w("KIDS'", "Permanent Marker", "#dc2626"), 120, 140, 272, 100)
    body += fit(_w("TABLE", "Permanent Marker", "#2563eb"), 140, 236, 232, 90)
    for i, c in enumerate(("#ef4444", "#3b82f6", "#22c55e", "#f59e0b", "#a855f7")):
        x = 120 + i * 60
        body += _sh(
            f'<g transform="rotate({-60 + i * 10} {x} 430)"><rect x="{x - 9}" y="380" width="18" height="96" rx="4" fill="{c}" stroke="{ink}" stroke-width="3"/><polygon points="{x - 9},380 {x + 9},380 {x},360" fill="{c}" stroke="{ink}" stroke-width="3"/></g>'
        )
    return svg(body, d)


@net("Second Helpings", SEASONS, *THANKS, "food")
def second_helpings():
    ink = "#1c1917"
    d = SH
    body = _sh(f'<circle cx="256" cy="210" r="170" fill="#fff" stroke="{ink}" stroke-width="7"/>')
    body += '<circle cx="256" cy="210" r="130" fill="none" stroke="#e7e5e4" stroke-width="6"/>'
    body += _sh(fit(_w("2nds", "Lobster", "#b45309", ink, 6), 156, 120, 200, 170))
    body += _sh(banner(28, 484, 350, 90, "#7c2d12", ink, 6, cut=24))
    body += fit(_w("SECOND HELPINGS", "Alfa Slab One", "#fef3c7"), 76, 364, 360, 60)
    return svg(body, d)


@net("Food Coma", SEASONS, *THANKS, "comedy")
def food_coma():
    ink = "#1c1917"
    d = SH + lin("fcm", [(0, "#fdba74"), (1, "#ea580c")])
    body = _panel(36, 80, 440, 352, "url(#fcm)", rx=30, edge=ink, sw=7)
    body += _sh(
        fit(_row("FOOD", "Bowlby One", ["#fff7ed"], ink, sw=10, dy=4, rot=4), 76, 120, 300, 110)
    )
    body += fit(_row("COMA", "Bowlby One", ["#7c2d12"], ink, sw=6, dy=6, rot=-7), 96, 250, 300, 110)
    for x, y, s in ((400, 150, 40), (430, 110, 30), (452, 80, 22)):
        body += fit(_w("Z", "Bowlby One", "#fff", ink, 6), x - s / 2, y - s / 2, s, s)
    return svg(body, d)


@net("Pumpkin Pie", SEASONS, *THANKS, "food", "autumn")
def pumpkin_pie():
    ink = "#2b1408"
    d = SH + lin("pp", [(0, "#f97316"), (1, "#c2410c")])
    slice_ = "M70 330 L440 330 L440 270 L110 150 Z"
    body = _sh(
        f'<path d="{slice_}" fill="url(#pp)" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/>'
    )
    body += f'<path d="M70 330 L440 330 L440 300 L70 300 Z" fill="#d6a35c" stroke="{ink}" stroke-width="5"/>'
    body += f'<path d="M440 330 L440 270 Q470 270 470 300 Q470 330 440 330 Z" fill="#d6a35c" stroke="{ink}" stroke-width="5"/>'
    body += _sh(
        f'<path d="M230 196 Q220 150 260 140 Q250 116 284 112 Q300 90 320 116 Q350 116 344 150 Q370 168 340 190 Q290 210 230 196 Z" fill="#fff" stroke="{ink}" stroke-width="5"/>'
    )
    body += _sh(banner(28, 484, 360, 92, "#7c2d12", ink, 6, cut=24))
    body += fit(_w("PUMPKIN PIE", "Alfa Slab One", "#fef3c7", ls=2), 80, 374, 352, 62)
    return svg(body, d)


# ======================================================================= summer

SUMMER = ("summer", "season", "family")


@net("Summer Vacation", SEASONS, *SUMMER, "travel")
def summer_vacation():
    ink = "#1c1917"
    d = SH + lin("svs", [(0, "#38bdf8"), (1, "#bae6fd")])
    body = _sh(
        f'<rect x="30" y="80" width="452" height="320" rx="8" fill="#fffbeb" stroke="{ink}" stroke-width="5" transform="rotate(-3 256 240)"/>'
    )
    body += '<g transform="rotate(-3 256 240)">'
    body += '<rect x="50" y="100" width="250" height="280" rx="4" fill="url(#svs)"/>'
    body += '<circle cx="240" cy="160" r="30" fill="#fde047"/><path d="M50 300 Q175 270 300 300 L300 380 L50 380 Z" fill="#0ea5e9"/><path d="M50 340 Q175 320 300 340 L300 380 L50 380 Z" fill="#fde68a"/>'
    body += '<path d="M110 340 Q100 270 120 220" fill="none" stroke="#7c4a21" stroke-width="7"/>'
    for a in (-60, -20, 20, 60, 100):
        body += f'<path d="M120 220 q{40 * math.cos(math.radians(a)):.0f} {-20 + 30 * math.sin(math.radians(a)):.0f} {70 * math.cos(math.radians(a)):.0f} {10 + 40 * math.sin(math.radians(a)):.0f}" fill="none" stroke="#16a34a" stroke-width="9" stroke-linecap="round"/>'
    body += '<line x1="320" y1="110" x2="320" y2="370" stroke="#d6d3d1" stroke-width="2"/>'
    body += '<rect x="380" y="110" width="80" height="96" fill="#fff" stroke="#dc2626" stroke-width="3" stroke-dasharray="6 3"/><circle cx="420" cy="158" r="20" fill="#f97316"/>'
    body += '<circle cx="370" cy="200" r="30" fill="none" stroke="#475569" stroke-width="2"/>'
    for i in range(3):
        body += f'<line x1="336" y1="{270 + i * 30}" x2="460" y2="{270 + i * 30}" stroke="#d6d3d1" stroke-width="2"/>'
    body += "</g>"
    body += _sh(banner(20, 492, 330, 96, "#f97316", ink, 6, cut=24))
    body += fit(_w("Summer Vacation", "Lobster", "#fff", ink, 6), 70, 340, 372, 76)
    return svg(body, d)


@net("Pool Party", SEASONS, *SUMMER, "party")
def pool_party():
    ink = "#0c4a6e"
    d = SH + lin("pool", [(0, "#67e8f9"), (1, "#0891b2")])
    body = '<defs><clipPath id="ppc"><rect x="36" y="56" width="440" height="400" rx="40"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "url(#pool)", rx=40, edge=ink, sw=6)
    body += '<g clip-path="url(#ppc)" fill="none" stroke="#fff" stroke-width="4" opacity=".45">'
    for y in range(80, 460, 34):
        body += f'<path d="M36 {y} q30 -10 60 0 t60 0 t60 0 t60 0 t60 0 t60 0 t60 0 t60 0"/>'
    body += "</g>"
    ring = ""
    for k in range(8):
        a1, a2 = k * 45, k * 45 + 45
        c = "#ef4444" if k % 2 == 0 else "#fff"
        x1, y1 = 256 + 100 * math.cos(math.radians(a1)), 170 + 100 * math.sin(math.radians(a1))
        x2, y2 = 256 + 100 * math.cos(math.radians(a2)), 170 + 100 * math.sin(math.radians(a2))
        ring += (
            f'<path d="M256 170 L{x1:.0f} {y1:.0f} A100 100 0 0 1 {x2:.0f} {y2:.0f} Z" fill="{c}"/>'
        )
    body += _sh(
        f'<g><circle cx="256" cy="170" r="104" fill="{ink}"/>{ring}<circle cx="256" cy="170" r="46" fill="url(#pool)" stroke="{ink}" stroke-width="6"/></g>'
    )
    body += '<ellipse cx="216" cy="110" rx="26" ry="10" fill="#fff" opacity=".6" transform="rotate(-30 216 110)"/>'
    body += _sh(fit(_w("POOL PARTY", "Titan One", "#fff", ink, 12), 66, 300, 380, 110))
    return svg(body, d)


@net("Heat Wave", SEASONS, *SUMMER)
def heat_wave():
    ink = "#450a0a"
    d = SH + lin("hw", [(0, "#fde047"), (0.5, "#f97316"), (1, "#dc2626")])
    body = _panel(36, 56, 440, 400, "url(#hw)", rx=30, edge=ink, sw=6)
    body += f'<rect x="384" y="86" width="44" height="220" rx="22" fill="#fff" stroke="{ink}" stroke-width="6"/><rect x="398" y="130" width="16" height="170" rx="8" fill="#dc2626"/><circle cx="406" cy="320" r="34" fill="#dc2626" stroke="{ink}" stroke-width="6"/>'
    for i in range(4):
        body += f'<line x1="430" y1="{110 + i * 40}" x2="444" y2="{110 + i * 40}" stroke="{ink}" stroke-width="4"/>'
    for i, y in enumerate((96, 126, 156)):
        body += f'<path d="M70 {y} q20 -14 40 0 t40 0 t40 0 t40 0" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity="{0.9 - i * 0.2:.1f}"/>'
    body += _sh(
        fit(_ex(_w("HEAT", "Bowlby One", "#fff7ed", ink, 10), 0, 7, ink, 6), 60, 190, 300, 110)
    )
    body += _sh(
        fit(_ex(_w("WAVE", "Bowlby One", "#fef08a", ink, 10), 0, 7, ink, 6), 60, 310, 300, 110)
    )
    return svg(body, d)


@net("Summer Reruns", SEASONS, *SUMMER, "classic tv", "reruns")
def summer_reruns():
    ink = "#7c2d12"
    d = SH + rad("srs", [(0, "#fef9c3"), (1, "#fbbf24")])
    body = _sh(f'<circle cx="256" cy="210" r="180" fill="none" stroke="{ink}" stroke-width="36"/>')
    body += '<circle cx="256" cy="210" r="180" fill="none" stroke="#f97316" stroke-width="24" stroke-dasharray="500 65"/>'
    for a in (0, 120, 240):
        x, y = (
            256 + 180 * math.cos(math.radians(a - 60)),
            210 + 180 * math.sin(math.radians(a - 60)),
        )
        body += f'<polygon points="{x - 22:.0f},{y - 14:.0f} {x + 22:.0f},{y - 14:.0f} {x:.0f},{y + 22:.0f}" fill="#f97316" stroke="{ink}" stroke-width="5" transform="rotate({a + 30} {x:.0f} {y:.0f})"/>'
    body += f'<circle cx="256" cy="210" r="140" fill="url(#srs)" stroke="{ink}" stroke-width="5"/>'
    body += _sh(fit(_w("SUMMER", "Alfa Slab One", "#9a3412", "#fff7ed", 6), 126, 150, 260, 96))
    body += _sh(banner(28, 484, 340, 92, "#0ea5e9", ink, 6, cut=24))
    body += fit(_w("RERUNS", "Alfa Slab One", "#fff", ls=14), 136, 354, 240, 62)
    return svg(body, d)


@net("Beach Blanket", SEASONS, *SUMMER, "beach", "movies")
def beach_blanket():
    ink = "#1c1917"
    d = (
        SH
        + "<pattern id='bbst' width='60' height='60' patternUnits='userSpaceOnUse' patternTransform='rotate(-20)'><rect width='60' height='60' fill='#fef3c7'/><rect width='60' height='20' fill='#ef4444'/><rect y='30' width='60' height='10' fill='#0ea5e9'/></pattern>"
    )
    body = '<rect x="0" y="0" width="512" height="512" fill="none"/>'
    body += _sh(
        f'<rect x="56" y="150" width="400" height="260" rx="6" fill="url(#bbst)" stroke="{ink}" stroke-width="6" transform="rotate(-8 256 280)"/>'
    )
    for x in range(70, 450, 20):
        body += f'<line x1="{x}" y1="420" x2="{x - 4}" y2="440" stroke="{ink}" stroke-width="3" transform="rotate(-8 256 280)"/>'
    body += f'<line x1="390" y1="40" x2="350" y2="300" stroke="{ink}" stroke-width="8"/>'
    body += _sh(
        f'<path d="M240 120 Q380 0 520 140 Z" fill="#f472b6" stroke="{ink}" stroke-width="6"/>'
    )
    body += (
        '<path d="M287 92 L380 120 L380 40 Z M380 120 L470 92 L380 40 Z" fill="#fff" opacity=".5"/>'
    )
    body += _sh(
        f'<rect x="80" y="220" width="352" height="130" rx="10" fill="#fff" stroke="{ink}" stroke-width="6" transform="rotate(-8 256 285)"/>'
    )
    body += f'<g transform="rotate(-8 256 285)">{fit(_w("BEACH", "Lilita One", "#0ea5e9", ink, 6, ls=6), 110, 228, 292, 66)}{fit(_w("BLANKET", "Lilita One", "#ef4444", ink, 6, ls=6), 120, 296, 272, 46)}</g>'
    return svg(body, d)


@net("School's Out", SEASONS, *SUMMER, "kids", "comedy")
def schools_out():
    ink = "#111827"
    d = SH
    sign = "M256 40 L452 180 L452 452 L60 452 L60 180 Z"
    body = _sh(
        f'<path d="{sign}" fill="#facc15" stroke="{ink}" stroke-width="10" stroke-linejoin="round"/>'
    )
    body += f'<path d="M256 64 L430 190 L430 430 L82 430 L82 190 Z" fill="none" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>'
    body += fit(_w("SCHOOL'S", "Archivo Black", ink, ls=2), 106, 200, 300, 90)
    body += fit(_w("OUT!", "Archivo Black", ink, ls=8), 150, 300, 212, 110)
    return svg(body, d)


@net("Dog Days", SEASONS, *SUMMER, "comedy")
def dog_days():
    ink = "#3b2410"
    d = SH + rad("dds", [(0, "#fef9c3"), (1, "#f59e0b")])
    body = '<circle cx="256" cy="150" r="110" fill="url(#dds)"/>'
    for k in range(16):
        a = math.radians(k * 22.5)
        body += f'<line x1="{256 + 120 * math.cos(a):.0f}" y1="{150 + 120 * math.sin(a):.0f}" x2="{256 + 150 * math.cos(a):.0f}" y2="{150 + 150 * math.sin(a):.0f}" stroke="#f59e0b" stroke-width="8" stroke-linecap="round"/>'
    body += _sh(
        f'<path d="M120 300 A56 56 0 0 1 64 244 A56 56 0 0 1 120 188 A56 56 0 0 1 160 210 L352 210 A56 56 0 0 1 392 188 A56 56 0 0 1 448 244 A56 56 0 0 1 392 300 A56 56 0 0 1 352 278 L160 278 A56 56 0 0 1 120 300 Z" fill="#fff7ed" stroke="{ink}" stroke-width="8" transform="translate(0 70)"/>'
    )
    body += fit(_w("DOG DAYS", "Alfa Slab One", "#b45309", ink, 4), 120, 286, 272, 72)
    body += fit(_w("OF SUMMER", "Oswald", "#fff7ed", ink, 6, weight=700, ls=10), 166, 400, 180, 34)
    return svg(body, d)


@net("Surf's Up", SEASONS, *SUMMER, "surfing", "beach")
def surfs_up():
    ink = "#0c1a2e"
    d = SH + lin("board", [(0, "#fde047"), (1, "#f97316")])
    body = _sh(
        f'<path d="M256 20 Q330 140 310 360 Q296 470 256 490 Q216 470 202 360 Q182 140 256 20 Z" fill="url(#board)" stroke="{ink}" stroke-width="8" transform="rotate(30 256 256)"/>'
    )
    body += '<g transform="rotate(30 256 256)"><path d="M256 40 L256 470" stroke="#dc2626" stroke-width="10"/><path d="M240 40 L240 470 M272 40 L272 470" stroke="#fff" stroke-width="4"/></g>'
    body += _sh(
        f'<rect x="36" y="196" width="440" height="130" rx="20" fill="#0891b2" stroke="{ink}" stroke-width="7"/>'
    )
    body += fit(
        _ex(_w("SURF'S UP", "Racing Sans One", "#fff", ink, 10, style="italic"), 4, 6, ink, 6),
        60,
        212,
        392,
        100,
    )
    return svg(body, d)


@net("Summer Camp", SEASONS, *SUMMER, "kids", "outdoors")
def summer_camp():
    scene = '<rect x="0" y="0" width="512" height="512" fill="#fde68a"/><circle cx="350" cy="160" r="50" fill="#f97316"/>'
    scene += '<path d="M0 330 L120 200 L200 290 L290 180 L400 300 L512 220 L512 512 L0 512 Z" fill="#15803d"/>'
    for x in (80, 140, 380, 440):
        scene += f'<polygon points="{x},210 {x - 30},300 {x + 30},300" fill="#14532d"/><polygon points="{x},250 {x - 38},340 {x + 38},340" fill="#14532d"/>'
    scene += '<polygon points="256,220 330,340 182,340" fill="#ef4444" stroke="#1c1917" stroke-width="5"/><polygon points="256,260 280,340 232,340" fill="#7f1d1d"/>'
    return L.patch(
        scene,
        "SUMMER CAMP",
        font="Graduate",
        ink="#fef3c7",
        band="#14532d",
        rim="#fef3c7",
        edge="#1c1917",
        shape="hexagon",
        ls=2,
    )


# ======================================================================= winter

WINTER = ("winter", "season", "cozy")


def _flake(cx, cy, r, colour, w=8):
    s = ""
    for k in range(6):
        a = math.radians(k * 60)
        x2, y2 = cx + r * math.cos(a), cy + r * math.sin(a)
        s += f'<line x1="{cx}" y1="{cy}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{colour}" stroke-width="{w}" stroke-linecap="round"/>'
        for t in (0.5, 0.75):
            bx, by = cx + r * t * math.cos(a), cy + r * t * math.sin(a)
            for da in (-40, 40):
                b = math.radians(k * 60 + da)
                s += f'<line x1="{bx:.0f}" y1="{by:.0f}" x2="{bx + r * 0.22 * math.cos(b):.0f}" y2="{by + r * 0.22 * math.sin(b):.0f}" stroke="{colour}" stroke-width="{w * 0.7:.0f}" stroke-linecap="round"/>'
    return s


@net("Snow Day", SEASONS, *WINTER, "kids")
def snow_day():
    ink = "#0c4a6e"
    d = SH + lin("sdk", [(0, "#38bdf8"), (1, "#1d4ed8")])
    body = _panel(36, 56, 440, 400, "url(#sdk)", rx=36, edge=ink, sw=6)
    body += _flake(256, 170, 100, "#fff", 12)
    for x, y, r in ((90, 100, 20), (420, 120, 26), (100, 300, 16), (430, 290, 18)):
        body += _flake(x, y, r, "#e0f2fe", 4)
    body += _sh(fit(_w("SNOW DAY", "Titan One", "#fff", ink, 12), 66, 296, 380, 96))
    body += fit(_w("NO SCHOOL TODAY!", "Fredoka", "#e0f2fe", weight=700, ls=6), 136, 400, 240, 30)
    return svg(body, d)


@net("Cabin Fever", SEASONS, *WINTER)
def cabin_fever():
    ink = "#1c0f05"
    d = SH + lin("cfn", [(0, "#0b1026"), (1, "#312e81")])
    body = '<defs><clipPath id="cfc"><rect x="36" y="56" width="440" height="400" rx="24"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "url(#cfn)", rx=24, edge="#000", sw=5)
    body += '<g clip-path="url(#cfc)">'
    rng = random.Random(6)
    for _ in range(40):
        body += f'<circle cx="{rng.uniform(40, 470):.0f}" cy="{rng.uniform(60, 440):.0f}" r="{rng.uniform(2, 4):.1f}" fill="#fff" opacity=".7"/>'
    body += f'<path d="M110 300 L110 220 L256 140 L402 220 L402 300 Z" fill="#7c4a21" stroke="{ink}" stroke-width="5"/>'
    for y in range(230, 300, 14):
        body += f'<line x1="110" y1="{y}" x2="402" y2="{y}" stroke="{ink}" stroke-width="3"/>'
    body += '<path d="M96 226 L256 132 L416 226 L404 236 L256 152 L108 236 Z" fill="#f8fafc"/>'
    body += '<rect x="170" y="240" width="50" height="40" fill="#fde047"/><rect x="292" y="240" width="50" height="40" fill="#fde047"/>'
    body += '<rect x="340" y="150" width="24" height="50" fill="#57534e"/><rect x="36" y="296" width="440" height="160" fill="#f8fafc"/></g>'
    body += _sh(fit(_w("CABIN FEVER", "Alfa Slab One", "#dc2626", ink, 6), 66, 320, 380, 80))
    body += fit(
        _w("WINTER MOVIE MARATHONS", "Oswald", "#1e3a8a", weight=700, ls=6), 116, 406, 280, 28
    )
    return svg(body, d)


@net("Snowed In", SEASONS, *WINTER)
def snowed_in():
    ink = "#1e293b"
    d = SH + lin("sni", [(0, "#1e3a8a"), (1, "#3b82f6")])
    body = _sh(
        f'<rect x="56" y="40" width="400" height="432" rx="8" fill="#f8fafc" stroke="{ink}" stroke-width="8"/>'
    )
    body += '<rect x="80" y="64" width="352" height="384" fill="url(#sni)"/>'
    body += '<line x1="256" y1="64" x2="256" y2="448" stroke="#e2e8f0" stroke-width="10"/><line x1="80" y1="256" x2="432" y2="256" stroke="#e2e8f0" stroke-width="10"/>'
    rng = random.Random(3)
    for _ in range(26):
        body += f'<circle cx="{rng.uniform(90, 420):.0f}" cy="{rng.uniform(70, 340):.0f}" r="{rng.uniform(2, 4):.1f}" fill="#fff" opacity=".8"/>'
    body += _sh(fit(_w("SNOWED", "Archivo Black", "#fff", ink, 8, ls=4), 96, 110, 320, 90))
    body += _sh(fit(_w("IN", "Archivo Black", "#fff", ink, 8, ls=10), 196, 214, 120, 100))
    body += '<path d="M80 448 L80 380 Q140 340 210 366 Q280 392 330 352 Q390 318 432 352 L432 448 Z" fill="#f8fafc" stroke="#cbd5e1" stroke-width="4"/>'
    return svg(body, d)


@net("Ski Lodge", SEASONS, *WINTER, "retro")
def ski_lodge():
    ink = "#1c1917"
    d = SH + lin("slk", [(0, "#fde68a"), (1, "#fb923c")])
    body = '<defs><clipPath id="slc"><rect x="56" y="40" width="400" height="432" rx="10"/></clipPath></defs>'
    body += _panel(56, 40, 400, 432, "url(#slk)", rx=10, edge=ink, sw=7)
    body += '<g clip-path="url(#slc)"><polygon points="56,320 200,120 290,240 350,170 456,320" fill="#f8fafc"/>'
    body += '<polygon points="200,120 240,176 214,170 196,186 176,160" fill="#fff"/><polygon points="56,320 200,120 160,240 120,260" fill="#cbd5e1"/>'
    body += '<rect x="56" y="320" width="400" height="152" fill="#1e3a8a"/>'
    body += f'<polygon points="256,240 320,320 192,320" fill="#7f1d1d" stroke="{ink}" stroke-width="4"/><rect x="240" y="290" width="32" height="30" fill="#fde047"/></g>'
    body += fit(_w("SKI", "Bevan", "#fef3c7", ls=20), 166, 334, 180, 70)
    body += fit(_w("LODGE", "Bevan", "#fde68a", ls=14), 126, 406, 260, 48)
    return svg(body, d)


@net("Fireside", SEASONS, *WINTER)
def fireside():
    ink = "#1c0f05"
    d = SH + rad("fglow", [(0, "#fde68a"), (0.5, "#f97316"), (1, "#7c2d12")], cx=0.5, cy=0.8, r=0.7)
    body = _sh(
        f'<rect x="40" y="130" width="432" height="340" rx="10" fill="#78716c" stroke="{ink}" stroke-width="7"/>'
    )
    rng = random.Random(8)
    for row in range(8):
        for col in range(7):
            x = 44 + col * 62 + (31 if row % 2 else 0)
            y = 134 + row * 42
            if x < 466:
                body += f'<rect x="{x}" y="{y}" width="{min(58, 468 - x)}" height="38" rx="6" fill="{rng.choice(("#a8a29e", "#8b8581", "#d6d3d1"))}" stroke="#57534e" stroke-width="2"/>'
    body += _sh(
        f'<rect x="20" y="100" width="472" height="44" rx="6" fill="#7c4a21" stroke="{ink}" stroke-width="6"/>'
    )
    body += f'<path d="M126 470 L126 320 Q126 240 256 240 Q386 240 386 320 L386 470 Z" fill="url(#fglow)" stroke="{ink}" stroke-width="7"/>'
    for x, h, c in (
        (200, 120, "#f97316"),
        (256, 170, "#fbbf24"),
        (312, 110, "#f97316"),
        (236, 90, "#fef3c7"),
        (280, 80, "#fef3c7"),
    ):
        body += f'<path d="M{x - 30} 450 Q{x - 34} {450 - h * 0.55:.0f} {x} {450 - h} Q{x + 34} {450 - h * 0.55:.0f} {x + 30} 450 Z" fill="{c}" opacity=".9"/>'
    body += '<rect x="150" y="440" width="212" height="22" rx="10" fill="#57290e"/>'
    body += _sh(fit(_w("Fireside", "Lobster", "#fef3c7", ink, 8), 106, 20, 300, 86))
    return svg(body, d)


@net("Hot Cocoa", SEASONS, *WINTER, "kids")
def hot_cocoa():
    ink = "#2b1408"
    d = SH
    body = ""
    for x in (206, 256, 306):
        body += f'<path d="M{x} 120 q-14 -26 0 -52 t0 -52" fill="none" stroke="#d6d3d1" stroke-width="8" stroke-linecap="round" opacity=".8"/>'
    body += _sh(
        f'<path d="M110 150 L402 150 L380 430 Q378 452 356 452 L156 452 Q134 452 132 430 Z" fill="#dc2626" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += f'<path d="M396 200 Q470 200 470 270 Q470 340 386 340" fill="none" stroke="{ink}" stroke-width="30"/><path d="M396 200 Q470 200 470 270 Q470 340 386 340" fill="none" stroke="#dc2626" stroke-width="16"/>'
    body += f'<ellipse cx="256" cy="152" rx="146" ry="22" fill="#7c4a21" stroke="{ink}" stroke-width="6"/>'
    for x, y in ((206, 148), (248, 142), (296, 150), (330, 144)):
        body += f'<rect x="{x - 14}" y="{y - 14}" width="28" height="22" rx="6" fill="#fff" stroke="{ink}" stroke-width="3"/>'
    body += f'<rect x="146" y="230" width="220" height="150" rx="14" fill="#fff7ed" stroke="{ink}" stroke-width="5"/>'
    body += fit(_w("HOT", "Alfa Slab One", "#dc2626", ls=10), 186, 244, 140, 56)
    body += fit(_w("COCOA", "Alfa Slab One", "#7c4a21", ls=4), 166, 310, 180, 54)
    return svg(body, d)


@net("Icicle", SEASONS, *WINTER)
def icicle():
    ink = "#0c4a6e"
    d = SH + lin("ice", [(0, "#ffffff"), (0.5, "#bae6fd"), (1, "#7dd3fc")])
    body = _sh(fit(_w("ICICLE", "Bowlby One", "url(#ice)", ink, 10, ls=6), 40, 130, 432, 150))
    rng = random.Random(5)
    x = 60
    while x < 452:
        w = rng.uniform(16, 26)
        h = rng.uniform(50, 150)
        body += f'<path d="M{x:.0f} 272 L{x + w:.0f} 272 L{x + w / 2:.0f} {272 + h:.0f} Z" fill="url(#ice)" stroke="{ink}" stroke-width="3" stroke-linejoin="round"/>'
        x += w + rng.uniform(6, 16)
    body += f'<rect x="40" y="262" width="432" height="16" rx="8" fill="#e0f2fe" stroke="{ink}" stroke-width="3"/>'
    return svg(body, d)


# ===================================================================== halloween

HALLOWEEN = ("halloween", "october", "spooky")


@net("Trick or Treat", SEASONS, *HALLOWEEN, "kids")
def trick_or_treat():
    ink = "#14061f"
    d = SH + lin("tot", [(0, "#4c1d95"), (1, "#1e0b36")])
    body = _panel(40, 66, 432, 380, "url(#tot)", rx=40, edge=ink, sw=6)
    body += '<rect x="58" y="84" width="396" height="344" rx="28" fill="none" stroke="#f97316" stroke-width="4" opacity=".75"/>'
    body += _sh(fit(_ex(_w("TRICK", "Bungee", "#fb923c", ink, 6), 6, 8, ink), 90, 104, 332, 112))
    body += '<line x1="96" y1="256" x2="206" y2="256" stroke="#f97316" stroke-width="4"/>'
    body += '<line x1="306" y1="256" x2="416" y2="256" stroke="#f97316" stroke-width="4"/>'
    body += f'<circle cx="256" cy="256" r="36" fill="#84cc16" stroke="{ink}" stroke-width="5"/>'
    body += fit(_w("or", "Pacifico", ink), 232, 232, 48, 42)
    body += _sh(fit(_ex(_w("TREAT", "Bungee", "#fde047", ink, 6), 6, 8, ink), 90, 300, 332, 112))
    return svg(body, d)


@net("Haunted House", SEASONS, *HALLOWEEN)
def haunted_house():
    ink = "#04140b"
    d = (
        SH
        + lin("hhg", [(0, "#166534"), (1, "#022c16")])
        + glow("hhw", "#4ade80", blur=12, strength=2)
    )
    shape = "M256 30 L474 196 L474 472 L38 472 L38 196 Z"
    body = _sh(
        f'<path d="{shape}" fill="url(#hhg)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += '<path d="M256 60 L448 206 L448 446 L64 446 L64 206 Z" fill="none" stroke="#86efac" stroke-width="3" stroke-linejoin="round" opacity=".55"/>'
    body += '<g filter="url(#hhw)"><circle cx="256" cy="170" r="42" fill="#d9f99d"/></g>'
    body += f'<line x1="256" y1="128" x2="256" y2="212" stroke="{ink}" stroke-width="7"/>'
    body += f'<line x1="214" y1="170" x2="298" y2="170" stroke="{ink}" stroke-width="7"/>'
    body += _sh(fit(_w("Haunted", "Pirata One", "#ecfccb", ink, 6, ls=2), 88, 236, 336, 108))
    body += fit(_w("HOUSE", "Cinzel", "#86efac", weight=800, ls=26), 140, 366, 232, 50)
    return svg(body, d)


@net("Candy Corn", SEASONS, *HALLOWEEN, "kids")
def candy_corn():
    ink = "#2a1405"
    kernel = (
        "M256 34 Q282 34 302 76 L414 300 Q434 346 384 346 L128 346 Q78 346 98 300 "
        "L210 76 Q230 34 256 34 Z"
    )
    d = SH + f'<clipPath id="ccc"><path d="{kernel}"/></clipPath>'
    body = _sh(f'<path d="{kernel}" fill="#fde047"/>')
    body += (
        '<g clip-path="url(#ccc)"><rect x="0" y="0" width="512" height="150" fill="#fff7ed"/>'
        '<rect x="0" y="150" width="512" height="104" fill="#fb923c"/></g>'
    )
    body += (
        f'<path d="{kernel}" fill="none" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += '<path d="M236 76 Q214 132 186 196" fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" opacity=".5"/>'
    body += _sh(fit(_w("CANDY CORN", "Bungee", "#fff7ed", ink, 12, ls=2), 36, 372, 440, 92))
    return svg(body, d)


@net("Jack-o'-Lantern", SEASONS, *HALLOWEEN)
def jack_o_lantern():
    ink = "#2a0f02"
    d = (
        SH
        + rad("jol", [(0, "#fdba74"), (0.65, "#f97316"), (1, "#c2410c")], cx=0.45, cy=0.4, r=0.75)
        + glow("jog", "#facc15", blur=8, strength=2)
    )
    body = '<path d="M256 128 Q248 84 284 56" fill="none" stroke="#3f6212" stroke-width="20" stroke-linecap="round"/>'
    lobes = ""
    for cx, rx in ((148, 118), (364, 118), (206, 112), (306, 112), (256, 104)):
        lobes += f'<ellipse cx="{cx}" cy="294" rx="{rx}" ry="168" fill="url(#jol)" stroke="{ink}" stroke-width="7"/>'
    body += _sh(lobes)
    body += f'<g filter="url(#jog)">{fit(_w("JACK·O’", "Titan One", "#fef08a", ink, 5, ls=2), 92, 196, 328, 104)}</g>'
    body += f'<g filter="url(#jog)">{fit(_w("LANTERN", "Titan One", "#fde047", ink, 5, ls=2), 92, 316, 328, 82)}</g>'
    return svg(body, d)


@net("Witching Hour", SEASONS, *HALLOWEEN, "late night")
def witching_hour():
    ink = "#0f0a1e"
    d = SH + rad("whf", [(0, "#f5f3ff"), (1, "#c4b5fd")], cx=0.5, cy=0.45, r=0.6)
    body = _sh(
        f'<circle cx="256" cy="222" r="190" fill="#2e1065" stroke="{ink}" stroke-width="8"/>'
    )
    body += '<circle cx="256" cy="222" r="172" fill="none" stroke="#c4b5fd" stroke-width="3"/>'
    body += f'<circle cx="256" cy="222" r="152" fill="url(#whf)" stroke="{ink}" stroke-width="5"/>'
    numerals = ("XII", "I", "II", "III", "IIII", "V", "VI", "VII", "VIII", "IX", "X", "XI")
    for k, n in enumerate(numerals):
        a = math.radians(k * 30 - 90)
        x, y = 256 + 120 * math.cos(a), 222 + 120 * math.sin(a)
        size = 24 if len(n) < 4 else 19
        body += text(n, "Cinzel", size, weight=800, fill=ink, x=round(x), y=round(y + size * 0.36))
    body += f'<path d="M256 222 L246 150 L256 92 L266 150 Z" fill="{ink}"/>'
    body += f'<path d="M256 222 L247 172 L256 134 L265 172 Z" fill="#7c3aed" stroke="{ink}" stroke-width="3"/>'
    body += f'<circle cx="256" cy="222" r="11" fill="{ink}"/>'
    body += _sh(banner(52, 460, 386, 76, "#7c3aed", edge=ink, sw=6, cut=22))
    body += fit(_w("WITCHING HOUR", "Cinzel", "#f5f3ff", weight=900, ls=4), 96, 400, 320, 48)
    return svg(body, d)


@net("Full Moon", SEASONS, *HALLOWEEN, "late night")
def full_moon():
    ink = "#05081c"
    d = (
        SH
        + lin("fmn", [(0, "#0b1238"), (1, "#1e1b4b")])
        + rad("fmm", [(0, "#fffbeb"), (0.7, "#fde68a"), (1, "#f5b342")], cx=0.42, cy=0.4, r=0.7)
        + glow("fmg", "#fde68a", blur=16, strength=2)
        + '<clipPath id="fmc"><rect x="40" y="40" width="432" height="432" rx="34"/></clipPath>'
    )
    body = _panel(40, 40, 432, 432, "url(#fmn)", rx=34, edge=ink, sw=6)
    body += '<g clip-path="url(#fmc)">'
    rng = random.Random(11)
    for _ in range(36):
        body += f'<circle cx="{rng.uniform(50, 462):.0f}" cy="{rng.uniform(50, 300):.0f}" r="{rng.uniform(1.2, 2.6):.1f}" fill="#fff" opacity=".7"/>'
    body += '<g filter="url(#fmg)"><circle cx="256" cy="210" r="140" fill="url(#fmm)"/></g>'
    for x, y, r in ((206, 160, 26), (300, 140, 15), (306, 248, 34), (212, 262, 18), (262, 198, 10)):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#d97706" opacity=".22"/>'
    trees = "M40 330"
    rng = random.Random(4)
    x = 40
    while x < 472:
        w = rng.uniform(22, 40)
        h = rng.uniform(30, 80)
        trees += f" L{x + w / 2:.0f} {330 - h:.0f} L{x + w:.0f} 330"
        x += w
    body += f'<path d="{trees} L472 472 L40 472 Z" fill="{ink}"/></g>'
    body += fit(_w("FULL MOON", "Bebas Neue", "#fde68a", ls=10), 76, 360, 360, 84)
    return svg(body, d)


@net("Costume Party", SEASONS, *HALLOWEEN, "party")
def costume_party():
    ink = "#1a0b2e"
    d = (
        SH
        + lin("cpb", [(0, "#3b0764"), (1, "#1a0b2e")])
        + lin("cpm", [(0, "#fef3c7"), (0.45, "#fbbf24"), (1, "#b45309")])
    )
    body = _panel(36, 56, 440, 400, "url(#cpb)", rx=36, edge="#000", sw=5)
    mask = (
        "M256 154 C300 124 378 112 434 132 C462 142 462 190 444 218 C416 264 358 276 316 250 "
        "C292 235 276 228 256 228 C236 228 220 235 196 250 C154 276 96 264 68 218 "
        "C50 190 50 142 78 132 C134 112 212 124 256 154 Z"
    )
    body += _sh(
        f'<path d="{mask}" fill="url(#cpm)" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/>'
    )
    body += f'<path d="M112 188 Q152 154 206 186 Q160 216 112 188 Z" fill="{ink}"/>'
    body += f'<path d="M400 188 Q360 154 306 186 Q352 216 400 188 Z" fill="{ink}"/>'
    for x, y in ((140, 142), (256, 168), (372, 142)):
        body += f'<circle cx="{x}" cy="{y}" r="6" fill="#a855f7" stroke="{ink}" stroke-width="2"/>'
    body += _sh(fit(_w("COSTUME", "Limelight", "#fde68a", ink, 6, ls=6), 70, 290, 372, 82))
    body += fit(_w("PARTY", "Limelight", "#d8b4fe", ink, 4, ls=22), 136, 386, 240, 50)
    return svg(body, d)


@net("Black Cat", SEASONS, *HALLOWEEN)
def black_cat():
    ink = "#0a0a0a"
    d = SH + rad("bcd", [(0, "#fdba74"), (0.75, "#f97316"), (1, "#c2410c")], cx=0.5, cy=0.4, r=0.7)
    body = _sh(
        f'<circle cx="256" cy="206" r="166" fill="url(#bcd)" stroke="{ink}" stroke-width="8"/>'
    )
    cat = (
        f'<path d="M300 334 C380 334 396 270 360 232" fill="none" stroke="{ink}" stroke-width="18" stroke-linecap="round"/>'
        f'<path d="M218 196 C188 240 184 304 204 344 L308 344 C328 304 324 240 294 196 Z" fill="{ink}"/>'
        f'<circle cx="256" cy="160" r="44" fill="{ink}"/>'
        f'<path d="M218 146 L224 92 L252 126 Z" fill="{ink}"/><path d="M294 146 L288 92 L260 126 Z" fill="{ink}"/>'
        '<ellipse cx="240" cy="160" rx="8" ry="5" fill="#fde047"/><ellipse cx="272" cy="160" rx="8" ry="5" fill="#fde047"/>'
    )
    body += cat
    body += _sh(
        f'<rect x="56" y="356" width="400" height="96" rx="14" fill="{ink}" stroke="#f97316" stroke-width="4"/>'
    )
    body += fit(_w("BLACK CAT", "Bebas Neue", "#fb923c", ls=12), 84, 370, 344, 70)
    return svg(body, d)


@net("Belfry", SEASONS, *HALLOWEEN)
def belfry():
    ink = "#0c0a14"
    stone = "#a8a29e"
    d = (
        SH
        + lin("bfs", [(0, "#312e81"), (1, "#0f0a1e")])
        + lin("bfb", [(0, "#fde68a"), (0.5, "#d97706"), (1, "#92400e")], x2=1, y2=0)
    )
    arch = "M150 420 L150 214 Q150 92 256 52 Q362 92 362 214 L362 420 Z"
    body = _sh(
        f'<path d="{arch}" fill="url(#bfs)" stroke="{stone}" stroke-width="18" stroke-linejoin="round"/>'
    )
    body += (
        f'<path d="{arch}" fill="none" stroke="{ink}" stroke-width="4" stroke-linejoin="round"/>'
    )
    body += f'<rect x="166" y="150" width="180" height="14" rx="4" fill="#57534e" stroke="{ink}" stroke-width="3"/>'
    bell = (
        "M256 168 C226 168 214 196 212 232 C210 264 200 282 184 294 L328 294 "
        "C312 282 302 264 300 232 C298 196 286 168 256 168 Z"
    )
    body += f'<line x1="256" y1="160" x2="256" y2="172" stroke="{ink}" stroke-width="8"/>'
    body += f'<path d="{bell}" fill="url(#bfb)" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>'
    body += f'<rect x="176" y="290" width="160" height="14" rx="7" fill="#b45309" stroke="{ink}" stroke-width="4"/>'
    body += f'<circle cx="256" cy="318" r="12" fill="#92400e" stroke="{ink}" stroke-width="4"/>'
    for x, y, sz in ((392, 96, 70), (430, 150, 48), (110, 120, 52)):
        body += centred(S.bat(P(k="#8b5cf6")), x, y, sz)
    body += _sh(
        f'<rect x="72" y="392" width="368" height="80" rx="8" fill="{stone}" stroke="{ink}" stroke-width="5"/>'
    )
    body += fit(_w("BELFRY", "Cinzel", "#1c1917", weight=900, ls=14), 104, 406, 304, 54)
    return svg(body, d)


@net("Hayride", SEASONS, *HALLOWEEN, "autumn")
def hayride():
    ink = "#271204"
    d = (
        SH
        + lin("hrw", [(0, "#b45309"), (1, "#78350f")])
        + rad("hrm", [(0, "#fde68a"), (1, "#f97316")], cx=0.5, cy=0.5, r=0.5)
    )
    body = '<circle cx="256" cy="150" r="112" fill="url(#hrm)" opacity=".95"/>'
    for x in (128, 384):
        body += f'<rect x="{x - 12}" y="200" width="24" height="250" rx="4" fill="#57290e" stroke="{ink}" stroke-width="4"/>'
    body += _sh(
        f'<rect x="40" y="180" width="432" height="160" rx="12" fill="url(#hrw)" stroke="{ink}" stroke-width="7"/>'
    )
    for y in (232, 288):
        body += f'<line x1="44" y1="{y}" x2="468" y2="{y}" stroke="{ink}" stroke-width="3" opacity=".45"/>'
    for x, y in ((62, 200), (450, 200), (62, 320), (450, 320)):
        body += f'<circle cx="{x}" cy="{y}" r="6" fill="#fde68a" stroke="{ink}" stroke-width="2"/>'
    body += _sh(fit(_w("HAYRIDE", "Rye", "#fef3c7", ink, 6, ls=4), 76, 198, 360, 124))
    rng = random.Random(9)
    straw = ""
    for _ in range(110):
        x = rng.uniform(64, 430)
        y = rng.uniform(378, 446)
        a = rng.uniform(-0.25, 0.25)
        straw += f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x + 30 * math.cos(a):.0f}" y2="{y + 30 * math.sin(a):.0f}" stroke="{rng.choice(("#facc15", "#eab308", "#fde68a"))}" stroke-width="3" stroke-linecap="round"/>'
    for x in (170, 342):
        straw += f'<rect x="{x}" y="368" width="10" height="88" fill="#7c2d12" opacity=".85"/>'
    body += f'<rect x="56" y="368" width="400" height="88" rx="16" fill="#ca8a04" stroke="{ink}" stroke-width="5"/>{straw}'
    return svg(body, d)


# ===================================================================== valentine

VALENTINE = ("valentine", "romance", "love")


def _heart(cx, cy, w, fill, edge, sw=6, rot=0):
    """A heart `w` wide with its middle at cx,cy."""
    s = w / 184
    d = (
        "M100 180 C40 136 8 104 8 64 C8 34 30 14 58 14 C78 14 92 26 100 42 "
        "C108 26 122 14 142 14 C170 14 192 34 192 64 C192 104 160 136 100 180 Z"
    )
    return (
        f'<g transform="translate({cx} {cy}) rotate({rot}) scale({s:.4f}) translate(-100 -97)">'
        f'<path d="{d}" fill="{fill}" stroke="{edge}" stroke-width="{sw / s:.1f}" stroke-linejoin="round"/></g>'
    )


@net("Love Notes", SEASONS, *VALENTINE, "music")
def love_notes():
    ink = "#4a0420"
    d = SH
    body = _panel(36, 70, 440, 372, "#fff1f2", rx=30, edge="#be185d", sw=6)
    for k in range(5):
        y = 120 + k * 22
        body += f'<line x1="70" y1="{y}" x2="442" y2="{y}" stroke="#be185d" stroke-width="3" opacity=".55"/>'
    notes = ((150, 186), (236, 164), (322, 142), (396, 186))
    for x, y in notes:
        body += _heart(x, y, 44, "#e11d48", ink, sw=4, rot=-14)
        body += f'<line x1="{x + 18}" y1="{y - 8}" x2="{x + 18}" y2="{y - 78}" stroke="{ink}" stroke-width="5" stroke-linecap="round"/>'
    body += f'<path d="M168 108 L254 86 L254 98 L168 120 Z" fill="{ink}"/>'
    body += f'<path d="M254 86 L340 64 L340 76 L254 98 Z" fill="{ink}"/>'
    body += _sh(fit(_w("Love Notes", "Great Vibes", "#be123c", "#fff1f2", 4), 64, 236, 384, 150))
    return svg(body, d)


@net("Candy Hearts", SEASONS, *VALENTINE, "kids")
def candy_hearts():
    d = SH + rough("chr", amount=2.2, freq=1.1)
    red = "#dc2626"
    body = _sh(_heart(356, 150, 170, "#fde68a", "#eab308", sw=5, rot=16))
    body += _sh(_heart(178, 210, 290, "#fbcfe8", "#f472b6", sw=6, rot=-10))
    body += _sh(_heart(330, 330, 280, "#bbf7d0", "#4ade80", sw=6, rot=8))
    word = '<g filter="url(#chr)">{}</g>'
    body += word.format(
        f'<g transform="rotate(16 356 150)">{fit(_w("XOXO", "Oswald", red, weight=700, ls=4), 316, 124, 80, 34)}</g>'
    )
    body += word.format(
        f'<g transform="rotate(-10 178 210)">{fit(_w("CANDY", "Oswald", red, weight=700, ls=6), 102, 168, 152, 58)}</g>'
    )
    body += word.format(
        f'<g transform="rotate(8 330 330)">{fit(_w("HEARTS", "Oswald", red, weight=700, ls=6), 254, 290, 152, 56)}</g>'
    )
    return svg(body, d)


@net("Cupid's Arrow", SEASONS, *VALENTINE)
def cupids_arrow():
    ink = "#3f0a1c"
    d = SH + lin("caw", [(0, "#fb7185"), (1, "#be123c")])
    body = _sh(
        fit(
            _w("CUPID’S", "Playfair Display", "url(#caw)", ink, 6, weight=900, style="italic"),
            58, 96, 396, 132,
        )
    )  # fmt: skip
    arrow = f'<line x1="58" y1="262" x2="420" y2="262" stroke="{ink}" stroke-width="14" stroke-linecap="round"/>'
    arrow += '<line x1="58" y1="262" x2="420" y2="262" stroke="#fbbf24" stroke-width="6" stroke-linecap="round"/>'
    for k in range(3):
        x = 66 + k * 22
        arrow += f'<path d="M{x} 262 l-26 -24 l22 0 l26 24 Z" fill="#fda4af" stroke="{ink}" stroke-width="3" stroke-linejoin="round"/>'
        arrow += f'<path d="M{x} 262 l-26 24 l22 0 l26 -24 Z" fill="#fb7185" stroke="{ink}" stroke-width="3" stroke-linejoin="round"/>'
    arrow += _heart(436, 262, 64, "#e11d48", ink, sw=5, rot=-90)
    body += _sh(arrow)
    body += _sh(
        fit(
            _w("ARROW", "Playfair Display", "#fdf2f8", ink, 6, weight=900, ls=16), 96, 304, 320, 108
        )
    )
    return svg(body, d)


@net("Be Mine", SEASONS, *VALENTINE, "retro")
def be_mine():
    d = (
        SH
        + lin("bmw", [(0, "#2a0a1e"), (1, "#14040e")])
        + glow("bmn", "#ff4fa3", blur=9, strength=3)
        + glow("bmh", "#ff6b8b", blur=7, strength=2)
        + '<clipPath id="bmc"><rect x="46" y="78" width="420" height="356" rx="22"/></clipPath>'
    )
    body = _panel(40, 72, 432, 368, "url(#bmw)", rx=26, edge="#000", sw=5)
    bricks = ""
    for row, y in enumerate(range(80, 440, 34)):
        for x in range(16 + (36 if row % 2 else 0), 480, 72):
            bricks += f'<rect x="{x}" y="{y}" width="66" height="28" rx="3" fill="#3b0d24" opacity=".55"/>'
    body += f'<g clip-path="url(#bmc)">{bricks}</g>'
    body += f'<g filter="url(#bmh)">{_heart(256, 166, 116, "none", "#ffd1e3", sw=7)}</g>'
    body += f'<g filter="url(#bmn)">{fit(_w("Be Mine", "Sacramento", "#ffe4f1", "#ff4fa3", 2), 76, 238, 360, 150)}</g>'
    return svg(body, d)


@net("Red Roses", SEASONS, *VALENTINE)
def red_roses():
    ink = "#3f0612"
    d = SH + rad("rrp", [(0, "#f43f5e"), (1, "#9f1239")], cx=0.45, cy=0.4, r=0.65)
    body = _sh(
        f'<circle cx="256" cy="206" r="170" fill="#fff7ed" stroke="{ink}" stroke-width="7"/>'
    )
    body += '<circle cx="256" cy="206" r="156" fill="none" stroke="#be123c" stroke-width="3"/>'
    stem = '<path d="M256 236 Q250 300 262 352" fill="none" stroke="#166534" stroke-width="12" stroke-linecap="round"/>'
    leaf = "M0 0 Q30 -26 64 -6 Q32 18 0 0 Z"
    stem += f'<path d="{leaf}" fill="#22c55e" stroke="{ink}" stroke-width="4" transform="translate(258 300) rotate(-24)"/>'
    stem += f'<path d="{leaf}" fill="#16a34a" stroke="{ink}" stroke-width="4" transform="translate(256 318) scale(-1 1) rotate(-20)"/>'
    body += stem
    rose = f'<path d="M190 170 C186 118 226 96 256 102 C292 96 330 120 322 172 C318 226 286 246 256 246 C222 246 194 226 190 170 Z" fill="url(#rrp)" stroke="{ink}" stroke-width="6"/>'
    for dd in (
        "M214 160 C220 128 248 120 270 128 C292 136 302 160 292 186",
        "M232 196 C222 170 238 150 258 152 C278 154 286 172 276 190",
        "M246 176 C246 166 256 162 264 168",
        "M200 196 C214 226 250 236 280 222",
        "M300 150 C312 176 306 206 286 224",
    ):
        rose += (
            f'<path d="{dd}" fill="none" stroke="{ink}" stroke-width="5" stroke-linecap="round"/>'
        )
    body += _sh(rose)
    body += _sh(banner(60, 452, 368, 84, "#be123c", edge=ink, sw=6, cut=24))
    body += fit(_w("RED ROSES", "Playfair Display", "#fff7ed", weight=800, ls=8), 104, 384, 304, 52)
    return svg(body, d)


@net("Box of Chocolates", SEASONS, *VALENTINE)
def box_of_chocolates():
    ink = "#2b0a0f"
    d = SH + rad("bcc", [(0, "#a16207"), (1, "#5b2c0b")], cx=0.4, cy=0.35, r=0.7)
    body = _sh(_heart(256, 196, 360, "#dc2626", ink, sw=8))
    body += _heart(256, 196, 314, "#7f1d1d", "#fca5a5", sw=3)
    spots = ((176, 130), (256, 160), (336, 130), (196, 206), (316, 206), (256, 250), (256, 108))
    for k, (x, y) in enumerate(spots):
        body += (
            f'<circle cx="{x}" cy="{y}" r="31" fill="#fde68a" stroke="#b45309" stroke-width="3"/>'
        )
        if k % 3 == 0:
            body += _heart(x, y, 40, "url(#bcc)", ink, sw=3)
        else:
            body += f'<circle cx="{x}" cy="{y}" r="22" fill="url(#bcc)" stroke="{ink}" stroke-width="3"/>'
            body += f'<path d="M{x - 12} {y - 4} q6 -8 12 0 t12 0" fill="none" stroke="#fde68a" stroke-width="3" stroke-linecap="round"/>'
    body += _sh(
        fit(
            _w("BOX OF", "Playfair Display", "#fff1f2", ink, 6, weight=900, ls=10),
            156,
            352,
            200,
            44,
        )
    )
    body += _sh(
        fit(
            _w("CHOCOLATES", "Playfair Display", "#fff1f2", ink, 7, weight=900, ls=2),
            46,
            400,
            420,
            70,
        )
    )
    return svg(body, d)


@net("Puppy Love", SEASONS, *VALENTINE, "kids", "pets")
def puppy_love():
    ink = "#4a0420"
    d = SH + lin("plb", [(0, "#fbcfe8"), (1, "#f9a8d4")])
    body = _panel(40, 56, 432, 400, "url(#plb)", rx=200, edge=ink, sw=6)
    paw = _heart(256, 196, 110, "#e11d48", ink, sw=5)
    for x, y, rx, ry, rot in (
        (186, 120, 22, 30, -24),
        (232, 94, 22, 30, -8),
        (280, 94, 22, 30, 8),
        (326, 120, 22, 30, 24),
    ):
        paw += f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="#e11d48" stroke="{ink}" stroke-width="5" transform="rotate({rot} {x} {y})"/>'
    body += _sh(paw)
    body += _sh(fit(_w("Puppy Love", "Pacifico", "#fff", ink, 10), 74, 268, 364, 120))
    return svg(body, d)


def logos() -> list[Logo]:
    return [Logo(i, name, cat, fn, tags) for i, name, cat, tags, fn in SEASON_LOGOS]
