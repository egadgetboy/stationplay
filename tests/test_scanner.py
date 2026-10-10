"""Checking files before they air: the quick check, the weekly sweep and the
overnight deep scan, against real damaged files."""

from __future__ import annotations

import itertools
import json
import logging
import random
import re
import shutil
import struct
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import scanner as sc
from app.config import Settings
from app.db import ScanRecord
from app.ffmpeg import ProbeResult, shortfall_allowed
from app.ffmpeg import probe as probe_file
from app.library import Library
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .test_e2e import ff

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

LENGTH_S = 150
# Where files are scrambled (as a share of their length), and (filled in by
# the files fixture) the time of the picture each one starts in.
BURSTS = {"one_glitch": [0.5], "two_glitches": [0.3, 0.7], "damaged": [0.22, 0.55, 0.9]}
BURST_AT: dict[str, list[float]] = {}
# The test files' picture: noise, the same every time (a random one, or
# frames encoded differently on a machine with more processors, would put
# the scrambled stretches somewhere else in the picture each run, and a
# stretch that happened to land where the decoder could cover it up
# wouldn't be found).
NOISY = "testsrc2=s=640x360:r=24000/1001,noise=alls=4:allf=t:all_seed=7"


def burst(data: bytearray, at: int, seed: int, size: int = 48 * 1024) -> None:
    """Scrambles a stretch of the file from byte `at`, as a bad download or
    disk would."""
    rng = random.Random(seed)
    data[at : at + size] = bytes(rng.randrange(256) for _ in range(size))


def video_packets(path: Path) -> list[tuple[float, int, int]]:
    """Each picture's time, where its data is in the file, and its size, in
    order."""
    probed = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
         "packet=pts_time,pos,size", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    packets = json.loads(probed).get("packets", [])
    return sorted(
        (float(p["pts_time"]), int(p["pos"]), int(p["size"]))
        for p in packets
        if "pts_time" in p and str(p.get("pos", "")).isdigit() and str(p.get("size", "")).isdigit()
    )


@pytest.fixture(scope="module")
def files(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("scan")
    clean = d / "clean.mkv"
    ff(
        "-f", "lavfi", "-i", NOISY,
        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", str(LENGTH_S),
        "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1", "-b:v", "1500k",
        "-maxrate", "2M", "-bufsize", "3M", "-c:a", "aac", "-shortest", str(clean),
    )  # fmt: skip
    data = clean.read_bytes()
    packets = video_packets(clean)
    out = {"clean": clean}
    for name, fractions in BURSTS.items():
        b = bytearray(data)
        BURST_AT[name] = []
        for n, f in enumerate(fractions):
            # (From the middle of a picture's data, so that picture breaks up,
            # and the next few with it.)
            t, pos, size = next(p for p in packets if p[0] >= f * LENGTH_S and p[2] >= 1500)
            burst(b, pos + size // 2, n)
            BURST_AT[name].append(t)
        out[name] = d / f"{name}.mkv"
        out[name].write_bytes(b)
    out["cut_short"] = d / "cut_short.mkv"
    out["cut_short"].write_bytes(data[: int(len(data) * 0.55)])
    out["not_video"] = d / "not_video.mkv"
    out["not_video"].write_bytes(b"this is not a video file " * 4000)
    # Healthy, but jumping into it makes the decoder complain (open GOPs,
    # as in TV recordings and Blu-ray remuxes).
    out["recording"] = d / "recording.ts"
    ff(
        "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30000/1001,noise=alls=4:allf=t:all_seed=7",
        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", str(LENGTH_S),
        "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
        "-x264-params", "open-gop=1:keyint=300:bframes=3",
        "-b:v", "1500k", "-c:a", "aac", "-f", "mpegts", str(out["recording"]),
    )  # fmt: skip
    out["sound_stops"] = d / "sound_stops.mkv"
    ff("-i", str(clean), "-map", "0", "-c:v", "copy", "-af", "atrim=0:50", str(out["sound_stops"]))

    def with_sound(name: str, sound: str, filters: str = "anull") -> None:
        """The clean file's picture with other sound (none, for "")."""
        out[name] = d / f"{name}.mkv"
        if not sound:
            ff("-i", str(clean), "-map", "0:v", "-c", "copy", str(out[name]))
            return
        ff(
            "-i", str(clean), "-f", "lavfi", "-t", str(LENGTH_S), "-i", sound, "-map", "0:v",
            "-map", "1:a", "-c:v", "copy", "-af", filters, "-c:a", "aac", str(out[name]),
        )  # fmt: skip

    def with_picture(name: str, filters: str) -> None:
        """The clean file with its picture changed."""
        out[name] = d / f"{name}.mkv"
        ff(
            "-i", str(clean), "-map", "0", "-vf", filters, "-fps_mode", "passthrough",
            "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "1500k", "-c:a", "copy",
            str(out[name]),
        )  # fmt: skip

    tone = "sine=f=440:sample_rate=48000"
    end = LENGTH_S - 40
    # The sound stops 40s before the end of the picture: cut off mid-sound...
    with_sound("sound_cut_off", tone, f"atrim=0:{end}")
    # ...or after fading out (a quiet ending), or with the picture black after it.
    with_sound("sound_fades_out", tone, f"afade=out:st={end - 6}:d=4,atrim=0:{end}")
    with_picture("black_after_the_sound", f"fade=out:st={end - 1}:d=1")
    ff(
        "-i", str(out["black_after_the_sound"]), "-map", "0", "-c:v", "copy",
        "-af", f"atrim=0:{end}", str(d / "black_after.mkv"),
    )  # fmt: skip
    out["black_after_the_sound"] = d / "black_after.mkv"
    with_sound("silent_track", "anullsrc=r=48000:cl=stereo")
    with_sound("silent_40s", tone, "volume=enable='between(t,60,100)':volume=0")
    with_sound("silent_20s", tone, "volume=enable='between(t,60,80)':volume=0")
    with_sound("silent_opening", tone, "volume=enable='lt(t,40)':volume=0")
    with_sound("sound_gap_40s", tone, "aselect='not(between(t,60,100))'")
    # The picture stops 30s before the end; the sound goes on.
    ff(
        "-i", str(clean), "-t", str(LENGTH_S - 30), "-map", "0:v", "-c", "copy",
        str(d / "picture.mkv"),
    )  # fmt: skip
    out["picture_cut_off"] = d / "picture_cut_off.mkv"
    ff(
        "-i", str(d / "picture.mkv"), "-i", str(clean), "-map", "0:v", "-map", "1:a",
        "-c", "copy", str(out["picture_cut_off"]),
    )  # fmt: skip
    with_sound("no_sound_track", "")
    with_picture("picture_gap_40s", "select='not(between(t,60,100))'")
    # Picture and sound both gone for 40s, as a recording's signal dropping out.
    out["dropout_40s"] = d / "dropout_40s.mkv"
    ff(
        "-i", str(out["picture_gap_40s"]), "-i", str(out["sound_gap_40s"]), "-map", "0:v",
        "-map", "1:a", "-c", "copy", str(out["dropout_40s"]),
    )  # fmt: skip
    with_picture("still_6s", "select='not(between(t,40,46))'")
    out["black"] = d / "black.mkv"
    ff(
        "-f", "lavfi", "-i", "color=c=black:s=640x360:r=24000/1001", "-f", "lavfi", "-i", tone,
        "-t", str(LENGTH_S), "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        str(out["black"]),
    )  # fmt: skip
    # Says (in its header) it's half as long as it plays.
    longer = bytearray(data)
    at = longer.find(b"\x44\x89\x88")  # the Matroska segment's Duration, a double
    ms = struct.unpack(">d", longer[at + 3 : at + 11])[0]
    longer[at + 3 : at + 11] = struct.pack(">d", ms / 2)
    out["plays_long"] = d / "plays_long.mkv"
    out["plays_long"].write_bytes(longer)
    return out


def library(
    tmp_path: Path, files: dict[str, Path], names: list[str]
) -> tuple[TestClient, FakePlex]:
    fp = FakePlex()
    fp.add_show("100", "Test Show")
    for n, name in enumerate(names, start=1):
        fp.add_episode(f"2{n:02d}", "100", 1, n, name, str(files[name]), LENGTH_S * 1000)
        fp.episodes[f"2{n:02d}"]["year"] = 2001
    app = create_app(
        Settings(
            plex_url="http://plex.test",
            plex_token="token",
            data_dir=tmp_path / "data",
            media_dir=str(tmp_path),
        ),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    return TestClient(app), fp


def make_station(client: TestClient) -> dict:
    made = client.post(
        "/api/channels",
        json={
            "number": 3,
            "orderMode": "rotate",
            "sources": [{"type": "show", "ratingKey": "100"}],
        },
    )
    assert made.status_code == 201, made.text
    return made.json()


def verdicts(client: TestClient) -> dict[str, tuple[str, str]]:
    """(problem, reason) of everything taken off the air, by title."""
    return {
        e["title"]: (e.get("problem", "broken"), e["reason"])
        for e in client.app.state.ctx.broken.entries()
    }


def test_where_the_quick_check_looks():
    assert sc.check_points(5) == [0.0]
    points = sc.check_points(2640)  # a 44-minute episode
    assert points[:4] == [0.0, 660.0, 1320.0, 1980.0]
    # The last point is as late as a file must still have picture, not to
    # count as cut short: a file a few seconds shorter than it says is fine.
    assert points[4] == 2640 - shortfall_allowed(2640) - sc.POINT_S == 2640 * 0.98 - 2
    assert sc.check_points(300)[-1] == 300 - 10 - sc.POINT_S  # at least 10s
    # Never more than a tenth short, though.
    assert sc.check_points(60)[-1] == 60 - 6 - sc.POINT_S


def test_the_quick_check_finds_whats_broken_and_leaves_the_rest(tmp_path, files):
    names = ["clean", "one_glitch", "cut_short", "not_video", "sound_stops"]
    client, _fp = library(tmp_path, files, names)
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        got = verdicts(client)
        assert set(got) == {"cut_short", "not_video", "sound_stops"}, got
        assert got["cut_short"][0] == "broken" and "cut short" in got["cut_short"][1]
        assert got["not_video"][0] == "broken"
        assert got["sound_stops"] == (
            "damaged",
            "Check: the sound stops at 0:50, 1:40 before the end",
        )
        scans = ctx.db.scans()
        assert scans["201"].quick == "ok" and scans["201"].quick_ms
        # Checked once; not again until next week.
        before = scans["201"].quick_ms
        client.portal.call(ctx.scanner.round)
        assert ctx.db.scans()["201"].quick_ms == before
        status = client.get("/api/scan").json()
        assert status["programs"] == 5 and status["quickChecked"] == 5


def deep_scan_all(client: TestClient, monkeypatch) -> None:
    ctx = client.app.state.ctx
    monkeypatch.setattr(ctx.scanner, "in_window", lambda now=None: True)
    # (A file a busy machine was too slow to check is checked again in the
    # next round, rather than in half an hour: the tests don't wait that long.)
    monkeypatch.setattr(sc, "SKIPPED_RETRY_S", 0.0)
    for _ in range(60):
        if not client.portal.call(ctx.scanner.round):
            break


def test_the_deep_scan_finds_damage_throughout_a_file(tmp_path, files, monkeypatch, caplog):
    names = ["clean", "one_glitch", "two_glitches", "damaged", "cut_short"]
    client, _fp = library(tmp_path, files, names)
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)  # the quick checks
        assert set(verdicts(client)) == {"cut_short"}
        deep_scan_all(client, monkeypatch)
        got = verdicts(client)
        print({k: v[1] for k, v in got.items()})
        # Even one place where the picture breaks up is damage.
        assert set(got) == {"cut_short", "one_glitch", "two_glitches", "damaged"}, got
        scans = ctx.db.scans()
        for key, name, places in (
            ("202", "one_glitch", 1), ("203", "two_glitches", 2), ("204", "damaged", 3)
        ):  # fmt: skip
            problem, reason = got[name]
            assert problem == "damaged" and scans[key].deep == "damaged"
            glitches = scans[key].glitches
            assert reason == "Deep scan: " + sc.glitch_reason(glitches, "aac"), reason
            # Each place the file was scrambled is found, and nothing else (it
            # skips there, or the picture or sound breaks up, or both).
            spots = sorted(at for _, at in glitches)
            near = 8  # (s: how far ahead of what's decoded ffmpeg's output is)
            for t in BURST_AT[name]:
                assert any(abs(at - t) < near for at in spots), (t, glitches)
            for at in spots:
                assert any(abs(at - t) < near for t in BURST_AT[name]), (at, glitches)
            assert len(re.findall(r"\d+:\d\d", reason)) >= places, reason
        assert scans["201"].deep == "ok" and scans["201"].note == ""
        assert scans["201"].glitches == [] and scans["201"].bad_minutes == []
        assert client.get("/api/scan").json()["deepScanned"] == 4
        # Scanned once: nothing more to do.
        assert not client.portal.call(ctx.scanner.round)


def test_sound_that_stops_before_the_picture_is_a_problem_only_if_somethings_lost(tmp_path, files):
    """Not when it faded out near the end, or the picture's black after it;
    and a film from before 1930 may well have no sound track."""
    names = [
        "sound_cut_off", "sound_fades_out", "black_after_the_sound", "sound_stops",
        "no_sound_track", "clean",
    ]  # fmt: skip
    client, _fp = library(tmp_path, files, names)
    with client:
        make_station(client)
        client.portal.call(client.app.state.ctx.scanner.round)
        assert verdicts(client) == {
            "sound_cut_off": ("damaged", "Check: the sound stops at 1:50, 0:40 before the end"),
            "sound_stops": ("damaged", "Check: the sound stops at 0:50, 1:40 before the end"),
            "no_sound_track": ("damaged", "Check: it has no sound track"),
        }


async def test_sound_stopping_in_the_end_credits_or_a_silent_film_is_fine(files):
    ctx = SimpleNamespace(settings=Settings())

    async def check(name: str, year: int | None = 2001, credits=()):
        source = str(files[name])
        probe = await probe_file(ctx.settings, source)

        async def credits_from() -> list[tuple[float, float]]:
            return list(credits)

        return await sc.quick_check(ctx, source, probe, year, credits_from)

    # Plex says the end credits run from 1:48: the sound stops in them (at 1:50).
    assert (await check("sound_cut_off", credits=[(108, 150)])).result == "ok"
    # They begin at 2:00: the sound stops before them; or it stops in an
    # earlier roll, with a scene after it.
    assert (await check("sound_cut_off", credits=[(120, 150)])).result == "damaged"
    assert (await check("sound_cut_off", credits=[(100, 112), (130, 150)])).result == "damaged"
    assert (await check("no_sound_track", year=1925)).result == "ok"
    assert (await check("no_sound_track", year=1930)).reason == "it has no sound track"
    # Without a year (a home video, say), there's no telling: left be.
    assert (await check("no_sound_track", year=None)).result == "ok"

    async def plex_down() -> list[tuple[float, float]]:
        raise sc.Unknown("Plex didn't say where the end credits are")

    source = str(files["sound_cut_off"])
    probe = await probe_file(ctx.settings, source)
    # Plex not answering about credits isn't the same as there being none.
    assert (await sc.quick_check(ctx, source, probe, 2001, plex_down)).result == "skipped"


async def test_a_still_picture_held_while_the_sound_plays_is_fine(files):
    """Some files hold one picture for a long time (an anime's end credits
    over one drawing): no picture for a while, sound playing, is fine.
    Neither picture nor sound is a dropout."""
    ctx = SimpleNamespace(settings=Settings())
    for name, expected in (("picture_gap_40s", "ok"), ("dropout_40s", "damaged")):
        source = str(files[name])
        probe = await probe_file(ctx.settings, source)
        # As if 2:04 long: the point halfway, 1:02, falls in the gap, which
        # runs on for more than 30s after it.
        probe.duration_s = 124.0
        got = await sc.quick_check(ctx, source, probe, 2001)
        assert got.result == expected, (name, got)
    assert got.reason == "no picture or sound for 30 seconds or more, starting at 1:02"


def test_the_deep_scan_finds_sound_and_picture_that_go_missing(tmp_path, files, monkeypatch):
    """What only decoding a whole file finds, and what looks like it but
    isn't a problem: a silent opening, a short silence, a picture held
    still (for 6s, and for 40s with the sound playing), sound that ends
    early over black."""
    names = [
        "silent_track", "silent_40s", "sound_gap_40s", "dropout_40s", "black", "plays_long",
        "silent_20s", "silent_opening", "still_6s", "picture_gap_40s", "sound_fades_out",
        "black_after_the_sound", "recording",
    ]  # fmt: skip
    client, _fp = library(tmp_path, files, names)
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        assert verdicts(client) == {}  # nothing the quick check can see
        deep_scan_all(client, monkeypatch)
        assert {k: v for k, (_, v) in verdicts(client).items()} == {
            "silent_track": "Deep scan: the sound track is silent all the way through",
            "silent_40s": "Deep scan: no sound from 1:00 to 1:40",
            "sound_gap_40s": "Deep scan: no sound from 1:00 to 1:40",
            "dropout_40s": "Deep scan: no sound from 1:00 to 1:40",
            "black": "Deep scan: the picture is black all the way through",
            "plays_long": (
                "Deep scan: it plays to 2:30, past its stated length of 1:15, so its ending would "
                "be cut off"
            ),
        }
        assert {e["problem"] for e in ctx.broken.entries()} == {"damaged"}
        off_air = ctx.broken.keys()
        assert all(r.deep == "ok" for k, r in ctx.db.scans().items() if k not in off_air)
        assert client.get("/api/scan").json()["deepScanned"] == len(names)


def test_a_silence_split_by_a_pause_in_the_scan_is_still_found():
    """A deep scan stopped partway (someone tuned in) and carried on from a
    little before: the two halves of a silence are one."""
    record = ScanRecord("1", "/tv/a.mkv")
    before = ScanRecord("1", "/tv/a.mkv")
    first = sc.Scanned(at=85.0, picture_to=85.0, silent_since=60.0)
    sc.take_in(record, before, first, 0.0)
    assert record.gaps == [["sound", 60.0, 85.0]] and record.sound_from_s == 0.0
    before = replace(record, gaps=list(record.gaps))
    second = sc.Scanned(at=150.0, picture_to=150.0, silences=[(75.0, 100.0)])
    sc.take_in(record, before, second, 75.0)
    assert record.gaps == [["sound", 60.0, 100.0]]
    assert (record.sound_from_s, record.sound_to_s) == (0.0, 150.0)
    probe = ProbeResult(ok=True, duration_s=150.0, audio_index=0)
    assert sc.judge(record, probe).reason == "no sound from 1:00 to 1:40"


@pytest.mark.parametrize(
    ("silence", "sound", "year", "credits", "expected"),
    [
        ((60.0, 95.0), (0.0, 150.0), 2001, None, "no sound from 1:00 to 1:35"),
        # Silent until 0:40 (a quiet opening), or after 2:00 (the end).
        ((0.0, 40.0), (40.0, 150.0), 2001, None, ""),
        ((120.0, 150.0), (0.0, 120.0), 2001, None, ""),
        # Too short to matter.
        ((60.0, 80.0), (0.0, 150.0), 2001, None, ""),
        # Then only a closing logo's sting, or silent end credits.
        ((95.0, 140.0), (0.0, 150.0), 2001, None, ""),
        ((90.0, 125.0), (0.0, 150.0), 2001, [(88.0, 150.0)], ""),
        ((90.0, 125.0), (0.0, 150.0), 2001, [(100.0, 150.0)], "no sound from 1:30 to 2:05"),
        # Silent in the first of two rolls of credits (a scene between them).
        ((90.0, 125.0), (0.0, 150.0), 2001, [(89.0, 126.0), (135.0, 150.0)], ""),
        # A silent film, whose sound track may be a placeholder.
        ((60.0, 95.0), (0.0, 150.0), 1925, None, ""),
    ],
)
def test_what_counts_as_a_dropout(silence, sound, year, credits, expected):
    record = ScanRecord("1", "/tv/a.mkv", picture_to_s=150.0, gaps=[["sound", *silence]])
    record.sound_from_s, record.sound_to_s = sound
    probe = ProbeResult(ok=True, duration_s=150.0, audio_index=0)
    assert sc.judge(record, probe, year, credits).reason == expected


def test_black_seen_again_where_a_scan_carried_on_counts_once():
    record = ScanRecord("1", "/tv/a.mkv")
    before = ScanRecord("1", "/tv/a.mkv", deep_at_s=50.0, black_s=50.0)
    # Carrying on from 0:40, it sees the black from there, again.
    sc.take_in(record, before, sc.Scanned(at=150.0, blacks=[(40.0, 150.0)]), 40.0)
    assert record.black_s == 150.0


def test_a_file_that_cant_be_checked_yet_waits_and_doesnt_hold_up_the_rest(
    tmp_path, files, monkeypatch
):
    client, _fp = library(tmp_path, files, ["clean", "one_glitch", "recording"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        real = sc.quick_check_item
        asked: list[str] = []

        async def slow_first(ctx_, item, station, record=None, *more):
            asked.append(item.rating_key)
            if item.rating_key == "201":
                return sc.Verdict("skipped", "timed out after 60s"), None
            return await real(ctx_, item, station, record, *more)

        monkeypatch.setattr(sc, "quick_check_item", slow_first)
        client.portal.call(ctx.scanner.round)
        assert asked == ["201", "202", "203"]
        assert set(ctx.db.scans()) == {"202", "203"}
        # Not asked again a minute later; after the wait, it is.
        asked.clear()
        client.portal.call(ctx.scanner.round)
        assert asked == []
        ctx.scanner._retry_at["201"] = 0
        monkeypatch.setattr(sc, "quick_check_item", real)
        client.portal.call(ctx.scanner.round)
        assert ctx.db.scans()["201"].quick == "ok"


def test_new_checks_look_again_at_what_the_old_ones_found(tmp_path, files, monkeypatch):
    """After an upgrade that changes the checks, every file is checked again;
    and what the quick check (or playing it, for ending a few seconds early)
    took off the air before is judged afresh, first."""
    names = ["clean", "one_glitch", "black_after_the_sound", "recording"]
    client, _fp = library(tmp_path, files, names)
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        items = {i.rating_key: i for i in ctx.db.latest_items(ctx.db.list_channels()[0].id)}
        # As an earlier version left things.
        now = int(time.time() * 1000)
        for key in ("201", "204"):
            path = str(files[names[int(key) - 201]])
            ctx.db.save_scan(ScanRecord(key, path, quick_ms=now, quick="ok", deep_ms=now))
        ctx.broken.record(items["202"], "Deep scan: the picture breaks up", 3, problem="damaged")
        ctx.broken.record(items["203"], "Check: no sound from 1:52", 3, problem="damaged")
        ctx.broken.record(items["204"], "file ended early at 2:22 of 2:30 (truncated?)", 3)
        ctx.db.set_meta(sc.META_CHECKS, "1")
        checked: list[str] = []
        real = sc.quick_check_item

        async def noting(ctx_, item, station, record=None, *more):
            checked.append(item.rating_key)
            return await real(ctx_, item, station, record, *more)

        monkeypatch.setattr(sc, "quick_check_item", noting)
        client.portal.call(ctx.scanner.round)
        assert checked == ["203", "204", "201"]
        assert set(verdicts(client)) == {"one_glitch"}  # the deep scan's finding stands
        scans = ctx.db.scans()
        assert scans["201"].quick == "ok" and scans["201"].deep_ms == 0
        assert ctx.db.get_meta(sc.META_CHECKS, "") == sc.CHECKS
        assert ctx.db.get_meta(sc.META_FIRST, "") == "[]"  # all checked
        # Not again.
        client.portal.call(ctx.scanner.round)
        assert checked == ["203", "204", "201"]


def test_a_deep_scan_that_reads_nothing_tries_another_night(tmp_path, files, monkeypatch):
    client, _fp = library(tmp_path, files, ["clean"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        monkeypatch.setattr(ctx.scanner, "in_window", lambda now=None: True)

        async def nothing(ctx_, source, start_s, *args, **kwargs):
            return sc.Scanned(at=start_s, picture_to=start_s)  # (say the share went away)

        monkeypatch.setattr(sc, "decode_through", nothing)
        client.portal.call(ctx.scanner.round)
        record = ctx.db.scans()["201"]
        assert not record.deep_ms and record.note.startswith("nothing could be read")
        assert verdicts(client) == {}


def test_a_new_file_that_cant_be_checked_yet_doesnt_set_the_scanner_spinning(
    tmp_path, files, monkeypatch
):
    client, fp = library(tmp_path, files, ["clean"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        monkeypatch.setattr(ctx.scanner, "in_window", lambda now=None: True)
        # Sonarr upgrades it, before its deep scan; the new file's still copying.
        fp.episodes["201"]["Media"][0]["Part"][0]["file"] = str(files["one_glitch"])

        async def copying(ctx_, item, station, record=None, *more):
            return sc.Verdict("skipped", "timed out after 60s"), None

        monkeypatch.setattr(sc, "quick_check_item", copying)
        client.portal.call(ctx.scanner.round)  # the deep scan finds the new file
        assert ctx.db.scans()["201"].quick == ""
        assert client.portal.call(ctx.scanner.round) is False  # checked; it waits
        assert client.portal.call(ctx.scanner.round) is False  # and nothing to do


def test_black_is_measured_by_time_not_by_keyframes():
    """Keyframes come unevenly (one at every cut): 50s of black with a two-
    second logo in it is mostly black, though 2 of its 7 keyframes aren't."""
    frames = [(0, 100), (10, 100), (20, 100), (25, 5), (27, 100), (30, 100), (40, 100)]
    assert sc.black_part(frames, 50.0) == pytest.approx(48 / 50)
    assert sc.black_part([(5, 100), (6, 0)], 10.0) == pytest.approx(1 / 5)
    assert sc.black_part([], 10.0) is None


async def test_a_picture_held_to_the_end_with_the_sound_playing_isnt_cut_short(files):
    """Some files hold their last frame a long time; jumping in after it
    began finds no new picture. If the picture says it runs to the end and
    the sound plays there, it's held, not cut short."""
    ctx = SimpleNamespace(settings=Settings())
    source = str(files["picture_cut_off"])  # (its picture stops at 2:00)
    probe = await probe_file(ctx.settings, source)
    assert (await sc.quick_check(ctx, source, probe, 2001)).result == "broken"
    probe.video_duration_s = LENGTH_S  # (as if its last frame ran to the end)
    assert (await sc.quick_check(ctx, source, probe, 2001)).result == "ok"


async def test_no_end_credits_marked_yet_on_a_new_arrival_means_cant_tell_yet():
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "New", "/tv/new.mkv", 60_000, added_at=int(time.time()))
    ctx = SimpleNamespace(
        library=Library(PlexClient("http://plex.test", "token", transport=fp.transport()))
    )
    item = SimpleNamespace(rating_key="201")
    with pytest.raises(sc.Unknown, match="hasn't looked"):
        await sc.credits_of(ctx, item)
    fp.episodes["201"]["addedAt"] = int(time.time()) - 3 * 86_400
    assert await sc.credits_of(ctx, item) == []  # (it has looked, by now)
    fp.set_markers(
        "201", ("intro", 0, 5_000), ("credits", 40_000, 45_000), ("credits", 50_000, 60_000, True)
    )
    assert await sc.credits_of(ctx, item) == [(40.0, 45.0), (50.0, 60.0)]
    fp.down = True
    with pytest.raises(sc.Unknown, match="didn't say"):
        await sc.credits_of(ctx, item)


@pytest.mark.parametrize(
    ("reason", "again"),
    [
        ("Check: no sound from 23:01", True),
        ("file ended early at 22:10 of 22:30 (truncated or damaged?)", True),
        ("file ended early at 1:03:00 of 1:04:00 (truncated or damaged?)", True),
        ("file ended early at 1:02:00 of 1:04:00 (truncated or damaged?)", False),
        ("file ended early at 12:00 of 22:30 (truncated or damaged?)", False),
        # (As it's said from 1.16.4.)
        ("the file ended at 22:10 of 22:30 (it may be cut short or damaged)", True),
        ("the file ended at 12:00 of 22:30 (it may be cut short or damaged)", False),
        ("Deep scan: the picture or sound breaks up in 4 different minutes", False),
        ("ffmpeg failed", False),
    ],
)
def test_what_new_checks_judge_again(reason, again):
    assert sc._judged_again({"reason": reason}) is again


def test_a_deep_scan_that_fails_tries_another_night(tmp_path, files, monkeypatch):
    client, _fp = library(tmp_path, files, ["clean"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        monkeypatch.setattr(ctx.scanner, "in_window", lambda now=None: True)

        async def fails(*args, **kwargs):
            raise RuntimeError("something nobody foresaw")

        monkeypatch.setattr(sc, "decode_through", fails)
        client.portal.call(ctx.scanner.round)  # (no exception: on to the next file)
        record = ctx.db.scans()["201"]
        assert not record.deep_ms and record.note.startswith("the scan failed")
        assert client.portal.call(ctx.scanner.round) is False  # not again tonight


def test_a_scan_carried_on_that_lands_at_the_end_starts_again(tmp_path, files, monkeypatch):
    client, _fp = library(tmp_path, files, ["clean"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        record = ctx.db.scans()["201"]
        record.deep_at_s, record.bad_minutes = 140.0, [1]
        ctx.db.save_scan(record)
        monkeypatch.setattr(ctx.scanner, "in_window", lambda now=None: True)
        real = sc.decode_through

        async def lands_at_the_end(ctx_, source, start_s, *args, **kwargs):
            if start_s:
                return sc.Scanned(at=start_s, picture_to=start_s)
            return await real(ctx_, source, start_s, *args, **kwargs)

        monkeypatch.setattr(sc, "decode_through", lands_at_the_end)
        client.portal.call(ctx.scanner.round)
        record = ctx.db.scans()["201"]
        assert (record.deep_at_s, record.bad_minutes, record.deep_ms) == (0.0, [], 0)
        client.portal.call(ctx.scanner.round)  # from the start, then
        assert ctx.db.scans()["201"].deep == "ok"


def test_playing_and_checking_agree_on_a_file_a_little_short():
    from app.broadcaster import played_whole

    episode = 22 * 60
    assert played_whole(episode - 20, episode)  # 2% of it: 26s
    assert not played_whole(episode - 30, episode)
    assert played_whole(7200 - 140, 7200) and not played_whole(7200 - 150, 7200)
    assert not played_whole(10, 12)  # a short file: a tenth of it at most
    assert not played_whole(100, None)
    for length in (12, 60, episode, 7200):
        assert sc.last_point(length) == pytest.approx(length - shortfall_allowed(length) - 2)


def test_the_deep_scan_stops_for_viewers_and_carries_on_later(tmp_path, files, monkeypatch):
    client, _fp = library(tmp_path, files, ["clean"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        monkeypatch.setattr(ctx.scanner, "in_window", lambda now=None: True)
        monkeypatch.setattr(sc, "WATCH_POLL_S", 0.2)
        # Read the file at 25x real time, so the scan is still going when
        # the viewer arrives however fast this machine decodes.
        real_args = sc._decode_args

        def paced(*args, **kwargs):
            cmd = real_args(*args, **kwargs)
            at = cmd.index("-i")
            return [*cmd[:at], "-readrate", "25", *cmd[at:]]

        monkeypatch.setattr(sc, "_decode_args", paced)
        # Someone tunes in shortly after the scan starts.
        started = time.monotonic()
        monkeypatch.setattr(ctx.scanner, "watching", lambda: time.monotonic() - started > 1.5)
        assert client.portal.call(ctx.scanner.round) is False
        record = ctx.db.scans()["201"]
        assert not record.deep_ms and 0 < record.deep_at_s < LENGTH_S
        assert ctx.scanner.state == "paused"
        # Nothing more while they watch.
        client.portal.call(ctx.scanner.round)
        assert ctx.db.scans()["201"].deep_at_s == record.deep_at_s
        # They stop: it carries on from where it got to, and finishes.
        monkeypatch.setattr(ctx.scanner, "watching", lambda: False)
        client.portal.call(ctx.scanner.round)
        done = ctx.db.scans()["201"]
        assert done.deep == "ok" and done.deep_ms and done.deep_at_s >= LENGTH_S - 1


def test_the_window_decides_when_deep_scans_run(tmp_path, files):
    client, _fp = library(tmp_path, files, ["clean"])
    with client:
        scanner = client.app.state.ctx.scanner
        assert scanner.window == (True, "01:00", "06:00")
        at = lambda hour, minute=0: time.mktime((2026, 9, 28, hour, minute, 0, 0, 0, -1))  # noqa: E731
        assert scanner.in_window(at(1)) and scanner.in_window(at(5, 59))
        assert not scanner.in_window(at(6)) and not scanner.in_window(at(0, 59))
        # Across midnight.
        put = client.put("/api/scan", json={"on": True, "start": "23:30", "end": "02:00"})
        assert put.status_code == 200 and put.json()["window"]["start"] == "23:30"
        assert scanner.in_window(at(23, 45)) and scanner.in_window(at(1, 30))
        assert not scanner.in_window(at(2)) and not scanner.in_window(at(12))
        # Off.
        client.put("/api/scan", json={"on": False, "start": "23:30", "end": "02:00"})
        assert not scanner.in_window(at(23, 45))
        for bad in ({"start": "25:00", "end": "02:00"}, {"start": "1:5", "end": "02:00"},
                    {"start": "02:00", "end": "02:00"}):  # fmt: skip
            assert client.put("/api/scan", json={"on": True, **bad}).status_code == 400


def test_retry_puts_a_file_back_on_the_air_for_good(tmp_path, files):
    client, _fp = library(tmp_path, files, ["sound_stops"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        assert set(verdicts(client)) == {"sound_stops"}
        assert client.delete("/api/broken/201").status_code == 204
        # A week later it's checked again, finds the same, and leaves it be.
        record = ctx.db.scans()["201"]
        record.quick_ms -= (sc.RECHECK_S + 2 * 86_400) * 1000
        ctx.db.save_scan(record)
        client.portal.call(ctx.scanner.round)
        assert verdicts(client) == {}
        assert ctx.db.scans()["201"].quick_ms > record.quick_ms


def test_a_new_file_is_checked_afresh(tmp_path, files):
    client, fp = library(tmp_path, files, ["clean"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        first = ctx.db.scans()["201"]
        first.deep_ms, first.deep = 1, "ok"
        ctx.db.save_scan(first)
        # Sonarr upgrades the episode: a new file, found at the next check.
        part = fp.episodes["201"]["Media"][0]["Part"][0]
        part["file"], part["size"] = str(files["cut_short"]), 12345
        record = ctx.db.scans()["201"]
        record.quick_ms = 1  # due
        ctx.db.save_scan(record)
        client.portal.call(ctx.scanner.round)
        fresh = ctx.db.scans()["201"]
        assert fresh.file == str(files["cut_short"]) and fresh.deep_ms == 0
        assert set(verdicts(client)) == {"clean"}  # the title's still "clean"


def test_new_arrivals_are_checked_first(tmp_path):
    ctx = SimpleNamespace()
    scanner = sc.Scanner(ctx)
    item = lambda k: SimpleNamespace(rating_key=k)  # noqa: E731
    slot = lambda k, start: SimpleNamespace(item=item(k), start_ms=start)  # noqa: E731
    now = int(time.time() * 1000)
    channel = SimpleNamespace(id=1, number=5)
    ctx.db = SimpleNamespace(
        list_channels=lambda: [channel], all_programs=lambda cid: [item("a"), item("b"), item("c")]
    )
    # (With a block's new program, too: see specials.py.)
    ctx.updater = SimpleNamespace(
        pending={1: SimpleNamespace(items=[item("new")], sets={"block:x": [item("toon")]})}
    )
    ctx.station = lambda cid: SimpleNamespace(
        between=lambda a, b: [slot("c", now + 1000), slot("a", now + 5000)]
    )
    order = [p.item.rating_key for p in scanner.programs()]
    assert order == ["new", "toon", "c", "a", "b"]


def test_records_round_trip(tmp_path):
    from app.db import Database

    db = Database(tmp_path / "db.sqlite")
    record = ScanRecord("5", "/tv/a.mkv", 10, quick_ms=3, quick="ok", bad_minutes=[1, 4])
    db.save_scan(record)
    assert db.scans()["5"] == record
    db.keep_on_air("5")
    assert db.scans()["5"].kept is True
    db.forget_scans(["5"])
    assert db.scans() == {}
    db.close()


def test_nothing_is_checked_while_plex_is_away(tmp_path, files):
    client, fp = library(tmp_path, files, ["clean", "one_glitch"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        fp.down = True
        assert client.portal.call(ctx.scanner.round) is False
        assert ctx.db.scans() == {} and verdicts(client) == {}
        fp.down = False
        client.portal.call(ctx.scanner.round)
        assert set(ctx.db.scans()) == {"201", "202"}


def test_a_file_that_cant_be_read_gets_another_night_first(tmp_path, files, monkeypatch):
    client, _fp = library(tmp_path, files, ["clean"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        monkeypatch.setattr(ctx.scanner, "in_window", lambda now=None: True)

        async def unreadable(ctx_, source, start_s, *args, **kwargs):
            return sc.Scanned(at=start_s + 30, unreadable=True)

        monkeypatch.setattr(sc, "decode_through", unreadable)
        client.portal.call(ctx.scanner.round)
        record = ctx.db.scans()["201"]
        assert record.tries == 1 and record.deep_at_s == 30 and not record.deep_ms
        assert verdicts(client) == {}
        # Not again tonight (a share can drop out for a while)...
        client.portal.call(ctx.scanner.round)
        assert ctx.db.scans()["201"].tries == 1
        # ...but the next night, failing at the same place again, it's broken.
        record.note = "couldn't be read at 0:30 on the night of 2000-01-01"
        ctx.db.save_scan(record)
        client.portal.call(ctx.scanner.round)
        got = verdicts(client)
        assert got["clean"] == (
            "broken",
            "Deep scan: the file can't be read at 0:50 (a disk or share error)",
        )


def test_jumping_into_a_healthy_file_isnt_damage(tmp_path, files, monkeypatch):
    """Decoders complain for a moment after a jump into a TV recording; the
    quick check (which jumps to five points) and a deep scan carried on
    several times (each a jump) mustn't count that."""
    client, _fp = library(tmp_path, files, ["recording"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        assert verdicts(client) == {} and ctx.db.scans()["201"].quick == "ok"
        monkeypatch.setattr(ctx.scanner, "in_window", lambda now=None: True)
        monkeypatch.setattr(sc, "WATCH_POLL_S", 0.2)
        for _ in range(3):  # someone keeps tuning in partway through
            started = time.monotonic()
            monkeypatch.setattr(
                ctx.scanner, "watching", lambda s=started: time.monotonic() - s > 1.0
            )
            client.portal.call(ctx.scanner.round)
        monkeypatch.setattr(ctx.scanner, "watching", lambda: False)
        client.portal.call(ctx.scanner.round)
        record = ctx.db.scans()["201"]
        assert record.deep == "ok" and record.bad_minutes == [], record
        assert verdicts(client) == {}


def test_file_checks_wait_while_someone_watches(tmp_path, files, monkeypatch):
    client, _fp = library(tmp_path, files, ["clean"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        monkeypatch.setattr(ctx.scanner, "watching", lambda: True)
        assert client.portal.call(ctx.scanner.round) is False
        assert "201" not in ctx.db.scans() and ctx.scanner.state == "paused"
        assert client.get("/api/scan").json()["state"] == "paused"
        monkeypatch.setattr(ctx.scanner, "watching", lambda: False)
        client.portal.call(ctx.scanner.round)
        assert ctx.db.scans()["201"].quick == "ok"


async def test_checks_go_one_at_a_time_while_someone_watches(monkeypatch):
    import asyncio

    from app import jobs

    monkeypatch.setattr(jobs, "WATCHING_REST_S", 0.05)
    ctx = SimpleNamespace(
        check_slots=asyncio.Semaphore(jobs.CHECK_CONCURRENCY),
        watching_checks=asyncio.Lock(),
        broadcasters={},
        plays=SimpleNamespace(now=list),
    )
    running, most = 0, 0

    async def check() -> None:
        nonlocal running, most
        async with jobs.check_turn(ctx):
            running += 1
            most = max(most, running)
            await asyncio.sleep(0.05)
            running -= 1

    await asyncio.gather(*(check() for _ in range(4)))
    assert most == jobs.CHECK_CONCURRENCY  # (no one watching)
    ctx.broadcasters = {1: SimpleNamespace(viewers={object()})}
    most = 0
    started = time.monotonic()
    await asyncio.gather(*(check() for _ in range(3)))
    assert most == 1
    assert time.monotonic() - started >= 3 * (0.05 + 0.05) - 0.02  # (with a rest after each)
    # Someone watching Media in the apps counts the same.
    ctx.broadcasters = {}
    ctx.plays = SimpleNamespace(now=lambda: [object()])
    most = 0
    await asyncio.gather(*(check() for _ in range(3)))
    assert most == 1


# Judging glitches by what they do (1.16.3) ------------------------------------------------

A = 48_000  # (a sample rate)


@pytest.mark.parametrize(
    ("line", "cost"),
    [
        # ffmpeg's word on a frame: a picture patched up (see the next
        # test), or not decoded at all...
        ("[vist#0:0/h264 @ 0x55d9] [warning] corrupt decoded frame", ("patched", 0.0)),
        ("[vist#0:0/hevc @ 0x55d9] [dec:hevc @ 0x55e0] [warning] corrupt decoded frame",
         ("patched", 0.0)),
        ("[vist#0:0/mpeg2video @ 0x5] [error] Error submitting packet to decoder: Invalid data "
         "found when processing input", ("picture", 0.0)),
        ("[vist#0:0/h264 @ 0x5] [dec:h264 @ 0x6] [error] Decoding error: Invalid data found when "
         "processing input", ("picture", 0.0)),
        # ...the sound costs a block of its format.
        ("[aist#0:1/ac3 @ 0x5] [dec:ac3 @ 0x6] [warning] corrupt decoded frame",
         ("sound", 1536 / A)),
        ("[aist#0:1/aac @ 0x5] [error] Error submitting packet to decoder: Invalid data found when "
         "processing input", ("sound", 1024 / A)),
        ("[aist#0:1/dts @ 0x5] [dec:dca @ 0x6] [error] Error submitting packet to decoder: Invalid "
         "data found when processing input", ("sound", 512 / A)),
        ("[aist#0:1/truehd @ 0x5] [dec:truehd @ 0x6] [error] Error submitting packet to decoder: "
         "Invalid data found when processing input", ("sound", 1 / 1200)),
        ("[aist#0:1/pcm_s16le @ 0x5] [warning] corrupt decoded frame", ("sound", 1024 / A)),
        # Part of the file skipped.
        ("[matroska,webm @ 0x5] [error] 0x00 at pos 14766665 (0xe15249) invalid as first byte of "
         "an EBML number", ("skip", 0.0)),
        ("[matroska,webm @ 0x5] [error] Element at 0x5d0bd1 ending at 0x5d4c9f exceeds containing "
         "master element ending at 0x5d4c9e", ("skip", 0.0)),
        ("[mov,mp4,m4a,3gp,3g2,mj2 @ 0x5] [error] stream 1, offset 0x24f12: partial file",
         ("skip", 0.0)),
        # The decoders' and demuxers' own detail isn't counted: where a frame
        # is lost, ffmpeg says so too; and some is about nothing seen or heard.
        ("[truehd @ 0x5576ac990600] [error] quant_step_size larger than huff_lsbs", None),
        ("[truehd @ 0x5] [warning] Lossless check failed - expected 53, calculated af.", None),
        ("[h264 @ 0x5] [error] error while decoding MB 33 18", None),
        ("[h264 @ 0x5] [error] mmco: unref short failure", None),
        ("[hevc @ 0x5] [error] Could not find ref with POC 21", None),
        ("[ac3 @ 0x5] [error] error decoding the audio block", None),
        ("[matroska,webm @ 0x5] [error] Duplicate element", None),
        ("[matroska,webm @ 0x5] [warning] Element at 0x1 ending at 0x2 exceeds containing "
         "master element ending at 0x1", None),
        ("[aist#0:1/ac3 @ 0x5] [info] corrupt decoded frame", None),
        ("frame=1200", None),
    ],
)  # fmt: skip
def test_what_a_lost_frame_costs(line, cost):
    got = sc.what_it_costs(line, A)
    if cost is None:
        assert got is None
    else:
        assert got is not None and got[0] == cost[0] and got[1] == pytest.approx(cost[1])
    # AAC at 44.1kHz: its frames are longer.
    assert sc.what_it_costs("[aist#0:1/aac @ 0x5] [warning] corrupt decoded frame", 44_100) == (
        "sound",
        pytest.approx(1024 / 44_100),
    )


def lost(*frames: tuple[float, str, float | str]) -> list[list]:
    """The glitches frames lost (at, kind, seconds of it) make; ("patching",
    a kind of picture) for a decoder patching one up."""
    got = sc.Scanned(at=0.0)
    for at, kind, seconds in frames:
        got.at = at
        if kind == "patching":
            got.patches(str(seconds))
        else:
            got.lost(kind, float(seconds))
    return got.glitches


def test_a_glitch_is_what_is_seen_or_heard():
    dts, aac, ac3 = 512 / A, 1024 / A, 1536 / A
    # Any picture broken up.
    assert lost((10, "picture", 0)) == [["picture", 10]]
    assert lost((10, "skip", 0)) == [["skip", 10]]
    # Sound: SOUND_HEARD_S or more at one spot.
    assert lost((10, "sound", aac)) == [["sound", 10]]
    assert lost((10, "sound", ac3)) == [["sound", 10]]
    assert lost((10, "sound", dts)) == []
    assert lost((10, "sound", dts), (10.6, "sound", dts)) == [["sound", 10.6]]
    assert lost((10, "sound", dts), (12, "sound", dts)) == []  # (two spots)
    truehd = [(10 + n / 1200, "sound", 1 / 1200) for n in range(23)]
    assert lost(*truehd) == []  # 19ms of TrueHD's 1/1200s blocks
    assert lost(*truehd, (10.1, "sound", 1 / 1200)) == [["sound", 10.1]]
    # One glitch at one spot, however many frames; each kind on its own.
    assert lost((10, "picture", 0), (10.4, "picture", 0), (10.9, "picture", 0)) == [["picture", 10]]
    assert lost((10, "picture", 0), (12, "picture", 0), (12.2, "sound", aac)) == [
        ["picture", 10],
        ["picture", 12],
        ["sound", 12.2],
    ]
    many = [(float(n), "picture", 0.0) for n in range(sc.MOST_GLITCHES + 50)]
    assert len(lost(*many)) == sc.MOST_GLITCHES


def test_a_patched_picture_counts_if_it_stays_on_screen():
    """One later pictures are built on (I, P), till the next whole picture;
    not one shown for an instant (a B-frame)."""
    assert lost((10, "patching", "P"), (10.3, "patched", 0)) == [["picture", 10.3]]
    assert lost((10, "patching", "I"), (10.3, "patched", 0)) == [["picture", 10.3]]
    assert lost((10, "patching", "B"), (10.3, "patched", 0)) == []
    assert lost((10, "patching", "b"), (10.3, "patched", 0)) == []
    # Each patched picture is the one the decoder said it was patching.
    assert lost(
        (10, "patching", "B"), (10.1, "patching", "P"), (10.2, "patched", 0), (10.3, "patched", 0)
    ) == [["picture", 10.3]]
    # Which it is isn't known (the decoder didn't say, or said it of a
    # picture never shown): it counts.
    assert lost((10, "patched", 0)) == [["picture", 10]]
    assert lost((10, "patching", "B"), (20, "patched", 0)) == [["picture", 20]]
    # A picture that couldn't be decoded at all counts.
    assert lost((10, "patching", "B"), (10.2, "picture", 0)) == [["picture", 10.2]]


def test_how_glitches_are_told():
    assert sc.glitch_reason([["picture", 751.3]]) == "the picture breaks up around 12:31"
    glitches = [["picture", 751.0], ["picture", 753.0], ["picture", 2882.0], ["sound", 3730.5]]
    assert sc.glitch_reason(glitches, "ac3") == (
        "the picture breaks up around 12:31 and 48:02; the sound (Dolby Digital) drops out around "
        "1:02:10"
    )
    assert sc.glitch_reason([["sound", 61.0]], "pcm_s24le") == "the sound drops out around 1:01"
    five = [["picture", 60.0 * n] for n in range(1, 6)]
    assert sc.glitch_reason(five) == (
        "the picture breaks up around 1:00, 2:00, 3:00 and 2 more places"
    )
    # Where it skips, the picture and sound breaking up are part of that.
    skips = [["skip", 45.0], ["picture", 46.0], ["sound", 42.0], ["picture", 100.0]]
    assert sc.glitch_reason(skips, "aac") == (
        "the picture breaks up around 1:40; it skips around 0:45 (part of the file is garbled there)"
    )
    # Scans that carried on (from a little before where they stopped) find
    # some twice: once each.
    together = sc._glitches_together(
        [["picture", 50.0], ["sound", 50.2]], [["picture", 50.6], ["picture", 70.0]]
    )
    assert together == [["picture", 50.0], ["sound", 50.2], ["picture", 70.0]]


def test_glitches_in_a_files_last_seconds_dont_count():
    probe = ProbeResult(ok=True, duration_s=150.0, audio_index=0, audio_codec="aac")

    def verdict(*glitches: list) -> sc.Verdict:
        record = ScanRecord("1", "/a.mkv", picture_to_s=150.0, sound_from_s=0.0, sound_to_s=150.0)
        record.glitches = [list(g) for g in glitches]
        return sc.judge(record, probe)

    assert verdict(["picture", 146.0], ["sound", 149.5]).result == "ok"
    assert verdict(["sound", 140.0], ["picture", 146.0]) == sc.Verdict(
        "damaged", "the sound (AAC) drops out around 2:20"
    )
    assert verdict() == sc.Verdict("ok")


@pytest.fixture(scope="module")
def sound_files(tmp_path_factory, files) -> dict[str, Path]:
    """The clean file's picture with sound in other formats, a few of its
    frames scrambled a minute in."""
    d = tmp_path_factory.mktemp("sound")
    out = {}
    for name, encoder, extra, frames in (
        ("ac3", "ac3", [], 4),
        ("dts", "dca", ["-strict", "-2"], 1),
        ("truehd", "truehd", ["-strict", "-2"], 4),
    ):  # fmt: skip
        raw = d / f"{name}.raw"
        ff(
            "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-ac", "2", "-t", str(LENGTH_S),
            "-c:a", encoder, *extra, "-f", name, str(raw),
        )  # fmt: skip
        data = bytearray(raw.read_bytes())
        rng = random.Random(1)
        per_s = len(data) / LENGTH_S
        for n in range(frames):
            at = int((SCRAMBLED_S + n * 0.04) * per_s) + 50
            data[at : at + 40] = bytes(rng.randrange(256) for _ in range(40))
        raw.write_bytes(data)
        out[name] = d / f"{name}.mkv"
        ff(
            "-i", str(files["clean"]), "-i", str(raw), "-map", "0:v", "-map", "1:a",
            "-c", "copy", str(out[name]),
        )  # fmt: skip
    return out


SCRAMBLED_S = 60.0


def test_sound_damage_is_judged_by_whats_lost(tmp_path, sound_files, monkeypatch):
    """Dolby Digital frames lost (32ms each): heard. One DTS frame (11ms):
    not. TrueHD's decoder complaining (its blocks are 1/1200s): not."""
    client, _fp = library(tmp_path, sound_files, ["ac3", "dts", "truehd"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)  # the quick checks
        assert verdicts(client) == {}
        deep_scan_all(client, monkeypatch)
        got = verdicts(client)
        assert set(got) == {"ac3"}, got
        problem, reason = got["ac3"]
        assert problem == "damaged"
        assert reason.startswith("Deep scan: the sound (Dolby Digital) drops out around "), reason
        # (Where it's heard: around one time, or a few, "0:53 and 1:02".)
        times = [sc._seconds(t) for t in re.findall(r"\d+:\d\d(?::\d\d)?", reason)]
        assert times and any(abs(at - SCRAMBLED_S) < 8 for at in times), reason
        scans = ctx.db.scans()
        assert scans["202"].deep == "ok" and scans["203"].deep == "ok"
        assert scans["202"].glitches == [] and scans["203"].glitches == []


def test_what_the_old_rule_took_off_the_air_is_judged_again(tmp_path, files, monkeypatch, caplog):
    """After the upgrade to judging glitches by what they do, files the deep
    scan found any in are scanned again: those it took off the air for them
    first, back on the air if they're fine; but not those you put back."""
    caplog.set_level(logging.INFO, "app.scanner")
    names = ["clean", "one_glitch", "damaged", "two_glitches", "sound_stops"]
    client, _fp = library(tmp_path, files, names)
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        items = {i.rating_key: i for i in ctx.db.latest_items(ctx.db.list_channels()[0].id)}
        # As 1.16.2 left things: the clean file off the air for decoders'
        # complaints (TrueHD's, say), one_glitch fine with a glitch, the
        # damaged one off the air, two_glitches put back on the air by you.
        now = int(time.time() * 1000)

        def scanned(key: str, deep: str, minutes: list[int], kept: bool = False) -> None:
            path = str(files[names[int(key) - 201]])
            ctx.db.save_scan(
                ScanRecord(key, path, quick_ms=now, quick="ok", deep_ms=now, deep=deep,
                           bad_minutes=minutes, kept=kept)
            )  # fmt: skip

        old = "Deep scan: the picture or sound breaks up in {} different minutes (from 0:00, 1:00)"
        scanned("201", "damaged", [0, 1, 2])
        ctx.broken.record(items["201"], old.format(3), 3, problem="damaged", found="deep scan")
        scanned("202", "ok", [1])
        scanned("203", "damaged", [0, 1, 2])
        ctx.broken.record(items["203"], old.format(3), 3, problem="damaged", found="deep scan")
        scanned("204", "damaged", [0, 1, 2], kept=True)
        scanned("205", "ok", [])
        ctx.db.set_meta(sc.META_CHECKS, sc.CHECKS)
        order: list[str] = []
        real = sc.decode_through

        async def noting(ctx_, source, *args, **kwargs):
            order.append(Path(source).stem)
            return await real(ctx_, source, *args, **kwargs)

        monkeypatch.setattr(sc, "decode_through", noting)
        deep_scan_all(client, monkeypatch)
        # Those off the air first; then the rest it found glitches in.
        assert order[:2] == ["clean", "damaged"] and order[2:] == ["one_glitch"], order
        got = verdicts(client)
        assert set(got) == {"one_glitch", "damaged"}, got  # (clean: back on the air)
        entries = {e["title"]: e for e in ctx.broken.entries()}
        assert entries["damaged"]["reason"].startswith("Deep scan: "), entries
        assert "different minutes" not in entries["damaged"]["reason"]
        assert entries["damaged"]["failures"] == 1  # (the same failure, judged again)
        assert entries["one_glitch"]["reason"].startswith("Deep scan: ")
        scans = ctx.db.scans()
        assert scans["201"].deep == "ok" and scans["201"].bad_minutes == []
        assert scans["204"].deep_ms == now and scans["205"].deep_ms == now  # (left)
        assert ctx.db.get_meta(sc.META_DEEP_RULES, "") == sc.DEEP_RULES
        assert ctx.db.get_meta(sc.META_AGAIN, "") == "[]"
        assert "clean” passed its rescan and is back on the air" in caplog.text
        # Once.
        client.portal.call(ctx.scanner.round)
        assert len(order) == 3


@pytest.fixture(scope="module")
def frame_files(tmp_path_factory) -> dict[str, Path]:
    """A file with B-frames, and copies with one picture garbled half a
    minute in: a B-frame (shown for an instant), a P-frame, an I-frame (later
    pictures are built on them)."""
    d = tmp_path_factory.mktemp("frames")
    clean = d / "clean_b.mkv"
    ff(
        "-f", "lavfi", "-i", NOISY,
        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", str(LENGTH_S),
        "-c:v", "libx264", "-preset", "veryfast", "-threads", "1",
        "-x264-params", "keyint=96:bframes=3", "-b:v", "1500k", "-c:a", "aac", "-shortest",
        str(clean),
    )  # fmt: skip
    probed = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
         "frame=pts_time,pkt_pos,pkt_size,pict_type", "-of", "csv=p=0", str(clean)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    frames = [line.split(",")[:4] for line in probed.splitlines() if line.count(",") >= 3]
    data = clean.read_bytes()
    out = {"clean_b": clean}
    for kind in ("B", "P", "I"):
        # (Garbling a picture doesn't always break it in the way ffmpeg names,
        # since the noise differs from run to run: the first pictures of the
        # kind just after GARBLED_S are tried, at a few places in each, until
        # one does.)
        near = [f for f in frames if GARBLED_S <= float(f[0]) < GARBLED_S + 6 and f[3] == kind]
        out[kind] = d / f"{kind}_frame.mkv"
        log = ""
        for (_, pos, size, _), share in itertools.product(near[:6], (2, 3, 4)):
            garbled = bytearray(data)
            at = int(pos) + int(size) // share
            for n in range(at, at + 8):
                garbled[n] ^= 0x5A
            out[kind].write_bytes(garbled)
            # (It's patched up: the test's about which of them is seen.)
            log = subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "level+info", "-i",
                 str(out[kind]), "-f", "null", "-"], capture_output=True, text=True,
            ).stderr  # fmt: skip
            if f"errors in {kind} frame" in log and "corrupt decoded frame" in log:
                break
        else:
            raise AssertionError(f"no {kind}-frame garbling ffmpeg names: {log[-2000:]}")
    return out


GARBLED_S = 30.0


def test_a_patched_picture_is_damage_only_if_it_stays_on_screen(tmp_path, frame_files, monkeypatch):
    client, _fp = library(tmp_path, frame_files, ["clean_b", "B", "P", "I"])
    with client:
        make_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)  # the quick checks
        assert verdicts(client) == {}
        deep_scan_all(client, monkeypatch)
        got = verdicts(client)
        assert set(got) == {"P", "I"}, got
        for kind in ("P", "I"):
            problem, reason = got[kind]
            assert problem == "damaged"
            assert reason.startswith("Deep scan: the picture breaks up around "), reason
            at = sc._seconds(reason.rsplit(" around ", 1)[1])
            assert abs(at - GARBLED_S) < 8, reason
        scans = ctx.db.scans()
        assert scans["202"].deep == "ok" and scans["202"].glitches == []
