"""Cartoon, anime and teen channels: invented brands in the style of real
animation and youth networks. Nothing here borrows a real channel's,
studio's or show's name, character, symbol or lettering."""

from __future__ import annotations

import math
import random
import re

import layouts as L
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
    shadow,
    star,
    svg,
    text,
    tilt,
)
from symbols import P, centred

SH = shadow("sh", dy=6, blur=6, opacity=0.45)
TOONS = "Cartoons & anime"
TEENS = "Teens"
STATIONS: list[tuple[str, str, str, list[str], object]] = []  # (id, name, category, tags, draw)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", "and")).strip("-")


def net(name: str, category: str, *tags: str):
    def add(fn):
        STATIONS.append((slug(name), name, category, list(tags), fn))
        return fn

    return add


# ======================================================================= helpers


def _panel(x, y, w, h, fill, rx=18, edge=None, sw=0):
    st = f' stroke="{edge}" stroke-width="{sw}"' if edge else ""
    return f'<g filter="url(#sh)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{st}/></g>'


def _x(
    word, font, fill, edge, dx=5, dy=7, steps=8, sw=14, weight=400, style="normal", ls=0, ex=None
):
    """A word with a solid block extrusion behind it."""
    t = text(word, font, 100, weight=weight, fill=fill, stroke=edge, sw=sw, style=style, ls=ls)
    return extrude(t, dx, dy, steps, ex or edge) + t


def _letters(word, font, fills, edge, sw=12, weight=400, bounce=6.0, rot=0.0, gap=0.0, scales=None):
    """A word set letter by letter: each its own colour, bouncing up and down."""
    out, x = "", 0.0
    for i, ch in enumerate(word):
        adv, _ = measure(ch, font, weight)
        if ch == " ":
            x += adv + gap
            continue
        dy = -bounce if i % 2 else bounce
        r = -rot if i % 2 else rot
        sc = f" scale({scales[i]})" if scales else ""
        out += (
            f'<g transform="translate({x + adv / 2:.1f} {dy:.1f}) rotate({r}){sc}">'
            + text(ch, font, 100, weight=weight, fill=fills[i % len(fills)], stroke=edge, sw=sw)
            + "</g>"
        )
        x += adv + gap
    return out


def _bulbs(points, r=7, fill="#fff3b0", edge="#8a5a00"):
    return "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{edge}" stroke-width="1.5"/>'
        for x, y in points
    )


def _halftone(pid, fill, dot, size=14, r=3.4):
    return (
        f"<pattern id='{pid}' width='{size}' height='{size}' patternUnits='userSpaceOnUse'>"
        f"<rect width='{size}' height='{size}' fill='{fill}'/><circle cx='{size / 2}' cy='{size / 2}' r='{r}' fill='{dot}'/></pattern>"
    )


# ======================================================================= drawings (200x200 box)


def pie_eye(p: P, look=(10, 22)) -> str:
    """A tall cartoon eye with a pie-cut pupil."""
    lx, ly = look
    s = f'<ellipse cx="100" cy="100" rx="62" ry="92" fill="{p.l}" stroke="{p.k}" stroke-width="8"/>'
    s += f'<clipPath id="pu{lx}{ly}"><ellipse cx="{100 + lx}" cy="{100 + ly}" rx="30" ry="46"/></clipPath>'
    s += f'<ellipse cx="{100 + lx}" cy="{100 + ly}" rx="30" ry="46" fill="{p.k}"/>'
    cx, cy = 100 + lx, 100 + ly
    a1, a2 = math.radians(-78), math.radians(-38)
    s += f'<polygon points="{cx},{cy} {cx + 70 * math.cos(a1):.1f},{cy + 70 * math.sin(a1):.1f} {cx + 70 * math.cos(a2):.1f},{cy + 70 * math.sin(a2):.1f}" fill="{p.l}" clip-path="url(#pu{lx}{ly})"/>'
    s += '<path d="M58 44 Q76 22 104 20" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity=".7"/>'
    return s


def inkpot(p: P) -> str:
    s = f'<rect x="72" y="8" width="56" height="30" rx="6" fill="{p.b}" stroke="{p.k}" stroke-width="6"/>'
    s += f'<path d="M78 36 L122 36 L126 56 Q176 60 184 100 L184 168 Q184 192 160 192 L40 192 Q16 192 16 168 L16 100 Q24 60 74 56 Z" fill="{p.a}" stroke="{p.k}" stroke-width="7" stroke-linejoin="round"/>'
    s += '<path d="M34 104 Q40 76 70 70" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round" opacity=".35"/>'
    return s


def bomb(p: P) -> str:
    s = f'<path d="M126 44 Q150 10 176 22" fill="none" stroke="{p.b}" stroke-width="9" stroke-linecap="round"/>'
    s += f'<rect x="104" y="40" width="40" height="30" rx="5" fill="{p.a}" stroke="{p.k}" stroke-width="6" transform="rotate(36 124 55)"/>'
    s += f'<circle cx="92" cy="116" r="72" fill="{p.a}" stroke="{p.k}" stroke-width="7"/>'
    s += '<path d="M50 96 Q56 66 86 56" fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" opacity=".45"/>'
    s += f'<polygon points="{star(178, 20, 22, 9, 8)}" fill="{p.c}" stroke="{p.k}" stroke-width="3"/>'
    return s


def skate(p: P) -> str:
    """A quad roller skate, side on."""
    s = f'<path d="M40 30 L100 30 L104 104 Q150 104 172 124 Q186 136 184 150 L30 150 Q22 150 24 140 Z" fill="{p.a}" stroke="{p.k}" stroke-width="7" stroke-linejoin="round"/>'
    s += f'<path d="M40 30 L100 30 L100 44 L42 44 Z" fill="{p.l}" stroke="{p.k}" stroke-width="5"/>'
    for y in (62, 80, 98):
        s += f'<line x1="70" y1="{y}" x2="96" y2="{y - 6}" stroke="{p.l}" stroke-width="5" stroke-linecap="round"/>'
    s += f'<path d="M26 128 L184 128" stroke="{p.b}" stroke-width="10"/>'
    s += f'<rect x="30" y="150" width="148" height="12" rx="4" fill="{p.k}"/>'
    for cx in (58, 150):
        s += f'<circle cx="{cx}" cy="172" r="22" fill="{p.c}" stroke="{p.k}" stroke-width="6"/><circle cx="{cx}" cy="172" r="7" fill="{p.l}"/>'
    s += (
        f'<ellipse cx="186" cy="140" rx="10" ry="12" fill="{p.b}" stroke="{p.k}" stroke-width="5"/>'
    )
    return s


# ======================================================================= classic cartoons


@net("Rubber Hose", TOONS, "cartoons", "classic cartoons", "animation")
def rubber_hose():
    ink = "#1a1210"
    d = SH + rad("rh", [(0, "#fff6e0"), (0.65, "#f0dcab"), (1, "#c99a57")], r=0.62)
    body = f'<g filter="url(#sh)"><circle cx="256" cy="226" r="206" fill="{ink}"/>'
    body += '<circle cx="256" cy="226" r="192" fill="url(#rh)"/></g>'
    for k in range(24):
        a = math.radians(k * 15)
        body += f'<line x1="{256 + 60 * math.cos(a):.0f}" y1="{226 + 60 * math.sin(a):.0f}" x2="{256 + 186 * math.cos(a):.0f}" y2="{226 + 186 * math.sin(a):.0f}" stroke="#c99a57" stroke-width="10" opacity=".25"/>'
    body += f'<circle cx="256" cy="226" r="176" fill="none" stroke="{ink}" stroke-width="3" opacity=".5"/>'
    top = _letters("RUBBER", "Chango", ["#d8452e"], ink, sw=14, bounce=5, rot=4)
    bot = _letters("HOSE", "Chango", ["#d8452e"], ink, sw=14, bounce=5, rot=-4)
    body += f'<g filter="url(#sh)">{fit(extrude(top, 4, 6, 6, ink) + top, 84, 96, 344, 112)}</g>'
    body += f'<g filter="url(#sh)">{fit(extrude(bot, 4, 6, 6, ink) + bot, 124, 210, 264, 112)}</g>'
    body += '<g filter="url(#sh)">' + banner(40, 472, 352, 70, ink, "#f0dcab", 5, cut=20) + "</g>"
    body += fit(
        text("CLASSIC CARTOONS", "Oswald", 40, weight=700, fill="#f0dcab", ls=10), 116, 368, 280, 38
    )
    return svg(body, d)


@net("Pie-Eyed", TOONS, "cartoons", "classic cartoons", "black and white")
def pie_eyed():
    cream, ink = "#f6ecd4", "#141110"
    d = SH + rad("pe", [(0, "#3a3430"), (1, "#0d0b0a")], r=0.7)
    body = _panel(28, 36, 456, 440, "url(#pe)", rx=34, edge="#000", sw=6)
    body += f'<rect x="46" y="54" width="420" height="404" rx="22" fill="none" stroke="{cream}" stroke-width="4"/>'
    body += f'<rect x="56" y="64" width="400" height="384" rx="16" fill="none" stroke="{cream}" stroke-width="1.5" opacity=".7"/>'
    eye = pie_eye(P(l=cream, k=ink), look=(12, 26))
    body += f'<g filter="url(#sh)">{centred(eye, 206, 176, 196)}{centred(eye, 306, 176, 196)}</g>'
    body += f'<path d="M150 70 Q196 50 236 74" fill="none" stroke="{cream}" stroke-width="9" stroke-linecap="round"/>'
    body += f'<path d="M276 74 Q316 50 362 70" fill="none" stroke="{cream}" stroke-width="9" stroke-linecap="round"/>'
    w = _x("PIE-EYED", "Shrikhand", cream, ink, dx=5, dy=7, ex="#c8342b", sw=10)
    body += f'<g filter="url(#sh)">{fit(tilt(w, -4), 60, 296, 392, 112)}</g>'
    body += fit(
        text("CLASSIC CARTOONS", "Oswald", 40, weight=600, fill=cream, ls=8), 150, 414, 212, 22
    )
    return svg(body, d)


@net("Before the Feature", TOONS, "cartoons", "classic cartoons", "shorts")
def before_the_feature():
    d = (
        SH
        + lin(
            "cu",
            [
                (0, "#5e0b14"),
                (0.25, "#b3182a"),
                (0.5, "#6e0c18"),
                (0.75, "#c21d31"),
                (1, "#5e0b14"),
            ],
            x2=1,
            y2=0,
        )
        + "<pattern id='fold' width='44' height='10' patternUnits='userSpaceOnUse'><rect width='44' height='10' fill='url(#cu)'/></pattern>"
        + rad("scr", [(0, "#fbf8ee"), (0.7, "#dcd7c7"), (1, "#8f8a7a")], r=0.7)
        + lin("gd", [(0, "#fff0b8"), (0.5, "#e2b54a"), (1, "#a8741c")])
        + lin("wd", [(0, "#5a3a1e"), (1, "#2c1a0c")])
    )
    body = _panel(24, 34, 464, 444, "#1c0508", rx=22)
    body += '<rect x="92" y="104" width="328" height="244" fill="url(#scr)" stroke="#0d0204" stroke-width="6"/>'
    for i in range(3):
        body += f'<line x1="{140 + i * 110}" y1="104" x2="{150 + i * 108}" y2="348" stroke="#8f8a7a" stroke-width="1.5" opacity=".35"/>'
    body += '<path d="M24 60 Q24 34 50 34 L112 34 L112 300 Q86 350 100 470 L50 470 Q24 470 24 444 Z" fill="url(#fold)" stroke="#0d0204" stroke-width="5"/>'
    body += '<path d="M488 60 Q488 34 462 34 L400 34 L400 300 Q426 350 412 470 L462 470 Q488 470 488 444 Z" fill="url(#fold)" stroke="#0d0204" stroke-width="5"/>'
    body += '<rect x="24" y="34" width="464" height="62" fill="url(#fold)" stroke="#0d0204" stroke-width="5"/>'
    body += (
        '<path d="M24 96 '
        + " ".join(f"Q{24 + 29 * (2 * k + 1)} 128 {24 + 58 * (k + 1)} 96" for k in range(8))
        + ' Z" fill="url(#fold)" stroke="#0d0204" stroke-width="5"/>'
    )
    body += (
        '<path d="M24 96 '
        + " ".join(f"Q{24 + 29 * (2 * k + 1)} 128 {24 + 58 * (k + 1)} 96" for k in range(8))
        + '" fill="none" stroke="url(#gd)" stroke-width="5"/>'
    )
    body += '<rect x="24" y="92" width="464" height="8" fill="url(#gd)"/>'
    for x in (104, 408):
        body += f'<path d="M{x - 18} 300 Q{x} 290 {x + 18} 300 L{x + 12} 316 Q{x} 322 {x - 12} 316 Z" fill="url(#gd)" stroke="#3a2006" stroke-width="3"/>'
    body += '<rect x="24" y="382" width="464" height="96" fill="url(#wd)" stroke="#0d0204" stroke-width="5"/>'
    body += '<rect x="24" y="382" width="464" height="10" fill="url(#gd)"/>'
    body += fit(tilt(text("Before the", "Great Vibes", 100, fill="#2a2622"), -4), 150, 124, 212, 72)
    body += fit(text("FEATURE", "Limelight", 100, fill="#1a1715"), 118, 206, 276, 110)
    body += '<line x1="150" y1="326" x2="362" y2="326" stroke="#1a1715" stroke-width="3"/>'
    body += fit(
        text("CARTOON SHORTS", "Oswald", 40, weight=700, fill="url(#gd)", ls=8), 110, 406, 292, 46
    )
    return svg(body, d)


@net("Ink & Paint", TOONS, "cartoons", "classic cartoons", "animation")
def ink_and_paint():
    ink = "#15110f"
    d = (
        SH
        + lin("pg", [(0, "#fffaf0"), (1, "#efe2c2")])
        + lin("bar", [(0, "#e8ebef"), (0.5, "#8d949c"), (1, "#c9ced4")])
        + lin("gl", [(0, "#4a4440"), (0.45, "#15110f"), (1, "#000")])
    )
    body = '<g filter="url(#sh)"><rect x="34" y="62" width="444" height="410" rx="10" fill="url(#pg)" stroke="#6b5a3a" stroke-width="3"/></g>'
    body += '<circle cx="256" cy="94" r="14" fill="#6b5a3a" opacity=".6"/><rect x="118" y="86" width="56" height="16" rx="8" fill="#6b5a3a" opacity=".6"/><rect x="338" y="86" width="56" height="16" rx="8" fill="#6b5a3a" opacity=".6"/>'
    body += '<g filter="url(#sh)"><rect x="70" y="30" width="372" height="40" rx="8" fill="url(#bar)" stroke="#2a2e33" stroke-width="5"/>'
    body += '<circle cx="256" cy="80" r="12" fill="url(#bar)" stroke="#2a2e33" stroke-width="4"/><rect x="124" y="72" width="44" height="16" rx="8" fill="url(#bar)" stroke="#2a2e33" stroke-width="4"/><rect x="344" y="72" width="44" height="16" rx="8" fill="url(#bar)" stroke="#2a2e33" stroke-width="4"/></g>'
    adv, _ = measure("INK", "Alfa Slab One")
    drips = ""
    for fx, ln in ((0.14, 26), (0.52, 40), (0.86, 20)):
        x = -adv / 2 + fx * adv
        drips += f'<path d="M{x - 7:.1f} -4 L{x - 7:.1f} {ln} A7 7 0 0 0 {x + 7:.1f} {ln} L{x + 7:.1f} -4 Z" fill="url(#gl)"/>'
    word = text("INK", "Alfa Slab One", 100, fill="url(#gl)") + drips
    word += text(
        "INK", "Alfa Slab One", 100, fill="none", stroke="#fff", sw=2, extra='opacity=".25"'
    )
    body += f'<g filter="url(#sh)">{fit(word, 136, 118, 240, 148)}</g>'
    paint = _letters(
        "& PAINT",
        "Alfa Slab One",
        ["#15110f", "#d8452e", "#f2a922", "#2f9e8f", "#2f6fc4", "#8e44ad"],
        ink,
        sw=8,
        bounce=3,
        rot=3,
        gap=2,
    )
    body += f'<g filter="url(#sh)">{fit(paint, 70, 288, 372, 108)}</g>'
    body += fit(
        text("THE CARTOON DEPARTMENT", "Oswald", 40, weight=600, fill="#6b5a3a", ls=5),
        128,
        420,
        256,
        22,
    )
    return svg(body, d)


@net("Squash & Stretch", TOONS, "cartoons", "classic cartoons", "animation")
def squash_and_stretch():
    cream, ink, red = "#f4e6c4", "#17120e", "#d8452e"
    d = (
        SH
        + rad("ss", [(0, "#3b2c20"), (1, "#15100c")], r=0.75)
        + rad("ball", [(0, "#ff8a6e"), (0.5, red), (1, "#8e1f12")], cx=0.35, cy=0.3, r=0.75)
    )
    body = _panel(28, 30, 456, 452, "url(#ss)", rx=34, edge="#000", sw=6)
    body += f'<rect x="46" y="48" width="420" height="416" rx="22" fill="none" stroke="{cream}" stroke-width="3" opacity=".6"/>'
    flat = f'<g transform="scale(1.3 .74)">{text("SQUASH", "Titan One", 100, fill=cream, stroke=ink, sw=10)}</g>'
    body += f'<g filter="url(#sh)">{fit(flat, 58, 70, 396, 104)}</g>'
    body += fit(text("&", "Titan One", 100, fill=red, stroke=ink, sw=8), 150, 190, 64, 50)
    tall = f'<g transform="scale(.74 1.36)">{text("STRETCH", "Titan One", 100, fill=cream, stroke=ink, sw=10)}</g>'
    body += f'<g filter="url(#sh)">{fit(tall, 58, 196, 396, 214)}</g>'
    body += f'<line x1="60" y1="424" x2="452" y2="424" stroke="{cream}" stroke-width="5" stroke-linecap="round"/>'
    return svg(body, d)


@net("Frame by Frame", TOONS, "cartoons", "classic cartoons", "animation")
def frame_by_frame():
    ink = "#1a120c"
    d = (
        SH
        + lin("fr", [(0, "#e9c889"), (1, "#b98a45")])
        + lin("fw", [(0, "#fff6dc"), (1, "#f0d69c")])
    )
    body = '<g filter="url(#sh)"><rect x="70" y="18" width="372" height="476" rx="14" fill="#17110c"/></g>'
    for y in range(30, 486, 30):
        body += f'<rect x="82" y="{y}" width="20" height="16" rx="4" fill="#f6e7c1"/><rect x="410" y="{y}" width="20" height="16" rx="4" fill="#f6e7c1"/>'
    frames = ((116, 34, 176), (116, 220, 72), (116, 302, 176))
    for x, y, h in frames:
        body += f'<rect x="{x}" y="{y}" width="280" height="{h}" rx="8" fill="url(#fr)" stroke="#3a2412" stroke-width="3"/>'
    w = _x("FRAME", "Bevan", "url(#fw)", ink, dx=4, dy=6, sw=10, ex="#5a3616")
    body += fit(w, 130, 62, 252, 120)
    body += fit(w, 130, 330, 252, 120)
    body += fit(text("BY", "Bevan", 100, fill=ink), 216, 234, 80, 44)
    for x, y, t in ((130, 44, "01"), (130, 230, "02"), (130, 312, "03")):
        body += text(t, "Oswald", 16, weight=700, fill="#5a3616", x=x + 8, y=y + 14)
    return svg(body, d)


@net("Funny Pages", TOONS, "cartoons", "classic cartoons", "comics")
def funny_pages():
    ink = "#141414"
    d = (
        SH
        + _halftone("ht", "#ffe58a", "#f28c28", 16, 4)
        + _halftone("ht2", "#bfe3f2", "#4a9fd8", 12, 3)
    )
    body = '<g filter="url(#sh)" transform="rotate(-4 256 256)"><rect x="34" y="44" width="444" height="424" rx="6" fill="#f3ead2" stroke="#141414" stroke-width="7"/></g>'
    body += '<g transform="rotate(-4 256 256)">'
    body += f'<rect x="52" y="62" width="200" height="120" fill="url(#ht)" stroke="{ink}" stroke-width="5"/><rect x="266" y="62" width="194" height="120" fill="url(#ht2)" stroke="{ink}" stroke-width="5"/>'
    body += f'<rect x="52" y="196" width="408" height="254" fill="#ffd0c4" stroke="{ink}" stroke-width="5"/>'
    body += "</g>"
    bubble = '<path d="M256 96 C400 96 480 150 480 230 C480 312 396 356 290 360 L230 430 L236 358 C120 350 32 306 32 230 C32 150 112 96 256 96 Z" fill="#fff" stroke="#141414" stroke-width="9" stroke-linejoin="round"/>'
    body += f'<g filter="url(#sh)">{bubble}</g>'
    body += f'<g filter="url(#sh)">{fit(_x("FUNNY", "Bowlby One", "#e63946", ink, dx=3, dy=5, sw=10), 96, 130, 320, 104)}</g>'
    body += f'<g filter="url(#sh)">{fit(_x("PAGES", "Bowlby One", "#1d5fd0", ink, dx=3, dy=5, sw=10), 104, 240, 304, 96)}</g>'
    body += f'<polygon points="{star(424, 420, 48, 24, 10)}" fill="#ffd23f" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>'
    body += text("HA!", "Bangers", 34, fill=ink, x=424, y=432)
    return svg(body, d)


@net("Short Subjects", TOONS, "cartoons", "classic cartoons", "shorts")
def short_subjects():
    cream, ink = "#f3ecdc", "#141414"
    d = (
        SH
        + rad("sc", [(0, "#8a8a86"), (0.8, "#3a3a38"), (1, "#1c1c1b")], r=0.75)
        + rad("ld", [(0, "#fbf7ec"), (1, "#c9c3b2")])
    )
    body = _panel(24, 58, 464, 396, "url(#sc)", rx=24, edge="#000", sw=6)
    rng = random.Random(4)
    for _ in range(7):
        x = rng.uniform(50, 460)
        body += f'<line x1="{x:.0f}" y1="70" x2="{x + rng.uniform(-6, 6):.0f}" y2="440" stroke="#fff" stroke-width="1.2" opacity=".18"/>'
    lx = 210
    leader = f'<circle cx="0" cy="-36" r="46" fill="url(#ld)" stroke="{ink}" stroke-width="8"/>'
    leader += '<path d="M0 -36 L0 -82 A46 46 0 0 1 43.7 -50.2 Z" fill="#6f6a5e" opacity=".55"/>'
    leader += f'<circle cx="0" cy="-36" r="34" fill="none" stroke="{ink}" stroke-width="3"/><line x1="-46" y1="-36" x2="46" y2="-36" stroke="{ink}" stroke-width="3"/><line x1="0" y1="-82" x2="0" y2="10" stroke="{ink}" stroke-width="3"/>'
    leader += text("3", "Oswald", 50, weight=700, fill=ink, y=-18)
    w_l = text("SH", "Bevan", 100, fill=cream, stroke=ink, sw=10, anchor="end", x=-50)
    w_r = text("RT", "Bevan", 100, fill=cream, stroke=ink, sw=10, anchor="start", x=50)
    body += f'<g filter="url(#sh)">{fit(w_l + leader + w_r, 56, 104, 400, 150)}</g>'
    body += f'<rect x="64" y="{lx + 70}" width="384" height="6" fill="{cream}"/>'
    body += fit(text("SUBJECTS", "Oswald", 100, weight=700, fill=cream, ls=14), 80, 300, 352, 80)
    body += f'<rect x="64" y="394" width="384" height="3" fill="{cream}"/>'
    body += fit(
        text("CARTOONS · NEWSREELS · SERIALS", "Oswald", 30, weight=500, fill=cream, ls=3),
        110,
        406,
        292,
        20,
    )
    return svg(body, d)


@net("Cel Block", TOONS, "cartoons", "classic cartoons")
def cel_block():
    ink = "#15171a"
    d = SH + lin("cel", [(0, "#e0f4fa"), (1, "#9ccfe0")], x2=1, y2=1)
    body = ""
    for i, (dx, dy, op) in enumerate(((-36, -30, 0.45), (-18, -15, 0.65), (0, 0, 1))):
        body += f'<g filter="url(#sh)" transform="translate({dx} {dy})"><rect x="72" y="104" width="388" height="300" rx="10" fill="url(#cel)" fill-opacity="{op}" stroke="#1d3a44" stroke-width="5"/></g>'
        body += f'<g transform="translate({dx} {dy})"><circle cx="266" cy="124" r="9" fill="#1d3a44" opacity=".7"/><rect x="170" y="117" width="40" height="14" rx="7" fill="#1d3a44" opacity=".7"/><rect x="322" y="117" width="40" height="14" rx="7" fill="#1d3a44" opacity=".7"/></g>'
    body += '<path d="M86 150 L210 150 L96 380 L86 380 Z" fill="#fff" opacity=".35"/>'
    w = text("CEL", "Black Ops One", 100, fill="#f28c28", stroke=ink, sw=10)
    body += f'<g filter="url(#sh)">{fit(extrude(w, 0, 8, 6, ink) + w, 110, 160, 292, 104)}</g>'
    w2 = text("BLOCK", "Black Ops One", 100, fill=ink)
    body += fit(w2, 110, 280, 292, 74)
    body += fit(
        text("CEL No. 001", "Oswald", 40, weight=600, fill="#1d3a44", ls=6), 330, 372, 110, 20
    )
    return svg(body, d)


@net("Inkpot", TOONS, "cartoons", "classic cartoons")
def inkpot_logo():
    ink = "#120e0c"
    d = (
        SH
        + rad("ip", [(0, "#fff3d6"), (0.7, "#e8cf9c"), (1, "#b98a45")], r=0.62)
        + lin("gl", [(0, "#3a3f58"), (0.4, "#12131c"), (1, "#000")], x2=1, y2=0.4)
        + lin("lb", [(0, "#fffaf0"), (1, "#f1dfb6")])
    )
    body = f'<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="{ink}"/><circle cx="256" cy="256" r="218" fill="url(#ip)"/></g>'
    body += '<g filter="url(#sh)"><g transform="rotate(24 330 150)"><rect x="318" y="20" width="22" height="150" rx="8" fill="#a33b20" stroke="#120e0c" stroke-width="5"/><rect x="316" y="150" width="26" height="22" fill="#d9b25a" stroke="#120e0c" stroke-width="4"/><path d="M318 172 L340 172 L329 214 Z" fill="#c9ced4" stroke="#120e0c" stroke-width="4" stroke-linejoin="round"/></g></g>'
    bottle = inkpot(P(a="url(#gl)", b="#6b4a2a", k=ink))
    body += f'<g filter="url(#sh)">{fit(bottle, 70, 120, 372, 350)}</g>'
    body += '<g filter="url(#sh)"><rect x="96" y="286" width="320" height="120" rx="10" fill="url(#lb)" stroke="#120e0c" stroke-width="5"/></g>'
    body += '<rect x="106" y="296" width="300" height="100" rx="6" fill="none" stroke="#c8342b" stroke-width="3"/>'
    body += '<path d="M150 286 L150 312 A8 8 0 0 0 166 312 L166 286 Z M330 286 L330 302 A8 8 0 0 0 346 302 L346 286 Z" fill="#12131c"/>'
    body += fit(text("INKPOT", "Ultra", 100, fill=ink), 120, 316, 272, 68)
    return svg(body, d)


@net("Toon Parade", TOONS, "cartoons", "classic cartoons", "kids")
def toon_parade():
    ink = "#1d1410"
    d = (
        SH
        + lin("bn", [(0, "#e0533a"), (1, "#a82a1c")])
        + lin("gd", [(0, "#fff0b8"), (0.5, "#e2b54a"), (1, "#a8741c")])
        + lin("pole", [(0, "#8a5a2a"), (0.5, "#e2b077"), (1, "#6b4020")], x2=1, y2=0)
    )
    rng = random.Random(8)
    conf = ""
    for _ in range(26):
        x, y = rng.uniform(30, 480), rng.uniform(20, 490)
        if 60 < x < 452 and 90 < y < 420:
            continue
        c = rng.choice(["#e0533a", "#3f9e8f", "#f2c14e", "#f6ecd4"])
        conf += f'<rect x="{x:.0f}" y="{y:.0f}" width="14" height="8" rx="2" fill="{c}" transform="rotate({rng.uniform(0, 180):.0f} {x:.0f} {y:.0f})"/>'
    body = conf
    body += '<g filter="url(#sh)">'
    for x in (46, 466):
        body += f'<rect x="{x - 10}" y="60" width="20" height="430" rx="8" fill="url(#pole)" stroke="{ink}" stroke-width="5"/>'
        body += f'<circle cx="{x}" cy="50" r="20" fill="url(#gd)" stroke="{ink}" stroke-width="5"/>'
    ban = (
        "M60 90 L452 90 L452 380 "
        + " ".join(f"Q{452 - 24 * (2 * k + 1)} 418 {452 - 49 * (k + 1)} 380" for k in range(8))
        + " Z"
    )
    body += (
        f'<path d="{ban}" fill="url(#bn)" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>'
    )
    body += f'<rect x="40" y="80" width="432" height="22" rx="10" fill="url(#gd)" stroke="{ink}" stroke-width="5"/>'
    body += "</g>"
    body += '<rect x="80" y="116" width="352" height="248" rx="10" fill="none" stroke="#f6ecd4" stroke-width="4"/>'
    for k in range(8):
        body += f'<circle cx="{452 - 24 * (2 * k + 1):.0f}" cy="402" r="7" fill="url(#gd)" stroke="{ink}" stroke-width="3"/>'
    body += f'<g filter="url(#sh)">{fit(_x("TOON", "Carter One", "#f6ecd4", ink, sw=12), 132, 128, 248, 110)}</g>'
    body += f'<g filter="url(#sh)">{fit(_x("PARADE", "Carter One", "#f2c14e", ink, sw=12), 100, 240, 312, 110)}</g>'
    return svg(body, d)


@net("Cartoon Carnival", TOONS, "cartoons", "classic cartoons", "kids")
def cartoon_carnival():
    ink = "#1d1410"
    d = (
        SH
        + lin("sg", [(0, "#fff7e0"), (1, "#f1dcae")])
        + lin("fr", [(0, "#e0533a"), (1, "#a82a1c")])
    )
    body = ""
    cx, cy, r = 256, 200, 180
    wheel = f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#2f8f86" stroke-width="10"/><circle cx="{cx}" cy="{cy}" r="{r - 26}" fill="none" stroke="#2f8f86" stroke-width="5"/>'
    for k in range(16):
        a = math.radians(k * 22.5)
        wheel += f'<line x1="{cx}" y1="{cy}" x2="{cx + r * math.cos(a):.1f}" y2="{cy + r * math.sin(a):.1f}" stroke="#2f8f86" stroke-width="4"/>'
    for k in range(8):
        a = math.radians(k * 45 + 22.5)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        wheel += f'<path d="M{x - 18:.1f} {y + 4:.1f} L{x + 18:.1f} {y + 4:.1f} L{x + 14:.1f} {y + 30:.1f} L{x - 14:.1f} {y + 30:.1f} Z" fill="{["#e0533a", "#f2c14e"][k % 2]}" stroke="{ink}" stroke-width="4"/><line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y + 6:.1f}" stroke="{ink}" stroke-width="4"/>'
    wheel += _bulbs(
        [
            (cx + r * math.cos(math.radians(k * 15)), cy + r * math.sin(math.radians(k * 15)))
            for k in range(24)
        ],
        r=5,
    )
    body += f'<g filter="url(#sh)">{wheel}</g>'
    body += f'<polygon points="{cx - 20},{cy} {cx - 110},470 {cx - 84},470" fill="#2f8f86" stroke="{ink}" stroke-width="4"/><polygon points="{cx + 20},{cy} {cx + 110},470 {cx + 84},470" fill="#2f8f86" stroke="{ink}" stroke-width="4"/>'
    body += f'<circle cx="{cx}" cy="{cy}" r="16" fill="#f2c14e" stroke="{ink}" stroke-width="5"/>'
    sign = "M40 250 Q256 150 472 250 L472 440 L40 440 Z"
    body += f'<g filter="url(#sh)"><path d="{sign}" fill="url(#fr)" stroke="{ink}" stroke-width="7"/></g>'
    body += '<path d="M62 262 Q256 176 450 262 L450 420 L62 420 Z" fill="url(#sg)" stroke="#1d1410" stroke-width="4"/>'
    pts_ = []
    for k in range(17):
        t = k / 16
        x = 40 + 432 * t
        y = (1 - t) ** 2 * 250 + 2 * (1 - t) * t * 150 + t**2 * 250
        pts_.append((x, y + 1))
    body += _bulbs(pts_[1:-1], r=6)
    a_defs, a_body = arc_text(
        "CARTOON", "Carter One", 256, 566, 290, 60, fill="#a82a1c", ls=4, pid="cc", start=50
    )
    d += a_defs
    body += a_body
    body += f'<g filter="url(#sh)">{fit(_x("CARNIVAL", "Carter One", "#2f8f86", ink, dx=3, dy=5, sw=10), 80, 318, 352, 94)}</g>'
    return svg(body, d)


# ======================================================================= saturday-morning & slapstick


@net("Cereal Bowl", TOONS, "cartoons", "saturday morning", "kids")
def cereal_bowl():
    ink = "#1e1b4b"
    d = SH + lin("box", [(0, "#facc15"), (1, "#f59e0b")])
    body = (
        '<g filter="url(#sh)"><path d="M108 40 L404 40 L424 60 L424 472 L88 472 L88 60 Z" fill="url(#box)" stroke="'
        + ink
        + '" stroke-width="8" stroke-linejoin="round"/></g>'
    )
    body += f'<path d="M108 40 L404 40 L424 60 L88 60 Z" fill="#fde68a" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>'
    body += '<rect x="88" y="300" width="336" height="172" fill="#2563eb"/>'
    body += f'<path d="M88 300 Q256 270 424 300" fill="none" stroke="{ink}" stroke-width="6"/>'
    body += f'<path d="M150 360 Q256 470 362 360 Z" fill="#fff" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/>'
    rng = random.Random(3)
    for _ in range(14):
        x, y = rng.uniform(166, 346), rng.uniform(332, 362)
        c = rng.choice(("#ef4444", "#22c55e", "#f97316", "#a855f7", "#facc15"))
        body += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="13" fill="{c}" stroke="{ink}" stroke-width="4"/><circle cx="{x:.0f}" cy="{y:.0f}" r="4" fill="{ink}" opacity=".5"/>'
    top = _letters(
        "CEREAL",
        "Luckiest Guy",
        ["#ef4444", "#2563eb", "#16a34a", "#ef4444", "#2563eb", "#16a34a"],
        ink,
        sw=14,
        bounce=5,
        rot=4,
    )
    body += f'<g filter="url(#sh)">{fit(top, 104, 84, 304, 98)}</g>'
    bot = _letters("BOWL", "Luckiest Guy", ["#fff"], ink, sw=14, bounce=5, rot=-4)
    body += f'<g filter="url(#sh)">{fit(bot, 156, 186, 200, 92)}</g>'
    body += f'<g filter="url(#sh)"><polygon points="{star(392, 300, 52, 36, 12)}" fill="#ef4444" stroke="{ink}" stroke-width="5"/></g>'
    body += fit(text("TOONS", "Luckiest Guy", 100, fill="#fff"), 362, 288, 60, 24)
    return svg(body, d)


@net("Couch Fort", TOONS, "cartoons", "kids", "saturday morning")
def couch_fort():
    ink = "#3b0764"
    d = (
        SH
        + lin("cush", [(0, "#c084fc"), (1, "#7e22ce")])
        + lin("cush2", [(0, "#f9a8d4"), (1, "#db2777")])
    )
    body = '<g filter="url(#sh)">'
    body += f'<rect x="40" y="176" width="432" height="250" rx="40" fill="url(#cush)" stroke="{ink}" stroke-width="8"/>'
    for x in (74, 214, 354):
        body += f'<rect x="{x}" y="122" width="84" height="84" rx="16" fill="url(#cush2)" stroke="{ink}" stroke-width="7"/>'
    body += "</g>"
    for x in (116, 256, 396):
        body += f'<circle cx="{x}" cy="164" r="5" fill="{ink}" opacity=".5"/>'
    body += f'<line x1="256" y1="122" x2="256" y2="50" stroke="{ink}" stroke-width="7" stroke-linecap="round"/>'
    body += f'<path d="M260 52 L326 66 L260 84 Z" fill="#facc15" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>'
    for x, y in ((120, 250), (256, 250), (392, 250), (188, 340), (324, 340)):
        body += f'<circle cx="{x}" cy="{y}" r="5" fill="{ink}" opacity=".35"/>'
    w = _x("COUCH FORT", "Titan One", "#fff", ink, 0, 7, 6, 12)
    body += f'<g filter="url(#sh)">{fit(w, 66, 228, 380, 100)}</g>'
    body += fit(
        text("CARTOONS ALL DAY", "Fredoka", 40, weight=700, fill="#fae8ff", ls=6), 140, 352, 232, 30
    )
    return svg(body, d)


@net("Toon Loop", TOONS, "cartoons", "animation", "kids")
def toon_loop():
    ink = "#0f172a"
    d = (
        SH
        + lin("lp1", [(0, "#22d3ee"), (1, "#6366f1")], x2=1, y2=0)
        + lin("lp2", [(0, "#f472b6"), (1, "#f59e0b")], x2=1, y2=0)
    )
    body = '<g filter="url(#sh)" fill="none" stroke-linecap="round">'
    body += f'<path d="M256 226 C196 136 66 136 66 226 C66 316 196 316 256 226" stroke="{ink}" stroke-width="64"/>'
    body += f'<path d="M256 226 C316 136 446 136 446 226 C446 316 316 316 256 226" stroke="{ink}" stroke-width="64"/>'
    body += '<path d="M256 226 C196 136 66 136 66 226 C66 316 196 316 256 226" stroke="url(#lp1)" stroke-width="48"/>'
    body += '<path d="M256 226 C316 136 446 136 446 226 C446 316 316 316 256 226" stroke="url(#lp2)" stroke-width="48"/>'
    body += "</g>"
    body += '<path d="M110 176 Q150 156 190 170" fill="none" stroke="#fff" stroke-width="9" stroke-linecap="round" opacity=".55"/>'
    w = _x("TOON LOOP", "Lilita One", "#fff", ink, 0, 7, 6, 14)
    body += f'<g filter="url(#sh)">{fit(w, 40, 340, 432, 110)}</g>'
    return svg(body, d)


@net("Toon Soup", TOONS, "cartoons", "kids", "variety")
def toon_soup():
    ink = "#1c1917"
    d = SH + lin("pot", [(0, "#94a3b8"), (0.45, "#e2e8f0"), (1, "#475569")], x2=1, y2=0)
    body = ""
    blobs = (
        (170, 118, 34, "#f472b6"),
        (236, 92, 42, "#facc15"),
        (308, 110, 36, "#22d3ee"),
        (360, 140, 24, "#a3e635"),
        (128, 150, 22, "#a78bfa"),
    )
    for x, y, r, c in blobs:
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}" stroke="{ink}" stroke-width="5"/><circle cx="{x - r * 0.35:.0f}" cy="{y - r * 0.35:.0f}" r="{r * 0.25:.0f}" fill="#fff" opacity=".7"/>'
    body += '<g filter="url(#sh)">'
    for x in (36, 436):
        body += f'<rect x="{x}" y="206" width="40" height="30" rx="12" fill="#475569" stroke="{ink}" stroke-width="6"/>'
    body += f'<path d="M66 176 L446 176 L428 436 Q426 456 406 456 L106 456 Q86 456 84 436 Z" fill="url(#pot)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    body += f'<rect x="52" y="160" width="408" height="34" rx="12" fill="#cbd5e1" stroke="{ink}" stroke-width="7"/>'
    body += "</g>"
    body += f'<rect x="96" y="250" width="320" height="130" rx="14" fill="#f97316" stroke="{ink}" stroke-width="6"/>'
    body += fit(_x("TOON SOUP", "Lilita One", "#fff7ed", ink, 0, 5, 5, 10), 112, 266, 288, 70)
    body += fit(
        text("A LITTLE OF EVERYTHING", "Fredoka", 40, weight=700, fill="#fff7ed", ls=4),
        130,
        344,
        252,
        24,
    )
    return svg(body, d)


@net("Anvil Drop", TOONS, "cartoons", "slapstick", "classic cartoons")
def anvil_drop():
    ink = "#0b0f14"
    d = SH + lin("anv", [(0, "#6b7280"), (0.5, "#374151"), (1, "#111827")])
    shape = "M40 150 L380 150 L476 132 L476 182 Q420 224 340 230 L322 290 L376 380 L376 412 L136 412 L136 380 L190 290 L172 230 Q90 226 40 196 Z"
    body = ""
    for x in (150, 256, 362):
        body += f'<line x1="{x}" y1="36" x2="{x}" y2="116" stroke="#94a3b8" stroke-width="8" stroke-linecap="round" opacity=".6"/>'
    body += f'<g filter="url(#sh)"><path d="{shape}" fill="url(#anv)" stroke="{ink}" stroke-width="9" stroke-linejoin="round"/></g>'
    body += '<path d="M52 160 L378 160 L466 144" fill="none" stroke="#d1d5db" stroke-width="6" stroke-linecap="round" opacity=".5"/>'
    body += '<path d="M120 444 Q256 470 392 444" fill="none" stroke="#94a3b8" stroke-width="7" stroke-linecap="round" opacity=".6"/>'
    w = text("ANVIL", "Black Ops One", 100, fill="#fbbf24", stroke=ink, sw=8)
    body += f'<g filter="url(#sh)">{fit(w, 96, 160, 300, 66)}</g>'
    body += (
        '<g filter="url(#sh)"><rect x="150" y="300" width="212" height="70" rx="8" fill="#dc2626" stroke="'
        + ink
        + '" stroke-width="6"/></g>'
    )
    body += fit(text("DROP", "Black Ops One", 100, fill="#fff"), 172, 312, 168, 46)
    return svg(body, d)


@net("Banana Peel", TOONS, "cartoons", "slapstick", "comedy")
def banana_peel():
    ink = "#1e1b4b"
    d = (
        SH
        + lin("bp", [(0, "#312e81"), (1, "#1e1b4b")])
        + lin("bw", [(0, "#fef08a"), (1, "#facc15")])
    )
    body = '<g transform="rotate(-8 256 256)">'
    body += _panel(36, 140, 440, 232, "url(#bp)", rx=116, edge=ink, sw=6)
    body += '<rect x="52" y="156" width="408" height="200" rx="100" fill="none" stroke="#facc15" stroke-width="4" opacity=".6"/>'
    body += "</g>"
    w = _x("BANANA PEEL", "Luckiest Guy", "url(#bw)", ink, 0, 7, 6, 12)
    body += f'<g filter="url(#sh)" transform="rotate(-8 256 256)">{fit(w, 74, 184, 364, 104)}</g>'
    body += f'<g transform="rotate(-8 256 256)">{fit(text("SLIPS, TRIPS & PRATFALLS", "Fredoka", 40, weight=700, fill="#facc15", ls=4), 146, 298, 220, 24)}</g>'
    return svg(body, d)


@net("Cream Pie", TOONS, "cartoons", "slapstick", "comedy")
def cream_pie():
    ink = "#3f1d0b"
    d = (
        SH
        + rad("crust", [(0.7, "#f6c27a"), (1, "#b7742e")])
        + rad("cream", [(0, "#ffffff"), (1, "#fde8ef")])
    )
    scallop = ""
    for k in range(28):
        a = math.radians(k * 360 / 28)
        scallop += f'<circle cx="{256 + 196 * math.cos(a):.1f}" cy="{236 + 196 * math.sin(a):.1f}" r="26" fill="#d9954a" stroke="{ink}" stroke-width="5"/>'
    body = (
        f'<g filter="url(#sh)">{scallop}<circle cx="256" cy="236" r="200" fill="url(#crust)"/></g>'
    )
    for k in range(28):
        a = math.radians(k * 360 / 28)
        body += f'<circle cx="{256 + 196 * math.cos(a):.1f}" cy="{236 + 196 * math.sin(a):.1f}" r="21" fill="#e8a65c"/>'
    body += (
        f'<circle cx="256" cy="236" r="164" fill="url(#cream)" stroke="{ink}" stroke-width="5"/>'
    )
    w = _x("CREAM", "Titan One", "#ec4899", ink, 0, 6, 6, 10)
    body += f'<g filter="url(#sh)">{fit(w, 126, 160, 260, 76)}</g>'
    w2 = _x("PIE", "Titan One", "#ec4899", ink, 0, 6, 6, 10)
    body += f'<g filter="url(#sh)">{fit(w2, 186, 242, 140, 70)}</g>'
    body += '<g filter="url(#sh)">' + banner(60, 452, 410, 64, "#ec4899", ink, 6, cut=18) + "</g>"
    body += fit(
        text("SLAPSTICK CLASSICS", "Fredoka", 40, weight=700, fill="#fff", ls=6), 126, 422, 260, 40
    )
    return svg(body, d)


@net("Seltzer Bottle", TOONS, "cartoons", "slapstick", "comedy")
def seltzer_bottle():
    ink = "#0c2a4a"
    d = SH + lin("sb", [(0, "#ef4444"), (1, "#991b1b")])
    body = f'<g filter="url(#sh)"><ellipse cx="256" cy="246" rx="226" ry="176" fill="{ink}"/>'
    body += '<ellipse cx="256" cy="246" rx="212" ry="162" fill="url(#sb)"/></g>'
    body += (
        '<ellipse cx="256" cy="246" rx="194" ry="144" fill="none" stroke="#fff" stroke-width="4"/>'
    )
    rng = random.Random(6)
    for _ in range(18):
        x, y, r = rng.uniform(96, 420), rng.uniform(110, 170), rng.uniform(4, 11)
        body += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.1f}" fill="none" stroke="#fff" stroke-width="3" opacity=".75"/>'
    w = text("Seltzer", "Yellowtail", 100, fill="#fff", stroke=ink, sw=10)
    body += f'<g filter="url(#sh)">{fit(w, 86, 162, 340, 116)}</g>'
    body += f'<rect x="96" y="288" width="320" height="60" rx="8" fill="#fff" stroke="{ink}" stroke-width="5"/>'
    body += fit(text("BOTTLE", "Archivo Black", 100, fill="#b91c1c", ls=14), 128, 298, 256, 40)
    body += fit(
        text("FIZZY FUNNIES", "Oswald", 40, weight=700, fill="#fff", ls=8), 186, 362, 140, 20
    )
    return svg(body, d)


@net("Screwball", TOONS, "cartoons", "comedy", "classic cartoons")
def screwball():
    ink = "#111827"
    d = SH + rad("ball", [(0, "#ffffff"), (1, "#d1d5db")], cx=0.38, cy=0.35)
    body = f'<g filter="url(#sh)"><circle cx="256" cy="180" r="130" fill="url(#ball)" stroke="{ink}" stroke-width="8"/></g>'
    body += '<g fill="none" stroke="#dc2626" stroke-width="7" stroke-linecap="round">'
    for i in range(4):
        r = 100 - i * 24
        body += f'<path d="M{256 - r} 180 A{r} {r} 0 0 1 {256 + r} 180 A{r * 0.85:.0f} {r * 0.85:.0f} 0 0 1 {256 - r * 0.7:.0f} 180"/>'
    body += "</g>"
    for k in range(3):
        y = 120 + k * 60
        body += f'<line x1="{60 + k * 10}" y1="{y}" x2="{110 + k * 10}" y2="{y}" stroke="#facc15" stroke-width="9" stroke-linecap="round"/>'
    w = _x("SCREWBALL", "Bangers", "#facc15", ink, 4, 7, 6, 12, ls=4)
    body += f'<g filter="url(#sh)">{fit(w, 30, 322, 452, 116)}</g>'
    return svg(body, d)


@net("Slapstick", TOONS, "cartoons", "slapstick", "comedy")
def slapstick():
    return L.block_word(
        [("SLAP", "#facc15", "#111827"), ("STICK", "#ef4444", "#fff")],
        font="Bowlby One",
        edge="#111827",
        tilt=-5,
        sub="PIES · PRATFALLS · PANIC",
        sub_fill="#fff",
    )


@net("Kaboom", TOONS, "cartoons", "action", "comedy")
def kaboom():
    return L.burst_word(
        "KABOOM!",
        "CARTOONS THAT GO BANG",
        font="Bangers",
        fill="#fef08a",
        edge="#111827",
        back="#f97316",
        back2="#dc2626",
        sub_fill="#fff",
        sub_font="Bangers",
        points=18,
        tilt=-8,
        rays=True,
    )


@net("Zany", TOONS, "cartoons", "comedy", "kids")
def zany():
    ink = "#1e1b4b"
    d = SH + lin("zp", [(0, "#a855f7"), (1, "#6d28d9")])
    zz = "M40 110 L120 70 L180 120 L256 60 L330 120 L396 70 L472 110 L472 400 L396 440 L330 392 L256 452 L180 392 L120 440 L40 400 Z"
    body = f'<g filter="url(#sh)"><path d="{zz}" fill="url(#zp)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += f'<path d="{zz}" fill="none" stroke="#f0abfc" stroke-width="3" transform="translate(256 256) scale(.92) translate(-256 -256)"/>'
    lets = _letters(
        "ZANY",
        "Luckiest Guy",
        ["#facc15", "#22d3ee", "#f472b6", "#a3e635"],
        ink,
        sw=14,
        bounce=12,
        rot=10,
    )
    body += f'<g filter="url(#sh)">{fit(extrude(lets, 4, 8, 7, ink) + lets, 70, 150, 372, 170)}</g>'
    body += fit(
        text("TOONS GONE WILD", "Fredoka", 40, weight=700, fill="#fff", ls=8), 146, 344, 220, 28
    )
    return svg(body, d)


@net("Cartoon Jukebox", TOONS, "cartoons", "music", "kids")
def cartoon_jukebox():
    ink = "#1c1917"
    d = (
        SH
        + lin("cj", [(0, "#f1f5f9"), (0.5, "#94a3b8"), (1, "#e2e8f0")])
        + lin("cjr", [(0, "#dc2626"), (1, "#7f1d1d")])
    )
    body = _panel(34, 60, 444, 392, "url(#cjr)", rx=24, edge=ink, sw=6)
    body += f'<rect x="56" y="82" width="400" height="104" rx="14" fill="url(#cj)" stroke="{ink}" stroke-width="5"/>'
    w = text("CARTOON", "Bungee", 100, fill="#dc2626", stroke=ink, sw=6)
    body += fit(w, 82, 96, 348, 46)
    body += fit(text("JUKEBOX", "Bungee", 100, fill=ink, ls=10), 140, 146, 232, 30)
    for i, lab in enumerate(("A1  TOON TUNES", "B4  SING-ALONGS", "C7  THEME SONGS")):
        y = 208 + i * 62
        body += f'<rect x="76" y="{y}" width="290" height="46" rx="5" fill="#fffbeb" stroke="{ink}" stroke-width="4"/>'
        body += f'<rect x="76" y="{y}" width="290" height="10" fill="#f59e0b"/>'
        body += fit(text(lab, "Oswald", 40, weight=700, fill=ink, ls=4), 92, y + 16, 258, 24)
        body += f'<circle cx="406" cy="{y + 23}" r="18" fill="#facc15" stroke="{ink}" stroke-width="5"/><circle cx="401" cy="{y + 18}" r="6" fill="#fff" opacity=".7"/>'
    return svg(body, d)


@net("Doodle Den", TOONS, "cartoons", "kids", "drawing")
def doodle_den():
    ink = "#1e3a8a"
    d = SH
    body = _panel(40, 60, 432, 392, "#fffef5", rx=10, edge="#1f2937", sw=4)
    for y in range(100, 452, 28):
        body += f'<line x1="40" y1="{y}" x2="472" y2="{y}" stroke="#93c5fd" stroke-width="2"/>'
    body += '<line x1="96" y1="60" x2="96" y2="452" stroke="#f87171" stroke-width="3"/>'
    body += f'<path d="M386 104 l10 22 24 3 -18 16 5 24 -21 -12 -21 12 5 -24 -18 -16 24 -3 Z" fill="none" stroke="{ink}" stroke-width="4" stroke-linejoin="round"/>'
    body += '<path d="M126 396 q20 -30 40 0 t40 0 t40 0" fill="none" stroke="#db2777" stroke-width="5" stroke-linecap="round"/>'
    body += '<path d="M380 380 a26 26 0 1 1 -2 -1 a18 18 0 1 0 2 1" fill="none" stroke="#16a34a" stroke-width="5" stroke-linecap="round"/>'
    w = text("Doodle", "Permanent Marker", 100, fill=ink)
    body += fit(w, 116, 140, 290, 120)
    w2 = text("DEN", "Permanent Marker", 100, fill="#db2777", ls=10)
    body += fit(w2, 176, 262, 180, 100)
    return svg(body, d)


@net("Sketchbook", TOONS, "cartoons", "animation", "drawing")
def sketchbook():
    d = SH + lin("skc", [(0, "#27272a"), (1, "#09090b")])
    body = _panel(70, 40, 372, 432, "url(#skc)", rx=18, edge="#000", sw=4)
    for y in range(66, 460, 30):
        body += f'<rect x="58" y="{y}" width="28" height="12" rx="6" fill="#d4d4d8" stroke="#000" stroke-width="2"/>'
    body += '<rect x="390" y="40" width="18" height="432" fill="#dc2626"/>'
    body += '<rect x="126" y="150" width="244" height="190" rx="6" fill="#f5f5f4" stroke="#a8a29e" stroke-width="3"/>'
    body += fit(text("SKETCH", "Special Elite", 100, fill="#18181b"), 142, 176, 212, 64)
    body += fit(text("BOOK", "Special Elite", 100, fill="#18181b", ls=12), 168, 250, 160, 54)
    body += '<line x1="146" y1="320" x2="350" y2="320" stroke="#a8a29e" stroke-width="2"/>'
    body += fit(
        text("ANIMATION · DRAWN BY HAND", "Oswald", 40, weight=600, fill="#d4d4d8", ls=6),
        130,
        376,
        236,
        20,
    )
    return svg(body, d)


@net("Toon Tower", TOONS, "cartoons", "kids")
def toon_tower():
    ink = "#0f172a"
    d = SH
    cells = (
        ("T", "#ef4444", 118, 40, -4),
        ("O", "#f59e0b", 258, 46, 3),
        ("O", "#22c55e", 122, 176, 2),
        ("N", "#3b82f6", 262, 172, -3),
    )
    body = '<g filter="url(#sh)">'
    for _ch, c, x, y, r in cells:
        body += f'<rect x="{x}" y="{y}" width="130" height="126" rx="12" fill="{c}" stroke="{ink}" stroke-width="7" transform="rotate({r} {x + 65} {y + 63})"/>'
    body += "</g>"
    for ch, _c, x, y, r in cells:
        body += f'<g transform="rotate({r} {x + 65} {y + 63})">{fit(text(ch, "Lilita One", 100, fill="#fff", stroke=ink, sw=6), x + 22, y + 16, 86, 94)}</g>'
    body += (
        '<g filter="url(#sh)"><rect x="40" y="316" width="432" height="134" rx="16" fill="#1e293b" stroke="'
        + ink
        + '" stroke-width="7"/></g>'
    )
    body += fit(_x("TOWER", "Lilita One", "#fff", ink, 0, 6, 6, 10, ls=10), 76, 336, 360, 96)
    return svg(body, d)


@net("Funhouse", TOONS, "cartoons", "comedy", "kids")
def funhouse():
    ink = "#3b0764"
    d = (
        SH
        + lin("fhf", [(0, "#fde68a"), (0.5, "#d97706"), (1, "#fde68a")])
        + lin("fhm", [(0, "#e0f2fe"), (0.5, "#bae6fd"), (1, "#a5b4fc")], x2=1, y2=1)
    )
    body = f'<g filter="url(#sh)"><ellipse cx="256" cy="256" rx="200" ry="226" fill="url(#fhf)" stroke="{ink}" stroke-width="7"/></g>'
    body += f'<ellipse cx="256" cy="256" rx="172" ry="198" fill="url(#fhm)" stroke="{ink}" stroke-width="5"/>'
    body += '<path d="M150 120 Q180 90 230 84" fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" opacity=".7"/>'
    top = _letters(
        "FUN", "Titan One", ["#c026d3", "#db2777", "#7c3aed"], ink, sw=12, bounce=6, rot=6
    )
    bot = _letters(
        "HOUSE", "Titan One", ["#7c3aed", "#c026d3", "#db2777"], ink, sw=12, bounce=6, rot=-6
    )
    body += f'<g filter="url(#sh)">{fit(top, 156, 120, 200, 100)}</g>'
    body += f'<g filter="url(#sh)">{fit(bot, 106, 222, 300, 96)}</g>'
    body += fit(text("STEP RIGHT UP", "Fredoka", 40, weight=700, fill=ink, ls=8), 166, 338, 180, 28)
    return svg(body, d)


@net("Spring Loaded", TOONS, "cartoons", "action", "kids")
def spring_loaded():
    ink = "#111827"
    d = SH + lin("spr", [(0, "#f1f5f9"), (0.5, "#64748b"), (1, "#e2e8f0")], x2=1, y2=0)
    coil = ""
    for i in range(7):
        y = 300 + i * 22
        coil += f'<ellipse cx="256" cy="{y}" rx="72" ry="14" fill="none" stroke="{ink}" stroke-width="16"/>'
        coil += f'<ellipse cx="256" cy="{y}" rx="72" ry="14" fill="none" stroke="url(#spr)" stroke-width="9"/>'
    body = f'<g filter="url(#sh)">{coil}</g>'
    body += f'<rect x="176" y="436" width="160" height="26" rx="6" fill="#475569" stroke="{ink}" stroke-width="6"/>'
    body += f'<g filter="url(#sh)"><rect x="40" y="70" width="432" height="216" rx="28" fill="#ef4444" stroke="{ink}" stroke-width="8"/></g>'
    body += '<rect x="56" y="86" width="400" height="184" rx="18" fill="none" stroke="#fecaca" stroke-width="3"/>'
    for x in (36, 476):
        body += f'<path d="M{x} 90 l{-14 if x < 100 else 14} -18 M{x} 130 l{-20 if x < 100 else 20} 0 M{x} 170 l{-14 if x < 100 else 14} 18" stroke="#facc15" stroke-width="7" stroke-linecap="round"/>'
    body += fit(_x("SPRING", "Titan One", "#fff", ink, 0, 6, 6, 10), 90, 96, 332, 88)
    body += fit(_x("LOADED", "Titan One", "#facc15", ink, 0, 6, 6, 10), 110, 190, 292, 74)
    return svg(body, d)


@net("Rad Toons", TOONS, "cartoons", "80s", "90s")
def rad_toons():
    ink = "#0a0a0a"
    d = SH + lin("rad", [(0, "#a3e635"), (1, "#22c55e")])
    rng = random.Random(12)
    pts_ = []
    for k in range(26):
        a = math.radians(k * 360 / 26)
        r = rng.choice((150, 186, 200, 170))
        pts_.append(f"{256 + r * math.cos(a):.0f},{230 + r * 0.8 * math.sin(a):.0f}")
    body = f'<g filter="url(#sh)"><polygon points="{" ".join(pts_)}" fill="#ec4899" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/></g>'
    for x, y, r in ((70, 90, 12), (450, 120, 9), (460, 360, 14), (60, 380, 8)):
        body += (
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="#ec4899" stroke="{ink}" stroke-width="4"/>'
        )
    w = _x("RAD", "Bangers", "url(#rad)", ink, 6, 8, 8, 12, ls=6)
    body += f'<g filter="url(#sh)" transform="rotate(-8 256 230)">{fit(w, 116, 110, 280, 160)}</g>'
    body += f'<g filter="url(#sh)"><rect x="126" y="320" width="260" height="76" rx="6" fill="#facc15" stroke="{ink}" stroke-width="7" transform="rotate(4 256 358)"/></g>'
    body += f'<g transform="rotate(4 256 358)">{fit(text("TOONS", "Bangers", 100, fill=ink, ls=10), 150, 330, 212, 56)}</g>'
    return svg(body, d)


@net("Tubular", TOONS, "cartoons", "80s", "surfing")
def tubular():
    ink = "#082f49"
    d = (
        SH
        + lin("tsky", [(0, "#f472b6"), (0.6, "#fb923c"), (1, "#fde047")])
        + lin("twav", [(0, "#22d3ee"), (1, "#0e7490")])
    )
    body = '<defs><clipPath id="tbc"><circle cx="256" cy="210" r="180"/></clipPath></defs>'
    body += f'<g filter="url(#sh)"><circle cx="256" cy="210" r="192" fill="{ink}"/></g>'
    body += (
        '<g clip-path="url(#tbc)"><rect x="60" y="20" width="400" height="400" fill="url(#tsky)"/>'
    )
    body += '<circle cx="256" cy="200" r="70" fill="#fef9c3" opacity=".9"/>'
    body += (
        '<path d="M60 300 Q120 120 280 150 Q380 170 360 250 Q340 210 300 214 Q250 222 270 280 Q300 330 460 300 L460 420 L60 420 Z" fill="url(#twav)" stroke="'
        + ink
        + '" stroke-width="6"/>'
    )
    body += '<path d="M290 160 Q360 170 356 236" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round" opacity=".8"/></g>'
    body += '<circle cx="256" cy="210" r="180" fill="none" stroke="#fde047" stroke-width="6"/>'
    w = text("TUBULAR", "Racing Sans One", 100, fill="#fde047", stroke=ink, sw=14, style="italic")
    body += f'<g filter="url(#sh)">{fit(extrude(w, 4, 8, 6, ink) + w, 30, 340, 452, 120)}</g>'
    return svg(body, d)


@net("Sugar Crash", TOONS, "cartoons", "kids", "saturday morning")
def sugar_crash():
    ink = "#4a044e"
    d = (
        SH
        + lin("sug", [(0, "#fbcfe8"), (1, "#f472b6")])
        + lin("sgw", [(0, "#ffffff"), (1, "#fce7f3")])
    )
    body = _panel(36, 70, 440, 372, "url(#sug)", rx=40, edge=ink, sw=6)
    for i in range(-4, 10):
        body += f'<line x1="{36 + i * 50}" y1="70" x2="{136 + i * 50}" y2="442" stroke="#fff" stroke-width="14" opacity=".25"/>'
    body = (
        '<defs><clipPath id="sgc"><rect x="36" y="70" width="440" height="372" rx="40"/></clipPath></defs>'
        + body.replace("<line", '<line clip-path="url(#sgc)"')
    )
    w = _x("SUGAR", "Titan One", "url(#sgw)", ink, 0, 8, 8, 12)
    body += f'<g filter="url(#sh)">{fit(w, 76, 100, 360, 120)}</g>'
    jag = "M50 270 L462 250 L448 286 L470 312 L440 340 L462 372 L50 392 L70 356 L44 330 L68 300 Z"
    body += f'<g filter="url(#sh)"><path d="{jag}" fill="#facc15" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/></g>'
    body += f'<g transform="rotate(-3 256 320)">{fit(text("CRASH", "Bangers", 100, fill=ink, ls=12), 110, 278, 292, 88)}</g>'
    return svg(body, d)


@net("Totally Toons", TOONS, "cartoons", "80s", "90s")
def totally_toons():
    d = SH
    body = _panel(36, 70, 440, 372, "#111827", rx=24)
    body += '<polygon points="70,110 130,96 112,150" fill="#22d3ee"/>'
    body += '<circle cx="420" cy="120" r="26" fill="none" stroke="#facc15" stroke-width="8"/>'
    body += '<path d="M380 380 q14 -20 28 0 t28 0 t28 0" fill="none" stroke="#a3e635" stroke-width="7" stroke-linecap="round"/>'
    body += '<rect x="70" y="372" width="40" height="40" fill="none" stroke="#ec4899" stroke-width="7" transform="rotate(20 90 392)"/>'
    w = text("Totally", "Yellowtail", 100, fill="#ec4899", stroke="#fff", sw=4)
    body += f'<g filter="url(#sh)" transform="rotate(-8 256 180)">{fit(w, 110, 110, 292, 110)}</g>'
    t = _x("TOONS", "Archivo Black", "#fff", "#000", 6, 8, 8, 6, ex="#22d3ee")
    body += f'<g filter="url(#sh)">{fit(t, 70, 226, 372, 120)}</g>'
    return svg(body, d)


# ======================================================================= morning & late-night blocks


@net("Neon Toons", TOONS, "cartoons", "80s", "90s")
def neon_toons():
    d = (
        SH
        + glow("gp", "#ec4899", blur=8, strength=2)
        + glow("gl", "#84cc16", blur=8, strength=2)
        + glow("gc", "#22d3ee", blur=6, strength=2)
    )
    body = _panel(30, 80, 452, 352, "#0d0a1a", rx=30, edge="#000", sw=6)
    body += '<g filter="url(#gc)"><rect x="52" y="102" width="408" height="308" rx="20" fill="none" stroke="#22d3ee" stroke-width="6"/></g>'
    body += '<rect x="52" y="102" width="408" height="308" rx="20" fill="none" stroke="#ecfeff" stroke-width="2"/>'
    for word, col, core, gid, y, h in (
        ("NEON", "#f472b6", "#fdf2f8", "gp", 130, 120),
        ("TOONS", "#a3e635", "#f7fee7", "gl", 270, 112),
    ):
        tube = text(word, "Bungee", 100, fill="none", stroke=col, sw=7, ls=6)
        hot = text(word, "Bungee", 100, fill="none", stroke=core, sw=2.5, ls=6)
        body += fit(f'<g filter="url(#{gid})">{tube}</g>{hot}', 86, y, 340, h)
    return svg(body, d)


@net("Pajama Toons", TOONS, "cartoons", "kids", "saturday morning")
def pajama_toons():
    ink = "#1e3a8a"
    d = SH
    body = '<defs><clipPath id="pjc"><rect x="36" y="64" width="440" height="384" rx="40"/></clipPath></defs>'
    body += _panel(36, 64, 440, 384, "#dbeafe", rx=40, edge=ink, sw=6)
    body += '<g clip-path="url(#pjc)">'
    for x in range(36, 480, 44):
        body += f'<rect x="{x}" y="64" width="20" height="384" fill="#93c5fd" opacity=".7"/>'
    body += "</g>"
    body += f'<path d="M402 104 A30 30 0 1 0 430 148 A24 24 0 1 1 402 104 Z" fill="#fde047" stroke="{ink}" stroke-width="4"/>'
    for x, y in ((90, 110), (340, 120), (110, 400), (420, 390)):
        body += f'<polygon points="{star(x, y, 13, 6)}" fill="#fde047" stroke="{ink}" stroke-width="3"/>'
    body += f'<g filter="url(#sh)"><rect x="64" y="176" width="384" height="170" rx="85" fill="#fff" stroke="{ink}" stroke-width="7"/></g>'
    w = _x("PAJAMA", "Fredoka", "#3b82f6", ink, 0, 6, 6, 10, weight=700)
    body += fit(w, 104, 192, 304, 84)
    body += fit(
        text("TOONS", "Fredoka", 100, weight=700, fill="#f472b6", stroke=ink, sw=8, ls=10),
        156,
        280,
        200,
        52,
    )
    return svg(body, d)


@net("Afterschool Toons", TOONS, "cartoons", "kids", "afterschool")
def afterschool_toons():
    ink = "#111827"
    d = SH + lin("bus", [(0, "#facc15"), (1, "#eab308")])
    body = _panel(30, 90, 452, 332, "url(#bus)", rx=30, edge=ink, sw=7)
    for y in (126, 146):
        body += f'<rect x="30" y="{y}" width="452" height="8" fill="{ink}"/>'
    for y in (372, 392):
        body += f'<rect x="30" y="{y}" width="452" height="8" fill="{ink}"/>'
    body += fit(_x("AFTERSCHOOL", "Archivo Black", ink, ink, 0, 0, 1, 0), 60, 172, 392, 70)
    body += f'<g filter="url(#sh)"><rect x="70" y="262" width="210" height="90" rx="12" fill="#dc2626" stroke="{ink}" stroke-width="6"/></g>'
    body += fit(text("TOONS", "Archivo Black", 100, fill="#fff"), 88, 282, 174, 50)
    body += f'<rect x="300" y="262" width="142" height="90" rx="12" fill="#0b0b0b" stroke="{ink}" stroke-width="6"/>'
    body += fit(text("3:30", "VT323", 100, fill="#ef4444"), 316, 270, 110, 74)
    return svg(body, d)


@net("Mega Morning", TOONS, "cartoons", "90s", "saturday morning")
def mega_morning():
    ink = "#1c1917"
    d = (
        SH
        + lin("mm1", [(0, "#fde047"), (1, "#f97316")])
        + lin("mmw", [(0, "#ffffff"), (1, "#fde68a")])
    )
    body = '<defs><clipPath id="mmc2"><circle cx="256" cy="226" r="200"/></clipPath></defs>'
    body += f'<g filter="url(#sh)"><circle cx="256" cy="226" r="212" fill="{ink}"/></g>'
    body += (
        '<g clip-path="url(#mmc2)"><rect x="40" y="10" width="440" height="440" fill="url(#mm1)"/>'
    )
    for k in range(18):
        a1, a2 = math.radians(k * 20), math.radians(k * 20 + 10)
        body += f'<polygon points="256,300 {256 + 500 * math.cos(a1):.0f},{300 + 500 * math.sin(a1):.0f} {256 + 500 * math.cos(a2):.0f},{300 + 500 * math.sin(a2):.0f}" fill="#fff" opacity=".22"/>'
    body += "</g>"
    w = _x("MEGA", "Bungee", "url(#mmw)", ink, 6, 9, 9, 12)
    body += f'<g filter="url(#sh)">{fit(w, 76, 96, 360, 150)}</g>'
    body += '<g filter="url(#sh)">' + banner(26, 486, 286, 92, "#2563eb", ink, 7, cut=24) + "</g>"
    body += fit(text("MORNING", "Bungee", 100, fill="#fff", ls=6), 90, 302, 332, 60)
    return svg(body, d)


@net("Toons After Dark", TOONS, "cartoons", "late night", "adult animation")
def toons_after_dark():
    ink = "#0b0620"
    d = (
        SH
        + rad("tad", [(0, "#4c1d95"), (1, "#0b0620")], cx=0.5, cy=0.3, r=0.8)
        + lin("tadw", [(0, "#fef08a"), (1, "#facc15")])
    )
    body = _panel(36, 70, 440, 372, "url(#tad)", rx=30, edge="#000", sw=5)
    body += '<circle cx="404" cy="132" r="34" fill="#fef3c7"/><circle cx="420" cy="120" r="32" fill="#2e1065"/>'
    for x, y in ((90, 110), (150, 150), (300, 104), (440, 210), (80, 380)):
        body += f'<circle cx="{x}" cy="{y}" r="3" fill="#fff"/>'
    w = _x("TOONS", "Lilita One", "url(#tadw)", ink, 0, 8, 8, 12, ls=4)
    body += f'<g filter="url(#sh)">{fit(w, 70, 140, 372, 130)}</g>'
    body += fit(
        text("after dark", "Pacifico", 100, fill="#c4b5fd", stroke=ink, sw=8), 120, 278, 272, 96
    )
    return svg(body, d)


@net("Late Toons", TOONS, "cartoons", "late night", "adult animation")
def late_toons():
    ink = "#0f172a"
    centre = '<circle cx="256" cy="256" r="222" fill="#fef3c7"/>'
    for k in range(12):
        a = math.radians(k * 30)
        r1 = 186 if k % 3 else 170
        centre += f'<line x1="{256 + r1 * math.cos(a):.0f}" y1="{256 + r1 * math.sin(a):.0f}" x2="{256 + 204 * math.cos(a):.0f}" y2="{256 + 204 * math.sin(a):.0f}" stroke="{ink}" stroke-width="{10 if k % 3 == 0 else 6}" stroke-linecap="round"/>'
    centre += f'<line x1="256" y1="256" x2="256" y2="104" stroke="{ink}" stroke-width="14" stroke-linecap="round"/>'
    centre += '<line x1="256" y1="256" x2="232" y2="136" stroke="#dc2626" stroke-width="10" stroke-linecap="round"/>'
    centre += f'<circle cx="256" cy="256" r="16" fill="{ink}"/>'
    return L.roundel(
        centre,
        "LATE TOONS",
        font="Lilita One",
        ink="#fef3c7",
        disc="#fef3c7",
        rim="#1e3a8a",
        edge=ink,
        bar="#1e3a8a",
        ls=6,
        bar_y=300,
    )


@net("Night Shift Toons", TOONS, "cartoons", "late night", "adult animation")
def night_shift_toons():
    return L.plate(
        "NIGHT SHIFT",
        "TOONS",
        font="Black Ops One",
        ink="#1e1b4b",
        metal=("#c7d2fe", "#6366f1"),
        stripe=("#facc15", "#1e1b4b"),
        edge="#1e1b4b",
    )


@net("Midnight Ink", TOONS, "cartoons", "late night", "animation")
def midnight_ink():
    ink = "#020617"
    d = SH + lin("mid", [(0, "#1e3a8a"), (1, "#020617")])
    drop = "M256 30 C300 120 412 200 412 300 C412 390 340 456 256 456 C172 456 100 390 100 300 C100 200 212 120 256 30 Z"
    body = f'<g filter="url(#sh)"><path d="{drop}" fill="url(#mid)" stroke="{ink}" stroke-width="8"/></g>'
    body += '<path d="M150 260 Q160 200 210 170" fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" opacity=".25"/>'
    for x, y in ((200, 230), (320, 200), (300, 420), (160, 380), (360, 380)):
        body += f'<polygon points="{star(x, y, 9, 4)}" fill="#e0e7ff"/>'
    body += fit(
        text("MIDNIGHT", "Cinzel", 100, weight=700, fill="#e0e7ff", ls=6), 124, 262, 264, 48
    )
    w = text("INK", "Abril Fatface", 100, fill="#93c5fd", stroke=ink, sw=6, ls=10)
    body += f'<g filter="url(#sh)">{fit(w, 160, 314, 192, 84)}</g>'
    return svg(body, d)


# ======================================================================= anime


@net("Kaiju Channel", TOONS, "anime", "monsters", "action")
def kaiju_channel():
    ink = "#0a0a0a"
    d = SH + lin("kj", [(0, "#7f1d1d"), (1, "#1c0606")])
    rng = random.Random(8)
    body = '<defs><clipPath id="kjc"><rect x="34" y="64" width="444" height="384" rx="20"/></clipPath></defs>'
    body += _panel(34, 64, 444, 384, "url(#kj)", rx=20, edge=ink, sw=6)
    body += '<g clip-path="url(#kjc)">'
    x = 34
    while x < 478:
        w, h = rng.uniform(24, 48), rng.uniform(40, 110)
        body += (
            f'<rect x="{x:.0f}" y="{448 - h:.0f}" width="{w:.0f}" height="{h:.0f}" fill="{ink}"/>'
        )
        x += w + 3
    for i in range(3):
        body += f'<path d="M{150 + i * 70} 80 Q{230 + i * 70} 250 {200 + i * 70} 420" fill="none" stroke="#fca5a5" stroke-width="{18 - i * 2}" stroke-linecap="round" opacity=".45"/>'
    body += "</g>"
    w = _x("KAIJU", "Black Ops One", "#fef2f2", ink, 0, 8, 8, 10, ls=4)
    body += f'<g filter="url(#sh)">{fit(w, 64, 150, 384, 130)}</g>'
    body += f'<rect x="120" y="296" width="272" height="50" fill="#dc2626" stroke="{ink}" stroke-width="5"/>'
    body += fit(text("CHANNEL", "Black Ops One", 100, fill="#fff", ls=12), 140, 304, 232, 34)
    return svg(body, d)


@net("Mecha", TOONS, "anime", "robots", "action")
def mecha():
    ink = "#0b1220"
    d = (
        SH
        + lin("mp", [(0, "#e2e8f0"), (0.5, "#94a3b8"), (1, "#475569")])
        + lin("mv", [(0, "#fde047"), (1, "#f59e0b")])
    )
    hexa = "M96 120 L176 70 L336 70 L416 120 L456 256 L416 392 L336 442 L176 442 L96 392 L56 256 Z"
    body = f'<g filter="url(#sh)"><path d="{hexa}" fill="url(#mp)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += f'<path d="{hexa}" fill="none" stroke="#fff" stroke-width="2" opacity=".6" transform="translate(256 256) scale(.9) translate(-256 -256)"/>'
    body += f'<path d="M256 40 L196 150 L256 126 L316 150 Z" fill="url(#mv)" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>'
    body += f'<path d="M150 170 L220 150 M362 170 L292 150" stroke="{ink}" stroke-width="5"/>'
    body += f'<rect x="76" y="210" width="360" height="110" fill="#1d4ed8" stroke="{ink}" stroke-width="6"/>'
    body += fit(text("MECHA", "Russo One", 100, fill="#fff", ls=10), 98, 224, 316, 82)
    body += f'<path d="M170 350 L342 350 L320 380 L192 380 Z" fill="#dc2626" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>'
    body += fit(text("ANIME", "Russo One", 40, fill="#fff", ls=10), 210, 354, 92, 22)
    return svg(body, d)


@net("Origami", TOONS, "anime", "japanese animation")
def origami():
    d = SH
    crane = (
        '<polygon points="256,60 330,190 256,220" fill="#fca5a5"/>'
        '<polygon points="256,60 182,190 256,220" fill="#f87171"/>'
        '<polygon points="256,220 330,190 440,150 356,250" fill="#ef4444"/>'
        '<polygon points="256,220 182,190 72,150 156,250" fill="#dc2626"/>'
        '<polygon points="156,250 256,220 356,250 256,290" fill="#b91c1c"/>'
        '<polygon points="356,250 420,170 440,180 380,260" fill="#fca5a5"/>'
    )
    body = f'<g filter="url(#sh)">{crane}</g>'
    body += '<g fill="none" stroke="#7f1d1d" stroke-width="2" opacity=".5"><path d="M256 60 L256 290 M182 190 L330 190"/></g>'
    body += fit(
        text("ORIGAMI", "Montserrat", 100, weight=300, fill="#f8fafc", ls=24), 60, 320, 392, 64
    )
    body += '<line x1="200" y1="406" x2="312" y2="406" stroke="#ef4444" stroke-width="3"/>'
    body += fit(
        text("ANIME · FOLDED FRESH", "Montserrat", 40, weight=600, fill="#fca5a5", ls=8),
        146,
        418,
        220,
        18,
    )
    return svg(body, d)


@net("Ramen Night", TOONS, "anime", "late night", "japanese animation")
def ramen_night():
    ink = "#1c1917"
    d = SH + lin("nor", [(0, "#1e3a8a"), (1, "#172554")])
    body = f'<g filter="url(#sh)"><rect x="40" y="70" width="432" height="22" rx="8" fill="#a16207" stroke="{ink}" stroke-width="5"/></g>'
    body += '<g filter="url(#sh)">'
    for i in range(3):
        x = 56 + i * 136
        body += f'<path d="M{x} 92 L{x + 128} 92 L{x + 128} 300 Q{x + 64} 312 {x} 300 Z" fill="url(#nor)" stroke="{ink}" stroke-width="5"/>'
    body += "</g>"
    body += fit(text("RAMEN", "Archivo Black", 100, fill="#f8fafc", ls=10), 76, 146, 360, 100)
    for i in (1, 2):
        body += f'<line x1="{56 + i * 136 - 4}" y1="96" x2="{56 + i * 136 - 4}" y2="304" stroke="#020617" stroke-width="8"/>'
    body += f'<g filter="url(#sh)"><rect x="96" y="340" width="320" height="86" rx="43" fill="#dc2626" stroke="{ink}" stroke-width="6"/></g>'
    body += fit(text("NIGHT", "Archivo Black", 100, fill="#fff", ls=16), 140, 356, 232, 54)
    return svg(body, d)


@net("Bullet Train", TOONS, "anime", "action", "japanese animation")
def bullet_train():
    ink = "#0f172a"
    d = SH + lin("bt", [(0, "#ffffff"), (1, "#cbd5e1")])
    body = ""
    for i, y in enumerate((120, 150, 180, 330, 360)):
        body += f'<line x1="{30 + i * 10}" y1="{y}" x2="{200 + i * 20}" y2="{y}" stroke="#38bdf8" stroke-width="8" stroke-linecap="round" opacity=".6"/>'
    nose = "M40 200 L330 200 Q470 206 480 290 L40 290 Z"
    body += f'<g filter="url(#sh)"><path d="{nose}" fill="url(#bt)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += '<path d="M300 210 Q400 214 430 260 L340 260 Z" fill="#1e293b"/>'
    body += '<rect x="40" y="262" width="430" height="14" fill="#1d4ed8"/>'
    for x in (80, 150, 220):
        body += f'<rect x="{x}" y="216" width="50" height="30" rx="6" fill="#1e293b"/>'
    w = text("BULLET TRAIN", "Racing Sans One", 100, fill="#fff", stroke=ink, sw=12, style="italic")
    body += f'<g filter="url(#sh)">{fit(extrude(w, 5, 7, 6, "#1d4ed8") + w, 36, 320, 440, 96)}</g>'
    return svg(body, d)


@net("Paper Lantern", TOONS, "anime", "japanese animation")
def paper_lantern():
    ink = "#1c1917"
    d = SH + rad("pl", [(0, "#fde68a"), (0.5, "#f97316"), (1, "#b91c1c")], cx=0.5, cy=0.45, r=0.6)
    body = f'<rect x="206" y="24" width="100" height="26" rx="6" fill="#a16207" stroke="{ink}" stroke-width="4"/>'
    body += f'<g filter="url(#sh)"><ellipse cx="256" cy="186" rx="130" ry="140" fill="url(#pl)" stroke="{ink}" stroke-width="7"/></g>'
    for k in range(-5, 6):
        body += f'<line x1="{256 - 130 * math.sqrt(max(0, 1 - (k / 6) ** 2)):.0f}" y1="{186 + k * 22}" x2="{256 + 130 * math.sqrt(max(0, 1 - (k / 6) ** 2)):.0f}" y2="{186 + k * 22}" stroke="{ink}" stroke-width="2" opacity=".35"/>'
    body += f'<rect x="206" y="320" width="100" height="24" rx="6" fill="#a16207" stroke="{ink}" stroke-width="4"/>'
    body += '<line x1="256" y1="344" x2="256" y2="364" stroke="#a16207" stroke-width="5"/>'
    body += fit(text("PAPER", "Cinzel", 100, weight=700, fill="#fef3c7", ls=8), 96, 376, 320, 50)
    body += fit(text("LANTERN", "Cinzel", 100, weight=700, fill="#f97316", ls=8), 106, 432, 300, 42)
    return svg(body, d)


@net("Katana Theater", TOONS, "anime", "samurai", "action")
def katana_theater():
    ink = "#0a0a0a"
    d = SH + lin("blade", [(0, "#f8fafc"), (1, "#94a3b8")])
    body = _panel(36, 56, 440, 400, "#f5f0e6", rx=8, edge=ink, sw=6)
    body += '<circle cx="256" cy="200" r="120" fill="#dc2626"/>'
    body += '<defs><clipPath id="ktc"><rect x="42" y="62" width="428" height="388" rx="4"/></clipPath></defs>'
    body += '<g clip-path="url(#ktc)"><g transform="translate(0 -24) rotate(-28 256 220)">'
    body += f'<path d="M60 214 L380 214 Q440 214 470 200 Q436 228 380 228 L60 228 Z" fill="url(#blade)" stroke="{ink}" stroke-width="4"/>'
    body += f'<rect x="40" y="206" width="14" height="30" rx="3" fill="#ca8a04" stroke="{ink}" stroke-width="3"/>'
    body += f'<rect x="-50" y="212" width="92" height="18" rx="5" fill="{ink}"/>'
    body += "</g></g>"
    w = text("KATANA", "Bebas Neue", 100, fill=ink, ls=14)
    body += fit(w, 76, 314, 360, 84)
    body += fit(text("THEATER", "Oswald", 40, weight=600, fill="#dc2626", ls=18), 166, 404, 180, 26)
    return svg(body, d)


def _fox() -> str:
    k = "#1c1917"
    g = f'<path d="M30 20 L80 80 L120 80 L170 20 L160 120 Q140 180 100 196 Q60 180 40 120 Z" fill="#fff" stroke="{k}" stroke-width="7" stroke-linejoin="round"/>'
    g += '<path d="M44 34 L74 76 L56 84 Z M156 34 L126 76 L144 84 Z" fill="#dc2626"/>'
    g += f'<path d="M62 116 Q76 104 88 118 M112 118 Q124 104 138 116" fill="none" stroke="{k}" stroke-width="7" stroke-linecap="round"/>'
    g += '<path d="M60 100 Q76 92 86 104 M114 104 Q124 92 140 100" fill="none" stroke="#dc2626" stroke-width="5" stroke-linecap="round"/>'
    g += '<path d="M100 84 L100 104" stroke="#dc2626" stroke-width="6" stroke-linecap="round"/><circle cx="100" cy="76" r="6" fill="#dc2626"/>'
    g += f'<ellipse cx="100" cy="176" rx="10" ry="7" fill="{k}"/>'
    g += '<path d="M76 150 Q100 162 124 150" fill="none" stroke="#dc2626" stroke-width="4" stroke-linecap="round"/>'
    return g


@net("Spirit Fox", TOONS, "anime", "fantasy", "japanese animation")
def spirit_fox():
    d = SH + rad("sfb", [(0, "#312e81"), (1, "#0f0a2e")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="216" r="196" fill="url(#sfb)" stroke="#a5b4fc" stroke-width="6"/></g>'
    for k in range(8):
        a = math.radians(k * 45 + 20)
        body += f'<circle cx="{256 + 166 * math.cos(a):.0f}" cy="{216 + 166 * math.sin(a):.0f}" r="9" fill="#7dd3fc" opacity=".7"/>'
    body += f'<g filter="url(#sh)">{centred(_fox(), 256, 196, 240)}</g>'
    body += (
        '<g filter="url(#sh)">' + banner(36, 476, 360, 82, "#dc2626", "#1c1917", 6, cut=22) + "</g>"
    )
    body += fit(text("SPIRIT FOX", "Cinzel", 100, weight=900, fill="#fff", ls=6), 96, 374, 320, 54)
    return svg(body, d)


# ======================================================================= teens


@net("Detention", TEENS, "teens", "school", "comedy")
def detention():
    d = SH + lin("chalk", [(0, "#1f3a2e"), (1, "#14261e")])
    body = _panel(30, 80, 452, 330, "#8b5a2b", rx=12, edge="#3b2410", sw=5)
    body += '<rect x="48" y="98" width="416" height="270" rx="4" fill="url(#chalk)"/>'
    body += '<rect x="48" y="368" width="416" height="18" fill="#a0703c"/>'
    body += '<rect x="330" y="372" width="40" height="10" rx="3" fill="#f5f5f4"/>'
    body += '<path d="M80 130 Q200 118 300 140" fill="none" stroke="#fff" stroke-width="10" opacity=".07" stroke-linecap="round"/>'
    w = text("DETENTION", "Permanent Marker", 100, fill="#f5f5f4", ls=2)
    body += fit(w, 70, 150, 372, 96)
    for i in range(4):
        body += f'<line x1="{300 + i * 18}" y1="270" x2="{300 + i * 18}" y2="330" stroke="#f5f5f4" stroke-width="6" stroke-linecap="round" opacity=".85"/>'
    body += '<line x1="290" y1="320" x2="370" y2="278" stroke="#f5f5f4" stroke-width="6" stroke-linecap="round" opacity=".85"/>'
    body += fit(text("3:00 – 4:00", "Permanent Marker", 100, fill="#fde68a"), 80, 274, 180, 46)
    return svg(body, d)


@net("Pop Quiz", TEENS, "teens", "game shows", "school")
def pop_quiz():
    ink = "#111827"
    d = SH + _halftone("pqh", "#fde047", "#f59e0b", 16, 4)
    body = _panel(40, 50, 432, 412, "url(#pqh)", rx=10, edge=ink, sw=7)
    w = _x("POP", "Bowlby One", "#ef4444", ink, 7, 9, 9, 12)
    body += f'<g filter="url(#sh)" transform="rotate(-6 256 200)">{fit(w, 80, 80, 300, 180)}</g>'
    body += f'<g filter="url(#sh)"><rect x="96" y="286" width="320" height="120" rx="10" fill="#fff" stroke="{ink}" stroke-width="7" transform="rotate(3 256 346)"/></g>'
    body += f'<g transform="rotate(3 256 346)">{fit(text("QUIZ", "Bowlby One", 100, fill=ink, ls=8), 126, 306, 260, 80)}</g>'
    body += f'<g filter="url(#sh)">{fit(text("?", "Bowlby One", 100, fill="#3b82f6", stroke=ink, sw=10), 376, 76, 70, 130)}</g>'
    return svg(body, d)


@net("Study Hall", TEENS, "teens", "school", "drama")
def study_hall():
    sym = '<rect x="20" y="40" width="160" height="130" rx="10" fill="#7f1d1d" stroke="#1c1917" stroke-width="7"/>'
    sym += '<rect x="34" y="52" width="132" height="106" rx="4" fill="#fef3c7" stroke="#1c1917" stroke-width="4"/>'
    sym += '<line x1="100" y1="52" x2="100" y2="158" stroke="#1c1917" stroke-width="4"/>'
    for y in (74, 92, 110, 128):
        sym += f'<line x1="46" y1="{y}" x2="90" y2="{y}" stroke="#a8a29e" stroke-width="4"/><line x1="110" y1="{y}" x2="154" y2="{y}" stroke="#a8a29e" stroke-width="4"/>'
    return L.crest(
        sym,
        "STUDY HALL",
        font="Graduate",
        ink="#1e3a8a",
        field="#1e3a8a",
        field2="#172554",
        rim="#facc15",
        edge="#0b1026",
        scroll="#fef3c7",
        scroll_dark="#d6c08a",
        top="EST. 1st PERIOD",
    )


@net("Yearbook", TEENS, "teens", "school", "nostalgia")
def yearbook():
    d = (
        SH
        + lin("yb", [(0, "#1e3a8a"), (1, "#172554")])
        + lin("gold", [(0, "#fff3c4"), (0.5, "#d4a63a"), (1, "#8a6414")])
    )
    body = _panel(80, 36, 352, 440, "url(#yb)", rx=10, edge="#0b1026", sw=5)
    body += '<rect x="80" y="36" width="34" height="440" fill="#0b1026" opacity=".5"/>'
    body += '<rect x="134" y="66" width="270" height="380" rx="4" fill="none" stroke="url(#gold)" stroke-width="4"/>'
    body += '<g filter="url(#sh)"><circle cx="269" cy="170" r="66" fill="none" stroke="url(#gold)" stroke-width="8"/></g>'
    body += f'<polygon points="{star(269, 170, 40, 17)}" fill="url(#gold)"/>'
    body += fit(
        text("YEARBOOK", "Cinzel", 100, weight=900, fill="url(#gold)", ls=6), 150, 268, 238, 50
    )
    body += '<line x1="190" y1="336" x2="348" y2="336" stroke="#d4a63a" stroke-width="2"/>'
    body += fit(
        text("CLASS OF '99", "Cinzel", 40, weight=700, fill="#d4a63a", ls=6), 176, 350, 186, 26
    )
    return svg(body, d)


@net("Class Clown", TEENS, "teens", "comedy", "school")
def class_clown():
    ink = "#111827"
    d = SH + lin("ccp", [(0, "#1e40af"), (1, "#1e3a8a")])
    body = _panel(36, 80, 440, 352, "url(#ccp)", rx=30, edge=ink, sw=6)
    body += fit(_x("CLASS", "Titan One", "#facc15", ink, 0, 7, 7, 12), 96, 110, 320, 104)
    left = text("CL", "Titan One", 100, fill="#facc15", stroke=ink, sw=12, anchor="end", x=-40)
    right = text("WN", "Titan One", 100, fill="#facc15", stroke=ink, sw=12, anchor="start", x=40)
    nose = '<circle cx="0" cy="-36" r="34" fill="#ef4444" stroke="#111827" stroke-width="7"/><circle cx="-11" cy="-48" r="9" fill="#fff" opacity=".6"/>'
    body += f'<g filter="url(#sh)">{fit(left + nose + right, 76, 226, 360, 104)}</g>'
    body += fit(
        text("THE FUNNIEST KIDS IN SCHOOL", "Fredoka", 40, weight=700, fill="#bfdbfe", ls=4),
        116,
        360,
        280,
        26,
    )
    return svg(body, d)


@net("Drama Club", TEENS, "teens", "drama", "school")
def drama_club():
    d = SH + lin("beam", [(0, "#fef9c3"), (1, "#fef9c3")])
    body = '<defs><clipPath id="dcc"><rect x="36" y="56" width="440" height="400" rx="20"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "#0a0a0a", rx=20)
    body += '<g clip-path="url(#dcc)"><polygon points="226,56 286,56 456,456 56,456" fill="#fef9c3" opacity=".16"/>'
    body += '<ellipse cx="256" cy="420" rx="200" ry="34" fill="#fef9c3" opacity=".22"/>'
    body += '<rect x="36" y="56" width="70" height="400" fill="#7f1d1d"/><rect x="406" y="56" width="70" height="400" fill="#7f1d1d"/>'
    for x in (50, 70, 90, 420, 440, 460):
        body += f'<line x1="{x}" y1="56" x2="{x}" y2="456" stroke="#450a0a" stroke-width="4"/>'
    body += "</g>"
    body += '<rect x="36" y="56" width="440" height="400" rx="20" fill="none" stroke="#d4a63a" stroke-width="5"/>'
    w = text("DRAMA", "Abril Fatface", 100, fill="#fef3c7", ls=6)
    body += f'<g filter="url(#sh)">{fit(w, 116, 150, 280, 104)}</g>'
    body += fit(text("Club", "Great Vibes", 100, fill="#d4a63a"), 176, 262, 160, 100)
    return svg(body, d)


@net("Homecoming", TEENS, "teens", "school", "football")
def homecoming():
    ink = "#1c1917"
    d = SH + rad("mum", [(0, "#ffffff"), (1, "#e5e7eb")])
    body = '<g filter="url(#sh)">'
    for i, (x, c) in enumerate(
        ((176, "#1e3a8a"), (214, "#facc15"), (256, "#1e3a8a"), (298, "#facc15"), (336, "#1e3a8a"))
    ):
        body += f'<path d="M{x - 18} 230 L{x + 18} 230 L{x + 18 + (i - 2) * 6} 470 L{x + (i - 2) * 6} 452 L{x - 18 + (i - 2) * 6} 470 Z" fill="{c}" stroke="{ink}" stroke-width="4"/>'
    for k in range(36):
        a = math.radians(k * 10)
        body += f'<ellipse cx="{256 + 120 * math.cos(a):.0f}" cy="{180 + 120 * math.sin(a):.0f}" rx="34" ry="14" fill="url(#mum)" stroke="#9ca3af" stroke-width="2" transform="rotate({k * 10} {256 + 120 * math.cos(a):.0f} {180 + 120 * math.sin(a):.0f})"/>'
    body += f'<circle cx="256" cy="180" r="112" fill="#1e3a8a" stroke="{ink}" stroke-width="6"/>'
    body += "</g>"
    body += '<circle cx="256" cy="180" r="98" fill="none" stroke="#facc15" stroke-width="4"/>'
    body += fit(text("HOME", "Graduate", 100, fill="#facc15"), 172, 120, 168, 56)
    body += fit(text("COMING", "Graduate", 100, fill="#fff"), 166, 186, 180, 46)
    body += f'<polygon points="{star(256, 254, 14, 6)}" fill="#facc15"/>'
    return svg(body, d)


@net("Letterman", TEENS, "teens", "sports", "school")
def letterman():
    ink = "#1c1917"
    d = SH
    body = _panel(40, 30, 432, 452, "#14532d", rx=40, edge=ink, sw=6)
    for y in (420, 440):
        body += f'<rect x="40" y="{y}" width="432" height="10" fill="#fde68a"/>'
    lpath = "M176 64 L276 64 L276 300 L356 300 L356 380 L176 380 Z"
    body += f'<g filter="url(#sh)"><path d="{lpath}" fill="#fde68a" stroke="#fef9c3" stroke-width="22" stroke-linejoin="round"/>'
    body += f'<path d="{lpath}" fill="#b91c1c" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/></g>'
    body += f'<path d="{lpath}" fill="none" stroke="#fff" stroke-width="2" stroke-dasharray="6 6" transform="translate(266 222) scale(.92) translate(-266 -222)" opacity=".6"/>'
    body += f'<g filter="url(#sh)"><rect x="70" y="190" width="372" height="76" rx="8" fill="{ink}"/></g>'
    body += fit(text("LETTERMAN", "Graduate", 100, fill="#fde68a", ls=4), 90, 204, 332, 48)
    return svg(body, d)


@net("Food Court", TEENS, "teens", "hangout", "comedy")
def food_court():
    ink = "#0f172a"
    d = SH
    body = f'<g filter="url(#sh)"><rect x="236" y="300" width="40" height="180" fill="#475569" stroke="{ink}" stroke-width="5"/></g>'
    body += f'<g filter="url(#sh)"><path d="M40 90 L420 90 L476 170 L420 250 L40 250 Z" fill="#0d9488" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/></g>'
    body += '<path d="M56 106 L412 106 L456 170 L412 234 L56 234 Z" fill="none" stroke="#99f6e4" stroke-width="3"/>'
    body += fit(_x("FOOD COURT", "Archivo Black", "#fff", ink, 0, 5, 5, 8), 70, 130, 340, 80)
    body += f'<g filter="url(#sh)"><rect x="100" y="270" width="312" height="64" rx="10" fill="#f97316" stroke="{ink}" stroke-width="6"/></g>'
    body += fit(
        text("EAT · HANG · REPEAT", "Oswald", 40, weight=700, fill="#fff", ls=6), 130, 282, 252, 40
    )
    return svg(body, d)


@net("Roller Rink", TEENS, "teens", "80s", "music")
def roller_rink():
    return L.sym_word(
        skate(P(a="#ec4899", b="#facc15", c="#22d3ee", k="#1e1b4b", l="#fff")),
        "ROLLER RINK",
        font="Racing Sans One",
        ink="#facc15",
        edge="#1e1b4b",
        style="italic",
        sub="ALL-SKATE ALL NIGHT",
        sub_font="Oswald",
        sub_ink="#f9a8d4",
        sym_box=(136, 30, 240, 240),
    )


@net("Skate Night", TEENS, "teens", "80s", "music")
def skate_night():
    ink = "#1e1b4b"
    d = SH + rad("disco", [(0, "#ffffff"), (0.6, "#cbd5e1"), (1, "#64748b")], cx=0.35, cy=0.3)
    body = '<defs><clipPath id="snc"><rect x="36" y="56" width="440" height="400" rx="30"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "#2e1065", rx=30, edge=ink, sw=6)
    body += '<g clip-path="url(#snc)">'
    for r in range(8):
        for c in range(12):
            if (r + c) % 2 == 0:
                body += f'<rect x="{36 + c * 40}" y="{336 + r * 40}" width="40" height="40" fill="#f9a8d4" opacity=".55"/>'
    for k in range(10):
        a = math.radians(20 + k * 14)
        body += f'<line x1="256" y1="140" x2="{256 + 400 * math.cos(a):.0f}" y2="{140 + 400 * math.sin(a):.0f}" stroke="#fef9c3" stroke-width="3" opacity=".25"/>'
    body += "</g>"
    body += '<line x1="256" y1="56" x2="256" y2="86" stroke="#cbd5e1" stroke-width="4"/>'
    body += f'<circle cx="256" cy="140" r="56" fill="url(#disco)" stroke="{ink}" stroke-width="5"/>'
    for i in range(-3, 4):
        body += f'<line x1="{256 + i * 15}" y1="{140 - 54 * math.sqrt(1 - (i / 3.7) ** 2):.0f}" x2="{256 + i * 15}" y2="{140 + 54 * math.sqrt(1 - (i / 3.7) ** 2):.0f}" stroke="#64748b" stroke-width="1.5"/>'
        body += f'<line x1="{256 - 54 * math.sqrt(1 - (i / 3.7) ** 2):.0f}" y1="{140 + i * 15}" x2="{256 + 54 * math.sqrt(1 - (i / 3.7) ** 2):.0f}" y2="{140 + i * 15}" stroke="#64748b" stroke-width="1.5"/>'
    w = text("Skate Night", "Yellowtail", 100, fill="#f472b6", stroke="#fff", sw=6)
    body += f'<g filter="url(#sh)">{fit(w, 60, 214, 392, 130)}</g>'
    return svg(body, d)


@net("Sleepover", TEENS, "teens", "comedy", "movies")
def sleepover():
    ink = "#3b0764"
    d = SH + lin("pil", [(0, "#fdf4ff"), (1, "#f5d0fe")])
    pillow = "M60 150 Q50 110 96 104 Q256 84 416 104 Q462 110 452 150 Q440 256 452 362 Q462 402 416 408 Q256 428 96 408 Q50 402 60 362 Q72 256 60 150 Z"
    body = f'<g filter="url(#sh)"><path d="{pillow}" fill="url(#pil)" stroke="{ink}" stroke-width="7"/></g>'
    body += '<path d="M96 120 Q256 104 416 120" fill="none" stroke="#e9d5ff" stroke-width="6"/>'
    w = _x("SLEEPOVER", "Fredoka", "#a855f7", ink, 0, 6, 6, 10, weight=700)
    body += f'<g filter="url(#sh)">{fit(w, 86, 196, 340, 96)}</g>'
    body += fit(
        text("MOVIES · SNACKS · NO SLEEP", "Fredoka", 40, weight=700, fill="#db2777", ls=4),
        126,
        306,
        260,
        24,
    )
    body += fit(text("z z z", "Fredoka", 100, weight=700, fill="#c084fc"), 344, 132, 70, 40)
    return svg(body, d)


@net("Boombox", TEENS, "teens", "music", "80s")
def boombox_logo():
    ink = "#0a0a0a"
    d = (
        SH
        + lin("bbx", [(0, "#4b5563"), (1, "#1f2937")])
        + rad("spk", [(0, "#6b7280"), (1, "#111827")])
    )
    body = f'<g filter="url(#sh)"><path d="M150 120 L150 92 Q150 76 166 76 L346 76 Q362 76 362 92 L362 120" fill="none" stroke="{ink}" stroke-width="14"/></g>'
    body += _panel(30, 120, 452, 280, "url(#bbx)", rx=26, edge=ink, sw=7)
    for cx in (124, 388):
        body += f'<circle cx="{cx}" cy="300" r="76" fill="url(#spk)" stroke="#9ca3af" stroke-width="6"/><circle cx="{cx}" cy="300" r="26" fill="#111827" stroke="#9ca3af" stroke-width="4"/>'
    body += '<rect x="214" y="250" width="84" height="100" rx="6" fill="#111827" stroke="#9ca3af" stroke-width="4"/>'
    body += '<circle cx="238" cy="300" r="10" fill="#9ca3af"/><circle cx="274" cy="300" r="10" fill="#9ca3af"/>'
    body += '<rect x="56" y="140" width="400" height="88" rx="8" fill="#0b0b0b"/>'
    body += fit(text("BOOMBOX", "Bungee", 100, fill="#facc15", ls=4), 76, 152, 360, 64)
    return svg(body, d)


@net("Flip Phone", TEENS, "teens", "2000s", "comedy")
def flip_phone():
    ink = "#0f172a"
    d = (
        SH
        + lin("lcd", [(0, "#d9f99d"), (1, "#a3e635")])
        + lin("ph", [(0, "#cbd5e1"), (1, "#64748b")])
    )
    body = _panel(40, 70, 432, 372, "url(#ph)", rx=40, edge=ink, sw=7)
    body += f'<rect x="72" y="104" width="368" height="248" rx="14" fill="url(#lcd)" stroke="{ink}" stroke-width="6"/>'
    for i in range(4):
        body += f'<rect x="{90 + i * 12}" y="{140 - i * 7}" width="8" height="{8 + i * 7}" fill="#1a2e05"/>'
    body += '<rect x="384" y="124" width="36" height="18" rx="3" fill="none" stroke="#1a2e05" stroke-width="3"/><rect x="388" y="128" width="20" height="10" fill="#1a2e05"/><rect x="420" y="129" width="4" height="8" fill="#1a2e05"/>'
    body += fit(text("FLIP", "VT323", 100, fill="#1a2e05"), 110, 160, 292, 90)
    body += fit(text("PHONE", "VT323", 100, fill="#1a2e05", ls=10), 130, 256, 252, 70)
    body += f'<rect x="196" y="372" width="120" height="44" rx="22" fill="#94a3b8" stroke="{ink}" stroke-width="5"/>'
    return svg(body, d)


@net("Dial-Up", TEENS, "teens", "90s", "comedy")
def dial_up():
    ink = "#000"
    d = SH + lin("tb", [(0, "#1e3a8a"), (1, "#3b82f6")], x2=1, y2=0)
    body = _panel(36, 96, 440, 320, "#c0c0c0", rx=2, edge=ink, sw=4)
    body += '<rect x="40" y="100" width="432" height="4" fill="#fff"/><rect x="40" y="100" width="4" height="312" fill="#fff"/>'
    body += '<rect x="48" y="108" width="416" height="40" fill="url(#tb)"/>'
    body += fit(
        text("Connecting...", "Inter", 40, weight=700, fill="#fff"), 60, 116, 180, 24, anchor="left"
    )
    for i, x in enumerate((382, 410, 438)):
        body += f'<rect x="{x}" y="114" width="24" height="26" fill="#c0c0c0" stroke="#000" stroke-width="2"/>'
    body += fit(text("×", "Inter", 40, weight=900, fill="#000"), 442, 116, 16, 20)
    body += fit(_x("DIAL-UP", "Archivo Black", "#1e3a8a", ink, 0, 0, 1, 0), 80, 170, 352, 100)
    body += '<rect x="80" y="300" width="352" height="34" fill="#fff" stroke="#808080" stroke-width="3"/>'
    for i in range(11):
        body += f'<rect x="{86 + i * 24}" y="306" width="18" height="22" fill="#1e3a8a"/>'
    body += fit(
        text("56K OF PURE NOSTALGIA", "Inter", 40, weight=700, fill="#000", ls=3), 130, 352, 252, 22
    )
    return svg(body, d)


@net("Away Message", TEENS, "teens", "2000s", "drama")
def away_message():
    ink = "#1c1917"
    d = SH
    body = f'<g filter="url(#sh)" transform="rotate(-4 256 256)"><rect x="70" y="60" width="372" height="392" fill="#fde68a" stroke="{ink}" stroke-width="4"/></g>'
    body += '<g transform="rotate(-4 256 256)"><rect x="70" y="60" width="372" height="62" fill="#facc15"/>'
    body += fit(text("AWAY MESSAGE", "Archivo Black", 100, fill=ink, ls=2), 96, 76, 320, 32)
    body += fit(text("brb", "Permanent Marker", 100, fill="#2563eb"), 140, 150, 232, 150)
    body += fit(
        text("(probably at the mall)", "Permanent Marker", 100, fill="#db2777"), 110, 320, 292, 44
    )
    body += f'<path d="M110 400 L402 400" stroke="{ink}" stroke-width="2" opacity=".3"/></g>'
    return svg(body, d)


@net("Whatever TV", TEENS, "teens", "comedy", "90s")
def whatever_tv():
    ink = "#0f172a"
    d = SH + lin("wtv", [(0, "#f9a8d4"), (1, "#c084fc")])
    body = f'<g filter="url(#sh)" transform="rotate(-6 256 256)"><rect x="40" y="120" width="432" height="230" rx="115" fill="url(#wtv)" stroke="{ink}" stroke-width="7"/></g>'
    w = text("whatever", "Permanent Marker", 100, fill="#fff", stroke=ink, sw=10)
    body += f'<g filter="url(#sh)" transform="rotate(-6 256 256)">{fit(w, 74, 160, 364, 120)}</g>'
    body += f'<g filter="url(#sh)"><rect x="324" y="322" width="116" height="66" rx="10" fill="#facc15" stroke="{ink}" stroke-width="6" transform="rotate(8 382 355)"/></g>'
    body += f'<g transform="rotate(8 382 355)">{fit(text("TV", "Archivo Black", 100, fill=ink), 350, 334, 64, 42)}</g>'
    return svg(body, d)


@net("Tween Screen", TEENS, "teens", "tweens", "comedy")
def tween_screen():
    ink = "#1e1b4b"
    d = SH + lin("tw1", [(0, "#a78bfa"), (0.5, "#f472b6"), (1, "#22d3ee")], x2=1, y2=1)
    body = _panel(56, 40, 400, 432, ink, rx=56)
    body += '<rect x="76" y="60" width="360" height="392" rx="40" fill="url(#tw1)"/>'
    body += '<rect x="216" y="70" width="80" height="12" rx="6" fill="' + ink + '"/>'
    for x, y, r in ((130, 120, 10), (390, 160, 7), (120, 400, 8), (380, 410, 12)):
        body += f'<path d="M{x} {y - r} Q{x + 2} {y - 2} {x + r} {y} Q{x + 2} {y + 2} {x} {y + r} Q{x - 2} {y + 2} {x - r} {y} Q{x - 2} {y - 2} {x} {y - r} Z" fill="#fff"/>'
    w = _x("TWEEN", "Unbounded", "#fff", ink, 0, 6, 6, 10, weight=900)
    body += f'<g filter="url(#sh)">{fit(w, 100, 150, 312, 100)}</g>'
    w2 = _x("SCREEN", "Unbounded", "#fef08a", ink, 0, 6, 6, 10, weight=900)
    body += f'<g filter="url(#sh)">{fit(w2, 100, 266, 312, 84)}</g>'
    return svg(body, d)


@net("Hall Pass", TEENS, "teens", "school", "comedy")
def hall_pass():
    ink = "#3b1d0e"
    d = SH + lin("wd", [(0, "#d6a368"), (0.5, "#b07a3e"), (1, "#8b5a2b")], x2=1, y2=0)
    paddle = "M92 120 Q92 70 142 70 L370 70 Q420 70 420 120 L420 290 Q420 340 370 340 L300 340 L300 452 Q300 476 276 476 L236 476 Q212 476 212 452 L212 340 L142 340 Q92 340 92 290 Z"
    body = f'<g filter="url(#sh)"><path d="{paddle}" fill="url(#wd)" stroke="{ink}" stroke-width="7"/></g>'
    for i in range(6):
        y = 90 + i * 42
        body += f'<path d="M106 {y} Q256 {y + (8 if i % 2 else -6)} 406 {y}" fill="none" stroke="{ink}" stroke-width="2" opacity=".25"/>'
    body += '<circle cx="256" cy="440" r="12" fill="#1c1917"/>'
    body += fit(
        text("HALL", "Alfa Slab One", 100, fill="#fff7ed", stroke=ink, sw=8), 140, 96, 232, 100
    )
    body += fit(
        text("PASS", "Alfa Slab One", 100, fill="#dc2626", stroke=ink, sw=8), 140, 204, 232, 100
    )
    body += fit(text("RM 108", "Oswald", 40, weight=700, fill=ink, ls=6), 216, 310, 80, 20)
    return svg(body, d)


@net("Locker Talk", TEENS, "teens", "drama", "school")
def locker_talk():
    ink = "#0f172a"
    d = SH + lin("lk", [(0, "#3b82f6"), (1, "#1d4ed8")], x2=1, y2=0)
    body = _panel(96, 30, 320, 452, "url(#lk)", rx=8, edge=ink, sw=6)
    body += '<rect x="112" y="46" width="288" height="420" rx="4" fill="none" stroke="#93c5fd" stroke-width="3"/>'
    for i in range(5):
        body += f'<rect x="166" y="{70 + i * 18}" width="180" height="8" rx="4" fill="{ink}" opacity=".7"/>'
    for i in range(5):
        body += f'<rect x="166" y="{380 + i * 14}" width="180" height="6" rx="3" fill="{ink}" opacity=".7"/>'
    body += f'<g filter="url(#sh)"><rect x="56" y="186" width="400" height="140" rx="10" fill="#facc15" stroke="{ink}" stroke-width="7"/></g>'
    body += fit(text("LOCKER", "Black Ops One", 100, fill=ink, ls=4), 86, 200, 340, 64)
    body += fit(text("TALK", "Black Ops One", 100, fill="#1d4ed8", ls=18), 156, 270, 200, 44)
    body += f'<circle cx="370" cy="356" r="16" fill="#e2e8f0" stroke="{ink}" stroke-width="5"/>'
    return svg(body, d)


@net("The Mall", TEENS, "teens", "90s", "hangout")
def the_mall():
    ink = "#0f172a"
    d = SH + lin("mal", [(0, "#14b8a6"), (1, "#0f766e")])
    body = _panel(36, 80, 440, 352, "url(#mal)", rx=24, edge=ink, sw=6)
    body += '<circle cx="410" cy="140" r="44" fill="#f472b6" opacity=".9"/>'
    body += '<polygon points="60,420 140,300 200,420" fill="#facc15" opacity=".85"/>'
    body += '<path d="M330 400 q20 -26 40 0 t40 0" fill="none" stroke="#a78bfa" stroke-width="10" stroke-linecap="round"/>'
    body += fit(text("the", "Pacifico", 100, fill="#fde047", stroke=ink, sw=8), 110, 104, 160, 80)
    w = _x("MALL", "Righteous", "#fff", ink, 0, 8, 8, 12, ls=8)
    body += f'<g filter="url(#sh)">{fit(w, 76, 180, 360, 160)}</g>'
    return svg(body, d)


@net("Arcade", TEENS, "teens", "80s", "games")
def arcade():
    ink = "#000"
    d = SH
    body = _panel(36, 80, 440, 352, "#0b0b2a", rx=8, edge=ink, sw=6)
    for x in range(48, 464, 16):
        for y in (92, 404):
            body += f'<rect x="{x}" y="{y}" width="10" height="10" fill="{"#f472b6" if (x // 16) % 2 else "#22d3ee"}"/>'
    w = text("ARCADE", "Press Start 2P", 100, fill="#facc15", stroke="#dc2626", sw=8)
    body += f'<g filter="url(#sh)">{fit(w, 70, 160, 372, 100)}</g>'
    body += fit(text("INSERT COIN", "Press Start 2P", 40, fill="#fff"), 140, 300, 232, 30)
    body += '<circle cx="256" cy="366" r="18" fill="#facc15" stroke="#b45309" stroke-width="4"/>'
    body += fit(text("¢", "Press Start 2P", 40, fill="#b45309"), 248, 356, 16, 20)
    return svg(body, d)


@net("B-Side", TEENS, "teens", "music", "90s")
def b_side():
    ink = "#111827"
    d = SH + lin("cas", [(0, "#374151"), (1, "#111827")])
    body = _panel(30, 96, 452, 320, "url(#cas)", rx=22, edge="#000", sw=6)
    body += '<rect x="56" y="118" width="400" height="196" rx="10" fill="#fef3c7"/>'
    body += '<rect x="56" y="118" width="400" height="24" rx="10" fill="#f97316"/><rect x="56" y="132" width="400" height="10" fill="#f97316"/>'
    body += fit(text("B-SIDE", "Permanent Marker", 100, fill="#dc2626"), 86, 150, 340, 88)
    body += f'<rect x="146" y="246" width="220" height="56" rx="28" fill="{ink}"/>'
    for cx in (190, 322):
        body += f'<circle cx="{cx}" cy="274" r="20" fill="#f3f4f6"/><circle cx="{cx}" cy="274" r="8" fill="{ink}"/>'
    body += '<path d="M130 416 L160 340 L352 340 L382 416 Z" fill="#1f2937" stroke="#000" stroke-width="5"/>'
    body += fit(
        text("DEEP CUTS", "Oswald", 40, weight=700, fill="#fef3c7", ls=8), 176, 360, 160, 34
    )
    return svg(body, d)


@net("Pep Rally", TEENS, "teens", "sports", "school")
def pep_rally():
    ink = "#1c1917"
    d = SH + lin("meg", [(0, "#ef4444"), (1, "#991b1b")])
    cone = "M60 200 L440 80 Q470 256 440 432 L60 312 Z"
    body = f'<g filter="url(#sh)"><path d="{cone}" fill="url(#meg)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/></g>'
    body += f'<rect x="30" y="196" width="40" height="120" rx="10" fill="#fef3c7" stroke="{ink}" stroke-width="6"/>'
    body += '<path d="M440 80 Q470 256 440 432" fill="none" stroke="#fef3c7" stroke-width="14"/>'
    body += '<path d="M100 220 L420 128" stroke="#fef3c7" stroke-width="5" opacity=".6"/><path d="M100 292 L420 384" stroke="#fef3c7" stroke-width="5" opacity=".6"/>'
    body += fit(text("PEP", "Graduate", 100, fill="#fef3c7"), 150, 170, 200, 76)
    body += fit(text("RALLY", "Graduate", 100, fill="#fef3c7", ls=6), 120, 256, 290, 76)
    return svg(body, d)


@net("Promposal", TEENS, "teens", "romance", "school")
def promposal():
    d = (
        SH
        + lin("pr", [(0, "#831843"), (1, "#500724")])
        + lin("prg", [(0, "#fff3c4"), (0.5, "#e2b13c"), (1, "#a8741a")])
    )
    body = _panel(46, 70, 420, 372, "url(#pr)", rx=16, edge="#2a0412", sw=5)
    body += '<rect x="66" y="90" width="380" height="332" rx="8" fill="none" stroke="url(#prg)" stroke-width="3"/>'
    body += '<rect x="76" y="100" width="360" height="312" rx="4" fill="none" stroke="url(#prg)" stroke-width="1.5"/>'
    body += fit(
        text("WILL YOU GO TO PROM?", "Montserrat", 40, weight=600, fill="#fbcfe8", ls=6),
        146,
        132,
        220,
        22,
    )
    body += f'<g filter="url(#sh)">{fit(text("Promposal", "Great Vibes", 100, fill="url(#prg)"), 86, 166, 340, 140)}</g>'
    body += f'<polygon points="{star(256, 352, 18, 7)}" fill="url(#prg)"/>'
    body += '<line x1="146" y1="352" x2="220" y2="352" stroke="#e2b13c" stroke-width="2"/><line x1="292" y1="352" x2="366" y2="352" stroke="#e2b13c" stroke-width="2"/>'
    return svg(body, d)


@net("Cafeteria", TEENS, "teens", "school", "comedy")
def cafeteria():
    ink = "#1f2937"
    d = SH + lin("tray", [(0, "#fb923c"), (1, "#ea580c")])
    body = _panel(36, 96, 440, 320, "url(#tray)", rx=36, edge=ink, sw=7)
    body += '<rect x="60" y="120" width="392" height="170" rx="18" fill="#fdba74" stroke="#c2410c" stroke-width="4"/>'
    for x, lab in ((60, "MON"), (196, "PIZZA"), (332, "12:00")):
        body += f'<rect x="{x}" y="306" width="120" height="86" rx="16" fill="#fdba74" stroke="#c2410c" stroke-width="4"/>'
        body += fit(text(lab, "Oswald", 40, weight=700, fill=ink, ls=4), x + 16, 332, 88, 34)
    body += fit(_x("CAFETERIA", "Archivo Black", "#fff", ink, 0, 6, 6, 10), 80, 150, 352, 110)
    return svg(body, d)


@net("Bus Stop", TEENS, "teens", "school", "drama")
def bus_stop():
    ink = "#0f172a"
    d = SH
    body = f'<g filter="url(#sh)"><rect x="244" y="250" width="24" height="230" fill="#94a3b8" stroke="{ink}" stroke-width="5"/></g>'
    body += f'<g filter="url(#sh)"><circle cx="256" cy="200" r="170" fill="#facc15" stroke="{ink}" stroke-width="8"/></g>'
    body += f'<circle cx="256" cy="200" r="152" fill="none" stroke="{ink}" stroke-width="4"/>'
    bus = f'<rect x="20" y="40" width="160" height="110" rx="18" fill="{ink}"/><rect x="34" y="56" width="132" height="44" rx="6" fill="#facc15"/>'
    bus += f'<line x1="100" y1="56" x2="100" y2="100" stroke="{ink}" stroke-width="6"/><circle cx="56" cy="156" r="16" fill="{ink}"/><circle cx="144" cy="156" r="16" fill="{ink}"/>'
    body += centred(bus, 256, 130, 110)
    body += fit(text("BUS STOP", "Archivo Black", 100, fill=ink, ls=4), 120, 214, 272, 66)
    body += fit(text("RIDING HOME", "Oswald", 40, weight=700, fill=ink, ls=8), 186, 292, 140, 24)
    return svg(body, d)


@net("Glow Stick", TEENS, "teens", "music", "party")
def glow_stick():
    d = SH
    cols = (("#a3e635", "gs1"), ("#f472b6", "gs2"), ("#22d3ee", "gs3"))
    for c, gid in cols:
        d += glow(gid, c, blur=9, strength=2)
    body = _panel(36, 56, 440, 400, "#0a0a14", rx=30, edge="#000", sw=5)
    for i, (c, gid) in enumerate(cols):
        x = 160 + i * 96
        body += f'<g transform="rotate({-18 + i * 18} {x} 190)"><g filter="url(#{gid})"><rect x="{x - 14}" y="80" width="28" height="200" rx="14" fill="{c}"/></g>'
        body += (
            f'<rect x="{x - 8}" y="92" width="8" height="170" rx="4" fill="#fff" opacity=".7"/></g>'
        )
    w = text("GLOW STICK", "Bungee", 100, fill="#fff", stroke="#000", sw=6)
    body += f'<g filter="url(#sh)">{fit(w, 66, 320, 380, 90)}</g>'
    return svg(body, d)


@net("Cool Kids", TEENS, "teens", "comedy", "90s")
def cool_kids():
    ink = "#020617"
    d = SH + lin("ck", [(0, "#67e8f9"), (1, "#3b82f6")])
    body = f'<g filter="url(#sh)" transform="rotate(-8 256 256)"><rect x="40" y="110" width="432" height="292" rx="40" fill="{ink}"/></g>'
    body += '<g transform="rotate(-8 256 256)"><rect x="56" y="126" width="400" height="260" rx="28" fill="none" stroke="#67e8f9" stroke-width="4"/>'
    body += fit(
        text("COOL", "Outfit", 100, weight=900, fill="url(#ck)", style="italic"), 80, 150, 352, 140
    )
    body += '<rect x="166" y="296" width="180" height="62" rx="6" fill="#facc15"/>'
    body += (
        fit(text("KIDS", "Outfit", 100, weight=900, fill=ink, ls=12), 186, 304, 140, 46) + "</g>"
    )
    return svg(body, d)


@net("Hangout", TEENS, "teens", "comedy", "hangout")
def hangout():
    ink = "#1c1917"
    d = SH + lin("hg", [(0, "#a855f7"), (1, "#6d28d9")])
    body = f'<rect x="40" y="40" width="432" height="16" rx="8" fill="#78716c" stroke="{ink}" stroke-width="4"/>'
    for x in (130, 382):
        for k in range(5):
            body += f'<ellipse cx="{x}" cy="{70 + k * 18}" rx="6" ry="9" fill="none" stroke="#a8a29e" stroke-width="4"/>'
    body += f'<g filter="url(#sh)"><rect x="56" y="150" width="400" height="250" rx="28" fill="url(#hg)" stroke="{ink}" stroke-width="7"/></g>'
    body += '<rect x="72" y="166" width="368" height="218" rx="18" fill="none" stroke="#e9d5ff" stroke-width="3"/>'
    body += f'<g filter="url(#sh)">{fit(_x("HANGOUT", "Lilita One", "#fff", ink, 0, 6, 6, 10, ls=4), 86, 210, 340, 96)}</g>'
    body += fit(
        text("COME AS YOU ARE", "Fredoka", 40, weight=700, fill="#facc15", ls=6), 156, 320, 200, 28
    )
    return svg(body, d)


@net("Group Chat", TEENS, "teens", "comedy", "2000s")
def group_chat():
    ink = "#0f172a"
    d = SH
    body = '<g filter="url(#sh)">'
    body += f'<path d="M60 70 L300 70 Q330 70 330 100 L330 190 Q330 220 300 220 L130 220 L90 254 L96 220 L60 220 Q30 220 30 190 L30 100 Q30 70 60 70 Z" fill="#22c55e" stroke="{ink}" stroke-width="6"/>'
    body += f'<path d="M212 160 L452 160 Q482 160 482 190 L482 280 Q482 310 452 310 L416 310 L422 344 L382 310 L212 310 Q182 310 182 280 L182 190 Q182 160 212 160 Z" fill="#3b82f6" stroke="{ink}" stroke-width="6"/>'
    body += "</g>"
    for i in range(3):
        body += f'<circle cx="{110 + i * 40}" cy="130" r="12" fill="#fff"/>'
    body += fit(_x("GROUP", "Archivo Black", "#fff", ink, 0, 5, 5, 8), 214, 196, 240, 76)
    body += f'<g filter="url(#sh)"><rect x="70" y="350" width="372" height="96" rx="48" fill="#f472b6" stroke="{ink}" stroke-width="6"/></g>'
    body += fit(text("CHAT", "Archivo Black", 100, fill="#fff", ls=14), 150, 366, 212, 64)
    return svg(body, d)


@net("Crush", TEENS, "teens", "romance", "drama")
def crush():
    heart = '<path d="M100 186 C40 146 8 112 8 72 C8 40 34 16 64 16 C82 16 94 28 100 40 C106 28 118 16 136 16 C166 16 192 40 192 72 C192 112 160 146 100 186 Z" fill="#ec4899" stroke="#4a044e" stroke-width="10"/>'
    return L.letter_swap(
        "CR",
        heart,
        "SH",
        font="Unbounded",
        weight=900,
        ink="#fdf2f8",
        edge="#4a044e",
        sub="TEEN ROMANCE",
        sub_font="Fredoka",
        sub_ink="#f9a8d4",
        sym_size=80,
        sym_dy=-36,
        extra_back='<g filter="url(#sh)"><rect x="30" y="120" width="452" height="290" rx="145" fill="#f9a8d4" stroke="#4a044e" stroke-width="7"/></g>',
        box=(60, 170, 392, 140),
        sub_box=(150, 326, 212, 34),
    )


@net("Diary", TEENS, "teens", "drama", "romance")
def diary():
    ink = "#2e1065"
    d = (
        SH
        + lin("dia", [(0, "#a855f7"), (1, "#6b21a8")])
        + lin("dg", [(0, "#fff3c4"), (0.5, "#e2b13c"), (1, "#a8741a")])
    )
    body = _panel(80, 36, 340, 440, "url(#dia)", rx=18, edge=ink, sw=6)
    body += (
        '<rect x="400" y="60" width="24" height="392" rx="6" fill="#fef3c7" stroke="'
        + ink
        + '" stroke-width="4"/>'
    )
    for y in range(72, 448, 18):
        body += f'<line x1="404" y1="{y}" x2="420" y2="{y}" stroke="#d6d3d1" stroke-width="2"/>'
    body += f'<rect x="380" y="214" width="76" height="84" rx="10" fill="url(#dg)" stroke="{ink}" stroke-width="5"/>'
    body += f'<path d="M418 240 C404 230 398 246 418 262 C438 246 432 230 418 240 Z" fill="{ink}"/>'
    body += '<rect x="112" y="68" width="268" height="376" rx="10" fill="none" stroke="url(#dg)" stroke-width="3"/>'
    body += f'<g filter="url(#sh)">{fit(text("Diary", "Great Vibes", 100, fill="url(#dg)"), 120, 156, 250, 150)}</g>'
    body += fit(text("KEEP OUT!", "Permanent Marker", 100, fill="#fbcfe8"), 166, 334, 160, 40)
    return svg(body, d)


@net("Bestie", TEENS, "teens", "comedy", "friendship")
def bestie():
    ink = "#1e1b4b"
    d = SH + lin("bst", [(0, "#fdf2f8"), (1, "#ede9fe")])
    body = _panel(30, 96, 452, 320, "url(#bst)", rx=40, edge=ink, sw=6)
    cols = ("#f472b6", "#a78bfa", "#38bdf8", "#4ade80", "#facc15", "#fb923c")

    def yat(x):
        return 210 + 50 * (1 - ((x - 256) / 230) ** 2)

    body += f'<path d="M30 210 Q256 310 482 210" fill="none" stroke="{ink}" stroke-width="5"/>'
    for x in (46, 466):
        body += f'<circle cx="{x}" cy="{yat(x):.0f}" r="8" fill="#fff" stroke="{ink}" stroke-width="3"/>'
    for ch, c, x in zip("BESTIE", cols, (86, 154, 222, 290, 358, 426), strict=True):
        y = yat(x)
        body += f'<g filter="url(#sh)" transform="rotate({(x - 256) / 10:.0f} {x} {y:.0f})"><rect x="{x - 32}" y="{y - 32:.0f}" width="64" height="64" rx="12" fill="{c}" stroke="{ink}" stroke-width="5"/>'
        body += (
            fit(text(ch, "Lilita One", 100, fill="#fff", stroke=ink, sw=6), x - 22, y - 24, 44, 48)
            + "</g>"
        )
    body += fit(
        text("FRIENDS FOREVER", "Fredoka", 40, weight=700, fill="#db2777", ls=8), 126, 330, 260, 34
    )
    return svg(body, d)


@net("Skate Park", TEENS, "teens", "sports", "90s")
def skate_park():
    ink = "#0a0a0a"
    d = SH + lin("deck", [(0, "#f97316"), (0.5, "#facc15"), (1, "#22c55e")], x2=1, y2=0)
    body = '<g transform="rotate(-14 256 256)">'
    body += f'<g filter="url(#sh)"><rect x="30" y="170" width="452" height="150" rx="75" fill="url(#deck)" stroke="{ink}" stroke-width="8"/></g>'
    for x in (120, 392):
        body += f'<rect x="{x - 30}" y="320" width="60" height="16" rx="5" fill="#9ca3af" stroke="{ink}" stroke-width="4"/>'
        for dx in (-22, 22):
            body += f'<circle cx="{x + dx}" cy="346" r="15" fill="#fef3c7" stroke="{ink}" stroke-width="5"/>'
    body += fit(_x("SKATE PARK", "Bangers", "#fff", ink, 3, 5, 5, 10, ls=4), 70, 196, 372, 100)
    body += "</g>"
    return svg(body, d)


@net("Garage Band", TEENS, "teens", "music", "comedy")
def garage_band():
    ink = "#111827"
    d = SH + lin("gd", [(0, "#e5e7eb"), (1, "#9ca3af")])
    body = f'<g filter="url(#sh)"><path d="M30 150 L256 50 L482 150 L482 470 L30 470 Z" fill="#7f1d1d" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/></g>'
    body += f'<rect x="70" y="170" width="372" height="300" fill="url(#gd)" stroke="{ink}" stroke-width="6"/>'
    for y in range(230, 470, 60):
        body += f'<line x1="70" y1="{y}" x2="442" y2="{y}" stroke="#6b7280" stroke-width="4"/>'
    body += f'<g filter="url(#sh)">{fit(text("GARAGE", "Black Ops One", 100, fill=ink, ls=6), 96, 180, 320, 70)}</g>'
    pick = "M256 470 C190 400 170 340 196 300 C220 270 292 270 316 300 C342 340 322 400 256 470 Z"
    body += f'<g filter="url(#sh)" transform="translate(0 -14)"><path d="{pick}" fill="#dc2626" stroke="{ink}" stroke-width="6"/></g>'
    body += fit(text("BAND", "Black Ops One", 100, fill="#fff"), 204, 306, 104, 50)
    return svg(body, d)


@net("Skip Day", TEENS, "teens", "comedy", "school")
def skip_day():
    ink = "#052e16"
    d = SH + glow("exg", "#4ade80", blur=7, strength=2)
    body = f'<g filter="url(#sh)"><rect x="40" y="130" width="432" height="230" rx="18" fill="#14532d" stroke="{ink}" stroke-width="8"/></g>'
    body += '<rect x="60" y="150" width="392" height="190" rx="10" fill="#052e16"/>'
    w = text("SKIP DAY", "Archivo Black", 100, fill="#bbf7d0", ls=6)
    body += f'<g filter="url(#exg)">{fit(w, 80, 178, 352, 92)}</g>{fit(w, 80, 178, 352, 92)}'
    body += '<g filter="url(#exg)"><path d="M190 300 L310 300 L310 286 L340 308 L310 330 L310 316 L190 316 Z" fill="#4ade80"/></g>'
    for x in (100, 412):
        body += f'<rect x="{x - 6}" y="100" width="12" height="34" fill="#475569"/>'
    return svg(body, d)


@net("Report Card", TEENS, "teens", "school", "comedy")
def report_card():
    ink = "#1f2937"
    d = SH
    body = f'<g filter="url(#sh)"><rect x="70" y="40" width="372" height="432" rx="8" fill="#fefce8" stroke="{ink}" stroke-width="5"/></g>'
    body += '<rect x="70" y="40" width="372" height="80" rx="8" fill="#1e3a8a"/><rect x="70" y="100" width="372" height="20" fill="#1e3a8a"/>'
    body += fit(text("REPORT CARD", "Archivo Black", 100, fill="#fff", ls=4), 96, 60, 320, 44)
    for i, (subj, g) in enumerate((("MATH", "B"), ("SCIENCE", "A"), ("HISTORY", "B+"))):
        y = 144 + i * 44
        body += f'<line x1="96" y1="{y + 34}" x2="300" y2="{y + 34}" stroke="#93c5fd" stroke-width="2"/>'
        body += fit(
            text(subj, "Oswald", 40, weight=600, fill=ink, ls=3, anchor="start"),
            100,
            y + 4,
            120,
            26,
            anchor="left",
        )
        body += fit(text(g, "Permanent Marker", 40, fill="#2563eb"), 250, y, 40, 30)
    body += '<ellipse cx="256" cy="380" rx="120" ry="70" fill="none" stroke="#dc2626" stroke-width="8" transform="rotate(-6 256 380)"/>'
    body += fit(text("A+", "Permanent Marker", 100, fill="#dc2626"), 180, 326, 152, 110)
    return svg(body, d)


@net("Teen Idol", TEENS, "teens", "music", "pop")
def teen_idol():
    ink = "#1c1917"
    d = SH + lin("mag", [(0, "#f9a8d4"), (1, "#ec4899")])
    body = _panel(70, 30, 372, 452, "url(#mag)", rx=6, edge=ink, sw=5)
    body += fit(
        text("TEEN IDOL", "Anton", 100, fill="#fff", stroke=ink, sw=6, ls=2), 90, 46, 332, 104
    )
    body += '<rect x="90" y="160" width="332" height="8" fill="#facc15"/>'
    for i, w in enumerate((200, 160, 220, 140)):
        body += f'<rect x="96" y="{196 + i * 40}" width="{w}" height="22" rx="4" fill="#fff" opacity=".85"/>'
    body += f'<g filter="url(#sh)"><polygon points="{star(356, 300, 74, 54, 14)}" fill="#facc15" stroke="{ink}" stroke-width="5"/></g>'
    body += fit(text("EXCLUSIVE!", "Anton", 100, fill="#dc2626"), 304, 284, 104, 32)
    body += fit(
        text("POSTERS · QUIZZES · GOSSIP", "Oswald", 40, weight=700, fill=ink, ls=4),
        96,
        420,
        320,
        26,
    )
    return svg(body, d)


@net("Spring Break", TEENS, "teens", "comedy", "beach")
def spring_break():
    ink = "#1e1b4b"
    d = SH + lin("sbk", [(0, "#f472b6"), (0.5, "#fb923c"), (1, "#fde047")])
    body = '<defs><clipPath id="sbc"><rect x="36" y="56" width="440" height="400" rx="40"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "url(#sbk)", rx=40, edge=ink, sw=6)
    body += (
        '<g clip-path="url(#sbc)"><circle cx="256" cy="300" r="110" fill="#fef9c3" opacity=".9"/>'
    )
    for i in range(4):
        body += (
            f'<rect x="146" y="{250 + i * 18}" width="220" height="{4 + i * 2}" fill="url(#sbk)"/>'
        )
    body += '<rect x="36" y="350" width="440" height="110" fill="#0891b2"/>'
    body += '<path d="M36 360 q30 -12 60 0 t60 0 t60 0 t60 0 t60 0 t60 0 t60 0 t60 0" fill="none" stroke="#a5f3fc" stroke-width="5"/>'
    for x, s_ in ((90, 1), (430, -1)):
        body += f'<path d="M{x} 360 Q{x + s_ * 10} 260 {x - s_ * 10} 170" fill="none" stroke="{ink}" stroke-width="10"/>'
        for a in (-60, -20, 20, 60, 100):
            body += f'<path d="M{x - s_ * 10} 170 q{s_ * 50 * math.cos(math.radians(a)):.0f} {-30 + 40 * math.sin(math.radians(a)):.0f} {s_ * 90 * math.cos(math.radians(a)):.0f} {10 + 60 * math.sin(math.radians(a)):.0f}" fill="none" stroke="{ink}" stroke-width="12" stroke-linecap="round"/>'
    body += "</g>"
    w = text("SPRING BREAK", "Racing Sans One", 100, fill="#fff", stroke=ink, sw=12, style="italic")
    body += f'<g filter="url(#sh)">{fit(extrude(w, 4, 7, 6, ink) + w, 50, 96, 412, 110)}</g>'
    return svg(body, d)


def logos() -> list[Logo]:
    return [Logo(sid, name, cat, fn, tags) for sid, name, cat, tags, fn in STATIONS]
