"""A movie in several files (Plex's stacked parts: "cd1", "cd2"), played as
one program: reading its parts from Plex, where each part's time falls in a
station's slot, the file checks and the Broken files list, and Media's copy
that joins them. (Real ffmpeg, end to end: see test_e2e_parts.py.)"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import broken, catalog, converting, ondemand, plex
from app import scanner as sc
from app.broken import BrokenFiles
from app.catalog import Media, Track
from app.config import Settings
from app.db import Item
from app.main import create_app
from app.markers import across, pieces
from app.plex import PlexClient
from app.sources import MediaAccess, part_starts

from .fakeplex import FakePlex

MIN = 60_000


def stack(fp: FakePlex, key: str, *files: tuple[str, int | None], total: bool = True) -> None:
    """Plex's description of a movie in several files: one Media, a Part
    for each file (its path, and its length, or none), in order; the
    Media's length theirs together (unless `total` is False)."""
    entry = fp.episodes[key]
    media = entry["Media"][0]
    media["Part"] = [
        {
            "id": int(key) * 10 + n,
            "key": f"/library/parts/{int(key) * 10 + n}/1/file.mkv",
            "file": path,
            "size": 1000 * n,
            **({"duration": ms} if ms is not None else {}),
        }
        for n, (path, ms) in enumerate(files, 1)
    ]
    length = sum(ms or 0 for _, ms in files)
    entry["duration"] = length
    if total:
        media["duration"] = length
    else:
        media.pop("duration", None)


def movie(*parts: dict, duration: int | None = None) -> dict:
    """Plex's metadata for a movie with one version in `parts`."""
    media: dict = {"id": 77, "container": "mkv", "videoCodec": "h264", "Part": list(parts)}
    if duration is not None:
        media["duration"] = duration
    return {"ratingKey": "300", "type": "movie", "title": "Long Movie", "year": 1999,
            "duration": duration, "Media": [media]}  # fmt: skip


def part(n: int, ms: int | None, **more) -> dict:
    found = {"id": n, "key": f"/library/parts/{n}/1/file.mkv", "file": f"/films/cd{n}.mkv",
             "size": 100 * n, **more}  # fmt: skip
    if ms is not None:
        found["duration"] = ms
    return found


# 1. Reading every part -------------------------------------------------------------------


def test_a_version_in_one_file_is_read_as_before():
    version = plex.to_media(movie(part(1, 100 * MIN), duration=100 * MIN))[0]
    assert version.parts == () and not version.joined
    assert version.files == (version,)
    assert (version.file, version.part_key, version.size, version.duration_ms) == (
        "/films/cd1.mkv", "/library/parts/1/1/file.mkv", 100, 100 * MIN
    )  # fmt: skip
    # (Its length from the version, where its file doesn't say.)
    assert plex.to_media(movie(part(1, None), duration=90 * MIN))[0].duration_ms == 90 * MIN


def test_two_files_each_with_its_length_and_the_whole():
    m = movie(part(1, 100 * MIN), part(2, 80 * MIN), duration=180 * MIN)
    version = plex.to_media(m)[0]
    assert version.joined and len(version.files) == 2
    assert [(f.file, f.duration_ms, f.size) for f in version.parts] == [
        ("/films/cd1.mkv", 100 * MIN, 100), ("/films/cd2.mkv", 80 * MIN, 200)
    ]  # fmt: skip
    # The version: its first file's, but for its length and size (all of it).
    assert (version.file, version.duration_ms, version.size, version.id) == (
        "/films/cd1.mkv", 180 * MIN, 300, "77"
    )  # fmt: skip
    item = plex.to_item(m)
    assert item is not None and item.duration_ms == 180 * MIN
    assert (item.file_path, item.part_key) == ("/films/cd1.mkv", "/library/parts/1/1/file.mkv")
    assert [f.file for f in plex.files_of(m)] == ["/films/cd1.mkv", "/films/cd2.mkv"]


def test_three_files_and_one_without_a_length():
    m = movie(part(1, 40 * MIN), part(2, None), part(3, 30 * MIN), duration=105 * MIN)
    version = plex.to_media(m)[0]
    assert [f.duration_ms for f in version.parts] == [40 * MIN, None, 30 * MIN]
    assert version.duration_ms == 105 * MIN  # (Plex's whole, as it says it)
    # Without Plex's whole: theirs together, if each says; else not known.
    assert plex.to_media(movie(part(1, 40 * MIN), part(2, 30 * MIN)))[0].duration_ms == 70 * MIN
    unknown = movie(part(1, 40 * MIN), part(2, None))
    assert plex.to_media(unknown)[0].duration_ms is None
    assert plex.to_item(unknown) is None  # (no length at all: it can't be scheduled)
    unknown["duration"] = 70 * MIN
    assert plex.to_item(unknown).duration_ms == 70 * MIN


def test_what_each_file_holds_is_its_own():
    video = {"streamType": 1, "codec": "h264", "width": 1920, "height": 1080, "index": 0}
    old = {"streamType": 1, "codec": "mpeg4", "width": 720, "height": 400, "index": 0}
    sound = {"id": 5, "streamType": 2, "codec": "ac3", "channels": 6, "index": 1}
    m = movie(part(1, MIN, Stream=[video, sound]), part(2, MIN, Stream=[old]), duration=2 * MIN)
    version = plex.to_media(m)[0]
    first, second = version.parts
    assert (version.video, version.width) == (first.video, first.width) == ("h264", 1920)
    assert (second.video, second.width, second.audio) == ("mpeg4", 720, ())
    assert [t.codec for t in version.audio] == ["ac3"]


def test_only_a_path_on_plex_is_asked_for_with_the_token():
    """A file's address from Plex is asked for with its token; one that
    isn't a path on Plex (someone else's address) never is."""
    for key in ("@evil.test/x", "//evil.test/x", "/library/parts/1/x?y=1", "http://e.test/"):
        assert plex.to_media(movie(part(1, MIN, key=key)))[0].part_key is None, key
    assert plex.to_media(movie(part(1, MIN)))[0].part_key == "/library/parts/1/1/file.mkv"


async def test_plex_says_a_programs_files_now():
    fp = FakePlex()
    fp.add_movie("300", "Long Movie", "/films/cd1.mkv", 100 * MIN)
    stack(fp, "300", ("/films/cd1.mkv", 60 * MIN), ("/films/cd2.mkv", 40 * MIN))
    client = PlexClient("http://plex.test", "token", transport=fp.transport())
    files = await client.current_files("300")
    assert [(f.file, f.duration_ms) for f in files] == [
        ("/films/cd1.mkv", 60 * MIN), ("/films/cd2.mkv", 40 * MIN)
    ]  # fmt: skip
    fp.add_movie("301", "Short", "/films/short.mkv", 9 * MIN)
    assert [f.file for f in await client.current_files("301")] == ["/films/short.mkv"]
    fp.episodes["301"]["Media"][0]["Part"] = []
    assert await client.current_files("301") == ()


# 2. Where each part's time falls in a station's slot ----------------------------------


STARTS = [0.0, 3600.0, 6000.0]  # (three files: an hour, 40 minutes, and the rest)


def test_the_slot_starts_in_the_first_file():
    assert across(pieces(None, 100.0, 50.0), STARTS) == [(0, 100.0, 50.0)]
    # The whole program: each file in turn, the last to the end of the slot.
    assert across(pieces(None, 0.0, 7000.0), STARTS) == [
        (0, 0.0, 3600.0), (1, 0.0, 2400.0), (2, 0.0, 1000.0)
    ]  # fmt: skip


def test_the_join():
    assert across(pieces(None, 3590.0, 20.0), STARTS) == [(0, 3590.0, 10.0), (1, 0.0, 10.0)]
    # Tuning in just as the second starts.
    assert across(pieces(None, 3600.0, 60.0), STARTS) == [(1, 0.0, 60.0)]


def test_the_third_file():
    assert across(pieces(None, 6100.0, 100.0), STARTS) == [(2, 100.0, 100.0)]
    # (The last file runs on as long as it's played.)
    assert across(pieces(None, 6000.0, 9e4), STARTS) == [(2, 0.0, 9e4)]


def test_one_file_is_all_one():
    assert across(pieces(None, 12.5, 30.0), [0.0]) == [(0, 12.5, 30.0)]


def test_skipping_credits_across_the_files():
    """With its intro and credits skipped, the stretches that air are in
    the whole program's time (as Plex marks them), and split at the join."""
    segments = ((60_000, 3_590_000), (3_620_000, 6_500_000))  # (skips 3590-3620s)
    # 10s in (program time): from 70s of the file, to 3590; then 3620 on.
    plan = pieces(segments, 10.0, 3550.0)
    assert across(plan, STARTS) == [(0, 70.0, 3520.0), (1, 20.0, 30.0)]


async def test_where_each_file_starts(tmp_path, monkeypatch):
    """By the lengths Plex gives; one it doesn't is found from the file."""
    files = (
        Media("mkv", "h264", duration_ms=60 * MIN), Media("mkv", "h264", file="/films/cd2.mkv"),
        Media("mkv", "h264", duration_ms=10 * MIN),
    )  # fmt: skip
    asked: list[str] = []

    async def located(settings, library, key, media, access):
        from app.sources import ResolvedSource

        return ResolvedSource(f"/local{media.file}", media.file)

    async def probe(settings, source, **_):
        asked.append(source)
        from app.ffmpeg import ProbeResult

        return ProbeResult(ok=True, duration_s=1500.0)

    monkeypatch.setattr("app.sources.locate", located)
    monkeypatch.setattr("app.sources.ff.probe", probe)
    got = await part_starts(Settings(), None, "300", files, MediaAccess())  # type: ignore[arg-type]
    assert got == [0.0, 3600.0, 5100.0] and asked == ["/local/films/cd2.mkv"]
    # Already known (opened to play): not probed again.
    asked.clear()
    assert await part_starts(Settings(), None, "300", files, MediaAccess(), {1: 1500.0}) == [
        0.0, 3600.0, 5100.0
    ]  # fmt: skip
    assert asked == []

    async def unreadable(settings, source, **_):
        from app.ffmpeg import ProbeResult

        return ProbeResult(ok=False, error="can't open it")

    monkeypatch.setattr("app.sources.ff.probe", unreadable)
    assert await part_starts(Settings(), None, "300", files, MediaAccess()) is None


# 3. The Broken files list says which part ---------------------------------------------


def test_an_entry_says_which_file_of_several(tmp_path):
    files = BrokenFiles(tmp_path / "broken-files.json")
    item = Item(0, 0, 180 * MIN, "300", "movie", "Long Movie", year=1999,
                file_path="/films/cd1.mkv")  # fmt: skip
    files.record(item, "Check: no picture from 40:12 on", 5, "/films/cd2.mkv", 2000,
                 part=(2, 3))  # fmt: skip
    entry = files.entry("300")
    assert entry["reason"] == "Check: no picture from 40:12 on, in part 2 of 3"
    assert (entry["file"], entry["part"], entry["parts"]) == ("/films/cd2.mkv", 2, 3)
    assert broken.entry_part(entry) == (2, 3)
    on_disk = json.loads((tmp_path / "broken-files.json").read_text())
    assert [e["ratingKey"] for e in on_disk["files"]] == ["300"]  # (one entry for the movie)
    # Found again as one file: it says nothing of parts.
    seen = {"300": entry["lastFailed"]}
    files.settle(seen, set(), {"300": {"reason": "Check: x", "part": None, "parts": None}})
    assert "part" not in files.entry("300") and broken.entry_part(files.entry("300")) is None


def test_part_words_and_keys():
    assert catalog.part_words(2, 3) == "part 2 of 3"
    assert broken.of_part("can't open the file", (2, 2)) == "can't open the file, in part 2 of 2"
    assert broken.of_part("can't open the file", None) == "can't open the file"
    assert broken.part_key("300", 1) == "300"  # (its first file's record is the version's)
    assert broken.part_key("300:77", 2) == "300:77/part2"
    assert broken.version_of_part("300:77/part2") == "300:77"
    assert broken.version_of_part("300") == "300"
    assert broken.entry_part({"part": 3, "parts": 2}) is None  # (nonsense: none)


# 4. Media: one program, its length the whole --------------------------------------------


def joined(*files: Media, **more) -> Media:
    first = files[0]
    total = sum(f.duration_ms or 0 for f in files)
    return Media(first.container, first.video, first.width, first.height, file=first.file,
                 duration_ms=total, parts=files, audio=first.audio, **more)  # fmt: skip


HD = Media("mkv", "h264", 1920, 1080, duration_ms=50 * MIN, file="/f/cd1.mkv",
           audio=(Track("1", "aac", default=True, index=1),))  # fmt: skip
TV = ondemand.device(["mkv"], [("h264", 1920, 1080, 8)], [], ["aac"])


def test_a_movie_in_several_files_is_as_long_as_all_of_them():
    movie_ = joined(HD, HD)
    entry = catalog.Entry("300", catalog.MOVIE, "Long Movie", duration_ms=100 * MIN,
                          media=(movie_,))  # fmt: skip
    assert ondemand.length_of(entry, movie_) == 100 * MIN
    assert ondemand.length_of(entry) == 100 * MIN
    assert not ondemand.is_watched(60 * MIN, entry, ondemand.length_of(entry, movie_))
    assert ondemand.is_watched(91 * MIN, entry, ondemand.length_of(entry, movie_))


def test_each_file_must_play_and_an_app_that_takes_no_copy_cant_join_them():
    old = Media("avi", "mpeg4", 720, 400, duration_ms=50 * MIN, file="/f/cd2.avi")
    assert ondemand.unplayable(joined(HD, HD), TV) == []
    assert ondemand.unplayable(joined(HD, old), TV) == [
        "its file type (AVI)", "its picture's format (MPEG-4)"
    ]  # fmt: skip
    assert ondemand.unplayable(joined(HD, HD), TV, joins=False) == ["it's in 2 files"]
    entry = catalog.Entry("300", catalog.MOVIE, "Long Movie", media=(joined(HD, HD, id="a"),))
    assert ondemand.choose(entry, TV, joins=False) == (None, ["it's in 2 files"])
    assert ondemand.choose(entry, TV)[0] is entry.media[0]
    assert ondemand.joined_why(joined(HD, HD, HD)) == "its 3 files, played as one"


def test_a_picture_is_kept_as_it_is_only_if_every_file_has_the_same():
    assert converting.picture_copyable(joined(HD, HD), [], frozenset({"ts"}))
    smaller = Media("mkv", "h264", 1280, 720, duration_ms=50 * MIN)
    assert not converting.picture_copyable(joined(HD, smaller), [], frozenset({"ts"}))
    assert not converting.picture_copyable(joined(HD, Media("mkv", "")), [], frozenset({"ts"}))


def test_a_copy_of_several_files_has_pieces_of_each():
    starts = converting.pieces_of(
        [(0.0, converting.pieces_every(14.0)), (14.0, converting.pieces_every(9.5))]
    )
    assert starts == (0.0, 6.0, 12.0, 14.0, 20.0)  # (none spans the join)
    parts = (converting.Part("/f/cd1.mkv", 0.0, "0:1"), converting.Part("/f/cd2.mkv", 14.0, "0:2"))
    plan = converting.Plan(
        converting.CONVERT, (), starts, 23.5, Track("1", "aac", index=1), "aac", height=720,
        kbps=2000, parts=parts,
    )  # fmt: skip
    assert [plan.part_of(n) for n in range(5)] == [0, 0, 0, 1, 1]
    assert (plan.after(0), plan.after(1)) == (3, 5)
    playlist = converting.playlist(plan)
    assert playlist.count("#EXTINF:6.000,") == 3 and "#EXTINF:2.000," in playlist
    assert "#EXTINF:3.500," in playlist and "DISCONTINUITY" not in playlist
    first = converting.command("ffmpeg", "/f/cd1.mkv", plan, 1)
    assert first[first.index("-i") + 1] == "/f/cd1.mkv"
    assert first[first.index("-ss") + 1] == "6.000"
    assert first[first.index("-force_key_frames") + 1] == "12.000"  # (its own pieces only)
    assert first[first.index("-output_ts_offset") + 1] == "10"
    assert first[first.index("-map", first.index("-i")) :].count("0:1") == 1
    second = converting.command("ffmpeg", "/f/cd1.mkv", plan, 4)
    assert second[second.index("-i") + 1] == "/f/cd2.mkv"
    assert second[second.index("-ss") + 1] == "6.000"  # (20s in: 6s into the second file)
    assert second[second.index("-output_ts_offset") + 1] == "24"  # (its times: the program's)
    assert second[second.index("-force_key_frames") + 1] == "9.500"  # (to its own end)
    assert "0:2" in second and "0:1" not in second
    # Its first piece: from the file's start.
    third = converting.command("ffmpeg", "/f/cd1.mkv", plan, 3)
    assert "-ss" not in third and third[third.index("-i") + 1] == "/f/cd2.mkv"


# 6. The file checks check every part ----------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="needs ffmpeg"
)
PART_S = 30


@pytest.fixture(scope="module")
def part_files(tmp_path_factory) -> dict[str, Path]:
    from .test_e2e import ff
    from .test_scanner import NOISY, burst, video_packets

    d = tmp_path_factory.mktemp("part-files")
    out = {}
    for name, tone in (("cd1", 440), ("cd2", 660)):
        out[name] = d / f"Long Movie-{name}.mkv"
        ff(
            "-f", "lavfi", "-i", NOISY.replace("640x360", "320x180"),
            "-f", "lavfi", "-i", f"sine=f={tone}:sample_rate=48000", "-t", str(PART_S),
            "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1", "-b:v", "600k",
            "-c:a", "aac", "-shortest", str(out[name]),
        )  # fmt: skip
    data = out["cd2"].read_bytes()
    out["cd2-cut"] = d / "Long Movie-cd2.cut.mkv"
    out["cd2-cut"].write_bytes(data[: len(data) // 2])
    damaged = bytearray(data)
    _t, pos, size = next(p for p in video_packets(out["cd2"]) if p[0] >= 15 and p[2] >= 1500)
    burst(damaged, pos + size // 2, 1)
    out["cd2-glitch"] = d / "Long Movie-cd2.glitch.mkv"
    out["cd2-glitch"].write_bytes(damaged)
    return out


def checked(tmp_path: Path, *files: Path) -> tuple[TestClient, FakePlex]:
    """A station with one movie, in `files`."""
    fp = FakePlex()
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Long Movie", str(files[0]), PART_S * 1000 * len(files), section="2")
    stack(fp, "300", *((str(f), PART_S * 1000) for f in files))
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    return TestClient(app), fp


def on_a_station(client: TestClient) -> None:
    made = client.post(
        "/api/channels", json={"number": 3, "sources": [{"type": "movie", "ratingKey": "300"}]}
    )
    assert made.status_code == 201, made.text


@needs_ffmpeg
def test_the_quick_check_checks_every_part(tmp_path, part_files):
    client, fp = checked(tmp_path, part_files["cd1"], part_files["cd2-cut"])
    with client:
        on_a_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        listed = ctx.broken.entries()
        assert [(e["ratingKey"], e["part"], e["parts"], e["file"]) for e in listed] == [
            ("300", 2, 2, str(part_files["cd2-cut"]))
        ]  # fmt: skip
        reason = listed[0]["reason"]
        assert reason.startswith("Check: no picture from ") and reason.endswith(", in part 2 of 2")
        scans = ctx.db.scans()
        assert (scans["300"].file, scans["300"].quick) == (str(part_files["cd1"]), "ok")
        assert (scans["300/part2"].file, scans["300/part2"].quick) == (
            str(part_files["cd2-cut"]), "broken"
        )  # fmt: skip
        # The Admin's alert says which, and never a file's name.
        needing = ctx.reports.needing()
        assert needing[0][2] == "StationPlay found Long Movie (2000) broken in part 2 of 2"
        # Retry: that file stays on the air, though its check finds the same.
        assert client.delete("/api/broken/300").status_code == 204
        assert ctx.db.scan("300/part2").kept and not ctx.db.scan("300").kept
        client.portal.call(sc.quick_check_item, ctx, ctx.db.all_programs(1)[0], 3)
        assert ctx.broken.entries() == []
        # A new second file (it's replaced) that's whole: checked afresh, and fine.
        stack(fp, "300", (str(part_files["cd1"]), PART_S * 1000),
              (str(part_files["cd2"]), PART_S * 1000))  # fmt: skip
        verdict, _ = client.portal.call(sc.quick_check_item, ctx, ctx.db.all_programs(1)[0], 3)
        assert verdict.result == "ok" and not ctx.db.scan("300/part2").kept
        # In one file again: the second's record goes.
        stack(fp, "300", (str(part_files["cd1"]), PART_S * 1000))
        client.portal.call(sc.quick_check_item, ctx, ctx.db.all_programs(1)[0], 3)
        assert ctx.db.scan("300/part2") is None


@needs_ffmpeg
def test_the_deep_scan_scans_every_part(tmp_path, part_files, monkeypatch):
    from .test_scanner import deep_scan_all

    client, _fp = checked(tmp_path, part_files["cd1"], part_files["cd2-glitch"])
    with client:
        on_a_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)  # (the quick checks: fine)
        assert ctx.broken.entries() == []
        deep_scan_all(client, monkeypatch)
        scans = ctx.db.scans()
        assert scans["300"].deep == "ok" and scans["300/part2"].deep == "damaged"
        listed = ctx.broken.entries()
        assert [(e["part"], e["parts"]) for e in listed] == [(2, 2)]
        reason = listed[0]["reason"]  # (where it was scrambled: 15s in)
        assert reason.startswith("Deep scan: ") and " around 0:1" in reason, reason
        assert reason.endswith(", in part 2 of 2")
        assert client.get("/api/scan").json()["deepScanned"] == 1


def test_medias_files_of_a_version_in_several_are_each_due_a_check():
    entry = catalog.Entry("300", catalog.MOVIE, "Long Movie", duration_ms=2 * MIN,
                          media=(joined(HD, Media("mkv", "h264", file="/f/cd2.mkv")),))  # fmt: skip
    program = sc.versions_of(entry)[0]
    assert [f.file for f in program.files] == ["/f/cd1.mkv", "/f/cd2.mkv"]
    from app.db import ScanRecord

    first = ScanRecord("300", "/f/cd1.mkv", 1, quick_ms=1, quick="ok")
    assert sc._unchecked({"300": first}, program)  # (its second hasn't been checked)
    second = ScanRecord("300/part2", "/f/cd2.mkv", 1, quick_ms=1, quick="ok")
    scans = {"300": first, "300/part2": second}
    assert not sc._unchecked(scans, program)
    assert sc._deep_due(scans, program)
    for record in scans.values():
        record.deep_ms = 5
    assert not sc._deep_due(scans, program) and sc._deep_done(scans, "300")
    scans["300/part2"] = ScanRecord("300/part2", "/f/new-cd2.mkv", 1, quick_ms=1, quick="ok")
    assert sc._unchecked(scans, program)  # (its second file changed)


# Found by the cold audit of 1.31.0 ------------------------------------------------


@needs_ffmpeg
def test_an_admins_retry_on_a_later_file_survives_plex_being_down(tmp_path, part_files):
    """Plex down during a quick check (its nightly update, say) forgets
    nothing about the movie's later files: an Admin's Retry on file 2
    still holds once Plex is back."""
    client, fp = checked(tmp_path, part_files["cd1"], part_files["cd2-cut"])
    with client:
        on_a_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        assert [(e["part"], e["parts"]) for e in ctx.broken.entries()] == [(2, 2)]
        assert client.delete("/api/broken/300").status_code == 204
        assert ctx.db.scan("300/part2").kept
        item = ctx.db.all_programs(1)[0]
        fp.down = True
        client.portal.call(sc.quick_check_item, ctx, item, 3)
        kept = ctx.db.scan("300/part2")
        fp.down = False
        client.portal.call(sc.quick_check_item, ctx, item, 3)
        assert kept is not None and kept.kept
        assert ctx.broken.entries() == []


@needs_ffmpeg
def test_a_file_put_back_on_the_air_doesnt_hide_a_later_ones_problem(tmp_path, part_files):
    """An Admin's Retry on file 2 is about file 2 only: a cut-short file 3
    added later still takes the movie off the air, named as file 3."""
    third = tmp_path / "Long Movie-cd3.mkv"
    shutil.copy(part_files["cd2-cut"], third)
    client, fp = checked(tmp_path, part_files["cd1"], part_files["cd2-cut"])
    with client:
        on_a_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        assert client.delete("/api/broken/300").status_code == 204
        stack(fp, "300", (str(part_files["cd1"]), PART_S * 1000),
              (str(part_files["cd2-cut"]), PART_S * 1000), (str(third), PART_S * 1000))  # fmt: skip
        client.portal.call(sc.quick_check_item, ctx, ctx.db.all_programs(1)[0], 3)
        assert [(e["part"], e["parts"]) for e in ctx.broken.entries()] == [(3, 3)]


@needs_ffmpeg
def test_a_file_put_back_on_the_air_isnt_named_when_the_list_is_checked_again(tmp_path, part_files):
    """File 2 kept on by an Admin, file 3 broken and then replaced: checking
    the Broken files list again clears the movie, rather than listing it
    again for file 2, which the Admin kept on the air."""
    from app import jobs

    third = tmp_path / "Long Movie-cd3.mkv"
    shutil.copy(part_files["cd2-cut"], third)
    client, fp = checked(tmp_path, part_files["cd1"], part_files["cd2-cut"])
    with client:
        on_a_station(client)
        ctx = client.app.state.ctx
        client.portal.call(ctx.scanner.round)
        assert client.delete("/api/broken/300").status_code == 204
        stack(fp, "300", (str(part_files["cd1"]), PART_S * 1000),
              (str(part_files["cd2-cut"]), PART_S * 1000), (str(third), PART_S * 1000))  # fmt: skip
        client.portal.call(sc.quick_check_item, ctx, ctx.db.all_programs(1)[0], 3)
        assert [(e["part"], e["parts"]) for e in ctx.broken.entries()] == [(3, 3)]
        shutil.copy(part_files["cd1"], third)  # (a good file 3 in its place)
        client.portal.call(jobs.look_again, ctx, jobs.ListCheck(running=True), True)
        assert [(e["reason"], e["part"]) for e in ctx.broken.entries()] == []
