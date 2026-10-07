"""The app connection (/api/v1, see appapi.py): checked against its
document, docs/app-api.md, field by field, so the two can't drift apart."""

from __future__ import annotations

import itertools
import re
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex

DOC = Path(__file__).resolve().parent.parent / "docs" / "app-api.md"
PUBLIC_PORT = 8443
PAT = {"name": "Pat", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple"}
TYPES = {"string": str, "number": (int, float), "boolean": bool, "list": list, "object": dict}
# Kinds of field that are objects described in sections of their own.
SHAPES = {"program": "A program", "card": "A card"}


def documented() -> dict[str, dict[str, str]]:
    """Each section of the document with a table of fields ("GET
    /api/v1/stations", "A program"): each field's path, and its type."""
    sections: dict[str, dict[str, str]] = {}
    heading = ""
    for line in DOC.read_text().splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            if heading.startswith(("GET /", "POST /")):
                sections[heading] = {}  # (an address, even with no fields: data, say)
        elif row := re.fullmatch(r"\| `([^`]+)` \| ([^|]+) \|.*", line):
            sections.setdefault(heading, {})[row.group(1)] = row.group(2).strip()
    return sections


DOCUMENTED = documented()
PROGRAM = DOCUMENTED["A program"]


class Checker:
    """Checks answers against the document, remembering which documented
    fields were seen (every one must be, by the end)."""

    def __init__(self) -> None:
        self.seen: dict[str, set[str]] = {name: set() for name in DOCUMENTED}

    def answer(self, res, endpoint: str, status: int = 200) -> dict[str, Any]:
        assert res.headers.get("stationplay-api") == "1", (endpoint, res.headers)
        assert res.status_code == status, (endpoint, res.text)
        body = res.json()
        if status != 200:
            assert set(body) == {"detail"} and isinstance(body["detail"], str), body
            return body
        self._object(body, "", endpoint)
        return body

    def _object(self, value: dict, prefix: str, section: str) -> None:
        assert isinstance(value, dict), (section, prefix, value)
        for key, inside in value.items():
            self._field(inside, f"{prefix}{key}", section)

    def _field(self, value: Any, path: str, section: str) -> None:
        rows = DOCUMENTED[section]
        assert path in rows, f"{section}: {path} isn't documented"
        self.seen[section].add(path)
        kind, _, nullable = rows[path].partition(" or ")
        if value is None:
            assert nullable == "null", f"{section}: {path} is null"
            return
        if kind in SHAPES:
            self._object(value, "", SHAPES[kind])
            return
        expected = TYPES[kind]
        assert isinstance(value, expected) and not (kind == "number" and isinstance(value, bool)), (
            f"{section}: {path} is {value!r}, not a {kind}"
        )
        if kind == "object":
            self._object(value, f"{path}.", section)
        elif kind == "list":
            for item in value:
                if f"{path}[]" in rows:
                    self._field(item, f"{path}[]", section)
                else:
                    self._object(item, f"{path}[].", section)

    def everything_seen(self) -> None:
        for section, rows in DOCUMENTED.items():
            assert set(rows) == self.seen[section], f"{section}: {set(rows) - self.seen[section]}"


@pytest.fixture
def app(tmp_path):
    fp = LibraryPlex()
    fp.add_show("100", "Show")
    for n in range(1, 5):
        fp.add_episode(f"20{n}", "100", 1, n, f"Ep {n}", f"/x/{n}.mkv", 22 * 60_000)
    # A library of movies, with one described in full (see test_ondemand.py).
    fp.add_section("2", "Movies", "movie")
    fp.add_movie(
        "300", "A Movie", "/x/movie.mkv", 90 * 60_000, year=1999, section="2", genres=["Drama"]
    )
    fp.describe("300", colorTrc="smpte2084", bitDepth=10, video="hevc", width=3840, height=2160)
    fp.add_subtitles("300", "pgs", "English")
    fp.add_subtitles("300", "srt", "Spanish", external=b"1\n00:00:01,000 --> 00:00:02,000\nHola\n")
    fp.set_markers("300", ("intro", 60_000, 120_000), ("credits", 5_000_000, 5_300_000, True))
    fp.add_version("300", 1920, 1080)  # (and in 1080p, as H.264)
    # (An episode's markers are the apps'; a movie's aren't.)
    fp.set_markers("202", ("intro", 60_000, 120_000), ("credits", 1_200_000, 1_319_000, True))
    fp.describe("202", colorTrc="smpte2084", bitDepth=10, video="hevc", width=3840, height=2160)
    fp.files["202"] = b"an episode, as it is" * 100
    fp.released["300"] = "1999-03-31"
    fp.files["300"] = b"a movie, as it is" * 100
    settings = Settings(
        plex_url="http://plex.test",
        plex_token="token",
        data_dir=tmp_path / "data",
        public_port=PUBLIC_PORT,
    )
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    app.state.ctx.play_transport = fp.transport()  # (Plex's files)
    return app


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_the_app_connection_matches_its_document(app):
    check = Checker()
    routes = {
        f"{method} {route.path}"
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/")
        for method in route.methods
    }
    assert routes == {
        name for name in DOCUMENTED if name.startswith(("GET /api/v1/", "POST /api/v1/"))
    }
    with TestClient(app) as home:
        # (Through a reverse proxy with HTTPS, as it says.)
        internet = TestClient(
            app, base_url=f"http://testserver:{PUBLIC_PORT}", headers={"X-Forwarded-Proto": "https"}
        )
        server = check.answer(home.get("/api/v1/server"), "GET /api/v1/server")
        assert server["api"] == 1 and not server["signIn"] and server["notSetUp"] is None
        assert server["features"] == ["hls", "speed-test"]
        # From the internet, until signing in is on, there's nothing to do.
        outside = check.answer(internet.get("/api/v1/server"), "GET /api/v1/server")
        assert outside["signIn"] and "home network" in outside["notSetUp"]
        check.answer(internet.get("/api/v1/stations"), "GET /api/v1/stations", 403)

        made = home.post("/api/channels", json={"number": 5, "name": "Hometown 5", "sources": [
            {"type": "show", "ratingKey": "100"}]})  # fmt: skip
        assert made.status_code == 201, made.text
        # Signing in is off: open on the home network, with nothing to sign in to.
        stations = check.answer(home.get("/api/v1/stations"), "GET /api/v1/stations")["stations"]
        [five] = stations
        assert (five["number"], five["name"]) == (5, "Hometown 5")
        assert five["hls"] == "/hls/5/index.m3u8" and five["logo"].startswith("/channel-icon/5.png")
        assert all(re.fullmatch(r"#[0-9A-F]{6}", c) for c in five["colors"].values())
        now, upcoming = five["now"], five["next"]
        assert now["kind"] == "episode" and now["title"] == "Show" and now["art"] == "/art/100"
        assert now["episodeTitle"].startswith("Ep ") and now["season"] == 1
        assert now["start"] <= time.time() * 1000 < now["end"] == upcoming["start"]
        refused = home.post("/api/v1/sign-in", json=PAT)
        check.answer(refused, "POST /api/v1/sign-in", 400)

        # Signing in on: an app signs in, and sends its token.
        assert home.post("/api/access/users", json=PAT).status_code == 201
        assert home.post("/api/access/users", json={**SAM, "role": "user"}).status_code == 201
        phone = TestClient(app)  # (no cookies: an app)
        check.answer(phone.get("/api/v1/stations"), "GET /api/v1/stations", 401)
        wrong = phone.post("/api/v1/sign-in", json={**SAM, "password": "not it at all"})
        check.answer(wrong, "POST /api/v1/sign-in", 401)
        check.answer(phone.post("/api/v1/sign-in", json={"name": 7}), "POST /api/v1/sign-in", 400)
        signed = check.answer(phone.post("/api/v1/sign-in", json=SAM), "POST /api/v1/sign-in")
        assert signed["user"] == {"name": "Sam", "role": "user"} and signed["device"]
        assert not phone.cookies  # (apps get a token, not a cookie)
        sam = bearer(signed["token"])
        listed = check.answer(phone.get("/api/v1/stations", headers=sam), "GET /api/v1/stations")
        assert [s["number"] for s in listed["stations"]] == [5]
        assert phone.get("/api/logs", headers=sam).status_code == 403  # a User, not an Admin
        assert phone.get("/api/v1/stations", headers=bearer("not a token")).status_code == 401

        start = int(time.time() * 1000)
        guide = check.answer(
            phone.get(f"/api/v1/guide?from={start}&to={start + 3 * 3600_000}", headers=sam),
            "GET /api/v1/guide",
        )
        assert (guide["from"], guide["to"]) == (start, start + 3 * 3600_000)
        [listing] = guide["stations"]
        programs = listing["programs"]
        assert listing["number"] == 5 and len(programs) >= 3
        assert programs[0]["start"] <= start and programs[-1]["end"] >= guide["to"]
        assert all(a["end"] == b["start"] for a, b in itertools.pairwise(programs))
        default = check.answer(phone.get("/api/v1/guide", headers=sam), "GET /api/v1/guide")
        assert default["to"] - default["from"] == 6 * 3600_000
        for bad in (
            "from=soon",
            f"from={start}&to={start}",
            f"from={start}&to={start + 3 * 86_400_000}",
            f"from={start + 8 * 86_400_000}",
        ):
            check.answer(phone.get(f"/api/v1/guide?{bad}", headers=sam), "GET /api/v1/guide", 400)

        # A connection test (see test_capacity.py): the data, then what was found.
        data = phone.get("/api/v1/speed-test?mb=1", headers=sam)
        assert data.status_code == 200 and len(data.content) == 1 << 20
        assert data.headers["stationplay-api"] == "1"
        assert phone.get("/api/v1/speed-test?mb=1").status_code == 401
        tested = {"mbps": 52.0, "app": "StationPlay for Android", "deviceName": "Pixel"}
        found = check.answer(
            phone.post("/api/v1/speed-test", headers=sam, json=tested), "POST /api/v1/speed-test"
        )
        assert (found["where"], found["mbps"]) == ("home", 52.0)

        # Your library (see test_ondemand.py): shared by an Admin, then
        # browsed and played.
        check.answer(phone.get("/api/v1/libraries", headers=sam), "GET /api/v1/libraries", 404)
        assert home.put("/api/app-libraries", json={"libraries": ["1", "2"]}).status_code == 200
        features = check.answer(phone.get("/api/v1/server"), "GET /api/v1/server")["features"]
        assert features == ["hls", "speed-test", "library"]
        libs = check.answer(phone.get("/api/v1/libraries", headers=sam), "GET /api/v1/libraries")
        assert [(x["key"], x["kind"]) for x in libs["libraries"]] == [("1", "show"), ("2", "movie")]
        shows = check.answer(
            phone.get("/api/v1/libraries/1?size=10", headers=sam), "GET /api/v1/libraries/{key}"
        )
        assert shows["total"] == 1 and shows["items"][0]["unwatched"] == 4
        movies = check.answer(
            phone.get("/api/v1/libraries/2?sort=added", headers=sam), "GET /api/v1/libraries/{key}"
        )
        assert movies["items"][0]["poster"] == "/api/v1/art/300?kind=poster"
        show = check.answer(phone.get("/api/v1/items/100", headers=sam), "GET /api/v1/items/{key}")
        assert show["next"]["key"] == "201" and show["seasons"][0]["title"] == "Season 1"
        episode = check.answer(
            phone.get("/api/v1/items/202", headers=sam), "GET /api/v1/items/{key}"
        )
        assert (
            episode["showKey"] == "100" and episode["backdrop"] == "/api/v1/art/100?kind=backdrop"
        )
        movie = check.answer(phone.get("/api/v1/items/300", headers=sam), "GET /api/v1/items/{key}")
        assert movie["markers"] == {"intro": None, "credits": None, "creditsToEnd": False}
        assert episode["markers"] == {
            "intro": [60_000, 120_000], "credits": [1_200_000, 1_320_000], "creditsToEnd": True
        }  # fmt: skip
        assert movie["picture"] == {"size": "4K", "hdr": "HDR10"}
        assert [v["name"] for v in movie["versions"]] == ["4K · HDR10", "1080p"]
        listed = check.answer(
            phone.get("/api/v1/items/100/episodes?season=1", headers=sam),
            "GET /api/v1/items/{key}/episodes",
        )
        assert [e["episode"] for e in listed["episodes"]] == [1, 2, 3, 4]
        found = check.answer(phone.get("/api/v1/search?q=movie", headers=sam), "GET /api/v1/search")
        assert [x["key"] for x in found["items"]] == ["300"] and found["onNow"] == []
        # (Search is where the stations and the library meet.)
        found = check.answer(phone.get("/api/v1/search?q=show", headers=sam), "GET /api/v1/search")
        assert [x["key"] for x in found["items"]] == ["100"]
        assert [(s["number"], s["now"]["title"]) for s in found["onNow"]] == [(5, "Show")]
        poster = phone.get("/api/v1/art/300?kind=poster&w=300", headers=sam)
        assert poster.status_code == 200 and poster.headers["stationplay-api"] == "1"
        tv = {"containers": ["mkv"], "video": [{"codec": "hevc", "width": 3840, "height": 2160,
              "bitDepth": 10}], "hdr": ["hdr10"], "audio": ["aac"]}  # fmt: skip
        played = check.answer(
            phone.post("/api/v1/play", headers=sam, json={"key": "300", "device": tv}),
            "POST /api/v1/play",
        )
        assert played["method"] == "direct" and played["resumeMs"] == 0
        assert played["version"] == movie["versions"][0]["id"] and played["whenSlow"] == "offer"
        assert [(v["playable"], v["why"]) for v in played["versions"]] == [
            (True, None), (False, ["its picture's format (H.264)"])
        ]  # fmt: skip
        assert phone.get(played["url"]).content == b"a movie, as it is" * 100
        [external] = [t for t in played["subtitles"] if t["external"]]
        assert phone.get(external["url"]).text.endswith("Hola\n")
        moved = check.answer(
            phone.post("/api/v1/progress", headers=sam,
                       json={"key": "300", "positionMs": 600_000, "session": played["session"]}),
            "POST /api/v1/progress",
        )  # fmt: skip
        assert moved == {"positionMs": 600_000, "watched": False}
        start = check.answer(phone.get("/api/v1/home", headers=sam), "GET /api/v1/home")
        assert [(c["key"], c["positionMs"]) for c in start["continue"]] == [("300", 600_000)]
        assert [a["title"] for a in start["added"]] == ["TV Shows", "Movies"]
        assert phone.post(played["leave"]).status_code == 204
        assert phone.get(played["url"]).status_code == 404
        played = check.answer(
            phone.post("/api/v1/play", headers=sam, json={"key": "202", "device": tv}),
            "POST /api/v1/play",
        )
        assert played["markers"]["intro"] == [60_000, 120_000]
        assert phone.post(played["leave"]).status_code == 204

        # A device that has signed in before keeps its device token.
        again = phone.post("/api/v1/sign-in", json={**SAM, "device": signed["device"]})
        assert check.answer(again, "POST /api/v1/sign-in")["device"] is None
        out = check.answer(phone.post("/api/v1/sign-out", headers=sam), "POST /api/v1/sign-out")
        assert out == {"ok": True}
        check.answer(phone.get("/api/v1/stations", headers=sam), "GET /api/v1/stations", 401)
        assert (
            phone.get("/api/v1/stations", headers=bearer(again.json()["token"])).status_code == 200
        )
        log = home.get("/api/logs?access_log=true").json()["text"]
        assert "Sam (User) signed in to a StationPlay app" in log
        assert "Failed sign-in as 'Sam' in a StationPlay app" in log
        assert "Sam signed out of a StationPlay app" in log

        # Signing in with a code: the TV asks, someone signed in enters it.
        tv = TestClient(app)
        started = check.answer(
            tv.post("/api/v1/link", json={"app": "StationPlay for Roku", "deviceName": "Den Roku"}),
            "POST /api/v1/link",
        )
        assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", started["code"])
        assert started["linkAt"] == "/link" and started["expiresIn"] == 600
        waiting = tv.post("/api/v1/link/check", json={"poll": started["poll"]})
        check.answer(waiting, "POST /api/v1/link/check", 202)
        check.answer(
            tv.post("/api/v1/link/check", json={"poll": "guess"}), "POST /api/v1/link/check", 404
        )
        assert home.get("/link").status_code == 200  # (the page, where codes go)
        wrong = home.get("/api/access/link/AAAA-AAAA")
        assert wrong.status_code == 404 and "TV" in wrong.json()["detail"]
        typed = started["code"].lower().replace("-", " ")
        shown = home.get(f"/api/access/link/{typed}")
        assert shown.json() == {"app": "StationPlay for Roku on Den Roku"}
        assert home.post("/api/access/link", json={"code": typed}).status_code == 200
        assert home.post("/api/access/link", json={"code": typed}).status_code == 404  # (once)
        linked = check.answer(
            tv.post("/api/v1/link/check", json={"poll": started["poll"]}), "POST /api/v1/link/check"
        )
        assert linked["user"] == {"name": "Pat", "role": "admin"}
        assert tv.get("/api/v1/stations", headers=bearer(linked["token"])).status_code == 200
        # (Handed over once.)
        gone = tv.post("/api/v1/link/check", json={"poll": started["poll"]})
        check.answer(gone, "POST /api/v1/link/check", 404)
        log = home.get("/api/logs?access_log=true").json()["text"]
        assert "Pat (Admin) linked StationPlay for Roku on Den Roku" in log
        # The Access tab lists signed-in apps, and signs one out.
        apps = home.get("/api/access/apps").json()
        den = next(a for a in apps if a["app"] == "StationPlay for Roku on Den Roku")
        assert den["user"] == "Pat"
        assert (
            phone.get("/api/access/apps", headers=bearer(again.json()["token"])).status_code == 403
        )
        assert home.delete(f"/api/access/apps/{den['id']}").status_code == 204
        assert tv.get("/api/v1/stations", headers=bearer(linked["token"])).status_code == 401
        assert home.delete(f"/api/access/apps/{den['id']}").status_code == 404

        # From the internet, only over HTTPS.
        plain_http = TestClient(app, base_url=f"http://testserver:{PUBLIC_PORT}")
        refused = plain_http.post("/api/v1/sign-in", json=PAT)
        assert refused.status_code == 403 and "HTTPS" in refused.json()["detail"]
        assert plain_http.get("/api/v1/server").status_code == 403
        # Over HTTPS, once signing in is on: signing in and the stations, but
        # not the streams (until watching away from home is on: test_hls.py).
        outside = check.answer(internet.get("/api/v1/server"), "GET /api/v1/server")
        assert outside["signIn"] and outside["notSetUp"] is None
        token = check.answer(internet.post("/api/v1/sign-in", json=PAT), "POST /api/v1/sign-in")
        pat = bearer(token["token"])
        assert internet.get("/api/v1/stations", headers=pat).status_code == 200
        assert internet.get("/hls/5/index.m3u8", headers=pat).status_code == 404
        away = internet.post("/api/v1/speed-test", headers=pat, json={"mbps": 12.5})
        assert check.answer(away, "POST /api/v1/speed-test")["where"] == "away"
    check.everything_seen()
