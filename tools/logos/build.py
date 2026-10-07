"""Draws StationPlay's logo library into app/logos/.

    cd tools/logos
    npm ci                      # the fonts (open-licensed, from npm)
    pip install playwright pillow imagequant
    python build.py             # every logo; or: python build.py ID...

Writes one 512x512 PNG per logo and catalog.json: the logos in the order
the picker shows them, and which new logo stands in for each logo of the
old (1.6 and earlier) library.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import classic_tv
import genres
import kids
import letters
import movies
import networks
import seasons
import themes
import toons
import tv_shows
from kit import Renderer, compress

OUT = Path(__file__).resolve().parents[2] / "app" / "logos"
CACHE = Path(__file__).resolve().parent / ".cache"
# Bumped whenever the pictures change, so browsers and Plex fetch them again.
VERSION = 3

ORDER = [
    "Broadcast networks",
    "Cable networks",
    "Movie channels",
    "Classic TV",
    "TV shows",
    "Over-the-air classics",
    "Decades",
    "Cartoons & anime",
    "Teens",
    "Kids & family",
    "Genres",
    "Holidays & seasons",
    "Times of day",
    "Formats & moods",
    "On the air",
    "Numbers",
    "Letters",
    "Retro numbers",
    "Retro letters",
]
# Channel names, listed A to Z (the rest keep the order they're drawn in:
# a holiday's logos together, numbers counting up...).
BY_NAME = {
    "Broadcast networks",
    "Cable networks",
    "Movie channels",
    "Classic TV",
    "TV shows",
    "Over-the-air classics",
    "Cartoons & anime",
    "Teens",
}

# The 1.6 library's logos, and the new one each station using it gets.
REPLACED = {
    "tv": "rabbit-ears",
    "movies": "movie-night",
    "features": "double-feature",
    "cinema": "projection-booth",
    "premieres": "premiere-row",
    "popcorn": "concession-stand",
    "classics": "classic-movies",
    "silver-screen": "decade-30s",
    "all-stars": "starstruck",
    "hits": "tentpole",
    "sci-fi": "science-fiction-atomic-age",
    "rocket": "liftoff",
    "space": "deep-field",
    "sci-fi-2": "science-fiction-modern",
    "robots": "science-fiction-80s",
    "science": "periodic",
    "horror": "horror-moon",
    "spooky": "halloween-haunted",
    "nightmares": "horror-dripping",
    "creepy": "horror-tombstone",
    "night-owl": "insomnia-theater",
    "morning": "good-morning",
    "sunrise": "good-morning",
    "romance": "romance-heart",
    "love-stories": "romance-rose",
    "drama": "drama-masks",
    "theater": "drama-curtain",
    "comedy": "comedy-burst",
    "laughs": "rimshot",
    "mystery": "mystery-magnifier",
    "detective": "film-noir-blinds",
    "western": "western-sheriff-star",
    "westerns": "western-sunset",
    "frontier": "sundown-trail",
    "action": "action-blast",
    "heroes": "cape-and-cowl",
    "action-2": "action-slash",
    "defenders": "precinct",
    "adventure": "adventure-compass",
    "explore": "basecamp",
    "fantasy": "fantasy-castle",
    "royalty": "fantasy-sword",
    "classics-2": "nitrate",
    "stories": "biography-book",
    "reality": "reality-rec",
    "world": "documentary-globe",
    "documentary": "documentary-camera",
    "music": "music-vinyl",
    "talk": "talk-show-speech-bubbles",
    "variety": "variety-mix",
    "oldies": "decade-50s",
    "jukebox": "decade-40s",
    "games": "player-two",
    "game-shows": "game-show-marquee",
    "quiz": "game-show-buzzer",
    "sports": "sport-trophy",
    "champions": "sport-varsity",
    "pets": "wag-and-purr",
    "animals": "critter-corner",
    "outdoors": "trailhead",
    "nature": "burrow-and-branch",
    "ocean": "tidepool",
    "surf": "offshore",
    "harbor": "tidepool",
    "travel": "travel-plane",
    "motors": "piston-alley",
    "cooking": "skillet",
    "family": "family-house",
    "home": "hearthside",
    "kids": "children-bubble-letters",
    "party": "friday-night",
    "kids-2": "kids-zone",
    "cartoons": "doodlebox",
    "timeless": "chronicle-hour",
    "nonstop": "binge",
    "replay": "reruns",
    "retro": "decade-70s",
    "80s": "decade-80s",
    "70s": "decade-70s",
    "groovy": "decade-60s",
    "mixtape": "cassette",
    "90s": "decade-90s",
    "christmas": "christmas-wreath",
    "holiday": "christmas-vintage",
    "holidays": "christmas-cozy",
    "ornament": "christmas-vintage",
    "gifts": "christmas-toons",
    "merry": "christmas-vintage",
    "snowman": "winter",
    "harvest": "thanksgiving",
    "witchy": "halloween-haunted",
    "halloween-2": "halloween",
    "boo": "cold-spot",
    "valentine": "valentines",
    "lucky": "st-patricks",
    "st-pats": "st-patricks",
    "new-year": "new-years-eve",
    "celebrate": "new-years-eve",
    "july-4th": "fourth-of-july",
    "new-year-2": "new-years-eve",
    "spring-2": "spring",
    "beach": "offshore",
    "sunny-days": "summer",
    "birthday": "friday-night",
    "pumpkin": "halloween",
    "snowflake": "winter",
    "moon": "bedtime-stories",
    "star": "starstruck",
    "favorites": "award-winners",
    "blast-off": "liftoff",
    "indie": "indie-clapperboard",
    "film-fest": "indie-laurels",
    "wilderness": "trailhead",
    "campfire": "basecamp",
    "bedtime": "bedtime-stories",
    "tv-2": "classic-tv",
    "tv-3": "vertical-hold",
    "tv-4": "rooftop-tv",
    "live-2": "bulletin",
    "hd": "lodestar",
    "one": "number-1-modern",
    "two": "number-2-modern",
    "play": "binge",
    "on-air-2": "on-air",
    "retro-2": "decade-80s",
    "retro-television": "vertical-hold",
    "gold-classics": "nitrate",
    "vault-classics": "silver-palace",
    "cult-favorites": "cult-classics",
    "rewind": "reruns",
    "replay-2": "rerun-road",
    "anytime": "marathon",
    "drive-in-movies": "drive-in",
    "sunday-matinee": "sunday-afternoon",
    "weekend": "friday-night",
    "spotlight": "footlight-cinema",
    "station": "hometown-nine",
    "classic": "grayscale",
    "oldies-2": "malt-shop",
    "chill": "sunroom",
    "now-playing": "projection-booth",
    "applause": "laugh-track",
    "static": "please-stand-by",
    "vintage": "title-card",
    "fun": "variety-mix",
    "turbo": "hot-pursuit",
    "lounge": "two-drink-minimum",
    "marquee": "musical-marquee",
    "channel": "channel-dial",
    "signal": "strange-frequency",
    "dream": "pajama-party",
    "home-theater": "movie-night",
    **{f"letter-{c}": f"letter-{c}-modern" for c in "abcdefghijklmnopqrstuvwxyz"},
    # 1.8: the spin-off channels go (each station using one gets its
    # parent's logo), and Hanukkah makes way for winter.
    **{
        f"{parent}-{feed}": parent
        for parent, feeds in (
            ("velvet-rope", ("family", "comedy", "signature")),
            ("night-reel", ("action", "thriller", "sci-fi")),
            ("premiere-row", ("family", "extreme")),
            ("second-showing", ("westerns", "classic", "action", "suspense", "family")),
            ("gold-seal", ("comedy", "edge", "kids-and-family")),
            ("widescreen", ("hits",)),
            ("vertical-hold", ("plus",)),
        )
        for feed in feeds
    },
    "hanukkah": "winter",
}
# Old logos whose names the new library uses again (same subject, new picture).
KEPT = {
    "classic-tv",
    "reruns",
    "movie-night",
    "b-movies",
    "late-night",
    "marathon",
    "toons",
    "winter",
    "halloween",
    "autumn",
    "thanksgiving",
    "easter",
    "spring",
    "summer",
    "rainy-day",
    "sing-along",
    "live",
    "on-air",
    "binge",
    "prime-time",
    "midnight-movies",
    "matinee",
    "double-feature",
    "saturday-morning",
    "test-pattern",
    "snow-day",  # (1.7 gave its stations the snow globe; 1.8 has a Snow Day again)
}


def all_logos():
    modules = (
        networks, classic_tv, tv_shows, movies, toons, kids, genres, themes, seasons, letters,
    )  # fmt: skip
    logos = [logo for module in modules for logo in module.logos()]
    rank = {c: i for i, c in enumerate(ORDER)}
    for logo in logos:
        assert logo.category in rank, logo.category
    return sorted(
        logos, key=lambda l: (rank[l.category], l.name.lower() if l.category in BY_NAME else "")
    )


def check(logos) -> None:
    ids = [l.id for l in logos]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"logos with the same id: {dupes}"
    known = set(ids)
    for old, new in REPLACED.items():
        assert new in known, f"{old} is replaced by {new}, which doesn't exist"
        assert old not in known, f"{old} is both replaced and kept"
    for old in KEPT:
        assert old in known, f"{old} was to be kept but isn't in the library"


def main() -> None:
    logos = all_logos()
    check(logos)
    only = set(sys.argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    r = None
    total = 0
    for n, logo in enumerate(logos, 1):
        if only and logo.id not in only:
            continue
        s = logo.draw()
        key = hashlib.sha1(s.encode()).hexdigest()[:20]
        cached = CACHE / f"{key}.png"
        if not cached.exists():
            if r is None:
                r = Renderer()
            cached.write_bytes(compress(r.png(s)))
        data = cached.read_bytes()
        (OUT / f"{logo.id}.png").write_bytes(data)
        total += len(data)
        print(f"{n}/{len(logos)} {logo.id}", file=sys.stderr)
    if r is not None:
        r.close()
    if not only:
        wanted = {f"{l.id}.png" for l in logos}
        for old in OUT.glob("*.png"):
            if old.name not in wanted:
                old.unlink()
    catalog = {
        "version": VERSION,
        "logos": [
            {"id": l.id, "name": l.name, "category": l.category, "tags": l.tags} for l in logos
        ],
        "replaced": dict(sorted(REPLACED.items())),
    }
    (OUT / "catalog.json").write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(logos)} logos, {total / 1e6:.1f} MB", file=sys.stderr)


if __name__ == "__main__":
    main()
