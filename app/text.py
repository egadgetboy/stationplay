"""Text people type (station names and descriptions, the names of uploaded
logos and bumpers), made plain before it's kept: it's shown on the page,
drawn by ffmpeg and passed to it as an argument, where a control character
(a NUL can't even be passed to a program) has no business."""

from __future__ import annotations

import re
import unicodedata


def plain(text: str) -> str:
    """`text` on one line: control characters (line breaks, tabs, NUL...)
    become spaces, runs of spaces one, and none at either end. (Invisible
    joiners stay: emoji are made with them.)"""
    kept = (" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c for c in text)
    return " ".join("".join(c for c in kept if unicodedata.category(c) != "Cs").split())


def name_from_file(file_name: str, otherwise: str) -> str:
    """A name to show for something uploaded, from its file's name: without
    the extension, underscores as spaces, plain, at most 40 characters (or
    `otherwise`, if that leaves nothing)."""
    name = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", plain(file_name))
    return plain(name.replace("_", " "))[:40] or otherwise
