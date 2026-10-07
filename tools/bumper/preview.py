"""Renders an Intro Bumper or a Station ID card to an MP4, for looking at
while working on it.

    python3 tools/bumper/preview.py LOGO NAME NUMBER SECONDS OUT.mp4 \\
        [--description TEXT] [--now "HEADING|SHOW|DETAIL"] [--version N] [--ident] [--silent]
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import intro
from app.config import Settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("logo")
    ap.add_argument("name")
    ap.add_argument("number", type=int)
    ap.add_argument("seconds", type=int, choices=sorted({*intro.LENGTHS[1:], *intro.ID_LENGTHS}))
    ap.add_argument("out")
    ap.add_argument("--description", default="")
    ap.add_argument("--now", default="")
    ap.add_argument("--version", type=int, default=0, help="which sound (1-4); random if 0")
    ap.add_argument("--ident", action="store_true", help="the Station ID card")
    ap.add_argument("--silent", action="store_true", help="without its sound")
    ap.add_argument(
        "--entrance", choices=intro.ENTRANCES, help="how the logo arrives; random if left out"
    )
    ap.add_argument("--idle", choices=intro.IDLES)
    ap.add_argument("--show", help="a video file whose sound the last third lands on")
    ap.add_argument("--show-at", type=float, default=60.0, help="where in it the last third starts")
    a = ap.parse_args()
    settings = Settings(plex_url="", plex_token="", data_dir=Path(tempfile.gettempdir()))
    logo = a.logo if a.logo != "-" else None
    now = tuple([*a.now.split("|"), "", "", ""][:3]) if a.now else ("", "", "")
    kind = intro.IDENT if a.ident else intro.INTRO
    card = intro.Card(a.name, a.number, a.description, logo, now, kind)  # type: ignore[arg-type]
    colours = asyncio.run(intro.colours(settings, logo))
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        subprocess.run(intro.stills_command(settings, card, colours, folder), check=True)
        how = intro.motion(a.seconds)
        how = intro.Motion(a.entrance or how.entrance, a.idle or how.idle)
        if a.ident:
            jingles = intro.jingles()
            jingle = (
                None
                if a.silent
                else jingles[(a.version - 1) % len(jingles)]
                if a.version and jingles
                else intro.jingle()
            )
            args = intro.ident_preview_command(
                settings, a.seconds, folder, jingle, Path(a.out), how
            )
            heard = jingle.name if jingle else "silent"
        else:
            choices = intro.sounds(a.seconds)
            sound = (
                None
                if a.silent
                else choices[(a.version - 1) % len(choices)]
                if a.version and choices
                else intro.sound(a.seconds)
            )
            show = intro.ShowAudio(a.show, a.show_at, 0, True) if a.show else None
            args = intro.preview_command(settings, a.seconds, folder, sound, Path(a.out), how, show)
            heard = sound.path.name if sound else "silent"
        subprocess.run(args, check=True)
    print(a.out, colours, heard, how)


if __name__ == "__main__":
    main()
