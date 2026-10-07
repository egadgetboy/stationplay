"""What keeps StationPlay safe when its page is reachable from the internet:
its public port (no Plex addresses, always signing in), only Plex's own
addresses ever asked of Plex, files people upload read only as what they
claim to be, plain names, limits on what a request can send, and a page
that runs only its own script."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import socket
import subprocess
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app import access, bumpers, logos
from app import main as app_main
from app.config import Settings
from app.main import Turns, create_app
from app.plex import PlexClient, PlexError
from app.text import name_from_file

from .fakeplex import FakePlex

SHOW = {"type": "show", "ratingKey": "100"}
PAT = {"name": "Pat", "password": "correct horse"}


def plex() -> FakePlex:
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * 60_000)
    return fp


def settings(tmp_path: Path, **extra) -> Settings:
    return Settings(
        plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data", **extra
    )


@pytest.fixture
def client(tmp_path):
    fp = plex()
    app = create_app(
        settings(tmp_path), PlexClient("http://plex.test", "token", transport=fp.transport())
    )
    with TestClient(app) as c:
        yield c


# Plex is only ever asked for its own addresses ---------------------------------------


async def test_plex_is_never_asked_for_anything_else():
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(404)

    client = PlexClient("http://plex.test", "token", transport=httpx.MockTransport(handler))
    tricks = [
        {"type": "show", "ratingKey": "1/../../:/prefs?x="},
        {"type": "movie", "ratingKey": "../../accounts"},
        {"type": "section", "key": "1/all?type=1&X-Plex-Token=x#"},
    ]
    for source in tricks:
        with pytest.raises(PlexError):
            await client.items_for_source(source)
    with pytest.raises(PlexError):
        await client.poster("1/../../photo?url=http://elsewhere", 96, 144)
    with pytest.raises(PlexError):
        await client.section_items("1%2F..")
    assert asked == []  # (not one request)
    with contextlib.suppress(PlexError):
        await client.items_for_source({"type": "show", "ratingKey": "100"})
    assert asked and all(
        u.startswith("http://plex.test/library/metadata/100/allLeaves") for u in asked
    )


def test_stations_are_made_only_of_plex_keys(client):
    bad = [
        {"type": "show", "ratingKey": "100?x=1"},
        {"type": "movie", "ratingKey": "../1"},
        {"type": "section", "key": "1/all", "sectionType": "show"},
        {"type": "collection", "ratingKey": "900", "title": "X", "library": "1?x", "kind": "movie"},
        {"type": "filter", "kind": "movie", "libraries": ["2/../1"]},
    ]
    for source in bad:
        made = client.post("/api/channels", json={"number": 7, "sources": [source]})
        assert made.status_code == 400, source
    assert client.get("/api/libraries/1%3Fx/items").status_code == 404
    assert client.get("/api/filter/fields?kind=movie&libraries=1%3Fx").json()["fields"] == []


# Text, and how much a request can send ---------------------------------------------


def test_names_are_made_plain(client):
    made = client.post(
        "/api/channels",
        json={"number": 3, "name": "Late\x00Night\n\tTV", "description": "a b\x07", "sources": [SHOW]},
    )  # fmt: skip
    assert made.status_code == 201, made.text
    assert (made.json()["name"], made.json()["description"]) == ("Late Night TV", "a b")
    assert name_from_file("my\x00_logo.png", "x") == "my logo"
    assert name_from_file("intro\r\n.mov", "x") == "intro"
    assert name_from_file(".png", "My logo") == "My logo"


def test_a_request_cant_send_more_than_stationplay_takes(client):
    huge = {"number": 4, "sources": [SHOW], "name": "x" * (access.BODY_MAX + 10)}
    assert client.post("/api/channels", json=huge).status_code == 413

    async def chunked():
        async def body():
            for _ in range(access.BODY_MAX // 65536 + 2):
                yield b"x" * 65536

        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://sp") as c:
            return await c.post("/api/channels", content=body())

    # (Without saying how much is coming, too.)
    assert client.portal.call(chunked).status_code == 413


def test_the_page_runs_only_its_own_script(client):
    page = client.get("/")
    policy = page.headers["content-security-policy"]
    nonce = policy.split("'nonce-")[1].split("'")[0]
    assert f'<script nonce="{nonce}">' in page.text and page.text.count("<script") == 1
    assert "frame-ancestors 'none'" in policy and "object-src 'none'" in policy
    assert client.get("/").headers["content-security-policy"] != policy  # a new one each time
    for path in ("/", "/api/channels"):
        got = client.get(path).headers
        assert got["x-frame-options"] == "DENY" and got["x-content-type-options"] == "nosniff"


async def test_previews_take_turns_and_only_a_few_wait():
    turns = Turns("busy", most_waiting=1)
    held = asyncio.Event()
    release = asyncio.Event()

    async def first():
        async with turns.turn():
            held.set()
            await release.wait()

    async def waiting():
        async with turns.turn():
            return "done"

    running = asyncio.create_task(first())
    await held.wait()
    second = asyncio.create_task(waiting())
    await asyncio.sleep(0)
    with pytest.raises(Exception, match="busy"):
        async with turns.turn():
            pass
    release.set()
    assert await second == "done"
    await running
    # Several at once, and none waiting: the rest are told straight away.
    two = Turns("full", at_once=2)
    async with two.turn(), two.turn():
        with pytest.raises(Exception, match="full"):
            async with two.turn():
                pass


# Uploads ------------------------------------------------------------------------------


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


@needs_ffmpeg
def test_an_uploaded_file_is_read_only_as_what_it_claims_to_be(tmp_path):
    folder = tmp_path / "bumpers"
    folder.mkdir()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x48:r=25", "-t", "2",
         "-c:v", "libx264", "-preset", "ultrafast", str(folder / "someone-elses.mp4")],
        check=True,
    )  # fmt: skip
    # A "video" that's a list of other files to play (ffmpeg would follow it).
    trick = folder / ".upload-0123456789"
    trick.write_text("ffconcat version 1.0\nfile someone-elses.mp4\n")
    png = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=40x30", "-frames:v", "1",
         "-f", "image2", "-c:v", "png", "pipe:1"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip

    async def check() -> None:
        library = bumpers.BumperLibrary(folder)
        with pytest.raises(bumpers.BumperError, match="can't play that file"):
            await library.add(trick, "Mine", Settings())
        # A "picture" that's anything but one.
        for not_a_picture in (
            b"ffconcat version 1.0\nfile x.png\n",
            b"<svg xmlns='x'/>",
            b"\0" * 64,
        ):
            with pytest.raises(logos.LogoError):
                await logos.to_logo_png(not_a_picture, "ffmpeg")
        assert (await logos.to_logo_png(png, "ffmpeg")).startswith(b"\x89PNG")

    asyncio.run(check())


def test_uploads_are_limited(client, monkeypatch):
    monkeypatch.setattr(logos, "MOST_UPLOADED", 0)
    assert client.post("/api/logos?name=x", content=b"\x89PNG....").status_code == 400
    monkeypatch.setattr(app_main, "DISK_SPARE", 1 << 60)  # (a disk that's always full)
    full = client.post("/api/bumpers?name=x", content=b"0" * 100)
    assert full.status_code == 507


# The public port ------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def both_ports(tmp_path):
    """StationPlay listening on its home-network port and its public one:
    (the home network's address, the internet's)."""
    lan, public = (socket.create_server(("127.0.0.1", 0)) for _ in range(2))
    ports = lan.getsockname()[1], public.getsockname()[1]
    fp = plex()
    app = create_app(
        settings(tmp_path, port=ports[0], public_port=ports[1]),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", proxy_headers=False))
    task = asyncio.create_task(server.serve(sockets=[lan, public]))
    while not server.started:
        await asyncio.sleep(0.02)
    try:
        yield tuple(f"http://127.0.0.1:{port}" for port in ports)
    finally:
        server.should_exit = True
        await task


async def test_from_the_internet_theres_nothing_until_signing_in_is_set_up(tmp_path):
    async with both_ports(tmp_path) as (home, internet):
        async with httpx.AsyncClient(base_url=internet) as outside:
            assert (await outside.get("/")).status_code == 200
            me = (await outside.get("/api/access/me")).json()
            assert me["required"] and me["user"] is None and "home network" in me["notSetUp"]
            for path in ("/api/channels", "/api/status", "/logos/anything.png", "/api/logs"):
                assert (await outside.get(path)).status_code == 403, path
            # Nobody from the internet makes themselves the first Admin.
            first = await outside.post("/api/access/users", json=PAT)
            assert first.status_code == 403
            # Plex's addresses aren't there at all.
            for path in ("/discover.json", "/lineup.json", "/xmltv.xml", "/stations.m3u",
                         "/stream/1", "/auto/v1", "/art/100", "/hls/1/index.m3u8"):  # fmt: skip
                assert (await outside.get(path)).status_code == 404, path
        async with httpx.AsyncClient(base_url=home) as inside:
            # At home it's open, as it was, and Plex's addresses are there.
            assert (await inside.get("/api/access/me")).json()["required"] is False
            assert (await inside.get("/discover.json")).status_code == 200
            assert (await inside.post("/api/access/users", json=PAT)).status_code == 201


async def test_signing_in_from_the_internet(tmp_path, monkeypatch):
    monkeypatch.setattr(access, "PUBLIC_TRIES", 3)
    async with both_ports(tmp_path) as (home, internet):
        async with httpx.AsyncClient(base_url=home) as inside:
            await inside.post("/api/access/users", json=PAT)
            assert (await inside.get("/logos/x.png")).status_code == 404  # (open at home)

        def visitor(address: str) -> httpx.AsyncClient:
            # As the tunnel passes it on: who's visiting.
            return httpx.AsyncClient(base_url=internet, headers={"CF-Connecting-IP": address})

        async with visitor("203.0.113.5") as pats:
            assert (await pats.get("/api/channels")).status_code == 401
            assert (await pats.get("/logos/x.png")).status_code == 401
            signed = await pats.post("/api/access/sign-in", json=PAT)
            assert signed.status_code == 200
            assert (await pats.get("/api/channels")).status_code == 200
            assert (await pats.get("/xmltv.xml")).status_code == 404  # signed in or not
            # Plex's address can't be told from here: Add to Plex says where yours goes.
            lan_port = home.rsplit(":", 1)[1]
            tuner = (await pats.get("/api/status")).json()["tunerUrl"]
            assert tuner == f"http://<your NAS>:{lan_port}"
            await pats.post("/api/access/sign-out")
            # Wrong passwords: by each visitor's address, and from the internet as a whole.
            for n in range(3):
                async with visitor(f"198.51.100.{n}") as guesser:
                    wrong = await guesser.post(
                        "/api/access/sign-in", json={**PAT, "password": "nope nope"}
                    )
                    assert wrong.status_code == 401
            async with visitor("198.51.100.99") as someone_else:
                busy = await someone_else.post("/api/access/sign-in", json=PAT)
                assert busy.status_code == 429 and "internet" in busy.json()["detail"]
            # But strangers' wrong passwords don't keep Pat out on a browser he's used.
            assert (await pats.post("/api/access/sign-in", json=PAT)).status_code == 200
        async with httpx.AsyncClient(base_url=home) as inside:
            assert (await inside.post("/api/access/sign-in", json=PAT)).status_code == 200
            log = (await inside.get("/api/logs?access_log=true")).json()["text"]
    assert "Pat (Admin) signed in from 203.0.113.5 (over the internet)" in log
    assert "from 198.51.100.0 (over the internet)" in log


def test_a_user_sees_only_what_the_stations_tab_needs(client):
    client.post("/api/access/users", json=PAT)
    client.post("/api/access/users", json={"name": "Sam", "password": "battery staple"})
    assert "mediaAccess" in client.get("/api/status").json()  # an Admin sees it all
    sam = TestClient(client.app)
    sam.post("/api/access/sign-in", json={"name": "Sam", "password": "battery staple"})
    status = sam.get("/api/status").json()
    assert set(status) == {"version", "plex", "streams", "tuners", "fillers"}
    assert set(status["fillers"]) == {"commercials", "trailers"}


async def test_cookies_are_only_sent_over_https_when_its_used(tmp_path):
    async with both_ports(tmp_path) as (home, internet):
        async with httpx.AsyncClient(base_url=home) as inside:
            await inside.post("/api/access/users", json=PAT)
        tunnel = {"CF-Connecting-IP": "203.0.113.5", "CF-Visitor": '{"scheme":"https"}'}
        async with httpx.AsyncClient(base_url=internet, headers=tunnel) as outside:
            signed = await outside.post("/api/access/sign-in", json=PAT)
        cookies = signed.headers.get_list("set-cookie")
        assert len(cookies) == 2  # signed in, and the browser remembered
        for cookie in cookies:
            assert all(x in cookie for x in ("HttpOnly", "SameSite=lax", "Secure")), cookie


def test_plex_is_asked_only_for_what_a_library_can_be_filtered_on(tmp_path):
    fp = plex()
    fp.add_section("2", "Movies", "movie")
    fp.add_movie("500", "Jaws", "/m/j.mkv", 90 * 60_000, section="2", genres=["Thriller"])
    app = create_app(
        settings(tmp_path), PlexClient("http://plex.test", "token", transport=fp.transport())
    )
    with TestClient(app) as client:
        # Plex's "refresh" (a library scan) is an address too.
        client.get("/api/filter/search?kind=movie&libraries=2&field=refresh&q=ab")
        tags = {"kind": "movie", "libraries": ["2"], "tags": {"refresh": ["x"]}}
        client.post("/api/filter/preview", json=tags)
        assert not [r for r in fp.requests if r.endswith("/refresh")]
        # What a library can be filtered on still is.
        assert client.get("/api/filter/search?kind=movie&libraries=2&field=genre&q=thr").json() == [
            "Thriller"
        ]
        # (Without the folders Plex keeps libraries in.)
        assert all(
            set(lib) == {"key", "title", "type"} for lib in client.get("/api/libraries").json()
        )


async def test_plex_errors_dont_say_where_plex_is():
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    plex_client = PlexClient(
        "http://192.0.2.1:32400", "token", transport=httpx.MockTransport(broken)
    )
    with pytest.raises(PlexError) as caught:
        await plex_client.identity()
    assert "192.0.2.1" not in str(caught.value) and "Plex" in str(caught.value)


def test_a_user_may_do_only_what_users_do(client):
    client.post("/api/access/users", json=PAT)
    client.post("/api/access/users", json={"name": "Sam", "password": "battery staple"})
    sam = TestClient(client.app)
    sam.post("/api/access/sign-in", json={"name": "Sam", "password": "battery staple"})
    for method, path in (("POST", "/api/fillers/refresh"), ("PUT", "/api/scan"),
                         ("GET", "/api/broken/download"), ("POST", "/api/backups"),
                         ("DELETE", "/api/bumpers/bumper-0123456789"), ("OPTIONS", "/api/channels")):  # fmt: skip
        assert sam.request(method, path).status_code == 403, path
    for path in ("/api/channels", "/api/libraries", "/api/stats", "/api/logos", "/api/bumpers"):
        assert sam.get(path).status_code == 200, path


def test_what_a_station_is_made_of_is_limited(client):
    def make(sources):
        return client.post("/api/channels", json={"number": 8, "sources": sources})

    assert make([SHOW, SHOW]).json()["detail"].startswith("The same show")
    libraries = [{"type": "section", "key": str(n), "sectionType": "show"} for n in range(51)]
    assert "50 libraries" in make(libraries).json()["detail"]
    twice = {"type": "filter", "kind": "movie", "libraries": ["2", "2"]}
    assert make([twice]).status_code == 400


async def test_asking_plex_a_lot_at_once_waits(monkeypatch):
    from starlette.requests import Request

    at_once = app_main.AtOnce(2, "busy")
    someone = Request({"type": "http", "client": ("192.0.2.9", 1), "state": {}, "headers": []})
    first, second = at_once(someone), at_once(someone)
    await first.__anext__()
    await second.__anext__()
    with pytest.raises(Exception, match="busy"):
        await at_once(someone).__anext__()
    other = Request({"type": "http", "client": ("192.0.2.10", 1), "state": {}, "headers": []})
    await at_once(other).__anext__()  # (someone else isn't held up)
    await first.aclose()
    await at_once(someone).__anext__()  # room again


def test_a_backup_is_restored_only_as_stationplay_made_it(client, tmp_path):
    import sqlite3
    import zipfile

    from app import backups

    ctx = client.app.state.ctx
    ctx.restart = lambda: None  # a test mustn't stop itself
    client.post("/api/channels", json={"number": 2, "name": "Ok", "sources": [SHOW]})
    made = backups.make_backup(ctx)

    def changed(db_change=None, extra: dict[str, bytes] | None = None) -> bytes:
        with zipfile.ZipFile(made) as z:
            files = {n: z.read(n) for n in z.namelist()}
        db = tmp_path / "x.db"
        db.write_bytes(files[backups.DB_NAME])
        if db_change:
            conn = sqlite3.connect(db)
            conn.execute(db_change)
            conn.commit()
            conn.close()
        files[backups.DB_NAME] = db.read_bytes()
        files.update(extra or {})
        out = tmp_path / "x.zip"
        with zipfile.ZipFile(out, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
        return out.read_bytes()

    trigger = (
        "CREATE TRIGGER sneaky AFTER INSERT ON sessions BEGIN UPDATE users SET role = 'admin'; END"
    )
    assert client.post("/api/restore", content=changed(trigger)).status_code == 400
    not_a_logo = {"logos/upload-0123456789.png": b"ffconcat version 1.0\nfile x.png\n"}
    refused = client.post("/api/restore", content=changed(extra=not_a_logo))
    assert refused.status_code == 400 and "isn't a picture" in refused.json()["detail"]
    sneaky_source = 'UPDATE channels SET sources = \'[{"type": "show", "ratingKey": "1?x"}]\''
    assert client.post("/api/restore", content=changed(sneaky_source)).status_code == 400
    # A name from before names were kept plain is made plain.
    old_name = "UPDATE channels SET name = 'Late' || char(10) || 'Night'"
    assert client.post("/api/restore", content=changed(old_name)).status_code == 200
    staged = sqlite3.connect(ctx.settings.data_dir / backups.RESTORE_DIR / backups.DB_NAME)
    assert staged.execute("SELECT name FROM channels").fetchone()[0] == "Late Night"
    staged.close()
