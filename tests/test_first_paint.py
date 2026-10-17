"""tapiOca's page before the server has said who's signed in (1.38.0, the
owner, October 17: "Settings, Logs, Access, Broken Files... flash for a
second" on refresh, and "they shouldn't flash for a second for a restricted
[non Admin] user at all").

1.37.1 began as if signing in were off (`me = { required: false }`, so
isAdmin() was true), drew the Admin tabs without `hidden`, and hid them only
once /api/access/me answered; and if that failed, it carried on as if
everyone were an Admin. Now nothing only an Admin may use is drawn until the
server has said this sign-in may use it, and if it can't be asked, the page
says so, with Try again, and shows nothing else. (The server never sent an
Admin's data to anyone else: what showed was the tabs. tools/page_sizes.py
checks it in a browser, with /api/access/me slow and failing.)"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from app.main import WEB_DIR

HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")
ACCESS = (WEB_DIR / "js" / "access.js").read_text(encoding="utf-8")
BOOT = (WEB_DIR / "js" / "boot.js").read_text(encoding="utf-8")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def test_the_admin_tabs_start_hidden():
    tabs = re.findall(r'<button class="tab admin"[^>]*>', HTML)
    assert len(tabs) == 4  # Setup, Access, Logs, Broken files
    assert all(re.search(r"\shidden[\s>]", t) for t in tabs), tabs
    assert re.search(r'<span id="footSetupWrap" hidden>', HTML)


def test_the_page_starts_hidden_until_the_server_says():
    """Not even the Stations tab's buttons before the sign-in screen, for
    someone signed out; and without JavaScript, a sentence, not the page."""
    assert '<div class="wrap" hidden>' in HTML
    assert re.search(r'<div class="panel me-problem" id="meProblem" hidden role="alert">', HTML)
    assert "<noscript>" in HTML


def test_the_page_never_carries_on_without_an_answer():
    """boot.js's first ask isn't caught and passed over."""
    assert "try { await loadMe(); } catch {}" not in BOOT
    assert "if (!await firstMe()) return;" in BOOT


def _piece(script: str, start: str) -> str:
    at = script.index(start)
    return script[at : script.index("\n}\n", at) + 3]


STAND_INS = """
const els = {};
const el = sel => els[sel] ??= {
  sel, hidden: sel === '.wrap' || sel.startsWith('#meProblem'), textContent: '',
  firstElementChild: { textContent: '' }, addEventListener() {},
};
const $ = sel => el(sel);
const adminTabs = ['setup', 'access', 'logs', 'broken'].map(t => el('.tab.admin#' + t));
for (const t of adminTabs) t.hidden = true;
const document = { querySelectorAll: sel => (sel === '.tab.admin' ? adminTabs : []) };
const TABS = ['stations', 'setup', 'access', 'stats', 'logs', 'broken'];
const FOR_EVERYONE = ['stations', 'stats'];
let currentTab = 'stations';
const shown = [];
function showTab(name) { shown.push(name); currentTab = name; }
function signOutAt() {}
function renderRoom() {}
const roleName = role => role === 'admin' ? 'Admin' : 'User';
const signedOut = () => false;
let answer = null;
async function api(path) {
  if (path !== '/api/access/me') throw new Error('not here');
  if (answer instanceof Error) throw answer;
  return answer;
}
"""


def page(steps: str) -> dict:
    """Runs access.js's sign-in state (me, isAdmin, loadMe, showForMe,
    showWatching and firstMe) with stand-ins for the page, then `steps`; what it printed."""
    code = (
        STAND_INS
        + re.search(r"^let me = .*;$", ACCESS, re.M)[0]
        + "\n"
        + re.search(r"^const isAdmin = .*;$", ACCESS, re.M)[0]
        + "\n"
        + _piece(ACCESS, "async function loadMe(")
        + _piece(ACCESS, "function showForMe(")
        + _piece(ACCESS, "function showWatching(")
        + _piece(ACCESS, "async function firstMe(")
        + "const tabs = () => adminTabs.filter(t => !t.hidden).length;\n"
        + "(async () => {\n"
        + steps
        + "\n})().catch(e => { console.error(e); process.exit(1); });"
    )
    done = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@needs_node
def test_before_the_answer_no_one_is_an_admin():
    said = page("console.log(JSON.stringify({ admin: isAdmin(), tabs: tabs() }));")
    assert said == {"admin": False, "tabs": 0}


@needs_node
def test_after_the_answer_the_tabs_are_as_it_says():
    said = page(
        """
const out = {};
for (const [name, a] of Object.entries({
  off: { required: false, user: null },
  signedOut: { required: true, user: null },
  user: { required: true, user: { name: 'Pat', role: 'user', adminTools: false } },
  watching: { required: true, user: { name: 'Sam', role: 'admin', adminTools: false, byNetwork: true } },
  admin: { required: true, user: { name: 'Sam', role: 'admin', adminTools: true } },
  // (A server from before 1.38.0 says nothing of adminTools: no Admin tabs
  // from what it can't be sure of.)
  older: { required: true, user: { name: 'Sam', role: 'admin', byNetwork: false } },
})) {
  answer = a;
  el('.wrap').hidden = true;  // (each as the page opens)
  out[name] = await firstMe() && { admin: isAdmin(), tabs: tabs(), wrap: !els['.wrap'].hidden };
}
console.log(JSON.stringify(out));
"""
    )
    yes = {"admin": True, "tabs": 4, "wrap": True}
    no = {"admin": False, "tabs": 0, "wrap": True}
    assert said == {
        "off": yes,
        "signedOut": {"admin": False, "tabs": 0, "wrap": False},  # (the sign-in screen's turn)
        "user": no,
        "watching": no,
        "admin": yes,
        "older": no,
    }


@needs_node
def test_without_an_answer_the_page_says_so_and_nothing_else():
    said = page(
        """
answer = Object.assign(new Error('Internal Server Error'), { status: 500 });
const ok = await firstMe();
console.log(JSON.stringify({
  ok, admin: isAdmin(), tabs: tabs(), problem: !els['#meProblem'].hidden,
  wrap: !els['.wrap'].hidden, tabrow: !els['.tabrow'].hidden,
  sections: TABS.filter(t => !els['#tab-' + t].hidden),
}));
"""
    )
    assert said == {
        "ok": False,
        "admin": False,
        "tabs": 0,
        "problem": True,
        "wrap": True,
        "tabrow": False,
        "sections": [],
    }


@needs_node
def test_an_admin_who_loses_admin_tools_goes_to_stations():
    """A role or sign-in changed while the page was open (the 10-second
    check): the Admin tabs go, and an Admin tab that was open with them."""
    said = page(
        """
answer = { required: true, user: { name: 'Sam', role: 'admin', adminTools: true } };
await firstMe();
currentTab = 'logs';
answer = { required: true, user: { name: 'Sam', role: 'user', adminTools: false } };
await loadMe();
console.log(JSON.stringify({ tabs: tabs(), shown, now: currentTab }));
"""
    )
    assert said == {"tabs": 0, "shown": ["stations"], "now": "stations"}


def test_a_page_the_browser_kept_asks_again_before_showing_admin_tools():
    """Back to a page the browser kept (its back-forward cache): as for
    someone signed out until tapiOca answers again."""
    kept = ACCESS.split("addEventListener('pageshow'", 1)[1].split("\n});\n", 1)[0]
    assert "if (!e.persisted" in kept
    assert "me = { ...me, known: false };" in kept
    assert kept.index("showForMe();") < kept.index("await firstMe()")


def test_the_pages_scripts_never_declare_a_name_twice():
    """(Found by tools/page_sizes.py before 1.38.0 shipped: access.js's new
    `let picked` clashed with filter.js's `const picked`. The page's scripts
    share one scope, so the browser refused access.js whole, and the page
    stayed blank for everyone.) Every name a script declares at its top
    level (let, const, class or function) is declared once in all of them."""
    order = re.findall(r'<script src="/web/js/([a-z]+\.js)\?v=__VERSION__"></script>', HTML)
    assert "access.js" in order and "filter.js" in order, order
    declared: dict[str, list[str]] = {}
    top = re.compile(r"^(?:async\s+)?(?:let|const|class|function\*?)\s+([A-Za-z_$][\w$]*)", re.M)
    for name in order:
        for found in top.findall((WEB_DIR / "js" / name).read_text(encoding="utf-8")):
            declared.setdefault(found, []).append(name)
    twice = {k: v for k, v in declared.items() if len(v) > 1}
    assert twice == {}, twice


SIGNED_IN_NOW = """
const sessionStorage = { removeItem() {} };
let pickedPerson = null;
function loadStatus() {}
function loadChannels() {}
function linkWanted() {}
"""


@needs_node
def test_signed_out_by_the_server_no_admin_tools_stay():
    """(The cold audit of 1.38.0.) A 401 while the page is open (a new role
    ended the sign-in, or an hour without activity): the sign-in screen
    shows, and with it nothing the old sign-in had, until tapiOca says who's
    signed in again."""
    assert re.search(
        r"function showSignIn\(idle = false\) \{\n  if \(signedOut\(\)\) return;\n  forgetMe\(\);",
        ACCESS,
    )
    said = page(
        _piece(ACCESS, "function forgetMe(")
        + """
answer = { required: true, user: { name: 'Lee', role: 'admin', adminTools: true } };
await firstMe();
const before = tabs();
forgetMe();
console.log(JSON.stringify({ before, admin: isAdmin(), tabs: tabs(), user: me.user,
                             watching: !els['#watchingNote'].hidden }));
"""
    )
    assert said == {"before": 4, "admin": False, "tabs": 0, "user": None, "watching": False}


@needs_node
def test_signing_in_again_shows_the_page_only_once_tapioca_says_who():
    """(The cold audit of 1.38.0: signedInNow showed the page, the Admin
    tabs of the sign-in before included, and only then asked who's signed
    in.) Lee, made a User, signs in again: nothing shows until the answer,
    and then no Admin tab."""
    said = page(
        SIGNED_IN_NOW
        + _piece(ACCESS, "function forgetMe(")
        + _piece(ACCESS, "async function signedInNow(")
        + """
answer = { required: true, user: { name: 'Lee', role: 'admin', adminTools: true } };
await firstMe();
el('#signinView').hidden = false;
el('.wrap').hidden = true;
let answered;
const later = new Promise(go => { answered = go; });
const asked = api;
api = async path => { await later; return asked(path); };
answer = { required: true, user: { name: 'Lee', role: 'user', adminTools: false } };
const going = signedInNow();
await new Promise(go => setTimeout(go, 20));
const waiting = { wrap: !els['.wrap'].hidden, tabs: tabs() };
answered();
await going;
console.log(JSON.stringify({ waiting, after: { wrap: !els['.wrap'].hidden, tabs: tabs(),
                                               signin: !els['#signinView'].hidden } }));
"""
    )
    assert said == {
        "waiting": {"wrap": False, "tabs": 0},
        "after": {"wrap": True, "tabs": 0, "signin": False},
    }
