"""Genre logos: three different designs for each of the genres Plex's
movie and TV agents use."""

from __future__ import annotations

import math
import random

import layouts as L
import symbols as S
from kit import Logo, extrude, fit, glow, lin, measure, rad, shadow, star, svg, text
from symbols import P, centred

SH = shadow("sh", dy=6, blur=6, opacity=0.45)
GENRES: list[tuple[str, str, list]] = []  # (genre, id stem, [(variant name, draw)])


def genre(name: str, stem: str | None = None):
    def add(*designs):
        GENRES.append((name, stem or name.lower().replace(" ", "-"), list(designs)))

    return add


# ======================================================================= Action


def action_blast():
    return L.burst_word(
        "ACTION",
        "NONSTOP",
        font="Anton",
        fill="#fff3c4",
        edge="#1a0f0a",
        back="#ffd23f",
        back2="#ff3d1f",
        sub_fill="#ffd23f",
        points=14,
        tilt=-7,
        rays=True,
    )


def action_plate():
    return L.plate("ACTION", "HIGH OCTANE", font="Black Ops One", ink="#161616")


def action_slash():
    d = SH + lin("red", [(0, "#ff4436"), (1, "#b3000c")])
    body = '<g filter="url(#sh)">'
    body += '<polygon points="96,120 492,120 416,392 20,392" fill="#141414"/>'
    body += '<polygon points="110,134 472,134 404,378 34,378" fill="url(#red)"/>'
    body += "</g>"
    for i, (y, w) in enumerate(((170, 70), (210, 110), (300, 90), (340, 60))):
        body += f'<rect x="{60 + i * 4}" y="{y}" width="{w}" height="7" rx="3" fill="#fff" opacity=".55" transform="skewX(-16)"/>'
    w = text("ACTION", "Anton", 100, fill="#fff")
    body += fit(
        f'<g transform="skewX(-16)">{extrude(w, 6, 6, 8, "#5a0006")}{w}</g>', 70, 178, 380, 150
    )
    return svg(body, d)


genre("Action")(("blast", action_blast), ("plate", action_plate), ("slash", action_slash))


# ======================================================================= Adventure


def adventure_compass():
    p = P(a="#c8372d", b="#d9a441", l="#f6ecd2", k="#1d2433")
    back = centred(S.compass(p), 256, 240, 440)
    return L.ribbon_badge(
        back,
        "ADVENTURE",
        font="Alfa Slab One",
        ink="#f6ecd2",
        band="#1f3a5f",
        band_dark="#132540",
        edge="#0c1422",
        y=300,
    )


def adventure_map():
    ink = "#4a2c12"
    d = SH + rad("paper", [(0, "#f6e7c1"), (0.75, "#e3c98f"), (1, "#c49a5b")], r=0.8)
    edge = L.ragged(34, 58, 444, 396, jag=7, step=18, seed=11)
    body = f'<polygon points="{edge}" fill="url(#paper)" filter="url(#sh)"/>'
    body += f'<path d="M90 380 Q150 300 120 250 Q96 206 170 190 Q250 176 250 130 Q252 96 330 104 Q380 110 400 150" fill="none" stroke="{ink}" stroke-width="6" stroke-dasharray="4 14" stroke-linecap="round"/>'
    body += '<g stroke="#b3121f" stroke-width="12" stroke-linecap="round"><line x1="386" y1="136" x2="418" y2="168"/><line x1="418" y1="136" x2="386" y2="168"/></g>'
    body += centred(S.compass(P(a="#b3121f", b="#c49a5b", l="#f6e7c1", k=ink)), 108, 128, 96)
    body += f'<path d="M300 300 q14 -10 28 0 q14 -10 28 0 M320 330 q10 -8 20 0 q10 -8 20 0" fill="none" stroke="{ink}" stroke-width="3" opacity=".6"/>'
    body += fit(
        text("Adventure", "IM Fell English", 100, fill=ink, style="italic"), 70, 250, 372, 116
    )
    body += fit(
        text("THE UNCHARTED CHANNEL", "IM Fell English", 40, fill=ink, ls=4), 110, 380, 292, 26
    )
    return svg(body, d)


def adventure_peak():
    d = lin("sky", [(0, "#ffcf70"), (0.6, "#ff8f5a"), (1, "#d9534f")], user=True, x2=0, y2=360)
    scene = '<rect width="512" height="512" fill="url(#sky)"/>'
    scene += '<circle cx="256" cy="230" r="70" fill="#fff1c9"/>'
    scene += '<polygon points="40,330 170,150 250,250 320,170 470,330" fill="#3d4f6e"/>'
    scene += '<polygon points="170,150 200,192 186,188 172,206 158,188 146,194" fill="#f6ecd2"/><polygon points="320,170 346,206 332,202 320,218 308,202 296,206" fill="#f6ecd2"/>'
    scene += (
        '<polygon points="40,360 150,250 240,330 330,260 470,360 470,520 40,520" fill="#26344d"/>'
    )
    return L.patch(
        scene,
        "ADVENTURE",
        font="Alfa Slab One",
        ink="#f6ecd2",
        band="#c8372d",
        rim="#f6ecd2",
        edge="#1b2336",
        defs=d,
    )


genre("Adventure")(("compass", adventure_compass), ("map", adventure_map), ("peak", adventure_peak))


# ======================================================================= Animation


def animation_bounce():
    ink = "#1b1b3a"
    d = SH
    body = '<g filter="url(#sh)"><rect x="30" y="40" width="452" height="250" rx="30" fill="#fdf6e3" stroke="#1b1b3a" stroke-width="8"/></g>'
    # a bouncing ball, frame by frame
    xs = [80, 128, 172, 212, 250, 290, 334, 382, 432]
    ys = [100, 150, 210, 256, 256, 206, 154, 116, 100]
    body += f'<path d="M80 100 Q170 330 250 256 Q330 190 432 100" fill="none" stroke="{ink}" stroke-width="3" stroke-dasharray="6 8" opacity=".5"/>'
    for i, (x, y) in enumerate(zip(xs, ys, strict=True)):
        sq = 1.35 if i in (3, 4) else 1
        body += f'<ellipse cx="{x}" cy="{y}" rx="{18 * sq:.0f}" ry="{18 / sq:.0f}" fill="#ff4f5e" stroke="{ink}" stroke-width="5" opacity="{0.35 + 0.08 * i:.2f}"/>'
    body += f'<line x1="200" y1="276" x2="300" y2="276" stroke="{ink}" stroke-width="5" stroke-linecap="round"/>'
    w = text("ANIMATION", "Luckiest Guy", 100, fill="#ffd12e", stroke=ink, sw=14)
    body += f'<g filter="url(#sh)">{fit(extrude(w, 5, 7, 8, ink) + w, 28, 318, 456, 110)}</g>'
    return svg(body, d)


def animation_pencil():
    p = P(a="#ff4f5e", b="#ffd12e", l="#fff", k="#1b1b3a")
    sym = (
        '<path d="M20 170 Q60 60 130 120 Q180 164 150 60" fill="none" stroke="#29a6ff" stroke-width="12" stroke-linecap="round"/>'
        + centred(S.pencil(p), 150, 60, 120)
    )
    return L.sym_word(
        sym,
        "ANIMATION",
        font="Bungee",
        ink="#fff",
        edge="#1b1b3a",
        sw=16,
        sub="DRAWN FOR TV",
        sub_font="Bungee",
        sub_ink="#ffd12e",
    )


def animation_palette():
    p = P(a="#ff4f5e", b="#ffd12e", c="#29a6ff", l="#fdf6e3", k="#1b1b3a")
    centre = centred(S.palette_paint(p), 256, 160, 230)
    return L.roundel(
        centre,
        "ANIMATION",
        font="Lilita One",
        ink="#fff",
        disc="#7a55d6",
        rim="#fdf6e3",
        edge="#1b1b3a",
        bar="#ff4f5e",
        bar_y=290,
    )


genre("Animation")(
    ("bouncing ball", animation_bounce),
    ("pencil", animation_pencil),
    ("palette", animation_palette),
)


# ======================================================================= Anime


def anime_speed():
    ink = "#15102a"
    rng = random.Random(8)
    d = SH + "<clipPath id='c'><circle cx='256' cy='256' r='220'/></clipPath>"
    body = f'<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="{ink}"/><circle cx="256" cy="256" r="220" fill="#fff"/></g>'
    body += '<g clip-path="url(#c)">'
    for k in range(72):
        a = math.radians(k * 5 + rng.uniform(-2, 2))
        r0 = rng.uniform(120, 170)
        w = rng.uniform(2, 7)
        body += f'<polygon points="{256 + 240 * math.cos(a - 0.02):.1f},{256 + 240 * math.sin(a - 0.02):.1f} {256 + 240 * math.cos(a + 0.02):.1f},{256 + 240 * math.sin(a + 0.02):.1f} {256 + r0 * math.cos(a):.1f},{256 + r0 * math.sin(a):.1f}" fill="{ink}" opacity="{min(1, w / 5):.2f}"/>'
    body += "</g>"
    w = text("ANIME", "Russo One", 100, fill="#ff4fa0", stroke=ink, sw=14)
    body += f'<g filter="url(#sh)">{fit(extrude(w, 6, 7, 8, ink) + w, 60, 186, 392, 140)}</g>'
    for x, y, r in ((392, 160, 34), (130, 350, 22), (402, 360, 16)):
        body += centred(S.sparkle(P(), "#ffd12e"), x, y, r * 2)
    body += fit(
        text("アニメ", "Noto Sans CJK JP", 40, weight=900, fill=ink, ls=6), 196, 338, 120, 40
    )
    return svg(body, d)


def anime_moon():
    d = lin("night", [(0, "#1d1446"), (1, "#5a2a82")], user=True, y2=420)
    scene = '<rect width="512" height="512" fill="url(#night)"/>'
    scene += '<circle cx="300" cy="180" r="96" fill="#fde7f0"/><circle cx="330" cy="160" r="14" fill="#f4c6d8"/><circle cx="276" cy="210" r="10" fill="#f4c6d8"/>'
    scene += '<path d="M40 150 Q140 170 190 240 Q230 290 300 300" fill="none" stroke="#2a1530" stroke-width="12" stroke-linecap="round"/>'
    scene += '<path d="M120 170 Q140 130 170 120 M190 240 Q210 200 250 196" fill="none" stroke="#2a1530" stroke-width="7" stroke-linecap="round"/>'
    p = P(a="#ff8fc0", b="#ffe07a", k="#6a1f4a")
    for x, y, s in (
        (100, 160, 50),
        (172, 118, 44),
        (206, 236, 56),
        (258, 196, 40),
        (292, 296, 46),
        (150, 206, 36),
    ):
        scene += centred(S.sakura(p), x, y, s)
    for x, y in ((80, 280), (380, 300), (420, 110), (350, 330)):
        scene += f'<ellipse cx="{x}" cy="{y}" rx="9" ry="5" fill="#ff8fc0" transform="rotate(30 {x} {y})"/>'
    return L.emblem(
        scene,
        "ANIME",
        font="Sora",
        weight=800,
        ink="#fff",
        band="#ff4fa0",
        rim="#fde7f0",
        edge="#150d33",
        defs=d,
        ls=14,
    )


def anime_neon():
    return L.neon(
        "ANIME",
        "アニメ",
        font="Tilt Neon",
        tube="#ff4fd8",
        glow_c="#ff4fd8",
        frame="#2fe6ff",
        sub_tube="#2fe6ff",
        sub_font="Noto Sans CJK JP",
    )


genre("Anime")(("speed lines", anime_speed), ("moon", anime_moon), ("neon", anime_neon))


# ======================================================================= Biography


def bio_quill():
    p = P(a="#1f3a5f", b="#c9a24a", l="#fbf6ea", k="#141b2b")
    return L.sym_word(
        S.quill(p),
        "BIOGRAPHY",
        font="Playfair Display",
        weight=900,
        ink="#fbf6ea",
        edge="#141b2b",
        sw=14,
        sub="TRUE LIVES",
        sub_font="Playfair Display",
        sub_ink="#c9a24a",
        sym_box=(126, 22, 260, 262),
    )


def bio_cameo():
    p = P(a="#6b2f3a", b="#c9a24a", l="#f6ead8", k="#2a1418")
    back = centred(S.profile(p), 256, 236, 440)
    return L.ribbon_badge(
        back,
        "BIOGRAPHY",
        font="Libre Baskerville",
        weight=700,
        ink="#f6ead8",
        band="#6b2f3a",
        band_dark="#431c24",
        edge="#2a1418",
        y=330,
    )


def bio_book():
    p = P(a="#264653", b="#e76f51", l="#fbf6ea", k="#15252b")
    centre = centred(S.book(p), 256, 262, 250)
    return L.seal(
        centre,
        "BIOGRAPHY",
        "TRUE STORIES",
        font="Cinzel",
        ring="#264653",
        ring_ink="#fbf6ea",
        face="#e9c46a",
        edge="#15252b",
    )


genre("Biography")(("quill", bio_quill), ("cameo", bio_cameo), ("book", bio_book))


# ======================================================================= Children


def kids_bubble():
    return L.bubble("KIDS", colors=["#ff4f5e", "#29a6ff", "#ffd12e", "#34c46a"])


def kids_kite():
    lin("sky", [(0, "#8fd8ff"), (1, "#e9f8ff")], user=True, y2=400)
    p = P(a="#ff4f5e", b="#ffd12e", c="#34c46a", k="#1b1b3a", l="#fff")
    scene = '<rect width="512" height="512" fill="url(#sky)"/>'
    scene += centred(S.cloud(p), 130, 250, 140) + centred(S.cloud(p), 380, 290, 110)
    scene += centred(S.kite(p), 290, 160, 200)
    scene += '<path d="M290 250 Q250 300 180 320 Q120 340 60 400" fill="none" stroke="#1b1b3a" stroke-width="3"/>'
    scene += '<rect y="330" width="512" height="200" fill="#6fd06a"/>'
    return L.emblem(
        scene,
        "KIDS TV",
        font="Luckiest Guy",
        ink="#fff",
        band="#ff4f5e",
        rim="#fff",
        edge="#1b1b3a",
        ls=4,
    )


def kids_rainbow():
    p = P(l="#fff", k="#1b1b3a")
    return L.sym_word(
        S.rainbow(p),
        "KIDS",
        font="Londrina Solid",
        weight=900,
        ink="#ffd12e",
        edge="#1b1b3a",
        sw=16,
        sub="PLAYTIME",
        sub_font="Londrina Solid",
        sub_ink="#fff",
        sym_box=(86, 40, 340, 220),
        word_box=(80, 262, 352, 164),
    )


genre("Children", "children")(
    ("bubble letters", kids_bubble), ("kite", kids_kite), ("rainbow", kids_rainbow)
)


# ======================================================================= Comedy


def comedy_club():
    scene = '<rect width="512" height="512" fill="#7a2418"/>'
    for r in range(12):
        off = 0 if r % 2 else 34
        for c in range(-1, 9):
            scene += f'<rect x="{c * 68 + off}" y="{r * 34}" width="62" height="28" rx="3" fill="#a3382a"/>'
    scene += '<circle cx="256" cy="210" r="130" fill="#ffe3a0" opacity=".45"/>'
    scene += centred(S.mic(P(a="#e8403a", l="#e9eef3", k="#141414")), 256, 214, 230)
    return L.emblem(
        scene,
        "COMEDY",
        font="Bowlby One",
        ink="#ffd23f",
        band="#141414",
        rim="#ffd23f",
        edge="#141414",
        ls=4,
    )


def comedy_haha():
    return L.burst_word(
        "COMEDY",
        "HA HA HA!",
        font="Titan One",
        fill="#ffd12e",
        edge="#1a1024",
        back="#ff5fa2",
        back2="#d81b60",
        sub_fill="#fff",
        sub_font="Luckiest Guy",
        points=18,
        tilt=-6,
    )


def comedy_smile():
    d = SH + lin("o", [(0, "#ffb347"), (1, "#ff6a1f")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="#2a1406"/><circle cx="256" cy="256" r="218" fill="url(#o)"/></g>'
    body += fit(
        text("comedy", "Baloo 2", 100, weight=800, fill="#fff", stroke="#2a1406", sw=10),
        70,
        160,
        372,
        130,
    )
    body += '<path d="M140 318 Q256 420 372 318" fill="none" stroke="#2a1406" stroke-width="30" stroke-linecap="round"/>'
    body += '<path d="M140 318 Q256 420 372 318" fill="none" stroke="#ffe066" stroke-width="16" stroke-linecap="round"/>'
    return svg(body, d)


genre("Comedy")(("comedy club", comedy_club), ("burst", comedy_haha), ("smile", comedy_smile))


# ======================================================================= Crime


def crime_tape():
    d = SH
    body = ""
    for rot in (-24, 24):
        tape = f'<g transform="rotate({rot} 256 256)" filter="url(#sh)"><rect x="-40" y="228" width="592" height="56" fill="#ffd400" stroke="#141414" stroke-width="5"/>'
        for x in range(-40, 560, 196):
            tape += text(
                "DO NOT CROSS", "Oswald", 32, weight=700, fill="#141414", x=x + 98, y=268, ls=2
            )
        tape += "</g>"
        body += tape
    body += '<g filter="url(#sh)"><rect x="70" y="166" width="372" height="180" rx="14" fill="#141414" stroke="#ffd400" stroke-width="6"/></g>'
    body += fit(text("CRIME", "Anton", 100, fill="#fff", ls=6), 96, 186, 320, 140)
    return svg(body, d)


def crime_badge():
    p = P(a="#1d2b4f", b="#d7b24a", k="#0d1428")
    back = centred(S.police_badge(p), 256, 236, 440)
    return L.ribbon_badge(
        back,
        "CRIME",
        font="Bebas Neue",
        ink="#fff",
        band="#1d2b4f",
        band_dark="#0d1428",
        edge="#070b17",
        y=318,
        ls=14,
    )


def crime_file():
    return L.stamp(
        "CRIME",
        "CASE FILE",
        "CLASSIFIED",
        ink="#b3121f",
        paper="#e9d7a4",
        round_=False,
        word_font="Black Ops One",
        tilt=-6,
        wear=0.85,
    )


genre("Crime")(("police tape", crime_tape), ("badge", crime_badge), ("case file", crime_file))


# ======================================================================= Documentary


def doc_camera():
    p = P(a="#e9c46a", b="#e76f51", l="#fff", k="#16202a")
    return L.sym_word(
        S.movie_camera(p),
        "DOCUMENTARY",
        font="Oswald",
        weight=700,
        ink="#fff",
        edge="#16202a",
        sw=12,
        ls=2,
        sub="REAL LIFE ON FILM",
        sub_font="Oswald",
        sub_ink="#e9c46a",
        word_box=(24, 300, 464, 104),
    )


def doc_iris():
    p = P(a="#2a9d8f", b="#1f7a70", l="#e9fbf8", k="#0e1c22")
    return L.letter_swap(
        "D",
        S.aperture(p),
        "CS",
        font="Montserrat",
        weight=900,
        ink="#fff",
        edge="#0e1c22",
        sym_size=86,
        gap=6,
        sym_dy=-36,
        sub="DOCUMENTARY",
        sub_font="Montserrat",
        sub_ink="#7fe3d6",
        sw=12,
    )


def doc_globe():
    p = P(a="#2b6cb0", l="#cfe8ff", k="#0d1f3a")
    centre = centred(S.globe(p), 256, 256, 250)
    return L.seal(
        centre,
        "DOCUMENTARY",
        "REAL STORIES",
        font="Oswald",
        ring="#0d1f3a",
        ring_ink="#cfe8ff",
        face="#e8f1fa",
        edge="#060f1f",
        weight=700,
        ls=5,
    )


genre("Documentary")(("camera", doc_camera), ("iris", doc_iris), ("globe", doc_globe))


# ======================================================================= Drama


def drama_masks():
    p = P(a="#c0392b", b="#f1c40f", k="#1a1414")
    return L.sym_word(
        S.masks(p),
        "DRAMA",
        font="Cinzel",
        weight=900,
        ink="#f6e3a1",
        edge="#1a1414",
        sw=14,
        ls=6,
        sub="STAGE & SCREEN",
        sub_font="Cinzel",
        sub_ink="#fff",
        sym_box=(76, 24, 360, 260),
    )


def drama_curtain():
    d = SH + rad("spot", [(0, "#fff4d0"), (0.6, "#e8c56a"), (1, "#3a0f12")], cx=0.5, cy=0.45, r=0.6)
    body = '<g filter="url(#sh)"><rect x="30" y="48" width="452" height="416" rx="16" fill="#1a0a0c"/></g>'
    body += '<rect x="50" y="68" width="412" height="376" rx="8" fill="url(#spot)"/>'
    body += centred(S.curtain(P(a="#a8161f", b="#d4a93a", k="#3a060a")), 256, 256, 412).replace(
        "<g transform", '<g opacity="1" transform', 1
    )
    body += '<rect x="30" y="420" width="452" height="44" rx="4" fill="#3a1c10"/>'
    w = text(
        "DRAMA",
        "Playfair Display",
        100,
        weight=900,
        style="italic",
        fill="#fff",
        stroke="#3a060a",
        sw=10,
    )
    body += fit(w, 120, 200, 272, 110)
    return svg(body, d)


def drama_prestige():
    d = SH + lin("g", [(0, "#f6e3a1"), (0.5, "#c9a24a"), (1, "#f2d27a")])
    body = '<g filter="url(#sh)"><rect x="40" y="96" width="432" height="320" rx="8" fill="#0e0e10"/></g>'
    body += '<rect x="58" y="114" width="396" height="284" rx="2" fill="none" stroke="url(#g)" stroke-width="2.5"/>'
    body += '<path d="M256 136 Q276 166 276 180 Q276 200 256 200 Q236 200 236 180 Q236 166 256 136 Z" fill="#b3121f"/>'
    body += fit(
        text("DRAMA", "Playfair Display", 100, weight=500, fill="#fff", ls=18), 96, 222, 320, 88
    )
    body += '<line x1="176" y1="336" x2="336" y2="336" stroke="url(#g)" stroke-width="2"/>'
    body += fit(
        text("PREMIERE SERIES", "Montserrat", 40, weight=600, fill="#c9a24a", ls=10),
        150,
        352,
        212,
        22,
    )
    return svg(body, d)


genre("Drama")(("masks", drama_masks), ("curtain", drama_curtain), ("prestige", drama_prestige))


# ======================================================================= Family


def family_house():
    p = P(a="#e63946", b="#f4a261", l="#fff8ec", k="#1d1a2b")
    return L.sym_word(
        S.house(p),
        "FAMILY",
        font="Carter One",
        ink="#fff8ec",
        edge="#1d1a2b",
        sw=14,
        sub="TOGETHER TIME",
        sub_font="Carter One",
        sub_ink="#f4a261",
    )


def family_people():
    p = P(a="#ff6b6b", b="#ffd166", c="#4dabf7", k="#1d1a2b")
    centre = centred(S.family(p), 256, 176, 250)
    return L.roundel(
        centre,
        "FAMILY",
        font="Fredoka",
        weight=700,
        ink="#fff",
        disc="#e8f6ff",
        rim="#fff",
        edge="#1d1a2b",
        bar="#2f9e44",
        bar_y=292,
    )


def family_night():
    return L.script_card(
        "Family",
        "MOVIE NIGHT",
        card="#118ab2",
        card2="#073b4c",
        edge="#1d1a2b",
        ink="#ffd166",
        script_font="Pacifico",
        shape="pill",
        tilt=-6,
    )


genre("Family")(("house", family_house), ("people", family_people), ("movie night", family_night))


# ======================================================================= Fantasy


def fantasy_castle():
    d = lin("night", [(0, "#1b1440"), (1, "#5b3a8c")], user=True, y2=380)
    p = P(a="#b8b1d6", b="#f2c14e", l="#fff7da", k="#150f2e")
    scene = '<rect width="512" height="512" fill="url(#night)"/>'
    for x, y in ((90, 110), (140, 70), (400, 140), (430, 90), (360, 60), (70, 200)):
        scene += f'<circle cx="{x}" cy="{y}" r="3" fill="#fff7da"/>'
    scene += centred(S.castle(p), 256, 196, 280)
    scene += (
        '<path d="M40 330 Q150 290 256 320 Q360 290 470 330 L470 520 L40 520 Z" fill="#2c2055"/>'
    )
    return L.emblem(
        scene,
        "FANTASY",
        font="Cinzel",
        weight=900,
        ink="#f2c14e",
        band="#2c2055",
        rim="#f2c14e",
        edge="#150f2e",
        defs=d,
        ls=6,
    )


def fantasy_wizard():
    p = P(a="#8e5bd6", b="#f2c14e", k="#150f2e")
    return L.sym_word(
        S.wizard_hat(p),
        "Fantasy",
        font="Pirata One",
        ink="#f2c14e",
        edge="#150f2e",
        sw=14,
        sub="REALMS OF MAGIC",
        sub_font="Cinzel",
        sub_ink="#fff",
        sym_box=(116, 18, 280, 262),
    )


def fantasy_sword():
    p = P(a="#6d3fb3", b="#f2c14e", l="#eef1f7", k="#150f2e")
    return L.crest(
        S.sword(p),
        "FANTASY",
        font="Cinzel",
        weight=900,
        ink="#150f2e",
        field="#6d3fb3",
        field2="#2c1a5c",
        rim="#f2c14e",
        edge="#150f2e",
        scroll="#f2e3b3",
        scroll_dark="#c9b27a",
    )


genre("Fantasy")(("castle", fantasy_castle), ("wizard", fantasy_wizard), ("sword", fantasy_sword))


# ======================================================================= Film-Noir


def noir_blinds():
    d = SH + "<clipPath id='nb'><rect x='40' y='60' width='432' height='392' rx='12'/></clipPath>"
    body = '<g filter="url(#sh)"><rect x="40" y="60" width="432" height="392" rx="12" fill="#0d0d0f"/></g>'
    body += '<g clip-path="url(#nb)" transform="rotate(0)">'
    for i in range(9):
        body += f'<polygon points="{-40 + i * 0},{80 + i * 44} 560,{20 + i * 44} 560,{42 + i * 44} -40,{102 + i * 44}" fill="#c9c3b6" opacity=".28"/>'
    fig = (
        '<path d="M60 460 L74 330 Q78 296 104 286 L120 280 L132 300 L144 280 L160 286 Q186 296 190 330 L204 460 Z" fill="#141416"/>'
        '<path d="M112 282 L104 250 L132 276 L160 250 L152 282 Z" fill="#1d1d20"/>'
        '<ellipse cx="132" cy="246" rx="22" ry="26" fill="#141416"/>'
    )
    body += fig + centred(S.fedora(P(a="#141416", k="#000")), 132, 214, 104)
    body += "</g>"
    body += fit(text("FILM", "Oswald", 40, weight=600, fill="#c9c3b6", ls=16), 250, 150, 170, 40)
    body += fit(text("NOIR", "Abril Fatface", 100, fill="#fff"), 214, 200, 240, 130)
    body += '<rect x="226" y="346" width="216" height="10" fill="#c1121f"/>'
    return svg(body, d)


def noir_lamp():
    scene = '<rect width="512" height="512" fill="#15171c"/>'
    rng = random.Random(3)
    for _ in range(60):
        x, y = rng.uniform(40, 470), rng.uniform(20, 330)
        scene += f'<line x1="{x:.0f}" y1="{y:.0f}" x2="{x - 8:.0f}" y2="{y + 26:.0f}" stroke="#9aa3b2" stroke-width="2" opacity=".45"/>'
    scene += centred(S.lamp(P(b="#f2e2b0", k="#050608")), 330, 200, 300)
    scene += (
        '<path d="M130 340 L140 250 Q144 222 166 218 Q188 222 192 250 L202 340 Z" fill="#050608"/>'
    )
    scene += '<path d="M138 222 Q166 196 194 222 Q180 214 166 214 Q152 214 138 222 Z" fill="#050608"/><rect x="150" y="196" width="32" height="22" rx="4" fill="#050608"/>'
    scene += '<rect y="330" width="512" height="200" fill="#0b0c10"/><ellipse cx="330" cy="352" rx="120" ry="10" fill="#f2e2b0" opacity=".25"/>'
    return L.emblem(
        scene,
        "FILM NOIR",
        font="Bebas Neue",
        ink="#fff",
        band="#0b0c10",
        rim="#c1121f",
        edge="#000",
        ls=10,
    )


def noir_frame():
    return L.film_frame(
        "NOIR",
        "BLACK & WHITE CRIME",
        font="Abril Fatface",
        ink="#111",
        film="#111",
        frame_fill="#d9d6cf",
    )


genre("Film-Noir", "film-noir")(
    ("blinds", noir_blinds), ("streetlamp", noir_lamp), ("film", noir_frame)
)


# ======================================================================= Food


def food_fork():
    p = P(l="#fff8ec", k="#2a1a12")
    sym = (
        '<circle cx="100" cy="100" r="92" fill="#e4572e" stroke="#2a1a12" stroke-width="8"/>'
        + centred(S.fork_knife(p), 100, 100, 150)
    )
    return L.sym_word(
        sym,
        "FOOD",
        font="Alfa Slab One",
        ink="#fff8ec",
        edge="#2a1a12",
        sw=14,
        ls=4,
        sub="EAT · COOK · SHARE",
        sub_font="Oswald",
        sub_ink="#ffc857",
        sym_box=(136, 22, 240, 240),
        word_box=(60, 284, 392, 130),
    )


def food_gingham():
    check = (
        "<pattern id='gh' width='40' height='40' patternUnits='userSpaceOnUse'><rect width='40' height='40' fill='#fff6ee'/>"
        "<rect width='20' height='40' fill='#e63946' opacity='.55'/><rect width='40' height='20' fill='#e63946' opacity='.55'/></pattern>"
    )
    centre = '<circle cx="256" cy="256" r="222" fill="url(#gh)"/>' + centred(
        S.chef_hat(P(a="#e63946", l="#fff", k="#2a1a12")), 256, 172, 200
    )
    return L.roundel(
        centre,
        "FOOD TV",
        font="Carter One",
        ink="#fff",
        disc="#fff6ee",
        rim="#fff",
        edge="#2a1a12",
        bar="#2a9d8f",
        defs=check,
        bar_y=300,
    )


def food_diner():
    return L.neon(
        "EATS",
        "FOOD & DRINK",
        font="Yellowtail",
        tube="#ff5a5f",
        glow_c="#ff5a5f",
        frame="#39d0ff",
        sub_tube="#ffe066",
        sub_font="Oswald",
    )


genre("Food")(("fork and knife", food_fork), ("gingham", food_gingham), ("diner", food_diner))


# ======================================================================= Game Show


def game_marquee():
    return L.marquee(
        "GAME SHOW", "PLAY ALONG", crest="TV", crest_ink="#fff3b0", frame="#6a1b9a", font="Oswald"
    )


def game_buzzer():
    p = P(a="#ff2e4d", b="#ffd12e", l="#fff", k="#1b1433")
    return L.sym_word(
        S.buzzer(p),
        "GAME SHOW",
        font="Bungee",
        ink="#ffd12e",
        edge="#1b1433",
        sw=16,
        sub="COME ON DOWN",
        sub_font="Bungee",
        sub_ink="#fff",
    )


def game_wheel():
    p = P(a="#ff2e4d", b="#ffd12e", c="#29a6ff", l="#fff", k="#1b1433")
    return L.sym_word(
        S.prize_wheel(p),
        "GAME SHOWS",
        font="Luckiest Guy",
        ink="#fff",
        edge="#1b1433",
        sw=16,
        sub="SPIN TO WIN",
        sub_font="Luckiest Guy",
        sub_ink="#ffd12e",
        sym_box=(126, 16, 260, 268),
    )


genre("Game Show", "game-show")(
    ("marquee", game_marquee), ("buzzer", game_buzzer), ("wheel", game_wheel)
)


# ======================================================================= History


def history_columns():
    p = P(l="#f3ecdc", k="#3a2e1f")
    return L.sym_word(
        S.columns(p),
        "HISTORY",
        font="Cinzel",
        weight=900,
        ink="#f3ecdc",
        edge="#3a2e1f",
        sw=14,
        ls=8,
        sub="THE STORY OF US",
        sub_font="Cinzel",
        sub_ink="#d4a93a",
    )


def history_hourglass():
    p = P(a="#6b4423", b="#d4a93a", c="#c8e3f0", k="#2a1a0c")
    centre = centred(S.hourglass(p), 256, 256, 230)
    return L.seal(
        centre,
        "HISTORY",
        "THEN & NOW",
        font="Cinzel",
        ring="#6b4423",
        ring_ink="#f3ecdc",
        face="#f3ecdc",
        edge="#2a1a0c",
    )


def history_scroll():
    d = SH + lin("parch", [(0, "#f6e8c6"), (1, "#e2c98c")])
    ink = "#3a2410"
    body = '<g filter="url(#sh)">'
    body += '<path d="M76 140 L436 140 L436 372 L76 372 Z" fill="url(#parch)" stroke="#3a2410" stroke-width="6"/>'
    for x in (58, 454):
        body += f'<rect x="{x - 24}" y="122" width="48" height="268" rx="24" fill="#d9b978" stroke="#3a2410" stroke-width="6"/>'
        body += f'<ellipse cx="{x}" cy="122" rx="24" ry="10" fill="#b8955a" stroke="#3a2410" stroke-width="5"/>'
    body += "</g>"
    body += fit(text("History", "IM Fell English", 100, fill=ink), 106, 168, 300, 120)
    body += '<line x1="140" y1="304" x2="372" y2="304" stroke="#3a2410" stroke-width="3"/>'
    body += fit(
        text("TALES FROM THE PAST", "IM Fell English", 40, fill=ink, ls=4), 130, 314, 252, 26
    )
    body += '<g filter="url(#sh)"><circle cx="256" cy="392" r="36" fill="#a4161a" stroke="#5c0a0d" stroke-width="5"/></g>'
    body += f'<polygon points="{star(256, 392, 18, 8)}" fill="#e05a5f"/>'
    return svg(body, d)


genre("History")(
    ("columns", history_columns), ("hourglass", history_hourglass), ("scroll", history_scroll)
)


# ======================================================================= Home and Garden


def home_can():
    p = P(a="#2f9e44", b="#ffd166", c="#4dabf7", k="#1d2a1d")
    sym = centred(S.watering_can(p), 100, 110, 180) + centred(
        S.flower(P(a="#ff6b6b", b="#ffd166", k="#1d2a1d")), 30, 150, 70
    )
    return L.stacked(
        [("HOME", "Alfa Slab One", "#fff", 400), ("& GARDEN", "Alfa Slab One", "#ffd166", 400)],
        edge="#1d2a1d",
        boxes=[(60, 262, 392, 90), (60, 360, 392, 70)],
        back=fit(f'<g filter="url(#sh)">{sym}</g>', 126, 24, 260, 224),
    )


def home_tools():
    p = P(a="#e76f51", b="#f4a261", l="#f1f3f5", k="#1d1a2b")
    centre = centred(S.tools_cross(p), 256, 256, 230)
    return L.seal(
        centre,
        "HOME",
        "& GARDEN",
        font="Oswald",
        ring="#2a9d8f",
        ring_ink="#fff",
        face="#f1faee",
        edge="#123",
        weight=700,
        ls=10,
    )


def home_blocks():
    return L.block_word(
        [("HOME", "#2f9e44", "#fff"), ("& GARDEN", "#ffd166", "#1d1a2b")],
        font="Archivo Black",
        edge="#1d1a2b",
        tilt=-4,
    )


genre("Home and Garden", "home-and-garden")(
    ("watering can", home_can), ("tools", home_tools), ("blocks", home_blocks)
)


# ======================================================================= Horror


def _drips(word: str, font: str, color: str, seed: int = 2, weight: int = 400) -> str:
    """Blood dripping from the bottom of a word (drawn at size 100, centred)."""
    w, (x0, y0, x1, y1) = measure(word, font, weight)
    rng = random.Random(seed)
    out = ""
    x = -w / 2 + 16
    while x < w / 2 - 16:
        length = rng.choice((18, 26, 40, 54, 30))
        width = rng.uniform(7, 11)
        out += (
            f'<path d="M{x - width:.1f} -4 L{x + width:.1f} -4 L{x + width * 0.55:.1f} {length:.1f} '
            f'Q{x:.1f} {length + width * 1.4:.1f} {x - width * 0.55:.1f} {length:.1f} Z" fill="{color}"/>'
            f'<circle cx="{x:.1f}" cy="{length + 4:.1f}" r="{width * 0.75:.1f}" fill="{color}"/>'
        )
        x += rng.uniform(36, 70)
    return out


def horror_moon():
    scene = '<rect width="512" height="512" fill="#1b0f24"/>' + centred(
        S.moon_tree(P(l="#f3e9c6", b="#c9b67a", k="#07040a")), 256, 196, 360
    )
    return L.emblem(
        scene,
        "HORROR",
        font="Pirata One",
        ink="#e0161b",
        band="#07040a",
        rim="#e0161b",
        edge="#07040a",
        ls=6,
    )


def horror_drip():
    d = SH
    word = "HORROR"
    body = '<g filter="url(#sh)"><rect x="24" y="110" width="464" height="292" rx="18" fill="#0a0708"/></g>'
    body += centred(S.bat(P(k="#e0161b")), 256, 150, 150)
    w = text(word, "Ultra", 100, fill="#e0161b")
    body += fit(w + _drips(word, "Ultra", "#e0161b"), 56, 196, 400, 170)
    return svg(body, d)


def horror_tomb():
    p = P(a="#3d5a3a", l="#b9b9b0", k="#0e0e10")
    return L.sym_word(
        S.tombstone(p),
        "Horror",
        font="UnifrakturMaguntia",
        ink="#e8e4d8",
        edge="#0e0e10",
        sw=14,
        sub="AFTER DARK",
        sub_font="Cinzel",
        sub_ink="#e0161b",
        sym_box=(136, 20, 240, 262),
    )


genre("Horror")(("moon", horror_moon), ("dripping", horror_drip), ("tombstone", horror_tomb))


# ======================================================================= Indie


def indie_stamp():
    return L.stamp(
        "INDIE",
        "INDEPENDENT",
        "FILM",
        ink="#1f6f6b",
        paper="#e6d6b3",
        word_font="Black Ops One",
        tilt=-8,
        wear=0.85,
    )


def indie_clapper():
    p = P(a="#ff6b6b", l="#f8f4ec", k="#141414")
    return L.sym_word(
        S.clapper(p),
        "indie",
        font="Permanent Marker",
        ink="#f8f4ec",
        edge="#141414",
        sw=14,
        sub="MADE WITH HEART",
        sub_font="Permanent Marker",
        sub_ink="#ffd166",
    )


def indie_laurel():
    d = SH + lin("g", [(0, "#f6e3a1"), (1, "#b8912f")])
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="#101012"/></g>'
    body += centred(S.laurel(P(a="url(#g)")), 256, 262, 400)
    body += fit(
        text("SELECTION", "Montserrat", 40, weight=700, fill="#d9bd6a", ls=10), 176, 150, 160, 22
    )
    body += fit(
        text("INDIE", "Playfair Display", 100, weight=900, fill="url(#g)"), 156, 190, 200, 100
    )
    body += fit(
        text("FILM FESTIVAL FAVORITES", "Montserrat", 40, weight=700, fill="#d9bd6a", ls=4),
        166,
        306,
        180,
        18,
    )
    return svg(body, d)


genre("Indie")(("stamp", indie_stamp), ("clapperboard", indie_clapper), ("laurels", indie_laurel))


# ======================================================================= Martial Arts


def ma_belt():
    P(a="#141414", b="#d4a93a", k="#000")
    sym = (
        '<circle cx="100" cy="100" r="94" fill="#c1121f" stroke="#1a0506" stroke-width="8"/>'
        + centred(S.belt(P(a="#141414", b="#d4a93a", k="#fff")), 100, 108, 150)
    )
    return L.sym_word(
        sym,
        "MARTIAL ARTS",
        font="Anton",
        ink="#fff",
        edge="#1a0506",
        sw=12,
        ls=3,
        sub="FISTS OF FURY",
        sub_font="Anton",
        sub_ink="#d4a93a",
        sym_box=(146, 22, 220, 240),
        word_box=(30, 280, 452, 124),
    )


def ma_enso():
    d = SH
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="#f4efe3"/></g>'
    body += centred(S.enso(P(a="#c1121f")), 256, 234, 340)
    body += fit(text("MARTIAL", "Knewave", 100, fill="#141414"), 110, 178, 292, 88)
    body += fit(text("ARTS", "Knewave", 100, fill="#141414"), 150, 270, 212, 80)
    return svg(body, d)


def ma_bamboo():
    lin("dusk", [(0, "#ffb86b"), (1, "#e2553b")], user=True, y2=360)
    scene = '<rect width="512" height="512" fill="url(#dusk)"/><circle cx="256" cy="210" r="96" fill="#fff0c9"/>'
    scene += centred(S.bamboo(P(a="#2d6a4f", b="#40916c", k="#10261c")), 110, 220, 250) + centred(
        S.bamboo(P(a="#2d6a4f", b="#40916c", k="#10261c")), 410, 240, 230
    )
    scene += '<rect y="320" width="512" height="200" fill="#10261c"/>'
    return L.emblem(
        scene,
        "MARTIAL ARTS",
        font="Anton",
        ink="#fff",
        band="#c1121f",
        rim="#fff0c9",
        edge="#10261c",
        ls=4,
    )


genre("Martial Arts", "martial-arts")(("belt", ma_belt), ("enso", ma_enso), ("bamboo", ma_bamboo))


# ======================================================================= Mini-Series


def mini_parts():
    d = SH
    body = ""
    for i, (x, c) in enumerate(((120, "#3a86ff"), (256, "#ff006e"), (392, "#ffbe0b"))):
        body += f'<g filter="url(#sh)"><rect x="{x - 58}" y="70" width="116" height="140" rx="16" fill="{c}" stroke="#14142b" stroke-width="7"/></g>'
        body += fit(
            text(str(i + 1), "Archivo Black", 100, fill="#fff", stroke="#14142b", sw=8),
            x - 38,
            88,
            76,
            104,
        )
        body += (
            fit(text("PART", "Oswald", 30, weight=700, fill="#14142b"), x - 30, 218, 60, 18)
            if False
            else ""
        )
    body += f'<g filter="url(#sh)">{fit(text("MINI-SERIES", "Archivo Black", 100, fill="#fff", stroke="#14142b", sw=14), 24, 250, 464, 110)}</g>'
    body += fit(
        text(
            "ONE STORY · A FEW NIGHTS",
            "Oswald",
            40,
            weight=700,
            fill="#ffbe0b",
            stroke="#14142b",
            sw=8,
            ls=4,
        ),
        90,
        382,
        332,
        36,
    )
    return svg(body, d)


def mini_film():
    return L.film_frame(
        "MINI-SERIES",
        "PART ONE OF THREE",
        font="Bebas Neue",
        ink="#14142b",
        film="#14142b",
        frame_fill="#ffe8b3",
    )


def mini_ticket():
    return L.ticket(
        "MINI-SERIES",
        "EVENT TELEVISION",
        font="Oswald",
        weight=700,
        ink="#14142b",
        paper="#fff3c4",
        edge="#14142b",
        accent="#d62828",
    )


genre("Mini-Series", "mini-series")(
    ("parts", mini_parts), ("film", mini_film), ("ticket", mini_ticket)
)


# ======================================================================= Music


def music_vinyl():
    d = SH
    body = (
        '<g filter="url(#sh)">' + centred(S.vinyl(P(a="#ff7b00", l="#111")), 256, 256, 470) + "</g>"
    )
    body += '<circle cx="256" cy="256" r="98" fill="#ff7b00"/><circle cx="256" cy="256" r="98" fill="none" stroke="#fff" stroke-width="3" opacity=".6"/>'
    body += fit(text("MUSIC", "Righteous", 100, fill="#fff"), 180, 226, 152, 50)
    body += '<circle cx="256" cy="292" r="7" fill="#111"/>'
    return svg(body, d)


def music_headphones():
    p = P(a="#7b2ff7", b="#f107a3", k="#12082b")
    return L.sym_word(
        S.headphones(p),
        "MUSIC",
        font="Righteous",
        ink="#fff",
        edge="#12082b",
        sw=14,
        ls=6,
        sub="TURN IT UP",
        sub_font="Righteous",
        sub_ink="#f107a3",
    )


def music_eq():
    p = P(a="#2ec4b6", b="#ffbf69", c="#ff5d8f")
    return L.sym_word(
        S.eq_bars(p),
        "MUSIC",
        font="Monoton",
        ink="#ff5d8f",
        edge="#150a1f",
        sw=10,
        ls=4,
        sub="VIDEOS · LIVE · CONCERTS",
        sub_font="Oswald",
        sub_ink="#2ec4b6",
        sym_box=(96, 30, 320, 240),
    )


genre("Music")(("vinyl", music_vinyl), ("headphones", music_headphones), ("equalizer", music_eq))


# ======================================================================= Musical


def musical_tophat():
    p = P(a="#c1121f", l="#fff", k="#0e0e12")
    sym = (
        '<circle cx="100" cy="100" r="96" fill="#f2c14e" stroke="#0e0e12" stroke-width="8"/>'
        + centred(S.tophat(p), 96, 104, 160)
    )
    return L.sym_word(
        sym,
        "MUSICALS",
        font="Limelight",
        ink="#f2c14e",
        edge="#0e0e12",
        sw=14,
        ls=4,
        sub="SONG & DANCE",
        sub_font="Poiret One",
        sub_ink="#fff",
        sym_box=(146, 20, 220, 250),
    )


def musical_marquee():
    return L.marquee(
        "MUSICALS", "SHOW TUNES", crest="★ ★ ★", crest_ink="#fff3b0", frame="#b3121f", font="Oswald"
    )


def musical_keys():
    keys = ""
    for i in range(14):
        keys += f'<rect x="{46 + i * 30}" y="330" width="30" height="72" fill="#fff" stroke="#141414" stroke-width="3"/>'
    for i in (0, 1, 3, 4, 5, 7, 8, 10, 11, 12):
        keys += f'<rect x="{46 + i * 30 + 20}" y="330" width="20" height="44" fill="#141414"/>'
    return L.script_card(
        "Musicals",
        None,
        card="#3a0ca3",
        card2="#240046",
        edge="#141414",
        ink="#ffd60a",
        script_font="Great Vibes",
        shape="pill",
        deco=keys,
        tilt=-4,
    )


genre("Musical")(("top hat", musical_tophat), ("marquee", musical_marquee), ("piano", musical_keys))


# ======================================================================= Mystery


def mystery_magnifier():
    p = P(a="#6a4c93", b="#c9a24a", c="#b8e0ff", l="#fff", k="#1a1330")
    return L.sym_word(
        S.magnifier(p),
        "MYSTERY",
        font="Playfair Display",
        weight=900,
        ink="#fff",
        edge="#1a1330",
        sw=14,
        ls=4,
        sub="WHODUNIT?",
        sub_font="Special Elite",
        sub_ink="#c9a24a",
    )


def mystery_keyhole():
    p = P(a="#2d6a4f", b="#d4a93a", k="#081c15")
    centre = centred(S.keyhole(p), 256, 170, 210)
    return L.roundel(
        centre,
        "MYSTERY",
        font="Cinzel",
        weight=900,
        ink="#d4a93a",
        disc="#1b4332",
        rim="#d4a93a",
        edge="#081c15",
        bar="#081c15",
        bar_y=296,
        ls=6,
    )


def mystery_qmark():
    d = SH + rad("fog", [(0, "#4a3f6b"), (1, "#16122a")], r=0.7)
    body = '<g filter="url(#sh)"><rect x="36" y="36" width="440" height="440" rx="40" fill="url(#fog)"/></g>'
    body += fit(
        text("?", "Abril Fatface", 100, fill="#9bd18b", stroke="#0b0a14", sw=6), 190, 60, 132, 230
    )
    body += fit(text("MYSTERY", "Abril Fatface", 100, fill="#fff", ls=4), 70, 312, 372, 92)
    body += fit(
        text("THEATRE", "Montserrat", 40, weight=700, fill="#9bd18b", ls=14), 170, 414, 172, 24
    )
    return svg(body, d)


genre("Mystery")(
    ("magnifier", mystery_magnifier), ("keyhole", mystery_keyhole), ("question mark", mystery_qmark)
)


# ======================================================================= News


def news_globe():
    p = P(a="#1d4ed8", l="#dbeafe", k="#0b1633")
    d = SH
    body = f'<g filter="url(#sh)">{fit(S.globe(p), 146, 20, 220, 220)}</g>'
    body += f'<g filter="url(#sh)">{fit(text("NEWS", "Montserrat", 100, weight=900, fill="#fff", stroke="#0b1633", sw=14, ls=4), 44, 256, 424, 118)}</g>'
    body += '<g filter="url(#sh)"><rect x="96" y="392" width="320" height="52" rx="6" fill="#dc2626" stroke="#0b1633" stroke-width="6"/></g>'
    body += fit(
        text("24 HOURS", "Montserrat", 40, weight=800, fill="#fff", ls=8), 128, 402, 256, 32
    )
    return svg(body, d)


def news_mic():
    p = P(a="#9ca3af", l="#e5e7eb", k="#111827")
    centre = centred(S.mic_vintage(p), 256, 170, 220)
    return L.roundel(
        centre,
        "NEWS",
        font="Oswald",
        weight=700,
        ink="#fff",
        disc="#1e3a8a",
        rim="#fff",
        edge="#0b1633",
        bar="#dc2626",
        bar_y=294,
        ls=18,
    )


def news_paper():
    return L.masthead(
        "The News",
        "ALL THE HEADLINES · MORNING AND NIGHT",
        sym=S.globe(P(a="#fff", l="#b3121f", k="#141414")),
    )


genre("News")(("globe", news_globe), ("microphone", news_mic), ("newspaper", news_paper))


# ======================================================================= Reality


def reality_rec():
    d = SH
    body = '<g filter="url(#sh)"><rect x="24" y="84" width="464" height="344" rx="34" fill="#101218"/></g>'
    for x, y, sx, sy in ((56, 116, 1, 1), (456, 116, -1, 1), (56, 396, 1, -1), (456, 396, -1, -1)):
        body += f'<path d="M{x} {y + 44 * sy} L{x} {y} L{x + 44 * sx} {y}" fill="none" stroke="#fff" stroke-width="7"/>'
    body += '<circle cx="96" cy="152" r="12" fill="#ff2d3d"/>' + text(
        "REC", "Oswald", 34, weight=700, fill="#fff", x=116, y=164, anchor="start"
    )
    body += '<rect x="384" y="140" width="46" height="24" rx="3" fill="none" stroke="#fff" stroke-width="4"/><rect x="430" y="146" width="5" height="12" fill="#fff"/><rect x="389" y="145" width="30" height="14" fill="#fff"/>'
    body += fit(
        text("REALITY", "Montserrat", 100, weight=900, fill="#fff", ls=2), 70, 204, 372, 100
    )
    body += fit(text("00:00:17:42", "VT323", 60, fill="#ffd23f", ls=4), 176, 330, 160, 44)
    return svg(body, d)


def reality_cam():
    P(a="#ff2d3d", c="#3a86ff", k="#101218")
    centre = centred(S.camcorder(P(a="#ff2d3d", c="#5aa9ff", k="#fff")), 256, 176, 230)
    return L.roundel(
        centre,
        "REALITY TV",
        font="Montserrat",
        weight=900,
        ink="#fff",
        disc="#101218",
        rim="#ff2d3d",
        edge="#050608",
        bar="#ff2d3d",
        bar_y=296,
    )


def reality_blocks():
    return L.block_word(
        [("REALITY", "#ff006e", "#fff"), ("NO SCRIPT", "#fff", "#141414")],
        font="Montserrat",
        weight=900,
        edge="#141414",
        tilt=-5,
    )


genre("Reality")(("rec", reality_rec), ("camcorder", reality_cam), ("blocks", reality_blocks))


# ======================================================================= Romance


def romance_heart():
    d = SH + lin("h", [(0, "#ff5c8a"), (1, "#c9184a")])
    body = f'<g filter="url(#sh)">{centred(S.heart(P(a="url(#h)", l="#fff", k="#590d22")), 256, 250, 460)}</g>'
    body += fit(
        f'<g transform="rotate(-8)">{text("Romance", "Great Vibes", 100, fill="#fff", stroke="#590d22", sw=10)}</g>',
        70,
        170,
        372,
        150,
    )
    return svg(body, d)


def romance_rose():
    p = P(a="#d62246", l="#fff", k="#3b0a17")
    return L.sym_word(
        S.rose(p),
        "ROMANCE",
        font="Playfair Display",
        weight=700,
        style="italic",
        ink="#fff",
        edge="#3b0a17",
        sw=14,
        sub="LOVE STORIES",
        sub_font="Playfair Display",
        sub_ink="#ffb3c6",
        sym_box=(146, 16, 220, 270),
    )


def romance_letter():
    p = P(a="#d62246", l="#fff8f0", k="#3b0a17")
    return L.postage(
        S.envelope(p),
        "ROMANCE",
        "14",
        font="Playfair Display",
        weight=900,
        ink="#3b0a17",
        paper="#fff8f0",
        field="#ffc2d1",
        edge="#3b0a17",
    )


genre("Romance")(("heart", romance_heart), ("rose", romance_rose), ("love letter", romance_letter))


# ======================================================================= Science Fiction


def scifi_atomic():
    d = (
        rad("pl", [(0, "#9ff2e0"), (0.55, "#22a891"), (1, "#0b4b45")], cx=0.35, cy=0.3, r=0.8)
        + lin("letters", [(0, "#fffbe0"), (0.5, "#ffe066"), (1, "#ff9f1c")])
        + SH
    )
    body = '<g filter="url(#sh)">'
    body += centred(S.sparkle(P(), "#fff4b0"), 360, 120, 150)
    body += '<g transform="rotate(-18 230 190)">'
    body += (
        '<path d="M60 190 A170 46 0 0 1 400 190" fill="none" stroke="#e44d8a" stroke-width="18"/>'
    )
    body += '<circle cx="230" cy="190" r="122" fill="url(#pl)" stroke="#073532" stroke-width="5"/>'
    body += (
        '<path d="M60 190 A170 46 0 0 0 400 190" fill="none" stroke="#073532" stroke-width="28"/>'
    )
    body += (
        '<path d="M60 190 A170 46 0 0 0 400 190" fill="none" stroke="#e44d8a" stroke-width="18"/>'
    )
    body += "</g>"
    for x, y, r in ((90, 80, 5), (130, 40, 3), (440, 250, 4), (60, 280, 3)):
        body += f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff4b0"/>'
    body += "</g>"
    word = text("SCI-FI", "Bungee", 100, fill="url(#letters)")
    inner = (
        extrude(word, 8, 10, 12, "#0b3b53")
        + text("SCI-FI", "Bungee", 100, fill="#0b3b53", stroke="#0b3b53", sw=10)
        + word
    )
    body += fit(f'<g transform="skewX(-10)">{inner}</g>', 26, 300, 460, 150)
    return svg(body, d)


def scifi_modern():
    d = (
        lin("g", [(0, "#39d5ff"), (0.5, "#5b7cff"), (1, "#b04bff")], x2=1, y2=0)
        + lin("pl", [(0, "#39d5ff"), (1, "#7a4bff")], x1=0.2, y1=0, x2=0.8, y2=1)
        + lin(
            "ring",
            [(0, "#39d5ff00"), (0.25, "#8ff0ff"), (0.75, "#d9a8ff"), (1, "#b04bff00")],
            x2=1,
            y2=0,
        )
        + glow("gl", "#aef4ff", blur=7, strength=2)
        + shadow("sh", dy=4, blur=5, opacity=0.5, color="#050818")
    )
    body = '<g filter="url(#sh)">'
    body += '<circle cx="256" cy="160" r="104" fill="#0b1236"/><circle cx="256" cy="160" r="96" fill="url(#pl)"/>'
    body += '<path d="M168 128 A96 96 0 0 1 330 102" fill="none" stroke="#e8fbff" stroke-width="6" stroke-linecap="round" opacity=".55"/>'
    body += '<g transform="rotate(-16 256 170)"><path d="M60 170 A196 44 0 0 0 452 170" fill="none" stroke="#0b1236" stroke-width="16"/>'
    body += '<path d="M60 170 A196 44 0 0 0 452 170" fill="none" stroke="url(#ring)" stroke-width="7"/></g>'
    body += '<circle cx="424" cy="134" r="10" fill="#f2fdff" filter="url(#gl)"/></g>'
    letters = text("SCI-FI", "Michroma", 100, fill="url(#g)", stroke="#0b1236", sw=12, ls=2)
    body += f'<g filter="url(#sh)">{fit(letters, 36, 300, 440, 104)}</g>'
    body += fit(
        text("CHANNEL", "Michroma", 30, fill="#ffffff", spacing=16, stroke="#0b1236", sw=8)
        if False
        else text("CHANNEL", "Michroma", 30, fill="#fff", ls=16, stroke="#0b1236", sw=8),
        146,
        420,
        220,
        26,
    )
    return svg(body, d)


def scifi_grid():
    d = (
        lin("sun", [(0, "#ffe45c"), (0.5, "#ff7a59"), (1, "#ff2d95")])
        + lin("skyg", [(0, "#120533"), (1, "#3b0b5c")])
        + "<clipPath id='cp'><circle cx='256' cy='236' r='200'/></clipPath><clipPath id='sunc'><circle cx='256' cy='214' r='118'/></clipPath>"
    )
    back = '<g filter="url(#sh)"><circle cx="256" cy="236" r="206" fill="#ff2d95"/>'
    back += '<g clip-path="url(#cp)"><rect width="512" height="512" fill="url(#skyg)"/>'
    back += '<circle cx="256" cy="214" r="118" fill="url(#sun)"/><g clip-path="url(#sunc)">'
    for i, y in enumerate((200, 224, 246, 266, 284, 300)):
        back += f'<rect x="120" y="{y}" width="272" height="{2 + i * 1.8:.1f}" fill="#2a0a52"/>'
    back += '</g><rect x="0" y="304" width="512" height="220" fill="#1a0638"/>'
    for i in range(-10, 11):
        back += f'<line x1="{256 + i * 18}" y1="304" x2="{256 + i * 90}" y2="470" stroke="#ff4fd8" stroke-width="2.4"/>'
    y = 304
    for k in range(8):
        y += 6 + k * 6
        back += f'<line x1="0" y1="{y}" x2="512" y2="{y}" stroke="#ff4fd8" stroke-width="2.4"/>'
    back += '<line x1="0" y1="304" x2="512" y2="304" stroke="#ffd1f5" stroke-width="3"/></g></g>'
    return L.chrome("SCI-FI", None, back=back, defs=d, box=(76, 300, 360, 116))


genre("Science Fiction", "science-fiction")(
    ("atomic age", scifi_atomic), ("modern", scifi_modern), ("80s", scifi_grid)
)


# ======================================================================= Short


def short_stopwatch():
    p = P(a="#ff7b00", b="#ffd166", l="#fff", k="#1a1a2e")
    return L.sym_word(
        S.stopwatch(p),
        "SHORTS",
        font="Archivo Black",
        ink="#fff",
        edge="#1a1a2e",
        sw=14,
        ls=4,
        sub="SHORT FILMS",
        sub_font="Archivo Black",
        sub_ink="#ffd166",
        sym_box=(136, 16, 240, 270),
    )


def short_film():
    return L.film_frame(
        "SHORTS",
        "SHORT FILM SHOWCASE",
        font="Archivo Black",
        ink="#1a1a2e",
        film="#1a1a2e",
        frame_fill="#ffd166",
    )


def short_ticket():
    return L.ticket(
        "SHORTS",
        "BITE-SIZE FILMS",
        font="Archivo Black",
        ink="#1a1a2e",
        paper="#e0fbfc",
        edge="#1a1a2e",
        accent="#ee6c4d",
        tilt=6,
    )


genre("Short")(("stopwatch", short_stopwatch), ("film", short_film), ("ticket", short_ticket))


# ======================================================================= Soap


def soap_bubbles():
    p = P(a="#ff5fa2", c="#b8f2ff", l="#fff", k="#3a0f2e")
    return L.sym_word(
        S.bubbles(p),
        "Soaps",
        font="Pacifico",
        ink="#fff",
        edge="#3a0f2e",
        sw=14,
        sub="DAYTIME DRAMA",
        sub_font="Oswald",
        sub_ink="#ff9ecb",
        sym_box=(116, 16, 280, 250),
        word_box=(60, 262, 392, 152),
    )


def soap_coupes():
    p = P(a="#ffd166", b="#fff3c4", k="#2a0f24")
    d = SH + rad("g", [(0, "#8e2c68"), (1, "#3a0f2e")], r=0.7)
    body = '<g filter="url(#sh)"><circle cx="256" cy="256" r="232" fill="url(#g)" stroke="#ffd166" stroke-width="6"/></g>'
    body += fit(S.coupes(p), 146, 60, 220, 190)
    body += fit(
        text("Soap Opera", "Playfair Display", 100, weight=700, style="italic", fill="#fff"),
        80,
        262,
        352,
        90,
    )
    body += fit(
        text("SCANDAL · ROMANCE · SECRETS", "Oswald", 40, weight=600, fill="#ffd166", ls=3),
        110,
        370,
        292,
        24,
    )
    return svg(body, d)


def soap_daytime():
    return L.script_card(
        "Daytime",
        "SOAP OPERAS",
        card="#ffb3c6",
        card2="#ff85a1",
        edge="#3a0f2e",
        ink="#fff",
        script_font="Great Vibes",
        shape="oval",
        sub_ink="#fff",
        tilt=-6,
    )


genre("Soap")(("bubbles", soap_bubbles), ("champagne", soap_coupes), ("daytime", soap_daytime))


# ======================================================================= Sport


def sport_trophy():
    p = P(a="#1d3557", b="#ffc300", l="#fff", k="#0b1a2e")
    return L.sym_word(
        S.trophy(p),
        "SPORTS",
        font="Graduate",
        ink="#fff",
        edge="#0b1a2e",
        sw=14,
        ls=4,
        sub="GAME DAY",
        sub_font="Graduate",
        sub_ink="#ffc300",
        sym_box=(136, 16, 240, 270),
    )


def sport_stadium():
    d = lin("nt", [(0, "#0b1a3a"), (1, "#23407a")], user=True, y2=320)
    scene = '<rect width="512" height="512" fill="url(#nt)"/>'
    for x in (120, 392):
        scene += f'<polygon points="{x - 40},110 {x + 40},110 {x + 170},330 {x - 170},330" fill="#fff" opacity=".08"/>'
        scene += centred(S.stadium_lights(P(l="#fff8d6", k="#0b1020")), x, 130, 130)
    scene += '<path d="M40 330 Q256 280 472 330 L472 520 L40 520 Z" fill="#2f9e44"/>'
    for x in range(60, 480, 44):
        scene += f'<line x1="{x}" y1="316" x2="{256 + (x - 256) * 1.6:.0f}" y2="400" stroke="#fff" stroke-width="3" opacity=".6"/>'
    scene += '<rect x="40" y="306" width="432" height="18" fill="#0b1020"/>'
    return L.emblem(
        scene,
        "SPORTS",
        font="Bebas Neue",
        ink="#fff",
        band="#c1121f",
        rim="#fff",
        edge="#0b1020",
        defs=d,
        ls=14,
    )


def sport_varsity():
    return L.varsity(
        "SPORTS",
        S.ball(P(a="#f77f00", k="#1d1a2b"), "basket"),
        fill="#fff",
        outline="#c1121f",
        edge="#0b1a2e",
        felt="#1d3557",
        sub="CLASSIC GAMES",
    )


genre("Sport", "sport")(
    ("trophy", sport_trophy), ("stadium", sport_stadium), ("varsity", sport_varsity)
)


# ======================================================================= Suspense


def suspense_clock():
    p = P(a="#c1121f", l="#f1f1ec", k="#0d0d0d")
    return L.sym_word(
        S.clock(p),
        "SUSPENSE",
        font="Bebas Neue",
        ink="#fff",
        edge="#0d0d0d",
        sw=12,
        ls=6,
        sub="EDGE OF YOUR SEAT",
        sub_font="Oswald",
        sub_ink="#c1121f",
        sym_box=(146, 18, 220, 240),
        word_box=(30, 276, 452, 128),
    )


def suspense_eye():
    p = P(a="#2a9d8f", l="#f1f1ec", k="#0d0d0d")
    centre = centred(S.eye(p), 256, 170, 280)
    return L.roundel(
        centre,
        "SUSPENSE",
        font="Bebas Neue",
        ink="#fff",
        disc="#1b1b1f",
        rim="#c1121f",
        edge="#050505",
        bar="#0d0d0d",
        bar_y=296,
        ls=10,
    )


def suspense_fuse():
    d = SH + glow("sp", "#ffd23f", blur=8, strength=2)
    body = '<g filter="url(#sh)"><rect x="24" y="120" width="464" height="272" rx="22" fill="#141418"/></g>'
    body += fit(text("SUSPENSE", "Bebas Neue", 100, fill="#fff", ls=6), 60, 150, 392, 130)
    body += '<path d="M70 330 Q160 300 250 330 T420 318" fill="none" stroke="#b08968" stroke-width="7" stroke-dasharray="14 6" stroke-linecap="round"/>'
    body += '<path d="M70 330 Q160 300 250 330" fill="none" stroke="#444" stroke-width="7" stroke-linecap="round"/>'
    body += f'<g filter="url(#sp)">{centred(S.sparkle(P(), "#ffd23f"), 250, 330, 60)}<circle cx="250" cy="330" r="8" fill="#fff"/></g>'
    return svg(body, d)


genre("Suspense")(("clock", suspense_clock), ("eye", suspense_eye), ("fuse", suspense_fuse))


# ======================================================================= Talk Show


def talk_skyline():
    rng = random.Random(5)
    d = lin("nt", [(0, "#1b1f4b"), (1, "#5a3d8a")], user=True, y2=330)
    scene = '<rect width="512" height="512" fill="url(#nt)"/><circle cx="380" cy="100" r="30" fill="#fff4d6"/>'
    x = 40
    while x < 480:
        w = rng.choice((36, 44, 52))
        h = rng.choice((90, 130, 170, 110, 150))
        scene += f'<rect x="{x}" y="{330 - h}" width="{w}" height="{h}" fill="#141733"/>'
        for wy in range(330 - h + 12, 320, 18):
            for wx in range(x + 8, x + w - 8, 12):
                if rng.random() < 0.45:
                    scene += f'<rect x="{wx}" y="{wy}" width="5" height="8" fill="#ffd166"/>'
        x += w + 4
    scene += '<rect y="300" width="512" height="200" fill="#6b3b1f"/><rect y="300" width="512" height="12" fill="#8a5a2b"/>'
    scene += centred(S.mic(P(a="#e63946", l="#e9eef3", k="#0e0e12")), 256, 240, 120)
    return L.emblem(
        scene,
        "TALK SHOW",
        font="Oswald",
        weight=700,
        ink="#fff",
        band="#e63946",
        rim="#ffd166",
        edge="#0e0e12",
        defs=d,
        ls=6,
    )


def talk_bubbles():
    p = P(a="#3a86ff", b="#ff006e", l="#fff", k="#14142b")
    return L.sym_word(
        S.speech(p),
        "TALK",
        font="Archivo Black",
        ink="#fff",
        edge="#14142b",
        sw=14,
        ls=8,
        sub="LATE NIGHT & DAYTIME",
        sub_font="Oswald",
        sub_ink="#ffbe0b",
        sym_box=(116, 18, 280, 250),
    )


def talk_chairs():
    p = P(a="#e76f51", b="#2a9d8f", l="#f1faee", k="#1d1a2b")
    centre = centred(S.armchairs(p), 256, 176, 240)
    return L.roundel(
        centre,
        "TALK SHOW",
        font="Archivo Black",
        ink="#1d1a2b",
        disc="#f4d35e",
        rim="#fff",
        edge="#1d1a2b",
        bar="#f1faee",
        bar_y=292,
        ls=2,
    )


genre("Talk Show", "talk-show")(
    ("skyline", talk_skyline), ("speech bubbles", talk_bubbles), ("armchairs", talk_chairs)
)


# ======================================================================= Thriller


def thriller_pulse():
    d = SH + glow("gl", "#ff2d3d", blur=6, strength=2)
    body = '<g filter="url(#sh)"><rect x="24" y="120" width="464" height="272" rx="22" fill="#0b0b0e"/></g>'
    body += fit(text("THRILLER", "Anton", 100, fill="#fff", ls=4), 56, 170, 400, 110)
    body += '<g filter="url(#gl)"><polyline points="40,330 150,330 176,300 198,362 226,262 254,392 280,318 300,330 472,330" fill="none" stroke="#ff2d3d" stroke-width="8" stroke-linejoin="round" stroke-linecap="round"/></g>'
    return svg(body, d)


def thriller_spiral():
    P(a="#ff2d3d")
    sym = (
        '<circle cx="100" cy="100" r="96" fill="#f1f1ec" stroke="#0b0b0e" stroke-width="8"/>'
        + centred(S.spiral(P(a="#0b0b0e")), 100, 100, 176)
    )
    return L.sym_word(
        sym,
        "THRILLER",
        font="Anton",
        ink="#fff",
        edge="#0b0b0e",
        sw=12,
        ls=4,
        sub="NO ONE IS SAFE",
        sub_font="Oswald",
        sub_ink="#ff2d3d",
        sym_box=(146, 18, 220, 240),
        word_box=(30, 276, 452, 128),
    )


def thriller_glass():
    d = SH
    body = '<g filter="url(#sh)"><rect x="24" y="80" width="464" height="352" rx="22" fill="#141821"/></g>'
    body += centred(S.shatter(P(a="#9fb3c8")), 256, 256, 420)
    body += f'<g filter="url(#sh)">{fit(text("THRILLER", "Anton", 100, fill="#fff", stroke="#141821", sw=10, ls=4), 56, 196, 400, 120)}</g>'
    return svg(body, d)


genre("Thriller")(
    ("heartbeat", thriller_pulse), ("spiral", thriller_spiral), ("shattered", thriller_glass)
)


# ======================================================================= Travel


def travel_plane():
    p = P(a="#2a9d8f", l="#e9f5f3", k="#12312d")
    sym = (
        centred(S.globe(p), 100, 106, 160)
        + '<path d="M16 120 A92 44 0 0 1 184 70" fill="none" stroke="#fff" stroke-width="5" stroke-dasharray="10 8" transform="rotate(-10 100 100)"/>'
    )
    sym += centred(
        S.airplane(P(a="#e76f51", c="#264653", l="#fff", k="#12312d")), 176, 52, 64
    ).replace("scale", "rotate(60) scale", 0)
    return L.sym_word(
        sym,
        "TRAVEL",
        font="Alfa Slab One",
        ink="#fff",
        edge="#12312d",
        sw=14,
        ls=6,
        sub="SEE THE WORLD",
        sub_font="Oswald",
        sub_ink="#f4a261",
        sym_box=(126, 14, 260, 256),
    )


def travel_stamp():
    p = P(a="#264653", b="#f4a261", c="#2a9d8f", l="#fff", k="#12312d")
    return L.postage(
        S.mountains(p),
        "TRAVEL",
        "25",
        font="Alfa Slab One",
        ink="#12312d",
        paper="#fdf6e3",
        field="#bde0fe",
        edge="#12312d",
    )


def travel_tag():
    p = P(a="#e76f51", b="#f4a261", c="#2a9d8f", l="#fff", k="#12312d")
    return L.tag(
        "TRAVEL",
        "BON VOYAGE",
        font="Alfa Slab One",
        ink="#12312d",
        paper="#f4d35e",
        edge="#12312d",
        sym=S.suitcase(p),
    )


genre("Travel")(
    ("plane", travel_plane), ("postage stamp", travel_stamp), ("luggage tag", travel_tag)
)


# ======================================================================= War


def war_stencil():
    d = SH
    body = '<g filter="url(#sh)"><rect x="28" y="96" width="456" height="320" rx="14" fill="#4b5320" stroke="#22260e" stroke-width="8"/></g>'
    body += '<rect x="44" y="112" width="424" height="288" rx="6" fill="none" stroke="#c9c19a" stroke-width="3" stroke-dasharray="12 8"/>'
    body += f'<circle cx="126" cy="256" r="64" fill="none" stroke="#e8e2c4" stroke-width="8"/><polygon points="{star(126, 260, 56, 22)}" fill="#e8e2c4"/>'
    body += fit(text("WAR", "Black Ops One", 100, fill="#e8e2c4"), 210, 170, 240, 110)
    body += fit(text("STORIES", "Black Ops One", 40, fill="#e8e2c4", ls=10), 212, 296, 236, 44)
    return svg(body, d)


def war_medal():
    p = P(a="#1d3557", b="#d4a93a", c="#c1121f", l="#fff3c4", k="#141414")
    return L.sym_word(
        S.medal(p),
        "WAR STORIES",
        font="Black Ops One",
        ink="#e8e2c4",
        edge="#141414",
        sw=12,
        sub="HONOR · COURAGE",
        sub_font="Oswald",
        sub_ink="#d4a93a",
        sym_box=(146, 14, 220, 270),
        word_box=(30, 294, 452, 110),
    )


def war_biplanes():
    d = lin("sky", [(0, "#f4d58d"), (1, "#bf8b67")], user=True, y2=340)
    scene = '<rect width="512" height="512" fill="url(#sky)"/>'
    for x, y, s, r in ((180, 170, 150, -12), (330, 110, 90, -8), (390, 230, 70, -10)):
        scene += f'<g transform="rotate({r} {x} {y})">{centred(S.biplane(P(a="#4b5320", b="#6b7a33", l="#e8e2c4", k="#22260e")), x, y, s)}</g>'
    scene += (
        '<path d="M40 330 Q150 300 256 318 Q380 300 472 326 L472 520 L40 520 Z" fill="#6b5a3a"/>'
    )
    return L.emblem(
        scene,
        "WAR",
        font="Black Ops One",
        ink="#e8e2c4",
        band="#4b5320",
        rim="#e8e2c4",
        edge="#22260e",
        defs=d,
        ls=20,
    )


genre("War")(("stencil", war_stencil), ("medal", war_medal), ("biplanes", war_biplanes))


# ======================================================================= Western


def western_poster():
    return L.poster(
        "THE", "WESTERN", "CHANNEL", font="Holtwood One SC", small_font="Rye", ink="#3a2210"
    )


def western_badge():
    d = lin("gold", [(0, "#fff1b8"), (0.35, "#f1c24b"), (0.7, "#c98a12"), (1, "#8a5a06")]) + lin(
        "gold2", [(0, "#b27b0d"), (1, "#f5d266")]
    )
    back = f'<polygon points="{star(256, 250, 222, 118, n=6)}" fill="url(#gold)" stroke="#6b4304" stroke-width="5" stroke-linejoin="round"/>'
    for k in range(6):
        a = math.radians(-90 + k * 60)
        back += f'<circle cx="{256 + 222 * math.cos(a):.1f}" cy="{250 + 222 * math.sin(a):.1f}" r="22" fill="url(#gold)" stroke="#6b4304" stroke-width="5"/>'
    back += (
        '<circle cx="256" cy="250" r="112" fill="url(#gold2)" stroke="#6b4304" stroke-width="4"/>'
    )
    back += '<circle cx="256" cy="250" r="98" fill="none" stroke="#fff3c4" stroke-width="2" stroke-dasharray="3 7" opacity=".8"/>'
    back += f'<polygon points="{star(256, 196, 34, 14)}" fill="#fff1b8" stroke="#6b4304" stroke-width="3" stroke-linejoin="round"/>'
    back += f'<polygon points="{star(256, 318, 22, 9)}" fill="#fff1b8" stroke="#6b4304" stroke-width="3" stroke-linejoin="round"/>'
    return L.ribbon_badge(
        back,
        "WESTERN",
        font="Rye",
        ink="#fff3d6",
        band="#a4161a",
        band_dark="#6e1010",
        edge="#4a0b0b",
        defs=d,
    )


def western_sunset():
    d = (
        lin("sky", [(0, "#ffd66b"), (0.45, "#ff8a3d"), (1, "#c2272d")], user=True, y1=24, y2=404)
        + "<clipPath id='sunc'><circle cx='256' cy='250' r='118'/></clipPath>"
    )
    scene = '<rect x="0" y="0" width="512" height="512" fill="url(#sky)"/>'
    scene += '<circle cx="256" cy="250" r="118" fill="#fff0b3"/><g clip-path="url(#sunc)">'
    for i, y in enumerate((224, 246, 266, 284, 300, 314)):
        scene += f'<rect x="120" y="{y}" width="272" height="{3 + i * 1.7:.1f}" fill="url(#sky)"/>'
    scene += "</g>"
    scene += (
        '<path d="M40 332 L70 318 L88 318 L96 262 L104 256 L150 256 L158 262 L164 300 L186 318 L200 332 Z" fill="#6e2a16"/>'
        '<path d="M268 332 L294 312 L304 238 L314 230 L380 230 L388 238 L398 296 L430 318 L472 332 Z" fill="#5a2211"/>'
        '<path d="M392 300 L404 282 L446 282 L452 300 L470 320 L380 320 Z" fill="#6e2a16"/>'
    )
    scene += '<path d="M40 330 C140 318 360 322 480 334 L480 440 L40 440 Z" fill="#2b1409"/>'
    scene += (
        '<g fill="#2b1409" transform="translate(196 214)"><rect x="-11" y="0" width="22" height="120" rx="11"/>'
        '<path d="M-11 66 L-28 66 Q-40 66 -40 54 L-40 24 Q-40 15 -33 15 Q-26 15 -26 24 L-26 51 L-11 51 Z"/>'
        '<path d="M11 50 L26 50 Q38 50 38 38 L38 8 Q38 -1 31 -1 Q24 -1 24 8 L24 36 L11 36 Z"/></g>'
    )
    return L.emblem(
        scene,
        "WESTERN",
        font="Rye",
        ink="#fbe3b0",
        band="#2b1409",
        rim="#fbe3b0",
        edge="#2b1409",
        defs=d,
    )


genre("Western")(
    ("poster", western_poster), ("sheriff star", western_badge), ("sunset", western_sunset)
)


def logos() -> list[Logo]:
    out = []
    for name, stem, designs in GENRES:
        for n, (variant, draw) in enumerate(designs, start=1):
            out.append(
                Logo(
                    f"{stem}-{variant.replace(' ', '-')}",
                    f"{name} · {variant}",
                    "Genres",
                    draw,
                    [name.lower(), variant],
                )
            )
    return out
