"""StationPlay's page as a web app: added to a phone's or tablet's home
screen, or installed on a computer, it opens in a window of its own. Its
manifest and icons (open before signing in, at home and from the internet),
what the page's head says about it, and links to other sites opening
outside its window."""

from __future__ import annotations

import re
import struct

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import WEB_DIR, create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .test_security import PAT, both_ports

ICONS = {"/icon-192.png": 192, "/icon-512.png": 512, "/icon-maskable-512.png": 512}
PAGE = (WEB_DIR / "index.html").read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data")
    app = create_app(
        settings, PlexClient("http://plex.test", "token", transport=FakePlex().transport())
    )
    with TestClient(app) as c:
        yield c


def background(theme: str) -> str:
    """The page's background (--bg) in its light or dark colors."""
    start = ':root[data-theme="dark"] {' if theme == "dark" else ":root {"
    found = re.search(r"--bg: (#[0-9a-f]{6});", PAGE.split(start, 1)[1].split("}", 1)[0])
    assert found
    return found[1]


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_the_manifest_says_how_to_install_the_page(client):
    got = client.get("/manifest.webmanifest")
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/manifest+json"
    assert got.headers["cache-control"] == "max-age=86400"
    manifest = got.json()
    assert manifest["name"] == manifest["short_name"] == "StationPlay"
    assert manifest["start_url"] == manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    # The page's own background, as it is in dark (the window's color before the page is drawn).
    assert background("dark") == "#11161b" and background("light") == "#f4f2ee"
    assert manifest["background_color"] == manifest["theme_color"] == background("dark")
    assert [(i["src"], i["sizes"], i["type"], i["purpose"]) for i in manifest["icons"]] == [
        ("/icon-192.png", "192x192", "image/png", "any"),
        ("/icon-512.png", "512x512", "image/png", "any"),
        ("/icon-maskable-512.png", "512x512", "image/png", "maskable"),
    ]
    # Each icon is there, at its size exactly.
    for icon in manifest["icons"]:
        got = client.get(icon["src"])
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        assert got.headers["cache-control"] == "max-age=86400"
        assert png_size(got.content) == (ICONS[icon["src"]],) * 2
    assert png_size(client.get("/apple-touch-icon.png").content) == (180, 180)


async def test_installing_needs_no_sign_in_at_home_or_from_the_internet(tmp_path):
    async with both_ports(tmp_path) as (home, internet):
        wanted = ["/manifest.webmanifest", "/apple-touch-icon.png", *ICONS]
        # From the internet before there's a user, when only the sign-in page is shown.
        async with httpx.AsyncClient(base_url=internet) as outside:
            assert (await outside.get("/api/status")).status_code == 403
            for path in wanted:
                assert (await outside.get(path)).status_code == 200, path
        async with httpx.AsyncClient(base_url=home) as inside:
            assert (await inside.post("/api/access/users", json=PAT)).status_code == 201
        # And with signing in on, before signing in.
        for base in (home, internet):
            async with httpx.AsyncClient(base_url=base) as visitor:
                assert (await visitor.get("/api/channels")).status_code == 401
                for path in wanted:
                    got = await visitor.get(path)
                    assert got.status_code == 200, (base, path)
                    assert got.headers["x-content-type-options"] == "nosniff"


def test_the_page_says_its_an_app(client):
    page = client.get("/").text
    head = page.split("</head>")[0]
    assert '<link rel="manifest" href="/manifest.webmanifest"' in head
    # The window's color: the page's background, light or dark as the device is.
    for theme in ("light", "dark"):
        assert (
            f'<meta name="theme-color" content="{background(theme)}" '
            f'media="(prefers-color-scheme: {theme})">' in head
        )
    for meta in (
        '<meta name="mobile-web-app-capable" content="yes">',
        '<meta name="apple-mobile-web-app-capable" content="yes">',
        '<meta name="apple-mobile-web-app-title" content="StationPlay">',
        # (Below the iPhone's status bar: "black-translucent" would put the page under it.)
        '<meta name="apple-mobile-web-app-status-bar-style" content="default">',
    ):
        assert meta in head, meta
    # No service worker: the page is always the one StationPlay serves now.
    assert "serviceWorker" not in page


def test_links_to_other_sites_open_outside_the_apps_window():
    # (Links in the page's HTML, and those its script makes.)
    links = re.findall(r"<a\b[^>]*>", PAGE) + re.findall(r"h\('a', \{.*?\}\)", PAGE)
    outside = [a for a in links if re.search(r"""href[=:] ?["'`]https?://""", a)]
    assert len(outside) >= 2  # (Buy Me a Coffee, and the license)
    for a in outside:
        assert re.search(r"""target[=:] ?["']_blank["']""", a), a
        assert re.search(r"""rel[=:] ?["'][^"']*\bnoopener\b""", a), a
