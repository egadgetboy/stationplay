"""A show's or movie's own logo from Plex (its "clear logo") as a station's:
fetched, trimmed to its own shape, added to your logos, and drawn as large
as the library's square logos look at each size."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import backups
from app import ffmpeg as ff
from app.config import Settings
from app.logos import (
    FILLED,
    LOGO_DIR,
    MAX_STRETCH,
    SIZE,
    UNREADABLE,
    WIDEST,
    LogoError,
    to_trimmed_logo_png,
)
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
MIN = 60_000
LOGO_URL = "/library/metadata/100/clearLogo/1730116804"


def drawn(size: str, block: str, at: tuple[int, int]) -> bytes:
    """A PNG of `size` that's see-through but for a white block of `block`
    at `at` (as a clear logo is: lettering on nothing)."""
    x, y = at
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=black@0:s={size},format=rgba",
         "-f", "lavfi", "-i", f"color=c=white:s={block},format=rgba",
         "-filter_complex", f"[0][1]overlay={x}:{y}:format=auto,format=rgba",
         "-frames:v", "1", "-f", "image2", "-c:v", "png", "pipe:1"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip


def png_size(data: bytes) -> tuple[int, int]:
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def visible_box(data: bytes) -> tuple[int, int, int, int]:
    """(w, h, x, y) of what's drawn in a PNG."""
    said = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", "pipe:0", "-vf",
         "format=rgba,alphaextract,bbox=min_val=10", "-f", "null", "-"],
        input=data, capture_output=True, check=True,
    ).stderr.decode()  # fmt: skip
    crop = said.rsplit("crop=", 1)[1].split()[0]
    w, h, x, y = (int(v) for v in crop.split(":"))
    return w, h, x, y


# Its shape on screen ---------------------------------------------------------


def write_png(path: Path, width: int, height: int) -> str:
    """A PNG's header, which is all logo_box reads."""
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
    )
    return str(path)


def test_a_square_logo_is_sized_as_it_always_was(tmp_path):
    assert ff.logo_box(str(LOGO_DIR / "classic-tv.png"), 94) == (94, 94)
    assert ff.logo_box(write_png(tmp_path / "s.png", 300, 300), 50) == (50, 50)
    # Not a PNG StationPlay can read: as a square.
    assert ff.logo_box(str(tmp_path / "missing.png"), 50) == (50, 50)
    (tmp_path / "junk.png").write_bytes(b"not a picture at all, not even close")
    assert ff.logo_box(str(tmp_path / "junk.png"), 50) == (50, 50)


def test_a_logo_in_its_own_shape_covers_as_much_as_a_square_one(tmp_path):
    # 4:1, twice as wide and half as tall: the same area.
    assert ff.logo_box(write_png(tmp_path / "w.png", 1024, 256), 100) == (200, 50)
    assert ff.logo_box(write_png(tmp_path / "w2.png", 900, 400), 100) == (150, 67)
    # Very wide: no more than LOGO_WIDEST as wide as the square (and smaller).
    w, h = ff.logo_box(write_png(tmp_path / "w3.png", 1000, 100), 100)
    assert (w, h) == (round(ff.LOGO_WIDEST * 100), 24)
    # Tall: no more than LOGO_TALLEST as tall.
    w, h = ff.logo_box(write_png(tmp_path / "t.png", 200, 400), 100)
    assert (w, h) == (round(ff.LOGO_TALLEST * 100 / 2), round(ff.LOGO_TALLEST * 100))
    # Each size scales it alike.
    small, large = (ff.logo_box(str(tmp_path / "w.png"), s) for s in (55, 100))
    assert small == (110, 28) and large == (200, 50)


def test_the_corner_mark_fits_it_in_its_box(tmp_path):
    hd = Settings(plex_url="", plex_token="")
    logo = write_png(tmp_path / "wide.png", 1024, 256)
    for size, scale in ff.WATERMARK_SIZES.items():
        mark = ff.Watermark(logo=logo, size=size)
        side = ff.mark_size(hd, mark)
        assert side == round(720 * 0.13 * scale)
        chains, _ = ff._watermark(hd, mark)
        assert f"scale={2 * side}:{round(side / 2)}:force_original_aspect_ratio=decrease" in chains
    square = ff.Watermark(logo=str(LOGO_DIR / "classic-tv.png"))
    side = ff.mark_size(hd, square)
    assert f"scale={side}:{side}:" in ff._watermark(hd, square)[0]


# Making it ready ---------------------------------------------------------------


@needs_ffmpeg
def test_its_trimmed_to_whats_drawn_with_room_like_the_librarys():
    # Lettering 800x200 in the middle of a big see-through picture.
    png = asyncio.run(to_trimmed_logo_png(drawn("1600x900", "800x200", (300, 500)), "ffmpeg"))
    width, height = png_size(png)
    assert width == WIDEST and abs(width / height - 4) < 0.05  # its own shape, as wide as it goes
    w, h, x, y = visible_box(png)
    assert abs(w / width - FILLED) < 0.01 and abs(h / height - FILLED) < 0.02
    assert abs(x - (width - w) / 2) <= 1 and abs(y - (height - h) / 2) <= 1  # in the middle
    # A very thin one gets more room above and below, so it's never drawn
    # too thin to show.
    thin = asyncio.run(to_trimmed_logo_png(drawn("2000x300", "1600x20", (100, 100)), "ffmpeg"))
    assert png_size(thin) == (WIDEST, WIDEST // MAX_STRETCH)
    # A tall one is no taller than the library's.
    tall = asyncio.run(to_trimmed_logo_png(drawn("400x900", "100x300", (150, 20)), "ffmpeg"))
    assert png_size(tall)[1] == SIZE
    # A small one is made as large.
    small = asyncio.run(to_trimmed_logo_png(drawn("120x60", "100x40", (10, 10)), "ffmpeg"))
    assert png_size(small)[0] == WIDEST


@needs_ffmpeg
def test_a_logo_with_nothing_in_it_or_not_a_picture_isnt_used():
    with pytest.raises(LogoError, match="nothing in it"):
        asyncio.run(to_trimmed_logo_png(empty(), "ffmpeg"))
    with pytest.raises(LogoError) as e:
        asyncio.run(to_trimmed_logo_png(b"<html>not a picture</html>", "ffmpeg"))
    assert str(e.value) == UNREADABLE


def empty() -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black@0:s=300x100,format=rgba",
         "-frames:v", "1", "-f", "image2", "-c:v", "png", "pipe:1"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip


# From Plex, in the editor ------------------------------------------------------


class PlexWithLogos:
    """FakePlex, with logos (and what Plex says about them) for some shows."""

    def __init__(self, fp: FakePlex) -> None:
        self.fp = fp
        self.logos: dict[str, tuple[str, bytes]] = {}  # rating key: (url, picture)
        self.fetched: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for key, (url, picture) in self.logos.items():
            if path == url:
                self.fetched.append(path)
                return httpx.Response(200, content=picture, headers={"content-type": "image/png"})
            if path == f"/library/metadata/{key}":
                show = self.fp.shows[key]
                images = [
                    {"type": "coverPoster", "url": f"/library/metadata/{key}/thumb/1"},
                    {"alt": show["title"], "type": "clearLogo", "url": url},
                ]
                meta = {**show, "type": "show", "Image": images}
                return httpx.Response(
                    200, content=json.dumps({"MediaContainer": {"Metadata": [meta]}})
                )
        return self.fp.handler(request)


@pytest.fixture
def plex(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Bonanza")
    fp.add_episode("201", "100", 1, 1, "A Rose for Lotta", "/tv/1.mkv", 50 * MIN)
    fp.add_show("101", "Gunsmoke")
    fp.add_episode("202", "101", 1, 1, "Matt Gets It", "/tv/2.mkv", 25 * MIN)
    return PlexWithLogos(fp)


@pytest.fixture
def client(plex, tmp_path):
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=httpx.MockTransport(plex.handler)),
    )
    with TestClient(app) as c:
        yield c


@needs_ffmpeg
def test_a_shows_logo_from_plex_can_be_a_stations(client, plex):
    plex.logos["100"] = (LOGO_URL, drawn("800x310", "700x200", (50, 55)))
    # The editor shows it as it would be used.
    preview = client.get("/plex-logo/100.png")
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"
    assert png_size(preview.content)[0] == WIDEST
    # (Kept only by the browser that asked, never by a proxy on the way.)
    assert preview.headers["cache-control"].startswith("private")
    # Added to your logos, named after the show.
    added = client.post("/api/logos/plex", json={"ratingKey": "100"})
    assert added.status_code == 201, added.text
    mine = added.json()
    assert mine["name"] == "Bonanza" and mine["category"] == "Your logos"
    assert mine["id"].startswith("upload-") and mine["id"] == preview.headers["x-logo-id"]
    assert client.get(f"/logos/{mine['id']}.png").content == preview.content
    # Fetched from Plex once, though asked about each time.
    assert plex.fetched == [LOGO_URL]
    # Adding it again finds the same one.
    again = client.post("/api/logos/plex", json={"ratingKey": "100"}).json()
    assert again == mine
    catalog = client.get("/api/logos").json()
    assert [logo["id"] for logo in catalog].count(mine["id"]) == 1
    # A station can use it, and Plex's guide gets it.
    made = client.post(
        "/api/channels",
        json={"number": 5, "sources": [{"type": "show", "ratingKey": "100"}], "logo": mine["id"]},
    )
    assert made.status_code == 201 and made.json()["logo"] == mine["id"]
    assert client.get("/channel-icon/5.png").content == preview.content
    # When the logo changes in Plex, the new one is another logo of yours.
    plex.logos["100"] = (
        LOGO_URL.replace("1730116804", "1740000000"),
        drawn("500x100", "400x60", (50, 20)),
    )
    changed = client.post("/api/logos/plex", json={"ratingKey": "100"}).json()
    assert changed["id"] != mine["id"] and changed["name"] == "Bonanza"


def test_without_a_logo_in_plex_theres_none_to_use(client, plex):
    for key in ("101", "999", "abc", "1..2"):
        assert client.get(f"/plex-logo/{key}.png").status_code == 404, key
        assert client.post("/api/logos/plex", json={"ratingKey": key}).status_code == 404, key
    assert not [p for p in plex.fp.requests if "clearLogo" in p]


@needs_ffmpeg
def test_only_a_logo_plex_keeps_itself_is_fetched(client, plex):
    # A logo somewhere else (or anything that isn't one of Plex's) isn't fetched.
    for url in ("https://elsewhere.test/logo.png", "/library/metadata/100/thumb/1", "/../logo"):
        plex.logos["100"] = (url, drawn("800x310", "700x200", (50, 55)))
        assert client.get("/plex-logo/100.png").status_code == 404, url
    assert plex.fetched == []


@needs_ffmpeg
def test_a_logo_plex_cant_send_isnt_used(client, plex):
    plex.logos["100"] = (LOGO_URL, b"<html>Plex had a problem</html>")
    assert client.get("/plex-logo/100.png").status_code == 404
    assert client.post("/api/logos/plex", json={"ratingKey": "100"}).status_code == 404
    assert all(logo["category"] != "Your logos" for logo in client.get("/api/logos").json())


@needs_ffmpeg
def test_a_backup_brings_it_back_in_its_own_shape(client, plex, tmp_path):
    plex.logos["100"] = (LOGO_URL, drawn("800x310", "700x200", (50, 55)))
    mine = client.post("/api/logos/plex", json={"ratingKey": "100"}).json()
    kept = client.get(f"/logos/{mine['id']}.png").content
    client.app.state.ctx.restart = lambda: None  # (a test mustn't stop itself)
    name = client.post("/api/backups").json()["name"]
    restored = client.post("/api/restore", content=client.get(f"/api/backups/{name}").content)
    assert restored.status_code == 200, restored.text
    # Drawn again (as everything from a backup is), the same shape and size.
    (staged,) = backups.staged_logos(tmp_path / "data")
    assert staged.name == f"{mine['id']}.png"
    assert png_size(staged.read_bytes()) == png_size(kept)
