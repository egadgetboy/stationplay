"""The setup's Tuner step (1.36.3, the owner: "I think maybe calling the
step Tuner is better"): where an Admin will watch their stations (Plex,
Jellyfin, Emby, Kodi, another app, or only tapiOca's own apps, more than
one allowed), kept server-side for Admins only, with Plex suggested until
it's answered; asked once after an update. And the step's page side, run
in Node with stand-ins for the page: the choices, what All set says, and
each app's steps."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import setup
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.plex import PlexClient
from app.updates import META_PLEX_DOWNLOAD

from .fakeplex import FakePlex
from .test_setup import make

JS = Path(__file__).resolve().parents[1] / "app" / "web" / "js"
URL = "/api/setup/watch-in"


def no_plex(tmp_path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path / "data"), PlexClient("", "")))


# The server ------------------------------------------------------------------------


def test_where_you_watch_round_trip(tmp_path, caplog):
    with make(tmp_path) as c:
        # (Plex is set up: it's suggested until there's an answer.)
        assert c.get(URL).json() == {"watchIn": None, "suggested": ["plex"]}
        with caplog.at_level(logging.INFO, logger="stationplay"):
            got = c.put(URL, json={"watchIn": ["jellyfin", "plex"]})
        assert got.status_code == 200, got.text
        # (Kept in the order the page lists them.)
        assert got.json() == {"watchIn": ["plex", "jellyfin"], "suggested": ["plex"]}
        assert c.get(URL).json()["watchIn"] == ["plex", "jellyfin"]
        assert "Where you watch changed: Plex, Jellyfin" in caplog.text
        # Both of them, and then just one: an Admin can watch in more than one.
        c.put(URL, json={"watchIn": ["kodi"]})
        assert c.get(URL).json()["watchIn"] == ["kodi"]
        c.put(URL, json={"watchIn": ["tapioca"]})
        assert c.get(URL).json()["watchIn"] == ["tapioca"]
        stored = c.app.state.ctx.db.get_meta(setup.META_WATCH_IN)
    assert json.loads(stored) == {"watchIn": ["tapioca"]}


def test_only_known_choices_are_kept(tmp_path):
    with make(tmp_path) as c:
        got = c.put(URL, json={"watchIn": ["kodi", "tivo", "kodi", "other"]})
        assert got.status_code == 200, got.text
        assert got.json()["watchIn"] == ["kodi", "other"]
        # (Saving it keeps what else the row holds: 1.37.0's draft reads it too.)
        db = c.app.state.ctx.db
        db.set_meta(setup.META_WATCH_IN, json.dumps({"sources": ["plex"], "watchIn": ["emby"]}))
        c.put(URL, json={"watchIn": ["jellyfin"]})
        assert json.loads(db.get_meta(setup.META_WATCH_IN)) == {
            "sources": ["plex"],
            "watchIn": ["jellyfin"],
        }
    # What's stored and can't be read, or isn't known, counts as no answer.
    db = Database(tmp_path / "db.sqlite")
    for stored in ("[not json", '"plex"', '{"watchIn": "plex"}', '{"watchIn": ["tivo"]}'):
        db.set_meta(setup.META_WATCH_IN, stored)
        assert setup.watch_in(db) is None, stored
    # (Only tapiOca's own apps is only on its own: stored with others, the others count.)
    db.set_meta(setup.META_WATCH_IN, json.dumps({"watchIn": ["tapioca", "plex"]}))
    assert setup.watch_in(db) == ["plex"]


def test_at_least_one_choice_is_needed(tmp_path):
    with make(tmp_path) as c:
        c.put(URL, json={"watchIn": ["plex"]})
        for chosen in ([], ["tivo"]):
            got = c.put(URL, json={"watchIn": chosen})
            assert got.status_code == 400
            assert got.json()["detail"] == "Choose at least one app, or Only tapiOca’s own apps."
        got = c.put(URL, json={"watchIn": ["tapioca", "jellyfin"]})
        assert got.status_code == 400
        assert got.json()["detail"] == (
            "Choose Only tapiOca’s own apps by itself, or the other apps you’ll use."
        )
        assert c.put(URL, json={}).status_code == 422
        assert c.put(URL, json={"watchIn": "plex"}).status_code == 422
        # (Nothing refused changes what's saved.)
        assert c.get(URL).json()["watchIn"] == ["plex"]


def test_where_you_watch_is_for_admins(tmp_path):
    with make(tmp_path) as c:
        # Signing in off, at home: whoever's there is as an Admin.
        assert c.get(URL).status_code == 200
        assert c.put(URL, json={"watchIn": ["emby"]}).status_code == 200
        c.post(
            "/api/access/users",
            json={"name": "Ada", "password": "correct horse", "role": "admin", "maxStations": None},
        )
        c.post(
            "/api/access/users",
            json={"name": "Bo", "password": "battery staple", "role": "user", "maxStations": None},
        )
        c.post("/api/access/sign-out")
        assert c.get(URL).status_code == 401
        assert c.put(URL, json={"watchIn": ["kodi"]}).status_code == 401
        c.post("/api/access/sign-in", json={"name": "Bo", "password": "battery staple"})
        assert c.get(URL).status_code == 403
        assert c.put(URL, json={"watchIn": ["kodi"]}).status_code == 403
        c.post("/api/access/sign-out")
        c.post("/api/access/sign-in", json={"name": "Ada", "password": "correct horse"})
        assert c.get(URL).json()["watchIn"] == ["emby"]
        assert c.put(URL, json={"watchIn": ["kodi"]}).status_code == 200
        # (A change needs the page's own header, as every change does: see access.PAGE_HEADER.)
        refused = c.put(URL, json={"watchIn": ["plex"]}, headers={"X-Tapioca-Page": ""})
        assert refused.status_code == 403
        assert c.get(URL).json()["watchIn"] == ["kodi"]


def test_plex_is_suggested_only_when_its_set_up_or_has_used_the_tuner(tmp_path):
    with no_plex(tmp_path / "a") as c:
        assert c.get(URL).json() == {"watchIn": None, "suggested": []}
        # Plex downloaded tapiOca's guide (with no PLEX_URL, it found the tuner by itself).
        c.app.state.ctx.db.set_meta(META_PLEX_DOWNLOAD, "1700000000000")
        assert c.get(URL).json()["suggested"] == ["plex"]
        # (The suggestion is only that: once saved, the answer is what's ticked.)
        c.put(URL, json={"watchIn": ["jellyfin"]})
        assert c.get(URL).json() == {"watchIn": ["jellyfin"], "suggested": ["plex"]}
    assert setup.suggested_watch_in(plex_set_up=True, plex_seen=False) == ["plex"]
    assert setup.suggested_watch_in(plex_set_up=False, plex_seen=True) == ["plex"]
    assert setup.suggested_watch_in(plex_set_up=False, plex_seen=False) == []


def test_the_tuner_step_is_asked_once_after_an_update(tmp_path):
    """An updated tapiOca (the step answered as 1.36.1's Plex step) asks it
    once: just it, then never again by itself."""
    assert setup.QUESTIONS["plex"] == 2
    db = Database(tmp_path / "db.sqlite")
    db.set_meta(setup.META_ANSWERED, json.dumps({**setup.QUESTIONS, "plex": 1}))
    setup.start(db, 3, False, False)
    assert setup.pending(db) == ["plex"]
    setup.mark(db, ["plex"])
    setup.start(db, 3, False, False)
    assert setup.pending(db) == []
    # And through the page's own calls, on a tapiOca updated with stations.
    with make(tmp_path / "app", fp=FakePlex()) as c:
        db = c.app.state.ctx.db
        db.set_meta(setup.META_ANSWERED, json.dumps({**setup.QUESTIONS, "plex": 1}))
        got = c.get("/api/setup").json()
        assert got["pending"] == ["plex"]
        # (Saving where you watch doesn't answer it: leaving the step does.)
        c.put(URL, json={"watchIn": ["plex", "jellyfin"]})
        assert c.get("/api/setup").json()["pending"] == ["plex"]
        assert c.put("/api/setup", json={"answered": ["plex"]}).json()["pending"] == []
        assert c.get("/api/setup").json()["pending"] == []


# The page --------------------------------------------------------------------------

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

STAND_INS = r"""
function h(tag, attrs = {}, ...kids) {
  return { tag, attrs: attrs || {}, kids: kids.flat().filter(k => k != null && k !== false) };
}
const copyButton = value => h('button', { class: 'btn' }, 'Copy');
function textOf(n) {
  if (n == null || n === false) return '';
  if (typeof n === 'string' || typeof n === 'number') return String(n);
  return (n.kids || []).map(textOf).join('');
}
function all(n, test, out = []) {
  if (!n || typeof n !== 'object') return out;
  if (test(n)) out.push(n);
  for (const k of n.kids || []) all(k, test, out);
  return out;
}
"""


def _function(script: str, name: str) -> str:
    start = script.index(f"function {name}(")
    return script[start : script.index("\n}\n", start) + 3]


def _line(script: str, start: str) -> str:
    a = script.index(start)
    return script[a : script.index(";\n", a) + 2]


def node(code: str) -> object:
    script = (JS / "setup.js").read_text(encoding="utf-8")
    a = script.index("const WATCH_CHOICES = [")
    choices = script[a : script.index("];\n", a) + 3]
    whole = "\n".join([
        STAND_INS,
        choices,
        _line(script, "const NO_WATCH_IN = "),
        _function(script, "watchToggled"),
        _function(script, "watchInWords"),
        _function(script, "watchSection"),
        f"console.log(JSON.stringify((() => {{ {code} }})()));",
    ])  # fmt: skip
    done = subprocess.run(["node", "-e", whole], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@needs_node
def test_the_choices_and_only_tapiocas_own_apps():
    got = node(r"""
      const labels = WATCH_CHOICES.map(([, name, more]) => more ? `${name} (${more})` : name);
      let c = ['plex'];
      const steps = [];
      c = watchToggled(c, 'jellyfin', true); steps.push(c);
      c = watchToggled(c, 'other', true); steps.push(c);
      c = watchToggled(c, 'tapioca', true); steps.push(c);
      c = watchToggled(c, 'kodi', true); steps.push(c);
      c = watchToggled(c, 'kodi', false); steps.push(c);
      return { labels, steps };
    """)
    assert got["labels"] == [
        "Plex", "Jellyfin", "Emby", "Kodi", "Another app (an M3U playlist and XMLTV guide)",
        "Only tapiOca’s own apps",
    ]  # fmt: skip
    assert got["steps"] == [
        ["plex", "jellyfin"],
        ["plex", "jellyfin", "other"],
        ["tapioca"],  # (ticking it clears the others)
        ["kodi"],  # (and ticking another clears it)
        [],
    ]
    # The page's choices are the server's.
    script = (JS / "setup.js").read_text(encoding="utf-8")
    block = script[script.index("const WATCH_CHOICES = [") :]
    block = block[: block.index("];")]
    assert re.findall(r"\['(\w+)'", block) == list(setup.WATCH_IN)
    assert "const NO_WATCH_IN = 'Choose at least one app, or Only tapiOca’s own apps.';" in script
    assert setup.NO_WATCH_IN == "Choose at least one app, or Only tapiOca’s own apps."


@needs_node
def test_all_set_says_what_was_chosen():
    got = node(r"""
      return [['plex', 'jellyfin'], ['kodi', 'plex', 'emby'], ['other'], ['jellyfin', 'other'],
              ['tapioca'], [], null].map(watchInWords);
    """)
    assert got == [
        "Plex and Jellyfin",
        "Plex, Emby and Kodi",
        "Another app",
        "Jellyfin and another app",
        "Only tapiOca’s own apps",
        "",
        "",
    ]
    script = (JS / "setup.js").read_text(encoding="utf-8")
    done = script[script.index("  async done(") :]
    assert "[['plex', watchInWords(watching.watchIn)]]" in done


URLS = '{ m3u: "http://10.0.0.5:3310/stations.m3u", guide: "http://10.0.0.5:3310/guide.xml" }'


@needs_node
@pytest.mark.parametrize(
    ("place", "heading", "rows", "words"),
    [
        ("jellyfin", "Adding tapiOca to Jellyfin",
         ["Playlist (M3U) for Jellyfin", "Guide (XMLTV) for Jellyfin"],
         ["Tuner Devices", "M3U Tuner", "TV Guide Data Providers", "XMLTV",
          "Dashboard → Scheduled Tasks → Refresh Guide", "no limit"]),
        ("emby", "Adding tapiOca to Emby",
         ["Playlist (M3U) for Emby", "Guide (XMLTV) for Emby"],
         ["Live TV", "M3U Tuner", "XMLTV", "Emby’s Live TV needs Emby Premiere."]),
        ("kodi", "Adding tapiOca to Kodi",
         ["Playlist (M3U) for Kodi", "Guide (XMLTV) for Kodi"],
         ["Kodi’s PVR Simple Client add-on", "M3U play list URL", "XMLTV URL", "TV"]),
        ("other", "Adding tapiOca to another app",
         ["Playlist (M3U)", "Guide (XMLTV)"],
         ["Channels DVR and VLC accept it", "If the app asks for a guide (XMLTV) too"]),
    ],
)  # fmt: skip
def test_each_apps_steps_and_addresses(place, heading, rows, words):
    got = node(rf"""
      const s = watchSection('{place}', {URLS});
      const copy = all(s, n => n.attrs.class === 'copyrow');
      return {{
        place: s.attrs['data-watch'],
        heading: textOf(all(s, n => n.tag === 'strong')[0]),
        rows: copy.map(r => textOf(r.kids[0])),
        codes: copy.map(r => textOf(r.kids[1])),
        buttons: copy.map(r => textOf(r.kids[2])),
        text: textOf(s),
      }};
    """)
    assert got["place"] == place and got["heading"] == heading
    assert got["rows"] == rows
    assert got["codes"] == ["http://10.0.0.5:3310/stations.m3u", "http://10.0.0.5:3310/guide.xml"]
    assert got["buttons"] == ["Copy", "Copy"]
    for word in words:
        assert word in got["text"], word
    # (Legal care and the wording rules: "station," never "channel"; never "IPTV".)
    words_said = got["text"].replace("Channels DVR", "")  # (an app's name: wording_allowed.txt)
    assert not re.search(r"\bchannels?\b|\biptv\b|\blibrar", words_said, re.IGNORECASE)


@needs_node
def test_only_tapiocas_own_apps_needs_nothing_else():
    got = node(f"return textOf(watchSection('tapioca', {URLS}));")
    assert (
        got == "Nothing else is needed. tapiOca’s own apps get your stations straight from tapiOca."
    )


def test_the_step_is_called_tuner_and_asks_where_you_watch():
    script = (JS / "setup.js").read_text(encoding="utf-8")
    assert "  plex: 'Tuner',  //" in script
    step = script[script.index("  async plex(") :]
    step = step[: step.index("\n  },\n")]
    assert "'Will you watch your stations in other apps?'" in step
    assert "api('/api/setup/watch-in', { method: 'PUT', body: { watchIn: chosen } })" in step
    assert "if (!chosen.length) return NO_WATCH_IN;" in step
    # Plex's part: today's checks, steps, addresses, Plex Pass and Plex's terms; and the tip.
    for said in (
        "'Adding tapiOca to Plex'",
        "copyRow('Tuner address', tuner)",
        "copyRow('Guide (XMLTV) for Plex', guide)",
        "'Watching in Plex needs Plex Pass on the account that owns your Plex server.",
        "PERSONAL_USE()",
        "'If Plex says “There was a problem fetching channel mappings,” reload Plex’s page and "
        "start again. Plex renames the tuner partway through setup, so it may still know "
        "tapiOca’s tuner from before.'",
    ):
        assert said in step, said
    # (The other steps say where Plex is checked now.)
    assert "Plex has a step of its own" not in script
    assert "Plex is checked in the Tuner step, near the end." in script
    tab = (JS / "addtoplex.js").read_text(encoding="utf-8")
    assert "its Tuner step says what to change" in tab and "its Plex step" not in tab


def test_plexs_terms_go_with_plexs_checks():
    """1.36.3's audit: with Plex set up but only Jellyfin ticked, Plex's checks
    showed without Plex's terms (CLAUDE.md: the setup's Plex step states
    them). They're part of the checks now, shown whenever Plex is checked."""
    script = (JS / "setup.js").read_text(encoding="utf-8")
    checks = script[script.index("const plexChecks = ") :]
    checks = checks[: checks.index(";\n")]
    assert "PERSONAL_USE()" in checks
