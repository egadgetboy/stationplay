"""The Setup tab's lines (addtoplex.js), run in Node with stand-ins for the
page: what Media files and Guide updates say, with Plex and without it.

(The third audit of 1.35.0: the Media files line still said "Mount your
media folder there", the advice that sent the owner to his server's own
path, October 13, and spoke of Plex where tapiOca doesn't use it.)"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "app" / "web" / "js" / "addtoplex.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

STAND_INS = """
const els = {};
function $(sel) {
  return els[sel] ??= {
    parentElement: { hidden: false }, className: '', children: [],
    replaceChildren(...c) { this.children = c; },
  };
}
function h(tag, attrs, ...kids) { return { tag, attrs, text: kids.join('') }; }
"""
SAID = """
const out = {};
for (const [k, v] of Object.entries(els)) {
  out[k] = {
    hidden: v.parentElement.hidden,
    text: v.children.map(c => typeof c === 'string' ? c : c.text).join(''),
  };
}
console.log(JSON.stringify(out));
"""


def _function(script: str, name: str) -> str:
    start = script.index(f"function {name}(")
    return script[start : script.index("\n}\n", start) + 3]


def lines(call: str, script: str | None = None) -> dict:
    """What the page's two lines hold after `call`, by their selectors."""
    script = script if script is not None else JS.read_text(encoding="utf-8")
    code = (
        STAND_INS
        + _function(script, "renderMediaAccess")
        + _function(script, "renderGuideState")
        + call
        + SAID
    )
    done = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


NOTHING_THERE = json.dumps(
    {"direct": 0, "viaPlex": 0, "mappings": [], "mediaDir": "/mnt/tank/media",
     "mediaDirPresent": False}
)  # fmt: skip
GUIDE = json.dumps({"plexDownloadedGuide": None, "canRefreshPlexGuide": False})


def test_nothing_at_media_dir_with_plex():
    said = lines(f"renderMediaAccess({NOTHING_THERE}, true); renderGuideState({GUIDE}, true);")
    assert said["#mediaAccess"]["text"] == (
        "Nothing is at /mnt/tank/media inside tapiOca. Run setup again: its first step says "
        "what to change. Until then, Plex’s files are streamed from Plex."
    )
    assert "Mount your media folder" not in said["#mediaAccess"]["text"]
    assert not said["#guideState"]["hidden"]
    assert said["#guideState"]["text"].startswith("Plex hasn’t downloaded the guide yet.")


def test_without_plex_nothing_is_said_about_it():
    said = lines(f"renderMediaAccess({NOTHING_THERE}, false); renderGuideState({GUIDE}, false);")
    assert said["#mediaAccess"]["text"] == (
        "Nothing is at /mnt/tank/media inside tapiOca. Run setup again: its first step says "
        "what to change."
    )
    assert said["#guideState"]["hidden"]
    # (And the page tells the two apart by the status's plexUsed, an Admin's,
    # or plex.used, a User's.)
    status = (JS.parent / "status.js").read_text(encoding="utf-8")
    assert "const plexUsed = (status.plexUsed ?? status.plex.used) !== false;" in status
    assert "renderMediaAccess(status.mediaAccess, plexUsed);" in status
    assert "renderGuideState(status.guide, plexUsed);" in status


def test_skipping_intros_says_what_your_own_folders_get():
    """(The audit of October 13) Intros and credits are skipped where Plex
    has found them: a station of your own folders' titles plays them in
    full, and the page says so, never "turn on detection in Plex" where
    tapiOca doesn't use Plex."""
    stations = (JS.parent / "stations.js").read_text(encoding="utf-8")
    editor = (JS.parent / "editor.js").read_text(encoding="utf-8")
    assert "Programs from your own Media folders play in full." in stations
    assert ": !plexUsed()" in stations  # (core.js: the one place that says)
    assert (
        "Programs Plex hasn’t marked, and those in your own Media folders, play in full." in editor
    )
    # (And an update that waits for review says what's gone, wherever it was.)
    assert "`Plex lost ${plural(p.removed" not in stations
    assert "`${plural(p.removed, 'program')} gone — needs your review`" in stations


def test_who_can_use_tapioca_says_nobody_from_the_internet():
    """(The owner, October 13: "Does the first one allow remote users too?")
    With signing in off, nobody can use tapiOca's page or apps from the
    internet: never "from the internet, tapiOca always asks people to sign
    in", which read as though they could. And what neither choice changes
    names every app, never Plex alone."""
    setup = (JS.parent / "setup.js").read_text(encoding="utf-8")
    access = (JS.parent / "access.js").read_text(encoding="utf-8")
    for script in (setup, access):
        assert "always asks people to sign in" not in script
        assert "Plex decides who can watch in Plex" not in script
    # (And what home means: the port a connection comes in on, the owner's
    # questions, 09:32 to 09:36.)
    assert (
        "No signing in. Anyone at home, on your network or through a VPN into it (port 3310), "
        "can use tapiOca’s page and apps and change anything, as an Admin can. Nobody can from "
        "the internet (port 3311), even with Away from home on." in setup
    )
    assert "Everyone signs in, at home and away, as an Admin or a User." in setup
    assert (
        "To use tapiOca’s apps from the internet (port 3311), also turn on Away from home on the "
        "Access tab." in setup
    )
    assert (
        "Neither changes who can watch in Plex, Jellyfin, Emby or Kodi: each app decides that "
        "itself." in setup
    )
    assert (
        "tapiOca is open: anyone at home, on your network or through a VPN into it (port 3310), "
        "can use it, and nobody can from the internet (port 3311)." in access
    )


def test_a_file_streamed_from_plex_never_brings_back_the_old_advice():
    """(The fourth audit of 1.35.0) Once a station has played with nothing
    at MEDIA_DIR, files have streamed from Plex: the Media files line still
    says to run setup again, never "mounting your media folder there"."""
    gone = json.dumps(
        {"direct": 0, "viaPlex": 3, "mappings": [], "mediaDir": "/mnt/hddpool/mediashare/media",
         "mediaDirPresent": False}
    )  # fmt: skip
    said = lines(f"renderMediaAccess({gone}, true); renderGuideState({GUIDE}, true);")
    assert said["#mediaAccess"]["text"] == (
        "Nothing is at /mnt/hddpool/mediashare/media inside tapiOca. Run setup again: its first "
        "step says what to change. Until then, Plex’s files are streamed from Plex."
    )


def test_the_page_says_nothing_of_plex_where_its_not_the_source():
    """(The fourth audit of 1.35.0) What's said of every station, whatever
    its titles' source: no "from Plex" for what isn't Plex's. And where
    only Plex is meant, it's said as Plex's."""
    stations = (JS.parent / "stations.js").read_text(encoding="utf-8")
    core = (JS.parent / "core.js").read_text(encoding="utf-8")
    apps = (JS.parent / "apps.js").read_text(encoding="utf-8")
    for gone in (
        "Pick some shows or movies from Plex",
        "Plex no longer lists many of this station’s programs",
        "Plex no longer lists the programs for one of this station’s blocks",
        "Check Plex for new and removed programs now.",
        "the same period the Plex guide covers",
        "Changes from Plex are ready.",
    ):
        assert gone not in stations, gone
    assert "Many of this station’s programs are gone." in stations
    assert "Check for new and removed programs now." in stations
    assert "plexUsed()" in stations
    assert "Watching in Plex? To add " in core
    assert "const plexUsed = () => (status?.plexUsed ?? status?.plex?.used) !== false;" in core
    # (Plex server only, on Tuner access: where Plex is used, or has been seen.)
    assert "plexOnly.hidden = !got.plex.length && !plexUsed();" in apps


def test_from_the_internet_before_signing_in_theres_no_form():
    """(The fourth audit of 1.35.0) From the internet, before signing in is
    on, the page shows the owner's sentence alone: no name, password or
    Sign in button under "can't reach the server"."""
    access = (JS.parent / "access.js").read_text(encoding="utf-8")
    page = (JS.parent.parent / "index.html").read_text(encoding="utf-8")
    assert '<button class="btn primary" type="submit" id="signinGo"' in page
    assert (
        "if (me.notSetUp) for (const id of ['#signinByPassword', '#signinByPin', '#signinGo']) "
        "$(id).hidden = true;"
    ) in access


def test_setup_offers_even_sound_where_media_in_the_apps_is_chosen():
    """The owner, October 14 (1.36.4): "Even Sound should be on by default,
    but I don't see where Admin can turn it off". It was only on the Access
    tab, in a panel folded shut. Setup's Media in tapiOca's apps step has it
    too, the same switch, saved with the step; and both say stations always
    have even sound, since the switch is for Media only (the owner: "even
    audio should always be on with Stations")."""
    setup = (JS.parent / "setup.js").read_text(encoding="utf-8")
    apps = (JS.parent / "apps.js").read_text(encoding="utf-8")
    step = setup.split("async library(", 1)[1].split("\n  async ", 1)[0]
    assert "evenSoundField(got" in step and "evenSound: even.input.checked" in step
    assert apps.count("= evenSoundField(got") == 1  # (the Access tab panel, the one other)
    assert "Stations always have even sound." in apps
