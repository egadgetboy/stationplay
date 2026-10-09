"""Media, rock solid (docs/on-demand.md, docs/internal-api.md): what the
apps get when Plex is slow, away or says something odd; odd data; large
libraries; Up next and the Resume row; progress; Viewing Levels on every
address; pictures; playing; and search. The everyday cases are in
test_ondemand.py, and the contract in test_app_api.py."""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import ondemand
from app import plex as plex_module
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex_library import LibraryPlex

ADA = {"name": "Ada", "password": "correct horse"}
KIT = {"name": "Kit", "password": "battery staple"}
# A TV box that plays H.264 and HEVC as they are, and takes copies.
TV = {
    "containers": ["mkv", "mp4"],
    "video": [{"codec": "h264", "width": 1920, "height": 1080, "bitDepth": 8},
              {"codec": "hevc", "width": 3840, "height": 2160, "bitDepth": 10}],
    "hdr": [],
    "audio": ["aac", "ac3"],
    "subtitles": ["srt"],
}  # fmt: skip
MINUTE = 60_000


class OddPlex(LibraryPlex):
    """The stand-in Plex, which can be made slow, or made to say something
    odd for some addresses."""

    def __init__(self) -> None:
        super().__init__()
        self.slow = False  # (every request waits until this is False again)
        self.slow_at: set[str] = set()  # (as do those for these addresses)
        self.pause = 0.0  # (each request to one of those takes this long, then)
        self.odd: dict[str, httpx.Response] = {}  # what's said instead, by address
        self.going = self.most_going = 0  # (requests being answered at once)

    async def answer(self, request: httpx.Request) -> httpx.Response:
        self.going += 1
        self.most_going = max(self.most_going, self.going)
        try:
            return await self._answer(request)
        finally:
            self.going -= 1

    async def _answer(self, request: httpx.Request) -> httpx.Response:
        while self.slow or (request.url.path in self.slow_at and not self.pause):
            await asyncio.sleep(0.02)
        if request.url.path in self.slow_at:
            await asyncio.sleep(self.pause)
        said = self.odd.get(request.url.path)
        if said is not None:
            return httpx.Response(said.status_code, content=said.content, headers=said.headers)
        return self.handler(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.answer)


def library() -> OddPlex:
    """A show with two seasons and a special, and a few movies."""
    fp = OddPlex()
    fp.add_show("100", "Bonanza", year=1959)
    for n in range(1, 4):
        fp.add_episode(f"20{n}", "100", 1, n, f"Episode {n}", f"/tv/b/{n}.mkv", 50 * MINUTE)
        fp.describe(f"20{n}")
    fp.add_episode("204", "100", 2, 1, "Season Two", "/tv/b/4.mkv", 50 * MINUTE)
    fp.add_episode("205", "100", 2, 2, "Season Two, Again", "/tv/b/5.mkv", 50 * MINUTE)
    fp.add_episode("209", "100", 0, 1, "A Special", "/tv/b/9.mkv", 50 * MINUTE)
    for key in ("204", "205", "209"):
        fp.describe(key)
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("300", "The Movie", "/films/movie.mkv", 100 * MINUTE, year=1999, section="2",
                 genres=["Drama"])  # fmt: skip
    fp.describe("300")
    fp.add_movie("301", "Another Movie", "/films/other.mkv", 90 * MINUTE, section="2",
                 genres=["Drama"])  # fmt: skip
    fp.describe("301")
    for key in ("201", "202", "300", "301"):
        fp.files[key] = b"a program" * 100
    return fp


@pytest.fixture
def plex(monkeypatch) -> OddPlex:
    monkeypatch.setattr(plex_module, "RETRY_S", 0.01)  # (asking Plex again, at once)
    return library()


@pytest.fixture
def app(plex, tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=plex.transport()))
    app.state.ctx.play_transport = plex.transport()
    return app


def shared(client: TestClient) -> None:
    assert client.put("/api/app-libraries", json={"libraries": ["1", "2"]}).status_code == 200


def play(client: TestClient, key: str, device: dict | None = None, **more) -> httpx.Response:
    return client.post("/api/internal/play", json={"key": key, "device": device or TV, **more})


# Every address of the library, as an app asks it (what `refused` checks).
ASKS = (
    ("GET", "/api/internal/libraries", None),
    ("GET", "/api/internal/libraries/2", None),
    ("GET", "/api/internal/home", None),
    ("GET", "/api/internal/search?q=movie", None),
    ("GET", "/api/internal/items/300", None),
    ("GET", "/api/internal/items/100", None),
    ("GET", "/api/internal/items/300/related", None),
    ("GET", "/api/internal/items/100/episodes", None),
    ("GET", "/api/internal/art/300?kind=poster&w=320", None),
    ("PUT", "/api/internal/items/300/languages", {"audio": "eng"}),
    ("DELETE", "/api/internal/items/300/languages", None),
    ("POST", "/api/internal/play", {"key": "300", "device": TV}),
    ("POST", "/api/internal/progress", {"key": "300", "positionMs": 20 * MINUTE}),
)


def settled(app) -> None:
    """Waits for what the library was asked in the background to be done
    (fetches carry on past an app's wait: see Catalog._once)."""
    for _ in range(200):
        if not app.state.ctx.catalog._fetching:
            return
        time.sleep(0.05)
    raise AssertionError("still fetching")


def refused(res: httpx.Response, status: int, detail: str | None = None) -> None:
    """A refusal, as the apps are promised: a status and a sentence to show
    as it is, never a stack trace."""
    assert res.status_code == status, (res.request.url, res.status_code, res.text)
    body = res.json()
    assert set(body) <= {"detail", "why", "limit", "most"} and isinstance(body["detail"], str)
    assert "Traceback" not in res.text and "plex.test" not in res.text
    if detail is not None:
        assert body["detail"] == detail, body


# 1. Plex slow or away ------------------------------------------------------------------------


def test_plex_slow_answers_503_within_moments(app, plex, monkeypatch):
    monkeypatch.setattr(ondemand, "LIBRARY_WAIT_S", 0.4)
    with TestClient(app) as home:
        shared(home)
        plex.slow = True
        try:
            for method, path, body in ASKS:
                began = time.monotonic()
                res = home.request(method, path, json=body)
                refused(res, 503, ondemand.UNREACHABLE)
                assert time.monotonic() - began < 2.0, path
        finally:
            plex.slow = False
        # What was being fetched carried on: asked again, it's there.
        settled(app)
        assert home.get("/api/internal/libraries/2").status_code == 200
        assert home.get("/api/internal/items/300").status_code == 200


def test_plex_away_answers_503_and_its_404_is_ours(app, plex, monkeypatch, caplog):
    monkeypatch.setattr(ondemand, "LIBRARY_WAIT_S", 0.5)
    with TestClient(app) as home:
        shared(home)
        plex.down = True
        for method, path, body in ASKS:
            refused(home.request(method, path, json=body), 503, ondemand.UNREACHABLE)
        # (Said in the log once, not for every app's every ask.)
        assert caplog.text.count("couldn't be shown your library") == 1
        plex.down = False
        settled(app)
        # Plex's "no such thing" is ours: as for anything not shared.
        plex.odd["/library/metadata/300"] = httpx.Response(404)
        refused(home.get("/api/internal/items/300"), 404, ondemand.NOT_SHARED)
        assert home.get("/api/internal/items/987654").json() == {"detail": ondemand.NOT_SHARED}
        plex.odd["/library/sections/2/all"] = httpx.Response(404)  # (gone since it was listed)
        refused(home.get("/api/internal/libraries/2"), 404, ondemand.NOT_SHARED)


UNREADABLE = [
    b"<html>Plex is updating</html>",  # (not JSON)
    b"[1, 2, 3]",  # (not what Plex says)
    b'{"MediaContainer": "busy"}',
    b'{"MediaContainer": {"Metadata": "nothing"}}',
    b'{"MediaContainer": {"Metadata": {"ratingKey": "300"}}}',
    b'{"MediaContainer": {"Metadata": [{"title": "The Movie"}]}}',  # (no kind, no key)
]
# Where Plex says it, and the apps' addresses that then can't be answered.
UNREADABLE_AT = {
    "/library/metadata/300": ("/api/internal/items/300", "/api/internal/play",
                              "/api/internal/progress"),
    "/library/sections": ("/api/internal/libraries",),
    "/library/sections/2/all": ("/api/internal/libraries/2", "/api/internal/search"),
}  # fmt: skip


@pytest.mark.parametrize("said", UNREADABLE)
@pytest.mark.parametrize("address", list(UNREADABLE_AT))
def test_plex_saying_what_cant_be_read_is_as_though_its_away(app, plex, monkeypatch, address, said):
    monkeypatch.setattr(ondemand, "LIBRARY_WAIT_S", 0.5)
    plex.odd = {address: httpx.Response(200, content=said)}
    with TestClient(app) as home:
        shared(home)
        for method, path, body in ASKS:
            res = home.request(method, path, json=body)
            # (A list of libraries that doesn't mention them: none. A list
            # with one thing in it that can't be read: the rest.)
            whole = said in UNREADABLE[:3] or (
                address != "/library/sections"
                and (address == "/library/metadata/300" or said != UNREADABLE[-1])
            )
            if (
                whole
                and path.split("?")[0] in UNREADABLE_AT[address]
                and (address != "/library/metadata/300" or "300" in json.dumps([path, body]))
            ):
                refused(res, 503, ondemand.UNREACHABLE)
            elif res.status_code >= 400:
                refused(res, res.status_code)  # (whatever it is, said as a sentence)
                assert res.status_code in (404, 503), (path, res.text)


def test_odd_fields_from_plex_are_left_out_not_failed_on(app, plex):
    """Plex describing something oddly (a field of the wrong kind) leaves
    that field out, rather than failing the whole answer."""
    plex.more["300"] = {
        "Genre": 5, "Role": "everyone", "Director": [None, {"tag": 7}, {"tag": "Cy"}],
        "year": "1999", "duration": "long", "Marker": [None, "intro"], "summary": None,
    }  # fmt: skip
    plex.add_movie("302", "No File", "/films/none.mkv", 60 * MINUTE, section="2")
    plex.more["302"] = {"Media": "a file"}
    plex.episodes["301"]["Genre"] = {"tag": "Drama"}
    plex.episodes["301"]["Role"] = 12
    with TestClient(app) as home:
        shared(home)
        movie = home.get("/api/internal/items/300")
        assert movie.status_code == 200, movie.text
        got = movie.json()
        assert (got["genres"], got["cast"], got["year"], got["durationMs"]) == ([], [], None, None)
        assert got["directors"] == ["7", "Cy"] and got["markers"]["intro"] is None
        assert got["summary"] == ""
        none = home.get("/api/internal/items/302").json()
        assert (none["versions"], none["audio"], none["picture"]) == ([], [], None)
        refused(play(home, "302"), 404, "This program has no file to play")
        listed = home.get("/api/internal/libraries/2").json()["items"]
        assert {m["key"] for m in listed} == {"300", "301", "302"}


# 2, 3 and 9. Odd titles, lists and search --------------------------------------------------


def titled(plex: OddPlex, *titles: str, sort: dict[str, str] | None = None) -> dict[str, str]:
    """Movies with these titles (keys from 500 up), and their sort titles as
    Plex has them: title -> key."""
    keys = {}
    for n, title in enumerate(titles):
        key = str(500 + n)
        plex.add_movie(key, title, f"/films/{key}.mkv", 90 * MINUTE, section="2",
                       added_at=1_700_000_000 + n % 3)  # fmt: skip
        if sort and title in sort:
            plex.episodes[key]["titleSort"] = sort[title]
        keys[title] = key
    return keys


ODD_TITLES = (
    "The Orbit Room", "A Drama", "An Ending", "Another Movie", "Élan", "Æon Flux", "eagle",
    "Saw 10", "Saw 2", "9 Lives", "(500) Days", "Hamlet", "Hamlet", "Zorro", "אבא",
    "東京物語", "The", "Amélie", "Spider-Man", "x" * 2_000, "¡Three Amigos!",
)  # fmt: skip


def test_titles_sort_as_the_library_does_whatever_they_are(app, plex):
    keys = titled(plex, *ODD_TITLES, sort={"The Orbit Room": "Orbit Room"})
    with TestClient(app) as home:
        shared(home)
        page = home.get("/api/internal/libraries/2?size=200").json()
        listed = [m["title"] for m in page["items"]]
        assert listed == [
            "9 Lives", "(500) Days", "אבא", "東京物語",  # ("#": digits, other alphabets)
            "Æon Flux", "Amélie", "Another Movie", "Another Movie",  # (case and accents aside)
            "A Drama", "eagle", "Élan", "An Ending", "Hamlet", "Hamlet", "The Movie",
            "The Orbit Room", "Saw 2", "Saw 10", "Spider-Man", "The", "¡Three Amigos!",
            "x" * 2_000, "Zorro",
        ]  # fmt: skip
        # Titles alike: in the order of their keys, every time.
        hamlets = [m["key"] for m in page["items"] if m["title"] == "Hamlet"]
        assert hamlets == sorted(hamlets, key=int)
        # Every letter together, in order, for jumping to it.
        letters = [(x["letter"], x["start"]) for x in page["letters"]]
        assert letters == [
            ("#", 0), ("A", 4), ("D", 8), ("E", 9), ("H", 12), ("M", 14), ("O", 15), ("S", 16),
            ("T", 19), ("X", 21), ("Z", 22),
        ]  # fmt: skip
        assert keys["The"] in [m["key"] for m in page["items"]]  # (just "The": under T)


@pytest.mark.parametrize("sort", ["title", "added", "released"])
def test_pages_never_repeat_or_skip(app, plex, sort):
    titled(plex, *(f"Movie {n % 7}" for n in range(60)))
    for n in range(0, 60, 2):
        plex.released[str(500 + n)] = "2001-02-03"  # (half on one day; the rest without one)
    with TestClient(app) as home:
        shared(home)
        whole = home.get(f"/api/internal/libraries/2?sort={sort}&size=200").json()
        seen = []
        for start in range(0, whole["total"], 7):
            page = home.get(f"/api/internal/libraries/2?sort={sort}&start={start}&size=7").json()
            assert page["total"] == whole["total"] and page["start"] == start
            seen += [m["key"] for m in page["items"]]
        assert seen == [m["key"] for m in whole["items"]] and len(set(seen)) == len(seen) == 62
        # (And the same again, after the library is asked again.)
        home.app.state.ctx.catalog._wholes.clear()
        again = home.get(f"/api/internal/libraries/2?sort={sort}&size=200").json()
        assert [m["key"] for m in again["items"]] == seen


def test_a_shows_episodes_a_page_at_a_time(app, plex):
    for n in range(4, 13):
        plex.add_episode(f"6{n:02d}", "100", 3, n, f"Three {n}", f"/tv/b/3{n}.mkv", 20 * MINUTE)
    plex.add_episode("690", "100", 3, None, "No Number", "/tv/b/x.mkv", 20 * MINUTE)
    with TestClient(app) as home:
        shared(home)
        everything = home.get("/api/internal/items/100/episodes").json()
        assert (everything["total"], len(everything["episodes"])) == (16, 16)
        assert everything["start"] == 0
        order = [(e["season"], e["episode"]) for e in everything["episodes"]]
        assert order[-3:] == [(3, 12), (3, None), (0, 1)]  # (without a number, then specials)
        pages = [home.get(f"/api/internal/items/100/episodes?start={s}&size=5").json()
                 for s in range(0, 16, 5)]  # fmt: skip
        assert [e["key"] for p in pages for e in p["episodes"]] == [
            e["key"] for e in everything["episodes"]
        ]
        three = home.get("/api/internal/items/100/episodes?season=3&size=4&start=8").json()
        assert (three["total"], [e["key"] for e in three["episodes"]]) == (10, ["612", "690"])
        for bad in ("size=0", "size=501", "start=-1", "season=x", "start=1000001"):
            refused(home.get(f"/api/internal/items/100/episodes?{bad}"), 400)
        refused(home.get("/api/internal/items/300/episodes"), 400, "That isn't a show")


def test_search_finds_titles_case_accents_and_punctuation_aside(app, plex):
    titled(plex, "Amélie", "Spider-Man", "Alien", "Aliens", "The Alien Within", "Mr. & Mrs. Smith",
           "100% Wolf", "Under_score", "O'Brien", "Señor Smile 🙂")  # fmt: skip
    with TestClient(app) as home:
        shared(home)

        def found(q: str) -> list[str]:
            got = home.get("/api/internal/search", params={"q": q})
            assert got.status_code == 200, (q, got.text)
            return [m["title"] for m in got.json()["items"]]

        assert found("Amelie") == found("AMÉLIE") == ["Amélie"]
        assert found("spiderman") == found("spider man") == found("Spider-Man") == ["Spider-Man"]
        # The best first: just that, then starting with it (its sort title
        # too), then a word, then anywhere; each in title order.
        assert found("alien") == ["Alien", "The Alien Within", "Aliens"]
        assert found("within") == ["The Alien Within"]
        assert found("lien") == ["Alien", "The Alien Within", "Aliens"]
        titled(plex, "Within Reach")
        home.app.state.ctx.catalog._wholes.clear()
        assert found("within") == ["Within Reach", "The Alien Within"]
        assert found("mr & mrs") == ["Mr. & Mrs. Smith"]
        assert found("100%") == ["100% Wolf"] and found("%") == [] and found("_") == []
        assert found("o'brien") == found("obrien") == ["O'Brien"]
        assert found("senor smile 🙂") == ["Señor Smile 🙂"]
        assert found("!!!") == []  # (nothing to search for in that)
        # One letter is enough (searching as the viewer types), up to 50.
        titled_more = home.get("/api/internal/search?q=e").json()["items"]
        assert 0 < len(titled_more) <= ondemand.SEARCH_MOST
        refused(home.get("/api/internal/search?q="), 400, "Type something to search for")
        too_long = home.get("/api/internal/search?q=" + "a" * 101)
        refused(too_long, 400, "That's too long to search for")
        assert home.get("/api/internal/search?q=" + "a" * 100).status_code == 200


def test_search_keeps_the_first_fifty_someone_may_see(app, plex):
    titled(plex, *(f"Night {n}" for n in range(60)))
    for n in range(60):
        plex.episodes[str(500 + n)]["contentRating"] = "R" if n < 40 else "G"
    with TestClient(app) as admin:
        shared(admin)
        assert len(admin.get("/api/internal/search?q=night").json()["items"]) == 50
        admin.post("/api/access/users", json=ADA)
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        levels = admin.get("/api/access/viewing").json()["levels"]
        kid = next(lv["id"] for lv in levels if lv["builtin"] == "kid")
        admin.put(f"/api/access/users/{kit['id']}/viewing", json={"level": kid})
        phone = TestClient(app)
        token = phone.post("/api/internal/sign-in", json=KIT).json()["token"]
        found = phone.get("/api/internal/search?q=night",
                          headers={"Authorization": f"Bearer {token}"}).json()["items"]  # fmt: skip
        assert [m["title"] for m in found] == [f"Night {n}" for n in range(40, 60)]


def test_a_large_library_answers_quickly_a_page_at_a_time(tmp_path):
    """5,000 movies, 300 shows and 20,000 episodes: once a library's list is
    kept, each list answers in moments, and every list is bounded."""
    fp = OddPlex()
    fp.add_section("2", "Movies", "movie")
    for n in range(5_000):
        key = str(10_000 + n)
        fp.add_movie(key, f"{'The ' if n % 3 == 0 else ''}Movie {n}", f"/m/{n}.mkv", 90 * MINUTE,
                     section="2", genres=["Drama" if n % 2 else "Comedy"],
                     added_at=1_600_000_000 + n // 10)  # fmt: skip
    for s in range(300):
        fp.add_show(str(100_000 + s), f"Show {s}", genres=["Drama"])
    for e in range(20_000):
        show, n = str(100_000 + e % 300), e // 300
        fp.add_episode(str(200_000 + e), show, 1 + n // 10, n % 10 + 1, f"Ep {e}", f"/t/{e}.mkv",
                       22 * MINUTE)  # fmt: skip
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(settings, PlexClient("http://plex.test", "token", transport=fp.transport()))
    with TestClient(app) as home:
        shared(home)
        first = home.get("/api/internal/libraries/2?size=200")
        assert first.status_code == 200 and first.json()["total"] == 5_000
        assert len(first.content) < 100_000  # (a page of 200, about 35 KB)
        asked = len(fp.requests)
        for path in (
            "/api/internal/libraries/2?size=200&start=4800",
            "/api/internal/libraries/2?size=50&sort=added",
            "/api/internal/libraries/2?size=50&sort=released",
            "/api/internal/libraries/2?size=50&unwatched=1",
            "/api/internal/search?q=movie 4999",
            "/api/internal/search?q=e",
            "/api/internal/items/10001/related",
        ):
            began = time.monotonic()
            res = home.get(path)
            assert res.status_code == 200 and len(res.content) < 100_000, path
            assert time.monotonic() - began < 1.0, path
        assert len(fp.requests) - asked <= 3  # (Plex asked only for what wasn't kept)
        page = home.get("/api/internal/libraries/2?size=200&start=4800").json()
        assert [m["title"] for m in page["items"]][-1] == "Movie 4999"
        letters = home.get("/api/internal/libraries/2?size=1").json()["letters"]
        assert letters == [{"letter": "M", "start": 0}]
        for path in (
            "/api/internal/libraries/1?size=200",
            "/api/internal/home",
            "/api/internal/items/100001",
            "/api/internal/items/100001/episodes",
        ):
            res = home.get(path)
            assert res.status_code == 200 and len(res.content) < 100_000, path
        episodes = home.get("/api/internal/items/100001/episodes").json()
        assert episodes["total"] == len(episodes["episodes"]) == 67


# 4. Up next and the Resume row ------------------------------------------------------------


def report(client: TestClient, key: str, ms: int | None = None, **more) -> dict:
    body = {"key": key, **({"positionMs": ms} if ms is not None else {}), **more}
    got = client.post("/api/internal/progress", json=body)
    assert got.status_code == 200, got.text
    return got.json()


def up_next(client: TestClient, show: str = "100") -> str | None:
    found = client.get(f"/api/internal/items/{show}").json()["next"]
    return found and found["key"]


def resume_row(client: TestClient) -> list[tuple[str, int]]:
    row = client.get("/api/internal/home").json()["continue"]
    return [(c["key"], c["positionMs"]) for c in row]


def test_up_next_across_seasons_and_specials(app):
    with TestClient(app) as home:
        shared(home)
        assert up_next(home) == "201" and resume_row(home) == []  # (not started: not resumed)
        report(home, "201", 50 * MINUTE)
        report(home, "202", 50 * MINUTE)
        report(home, "203", 50 * MINUTE)
        assert up_next(home) == "204" and resume_row(home) == [("204", 0)]  # (season 2)
        # A special in between: they're where they were before it.
        report(home, "209", 50 * MINUTE)
        assert up_next(home) == "204" and resume_row(home) == [("204", 0)]
        # Partway through a special: that's the one to carry on with.
        report(home, "209", 10 * MINUTE)
        assert up_next(home) == "209" and resume_row(home) == [("209", 10 * MINUTE)]
        report(home, "209", 49 * MINUTE)
        # Barely started (under a minute): from the start, but it's the one.
        report(home, "204", 30_000)
        assert up_next(home) == "204" and resume_row(home) == [("204", 0)]


def test_a_show_finished_has_nothing_next(app):
    with TestClient(app) as home:
        shared(home)
        report(home, "201", 50 * MINUTE)
        report(home, "203", 50 * MINUTE)  # (one skipped)
        assert up_next(home) == "204"
        report(home, "205", 50 * MINUTE)  # (the last)
        assert up_next(home) is None and resume_row(home) == []
        # Watching an earlier one again: the next one they haven't seen.
        report(home, "201", 20 * MINUTE)
        assert up_next(home) == "201"
        report(home, "201", 50 * MINUTE)
        assert up_next(home) == "202" and resume_row(home) == [("202", 0)]
        # Marked unwatched from a menu: it says nothing about where they are.
        report(home, "203", watched=False)
        assert up_next(home) == "202"


def test_the_resume_row_newest_first_one_per_show(app, plex):
    plex.add_show("110", "Other Show")
    plex.add_episode("211", "110", 1, 1, "Other 1", "/tv/o/1.mkv", 30 * MINUTE)
    plex.add_episode("212", "110", 1, 2, "Other 2", "/tv/o/2.mkv", 30 * MINUTE)
    with TestClient(app) as home:
        shared(home)
        report(home, "300", 20 * MINUTE)
        report(home, "211", 30 * MINUTE)  # (finished: next is 212)
        report(home, "201", 10 * MINUTE)
        report(home, "202", 12 * MINUTE)  # (the same show, later: the one for it)
        report(home, "301", 30_000)  # (a movie barely started isn't resumed)
        assert resume_row(home) == [("202", 12 * MINUTE), ("212", 0), ("300", 20 * MINUTE)]
        # Near the end (90% of the way, or into its credits): watched, and Up next.
        report(home, "300", 90 * MINUTE)
        assert report(home, "202", 46 * MINUTE) == {"positionMs": 0, "watched": True}
        assert resume_row(home) == [("203", 0), ("212", 0)]


def test_plexs_own_watched_marks_are_left_as_they_are(app, plex):
    """Decided: one Plex account can't stand for several people, so what's
    watched in Plex's own players doesn't move anyone's place here (and
    nothing here is sent to Plex)."""
    for key in ("201", "202"):
        plex.episodes[key].update(viewCount=1, lastViewedAt=1_700_000_000)
    plex.episodes["203"]["viewOffset"] = 20 * MINUTE
    with TestClient(app) as home:
        shared(home)
        assert up_next(home) == "201" and resume_row(home) == []
        report(home, "201", 50 * MINUTE)
        assert plex.posts == []  # (nothing sent on to Plex)
        assert not [r for r in plex.requests if "scrobble" in r or "timeline" in r]


def test_episodes_in_one_file_are_watched_together(app, plex):
    """A file with two episodes in it (S01E01-E02): Plex lists each; playing
    either plays the file, where it was, and finishing it finishes both."""
    for key in ("201", "202"):
        plex.episodes[key]["Media"][0]["Part"][0]["file"] = "/tv/b/S01E01-E02.mkv"
    with TestClient(app) as home:
        shared(home)
        listed = home.get("/api/internal/items/100/episodes?season=1").json()["episodes"]
        assert [(e["episode"], e["episodeTitle"]) for e in listed][:2] == [
            (1, "Episode 1"), (2, "Episode 2")
        ]  # fmt: skip
        report(home, "201", 30 * MINUTE)
        cards = home.get("/api/internal/items/100/episodes?season=1").json()["episodes"]
        assert [e["positionMs"] for e in cards] == [30 * MINUTE, 30 * MINUTE, 0]
        assert len(resume_row(home)) == 1  # (one show, one place)
        report(home, "201", 50 * MINUTE)
        cards = home.get("/api/internal/items/100/episodes?season=1").json()["episodes"]
        assert [e["watched"] for e in cards] == [True, True, False]
        assert up_next(home) == "203" and resume_row(home) == [("203", 0)]


def test_a_show_with_only_specials_still_has_what_is_next(app, plex):
    plex.add_show("120", "Holiday Specials")
    plex.add_episode("221", "120", 0, 1, "Winter", "/tv/h/1.mkv", 30 * MINUTE)
    plex.add_episode("222", "120", 0, 2, "Summer", "/tv/h/2.mkv", 30 * MINUTE)
    with TestClient(app) as home:
        shared(home)
        assert up_next(home, "120") == "221"
        report(home, "221", 30 * MINUTE)
        assert up_next(home, "120") == "222"


# 5. Progress ------------------------------------------------------------------------------


def test_progress_out_of_bounds_is_refused_and_a_little_past_the_end_is_the_end(app, plex):
    plex.add_movie("302", "No Length", "/films/x.mkv", 0, section="2")
    plex.episodes["302"].pop("duration")
    with TestClient(app) as home:
        shared(home)
        for wrong in (-1, -(2**40), 7 * 86_400_000 + 1, 2**63, "soon", 1.5e300):
            got = home.post("/api/internal/progress", json={"key": "300", "positionMs": wrong})
            refused(got, 400)
        report(home, "300", 20 * MINUTE)
        # Absurdly far past the end (more than 10 minutes): refused; nothing changes.
        too_far = {"key": "300", "positionMs": 111 * MINUTE}
        refused(home.post("/api/internal/progress", json=too_far), 400,
                "That's past the end of this program")  # fmt: skip
        assert home.get("/api/internal/items/300").json()["positionMs"] == 20 * MINUTE
        # A little past it: the end. Watched, from the start next time.
        assert report(home, "300", 100 * MINUTE + 900) == {"positionMs": 0, "watched": True}
        # How long it is isn't known: taken as it is.
        assert report(home, "302", 300 * MINUTE) == {"positionMs": 300 * MINUTE, "watched": False}
        refused(
            home.post("/api/internal/progress", json={"key": "300"}),
            400,
            "Send positionMs, or watched",
        )
        refused(home.post("/api/internal/progress", json={"key": "100", "watched": True}), 400)
        refused(home.post("/api/internal/progress", json={"key": "300", "positionMs": 1,
                                                           "sequence": 0}), 400)  # fmt: skip


def test_a_late_report_never_moves_someone_back(app, plex, caplog):
    caplog.set_level("INFO")
    with TestClient(app) as home:
        shared(home)
        played = play(home, "300").json()
        session = played["session"]

        def at(ms: int, n: int | None) -> dict:
            more = {"session": session, **({"sequence": n} if n else {})}
            return report(home, "300", ms, **more)

        assert at(10 * MINUTE, 1)["positionMs"] == 10 * MINUTE
        assert at(30 * MINUTE, 3)["positionMs"] == 30 * MINUTE
        # Sent before the last one, arriving after it: what's kept stays.
        assert at(20 * MINUTE, 2) == {"positionMs": 30 * MINUTE, "watched": False}
        assert home.get("/api/internal/items/300").json()["positionMs"] == 30 * MINUTE
        # Rewinding is a newer report: back it goes.
        assert at(5 * MINUTE, 4)["positionMs"] == 5 * MINUTE
        # The last, as it stops; then leaving. One straggling in after: still late.
        assert at(6 * MINUTE, 5)["positionMs"] == 6 * MINUTE
        assert home.post(played["leave"]).status_code == 204
        assert "stopped The Movie (1999) at 6:00" in caplog.text
        assert at(50 * MINUTE, 4) == {"positionMs": 6 * MINUTE, "watched": False}
        # Apps that don't number their reports: as they arrive.
        assert at(40 * MINUTE, None)["positionMs"] == 40 * MINUTE
        assert at(20 * MINUTE, None)["positionMs"] == 20 * MINUTE


def test_reporting_every_second_never_reaches_plex(app, plex):
    with TestClient(app) as home:
        shared(home)
        played = play(home, "201").json()
        asked = list(plex.requests)
        for second in range(60):
            report(home, "201", 20 * MINUTE + second * 1000, session=played["session"],
                   sequence=second + 1)  # fmt: skip
        assert plex.requests == asked and plex.posts == []
        # Nor does Plex away stop it being kept, while it plays.
        plex.down = True
        assert report(home, "201", 22 * MINUTE, session=played["session"],
                      sequence=61)["positionMs"] == 22 * MINUTE  # fmt: skip
        plex.down = False
        assert home.get("/api/internal/items/201").json()["positionMs"] == 22 * MINUTE
        # Someone else's playing (or another program's) isn't theirs to report on.
        report(home, "202", 15 * MINUTE, session=played["session"])
        assert home.get("/api/internal/items/202").json()["positionMs"] == 15 * MINUTE


# 6. Viewing Levels on every address ----------------------------------------------------------


def every_ask(key: str, show: str = "100") -> list[tuple[str, str, dict | None]]:
    """Each address of the library about one show, movie or episode."""
    return [
        ("GET", f"/api/internal/items/{key}", None),
        ("GET", f"/api/internal/items/{key}/related", None),
        ("GET", f"/api/internal/items/{key}/episodes", None),
        ("GET", f"/api/internal/art/{key}?kind=poster", None),
        ("GET", f"/api/internal/art/{key}?kind=backdrop&w=1280", None),
        ("GET", f"/api/internal/art/{key}?kind=thumb", None),
        ("PUT", f"/api/internal/items/{key}/languages", {"audio": "eng"}),
        ("DELETE", f"/api/internal/items/{key}/languages", None),
        ("POST", "/api/internal/play", {"key": key, "device": TV}),
        ("POST", "/api/internal/progress", {"key": key, "positionMs": 5 * MINUTE}),
        ("POST", "/api/internal/progress", {"key": key, "watched": True}),
    ]


def limited(app, plex) -> tuple[TestClient, dict[str, str], dict[str, str]]:
    """Ada (an Admin), Kit (on Kid) and Lee (on a level with only the TV
    library), each signed in to an app; a TV-MA show and an R movie."""
    plex.add_show("110", "Night Shift", contentRating=["TV-MA"])
    plex.add_episode("211", "110", 1, 1, "Shift 1", "/tv/n/1.mkv", 44 * MINUTE)
    plex.describe("211")
    plex.files["211"] = b"a program" * 100
    plex.shows["100"]["contentRating"] = "TV-G"
    plex.episodes["300"]["contentRating"] = "PG"
    plex.episodes["301"]["contentRating"] = "R"
    admin = TestClient(app)
    admin.__enter__()
    shared(admin)
    admin.post("/api/access/users", json=ADA)
    kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
    lee = admin.post("/api/access/users", json={"name": "Lee", "password": "a long one",
                                                 "role": "user"}).json()  # fmt: skip
    levels = admin.get("/api/access/viewing").json()["levels"]
    kid = next(lv["id"] for lv in levels if lv["builtin"] == "kid")
    tv_only = admin.post("/api/access/levels", json={"name": "TV only", "libraries": ["1"]})
    admin.put(f"/api/access/users/{kit['id']}/viewing", json={"level": kid})
    admin.put(f"/api/access/users/{lee['id']}/viewing", json={"level": tv_only.json()["id"]})

    def token(who: dict) -> dict[str, str]:
        signed = TestClient(app).post("/api/internal/sign-in", json=who)
        return {"Authorization": f"Bearer {signed.json()['token']}"}

    return admin, token(KIT), token({"name": "Lee", "password": "a long one"})


def test_every_address_refuses_what_someone_may_not_see_the_same_way(app, plex):
    admin, kit, lee = limited(app, plex)
    try:
        phone = TestClient(app)
        # What Ada watches is on her Resume row; it's still not Kit's to see or play.
        signed = phone.post("/api/internal/sign-in", json=ADA).json()
        ada = {"Authorization": f"Bearer {signed['token']}"}
        phone.post("/api/internal/progress", json={"key": "211", "positionMs": 9 * MINUTE},
                   headers=ada)  # fmt: skip
        resume = phone.get("/api/internal/home", headers=ada).json()["continue"]
        assert [c["key"] for c in resume] == ["211"]
        phone.get("/api/internal/art/301", headers=ada)  # (and its poster is kept)
        missing = phone.get("/api/internal/items/987654", headers=kit).json()
        for who, hidden in ((kit, ("110", "211", "301")), (lee, ("300", "301"))):
            for key in hidden:
                for method, path, body in every_ask(key):
                    res = phone.request(method, path, json=body, headers=who)
                    refused(res, 404)
                    assert res.json() == missing, (key, path)
            # Nor is any of it in a list.
            lists = [
                phone.get(path, headers=who).text
                for path in ("/api/internal/libraries/1", "/api/internal/home",
                             "/api/internal/search?q=i", "/api/internal/items/100/related",
                             "/api/internal/items/100/episodes", "/api/internal/items/100")
            ]  # fmt: skip
            for key in hidden:
                assert all(f'"key":"{key}"' not in text for text in lists), key
        # Kit sees and plays what Kid allows; Lee, the TV library only.
        for method, path, body in every_ask("201"):
            seen = phone.request(method, path, json=body, headers=kit)
            assert seen.status_code < 400 or path.endswith("/episodes"), path  # (not a show)
        assert [x["key"] for x in phone.get("/api/internal/libraries", headers=lee).json()[
            "libraries"]] == ["1"]  # fmt: skip
        refused(phone.get("/api/internal/libraries/2", headers=lee), 404, ondemand.NOT_SHARED)
        assert phone.get("/api/internal/libraries/2", headers=kit).status_code == 200
        # Someone's playing is theirs: another's session doesn't let Kit report on it.
        played = phone.post("/api/internal/play", json={"key": "211", "device": TV},
                            headers=ada).json()  # fmt: skip
        sneaky = {"key": "211", "positionMs": 1 * MINUTE, "session": played["session"]}
        refused(phone.post("/api/internal/progress", json=sneaky, headers=kit), 404)
    finally:
        admin.__exit__(None, None, None)


# 7. Pictures ---------------------------------------------------------------------------------


def test_a_picture_is_fetched_once_and_its_etag_spares_fetching_it_again(app, plex):
    with TestClient(app) as home:
        shared(home)
        first = home.get("/api/internal/art/300?kind=poster&w=300")
        assert first.status_code == 200 and first.content == b"poster 300"
        tag = first.headers["etag"]
        assert first.headers["cache-control"] == "private, max-age=86400"
        assert first.headers["x-content-type-options"] == "nosniff"
        asked = len(plex.requests)
        for said in (tag, f"W/{tag}", f'"other", {tag}', "*"):
            again = home.get("/api/internal/art/300?kind=poster&w=320",
                             headers={"If-None-Match": said})  # fmt: skip
            assert again.status_code == 304 and again.content == b"", said
            assert again.headers["etag"] == tag
        changed = home.get("/api/internal/art/300?kind=poster&w=320",
                           headers={"If-None-Match": '"not it"'})  # fmt: skip
        assert changed.status_code == 200 and changed.content == b"poster 300"
        assert len(plex.requests) == asked  # (kept: Plex isn't asked again)
        # Sizes: rounded up to one of a few; too big is the biggest; nonsense refused.
        assert home.get("/api/internal/art/300?w=1").status_code == 200
        assert home.get("/api/internal/art/300?w=5000").status_code == 200
        for wrong in ("w=0", "w=-5", "w=10001", "w=wide", "kind=banner"):
            refused(home.get(f"/api/internal/art/300?{wrong}"), 400)


def test_a_missing_or_broken_picture_is_404_at_once(app, plex, monkeypatch):
    monkeypatch.setattr(ondemand, "LIBRARY_WAIT_S", 0.5)
    plex.add_movie("302", "No Poster", "/films/x.mkv", 60 * MINUTE, section="2")
    plex.more["302"] = {"thumb": None}  # (Plex has no poster for it)
    plex.no_poster.add("301")
    with TestClient(app) as home:
        shared(home)
        home.get("/api/internal/items/302")
        home.get("/api/internal/items/300")
        asked = len(plex.requests)
        refused(home.get("/api/internal/art/302"), 404, "There's no such picture")
        refused(home.get("/api/internal/art/300?kind=backdrop"), 404)  # (it has none)
        assert len(plex.requests) == asked  # (the library said it has none: not asked)
        refused(home.get("/api/internal/art/301"), 404, "There's no such picture")
        # Plex answering with something that isn't a picture, or nothing: none.
        for said in (httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}),
                     httpx.Response(200, content=b"", headers={"content-type": "image/jpeg"}),
                     httpx.Response(500)):  # fmt: skip
            plex.odd = {"/photo/:/transcode": said, "/library/metadata/201/thumb": said}
            refused(home.get("/api/internal/art/201?kind=thumb&w=160"), 404)
        plex.odd = {}
        # Plex not answering for it: never a hang.
        plex.slow_at = {"/photo/:/transcode"}
        began = time.monotonic()
        refused(home.get("/api/internal/art/201?kind=thumb&w=480"), 503, ondemand.UNREACHABLE)
        assert time.monotonic() - began < 2.0
        plex.slow_at = set()


def test_pictures_are_asked_of_plex_a_few_at_a_time(app, plex):
    from concurrent.futures import ThreadPoolExecutor

    plex.slow_at, plex.pause = {"/photo/:/transcode"}, 0.1
    with TestClient(app) as home:
        shared(home)
        home.get("/api/internal/items/300")
        plex.most_going = 0
        with ThreadPoolExecutor(20) as pool:
            got = list(pool.map(lambda w: home.get(f"/api/internal/art/300?w={w}").status_code,
                                [160, 320, 480, 720, 1280, 1920] * 2 + [161] * 8))  # fmt: skip
        assert set(got) == {200}
        assert plex.most_going <= ondemand.PICTURES_AT_ONCE


def test_pictures_kept_stay_within_their_memory():
    kept = ondemand.PictureCache(most_bytes=1000)
    for n in range(50):
        stored = kept.put((str(n), "poster", 160), (bytes([n]) * 100, "image/jpeg"))
        assert stored[2].startswith('"') and len(stored[2]) == 26
    assert kept._bytes <= 1000 and kept.get(("0", "poster", 160)) is None
    big = kept.put(("big", "poster", 1920), (b"x" * 200, "image/jpeg"))
    assert big[0] == b"x" * 200 and kept.get(("big", "poster", 1920)) is None


# 8. Playing ----------------------------------------------------------------------------------

# A phone that takes copies, and plays H.264 and AAC as they are.
PHONE = {
    "containers": ["mp4", "mkv"],
    "video": [{"codec": "h264", "width": 1920, "height": 1080, "bitDepth": 8}],
    "hdr": [],
    "audio": ["aac"],
    "hls": ["ts"],
}


def test_every_refusal_to_play_says_why_plainly(app, plex, monkeypatch):
    from app import applibrary, converting

    plex.describe("301", container="avi", video="mpeg4", audio="mp3")
    plex.add_movie("302", "No File", "/films/x.mkv", 60 * MINUTE, section="2")
    del plex.episodes["302"]["Media"][0]["Part"][0]["file"]
    del plex.episodes["302"]["Media"][0]["Part"][0]["key"]
    with TestClient(app) as home:
        shared(home)
        # Can't play it as it is, and the app takes no copies.
        old_app = {k: v for k, v in PHONE.items() if k != "hls"}
        refused(play(home, "301", old_app), 422,
                "This device can't play this file as it is (its file type (AVI), its picture's "
                "format (MPEG-4) and its sound's format (MP3)), and this app can't take a copy "
                "made for it. Update the app to play it.")  # fmt: skip
        refused(play(home, "302"), 503, applibrary.NO_FILE)
        refused(play(home, "100"), 400, applibrary.NOT_PLAYABLE)
        refused(play(home, "987654"), 404, ondemand.NOT_SHARED)
        refused(home.post("/api/internal/play", json={"key": "300"}), 400)  # (no device)
        refused(home.post("/api/internal/play", json={"key": "300", "device": TV,
                                                      "startMs": -1}), 400)  # fmt: skip
        # A copy that can't be begun (the disk full, say).
        monkeypatch.setattr(converting, "new_folder", lambda: (_ for _ in ()).throw(OSError(28)))
        refused(play(home, "301", PHONE), 503, applibrary.COPY_FAILED)


def test_a_device_plays_one_program_at_a_time(app, plex, caplog):
    caplog.set_level("INFO")
    with TestClient(app) as home:
        shared(home)
        first = play(home, "300").json()
        report(home, "300", 12 * MINUTE, session=first["session"])
        second = play(home, "201").json()
        assert home.get(first["url"]).status_code == 404  # (the first is ended)
        assert home.get(second["url"]).status_code == 200
        assert "Someone stopped The Movie (1999) at 12:00" in caplog.text
        # The same program again (another sound track, say): the same play.
        caplog.clear()
        again = play(home, "201").json()
        assert home.get(second["url"]).status_code == 404
        assert home.get(again["url"]).status_code == 200 and "stopped" not in caplog.text
        assert len(home.app.state.ctx.plays) == 1
        # Its old one's leave, coming after, changes nothing.
        assert home.post(second["leave"]).status_code == 204
        assert home.get(again["url"]).status_code == 200


def test_two_apps_signed_in_at_one_address_each_play_their_own(app, plex):
    with TestClient(app) as admin:
        shared(admin)
        admin.post("/api/access/users", json=ADA)
        admin.post("/api/access/users", json={**KIT, "role": "user"})
        phone, tablet = TestClient(app), TestClient(app)  # (at one address: "testclient")

        def signed(client: TestClient, who: dict) -> dict[str, str]:
            token = client.post("/api/internal/sign-in", json=who).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        on_phone, on_tablet = signed(phone, ADA), signed(tablet, KIT)
        mine = phone.post("/api/internal/play", json={"key": "300", "device": TV},
                          headers=on_phone).json()  # fmt: skip
        theirs = tablet.post("/api/internal/play", json={"key": "201", "device": TV},
                             headers=on_tablet).json()  # fmt: skip
        assert phone.get(mine["url"]).status_code == tablet.get(theirs["url"]).status_code == 200


def test_a_play_asked_for_while_its_copy_is_being_made(app, plex, monkeypatch):
    from app import applibrary

    monkeypatch.setattr(applibrary, "CONVERTING_MOST", 1)
    plex.describe("301", container="avi", video="mpeg4", audio="mp3")
    with TestClient(app) as home:
        shared(home)
        ctx = home.app.state.ctx
        first = play(home, "301", PHONE).json()
        assert first["method"] == "convert" and ctx.plays.copies() == 1
        # Asked again on the same device (the viewer backed out and chose it
        # again, say): the first is ended, and the device isn't refused for
        # its own copy.
        again = play(home, "301", PHONE)
        assert again.status_code == 200, again.text
        assert home.get(first["url"]).status_code == 404 and ctx.plays.copies() == 1
        # Another device is refused while that one's being made.
        other = TestClient(app, client=("10.0.0.9", 5000))
        refused(play(other, "301", PHONE), 503, applibrary.BUSY_CONVERTING)


def test_a_copy_left_by_an_app_gone_without_leaving(tmp_path, monkeypatch):
    """Its ffmpeg stops when nothing's asked for two minutes (see
    test_converting.py); its pieces are deleted after ten (made again if the
    player comes back); the session itself ends after four hours."""
    from app import converting

    from .test_converting import converted

    copy = converting.Copy("ffmpeg", "file.mkv", converted(3, 18.0), tmp_path / "copy")
    (tmp_path / "copy").mkdir(exist_ok=True)
    for n in range(3):
        copy.ready[n] = tmp_path / "copy" / f"piece-{n}.ts"
        copy.ready[n].write_bytes(b"piece")
    copy.rest(ondemand.COPY_RESTING_S)
    assert len(copy.ready) == 3  # (asked for just now)
    copy.asked -= ondemand.COPY_RESTING_S
    sessions = ondemand.PlaySessions()
    session = sessions.start(user_id=0, user="", sign_in=None,
                             entry=ondemand.Entry("300", "movie", "The Movie"),
                             media=ondemand.Media(container="mkv", video="h264"), path=None,
                             plex="http://plex.test/x", client="10.0.0.2", away=False)  # fmt: skip
    session.copy = copy
    sessions.tidy()
    assert copy.ready == {} and not list((tmp_path / "copy").iterdir())
    assert sessions.find(session.id) is session  # (still there to come back to)
    session.seen -= ondemand.SESSION_IDLE_S + 1
    sessions.tidy()
    assert sessions.find(session.id) is None and copy.stopped


def test_a_movie_in_several_files_plays_its_first(app, plex, caplog):
    caplog.set_level("INFO")
    plex.add_movie("303", "Long Movie", "/films/cd1.mkv", 180 * MINUTE, section="2")
    streams = [{"id": 3031, "streamType": 1, "codec": "h264", "width": 1920, "height": 1080,
                "index": 0}, {"id": 3032, "streamType": 2, "codec": "aac", "default": True,
                "index": 1, "channels": 2}]  # fmt: skip
    plex.more["303"] = {"Media": [{
        "id": 30300, "container": "mkv", "videoCodec": "h264", "duration": 180 * MINUTE,
        "Part": [
            {"key": "/library/parts/303/1/file.mkv", "file": "/films/cd1.mkv",
             "duration": 100 * MINUTE, "size": 1000, "Stream": streams},
            {"key": "/library/parts/303/2/file.mkv", "file": "/films/cd2.mkv",
             "duration": 80 * MINUTE, "size": 1000},
        ],
    }]}  # fmt: skip
    plex.files["303"] = b"part one" * 100
    with TestClient(app) as home:
        shared(home)
        played = play(home, "303").json()
        assert played["method"] == "direct" and played["durationMs"] == 100 * MINUTE
        assert [v["playable"] for v in played["versions"]] == [True]
        assert home.get(played["url"]).content == b"part one" * 100
        said = "Long Movie (2000) is split into 2 files in Plex; StationPlay's apps play only"
        assert f"{said} the first" in caplog.text
        # 90% of what plays (the first file) is watched.
        watched = report(home, "303", 91 * MINUTE, session=played["session"], sequence=1)
        assert watched == {"positionMs": 0, "watched": True}
        copied = play(home, "303", PHONE, night=True).json()
        assert copied["method"] == "repackage" or copied["method"] == "convert"


# 2. Odd data, more ---------------------------------------------------------------------------


def test_episodes_without_titles_numbers_or_seasons(app, plex):
    plex.add_show("130", "Odd Show")
    plex.add_episode("231", "130", 1, 2, "", "/tv/x/2.mkv", 20 * MINUTE)  # (no title)
    plex.add_episode("232", "130", 1, 1, "First", "/tv/x/1.mkv", 20 * MINUTE)
    plex.add_episode("233", "130", 1, None, "No Number", "/tv/x/n.mkv", 20 * MINUTE)
    plex.add_episode("234", "130", None, None, "Loose", "/tv/x/l.mkv", 20 * MINUTE)
    plex.add_episode("235", "130", 0, 1, "Special", "/tv/x/s.mkv", 20 * MINUTE)
    plex.episodes["234"]["parentIndex"] = None  # (as Plex leaves it out)
    with TestClient(app) as home:
        shared(home)
        show = home.get("/api/internal/items/130").json()
        assert [(s["season"], s["title"], s["episodes"]) for s in show["seasons"]] == [
            (1, "Season 1", 3), (None, "Episodes", 1), (0, "Specials", 1)
        ]  # fmt: skip
        listed = home.get("/api/internal/items/130/episodes").json()["episodes"]
        assert [(e["key"], e["season"], e["episode"], e["episodeTitle"]) for e in listed] == [
            ("232", 1, 1, "First"), ("231", 1, 2, None), ("233", 1, None, "No Number"),
            ("234", None, None, "Loose"), ("235", 0, 1, "Special"),
        ]  # fmt: skip
        assert show["next"]["key"] == "232"
        for key in ("232", "231", "233"):
            report(home, key, 20 * MINUTE)
        assert up_next(home, "130") == "234"  # (without a season: after them)
        report(home, "234", 20 * MINUTE)
        assert up_next(home, "130") is None  # (the specials aside)
        refused(home.get("/api/internal/items/130/episodes?season=-1"), 400)


def test_versions_of_different_lengths_finish_by_the_one_playing(app, plex):
    plex.add_version("300", 3840, 2160, video="hevc", bitrate=40_000, bitDepth=10,
                     duration=130 * MINUTE)  # (an extended cut, in 4K)  # fmt: skip
    with TestClient(app) as home:
        shared(home)
        movie = home.get("/api/internal/items/300").json()
        long_cut = movie["versions"][0]["id"]
        played = play(home, "300", version=long_cut).json()
        assert played["version"] == long_cut and played["durationMs"] == 130 * MINUTE
        # 95 minutes in: 90% of the theatrical cut, but not of the one playing.
        kept = report(home, "300", 95 * MINUTE, session=played["session"], sequence=1)
        assert kept == {"positionMs": 95 * MINUTE, "watched": False}
        assert report(home, "300", 118 * MINUTE, session=played["session"], sequence=2) == {
            "positionMs": 0, "watched": True
        }  # fmt: skip


def test_letters_and_totals_follow_what_someone_sees(app, plex):
    titled(plex, "Apple", "Banana", "Cherry", "Date", "Elder")
    with TestClient(app) as home:
        shared(home)
        for key in ("500", "502"):  # (Apple and Cherry)
            report(home, key, watched=True)
        left = home.get("/api/internal/libraries/2?unwatched=1&size=2").json()
        assert left["total"] == 5  # (Another Movie, Banana, Date, Elder, The Movie)
        assert [(x["letter"], x["start"]) for x in left["letters"]] == [
            ("A", 0), ("B", 1), ("D", 2), ("E", 3), ("M", 4)
        ]  # fmt: skip
        page = home.get("/api/internal/libraries/2?unwatched=1&start=2&size=2").json()
        assert [m["title"] for m in page["items"]] == ["Date", "Elder"]
