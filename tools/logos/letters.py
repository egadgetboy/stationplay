"""Letters A-Z and numbers 1-50, in two matched sets: modern (a bold
character in a badge, like a local station's number) and retro (a chunky
italic character over 70s/80s stripes)."""

from __future__ import annotations

from kit import Logo, extrude, fit, lin, shadow, svg, text

# (light, main, dark) of each modern badge
MODERN = [
    ("#ff5a5a", "#d0161f", "#6a0a0e"),  # red
    ("#4b95ff", "#1546c8", "#0a2266"),  # blue
    ("#3fd07a", "#128a3e", "#07401c"),  # green
    ("#ffb347", "#e2620d", "#6e2c03"),  # orange
    ("#ad7bff", "#6320d0", "#2e0b6b"),  # purple
    ("#35d9c8", "#0b8f86", "#044540"),  # teal
    ("#ffd84d", "#d99a06", "#6b4a00"),  # gold
    ("#ff6fb0", "#c8186a", "#5e0833"),  # magenta
    ("#5f7bb3", "#233a73", "#0d1936"),  # navy
    ("#8fa0b5", "#4a5a70", "#1c2430"),  # slate
]
SHAPES = ["circle", "shield", "screen", "hexagon", "diamond"]


def _shape(shape: str, inset: float) -> str:
    if shape == "circle":
        return f'<circle cx="256" cy="256" r="{236 - inset}"/>'
    if shape == "shield":
        L, R = 46 + inset, 466 - inset
        return (
            f'<path d="M256 {26 + inset * 1.2} L{R} {92 + inset} L{R} 290 '
            f'Q{R} {418 - inset * 0.6} 256 {490 - inset * 1.3} Q{L} {418 - inset * 0.6} {L} 290 L{L} {92 + inset} Z"/>'
        )
    if shape == "screen":
        L, R, T, B = 34 + inset, 478 - inset, 66 + inset, 446 - inset
        return (
            f'<path d="M{L + 30} {T} Q256 {T - 16} {R - 30} {T} Q{R} {T} {R} {T + 30} Q{R + 12} 256 {R} {B - 30} '
            f"Q{R} {B} {R - 30} {B} Q256 {B + 16} {L + 30} {B} Q{L} {B} {L} {B - 30} Q{L - 12} 256 {L} {T + 30} "
            f'Q{L} {T} {L + 30} {T} Z"/>'
        )
    if shape == "hexagon":
        import math

        r = 240 - inset * 1.15
        p = " ".join(
            f"{256 + r * math.cos(math.radians(a)):.1f},{256 + r * math.sin(math.radians(a)):.1f}"
            for a in range(0, 360, 60)
        )
        return f'<polygon points="{p}" stroke-linejoin="round"/>'
    w = 330 - inset * 1.41
    return f'<rect x="{256 - w / 2}" y="{256 - w / 2}" width="{w}" height="{w}" rx="{36 - inset * 0.3}" transform="rotate(45 256 256)"/>'


# Where the character goes in each shape.
BOX = {
    "circle": (112, 108, 288, 296),
    "shield": (128, 104, 256, 272),
    "screen": (104, 116, 304, 280),
    "hexagon": (118, 116, 276, 280),
    "diamond": (152, 152, 208, 208),
}


def modern(label: str, n: int) -> str:
    wide = len(label) > 1
    shapes = [s for s in SHAPES if not (wide and s == "diamond")]
    shape = shapes[n % len(shapes)]
    hi, mid, dark = MODERN[(n * 3) % len(MODERN)]
    defs = lin("f", [(0, hi), (1, mid)]) + shadow("sh", dy=5, blur=5, opacity=0.45)
    gold = hi == "#ffd84d"
    body = (
        f'<g filter="url(#sh)"><g fill="{dark}">{_shape(shape, 0)}</g>'
        f'<g fill="url(#f)">{_shape(shape, 12)}</g></g>'
        f'<g fill="none" stroke="#fff" stroke-opacity=".85" stroke-width="4">{_shape(shape, 24)}</g>'
    )
    font, weight = ("Big Shoulders Display", 900) if wide else ("Archivo Black", 400)
    face = (
        text(label, font, 100, weight=weight, fill="#3a2800", stroke="#fff6cf", sw=7)
        if gold
        else text(label, font, 100, weight=weight, fill="#fff", stroke=dark, sw=7)
    )
    body += fit(face, *BOX[shape])
    return svg(body, defs)


RETRO = [
    ["#f3c12e", "#ec8a1c", "#c2481a", "#8a2a1a"],  # sunset
    ["#8ee0ff", "#3fa9f5", "#2b64c9", "#28307a"],  # cool
    ["#ff9ecf", "#ff5ca8", "#c2338f", "#6e1f73"],  # pink
    ["#b7f05a", "#3fcf8e", "#139c8a", "#0f5c66"],  # mint
    ["#ffe066", "#ff9f1c", "#e84a5f", "#6a2c70"],  # 80s sunset
    ["#e8c07a", "#c98a3d", "#8a5a2b", "#4f3219"],  # 70s brown
]


def retro(label: str, n: int) -> str:
    stripes = RETRO[n % len(RETRO)]
    ink = "#241208"
    defs = shadow("sh", dy=6, blur=5, opacity=0.45)
    body = '<g filter="url(#sh)"><g transform="translate(0 330) skewX(-18) translate(0 -330)">'
    for i, c in enumerate(stripes):
        body += f'<rect x="36" y="{262 + i * 38}" width="440" height="28" fill="{c}"/>'
    body += "</g></g>"
    wide = len(label) > 1
    face = text(
        label,
        "Kanit",
        100,
        weight=900,
        style="italic",
        fill="#fff7e0",
        stroke=ink,
        sw=9,
        ls=-2 if wide else 0,
    )
    ex = extrude(face, 9, 9, 12, ink)
    box = (36, 116, 440, 270) if wide else (96, 36, 320, 400)
    body += fit(ex + face, *box)
    return svg(body, defs)


def logos() -> list[Logo]:
    out = []
    labels = [(str(n), "number", f"Number {n}") for n in range(1, 51)] + [
        (ch, "letter", f"Letter {ch}") for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ]
    for n, (label, kind, name) in enumerate(labels):
        slug = f"{kind}-{label.lower()}"
        cat = "Numbers" if kind == "number" else "Letters"
        tags = [label.lower(), kind]
        out.append(Logo(f"{slug}-modern", name, cat, lambda l=label, i=n: modern(l, i), tags))
        out.append(
            Logo(
                f"{slug}-retro",
                f"{name} · retro",
                f"Retro {cat.lower()}",
                lambda l=label, i=n: retro(l, i),
                tags + ["retro"],
            )
        )
    return out
