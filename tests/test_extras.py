"""Station logos and the Logs tab."""

from __future__ import annotations

import logging
import random

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.logos import COLLECTION_LOGO, LogoLibrary
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .helpers import page_code

MIN = 60_000


@pytest.fixture
def client(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * MIN)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    with TestClient(app) as c:
        yield c


def station(client, number, **extra):
    body = {"number": number, "sources": [{"type": "show", "ratingKey": "100"}], **extra}
    resp = client.post("/api/channels", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_the_library_has_nearly_1000_logos_that_all_exist():
    library = LogoLibrary()
    catalog = library.catalog()
    assert len(catalog) >= 980
    assert len({logo["id"] for logo in catalog}) == len(catalog)
    for logo in catalog:
        path = library.path(logo["id"])
        assert path is not None and path.stat().st_size > 1000
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert logo["name"] and isinstance(logo["tags"], list)
    categories = {logo["category"] for logo in catalog}
    assert {
        "Broadcast networks",
        "Cable networks",
        "Movie channels",
        "Classic TV",
        "TV shows",
        "Over-the-air classics",
        "Decades",
        "Cartoons & anime",
        "Teens",
        "Kids & family",
        "Genres",
        "Holidays & seasons",
        "On the air",
        "Numbers",
        "Letters",
        "Retro numbers",
        "Retro letters",
    } <= categories
    # Three designs for each genre Plex's agents use.
    genres = [logo for logo in catalog if logo["category"] == "Genres"]
    assert len(genres) == 37 * 3
    for n in range(1, 51):
        assert library.exists(f"number-{n}-modern") and library.exists(f"number-{n}-retro")


def test_every_logo_from_before_1_7_still_shows_a_logo():
    from pathlib import Path

    library = LogoLibrary()
    old_ids = list(library.replaced) + [p.stem for p in Path(library.directory).glob("*.png")]
    for old in library.replaced:
        new = library.resolve(old)
        assert new != old and library.exists(new), old
        assert library.path(old) == library.path(new)  # an old address still works
    assert len(library.replaced) > 150 and old_ids


def test_new_stations_1_to_50_get_their_number_and_others_different_pictures(client):
    assert [station(client, n)["logo"] for n in (1, 7, 50)] == [
        "number-1-modern",
        "number-7-modern",
        "number-50-modern",
    ]
    logos = [station(client, n)["logo"] for n in range(60, 65)]
    library = LogoLibrary()
    assert all(library.exists(logo) for logo in logos)
    assert len(set(logos)) == 5  # no two stations share one while others are free
    categories = {logo["id"]: logo["category"] for logo in library.catalog()}
    assert not any(
        categories[logo] in ("Letters", "Numbers", "Retro letters", "Retro numbers")
        for logo in logos
    )


def test_picking_keeping_and_clearing_a_logo(client):
    chosen = station(client, 1, logo="christmas-wreath")
    assert chosen["logo"] == "christmas-wreath"
    body = {"number": 1, "sources": chosen["sources"]}
    kept = client.put(f"/api/channels/{chosen['id']}", json={**body, "name": "Xmas"}).json()
    assert kept["logo"] == "christmas-wreath"  # not mentioned: unchanged
    # A logo's name from before 1.7 still works: it's the new one that replaced it.
    old = client.put(f"/api/channels/{chosen['id']}", json={**body, "logo": "christmas"}).json()
    assert old["logo"] == LogoLibrary().resolve("christmas") != "christmas"
    cleared = client.put(f"/api/channels/{chosen['id']}", json={**body, "logo": ""}).json()
    assert cleared["logo"] == ""  # the station's number instead
    bad = client.put(f"/api/channels/{chosen['id']}", json={**body, "logo": "nbc"})
    assert bad.status_code == 400


def test_plex_gets_the_logo_and_notices_when_it_changes(client):
    s = station(client, 4, logo="halloween")
    icon = client.get("/channel-icon/4.png")
    assert icon.status_code == 200
    assert icon.content == LogoLibrary().path("halloween").read_bytes()
    guide = client.get("/guide.xml").text
    v = LogoLibrary().version
    assert f"/channel-icon/4.png?v={v}-halloween" in guide
    assert f"/channel-icon/4.png?v={v}-halloween" in client.get("/stations.m3u").text
    client.put(
        f"/api/channels/{s['id']}", json={"number": 4, "sources": s["sources"], "logo": "winter"}
    )
    assert f"/channel-icon/4.png?v={v}-winter" in client.get("/guide.xml").text
    assert client.get("/logos/winter.png").status_code == 200
    assert client.get("/logos/../main.py").status_code == 404
    assert client.get("/logos/nope.png").status_code == 404
    assert len(client.get("/api/logos").json()) >= 500
    # The page asks for logos with the library's version, so it never shows old ones.
    page = page_code(client)
    assert "?v=${LOGO_V}" in page and f"const LOGO_V = '{v}'" in page


def test_pick_prefers_logos_no_station_has():
    library = LogoLibrary()
    lettering = {"Letters", "Numbers", "Retro letters", "Retro numbers"}
    everything = {
        logo["id"]
        for logo in library.catalog()
        if logo["category"] not in lettering and logo["id"] != COLLECTION_LOGO
    }
    free = sorted(everything)[:1]
    assert library.pick(everything - set(free), random.Random(1)) == free[0]
    assert library.pick(everything, random.Random(1)) in everything  # all taken: any
    # The Collection logo is for stations made from Plex collections only.
    rng = random.Random(2)
    assert library.exists(COLLECTION_LOGO)
    assert COLLECTION_LOGO not in {library.pick(set(), rng) for _ in range(3000)}


def test_logos_that_went_in_1_8_show_another():
    """The spin-off channels went (a station using one gets its parent's
    logo), and so did Hanukkah (winter instead)."""
    library = LogoLibrary()
    for old, new in (
        ("night-reel-action", "night-reel"),
        ("gold-seal-kids-and-family", "gold-seal"),
        ("vertical-hold-plus", "vertical-hold"),
        ("hanukkah", "winter"),
    ):
        assert library.resolve(old) == new and library.exists(new)
        assert library.path(old) == library.path(new)


def test_the_logs_tab_shows_recent_entries_and_filters_them(client):
    log = logging.getLogger("app.broadcaster")
    log.warning("Station 3: a file stalled; resuming it")
    log.error("Station 3 is OFF THE AIR: example")
    everything = client.get("/api/logs").json()
    messages = [e["message"] for e in everything["entries"]]
    assert "Station 3: a file stalled; resuming it" in messages
    only_errors = client.get("/api/logs?levels=ERROR").json()["entries"]
    assert {e["level"] for e in only_errors} == {"ERROR"}
    both = client.get("/api/logs?levels=WARNING,ERROR").json()["entries"]
    assert {e["level"] for e in both} == {"WARNING", "ERROR"}
    text = client.get("/api/logs?levels=ERROR").json()["text"]
    assert "ERROR   app.broadcaster: Station 3 is OFF THE AIR: example" in text


def test_logs_never_show_a_plex_token(client):
    logging.getLogger("app.sources").warning(
        "Couldn't open http://plex:32400/library/parts/1/file.mkv?X-Plex-Token=SECRET123"
    )
    text = client.get("/api/logs").json()["text"]
    assert "SECRET123" not in text and "X-Plex-Token=<hidden>" in text


def test_stations_from_before_logos_get_one_once(tmp_path):
    from app.db import Database

    data = tmp_path / "data"
    db = Database(data / "stationplay.db")
    old = [db.create_channel(n, f"S{n}", [], order_mode="rotate") for n in (1, 2)]
    db.close()
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=data)
    app = create_app(
        settings, PlexClient("http://plex.test", "token", transport=FakePlex().transport())
    )
    with TestClient(app) as c:
        logos = [ch["logo"] for ch in c.get("/api/channels").json()]
        assert all(logos) and len(set(logos)) == 2
        # You choose "Station number" for one of them.
        c.app.state.ctx.db.update_channel(old[0].id, logo="")
    app = create_app(
        settings, PlexClient("http://plex.test", "token", transport=FakePlex().transport())
    )
    with TestClient(app) as c:
        assert c.get("/api/channels").json()[0]["logo"] == ""  # the choice sticks


def test_stations_with_a_logo_from_before_1_7_get_its_replacement(tmp_path):
    """After the update (or restoring an older backup), a station whose logo
    was in the old library shows the new logo that replaced it."""
    from app.db import Database

    data = tmp_path / "data"
    db = Database(data / "stationplay.db")
    db.set_meta("logos_given", "1")
    kept = db.create_channel(
        1, "Kept", [], order_mode="rotate", logo="halloween"
    )  # the name lives on
    moved = db.create_channel(2, "Moved", [], order_mode="rotate", logo="tv")
    number = db.create_channel(3, "Number", [], order_mode="rotate", logo="")
    db.close()
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=data)
    app = create_app(
        settings, PlexClient("http://plex.test", "token", transport=FakePlex().transport())
    )
    with TestClient(app) as c:
        logos = {ch["id"]: ch["logo"] for ch in c.get("/api/channels").json()}
        library = c.app.state.ctx.logos
        assert logos[kept.id] == "halloween"
        assert logos[moved.id] == library.resolve("tv") != "tv" and library.exists(logos[moved.id])
        assert logos[number.id] == ""  # the station number stays the station number


# Your own logos ----------------------------------------------------------------


def picture(fmt: str = "png", size: str = "800x300") -> bytes:
    import subprocess

    return subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=red:s={size}", "-frames:v", "1",
         "-f", "image2", "-c:v", {"png": "png", "jpeg": "mjpeg"}[fmt], "pipe:1"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip


def test_you_can_add_use_and_remove_your_own_logos(client):
    added = client.post("/api/logos?name=Our%20Movie%20Night.png", content=picture("jpeg"))
    assert added.status_code == 201, added.text
    mine = added.json()
    assert mine["name"] == "Our Movie Night" and mine["category"] == "Your logos"
    assert mine["id"].startswith("upload-")
    catalog = client.get("/api/logos").json()
    assert catalog[0] == mine  # listed first
    png = client.get(f"/logos/{mine['id']}.png")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    import subprocess

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height,pix_fmt", "-of", "csv=p=0", "-"],
        input=png.content, capture_output=True, text=False, check=True,
    ).stdout.decode()  # fmt: skip
    assert probe.strip() == "512,512,rgba"  # the library's size, clear background

    # A station can use it, and Plex gets it.
    s = station(client, 6, logo=mine["id"])
    assert s["logo"] == mine["id"]
    assert client.get("/channel-icon/6.png").content == png.content
    assert (
        f"/channel-icon/6.png?v={LogoLibrary().version}-{mine['id']}"
        in client.get("/guide.xml").text
    )
    # It can't be deleted while a station uses it.
    busy = client.delete(f"/api/logos/{mine['id']}")
    assert busy.status_code == 409 and "station 6" in busy.json()["detail"]
    client.put(
        f"/api/channels/{s['id']}", json={"number": 6, "sources": s["sources"], "logo": "tv"}
    )
    assert client.delete(f"/api/logos/{mine['id']}").status_code == 204
    assert client.get(f"/logos/{mine['id']}.png").status_code == 404
    assert all(logo["id"] != mine["id"] for logo in client.get("/api/logos").json())
    assert client.delete(f"/api/logos/{mine['id']}").status_code == 404
    assert client.delete("/api/logos/christmas").status_code == 404  # the library's stay


def test_uploads_that_arent_usable_pictures_are_refused(client):
    bad = client.post("/api/logos?name=x", content=b"this is not a picture")
    assert bad.status_code == 400 and "can't read that picture" in bad.json()["detail"]
    assert client.post("/api/logos?name=x", content=b"").status_code == 400
    from app import logos

    big = client.post("/api/logos?name=x", content=b"\0" * (logos.MAX_UPLOAD_BYTES + 1))
    assert big.status_code == 413
    assert all(logo["category"] != "Your logos" for logo in client.get("/api/logos").json())


def test_your_logos_are_kept_and_never_handed_out_at_random(tmp_path):
    data = tmp_path / "data"

    def make():
        fp = FakePlex()
        fp.add_show("100", "Show")
        fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * MIN)
        return create_app(
            Settings(plex_url="http://plex.test", plex_token="token", data_dir=data),
            PlexClient("http://plex.test", "token", transport=fp.transport()),
        )

    with TestClient(make()) as c:
        mine = c.post("/api/logos?name=Ours", content=picture()).json()
        library = c.app.state.ctx.logos
        taken = {logo["id"] for logo in library.catalog() if logo["id"] != mine["id"]}
        picks = {library.pick(taken, random.Random(n)) for n in range(50)}
        assert mine["id"] not in picks
    with TestClient(make()) as c:  # after a restart
        assert c.get("/api/logos").json()[0]["id"] == mine["id"]
        assert c.get(f"/logos/{mine['id']}.png").status_code == 200


def test_the_page_can_show_the_version(client):
    import re
    import tomllib
    from pathlib import Path

    from app import __version__

    assert client.get("/api/status").json()["version"] == __version__
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert project["project"]["version"] == __version__  # one version everywhere
    # (The image TrueNAS and Docker Compose build, too.)
    for name in ("stationplay.yaml", "docker-compose.yml"):
        images = re.findall(r"^\s*image: stationplay:(\S+)$", (root / name).read_text(), re.M)
        assert images == [__version__], name


def test_the_page_starts_in_the_appearance_this_browser_chose(client):
    # Automatic (no cookie): the device's own setting.
    assert '<html lang="en">' in client.get("/").text
    client.cookies.set("stationplay_theme", "dark")
    assert '<html lang="en" data-theme="dark">' in client.get("/").text
    client.cookies.set("stationplay_theme", "light")
    assert '<html lang="en" data-theme="light">' in client.get("/").text
    # Anything else is Automatic, and never put in the page.
    client.cookies.set("stationplay_theme", '"><script>alert(1)</script>')
    page = client.get("/").text
    assert '<html lang="en">' in page and "alert(1)" not in page
    client.cookies.clear()


def test_station_names_cant_break_the_playlist(client):
    s = station(client, 7, name='The "Best" TV\nEver')
    assert s["name"] == 'The "Best" TV Ever'  # (on one line: see text.py)
    m3u = client.get("/stations.m3u").text
    assert "tvg-name=\"The 'Best' TV Ever\"" in m3u and ",The 'Best' TV Ever\n" in m3u


def test_cards_count_broken_programs_and_warn_about_one_big_show(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Big")
    fp.add_show("300", "Small")
    for n in range(1, 8):
        fp.add_episode(f"1{n:02d}", "100", 1, n, f"Big {n}", f"/x/b{n}.mkv", 22 * MIN)
    fp.add_episode("301", "300", 1, 1, "Small 1", "/x/s1.mkv", 22 * MIN)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    with TestClient(app) as c:
        sources = [{"type": "show", "ratingKey": "100"}, {"type": "show", "ratingKey": "300"}]
        made = c.post(
            "/api/channels", json={"number": 1, "orderMode": "shuffle", "sources": sources}
        ).json()
        assert made["mostlyOneShow"] is True and made["brokenCount"] == 0
        items = c.app.state.ctx.db.latest_items(made["id"])
        for item in items[:2]:
            c.app.state.ctx.broken.record(item, "test", 1)
        card = c.get("/api/channels").json()[0]
        assert card["brokenCount"] == 2
        rotate = c.post(
            "/api/channels", json={"number": 2, "orderMode": "rotate", "sources": sources}
        ).json()
        assert rotate["mostlyOneShow"] is False  # only shuffle can't spread it out


def test_a_logo_whose_picture_went_missing_can_still_be_deleted(client, tmp_path):
    mine = client.post("/api/logos?name=Gone", content=picture()).json()
    ctx = client.app.state.ctx
    (ctx.settings.data_dir / "logos" / f"{mine['id']}.png").unlink()
    assert client.delete(f"/api/logos/{mine['id']}").status_code == 204
    assert all(logo["id"] != mine["id"] for logo in client.get("/api/logos").json())


def test_a_logo_deleted_while_a_station_is_saved_isnt_saved_with_it(client, monkeypatch):
    mine = client.post("/api/logos?name=Ours", content=picture()).json()
    s = station(client, 8)
    ctx = client.app.state.ctx
    real = ctx.updater.gather

    async def slow_plex(*args, **kwargs):
        ctx.logos.remove(mine["id"])  # deleted from another tab meanwhile
        return await real(*args, **kwargs)

    monkeypatch.setattr(ctx.updater, "gather", slow_plex)
    resp = client.put(
        f"/api/channels/{s['id']}",
        json={"number": 8, "sources": s["sources"], "logo": mine["id"], "skipIntros": True},
    )
    assert resp.status_code == 400
    assert client.get("/api/channels").json()[0]["logo"] == s["logo"]


def test_a_hung_media_share_ties_up_one_check_at_most(client, monkeypatch):
    import threading

    from app import main

    release = threading.Event()
    started = []
    real_isdir = main.os.path.isdir

    def hung(path):
        if path == client.app.state.ctx.settings.media_dir:
            started.append(1)
            release.wait(30)
            return True
        return real_isdir(path)

    monkeypatch.setattr(main.os.path, "isdir", hung)
    try:
        for _ in range(3):
            assert client.get("/api/status").json()["mediaAccess"]["mediaDirPresent"] is False
        assert len(started) == 1
    finally:
        release.set()


def test_corner_logo_size_and_transparency(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "One", "/tv/1.mkv", 22 * 60_000)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    body = {"number": 4, "orderMode": "rotate", "sources": [{"type": "show", "ratingKey": "100"}]}
    with TestClient(app) as client:
        made = client.post("/api/channels", json={**body, "watermark": "logo"}).json()
        # Unless chosen, large and a little see-through.
        assert (made["watermarkSize"], made["watermarkTransparency"]) == ("large", "medium")
        cid = made["id"]
        edited = client.put(
            f"/api/channels/{cid}",
            json={**body, "watermarkSize": "small", "watermarkTransparency": "high"},
        ).json()
        assert (edited["watermark"], edited["watermarkSize"], edited["watermarkTransparency"]) == (
            "logo",
            "small",
            "high",
        )
        # Not a change to what airs: the schedule stays as it was.
        assert edited["lastChange"]["reason"] == "created"
        kept = client.put(f"/api/channels/{cid}", json=body).json()  # left out: unchanged
        assert (kept["watermarkSize"], kept["watermarkTransparency"]) == ("small", "high")
        for bad in (
            {"watermarkSize": "huge"},
            {"watermarkTransparency": "none"},
            {"watermarkPosition": "middle"},
        ):
            assert client.put(f"/api/channels/{cid}", json={**body, **bad}).status_code == 400
        # Which corner: bottom left (where the Up Next Banner takes its place) unless chosen.
        assert kept["watermarkPosition"] == "bottom-left"
        moved = client.put(
            f"/api/channels/{cid}", json={**body, "watermarkPosition": "top-left"}
        ).json()
        assert moved["watermarkPosition"] == "top-left" and moved["watermarkSize"] == "small"
        assert (
            client.put(f"/api/channels/{cid}", json=body).json()["watermarkPosition"] == "top-left"
        )


def test_corner_logo_just_at_the_start(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "One", "/tv/1.mkv", 22 * 60_000)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    body = {"number": 4, "orderMode": "rotate", "sources": [{"type": "show", "ratingKey": "100"}]}
    with TestClient(app) as client:
        made = client.post("/api/channels", json={**body, "watermark": "name"}).json()
        assert made["watermarkTiming"] == "always"  # all the time unless chosen
        cid = made["id"]
        timed = client.put(f"/api/channels/{cid}", json={**body, "watermarkTiming": "start"}).json()
        assert timed["watermarkTiming"] == "start"
        assert timed["lastChange"]["reason"] == "created"  # not a change to what airs
        assert client.put(f"/api/channels/{cid}", json=body).json()["watermarkTiming"] == "start"
        bad = client.put(f"/api/channels/{cid}", json={**body, "watermarkTiming": "sometimes"})
        assert bad.status_code == 400
