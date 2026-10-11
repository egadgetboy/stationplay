"""StationPlay's page as a web app: added to a phone's or tablet's home
screen, or installed on a computer, it opens in a window of its own. Its
manifest and icons (open before signing in, at home and from the internet),
what the page's head says about it, and links to other sites opening
outside its window."""

from __future__ import annotations

import json
import re
import struct

import httpx
import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.access import PAGE_FILES
from app.config import Settings
from app.main import WEB_DIR, create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .helpers import page_code
from .test_security import PAT, both_ports

ICONS = {"/icon-192.png": 192, "/icon-512.png": 512, "/icon-maskable-512.png": 512}
# The page's code: index.html, and its own styles and scripts.
PAGE = "\n".join(
    (WEB_DIR / name).read_text(encoding="utf-8") for name in ("index.html", *PAGE_FILES)
)


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


async def test_the_pages_files_need_no_sign_in_at_home_or_from_the_internet(tmp_path):
    wanted = [f"/web/{name}?v={__version__}" for name in PAGE_FILES]
    others = [f"/web/index.html?v={__version__}", f"/web/..%2fmain.py?v={__version__}"]
    async with both_ports(tmp_path) as (home, internet):
        # From the internet before there's a user, when only the sign-in page is shown.
        async with httpx.AsyncClient(base_url=internet) as outside:
            for path in wanted:
                assert (await outside.get(path)).status_code == 200, path
            for path in others:
                assert (await outside.get(path)).status_code == 403, path
        async with httpx.AsyncClient(base_url=home) as inside:
            assert (await inside.post("/api/access/users", json=PAT)).status_code == 201
        # And with signing in on, before signing in.
        for base in (home, internet):
            async with httpx.AsyncClient(base_url=base) as visitor:
                for path in wanted:
                    got = await visitor.get(path)
                    assert got.status_code == 200, (base, path)
                    assert got.headers["cache-control"] == "max-age=31536000, immutable"
                for path in others:
                    assert (await visitor.get(path)).status_code == 401, (base, path)


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
    assert "serviceWorker" not in page_code(client)


def test_links_to_other_sites_open_outside_the_apps_window():
    # (Links in the page's HTML, and those its script makes.)
    links = re.findall(r"<a\b[^>]*>", PAGE) + re.findall(r"h\('a', \{.*?\}\)", PAGE)
    outside = [a for a in links if re.search(r"""href[=:] ?["'`]https?://""", a)]
    assert len(outside) >= 3  # (Buy Me a Coffee, the license, and the source)
    for a in outside:
        assert re.search(r"""target[=:] ?["']_blank["']""", a), a
        assert re.search(r"""rel[=:] ?["'][^"']*\bnoopener\b""", a), a


def test_the_server_has_no_license():
    """StationPlay's apps are unlocked in their own stores (the owner's
    choice, October 10): the server has no License section, no license
    addresses and no server ID, and its page says nothing of a license but
    its own, the AGPL."""
    assert "licensePanel" not in PAGE and "loadLicense" not in PAGE
    assert "/api/access/license" not in PAGE and "serverId" not in PAGE
    assert not (WEB_DIR.parent / "licensing.py").exists()


def test_codes_and_addresses_arent_autocorrected():
    """What people type exactly (an app's link code, a Sonarr or Radarr
    address) tells a phone's keyboard not to autocorrect it, capitalize it
    or check its spelling: the owner's Android keyboard kept "correcting"
    a link code as it was typed."""
    link = re.search(r'<input type="text" id="linkCode"[^>]*>', PAGE).group(0)
    for attribute in (
        'autocorrect="off"',
        'autocapitalize="characters"',
        'spellcheck="false"',
        'autocomplete="off"',
    ):
        assert attribute in link, attribute
    arr = re.search(r"const url = h\('input', \{ type: 'text', value: a\.url,[^\n]*", PAGE).group(0)
    for attribute in (
        "autocorrect: 'off'",
        "autocapitalize: 'off'",
        "spellcheck: 'false'",
        "autocomplete: 'off'",
    ):
        assert attribute in arr, attribute


def test_a_stations_progress_bar_marks_its_end():
    """The bar under what's playing has an end mark like the playhead's (the
    same size), in orange, inside the bar; it turns red with a short glow
    in the program's last 2%, timed by the page, and with less motion only
    its color changes."""
    css = (WEB_DIR / "page.css").read_text(encoding="utf-8")
    playhead = re.search(r"\.bar > span\.at::after \{([^}]*)\}", css)
    end = re.search(r"\.bar::after \{([^}]*)\}", css)
    assert playhead and end
    for size in ("top: -4px", "width: 2px", "height: 10px"):
        assert size in playhead[1] and size in end[1], size
    # (Inside the bar: it never sticks out.)
    assert "right: 0;" in end[1] and "background: var(--warn)" in end[1]
    assert "animation: bar-end 1.6s ease-out var(--arrive, 0s) both" in end[1]
    keyframes = css.split("@keyframes bar-end {", 1)[1].split("\n}", 1)[0]
    assert "background: var(--warn)" in keyframes and "background: var(--bad)" in keyframes
    assert "box-shadow" in keyframes  # (the glow)
    still = css.split("@keyframes bar-end-still {", 1)[1].split("}\n", 1)[0]
    assert "var(--bad)" in still and "box-shadow" not in still
    assert (
        "@media (prefers-reduced-motion: reduce) { .bar::after { animation-name: bar-end-still; } }"
        in css
    )
    stations = (WEB_DIR / "js/stations.js").read_text(encoding="utf-8")
    assert "const BAR_END = 0.98;" in stations
    assert "Math.round(n.start + (n.end - n.start) * BAR_END - now)" in stations
    assert "h('div', { class: 'bar', style: `--arrive:${arrive}ms` }" in stations


def test_the_users_table_sets_changes_and_removes_pins():
    """Beside New password, for each person (an Admin's own row too): Set
    PIN or Change PIN, then Remove PIN, through the Devices dialog's own
    controls and address; what the server says against it is shown."""
    access = (WEB_DIR / "js/access.js").read_text(encoding="utf-8")
    row = access.split("const actions = h('td', {},", 1)[1].split("ownPassword, canReport);", 1)[0]
    assert row.index("'New password'") < row.index(
        "onclick: () => editPin(u, actions) }, u.pin ? 'Change PIN' : 'Set PIN')"
    )
    assert "u.id === me.user" not in row  # (every row)
    # One set of controls, in the table and in the Devices dialog.
    assert access.count("'Remove PIN'") == 1 and access.count("pinControls(") == 3
    assert "pinControls(u, savePicker)" in access
    editing = access.split("function editPin(u, cell) {", 1)[1].split("\n}\n", 1)[0]
    assert "api(`/api/access/users/${u.id}/picker`, { method: 'PUT', body })" in editing
    assert "said.textContent = err.message" in editing
    controls = access.split("function pinControls(", 1)[1].split("\n}\n", 1)[0]
    assert "save({ pin: pin.value.trim() }, 'PIN saved')" in controls
    assert "save({ pin: '' }, 'PIN removed')" in controls


def test_the_page_says_its_license_and_offers_its_source(client):
    """StationPlay is under the GNU AGPL v3 (LICENSE, pyproject.toml, the
    API's spec): the page's foot says so, with the license's link and a link
    to StationPlay's source, as the AGPL asks of a program used over a
    network."""
    root = WEB_DIR.parent.parent
    assert (
        (root / "LICENSE")
        .read_text()
        .startswith("GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3, 19 November 2007\n")
    )
    assert 'license = "AGPL-3.0-only"' in (root / "pyproject.toml").read_text()
    spec = json.loads((root / "docs" / "openapi-v1.json").read_text())
    assert spec["info"]["license"] == {"name": "AGPL-3.0-only"}
    foot = client.get("/").text.split('<footer class="foot">', 1)[1].split("</footer>", 1)[0]
    assert (
        "© 2026 egadgetboy · Open source under the "
        '<a href="https://www.gnu.org/licenses/agpl-3.0.html" target="_blank" '
        'rel="noopener noreferrer">GNU AGPL v3</a> · '
        '<a href="https://github.com/egadgetboy/stationplay" target="_blank" '
        'rel="noopener noreferrer">Source</a> · No warranty'
    ) in foot
    assert "/gpl-3.0.html" not in PAGE and "GNU GPL" not in PAGE
