"""tapiOca's page as a web app: added to a phone's or tablet's home
screen, or installed on a computer, it opens in a window of its own. Its
manifest and icons (open before signing in, at home and from the internet),
what the page's head says about it, and links to other sites opening
outside its window."""

from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.access import FONT_FILES, PAGE_FILES
from app.config import Settings
from app.main import WEB_DIR, create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .helpers import PAGE as FROM_PAGE
from .helpers import page_code
from .test_security import PAT, both_ports

ICONS = {"/icon-192.png": 192, "/icon-512.png": 512, "/icon-maskable-512.png": 512}
# (1.34.0, tapiOca's brand) Its mark in a browser's tab, and the page's fonts.
FAVICONS = {"/favicon.svg": "image/svg+xml", "/favicon.ico": "image/x-icon"}
MARK = "2"  # (the icons' version: tapiOca's mark, 1.36.4)
FONTS = [f"/fonts/{name}" for name in FONT_FILES]
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
    # (The owner, October 14, 1.36.4: "tapiOca Server", as the tab says; under its icon, tapiOca.)
    assert (manifest["name"], manifest["short_name"]) == ("tapiOca Server", "tapiOca")
    assert manifest["start_url"] == manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    # The page's own background, as it is in dark (the window's color before the page is drawn).
    assert background("dark") == "#0a0a0a" and background("light") == "#ffffff"
    assert manifest["background_color"] == manifest["theme_color"] == background("dark")
    assert [(i["src"], i["sizes"], i["type"], i["purpose"]) for i in manifest["icons"]] == [
        (f"/icon-192.png?v={MARK}", "192x192", "image/png", "any"),
        (f"/icon-512.png?v={MARK}", "512x512", "image/png", "any"),
        (f"/icon-maskable-512.png?v={MARK}", "512x512", "image/png", "maskable"),
    ]
    # Each icon is there, at its size exactly.
    for icon in manifest["icons"]:
        got = client.get(icon["src"])
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        assert got.headers["cache-control"] == "max-age=86400"
        assert png_size(got.content) == (ICONS[icon["src"].split("?")[0]],) * 2
    assert png_size(client.get("/apple-touch-icon.png").content) == (180, 180)


async def test_installing_needs_no_sign_in_at_home_or_from_the_internet(tmp_path):
    async with both_ports(tmp_path) as (home, internet):
        wanted = ["/manifest.webmanifest", "/apple-touch-icon.png", *ICONS,
                  f"/apple-touch-icon.png?v={MARK}", *(f"{p}?v={MARK}" for p in ICONS)]  # fmt: skip
        # From the internet before there's a user, when only the sign-in page is shown.
        async with httpx.AsyncClient(headers=FROM_PAGE, base_url=internet) as outside:
            assert (await outside.get("/api/status")).status_code == 403
            for path in wanted:
                assert (await outside.get(path)).status_code == 200, path
        async with httpx.AsyncClient(headers=FROM_PAGE, base_url=home) as inside:
            assert (await inside.post("/api/access/users", json=PAT)).status_code == 201
        # And with signing in on, before signing in.
        for base in (home, internet):
            async with httpx.AsyncClient(headers=FROM_PAGE, base_url=base) as visitor:
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
        async with httpx.AsyncClient(headers=FROM_PAGE, base_url=internet) as outside:
            for path in wanted:
                assert (await outside.get(path)).status_code == 200, path
            for path in others:
                assert (await outside.get(path)).status_code == 403, path
        async with httpx.AsyncClient(headers=FROM_PAGE, base_url=home) as inside:
            assert (await inside.post("/api/access/users", json=PAT)).status_code == 201
        # And with signing in on, before signing in.
        for base in (home, internet):
            async with httpx.AsyncClient(headers=FROM_PAGE, base_url=base) as visitor:
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
        '<meta name="apple-mobile-web-app-title" content="tapiOca">',
        # (Below the iPhone's status bar: "black-translucent" would put the page under it.)
        '<meta name="apple-mobile-web-app-status-bar-style" content="default">',
    ):
        assert meta in head, meta
    # No service worker: the page is always the one tapiOca serves now.
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
    """tapiOca's apps are unlocked in their own stores (the owner's
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
    same size), in the warning color (--warn), inside the bar; it turns red with a short glow
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
    """tapiOca is under the GNU AGPL v3 (LICENSE, pyproject.toml, the
    API's spec): the page's foot says so, with the license's link and a link
    to tapiOca's source, as the AGPL asks of a program used over a
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
        '<a href="https://github.com/egadgetboy/tapioca-server" target="_blank" '
        'rel="noopener noreferrer">Source</a> · '
        '<a href="/open-source-notices" target="_blank" '
        'rel="noopener noreferrer">Open-source notices</a> · No warranty'
    ) in foot
    assert "/gpl-3.0.html" not in PAGE and "GNU GPL" not in PAGE


def test_the_open_source_notices_are_open_to_everyone(client):
    """The notices are for anyone tapiOca is offered to: with sign-in
    on, someone signed out (the sign-in page links to them) and a User get
    them too, as the page's own files are open."""
    from fastapi.testclient import TestClient

    client.post("/api/access/users", json={"name": "Pat", "password": "correct horse"})
    stranger = TestClient(client.app)
    assert stranger.get("/api/access/me").json()["user"] is None
    got = stranger.get("/open-source-notices")
    assert got.status_code == 200 and "FFmpeg" in got.text


def test_the_page_offers_the_open_source_notices(client):
    """THIRD_PARTY_NOTICES.md (beside LICENSE, and in the image beside it,
    with the exact Debian packages: see the Dockerfile) is served as plain text at /open-source-notices, the
    link beside Source at the foot of the page and of the sign-in page. It
    names tapiOca's own license and FFmpeg's, and where FFmpeg's exact
    source is."""
    root = WEB_DIR.parent.parent
    notices = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    got = client.get("/open-source-notices")
    assert got.status_code == 200
    assert got.headers["content-type"] == "text/plain; charset=utf-8"
    assert got.text == notices
    assert "AGPL-3.0" in notices and "[LICENSE](LICENSE)" in notices
    assert "## FFmpeg" in notices and "GPL-2.0-or-later" in notices
    assert "LGPL-2.1-or-later" in notices
    assert "sources.debian.org" in notices and "snapshot.debian.org" in notices
    assert "/opt/stationplay/third-party-packages.txt" in notices
    # Every package in requirements.txt, at its pinned version.
    for line in (root / "requirements.txt").read_text().splitlines():
        if "==" in line:
            name, version = line.split("==")
            assert f"| {name} | {version} |" in notices, name
    # Both feet link to it (the page's and the sign-in page's).
    link = (
        '<a href="/open-source-notices" target="_blank" '
        'rel="noopener noreferrer">Open-source notices</a>'
    )
    assert client.get("/").text.count(link) == 2


def test_the_access_tab_has_tuner_access():
    """Tuner access, on the Access tab (see tuner.py), just before Block
    stations for some Plex users and loaded with the tab: Any device on my
    home network or Only these devices, each change sending the whole of it;
    Only these devices with none listed saving nothing, and the last device
    never removed while only listed devices may use it; Plex server only;
    Recent tuner connections with Allow. (tools/page_sizes.py tries each
    control against the server.)"""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    panel = html.index('<details class="panel arr" id="tunerPanel">')
    assert panel < html.index('id="limitsPanel"')
    assert (
        '<summary><strong>Tuner access</strong><span class="muted" id="tunerSum"></span></summary>'
        in html[panel:]
    )
    assert '<div class="arr-body" id="tunerBody"></div>' in html[panel:]
    note = html.split("Plex, Jellyfin and other apps never sign in,", 1)[1].split("</p>", 1)[0]
    assert "open to every device on your network, unless you choose Only these devices" in note
    assert "under Tuner access" in note and "reset-access" in note
    core = (WEB_DIR / "js/core.js").read_text(encoding="utf-8")
    assert "if (name === 'access') { loadAccess(); loadApps(); loadTuner();" in core
    apps = (WEB_DIR / "js/apps.js").read_text(encoding="utf-8")
    tuner = apps.split("async function loadTuner() {", 1)[1].split("\n// tapiOca's apps", 1)[0]
    assert "api('/api/tuner')" in tuner
    assert "send('/api/tuner', { method: 'PUT', body: { only: onlyThese, devices } }" in tuner
    assert "send('/api/tuner/allow', { method: 'POST', body: { address: r.address } }" in tuner
    assert "send('/api/tuner/plex-only', { method: 'POST' }" in tuner
    # Every change shows what's answered, or why not (with what was saved).
    assert "catch (e) { renderTuner(got, e.message); return; }" in tuner
    assert "renderTuner(now);" in tuner
    # Only these devices with none listed: shown, not saved.
    sentence = "const TUNER_NONE = 'List at least one device, or choose Plex server only.';"
    assert sentence in apps
    assert "if (got.devices.length) put(true, got.devices," in tuner
    assert "else { tunerOnlyChosen = true; renderTuner(got); }" in tuner
    assert "if (got.devices.length === 1) { result.textContent = TUNER_NONE; return; }" in tuner
    assert "h('span', { class: 'hint', role: 'status' }, said)" in tuner
    for words in (
        "'Any device on my home network'",
        "'Only these devices', 'tapiOca’s own apps, signed in, never need listing.'",
        "`Only ${plural(got.devices.length, 'device')}`",
        "'Recent tuner connections'",
        "r.name || 'Unknown device'",
        "h('span', { class: 'chip bad' }, 'Refused')",
        "'No device has used the tuner in the last 7 days.'",
        "placeholder: '192.168.1.20'",
        "'Plex server only'",
        "ago(r.lastMs)",
    ):
        assert words in tuner, words
    # The warning: as tapiOca says it, with an icon (not color alone).
    assert "...(got.warning ? [h('div', { class: 'reach down' }," in tuner
    # (replaceChildren shows a null as the word "null": nothing is passed as one.)
    shown = tuner.rsplit("$('#tunerBody').replaceChildren(", 1)[1]  # (the panel, not a problem)
    assert ": null" not in shown and ") : null" not in shown
    assert "reachIcon('down')" in tuner and "h('p', { class: 'what' }, got.warning)" in tuner
    assert "channel" not in tuner.lower()


def test_the_privacy_notice_is_served_and_linked(client):
    """Plex's terms ask software that calls Plex Media Server to include a
    privacy notice (or link to one), and a copyright notice in its source
    (the owner, October 12: "just do it"). PRIVACY.md is served as plain
    text at /privacy, to anyone (the sign-in page links to it), and linked
    from the foot of the page and the sign-in page; the source says whose
    it is."""
    from fastapi.testclient import TestClient

    import app as package

    root = WEB_DIR.parent.parent
    notice = (root / "PRIVACY.md").read_text(encoding="utf-8")
    client.post("/api/access/users", json={"name": "Pat", "password": "correct horse"})
    stranger = TestClient(client.app)
    got = stranger.get("/privacy")
    assert got.status_code == 200 and got.text == notice
    assert got.headers["content-type"] == "text/plain; charset=utf-8"
    assert "sends nothing to its developer" in notice
    assert "Plex's own privacy policy covers Plex" in notice
    assert (
        PAGE.count('<a href="/privacy" target="_blank" rel="noopener noreferrer">Privacy</a>') == 2
    )
    assert "Copyright © 2026 egadgetboy" in (package.__doc__ or "")
    assert "COPY LICENSE THIRD_PARTY_NOTICES.md PRIVACY.md ./" in (root / "Dockerfile").read_text()


def test_the_privacy_notice_is_open_on_the_public_port_too(tmp_path):
    """From the internet too, before there's a user and after."""
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from app.plex import PlexClient

    from .fakeplex import FakePlex

    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
                 public_port=3311),
        PlexClient("http://plex.test", "token", transport=FakePlex().transport()),
    )  # fmt: skip
    with TestClient(app) as home:
        away = TestClient(app, base_url="http://testserver:3311")
        assert away.get("/privacy").status_code == 200
        home.post("/api/access/users", json={"name": "Pat", "password": "correct horse"})
        assert away.get("/privacy").status_code == 200


def test_first_run_setup_says_what_plexs_terms_require():
    """The owner, October 12: the Plex step of first-run setup states Plex's
    personal-use terms (and links tapiOca's privacy notice)."""
    script = (WEB_DIR / "js" / "setup.js").read_text(encoding="utf-8")
    assert (
        "Plex’s terms license Plex Media Server for personal use, on hardware and storage you own."
        in script
    )
    assert script.count("PERSONAL_USE()") == 1  # (once: the Plex step)
    # (In the Plex step itself, 1.33.1's audit asked: not just somewhere.)
    plex_step = script[script.index("  async plex(") :]
    plex_step = plex_step[: plex_step.index("\n  },\n")]
    assert "PERSONAL_USE()" in plex_step
    # Plex's own terms are linked, beside tapiOca's privacy notice.
    assert "https://www.plex.tv/about/privacy-legal/plex-terms-of-service/" in script


def test_more_arrows_are_only_drawn():
    """The owner, October 12: the down arrow while more is below what shows,
    and the up arrow while more is above (as tapiOca's apps have them),
    on every dialog's body, the log, a problem's journal, the editor's lists
    and the page itself. "More" is more than 1px, from what's laid out. They
    never take a click or a tap, are never focused, and screen readers pass
    them by. (tools/page_sizes.py checks them in a browser.)"""
    core = (WEB_DIR / "js" / "core.js").read_text(encoding="utf-8")
    assert "const MORE_SLACK = 1;" in core
    assert (
        "({ above: scrolled > MORE_SLACK, below: whole - shown - scrolled > MORE_SLACK })" in core
    )
    assert "'aria-hidden': 'true'" in core and 'focusable="false"' in core
    assert "tabindex" not in core.split("// More above, more below", 1)[1].split("// Copying", 1)[0]
    assert (
        "document.querySelectorAll('.dlg-body, #logList, .picker-list, .fbox, #fMatches')"
        ".forEach(moreArrows);" in core
    )
    assert "moreArrowsOf(el.scrollTop, el.clientHeight, el.scrollHeight)" in core
    assert "moreArrowsOf(page.scrollTop, window.innerHeight, page.scrollHeight)" in core
    logs = (WEB_DIR / "js" / "logs.js").read_text(encoding="utf-8")
    assert "moreArrows(lines);" in logs
    css = (WEB_DIR / "page.css").read_text(encoding="utf-8")
    layer = re.search(r"\.more-arrows \{([^}]*)\}", css)
    pieces = re.search(r"\.more-up, \.more-down \{([^}]*)\}", css)
    assert layer and pieces
    assert "pointer-events: none" in layer[1] and "pointer-events: none" in pieces[1]
    # The chevron in the muted text color, on a 44px fade into the background.
    assert "height: 44px" in pieces[1] and "color: var(--ink-2)" in pieces[1]
    assert ".more-arrows svg { display: block; width: 32px; height: 32px;" in css
    assert ".more-arrows.page { position: fixed;" in css and "--more-bg: var(--bg)" in css


def test_every_file_the_page_loads_is_one_of_its_files():
    """(1.34.0: updates.js was in index.html but not served, so the page
    had no update banner.) Each script and stylesheet the page asks for is
    in PAGE_FILES, in the order it loads them, and nothing in app/web/js is
    left out."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    asked = re.findall(r'(?:src|href)="/web/([^"?]+)\?v=__VERSION__"', html)
    assert asked == list(PAGE_FILES)
    scripts = sorted(f"js/{p.name}" for p in (WEB_DIR / "js").glob("*.js"))
    assert scripts == sorted(name for name in PAGE_FILES if name.startswith("js/"))


async def test_the_brands_icons_and_fonts_need_no_sign_in_at_home_or_from_the_internet(tmp_path):
    """(1.34.0) The favicons and the page's fonts load on the sign-in page
    too: from the internet before there's a user, and before signing in."""
    # (And as the page asks for them, with the mark's version, 1.36.4.)
    wanted = [*FAVICONS, *(f"{p}?v={MARK}" for p in FAVICONS), *FONTS]
    others = ["/fonts/SpaceGrotesk/OFL.txt", "/fonts/..%2findex.html", "/favicon.png"]
    async with both_ports(tmp_path) as (home, internet):
        async with httpx.AsyncClient(headers=FROM_PAGE, base_url=internet) as outside:
            for path in wanted:
                assert (await outside.get(path)).status_code == 200, path
            for path in others:
                assert (await outside.get(path)).status_code == 403, path
        async with httpx.AsyncClient(headers=FROM_PAGE, base_url=home) as inside:
            assert (await inside.post("/api/access/users", json=PAT)).status_code == 201
        for base in (home, internet):
            async with httpx.AsyncClient(headers=FROM_PAGE, base_url=base) as visitor:
                assert (await visitor.get("/api/channels")).status_code == 401
                for path in wanted:
                    got = await visitor.get(path)
                    assert got.status_code == 200, (base, path)
                    assert got.headers["x-content-type-options"] == "nosniff"
                for path in others:
                    assert (await visitor.get(path)).status_code == 401, (base, path)


def test_the_page_has_tapiocas_icons_and_its_own_fonts(client):
    """(1.34.0) The head asks for the favicons; each is served as its kind.
    The page's fonts are tapiOca's own files (never a font service's), each
    swapped in once loaded, served as WOFF2, with its license beside it."""
    head = client.get("/").text.split("</head>")[0]
    # (Their addresses carry the mark's version from 1.36.4: see the next test.)
    assert f'<link rel="icon" href="/favicon.svg?v={MARK}" type="image/svg+xml">' in head
    assert f'<link rel="icon" href="/favicon.ico?v={MARK}" sizes="48x48">' in head
    for path, kind in FAVICONS.items():
        got = client.get(path)
        assert got.status_code == 200 and got.headers["content-type"].startswith(kind), path
        assert got.content == (WEB_DIR / path.lstrip("/")).read_bytes()
    css = (WEB_DIR / "page.css").read_text(encoding="utf-8")
    faces = re.findall(r"@font-face \{([^}]*)\}", css)
    assert sorted(re.search(r"url\(([^)]+)\)", f)[1] for f in faces) == sorted(FONTS)
    assert all("font-display: swap;" in f for f in faces)
    assert not re.search(r"https?://|//fonts\.|@import", css)
    for path in FONTS:
        got = client.get(path)
        assert got.status_code == 200 and got.headers["content-type"] == "font/woff2", path
        assert got.content[:4] == b"wOF2"
        assert (WEB_DIR / path.lstrip("/")).with_name("OFL.txt").is_file()
    assert client.get("/fonts/SpaceGrotesk/OFL.txt").status_code == 404
    on_disk = sorted(p.relative_to(WEB_DIR / "fonts").as_posix()
                     for p in (WEB_DIR / "fonts").rglob("*.woff2"))  # fmt: skip
    assert on_disk == sorted(FONT_FILES)


def test_the_tab_says_tapioca_server_with_tapiocas_mark(client):
    """The owner, October 14 (1.36.4): the browser's tab showed StationPlay's
    old icon, and should say "tapiOca Server". A browser keeps a page's icon
    by the icon's address, however long ago it got it, so the addresses
    carry the mark's version (MARK): one that kept StationPlay's asks again.
    The installed web app has the name too."""
    head = client.get("/").text.split("</head>")[0]
    assert "<title>tapiOca Server</title>" in head
    links = re.findall(r'<link rel="(?:icon|apple-touch-icon)" href="([^"]+)"', head)
    assert len(links) == 3 and all(link.endswith(f"?v={MARK}") for link in links), links
    for link in links:
        got = client.get(link)
        path = link.split("?")[0]
        assert got.status_code == 200 and got.content == (WEB_DIR / path.lstrip("/")).read_bytes()
    made = client.get("/manifest.webmanifest").json()
    assert made["name"] == "tapiOca Server" and made["short_name"] == "tapiOca"
    assert all(i["src"].endswith(f"?v={MARK}") for i in made["icons"])


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def _luminance(color: str) -> float:
    def part(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * part(r) + 0.7152 * part(g) + 0.0722 * part(b)


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _over(color: str, percent: float, surface: str) -> str:
    mixed = [
        round(int(color[i : i + 2], 16) * percent + int(surface[i : i + 2], 16) * (1 - percent))
        for i in (1, 3, 5)
    ]
    return "#" + "".join(f"{c:02x}" for c in mixed)


def test_the_needs_a_look_chip_is_easy_to_read():
    """Setup's checks: "Needs a look" (.chip.warn) is at least 4.5:1 on
    every surface it can sit on, light and dark (the audit of 1.34.0: 4.4:1
    in the light theme), in the brand kit's colors."""
    css = (WEB_DIR / "page.css").read_text(encoding="utf-8")
    light = _tokens(css.split(":root {", 1)[1].split("}", 1)[0])
    dark = _tokens(css.split('[data-theme="dark"]', 1)[1].split("}", 1)[0])
    assert light["--warn"].lower() == "#c62828"  # (the kit's Danger, light)
    rule = re.search(r"\.chip\.warn \{([^}]*)\}", css)
    assert rule
    text = re.search(r"(?<![-\w])color: var\((--[\w-]+)\)", rule[1])
    assert text
    background = re.search(r"background: ([^;]+);", rule[1])
    for theme in (light, dark):
        ink = theme[text[1]]
        for surface in (theme["--bg"], theme["--panel"], theme["--panel-2"]):
            fill = surface
            if background:
                said = background[1].strip()
                mixed = re.fullmatch(
                    r"color-mix\(in srgb, var\((--[\w-]+)\) (\d+)%, transparent\)", said
                )
                token = re.fullmatch(r"var\((--[\w-]+)\)", said)
                if mixed:
                    fill = _over(theme[mixed[1]], int(mixed[2]) / 100, surface)
                elif token:
                    fill = theme[token[1]]
                else:
                    assert said in ("transparent", "none"), said
            assert _contrast(ink, fill) >= 4.5, (ink, fill, surface)


def test_no_style_makes_the_name_capitals():
    """tapiOca is always written so: no text-transform makes it "TAPIOCA"
    (the audit of 1.34.0: setup's last step on a phone said "WHO CAN USE
    TAPIOCA"). Capitals only for fixed words that never hold the name:
    tables' headings, the Watching now table's labels on a phone, and a
    problem's "What it means". (Block names, shown as On now's and the
    guide's labels, are anyone's words.)"""
    css = (WEB_DIR / "page.css").read_text(encoding="utf-8")
    capitals = sorted(
        " ".join(selector.split())
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        if re.search(r"text-transform:\s*(uppercase|capitalize)", body)
    )
    assert capitals == sorted(
        [
            "th",
            "table.now td.now-how::before, table.now td.now-app::before",
            ".problem-means .label",
        ]
    )
    for name in ("index.html", *(f for f in PAGE_FILES if f != "page.css")):
        page = (WEB_DIR / name).read_text(encoding="utf-8")
        found = re.findall(r"text-?[tT]ransform:\s*'?(\w+)", page)
        # (Only Link an app's code, which a person types.)
        assert found in ([], ["uppercase"]), name
        if found:
            assert 'id="linkCode"' in page and page.count("uppercase") == 1, name


def test_top_people_rows_are_never_the_sign_in_screens_cards():
    """The owner, October 15 (1.36.4): "User names are truncated in
    Server/Stats/Top People - no reason for this - plenty of room." Top
    people's rows (class who) took the sign-in screen's Who's tuning in?
    cards' styles, made for any .who: centered, so each row's line shrank
    to fit and its name was cut ("egadgetb…") beside an empty panel. Each
    use has its own: the cards in their list, Top people's rows in theirs."""
    css = (WEB_DIR / "page.css").read_text(encoding="utf-8")
    selectors = [
        " ".join(s.split())
        for group, _ in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        for s in group.split(",")
    ]
    assert not [s for s in selectors if s.startswith(".who") and not s.startswith(".who-")]
    assert ".who-list .who { display: grid; justify-items: center;" in css
    assert ".toplist .who { display: grid; gap: 4px; }" in css
    assert ".toplist .who + .who { border-top: 1px solid var(--line); padding-top: 8px; }" in css
    stats = (WEB_DIR / "js" / "stats.js").read_text(encoding="utf-8")
    assert "$('#statPeople').replaceChildren(" in stats and "h('div', { class: 'who' }," in stats
    assert '<div class="toplist" id="statPeople"></div>' in (WEB_DIR / "index.html").read_text(
        encoding="utf-8"
    )


def test_checkboxes_and_radio_buttons_are_the_accent():
    """(1.36.4) Every checkbox and radio button on the page is in the
    page's accent (Signal Teal's ink in light, Signal Teal in dark), never
    the browser's blue."""
    css = re.sub(r"/\*.*?\*/", "", (WEB_DIR / "page.css").read_text(encoding="utf-8"), flags=re.S)
    rules = {
        " ".join(selector.split()): body.strip()
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    }
    assert rules['input[type="checkbox"], input[type="radio"]'] == "accent-color: var(--accent);"


def test_the_pages_down_arrow_only_for_more_to_see():
    """The owner, October 15 (1.36.4), in Safari: the Stations tab with two
    stations showed the page's down arrow, with nothing below the footer
    but the page's empty space. The page's own down arrow shows only while
    the last footer that shows (the page's or the sign-in screen's) ends
    below the window, by more than MORE_SLACK. (tools/page_sizes.py checks
    it in a browser, at a window that hides only the space under the footer
    and one that hides the footer.)"""
    if shutil.which("node") is None:
        pytest.skip("needs node")
    core = (WEB_DIR / "js" / "core.js").read_text(encoding="utf-8")
    helper = core[core.index("const pageBelow = ") :].split("\n};\n", 1)[0] + "\n};\n"
    code = (
        "const MORE_SLACK = 1;\n"
        + helper
        + """
const foot = (bottom, shown = true) => ({
  getClientRects: () => (shown ? [1] : []), getBoundingClientRect: () => ({ bottom }) });
console.log(JSON.stringify([
  pageBelow([foot(830)], 844),            // the footer in sight, space under it hidden
  pageBelow([foot(845)], 844),            // 1px: rounding
  pageBelow([foot(846)], 844),            // the footer out of sight
  pageBelow([foot(900), foot(830, false)], 844),  // the sign-in screen's, hidden
  pageBelow([foot(900, false), foot(830)], 844),  // the page's, hidden
  pageBelow([foot(900, false)], 844),     // none shows: not known here
]));
"""
    )
    done = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [False, False, True, True, False, None]
    page = core.split("// The page's own, at the window's edges.", 1)[1].split("\n})();", 1)[0]
    assert "pageBelow(document.querySelectorAll('.foot'), window.innerHeight)" in page
    assert "moreArrowsOf(page.scrollTop, window.innerHeight, page.scrollHeight)" in page
