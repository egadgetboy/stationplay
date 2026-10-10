"""One process for every file (1.30.0): what the checks find is kept per
file, whoever plays it, a station or Media in StationPlay's apps; the
checks reach what's shared for Media, in one queue; and nothing is checked
while anyone watches, a station or Media."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import jobs
from app import scanner as sc
from app.broken import DEEP_SCAN, version_key
from app.config import Settings
from app.db import ScanRecord
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex
from .test_e2e import ff

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

LENGTH_S = 20
NOW = int(time.time())


@pytest.fixture(scope="module")
def clean(tmp_path_factory) -> Path:
    """A short file that plays fine, picture and sound."""
    path = tmp_path_factory.mktemp("every") / "clean.mkv"
    ff(
        "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24", "-f", "lavfi",
        "-i", "sine=f=440:sample_rate=48000", "-t", str(LENGTH_S), "-c:v", "libx264",
        "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path),
    )  # fmt: skip
    return path


def a_version(fp: LibraryPlex, key: str, media_id: int, path: str) -> None:
    """Another version of a program's file, as Plex lists it."""
    first = fp.episodes[key]["Media"][0]
    first.setdefault("id", int(key) * 10)
    part = {**first["Part"][0], "id": media_id, "key": f"/library/parts/{media_id}/1/file.mkv",
            "file": path}  # fmt: skip
    fp.episodes[key]["Media"].append({"id": media_id, "duration": first["duration"],
                                      "Part": [part]})  # fmt: skip


def a_file(folder: Path, clean: Path, name: str) -> str:
    """A file of its own for a program (the clean one, under its own name)."""
    path = folder / f"{name}.mkv"
    path.symlink_to(clean)
    return str(path)


def world(tmp_path: Path, clean: Path) -> tuple[TestClient, LibraryPlex]:
    """A show on a station (100: 201, 202), a show only in Media (110: 211,
    added lately), and movies only in Media (300, added lately, in two
    versions; 301, long ago), both libraries shared with the apps."""
    fp = LibraryPlex()
    fp.add_show("100", "On The Air")

    def file(name: str) -> str:
        return a_file(tmp_path, clean, name)

    for n in (1, 2):
        fp.add_episode(f"20{n}", "100", 1, n, f"Air {n}", file(f"20{n}"), LENGTH_S * 1000)
    fp.add_show("110", "Only In Media")
    fp.add_episode("211", "110", 1, 1, "Media 1", file("211"), LENGTH_S * 1000, added_at=NOW)
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "New Movie", file("300"), LENGTH_S * 1000, section="2", added_at=NOW + 1)
    a_version(fp, "300", 3002, file("300-2"))
    fp.add_movie("301", "Old Movie", file("301"), LENGTH_S * 1000, section="2")
    settings = Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
        media_dir=str(tmp_path),
    )  # fmt: skip
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    return TestClient(app), fp


def start(client: TestClient, since: int = NOW - 3600) -> SimpleNamespace:
    """The station, Media on (from `since`: what was added after it is
    new), and the order files are quick-checked in."""
    ctx = client.app.state.ctx
    made = client.post("/api/channels", json={"number": 4, "sources": [
        {"type": "show", "ratingKey": "100"}]})  # fmt: skip
    assert made.status_code == 201, made.text
    ctx.shared.save(["1", "2"])
    ctx.db.set_meta(sc.META_MEDIA_FROM, str(since))
    order: list[str] = []
    real = ctx.scanner._quick

    async def quick(program, record):
        order.append(program.key)
        return await real(program, record)

    ctx.scanner._quick = quick
    return SimpleNamespace(ctx=ctx, order=order, station=made.json())


def test_whats_new_in_media_is_checked_after_the_stations_programs(tmp_path, clean):
    client, _fp = world(tmp_path, clean)
    with client:
        w = start(client)
        client.portal.call(w.ctx.scanner.round)
        # The station's programs first; then what's new in Media, the newest
        # first, each version its own file; what was there before is left
        # for the overnight deep scan.
        assert w.order == ["201", "202", "300", "300:3002", "211"], w.order
        scans = w.ctx.db.scans()
        assert {k: r.quick for k, r in scans.items()} == dict.fromkeys(w.order, "ok")
        assert scans["300:3002"].rating_key == "300:3002"
        # Checked once: not again for Media (nor for a station).
        client.portal.call(w.ctx.scanner.round)
        assert len(w.order) == 5


def test_a_file_checked_for_one_isnt_checked_again_for_the_other(tmp_path, clean):
    client, fp = world(tmp_path, clean)
    with client:
        w = start(client)
        client.portal.call(w.ctx.scanner.round)
        checked = {k: r.quick_ms for k, r in w.ctx.db.scans().items()}
        # A station's program newly added in Media is the station's file: as
        # it was checked for the station, it isn't checked again.
        fp.episodes["202"]["addedAt"] = NOW + 5
        fp.changed += 1
        # And a station taking up what was checked for Media doesn't check it
        # again either.
        made = client.post("/api/channels", json={"number": 9, "sources": [
            {"type": "show", "ratingKey": "110"}]})  # fmt: skip
        assert made.status_code == 201
        client.portal.call(w.ctx.scanner.round)
        assert w.order == ["201", "202", "300", "300:3002", "211"]
        assert {k: r.quick_ms for k, r in w.ctx.db.scans().items()} == checked
        # A new file is checked again, whoever plays it.
        fp.episodes["211"]["Media"][0]["Part"][0]["size"] = 4321
        record = w.ctx.db.scan("211")
        record.quick_ms -= (sc.RECHECK_S + 2 * 86_400) * 1000  # (the weekly sweep's turn)
        w.ctx.db.save_scan(record)
        client.portal.call(w.ctx.scanner.round)
        assert w.order[-1] == "211" and w.ctx.db.scan("211").size == 4321


def test_nothing_is_checked_while_someone_watches_media(tmp_path, clean, monkeypatch):
    client, _fp = world(tmp_path, clean)
    with client:
        w = start(client)
        monkeypatch.setattr(w.ctx.plays, "now", lambda: [object()])
        assert client.portal.call(w.ctx.scanner.round) is False
        assert w.order == [] and w.ctx.scanner.state == "paused"
        monkeypatch.setattr(w.ctx.plays, "now", list)
        client.portal.call(w.ctx.scanner.round)
        assert w.order[:2] == ["201", "202"]


def test_the_overnight_deep_scan_reaches_media_in_its_order(tmp_path, clean, monkeypatch):
    client, fp = world(tmp_path, clean)
    for n in (2, 3):
        fp.add_episode(f"21{n}", "110", 1, n, f"Media {n}", a_file(tmp_path, clean, f"21{n}"),
                       LENGTH_S * 1000, added_at=NOW - 100 * n)  # fmt: skip
    fp.add_movie("302", "Older Movie", a_file(tmp_path, clean, "302"), LENGTH_S * 1000,
                 section="2", added_at=NOW - 50)  # fmt: skip
    with client:
        w = start(client, since=NOW + 3600)  # (nothing's new: the deep scan has it all)
        ctx = w.ctx
        # Someone's partway through 212: it's in their Continue Watching,
        # and 213 is next.
        ctx.db.save_progress(
            0, "212", "110", 5_000, LENGTH_S * 1000, False, int(time.time() * 1000)
        )
        client.portal.call(ctx.scanner.round)  # (the station's quick checks)
        assert w.order == ["201", "202"]
        monkeypatch.setattr(ctx.scanner, "in_window", lambda now=None: True)
        deep: list[str] = []

        async def deep_scan(program, record, anytime=False):
            deep.append(program.key)
            record.deep_ms, record.deep = int(time.time() * 1000), "ok"
            ctx.db.save_scan(record)
            return True

        monkeypatch.setattr(ctx.scanner, "deep_scan", deep_scan)
        for _ in range(30):
            if not client.portal.call(ctx.scanner.round):
                break
        # The stations' programs; then Continue Watching, the next episode,
        # and the rest, the most recently added first. Each of Media's had its
        # quick check just before.
        assert deep == ["201", "202", "212", "213", "300", "300:3002", "211", "302", "301"], deep
        assert w.order == ["201", "202", "212", "213", "300", "300:3002", "211", "302", "301"]
        # (Media has the station's programs too: they're in a shared library.)
        status = client.get("/api/scan").json()
        assert status["media"] == {"files": 9, "quickChecked": 9, "deepScanned": 9}


def test_one_entry_per_file_whoever_plays_it(tmp_path, clean):
    client, fp = world(tmp_path, clean)
    with client:
        w = start(client)
        ctx = w.ctx
        client.portal.call(ctx.scanner.round)
        movie = client.portal.call(ctx.library.entry, "300", True)
        item = sc.item_of(movie, movie.media[1])
        ctx.broken.record(item, "Deep scan: the picture breaks up around 0:10", None,
                          item.file_path, 1000, problem="damaged", found=DEEP_SCAN,
                          version="3002", library="2")  # fmt: skip
        assert ctx.broken.keys() == {version_key("300", "3002")}
        assert not ctx.broken.is_broken("300")  # (its first version is fine)
        [listed] = client.get("/api/broken").json()
        assert (listed["key"], listed["version"], listed["media"], listed["on"]) == (
            "300:3002",
            "3002",
            True,
            [],
        )
        # A station's program on the list says it's in Media too.
        on_air = jobs.on_stations(ctx).by_key["201"]
        ctx.broken.record(on_air, "Check: no sound anywhere in it", 4, on_air.file_path, 1000,
                          problem="damaged", library="1")  # fmt: skip
        both = {e["key"]: e for e in client.get("/api/broken").json()}
        assert both["201"]["media"] and [s["number"] for s in both["201"]["on"]] == [4]
        # Retry, by its file key.
        assert client.delete("/api/broken/300:3002").status_code == 204
        assert ctx.db.scan("300:3002").kept and ctx.broken.keys() == {"201"}
        # A version Plex no longer has comes off the list as the list's gone
        # through.
        ctx.broken.record(item, "Check: no sound anywhere in it", None, item.file_path, 1000,
                          problem="damaged", version="3002", library="2")  # fmt: skip
        fp.episodes["300"]["Media"].pop()
        client.portal.call(jobs.look_again, ctx, jobs.ListCheck(running=True), False)
        assert ctx.broken.keys() == {"201"}


def test_a_missing_file_media_has_stays_on_the_list(tmp_path, clean):
    client, fp = world(tmp_path, clean)
    fp.episodes["211"]["Media"][0]["Part"][0]["file"] = "/gone.mkv"
    with client:
        w = start(client)
        ctx = w.ctx
        episode = client.portal.call(ctx.library.entry, "211", True)
        item = sc.item_of(episode, episode.media[0])
        ctx.broken.record(item, "Check: file not found: /gone.mkv", None, "/gone.mkv", 1000,
                          library="1")  # fmt: skip
        look = jobs.ListCheck(running=True)
        client.portal.call(jobs.look_again, ctx, look, False)
        assert ctx.broken.keys() == {"211"}  # (in Media, though on no station)
        # No longer shared: it comes off.
        ctx.shared.save(["2"])
        client.portal.call(jobs.look_again, ctx, jobs.ListCheck(running=True), False)
        assert ctx.broken.keys() == set()


def test_records_are_kept_for_what_media_has(tmp_path, clean):
    client, _fp = world(tmp_path, clean)
    with client:
        w = start(client)
        ctx = w.ctx
        old = int((time.time() - 40 * 86_400) * 1000)
        for key in ("301", "999"):
            ctx.db.save_scan(ScanRecord(key, str(clean), 1, quick_ms=old, quick="ok"))
        scanner = ctx.scanner
        # Until Media's files are all known, nothing's forgotten...
        scanner._forget_old(ctx.db.scans(), [])
        assert {"301", "999"} <= set(ctx.db.scans())
        # ...then what neither a station nor Media has.
        client.portal.call(scanner._media_everything)
        scanner._forget_old(ctx.db.scans(), [])
        assert "301" in ctx.db.scans() and "999" not in ctx.db.scans()
