"""Theme logos: decades, holidays and seasons, times of day, formats, kids
and family, and the look of TV itself."""

from __future__ import annotations

import math
import random

import layouts as L
import symbols as S
from kit import (
    Logo,
    banner,
    extrude,
    fit,
    glow,
    lin,
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
DECADES = "Decades"
HOLIDAYS = "Holidays & seasons"
TIMES = "Times of day"
FORMATS = "Formats & moods"
KIDS = "Kids & family"
TV = "On the air"
THEMES: list[tuple[str, str, str, list[str], object]] = []


def theme(tid: str, name: str, category: str, *tags: str):
    def add(fn):
        THEMES.append((tid, name, category, list(tags), fn))
        return fn

    return add


def _panel(x, y, w, h, fill, rx=18, edge=None, sw=0):
    st = f' stroke="{edge}" stroke-width="{sw}"' if edge else ""
    return f'<g filter="url(#sh)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{st}/></g>'


# ======================================================================= decades


@theme("decade-30s", "The 30s", DECADES, "1930s", "classic movies", "black and white")
def thirties():
    d = SH + lin("sil", [(0, "#ffffff"), (0.45, "#c9ced6"), (0.5, "#6b7480"), (1, "#e8ebef")])
    body = _panel(36, 60, 440, 392, "#0c0c0e", rx=10, edge="#c9ced6", sw=4)
    for i in range(5):
        body += f'<rect x="36" y="{150 + i * 16}" width="440" height="6" fill="#c9ced6" opacity="{0.5 - i * 0.08:.2f}"/>'
    body += fit(text("THE", "Federo", 60, fill="#c9ced6", ls=20), 196, 88, 120, 36)
    w = text("30s", "Limelight", 100, fill="url(#sil)")
    body += fit(extrude(w, 6, 6, 8, "#2b2f36") + w, 106, 130, 300, 230)
    body += fit(text("SILVER SCREEN ERA", "Federo", 40, fill="#c9ced6", ls=8), 136, 386, 240, 30)
    return svg(body, d)


@theme("decade-40s", "The 40s", DECADES, "1940s", "swing", "big band")
def forties():
    d = (
        SH
        + lin("wood", [(0, "#b5651d"), (1, "#6b3410")])
        + lin("glow", [(0, "#ffd166"), (1, "#f77f00")])
    )
    arch = "M76 470 L76 220 Q76 40 256 40 Q436 40 436 220 L436 470 Z"
    body = f'<g filter="url(#sh)"><path d="{arch}" fill="url(#wood)" stroke="#2a1206" stroke-width="8"/></g>'
    body += '<path d="M116 470 L116 230 Q116 80 256 80 Q396 80 396 230 L396 470" fill="none" stroke="url(#glow)" stroke-width="12"/>'
    body += '<path d="M146 470 L146 236 Q146 112 256 112 Q366 112 366 236 L366 470" fill="none" stroke="#ff4d6d" stroke-width="8"/>'
    body += '<rect x="176" y="340" width="160" height="110" rx="10" fill="#2a1206" opacity=".55"/>'
    for x in range(190, 330, 18):
        body += f'<rect x="{x}" y="352" width="8" height="86" rx="4" fill="#ffd166" opacity=".7"/>'
    body += f'<g filter="url(#sh)">{fit(tilt(text("40s", "Lobster", 100, fill="#fff4d6", stroke="#2a1206", sw=12), -6), 150, 150, 212, 170)}</g>'
    body += fit(
        text("SWING ERA", "Oswald", 40, weight=700, fill="#ffd166", ls=10), 180, 300, 152, 28
    )
    return svg(body, d)


@theme("decade-50s", "The 50s", DECADES, "1950s", "atomic age", "rock and roll")
def fifties():
    d = SH
    body = '<g filter="url(#sh)"><path d="M40 300 Q60 120 260 110 Q430 104 480 190 Q400 170 330 210 Q260 256 300 340 Q200 400 40 300 Z" fill="#4ecdc4" stroke="#1d2a3a" stroke-width="8"/></g>'
    for x, y, r, c in (
        (120, 110, 40, "#ffd23f"),
        (410, 330, 30, "#ff6b9d"),
        (90, 400, 24, "#ff6b9d"),
    ):
        body += f'<polygon points="{star(x, y, r, r * 0.3, 8)}" fill="{c}" stroke="#1d2a3a" stroke-width="4" stroke-linejoin="round"/>'
    for x, y in ((380, 90), (440, 140), (60, 200)):
        body += f'<circle cx="{x}" cy="{y}" r="8" fill="#1d2a3a"/>'
    body += '<path d="M330 420 l30 -30 l30 30 l30 -30" fill="none" stroke="#1d2a3a" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>'
    body += f'<g filter="url(#sh)">{fit(tilt(text("50s", "Yellowtail", 100, fill="#ff6b9d", stroke="#1d2a3a", sw=14), -8), 100, 120, 312, 240)}</g>'
    return svg(body, d)


@theme("decade-60s", "The 60s", DECADES, "1960s", "groovy", "psychedelic")
def sixties():
    d = SH
    cols = ["#ff006e", "#fb5607", "#ffbe0b", "#8338ec", "#3a86ff", "#06d6a0"]
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="#1a0b2e"/></g>'
    for i in range(10):
        r = 220 - i * 21
        pts_ = []
        for k in range(73):
            a = math.radians(k * 5)
            rr = r + 8 * math.sin(a * 8 + i)
            pts_.append(f"{256 + rr * math.cos(a):.1f},{256 + rr * math.sin(a):.1f}")
        body += f'<polygon points="{" ".join(pts_)}" fill="{cols[i % 6]}"/>'
    w = text("60s", "Chango", 100, fill="#fff", stroke="#1a0b2e", sw=16)
    body += f'<g filter="url(#sh)">{fit(w, 96, 150, 320, 200)}</g>'
    body += fit(
        text("FAR OUT", "Righteous", 40, fill="#fff", stroke="#1a0b2e", sw=8, ls=10),
        186,
        370,
        140,
        34,
    )
    return svg(body, d)


@theme("decade-70s", "The 70s", DECADES, "1970s", "disco", "groovy")
def seventies():
    cols = ["#6b2f1a", "#c2481a", "#ec8a1c", "#f3c12e"]
    body = '<g filter="url(#sh)">'
    for i, c in enumerate(cols):
        r = 230 - i * 34
        body += f'<path d="M{256 - r} 330 A{r} {r} 0 0 1 {256 + r} 330" fill="none" stroke="{c}" stroke-width="34"/>'
    body += "</g>"
    word = text("70s", "Shrikhand", 100, fill="#fff3d9", stroke="#3b1608", sw=14)
    body += fit(extrude(word, 6, 8, 10, "#3b1608") + word, 96, 150, 320, 220)
    body += fit(
        text("THE SEVENTIES", "Righteous", 40, fill="#3b1608", ls=6, stroke="#fff3d9", sw=8),
        120,
        392,
        272,
        40,
    )
    return svg(body, SH)


@theme("decade-80s", "The 80s", DECADES, "1980s", "neon", "retro")
def eighties():
    ink = "#141414"
    d = SH + lin("w", [(0, "#ffe14d"), (1, "#ff9f1c")])
    body = '<g filter="url(#sh)">'
    body += f'<rect x="70" y="120" width="372" height="262" rx="6" fill="#ff4fb4" stroke="{ink}" stroke-width="8" transform="rotate(-6 256 251)"/>'
    for r in range(4):
        for c in range(6):
            body += f'<circle cx="{300 + c * 22}" cy="{300 + r * 20}" r="4" fill="{ink}" opacity=".85" transform="rotate(-6 256 251)"/>'
    body += f'<polygon points="52,196 136,40 222,196" fill="#18d6c8" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>'
    body += f'<circle cx="400" cy="112" r="66" fill="#3d5afe" stroke="{ink}" stroke-width="8"/>'
    body += f'<path d="M346 112 L454 112" stroke="{ink}" stroke-width="6" stroke-dasharray="10 8"/>'
    body += f'<path d="M86 424 l24 -24 l24 24 l24 -24 l24 24 l24 -24" fill="none" stroke="{ink}" stroke-width="10" stroke-linejoin="round" stroke-linecap="round"/>'
    body += '<path d="M330 430 q18 -26 36 0 t36 0 t36 0" fill="none" stroke="#18d6c8" stroke-width="12" stroke-linecap="round"/></g>'
    w = text("80s", "Racing Sans One", 100, fill="url(#w)", stroke=ink, sw=12)
    body += fit(tilt(extrude(w, 10, 10, 12, ink) + w, -6), 82, 130, 348, 240)
    return svg(body, d)


@theme("decade-90s", "The 90s", DECADES, "1990s", "grunge", "extreme")
def nineties():
    d = SH + rough("rg", amount=6, freq=0.04, seed=3)
    rng = random.Random(9)
    body = '<g filter="url(#sh)"><polygon points="30,120 482,70 470,420 50,450" fill="#141414" filter="url(#rg)"/></g>'
    for _ in range(18):
        x, y, r = rng.uniform(60, 450), rng.uniform(90, 430), rng.uniform(4, 16)
        body += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.0f}" fill="{rng.choice(["#b8f500", "#00e5ff", "#ff2bd6"])}"/>'
    body += '<path d="M70 160 l30 -30 l30 30 l30 -30 l30 30" fill="none" stroke="#b8f500" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>'
    body += '<path d="M320 400 q20 -30 40 0 t40 0 t40 0" fill="none" stroke="#00e5ff" stroke-width="10" stroke-linecap="round"/>'
    w = text("90s", "Knewave", 100, fill="#ff2bd6", stroke="#141414", sw=12)
    body += f'<g filter="url(#sh)">{fit(tilt(extrude(w, 6, 6, 8, "#00e5ff") + w, -8), 90, 150, 332, 220)}</g>'
    return svg(body, d)


@theme("decade-2000s", "The 2000s", DECADES, "2000s", "y2k")
def two_thousands():
    d = (
        SH
        + rad("orb", [(0, "#e8f7ff"), (0.4, "#6ec3ff"), (1, "#0b4fa8")], cx=0.4, cy=0.3, r=0.8)
        + lin("gl", [(0, "#ffffffcc"), (1, "#ffffff00")])
    )
    body = '<g filter="url(#sh)"><circle cx="256" cy="226" r="200" fill="url(#orb)" stroke="#06306b" stroke-width="6"/></g>'
    body += '<ellipse cx="236" cy="120" rx="150" ry="74" fill="url(#gl)"/>'
    for x, y, r in ((420, 110, 36), (90, 330, 26), (410, 360, 20)):
        body += centred(S.sparkle(P(), "#fff"), x, y, r * 2)
    body += f'<g filter="url(#sh)">{fit(text("2000s", "Unbounded", 100, weight=800, fill="#fff", stroke="#06306b", sw=10), 80, 176, 352, 110)}</g>'
    body += fit(text("Y2K", "Unbounded", 60, weight=800, fill="#c9f0ff", ls=10), 206, 304, 100, 40)
    return svg(body, d)


@theme("decade-2010s", "The 2010s", DECADES, "2010s")
def twenty_tens():
    d = SH
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="80" fill="#fef6e4"/></g>'
    body += '<circle cx="140" cy="140" r="60" fill="#f582ae"/><rect x="330" y="80" width="100" height="100" rx="20" fill="#8bd3dd"/><polygon points="380,360 440,440 320,440" fill="#f3d2c1"/>'
    body += fit(text("#", "Outfit", 100, weight=800, fill="#001858"), 80, 330, 70, 100)
    body += fit(text("2010s", "Outfit", 100, weight=800, fill="#001858"), 96, 196, 320, 120)
    body += centred(S.heart(P(a="#f582ae", l="#fff", k="#001858")), 256, 360, 70)
    return svg(body, d)


# ======================================================================= Christmas


@theme("christmas-wreath", "Christmas Classics", HOLIDAYS, "christmas", "holiday")
def christmas_wreath():
    rng = random.Random(7)
    body = '<g filter="url(#sh)"><circle cx="256" cy="236" r="178" fill="#0d4a26"/><circle cx="256" cy="236" r="150" fill="#fbf4e2"/>'
    greens = ["#0f5a2e", "#16733a", "#1f8a46", "#2a9d52"]
    for layer, (r, n, ln) in enumerate(
        ((182, 60, 44), (170, 56, 40), (190, 52, 38), (176, 48, 34))
    ):
        for k in range(n):
            a = 2 * math.pi * k / n + layer * 0.07
            rr = r + rng.uniform(-14, 14)
            x, y = 256 + rr * math.cos(a), 236 + rr * math.sin(a)
            rot = math.degrees(a) + 90 + rng.uniform(-50, 50)
            body += f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{ln / 2:.0f}" ry="7" fill="{greens[(k + layer) % 4]}" transform="rotate({rot:.0f} {x:.1f} {y:.1f})"/>'
    for k in range(18):
        a = 2 * math.pi * k / 18 + 0.2
        rr = 178 + rng.uniform(-18, 18)
        body += f'<circle cx="{256 + rr * math.cos(a):.1f}" cy="{236 + rr * math.sin(a):.1f}" r="8" fill="#d62331" stroke="#7a0d15" stroke-width="2"/>'
    body += (
        '<g transform="translate(256 420)"><path d="M0 0 L-70 -34 Q-86 0 -70 34 Z" fill="#d62331" stroke="#7a0d15" stroke-width="4" stroke-linejoin="round"/>'
        '<path d="M0 0 L70 -34 Q86 0 70 34 Z" fill="#d62331" stroke="#7a0d15" stroke-width="4" stroke-linejoin="round"/>'
        '<path d="M-6 6 L-40 76 L-20 70 L-10 86 L6 10 Z" fill="#b51c28"/><path d="M6 6 L40 76 L20 70 L10 86 L-6 10 Z" fill="#b51c28"/>'
        '<circle r="16" fill="#e8343f" stroke="#7a0d15" stroke-width="4"/></g></g>'
    )
    body += fit(
        tilt(text("Christmas", "Great Vibes", 100, fill="#c8102e", stroke="#fbf4e2", sw=6), -6),
        112,
        172,
        288,
        104,
    )
    body += fit(
        text("CLASSICS", "Cinzel", 40, weight=700, fill="#0d4a26", ls=10), 176, 290, 160, 24
    )
    return svg(body, SH)


@theme("christmas-vintage", "Merry Christmas", HOLIDAYS, "christmas", "vintage", "holiday")
def christmas_vintage():
    d = SH + rad("orn", [(0, "#ff8fa3"), (0.5, "#d62828"), (1, "#7a0d15")], cx=0.35, cy=0.3, r=0.8)
    body = '<g filter="url(#sh)"><rect x="232" y="30" width="48" height="36" rx="6" fill="#d4a93a" stroke="#3a0508" stroke-width="5"/>'
    body += '<circle cx="256" cy="26" r="14" fill="none" stroke="#d4a93a" stroke-width="6"/>'
    body += (
        '<circle cx="256" cy="262" r="200" fill="url(#orn)" stroke="#3a0508" stroke-width="8"/></g>'
    )
    body += '<path d="M60 230 Q256 280 452 230" fill="none" stroke="#fff4d6" stroke-width="5" stroke-dasharray="2 12" stroke-linecap="round"/>'
    body += '<path d="M66 320 Q256 370 446 320" fill="none" stroke="#fff4d6" stroke-width="5" stroke-dasharray="2 12" stroke-linecap="round"/>'
    body += '<path d="M130 150 Q160 110 200 100" fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" opacity=".5"/>'
    body += fit(
        tilt(text("Merry", "Yellowtail", 100, fill="#fff4d6", stroke="#3a0508", sw=10), -8),
        120,
        170,
        272,
        90,
    )
    body += fit(
        text("CHRISTMAS", "Bevan", 100, fill="#fff4d6", stroke="#3a0508", sw=8, ls=4),
        96,
        264,
        320,
        60,
    )
    return svg(body, d)


@theme("christmas-movies", "Christmas Movies", HOLIDAYS, "christmas", "holiday movies")
def christmas_movies():
    return L.marquee(
        "CHRISTMAS",
        "MOVIES",
        crest="★ ★ ★",
        crest_ink="#fff3b0",
        frame="#1b6b3a",
        board="#fffaf0",
        letters="#b3121f",
        font="Oswald",
    )


@theme("christmas-cozy", "Cozy Christmas", HOLIDAYS, "christmas", "holiday")
def christmas_cozy():
    d = SH + rad("fire", [(0, "#ffd166"), (0.5, "#e76f22"), (1, "#5a1a0c")], cx=0.5, cy=0.95, r=0.8)
    body = '<g filter="url(#sh)"><rect x="40" y="70" width="432" height="400" rx="10" fill="#8c2f1f" stroke="#2a0c06" stroke-width="8"/></g>'
    body += '<rect x="24" y="56" width="464" height="34" rx="6" fill="#f4efe3" stroke="#2a0c06" stroke-width="6"/>'
    body += '<path d="M120 470 L120 270 Q120 200 256 200 Q392 200 392 270 L392 470 Z" fill="url(#fire)" stroke="#2a0c06" stroke-width="6"/>'
    body += centred(S.campfire(P(a="#ff7b00", b="#ffd166", k="#2a0c06")), 256, 410, 120)
    for x, c in ((110, "#d62828"), (200, "#2a9d52"), (312, "#d62828"), (402, "#2a9d52")):
        body += f'<path d="M{x - 18} 92 L{x + 18} 92 L{x + 18} 160 Q{x + 18} 176 {x + 34} 176 Q{x + 44} 186 {x + 34} 196 L{x - 4} 196 Q{x - 18} 196 {x - 18} 180 Z" fill="{c}" stroke="#2a0c06" stroke-width="5"/>'
        body += f'<rect x="{x - 20}" y="88" width="40" height="18" rx="4" fill="#fff" stroke="#2a0c06" stroke-width="4"/>'
    body += f'<g filter="url(#sh)">{fit(text("Cozy Christmas", "Pacifico", 100, fill="#fff4d6", stroke="#2a0c06", sw=12), 60, 210, 392, 110)}</g>'
    return svg(body, d)


@theme("christmas-snow-globe", "Snow Globe", HOLIDAYS, "christmas", "winter", "holiday")
def snow_globe():
    d = SH + rad("gl", [(0, "#e3f6ff"), (1, "#7cc6ea")], cx=0.4, cy=0.3, r=0.8)
    rng = random.Random(2)
    body = '<g filter="url(#sh)"><path d="M130 400 L382 400 L410 480 L102 480 Z" fill="#7a2e1c" stroke="#2a0c06" stroke-width="7" stroke-linejoin="round"/>'
    body += (
        '<circle cx="256" cy="226" r="190" fill="url(#gl)" stroke="#2a4a5a" stroke-width="7"/></g>'
    )
    body += '<clipPath id="g"><circle cx="256" cy="226" r="186"/></clipPath><g clip-path="url(#g)">'
    body += '<ellipse cx="256" cy="380" rx="220" ry="70" fill="#fff"/>'
    for x, h, c in ((170, 80, "#e63946"), (256, 110, "#2a9d8f"), (340, 70, "#f4a261")):
        body += f'<rect x="{x - 34}" y="{340 - h}" width="68" height="{h}" fill="{c}" stroke="#1d3557" stroke-width="5"/><polygon points="{x - 44},{340 - h} {x},{300 - h} {x + 44},{340 - h}" fill="#fff" stroke="#1d3557" stroke-width="5"/>'
        body += f'<rect x="{x - 10}" y="{310}" width="20" height="30" fill="#1d3557"/><rect x="{x - 24}" y="{350 - h}" width="14" height="14" fill="#ffd166"/>'
    body += centred(S.pine(P(a="#2d6a4f", b="#6b4423", k="#1b4332")), 100, 290, 90) + centred(
        S.pine(P(a="#2d6a4f", b="#6b4423", k="#1b4332")), 420, 300, 80
    )
    for _ in range(40):
        body += f'<circle cx="{rng.uniform(80, 440):.0f}" cy="{rng.uniform(50, 330):.0f}" r="{rng.uniform(2, 5):.1f}" fill="#fff"/>'
    body += "</g>"
    body += '<path d="M150 110 Q180 70 230 60" fill="none" stroke="#fff" stroke-width="12" stroke-linecap="round" opacity=".6"/>'
    body += fit(
        text("SNOW GLOBE", "Cinzel", 100, weight=900, fill="#fff4d6", ls=6), 140, 418, 232, 44
    )
    return svg(body, d)


@theme("christmas-toons", "Holiday Toons", HOLIDAYS, "christmas", "cartoons", "kids")
def holiday_toons():
    d = (
        SH
        + "<pattern id='cc' width='40' height='40' patternUnits='userSpaceOnUse' patternTransform='rotate(45)'><rect width='40' height='40' fill='#fff'/><rect width='20' height='40' fill='#e63946'/></pattern>"
    )
    body = '<g filter="url(#sh)"><rect x="30" y="60" width="452" height="392" rx="196" fill="url(#cc)" stroke="#3a0508" stroke-width="8"/></g>'
    body += '<rect x="80" y="130" width="352" height="250" rx="125" fill="#2a9d52" stroke="#3a0508" stroke-width="7"/>'
    top = text("HOLIDAY", "Luckiest Guy", 100, fill="#fff", stroke="#3a0508", sw=14)
    bot = text("TOONS", "Luckiest Guy", 100, fill="#ffd23f", stroke="#3a0508", sw=14)
    body += f'<g filter="url(#sh)">{fit(tilt(extrude(top, 4, 6, 6, "#3a0508") + top, -5), 110, 160, 292, 90)}{fit(tilt(extrude(bot, 4, 6, 6, "#3a0508") + bot, -5), 140, 254, 232, 100)}</g>'
    return svg(body, d)


# ======================================================================= other holidays and seasons


@theme("halloween", "Halloween", HOLIDAYS, "halloween", "october", "spooky")
def halloween():
    scene = '<rect width="512" height="512" fill="#2a1240"/><circle cx="380" cy="110" r="50" fill="#fff4c9"/>'
    for x, y in ((150, 110), (220, 70), (300, 150)):
        scene += centred(S.bat(P(k="#0b0614")), x, y, 60)
    scene += centred(S.pumpkin(P(a="#ff7b00", k="#3a1400")), 256, 230, 230)
    return L.emblem(
        scene,
        "HALLOWEEN",
        font="Pirata One",
        ink="#ff9f1c",
        band="#0b0614",
        rim="#ff9f1c",
        edge="#0b0614",
        ls=6,
    )


@theme("halloween-haunted", "Spooky Season", HOLIDAYS, "halloween", "october", "spooky")
def spooky_season():
    d = SH + lin("sky", [(0, "#6a1b9a"), (1, "#ff6d00")], user=True, y2=420)
    body = '<g filter="url(#sh)"><rect x="30" y="30" width="452" height="452" rx="30" fill="url(#sky)" stroke="#12051c" stroke-width="8"/></g>'
    body += '<circle cx="256" cy="170" r="90" fill="#ffe8a8" opacity=".9"/>'
    house = (
        '<path d="M160 330 L160 200 L200 160 L200 110 L230 90 L260 110 L260 150 L320 150 L352 190 L352 330 Z" fill="#12051c"/>'
        '<polygon points="190,160 230,120 270,160" fill="#12051c"/>'
    )
    body += house
    for x, y in ((186, 220), (226, 220), (300, 220), (300, 270), (230, 130)):
        body += f'<rect x="{x}" y="{y}" width="20" height="26" fill="#ffd166"/>'
    body += '<path d="M34 330 L478 330 L478 450 Q478 478 450 478 L62 478 Q34 478 34 450 Z" fill="#12051c"/>'
    body += f'<g filter="url(#sh)">{fit(text("SPOOKY", "Pirata One", 100, fill="#ff9f1c", stroke="#12051c", sw=10, ls=4), 90, 340, 332, 70)}</g>'
    body += fit(text("SEASON", "Cinzel", 60, weight=900, fill="#fff", ls=14), 170, 414, 172, 40)
    return svg(body, d)


@theme("thanksgiving", "Thanksgiving", HOLIDAYS, "thanksgiving", "autumn", "harvest")
def thanksgiving():
    d = lin("sky", [(0, "#ffd89b"), (1, "#f4a261")], user=True, y2=330)
    scene = '<rect width="512" height="512" fill="url(#sky)"/>'
    for x, y, c, r in (
        (130, 170, "#d9480f", -20),
        (256, 130, "#e8590c", 0),
        (380, 170, "#f08c00", 20),
        (200, 250, "#bf360c", -10),
        (320, 250, "#e67700", 10),
    ):
        scene += f'<g transform="rotate({r} {x} {y})">{centred(S.leaf(P(a=c, k="#5a2a12")), x, y, 120)}</g>'
    scene += '<path d="M40 320 Q256 290 472 320 L472 520 L40 520 Z" fill="#6b3410"/>'
    return L.emblem(
        scene,
        "THANKSGIVING",
        font="Alfa Slab One",
        ink="#fff3d6",
        band="#8a3b12",
        rim="#fff3d6",
        edge="#3a1606",
        defs=d,
    )


@theme("new-years-eve", "New Year's Eve", HOLIDAYS, "new year", "countdown", "party")
def new_years_eve():
    d = SH + lin("g", [(0, "#fff3b0"), (0.5, "#ffc300"), (1, "#c77800")])
    body = _panel(30, 30, 452, 452, "#0b0a1f", rx=30)
    random.Random(8)
    for cx, cy, r, c in (
        (140, 130, 80, "#ff4fd8"),
        (370, 110, 70, "#29d0ff"),
        (260, 200, 60, "#ffd166"),
    ):
        for k in range(16):
            a = math.radians(k * 22.5)
            body += f'<line x1="{cx + r * 0.3 * math.cos(a):.0f}" y1="{cy + r * 0.3 * math.sin(a):.0f}" x2="{cx + r * math.cos(a):.0f}" y2="{cy + r * math.sin(a):.0f}" stroke="{c}" stroke-width="4" stroke-linecap="round"/>'
            body += f'<circle cx="{cx + r * 1.1 * math.cos(a):.0f}" cy="{cy + r * 1.1 * math.sin(a):.0f}" r="3" fill="{c}"/>'
    body += fit(text("HAPPY", "Montserrat", 100, weight=800, fill="#fff", ls=10), 136, 262, 240, 44)
    body += f'<g filter="url(#sh)">{fit(text("NEW YEAR", "Abril Fatface", 100, fill="url(#g)", ls=4), 60, 310, 392, 90)}</g>'
    body += fit(
        text(
            "10 · 9 · 8 · 7 · 6 · 5 · 4 · 3 · 2 · 1",
            "Montserrat",
            40,
            weight=700,
            fill="#ff4fd8",
            ls=2,
        ),
        90,
        414,
        332,
        24,
    )
    return svg(body, d)


@theme("valentines", "Valentine's Day", HOLIDAYS, "valentine", "romance", "love")
def valentines():
    d = SH + lin("h", [(0, "#ff85a1"), (1, "#e5383b")])
    body = f'<g filter="url(#sh)">{centred(S.heart(P(a="url(#h)", l="#fff", k="#590d22")), 256, 236, 440)}</g>'
    body += '<g filter="url(#sh)" transform="rotate(-6 256 236)"><rect x="120" y="200" width="272" height="80" rx="40" fill="#fff" stroke="#590d22" stroke-width="6"/></g>'
    body += fit(tilt(text("Be Mine", "Pacifico", 100, fill="#e5383b"), -6), 140, 206, 232, 70)
    body += fit(
        text("VALENTINE'S", "Playfair Display", 40, weight=900, fill="#fff", ls=6),
        166,
        116,
        180,
        30,
    )
    return svg(body, d)


@theme("easter", "Easter", HOLIDAYS, "easter", "spring")
def easter():
    d = SH
    body = '<g filter="url(#sh)"><path d="M86 250 L426 250 L396 440 Q392 460 372 460 L140 460 Q120 460 116 440 Z" fill="#c8964f" stroke="#4a2c12" stroke-width="7"/></g>'
    body += '<path d="M100 250 Q256 40 412 250" fill="none" stroke="#4a2c12" stroke-width="18"/><path d="M100 250 Q256 40 412 250" fill="none" stroke="#c8964f" stroke-width="10"/>'
    for i in range(6):
        body += f'<line x1="{120 + i * 50}" y1="260" x2="{128 + i * 48}" y2="452" stroke="#4a2c12" stroke-width="3" opacity=".5"/>'
    eggs = (("#ff8fab", 170, 236, -14), ("#a0e7e5", 250, 220, 4), ("#fdf0a8", 330, 236, 16))
    for c, x, y, r in eggs:
        body += f'<ellipse cx="{x}" cy="{y}" rx="46" ry="60" fill="{c}" stroke="#4a2c12" stroke-width="6" transform="rotate({r} {x} {y})"/>'
        body += f'<path d="M{x - 42} {y} q14 -12 28 0 t28 0 t28 0" fill="none" stroke="#4a2c12" stroke-width="4" transform="rotate({r} {x} {y})"/>'
    body += '<rect x="86" y="270" width="340" height="16" fill="#8fd694" opacity=".0"/>'
    body += f'<g filter="url(#sh)">{fit(text("Easter", "Pacifico", 100, fill="#fff", stroke="#4a2c12", sw=12), 136, 320, 240, 110)}</g>'
    return svg(body, d)


@theme("st-patricks", "St. Patrick's Day", HOLIDAYS, "st patricks", "march", "lucky")
def st_patricks():
    d = SH + lin("g", [(0, "#52b788"), (1, "#1b4332")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="url(#g)" stroke="#0b2418" stroke-width="8"/></g>'
    leaf = "M100 100 Q60 90 50 56 Q40 20 70 14 Q92 10 100 36 Q108 10 130 14 Q160 20 150 56 Q140 90 100 100 Z"
    body += '<g transform="translate(156 40)">'
    for r in (0, 120, 240):
        body += f'<path d="{leaf}" fill="#95d5b2" stroke="#0b2418" stroke-width="6" transform="rotate({r} 100 100)"/>'
    body += '<path d="M100 100 Q110 150 140 180" fill="none" stroke="#0b2418" stroke-width="10" stroke-linecap="round"/></g>'
    body += fit(
        text("LUCKY", "Alfa Slab One", 100, fill="#ffd166", stroke="#0b2418", sw=10, ls=6),
        110,
        272,
        292,
        80,
    )
    body += fit(
        text("ST. PATRICK'S DAY", "Oswald", 40, weight=700, fill="#fff", ls=6), 140, 366, 232, 30
    )
    return svg(body, d)


@theme("fourth-of-july", "Fourth of July", HOLIDAYS, "july 4th", "independence day", "summer")
def fourth_of_july():
    d = SH
    body = _panel(30, 30, 452, 452, "#0b1d51", rx=30)
    for cx, cy, r, c in (
        (130, 130, 80, "#e63946"),
        (370, 120, 70, "#fff"),
        (256, 210, 60, "#4dabf7"),
    ):
        for k in range(18):
            a = math.radians(k * 20)
            body += f'<line x1="{cx + r * 0.25 * math.cos(a):.0f}" y1="{cy + r * 0.25 * math.sin(a):.0f}" x2="{cx + r * math.cos(a):.0f}" y2="{cy + r * math.sin(a):.0f}" stroke="{c}" stroke-width="5" stroke-linecap="round"/>'
    for i in range(4):
        body += f'<rect x="34" y="{300 + i * 24}" width="444" height="12" fill="#e63946"/>'
    body += f'<g filter="url(#sh)">{fit(text("FOURTH OF JULY", "Bevan", 100, fill="#fff", stroke="#0b1d51", sw=10), 50, 296, 412, 80)}</g>'
    body += "".join(
        f'<polygon points="{star(x, 430, 14, 6)}" fill="#fff"/>' for x in (196, 256, 316)
    )
    return svg(body, d)


@theme("summer", "Summer", HOLIDAYS, "summer", "beach")
def summer():
    d = lin(
        "sky",
        [(0, "#ffd166"), (0.55, "#ff9f68"), (0.56, "#48cae4"), (1, "#0077b6")],
        user=True,
        y2=330,
    )
    scene = '<rect width="512" height="512" fill="url(#sky)"/><circle cx="256" cy="160" r="70" fill="#fff3b0"/>'
    scene += '<path d="M40 300 Q256 250 472 300 L472 520 L40 520 Z" fill="#f6d6a8"/>'
    scene += '<path d="M120 300 L120 180 M120 180 Q60 170 40 200 Q80 150 120 180 Q180 150 210 190 Q160 160 120 180" fill="#2d6a4f" stroke="#2d6a4f" stroke-width="10" stroke-linecap="round"/>'
    scene += '<g transform="translate(360 240) rotate(-20)"><path d="M-70 0 A70 70 0 0 1 70 0 Z" fill="#e63946"/><path d="M-70 0 A70 70 0 0 1 -23 -66 L0 0 Z" fill="#fff"/><path d="M23 -66 A70 70 0 0 1 70 0 L0 0 Z" fill="#fff"/><line x1="0" y1="0" x2="0" y2="80" stroke="#4a2c12" stroke-width="6"/></g>'
    return L.emblem(
        scene,
        "SUMMER",
        font="Righteous",
        ink="#fff",
        band="#0077b6",
        rim="#fff3b0",
        edge="#023047",
        defs=d,
        ls=12,
    )


@theme("winter", "Winter", HOLIDAYS, "winter", "snow")
def winter():
    d = SH + lin("b", [(0, "#a2d2ff"), (1, "#3a6ea5")])
    body = '<g filter="url(#sh)"><rect x="56" y="30" width="400" height="452" rx="200" fill="url(#b)" stroke="#0b2750" stroke-width="8"/></g>'
    body += f'<g filter="url(#sh)">{centred(S.snowflake(P(l="#fff")), 256, 186, 250)}</g>'
    body += fit(
        text("WINTER", "Cinzel", 100, weight=900, fill="#fff", stroke="#0b2750", sw=10, ls=10),
        110,
        340,
        292,
        70,
    )
    body += fit(
        text("COZY UP", "Montserrat", 40, weight=700, fill="#e3f2ff", ls=14), 190, 420, 132, 24
    )
    return svg(body, d)


@theme("spring", "Spring", HOLIDAYS, "spring", "flowers")
def spring():
    d = SH + lin("g", [(0, "#d8f3dc"), (1, "#95d5b2")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="url(#g)" stroke="#1b4332" stroke-width="8"/></g>'
    for x, y, s, a in (
        (170, 200, 150, "#ff8fab"),
        (330, 190, 170, "#ffd166"),
        (256, 230, 120, "#c77dff"),
    ):
        body += centred(S.flower(P(a=a, b="#fff3b0", k="#1b4332")), x, y, s)
    body += f'<g filter="url(#sh)">{fit(text("Spring", "Pacifico", 100, fill="#fff", stroke="#1b4332", sw=12), 110, 300, 292, 120)}</g>'
    return svg(body, d)


@theme("autumn", "Autumn", HOLIDAYS, "autumn", "fall", "harvest")
def autumn():
    d = SH + lin("o", [(0, "#ffb347"), (1, "#c2410c")])
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="60" fill="url(#o)" stroke="#431407" stroke-width="8"/></g>'
    for x, y, c, r, s in (
        (150, 150, "#9a3412", -30, 130),
        (330, 130, "#facc15", 20, 150),
        (240, 210, "#dc2626", 0, 110),
    ):
        body += f'<g transform="rotate({r} {x} {y})">{centred(S.leaf(P(a=c, k="#431407")), x, y, s)}</g>'
    body += f'<g filter="url(#sh)">{fit(text("AUTUMN", "Alfa Slab One", 100, fill="#fff7ed", stroke="#431407", sw=10, ls=8), 80, 300, 352, 90)}</g>'
    body += fit(
        text("FALL FAVORITES", "Oswald", 40, weight=700, fill="#431407", ls=8), 156, 400, 200, 28
    )
    return svg(body, d)


# ======================================================================= times of day


@theme("saturday-morning", "Saturday Morning", TIMES, "saturday morning", "cartoons", "kids")
def saturday_morning():
    body = '<g filter="url(#sh)">'
    body += f'<polygon points="{star(256, 250, 240, 196, 22)}" fill="#ffd12e" stroke="#1b1b3a" stroke-width="8" stroke-linejoin="round"/>'
    body += (
        '<circle cx="256" cy="250" r="176" fill="#29a6ff" stroke="#1b1b3a" stroke-width="8"/></g>'
    )
    top = text("SATURDAY", "Luckiest Guy", 100, fill="#fff", stroke="#1b1b3a", sw=16)
    body += fit(tilt(extrude(top, 5, 7, 8, "#1b1b3a") + top, -6), 70, 128, 372, 100)
    mid = text("MORNING", "Luckiest Guy", 100, fill="#ff4f7a", stroke="#1b1b3a", sw=16)
    body += fit(tilt(extrude(mid, 5, 7, 8, "#1b1b3a") + mid, -6), 80, 214, 352, 100)
    body += '<path d="M150 330 L362 330 L346 356 L362 382 L150 382 L166 356 Z" fill="#1b1b3a"/>'
    body += fit(text("TOONS", "Bungee", 60, fill="#ffd12e", ls=6), 190, 336, 132, 40)
    return svg(body, SH)


@theme("late-night", "Late Night", TIMES, "late night", "after dark")
def late_night():
    return L.neon(
        "LATE NIGHT",
        "11:35",
        font="Tilt Neon",
        tube="#b388ff",
        glow_c="#7c4dff",
        frame="#ff4081",
        sub_tube="#ffd740",
        sub_font="Tilt Neon",
        sym=centred(S.crescent(P(l="#ffd740", b="#c79a00", k="#12101a")), 400, 150, 60),
    )


@theme("prime-time", "Prime Time", TIMES, "prime time", "evening")
def prime_time():
    d = (
        SH
        + lin("g", [(0, "#fff3b0"), (0.5, "#ffc300"), (1, "#c77800")])
        + rad("bg", [(0, "#2b2d42"), (1, "#0d0e17")], r=0.7)
    )
    body = _panel(24, 40, 464, 432, "url(#bg)", rx=28)
    rng = random.Random(3)
    for _ in range(40):
        body += f'<circle cx="{rng.uniform(50, 462):.0f}" cy="{rng.uniform(60, 450):.0f}" r="{rng.uniform(1, 2.6):.1f}" fill="#fff" opacity="{rng.uniform(0.3, 0.8):.2f}"/>'
    w = text("PRIME TIME", "Bowlby One", 100, fill="url(#g)", stroke="#3a2200", sw=6)
    body += (
        f'<g filter="url(#sh)">{fit(extrude(w, 0, 12, 12, "#3a2200") + w, 50, 170, 412, 120)}</g>'
    )
    body += fit(
        text("8 PM · 9 PM · 10 PM", "Montserrat", 40, weight=800, fill="#fff", ls=6),
        126,
        330,
        260,
        30,
    )
    body += "".join(
        f'<polygon points="{star(x, 120, 16, 7)}" fill="url(#g)"/>' for x in (206, 256, 306)
    )
    return svg(body, d)


@theme("matinee", "Matinee", TIMES, "matinee", "afternoon", "movies")
def matinee():
    return L.ticket(
        "MATINEE",
        "2 O'CLOCK SHOW",
        font="Limelight",
        ink="#7a0d15",
        paper="#fdf0d5",
        edge="#2a0508",
        accent="#c1121f",
    )


@theme("midnight-movies", "Midnight Movies", TIMES, "midnight", "movies", "cult")
def midnight_movies():
    d = SH + lin("n", [(0, "#240046"), (1, "#10002b")])
    body = _panel(36, 36, 440, 440, "url(#n)", rx=220)
    body += centred(S.clock(P(a="#c77dff", l="#f3e8ff", k="#10002b"), h=12, m=0), 256, 170, 210)
    body += f'<g filter="url(#sh)">{fit(text("MIDNIGHT", "Limelight", 100, fill="#e0aaff", stroke="#10002b", sw=8, ls=4), 90, 290, 332, 70)}</g>'
    body += fit(text("MOVIES", "Limelight", 100, fill="#fff", ls=20), 150, 370, 212, 44)
    return svg(body, d)


@theme("sunday-afternoon", "Sunday Afternoon", TIMES, "sunday", "weekend", "lazy")
def sunday_afternoon():
    d = SH + lin("sky", [(0, "#bde0fe"), (1, "#fefae0")])
    body = '<g filter="url(#sh)"><rect x="30" y="60" width="452" height="392" rx="196" fill="url(#sky)" stroke="#264653" stroke-width="8"/></g>'
    body += centred(S.sun(P(b="#ffb703", k="#264653")), 380, 150, 110)
    body += '<path d="M90 250 Q256 330 422 250" fill="none" stroke="#e76f51" stroke-width="18" stroke-linecap="round"/>'
    body += '<path d="M90 250 Q256 330 422 250" fill="none" stroke="#f4a261" stroke-width="8" stroke-dasharray="12 10"/>'
    body += '<line x1="90" y1="250" x2="70" y2="400" stroke="#6b4423" stroke-width="10"/><line x1="422" y1="250" x2="442" y2="400" stroke="#6b4423" stroke-width="10"/>'
    body += f'<g filter="url(#sh)">{fit(tilt(text("Sunday", "Pacifico", 100, fill="#264653", stroke="#fefae0", sw=10), -6), 110, 110, 240, 110)}</g>'
    body += fit(
        text("AFTERNOON", "Oswald", 100, weight=700, fill="#264653", ls=10), 150, 330, 212, 56
    )
    return svg(body, d)


@theme("after-school", "After School", TIMES, "after school", "kids")
def after_school():
    d = SH
    bus = (
        '<rect x="30" y="20" width="140" height="150" rx="18" fill="#ffc300" stroke="#1d1a2b" stroke-width="8"/>'
        '<rect x="44" y="36" width="112" height="56" rx="8" fill="#9ad1f5" stroke="#1d1a2b" stroke-width="5"/><line x1="100" y1="36" x2="100" y2="92" stroke="#1d1a2b" stroke-width="5"/>'
        '<rect x="50" y="110" width="100" height="14" fill="#1d1a2b"/><circle cx="56" cy="146" r="10" fill="#fff" stroke="#1d1a2b" stroke-width="4"/><circle cx="144" cy="146" r="10" fill="#fff" stroke="#1d1a2b" stroke-width="4"/>'
        '<rect x="40" y="170" width="30" height="20" fill="#1d1a2b"/><rect x="130" y="170" width="30" height="20" fill="#1d1a2b"/>'
    )
    body = '<g filter="url(#sh)"><rect x="30" y="30" width="452" height="452" rx="40" fill="#29a6ff" stroke="#1d1a2b" stroke-width="8"/></g>'
    body += '<rect x="34" y="250" width="444" height="228" rx="0" fill="#6fd06a" opacity=".0"/>'
    body += f'<g filter="url(#sh)">{fit(bus, 176, 50, 160, 200)}</g>'
    w = text("AFTER SCHOOL", "Luckiest Guy", 100, fill="#ffc300", stroke="#1d1a2b", sw=14)
    body += f'<g filter="url(#sh)">{fit(extrude(w, 4, 6, 6, "#1d1a2b") + w, 50, 272, 412, 100)}</g>'
    body += fit(
        text("3 O'CLOCK TV", "Luckiest Guy", 40, fill="#fff", stroke="#1d1a2b", sw=8, ls=6),
        156,
        396,
        200,
        40,
    )
    return svg(body, d)


@theme("friday-night", "Friday Night", TIMES, "friday", "weekend", "party")
def friday_night():
    return L.neon(
        "FRIDAY",
        "NIGHT",
        font="Tilt Neon",
        tube="#ff4fd8",
        glow_c="#ff4fd8",
        frame="#29d0ff",
        sub_tube="#29d0ff",
        sub_font="Tilt Neon",
    )


@theme("good-morning", "Good Morning", TIMES, "morning", "breakfast")
def good_morning():
    d = SH + lin("sky", [(0, "#ffd6a5"), (1, "#fdffb6")])
    body = '<g filter="url(#sh)"><rect x="30" y="60" width="452" height="392" rx="30" fill="url(#sky)" stroke="#7a3e12" stroke-width="8"/></g>'
    body += '<clipPath id="gm"><rect x="34" y="64" width="444" height="384" rx="26"/></clipPath><g clip-path="url(#gm)">'
    for k in range(12):
        a = math.radians(-180 + k * 16.4)
        body += f'<polygon points="256,330 {256 + 400 * math.cos(a - 0.05):.0f},{330 + 400 * math.sin(a - 0.05):.0f} {256 + 400 * math.cos(a + 0.05):.0f},{330 + 400 * math.sin(a + 0.05):.0f}" fill="#ffb703" opacity=".25"/>'
    body += '<circle cx="256" cy="330" r="90" fill="#ffb703"/><rect x="30" y="330" width="452" height="130" fill="#f4a261"/></g>'
    body += centred(S.coffee(P(a="#e63946", b="#fff", l="#fff", k="#7a3e12")), 390, 350, 110)
    body += f'<g filter="url(#sh)">{fit(tilt(text("Good Morning", "Pacifico", 100, fill="#fff", stroke="#7a3e12", sw=12), -4), 50, 120, 412, 130)}</g>'
    return svg(body, d)


@theme("bedtime-stories", "Bedtime Stories", TIMES, "bedtime", "kids", "stories")
def bedtime_stories():
    d = SH + lin("n", [(0, "#3a0ca3"), (1, "#10002b")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="url(#n)" stroke="#0a0014" stroke-width="8"/></g>'
    body += centred(S.crescent(P(l="#ffe8a8", b="#d4a93a", k="#0a0014")), 190, 150, 170)
    for x, y, r in ((330, 110, 14), (380, 170, 10), (300, 200, 8), (130, 260, 8)):
        body += f'<polygon points="{star(x, y, r, r * 0.45)}" fill="#ffe8a8"/>'
    body += centred(S.book(P(a="#7b2cbf", b="#ff8fab", l="#fff", k="#0a0014")), 256, 290, 150)
    body += fit(
        text("Bedtime Stories", "Pacifico", 100, fill="#ffe8a8", stroke="#0a0014", sw=10),
        80,
        360,
        352,
        80,
    )
    return svg(body, d)


# ======================================================================= formats and moods


@theme("classic-tv", "Classic TV", FORMATS, "classic tv", "reruns")
def classic_tv():
    d = lin("sk", [(0, "#8ecae6"), (1, "#219ebc")], user=True, y2=340)
    scene = '<rect width="512" height="512" fill="url(#sk)"/>' + centred(
        S.tv_set(P(a="#b5651d", c="#2f8f8a", l="#f3e6c8", k="#2a1d14")), 256, 196, 250
    )
    return L.emblem(
        scene,
        "CLASSIC TV",
        font="Righteous",
        ink="#fff8e7",
        band="#d6452f",
        rim="#fff8e7",
        edge="#2a1d14",
        defs=d,
        ls=4,
    )


@theme("classic-movies", "Classic Movies", FORMATS, "classic movies", "golden age")
def classic_movies():
    return L.deco(
        "CLASSICS",
        "GOLDEN AGE MOVIES",
        font="Federo",
        gold=("#ffffff", "#c9ced6", "#6b7480", "#e8ebef"),
    )


@theme("variety-mix", "Variety Mix", FORMATS, "variety", "mix", "shuffle")
def variety_mix():
    d = SH
    cols = [
        "#ff595e",
        "#ffca3a",
        "#8ac926",
        "#1982c4",
        "#6a4c93",
        "#ff924c",
        "#52a675",
        "#4267ac",
        "#b5a6c9",
    ]
    body = ""
    for i in range(9):
        x, y = 70 + (i % 3) * 126, 40 + (i // 3) * 126
        rot = (i * 7) % 11 - 5
        body += f'<g filter="url(#sh)"><rect x="{x}" y="{y}" width="112" height="112" rx="16" fill="{cols[i]}" stroke="#1d1a2b" stroke-width="6" transform="rotate({rot} {x + 56} {y + 56})"/></g>'
    body += '<g filter="url(#sh)"><rect x="40" y="170" width="432" height="150" rx="20" fill="#1d1a2b"/></g>'
    body += fit(text("VARIETY MIX", "Archivo Black", 100, fill="#fff", ls=2), 64, 190, 384, 80)
    body += fit(
        text("A LITTLE OF EVERYTHING", "Oswald", 40, weight=700, fill="#ffca3a", ls=6),
        110,
        280,
        292,
        28,
    )
    return svg(body, d)


@theme("marathon", "Marathon", FORMATS, "marathon", "all day", "binge")
def marathon():
    d = SH + lin("r", [(0, "#ff5a5f"), (1, "#c81d25")])
    body = '<g filter="url(#sh)"><rect x="24" y="96" width="464" height="320" rx="160" fill="url(#r)" stroke="#3a0508" stroke-width="8"/></g>'
    body += '<rect x="52" y="124" width="408" height="264" rx="132" fill="none" stroke="#fff" stroke-width="4" stroke-dasharray="16 12"/>'
    body += fit(text("MARATHON", "Anton", 100, fill="#fff", ls=6), 90, 168, 332, 110)
    body += fit(
        text("ALL DAY · EPISODE AFTER EPISODE", "Oswald", 40, weight=700, fill="#ffd166", ls=3),
        110,
        298,
        292,
        30,
    )
    return svg(body, d)


@theme("binge", "Binge", FORMATS, "binge", "next episode")
def binge():
    d = SH + lin("p", [(0, "#7b2ff7"), (1, "#f107a3")])
    body = '<g filter="url(#sh)"><rect x="40" y="60" width="432" height="392" rx="40" fill="#12082b"/></g>'
    body += '<rect x="80" y="330" width="352" height="16" rx="8" fill="#3b2a6b"/><rect x="80" y="330" width="280" height="16" rx="8" fill="url(#p)"/><circle cx="360" cy="338" r="14" fill="#fff"/>'
    body += fit(text("BINGE", "Archivo Black", 100, fill="url(#p)"), 90, 110, 332, 150)
    body += fit(
        text("NEXT EPISODE IN 5…", "Montserrat", 40, weight=700, fill="#fff", ls=4),
        120,
        372,
        272,
        30,
    )
    body += '<polygon points="380,236 420,260 380,284" fill="#fff"/><rect x="424" y="236" width="8" height="48" fill="#fff"/>'
    return svg(body, d)


@theme("double-feature", "Double Feature", FORMATS, "double feature", "movies")
def double_feature():
    d = SH
    tk = "M20 60 L180 60 L180 84 A16 16 0 0 0 180 116 L180 140 L20 140 L20 116 A16 16 0 0 0 20 84 Z"
    body = ""
    for rot, x, y, c in ((-14, 40, 120, "#e63946"), (10, 180, 170, "#ffd166")):
        body += f'<g filter="url(#sh)" transform="translate({x} {y}) rotate({rot} 100 100) scale(1.5)"><path d="{tk}" fill="{c}" stroke="#1d1a2b" stroke-width="4"/>'
        body += '<line x1="140" y1="64" x2="140" y2="136" stroke="#1d1a2b" stroke-width="3" stroke-dasharray="5 4"/>'
        body += f'<polygon points="{star(80, 100, 20, 8)}" fill="#1d1a2b"/></g>'
    body += '<g filter="url(#sh)"><rect x="40" y="360" width="432" height="96" rx="12" fill="#1d1a2b"/></g>'
    body += fit(
        text("DOUBLE FEATURE", "Oswald", 100, weight=700, fill="#fff", ls=6), 64, 376, 384, 64
    )
    return svg(body, d)


@theme("drive-in", "Drive-In", FORMATS, "drive-in", "movies", "retro")
def drive_in():
    d = SH + lin("sign", [(0, "#ff5b5b"), (1, "#b3121f")])
    arrow = "M40 150 L380 150 L380 104 L480 250 L380 396 L380 350 L40 350 Z"
    body = f'<g filter="url(#sh)"><path d="{arrow}" fill="url(#sign)" stroke="#1d1d24" stroke-width="10" stroke-linejoin="round"/>'
    inner = "M58 168 L398 168 L398 150 L458 250 L398 350 L398 332 L58 332 Z"
    body += (
        f'<path d="{inner}" fill="none" stroke="#ffe7a8" stroke-width="4" stroke-linejoin="round"/>'
    )
    bulbs = [(x, y) for x in range(72, 392, 26) for y in (182, 318)]
    bulbs += [(408 + t * 9.5, 180 + t * 13.5) for t in range(6)] + [
        (408 + t * 9.5, 320 - t * 13.5) for t in range(6)
    ]
    for x, y in bulbs:
        body += f'<circle cx="{x}" cy="{y}" r="5.5" fill="#fff6c9" stroke="#b36b00" stroke-width="1.5"/>'
    body += "</g>"
    body += fit(
        text("Drive-In", "Yellowtail", 100, fill="#fff9e8", stroke="#1d1d24", sw=14),
        76,
        196,
        330,
        110,
    )
    body += '<rect x="130" y="392" width="252" height="54" rx="8" fill="#1d1d24"/>'
    body += fit(text("MOVIES", "Bungee Inline", 60, fill="#ffe7a8", ls=8), 150, 400, 212, 38)
    return svg(body, d)


@theme("cult-classics", "Cult Classics", FORMATS, "cult", "vhs", "midnight movies")
def cult_classics():
    d = SH
    body = '<g filter="url(#sh)"><rect x="30" y="110" width="452" height="292" rx="16" fill="#1a1a1e" stroke="#000" stroke-width="6"/></g>'
    body += '<circle cx="150" cy="290" r="44" fill="#2b2b33"/><circle cx="362" cy="290" r="44" fill="#2b2b33"/><circle cx="150" cy="290" r="16" fill="#0a0a0c"/><circle cx="362" cy="290" r="16" fill="#0a0a0c"/>'
    body += '<rect x="194" y="262" width="124" height="56" fill="#3a2a22"/>'
    body += '<g transform="rotate(-2 256 190)"><rect x="60" y="136" width="392" height="110" rx="4" fill="#fbf8ee"/>'
    body += '<line x1="72" y1="200" x2="440" y2="200" stroke="#9ad1f5" stroke-width="2"/><line x1="72" y1="226" x2="440" y2="226" stroke="#9ad1f5" stroke-width="2"/>'
    body += fit(text("CULT CLASSICS", "Permanent Marker", 100, fill="#c1121f"), 80, 144, 352, 80)
    body += (
        fit(text("DO NOT TAPE OVER!!", "Permanent Marker", 40, fill="#1d4ed8"), 150, 212, 212, 24)
        + "</g>"
    )
    body += '<rect x="30" y="370" width="452" height="14" fill="#2b2b33"/>'
    return svg(body, d)


@theme("b-movies", "B-Movies", FORMATS, "b-movies", "creature features", "sci-fi")
def b_movies():
    d = SH + lin("sk", [(0, "#ffde59"), (1, "#ff5757")])
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="10" fill="url(#sk)" stroke="#1d0f0f" stroke-width="8"/></g>'
    body += '<path d="M40 330 L120 300 L200 330 L300 290 L400 320 L472 300 L472 472 L40 472 Z" fill="#1d0f0f"/>'
    claw = '<path d="M180 330 Q160 200 230 130 Q260 110 280 130 Q300 150 290 190 L330 150 Q350 140 356 160 L320 220 L370 200 Q386 200 380 220 L310 280 Q300 330 290 340 Z" fill="#4c956c" stroke="#1d0f0f" stroke-width="7" stroke-linejoin="round"/>'
    body += claw
    w = text("B-MOVIES", "Bangers", 100, fill="#fff", stroke="#1d0f0f", sw=12, ls=4)
    body += f'<g filter="url(#sh)">{fit(skew(extrude(w, 6, 6, 8, "#1d0f0f") + w, -8), 60, 60, 392, 110)}</g>'
    body += fit(
        text("IT CAME FROM THE LATE SHOW!", "Bangers", 40, fill="#ffde59", ls=2), 80, 380, 352, 50
    )
    return svg(body, d)


@theme("reruns", "Reruns", FORMATS, "reruns", "classic tv")
def reruns():
    d = SH
    body = '<g filter="url(#sh)"><circle cx="256" cy="226" r="190" fill="#2a9d8f" stroke="#0b2b28" stroke-width="8"/></g>'
    body += '<path d="M130 226 A126 126 0 1 1 256 352" fill="none" stroke="#fff" stroke-width="22" stroke-linecap="round"/>'
    body += '<polygon points="96,226 164,226 130,276" fill="#fff" transform="rotate(0)"/>'
    body += fit(
        text("RERUNS", "Archivo Black", 100, fill="#fff", stroke="#0b2b28", sw=10),
        160,
        190,
        192,
        70,
    )
    body += f'<g filter="url(#sh)">{banner(60, 452, 380, 72, "#e9c46a", "#0b2b28", 6, cut=18)}</g>'
    body += fit(
        text("SEEN IT? SEE IT AGAIN", "Oswald", 40, weight=700, fill="#0b2b28", ls=4),
        110,
        394,
        292,
        44,
    )
    return svg(body, d)


@theme("movie-night", "Movie Night", FORMATS, "movie night", "movies", "family")
def movie_night():
    d = SH
    body = _panel(30, 30, 452, 452, "#1b1f3a", rx=40)
    body += fit(S.popcorn(P(a="#e63946", l="#fff", k="#0b0d1f")), 176, 56, 160, 200)
    body += f'<g filter="url(#sh)">{fit(tilt(text("Movie Night", "Yellowtail", 100, fill="#ffd166", stroke="#0b0d1f", sw=12), -6), 50, 260, 412, 140)}</g>'
    body += fit(
        text("GRAB THE POPCORN", "Oswald", 40, weight=700, fill="#fff", ls=8), 136, 410, 240, 30
    )
    return svg(body, d)


@theme("award-winners", "Award Winners", FORMATS, "award winners", "best picture", "acclaimed")
def award_winners():
    d = SH + lin("g", [(0, "#fff0c4"), (0.5, "#e2b85a"), (1, "#9c7424")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="#0f0d0a" stroke="url(#g)" stroke-width="6"/></g>'
    body += centred(S.laurel(P(a="url(#g)")), 256, 240, 380)
    body += f'<polygon points="{star(256, 150, 44, 18)}" fill="url(#g)"/>'
    body += fit(text("AWARD", "Cinzel", 100, weight=900, fill="url(#g)", ls=8), 170, 206, 172, 50)
    body += fit(text("WINNERS", "Cinzel", 100, weight=900, fill="#fff", ls=8), 160, 266, 192, 44)
    body += fit(
        text("THE ACCLAIMED ONES", "Montserrat", 40, weight=700, fill="#e2b85a", ls=4),
        186,
        322,
        140,
        16,
    )
    return svg(body, d)


@theme("directors-cut", "Director's Cut", FORMATS, "directors cut", "auteur", "movies")
def directors_cut():
    d = SH + rad("sp", [(0, "#3a3f4b"), (1, "#0d0f14")], cy=0.3, r=0.8)
    body = '<g filter="url(#sh)"><rect x="36" y="36" width="440" height="440" rx="28" fill="url(#sp)" stroke="#000" stroke-width="6"/></g>'
    body += '<polygon points="206,36 306,36 400,300 112,300" fill="#fff4d0" opacity=".08"/>'
    chair = (
        '<rect x="36" y="26" width="128" height="50" rx="6" fill="#e63946" stroke="#141414" stroke-width="6"/>'
        '<rect x="40" y="112" width="120" height="18" rx="4" fill="#e63946" stroke="#141414" stroke-width="5"/>'
        '<path d="M52 76 L52 196 M148 76 L148 196 M52 130 L148 196 M148 130 L52 196" stroke="#141414" stroke-width="16" stroke-linecap="round"/>'
        '<path d="M52 76 L52 196 M148 76 L148 196 M52 130 L148 196 M148 130 L52 196" stroke="#d9a35c" stroke-width="9" stroke-linecap="round"/>'
    )
    body += f'<g filter="url(#sh)">{fit(chair, 186, 64, 140, 170)}</g>'
    body += f'<g filter="url(#sh)">{fit(text("DIRECTOR’S", "Oswald", 100, weight=700, fill="#fff", stroke="#141414", sw=10, ls=8), 70, 258, 372, 78)}</g>'
    body += '<line x1="70" y1="392" x2="170" y2="392" stroke="#fff" stroke-width="4" stroke-dasharray="10 8"/><line x1="342" y1="392" x2="442" y2="392" stroke="#fff" stroke-width="4" stroke-dasharray="10 8"/>'
    body += f'<g filter="url(#sh)">{fit(text("CUT", "Anton", 100, fill="#e63946", stroke="#141414", sw=10, ls=16), 186, 350, 140, 88)}</g>'
    return svg(body, d)


@theme("sitcoms", "Sitcoms", FORMATS, "sitcoms", "comedy")
def sitcoms():
    d = SH
    body = '<g filter="url(#sh)"><rect x="30" y="40" width="452" height="432" rx="30" fill="#ffe5ec" stroke="#3a0f24" stroke-width="8"/></g>'
    body += '<rect x="80" y="70" width="140" height="110" rx="6" fill="#bde0fe" stroke="#3a0f24" stroke-width="6"/><line x1="150" y1="70" x2="150" y2="180" stroke="#3a0f24" stroke-width="5"/>'
    body += '<rect x="290" y="80" width="120" height="100" rx="4" fill="#ffd166" stroke="#3a0f24" stroke-width="6"/>'
    body += fit(S.sofa(P(a="#ff5d8f", b="#ffb3c6", k="#3a0f24")), 110, 170, 292, 150)
    body += f'<g filter="url(#sh)">{fit(text("SITCOMS", "Titan One", 100, fill="#fff", stroke="#3a0f24", sw=14, ls=4), 60, 330, 392, 100)}</g>'
    return svg(body, d)


@theme("game-night", "Game Night", FORMATS, "game night", "family", "games")
def game_night():
    d = SH + rad("felt", [(0, "#2d9c5a"), (1, "#14532d")], r=0.7)
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="url(#felt)" stroke="#6b4423" stroke-width="14"/></g>'
    body += f'<g filter="url(#sh)">{fit(S.dice(P(a="#e63946", l="#fff", k="#1d1a2b")), 146, 60, 220, 180)}</g>'
    body += f'<g filter="url(#sh)">{fit(text("GAME NIGHT", "Bungee", 100, fill="#ffd166", stroke="#1d1a2b", sw=12), 60, 260, 392, 90)}</g>'
    body += fit(text("ROLL · SPIN · WIN", "Bungee", 40, fill="#fff", ls=6), 150, 370, 212, 30)
    return svg(body, d)


@theme("sing-along", "Sing-Along", FORMATS, "sing-along", "karaoke", "musicals")
def sing_along():
    d = SH + glow("gl", "#ff4fd8", blur=6)
    body = _panel(36, 36, 440, 440, "#1a1036", rx=220)
    body += fit(S.mic(P(a="#ff4fd8", l="#f0f0f0", k="#0a0616")), 186, 70, 140, 190)
    for x, y in ((130, 130), (380, 110), (400, 200)):
        body += f'<g transform="translate({x - 30} {y - 30}) scale(.3)">{S.notes(P(a="#29d0ff", k="#29d0ff"))}</g>'
    body += f'<g filter="url(#gl)">{fit(text("SING-ALONG", "Tilt Neon", 100, fill="#ffe3fa"), 80, 280, 352, 90)}</g>'
    body += fit(
        text("♪ FOLLOW THE BOUNCING BALL ♪", "DejaVu Sans", 40, weight=700, fill="#29d0ff"),
        110,
        386,
        292,
        26,
    )
    return svg(body, d)


@theme("rainy-day", "Rainy Day", FORMATS, "rainy day", "cozy")
def rainy_day():
    d = SH + lin("g", [(0, "#a8b8c8"), (1, "#5b7083")])
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="40" fill="url(#g)" stroke="#1d2a3a" stroke-width="8"/></g>'
    rng = random.Random(7)
    for _ in range(40):
        x, y = rng.uniform(60, 450), rng.uniform(60, 440)
        body += f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x - 6:.0f}" y2="{y + 18:.0f}" stroke="#e0f0ff" stroke-width="3" stroke-linecap="round" opacity=".6"/>'
    umb = (
        '<path d="M20 110 Q100 10 180 110 Q160 96 140 110 Q120 96 100 110 Q80 96 60 110 Q40 96 20 110 Z" fill="#ffd166" stroke="#1d2a3a" stroke-width="6" stroke-linejoin="round"/>'
        '<path d="M100 110 L100 176 Q100 196 80 190" fill="none" stroke="#1d2a3a" stroke-width="8" stroke-linecap="round"/>'
    )
    body += fit(umb, 166, 60, 180, 200)
    body += f'<g filter="url(#sh)">{fit(text("RAINY DAY", "Carter One", 100, fill="#fff", stroke="#1d2a3a", sw=14, ls=2), 70, 290, 372, 90)}</g>'
    body += fit(
        text("STAY IN · WATCH SOMETHING", "Oswald", 40, weight=700, fill="#1d2a3a", ls=4),
        120,
        394,
        272,
        28,
    )
    return svg(body, d)


@theme("road-trip", "Road Trip", FORMATS, "road trip", "travel", "adventure")
def road_trip():
    d = lin("sky", [(0, "#ffcf70"), (1, "#ff8f5a")], user=True, y2=330)
    scene = '<rect width="512" height="512" fill="url(#sky)"/>'
    scene += '<path d="M40 280 L140 200 L200 250 L280 180 L380 250 L472 210 L472 300 L40 300 Z" fill="#7a4a8a"/>'
    scene += '<rect x="40" y="290" width="440" height="240" fill="#5a3a2a"/>'
    scene += centred(
        S.car(P(a="#2a9d8f", c="#caf0f8", b="#ffd166", l="#fff", k="#10302c")), 256, 250, 220
    )
    return L.emblem(
        scene,
        "ROAD TRIP",
        font="Alfa Slab One",
        ink="#fff",
        band="#e76f51",
        rim="#fff",
        edge="#2a1208",
        defs=d,
        ls=6,
    )


# ======================================================================= kids and family


@theme("kids-zone", "Kids Zone", KIDS, "kids")
def kids_zone():
    return L.bubble(
        "KIDS",
        colors=["#ff4f5e", "#29a6ff", "#ffd12e", "#34c46a"],
        back=(
            f'<g filter="url(#sh)"><polygon points="{star(256, 256, 240, 190, 18)}" fill="#7b2cbf" stroke="#1b1b3a" stroke-width="8" stroke-linejoin="round"/></g>'
        ),
        sub="ZONE",
        sub_fill="#ffd12e",
    )


@theme("toons", "Toons", KIDS, "cartoons", "toons", "kids")
def toons():
    return L.burst_word(
        "TOONS",
        "ALL CARTOONS, ALL DAY",
        font="Luckiest Guy",
        fill="#ffd12e",
        edge="#1b1b3a",
        back="#29a6ff",
        back2="#1565c0",
        sub_fill="#fff",
        sub_font="Luckiest Guy",
        points=14,
        tilt=-6,
        rays=True,
    )


@theme("teen-scene", "Teen Scene", KIDS, "teens")
def teen_scene():
    d = SH
    body = '<g filter="url(#sh)"><rect x="50" y="40" width="412" height="432" rx="6" fill="#fdfcf7" transform="rotate(3 256 256)"/></g>'
    body += '<g transform="rotate(3 256 256)">'
    for y in range(90, 470, 26):
        body += f'<line x1="50" y1="{y}" x2="462" y2="{y}" stroke="#a9d6f5" stroke-width="2"/>'
    body += '<line x1="100" y1="40" x2="100" y2="472" stroke="#f5a3a3" stroke-width="3"/>'
    for y in (100, 250, 400):
        body += f'<circle cx="74" cy="{y}" r="11" fill="#1b1b3a" opacity=".85"/>'
    body += fit(text("TEEN", "Permanent Marker", 100, fill="#7209b7"), 130, 110, 292, 120)
    body += fit(text("SCENE", "Permanent Marker", 100, fill="#f72585"), 150, 240, 280, 110)
    body += f'<polygon points="{star(400, 400, 30, 13)}" fill="#ffd60a" stroke="#1b1b3a" stroke-width="4"/>'
    body += centred(S.heart(P(a="#f72585", l="#fff", k="#1b1b3a")), 170, 400, 60) + "</g>"
    return svg(body, d)


@theme("family-night", "Family Night", KIDS, "family", "movie night")
def family_night():
    return L.script_card(
        "Family Night",
        "TOGETHER ON THE COUCH",
        card="#118ab2",
        card2="#073b4c",
        edge="#1d1a2b",
        ink="#ffd166",
        script_font="Pacifico",
        shape="pill",
        tilt=-6,
    )


@theme("pajama-party", "Pajama Party", KIDS, "sleepover", "kids", "movie night")
def pajama_party():
    d = SH + lin("n", [(0, "#c77dff"), (1, "#5a189a")])
    body = '<g filter="url(#sh)"><rect x="30" y="60" width="452" height="392" rx="196" fill="url(#n)" stroke="#240046" stroke-width="8"/></g>'
    body += centred(S.crescent(P(l="#ffe8a8", b="#d4a93a", k="#240046")), 370, 150, 110)
    for x, y, r in ((130, 140, 12), (190, 110, 8), (300, 120, 9)):
        body += f'<polygon points="{star(x, y, r, r * 0.45)}" fill="#ffe8a8"/>'
    body += '<g filter="url(#sh)"><rect x="100" y="300" width="140" height="90" rx="40" fill="#ff8fab" stroke="#240046" stroke-width="6"/><rect x="270" y="300" width="140" height="90" rx="40" fill="#8ecae6" stroke="#240046" stroke-width="6"/></g>'
    body += f'<g filter="url(#sh)">{fit(text("PJ PARTY", "Luckiest Guy", 100, fill="#fff", stroke="#240046", sw=14, ls=2), 80, 180, 352, 110)}</g>'
    return svg(body, d)


# ======================================================================= on the air


@theme("on-air", "On Air", TV, "on air", "live", "studio")
def on_air():
    d = SH + glow("gl", "#ff2d3d", blur=12, strength=2)
    body = '<g filter="url(#sh)"><rect x="30" y="140" width="452" height="232" rx="26" fill="#1b1b1f" stroke="#050505" stroke-width="8"/></g>'
    body += '<rect x="54" y="164" width="404" height="184" rx="14" fill="#6a0a0f"/>'
    body += '<g filter="url(#gl)"><rect x="54" y="164" width="404" height="184" rx="14" fill="#e5383b" opacity=".85"/></g>'
    body += fit(text("ON AIR", "Oswald", 100, weight=700, fill="#fff", ls=14), 84, 186, 344, 140)
    for x in (140, 372):
        body += f'<rect x="{x - 6}" y="98" width="12" height="44" fill="#050505"/>'
    return svg(body, d)


@theme("test-pattern", "Test Pattern", TV, "test pattern", "retro tv")
def test_pattern():
    d = SH + "<clipPath id='tc'><circle cx='256' cy='256' r='176'/></clipPath>"
    cols = ["#c0c0c0", "#c0c000", "#00c0c0", "#00c000", "#c000c0", "#c00000", "#0000c0"]
    body = '<g filter="url(#sh)"><rect x="24" y="64" width="464" height="384" rx="18" fill="#101010"/></g>'
    for i, c in enumerate(cols):
        body += f'<rect x="{24 + i * 66.3:.1f}" y="64" width="66.3" height="384" fill="{c}"/>'
    body += '<rect x="24" y="64" width="464" height="384" rx="18" fill="none" stroke="#101010" stroke-width="10"/>'
    body += '<circle cx="256" cy="256" r="180" fill="#1b1b1b" stroke="#fff" stroke-width="6"/>'
    body += '<g clip-path="url(#tc)">'
    for x in range(96, 420, 32):
        body += f'<line x1="{x}" y1="60" x2="{x}" y2="452" stroke="#fff" stroke-width="2" opacity=".3"/>'
    for y in range(96, 420, 32):
        body += f'<line x1="60" y1="{y}" x2="452" y2="{y}" stroke="#fff" stroke-width="2" opacity=".3"/>'
    body += "</g>"
    body += '<circle cx="256" cy="256" r="100" fill="none" stroke="#fff" stroke-width="4"/><line x1="256" y1="90" x2="256" y2="422" stroke="#fff" stroke-width="3"/><line x1="90" y1="256" x2="422" y2="256" stroke="#fff" stroke-width="3"/>'
    body += '<rect x="126" y="216" width="260" height="80" rx="8" fill="#101010" stroke="#fff" stroke-width="4"/>'
    body += fit(
        text("TEST PATTERN", "Oswald", 100, weight=700, fill="#fff", ls=4), 140, 228, 232, 56
    )
    return svg(body, d)


@theme("please-stand-by", "Please Stand By", TV, "stand by", "retro tv")
def please_stand_by():
    d = SH
    tv = centred(S.tv_set(P(a="#f4a261", c="#2a9d8f", l="#fff", k="#1d1a2b")), 256, 170, 250)
    body = f'<g filter="url(#sh)">{tv}</g>'
    body += '<g transform="translate(0 0)"><text x="196" y="186" font-family="\'Luckiest Guy\'" font-size="40" fill="#fff" stroke="#1d1a2b" stroke-width="6" paint-order="stroke" text-anchor="middle">?!</text></g>'
    body += f'<g filter="url(#sh)">{banner(24, 488, 322, 80, "#e63946", "#1d1a2b", 6, cut=20)}</g>'
    body += fit(text("PLEASE STAND BY", "Luckiest Guy", 100, fill="#fff", ls=2), 70, 336, 372, 52)
    body += fit(
        text(
            "WE'LL BE RIGHT BACK",
            "Oswald",
            40,
            weight=700,
            fill="#fff",
            stroke="#1d1a2b",
            sw=8,
            ls=6,
        ),
        136,
        422,
        240,
        30,
    )
    return svg(body, d)


@theme("channel-dial", "Channel Dial", TV, "channel", "retro tv")
def channel_dial():
    d = SH + rad("k", [(0, "#f1f1ec"), (1, "#9a9a95")], cx=0.4, cy=0.35, r=0.8)
    body = '<g filter="url(#sh)"><circle cx="256" cy="226" r="190" fill="#2b2d33" stroke="#0e0f12" stroke-width="8"/></g>'
    for k in range(12):
        a = math.radians(-90 + k * 30)
        body += text(
            str(k + 2),
            "Oswald",
            34,
            weight=700,
            fill="#f1f1ec",
            x=256 + 150 * math.cos(a),
            y=238 + 150 * math.sin(a),
        )
    body += '<circle cx="256" cy="226" r="110" fill="url(#k)" stroke="#0e0f12" stroke-width="6"/>'
    body += '<rect x="244" y="126" width="24" height="200" rx="12" fill="#c9ccd1" stroke="#0e0f12" stroke-width="5" transform="rotate(30 256 226)"/>'
    body += '<polygon points="256,40 244,20 268,20" fill="#e63946"/>'
    body += f'<g filter="url(#sh)">{fit(text("CHANNEL", "Righteous", 100, fill="#fff", stroke="#0e0f12", sw=12, ls=10), 90, 424, 332, 64)}</g>'
    return svg(body, d)


@theme("live", "Live", TV, "live", "breaking")
def live():
    d = (
        SH
        + glow("gl", "#ff2d3d", blur=10, strength=2)
        + lin("pn", [(0, "#2b2f38"), (1, "#0d0f14")])
    )
    body = '<g filter="url(#sh)"><rect x="30" y="96" width="452" height="320" rx="30" fill="url(#pn)" stroke="#000" stroke-width="7"/></g>'
    body += '<rect x="50" y="116" width="412" height="280" rx="18" fill="none" stroke="#ff2d3d" stroke-width="4" opacity=".7"/>'
    body += '<g filter="url(#gl)"><circle cx="132" cy="230" r="44" fill="#ff2d3d"/></g><circle cx="132" cy="230" r="20" fill="#fff" opacity=".55"/>'
    body += fit(text("LIVE", "Montserrat", 100, weight=900, fill="#fff", ls=10), 196, 176, 250, 110)
    body += '<rect x="50" y="312" width="412" height="64" fill="#ff2d3d"/>'
    body += fit(
        text("ON THE AIR NOW", "Montserrat", 40, weight=800, fill="#fff", ls=10), 96, 326, 320, 36
    )
    return svg(body, d)


@theme("rabbit-ears", "TV Time", TV, "tv", "retro tv", "antenna")
def tv_time():
    d = lin("sk", [(0, "#ffd166"), (1, "#ef476f")], user=True, y2=340)
    scene = '<rect width="512" height="512" fill="url(#sk)"/>' + centred(
        S.tv_set(P(a="#118ab2", c="#caf0f8", l="#fff", k="#1d1a2b")), 256, 196, 250
    )
    return L.emblem(
        scene,
        "TV TIME",
        font="Righteous",
        ink="#fff",
        band="#1d1a2b",
        rim="#ffd166",
        edge="#1d1a2b",
        defs=d,
        ls=10,
    )


def logos() -> list[Logo]:
    return [Logo(tid, name, cat, fn, tags) for tid, name, cat, tags, fn in THEMES]
