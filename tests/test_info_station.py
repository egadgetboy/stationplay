"""The INFO station (infostation.py): a new tapiOca starts with station 99,
INFO, so Plex's tuner setup has a station to find (the owner, October 12:
Plex wouldn't take tapiOca's tuner on a new tapiOca, which had no stations,
so setup couldn't get it into Plex). It plays its film from the image,
without Plex, with the date, the time and its panels drawn over it and its
pearls in front of them. It's always 99; it's made once by itself, and
brought back only by an Admin."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app import __version__, ffmpeg, infostation, setup
from app.config import Settings
from app.db import Database
from app.library import Library
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .test_e2e import assert_clean_stream, record, start_server

pytestmark = pytest.mark.info_station

SHOW = {"type": "show", "ratingKey": "100"}


def plex() -> FakePlex:
    fp = FakePlex()
    fp.add_show("100", "Show")
    for n in range(1, 4):
        fp.add_episode(f"20{n}", "100", 1, n, f"Ep {n}", f"/x/{n}.mkv", 22 * 60_000)
    return fp


def make(tmp_path, fp: FakePlex | None = None) -> TestClient:
    return TestClient(
        create_app(
            Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
            PlexClient("http://plex.test", "token", transport=(fp or plex()).transport()),
        )
    )


def test_a_new_tapioca_starts_with_info_on_99(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    with make(tmp_path) as c:
        [station] = c.get("/api/channels").json()
        assert (station["number"], station["name"]) == (99, "INFO")
        assert station["logo"] == infostation.LOGO
        assert station["now"]["title"] == "tapiOca INFO"
        # Plex's tuner setup finds it: in the lineup and the guide.
        lineup = c.get("/lineup.json").json()
        assert [(s["GuideNumber"], s["GuideName"]) for s in lineup] == [("99", "INFO")]
        guide = c.get("/xmltv.xml").text
        assert "INFO" in guide and "tapiOca INFO" in guide
        logo = c.get("/channel-icon/99.png")
        assert logo.status_code == 200 and logo.content[:8] == b"\x89PNG\r\n\x1a\n"
        # Setup still treats tapiOca as new.
        assert c.get("/api/setup").json()["fresh"] is True
        assert c.get("/api/info-station").json() == {
            "station": station["id"],
            "number": 99,
            "name": "INFO",
            "taken": None,
        }
    assert "Made the INFO station, station 99" in caplog.text


def test_info_is_always_99_and_nothing_else_can_be(tmp_path):
    with make(tmp_path) as c:
        [info] = c.get("/api/channels").json()
        body = {"number": 99, "name": "News", "sources": [SHOW]}
        refused = c.post("/api/channels", json=body)
        assert (
            refused.status_code == 409 and refused.json()["detail"] == "Station 99 is kept for INFO"
        )
        five = c.post("/api/channels", json={**body, "number": 5})
        assert five.status_code == 201, five.text
        moved = c.put(f"/api/channels/{five.json()['id']}", json={**body, "number": 99})
        assert moved.status_code == 409
        # INFO: renamed, but never renumbered, and it plays only its film.
        mine = {"number": 99, "name": "Our INFO", "sources": [infostation.SOURCE]}
        assert c.put(f"/api/channels/{info['id']}", json=mine).status_code == 200
        assert (
            c.put(f"/api/channels/{info['id']}", json={**mine, "number": 7}).json()["detail"]
            == "INFO is always station 99"
        )
        changed = c.put(f"/api/channels/{info['id']}", json={**mine, "sources": [SHOW]})
        assert (
            changed.status_code == 400
            and changed.json()["detail"] == "INFO always plays its own film"
        )
        # And no other station can play its film.
        copy = c.post(
            "/api/channels", json={"number": 8, "name": "Copy", "sources": [infostation.SOURCE]}
        )
        assert copy.status_code == 400
        # Smart stations skip 99.
        assert 99 not in [
            s["number"] for s in c.get("/api/channels").json() if s["id"] != info["id"]
        ]


def test_info_is_made_once_and_an_admin_brings_it_back(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    with make(tmp_path) as c:
        [info] = c.get("/api/channels").json()
        assert c.delete(f"/api/channels/{info['id']}").status_code in (200, 204)
    # Deleted, it stays deleted...
    with make(tmp_path) as c:
        assert c.get("/api/channels").json() == []
        assert c.get("/api/info-station").json()["station"] is None
        # ...until an Admin brings it back.
        back = c.post("/api/info-station")
        assert back.status_code == 201, back.text
        assert [(s["number"], s["name"]) for s in c.get("/api/channels").json()] == [(99, "INFO")]
        assert c.post("/api/info-station").status_code == 409
    assert "added the INFO station, station 99" in caplog.text


def test_an_update_never_adds_info_and_a_station_on_99_keeps_it(tmp_path):
    """A tapiOca set up before 1.34.1 gets no INFO by itself; one whose
    station 99 is another one keeps it, and INFO waits till it moves."""
    db = Database(tmp_path / "data" / "stationplay.db")
    setup.mark(db, ["playback"])
    with make(tmp_path) as c:
        assert c.get("/api/channels").json() == []
        made = c.post("/api/channels", json={"number": 9, "name": "Nine", "sources": [SHOW]})
        assert made.status_code == 201
        # (As if made on 99 before 1.34.1.)
        c.app.state.ctx.db.update_channel(made.json()["id"], number=99)
        mine = {"number": 99, "name": "Still mine", "sources": [SHOW]}
        assert c.put(f"/api/channels/{made.json()['id']}", json=mine).status_code == 200
        assert c.get("/api/info-station").json()["taken"] == "Still mine"
        refused = c.post("/api/info-station")
        assert (
            refused.status_code == 409
            and "Give it another number first" in refused.json()["detail"]
        )
        assert (
            c.put(f"/api/channels/{made.json()['id']}", json={**mine, "number": 98}).status_code
            == 200
        )
        assert c.post("/api/info-station").status_code == 201


def test_bringing_info_back_is_for_admins(tmp_path):
    with make(tmp_path) as c:
        c.post("/api/access/users", json={"name": "Ada", "password": "correct horse"})
        c.post(
            "/api/access/users", json={"name": "Bo", "password": "battery staple", "role": "user"}
        )
        c.post("/api/access/sign-out")
        c.post("/api/access/sign-in", json={"name": "Bo", "password": "battery staple"})
        assert c.post("/api/info-station").status_code == 403
        assert c.get("/api/info-station").status_code == 403


def test_the_library_answers_for_info_without_plex():
    library = Library(PlexClient("", ""))

    async def ask():
        [item] = await library.items_for_source(infostation.SOURCE)
        assert (item.rating_key, item.duration_ms, item.title) == (
            infostation.KEY,
            infostation.LENGTH_MS,
            "tapiOca INFO",
        )
        [media] = await library.current_files(infostation.KEY)
        assert media.file == str(infostation.FILE)
        assert await library.markers(infostation.KEY) == []
        assert await library.find_again(item) is None

    asyncio.run(ask())


def test_the_film_is_as_infostation_says():
    """Its length and size, its picture, its pearls in front (full range
    gray, not the default stream), its sound, and its logo."""
    asked = ["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,codec_name,width,height,duration,pix_fmt:stream_disposition=default",
             "-of", "json", str(infostation.FILE)]  # fmt: skip
    found = subprocess.run(asked, capture_output=True, text=True, check=True).stdout
    probed = json.loads(found)["streams"]
    picture, pearls = (s for s in probed if s["codec_type"] == "video")
    audio = next(s for s in probed if s["codec_type"] == "audio")
    for video in (picture, pearls):
        assert (video["codec_name"], video["width"], video["height"]) == (
            "h264",
            infostation.WIDTH,
            infostation.HEIGHT,
        )
    assert picture["disposition"]["default"] == 1 and pearls["disposition"]["default"] == 0
    assert pearls["pix_fmt"] in ("gray", "yuvj420p")
    assert audio["codec_name"] == "aac"
    for stream in (picture, pearls, audio):
        assert abs(float(stream["duration"]) * 1000 - infostation.LENGTH_MS) < 50
    assert infostation.LOGO_FILE.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_whats_new_is_this_versions():
    """news.json is this version's, so INFO never shows an old one's."""
    news = json.loads(infostation.NEWS_FILE.read_text(encoding="utf-8"))
    assert news["version"] == __version__
    assert infostation.highlights() == news["new"] and 1 <= len(news["new"]) <= 3
    assert all(len(h) <= infostation.LINE_MOST - 2 for h in news["new"])
    assert all(a["name"] and a["version"] for a in infostation.apps())


def test_the_panels_say_whats_fine_for_anyone(tmp_path):
    """Counts, never titles; this version's news, never the server's state
    (1.34.1, the audit: whether a newer version is out is for Admins, on the
    page); the apps as what they are, in beta; tips for the apps."""
    counts = infostation.Counts(stations=12, movies=1204, shows=312, episodes=9876, this_week=42)
    shown = infostation.panels(counts, 3)
    titles = [p.title for p in shown]
    assert titles == [
        f"What's new in tapiOca {__version__}",
        "tapiOca's apps, in beta",
        "By the numbers",
        "A tip for tapiOca's apps",
    ]
    assert not any("is out" in p.body or "update" in p.body.lower() for p in shown)
    assert shown[2].body.splitlines() == [
        "12 stations · 1,204 movies", "312 shows · 9,876 episodes",
        "42 new movies and episodes this week",
    ]  # fmt: skip
    assert shown[3].body == infostation.TIPS[3]
    for panel in shown:
        lines = panel.body.splitlines()
        assert len(lines) <= infostation.LINES_MOST
        assert all(len(line) <= infostation.LINE_MOST for line in lines)
    # Written whole, each in its file; and as it was, not written again.
    infostation.write(tmp_path, shown)
    [(title, body), *_] = infostation.files(tmp_path)
    assert title.read_text(encoding="utf-8") == f"What’s new in tapiOca {__version__}"
    before = body.stat().st_mtime_ns
    time.sleep(0.01)
    infostation.write(tmp_path, shown)
    assert body.stat().st_mtime_ns == before
    assert not list(tmp_path.glob("*.new"))


def drawn(folder) -> tuple[tuple[str, str, int], ...]:
    return tuple((str(t), str(b), infostation.lines(b)) for t, b in infostation.files(folder))


def test_what_info_draws_is_a_graph_ffmpeg_takes(tmp_path):
    """The date, the time, the address and the panels, each panel in its 15
    seconds, and the pearls back in front: as ffmpeg runs it, on the film
    itself."""
    infostation.write(tmp_path, infostation.panels(infostation.Counts(stations=1), 0))
    info = ffmpeg.Info(panels=drawn(tmp_path), airs_at_s=1_791_000_000.0)
    settings = Settings(video_width=640, video_height=360)
    graph = ffmpeg._video_filter(settings, info=info)
    assert graph.startswith("[0:v:0]") and graph.endswith("[vout]")
    assert graph.count("drawtext=") == 3 + 2 * infostation.PANELS
    assert "text='tapioca.tv'" in graph
    assert "[0:v:1]scale=640:360,format=gray" in graph and "alphamerge" in graph
    out = tmp_path / "drawn.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(infostation.FILE), "-filter_complex", graph,
         "-map", "[vout]", "-t", "2", "-c:v", "libx264", "-preset", "ultrafast", str(out)],
        check=True, capture_output=True,
    )  # fmt: skip
    assert out.stat().st_size > 10_000


async def test_info_plays_without_plex(tmp_path):
    """Plex knows nothing (a new tapiOca, before it's connected): INFO plays
    anyway, drawn on, a clean stream."""
    base, app, _settings, srv, task = await start_server(tmp_path, FakePlex())
    try:
        data = await record(f"{base}/stream/99", 6.0)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "info.ts"
    out.write_bytes(data)
    assert len(data) > 100_000
    assert_clean_stream(out)
    # (Its panels were written for it to draw.)
    assert all(
        t.is_file() and b.is_file() for t, b in infostation.files(app.state.ctx.info_panels.folder)
    )


def test_info_lines_up_at_its_margins(tmp_path, monkeypatch):
    """Each panel's last line on the same baseline as the address, bottom
    right, however many lines it has, at the bottom margin, which matches
    the top's; the address set right at the time's right edge (the owner,
    October 12: "so everything looks uniform"). Drawn by ffmpeg and
    measured, in a picture of only the text: x's sit on their baseline, so
    the address is x's too here."""
    monkeypatch.setattr(ffmpeg, "INFO_ADDRESS", "xxxx")
    shown = [infostation.Panel(f"Panel {n}", "\n".join(["xxxxxxxx"] * n)) for n in (1, 2, 3, 4)]
    infostation.write(tmp_path, shown)
    assert [infostation.lines(b) for _, b in infostation.files(tmp_path)] == [1, 2, 3, 4]
    # (Airing where the drift is nothing, and the first panel's turn starts.)
    w, h, airs = 1280, 720, ffmpeg.DRIFT_S * len(ffmpeg.NUDGES) * 830_000
    info = ffmpeg.Info(panels=drawn(tmp_path), airs_at_s=airs, panel_s=15)
    chain = ffmpeg.info_text(Settings(video_width=w, video_height=h), info)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=black:s={w}x{h}:r=2",
         "-vf", f"{chain},select='eq(n,14)+eq(n,44)+eq(n,74)+eq(n,104)',format=gray",
         "-fps_mode", "passthrough", "-frames:v", "4", "-f", "rawvideo", str(tmp_path / "frames")],
        check=True, capture_output=True,
    )  # fmt: skip
    raw = (tmp_path / "frames").read_bytes()
    assert len(raw) == 4 * w * h
    edge, side = round(0.065 * h), round(0.06 * w)

    def lit(frame: bytes, cols: range, rows: range) -> tuple[list[int], list[int]]:
        ys = [y for y in rows if any(frame[y * w + x] > 128 for x in cols)]
        xs = [x for x in cols if any(frame[y * w + x] > 128 for y in rows)]
        return ys, xs

    for n in range(4):
        frame = raw[n * w * h : (n + 1) * w * h]
        left_rows, left_cols = lit(frame, range(w // 2), range(h // 2, h))
        right_rows, right_cols = lit(frame, range(w // 2, w), range(h // 2, h))
        # The bottoms of the x's: a row above the baseline, the bottom margin.
        assert max(left_rows) == max(right_rows) == h - edge - 1, n
        assert abs(min(left_cols) - side) <= 3 and abs((w - 1 - max(right_cols)) - side) <= 3
        # Its title above it, with room between.
        assert min(left_rows) < h - edge - (n + 1) * 30
    # And the time's right edge is the address's.
    top = raw[: w * h]
    _, time_cols = lit(top, range(w // 2, w), range(h // 4))
    assert abs(max(time_cols) - max(lit(top, range(w // 2, w), range(h // 2, h))[1])) <= 3


def test_infos_film_plays_only_on_info(tmp_path):
    """(1.34.1, the audit) INFO's film plays only on INFO, and INFO plays
    only its film: never beside other sources, in a block, as anything but
    INFO's own source; and INFO has no blocks, Feature Presentation or
    marathons, which would play titles from Plex on it."""
    with make(tmp_path) as c:
        [info] = c.get("/api/channels").json()
        c.post("/api/access/users", json={"name": "Ada", "password": "correct horse"})
        c.post(
            "/api/access/users", json={"name": "Bo", "password": "battery staple", "role": "user"}
        )
        bo = TestClient(c.app)
        assert (
            bo.post(
                "/api/access/sign-in", json={"name": "Bo", "password": "battery staple"}
            ).status_code
            == 200
        )
        odd = {"type": "info", "x": "y" * 500}
        for who in (c, bo):
            mixed = who.post(
                "/api/channels", json={"number": 12, "name": "Mixed", "sources": [odd, SHOW]}
            )
            assert mixed.status_code == 400, mixed.text
            mixed = who.post(
                "/api/channels",
                json={"number": 12, "name": "Mixed", "sources": [infostation.SOURCE, SHOW]},
            )
            assert mixed.status_code == 400 and mixed.json()["detail"] == infostation.ONLY_ON_INFO
            block = {"name": "B", "days": "0,1,2,3,4,5,6", "start": "20:00", "end": "21:00",
                     "sources": [infostation.SOURCE]}  # fmt: skip
            blocked = who.post(
                "/api/channels",
                json={"number": 13, "name": "Block", "sources": [SHOW], "blocks": [block]},
            )
            assert (
                blocked.status_code == 400 and blocked.json()["detail"] == infostation.ONLY_ON_INFO
            )
        assert [s["number"] for s in c.get("/api/channels").json()] == [99]
        # INFO itself: only its own source, as it is, and nothing else on it.
        mine = {"number": 99, "name": "INFO", "sources": [infostation.SOURCE]}
        assert (
            c.put(f"/api/channels/{info['id']}", json={**mine, "sources": [odd]}).status_code == 400
        )
        block = {"name": "B", "days": "0", "start": "20:00", "end": "21:00", "sources": [SHOW]}
        for extra in ({"blocks": [block]}, {"featureMode": "on"}, {"marathonMode": "random"}):
            refused = c.put(f"/api/channels/{info['id']}", json={**mine, **extra})
            assert (
                refused.status_code == 400 and refused.json()["detail"] == infostation.ONLY_ITS_FILM
            ), extra
        assert (
            c.put(
                f"/api/channels/{info['id']}", json={**mine, "featureMode": "off", "blocks": []}
            ).status_code
            == 200
        )


def test_everyone_who_can_watch_stations_sees_info(tmp_path):
    """(1.34.1, the audit) INFO is for everyone: a Kid, or a level that
    includes only some Media folders, sees it too (its film is tapiOca's
    own, unrated by Plex, in no Media folder)."""
    from .fakeplex_library import LibraryPlex
    from .test_who_sees_what import ADA, KIT, kid_level, set_up, sign_in_app

    # (test_who_sees_what's Plex.)
    fp = LibraryPlex()
    fp.add_show("100", "Puppet Town", contentRating=["TV-Y7"])
    for n in range(1, 4):
        fp.add_episode(f"20{n}", "100", 1, n, f"Puppets {n}", f"/tv/p/{n}.mkv", 22 * 60_000)
    fp.add_show("110", "Night Shift", contentRating=["TV-MA"])
    for n in range(1, 3):
        fp.add_episode(f"21{n}", "110", 1, n, f"Shift {n}", f"/tv/n/{n}.mkv", 44 * 60_000)
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "Picnic", "/m/picnic.mkv", 90 * 60_000, section="2", contentRating=["PG"])
    fp.add_movie("301", "Heist", "/m/heist.mkv", 100 * 60_000, section="2", contentRating=["R"])
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    with TestClient(app) as admin:
        set_up(admin)
        admin.post("/api/access/users", json=ADA)
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        admin.put(f"/api/access/users/{kit['id']}/viewing", json={"level": kid_level(admin)})
        as_kit = sign_in_app(app, KIT)
        seen = [
            s["number"]
            for s in TestClient(app).get("/api/v1/stations", headers=as_kit).json()["stations"]
        ]
        assert 99 in seen and 5 not in seen
        tv_only = admin.post("/api/access/levels", json={"name": "TV only", "libraries": ["1"]})
        assert tv_only.status_code == 201, tv_only.text
        admin.put(f"/api/access/users/{kit['id']}/viewing", json={"level": tv_only.json()["id"]})
        seen = [
            s["number"]
            for s in TestClient(app).get("/api/v1/stations", headers=as_kit).json()["stations"]
        ]
        assert 99 in seen and 9 not in seen


def test_by_the_numbers_counts_only_the_media_shared_and_never_info(tmp_path):
    """(1.34.1, the audit) What INFO counts is what's shared with tapiOca's
    apps, not all of Plex: a Media folder kept out isn't counted, and with
    none shared, only stations are. INFO doesn't count itself."""
    from .fakeplex_library import LibraryPlex

    fp = LibraryPlex()
    fp.add_show("100", "Bonanza")
    for n in range(1, 4):
        fp.add_episode(f"20{n}", "100", 1, n, f"Episode {n}", f"/tv/b/{n}.mkv", 50 * 60_000)
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "The Movie", "/m/a.mkv", 100 * 60_000, section="2")
    fp.add_section("3", "Home Videos", "movie")
    fp.add_movie("302", "Birthday", "/home/bday.mp4", 10 * 60_000, section="3")
    fp.add_movie("303", "Picnic", "/home/picnic.mp4", 10 * 60_000, section="3")
    with make(tmp_path, fp) as c:
        panels = c.app.state.ctx.info_panels
        c.portal.call(panels.count)
        assert (panels.counts.movies, panels.counts.shows, panels.counts.episodes) == (3, 1, 3)
        assert c.put("/api/app-libraries", json={"libraries": ["1", "2"]}).status_code == 200
        c.portal.call(panels.count)
        assert (panels.counts.movies, panels.counts.shows, panels.counts.episodes) == (1, 1, 3)
        # Narrowed while Plex can't be asked: what was counted before isn't
        # shown for what's shared now (the second audit). And sharing
        # changed wakes the panels, to be counted and written again.
        real = c.app.state.ctx.library.counts

        async def failing(keys=None):
            raise RuntimeError("Plex isn't answering")

        c.app.state.ctx.library.counts = failing
        woken, wake = [], panels.wake.set
        panels.wake.set = lambda: (woken.append(True), wake())[1]
        assert c.put("/api/app-libraries", json={"libraries": ["2"]}).status_code == 200
        assert woken
        c.portal.call(panels.count)
        assert panels.counts.movies is panels.counts.shows is panels.counts.episodes is None
        c.app.state.ctx.library.counts = real
        c.portal.call(panels.count)
        assert (panels.counts.movies, panels.counts.shows, panels.counts.episodes) == (1, 0, 0)
        assert c.put("/api/app-libraries", json={"libraries": []}).status_code == 200
        c.portal.call(panels.count)
        assert panels.counts.movies is panels.counts.shows is panels.counts.episodes is None
        panels.write_now()
        assert panels.counts.stations == 0
        # A new tapiOca, nothing counted yet: not "0 stations" (the second
        # audit), but what to do.
        [_, _, (_, numbers), _] = infostation.files(panels.folder)
        assert numbers.read_text(encoding="utf-8") == "Make your first station on tapiOca’s page."


def test_by_the_numbers_leaves_out_none_of_a_kind():
    """Nothing counted reads as what to do, and a count of none is left out
    (the second audit: "0 stations" on a new tapiOca)."""
    shown = infostation.panels(infostation.Counts(stations=0, movies=120, shows=0, episodes=0), 0)
    assert shown[2].body == "120 movies"
    shown = infostation.panels(infostation.Counts(stations=3), 0)
    assert shown[2].body == "3 stations"
