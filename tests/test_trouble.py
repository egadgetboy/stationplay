"""While someone watches Media (1.30.0): trouble playing a file (a copy that
fails, an app saying it stopped) puts that file at the front of the queue
for a check there, and only what StationPlay finds puts it on the list; and
what's on the list as broken never plays in the apps, while another version
of it does."""

from __future__ import annotations

import logging
import re
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import applibrary, converting
from app import scanner as sc
from app.broken import DEEP_SCAN, TARGETED
from app.config import Settings
from app.db import ScanRecord
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex
from .test_e2e import ff
from .test_ondemand import TV
from .test_scanner import NOISY, burst, video_packets

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
LENGTH_S = 60
GLITCH_AT = 0.5  # (of its length)
NOW = int(time.time())


@pytest.fixture(scope="module")
def files(tmp_path_factory) -> dict[str, Path]:
    """A minute that plays fine, and the same with its picture scrambled
    halfway through."""
    d = tmp_path_factory.mktemp("trouble")
    clean = d / "clean.mkv"
    ff(
        "-f", "lavfi", "-i", NOISY, "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000",
        "-t", str(LENGTH_S), "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1",
        "-b:v", "1500k", "-maxrate", "2M", "-bufsize", "3M", "-c:a", "aac", "-shortest",
        str(clean),
    )  # fmt: skip
    data = bytearray(clean.read_bytes())
    _t, pos, size = next(
        p for p in video_packets(clean) if p[0] >= GLITCH_AT * LENGTH_S and p[2] >= 1500
    )
    burst(data, pos + size // 2, 0)
    glitch = d / "glitch.mkv"
    glitch.write_bytes(data)
    return {"clean": clean, "glitch": glitch}


def world(tmp_path: Path, files: dict[str, Path] | None = None) -> tuple[TestClient, LibraryPlex]:
    """Movies shared with the apps: 300 (scrambled halfway), 301 (fine)."""
    fp = LibraryPlex()
    fp.add_section("2", "Movies", "movie")
    for key, name in (("300", "glitch"), ("301", "clean")):
        path = tmp_path / f"{key}.mkv"
        if files:
            path.symlink_to(files[name])
        fp.add_movie(key, f"Movie {key}", str(path), LENGTH_S * 1000, section="2")
    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
        media_dir=str(tmp_path),
    )  # fmt: skip
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    app.state.ctx.play_transport = fp.transport()
    app.state.ctx.shared.save(["2"])
    return TestClient(app), fp


@needs_ffmpeg
def test_a_file_someone_had_trouble_with_is_checked_where_it_happened(tmp_path, files, caplog):
    caplog.set_level(logging.INFO)
    client, _fp = world(tmp_path, files)
    with client:
        ctx = client.app.state.ctx
        ctx.db.set_meta(sc.META_MEDIA_FROM, str(NOW + 3600))  # (nothing's new)
        at = GLITCH_AT * LENGTH_S
        ctx.scanner.target("300", "", at, "Tia's app said it stopped playing")
        ctx.scanner.target("301", "", at, "Tia's app said it stopped playing")
        assert ctx.scanner.waiting("300") and ctx.scanner.as_dict()["checking"] == 2
        client.portal.call(ctx.scanner.round)
        # Found where it happened: on the list, as the deep scan would judge it.
        entry = ctx.broken.entry("300")
        assert entry["problem"] == "damaged" and entry["foundBy"] == TARGETED
        # (From a little before, or as near it as a stretch can start, to the
        # end; the file's scrambled where it skips, so it breaks up there.)
        start = sc.fmt_offset(min(at - sc.STRETCH_BEFORE_S, LENGTH_S - sc.STRETCH_S))
        assert re.fullmatch(
            rf"Check from {start}: (the picture breaks up|it skips) around 0:(2[3-9]|3\d).*",
            entry["reason"],
        ), entry["reason"]
        # Nothing wrong: then its quick check too, and the file stays as it is.
        assert ctx.broken.entry("301") is None
        assert ctx.db.scan("301").quick == "ok"
        assert (
            "“Movie 301” (2000): StationPlay found nothing wrong with its file (Tia's app said it "
            "stopped playing), so it stays as it is"
        ) in caplog.text
        assert not ctx.scanner.waiting("300") and not ctx.scanner.waiting("301")
        assert ctx.db.get_meta(sc.META_TARGETS, "") == "[]"


def test_what_waits_is_kept_and_checked_after_a_restart(tmp_path):
    client, _fp = world(tmp_path)
    with client:
        ctx = client.app.state.ctx
        ctx.scanner.target("300", "", 30.0, "Tia's app said it didn't play", report=7, full=True)
        ctx.scanner.target("300", "", 31.0, "Sam reported No picture", report=8)
        [kept] = sc._json_list(ctx.db.get_meta(sc.META_TARGETS, ""))
        assert kept["reports"] == [7, 8] and kept["full"] and kept["at_s"] == 30.0
        # Elsewhere in it: that stretch, checked anew.
        ctx.scanner.target("300", "", 95.0, "Sam reported No picture", report=8)
        [kept] = sc._json_list(ctx.db.get_meta(sc.META_TARGETS, ""))
        assert kept["at_s"] == 95.0 and kept["stage"] == sc.STRETCH
        again = sc.Scanner(SimpleNamespace(db=ctx.db))
        assert again.waiting("300") and again._targets[0].reports == [7, 8]


def test_whats_wrong_only_by_the_network_changes_nothing(tmp_path, monkeypatch):
    """A check that can't read the file (a share gone quiet) tries again a
    few times, then gives up, saying so to the reports waiting; nothing
    goes on the list."""
    client, _fp = world(tmp_path)
    told: list[tuple[list[int], str, str]] = []
    with client:
        ctx = client.app.state.ctx
        ctx.scanner.on_checked = lambda reports, outcome, note: told.append(
            (reports, outcome, note)
        )
        monkeypatch.setattr(sc, "SKIPPED_RETRY_S", 0.0)

        async def unreachable(ctx_, item, version=""):
            return sc.ResolvedSource(None, item.file_path, None, "the share isn't responding",
                                     transient=True)  # fmt: skip

        monkeypatch.setattr(sc, "resolve", unreachable)
        ctx.scanner.target("300", "", 30.0, "Tia reported No sound", report=3)
        for _ in range(sc.TARGET_TRIES):
            client.portal.call(ctx.scanner.round)
        assert told == [([3], sc.COULDNT, "StationPlay couldn't check its file (the share isn't "
                         "responding)")]  # fmt: skip
        assert ctx.broken.keys() == set() and not ctx.scanner.waiting("300")


def test_the_queues_order(tmp_path, monkeypatch):
    """A station's program airing soon; a file someone had trouble with; new
    arrivals (the stations', then Media's); the weekly sweep."""
    fp = LibraryPlex()
    fp.add_show("100", "On The Air")
    for n in (1, 2, 3):
        fp.add_episode(f"20{n}", "100", 1, n, f"Air {n}", f"/tv/{n}.mkv", 20 * 60_000)
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Trouble", "/films/300.mkv", 90 * 60_000, section="2")
    fp.add_movie("301", "New", "/films/301.mkv", 90 * 60_000, section="2", added_at=NOW)
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "d")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    monkeypatch.setattr(sc, "SOON_S", 0.001)  # (only what's on now airs soon)
    with TestClient(app) as client:
        ctx = app.state.ctx
        made = client.post("/api/channels", json={"number": 4, "sources": [
            {"type": "show", "ratingKey": "100"}]})  # fmt: skip
        assert made.status_code == 201
        ctx.shared.save(["2"])
        ctx.db.set_meta(sc.META_MEDIA_FROM, str(NOW - 60))
        ctx.scanner.programs()
        [soon] = ctx.scanner.soon
        weekly, new = sorted({"201", "202", "203"} - {soon})
        long_ago = int((time.time() - sc.RECHECK_S - 2 * 86_400) * 1000)
        ctx.db.save_scan(ScanRecord(weekly, f"/tv/{weekly[-1]}.mkv", quick_ms=long_ago, quick="ok"))
        ctx.scanner.target("300", "", 600.0, "Tia's app said it stopped playing")
        order: list[str] = []

        async def quick(program, record):
            order.append(program.key)
            return sc.Verdict("ok")

        async def targeted(target):
            order.append(f"target {target.key}")
            ctx.scanner._done_with(target, sc.NOTHING)

        monkeypatch.setattr(ctx.scanner, "_quick", quick)
        monkeypatch.setattr(ctx.scanner, "_targeted", targeted)
        client.portal.call(ctx.scanner.round)
        assert order == [soon, "target 300", new, "301", weekly], order


def test_a_copy_that_fails_says_where(tmp_path):
    plan = converting.Plan(
        method=converting.CONVERT, why=(), starts=(0.0, 6.0, 12.0, 18.0), duration_s=24.0,
        audio=None, audio_codec="aac",
    )  # fmt: skip
    copy = converting.Copy("ffmpeg", "/films/x.mkv", plan, tmp_path / "pieces")
    said: list[tuple[float, str]] = []
    copy.trouble = lambda at_s, why: said.append((at_s, why))
    run = SimpleNamespace(encoder=converting.CPU, first=1, newest=1)
    copy._failed(run, "ffmpeg 1: Invalid data found when processing input")
    assert said == [(12.0, "ffmpeg 1: Invalid data found when processing input")]
    # On the GPU, it may be the GPU's fault: the CPU carries on, and that's all.
    copy.encoder = SimpleNamespace(is_gpu=True)
    copy._failed(SimpleNamespace(encoder=SimpleNamespace(is_gpu=True), first=3, newest=2), "x")
    assert len(said) == 1


def test_trouble_in_media_puts_the_file_first(tmp_path):
    client, fp = world(tmp_path)
    fp.describe("300", audio="dts")  # (a copy, for a TV without DTS)
    fp.files["300"] = b"a movie" * 100
    with client:
        ctx = client.app.state.ctx
        sam = client.post("/api/internal/play", json={
            "key": "300", "device": {**TV, "hls": ["ts"]}}).json()  # fmt: skip
        assert sam["method"] == "repackage" or sam["method"] == "convert"
        session = ctx.plays.find(sam["session"])
        # Making its copy fails, halfway: checked there.
        session.copy.trouble(1800.0, "ffmpeg 1: Invalid data found when processing input")
        [target] = ctx.scanner._targets
        assert (target.key, target.at_s) == ("300", 1800.0)
        assert target.why.startswith("making a copy for someone stopped (ffmpeg 1:")
        ctx.scanner._done_with(target, sc.NOTHING)
        # The app says it stopped (from 1.30.0, with its playing and where).
        said = {"kind": "library-stopped", "title": "Movie 300", "session": sam["session"],
                "positionMs": 754_000}  # fmt: skip
        assert client.post("/api/internal/problem", json=said).json() == {"ok": True}
        [target] = ctx.scanner._targets
        assert (target.key, target.at_s) == ("300", 754.0)
        assert target.why == "someone's app said it stopped playing"
        ctx.scanner._done_with(target, sc.NOTHING)
        # An app before 1.30.0 says only what it was: what this device played
        # last, where it last said it was.
        session.position_ms = 99_000
        said = {"kind": "library-failed", "title": "Movie 300"}
        assert client.post("/api/internal/problem", json=said).json() == {"ok": True}
        [target] = ctx.scanner._targets
        assert (target.key, target.at_s) == ("300", 99.0)
        ctx.scanner._done_with(target, sc.NOTHING)
        # A station's problem, or a playing that's no one's, isn't one.
        client.post("/api/internal/problem", json={"kind": "station-stopped", "station": 5})
        client.post("/api/internal/problem", json={**said, "session": "not-a-session"})
        assert ctx.scanner._targets == []
        # Nothing about the file changed.
        assert ctx.broken.keys() == set()


def a_second_version(fp: LibraryPlex) -> None:
    fp.describe("300", width=3840, height=2160, video="hevc", bitDepth=10)
    fp.add_version("300", 1920, 1080)


def test_a_broken_version_never_plays_while_another_does(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    client, fp = world(tmp_path)
    a_second_version(fp)
    fp.files["300"] = b"a movie" * 100
    with client:
        ctx = client.app.state.ctx
        movie = client.portal.call(ctx.library.entry, "300", True)
        uhd, hd = movie.media
        # The 4K version is found broken.
        ctx.broken.record(sc.item_of(movie, uhd), "Deep scan: the picture stops at 10:00 of 1:00",
                          None, uhd.file, 1, problem="broken", found=DEEP_SCAN, library="2")  # fmt: skip
        details = client.get("/api/internal/items/300").json()
        assert [(v["name"], v["problem"]) for v in details["versions"]] == [
            ("4K", "broken"), ("1080p", None),
        ]  # fmt: skip
        played = client.post("/api/internal/play", json={"key": "300", "device": TV}).json()
        assert played["version"] == hd.id and played["method"] == "direct"
        assert played["why"] == ["another version, as 4K can't play right now"]
        assert [v["problem"] for v in played["versions"]] == ["broken", None]
        assert "StationPlay found the 4K one broken" in caplog.text
        # Asked for by name, too.
        asked = client.post("/api/internal/play", json={"key": "300", "device": TV,
                                                        "version": uhd.id}).json()  # fmt: skip
        assert asked["version"] == hd.id and asked["why"]
        # The 1080p one asked for: nothing to say.
        fine = client.post("/api/internal/play", json={"key": "300", "device": TV,
                                                       "version": hd.id}).json()  # fmt: skip
        assert fine["version"] == hd.id and fine["why"] is None
        # Both broken: nothing plays, and the app is told so.
        ctx.broken.record(sc.item_of(movie, hd), "Check: no picture from 30:00 on", None, hd.file,
                          1, problem="broken", version=hd.id, library="2")  # fmt: skip
        refused = client.post("/api/internal/play", json={"key": "300", "device": TV})
        assert refused.status_code == 422
        assert refused.json()["detail"] == applibrary.ON_THE_LIST
        assert refused.json()["detail"] == "This one can't play right now. An Admin has been told."


def test_a_damaged_file_still_plays(tmp_path):
    client, fp = world(tmp_path)
    fp.files["301"] = b"a movie" * 100
    with client:
        ctx = client.app.state.ctx
        movie = client.portal.call(ctx.library.entry, "301", True)
        ctx.broken.record(sc.item_of(movie, movie.media[0]), "Deep scan: the sound drops out "
                          "around 12:00", None, movie.media[0].file, 1, problem="damaged",
                          found=DEEP_SCAN, library="2")  # fmt: skip
        played = client.post("/api/internal/play", json={"key": "301", "device": TV})
        assert played.status_code == 200 and played.json()["why"] is None
