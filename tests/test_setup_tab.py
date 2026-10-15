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
    assert "Programs from Media folders tapiOca reads itself play in full." in stations
    assert ": !plexUsed()" in stations  # (core.js: the one place that says)
    assert (
        "Programs Plex hasn’t marked, and those in Media folders tapiOca reads itself, play in full."
        in editor
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
    assert "Episodes on your stations always have even sound." in apps
    # (1.36.4's audit: setup's box had the Access tab's id, so its words could change the
    # other box; and saving setup's step with only Even sound changed sent every folder,
    # which stopped sharing Media folders added later. Even sound goes alone then.)
    assert "evenSoundField(got, () => {}, 'setupEvenSound')" in step
    assert "if (cant || (!fields.changed() && !got.waiting)) {" in step
    assert "body: { evenSound: even.input.checked }" in step


MEDIA_FOLDERS_STAND_INS = r"""
const els = {};
const calls = [], toasts = [];
function $(sel) {
  return els[sel] ??= { children: [], hidden: false, addEventListener() {},
    replaceChildren(...c) { this.children = c; } };
}
const document = { querySelectorAll: () => [] };
function h(tag, attrs, ...kids) {
  const el = { tag, attrs: attrs || {}, kids: kids.flat(Infinity).filter(k => k != null && k !== false && k !== '') };
  el.checked = !!el.attrs.checked;
  el.disabled = !!el.attrs.disabled;
  return el;
}
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
const ago = () => '1 min ago';
const warnIcon = () => '⚠';
const toast = (said, bad) => toasts.push([said, !!bad]);
const pressOne = () => {};
let FOLDERS, MEDIA;
async function api(url, opts) {
  calls.push([url, opts || null]);
  if (url === '/api/folder-libraries') return FOLDERS;
  if (url === '/api/app-libraries') return MEDIA;
  throw new Error('unexpected ' + url);
}
const text = n => typeof n === 'string' ? n : n.kids.map(text).join('');
const all = (n, test, out = []) => {
  if (typeof n === 'string') return out;
  if (test(n)) out.push(n);
  n.kids.forEach(k => all(k, test, out));
  return out;
};
const panel = () => ({ tag: 'panel', attrs: {}, kids: $('#foldersPanel').children });
const boxes = () => all(panel(), n => n.tag === 'input' && n.attrs.type === 'checkbox');
const rows = () => all(panel(), n => n.tag === 'tr' && n.attrs['data-key']);
"""
OURS = {
    "key": "f1", "name": "Our shows", "kind": "show", "folders": ["/media/TV"], "shows": 2,
    "episodes": 6, "scannedMs": 1, "missingFolders": [], "alsoInPlex": [], "problem": None,
}  # fmt: skip
FOLDERS = {"libraries": [OURS], "mediaReal": "/media", "mediaDir": "/media", "plex": []}
MEDIA = {
    "libraries": [
        {"key": "1", "title": "TV Shows", "kind": "show"},
        {"key": "2", "title": "Films", "kind": "movie"},
        {"key": "f1", "title": "Our shows", "kind": "show"},
    ],
    "shared": ["1", "f1"], "everything": False, "waiting": False, "problem": None,
}  # fmt: skip


def media_folders(folders: dict, media: dict, then: str) -> dict:
    """The Setup tab's Media folders (folders.js, with apps.js's box for
    tapiOca's apps), drawn from these answers, then `then` (awaited)."""
    js = JS.parent
    apps = (js / "apps.js").read_text(encoding="utf-8")
    code = (
        MEDIA_FOLDERS_STAND_INS
        + _function(apps, "mediaFolderBox")
        + (js / "folders.js").read_text(encoding="utf-8")
        + f"FOLDERS = {json.dumps(folders)}; MEDIA = {json.dumps(media)};\n"
        + "(async () => { await loadFolderLibraries();\n"
        + then
        + "\n})().catch(e => { console.error(e.stack); process.exit(1); });"
    )
    done = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_one_list_of_media_folders_on_the_setup_tab():
    """The owner, October 15 (1.36.4): "I don't care what folders Plex can
    see. Server just needs to know what folders it can see, and the option
    to toggle them on and off." One Media folders section lists every Media
    folder tapiOca has, each with its switch for tapiOca's apps; those
    tapiOca reads itself also show their folders, state, Read again, Edit
    and Remove. Nothing names Plex for a folder."""
    said = media_folders(
        FOLDERS,
        MEDIA,
        """
    console.log(JSON.stringify({
      rows: rows().map(r => [r.attrs['data-key'], text(r)]),
      boxes: boxes().map(b => [b.checked, b.disabled, b.attrs['aria-label']]),
      labels: all(panel(), n => n.tag === 'label').map(text),
      reads: all(panel(), n => n.tag === 'button' && text(n) === 'Read again').length,
      all: text(panel()),
    }));
    """,
    )
    assert [key for key, _ in said["rows"]] == ["1", "2", "f1"]
    tv, films, ours = (row for _, row in said["rows"])
    assert tv.startswith("TV Shows") and "Shows" in tv and "Movies" not in tv
    assert films.startswith("Films") and "Movies" in films
    assert "Shows · 2 shows, 6 episodes" in ours and "Read 1 min ago" in ours
    assert said["boxes"] == [
        [True, False, "TV Shows in tapiOca’s apps"],
        [False, False, "Films in tapiOca’s apps"],
        [True, False, "Our shows in tapiOca’s apps"],
    ]
    assert [label.strip() for label in said["labels"]] == ["In tapiOca’s apps"] * 3
    assert said["reads"] == 1  # (only the one tapiOca reads itself)
    assert "Plex" not in said["all"]


def test_a_media_folders_switch_saves_at_once():
    """Switching one off saves the ones now on (and only them), says
    Saved, and draws the list again from the server."""
    said = media_folders(
        FOLDERS,
        MEDIA,
        """
    calls.length = 0;
    const box = boxes()[0];
    box.checked = false;
    await box.attrs.oninput();
    console.log(JSON.stringify({ calls, toasts }));
    """,
    )
    assert said["calls"][0] == [
        "/api/app-libraries",
        {"method": "PUT", "body": {"libraries": ["f1"]}},
    ]
    assert sorted(url for url, _ in said["calls"][1:]) == [
        "/api/app-libraries",
        "/api/folder-libraries",
    ]
    assert said["toasts"] == [["Saved", False]]


def test_media_folders_while_they_cant_all_be_listed():
    """While the Media folders can't all be listed, the switches can't be
    changed and the problem is said, as on the Access tab. A switch is on
    only while its folder is shared: while none has been chosen yet (from
    before 1.34.1), every one is off, and the page says how to choose (1.36.4's
    third audit: they all showed on, though nothing was shared)."""
    problem = "Plex isn’t answering, so tapiOca can’t list Plex’s Media folders right now."
    down = {**MEDIA, "libraries": MEDIA["libraries"][2:], "problem": problem}
    said = media_folders(
        FOLDERS,
        down,
        """
    console.log(JSON.stringify({ boxes: boxes().map(b => [b.checked, b.disabled]), all: text(panel()) }));
    """,
    )
    assert said["boxes"] == [[True, True]]
    assert problem in said["all"]
    waiting = {**MEDIA, "shared": [], "waiting": True}
    said = media_folders(
        FOLDERS,
        waiting,
        """
    console.log(JSON.stringify({ boxes: boxes().map(b => b.checked), all: text(panel()) }));
    """,
    )
    assert said["boxes"] == [False, False, False]
    assert "None are in tapiOca’s apps yet." in said["all"]


def test_no_media_folders_yet():
    said = media_folders(
        {**FOLDERS, "libraries": []},
        {
            **MEDIA,
            "libraries": [],
            "shared": [],
            "problem": "There are no Media folders to share yet.",
        },
        "console.log(JSON.stringify(text(panel())));",
    )
    assert said == "No Media folders yet. Add one, or connect Plex in setup."


def test_the_media_folders_section_says_what_it_is():
    """The Setup tab's section, once "Folders tapiOca reads itself", is
    Media folders (1.36.4), with Add a Media folder as before."""
    page = (JS.parent.parent / "index.html").read_text(encoding="utf-8")
    assert "Folders tapiOca reads itself" not in page
    head = page.split('id="addFolderLibrary"', 1)[0].rsplit('<div class="section-head"', 1)[1]
    assert "<h2>Media folders</h2>" in head
    assert ">Add a Media folder</button>" in page.split('id="addFolderLibrary"', 1)[1][:40]
    said = page.split('id="addFolderLibrary"', 1)[1].split('<div class="panel" id="foldersPanel">')[
        0
    ]
    assert (
        "Every Media folder tapiOca has. Switch one off to keep it out of tapiOca’s apps; "
        "stations can still use it. Add a Media folder to have tapiOca read shows or movies "
        "itself, from the folders it can see. It takes each title’s details from the NFO files beside it, the "
        "file itself and its name, and its pictures from beside it, and reads them again every "
        "6 hours, when you choose Read again, and when Sonarr or Radarr brings a replacement "
        "tapiOca asked for."
    ) in said
    # (The Access tab's panel decides the same way: one box, from apps.js.)
    apps = (JS.parent / "apps.js").read_text(encoding="utf-8")
    assert "const box = mediaFolderBox(got, l.key, onEdit);" in apps
    folders = (JS.parent / "folders.js").read_text(encoding="utf-8")
    assert "mediaFolderBox({ ...media, waiting: false }, l.key" in folders


def test_a_save_keeps_every_media_folder_shared_unless_a_folders_switch_changed():
    """1.36.4's third audit: saving the Access tab's panel, or setup's Media step, with
    only "When playing can't keep up" or Even sound changed sent every folder, which
    stopped sharing Media folders added later. The choice of folders goes only when a
    folder's switch changed. And the Setup tab's switches drop a slow, older answer, so
    one never brings back a folder just switched off, and say what switching one does."""
    apps = (JS.parent / "apps.js").read_text(encoding="utf-8")
    setup = (JS.parent / "setup.js").read_text(encoding="utf-8")
    folders = (JS.parent / "folders.js").read_text(encoding="utf-8")
    assert "if (!got.waiting && !fields.librariesChanged()) delete chosen.libraries;" in apps
    assert "if (!got.waiting && !fields.librariesChanged()) delete body.libraries;" in setup
    assert "if (asked !== foldersAsked) return;" in folders and "foldersAsked++;" in folders
    assert (
        "Once you switch one off, only those switched on are, and new ones start switched off."
        in folders
    )
