"""The logo library's legal care (the owner, October 11): no logo's name says
"channel", or is a real network's or program's name, and no logo is drawn
like a real network's mark. Redrawn and renamed logos keep their ids, so
stations using them keep them."""

from __future__ import annotations

import re

from app.logos import LIBRARY_VERSION, LogoLibrary

# Logos renamed in 1.32: the id stays, the name (and the words drawn) changed.
RENAMED = {
    "chuckle-channel": "Chuckle Hour",
    "channel-knob": "Tuning Knob",
    "cosmic-channel": "Cosmic TV",
    "kaiju-channel": "Kaiju Theater",
    "channel-dial": "Station Dial",
    "shock-theater": "Jolt Theater",
    "creature-feature": "Beastly Feature",
    "the-4-30-movie": "The 3:45 Movie",
    "movie-of-the-week": "Midweek Movie",
    "sunday-night-movie": "Sunday Evening Feature",
    "the-late-movie": "The Moonlight Movie",
    "the-big-story": "Stop the Presses",
    "the-lineup": "Mugshot",
    "space-station-9": "Space Station 3",
    "letterman": "Varsity Letter",
    "suspense-eye": "Suspense · door",
    "are-you-still-watching": "Still Up?",
    "front-line": "Battle Line",
}

# Real networks' and programs' names that no logo may be called.
REAL_NAMES = {
    "the 4:30 movie",
    "movie of the week",
    "sunday night movie",
    "the late movie",
    "shock theater",
    "creature feature",
    "creature features",
    "the big story",
    "the lineup",
    "letterman",
    "food tv",
    "sci-fi channel",
    "the western channel",
    "are you still watching?",
    "front line",
    "frontline",
    "be kind rewind",
}


def test_no_logo_or_category_says_channel():
    for logo in LogoLibrary().catalog():
        for words in (logo["name"], logo["category"]):
            assert not re.search(r"channel", words, re.I), logo


def test_the_categories_were_renamed():
    categories = {logo["category"] for logo in LogoLibrary().catalog()}
    assert {"Movie stations", "Classic stations"} <= categories
    assert not {"Movie channels", "Over-the-air classics"} & categories


def test_renamed_logos_keep_their_ids_and_pictures():
    library = LogoLibrary()
    names = {logo["id"]: logo["name"] for logo in library.catalog()}
    for logo_id, name in RENAMED.items():
        assert names.get(logo_id) == name, logo_id
        assert library.exists(logo_id) and library.resolve(logo_id) == logo_id


def test_no_logo_has_a_real_network_or_program_name():
    for logo in LogoLibrary().catalog():
        assert logo["name"].lower() not in REAL_NAMES, logo


def test_the_redrawn_library_has_a_new_version():
    # Part of each logo's address: browsers and Plex fetch the new pictures.
    assert LIBRARY_VERSION >= 4 and LogoLibrary().version == LIBRARY_VERSION


def test_number_and_letter_badges_are_never_shields():
    """A number in a shield looks like a real local station's. (Read from
    the drawing's code as written, without running it, so the image's test
    stage needs only that one file: its drawing kit isn't there.)"""
    import ast
    from pathlib import Path

    code = (Path(__file__).resolve().parents[1] / "tools" / "logos" / "letters.py").read_text()
    found = {
        target.id: ast.literal_eval(node.value)
        for node in ast.parse(code).body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in ("SHAPES", "BOX")
    }
    assert set(found) == {"SHAPES", "BOX"}
    assert "shield" not in found["SHAPES"] and "shield" not in found["BOX"]
