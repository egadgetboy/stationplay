"""Movie channels: a big set of invented movie-channel brands, one per kind
of movie station (hits, action, comedy, horror, sci-fi, thrillers,
romance, classics, video-store nights, drive-in and cult, epics, war and
westerns, indie and world, family, musicals). None borrows a real movie
channel's, studio's, theatre chain's or video store's name, marks,
colours or lettering."""

from __future__ import annotations

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
    measure,
    pts,
    rad,
    rough,
    shadow,
    skew,
    star,
    svg,
    text,
    tilt,
)
from symbols import P, centred

SH = shadow("sh", dy=6, blur=6, opacity=0.45)
MOVIES = "Movie channels"
CHANNELS: list[tuple[str, str, str, list[str], object]] = []  # (id, name, category, tags, draw)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", "and")).strip("-")


def net(name: str, category: str, *tags: str):
    def add(fn):
        CHANNELS.append((slug(name), name, category, list(tags), fn))
        return fn

    return add


# ======================================================================= helpers


def _panel(x, y, w, h, fill, rx=18, edge=None, sw=0):
    st = f' stroke="{edge}" stroke-width="{sw}"' if edge else ""
    return f'<g filter="url(#sh)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{st}/></g>'


def _sh(inner: str) -> str:
    return f'<g filter="url(#sh)">{inner}</g>'


def _t(s, font, fill="#fff", weight=400, stroke=None, sw=0, ls=0, style="normal", size=100):
    return text(s, font, size, weight=weight, fill=fill, stroke=stroke, sw=sw, ls=ls, style=style)


def _ext(t: str, dx: float, dy: float, color: str, steps: int = 8) -> str:
    return extrude(t, dx, dy, steps, color) + t


def _sparkle(cx, cy, r, fill="#fff", thin=0.22) -> str:
    """A four-pointed glint."""
    return f'<polygon points="{star(cx, cy, r, r * thin, 4)}" fill="{fill}"/>'


def _swoosh(cx, cy, r, a0, a1, w, fill, edge=None, sw=0, n=40) -> str:
    """A crescent that tapers from nothing at a0 to w thick at a1 (degrees)."""
    outer, inner = [], []
    for i in range(n + 1):
        t = i / n
        a = math.radians(a0 + (a1 - a0) * t)
        th = w * math.sin(t * math.pi * 0.5) ** 1.2
        outer.append((cx + (r + th / 2) * math.cos(a), cy + (r + th / 2) * math.sin(a)))
        inner.append((cx + (r - th / 2) * math.cos(a), cy + (r - th / 2) * math.sin(a)))
    st = f' stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"' if edge else ""
    return f'<polygon points="{pts(outer + inner[::-1])}" fill="{fill}"{st}/>'


def _rays(cx, cy, r, n, fill, opacity=0.1, width=0.09, rot=0) -> str:
    out = ""
    for k in range(n):
        a = math.radians(rot + k * 360 / n)
        out += f'<polygon points="{cx},{cy} {cx + r * math.cos(a - width):.1f},{cy + r * math.sin(a - width):.1f} {cx + r * math.cos(a + width):.1f},{cy + r * math.sin(a + width):.1f}" fill="{fill}" opacity="{opacity}"/>'
    return out


def _bulbs(points, r=6, fill="#fff3b0", ring="#b36b00") -> str:
    return "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{ring}" stroke-width="1.5"/>'
        for x, y in points
    )


def _halftone(x0, y0, x1, y1, step, r, fill, opacity=0.25) -> str:
    out = ""
    for j, y in enumerate(range(int(y0), int(y1), step)):
        off = step / 2 if j % 2 else 0
        for x in range(int(x0), int(x1), step):
            out += f'<circle cx="{x + off:.0f}" cy="{y}" r="{r}"/>'
    return f'<g fill="{fill}" opacity="{opacity}">{out}</g>'


# ======================================================================= pictures
# Drawn on a 200x200 box like symbols.py, from a P palette.


def soda_cup(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round"'
    s = f'<path d="M118 34 L132 6 L144 10 L132 38" fill="{p.b}" {o}/>'
    s += f'<path d="M40 44 L160 44 L144 194 L56 194 Z" fill="{p.l}" {o}/>'
    s += f'<path d="M44 80 Q100 64 156 80 L151 128 Q100 112 49 128 Z" fill="{p.a}"/>'
    s += f'<path d="M52 150 Q100 136 148 150 L146 166 Q100 152 54 166 Z" fill="{p.c}"/>'
    s += f'<path d="M40 44 L160 44 L144 194 L56 194 Z" fill="none" {o}/>'
    s += f'<path d="M30 34 Q100 18 170 34 L166 48 Q100 36 34 48 Z" fill="{p.c}" {o}/>'
    s += '<path d="M62 60 L72 176" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity=".5"/>'
    return s


def skull(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round"'
    s = f'<path d="M100 18 C150 18 180 52 178 94 C177 118 166 132 154 140 L150 170 Q150 184 136 184 L64 184 Q50 184 50 170 L46 140 C34 132 23 118 22 94 C20 52 50 18 100 18 Z" fill="{p.l}" {o}/>'
    s += f'<path d="M58 88 Q60 70 80 72 Q96 76 92 96 Q88 114 70 112 Q56 108 58 88 Z" fill="{p.k}"/>'
    s += f'<path d="M142 88 Q140 70 120 72 Q104 76 108 96 Q112 114 130 112 Q144 108 142 88 Z" fill="{p.k}"/>'
    s += f'<path d="M100 118 L90 140 L110 140 Z" fill="{p.k}"/>'
    for x in (74, 92, 110, 128):
        s += f'<rect x="{x - 2}" y="152" width="4" height="30" fill="{p.k}"/>'
    s += '<path d="M50 60 Q60 36 90 30" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity=".7"/>'
    return s


def lyre(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"'
    s = f'<path d="M58 176 L142 176 L136 162 L64 162 Z" fill="{p.a}" {o}/>'
    s += f'<path d="M64 162 C28 130 30 70 52 46 C62 36 72 40 70 52 C66 70 80 76 86 60 M136 162 C172 130 170 70 148 46 C138 36 128 40 130 52 C134 70 120 76 114 60" fill="none" stroke="{p.k}" stroke-width="20" stroke-linecap="round"/>'
    s += f'<path d="M64 162 C28 130 30 70 52 46 C62 36 72 40 70 52 C66 70 80 76 86 60 M136 162 C172 130 170 70 148 46 C138 36 128 40 130 52 C134 70 120 76 114 60" fill="none" stroke="{p.a}" stroke-width="10" stroke-linecap="round"/>'
    s += f'<rect x="52" y="54" width="96" height="14" rx="7" fill="{p.b}" {o}/>'
    for x in (80, 93, 107, 120):
        s += f'<line x1="{x}" y1="68" x2="{x}" y2="162" stroke="{p.l}" stroke-width="3"/>'
    return s


def robot_head(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round"'
    s = f'<line x1="100" y1="40" x2="100" y2="14" stroke="{p.k}" stroke-width="6"/><circle cx="100" cy="12" r="10" fill="{p.a}" {o}/>'
    s += f'<rect x="10" y="80" width="20" height="46" rx="6" fill="{p.b}" {o}/><rect x="170" y="80" width="20" height="46" rx="6" fill="{p.b}" {o}/>'
    s += f'<rect x="28" y="38" width="144" height="124" rx="26" fill="{p.l}" {o}/>'
    s += f'<rect x="44" y="60" width="112" height="56" rx="18" fill="{p.k}"/>'
    s += f'<circle cx="74" cy="88" r="16" fill="{p.c}"/><circle cx="126" cy="88" r="16" fill="{p.c}"/>'
    s += '<circle cx="69" cy="83" r="5" fill="#fff"/><circle cx="121" cy="83" r="5" fill="#fff"/>'
    s += f'<rect x="60" y="128" width="80" height="20" rx="6" fill="{p.a}" {o}/>'
    for x in (80, 100, 120):
        s += f'<line x1="{x}" y1="130" x2="{x}" y2="146" stroke="{p.k}" stroke-width="3"/>'
    for x, y in ((40, 50), (160, 50), (40, 150), (160, 150)):
        s += f'<circle cx="{x}" cy="{y}" r="4" fill="{p.k}" opacity=".6"/>'
    s += '<path d="M40 54 Q42 44 56 42" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".8"/>'
    return s


def tap_shoes(p: P) -> str:
    def shoe(x, y, flip):
        sx = -1 if flip else 1
        g = f'<g transform="translate({x} {y}) scale({sx} 1)">'
        g += f'<path d="M-70 10 Q-72 -26 -46 -30 Q-20 -30 0 -18 Q30 -2 58 2 Q76 6 74 22 L-66 22 Q-72 20 -70 10 Z" fill="{p.k}" stroke="{p.k}" stroke-width="4"/>'
        g += f'<path d="M-40 -24 Q-20 -24 -4 -14" fill="none" stroke="{p.l}" stroke-width="4" stroke-linecap="round" opacity=".6"/>'
        g += f'<path d="M-14 -16 Q-4 -30 8 -14 Q-4 -22 -14 -16 Z" fill="{p.a}"/><circle cx="-3" cy="-17" r="5" fill="{p.a}"/>'
        g += f'<rect x="30" y="22" width="42" height="9" rx="3" fill="{p.b}" stroke="{p.k}" stroke-width="3"/>'
        g += f'<rect x="-68" y="22" width="30" height="9" rx="3" fill="{p.b}" stroke="{p.k}" stroke-width="3"/>'
        g += '<path d="M30 0 Q50 2 62 8" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" opacity=".5"/>'
        return g + "</g>"

    return shoe(78, 70, True) + shoe(118, 132, False)


def loveseat(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round"'
    heart = "M100 150 C60 120 18 96 22 58 C26 26 70 18 100 48 C130 18 174 26 178 58 C182 96 140 120 100 150 Z"
    s = f'<path d="{heart}" fill="{p.a}" {o}/>'
    s += '<path d="M36 60 C40 38 64 34 82 50" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity=".45"/>'
    s += f'<path d="M100 56 L100 124" stroke="{p.k}" stroke-width="3" opacity=".35"/>'
    for x, y in ((64, 70), (136, 70), (82, 100), (118, 100)):
        s += f'<circle cx="{x}" cy="{y}" r="4" fill="{p.k}" opacity=".45"/>'
    s += f'<rect x="30" y="118" width="140" height="34" rx="14" fill="{p.b}" {o}/>'
    s += f'<line x1="100" y1="120" x2="100" y2="150" stroke="{p.k}" stroke-width="4"/>'
    s += f'<rect x="8" y="104" width="34" height="62" rx="16" fill="{p.a}" {o}/><rect x="158" y="104" width="34" height="62" rx="16" fill="{p.a}" {o}/>'
    s += f'<rect x="20" y="152" width="160" height="22" rx="8" fill="{p.a}" {o}/>'
    s += f'<path d="M34 174 L28 194 M166 174 L172 194" stroke="{p.c}" stroke-width="10" stroke-linecap="round"/>'
    return s


def cheese(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round"'
    s = f'<path d="M14 120 L150 44 Q176 50 188 72 L188 150 L14 150 Z" fill="{p.b}" {o}/>'
    s += f'<path d="M14 120 L150 44 Q176 50 188 72 L14 120 Z" fill="{p.l}" {o}/>'
    s += f'<path d="M14 120 L188 72 L188 150 L14 150 Z" fill="{p.a}" {o}/>'
    for cx, cy, r in ((60, 132, 9), (104, 120, 12), (150, 132, 8), (168, 100, 9), (128, 100, 6)):
        s += f'<ellipse cx="{cx}" cy="{cy}" rx="{r}" ry="{r * 0.8:.1f}" fill="{p.c}"/>'
    s += f'<path d="M80 150 Q84 172 92 150 M140 150 Q146 184 154 150" fill="{p.a}" {o}/>'
    s += '<path d="M120 62 L96 76" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".7"/>'
    return s


def roller_skate(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round"'
    s = f'<path d="M50 20 L110 20 L112 84 Q150 88 170 104 Q184 116 180 136 L40 136 Q34 90 50 20 Z" fill="{p.l}" {o}/>'
    s += f'<path d="M110 20 L112 84 Q150 88 170 104 Q184 116 180 136 L140 136 Q146 106 112 102 L52 102" fill="none" stroke="{p.k}" stroke-width="3" opacity=".35"/>'
    for y in (40, 58, 76):
        s += f'<line x1="86" y1="{y}" x2="118" y2="{y + 4}" stroke="{p.a}" stroke-width="5" stroke-linecap="round"/>'
    s += f'<path d="M48 110 L180 110 L180 136 L40 136 Z" fill="{p.a}" {o}/>'
    s += f'<rect x="36" y="136" width="148" height="12" rx="5" fill="{p.k}"/>'
    s += f'<circle cx="164" cy="116" r="13" fill="{p.b}" {o}/>'
    for x in (62, 146):
        s += f'<circle cx="{x}" cy="166" r="22" fill="{p.c}" {o}/><circle cx="{x}" cy="166" r="8" fill="{p.l}" {o}/>'
    s += '<path d="M58 30 Q56 60 60 90" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity=".7"/>'
    return s


def helmet(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round"'
    s = f'<path d="M14 128 Q14 30 100 28 Q186 30 186 128 Q190 140 176 142 L24 142 Q10 140 14 128 Z" fill="{p.a}" {o}/>'
    s += f'<path d="M4 140 Q100 118 196 140 L196 152 Q100 132 4 152 Z" fill="{p.a}" {o}/>'
    s += f'<g fill="none" stroke="{p.b}" stroke-width="5" opacity=".9"><path d="M24 110 Q100 60 176 110"/><path d="M40 72 Q100 40 160 72"/></g>'
    s += f'<g fill="{p.c}" opacity=".9"><circle cx="70" cy="66" r="7"/><circle cx="130" cy="90" r="6"/><circle cx="96" cy="112" r="7"/><circle cx="150" cy="60" r="5"/></g>'
    s += '<path d="M50 60 Q80 38 112 38" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity=".35"/>'
    return s


def ships_wheel(p: P) -> str:
    s = ""
    for k in range(8):
        a = math.radians(k * 45)
        x1, y1 = 100 + 96 * math.cos(a), 100 + 96 * math.sin(a)
        s += f'<line x1="100" y1="100" x2="{x1:.1f}" y2="{y1:.1f}" stroke="{p.k}" stroke-width="18" stroke-linecap="round"/>'
        s += f'<line x1="100" y1="100" x2="{x1:.1f}" y2="{y1:.1f}" stroke="{p.a}" stroke-width="9" stroke-linecap="round"/>'
    s += f'<circle cx="100" cy="100" r="68" fill="none" stroke="{p.k}" stroke-width="24"/>'
    s += f'<circle cx="100" cy="100" r="68" fill="none" stroke="{p.a}" stroke-width="14"/>'
    s += (
        '<circle cx="100" cy="100" r="68" fill="none" stroke="#fff" stroke-width="3" opacity=".3"/>'
    )
    s += f'<circle cx="100" cy="100" r="22" fill="{p.b}" stroke="{p.k}" stroke-width="6"/><circle cx="100" cy="100" r="8" fill="{p.k}"/>'
    return s


def magic_lantern(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round"'
    s = f'<rect x="76" y="6" width="30" height="34" rx="4" fill="{p.a}" {o}/><path d="M70 6 L112 6 L106 -2 L76 -2 Z" fill="{p.a}" {o}/>'
    s += f'<path d="M50 40 L132 40 L140 150 L42 150 Z" fill="{p.a}" {o}/>'
    s += f'<path d="M58 52 L124 52 L128 94 L54 94 Z" fill="{p.b}" {o}/>'
    s += f'<circle cx="91" cy="122" r="12" fill="{p.l}" {o}/>'
    s += f'<rect x="132" y="84" width="36" height="44" rx="4" fill="{p.a}" {o}/>'
    s += f'<rect x="166" y="76" width="22" height="60" rx="6" fill="{p.a}" {o}/><ellipse cx="188" cy="106" rx="8" ry="26" fill="{p.l}" {o}/>'
    s += f'<rect x="36" y="150" width="112" height="16" rx="4" fill="{p.c}" {o}/>'
    for x in (48, 136):
        s += f'<path d="M{x} 166 L{x - 6} 194" stroke="{p.k}" stroke-width="8" stroke-linecap="round"/>'
    s += '<path d="M58 60 L62 140" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".5"/>'
    return s


def tissue_box(p: P) -> str:
    o = f'stroke="{p.k}" stroke-width="6" stroke-linejoin="round"'
    s = f'<path d="M20 80 L60 56 L196 56 L156 80 Z" fill="{p.b}" {o}/>'
    s += f'<path d="M156 80 L196 56 L196 160 L156 186 Z" fill="{p.c}" {o}/>'
    s += f'<rect x="20" y="80" width="136" height="106" fill="{p.a}" {o}/>'
    s += f'<ellipse cx="108" cy="68" rx="36" ry="9" fill="{p.k}"/>'
    s += f'<path d="M84 68 Q70 30 96 14 Q112 4 118 22 Q130 8 140 24 Q150 44 132 68 Z" fill="{p.l}" {o}/>'
    s += f'<path d="M100 22 Q98 44 110 64" fill="none" stroke="{p.k}" stroke-width="3" opacity=".3"/>'
    return s


# ======================================================================= hits

HITS = ("movies", "hits", "blockbusters")


@net("Opening Weekend", MOVIES, "movies", "new movies", "blockbusters")
def opening_weekend():
    d = (
        SH
        + lin("sky", [(0, "#060b22"), (1, "#1c2d66")])
        + lin("beam", [(0, "#fff6c9"), (1, "#fff6c9")], x1=0.5, y1=1, x2=0.5, y2=0)
        + lin("bm", [(0, "#fff6c9"), (0.9, "#fff6c9")], x1=0, y1=1, x2=0, y2=0)
        + lin("gold", [(0, "#fff4c2"), (0.5, "#ffcf4a"), (1, "#d48a12")])
        + "<clipPath id='pc'><rect x='36' y='36' width='440' height='440' rx='34'/></clipPath>"
        + "<linearGradient id='fade' x1='0' y1='1' x2='0' y2='0'><stop offset='0' stop-color='#fff6c9' stop-opacity='.75'/><stop offset='1' stop-color='#fff6c9' stop-opacity='0'/></linearGradient>"
    )
    body = _panel(36, 36, 440, 440, "url(#sky)", rx=34, edge="#02040f", sw=6)
    body += '<g clip-path="url(#pc)">'
    for bx, tx in ((150, 40), (362, 472), (110, 250), (402, 262)):
        body += f'<polygon points="{bx - 8},470 {bx + 8},470 {tx + 44},20 {tx - 44},20" fill="url(#fade)" opacity=".55"/>'
    for x, y in ((90, 90), (410, 110), (330, 70), (180, 76), (440, 200), (70, 210)):
        body += _sparkle(x, y, 7, "#fff")
    city = "M36 476 L36 420 L70 420 L70 396 L96 396 L96 430 L124 430 L124 380 L150 380 L150 410 L184 410 L184 392 L214 392 L214 424 L300 424 L300 386 L326 386 L326 408 L352 408 L352 372 L384 372 L384 418 L414 418 L414 398 L444 398 L444 428 L476 428 L476 476 Z"
    body += f'<path d="{city}" fill="#02040f"/>'
    body += "</g>"
    w = _t("OPENING", "Big Shoulders Display", "url(#gold)", 900, "#02040f", 8, ls=2)
    body += _sh(fit(_ext(w, 0, 10, "#6b3a00", 10), 60, 140, 392, 138))
    body += _sh(
        '<rect x="72" y="300" width="368" height="76" rx="8" fill="#d62839" stroke="#02040f" stroke-width="6"/>'
    )
    body += fit(_t("WEEKEND", "Big Shoulders Display", "#fff", 900, ls=16), 96, 312, 320, 52)
    body += "".join(
        f'<polygon points="{star(x, 110, r, r * 0.42)}" fill="url(#gold)"/>'
        for x, r in ((206, 14), (256, 20), (306, 14))
    )
    return svg(body, d)


@net("Sold Out", MOVIES, *HITS)
def sold_out():
    d = (
        SH
        + lin("wood", [(0, "#7a1b24"), (1, "#3d0a10")])
        + lin("glass", [(0, "#1f4e79"), (1, "#0b1f33")])
        + lin("gold", [(0, "#fff0b8"), (0.5, "#e7b64a"), (1, "#a8741b")])
        + lin("sign", [(0, "#ff4b4b"), (1, "#b3001b")])
    )
    arch = "M76 470 L76 190 Q76 44 256 44 Q436 44 436 190 L436 470 Z"
    body = f'<g filter="url(#sh)"><path d="{arch}" fill="url(#wood)" stroke="#1c0508" stroke-width="8"/></g>'
    win = "M120 440 L120 210 Q120 96 256 96 Q392 96 392 210 L392 440 Z"
    body += f'<path d="{win}" fill="url(#glass)" stroke="url(#gold)" stroke-width="8"/>'
    body += '<path d="M150 200 Q160 130 240 118" fill="none" stroke="#fff" stroke-width="10" stroke-linecap="round" opacity=".18"/>'
    body += '<rect x="196" y="392" width="120" height="30" rx="15" fill="#0b1f33" stroke="url(#gold)" stroke-width="5"/>'
    body += fit(
        text("BOX OFFICE", "Cinzel", 40, weight=700, fill="url(#gold)", ls=6), 166, 120, 180, 30
    )
    body += '<circle cx="256" cy="176" r="7" fill="url(#gold)" stroke="#1c0508" stroke-width="2"/>'
    sign = '<g transform="rotate(-8 256 280)">'
    sign += '<path d="M256 176 L110 232 M256 176 L402 232" stroke="#d9c38a" stroke-width="4"/>'
    sign += '<rect x="44" y="222" width="424" height="150" rx="16" fill="url(#sign)" stroke="#2a0306" stroke-width="8"/>'
    sign += '<rect x="60" y="238" width="392" height="118" rx="10" fill="none" stroke="#fff" stroke-width="3" opacity=".7"/>'
    sign += fit(_t("SOLD OUT", "Archivo Black", "#fff", ls=4), 78, 254, 356, 86)
    sign += "</g>"
    body += _sh(sign)
    return svg(body, d)


@net("Wide Release", MOVIES, *HITS)
def wide_release():
    d = (
        SH
        + lin("scr", [(0, "#e9fbff"), (0.55, "#9ee7f2"), (1, "#3fb6c9")])
        + rad("beam", [(0, "#bff6ff"), (1, "#bff6ff")])
        + "<linearGradient id='fade' x1='0' y1='1' x2='0' y2='0'><stop offset='0' stop-color='#bff6ff' stop-opacity='.5'/><stop offset='1' stop-color='#bff6ff' stop-opacity='0'/></linearGradient>"
    )
    body = _panel(16, 96, 480, 320, "#081a24", rx=26, edge="#020a0f", sw=6)
    screen = "M44 136 Q256 112 468 136 L468 300 Q256 324 44 300 Z"
    body += f'<path d="{screen}" fill="url(#scr)" stroke="#020a0f" stroke-width="5"/>'
    body += '<polygon points="236,404 276,404 300,312 212,312" fill="url(#fade)"/>'
    body += '<path d="M60 150 Q256 128 452 150" fill="none" stroke="#fff" stroke-width="6" opacity=".6"/>'
    w = _t("WIDE", "Syncopate", "#0a2a3a", 700, ls=10)
    body += fit(w, 96, 160, 320, 110)
    for x, flip in ((62, 1), (450, -1)):
        body += (
            f'<polygon points="{x},218 {x + 26 * flip},198 {x + 26 * flip},238" fill="#0a2a3a"/>'
        )
    body += fit(_t("RELEASE", "Syncopate", "#9ee7f2", 700, ls=22), 110, 336, 292, 44)
    return svg(body, d)


@net("Feature Presentation", MOVIES, "movies", "hits", "70s")
def feature_presentation():
    d = (
        SH
        + lin("gold", [(0, "#fff2c2"), (0.45, "#ffc94a"), (1, "#e0701a")])
        + "<clipPath id='pc'><rect x='30' y='56' width='452' height='400' rx='60'/></clipPath>"
    )
    body = _panel(30, 56, 452, 400, "#2b140a", rx=60, edge="#150803", sw=6)
    body += '<g clip-path="url(#pc)">'
    body += _rays(256, 256, 420, 24, "#ffb347", 0.09, 0.06)
    for i, c in enumerate(("#e8742a", "#f2b134", "#c8341f", "#7a3b16")):
        y = 150 + i * 30
        body += f'<path d="M-10 {y + 60} Q140 {y - 70} 256 {y} T522 {y - 30}" fill="none" stroke="{c}" stroke-width="26"/>'
    body += "</g>"
    w = _t("Feature", "Shrikhand", "url(#gold)", stroke="#150803", sw=12)
    body += _sh(fit(tilt(_ext(w, 4, 8, "#150803"), -6), 56, 110, 400, 170))
    body += _sh(
        '<rect x="60" y="330" width="392" height="70" rx="35" fill="#fbe8c3" stroke="#150803" stroke-width="6"/>'
    )
    body += fit(_t("PRESENTATION", "Oswald", "#2b140a", 700, ls=10), 90, 344, 332, 42)
    return svg(body, d)


@net("Coming Attractions", MOVIES, "movies", "new movies", "trailers")
def coming_attractions():
    d = SH + rad("leader", [(0, "#d9cfb8"), (1, "#8f8672")], r=0.6)
    d += "<clipPath id='cc'><circle cx='256' cy='160' r='118'/></clipPath>"
    body = _panel(40, 26, 432, 460, "#141210", rx=22, edge="#000", sw=4)
    for y in range(44, 480, 34):
        body += f'<rect x="54" y="{y}" width="20" height="16" rx="4" fill="#3a3630"/><rect x="438" y="{y}" width="20" height="16" rx="4" fill="#3a3630"/>'
    body += '<circle cx="256" cy="160" r="128" fill="#141210"/>'
    body += '<circle cx="256" cy="160" r="118" fill="url(#leader)"/>'
    a = math.radians(-90)
    b = math.radians(150)
    body += f'<g clip-path="url(#cc)"><path d="M256 160 L{256 + 140 * math.cos(a):.1f} {160 + 140 * math.sin(a):.1f} A140 140 0 1 1 {256 + 140 * math.cos(b):.1f} {160 + 140 * math.sin(b):.1f} Z" fill="#141210" opacity=".28"/></g>'
    body += '<g fill="none" stroke="#fbf6ea" stroke-width="5"><circle cx="256" cy="160" r="104"/><circle cx="256" cy="160" r="86"/></g>'
    body += '<g stroke="#141210" stroke-width="3" opacity=".7"><line x1="126" y1="160" x2="386" y2="160"/><line x1="256" y1="30" x2="256" y2="290"/></g>'
    body += fit(_t("3", "Oswald", "#141210", 700), 216, 104, 80, 112)
    w = _t("COMING", "Bebas Neue", "#fbf6ea", stroke="#141210", sw=10, ls=6)
    body += _sh(fit(w, 84, 300, 344, 96))
    body += _sh(
        '<rect x="64" y="404" width="384" height="64" rx="6" fill="#c8102e" stroke="#000" stroke-width="5"/>'
    )
    body += fit(_t("ATTRACTIONS", "Bebas Neue", "#fff", ls=8), 84, 414, 344, 44)
    return svg(body, d)


@net("Intermission", MOVIES, "movies", "classic movies", "retro")
def intermission():
    d = (
        SH
        + lin("cur", [(0, "#5c0a14"), (0.5, "#b3192b"), (1, "#5c0a14")], x2=1, y2=0)
        + lin("gold", [(0, "#fff0b8"), (0.5, "#e7b64a"), (1, "#a8741b")])
        + lin("card", [(0, "#fffaf0"), (1, "#f1e2c2")])
    )
    body = _panel(30, 40, 452, 432, "#2a0508", rx=20, edge="#140204", sw=6)
    folds = ""
    for i in range(10):
        x = 44 + i * 43
        folds += f'<rect x="{x}" y="70" width="43" height="380" fill="url(#cur)"/>'
    body += folds
    body += '<path d="M44 450 Q66 470 87 450 Q108 470 130 450 Q152 470 173 450 Q194 470 216 450 Q238 470 259 450 Q280 470 302 450 Q324 470 345 450 Q366 470 388 450 Q410 470 431 450 Q452 470 468 450 L468 436 L44 436 Z" fill="url(#gold)"/>'
    body += '<path d="M40 50 L472 50 L472 96 Q420 130 364 96 Q310 130 256 96 Q202 130 148 96 Q92 130 40 96 Z" fill="#8a0f1f" stroke="#140204" stroke-width="5"/>'
    body += '<path d="M40 88 Q92 122 148 88 Q202 122 256 88 Q310 122 364 88 Q420 122 472 88" fill="none" stroke="url(#gold)" stroke-width="6"/>'
    card = '<line x1="176" y1="112" x2="146" y2="200" stroke="url(#gold)" stroke-width="4"/><line x1="336" y1="112" x2="366" y2="200" stroke="url(#gold)" stroke-width="4"/>'
    card += '<rect x="46" y="190" width="420" height="170" rx="18" fill="url(#card)" stroke="#140204" stroke-width="7"/>'
    card += '<rect x="60" y="204" width="392" height="142" rx="10" fill="none" stroke="#b3192b" stroke-width="3"/>'
    body += _sh(card)
    body += fit(_t("Intermission", "Lobster", "#8a0f1f"), 76, 214, 360, 96)
    body += fit(
        _t("THE SHOW WILL RESUME SHORTLY", "Oswald", "#2a0508", 600, ls=3), 110, 318, 292, 20
    )
    return svg(body, d)


@net("Front Row", MOVIES, *HITS)
def front_row():
    d = (
        SH
        + lin("scr", [(0, "#ffffff"), (1, "#bfe0ff")])
        + lin("seat", [(0, "#e8394a"), (1, "#8c0f1f")])
        + rad("glow", [(0, "#9fd3ff"), (1, "#0b1330")], cy=0.3, r=0.8)
    )
    body = _panel(26, 26, 460, 460, "url(#glow)", rx=30, edge="#050a1c", sw=6)
    body += _sh(
        '<polygon points="44,50 468,50 424,300 88,300" fill="url(#scr)" stroke="#050a1c" stroke-width="6"/>'
    )
    body += '<polygon points="60,62 452,62 446,96 66,96" fill="#fff" opacity=".6"/>'
    body += fit(_t("FRONT", "Archivo Black", "#0f1d3a", ls=4), 110, 88, 292, 100)
    body += fit(_t("ROW", "Archivo Black", "#e8394a", ls=18), 150, 196, 212, 84)
    seats = ""
    for i in range(4):
        x = 42 + i * 110
        seats += f'<rect x="{x - 10}" y="366" width="20" height="120" rx="8" fill="#1a1a2a"/>'
        seats += f'<path d="M{x + 8} 486 L{x + 8} 356 Q{x + 8} 322 {x + 50} 322 Q{x + 92} 322 {x + 92} 356 L{x + 92} 486 Z" fill="url(#seat)" stroke="#2a0508" stroke-width="5"/>'
        seats += f'<path d="M{x + 22} 360 Q{x + 24} 338 {x + 48} 336" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".35"/>'
        seats += f'<rect x="{x + 36}" y="440" width="28" height="16" rx="3" fill="#e7b64a" stroke="#2a0508" stroke-width="2"/>'
    seats += '<rect x="472" y="366" width="20" height="120" rx="8" fill="#1a1a2a"/>'
    body += f'<g clip-path="url(#seatclip)">{seats}</g>'
    d += "<clipPath id='seatclip'><rect x='26' y='26' width='460' height='460' rx='30'/></clipPath>"
    return svg(body, d)


@net("Ticket Stub", MOVIES, *HITS)
def ticket_stub():
    rng = random.Random(4)
    d = SH + lin("tk", [(0, "#ef4b4f"), (1, "#b81d2a")])
    right = [(410 + rng.uniform(-10, 10), y) for y in range(130, 391, 13)]
    shape = [(70, 130), *right, (70, 390)]
    path = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in shape)
    path = (
        f"M70 130 L{right[0][0]:.1f} 130 "
        + " ".join(f"L{x:.1f} {y}" for x, y in right)
        + " L70 390 L70 290 A30 30 0 0 0 70 230 Z"
    )
    body = f'<g transform="rotate(-7 256 260)"><g filter="url(#sh)"><path d="{path}" fill="url(#tk)" stroke="#3d060b" stroke-width="7" stroke-linejoin="round"/></g>'
    body += '<rect x="100" y="152" width="286" height="216" rx="8" fill="none" stroke="#ffe7c2" stroke-width="3"/>'
    body += '<line x1="138" y1="152" x2="138" y2="368" stroke="#ffe7c2" stroke-width="2" stroke-dasharray="6 6"/>'
    body += f'<g transform="translate(120 260) rotate(-90)">{_t("ADMIT ONE", "Oswald", "#ffe7c2", 700, size=24, ls=3)}</g>'
    body += fit(_t("TICKET", "Alfa Slab One", "#fff4dc"), 152, 170, 222, 84)
    body += fit(_t("STUB", "Alfa Slab One", "#fff4dc", ls=10), 176, 262, 174, 64)
    body += fit(_t("No. 004751", "Oswald", "#3d060b", 700, ls=4), 196, 338, 134, 20)
    body += "</g>"
    return svg(body, d)


@net("Free Refill", MOVIES, *HITS)
def free_refill():
    d = SH + lin("band", [(0, "#1c5fd6"), (1, "#123c8c")])
    p = P(a="#e8303a", b="#ffe44d", c="#1c5fd6", k="#1a1330", l="#fffdf6")
    body = _sh(centred(soda_cup(p), 256, 214, 380))
    for x, y, r in ((190, 60, 8), (330, 52, 6), (356, 96, 9), (160, 100, 5)):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" stroke="#1a1330" stroke-width="3"/>'
    burst = f'<polygon points="{star(256, 222, 104, 84, 18)}" fill="#ffe44d" stroke="#1a1330" stroke-width="6" stroke-linejoin="round"/>'
    body += _sh(tilt(burst, 0))
    body += fit(
        tilt(_t("FREE", "Lilita One", "#e8303a", stroke="#1a1330", sw=6), -10), 176, 176, 160, 92
    )
    body += _sh(banner(40, 472, 360, 88, "url(#band)", "#1a1330", 6, cut=24))
    body += fit(_t("REFILL", "Lilita One", "#fff", ls=8), 110, 372, 292, 64)
    return svg(body, d)


@net("Jumbo Tub", MOVIES, "movies", "hits", "family movies")
def jumbo_tub():
    d = SH + lin("gold", [(0, "#fff38a"), (1, "#ffb400")])
    d += "<clipPath id='tub'><path d='M60 196 L452 196 L420 470 L92 470 Z'/></clipPath>"
    body = ""
    rng = random.Random(7)
    puffs = [(x, 150 + rng.uniform(-40, 30), rng.uniform(34, 46)) for x in range(80, 450, 40)]
    puffs += [(x, 90 + rng.uniform(-20, 30), rng.uniform(32, 42)) for x in range(130, 400, 46)]
    puffs += [(256, 50, 40), (200, 70, 34), (316, 66, 36)]
    kern = ""
    for x, y, r in sorted(puffs, key=lambda q: q[1]):
        kern += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.0f}" fill="#fff8e1" stroke="#2a1606" stroke-width="6"/>'
        kern += f'<circle cx="{x - r * 0.3:.0f}" cy="{y - r * 0.3:.0f}" r="{r * 0.28:.0f}" fill="#fff"/>'
        kern += f'<circle cx="{x + r * 0.35:.0f}" cy="{y + r * 0.25:.0f}" r="{r * 0.25:.0f}" fill="#ffd54a" opacity=".8"/>'
    body += _sh(kern)
    tub = '<path d="M60 196 L452 196 L420 470 L92 470 Z" fill="#fff8ee" stroke="#2a1606" stroke-width="8" stroke-linejoin="round"/>'
    stripes = '<g clip-path="url(#tub)">'
    for i in range(9):
        x0 = 60 + i * 48
        stripes += f'<polygon points="{x0 + 10},196 {x0 + 34},196 {x0 + 30 - (x0 - 256) * 0.08},470 {x0 + 8 - (x0 - 256) * 0.08},470" fill="#e02a33"/>'
    stripes += "</g>"
    body += _sh(
        tub
        + stripes
        + '<path d="M60 196 L452 196 L420 470 L92 470 Z" fill="none" stroke="#2a1606" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += '<rect x="44" y="184" width="424" height="26" rx="10" fill="#e02a33" stroke="#2a1606" stroke-width="6"/>'
    body += _sh(
        '<rect x="52" y="250" width="408" height="130" rx="22" fill="#1d1a4a" stroke="#2a1606" stroke-width="7"/>'
    )
    w = _t("JUMBO", "Titan One", "url(#gold)", stroke="#2a1606", sw=8, ls=4)
    body += fit(_ext(w, 0, 6, "#2a1606", 6), 76, 262, 360, 88)
    body += _sh(
        '<circle cx="256" cy="414" r="46" fill="#ffd54a" stroke="#2a1606" stroke-width="6"/>'
    )
    body += fit(_t("TUB", "Titan One", "#e02a33"), 222, 396, 68, 36)
    return svg(body, d)


@net("Big Screen", MOVIES, *HITS)
def big_screen():
    d = (
        SH
        + lin("gold", [(0, "#fff38a"), (0.5, "#ffc21a"), (1, "#ff8a00")])
        + lin("scr", [(0, "#ffffff"), (1, "#d7e6ff")])
        + lin("cur", [(0, "#6d0f1d"), (0.5, "#c01f33"), (1, "#6d0f1d")], x2=1, y2=0)
    )
    body = _panel(24, 236, 464, 240, "#1a1030", rx=16, edge="#0a0614", sw=6)
    body += '<rect x="44" y="256" width="424" height="200" fill="#0a0614"/>'
    body += '<rect x="80" y="266" width="352" height="180" rx="4" fill="url(#scr)"/>'
    for x in (36, 440):
        body += f'<path d="M{x} 250 L{x + 36} 250 L{x + 36} 462 Q{x + 18} 470 {x} 462 Z" fill="url(#cur)" stroke="#0a0614" stroke-width="4"/>'
    body += fit(_t("SCREEN", "Bebas Neue", "#1a1030", ls=10), 104, 296, 304, 124)
    w = _t("BIG", "Ultra", "url(#gold)", stroke="#1a1030", sw=10, ls=6)
    body += _sh(fit(_ext(w, 10, 14, "#3a1a6e", 14), 90, 22, 332, 196))
    return svg(body, d)


@net("Red Carpet", MOVIES, "movies", "hits", "award winners")
def red_carpet():
    d = (
        SH
        + lin("gold", [(0, "#fff3c4"), (0.45, "#e6bd5a"), (1, "#9c7424")])
        + lin("rug", [(0, "#7d0c1a"), (1, "#e0243a")])
        + "<clipPath id='pc'><rect x='36' y='36' width='440' height='440' rx='30'/></clipPath>"
    )
    body = _panel(36, 36, 440, 440, "#0d0a0c", rx=30)
    body += '<g clip-path="url(#pc)">'
    body += '<polygon points="226,262 286,262 420,480 92,480" fill="url(#rug)"/>'
    body += '<polygon points="226,262 232,262 106,480 92,480" fill="url(#gold)"/><polygon points="286,262 280,262 406,480 420,480" fill="url(#gold)"/>'
    for i in range(1, 6):
        y = 262 + i * i * 8
        body += f'<line x1="0" y1="{y}" x2="512" y2="{y}" stroke="#000" stroke-width="1.5" opacity=".18"/>'
    body += "</g>"
    body += '<rect x="54" y="54" width="404" height="404" rx="18" fill="none" stroke="url(#gold)" stroke-width="3"/>'
    for x, y, r in (
        (96, 300, 22),
        (416, 320, 26),
        (130, 404, 14),
        (386, 420, 16),
        (74, 212, 10),
        (440, 230, 12),
    ):
        body += f'<circle cx="{x}" cy="{y}" r="{r * 0.9}" fill="#fff" opacity=".18"/>' + _sparkle(
            x, y, r, "#fff"
        )
    body += _sh(
        fit(
            _t("RED", "Playfair Display", "#e0243a", 900, stroke="#0d0a0c", sw=6, ls=14),
            150,
            76,
            212,
            84,
        )
    )
    body += _sh(
        fit(
            _t("CARPET", "Playfair Display", "url(#gold)", 900, stroke="#0d0a0c", sw=6, ls=8),
            76,
            164,
            360,
            84,
        )
    )
    return svg(body, d)


# ======================================================================= action


@net("One-Liner", MOVIES, "movies", "action")
def one_liner():
    d = SH + lin("y", [(0, "#ffe14d"), (1, "#ffb300")])
    body = '<g transform="rotate(-4 256 256)">'
    body += _sh(
        '<rect x="30" y="112" width="452" height="288" rx="10" fill="#121212" stroke="url(#y)" stroke-width="12"/>'
    )
    body += fit(_t("“", "Abril Fatface", "#e8262e"), 44, 60, 96, 120)
    body += fit(_t("”", "Abril Fatface", "#e8262e"), 372, 330, 96, 120)
    w = _t("ONE-LINER", "Anton", "#fff", ls=4)
    body += fit(_ext(w, 5, 6, "#e8262e", 6), 70, 190, 372, 120)
    body += fit(_t("ACTION MOVIES", "Oswald", "url(#y)", 700, ls=10), 150, 330, 212, 30)
    body += "</g>"
    return svg(body, d)


@net("Roundhouse", MOVIES, "movies", "action", "martial arts")
def roundhouse():
    d = SH + rad("disc", [(0, "#3f3f46"), (0.7, "#18181b"), (1, "#09090b")], r=0.6)
    body = _sh(
        '<circle cx="256" cy="256" r="196" fill="url(#disc)" stroke="#1a0a05" stroke-width="10"/>'
    )
    body += _rays(256, 256, 190, 16, "#fff", 0.08, 0.1)
    body += _sh(_swoosh(256, 256, 222, 150, 400, 44, "#fff", "#1a0a05", 6))
    body += _sh(
        '<polygon points="20,210 500,186 492,316 12,338" fill="#dc2626" stroke="#1a0a05" stroke-width="8"/>'
    )
    w = _t("ROUNDHOUSE", "Russo One", "#fff", style="italic")
    body += fit(skew(_ext(w, 4, 5, "#1a0a05", 5), -10), 36, 216, 440, 100)
    return svg(body, d)


@net("Mayhem Movies", MOVIES, "movies", "action")
def mayhem_movies():
    return L.burst_word(
        "MAYHEM",
        "MOVIES",
        font="Knewave",
        fill="#ffd23f",
        edge="#16060a",
        back="#e0301e",
        back2="#5e0808",
        sub_fill="#fff",
        sub_font="Archivo Black",
        points=20,
        tilt=-6,
        rays=True,
    )


@net("Slow-Mo", MOVIES, "movies", "action")
def slow_mo():
    d = (
        SH
        + lin("bg", [(0, "#123047"), (1, "#060f18")])
        + lin("brass", [(0, "#ffe9a6"), (0.5, "#d4a017"), (1, "#8a5a00")], x2=0, y2=1)
        + lin("lead", [(0, "#e3e7ee"), (1, "#8d96a6")], x2=0, y2=1)
    )
    body = _panel(24, 60, 464, 392, "url(#bg)", rx=36, edge="#02070c", sw=6)
    for i, r in enumerate((20, 34, 50, 68)):
        body += f'<ellipse cx="{150 - i * 26}" cy="156" rx="{r * 0.45:.0f}" ry="{r}" fill="none" stroke="#4cc9f0" stroke-width="{4 - i * 0.6:.1f}" opacity="{0.9 - i * 0.18:.2f}"/>'
    body += (
        '<line x1="40" y1="156" x2="150" y2="156" stroke="#4cc9f0" stroke-width="2" opacity=".5"/>'
    )
    bullet = '<rect x="160" y="136" width="96" height="40" rx="3" fill="url(#brass)" stroke="#02070c" stroke-width="4"/>'
    bullet += '<rect x="248" y="132" width="12" height="48" rx="2" fill="url(#brass)" stroke="#02070c" stroke-width="4"/>'
    bullet += '<path d="M156 136 L120 136 Q86 136 76 156 Q86 176 120 176 L156 176 Z" fill="url(#lead)" stroke="#02070c" stroke-width="4"/>'
    body += _sh(f'<g transform="translate(476 0) scale(-1 1) translate(90 0)">{bullet}</g>')
    for i, op in enumerate((0.14, 0.24, 0.38)):
        body += fit(
            _t("SLOW-MO", "Kanit", "#4cc9f0", 900, style="italic"),
            44 + i * 12,
            236,
            400,
            124,
        ).replace('class="fit"', f'class="fit" opacity="{op}"')
    body += _sh(
        fit(
            _t("SLOW-MO", "Kanit", "#fff", 900, style="italic", stroke="#02070c", sw=6),
            84,
            236,
            400,
            124,
        )
    )
    body += fit(_t("ACTION MOVIES", "Kanit", "#4cc9f0", 700, ls=10), 176, 382, 240, 30)
    return svg(body, d)


@net("Blast Radius", MOVIES, "movies", "action")
def blast_radius():
    d = rad("boom", [(0, "#fffbe0"), (0.25, "#ffd23f"), (0.6, "#ff6a1a"), (1, "#7a1405")], r=0.5)
    centre = '<circle cx="256" cy="186" r="180" fill="#1d1a14"/>'
    for i, r in enumerate(range(200, 30, -34)):
        c = "#ffcf33" if i % 2 == 0 else "#1d1a14"
        centre += f'<circle cx="256" cy="186" r="{r}" fill="{c}"/>'
    centre += f'<polygon points="{star(256, 176, 110, 46, 12)}" fill="url(#boom)" stroke="#1d1a14" stroke-width="6" stroke-linejoin="round"/>'
    centre += '<circle cx="256" cy="176" r="30" fill="#fffbe0"/>'
    return L.roundel(
        centre,
        "BLAST RADIUS",
        font="Black Ops One",
        ink="#ffcf33",
        disc="#1d1a14",
        rim="#ffcf33",
        edge="#0d0b08",
        bar="#1d1a14",
        defs=d,
        bar_y=300,
        ls=4,
    )


@net("Adrenaline", MOVIES, "movies", "action", "extreme")
def adrenaline():
    d = SH + lin("hot", [(0, "#fff176"), (0.45, "#ff9100"), (1, "#e3001b")], x2=0, y2=1)
    body = _sh(
        '<polygon points="70,120 500,120 442,392 12,392" fill="#101014" stroke="#000" stroke-width="6"/>'
    )
    body += '<polygon points="84,134 482,134 432,378 26,378" fill="none" stroke="#e3001b" stroke-width="3"/>'
    body += '<polyline points="30,300 120,300 146,250 170,340 200,180 232,320 256,280 480,280" fill="none" stroke="#ffe14d" stroke-width="7" stroke-linejoin="round" opacity=".85"/>'
    for i in range(3):
        x = 60 + i * 30
        body += f'<polygon points="{x},160 {x + 22},186 {x},212 {x + 12},212 {x + 34},186 {x + 12},160" fill="#e3001b" opacity="{0.5 + i * 0.25:.2f}"/>'
    w = _t("ADRENALINE", "Big Shoulders Display", "url(#hot)", 900, stroke="#000", sw=6, ls=2)
    body += _sh(fit(skew(_ext(w, 6, 6, "#5a0006", 6), -14), 54, 176, 420, 150))
    return svg(body, d)


@net("Showdown", MOVIES, "movies", "action", "westerns")
def showdown():
    d = (
        SH
        + lin("blue", [(0, "#2f6bff"), (1, "#0d2a8a")])
        + lin("red", [(0, "#ff4436"), (1, "#8f0a12")])
        + "<clipPath id='pc'><rect x='36' y='36' width='440' height='440' rx='40'/></clipPath>"
    )
    body = _panel(36, 36, 440, 440, "#0b0b12", rx=40, edge="#000", sw=6)
    seam = "40,300 180,260 220,300 300,200 330,236 472,190"
    body += '<g clip-path="url(#pc)">'
    body += f'<polygon points="0,0 512,0 {seam.replace(" ", " ")} 472,190 512,180 512,0" fill="url(#blue)"/>'
    body += f'<polygon points="0,512 512,512 512,180 {" ".join(reversed(seam.split()))} 0,305" fill="url(#red)"/>'
    body += f'<polyline points="0,305 {seam} 512,180" fill="none" stroke="#fff" stroke-width="10" stroke-linejoin="round"/>'
    body += f'<polyline points="0,305 {seam} 512,180" fill="none" stroke="#ffd23f" stroke-width="4" stroke-linejoin="round"/>'
    body += "</g>"
    body += f'<polygon points="{star(262, 248, 60, 22, 10)}" fill="#ffd23f" stroke="#0b0b12" stroke-width="4"/>'
    w1 = _t("SHOW", "Teko", "#fff", 700, stroke="#0b0b12", sw=8, ls=4)
    w2 = _t("DOWN", "Teko", "#fff", 700, stroke="#0b0b12", sw=8, ls=4)
    body += _sh(fit(_ext(w1, 4, 6, "#0b0b12", 6), 60, 64, 300, 150))
    body += _sh(fit(_ext(w2, 4, 6, "#0b0b12", 6), 152, 300, 300, 150))
    return svg(body, d)


@net("Last Stand", MOVIES, "movies", "action", "war")
def last_stand():
    flag = '<path d="M60 30 L60 196" stroke="#1a1d22" stroke-width="10" stroke-linecap="round"/>'
    flag += '<path d="M64 36 Q110 20 150 40 Q170 50 190 40 L176 70 L192 96 Q168 110 146 96 Q112 80 64 100 Z" fill="#e8562a" stroke="#1a1d22" stroke-width="6" stroke-linejoin="round"/>'
    flag += '<path d="M150 62 L170 58 L160 80 Z" fill="#1a1d22"/>'
    flag += '<path d="M10 196 Q60 150 110 176 Q150 150 196 196 Z" fill="#4a4f58" stroke="#1a1d22" stroke-width="6" stroke-linejoin="round"/>'
    flag += '<circle cx="60" cy="26" r="8" fill="#ffcf33" stroke="#1a1d22" stroke-width="4"/>'
    return L.crest(
        flag,
        "LAST STAND",
        font="Bowlby One",
        ink="#fff3d6",
        field="#5b6270",
        field2="#2a2e36",
        rim="#e8562a",
        edge="#121418",
        scroll="#c2410c",
        scroll_dark="#7c2d12",
    )


@net("Full Throttle", MOVIES, "movies", "action", "car chases")
def full_throttle():
    d = (
        SH
        + lin("chrome", [(0, "#ffffff"), (0.45, "#b8c2cc"), (0.55, "#6b7785"), (1, "#e6ebf0")])
        + rad("face", [(0, "#2a2e36"), (1, "#0b0c10")], r=0.6)
    )
    cx, cy = 256, 236
    body = _sh(
        f'<circle cx="{cx}" cy="{cy}" r="212" fill="url(#chrome)" stroke="#0b0c10" stroke-width="6"/>'
    )
    body += f'<circle cx="{cx}" cy="{cy}" r="190" fill="url(#face)"/>'
    a0, a1 = 150, 390
    ticks = ""
    for k in range(25):
        a = math.radians(a0 + (a1 - a0) * k / 24)
        r1 = 150 if k % 3 else 136
        col = "#ff2a2a" if k > 18 else "#e8ecf2"
        ticks += f'<line x1="{cx + r1 * math.cos(a):.1f}" y1="{cy + r1 * math.sin(a):.1f}" x2="{cx + 176 * math.cos(a):.1f}" y2="{cy + 176 * math.sin(a):.1f}" stroke="{col}" stroke-width="{7 if k % 3 == 0 else 4}"/>'
    body += ticks
    ra0, ra1 = math.radians(a0 + (a1 - a0) * 19 / 24), math.radians(a1)
    body += f'<path d="M{cx + 182 * math.cos(ra0):.1f} {cy + 182 * math.sin(ra0):.1f} A182 182 0 0 1 {cx + 182 * math.cos(ra1):.1f} {cy + 182 * math.sin(ra1):.1f}" fill="none" stroke="#ff2a2a" stroke-width="10"/>'
    na = math.radians(a0 + (a1 - a0) * 0.93)
    body += f'<polygon points="{cx + 160 * math.cos(na):.1f},{cy + 160 * math.sin(na):.1f} {cx + 12 * math.cos(na + 1.57):.1f},{cy + 12 * math.sin(na + 1.57):.1f} {cx - 30 * math.cos(na):.1f},{cy - 30 * math.sin(na):.1f} {cx + 12 * math.cos(na - 1.57):.1f},{cy + 12 * math.sin(na - 1.57):.1f}" fill="#ff2a2a" stroke="#0b0c10" stroke-width="3"/>'
    body += f'<circle cx="{cx}" cy="{cy}" r="22" fill="url(#chrome)" stroke="#0b0c10" stroke-width="5"/>'
    body += _sh(
        '<path d="M16 316 L496 316 L470 420 L42 420 Z" fill="#d90f1f" stroke="#0b0c10" stroke-width="7" stroke-linejoin="round"/>'
    )
    body += '<path d="M30 328 L482 328" stroke="#fff" stroke-width="3" opacity=".4"/>'
    w = _t("FULL THROTTLE", "Racing Sans One", "#fff", stroke="#0b0c10", sw=6)
    body += fit(_ext(w, 3, 5, "#0b0c10", 5), 50, 332, 412, 72)
    return svg(body, d)


@net("Powder Burn", MOVIES, "movies", "action")
def powder_burn():
    d = (
        SH
        + lin("fire", [(0, "#fff3a0"), (0.4, "#ffb020"), (1, "#e2361b")], x2=0, y2=1)
        + rad("scorch", [(0, "#000"), (1, "#000")])
        + "<radialGradient id='burn'><stop offset='0' stop-color='#ff8a1f' stop-opacity='.9'/><stop offset='.5' stop-color='#b3260e' stop-opacity='.4'/><stop offset='1' stop-color='#000' stop-opacity='0'/></radialGradient>"
        + glow("gl", "#ffb020", blur=6, strength=2)
    )
    body = _panel(26, 60, 460, 392, "#1d1b1a", rx=24, edge="#050404", sw=6)
    body += '<circle cx="404" cy="372" r="96" fill="url(#burn)"/>'
    body += '<path d="M40 410 Q120 380 200 404 Q280 430 330 396 Q370 370 400 374" fill="none" stroke="#050404" stroke-width="16" stroke-linecap="round"/>'
    body += '<path d="M40 410 Q120 380 200 404 Q280 430 330 396 Q370 370 400 374" fill="none" stroke="#c9a46a" stroke-width="9" stroke-linecap="round" stroke-dasharray="10 5"/>'
    spark = f'<polygon points="{star(404, 372, 40, 10, 8)}" fill="#fff3a0"/>'
    spark += f'<polygon points="{star(404, 372, 26, 7, 8, rot=-67)}" fill="#ff8a1f"/>'
    body += f'<g filter="url(#gl)">{spark}</g>'
    for x, y in ((440, 330), (372, 330), (452, 400), (430, 300)):
        body += f'<circle cx="{x}" cy="{y}" r="3" fill="#ffd23f"/>'
    w1 = _t("POWDER", "Black Ops One", "#e9e4dc", ls=6)
    body += _sh(fit(w1, 60, 96, 392, 110))
    w2 = _t(
        "BURN", "Barlow Condensed", "url(#fire)", 900, stroke="#050404", sw=6, style="italic", ls=12
    )
    body += _sh(fit(_ext(w2, 4, 6, "#5a1205", 6), 110, 212, 292, 130))
    return svg(body, d)


# ======================================================================= comedy

COMEDY = ("movies", "comedy")


@net("Crack-Up Cinema", MOVIES, *COMEDY)
def crack_up_cinema():
    ink = "#111827"
    d = SH
    body = _panel(36, 96, 440, 320, "#facc15", rx=26, edge=ink, sw=7)
    w = _ext(_t("CRACK-UP", "Archivo Black", "#fff", stroke=ink, sw=12), 0, 7, ink, 6)
    body += fit(w, 66, 130, 380, 120)
    crack = "M300 104 L282 150 L298 180 L266 226 L280 256 L256 296"
    body += f'<path d="{crack}" fill="none" stroke="#facc15" stroke-width="12" stroke-linejoin="round"/>'
    body += (
        f'<path d="{crack}" fill="none" stroke="{ink}" stroke-width="3" stroke-linejoin="round"/>'
    )
    body += f'<rect x="126" y="300" width="260" height="80" rx="8" fill="{ink}"/>'
    body += fit(_t("CINEMA", "Archivo Black", "#facc15", ls=14), 146, 314, 220, 52)
    return svg(body, d)


@net("Goofball", MOVIES, *COMEDY)
def goofball():
    ink = "#1e1b4b"
    d = SH + rad("gb", [(0, "#fef9c3"), (0.6, "#facc15"), (1, "#ca8a04")], cx=0.38, cy=0.35)
    body = _sh(
        f'<circle cx="256" cy="236" r="200" fill="url(#gb)" stroke="{ink}" stroke-width="9"/>'
    )
    body += '<ellipse cx="190" cy="140" rx="60" ry="30" fill="#fff" opacity=".55" transform="rotate(-30 190 140)"/>'
    body += fit(
        _ext(_t("GOOF", "Bowlby One", "#ec4899", stroke=ink, sw=12), 0, 7, ink, 6),
        106,
        120,
        300,
        110,
    )
    body += _sh(banner(24, 488, 250, 96, "#2563eb", ink, 7, cut=24))
    body += fit(_t("BALL", "Bowlby One", "#fff", ls=12), 150, 264, 212, 66)
    body += fit(
        _t("COMEDY MOVIES", "Oswald", fill=ink, weight=700, ls=8, size=40), 176, 372, 160, 26
    )
    return svg(body, d)


@net("Blooper Reel", MOVIES, *COMEDY)
def blooper_reel():
    ink = "#111827"
    d = SH
    reel = S.reel(P(a="#9ca3af", b="#374151", c="#e5e7eb", k=ink, l="#f3f4f6"))
    body = _sh(centred(reel, 256, 186, 300))
    body += _sh(banner(28, 484, 330, 96, "#ef4444", ink, 7, cut=24))
    body += fit(_t("BLOOPER REEL", "Archivo Black", "#fff", ls=2), 76, 346, 360, 62)
    return svg(body, d)


@net("Outtakes", MOVIES, *COMEDY)
def outtakes():
    ink = "#0a0a0a"
    d = SH
    body = "<g filter='url(#sh)'>"
    body += f'<g transform="rotate(-14 60 140)"><rect x="40" y="96" width="432" height="60" rx="6" fill="{ink}"/>'
    for i in range(7):
        body += f'<polygon points="{60 + i * 62},96 {92 + i * 62},96 {62 + i * 62},156 {30 + i * 62},156" fill="#fff"/>'
    body += "</g>"
    body += f'<rect x="40" y="160" width="432" height="300" rx="10" fill="#1f2937" stroke="{ink}" stroke-width="6"/></g>'
    body += f'<rect x="40" y="160" width="432" height="60" fill="{ink}"/>'
    for i in range(7):
        body += f'<polygon points="{60 + i * 62},160 {92 + i * 62},160 {62 + i * 62},220 {30 + i * 62},220" fill="#fff"/>'
    body += fit(_t("OUTTAKES", "Archivo Black", "#fff", ls=4), 70, 240, 372, 84)
    body += '<line x1="60" y1="340" x2="452" y2="340" stroke="#9ca3af" stroke-width="3"/><line x1="256" y1="340" x2="256" y2="440" stroke="#9ca3af" stroke-width="3"/>'
    body += fit(_t("SCENE 4", "Permanent Marker", "#f9fafb"), 80, 360, 156, 60)
    body += fit(_t("TAKE 27", "Permanent Marker", "#facc15"), 276, 360, 156, 60)
    return svg(body, d)


@net("Laughing Gas", MOVIES, *COMEDY)
def laughing_gas():
    ink = "#052e16"
    d = SH + lin("lg", [(0, "#bbf7d0"), (1, "#22c55e")])
    body = _panel(36, 70, 440, 372, "#052e16", rx=30, edge="#000", sw=5)
    for x, y, r in (
        (120, 130, 26),
        (180, 100, 18),
        (330, 110, 30),
        (400, 150, 20),
        (260, 96, 14),
        (90, 200, 12),
        (430, 220, 14),
    ):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="#86efac" stroke-width="4"/>'
        if r > 20:
            body += fit(
                _t("HA", "Archivo Black", "#86efac"), x - r * 0.6, y - r * 0.4, r * 1.2, r * 0.8
            )
    w = _ext(_t("LAUGHING", "Archivo Black", "url(#lg)", stroke=ink, sw=10), 0, 6, "#000", 6)
    body += _sh(fit(w, 66, 210, 380, 96))
    body += fit(_t("GAS", "Archivo Black", "#fff", ls=30), 176, 316, 160, 80)
    return svg(body, d)


@net("Silly Pictures", MOVIES, *COMEDY)
def silly_pictures():
    return L.deco("SILLY", "PICTURES", font="Shrikhand", field="#1a1033", ls=4)


@net("Gut Buster", MOVIES, *COMEDY)
def gut_buster():
    ink = "#2b1408"
    d = SH + rad(
        "buckle", [(0, "#fff3c4"), (0.55, "#e2b13c"), (1, "#8a6414")], cx=0.4, cy=0.35, r=0.7
    )
    body = f'<rect x="0" y="210" width="512" height="92" fill="#6b4423" stroke="{ink}" stroke-width="6"/>'
    for x in range(10, 512, 24):
        body += f'<line x1="{x}" y1="220" x2="{x + 12}" y2="220" stroke="#d6a368" stroke-width="3"/><line x1="{x}" y1="292" x2="{x + 12}" y2="292" stroke="#d6a368" stroke-width="3"/>'
    body += _sh(
        f'<ellipse cx="256" cy="256" rx="214" ry="150" fill="url(#buckle)" stroke="{ink}" stroke-width="9"/>'
    )
    body += f'<ellipse cx="256" cy="256" rx="186" ry="124" fill="none" stroke="{ink}" stroke-width="4"/>'
    for k in range(20):
        a = math.radians(k * 18)
        body += f'<circle cx="{256 + 200 * math.cos(a):.0f}" cy="{256 + 137 * math.sin(a):.0f}" r="5" fill="#fff3c4" stroke="{ink}" stroke-width="2"/>'
    body += fit(_t("GUT", "Rye", "#7c2d12"), 186, 160, 140, 70)
    body += fit(_t("BUSTER", "Rye", "#7c2d12", ls=4), 116, 236, 280, 80)
    body += fit(
        _t("BELLY-LAUGH MOVIES", "Oswald", "#7c2d12", weight=700, ls=6, size=40), 170, 326, 172, 22
    )
    return svg(body, d)


@net("Guffaw", MOVIES, *COMEDY)
def guffaw():
    ink = "#111827"
    d = SH
    body = _sh(
        f'<rect x="30" y="140" width="452" height="232" rx="116" fill="#7c3aed" stroke="{ink}" stroke-width="8"/>'
    )
    cols = ("#facc15", "#f472b6", "#22d3ee", "#a3e635", "#fb923c", "#facc15")
    out, x = "", 0.0
    for i, (ch, c) in enumerate(zip("GUFFAW", cols, strict=True)):
        adv, _ = measure(ch, "Bowlby One", 400)
        dy = -12 if i % 2 else 10
        rot = -8 if i % 2 else 7
        out += f'<g transform="translate({x + adv / 2:.1f} {dy}) rotate({rot})">{_t(ch, "Bowlby One", c, stroke=ink, sw=12)}</g>'
        x += adv + 4
    body += _sh(fit(out, 52, 166, 408, 148))
    for x, y in ((470, 120), (490, 160), (40, 380)):
        body += f'<line x1="{x}" y1="{y}" x2="{x + (14 if x > 256 else -14)}" y2="{y - 14}" stroke="#facc15" stroke-width="7" stroke-linecap="round"/>'
    body += fit(
        _t("THE BIG-LAUGH CHANNEL", "Oswald", "#fff", weight=700, ls=6, size=40), 136, 320, 240, 30
    )
    return svg(body, d)


# ======================================================================= horror

HORROR = ("movies", "horror")


@net("Creature Feature", MOVIES, *HORROR, "monsters")
def creature_feature():
    ink = "#020617"
    d = SH + lin("slime", [(0, "#d9f99d"), (1, "#4d7c0f")])
    body = _panel(36, 56, 440, 400, "#0b1a0b", rx=20, edge="#000", sw=5)
    w = _t("CREATURE", "Bowlby One", "url(#slime)", stroke=ink, sw=10)
    body += _sh(fit(w, 60, 120, 392, 100))
    for x, h in ((106, 40), (160, 70), (214, 30), (262, 90), (318, 50), (372, 64), (420, 34)):
        body += f'<path d="M{x - 10} 214 L{x + 10} 214 L{x + 8} {214 + h} Q{x} {226 + h} {x - 8} {214 + h} Z" fill="#84cc16"/>'
    body += f'<rect x="96" y="320" width="320" height="76" rx="6" fill="#84cc16" stroke="{ink}" stroke-width="5"/>'
    body += fit(_t("FEATURE", "Bowlby One", ink, ls=8), 116, 332, 280, 52)
    return svg(body, d)


@net("Shock Theater", MOVIES, *HORROR)
def shock_theater():
    ink = "#0b0620"
    d = SH + glow("bolt", "#a78bfa", blur=8, strength=2)
    body = _panel(36, 56, 440, 400, "#0b0620", rx=20, edge="#000", sw=5)
    for x in (80, 432):
        body += f'<rect x="{x - 14}" y="300" width="28" height="140" fill="#475569"/><circle cx="{x}" cy="290" r="26" fill="#94a3b8" stroke="{ink}" stroke-width="4"/>'
    arc = "M80 290 L130 240 L160 270 L210 200 L250 250 L300 190 L330 240 L380 210 L432 290"
    body += f'<g filter="url(#bolt)"><path d="{arc}" fill="none" stroke="#c4b5fd" stroke-width="6" stroke-linejoin="round"/></g>'
    body += f'<path d="{arc}" fill="none" stroke="#fff" stroke-width="2"/>'
    w = _ext(_t("SHOCK", "Black Ops One", "#fef08a", stroke=ink, sw=8), 0, 7, "#7c3aed", 6)
    body += _sh(fit(w, 96, 90, 320, 110))
    body += fit(_t("THEATER", "Black Ops One", "#c4b5fd", ls=14), 136, 320, 240, 60)
    return svg(body, d)


@net("Spook Show", MOVIES, *HORROR, "retro")
def spook_show():
    return L.poster(
        "LIVE ON STAGE AT MIDNIGHT",
        "SPOOK",
        "SHOW",
        font="Bevan",
        small_font="Oswald",
        ink="#6b21a8",
        paper=("#f3e8d0", "#e2cfa4", "#bfa36b"),
        seed=13,
        deco="rule",
        word_box=(100, 150, 312, 120),
    )


@net("Fog Machine", MOVIES, *HORROR)
def fog_machine():
    d = SH + lin("fogp", [(0, "#1e293b"), (1, "#020617")])
    body = '<defs><clipPath id="fmc"><rect x="36" y="56" width="440" height="400" rx="24"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "url(#fogp)", rx=24, edge="#000", sw=5)
    body += fit(_t("FOG", "Cinzel", "#e2e8f0", weight=900, ls=24), 106, 120, 300, 130)
    body += fit(_t("MACHINE", "Cinzel", "#94a3b8", weight=700, ls=14), 106, 262, 300, 50)
    body += '<g clip-path="url(#fmc)">'
    for y, op, dx in ((216, 0.35, 0), (300, 0.45, 60), (370, 0.6, -40), (420, 0.75, 20)):
        body += f'<path d="M{-40 + dx} {y} Q{60 + dx} {y - 30} {160 + dx} {y} T{360 + dx} {y} T{560 + dx} {y} L{560 + dx} {y + 60} L{-40 + dx} {y + 60} Z" fill="#cbd5e1" opacity="{op}"/>'
    body += "</g>"
    return svg(body, d)


@net("Cheap Scares", MOVIES, *HORROR, "b-movies")
def cheap_scares():
    ink = "#111827"
    d = SH
    tag = "M100 120 L420 120 Q440 120 440 140 L440 372 Q440 392 420 392 L100 392 L40 256 Z"
    body = _sh(
        f'<path d="{tag}" fill="#f97316" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += f'<circle cx="96" cy="256" r="16" fill="#111827"/><path d="M80 256 Q30 200 10 120" fill="none" stroke="{ink}" stroke-width="4"/>'
    body += fit(_t("99¢", "Archivo Black", "#fff", stroke=ink, sw=8), 330, 140, 96, 60)
    body += fit(_t("CHEAP", "Archivo Black", ink, ls=4), 140, 190, 280, 80)
    body += fit(_t("SCARES", "Archivo Black", "#fff", stroke=ink, sw=8, ls=4), 140, 280, 280, 80)
    return svg(body, d)


@net("Jump Scare", MOVIES, *HORROR)
def jump_scare():
    ink = "#000"
    d = SH
    body = _panel(70, 120, 372, 290, "#111", rx=10, edge="#e5e7eb", sw=8)
    body += '<rect x="90" y="140" width="332" height="250" fill="#1f1f1f"/>'
    w = _ext(_t("JUMP", "Anton", "#fff", stroke=ink, sw=10, ls=2), 0, 8, "#dc2626", 6)
    body += _sh(fit(w, 30, 60, 452, 220))
    body += f'<rect x="146" y="320" width="220" height="64" fill="#dc2626" stroke="{ink}" stroke-width="5"/>'
    body += fit(_t("SCARE", "Anton", "#fff", ls=14), 166, 330, 180, 44)
    for x, y in ((40, 140), (470, 110), (30, 300), (480, 330)):
        body += f'<line x1="{x}" y1="{y}" x2="{x + (24 if x < 256 else -24)}" y2="{y + 8}" stroke="#facc15" stroke-width="7" stroke-linecap="round"/>'
    return svg(body, d)


@net("Cobweb Cinema", MOVIES, *HORROR, "classic horror")
def cobweb_cinema():
    d = SH
    body = _panel(36, 56, 440, 400, "#120d1a", rx=12, edge="#000", sw=5)
    web = ""
    for k in range(6):
        a = math.radians(k * 18)
        web += f'<line x1="476" y1="56" x2="{476 - 220 * math.cos(a):.0f}" y2="{56 + 220 * math.sin(a):.0f}"/>'
    for r in (50, 100, 150, 200):
        pts_ = [
            (476 - r * math.cos(math.radians(k * 18)), 56 + r * math.sin(math.radians(k * 18)))
            for k in range(6)
        ]
        web += (
            "<path d='M"
            + " Q".join(
                f"{476 - r * 0.9 * math.cos(math.radians(k * 18 + 9)):.0f} {56 + r * 0.9 * math.sin(math.radians(k * 18 + 9)):.0f} {x:.0f} {y:.0f}"
                if k
                else f"{x:.0f} {y:.0f}"
                for k, (x, y) in enumerate(pts_)
            )
            + "' fill='none'/>"
        )
    body += f'<g stroke="#cbd5e1" stroke-width="2" opacity=".6">{web}</g>'
    body += f'<g transform="scale(-1 1) translate(-512 0) translate(0 400) scale(1 -1) translate(0 -112)" stroke="#cbd5e1" stroke-width="2" opacity=".35">{web}</g>'
    body += _sh(fit(_t("Cobweb", "UnifrakturMaguntia", "#e9d5ff"), 76, 140, 360, 140))
    body += fit(_t("CINEMA", "Cinzel", "#a78bfa", weight=700, ls=18), 136, 300, 240, 50)
    return svg(body, d)


@net("Graveyard Shift", MOVIES, *HORROR)
def graveyard_shift():
    ink = "#0f172a"
    d = SH + lin("stone", [(0, "#cbd5e1"), (1, "#64748b")])
    body = '<rect x="20" y="420" width="472" height="40" rx="20" fill="#14532d"/>'
    body += _sh(
        f'<path d="M96 430 L96 190 Q96 50 256 50 Q416 50 416 190 L416 430 Z" fill="url(#stone)" stroke="{ink}" stroke-width="8"/>'
    )
    body += f'<path d="M150 120 L170 150 L160 180" fill="none" stroke="{ink}" stroke-width="3" opacity=".5"/>'
    body += fit(_t("GRAVEYARD", "Cinzel", ink, weight=900, ls=4), 120, 160, 272, 56)
    body += fit(_t("SHIFT", "Cinzel", ink, weight=900, ls=16), 150, 230, 212, 62)
    body += f'<line x1="156" y1="314" x2="356" y2="314" stroke="{ink}" stroke-width="3"/>'
    body += fit(
        _t("MIDNIGHT – DAWN", "Cinzel", "#334155", weight=700, ls=4, size=40), 156, 330, 200, 26
    )
    return svg(body, d)


@net("Things That Go Bump", MOVIES, *HORROR)
def things_that_go_bump():
    d = SH + glow("eyes", "#facc15", blur=6, strength=2)
    body = _panel(36, 56, 440, 400, "#05060f", rx=24, edge="#000", sw=5)
    for cx in (216, 296):
        body += f'<g filter="url(#eyes)"><ellipse cx="{cx}" cy="140" rx="26" ry="14" fill="#facc15"/></g><ellipse cx="{cx}" cy="140" rx="5" ry="12" fill="#05060f"/>'
    body += fit(
        _t("THINGS THAT GO", "Oswald", "#94a3b8", weight=700, ls=10, size=40), 116, 196, 280, 34
    )
    w = _ext(_t("BUMP", "Bowlby One", "#e2e8f0", stroke="#000", sw=10), 0, 8, "#4c1d95", 6)
    body += _sh(fit(w, 86, 244, 340, 140))
    for x, y in ((70, 280), (60, 320), (442, 280), (452, 320)):
        body += f'<line x1="{x}" y1="{y}" x2="{x + (20 if x < 256 else -20)}" y2="{y}" stroke="#a78bfa" stroke-width="6" stroke-linecap="round"/>'
    return svg(body, d)


@net("Monster Matinee", MOVIES, *HORROR, "monsters")
def monster_matinee():
    return L.marquee(
        "MONSTER",
        "MATINEE",
        crest="TODAY",
        crest_ink="#d9f99d",
        board="#f7fee7",
        letters="#14532d",
        frame="#15803d",
        edge="#052e16",
        font="Oswald",
    )


@net("Fright Lights", MOVIES, *HORROR)
def fright_lights():
    d = SH + glow("fo", "#fb923c", blur=8, strength=2) + glow("fp", "#c084fc", blur=8, strength=2)
    body = _panel(30, 80, 452, 352, "#0c0612", rx=30, edge="#000", sw=6)
    body += '<path d="M40 100 Q256 150 472 100" fill="none" stroke="#3f3f46" stroke-width="4"/>'
    for i in range(9):
        t = (i + 0.5) / 9
        x = 40 + 432 * t
        y = 100 + 4 * 50 * t * (1 - t)
        c = "#fb923c" if i % 2 == 0 else "#c084fc"
        body += f'<g filter="url(#{"fo" if i % 2 == 0 else "fp"})"><ellipse cx="{x:.0f}" cy="{y + 18:.0f}" rx="9" ry="13" fill="{c}"/></g>'
    for word, col, core, gid, y, h in (
        ("FRIGHT", "#fb923c", "#ffedd5", "fo", 170, 110),
        ("LIGHTS", "#c084fc", "#f3e8ff", "fp", 300, 100),
    ):
        tube = _t(word, "Bungee", "none", stroke=col, sw=7, ls=6)
        hot = _t(word, "Bungee", "none", stroke=core, sw=2.5, ls=6)
        body += fit(f'<g filter="url(#{gid})">{tube}</g>{hot}', 76, y, 360, h)
    return svg(body, d)


@net("Night Terrors", MOVIES, *HORROR)
def night_terrors():
    d = (
        SH
        + rough("ntr", amount=6, freq=0.06, seed=4)
        + lin("ntp", [(0, "#450a0a"), (1, "#0a0000")])
    )
    body = _panel(36, 56, 440, 400, "url(#ntp)", rx=16, edge="#000", sw=5)
    for i in range(3):
        body += f'<path d="M{330 + i * 34} 80 Q{370 + i * 34} 200 {320 + i * 34} 330" fill="none" stroke="#7f1d1d" stroke-width="{14 - i * 3}" stroke-linecap="round" opacity=".7"/>'
    body += fit(_t("NIGHT", "Cinzel", "#fca5a5", weight=400, ls=30), 96, 120, 320, 60)
    w = _t("TERRORS", "Cinzel", "#fef2f2", weight=900, stroke="#000", sw=6, ls=4)
    body += f'<g filter="url(#ntr)">{_sh(fit(w, 56, 200, 400, 110))}</g>'
    body += '<line x1="146" y1="342" x2="366" y2="342" stroke="#7f1d1d" stroke-width="3"/>'
    body += fit(
        _t("DON'T FALL ASLEEP", "Oswald", "#fca5a5", weight=600, ls=8, size=40), 156, 358, 200, 26
    )
    return svg(body, d)


@net("Coffin Theater", MOVIES, *HORROR, "classic horror")
def coffin_theater():
    ink = "#0a0a0a"
    d = SH + lin("cof", [(0, "#5b2a12"), (0.5, "#7c3a16"), (1, "#3b1a0a")], x2=1, y2=0)
    coffin = "M196 24 L316 24 L392 130 L352 488 L160 488 L120 130 Z"
    body = _sh(
        f'<path d="{coffin}" fill="url(#cof)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += '<path d="M206 46 L306 46 L366 132 L332 466 L180 466 L146 132 Z" fill="none" stroke="#d4a63a" stroke-width="3"/>'
    body += '<polygon points="256,84 286,130 256,176 226,130" fill="#d4a63a"/>'
    body += _sh(
        f'<rect x="40" y="226" width="432" height="120" rx="8" fill="{ink}" stroke="#d4a63a" stroke-width="4"/>'
    )
    body += fit(_t("COFFIN", "Cinzel", "#f5f0e6", weight=900, ls=10), 70, 238, 372, 60)
    body += fit(_t("THEATER", "Cinzel", "#d4a63a", weight=700, ls=18), 136, 302, 240, 32)
    return svg(body, d)


@net("Midnight Morgue", MOVIES, *HORROR)
def midnight_morgue():
    ink = "#1c1917"
    d = SH
    tag = "M60 120 L380 120 L460 200 L460 400 Q460 420 440 420 L60 420 Q40 420 40 400 L40 140 Q40 120 60 120 Z"
    body = '<path d="M420 170 Q480 120 470 40" fill="none" stroke="#a8a29e" stroke-width="5"/>'
    body += _sh(
        f'<path d="{tag}" fill="#f5f0e1" stroke="{ink}" stroke-width="6" transform="rotate(-6 256 270)"/>'
    )
    body += '<g transform="rotate(-6 256 270)"><circle cx="410" cy="186" r="16" fill="#1c1917" stroke="#a8a29e" stroke-width="5"/>'
    body += '<rect x="60" y="140" width="300" height="40" fill="#7f1d1d"/>'
    body += fit(_t("No. 12:00 AM", "Special Elite", "#fff", size=40), 74, 146, 272, 28)
    body += fit(_t("MIDNIGHT", "Special Elite", ink), 70, 196, 360, 80)
    body += fit(_t("MORGUE", "Special Elite", "#7f1d1d", ls=14), 90, 286, 320, 80)
    body += f'<line x1="70" y1="384" x2="420" y2="384" stroke="{ink}" stroke-width="2" opacity=".5"/></g>'
    return svg(body, d)


# ======================================================================= sci-fi

SCIFI = ("movies", "sci-fi", "science fiction")


def _stars(x, y, w, h, n, seed, colour="#fff"):
    rng = random.Random(seed)
    return "".join(
        f'<circle cx="{x + rng.random() * w:.0f}" cy="{y + rng.random() * h:.0f}" r="{rng.choice((1.4, 2, 2.6))}" fill="{colour}" opacity="{rng.choice((0.5, 0.8, 1))}"/>'
        for _ in range(n)
    )


@net("Deep Space Drive-In", MOVIES, *SCIFI, "drive-in")
def deep_space_drive_in():
    ink = "#020617"
    d = (
        SH
        + rad("dsd", [(0, "#4338ca"), (1, "#0b1026")])
        + rad("dsp", [(0, "#fde68a"), (1, "#f97316")], cx=0.35, cy=0.35)
    )
    body = (
        '<defs><clipPath id="dsc"><rect x="56" y="40" width="400" height="236"/></clipPath></defs>'
    )
    body += _sh(
        f'<rect x="44" y="28" width="424" height="260" rx="6" fill="#e5e7eb" stroke="{ink}" stroke-width="7"/>'
    )
    body += (
        '<g clip-path="url(#dsc)"><rect x="56" y="40" width="400" height="236" fill="url(#dsd)"/>'
        + _stars(56, 40, 400, 236, 40, 3)
    )
    body += '<circle cx="370" cy="110" r="44" fill="url(#dsp)"/><ellipse cx="370" cy="110" rx="80" ry="14" fill="none" stroke="#fde68a" stroke-width="5" transform="rotate(-16 370 110)"/></g>'
    body += fit(_t("DEEP SPACE", "Orbitron", "#e0e7ff", weight=900, ls=4), 80, 170, 280, 50)
    for x in (140, 372):
        body += f'<rect x="{x - 10}" y="288" width="20" height="90" fill="#475569"/>'
    body += _sh(
        f'<rect x="70" y="350" width="372" height="100" rx="12" fill="#dc2626" stroke="{ink}" stroke-width="7"/>'
    )
    body += _bulbs(
        [(x, 362) for x in range(90, 430, 24)] + [(x, 438) for x in range(90, 430, 24)], r=5
    )
    body += fit(_t("DRIVE-IN", "Bungee", "#fff"), 110, 374, 292, 52)
    return svg(body, d)


@net("Hyperdrive", MOVIES, *SCIFI, "space")
def hyperdrive():
    d = SH + rad("hy", [(0, "#ffffff"), (0.2, "#93c5fd"), (1, "#020617")])
    body = '<defs><clipPath id="hyc"><rect x="36" y="56" width="440" height="400" rx="24"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "url(#hy)", rx=24, edge="#000", sw=5)
    rng = random.Random(5)
    body += '<g clip-path="url(#hyc)">'
    for _ in range(70):
        a = rng.uniform(0, 2 * math.pi)
        r1 = rng.uniform(40, 140)
        r2 = r1 + rng.uniform(80, 220)
        body += f'<line x1="{256 + r1 * math.cos(a):.0f}" y1="{256 + r1 * math.sin(a):.0f}" x2="{256 + r2 * math.cos(a):.0f}" y2="{256 + r2 * math.sin(a):.0f}" stroke="#e0f2fe" stroke-width="{rng.choice((1.5, 2.5, 3.5))}" opacity=".8" stroke-linecap="round"/>'
    body += "</g>"
    body += '<rect x="36" y="206" width="440" height="100" fill="#020617" opacity=".7"/>'
    w = _ext(
        _t("HYPERDRIVE", "Orbitron", "#fff", weight=900, stroke="#0c4a6e", sw=8, style="italic"),
        4,
        6,
        "#0c4a6e",
        6,
    )
    body += _sh(fit(skew(w, -10), 50, 206, 412, 100))
    return svg(body, d)


@net("Cyber Cinema", MOVIES, *SCIFI, "cyberpunk")
def cyber_cinema():
    d = SH
    body = _panel(36, 70, 440, 372, "#050816", rx=12, edge="#000", sw=5)
    body += '<defs><clipPath id="ccc"><rect x="36" y="70" width="440" height="372" rx="12"/></clipPath></defs><g clip-path="url(#ccc)">'
    rng = random.Random(9)
    for _ in range(14):
        x, y = rng.randrange(50, 460, 10), rng.randrange(80, 430, 10)
        dx = rng.choice((40, 70, 100))
        body += f'<path d="M{x} {y} h{dx} v{rng.choice((-30, 30))}" fill="none" stroke="#0e7490" stroke-width="3" opacity=".6"/><circle cx="{x}" cy="{y}" r="4" fill="#22d3ee" opacity=".7"/>'
    body += "</g>"
    for dx, c in ((-6, "#f0f"), (6, "#0ff")):
        body += f'<g opacity=".75" transform="translate({dx} 0)">{fit(_t("CYBER", "Orbitron", c, weight=900, ls=6), 70, 130, 372, 120)}</g>'
    body += fit(_t("CYBER", "Orbitron", "#fff", weight=900, ls=6), 70, 130, 372, 120)
    body += '<rect x="70" y="190" width="372" height="8" fill="#050816" opacity=".8"/>'
    body += '<rect x="126" y="290" width="260" height="70" fill="#22d3ee"/>'
    body += fit(_t("CINEMA", "Orbitron", "#050816", weight=900, ls=12), 146, 304, 220, 42)
    return svg(body, d)


@net("Future Shock", MOVIES, *SCIFI)
def future_shock():
    ink = "#0f172a"
    d = (
        SH
        + lin("fsm", [(0, "#f1f5f9"), (0.5, "#94a3b8"), (1, "#e2e8f0")])
        + lin("fsa", [(0, "#22d3ee"), (1, "#a855f7")], x2=1, y2=0)
    )
    hexa = "M150 60 L362 60 L466 256 L362 452 L150 452 L46 256 Z"
    body = _sh(
        f'<path d="{hexa}" fill="url(#fsm)" stroke="{ink}" stroke-width="9" stroke-linejoin="round"/>'
    )
    body += f'<path d="{hexa}" fill="none" stroke="#fff" stroke-width="2" transform="translate(256 256) scale(.9) translate(-256 -256)"/>'
    for i in range(3):
        x = 150 + i * 70
        body += f'<polygon points="{x},92 {x + 60},92 {x + 100},150 {x + 60},208 {x},208 {x + 40},150" fill="url(#fsa)" stroke="{ink}" stroke-width="5" stroke-linejoin="round" opacity="{0.5 + i * 0.25}"/>'
    body += fit(_t("FUTURE", "Audiowide", ink, ls=6), 90, 236, 332, 80)
    body += f'<rect x="116" y="330" width="280" height="62" rx="6" fill="{ink}"/>'
    body += fit(_t("SHOCK", "Audiowide", "#22d3ee", ls=16), 140, 340, 232, 42)
    return svg(body, d)


@net("Robot Theater", MOVIES, *SCIFI, "robots")
def robot_theater():
    ink = "#0f172a"
    head = robot_head(P(a="#94a3b8", b="#ef4444", c="#22d3ee", k=ink, l="#e2e8f0"))
    return L.roundel(
        f'<g clip-path="url(#rc)"><rect x="0" y="0" width="512" height="512" fill="#1e3a8a"/>{centred(head, 256, 176, 230)}</g>',
        "ROBOT THEATER",
        font="Russo One",
        ink="#fff",
        disc="#1e3a8a",
        rim="#facc15",
        edge=ink,
        bar="#dc2626",
        ls=2,
        bar_y=300,
    )


@net("Laserlight", MOVIES, *SCIFI, "action")
def laserlight():
    d = SH + glow("lg1", "#22c55e", blur=5, strength=2) + glow("lg2", "#ef4444", blur=5, strength=2)
    body = '<defs><clipPath id="llc"><rect x="36" y="56" width="440" height="400" rx="24"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "#030712", rx=24, edge="#000", sw=5)
    body += '<g clip-path="url(#llc)">'
    for k in range(7):
        a = math.radians(-160 + k * 23)
        gid, c = ("lg1", "#86efac") if k % 2 else ("lg2", "#fca5a5")
        body += f'<g filter="url(#{gid})"><line x1="256" y1="470" x2="{256 + 600 * math.cos(a):.0f}" y2="{470 + 600 * math.sin(a):.0f}" stroke="{c}" stroke-width="4"/></g>'
    body += "</g>"
    body += _sh(
        '<rect x="46" y="190" width="420" height="132" rx="10" fill="#030712" opacity=".85"/>'
    )
    body += fit(_t("LASERLIGHT", "Michroma", "#f0fdf4", ls=4), 62, 214, 388, 84)
    return svg(body, d)


@net("Astro Cinema", MOVIES, *SCIFI, "retro")
def astro_cinema():
    ink = "#0f172a"
    d = SH + lin("ast", [(0, "#14b8a6"), (1, "#0f766e")])
    body = _sh(
        f'<path d="M60 380 Q40 200 200 120 L470 60 Q420 200 440 380 Z" fill="url(#ast)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    body += _sh(
        f'<polygon points="{star(420, 92, 56, 14, 8)}" fill="#facc15" stroke="{ink}" stroke-width="4"/>'
    )
    body += '<circle cx="120" cy="180" r="6" fill="#facc15"/><circle cx="160" cy="150" r="4" fill="#facc15"/>'
    body += _sh(fit(_t("Astro", "Lobster", "#fff7ed", stroke=ink, sw=10), 96, 160, 320, 130))
    body += f'<rect x="80" y="300" width="352" height="64" rx="32" fill="#f97316" stroke="{ink}" stroke-width="6"/>'
    body += fit(_t("CINEMA", "Archivo Black", "#fff", ls=16), 120, 312, 272, 40)
    return svg(body, d)


@net("Orbit Cinema", MOVIES, *SCIFI, "space")
def orbit_cinema():
    planet = (
        '<g transform="rotate(-20 100 100)"><path d="M0 100 A100 28 0 0 1 200 100" fill="none" stroke="#fde68a" stroke-width="12"/>'
        '<circle cx="100" cy="100" r="62" fill="#a855f7" stroke="#1e1b4b" stroke-width="8"/>'
        '<path d="M0 100 A100 28 0 0 0 200 100" fill="none" stroke="#1e1b4b" stroke-width="20"/><path d="M0 100 A100 28 0 0 0 200 100" fill="none" stroke="#fde68a" stroke-width="12"/></g>'
    )
    return L.letter_swap(
        "",
        planet,
        "RBIT",
        font="Unbounded",
        weight=900,
        ink="#fff",
        edge="#1e1b4b",
        sub="CINEMA",
        sub_font="Unbounded",
        sub_ink="#c4b5fd",
        sym_size=110,
        sym_dy=-36,
        extra_back=_panel(36, 96, 440, 320, "#1e1b4b", rx=30) + _stars(46, 106, 420, 300, 40, 4),
        box=(66, 150, 380, 150),
        sub_box=(146, 318, 220, 50),
    )


# ======================================================================= thrillers

THRILL = ("movies", "thriller", "suspense")


@net("Edge of Your Seat", MOVIES, *THRILL)
def edge_of_your_seat():
    ink = "#0a0a0a"
    d = SH
    body = _panel(36, 56, 440, 400, "#7f1d1d", rx=12, edge="#000", sw=5)
    body += f'<path d="M36 300 L330 300 L330 456 L36 456 Z" fill="{ink}"/>'
    body += f'<path d="M330 300 L476 456" stroke="{ink}" stroke-width="0"/>'
    w = _t("EDGE", "Anton", "#fef2f2", ls=6)
    body += _sh(fit(w, 70, 110, 300, 190))
    body += fit(_t("OF YOUR SEAT", "Oswald", "#fca5a5", weight=700, ls=10), 60, 330, 260, 40)
    body += '<line x1="60" y1="390" x2="300" y2="390" stroke="#7f1d1d" stroke-width="3"/>'
    body += fit(_t("THRILLERS", "Oswald", "#fef2f2", weight=600, ls=14, size=40), 60, 404, 180, 24)
    return svg(body, d)


@net("White Knuckle", MOVIES, *THRILL)
def white_knuckle():
    d = SH
    body = _panel(36, 70, 440, 372, "#0a0a0a", rx=12, edge="#000", sw=5)
    body += fit(_t("WHITE", "Bebas Neue", "#fff", ls=20), 76, 106, 360, 110)
    body += '<path d="M56 256 L170 256 L190 210 L214 300 L236 236 L252 256 L456 256" fill="none" stroke="#ef4444" stroke-width="7" stroke-linejoin="round"/>'
    body += fit(_t("KNUCKLE", "Bebas Neue", "#ef4444", ls=14), 76, 290, 360, 120)
    return svg(body, d)


@net("Nail Biter", MOVIES, *THRILL)
def nail_biter():
    ink = "#0a0a0a"
    d = SH + glow("nbg", "#ef4444", blur=6, strength=2)
    body = _panel(36, 70, 440, 372, "#18181b", rx=16, edge="#000", sw=5)
    body += fit(_t("NAIL BITER", "Anton", "#fafafa", ls=8), 66, 106, 380, 110)
    body += f'<rect x="126" y="250" width="260" height="130" rx="10" fill="{ink}" stroke="#3f3f46" stroke-width="5"/>'
    body += f'<g filter="url(#nbg)">{fit(_t("00:07", "VT323", "#ef4444"), 146, 262, 220, 106)}</g>'
    body += '<rect x="196" y="236" width="40" height="18" rx="4" fill="#ef4444"/><rect x="276" y="236" width="40" height="18" rx="4" fill="#3b82f6"/>'
    return svg(body, d)


@net("Double Cross", MOVIES, *THRILL)
def double_cross():
    ink = "#0a0a0a"
    d = SH
    body = _panel(36, 70, 440, 372, "#e7e5e4", rx=8, edge=ink, sw=6)
    body += '<path d="M90 110 L422 402 M422 110 L90 402" stroke="#dc2626" stroke-width="40" stroke-linecap="round" opacity=".35"/>'
    w = _t("DOUBLE", "Anton", "none", stroke=ink, sw=4, ls=6)
    body += f'<g transform="translate(8 8)">{fit(w, 76, 110, 360, 130)}</g>'
    body += fit(_t("DOUBLE", "Anton", ink, ls=6), 76, 110, 360, 130)
    body += f'<rect x="136" y="276" width="240" height="96" fill="{ink}"/>'
    body += fit(_t("CROSS", "Anton", "#e7e5e4", ls=14), 156, 290, 200, 68)
    return svg(body, d)


@net("Dark Alley", MOVIES, *THRILL, "noir")
def dark_alley():
    d = SH + rad("lamp", [(0, "#fef3c7"), (0.4, "#fde68a"), (1, "#0a0a0a")], cx=0.5, cy=0.25, r=0.6)
    body = '<defs><clipPath id="dac"><rect x="36" y="56" width="440" height="400" rx="10"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "#0a0a0a", rx=10, edge="#000", sw=5)
    body += '<g clip-path="url(#dac)">'
    body += '<polygon points="200,56 312,56 476,456 36,456" fill="#1c1917"/>'
    body += '<polygon points="36,56 200,56 220,300 36,456" fill="#292524"/><polygon points="476,56 312,56 292,300 476,456" fill="#292524"/>'
    for i in range(5):
        y = 90 + i * 50
        body += f'<rect x="{60 + i * 10}" y="{y}" width="40" height="26" fill="#0a0a0a"/><rect x="{412 - i * 10}" y="{y}" width="40" height="26" fill="#0a0a0a"/>'
    body += '<ellipse cx="256" cy="230" rx="160" ry="200" fill="url(#lamp)" opacity=".5"/>'
    body += '<rect x="250" y="120" width="12" height="40" fill="#57534e"/><path d="M236 160 L276 160 L268 174 L244 174 Z" fill="#fde68a"/>'
    body += "</g>"
    body += _sh(fit(_t("DARK ALLEY", "Bebas Neue", "#fafaf9", ls=12), 66, 330, 380, 100))
    return svg(body, d)


@net("Wiretap", MOVIES, *THRILL, "spy")
def wiretap():
    d = SH
    body = _panel(36, 96, 440, 320, "#1c1917", rx=14, edge="#000", sw=5)
    body += '<circle cx="80" cy="140" r="12" fill="#ef4444"/>'
    body += fit(_t("REC", "Special Elite", "#ef4444"), 100, 128, 60, 26)
    rng = random.Random(3)
    for i in range(46):
        x = 60 + i * 8.6
        h = rng.uniform(6, 60) * (1 - abs(i - 23) / 30)
        body += f'<rect x="{x:.1f}" y="{230 - h:.0f}" width="5" height="{2 * h:.0f}" rx="2" fill="#22c55e" opacity=".85"/>'
    body += fit(_t("WIRETAP", "Special Elite", "#fafaf9", ls=10), 76, 300, 360, 80)
    return svg(body, d)


@net("Getaway Car", MOVIES, *THRILL, "heist")
def getaway_car():
    ink = "#0a0a0a"
    d = (
        SH
        + glow("tl", "#ef4444", blur=10, strength=2)
        + lin("car", [(0, "#1f2937"), (1, "#030712")])
    )
    body = _panel(36, 70, 440, 372, "#0b1120", rx=20, edge="#000", sw=5)
    body += _sh(
        '<path d="M86 300 L96 190 Q100 160 140 156 L372 156 Q412 160 416 190 L426 300 Z" fill="url(#car)" stroke="#374151" stroke-width="5"/>'
    )
    body += '<path d="M140 166 L372 166 L390 220 L122 220 Z" fill="#111827" stroke="#374151" stroke-width="4"/>'
    for x in (126, 386):
        body += f'<g filter="url(#tl)"><rect x="{x - 34}" y="236" width="68" height="26" rx="6" fill="#ef4444"/></g>'
    body += '<rect x="206" y="240" width="100" height="40" rx="4" fill="#fef3c7" stroke="#0a0a0a" stroke-width="3"/>'
    body += fit(_t("GTWY 1", "Oswald", ink, weight=700), 216, 248, 80, 24)
    body += f'<rect x="96" y="300" width="60" height="30" rx="6" fill="{ink}"/><rect x="356" y="300" width="60" height="30" rx="6" fill="{ink}"/>'
    w = _t("GETAWAY CAR", "Racing Sans One", "#fff", stroke=ink, sw=10, style="italic")
    body += _sh(fit(w, 56, 340, 400, 80))
    return svg(body, d)


@net("Paper Trail", MOVIES, *THRILL, "conspiracy")
def paper_trail():
    ink = "#3b2410"
    d = SH + rough("stmp", amount=3, freq=0.8, seed=6)
    body = _sh(
        f'<path d="M50 120 L200 120 L220 96 L462 96 L462 440 L50 440 Z" fill="#e7c98a" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>'
    )
    body += '<rect x="80" y="150" width="352" height="260" fill="#fffbeb" stroke="#d6c08a" stroke-width="3" transform="rotate(3 256 280)"/>'
    for i in range(6):
        body += f'<rect x="110" y="{200 + i * 26}" width="{240 - (i % 3) * 40}" height="10" rx="3" fill="#a8a29e" transform="rotate(3 256 280)"/>'
    body += fit(_t("PAPER TRAIL", "Special Elite", "#1c1917", ls=4), 90, 150, 332, 50)
    body += '<g filter="url(#stmp)" transform="rotate(-12 256 330)"><rect x="96" y="290" width="320" height="80" rx="6" fill="none" stroke="#dc2626" stroke-width="7"/>'
    body += fit(_t("CONFIDENTIAL", "Special Elite", "#dc2626", ls=6), 112, 304, 288, 52) + "</g>"
    return svg(body, d)


# ======================================================================= romance

ROMANCE = ("movies", "romance", "love stories")


def _heart(cx, cy, s, fill, edge="none", sw=0):
    return (
        f'<path d="M{cx} {cy + s * 0.9} C{cx - s * 1.2} {cy + s * 0.1} {cx - s * 1.1} {cy - s * 0.9} {cx - s * 0.5} {cy - s * 0.9} '
        f"C{cx - s * 0.2} {cy - s * 0.9} {cx} {cy - s * 0.6} {cx} {cy - s * 0.4} C{cx} {cy - s * 0.6} {cx + s * 0.2} {cy - s * 0.9} {cx + s * 0.5} {cy - s * 0.9} "
        f'C{cx + s * 1.1} {cy - s * 0.9} {cx + s * 1.2} {cy + s * 0.1} {cx} {cy + s * 0.9} Z" fill="{fill}" stroke="{edge}" stroke-width="{sw}" stroke-linejoin="round"/>'
    )


@net("Date Night", MOVIES, *ROMANCE)
def date_night():
    d = (
        SH
        + lin("dn", [(0, "#4a044e"), (1, "#1e0626")])
        + lin("dng", [(0, "#fff3c4"), (0.5, "#e2b13c"), (1, "#a8741a")])
    )
    body = _panel(36, 80, 440, 352, "url(#dn)", rx=30, edge="#000", sw=5)
    body += '<rect x="56" y="100" width="400" height="312" rx="20" fill="none" stroke="url(#dng)" stroke-width="3"/>'
    body += _heart(256, 150, 30, "#f472b6")
    body += _sh(fit(_t("Date Night", "Great Vibes", "url(#dng)"), 70, 190, 372, 150))
    body += fit(
        _t("ROMANCE AFTER DARK", "Montserrat", "#f9a8d4", weight=600, ls=8, size=40),
        136,
        352,
        240,
        24,
    )
    return svg(body, d)


@net("Back Row", MOVIES, *ROMANCE)
def back_row():
    ink = "#0a0a0a"
    d = SH + rad("scrn", [(0, "#fef3c7"), (1, "#f59e0b")])
    body = _panel(36, 56, 440, 400, "#1c0a12", rx=20, edge="#000", sw=5)
    body += '<rect x="96" y="80" width="320" height="130" rx="6" fill="url(#scrn)" opacity=".9"/>'
    body += _heart(256, 140, 36, "#ef4444")
    for row, y in enumerate((300, 360)):
        for i in range(6):
            x = 66 + i * 66 + (row * 0)
            body += f'<rect x="{x}" y="{y}" width="56" height="70" rx="16" fill="#7f1d1d" stroke="{ink}" stroke-width="4"/>'
    body += _sh(
        f'<rect x="80" y="230" width="352" height="66" rx="8" fill="{ink}" stroke="#ef4444" stroke-width="3"/>'
    )
    body += fit(_t("BACK ROW", "Archivo Black", "#fecaca", ls=10), 100, 240, 312, 46)
    return svg(body, d)


@net("Swoon", MOVIES, *ROMANCE)
def swoon():
    d = SH + lin("sw", [(0, "#fbcfe8"), (1, "#f472b6")])
    body = _sh(
        '<circle cx="256" cy="256" r="210" fill="url(#sw)" stroke="#831843" stroke-width="7"/>'
    )
    body += '<circle cx="256" cy="256" r="190" fill="none" stroke="#fff" stroke-width="3"/>'
    body += _sh(fit(_t("Swoon", "Great Vibes", "#831843"), 86, 150, 340, 170))
    body += '<path d="M150 350 Q256 300 362 350" fill="none" stroke="#831843" stroke-width="3"/>'
    body += _heart(256, 380, 16, "#be185d")
    return svg(body, d)


@net("Love Seat", MOVIES, *ROMANCE)
def love_seat():
    seat = loveseat(P(a="#be123c", b="#fda4af", c="#fde68a", k="#4c0519", l="#fff1f2"))
    return L.sym_word(
        seat,
        "LOVE SEAT",
        font="Playfair Display",
        weight=900,
        ink="#fff1f2",
        edge="#4c0519",
        sub="ROMANCE FOR TWO",
        sub_font="Montserrat",
        sub_ink="#fda4af",
    )


@net("Happily Ever After", MOVIES, *ROMANCE, "fairy tales")
def happily_ever_after():
    d = SH + lin("hea", [(0, "#c4b5fd"), (0.6, "#fbcfe8"), (1, "#fde68a")])
    body = _panel(36, 56, 440, 400, "url(#hea)", rx=40, edge="#4c1d95", sw=6)
    castle = "M150 260 L150 160 L170 160 L170 130 L190 160 L210 160 L210 110 L230 80 L250 110 L250 150 L262 150 L262 110 L282 80 L302 110 L302 160 L322 160 L342 130 L342 160 L362 160 L362 260 Z"
    body += f'<path d="{castle}" fill="#fff" opacity=".85" stroke="#4c1d95" stroke-width="4" stroke-linejoin="round"/>'
    body += '<path d="M244 260 L244 220 Q256 204 268 220 L268 260 Z" fill="#c4b5fd"/>'
    for x, y in ((110, 110), (400, 130), (420, 220)):
        body += _sparkle(x, y, 16, "#fff")
    body += _sh(
        fit(
            _t("Happily Ever After", "Great Vibes", "#4c1d95", stroke="#fff", sw=6),
            50,
            268,
            412,
            150,
        )
    )
    return svg(body, d)


@net("Candlelight Cinema", MOVIES, *ROMANCE)
def candlelight_cinema():
    d = (
        SH
        + rad("flame", [(0, "#fffbeb"), (0.5, "#fbbf24"), (1, "#ea580c")], cy=0.6)
        + rad("halo", [(0, "#fde68a"), (1, "#1c0a00")])
    )
    body = _panel(36, 56, 440, 400, "#1c0a00", rx=24, edge="#000", sw=5)
    body += '<circle cx="256" cy="150" r="120" fill="url(#halo)" opacity=".7"/>'
    body += (
        '<path d="M256 80 Q286 130 270 170 Q256 190 242 170 Q226 130 256 80 Z" fill="url(#flame)"/>'
    )
    body += '<line x1="256" y1="168" x2="256" y2="190" stroke="#1c1917" stroke-width="4"/>'
    body += '<rect x="226" y="188" width="60" height="70" rx="6" fill="#fef3c7" stroke="#d6c08a" stroke-width="3"/>'
    body += _sh(fit(_t("Candlelight", "Great Vibes", "#fde68a"), 66, 262, 380, 110))
    body += fit(_t("CINEMA", "Cinzel", "#fbbf24", weight=700, ls=20), 156, 378, 200, 40)
    return svg(body, d)


@net("Three-Hanky Movies", MOVIES, *ROMANCE, "tearjerkers")
def three_hanky_movies():
    ink = "#1e3a8a"
    d = SH
    body = ""
    for i, (rot, c) in enumerate(((-18, "#bfdbfe"), (0, "#fbcfe8"), (18, "#ddd6fe"))):
        x = 156 + i * 100
        body += f'<g filter="url(#sh)" transform="rotate({rot} {x} 150)"><rect x="{x - 70}" y="80" width="140" height="140" rx="6" fill="{c}" stroke="{ink}" stroke-width="5"/>'
        body += f'<rect x="{x - 58}" y="92" width="116" height="116" rx="4" fill="none" stroke="#fff" stroke-width="4" stroke-dasharray="6 6"/></g>'
    body += _sh('<rect x="36" y="250" width="440" height="180" rx="20" fill="#eff6ff"/>')
    body += fit(_t("THREE-HANKY", "Playfair Display", ink, weight=900, ls=2), 60, 268, 392, 76)
    body += f'<rect x="146" y="356" width="220" height="56" rx="28" fill="{ink}"/>'
    body += fit(_t("MOVIES", "Montserrat", "#fff", weight=700, ls=16), 176, 368, 160, 32)
    return svg(body, d)


@net("Tissue Box", MOVIES, *ROMANCE, "tearjerkers")
def tissue_box_logo():
    ink = "#1e293b"
    d = SH
    box = tissue_box(P(a="#93c5fd", b="#bfdbfe", c="#fbcfe8", k=ink, l="#fff"))
    body = _sh(centred(box, 256, 200, 340))
    body += _sh(banner(28, 484, 330, 92, "#ec4899", ink, 6, cut=24))
    body += fit(_t("TISSUE BOX", "Archivo Black", "#fff", ls=4), 80, 344, 352, 62)
    return svg(body, d)


@net("Sweet Nothings", MOVIES, *ROMANCE)
def sweet_nothings():
    ink = "#831843"
    d = SH
    body = _sh(
        f'<rect x="76" y="50" width="360" height="250" rx="12" fill="#fdf2f8" stroke="{ink}" stroke-width="6"/>'
    )
    body += f'<path d="M76 56 L256 196 L436 56" fill="none" stroke="{ink}" stroke-width="5"/>'
    body += '<path d="M76 300 L210 168 M436 300 L302 168" fill="none" stroke="#f9a8d4" stroke-width="4"/>'
    body += _heart(256, 190, 34, "#be185d", ink, 4)
    body += _sh(
        fit(_t("Sweet Nothings", "Great Vibes", ink, stroke="#fff", sw=8), 46, 316, 420, 150)
    )
    return svg(body, d)


@net("Heart Throb", MOVIES, *ROMANCE)
def heart_throb():
    ink = "#4c0519"
    d = SH + rad("hth", [(0, "#fda4af"), (1, "#be123c")], cx=0.4, cy=0.35)
    body = _sh(_heart(256, 200, 150, "url(#hth)", ink, 9))
    body += '<path d="M30 220 L150 220 L180 160 L214 280 L246 190 L270 220 L482 220" fill="none" stroke="#fff" stroke-width="9" stroke-linejoin="round" stroke-linecap="round"/>'
    body += _sh(f'<rect x="56" y="350" width="400" height="90" rx="12" fill="{ink}"/>')
    body += fit(_t("HEART THROB", "Archivo Black", "#fecdd3", ls=6), 80, 366, 352, 58)
    return svg(body, d)


# ======================================================================= classic hollywood

CLASSIC = ("movies", "classic movies", "old hollywood")


def _gold(id_="gld"):
    return lin(id_, [(0, "#fff3c4"), (0.45, "#e2b13c"), (0.75, "#a8741a"), (1, "#f2d27a")])


@net("Old Hollywood", MOVIES, *CLASSIC)
def old_hollywood():
    d = SH + _gold() + lin("ohs", [(0, "#fef3c7"), (1, "#fef3c7")])
    body = '<defs><clipPath id="ohc"><rect x="36" y="56" width="440" height="400" rx="8"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "#0b0a08", rx=8, edge="#000", sw=5)
    body += '<g clip-path="url(#ohc)">'
    for x, ang in ((130, -18), (382, 18)):
        body += f'<polygon points="{x - 10},456 {x + 10},456 {x + 10 + 500 * math.sin(math.radians(ang)) + 50:.0f},0 {x - 10 + 500 * math.sin(math.radians(ang)) - 50:.0f},0" fill="#fef3c7" opacity=".12"/>'
    body += "</g>"
    body += '<rect x="56" y="76" width="400" height="360" rx="4" fill="none" stroke="url(#gld)" stroke-width="3"/>'
    body += _sh(fit(_t("Old Hollywood", "Great Vibes", "url(#gld)"), 66, 170, 380, 150))
    body += fit(
        _t("THE GOLDEN AGE OF FILM", "Cinzel", "#e2b13c", weight=700, ls=6, size=40),
        116,
        346,
        280,
        24,
    )
    body += f'<polygon points="{star(256, 130, 18, 7)}" fill="url(#gld)"/>'
    return svg(body, d)


@net("Studio Lot", MOVIES, *CLASSIC)
def studio_lot():
    ink = "#1c1917"
    d = SH + _gold() + lin("stucco", [(0, "#fef3c7"), (1, "#e7d3a3")])
    body = _sh(
        f'<path d="M40 470 L40 170 L100 170 L100 120 Q256 30 412 120 L412 170 L472 170 L472 470 L380 470 L380 260 Q256 190 132 260 L132 470 Z" fill="url(#stucco)" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/>'
    )
    for x in (160, 200, 240, 280, 320, 360):
        body += f'<line x1="{x}" y1="{260 - (60 - abs(x - 256) / 2.2):.0f}" x2="{x}" y2="470" stroke="{ink}" stroke-width="5"/>'
    body += f'<rect x="100" y="120" width="312" height="70" fill="#7c2d12" stroke="{ink}" stroke-width="5"/>'
    body += fit(_t("STUDIO LOT", "Cinzel", "url(#gld)", weight=900, ls=6), 116, 132, 280, 46)
    body += '<rect x="56" y="200" width="60" height="28" rx="4" fill="#7c2d12"/><rect x="396" y="200" width="60" height="28" rx="4" fill="#7c2d12"/>'
    body += fit(_t("GATE 2", "Oswald", "#fef3c7", weight=700, size=40), 62, 204, 48, 20) + fit(
        _t("EST. 1927", "Oswald", "#fef3c7", weight=700, size=40), 400, 204, 52, 20
    )
    return svg(body, d)


@net("Soundstage 9", MOVIES, *CLASSIC, "movies")
def soundstage_9():
    ink = "#1c1917"
    d = SH + lin("stg", [(0, "#d6d3d1"), (1, "#a8a29e")])
    body = _sh(
        f'<path d="M40 470 L40 170 Q256 60 472 170 L472 470 Z" fill="url(#stg)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    for x in range(70, 460, 26):
        body += f'<line x1="{x}" y1="{170 - (110 * (1 - ((x - 256) / 216) ** 2)):.0f}" x2="{x}" y2="470" stroke="#78716c" stroke-width="2" opacity=".5"/>'
    body += f'<rect x="300" y="300" width="140" height="170" fill="#57534e" stroke="{ink}" stroke-width="5"/>'
    body += (
        f'<g stroke="{ink}" stroke-width="3">'
        + "".join(f'<line x1="300" y1="{y}" x2="440" y2="{y}"/>' for y in range(320, 470, 20))
        + "</g>"
    )
    body += _sh(fit(_t("9", "Bevan", "#dc2626", stroke=ink, sw=6), 90, 150, 170, 220))
    body += f'<rect x="60" y="390" width="230" height="60" fill="{ink}"/>'
    body += fit(_t("SOUNDSTAGE", "Oswald", "#fef3c7", weight=700, ls=6), 72, 400, 206, 40)
    return svg(body, d)


@net("Picture Palace", MOVIES, *CLASSIC)
def picture_palace():
    ink = "#3b0a0a"
    d = SH + _gold() + lin("ppr", [(0, "#b91c1c"), (1, "#7f1d1d")])
    body = _sh(
        f'<path d="M256 30 Q300 70 300 110 L360 110 Q360 150 400 160 L440 160 L440 470 L72 470 L72 160 L112 160 Q152 150 152 110 L212 110 Q212 70 256 30 Z" fill="url(#ppr)" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/>'
    )
    body += '<path d="M256 30 Q300 70 300 110 L212 110 Q212 70 256 30 Z" fill="url(#gld)"/>'
    for x in (120, 392):
        body += f'<rect x="{x - 10}" y="170" width="20" height="300" fill="url(#gld)"/>'
    body += _sh(
        '<rect x="56" y="200" width="400" height="140" rx="8" fill="#1c0a0a" stroke="url(#gld)" stroke-width="5"/>'
    )
    body += fit(_t("PICTURE", "Cinzel", "url(#gld)", weight=900, ls=8), 86, 212, 340, 60)
    body += fit(_t("PALACE", "Cinzel", "#fef3c7", weight=700, ls=20), 116, 280, 280, 48)
    body += _bulbs([(x, 360) for x in range(96, 430, 26)], r=6)
    return svg(body, d)


@net("The Orpheum", MOVIES, *CLASSIC, "movie palace")
def the_orpheum():
    ink = "#1c1917"
    d = SH + _gold()
    body = _sh(
        f'<rect x="176" y="20" width="160" height="470" rx="14" fill="#7c2d12" stroke="{ink}" stroke-width="7"/>'
    )
    body += '<rect x="190" y="34" width="132" height="442" rx="8" fill="none" stroke="url(#gld)" stroke-width="4"/>'
    body += _bulbs(
        [(184, y) for y in range(40, 480, 22)] + [(328, y) for y in range(40, 480, 22)], r=5
    )
    body += fit(_t("THE", "Cinzel", "#fef3c7", weight=700, ls=6, size=40), 216, 46, 80, 24)
    for i, ch in enumerate("ORPHEUM"):
        body += fit(_t(ch, "Bevan", "url(#gld)", stroke=ink, sw=4), 220, 80 + i * 56, 72, 50)
    return svg(body, d)


@net("The Rialto", MOVIES, *CLASSIC, "movie palace")
def the_rialto():
    d = SH + glow("rg", "#f472b6", blur=8, strength=2) + glow("rb", "#38bdf8", blur=6, strength=2)
    body = _panel(30, 100, 452, 312, "#120a18", rx=16, edge="#000", sw=6)
    body += '<g filter="url(#rb)"><rect x="50" y="120" width="412" height="272" rx="10" fill="none" stroke="#38bdf8" stroke-width="5"/></g>'
    body += fit(_t("THE", "Oswald", "#bae6fd", weight=700, ls=12, size=40), 216, 140, 80, 26)
    neon = _t("Rialto", "Yellowtail", "none", stroke="#f472b6", sw=7)
    core = _t("Rialto", "Yellowtail", "none", stroke="#fdf2f8", sw=2.5)
    body += fit(f'<g filter="url(#rg)">{neon}</g>{core}', 86, 176, 340, 150)
    body += fit(
        _t("NOW SHOWING", "Oswald", "#bae6fd", weight=700, ls=12, size=40), 166, 346, 180, 26
    )
    return svg(body, d)


@net("The Roxy", MOVIES, *CLASSIC, "movie palace")
def the_roxy():
    ink = "#0f172a"
    d = SH + lin("chr", [(0, "#f8fafc"), (0.48, "#94a3b8"), (0.52, "#334155"), (1, "#e2e8f0")])
    body = _panel(36, 120, 440, 272, "#0f766e", rx=136, edge=ink, sw=7)
    for i in range(3):
        body += f'<rect x="60" y="{318 + i * 16}" width="392" height="6" rx="3" fill="#fef3c7" opacity="{0.9 - i * 0.25:.2f}"/>'
    body += fit(_t("THE", "Poiret One", "#fef3c7", weight=400, ls=16, size=40), 216, 150, 80, 26)
    body += _sh(fit(_t("ROXY", "Monoton", "#fef3c7"), 86, 182, 340, 126))
    return svg(body, d)


@net("The Bijou", MOVIES, *CLASSIC, "movie palace")
def the_bijou():
    ink = "#1e1b4b"
    d = SH + _gold()
    gem = "M256 40 L376 110 L376 250 L256 320 L136 250 L136 110 Z"
    body = _sh(
        f'<path d="{gem}" fill="#6d28d9" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/>'
    )
    for pts_, c in (
        ("256,40 376,110 256,180", "#a78bfa"),
        ("256,40 136,110 256,180", "#8b5cf6"),
        ("136,110 136,250 256,180", "#5b21b6"),
        ("376,110 376,250 256,180", "#7c3aed"),
        ("136,250 256,320 256,180", "#4c1d95"),
        ("376,250 256,320 256,180", "#6d28d9"),
    ):
        body += f'<polygon points="{pts_}" fill="{c}" stroke="{ink}" stroke-width="2"/>'
    body += (
        f'<path d="{gem}" fill="none" stroke="url(#gld)" stroke-width="6" stroke-linejoin="round"/>'
    )
    body += _sparkle(330, 86, 18, "#fff")
    body += _sh(
        f'<rect x="56" y="300" width="400" height="110" rx="10" fill="{ink}" stroke="url(#gld)" stroke-width="5"/>'
    )
    body += fit(_t("THE BIJOU", "Cinzel", "url(#gld)", weight=900, ls=8), 80, 320, 352, 70)
    return svg(body, d)


@net("Golden Era", MOVIES, *CLASSIC)
def golden_era():
    d = SH + _gold()
    leaves = ""
    for side in (-1, 1):
        for k in range(9):
            deg = 100 + k * 17 if side < 0 else 80 - k * 17
            a = math.radians(deg)
            for dr, tw in ((-13, -28), (13, 28)):
                r = 168 + dr
                cx, cy = 256 + r * math.cos(a), 236 + r * math.sin(a)
                leaves += f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="9" ry="21" fill="url(#gld)" stroke="#3b2a05" stroke-width="2" transform="rotate({deg + tw * side:.0f} {cx:.0f} {cy:.0f})"/>'
    body = _sh(leaves)
    body += fit(
        _t("GOLDEN", "Cinzel", "url(#gld)", weight=900, ls=8, stroke="#3b2a05", sw=3),
        126,
        170,
        260,
        66,
    )
    body += fit(_t("ERA", "Cinzel", "#fef3c7", weight=700, ls=30), 186, 248, 140, 52)
    body += f'<polygon points="{star(256, 128, 20, 8)}" fill="url(#gld)"/>'
    body += _sh(banner(76, 436, 380, 60, "#7f1d1d", "#3b2a05", 5, cut=18))
    body += fit(
        _t("CLASSIC MOVIES", "Cinzel", "#fef3c7", weight=700, ls=6, size=40), 136, 392, 240, 36
    )
    return svg(body, d)


@net("Monochrome", MOVIES, *CLASSIC, "black and white")
def monochrome():
    d = SH
    body = _sh('<rect x="36" y="56" width="440" height="400" rx="6" fill="#0a0a0a"/>')
    body += '<rect x="256" y="56" width="220" height="400" fill="#f5f5f4"/>'
    rng = random.Random(2)
    for _ in range(60):
        body += f'<circle cx="{rng.uniform(40, 470):.0f}" cy="{rng.uniform(60, 450):.0f}" r="1.5" fill="#78716c" opacity=".5"/>'
    w1 = fit(_t("MONO", "DM Serif Display", "#fff", ls=6), 66, 130, 380, 120)
    w2 = fit(_t("CHROME", "DM Serif Display", "#fff", ls=6), 66, 270, 380, 110)
    body += f'<g style="mix-blend-mode:difference">{w1}{w2}</g>'
    body += '<rect x="36" y="56" width="440" height="400" rx="6" fill="none" stroke="#0a0a0a" stroke-width="6"/>'
    return svg(body, d)


@net("Leading Man", MOVIES, *CLASSIC)
def leading_man():
    ink = "#0a0a0a"
    d = SH
    body = _panel(36, 56, 440, 400, "#0a0a0a", rx=16, edge="#000", sw=5)
    body += '<polygon points="160,56 256,300 352,56" fill="#f5f5f4"/>'
    body += '<polygon points="160,56 256,300 200,56" fill="#d6d3d1"/>'
    body += '<polygon points="96,56 160,56 256,300 210,330" fill="#1c1917"/><polygon points="416,56 352,56 256,300 302,330" fill="#1c1917"/>'
    body += f'<path d="M206 92 L246 112 L246 132 L206 152 Z M306 92 L266 112 L266 132 L306 152 Z" fill="#7f1d1d" stroke="{ink}" stroke-width="4"/><rect x="242" y="108" width="28" height="28" rx="4" fill="#991b1b" stroke="{ink}" stroke-width="4"/>'
    for y in (190, 236):
        body += f'<circle cx="256" cy="{y}" r="6" fill="#1c1917"/>'
    body += _sh('<rect x="56" y="330" width="400" height="100" rx="8" fill="#f5f5f4"/>')
    body += fit(_t("LEADING MAN", "DM Serif Display", ink, ls=4), 76, 344, 360, 72)
    return svg(body, d)


@net("Starlet", MOVIES, *CLASSIC)
def starlet():
    d = SH + _gold() + lin("sp", [(0, "#fbcfe8"), (1, "#db2777")])
    body = _sh(
        f'<polygon points="{star(256, 186, 160, 70)}" fill="url(#gld)" stroke="#831843" stroke-width="7" stroke-linejoin="round"/>'
    )
    body += f'<polygon points="{star(256, 186, 120, 52)}" fill="none" stroke="#fff7ed" stroke-width="3"/>'
    for x, y, r in ((420, 80, 22), (90, 120, 14), (430, 250, 12)):
        body += _sparkle(x, y, r, "#fbcfe8")
    body += _sh(
        fit(_t("Starlet", "Great Vibes", "url(#sp)", stroke="#fff", sw=6), 66, 300, 380, 150)
    )
    return svg(body, d)


# ======================================================================= video store

VIDEO = ("movies", "video store", "80s", "90s")


@net("Late Fee", MOVIES, *VIDEO)
def late_fee():
    ink = "#7f1d1d"
    d = SH + rough("lfr", amount=3, freq=0.8, seed=2)
    body = _sh(
        '<rect x="60" y="60" width="392" height="392" rx="6" fill="#fffbeb" stroke="#d6d3d1" stroke-width="3" transform="rotate(-4 256 256)"/>'
    )
    body += '<g transform="rotate(-4 256 256)">'
    body += fit(_t("RETURN BY: FRI 9PM", "Special Elite", "#57534e", size=40), 96, 90, 320, 28)
    for i in range(3):
        body += f'<rect x="96" y="{140 + i * 24}" width="{300 - i * 50}" height="8" rx="3" fill="#d6d3d1"/>'
    body += "</g>"
    body += f'<g filter="url(#lfr)" transform="rotate(-14 256 300)"><rect x="66" y="210" width="380" height="200" rx="16" fill="none" stroke="{ink}" stroke-width="10"/>'
    body += fit(_t("LATE FEE", "Black Ops One", "#dc2626", ls=4), 90, 230, 332, 96)
    body += fit(_t("$1.99 PER DAY", "Black Ops One", "#dc2626", ls=4), 120, 336, 272, 48) + "</g>"
    return svg(body, d)


@net("New Releases", MOVIES, *VIDEO, "new movies")
def new_releases():
    ink = "#0a0a0a"
    d = SH
    body = _sh(
        f'<rect x="30" y="60" width="452" height="120" rx="10" fill="#dc2626" stroke="{ink}" stroke-width="7"/>'
    )
    body += fit(_t("NEW RELEASES", "Archivo Black", "#fff", ls=4), 56, 84, 400, 72)
    body += _sh(
        f'<rect x="30" y="200" width="452" height="250" rx="8" fill="#292524" stroke="{ink}" stroke-width="6"/>'
    )
    cols = ("#1d4ed8", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#be123c", "#ca8a04")
    for row, y in enumerate((214, 334)):
        for i in range(len(cols)):
            x = 50 + i * 60
            body += f'<rect x="{x}" y="{y}" width="50" height="100" rx="3" fill="{cols[(i + row * 3) % 7]}" stroke="{ink}" stroke-width="3"/>'
            body += (
                f'<rect x="{x + 8}" y="{y + 14}" width="34" height="10" fill="#fff" opacity=".8"/>'
            )
    body += _sh(
        f'<polygon points="{star(430, 66, 46, 30, 12)}" fill="#facc15" stroke="{ink}" stroke-width="4"/>'
    )
    body += fit(_t("HOT!", "Archivo Black", ink), 408, 54, 44, 24)
    return svg(body, d)


@net("Please Rewind", MOVIES, *VIDEO)
def please_rewind():
    ink = "#1e1b4b"
    d = SH
    body = _sh(
        f'<circle cx="256" cy="256" r="212" fill="#facc15" stroke="{ink}" stroke-width="9"/>'
    )
    body += f'<circle cx="256" cy="256" r="190" fill="none" stroke="{ink}" stroke-width="3"/>'
    body += f'<polygon points="250,110 250,190 190,150" fill="{ink}"/><polygon points="320,110 320,190 260,150" fill="{ink}"/>'
    body += fit(_t("BE KIND", "Archivo Black", "#dc2626", ls=4), 136, 216, 240, 50)
    body += fit(_t("PLEASE", "Archivo Black", ink, ls=6), 136, 276, 240, 50)
    body += fit(_t("REWIND", "Archivo Black", ink, ls=6), 116, 334, 280, 64)
    return svg(body, d)


@net("Tracking", MOVIES, *VIDEO, "retro")
def tracking():
    d = SH
    body = '<defs><clipPath id="trc"><rect x="36" y="70" width="440" height="372" rx="14"/></clipPath></defs>'
    body += _panel(36, 70, 440, 372, "#1d4ed8", rx=14, edge="#000", sw=6)
    body += '<g clip-path="url(#trc)">'
    rng = random.Random(8)
    for _ in range(18):
        y = rng.uniform(70, 440)
        body += f'<rect x="{rng.uniform(-20, 300):.0f}" y="{y:.0f}" width="{rng.uniform(80, 300):.0f}" height="{rng.uniform(2, 8):.0f}" fill="#fff" opacity="{rng.uniform(0.15, 0.5):.2f}"/>'
    body += '<rect x="36" y="300" width="440" height="30" fill="#fff" opacity=".18"/></g>'
    body += fit(_t("PLAY ▶", "VT323", "#fff"), 66, 90, 140, 50)
    body += fit(_t("TRACKING", "VT323", "#fff", ls=6), 66, 170, 380, 110)
    body += (
        '<rect x="96" y="300" width="320" height="26" fill="none" stroke="#fff" stroke-width="4"/>'
    )
    body += '<rect x="102" y="306" width="200" height="14" fill="#fff"/>'
    body += fit(_t("- +", "VT323", "#fff"), 210, 340, 92, 40)
    return svg(body, d)


@net("Video Store Friday", MOVIES, *VIDEO)
def video_store_friday():
    d = SH + glow("vsf", "#ef4444", blur=8, strength=2)
    body = _panel(30, 70, 452, 372, "#0c0a09", rx=20, edge="#000", sw=6)
    tube = _t("VIDEO STORE", "Bungee", "none", stroke="#f87171", sw=7, ls=4)
    hot = _t("VIDEO STORE", "Bungee", "none", stroke="#fee2e2", sw=2.5, ls=4)
    body += fit(f'<g filter="url(#vsf)">{tube}</g>{hot}', 66, 110, 380, 80)
    body += _sh(
        fit(_t("Friday", "Yellowtail", "#facc15", stroke="#0c0a09", sw=8), 96, 200, 320, 140)
    )
    body += fit(
        _t("PICK 3 · KEEP 'TIL MONDAY", "Oswald", "#e7e5e4", weight=700, ls=6, size=40),
        106,
        364,
        300,
        26,
    )
    return svg(body, d)


@net("Top Shelf", MOVIES, *VIDEO, "best movies")
def top_shelf():
    ink = "#1c1917"
    d = SH + lin("wd", [(0, "#a0703c"), (1, "#6b4423")])
    body = _sh(
        f'<rect x="30" y="40" width="452" height="430" rx="8" fill="url(#wd)" stroke="{ink}" stroke-width="7"/>'
    )
    body += '<rect x="46" y="56" width="420" height="398" fill="#3b2410"/>'
    for y in (170, 300, 430):
        body += f'<rect x="46" y="{y}" width="420" height="16" fill="url(#wd)" stroke="{ink}" stroke-width="3"/>'
    cols = ("#facc15", "#dc2626", "#2563eb", "#16a34a", "#7c3aed", "#ea580c")
    for i in range(6):
        x = 70 + i * 64
        body += f'<rect x="{x}" y="70" width="52" height="100" rx="3" fill="{cols[i]}" stroke="{ink}" stroke-width="3"/>'
    body += _sh(
        f'<rect x="76" y="200" width="360" height="96" rx="8" fill="#fef3c7" stroke="{ink}" stroke-width="5"/>'
    )
    body += fit(_t("TOP SHELF", "Archivo Black", ink, ls=6), 96, 216, 320, 64)
    for i in range(5):
        body += f'<polygon points="{star(156 + i * 50, 372, 20, 9)}" fill="#facc15" stroke="{ink}" stroke-width="3"/>'
    return svg(body, d)


@net("Rental Night", MOVIES, *VIDEO)
def rental_night():
    ink = "#0a0a0a"
    d = SH
    body = _sh(
        f'<rect x="96" y="30" width="320" height="450" rx="16" fill="#1c1917" stroke="{ink}" stroke-width="7"/>'
    )
    body += '<rect x="112" y="46" width="288" height="418" rx="10" fill="none" stroke="#44403c" stroke-width="4"/>'
    body += '<rect x="130" y="80" width="252" height="260" rx="6" fill="#1e3a8a"/>'
    body += _stars_mv(130, 80, 252, 150)
    body += '<circle cx="330" cy="130" r="26" fill="#fef3c7"/><circle cx="342" cy="122" r="24" fill="#1e3a8a"/>'
    body += fit(_t("RENTAL", "Archivo Black", "#fef3c7", ls=4), 146, 220, 220, 54)
    body += fit(_t("NIGHT", "Archivo Black", "#facc15", ls=12), 166, 282, 180, 44)
    body += _sh(
        f'<circle cx="160" cy="400" r="40" fill="#dc2626" stroke="{ink}" stroke-width="4"/>'
    )
    body += fit(_t("2 DAY", "Archivo Black", "#fff", size=40), 132, 386, 56, 28)
    body += '<rect x="226" y="380" width="150" height="40" rx="4" fill="#fef3c7"/>'
    body += fit(_t("No. 04412", "Special Elite", ink, size=40), 236, 388, 130, 24)
    return svg(body, d)


def _stars_mv(x, y, w, h, n=24, seed=6):
    rng = random.Random(seed)
    return "".join(
        f'<circle cx="{x + rng.random() * w:.0f}" cy="{y + rng.random() * h:.0f}" r="2" fill="#fff" opacity=".8"/>'
        for _ in range(n)
    )


@net("Staff Picks", MOVIES, *VIDEO, "recommendations")
def staff_picks():
    ink = "#1e293b"
    d = SH
    body = _sh(
        '<rect x="60" y="56" width="392" height="400" rx="6" fill="#fef9c3" stroke="#ca8a04" stroke-width="3" transform="rotate(3 256 256)"/>'
    )
    body += '<g transform="rotate(3 256 256)">'
    body += '<rect x="220" y="40" width="72" height="30" fill="#fde68a" opacity=".9" transform="rotate(-8 256 55)"/>'
    body += fit(_t("STAFF", "Permanent Marker", "#dc2626"), 100, 90, 312, 100)
    body += fit(_t("PICKS", "Permanent Marker", "#2563eb"), 120, 196, 272, 96)
    body += '<path d="M120 300 Q256 286 392 300" fill="none" stroke="#dc2626" stroke-width="5" stroke-linecap="round"/>'
    for i in range(5):
        body += f'<polygon points="{star(146 + i * 55, 350, 22, 10)}" fill="#facc15" stroke="{ink}" stroke-width="3"/>'
    body += fit(_t("— Dana says: a must-see!", "Permanent Marker", ink), 110, 386, 292, 34) + "</g>"
    return svg(body, d)


# ======================================================================= drive-in & cult

CULT = ("movies", "cult movies", "b-movies")


@net("Speaker Box", MOVIES, *CULT, "drive-in")
def speaker_box():
    ink = "#111827"
    d = SH + lin("spk", [(0, "#cbd5e1"), (0.5, "#94a3b8"), (1, "#64748b")])
    body = '<path d="M256 470 L256 400" stroke="#475569" stroke-width="18"/>'
    body += f'<path d="M400 200 Q470 260 440 360 Q420 420 330 420" fill="none" stroke="{ink}" stroke-width="10"/>'
    body += _sh(
        f'<rect x="80" y="70" width="352" height="330" rx="40" fill="url(#spk)" stroke="{ink}" stroke-width="8"/>'
    )
    body += f'<rect x="106" y="40" width="300" height="50" rx="14" fill="#64748b" stroke="{ink}" stroke-width="6"/>'
    for y in range(110, 230, 20):
        body += f'<rect x="120" y="{y}" width="272" height="10" rx="5" fill="{ink}" opacity=".7"/>'
    body += _sh(
        f'<rect x="96" y="244" width="320" height="130" rx="10" fill="#dc2626" stroke="{ink}" stroke-width="6"/>'
    )
    body += fit(_t("SPEAKER", "Bungee", "#fff"), 116, 256, 280, 56)
    body += fit(_t("BOX", "Bungee", "#fef3c7", ls=16), 176, 316, 160, 46)
    return svg(body, d)


@net("Dusk to Dawn", MOVIES, *CULT, "drive-in", "all night")
def dusk_to_dawn():
    d = SH + lin("dtd", [(0, "#0b1026"), (0.55, "#7c3aed"), (0.8, "#f97316"), (1, "#fde047")])
    body = '<defs><clipPath id="dtc"><rect x="36" y="56" width="440" height="400" rx="24"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "url(#dtd)", rx=24, edge="#000", sw=5)
    body += '<g clip-path="url(#dtc)">' + _stars_mv(36, 56, 440, 140, 30, 9)
    body += '<rect x="140" y="250" width="232" height="120" fill="#0b1026"/><rect x="190" y="370" width="16" height="90" fill="#0b1026"/><rect x="306" y="370" width="16" height="90" fill="#0b1026"/>'
    body += '<rect x="36" y="430" width="440" height="30" fill="#0b1026"/></g>'
    body += fit(_t("DUSK", "Bevan", "#fef3c7"), 76, 96, 160, 80) + fit(
        _t("DAWN", "Bevan", "#fef3c7"), 276, 96, 160, 80
    )
    body += fit(_t("to", "Lobster", "#fde047"), 226, 120, 60, 50)
    body += fit(_t("ALL-NIGHT", "Oswald", "#fde047", weight=700, ls=10), 166, 268, 180, 40)
    body += fit(_t("MOVIES", "Oswald", "#fff", weight=700, ls=10), 176, 316, 160, 38)
    return svg(body, d)


@net("Car Hop", MOVIES, *CULT, "drive-in", "50s")
def car_hop():
    ink = "#1c1917"
    d = SH
    arrow = "M40 150 L380 150 L380 100 L480 220 L380 340 L380 290 L40 290 Z"
    body = _sh(
        f'<path d="{arrow}" fill="#dc2626" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    pts_ = (
        [(x, 170) for x in range(60, 380, 26)]
        + [(x, 270) for x in range(60, 380, 26)]
        + [(400 + i * 14, 140 + i * 14) for i in range(5)]
    )
    body += _bulbs(pts_, r=6)
    body += _sh(fit(_t("Car Hop", "Lobster", "#fef3c7", stroke=ink, sw=8), 70, 180, 300, 90))
    body += _sh(
        f'<rect x="140" y="350" width="232" height="70" rx="35" fill="#14b8a6" stroke="{ink}" stroke-width="6"/>'
    )
    body += fit(_t("DRIVE-IN", "Oswald", "#fff", weight=700, ls=10), 166, 364, 180, 40)
    return svg(body, d)


@net("Sticky Floor", MOVIES, *CULT, "comedy")
def sticky_floor():
    ink = "#3b0a0a"
    d = SH + lin("soda", [(0, "#7c2d12"), (1, "#431407")])
    body = _sh(
        f'<ellipse cx="256" cy="376" rx="200" ry="70" fill="url(#soda)" stroke="{ink}" stroke-width="6"/><circle cx="460" cy="420" r="16" fill="#7c2d12" stroke="{ink}" stroke-width="4"/><circle cx="60" cy="330" r="11" fill="#7c2d12" stroke="{ink}" stroke-width="4"/>'
    )
    body += '<ellipse cx="190" cy="370" rx="50" ry="10" fill="#fff" opacity=".25"/>'
    w = _ext(_t("STICKY", "Bowlby One", "#fde68a", stroke=ink, sw=12), 0, 8, ink, 6)
    body += _sh(fit(w, 66, 80, 380, 120))
    for x, h in ((130, 50), (210, 80), (300, 40), (370, 64)):
        body += f'<path d="M{x - 12} 180 L{x + 12} 180 L{x + 8} {190 + h} Q{x} {206 + h} {x - 8} {190 + h} Z" fill="#fde68a" stroke="{ink}" stroke-width="4"/>'
    body += fit(_t("FLOOR", "Bowlby One", "#fff", ls=14), 136, 344, 240, 64)
    return svg(body, d)


@net("Direct to Video", MOVIES, *CULT, "90s", "action")
def direct_to_video():
    ink = "#0a0a0a"
    d = SH + lin("dtv", [(0, "#f97316"), (0.5, "#ec4899"), (1, "#7c3aed")], x2=1, y2=1)
    body = _sh(
        f'<rect x="96" y="40" width="320" height="432" rx="8" fill="url(#dtv)" stroke="{ink}" stroke-width="7" transform="rotate(-5 256 256)"/>'
    )
    body += '<g transform="rotate(-5 256 256)">'
    body += f'<rect x="96" y="40" width="40" height="432" fill="{ink}"/>'
    body += fit(_t("DIRECT", "Anton", "#fff", stroke=ink, sw=8, ls=4), 150, 90, 240, 100)
    body += fit(_t("TO", "Anton", "#facc15", stroke=ink, sw=6), 230, 196, 80, 50)
    body += fit(_t("VIDEO", "Anton", "#fff", stroke=ink, sw=8, ls=4), 150, 252, 240, 100)
    body += "</g>"
    body += _sh(
        f'<polygon points="{star(380, 400, 76, 54, 16)}" fill="#facc15" stroke="{ink}" stroke-width="5"/>'
    )
    body += fit(_t("NEVER IN", "Anton", "#dc2626"), 340, 374, 80, 22) + fit(
        _t("THEATERS!", "Anton", "#dc2626"), 336, 400, 88, 24
    )
    return svg(body, d)


@net("Extra Cheese", MOVIES, *CULT, "comedy")
def extra_cheese():
    ink = "#3b2a05"
    ch = cheese(P(a="#facc15", b="#eab308", c="#ca8a04", k=ink, l="#fef08a"))
    body = _sh(centred(ch, 256, 170, 300))
    body += _sh(banner(28, 484, 300, 96, "#dc2626", ink, 7, cut=24))
    body += fit(_t("EXTRA CHEESE", "Archivo Black", "#fff", ls=2), 76, 316, 360, 62)
    body += fit(
        _t("GLORIOUSLY CHEESY MOVIES", "Oswald", "#fde68a", weight=700, ls=6, size=40),
        126,
        412,
        260,
        26,
    )
    return svg(body, SH)


@net("So Bad It's Good", MOVIES, *CULT, "comedy")
def so_bad_its_good():
    ink = "#0a0a0a"
    d = SH + rough("sbg", amount=3, freq=0.8, seed=11)
    body = _panel(36, 70, 440, 372, "#fef3c7", rx=10, edge=ink, sw=6)
    body += '<g filter="url(#sbg)" transform="rotate(-8 256 180)"><rect x="76" y="110" width="360" height="130" rx="12" fill="none" stroke="#dc2626" stroke-width="9"/>'
    body += fit(_t("SO BAD", "Black Ops One", "#dc2626", ls=6), 96, 126, 320, 98) + "</g>"
    body += '<g filter="url(#sbg)" transform="rotate(6 256 340)"><rect x="66" y="276" width="380" height="120" rx="12" fill="none" stroke="#16a34a" stroke-width="9"/>'
    body += fit(_t("IT'S GOOD!", "Black Ops One", "#16a34a", ls=4), 86, 292, 340, 88) + "</g>"
    return svg(body, d)


@net("Starlite Drive-In", MOVIES, *CULT, "drive-in", "50s")
def starlite_drive_in():
    ink = "#0f172a"
    d = SH + glow("sdg", "#f472b6", blur=7, strength=2)
    body = f'<rect x="236" y="300" width="40" height="190" fill="#475569" stroke="{ink}" stroke-width="5"/>'
    body += _sh(
        f'<path d="M60 120 Q60 60 120 60 L392 60 Q452 60 452 120 L452 260 Q452 320 392 320 L120 320 Q60 320 60 260 Z" fill="#0f766e" stroke="{ink}" stroke-width="8"/>'
    )
    body += _sh(
        f'<polygon points="{star(256, 60, 60, 26)}" fill="#facc15" stroke="{ink}" stroke-width="5"/>'
    )
    neon = _t("Starlite", "Yellowtail", "none", stroke="#f472b6", sw=7)
    core = _t("Starlite", "Yellowtail", "none", stroke="#fdf2f8", sw=2.5)
    body += fit(f'<g filter="url(#sdg)">{neon}</g>{core}', 96, 110, 320, 120)
    body += f'<rect x="96" y="240" width="320" height="56" rx="6" fill="#fef3c7" stroke="{ink}" stroke-width="4"/>'
    body += fit(_t("DRIVE-IN", "Oswald", "#0f766e", weight=700, ls=14), 126, 248, 260, 40)
    return svg(body, d)


@net("Cult Following", MOVIES, *CULT, "midnight movies")
def cult_following():
    d = SH + lin("cf", [(0, "#3b0764"), (1, "#0f0518")])
    body = _panel(36, 56, 440, 400, "url(#cf)", rx=18, edge="#000", sw=5)
    body += _sh(fit(_t("CULT", "Pirata One", "#f5d0fe"), 86, 86, 340, 180))
    body += fit(_t("FOLLOWING", "Cinzel", "#c084fc", weight=700, ls=12), 96, 280, 320, 46)
    for i in range(9):
        x = 76 + i * 45
        body += f'<circle cx="{x}" cy="380" r="14" fill="#0f0518"/><path d="M{x - 20} 456 Q{x - 20} 396 {x} 396 Q{x + 20} 396 {x + 20} 456 Z" fill="#0f0518"/>'
    body += '<rect x="36" y="350" width="440" height="4" fill="#c084fc" opacity=".4"/>'
    return svg(body, d)


@net("Bargain Matinee", MOVIES, *CULT, "classic movies")
def bargain_matinee():
    ink = "#14532d"
    d = SH
    tk = "M40 150 L472 150 L472 214 A42 42 0 0 0 472 298 L472 362 L40 362 L40 298 A42 42 0 0 0 40 214 Z"
    tkp = f'<path d="{tk}" fill="#dcfce7" stroke="{ink}" stroke-width="7"/>'
    body = f'<g transform="rotate(-6 256 256)">{_sh(tkp)}'
    body += f'<line x1="150" y1="160" x2="150" y2="352" stroke="{ink}" stroke-width="4" stroke-dasharray="10 8"/>'
    body += fit(_t("$2", "Archivo Black", "#16a34a"), 66, 214, 70, 84)
    body += fit(_t("BARGAIN", "Archivo Black", ink, ls=4), 170, 180, 270, 70)
    body += fit(_t("MATINEE", "Archivo Black", "#16a34a", ls=8), 180, 258, 250, 52)
    body += (
        fit(_t("SHOWS BEFORE 6PM", "Oswald", ink, weight=700, ls=6, size=40), 186, 318, 236, 24)
        + "</g>"
    )
    return svg(body, d)


# ======================================================================= epics, war & westerns

EPIC = ("movies", "epics", "adventure")


@net("Cast of Thousands", MOVIES, *EPIC, "classic movies")
def cast_of_thousands():
    d = SH + _gold() + lin("cot", [(0, "#7c2d12"), (1, "#1c0a00")])
    body = '<defs><clipPath id="cotc"><rect x="36" y="56" width="440" height="400" rx="12"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "url(#cot)", rx=12, edge="#000", sw=5)
    body += '<g clip-path="url(#cotc)">'
    for row in range(5):
        y = 330 + row * 28
        for i in range(24):
            x = 30 + i * 20 + (10 if row % 2 else 0)
            body += f'<circle cx="{x}" cy="{y}" r="9" fill="#0c0400" opacity="{0.6 + row * 0.08:.2f}"/><rect x="{x - 10}" y="{y + 6}" width="20" height="30" rx="8" fill="#0c0400" opacity="{0.6 + row * 0.08:.2f}"/>'
    body += "</g>"
    body += fit(_t("CAST OF", "Cinzel", "#fef3c7", weight=700, ls=14), 136, 96, 240, 44)
    body += _sh(fit(_t("THOUSANDS", "Cinzel", "url(#gld)", weight=900, ls=4), 66, 150, 380, 90))
    body += fit(
        _t("THE BIGGEST MOVIES EVER MADE", "Cinzel", "#fde68a", weight=700, ls=4, size=40),
        106,
        256,
        300,
        24,
    )
    return svg(body, d)


@net("Three-Hour Epic", MOVIES, *EPIC)
def three_hour_epic():
    ink = "#3b2a05"
    d = SH + _gold() + lin("sand", [(0, "#fde68a"), (1, "#f59e0b")])
    body = _sh(
        f'<rect x="166" y="30" width="180" height="22" rx="6" fill="url(#gld)" stroke="{ink}" stroke-width="5"/><rect x="166" y="300" width="180" height="22" rx="6" fill="url(#gld)" stroke="{ink}" stroke-width="5"/>'
    )
    body += f'<path d="M186 52 Q186 140 248 176 Q186 212 186 300 L326 300 Q326 212 264 176 Q326 140 326 52 Z" fill="#e0f2fe" fill-opacity=".5" stroke="{ink}" stroke-width="6"/>'
    body += '<path d="M206 100 L306 100 Q296 140 256 168 Q216 140 206 100 Z" fill="url(#sand)"/>'
    body += '<path d="M252 176 L252 260" stroke="#f59e0b" stroke-width="4"/><path d="M206 296 Q256 240 306 296 Z" fill="url(#sand)"/>'
    body += _sh(banner(28, 484, 340, 90, "#7f1d1d", ink, 6, cut=24))
    body += fit(_t("THREE-HOUR EPIC", "Cinzel", "url(#gld)", weight=900, ls=2), 76, 356, 360, 58)
    return svg(body, d)


@net("Front Line", MOVIES, "movies", "war", "action")
def front_line():
    ink = "#1a1f0e"
    d = SH + lin("od", [(0, "#556b2f"), (1, "#3b4a1f")])
    body = _panel(36, 70, 440, 372, "url(#od)", rx=10, edge=ink, sw=7)
    for x in (60, 452):
        for y in (94, 418):
            body += (
                f'<circle cx="{x}" cy="{y}" r="8" fill="#2a3317" stroke="{ink}" stroke-width="3"/>'
            )
    for i in range(3):
        body += f'<path d="M196 {108 + i * 26} L256 {84 + i * 26} L316 {108 + i * 26}" fill="none" stroke="#e7e5c8" stroke-width="12" stroke-linejoin="miter"/>'
    body += fit(_t("FRONT LINE", "Black Ops One", "#e7e5c8", ls=6), 66, 196, 380, 110)
    body += '<rect x="96" y="330" width="320" height="6" fill="#e7e5c8"/>'
    body += fit(_t("WAR MOVIES", "Black Ops One", "#e7e5c8", ls=14, size=40), 156, 352, 200, 32)
    return svg(body, d)


@net("Foxhole", MOVIES, "movies", "war")
def foxhole():
    ink = "#1c1917"
    d = SH
    hm = helmet(P(a="#556b2f", b="#3b4a1f", c="#6b7c3a", k=ink, l="#fff"))
    body = ""
    for row, (y, n) in enumerate(((330, 5), (290, 4))):
        for i in range(n):
            x = 96 + i * 80 + (40 if row else 0)
            body += f'<rect x="{x - 40}" y="{y}" width="80" height="44" rx="20" fill="#c2a878" stroke="{ink}" stroke-width="5"/>'
    body = centred(hm, 256, 230, 230) + body
    body = _sh(body)
    body += _sh(f'<rect x="56" y="384" width="400" height="80" rx="8" fill="{ink}"/>')
    body += fit(_t("FOXHOLE", "Black Ops One", "#e7e5c8", ls=10), 86, 396, 340, 56)
    return svg(body, d)


@net("Six-Gun Cinema", MOVIES, "movies", "westerns")
def six_gun_cinema():
    ink = "#2b1408"
    d = SH + rad("cyl", [(0, "#e5e7eb"), (1, "#6b7280")], cx=0.4, cy=0.35)
    body = _sh(
        f'<circle cx="256" cy="196" r="150" fill="url(#cyl)" stroke="{ink}" stroke-width="8"/>'
    )
    for k in range(6):
        a = math.radians(k * 60 - 90)
        body += f'<circle cx="{256 + 88 * math.cos(a):.0f}" cy="{196 + 88 * math.sin(a):.0f}" r="34" fill="#1f2937" stroke="{ink}" stroke-width="5"/><circle cx="{256 + 88 * math.cos(a):.0f}" cy="{196 + 88 * math.sin(a):.0f}" r="20" fill="#b45309"/>'
    body += f'<circle cx="256" cy="196" r="18" fill="#374151" stroke="{ink}" stroke-width="4"/>'
    body += _sh(banner(28, 484, 316, 100, "#7c2d12", ink, 7, cut=26))
    body += fit(_t("SIX-GUN CINEMA", "Rye", "#fef3c7"), 80, 334, 352, 64)
    return svg(body, d)


@net("Saddle Theater", MOVIES, "movies", "westerns")
def saddle_theater():
    ink = "#2b1408"
    d = SH + lin("wdf", [(0, "#b07a3e"), (1, "#7c4a21")])
    front = "M60 470 L60 150 L120 150 L120 100 L170 100 L170 60 L342 60 L342 100 L392 100 L392 150 L452 150 L452 470 Z"
    body = _sh(
        f'<path d="{front}" fill="url(#wdf)" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    )
    for x in range(80, 452, 24):
        body += f'<line x1="{x}" y1="150" x2="{x}" y2="470" stroke="{ink}" stroke-width="2" opacity=".35"/>'
    body += f'<rect x="90" y="120" width="332" height="110" rx="6" fill="#fef3c7" stroke="{ink}" stroke-width="6"/>'
    body += fit(_t("SADDLE", "Rye", "#7c2d12", ls=4), 110, 130, 292, 54)
    body += fit(_t("THEATER", "Rye", ink, ls=10), 130, 188, 252, 34)
    body += f'<rect x="200" y="300" width="112" height="170" fill="#3b2410" stroke="{ink}" stroke-width="6"/><line x1="256" y1="300" x2="256" y2="470" stroke="{ink}" stroke-width="4"/>'
    for x in (100, 340):
        body += f'<rect x="{x}" y="270" width="72" height="80" fill="#fde68a" stroke="{ink}" stroke-width="5"/>'
    return svg(body, d)


@net("Battle Stations", MOVIES, "movies", "war", "navy")
def battle_stations():
    ink = "#0f172a"
    d = (
        SH
        + lin("navy", [(0, "#94a3b8"), (1, "#475569")])
        + glow("alarm", "#ef4444", blur=8, strength=2)
    )
    body = _panel(36, 96, 440, 340, "url(#navy)", rx=10, edge=ink, sw=7)
    for x in (60, 452):
        for y in (120, 412):
            body += (
                f'<circle cx="{x}" cy="{y}" r="8" fill="#334155" stroke="{ink}" stroke-width="3"/>'
            )
    body += '<g filter="url(#alarm)"><path d="M216 96 L216 70 Q216 40 256 40 Q296 40 296 70 L296 96 Z" fill="#ef4444"/></g>'
    body += f'<path d="M216 96 L216 70 Q216 40 256 40 Q296 40 296 70 L296 96 Z" fill="none" stroke="{ink}" stroke-width="5"/>'
    body += fit(_t("BATTLE", "Black Ops One", "#f8fafc", stroke=ink, sw=6, ls=8), 76, 140, 360, 110)
    body += fit(
        _t("STATIONS", "Black Ops One", "#fef08a", stroke=ink, sw=5, ls=6), 76, 266, 360, 76
    )
    body += f'<rect x="36" y="376" width="440" height="30" fill="{ink}"/>'
    body += fit(
        _t("NAVAL WAR MOVIES", "Oswald", "#e2e8f0", weight=700, ls=10, size=40), 146, 380, 220, 22
    )
    return svg(body, d)


@net("Sword & Sandal", MOVIES, *EPIC, "historical")
def sword_and_sandal():
    ink = "#3b2a05"
    d = SH + lin("marble", [(0, "#fafaf9"), (1, "#d6d3d1")]) + _gold()
    body = _sh(
        f'<polygon points="40,150 256,50 472,150" fill="url(#marble)" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/>'
    )
    body += f'<polygon points="90,140 256,72 422,140" fill="none" stroke="{ink}" stroke-width="3"/>'
    body += _sh(
        f'<rect x="40" y="150" width="432" height="76" fill="url(#marble)" stroke="{ink}" stroke-width="7"/>'
    )
    body += fit(_t("SWORD & SANDAL", "Cinzel", ink, weight=900, ls=2), 60, 164, 392, 48)
    for x in (80, 172, 264, 356):
        body += f'<rect x="{x}" y="226" width="56" height="200" fill="url(#marble)" stroke="{ink}" stroke-width="5"/>'
        for k in range(1, 4):
            body += f'<line x1="{x + k * 14}" y1="232" x2="{x + k * 14}" y2="420" stroke="#a8a29e" stroke-width="2"/>'
    body += _sh(
        f'<rect x="30" y="426" width="452" height="40" fill="url(#gld)" stroke="{ink}" stroke-width="6"/>'
    )
    body += fit(
        _t("EPICS OF THE ANCIENT WORLD", "Cinzel", ink, weight=700, ls=4, size=40), 76, 434, 360, 24
    )
    return svg(body, d)


@net("High Seas", MOVIES, *EPIC, "pirates", "swashbucklers")
def high_seas():
    ink = "#0c1a2e"
    d = SH + lin("hsk", [(0, "#fde68a"), (1, "#f97316")])
    centre = '<g clip-path="url(#rc)"><rect x="0" y="0" width="512" height="512" fill="url(#hsk)"/>'
    centre += f'<path d="M180 250 L330 250 L310 280 L200 280 Z" fill="#3b2410" stroke="{ink}" stroke-width="4"/>'
    centre += f'<line x1="256" y1="90" x2="256" y2="250" stroke="{ink}" stroke-width="6"/><line x1="206" y1="130" x2="206" y2="250" stroke="{ink}" stroke-width="5"/>'
    for x, top, h, w in (
        (256, 96, 60, 70),
        (256, 166, 64, 80),
        (206, 140, 50, 50),
        (206, 196, 44, 58),
    ):
        centre += f'<path d="M{x - w / 2:.0f} {top} Q{x} {top + 10} {x + w / 2:.0f} {top} L{x + w / 2 + 6:.0f} {top + h} Q{x} {top + h + 12} {x - w / 2 - 6:.0f} {top + h} Z" fill="#fef3c7" stroke="{ink}" stroke-width="4"/>'
    centre += '<path d="M30 290 Q100 260 170 290 T310 290 T450 290 L500 290 L500 512 L0 512 Z" fill="#0e7490"/></g>'
    return L.roundel(
        centre,
        "HIGH SEAS",
        font="Pirata One",
        ink="#fef3c7",
        disc="#fde68a",
        rim="#fef3c7",
        edge=ink,
        bar=ink,
        defs=d.replace(SH, ""),
        ls=6,
        bar_y=300,
    )


@net("Wide Open Range", MOVIES, "movies", "westerns")
def wide_open_range():
    ink = "#2b1408"
    d = (
        SH
        + lin("wsky", [(0, "#38bdf8"), (1, "#e0f2fe")])
        + lin("grass", [(0, "#eab308"), (1, "#a16207")])
    )
    body = '<defs><clipPath id="worc"><rect x="20" y="130" width="472" height="252" rx="12"/></clipPath></defs>'
    body += _panel(20, 130, 472, 252, "url(#wsky)", rx=12, edge=ink, sw=6)
    body += '<g clip-path="url(#worc)"><path d="M20 290 L120 250 L190 270 L260 236 L360 268 L492 246 L492 382 L20 382 Z" fill="#7c3aed" opacity=".35"/>'
    body += '<rect x="20" y="290" width="472" height="92" fill="url(#grass)"/>'
    for x in range(40, 492, 60):
        body += f'<rect x="{x}" y="300" width="6" height="44" fill="{ink}"/>'
    body += f'<line x1="20" y1="312" x2="492" y2="312" stroke="{ink}" stroke-width="3"/><line x1="20" y1="330" x2="492" y2="330" stroke="{ink}" stroke-width="3"/>'
    body += '<circle cx="400" cy="180" r="26" fill="#fef9c3"/></g>'
    body += _sh(fit(_t("WIDE OPEN", "Rye", "#fff", stroke=ink, sw=8, ls=8), 46, 160, 420, 70))
    body += _sh(fit(_t("RANGE", "Rye", "#fef3c7", stroke=ink, sw=8, ls=40), 46, 236, 420, 56))
    return svg(body, d)


# ======================================================================= arthouse & world

ART = ("movies", "independent", "world cinema")


@net("Festival Circuit", MOVIES, *ART, "festival films")
def festival_circuit():
    ink = "#0a0a0a"
    d = SH + _gold()
    body = _sh(f'<circle cx="256" cy="256" r="216" fill="{ink}"/>')
    for k in range(28):
        a = math.radians(k * 360 / 28)
        x, y = 256 + 196 * math.cos(a), 256 + 196 * math.sin(a)
        body += f'<rect x="{x - 9:.0f}" y="{y - 7:.0f}" width="18" height="14" rx="3" fill="#fef3c7" transform="rotate({k * 360 / 28 + 90:.0f} {x:.0f} {y:.0f})"/>'
    body += '<circle cx="256" cy="256" r="172" fill="#7f1d1d" stroke="url(#gld)" stroke-width="5"/>'
    for k in range(5):
        a = math.radians(-90 + k * 72)
        body += f'<polygon points="{star(256 + 150 * math.cos(a), 256 + 150 * math.sin(a), 11, 4.5)}" fill="url(#gld)"/>'
    body += fit(_t("FESTIVAL", "Cinzel", "url(#gld)", weight=900, ls=6), 116, 196, 280, 52)
    body += fit(_t("CIRCUIT", "Cinzel", "#fef3c7", weight=700, ls=16), 146, 256, 220, 40)
    return svg(body, d)


@net("Passport Cinema", MOVIES, *ART, "foreign films")
def passport_cinema():
    ink = "#0b1026"
    d = SH + _gold() + lin("pp", [(0, "#1e3a8a"), (1, "#172554")])
    body = _panel(96, 30, 320, 452, "url(#pp)", rx=14, edge=ink, sw=6)
    body += fit(_t("PASSPORT", "Cinzel", "url(#gld)", weight=900, ls=8), 126, 80, 260, 44)
    g = '<circle cx="100" cy="100" r="80" fill="none" stroke="url(#gld)" stroke-width="7"/>'
    g += '<ellipse cx="100" cy="100" rx="38" ry="80" fill="none" stroke="url(#gld)" stroke-width="5"/>'
    g += '<line x1="20" y1="100" x2="180" y2="100" stroke="url(#gld)" stroke-width="5"/><path d="M34 60 Q100 76 166 60 M34 140 Q100 124 166 140" fill="none" stroke="url(#gld)" stroke-width="5"/>'
    body += centred(g, 256, 236, 180)
    body += fit(_t("CINEMA", "Cinzel", "url(#gld)", weight=900, ls=14), 146, 352, 220, 40)
    body += '<rect x="226" y="410" width="60" height="40" rx="6" fill="none" stroke="#e2b13c" stroke-width="3"/><rect x="236" y="420" width="40" height="20" fill="none" stroke="#e2b13c" stroke-width="2"/>'
    return svg(body, d)


def _branch(side, cx, cy, h, fill):
    s = f'<path d="M{cx} {cy + h / 2} Q{cx - side * 46} {cy} {cx} {cy - h / 2}" fill="none" stroke="{fill}" stroke-width="5"/>'
    for k in range(8):
        t = k / 7
        y = cy + h / 2 - t * h
        x = cx - side * 46 * 4 * t * (1 - t) * 0.5
        rot = -side * (30 + t * 20)
        s += f'<ellipse cx="{x - side * 14:.0f}" cy="{y:.0f}" rx="7" ry="17" fill="{fill}" transform="rotate({rot:.0f} {x - side * 14:.0f} {y:.0f})"/>'
        s += f'<ellipse cx="{x + side * 8:.0f}" cy="{y - 6:.0f}" rx="6" ry="15" fill="{fill}" transform="rotate({-rot:.0f} {x + side * 8:.0f} {y - 6:.0f})"/>'
    return s


@net("Laurel Wreath", MOVIES, *ART, "award winners", "festival films")
def laurel_wreath():
    d = SH
    body = _panel(36, 96, 440, 320, "#0a0a0a", rx=10, edge="#000", sw=5)
    body += _branch(1, 96, 256, 230, "#f5f5f4") + _branch(-1, 416, 256, 230, "#f5f5f4")
    body += fit(
        _t("OFFICIAL SELECTION", "Montserrat", "#d6d3d1", weight=600, ls=6, size=40),
        146,
        160,
        220,
        20,
    )
    body += fit(_t("LAUREL", "Playfair Display", "#fafaf9", weight=900, ls=8), 146, 194, 220, 70)
    body += fit(_t("WREATH", "Playfair Display", "#fafaf9", weight=400, ls=14), 156, 276, 200, 44)
    body += fit(
        _t("AWARD-WINNING FILMS", "Montserrat", "#a8a29e", weight=600, ls=4, size=40),
        156,
        336,
        200,
        18,
    )
    return svg(body, d)


@net("World Cinema", MOVIES, *ART, "foreign films")
def world_cinema():
    ink = "#0f172a"
    d = SH + rad("wc", [(0, "#5eead4"), (1, "#0f766e")], cx=0.38, cy=0.35)
    body = _sh(
        f'<circle cx="256" cy="170" r="130" fill="url(#wc)" stroke="{ink}" stroke-width="7"/>'
    )
    body += '<g fill="none" stroke="#ccfbf1" stroke-width="4" opacity=".8">'
    body += '<ellipse cx="256" cy="170" rx="60" ry="130"/><line x1="126" y1="170" x2="386" y2="170"/><path d="M144 110 Q256 130 368 110 M144 230 Q256 210 368 230"/></g>'
    for k in range(16):
        a = math.radians(k * 22.5)
        body += f'<rect x="{256 + 150 * math.cos(a) - 7:.0f}" y="{170 + 150 * math.sin(a) - 5:.0f}" width="14" height="10" rx="2" fill="#f97316"/>'
    body += fit(_t("WORLD", "Playfair Display", "#f8fafc", weight=900, ls=14), 96, 330, 320, 72)
    body += fit(_t("CINEMA", "Montserrat", "#f97316", weight=700, ls=18), 156, 414, 200, 34)
    return svg(body, d)


@net("Short List", MOVIES, *ART, "short films")
def short_list():
    ink = "#1c1917"
    d = SH
    body = _sh(
        f'<rect x="96" y="40" width="320" height="432" rx="8" fill="#fafaf9" stroke="{ink}" stroke-width="6"/>'
    )
    body += f'<rect x="96" y="40" width="320" height="110" rx="8" fill="{ink}"/>'
    body += fit(_t("SHORT", "Bebas Neue", "#fafaf9", ls=14), 126, 56, 260, 44)
    body += fit(_t("LIST", "Bebas Neue", "#f59e0b", ls=30), 186, 104, 140, 36)
    for i in range(5):
        y = 186 + i * 54
        body += f'<rect x="126" y="{y}" width="30" height="30" rx="4" fill="none" stroke="{ink}" stroke-width="4"/>'
        if i < 3:
            body += f'<path d="M130 {y + 16} L140 {y + 26} L156 {y + 2}" fill="none" stroke="#dc2626" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
        body += f'<rect x="172" y="{y + 10}" width="{200 - (i % 2) * 50}" height="10" rx="4" fill="#a8a29e"/>'
    return svg(body, d)


@net("Film Society", MOVIES, *ART, "classic movies")
def film_society():
    centre = fit(_t("FS", "Playfair Display", "#7f1d1d", weight=900), 176, 186, 160, 140)
    return L.seal(
        centre,
        "FILM SOCIETY",
        "EST · 1962",
        font="Cinzel",
        ring="#7f1d1d",
        ring_ink="#fef3c7",
        face="#fef3c7",
        edge="#2a0606",
    )


# ======================================================================= kids' films

KIDFILM = ("movies", "family", "kids")


@net("Storybook Cinema", MOVIES, *KIDFILM, "fairy tales")
def storybook_cinema():
    ink = "#3b0764"
    d = SH + _gold() + lin("sbk", [(0, "#7c3aed"), (1, "#4c1d95")])
    body = _sh(
        f'<rect x="80" y="40" width="352" height="432" rx="14" fill="url(#sbk)" stroke="{ink}" stroke-width="7"/>'
    )
    body += f'<rect x="80" y="40" width="30" height="432" fill="{ink}" opacity=".5"/>'
    body += '<rect x="132" y="66" width="276" height="380" rx="8" fill="none" stroke="url(#gld)" stroke-width="4"/>'
    for x, y, r in ((180, 120, 14), (340, 110, 18), (300, 170, 10), (200, 380, 12), (350, 400, 16)):
        body += _sparkle(x, y, r, "#fde68a")
    body += _sh(fit(_t("Storybook", "Lobster", "url(#gld)", stroke=ink, sw=6), 140, 190, 260, 100))
    body += fit(_t("CINEMA", "Cinzel", "#fef3c7", weight=700, ls=16), 170, 300, 200, 40)
    return svg(body, d)


@net("Cartoon Cinema", MOVIES, *KIDFILM, "cartoons")
def cartoon_cinema():
    ink = "#1e1b4b"
    d = SH
    body = _panel(36, 56, 440, 400, "#1e1b4b", rx=20, edge="#000", sw=5)
    body += '<rect x="66" y="86" width="380" height="220" rx="10" fill="#fef9c3"/>'
    cols = ("#ef4444", "#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ec4899", "#14b8a6")
    out, x = "", 0.0
    for i, (ch, c) in enumerate(zip("CARTOON", cols, strict=True)):
        adv, _ = measure(ch, "Luckiest Guy", 400)
        dy = -8 if i % 2 else 8
        out += f'<g transform="translate({x + adv / 2:.1f} {dy})">{_t(ch, "Luckiest Guy", c, stroke=ink, sw=10)}</g>'
        x += adv + 2
    body += fit(out, 86, 130, 340, 130)
    for i in range(6):
        body += f'<rect x="{70 + i * 64}" y="336" width="54" height="90" rx="16" fill="#dc2626" stroke="#000" stroke-width="4"/>'
    body += _sh(
        '<rect x="126" y="300" width="260" height="64" rx="8" fill="#facc15" stroke="#000" stroke-width="5"/>'
    )
    body += fit(_t("CINEMA", "Luckiest Guy", ink, ls=10), 146, 310, 220, 44)
    return svg(body, d)


@net("Family Feature", MOVIES, *KIDFILM)
def family_feature():
    ink = "#1c1917"
    d = SH + lin("beam2", [(0, "#fef9c3"), (1, "#fef9c3")])
    body = _panel(36, 56, 440, 400, "#1e293b", rx=24, edge="#000", sw=5)
    body += '<polygon points="110,120 476,150 476,430 110,170" fill="#fef9c3" opacity=".16"/>'
    body += f'<rect x="56" y="104" width="80" height="60" rx="8" fill="#475569" stroke="{ink}" stroke-width="5"/><circle cx="74" cy="92" r="20" fill="#64748b" stroke="{ink}" stroke-width="4"/><circle cx="116" cy="92" r="20" fill="#64748b" stroke="{ink}" stroke-width="4"/><rect x="132" y="122" width="22" height="24" rx="4" fill="#94a3b8" stroke="{ink}" stroke-width="4"/>'
    body += _sh(fit(_t("FAMILY", "Titan One", "#facc15", stroke=ink, sw=10), 176, 196, 280, 90))
    body += _sh(fit(_t("FEATURE", "Titan One", "#fff", stroke=ink, sw=10), 166, 296, 290, 80))
    return svg(body, d)


@net("Toon Theater", MOVIES, *KIDFILM, "cartoons")
def toon_theater():
    ink = "#1e1b4b"
    d = SH
    body = _sh(
        f'<rect x="40" y="200" width="432" height="260" rx="12" fill="#fef3c7" stroke="{ink}" stroke-width="7"/>'
    )
    cols = ("#ef4444", "#3b82f6", "#22c55e", "#f59e0b")
    for i, (ch, c) in enumerate(zip("TOON", cols, strict=True)):
        x = 56 + i * 102
        body += _sh(
            f'<rect x="{x}" y="50" width="94" height="130" rx="12" fill="{c}" stroke="{ink}" stroke-width="6" transform="rotate({(-4, 3, -3, 4)[i]} {x + 47} 115)"/>'
        )
        body += f'<g transform="rotate({(-4, 3, -3, 4)[i]} {x + 47} 115)">{fit(_t(ch, "Luckiest Guy", "#fff", stroke=ink, sw=8), x + 14, 66, 66, 98)}</g>'
    body += fit(_t("THEATER", "Luckiest Guy", ink, ls=10), 80, 226, 352, 80)
    body += f'<path d="M176 460 L176 360 Q256 300 336 360 L336 460 Z" fill="#dc2626" stroke="{ink}" stroke-width="6"/>'
    return svg(body, d)


@net("Popcorn Pals", MOVIES, *KIDFILM)
def popcorn_pals():
    ink = "#3b0a0a"
    pc = S.popcorn(P(a="#ef4444", b="#fff", c="#fde68a", k=ink, l="#fff7e0"))
    body = _sh(centred(pc, 186, 170, 230) + centred(pc, 336, 196, 180))
    body += _sh(banner(28, 484, 320, 96, "#2563eb", ink, 7, cut=24))
    body += fit(_t("POPCORN PALS", "Luckiest Guy", "#fff", ls=4), 76, 334, 360, 66)
    return svg(body, SH)


@net("Magic Lantern", MOVIES, *KIDFILM, "classic movies")
def magic_lantern_logo():
    ink = "#2e1065"
    d = SH + _gold()
    body = _panel(36, 56, 440, 400, "#1e1033", rx=24, edge="#000", sw=5)
    body += '<polygon points="200,180 476,120 476,330 200,240" fill="#fde68a" opacity=".2"/>'
    ml = magic_lantern(P(a="#b45309", b="#fde68a", c="#fef3c7", k=ink, l="#f59e0b"))
    body += _sh(centred(ml, 140, 210, 190))
    for x, y in ((320, 170), (400, 210), (360, 260)):
        body += _sparkle(x, y, 14, "#fde68a")
    body += _sh(
        fit(_t("Magic Lantern", "Lobster", "url(#gld)", stroke=ink, sw=6), 56, 330, 400, 100)
    )
    return svg(body, d)


# ======================================================================= musicals

MUSICAL = ("movies", "musicals", "music")


@net("Show Tunes", MOVIES, *MUSICAL)
def show_tunes():
    ink = "#0a0a0a"
    d = SH + _gold()
    body = _panel(36, 70, 440, 372, "#1c0a12", rx=20, edge="#000", sw=5)
    body += f'<rect x="56" y="320" width="400" height="100" fill="#fafaf9" stroke="{ink}" stroke-width="4"/>'
    for i in range(1, 14):
        body += f'<line x1="{56 + i * 30.8:.0f}" y1="320" x2="{56 + i * 30.8:.0f}" y2="420" stroke="{ink}" stroke-width="2"/>'
    for i in (0, 1, 3, 4, 5, 7, 8, 10, 11, 12):
        body += f'<rect x="{56 + i * 30.8 + 20:.0f}" y="320" width="20" height="60" fill="{ink}"/>'
    body += _sh(fit(_t("Show Tunes", "Great Vibes", "url(#gld)"), 66, 110, 380, 160))
    body += '<path d="M110 120 l0 -40 l30 -8 l0 40" fill="none" stroke="#e2b13c" stroke-width="5"/><circle cx="104" cy="122" r="9" fill="#e2b13c"/><circle cx="134" cy="114" r="9" fill="#e2b13c"/>'
    return svg(body, d)


@net("Song & Dance", MOVIES, *MUSICAL)
def song_and_dance():
    d = SH + _gold()
    body = '<defs><clipPath id="sdc"><rect x="36" y="56" width="440" height="400" rx="20"/></clipPath></defs>'
    body += _panel(36, 56, 440, 400, "#120a24", rx=20, edge="#000", sw=5)
    body += '<g clip-path="url(#sdc)"><polygon points="36,56 100,56 330,456 200,456" fill="#fef9c3" opacity=".14"/><polygon points="476,56 412,56 182,456 312,456" fill="#fef9c3" opacity=".14"/>'
    body += '<ellipse cx="256" cy="440" rx="150" ry="30" fill="#fef9c3" opacity=".25"/></g>'
    body += _sh(fit(_t("SONG", "Abril Fatface", "url(#gld)", ls=8), 106, 110, 300, 100))
    body += fit(_t("&", "Great Vibes", "#f472b6"), 226, 210, 60, 70)
    body += _sh(fit(_t("DANCE", "Abril Fatface", "#fef3c7", ls=8), 96, 286, 320, 100))
    return svg(body, d)


@net("Tap Shoes", MOVIES, *MUSICAL, "dance")
def tap_shoes_logo():
    ink = "#0a0a0a"
    d = SH + rad("tspot", [(0, "#fdf2f8"), (0.7, "#f9a8d4"), (1, "#db2777")])
    shoes = tap_shoes(P(a="#b91c1c", b="#d1d5db", c="#f3f4f6", k=ink, l="#fff"))
    body = _sh(
        f'<ellipse cx="256" cy="170" rx="190" ry="140" fill="url(#tspot)" stroke="{ink}" stroke-width="6"/>'
    )
    body += _sh(fit(shoes, 136, 60, 240, 210))
    body += _sh(
        fit(_t("TAP SHOES", "Abril Fatface", "#fef3c7", stroke=ink, sw=12), 36, 320, 440, 100)
    )
    body += fit(
        _t("DANCE MUSICALS", "Oswald", "#f472b6", weight=600, stroke=ink, sw=6, ls=6, size=40),
        136,
        430,
        240,
        30,
    )
    return svg(body, d)


@net("Jukebox Musical", MOVIES, *MUSICAL, "pop music")
def jukebox_musical():
    d = SH
    cols = ("#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7")
    for i, c in enumerate(cols):
        d += glow(f"jb{i}", c, blur=5, strength=2)
    body = _panel(56, 56, 400, 410, "#0c0a12", rx=200, edge="#000", sw=6)
    for i, c in enumerate(cols):
        r = 176 - i * 14
        body += f'<g filter="url(#jb{i})"><path d="M{256 - r} 400 L{256 - r} 256 A{r} {r} 0 0 1 {256 + r} 256 L{256 + r} 400" fill="none" stroke="{c}" stroke-width="7"/></g>'
    body += _sh(fit(_t("JUKEBOX", "Bungee", "#fff", stroke="#0c0a12", sw=6), 136, 220, 240, 70))
    body += fit(_t("Musical", "Yellowtail", "#f472b6", stroke="#0c0a12", sw=6), 156, 290, 200, 80)
    return svg(body, d)


def logos() -> list[Logo]:
    return [Logo(cid, name, cat, fn, tags) for cid, name, cat, tags, fn in CHANNELS]
