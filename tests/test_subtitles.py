"""Subtitles drawn into the picture: which a station draws (off, forced
only, always), from the file or a subtitle file next to it, as text or as
DVD and Blu-ray pictures; drawn at the right moments wherever a program is
joined; and a program whose subtitles can't be drawn plays without them."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app import ffmpeg as ff
from app import jobs, subtitles
from app.config import Settings
from app.subtitles import Candidate, choose, language, sidecars

from .fakeplex import FakePlex
from .test_e2e import assert_clean_stream, record, start_server
from .vobsub import write as write_vobsub

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
SMALL = Settings(plex_url="", plex_token="", video_width=640, video_height=360)
FPS = 30000 / 1001
# Where subtitles land in a 640x360 picture: text centred near the bottom,
# and the DVD subtitles' bar (see vobsub.py), its picture fitted to 4:3.
TEXT_AREA = "300:50:170:290"
BAR_AREA = "140:24:130:288"


def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args], check=True)


def srt(path: Path, cues: list[tuple[float, float, str]]) -> Path:
    def stamp(t: float) -> str:
        ms = round(t * 1000)
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    path.write_text(
        "\n".join(
            f"{n}\n{stamp(a)} --> {stamp(b)}\n{text}\n" for n, (a, b, text) in enumerate(cues, 1)
        ),
        encoding="utf-8",
    )
    return path


def black(path: Path, seconds: float = 14, size: str = "640x360") -> Path:
    run(
        "-f", "lavfi", "-i", f"color=c=black:s={size}:r=25:d={seconds}",
        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", str(seconds),
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path),
    )  # fmt: skip
    return path


EARLY = (2.0, 4.0, "WWWWWWWWWW WWWWWWWWWW")
LATE = (9.0, 11.0, "MMMMMMMMMM MMMMMMMMMM")


def with_text_tracks(tmp: Path, *tracks: tuple[list, str, bool]) -> Path:
    """A 14-second black film with subtitle streams: (cues, language,
    forced) each."""
    video = black(tmp / "plain.mkv")
    args = ["-i", str(video)]
    for n, (cues, _, _) in enumerate(tracks):
        args += ["-i", str(srt(tmp / f"track{n}.srt", cues))]
    args += ["-map", "0"] + [x for n in range(len(tracks)) for x in ("-map", str(n + 1))]
    args += ["-c", "copy", "-c:s", "srt"]
    for n, (_, lang, forced) in enumerate(tracks):
        args += [f"-metadata:s:s:{n}", f"language={lang}"]
        args += [f"-disposition:s:{n}", "forced" if forced else "0"]
    out = tmp / "film.mkv"
    run(*args, str(out))
    return out


def shown(path: Path, area: str) -> list[bool]:
    """Whether something bright is in `area` of each frame."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf",
         f"crop={area},signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return [float(line.split("=")[1]) > 24 for line in out.splitlines() if "YAVG=" in line]


def spans(flags: list[bool]) -> list[tuple[float, float]]:
    """The stretches (from, to), in seconds, where flags are set."""
    out, start = [], None
    for n, on in enumerate([*flags, False]):
        if on and start is None:
            start = n
        elif not on and start is not None:
            out.append((round(start / FPS, 1), round(n / FPS, 1)))
            start = None
    return out


async def played(
    source: Path, out: Path, offset_s: float, seconds: float, subs: ff.Subtitles | None
) -> Path:
    probe = await ff.probe(SMALL, str(source))
    assert probe.ok, probe.error
    args = ff.program_command(
        SMALL, str(source), offset_s, seconds, 10.0, 100.0, probe.audio_index, "Test",
        source_aspect=probe.display_aspect, video_index=probe.video_index, subtitles=subs,
    )  # fmt: skip
    args[args.index("pipe:1")] = str(out)
    proc = await asyncio.create_subprocess_exec(
        *args, stderr=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL
    )
    _, err = await asyncio.wait_for(proc.communicate(), 120)
    assert proc.returncode == 0, err.decode()[-500:]
    return out


def is_link(path: str) -> bool:
    return Path(path).is_symlink()


async def picked(tmp: Path, source: Path, mode: str) -> ff.Subtitles | subtitles.Extraction | None:
    probe = await ff.probe(SMALL, str(source))
    return await asyncio.to_thread(subtitles.for_program, tmp, mode, "eng", str(source), probe)


async def ready(choice: ff.Subtitles | subtitles.Extraction | None) -> ff.Subtitles | None:
    """Subtitles to draw, read out of the file first if they're in it."""
    if isinstance(choice, subtitles.Extraction):
        assert await subtitles.extract(SMALL, choice)
        return choice.ready()
    return choice


# Which subtitles -----------------------------------------------------------


def test_languages_are_named_alike():
    assert [language(x) for x in ("en", "ENG", "English", "eng ", "en-US", "en_GB")] == ["eng"] * 6
    assert language("fr") == language("fra") == language("French") == "fre"
    assert language("pt-BR") == "por" and language("zh-Hans") == "chi"
    # Codes without a name here are still languages (just not English).
    assert language("sr") == "sr" and language("sr-Latn") == "sr"
    assert language("klingon") == "klingon"


def test_subtitle_files_next_to_a_film_are_found(tmp_path):
    film = tmp_path / "Film (1999).mkv"
    film.write_bytes(b"")
    for name in (
        "Film (1999).srt", "Film (1999).en.srt", "Film (1999).eng.forced.srt",
        "Film (1999).English.SDH.srt", "Film (1999).fr.ass", "Film (1999).en.sub",
        "Film (1999) - Extras.en.srt", "Other.en.srt", "Film (1999).pt-BR.srt",
        "Film (1999).en-US.forced.srt", "Film (1999).sr.srt",
    ):  # fmt: skip
        (tmp_path / name).write_text("")
    found = {
        Path(c.path).name: (c.codec, c.language, c.forced, c.hearing_impaired)
        for c in sidecars(str(film))
    }
    assert found == {
        "Film (1999).srt": ("subrip", "", False, False),
        "Film (1999).en.srt": ("subrip", "eng", False, False),
        "Film (1999).eng.forced.srt": ("subrip", "eng", True, False),
        "Film (1999).English.SDH.srt": ("subrip", "eng", False, True),
        "Film (1999).fr.ass": ("ass", "fre", False, False),
        "Film (1999).pt-BR.srt": ("subrip", "por", False, False),
        "Film (1999).en-US.forced.srt": ("subrip", "eng", True, False),
        "Film (1999).sr.srt": ("subrip", "sr", False, False),
    }
    # Only the one that doesn't say its language stands in for English.
    picked = choose("always", "eng", [c for c in sidecars(str(film)) if c.language != "eng"])
    assert picked is not None and Path(picked[0].path).name == "Film (1999).srt"
    assert sidecars(str(tmp_path / "gone" / "film.mkv")) == []


def test_which_subtitles_a_station_draws():
    full = Candidate("subrip", "eng", False, False, stream=0)
    sdh = Candidate("subrip", "eng", False, True, stream=1)
    forced = Candidate("subrip", "eng", True, False, stream=2)
    french = Candidate("subrip", "fre", False, False, stream=3)
    pgs = Candidate("hdmv_pgs_subtitle", "eng", False, False, stream=4)
    beside = Candidate("subrip", "eng", False, False, path="/x/film.en.srt")
    untagged = Candidate("subrip", "", False, False, path="/x/film.srt")
    everything = [french, pgs, sdh, forced, full, beside, untagged]
    assert choose("off", "eng", everything) is None
    # Always: plain text in the language first (the file's own before a
    # file beside it), then SDH, then one that doesn't say its language.
    assert choose("always", "eng", everything) == (full, False)
    assert choose("always", "eng", [beside, pgs]) == (beside, False)
    assert choose("always", "eng", [pgs, sdh]) == (pgs, False)  # (no sound descriptions)
    assert choose("always", "eng", [sdh, untagged]) == (sdh, False)
    assert choose("always", "eng", [pgs]) == (pgs, False)
    assert choose("always", "eng", [untagged, french]) == (untagged, False)
    assert choose("always", "eng", [forced]) == (forced, False)
    assert choose("always", "eng", [french]) is None
    assert choose("always", "fre", everything) == (french, False)
    # Forced only: a forced stream; else a Blu-ray's own, its forced lines.
    assert choose("forced", "eng", everything) == (forced, False)
    assert choose("forced", "eng", [full, pgs]) == (pgs, True)
    assert choose("forced", "eng", [full, sdh, beside]) is None
    assert choose(
        "forced", "eng", [Candidate("subrip", "eng", True, False, path="/x/f.en.forced.srt")]
    )


def test_the_probe_lists_subtitle_streams(tmp_path):
    film = with_text_tracks(tmp_path, ([EARLY], "eng", False), ([LATE], "spa", True))
    tracks = asyncio.run(ff.probe(SMALL, str(film))).subtitles
    assert [(t.index, t.codec, t.language, t.forced) for t in tracks] == [
        (0, "subrip", "eng", False),
        (1, "subrip", "spa", True),
    ]


# Drawn at the right moments ----------------------------------------------


async def test_text_subtitles_are_drawn_when_they_should_be(tmp_path):
    film = with_text_tracks(tmp_path, ([EARLY, LATE], "eng", False))
    # Read out of the file into one of their own first (drawing them from
    # the film itself would mean reading all of it before its first frame).
    choice = await picked(tmp_path, film, "always")
    assert isinstance(choice, subtitles.Extraction) and choice.stream == 0
    subs = await ready(choice)
    assert subs is not None and not subs.image and subs.path.endswith(".ass")
    assert "/" + subtitles.FOLDER + "/" in subs.path
    # The next time, they're ready.
    again = await picked(tmp_path, film, "always")
    assert isinstance(again, ff.Subtitles) and again.path == subs.path
    out = await played(film, tmp_path / "a.ts", 0.0, 6.0, subs)
    assert_clean_stream(out)
    print("\nfrom the start:", spans(shown(out, TEXT_AREA)))
    assert spans(shown(out, TEXT_AREA)) == [(2.0, 4.0)]
    # Joined partway: the same subtitles, at the same moments of the film.
    out = await played(film, tmp_path / "b.ts", 7.5, 5.0, subs)
    print("from 7.5s in:", spans(shown(out, TEXT_AREA)))
    assert spans(shown(out, TEXT_AREA)) == [(1.5, 3.5)]
    # Without, nothing.
    out = await played(film, tmp_path / "c.ts", 0.0, 6.0, None)
    assert spans(shown(out, TEXT_AREA)) == []


async def test_forced_only_draws_just_the_forced_lines(tmp_path):
    film = with_text_tracks(tmp_path, ([EARLY], "eng", False), ([LATE], "eng", True))
    choice = await picked(tmp_path, film, "forced")
    assert isinstance(choice, subtitles.Extraction) and choice.stream == 1
    out = await played(film, tmp_path / "a.ts", 0.0, 12.0, await ready(choice))
    assert spans(shown(out, TEXT_AREA)) == [(9.0, 11.0)]
    always = await picked(tmp_path, film, "always")
    assert isinstance(always, subtitles.Extraction) and always.stream == 0


async def test_a_subtitle_file_beside_the_film(tmp_path):
    film = black(tmp_path / "Film (1999).mkv")
    srt(tmp_path / "Film (1999).en.srt", [EARLY])
    subs = await picked(tmp_path, film, "always")
    assert isinstance(subs, ff.Subtitles) and subs.stream is None and is_link(subs.path)
    out = await played(film, tmp_path / "a.ts", 0.0, 6.0, subs)
    assert spans(shown(out, TEXT_AREA)) == [(2.0, 4.0)]
    assert await picked(tmp_path, film, "forced") is None


async def test_dvd_subtitles_are_drawn_where_and_when_they_should_be(tmp_path):
    idx = write_vobsub(tmp_path / "bar", [(2.0, 4.0), (9.0, 11.0)])
    video = black(tmp_path / "plain.mkv", size="720x480")
    film = tmp_path / "dvd.mkv"
    run(
        "-i", str(video), "-i", str(idx), "-map", "0", "-map", "1", "-c", "copy",
        "-metadata:s:s:0", "language=eng", str(film),
    )  # fmt: skip
    subs = await picked(tmp_path, film, "always")
    assert subs == ff.Subtitles(stream=0, image=True)
    out = await played(film, tmp_path / "a.ts", 0.0, 6.0, subs)
    assert_clean_stream(out)
    print("\nfrom the start:", spans(shown(out, BAR_AREA)))
    assert spans(shown(out, BAR_AREA)) == [(2.0, 4.0)]
    out = await played(film, tmp_path / "b.ts", 7.5, 5.0, subs)
    print("from 7.5s in:", spans(shown(out, BAR_AREA)))
    assert spans(shown(out, BAR_AREA)) == [(1.5, 3.5)]
    # (Only DVD subtitles of Blu-rays have forced lines of their own.)
    assert await picked(tmp_path, film, "forced") is None


def test_the_drawing_is_tried_at_startup(tmp_path):
    assert asyncio.run(ff.subtitles_problem(SMALL, tmp_path / "subs")) is None
    # Whatever the data folder is called.
    odd = tmp_path / "it's a: [folder], here;\\"
    assert asyncio.run(ff.subtitles_problem(SMALL, odd / "subs")) is None
    broken = tmp_path / "ffmpeg"
    broken.write_text("#!/bin/sh\necho \"No such filter: 'subtitles'\" >&2\nexit 1\n")
    broken.chmod(0o755)
    problem = asyncio.run(
        ff.subtitles_problem(replace(SMALL, ffmpeg_path=str(broken)), tmp_path / "subs")
    )
    assert problem and "subtitles" in problem


def test_links_are_made_whatever_a_file_is_called(tmp_path):
    # (A name that isn't valid UTF-8, as Linux allows.)
    odd = tmp_path / "Film (1999).fran\udce7ais.srt"
    made = subtitles.link(tmp_path / "data", str(odd))
    assert made is not None and Path(made).is_symlink()
    assert subtitles.link(tmp_path / "data", str(odd)) == made  # (the same link again)
    # Nothing half made is left behind.
    assert all(not p.name.endswith(".new") for p in (tmp_path / "data" / "subtitles").iterdir())


async def test_subtitles_that_cant_be_read_out_arent_tried_again_straight_away(tmp_path):
    film = with_text_tracks(tmp_path, ([EARLY], "eng", False))
    choice = await picked(tmp_path, film, "always")
    assert isinstance(choice, subtitles.Extraction)
    broken = tmp_path / "ffmpeg"
    broken.write_text("#!/bin/sh\nexit 1\n")
    broken.chmod(0o755)
    assert not await subtitles.extract(replace(SMALL, ffmpeg_path=str(broken)), choice)
    assert await picked(tmp_path, film, "always") is None  # (for a day)


# On a station --------------------------------------------------------------


async def test_a_station_draws_subtitles_and_plays_on_if_it_cant(tmp_path, monkeypatch, caplog):
    """Two films with subtitle files: one's fine, the other's isn't a
    subtitle file at all. Both play, the first with its subtitles; nothing
    counts against the second."""
    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", False)
    d = tmp_path / "media"
    d.mkdir()
    plex = FakePlex()
    for n, name in enumerate(("Good", "Bad"), start=1):
        black(d / f"{name}.mkv", seconds=6)
        plex.add_movie(str(100 + n), name, str(d / f"{name}.mkv"), 6000, year=2000)
    srt(d / "Good.en.srt", [(0.0, 6.0, "WWWWWWWWWW WWWWWWWWWW")])
    (d / "Bad.en.srt").write_bytes(b"\x00\xff\xfe not subtitles \x00" * 200)
    base, app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={
                    "number": 3, "orderMode": "rotate", "introSeconds": 0, "upNextSeconds": 0,
                    "watermark": "off", "subtitles": "always",
                    "sources": [{"type": "movie", "ratingKey": "101"}, {"type": "movie", "ratingKey": "102"}],
                },
            )  # fmt: skip
            assert made.status_code == 201, made.text
            assert made.json()["subtitles"] == "always"
            data = await record(f"{base}/stream/3", 13)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "out.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert any(shown(out, TEXT_AREA)), "the good film's subtitles were drawn"
    assert app.state.ctx.broken.entries() == []
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "trying it again with nothing drawn over it" in said


async def test_a_slow_share_never_holds_a_program_up_for_its_subtitles(
    tmp_path, monkeypatch, caplog
):
    """Reading a big file's subtitles out over a slow share takes a while
    (here: 8 seconds each). The program starts straight away without them,
    and they're there the next time it plays."""
    import logging
    import time

    monkeypatch.setattr(jobs, "CHECK_NEW_STATIONS", False)
    d = tmp_path / "media"
    d.mkdir()
    film = with_text_tracks(d, ([(0.0, 6.0, "WWWWWWWWWW WWWWWWWWWW")], "eng", False))
    plex = FakePlex()
    plex.add_movie("101", "Film", str(film), 14_000, year=2000)
    slow = tmp_path / "ffmpeg"
    real = shutil.which("ffmpeg")
    slow.write_text(f'#!/bin/sh\ncase "$*" in *"-c:s ass"*) sleep 8;; esac\nexec {real} "$@"\n')
    slow.chmod(0o755)
    caplog.set_level(logging.INFO)
    base, app, _settings, srv, task = await start_server(tmp_path, plex, ffmpeg_path=str(slow))
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={
                    "number": 3, "introSeconds": 0, "upNextSeconds": 0, "watermark": "off",
                    "subtitles": "always", "sources": [{"type": "movie", "ratingKey": "101"}],
                },
            )  # fmt: skip
            assert made.status_code == 201, made.text
            asked = time.monotonic()
            first_byte_s = None
            data = bytearray()
            async with client.stream("GET", f"{base}/stream/3") as resp:
                async for chunk in resp.aiter_bytes():
                    if first_byte_s is None:
                        first_byte_s = time.monotonic() - asked
                    data += chunk
                    if time.monotonic() - asked > 34:
                        break
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "out.ts"
    out.write_bytes(bytes(data))
    assert_clean_stream(out)
    assert first_byte_s is not None and first_byte_s < 6, first_byte_s
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "aren't ready yet; it plays without them this time" in said
    assert "Extracted the subtitles from" in said
    # Not at first; then, the next time round, there.
    flags = shown(out, TEXT_AREA)
    assert not any(flags[: 25 * 5]) and any(flags[25 * 16 :]), spans(flags)
    assert app.state.ctx.broken.entries() == []
