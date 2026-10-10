"""Replacing broken files with Sonarr and Radarr (app/replacing.py), against
stand-ins that answer as their own code does (tests/fakearr.py): the
release is blocklisted before the file is removed, never otherwise; a
missing file is searched for; three searches in about a day, then it's
left to you; and an app that can't be reached changes nothing."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx
import pytest
from fastapi.testclient import TestClient

from app import jobs, replacing
from app.broken import CHECK, DEEP_SCAN
from app.config import Settings
from app.db import Item
from app.main import create_app
from app.plex import PlexClient
from tests.fakearr import FakeArr, both
from tests.fakeplex import FakePlex
from tests.helpers import like_plex

SHOW = "/tv/Bonanza (1959)"
H = 3600 * 1000


def plex_answers(fp: FakePlex) -> httpx.MockTransport:
    """The stand-in Plex, also saying what a show was matched to (its own
    details), and taking requests to look in a folder (kept in fp.scans)."""
    base = like_plex(fp)
    fp.scans = []

    def handler(request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")
        if parts[:2] == ["library", "metadata"] and len(parts) == 3 and parts[2] in fp.shows:
            show = {k: v for k, v in fp.shows[parts[2]].items() if not k.startswith("_")}
            return httpx.Response(200, content=json.dumps({"MediaContainer": {"Metadata": [show]}}))
        if parts[:2] == ["library", "sections"] and parts[-1:] == ["refresh"]:
            fp.scans.append((parts[2], request.url.params.get("path")))
            return httpx.Response(200)
        return base.handle_request(request)

    return httpx.MockTransport(handler)


@dataclass
class World:
    client: TestClient
    ctx: object
    plex: FakePlex
    sonarr: FakeArr
    radarr: FakeArr
    station: dict

    def item(self, key):
        return jobs.on_stations(self.ctx).by_key[key]

    def file(self, key) -> str:
        return self.plex.episodes[key]["Media"][0]["Part"][0]["file"]

    def go(self, everything: bool = False) -> None:
        """Goes through the list (and then Sonarr's and Radarr's part)."""
        self.client.portal.call(jobs.look_again, self.ctx, jobs.ListCheck(running=True), everything)

    def entry(self, key) -> dict:
        return next(e for e in self.ctx.broken.entries() if e["ratingKey"] == key)

    def broken(self, key, reason, problem="damaged", found=DEEP_SCAN, size=None) -> None:
        part = self.plex.episodes[key]["Media"][0]["Part"][0]
        self.ctx.broken.record(
            self.item(key), reason, 55, part["file"],
            part["size"] if size is None else size, problem=problem, found=found,
        )  # fmt: skip


@pytest.fixture
def world(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Bonanza", year=1959)
    fp.shows["100"]["Guid"] = [{"id": "tvdb://73378"}]
    fp.shows["100"]["librarySectionID"] = 1
    for n in range(1, 6):
        name = f"Bonanza (1959) - S05E{30 + n} - Title {n} [DVD][MP3 1.0][XviD]-nodlabs.avi"
        fp.add_episode(f"20{n}", "100", 5, 30 + n, f"Title {n}", f"{SHOW}/{name}", 22 * 60_000,
                       size=1000 + n)  # fmt: skip
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("301", "Dune", "/movies/Dune (1984)/Dune (1984).mkv", 120 * 60_000, year=1984,
                 section="2")  # fmt: skip
    fp.episodes["301"]["Guid"] = [{"id": "tmdb://841"}]
    fp.episodes["301"]["librarySectionID"] = 2
    sonarr, radarr = FakeArr("sonarr"), FakeArr("radarr", version="5.14.0.9383")
    sonarr.add_show(7, "Bonanza", 73378)
    for n in range(1, 6):
        sonarr.add_episode(70 + n, 7, 5, 30 + n, f"Title {n}")
    radarr.add_movie(9, "Dune", 1984, 841, "tt0087182")
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=plex_answers(fp)))
    with TestClient(app) as c:
        ctx = app.state.ctx
        ctx.arr_transport = both(sonarr, radarr)
        made = c.post("/api/channels", json={"number": 55, "sources": [
            {"type": "show", "ratingKey": "100", "title": "Bonanza"},
            {"type": "movie", "ratingKey": "301", "title": "Dune"}]})  # fmt: skip
        assert made.status_code == 201, made.text
        for app_name, url, arr in (
            ("sonarr", "http://sonarr.test:8989", sonarr),
            ("radarr", "http://radarr.test:7878", radarr),
        ):
            saved = c.put(
                "/api/arr", json={"app": app_name, "url": url, "key": arr.key, "on": True}
            )
            assert saved.status_code == 200, saved.text
        # (By themselves: what most of these are about. When you say so, the
        # default, is tested on its own.)
        assert c.put("/api/arr/when", json={"when": "auto"}).json()["when"] == "auto"
        yield World(c, ctx, fp, sonarr, radarr, made.json())


def calls_like(arr: FakeArr, start: str) -> list[int]:
    return [n for n, call in enumerate(arr.calls) if call.startswith(start)]


def test_the_settings_never_show_the_key_and_are_checked(world):
    c = world.client
    shown = c.get("/api/arr").json()
    assert shown["apps"]["sonarr"] == {"url": "http://sonarr.test:8989", "on": True, "hasKey": True}
    assert world.sonarr.key not in c.get("/api/arr").text
    for bad, why in (
        ({"url": "sonarr.test:8989"}, "http://"),
        ({"url": "http://user@sonarr.test"}, "user name"),
        ({"key": "abc; rm -rf"}, "letters and numbers"),
    ):
        got = c.put(
            "/api/arr", json={"app": "sonarr", "url": "http://sonarr.test", "on": True, **bad}
        )
        assert got.status_code == 400 and why in got.json()["detail"], got.text
    assert c.put("/api/arr", json={"app": "lidarr", "url": "http://x.test"}).status_code == 422
    # (Changing the address keeps the key.)
    kept = c.put("/api/arr", json={"app": "sonarr", "url": "http://sonarr.test:8989/", "on": True})
    assert kept.json()["apps"]["sonarr"]["url"] == "http://sonarr.test:8989"
    # Test: as saved, with another key, and pointed at the wrong app.
    tested = c.post("/api/arr/test", json={"app": "sonarr"}).json()
    assert tested == {"name": "Sonarr", "version": "4.0.15.2941"}
    wrong = c.post("/api/arr/test", json={"app": "sonarr", "key": "nope123"})
    assert wrong.status_code == 400 and "didn't accept the API key" in wrong.json()["detail"]
    mixed = c.post("/api/arr/test", json={"app": "sonarr", "url": "http://radarr.test:7878",
                                          "key": world.radarr.key})  # fmt: skip
    assert mixed.status_code == 400 and "doesn't point to Sonarr" in mixed.json()["detail"]


def test_a_broken_file_is_blocklisted_before_it_is_removed(world):
    s = world.sonarr
    name = world.file("201").rsplit("/", 1)[1]
    s.give_file(71, name, 1001, downloaded="Bonanza.S05E31.DVDRip.XviD-NODLABS")
    s.releases[71] = ["Bonanza.S05E31.DVDRip.XviD-NODLABS", "Bonanza.S05E31.720p.WEB.x264-GOOD"]
    world.broken("201", "Deep scan: the picture breaks up around 2:00, 9:00 and 14:00")
    world.go()
    # Blocklisted first, then removed, then searched for: in that order.
    failed, deleted = calls_like(s, "POST history/failed/"), calls_like(s, "DELETE episodefile/")
    searched = [n for n, c in enumerate(s.calls) if c == "POST command"]
    assert len(failed) == len(deleted) == 1 and failed[0] < deleted[0] < searched[-1]
    assert s.blocklist == ["Bonanza.S05E31.DVDRip.XviD-NODLABS"]
    assert s.recycled == [f"/tv/Bonanza/{name}"]
    assert [c["name"] for c in s.commands] == ["EpisodeSearch"]
    assert s.commands[0]["body"]["episodeIds"] == [71]
    state = world.entry("201")["replace"]
    assert state["state"] == "searching" and state["tries"] == 1
    assert "blocklisted Bonanza.S05E31.DVDRip.XviD-NODLABS" in state["note"]
    assert "(try 1 of 3)" in state["note"]
    # Downloading: nothing else is done.
    world.go()
    state = world.entry("201")["replace"]
    assert state["state"] == "downloading" and "720p.WEB" in state["note"]
    assert len(s.commands) == 1
    # Downloaded: Plex is asked to look in that folder.
    s.finish(71, "Bonanza (1959) - S05E31 - Title 1 [WEBDL-720p][AAC 2.0][x264]-GOOD.mkv", 5_000)
    world.go()
    state = world.entry("201")["replace"]
    assert state["state"] == "downloaded" and "once Plex finds it" in state["note"]
    assert world.plex.scans == [("1", SHOW)]
    # Plex has it (under a new key): off the list, and the station takes it up.
    world.plex.remove("201")
    world.plex.add_episode("211", "100", 5, 31, "Title 1", f"{SHOW}/new.mkv", 22 * 60_000)
    world.go()
    assert "201" not in {e["ratingKey"] for e in world.ctx.broken.entries()}


def test_a_file_added_by_hand_is_left_to_you(world):
    s = world.sonarr
    s.give_file(72, world.file("202").rsplit("/", 1)[1], 1002)  # (no download behind it)
    world.broken("202", "Check: no sound from 3:10 to 4:00")
    world.go()
    state = world.entry("202")["replace"]
    assert state["state"] == "can't" and "no record of downloading this file" in state["note"]
    assert not calls_like(s, "POST history/failed/") and not s.recycled and not s.commands
    world.go()  # (and it's not tried again)
    assert not s.commands and world.entry("202")["replace"]["state"] == "can't"


def test_a_file_that_isnt_the_broken_one_is_never_touched(world):
    s = world.sonarr
    s.give_file(73, "Bonanza (1959) - S05E33 - Title 3 [SDTV][AAC 1.0][x265].mp4", 777,
                downloaded="Bonanza.S05E33.SDTV.x265")  # fmt: skip
    world.broken("203", "file ended early at 12:00 of 25:00 (truncated or damaged?)",
                 problem="broken", found="playing")  # fmt: skip
    world.go()
    assert not calls_like(s, "POST history/failed/") and not s.recycled and not s.commands
    state = world.entry("203")["replace"]
    assert state["state"] == "downloaded" and "x265" in state["note"]
    assert world.plex.scans == [("1", SHOW)]
    # The same name but another size: not the one either.
    world.ctx.broken.remove("203")
    s.give_file(73, world.file("203").rsplit("/", 1)[1], 9_999, downloaded="Other")
    world.broken("203", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")
    world.go()
    assert not calls_like(s, "POST history/failed/") and not s.recycled


def test_a_missing_file_is_looked_for_on_disk_then_searched_for(world):
    s = world.sonarr
    fid = s.give_file(74, world.file("204").rsplit("/", 1)[1], 1004, downloaded="Old")
    s.gone(fid)  # (gone from disk: Sonarr doesn't know yet)
    s.releases[74] = ["Bonanza.S05E34.DVDRip-NEW"]
    world.broken("204", "Check: removed from Plex", problem="broken", found=CHECK)
    world.plex.remove("204")
    world.go()
    assert [c["name"] for c in s.commands] == ["RescanSeries", "EpisodeSearch"]
    assert s.commands[0]["body"]["seriesId"] == 7
    assert not calls_like(s, "POST history/failed/")  # (nothing to blocklist: it's missing)
    assert world.entry("204")["replace"]["state"] == "searching"
    # No station has it now, but it stays on the list while it's replaced...
    world.client.delete(f"/api/channels/{world.station['id']}")
    world.go()
    assert world.entry("204")["replace"]["state"] == "downloading"
    # ...till Plex has it again.
    s.finish(74, "Bonanza (1959) - S05E34 - Title 4 [DVD].mkv", 1_234)
    world.plex.add_episode("214", "100", 5, 34, "Title 4", f"{SHOW}/new4.mkv", 22 * 60_000)
    world.go()
    assert "204" not in {e["ratingKey"] for e in world.ctx.broken.entries()}


def test_three_searches_in_about_a_day_then_it_is_left_to_you(world, monkeypatch):
    s = world.sonarr
    clock = [10**12]
    monkeypatch.setattr(replacing, "now_ms", lambda: clock[0])
    world.broken("205", "Check: removed from Plex", problem="broken", found=CHECK)
    world.plex.remove("205")

    def searches() -> int:
        return sum(c["name"] == "EpisodeSearch" for c in s.commands)

    for hours, expected in ((0, 1), (1, 1), (8, 2), (12, 2), (16, 3), (20, 3)):
        clock[0] = 10**12 + hours * H
        world.go()
        assert searches() == expected, hours
        if hours == 12:
            note = world.entry("205")["replace"]["note"]
            assert "searched 2 of 3 times so far and will search again after" in note, note
    # (The last search may still bring a file, for a while.)
    assert "StationPlay will stop trying" in world.entry("205")["replace"]["note"]
    clock[0] = 10**12 + 24 * H
    world.go()
    state = world.entry("205")["replace"]
    assert state["state"] == "gave up" and "3 times in about a day" in state["note"]
    clock[0] = 10**12 + 48 * H
    world.go()
    assert searches() == 3  # (nothing more till you choose Try again)
    assert world.entry("205")["problem"] == "broken"  # (still on the list)
    # Try again: afresh.
    assert world.client.post("/api/broken/205/replace").status_code == 202
    for _ in range(50):
        if searches() == 4:
            break
        time.sleep(0.1)
    assert searches() == 4
    assert world.entry("205")["replace"]["state"] == "searching"


def test_a_new_file_that_fails_too_is_blocklisted_in_turn(world):
    s = world.sonarr
    first = world.file("201").rsplit("/", 1)[1]
    s.give_file(71, first, 1001, downloaded="R1")
    s.releases[71] = ["R1", "R2", "R3"]
    world.broken("201", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")
    world.go()
    assert s.blocklist == ["R1"]
    # R2 arrives, and StationPlay's check finds it broken too (as going
    # through the list does, with Plex's new file).
    s.finish(71, "R2.mkv", 2_002)
    part = world.plex.episodes["201"]["Media"][0]["Part"][0]
    part["file"], part["size"] = f"{SHOW}/R2.mkv", 2_002
    world.ctx.broken.record(world.item("201"), "Check: no sound from 1:00 to 2:00", 55,
                            f"{SHOW}/R2.mkv", 2_002, problem="damaged", found=CHECK)  # fmt: skip
    world.go()
    assert s.blocklist == ["R1", "R2"]  # (straight away: a new file came of the last search)
    assert world.entry("201")["replace"]["tries"] == 2


def test_radarr_replaces_a_broken_movie(world):
    r = world.radarr
    r.give_file(9, "Dune (1984).mkv", 1000, downloaded="Dune.1984.720p.BluRay-OLD")
    r.releases[9] = ["Dune.1984.720p.BluRay-OLD", "Dune.1984.1080p.BluRay-NEW"]
    world.broken("301", "Deep scan: the picture breaks up around 5:00, 50:00 and 1:30:00")
    world.go()
    grab = next(h for h in r.history if h["eventType"] == "grabbed")
    failed, deleted = calls_like(r, "POST history/failed/"), calls_like(r, "DELETE moviefile/")
    assert r.calls[failed[0]] == f"POST history/failed/{grab['id']}"  # (the grab itself)
    assert failed[0] < deleted[0]
    assert r.blocklist == ["Dune.1984.720p.BluRay-OLD"]
    assert [c["name"] for c in r.commands] == ["MoviesSearch"]
    assert r.commands[0]["body"]["movieIds"] == [9]
    assert world.entry("301")["replace"]["app"] == "radarr"


def test_a_file_only_media_has_is_replaced_the_same_way(world):
    """One process for every file (1.30.0): what's in a library shared with
    the apps is replaced as a station's program is, with the same rules."""
    ctx, r = world.ctx, world.radarr
    path = "/movies/Alien (1979)/Alien (1979).mkv"
    world.plex.add_movie("302", "Alien", path, 117 * 60_000, year=1979, section="2")
    world.plex.episodes["302"]["Guid"] = [{"id": "tmdb://348"}]
    r.add_movie(10, "Alien", 1979, 348)
    r.give_file(10, "Alien (1979).mkv", 1000, downloaded="Alien.1979.720p.BluRay-OLD")
    alien = Item(0, 0, 117 * 60_000, "302", "movie", "Alien", year=1979, file_path=path)
    ctx.broken.record(alien, "Deep scan: the picture breaks up around 10:00", None, path, 1000,
                      problem="damaged", found=DEEP_SCAN, library="2")  # fmt: skip
    # Not shared with the apps, and on no station: no one plays it, so it's
    # left be.
    world.go()
    assert not r.commands and "replace" not in world.entry("302")
    ctx.shared.save(["2"])
    world.go()
    assert r.blocklist == ["Alien.1979.720p.BluRay-OLD"]
    assert [c["body"]["movieIds"] for c in r.commands] == [[10]]
    assert world.entry("302")["replace"]["state"] == "searching"


def test_a_version_is_replaced_only_when_the_apps_file_is_that_one(world):
    ctx, r = world.ctx, world.radarr
    ctx.shared.save(["2"])
    r.give_file(9, "Dune (1984).mkv", 1000, downloaded="Dune.1984.720p.BluRay-OLD")
    dune = world.item("301")
    # (Plex has it in 4K too: a second version.)
    other = "/movies/Dune (1984)/Dune (1984) - 2160p.mkv"
    media = world.plex.episodes["301"]["Media"]
    part = {**media[0]["Part"][0], "id": 3012, "file": other, "size": 5000}
    media.append({"id": 3012, "duration": media[0]["duration"], "Part": [part]})
    ctx.broken.record(dune, "Deep scan: the picture breaks up around 1:00:00", None, other, 5000,
                      problem="damaged", found=DEEP_SCAN, version="3012", library="2")  # fmt: skip
    world.go()
    entry = ctx.broken.entry("301:3012")
    assert (
        entry["replace"]["state"] == "can't"
        and "another of its versions" in entry["replace"]["note"]
    )
    assert not r.blocklist and not r.commands and not r.recycled


def test_where_each_entry_is_on_the_tab(world):
    """Needs you, being replaced, or found (see replacing.tab_section)."""
    db = world.ctx.db
    damaged = {"problem": "damaged", "reason": "Deep scan: x", "show": "Bonanza"}
    section = replacing.tab_section
    # By themselves (as world has it): being replaced, if a station or Media
    # plays it; not, left to you.
    assert section(db, damaged, True) == replacing.BEING_REPLACED
    assert section(db, damaged, False) == replacing.NEEDS_YOU
    assert section(db, {**damaged, "replace": {"state": "downloading"}}, True) == (
        replacing.BEING_REPLACED
    )
    for state in ("gave up", "can't", "same"):
        assert section(db, {**damaged, "replace": {"state": state}}, True) == replacing.NEEDS_YOU
    assert section(db, {**damaged, "replace": {"state": "left"}}, True) == replacing.FOUND_ONLY
    assert section(db, {**damaged, "problem": "unsupported"}, True) == replacing.FOUND_ONLY
    # When you say so: it waits for you, until you do.
    replacing.save_when(db, replacing.ASK)
    assert section(db, damaged, True) == replacing.NEEDS_YOU
    assert section(db, {**damaged, "replace": {"asked": 1}}, True) == replacing.BEING_REPLACED
    # Without the app: it waits for you.
    replacing.save(db, "sonarr", "", None, False)
    assert section(db, {**damaged, "replace": {"asked": 1}}, True) == replacing.NEEDS_YOU


def test_an_app_that_cant_be_reached_changes_nothing(world):
    s = world.sonarr
    s.give_file(71, world.file("201").rsplit("/", 1)[1], 1001, downloaded="R1")
    world.broken("201", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")
    s.down = True
    world.go()
    assert "replace" not in world.entry("201") and not s.blocklist
    status = world.client.get("/api/arr").json()["status"]["sonarr"]
    assert not status["ok"] and "can't be reached" in status["problem"]
    s.down = False
    s.key = "anotherkey9"  # (its key changed)
    world.go()
    assert "replace" not in world.entry("201")
    assert (
        "didn't accept the API key"
        in world.client.get("/api/arr").json()["status"]["sonarr"]["problem"]
    )


def test_nothing_is_done_unless_its_turned_on_and_it_can_be_told_apart(world):
    s = world.sonarr
    s.give_file(71, world.file("201").rsplit("/", 1)[1], 1001, downloaded="R1")
    world.broken("201", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")
    world.client.put(
        "/api/arr", json={"app": "sonarr", "url": "http://sonarr.test:8989", "on": False}
    )
    world.go()
    assert not s.calls
    world.client.put(
        "/api/arr", json={"app": "sonarr", "url": "http://sonarr.test:8989", "on": True}
    )
    # Unsupported files (Dolby Vision profile 5) aren't replaced this way.
    world.ctx.broken.remove("201")
    world.broken("202", "it's Dolby Vision profile 5", problem="unsupported", found="playing")
    world.go()
    assert not s.calls
    # Two shows Sonarr can't tell apart (Plex didn't say which TVDB show).
    del world.plex.shows["100"]["Guid"]
    s.add_show(8, "Bonanza", 999999, year=2031)
    world.broken("203", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")
    world.go()
    state = world.entry("203")["replace"]
    assert state["state"] == "can't" and "Sonarr has 2 shows matching Bonanza" in state["note"]
    assert not s.blocklist and not s.recycled


def test_they_replace_only_the_kind_chosen(world):
    s = world.sonarr
    c = world.client
    assert c.get("/api/arr").json()["what"] == "both"
    s.give_file(71, world.file("201").rsplit("/", 1)[1], 1001, downloaded="R1")
    s.releases[71] = ["R1", "R2"]
    world.broken("201", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")
    world.broken("205", "Check: removed from Plex", problem="broken", found=CHECK)
    world.plex.remove("205")
    # Missing files only: the broken one is left alone.
    assert c.put("/api/arr/what", json={"what": "missing"}).json()["what"] == "missing"
    world.go()
    assert not s.blocklist and "replace" not in world.entry("201")
    assert [c["name"] for c in s.commands] == ["EpisodeSearch"]  # (for 205)
    assert world.entry("205")["replace"]["state"] == "searching"
    # Broken or damaged only: the missing one's left to you (what was begun
    # is forgotten), and the broken one is replaced.
    assert c.put("/api/arr/what", json={"what": "broken"}).status_code == 200
    world.go()
    assert "replace" not in world.entry("205")
    assert s.blocklist == ["R1"] and world.entry("201")["replace"]["state"] == "searching"
    assert c.put("/api/arr/what", json={"what": "everything"}).status_code == 422
    # (Saving an app's settings keeps the choice.)
    c.put("/api/arr", json={"app": "sonarr", "url": "http://sonarr.test:8989", "on": True})
    assert c.get("/api/arr").json()["what"] == "broken"


@pytest.mark.parametrize("unmonitored", ["show", "episode"])
def test_what_sonarr_isnt_monitoring_is_left_alone(world, unmonitored):
    s = world.sonarr
    if unmonitored == "show":
        s.shows[7]["monitored"] = False
    else:
        s.episodes[71]["monitored"] = False
        s.episodes[75]["monitored"] = False
    s.give_file(71, world.file("201").rsplit("/", 1)[1], 1001, downloaded="R1")
    world.broken("201", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")
    world.broken("205", "Check: removed from Plex", problem="broken", found=CHECK)
    world.plex.remove("205")
    world.go()
    assert not s.blocklist and not s.recycled
    assert all(c["name"] != "EpisodeSearch" for c in s.commands)
    for key in ("201", "205"):
        state = world.entry(key)["replace"]
        assert state["state"] == "can't", state
        assert f"Sonarr isn't monitoring this {unmonitored}" in state["note"]
    # Monitored again, and Try again: replaced.
    s.shows[7]["monitored"] = True
    s.episodes[71]["monitored"] = True
    assert world.client.post("/api/broken/201/replace").status_code == 202
    for _ in range(50):
        if s.blocklist:
            break
        time.sleep(0.1)
    assert s.blocklist == ["R1"]


def test_a_movie_radarr_isnt_monitoring_is_left_alone(world):
    r = world.radarr
    r.movies[9]["monitored"] = False
    r.give_file(9, "Dune (1984).mkv", 1000, downloaded="Dune.1984.720p.BluRay-OLD")
    world.broken("301", "Deep scan: the picture breaks up around 5:00, 50:00 and 1:30:00")
    world.go()
    assert not r.blocklist and not r.recycled and not r.commands
    assert "Radarr isn't monitoring this movie" in world.entry("301")["replace"]["note"]


def test_each_entry_says_which_stations_have_it(world):
    c = world.client
    other = c.post("/api/channels", json={"number": 12, "name": "Classics", "sources": [
        {"type": "show", "ratingKey": "100", "title": "Bonanza"}]})  # fmt: skip
    assert other.status_code == 201, other.text
    world.broken("201", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")
    world.broken("301", "Check: file not found: /movies/Dune (1984)/Dune (1984).mkv",
                 problem="broken", found=CHECK)  # fmt: skip
    listed = {e["ratingKey"]: e for e in c.get("/api/broken").json()}
    assert [s["number"] for s in listed["201"]["on"]] == [12, 55]
    assert listed["201"]["missing"] is False
    assert [(s["number"], s["name"]) for s in listed["301"]["on"]] == [(55, "Station 55")]
    assert listed["301"]["missing"] is True


def test_a_missing_program_comes_off_the_list_once_no_station_has_it(world):
    c = world.client
    for app_name in ("sonarr", "radarr"):  # (the list alone)
        c.put("/api/arr", json={"app": app_name, "url": f"http://{app_name}.test", "on": False})
    world.broken(
        "201", f"Check: file not found: {world.file('201')}", problem="broken", found=CHECK
    )
    world.broken("202", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")
    world.ctx.broken.record(world.item("301"), "Check: file not found: /movies/Dune.mkv", 55,
                            "/movies/Dune.mkv", 1, problem="broken", found=CHECK)  # fmt: skip
    world.go()
    assert {e["ratingKey"] for e in world.ctx.broken.entries()} == {"201", "202", "301"}
    # Bonanza taken off the station on purpose: its missing episode comes off
    # the list; its damaged one stays (it mustn't go back on a station
    # unnoticed), and so does the missing movie the station still has.
    body = {"number": 55, "sources": [{"type": "movie", "ratingKey": "301", "title": "Dune"}]}
    assert c.put(f"/api/channels/{world.station['id']}", json=body).status_code == 200
    listed = {e["ratingKey"]: e for e in c.get("/api/broken").json()}
    assert listed["201"]["on"] == [] and listed["301"]["on"][0]["number"] == 55
    world.go()
    assert {e["ratingKey"] for e in world.ctx.broken.entries()} == {"202", "301"}


def test_the_two_on_the_list_this_morning(world):
    """The very entries on the user's list (2026-10-06): an Adventure Time
    episode the deep scan found cut short, filed by Sonarr straight in its
    show's folder; and Return of the Jedi, which Plex calls "Star Wars:
    Episode VI - Return of the Jedi" and Radarr "Return of the Jedi", found
    damaged. Each found by its TVDB or TMDB id, its very file blocklisted,
    then removed, then searched for."""
    c, fp, s, r = world.client, world.plex, world.sonarr, world.radarr
    tv = "/mnt/hddpool/mediashare/media/tv/tv-current/Adventure Time (2010) {tvdb-152831}"
    at = "Adventure Time (2010) - S06E23 - The Pajama War [WEBDL-1080p][AAC 2.0][h264]-NTB.mkv"
    fp.add_show("600", "Adventure Time", year=2010)
    fp.shows["600"]["Guid"] = [{"id": "tvdb://152831"}, {"id": "tmdb://15260"}]
    fp.shows["600"]["librarySectionID"] = 1
    fp.add_episode("623", "600", 6, 23, "The Pajama War", f"{tv}/{at}", 716_000, size=287_311_552)
    movies = "/mnt/hddpool/mediashare/media/movies/movies-parents/Return of the Jedi (1983)"
    rotj = ("Return of the Jedi (1983) {tmdb-1892} {edition-Remastered} [ATMOS][Bluray-1080p]"
            "[TrueHD Atmos 7.1][x265]-TAoE.mkv")  # fmt: skip
    fp.add_movie("700", "Star Wars: Episode VI - Return of the Jedi", f"{movies}/{rotj}",
                 8_040_000, year=1983, section="2")  # fmt: skip
    fp.episodes["700"]["Guid"] = [{"id": "imdb://tt0086190"}, {"id": "tmdb://1892"}]
    fp.episodes["700"]["librarySectionID"] = 2
    fp.episodes["700"]["Media"][0]["Part"][0]["size"] = 14_623_901_234
    for number, source in (
        (75, {"type": "show", "ratingKey": "600", "title": "Adventure Time"}),
        (3, {"type": "movie", "ratingKey": "700", "title": "Star Wars: Episode VI - Return of the Jedi"}),
    ):  # fmt: skip
        made = c.post("/api/channels", json={"number": number, "sources": [source]})
        assert made.status_code == 201, made.text
    s.add_show(60, "Adventure Time", 152831, year=2010)
    s.add_episode(623, 60, 6, 23, "The Pajama War")
    s.add_episode(624, 60, 6, 24, "Wake Up")
    s.give_file(623, at, 287_311_552,
                downloaded="Adventure.Time.S06E23.The.Pajama.War.1080p.WEB-DL.AAC2.0.H.264-NTB")  # fmt: skip
    s.releases[623] = ["Adventure.Time.S06E23.The.Pajama.War.1080p.WEB-DL.AAC2.0.H.264-NTB",
                       "Adventure.Time.S06E23.1080p.AMZN.WEB-DL.DDP2.0.H.264-NTb"]  # fmt: skip
    r.add_movie(19, "Return of the Jedi", 1983, 1892, "tt0086190")
    r.give_file(19, rotj, 14_623_901_234,
                downloaded="Return.of.the.Jedi.1983.Remastered.1080p.BluRay.TrueHD.Atmos.7.1.x265-TAoE")  # fmt: skip
    r.releases[19] = ["Return.of.the.Jedi.1983.Remastered.1080p.BluRay.TrueHD.Atmos.7.1.x265-TAoE",
                      "Return.of.the.Jedi.1983.1080p.BluRay.DTS-HD.MA.5.1.x264-OTHER"]  # fmt: skip
    items = jobs.on_stations(world.ctx).by_key
    for key, reason, problem, size in (
        ("623", "Deep scan: nothing plays after 11:41 of its 11:56: it's cut short, or damaged "
         "there", "broken", 287_311_552),
        ("700", "Deep scan: the picture or sound breaks up in 7 different minutes (from 5:00, "
         "18:00, 26:00, 52:00, 59:00 and 2 more)", "damaged", 14_623_901_234),
    ):  # fmt: skip
        file = fp.episodes[key]["Media"][0]["Part"][0]["file"]
        world.ctx.broken.record(items[key], reason, 75, file, size, problem=problem,
                                found=DEEP_SCAN)  # fmt: skip
    world.go()
    # Sonarr: Adventure Time S06E23's release blocklisted, then its file
    # removed, then a search; nothing else touched.
    assert s.blocklist == ["Adventure.Time.S06E23.The.Pajama.War.1080p.WEB-DL.AAC2.0.H.264-NTB"]
    assert [p.rsplit("/", 1)[1] for p in s.recycled] == [at]
    failed, deleted = calls_like(s, "POST history/failed/"), calls_like(s, "DELETE episodefile/")
    assert failed[0] < deleted[0]
    assert [cmd["body"].get("episodeIds") for cmd in s.commands] == [[623]]
    assert world.entry("623")["replace"]["state"] == "searching"
    # Radarr: the same, for the movie.
    assert r.blocklist == [
        "Return.of.the.Jedi.1983.Remastered.1080p.BluRay.TrueHD.Atmos.7.1.x265-TAoE"
    ]
    assert [p.rsplit("/", 1)[1] for p in r.recycled] == [rotj]
    assert [cmd["body"].get("movieIds") for cmd in r.commands] == [[19]]
    assert world.entry("700")["replace"]["state"] == "searching"
    # The new downloads: grabbed, not the blocklisted releases.
    assert [q["title"] for q in s.queue] == [
        "Adventure.Time.S06E23.1080p.AMZN.WEB-DL.DDP2.0.H.264-NTb"
    ]
    assert [q["title"] for q in r.queue] == [
        "Return.of.the.Jedi.1983.1080p.BluRay.DTS-HD.MA.5.1.x264-OTHER"
    ]


def test_replacing_goes_on_when_plex_is_too_slow_for_the_whole_list(world, monkeypatch):
    s = world.sonarr
    s.give_file(71, world.file("201").rsplit("/", 1)[1], 1001, downloaded="R1")
    s.releases[71] = ["R1", "R2"]
    world.broken("201", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")

    async def slow(*_args, **_kwargs):
        raise jobs.PlexAway("Plex didn't answer")

    monkeypatch.setattr(jobs, "look_at", slow)
    world.go(everything=True)
    assert s.blocklist == ["R1"]


# When you say so, leaving one to you, and the same problem again (1.16.3) -------------


def wait_for(done, what: str) -> None:
    for _ in range(100):
        if done():
            return
        time.sleep(0.05)
    raise AssertionError(what)


def test_they_replace_when_you_say_so_unless_you_choose_automatically(world):
    s = world.sonarr
    c = world.client
    assert c.put("/api/arr/when", json={"when": "ask"}).json()["when"] == "ask"
    s.give_file(71, world.file("201").rsplit("/", 1)[1], 1001, downloaded="R1")
    s.releases[71] = ["R1", "R2"]
    world.broken("201", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")
    world.broken("205", "Check: removed from Plex", problem="broken", found=CHECK)
    world.plex.remove("205")
    world.go()
    # Nothing's asked of Sonarr till you say so.
    assert not s.calls
    assert "replace" not in world.entry("201") and "replace" not in world.entry("205")
    # Replace (on the list): that one, now; and it carries on by itself.
    assert c.post("/api/broken/201/replace").status_code == 202
    wait_for(lambda: s.blocklist == ["R1"], "blocklisted")
    assert world.entry("201")["replace"]["state"] == "searching"
    world.go()
    assert world.entry("201")["replace"]["state"] == "downloading"
    assert not any(c_["name"] == "RescanSeries" for c_ in s.commands)  # (205: still waiting)
    # Missing, and not asked for: off the list once no station has it.
    c.delete(f"/api/channels/{world.station['id']}")
    world.go()
    assert {e["ratingKey"] for e in world.ctx.broken.entries()} == {"201"}
    # (Saving an app's settings, or what they replace, keeps the choice.)
    c.put("/api/arr", json={"app": "sonarr", "url": "http://sonarr.test:8989", "on": True})
    c.put("/api/arr/what", json={"what": "broken"})
    assert c.get("/api/arr").json()["when"] == "ask"
    assert c.put("/api/arr/when", json={"when": "sometimes"}).status_code == 422


def test_its_when_you_say_so_until_you_choose_otherwise(tmp_path):
    from app.db import Database

    db = Database(tmp_path / "db.sqlite")
    assert replacing.when(db) == replacing.ASK
    replacing.save(db, "sonarr", "http://sonarr.test", "abc123", True)
    assert replacing.when(db) == replacing.ASK
    replacing.save_when(db, replacing.AUTO)
    replacing.save_what(db, replacing.MISSING)
    replacing.save(db, "radarr", "http://radarr.test", "def456", True)
    assert (replacing.when(db), replacing.what(db)) == (replacing.AUTO, replacing.MISSING)
    with pytest.raises(ValueError):
        replacing.save_when(db, "never")
    db.close()


def test_leave_this_one_to_me(world):
    s = world.sonarr
    c = world.client
    s.give_file(71, world.file("201").rsplit("/", 1)[1], 1001, downloaded="R1")
    s.releases[71] = ["R1", "R2"]
    world.broken("201", "Deep scan: the picture breaks up around 1:00, 2:00 and 3:00")
    world.broken("205", "Check: removed from Plex", problem="broken", found=CHECK)
    world.plex.remove("205")
    # Left to you before anything's asked; and while it's searching.
    assert c.post("/api/broken/201/leave").status_code == 204
    world.go()
    assert not s.blocklist
    state = world.entry("201")["replace"]
    assert state["state"] == "left" and "won't ask Sonarr to replace it" in state["note"]
    assert state["app"] == "sonarr"
    assert world.entry("205")["replace"]["state"] == "searching"
    assert c.post("/api/broken/205/leave").status_code == 204
    searches = len(s.commands)
    world.go()
    assert len(s.commands) == searches and world.entry("205")["replace"]["state"] == "left"
    # Missing and left to you: off the list once no station has it.
    body = {"number": 55, "sources": [{"type": "movie", "ratingKey": "301", "title": "Dune"}]}
    assert c.put(f"/api/channels/{world.station['id']}", json=body).status_code == 200
    world.go()
    assert {e["ratingKey"] for e in world.ctx.broken.entries()} == {"201"}
    # Replace, after all.
    assert c.post("/api/broken/201/replace").status_code == 202
    wait_for(lambda: s.blocklist == ["R1"], "blocklisted")
    assert c.post("/api/broken/999/leave").status_code == 404


@pytest.mark.parametrize(
    ("before", "now", "same"),
    [
        ("Deep scan: the picture breaks up around 5:00, 18:00 and 26:00",
         "Deep scan: the picture breaks up around 5:02, 18:01 and 26:20", True),
        ("Deep scan: the picture breaks up around 5:00, 18:00 and 26:00",
         "Deep scan: the picture breaks up around 5:00, 40:00 and 52:00", False),
        ("Deep scan: the picture breaks up around 5:00 and 18:00",
         "Deep scan: the picture breaks up around 5:10, 31:00, 40:00 and 1 more places", False),
        ("Deep scan: the picture breaks up around 5:00 and 18:00",
         "Deep scan: the picture breaks up around 5:10 and 31:00", True),  # (half)
        ("Deep scan: the picture breaks up around 1:02:03",
         "Deep scan: the picture breaks up around 1:02:30", True),
        ("Deep scan: the picture breaks up around 5:00",
         "Deep scan: the sound (AAC) drops out around 5:00", False),
        ("Deep scan: nothing plays after 11:41 of its 11:56: it's cut short, or damaged there",
         "Check: nothing plays after 11:40 of its 11:58: it's cut short, or damaged there", True),
        ("Check: it has no sound track", "Check: it has no sound track", True),
        ("Check: it has no sound track", "Check: no sound from 3:10 to 4:00", False),
        ("Deep scan: the picture breaks up around 5:00", "Deep scan: the picture breaks up", False),
        (None, "Deep scan: the picture breaks up around 5:00", False),
        ("", "Deep scan: the picture breaks up around 5:00", False),
    ],
)  # fmt: skip
def test_what_counts_as_the_same_problem(before, now, same):
    assert replacing.same_problem(before, now) is same


def test_a_new_file_with_the_same_problem_in_the_same_places_wants_your_look(world):
    """It may be how the program was made (an old film's effects), not a
    bad file: nothing more is blocklisted or searched for until you say."""
    s = world.sonarr
    c = world.client
    first = world.file("201").rsplit("/", 1)[1]
    s.give_file(71, first, 1001, downloaded="R1")
    s.releases[71] = ["R1", "R2", "R3"]
    world.broken("201", "Deep scan: the picture breaks up around 5:00, 18:00 and 26:00")
    world.go()
    assert s.blocklist == ["R1"]

    def arrives(release: str, size: int, reason: str, kept: bool = True) -> None:
        """A release arrives; Plex has it; a check finds what's wrong with it.
        `kept`: its entry stays on the list meanwhile (the quick check found
        it); else it went (it passed), and the deep scan put it back."""
        s.finish(71, f"{release}.mkv", size)
        part = world.plex.episodes["201"]["Media"][0]["Part"][0]
        part["file"], part["size"] = f"{SHOW}/{release}.mkv", size
        if not kept:
            world.ctx.broken.remove("201")
        world.ctx.broken.record(world.item("201"), reason, 55, f"{SHOW}/{release}.mkv", size,
                                problem="damaged", found=DEEP_SCAN)  # fmt: skip

    arrives("R2", 2_002, "Deep scan: the picture breaks up around 5:01, 18:03 and 26:10")
    world.go()
    assert s.blocklist == ["R1"]  # (not R2)
    state = world.entry("201")["replace"]
    assert state["state"] == "same", state
    assert state["note"].startswith("The new file has the same problem in the same places")
    searches = len(s.commands)
    world.go()
    assert len(s.commands) == searches and world.entry("201")["replace"]["state"] == "same"
    # Try another: R2 is blocklisted, and R3 searched for...
    assert c.post("/api/broken/201/replace").status_code == 202
    wait_for(lambda: s.blocklist == ["R1", "R2"], "blocklisted")
    # ...and comes with the same problem (found by the deep scan once it was
    # back on the air): wants your look again.
    arrives("R3", 3_003, "Deep scan: the picture breaks up around 5:00, 18:02 and 26:01",
            kept=False)  # fmt: skip
    world.go()
    assert s.blocklist == ["R1", "R2"]
    assert world.entry("201")["replace"]["state"] == "same"
    # Retry: it's fine, back on the air.
    assert c.delete("/api/broken/201").status_code == 204
    assert world.ctx.broken.entries() == []
