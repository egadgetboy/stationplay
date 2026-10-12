"""Pictures used in the logos, each drawn in a 200x200 box (its middle at
100,100) from a palette: a (main), b (second), c (accent), k (dark
outline) and l (light). Place one with kit.at(symbol, x, y, scale)."""

from __future__ import annotations

import math
import random

from kit import pts, star


class P:
    def __init__(self, a="#e84a3c", b="#f4b73a", c="#3aa0e8", k="#1c1a2b", l="#fff6e6"):
        self.a, self.b, self.c, self.k, self.l = a, b, c, k, l


def _o(p, w=6):
    return f'stroke="{p.k}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"'


def centred(inner: str, cx: float, cy: float, size: float) -> str:
    """A symbol (200 box) drawn `size` wide with its middle at cx,cy."""
    s = size / 200
    return f'<g transform="translate({cx - 100 * s:.2f} {cy - 100 * s:.2f}) scale({s:.4f})">{inner}</g>'


# ---------------------------------------------------------------- adventure, travel


def compass(p: P) -> str:
    o = _o(p, 5)
    s = f'<circle cx="100" cy="100" r="92" fill="{p.l}" {o}/>'
    s += f'<circle cx="100" cy="100" r="78" fill="none" stroke="{p.k}" stroke-width="2.5"/>'
    for k in range(32):
        a = math.radians(k * 360 / 32)
        r1 = 70 if k % 4 else 64
        s += f'<line x1="{100 + r1 * math.cos(a):.1f}" y1="{100 + r1 * math.sin(a):.1f}" x2="{100 + 78 * math.cos(a):.1f}" y2="{100 + 78 * math.sin(a):.1f}" stroke="{p.k}" stroke-width="2"/>'
    # diagonal points
    for k in range(4):
        a = math.radians(45 + k * 90)
        tip = (100 + 52 * math.cos(a), 100 + 52 * math.sin(a))
        l1 = (100 + 12 * math.cos(a - math.pi / 2), 100 + 12 * math.sin(a - math.pi / 2))
        l2 = (100 + 12 * math.cos(a + math.pi / 2), 100 + 12 * math.sin(a + math.pi / 2))
        s += f'<polygon points="{pts([tip, l1, (100, 100)])}" fill="{p.b}" {_o(p, 3)}/>'
        s += f'<polygon points="{pts([tip, l2, (100, 100)])}" fill="{p.k}" {_o(p, 3)}/>'
    for k in range(4):
        a = math.radians(-90 + k * 90)
        tip = (100 + 86 * math.cos(a), 100 + 86 * math.sin(a))
        l1 = (100 + 16 * math.cos(a - math.pi / 2), 100 + 16 * math.sin(a - math.pi / 2))
        l2 = (100 + 16 * math.cos(a + math.pi / 2), 100 + 16 * math.sin(a + math.pi / 2))
        s += f'<polygon points="{pts([tip, l1, (100, 100)])}" fill="{p.a}" {_o(p, 3)}/>'
        s += f'<polygon points="{pts([tip, l2, (100, 100)])}" fill="{p.l}" {_o(p, 3)}/>'
    s += f'<circle cx="100" cy="100" r="8" fill="{p.b}" {_o(p, 3)}/>'
    return s


def mountains(p: P) -> str:
    s = f'<circle cx="128" cy="70" r="34" fill="{p.b}"/>'
    s += f'<polygon points="4,176 78,52 152,176" fill="{p.a}" {_o(p)}/>'
    s += f'<polygon points="78,52 98,86 86,80 76,96 64,80 58,86" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<polygon points="92,176 146,92 196,176" fill="{p.c}" {_o(p)}/>'
    s += f'<polygon points="146,92 162,118 152,114 144,126 136,114 131,118" fill="{p.l}" {_o(p, 4)}/>'
    return s


def airplane(p: P) -> str:
    body = "M100 14 C110 14 114 30 114 44 L114 82 L186 118 L186 136 L114 118 L112 160 L136 176 L136 188 L100 180 L64 188 L64 176 L88 160 L86 118 L14 136 L14 118 L86 82 L86 44 C86 30 90 14 100 14 Z"
    return (
        f'<path d="{body}" fill="{p.l}" {_o(p)}/>'
        f'<path d="M92 40 Q100 30 108 40 L108 52 L92 52 Z" fill="{p.c}"/>'
        f'<path d="M114 96 L186 128 L186 136 L114 118 Z" fill="{p.a}" opacity=".9"/>'
        f'<path d="M86 96 L14 128 L14 136 L86 118 Z" fill="{p.a}" opacity=".9"/>'
    )


def globe(p: P, lines: str | None = None) -> str:
    ln = lines or p.l
    s = f'<circle cx="100" cy="100" r="88" fill="{p.a}" {_o(p)}/>'
    s += f'<g fill="none" stroke="{ln}" stroke-width="5">'
    for rx in (30, 62):
        s += f'<ellipse cx="100" cy="100" rx="{rx}" ry="86"/>'
    s += '<line x1="100" y1="12" x2="100" y2="188"/>'
    for y, w in ((52, 72), (100, 88), (148, 72)):
        s += f'<line x1="{100 - w}" y1="{y}" x2="{100 + w}" y2="{y}"/>'
    s += "</g>"
    return s


def suitcase(p: P) -> str:
    s = f'<path d="M72 44 Q72 30 86 30 L114 30 Q128 30 128 44 L128 56 L116 56 L116 44 L84 44 L84 56 L72 56 Z" fill="{p.k}"/>'
    s += f'<rect x="20" y="54" width="160" height="120" rx="16" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="44" y="54" width="14" height="120" fill="{p.b}"/><rect x="142" y="54" width="14" height="120" fill="{p.b}"/>'
    s += f'<rect x="20" y="54" width="160" height="120" rx="16" fill="none" {_o(p)}/>'
    s += f'<circle cx="92" cy="104" r="17" fill="{p.l}" {_o(p, 3)}/><rect x="104" y="116" width="30" height="20" rx="3" fill="{p.c}" {_o(p, 3)} transform="rotate(-10 119 126)"/>'
    return s


# ---------------------------------------------------------------- film, TV, stage


def clapper(p: P) -> str:
    s = f'<rect x="24" y="78" width="152" height="100" rx="8" fill="{p.k}"/>'
    s += f'<rect x="34" y="96" width="132" height="4" fill="{p.l}" opacity=".85"/><rect x="34" y="124" width="132" height="4" fill="{p.l}" opacity=".85"/><rect x="34" y="152" width="132" height="4" fill="{p.l}" opacity=".85"/>'
    s += f'<rect x="24" y="56" width="152" height="24" rx="4" fill="{p.l}" {_o(p, 5)}/>'
    for x in range(34, 176, 32):
        s += f'<polygon points="{x},56 {x + 16},56 {x + 4},80 {x - 12},80" fill="{p.k}"/>'
    s += f'<g transform="rotate(-18 28 52)"><rect x="24" y="30" width="152" height="24" rx="4" fill="{p.l}" {_o(p, 5)}/>'
    for x in range(34, 176, 32):
        s += f'<polygon points="{x},30 {x + 16},30 {x + 4},54 {x - 12},54" fill="{p.k}"/>'
    s += "</g>"
    s += f'<circle cx="30" cy="54" r="7" fill="{p.b}" {_o(p, 3)}/>'
    return s


def reel(p: P) -> str:
    s = f'<circle cx="100" cy="100" r="88" fill="{p.a}" {_o(p)}/>'
    s += f'<circle cx="100" cy="100" r="70" fill="none" stroke="{p.k}" stroke-width="3" opacity=".6"/>'
    for k in range(5):
        a = math.radians(-90 + k * 72)
        s += f'<circle cx="{100 + 44 * math.cos(a):.1f}" cy="{100 + 44 * math.sin(a):.1f}" r="21" fill="{p.k}"/>'
    s += f'<circle cx="100" cy="100" r="14" fill="{p.l}" {_o(p, 4)}/>'
    return s


def movie_camera(p: P) -> str:
    s = ""
    for cx, r in ((66, 36), (130, 30)):
        s += f'<circle cx="{cx}" cy="{64 - (r - 30)}" r="{r}" fill="{p.a}" {_o(p)}/>'
        for k in range(3):
            a = math.radians(-90 + k * 120)
            s += f'<circle cx="{cx + r * 0.5 * math.cos(a):.1f}" cy="{64 - (r - 30) + r * 0.5 * math.sin(a):.1f}" r="{r * 0.22:.1f}" fill="{p.k}"/>'
    s += f'<rect x="28" y="96" width="120" height="70" rx="10" fill="{p.k}"/>'
    s += f'<rect x="40" y="108" width="60" height="10" rx="3" fill="{p.l}" opacity=".7"/>'
    s += f'<polygon points="148,112 190,94 190,168 148,150" fill="{p.b}" {_o(p)}/>'
    s += f'<rect x="60" y="166" width="16" height="22" fill="{p.k}"/><rect x="40" y="184" width="56" height="8" rx="3" fill="{p.k}"/>'
    return s


def aperture(p: P) -> str:
    """A camera iris: six blades around a hexagonal opening."""
    s = f'<circle cx="100" cy="100" r="90" fill="{p.k}"/><circle cx="100" cy="100" r="80" fill="{p.a}"/>'
    hexr = 30
    for k in range(6):
        a0 = math.radians(k * 60 - 90)
        a1 = math.radians(k * 60 - 30)
        v0 = (100 + hexr * math.cos(a0), 100 + hexr * math.sin(a0))
        v1 = (100 + hexr * math.cos(a1), 100 + hexr * math.sin(a1))
        # the blade runs from its edge of the opening out to the rim
        far0 = (100 + 80 * math.cos(a0 - 0.95), 100 + 80 * math.sin(a0 - 0.95))
        far1 = (100 + 80 * math.cos(a1 - 0.95), 100 + 80 * math.sin(a1 - 0.95))
        shade = p.b if k % 2 else p.a
        s += f'<path d="M{v0[0]:.1f} {v0[1]:.1f} L{v1[0]:.1f} {v1[1]:.1f} L{far1[0]:.1f} {far1[1]:.1f} A80 80 0 0 0 {far0[0]:.1f} {far0[1]:.1f} Z" fill="{shade}" stroke="{p.k}" stroke-width="4" stroke-linejoin="round"/>'
    s += f'<polygon points="{" ".join(f"{100 + hexr * math.cos(math.radians(k * 60 - 90)):.1f},{100 + hexr * math.sin(math.radians(k * 60 - 90)):.1f}" for k in range(6))}" fill="{p.k}"/>'
    s += f'<circle cx="100" cy="100" r="86" fill="none" stroke="{p.k}" stroke-width="10"/>'
    s += f'<path d="M86 78 Q92 72 100 72" fill="none" stroke="{p.l}" stroke-width="5" stroke-linecap="round" opacity=".6"/>'
    return s


def masks(p: P) -> str:
    face = "M-44 -52 Q0 -70 44 -52 Q54 8 0 64 Q-54 8 -44 -52 Z"
    happy = (
        f'<path d="{face}" fill="{p.b}" {_o(p)}/>'
        f'<path d="M-30 -22 Q-20 -34 -8 -22 Q-20 -16 -30 -22 Z" fill="{p.k}"/><path d="M30 -22 Q20 -34 8 -22 Q20 -16 30 -22 Z" fill="{p.k}"/>'
        f'<path d="M-26 10 Q0 44 26 10 Q0 22 -26 10 Z" fill="{p.k}"/>'
        f'<path d="M-36 -40 Q-22 -48 -8 -40" fill="none" stroke="{p.k}" stroke-width="4"/><path d="M36 -40 Q22 -48 8 -40" fill="none" stroke="{p.k}" stroke-width="4"/>'
    )
    sad = (
        f'<path d="{face}" fill="{p.a}" {_o(p)}/>'
        f'<path d="M-30 -18 Q-20 -30 -8 -18 Q-20 -12 -30 -18 Z" fill="{p.k}"/><path d="M30 -18 Q20 -30 8 -18 Q20 -12 30 -18 Z" fill="{p.k}"/>'
        f'<path d="M-24 32 Q0 6 24 32 Q0 22 -24 32 Z" fill="{p.k}"/>'
        f'<path d="M-34 -32 Q-22 -40 -10 -34" fill="none" stroke="{p.k}" stroke-width="4"/><path d="M34 -32 Q22 -40 10 -34" fill="none" stroke="{p.k}" stroke-width="4"/>'
    )
    return (
        f'<g transform="translate(130 108) rotate(14)">{sad}</g>'
        f'<g transform="translate(70 96) rotate(-12)">{happy}</g>'
    )


def spotlight(p: P) -> str:
    s = f'<polygon points="70,40 130,40 190,196 10,196" fill="{p.b}" opacity=".35"/>'
    s += f'<ellipse cx="100" cy="186" rx="90" ry="12" fill="{p.b}" opacity=".55"/>'
    s += f'<rect x="66" y="10" width="68" height="40" rx="10" fill="{p.k}"/>'
    s += f'<ellipse cx="100" cy="50" rx="34" ry="9" fill="{p.l}"/>'
    return s


def tophat(p: P) -> str:
    s = f'<line x1="150" y1="40" x2="176" y2="190" stroke="{p.k}" stroke-width="9" stroke-linecap="round"/>'
    s += f'<circle cx="150" cy="38" r="9" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<path d="M52 36 L136 36 L128 136 L60 136 Z" fill="{p.k}"/>'
    s += f'<rect x="58" y="108" width="72" height="18" fill="{p.a}"/>'
    s += f'<ellipse cx="94" cy="140" rx="74" ry="16" fill="{p.k}"/>'
    s += f'<path d="M66 44 L74 44 L70 100 L64 100 Z" fill="{p.l}" opacity=".25"/>'
    return s


def piano(p: P) -> str:
    s = f'<rect x="8" y="50" width="184" height="104" rx="6" fill="{p.l}" {_o(p)}/>'
    for i in range(1, 8):
        x = 8 + i * 23
        s += f'<line x1="{x}" y1="50" x2="{x}" y2="154" stroke="{p.k}" stroke-width="3"/>'
    for i in (1, 2, 4, 5, 6):
        x = 8 + i * 23 - 7
        s += f'<rect x="{x}" y="50" width="14" height="62" rx="2" fill="{p.k}"/>'
    return s


def ticket(p: P) -> str:
    d = "M20 50 L180 50 L180 80 A20 20 0 0 0 180 120 L180 150 L20 150 L20 120 A20 20 0 0 0 20 80 Z"
    s = f'<path d="{d}" fill="{p.a}" {_o(p)} transform="rotate(-10 100 100)"/>'
    s += f'<g transform="rotate(-10 100 100)"><line x1="132" y1="56" x2="132" y2="144" stroke="{p.l}" stroke-width="4" stroke-dasharray="7 6"/>'
    s += f'<rect x="40" y="70" width="80" height="60" rx="4" fill="none" stroke="{p.l}" stroke-width="4"/>'
    s += f'<polygon points="{star(80, 100, 20, 8)}" fill="{p.l}"/></g>'
    return s


def popcorn(p: P) -> str:
    s = ""
    for cx, cy, r in (
        (56, 62, 24),
        (84, 44, 26),
        (116, 44, 26),
        (144, 62, 24),
        (70, 78, 22),
        (100, 66, 24),
        (130, 78, 22),
    ):
        s += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{p.l}" {_o(p, 5)}/>'
    s += f'<path d="M36 80 L164 80 L148 190 L52 190 Z" fill="{p.l}" {_o(p)}/>'
    for x0, x1 in ((52, 62), (84, 90), (116, 110), (148, 138)):
        s += f'<path d="M{x0 - 8} 80 L{x0 + 8} 80 L{x1 + 6} 190 L{x1 - 8} 190 Z" fill="{p.a}"/>'
    s += f'<path d="M36 80 L164 80 L148 190 L52 190 Z" fill="none" {_o(p)}/>'
    return s


def film_strip(p: P) -> str:
    s = f'<rect x="10" y="50" width="180" height="100" rx="6" fill="{p.k}"/>'
    for x in range(18, 190, 22):
        s += f'<rect x="{x}" y="58" width="12" height="10" rx="2" fill="{p.l}"/><rect x="{x}" y="132" width="12" height="10" rx="2" fill="{p.l}"/>'
    for i in range(3):
        s += f'<rect x="{22 + i * 54}" y="76" width="48" height="48" rx="3" fill="{(p.a, p.b, p.c)[i]}"/>'
    return s


def tv_set(p: P) -> str:
    s = f'<line x1="80" y1="40" x2="56" y2="8" stroke="{p.k}" stroke-width="6" stroke-linecap="round"/><line x1="120" y1="40" x2="146" y2="10" stroke="{p.k}" stroke-width="6" stroke-linecap="round"/>'
    s += f'<rect x="14" y="40" width="172" height="132" rx="22" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="30" y="56" width="116" height="100" rx="16" fill="{p.c}" {_o(p, 5)}/>'
    s += f'<path d="M40 70 Q60 62 76 66" fill="none" stroke="{p.l}" stroke-width="6" stroke-linecap="round" opacity=".7"/>'
    s += f'<circle cx="166" cy="78" r="9" fill="{p.l}" {_o(p, 3)}/><circle cx="166" cy="106" r="9" fill="{p.l}" {_o(p, 3)}/>'
    s += f'<rect x="156" y="126" width="20" height="4" fill="{p.k}"/><rect x="156" y="136" width="20" height="4" fill="{p.k}"/>'
    s += f'<rect x="40" y="172" width="14" height="18" fill="{p.k}"/><rect x="146" y="172" width="14" height="18" fill="{p.k}"/>'
    return s


def mic(p: P) -> str:
    s = f'<rect x="92" y="130" width="16" height="48" fill="{p.k}"/><rect x="58" y="176" width="84" height="12" rx="6" fill="{p.k}"/>'
    s += f'<path d="M62 94 Q62 140 100 140 Q138 140 138 94" fill="none" stroke="{p.k}" stroke-width="9"/>'
    s += f'<rect x="70" y="14" width="60" height="112" rx="30" fill="{p.l}" {_o(p)}/>'
    for y in range(34, 116, 14):
        s += f'<line x1="74" y1="{y}" x2="126" y2="{y}" stroke="{p.k}" stroke-width="3" opacity=".7"/>'
    s += f'<rect x="70" y="66" width="60" height="16" fill="{p.a}" {_o(p, 4)}/>'
    return s


def mic_vintage(p: P) -> str:
    s = f'<rect x="94" y="150" width="12" height="36" fill="{p.k}"/><rect x="54" y="182" width="92" height="12" rx="6" fill="{p.k}"/>'
    s += f'<path d="M58 84 L58 118 Q58 152 100 152 Q142 152 142 118 L142 84" fill="none" stroke="{p.k}" stroke-width="10"/>'
    s += f'<rect x="64" y="10" width="72" height="132" rx="36" fill="{p.a}" {_o(p)}/>'
    for x in range(78, 124, 11):
        s += f'<line x1="{x}" y1="22" x2="{x}" y2="130" stroke="{p.k}" stroke-width="3.5" opacity=".75"/>'
    s += f'<rect x="64" y="70" width="72" height="14" fill="{p.l}" {_o(p, 4)}/>'
    return s


def camcorder(p: P) -> str:
    s = f'<rect x="20" y="60" width="120" height="84" rx="12" fill="{p.k}"/>'
    s += f'<polygon points="140,82 186,60 186,144 140,122" fill="{p.k}"/>'
    s += f'<circle cx="48" cy="44" r="10" fill="{p.a}"/>'
    s += f'<rect x="34" y="76" width="70" height="52" rx="6" fill="{p.c}"/>'
    s += f'<circle cx="52" cy="96" r="8" fill="{p.a}"/>'
    return s


# ---------------------------------------------------------------- hearts, home, family


def heart(p: P, fill: str | None = None) -> str:
    d = "M100 180 C40 136 8 104 8 64 C8 34 30 14 58 14 C78 14 92 26 100 42 C108 26 122 14 142 14 C170 14 192 34 192 64 C192 104 160 136 100 180 Z"
    return f'<path d="{d}" fill="{fill or p.a}" {_o(p)}/><path d="M36 50 Q42 30 62 28" fill="none" stroke="{p.l}" stroke-width="8" stroke-linecap="round" opacity=".6"/>'


def house(p: P) -> str:
    s = f'<rect x="138" y="30" width="22" height="46" fill="{p.b}" {_o(p, 5)}/>'
    s += f'<polygon points="100,16 190,92 10,92" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="32" y="88" width="136" height="96" fill="{p.l}" {_o(p)}/>'
    s += f'<rect x="84" y="124" width="34" height="60" rx="3" fill="{p.b}" {_o(p, 5)}/>'
    s += f'<g transform="translate(46 104) scale(.15)">{heart(p, p.a)}</g>'
    s += f'<g transform="translate(124 104) scale(.15)">{heart(p, p.a)}</g>'
    return s


def family(p: P) -> str:
    s = ""
    for x, h, c in ((40, 120, p.a), (84, 132, p.c), (124, 90, p.b), (160, 78, p.a)):
        top = 190 - h
        r = h * 0.14
        s += f'<circle cx="{x}" cy="{top + r}" r="{r}" fill="{c}" {_o(p, 5)}/>'
        s += f'<path d="M{x - r * 1.35} 190 L{x - r * 1.35} {top + r * 3.6} Q{x - r * 1.35} {top + r * 2.4} {x} {top + r * 2.4} Q{x + r * 1.35} {top + r * 2.4} {x + r * 1.35} {top + r * 3.6} L{x + r * 1.35} 190 Z" fill="{c}" {_o(p, 5)}/>'
    return s


def sofa(p: P) -> str:
    s = f'<rect x="30" y="60" width="140" height="70" rx="18" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="10" y="100" width="40" height="70" rx="14" fill="{p.a}" {_o(p)}/><rect x="150" y="100" width="40" height="70" rx="14" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="44" y="118" width="112" height="44" rx="10" fill="{p.b}" {_o(p)}/>'
    s += f'<rect x="20" y="168" width="10" height="16" fill="{p.k}"/><rect x="170" y="168" width="10" height="16" fill="{p.k}"/>'
    return s


def blocks(p: P) -> str:
    s = ""
    for x, y, r, c, ch in (
        (14, 104, -6, p.a, "A"),
        (100, 108, 5, p.c, "B"),
        (58, 26, -3, p.b, "C"),
    ):
        s += (
            f'<g transform="rotate({r} {x + 42} {y + 42})"><rect x="{x}" y="{y}" width="84" height="84" rx="10" fill="{c}" {_o(p)}/>'
            f'<rect x="{x + 10}" y="{y + 10}" width="64" height="64" rx="6" fill="none" stroke="{p.l}" stroke-width="4" opacity=".8"/>'
            f'<text x="{x + 42}" y="{y + 64}" font-family="Titan One" font-size="56" text-anchor="middle" fill="{p.l}" stroke="{p.k}" stroke-width="5" paint-order="stroke">{ch}</text></g>'
        )
    return s


def kite(p: P) -> str:
    s = f'<path d="M100 150 Q80 170 100 180 Q120 190 100 198" fill="none" stroke="{p.k}" stroke-width="4"/>'
    for y, c in ((166, p.a), (182, p.b)):
        s += f'<path d="M100 {y} l-12 -8 l0 16 Z M100 {y} l12 -8 l0 16 Z" fill="{c}"/>'
    s += f'<polygon points="100,8 164,70 100,150 36,70" fill="{p.a}" {_o(p)}/>'
    s += f'<polygon points="100,8 164,70 100,70" fill="{p.b}"/><polygon points="100,70 36,70 100,150" fill="{p.c}"/>'
    s += f'<polygon points="100,8 164,70 100,150 36,70" fill="none" {_o(p)}/>'
    s += f'<line x1="100" y1="8" x2="100" y2="150" stroke="{p.k}" stroke-width="4"/><line x1="36" y1="70" x2="164" y2="70" stroke="{p.k}" stroke-width="4"/>'
    return s


def rainbow(p: P) -> str:
    cols = ["#ef4a3c", "#f59a2f", "#f7d23a", "#4cc26a", "#3a8fe0", "#7a55d6"]
    s = ""
    for i, c in enumerate(cols):
        r = 92 - i * 12
        s += f'<path d="M{100 - r} 150 A{r} {r} 0 0 1 {100 + r} 150" fill="none" stroke="{c}" stroke-width="12"/>'
    for cx, cy, sc in ((34, 150, 1), (166, 150, 1)):
        s += f'<g fill="{p.l}" {_o(p, 4)}><circle cx="{cx - 18}" cy="{cy}" r="16"/><circle cx="{cx + 16}" cy="{cy}" r="16"/><circle cx="{cx}" cy="{cy - 12}" r="20"/></g>'
        s += f'<rect x="{cx - 30}" y="{cy}" width="60" height="14" fill="{p.l}"/>'
    return s


def sun(p: P, rays: int = 12) -> str:
    s = ""
    for k in range(rays):
        a = math.radians(k * 360 / rays)
        s += f'<line x1="{100 + 62 * math.cos(a):.1f}" y1="{100 + 62 * math.sin(a):.1f}" x2="{100 + 90 * math.cos(a):.1f}" y2="{100 + 90 * math.sin(a):.1f}" stroke="{p.b}" stroke-width="12" stroke-linecap="round"/>'
    s += f'<circle cx="100" cy="100" r="50" fill="{p.b}" {_o(p)}/>'
    return s


# ---------------------------------------------------------------- fantasy, spooky


def castle(p: P) -> str:
    s = f'<circle cx="150" cy="44" r="26" fill="{p.l}" opacity=".95"/>'
    wall = p.a

    def tower(x, w, top, h):
        t = f'<rect x="{x}" y="{top}" width="{w}" height="{h}" fill="{wall}" {_o(p, 5)}/>'
        for i in range(3):
            t += f'<rect x="{x + i * w / 3 + 1}" y="{top - 12}" width="{w / 3 - 5}" height="14" fill="{wall}" {_o(p, 4)}/>'
        return t

    s += f'<line x1="58" y1="44" x2="58" y2="14" stroke="{p.k}" stroke-width="4"/><path d="M58 14 L82 20 L58 28 Z" fill="{p.b}" {_o(p, 3)}/>'
    s += tower(38, 40, 56, 132)
    s += f'<line x1="142" y1="60" x2="142" y2="28" stroke="{p.k}" stroke-width="4"/><path d="M142 28 L166 34 L142 42 Z" fill="{p.b}" {_o(p, 3)}/>'
    s += tower(122, 40, 70, 118)
    s += f'<rect x="72" y="98" width="56" height="90" fill="{wall}" {_o(p, 5)}/>'
    for i in range(4):
        s += f'<rect x="{73 + i * 14}" y="88" width="9" height="12" fill="{wall}" {_o(p, 4)}/>'
    s += f'<path d="M86 188 L86 150 Q100 132 114 150 L114 188 Z" fill="{p.k}"/>'
    s += f'<rect x="52" y="90" width="12" height="20" rx="6" fill="{p.k}"/><rect x="136" y="100" width="12" height="20" rx="6" fill="{p.k}"/>'
    return s


def wizard_hat(p: P) -> str:
    s = f'<ellipse cx="100" cy="166" rx="88" ry="20" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M40 164 Q64 110 84 60 Q98 22 142 10 Q116 34 118 64 Q130 120 160 164 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M50 150 Q100 136 152 150 L156 160 Q100 150 46 162 Z" fill="{p.b}"/>'
    for x, y, r in ((96, 104, 12), (122, 132, 8), (104, 64, 7), (70, 138, 7)):
        s += f'<polygon points="{star(x, y, r, r * 0.45)}" fill="{p.b}"/>'
    return s


def gem(p: P) -> str:
    s = f'<polygon points="40,64 72,30 128,30 160,64 100,176" fill="{p.a}" {_o(p)}/>'
    s += f'<polygon points="40,64 160,64 100,176" fill="{p.c}" opacity=".85"/>'
    s += f'<polygon points="72,30 100,64 128,30" fill="{p.l}" opacity=".7"/>'
    s += f'<polygon points="72,64 100,176 128,64" fill="{p.l}" opacity=".25"/>'
    s += f'<polyline points="40,64 160,64" fill="none" stroke="{p.k}" stroke-width="4"/><polyline points="72,30 100,64 128,30" fill="none" stroke="{p.k}" stroke-width="4"/><polyline points="72,64 100,176 128,64" fill="none" stroke="{p.k}" stroke-width="3"/>'
    s += f'<polygon points="40,64 72,30 128,30 160,64 100,176" fill="none" {_o(p)}/>'
    return s


def sword(p: P) -> str:
    s = f'<polygon points="100,6 112,24 112,138 88,138 88,24" fill="{p.l}" {_o(p, 5)}/>'
    s += f'<line x1="100" y1="24" x2="100" y2="134" stroke="{p.k}" stroke-width="3" opacity=".4"/>'
    s += f'<rect x="54" y="136" width="92" height="14" rx="7" fill="{p.b}" {_o(p, 5)}/>'
    s += f'<rect x="92" y="150" width="16" height="30" fill="{p.a}" {_o(p, 5)}/>'
    s += f'<circle cx="100" cy="186" r="10" fill="{p.b}" {_o(p, 5)}/>'
    return s


def moon_tree(p: P) -> str:
    s = f'<circle cx="112" cy="84" r="70" fill="{p.l}"/>'
    s += f'<circle cx="140" cy="60" r="10" fill="{p.b}" opacity=".35"/><circle cx="100" cy="110" r="14" fill="{p.b}" opacity=".3"/>'
    s += (
        f'<path d="M20 196 L32 150 Q36 120 26 96 Q40 112 44 130 Q56 104 50 72 Q64 96 60 128 Q76 110 96 104 Q76 124 64 146 L70 196 Z" fill="{p.k}"/>'
        f'<path d="M50 72 Q46 56 36 48 M50 90 Q66 72 74 70 M26 96 Q16 86 8 88" fill="none" stroke="{p.k}" stroke-width="5" stroke-linecap="round"/>'
    )
    s += f'<rect x="0" y="184" width="200" height="16" fill="{p.k}"/>'
    s += f'<g transform="translate(150 140) scale(.22)">{bat(p)}</g><g transform="translate(118 30) scale(.16)">{bat(p)}</g>'
    return s


def bat(p: P) -> str:
    d = (
        "M100 70 Q92 58 92 48 L100 58 L108 48 Q108 58 100 70 Z "
        "M100 66 Q70 40 20 48 Q36 60 30 80 Q48 70 58 84 Q66 70 80 82 Q86 70 100 90 Q114 70 120 82 Q134 70 142 84 Q152 70 170 80 Q164 60 180 48 Q130 40 100 66 Z"
    )
    return f'<path d="{d}" fill="{p.k}"/>'


def tombstone(p: P) -> str:
    s = f'<path d="M44 176 L44 70 Q44 20 100 20 Q156 20 156 70 L156 176 Z" fill="{p.l}" {_o(p)}/>'
    s += f'<text x="100" y="98" font-family="Cinzel" font-weight="700" font-size="40" text-anchor="middle" fill="{p.k}">RIP</text>'
    s += f'<line x1="68" y1="118" x2="132" y2="118" stroke="{p.k}" stroke-width="4"/><line x1="76" y1="134" x2="124" y2="134" stroke="{p.k}" stroke-width="4"/>'
    s += f'<path d="M4 190 Q30 168 56 180 Q80 164 100 178 Q128 162 150 178 Q174 166 196 190 Z" fill="{p.a}" {_o(p, 5)}/>'
    return s


def pumpkin(p: P) -> str:
    s = '<path d="M100 40 Q96 22 108 12" fill="none" stroke="#3e6b25" stroke-width="10" stroke-linecap="round"/>'
    for cx, rx in ((58, 46), (142, 46), (100, 50)):
        s += f'<ellipse cx="{cx}" cy="112" rx="{rx}" ry="72" fill="{p.a}" {_o(p)}/>'
    s += f'<polygon points="64,96 86,96 76,76" fill="{p.k}"/><polygon points="114,96 136,96 124,76" fill="{p.k}"/>'
    s += f'<path d="M56 128 L72 140 L84 128 L100 142 L116 128 L128 140 L144 128 Q134 164 100 166 Q66 164 56 128 Z" fill="{p.k}"/>'
    return s


def ghost(p: P) -> str:
    d = "M40 186 L40 88 Q40 22 100 22 Q160 22 160 88 L160 186 L140 170 L120 186 L100 170 L80 186 L60 170 Z"
    return (
        f'<path d="{d}" fill="{p.l}" {_o(p)}/><ellipse cx="80" cy="90" rx="10" ry="16" fill="{p.k}"/>'
        f'<ellipse cx="120" cy="90" rx="10" ry="16" fill="{p.k}"/><ellipse cx="100" cy="130" rx="14" ry="18" fill="{p.k}"/>'
    )


# ---------------------------------------------------------------- mystery, crime


def magnifier(p: P) -> str:
    s = f'<line x1="130" y1="130" x2="184" y2="184" stroke="{p.k}" stroke-width="30" stroke-linecap="round"/>'
    s += f'<line x1="134" y1="134" x2="180" y2="180" stroke="{p.b}" stroke-width="16" stroke-linecap="round"/>'
    s += f'<circle cx="84" cy="84" r="66" fill="{p.c}" fill-opacity=".35" stroke="{p.k}" stroke-width="12"/>'
    s += f'<circle cx="84" cy="84" r="66" fill="none" stroke="{p.a}" stroke-width="6"/>'
    s += f'<path d="M48 70 Q52 48 74 42" fill="none" stroke="{p.l}" stroke-width="9" stroke-linecap="round"/>'
    return s


def keyhole(p: P) -> str:
    s = f'<rect x="20" y="10" width="160" height="180" rx="20" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="32" y="22" width="136" height="156" rx="12" fill="none" stroke="{p.b}" stroke-width="4"/>'
    s += f'<path d="M100 44 A30 30 0 0 1 116 100 L128 158 L72 158 L84 100 A30 30 0 0 1 100 44 Z" fill="{p.k}"/>'
    return s


def qmark(p: P, fill: str | None = None) -> str:
    return (
        f'<text x="100" y="170" font-family="Archivo Black" font-size="200" text-anchor="middle" '
        f'fill="{fill or p.a}" stroke="{p.k}" stroke-width="8" paint-order="stroke">?</text>'
    )


def fingerprint(p: P) -> str:
    s = f'<g fill="none" stroke="{p.a}" stroke-width="7" stroke-linecap="round">'
    for i, r in enumerate(range(14, 96, 12)):
        gap = 30 + (i * 37) % 60
        start = math.radians(-90 + gap / 2 + i * 13)
        end = math.radians(-90 - gap / 2 + 360 + i * 13)
        ry = r * 1.2
        x1, y1 = 100 + r * math.cos(start), 104 + ry * math.sin(start)
        x2, y2 = 100 + r * math.cos(end), 104 + ry * math.sin(end)
        s += f'<path d="M{x1:.1f} {y1:.1f} A{r} {ry} 0 1 1 {x2:.1f} {y2:.1f}"/>'
    s += "</g>"
    return s


def police_badge(p: P) -> str:
    d = "M100 8 L124 22 L150 16 L160 40 L184 52 L178 78 L192 100 L178 122 L184 148 L160 160 L150 184 L124 178 L100 192 L76 178 L50 184 L40 160 L16 148 L22 122 L8 100 L22 78 L16 52 L40 40 L50 16 L76 22 Z"
    s = f'<path d="{d}" fill="{p.b}" {_o(p)}/>'
    s += f'<circle cx="100" cy="100" r="58" fill="{p.a}" {_o(p, 5)}/>'
    s += f'<polygon points="{star(100, 102, 42, 17)}" fill="{p.b}" {_o(p, 4)}/>'
    return s


def folder(p: P) -> str:
    s = f'<path d="M14 40 L74 40 L88 56 L186 56 L186 176 L14 176 Z" fill="{p.b}" {_o(p)}/>'
    s += f'<rect x="30" y="70" width="140" height="96" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<path d="M14 80 L186 80 L186 176 L14 176 Z" fill="{p.b}" {_o(p)}/>'
    s += f'<rect x="40" y="104" width="120" height="44" rx="4" fill="none" stroke="{p.a}" stroke-width="6" transform="rotate(-8 100 126)"/>'
    return s


# ---------------------------------------------------------------- food, home


def fork_knife(p: P) -> str:
    s = f'<g transform="rotate(-30 100 100)"><rect x="54" y="80" width="14" height="110" rx="7" fill="{p.l}" {_o(p, 5)}/>'
    s += f'<path d="M42 12 L42 64 Q42 86 61 86 Q80 86 80 64 L80 12" fill="none" stroke="{p.k}" stroke-width="18" stroke-linecap="round"/>'
    s += f'<path d="M42 12 L42 64 Q42 86 61 86 Q80 86 80 64 L80 12" fill="none" stroke="{p.l}" stroke-width="8" stroke-linecap="round"/>'
    s += f'<line x1="61" y1="12" x2="61" y2="60" stroke="{p.k}" stroke-width="18" stroke-linecap="round"/><line x1="61" y1="12" x2="61" y2="60" stroke="{p.l}" stroke-width="8" stroke-linecap="round"/></g>'
    s += f'<g transform="rotate(30 100 100)"><path d="M126 190 L126 20 Q160 40 156 110 L140 112 L140 190 Z" fill="{p.l}" {_o(p, 5)}/></g>'
    return s


def chef_hat(p: P) -> str:
    s = f'<g fill="{p.l}" {_o(p)}><circle cx="62" cy="78" r="38"/><circle cx="100" cy="58" r="44"/><circle cx="140" cy="78" r="38"/></g>'
    s += f'<rect x="46" y="84" width="108" height="72" fill="{p.l}"/>'
    s += f'<path d="M46 96 L46 176 L154 176 L154 96" fill="{p.l}" {_o(p)}/>'
    s += f'<rect x="46" y="146" width="108" height="30" fill="{p.a}" {_o(p)}/>'
    for x in (74, 100, 126):
        s += f'<line x1="{x}" y1="104" x2="{x}" y2="140" stroke="{p.k}" stroke-width="4" opacity=".35"/>'
    return s


def whisk(p: P) -> str:
    s = f'<g transform="rotate(35 100 100)"><rect x="92" y="120" width="16" height="74" rx="8" fill="{p.a}" {_o(p, 5)}/>'
    for w in (14, 30, 46):
        s += f'<path d="M100 122 Q{100 - w} 60 100 8 Q{100 + w} 60 100 122" fill="none" stroke="{p.k}" stroke-width="7"/><path d="M100 122 Q{100 - w} 60 100 8 Q{100 + w} 60 100 122" fill="none" stroke="{p.l}" stroke-width="3"/>'
    s += "</g>"
    return s


def skillet_pan(p: P) -> str:
    s = f'<path d="M150 124 L194 170 Q198 178 190 184 Q182 190 176 182 L132 138 Z" fill="{p.k}"/>'
    s += f'<circle cx="86" cy="96" r="80" fill="{p.k}"/><circle cx="86" cy="96" r="64" fill="{p.a}"/>'
    s += f'<ellipse cx="86" cy="96" rx="30" ry="24" fill="{p.l}"/><circle cx="92" cy="100" r="13" fill="{p.b}"/>'
    return s


def tools_cross(p: P) -> str:
    s = f'<g transform="rotate(45 100 100)"><rect x="92" y="40" width="16" height="150" rx="6" fill="{p.b}" {_o(p, 5)}/>'
    s += f'<path d="M60 18 L140 18 L140 46 L116 46 L116 56 L84 56 L84 46 L60 46 Z" fill="{p.l}" {_o(p, 5)}/></g>'
    s += (
        f'<g transform="rotate(-45 100 100)"><rect x="92" y="50" width="16" height="130" rx="8" fill="{p.a}" {_o(p, 5)}/>'
        f'<path d="M100 10 A30 30 0 1 0 100 70 A30 30 0 1 0 100 10 Z M90 8 L90 36 L110 36 L110 8 Z" fill="{p.l}" fill-rule="evenodd" {_o(p, 5)}/>'
        f'<circle cx="100" cy="176" r="14" fill="{p.l}" {_o(p, 5)}/></g>'
    )
    return s


def watering_can(p: P) -> str:
    s = f'<path d="M140 96 L186 50 L196 60 L148 118 Z" fill="{p.a}" {_o(p, 5)}/>'
    s += f'<rect x="178" y="40" width="18" height="30" rx="4" fill="{p.a}" {_o(p, 5)} transform="rotate(45 187 55)"/>'
    s += f'<path d="M40 84 Q40 62 90 62 Q140 62 140 84 L140 170 Q90 184 40 170 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M58 70 Q60 20 90 20 Q120 20 122 70" fill="none" stroke="{p.k}" stroke-width="12"/>'
    s += f'<rect x="40" y="110" width="100" height="18" fill="{p.b}"/>'
    s += f'<path d="M40 84 Q40 62 90 62 Q140 62 140 84 L140 170 Q90 184 40 170 Z" fill="none" {_o(p)}/>'
    s += f'<g fill="{p.c}"><ellipse cx="18" cy="120" rx="4" ry="8"/><ellipse cx="10" cy="146" rx="4" ry="8"/><ellipse cx="24" cy="166" rx="4" ry="8"/></g>'
    return s


def sprout(p: P) -> str:
    s = f'<path d="M100 190 L100 96" stroke="{p.k}" stroke-width="10" stroke-linecap="round"/>'
    s += f'<path d="M100 110 Q40 110 24 44 Q88 40 100 110 Z" fill="{p.a}" {_o(p)}/><path d="M100 110 Q58 86 36 56" fill="none" stroke="{p.k}" stroke-width="4"/>'
    s += f'<path d="M100 96 Q160 96 176 26 Q112 22 100 96 Z" fill="{p.b}" {_o(p)}/><path d="M100 96 Q142 72 164 38" fill="none" stroke="{p.k}" stroke-width="4"/>'
    return s


def leaf(p: P) -> str:
    return (
        f'<path d="M30 170 Q10 60 170 30 Q160 170 30 170 Z" fill="{p.a}" {_o(p)}/>'
        f'<path d="M30 170 Q90 110 150 50" fill="none" stroke="{p.k}" stroke-width="6"/>'
        f'<path d="M70 128 L70 90 M100 100 L100 64 M100 100 L136 104 M70 128 L110 132" fill="none" stroke="{p.k}" stroke-width="4" stroke-linecap="round"/>'
    )


# ---------------------------------------------------------------- history, knowledge


def columns(p: P) -> str:
    s = f'<polygon points="100,12 190,58 10,58" fill="{p.l}" {_o(p)}/>'
    s += f'<rect x="14" y="58" width="172" height="16" fill="{p.l}" {_o(p, 5)}/>'
    for x in (30, 70, 110, 150):
        s += f'<rect x="{x}" y="74" width="20" height="92" fill="{p.l}" {_o(p, 5)}/>'
        s += f'<line x1="{x + 7}" y1="80" x2="{x + 7}" y2="160" stroke="{p.k}" stroke-width="2" opacity=".5"/><line x1="{x + 13}" y1="80" x2="{x + 13}" y2="160" stroke="{p.k}" stroke-width="2" opacity=".5"/>'
    s += f'<rect x="10" y="166" width="180" height="12" fill="{p.l}" {_o(p, 5)}/><rect x="2" y="178" width="196" height="14" fill="{p.l}" {_o(p, 5)}/>'
    return s


def hourglass(p: P) -> str:
    s = f'<rect x="36" y="10" width="128" height="18" rx="6" fill="{p.a}" {_o(p, 5)}/><rect x="36" y="172" width="128" height="18" rx="6" fill="{p.a}" {_o(p, 5)}/>'
    s += f'<path d="M52 28 Q52 84 96 100 Q52 116 52 172 L148 172 Q148 116 104 100 Q148 84 148 28 Z" fill="{p.c}" fill-opacity=".35" {_o(p, 5)}/>'
    s += f'<path d="M68 60 L132 60 Q124 86 100 96 Q76 86 68 60 Z" fill="{p.b}"/>'
    s += f'<path d="M100 104 L100 150" stroke="{p.b}" stroke-width="4"/><path d="M62 170 Q100 128 138 170 Z" fill="{p.b}"/>'
    return s


def scroll(p: P) -> str:
    s = f'<rect x="36" y="30" width="128" height="140" fill="{p.l}" {_o(p)}/>'
    s += f'<rect x="22" y="16" width="156" height="24" rx="12" fill="{p.b}" {_o(p, 5)}/><rect x="22" y="160" width="156" height="24" rx="12" fill="{p.b}" {_o(p, 5)}/>'
    for y in (64, 84, 104, 124):
        s += f'<line x1="56" y1="{y}" x2="{144 - (y % 40)}" y2="{y}" stroke="{p.k}" stroke-width="5" stroke-linecap="round" opacity=".55"/>'
    s += f'<circle cx="138" cy="140" r="20" fill="{p.a}" {_o(p, 4)}/><polygon points="{star(138, 140, 11, 5)}" fill="{p.l}" opacity=".8"/>'
    return s


def book(p: P) -> str:
    s = f'<path d="M100 44 Q60 24 12 34 L12 168 Q60 158 100 178 Q140 158 188 168 L188 34 Q140 24 100 44 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M100 50 Q64 32 22 40 L22 158 Q64 150 100 168 Z" fill="{p.l}" {_o(p, 4)}/><path d="M100 50 Q136 32 178 40 L178 158 Q136 150 100 168 Z" fill="{p.l}" {_o(p, 4)}/>'
    for y in (66, 86, 106, 126):
        s += f'<path d="M36 {y - 8} Q64 {y - 12} 88 {y}" fill="none" stroke="{p.k}" stroke-width="4" opacity=".4"/><path d="M112 {y} Q136 {y - 12} 164 {y - 8}" fill="none" stroke="{p.k}" stroke-width="4" opacity=".4"/>'
    s += f'<path d="M140 36 L140 90 L150 80 L160 90 L160 36" fill="{p.b}" {_o(p, 3)}/>'
    return s


def quill(p: P) -> str:
    s = f'<path d="M52 150 L60 110 L140 110 L148 150 Q148 178 100 178 Q52 178 52 150 Z" fill="{p.a}" {_o(p, 5)}/>'
    s += f'<rect x="56" y="100" width="88" height="14" rx="4" fill="{p.b}" {_o(p, 5)}/>'
    s += f'<path d="M92 118 Q120 60 180 8 Q176 60 128 100 Q112 112 92 118 Z" fill="{p.l}" {_o(p, 5)}/>'
    s += f'<path d="M96 116 Q136 64 176 14" fill="none" stroke="{p.k}" stroke-width="3"/>'
    s += f'<line x1="92" y1="118" x2="82" y2="140" stroke="{p.k}" stroke-width="5" stroke-linecap="round"/>'
    return s


def profile(p: P) -> str:
    s = f'<ellipse cx="100" cy="100" rx="78" ry="94" fill="{p.l}" {_o(p)}/>'
    s += f'<ellipse cx="100" cy="100" rx="66" ry="82" fill="none" stroke="{p.b}" stroke-width="4"/>'
    head = (
        "M118 172 L118 150 Q94 150 88 146 L90 132 L82 128 L88 120 L78 116 Q78 106 86 100 "
        "Q82 70 104 54 Q128 40 146 62 Q158 80 150 104 Q144 126 146 150 L146 172 Z"
    )
    s += f'<path d="{head}" fill="{p.a}" transform="translate(-14 0)"/>'
    return s


# ---------------------------------------------------------------- martial arts


def belt(p: P) -> str:
    s = f'<path d="M10 70 Q100 90 190 70 L190 100 Q100 120 10 100 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M86 96 L56 184 L82 184 L100 110 L118 184 L144 184 L114 96 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="80" y="66" width="40" height="48" rx="8" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="60" y="170" width="24" height="12" fill="{p.b}"/><rect x="116" y="170" width="24" height="12" fill="{p.b}"/>'
    return s


def enso(p: P) -> str:
    return (
        f'<path d="M150 46 Q176 76 170 116 Q160 172 100 180 Q36 184 22 120 Q12 60 70 30 Q110 12 146 36 '
        f'Q112 26 78 42 Q34 66 40 120 Q48 166 100 166 Q150 162 158 116 Q164 82 150 46 Z" fill="{p.a}"/>'
    )


def bamboo(p: P) -> str:
    s = ""
    for x, h, w in ((56, 190, 20), (100, 176, 22), (142, 190, 18)):
        top = 200 - h
        s += f'<rect x="{x - w / 2}" y="{top}" width="{w}" height="{h}" rx="6" fill="{p.a}" {_o(p, 4)}/>'
        for y in range(top + 36, 200, 44):
            s += f'<rect x="{x - w / 2 - 2}" y="{y}" width="{w + 4}" height="6" rx="3" fill="{p.k}"/>'
    s += f'<path d="M110 60 Q140 40 176 44 Q146 60 110 60 Z" fill="{p.b}" {_o(p, 3)}/><path d="M46 90 Q18 70 6 76 Q24 96 46 90 Z" fill="{p.b}" {_o(p, 3)}/>'
    return s


# ---------------------------------------------------------------- music


def vinyl(p: P) -> str:
    s = f'<circle cx="100" cy="100" r="92" fill="{p.k}"/>'
    for r in (82, 72, 62, 52):
        s += f'<circle cx="100" cy="100" r="{r}" fill="none" stroke="#fff" stroke-opacity=".12" stroke-width="2"/>'
    s += '<path d="M40 50 A76 76 0 0 1 84 26" fill="none" stroke="#fff" stroke-opacity=".35" stroke-width="6" stroke-linecap="round"/>'
    s += f'<circle cx="100" cy="100" r="34" fill="{p.a}"/><circle cx="100" cy="100" r="6" fill="{p.l}"/>'
    return s


def headphones(p: P) -> str:
    s = f'<path d="M30 120 L30 100 Q30 26 100 26 Q170 26 170 100 L170 120" fill="none" stroke="{p.k}" stroke-width="16"/>'
    s += f'<path d="M30 120 L30 100 Q30 26 100 26 Q170 26 170 100 L170 120" fill="none" stroke="{p.a}" stroke-width="7"/>'
    for x in (14, 142):
        s += f'<rect x="{x}" y="100" width="44" height="76" rx="16" fill="{p.a}" {_o(p)}/><rect x="{x + (26 if x < 100 else 0)}" y="110" width="18" height="56" rx="8" fill="{p.b}"/>'
    return s


def eq_bars(p: P) -> str:
    s = ""
    hs = [70, 120, 160, 100, 140, 80, 50]
    for i, h in enumerate(hs):
        x = 10 + i * 27
        for j in range(int(h // 20)):
            y = 190 - (j + 1) * 20
            c = p.a if j < 4 else (p.b if j < 6 else p.c)
            s += f'<rect x="{x}" y="{y}" width="22" height="16" rx="3" fill="{c}"/>'
    return s


def notes(p: P) -> str:
    s = f'<path d="M70 150 L70 40 L170 18 L170 128" fill="none" stroke="{p.k}" stroke-width="12" stroke-linejoin="round"/>'
    s += f'<path d="M70 40 L170 18 L170 46 L70 68 Z" fill="{p.k}"/>'
    s += f'<ellipse cx="50" cy="152" rx="26" ry="19" fill="{p.a}" {_o(p)} transform="rotate(-20 50 152)"/>'
    s += f'<ellipse cx="150" cy="130" rx="26" ry="19" fill="{p.a}" {_o(p)} transform="rotate(-20 150 130)"/>'
    return s


def guitar(p: P) -> str:
    s = f'<g transform="rotate(-40 100 100)"><rect x="92" y="4" width="16" height="104" fill="{p.k}"/>'
    s += f'<rect x="86" y="0" width="28" height="22" rx="4" fill="{p.k}"/>'
    s += f'<path d="M100 96 Q60 90 62 124 Q64 140 56 150 Q44 178 76 192 Q100 200 124 192 Q156 178 144 150 Q136 140 138 124 Q140 90 100 96 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<circle cx="100" cy="140" r="14" fill="{p.k}"/><rect x="84" y="166" width="32" height="8" rx="3" fill="{p.k}"/></g>'
    return s


# ---------------------------------------------------------------- sport, games


def trophy(p: P) -> str:
    s = f'<path d="M50 30 Q12 30 16 64 Q20 100 64 104" fill="none" stroke="{p.k}" stroke-width="16"/><path d="M150 30 Q188 30 184 64 Q180 100 136 104" fill="none" stroke="{p.k}" stroke-width="16"/>'
    s += f'<path d="M50 30 Q12 30 16 64 Q20 100 64 104" fill="none" stroke="{p.b}" stroke-width="7"/><path d="M150 30 Q188 30 184 64 Q180 100 136 104" fill="none" stroke="{p.b}" stroke-width="7"/>'
    s += f'<path d="M44 16 L156 16 L152 60 Q146 120 100 128 Q54 120 48 60 Z" fill="{p.b}" {_o(p)}/>'
    s += f'<rect x="88" y="126" width="24" height="30" fill="{p.b}" {_o(p, 5)}/><rect x="56" y="154" width="88" height="34" rx="4" fill="{p.a}" {_o(p)}/>'
    s += f'<polygon points="{star(100, 64, 26, 11)}" fill="{p.l}" opacity=".9"/>'
    s += f'<path d="M62 28 L70 28 L72 70 Q74 90 84 104" fill="none" stroke="{p.l}" stroke-width="6" stroke-linecap="round" opacity=".45"/>'
    return s


def medal(p: P) -> str:
    s = f'<polygon points="56,4 88,4 116,92 84,92" fill="{p.a}" {_o(p, 5)}/><polygon points="144,4 112,4 84,92 116,92" fill="{p.c}" {_o(p, 5)}/>'
    s += f'<circle cx="100" cy="134" r="58" fill="{p.b}" {_o(p)}/><circle cx="100" cy="134" r="44" fill="none" stroke="{p.k}" stroke-width="4" opacity=".5"/>'
    s += f'<polygon points="{star(100, 136, 32, 13)}" fill="{p.l}" {_o(p, 3)}/>'
    return s


def ball(p: P, kind: str = "basket") -> str:
    if kind == "basket":
        s = f'<circle cx="100" cy="100" r="88" fill="{p.a}" {_o(p)}/>'
        s += f'<g fill="none" stroke="{p.k}" stroke-width="6"><line x1="12" y1="100" x2="188" y2="100"/><line x1="100" y1="12" x2="100" y2="188"/>'
        s += '<path d="M40 36 Q70 100 40 164"/><path d="M160 36 Q130 100 160 164"/></g>'
        return s
    if kind == "base":
        s = f'<circle cx="100" cy="100" r="88" fill="{p.l}" {_o(p)}/>'
        s += f'<g fill="none" stroke="{p.a}" stroke-width="5"><path d="M44 30 Q84 100 44 170"/><path d="M156 30 Q116 100 156 170"/></g>'
        for i in range(8):
            y = 44 + i * 16
            dx = 16 * math.sin((y - 100) / 70 * 1.2)
            s += f'<path d="M{58 + abs(dx) * 0.4 - 8} {y} l10 -5" stroke="{p.a}" stroke-width="4"/><path d="M{142 - abs(dx) * 0.4 + 8} {y} l-10 -5" stroke="{p.a}" stroke-width="4"/>'
        return s
    # football
    s = f'<ellipse cx="100" cy="100" rx="92" ry="56" fill="{p.a}" {_o(p)} transform="rotate(-30 100 100)"/>'
    s += f'<g transform="rotate(-30 100 100)"><line x1="64" y1="100" x2="136" y2="100" stroke="{p.l}" stroke-width="6"/>'
    for x in range(72, 136, 14):
        s += f'<line x1="{x}" y1="90" x2="{x}" y2="110" stroke="{p.l}" stroke-width="5"/>'
    s += f'<path d="M24 76 Q30 100 24 124" fill="none" stroke="{p.l}" stroke-width="6"/><path d="M176 76 Q170 100 176 124" fill="none" stroke="{p.l}" stroke-width="6"/></g>'
    return s


def stadium_lights(p: P) -> str:
    s = f'<rect x="92" y="96" width="16" height="100" fill="{p.k}"/>'
    s += f'<rect x="22" y="14" width="156" height="86" rx="8" fill="{p.k}"/>'
    for r in range(3):
        for c in range(5):
            s += f'<circle cx="{44 + c * 28}" cy="{34 + r * 26}" r="10" fill="{p.l}"/>'
    return s


def buzzer(p: P) -> str:
    s = f'<rect x="20" y="130" width="160" height="50" rx="12" fill="{p.k}"/>'
    s += f'<rect x="44" y="112" width="112" height="28" rx="8" fill="{p.b}" {_o(p, 5)}/>'
    s += f'<path d="M50 116 Q50 44 100 44 Q150 44 150 116 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M70 86 Q74 62 96 58" fill="none" stroke="{p.l}" stroke-width="9" stroke-linecap="round" opacity=".7"/>'
    for a in (-150, -120, -90, -60, -30):
        r = math.radians(a)
        s += f'<line x1="{100 + 70 * math.cos(r):.0f}" y1="{96 + 70 * math.sin(r):.0f}" x2="{100 + 92 * math.cos(r):.0f}" y2="{96 + 92 * math.sin(r):.0f}" stroke="{p.b}" stroke-width="8" stroke-linecap="round"/>'
    return s


def prize_wheel(p: P) -> str:
    cols = [p.a, p.b, p.c, p.l]
    s = f'<circle cx="100" cy="104" r="90" fill="{p.k}"/>'
    for k in range(12):
        a0, a1 = math.radians(k * 30 - 90), math.radians((k + 1) * 30 - 90)
        s += f'<path d="M100 104 L{100 + 80 * math.cos(a0):.1f} {104 + 80 * math.sin(a0):.1f} A80 80 0 0 1 {100 + 80 * math.cos(a1):.1f} {104 + 80 * math.sin(a1):.1f} Z" fill="{cols[k % 4]}" stroke="{p.k}" stroke-width="2"/>'
    for k in range(12):
        a = math.radians(k * 30 - 90)
        s += f'<circle cx="{100 + 86 * math.cos(a):.1f}" cy="{104 + 86 * math.sin(a):.1f}" r="3.5" fill="{p.l}"/>'
    s += f'<circle cx="100" cy="104" r="16" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<polygon points="88,2 112,2 100,30" fill="{p.a}" {_o(p, 4)}/>'
    return s


def dice(p: P) -> str:
    s = f'<g transform="rotate(-12 70 110)"><rect x="18" y="58" width="104" height="104" rx="18" fill="{p.l}" {_o(p)}/>'
    for x, y in ((46, 86), (94, 134), (70, 110)):
        s += f'<circle cx="{x}" cy="{y}" r="10" fill="{p.k}"/>'
    s += "</g>"
    s += f'<g transform="rotate(16 140 80)"><rect x="96" y="30" width="90" height="90" rx="16" fill="{p.a}" {_o(p)}/>'
    for x, y in ((118, 52), (164, 52), (118, 98), (164, 98)):
        s += f'<circle cx="{x}" cy="{y}" r="9" fill="{p.l}"/>'
    s += "</g>"
    return s


def gamepad(p: P) -> str:
    d = "M52 56 L148 56 Q186 56 192 110 Q198 164 170 168 Q150 170 134 140 L66 140 Q50 170 30 168 Q2 164 8 110 Q14 56 52 56 Z"
    s = f'<path d="{d}" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="38" y="90" width="44" height="14" rx="3" fill="{p.k}"/><rect x="53" y="75" width="14" height="44" rx="3" fill="{p.k}"/>'
    for x, y, c in ((142, 84, p.b), (162, 100, p.c), (142, 116, p.l), (122, 100, p.b)):
        s += f'<circle cx="{x}" cy="{y}" r="9" fill="{c}" {_o(p, 3)}/>'
    return s


# ---------------------------------------------------------------- time, tension


def clock(p: P, h: float = 11.9, m: float = 55) -> str:
    s = f'<circle cx="100" cy="100" r="88" fill="{p.l}" {_o(p, 8)}/>'
    for k in range(12):
        a = math.radians(k * 30)
        r1 = 66 if k % 3 else 60
        s += f'<line x1="{100 + r1 * math.sin(a):.1f}" y1="{100 - r1 * math.cos(a):.1f}" x2="{100 + 76 * math.sin(a):.1f}" y2="{100 - 76 * math.cos(a):.1f}" stroke="{p.k}" stroke-width="{7 if k % 3 == 0 else 4}"/>'
    ha, ma = math.radians(h * 30), math.radians(m * 6)
    s += f'<line x1="100" y1="100" x2="{100 + 42 * math.sin(ha):.1f}" y2="{100 - 42 * math.cos(ha):.1f}" stroke="{p.k}" stroke-width="10" stroke-linecap="round"/>'
    s += f'<line x1="100" y1="100" x2="{100 + 64 * math.sin(ma):.1f}" y2="{100 - 64 * math.cos(ma):.1f}" stroke="{p.a}" stroke-width="6" stroke-linecap="round"/>'
    s += f'<circle cx="100" cy="100" r="8" fill="{p.a}"/>'
    return s


def stopwatch(p: P) -> str:
    s = f'<rect x="88" y="8" width="24" height="18" rx="4" fill="{p.k}"/><rect x="96" y="22" width="8" height="12" fill="{p.k}"/>'
    s += f'<rect x="146" y="32" width="18" height="12" rx="3" fill="{p.k}" transform="rotate(45 155 38)"/>'
    s += f'<circle cx="100" cy="112" r="80" fill="{p.a}" {_o(p)}/><circle cx="100" cy="112" r="64" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<path d="M100 112 L100 56 A56 56 0 0 1 148 84 Z" fill="{p.b}" opacity=".7"/>'
    s += f'<line x1="100" y1="112" x2="100" y2="58" stroke="{p.k}" stroke-width="6" stroke-linecap="round"/><circle cx="100" cy="112" r="7" fill="{p.k}"/>'
    return s


def eye(p: P) -> str:
    s = f'<path d="M8 100 Q100 10 192 100 Q100 190 8 100 Z" fill="{p.l}" {_o(p, 7)}/>'
    s += f'<circle cx="100" cy="100" r="44" fill="{p.a}" {_o(p, 5)}/><circle cx="100" cy="100" r="20" fill="{p.k}"/>'
    s += f'<circle cx="86" cy="86" r="8" fill="{p.l}"/>'
    return s


def heartbeat(p: P) -> str:
    return (
        f'<polyline points="4,110 50,110 66,86 80,138 98,30 116,170 132,100 146,110 196,110" fill="none" '
        f'stroke="{p.a}" stroke-width="12" stroke-linejoin="round" stroke-linecap="round"/>'
    )


def spiral(p: P) -> str:
    d = "M100 100"
    for i in range(1, 160):
        t = i * 0.12
        r = 4 + t * 5.4
        d += f" L{100 + r * math.cos(t):.1f} {100 + r * math.sin(t):.1f}"
    return f'<path d="{d}" fill="none" stroke="{p.a}" stroke-width="9" stroke-linecap="round"/>'


def shatter(p: P) -> str:
    rng = random.Random(4)
    s = ""
    cx, cy = 110, 90
    ends = []
    for k in range(9):
        a = math.radians(k * 40 + rng.uniform(-12, 12))
        r = rng.uniform(80, 110)
        mid = (
            cx + r * 0.45 * math.cos(a) + rng.uniform(-6, 6),
            cy + r * 0.45 * math.sin(a) + rng.uniform(-6, 6),
        )
        end = (cx + r * math.cos(a), cy + r * math.sin(a))
        ends.append((mid, end))
        s += f'<polyline points="{pts([(cx, cy), mid, end])}" fill="none" stroke="{p.a}" stroke-width="5" stroke-linejoin="round"/>'
    for i in range(len(ends)):
        (m1, _), (m2, _) = ends[i], ends[(i + 1) % len(ends)]
        s += f'<line x1="{m1[0]:.1f}" y1="{m1[1]:.1f}" x2="{m2[0]:.1f}" y2="{m2[1]:.1f}" stroke="{p.a}" stroke-width="4"/>'
    return s


# ---------------------------------------------------------------- talk, news


def speech(p: P) -> str:
    s = f'<path d="M20 30 L130 30 Q146 30 146 46 L146 100 Q146 116 130 116 L70 116 L42 142 L46 116 L36 116 Q20 116 20 100 L20 46 Q20 30 36 30 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M84 90 L170 90 Q184 90 184 104 L184 150 Q184 164 170 164 L162 164 L166 188 L138 164 L98 164 Q84 164 84 150 Z" fill="{p.b}" {_o(p)}/>'
    for x in (58, 82, 106):
        s += f'<circle cx="{x}" cy="73" r="8" fill="{p.l}"/>'
    return s


def armchairs(p: P) -> str:
    def chair(x, c):
        return (
            f'<rect x="{x}" y="60" width="70" height="80" rx="16" fill="{c}" {_o(p)}/>'
            f'<rect x="{x - 10}" y="104" width="22" height="60" rx="10" fill="{c}" {_o(p)}/><rect x="{x + 58}" y="104" width="22" height="60" rx="10" fill="{c}" {_o(p)}/>'
            f'<rect x="{x + 10}" y="120" width="50" height="34" rx="8" fill="{p.l}" {_o(p, 4)}/>'
            f'<rect x="{x}" y="160" width="8" height="18" fill="{p.k}"/><rect x="{x + 62}" y="160" width="8" height="18" fill="{p.k}"/>'
        )

    return chair(18, p.a) + chair(112, p.b)


def newspaper(p: P) -> str:
    s = f'<rect x="20" y="24" width="160" height="152" rx="4" fill="{p.l}" {_o(p)}/>'
    s += f'<rect x="34" y="38" width="132" height="22" fill="{p.k}"/>'
    s += f'<rect x="34" y="70" width="60" height="50" fill="{p.a}"/>'
    for y in range(72, 124, 12):
        s += f'<line x1="104" y1="{y}" x2="166" y2="{y}" stroke="{p.k}" stroke-width="5" opacity=".6"/>'
    for y in range(134, 170, 12):
        s += f'<line x1="34" y1="{y}" x2="166" y2="{y}" stroke="{p.k}" stroke-width="5" opacity=".6"/>'
    return s


# ---------------------------------------------------------------- space


def rocket(p: P) -> str:
    s = f'<path d="M100 196 Q84 176 88 154 L112 154 Q116 176 100 196 Z" fill="{p.b}"/>'
    s += f'<path d="M100 184 Q92 170 94 156 L106 156 Q108 170 100 184 Z" fill="{p.l}"/>'
    s += f'<path d="M72 118 L40 150 L40 172 L76 150 Z" fill="{p.a}" {_o(p, 5)}/><path d="M128 118 L160 150 L160 172 L124 150 Z" fill="{p.a}" {_o(p, 5)}/>'
    s += f'<path d="M100 6 Q140 40 136 112 L126 156 L74 156 L64 112 Q60 40 100 6 Z" fill="{p.l}" {_o(p)}/>'
    s += f'<path d="M100 6 Q124 26 132 56 L68 56 Q76 26 100 6 Z" fill="{p.a}" {_o(p, 5)}/>'
    s += f'<circle cx="100" cy="92" r="18" fill="{p.c}" {_o(p, 5)}/>'
    s += f'<rect x="92" y="136" width="16" height="30" rx="4" fill="{p.a}" {_o(p, 4)}/>'
    return s


def planet(p: P) -> str:
    s = f'<g transform="rotate(-20 100 100)"><path d="M8 100 A92 26 0 0 1 192 100" fill="none" stroke="{p.b}" stroke-width="12"/>'
    s += f'<circle cx="100" cy="100" r="60" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M50 80 Q100 70 150 80" fill="none" stroke="{p.l}" stroke-width="6" opacity=".35"/><path d="M44 110 Q100 100 156 110" fill="none" stroke="{p.k}" stroke-width="6" opacity=".2"/>'
    s += f'<path d="M8 100 A92 26 0 0 0 192 100" fill="none" stroke="{p.k}" stroke-width="20"/><path d="M8 100 A92 26 0 0 0 192 100" fill="none" stroke="{p.b}" stroke-width="12"/></g>'
    return s


def sparkle(p: P, fill: str | None = None) -> str:
    return f'<path d="M100 4 Q108 92 196 100 Q108 108 100 196 Q92 108 4 100 Q92 92 100 4 Z" fill="{fill or p.l}"/>'


def ufo(p: P) -> str:
    s = f'<polygon points="70,120 130,120 170,196 30,196" fill="{p.b}" opacity=".35"/>'
    s += f'<ellipse cx="100" cy="80" rx="42" ry="40" fill="{p.c}" fill-opacity=".6" {_o(p, 5)}/>'
    s += f'<ellipse cx="100" cy="104" rx="92" ry="28" fill="{p.a}" {_o(p)}/>'
    for x in (40, 70, 100, 130, 160):
        s += f'<circle cx="{x}" cy="{106 + (abs(x - 100) / 12)}" r="6" fill="{p.b}"/>'
    return s


# ---------------------------------------------------------------- bubbles, drinks, flowers


def bubbles(p: P) -> str:
    s = ""
    for cx, cy, r in ((84, 110, 62), (150, 62, 38), (156, 150, 28), (40, 40, 20), (130, 188, 10)):
        s += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{p.c}" fill-opacity=".55" stroke="{p.a}" stroke-width="{max(3, r / 9):.1f}"/>'
        s += f'<path d="M{cx - r * 0.55} {cy - r * 0.2} Q{cx - r * 0.5} {cy - r * 0.6} {cx - r * 0.1} {cy - r * 0.62}" fill="none" stroke="{p.l}" stroke-width="{max(3, r / 7):.1f}" stroke-linecap="round"/>'
    return s


def coupes(p: P) -> str:
    def glass(rot, x):
        return (
            f'<g transform="rotate({rot} {x} 180)"><path d="M{x - 44} 40 Q{x} 110 {x + 44} 40 Z" fill="{p.b}" {_o(p, 5)}/>'
            f'<line x1="{x}" y1="86" x2="{x}" y2="170" stroke="{p.k}" stroke-width="7"/><rect x="{x - 28}" y="168" width="56" height="10" rx="5" fill="{p.k}"/></g>'
        )

    s = glass(-16, 76) + glass(16, 124)
    s += f'<g fill="{p.a}"><polygon points="{star(100, 20, 14, 5, 4)}"/><circle cx="72" cy="16" r="4"/><circle cx="130" cy="12" r="4"/></g>'
    return s


def rose(p: P) -> str:
    s = '<path d="M100 196 L100 104" stroke="#2f7a3a" stroke-width="9" stroke-linecap="round"/>'
    s += f'<path d="M100 160 Q60 150 50 120 Q86 120 100 150 Z" fill="#3f9a4a" {_o(p, 4)}/><path d="M100 140 Q140 130 152 104 Q116 104 100 130 Z" fill="#3f9a4a" {_o(p, 4)}/>'
    s += f'<path d="M100 112 Q46 104 48 58 Q50 22 100 18 Q150 22 152 58 Q154 104 100 112 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M68 52 Q84 30 108 36 Q132 44 130 68 Q126 90 100 92 Q76 90 76 70 Q78 54 98 54 Q114 56 112 70" fill="none" stroke="{p.k}" stroke-width="5" stroke-linecap="round"/>'
    return s


def envelope(p: P) -> str:
    s = f'<rect x="14" y="44" width="172" height="118" rx="8" fill="{p.l}" {_o(p)}/>'
    s += f'<polyline points="14,52 100,118 186,52" fill="none" {_o(p, 5)}/><polyline points="14,160 76,100 M186,160 124,100" fill="none" {_o(p, 4)}/>'
    s += f'<g transform="translate(76 92) scale(.24)">{heart(p)}</g>'
    return s


def sakura(p: P) -> str:
    s = ""
    for k in range(5):
        s += (
            f'<path d="M100 100 Q70 60 84 26 Q92 34 100 26 Q108 34 116 26 Q130 60 100 100 Z" fill="{p.a}" {_o(p, 4)} '
            f'transform="rotate({k * 72} 100 100)"/>'
        )
    s += f'<circle cx="100" cy="100" r="16" fill="{p.b}" {_o(p, 4)}/>'
    return s


def snowflake(p: P) -> str:
    s = f'<g stroke="{p.l}" stroke-width="10" stroke-linecap="round" fill="none">'
    for k in range(6):
        s += f'<g transform="rotate({k * 60} 100 100)"><line x1="100" y1="100" x2="100" y2="14"/><polyline points="80,40 100,58 120,40"/><polyline points="86,70 100,82 114,70"/></g>'
    s += "</g>"
    return s


def pine(p: P) -> str:
    s = f'<rect x="90" y="160" width="20" height="30" fill="{p.b}"/>'
    s += f'<polygon points="100,10 140,70 124,70 160,120 138,120 176,168 24,168 62,120 40,120 76,70 60,70" fill="{p.a}" {_o(p)}/>'
    return s


def campfire(p: P) -> str:
    s = f'<g transform="rotate(14 100 176)"><rect x="30" y="164" width="140" height="22" rx="11" fill="#7a4a24" {_o(p, 5)}/></g>'
    s += f'<g transform="rotate(-14 100 176)"><rect x="30" y="164" width="140" height="22" rx="11" fill="#8f5a2c" {_o(p, 5)}/></g>'
    s += f'<path d="M100 20 Q150 80 140 130 Q134 168 100 170 Q66 168 60 130 Q52 90 84 60 Q86 90 100 96 Q92 60 100 20 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M100 84 Q126 114 120 140 Q116 160 100 160 Q84 160 80 140 Q78 118 94 104 Q96 120 104 122 Q100 104 100 84 Z" fill="{p.b}"/>'
    return s


def paw(p: P) -> str:
    s = f'<path d="M100 96 Q140 96 156 140 Q164 176 132 176 Q116 176 100 168 Q84 176 68 176 Q36 176 44 140 Q60 96 100 96 Z" fill="{p.a}" {_o(p)}/>'
    for x, y, r in ((40, 84, 20), (76, 44, 22), (124, 44, 22), (160, 84, 20)):
        s += f'<ellipse cx="{x}" cy="{y}" rx="{r}" ry="{r * 1.25}" fill="{p.a}" {_o(p)}/>'
    return s


def fish(p: P) -> str:
    s = f'<path d="M150 100 L196 60 L190 100 L196 140 Z" fill="{p.b}" {_o(p)}/>'
    s += f'<path d="M10 100 Q60 40 130 60 Q160 72 160 100 Q160 128 130 140 Q60 160 10 100 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<circle cx="44" cy="92" r="8" fill="{p.k}"/><path d="M76 70 Q90 100 76 130" fill="none" stroke="{p.k}" stroke-width="5"/>'
    return s


def anchor(p: P) -> str:
    s = f'<circle cx="100" cy="34" r="20" fill="none" stroke="{p.a}" stroke-width="12"/>'
    s += f'<rect x="92" y="52" width="16" height="130" fill="{p.a}"/><rect x="54" y="72" width="92" height="14" rx="7" fill="{p.a}"/>'
    s += f'<path d="M22 118 Q24 176 100 184 Q176 176 178 118" fill="none" stroke="{p.a}" stroke-width="14" stroke-linecap="round"/>'
    s += f'<polygon points="8,128 36,104 40,136" fill="{p.a}"/><polygon points="192,128 164,104 160,136" fill="{p.a}"/>'
    return s


def car(p: P) -> str:
    s = f'<path d="M14 136 L14 110 Q14 96 30 92 L56 86 L80 54 Q86 46 98 46 L140 46 Q152 46 160 56 L180 86 Q192 90 192 104 L192 136 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M86 60 L102 60 L102 86 L66 86 Z" fill="{p.c}" {_o(p, 4)}/><path d="M112 60 L140 60 Q146 60 150 66 L162 86 L112 86 Z" fill="{p.c}" {_o(p, 4)}/>'
    for x in (54, 152):
        s += f'<circle cx="{x}" cy="138" r="26" fill="{p.k}"/><circle cx="{x}" cy="138" r="11" fill="{p.l}"/>'
    s += f'<rect x="172" y="104" width="18" height="10" rx="3" fill="{p.b}"/>'
    return s


def piston(p: P) -> str:
    s = f'<rect x="44" y="18" width="112" height="70" rx="10" fill="{p.l}" {_o(p)}/>'
    for y in (34, 50, 66):
        s += f'<line x1="44" y1="{y}" x2="156" y2="{y}" stroke="{p.k}" stroke-width="4"/>'
    s += f'<rect x="84" y="86" width="32" height="92" rx="10" fill="{p.a}" {_o(p)}/>'
    s += f'<circle cx="100" cy="176" r="22" fill="{p.a}" {_o(p)}/><circle cx="100" cy="176" r="8" fill="{p.k}"/>'
    return s


def tent(p: P) -> str:
    s = f'<polygon points="100,20 188,176 12,176" fill="{p.a}" {_o(p)}/>'
    s += f'<polygon points="100,70 136,176 64,176" fill="{p.k}"/>'
    s += f'<line x1="100" y1="20" x2="100" y2="4" stroke="{p.k}" stroke-width="6"/><path d="M100 4 L124 10 L100 18 Z" fill="{p.b}"/>'
    return s


def cloud(p: P) -> str:
    return (
        f'<g fill="{p.l}" {_o(p)}><circle cx="60" cy="112" r="38"/><circle cx="100" cy="84" r="50"/><circle cx="146" cy="112" r="38"/></g>'
        f'<rect x="60" y="100" width="86" height="50" fill="{p.l}"/><path d="M22 116 Q22 150 60 150 L146 150 Q184 150 184 112" fill="none" {_o(p)}/>'
    )


def lightning(p: P) -> str:
    return (
        f'<polygon points="118,6 40,112 92,112 74,194 162,78 108,78 136,6" fill="{p.b}" {_o(p)}/>'
    )


def horseshoe(p: P) -> str:
    s = f'<path d="M40 30 L40 110 Q40 176 100 176 Q160 176 160 110 L160 30" fill="none" stroke="{p.k}" stroke-width="40" stroke-linecap="butt"/>'
    s += f'<path d="M40 30 L40 110 Q40 176 100 176 Q160 176 160 110 L160 30" fill="none" stroke="{p.a}" stroke-width="28"/>'
    for x, y in ((40, 60), (40, 100), (160, 60), (160, 100), (62, 150), (138, 150)):
        s += f'<circle cx="{x}" cy="{y}" r="5" fill="{p.k}"/>'
    return s


def cowboy_hat(p: P) -> str:
    s = f'<path d="M6 120 Q20 150 100 150 Q180 150 194 120 Q176 132 150 128 Q156 70 138 52 Q120 42 100 60 Q80 42 62 52 Q44 70 50 128 Q24 132 6 120 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M52 110 Q100 124 148 110 L150 126 Q100 138 50 126 Z" fill="{p.k}"/>'
    return s


def cactus(p: P) -> str:
    s = f'<rect x="84" y="20" width="32" height="170" rx="16" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M84 110 L56 110 Q40 110 40 94 L40 60 Q40 50 50 50 Q60 50 60 60 L60 90 L84 90" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M116 90 L140 90 Q156 90 156 74 L156 44 Q156 34 146 34 Q136 34 136 44 L136 70 L116 70" fill="{p.a}" {_o(p)}/>'
    return s


def biplane(p: P) -> str:
    s = f'<rect x="20" y="58" width="160" height="16" rx="6" fill="{p.a}" {_o(p, 5)}/><rect x="20" y="118" width="160" height="16" rx="6" fill="{p.a}" {_o(p, 5)}/>'
    s += f'<line x1="50" y1="74" x2="50" y2="118" stroke="{p.k}" stroke-width="5"/><line x1="150" y1="74" x2="150" y2="118" stroke="{p.k}" stroke-width="5"/>'
    s += f'<rect x="76" y="70" width="48" height="62" rx="20" fill="{p.b}" {_o(p, 5)}/>'
    s += f'<ellipse cx="100" cy="100" rx="10" ry="38" fill="{p.l}" opacity=".7"/><circle cx="100" cy="100" r="8" fill="{p.k}"/>'
    s += f'<rect x="84" y="134" width="8" height="24" fill="{p.k}"/><rect x="108" y="134" width="8" height="24" fill="{p.k}"/><circle cx="88" cy="162" r="8" fill="{p.k}"/><circle cx="112" cy="162" r="8" fill="{p.k}"/>'
    return s


def laurel(p: P) -> str:
    """Two laurel branches curving up into a wreath."""
    s = ""
    for side in (-1, 1):
        stem = []
        for i in range(11):
            a = math.radians(90 + side * (22 + i / 10 * 136))
            stem.append((100 + 78 * math.cos(a), 104 + 84 * math.sin(a)))
        s += f'<polyline points="{pts(stem)}" fill="none" stroke="{p.a}" stroke-width="5" stroke-linecap="round"/>'
        for i in range(1, 11):
            a = math.radians(90 + side * (22 + i / 10 * 136))
            x, y = 100 + 78 * math.cos(a), 104 + 84 * math.sin(a)
            th = math.atan2(side * math.cos(a), side * -math.sin(a))
            offs = (0,) if i == 10 else (-40, 40)
            for off in offs:
                tl = th + math.radians(off)
                cx, cy = x + 14 * math.cos(tl), y + 14 * math.sin(tl)
                s += (
                    f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="7" ry="16" fill="{p.a}" '
                    f'transform="rotate({math.degrees(tl) + 90:.0f} {cx:.1f} {cy:.1f})"/>'
                )
    return s


def crown(p: P) -> str:
    s = f'<path d="M24 150 L14 50 L64 98 L100 30 L136 98 L186 50 L176 150 Z" fill="{p.b}" {_o(p)}/>'
    s += f'<rect x="22" y="146" width="156" height="30" rx="4" fill="{p.b}" {_o(p)}/>'
    for x, c in ((60, p.a), (100, p.c), (140, p.a)):
        s += f'<circle cx="{x}" cy="161" r="8" fill="{c}"/>'
    for x, y in ((14, 50), (100, 30), (186, 50)):
        s += f'<circle cx="{x}" cy="{y}" r="9" fill="{p.b}" {_o(p, 5)}/>'
    return s


def lamp(p: P) -> str:
    """A streetlamp with a pool of light."""
    s = f'<ellipse cx="100" cy="190" rx="70" ry="8" fill="{p.b}" opacity=".4"/>'
    s += f'<polygon points="80,52 120,52 170,190 30,190" fill="{p.b}" opacity=".18"/>'
    s += f'<rect x="94" y="46" width="12" height="146" fill="{p.k}"/>'
    s += f'<path d="M72 50 L128 50 L116 22 L84 22 Z" fill="{p.k}"/><path d="M78 50 L122 50 L118 60 L82 60 Z" fill="{p.b}"/>'
    s += f'<rect x="96" y="10" width="8" height="14" fill="{p.k}"/><rect x="80" y="182" width="40" height="10" fill="{p.k}"/>'
    return s


def fedora(p: P) -> str:
    s = f'<path d="M4 132 Q40 152 100 152 Q160 152 196 132 Q170 120 150 120 Q156 70 136 50 Q118 40 100 56 Q82 40 64 50 Q44 70 50 120 Q30 120 4 132 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M52 104 Q100 118 148 104 L150 120 Q100 132 50 120 Z" fill="{p.k}"/>'
    s += f'<path d="M100 58 Q92 80 100 100" fill="none" stroke="{p.k}" stroke-width="4" opacity=".5"/>'
    return s


def eightball(p: P) -> str:
    s = f'<circle cx="100" cy="100" r="88" fill="{p.k}"/>'
    s += f'<circle cx="100" cy="90" r="36" fill="{p.l}"/><text x="100" y="110" font-family="Archivo Black" font-size="50" text-anchor="middle" fill="{p.k}">8</text>'
    s += '<path d="M40 60 Q54 30 86 24" fill="none" stroke="#fff" stroke-opacity=".35" stroke-width="8" stroke-linecap="round"/>'
    return s


def cassette(p: P) -> str:
    s = f'<rect x="8" y="36" width="184" height="128" rx="12" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="28" y="52" width="144" height="54" rx="6" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<rect x="28" y="52" width="144" height="16" fill="{p.b}"/>'
    s += f'<rect x="56" y="74" width="88" height="26" rx="13" fill="{p.k}"/>'
    s += (
        f'<circle cx="72" cy="87" r="9" fill="{p.l}"/><circle cx="128" cy="87" r="9" fill="{p.l}"/>'
    )
    s += f'<path d="M40 164 L56 124 L144 124 L160 164 Z" fill="{p.k}" opacity=".85"/>'
    return s


def boombox(p: P) -> str:
    s = f'<path d="M50 44 Q50 20 76 20 L124 20 Q150 20 150 44" fill="none" stroke="{p.k}" stroke-width="10"/>'
    s += f'<rect x="6" y="44" width="188" height="120" rx="14" fill="{p.a}" {_o(p)}/>'
    for cx in (50, 150):
        s += f'<circle cx="{cx}" cy="110" r="36" fill="{p.k}"/><circle cx="{cx}" cy="110" r="22" fill="{p.l}"/><circle cx="{cx}" cy="110" r="8" fill="{p.k}"/>'
    s += f'<rect x="80" y="60" width="40" height="22" rx="3" fill="{p.l}"/><rect x="84" y="94" width="32" height="30" rx="4" fill="{p.k}"/>'
    return s


def satellite_dish(p: P) -> str:
    s = f'<path d="M40 60 Q60 160 160 170 Q100 120 40 60 Z" fill="{p.l}" {_o(p)}/>'
    s += f'<line x1="98" y1="118" x2="140" y2="76" stroke="{p.k}" stroke-width="6"/><circle cx="142" cy="74" r="10" fill="{p.a}"/>'
    s += f'<path d="M100 150 L80 196 L140 196 L118 150" fill="{p.k}"/>'
    for r in (24, 40):
        s += f'<path d="M{150 + r * 0.2} {50 - r * 0.6} A{r} {r} 0 0 1 {170 + r * 0.6} {70 - r * 0.2}" fill="none" stroke="{p.b}" stroke-width="6" stroke-linecap="round"/>'
    return s


def antenna_tv(p: P) -> str:
    return tv_set(p)


def lightbulb(p: P) -> str:
    s = f'<path d="M100 14 Q156 14 156 72 Q156 100 134 122 Q124 132 124 150 L76 150 Q76 132 66 122 Q44 100 44 72 Q44 14 100 14 Z" fill="{p.b}" {_o(p)}/>'
    s += f'<rect x="76" y="150" width="48" height="16" fill="{p.l}" {_o(p, 4)}/><rect x="80" y="166" width="40" height="14" fill="{p.l}" {_o(p, 4)}/><rect x="88" y="180" width="24" height="12" rx="6" fill="{p.k}"/>'
    s += f'<path d="M84 150 L84 110 Q84 96 100 96 Q116 96 116 110 L116 150" fill="none" stroke="{p.k}" stroke-width="4"/>'
    return s


def beaker(p: P) -> str:
    s = f'<path d="M72 14 L128 14 M80 14 L80 70 L24 172 Q18 186 34 186 L166 186 Q182 186 176 172 L120 70 L120 14" fill="{p.l}" {_o(p)}/>'
    s += f'<path d="M50 124 L150 124 L172 170 Q176 180 166 180 L34 180 Q24 180 28 170 Z" fill="{p.a}"/>'
    s += f'<circle cx="86" cy="150" r="8" fill="{p.l}" opacity=".7"/><circle cx="116" cy="160" r="5" fill="{p.l}" opacity=".7"/><circle cx="104" cy="138" r="4" fill="{p.l}" opacity=".7"/>'
    s += f'<path d="M80 14 L80 70 L24 172 Q18 186 34 186 L166 186 Q182 186 176 172 L120 70 L120 14" fill="none" {_o(p)}/>'
    return s


def atom(p: P) -> str:
    s = f'<g fill="none" stroke="{p.a}" stroke-width="9">'
    for r in (0, 60, 120):
        s += f'<ellipse cx="100" cy="100" rx="88" ry="32" transform="rotate({r} 100 100)"/>'
    s += f'</g><circle cx="100" cy="100" r="16" fill="{p.b}"/>'
    return s


def wave(p: P) -> str:
    return (
        f'<path d="M6 150 Q20 60 96 40 Q170 26 190 90 Q160 64 128 80 Q100 96 118 126 Q84 120 76 150 Z" fill="{p.a}" {_o(p)}/>'
        f'<path d="M6 150 L194 150 L194 190 L6 190 Z" fill="{p.c}" {_o(p)}/>'
        f'<path d="M150 64 Q170 60 182 74" fill="none" stroke="{p.l}" stroke-width="7" stroke-linecap="round"/>'
    )


def surfboard(p: P) -> str:
    return (
        f'<g transform="rotate(30 100 100)"><path d="M100 4 Q146 60 140 150 Q134 196 100 196 Q66 196 60 150 Q54 60 100 4 Z" fill="{p.a}" {_o(p)}/>'
        f'<line x1="100" y1="16" x2="100" y2="188" stroke="{p.l}" stroke-width="8"/><line x1="100" y1="16" x2="100" y2="188" stroke="{p.b}" stroke-width="3"/></g>'
    )


def palm(p: P) -> str:
    s = f'<path d="M96 196 Q92 140 112 76" fill="none" stroke="{p.b}" stroke-width="16" stroke-linecap="round"/>'
    for k in range(6):
        y = 186 - k * 20
        s += f'<path d="M{92 + k * 3} {y} l16 -4" stroke="{p.k}" stroke-width="3" opacity=".4"/>'
    fronds = [(-170, 76, 30), (-135, 70, 22), (-95, 50, 10), (-50, 70, 22), (-10, 76, 30)]
    for a, l, droop in fronds:
        r = math.radians(a)
        x2, y2 = 112 + l * math.cos(r), 76 + l * math.sin(r) + droop
        cx, cy = 112 + l * 0.55 * math.cos(r), 76 + l * 0.55 * math.sin(r) - 18
        s += f'<path d="M112 76 Q{cx:.0f} {cy:.0f} {x2:.0f} {y2:.0f} Q{cx:.0f} {cy + 16:.0f} 112 84 Z" fill="{p.a}" {_o(p, 4)}/>'
    s += '<circle cx="104" cy="88" r="7" fill="#8a5a2b"/><circle cx="118" cy="90" r="7" fill="#8a5a2b"/>'
    return s


def saw(p: P) -> str:
    s = f'<path d="M20 90 L160 60 L170 110 L30 130 Z" fill="{p.l}" {_o(p)}/>'
    teeth = " ".join(f"L{30 + i * 10} {130 + (6 if i % 2 else 0) - i * 1.4:.1f}" for i in range(14))
    s += f'<path d="M30 130 {teeth}" fill="none" stroke="{p.k}" stroke-width="4"/>'
    s += f'<path d="M150 50 Q186 40 190 76 L192 120 Q180 132 164 120 Z" fill="{p.a}" {_o(p)}/><ellipse cx="174" cy="90" rx="8" ry="16" fill="{p.l}"/>'
    return s


def hammer(p: P) -> str:
    return (
        f'<g transform="rotate(-35 100 100)"><rect x="92" y="60" width="16" height="136" rx="6" fill="{p.b}" {_o(p, 5)}/>'
        f'<path d="M52 20 L148 20 L148 60 L52 60 Q40 40 52 20 Z" fill="{p.l}" {_o(p, 5)}/></g>'
    )


def flower(p: P) -> str:
    s = f'<path d="M100 196 L100 110" stroke="#2f7a3a" stroke-width="9" stroke-linecap="round"/><path d="M100 160 Q64 150 56 124 Q88 128 100 150 Z" fill="#3f9a4a" {_o(p, 4)}/>'
    for k in range(8):
        s += f'<ellipse cx="100" cy="46" rx="18" ry="36" fill="{p.a}" {_o(p, 4)} transform="rotate({k * 45} 100 82)"/>'
    s += f'<circle cx="100" cy="82" r="22" fill="{p.b}" {_o(p, 4)}/>'
    return s


def mortarboard(p: P) -> str:
    s = f'<polygon points="100,30 196,74 100,118 4,74" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M50 96 L50 142 Q100 170 150 142 L150 96 L100 118 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M100 74 L168 90 L168 142" fill="none" stroke="{p.b}" stroke-width="5"/><rect x="160" y="140" width="16" height="30" rx="4" fill="{p.b}"/>'
    return s


def apple(p: P) -> str:
    s = f'<path d="M100 48 Q60 24 34 56 Q10 90 30 136 Q50 186 82 180 Q92 176 100 180 Q108 176 118 180 Q150 186 170 136 Q190 90 166 56 Q140 24 100 48 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M100 48 Q98 26 108 10" fill="none" stroke="{p.k}" stroke-width="7" stroke-linecap="round"/><path d="M108 28 Q136 8 150 24 Q128 40 108 28 Z" fill="#3f9a4a" {_o(p, 4)}/>'
    s += f'<path d="M52 80 Q58 62 76 58" fill="none" stroke="{p.l}" stroke-width="8" stroke-linecap="round" opacity=".6"/>'
    return s


def pencil(p: P) -> str:
    return (
        f'<g transform="rotate(45 100 100)"><rect x="80" y="30" width="40" height="120" fill="{p.b}" {_o(p)}/>'
        f'<rect x="80" y="10" width="40" height="24" rx="6" fill="{p.a}" {_o(p)}/><rect x="80" y="30" width="40" height="10" fill="{p.l}" {_o(p, 4)}/>'
        f'<polygon points="80,150 120,150 100,192" fill="#f3d7a8" {_o(p)}/><polygon points="92,176 108,176 100,192" fill="{p.k}"/>'
        f'<line x1="93" y1="42" x2="93" y2="148" stroke="{p.k}" stroke-width="3" opacity=".3"/><line x1="107" y1="42" x2="107" y2="148" stroke="{p.k}" stroke-width="3" opacity=".3"/></g>'
    )


def palette_paint(p: P) -> str:
    s = f'<path d="M100 14 Q186 14 190 90 Q192 140 150 140 Q126 140 130 162 Q134 190 100 190 Q14 188 12 100 Q14 14 100 14 Z" fill="{p.l}" {_o(p)}/>'
    s += f'<circle cx="150" cy="112" r="14" fill="{p.k}" opacity=".0"/><ellipse cx="146" cy="116" rx="14" ry="12" fill="{p.k}" opacity=".15"/>'
    for x, y, c in (
        (58, 60, p.a),
        (102, 44, p.b),
        (146, 62, p.c),
        (46, 110, "#4cc26a"),
        (70, 152, "#7a55d6"),
    ):
        s += f'<circle cx="{x}" cy="{y}" r="17" fill="{c}" {_o(p, 4)}/>'
    return s


def stars_cluster(p: P) -> str:
    return (
        f'<polygon points="{star(80, 110, 70, 30)}" fill="{p.b}" {_o(p)}/>'
        f'<polygon points="{star(156, 50, 34, 14)}" fill="{p.a}" {_o(p, 5)}/><polygon points="{star(160, 150, 24, 10)}" fill="{p.c}" {_o(p, 4)}/>'
    )


def lips(p: P) -> str:
    return (
        f'<path d="M10 100 Q40 60 80 70 Q100 76 100 80 Q100 76 120 70 Q160 60 190 100 Q150 150 100 150 Q50 150 10 100 Z" fill="{p.a}" {_o(p)}/>'
        f'<path d="M14 100 Q60 108 100 104 Q140 108 186 100" fill="none" stroke="{p.k}" stroke-width="5"/>'
        f'<path d="M60 120 Q80 132 104 130" fill="none" stroke="{p.l}" stroke-width="6" stroke-linecap="round" opacity=".5"/>'
    )


def dress(p: P) -> str:
    s = f'<path d="M76 20 L90 20 L100 40 L110 20 L124 20 L124 60 Q116 80 120 96 L170 186 L30 186 L80 96 Q84 80 76 60 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M80 96 L120 96" stroke="{p.b}" stroke-width="10"/>'
    return s


def cupcake(p: P) -> str:
    s = f'<path d="M42 110 L158 110 L144 186 L56 186 Z" fill="{p.b}" {_o(p)}/>'
    for x in (64, 86, 108, 130):
        s += f'<line x1="{x}" y1="112" x2="{x - 4 + (x - 100) * 0.1}" y2="184" stroke="{p.k}" stroke-width="3" opacity=".35"/>'
    s += f'<path d="M30 112 Q24 80 60 76 Q60 40 100 40 Q140 40 140 76 Q176 80 170 112 Z" fill="{p.l}" {_o(p)}/>'
    s += f'<circle cx="100" cy="30" r="14" fill="{p.a}" {_o(p, 4)}/>'
    for x, y, c in ((70, 90, p.a), (104, 66, p.c), (132, 96, "#4cc26a"), (90, 100, p.c)):
        s += f'<rect x="{x}" y="{y}" width="12" height="4" rx="2" fill="{c}" transform="rotate(30 {x} {y})"/>'
    return s


def rolling_pin(p: P) -> str:
    return (
        f'<g transform="rotate(-20 100 100)"><rect x="46" y="76" width="108" height="48" rx="10" fill="{p.b}" {_o(p)}/>'
        f'<rect x="8" y="92" width="40" height="16" rx="8" fill="{p.a}" {_o(p, 5)}/><rect x="152" y="92" width="40" height="16" rx="8" fill="{p.a}" {_o(p, 5)}/></g>'
    )


def diner_plate(p: P) -> str:
    s = f'<circle cx="100" cy="100" r="90" fill="{p.l}" {_o(p)}/><circle cx="100" cy="100" r="66" fill="none" stroke="{p.c}" stroke-width="8"/>'
    s += f'<circle cx="100" cy="100" r="80" fill="none" stroke="{p.c}" stroke-width="3"/>'
    return s


def coffee(p: P) -> str:
    s = f'<path d="M150 90 Q186 90 184 118 Q182 144 146 140" fill="none" stroke="{p.k}" stroke-width="14"/>'
    s += f'<path d="M30 70 L160 70 L150 166 Q148 184 130 184 L60 184 Q42 184 40 166 Z" fill="{p.l}" {_o(p)}/>'
    s += f'<rect x="36" y="100" width="118" height="22" fill="{p.a}"/><path d="M30 70 L160 70 L150 166 Q148 184 130 184 L60 184 Q42 184 40 166 Z" fill="none" {_o(p)}/>'
    for x in (70, 100, 130):
        s += f'<path d="M{x} 54 q-10 -14 0 -26 q10 -12 0 -24" fill="none" stroke="{p.b}" stroke-width="6" stroke-linecap="round"/>'
    return s


def mask_hero(p: P) -> str:
    return (
        f'<path d="M6 80 Q40 50 100 80 Q160 50 194 80 Q190 140 140 136 Q116 132 100 114 Q84 132 60 136 Q10 140 6 80 Z" fill="{p.a}" {_o(p)}/>'
        f'<path d="M36 94 Q56 78 80 96 Q58 110 36 94 Z" fill="{p.l}"/><path d="M164 94 Q144 78 120 96 Q142 110 164 94 Z" fill="{p.l}"/>'
    )


def spy_glasses(p: P) -> str:
    return (
        f'<path d="M10 80 L190 80" stroke="{p.k}" stroke-width="8"/>'
        f'<path d="M20 80 L90 80 Q90 130 56 130 Q20 130 20 80 Z" fill="{p.a}" {_o(p)}/><path d="M110 80 L180 80 Q180 130 146 130 Q110 130 110 80 Z" fill="{p.a}" {_o(p)}/>'
        f'<path d="M32 90 Q40 110 60 114" fill="none" stroke="{p.l}" stroke-width="5" stroke-linecap="round" opacity=".6"/>'
    )


def ghost_hunter(p: P) -> str:
    """A thermometer dropping into the blue: a cold spot."""
    s = f'<rect x="80" y="10" width="40" height="140" rx="20" fill="{p.l}" {_o(p)}/>'
    s += f'<circle cx="100" cy="160" r="32" fill="{p.c}" {_o(p)}/><rect x="92" y="90" width="16" height="70" fill="{p.c}"/>'
    for y in range(30, 130, 20):
        s += f'<line x1="120" y1="{y}" x2="136" y2="{y}" stroke="{p.k}" stroke-width="4"/>'
    return s


def world_map_pin(p: P) -> str:
    return (
        f'<path d="M100 196 Q40 120 40 76 Q40 16 100 16 Q160 16 160 76 Q160 120 100 196 Z" fill="{p.a}" {_o(p)}/>'
        f'<circle cx="100" cy="74" r="24" fill="{p.l}" {_o(p, 5)}/>'
    )


def curtain(p: P) -> str:
    s = f'<rect x="0" y="0" width="200" height="22" fill="{p.b}" {_o(p, 5)}/>'
    s += f'<path d="M0 22 L90 22 Q70 110 90 190 Q40 196 0 190 Z" fill="{p.a}" {_o(p)}/><path d="M200 22 L110 22 Q130 110 110 190 Q160 196 200 190 Z" fill="{p.a}" {_o(p)}/>'
    for x in (20, 44, 66):
        s += f'<path d="M{x} 26 Q{x - 6} 110 {x + 4} 186" fill="none" stroke="{p.k}" stroke-width="3" opacity=".35"/><path d="M{200 - x} 26 Q{206 - x} 110 {196 - x} 186" fill="none" stroke="{p.k}" stroke-width="3" opacity=".35"/>'
    return s


def pizza(p: P) -> str:
    return (
        f'<path d="M100 190 L20 40 Q100 4 180 40 Z" fill="{p.b}" {_o(p)}/><path d="M24 46 Q100 12 176 46 L166 58 Q100 28 34 58 Z" fill="#d08a3a"/>'
        f'<circle cx="84" cy="78" r="14" fill="{p.a}"/><circle cx="120" cy="96" r="13" fill="{p.a}"/><circle cx="98" cy="132" r="12" fill="{p.a}"/>'
    )


# ---------------------------------------------------------------- more, for the networks


def stanchions(p: P) -> str:
    """Two brass posts with a velvet rope swag."""
    s = ""
    for x in (30, 170):
        s += f'<rect x="{x - 7}" y="60" width="14" height="112" fill="{p.b}" {_o(p, 4)}/>'
        s += f'<ellipse cx="{x}" cy="176" rx="28" ry="9" fill="{p.b}" {_o(p, 4)}/><circle cx="{x}" cy="52" r="13" fill="{p.b}" {_o(p, 4)}/>'
    s += f'<path d="M36 70 Q100 150 164 70" fill="none" stroke="{p.k}" stroke-width="20" stroke-linecap="round"/>'
    s += f'<path d="M36 70 Q100 150 164 70" fill="none" stroke="{p.a}" stroke-width="13" stroke-linecap="round"/>'
    s += '<path d="M60 96 Q100 128 140 96" fill="none" stroke="#fff" stroke-width="3" opacity=".35"/>'
    return s


def projector(p: P) -> str:
    s = f'<polygon points="150,86 200,40 200,160 150,114" fill="{p.b}" opacity=".45"/>'
    for cx, r in ((58, 32), (112, 26)):
        s += f'<circle cx="{cx}" cy="{48 - (r - 26)}" r="{r}" fill="{p.a}" {_o(p, 5)}/><circle cx="{cx}" cy="{48 - (r - 26)}" r="{r * 0.3:.0f}" fill="{p.k}"/>'
    s += f'<rect x="20" y="78" width="112" height="62" rx="8" fill="{p.k}"/>'
    s += f'<rect x="130" y="88" width="24" height="42" rx="4" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<path d="M40 140 L26 190 M112 140 L126 190 M76 140 L76 190" stroke="{p.k}" stroke-width="7" stroke-linecap="round"/>'
    return s


def fireplace(p: P) -> str:
    s = f'<rect x="14" y="40" width="172" height="150" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="4" y="26" width="192" height="22" rx="4" fill="{p.b}" {_o(p, 5)}/>'
    for y in range(64, 190, 22):
        off = 0 if (y // 22) % 2 else 22
        for x in range(14 + off, 186, 44):
            s += f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y + 22}" stroke="{p.k}" stroke-width="2" opacity=".35"/>'
        s += f'<line x1="14" y1="{y}" x2="186" y2="{y}" stroke="{p.k}" stroke-width="2" opacity=".35"/>'
    s += f'<path d="M46 190 L46 108 Q46 80 100 80 Q154 80 154 108 L154 190 Z" fill="{p.k}"/>'
    s += centred(campfire(P(a="#ff7b00", b="#ffd166", k=p.k)), 100, 150, 86)
    return s


def teacup(p: P) -> str:
    s = f'<ellipse cx="100" cy="170" rx="86" ry="16" fill="{p.l}" {_o(p)}/>'
    s += f'<path d="M150 96 Q190 96 186 122 Q182 146 146 142" fill="none" stroke="{p.k}" stroke-width="14"/><path d="M150 96 Q190 96 186 122 Q182 146 146 142" fill="none" stroke="{p.l}" stroke-width="6"/>'
    s += f'<path d="M30 80 L170 80 Q166 152 100 162 Q34 152 30 80 Z" fill="{p.l}" {_o(p)}/>'
    s += f'<path d="M36 100 Q100 116 164 100" fill="none" stroke="{p.a}" stroke-width="7"/>'
    s += f'<ellipse cx="100" cy="80" rx="70" ry="12" fill="{p.b}" {_o(p, 5)}/>'
    for x in (72, 100, 128):
        s += f'<path d="M{x} 60 q-10 -14 0 -28 q10 -14 0 -28" fill="none" stroke="{p.l}" stroke-width="6" stroke-linecap="round" opacity=".8"/>'
    return s


def keg(p: P) -> str:
    s = f'<path d="M150 36 Q170 10 188 18" fill="none" stroke="{p.k}" stroke-width="7" stroke-linecap="round"/>'
    s += centred(sparkle(p, p.b), 188, 18, 40)
    s += f'<path d="M40 40 Q26 110 40 180 L160 180 Q174 110 160 40 Z" fill="{p.a}" {_o(p)}/>'
    for y in (58, 162):
        s += (
            f'<path d="M36 {y} Q100 {y + 8} 164 {y}" fill="none" stroke="{p.k}" stroke-width="10"/>'
        )
    for x in (70, 100, 130):
        s += f'<path d="M{x} 44 Q{x + (x - 100) * 0.12} 110 {x} 176" fill="none" stroke="{p.k}" stroke-width="3" opacity=".45"/>'
    s += f'<rect x="64" y="92" width="72" height="40" rx="4" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<polygon points="104,96 84,116 98,116 92,130 114,108 100,108 106,96" fill="{p.k}"/>'
    return s


def crescent(p: P) -> str:
    return (
        f'<path d="M130 16 A90 90 0 1 0 184 150 A74 74 0 1 1 130 16 Z" fill="{p.l}" {_o(p)}/>'
        f'<circle cx="64" cy="120" r="10" fill="{p.b}" opacity=".45"/><circle cx="90" cy="162" r="7" fill="{p.b}" opacity=".45"/><circle cx="58" cy="76" r="6" fill="{p.b}" opacity=".45"/>'
    )


def spit_mug(p: P) -> str:
    s = f'<path d="M126 96 Q160 96 158 122 Q156 148 122 144" fill="none" stroke="{p.k}" stroke-width="12"/>'
    s += f'<g transform="rotate(-24 80 130)"><path d="M30 80 L130 80 L122 176 Q120 188 106 188 L54 188 Q40 188 38 176 Z" fill="{p.a}" {_o(p)}/></g>'
    for x, y, r in (
        (112, 40, 12),
        (146, 26, 9),
        (168, 52, 11),
        (136, 64, 7),
        (180, 20, 6),
        (156, 84, 6),
        (190, 70, 5),
    ):
        s += f'<circle cx="{x}" cy="{y}" r="{r}" fill="{p.c}" {_o(p, 3)}/>'
    return s


def galaxy(p: P) -> str:
    rng = random.Random(11)
    s = f'<circle cx="100" cy="100" r="96" fill="{p.k}"/>'
    for arm in range(2):
        for i in range(70):
            t = i / 70 * 3.4
            r = 8 + t * 24
            a = t + arm * math.pi
            x, y = (
                100 + r * math.cos(a) + rng.uniform(-6, 6),
                100 + r * math.sin(a) * 0.62 + rng.uniform(-5, 5),
            )
            s += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rng.uniform(1.2, 3.4):.1f}" fill="{(p.a, p.b, p.l)[i % 3]}" opacity="{rng.uniform(0.5, 1):.2f}"/>'
    s += f'<ellipse cx="100" cy="100" rx="22" ry="14" fill="{p.l}" opacity=".9"/>'
    for _ in range(30):
        s += f'<circle cx="{rng.uniform(20, 180):.0f}" cy="{rng.uniform(20, 180):.0f}" r="{rng.uniform(0.8, 1.8):.1f}" fill="#fff" opacity=".7"/>'
    return s


def lighthouse(p: P) -> str:
    s = f'<polygon points="100,62 200,30 200,94" fill="{p.b}" opacity=".45"/><polygon points="100,62 0,30 0,94" fill="{p.b}" opacity=".3"/>'
    s += f'<path d="M78 186 L86 80 L114 80 L122 186 Z" fill="{p.l}" {_o(p)}/>'
    for y in (100, 134, 166):
        s += f'<path d="M{86 - (y - 80) * 0.08:.0f} {y} L{114 + (y - 80) * 0.08:.0f} {y} L{115 + (y + 14 - 80) * 0.08:.0f} {y + 14} L{85 - (y + 14 - 80) * 0.08:.0f} {y + 14} Z" fill="{p.a}"/>'
    s += f'<rect x="80" y="48" width="40" height="32" rx="4" fill="{p.b}" {_o(p, 5)}/><path d="M76 48 L100 26 L124 48 Z" fill="{p.a}" {_o(p, 5)}/>'
    s += f'<rect x="70" y="80" width="60" height="8" fill="{p.k}"/><rect x="58" y="184" width="84" height="12" rx="4" fill="{p.k}"/>'
    return s


def padlock(p: P) -> str:
    s = f'<path d="M56 96 L56 64 Q56 18 100 18 Q144 18 144 64 L144 96" fill="none" stroke="{p.k}" stroke-width="26"/>'
    s += f'<path d="M56 96 L56 64 Q56 18 100 18 Q144 18 144 64 L144 96" fill="none" stroke="{p.l}" stroke-width="12"/>'
    s += f'<rect x="30" y="90" width="140" height="102" rx="16" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M100 118 A16 16 0 0 1 108 148 L114 172 L86 172 L92 148 A16 16 0 0 1 100 118 Z" fill="{p.k}"/>'
    return s


def turntable(p: P) -> str:
    s = f'<rect x="6" y="20" width="188" height="160" rx="14" fill="{p.b}" {_o(p)}/>'
    s += centred(vinyl(P(a=p.a, l=p.l, k=p.k)), 84, 100, 150)
    s += f'<circle cx="166" cy="44" r="12" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<path d="M166 44 L166 116 L120 146" fill="none" stroke="{p.k}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>'
    s += f'<path d="M166 44 L166 116 L120 146" fill="none" stroke="{p.l}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
    s += f'<rect x="108" y="140" width="22" height="14" rx="3" fill="{p.l}" {_o(p, 3)} transform="rotate(-34 119 147)"/>'
    return s


def lantern(p: P) -> str:
    s = f'<circle cx="100" cy="110" r="84" fill="{p.b}" opacity=".25"/>'
    s += f'<path d="M84 16 Q100 4 116 16" fill="none" stroke="{p.k}" stroke-width="7"/>'
    s += f'<path d="M70 30 L130 30 L122 50 L78 50 Z" fill="{p.k}"/>'
    s += f'<path d="M72 50 L128 50 L136 150 L64 150 Z" fill="{p.b}" {_o(p)}/>'
    s += f'<path d="M100 72 Q116 96 110 116 Q106 130 100 130 Q94 130 90 116 Q84 96 100 72 Z" fill="{p.l}"/>'
    s += f'<line x1="100" y1="50" x2="100" y2="150" stroke="{p.k}" stroke-width="4"/><line x1="68" y1="100" x2="132" y2="100" stroke="{p.k}" stroke-width="4"/>'
    s += f'<rect x="56" y="150" width="88" height="18" rx="4" fill="{p.k}"/>'
    return s


def drum(p: P) -> str:
    s = f'<line x1="40" y1="20" x2="100" y2="80" stroke="{p.b}" stroke-width="9" stroke-linecap="round"/><line x1="160" y1="20" x2="100" y2="80" stroke="{p.b}" stroke-width="9" stroke-linecap="round"/>'
    s += (
        f'<circle cx="40" cy="20" r="9" fill="{p.b}"/><circle cx="160" cy="20" r="9" fill="{p.b}"/>'
    )
    s += f'<path d="M20 90 L20 160 Q100 196 180 160 L180 90" fill="{p.a}" {_o(p)}/>'
    zig = " ".join(f"L{20 + i * 20} {100 if i % 2 else 158}" for i in range(9))
    s += f'<path d="M20 100 {zig}" fill="none" stroke="{p.l}" stroke-width="5"/>'
    s += f'<ellipse cx="100" cy="90" rx="80" ry="22" fill="{p.l}" {_o(p)}/>'
    return s


def gavel(p: P) -> str:
    s = f'<rect x="30" y="160" width="110" height="24" rx="6" fill="{p.b}" {_o(p, 5)}/>'
    s += f'<g transform="rotate(-40 110 90)"><rect x="104" y="80" width="18" height="110" rx="8" fill="{p.b}" {_o(p, 5)}/>'
    s += f'<rect x="62" y="40" width="102" height="48" rx="12" fill="{p.a}" {_o(p)}/><rect x="72" y="34" width="12" height="60" rx="4" fill="{p.b}" {_o(p, 4)}/><rect x="142" y="34" width="12" height="60" rx="4" fill="{p.b}" {_o(p, 4)}/></g>'
    return s


def dome(p: P) -> str:
    s = f'<rect x="96" y="12" width="8" height="24" fill="{p.k}"/><path d="M84 40 Q100 22 116 40 Z" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<rect x="84" y="40" width="32" height="22" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<path d="M38 118 Q38 56 100 56 Q162 56 162 118 Z" fill="{p.l}" {_o(p)}/>'
    for x in (62, 82, 100, 118, 138):
        s += f'<path d="M100 58 Q{x} 80 {x} 118" fill="none" stroke="{p.k}" stroke-width="3" opacity=".5"/>'
    s += f'<rect x="30" y="118" width="140" height="14" fill="{p.l}" {_o(p, 4)}/>'
    for x in range(40, 170, 20):
        s += f'<rect x="{x}" y="132" width="10" height="40" fill="{p.l}" {_o(p, 3)}/>'
    s += f'<rect x="20" y="172" width="160" height="16" fill="{p.l}" {_o(p, 4)}/>'
    return s


def sunny_window(p: P) -> str:
    s = f'<rect x="30" y="20" width="140" height="150" rx="70" fill="{p.c}" {_o(p)}/>'
    s += f'<circle cx="100" cy="92" r="30" fill="{p.b}"/>'
    s += f'<path d="M30 90 L170 90 M100 20 L100 170" stroke="{p.l}" stroke-width="10"/>'
    s += f'<rect x="30" y="20" width="140" height="150" rx="70" fill="none" stroke="{p.l}" stroke-width="10"/>'
    s += f'<rect x="30" y="20" width="140" height="150" rx="70" fill="none" {_o(p)}/>'
    s += f'<rect x="14" y="166" width="172" height="16" rx="4" fill="{p.l}" {_o(p, 5)}/>'
    s += f'<path d="M150 166 Q140 130 156 120 Q170 136 162 166 Z" fill="#3f9a4a" {_o(p, 3)}/><path d="M44 166 Q36 140 50 132 Q62 146 56 166 Z" fill="#3f9a4a" {_o(p, 3)}/>'
    return s


def flashbulb(p: P) -> str:
    s = centred(sparkle(p, p.b), 100, 64, 140)
    s += f'<rect x="84" y="100" width="32" height="50" fill="{p.l}" {_o(p, 5)}/>'
    s += f'<path d="M40 150 L160 150 L150 190 L50 190 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M20 150 Q100 110 180 150" fill="{p.l}" {_o(p, 5)}/>'
    return s


def proscenium(p: P) -> str:
    s = f'<path d="M6 190 L6 40 Q100 -6 194 40 L194 190 L168 190 L168 64 Q100 30 32 64 L32 190 Z" fill="{p.b}" {_o(p)}/>'
    s += f'<path d="M32 64 Q100 30 168 64 L168 190 L32 190 Z" fill="{p.k}"/>'
    s += f'<path d="M32 64 Q66 50 96 50 Q80 120 96 190 L32 190 Z" fill="{p.a}"/><path d="M168 64 Q134 50 104 50 Q120 120 104 190 L168 190 Z" fill="{p.a}"/>'
    s += f'<circle cx="100" cy="24" r="10" fill="{p.l}" {_o(p, 4)}/>'
    return s


def rocking_chair(p: P) -> str:
    s = f'<path d="M20 176 Q100 196 180 170" fill="none" stroke="{p.k}" stroke-width="16" stroke-linecap="round"/><path d="M20 176 Q100 196 180 170" fill="none" stroke="{p.a}" stroke-width="8" stroke-linecap="round"/>'
    s += f'<path d="M56 180 L50 26 M124 182 L118 26" stroke="{p.k}" stroke-width="16" stroke-linecap="round"/><path d="M56 180 L50 26 M124 182 L118 26" stroke="{p.a}" stroke-width="8" stroke-linecap="round"/>'
    for y in (40, 64, 88):
        s += (
            f'<line x1="50" y1="{y}" x2="120" y2="{y}" stroke="{p.a}" stroke-width="9" {_o(p, 0)}/>'
        )
    s += f'<rect x="46" y="110" width="116" height="16" rx="6" fill="{p.a}" {_o(p, 5)}/><path d="M156 126 L162 176" stroke="{p.k}" stroke-width="10" stroke-linecap="round"/>'
    return s


def box_rocket(p: P) -> str:
    s = f'<path d="M100 196 Q80 170 86 150 L114 150 Q120 170 100 196 Z" fill="{p.a}"/><path d="M100 184 Q92 168 94 154 L106 154 Q108 168 100 184 Z" fill="{p.b}"/>'
    s += f'<polygon points="56,110 20,160 56,150" fill="{p.a}" {_o(p, 5)}/><polygon points="144,110 180,160 144,150" fill="{p.a}" {_o(p, 5)}/>'
    s += f'<rect x="56" y="60" width="88" height="92" fill="#c8964f" {_o(p)}/>'
    s += f'<polygon points="56,60 100,10 144,60" fill="{p.c}" {_o(p)}/>'
    s += f'<circle cx="100" cy="96" r="18" fill="{p.l}" {_o(p, 5)}/><path d="M60 128 L140 128" stroke="{p.k}" stroke-width="4" stroke-dasharray="8 6"/>'
    return s


def alarm_clock(p: P) -> str:
    s = f'<circle cx="46" cy="40" r="26" fill="{p.b}" {_o(p)}/><circle cx="154" cy="40" r="26" fill="{p.b}" {_o(p)}/>'
    s += f'<path d="M60 180 L44 196 M140 180 L156 196" stroke="{p.k}" stroke-width="10" stroke-linecap="round"/>'
    s += f'<circle cx="100" cy="110" r="78" fill="{p.a}" {_o(p)}/><circle cx="100" cy="110" r="62" fill="{p.l}" {_o(p, 4)}/>'
    s += f'<line x1="100" y1="110" x2="100" y2="66" stroke="{p.k}" stroke-width="8" stroke-linecap="round"/><line x1="100" y1="110" x2="136" y2="110" stroke="{p.k}" stroke-width="8" stroke-linecap="round"/>'
    s += f'<circle cx="100" cy="110" r="7" fill="{p.k}"/>'
    return s


def cocktails(p: P) -> str:
    def glass(x, rot, c):
        return (
            f'<g transform="rotate({rot} {x} 180)"><path d="M{x - 46} 40 L{x + 46} 40 L{x} 100 Z" fill="{c}" {_o(p, 5)}/>'
            f'<line x1="{x}" y1="100" x2="{x}" y2="170" stroke="{p.k}" stroke-width="7"/><rect x="{x - 28}" y="168" width="56" height="10" rx="5" fill="{p.k}"/>'
            f'<circle cx="{x + 20}" cy="40" r="10" fill="#e63946" {_o(p, 3)}/></g>'
        )

    return glass(70, -12, p.a) + glass(130, 12, p.b)


def stethoscope(p: P) -> str:
    s = f'<path d="M50 20 L50 80 Q50 130 100 130 Q150 130 150 80 L150 20" fill="none" stroke="{p.k}" stroke-width="14"/>'
    s += f'<path d="M50 20 L50 80 Q50 130 100 130 Q150 130 150 80 L150 20" fill="none" stroke="{p.a}" stroke-width="7"/>'
    s += f'<path d="M100 130 L100 150 Q100 184 140 184 Q170 184 170 160" fill="none" stroke="{p.k}" stroke-width="12"/><path d="M100 130 L100 150 Q100 184 140 184 Q170 184 170 160" fill="none" stroke="{p.a}" stroke-width="6"/>'
    s += f'<circle cx="170" cy="146" r="20" fill="{p.l}" {_o(p, 6)}/><circle cx="170" cy="146" r="9" fill="{p.a}"/>'
    s += (
        f'<circle cx="50" cy="16" r="9" fill="{p.k}"/><circle cx="150" cy="16" r="9" fill="{p.k}"/>'
    )
    return s


def milkshake(p: P) -> str:
    s = f'<line x1="118" y1="10" x2="100" y2="76" stroke="{p.c}" stroke-width="12" stroke-linecap="round"/><line x1="118" y1="10" x2="100" y2="76" stroke="{p.l}" stroke-width="4" stroke-dasharray="8 8"/>'
    s += f'<g fill="{p.l}" {_o(p, 5)}><circle cx="70" cy="70" r="24"/><circle cx="100" cy="56" r="28"/><circle cx="130" cy="70" r="24"/></g>'
    s += f'<circle cx="100" cy="30" r="12" fill="#d62828" {_o(p, 4)}/>'
    s += f'<path d="M44 80 L156 80 L136 176 L64 176 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M50 104 L150 104" stroke="{p.l}" stroke-width="6" opacity=".6"/><rect x="60" y="176" width="80" height="14" rx="5" fill="{p.l}" {_o(p, 5)}/>'
    return s


def bus(p: P) -> str:
    s = f'<rect x="30" y="10" width="140" height="170" rx="16" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="44" y="26" width="112" height="44" rx="6" fill="{p.c}" {_o(p, 4)}/><rect x="44" y="84" width="112" height="44" rx="6" fill="{p.c}" {_o(p, 4)}/>'
    s += f'<rect x="60" y="138" width="80" height="16" rx="3" fill="{p.l}" {_o(p, 3)}/>'
    s += f'<circle cx="54" cy="160" r="8" fill="{p.b}"/><circle cx="146" cy="160" r="8" fill="{p.b}"/>'
    s += f'<rect x="40" y="180" width="26" height="14" fill="{p.k}"/><rect x="134" y="180" width="26" height="14" fill="{p.k}"/>'
    return s


def cabinet(p: P) -> str:
    s = f'<rect x="30" y="10" width="140" height="180" rx="8" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M22 14 L178 14 L170 4 L30 4 Z" fill="{p.a}" {_o(p, 4)}/>'
    s += (
        f'<rect x="42" y="24" width="116" height="150" fill="{p.c}" fill-opacity=".35" {_o(p, 4)}/>'
    )
    for y in (72, 122):
        s += f'<line x1="42" y1="{y}" x2="158" y2="{y}" stroke="{p.k}" stroke-width="5"/>'
    s += f'<circle cx="70" cy="56" r="14" fill="{p.b}" {_o(p, 3)}/><rect x="98" y="40" width="20" height="30" rx="4" fill="#7fc8a9" {_o(p, 3)}/><path d="M130 70 L144 40 L152 70 Z" fill="{p.l}" {_o(p, 3)}/>'
    s += f'<path d="M58 120 Q70 96 86 120 Z" fill="#f4a261" {_o(p, 3)}/><circle cx="118" cy="106" r="14" fill="{p.l}" {_o(p, 3)}/><path d="M112 102 L124 110" stroke="{p.k}" stroke-width="2"/>'
    s += f'<rect x="60" y="140" width="36" height="30" rx="3" fill="#b5838d" {_o(p, 3)}/><path d="M120 170 Q130 138 144 170 Z" fill="{p.b}" {_o(p, 3)}/>'
    s += f'<circle cx="100" cy="186" r="4" fill="{p.k}"/>'
    return s


def twister(p: P) -> str:
    s = ""
    for i in range(9):
        y = 20 + i * 18
        w = 90 - i * 9
        s += f'<ellipse cx="{100 + math.sin(i * 0.8) * 10:.0f}" cy="{y}" rx="{w}" ry="{10 - i * 0.5:.1f}" fill="none" stroke="{p.a}" stroke-width="{9 - i * 0.5:.1f}" stroke-linecap="round"/>'
    s += f'<path d="M10 190 Q100 170 190 190" fill="none" stroke="{p.a}" stroke-width="8" stroke-linecap="round" opacity=".6"/>'
    return s


def big_top(p: P) -> str:
    s = f'<line x1="100" y1="4" x2="100" y2="40" stroke="{p.k}" stroke-width="6"/><path d="M100 6 L128 14 L100 24 Z" fill="{p.b}" {_o(p, 3)}/>'
    s += f'<path d="M100 34 L184 110 L16 110 Z" fill="{p.l}" {_o(p)}/>'
    for k in range(-3, 4, 2):
        s += f'<path d="M100 34 L{100 + k * 24} 110 L{100 + (k + 1) * 24} 110 Z" fill="{p.a}"/>'
    s += f'<path d="M100 34 L184 110 L16 110 Z" fill="none" {_o(p)}/>'
    s += f'<rect x="24" y="110" width="152" height="80" fill="{p.l}" {_o(p)}/>'
    for x in range(24, 176, 30):
        s += f'<rect x="{x}" y="110" width="15" height="80" fill="{p.a}"/>'
    s += f'<rect x="24" y="110" width="152" height="80" fill="none" {_o(p)}/>'
    s += f'<path d="M78 190 L78 146 Q100 124 122 146 L122 190 Z" fill="{p.k}"/>'
    s += f'<path d="M16 110 Q40 128 58 110 Q79 128 100 110 Q121 128 142 110 Q160 128 184 110" fill="{p.b}" {_o(p, 4)}/>'
    return s


def seats(p: P) -> str:
    s = ""
    for row, (y, n, sc) in enumerate(((86, 4, 1), (132, 5, 1))):
        for i in range(n):
            x = 100 + (i - (n - 1) / 2) * 38
            s += (
                f'<rect x="{x - 16}" y="{y - 30}" width="32" height="40" rx="10" fill="{p.a}" {_o(p, 4)}/>'
                f'<rect x="{x - 18}" y="{y + 6}" width="36" height="16" rx="6" fill="{p.a}" {_o(p, 4)}/>'
            )
    s += centred(sparkle(p, p.b), 100, 20, 40)
    return s


def jumprope(p: P) -> str:
    s = f'<path d="M36 70 Q30 190 100 190 Q170 190 164 70" fill="none" stroke="{p.k}" stroke-width="12"/>'
    s += f'<path d="M36 70 Q30 190 100 190 Q170 190 164 70" fill="none" stroke="{p.a}" stroke-width="6" stroke-dasharray="12 6"/>'
    for x in (36, 164):
        s += f'<rect x="{x - 12}" y="16" width="24" height="60" rx="12" fill="{p.b}" {_o(p, 5)}/>'
    return s


def banana_peel(p: P) -> str:
    s = f'<path d="M100 120 Q60 120 20 176 Q60 166 90 144 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M100 120 Q140 120 184 176 Q140 166 110 144 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M92 124 Q76 150 88 190 Q100 170 108 190 Q124 150 108 124 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M96 126 Q104 70 90 30 Q116 50 112 126 Z" fill="{p.l}" {_o(p)}/>'
    s += '<rect x="84" y="20" width="14" height="16" rx="4" fill="#6b4a1a" transform="rotate(-20 91 28)"/>'
    return s


def dog_cat(p: P) -> str:
    s = f'<path d="M20 70 Q16 30 44 24 Q56 40 56 60 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<circle cx="64" cy="112" r="56" fill="{p.a}" {_o(p)}/>'
    s += f'<path d="M104 70 Q104 30 118 24 Q116 46 110 70 Z" fill="{p.a}" {_o(p)}/>'
    s += f'<ellipse cx="64" cy="132" rx="28" ry="22" fill="{p.l}"/><ellipse cx="64" cy="122" rx="10" ry="7" fill="{p.k}"/>'
    s += f'<circle cx="44" cy="98" r="7" fill="{p.k}"/><circle cx="84" cy="98" r="7" fill="{p.k}"/>'
    s += f'<polygon points="128,72 136,24 160,60" fill="{p.b}" {_o(p)}/><polygon points="192,72 184,24 160,60" fill="{p.b}" {_o(p)}/>'
    s += f'<circle cx="160" cy="112" r="46" fill="{p.b}" {_o(p)}/>'
    s += f'<ellipse cx="146" cy="104" rx="6" ry="9" fill="{p.k}"/><ellipse cx="174" cy="104" rx="6" ry="9" fill="{p.k}"/>'
    s += f'<polygon points="154,122 166,122 160,130" fill="{p.a}"/><path d="M130 124 L110 118 M130 130 L110 132 M190 124 L210 118" stroke="{p.k}" stroke-width="3"/>'
    return s


def starfish(p: P) -> str:
    return (
        f'<polygon points="{star(100, 104, 94, 40)}" fill="{p.a}" {_o(p)} stroke-linejoin="round"/>'
        + "".join(
            f'<circle cx="{100 + r * math.cos(math.radians(-90 + k * 72)):.0f}" cy="{104 + r * math.sin(math.radians(-90 + k * 72)):.0f}" r="5" fill="{p.l}" opacity=".7"/>'
            for k in range(5)
            for r in (30, 52)
        )
    )


def speaker(p: P) -> str:
    s = f'<rect x="30" y="10" width="140" height="180" rx="14" fill="{p.k}"/>'
    s += f'<circle cx="100" cy="60" r="28" fill="{p.a}"/><circle cx="100" cy="60" r="10" fill="{p.k}"/>'
    s += f'<circle cx="100" cy="132" r="46" fill="{p.a}"/><circle cx="100" cy="132" r="30" fill="{p.b}"/><circle cx="100" cy="132" r="12" fill="{p.k}"/>'
    return s


def comic_panels(p: P) -> str:
    s = f'<rect x="6" y="30" width="188" height="140" fill="{p.l}" {_o(p)}/>'
    for x in (68, 132):
        s += f'<line x1="{x}" y1="30" x2="{x}" y2="170" stroke="{p.k}" stroke-width="6"/>'
    s += f'<circle cx="36" cy="120" r="18" fill="{p.a}"/><path d="M20 70 L56 70 Q60 70 60 74 L60 94 L46 94 L40 104 L40 94 L20 94 Z" fill="#fff" {_o(p, 3)}/>'
    s += f'<polygon points="{star(100, 100, 30, 14, 8)}" fill="{p.b}" {_o(p, 3)}/>'
    for y in range(44, 166, 12):
        for x in range(140, 190, 12):
            s += f'<circle cx="{x}" cy="{y}" r="3" fill="{p.c}"/>'
    return s


def dish(p: P) -> str:
    return diner_plate(p) + centred(fork_knife(P(l=p.l, k=p.k)), 100, 100, 100)


def ticker_arrows(p: P) -> str:
    s = f'<polyline points="10,150 60,110 96,130 150,60 190,40" fill="none" stroke="{p.a}" stroke-width="14" stroke-linejoin="round" stroke-linecap="round"/>'
    s += f'<polygon points="190,20 196,62 160,44" fill="{p.a}"/>'
    s += f'<polyline points="10,50 60,80 96,70 150,130 190,160" fill="none" stroke="{p.b}" stroke-width="10" stroke-linejoin="round" stroke-linecap="round" opacity=".85"/>'
    return s


def golf(p: P) -> str:
    s = f'<line x1="140" y1="20" x2="140" y2="170" stroke="{p.k}" stroke-width="6"/><path d="M140 20 L192 38 L140 56 Z" fill="{p.a}" {_o(p, 4)}/>'
    s += f'<ellipse cx="120" cy="176" rx="70" ry="14" fill="{p.b}"/>'
    s += f'<path d="M54 140 L66 140 L62 180 L58 180 Z" fill="{p.l}" {_o(p, 3)}/><circle cx="60" cy="120" r="24" fill="{p.l}" {_o(p, 5)}/>'
    for x, y in ((52, 114), (62, 108), (68, 120), (56, 126)):
        s += f'<circle cx="{x}" cy="{y}" r="2.5" fill="{p.k}" opacity=".4"/>'
    return s


def isobars(p: P) -> str:
    s = f'<circle cx="100" cy="100" r="92" fill="{p.l}" {_o(p)}/>'
    s += '<clipPath id="isoc"><circle cx="100" cy="100" r="88"/></clipPath><g clip-path="url(#isoc)" fill="none">'
    for r in (18, 38, 58, 78):
        s += f'<ellipse cx="66" cy="84" rx="{r}" ry="{r * 0.8}" stroke="{p.c}" stroke-width="4"/>'
    for r in (16, 34, 52):
        s += f'<ellipse cx="146" cy="132" rx="{r}" ry="{r * 0.8}" stroke="{p.a}" stroke-width="4"/>'
    s += "</g>"
    s += f'<circle cx="66" cy="84" r="16" fill="{p.l}"/><text x="66" y="97" font-family="Archivo Black" font-size="34" text-anchor="middle" fill="{p.c}">H</text>'
    s += f'<circle cx="146" cy="132" r="15" fill="{p.l}"/><text x="146" y="144" font-family="Archivo Black" font-size="30" text-anchor="middle" fill="{p.a}">L</text>'
    return s


def tv_house(p: P) -> str:
    """A little TV set with a roof: one house in Tube Town."""
    s = f'<polygon points="100,10 190,80 10,80" fill="{p.a}" {_o(p)}/>'
    s += f'<rect x="24" y="76" width="152" height="110" rx="14" fill="{p.b}" {_o(p)}/>'
    s += f'<rect x="38" y="90" width="96" height="80" rx="12" fill="{p.c}" {_o(p, 5)}/>'
    s += f'<circle cx="156" cy="108" r="8" fill="{p.l}" {_o(p, 3)}/><circle cx="156" cy="134" r="8" fill="{p.l}" {_o(p, 3)}/>'
    return s


SYMBOLS = {
    name: fn
    for name, fn in list(globals().items())
    if callable(fn)
    and not name.startswith("_")
    and name not in ("P", "centred", "pts", "star", "SYMBOLS")
    and fn.__module__ == __name__
}
