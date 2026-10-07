"""Original networks: one invented channel brand for each kind of cable
channel. The names were checked against real channels (none is one), and
nothing here borrows a real network's name, symbol, colours or lettering."""

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
    skew,
    star,
    svg,
    text,
    tilt,
    worn,
)
from symbols import P, centred

SH = shadow("sh", dy=6, blur=6, opacity=0.45)
BROADCAST = "Broadcast networks"
CABLE = "Cable networks"
MOVIES = "Movie channels"
OTA = "Over-the-air classics"
NETWORKS: list[tuple[str, str, str, list[str], object]] = []  # (id, name, category, tags, draw)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", "and")).strip("-")


def net(name: str, category: str, *tags: str):
    def add(fn):
        NETWORKS.append((slug(name), name, category, list(tags), fn))
        return fn

    return add


def _panel(x, y, w, h, fill, rx=18, edge=None, sw=0):
    st = f' stroke="{edge}" stroke-width="{sw}"' if edge else ""
    return f'<g filter="url(#sh)"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{st}/></g>'


# ======================================================================= movies


@net("Velvet Rope", MOVIES, "premium movies", "movies")
def velvet_rope():
    d = SH + lin("g", [(0, "#fff0c4"), (0.45, "#e2b85a"), (1, "#9c7424")])
    body = _panel(36, 36, 440, 440, "#0f0a10", rx=28)
    body += '<rect x="54" y="54" width="404" height="404" rx="16" fill="none" stroke="url(#g)" stroke-width="3"/>'
    body += fit(S.stanchions(P(a="#9e1b32", b="url(#g)", k="#0f0a10")), 136, 86, 240, 150)
    body += fit(text("VELVET", "Cinzel", 100, weight=700, fill="url(#g)", ls=10), 96, 262, 320, 70)
    body += fit(text("ROPE", "Cinzel", 100, weight=700, fill="url(#g)", ls=24), 150, 344, 212, 52)
    body += '<line x1="120" y1="418" x2="392" y2="418" stroke="#9e1b32" stroke-width="4"/>'
    return svg(body, d)


@net("Night Reel", MOVIES, "late-night movies", "thrillers", "movies")
def night_reel():
    centre = centred(S.crescent(P(l="#ffd98a", b="#c99a3a", k="#0d0b24")), 206, 176, 210) + centred(
        S.reel(P(a="#e8e4ff", l="#e8e4ff", k="#1b1747")), 318, 198, 130
    )
    for x, y in ((120, 110), (360, 92), (410, 170), (160, 250)):
        centre += f'<circle cx="{x}" cy="{y}" r="3" fill="#fff"/>'
    return L.roundel(
        centre,
        "NIGHT REEL",
        font="Bebas Neue",
        ink="#ffd98a",
        disc="#1b1747",
        rim="#ffd98a",
        edge="#0d0b24",
        bar="#0d0b24",
        bar_y=300,
        ls=12,
    )


@net("Projection Booth", MOVIES, "movies")
def projection_booth():
    d = SH
    body = _panel(24, 40, 464, 432, "#161a22", rx=30)
    body += '<polygon points="206,150 470,70 470,300" fill="#fff4c9" opacity=".22"/>'
    body += fit(
        S.projector(P(a="#e63946", b="#fff4c9", l="#f1faee", k="#0b0d12")), 50, 74, 210, 200
    )
    body += fit(text("PROJECTION", "Oswald", 100, weight=700, fill="#fff", ls=4), 54, 300, 404, 74)
    body += fit(text("BOOTH", "Limelight", 100, fill="#ffd166", ls=14), 136, 386, 240, 60)
    return svg(body, d)


@net("Sidestreet Cinema", MOVIES, "independent film", "indie", "movies")
def sidestreet_cinema():
    d = SH
    body = '<g filter="url(#sh)">'
    body += '<rect x="244" y="96" width="24" height="400" rx="6" fill="#56616e" stroke="#1a1f26" stroke-width="5"/>'
    body += '<circle cx="256" cy="84" r="18" fill="#56616e" stroke="#1a1f26" stroke-width="5"/>'
    body += '<g transform="rotate(-6 256 180)"><rect x="18" y="126" width="476" height="112" rx="12" fill="#1e7a46" stroke="#fff" stroke-width="6"/>'
    body += '<rect x="18" y="126" width="476" height="112" rx="12" fill="none" stroke="#10301f" stroke-width="12" opacity=".0"/></g>'
    body += '<g transform="rotate(8 256 330)"><rect x="70" y="282" width="372" height="92" rx="12" fill="#2b4c9b" stroke="#fff" stroke-width="6"/></g>'
    body += "</g>"
    body += f'<g transform="rotate(-6 256 180)">{fit(text("SIDESTREET", "Barlow Condensed", 100, weight=700, fill="#fff", ls=4), 44, 146, 424, 74)}</g>'
    body += f'<g transform="rotate(8 256 330)">{fit(text("CINEMA", "Barlow Condensed", 100, weight=700, fill="#fff", ls=14), 110, 298, 292, 60)}</g>'
    return svg(body, d)


@net("Hearthside", MOVIES, "feel-good movies", "romance", "holiday", "movies")
def hearthside():
    d = SH + rad("fire", [(0, "#ffd166"), (0.5, "#e76f22"), (1, "#5a1a0c")], cx=0.5, cy=0.95, r=0.8)
    arch = "M60 470 L60 200 Q60 40 256 40 Q452 40 452 200 L452 470 Z"
    body = f'<g filter="url(#sh)"><path d="{arch}" fill="#7a2e1c" stroke="#2a120b" stroke-width="8"/></g>'
    for y in range(80, 470, 30):
        off = 0 if (y // 30) % 2 else 28
        body += f'<line x1="60" y1="{y}" x2="452" y2="{y}" stroke="#2a120b" stroke-width="2" opacity=".35"/>'
        for x in range(60 + off, 452, 56):
            body += f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y + 30}" stroke="#2a120b" stroke-width="2" opacity=".35"/>'
    body += '<path d="M110 470 L110 230 Q110 120 256 120 Q402 120 402 230 L402 470 Z" fill="url(#fire)" stroke="#2a120b" stroke-width="6"/>'
    body += f'<path d="{arch}" fill="none" stroke="#e8c07a" stroke-width="4" transform="translate(256 260) scale(.94) translate(-256 -260)"/>'
    body += centred(S.campfire(P(a="#ff7b00", b="#ffd166", k="#2a120b")), 256, 400, 130)
    body += f'<g filter="url(#sh)">{fit(text("Hearthside", "Pacifico", 100, fill="#fff3dc", stroke="#2a120b", sw=14), 44, 170, 424, 150)}</g>'
    body += fit(
        text(
            "FEEL-GOOD MOVIES",
            "Oswald",
            40,
            weight=700,
            fill="#fff3dc",
            stroke="#2a120b",
            sw=8,
            ls=6,
        ),
        146,
        300,
        220,
        28,
    )
    return svg(body, d)


@net("Parlor Mysteries", MOVIES, "cozy mysteries", "mystery", "movies")
def parlor_mysteries():
    d = SH + lin("c", [(0, "#f8f0e3"), (1, "#e9d8bd")])
    body = '<g filter="url(#sh)"><ellipse cx="256" cy="256" rx="236" ry="220" fill="url(#c)" stroke="#3b1f33" stroke-width="8"/></g>'
    body += '<ellipse cx="256" cy="256" rx="216" ry="200" fill="none" stroke="#b08a3e" stroke-width="3"/>'
    body += fit(
        S.teacup(P(a="#7b2d5b", b="#c98a4b", l="#fff", k="#3b1f33"))
        + centred(
            S.magnifier(P(a="#b08a3e", b="#3b1f33", c="#cfe8ff", l="#fff", k="#3b1f33")),
            170,
            60,
            110,
        ),
        156,
        58,
        200,
        150,
    )
    body += fit(
        text("Parlor", "Playfair Display", 100, weight=900, style="italic", fill="#7b2d5b"),
        110,
        222,
        292,
        110,
    )
    body += fit(
        text("MYSTERIES", "Playfair Display", 40, weight=700, fill="#3b1f33", ls=10),
        146,
        350,
        220,
        30,
    )
    body += f'<polygon points="{star(256, 406, 10, 4, 4)}" fill="#b08a3e"/>'
    return svg(body, d)


@net("Saucer Theater", OTA, "b-movies", "creature features", "sci-fi", "movies")
def saucer_theater():
    d = lin("sk", [(0, "#0b2a3a"), (1, "#1f6f78")], user=True, y2=330)
    rng = random.Random(4)
    scene = '<rect width="512" height="512" fill="url(#sk)"/>'
    for _ in range(26):
        scene += f'<circle cx="{rng.uniform(70, 440):.0f}" cy="{rng.uniform(40, 280):.0f}" r="{rng.uniform(1.5, 3):.1f}" fill="#e8fff4"/>'
    scene += centred(S.ufo(P(a="#9be564", b="#e8ff8a", c="#c8f7ff", k="#0b1f16")), 256, 170, 270)
    scene += '<path d="M40 330 Q256 290 472 330 L472 520 L40 520 Z" fill="#0b1f16"/>'
    return L.emblem(
        scene,
        "SAUCER THEATER",
        font="Bangers",
        ink="#e8ff8a",
        band="#0b1f16",
        rim="#9be564",
        edge="#0b1f16",
        defs=d,
        ls=6,
    )


@net("Sundown Trail", MOVIES, "westerns", "movies")
def sundown_trail():
    d = lin("sky", [(0, "#ffcf70"), (0.6, "#f07b3f"), (1, "#a4161a")], user=True, y2=360)
    scene = '<rect width="512" height="512" fill="url(#sky)"/><circle cx="256" cy="250" r="80" fill="#ffe6a8"/>'
    scene += (
        '<path d="M60 330 L140 250 L200 300 L270 230 L360 300 L440 250 L460 330 Z" fill="#6b2a19"/>'
    )
    scene += '<path d="M60 340 L460 340 L460 520 L60 520 Z" fill="#3a1a0e"/>'
    scene += '<path d="M256 340 Q230 380 280 420 Q330 460 250 520 L300 520 Q370 460 320 420 Q280 390 268 340 Z" fill="#c98a4b"/>'
    scene += centred(S.horseshoe(P(a="#e8c07a", k="#3a1a0e")), 256, 120, 90)
    return L.patch(
        scene,
        "SUNDOWN TRAIL",
        font="Rye",
        ink="#ffe6a8",
        band="#7a2414",
        rim="#ffe6a8",
        edge="#2a1208",
        defs=d,
    )


@net("Powder Keg", CABLE, "action movies", "movies")
def powder_keg():
    d = lin("boom", [(0, "#ffd23f"), (1, "#e2361c")], user=True, y2=360)
    scene = '<rect width="512" height="512" fill="#2a0f0a"/>'
    scene += f'<polygon points="{star(256, 200, 190, 120, 14)}" fill="url(#boom)"/>'
    scene += (
        f'<polygon points="{star(256, 200, 110, 70, 14, rot=-77)}" fill="#fff3b0" opacity=".85"/>'
    )
    scene += centred(S.keg(P(a="#8a4b22", b="#ffd23f", l="#f3e3c3", k="#1a0f0a")), 256, 196, 200)
    return L.emblem(
        scene,
        "POWDER KEG",
        font="Black Ops One",
        ink="#ffd23f",
        band="#1a0f0a",
        rim="#ffd23f",
        edge="#1a0f0a",
        defs=d,
        ls=4,
        sub="ACTION",
        sub_font="Black Ops One",
    )


@net("Hollow Moon", MOVIES, "horror", "movies")
def hollow_moon():
    d = SH + rad("gl", [(0, "#b8ff6b"), (1, "#4a7a1a")], r=0.8)
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="#1c0f2e"/></g>'
    body += '<circle cx="256" cy="256" r="220" fill="none" stroke="#7a3fa0" stroke-width="4"/>'
    body += centred(S.crescent(P(l="url(#gl)", b="#2a4a0a", k="#0b0614")), 232, 190, 250)
    body += centred(S.bat(P(k="#0b0614")), 330, 120, 110) + centred(
        S.bat(P(k="#0b0614")), 370, 200, 70
    )
    body += f'<g filter="url(#sh)">{fit(text("HOLLOW MOON", "Pirata One", 100, fill="#e9dcff", stroke="#0b0614", sw=12, ls=2), 58, 318, 396, 94)}</g>'
    return svg(body, d)


# ======================================================================= TV


@net("Vertical Hold", OTA, "classic tv", "reruns")
def vertical_hold():
    return L.tv_screen("Vertical", "HOLD", "CLASSIC TELEVISION")


@net("Tube Town", CABLE, "classic tv", "reruns", "sitcoms")
def tube_town():
    d = SH + lin("sky", [(0, "#ffcf70"), (1, "#ff8f5a")])
    body = '<g filter="url(#sh)"><rect x="24" y="30" width="464" height="452" rx="34" fill="url(#sky)" stroke="#2a1d14" stroke-width="8"/></g>'
    body += '<circle cx="380" cy="100" r="40" fill="#fff4d6"/>'
    body += '<path d="M28 250 Q256 200 484 250 L484 452 Q484 478 458 478 L54 478 Q28 478 28 452 Z" fill="#6fb07f"/>'
    for x, y, sz, pal in (
        (126, 196, 150, ("#e63946", "#f4e3c1", "#4dabf7")),
        (256, 170, 170, ("#2a9d8f", "#f4e3c1", "#ffd166")),
        (386, 200, 140, ("#f4a261", "#f4e3c1", "#9b5de5")),
    ):
        body += centred(
            S.tv_house(P(a=pal[0], b=pal[1], c=pal[2], l="#fff", k="#2a1d14")), x, y, sz
        )
    body += '<rect x="28" y="296" width="456" height="30" fill="#2a1d14" opacity=".0"/>'
    body += f'<g filter="url(#sh)">{fit(text("TUBE TOWN", "Righteous", 100, fill="#fff8e7", stroke="#2a1d14", sw=14, ls=4), 52, 316, 408, 110)}</g>'
    return svg(body, d)


@net("Rimshot", CABLE, "sitcoms", "comedy")
def rimshot():
    extra = (
        '<g transform="translate(372 110) rotate(-16)"><ellipse rx="70" ry="16" fill="#ffd54d" stroke="#1a1024" stroke-width="6"/><ellipse rx="14" ry="5" fill="#b8860b"/>'
        '<line x1="0" y1="-8" x2="0" y2="-26" stroke="#1a1024" stroke-width="6" stroke-linecap="round"/></g>'
    )
    for a in (-40, -10, 20):
        r = math.radians(a)
        extra += f'<line x1="{372 + 90 * math.cos(r):.0f}" y1="{110 + 90 * math.sin(r):.0f}" x2="{372 + 118 * math.cos(r):.0f}" y2="{110 + 118 * math.sin(r):.0f}" stroke="#1a1024" stroke-width="8" stroke-linecap="round"/>'
    return L.burst_word(
        "RIMSHOT",
        "COMEDY 24/7",
        font="Titan One",
        fill="#ffe14d",
        edge="#1a1024",
        back="#ff5a36",
        back2="#d81b3c",
        extra=extra,
        tilt=-8,
    )


@net("Spit Take", CABLE, "sketch comedy", "comedy")
def spit_take():
    d = SH + lin("sp", [(0, "#8ee3ff"), (1, "#1e9bd7")])
    rng = random.Random(6)
    blob = []
    for k in range(28):
        a = math.radians(k * 360 / 28)
        r = 200 if k % 2 else rng.uniform(150, 175)
        blob.append((256 + r * math.cos(a), 250 + r * 0.82 * math.sin(a)))
    pts_ = " ".join(f"{x:.0f},{y:.0f}" for x, y in blob)
    body = f'<g filter="url(#sh)"><polygon points="{pts_}" fill="#10263a" stroke="#10263a" stroke-width="18" stroke-linejoin="round"/>'
    body += f'<polygon points="{pts_}" fill="url(#sp)" stroke="url(#sp)" stroke-width="4" stroke-linejoin="round"/></g>'
    for x, y, r in ((70, 90, 16), (440, 110, 12), (60, 400, 10), (456, 380, 18), (410, 60, 8)):
        body += (
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="#8ee3ff" stroke="#10263a" stroke-width="5"/>'
        )
    w = text("SPIT", "Bangers", 100, fill="#ffe14d", stroke="#10263a", sw=14)
    w2 = text("TAKE!", "Bangers", 100, fill="#fff", stroke="#10263a", sw=14)
    body += fit(
        f'<g transform="rotate(-8)">{extrude(w, 5, 7, 8, "#10263a")}{w}</g>', 96, 110, 320, 150
    )
    body += fit(
        f'<g transform="rotate(-8)">{extrude(w2, 5, 7, 8, "#10263a")}{w2}</g>', 120, 250, 290, 130
    )
    body += fit(
        text("SKETCH COMEDY", "Oswald", 40, weight=700, fill="#10263a", ls=6), 166, 392, 180, 24
    )
    return svg(body, d)


@net("Curtain Call", CABLE, "drama")
def curtain_call():
    d = SH + rad("st", [(0, "#fff4c9"), (1, "#3a0f14")], cx=0.5, cy=0.6, r=0.7)
    body = _panel(24, 40, 464, 432, "#12070a", rx=22)
    body += fit(
        S.proscenium(P(a="#9e1b32", b="#e2b85a", l="#fff4c9", k="#1a0a0e")), 44, 56, 424, 330
    )
    body += '<ellipse cx="256" cy="330" rx="120" ry="26" fill="#fff4c9" opacity=".18"/>'
    body += f'<g filter="url(#sh)">{fit(text("Curtain Call", "Playfair Display", 100, weight=900, style="italic", fill="#fff4c9", stroke="#12070a", sw=12), 70, 196, 372, 110)}</g>'
    body += '<rect x="44" y="392" width="424" height="16" fill="#e2b85a"/>'
    body += fit(
        text("DRAMA SERIES", "Playfair Display", 40, weight=700, fill="#e2b85a", ls=10),
        166,
        422,
        180,
        28,
    )
    return svg(body, d)


@net("Deep Field", CABLE, "sci-fi", "space")
def deep_field():
    centre = centred(S.galaxy(P(a="#ff7ad9", b="#7fdcff", l="#fff6d9", k="#07061a")), 256, 220, 400)
    return L.roundel(
        centre,
        "DEEP FIELD",
        font="Michroma",
        ink="#07061a",
        disc="#07061a",
        rim="#7fdcff",
        edge="#030210",
        bar="#7fdcff",
        bar_y=310,
        ls=4,
    )


@net("Farlight", CABLE, "fantasy")
def farlight():
    d = SH + lin("n", [(0, "#10223f"), (1, "#2d4d7c")], user=True, y2=512)
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="url(#n)" stroke="#e8c96a" stroke-width="6"/></g>'
    body += centred(
        S.lighthouse(P(a="#c1403d", b="#ffe08a", l="#f4efe3", k="#0a1426")), 256, 176, 230
    )
    body += '<path d="M40 300 Q150 280 256 296 Q360 280 472 300 L472 330 L40 330 Z" fill="#0a1426" opacity=".0"/>'
    body += f'<g filter="url(#sh)">{fit(text("FARLIGHT", "Cinzel", 100, weight=900, fill="#ffe08a", stroke="#0a1426", sw=10, ls=6), 72, 300, 368, 82)}</g>'
    body += fit(
        text("TALES OF FANTASY", "Cinzel", 40, weight=700, fill="#f4efe3", ls=6), 150, 394, 212, 24
    )
    return svg(body, d)


@net("Precinct", CABLE, "crime", "police procedurals")
def precinct():
    d = SH + glow("rg", "#ff2d3d", blur=8) + glow("bg", "#2d7dff", blur=8)
    body = _panel(24, 124, 464, 290, "#0f1c3a", rx=22, edge="#050a18", sw=8)
    body += '<g filter="url(#sh)"><rect x="96" y="70" width="320" height="56" rx="26" fill="#1b1f27" stroke="#050a18" stroke-width="6"/></g>'
    body += '<g filter="url(#rg)"><rect x="112" y="80" width="130" height="36" rx="16" fill="#ff2d3d"/></g><g filter="url(#bg)"><rect x="270" y="80" width="130" height="36" rx="16" fill="#2d7dff"/></g>'
    body += fit(text("PRECINCT", "Anton", 100, fill="#fff", ls=6), 60, 168, 392, 140)
    body += '<rect x="60" y="326" width="392" height="6" fill="#ffd23f"/>'
    body += fit(
        text("CRIME & POLICE DRAMA", "Oswald", 40, weight=700, fill="#ffd23f", ls=6),
        96,
        346,
        320,
        40,
    )
    return svg(body, d)


@net("Fingerprint", CABLE, "true crime", "crime")
def fingerprint():
    d = SH
    body = _panel(24, 40, 464, 432, "#f1efe8", rx=10, edge="#141414", sw=8)
    body += centred(S.fingerprint(P(a="#e63946")), 256, 200, 300)
    body += '<g filter="url(#sh)"><rect x="24" y="300" width="464" height="96" fill="#141414"/></g>'
    body += fit(text("FINGERPRINT", "Oswald", 100, weight=700, fill="#fff", ls=6), 50, 316, 412, 64)
    body += fit(text("TRUE CRIME", "Special Elite", 40, fill="#141414", ls=10), 166, 414, 180, 34)
    return svg(body, d)


@net("Locked Room", OTA, "mystery", "whodunit")
def locked_room():
    p = P(a="#b08a3e", l="#e9ecef", k="#1a1330")
    d = SH
    body = _panel(40, 40, 432, 432, "#3b2a5c", rx=36, edge="#1a1330", sw=8)
    body += '<rect x="60" y="60" width="392" height="392" rx="24" fill="none" stroke="#b08a3e" stroke-width="3"/>'
    body += fit(S.padlock(p), 176, 80, 160, 170)
    body += fit(text("LOCKED", "Abril Fatface", 100, fill="#fff", ls=4), 96, 268, 320, 84)
    body += fit(text("ROOM", "Abril Fatface", 100, fill="#b08a3e", ls=18), 150, 364, 212, 62)
    return svg(body, d)


@net("Streetlamp", CABLE, "film noir", "crime")
def streetlamp():
    d = SH + glow("gl", "#ffd98a", blur=10)
    body = _panel(40, 40, 432, 432, "#101626", rx=24)
    rng = random.Random(9)
    for _ in range(40):
        x, y = rng.uniform(60, 450), rng.uniform(60, 300)
        body += f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x - 6:.0f}" y2="{y + 22:.0f}" stroke="#8fa0c0" stroke-width="2" opacity=".35"/>'
    body += '<polygon points="210,90 302,90 400,300 112,300" fill="#ffd98a" opacity=".16"/>'
    body += '<rect x="248" y="96" width="16" height="230" fill="#05070d"/><path d="M216 96 L296 96 L280 60 L232 60 Z" fill="#05070d"/>'
    body += (
        '<g filter="url(#gl)"><path d="M224 96 L288 96 L282 110 L230 110 Z" fill="#ffd98a"/></g>'
    )
    body += fit(
        text(
            "Streetlamp",
            "Playfair Display",
            100,
            weight=900,
            style="italic",
            fill="#fff",
            stroke="#05070d",
            sw=10,
        ),
        66,
        300,
        380,
        92,
    )
    body += fit(
        text("DARK CITY · CLASSIC NOIR", "Oswald", 40, weight=600, fill="#ffd98a", ls=6),
        110,
        406,
        292,
        26,
    )
    return svg(body, d)


@net("Unscripted", OTA, "reality")
def unscripted():
    d = SH + worn("wn", cut=0.9, seed=4)
    body = '<g filter="url(#sh)"><rect x="56" y="70" width="400" height="372" rx="6" fill="#fbfaf5" transform="rotate(-4 256 256)"/></g>'
    body += '<g transform="rotate(-4 256 256)">'
    for y in range(110, 440, 26):
        body += f'<line x1="56" y1="{y}" x2="456" y2="{y}" stroke="#bcd4f0" stroke-width="2"/>'
    body += '<line x1="104" y1="70" x2="104" y2="442" stroke="#f2a1a1" stroke-width="2"/>'
    body += fit(text("SCRIPTED", "Special Elite", 100, fill="#1b1b1b"), 120, 230, 316, 80)
    body += '<path d="M112 266 Q200 250 280 272 T446 262" fill="none" stroke="#e5383b" stroke-width="12" stroke-linecap="round"/>'
    body += "</g>"
    body += fit(
        f'<g transform="rotate(-10)">{text("UN", "Permanent Marker", 100, fill="#e5383b")}</g>',
        96,
        110,
        170,
        120,
    )
    body += fit(
        text("REAL PEOPLE · REAL DRAMA", "Oswald", 40, weight=700, fill="#1b1b1b", ls=4),
        126,
        350,
        272,
        30,
    )
    return svg(body, d)


@net("Monologue", CABLE, "talk shows", "late night")
def monologue():
    d = SH
    body = '<g filter="url(#sh)"><circle cx="256" cy="200" r="170" fill="#16204a" stroke="#0a0f26" stroke-width="8"/></g>'
    body += centred(S.crescent(P(l="#ffd166", b="#c99a3a", k="#0a0f26")), 216, 186, 250)
    body += centred(S.mic(P(a="#e63946", l="#e9eef3", k="#0a0f26")), 316, 214, 170)
    for x, y in ((150, 100), (330, 80), (380, 150)):
        body += f'<circle cx="{x}" cy="{y}" r="4" fill="#fff"/>'
    body += f'<g filter="url(#sh)">{fit(text("MONOLOGUE", "Montserrat", 100, weight=900, fill="#fff", stroke="#0a0f26", sw=14, ls=2), 30, 338, 452, 90)}</g>'
    body += fit(
        text(
            "LATE NIGHT TALK",
            "Montserrat",
            40,
            weight=700,
            fill="#ffd166",
            stroke="#0a0f26",
            sw=8,
            ls=8,
        ),
        136,
        438,
        240,
        30,
    )
    return svg(body, d)


@net("Big Board", CABLE, "game shows")
def big_board():
    d = SH
    body = '<g filter="url(#sh)"><rect x="24" y="70" width="464" height="372" rx="24" fill="#2a0f5c" stroke="#120526" stroke-width="8"/></g>'
    for x in range(44, 480, 24):
        body += f'<circle cx="{x}" cy="90" r="6" fill="#fff3b0"/><circle cx="{x}" cy="422" r="6" fill="#fff3b0"/>'
    for y in range(114, 410, 24):
        body += f'<circle cx="44" cy="{y}" r="6" fill="#fff3b0"/><circle cx="468" cy="{y}" r="6" fill="#fff3b0"/>'
    for i, dgt in enumerate("888"):
        x = 146 + i * 76
        body += f'<rect x="{x}" y="118" width="66" height="92" rx="8" fill="#0b0414" stroke="#ffd23f" stroke-width="4"/>'
        body += fit(text(dgt, "Oswald", 100, weight=700, fill="#ff3d6e"), x + 12, 128, 42, 72)
        body += (
            f'<line x1="{x}" y1="164" x2="{x + 66}" y2="164" stroke="#0b0414" stroke-width="3"/>'
        )
    body += fit(
        text("BIG BOARD", "Bungee", 100, fill="#ffd23f", stroke="#120526", sw=10), 66, 236, 380, 104
    )
    body += fit(text("GAME SHOWS", "Bungee", 40, fill="#fff", ls=8), 150, 356, 212, 34)
    return svg(body, d)


@net("Nitrate", MOVIES, "classic movies", "movies")
def nitrate():
    return L.deco("NITRATE", "CLASSIC FILM", font="Limelight")


# ======================================================================= music


@net("Tonearm", CABLE, "music videos", "music")
def tonearm():
    d = SH + lin("sl", [(0, "#ff5d8f"), (1, "#7b2ff7")])
    body = (
        '<g filter="url(#sh)">'
        + centred(S.vinyl(P(a="#ffd166", l="#111", k="#0d0d12")), 350, 226, 300)
        + "</g>"
    )
    body += '<g filter="url(#sh)"><rect x="24" y="112" width="360" height="360" rx="10" fill="url(#sl)" stroke="#12082b" stroke-width="7"/></g>'
    for i in range(5):
        body += f'<rect x="24" y="{350 + i * 22}" width="360" height="9" fill="#fff" opacity="{0.12 + i * 0.05:.2f}"/>'
    body += '<g transform="translate(420 44) rotate(24)"><circle cx="0" cy="0" r="18" fill="#e9ecef" stroke="#12082b" stroke-width="5"/>'
    body += '<path d="M0 0 L0 150 L-30 184" fill="none" stroke="#12082b" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>'
    body += '<path d="M0 0 L0 150 L-30 184" fill="none" stroke="#e9ecef" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
    body += '<rect x="-48" y="176" width="30" height="20" rx="4" fill="#e9ecef" stroke="#12082b" stroke-width="4" transform="rotate(-40 -33 186)"/></g>'
    body += fit(
        text("TONEARM", "Righteous", 100, fill="#fff", stroke="#12082b", sw=10, ls=2),
        44,
        176,
        320,
        110,
    )
    body += fit(text("MUSIC VIDEOS", "Righteous", 40, fill="#ffd166", ls=6), 70, 296, 268, 36)
    return svg(body, d)


@net("Porch Light", CABLE, "country music", "music")
def porch_light():
    d = (
        SH
        + lin("wood", [(0, "#9c6b3c"), (1, "#6b4423")])
        + glow("gl", "#ffcf6b", blur=14, strength=2)
    )
    body = '<g filter="url(#sh)"><rect x="30" y="30" width="452" height="452" rx="30" fill="#14213d"/></g>'
    for x, y in ((80, 80), (420, 70), (130, 150), (380, 140), (440, 200)):
        body += f'<circle cx="{x}" cy="{y}" r="3" fill="#fff"/>'
    body += f'<g filter="url(#gl)">{centred(S.lantern(P(b="#ffcf6b", l="#fff8e1", k="#0b1224")), 256, 146, 190)}</g>'
    body += '<path d="M120 250 L120 272 M392 250 L392 272" stroke="#c9b28a" stroke-width="5"/>'
    body += '<g filter="url(#sh)"><rect x="54" y="270" width="404" height="120" rx="10" fill="url(#wood)" stroke="#3a220e" stroke-width="6"/></g>'
    for y in (300, 330, 360):
        body += f'<path d="M64 {y} Q180 {y - 6} 300 {y} T448 {y}" fill="none" stroke="#3a220e" stroke-width="2" opacity=".35"/>'
    body += fit(
        text("PORCH LIGHT", "Sancreek", 100, fill="#fff3d6", stroke="#3a220e", sw=8),
        74,
        286,
        364,
        88,
    )
    body += fit(text("COUNTRY MUSIC", "Rye", 40, fill="#ffcf6b", ls=6), 140, 412, 232, 32)
    return svg(body, d)


@net("Bassline", CABLE, "hip-hop", "r&b", "music")
def bassline():
    d = SH + lin("g", [(0, "#ffd166"), (1, "#f7a01d")])
    body = _panel(30, 30, 452, 452, "#1a0f2e", rx=34, edge="#0b0616", sw=8)
    body += '<g fill="none" stroke="#7b2ff7" stroke-width="7" stroke-linecap="round">'
    for r in (120, 150, 180):
        body += (
            f'<path d="M{256 - r} 176 A{r} {r} 0 0 1 {256 + r} 176" opacity="{1.1 - r / 200:.2f}"/>'
        )
    body += "</g>"
    body += '<circle cx="256" cy="176" r="96" fill="#0b0616" stroke="url(#g)" stroke-width="8"/><circle cx="256" cy="176" r="64" fill="#2b1a4a" stroke="#7b2ff7" stroke-width="5"/>'
    body += '<circle cx="256" cy="176" r="26" fill="url(#g)"/>'
    body += fit(
        text("BASSLINE", "Bungee", 100, fill="url(#g)", stroke="#0b0616", sw=8), 60, 300, 392, 90
    )
    body += fit(text("HIP-HOP & R&B", "Bungee", 40, fill="#fff", ls=6), 136, 404, 240, 32)
    return svg(body, d)


@net("Headliner", CABLE, "concerts", "rock", "music")
def headliner():
    d = (
        SH
        + lin("ch", [(0, "#fff6d0"), (0.48, "#f2c14e"), (0.5, "#8a5a06"), (1, "#ffe08a")])
        + rad("fl", [(0, "#ff3d6e"), (1, "#2a0b24")], cx=0.5, cy=1, r=0.9)
    )
    body = _panel(24, 40, 464, 432, "url(#fl)", rx=24)
    for x, a in ((70, 0.35), (442, -0.35), (256, 0)):
        body += f'<polygon points="{x - 16},40 {x + 16},40 {256 + 220 * math.sin(a) + 100},360 {256 + 220 * math.sin(a) - 100},360" fill="#fff6c9" opacity=".22"/>'
    body += '<rect x="24" y="398" width="464" height="74" fill="#12060f"/>'
    for x in range(40, 480, 30):
        body += f'<circle cx="{x}" cy="{404 + (x * 7) % 12}" r="13" fill="#12060f"/>'
    w = text("HEADLINER", "Bungee", 100, fill="url(#ch)", stroke="#12060f", sw=12)
    body += f'<g filter="url(#sh)">{fit(extrude(w, 5, 7, 8, "#12060f") + w, 40, 170, 432, 120)}</g>'
    body += "".join(
        f'<polygon points="{star(x, 134, 20, 8)}" fill="#ffe08a" stroke="#12060f" stroke-width="3"/>'
        for x in (196, 256, 316)
    )
    body += fit(
        text("LIVE IN CONCERT", "Oswald", 40, weight=700, fill="#fff", ls=10), 126, 312, 260, 40
    )
    return svg(body, d)


@net("Jellybean", CABLE, "kids")
def jellybean():
    d = SH
    cols = ["#ff4f7a", "#ff9f1c", "#ffd23f", "#34c46a", "#29a6ff", "#9b5de5"]
    body = '<g filter="url(#sh)"><rect x="24" y="126" width="464" height="260" rx="130" fill="#fff" stroke="#23113d" stroke-width="8"/></g>'
    rng = random.Random(2)
    for i, (x, y) in enumerate(
        ((70, 100), (160, 70), (360, 76), (446, 110), (110, 420), (300, 432), (420, 406))
    ):
        c = cols[i % len(cols)]
        body += f'<ellipse cx="{x}" cy="{y}" rx="26" ry="16" fill="{c}" stroke="#23113d" stroke-width="5" transform="rotate({rng.uniform(-40, 40):.0f} {x} {y})"/>'
    letters, x = "", 0
    for i, ch in enumerate("jellybean"):
        adv, _ = measure(ch, "Fredoka", 700)
        letters += text(
            ch,
            "Fredoka",
            100,
            weight=700,
            fill=cols[i % len(cols)],
            stroke="#23113d",
            sw=12,
            x=x + adv / 2,
            y=-8 if i % 2 else 6,
        )
        x += adv - 2
    body += fit(letters, 56, 170, 400, 150)
    return svg(body, d)


@net("Tiny Town", CABLE, "preschool", "kids")
def tiny_town():
    d = SH + lin("sky", [(0, "#9ee6ff"), (1, "#e7f9ff")])
    body = '<g filter="url(#sh)"><rect x="24" y="30" width="464" height="452" rx="120" fill="url(#sky)" stroke="#23305a" stroke-width="8"/></g>'
    body += centred(S.sun(P(b="#ffd23f", k="#23305a")), 390, 110, 110)
    body += '<path d="M28 300 Q256 230 484 300 L484 390 Q484 478 380 478 L132 478 Q28 478 28 390 Z" fill="#7ed957" stroke="#23305a" stroke-width="0"/>'
    for x, y, sz, a, b in (
        (120, 250, 120, "#ff5a5f", "#fff7e6"),
        (256, 222, 140, "#29a6ff", "#fff7e6"),
        (392, 256, 110, "#ffb13b", "#fff7e6"),
    ):
        body += centred(S.house(P(a=a, b="#ffd23f", l=b, k="#23305a")), x, y, sz)
    body += f'<g filter="url(#sh)">{fit(text("tiny town", "Baloo 2", 100, weight=800, fill="#fff", stroke="#23305a", sw=14), 60, 322, 392, 110)}</g>'
    return svg(body, d)


@net("Doodlebox", CABLE, "cartoons", "kids")
def doodlebox():
    d = SH
    body = '<g filter="url(#sh)"><polygon points="70,250 442,250 412,470 100,470" fill="#c8964f" stroke="#2a1a0c" stroke-width="8" stroke-linejoin="round"/></g>'
    body += '<polygon points="70,250 20,200 190,190 230,250" fill="#b38040" stroke="#2a1a0c" stroke-width="7" stroke-linejoin="round"/><polygon points="442,250 492,200 322,190 282,250" fill="#b38040" stroke="#2a1a0c" stroke-width="7" stroke-linejoin="round"/>'
    doodles = (
        '<path d="M120 170 q20 -60 40 0 t40 0 t40 0" fill="none" stroke="#ff4f7a" stroke-width="10" stroke-linecap="round"/>'
        f'<polygon points="{star(340, 120, 44, 18)}" fill="#ffd23f" stroke="#2a1a0c" stroke-width="6" stroke-linejoin="round"/>'
        '<path d="M250 60 q30 0 30 30 q0 26 -26 26 q-22 0 -22 -22 q0 -18 18 -18 q14 0 14 14" fill="none" stroke="#29a6ff" stroke-width="9" stroke-linecap="round"/>'
        '<circle cx="190" cy="92" r="20" fill="#34c46a" stroke="#2a1a0c" stroke-width="6"/><path d="M400 200 l20 -30 l20 30 z" fill="#9b5de5" stroke="#2a1a0c" stroke-width="6" stroke-linejoin="round"/>'
    )
    body = doodles + body
    cols = ["#ff4f7a", "#ffd23f", "#29a6ff", "#34c46a"]
    letters, x = "", 0
    for i, ch in enumerate("DOODLEBOX"):
        adv, _ = measure(ch, "Londrina Solid", 900)
        letters += text(
            ch,
            "Londrina Solid",
            100,
            weight=900,
            fill=cols[i % 4],
            stroke="#2a1a0c",
            sw=12,
            x=x + adv / 2,
            y=-5 if i % 2 else 5,
        )
        x += adv + 2
    body += fit(letters, 84, 292, 344, 150)
    return svg(body, d)


@net("Sunday Funnies", CABLE, "classic cartoons", "kids")
def sunday_funnies():
    d = (
        SH
        + "<pattern id='ht' width='14' height='14' patternUnits='userSpaceOnUse'><rect width='14' height='14' fill='#ffe066'/><circle cx='7' cy='7' r='3.4' fill='#ff9f1c'/></pattern>"
    )
    body = _panel(24, 40, 464, 432, "#fbf6e8", rx=6, edge="#141414", sw=7)
    body += '<rect x="44" y="60" width="130" height="150" fill="url(#ht)" stroke="#141414" stroke-width="6"/>'
    body += '<rect x="190" y="60" width="130" height="150" fill="#8ecae6" stroke="#141414" stroke-width="6"/><rect x="336" y="60" width="132" height="150" fill="#ffadad" stroke="#141414" stroke-width="6"/>'
    body += '<path d="M60 76 L150 76 Q158 76 158 84 L158 118 Q158 126 150 126 L110 126 L96 142 L98 126 L60 126 Q52 126 52 118 L52 84 Q52 76 60 76 Z" fill="#fff" stroke="#141414" stroke-width="4"/>'
    body += text("HA!", "Bangers", 30, fill="#141414", x=105, y=112)
    body += (
        f'<polygon points="{star(255, 135, 50, 24, 10)}" fill="#fff" stroke="#141414" stroke-width="5"/>'
        + text("POW", "Bangers", 30, fill="#e63946", x=255, y=146)
    )
    body += '<circle cx="402" cy="150" r="30" fill="#fff" stroke="#141414" stroke-width="5"/><circle cx="392" cy="144" r="5" fill="#141414"/><circle cx="412" cy="144" r="5" fill="#141414"/><path d="M388 160 Q402 172 416 160" fill="none" stroke="#141414" stroke-width="4"/>'
    body += fit(
        text("SUNDAY", "Bangers", 100, fill="#e63946", stroke="#141414", sw=10, ls=4),
        60,
        226,
        392,
        110,
    )
    body += fit(
        text("FUNNIES", "Bangers", 100, fill="#1d4ed8", stroke="#141414", sw=10, ls=4),
        90,
        344,
        332,
        100,
    )
    return svg(body, d)


@net("Hyperbeam", CABLE, "anime")
def hyperbeam():
    d = (
        SH
        + lin("beam", [(0, "#2fe6ff"), (0.5, "#ffffff"), (1, "#ff4fd8")], x2=1, y2=0)
        + glow("gl", "#2fe6ff", blur=10, strength=2)
    )
    d += lin("wf", [(0, "#ffffff"), (1, "#9ff3ff")])
    body = _panel(24, 60, 464, 392, "#0d0a24", rx=30, edge="#2fe6ff", sw=4)
    for i in range(14):
        y = 90 + i * 26
        body += f'<line x1="{40 + (i * 37) % 90}" y1="{y}" x2="{250 + (i * 53) % 200}" y2="{y}" stroke="#fff" stroke-width="2" opacity=".18"/>'
    body += '<g filter="url(#gl)"><polygon points="30,300 470,236 480,276 30,324" fill="url(#beam)"/></g>'
    w = text("HYPER", "Russo One", 100, fill="url(#wf)", stroke="#0d0a24", sw=12, style="italic")
    w2 = text("BEAM", "Russo One", 100, fill="url(#wf)", stroke="#0d0a24", sw=12, style="italic")
    body += fit(
        '<g transform="skewX(-14)">' + extrude(w, 6, 6, 8, "#ff4fd8") + w + "</g>", 60, 96, 392, 120
    )
    body += fit(
        '<g transform="skewX(-14)">' + extrude(w2, 6, 6, 8, "#ff4fd8") + w2 + "</g>",
        110,
        212,
        300,
        110,
    )
    body += fit(text("ANIME", "Russo One", 40, fill="#2fe6ff", ls=20), 186, 360, 140, 44)
    return svg(body, d)


@net("Homeroom", CABLE, "teens")
def homeroom():
    d = SH + lin("met", [(0, "#3f6fd8"), (1, "#244a9e")], x2=1, y2=0)
    body = '<g filter="url(#sh)"><rect x="96" y="20" width="320" height="472" rx="12" fill="url(#met)" stroke="#0f1d40" stroke-width="8"/></g>'
    body += '<rect x="116" y="40" width="280" height="432" rx="6" fill="none" stroke="#0f1d40" stroke-width="3" opacity=".6"/>'
    for y in range(64, 140, 16):
        body += (
            f'<rect x="170" y="{y}" width="172" height="8" rx="4" fill="#0f1d40" opacity=".55"/>'
        )
    body += (
        '<rect x="226" y="160" width="60" height="30" rx="4" fill="#d9dde6" stroke="#0f1d40" stroke-width="4"/>'
        + text("22", "Oswald", 26, weight=700, fill="#0f1d40", x=256, y=184)
    )
    body += '<rect x="360" y="250" width="16" height="70" rx="6" fill="#d9dde6" stroke="#0f1d40" stroke-width="4"/>'
    body += '<g filter="url(#sh)" transform="rotate(-6 256 300)"><rect x="40" y="224" width="432" height="150" rx="8" fill="#fff" stroke="#0f1d40" stroke-width="6"/></g>'
    body += f'<g transform="rotate(-6 256 300)">{fit(text("HOMEROOM", "Permanent Marker", 100, fill="#e63946"), 66, 240, 380, 100)}'
    body += (
        fit(text("TEEN TV", "Permanent Marker", 40, fill="#1d4ed8", ls=6), 190, 336, 132, 30)
        + "</g>"
    )
    body += f'<polygon points="{star(420, 190, 30, 13)}" fill="#ffd23f" stroke="#0f1d40" stroke-width="5" transform="rotate(12 420 190)"/>'
    return svg(body, d)


@net("Night Doodle", CABLE, "adult animation", "cartoons")
def night_doodle():
    d = (
        SH
        + glow("pk", "#ff4fd8", blur=5)
        + glow("cy", "#2fe6ff", blur=5)
        + glow("yl", "#ffe14d", blur=5)
    )
    body = _panel(24, 40, 464, 432, "#0b0b12", rx=28)
    body += '<g filter="url(#yl)"><path d="M150 90 A70 70 0 1 0 220 190 A56 56 0 1 1 150 90 Z" fill="none" stroke="#ffe14d" stroke-width="6" stroke-linejoin="round"/></g>'
    body += f'<g filter="url(#cy)"><polygon points="{star(360, 110, 30, 12)}" fill="none" stroke="#2fe6ff" stroke-width="5" stroke-linejoin="round"/><polygon points="{star(420, 190, 18, 7)}" fill="none" stroke="#2fe6ff" stroke-width="4"/></g>'
    body += '<g filter="url(#pk)"><path d="M280 180 q16 -30 32 0 t32 0" fill="none" stroke="#ff4fd8" stroke-width="6" stroke-linecap="round"/></g>'
    body += f'<g filter="url(#pk)">{fit(text("NIGHT", "Permanent Marker", 100, fill="#ff4fd8"), 70, 230, 372, 100)}</g>'
    body += f'<g filter="url(#cy)">{fit(text("DOODLE", "Permanent Marker", 100, fill="#2fe6ff"), 90, 336, 332, 100)}</g>'
    return svg(body, d)


# ======================================================================= knowledge


@net("Viewfinder", CABLE, "documentary")
def viewfinder():
    d = SH
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="#0e1c22" stroke="#050b0e" stroke-width="8"/></g>'
    for k in range(60):
        a = math.radians(k * 6)
        r1 = 206 if k % 5 else 196
        body += f'<line x1="{256 + r1 * math.cos(a):.1f}" y1="{256 + r1 * math.sin(a):.1f}" x2="{256 + 218 * math.cos(a):.1f}" y2="{256 + 218 * math.sin(a):.1f}" stroke="#7fe3d6" stroke-width="{3 if k % 5 == 0 else 1.5}"/>'
    body += '<circle cx="256" cy="256" r="150" fill="none" stroke="#7fe3d6" stroke-width="3" opacity=".6"/>'
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        body += f'<path d="M{256 + sx * 150} {256 + sy * 70} L{256 + sx * 150} {256 + sy * 100} L{256 + sx * 120} {256 + sy * 100}" fill="none" stroke="#fff" stroke-width="5"/>'
    body += '<line x1="256" y1="140" x2="256" y2="170" stroke="#fff" stroke-width="3"/><line x1="256" y1="342" x2="256" y2="372" stroke="#fff" stroke-width="3"/>'
    body += fit(
        text("VIEWFINDER", "Montserrat", 100, weight=800, fill="#fff", ls=4), 110, 222, 292, 52
    )
    body += fit(
        text("DOCUMENTARIES", "Montserrat", 40, weight=700, fill="#7fe3d6", ls=6), 166, 286, 180, 20
    )
    return svg(body, d)


@net("Periodic", CABLE, "science")
def periodic():
    d = SH + lin("t", [(0, "#ffe8c7"), (1, "#ffc98a")])
    body = '<g filter="url(#sh)"><rect x="96" y="30" width="320" height="320" rx="18" fill="url(#t)" stroke="#3a1c71" stroke-width="8"/></g>'
    body += '<rect x="96" y="30" width="320" height="64" rx="18" fill="#3a1c71"/><rect x="96" y="70" width="320" height="24" fill="#3a1c71"/>'
    body += text("42", "Space Grotesk", 44, weight=700, fill="#ffe8c7", x=124, y=80, anchor="start")
    body += text("4.2", "Space Grotesk", 30, weight=500, fill="#ffe8c7", x=388, y=78, anchor="end")
    body += fit(text("Pe", "Space Grotesk", 100, weight=700, fill="#3a1c71"), 150, 116, 212, 150)
    body += fit(
        text("Periodium", "Space Grotesk", 40, weight=500, fill="#3a1c71"), 160, 290, 192, 32
    )
    body += f'<g filter="url(#sh)">{fit(text("PERIODIC", "Space Grotesk", 100, weight=700, fill="#fff", stroke="#3a1c71", sw=12, ls=6), 40, 372, 432, 86)}</g>'
    return svg(body, d)


@net("Almanac", CABLE, "history")
def almanac():
    d = (
        SH
        + lin("lea", [(0, "#7a3b1d"), (1, "#4a200e")])
        + lin("gold", [(0, "#f6e3a1"), (1, "#b8912f")])
    )
    body = '<g filter="url(#sh)"><rect x="70" y="24" width="372" height="464" rx="10" fill="url(#lea)" stroke="#2a1006" stroke-width="7"/></g>'
    body += '<rect x="70" y="24" width="32" height="464" fill="#2a1006" opacity=".5"/>'
    body += '<rect x="120" y="50" width="298" height="412" rx="4" fill="none" stroke="url(#gold)" stroke-width="4"/><rect x="132" y="62" width="274" height="388" rx="2" fill="none" stroke="url(#gold)" stroke-width="1.5"/>'
    body += '<clipPath id="half"><rect x="190" y="90" width="80" height="170"/></clipPath>'
    body += '<circle cx="270" cy="170" r="66" fill="url(#gold)"/>'
    for k in range(16):
        a = math.radians(k * 22.5)
        body += f'<line x1="{270 + 74 * math.cos(a):.0f}" y1="{170 + 74 * math.sin(a):.0f}" x2="{270 + 92 * math.cos(a):.0f}" y2="{170 + 92 * math.sin(a):.0f}" stroke="url(#gold)" stroke-width="5" stroke-linecap="round" opacity="{0 if 90 < k * 22.5 < 270 else 1}"/>'
    body += '<path d="M270 104 A66 66 0 0 0 270 236 A50 66 0 0 1 270 104 Z" fill="#4a200e"/>'
    body += fit(text("ALMANAC", "IM Fell English", 100, fill="url(#gold)", ls=4), 136, 280, 266, 70)
    body += '<line x1="176" y1="366" x2="362" y2="366" stroke="url(#gold)" stroke-width="2"/>'
    body += fit(
        text("HISTORY · DAY BY DAY", "IM Fell English", 40, fill="#f6e3a1", ls=3), 150, 380, 238, 26
    )
    return svg(body, d)


@net("Muster", CABLE, "military history", "war")
def muster():
    p = P(a="#6b1e1e", b="#c9a24a", l="#f1e6c8", k="#1a1508")
    d = lin("od", [(0, "#56602b"), (1, "#39401a")], user=True, y2=512)
    scene = '<rect width="512" height="512" fill="url(#od)"/>'
    scene += "".join(
        f'<polygon points="{star(x, 110, 14, 6)}" fill="#f1e6c8"/>' for x in (120, 392)
    )
    scene += centred(S.drum(p), 256, 196, 250)
    return L.emblem(
        scene,
        "MUSTER",
        font="Black Ops One",
        ink="#f1e6c8",
        band="#1a1508",
        rim="#c9a24a",
        edge="#1a1508",
        defs=d,
        ls=16,
        sub="MILITARY HISTORY",
        sub_font="Black Ops One",
    )


# ======================================================================= nature, travel


@net("Burrow & Branch", CABLE, "animals", "wildlife", "nature")
def burrow_and_branch():
    d = lin("sky", [(0, "#cfe9c7"), (1, "#8ebf7a")], user=True, y2=300)
    scene = '<rect width="512" height="512" fill="url(#sky)"/>'
    for cx, cy, r in (
        (200, 120, 70),
        (280, 100, 80),
        (340, 150, 66),
        (160, 180, 60),
        (256, 170, 80),
        (330, 210, 50),
    ):
        scene += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#2d6a4f"/>'
    for cx, cy, r in ((230, 110, 30), (300, 130, 24), (190, 170, 22)):
        scene += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#40916c"/>'
    scene += '<path d="M240 330 L244 210 L232 180 L252 200 L262 160 L270 206 L290 186 L276 222 L280 330 Z" fill="#6b4423"/>'
    scene += '<path d="M40 300 Q256 270 472 300 L472 520 L40 520 Z" fill="#7a5230"/>'
    scene += '<path d="M244 300 Q200 330 180 380 M276 300 Q320 340 350 370 M262 300 L262 380" fill="none" stroke="#5a3a1f" stroke-width="10" stroke-linecap="round"/>'
    scene += '<ellipse cx="150" cy="330" rx="54" ry="30" fill="#2a1a0c"/>'
    scene += '<ellipse cx="136" cy="290" rx="9" ry="30" fill="#c9b28a" stroke="#2a1a0c" stroke-width="4"/><ellipse cx="160" cy="290" rx="9" ry="30" fill="#c9b28a" stroke="#2a1a0c" stroke-width="4"/>'
    scene += '<ellipse cx="148" cy="322" rx="30" ry="22" fill="#c9b28a" stroke="#2a1a0c" stroke-width="4"/><circle cx="138" cy="318" r="4" fill="#2a1a0c"/><circle cx="158" cy="318" r="4" fill="#2a1a0c"/>'
    return L.emblem(
        scene,
        "BURROW & BRANCH",
        font="Alfa Slab One",
        ink="#f6efe0",
        band="#2d6a4f",
        rim="#f6efe0",
        edge="#1b3a2b",
        defs=d,
    )


@net("Tidepool", CABLE, "ocean", "nature")
def tidepool():
    d = lin("sea", [(0, "#7fe0e0"), (1, "#0f6f8a")], user=True, y2=400)
    scene = '<rect width="512" height="512" fill="url(#sea)"/>'
    for y in (90, 130, 170):
        scene += f'<path d="M40 {y} q30 -14 60 0 t60 0 t60 0 t60 0 t60 0 t60 0 t60 0" fill="none" stroke="#fff" stroke-width="4" opacity=".35"/>'
    scene += '<path d="M40 290 Q120 250 200 280 Q280 240 360 280 Q420 260 472 290 L472 520 L40 520 Z" fill="#6d5a4a"/>'
    scene += '<ellipse cx="120" cy="300" rx="60" ry="26" fill="#8a7662"/><ellipse cx="390" cy="296" rx="70" ry="28" fill="#7a6552"/>'
    scene += centred(S.starfish(P(a="#ff7b54", l="#ffd6c2", k="#5a1a0c")), 256, 230, 150)
    scene += '<circle cx="360" cy="220" r="16" fill="#9b5de5" stroke="#2a1540" stroke-width="4"/><circle cx="160" cy="236" r="12" fill="#ffd23f" stroke="#5a4a0c" stroke-width="4"/>'
    return L.emblem(
        scene,
        "tidepool",
        font="Fredoka",
        weight=700,
        ink="#fff",
        band="#0f6f8a",
        rim="#fff",
        edge="#0a3a4a",
        defs=d,
        ls=4,
    )


@net("Postcard", CABLE, "travel")
def postcard():
    d = SH + lin(
        "scn",
        [(0, "#ffb347"), (0.45, "#ff6f61"), (0.46, "#1e90c8"), (1, "#0b4f7a")],
        user=True,
        y1=200,
        y2=330,
    )
    word = "POSTCARD"
    d += f"<clipPath id='wc'>{text(word, 'Bowlby One', 100, x=256, y=320, ls=0)}</clipPath>"
    body = '<g filter="url(#sh)" transform="rotate(-4 256 256)"><rect x="20" y="96" width="472" height="320" rx="10" fill="#fdf6e3" stroke="#1d2433" stroke-width="7"/></g>'
    body += '<g transform="rotate(-4 256 256)"><rect x="410" y="112" width="64" height="76" fill="#e63946" stroke="#1d2433" stroke-width="4" stroke-dasharray="5 4"/>'
    body += '<circle cx="400" cy="150" r="34" fill="none" stroke="#1d2433" stroke-width="3" opacity=".6"/>'
    inner = (
        f"<g>{text(word, 'Bowlby One', 100, fill='#1d2433', stroke='#1d2433', sw=16, x=256, y=320)}"
        f'<g clip-path="url(#wc)"><rect x="0" y="200" width="512" height="140" fill="url(#scn)"/>'
        f'<path d="M0 300 L80 260 L140 290 L220 250 L300 290 L380 256 L512 300 L512 340 L0 340 Z" fill="#2a1d44" opacity=".85"/>'
        f'<circle cx="340" cy="262" r="26" fill="#fff3b0"/></g>'
        f"{text(word, 'Bowlby One', 100, fill='none', stroke='#fff', sw=3, x=256, y=320)}</g>"
    )
    body += fit(inner, 44, 196, 424, 130)
    body += fit(text("Greetings from", "Yellowtail", 100, fill="#e63946"), 50, 126, 260, 70)
    body += fit(
        text("TRAVEL THE WORLD", "Oswald", 40, weight=700, fill="#1d2433", ls=8), 136, 350, 240, 30
    )
    body += "</g>"
    return svg(body, d)


@net("Skillet", CABLE, "food", "cooking")
def skillet():
    d = SH + rad("pan", [(0, "#ff9b3d"), (0.6, "#e0531f"), (1, "#a1300f")], cx=0.45, cy=0.4, r=0.7)
    body = '<g filter="url(#sh)"><path d="M360 330 L486 452 Q496 464 484 474 Q472 484 460 472 L334 352 Z" fill="#1d1a19"/>'
    body += '<circle cx="232" cy="236" r="206" fill="#1d1a19"/><circle cx="232" cy="236" r="176" fill="url(#pan)"/>'
    body += '<circle cx="232" cy="236" r="176" fill="none" stroke="#000" stroke-opacity=".25" stroke-width="10"/><circle cx="470" cy="458" r="6" fill="#5a5250"/></g>'
    body += fit(
        f'<g transform="rotate(-8)">{text("skillet", "Pacifico", 100, fill="#fff6e6", stroke="#3a1206", sw=12)}</g>',
        70,
        140,
        324,
        170,
    )
    body += fit(
        text("FOOD  ·  KITCHEN", "Oswald", 40, weight=600, fill="#fff6e6", ls=4), 142, 326, 180, 24
    )
    for dx in (-40, 0, 40):
        body += f'<path d="M{232 + dx} 100 q-10 -14 0 -28 q10 -14 0 -28" fill="none" stroke="#fff6e6" stroke-width="7" stroke-linecap="round" opacity=".9"/>'
    return svg(body, d)


@net("Butter & Crumb", CABLE, "baking", "food")
def butter_and_crumb():
    d = SH + lin("c", [(0, "#fff4dc"), (1, "#f6dcb0")])
    body = '<g filter="url(#sh)"><ellipse cx="256" cy="256" rx="236" ry="210" fill="url(#c)" stroke="#5a3a22" stroke-width="8"/></g>'
    body += '<ellipse cx="256" cy="256" rx="216" ry="190" fill="none" stroke="#d98c8c" stroke-width="3" stroke-dasharray="2 10" stroke-linecap="round"/>'
    body += fit(
        S.cupcake(P(a="#e76f7a", b="#f4b860", c="#6ec6ff", l="#fff", k="#5a3a22")),
        196,
        58,
        120,
        124,
    )
    body += fit(text("Butter", "Pacifico", 100, fill="#5a3a22"), 110, 180, 292, 90)
    body += fit(
        text("& CRUMB", "Fraunces", 100, weight=800, fill="#e76f7a", ls=6), 150, 282, 212, 60
    )
    body += fit(
        text("BAKING SHOW", "Oswald", 40, weight=600, fill="#5a3a22", ls=8), 186, 362, 140, 22
    )
    return svg(body, d)


@net("Hammer & Bloom", CABLE, "home and garden", "diy")
def hammer_and_bloom():
    sym = centred(S.hammer(P(b="#8a5a2b", l="#cfd8dc", k="#1d2a1d")), 90, 100, 190) + centred(
        S.flower(P(a="#ff6b6b", b="#ffd166", k="#1d2a1d")), 118, 96, 170
    )
    return L.crest(
        sym,
        "HAMMER & BLOOM",
        font="Alfa Slab One",
        ink="#1d2a1d",
        field="#6fb07f",
        field2="#2f6b45",
        rim="#f4efe3",
        edge="#1d2a1d",
        scroll="#f4efe3",
        scroll_dark="#c9b99a",
    )


@net("Sawdust", CABLE, "diy", "workshop")
def sawdust():
    d = (
        SH
        + lin("wood", [(0, "#e2b77a"), (1, "#b98446")])
        + lin("st", [(0, "#eef2f5"), (1, "#9aa6b2")])
    )
    teeth = []
    for k in range(48):
        a = math.radians(k * 7.5)
        r = 214 if k % 2 == 0 else 190
        teeth.append((256 + r * math.cos(a), 250 + r * math.sin(a)))
    body = f'<g filter="url(#sh)"><polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in teeth)}" fill="url(#st)" stroke="#2a3038" stroke-width="6" stroke-linejoin="round"/></g>'
    body += '<circle cx="256" cy="250" r="150" fill="none" stroke="#2a3038" stroke-width="3" opacity=".5"/><circle cx="256" cy="250" r="22" fill="#2a3038"/>'
    body += '<g filter="url(#sh)"><rect x="20" y="194" width="472" height="118" rx="8" fill="url(#wood)" stroke="#4a2c12" stroke-width="7"/></g>'
    for y in (214, 240, 270, 292):
        body += f'<path d="M30 {y} Q160 {y - 8} 280 {y} T482 {y - 4}" fill="none" stroke="#8a5a2b" stroke-width="2" opacity=".5"/>'
    body += fit(
        text("SAWDUST", "Alfa Slab One", 100, fill="#fff8ec", stroke="#4a2c12", sw=10, ls=4),
        50,
        208,
        412,
        90,
    )
    body += fit(
        text("MAKE · FIX · BUILD", "Oswald", 40, weight=700, fill="#2a3038", ls=6),
        166,
        350,
        180,
        28,
    )
    return svg(body, d)


@net("Piston Alley", CABLE, "cars", "motors")
def piston_alley():
    d = (
        SH
        + "<pattern id='chk' width='40' height='40' patternUnits='userSpaceOnUse'><rect width='40' height='40' fill='#fff'/><rect width='20' height='20' fill='#141414'/><rect x='20' y='20' width='20' height='20' fill='#141414'/></pattern>"
    )
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="#1d1d24" stroke="#0a0a0e" stroke-width="8"/></g>'
    body += '<clipPath id="dc"><circle cx="256" cy="256" r="222"/></clipPath><g clip-path="url(#dc)"><rect x="0" y="40" width="512" height="80" fill="url(#chk)"/><rect x="0" y="392" width="512" height="80" fill="url(#chk)"/></g>'
    for rot in (-35, 35):
        body += f'<g transform="rotate({rot} 256 256)">{centred(S.piston(P(a="#e63946", l="#e9ecef", k="#0a0a0e")), 256, 256, 250)}</g>'
    w = text("PISTON ALLEY", "Racing Sans One", 100, fill="#ffd23f", stroke="#0a0a0e", sw=14)
    body += f'<g filter="url(#sh)">{fit(extrude(w, 6, 6, 8, "#0a0a0e") + w, 30, 200, 452, 110)}</g>'
    return svg(body, d)


@net("Trailhead", CABLE, "outdoors", "hunting", "fishing")
def trailhead():
    d = lin("sky", [(0, "#f6e7b8"), (1, "#f0c878")])
    scene = '<rect width="512" height="512" fill="url(#sky)"/><circle cx="320" cy="190" r="38" fill="#f7f1dc"/>'
    scene += '<path d="M60 300 L150 190 L200 240 L262 160 L360 290 L400 250 L460 300 L460 520 L60 520 Z" fill="#6b8f5e"/>'
    scene += '<path d="M262 160 L292 200 L276 196 L262 214 L248 194 L236 196 Z" fill="#f7f1dc"/><path d="M60 330 L460 330 L460 520 L60 520 Z" fill="#2f5a40"/>'
    for i, x in enumerate(range(80, 460, 34)):
        h = 70 + (i * 37) % 40
        scene += f'<path d="M{x} {344 - h} L{x + 18} 344 L{x - 18} 344 Z" fill="#1f3a2b"/>'
    scene += '<path d="M150 128 q14 -12 28 0 q14 -12 28 0 q-14 -4 -28 8 q-14 -12 -28 -8 Z" fill="#1f3a2b"/>'
    return L.patch(
        scene,
        "TRAILHEAD",
        font="Alfa Slab One",
        ink="#f7f1dc",
        band="#b5532a",
        rim="#f7f1dc",
        edge="#1f3a2b",
        defs=d,
        ls=4,
    )


@net("Home Stretch", CABLE, "sports")
def home_stretch():
    d = (
        SH
        + "<pattern id='chk' width='24' height='24' patternUnits='userSpaceOnUse'><rect width='24' height='24' fill='#fff'/><rect width='12' height='12' fill='#141414'/><rect x='12' y='12' width='12' height='12' fill='#141414'/></pattern>"
    )
    body = '<g filter="url(#sh)"><rect x="24" y="60" width="464" height="392" rx="196" fill="#2d6a4f" stroke="#0f2a1c" stroke-width="8"/></g>'
    body += '<rect x="64" y="100" width="384" height="312" rx="156" fill="none" stroke="#fff" stroke-width="5" opacity=".7"/>'
    body += '<rect x="104" y="140" width="304" height="232" rx="116" fill="#b5835a"/>'
    body += '<rect x="340" y="60" width="24" height="80" fill="url(#chk)" stroke="#0f2a1c" stroke-width="3"/>'
    w = text(
        "HOME STRETCH",
        "Teko",
        100,
        weight=700,
        fill="#fff",
        stroke="#0f2a1c",
        sw=12,
        style="normal",
    )
    skewed = '<g transform="skewX(-12)">' + w + "</g>"
    body += f'<g filter="url(#sh)">{fit(skewed, 60, 196, 392, 100)}</g>'
    body += fit(text("SPORTS", "Teko", 60, weight=600, fill="#ffd23f", ls=16), 196, 300, 120, 40)
    return svg(body, d)


# ======================================================================= broadcast networks


def _butterfly(a: str, b: str, k: str) -> str:
    wing_u = "M100 100 Q70 20 20 30 Q-4 36 14 76 Q30 104 100 104 Z"
    wing_l = "M100 104 Q40 108 34 144 Q30 180 64 176 Q96 170 100 108 Z"
    s = ""
    for flip in ("", ' transform="translate(200 0) scale(-1 1)"'):
        s += (
            f'<g{flip}><path d="{wing_u}" fill="{a}" stroke="{k}" stroke-width="6" stroke-linejoin="round"/>'
            f'<path d="{wing_l}" fill="{b}" stroke="{k}" stroke-width="6" stroke-linejoin="round"/>'
            f'<circle cx="46" cy="60" r="12" fill="#fff" opacity=".85"/><circle cx="62" cy="144" r="8" fill="#fff" opacity=".85"/></g>'
        )
    s += f'<rect x="93" y="60" width="14" height="100" rx="7" fill="{k}"/>'
    s += f'<path d="M98 62 Q86 30 70 22 M102 62 Q114 30 130 22" fill="none" stroke="{k}" stroke-width="4" stroke-linecap="round"/>'
    return s


@net("Keynote", BROADCAST, "broadcast network", "general entertainment")
def keynote():
    d = (
        SH
        + lin("nv", [(0, "#24345f"), (1, "#0e1733")])
        + lin("gd", [(0, "#fff0b8"), (0.5, "#f2c14e"), (1, "#b07d12")])
    )
    body = '<g filter="url(#sh)"><rect x="106" y="30" width="300" height="300" rx="70" fill="url(#nv)" stroke="#060b1c" stroke-width="8"/></g>'
    body += '<rect x="122" y="46" width="268" height="268" rx="56" fill="none" stroke="url(#gd)" stroke-width="3"/>'
    key = (
        '<circle cx="62" cy="100" r="48" fill="none" stroke="url(#gd)" stroke-width="22"/>'
        '<rect x="104" y="89" width="92" height="22" rx="6" fill="url(#gd)"/>'
        '<rect x="160" y="108" width="14" height="30" rx="3" fill="url(#gd)"/><rect x="180" y="108" width="12" height="22" rx="3" fill="url(#gd)"/>'
        '<circle cx="62" cy="100" r="16" fill="url(#gd)"/>'
    )
    body += fit(f'<g transform="rotate(-35 100 100)">{key}</g>', 150, 70, 212, 220)
    body += f'<g filter="url(#sh)">{fit(text("KEYNOTE", "Montserrat", 100, weight=900, fill="#fff", stroke="#060b1c", sw=12, ls=8), 40, 360, 432, 84)}</g>'
    return svg(body, d)


@net("Lodestar", BROADCAST, "broadcast network", "general entertainment")
def lodestar():
    d = SH + lin("b", [(0, "#2f6fe0"), (1, "#0d2a78")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="186" r="156" fill="url(#b)" stroke="#071640" stroke-width="8"/></g>'
    body += f'<polygon points="{star(256, 186, 128, 26, 4)}" fill="#fff"/><polygon points="{star(256, 186, 76, 18, 4, rot=-45)}" fill="#ffd166"/>'
    body += '<circle cx="256" cy="186" r="12" fill="#0d2a78"/>'
    body += f'<g filter="url(#sh)">{fit(text("LODESTAR", "Montserrat", 100, weight=800, fill="#fff", stroke="#071640", sw=12, ls=10), 40, 368, 432, 76)}</g>'
    return svg(body, d)


@net("Falconer", BROADCAST, "broadcast network", "general entertainment")
def falconer():
    d = (
        SH
        + lin("t", [(0, "#1d7874"), (1, "#0b3c3a")])
        + lin("gd", [(0, "#ffe29a"), (1, "#e09f1f")])
    )
    body = '<g filter="url(#sh)"><circle cx="256" cy="190" r="160" fill="url(#t)" stroke="#06201f" stroke-width="8"/></g>'
    bird = (
        '<path d="M100 58 Q112 60 116 74 L128 82 L116 86 L118 96 L196 34 Q182 104 124 122 L132 176 L110 158 L100 186 '
        'L90 158 L68 176 L76 122 Q18 104 4 34 L82 96 Q80 66 100 58 Z" fill="url(#gd)" stroke="#06201f" stroke-width="6" stroke-linejoin="round"/>'
        '<circle cx="104" cy="72" r="4" fill="#06201f"/>'
    )
    body += fit(bird, 116, 64, 280, 240)
    w = text(
        "FALCONER",
        "Barlow Condensed",
        100,
        weight=800,
        style="italic",
        fill="#fff",
        stroke="#06201f",
        sw=12,
        ls=6,
    )
    body += f'<g filter="url(#sh)">{fit(w, 36, 366, 440, 90)}</g>'
    return svg(body, d)


@net("The Commons", BROADCAST, "public television", "documentary", "kids")
def the_commons():
    d = SH + lin("g", [(0, "#2a9d8f"), (1, "#1d6f66")])
    body = '<g filter="url(#sh)"><rect x="106" y="30" width="300" height="300" rx="150" fill="url(#g)" stroke="#0b2b28" stroke-width="8"/></g>'
    body += '<path d="M256 90 Q300 150 284 200 Q276 224 256 226 Q236 224 228 200 Q212 150 256 90 Z" fill="#ffd166" stroke="#0b2b28" stroke-width="6"/>'
    body += '<path d="M256 150 Q274 180 266 204 Q262 214 256 214 Q250 214 246 204 Q238 180 256 150 Z" fill="#fff4d6"/>'
    body += '<path d="M196 236 L316 236 L300 290 L212 290 Z" fill="#f4efe3" stroke="#0b2b28" stroke-width="6" stroke-linejoin="round"/>'
    body += f'<g filter="url(#sh)">{fit(text("THE COMMONS", "Libre Baskerville", 100, weight=700, fill="#fff", stroke="#0b2b28", sw=12, ls=6), 40, 354, 432, 76)}</g>'
    body += fit(
        text(
            "PUBLIC TELEVISION",
            "Montserrat",
            40,
            weight=700,
            fill="#7fe3d6",
            stroke="#0b2b28",
            sw=6,
            ls=8,
        ),
        130,
        440,
        252,
        26,
    )
    return svg(body, d)


@net("Crosswind", BROADCAST, "young adult", "drama", "broadcast network")
def crosswind():
    d = (
        SH
        + lin("a", [(0, "#00f5d4"), (1, "#00bbf9")], x2=1, y2=0)
        + lin("b", [(0, "#f15bb5"), (1, "#9b5de5")], x2=1, y2=0)
    )
    body = '<g filter="url(#sh)"><circle cx="256" cy="178" r="150" fill="#16122e" stroke="#07061a" stroke-width="8"/></g>'
    for grad, y, flip in (("a", 150, 1), ("b", 206, -1)):
        body += (
            f'<path d="M126 {y + flip * 40} C200 {y - flip * 60} 290 {y + flip * 70} 390 {y - flip * 30}" fill="none" stroke="#07061a" stroke-width="34" stroke-linecap="round"/>'
            f'<path d="M126 {y + flip * 40} C200 {y - flip * 60} 290 {y + flip * 70} 390 {y - flip * 30}" fill="none" stroke="url(#{grad})" stroke-width="22" stroke-linecap="round"/>'
        )
    body += f'<g filter="url(#sh)">{fit(text("crosswind", "Outfit", 100, weight=800, fill="#fff", stroke="#07061a", sw=12), 40, 344, 432, 110)}</g>'
    return svg(body, d)


@net("Birchwood", BROADCAST, "family", "broadcast network")
def birchwood():
    d = SH + lin("g", [(0, "#8fd694"), (1, "#3a8f5a")])
    body = '<g filter="url(#sh)"><rect x="76" y="30" width="360" height="300" rx="40" fill="url(#g)" stroke="#123620" stroke-width="8"/></g>'
    body += '<clipPath id="bw"><rect x="80" y="34" width="352" height="292" rx="36"/></clipPath><g clip-path="url(#bw)">'
    rng = random.Random(5)
    for cx, cy, r in (
        (150, 90, 56),
        (230, 70, 64),
        (310, 96, 60),
        (372, 84, 44),
        (190, 120, 40),
        (282, 124, 44),
    ):
        body += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#b7e4a0" opacity=".9"/>'
    for x, top, w, lean in ((160, 110, 26, -3), (236, 88, 32, 2), (316, 118, 24, 4)):
        body += f'<g transform="rotate({lean} {x} 320)"><rect x="{x - w / 2}" y="{top}" width="{w}" height="{322 - top}" rx="6" fill="#f4f1ea" stroke="#123620" stroke-width="5"/>'
        y = top + 18
        while y < 300:
            ln = rng.uniform(0.3, 0.75) * w
            side = rng.choice((-1, 1))
            x0 = x - w / 2 if side < 0 else x + w / 2 - ln
            body += f'<rect x="{x0:.1f}" y="{y:.0f}" width="{ln:.1f}" height="{rng.uniform(4, 8):.1f}" rx="3" fill="#2a2a2a"/>'
            y += rng.uniform(18, 34)
        body += "</g>"
    body += "</g>"
    body += '<rect x="80" y="296" width="352" height="30" fill="#2d6a4f" opacity=".6"/>'
    body += f'<g filter="url(#sh)">{fit(text("BIRCHWOOD", "Fraunces", 100, weight=800, fill="#fff", stroke="#123620", sw=12, ls=4), 40, 356, 432, 80)}</g>'
    body += fit(
        text(
            "FAMILY TELEVISION",
            "Montserrat",
            40,
            weight=700,
            fill="#d8f3dc",
            stroke="#123620",
            sw=6,
            ls=8,
        ),
        130,
        444,
        252,
        24,
    )
    return svg(body, d)


@net("Hometown Nine", BROADCAST, "local station", "syndication")
def hometown_nine():
    d = SH + lin("b", [(0, "#ff9f1c"), (1, "#e2550d")])
    t_defs, t_body = arc_text(
        "HOMETOWN", "Oswald", 256, 270, 176, 56, weight=700, fill="#fff", ls=12, pid="ht"
    )
    d += t_defs
    body = '<g filter="url(#sh)"><circle cx="256" cy="270" r="230" fill="#102a43" stroke="#061523" stroke-width="8"/></g>'
    body += '<circle cx="256" cy="270" r="140" fill="url(#b)" stroke="#fff" stroke-width="6"/>'
    body += '<polygon points="256,100 356,166 156,166" fill="#fff" stroke="#061523" stroke-width="6" stroke-linejoin="round"/>'
    body += t_body
    body += fit(
        text("9", "Archivo Black", 100, fill="#fff", stroke="#061523", sw=10), 196, 180, 120, 200
    )
    body += fit(
        text("YOUR STATION", "Oswald", 40, weight=700, fill="#ffd166", ls=10), 176, 440, 160, 26
    )
    return svg(body, d)


@net("Vivaluz", BROADCAST, "spanish language", "broadcast network")
def vivaluz():
    d = SH
    body = f'<g filter="url(#sh)">{fit(_butterfly("#ff006e", "#ffbe0b", "#2b0a3d"), 106, 20, 300, 290)}</g>'
    body += f'<g filter="url(#sh)">{fit(text("vivaluz", "Sora", 100, weight=800, fill="#fff", stroke="#2b0a3d", sw=12), 60, 330, 392, 106)}</g>'
    return svg(body, d)


@net("Solstice", BROADCAST, "broadcast network", "general entertainment")
def solstice():
    d = SH + rad("s", [(0, "#ffe066"), (1, "#ff8c00")], r=0.6)
    body = '<g filter="url(#sh)">'
    for k in range(16):
        a = math.radians(k * 22.5)
        body += f'<polygon points="{256 + 110 * math.cos(a - 0.12):.0f},{176 + 110 * math.sin(a - 0.12):.0f} {256 + 168 * math.cos(a):.0f},{176 + 168 * math.sin(a):.0f} {256 + 110 * math.cos(a + 0.12):.0f},{176 + 110 * math.sin(a + 0.12):.0f}" fill="#ff8c00" stroke="#4a1a00" stroke-width="5" stroke-linejoin="round"/>'
    body += (
        '<circle cx="256" cy="176" r="106" fill="url(#s)" stroke="#4a1a00" stroke-width="7"/></g>'
    )
    body += f'<g filter="url(#sh)">{fit(text("SOLSTICE", "Montserrat", 100, weight=900, fill="#fff", stroke="#4a1a00", sw=12, ls=10), 40, 364, 432, 86)}</g>'
    return svg(body, d)


# ======================================================================= premium movie channels and their feeds


@net("Premiere Row", MOVIES, "premium movies", "movies")
def premiere_row():
    d = (
        SH
        + lin("g", [(0, "#fff0c4"), (0.5, "#e2b85a"), (1, "#9c7424")])
        + rad("sp", [(0, "#fff4c9"), (1, "#5c0f1c")], cy=0.2, r=0.8)
    )
    body = _panel(36, 36, 440, 440, "url(#sp)", rx=26, edge="#2a0710", sw=8)
    for row, (y, n) in enumerate(((330, 6), (392, 7))):
        for i in range(n):
            x = 256 + (i - (n - 1) / 2) * 62
            body += f'<rect x="{x - 24}" y="{y - 30}" width="48" height="52" rx="14" fill="#9e1b32" stroke="#2a0710" stroke-width="5"/>'
    body += '<rect x="36" y="420" width="440" height="56" fill="#2a0710" opacity=".0"/>'
    body += f'<polygon points="{star(256, 96, 34, 14)}" fill="url(#g)"/>'
    body += f'<g filter="url(#sh)">{fit(text("PREMIERE", "DM Serif Display", 100, fill="url(#g)", stroke="#2a0710", sw=8, ls=6), 70, 140, 372, 90)}'
    body += (
        fit(
            text("ROW", "DM Serif Display", 100, fill="#fff", stroke="#2a0710", sw=8, ls=30),
            170,
            232,
            172,
            56,
        )
        + "</g>"
    )
    return svg(body, d)


@net("Tentpole", MOVIES, "premium movies", "blockbusters")
def tentpole():
    d = (
        SH
        + lin("gold", [(0, "#fff3b0"), (0.5, "#ffc300"), (1, "#c77800")])
        + rad("bg", [(0, "#9d174d"), (1, "#3b0a1f")], r=0.7)
    )
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="url(#bg)" stroke="#1f0410" stroke-width="8"/></g>'
    for k in range(12):
        a = math.radians(k * 30 + 15)
        body += f'<polygon points="256,256 {256 + 240 * math.cos(a - 0.09):.0f},{256 + 240 * math.sin(a - 0.09):.0f} {256 + 240 * math.cos(a + 0.09):.0f},{256 + 240 * math.sin(a + 0.09):.0f}" fill="#fff" opacity=".07"/>'
    w = text("TENTPOLE", "Bowlby One", 100, fill="url(#gold)", stroke="#3a2200", sw=6)
    body += (
        f'<g filter="url(#sh)">{fit(extrude(w, 0, 16, 16, "#3a2200") + w, 40, 186, 432, 120)}</g>'
    )
    body += "".join(
        f'<polygon points="{star(x, y, r, r * 0.42)}" fill="url(#gold)"/>'
        for x, y, r in ((176, 136, 20), (256, 118, 28), (336, 136, 20))
    )
    body += fit(
        text("BLOCKBUSTER MOVIES", "Montserrat", 40, weight=800, fill="#fff", ls=6),
        130,
        348,
        252,
        26,
    )
    return svg(body, d)


@net("Second Showing", MOVIES, "premium movies", "classic movies")
def second_showing():
    d = SH + lin("cr", [(0, "#fdf0d5"), (1, "#f2dcae")])
    body = '<g filter="url(#sh)"><rect x="36" y="56" width="440" height="400" rx="20" fill="url(#cr)" stroke="#1d1a2b" stroke-width="8"/></g>'
    body += '<rect x="56" y="76" width="400" height="360" rx="10" fill="none" stroke="#c1121f" stroke-width="4"/>'
    body += '<g filter="url(#sh)"><circle cx="256" cy="186" r="92" fill="#c1121f" stroke="#1d1a2b" stroke-width="7"/></g>'
    body += fit(text("2", "Archivo Black", 100, fill="#fdf0d5"), 216, 120, 60, 130)
    body += fit(text("nd", "Archivo Black", 100, fill="#fdf0d5"), 280, 132, 34, 34)
    body += fit(
        text("SECOND SHOWING", "Oswald", 100, weight=700, fill="#1d1a2b", ls=4), 76, 300, 360, 64
    )
    body += fit(
        text("MORE MOVIES · ALL NIGHT", "Oswald", 40, weight=600, fill="#c1121f", ls=6),
        126,
        382,
        260,
        28,
    )
    return svg(body, d)


@net("Footlight Cinema", MOVIES, "premium movies", "movies")
def footlight_cinema():
    d = SH + glow("gl", "#ffd98a", blur=10, strength=2) + lin("g", [(0, "#fff0c4"), (1, "#c9a24a")])
    body = _panel(36, 56, 440, 400, "#0e0f16", rx=24)
    body += '<rect x="36" y="370" width="440" height="86" rx="0" fill="#2a1a10"/>'
    for i in range(8):
        x = 70 + i * 53
        body += f'<g filter="url(#gl)"><path d="M{x - 20} 372 A20 20 0 0 1 {x + 20} 372 Z" fill="#ffe8a8"/></g>'
        body += f'<polygon points="{x - 18},372 {x + 18},372 {x + 60},120 {x - 60},120" fill="#ffe8a8" opacity=".05"/>'
    body += fit(text("FOOTLIGHT", "Federo", 100, fill="url(#g)", ls=6), 70, 150, 372, 100)
    body += fit(text("CINEMA", "Federo", 100, fill="#fff", ls=30), 150, 270, 212, 50)
    return svg(body, d)


@net("Gold Seal", MOVIES, "premium movies", "movies")
def gold_seal():
    d = (
        SH
        + lin("gd", [(0, "#fff3b0"), (0.5, "#f2c14e"), (1, "#a8740f")])
        + rad("bg", [(0, "#2b2b2b"), (1, "#070707")], r=0.7)
    )
    body = _panel(36, 36, 440, 440, "url(#bg)", rx=28, edge="#000", sw=6)
    scallop = " ".join(
        f"{256 + (150 if k % 2 == 0 else 136) * math.cos(math.radians(k * 7.5)):.1f},{206 + (150 if k % 2 == 0 else 136) * math.sin(math.radians(k * 7.5)):.1f}"
        for k in range(48)
    )
    body += f'<g filter="url(#sh)"><polygon points="{scallop}" fill="url(#gd)" stroke="#5a3a00" stroke-width="5" stroke-linejoin="round"/></g>'
    body += '<circle cx="256" cy="206" r="112" fill="none" stroke="#7a5200" stroke-width="3"/><circle cx="256" cy="206" r="102" fill="none" stroke="#fff3b0" stroke-width="2" opacity=".7"/>'
    body += f'<polygon points="{star(256, 150, 26, 11)}" fill="#7a5200"/>'
    body += fit(text("GOLD", "Cinzel", 100, weight=900, fill="#5a3a00", ls=8), 176, 180, 160, 50)
    body += fit(text("SEAL", "Cinzel", 100, weight=900, fill="#5a3a00", ls=8), 186, 236, 140, 44)
    body += fit(
        text("PREMIUM MOVIES", "Montserrat", 40, weight=800, fill="#f2c14e", ls=10),
        120,
        392,
        272,
        30,
    )
    return svg(body, d)


@net("Widescreen", MOVIES, "premium movies", "movies")
def widescreen():
    d = SH + lin(
        "sc", [(0, "#ffb347"), (0.55, "#ff5e62"), (1, "#3a1c71")], user=True, y1=130, y2=380
    )
    body = _panel(20, 100, 472, 312, "#050507", rx=18)
    body += '<clipPath id="ws"><rect x="36" y="130" width="440" height="252"/></clipPath><g clip-path="url(#ws)">'
    body += '<rect x="36" y="130" width="440" height="252" fill="url(#sc)"/><circle cx="346" cy="318" r="56" fill="#fff1c9"/>'
    body += '<path d="M36 382 L130 300 L200 340 L290 276 L380 350 L476 306 L476 382 Z" fill="#1d0f3a"/></g>'
    body += '<rect x="36" y="130" width="440" height="252" fill="none" stroke="#fff" stroke-width="3" opacity=".8"/>'
    body += f'<g filter="url(#sh)">{fit(text("WIDESCREEN", "Syncopate", 100, weight=700, fill="#fff", stroke="#1d0f3a", sw=10), 52, 190, 408, 72)}</g>'
    body += fit(
        text(
            "MOVIES AS THEY WERE MEANT TO BE SEEN",
            "Montserrat",
            40,
            weight=700,
            fill="#fff",
            stroke="#1d0f3a",
            sw=6,
            ls=3,
        ),
        76,
        276,
        360,
        22,
    )
    return svg(body, d)


@net("Movie House Nine", MOVIES, "premium movies", "movies")
def movie_house_nine():
    d = SH + lin("r", [(0, "#e63946"), (1, "#9d0208")])
    house = "M256 30 L470 190 L436 190 L436 470 L76 470 L76 190 L42 190 Z"
    body = f'<g filter="url(#sh)"><path d="{house}" fill="url(#r)" stroke="#2b0406" stroke-width="8" stroke-linejoin="round"/></g>'
    body += '<rect x="106" y="210" width="300" height="140" rx="10" fill="#fdf0d5" stroke="#2b0406" stroke-width="6"/>'
    for x in range(118, 400, 22):
        body += f'<circle cx="{x}" cy="198" r="5" fill="#fff3b0"/><circle cx="{x}" cy="362" r="5" fill="#fff3b0"/>'
    body += '<g filter="url(#sh)"><circle cx="256" cy="126" r="58" fill="#fdf0d5" stroke="#2b0406" stroke-width="6"/></g>'
    body += fit(text("9", "Archivo Black", 100, fill="#9d0208"), 226, 84, 60, 86)
    body += fit(
        text("MOVIE HOUSE", "Oswald", 100, weight=700, fill="#2b0406", ls=4), 126, 236, 260, 90
    )
    body += fit(
        text("NONSTOP MOVIES", "Oswald", 40, weight=700, fill="#fdf0d5", ls=8), 136, 392, 240, 36
    )
    return svg(body, d)


@net("Matinee House", MOVIES, "movies", "afternoon movies")
def matinee_house():
    d = SH + lin("sky", [(0, "#ffe5b4"), (1, "#ffb4a2")])
    body = '<g filter="url(#sh)"><rect x="40" y="60" width="432" height="392" rx="196" fill="url(#sky)" stroke="#4a2c2a" stroke-width="8"/></g>'
    body += centred(S.sun(P(b="#ffb703", k="#4a2c2a")), 256, 150, 150)
    body += '<rect x="40" y="220" width="432" height="10" fill="#4a2c2a" opacity=".0"/>'
    body += fit(
        text("Matinee", "DM Serif Display", 100, style="italic", fill="#4a2c2a"), 110, 222, 292, 100
    )
    body += fit(
        text("HOUSE", "Montserrat", 100, weight=800, fill="#e5383b", ls=24), 170, 330, 172, 40
    )
    body += fit(
        text("AFTERNOON MOVIES", "Montserrat", 40, weight=700, fill="#4a2c2a", ls=6),
        166,
        392,
        180,
        20,
    )
    return svg(body, d)


@net("Grand Lobby", MOVIES, "premium movies", "classic movies")
def grand_lobby():
    d = (
        SH
        + lin("mar", [(0, "#1b4d3e"), (1, "#0b2a22")])
        + lin("g", [(0, "#fff0c4"), (0.5, "#e2b85a"), (1, "#9c7424")])
    )
    arch = "M96 470 L96 210 Q96 50 256 50 Q416 50 416 210 L416 470 Z"
    body = f'<g filter="url(#sh)"><path d="{arch}" fill="url(#mar)" stroke="url(#g)" stroke-width="10"/></g>'
    body += '<path d="M136 470 L136 220 Q136 96 256 96 Q376 96 376 220 L376 470" fill="none" stroke="url(#g)" stroke-width="3"/>'
    for k in range(9):
        a = math.radians(-180 + k * 22.5)
        body += f'<line x1="256" y1="220" x2="{256 + 116 * math.cos(a):.0f}" y2="{220 + 116 * math.sin(a):.0f}" stroke="url(#g)" stroke-width="3" opacity=".8"/>'
    body += '<circle cx="256" cy="220" r="26" fill="url(#g)"/>'
    for row in range(4):
        for col in range(6):
            if (row + col) % 2 == 0:
                x0, _x1 = 136 + col * 40, 136 + (col + 1) * 40
                y = 390 + row * 20
                body += (
                    f'<rect x="{x0}" y="{y}" width="40" height="20" fill="#f4efe3" opacity=".25"/>'
                )
    body += fit(text("GRAND", "Cinzel", 100, weight=700, fill="url(#g)", ls=14), 150, 262, 212, 50)
    body += fit(text("LOBBY", "Cinzel", 100, weight=700, fill="#fff", ls=14), 150, 322, 212, 50)
    return svg(body, d)


@net("Concession Stand", MOVIES, "movies", "family movies")
def concession_stand():
    d = SH
    body = '<g filter="url(#sh)"><rect x="40" y="150" width="432" height="300" rx="16" fill="#fdf6e3" stroke="#1d1a2b" stroke-width="8"/></g>'
    aw = ""
    for i in range(8):
        x = 30 + i * 57
        aw += f'<path d="M{x} 90 L{x + 57} 90 L{x + 57} 170 Q{x + 28.5} 200 {x} 170 Z" fill="{"#e63946" if i % 2 == 0 else "#fff"}" stroke="#1d1a2b" stroke-width="5"/>'
    body += f'<g filter="url(#sh)">{aw}</g>'
    body += '<rect x="30" y="70" width="456" height="26" rx="8" fill="#1d1a2b"/>'
    body += fit(S.popcorn(P(a="#e63946", l="#fff", k="#1d1a2b")), 330, 250, 120, 150)
    body += fit(
        text("CONCESSION", "Bowlby One", 100, fill="#e63946", stroke="#1d1a2b", sw=6),
        64,
        220,
        260,
        70,
    )
    body += fit(text("STAND", "Bowlby One", 100, fill="#1d1a2b"), 64, 300, 260, 70)
    body += fit(
        text("MOVIES & SNACKS", "Oswald", 40, weight=700, fill="#1d1a2b", ls=6), 70, 392, 240, 30
    )
    return svg(body, d)


# ======================================================================= more movie channels


@net("Arthouse Row", MOVIES, "arthouse", "independent film", "movies")
def arthouse_row():
    d = SH
    body = _panel(40, 40, 432, 432, "#f4efe3", rx=6, edge="#141414", sw=8)
    body += '<circle cx="190" cy="176" r="96" fill="#e63946"/>'
    body += '<polygon points="252,264 400,264 326,110" fill="#1d4ed8"/>'
    body += '<rect x="96" y="226" width="110" height="110" fill="#ffd23f" opacity=".92"/>'
    body += '<line x1="60" y1="344" x2="452" y2="344" stroke="#141414" stroke-width="6"/>'
    body += fit(
        text("arthouse row", "Space Grotesk", 100, weight=700, fill="#141414"), 70, 362, 372, 64
    )
    body += fit(
        text("INDEPENDENT & WORLD CINEMA", "Space Grotesk", 40, weight=500, fill="#141414", ls=3),
        70,
        436,
        300,
        18,
    )
    return svg(body, d)


@net("Double Bill", MOVIES, "movies", "double features")
def double_bill():
    d = SH
    body = '<g filter="url(#sh)"><rect x="30" y="60" width="452" height="392" rx="24" fill="#b3121f" stroke="#2a0508" stroke-width="8"/></g>'
    body += '<rect x="48" y="78" width="416" height="356" rx="14" fill="none" stroke="#ffd98a" stroke-width="3"/>'
    body += centred(S.reel(P(a="#ffd98a", l="#2a0508", k="#2a0508")), 196, 176, 170) + centred(
        S.reel(P(a="#fff4e0", l="#2a0508", k="#2a0508")), 316, 176, 170
    )
    body += fit(
        text("DOUBLE BILL", "Oswald", 100, weight=700, fill="#fff4e0", ls=6), 70, 290, 372, 80
    )
    body += fit(
        text("TWO MOVIES · ONE NIGHT", "Oswald", 40, weight=600, fill="#ffd98a", ls=6),
        110,
        386,
        292,
        28,
    )
    return svg(body, d)


@net("Maple Lane", MOVIES, "family movies", "movies")
def maple_lane():
    d = SH + lin("sky", [(0, "#ffe8c2"), (1, "#ffc78a")])
    leaf = (
        "M100 8 L112 50 L150 34 L138 74 L180 80 L148 108 L170 140 L124 132 L110 176 L100 176 L90 176 L76 132 L30 140 L52 108 L20 80 "
        "L62 74 L50 34 L88 50 Z"
    )
    body = '<g filter="url(#sh)"><rect x="30" y="30" width="452" height="452" rx="40" fill="url(#sky)" stroke="#5a2a12" stroke-width="8"/></g>'
    for x, y, sz, c, r in (
        (150, 130, 140, "#d9480f", -14),
        (300, 110, 170, "#e8590c", 10),
        (390, 190, 90, "#f08c00", 24),
    ):
        body += f'<g transform="translate({x - sz / 2} {y - sz / 2}) scale({sz / 200}) rotate({r} 100 100)"><path d="{leaf}" fill="{c}" stroke="#5a2a12" stroke-width="8" stroke-linejoin="round"/><path d="M100 176 L100 60" stroke="#5a2a12" stroke-width="6"/></g>'
    body += f'<g filter="url(#sh)">{fit(text("Maple Lane", "Pacifico", 100, fill="#fff", stroke="#5a2a12", sw=14), 50, 240, 412, 150)}</g>'
    body += fit(
        text("FAMILY MOVIES", "Oswald", 40, weight=700, fill="#5a2a12", ls=8), 156, 404, 200, 28
    )
    return svg(body, d)


@net("Nightstand", MOVIES, "thriller movies", "movies")
def nightstand():
    d = SH + glow("gl", "#ffcf6b", blur=12, strength=2) + lin("n", [(0, "#2a1640"), (1, "#120a20")])
    body = _panel(36, 36, 440, 440, "url(#n)", rx=26)
    body += '<rect x="300" y="70" width="140" height="160" rx="6" fill="#1b2b52" stroke="#070410" stroke-width="6"/><line x1="370" y1="70" x2="370" y2="230" stroke="#070410" stroke-width="5"/><line x1="300" y1="150" x2="440" y2="150" stroke="#070410" stroke-width="5"/>'
    body += '<circle cx="404" cy="112" r="20" fill="#f4efe3"/>'
    body += '<polygon points="120,120 200,120 224,190 96,190" fill="#ffcf6b" filter="url(#gl)"/>'
    body += '<rect x="154" y="190" width="12" height="54" fill="#f4efe3"/><rect x="118" y="244" width="84" height="12" rx="4" fill="#f4efe3"/>'
    body += '<rect x="76" y="256" width="170" height="20" rx="4" fill="#6b3b23"/><rect x="88" y="276" width="146" height="60" fill="#5a3019"/>'
    body += f'<g filter="url(#sh)">{fit(text("NIGHTSTAND", "Playfair Display", 100, weight=900, fill="#fff", stroke="#070410", sw=10, ls=4), 62, 338, 388, 74)}</g>'
    body += fit(
        text("THRILLERS AFTER DARK", "Oswald", 40, weight=600, fill="#ff5d73", ls=6),
        130,
        420,
        252,
        28,
    )
    return svg(body, d)


@net("Sweetheart Cinema", MOVIES, "romance movies", "movies")
def sweetheart_cinema():
    d = SH + lin("h", [(0, "#ff5c8a"), (1, "#c9184a")])
    heart = "M256 440 C136 352 60 288 60 196 C60 130 110 86 172 86 C212 86 240 110 256 140 C272 110 300 86 340 86 C402 86 452 130 452 196 C452 288 376 352 256 440 Z"
    body = f'<g filter="url(#sh)"><path d="{heart}" fill="#1a0a10"/></g>'
    body += f'<path d="{heart}" fill="none" stroke="#fff" stroke-width="14" stroke-dasharray="14 12" transform="translate(256 262) scale(.93) translate(-256 -262)"/>'
    body += f'<path d="{heart}" fill="url(#h)" transform="translate(256 262) scale(.82) translate(-256 -262)"/>'
    body += fit(
        f'<g transform="rotate(-8)">{text("Sweetheart", "Great Vibes", 100, fill="#fff", stroke="#590d22", sw=8)}</g>',
        100,
        170,
        312,
        110,
    )
    body += fit(
        text("CINEMA", "Playfair Display", 100, weight=900, fill="#fff", ls=12), 176, 290, 160, 40
    )
    return svg(body, d)


@net("Home Front", MOVIES, "war movies", "movies")
def home_front():
    d = SH
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="8" fill="#f2e6c9" stroke="#1d2a44" stroke-width="8"/></g>'
    for k in range(16):
        a = math.radians(k * 22.5)
        body += f'<polygon points="256,200 {256 + 300 * math.cos(a - 0.09):.0f},{200 + 300 * math.sin(a - 0.09):.0f} {256 + 300 * math.cos(a + 0.09):.0f},{200 + 300 * math.sin(a + 0.09):.0f}" fill="#c8102e" opacity=".14"/>'
    body = body.replace(
        "</g>", '</g><clipPath id="pc"><rect x="44" y="44" width="424" height="424"/></clipPath>', 1
    )
    body = body.replace('<polygon points="256,200', '<polygon clip-path="url(#pc)" points="256,200')
    body += f'<circle cx="256" cy="176" r="86" fill="#1d2a44"/><polygon points="{star(256, 180, 72, 28)}" fill="#f2e6c9"/>'
    for i, c in enumerate(("#c8102e", "#f2e6c9", "#c8102e")):
        body += f'<rect x="40" y="{286 + i * 14}" width="432" height="14" fill="{c}"/>'
    body += f'<g filter="url(#sh)">{fit(text("HOME FRONT", "Bevan", 100, fill="#1d2a44", stroke="#f2e6c9", sw=8), 60, 340, 392, 80)}</g>'
    body += fit(
        text("WAR MOVIES", "Oswald", 40, weight=700, fill="#c8102e", ls=10), 176, 432, 160, 26
    )
    return svg(body, d)


@net("Dojo Theater", MOVIES, "martial arts movies", "movies")
def dojo_theater():
    d = SH
    body = '<g filter="url(#sh)"><circle cx="256" cy="226" r="200" fill="#d62828" stroke="#1a0506" stroke-width="8"/></g>'
    for k in range(10):
        y = 120 + k * 22
        body += f'<line x1="{80 + (k * 31) % 60}" y1="{y}" x2="{200 + (k * 47) % 120}" y2="{y}" stroke="#1a0506" stroke-width="3" opacity=".25"/>'
    body += fit(
        text("DOJO", "Knewave", 100, fill="#fff", stroke="#1a0506", sw=12), 106, 120, 300, 180
    )
    body += f'<g filter="url(#sh)">{banner(40, 472, 340, 90, "#1a0506", "#fff", 5, cut=22)}</g>'
    body += fit(text("THEATER", "Anton", 100, fill="#fff", ls=14), 110, 356, 292, 58)
    return svg(body, d)


@net("Subtitle", MOVIES, "international film", "movies")
def subtitle():
    d = SH + lin("scn", [(0, "#2b3a67"), (0.6, "#6a4c93"), (1, "#f4a261")])
    body = '<g filter="url(#sh)"><rect x="20" y="90" width="472" height="332" rx="10" fill="#0b0b0f"/></g>'
    body += '<rect x="36" y="130" width="440" height="248" fill="url(#scn)"/>'
    body += '<circle cx="340" cy="250" r="44" fill="#ffd6a5" opacity=".9"/><path d="M36 330 L140 270 L220 310 L320 260 L476 330 L476 378 L36 378 Z" fill="#1b1b2f"/>'
    body += f'<g filter="url(#sh)">{fit(text("SUBTITLE", "Inter", 100, weight=800, fill="#ffe14d", stroke="#000", sw=12, ls=2), 96, 300, 320, 64)}</g>'
    body += fit(
        text("WORLD CINEMA", "Inter", 40, weight=700, fill="#fff", ls=10), 176, 104, 160, 18
    )
    body += fit(
        text("[ MUSIC PLAYING ]", "Inter", 40, weight=600, fill="#fff", ls=2), 186, 388, 140, 22
    )
    return svg(body, d)


@net("Showstopper", MOVIES, "musicals", "broadway")
def showstopper():
    d = lin("g", [(0, "#fff3b0"), (0.6, "#ffc300"), (1, "#c77800")])
    back = f'<polygon points="{star(256, 250, 230, 104)}" fill="url(#g)" stroke="#3a2200" stroke-width="8" stroke-linejoin="round"/>'
    import math as _m

    for k in range(10):
        r = 230 if k % 2 == 0 else 104
        a = _m.radians(-90 + k * 36)
        back += f'<circle cx="{256 + (r - 26) * _m.cos(a):.0f}" cy="{250 + (r - 26) * _m.sin(a):.0f}" r="8" fill="#fff" stroke="#b36b00" stroke-width="2"/>'
    return L.ribbon_badge(
        back,
        "SHOWSTOPPER",
        font="Limelight",
        ink="#fff3d6",
        band="#6a0dad",
        band_dark="#3c096c",
        edge="#1a0530",
        defs=d,
        y=282,
    )


# ======================================================================= over-the-air classics


@net("Toon Attic", OTA, "classic cartoons", "kids")
def toon_attic():
    d = SH
    body = '<g filter="url(#sh)"><polygon points="256,24 486,250 26,250" fill="#7b2cbf" stroke="#1b0b33" stroke-width="8" stroke-linejoin="round"/></g>'
    body += '<polygon points="256,60 440,240 72,240" fill="#9d4edd"/>'
    for y in range(90, 240, 22):
        body += f'<line x1="{256 - (y - 60) * 1.02:.0f}" y1="{y}" x2="{256 + (y - 60) * 1.02:.0f}" y2="{y}" stroke="#1b0b33" stroke-width="2" opacity=".3"/>'
    body += '<circle cx="256" cy="168" r="62" fill="#ffd23f" stroke="#1b0b33" stroke-width="7"/><line x1="194" y1="168" x2="318" y2="168" stroke="#1b0b33" stroke-width="6"/><line x1="256" y1="106" x2="256" y2="230" stroke="#1b0b33" stroke-width="6"/>'
    body += '<ellipse cx="236" cy="150" rx="12" ry="16" fill="#fff" stroke="#1b0b33" stroke-width="4"/><ellipse cx="276" cy="150" rx="12" ry="16" fill="#fff" stroke="#1b0b33" stroke-width="4"/>'
    body += '<circle cx="240" cy="154" r="6" fill="#1b0b33"/><circle cx="280" cy="154" r="6" fill="#1b0b33"/>'
    w = text("TOON ATTIC", "Luckiest Guy", 100, fill="#ffd23f", stroke="#1b0b33", sw=14)
    body += f'<g filter="url(#sh)">{fit(extrude(w, 5, 7, 8, "#1b0b33") + w, 36, 270, 440, 110)}</g>'
    body += fit(
        text("CLASSIC CARTOONS", "Luckiest Guy", 40, fill="#fff", ls=6, stroke="#1b0b33", sw=6),
        136,
        400,
        240,
        34,
    )
    return svg(body, d)


@net("Rooftop TV", OTA, "classic tv", "sitcoms")
def rooftop_tv():
    d = SH + lin("sky", [(0, "#56cfe1"), (1, "#c7f0f6")])
    body = '<g filter="url(#sh)"><rect x="30" y="30" width="452" height="452" rx="34" fill="url(#sky)" stroke="#1d2a44" stroke-width="8"/></g>'
    body += '<clipPath id="rt"><rect x="34" y="34" width="444" height="444" rx="30"/></clipPath><g clip-path="url(#rt)">'
    body += '<polygon points="-40,330 256,196 552,330 552,520 -40,520" fill="#c8553d"/>'
    for i in range(12):
        y = 226 + i * 24
        body += f'<line x1="{256 - (y - 196) * 2.2:.0f}" y1="{y}" x2="{256 + (y - 196) * 2.2:.0f}" y2="{y}" stroke="#7a2a1a" stroke-width="3"/>'
    body += "</g>"
    body += '<line x1="300" y1="210" x2="300" y2="60" stroke="#1d2a44" stroke-width="8"/>'
    for i, w in enumerate((150, 126, 104, 84, 64)):
        y = 70 + i * 24
        body += f'<line x1="{300 - w / 2}" y1="{y}" x2="{300 + w / 2}" y2="{y}" stroke="#1d2a44" stroke-width="6" stroke-linecap="round"/>'
    body += f'<g filter="url(#sh)">{fit(text("ROOFTOP TV", "Righteous", 100, fill="#fff", stroke="#1d2a44", sw=14, ls=2), 56, 296, 400, 90)}</g>'
    body += fit(text("CLASSIC TELEVISION", "Righteous", 40, fill="#fff", ls=6), 110, 410, 292, 30)
    return svg(body, d)


@net("Kitchen Table", OTA, "lifestyle", "classic tv", "cooking")
def kitchen_table():
    d = (
        SH
        + "<pattern id='ck' width='36' height='36' patternUnits='userSpaceOnUse'><rect width='36' height='36' fill='#fff'/><rect width='18' height='36' fill='#4dabf7' opacity='.55'/><rect width='36' height='18' fill='#4dabf7' opacity='.55'/></pattern>"
    )
    body = '<g filter="url(#sh)"><path d="M40 250 L472 250 L500 420 L12 420 Z" fill="url(#ck)" stroke="#1d3557" stroke-width="7" stroke-linejoin="round"/></g>'
    body += centred(S.coffee(P(a="#e63946", b="#adb5bd", l="#fff", k="#1d3557")), 160, 220, 130)
    body += '<g filter="url(#sh)"><ellipse cx="340" cy="268" rx="90" ry="26" fill="#f4a261" stroke="#1d3557" stroke-width="6"/><path d="M250 262 Q340 200 430 262" fill="#f6bd60" stroke="#1d3557" stroke-width="6"/></g>'
    body += fit(
        text("Kitchen Table", "Yellowtail", 100, fill="#1d3557", stroke="#fff", sw=12),
        40,
        40,
        432,
        130,
    )
    body += fit(
        text("COZY CLASSICS", "Oswald", 40, weight=700, fill="#1d3557", ls=8, stroke="#fff", sw=6),
        150,
        432,
        212,
        32,
    )
    return svg(body, d)


@net("Laugh Track", OTA, "classic sitcoms", "comedy")
def laugh_track():
    d = SH + glow("gl", "#ff3d3d", blur=10, strength=2)
    body = '<g filter="url(#sh)"><rect x="24" y="130" width="464" height="220" rx="22" fill="#1b1b1f" stroke="#050505" stroke-width="8"/></g>'
    body += '<rect x="48" y="154" width="416" height="172" rx="10" fill="#3a0a0a"/>'
    body += f'<g filter="url(#gl)">{fit(text("LAUGH TRACK", "Oswald", 100, weight=700, fill="#ff4d4d", ls=6), 70, 176, 372, 128)}</g>'
    body += fit(
        text("LAUGH TRACK", "Oswald", 100, weight=700, fill="#ffd6d6", ls=6), 70, 176, 372, 128
    )
    for x in (130, 382):
        body += f'<rect x="{x - 6}" y="96" width="12" height="36" fill="#050505"/>'
    body += fit(
        text(
            "CLASSIC SITCOMS", "Oswald", 40, weight=700, fill="#fff", stroke="#050505", sw=8, ls=10
        ),
        136,
        376,
        240,
        36,
    )
    return svg(body, d)


@net("Pratfall", OTA, "comedy movies", "comedy")
def pratfall():
    d = SH
    body = '<g filter="url(#sh)"><circle cx="256" cy="226" r="206" fill="#3a86ff" stroke="#10204a" stroke-width="8"/></g>'
    body += fit(S.banana_peel(P(a="#ffd23f", l="#fff3c4", k="#10204a")), 176, 56, 160, 170)
    for x, y, r in ((150, 120, 10), (370, 110, 8), (130, 200, 6)):
        body += f'<polygon points="{star(x, y, r * 2, r)}" fill="#fff"/>'
    w = text("PRATFALL", "Titan One", 100, fill="#ffd23f", stroke="#10204a", sw=14)
    body += f'<g filter="url(#sh)">{fit(tilt(extrude(w, 5, 7, 8, "#10204a") + w, -6), 40, 250, 432, 110)}</g>'
    body += fit(
        text("COMEDY MOVIES", "Titan One", 40, fill="#fff", stroke="#10204a", sw=8, ls=6),
        146,
        380,
        220,
        36,
    )
    return svg(body, d)


@net("Dust Devil", OTA, "westerns", "action")
def dust_devil():
    d = lin("sky", [(0, "#f6d6a8"), (1, "#d98c4a")], user=True, y2=340)
    scene = '<rect width="512" height="512" fill="url(#sky)"/><circle cx="380" cy="120" r="36" fill="#fff3d6"/>'
    scene += '<path d="M40 300 L110 260 L150 270 L170 240 L230 240 L250 270 L472 290 L472 520 L40 520 Z" fill="#a0522d"/>'
    scene += centred(S.twister(P(a="#6b3a1f")), 256, 196, 250)
    scene += '<path d="M40 320 Q256 300 472 320 L472 520 L40 520 Z" fill="#5a2e14"/>'
    return L.emblem(
        scene,
        "DUST DEVIL",
        font="Ewert",
        ink="#fff3d6",
        band="#5a2e14",
        rim="#fff3d6",
        edge="#2a1208",
        defs=d,
        ls=2,
    )


@net("Hot Pursuit", OTA, "action", "cop shows")
def hot_pursuit():
    d = SH + glow("rg", "#ff2d3d", blur=9) + glow("bg", "#2d7dff", blur=9)
    body = _panel(24, 80, 464, 352, "#0e0e14", rx=26)
    for i in range(9):
        y = 120 + i * 32
        body += f'<rect x="{40 + (i * 53) % 120}" y="{y}" width="{160 + (i * 71) % 160}" height="6" rx="3" fill="#fff" opacity=".12"/>'
    body += '<g filter="url(#rg)"><circle cx="150" cy="130" r="22" fill="#ff2d3d"/></g><g filter="url(#bg)"><circle cx="362" cy="130" r="22" fill="#2d7dff"/></g>'
    w = text("HOT PURSUIT", "Racing Sans One", 100, fill="#fff", stroke="#0e0e14", sw=10)
    body += f'<g filter="url(#sh)">{fit(skew(extrude(w, 8, 4, 10, "#ff2d3d") + w, -10), 44, 190, 424, 120)}</g>'
    body += fit(
        text("CHASES · CAPERS · COPS", "Oswald", 40, weight=700, fill="#ffd23f", ls=6),
        110,
        344,
        292,
        32,
    )
    return svg(body, d)


@net("Lightning Round", OTA, "game shows")
def lightning_round():
    d = SH + lin("b", [(0, "#ffe14d"), (1, "#ff9f1c")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="#1d3a8a" stroke="#0a1740" stroke-width="8"/></g>'
    for k in range(24):
        a = math.radians(k * 15)
        body += f'<circle cx="{256 + 214 * math.cos(a):.0f}" cy="{256 + 214 * math.sin(a):.0f}" r="7" fill="#fff3b0"/>'
    body += f'<g filter="url(#sh)">{centred(S.lightning(P(b="url(#b)", k="#0a1740")), 256, 150, 190)}</g>'
    body += f'<g filter="url(#sh)">{fit(text("LIGHTNING", "Bungee", 100, fill="#fff", stroke="#0a1740", sw=10), 70, 244, 372, 76)}'
    body += (
        fit(
            text("ROUND", "Bungee", 100, fill="url(#b)", stroke="#0a1740", sw=10, ls=10),
            130,
            330,
            252,
            72,
        )
        + "</g>"
    )
    return svg(body, d)


@net("Hero Hour", OTA, "cop shows", "westerns", "heroes", "action")
def hero_hour():
    d = lin("gold", [(0, "#fff1b8"), (1, "#c98a12")])
    sym = (
        f'<polygon points="{star(100, 96, 90, 44, 6)}" fill="url(#gold)" stroke="#3a2200" stroke-width="6" stroke-linejoin="round"/>'
        f'<circle cx="100" cy="96" r="40" fill="#c98a12" stroke="#3a2200" stroke-width="5"/>'
        f'<polygon points="{star(100, 98, 26, 11)}" fill="#fff1b8"/>'
    )
    return L.crest(
        sym,
        "HERO HOUR",
        font="Rye",
        ink="#2a1208",
        field="#4f6d7a",
        field2="#1f3a48",
        rim="#e8c07a",
        edge="#10212a",
        scroll="#f3e3c3",
        scroll_dark="#c9b28a",
    ).replace("<defs>", "<defs>" + d, 1)


@net("Leading Lady", OTA, "classic dramas", "female-led")
def leading_lady():
    d = (
        SH
        + lin("g", [(0, "#fff0c4"), (0.5, "#e2b85a"), (1, "#9c7424")])
        + rad("r", [(0, "#b5174a"), (1, "#5c0620")], r=0.7)
    )
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="url(#r)" stroke="url(#g)" stroke-width="8"/></g>'
    body += '<circle cx="256" cy="256" r="212" fill="none" stroke="url(#g)" stroke-width="2"/>'
    body += f'<polygon points="{star(256, 132, 40, 16)}" fill="url(#g)"/>'
    body += fit(
        f'<g transform="rotate(-6)">{text("Leading Lady", "Great Vibes", 100, fill="#fff", stroke="#3a0414", sw=6)}</g>',
        70,
        190,
        372,
        130,
    )
    body += fit(
        text("STARRING HER", "Playfair Display", 40, weight=700, fill="url(#g)", ls=10),
        166,
        344,
        180,
        26,
    )
    return svg(body, d)


@net("Silver Palace", OTA, "classic movies", "movies")
def silver_palace():
    d = SH + lin("sil", [(0, "#ffffff"), (0.5, "#b8c1cc"), (1, "#6c7a89")])
    body = '<g filter="url(#sh)"><rect x="196" y="20" width="120" height="330" rx="14" fill="#b3121f" stroke="#2a0508" stroke-width="7"/></g>'
    for y in range(36, 340, 22):
        body += f'<circle cx="212" cy="{y}" r="5" fill="#fff3b0"/><circle cx="300" cy="{y}" r="5" fill="#fff3b0"/>'
    for i, ch in enumerate("SILVER"):
        body += fit(text(ch, "Limelight", 100, fill="url(#sil)"), 228, 40 + i * 50, 56, 44)
    body += '<g filter="url(#sh)"><path d="M40 360 L472 360 L452 470 L60 470 Z" fill="#1b1b24" stroke="#2a0508" stroke-width="7" stroke-linejoin="round"/></g>'
    body += fit(text("PALACE", "Limelight", 100, fill="url(#sil)", ls=10), 90, 378, 332, 74)
    return svg(body, d)


@net("Insomnia Theater", OTA, "late-night movies", "horror", "cult")
def insomnia_theater():
    d = SH + lin("n", [(0, "#3c1a5b"), (1, "#140a24")])
    body = _panel(36, 36, 440, 440, "url(#n)", rx=30)
    body += centred(S.crescent(P(l="#c3f73a", b="#6a8f1a", k="#0b0614")), 380, 110, 110)
    body += centred(
        S.alarm_clock(P(a="#c3f73a", b="#c3f73a", l="#f4efe3", k="#0b0614")), 196, 156, 190
    )
    body += f'<g filter="url(#sh)">{fit(text("INSOMNIA", "Limelight", 100, fill="#c3f73a", stroke="#0b0614", sw=10, ls=4), 60, 272, 392, 84)}</g>'
    body += fit(text("THEATER", "Limelight", 100, fill="#fff", ls=20), 130, 368, 252, 50)
    return svg(body, d)


@net("Grayscale", OTA, "black and white classics", "classic movies")
def grayscale():
    d = SH
    body = '<g filter="url(#sh)"><rect x="30" y="60" width="452" height="392" rx="18" fill="#0b0b0b"/></g>'
    for i in range(8):
        v = 255 - i * 34
        body += f'<rect x="{50 + i * 51.5:.1f}" y="80" width="51.5" height="220" fill="rgb({v},{v},{v})"/>'
    body += (
        '<rect x="50" y="80" width="412" height="220" fill="none" stroke="#fff" stroke-width="3"/>'
    )
    body += fit(text("GRAYSCALE", "Outfit", 100, weight=800, fill="#fff", ls=8), 64, 322, 384, 70)
    body += fit(
        text("BLACK & WHITE CLASSICS", "Outfit", 40, weight=600, fill="#9a9a9a", ls=6),
        110,
        408,
        292,
        24,
    )
    return svg(body, d)


@net("Front Stoop", OTA, "classic sitcoms", "comedy")
def front_stoop():
    d = SH + lin("br", [(0, "#b5553a"), (1, "#7a321f")])
    body = '<g filter="url(#sh)"><rect x="56" y="30" width="400" height="300" rx="10" fill="url(#br)" stroke="#2a120b" stroke-width="8"/></g>'
    for y in range(50, 320, 20):
        body += f'<line x1="60" y1="{y}" x2="452" y2="{y}" stroke="#2a120b" stroke-width="1.5" opacity=".35"/>'
    body += '<path d="M206 250 L206 110 Q206 70 256 70 Q306 70 306 110 L306 250 Z" fill="#1d3557" stroke="#2a120b" stroke-width="6"/>'
    body += '<circle cx="290" cy="170" r="6" fill="#ffd166"/>'
    for i, w in enumerate((140, 180, 220, 260)):
        body += f'<rect x="{256 - w / 2}" y="{250 + i * 20}" width="{w}" height="20" fill="#a8a29e" stroke="#2a120b" stroke-width="4"/>'
    body += '<path d="M180 250 L120 330 M332 250 L392 330" stroke="#141414" stroke-width="8" stroke-linecap="round"/>'
    body += f'<g filter="url(#sh)">{fit(text("FRONT STOOP", "Carter One", 100, fill="#ffd166", stroke="#2a120b", sw=14), 40, 346, 432, 90)}</g>'
    body += fit(
        text("CLASSIC COMEDY", "Oswald", 40, weight=700, fill="#fff", stroke="#2a120b", sw=6, ls=8),
        150,
        444,
        212,
        28,
    )
    return svg(body, d)


@net("Sidebar", OTA, "court shows", "legal")
def sidebar():
    d = SH + lin("w", [(0, "#7a4a2a"), (1, "#4a2a16")])
    body = '<g filter="url(#sh)"><rect x="36" y="60" width="440" height="392" rx="20" fill="url(#w)" stroke="#1d0f06" stroke-width="8"/></g>'
    body += '<rect x="56" y="80" width="400" height="352" rx="10" fill="none" stroke="#d4a93a" stroke-width="3"/>'
    body += fit(S.gavel(P(a="#8a5a2b", b="#c98a4b", k="#1d0f06")), 176, 96, 160, 150)
    body += fit(
        text("SIDEBAR", "Playfair Display", 100, weight=900, fill="#f4efe3", ls=8), 80, 262, 352, 90
    )
    body += fit(
        text("COURT IS IN SESSION", "Playfair Display", 40, weight=700, fill="#d4a93a", ls=6),
        126,
        370,
        260,
        30,
    )
    return svg(body, d)


@net("Chronicle Hour", OTA, "classic dramas")
def chronicle_hour():
    d = SH + lin("g", [(0, "#f6e3a1"), (0.5, "#c9a24a"), (1, "#8a6a1e")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="200" r="150" fill="url(#g)" stroke="#3a2a0c" stroke-width="8"/></g>'
    body += '<rect x="240" y="26" width="32" height="30" rx="8" fill="url(#g)" stroke="#3a2a0c" stroke-width="6"/><circle cx="256" cy="20" r="14" fill="none" stroke="#3a2a0c" stroke-width="6"/>'
    body += '<circle cx="256" cy="200" r="124" fill="#fbf4e2" stroke="#3a2a0c" stroke-width="4"/>'
    for k in range(12):
        a = math.radians(k * 30)
        body += text(
            ["XII", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI"][k],
            "Cinzel",
            20,
            weight=700,
            fill="#3a2a0c",
            x=256 + 100 * math.sin(a),
            y=207 - 100 * math.cos(a),
        )
    body += '<line x1="256" y1="200" x2="256" y2="118" stroke="#3a2a0c" stroke-width="6" stroke-linecap="round"/><line x1="256" y1="200" x2="310" y2="222" stroke="#3a2a0c" stroke-width="8" stroke-linecap="round"/><circle cx="256" cy="200" r="8" fill="#3a2a0c"/>'
    body += f'<g filter="url(#sh)">{fit(text("CHRONICLE", "Libre Baskerville", 100, weight=700, fill="#fff", stroke="#3a2a0c", sw=12, ls=4), 60, 362, 392, 62)}</g>'
    body += fit(
        text(
            "HOUR",
            "Libre Baskerville",
            100,
            weight=700,
            fill="#c9a24a",
            stroke="#3a2a0c",
            sw=8,
            ls=16,
        ),
        176,
        432,
        160,
        42,
    )
    return svg(body, d)


@net("Cassette", OTA, "80s and 90s", "sitcoms", "nostalgia")
def cassette():
    d = SH + lin("w", [(0, "#ff4fd8"), (1, "#29d0ff")], x2=1, y2=0)
    body = '<g filter="url(#sh)"><rect x="24" y="60" width="464" height="392" rx="30" fill="#1a1036" stroke="#0a0616" stroke-width="8"/></g>'
    for i in range(7):
        y = 330 + i * 18
        body += f'<line x1="24" y1="{y}" x2="488" y2="{y}" stroke="#ff4fd8" stroke-width="2" opacity=".35"/>'
    body += fit(
        S.cassette(P(a="#29d0ff", b="#ff4fd8", l="#fdf6e3", k="#0a0616")), 136, 80, 240, 170
    )
    w = text("CASSETTE", "Racing Sans One", 100, fill="url(#w)", stroke="#0a0616", sw=12)
    body += f'<g filter="url(#sh)">{fit(skew(w, -10), 44, 262, 424, 110)}</g>'
    body += fit(
        text("80s · 90s · REWIND", "Oswald", 40, weight=700, fill="#fff", ls=8), 136, 392, 240, 30
    )
    return svg(body, d)


@net("Malt Shop", OTA, "1950s", "1960s", "classic tv")
def malt_shop():
    d = (
        SH
        + "<pattern id='ck' width='40' height='40' patternUnits='userSpaceOnUse'><rect width='40' height='40' fill='#fff'/><rect width='20' height='20' fill='#141414'/><rect x='20' y='20' width='20' height='20' fill='#141414'/></pattern>"
    )
    body = '<g filter="url(#sh)"><rect x="30" y="30" width="452" height="452" rx="60" fill="#ff8fab" stroke="#3a0f24" stroke-width="8"/></g>'
    body += '<clipPath id="ms"><rect x="34" y="34" width="444" height="444" rx="56"/></clipPath><rect x="30" y="400" width="452" height="90" fill="url(#ck)" clip-path="url(#ms)"/>'
    body += '<rect x="30" y="392" width="452" height="12" fill="#3a0f24"/>'
    body += fit(S.milkshake(P(a="#4ecdc4", c="#e63946", l="#fff", k="#3a0f24")), 190, 50, 132, 160)
    body += f'<g filter="url(#sh)">{fit(tilt(text("Malt Shop", "Yellowtail", 100, fill="#fff", stroke="#3a0f24", sw=14), -6), 50, 210, 412, 140)}</g>'
    body += fit(
        text("SOCK HOP CLASSICS", "Oswald", 40, weight=700, fill="#3a0f24", ls=6), 150, 356, 212, 28
    )
    return svg(body, d)


@net("Welcome Mat", OTA, "lifestyle", "home")
def welcome_mat():
    d = SH + lin("c", [(0, "#d9b77e"), (1, "#b48a4f")])
    rng = random.Random(3)
    body = '<g filter="url(#sh)"><rect x="24" y="110" width="464" height="292" rx="26" fill="url(#c)" stroke="#4a3013" stroke-width="8"/></g>'
    for _ in range(420):
        x, y = rng.uniform(40, 472), rng.uniform(126, 386)
        body += f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x + rng.uniform(-3, 3):.0f}" y2="{y + 6:.0f}" stroke="#7a5a2a" stroke-width="1.5" opacity=".35"/>'
    body += '<rect x="46" y="132" width="420" height="248" rx="14" fill="none" stroke="#4a3013" stroke-width="5"/>'
    body += fit(text("WELCOME", "Alfa Slab One", 100, fill="#3a2410", ls=6), 76, 170, 360, 100)
    body += fit(text("MAT", "Alfa Slab One", 100, fill="#b3121f", ls=24), 190, 284, 132, 64)
    return svg(body, d)


@net("Far Horizon", OTA, "adventure", "exploration")
def far_horizon():
    d = lin("sky", [(0, "#ffd166"), (0.6, "#ef8354"), (1, "#8e3b46")], user=True, y2=260)
    scene = '<rect width="512" height="512" fill="url(#sky)"/><circle cx="256" cy="250" r="54" fill="#fff4d6"/>'
    scene += '<path d="M40 260 L150 220 L220 250 L300 210 L380 240 L472 220 L472 270 L40 270 Z" fill="#6d3b47"/>'
    scene += '<rect x="40" y="266" width="440" height="260" fill="#3d2c3e"/>'
    scene += '<polygon points="236,266 276,266 420,520 92,520" fill="#1f1a24"/>'
    for i in range(6):
        y0 = 272 + i * i * 6 + i * 8
        scene += f'<polygon points="{254 - i * 0.6:.1f},{y0} {258 + i * 0.6:.1f},{y0} {258 + i * 2:.1f},{y0 + 4 + i * 3} {254 - i * 2:.1f},{y0 + 4 + i * 3}" fill="#ffd166"/>'
    return L.emblem(
        scene,
        "FAR HORIZON",
        font="Alfa Slab One",
        ink="#fff4d6",
        band="#8e3b46",
        rim="#fff4d6",
        edge="#2a1420",
        defs=d,
    )


@net("Tough Stuff", OTA, "reality", "work", "trucks")
def tough_stuff():
    return L.plate(
        "TOUGH STUFF",
        "HARD WORK · REAL GRIT",
        font="Black Ops One",
        ink="#1a1a1a",
        metal=("#ffb347", "#e2620d"),
        stripe=("#1a1a1a", "#ffb347"),
    )


@net("Fiddle & Steel", OTA, "country music", "music")
def fiddle_and_steel():
    fiddle = (
        '<g transform="rotate(-30 100 110)">'
        '<path d="M100 60 Q70 60 72 90 Q74 104 64 112 Q48 128 62 156 Q76 184 100 184 Q124 184 138 156 Q152 128 136 112 Q126 104 128 90 Q130 60 100 60 Z" fill="#b5651d" stroke="#2a1208" stroke-width="6"/>'
        '<rect x="94" y="-10" width="12" height="96" fill="#2a1208"/><path d="M92 -16 Q100 -34 108 -16 Z" fill="#2a1208"/>'
        '<path d="M86 118 Q82 132 88 140 M114 118 Q118 132 112 140" fill="none" stroke="#2a1208" stroke-width="4"/>'
        '<rect x="88" y="150" width="24" height="8" rx="2" fill="#2a1208"/></g>'
        '<line x1="20" y1="60" x2="190" y2="160" stroke="#f3e3c3" stroke-width="5" stroke-linecap="round"/>'
    )
    d = lin("sky", [(0, "#f7d9a8"), (1, "#e8a15a")], user=True, y2=340)
    scene = '<rect width="512" height="512" fill="url(#sky)"/>' + centred(fiddle, 256, 196, 260)
    return L.emblem(
        scene,
        "FIDDLE & STEEL",
        font="Rye",
        ink="#fff3d6",
        band="#6b2a14",
        rim="#fff3d6",
        edge="#2a1208",
        defs=d,
    )


@net("Neighborly", OTA, "feel-good", "community", "lifestyle")
def neighborly():
    d = SH + lin("g", [(0, "#95d5b2"), (1, "#52b788")])
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="216" fill="url(#g)" stroke="#1b4332" stroke-width="8"/></g>'
    box = (
        '<rect x="92" y="126" width="16" height="70" fill="#6b4423" stroke="#1b4332" stroke-width="4"/>'
        '<path d="M50 70 Q50 40 90 40 L130 40 Q150 40 150 70 L150 128 L50 128 Z" fill="#e63946" stroke="#1b4332" stroke-width="6"/>'
        '<path d="M90 40 Q60 40 60 70 L60 128" fill="none" stroke="#1b4332" stroke-width="4"/>'
        '<rect x="148" y="44" width="8" height="46" fill="#1b4332"/><rect x="150" y="44" width="30" height="18" fill="#ffd166" stroke="#1b4332" stroke-width="4"/>'
        '<rect x="70" y="84" width="60" height="30" rx="4" fill="#fff" stroke="#1b4332" stroke-width="3" transform="rotate(-8 100 99)"/>'
    )
    body += fit(box, 180, 76, 150, 170)
    body += f'<g filter="url(#sh)">{fit(text("neighborly", "Fraunces", 100, weight=800, fill="#fff", stroke="#1b4332", sw=12), 70, 270, 372, 90)}</g>'
    body += fit(
        text("GOOD NEWS · GOOD PEOPLE", "Oswald", 40, weight=700, fill="#1b4332", ls=4),
        136,
        374,
        240,
        26,
    )
    return svg(body, d)


@net("Backyard Fence", OTA, "talk shows", "gossip", "daytime")
def backyard_fence():
    d = SH
    body = '<g filter="url(#sh)">'
    for i in range(7):
        x = 40 + i * 64
        body += f'<path d="M{x} 460 L{x} 250 L{x + 24} 222 L{x + 48} 250 L{x + 48} 460 Z" fill="#fdfdfd" stroke="#1d3557" stroke-width="6" stroke-linejoin="round"/>'
    body += '<rect x="24" y="300" width="464" height="20" fill="#fdfdfd" stroke="#1d3557" stroke-width="6"/><rect x="24" y="400" width="464" height="20" fill="#fdfdfd" stroke="#1d3557" stroke-width="6"/></g>'
    body += f'<g filter="url(#sh)">{fit(S.speech(P(a="#ff6b6b", b="#ffd166", l="#fff", k="#1d3557")), 176, 24, 160, 150)}</g>'
    body += '<g filter="url(#sh)"><rect x="40" y="316" width="432" height="92" rx="10" fill="#1d3557"/></g>'
    body += fit(text("BACKYARD FENCE", "Carter One", 100, fill="#fff", ls=2), 60, 332, 392, 60)
    body += fit(
        text("DAYTIME TALK", "Carter One", 40, fill="#1d3557", ls=6, stroke="#fff", sw=6),
        180,
        190,
        152,
        30,
    )
    return svg(body, d)


@net("Title Card", OTA, "silent films", "classic movies")
def title_card():
    d = SH
    body = '<g filter="url(#sh)"><rect x="30" y="70" width="452" height="372" rx="6" fill="#0c0c0c"/></g>'
    body += '<rect x="52" y="92" width="408" height="328" fill="none" stroke="#e9e4d8" stroke-width="3"/><rect x="62" y="102" width="388" height="308" fill="none" stroke="#e9e4d8" stroke-width="1.5"/>'
    for x, y, sx, sy in ((62, 102, 1, 1), (450, 102, -1, 1), (62, 410, 1, -1), (450, 410, -1, -1)):
        body += f'<path d="M{x} {y + 34 * sy} Q{x} {y} {x + 34 * sx} {y} M{x + 10 * sx} {y + 24 * sy} Q{x + 10 * sx} {y + 10 * sy} {x + 24 * sx} {y + 10 * sy}" fill="none" stroke="#e9e4d8" stroke-width="2.5"/>'
    body += fit(
        text("Title Card", "IM Fell English", 100, style="italic", fill="#e9e4d8"),
        96,
        170,
        320,
        110,
    )
    body += '<line x1="176" y1="300" x2="336" y2="300" stroke="#e9e4d8" stroke-width="2"/>'
    body += fit(
        text("THE SILENT ERA", "IM Fell English", 40, fill="#e9e4d8", ls=8), 166, 318, 180, 28
    )
    return svg(body, d)


# ======================================================================= more cable networks


@net("Big Tent", CABLE, "general entertainment")
def big_tent():
    p = P(a="#d62828", b="#ffd23f", l="#fff8ec", k="#1d1a2b")
    return L.sym_word(
        S.big_top(p),
        "BIG TENT",
        font="Ultra",
        ink="#fff8ec",
        edge="#1d1a2b",
        sw=14,
        ls=4,
        sub="SOMETHING FOR EVERYONE",
        sub_font="Oswald",
        sub_ink="#ffd23f",
        sym_box=(126, 16, 260, 256),
    )


@net("Live Wire", CABLE, "edgy drama", "drama")
def live_wire():
    d = SH + glow("el", "#7df9ff", blur=6, strength=2)
    body = _panel(24, 70, 464, 372, "#0b0b0e", rx=20)
    bolt = "M60 250 L150 250 L175 200 L205 300 L240 180 L268 280 L292 230 L452 230"
    body += f'<g filter="url(#el)"><path d="{bolt}" fill="none" stroke="#7df9ff" stroke-width="6" stroke-linejoin="round"/></g>'
    body += f'<path d="{bolt}" fill="none" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>'
    body += f'<g filter="url(#sh)">{fit(text("LIVE WIRE", "Anton", 100, fill="#ffe14d", stroke="#0b0b0e", sw=12, ls=6), 60, 110, 392, 110)}</g>'
    body += fit(
        text("DRAMA WITH AN EDGE", "Oswald", 40, weight=700, fill="#fff", ls=8), 116, 340, 280, 40
    )
    return svg(body, d)


@net("Two-Drink Minimum", CABLE, "stand-up comedy", "comedy")
def two_drink_minimum():
    return L.neon(
        "TWO-DRINK",
        "MINIMUM",
        font="Tilt Neon",
        tube="#ffe14d",
        glow_c="#ffb000",
        frame="#ff4fd8",
        sub_tube="#ff4fd8",
        sub_font="Tilt Neon",
    )


@net("Sidesplitter", CABLE, "comedy reality", "comedy")
def sidesplitter():
    d = (
        SH
        + "<clipPath id='tp'><polygon points='0,0 512,0 512,210 0,300'/></clipPath><clipPath id='bt'><polygon points='0,300 512,210 512,512 0,512'/></clipPath>"
    )
    body = '<g filter="url(#sh)"><rect x="30" y="80" width="452" height="352" rx="30" fill="#ffd23f" stroke="#1a1024" stroke-width="8"/></g>'
    body += '<clipPath id="pn"><rect x="34" y="84" width="444" height="344" rx="26"/></clipPath>'
    body += (
        '<g clip-path="url(#pn)"><polygon points="0,300 512,210 512,512 0,512" fill="#ff4f7a"/></g>'
    )
    body += '<line x1="30" y1="300" x2="482" y2="220" stroke="#1a1024" stroke-width="8"/>'
    w1 = text("SIDESPLITTER", "Archivo Black", 100, fill="#1a1024")
    body += fit(tilt(w1, -11), 50, 150, 412, 170)
    body += fit(
        text(
            "COMEDY UNLEASHED", "Oswald", 40, weight=700, fill="#fff", stroke="#1a1024", sw=8, ls=8
        ),
        136,
        360,
        240,
        36,
    )
    return svg(body, d)


@net("Life Story", CABLE, "biography", "documentary")
def life_story():
    p = P(a="#264653", b="#e76f51", l="#fbf6ea", k="#15252b")
    d = SH
    body = f'<g filter="url(#sh)">{fit(S.book(p), 106, 40, 300, 230)}</g>'
    body += f'<g filter="url(#sh)">{fit(text("Life Story", "DM Serif Display", 100, fill="#fbf6ea", stroke="#15252b", sw=12), 50, 280, 412, 120)}</g>'
    body += fit(
        text(
            "BIOGRAPHY · TRUE LIVES",
            "Oswald",
            40,
            weight=700,
            fill="#e9c46a",
            stroke="#15252b",
            sw=6,
            ls=6,
        ),
        130,
        414,
        252,
        28,
    )
    return svg(body, d)


@net("Basecamp", CABLE, "exploration", "adventure", "documentary")
def basecamp():
    d = lin("sky", [(0, "#1d3557"), (1, "#457b9d")], user=True, y2=320)
    scene = '<rect width="512" height="512" fill="url(#sky)"/>'
    for x, y in ((100, 90), (160, 60), (380, 80), (420, 150), (300, 50)):
        scene += f'<circle cx="{x}" cy="{y}" r="3" fill="#fff"/>'
    scene += '<polygon points="40,320 180,130 250,230 330,120 472,320" fill="#a8dadc"/><polygon points="180,130 206,168 192,164 180,182 166,164 154,170" fill="#fff"/><polygon points="330,120 356,158 342,154 330,172 316,154 304,160" fill="#fff"/>'
    scene += '<rect x="40" y="300" width="440" height="220" fill="#1d3557"/>'
    scene += centred(S.tent(P(a="#f77f00", b="#fcbf49", k="#0b1a2e")), 256, 262, 130)
    return L.emblem(
        scene,
        "BASECAMP",
        font="Alfa Slab One",
        ink="#fff",
        band="#f77f00",
        rim="#fff",
        edge="#0b1a2e",
        defs=d,
        ls=8,
    )


@net("Critter Corner", CABLE, "animals", "kids")
def critter_corner():
    d = SH
    body = '<g filter="url(#sh)"><path d="M40 40 L472 40 L472 300 Q472 472 300 472 L40 472 Z" fill="#ffd166" stroke="#3a2a0c" stroke-width="8"/></g>'
    body += fit(S.dog_cat(P(a="#c8773c", b="#9c9c9c", l="#fff3dc", k="#3a2a0c")), 90, 60, 330, 220)
    body += f'<g filter="url(#sh)">{fit(text("Critter Corner", "Fredoka", 100, weight=700, fill="#fff", stroke="#3a2a0c", sw=12), 56, 300, 400, 100)}</g>'
    body += fit(
        text("ANIMALS · PETS · WILD", "Oswald", 40, weight=700, fill="#3a2a0c", ls=6),
        120,
        410,
        250,
        28,
    )
    return svg(body, d)


@net("Wag & Purr", CABLE, "pets", "animals")
def wag_and_purr():
    centre = centred(S.dog_cat(P(a="#e76f51", b="#f4a261", l="#fff", k="#1d1a2b")), 256, 176, 250)
    return L.roundel(
        centre,
        "WAG & PURR",
        font="Carter One",
        ink="#fff",
        disc="#90e0ef",
        rim="#fff",
        edge="#1d1a2b",
        bar="#1d3557",
        bar_y=296,
        ls=2,
    )


@net("Wonder Cabinet", CABLE, "museums", "curiosities", "documentary")
def wonder_cabinet():
    d = SH
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="20" fill="#2b2d42" stroke="#0d0e17" stroke-width="8"/></g>'
    body += fit(
        S.cabinet(P(a="#8d5524", b="#e9c46a", c="#bde0fe", l="#f4efe3", k="#0d0e17")),
        176,
        58,
        160,
        230,
    )
    body += fit(text("WONDER", "Cinzel", 100, weight=900, fill="#e9c46a", ls=8), 80, 306, 352, 66)
    body += fit(text("CABINET", "Cinzel", 100, weight=900, fill="#f4efe3", ls=8), 110, 384, 292, 56)
    return svg(body, d)


@net("Two-Lane", CABLE, "road trips", "americana", "travel")
def two_lane():
    d = SH + lin("sky", [(0, "#ffb86b"), (1, "#ffe3b3")])
    body = '<g filter="url(#sh)"><rect x="30" y="30" width="452" height="452" rx="30" fill="url(#sky)" stroke="#1d2a1d" stroke-width="8"/></g>'
    body += '<clipPath id="tl"><rect x="34" y="34" width="444" height="444" rx="26"/></clipPath><g clip-path="url(#tl)">'
    body += '<rect x="30" y="250" width="452" height="240" fill="#a3b18a"/><polygon points="236,250 276,250 470,490 42,490" fill="#3a3a3a"/>'
    for i in range(6):
        y0 = 256 + i * i * 7 + i * 10
        body += f'<polygon points="{254 - i:.0f},{y0} {258 + i:.0f},{y0} {258 + i * 2.6:.1f},{y0 + 6 + i * 4} {254 - i * 2.6:.1f},{y0 + 6 + i * 4}" fill="#ffd166"/>'
    body += "</g>"
    body += '<g filter="url(#sh)"><rect x="70" y="80" width="372" height="140" rx="16" fill="#1e6f45" stroke="#fff" stroke-width="7"/></g>'
    body += fit(
        text("TWO-LANE", "Barlow Condensed", 100, weight=700, fill="#fff", ls=6), 96, 98, 320, 80
    )
    body += fit(
        text("BACKROADS · DINERS · TOWNS", "Barlow Condensed", 40, weight=600, fill="#fff", ls=6),
        116,
        184,
        280,
        26,
    )
    return svg(body, d)


@net("Hot Plate", CABLE, "cooking competitions", "food")
def hot_plate():
    d = SH + glow("gl", "#ff6a00", blur=8, strength=2)
    body = '<g filter="url(#sh)"><rect x="56" y="40" width="400" height="260" rx="30" fill="#2b2d33" stroke="#0e0f12" stroke-width="8"/></g>'
    spiral = "M256 170"
    for i in range(1, 120):
        t = i * 0.16
        r = 10 + t * 5.5
        spiral += f" L{256 + r * math.cos(t):.1f} {170 + r * 0.55 * math.sin(t):.1f}"
    body += f'<g filter="url(#gl)"><path d="{spiral}" fill="none" stroke="#ff6a00" stroke-width="9" stroke-linecap="round"/></g>'
    body += (
        f'<path d="{spiral}" fill="none" stroke="#ffd166" stroke-width="3" stroke-linecap="round"/>'
    )
    for x in (110, 402):
        body += (
            f'<circle cx="{x}" cy="262" r="16" fill="#c9ccd1" stroke="#0e0f12" stroke-width="4"/>'
        )
    w = text("HOT PLATE", "Bungee", 100, fill="#ff6a00", stroke="#0e0f12", sw=12)
    body += f'<g filter="url(#sh)">{fit(extrude(w, 0, 8, 8, "#0e0f12") + w, 40, 318, 432, 100)}</g>'
    body += fit(
        text(
            "COOK-OFFS & COMPETITIONS",
            "Oswald",
            40,
            weight=700,
            fill="#fff",
            stroke="#0e0f12",
            sw=6,
            ls=4,
        ),
        120,
        430,
        272,
        28,
    )
    return svg(body, d)


@net("Blue Plate", CABLE, "diners", "food", "road food")
def blue_plate():
    d = SH
    body = f'<g filter="url(#sh)">{centred(S.diner_plate(P(c="#1d4ed8", l="#fdfcf8", k="#0b1633")), 256, 220, 400)}</g>'
    body += f'<g filter="url(#sh)">{fit(tilt(text("Blue Plate", "Yellowtail", 100, fill="#1d4ed8", stroke="#fdfcf8", sw=12), -8), 70, 150, 372, 130)}</g>'
    body += f'<g filter="url(#sh)">{banner(96, 416, 400, 64, "#1d4ed8", "#0b1633", 6, cut=16)}</g>'
    body += fit(
        text("DINER CLASSICS", "Oswald", 40, weight=700, fill="#fff", ls=8), 150, 414, 212, 36
    )
    return svg(body, d)


@net("Open Door", CABLE, "family reality", "reality")
def open_door():
    d = SH + lin("lt", [(0, "#fff3c4"), (1, "#ffd16600")])
    body = '<g filter="url(#sh)"><rect x="40" y="30" width="432" height="340" rx="16" fill="#2a9d8f" stroke="#10302c" stroke-width="8"/></g>'
    for y in range(50, 370, 26):
        body += f'<line x1="44" y1="{y}" x2="468" y2="{y}" stroke="#10302c" stroke-width="2" opacity=".25"/>'
    body += '<rect x="176" y="90" width="160" height="280" fill="#ffe8a8" stroke="#10302c" stroke-width="6"/>'
    body += '<polygon points="176,90 250,110 250,390 176,370" fill="#e76f51" stroke="#10302c" stroke-width="6" stroke-linejoin="round"/><circle cx="236" cy="240" r="7" fill="#ffd166"/>'
    body += '<polygon points="176,370 336,370 420,470 92,470" fill="url(#lt)"/>'
    body += f'<g filter="url(#sh)">{fit(text("OPEN DOOR", "Carter One", 100, fill="#fff", stroke="#10302c", sw=14, ls=2), 40, 380, 432, 90)}</g>'
    return svg(body, d)


@net("Champagne Hour", CABLE, "glam reality", "reality")
def champagne_hour():
    d = SH + lin("g", [(0, "#fff0c4"), (0.5, "#e2b85a"), (1, "#9c7424")])
    body = _panel(36, 36, 440, 440, "#0f0d0a", rx=220)
    body += '<circle cx="256" cy="256" r="206" fill="none" stroke="url(#g)" stroke-width="3"/>'
    bottle = (
        '<g transform="rotate(-24 256 170)"><path d="M236 60 L276 60 L276 110 Q304 128 304 170 L304 250 L208 250 L208 170 Q208 128 236 110 Z" fill="#1f4d3a" stroke="url(#g)" stroke-width="5"/>'
        '<rect x="226" y="48" width="60" height="30" rx="6" fill="url(#g)"/><rect x="214" y="170" width="84" height="50" rx="4" fill="url(#g)"/></g>'
    )
    body += bottle
    for x, y, r in ((330, 70, 9), (360, 100, 6), (316, 40, 5), (380, 60, 7), (344, 130, 4)):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="url(#g)" stroke-width="3"/>'
    body += fit(tilt(text("Champagne", "Great Vibes", 100, fill="#fff"), -6), 70, 256, 372, 110)
    body += fit(text("HOUR", "Cinzel", 100, weight=700, fill="url(#g)", ls=24), 176, 374, 160, 44)
    return svg(body, d)


@net("Flashbulb", CABLE, "celebrity", "entertainment news")
def flashbulb():
    d = SH + glow("gl", "#fff6c9", blur=12, strength=2)
    body = _panel(36, 60, 440, 392, "#16121e", rx=24)
    body += f'<g filter="url(#gl)">{centred(S.sparkle(P(), "#fff6c9"), 256, 150, 170)}</g>'
    body += centred(S.sparkle(P(), "#ff4f9a"), 150, 110, 50) + centred(
        S.sparkle(P(), "#ff4f9a"), 370, 190, 40
    )
    body += f'<g filter="url(#sh)">{fit(text("FLASHBULB", "Abril Fatface", 100, fill="#fff", stroke="#16121e", sw=8, ls=4), 60, 250, 392, 90)}</g>'
    body += '<rect x="136" y="352" width="240" height="6" fill="#ff4f9a"/>'
    body += fit(
        text("STARS · SCOOPS · RED CARPETS", "Oswald", 40, weight=600, fill="#ff4f9a", ls=4),
        110,
        372,
        292,
        30,
    )
    return svg(body, d)


@net("Starstruck", CABLE, "celebrity documentaries")
def starstruck():
    d = (
        SH
        + rad("p", [(0, "#7b2cbf"), (1, "#240046")], r=0.7)
        + lin("g", [(0, "#fff3b0"), (1, "#ffb703")])
    )
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="url(#p)" stroke="#12002a" stroke-width="8"/></g>'
    body += f'<polygon points="{star(256, 170, 110, 46)}" fill="url(#g)" stroke="#12002a" stroke-width="6" stroke-linejoin="round"/>'
    for x, y, r in ((130, 120, 40), (390, 110, 30), (380, 230, 22), (120, 230, 24)):
        body += centred(S.sparkle(P(), "#fff3b0"), x, y, r)
    body += f'<g filter="url(#sh)">{fit(text("STARSTRUCK", "Playfair Display", 100, weight=900, style="italic", fill="#fff", stroke="#12002a", sw=10), 60, 300, 392, 80)}</g>'
    body += fit(
        text("CELEBRITY STORIES", "Montserrat", 40, weight=700, fill="#ffb703", ls=6),
        150,
        390,
        212,
        24,
    )
    return svg(body, d)


@net("Sunroom", CABLE, "lifestyle", "women")
def sunroom():
    d = SH
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="60" fill="#fff4d6" stroke="#6b4e16" stroke-width="8"/></g>'
    body += fit(
        S.sunny_window(P(b="#ffd166", c="#9ad1f5", l="#fff", k="#6b4e16")), 166, 60, 180, 200
    )
    body += fit(
        text("sunroom", "DM Serif Display", 100, style="italic", fill="#e07a5f"), 80, 276, 352, 110
    )
    body += fit(
        text("LIFE · HOME · HEART", "Montserrat", 40, weight=700, fill="#6b4e16", ls=8),
        140,
        398,
        232,
        24,
    )
    return svg(body, d)


@net("Kindred", CABLE, "inspiration", "lifestyle")
def kindred():
    d = SH + rad("w", [(0, "#ffd6a5"), (1, "#f4845f")], r=0.7)
    body = '<g filter="url(#sh)"><circle cx="256" cy="186" r="150" fill="url(#w)" stroke="#5a1e1e" stroke-width="8"/></g>'
    body += centred(S.heart(P(a="#e5383b", l="#fff", k="#5a1e1e")), 256, 214, 170)
    body += '<path d="M256 150 Q256 110 246 84" fill="none" stroke="#2d6a4f" stroke-width="8" stroke-linecap="round"/>'
    body += '<path d="M248 104 Q210 96 204 64 Q240 64 248 104 Z" fill="#52b788" stroke="#1b4332" stroke-width="5"/><path d="M252 96 Q286 80 300 50 Q262 50 252 96 Z" fill="#74c69d" stroke="#1b4332" stroke-width="5"/>'
    body += f'<g filter="url(#sh)">{fit(text("Kindred", "Fraunces", 100, weight=700, style="italic", fill="#fff", stroke="#5a1e1e", sw=12), 70, 330, 372, 110)}</g>'
    body += fit(
        text(
            "STORIES THAT LIFT YOU",
            "Montserrat",
            40,
            weight=700,
            fill="#f7b267",
            stroke="#5a1e1e",
            sw=6,
            ls=6,
        ),
        136,
        448,
        240,
        24,
    )
    return svg(body, d)


@net("Heart to Heart", CABLE, "relationships", "reality")
def heart_to_heart():
    d = SH
    body = '<g filter="url(#sh)">'
    body += '<path d="M256 400 C150 330 70 270 70 180 C70 120 116 80 170 80 C210 80 240 104 256 136 L256 400 Z" fill="#ff5d8f" stroke="#3a0b24" stroke-width="8" stroke-linejoin="round"/>'
    body += '<path d="M256 400 C362 330 442 270 442 180 C442 120 396 80 342 80 C302 80 272 104 256 136 L256 400 Z" fill="#ffb3c6" stroke="#3a0b24" stroke-width="8" stroke-linejoin="round" transform="translate(12 -8)"/>'
    body += '<path d="M120 380 L96 440 L170 400" fill="#ff5d8f" stroke="#3a0b24" stroke-width="8" stroke-linejoin="round"/></g>'
    for x, y in ((160, 190), (196, 190), (232, 190)):
        body += f'<circle cx="{x - 20}" cy="{y}" r="10" fill="#fff"/>'
    body += f'<g filter="url(#sh)">{fit(text("HEART TO HEART", "Carter One", 100, fill="#fff", stroke="#3a0b24", sw=12), 40, 228, 432, 80)}</g>'
    return svg(body, d)


@net("Cold Trail", CABLE, "true crime", "cold cases")
def cold_trail():
    d = SH + lin("ice", [(0, "#e8f4fa"), (1, "#b8d8ea")])
    body = _panel(36, 36, 440, 440, "url(#ice)", rx=20, edge="#0d2436", sw=8)
    random.Random(3)
    x, y = 250, 390
    for i in range(6):
        side = -1 if i % 2 else 1
        body += f'<g transform="translate({x + side * 12} {y}) rotate(-36)"><ellipse cx="0" cy="0" rx="9" ry="16" fill="#0d2436" opacity=".7"/><ellipse cx="0" cy="-22" rx="7" ry="6" fill="#0d2436" opacity=".7"/></g>'
        x += 36
        y -= 34
    body += fit(text("COLD", "Oswald", 100, weight=700, fill="#0d2436", ls=10), 70, 90, 220, 90)
    body += fit(text("TRAIL", "Oswald", 100, weight=700, fill="#c1121f", ls=10), 70, 186, 220, 90)
    body += fit(
        text("UNSOLVED · REOPENED · TRUE", "Oswald", 40, weight=600, fill="#0d2436", ls=4),
        70,
        420,
        372,
        26,
    )
    return svg(body, d)


@net("Inkblot", CABLE, "cartoons", "kids")
def inkblot():
    d = SH
    rng = random.Random(12)
    blob = []
    for k in range(24):
        a = math.radians(k * 15)
        r = rng.uniform(120, 160) if k % 2 else rng.uniform(150, 185)
        blob.append((256 + r * math.cos(a), 200 + r * 0.85 * math.sin(a)))
    d_path = (
        "M"
        + " Q".join(
            f"{blob[i][0]:.0f} {blob[i][1]:.0f} {(blob[i][0] + blob[(i + 1) % 24][0]) / 2:.0f} {(blob[i][1] + blob[(i + 1) % 24][1]) / 2:.0f}"
            for i in range(24)
        )
        + " Z"
    )
    body = f'<g filter="url(#sh)"><path d="{d_path}" fill="#141414"/></g>'
    for x, y, r in ((100, 330, 18), (410, 320, 14), (380, 70, 12), (120, 70, 10)):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#141414"/>'
    body += '<ellipse cx="220" cy="170" rx="30" ry="40" fill="#fff"/><ellipse cx="292" cy="170" rx="30" ry="40" fill="#fff"/><circle cx="228" cy="180" r="14" fill="#141414"/><circle cx="300" cy="180" r="14" fill="#141414"/>'
    body += '<path d="M220 240 Q256 270 292 240" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round"/>'
    w = text("INKBLOT", "Londrina Solid", 100, weight=900, fill="#ffd23f", stroke="#141414", sw=14)
    body += f'<g filter="url(#sh)">{fit(tilt(w, -5), 50, 320, 412, 130)}</g>'
    return svg(body, d)


@net("Jumprope", CABLE, "kids")
def jumprope():
    d = SH
    cols = ["#ff595e", "#ffca3a", "#8ac926", "#1982c4", "#6a4c93"]
    body = '<g filter="url(#sh)"><rect x="30" y="100" width="452" height="312" rx="156" fill="#fff" stroke="#23113d" stroke-width="8"/></g>'
    body += '<path d="M80 150 Q256 470 432 150" fill="none" stroke="#23113d" stroke-width="12"/><path d="M80 150 Q256 470 432 150" fill="none" stroke="#ff595e" stroke-width="6" stroke-dasharray="14 8"/>'
    for x in (80, 432):
        body += f'<rect x="{x - 14}" y="80" width="28" height="74" rx="14" fill="#1982c4" stroke="#23113d" stroke-width="6"/>'
    letters, x = "", 0
    for i, ch in enumerate("jumprope"):
        adv, _ = measure(ch, "Fredoka", 700)
        letters += text(
            ch,
            "Fredoka",
            100,
            weight=700,
            fill=cols[i % 5],
            stroke="#23113d",
            sw=12,
            x=x + adv / 2,
            y=-8 if i % 2 else 6,
        )
        x += adv
    body += fit(letters, 90, 180, 332, 120)
    return svg(body, d)


@net("Tadpole", CABLE, "preschool", "kids")
def tadpole():
    d = SH + lin("w", [(0, "#8fe3ff"), (1, "#2fb3e0")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="210" r="180" fill="url(#w)" stroke="#0b3a4a" stroke-width="8"/></g>'
    body += '<ellipse cx="170" cy="300" rx="70" ry="22" fill="#6bbf59" stroke="#0b3a4a" stroke-width="5"/><ellipse cx="350" cy="120" rx="54" ry="18" fill="#6bbf59" stroke="#0b3a4a" stroke-width="5"/>'
    body += '<path d="M300 220 Q340 180 390 210 Q370 230 390 250 Q340 270 300 230 Z" fill="#3d5a3a" stroke="#0b3a4a" stroke-width="5"/>'
    body += '<circle cx="256" cy="220" r="56" fill="#6bbf59" stroke="#0b3a4a" stroke-width="7"/>'
    body += '<circle cx="236" cy="206" r="14" fill="#fff" stroke="#0b3a4a" stroke-width="4"/><circle cx="276" cy="206" r="14" fill="#fff" stroke="#0b3a4a" stroke-width="4"/><circle cx="238" cy="208" r="6" fill="#0b3a4a"/><circle cx="278" cy="208" r="6" fill="#0b3a4a"/>'
    body += '<path d="M236 236 Q256 252 276 236" fill="none" stroke="#0b3a4a" stroke-width="5" stroke-linecap="round"/>'
    body += f'<g filter="url(#sh)">{fit(text("tadpole", "Baloo 2", 100, weight=800, fill="#fff", stroke="#0b3a4a", sw=14), 60, 336, 392, 120)}</g>'
    return svg(body, d)


@net("Rocket Box", CABLE, "kids action", "kids")
def rocket_box():
    d = SH
    body = '<g filter="url(#sh)"><rect x="30" y="30" width="452" height="452" rx="40" fill="#1a1a4e" stroke="#0a0a24" stroke-width="8"/></g>'
    rng = random.Random(4)
    for _ in range(20):
        body += f'<circle cx="{rng.uniform(50, 460):.0f}" cy="{rng.uniform(50, 300):.0f}" r="{rng.uniform(1.5, 3.5):.1f}" fill="#fff"/>'
    body += fit(
        S.box_rocket(P(a="#ff5a5f", b="#ffd166", c="#29a6ff", l="#fff", k="#0a0a24")),
        186,
        50,
        140,
        220,
    )
    w = text("ROCKET BOX", "Bungee", 100, fill="#ffd166", stroke="#0a0a24", sw=12)
    body += f'<g filter="url(#sh)">{fit(extrude(w, 0, 8, 8, "#0a0a24") + w, 50, 300, 412, 90)}</g>'
    body += fit(text("ACTION FOR KIDS", "Bungee", 40, fill="#fff", ls=6), 140, 408, 232, 30)
    return svg(body, d)


@net("Hallway", CABLE, "young adult", "teen drama")
def hallway():
    d = SH + glow("gl", "#ff4fd8", blur=6, strength=2)
    body = _panel(30, 40, 452, 432, "#1b1f3a", rx=24)
    body += '<clipPath id="hw"><rect x="34" y="44" width="444" height="424" rx="20"/></clipPath><g clip-path="url(#hw)">'
    body += '<polygon points="30,40 216,200 216,300 30,470" fill="#3f6fd8"/><polygon points="482,40 296,200 296,300 482,470" fill="#3f6fd8"/>'
    for i in range(6):
        t = i / 6
        xl = 30 + t * 186
        body += f'<line x1="{xl:.0f}" y1="{40 + t * 160:.0f}" x2="{xl:.0f}" y2="{470 - t * 170:.0f}" stroke="#1b2d6b" stroke-width="{6 - i * 0.7:.1f}"/>'
        xr = 482 - t * 186
        body += f'<line x1="{xr:.0f}" y1="{40 + t * 160:.0f}" x2="{xr:.0f}" y2="{470 - t * 170:.0f}" stroke="#1b2d6b" stroke-width="{6 - i * 0.7:.1f}"/>'
    body += '<rect x="216" y="200" width="80" height="100" fill="#fff4d6"/><polygon points="30,470 216,300 296,300 482,470" fill="#c9c3b6"/></g>'
    body += f'<g filter="url(#gl)">{fit(text("HALLWAY", "Permanent Marker", 100, fill="#ff4fd8"), 60, 140, 392, 120)}</g>'
    body += fit(text("HALLWAY", "Permanent Marker", 100, fill="#ffe3fa"), 60, 140, 392, 120)
    return svg(body, d)


@net("Chalkboard", CABLE, "kids", "learning")
def chalkboard():
    d = SH + rough("ch", amount=2.5, freq=1.2, seed=2)
    body = '<g filter="url(#sh)"><rect x="24" y="70" width="464" height="340" rx="10" fill="#b5835a" stroke="#4a2c12" stroke-width="7"/></g>'
    body += '<rect x="46" y="92" width="420" height="296" fill="#2f5d50"/><rect x="60" y="390" width="392" height="14" rx="4" fill="#8a5a2b"/><rect x="120" y="386" width="40" height="8" rx="3" fill="#fff"/>'
    body += f'<g filter="url(#ch)">{fit(text("CHALKBOARD", "Permanent Marker", 100, fill="#f4f1ea"), 70, 130, 372, 100)}'
    body += (
        fit(text("ABC · 123 · LEARN!", "Permanent Marker", 60, fill="#ffd6a5"), 110, 260, 292, 60)
        + "</g>"
    )
    return svg(body, d)


@net("Kite Hill", CABLE, "kids", "family")
def kite_hill():
    d = SH + lin("sky", [(0, "#a0e7ff"), (1, "#e0f7ff")])
    body = '<g filter="url(#sh)"><rect x="30" y="30" width="452" height="452" rx="226" fill="url(#sky)" stroke="#1d3557" stroke-width="8"/></g>'
    body += '<clipPath id="kh"><circle cx="256" cy="256" r="222"/></clipPath><g clip-path="url(#kh)"><ellipse cx="256" cy="470" rx="330" ry="170" fill="#70c05a"/></g>'
    for x, y, sz, a, b in (
        (180, 140, 120, "#ff595e", "#ffca3a"),
        (330, 110, 90, "#1982c4", "#8ac926"),
    ):
        body += centred(S.kite(P(a=a, b=b, c="#6a4c93", k="#1d3557")), x, y, sz)
    body += '<path d="M180 220 Q210 280 250 320 M330 170 Q300 250 262 320" fill="none" stroke="#1d3557" stroke-width="3"/>'
    body += f'<g filter="url(#sh)">{fit(text("KITE HILL", "Fredoka", 100, weight=700, fill="#fff", stroke="#1d3557", sw=14, ls=2), 70, 318, 372, 100)}</g>'
    return svg(body, d)


@net("Scoreline", CABLE, "sports")
def scoreline():
    d = SH + glow("gl", "#ffb000", blur=6, strength=1)
    body = _panel(24, 60, 464, 392, "#101418", rx=18, edge="#050608", sw=8)
    body += '<rect x="56" y="92" width="400" height="140" rx="10" fill="#050608" stroke="#3a3f47" stroke-width="4"/>'
    body += f'<g filter="url(#gl)">{fit(text("4TH", "Teko", 100, weight=600, fill="#ffb000"), 80, 110, 120, 104)}{fit(text("0:04", "Teko", 100, weight=600, fill="#ff3d3d"), 230, 110, 200, 104)}</g>'
    body += fit(text("SCORELINE", "Teko", 100, weight=700, fill="#fff", ls=8), 56, 256, 400, 110)
    body += fit(
        text("SPORTS · LIVE · LEGENDS", "Teko", 60, weight=500, fill="#ffb000", ls=8),
        116,
        380,
        280,
        44,
    )
    return svg(body, d)


@net("Loose Cannon", CABLE, "edgy drama", "comedy", "drama")
def loose_cannon():
    d = SH + glow("sp", "#ffd23f", blur=8, strength=2)
    body = _panel(24, 60, 464, 392, "#0b0b0d", rx=22, edge="#ef233c", sw=5)
    cannon = (
        '<rect x="30" y="70" width="130" height="46" rx="20" fill="#2b2d31" stroke="#0b0b0d" stroke-width="6" transform="rotate(-18 95 93)"/>'
        '<circle cx="70" cy="126" r="30" fill="#6b4423" stroke="#0b0b0d" stroke-width="6"/><circle cx="70" cy="126" r="8" fill="#0b0b0d"/>'
        '<path d="M150 58 Q170 40 186 46" fill="none" stroke="#c9b28a" stroke-width="5" stroke-linecap="round"/>'
    )
    body += fit(cannon, 300, 84, 160, 110)
    body += f'<g filter="url(#sp)">{centred(S.sparkle(P(), "#ffd23f"), 454, 104, 40)}</g>'
    body += fit(text("LOOSE", "Anton", 100, fill="#fff", ls=6), 56, 170, 300, 110)
    body += fit(text("CANNON", "Anton", 100, fill="#ef233c", ls=6), 56, 290, 400, 110)
    return svg(body, d)


@net("Heartstrings", CABLE, "women", "movies", "drama")
def heartstrings():
    d = SH + lin("pl", [(0, "#b5179e"), (1, "#560bad")])
    body = _panel(36, 36, 440, 440, "url(#pl)", rx=220, edge="#2a0540", sw=8)
    body += (
        '<path d="M256 330 C170 270 116 222 116 170 C116 128 150 100 188 100 C220 100 244 122 256 146 C268 122 292 100 324 100 '
        'C362 100 396 128 396 170 C396 222 342 270 256 330 C246 350 250 380 280 392 Q320 404 340 380" fill="none" stroke="#ffd6f0" stroke-width="10" stroke-linecap="round"/>'
    )
    body += f'<g filter="url(#sh)">{fit(text("Heartstrings", "Great Vibes", 100, fill="#fff", stroke="#2a0540", sw=10), 60, 180, 392, 130)}</g>'
    body += fit(
        text("MOVIES · DRAMA · TRUE STORIES", "Montserrat", 40, weight=700, fill="#ffd6f0", ls=3),
        110,
        402,
        292,
        22,
    )
    return svg(body, d)


@net("Two-Minute Drill", CABLE, "football", "sports")
def two_minute_drill():
    d = SH + glow("gl", "#ff3d3d", blur=6, strength=1) + lin("f", [(0, "#2d6a4f"), (1, "#1b4332")])
    body = _panel(24, 40, 464, 432, "url(#f)", rx=24, edge="#081c15", sw=8)
    for x in range(64, 470, 48):
        body += f'<line x1="{x}" y1="40" x2="{x}" y2="472" stroke="#fff" stroke-width="3" opacity=".35"/>'
    body += '<rect x="126" y="70" width="260" height="110" rx="12" fill="#050608" stroke="#fff" stroke-width="4"/>'
    body += f'<g filter="url(#gl)">{fit(text("2:00", "Teko", 100, weight=600, fill="#ff3d3d"), 150, 84, 212, 84)}</g>'
    body += f'<g filter="url(#sh)">{centred(S.ball(P(a="#8b4513", l="#fff", k="#2a1404"), "foot"), 256, 256, 150)}</g>'
    body += f'<g filter="url(#sh)">{fit(text("TWO-MINUTE DRILL", "Teko", 100, weight=700, fill="#fff", stroke="#081c15", sw=10, ls=4), 40, 330, 432, 90)}</g>'
    body += fit(text("FOOTBALL", "Teko", 60, weight=600, fill="#ffd166", ls=14), 186, 424, 140, 34)
    return svg(body, d)


@net("Pennant", CABLE, "classic sports", "sports")
def pennant():
    return L.pennant(
        "PENNANT",
        font="Graduate",
        ink="#fff",
        felt="#1d3557",
        edge="#0b1a2e",
        stripe="#ffd166",
        sym=f'<polygon points="{star(100, 100, 90, 38)}" fill="#ffd166" stroke="#0b1a2e" stroke-width="8"/>',
    )


@net("Tee Box", CABLE, "golf", "sports")
def tee_box():
    d = SH + lin("g", [(0, "#52b788"), (1, "#1b4332")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="url(#g)" stroke="#0b2418" stroke-width="8"/></g>'
    body += fit(S.golf(P(a="#e63946", b="#95d5b2", l="#fff", k="#0b2418")), 156, 50, 200, 190)
    body += f'<g filter="url(#sh)">{fit(text("TEE BOX", "Montserrat", 100, weight=900, fill="#fff", stroke="#0b2418", sw=12, ls=8), 80, 266, 352, 90)}</g>'
    body += fit(
        text("GOLF", "Montserrat", 40, weight=800, fill="#d8f3dc", ls=24), 196, 372, 120, 30
    )
    return svg(body, d)


@net("Match Point", CABLE, "tennis", "sports")
def match_point():
    d = SH + rad("ball", [(0, "#f1ff8a"), (1, "#b5d100")], cx=0.35, cy=0.3, r=0.8)
    body = _panel(24, 60, 464, 392, "#1d3557", rx=26)
    for x in range(40, 480, 20):
        body += f'<line x1="{x}" y1="220" x2="{x}" y2="300" stroke="#fff" stroke-width="2" opacity=".5"/>'
    for y in range(220, 300, 16):
        body += f'<line x1="24" y1="{y}" x2="488" y2="{y}" stroke="#fff" stroke-width="2" opacity=".5"/>'
    body += '<rect x="24" y="214" width="464" height="12" fill="#fff"/>'
    body += '<circle cx="360" cy="150" r="56" fill="url(#ball)" stroke="#0b1a2e" stroke-width="5"/><path d="M314 118 Q360 150 314 186 M406 118 Q360 150 406 186" fill="none" stroke="#fff" stroke-width="6"/>'
    body += f'<g filter="url(#sh)">{fit(skew(text("MATCH POINT", "Montserrat", 100, weight=900, fill="#fff", stroke="#0b1a2e", sw=12), -10), 44, 314, 424, 80)}</g>'
    body += fit(
        text("TENNIS", "Montserrat", 40, weight=800, fill="#d4ff3a", ls=20), 196, 404, 120, 26
    )
    return svg(body, d)


@net("Tackle Box", CABLE, "fishing", "hunting", "outdoors")
def tackle_box():
    d = lin("w", [(0, "#8fd3e8"), (1, "#1e6f8a")], user=True, y2=330)
    scene = '<rect width="512" height="512" fill="url(#w)"/>'
    scene += '<path d="M256 30 L256 110 Q256 140 280 140 Q300 140 300 120" fill="none" stroke="#1d2a1d" stroke-width="6" stroke-linecap="round"/>'
    scene += centred(S.fish(P(a="#f77f00", b="#fcbf49", k="#1d2a1d")), 240, 210, 220)
    for y in (300, 320):
        scene += f'<path d="M40 {y} q30 -12 60 0 t60 0 t60 0 t60 0 t60 0 t60 0 t60 0" fill="none" stroke="#fff" stroke-width="4" opacity=".4"/>'
    return L.emblem(
        scene,
        "TACKLE BOX",
        font="Alfa Slab One",
        ink="#fff",
        band="#2d6a4f",
        rim="#fcbf49",
        edge="#10261c",
        defs=d,
        ls=4,
    )


@net("Isobar", CABLE, "weather")
def isobar():
    centre = centred(
        S.isobars(P(a="#e63946", c="#0f766e", l="#f1faee", k="#083b36")), 256, 160, 250
    )
    return L.roundel(
        centre,
        "ISOBAR",
        font="Space Grotesk",
        weight=700,
        ink="#fff",
        disc="#99e2d8",
        rim="#fff",
        edge="#083b36",
        bar="#0f766e",
        bar_y=296,
        ls=14,
    )


@net("Bulletin", CABLE, "news")
def bulletin():
    d = SH
    body = _panel(24, 80, 464, 352, "#0f1c3a", rx=16)
    body += fit(S.globe(P(a="#2b6cb0", l="#cfe8ff", k="#060f1f")), 60, 110, 120, 120)
    body += fit(text("BULLETIN", "Oswald", 100, weight=700, fill="#fff", ls=4), 200, 120, 260, 100)
    body += '<g filter="url(#sh)"><rect x="24" y="258" width="464" height="72" fill="#c1121f"/></g>'
    body += fit(
        text("BREAKING NEWS · 24 HOURS", "Oswald", 60, weight=700, fill="#fff", ls=4),
        56,
        272,
        400,
        44,
    )
    body += fit(text("LIVE", "Oswald", 40, weight=700, fill="#ffd166", ls=10), 206, 352, 100, 50)
    return svg(body, d)


@net("Wire Desk", CABLE, "news", "headlines")
def wire_desk():
    d = SH
    body = '<g filter="url(#sh)"><rect x="96" y="30" width="320" height="330" fill="#fbf8ee" stroke="#1d2433" stroke-width="6" transform="rotate(-4 256 195)"/></g>'
    body += '<g transform="rotate(-4 256 195)">'
    for y in range(70, 340, 26):
        body += f'<rect x="120" y="{y}" width="{200 + (y * 37) % 70}" height="8" fill="#1d2433" opacity=".35"/>'
    body += "</g>"
    body += '<g filter="url(#sh)"><rect x="24" y="300" width="464" height="112" rx="10" fill="#1d2433"/></g>'
    body += fit(text("WIRE DESK", "Special Elite", 100, fill="#fbf8ee", ls=6), 50, 318, 412, 76)
    body += fit(text("-- URGENT --", "Special Elite", 40, fill="#c1121f", ls=6), 176, 90, 160, 30)
    return svg(body, d)


@net("Bull & Bear", CABLE, "business news", "finance")
def bull_and_bear():
    d = SH
    body = _panel(24, 60, 464, 392, "#0b1633", rx=20)
    for y in range(100, 300, 40):
        body += f'<line x1="44" y1="{y}" x2="468" y2="{y}" stroke="#fff" stroke-width="1.5" opacity=".15"/>'
    body += fit(S.ticker_arrows(P(a="#2ecc71", b="#ff4d4d")), 60, 80, 392, 200)
    body += fit(text("BULL & BEAR", "Oswald", 100, weight=700, fill="#fff", ls=4), 56, 300, 400, 90)
    body += fit(
        text("MARKETS · MONEY · BUSINESS", "Oswald", 40, weight=500, fill="#9fb3c8", ls=4),
        106,
        400,
        300,
        26,
    )
    return svg(body, d)


@net("Rotunda", CABLE, "public affairs", "government")
def rotunda():
    d = SH + lin("n", [(0, "#2b3a67"), (1, "#141d3a")])
    body = '<g filter="url(#sh)"><rect x="40" y="40" width="432" height="432" rx="20" fill="url(#n)" stroke="#0a0f24" stroke-width="8"/></g>'
    body += fit(S.dome(P(l="#f4efe3", k="#0a0f24")), 136, 60, 240, 220)
    body += fit(text("ROTUNDA", "Cinzel", 100, weight=900, fill="#f4efe3", ls=10), 80, 298, 352, 80)
    body += fit(
        text("PUBLIC AFFAIRS", "Cinzel", 40, weight=700, fill="#c9a24a", ls=10), 146, 396, 220, 26
    )
    return svg(body, d)


@net("Bargain Bin", CABLE, "shopping")
def bargain_bin():
    return L.tag(
        "BARGAIN BIN",
        "SHOP FROM HOME",
        font="Bowlby One",
        ink="#1d1a2b",
        paper="#ffd166",
        edge="#1d1a2b",
        sym='<circle cx="100" cy="100" r="90" fill="#e63946" stroke="#1d1a2b" stroke-width="8"/>'
        + text("%", "Bowlby One", 120, fill="#fff", x=100, y=142),
    )


@net("Double Decker", CABLE, "british tv")
def double_decker():
    d = SH
    body = '<g filter="url(#sh)"><circle cx="256" cy="200" r="170" fill="#1d3557" stroke="#0b1424" stroke-width="8"/></g>'
    body += fit(
        S.bus(P(a="#d62828", b="#ffd166", c="#9ad1f5", l="#fff", k="#0b1424")), 186, 56, 140, 290
    )
    body += f'<g filter="url(#sh)">{fit(text("DOUBLE DECKER", "Oswald", 100, weight=700, fill="#fff", stroke="#0b1424", sw=12, ls=4), 30, 360, 452, 76)}</g>'
    body += fit(
        text(
            "BRITISH TELEVISION",
            "Oswald",
            40,
            weight=600,
            fill="#ffd166",
            stroke="#0b1424",
            sw=6,
            ls=8,
        ),
        130,
        444,
        252,
        26,
    )
    return svg(body, d)


@net("Player Two", CABLE, "video games", "gaming")
def player_two():
    d = SH
    body = '<g filter="url(#sh)"><rect x="30" y="60" width="452" height="392" fill="#10002b" stroke="#000" stroke-width="8"/></g>'
    for i in range(0, 452, 16):
        body += f'<rect x="{30 + i}" y="60" width="8" height="8" fill="#7b2ff7"/><rect x="{30 + i}" y="444" width="8" height="8" fill="#7b2ff7"/>'
    body += fit(
        S.gamepad(P(a="#ff4fd8", b="#29d0ff", c="#ffe14d", l="#fff", k="#000")), 146, 90, 220, 150
    )
    body += fit(text("PLAYER 2", "Press Start 2P", 100, fill="#29d0ff"), 60, 270, 392, 60)
    body += fit(text("PRESS START", "Press Start 2P", 40, fill="#ffe14d"), 150, 370, 212, 26)
    return svg(body, d)


@net("Proscenium", CABLE, "performing arts", "arts")
def proscenium():
    d = SH
    body = _panel(36, 36, 440, 440, "#1a1024", rx=22)
    body += fit(
        S.proscenium(P(a="#7b2d5b", b="#d4a93a", l="#fff4c9", k="#0d0712")), 76, 60, 360, 260
    )
    body += fit(
        text("PROSCENIUM", "Cinzel", 100, weight=900, fill="#d4a93a", ls=4), 64, 336, 384, 64
    )
    body += fit(
        text("THE PERFORMING ARTS", "Cinzel", 40, weight=700, fill="#fff", ls=6), 126, 414, 260, 26
    )
    return svg(body, d)


@net("Hemline", CABLE, "fashion", "style")
def hemline():
    d = SH
    body = _panel(56, 36, 400, 440, "#fbe8ec", rx=10, edge="#1a1a1a", sw=8)
    body += fit(S.dress(P(a="#1a1a1a", b="#e5383b", k="#1a1a1a")), 186, 60, 140, 220)
    body += '<rect x="80" y="290" width="352" height="26" fill="#ffd166" stroke="#1a1a1a" stroke-width="4"/>'
    for x in range(88, 430, 14):
        body += f'<line x1="{x}" y1="290" x2="{x}" y2="{302 if (x - 88) % 42 else 308}" stroke="#1a1a1a" stroke-width="2"/>'
    body += fit(text("HEMLINE", "Abril Fatface", 100, fill="#1a1a1a", ls=8), 90, 334, 332, 80)
    body += fit(
        text("FASHION · STYLE · RUNWAY", "Montserrat", 40, weight=600, fill="#e5383b", ls=4),
        126,
        426,
        260,
        22,
    )
    return svg(body, d)


@net("Suds", CABLE, "soaps", "daytime drama")
def suds():
    d = SH + rad("b", [(0, "#ffd6e8"), (1, "#ff85b3")], r=0.7)
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="220" fill="url(#b)" stroke="#5a0f36" stroke-width="8"/></g>'
    for x, y, r in ((130, 130, 40), (380, 110, 30), (400, 380, 44), (110, 380, 26), (256, 90, 20)):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" fill-opacity=".45" stroke="#fff" stroke-width="4"/><path d="M{x - r * 0.5} {y - r * 0.1} Q{x - r * 0.45} {y - r * 0.55} {x - r * 0.05} {y - r * 0.6}" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round"/>'
    body += f'<g filter="url(#sh)">{fit(tilt(text("suds", "Pacifico", 100, fill="#fff", stroke="#5a0f36", sw=14), -8), 110, 150, 292, 170)}</g>'
    body += fit(
        text("DAYTIME DRAMA", "Oswald", 40, weight=700, fill="#5a0f36", ls=8), 166, 340, 180, 28
    )
    return svg(body, d)


@net("Liftoff", CABLE, "space", "science")
def liftoff():
    d = SH + lin("sky", [(0, "#0b1d51"), (1, "#3a5a9f")], user=True, y2=340)
    scene = '<rect width="512" height="512" fill="url(#sky)"/>'
    for x, y in ((90, 80), (420, 70), (380, 150), (140, 170)):
        scene += f'<circle cx="{x}" cy="{y}" r="3" fill="#fff"/>'
    scene += centred(
        S.rocket(P(a="#e63946", b="#ffb703", c="#8ecae6", l="#f4f4f4", k="#0a0f24")), 256, 150, 220
    )
    for cx, cy, r in (
        (200, 300, 50),
        (256, 310, 60),
        (312, 300, 50),
        (160, 330, 40),
        (352, 330, 40),
    ):
        scene += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#e9ecef" stroke="#adb5bd" stroke-width="3"/>'
    return L.emblem(
        scene,
        "LIFTOFF",
        font="Orbitron",
        weight=900,
        ink="#fff",
        band="#0a0f24",
        rim="#ffb703",
        edge="#0a0f24",
        defs=d,
        ls=10,
    )


@net("Offshore", CABLE, "surfing", "beach")
def offshore():
    d = lin(
        "sky",
        [(0, "#ffb347"), (0.55, "#ff6f61"), (0.56, "#0096c7"), (1, "#023e8a")],
        user=True,
        y2=330,
    )
    scene = '<rect width="512" height="512" fill="url(#sky)"/><circle cx="256" cy="176" r="60" fill="#ffe8a8"/>'
    scene += centred(S.wave(P(a="#48cae4", c="#0077b6", l="#fff", k="#023047")), 170, 250, 190)
    scene += centred(S.palm(P(a="#2d6a4f", b="#8a5a2b", k="#10261c")), 390, 210, 190)
    return L.emblem(
        scene,
        "OFFSHORE",
        font="Righteous",
        ink="#fff",
        band="#023e8a",
        rim="#ffe8a8",
        edge="#021a3a",
        defs=d,
        ls=8,
    )


@net("Dead Drop", CABLE, "spy thrillers")
def dead_drop():
    d = SH + worn("wn", cut=0.85, seed=7)
    body = '<g filter="url(#sh)"><rect x="56" y="40" width="400" height="432" fill="#efe6cf" stroke="#2a2a2a" stroke-width="5" transform="rotate(3 256 256)"/></g>'
    body += '<g transform="rotate(3 256 256)">'
    body += fit(text("DEAD DROP", "Special Elite", 100, fill="#1a1a1a"), 96, 90, 320, 76)
    for y, w in ((196, 300), (224, 220), (252, 280), (280, 180), (308, 260)):
        body += f'<rect x="96" y="{y}" width="{w}" height="16" fill="#111"/>'
    body += f'<g filter="url(#wn)" transform="rotate(-12 300 390)"><rect x="176" y="350" width="250" height="76" rx="6" fill="none" stroke="#c1121f" stroke-width="8"/>{fit(text("TOP SECRET", "Black Ops One", 100, fill="#c1121f"), 190, 364, 222, 48)}</g>'
    body += "</g>"
    return svg(body, d)


@net("Cape & Cowl", CABLE, "superheroes", "action")
def cape_and_cowl():
    d = (
        SH
        + "<pattern id='ht' width='16' height='16' patternUnits='userSpaceOnUse'><rect width='16' height='16' fill='#ffd23f'/><circle cx='8' cy='8' r='4' fill='#ff9f1c'/></pattern>"
    )
    body = f'<g filter="url(#sh)"><polygon points="{star(256, 220, 236, 170, 14)}" fill="#1a1024"/><polygon points="{star(256, 220, 218, 158, 14)}" fill="url(#ht)"/></g>'
    body += fit(S.mask_hero(P(a="#1d4ed8", l="#fff", k="#1a1024")), 136, 90, 240, 110)
    w = text("CAPE & COWL", "Bangers", 100, fill="#e63946", stroke="#1a1024", sw=14, ls=2)
    body += f'<g filter="url(#sh)">{fit(tilt(extrude(w, 5, 7, 8, "#1a1024") + w, -6), 40, 214, 432, 120)}</g>'
    body += fit(
        text(
            "HEROES · VILLAINS · LEGENDS", "Bangers", 40, fill="#fff", stroke="#1a1024", sw=8, ls=3
        ),
        110,
        396,
        292,
        36,
    )
    return svg(body, d)


@net("Strange Frequency", CABLE, "anthology", "twilight", "sci-fi")
def strange_frequency():
    d = SH + glow("gl", "#39ff88", blur=6, strength=2)
    body = _panel(24, 40, 464, 432, "#07130d", rx=24)
    for x in range(44, 470, 28):
        body += f'<line x1="{x}" y1="60" x2="{x}" y2="300" stroke="#39ff88" stroke-width="1" opacity=".15"/>'
    for y in range(60, 300, 28):
        body += f'<line x1="44" y1="{y}" x2="468" y2="{y}" stroke="#39ff88" stroke-width="1" opacity=".15"/>'
    wave = "M44 180"
    for i in range(1, 213):
        x = 44 + i * 2
        amp = 60 * math.sin(i / 212 * math.pi) * (1 + 0.4 * math.sin(i * 0.9))
        wave += f" L{x} {180 + amp * math.sin(i * 0.21):.1f}"
    body += (
        f'<g filter="url(#gl)"><path d="{wave}" fill="none" stroke="#39ff88" stroke-width="4"/></g>'
    )
    body += fit(
        text("STRANGE", "Syncopate", 100, weight=700, fill="#e8fff1", ls=6), 60, 324, 392, 58
    )
    body += fit(
        text("FREQUENCY", "Syncopate", 100, weight=700, fill="#39ff88", ls=6), 60, 396, 392, 50
    )
    return svg(body, d)


@net("Cold Spot", CABLE, "paranormal", "ghosts")
def cold_spot():
    d = (
        SH
        + glow("gl", "#9ad1f5", blur=10, strength=2)
        + rad("n", [(0, "#1d3a5f"), (1, "#081424")], r=0.7)
    )
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="url(#n)" stroke="#040a14" stroke-width="8"/></g>'
    body += f'<g filter="url(#gl)" opacity=".92">{centred(S.ghost(P(l="#e8f6ff", k="#081424")), 256, 176, 210)}</g>'
    body += centred(S.snowflake(P(l="#9ad1f5")), 380, 120, 60) + centred(
        S.snowflake(P(l="#9ad1f5")), 136, 110, 44
    )
    body += f'<g filter="url(#sh)">{fit(text("COLD SPOT", "Audiowide", 100, fill="#e8f6ff", stroke="#040a14", sw=10, ls=4), 70, 300, 372, 80)}</g>'
    body += fit(
        text("PARANORMAL INVESTIGATIONS", "Audiowide", 40, fill="#9ad1f5", ls=2), 106, 396, 300, 24
    )
    return svg(body, d)


@net("Grand Rounds", CABLE, "medical drama", "drama")
def grand_rounds():
    d = SH
    body = _panel(36, 60, 440, 392, "#e9f7f6", rx=24, edge="#0b3a3a", sw=8)
    body += '<polyline points="56,210 170,210 196,160 222,262 250,120 278,300 304,210 456,210" fill="none" stroke="#2a9d8f" stroke-width="8" stroke-linejoin="round" stroke-linecap="round"/>'
    body += fit(S.stethoscope(P(a="#0b3a3a", l="#fff", k="#0b3a3a")), 330, 80, 110, 110)
    body += fit(
        text("GRAND ROUNDS", "Montserrat", 100, weight=900, fill="#0b3a3a", ls=4), 66, 290, 380, 70
    )
    body += fit(
        text("MEDICAL DRAMA", "Montserrat", 40, weight=700, fill="#2a9d8f", ls=10),
        150,
        380,
        212,
        26,
    )
    return svg(body, d)


@net("Rerun Road", CABLE, "marathons", "classic tv", "reruns")
def rerun_road():
    d = SH
    body = '<g filter="url(#sh)"><rect x="24" y="96" width="464" height="220" rx="18" fill="#1e6f45" stroke="#fff" stroke-width="8"/></g>'
    body += fit(
        text("RERUN ROAD", "Barlow Condensed", 100, weight=700, fill="#fff", ls=4), 60, 120, 392, 96
    )
    body += fit(
        text("NEXT EPISODE  →", "Barlow Condensed", 60, weight=600, fill="#fff", ls=4),
        150,
        236,
        212,
        50,
    )
    body += '<rect x="244" y="316" width="24" height="170" fill="#8d99ae"/>'
    shield = (
        "M196 350 L316 350 Q322 380 316 400 Q308 440 256 470 Q204 440 196 400 Q190 380 196 350 Z"
    )
    body += f'<g filter="url(#sh)"><path d="{shield}" fill="#fff" stroke="#141414" stroke-width="6"/></g>'
    body += fit(text("24", "Barlow Condensed", 100, weight=700, fill="#141414"), 216, 370, 80, 70)
    return svg(body, d)


@net("Front Porch", CABLE, "family classics", "family")
def front_porch():
    d = SH + lin("w", [(0, "#d9a066"), (1, "#a8703c")])
    body = '<g filter="url(#sh)"><rect x="30" y="40" width="452" height="432" rx="24" fill="#8ecae6" stroke="#1d3557" stroke-width="8"/></g>'
    body += '<rect x="34" y="330" width="444" height="138" fill="url(#w)"/>'
    for y in range(350, 470, 22):
        body += f'<line x1="34" y1="{y}" x2="478" y2="{y}" stroke="#6b4423" stroke-width="3"/>'
    for x in (60, 452):
        body += f'<rect x="{x - 12}" y="44" width="24" height="290" fill="#fff" stroke="#1d3557" stroke-width="4"/>'
    body += fit(S.rocking_chair(P(a="#fff", k="#1d3557")), 300, 190, 130, 160)
    body += f'<g filter="url(#sh)">{fit(tilt(text("Front Porch", "Yellowtail", 100, fill="#fff", stroke="#1d3557", sw=14), -6), 60, 80, 392, 130)}</g>'
    body += fit(
        text("FAMILY CLASSICS", "Oswald", 40, weight=700, fill="#1d3557", ls=6), 80, 224, 200, 30
    )
    return svg(body, d)


@net("Tinsel", CABLE, "christmas", "holiday movies")
def tinsel():
    d = (
        SH
        + lin("g", [(0, "#fff3b0"), (0.5, "#ffc300"), (1, "#c77800")])
        + rad("r", [(0, "#d62828"), (1, "#7a0d15")], r=0.7)
    )
    body = '<g filter="url(#sh)"><rect x="30" y="60" width="452" height="392" rx="40" fill="url(#r)" stroke="#3a0508" stroke-width="8"/></g>'
    garland = "M40 110 Q140 180 256 120 Q372 60 472 130"
    body += f'<path d="{garland}" fill="none" stroke="url(#g)" stroke-width="16" stroke-dasharray="3 3"/>'
    for x, y, c in (
        (120, 150, "#2a9d8f"),
        (200, 150, "#fff"),
        (300, 104, "#2a9d8f"),
        (390, 100, "#fff"),
    ):
        body += f'<line x1="{x}" y1="{y - 20}" x2="{x}" y2="{y}" stroke="url(#g)" stroke-width="3"/><circle cx="{x}" cy="{y + 16}" r="18" fill="{c}" stroke="#3a0508" stroke-width="4"/><rect x="{x - 6}" y="{y - 4}" width="12" height="8" fill="url(#g)"/>'
    body += f'<g filter="url(#sh)">{fit(tilt(text("Tinsel", "Great Vibes", 100, fill="url(#g)", stroke="#3a0508", sw=6), -6), 90, 190, 332, 150)}</g>'
    body += fit(
        text("CHRISTMAS ALL YEAR", "Cinzel", 40, weight=700, fill="#fff3d6", ls=6),
        136,
        370,
        240,
        28,
    )
    return svg(body, d)


def logos() -> list[Logo]:
    return [Logo(nid, name, cat, fn, tags) for nid, name, cat, tags, fn in NETWORKS]
