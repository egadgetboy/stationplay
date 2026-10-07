"""Reusable logo compositions. Each returns a whole logo's SVG. The words,
fonts, colours and pictures are the caller's; these only arrange them the
way real channel logos are arranged."""

from __future__ import annotations

import math
import random

from kit import (
    arc_text,
    banner,
    esc,
    extrude,
    fit,
    glow,
    lin,
    pts,
    rad,
    rough,
    shadow,
    star,
    svg,
    text,
    worn,
)
from symbols import centred

SH = shadow("sh", dy=6, blur=6, opacity=0.45)


def _word(word, font, fill, stroke=None, sw=0, weight=400, style="normal", ls=0):
    return text(word, font, 100, weight=weight, fill=fill, stroke=stroke, sw=sw, style=style, ls=ls)


# ---------------------------------------------------------------- emblems


def emblem(
    scene: str,
    word: str,
    *,
    font: str,
    ink: str,
    band: str,
    rim: str,
    edge: str,
    weight: int = 400,
    sky: str = "",
    defs: str = "",
    ls: float = 0,
    sub: str | None = None,
    sub_font: str | None = None,
) -> str:
    """A round picture (scene drawn for a circle at 256,214 r190) with a
    notched banner across the bottom carrying the word."""
    d = SH + defs + "<clipPath id='ec'><circle cx='256' cy='214' r='190'/></clipPath>"
    body = '<g filter="url(#sh)">'
    body += f'<circle cx="256" cy="214" r="202" fill="{edge}"/>'
    body += f'<g clip-path="url(#ec)">{sky}{scene}</g>'
    body += f'<circle cx="256" cy="214" r="190" fill="none" stroke="{rim}" stroke-width="6"/>'
    body += banner(24, 488, 348, 84, band, rim, 5, cut=20)
    body += "</g>"
    body += fit(_word(word, font, ink, weight=weight, ls=ls), 76, 362, 360, 56)
    if sub:
        body += fit(text(sub, sub_font or font, 40, fill=rim, ls=4), 176, 446, 160, 22)
    return svg(body, d)


def patch(
    scene: str,
    word: str,
    *,
    font: str,
    ink: str,
    band: str,
    rim: str,
    edge: str,
    weight: int = 400,
    defs: str = "",
    shape: str = "shield",
    ls: float = 0,
) -> str:
    """A patch (shield or hexagon) with a picture and a banner across it."""
    if shape == "shield":
        outer = "M256 30 L458 128 L458 296 Q458 436 256 490 Q54 436 54 296 L54 128 Z"
        inner = "M256 52 L438 140 L438 296 Q438 420 256 468 Q74 420 74 296 L74 140 Z"
    else:
        outer = f"M{pts([(256 + 236 * math.cos(math.radians(a)), 256 + 236 * math.sin(math.radians(a))) for a in range(-90, 270, 60)])}Z".replace(
            "M", "M", 1
        )
        outer = (
            "M"
            + " L".join(
                f"{256 + 236 * math.cos(math.radians(a)):.1f} {256 + 236 * math.sin(math.radians(a)):.1f}"
                for a in range(-90, 270, 60)
            )
            + " Z"
        )
        inner = (
            "M"
            + " L".join(
                f"{256 + 214 * math.cos(math.radians(a)):.1f} {256 + 214 * math.sin(math.radians(a)):.1f}"
                for a in range(-90, 270, 60)
            )
            + " Z"
        )
    d = SH + defs + f"<clipPath id='pc'><path d='{inner}'/></clipPath>"
    body = f'<g filter="url(#sh)"><path d="{outer}" fill="{edge}"/>'
    body += f'<g clip-path="url(#pc)">{scene}</g>'
    body += f'<path d="{inner}" fill="none" stroke="{rim}" stroke-width="6"/>'
    body += banner(30, 482, 352, 76, band, edge, 6, cut=18)
    body += "</g>"
    body += fit(_word(word, font, ink, weight=weight, ls=ls), 76, 364, 360, 52)
    return svg(body, d)


def ribbon_badge(
    back: str,
    word: str,
    *,
    font: str,
    ink: str,
    band: str,
    band_dark: str,
    edge: str,
    weight: int = 400,
    defs: str = "",
    y: float = 244,
    ls: float = 0,
) -> str:
    """A big emblem (sheriff star, medal, seal...) with a ribbon across it."""
    d = SH + defs
    body = f'<g filter="url(#sh)">{back}'
    body += f'<path d="M34 {y + 18} L90 {y + 18} L76 {y + 48} L90 {y + 78} L34 {y + 78} L52 {y + 48} Z" fill="{band_dark}" stroke="{edge}" stroke-width="4" stroke-linejoin="round"/>'
    body += f'<path d="M478 {y + 18} L422 {y + 18} L436 {y + 48} L422 {y + 78} L478 {y + 78} L460 {y + 48} Z" fill="{band_dark}" stroke="{edge}" stroke-width="4" stroke-linejoin="round"/>'
    body += f'<rect x="78" y="{y}" width="356" height="78" rx="4" fill="{band}" stroke="{edge}" stroke-width="5"/>'
    body += "</g>"
    body += fit(_word(word, font, ink, weight=weight, ls=ls), 100, y + 12, 312, 54)
    return svg(body, d)


def seal(
    centre: str,
    top: str,
    bottom: str,
    *,
    font: str,
    ring: str,
    ring_ink: str,
    face: str,
    edge: str,
    weight: int = 700,
    defs: str = "",
    dots: str | None = None,
    ls: float = 6,
) -> str:
    """A round seal: words around a ring, a picture in the middle."""
    d = SH + defs
    t_defs, t_body = arc_text(
        top, font, 256, 256, 176, 50, weight=weight, fill=ring_ink, ls=ls, pid="top"
    )
    b_defs, b_body = arc_text(
        bottom, font, 256, 256, 190, 50, weight=weight, fill=ring_ink, ls=ls, bottom=True, pid="bot"
    )
    d += t_defs + b_defs
    body = f'<g filter="url(#sh)"><circle cx="256" cy="256" r="236" fill="{edge}"/>'
    body += f'<circle cx="256" cy="256" r="226" fill="{ring}"/>'
    body += (
        f'<circle cx="256" cy="256" r="150" fill="{face}" stroke="{edge}" stroke-width="6"/></g>'
    )
    body += f'<circle cx="256" cy="256" r="216" fill="none" stroke="{ring_ink}" stroke-width="3" opacity=".7"/>'
    body += t_body + b_body
    for x in (46, 466):
        body += f'<polygon points="{star(x, 262, 16, 7)}" fill="{dots or ring_ink}"/>'
    body += centre
    return svg(body, d)


def roundel(
    centre: str,
    word: str,
    *,
    font: str,
    ink: str,
    disc: str,
    rim: str,
    edge: str,
    bar: str,
    weight: int = 400,
    defs: str = "",
    ls: float = 0,
    bar_y: float = 300,
) -> str:
    """A disc with a picture and a bar across the lower part with the word
    (a classic network roundel)."""
    d = SH + defs + "<clipPath id='rc'><circle cx='256' cy='256' r='222'/></clipPath>"
    body = f'<g filter="url(#sh)"><circle cx="256" cy="256" r="236" fill="{edge}"/>'
    body += f'<circle cx="256" cy="256" r="222" fill="{disc}"/>{centre}'
    body += f'<rect x="10" y="{bar_y}" width="492" height="92" fill="{bar}" stroke="{edge}" stroke-width="7"/>'
    body += f'<circle cx="256" cy="256" r="222" fill="none" stroke="{rim}" stroke-width="7"/></g>'
    body += fit(_word(word, font, ink, weight=weight, ls=ls), 60, bar_y + 16, 392, 60)
    return svg(body, d)


# ---------------------------------------------------------------- picture + word


def sym_word(
    sym: str,
    word: str,
    *,
    font: str,
    ink: str,
    edge: str,
    weight: int = 400,
    sub: str | None = None,
    sub_font: str | None = None,
    sub_ink: str | None = None,
    defs: str = "",
    style: str = "normal",
    ls: float = 0,
    sw: float = 14,
    sym_box=(106, 20, 300, 270),
    word_box=(24, 300, 464, 116),
    sub_box=(96, 432, 320, 38),
    word_fill: str | None = None,
) -> str:
    """A picture above a big word (and an optional line under it)."""
    d = SH + defs
    body = f'<g filter="url(#sh)">{fit(sym, *sym_box)}</g>'
    body += f'<g filter="url(#sh)">{fit(text(word, font, 100, weight=weight, fill=word_fill or ink, stroke=edge, sw=sw, style=style, ls=ls), *word_box)}</g>'
    if sub:
        body += fit(
            text(
                sub,
                sub_font or font,
                40,
                weight=weight,
                fill=sub_ink or ink,
                stroke=edge,
                sw=8,
                ls=6,
            ),
            *sub_box,
        )
    return svg(body, d)


def word_sym(
    word: str,
    sym: str,
    *,
    font: str,
    ink: str,
    edge: str,
    weight: int = 400,
    defs: str = "",
    style: str = "normal",
    ls: float = 0,
    sw: float = 14,
    top_box=(24, 40, 464, 140),
    sym_box=(96, 196, 320, 276),
    word_fill: str | None = None,
) -> str:
    """A word across the top with a picture under it."""
    d = SH + defs
    body = f'<g filter="url(#sh)">{fit(sym, *sym_box)}</g>'
    body += f'<g filter="url(#sh)">{fit(text(word, font, 100, weight=weight, fill=word_fill or ink, stroke=edge, sw=sw, style=style, ls=ls), *top_box)}</g>'
    return svg(body, d)


def letter_swap(
    before: str,
    sym: str,
    after: str,
    *,
    font: str,
    ink: str,
    edge: str,
    weight: int = 400,
    sub: str | None = None,
    sub_font: str | None = None,
    sub_ink: str | None = None,
    defs: str = "",
    sym_size: float = 78,
    gap: float = 4,
    sw: float = 12,
    ls: float = 0,
    sym_dy: float = -34,
    style: str = "normal",
    box=(20, 150, 472, 180),
    sub_box=(96, 350, 320, 40),
    word_fill: str | None = None,
    extra_back: str = "",
) -> str:
    """A word with one letter replaced by a picture (an O as a moon, a
    globe or a reel...)."""
    d = SH + defs
    left = text(
        before,
        font,
        100,
        weight=weight,
        fill=word_fill or ink,
        stroke=edge,
        sw=sw,
        anchor="end",
        x=-sym_size / 2 - gap,
        style=style,
        ls=ls,
    )
    right = text(
        after,
        font,
        100,
        weight=weight,
        fill=word_fill or ink,
        stroke=edge,
        sw=sw,
        anchor="start",
        x=sym_size / 2 + gap,
        style=style,
        ls=ls,
    )
    pic = centred(sym, 0, sym_dy, sym_size)
    body = extra_back + f'<g filter="url(#sh)">{fit(left + pic + right, *box)}</g>'
    if sub:
        body += fit(
            text(
                sub,
                sub_font or font,
                40,
                weight=weight,
                fill=sub_ink or ink,
                stroke=edge,
                sw=8,
                ls=8,
            ),
            *sub_box,
        )
    return svg(body, d)


def stacked(
    lines: list[tuple[str, str, str, int]],
    *,
    edge: str,
    sw: float = 14,
    defs: str = "",
    boxes: list[tuple] | None = None,
    back: str = "",
    tilt: float = 0,
    extrude_by: float = 0,
    style: str = "normal",
) -> str:
    """Words on two or three lines, each fitted to its own box; lines are
    (word, font, fill, weight)."""
    d = SH + defs
    n = len(lines)
    if boxes is None:
        boxes = {
            1: [(24, 150, 464, 212)],
            2: [(30, 104, 452, 150), (30, 262, 452, 150)],
            3: [(40, 70, 432, 112), (40, 196, 432, 112), (40, 322, 432, 112)],
        }[n]
    body = back
    for (word, font, fill, weight), box in zip(lines, boxes, strict=True):
        t = text(word, font, 100, weight=weight, fill=fill, stroke=edge, sw=sw, style=style)
        if extrude_by:
            t = extrude(t, extrude_by * 0.7, extrude_by, 10, edge) + t
        if tilt:
            t = f'<g transform="rotate({tilt})">{t}</g>'
        body += f'<g filter="url(#sh)">{fit(t, *box)}</g>'
    return svg(body, d)


# ---------------------------------------------------------------- loud


def burst_word(
    word: str,
    sub: str | None,
    *,
    font: str,
    fill: str,
    edge: str,
    back: str,
    back2: str,
    sub_fill: str = "#fff",
    sub_font: str = "Archivo Black",
    points: int = 16,
    tilt: float = -8,
    weight: int = 400,
    defs: str = "",
    extra: str = "",
    rays: bool = False,
) -> str:
    """A cartoon burst with a big tilted word."""
    d = SH + defs + lin("bw", [(0, back), (1, back2)])
    body = '<g filter="url(#sh)">'
    body += f'<polygon points="{star(256, 246, 240, 176, points, rot=-80)}" fill="{edge}"/>'
    body += f'<polygon points="{star(256, 246, 222, 164, points, rot=-80)}" fill="url(#bw)"/>'
    if rays:
        for k in range(points):
            a = math.radians(-80 + k * 360 / points)
            body += f'<line x1="{256 + 60 * math.cos(a):.0f}" y1="{246 + 60 * math.sin(a):.0f}" x2="{256 + 150 * math.cos(a):.0f}" y2="{246 + 150 * math.sin(a):.0f}" stroke="#fff" stroke-opacity=".18" stroke-width="18"/>'
    body += "</g>" + extra
    w = text(word, font, 100, weight=weight, fill=fill, stroke=edge, sw=14)
    body += fit(
        f'<g transform="rotate({tilt})">{extrude(w, 5, 8, 8, edge)}{w}</g>',
        34,
        150 if sub else 170,
        444,
        160,
    )
    if sub:
        body += fit(
            text(sub, sub_font, 40, fill=sub_fill, stroke=edge, sw=9, ls=4), 140, 330, 232, 40
        )
    return svg(body, d)


def plate(
    word: str,
    sub: str | None,
    *,
    font: str,
    ink: str,
    metal=("#d6dbe0", "#8e979f"),
    stripe=("#f5c518", "#141414"),
    edge: str = "#141414",
    defs: str = "",
    weight: int = 400,
) -> str:
    """A riveted metal plate with hazard stripes."""
    d = (
        SH
        + defs
        + lin("metal", [(0, metal[0]), (0.5, metal[1]), (1, metal[0])])
        + "<clipPath id='hz'><rect x='40' y='362' width='432' height='40'/></clipPath>"
    )
    body = '<g filter="url(#sh)">'
    body += f'<rect x="28" y="96" width="456" height="320" rx="26" fill="{edge}"/>'
    body += '<rect x="40" y="108" width="432" height="296" rx="18" fill="url(#metal)"/>'
    body += (
        f'<g clip-path="url(#hz)"><rect x="40" y="362" width="432" height="40" fill="{stripe[0]}"/>'
    )
    for x in range(0, 520, 44):
        body += (
            f'<polygon points="{x},362 {x + 22},362 {x - 18},402 {x - 40},402" fill="{stripe[1]}"/>'
        )
    body += "</g>"
    for x, y in ((64, 132), (448, 132), (64, 336), (448, 336)):
        body += f'<circle cx="{x}" cy="{y}" r="11" fill="{metal[1]}" stroke="{edge}" stroke-width="4"/><circle cx="{x - 3}" cy="{y - 3}" r="4" fill="#fff" opacity=".6"/>'
    body += "</g>"
    body += fit(
        text(word, font, 100, weight=weight, fill=ink),
        84,
        150 if sub else 170,
        344,
        130 if sub else 150,
    )
    if sub:
        body += fit(text(sub, font, 40, weight=weight, fill=ink, ls=6), 120, 298, 272, 34)
    return svg(body, d)


def neon(
    word: str,
    sub: str | None,
    *,
    font: str,
    tube: str,
    glow_c: str,
    frame: str,
    panel: str = "#12101a",
    style: str = "normal",
    weight: int = 400,
    sub_tube: str | None = None,
    sub_font: str | None = None,
    shape: str = "rect",
    sym: str = "",
) -> str:
    """A neon sign on a dark panel."""
    d = SH + glow("ng", glow_c, blur=9, strength=2) + glow("fg", frame, blur=7, strength=2)
    if sub_tube:
        d += glow("sg", sub_tube, blur=7, strength=2)
    if shape == "rect":
        outline = '<rect x="30" y="92" width="452" height="328" rx="40"/>'
        inner = '<rect x="52" y="114" width="408" height="284" rx="26"/>'
    else:
        outline = '<circle cx="256" cy="256" r="232"/>'
        inner = '<circle cx="256" cy="256" r="208"/>'
    body = f'<g filter="url(#sh)" fill="{panel}" stroke="#000" stroke-width="4">{outline}</g>'
    body += f'<g fill="none" stroke="{frame}" stroke-width="7" filter="url(#fg)">{inner}</g>'
    body += f'<g fill="none" stroke="#fff" stroke-width="2" opacity=".7">{inner}</g>'
    if sym:
        body += sym
    w = text(word, font, 100, weight=weight, fill="none", stroke=tube, sw=6, style=style)
    core = text(word, font, 100, weight=weight, fill="none", stroke="#fff", sw=2, style=style)
    top = 150 if sub else 176
    body += fit(f'<g filter="url(#ng)">{w}</g>{core}', 80, top, 352, 140 if sub else 160)
    if sub:
        st = sub_tube or tube
        body += fit(
            f'<g filter="url(#sg)">{text(sub, sub_font or font, 40, fill=st, weight=weight)}</g>',
            150,
            316,
            212,
            50,
        )
    return svg(body, d)


def marquee(
    word: str,
    sub: str | None,
    *,
    crest: str,
    crest_ink: str,
    board: str = "#fbf7ea",
    letters: str = "#16161c",
    frame: str = "#b3121f",
    edge: str = "#16161c",
    bulbs: str = "#fff3b0",
    font: str = "Oswald",
    weight: int = 700,
) -> str:
    """A theatre marquee: a lit frame with changeable letters on a white
    board, and a crest on top."""
    d = SH + lin("fr", [(0, frame), (1, "#000")], user=False)
    body = '<g filter="url(#sh)">'
    body += f'<path d="M150 118 L178 40 L334 40 L362 118 Z" fill="{frame}" stroke="{edge}" stroke-width="6" stroke-linejoin="round"/>'
    body += f'<rect x="26" y="110" width="460" height="290" rx="14" fill="{frame}" stroke="{edge}" stroke-width="7"/>'
    body += f'<rect x="64" y="148" width="384" height="214" rx="6" fill="{board}" stroke="{edge}" stroke-width="5"/>'
    for x in range(48, 470, 26):
        body += f'<circle cx="{x}" cy="130" r="7" fill="{bulbs}" stroke="#b36b00" stroke-width="1.5"/><circle cx="{x}" cy="382" r="7" fill="{bulbs}" stroke="#b36b00" stroke-width="1.5"/>'
    for y in range(156, 370, 26):
        body += f'<circle cx="45" cy="{y}" r="7" fill="{bulbs}" stroke="#b36b00" stroke-width="1.5"/><circle cx="467" cy="{y}" r="7" fill="{bulbs}" stroke="#b36b00" stroke-width="1.5"/>'
    body += f'<rect x="236" y="400" width="40" height="70" fill="{edge}"/>'
    body += "</g>"
    body += fit(text(crest, font, 40, weight=weight, fill=crest_ink, ls=8), 196, 60, 120, 44)
    body += fit(
        text(word, font, 100, weight=weight, fill=letters),
        84,
        172 if sub else 190,
        344,
        110 if sub else 130,
    )
    if sub:
        body += f'<line x1="96" y1="298" x2="416" y2="298" stroke="{letters}" stroke-width="3"/>'
        body += fit(text(sub, font, 40, weight=weight, fill=frame, ls=6), 110, 310, 292, 36)
    return svg(body, d)


# ---------------------------------------------------------------- print, paper


def ragged(x, y, w, h, jag=4, step=14, seed=1):
    rng = random.Random(seed)
    p = []
    for i in range(int(w // step) + 1):
        p.append((x + min(w, i * step), y + (rng.uniform(-jag, jag) if i else 0)))
    for i in range(1, int(h // step) + 1):
        p.append((x + w + rng.uniform(-jag, jag), y + min(h, i * step)))
    for i in range(int(w // step), -1, -1):
        p.append((x + min(w, i * step), y + h + rng.uniform(-jag, jag)))
    for i in range(int(h // step), 0, -1):
        p.append((x + rng.uniform(-jag, jag), y + min(h, i * step)))
    return pts(p)


def poster(
    top: str,
    word: str,
    bottom: str,
    *,
    font: str,
    small_font: str,
    ink: str,
    paper=("#f4e4bc", "#e6cc92", "#c9a263"),
    seed: int = 3,
    deco: str = "stars",
    word_box=(108, 150, 296, 116),
) -> str:
    """An old printed poster: worn paper, ruled frame, big wood-type word."""
    d = SH + rad("paper", [(0, paper[0]), (0.7, paper[1]), (1, paper[2])], r=0.75)
    body = f'<polygon points="{ragged(62, 40, 388, 432, seed=seed)}" fill="url(#paper)" filter="url(#sh)"/>'
    body += f'<rect x="84" y="62" width="344" height="388" fill="none" stroke="{ink}" stroke-width="3"/>'
    body += f'<rect x="92" y="70" width="328" height="372" fill="none" stroke="{ink}" stroke-width="1.5"/>'
    for nx, ny in ((78, 52), (434, 52), (78, 460), (434, 460)):
        body += f'<circle cx="{nx}" cy="{ny}" r="5" fill="#5b3a1a"/><circle cx="{nx - 1}" cy="{ny - 1}" r="2" fill="#a67c47"/>'
    if deco == "stars":
        tl = (
            f'<polygon points="{star(-100, -20, 14, 6)}" fill="{ink}"/>'
            + text(top, small_font, 44, fill=ink, y=-4)
            + f'<polygon points="{star(100, -20, 14, 6)}" fill="{ink}"/>'
        )
    else:
        tl = text(top, small_font, 44, fill=ink, y=-4, ls=4)
    body += fit(tl, 140, 92, 232, 42)
    body += fit(text(word, font, 100, fill=ink), *word_box)
    body += f'<line x1="120" y1="290" x2="392" y2="290" stroke="{ink}" stroke-width="4"/><line x1="120" y1="298" x2="392" y2="298" stroke="{ink}" stroke-width="1.5"/>'
    body += fit(text(bottom, small_font, 60, fill=ink, ls=6), 124, 318, 264, 58)
    body += fit(
        f'<polygon points="{star(-60, 0, 12, 5)}" fill="{ink}"/><circle cx="0" cy="0" r="4" fill="{ink}"/><polygon points="{star(60, 0, 12, 5)}" fill="{ink}"/>',
        196,
        398,
        120,
        22,
    )
    return svg(body, d)


def stamp(
    word: str,
    top: str,
    bottom: str,
    *,
    ink: str,
    paper: str = "#f3ead3",
    font: str = "Special Elite",
    word_font: str | None = None,
    tilt: float = -10,
    seed: int = 5,
    round_: bool = True,
    weight: int = 400,
    wear: float = 0.85,
) -> str:
    """A rubber-stamp impression on a paper tag."""
    d = SH + worn("wn", seed=seed, cut=wear) + rough("rg", amount=3, seed=seed)
    if round_:
        t_defs, t_body = arc_text(
            top, font, 256, 256, 150, 44, fill=ink, ls=6, pid="st", weight=weight
        )
        b_defs, b_body = arc_text(
            bottom, font, 256, 256, 164, 44, fill=ink, ls=6, bottom=True, pid="sb", weight=weight
        )
        d += t_defs + b_defs
        body = f'<circle cx="256" cy="256" r="240" fill="{paper}" filter="url(#sh)"/>'
        ink_art = (
            f'<circle cx="256" cy="256" r="212" fill="none" stroke="{ink}" stroke-width="12"/>'
            f'<circle cx="256" cy="256" r="136" fill="none" stroke="{ink}" stroke-width="5"/>'
            + t_body
            + b_body
        )
        ink_art += fit(
            text(word, word_font or font, 100, fill=ink, weight=weight), 140, 206, 232, 96
        )
        ink_art += f'<polygon points="{star(84, 262, 14, 6)}" fill="{ink}"/><polygon points="{star(428, 262, 14, 6)}" fill="{ink}"/>'
    else:
        body = f'<rect x="20" y="96" width="472" height="320" rx="10" fill="{paper}" filter="url(#sh)"/>'
        ink_art = (
            f'<rect x="46" y="122" width="420" height="268" rx="6" fill="none" stroke="{ink}" stroke-width="12"/>'
            f'<rect x="62" y="138" width="388" height="236" rx="2" fill="none" stroke="{ink}" stroke-width="4"/>'
        )
        ink_art += fit(text(top, font, 40, fill=ink, ls=6, weight=weight), 120, 158, 272, 34)
        ink_art += fit(
            text(word, word_font or font, 100, fill=ink, weight=weight), 84, 204, 344, 110
        )
        ink_art += fit(text(bottom, font, 40, fill=ink, ls=6, weight=weight), 120, 330, 272, 30)
    body += f'<g transform="rotate({tilt} 256 256)"><g filter="url(#wn)"><g filter="url(#rg)">{ink_art}</g></g></g>'
    return svg(body, d)


def masthead(
    word: str,
    line: str,
    *,
    font: str = "UnifrakturMaguntia",
    ink: str = "#141414",
    paper: str = "#f6f1e3",
    accent: str = "#b3121f",
    sym: str = "",
) -> str:
    """A newspaper front page masthead."""
    d = SH
    body = f'<g filter="url(#sh)"><rect x="24" y="84" width="464" height="344" rx="4" fill="{paper}"/></g>'
    body += f'<rect x="24" y="84" width="464" height="344" rx="4" fill="none" stroke="{ink}" stroke-width="4"/>'
    body += fit(text(word, font, 100, fill=ink), 48, 110, 416, 120)
    body += f'<line x1="44" y1="252" x2="468" y2="252" stroke="{ink}" stroke-width="5"/><line x1="44" y1="262" x2="468" y2="262" stroke="{ink}" stroke-width="2"/>'
    body += fit(text(line, "Oswald", 40, weight=600, fill=ink, ls=4), 60, 272, 392, 24)
    body += f'<line x1="44" y1="306" x2="468" y2="306" stroke="{ink}" stroke-width="2"/>'
    if sym:
        body += f'<rect x="44" y="320" width="130" height="92" fill="{accent}"/>' + fit(
            sym, 60, 326, 98, 80
        )
    for y in range(326, 410, 14):
        body += f'<rect x="{190 if sym else 44}" y="{y}" width="{278 if sym else 424}" height="6" fill="{ink}" opacity=".5"/>'
    return svg(body, d)


def ticket(
    word: str,
    sub: str,
    *,
    font: str,
    ink: str,
    paper: str,
    edge: str,
    accent: str,
    weight: int = 400,
    tilt: float = -8,
) -> str:
    """An admission ticket."""
    d = SH
    tk = "M40 150 L472 150 L472 214 A42 42 0 0 0 472 298 L472 362 L40 362 L40 298 A42 42 0 0 0 40 214 Z"
    body = f'<g transform="rotate({tilt} 256 256)"><g filter="url(#sh)"><path d="{tk}" fill="{paper}" stroke="{edge}" stroke-width="7"/></g>'
    body += f'<path d="M66 172 L446 172 L446 222 A30 30 0 0 0 446 290 L446 340 L66 340 L66 290 A30 30 0 0 0 66 222 Z" fill="none" stroke="{accent}" stroke-width="4" stroke-dasharray="2 0"/>'
    body += f'<line x1="372" y1="160" x2="372" y2="352" stroke="{edge}" stroke-width="4" stroke-dasharray="10 8"/>'
    body += fit(text(word, font, 100, weight=weight, fill=ink), 90, 196, 262, 96)
    body += fit(text(sub, "Oswald", 40, weight=700, fill=accent, ls=6), 110, 298, 222, 30)
    body += f'<g transform="translate(409 256) rotate(-90)">{text("ADMIT ONE", "Oswald", 26, weight=700, fill=edge, ls=3, y=9)}</g>'
    body += "</g>"
    return svg(body, d)


def film_frame(
    word: str,
    sub: str | None,
    *,
    font: str,
    ink: str,
    film: str = "#16161c",
    frame_fill: str = "#f2ead8",
    weight: int = 400,
    edge: str = "#16161c",
    style: str = "normal",
) -> str:
    """A strip of film with the word in its frame."""
    d = SH
    body = f'<g filter="url(#sh)" transform="rotate(-6 256 256)"><rect x="-10" y="120" width="532" height="272" rx="10" fill="{film}"/>'
    for x in range(8, 512, 38):
        body += f'<rect x="{x}" y="136" width="22" height="18" rx="4" fill="#f2ead8"/><rect x="{x}" y="358" width="22" height="18" rx="4" fill="#f2ead8"/>'
    body += f'<rect x="54" y="172" width="404" height="168" rx="8" fill="{frame_fill}"/>'
    body += fit(
        text(word, font, 100, weight=weight, fill=ink, style=style),
        76,
        194 if sub else 200,
        360,
        90 if sub else 112,
    )
    if sub:
        body += fit(text(sub, "Oswald", 40, weight=700, fill=ink, ls=8), 120, 294, 272, 30)
    body += "</g>"
    return svg(body, d)


# ---------------------------------------------------------------- frames


def deco(
    word: str,
    sub: str | None,
    *,
    font: str,
    gold=("#fff3c2", "#e7bf5a", "#a87a1e", "#f2d27a"),
    field: str = "#0e0d0b",
    sub_font: str = "Poiret One",
    fan: bool = True,
    ls: float = 6,
    weight: int = 400,
) -> str:
    """An art-deco frame with a sunburst fan (old Hollywood)."""
    d = (
        SH
        + lin("gold", [(0, gold[0]), (0.4, gold[1]), (0.75, gold[2]), (1, gold[3])])
        + lin("goldv", [(0, gold[3]), (1, gold[2])])
    )
    frame = "M126 40 L386 40 L386 62 L430 62 L430 106 L452 106 L452 406 L430 406 L430 450 L386 450 L386 472 L126 472 L126 450 L82 450 L82 406 L60 406 L60 106 L82 106 L82 62 L126 62 Z"
    body = f'<g filter="url(#sh)"><path d="{frame}" fill="{field}" stroke="url(#goldv)" stroke-width="8"/></g>'
    body += f'<path d="{frame}" fill="none" stroke="url(#goldv)" stroke-width="2.5" transform="translate(256 256) scale(.91) translate(-256 -256)"/>'
    if fan:
        for k in range(13):
            a = math.radians(-180 + k * 15)
            body += f'<line x1="256" y1="232" x2="{256 + 146 * math.cos(a):.1f}" y2="{232 + 146 * math.sin(a):.1f}" stroke="url(#goldv)" stroke-width="{4 if k % 2 == 0 else 2}"/>'
        body += f'<rect x="96" y="232" width="320" height="160" fill="{field}"/>'
        body += '<path d="M206 232 A50 50 0 0 1 306 232 Z" fill="url(#gold)"/>'
    body += fit(
        text(word, font, 100, weight=weight, fill="url(#gold)", ls=ls),
        100,
        248 if fan else 170,
        312,
        84 if fan else 120,
    )
    if sub:
        body += '<line x1="136" y1="352" x2="376" y2="352" stroke="url(#goldv)" stroke-width="3"/>'
        body += fit(text(sub, sub_font, 40, fill=gold[3], ls=10), 150, 364, 212, 30)
    return svg(body, d)


def tv_screen(
    script: str,
    word: str,
    sub: str | None,
    *,
    screen=("#2f8f8a", "#15504f"),
    band: str = "#d6452f",
    cabinet: str = "#f3e6c8",
    edge: str = "#2a1d14",
    ink: str = "#fff8e7",
    script_font: str = "Yellowtail",
    font: str = "Archivo Black",
) -> str:
    """A 1950s TV set with a script word on the screen and a banner."""
    d = (
        SH
        + lin("scr", [(0, screen[0]), (1, screen[1])])
        + "<clipPath id='screen'><path d='M96 70 Q256 52 416 70 Q440 190 416 330 Q256 348 96 330 Q72 190 96 70 Z'/></clipPath>"
    )
    body = '<g filter="url(#sh)" transform="translate(0 30) scale(1 .96)">'
    body += f'<path d="M80 54 Q256 30 432 54 Q462 190 432 346 Q256 370 80 346 Q50 190 80 54 Z" fill="{cabinet}" stroke="{edge}" stroke-width="8"/>'
    body += f'<path d="M96 70 Q256 52 416 70 Q440 190 416 330 Q256 348 96 330 Q72 190 96 70 Z" fill="url(#scr)" stroke="{edge}" stroke-width="5"/>'
    body += '<g clip-path="url(#screen)">'
    for i, y in enumerate(range(40, 360, 44)):
        body += f'<rect x="60" y="{y}" width="400" height="22" fill="#fff" opacity="{0.08 + 0.03 * (i % 3):.2f}"/>'
    body += '<path d="M104 84 Q256 66 408 84 Q412 110 404 130 Q256 104 110 132 Q100 108 104 84 Z" fill="#fff" opacity=".12"/></g>'
    for dx in (-40, 40):
        body += f'<line x1="{256 + dx * 0.6}" y1="40" x2="{256 + dx * 2.4}" y2="-4" stroke="{edge}" stroke-width="7" stroke-linecap="round"/>'
    body += "</g>"
    body += fit(text(script, script_font, 100, fill=ink, stroke=edge, sw=16), 88, 128, 336, 124)
    body += banner(60, 452, 330, 76, band, edge, 7, cut=14)
    body += fit(text(word, font, 100, fill=ink, ls=14), 130, 344, 252, 48)
    if sub:
        body += fit(
            text(sub, "Oswald", 40, weight=600, fill=cabinet, ls=5, stroke=edge, sw=8),
            126,
            424,
            260,
            30,
        )
    return svg(body, d)


def crest(
    sym: str,
    word: str,
    *,
    font: str,
    ink: str,
    field: str,
    field2: str,
    rim: str,
    edge: str,
    scroll: str,
    scroll_dark: str,
    weight: int = 400,
    top: str | None = None,
) -> str:
    """A shield with a picture and a scroll under it."""
    d = SH + lin("cf", [(0, field), (1, field2)])
    sh = "M256 34 Q340 60 424 48 L424 250 Q424 382 256 440 Q88 382 88 250 L88 48 Q172 60 256 34 Z"
    body = f'<g filter="url(#sh)"><path d="{sh}" fill="url(#cf)" stroke="{edge}" stroke-width="8"/>'
    body += f'<path d="{sh}" fill="none" stroke="{rim}" stroke-width="4" transform="translate(256 240) scale(.92) translate(-256 -240)"/>'
    body += fit(sym, 156, 90 if not top else 120, 200, 200 if not top else 176)
    body += f'<path d="M24 372 L96 360 L96 430 L24 440 L52 404 Z" fill="{scroll_dark}" stroke="{edge}" stroke-width="5" stroke-linejoin="round"/>'
    body += f'<path d="M488 372 L416 360 L416 430 L488 440 L460 404 Z" fill="{scroll_dark}" stroke="{edge}" stroke-width="5" stroke-linejoin="round"/>'
    body += f'<path d="M72 350 Q256 310 440 350 L440 424 Q256 384 72 424 Z" fill="{scroll}" stroke="{edge}" stroke-width="6" stroke-linejoin="round"/></g>'
    body += fit(
        f'<g transform="rotate(0)">{text(word, font, 100, weight=weight, fill=ink)}</g>',
        104,
        350,
        304,
        48,
    )
    if top:
        body += fit(text(top, font, 40, weight=weight, fill=rim, ls=6), 170, 70, 172, 32)
    return svg(body, d)


def block_word(
    parts: list[tuple[str, str, str]],
    *,
    font: str,
    weight: int = 400,
    edge: str = "#141414",
    tilt: float = 0,
    defs: str = "",
    sub: str | None = None,
    sub_fill: str = "#fff",
    ls: float = 0,
) -> str:
    """A modern network wordmark: the word split into solid coloured boxes
    (each part is (text, box colour, text colour))."""
    d = SH + defs
    n = len(parts)
    h = 150 if n <= 2 else 118
    total = n * h + (n - 1) * 14
    y0 = 256 - total / 2 - (22 if sub else 0)
    body = f'<g filter="url(#sh)" transform="rotate({tilt} 256 256)">'
    for i, (word, box, ink) in enumerate(parts):
        y = y0 + i * (h + 14)
        w = 440 - (i % 2) * 40
        x = 256 - w / 2 + (18 if i % 2 else -10)
        body += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{box}" stroke="{edge}" stroke-width="7"/>'
        body += fit(
            text(word, font, 100, weight=weight, fill=ink, ls=ls), x + 24, y + 18, w - 48, h - 36
        )
    if sub:
        y = y0 + total + 20
        body += fit(
            text(sub, font, 40, weight=weight, fill=sub_fill, stroke=edge, sw=8, ls=8),
            136,
            y,
            240,
            34,
        )
    body += "</g>"
    return svg(body, d)


def pennant(
    word: str,
    *,
    font: str,
    ink: str,
    felt: str,
    edge: str,
    stripe: str,
    sym: str = "",
    weight: int = 400,
) -> str:
    """A felt sports pennant."""
    d = SH
    body = '<g filter="url(#sh)" transform="rotate(-10 256 256)">'
    body += f'<rect x="20" y="120" width="36" height="272" rx="8" fill="{stripe}" stroke="{edge}" stroke-width="6"/>'
    body += f'<path d="M52 124 L500 256 L52 388 Z" fill="{felt}" stroke="{edge}" stroke-width="7" stroke-linejoin="round"/>'
    body += f'<path d="M72 150 L440 256 L72 362" fill="none" stroke="{stripe}" stroke-width="5" stroke-linejoin="round"/>'
    if sym:
        body += fit(sym, 76, 214, 84, 84)
    body += fit(
        text(word, font, 100, weight=weight, fill=ink, stroke=edge, sw=10),
        168 if sym else 90,
        222,
        250 if sym else 310,
        68,
    )
    body += "</g>"
    return svg(body, d)


def postage(
    sym: str,
    word: str,
    value: str,
    *,
    font: str,
    ink: str,
    paper: str,
    field: str,
    edge: str,
    weight: int = 400,
    tilt: float = 6,
) -> str:
    """A postage stamp with perforated edges."""
    d = SH
    perf = ""
    for i in range(12):
        perf += f'<circle cx="{76 + i * 32.7:.1f}" cy="56" r="11"/><circle cx="{76 + i * 32.7:.1f}" cy="456" r="11"/>'
        perf += f'<circle cx="56" cy="{76 + i * 32.7:.1f}" r="11"/><circle cx="456" cy="{76 + i * 32.7:.1f}" r="11"/>'
    d += f"<mask id='perf'><rect x='0' y='0' width='512' height='512' fill='#fff'/><g fill='#000'>{perf}</g></mask>"
    body = f'<g transform="rotate({tilt} 256 256)"><g filter="url(#sh)"><rect x="56" y="56" width="400" height="400" fill="{paper}" mask="url(#perf)"/></g>'
    body += f'<rect x="88" y="88" width="336" height="258" fill="{field}" stroke="{edge}" stroke-width="4"/>'
    body += fit(sym, 110, 100, 292, 234)
    body += fit(text(word, font, 100, weight=weight, fill=ink), 96, 358, 250, 70)
    body += fit(text(value, "Oswald", 60, weight=700, fill=ink), 356, 360, 60, 64)
    body += "</g>"
    return svg(body, d)


def tag(
    word: str,
    sub: str | None,
    *,
    font: str,
    ink: str,
    paper: str,
    edge: str,
    string: str = "#8a6a3a",
    weight: int = 400,
    sym: str = "",
) -> str:
    """A luggage/price tag on a string."""
    d = SH
    shape = "M140 96 L440 96 Q460 96 460 116 L460 396 Q460 416 440 416 L140 416 L52 256 Z"
    body = f'<path d="M52 256 Q20 180 90 120" fill="none" stroke="{string}" stroke-width="6"/>'
    body += f'<g filter="url(#sh)"><path d="{shape}" fill="{paper}" stroke="{edge}" stroke-width="7" stroke-linejoin="round"/></g>'
    body += f'<circle cx="112" cy="256" r="16" fill="#fff" stroke="{edge}" stroke-width="5"/>'
    if sym:
        body += fit(sym, 170, 122, 250, 120)
        body += fit(text(word, font, 100, weight=weight, fill=ink), 158, 262, 280, 84)
    else:
        body += fit(
            text(word, font, 100, weight=weight, fill=ink),
            158,
            170 if sub else 190,
            280,
            110 if sub else 130,
        )
    if sub:
        body += fit(
            text(sub, "Oswald", 40, weight=700, fill=ink, ls=6), 178, 356 if sym else 300, 240, 32
        )
    return svg(body, d)


def chrome(
    word: str,
    sub: str | None,
    *,
    font: str = "Audiowide",
    back: str = "",
    defs: str = "",
    style: str = "italic",
    edge: str = "#12052e",
    skew: float = -12,
    box=(30, 170, 452, 150),
    sub_font: str = "Yellowtail",
    sub_fill: str = "#ff4fd8",
) -> str:
    """80s chrome lettering (with a sparkle)."""
    d = (
        SH
        + defs
        + lin(
            "chrome",
            [
                (0, "#e6f7ff"),
                (0.48, "#7fb8ff"),
                (0.5, "#1c1340"),
                (0.62, "#ff7ad9"),
                (1, "#fff0fb"),
            ],
        )
    )
    body = back
    w = text(word, font, 100, fill="url(#chrome)", stroke=edge, sw=12, style=style)
    skewed = f'<g transform="skewX({skew})">{w}</g>'
    body += f'<g filter="url(#sh)">{fit(skewed, *box)}</g>'
    if sub:
        body += fit(
            f'<g transform="rotate(-8)">{text(sub, sub_font, 100, fill=sub_fill, stroke=edge, sw=10)}</g>',
            150,
            box[1] + box[3] - 10,
            300,
            90,
        )
    return svg(body, d)


def bubble(
    word: str,
    *,
    colors: list[str],
    edge: str = "#1b1b3a",
    cloud: str = "#ffffff",
    font: str = "Titan One",
    sub: str | None = None,
    sub_fill: str = "#1b1b3a",
    back: str | None = None,
) -> str:
    """Kids' bubble letters, each its own colour, bouncing on a cloud."""
    d = SH
    cl = (
        back
        if back is not None
        else (
            f'<g filter="url(#sh)" fill="{cloud}" stroke="{edge}" stroke-width="8">'
            '<circle cx="130" cy="280" r="96"/><circle cx="256" cy="220" r="130"/><circle cx="384" cy="280" r="96"/>'
            '<rect x="130" y="260" width="254" height="116" stroke="none"/></g>'
            f'<path d="M34 280 Q34 376 130 376 L384 376 Q480 376 480 280" fill="none" stroke="{edge}" stroke-width="8"/>'
            f'<rect x="120" y="270" width="274" height="100" fill="{cloud}"/>'
        )
    )
    letters = ""
    x = 0
    for i, ch in enumerate(word):
        dy = -14 if i % 2 else 10
        rot = -8 if i % 2 else 6
        letters += (
            f'<g transform="translate({x} {dy}) rotate({rot})">'
            f"{text(ch, font, 100, fill=colors[i % len(colors)], stroke=edge, sw=14, anchor='middle')}</g>"
        )
        x += 74 if ch not in "MW" else 92
    body = cl + f'<g filter="url(#sh)">{fit(letters, 60, 176, 392, 150)}</g>'
    if sub:
        body += fit(text(sub, "Luckiest Guy", 60, fill=sub_fill, ls=4), 150, 390, 212, 44)
    return svg(body, d)


def script_card(
    script: str,
    sub: str | None,
    *,
    card: str,
    card2: str,
    edge: str,
    ink: str,
    script_font: str = "Yellowtail",
    shape: str = "oval",
    sub_font: str = "Oswald",
    sub_ink: str | None = None,
    deco: str = "",
    tilt: float = -8,
    defs: str = "",
) -> str:
    """Script lettering on an oval, diamond or boomerang card (50s style)."""
    d = SH + defs + lin("card", [(0, card), (1, card2)])
    if shape == "oval":
        s = '<ellipse cx="256" cy="256" rx="236" ry="170"/>'
    elif shape == "diamond":
        s = '<polygon points="256,40 492,256 256,472 20,256"/>'
    elif shape == "boomerang":
        s = '<path d="M30 300 Q60 120 260 110 Q420 104 484 170 Q400 150 330 190 Q260 240 290 330 Q200 380 30 300 Z"/>'
    else:
        s = '<rect x="24" y="116" width="464" height="280" rx="140"/>'
    body = f'<g filter="url(#sh)" fill="url(#card)" stroke="{edge}" stroke-width="8">{s}</g>' + deco
    w = text(script, script_font, 100, fill=ink, stroke=edge, sw=14)
    body += fit(f'<g transform="rotate({tilt})">{w}</g>', 56, 150 if sub else 170, 400, 150)
    if sub:
        body += fit(
            text(sub, sub_font, 40, weight=700, fill=sub_ink or ink, ls=8, stroke=edge, sw=8),
            150,
            318,
            212,
            36,
        )
    return svg(body, d)


def varsity(
    word: str,
    sym: str,
    *,
    font: str = "Graduate",
    fill: str,
    outline: str,
    edge: str,
    felt: str | None = None,
    sub: str | None = None,
) -> str:
    """Collegiate arched lettering over a picture."""
    d = SH
    path = "M56 250 Q256 120 456 250"
    d += f'<path id="va" d="{path}" fill="none"/>'
    body = ""
    if felt:
        body += f'<g filter="url(#sh)"><path d="M256 24 Q380 40 470 90 L470 300 Q460 430 256 490 Q52 430 42 300 L42 90 Q132 40 256 24 Z" fill="{felt}" stroke="{edge}" stroke-width="8"/></g>'
    arched = ""
    quoted = f"'{font}'"
    for sw, col in ((30, edge), (20, outline)):
        arched += (
            f'<text font-family="{quoted}" font-size="96" fill="{col}" stroke="{col}" stroke-width="{sw}" stroke-linejoin="round">'
            f'<textPath href="#va" startOffset="50%" text-anchor="middle">{esc(word)}</textPath></text>'
        )
    arched += (
        f'<text font-family="{quoted}" font-size="96" fill="{fill}">'
        f'<textPath href="#va" startOffset="50%" text-anchor="middle">{esc(word)}</textPath></text>'
    )
    body += fit(arched, 36, 44, 440, 196)
    body += f'<g filter="url(#sh)">{fit(sym, 156, 250, 200, 190)}</g>'
    if sub:
        body += fit(text(sub, font, 40, fill=fill, stroke=edge, sw=8, ls=6), 146, 446, 220, 36)
    return svg(body, d)


def tile_word(
    mark: str,
    word: str,
    *,
    font: str,
    ink: str,
    edge: str,
    tile: str,
    tile2: str | None = None,
    weight: int = 800,
    sub: str | None = None,
    sub_ink: str | None = None,
    sub_font: str | None = None,
    shape: str = "circle",
    ls: float = 4,
    defs: str = "",
    ring: str | None = None,
    mark_box=(150, 40, 212, 212),
    word_box=(30, 292, 452, 100),
    sub_box=(110, 410, 292, 34),
) -> str:
    """A modern network mark: a symbol on a solid tile, the name under it."""
    d = SH + defs + lin("tile", [(0, tile), (1, tile2 or tile)])
    x, y, w, h = 136, 24, 240, 240
    if shape == "circle":
        t = f'<circle cx="256" cy="144" r="120" fill="url(#tile)" stroke="{edge}" stroke-width="8"/>'
        rg = (
            f'<circle cx="256" cy="144" r="106" fill="none" stroke="{ring}" stroke-width="4"/>'
            if ring
            else ""
        )
    elif shape == "square":
        t = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="44" fill="url(#tile)" stroke="{edge}" stroke-width="8"/>'
        rg = (
            f'<rect x="{x + 14}" y="{y + 14}" width="{w - 28}" height="{h - 28}" rx="32" fill="none" stroke="{ring}" stroke-width="4"/>'
            if ring
            else ""
        )
    else:  # hexagon
        pts_ = " ".join(
            f"{256 + 128 * math.cos(math.radians(a)):.1f},{144 + 128 * math.sin(math.radians(a)):.1f}"
            for a in range(-90, 270, 60)
        )
        t = f'<polygon points="{pts_}" fill="url(#tile)" stroke="{edge}" stroke-width="8" stroke-linejoin="round"/>'
        rg = ""
    body = f'<g filter="url(#sh)">{t}</g>{rg}{fit(mark, *mark_box)}'
    body += f'<g filter="url(#sh)">{fit(text(word, font, 100, weight=weight, fill=ink, stroke=edge, sw=12, ls=ls), *word_box)}</g>'
    if sub:
        body += fit(
            text(
                sub,
                sub_font or font,
                40,
                weight=weight,
                fill=sub_ink or ink,
                stroke=edge,
                sw=8,
                ls=8,
            ),
            *sub_box,
        )
    return svg(body, d)
