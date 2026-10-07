"""Classic TV: nostalgia networks and rerun channels, for stations of old
sitcoms, dramas, action shows, westerns, mysteries and sci-fi. All invented;
none borrows a real channel's name, symbol, colours or lettering."""

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
    rad,
    ribbon,
    shadow,
    star,
    svg,
    text,
)
from symbols import P, centred

SH = shadow("sh", dy=6, blur=6, opacity=0.45)
CLASSIC = "Classic TV"
LOGOS: list[tuple[str, str, str, list[str], object]] = []


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", "and")).strip("-")


def net(name: str, *tags: str):
    def add(fn):
        LOGOS.append((slug(name), name, CLASSIC, ["classic tv", *tags], fn))
        return fn

    return add


def _panel(x, y, w, h, fill, rx=18, edge=None, sw=0):
    st = f' stroke="{edge}" stroke-width="{sw}"' if edge else ""
    return f'<g filter="url(#sh)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{st}/></g>'


def _word(s, font, fill, edge=None, sw=0, weight=400, ls=0, style="normal"):
    return text(s, font, 100, weight=weight, fill=fill, stroke=edge, sw=sw, ls=ls, style=style)


def _lines(x1, x2, y, n, gap, colour, width=3, opacity=0.5):
    return "".join(
        f'<line x1="{x1}" y1="{y + i * gap}" x2="{x2}" y2="{y + i * gap}" stroke="{colour}" '
        f'stroke-width="{width}" opacity="{opacity}"/>'
        for i in range(n)
    )


# ================================================================== comedy


@net("Chuckle Channel", "comedy", "sitcoms")
def chuckle_channel():
    return L.tv_screen(
        "Chuckle",
        "CHANNEL",
        "CLASSIC COMEDY",
        screen=("#f6b93b", "#d35400"),
        band="#1e3799",
        cabinet="#f8ecd1",
        edge="#2b1a10",
        ink="#fffaf0",
        script_font="Lobster",
    )


@net("Laugh Riot", "comedy", "sitcoms")
def laugh_riot():
    d = SH + lin("lr", [(0, "#ef4444"), (1, "#991b1b")])
    body = '<g filter="url(#sh)"><rect x="46" y="66" width="420" height="380" rx="28" fill="url(#lr)" stroke="#2a0606" stroke-width="7"/></g>'
    body += fit(text("LAUGH", "Anton", 100, fill="#fff", ls=6), 86, 92, 340, 150)
    body += '<rect x="86" y="248" width="340" height="112" rx="10" fill="#fde047"/>'
    body += fit(text("RIOT", "Anton", 100, fill="#2a0606", ls=20), 120, 258, 272, 92)
    body += fit(
        text("COMEDY ALL DAY", "Oswald", 40, weight=700, fill="#fecaca", ls=10), 150, 382, 212, 30
    )
    return svg(body, d)


@net("Knee Slapper", "comedy", "sitcoms")
def knee_slapper():
    d = SH + lin("ks", [(0, "#2ec4b6"), (1, "#136f63")])
    body = _panel(40, 70, 432, 372, "url(#ks)", rx=36, edge="#0b2e2a", sw=8)
    for i in range(6):
        body += (
            f'<rect x="40" y="{94 + i * 58}" width="432" height="22" fill="#fff" opacity=".05"/>'
        )
    w1 = _word("KNEE", "Bowlby One", "#ffd23f", "#0b2e2a", 14)
    w2 = _word("SLAPPER", "Bowlby One", "#ffffff", "#0b2e2a", 14)
    body += fit(extrude(w1, 6, 8, 8, "#0b2e2a") + w1, 110, 104, 292, 128)
    body += fit(extrude(w2, 6, 8, 8, "#0b2e2a") + w2, 64, 240, 384, 116)
    body += fit(
        text("CLASSIC COMEDY", "Oswald", 40, weight=700, fill="#e8fff9", ls=8), 156, 384, 200, 30
    )
    return svg(body, d)


@net("Canned Laughter", "comedy", "sitcoms")
def canned_laughter():
    d = SH + lin("cl", [(0, "#fff7e6"), (1, "#f3dfb6")])
    body = '<g filter="url(#sh)"><ellipse cx="256" cy="256" rx="224" ry="170" fill="#b91c1c" stroke="#3b0707" stroke-width="8"/></g>'
    body += '<ellipse cx="256" cy="256" rx="200" ry="148" fill="url(#cl)" stroke="#3b0707" stroke-width="5"/>'
    body += '<ellipse cx="256" cy="256" rx="186" ry="134" fill="none" stroke="#b91c1c" stroke-width="3"/>'
    body += fit(text("Canned", "Lobster", 100, fill="#b91c1c"), 136, 132, 240, 96)
    body += fit(text("LAUGHTER", "Alfa Slab One", 100, fill="#1f2937", ls=4), 104, 232, 304, 62)
    wave = "M120 330"
    for k in range(16):
        x = 120 + k * 17
        h = (8, 18, 30, 14, 24, 36, 20, 10, 28, 40, 22, 12, 30, 16, 24, 8)[k]
        wave += f" M{x} {330 - h / 2} L{x} {330 + h / 2}"
    body += f'<path d="{wave}" stroke="#b91c1c" stroke-width="7" stroke-linecap="round"/>'
    return svg(body, d)


@net("Studio Audience", "comedy", "sitcoms", "game shows")
def studio_audience():
    d = (
        SH
        + glow("lit", "#ff2e2e", blur=10, strength=2)
        + lin("face", [(0, "#ff5a5a"), (1, "#b30000")])
    )
    body = '<g filter="url(#sh)"><rect x="30" y="120" width="452" height="272" rx="28" fill="#1b1b1f" stroke="#050506" stroke-width="6"/></g>'
    body += '<rect x="44" y="134" width="424" height="244" rx="18" fill="#2a2a30"/>'
    for x in (72, 440):
        for y in (156, 356):
            body += (
                f'<circle cx="{x}" cy="{y}" r="8" fill="#8a8f98" stroke="#111" stroke-width="3"/>'
            )
    body += '<g filter="url(#lit)"><rect x="92" y="160" width="328" height="192" rx="10" fill="url(#face)"/></g>'
    body += '<rect x="92" y="160" width="328" height="192" rx="10" fill="none" stroke="#ffd0d0" stroke-width="3" opacity=".6"/>'
    body += fit(text("STUDIO", "Oswald", 100, weight=700, fill="#fff", ls=14), 136, 178, 240, 50)
    body += fit(text("AUDIENCE", "Archivo Black", 100, fill="#fff"), 110, 240, 292, 86)
    # the stand it hangs from
    body += '<rect x="236" y="60" width="40" height="62" fill="#3a3a40" stroke="#050506" stroke-width="5"/>'
    body += '<rect x="176" y="44" width="160" height="24" rx="8" fill="#55555c" stroke="#050506" stroke-width="5"/>'
    body += fit(
        text("LIVE STUDIO CLASSICS", "Oswald", 40, weight=600, fill="#f2f2f2", ls=6),
        150,
        408,
        212,
        26,
    )
    return svg(body, d)


@net("Shenanigans", "comedy", "sitcoms")
def shenanigans():
    return L.script_card(
        "Shenanigans",
        "CLASSIC COMEDY",
        card="#7ed6df",
        card2="#22a6b3",
        edge="#1b2b34",
        ink="#fff7e6",
        script_font="Yellowtail",
        shape="boomerang",
        sub_ink="#fff7e6",
    )


@net("Hijinks", "comedy", "sitcoms")
def hijinks():
    return L.block_word(
        [("HI", "#f94144", "#fff"), ("JINKS", "#277da1", "#ffd166")],
        font="Archivo Black",
        edge="#10131a",
        tilt=-6,
        sub="CLASSIC COMEDY",
        sub_fill="#f1f1f1",
    )


@net("Wisecrack", "comedy", "sitcoms")
def wisecrack():
    d = SH + lin("wc", [(0, "#3a3d5c"), (1, "#1c1e33")])
    top = "M40 90 L472 90 L472 262 L382 250 L340 280 L300 244 L262 272 L222 238 L176 276 L140 250 L40 262 Z"
    bottom = "M40 272 L140 260 L176 286 L222 248 L262 282 L300 254 L340 290 L382 260 L472 272 L472 424 L40 424 Z"
    body = '<g filter="url(#sh)">'
    body += f'<g transform="translate(-6 -8) rotate(-2 256 176)"><path d="{top}" fill="url(#wc)" stroke="#0c0d17" stroke-width="7" stroke-linejoin="round"/></g>'
    body += f'<g transform="translate(6 8) rotate(1.5 256 346)"><path d="{bottom}" fill="#f4c542" stroke="#0c0d17" stroke-width="7" stroke-linejoin="round"/></g>'
    body += "</g>"
    body += f'<g transform="translate(-6 -8) rotate(-2 256 176)">{fit(_word("WISE", "Alfa Slab One", "#f4c542"), 110, 112, 292, 120)}</g>'
    body += f'<g transform="translate(6 8) rotate(1.5 256 346)">{fit(_word("CRACK", "Alfa Slab One", "#1c1e33"), 80, 300, 352, 106)}</g>'
    return svg(body, d)


def _houses() -> str:
    sky = '<rect x="40" y="20" width="432" height="400" fill="url(#dusk)"/>'
    sky += '<circle cx="360" cy="110" r="34" fill="#fff4c7" opacity=".9"/>'
    out = sky
    for x, w, h, roof, wall in (
        (70, 120, 150, "#8e3b46", "#f1d6a3"),
        (196, 124, 190, "#355c7d", "#fbe7c6"),
        (326, 120, 160, "#6c5b7b", "#f7d0a8"),
    ):
        base = 380
        top = base - h
        out += f'<rect x="{x}" y="{top}" width="{w}" height="{h}" fill="{wall}" stroke="#23150f" stroke-width="5"/>'
        out += f'<polygon points="{x - 10},{top} {x + w / 2},{top - 56} {x + w + 10},{top}" fill="{roof}" stroke="#23150f" stroke-width="5" stroke-linejoin="round"/>'
        for wx in (x + 18, x + w - 48):
            out += f'<rect x="{wx}" y="{top + 30}" width="30" height="34" fill="#ffd166" stroke="#23150f" stroke-width="4"/>'
        out += f'<rect x="{x + w / 2 - 16}" y="{base - 60}" width="32" height="60" fill="#5b3a29" stroke="#23150f" stroke-width="4"/>'
    out += '<rect x="40" y="380" width="432" height="60" fill="#3b4c3a"/>'
    return out


@net("Sitcom Street", "comedy", "sitcoms", "family")
def sitcom_street():
    return L.emblem(
        _houses(),
        "SITCOM STREET",
        font="Archivo Black",
        ink="#fff6e0",
        band="#c0392b",
        rim="#f6d6a8",
        edge="#23150f",
        defs=lin("dusk", [(0, "#f6a55b"), (0.6, "#e76f51"), (1, "#7a4e8c")]),
        ls=2,
    )


@net("TV Dinner", "comedy", "sitcoms", "family")
def tv_dinner():
    d = (
        SH
        + lin(
            "foil", [(0, "#f5f7f9"), (0.4, "#b9c2cb"), (0.7, "#e8ecef"), (1, "#8d98a3")], x2=1, y2=1
        )
        + lin("rib", [(0, "#e63946"), (1, "#a4161a")])
    )
    body = '<g filter="url(#sh)"><rect x="46" y="88" width="420" height="300" rx="34" fill="url(#foil)" stroke="#5c6670" stroke-width="6"/></g>'
    body += '<rect x="66" y="108" width="232" height="260" rx="22" fill="#cfd6dc" stroke="#7d8893" stroke-width="4"/>'
    body += '<rect x="312" y="108" width="134" height="124" rx="20" fill="#cfd6dc" stroke="#7d8893" stroke-width="4"/>'
    body += '<rect x="312" y="244" width="134" height="124" rx="20" fill="#cfd6dc" stroke="#7d8893" stroke-width="4"/>'
    # meatloaf with gravy, peas, mashed potatoes
    body += '<rect x="96" y="150" width="172" height="118" rx="30" fill="#7b3f24" stroke="#3b1a0c" stroke-width="5"/>'
    body += '<path d="M104 176 Q180 150 262 178 L262 196 Q180 176 104 200 Z" fill="#b5462d" opacity=".9"/>'
    for i in range(14):
        x, y = 330 + (i % 5) * 22, 136 + (i // 5) * 24
        body += (
            f'<circle cx="{x}" cy="{y}" r="10" fill="#6ab04c" stroke="#2d5a1b" stroke-width="3"/>'
        )
    body += '<path d="M330 330 Q344 272 380 282 Q420 262 430 320 Q420 350 380 346 Q340 352 330 330 Z" fill="#fff8e7" stroke="#bfa98a" stroke-width="4"/>'
    body += '<ellipse cx="382" cy="306" rx="16" ry="9" fill="#f6c343"/>'
    # the name across it on a ribbon
    body += (
        '<g filter="url(#sh)">'
        + ribbon(70, 442, 300, 104, "url(#rib)", edge="#5c0a0e", sw=5, tail=44, tail_fill="#8d0e18")
        + "</g>"
    )
    body += fit(
        text("TV Dinner", "Lobster", 100, fill="#fff8e7", stroke="#5c0a0e", sw=6), 92, 310, 328, 84
    )
    body += fit(
        text(
            "SERVED WITH CLASSIC TV",
            "Oswald",
            40,
            weight=700,
            fill="#f1f3f5",
            stroke="#2b2f36",
            sw=8,
            ls=5,
        ),
        128,
        428,
        256,
        32,
    )
    return svg(body, d)


@net("Shag Carpet TV", "comedy", "sitcoms", "70s")
def shag_carpet_tv():
    rng = random.Random(7)
    d = SH + lin("shag", [(0, "#e76f51"), (0.5, "#d35400"), (1, "#9c3d10")])
    body = '<g filter="url(#sh)"><rect x="34" y="60" width="444" height="392" rx="46" fill="url(#shag)" stroke="#3a1a08" stroke-width="7"/></g>'
    strands = ""
    for _ in range(520):
        x, y = rng.uniform(50, 462), rng.uniform(76, 436)
        a = math.radians(rng.uniform(55, 125))
        l = rng.uniform(10, 20)
        c = rng.choice(("#f4a261", "#b5461a", "#e9c46a", "#8a3410"))
        strands += f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x + l * math.cos(a):.0f}" y2="{y + l * math.sin(a):.0f}" stroke="{c}" stroke-width="3" stroke-linecap="round" opacity=".75"/>'
    body += f'<clipPath id="shc"><rect x="40" y="66" width="432" height="380" rx="40"/></clipPath><g clip-path="url(#shc)">{strands}</g>'
    body += '<rect x="68" y="128" width="376" height="176" rx="88" fill="#f4e3b5" stroke="#3a1a08" stroke-width="7"/>'
    w = _word("SHAG", "Shrikhand", "#6b3e1a")
    body += fit(w, 98, 140, 316, 92)
    body += fit(_word("CARPET", "Shrikhand", "#d35400"), 128, 226, 256, 62)
    body += '<circle cx="256" cy="368" r="58" fill="#6a994e" stroke="#3a1a08" stroke-width="7"/>'
    body += fit(_word("TV", "Chango", "#f4e3b5"), 216, 342, 80, 52)
    return svg(body, d)


@net("Belly Laugh", "comedy", "sitcoms")
def belly_laugh():
    centre = '<ellipse cx="256" cy="178" rx="120" ry="84" fill="#fff" stroke="#1b1f3b" stroke-width="7"/>'
    centre += '<polygon points="196,246 176,300 240,254" fill="#fff" stroke="#1b1f3b" stroke-width="7" stroke-linejoin="round"/>'
    centre += '<ellipse cx="256" cy="178" rx="113" ry="77" fill="#fff"/>'
    centre += fit(text("HA HA!", "Luckiest Guy", 100, fill="#ff6b35"), 164, 138, 184, 80)
    return L.roundel(
        centre,
        "BELLY LAUGH",
        font="Archivo Black",
        ink="#fff",
        disc="#4361ee",
        rim="#ffd166",
        edge="#1b1f3b",
        bar="#1b1f3b",
        bar_y=300,
        ls=2,
    )


@net("Giggle Box", "comedy", "sitcoms", "family")
def giggle_box():
    mark = '<rect x="-74" y="-58" width="148" height="112" rx="26" fill="#fff" stroke="#3b0a1f" stroke-width="8"/>'
    mark += '<rect x="-56" y="-42" width="112" height="80" rx="16" fill="#ffd1dc"/>'
    mark += '<path d="M-30 -2 Q0 30 30 -2" fill="none" stroke="#c2185b" stroke-width="10" stroke-linecap="round"/>'
    mark += '<circle cx="-22" cy="-20" r="7" fill="#c2185b"/><circle cx="22" cy="-20" r="7" fill="#c2185b"/>'
    mark += '<path d="M-30 -82 L-6 -58 M30 -82 L6 -58" stroke="#3b0a1f" stroke-width="8" stroke-linecap="round"/>'
    return L.tile_word(
        f'<g transform="translate(256 156)">{mark}</g>',
        "GIGGLE BOX",
        font="Fredoka",
        ink="#fff",
        edge="#3b0a1f",
        tile="#ff5c8a",
        tile2="#c2185b",
        weight=700,
        sub="CLASSIC COMEDY",
        sub_ink="#ffd1dc",
        shape="square",
        ring="#fff",
    )


@net("Punchline", "comedy", "sitcoms")
def punchline():
    d = SH + lin("pl", [(0, "#1e3a8a"), (1, "#0b1a44")])
    body = '<g filter="url(#sh)"><rect x="36" y="110" width="440" height="292" rx="30" fill="url(#pl)" stroke="#050b1f" stroke-width="7"/></g>'
    bub = '<path d="M0 18 Q0 0 18 0 L90 0 Q108 0 108 18 L108 62 Q108 80 90 80 L46 80 L24 102 L28 80 L18 80 Q0 80 0 62 Z" fill="#fde047" stroke="#050b1f" stroke-width="6" stroke-linejoin="round"/>'
    bub += '<rect x="48" y="14" width="12" height="36" rx="5" fill="#050b1f"/><circle cx="54" cy="64" r="7" fill="#050b1f"/>'
    body += f'<g filter="url(#sh)">{fit(bub, 206, 40, 100, 100)}</g>'
    body += fit(text("PUNCHLINE", "Archivo Black", 100, fill="#fff"), 66, 170, 380, 96)
    body += '<path d="M120 286 Q256 314 392 286" fill="none" stroke="#ef4444" stroke-width="10" stroke-linecap="round"/>'
    body += fit(
        text("CLASSIC COMEDY", "Oswald", 40, weight=700, fill="#fde047", ls=10), 150, 330, 212, 32
    )
    return svg(body, d)


@net("Madcap", "comedy", "sitcoms")
def madcap():
    return L.script_card(
        "Madcap",
        "CLASSIC COMEDY",
        card="#ff9f1c",
        card2="#e85d04",
        edge="#1d1d1f",
        ink="#fff8e7",
        script_font="Lobster",
        shape="diamond",
        sub_ink="#fff8e7",
        tilt=-6,
    )


@net("Tomfoolery", "comedy", "sitcoms", "vaudeville")
def tomfoolery():
    d = SH + lin("tfr", [(0, "#2b2d42"), (1, "#0f1020")])
    shield = "M256 36 L452 92 L452 256 Q452 418 256 480 Q60 418 60 256 L60 92 Z"
    body = f'<g filter="url(#sh)"><path d="{shield}" fill="#f2c14e" stroke="#1d1a14" stroke-width="9" stroke-linejoin="round"/></g>'
    body += f'<clipPath id="tfc"><path d="{shield}"/></clipPath><g clip-path="url(#tfc)">'
    size = 64
    for row in range(-1, 18):
        for col in range(-1, 9):
            cx, cy = 32 + col * size + (size / 2 if row % 2 else 0), 20 + row * size / 2
            fill = ("#c1121f", "#1d1a14")[row % 2]  # a harlequin check
            body += f'<polygon points="{cx},{cy - size / 2} {cx + size / 2},{cy} {cx},{cy + size / 2} {cx - size / 2},{cy}" fill="{fill}" stroke="#f2c14e" stroke-width="3"/>'
    body += "</g>"
    body += f'<path d="{shield}" fill="none" stroke="#fff3cf" stroke-width="5" transform="translate(256 262) scale(.93) translate(-256 -262)"/>'
    body += (
        '<g filter="url(#sh)">'
        + ribbon(40, 472, 214, 110, "url(#tfr)", edge="#f2c14e", sw=6, tail=36, tail_fill="#1d1a14")
        + "</g>"
    )
    body += fit(text("TOMFOOLERY", "Ultra", 100, fill="#fff3cf"), 58, 232, 396, 74)
    body += fit(
        text(
            "CLASSIC COMEDY", "Oswald", 40, weight=700, fill="#fff3cf", stroke="#1d1a14", sw=8, ls=8
        ),
        150,
        384,
        212,
        34,
    )
    return svg(body, d)


def _feather() -> str:
    f = '<path d="M30 190 Q60 120 120 60 Q150 30 188 14 Q176 60 150 96 Q110 150 30 190 Z" fill="url(#plume)" stroke="#4a1942" stroke-width="5" stroke-linejoin="round"/>'
    f += '<path d="M30 190 Q100 110 186 16" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" opacity=".9"/>'
    for i in range(9):
        t = 0.18 + i * 0.09
        x, y = 30 + 156 * t, 190 - 174 * t
        f += f'<path d="M{x:.0f} {y:.0f} q{-26 + i:.0f} {-2:.0f} {-40 + i * 2:.0f} {14 - i:.0f}" fill="none" stroke="#4a1942" stroke-width="2.5" opacity=".45"/>'
    return f


@net("Rib Tickler", "comedy", "sitcoms")
def rib_tickler():
    d = SH + lin("plume", [(0, "#ff85a1"), (0.5, "#f15bb5"), (1, "#9b5de5")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="220" fill="#fee440" stroke="#4a1942" stroke-width="8"/></g>'
    body += '<circle cx="256" cy="256" r="200" fill="none" stroke="#f15bb5" stroke-width="5" stroke-dasharray="14 12"/>'
    body += f'<g filter="url(#sh)">{fit(_feather(), 220, 46, 230, 230)}</g>'
    body += fit(_word("RIB", "Titan One", "#9b5de5", "#4a1942", 12), 88, 150, 170, 110)
    body += fit(_word("TICKLER", "Titan One", "#f15bb5", "#4a1942", 12), 64, 270, 384, 104)
    body += fit(
        text("GIGGLES SINCE '59", "Oswald", 40, weight=700, fill="#4a1942", ls=6), 170, 390, 172, 28
    )
    return svg(body, d)


@net("Laugh Lines", "comedy", "sitcoms", "70s")
def laugh_lines():
    d = SH
    body = '<g filter="url(#sh)"><rect x="36" y="56" width="440" height="400" rx="200" fill="#fdf0d5" stroke="#3d1f0e" stroke-width="8"/></g>'
    body += '<clipPath id="llc"><rect x="44" y="64" width="424" height="384" rx="192"/></clipPath><g clip-path="url(#llc)">'
    for i, c in enumerate(("#d62828", "#f77f00", "#fcbf49", "#6a994e", "#277da1")):
        r = 250 - i * 30
        body += f'<path d="M{256 - r} 250 A{r} {r * 0.8} 0 0 0 {256 + r} 250" fill="none" stroke="{c}" stroke-width="26"/>'
    body += "</g>"
    body += fit(_word("LAUGH", "Chango", "#3d1f0e"), 96, 104, 320, 90)
    body += fit(_word("LINES", "Chango", "#d62828"), 132, 188, 248, 72)
    return svg(body, d)


@net("Wood Panel TV", "comedy", "sitcoms", "70s", "favorites")
def wood_panel_tv():
    d = (
        SH
        + lin(
            "wood",
            [(0, "#8b5a2b"), (0.3, "#a86b35"), (0.55, "#7a4a22"), (0.8, "#a0662f"), (1, "#6e3f1c")],
            x2=1,
            y2=0,
        )
        + lin("brass", [(0, "#fff2c2"), (0.45, "#d9a93c"), (0.55, "#b8862a"), (1, "#f2d27a")])
    )
    body = '<g filter="url(#sh)"><rect x="28" y="76" width="456" height="360" rx="20" fill="url(#wood)" stroke="#3b200c" stroke-width="8"/></g>'
    rng = random.Random(4)
    grain = ""
    for x in range(40, 480, 76):
        body += f'<line x1="{x}" y1="80" x2="{x}" y2="432" stroke="#3b200c" stroke-width="3" opacity=".6"/>'
        for _ in range(5):
            gx = x + rng.uniform(8, 66)
            grain += f'<path d="M{gx:.0f} 84 Q{gx + rng.uniform(-10, 10):.0f} 256 {gx + rng.uniform(-6, 6):.0f} 430" fill="none" stroke="#4a2810" stroke-width="1.6" opacity=".35"/>'
    body += grain
    body += '<g filter="url(#sh)"><rect x="76" y="160" width="360" height="192" rx="18" fill="url(#brass)" stroke="#5a3d0a" stroke-width="6"/></g>'
    body += '<rect x="90" y="174" width="332" height="164" rx="10" fill="none" stroke="#8a6414" stroke-width="3"/>'
    for x, y in ((100, 184), (412, 184), (100, 328), (412, 328)):
        body += f'<circle cx="{x}" cy="{y}" r="6" fill="#8a6414"/><line x1="{x - 4}" y1="{y}" x2="{x + 4}" y2="{y}" stroke="#f2d27a" stroke-width="2"/>'
    body += fit(text("WOOD PANEL", "Holtwood One SC", 100, fill="#4a3208"), 112, 196, 288, 64)
    body += fit(text("TV", "Holtwood One SC", 100, fill="#4a3208"), 206, 266, 100, 58)
    return svg(body, d)


@net("Meatloaf Monday", "comedy", "sitcoms", "family")
def meatloaf_monday():
    d = SH
    body = '<g filter="url(#sh)"><rect x="76" y="40" width="360" height="424" rx="22" fill="#fffdf6" stroke="#2b2118" stroke-width="7"/></g>'
    body += '<path d="M76 62 Q76 40 98 40 L414 40 Q436 40 436 62 L436 150 L76 150 Z" fill="#d62828" stroke="#2b2118" stroke-width="7"/>'
    for x in (140, 208, 304, 372):
        body += f'<rect x="{x - 8}" y="26" width="16" height="40" rx="8" fill="#9aa3ad" stroke="#2b2118" stroke-width="5"/>'
    body += fit(text("MONDAY", "Archivo Black", 100, fill="#fffdf6", ls=6), 116, 78, 280, 58)
    body += _lines(100, 412, 206, 6, 38, "#a8c5e0", 2, 0.7)
    body += fit(text("Meatloaf", "Lobster", 100, fill="#7a2e12"), 104, 160, 304, 96)
    # a loaf on a platter
    body += '<ellipse cx="256" cy="378" rx="136" ry="34" fill="#e9ecef" stroke="#2b2118" stroke-width="6"/>'
    body += '<path d="M150 370 Q150 300 256 296 Q362 300 362 370 Z" fill="#7b3f24" stroke="#2b2118" stroke-width="6"/>'
    body += (
        '<path d="M160 330 Q256 292 352 330 Q340 312 256 306 Q172 312 160 330 Z" fill="#c0392b"/>'
    )
    body += '<path d="M200 322 L216 312 M246 318 L262 308 M292 322 L308 312" stroke="#f5b7a8" stroke-width="5" stroke-linecap="round"/>'
    body += fit(
        text("COMFORT CLASSICS", "Oswald", 40, weight=700, fill="#2b2118", ls=6), 150, 424, 212, 24
    )
    return svg(body, d)


# ======================================================== favorites & mix


@net("Memory Lane", "favorites", "reruns", "nostalgia")
def memory_lane():
    d = SH + lin("sepia", [(0, "#f3d9a4"), (0.55, "#d9a566"), (1, "#8b5a2b")])
    body = '<g filter="url(#sh)"><g transform="rotate(-5 256 256)">'
    body += '<rect x="66" y="40" width="380" height="440" rx="8" fill="#fbf8f1" stroke="#cfc6b2" stroke-width="3"/>'
    body += '<rect x="96" y="70" width="320" height="270" fill="url(#sepia)"/>'
    # a road winding to the horizon, and a row of old poles
    body += (
        '<path d="M96 250 Q180 222 256 214 Q340 206 416 214 L416 340 L96 340 Z" fill="#a8733f"/>'
    )
    body += '<path d="M150 340 Q220 290 246 250 Q258 226 262 214 Q268 232 290 262 Q330 306 380 340 Z" fill="#6b4423"/>'
    body += '<path d="M262 216 L262 226 M258 246 L256 262 M246 290 L240 312" stroke="#f3d9a4" stroke-width="5" stroke-linecap="round"/>'
    for i, x in enumerate((130, 176, 212)):
        h = 110 - i * 30
        body += f'<line x1="{x}" y1="{250 - h}" x2="{x}" y2="{252 - i * 12}" stroke="#4a2c14" stroke-width="{5 - i}"/>'
        body += f'<line x1="{x - 14 + i * 4}" y1="{256 - h}" x2="{x + 14 - i * 4}" y2="{256 - h}" stroke="#4a2c14" stroke-width="{4 - i}"/>'
    body += '<circle cx="356" cy="140" r="34" fill="#fff2d1" opacity=".8"/>'
    body += '<rect x="96" y="70" width="320" height="270" fill="none" stroke="#6b4423" stroke-width="3" opacity=".6"/>'
    body += fit(text("Memory Lane", "Yellowtail", 100, fill="#5a3a1c"), 96, 350, 320, 82)
    body += fit(
        text("CLASSIC TELEVISION", "Oswald", 40, weight=600, fill="#8b5a2b", ls=8),
        150,
        436,
        212,
        22,
    )
    body += "</g></g>"
    return svg(body, d)


@net("Time Capsule", "favorites", "reruns", "nostalgia")
def time_capsule():
    d = (
        SH
        + lin(
            "cap",
            [
                (0, "#f1f5f9"),
                (0.35, "#aab6c3"),
                (0.5, "#66778a"),
                (0.75, "#c9d3dd"),
                (1, "#7a8a9b"),
            ],
        )
        + lin("band", [(0, "#ffd166"), (0.5, "#e8a33d"), (1, "#9a6412")])
    )
    body = '<g filter="url(#sh)"><g transform="rotate(-18 256 256)">'
    body += '<rect x="40" y="178" width="432" height="156" rx="78" fill="url(#cap)" stroke="#2b3440" stroke-width="7"/>'
    for x in (118, 394):
        body += f'<rect x="{x - 14}" y="176" width="28" height="160" fill="url(#band)" stroke="#2b3440" stroke-width="5"/>'
        for y in (196, 256, 316):
            body += f'<circle cx="{x}" cy="{y}" r="5" fill="#5c3d0a"/>'
    body += '<rect x="150" y="206" width="212" height="100" rx="10" fill="#1f2a38" stroke="#2b3440" stroke-width="5"/>'
    body += fit(text("TIME", "Black Ops One", 100, fill="#ffd166", ls=6), 168, 214, 176, 44)
    body += fit(text("CAPSULE", "Black Ops One", 100, fill="#f1f5f9", ls=4), 164, 262, 184, 34)
    body += "</g></g>"
    for x, y, r in ((420, 110, 26), (96, 400, 20), (446, 380, 14)):
        body += f'<polygon points="{star(x, y, r, r * 0.3, 4)}" fill="#ffd166"/>'
    body += fit(
        text(
            "SEALED IN THE 20TH CENTURY",
            "Oswald",
            40,
            weight=700,
            fill="#e9eef3",
            stroke="#1f2a38",
            sw=8,
            ls=4,
        ),
        110,
        432,
        292,
        30,
    )
    return svg(body, d)


@net("Heirloom TV", "favorites", "reruns", "classic tv")
def heirloom_tv():
    d = (
        SH
        + lin(
            "gilt",
            [(0, "#fff1c1"), (0.3, "#d4a63c"), (0.55, "#8a6414"), (0.8, "#e7c56c"), (1, "#a67c1f")],
            x2=1,
            y2=1,
        )
        + rad("velvet", [(0, "#8c1c3a"), (1, "#3d0717")])
    )
    body = '<g filter="url(#sh)"><ellipse cx="256" cy="246" rx="206" ry="222" fill="url(#gilt)" stroke="#4a3208" stroke-width="6"/></g>'
    for k in range(24):
        a = math.radians(k * 15)
        x, y = 256 + 192 * math.cos(a), 246 + 208 * math.sin(a)
        body += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="8" fill="#f7dc8a" stroke="#6b4c0c" stroke-width="3"/>'
    body += '<ellipse cx="256" cy="246" rx="164" ry="180" fill="url(#velvet)" stroke="#4a3208" stroke-width="6"/>'
    body += '<ellipse cx="256" cy="246" rx="150" ry="166" fill="none" stroke="#e7c56c" stroke-width="2" opacity=".7"/>'
    body += fit(
        text("Heirloom", "Playfair Display", 100, weight=700, style="italic", fill="#f7dc8a"),
        118,
        176,
        276,
        96,
    )
    body += '<line x1="176" y1="296" x2="336" y2="296" stroke="#e7c56c" stroke-width="3"/>'
    body += fit(
        text("TELEVISION", "Cinzel", 100, weight=700, fill="#f7dc8a", ls=12), 150, 310, 212, 36
    )
    body += f'<polygon points="{star(256, 120, 14, 6)}" fill="#f7dc8a"/>'
    return svg(body, d)


@net("Hand-Me-Down TV", "favorites", "reruns")
def hand_me_down_tv():
    mark = centred(
        S.tv_set(P(a="#9a3412", b="#fef3c7", c="#5b8a72", k="#2a1608", l="#fff")), 256, 150, 190
    )
    return L.tile_word(
        mark,
        "HAND-ME-DOWN",
        font="Alfa Slab One",
        ink="#fef3c7",
        edge="#2a1608",
        tile="#fde68a",
        tile2="#f59e0b",
        weight=400,
        sub="TELEVISION",
        sub_ink="#fde68a",
        shape="circle",
        ring="#9a3412",
    )


@net("Way Back When", "favorites", "reruns", "nostalgia")
def way_back_when():
    d = (
        SH
        + glow("bulb", "#ffe08a", blur=4, strength=1)
        + lin("arr", [(0, "#ff6b6b"), (1, "#c92a2a")])
    )
    arrow = "M468 170 L150 170 L150 110 L36 248 L150 386 L150 326 L468 326 Z"
    body = f'<g filter="url(#sh)"><path d="{arrow}" fill="url(#arr)" stroke="#2b0f0f" stroke-width="9" stroke-linejoin="round"/></g>'
    body += '<path d="M456 184 L162 184 L162 144 L62 248 L162 352 L162 312 L456 312 Z" fill="none" stroke="#fff1c2" stroke-width="4" stroke-linejoin="round"/>'
    for i in range(12):
        x = 180 + i * 24
        body += f'<g filter="url(#bulb)"><circle cx="{x}" cy="162" r="0"/></g>'
    for x in range(186, 456, 26):
        for y in (160, 336):
            body += f'<circle cx="{x}" cy="{y}" r="6" fill="#fff4c2" stroke="#8a5a00" stroke-width="2"/>'
    body += fit(
        text("WAY BACK", "Bowlby One", 100, fill="#fff4c2", stroke="#2b0f0f", sw=10),
        168,
        196,
        280,
        70,
    )
    body += fit(
        text("WHEN", "Yellowtail", 100, fill="#fff4c2", stroke="#2b0f0f", sw=8), 214, 256, 190, 70
    )
    return svg(body, d)


@net("Console TV", "favorites", "reruns", "classic tv")
def console_tv():
    d = (
        SH
        + lin("teak", [(0, "#9c5a2b"), (0.5, "#7b4420"), (1, "#5a2f14")], x2=1, y2=0)
        + rad("glass", [(0, "#8fd3c9"), (0.7, "#2d7f78"), (1, "#123f3c")], cx=0.45, cy=0.4)
    )
    body = '<g filter="url(#sh)">'
    for x in (92, 408):
        body += f'<path d="M{x} 418 L{x + (8 if x < 256 else -8)} 470" stroke="#2c1608" stroke-width="12" stroke-linecap="round"/>'
    body += '<rect x="36" y="116" width="440" height="306" rx="22" fill="url(#teak)" stroke="#2c1608" stroke-width="8"/></g>'
    body += '<rect x="62" y="140" width="250" height="196" rx="40" fill="#1a0f08"/>'
    body += '<rect x="72" y="150" width="230" height="176" rx="34" fill="url(#glass)"/>'
    body += '<path d="M90 176 Q150 156 226 166" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round" opacity=".35"/>'
    body += fit(text("CONSOLE", "Archivo Black", 100, fill="#fff8e7"), 86, 204, 202, 56)
    body += fit(text("TV", "Archivo Black", 100, fill="#ffd166"), 150, 264, 74, 46)
    body += '<rect x="330" y="140" width="124" height="196" rx="12" fill="#3a2010"/>'
    for y in range(152, 330, 12):
        body += f'<line x1="340" y1="{y}" x2="444" y2="{y}" stroke="#c9a46a" stroke-width="4" opacity=".7"/>'
    for x in (126, 246):
        body += f'<circle cx="{x}" cy="378" r="20" fill="#e9dcc2" stroke="#2c1608" stroke-width="6"/><line x1="{x}" y1="364" x2="{x}" y2="378" stroke="#2c1608" stroke-width="5"/>'
    body += fit(
        text("TELEVISION FOR THE WHOLE FAMILY", "Oswald", 40, weight=600, fill="#f2dcb2", ls=3),
        290,
        368,
        170,
        22,
    )
    return svg(body, d)


def _tube() -> str:
    t = '<path d="M60 210 L60 70 Q60 14 100 14 Q140 14 140 70 L140 210 Z" fill="url(#tubeglass)" stroke="#e8f4ff" stroke-width="4" opacity=".95"/>'
    t += '<rect x="78" y="80" width="44" height="110" rx="6" fill="#4a5058" stroke="#20242a" stroke-width="3"/>'
    t += '<g filter="url(#fil)"><path d="M88 186 L88 100 Q100 88 112 100 L112 186" fill="none" stroke="#ffb347" stroke-width="5"/></g>'
    t += '<rect x="52" y="206" width="96" height="30" rx="6" fill="#2b2b2b" stroke="#111" stroke-width="3"/>'
    for x in (68, 88, 112, 132):
        t += f'<rect x="{x - 2}" y="236" width="4" height="16" fill="#b8b8b8"/>'
    return t


@net("Tube Glow", "favorites", "reruns", "classic tv")
def tube_glow():
    d = (
        SH
        + glow("fil", "#ff8c1a", blur=6, strength=3)
        + glow("tg", "#ff7b00", blur=10, strength=2)
        + lin("tubeglass", [(0, "#ffd39b"), (0.5, "#ff9f43"), (1, "#8a3b00")], x2=1, y2=0)
        + rad("halo", [(0, "#ff9f43"), (1, "#ff9f4300")])
    )
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="60" fill="#1b1410" stroke="#000" stroke-width="6"/></g>'
    body += '<circle cx="256" cy="178" r="150" fill="url(#halo)" opacity=".55"/>'
    body += fit(_tube(), 186, 58, 140, 240)
    body += f'<g filter="url(#tg)">{fit(text("TUBE GLOW", "Righteous", 100, fill="#ffc46b"), 76, 318, 360, 86)}</g>'
    body += fit(
        text("WARMED UP CLASSICS", "Oswald", 40, weight=600, fill="#f2c79a", ls=6),
        146,
        414,
        220,
        26,
    )
    return svg(body, d)


@net("The Clicker", "favorites", "reruns")
def the_clicker():
    d = SH + lin("clk", [(0, "#14b8a6"), (1, "#0f766e")])
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="80" fill="url(#clk)" stroke="#042f2e" stroke-width="8"/></g>'
    r = '<rect x="-40" y="-96" width="80" height="192" rx="30" fill="#f8fafc" stroke="#042f2e" stroke-width="7"/>'
    r += '<circle cx="0" cy="-60" r="13" fill="#ef4444"/>'
    for cx, cy in ((-16, -18), (16, -18), (-16, 14), (16, 14), (-16, 46), (16, 46)):
        r += f'<circle cx="{cx}" cy="{cy}" r="9" fill="#0f766e"/>'
    body += f'<g filter="url(#sh)"><g transform="translate(256 168) rotate(-20)">{r}</g></g>'
    for a in (-60, -35, -10):
        x, y = 256 + 100 * math.cos(math.radians(a)), 168 + 100 * math.sin(math.radians(a))
        body += f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x + 26 * math.cos(math.radians(a)):.0f}" y2="{y + 26 * math.sin(math.radians(a)):.0f}" stroke="#fef08a" stroke-width="8" stroke-linecap="round"/>'
    body += fit(text("THE CLICKER", "Archivo Black", 100, fill="#fff"), 76, 318, 360, 70)
    body += fit(
        text("CLASSIC TV FAVORITES", "Oswald", 40, weight=700, fill="#ccfbf1", ls=6),
        140,
        400,
        232,
        28,
    )
    return svg(body, d)


def _ears() -> str:
    foil = "url(#foil)"
    e = '<ellipse cx="150" cy="276" rx="92" ry="34" fill="#3b3f46" stroke="#15171c" stroke-width="6"/>'
    e += '<rect x="96" y="238" width="108" height="40" rx="14" fill="#555b64" stroke="#15171c" stroke-width="6"/>'
    for x2, y2 in ((34, 40), (268, 40)):
        e += f'<line x1="150" y1="240" x2="{x2}" y2="{y2}" stroke="#c9ced6" stroke-width="8" stroke-linecap="round"/>'
        e += f'<line x1="150" y1="240" x2="{x2}" y2="{y2}" stroke="#f8f9fa" stroke-width="3" stroke-linecap="round"/>'
        pts_ = []
        rng = random.Random(x2)
        for k in range(14):
            a = math.radians(k * 360 / 14)
            r = 38 + rng.uniform(-8, 8)
            pts_.append(f"{x2 + r * math.cos(a):.0f},{y2 + r * math.sin(a):.0f}")
        e += f'<polygon points="{" ".join(pts_)}" fill="{foil}" stroke="#495057" stroke-width="4" stroke-linejoin="round"/>'
        e += f'<path d="M{x2 - 18} {y2 - 6} L{x2 + 4} {y2 + 8} L{x2 + 20} {y2 - 10} M{x2 - 10} {y2 + 18} L{x2 + 12} {y2 + 14}" stroke="#868e96" stroke-width="3" fill="none"/>'
    return e


@net("Tin Foil Antenna", "favorites", "reruns", "over the air")
def tin_foil_antenna():
    d = SH + lin(
        "foil", [(0, "#ffffff"), (0.3, "#adb5bd"), (0.6, "#f1f3f5"), (1, "#868e96")], x2=1, y2=1
    )
    body = f'<g filter="url(#sh)">{fit(_ears(), 96, 24, 320, 290)}</g>'
    body += '<g filter="url(#sh)"><rect x="40" y="318" width="432" height="150" rx="20" fill="#2b2d42" stroke="#101124" stroke-width="7"/></g>'
    body += fit(text("TIN FOIL", "Russo One", 100, fill="#e9ecef"), 74, 332, 364, 66)
    body += fit(text("ANTENNA", "Russo One", 100, fill="#ffd166", ls=6), 108, 404, 296, 50)
    return svg(body, d)


def _recliner() -> str:
    """A recliner from the side, leaned back with its footrest up (on a
    280x200 box)."""
    k = "#2b160c"
    c = f'<path d="M20 26 Q18 8 36 8 L82 14 Q100 18 98 36 L86 132 L30 132 Z" fill="#8e5a3c" stroke="{k}" stroke-width="7" stroke-linejoin="round"/>'
    c += '<path d="M36 30 L78 34" stroke="#b07a55" stroke-width="7" stroke-linecap="round"/>'
    c += f'<path d="M30 110 Q28 96 44 96 L170 104 Q186 106 184 122 L182 150 L30 150 Z" fill="#9c6644" stroke="{k}" stroke-width="7" stroke-linejoin="round"/>'
    c += f'<path d="M176 120 L250 96 Q268 92 268 108 L266 124 L186 150 Z" fill="#8e5a3c" stroke="{k}" stroke-width="7" stroke-linejoin="round"/>'
    c += f'<rect x="18" y="116" width="62" height="54" rx="18" fill="#7a4a30" stroke="{k}" stroke-width="7"/>'
    c += f'<rect x="120" y="116" width="62" height="54" rx="18" fill="#7a4a30" stroke="{k}" stroke-width="7" opacity="0"/>'
    c += f'<path d="M36 170 L32 196 M166 150 L170 196" stroke="{k}" stroke-width="9" stroke-linecap="round"/>'
    c += f'<rect x="10" y="190" width="186" height="10" rx="5" fill="{k}"/>'
    return c


@net("The Recliner", "favorites", "reruns", "comfort")
def the_recliner():
    centre = centred(_recliner(), 256, 176, 230)
    return L.roundel(
        centre,
        "THE RECLINER",
        font="Alfa Slab One",
        ink="#fff4e0",
        disc="#e9c46a",
        rim="#fff4e0",
        edge="#2b160c",
        bar="#6d3b1f",
        bar_y=300,
        ls=2,
    )


@net("Evergreen TV", "favorites", "reruns", "classics")
def evergreen_tv():
    mark = centred(S.pine(P(a="#2d6a4f", b="#95d5b2", k="#081c15", l="#d8f3dc")), 256, 146, 180)
    return L.tile_word(
        mark,
        "EVERGREEN",
        font="Montserrat",
        ink="#d8f3dc",
        edge="#081c15",
        tile="#d8f3dc",
        tile2="#95d5b2",
        weight=800,
        sub="TELEVISION",
        sub_ink="#95d5b2",
        shape="circle",
        ring="#2d6a4f",
    )


def _dial() -> str:
    g = '<circle cx="0" cy="0" r="120" fill="url(#dialface)" stroke="#5a3d0a" stroke-width="6"/>'
    for n in range(2, 14):
        a = math.radians(-120 + (n - 2) * 22)
        x, y = 92 * math.cos(a), 92 * math.sin(a)
        g += text(str(n), "Oswald", 26, weight=700, fill="#3d2a06", x=round(x), y=round(y + 9))
    g += '<circle cx="0" cy="0" r="58" fill="url(#knob)" stroke="#5a3d0a" stroke-width="5"/>'
    g += '<rect x="-10" y="-56" width="20" height="112" rx="8" fill="#e8c56a" stroke="#5a3d0a" stroke-width="4"/>'
    g += '<polygon points="0,-128 -10,-146 10,-146" fill="#c1121f"/>'
    return f'<g transform="translate(256 256)">{g}</g>'


@net("Golden Dial", "favorites", "reruns", "classics")
def golden_dial():
    defs = rad("dialface", [(0, "#fff6d8"), (1, "#e3c77a")]) + lin(
        "knob", [(0, "#fff1c1"), (0.5, "#c9962e"), (1, "#8a6414")]
    )
    return L.seal(
        _dial(),
        "GOLDEN DIAL",
        "CLASSIC TV",
        font="Cinzel",
        ring="#1f2b44",
        ring_ink="#f2d27a",
        face="#1f2b44",
        edge="#0d1322",
        defs=defs,
        dots="#f2d27a",
        ls=8,
    )


@net("Station Break", "favorites", "reruns", "classics")
def station_break():
    d = SH + lin("sb", [(0, "#243b6b"), (1, "#101c38")])
    body = '<g filter="url(#sh)"><rect x="36" y="60" width="440" height="392" rx="24" fill="url(#sb)" stroke="#0a1022" stroke-width="7"/></g>'
    for cx, cy in ((92, 116), (420, 116), (92, 396), (420, 396)):
        body += f'<circle cx="{cx}" cy="{cy}" r="30" fill="none" stroke="#f4d35e" stroke-width="5"/><circle cx="{cx}" cy="{cy}" r="16" fill="none" stroke="#f4d35e" stroke-width="3"/>'
    body += fit(
        S.mic_vintage(P(a="#e9ecef", b="#adb5bd", k="#0a1022", l="#fff")), 206, 86, 100, 120
    )
    for side in (-1, 1):
        body += f'<polyline points="{256 + side * 70},110 {256 + side * 100},140 {256 + side * 82},146 {256 + side * 116},186" fill="none" stroke="#f4d35e" stroke-width="8" stroke-linejoin="round" stroke-linecap="round"/>'
    body += fit(text("STATION", "Alfa Slab One", 100, fill="#f4d35e", ls=4), 96, 224, 320, 80)
    body += fit(text("BREAK", "Alfa Slab One", 100, fill="#fdfdfd", ls=10), 136, 312, 240, 64)
    body += fit(
        text("WE'LL BE RIGHT BACK WITH MORE", "Oswald", 40, weight=600, fill="#c9d6ef", ls=4),
        130,
        392,
        252,
        24,
    )
    return svg(body, d)


def _knob() -> str:
    k = '<circle cx="0" cy="0" r="150" fill="url(#bezel)" stroke="#1e2126" stroke-width="7"/>'
    for n, lab in enumerate(("2", "4", "5", "7", "9", "11", "13", "UHF")):
        a = math.radians(-150 + n * 34)
        x, y = 124 * math.cos(a), 124 * math.sin(a)
        k += text(
            lab,
            "Oswald",
            22 if lab == "UHF" else 26,
            weight=700,
            fill="#f8f9fa",
            x=round(x),
            y=round(y + 9),
        )
    k += '<circle cx="0" cy="0" r="92" fill="url(#chrome)" stroke="#1e2126" stroke-width="6"/>'
    for n in range(24):
        a = math.radians(n * 15)
        k += f'<line x1="{86 * math.cos(a):.1f}" y1="{86 * math.sin(a):.1f}" x2="{76 * math.cos(a):.1f}" y2="{76 * math.sin(a):.1f}" stroke="#495057" stroke-width="3"/>'
    k += '<rect x="-14" y="-88" width="28" height="176" rx="12" fill="url(#grip)" stroke="#1e2126" stroke-width="5"/>'
    k += '<polygon points="0,-84 -8,-66 8,-66" fill="#e63946"/>'
    return f'<g transform="translate(256 208) rotate(-12)">{k}</g>'


@net("Channel Knob", "favorites", "reruns", "classics")
def channel_knob():
    d = (
        SH
        + rad("bezel", [(0, "#495057"), (1, "#212529")])
        + rad("chrome", [(0, "#ffffff"), (0.6, "#ced4da"), (1, "#6c757d")], cx=0.4, cy=0.35)
        + lin("grip", [(0, "#f8f9fa"), (1, "#868e96")], x2=1, y2=0)
    )
    body = f'<g filter="url(#sh)">{_knob()}</g>'
    body += '<g filter="url(#sh)"><rect x="70" y="376" width="372" height="86" rx="16" fill="#e63946" stroke="#1e2126" stroke-width="7"/></g>'
    body += fit(text("CHANNEL KNOB", "Archivo Black", 100, fill="#fff"), 92, 390, 328, 58)
    return svg(body, d)


@net("Comfort TV", "favorites", "reruns", "comfort")
def comfort_tv():
    d = SH
    colours = [
        "#e07a5f",
        "#f2cc8f",
        "#81b29a",
        "#f4f1de",
        "#3d405b",
        "#e07a5f",
        "#81b29a",
        "#f2cc8f",
        "#e07a5f",
    ]
    body = '<g filter="url(#sh)"><rect x="46" y="46" width="420" height="420" rx="36" fill="#3d405b" stroke="#23253a" stroke-width="7"/></g>'
    for i in range(9):
        x, y = 62 + (i % 3) * 130, 62 + (i // 3) * 130
        body += f'<rect x="{x}" y="{y}" width="128" height="128" rx="10" fill="{colours[i]}"/>'
        body += f'<rect x="{x + 8}" y="{y + 8}" width="112" height="112" rx="6" fill="none" stroke="#23253a" stroke-width="3" stroke-dasharray="7 6" opacity=".55"/>'
    body += '<g filter="url(#sh)"><rect x="92" y="170" width="328" height="172" rx="26" fill="#f4f1de" stroke="#23253a" stroke-width="7"/></g>'
    body += '<rect x="104" y="182" width="304" height="148" rx="18" fill="none" stroke="#e07a5f" stroke-width="4" stroke-dasharray="8 7"/>'
    body += fit(text("Comfort", "Pacifico", 100, fill="#e07a5f"), 122, 188, 268, 88)
    body += fit(
        text("TELEVISION", "Oswald", 100, weight=700, fill="#3d405b", ls=10), 160, 284, 192, 34
    )
    return svg(body, d)


def _geyser() -> str:
    g = '<rect x="40" y="20" width="432" height="400" fill="url(#pksky)"/>'
    g += '<path d="M40 300 L140 220 L210 270 L300 190 L400 260 L472 220 L472 420 L40 420 Z" fill="#5f7f6a"/>'
    g += '<path d="M40 330 L472 330 L472 420 L40 420 Z" fill="#c7b07a"/>'
    g += '<path d="M226 330 Q236 250 222 180 Q240 120 256 60 Q272 120 290 180 Q276 250 286 330 Z" fill="#f8fbff" stroke="#a9c6d9" stroke-width="4"/>'
    for x, y, r in ((236, 90, 22), (276, 80, 26), (256, 58, 24), (222, 130, 18), (292, 124, 20)):
        g += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#f8fbff" stroke="#a9c6d9" stroke-width="3"/>'
    g += '<ellipse cx="256" cy="334" rx="70" ry="12" fill="#e2d3a3" stroke="#8a7440" stroke-width="3"/>'
    return g


@net("Old Faithful", "favorites", "reruns", "classics")
def old_faithful():
    return L.emblem(
        _geyser(),
        "OLD FAITHFUL",
        font="Alfa Slab One",
        ink="#fff8e7",
        band="#8a3b12",
        rim="#f4e3b5",
        edge="#2b1507",
        defs=lin("pksky", [(0, "#5fa8d3"), (1, "#cae9ff")]),
        ls=2,
    )


@net("Pot Luck TV", "favorites", "reruns", "variety")
def pot_luck_tv():
    centre = centred(
        S.fork_knife(P(a="#fde68a", b="#fef3c7", k="#3b0d0d", l="#fff")), 256, 170, 200
    )
    return L.roundel(
        centre,
        "POT LUCK TV",
        font="Carter One",
        ink="#fff7e6",
        disc="#c2410c",
        rim="#fde68a",
        edge="#3b0d0d",
        bar="#7c2d12",
        bar_y=300,
        ls=2,
    )


def _rosette(petals: str, petals2: str, edge: str) -> str:
    r = ""
    for side, rot in ((-1, 14), (1, -14)):
        x = 256 + side * 44
        r += f'<g transform="rotate({rot} {x} 300)"><path d="M{x - 38} 290 L{x + 38} 290 L{x + 38} 470 L{x} 440 L{x - 38} 470 Z" fill="{petals2}" stroke="{edge}" stroke-width="6" stroke-linejoin="round"/></g>'
    pts_ = []
    for k in range(48):
        a = math.radians(k * 7.5)
        rr = 170 if k % 2 == 0 else 152
        pts_.append(f"{256 + rr * math.cos(a):.1f},{214 + rr * math.sin(a):.1f}")
    r += f'<polygon points="{" ".join(pts_)}" fill="{petals}" stroke="{edge}" stroke-width="6" stroke-linejoin="round"/>'
    r += f'<circle cx="256" cy="214" r="134" fill="{petals2}" stroke="{edge}" stroke-width="5"/>'
    return r


@net("Sunday Best", "favorites", "reruns", "family")
def sunday_best():
    d = SH + rad("sbc", [(0, "#ffffff"), (1, "#fdf0d5")])
    body = f'<g filter="url(#sh)">{_rosette("#5e60ce", "#4ea8de", "#1d1a39")}</g>'
    body += '<circle cx="256" cy="214" r="110" fill="url(#sbc)" stroke="#1d1a39" stroke-width="5"/>'
    body += '<circle cx="256" cy="214" r="98" fill="none" stroke="#5e60ce" stroke-width="3" stroke-dasharray="3 7"/>'
    body += fit(
        text("SUNDAY", "Playfair Display", 100, weight=700, fill="#1d1a39", ls=4), 170, 156, 172, 50
    )
    body += fit(text("Best", "Great Vibes", 100, fill="#5e60ce"), 178, 204, 156, 84)
    body += fit(
        text("CLASSIC TV", "Oswald", 40, weight=700, fill="#fdf0d5", ls=6), 200, 364, 112, 26
    )
    return svg(body, d)


@net("The Den", "favorites", "reruns", "comfort")
def the_den():
    d = (
        SH
        + lin("plank", [(0, "#a0672d"), (0.5, "#7f4f22"), (1, "#5c3715")])
        + lin("brass2", [(0, "#fff1c1"), (0.5, "#c9962e"), (1, "#8a6414")])
    )
    body = '<path d="M150 80 L150 170 M362 80 L362 170" stroke="#adb5bd" stroke-width="6" stroke-dasharray="10 5"/>'
    body += '<rect x="120" y="68" width="272" height="16" rx="8" fill="#6c757d"/>'
    body += '<g filter="url(#sh)"><rect x="40" y="162" width="432" height="250" rx="26" fill="url(#plank)" stroke="#2e1a08" stroke-width="8"/></g>'
    for y in (220, 282, 344):
        body += f'<path d="M48 {y} Q256 {y + 8} 464 {y}" fill="none" stroke="#2e1a08" stroke-width="3" opacity=".5"/>'
    for x, y in ((66, 186), (446, 186), (66, 388), (446, 388)):
        body += f'<circle cx="{x}" cy="{y}" r="9" fill="url(#brass2)" stroke="#2e1a08" stroke-width="3"/>'
    w = _word("THE DEN", "Rye", "#fdf0d5", "#2e1a08", 12)
    body += fit(w, 78, 204, 356, 130)
    body += fit(
        text("KICK BACK WITH THE CLASSICS", "Oswald", 40, weight=700, fill="#fdf0d5", ls=4),
        118,
        346,
        276,
        28,
    )
    return svg(body, d)


@net("Back in the Day", "favorites", "reruns", "nostalgia")
def back_in_the_day():
    rays = ""
    for k in range(18):
        a0, a1 = math.radians(k * 20), math.radians(k * 20 + 10)
        rays += f'<polygon points="256,256 {256 + 400 * math.cos(a0):.0f},{256 + 400 * math.sin(a0):.0f} {256 + 400 * math.cos(a1):.0f},{256 + 400 * math.sin(a1):.0f}" fill="#f4a261" opacity=".55"/>'
    back = '<g filter="url(#sh)"><circle cx="256" cy="256" r="230" fill="#e76f51" stroke="#2a1a3e" stroke-width="8"/></g>'
    back += f'<clipPath id="bdc"><circle cx="256" cy="256" r="222"/></clipPath><g clip-path="url(#bdc)">{rays}</g>'
    return L.stacked(
        [
            ("BACK", "Bungee", "#ffe8a3", 400),
            ("in the", "Yellowtail", "#2a1a3e", 400),
            ("DAY", "Bungee", "#ffe8a3", 400),
        ],
        edge="#2a1a3e",
        sw=14,
        back=back,
        boxes=[(100, 96, 312, 110), (150, 204, 212, 76), (150, 284, 212, 126)],
        extrude_by=6,
    )


# =================================================================== drama


@net("To Be Continued", "drama", "soaps")
def to_be_continued():
    d = (
        SH
        + lin("tbc", [(0, "#2b2d42"), (1, "#14151f")])
        + lin("gold", [(0, "#fff1c1"), (0.5, "#e2b04a"), (1, "#a97a1f")])
    )
    body = '<g filter="url(#sh)"><rect x="34" y="96" width="444" height="320" rx="20" fill="url(#tbc)" stroke="#07070c" stroke-width="7"/></g>'
    body += '<rect x="52" y="114" width="408" height="284" rx="10" fill="none" stroke="url(#gold)" stroke-width="3"/>'
    body += fit(text("TO BE", "Cinzel", 100, weight=700, fill="#e9e6dc", ls=18), 166, 138, 180, 46)
    body += fit(
        text("Continued", "Playfair Display", 100, weight=700, style="italic", fill="url(#gold)"),
        72,
        196,
        368,
        110,
    )
    for i in range(3):
        body += f'<circle cx="{224 + i * 32}" cy="342" r="9" fill="#e2b04a"/>'
    body += '<path d="M330 342 L410 342 M392 326 L412 342 L392 358" fill="none" stroke="#e2b04a" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
    return svg(body, d)


@net("Previously On", "drama", "reruns")
def previously_on():
    d = SH + lin("vhs", [(0, "#1d4ed8"), (1, "#172554")])
    body = '<g filter="url(#sh)"><rect x="34" y="78" width="444" height="356" rx="26" fill="url(#vhs)" stroke="#0b1026" stroke-width="7"/></g>'
    for y in range(92, 430, 8):
        body += f'<line x1="40" y1="{y}" x2="472" y2="{y}" stroke="#fff" stroke-width="1" opacity=".07"/>'
    body += '<g fill="#fff">'
    body += (
        '<polygon points="220,120 160,160 220,200"/><polygon points="292,120 232,160 292,200"/></g>'
    )
    body += fit(text("PREVIOUSLY", "Oswald", 100, weight=700, fill="#fff", ls=6), 70, 222, 372, 88)
    body += fit(text("ON", "Oswald", 100, weight=700, fill="#facc15", ls=10), 216, 314, 80, 56)
    body += fit(text("PLAY ▸ 00:00:00", "VT323", 100, fill="#a5f3fc"), 56, 386, 150, 28)
    return svg(body, d)


@net("Stay Tuned", "drama", "favorites")
def stay_tuned():
    return L.neon(
        "Stay Tuned",
        "DRAMA ALL NIGHT",
        font="Yellowtail",
        tube="#ff4fd8",
        glow_c="#ff1493",
        frame="#38bdf8",
        sub_tube="#7dd3fc",
        sub_font="Oswald",
    )


def _cliff() -> str:
    g = '<rect x="40" y="20" width="432" height="400" fill="url(#cliffsky)"/>'
    g += '<circle cx="350" cy="250" r="60" fill="#ffd166" opacity=".9"/>'
    g += '<path d="M40 420 L40 150 L176 150 L186 196 L176 262 L194 330 L182 420 Z" fill="#2b1d33"/>'
    g += '<path d="M40 150 L176 150 L186 196" fill="none" stroke="#6b4f7a" stroke-width="6"/>'
    # someone hanging on by their fingertips, against the sky
    k = "#2b1d33"
    g += f'<path d="M184 152 L206 178 M196 150 L224 176" stroke="{k}" stroke-width="9" stroke-linecap="round"/>'
    g += f'<circle cx="222" cy="196" r="17" fill="{k}"/>'
    g += f'<path d="M222 210 Q226 240 224 270" stroke="{k}" stroke-width="16" stroke-linecap="round" fill="none"/>'
    g += f'<path d="M224 268 L208 318 M224 268 L246 312" stroke="{k}" stroke-width="12" stroke-linecap="round"/>'
    return g


@net("Cliffhanger", "drama", "suspense")
def cliffhanger():
    return L.emblem(
        _cliff(),
        "CLIFFHANGER",
        font="Archivo Black",
        ink="#fff3e0",
        band="#9d174d",
        rim="#fbcfe8",
        edge="#1c0b22",
        defs=lin("cliffsky", [(0, "#f472b6"), (0.6, "#fb923c"), (1, "#fde68a")]),
        ls=2,
    )


@net("Big Hair TV", "drama", "80s", "soaps")
def big_hair_tv():
    grid = '<rect x="40" y="250" width="432" height="190" fill="#1e0b3a"/>'
    for k in range(7):
        y = 262 + k * k * 4.2
        grid += f'<line x1="40" y1="{y:.0f}" x2="472" y2="{y:.0f}" stroke="#ec4899" stroke-width="2.5"/>'
    for k in range(-6, 7):
        grid += f'<line x1="256" y1="252" x2="{256 + k * 70}" y2="440" stroke="#ec4899" stroke-width="2.5"/>'
    sun = '<circle cx="256" cy="250" r="150" fill="url(#bhsun)"/>'
    for k in range(5):
        sun += f'<rect x="100" y="{170 + k * 18}" width="312" height="{4 + k * 2}" fill="#1e0b3a"/>'
    back = '<g filter="url(#sh)"><rect x="40" y="60" width="432" height="380" rx="30" fill="#2e1065"/></g>'
    back += f'<clipPath id="bhc"><rect x="40" y="60" width="432" height="380" rx="30"/></clipPath><g clip-path="url(#bhc)">{sun}{grid}</g>'
    return L.chrome(
        "BIG HAIR",
        "TV",
        back=back,
        defs=lin("bhsun", [(0, "#fde047"), (0.5, "#fb923c"), (1, "#db2777")]),
        box=(40, 150, 432, 140),
        sub_font="Yellowtail",
        sub_fill="#22d3ee",
    )


@net("Shoulder Pads", "drama", "80s", "soaps")
def shoulder_pads():
    d = SH + lin("suit", [(0, "#ec4899"), (1, "#9d174d")])
    jacket = "M40 470 L60 170 Q64 120 150 112 L206 104 L256 230 L306 104 L362 112 Q448 120 452 170 L472 470 Z"
    body = f'<g filter="url(#sh)"><path d="{jacket}" fill="url(#suit)" stroke="#3f0d24" stroke-width="8" stroke-linejoin="round"/></g>'
    body += '<path d="M206 104 L256 230 L306 104 L282 98 L256 150 L230 98 Z" fill="#fdf2f8" stroke="#3f0d24" stroke-width="6" stroke-linejoin="round"/>'
    body += '<path d="M206 104 L180 200 L240 250 M306 104 L332 200 L272 250" fill="none" stroke="#3f0d24" stroke-width="6" stroke-linejoin="round"/>'
    for y in (300, 360, 420):
        body += (
            f'<circle cx="256" cy="{y}" r="11" fill="#fbbf24" stroke="#3f0d24" stroke-width="4"/>'
        )
    body += '<rect x="70" y="270" width="372" height="0"/>'
    body += f'<g filter="url(#sh)">{fit(text("SHOULDER", "Anton", 100, fill="#fff", stroke="#3f0d24", sw=12, ls=4), 60, 258, 392, 88)}</g>'
    body += f'<g filter="url(#sh)">{fit(text("PADS", "Anton", 100, fill="#fbbf24", stroke="#3f0d24", sw=12, ls=12), 140, 350, 232, 88)}</g>'
    return svg(body, d)


@net("Objection!", "drama", "courtroom", "legal")
def objection():
    centre = centred(S.gavel(P(a="#a16207", b="#fde68a", k="#0b1a3a", l="#fff")), 256, 172, 210)
    return L.roundel(
        centre,
        "OBJECTION!",
        font="Playfair Display",
        weight=700,
        ink="#fde68a",
        disc="#1e3a8a",
        rim="#fde68a",
        edge="#0b1a3a",
        bar="#0b1a3a",
        bar_y=300,
        ls=2,
    )


def _bag() -> str:
    b = '<path d="M50 70 Q50 40 80 40 L120 40 Q150 40 150 70" fill="none" stroke="#1a1a1a" stroke-width="14"/>'
    b += '<path d="M8 110 Q8 70 48 66 L152 66 Q192 70 192 110 L196 190 Q196 210 176 210 L24 210 Q4 210 4 190 Z" fill="url(#leather)" stroke="#0b0b0b" stroke-width="7"/>'
    b += '<path d="M8 110 Q100 128 192 110" fill="none" stroke="#0b0b0b" stroke-width="6"/>'
    b += '<rect x="86" y="104" width="28" height="22" rx="4" fill="#e2b04a" stroke="#0b0b0b" stroke-width="4"/>'
    b += '<rect x="80" y="140" width="40" height="40" fill="none"/>'
    b += '<path d="M92 142 L108 142 L108 152 L118 152 L118 168 L108 168 L108 178 L92 178 L92 168 L82 168 L82 152 L92 152 Z" fill="#ef4444" stroke="#fff" stroke-width="3"/>'
    return b


@net("House Call", "drama", "medical")
def house_call():
    d = SH + lin("leather", [(0, "#4b4b4b"), (1, "#151515")])
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="216" fill="#e0f2fe" stroke="#0c4a6e" stroke-width="8"/></g>'
    body += '<circle cx="256" cy="256" r="196" fill="none" stroke="#38bdf8" stroke-width="4" stroke-dasharray="2 10" stroke-linecap="round"/>'
    body += f'<g filter="url(#sh)">{fit(_bag(), 146, 70, 220, 200)}</g>'
    body += (
        '<g filter="url(#sh)">'
        + banner(36, 476, 290, 92, "#0c4a6e", edge="#e0f2fe", sw=5, cut=24)
        + "</g>"
    )
    body += fit(text("HOUSE CALL", "Alfa Slab One", 100, fill="#fff"), 88, 304, 336, 64)
    body += fit(
        text("MEDICAL DRAMA", "Oswald", 40, weight=700, fill="#0c4a6e", ls=8), 180, 396, 152, 28
    )
    return svg(body, d)


@net("Bedside Manner", "drama", "medical")
def bedside_manner():
    centre = centred(
        S.stethoscope(P(a="#0f766e", b="#99f6e4", k="#042f2e", l="#fff")), 256, 168, 220
    )
    return L.roundel(
        centre,
        "BEDSIDE MANNER",
        font="Montserrat",
        weight=800,
        ink="#fff",
        disc="#ccfbf1",
        rim="#fff",
        edge="#042f2e",
        bar="#0f766e",
        bar_y=300,
        ls=1,
    )


@net("The Big Story", "drama", "news")
def the_big_story():
    return L.masthead(
        "The Big Story",
        "DRAMA EVERY NIGHT ★ LATE EDITION",
        font="UnifrakturMaguntia",
        ink="#111",
        paper="#f6f1e3",
        accent="#b91c1c",
    )


@net("Second Act", "drama", "theater")
def second_act():
    return L.deco(
        "SECOND ACT",
        "DRAMA",
        font="Poiret One",
        field="#101820",
        weight=400,
        ls=8,
    )


@net("Soap Box", "drama", "soaps")
def soap_box():
    deco = ""
    for x, y, r in ((392, 120, 26), (424, 168, 16), (110, 380, 20)):
        deco += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" fill-opacity=".25" stroke="#fff" stroke-width="4"/>'
    return L.script_card(
        "Soap Box",
        "DAYTIME DRAMA",
        card="#f9a8d4",
        card2="#a855f7",
        edge="#3b0a3a",
        ink="#fff",
        script_font="Great Vibes",
        shape="oval",
        sub_ink="#fdf4ff",
        deco=deco,
        tilt=-4,
    )


@net("Front Page", "drama", "news")
def front_page():
    d = SH
    body = '<g filter="url(#sh)"><g transform="rotate(-7 256 256)">'
    body += '<rect x="64" y="46" width="384" height="420" fill="#fbfaf5" stroke="#1f2937" stroke-width="5"/>'
    body += '<rect x="64" y="46" width="384" height="420" fill="none" stroke="#d6d3c4" stroke-width="2" transform="translate(8 8)"/>'
    body += fit(text("FRONT", "Abril Fatface", 100, fill="#111827"), 92, 66, 328, 104)
    body += fit(text("PAGE", "Abril Fatface", 100, fill="#b91c1c"), 136, 172, 240, 88)
    body += '<line x1="88" y1="272" x2="424" y2="272" stroke="#111827" stroke-width="4"/>'
    body += '<rect x="88" y="290" width="150" height="140" fill="#9ca3af"/><rect x="88" y="290" width="150" height="140" fill="none" stroke="#111827" stroke-width="3"/>'
    body += '<circle cx="163" cy="340" r="26" fill="#4b5563"/><path d="M110 430 Q163 360 216 430 Z" fill="#4b5563"/>'
    body += _lines(256, 424, 300, 9, 15, "#6b7280", 5, 0.8)
    body += "</g></g>"
    return svg(body, d)


@net("Grand Jury", "drama", "courtroom", "legal")
def grand_jury():
    centre = centred(S.columns(P(a="#f8fafc", b="#cbd5e1", k="#1e1b4b", l="#fff")), 256, 256, 210)
    return L.seal(
        centre,
        "GRAND JURY",
        "DRAMA",
        font="Cinzel",
        ring="#7f1d1d",
        ring_ink="#fde68a",
        face="#1e1b4b",
        edge="#2a0a0a",
        dots="#fde68a",
        ls=6,
    )


@net("Family Secrets", "drama", "soaps", "family")
def family_secrets():
    d = (
        SH
        + lin("cover", [(0, "#7c2d12"), (1, "#431407")])
        + lin("gilt2", [(0, "#fde68a"), (0.5, "#d97706"), (1, "#fbbf24")])
    )
    body = '<g filter="url(#sh)"><rect x="92" y="40" width="330" height="432" rx="18" fill="url(#cover)" stroke="#1c0a03" stroke-width="7"/></g>'
    body += '<rect x="92" y="40" width="38" height="432" rx="10" fill="#5a1e08" stroke="#1c0a03" stroke-width="5"/>'
    body += '<rect x="150" y="70" width="244" height="372" rx="10" fill="none" stroke="url(#gilt2)" stroke-width="4"/>'
    body += fit(text("Family", "Great Vibes", 100, fill="url(#gilt2)"), 168, 104, 208, 86)
    body += fit(text("SECRETS", "Cinzel", 100, weight=700, fill="#fde68a", ls=6), 168, 196, 208, 44)
    # a strap with a little lock
    body += '<rect x="380" y="256" width="72" height="56" rx="10" fill="#92400e" stroke="#1c0a03" stroke-width="6"/>'
    body += f'<g filter="url(#sh)">{fit(S.padlock(P(a="#fbbf24", b="#fde68a", k="#1c0a03", l="#fff")), 388, 250, 96, 110)}</g>'
    body += fit(
        text("DRAMA AFTER DARK", "Oswald", 40, weight=600, fill="#fde68a", ls=6), 176, 380, 192, 26
    )
    return svg(body, d)


# ====================================================== action & adventure


@net("Car Chase", "action", "adventure", "cars")
def car_chase():
    d = SH + lin("cc", [(0, "#facc15"), (1, "#f97316")])
    body = '<g filter="url(#sh)"><path d="M70 90 L480 90 L442 410 L32 410 Z" fill="#111827" stroke="#000" stroke-width="7" stroke-linejoin="round"/></g>'
    for i, y in enumerate((130, 168, 206)):
        body += f'<line x1="{70 - i * 4}" y1="{y}" x2="{170 - i * 20}" y2="{y}" stroke="#facc15" stroke-width="8" stroke-linecap="round" opacity="{0.9 - i * 0.2:.1f}"/>'
    body += fit(
        S.car(P(a="#ef4444", b="#fecaca", c="#1f2937", k="#000", l="#fff")), 180, 104, 260, 150
    )
    w = text(
        "CAR CHASE", "Racing Sans One", 100, style="italic", fill="url(#cc)", stroke="#000", sw=12
    )
    body += fit(extrude(w, 6, 6, 6, "#7c2d12") + w, 56, 264, 400, 100)
    body += fit(
        text("ACTION CLASSICS", "Oswald", 40, weight=700, fill="#fff", ls=10), 150, 370, 212, 26
    )
    return svg(body, d)


@net("Stunt Double", "action", "adventure")
def stunt_double():
    stripes = "".join(
        f'<polygon points="{x},60 {x + 30},60 {x - 30},460 {x - 60},460" fill="#facc15"/>'
        for x in range(30, 600, 60)
    )
    back = '<g filter="url(#sh)"><rect x="40" y="60" width="432" height="400" rx="24" fill="#111"/></g>'
    back += f'<clipPath id="sdc"><rect x="40" y="60" width="432" height="400" rx="24"/></clipPath><g clip-path="url(#sdc)" opacity=".9">{stripes}</g>'
    back += '<rect x="70" y="120" width="372" height="280" rx="16" fill="#111" stroke="#facc15" stroke-width="5"/>'
    w = text("STUNT", "Black Ops One", 100, fill="#facc15", stroke="#000", sw=8)
    w2 = text("DOUBLE", "Black Ops One", 100, fill="#fff", stroke="#000", sw=8)
    back += fit(f'<g opacity=".35" transform="translate(10 8)">{w}</g>{w}', 96, 140, 320, 120)
    back += fit(f'<g opacity=".35" transform="translate(10 8)">{w2}</g>{w2}', 96, 266, 320, 112)
    return svg(back, SH)


@net("Freeze Frame", "action", "adventure")
def freeze_frame():
    return L.film_frame(
        "FREEZE FRAME",
        "ACTION CLASSICS",
        font="Anton",
        ink="#0c4a6e",
        film="#0b1220",
        frame_fill="#e0f7ff",
        edge="#0b1220",
    )


@net("Code Three", "action", "police", "crime")
def code_three():
    d = (
        SH
        + glow("red", "#ff1f1f", blur=10, strength=2)
        + glow("blue", "#1f6bff", blur=10, strength=2)
        + lin("lens_r", [(0, "#ff8a8a"), (1, "#c00000")])
        + lin("lens_b", [(0, "#8ab4ff"), (1, "#0033c0")])
    )
    body = '<g filter="url(#sh)"><rect x="40" y="88" width="432" height="96" rx="40" fill="#1f2937" stroke="#030712" stroke-width="7"/></g>'
    body += '<g filter="url(#red)"><rect x="58" y="102" width="186" height="68" rx="30" fill="url(#lens_r)"/></g>'
    body += '<g filter="url(#blue)"><rect x="268" y="102" width="186" height="68" rx="30" fill="url(#lens_b)"/></g>'
    body += '<rect x="250" y="102" width="12" height="68" fill="#e5e7eb"/>'
    body += '<g filter="url(#sh)"><rect x="56" y="208" width="400" height="232" rx="18" fill="#f9fafb" stroke="#030712" stroke-width="7"/></g>'
    body += '<rect x="56" y="208" width="400" height="60" rx="18" fill="#111827"/><rect x="56" y="250" width="400" height="18" fill="#111827"/>'
    body += fit(
        text("POLICE ACTION", "Oswald", 40, weight=700, fill="#f9fafb", ls=10), 140, 222, 232, 32
    )
    body += fit(text("CODE 3", "Russo One", 100, fill="#111827"), 92, 284, 328, 110)
    body += fit(
        text("CODE THREE", "Oswald", 40, weight=700, fill="#b91c1c", ls=10), 176, 400, 160, 26
    )
    return svg(body, d)


def _stakeout() -> str:
    g = '<rect x="40" y="20" width="432" height="400" fill="url(#night)"/>'
    for x, y in ((90, 70), (160, 50), (400, 80), (330, 46), (440, 140)):
        g += f'<circle cx="{x}" cy="{y}" r="2.5" fill="#fff"/>'
    g += '<polygon points="140,92 60,330 230,330" fill="#fef3c7" opacity=".28"/>'
    g += '<rect x="134" y="80" width="12" height="260" fill="#111"/><path d="M140 84 Q176 66 196 92" fill="none" stroke="#111" stroke-width="10"/>'
    g += '<rect x="186" y="88" width="22" height="14" rx="3" fill="#fde68a"/>'
    g += '<path d="M230 300 L262 250 Q272 236 300 236 L376 236 Q396 236 410 252 L440 300 L452 300 Q466 300 466 316 L466 336 L220 336 L220 316 Q220 300 230 300 Z" fill="#0f172a" stroke="#000" stroke-width="4"/>'
    g += '<path d="M270 296 L284 256 L330 256 L330 296 Z M340 296 L340 256 L384 256 L404 296 Z" fill="#334155"/>'
    g += '<circle cx="300" cy="278" r="9" fill="#fbbf24" opacity=".9"/>'
    g += '<circle cx="268" cy="338" r="22" fill="#000"/><circle cx="420" cy="338" r="22" fill="#000"/>'
    g += '<rect x="40" y="340" width="432" height="80" fill="#1e293b"/>'
    return g


@net("Stakeout", "action", "crime", "police")
def stakeout():
    return L.emblem(
        _stakeout(),
        "STAKEOUT",
        font="Anton",
        ink="#fef3c7",
        band="#991b1b",
        rim="#cbd5e1",
        edge="#020617",
        defs=lin("night", [(0, "#0b1026"), (1, "#334155")]),
        ls=8,
    )


def _chopper() -> str:
    c = '<ellipse cx="100" cy="30" rx="96" ry="7" fill="#cbd5e1" opacity=".75"/>'
    c += '<rect x="96" y="30" width="8" height="22" fill="#1f2937"/>'
    c += '<path d="M40 70 Q44 48 90 48 L130 48 Q166 50 170 80 Q172 108 140 112 L70 112 Q40 108 40 70 Z" fill="#dc2626" stroke="#111" stroke-width="5"/>'
    c += (
        '<path d="M126 56 Q158 60 162 84 L126 84 Z" fill="#bae6fd" stroke="#111" stroke-width="4"/>'
    )
    c += '<path d="M44 76 L-40 64 L-46 56 L-56 58 L-52 84 L-40 80 L44 92 Z" fill="#dc2626" stroke="#111" stroke-width="5" stroke-linejoin="round"/>'
    c += '<ellipse cx="-50" cy="70" rx="5" ry="22" fill="#cbd5e1" opacity=".8"/>'
    c += '<path d="M64 112 L60 128 M140 112 L144 128 M44 128 L164 128" stroke="#111" stroke-width="6" stroke-linecap="round"/>'
    return c


@net("Chopper TV", "action", "adventure")
def chopper_tv():
    d = (
        SH
        + lin("beam", [(0, "#fef9c3"), (1, "#fef9c300")])
        + lin("dusk2", [(0, "#1e1b4b"), (1, "#7c2d12")])
    )
    body = '<g filter="url(#sh)"><circle cx="256" cy="230" r="196" fill="url(#dusk2)" stroke="#0b0820" stroke-width="8"/></g>'
    body += (
        '<clipPath id="chc"><circle cx="256" cy="230" r="188"/></clipPath><g clip-path="url(#chc)">'
    )
    body += '<polygon points="268,206 170,430 370,430" fill="url(#beam)" opacity=".7"/>'
    body += '<path d="M60 400 L110 330 L150 360 L210 300 L270 352 L330 310 L400 370 L452 330 L460 430 L60 430 Z" fill="#0b0820"/>'
    body += "</g>"
    body += f'<g filter="url(#sh)">{fit(_chopper(), 120, 88, 280, 140)}</g>'
    body += '<g filter="url(#sh)"><rect x="70" y="384" width="372" height="88" rx="14" fill="#dc2626" stroke="#0b0820" stroke-width="7"/></g>'
    body += fit(text("CHOPPER TV", "Russo One", 100, fill="#fff"), 92, 398, 328, 60)
    return svg(body, d)


@net("Muscle Car TV", "action", "cars", "70s")
def muscle_car_tv():
    d = (
        SH
        + lin("paint", [(0, "#ef4444"), (1, "#7f1d1d")])
        + lin("chromebar", [(0, "#ffffff"), (0.45, "#9ca3af"), (0.55, "#4b5563"), (1, "#e5e7eb")])
    )
    body = '<g filter="url(#sh)"><path d="M60 60 L452 60 Q480 260 452 460 L60 460 Q32 260 60 60 Z" fill="url(#paint)" stroke="#1c0505" stroke-width="8"/></g>'
    for x in (196, 284):
        body += f'<rect x="{x}" y="64" width="32" height="392" fill="#f9fafb"/><rect x="{x + 6}" y="64" width="4" height="392" fill="#111" opacity=".35"/>'
    body += '<g filter="url(#sh)"><rect x="46" y="198" width="420" height="132" rx="20" fill="url(#chromebar)" stroke="#111" stroke-width="7"/></g>'
    body += '<rect x="62" y="212" width="388" height="104" rx="12" fill="#111827"/>'
    body += fit(text("MUSCLE CAR", "Bebas Neue", 100, fill="#f9fafb", ls=6), 78, 220, 356, 66)
    body += fit(
        text("TELEVISION", "Oswald", 40, weight=700, fill="#facc15", ls=12), 172, 286, 168, 22
    )
    return svg(body, d)


@net("High Octane", "action", "cars")
def high_octane():
    d = SH + rad("globe", [(0, "#ffffff"), (0.75, "#f1f5f9"), (1, "#cbd5e1")], cx=0.4, cy=0.35)
    body = '<g filter="url(#sh)"><rect x="196" y="384" width="120" height="88" rx="8" fill="#1f2937" stroke="#000" stroke-width="6"/>'
    body += (
        '<circle cx="256" cy="226" r="196" fill="url(#globe)" stroke="#111" stroke-width="8"/></g>'
    )
    body += '<circle cx="256" cy="226" r="176" fill="none" stroke="#dc2626" stroke-width="22"/>'
    body += '<circle cx="256" cy="226" r="150" fill="none" stroke="#111" stroke-width="3"/>'
    d2, top = arc_text("HIGH", "Bowlby One", 256, 226, 120, 54, fill="#111", ls=10, pid="hoT")
    body += top
    body += fit(
        text("OCTANE", "Bowlby One", 100, fill="#dc2626", stroke="#111", sw=6), 104, 200, 304, 76
    )
    body += '<polygon points="256,290 236,326 250,326 244,356 276,316 262,316 268,290" fill="#facc15" stroke="#111" stroke-width="4" stroke-linejoin="round"/>'
    return svg(body, d + d2)


@net("Road Block", "action", "adventure")
def road_block():
    return L.plate(
        "ROAD BLOCK",
        "ACTION TV",
        font="Russo One",
        ink="#111",
        stripe=("#f97316", "#f9fafb"),
        edge="#111",
    )


def _aviators() -> str:
    lens = "M0 20 Q0 0 30 0 L110 0 Q140 0 136 30 Q128 96 70 100 Q8 100 0 40 Z"
    g = f'<path d="{lens}" fill="url(#lensfill)" stroke="#d4a017" stroke-width="7"/>'
    g += f'<path d="{lens}" fill="url(#lensfill)" stroke="#d4a017" stroke-width="7" transform="translate(296 0) scale(-1 1) translate(-6 0)"/>'
    g += '<path d="M136 24 Q148 10 160 24" fill="none" stroke="#d4a017" stroke-width="7"/>'
    g += '<path d="M0 10 L-30 6 M296 10 L326 6" stroke="#d4a017" stroke-width="7" stroke-linecap="round"/>'
    g += '<path d="M20 22 Q50 14 80 30" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity=".7"/>'
    return g


@net("Aviator Shades", "action", "adventure", "80s")
def aviator_shades():
    d = SH + lin("lensfill", [(0, "#fb923c"), (0.5, "#db2777"), (1, "#4c1d95")])
    body = '<g filter="url(#sh)"><rect x="34" y="70" width="444" height="372" rx="40" fill="#0f172a" stroke="#020617" stroke-width="7"/></g>'
    body += f'<g filter="url(#sh)">{fit(_aviators(), 70, 104, 372, 150)}</g>'
    body += fit(text("AVIATOR", "Michroma", 100, fill="#f8fafc", ls=8), 74, 286, 364, 58)
    body += fit(text("SHADES", "Yellowtail", 100, fill="#fb923c"), 150, 340, 212, 80)
    return svg(body, d)


@net("Burnout", "action", "cars")
def burnout():
    d = SH + lin("bo", [(0, "#1f2937"), (1, "#030712")])
    hexa = " ".join(
        f"{256 + 220 * math.cos(math.radians(a)):.1f},{256 + 200 * math.sin(math.radians(a)):.1f}"
        for a in range(0, 360, 60)
    )
    body = f'<g filter="url(#sh)"><polygon points="{hexa}" fill="url(#bo)" stroke="#000" stroke-width="8" stroke-linejoin="round"/></g>'
    body += f'<clipPath id="boc"><polygon points="{hexa}"/></clipPath><g clip-path="url(#boc)">'
    for row in range(2):
        for col in range(16):
            body += f'<rect x="{30 + col * 30}" y="{318 + row * 30}" width="30" height="30" fill="{"#f9fafb" if (row + col) % 2 else "#111"}"/>'
    body += "</g>"
    w = text(
        "BURNOUT", "Racing Sans One", 100, style="italic", fill="#f97316", stroke="#000", sw=10
    )
    body += fit(extrude(w, 5, 5, 5, "#7c2d12") + w, 60, 150, 392, 120)
    body += fit(
        text("HIGH-SPEED CLASSICS", "Oswald", 40, weight=700, fill="#f9fafb", ls=6),
        140,
        270,
        232,
        30,
    )
    return svg(body, d)


def _rescue() -> str:
    g = '<rect x="0" y="0" width="512" height="512" fill="url(#sea)"/>'
    g += '<path d="M0 330 Q64 310 128 330 T256 330 T384 330 T512 330 L512 512 L0 512 Z" fill="#1e3a8a" opacity=".6"/>'
    ring = '<circle cx="256" cy="210" r="104" fill="#f9fafb" stroke="#111" stroke-width="7"/><circle cx="256" cy="210" r="52" fill="url(#sea)" stroke="#111" stroke-width="7"/>'
    for a in (0, 90, 180, 270):
        ring += f'<path d="M256 210 L{256 + 120 * math.cos(math.radians(a - 22)):.0f} {210 + 120 * math.sin(math.radians(a - 22)):.0f} A120 120 0 0 1 {256 + 120 * math.cos(math.radians(a + 22)):.0f} {210 + 120 * math.sin(math.radians(a + 22)):.0f} Z" fill="#dc2626"/>'
    ring = f'<clipPath id="rr"><path d="M256 106 A104 104 0 1 1 255.9 106 Z M256 158 A52 52 0 1 0 256.1 158 Z" fill-rule="evenodd"/></clipPath><g clip-path="url(#rr)">{ring}</g>'
    g += '<circle cx="256" cy="210" r="104" fill="#f9fafb" stroke="#111" stroke-width="7"/>' + ring
    g += '<circle cx="256" cy="210" r="104" fill="none" stroke="#111" stroke-width="7"/><circle cx="256" cy="210" r="52" fill="none" stroke="#111" stroke-width="7"/>'
    return g


@net("Rescue Squad", "action", "adventure")
def rescue_squad():
    return L.patch(
        _rescue(),
        "RESCUE SQUAD",
        font="Archivo Black",
        ink="#fff",
        band="#dc2626",
        rim="#fde68a",
        edge="#0b1324",
        defs=lin("sea", [(0, "#0ea5e9"), (1, "#0c4a6e")]),
    )


@net("Undercover", "action", "crime", "spies")
def undercover():
    d = SH
    body = '<g filter="url(#sh)"><rect x="34" y="96" width="444" height="320" rx="22" fill="#e7e5e4" stroke="#1c1917" stroke-width="7"/></g>'
    body += fit(
        S.fedora(P(a="#292524", b="#57534e", c="#b91c1c", k="#0c0a09", l="#a8a29e")),
        176,
        112,
        160,
        110,
    )
    body += fit(text("UNDERCOVER", "Special Elite", 100, fill="#1c1917", ls=4), 66, 230, 380, 72)
    body += '<rect x="96" y="318" width="210" height="36" fill="#0c0a09"/><rect x="320" y="318" width="96" height="36" fill="#0c0a09"/>'
    body += '<g transform="rotate(-12 380 170)"><rect x="318" y="146" width="132" height="46" fill="none" stroke="#b91c1c" stroke-width="5"/>'
    body += (
        fit(text("CLASSIFIED", "Special Elite", 100, fill="#b91c1c"), 326, 154, 116, 30) + "</g>"
    )
    return svg(body, d)


@net("Mission Control", "action", "adventure", "space")
def mission_control():
    d = (
        SH
        + rad("scope", [(0, "#14532d"), (1, "#022c22")])
        + lin("sweep", [(0, "#4ade80"), (1, "#4ade8000")], x2=1, y2=0)
    )
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="48" fill="#1f2937" stroke="#030712" stroke-width="7"/></g>'
    body += (
        '<circle cx="256" cy="206" r="148" fill="url(#scope)" stroke="#9ca3af" stroke-width="8"/>'
    )
    for r in (100, 52):
        body += f'<circle cx="256" cy="206" r="{r}" fill="none" stroke="#4ade80" stroke-width="2" opacity=".6"/>'
    body += '<path d="M108 206 L404 206 M256 58 L256 354" stroke="#4ade80" stroke-width="2" opacity=".6"/>'
    body += '<path d="M256 206 L398 166 A148 148 0 0 0 330 78 Z" fill="url(#sweep)" opacity=".7"/>'
    for x, y in ((320, 140), (196, 260), (300, 280)):
        body += f'<circle cx="{x}" cy="{y}" r="7" fill="#bbf7d0"/>'
    body += fit(
        text("MISSION CONTROL", "Orbitron", 100, weight=700, fill="#f9fafb", ls=2), 64, 372, 384, 52
    )
    body += fit(
        text("ACTION · ADVENTURE · SPACE", "Oswald", 40, weight=600, fill="#4ade80", ls=4),
        120,
        428,
        272,
        22,
    )
    return svg(body, d)


@net("Tailpipe", "action", "cars")
def tailpipe():
    d = SH + lin("tp", [(0, "#fde047"), (0.5, "#f97316"), (1, "#dc2626")], x2=1, y2=0)
    body = '<g filter="url(#sh)"><path d="M78 140 L478 140 L434 372 L34 372 Z" fill="#111827" stroke="#000" stroke-width="8" stroke-linejoin="round"/></g>'
    body += '<path d="M64 330 L452 330 L446 358 L58 358 Z" fill="url(#tp)"/>'
    w = text(
        "TAILPIPE", "Racing Sans One", 100, style="italic", fill="#f9fafb", stroke="#000", sw=8
    )
    body += fit(w, 70, 172, 380, 120)
    body += fit(
        text("ACTION CLASSICS", "Oswald", 40, weight=700, fill="#f97316", ls=10), 150, 290, 212, 30
    )
    return svg(body, d)


# ================================================================ westerns


@net("Horse Opera", "westerns")
def horse_opera():
    centre = centred(S.horseshoe(P(a="#d4a94a", b="#fde9b0", k="#2b1408", l="#fff")), 256, 256, 210)
    return L.seal(
        centre,
        "HORSE OPERA",
        "WESTERNS",
        font="Rye",
        ring="#7f1d1d",
        ring_ink="#fde9b0",
        face="#2b1408",
        edge="#1a0a03",
        dots="#d4a94a",
        ls=4,
    )


@net("Ten-Gallon TV", "westerns")
def ten_gallon_tv():
    return L.sym_word(
        S.cowboy_hat(P(a="#a16207", b="#713f12", c="#fde68a", k="#1c0d03", l="#fef3c7")),
        "TEN-GALLON",
        font="Alfa Slab One",
        ink="#fde68a",
        edge="#1c0d03",
        sub="TELEVISION",
        sub_font="Oswald",
        sub_ink="#fef3c7",
        ls=2,
    )


def _wagon() -> str:
    g = '<rect x="40" y="20" width="432" height="400" fill="url(#prairie)"/>'
    g += '<circle cx="380" cy="120" r="44" fill="#fff1c1" opacity=".85"/>'
    g += '<path d="M40 300 Q160 270 300 290 Q400 300 472 280 L472 420 L40 420 Z" fill="#b45309"/>'
    k = "#2b1408"
    g += f'<path d="M150 270 L150 170 Q150 120 200 120 L300 120 Q352 120 352 170 L352 270 Z" fill="#fdf6e3" stroke="{k}" stroke-width="6"/>'
    for x in (200, 250, 300):
        g += f'<path d="M{x} 122 Q{x - 4} 200 {x} 270" fill="none" stroke="{k}" stroke-width="3" opacity=".55"/>'
    g += f'<rect x="130" y="262" width="246" height="34" rx="6" fill="#7c2d12" stroke="{k}" stroke-width="6"/>'
    for cx in (176, 330):
        g += f'<circle cx="{cx}" cy="316" r="38" fill="none" stroke="{k}" stroke-width="8"/><circle cx="{cx}" cy="316" r="6" fill="{k}"/>'
        for a in range(0, 180, 30):
            r = math.radians(a)
            g += f'<line x1="{cx - 36 * math.cos(r):.0f}" y1="{316 - 36 * math.sin(r):.0f}" x2="{cx + 36 * math.cos(r):.0f}" y2="{316 + 36 * math.sin(r):.0f}" stroke="{k}" stroke-width="4"/>'
    return g


@net("Chuckwagon", "westerns")
def chuckwagon():
    return L.emblem(
        _wagon(),
        "CHUCKWAGON",
        font="Rye",
        ink="#fef3c7",
        band="#7c2d12",
        rim="#fde68a",
        edge="#2b1408",
        defs=lin("prairie", [(0, "#f59e0b"), (1, "#fde68a")]),
        ls=2,
    )


@net("Tumbleweed", "westerns")
def tumbleweed():
    d = (
        SH
        + lin("dusk", [(0, "#7c2d12"), (0.55, "#ea580c"), (1, "#fcd34d")])
        + lin("tw", [(0, "#fff7e0"), (1, "#f5c77a")])
    )
    body = '<defs><clipPath id="twc"><rect x="40" y="70" width="432" height="372" rx="28"/></clipPath></defs>'
    body += _panel(40, 70, 432, 372, "#2b1408", rx=28)
    body += (
        '<g clip-path="url(#twc)"><rect x="40" y="70" width="432" height="250" fill="url(#dusk)"/>'
    )
    body += '<circle cx="256" cy="300" r="92" fill="#fde68a" opacity=".9"/>'
    body += '<path d="M40 300 L120 300 L138 262 L196 262 L212 300 L330 300 L342 276 L392 276 L404 300 L472 300 L472 442 L40 442 Z" fill="#2b1408"/></g>'
    body += '<rect x="40" y="70" width="432" height="372" rx="28" fill="none" stroke="#f5c77a" stroke-width="8"/>'
    body += '<rect x="56" y="86" width="400" height="340" rx="18" fill="none" stroke="#f5c77a" stroke-width="2" opacity=".6"/>'
    w = _word("TUMBLEWEED", "Rye", "url(#tw)", "#2b1408", 6)
    body += fit(extrude(w, 6, 8, 8, "#000") + w, 70, 318, 372, 74)
    body += fit(
        text("WESTERN CLASSICS", "Oswald", 40, weight=600, fill="#f5c77a", ls=12), 150, 400, 212, 22
    )
    return svg(body, d)


@net("Hitching Post", "westerns")
def hitching_post():
    d = (
        SH
        + lin("log", [(0, "#8b5a2b"), (0.5, "#a0703c"), (1, "#5c3a17")], x2=1, y2=0)
        + lin("board", [(0, "#c08a4d"), (1, "#8b5a2b")])
    )
    body = '<g filter="url(#sh)">'
    for x in (64, 408):
        body += f'<rect x="{x}" y="70" width="40" height="400" rx="8" fill="url(#log)" stroke="#2b1408" stroke-width="6"/>'
    body += '<rect x="40" y="70" width="432" height="34" rx="12" fill="url(#log)" stroke="#2b1408" stroke-width="6"/>'
    body += '<rect x="78" y="130" width="356" height="176" rx="14" fill="url(#board)" stroke="#2b1408" stroke-width="7"/></g>'
    for x in (150, 362):
        body += f'<line x1="{x}" y1="104" x2="{x}" y2="132" stroke="#2b1408" stroke-width="5"/>'
    body += fit(text("HITCHING", "Rye", 100, fill="#2b1408"), 100, 148, 312, 70)
    body += fit(text("POST", "Rye", 100, fill="#7f1d1d"), 166, 220, 180, 70)
    body += '<rect x="104" y="390" width="304" height="20" rx="8" fill="url(#log)" stroke="#2b1408" stroke-width="5"/>'
    body += fit(
        text("WESTERNS", "Oswald", 40, weight=700, fill="#fde9b0", stroke="#2b1408", sw=8, ls=12),
        170,
        334,
        172,
        34,
    )
    return svg(body, d)


@net("Saddle Up", "westerns")
def saddle_up():
    d = SH + rad("tooled", [(0, "#b45309"), (1, "#5a2a08")])
    body = '<g filter="url(#sh)"><ellipse cx="256" cy="256" rx="228" ry="186" fill="url(#tooled)" stroke="#2b1408" stroke-width="8"/></g>'
    body += '<ellipse cx="256" cy="256" rx="206" ry="164" fill="none" stroke="#e8c27a" stroke-width="10" stroke-dasharray="16 6"/>'
    body += '<ellipse cx="256" cy="256" rx="186" ry="144" fill="none" stroke="#2b1408" stroke-width="3"/>'
    for a in range(0, 360, 45):
        x, y = 256 + 170 * math.cos(math.radians(a)), 256 + 130 * math.sin(math.radians(a))
        body += f'<polygon points="{star(x, y, 9, 4, 4)}" fill="#e8c27a"/>'
    body += fit(
        text("SADDLE", "Rye", 100, fill="#fde9b0", stroke="#2b1408", sw=8), 122, 168, 268, 84
    )
    body += fit(text("UP!", "Rye", 100, fill="#fbbf24", stroke="#2b1408", sw=8), 196, 252, 120, 84)
    return svg(body, d)


def _skull() -> str:
    k = "#2b1408"
    g = f'<path d="M100 40 Q60 70 0 50 Q30 80 74 86 Q80 96 76 110 Q84 150 100 170 Q116 150 124 110 Q120 96 126 86 Q170 80 200 50 Q140 70 100 40 Z" fill="#fef3c7" stroke="{k}" stroke-width="6" stroke-linejoin="round"/>'
    g += f'<ellipse cx="86" cy="98" rx="9" ry="12" fill="{k}"/><ellipse cx="114" cy="98" rx="9" ry="12" fill="{k}"/>'
    g += f'<path d="M94 142 L94 154 M106 142 L106 154" stroke="{k}" stroke-width="5" stroke-linecap="round"/>'
    return g


@net("Stampede", "westerns")
def stampede():
    d = SH + lin("dust", [(0, "#c2410c"), (1, "#7c2d12")])
    body = '<g filter="url(#sh)"><rect x="34" y="170" width="444" height="170" rx="18" fill="url(#dust)" stroke="#2b1408" stroke-width="8"/></g>'
    body += f'<g filter="url(#sh)">{fit(_skull(), 146, 30, 220, 160)}</g>'
    body += fit(
        text("STAMPEDE", "Holtwood One SC", 100, fill="#fde9b0", stroke="#2b1408", sw=6),
        60,
        196,
        392,
        96,
    )
    body += fit(
        text("WESTERNS ALL DAY", "Oswald", 40, weight=700, fill="#fde9b0", ls=8), 156, 296, 200, 28
    )
    return svg(body, d)


@net("Lasso", "westerns")
def lasso():
    d = SH + lin("rope", [(0, "#e7c27d"), (1, "#a8742b")])
    loop = '<ellipse cx="256" cy="236" rx="200" ry="170" fill="none" stroke="#5a3a12" stroke-width="30"/>'
    loop += '<ellipse cx="256" cy="236" rx="200" ry="170" fill="none" stroke="url(#rope)" stroke-width="22"/>'
    loop += '<ellipse cx="256" cy="236" rx="200" ry="170" fill="none" stroke="#5a3a12" stroke-width="3" stroke-dasharray="6 12" opacity=".8"/>'
    loop += '<path d="M330 400 Q360 446 420 470" fill="none" stroke="#5a3a12" stroke-width="22" stroke-linecap="round"/>'
    loop += '<path d="M330 400 Q360 446 420 470" fill="none" stroke="url(#rope)" stroke-width="15" stroke-linecap="round"/>'
    body = (
        '<g filter="url(#sh)"><ellipse cx="256" cy="236" rx="180" ry="150" fill="#1f2937"/></g>'
        + f'<g filter="url(#sh)">{loop}</g>'
    )
    body += fit(text("Lasso", "Sancreek", 100, fill="#fde9b0"), 120, 150, 272, 118)
    body += fit(
        text("WESTERN CLASSICS", "Oswald", 40, weight=700, fill="#e7c27d", ls=8), 160, 282, 192, 28
    )
    return svg(body, d)


def _boothill() -> str:
    g = '<rect x="0" y="0" width="512" height="512" fill="url(#bhdusk)"/>'
    g += '<circle cx="256" cy="230" r="70" fill="#fecaca" opacity=".6"/>'
    g += '<path d="M60 300 Q256 170 452 300 L452 512 L60 512 Z" fill="#3b1d0e"/>'
    for x, y, s in ((190, 226, 1), (256, 206, 1.2), (322, 228, 1)):
        g += f'<g transform="translate({x} {y}) scale({s})"><rect x="-5" y="-40" width="10" height="56" fill="#3b1d0e"/><rect x="-20" y="-28" width="40" height="9" fill="#3b1d0e"/></g>'
    return g


@net("Boot Hill", "westerns")
def boot_hill():
    return L.roundel(
        _boothill(),
        "BOOT HILL",
        font="Rye",
        ink="#fde9b0",
        disc="#7c2d12",
        rim="#fde9b0",
        edge="#1a0a03",
        bar="#1a0a03",
        bar_y=300,
        ls=4,
        defs=lin("bhdusk", [(0, "#7c3aed"), (0.6, "#f97316"), (1, "#fbbf24")]),
    )


def _mesa() -> str:
    g = '<rect x="0" y="0" width="200" height="200" fill="url(#mesasky)"/>'
    g += '<circle cx="140" cy="62" r="22" fill="#fff1c1"/>'
    g += '<path d="M0 150 L30 150 L40 96 L90 96 L100 150 L200 150 L200 200 L0 200 Z" fill="#9a3412"/>'
    g += '<path d="M120 150 L130 120 L170 120 L178 150 Z" fill="#c2410c"/>'
    g += '<path d="M0 170 Q100 150 200 176 L200 200 L0 200 Z" fill="#7c2d12"/>'
    return g


@net("Dusty Trails", "westerns")
def dusty_trails():
    return L.postage(
        _mesa().replace("url(#mesasky)", "#fdba74"),
        "DUSTY TRAILS",
        "5¢",
        font="Rye",
        ink="#3b1d0e",
        paper="#fdf3dc",
        field="#fde68a",
        edge="#3b1d0e",
    )


# ========================================================= mystery & crime


@net("Whodunit", "mystery", "crime")
def whodunit():
    return L.letter_swap(
        "WH",
        S.magnifier(P(a="#fbbf24", b="#bae6fd", k="#0f172a", l="#fff")),
        "DUNIT",
        font="Playfair Display",
        weight=900,
        ink="#f8fafc",
        edge="#0f172a",
        sym_size=84,
        gap=4,
        sym_dy=-36,
        sub="MYSTERY THEATER",
        sub_font="Oswald",
        sub_ink="#fbbf24",
        sw=12,
    )


@net("Red Herring", "mystery", "crime")
def red_herring():
    fish = S.fish(P(a="#dc2626", b="#fca5a5", k="#3b0707", l="#fff"))
    return L.tile_word(
        fish,
        "RED HERRING",
        font="Playfair Display",
        ink="#fef2f2",
        edge="#3b0707",
        tile="#fff7ed",
        tile2="#fed7aa",
        weight=900,
        sub="MYSTERIES & CLUES",
        sub_ink="#fca5a5",
        shape="circle",
        ring="#dc2626",
        ls=2,
    )


@net("The Butler Did It", "mystery", "whodunits")
def the_butler_did_it():
    return L.deco(
        "THE BUTLER DID IT",
        "MYSTERIES",
        font="Cinzel",
        field="#0b0b10",
        weight=700,
        ls=4,
    )


@net("Plot Twist", "mystery", "suspense")
def plot_twist():
    centre = centred(S.spiral(P(a="#a78bfa", b="#ede9fe", k="#1e1b4b", l="#fff")), 256, 170, 220)
    return L.roundel(
        centre,
        "PLOT TWIST",
        font="Archivo Black",
        ink="#fff",
        disc="#312e81",
        rim="#c4b5fd",
        edge="#0f0d2e",
        bar="#7c3aed",
        bar_y=300,
        ls=4,
    )


@net("Trench Coat", "mystery", "crime", "film noir")
def trench_coat():
    d = SH + lin("tc", [(0, "#1f2937"), (1, "#030712")])
    body = '<g filter="url(#sh)"><rect x="40" y="50" width="432" height="412" rx="22" fill="url(#tc)" stroke="#000" stroke-width="7"/></g>'
    rng = random.Random(2)
    for _ in range(40):
        x, y = rng.uniform(50, 460), rng.uniform(60, 440)
        body += f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x - 8:.0f}" y2="{y + 26:.0f}" stroke="#9ca3af" stroke-width="2" opacity=".35"/>'
    k = "#000"
    fig = f'<path d="M60 40 Q100 10 140 40 L150 54 L50 54 Z" fill="{k}"/><rect x="30" y="52" width="140" height="10" rx="5" fill="{k}"/>'
    fig += f'<path d="M64 62 Q100 92 136 62 L150 130 Q170 160 176 250 L24 250 Q30 160 50 130 Z" fill="{k}"/>'
    fig += '<path d="M64 62 L100 120 L136 62" fill="none" stroke="#374151" stroke-width="4"/>'
    body += f'<g opacity=".95">{fit(fig, 176, 70, 160, 200)}</g>'
    body += '<line x1="40" y1="272" x2="472" y2="272" stroke="#fbbf24" stroke-width="4"/>'
    body += fit(text("TRENCH COAT", "Bebas Neue", 100, fill="#f9fafb", ls=6), 70, 290, 372, 88)
    body += fit(
        text("CRIME · NOIR · MYSTERY", "Oswald", 40, weight=600, fill="#fbbf24", ls=6),
        140,
        392,
        232,
        28,
    )
    return svg(body, d)


@net("Gumshoe", "mystery", "crime", "detectives")
def gumshoe():
    return L.stamp(
        "GUMSHOE",
        "PRIVATE",
        "DETECTIVES",
        ink="#1e3a8a",
        paper="#e9dfc7",
        word_font="Black Ops One",
        round_=False,
        tilt=-5,
        wear=0.85,
    )


@net("The Lineup", "crime", "police", "mystery")
def the_lineup():
    d = SH
    body = '<g filter="url(#sh)"><rect x="36" y="44" width="440" height="424" rx="20" fill="#e5e7eb" stroke="#111827" stroke-width="7"/></g>'
    for i, y in enumerate(range(80, 440, 44)):
        body += f'<line x1="56" y1="{y}" x2="456" y2="{y}" stroke="#6b7280" stroke-width="3"/>'
        body += text(
            f"{7 - i // 2}'{('0' if i % 2 == 0 else '6')}",
            "Oswald",
            22,
            weight=600,
            fill="#6b7280",
            x=78,
            y=y - 6,
        )
    body += '<g filter="url(#sh)"><rect x="76" y="176" width="360" height="168" rx="12" fill="#111827"/></g>'
    body += fit(text("THE", "Oswald", 100, weight=700, fill="#facc15", ls=20), 206, 190, 100, 34)
    body += fit(text("LINEUP", "Anton", 100, fill="#f9fafb", ls=10), 100, 228, 312, 100)
    body += fit(
        text("CRIME DRAMA", "Oswald", 40, weight=700, fill="#111827", ls=10), 176, 382, 160, 30
    )
    return svg(body, d)


@net("Private Eye", "mystery", "detectives", "crime")
def private_eye():
    d = (
        SH
        + lin("door", [(0, "#5b3a1e"), (1, "#2e1b0c")], x2=1, y2=1)
        + lin("glass", [(0, "#fde9b6"), (1, "#d9a85b")], x2=1, y2=1)
    )
    d += lin("leaf", [(0, "#fff3c4"), (0.5, "#e2b13c"), (1, "#a8741a")])
    body = _panel(70, 40, 372, 432, "url(#door)", rx=16, edge="#1a0f06", sw=6)
    body += '<rect x="104" y="74" width="304" height="300" rx="6" fill="url(#glass)" stroke="#1a0f06" stroke-width="6"/>'
    body += '<path d="M120 90 L210 90 L130 300 L120 300 Z" fill="#fff" opacity=".18"/>'
    for y in (74, 374):
        body += f'<rect x="96" y="{y - 8}" width="320" height="16" rx="4" fill="#3b2410"/>'
    w = _word("PRIVATE", "Abril Fatface", "url(#leaf)", "#1a0f06", 5, ls=4)
    body += fit(w, 128, 128, 256, 78)
    w2 = _word("EYE", "Abril Fatface", "url(#leaf)", "#1a0f06", 5, ls=14)
    body += fit(w2, 160, 214, 192, 100)
    body += '<line x1="150" y1="332" x2="362" y2="332" stroke="#1a0f06" stroke-width="3"/>'
    body += fit(
        text("INVESTIGATIONS", "Cinzel", 40, weight=700, fill="#1a0f06", ls=8), 150, 340, 212, 22
    )
    body += '<circle cx="380" cy="420" r="13" fill="url(#leaf)" stroke="#1a0f06" stroke-width="4"/>'
    body += fit(
        text("DETECTIVE DRAMA", "Oswald", 40, weight=600, fill="#e2b13c", ls=10), 130, 402, 200, 22
    )
    return svg(body, d)


@net("Night Beat", "crime", "police")
def night_beat():
    return L.neon(
        "NIGHT BEAT",
        "CRIME DRAMA",
        font="Bebas Neue",
        tube="#60a5fa",
        glow_c="#2563eb",
        frame="#f472b6",
        sub_tube="#fbcfe8",
        sub_font="Oswald",
        sym='<g transform="translate(386 132)"><path d="M0 -26 A26 26 0 1 0 22 14 A20 20 0 1 1 0 -26 Z" fill="#fde68a"/></g>',
    )


def _deerstalker() -> str:
    k = "#1c1917"
    g = f'<path d="M30 120 Q30 40 100 36 Q170 40 170 120 Z" fill="url(#tweed)" stroke="{k}" stroke-width="6"/>'
    g += f'<path d="M30 118 L-14 132 Q10 150 40 134 Z" fill="url(#tweed)" stroke="{k}" stroke-width="6" stroke-linejoin="round"/>'
    g += f'<path d="M170 118 L214 132 Q190 150 160 134 Z" fill="url(#tweed)" stroke="{k}" stroke-width="6" stroke-linejoin="round"/>'
    g += f'<path d="M100 36 L100 120 M62 46 Q72 80 66 120 M138 46 Q128 80 134 120" fill="none" stroke="{k}" stroke-width="3" opacity=".6"/>'
    g += '<path d="M48 70 Q60 40 100 28 Q140 40 152 70" fill="none" stroke="#7c2d12" stroke-width="7" stroke-linecap="round"/>'
    g += f'<circle cx="100" cy="26" r="9" fill="#7c2d12" stroke="{k}" stroke-width="4"/>'
    return g


@net("Deerstalker", "mystery", "detectives", "british")
def deerstalker():
    d = SH + lin("tweed", [(0, "#a8a29e"), (0.5, "#78716c"), (1, "#57534e")])
    body = '<g filter="url(#sh)"><ellipse cx="256" cy="256" rx="214" ry="226" fill="#14532d" stroke="#052e16" stroke-width="8"/></g>'
    body += '<ellipse cx="256" cy="256" rx="196" ry="208" fill="none" stroke="#d4a94a" stroke-width="4"/>'
    body += f'<g filter="url(#sh)">{fit(_deerstalker(), 146, 76, 220, 150)}</g>'
    body += fit(
        text("DEERSTALKER", "Playfair Display", 100, weight=900, fill="#fef3c7"), 80, 250, 352, 64
    )
    body += '<line x1="166" y1="330" x2="346" y2="330" stroke="#d4a94a" stroke-width="3"/>'
    body += fit(
        text("BRITISH MYSTERIES", "Cinzel", 100, weight=700, fill="#d4a94a", ls=6),
        140,
        344,
        232,
        28,
    )
    return svg(body, d)


# ================================================================== sci-fi


def _starfield(x, y, w, h, n=40, seed=7, colour="#fff"):

    rng = random.Random(seed)
    return "".join(
        f'<circle cx="{x + rng.random() * w:.1f}" cy="{y + rng.random() * h:.1f}" '
        f'r="{rng.choice((1.2, 1.6, 2.2, 3))}" fill="{colour}" opacity="{rng.choice((0.5, 0.7, 0.95))}"/>'
        for _ in range(n)
    )


@net("Ray Gun TV", "sci-fi", "science fiction")
def ray_gun_tv():
    d = (
        SH
        + lin("rgp", [(0, "#13243f"), (1, "#060c1a")])
        + lin("chromeword", [(0, "#ffffff"), (0.48, "#cfe9f5"), (0.52, "#5f8fa8"), (1, "#e0f5ff")])
    )
    body = '<defs><clipPath id="rgc"><rect x="36" y="72" width="440" height="368" rx="30"/></clipPath></defs>'
    body += _panel(36, 72, 440, 368, "url(#rgp)", rx=30)
    body += '<g clip-path="url(#rgc)" fill="none">'
    for i, r in enumerate(range(60, 560, 46)):
        c = "#ef4444" if i % 2 else "#2dd4bf"
        body += f'<circle cx="36" cy="256" r="{r}" stroke="{c}" stroke-width="{10 - i * 0.6:.1f}" opacity="{0.55 - i * 0.04:.2f}"/>'
    body += "</g>"
    body += '<rect x="36" y="72" width="440" height="368" rx="30" fill="none" stroke="#2dd4bf" stroke-width="6"/>'
    w = _word("RAY GUN", "Audiowide", "url(#chromeword)", "#0b1222", 8)
    body += fit(extrude(w, 0, 8, 6, "#ef4444") + w, 66, 138, 380, 120)
    body += '<g filter="url(#sh)"><rect x="196" y="290" width="120" height="66" rx="33" fill="#ef4444" stroke="#0b1222" stroke-width="5"/></g>'
    body += fit(text("TV", "Audiowide", 100, fill="#fff"), 222, 302, 68, 42)
    body += fit(text("SCI-FI SERIES", "Michroma", 40, fill="#2dd4bf", ls=8), 140, 384, 232, 20)
    return svg(body, d)


@net("Tin Robot", "sci-fi", "science fiction", "robots")
def tin_robot():
    d = (
        SH
        + lin("tin", [(0, "#f8fafc"), (0.5, "#a8b3c2"), (1, "#e2e8f0")], x2=1, y2=1)
        + lin("tinred", [(0, "#f87171"), (1, "#b91c1c")])
    )
    body = _panel(40, 84, 432, 344, "#1e293b", rx=30)
    body += '<rect x="52" y="96" width="408" height="320" rx="22" fill="url(#tin)"/>'
    body += _lines(64, 448, 112, 15, 20, "#ffffff", 2, 0.35)
    for x, y in ((76, 120), (436, 120), (76, 392), (436, 392)):
        body += f'<circle cx="{x}" cy="{y}" r="10" fill="#94a3b8" stroke="#1e293b" stroke-width="4"/><circle cx="{x - 3}" cy="{y - 3}" r="3.5" fill="#fff" opacity=".7"/>'
    body += '<g filter="url(#sh)"><rect x="186" y="122" width="140" height="64" rx="12" fill="url(#tinred)" stroke="#1e293b" stroke-width="5"/></g>'
    body += fit(text("TIN", "Bungee", 100, fill="#fff"), 206, 132, 100, 44)
    w = _word("ROBOT", "Bungee", "url(#tinred)", "#1e293b", 8)
    body += (
        f'<g filter="url(#sh)">{fit(extrude(w, 0, 10, 8, "#1e293b") + w, 80, 204, 352, 120)}</g>'
    )
    body += fit(text("SCI-FI CLASSICS", "Michroma", 40, fill="#1e293b", ls=8), 136, 352, 240, 22)
    return svg(body, d)


@net("Tractor Beam", "sci-fi", "science fiction", "aliens")
def tractor_beam():
    d = (
        SH
        + lin("tbsky", [(0, "#020617"), (1, "#0f2a2a")])
        + lin("beam", [(0, "#d9f99d"), (1, "#4ade80")])
    )
    d += lin("hull", [(0, "#e2e8f0"), (1, "#64748b")])
    body = '<defs><clipPath id="tbc"><rect x="44" y="44" width="424" height="424" rx="34"/></clipPath></defs>'
    body += _panel(44, 44, 424, 424, "url(#tbsky)", rx=34)
    body += '<g clip-path="url(#tbc)">' + _starfield(44, 44, 424, 200, 30, seed=3)
    body += '<polygon points="214,150 298,150 430,468 82,468" fill="url(#beam)" opacity=".28"/>'
    body += '<polygon points="234,150 278,150 360,468 152,468" fill="url(#beam)" opacity=".35"/>'
    for y in (220, 262, 304):
        body += f'<line x1="{256 - (y - 150) * 0.45:.0f}" y1="{y}" x2="{256 + (y - 150) * 0.45:.0f}" y2="{y}" stroke="#d9f99d" stroke-width="3" opacity=".5"/>'
    body += "</g>"
    body += '<g filter="url(#sh)"><ellipse cx="256" cy="112" rx="58" ry="40" fill="#99f6e4" fill-opacity=".8" stroke="#0f172a" stroke-width="6"/>'
    body += '<ellipse cx="256" cy="140" rx="150" ry="30" fill="url(#hull)" stroke="#0f172a" stroke-width="7"/>'
    for x in (156, 206, 256, 306, 356):
        body += f'<circle cx="{x}" cy="{142 + abs(x - 256) / 14:.0f}" r="7" fill="#a3e635"/>'
    body += "</g>"
    body += '<rect x="44" y="44" width="424" height="424" rx="34" fill="none" stroke="#a3e635" stroke-width="6"/>'
    w = _word("TRACTOR", "Michroma", "#f7fee7", "#022c22", 10, ls=4)
    body += f'<g filter="url(#sh)">{fit(w, 80, 300, 352, 62)}</g>'
    w2 = _word("BEAM", "Michroma", "#a3e635", "#022c22", 10, ls=30)
    body += f'<g filter="url(#sh)">{fit(w2, 120, 374, 272, 62)}</g>'
    return svg(body, d)


@net("Moon Base", "sci-fi", "science fiction", "space")
def moon_base():
    centre = '<g clip-path="url(#rc)"><rect x="0" y="0" width="512" height="512" fill="#0b1026"/>'
    centre += _starfield(34, 34, 444, 220, 34, seed=11)
    centre += '<circle cx="368" cy="118" r="38" fill="#3b82f6"/><path d="M342 104 Q360 92 372 110 Q386 128 402 120" fill="none" stroke="#86efac" stroke-width="9" stroke-linecap="round"/>'
    centre += '<circle cx="256" cy="740" r="480" fill="url(#lunar)"/>'
    for cx, cy, r in ((120, 286, 16), (330, 276, 12), (410, 292, 9), (200, 296, 8)):
        centre += f'<ellipse cx="{cx}" cy="{cy}" rx="{r}" ry="{r * 0.4:.1f}" fill="#64748b"/>'
    centre += '<path d="M190 268 A66 66 0 0 1 322 268 Z" fill="url(#dome)" stroke="#1e293b" stroke-width="5"/>'
    centre += '<path d="M212 268 A44 44 0 0 1 256 224" fill="none" stroke="#fff" stroke-width="5" opacity=".7"/>'
    centre += '<line x1="256" y1="202" x2="256" y2="160" stroke="#cbd5e1" stroke-width="5"/><circle cx="256" cy="156" r="7" fill="#f87171"/></g>'
    defs = rad("lunar", [(0, "#e2e8f0"), (1, "#94a3b8")]) + lin(
        "dome", [(0, "#f8fafc"), (1, "#7dd3fc")]
    )
    return L.roundel(
        centre,
        "MOON BASE",
        font="Orbitron",
        weight=900,
        ink="#f8fafc",
        disc="#0b1026",
        rim="#cbd5e1",
        edge="#0f172a",
        bar="#1d4ed8",
        defs=defs,
        ls=4,
    )


@net("Launch Pad", "sci-fi", "science fiction", "space")
def launch_pad():
    scene = '<rect x="0" y="0" width="512" height="512" fill="url(#lpsky)"/>' + _starfield(
        60, 40, 392, 140, 22, seed=5
    )
    scene += '<path d="M236 380 Q256 470 276 380 Z" fill="#fde68a" opacity=".6"/>'
    scene += '<path d="M150 512 Q160 400 256 360 Q352 400 362 512 Z" fill="#e5e7eb" opacity=".55"/>'
    for x in (120, 136):
        scene += f'<line x1="{x}" y1="140" x2="{x}" y2="420" stroke="#1e293b" stroke-width="6"/>'
    for y in range(160, 420, 30):
        scene += (
            f'<line x1="120" y1="{y}" x2="136" y2="{y + 26}" stroke="#1e293b" stroke-width="4"/>'
        )
    scene += '<line x1="136" y1="200" x2="200" y2="200" stroke="#1e293b" stroke-width="6"/>'
    scene += centred(
        S.rocket(P(a="#dc2626", b="#f59e0b", c="#7dd3fc", k="#0f172a", l="#f8fafc")), 256, 230, 260
    )
    defs = lin("lpsky", [(0, "#0b1a3a"), (0.6, "#1e3a8a"), (1, "#f97316")])
    return L.patch(
        scene,
        "LAUNCH PAD",
        font="Russo One",
        ink="#f8fafc",
        band="#dc2626",
        rim="#fbbf24",
        edge="#0f172a",
        defs=defs,
        ls=2,
    )


@net("Flying Saucer", "sci-fi", "science fiction", "aliens")
def flying_saucer():
    d = SH + lin("fsh", [(0, "#f8fafc"), (0.45, "#cbd5e1"), (0.55, "#64748b"), (1, "#334155")])
    d += lin("fsd", [(0, "#ccfbf1"), (1, "#14b8a6")])
    body = '<g filter="url(#sh)">'
    body += '<path d="M146 236 A110 104 0 0 1 366 236 Z" fill="url(#fsd)" stroke="#0f172a" stroke-width="8"/>'
    body += '<path d="M176 220 A84 84 0 0 1 240 150" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round" opacity=".7"/>'
    body += '<ellipse cx="256" cy="286" rx="236" ry="78" fill="url(#fsh)" stroke="#0f172a" stroke-width="9"/>'
    body += '<path d="M40 298 Q256 380 472 298" fill="none" stroke="#0f172a" stroke-width="4" opacity=".5"/>'
    body += "</g>"
    for x in range(96, 440, 54):
        body += f'<circle cx="{x}" cy="{332 + abs(x - 256) * 0.05 - (abs(x - 256) ** 2) / 1400:.0f}" r="9" fill="#facc15" stroke="#0f172a" stroke-width="3"/>'
    w = _word("FLYING SAUCER", "Racing Sans One", "#ef4444", "#0f172a", 10, style="italic")
    body += fit(w, 64, 246, 384, 62)
    body += fit(text("SCI-FI THEATER", "Michroma", 40, fill="#e2e8f0", ls=8), 156, 396, 200, 20)
    return svg(body, d)


@net("Atomic TV", "sci-fi", "science fiction", "1950s")
def atomic_tv():
    d = SH + lin("atw", [(0, "#fef3c7"), (1, "#fcd34d")])
    body = '<g filter="url(#sh)" fill="none">'
    for r in (0, 60, 120):
        body += f'<ellipse cx="256" cy="226" rx="226" ry="76" transform="rotate({r} 256 226)" stroke="#1f2937" stroke-width="20"/>'
    for r in (0, 60, 120):
        body += f'<ellipse cx="256" cy="226" rx="226" ry="76" transform="rotate({r} 256 226)" stroke="#14b8a6" stroke-width="10"/>'
    body += "</g>"
    for ang in (30, 150, 270):
        x = 256 + 226 * math.cos(math.radians(ang))
        y = 226 + 76 * math.sin(math.radians(ang))
        rot = {30: 0, 150: 60, 270: 120}[ang]
        body += f'<g transform="rotate({rot} 256 226)"><circle cx="{x:.1f}" cy="{y:.1f}" r="16" fill="#f97316" stroke="#1f2937" stroke-width="5"/></g>'
    w = _word("ATOMIC", "Bowlby One", "url(#atw)", "#1f2937", 10)
    body += f'<g filter="url(#sh)">{fit(extrude(w, 6, 8, 8, "#1f2937") + w, 40, 168, 432, 110)}</g>'
    body += '<g filter="url(#sh)"><rect x="176" y="340" width="160" height="72" rx="14" fill="#f97316" stroke="#1f2937" stroke-width="6"/></g>'
    body += fit(text("TV", "Bowlby One", 100, fill="#fef3c7"), 216, 352, 80, 48)
    return svg(body, d)


@net("Space Station 9", "sci-fi", "science fiction", "space")
def space_station_9():

    d = (
        SH
        + rad("ss9", [(0, "#1e3a8a"), (1, "#0b1026")])
        + lin("ss9n", [(0, "#ffffff"), (1, "#fdba74")])
    )
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="#0f172a"/><circle cx="256" cy="256" r="220" fill="url(#ss9)"/></g>'
    body += _starfield(60, 60, 392, 392, 26, seed=9)
    body += '<circle cx="256" cy="256" r="150" fill="none" stroke="#0f172a" stroke-width="42"/>'
    body += '<circle cx="256" cy="256" r="150" fill="none" stroke="#cbd5e1" stroke-width="30"/>'
    for k in range(12):
        a = math.radians(k * 30)
        body += f'<line x1="{256 + 136 * math.cos(a):.1f}" y1="{256 + 136 * math.sin(a):.1f}" x2="{256 + 164 * math.cos(a):.1f}" y2="{256 + 164 * math.sin(a):.1f}" stroke="#475569" stroke-width="5"/>'
    for a in (45, 135, 225, 315):
        r = math.radians(a)
        body += f'<line x1="{256 + 92 * math.cos(r):.1f}" y1="{256 + 92 * math.sin(r):.1f}" x2="{256 + 136 * math.cos(r):.1f}" y2="{256 + 136 * math.sin(r):.1f}" stroke="#94a3b8" stroke-width="12"/>'
    body += '<circle cx="256" cy="256" r="92" fill="#f97316" stroke="#0f172a" stroke-width="7"/>'
    nine = _word("9", "Orbitron", "url(#ss9n)", "#0f172a", 8, weight=900)
    body += fit(nine, 214, 196, 84, 120)
    a1, b1 = arc_text(
        "SPACE STATION", "Michroma", 256, 256, 196, 30, fill="#f8fafc", ls=6, pid="ss9t"
    )
    a2, b2 = arc_text(
        "SCIENCE FICTION",
        "Michroma",
        256,
        256,
        196,
        22,
        fill="#fdba74",
        ls=6,
        pid="ss9b",
        bottom=True,
    )
    return svg(body + b1 + b2, d + a1 + a2)


@net("Cosmic Channel", "sci-fi", "science fiction", "space")
def cosmic_channel():
    d = SH + rad(
        "neb",
        [(0, "#f0abfc"), (0.35, "#a21caf"), (0.75, "#3b0764"), (1, "#0c0a24")],
        cx=0.4,
        cy=0.4,
        r=0.7,
    )
    d += lin("cw", [(0, "#ffffff"), (1, "#f5d0fe")]) + rad(
        "cpl", [(0, "#fde68a"), (1, "#f97316")], cx=0.35, cy=0.35
    )
    body = '<g filter="url(#sh)"><circle cx="256" cy="200" r="164" fill="url(#neb)" stroke="#0c0a24" stroke-width="8"/></g>'
    body += '<defs><clipPath id="ccc"><circle cx="256" cy="200" r="160"/></clipPath></defs>'
    body += '<g clip-path="url(#ccc)">' + _starfield(96, 40, 320, 320, 40, seed=21)
    body += '<g transform="rotate(-18 300 170)"><ellipse cx="300" cy="170" rx="86" ry="20" fill="none" stroke="#fde68a" stroke-width="8" opacity=".9"/>'
    body += '<circle cx="300" cy="170" r="44" fill="url(#cpl)"/>'
    body += '<path d="M214 170 A86 20 0 0 0 386 170" fill="none" stroke="#fde68a" stroke-width="8"/></g></g>'
    body += '<circle cx="256" cy="200" r="164" fill="none" stroke="#f0abfc" stroke-width="4" opacity=".7"/>'
    w = _word("COSMIC", "Unbounded", "url(#cw)", "#0c0a24", 14, weight=900)
    body += f'<g filter="url(#sh)">{fit(w, 40, 316, 432, 100)}</g>'
    body += fit(
        text("CHANNEL", "Unbounded", 40, weight=600, fill="#e879f9", stroke="#0c0a24", sw=6, ls=22),
        150,
        428,
        212,
        30,
    )
    return svg(body, d)


@net("Star Hopper", "sci-fi", "science fiction", "space adventure")
def star_hopper():
    d = (
        SH
        + lin("shp", [(0, "#1e3a8a"), (1, "#0c1a3a")])
        + lin("shw", [(0, "#fef08a"), (1, "#f59e0b")])
    )
    body = '<defs><clipPath id="shc"><rect x="36" y="120" width="440" height="300" rx="34"/></clipPath></defs>'
    body += _panel(36, 120, 440, 300, "url(#shp)", rx=34)
    body += '<g clip-path="url(#shc)">' + _starfield(36, 120, 440, 300, 40, seed=17) + "</g>"
    body += '<rect x="36" y="120" width="440" height="300" rx="34" fill="none" stroke="#38bdf8" stroke-width="6"/>'
    body += '<path d="M70 206 Q130 120 190 196 Q260 90 330 170 Q370 90 392 104" fill="none" stroke="#7dd3fc" stroke-width="8" stroke-dasharray="2 16" stroke-linecap="round"/>'
    body += f'<g filter="url(#sh)"><polygon points="{star(410, 108, 64, 26, 5)}" fill="url(#shw)" stroke="#0c1a3a" stroke-width="7" stroke-linejoin="round"/></g>'
    w = _word("STAR HOPPER", "Racing Sans One", "url(#shw)", "#0c1a3a", 10, style="italic")
    body += f'<g filter="url(#sh)">{fit(extrude(w, 4, 7, 6, "#0c1a3a") + w, 60, 224, 392, 100)}</g>'
    body += fit(text("SPACE ADVENTURES", "Michroma", 40, fill="#7dd3fc", ls=8), 130, 352, 252, 22)
    return svg(body, d)


def logos() -> list[Logo]:
    return [Logo(lid, name, cat, fn, tags) for lid, name, cat, tags, fn in LOGOS]
