"""Skips moved to where the picture cuts (app/cuts.py)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import cuts
from app import markers as mk
from app.config import Settings
from app.db import Item
from app.markers import CREDITS, INTRO, Marker
from app.sources import MediaAccess, ResolvedSource, readable

from .test_e2e import ff
from .test_e2e_skipping import sectioned

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
S = 1000
SETTINGS = Settings(plex_url="", plex_token="")


# Where a skip goes ------------------------------------------------------------------


def test_a_skip_starts_where_the_cold_open_ends():
    # Plex says 5.5 s (the theme's first note); the picture cuts to the titles at 7 s.
    assert cuts.later_start(5500, [7000, 9000]) == 7000
    # A shot change in the cold open just before Plex's start says nothing about where
    # the cold open ends: its last shot runs on to 7 s. (It held the skip at 5.5 s.)
    assert cuts.later_start(5500, [5200, 7000]) == 7000
    # The cold open changes shot under the music (at 6 s), and ends at 7 s: within 3 s
    # of Plex's start, the last cut, so all of it plays (and at worst a moment of the
    # titles). (The skip started at 6 s, and the cold open's last second was lost.)
    assert cuts.later_start(5500, [6000, 7000, 9000]) == 7000
    assert cuts.later_start(5500, [6000, 7000, 8500, 9000]) == 8500
    # Beyond 3 s, the first cut up to 6 s.
    assert cuts.later_start(5500, [9000, 10000]) == 9000
    # None near it (a dissolve), or not looked at yet: 2 s later.
    assert cuts.later_start(5500, [20000]) == 7500
    assert cuts.later_start(5500, [5200]) == 7500
    assert cuts.later_start(5500, []) == 7500
    assert cuts.later_start(5500, None) == 7500
    # A cut right at Plex's start (as close as a file's clock is to its picture): Plex's.
    assert cuts.later_start(6000, [6021, 7000, 8000]) == 6000
    assert cuts.later_start(6000, [5950, 9000]) == 6000


def test_a_skip_ends_where_the_program_starts():
    # Plex says 14.5 s (the theme's last note); the program's first shot began at 13 s.
    assert cuts.earlier_end(14500, [9000, 13000]) == 13000
    # The program's second shot, just after Plex's end, isn't where the program starts.
    # (It held the skip at 14.5 s, and the program's first 1.5 s were skipped.)
    assert cuts.earlier_end(14500, [13000, 14800]) == 13000
    # The program changes shot under the music (at 14 s), having started at 13 s:
    # within 3 s of Plex's end, the first cut, so all of it plays.
    assert cuts.earlier_end(14500, [9000, 13000, 14000]) == 13000
    assert cuts.earlier_end(14500, [9000, 12000, 13000, 14000]) == 12000
    # Beyond 3 s, the last cut from 6 s before.
    assert cuts.earlier_end(14500, [9000, 10000]) == 10000
    assert cuts.earlier_end(14500, [14800]) == 12500
    assert cuts.earlier_end(14500, []) == 12500
    assert cuts.earlier_end(14500, None) == 12500
    assert cuts.earlier_end(10000, [6021, 8000, 10021]) == 10000  # (right at Plex's end)


def test_a_skip_only_ever_gets_shorter():
    intro = Marker(INTRO, 5500, 14500)
    assert cuts.moved(intro, [7000], [13000], 60000) == Marker(INTRO, 7000, 13000)
    # Cuts found only past Plex's own start and end: the margins.
    assert cuts.moved(intro, [5200], [14800], 60000) == Marker(INTRO, 7500, 12500)
    # Final credits run to the end of the file, whatever is found there.
    final = Marker(CREDITS, 32000, 37000, True)
    assert cuts.moved(final, [33000], None, 37000) == Marker(CREDITS, 33000, 37000, True)
    # Cuts that cross: nothing's skipped.
    assert cuts.moved(Marker(INTRO, 6000, 10000), [8500], [7000], 60000).end_ms == 8500


def test_a_skip_left_too_short_isnt_made():
    """A short intro (5 s) under the margins, or with the cuts found inside
    it crossing, is too short to skip: the program plays in full, those
    seconds of titles and all, rather than lose a moment of itself (see
    test_skipping for its station's updates)."""
    length = 22 * 60 * S
    short = Marker(INTRO, 60 * S, 65 * S)
    assert cuts.moved(short, None, None, length) == Marker(INTRO, 62 * S, 63 * S)
    crossed = cuts.moved(short, [61 * S, 63 * S], [61 * S, 63 * S], length)
    assert crossed == Marker(INTRO, 63 * S, 63 * S)
    for moved in (cuts.moved(short, None, None, length), crossed):
        assert mk.segments_for(length, [moved]) is None


def test_skips_at_the_very_start_or_end_of_a_file_stay_put():
    """A few seconds left before a skip at the start of a file (a logo), or
    after one at its end, are skipped too (see markers.py). Moved, the skip
    left 5 seconds or more there, and they flashed up."""
    length = 22 * 60 * S
    logo = Marker(INTRO, 3 * S, 60 * S)
    assert cuts.moved(logo, None, [58 * S], length) == Marker(INTRO, 3 * S, 58 * S)
    assert mk.segments_for(length, [cuts.moved(logo, None, [58 * S], length)]) == (
        (58 * S, length),
    )
    sting = Marker(CREDITS, length - 60 * S, length - 3 * S)
    assert cuts.moved(sting, None, None, length).end_ms == length - 3 * S
    assert mk.segments_for(length, [cuts.moved(sting, None, None, length)]) == (
        (0, length - 58 * S),
    )
    assert cuts.edges([logo, sting], length) == [f"end:{60 * S}", f"start:{length - 60 * S}"]
    # Further in, they move.
    assert cuts.edges([Marker(INTRO, 5 * S, 60 * S)], length) == [f"start:{5 * S}", f"end:{60 * S}"]


def test_times_are_read_however_ffmpeg_writes_them():
    """FFmpeg 6.1 writes a time near 0 as, say, 1.11111e-05 (read as 1.1 s,
    it was a false cut)."""
    said = "\n".join(
        [
            "[Parsed_showinfo_3 @ 0x1] n:   0 pts:      1 pts_time:1.11111e-05 duration:1",
            "[blackdetect @ 0x2] black_start:1.11111e-05 black_end:0.5 black_duration:0.5",
            "[Parsed_showinfo_3 @ 0x1] n:   1 pts:  75000 pts_time:2.5    duration:1",
            "[blackdetect @ 0x2] black_start:4.2 black_end:4.40001 black_duration:0.2",
        ]
    )
    assert cuts.read_back(said, 10_000, starts=True) == (10_000, [12_500, 14_200])
    assert cuts.read_back(said, 10_000, starts=False) == (10_000, [10_500, 12_500, 14_400])
    assert cuts.read_back("nothing", 10_000, starts=True) == (None, [])


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[]",
        "null",
        '"cuts"',
        '{"version": 1, "programs": []}',
        '{"version": 99, "programs": {}}',
        '{"version": 1, "programs": {"201:60000": 5}}',
        '{"version": 1, "programs": {"201:60000": {"used": "today", "edges": {}}}}',
        '{"version": 1, "programs": {"201:60000": {"used": 1, "edges": {"start:5500": [true]}}}}',
        '{"version": 1, "programs": {"201:60000": {"used": 1, "edges": {"start:5500": "7000"}}}}',
    ],
)
async def test_a_damaged_or_strange_cuts_file_is_set_aside(tmp_path, text):
    """Whatever's in cuts.json, skips keep their margins (it once broke every
    skipping station)."""
    (tmp_path / cuts.FILE).write_text(text)

    async def resolve(item: Item) -> ResolvedSource:
        return ResolvedSource(None)  # (nowhere to read it: the margins hold)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    item = _item("/x.mkv", 60 * S)
    assert finder.adjusted(item, [Marker(INTRO, 5500, 14500)]) == [Marker(INTRO, 7500, 12500)]
    got = await finder.refined([item], {"201": [Marker(INTRO, 5500, 14500)]})
    assert got == {"201": [Marker(INTRO, 7500, 12500)]}
    await asyncio.wait_for(finder._worker, 5)


def test_only_whats_in_shape_is_read_from_the_cuts_file():
    text = json.dumps(
        {
            "version": 1,
            "programs": {
                "201:60000": {
                    "used": 20000,
                    "edges": {
                        "start:5500": [7000, 9000, 7000],
                        "end:14500": [13000],
                        "middle:3": [1],
                        "start:x": [2],
                        "end:900": [False],
                    },
                },
                "202:60000": {"used": 20000},
            },
        }
    )
    assert cuts.parsed(text) == {
        "201:60000": {"used": 20000, "edges": {"start:5500": [7000, 9000], "end:14500": [13000]}}
    }


# Looking ---------------------------------------------------------------------------


def _item(path: str, length_ms: int, key: str = "201") -> Item:
    return Item(0, 0, length_ms, key, "episode", "Episode 1", file_path=path)


def _reads(path):
    async def resolve(item: Item) -> ResolvedSource:
        return ResolvedSource(str(path))

    return resolve


@needs_ffmpeg
async def test_cuts_are_found_kept_and_used(tmp_path):
    """Cuts are found around each marker (a change of shot, or black), kept
    in cuts.json by program, file length and marker, and used next time
    without looking again."""
    film = tmp_path / "1.mkv"
    sectioned(film, [("yellow", 7), ("lime", 6), ("cyan", 20), ("magenta", 4)])
    looked = []

    async def resolve(item: Item) -> ResolvedSource:
        looked.append(item.rating_key)
        return ResolvedSource(str(film))

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    item = _item(str(film), 37 * S)
    known = {"201": [Marker(INTRO, 5500, 14500), Marker(CREDITS, 32000, 37000, True)]}
    got = await finder.refined([item], known, look_s=60)
    start, end = got["201"][0].start_ms, got["201"][0].end_ms
    assert abs(start - 7000) <= 60 and abs(end - 13000) <= 60, got
    assert abs(got["201"][1].start_ms - 33000) <= 60, got
    assert finder.placed == {"201"}
    await finder.save()
    kept = json.loads((tmp_path / cuts.FILE).read_text())
    assert kept["version"] == cuts.VERSION
    assert set(kept["programs"]) == {"201:37000"}
    assert set(kept["programs"]["201:37000"]["edges"]) == {"start:5500", "end:14500", "start:32000"}
    again = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    assert await again.refined([item], known, look_s=60) == got
    assert looked == ["201"]  # (looked at once)
    assert again.placed == {"201"}


@needs_ffmpeg
async def test_with_no_cut_near_a_marker_the_skip_keeps_a_margin(tmp_path):
    """Where the picture shows no cut near a marker (here the cold open runs
    on into the titles in one shot), the skip is 2 seconds shorter there."""
    film = tmp_path / "1.mkv"
    sectioned(film, [("yellow", 13), ("cyan", 20), ("magenta", 4)])
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(film))
    got = await finder.refined(
        [_item(str(film), 37 * S)], {"201": [Marker(INTRO, 5500, 14500)]}, look_s=60
    )
    assert got["201"][0].start_ms == 7500
    assert abs(got["201"][0].end_ms - 13000) <= 60  # (the cut to cyan)


@needs_ffmpeg
async def test_a_shot_change_just_outside_a_marker_doesnt_hold_the_skip_there(tmp_path):
    """The cold open changes shot 0.3 s before the theme starts, and runs on
    to 7 s; the program's second shot begins 0.3 s after the theme ends, its
    first at 13 s. The skip goes from 7 s to 13 s. (It stayed at Plex's 5.5
    to 14.5 s: 1.5 s of the cold open and of the program were skipped.)"""
    film = tmp_path / "1.mkv"
    sectioned(
        film,
        [("yellow", 5.2), ("orange", 1.8), ("lime", 6), ("cyan", 1.8), ("white", 18.2),
         ("magenta", 4)],
    )  # fmt: skip
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(film))
    got = await finder.refined(
        [_item(str(film), 37 * S)], {"201": [Marker(INTRO, 5500, 14500)]}, look_s=60
    )
    assert abs(got["201"][0].start_ms - 7000) <= 60, got
    assert abs(got["201"][0].end_ms - 13000) <= 60, got


@needs_ffmpeg
@pytest.mark.parametrize("keyframes", ["0,7,13,33", "0,20"])
async def test_a_recording_is_read_from_far_enough_back(tmp_path, keyframes):
    """A TV recording (MPEG-TS, its clock far from 0), Plex's markers right
    on its cuts. FFmpeg's seek in it lands on the next keyframe. With
    keyframes at the cuts, the first frame read was the cut itself, and
    can't be seen to be one: the skip started 2 s late, and 2 s of the
    titles aired. With keyframes far apart, nothing near the marker was
    read at all."""
    sections = [("yellow", 7), ("lime", 6), ("cyan", 20), ("magenta", 4)]
    chains = [f"color=c={c}:s=640x360:r=30:d={d}[s{n}]" for n, (c, d) in enumerate(sections)]
    joined = "".join(f"[s{n}]" for n in range(4))
    graph = ";".join(chains) + f";{joined}concat=n=4:v=1:a=0[out0]"
    film = tmp_path / "rec.ts"
    ff(
        "-f", "lavfi", "-i", graph, "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000",
        "-t", "37", "-c:v", "libx264", "-preset", "ultrafast", "-g", "9999", "-sc_threshold", "0",
        "-force_key_frames", keyframes, "-c:a", "aac", "-output_ts_offset", "30000",
        "-shortest", str(film),
    )  # fmt: skip
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(film))
    got = await finder.refined(
        [_item(str(film), 37 * S)], {"201": [Marker(INTRO, 7000, 13000)]}, look_s=60
    )
    assert got["201"] == [Marker(INTRO, 7000, 13000)]


@needs_ffmpeg
async def test_a_marker_past_the_end_of_the_file_read_keeps_its_margin(tmp_path):
    """(A program in two files: only the first is read, and a marker in the
    second finds nothing there.)"""
    film = tmp_path / "1.mkv"
    sectioned(film, [("yellow", 7), ("lime", 6), ("cyan", 4)])
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(film))
    item = _item(str(film), 120 * S)
    got = await finder.refined([item], {"201": [Marker(CREDITS, 80 * S, 100 * S)]}, look_s=60)
    assert got["201"] == [Marker(CREDITS, 82 * S, 98 * S)]
    assert finder.placed == {"201"}  # (looked at: nothing more to find)


# Looking in the background -------------------------------------------------------------


async def test_saving_a_station_waits_no_longer_than_allowed(tmp_path):
    """However slow a file is to reach, a station being saved waits no more
    than its time (it once waited minutes); the margins hold meanwhile, and
    the file is looked at in the background."""
    release = asyncio.Event()
    asked = []

    async def resolve(item: Item) -> ResolvedSource:
        asked.append(item.rating_key)
        await release.wait()
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    items = [_item("/x.mkv", 60 * S), _item("/y.mkv", 60 * S, "202")]
    known = {k: [Marker(INTRO, 5500, 14500)] for k in ("201", "202")}
    began = time.monotonic()
    got = await finder.refined(items, known, look_s=0.3)
    assert time.monotonic() - began < 1.5
    assert got["201"] == got["202"] == [Marker(INTRO, 7500, 12500)]
    assert asked == ["201"]
    release.set()
    await asyncio.wait_for(finder._worker, 5)
    assert asked == ["201", "202"]
    assert finder.ready(items[0], known["201"]) and finder.ready(items[1], known["202"])
    finder.stop()


async def test_the_hourly_update_doesnt_wait(tmp_path):
    release = asyncio.Event()

    async def resolve(item: Item) -> ResolvedSource:
        await release.wait()
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    began = time.monotonic()
    await finder.refined([_item("/x.mkv", 60 * S)], {"201": [Marker(INTRO, 5500, 14500)]})
    assert time.monotonic() - began < 0.5
    finder.stop()


async def test_a_station_being_saved_goes_first(tmp_path):
    asked = []

    async def resolve(item: Item) -> ResolvedSource:
        asked.append(item.rating_key)
        await asyncio.sleep(0.01)
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    marked = [Marker(INTRO, 5500, 14500)]
    rest = [_item(f"/{n}.mkv", 60 * S, str(n)) for n in range(300, 320)]
    await finder.refined(rest, {i.rating_key: marked for i in rest})
    mine = _item("/mine.mkv", 60 * S, "201")
    await finder.refined([mine], {"201": marked}, look_s=5)
    assert finder.ready(mine, marked)
    assert asked.index("201") <= 1, asked  # (after the one already under way, at most)
    finder.stop()


@needs_ffmpeg
async def test_a_file_that_cant_be_read_now_is_tried_again(tmp_path, monkeypatch):
    """A file that can't be read (a failed or slow read) isn't taken to have
    no cuts: it's tried again later, and its cuts are found then. (Its
    margins were kept for good.)"""
    monkeypatch.setattr(cuts, "RETRY_S", (3.0, 3.0, 3.0))
    film = tmp_path / "1.mkv"
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(film))
    item = _item(str(film), 37 * S)
    known = {"201": [Marker(INTRO, 5500, 14500)]}
    got = await finder.refined([item], known, look_s=5)  # (not there yet)
    assert got["201"] == [Marker(INTRO, 7500, 12500)]
    assert not finder.ready(item, known["201"]) and finder.placed == set()
    await finder.save()
    assert not (tmp_path / cuts.FILE).exists()
    sectioned(film, [("yellow", 7), ("lime", 6), ("cyan", 20), ("magenta", 4)])
    await asyncio.wait_for(finder._worker, 30)
    monkeypatch.setattr(cuts, "SHOW_EVERY_S", 0.0)
    finder.show()
    got = await finder.refined([item], known)
    assert abs(got["201"][0].start_ms - 7000) <= 60 and abs(got["201"][0].end_ms - 13000) <= 60


async def test_a_file_that_never_reads_is_left_with_its_margins(tmp_path, monkeypatch):
    monkeypatch.setattr(cuts, "RETRY_S", (0.01, 0.01, 0.01))
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(tmp_path / "missing.mkv"))
    item = _item(str(tmp_path / "missing.mkv"), 37 * S)
    known = {"201": [Marker(INTRO, 5500, 14500)]}
    await finder.refined([item], known)
    await asyncio.wait_for(finder._worker, 30)
    assert set(finder._left) == {"201:37000"}
    assert await finder.refined([item], known) == {"201": [Marker(INTRO, 7500, 12500)]}
    assert finder._worker.done() and not finder._queue  # (not asked about again)


async def test_while_the_share_isnt_answering_looking_waits(tmp_path, monkeypatch):
    """A media share that doesn't answer stops looking for a while (not one
    failure after another, each kept), then the same program is looked at."""
    monkeypatch.setattr(cuts, "PAUSE_S", 0.2)
    answers = [ResolvedSource(None, error="the media share isn't responding", transient=True)]
    asked = []

    async def resolve(item: Item) -> ResolvedSource:
        asked.append((item.rating_key, time.monotonic()))
        return answers.pop(0) if answers else ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    items = [_item("/x.mkv", 60 * S), _item("/y.mkv", 60 * S, "202")]
    known = {k: [Marker(INTRO, 5500, 14500)] for k in ("201", "202")}
    began = time.monotonic()
    await finder.refined(items, known, look_s=5)
    assert time.monotonic() - began < 1  # (no waiting on a share that isn't there)
    await asyncio.wait_for(finder._worker, 5)
    assert [k for k, _ in asked] == ["201", "201", "202"]
    assert asked[1][1] - asked[0][1] >= 0.2
    assert finder.ready(items[0], known["201"])


async def test_whats_found_is_saved_now_and_then_and_old_programs_go(tmp_path, monkeypatch):
    """Saving rewrote the whole file for every program looked at, and kept
    every program ever looked at."""
    writes = []
    real_write = cuts._write

    def write(path, text):
        writes.append(text)
        real_write(path, text)

    monkeypatch.setattr(cuts, "_write", write)
    monkeypatch.setattr(cuts, "MOST_PROGRAMS", 30)
    old = {"version": 1, "programs": {"9:60000": {"used": cuts.today() - 61, "edges": {}}}}
    (tmp_path / cuts.FILE).write_text(json.dumps(old))

    async def resolve(item: Item) -> ResolvedSource:
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    items = [_item(f"/{n}.mkv", 60 * S, str(n)) for n in range(100, 140)]
    marked = [Marker(INTRO, 5500, 14500)]
    await finder.refined(items, {i.rating_key: marked for i in items})
    await asyncio.wait_for(finder._worker, 5)
    assert len(writes) <= 1
    finder.stop()  # (saved on the way out)
    kept = json.loads((tmp_path / cuts.FILE).read_text())["programs"]
    assert len(kept) == 40 and "9:60000" not in kept  # (all 40 scheduled today stay)


async def test_looking_doesnt_ask_plex_or_count_as_a_file_played(tmp_path):
    """Where a file is read from to look at it: as Plex listed it just now,
    without asking Plex again (it warned in the log for each program while
    Plex was down) or counting it on the status page as a file played."""
    film = tmp_path / "1.mkv"
    film.write_bytes(b"x")
    access = MediaAccess()
    library = SimpleNamespace(configured=True, stream_url=lambda key, part: f"http://plex/{part}")
    item = replace(_item(str(film), 60 * S), part_key="/library/parts/7/file.mkv")
    got = await readable(SETTINGS, library, item, access)  # type: ignore[arg-type]
    assert got.source == str(film)
    elsewhere = replace(item, file_path="/nowhere/1.mkv")
    got = await readable(SETTINGS, library, elsewhere, access)  # type: ignore[arg-type]
    assert got.source == "http://plex//library/parts/7/file.mkv"
    assert (access.direct, access.via_plex) == (0, 0)


async def test_a_share_that_stops_answering_holds_one_check_at_most(tmp_path, monkeypatch):
    """The final audit of 1.31.2: each try while the media share wasn't
    answering left one more thread stuck on it (they're shared with signing
    in, among others). While a check is still stuck, looking doesn't start
    another: it waits, as for a share that isn't answering."""
    from app import sources

    release = threading.Event()
    calls: list[int] = []

    def stuck(candidates):
        calls.append(1)
        release.wait(10)

    monkeypatch.setattr(sources, "_first_existing", stuck)
    monkeypatch.setattr(sources, "SHARE_WAIT_S", 0.1)
    check = sources.ShareCheck()
    library = SimpleNamespace(configured=False)
    item = _item("/media/1.mkv", 60 * S)
    try:
        for _ in range(3):
            got = await readable(SETTINGS, library, item, MediaAccess(), check)  # type: ignore[arg-type]
            assert got.source is None and got.transient
        assert len(calls) == 1
    finally:
        release.set()
    for _ in range(50):
        if not check.stuck():
            break
        await asyncio.sleep(0.02)
    await readable(SETTINGS, library, item, MediaAccess(), check)  # type: ignore[arg-type]
    assert len(calls) == 2  # (once it answered, it's checked again)


@needs_ffmpeg
async def test_shot_changes_under_the_music_all_play(tmp_path):
    """The cold open's last shot (orange, 1 s) starts under the theme
    music, and so does the program's first (cyan, 1.5 s): each overlap
    holds two cuts. The skip keeps both shots. (It took the cut nearest
    Plex's marker each time, and both were lost.)"""
    film = tmp_path / "1.mkv"
    sectioned(
        film,
        [("yellow", 10), ("orange", 1), ("lime", 7), ("cyan", 1.5), ("white", 20)],
    )
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(film))
    got = await finder.refined(
        [_item(str(film), 39500)], {"201": [Marker(INTRO, 9500, 20500)]}, look_s=60
    )
    assert abs(got["201"][0].start_ms - 11000) <= 60, got
    assert abs(got["201"][0].end_ms - 18000) <= 60, got


async def test_a_station_with_many_programs_to_look_at_doesnt_wait(tmp_path):
    """(Too many to be done in time: it waited the whole time anyway.)"""
    release = asyncio.Event()

    async def resolve(item: Item) -> ResolvedSource:
        await release.wait()
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    many = [_item(f"/{n}.mkv", 60 * S, str(n)) for n in range(cuts.LOOK_NOW_MOST + 1)]
    began = time.monotonic()
    await finder.refined(many, {i.rating_key: [Marker(INTRO, 5500, 14500)] for i in many}, 5)
    assert time.monotonic() - began < 0.5
    finder.stop()


def test_whats_scheduled_lately_is_always_kept(monkeypatch):
    """At the most kept, programs scheduled in the last day stay, however
    many: dropped, they were looked at again at the next update, and
    dropped again, round and round."""
    monkeypatch.setattr(cuts, "MOST_PROGRAMS", 3)
    day = 20000
    programs = {
        **{f"{n}:1": {"used": day - 10 - n, "edges": {}} for n in range(3)},
        **{f"{n}:1": {"used": day, "edges": {}} for n in range(10, 12)},
    }
    text, kept = cuts.saved_text(programs, day)
    assert kept == {"10:1", "11:1", "0:1"}
    assert json.loads(text) == {"version": 1, "programs": {k: programs[k] for k in kept}}
    today = {f"{n}:1": {"used": day - 1, "edges": {}} for n in range(5)}
    assert cuts.saved_text(today, day)[1] == set(today)


async def test_programs_past_the_most_kept_arent_looked_at_again(tmp_path, monkeypatch):
    monkeypatch.setattr(cuts, "MOST_PROGRAMS", 3)
    asked = []

    async def resolve(item: Item) -> ResolvedSource:
        asked.append(item.rating_key)
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    items = [_item(f"/{n}.mkv", 60 * S, str(n)) for n in range(5)]
    known = {i.rating_key: [Marker(INTRO, 5500, 14500)] for i in items}
    for _ in range(3):
        await finder.refined(items, known)
        if finder._worker is not None:
            await asyncio.wait_for(finder._worker, 5)
        await finder.save()
    assert sorted(asked) == ["0", "1", "2", "3", "4"]  # (each once)
    finder.stop()


async def test_a_file_left_is_tried_again_the_next_day(tmp_path, monkeypatch):
    """Files read through Plex while Plex is down for hours fail every try:
    they're left with their margins for a day, then tried again. (They were
    left until tapiOca restarted.)"""
    monkeypatch.setattr(cuts, "RETRY_S", (0.01, 0.01, 0.01))
    monkeypatch.setattr(cuts, "LEFT_FOR_S", 0.3)
    film = tmp_path / "1.mkv"
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(film))
    item = _item(str(film), 37 * S)
    known = {"201": [Marker(INTRO, 5500, 14500)]}
    await finder.refined([item], known)
    await asyncio.wait_for(finder._worker, 30)
    assert set(finder._left) == {"201:37000"}
    await finder.refined([item], known)
    assert finder._worker.done()  # (not yet)
    if shutil.which("ffmpeg"):
        sectioned(film, [("yellow", 7), ("lime", 6), ("cyan", 20), ("magenta", 4)])
    await asyncio.sleep(0.3)
    got = await finder.refined([item], known, look_s=30)
    assert not finder._left
    if shutil.which("ffmpeg"):
        assert abs(got["201"][0].start_ms - 7000) <= 60, got


async def test_saving_is_worked_out_off_the_event_loop(tmp_path, monkeypatch):
    """(At 50,000 programs, working out the file took 0.3 s on the loop.)"""
    threads = []
    real = cuts.saved_text

    def saved_text(programs, day):
        threads.append(threading.current_thread())
        return real(programs, day)

    monkeypatch.setattr(cuts, "saved_text", saved_text)

    async def resolve(item: Item) -> ResolvedSource:
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    item = _item("/x.mkv", 60 * S)
    await finder.refined([item], {"201": [Marker(INTRO, 5500, 14500)]})
    await asyncio.wait_for(finder._worker, 5)
    await finder.save()
    assert threads and threading.main_thread() not in threads
    assert "201:60000" in json.loads((tmp_path / cuts.FILE).read_text())["programs"]


async def test_cuts_json_is_read_once_by_its_first_callers(tmp_path, monkeypatch):
    """Two stations checked at once as tapiOca starts: what the first
    found while the second was still reading cuts.json was lost."""
    reads = []
    real = cuts.CutFinder._from_file

    def slow(self):
        reads.append(1)
        time.sleep(0.3)
        return real(self)

    monkeypatch.setattr(cuts.CutFinder, "_from_file", slow)

    async def resolve(item: Item) -> ResolvedSource:
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    a, b = _item("/a.mkv", 60 * S, "201"), _item("/b.mkv", 60 * S, "202")
    marked = [Marker(INTRO, 5500, 14500)]
    await asyncio.gather(
        finder.refined([a], {"201": marked}, look_s=5), finder.refined([b], {"202": marked})
    )
    await asyncio.wait_for(finder._worker, 5)
    assert len(reads) == 1
    assert finder.ready(a, marked) and finder.ready(b, marked)
    finder.stop()


async def test_whats_found_in_the_background_reaches_the_stations_twice_a_day(tmp_path):
    """Programs are looked at one at a time, and each hour's finds moved
    skips again: a station took a new schedule, and Plex a new guide, every
    hour for days. What's found now waits to reach the stations together,
    12 hours after they were last given any."""

    async def resolve(item: Item) -> ResolvedSource:
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    item = _item("/x.mkv", 60 * S)
    known = {"201": [Marker(INTRO, 5500, 14500)]}
    await finder.refined([item], known)
    await asyncio.wait_for(finder._worker, 5)
    finder._keep(item, {"start:5500": [7000], "end:14500": [13000]})  # (found, say)
    assert finder.ready(item, known["201"]) and not finder.due()
    finder.show()
    assert (await finder.refined([item], known))["201"] == [Marker(INTRO, 7500, 12500)]
    finder._shown_at -= cuts.SHOW_EVERY_S
    assert finder.due()
    finder.show()
    assert (await finder.refined([item], known))["201"] == [Marker(INTRO, 7000, 13000)]
    assert finder.placed == {"201"} and not finder.due()
    # What's waited for as a station is saved reaches it at once (see also
    # test_cuts_are_found_kept_and_used).
    other = _item("/y.mkv", 60 * S, "202")
    await finder.refined([other], {"202": known["201"]}, look_s=5)
    assert finder.placed == {"201", "202"}
    finder.stop()


def test_saving_writes_a_program_at_a_time(monkeypatch):
    """One json.dumps of 50,000 programs held the event loop for over 0.1 s,
    on any thread (it never lets go of Python's lock). Written a program at
    a time, the loop gets its turns."""
    biggest = []

    class Watched:
        loads = staticmethod(json.loads)

        @staticmethod
        def dumps(value, **kw):
            biggest.append(len(value) if isinstance(value, dict) else 0)
            return json.dumps(value, **kw)

    monkeypatch.setattr(cuts, "json", Watched)
    day = cuts.today()
    edges = {"start:90000": [91000], "end:150000": [148000]}
    programs = {f"{n}:1320000": {"used": day, "edges": edges} for n in range(1000)}
    text, kept = cuts.saved_text(programs, day)
    assert max(biggest) <= 2  # ("used" and "edges")
    assert json.loads(text) == {"version": 1, "programs": programs} and len(kept) == 1000


def _running(word: str) -> list[int]:
    """Processes whose command line has `word` in it (by their PIDs)."""
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            with contextlib.suppress(OSError):
                if word.encode() in (entry / "cmdline").read_bytes():
                    found.append(int(entry.name))
    return found


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="needs ffprobe")
async def test_stopping_stops_what_is_being_read(tmp_path):
    """tapiOca stopping while a file is being opened: the reading stops
    with it. (Opening went on, and its process outlived tapiOca's loop.)"""
    stuck = tmp_path / "stuck.ts"
    os.mkfifo(stuck)  # (nothing ever arrives: opening it waits)
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(stuck))
    await finder.refined([_item(str(stuck), 60 * S)], {"201": [Marker(INTRO, 5500, 14500)]})
    for _ in range(50):
        if _running(str(stuck)):
            break
        await asyncio.sleep(0.05)
    assert _running(str(stuck))
    await finder.close()
    assert not _running(str(stuck))


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="needs ffprobe")
def test_stopping_stationplay_stops_what_is_being_read(tmp_path, monkeypatch):
    """The final audit of 1.31.2: tapiOca itself stopping (not only the
    finder) stops a file being opened in the background, and waits for it a
    moment at most, after what matters more (alerts kept to send, streams
    ended)."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    stuck = tmp_path / "stuck.ts"
    os.mkfifo(stuck)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
    )
    with TestClient(app) as client:
        finder = app.state.ctx.markers.cuts
        finder.resolve = _reads(stuck)
        item = _item(str(stuck), 60 * S)
        client.portal.call(finder.refined, [item], {"201": [Marker(INTRO, 5500, 14500)]})
        for _ in range(100):
            if _running(str(stuck)):
                break
            time.sleep(0.05)
        assert _running(str(stuck))
        began = time.monotonic()
    assert not _running(str(stuck))
    assert time.monotonic() - began < cuts.CLOSE_WAIT_S + 3


def test_stopping_stationplay_keeps_alerts_and_ends_streams_before_cuts(
    tmp_path, monkeypatch, caplog
):
    """The re-audit of 1.31.2: what matters more as tapiOca stops (the
    alerts not sent yet kept, streams ended) comes before waiting on a file
    being opened for its cuts; looking stops at once, at the start; and
    looking's saving runs even if an earlier step fails."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
    )
    said: list[str] = []
    ctx = app.state.ctx
    cancel, unsent, close = ctx.markers.cuts.cancel, ctx.notify.unsent, ctx.markers.cuts.close
    stop_all = ctx.hls_streams.stop_all

    def cancelling():
        said.append("cuts cancelled")
        cancel()

    def keeping():
        said.append("alerts kept")
        unsent()

    async def stopping(why):
        said.append("streams ended")
        await stop_all(why)
        raise RuntimeError("a stream that won't stop")

    async def closing():
        said.append("cuts closed")
        await close()

    monkeypatch.setattr(ctx.markers.cuts, "cancel", cancelling)
    monkeypatch.setattr(ctx.notify, "unsent", keeping)
    monkeypatch.setattr(ctx.hls_streams, "stop_all", stopping)
    monkeypatch.setattr(ctx.markers.cuts, "close", closing)
    closed = []
    monkeypatch.setattr(ctx.db, "close", lambda: closed.append("database"))

    class Station:
        """Stands in for a station's stream (the first won't stop)."""

        def __init__(self, number: int, name: str) -> None:
            self.number = number
            self._number, self._name = number, name

        async def stop(self, why: str) -> None:
            said.append(f"station {self.number} stopped")
            if self.number == 1:
                raise RuntimeError("it won't stop")

    caplog.set_level(logging.ERROR, logger="stationplay")
    with contextlib.suppress(Exception), TestClient(app):
        ctx.broadcasters.update({1: Station(1, "Cartoon Classics"), 2: Station(2, "Station 2")})
    assert closed == ["database"]  # (every step runs, whichever fails)
    assert said == [
        "cuts cancelled", "alerts kept", "streams ended", "station 1 stopped", "station 2 stopped",
        "cuts closed",
    ], said  # fmt: skip
    logged = [r.getMessage() for r in caplog.records if r.name == "stationplay"]
    assert "While stopping, ending the apps' streams didn't work" in logged, logged
    # (Named as the log names a station: the last audit of 1.31.2 found
    # "While stopping, stopping Station 1 didn't work".)
    assert "While stopping, ending station 1, Cartoon Classics, didn't work" in logged, logged


def test_stopping_stationplay_runs_every_step_when_cancelled(tmp_path, monkeypatch):
    """The last audit of 1.31.2: a step stopped by something that isn't an
    error (being cancelled) still lets every later step run, the database
    closed last, and is raised once they have."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
    )
    ctx = app.state.ctx
    ran: list[str] = []
    close = ctx.markers.cuts.close

    def cancelled():
        ran.append("alerts")
        raise asyncio.CancelledError

    async def closing():
        ran.append("cuts closed")
        await close()

    monkeypatch.setattr(ctx.notify, "unsent", cancelled)
    monkeypatch.setattr(ctx.markers.cuts, "close", closing)
    monkeypatch.setattr(ctx.db, "close", lambda: ran.append("database"))
    # (Raised through the test client's own thread, as concurrent.futures'.)
    with (
        pytest.raises((asyncio.CancelledError, concurrent.futures.CancelledError)),
        TestClient(app),
    ):
        pass
    assert ran == ["alerts", "cuts closed", "database"], ran


async def test_closing_waits_for_whats_being_read_a_moment_at_most(tmp_path):
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(tmp_path / "x.mkv"))
    going = True

    async def stubborn():
        while going:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(10)

    finder._worker = asyncio.create_task(stubborn())
    began = time.monotonic()
    await finder.close()
    assert time.monotonic() - began < cuts.CLOSE_WAIT_S + 1
    going = False
    finder._worker.cancel()


def test_looking_checks_the_share_one_check_at_a_time(tmp_path, monkeypatch):
    """The re-audit of 1.31.2: tapiOca's own reading for cuts goes through
    its one-check-at-a-time share check (it could be left out unnoticed)."""
    from fastapi.testclient import TestClient

    from app import sources
    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    release = threading.Event()
    calls: list[int] = []

    def stuck(candidates):
        calls.append(1)
        release.wait(10)

    monkeypatch.setattr(sources, "_first_existing", stuck)
    monkeypatch.setattr(sources, "SHARE_WAIT_S", 0.1)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
    )
    with TestClient(app) as client:
        try:
            ctx = app.state.ctx
            for _ in range(3):
                got = client.portal.call(ctx.markers.cuts.resolve, _item("/media/1.mkv", 60 * S))
                assert got.transient
            assert len(calls) == 1
        finally:
            release.set()  # (before tapiOca stops: it waits for its threads)


async def test_a_share_check_stuck_for_long_is_said_once(tmp_path, monkeypatch, caplog):
    """The re-audit of 1.31.2: a check that never comes back stops placing
    skips until tapiOca restarts; the log says so once it's been stuck
    that long (not before), once, and again only for another stuck check."""
    from app import sources

    caplog.set_level(logging.WARNING, logger="app.sources")
    release = threading.Event()
    monkeypatch.setattr(sources, "_first_existing", lambda candidates: release.wait(10))
    monkeypatch.setattr(sources, "SHARE_WAIT_S", 0.05)
    monkeypatch.setattr(sources, "STUCK_SAID_AFTER_S", 0.3)
    check = sources.ShareCheck()
    library = SimpleNamespace(configured=False)
    item = _item("/media/1.mkv", 60 * S)

    def stuck_lines() -> int:
        return sum("hasn't answered" in r.getMessage() for r in caplog.records)

    async def ask(times: int) -> None:
        for _ in range(times):
            await readable(SETTINGS, library, item, MediaAccess(), check)  # type: ignore[arg-type]
            await asyncio.sleep(0.05)

    try:
        await ask(3)  # (about 0.25 s: not that long yet)
        assert stuck_lines() == 0
        await ask(4)
        assert stuck_lines() == 1
        await ask(3)
        assert stuck_lines() == 1  # (once)
        release.set()
        for _ in range(50):
            if not check.stuck():
                break
            await asyncio.sleep(0.02)
        release.clear()
        await ask(8)  # (a fresh check, stuck again)
        assert stuck_lines() == 2
    finally:
        release.set()
    assert caplog.records[-1].getMessage() == (
        "The media share hasn't answered for over an hour. Placing skipped intros and credits "
        "waits until it does. Check the share, then restart tapiOca."
    )


async def test_a_program_read_after_it_was_left_isnt_said_unreadable(tmp_path, monkeypatch, caplog):
    """The re-audit of 1.31.2: a round can last days; a program left, asked
    again a day later in the same round and read then, was still named
    unreadable at the round's end. (Each step by hand, no worker.)"""
    caplog.set_level(logging.INFO, logger="app.cuts")
    monkeypatch.setattr(cuts, "LEFT_FOR_S", 0.0)
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(tmp_path / "x.mkv"))
    finder._worker = asyncio.get_running_loop().create_future()  # (so none starts)
    left = _item("/a.mkv", 60 * S, "200")
    other = _item("/b.mkv", 60 * S, "300")
    known = {k: [Marker(INTRO, 5500, 14500)] for k in ("200", "300")}
    await finder.refined([left, other], known)
    finder._began(set(finder._queue))
    k_left, k_other = cuts.program_key(left), cuts.program_key(other)
    finder._queue.pop(k_left)
    for _ in range(cuts.TRIES):
        finder._later.pop(k_left, None)
        finder._after(k_left, left, known["200"], cuts.FAILED)
    finder._went_on(k_left)
    assert k_left in finder._left
    # A day later, the round still going (the other not looked at yet): asked again, and read.
    await finder.refined([left], known)
    assert k_left not in finder._round.left  # (no longer left, nor counted as looked at)
    finder._queue.pop(k_left)
    finder._after(k_left, left, known["200"], cuts.DONE)
    finder._went_on(k_left)
    finder._queue.pop(k_other)
    finder._after(k_other, other, known["300"], cuts.DONE)
    finder._went_on(k_other)
    end = [r.getMessage() for r in caplog.records][-1]
    assert end == "Placing skipped intros and credits: done, 2 programs looked at.", end
    finder._worker.cancel()


def _by_hand(tmp_path) -> cuts.CutFinder:
    """A finder with no worker: each step is taken by hand."""
    finder = cuts.CutFinder(SETTINGS, tmp_path, _reads(tmp_path / "x.mkv"))
    finder._worker = asyncio.get_running_loop().create_future()  # (so none starts)
    return finder


@pytest.mark.parametrize("where", ["waiting", "to look at", "left", "being looked at"])
@pytest.mark.parametrize("markers", ["found again", "not yet"])
async def test_a_replaced_file_lets_its_old_one_go(tmp_path, monkeypatch, caplog, where, markers):
    """The audits of 1.31.2: a file replaced (a new length, so a new program
    key) while its old one was waiting to be tried again, still to be looked
    at, left, or being looked at, was two programs: the old one tried again
    for hours on a dead address, holding the round open, then named
    unreadable. However Plex lists the new one (with its markers again, or
    none yet), the old one is let go."""
    caplog.set_level(logging.INFO, logger="app.cuts")
    finder = _by_hand(tmp_path)
    old = replace(_item("/old.mkv", 60 * S, "200"), title="Old")
    new = replace(_item("/new.mkv", 61 * S, "200"), title="Old")
    other = _item("/b.mkv", 60 * S, "300")
    with_markers = {k: [Marker(INTRO, 5500, 14500)] for k in ("200", "300")}
    await finder.refined([old, other], with_markers)
    finder._began(set(finder._queue))
    k_old, k_other = cuts.program_key(old), cuts.program_key(other)
    if where != "to look at":
        finder._queue.pop(k_old)
        if where == "waiting":
            finder._after(k_old, old, with_markers["200"], cuts.FAILED)
            finder._went_on(k_old)
        elif where == "left":
            for _ in range(cuts.TRIES):
                finder._later.pop(k_old, None)
                finder._after(k_old, old, with_markers["200"], cuts.FAILED)
            finder._went_on(k_old)
        else:
            finder._current = k_old
    # Plex lists the new file.
    await finder.refined(
        [new, other], with_markers if markers == "found again" else {"300": with_markers["300"]}
    )
    assert k_old not in finder._queue and k_old not in finder._later and k_old not in finder._left
    if where == "being looked at":
        finder._current = None
        counts = finder._after(k_old, old, with_markers["200"], cuts.FAILED)  # (it was being read)
        assert not counts and k_old not in finder._later  # (not tried again)
        finder._went_on(None)  # (as the worker goes on after one that no longer counts)
    k_new = cuts.program_key(new)
    if k_new in finder._queue:
        finder._queue.pop(k_new)
        finder._after(k_new, new, with_markers["200"], cuts.DONE)
        finder._went_on(k_new)
    finder._queue.pop(k_other)
    finder._after(k_other, other, with_markers["300"], cuts.DONE)
    finder._went_on(k_other)
    looked = 2 if markers == "found again" else 1
    end = [r.getMessage() for r in caplog.records][-1]
    assert (
        end
        == f"Placing skipped intros and credits: done, {looked} program{'s' if looked > 1 else ''} looked at."
    ), end
    finder._worker.cancel()


async def test_a_program_looked_at_then_asked_again_and_replaced_counts_once(tmp_path):
    """The audit of 2d3a3b0: a program looked at in a round, asked again
    (Plex redid its markers) and then replaced, stayed counted as looked at
    after it was let go, so the count could pass the total."""
    finder = _by_hand(tmp_path)
    old = _item("/old.mkv", 60 * S, "200")
    other = _item("/b.mkv", 60 * S, "300")
    await finder.refined([old, other], {k: [Marker(INTRO, 5500, 14500)] for k in ("200", "300")})
    finder._began(set(finder._queue))
    k_old = cuts.program_key(old)
    finder._queue.pop(k_old)
    finder._after(k_old, old, [Marker(INTRO, 5500, 14500)], cuts.DONE)
    finder._went_on(k_old)
    # Plex redid its markers: asked again, then the file's replaced.
    await finder.refined([old], {"200": [Marker(INTRO, 7500, 16500)]})
    assert k_old in finder._queue
    await finder.refined([_item("/new.mkv", 61 * S, "200")], {})
    assert k_old not in finder._round.looked and k_old not in finder._round.keys
    finder._worker.cancel()


async def test_bulk_made_stations_go_first_and_never_wait(tmp_path):
    """The re-audit of 1.31.2: stations made several at a time (smart
    stations, Plex collections) had lost their place at the front along
    with the wait. Asked while another program is being looked at, theirs go
    to the front, and they come straight back."""
    stuck = asyncio.Event()

    async def resolve(item: Item) -> ResolvedSource:
        await stuck.wait()
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    known = {k: [Marker(INTRO, 5500, 14500)] for k in ("100", "200", "300")}
    await finder.refined([_item("/a.mkv", 60 * S, "100"), _item("/b.mkv", 60 * S, "200")], known)
    for _ in range(100):
        if finder._current:
            break
        await asyncio.sleep(0.01)
    began = time.monotonic()
    await finder.refined([_item("/c.mkv", 60 * S, "300")], known, look_s=cuts.FIRST_NO_WAIT_S)
    assert time.monotonic() - began < 0.1
    assert next(iter(finder._queue)) == "300:60000"
    stuck.set()
    await asyncio.wait_for(finder._worker, 10)


async def test_a_file_replaced_while_waiting_is_one_program(tmp_path, monkeypatch, caplog):
    """The re-audit of 1.31.2: a file replaced (a new length: a new program
    key) while its old one waited to be tried again was two programs, the
    old one named unreadable, holding the round open for hours. (Through the
    worker, as it runs.)"""
    caplog.set_level(logging.INFO, logger="app.cuts")
    monkeypatch.setattr(cuts, "RETRY_S", (30.0, 30.0, 30.0))

    async def resolve(item: Item) -> ResolvedSource:
        if item.duration_ms == 60 * S:
            return ResolvedSource(str(tmp_path / "missing.mkv"))  # (the old file: unreadable)
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    old = _item("/old.mkv", 60 * S, "200")
    new = _item("/new.mkv", 61 * S, "200")
    await finder.refined([old], {"200": [Marker(INTRO, 5500, 14500)]})
    for _ in range(200):
        if finder._later:
            break
        await asyncio.sleep(0.01)
    await finder.refined([new], {"200": [Marker(INTRO, 5500, 14500)]})
    await asyncio.wait_for(finder._worker, 10)
    assert not finder._later and not finder._tries
    assert [r.getMessage() for r in caplog.records][-1] == (
        "Placing skipped intros and credits: done, 1 program looked at."
    )


async def test_a_replaced_file_last_to_wait_ends_its_round(tmp_path, monkeypatch, caplog):
    """The audit of 2d3a3b0: the old file of one replaced, the last thing
    waiting, let go while Plex had no markers for the new one yet: the round
    never ended (no "done"), and the next round counted it."""
    caplog.set_level(logging.INFO, logger="app.cuts")
    monkeypatch.setattr(cuts, "RETRY_S", (30.0, 30.0, 30.0))

    async def resolve(item: Item) -> ResolvedSource:
        if item.rating_key == "200":
            return ResolvedSource(str(tmp_path / "missing.mkv"))  # (deleted: unreadable)
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    old = _item("/old.mkv", 60 * S, "200")
    other = _item("/b.mkv", 60 * S, "300")
    known = {k: [Marker(INTRO, 5500, 14500)] for k in ("200", "300")}
    await finder.refined([old, other], known)
    for _ in range(200):
        if finder._later and not finder._queue and finder._current is None:
            break
        await asyncio.sleep(0.01)
    new = _item("/new.mkv", 61 * S, "200")
    await finder.refined([new, other], {"300": known["300"]})  # (no markers for the new file yet)
    await asyncio.wait_for(finder._worker, 10)
    said = [r.getMessage() for r in caplog.records]
    assert said[-1] == "Placing skipped intros and credits: done, 1 program looked at.", said
    assert finder._round is None and not finder._tries
    # The next round counts only its own.
    caplog.clear()
    another = _item("/c.mkv", 60 * S, "400")
    await finder.refined([another], {"400": known["300"]})
    await asyncio.wait_for(finder._worker, 10)
    said = [r.getMessage() for r in caplog.records]
    assert said[0].endswith(
        "started, in the background (until a program is looked at, its skips keep a 2-second margin)"
    )
    assert said[-1] == "Placing skipped intros and credits: done, 1 program looked at.", said


async def test_the_only_program_replaced_while_being_read_ends_its_round(
    tmp_path, monkeypatch, caplog
):
    """The audit of 2d3a3b0: a round whose one program was replaced while
    it was being read (and its share then didn't answer) stayed open, with
    only "started" said; or it said "done, 0 programs looked at"."""
    caplog.set_level(logging.INFO, logger="app.cuts")
    monkeypatch.setattr(cuts, "PAUSE_S", 30.0)
    reading = asyncio.Event()
    go_on = asyncio.Event()

    async def resolve(item: Item) -> ResolvedSource:
        reading.set()
        await go_on.wait()
        return ResolvedSource(None, error="the media share isn't responding", transient=True)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    old = _item("/old.mkv", 60 * S, "200")
    await finder.refined([old], {"200": [Marker(INTRO, 5500, 14500)]})
    await asyncio.wait_for(reading.wait(), 5)
    await finder.refined([_item("/new.mkv", 61 * S, "200")], {})  # (replaced; no markers yet)
    go_on.set()
    await asyncio.wait_for(finder._worker, 10)
    said = [r.getMessage() for r in caplog.records if r.name == "app.cuts"]
    assert finder._round is None and not finder._queue, said
    # (Nothing of its own was looked at: never "done, 0 programs", but the
    # round that said "started" says it's done, as the README promises: the
    # last audit of 1.31.2.)
    assert said[-1] == (
        "Placing skipped intros and credits: done, with nothing left to look at "
        "(its files were replaced)."
    ), said
    assert sum(": done" in line for line in said) == 1, said
    assert not any("0 programs" in line for line in said), said


async def test_the_log_says_when_looking_starts_how_far_it_has_got_and_ends(
    tmp_path, monkeypatch, caplog
):
    """A big library takes hours to look at: the log says so as it starts,
    how far it's got now and then, and when it's done (the owner asked). A
    program that can't be read now is tried again within the same round, so
    the round ends once it's read (or left)."""
    caplog.set_level(logging.INFO, logger="app.cuts")
    monkeypatch.setattr(cuts, "PROGRESS_EVERY_S", 0.0)
    monkeypatch.setattr(cuts, "RETRY_S", (0.3, 0.3, 0.3))
    unreadable = {"103"}

    async def resolve(item: Item) -> ResolvedSource:
        if item.rating_key in unreadable:
            unreadable.clear()  # (read the second time)
            return ResolvedSource(str(tmp_path / "missing.mkv"))
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    items = [_item(f"/{n}.mkv", 60 * S, str(n)) for n in range(100, 104)]
    await finder.refined(items, {i.rating_key: [Marker(INTRO, 5500, 14500)] for i in items})
    await asyncio.wait_for(finder._worker, 10)
    said = [r.getMessage() for r in caplog.records]
    assert said[0] == (
        "Placing skipped intros and credits where the picture cuts: started, in the background "
        "(until a program is looked at, its skips keep a 2-second margin)"
    )
    assert "Placing skipped intros and credits: 1 of 4 programs looked at" in said
    assert "Placing skipped intros and credits: 3 of 4 programs looked at, 1 to try again" in said
    assert said[-1] == "Placing skipped intros and credits: done, 4 programs looked at."
    assert sum("started" in line for line in said) == 1
    finder.stop()


async def test_the_counts_go_by_program_not_by_try(tmp_path, monkeypatch, caplog):
    """The final audit of 1.31.2: a program tried again was counted again
    ("32 of 31 programs looked at"; "Placed ... of 15 programs" when none
    were), and programs waiting from before were taken off a new round's."""
    caplog.set_level(logging.INFO, logger="app.cuts")
    monkeypatch.setattr(cuts, "PROGRESS_EVERY_S", 0.0)
    monkeypatch.setattr(cuts, "RETRY_S", (0.05, 0.05, 0.05))
    bad = {str(n) for n in range(100, 105)}

    async def resolve(item: Item) -> ResolvedSource:
        if item.rating_key in bad:
            return ResolvedSource(str(tmp_path / "missing.mkv"))
        return ResolvedSource(None)

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    items = [
        replace(_item(f"/{n}.mkv", 60 * S, str(n)), title=f"Episode {n}") for n in range(100, 107)
    ]
    await finder.refined(items, {i.rating_key: [Marker(INTRO, 5500, 14500)] for i in items})
    await asyncio.wait_for(finder._worker, 10)
    said = [r.getMessage() for r in caplog.records]
    for line in said:
        if " of " in line and "looked at" in line and ": done," not in line:
            got = line.split(": ", 1)[1].split()
            assert int(got[0]) <= int(got[2]) == 7, line
    # (The last audit of 1.31.2: the end counted those that couldn't be read
    # apart from those looked at, so the Logs tab went from "6 of 7 programs
    # looked at" to "done, 2 programs looked at": it counts them as the
    # progress lines do, and says how many of them couldn't be read.)
    assert said[-1] == (
        "Placing skipped intros and credits: done, 7 programs looked at, and 5 of them couldn't "
        "be read (“Episode 100”, “Episode 101”, “Episode 102” and 2 more). Their skips keep a "
        "2-second margin, and they'll be tried again in a day."
    )
    # A new round later counts only its own.
    caplog.clear()
    bad.clear()
    more = [_item(f"/{n}.mkv", 60 * S, str(n)) for n in range(200, 202)]
    await finder.refined(more, {i.rating_key: [Marker(INTRO, 5500, 14500)] for i in more})
    await asyncio.wait_for(finder._worker, 10)
    assert [r.getMessage() for r in caplog.records][-1] == (
        "Placing skipped intros and credits: done, 2 programs looked at."
    )
    finder.stop()


async def test_files_that_never_read_dont_fill_the_log(tmp_path, monkeypatch, caplog):
    """The final audit of 1.31.2: each try again opened and closed a round of
    its own (two lines each), and every file left said so in a line of its
    own, so many unreadable files (or Plex down for hours) pushed real
    warnings off the Logs tab. Now: one round, a few names, and the rest
    counted."""
    caplog.set_level(logging.INFO, logger="app.cuts")
    monkeypatch.setattr(cuts, "RETRY_S", (0.02, 0.05, 0.1))

    async def resolve(item: Item) -> ResolvedSource:
        return ResolvedSource(str(tmp_path / "missing.mkv"))

    finder = cuts.CutFinder(SETTINGS, tmp_path, resolve)
    items = [_item(f"/{n}.mkv", 60 * S, str(n)) for n in range(100, 150)]
    await finder.refined(items, {i.rating_key: [Marker(INTRO, 5500, 14500)] for i in items})
    await asyncio.wait_for(finder._worker, 30)
    said = [r.getMessage() for r in caplog.records]
    assert sum("started" in line for line in said) == 1
    assert sum(line.startswith("Couldn't read") for line in said) <= cuts.LEFT_NAMED
    assert len(said) <= 8, said  # (200 tries of 50 files)
    assert said[-1].startswith(
        "Placing skipped intros and credits: done, 50 programs looked at, and 50 of them couldn't "
        "be read ("
    ), said[-1]
    finder.stop()
