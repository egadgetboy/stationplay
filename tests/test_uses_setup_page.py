"""The setup's and the Setup tab's side of What you use (1.37.0), run in
Node with stand-ins for the page: the steps an updated tapiOca asks, what
step 4 says signing in doesn't change, each place's section on the Setup
tab (its chip, its guide line, its steps), the addresses shown for each
choice, and the Media files line with Media folders of your own. Until an
Admin chooses, each says what 1.36.0 said."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "app" / "web"
JS = WEB / "js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

HOUR = 3_600_000
DAY = 24 * HOUR

# Stand-ins for the page: h() makes plain objects; textOf() reads one back.
STAND_INS = r"""
const els = {};
function $(sel) {
  return els[sel] ??= {
    parentElement: { hidden: false }, className: '', children: [],
    replaceChildren(...c) { this.children = c; },
  };
}
function h(tag, attrs = {}, ...kids) {
  return {
    tag, attrs: attrs || {}, kids: kids.flat().filter(k => k != null && k !== false),
    replaceChildren(...c) { this.kids = c.flat(); },
  };
}
const copyButton = value => h('button', { class: 'btn' }, 'Copy');
const awaySummary = away => !away?.on ? 'Off' : 'Ready';
function textOf(n) {
  if (n == null || n === false) return '';
  if (typeof n === 'string' || typeof n === 'number') return String(n);
  return (n.kids || n.children || []).map(textOf).join('');
}
function find(n, test) {
  if (!n || typeof n !== 'object') return null;
  if (test(n)) return n;
  for (const k of n.kids || n.children || []) { const got = find(k, test); if (got) return got; }
  return null;
}
function chipOf(n) {
  const chip = find(n, x => /\bchip\b/.test(x.attrs?.class || ''));
  return chip ? [chip.attrs.class.replace(/\b(chip|note)\b/g, '').trim(), textOf(chip)] : null;
}
"""


def _function(script: str, name: str) -> str:
    start = script.index(f"function {name}(")
    return script[start : script.index("\n}\n", start) + 3]


def _line(script: str, start: str) -> str:
    a = script.index(start)
    return script[a : script.index(";\n", a) + 2]


def _block(script: str, start: str, end: str) -> str:
    a = script.index(start)
    return script[a : script.index(end, a)]


def node(code: str, status: dict | None = None) -> object:
    core = (JS / "core.js").read_text(encoding="utf-8")
    setup = (JS / "setup.js").read_text(encoding="utf-8")
    tab = (JS / "addtoplex.js").read_text(encoding="utf-8")
    stations = (JS / "stations.js").read_text(encoding="utf-8")
    script = "\n".join(
        [
            STAND_INS,
            f"let status = {json.dumps(status)};",
            _line(core, "const noun = "),
            _line(core, "const plural = "),
            _function(stations, "ago"),
            _line(setup, "const needsLook = "),
            _function(setup, "setupSteps"),
            _function(setup, "whoWatchesLine"),
            _function(setup, "usesWords"),
            _function(tab, "renderMediaAccess"),
            _function(tab, "renderGuideState"),
            _block(tab, "// Each place you watch", "// The Setup tab's places, painted"),
            f"console.log(JSON.stringify((() => {{ {code} }})()));",
        ]
    )
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# Step 4, Who can use tapiOca: what signing in doesn't change -----------------

OLD_NEW = (
    "Signing in doesn’t change who can watch in Plex, Jellyfin, Emby or Kodi: each app decides "
    "that itself."
)
OLD_UPDATED = "Neither changes who can watch in Plex, Jellyfin, Emby or Kodi: each app decides that itself."


@pytest.mark.parametrize(
    ("watch_in", "new", "updated"),
    [
        (None, OLD_NEW, OLD_UPDATED),
        (["tapioca"], "", ""),
        (["tapioca", "other"], "", ""),
        (
            ["emby"],
            "Signing in doesn’t change who can watch in Emby: Emby decides that itself.",
            "Neither changes who can watch in Emby: Emby decides that itself.",
        ),
        (
            ["tapioca", "plex", "jellyfin"],
            "Signing in doesn’t change who can watch in Plex or Jellyfin: each app decides that "
            "itself.",
            "Neither changes who can watch in Plex or Jellyfin: each app decides that itself.",
        ),
        (
            ["kodi", "emby", "plex", "other"],
            "Signing in doesn’t change who can watch in Plex, Emby or Kodi: each app decides that "
            "itself.",
            "Neither changes who can watch in Plex, Emby or Kodi: each app decides that itself.",
        ),
    ],
)
def test_step_4_says_what_signing_in_doesnt_change_where_you_watch(watch_in, new, updated):
    got = node(f"const w = {json.dumps(watch_in)}; return [whoWatchesLine(w), whoWatchesLine(w, true)];")
    assert got == [new, updated]


def test_step_4_still_has_136s_sentences_for_nothing_chosen():
    """(tests/test_setup_tab.py pins them too.) And the step uses the line."""
    setup = (JS / "setup.js").read_text(encoding="utf-8")
    assert f"'{OLD_NEW}'" in setup and f"'{OLD_UPDATED}'" in setup
    step = setup[setup.index("  async signIn(") :]
    step = step[: step.index("\n  },\n")]
    assert "whoWatchesLine(setupWatchIn())" in step
    assert "whoWatchesLine(setupWatchIn(), true)" in step


# The steps -----------------------------------------------------------------


def test_the_steps_after_an_update_from_136():
    st = {"pending": ["sources", "watchIn", "plex"], "questions": ["sources", "watchIn", "playback",
          "newStation", "signIn", "viewing", "away", "library", "fileChecks", "plex"]}  # fmt: skip
    fine = [{"state": "good"}]
    look = [{"state": "good"}, {"state": "warn"}]
    assert node(f"return setupSteps({json.dumps(st)}, 'updated', {json.dumps(fine)});") == [
        "sources", "watchIn", "plex", "done"
    ]  # fmt: skip
    assert node(f"return setupSteps({json.dumps(st)}, 'updated', {json.dumps(look)});") == [
        "checks", "sources", "watchIn", "plex", "done"
    ]  # fmt: skip
    # A new tapiOca: the checks, then every question (what you use first).
    assert node(f"return setupSteps({json.dumps(st)}, 'new', null);") == [
        "checks", *st["questions"], "done"
    ]  # fmt: skip


def test_the_steps_titles():
    setup = (JS / "setup.js").read_text(encoding="utf-8")
    titles = _block(setup, "const SETUP_TITLES = {", "};")
    assert "sources: 'Your shows and movies'," in titles
    assert "watchIn: 'Where you watch'," in titles
    assert "plex: 'Connecting your apps'," in titles


@pytest.mark.parametrize(
    ("sources", "watch_in", "said"),
    [
        (["plex"], ["tapioca"], {"sources": "Plex", "watchIn": "tapiOca’s apps"}),
        (["plex", "folders"], ["tapioca", "plex", "jellyfin"],
         {"sources": "Plex and Media folders of your own",
          "watchIn": "tapiOca’s apps, Plex and Jellyfin"}),
        (["folders"], ["other"], {"sources": "Media folders of your own", "watchIn": "Other apps"}),
        (None, None, {"sources": "", "watchIn": ""}),
    ],
)  # fmt: skip
def test_all_set_says_what_you_use(sources, watch_in, said):
    assert node(f"return usesWords({json.dumps(sources)}, {json.dumps(watch_in)});") == said


# The Setup tab: the addresses shown for each choice -----------------------------


@pytest.mark.parametrize(
    ("watch_in", "rows"),
    [
        (None, {"tuner": True, "xmltv": True, "m3u": True, "guide": True}),
        (["tapioca"], {"tuner": False, "xmltv": False, "m3u": False, "guide": False}),
        (["plex"], {"tuner": True, "xmltv": True, "m3u": False, "guide": False}),
        (["tapioca", "emby"], {"tuner": False, "xmltv": False, "m3u": True, "guide": True}),
        (["other"], {"tuner": False, "xmltv": False, "m3u": True, "guide": True}),
        (["plex", "jellyfin", "other"], {"tuner": True, "xmltv": True, "m3u": True, "guide": True}),
    ],
)
def test_the_addresses_shown_for_each_choice(watch_in, rows):
    assert node(f"return copyRowsShown({json.dumps(watch_in)});") == rows


def test_the_copy_rows_keep_their_ids():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for row, code in (("tunerRow", "tunerUrl"), ("xmltvRow", "xmltvUrl"), ("m3uRow", "m3uUrl"),
                      ("guideRow", "guideUrl")):  # fmt: skip
        assert re.search(rf'<div class="copyrow" id="{row}">.*?<code id="{code}">', html)
    assert '<span id="mediaAccess" class="small">' in html
    assert '<span id="encoding" class="small">' in html
    assert '<span id="guideState" class="small">' in html


# The Setup tab: each place's section ------------------------------------------------


def place(name: str, status: dict, **opts) -> dict:
    return node(
        f"const n = placeSection({json.dumps(name)}, status, {json.dumps(opts)});"
        "return { text: textOf(n), chip: chipOf(n), heading: textOf(find(n, x => x.tag === 'h3')) };",
        status,
    )


def status_with(plex_configured: bool = True, **guide) -> dict:
    return {
        "tunerUrl": "http://10.0.0.5:3310", "xmltvUrl": "http://10.0.0.5:3310/xmltv.xml",
        "m3uUrl": "http://10.0.0.5:3310/stations.m3u", "guideUrl": "http://10.0.0.5:3310/guide.xml",
        "plex": {"configured": plex_configured}, "away": {"on": False},
        "guide": {"plexDownloadedGuide": None, "canRefreshPlexGuide": False, "downloads": {},
                  **guide},
    }  # fmt: skip


def now_ms() -> int:
    return int(node("return Date.now();"))


def test_plex_set_up_and_in_plex():
    got = place("plex", status_with(True, plexDownloadedGuide=now_ms() - HOUR,
                                     canRefreshPlexGuide=True))  # fmt: skip
    assert got["heading"] == "Adding tapiOca to Plex"
    assert got["chip"][1] == "In Plex" and "good" in got["chip"][0]
    assert "When a station changes, tapiOca asks Plex to refresh the guide." in got["text"]
    assert "Settings → Live TV & DVR → Set Up Plex DVR" in got["text"]
    assert "Scan for channels" in got["text"]
    assert "Watching in Plex needs Plex Pass on the account that owns your Plex server." in got["text"]


def test_plex_set_up_but_not_added():
    got = place("plex", status_with(True))
    assert got["chip"][1] == "Not added yet" and "accent" in got["chip"][0]
    assert got["text"].count("Plex hasn’t downloaded the guide yet.") == 1


@pytest.mark.parametrize(
    ("ago", "chip"),
    [
        (3 * HOUR, ["good", "Downloaded the guide 3 hr ago"]),
        (5 * DAY, ["accent", "Last downloaded the guide 5 days ago"]),
        (None, ["accent", "Not added yet"]),
    ],
)
def test_plex_as_a_place_without_plex_url(ago, chip):
    when = None if ago is None else now_ms() - ago
    got = place("plex", status_with(False, plexDownloadedGuide=when))
    assert got["chip"] == chip
    first = "Plex hasn’t downloaded the guide yet." if ago is None else "Plex last downloaded the guide on "
    assert first in got["text"]
    assert (
        "With PLEX_URL and PLEX_TOKEN set, tapiOca also asks Plex to refresh its guide when a "
        "station changes. Until then, refresh it in Plex after you change a station: Settings → "
        "Live TV & DVR → your tuner → Refresh Guide." in got["text"]
    )
    # (Never that tapiOca keeps Plex's guide up to date: it can't.)
    assert "tapiOca keeps the Plex guide up to date" not in got["text"]
    assert "Watching in Plex needs Plex Pass on the account that owns your Plex server." in got["text"]


@pytest.mark.parametrize(
    ("app", "name", "guide_line", "also"),
    [
        ("jellyfin", "Jellyfin",
         "Jellyfin downloads the guide on its own schedule, about once a day. After you change a "
         "station, refresh it in Jellyfin: Dashboard → Scheduled Tasks → Refresh Guide.",
         "Leave Jellyfin’s limit on simultaneous streams at its default (no limit). tapiOca "
         "enforces its own."),
        ("emby", "Emby",
         "Emby downloads the guide on its own schedule, about once a day. After you change a "
         "station, refresh the guide in Emby to see it right away.",
         "Emby’s Live TV needs Emby Premiere."),
        ("kodi", "Kodi",
         "Kodi downloads the guide on its own schedule, about once a day. After you change a "
         "station, refresh the guide in Kodi to see it right away.",
         "PVR Simple Client"),
    ],
)  # fmt: skip
def test_jellyfin_emby_and_kodi(app, name, guide_line, also):
    recent = place(app, status_with(downloads={app: now_ms() - 3 * HOUR}))
    assert recent["heading"] == f"Adding tapiOca to {name}"
    assert recent["chip"] == ["good", "Downloaded the guide 3 hr ago"]
    assert guide_line in recent["text"] and also in recent["text"]
    assert "the playlist address" in recent["text"]
    assert "as far as tapiOca can tell" not in recent["text"]
    older = place(app, status_with(downloads={app: now_ms() - 5 * DAY}))
    assert older["chip"] == ["accent", "Last downloaded the guide 5 days ago"]
    never = place(app, status_with())
    assert never["chip"] == ["plain", "Not seen yet"]
    assert (
        f"{name} hasn’t downloaded the guide yet, as far as tapiOca can tell: it knows each app "
        "by the name it gives." in never["text"]
    )
    # (Another app's download doesn't count for this one.)
    other = place(app, status_with(downloads={"other": now_ms() - HOUR}))
    assert other["chip"] == ["plain", "Not seen yet"]


def test_other_apps():
    got = place("other", status_with(downloads={"other": now_ms() - HOUR}))
    assert got["heading"] == "Other apps"
    assert got["chip"] == ["good", "Downloaded the guide 1 hr ago"]
    assert (
        "Other apps download the guide on their own schedule, about once a day. After you change "
        "a station, refresh the guide in the app to see it right away." in got["text"]
    )
    assert "Channels DVR and VLC accept the playlist address above." in got["text"]
    never = place("other", status_with())
    assert (
        "No other app has downloaded the guide yet, as far as tapiOca can tell: it knows each app "
        "by the name it gives." in never["text"]
    )


def test_tapiocas_apps():
    got = place("tapioca", status_with())
    assert got["heading"] == "tapiOca’s apps"
    assert got["chip"] is None
    assert "In the app, enter this server’s address: http://10.0.0.5:3310." in got["text"]
    assert "Away from home: Off." in got["text"]
    assert "Signing in, Away from home and Media in the apps are on the Access tab." in got["text"]


def test_in_the_setup_each_place_has_its_addresses():
    """In the setup, there's no copy panel above: each place has its own."""
    plex = place("plex", status_with(), inSetup=True)
    assert "Tuner address" in plex["text"] and "http://10.0.0.5:3310/xmltv.xml" in plex["text"]
    assert "Then choose Check again here." in plex["text"]
    emby = place("emby", status_with(), inSetup=True)
    assert "http://10.0.0.5:3310/stations.m3u" in emby["text"]
    assert "http://10.0.0.5:3310/guide.xml" in emby["text"]
    # On the Setup tab, they're in the panel above; under More ways to
    # watch (not chosen, so not in that panel), each has its own.
    assert "http://10.0.0.5:3310/stations.m3u" not in place("emby", status_with())["text"]
    assert "http://10.0.0.5:3310/stations.m3u" in place("emby", status_with(), addresses=True)["text"]
    assert "http://10.0.0.5:3310/xmltv.xml" in place("plex", status_with(), addresses=True)["text"]
    # Before the status has come (the setup opens at once): no chip, still the steps.
    early = node(
        "const n = placeSection('jellyfin', null, { inSetup: true, urls: { tuner: 'http://t' } });"
        "return [chipOf(n), textOf(n)];"
    )
    assert early[0] is None and "http://t/stations.m3u" in early[1]


def test_no_place_says_channel_or_library():
    for name in ("tapioca", "plex", "jellyfin", "emby", "kodi", "other"):
        text = place(name, status_with(), inSetup=True)["text"]
        cleaned = text
        for allowed in ("Scan for channels", "calls them channels", "Channels DVR"):  # (wording_allowed.txt)
            cleaned = cleaned.replace(allowed, "")
        assert not re.search(r"\bchannels?\b", cleaned, re.I), name
        assert not re.search(r"\blibrar(y|ies)\b", cleaned, re.I), name


# The Media files line, with Media folders of your own --------------------------------

DIRECT = json.dumps({"direct": 12, "viaPlex": 0, "mappings": [], "mediaDir": "/media",
                     "mediaDirPresent": True})  # fmt: skip


def media_line(call: str, status: dict | None = None) -> str:
    return node(f"{call}; return textOf($('#mediaAccess'));", status)


def test_media_files_with_your_own_folders():
    assert media_line(f"renderMediaAccess({DIRECT}, false, {{count: 3, missing: 0}})") == (
        "Read directly from disk. tapiOca reads your 3 Media folders from /media."
    )
    assert media_line(f"renderMediaAccess({DIRECT}, true, {{count: 1, missing: 1}})") == (
        "Read directly from disk. tapiOca reads your 1 Media folder from /media. "
        "1 can’t be read now: see Your own folders, below."
    )
    # None: as before.
    assert media_line(f"renderMediaAccess({DIRECT}, true, {{count: 0, missing: 0}})") == (
        "Read directly from disk."
    )


def test_media_files_two_arguments_as_136():
    """status.js's call (two arguments): the line as 1.36.0 says it until an
    Admin has chosen, then with the status's folders."""
    call = f"renderMediaAccess({DIRECT}, false)"
    folders = {"count": 2, "missing": 0}
    assert media_line(call) == "Read directly from disk."
    assert media_line(call, {"uses": {"saved": False}, "folders": folders}) == (
        "Read directly from disk."
    )
    assert media_line(call, {"uses": {"saved": True}, "folders": folders}) == (
        "Read directly from disk. tapiOca reads your 2 Media folders from /media."
    )
    status = (JS / "status.js").read_text(encoding="utf-8")
    assert "renderMediaAccess(status.mediaAccess, plexUsed);" in status


# The page's static parts, by the choices (data-when) ---------------------------------


class _Whens:
    def __init__(self, html: str) -> None:
        self.found = re.findall(r'<(\w+) data-when="([^"]+)"[^>]*>(.*?)</\1>', html, re.S)

    def holding(self, words: str) -> list[str]:
        return [when for _, when, inner in self.found if words in inner]


def test_each_part_shown_by_the_choices_says_when():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    whens = _Whens(html)
    assert whens.holding(" or from Plex") == ["plex"]
    assert whens.holding("when Plex has it again under a new ID") == ["plex"]
    assert whens.holding("For Plex, tapiOca asks Plex every 30 seconds") == ["plex watch-plex"]
    # Every token is one core.js knows.
    core = (JS / "core.js").read_text(encoding="utf-8")
    for _, when, _ in whens.found:
        for token in when.split():
            assert f"{token}: () =>" in core or f"'{token}': () =>" in core, token


def test_the_sentences_read_whole_with_the_parts_hidden():
    """What's left when a data-when part is hidden still reads as a sentence."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    shown = re.sub(r'<(\w+) data-when="[^"]+"[^>]*>.*?</\1>', "", html, flags=re.S)
    assert "are gone from disk while a station or Media still has them." in shown
    assert "a program comes off the list when it’s missing and neither a station nor Media" in shown
    assert "stations and Media alike. Viewing in other apps" in shown


def test_generic_sentences_name_no_source():
    """(H1) What any source does is said without Plex's name."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for gone in (
        "what’s in your Plex",
        "each Plex collection you pick",
        "From Plex collections",
        "Programs back in Plex",
        "a show’s logo from Plex",
        "uploaded or from Plex",
        "Use the logo from Plex",
        "audience rating in Plex",
        "Stations from Plex collections",
        "added to the collection in Plex",
        "stays in sync with Plex",
        "the streams Plex asks it for",
    ):
        assert gone not in html, gone
    folders = (JS / "folders.js").read_text(encoding="utf-8")
    assert "'None yet. Add one to use your own folders.'" in folders
    # (Plex's own button names stay where they're Plex's.)
    assert "Scan for channels" in (JS / "addtoplex.js").read_text(encoding="utf-8")


def test_the_access_footer_keeps_its_literal_and_says_it_by_the_choices():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<p class="muted small" id="neverSignIn">Plex, Jellyfin and other apps never sign in,' in html
    tab = (JS / "addtoplex.js").read_text(encoding="utf-8")
    said = _function(tab, "whoNeverSignsIn")
    code = said + "return [null, ['tapioca'], ['plex'], ['plex', 'jellyfin'], ['other'], ['emby', 'other']].map(w => whoNeverSignsIn(w));"
    assert node(code) == [
        "Plex, Jellyfin and other apps never sign in,",
        "Apps other than tapiOca’s never sign in,",
        "Plex never signs in,",
        "Plex and Jellyfin never sign in,",
        "Other apps never sign in,",
        "Emby and other apps never sign in,",
    ]
