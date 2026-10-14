"""The page's wording, by what an Admin chose under What you use (1.37.0),
run in Node with stand-ins. Facts stay; names follow the choices: an app
is named where it's chosen, a sentence about what isn't protected or
limited keeps its fact for every choice ("apps other than tapiOca's" when
no other app is chosen), and a sentence that named Plex for what any
source does loses the name. Until an Admin saves the choices, each
sentence is 1.36.0's, word for word."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "app" / "web" / "js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

# A stand-in for the page's h(): an element as its tag around its text.
H = (
    "const h = (tag, attrs, ...kids) => "
    "`<${tag}>${kids.flat().filter(k => k != null && k !== false).join('')}</${tag}>`;"
)


def _js(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


def _fn(script: str, name: str) -> str:
    """A top-level function, from `function name(` to its closing brace."""
    a = script.index(f"function {name}(")
    return script[a : script.index("\n}\n", a) + 3]


def run(status: dict | None, code: str, fns: dict[str, list[str]] | None = None) -> object:
    core = _js("core.js")
    helpers = core[core.index("const noun = ") : core.index("\n}\n", core.index("function showForChoices(")) + 3]
    said = core[core.index("const upFirst = ") : core.index("\n}\n", core.index("function madeAppsSaid(")) + 3]
    extra = "\n".join(_fn(_js(f), n) for f, names in (fns or {}).items() for n in names)
    script = f"let status = {json.dumps(status)};\n{H}\n{helpers}\n{said}\n{extra}\n"
    script += f"console.log(JSON.stringify((() => {{ {code} }})()));"
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# What an Admin's status says (see main.py's status and uses.py) --------------
# Nothing saved: Plex set up, as most homes updating from 1.36.0 are.
UNSAVED = {
    "plexUsed": True, "plex": {"configured": True, "ok": True},
    "uses": {"sources": ["plex"], "watchIn": None, "saved": False},
}  # fmt: skip
# Nothing saved, in a home that doesn't use Plex (1.35.0's rule).
UNSAVED_NO_PLEX = {
    "plexUsed": False, "plex": {"configured": False},
    "uses": {"sources": ["folders"], "watchIn": None, "saved": False},
}  # fmt: skip
TAPIOCA, PLEX, EMBY, MANY = ["tapioca"], ["plex"], ["emby"], ["plex", "jellyfin", "other"]


def chose(watch_in, sources=("plex",)):
    plex = "plex" in sources
    return {"plexUsed": plex, "plex": {"configured": plex, "ok": plex},
            "uses": {"sources": list(sources), "watchIn": watch_in, "saved": True},
            "folders": {"count": int("folders" in sources), "missing": 0}}  # fmt: skip


def said_for(fns, call, cases):
    """Each case's sentence: [(status, expected)]."""
    for status, expected in cases:
        assert run(status, f"return {call};", fns) == expected, (status, call)


# core.js: madeNotice --------------------------------------------------------
SCAN = (
    "go to <em>Settings → Live TV & DVR → your tuner → Scan for channels</em> in Plex "
    "(Plex calls stations “channels”)."
)


@needs_node
def test_made_notice_names_the_apps_chosen():
    call = "madeAppsSaid({one}, {admin}).join('')"
    one, many = call.format(one="true", admin="true"), call.format(one="false", admin="true")
    user = call.format(one="false", admin="false")
    said_for({}, one, [
        (UNSAVED, f"Watching in Plex? To add it, {SCAN} Other apps show new stations once they "
                  "refresh their guide. Tuner integration, on the Setup tab, shows how to add "
                  "tapiOca to each."),
        # (A User's status has no choices in it: 1.36.0's words.)
        ({"plex": {"used": True}}, f"Watching in Plex? To add it, {SCAN} Other apps show new "
                                   "stations once they refresh their guide. Tuner integration, "
                                   "on the Setup tab, shows how to add tapiOca to each."),
        (chose(TAPIOCA), ""),
        (chose(PLEX), f"Watching in Plex? To add it, {SCAN} Tuner integration, on the Setup "
                      "tab, shows how to add tapiOca to Plex."),
        (chose(EMBY, ("folders",)), "Emby shows new stations once it refreshes its guide. Tuner "
                                    "integration, on the Setup tab, shows how to add tapiOca to "
                                    "Emby."),
    ])  # fmt: skip
    said_for({}, many, [
        (chose(MANY, ("plex", "folders")), f"Watching in Plex? To add them, {SCAN} Jellyfin and "
                                           "other apps show new stations once they refresh their "
                                           "guide. Tuner integration, on the Setup tab, shows how "
                                           "to add tapiOca to each."),
        (chose(["other"]), "Other apps show new stations once they refresh their guide. Tuner "
                           "integration, on the Setup tab, shows how to add tapiOca to each."),
    ])  # fmt: skip
    # The Setup tab's pointer is for Admins.
    said_for({}, user, [
        (chose(MANY), f"Watching in Plex? To add them, {SCAN} Jellyfin and other apps show new "
                      "stations once they refresh their guide."),
        (chose(TAPIOCA), ""),
    ])  # fmt: skip
    # (tests/test_setup_tab.py pins this, and madeNotice leaves out an empty line.)
    core = _js("core.js")
    assert "Watching in Plex? To add " in core
    made = _fn(core, "madeNotice")
    assert "madeAppsSaid(one, isAdmin())" in made and "said.length ? h('p'" in made


# stations.js ------------------------------------------------------------------
@needs_node
def test_a_station_off_the_air_says_why_by_the_source():
    fns = {"stations.js": ["offAirWhy"]}
    plex = ("nothing on it could play just now, usually because Plex or your media can’t be "
            "reached, so viewers see the off-air card (an Admin can see why on the Logs tab)")
    no_plex = plex.replace("Plex or your media", "your media")
    said_for(fns, "offAirWhy()", [
        (UNSAVED, plex), (UNSAVED_NO_PLEX, no_plex), ({"plex": {"used": False}}, no_plex),
        (chose(PLEX), plex), (chose(TAPIOCA, ("folders",)), no_plex),
        (chose(EMBY, ("plex", "folders")), plex),
    ])  # fmt: skip


@needs_node
def test_a_change_says_which_guides_to_refresh():
    fns = {"stations.js": ["changedMessage"]}
    call = "changedMessage({ name: 'Classics', changed: true })"
    refreshed = "changedMessage({ name: 'Classics', changed: true, plexGuideRefreshed: true })"
    said_for(fns, call, [
        (UNSAVED, "Classics changes shortly. Refresh the guide in Plex so it matches."),
        (UNSAVED_NO_PLEX, "Classics changes shortly. Apps that downloaded the guide show the "
                          "change once they refresh it."),
        (chose(TAPIOCA), "Classics changes shortly."),
        (chose(TAPIOCA, ("folders",)), "Classics changes shortly."),
        (chose(PLEX), "Classics changes shortly. Refresh the guide in Plex so it matches."),
        (chose(EMBY), "Classics changes shortly. Emby shows the change once it refreshes its "
                      "guide."),
        (chose(MANY, ("plex", "folders")), "Classics changes shortly. Refresh the guide in Plex "
                                           "so it matches. Jellyfin and other apps show the "
                                           "change once they refresh their guide."),
    ])  # fmt: skip
    said_for(fns, refreshed, [
        (UNSAVED, "Classics changes shortly. The Plex guide is being refreshed."),
        (chose(PLEX), "Classics changes shortly. The Plex guide is being refreshed."),
        (chose(MANY), "Classics changes shortly. The Plex guide is being refreshed. Jellyfin and "
                      "other apps show the change once they refresh their guide."),
        (chose(TAPIOCA), "Classics changes shortly."),
    ])  # fmt: skip


def test_picture_sizes_arent_said_to_be_plexs():
    stations = _js("stations.js")
    assert "according to Plex" not in stations
    assert "`Picture sizes of the program files: ${sizes}. The station plays them all" in stations


# status.js --------------------------------------------------------------------
@needs_node
def test_the_live_pills_tooltip():
    fns = {"status.js": ["livePillTitle"]}
    start = ("Stations being watched right now, and how many connections there are. Each "
             "station uses one tuner (tapiOca has 2 tuners), no matter how many people watch it")
    full = " Every tuner is in use, so anyone tuning in to another station sees a card saying so."
    said_for(fns, "livePillTitle(2, false)", [
        (UNSAVED, f"{start} in Plex or another app."),
        (UNSAVED_NO_PLEX, f"{start} in Plex or another app."),
        (chose(TAPIOCA), f"{start}, in any app."), (chose(PLEX), f"{start}, in any app."),
        (chose(EMBY), f"{start}, in any app."), (chose(MANY), f"{start}, in any app."),
    ])  # fmt: skip
    said_for(fns, "livePillTitle(2, true)", [
        (UNSAVED, f"{start} in Plex or another app.{full}"), (chose(EMBY), f"{start}, in any app.{full}"),
    ])  # fmt: skip


@needs_node
def test_the_tuners_hint():
    fns = {"status.js": ["tunersHint"]}
    shared = (" Everyone watching the same station shares one stream, so a station uses one "
              "tuner no matter how many people watch it. When every tuner is in use, anyone "
              "tuning in to another station sees a card saying so.")
    plex = (" (tapiOca tells Plex it has 6 tuners so that Plex lets it show that card. If you "
            "raise this number and Plex still won’t play more, restart Plex.)")
    old = f"Up to 3 stations can play at once, across Plex and all other apps.{shared}{plex}"
    new = f"Up to 3 stations can play at once, across every app.{shared}"
    said_for(fns, "tunersHint(3)", [
        (UNSAVED, old), (UNSAVED_NO_PLEX, old), (chose(TAPIOCA), new), (chose(PLEX), new + plex),
        (chose(EMBY, ("plex", "folders")), new), (chose(MANY), new + plex),
    ])  # fmt: skip


@needs_node
def test_the_hdr_hint_names_plex_only_where_its_watched():
    fns = {"status.js": ["hdrHint"]}
    old = ("4K plays at the station’s picture size (1080p at most), and HDR is converted to "
           "standard color so it doesn’t look washed out. A station must play everything in its "
           "one format to run without glitches. Streaming in 4K HDR would need a GPU fast enough "
           "to convert everything in real time and about 20 Mbps per viewer, and Plex Live TV "
           "isn’t known to pass HDR through to the TV. (Plex still struggles with ATSC 3.0, the "
           "broadcast standard that brings HEVC and HDR from real tuners.) So, for stability, "
           "stations play at up to 1080p in standard color. Dolby Vision profile 5 files can’t "
           "play correctly without a Dolby Vision player, so they’re left out and listed on the "
           "Broken files tab.")
    new = old.replace(", and Plex Live TV isn’t known to pass HDR through to the TV. (Plex still "
                      "struggles with ATSC 3.0, the broadcast standard that brings HEVC and HDR "
                      "from real tuners.)", ".")
    assert new != old
    said_for(fns, "hdrHint()", [
        (UNSAVED, old), (UNSAVED_NO_PLEX, old), (chose(TAPIOCA), new), (chose(PLEX), old),
        (chose(EMBY), new), (chose(MANY), old),
    ])  # fmt: skip


# apps.js ----------------------------------------------------------------------
@needs_node
def test_block_stations_for_some_plex_users_shows_where_it_can_work():
    fns = {"apps.js": ["limitsPanelShown"]}
    said_for(fns, "limitsPanelShown(false)", [
        (UNSAVED, True), (UNSAVED_NO_PLEX, True), (chose(TAPIOCA), False), (chose(PLEX), True),
        (chose(EMBY), False), (chose(MANY), True),
        # Plex chosen as a place, but PLEX_URL isn't set: it can't work yet.
        (chose(PLEX, ("folders",)), False),
    ])  # fmt: skip
    # On already: always shown, so it can be turned off.
    said_for(fns, "limitsPanelShown(true)", [(chose(TAPIOCA), True), (chose(EMBY, ("folders",)), True)])
    limits = _fn(_js("apps.js"), "loadLimits")
    assert "$('#limitsPanel').hidden = !limitsPanelShown(got.on);" in limits
    assert "$('#limitsPanel').hidden = !limitsPanelShown(false);" in limits


@needs_node
def test_the_access_tabs_sentences_keep_their_facts():
    fns = {"apps.js": ["tunerIntro", "awayOthers", "appLimitsOthers", "othersUnchanged"]}
    streams = ": the tuner itself, the guide, the list of stations and the stations’ streams."
    said_for(fns, "tunerIntro()", [
        (UNSAVED, f"The tuner is what Plex, Jellyfin and other apps use{streams} These apps can’t sign in."),
        (chose(TAPIOCA), f"The tuner is what apps other than tapiOca’s use{streams} These apps can’t sign in."),
        (chose(PLEX), f"The tuner is what Plex uses{streams} Plex can’t sign in."),
        (chose(EMBY), f"The tuner is what Emby uses{streams} Emby can’t sign in."),
        (chose(MANY), f"The tuner is what Plex, Jellyfin and other apps use{streams} These apps can’t sign in."),
        (chose(["other"]), f"The tuner is what other apps use{streams} These apps can’t sign in."),
    ])  # fmt: skip
    home = "on your home network only."
    said_for(fns, "awayOthers()", [
        (UNSAVED, f"Plex, Jellyfin and other apps don’t change: they use tapiOca {home}"),
        (chose(TAPIOCA), f"Apps other than tapiOca’s don’t change: they use tapiOca {home}"),
        (chose(PLEX), f"Plex doesn’t change: it uses tapiOca {home}"),
        (chose(EMBY), f"Emby doesn’t change: it uses tapiOca {home}"),
        (chose(MANY), f"Plex, Jellyfin and other apps don’t change: they use tapiOca {home}"),
    ])  # fmt: skip
    said_for(fns, "appLimitsOthers()", [
        (UNSAVED, "Plex, Jellyfin and other apps aren’t counted here: they have limits of their "
                  "own, and the tuners cover them."),
        (chose(TAPIOCA), "Apps other than tapiOca’s aren’t counted here: they have limits of "
                         "their own, and the tuners cover them."),
        (chose(PLEX), "Plex isn’t counted here: it has limits of its own, and the tuners cover it."),
        (chose(EMBY), "Emby isn’t counted here: it has limits of its own, and the tuners cover it."),
        (chose(MANY), "Plex, Jellyfin and other apps aren’t counted here: they have limits of "
                      "their own, and the tuners cover them."),
    ])  # fmt: skip
    said_for(fns, "othersUnchanged()", [
        (UNSAVED, "Stations don’t change, and neither do Plex, Jellyfin or other apps."),
        (chose(TAPIOCA), "Stations don’t change, and neither do apps other than tapiOca’s."),
        (chose(PLEX), "Stations don’t change, and neither does Plex."),
        (chose(EMBY), "Stations don’t change, and neither does Emby."),
        (chose(MANY), "Stations don’t change, and neither do Plex, Jellyfin or other apps."),
    ])  # fmt: skip
    apps = _js("apps.js")
    assert apps.count("othersUnchanged()") == 4  # (the function, and its three sentences)
    for sentence in ("tunerIntro()", "awayOthers()", "appLimitsOthers()"):
        assert apps.count(sentence) == 2, sentence
    assert "neither do Plex, Jellyfin or other apps.'" not in apps.replace(
        _fn(apps, "othersUnchanged"), ""
    )


@needs_node
def test_the_alerts_intro_without_plex():
    fns = {"apps.js": ["alertsIntro"]}
    old = ("tapiOca says when something needs a look: Plex can’t be reached, the data folder is "
           "nearly full or can’t be written to, a station keeps failing to start, backups fail, "
           "the clock is badly off, or tapiOca’s apps can’t reach it from outside.")
    new = ("tapiOca says when something needs a look: the data folder is nearly full or can’t "
           "be written to, a station keeps failing to start, backups fail, or tapiOca’s apps "
           "can’t reach it from outside.")
    said_for(fns, "alertsIntro()", [
        (UNSAVED, old), (UNSAVED_NO_PLEX, new), (chose(TAPIOCA), old), (chose(EMBY), old),
        (chose(TAPIOCA, ("folders",)), new), (chose(MANY, ("plex", "folders")), old),
    ])  # fmt: skip


@needs_node
def test_api_tokens_update_a_station_now():
    fns = {"apps.js": ["tokensIntro"]}
    start = ("API tokens let your own scripts, home automation (such as Home Assistant) and "
             "other players use tapiOca’s API: its stations, guide and streams, and how it’s "
             "doing. An Admin token can also update a station now, check a station’s files, ")
    end = " The README’s “tapiOca’s API” section explains how, and docs/api.md lists every address."
    plex = f"{start}refresh Plex’s guide and make a backup.{end}"
    no_plex = f"{start[:-2]} and make a backup.{end}"
    said_for(fns, "tokensIntro()", [
        (UNSAVED, plex), (UNSAVED_NO_PLEX, plex), (chose(TAPIOCA), no_plex), (chose(PLEX), plex),
        (chose(EMBY), no_plex), (chose(MANY), plex), (chose(PLEX, ("folders",)), no_plex),
    ])  # fmt: skip
    assert "update a station from Plex" not in _js("apps.js")


# viewing.js -------------------------------------------------------------------
@needs_node
def test_viewing_levels_say_what_other_apps_show():
    fns = {"viewing.js": ["othersNote"]}
    block = " To keep stations from some people in Plex, use Block stations for some Plex users, below."
    said_for(fns, "othersNote()", [
        (UNSAVED, ["Plex and other apps. ", "Plex, Jellyfin and other apps don’t say who’s "
                   "watching, so they show every station." + block]),
        (UNSAVED_NO_PLEX, ["Plex and other apps. ", "Plex, Jellyfin and other apps don’t say "
                           "who’s watching, so they show every station." + block]),
        (chose(TAPIOCA), ["Other apps. ", "Apps other than tapiOca’s don’t say who’s watching, "
                          "so they show every station."]),
        (chose(PLEX), ["Other apps. ", "Plex doesn’t say who’s watching, so it shows every "
                       "station." + block]),
        (chose(PLEX, ("folders",)), ["Other apps. ", "Plex doesn’t say who’s watching, so it "
                                     "shows every station."]),
        (chose(EMBY), ["Other apps. ", "Emby doesn’t say who’s watching, so it shows every station."]),
        (chose(MANY), ["Other apps. ", "Plex, Jellyfin and other apps don’t say who’s watching, "
                       "so they show every station." + block]),
    ])  # fmt: skip


@needs_node
def test_plex_calls_these_labels_only_with_plex():
    fns = {"viewing.js": ["labelsNote"]}
    said_for(fns, "labelsNote()", [
        (UNSAVED, "Plex calls these labels"), (UNSAVED_NO_PLEX, ""), (chose(TAPIOCA), "Plex calls these labels"),
        (chose(EMBY, ("folders",)), ""), (chose(MANY, ("plex", "folders")), "Plex calls these labels"),
    ])  # fmt: skip
    viewing = _js("viewing.js")
    assert viewing.count("labelsNote()") == 5  # (the function, and twice in each of two places)
    assert "'Plex calls these labels.'" not in viewing


@needs_node
def test_trusted_networks_say_what_other_apps_use():
    fns = {"trusted.js": ["trustedOthers"]}
    said_for(fns, "trustedOthers()", [
        (UNSAVED, "Plex, Jellyfin and other apps use Tuner access."),
        (chose(TAPIOCA), "Apps other than tapiOca’s use Tuner access."),
        (chose(PLEX), "Plex uses Tuner access."), (chose(EMBY), "Emby uses Tuner access."),
        (chose(MANY), "Plex, Jellyfin and other apps use Tuner access."),
    ])  # fmt: skip
    assert "(1.36.0 and later) and on this page. ', trustedOthers())" in _js("trusted.js")


# broken.js --------------------------------------------------------------------
@needs_node
def test_broken_files_by_the_source():
    fns = {"broken.js": ["missingFileWhere", "wrongTitleFix"]}
    said_for(fns, "missingFileWhere()", [
        (UNSAVED, "(gone from disk or from Plex while a station or Media still has it): the app "
                  "first checks what’s on disk, then searches for it."),
        (UNSAVED_NO_PLEX, "(gone from disk while a station or Media still has it): the app first "
                          "checks what’s on disk, then searches for it."),
        (chose(EMBY), "(gone from disk or from Plex while a station or Media still has it): the "
                      "app first checks what’s on disk, then searches for it."),
        (chose(EMBY, ("folders",)), "(gone from disk while a station or Media still has it): the "
                                    "app first checks what’s on disk, then searches for it."),
    ])  # fmt: skip
    said_for(fns, "wrongTitleFix()", [
        (UNSAVED, "fix it in Plex, then dismiss it."),
        # (Nothing saved: 1.36.0's words, even with folders of its own.)
        ({**UNSAVED, "uses": {"sources": ["plex", "folders"], "watchIn": None, "saved": False}},
         "fix it in Plex, then dismiss it."),
        (UNSAVED_NO_PLEX, "fix its NFO file or name, then dismiss it."),
        (chose(TAPIOCA), "fix it in Plex, then dismiss it."),
        (chose(TAPIOCA, ("folders",)), "fix its NFO file or name, then dismiss it."),
        (chose(MANY, ("plex", "folders")), "fix it in Plex, or in the NFO file beside it for "
                                           "your own Media folders, then dismiss it."),
    ])  # fmt: skip


# editor.js --------------------------------------------------------------------
@needs_node
def test_skipping_intros_by_the_source():
    fns = {"editor.js": ["skipHint"]}
    plex = ("Skips intros and end credits wherever Plex has found them, like Skip Intro and Skip "
            "Credits in Plex, so the next program starts right away. Anything before the intro "
            "still plays, and so does a scene after the credits. Programs Plex hasn’t marked, "
            "and those in your own Media folders, play in full.")
    no_plex = ("Skips intros and end credits where tapiOca knows where they are. Programs from "
               "your own Media folders play in full for now.")
    said_for(fns, "skipHint(true)", [
        (UNSAVED, plex), (UNSAVED_NO_PLEX, no_plex), (chose(TAPIOCA), plex),
        (chose(EMBY, ("folders",)), no_plex), (chose(MANY, ("plex", "folders")), plex),
    ])  # fmt: skip
    said_for(fns, "skipHint(false)", [(UNSAVED, "Programs play in full."), (chose(EMBY, ("folders",)), "Programs play in full.")])
    assert "$('#skipHint').textContent = skipHint(on);" in _js("editor.js")


@needs_node
def test_commercials_and_trailers_hint_by_the_source():
    fns = {"editor.js": ["breaksHintText"]}
    start = ("Commercials play after episodes and trailers after movies, within each program’s "
             "time slot in the guide. Found 0 commercials and 0 trailers. To add some, make a "
             "folder named commercials at the top of your TV shows’ Media folder and one named "
             "trailers at the top of your movies’ Media folder (both lowercase).")
    plex = (" Put a .plexignore file containing * in each, so Plex doesn’t add them to your "
            "Media folders.")
    fillers = {"fillers": {"commercials": 0, "trailers": 0}}
    said_for(fns, "breaksHintText()", [
        ({**UNSAVED, **fillers}, start + plex),
        ({**UNSAVED_NO_PLEX, **fillers}, start + plex),  # (nothing saved: 1.36.0's words)
        ({**chose(EMBY), **fillers}, start + plex),
        ({**chose(MANY, ("plex", "folders")), **fillers}, start + plex),
        ({**chose(TAPIOCA, ("folders",)), **fillers}, start),
        ({**chose(EMBY, ("folders",)), **fillers}, start),
    ])  # fmt: skip


@needs_node
def test_the_media_list_says_what_it_cant_reach():
    fns = {"editor.js": ["cantListMedia"]}
    said_for(fns, "cantListMedia()", [
        (UNSAVED, "Can’t reach Plex"), (UNSAVED_NO_PLEX, "Can’t list your Media folders"),
        (chose(EMBY, ("folders",)), "Can’t list your Media folders"), (chose(TAPIOCA), "Can’t reach Plex"),
    ])  # fmt: skip
    assert "h('option', {}, cantListMedia())" in _js("editor.js")


# Sentences that named Plex for what any source does: the name goes -----------
GONE_AND_SAID = {
    "viewing.js": [
        ("' — not in Plex now: find it again'", "' — gone now: find it again'"),
        ("'Plex can’t be reached right now. Try again in a moment.'",
         "'Searching didn’t work just now. Try again in a moment.'"),
        ("'Titles with no rating in Plex.'", "'Titles with no rating.'"),
    ],
    "updates.js": [
        ("in Plex too, so it never shows",
         "Everyone who can watch your stations sees it, in every app, so it never shows your "
         "server’s addresses or how it’s doing. It plays even without any Media folders, so every "
         "app has a station to find when you add tapiOca to it.');"),
    ],
    "checking.js": [
        ("Changes in Plex are checked every half hour.",
         "whenever you choose Check the list again. It’s also checked against your Media folders "
         "every half hour.`"),
    ],
    "broken.js": [
        ("tapiOca itself only needs Plex;",
         "tapiOca itself doesn’t need Sonarr or Radarr; this just uses apps you already have."),
    ],
    "logos.js": [
        ("`The logo Plex has for ${offered.title}`", "`The logo for ${offered.title}`"),
    ],
    "editor.js": [
        ("tapiOca keeps checking Plex for matches",
         "'A filter. tapiOca keeps checking for matches, and new matches are added automatically. "
         "Click to change it.'"),
        ("'A Plex collection. Anything added to it in Plex joins the station automatically.'",
         "'A collection. Anything added to it joins the station automatically.'"),
    ],
    "filter.js": [
        ("`Plex has no ${flt.kind === 'show' ? 'TV' : 'movie'} Media folders.`",
         "`There are no ${flt.kind === 'show' ? 'TV' : 'movie'} Media folders yet.`"),
        ("'Episodes added to Plex in that time,",
         "'Episodes added in that time, from any matching show (e.g., 30 for a New Arrivals "
         "station).'"),
        ("'Movies added to Plex in that time", "'Movies added in that time (e.g., 30 for a New "
                                               "Arrivals station).'"),
        ("'Checking Plex…'", "'Counting…'"),
        ("'Filter added. New matches in Plex join the station automatically.'",
         "'Filter added. New matches join the station automatically.'"),
        ("Couldn’t add the logo from Plex",
         "`Couldn’t add the title’s logo (${err.message}). Choose another logo.`"),
        ("'Building the schedule from Plex…'", "'Building the schedule…'"),
    ],
    "smart.js": [
        ("'Plex has no collections in your TV or movie Media folders.'",
         "'There are no collections in your TV or movie Media folders.'"),
        ("'Getting collections from Plex…'", "'Getting collections…'"),
        ("'Building the schedules from Plex…'", "'Building the schedules…'"),
        ("'Checking Plex…'", "renderSmart('Counting…');"),
        ("stations`} from Plex…`", "stations`}…`"),
    ],
}


@pytest.mark.parametrize("name", sorted(GONE_AND_SAID))
def test_generic_sentences_lose_plexs_name(name):
    script = _js(name)
    for gone, said in GONE_AND_SAID[name]:
        assert gone not in script, gone
        assert said in script, said
