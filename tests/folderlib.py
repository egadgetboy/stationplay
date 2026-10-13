"""A test library of folders, in the layouts Sonarr, Radarr, Jellyfin and
Plex use: tiny real files made with ffmpeg (a few seconds each, made once
and copied) where what's inside matters, zero-byte stand-ins where only
names do, with NFO files, pictures and odd cases (specials, two-episode
files, daily shows, versions, multi-part movies, extras folders, samples,
Unicode names). Everything goes under a test's own folder and is removed
with it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

CLIP_S = 3


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


class Clips:
    """Real files to copy into a library: made once per test run."""

    def __init__(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.folder = folder
        self.plain = folder / "plain.mkv"
        self.tagged = folder / "tagged.mp4"
        self.covered = folder / "covered.mkv"
        self.dark_start = folder / "dark-start.mkv"
        self.picture = folder / "picture.jpg"
        self.wide = folder / "wide.jpg"
        if not self.plain.exists():
            self._make()

    def _make(self) -> None:
        av = [
            "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=25:d={CLIP_S}",
            "-f", "lavfi", "-i", f"sine=f=440:d={CLIP_S}",
        ]  # fmt: skip
        enc = ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest"]
        ff(*av, *enc, "-metadata:s:a:0", "language=eng", str(self.plain))
        ff(
            *av, *enc,
            "-metadata", "title=The Title Inside",
            "-metadata", "date=2011-04-02",
            "-metadata", "description=A description from the file's own tags, long enough.",
            "-metadata", "genre=Drama;Mystery",
            str(self.tagged),
        )  # fmt: skip
        ff("-f", "lavfi", "-i", "color=c=0xC03030:s=60x90", "-frames:v", "1", str(self.picture))
        ff("-f", "lavfi", "-i", "color=c=0x3060C0:s=160x90", "-frames:v", "1", str(self.wide))
        ff(
            "-i", str(self.plain), "-attach", str(self.picture),
            "-metadata:s:t", "mimetype=image/jpeg", "-metadata:s:t", "filename=cover.jpg",
            "-c", "copy", str(self.covered),
        )  # fmt: skip
        # Black for its first 1.2 seconds, then bright.
        ff(
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=1.2",
            "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=25:d={CLIP_S}",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
            "-c:v", "libx264", "-preset", "ultrafast", str(self.dark_start),
        )  # fmt: skip


def put(path: Path, source: Path | None = None, text: str | None = None) -> Path:
    """A file: a copy of `source`, `text`, or a zero-byte stand-in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if source is not None:
        shutil.copyfile(source, path)
    elif text is not None:
        path.write_text(text, encoding="utf-8")
    else:
        path.write_bytes(b"")
    return path


def sparse(path: Path, size: int) -> Path:
    """A big file that takes no room on disk (only its size matters)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)
    return path


def tvshow_nfo(title: str, year: int | None = None, plot: str = "", **ids: str) -> str:
    unique = "".join(f'<uniqueid type="{k}">{v}</uniqueid>' for k, v in ids.items())
    year_tag = f"<year>{year}</year>" if year else ""
    return (
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
        f"<tvshow><title>{title}</title>{year_tag}<plot>{plot}</plot>"
        "<mpaa>TV-14</mpaa><genre>Drama</genre><genre>Mystery</genre><studio>Northern Network</studio>"
        "<actor><name>Ana Lee</name><role>Captain</role><order>1</order></actor>"
        "<actor><name>Bo Diaz</name><role>Pilot</role><order>0</order></actor>"
        f"{unique}</tvshow>"
    )


def episode_nfo(*episodes: tuple[int, int, str], plot: str = "") -> str:
    return '<?xml version="1.0" encoding="utf-8"?>\n' + "".join(
        f"<episodedetails><title>{title}</title><season>{s}</season><episode>{e}</episode>"
        f"<plot>{plot}</plot><aired>2019-0{s}-1{e % 10}</aired></episodedetails>"
        for s, e, title in episodes
    )


def movie_nfo(title: str, year: int, plot: str = "", sets: str = "", **ids: str) -> str:
    unique = "".join(f'<uniqueid type="{k}">{v}</uniqueid>' for k, v in ids.items())
    set_tag = f"<set><name>{sets}</name></set>" if sets else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f"<movie><title>{title}</title><year>{year}</year><plot>{plot}</plot>"
        f"<tagline>The tagline</tagline><mpaa>R</mpaa><genre>Action</genre>"
        f"<director>Dee Rector</director>{set_tag}{unique}</movie>"
    )


def sonarr_tv(root: Path, clips: Clips) -> dict[str, Path]:
    """Shows as Sonarr lays them out (with its Kodi metadata: tvshow.nfo,
    each episode's NFO, poster, fanart, season posters, thumbnails)."""
    show = root / "Northbound (2019) {tvdb-90001}"
    s1 = show / "Season 01"
    out = {
        "show": show,
        "e1": put(s1 / "Northbound (2019) - S01E01 - Pilot.mkv", clips.plain),
        "e23": put(s1 / "Northbound (2019) - S01E02E03 - The Double.mkv", clips.plain),
        "e4": put(s1 / "Northbound (2019) - S01E04 - Dark Water.mkv", clips.dark_start),
        "special": put(
            show / "Specials" / "Northbound (2019) - S00E01 - Behind It.mkv", clips.plain
        ),
    }
    put(
        show / "tvshow.nfo",
        text=tvshow_nfo("Northbound", 2019, "A ship goes north.", tvdb="90001", imdb="tt9000001"),
    )
    put(
        s1 / "Northbound (2019) - S01E01 - Pilot.nfo",
        text=episode_nfo((1, 1, "Pilot From NFO"), plot="It begins."),
    )
    put(
        s1 / "Northbound (2019) - S01E02E03 - The Double.nfo",
        text=episode_nfo((1, 2, "Part One"), (1, 3, "Part Two")),
    )
    put(show / "poster.jpg", clips.picture)
    put(show / "fanart.jpg", clips.wide)
    put(show / "clearlogo.png", clips.picture)
    put(show / "season01-poster.jpg", clips.picture)
    put(s1 / "Northbound (2019) - S01E01 - Pilot-thumb.jpg", clips.wide)
    # Extras and a NAS's own folders, never programs.
    put(show / "Featurettes" / "Making Northbound.mkv", clips.plain)
    put(show / "@eaDir" / "Northbound (2019) - S01E05.mkv")
    put(s1 / ".hidden - S01E09.mkv")
    # A daily show, named by date.
    daily = root / "The Daily Hour"
    out["daily1"] = put(daily / "The Daily Hour - 2024-03-15 - First Guest.mkv", clips.plain)
    out["daily2"] = put(daily / "The Daily Hour - 2024-03-18.mkv", clips.plain)
    return out


def plex_tv(root: Path, clips: Clips) -> dict[str, Path]:
    """Shows as Plex's own naming has them: "Season 1", 1x02 and s01e02,
    tags inside the files, and one StationPlay can't place."""
    show = root / "Orbit Room"
    return {
        "show": show,
        "o1": put(show / "Season 1" / "Orbit Room - 1x01 - Launch.mp4", clips.tagged),
        "o2": put(show / "Season 1" / "Orbit Room - s01e02.mp4", clips.plain),
        "odd": put(root / "Unplaced Show" / "Season 02" / "a recording.mkv", clips.plain),
        "sample": put(show / "Season 1" / "Orbit Room - s01e02 - sample.mkv"),
    }


def radarr_movies(root: Path, clips: Clips) -> dict[str, Path]:
    """Movies as Radarr lays them out (movie.nfo, poster, fanart), with
    versions, a multi-part movie, extras, samples and a Unicode name."""
    matrix = root / "The Glass Garden (1999)"
    heat = root / "Dry Season (1995)"
    long_movie = root / "Long Movie (1980)"
    out = {
        "matrix": put(matrix / "The Glass Garden (1999) {imdb-tt9100001}.mkv", clips.covered),
        "heat1080": put(heat / "Dry Season (1995) - 1080p.mkv", clips.plain),
        "heat4k": put(heat / "Dry Season (1995) - 4K.mkv", clips.tagged),
        "cd1": put(long_movie / "Long Movie (1980) - cd1.mkv", clips.plain),
        "cd2": put(long_movie / "Long Movie (1980) - cd2.mkv", clips.plain),
        "amelie": put(root / "Émilie (2001)" / "Émilie (2001).mkv", clips.plain),
        "loose": put(root / "Loose Movie (2005).mkv", clips.plain),
    }
    put(
        matrix / "movie.nfo",
        text=movie_nfo(
            "The Glass Garden",
            1999,
            "A hacker learns.",
            sets="The Glass Garden Collection",
            imdb="tt9100001",
            tmdb="91603",
        ),
    )
    put(matrix / "poster.jpg", clips.picture)
    put(matrix / "fanart.jpg", clips.wide)
    put(matrix / "sample.mkv", clips.plain)
    put(heat / "Dry Season (1995)-trailer.mkv", clips.plain)
    put(heat / "Featurettes" / "On Set.mkv", clips.plain)
    put(heat / "Behind The Scenes" / "Making It.mkv", clips.plain)
    # A small file beside a much bigger one is a sample.
    big = root / "Tall Tale (1988)"
    out["big"] = sparse(big / "Tall Tale (1988).mkv", 2 << 30)
    out["smpl"] = put(big / "big-smpl.mkv", clips.plain)
    return out


def jellyfin_movies(root: Path) -> dict[str, Path]:
    """Movies named as Jellyfin has them ([tmdbid-...], " - " versions)."""
    folder = root / "Neon Rain (1982) [tmdbid-90078]"
    return {
        "final": put(folder / "Neon Rain (1982) [tmdbid-90078] - Final Cut.mkv"),
        "theatrical": put(folder / "Neon Rain (1982) [tmdbid-90078] - Theatrical.mkv"),
        "alien": put(
            root
            / "Far Station (1979) {edition-Director's Cut}"
            / "Far Station (1979) {edition-Director's Cut}.mkv"
        ),
    }


def remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists() or os.path.islink(path):
        path.unlink()
