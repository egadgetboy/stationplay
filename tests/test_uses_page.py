"""The page's side of What you use (1.37.0), run in Node with stand-ins:
which places count as watched, how the other apps are named in a sentence,
the parts shown for each choice, the header's pill, and when a ready update
starts. Until an Admin chooses, the page says what 1.36.0 said."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "app" / "web" / "js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def _between(script: str, start: str, end: str) -> str:
    a = script.index(start)
    b = script.index(end, a)
    return script[a : b + len(end)]


def run(status: dict | None, code: str) -> object:
    core = (JS / "core.js").read_text(encoding="utf-8")
    start = core.index("const plexUsed = ")
    helpers = core[start : core.index("\n}\n", core.index("function showForChoices(")) + 3]
    pill = _between((JS / "status.js").read_text(encoding="utf-8"), "function pillFor(", "\n}\n")
    starts = _between(
        (JS / "stations.js").read_text(encoding="utf-8"), "function updateStarts(", "\n}\n"
    )
    script = f"let status = {json.dumps(status)};\n{helpers}\n{pill}\n{starts}\n"
    script += f"console.log(JSON.stringify((() => {{ {code} }})()));"
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def chose(watch_in, sources=("plex",)):
    return {"plexUsed": "plex" in sources, "plex": {"configured": True, "ok": True},
            "uses": {"sources": list(sources), "watchIn": watch_in, "saved": True},
            "folders": {"count": 0, "missing": 0}}  # fmt: skip


def test_which_places_count_as_watched():
    places = ["tapioca", "plex", "jellyfin", "emby", "kodi", "other"]
    ask = f"return {json.dumps(places)}.map(p => watches(p));"
    # Nothing chosen: every place, Plex where tapiOca uses Plex (1.36.0).
    unsaved = {"plexUsed": True, "uses": {"sources": ["plex"], "watchIn": None, "saved": False}}
    assert run(unsaved, ask) == [True] * 6
    assert run({**unsaved, "plexUsed": False}, ask) == [True, False, True, True, True, True]
    assert run(chose(["tapioca", "emby"]), ask) == [True, False, False, True, False, False]
    # A User's status (no choices in it): as 1.36.0.
    assert run({"plex": {"used": False}}, ask) == [True, False, True, True, True, True]


@pytest.mark.parametrize(
    ("watch_in", "said"),
    [
        (None, None),
        (["tapioca"], {"text": "", "one": False, "none": True}),
        (["plex"], {"text": "Plex", "one": True, "none": False}),
        (["emby", "tapioca"], {"text": "Emby", "one": True, "none": False}),
        (["plex", "jellyfin", "other"], {"text": "Plex, Jellyfin or other apps", "one": False,
                                         "none": False}),  # fmt: skip
        (["other"], {"text": "other apps", "one": False, "none": False}),
    ],
)
def test_the_other_apps_named_in_a_sentence(watch_in, said):
    status = chose(watch_in) if watch_in else {"uses": {"saved": False, "watchIn": None}}
    assert run(status, "return appsNamed('or');") == said


def test_parts_shown_for_each_choice():
    code = """
      const els = [['plex'], ['folders'], ['watch-plex'], ['watch-others'], ['plex watch-plex'],
                   ['nonsense']].map(([when]) => ({ dataset: { when }, hidden: false }));
      showForChoices({ querySelectorAll: () => els });
      return els.map(e => e.hidden);
    """
    # Plex and folders, watched in Jellyfin only.
    got = run(chose(["jellyfin"], ("plex", "folders")), code)
    assert got == [False, False, True, False, True, False]
    # Folders only, in tapiOca's apps only.
    assert run(chose(["tapioca"], ("folders",)), code) == [True, False, True, True, True, False]


@pytest.mark.parametrize(
    ("status", "pill"),
    [
        # A User's status: Plex, where tapiOca uses it (as 1.36.0).
        ({"plex": {"used": True, "configured": True, "ok": True}}, ["ok", "Plex connected"]),
        ({"plex": {"used": True, "configured": False, "ok": False}}, ["bad", "Nothing to play yet"]),
        ({"plex": {"used": False, "configured": False}}, ["", ""]),
        # An Admin's.
        ({"plexUsed": True, "plex": {"configured": True, "ok": False, "error": "timed out"},
          "uses": {"sources": ["plex"]}, "folders": {"count": 0, "missing": 0}},
         ["bad", "Plex: timed out"]),
        ({"plexUsed": True, "plex": {"configured": True, "ok": True},
          "uses": {"sources": ["plex", "folders"]}, "folders": {"count": 2, "missing": 1}},
         ["bad", "A Media folder can’t be read"]),
        ({"plexUsed": True, "plex": {"configured": False},
          "uses": {"sources": ["plex", "folders"]}, "folders": {"count": 1, "missing": 0}},
         ["warn", "Plex isn’t set up yet"]),
        ({"plexUsed": False, "plex": {"configured": False},
          "uses": {"sources": ["folders"]}, "folders": {"count": 3, "missing": 0}},
         ["ok", "Media folders ready"]),
        ({"plexUsed": True, "plex": {"configured": False},
          "uses": {"sources": ["plex"]}, "folders": {"count": 0, "missing": 0}},
         ["bad", "Nothing to play yet"]),
    ],
)  # fmt: skip
def test_the_headers_pill(status, pill):
    assert run(status, f"return pillFor({json.dumps(status)});") == pill


def test_when_a_ready_update_starts():
    now = 1_800_000_000_000
    assert run(None, f"return updateStarts({{waitsFor: 'plex'}}, {now});") == (
        "Changes are ready. They start at the next program break after Plex downloads the "
        "guide, so the Plex guide always matches."
    )
    later = run(None, f"return updateStarts({{waitsFor: 'guide', after: {now + 3600_000}}}, {now});")
    assert later.startswith("Changes are ready. They start at the first program break after ")
    assert later.endswith(", when the guide other apps downloaded runs out, so their guides stay right.")
    assert run(None, f"return updateStarts({{waitsFor: 'guide', after: {now}}}, {now});") == (
        "Changes are ready. They start at a program break within the hour."
    )
