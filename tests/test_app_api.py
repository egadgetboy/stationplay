"""StationPlay's API (/api/v1, see appapi.py and api.py) and the apps' own
addresses (/api/internal): checked against their documents, docs/api.md and
docs/internal-api.md, field by field, so they can't drift apart. (The API's
tokens and its OpenAPI spec: test_api.py.)"""

from __future__ import annotations

import itertools
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import appapi
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex
from .helpers import Proxy

DOCS = Path(__file__).resolve().parent.parent / "docs"
API_DOC, INTERNAL_DOC = DOCS / "api.md", DOCS / "internal-api.md"
PUBLIC_PORT = 8443
PAT = {"name": "Pat", "password": "correct horse"}
SAM = {"name": "Sam", "password": "battery staple"}
TYPES = {"string": str, "number": (int, float), "boolean": bool, "list": list, "object": dict}
# How an address's section starts ("GET /api/v1/stations").
METHODS = ("GET /", "POST /", "PUT /", "DELETE /")
# Kinds of field that are objects described in sections of their own.
SHAPES = {"program": "A program", "card": "A card"}


def documented(*docs: Path) -> dict[str, dict[str, str]]:
    """Each section of the documents with a table of fields ("GET
    /api/v1/stations", "A program"): each field's path, and its type."""
    sections: dict[str, dict[str, str]] = {}
    for doc in docs:
        heading = ""
        for line in doc.read_text().splitlines():
            if line.startswith("## "):
                heading = line[3:].strip()
                if heading.startswith(METHODS):
                    sections[heading] = {}  # (an address, even with no fields: data, say)
            elif row := re.fullmatch(r"\| `([^`]+)` \| ([^|]+) \|.*", line):
                sections.setdefault(heading, {})[row.group(1)] = row.group(2).strip()
    return sections


DOCUMENTED = documented(API_DOC, INTERNAL_DOC)


def addresses(doc: Path) -> set[str]:
    """The addresses a document describes ("GET /api/v1/stations")."""
    return {name for name in documented(doc) if name.startswith(METHODS)}


class Checker:
    """Checks answers against the document, remembering which documented
    fields were seen (every one must be, by the end)."""

    def __init__(self) -> None:
        self.seen: dict[str, set[str]] = {name: set() for name in DOCUMENTED}

    def answer(self, res, endpoint: str, status: int = 200) -> dict[str, Any]:
        assert res.headers.get("stationplay-api") == "1", (endpoint, res.headers)
        assert res.status_code == status, (endpoint, res.text)
        body = res.json()
        if status not in (200, 201):
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
    fp.add_movie("301", "The Other One", "/x/other.mkv", 60 * 60_000, year=2001, section="2",
                 genres=["Drama", "Comedy"])  # fmt: skip
    fp.episodes["301"]["titleSort"] = "Other One"
    fp.more["300"] = {
        "tagline": "One of a kind.",
        "Role": [{"tag": "Ada Lund", "role": "Kit"}, {"tag": "Bo Hale"}],
        "Director": [{"tag": "Cy Marsh"}],
        "Writer": [{"tag": "Cy Marsh"}, {"tag": "Di Pell"}],
    }
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


def served(app, under: str) -> set[str]:
    return {
        f"{method} {route.path}"
        for route in app.routes
        if getattr(route, "path", "").startswith(under)
        for method in route.methods
    }


def test_the_api_and_the_apps_addresses_match_their_documents(app):
    check = Checker()
    assert served(app, "/api/v1/") == addresses(API_DOC)
    assert served(app, "/api/internal/") == addresses(INTERNAL_DOC)
    with TestClient(app) as home:
        # (Through a reverse proxy with HTTPS, as it says.)
        internet = TestClient(
            app, base_url=f"http://testserver:{PUBLIC_PORT}", headers={"X-Forwarded-Proto": "https"}
        )
        server = check.answer(home.get("/api/v1/server"), "GET /api/v1/server")
        assert server["api"] == 1 and not server["signIn"] and server["notSetUp"] is None
        assert server["features"] == ["hls", "speed-test", "reports", "night", "problems"]
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
        refused = home.post("/api/internal/sign-in", json=PAT)
        check.answer(refused, "POST /api/internal/sign-in", 400)
        nobody = check.answer(home.get("/api/internal/me"), "GET /api/internal/me")
        assert nobody["user"] is None and nobody["languages"]["audio"] is None

        # Signing in on: an app signs in, and sends its token.
        assert home.post("/api/access/users", json=PAT).status_code == 201
        # (On every device at home, as in a household: see test_picker.py.)
        household = {**SAM, "role": "user", "showOn": "home"}
        assert home.post("/api/access/users", json=household).status_code == 201
        phone = TestClient(app)  # (no cookies: an app)
        check.answer(phone.get("/api/v1/stations"), "GET /api/v1/stations", 401)
        wrong = phone.post("/api/internal/sign-in", json={**SAM, "password": "not it at all"})
        check.answer(wrong, "POST /api/internal/sign-in", 401)
        check.answer(
            phone.post("/api/internal/sign-in", json={"name": 7}), "POST /api/internal/sign-in", 400
        )
        signed = check.answer(
            phone.post("/api/internal/sign-in", json=SAM), "POST /api/internal/sign-in"
        )
        assert signed["user"] == {"name": "Sam", "role": "user"} and signed["device"]
        assert not phone.cookies  # (apps get a token, not a cookie)
        sam = bearer(signed["token"])
        me = check.answer(phone.get("/api/internal/me", headers=sam), "GET /api/internal/me")
        assert me["user"] == {
            "name": "Sam",
            "role": "user",
            "pin": False,
            "canChangePassword": True,
            "canReport": True,
        }
        assert (me["languages"]["audio"], me["languages"]["captions"]) == (None, False)
        assert {"code": "jpn", "name": "Japanese"} in me["languages"]["choices"]
        # His languages, on every device (see test_languages.py).
        mine = check.answer(
            phone.put("/api/internal/languages", headers=sam,
                      json={"audio": "en", "captions": True, "captionLanguage": "spa"}),
            "PUT /api/internal/languages",
        )  # fmt: skip
        assert mine == {"audio": {"code": "eng", "name": "English"}, "captions": True,
                        "captionLanguage": {"code": "spa", "name": "Spanish"}}  # fmt: skip
        check.answer(
            phone.put("/api/internal/languages", headers=sam, json={"audio": "klingon"}),
            "PUT /api/internal/languages",
            400,
        )
        me = check.answer(phone.get("/api/internal/me", headers=sam), "GET /api/internal/me")
        assert me["languages"]["captionLanguage"]["code"] == "spa"
        check.answer(phone.get("/api/internal/me"), "GET /api/internal/me", 401)
        # A PIN, as the app asks after signing in (see test_picker.py).
        assert signed["askPin"] is True
        pin = "POST /api/internal/pin"
        check.answer(phone.post("/api/internal/pin", headers=sam, json={"pin": "12"}), pin, 400)
        check.answer(phone.post("/api/internal/pin", json={"pin": "2468"}), pin, 401)
        chose = check.answer(
            phone.post("/api/internal/pin", headers=sam, json={"pin": "2468"}), pin
        )
        assert chose == {"pin": True}
        assert phone.get("/api/internal/me", headers=sam).json()["user"]["pin"] is True
        none = check.answer(phone.post("/api/internal/pin", headers=sam, json={"pin": None}), pin)
        assert none == {"pin": False}
        # His password, as on the page (see test_access.py): the app carries
        # on with a new token. (And back again, for what follows.)
        pw = "POST /api/internal/password"
        guess = {"current": "a guess", "new": "a whole new one"}
        check.answer(phone.post("/api/internal/password", headers=sam, json=guess), pw, 400)
        for current, new in (
            (SAM["password"], "a whole new one"),
            ("a whole new one", SAM["password"]),
        ):
            changed = check.answer(
                phone.post("/api/internal/password", headers=sam,
                           json={"current": current, "new": new}), pw,
            )  # fmt: skip
            assert phone.get("/api/internal/me", headers=sam).status_code == 401
            sam = bearer(changed["token"])
            assert phone.get("/api/internal/me", headers=sam).status_code == 200
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
        data = phone.get("/api/internal/speed-test?mb=1", headers=sam)
        assert data.status_code == 200 and len(data.content) == 1 << 20
        assert data.headers["stationplay-api"] == "1"
        assert phone.get("/api/internal/speed-test?mb=1").status_code == 401
        tested = {"mbps": 52.0, "app": "StationPlay for Android", "deviceName": "Pixel"}
        found = check.answer(
            phone.post("/api/internal/speed-test", headers=sam, json=tested),
            "POST /api/internal/speed-test",
        )
        assert (found["where"], found["mbps"]) == ("home", 52.0)

        # A problem report, for the Logs tab: each line plain, and not too many.
        lines = ["StationPlay for Android 0.1.0 (build 7)", "14:02:05 Tuned to 5\tHometown 5"]
        reported = phone.post(
            "/api/internal/report",
            headers=sam,
            json={"text": "\n".join(lines + ["x" * 10] * 500), "app": "StationPlay for Android",
                  "deviceName": "Pixel"},
        )  # fmt: skip
        assert check.answer(reported, "POST /api/internal/report") == {"ok": True}
        again = phone.post("/api/internal/report", headers=sam, json={"text": "Again"})
        check.answer(again, "POST /api/internal/report", 429)
        # A problem the app ran into, as it happened (see test_problems.py).
        problem = phone.post(
            "/api/internal/problem",
            headers=sam,
            json={"kind": "station-failed", "station": 5, "detail": "It didn't answer in time",
                  "app": "StationPlay for Android", "version": "0.1.0",
                  "device": "Pixel 8, Android 15", "deviceName": "Pixel"},
        )  # fmt: skip
        assert check.answer(problem, "POST /api/internal/problem") == {"ok": True}
        check.answer(
            phone.post("/api/internal/problem", headers=sam, json={"kind": "nope"}),
            "POST /api/internal/problem",
            400,
        )
        [entry] = [
            e["message"]
            for e in home.get("/api/logs?levels=WARNING").json()["entries"]
            if e["message"].startswith("Report from")
        ]
        head, *body = entry.splitlines()
        assert head == "Report from StationPlay for Android on Pixel (Sam):"
        assert body[:2] == [
            "StationPlay for Android 0.1.0 (build 7)",
            "14:02:05 Tuned to 5 Hometown 5",
        ]
        assert body[-1] == "(and 102 more lines, left off)" and len(body) == 401

        # Your library (see test_ondemand.py): shared by an Admin, then
        # browsed and played.
        check.answer(
            phone.get("/api/internal/libraries", headers=sam), "GET /api/internal/libraries", 404
        )
        assert home.put("/api/app-libraries", json={"libraries": ["1", "2"]}).status_code == 200
        features = check.answer(phone.get("/api/v1/server"), "GET /api/v1/server")["features"]
        assert features == [
            "hls", "speed-test", "reports", "night", "problems", "library", "convert",
            "convert-asked", "even-sound",
        ]  # fmt: skip
        libs = check.answer(
            phone.get("/api/internal/libraries", headers=sam), "GET /api/internal/libraries"
        )
        assert [(x["key"], x["kind"]) for x in libs["libraries"]] == [("1", "show"), ("2", "movie")]
        shows = check.answer(
            phone.get("/api/internal/libraries/1?size=10", headers=sam),
            "GET /api/internal/libraries/{key}",
        )
        assert shows["total"] == 1 and shows["items"][0]["unwatched"] == 4
        movies = check.answer(
            phone.get("/api/internal/libraries/2?sort=added", headers=sam),
            "GET /api/internal/libraries/{key}",
        )
        assert movies["items"][0]["poster"] == "/api/internal/art/300?kind=poster"
        comedies = check.answer(
            phone.get("/api/internal/libraries/2?genre=Comedy", headers=sam),
            "GET /api/internal/libraries/{key}",
        )
        assert [x["key"] for x in comedies["items"]] == ["301"]
        assert comedies["genres"] == ["Comedy", "Drama"]
        assert comedies["letters"] == [{"letter": "O", "start": 0}]  # ("The Other One")
        show = check.answer(
            phone.get("/api/internal/items/100", headers=sam), "GET /api/internal/items/{key}"
        )
        assert show["next"]["key"] == "201" and show["seasons"][0]["title"] == "Season 1"
        # Languages for the whole show, and for one episode (see test_languages.py).
        whole = check.answer(
            phone.put("/api/internal/items/100/languages", headers=sam,
                      json={"audio": "jpn", "captions": False, "captionLanguage": "eng"}),
            "PUT /api/internal/items/{key}/languages",
        )  # fmt: skip
        assert whole["item"]["audio"]["code"] == "jpn" and whole["show"] is None
        one = check.answer(
            phone.put("/api/internal/items/202/languages", headers=sam,
                      json={"audio": "eng", "captions": True, "captionLanguage": "es"}),
            "PUT /api/internal/items/{key}/languages",
        )  # fmt: skip
        assert (one["item"]["captions"], one["show"]["captions"]) == (True, False)
        episode = check.answer(
            phone.get("/api/internal/items/202", headers=sam), "GET /api/internal/items/{key}"
        )
        assert episode["languages"] == one
        cleared = check.answer(
            phone.delete("/api/internal/items/202/languages", headers=sam),
            "DELETE /api/internal/items/{key}/languages",
        )
        assert cleared == {"item": None, "show": whole["item"]}
        check.answer(
            phone.delete("/api/internal/items/100/languages", headers=sam),
            "DELETE /api/internal/items/{key}/languages",
        )
        assert (
            episode["showKey"] == "100"
            and episode["backdrop"] == "/api/internal/art/100?kind=backdrop"
        )
        movie = check.answer(
            phone.get("/api/internal/items/300", headers=sam), "GET /api/internal/items/{key}"
        )
        assert movie["markers"] == {"intro": None, "credits": None, "creditsToEnd": False}
        assert episode["markers"] == {
            "intro": [60_000, 120_000], "credits": [1_200_000, 1_320_000], "creditsToEnd": True
        }  # fmt: skip
        assert movie["picture"] == {"size": "4K", "hdr": "HDR10"}
        assert movie["tagline"] == "One of a kind."
        assert movie["cast"] == [
            {"name": "Ada Lund", "role": "Kit"},
            {"name": "Bo Hale", "role": ""},
        ]
        assert (movie["directors"], movie["writers"]) == (["Cy Marsh"], ["Cy Marsh", "Di Pell"])
        like = check.answer(
            phone.get("/api/internal/items/300/related", headers=sam),
            "GET /api/internal/items/{key}/related",
        )
        assert [x["key"] for x in like["items"]] == ["301"]
        assert [v["name"] for v in movie["versions"]] == ["4K · HDR10", "1080p"]
        listed = check.answer(
            phone.get("/api/internal/items/100/episodes?season=1", headers=sam),
            "GET /api/internal/items/{key}/episodes",
        )
        assert [e["episode"] for e in listed["episodes"]] == [1, 2, 3, 4]
        found = check.answer(
            phone.get("/api/internal/search?q=movie", headers=sam), "GET /api/internal/search"
        )
        assert [x["key"] for x in found["items"]] == ["300"] and found["onNow"] == []
        # (Search is where the stations and the library meet.)
        found = check.answer(
            phone.get("/api/internal/search?q=show", headers=sam), "GET /api/internal/search"
        )
        assert [x["key"] for x in found["items"]] == ["100"]
        assert [(s["number"], s["now"]["title"]) for s in found["onNow"]] == [(5, "Show")]
        poster = phone.get("/api/internal/art/300?kind=poster&w=300", headers=sam)
        assert poster.status_code == 200 and poster.headers["stationplay-api"] == "1"
        tv = {"containers": ["mkv"], "video": [{"codec": "hevc", "width": 3840, "height": 2160,
              "bitDepth": 10}], "hdr": ["hdr10"], "audio": ["aac"], "subtitles": ["srt"]}  # fmt: skip
        played = check.answer(
            phone.post("/api/internal/play", headers=sam, json={"key": "300", "device": tv}),
            "POST /api/internal/play",
        )
        assert played["method"] == "direct" and played["resumeMs"] == 0
        # (His Spanish captions: the file of their own beside it, which his player shows.)
        [spanish] = [t for t in played["subtitles"] if t["language"] == "Spanish"]
        assert played["chosen"] == {
            "audio": played["audio"][0]["id"], "audioWhy": "English, as you chose",
            "subtitle": spanish["id"], "subtitleWhy": "Spanish subtitles, as you chose",
        }  # fmt: skip
        assert played["version"] == movie["versions"][0]["id"] and played["whenSlow"] == "offer"
        assert [(v["playable"], v["why"]) for v in played["versions"]] == [
            (True, None), (False, ["its picture's format (H.264)"])
        ]  # fmt: skip
        assert phone.get(played["url"]).content == b"a movie, as it is" * 100
        [external] = [t for t in played["subtitles"] if t["external"]]
        assert phone.get(external["url"]).text.endswith("Hola\n")
        moved = check.answer(
            phone.post("/api/internal/progress", headers=sam,
                       json={"key": "300", "positionMs": 600_000, "session": played["session"]}),
            "POST /api/internal/progress",
        )  # fmt: skip
        assert moved == {"positionMs": 600_000, "watched": False}
        start = check.answer(phone.get("/api/internal/home", headers=sam), "GET /api/internal/home")
        assert [(c["key"], c["positionMs"]) for c in start["continue"]] == [("300", 600_000)]
        assert [a["title"] for a in start["added"]] == ["TV Shows", "Movies"]
        assert phone.post(played["leave"]).status_code == 204
        assert phone.get(played["url"]).status_code == 404
        played = check.answer(
            phone.post("/api/internal/play", headers=sam, json={"key": "202", "device": tv}),
            "POST /api/internal/play",
        )
        assert played["markers"]["intro"] == [60_000, 120_000]
        assert phone.post(played["leave"]).status_code == 204
        # A copy (StationPlay 1.24.0): a smaller picture made to fit.
        phone_device = {**tv, "video": [{"codec": "h264", "width": 1920, "height": 1080}],
                        "hls": ["ts"]}  # fmt: skip
        copied = check.answer(
            phone.post("/api/internal/play", headers=sam,
                       json={"key": "201", "device": phone_device, "maxKbps": 3000, "fit": True}),
            "POST /api/internal/play",
        )  # fmt: skip
        assert (copied["method"], copied["why"]) == (
            "convert", ["a smaller picture, to fit the connection"]
        )  # fmt: skip
        assert copied["url"].endswith("/index.m3u8") and copied["bitrateKbps"] <= 2000
        assert phone.post(copied["leave"]).status_code == 204
        # Reporting a problem (see test_reports.py): picked from the server's list.
        offered = check.answer(
            phone.get("/api/internal/report-choices", headers=sam),
            "GET /api/internal/report-choices",
        )
        assert offered["choices"][0] == {"id": "no-picture", "group": "Picture",
                                          "label": "No picture"}  # fmt: skip
        reported = check.answer(
            phone.post("/api/internal/report-problem", headers=sam,
                       json={"choice": "wrong-language", "key": "300", "positionMs": 60_000,
                             "method": "direct", "version": movie["versions"][0]["id"]}),
            "POST /api/internal/report-problem",
        )  # fmt: skip
        assert reported == {"detail": "Thanks. An Admin will take a look."}
        check.answer(
            phone.post("/api/internal/report-problem", headers=sam,
                       json={"choice": "no-sound", "key": "300"}),
            "POST /api/internal/report-problem",
            429,
        )  # fmt: skip
        check.answer(
            phone.post("/api/internal/report-problem", headers=sam,
                       json={"choice": "it's broken", "station": 5}),
            "POST /api/internal/report-problem",
            400,
        )  # fmt: skip

        # A device that has signed in before keeps its device token.
        again = phone.post("/api/internal/sign-in", json={**SAM, "device": signed["device"]})
        again_said = check.answer(again, "POST /api/internal/sign-in")
        assert again_said["device"] is None and again_said["askPin"] is False  # (he chose none)
        out = check.answer(
            phone.post("/api/internal/sign-out", headers=sam), "POST /api/internal/sign-out"
        )
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
            tv.post(
                "/api/internal/link", json={"app": "StationPlay for Roku", "deviceName": "Den Roku"}
            ),
            "POST /api/internal/link",
        )
        assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", started["code"])
        assert started["linkAt"] == "/link" and started["expiresIn"] == 600
        waiting = tv.post("/api/internal/link/check", json={"poll": started["poll"]})
        check.answer(waiting, "POST /api/internal/link/check", 202)
        check.answer(
            tv.post("/api/internal/link/check", json={"poll": "guess"}),
            "POST /api/internal/link/check",
            404,
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
            tv.post("/api/internal/link/check", json={"poll": started["poll"]}),
            "POST /api/internal/link/check",
        )
        assert linked["user"] == {"name": "Pat", "role": "admin"} and linked["askPin"] is True
        assert tv.get("/api/v1/stations", headers=bearer(linked["token"])).status_code == 200
        # (Handed over once.)
        gone = tv.post("/api/internal/link/check", json={"poll": started["poll"]})
        check.answer(gone, "POST /api/internal/link/check", 404)
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

        # A TV with a picker: linked with a code, then whoever's watching
        # picks themselves, or signs in by name (see test_picker.py).
        started = check.answer(
            tv.post(
                "/api/internal/link",
                json={"app": "StationPlay for Roku", "deviceName": "Den Roku", "picker": True},
            ),
            "POST /api/internal/link",
        )
        assert home.post("/api/access/link", json={"code": started["code"]}).status_code == 200
        linked = check.answer(
            tv.post("/api/internal/link/check", json={"poll": started["poll"]}),
            "POST /api/internal/link/check",
        )
        key = {"StationPlay-Device": linked["deviceKey"]}
        listed = check.answer(
            tv.get("/api/internal/picker", headers=key), "GET /api/internal/picker"
        )
        assert listed["device"] == "StationPlay for Roku on Den Roku"
        assert [(p["name"], p["admin"]) for p in listed["people"]] == [
            ("Pat", True),
            ("Sam", False),
        ]
        sam_id = next(p["id"] for p in listed["people"] if p["name"] == "Sam")
        picked = check.answer(
            tv.post("/api/internal/picker/choose", json={"id": sam_id}, headers=key),
            "POST /api/internal/picker/choose",
        )
        assert picked["user"] == {"name": "Sam", "role": "user"}
        signed = check.answer(
            tv.post("/api/internal/picker/sign-in", json=SAM, headers=key),
            "POST /api/internal/picker/sign-in",
        )
        removed = check.answer(
            tv.post("/api/internal/picker/remove", headers={**key, **bearer(signed["token"])}),
            "POST /api/internal/picker/remove",
        )
        assert removed == {"ok": True}
        check.answer(tv.get("/api/internal/picker"), "GET /api/internal/picker", 401)

        # From the internet, only over HTTPS.
        plain_http = TestClient(app, base_url=f"http://testserver:{PUBLIC_PORT}")
        refused = plain_http.post("/api/internal/sign-in", json=PAT)
        assert refused.status_code == 403 and "HTTPS" in refused.json()["detail"]
        assert plain_http.get("/api/v1/server").status_code == 403
        # Over HTTPS, once signing in is on: signing in and the stations, but
        # not the streams (until watching away from home is on: test_hls.py).
        outside = check.answer(internet.get("/api/v1/server"), "GET /api/v1/server")
        assert outside["signIn"] and outside["notSetUp"] is None
        token = check.answer(
            internet.post("/api/internal/sign-in", json=PAT), "POST /api/internal/sign-in"
        )
        pat = bearer(token["token"])
        assert internet.get("/api/v1/stations", headers=pat).status_code == 200
        assert internet.get("/hls/5/index.m3u8", headers=pat).status_code == 404
        away = internet.post("/api/internal/speed-test", headers=pat, json={"mbps": 12.5})
        assert check.answer(away, "POST /api/internal/speed-test")["where"] == "away"

        # StationPlay's API with an Admin's API token (see test_api.py): how
        # StationPlay is doing, and what an Admin can have it do.
        minted = home.post("/api/api-tokens", json={"name": "Home Assistant", "scope": "admin"})
        assert minted.status_code == 201, minted.text
        admin = bearer(minted.json()["token"])  # (from home, whose event loop the check runs on)
        ctx = app.state.ctx
        five_id = made.json()["id"]
        # (A station playing, as far as the status can tell.)
        ctx.broadcasters[five_id] = SimpleNamespace(
            running=True, viewers={"plex"}, now_playing=None, started_at_ms=0, off_air=False,
            off_air_why="",
        )  # fmt: skip
        try:
            status = check.answer(home.get("/api/v1/status", headers=admin), "GET /api/v1/status")
        finally:
            del ctx.broadcasters[five_id]
        assert status["playing"] == [{"number": 5, "viewers": 1}] and status["tuners"] >= 1
        updated = home.post("/api/v1/stations/5/update", headers=admin)
        assert check.answer(updated, "POST /api/v1/stations/{number}/update") == {
            "number": 5, "changed": False
        }  # fmt: skip
        missing = home.post("/api/v1/stations/9/update", headers=admin)
        check.answer(missing, "POST /api/v1/stations/{number}/update", 404)
        before = check.answer(
            home.get("/api/v1/stations/5/check", headers=admin),
            "GET /api/v1/stations/{number}/check",
        )
        assert before["total"] == 0 and not before["running"]
        checking = check.answer(
            home.post("/api/v1/stations/5/check", headers=admin),
            "POST /api/v1/stations/{number}/check",
        )
        assert checking["running"] and checking["total"] == 4
        for _ in range(100):
            checked = home.get("/api/v1/stations/5/check", headers=admin).json()
            if not checked["running"]:
                break
            time.sleep(0.05)
        assert checked["done"] == 4
        check.answer(
            home.post("/api/v1/guide/refresh", headers=admin), "POST /api/v1/guide/refresh"
        )
        backed = home.post("/api/v1/backups", headers=admin)
        name = check.answer(backed, "POST /api/v1/backups", 201)["name"]
        assert name in [b["name"] for b in home.get("/api/backups").json()["backups"]]
        spec = home.get("/api/v1/openapi.json", headers=admin)
        assert spec.status_code == 200 and spec.json()["info"]["title"] == "StationPlay API"

        # Admin alerts (see test_alerts.py): for Admins only.
        ctx.alerts.backup_failed()
        ctx.alerts.backup_failed()
        alerts = check.answer(home.get("/api/internal/alerts"), "GET /api/internal/alerts")
        assert [(a["kind"], a["fixed"]) for a in alerts["alerts"]] == [("backups", None)]
        user = bearer(again.json()["token"])
        check.answer(
            phone.get("/api/internal/alerts", headers=user), "GET /api/internal/alerts", 403
        )
        ctx.alerts.backup_made()
        alerts = check.answer(home.get("/api/internal/alerts"), "GET /api/internal/alerts")[
            "alerts"
        ]
        assert alerts[0]["fixed"] >= alerts[0]["since"]

        # StationPlay checking that apps reach it from outside (see
        # test_reach.py), through a reverse proxy to the public port.
        proxy = Proxy(app, PUBLIC_PORT)
        ctx.reach.transport = proxy.transport
        on = home.put("/api/away", json={"on": True, "address": "https://tv.example.com"})
        assert on.status_code == 200
        assert home.post("/api/away/check").json()["state"] == "up"
        reached = check.answer(proxy.answers[-1], "GET /api/internal/reach")
        assert reached == {"stationplay": True, "port": "public", "https": True}
        check.answer(internet.get("/api/internal/reach?n=guess"), "GET /api/internal/reach", 404)

        # With watching away from home on, Media through the public port too
        # (see test_ondemand.py), its programs at addresses of their own there.
        outside = check.answer(internet.get("/api/v1/server"), "GET /api/v1/server")
        assert {"away", "library", "convert"} <= set(outside["features"])
        box = {"containers": ["mkv"], "video": [{"codec": "hevc", "width": 3840, "height": 2160,
               "bitDepth": 10}], "hdr": ["hdr10"], "audio": ["aac"]}  # fmt: skip
        away = check.answer(
            internet.post("/api/internal/play", headers=pat, json={"key": "300", "device": box}),
            "POST /api/internal/play",
        )
        assert away["method"] == "direct" and away["whenSlow"] == "switch"
        assert internet.get(away["url"]).content == b"a movie, as it is" * 100
        assert internet.post(away["leave"]).status_code == 204
        assert internet.get(away["url"]).status_code == 404

        # No license (the owner's choice: the apps are unlocked in their
        # stores, and the server has no licensing at all).
        for method in ("get", "post", "delete"):
            assert getattr(phone, method)("/api/internal/license", headers=pat).status_code == 404
    check.everything_seen()


def test_a_report_is_kept_plain_and_short():
    assert appapi.report_text("a\x00b\n\n" + "y" * 30_000) == "a b\n\n(and 1 more line, left off)"
    assert appapi.report_text("  \n\t\n") == ""
