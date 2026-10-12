"""The wording scan (1.33.0): every string people see says "station," never
"channel," and keeps the plan's legal care.

It reads the docs (README, SECURITY.md, the open-source notices, docs/*.md,
and the release notes from 1.33.0 on), the Unraid template's words (from
1.34.0: its Overview and what it says of each setting), tapiOca's page
(index.html and the strings in app/web/js) and the sentences in the
server's Python (strings with a space in them, but not docstrings or SQL).
Code isn't words: in Markdown, code spans, code blocks and link addresses
are skipped, and only the descriptions in openapi-v1.json are read.

Words are matched whole, ignoring case, so "record" never matches "cord".
It fails on "channel" or "channels" (not inside a longer word, and not
joined to a number for sound, such as "6-channel"), "passcode," "IPTV,"
"free TV," "cord," and real TV network names (short all-capital ones such
as ABC only in capitals). On the page and in the Python, it also fails on
"library" or "libraries": the on-demand titles are "Media," and Plex's
libraries are "Media folders."

The brand (1.34.0, the owner's rename): it fails on "StationPlay", the
old name, and on "Tapioca", "TAPIOCA" or "TapiOca" (it's always "tapiOca";
lowercase "tapioca" in names and addresses). These match case and all, so
the names kept for other programs (STATIONPLAY_SOAK, stationplay.db;
docs/notes/names-kept.md) and lowercase names (tapioca-server) never count.
Release notes before 1.34.0 are published history: the brand rule skips
them.

A phrase in tests/wording_allowed.txt (with why, after a #) may hold a
flagged word: it excuses only the words inside it, and each one has to
excuse something, so the list never goes stale.
"""

from __future__ import annotations

import ast
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_FILE = Path(__file__).with_name("wording_allowed.txt")
FIRST_NOTES = (1, 33, 0)  # older release notes are published history
FIRST_BRAND_NOTES = (1, 34, 0)  # the first notes as tapiOca


@dataclass
class Unit:
    """A piece of text people see, from `path`, starting on `line`."""

    path: str
    line: int
    text: str
    page_or_code: bool = False  # the page, or the server's Python: "library" counts
    brand: bool = True  # the brand rule applies (all but release notes before 1.34.0)


@dataclass
class Hit:
    path: str
    line: int
    word: str
    around: str
    excused_by: str | None = field(default=None, compare=False)

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.word!r} in “{self.around}”"


# What fails ------------------------------------------------------------------


def _words(*phrases: str) -> str:
    """Phrases as one pattern, each word whole, any space between words."""
    return "|".join(r"\s+".join(map(re.escape, p.split())) for p in phrases)


def _listed(names: str) -> list[str]:
    return [n.strip() for n in names.split("|")]


_NETWORKS_IN_CAPITALS = _listed(
    "ABC|CBS|NBC|FOX|Fox|PBS|CNN|HBO|ESPN|MTV|AMC|TNT|TBS|CW|BET|TLC|HGTV|FX|FXX|QVC|A&E|C-SPAN|"
    "Boomerang|Sling"
)
_NETWORKS = _listed(
    "Nickelodeon|Showtime|Cinemax|Starz|Disney Channel|Cartoon Network|Comedy Central|"
    "Turner Classic Movies|Hallmark Channel|History Channel|Discovery Channel|Weather Channel|"
    "Food Network|USA Network|Nick at Nite|Adult Swim|MeTV|Antenna TV|Pluto TV|Tubi|TV Land|Syfy|"
    "Freeform|Telemundo|Univision"
)
_CHANNEL = re.compile(r"(?<!\w)channels?(?!\w)", re.IGNORECASE)
_SOUND = re.compile(r"\d-$")  # "6-channel", "5.1-channel": sound, not a station
_ANYWHERE = [
    re.compile(r"(?<!\w)passcodes?(?!\w)", re.IGNORECASE),
    re.compile(r"(?<!\w)iptv(?!\w)", re.IGNORECASE),
    re.compile(r"(?<!\w)free\s+tv(?!\w)", re.IGNORECASE),
    re.compile(r"(?<!\w)cords?(?!\w)", re.IGNORECASE),
    # Real TV networks: the short ones only in capitals ("Fox" too, as a
    # name), so "abc" in an example code or "fox" the animal aren't caught.
    re.compile(r"(?<!\w)(?:" + _words(*_NETWORKS_IN_CAPITALS) + r")(?!\w)"),
    re.compile(r"(?<!\w)(?:" + _words(*_NETWORKS) + r")(?!\w)", re.IGNORECASE),
]
_LIBRARY = re.compile(r"(?<!\w)librar(?:y|ies)(?!\w)", re.IGNORECASE)
# The brand: never the old name, and tapiOca only as it's written (case matters).
_BRAND = [
    re.compile(r"(?<!\w)StationPlay(?!\w)"),
    re.compile(r"(?<!\w)(?:Tapioca|TAPIOCA|TapiOca)(?!\w)"),
]


def find_words(unit: Unit) -> list[tuple[int, int]]:
    """Where `unit` says something it mustn't, as (start, end) in its text."""
    text = unit.text
    found = [
        (m.start(), m.end())
        for m in _CHANNEL.finditer(text)
        if not _SOUND.search(text[max(0, m.start() - 2) : m.start()])
    ]
    patterns = _ANYWHERE + ([_LIBRARY] if unit.page_or_code else [])
    for pattern in patterns + (_BRAND if unit.brand else []):
        found += [(m.start(), m.end()) for m in pattern.finditer(text)]
    return sorted(found)


# The allowed list -------------------------------------------------------------


def allowed_phrases() -> list[str]:
    """The phrases in wording_allowed.txt (each line: phrase, then # why)."""
    phrases = []
    for raw in ALLOWED_FILE.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        phrase, sep, why = raw.partition(" #")
        assert sep and why.strip(), f"wording_allowed.txt: say why, after a #: {raw!r}"
        phrases.append(phrase.strip())
    return phrases


def scan(units: list[Unit], allowed: list[str]) -> list[Hit]:
    """Every word that mustn't be there, with the allowed phrase (if any)
    that excuses it."""
    patterns = [(p, re.compile(_words(p), re.IGNORECASE)) for p in allowed]
    hits = []
    for unit in units:
        spots = find_words(unit)
        if not spots:
            continue
        covers = [(m.start(), m.end(), p) for p, rx in patterns for m in rx.finditer(unit.text)]
        for start, end in spots:
            excuse = next((p for s, e, p in covers if s <= start and end <= e), None)
            before = unit.text[max(0, start - 45) : start]
            after = unit.text[end : end + 45]
            around = " ".join(f"{before}{unit.text[start:end]}{after}".split())
            hits.append(
                Hit(
                    unit.path,
                    unit.line + unit.text.count("\n", 0, start),
                    unit.text[start:end],
                    around,
                    excuse,
                )
            )
    return hits


# What's read: Markdown ------------------------------------------------------------


def _blank(text: str, start: int, end: int) -> str:
    """`text` with [start, end) turned to spaces, keeping its line breaks."""
    return text[:start] + re.sub(r"[^\n]", " ", text[start:end]) + text[end:]


_FENCE = re.compile(r"^\s*(```|~~~)")
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
_HTML_TAG = re.compile(r"<!--.*?-->|<[A-Za-z/][^>]*>", re.DOTALL)
_SEEN_ATTR = re.compile(r"""\b(?:alt|title)\s*=\s*(["'])(.*?)\1""", re.DOTALL)
_ADDRESSES = [
    re.compile(r"\]\([^)\s]*(?:\s+\"[^\"]*\")?\)"),  # a link's address: ](…)
    re.compile(r"^\s*\[[^\]]+\]:\s*\S+.*$", re.MULTILINE),  # [name]: address
    re.compile(r"https?://\S+"),
]


def markdown_text(md: str) -> str:
    """The words of a Markdown file, with code, addresses and HTML blanked
    out (so line numbers still match)."""
    lines, inside = md.split("\n"), None
    for i, line in enumerate(lines):
        fence = _FENCE.match(line)
        if inside or fence:
            if fence and (inside is None or fence.group(1) == inside):
                inside = None if inside else fence.group(1)
            lines[i] = ""
    text = "\n".join(lines)
    for m in reversed(list(_CODE_SPAN.finditer(text))):
        if "\n\n" not in m.group(0):
            text = _blank(text, m.start(), m.end())
    for m in reversed(list(_HTML_TAG.finditer(text))):
        kept = re.sub(r"[^\n]", " ", m.group(0))
        for a in _SEEN_ATTR.finditer(m.group(0)):  # alt and title are read
            kept = kept[: a.start(2)] + a.group(2) + kept[a.end(2) :]
        text = text[: m.start()] + kept + text[m.end() :]
    for pattern in _ADDRESSES:
        for m in reversed(list(pattern.finditer(text))):
            text = _blank(text, m.start() + (1 if m.group(0).startswith("]") else 0), m.end())
    return text


def _notes_version(path: Path) -> tuple[int, ...]:
    m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\.md", path.name)
    return tuple(int(n) for n in m.groups()) if m else (0,)


def markdown_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "SECURITY.md", ROOT / "PRIVACY.md",
             *sorted(ROOT.glob("THIRD_PARTY_NOTICES*"))]  # fmt: skip
    files += sorted((ROOT / "docs").glob("*.md"))
    files += [
        p
        for p in sorted((ROOT / "docs" / "releases").glob("v*.md"))
        if _notes_version(p) >= FIRST_NOTES
    ]
    return [p for p in files if p.is_file()]


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def doc_units() -> list[Unit]:
    units = [
        Unit(
            _rel(p),
            1,
            markdown_text(p.read_text(encoding="utf-8")),
            brand=p.parent.name != "releases" or _notes_version(p) >= FIRST_BRAND_NOTES,
        )
        for p in markdown_files()
    ]
    # The API's description: its prose, not its field names or addresses.
    spec_path = ROOT / "docs" / "openapi-v1.json"
    raw = spec_path.read_text(encoding="utf-8")

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("description", "summary", "title") and isinstance(value, str):
                    at = raw.find(json.dumps(value, ensure_ascii=False)[1:60])
                    line = raw.count("\n", 0, at) + 1 if at >= 0 else 1
                    units.append(Unit(_rel(spec_path), line, markdown_text(value)))
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(raw))
    # Unraid's templates: what Unraid shows of them.
    for xml in sorted((ROOT / "unraid").glob("*.xml")):
        raw = xml.read_text(encoding="utf-8")
        for element in ET.fromstring(raw).iter():
            said = [element.text if element.tag in ("Overview", "Requires") else None,
                    element.get("Name"), element.get("Description")]  # fmt: skip
            for text in filter(None, said):
                at = raw.find(text[:60].replace("&", "&amp;").replace("'", "&apos;"))
                line = raw.count("\n", 0, at) + 1 if at >= 0 else 1
                units.append(Unit(_rel(xml), line, text))
    return units


# What's read: the page ---------------------------------------------------------------


def _shown(text: str) -> bool:
    """A JavaScript string people might read: words with a space, or one
    capitalized word, such as a button's label (not keys, paths or ids)."""
    return bool(re.search(r"\s", text.strip())) or bool(re.fullmatch(r"[A-Z][a-z]+[.:!?]?", text))


class _JS:
    """The string and template literals in JavaScript, with their lines.
    A template's ${…} reads as 0 (so `${n}-channel` stays sound)."""

    KEYWORDS: ClassVar = frozenset(
        _listed("return|typeof|case|in|of|delete|void|throw|new|else|do|instanceof|yield|await")
    )

    def __init__(self, src: str, first_line: int = 1) -> None:
        self.s, self.i, self.line = src, 0, first_line
        self.found: list[tuple[int, str]] = []
        self.code(stop_at_brace=False)

    def code(self, stop_at_brace: bool) -> None:
        s, depth, prev, before = self.s, 0, "", ""
        while self.i < len(s):
            c = s[self.i]
            last = prev
            if c == "\n":
                self.line += 1
                self.i += 1
                continue
            if c.isspace():
                self.i += 1
                continue
            if s.startswith("//", self.i):
                end = s.find("\n", self.i)
                self.i = len(s) if end < 0 else end
                continue
            if s.startswith("/*", self.i):
                end = s.find("*/", self.i + 2)
                end = len(s) if end < 0 else end + 2
                self.line += s.count("\n", self.i, end)
                self.i = end
                continue
            if c in "'\"`":
                had = len(self.found)
                self.quoted(c) if c != "`" else self.template()
                if prev in (":", "=") and before in ("class", "className"):
                    del self.found[had:]  # CSS class names, not words
                prev = "a"
            elif c == "/":
                if not prev or prev in "(,=:[!&|?{};+-*%<>~^" or prev in self.KEYWORDS:
                    self.regex()
                    prev = "a"
                else:
                    self.i += 1
                    prev = "/"
            elif c.isalnum() or c in "_$":
                m = re.compile(r"[\w$]+").match(s, self.i)
                assert m
                prev, self.i = m.group(0), m.end()
            else:
                self.i += 1
                prev = c
                if c == "{":
                    depth += 1
                elif c == "}":
                    if stop_at_brace and depth == 0:
                        return
                    depth -= 1
            before = last

    def escape(self) -> str:
        s, e = self.s, self.s[self.i + 1 : self.i + 2]
        self.i += 2
        if e == "\n":
            self.line += 1
            return ""
        if e == "u":
            m = re.compile(r"\{([0-9a-fA-F]+)\}|([0-9a-fA-F]{4})").match(s, self.i)
            if m:
                self.i = m.end()
                return chr(int(m.group(1) or m.group(2), 16))
        if e == "x" and re.fullmatch(r"[0-9a-fA-F]{2}", s[self.i : self.i + 2]):
            self.i += 2
            return chr(int(s[self.i - 2 : self.i], 16))
        return {"n": "\n", "t": "\t", "r": ""}.get(e, e)

    def quoted(self, quote: str) -> None:
        s, line, out = self.s, self.line, []
        self.i += 1
        while self.i < len(s) and s[self.i] not in (quote, "\n"):
            if s[self.i] == "\\":
                out.append(self.escape())
            else:
                out.append(s[self.i])
                self.i += 1
        self.i += 1
        self.found.append((line, "".join(out)))

    def template(self) -> None:
        s, line, out = self.s, self.line, []
        self.i += 1
        while self.i < len(s) and s[self.i] != "`":
            if s[self.i] == "\\":
                out.append(self.escape())
            elif s.startswith("${", self.i):
                self.i += 2
                self.code(stop_at_brace=True)
                out.append("0")
            else:
                if s[self.i] == "\n":
                    self.line += 1
                out.append(s[self.i])
                self.i += 1
        self.i += 1
        self.found.append((line, "".join(out)))

    def regex(self) -> None:
        s, in_class = self.s, False
        self.i += 1
        while self.i < len(s) and s[self.i] != "\n":
            c = s[self.i]
            if c == "\\":
                self.i += 2
                continue
            self.i += 1
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                break
        while self.i < len(s) and s[self.i].isalpha():
            self.i += 1


def js_strings(src: str, first_line: int = 1) -> list[tuple[int, str]]:
    return _JS(src, first_line).found


class _Page(HTMLParser):
    SEEN: ClassVar = frozenset(
        ("title", "placeholder", "aria-label", "alt", "label", "aria-description")
    )

    def __init__(self, path: str) -> None:
        super().__init__(convert_charrefs=True)
        self.path, self.units, self.in_code = path, [], ""

    def add(self, text: str, line: int | None = None) -> None:
        if text.strip():
            self.units.append(Unit(self.path, line or self.getpos()[0], text, page_or_code=True))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        got = dict(attrs)
        for name, value in attrs:
            if value and (
                name in self.SEEN
                or (name == "value" and got.get("type") in ("button", "submit", "reset"))
                or (name == "content" and got.get("name") == "description")
            ):
                self.add(value)
        if tag in ("script", "style"):
            self.in_code = tag

    def handle_endtag(self, tag: str) -> None:
        if tag == self.in_code:
            self.in_code = ""

    def handle_data(self, data: str) -> None:
        if self.in_code == "script":
            for line, text in js_strings(data, self.getpos()[0]):
                if _shown(text):
                    self.add(text, line)
        elif not self.in_code:
            self.add(data)


def page_units() -> list[Unit]:
    index = ROOT / "app" / "web" / "index.html"
    page = _Page(_rel(index))
    page.feed(index.read_text(encoding="utf-8"))
    page.close()
    units = page.units
    for js in sorted((ROOT / "app" / "web" / "js").glob("*.js")):
        units += [
            Unit(_rel(js), line, text, page_or_code=True)
            for line, text in js_strings(js.read_text(encoding="utf-8"))
            if _shown(text)
        ]
    manifest = ROOT / "app" / "web" / "manifest.webmanifest"
    for key, value in json.loads(manifest.read_text(encoding="utf-8")).items():
        if key in ("name", "short_name", "description") and isinstance(value, str):
            units.append(Unit(_rel(manifest), 1, value, page_or_code=True))
    return units


# What's read: the server's sentences ---------------------------------------------------------


_SQL = re.compile(
    r"^\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|PRAGMA|WITH|REPLACE)\s"
    r"|\s(?:FROM|WHERE|JOIN|VALUES|ON CONFLICT|SET)\s"
)


def python_strings(src: str) -> list[tuple[int, str]]:
    """The strings in Python people might read: f-strings and plain strings
    with a space in them, not docstrings, bare strings or SQL."""
    tree = ast.parse(src)
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            skip.add(id(node.value))  # docstrings, and strings used as comments
        elif isinstance(node, ast.JoinedStr):
            skip.update(id(v) for v in node.values if isinstance(v, ast.Constant))
        elif isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            skip.add(id(node.format_spec))
    found = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "0" for v in node.values)
        else:
            continue
        if re.search(r"\s", text.strip()) and not _SQL.search(text):
            found.append((node.lineno, _not_code(text)))
    return sorted(found, key=lambda f: f[0])


def _not_code(text: str) -> str:
    """A sentence with its `code` spans and <markup> blanked (the guide's
    XML is a format, not words)."""
    for pattern in (_CODE_SPAN, _HTML_TAG):
        for m in reversed(list(pattern.finditer(text))):
            text = _blank(text, m.start(), m.end())
    return text


def python_units() -> list[Unit]:
    units = []
    for py in sorted((ROOT / "app").rglob("*.py")):
        units += [
            Unit(_rel(py), line, text, page_or_code=True)
            for line, text in python_strings(py.read_text(encoding="utf-8"))
        ]
    return units


def all_units() -> list[Unit]:
    return doc_units() + page_units() + python_units()


# The tests ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def hits() -> list[Hit]:
    return scan(all_units(), allowed_phrases())


def test_nothing_people_see_says_what_it_mustnt(hits):
    wrong = [str(h) for h in hits if not h.excused_by]
    assert not wrong, f"{len(wrong)} words people see mustn't be there:\n" + "\n".join(wrong)


def test_every_allowed_phrase_is_still_used(hits):
    used = {h.excused_by for h in hits if h.excused_by}
    stale = [p for p in allowed_phrases() if p not in used]
    assert not stale, "wording_allowed.txt has phrases nothing needs any more: " + ", ".join(stale)


def test_it_reads_every_kind_of_text():
    """The scan finds the files it means to: a scan of nothing would pass."""
    paths = {u.path for u in all_units()}
    for expected in (
        "README.md",
        "SECURITY.md",
        "PRIVACY.md",
        "THIRD_PARTY_NOTICES.md",
        "docs/users.md",
        "docs/internal-api.md",
        "docs/openapi-v1.json",
        "app/web/index.html",
        "app/web/js/access.js",
        "app/main.py",
        "unraid/stationplay.xml",  # (the audit of 1.34.0)
    ):
        assert expected in paths, expected
    assert not any(p.startswith("docs/releases/v1.32") for p in paths)


# The scan's own rules ------------------------------------------------------------------


def _said(text: str, page_or_code: bool = False, allowed: tuple[str, ...] = ()) -> list[str]:
    return [
        h.word for h in scan([Unit("x", 1, text, page_or_code)], list(allowed)) if not h.excused_by
    ]


@pytest.mark.parametrize(
    "text, words",
    [
        ("Pick a channel.", ["channel"]),
        ("Your CHANNELS are ready", ["CHANNELS"]),
        ("channel-surfing all night", ["channel"]),
        ("multichannel sound, 6-channel or 5.1-channel audio", []),
        ("Record it to keep the records.", []),
        ("cut the cord, cord-cutting, Cord cutters", ["cord", "cord", "Cord"]),
        ("cordless, accord, concordance", []),
        ("Enter your passcode", ["passcode"]),
        ("Passcodes are 4 digits", ["Passcodes"]),
        ("Use it as IPTV, iptv or ipTV", ["IPTV", "iptv", "ipTV"]),
        ("Watch free TV here, or free\n  tv there", ["free TV", "free\n  tv"]),
        ("Free TV-G titles", ["Free TV"]),
        ("Like ABC, NBC and FOX", ["ABC", "NBC", "FOX"]),
        ("A Fox show", ["Fox"]),
        ("the quick brown fox, an abc of it, ABCD-1234", []),
        ("Like Cartoon\n Network or adult swim", ["Cartoon\n Network", "adult swim"]),
        ("a channel_id and user_channels", []),
        ("Your Media library", []),
        # The brand (1.34.0)
        ("StationPlay's page, StationPlays", ["StationPlay"]),
        ("Tapioca, TAPIOCA or TapiOca", ["Tapioca", "TAPIOCA", "TapiOca"]),
        ("tapiOca, tapioca-release and ghcr.io/egadgetboy/tapioca-server", []),
        ("STATIONPLAY_SOAK, stationplay.db and github.com/egadgetboy/tapioca-server", []),
        ("TAPIOCA_INSTALL and tapioca.updateNotNow", []),
    ],
)
def test_the_words_it_finds(text, words):
    assert _said(text) == words


def test_the_brand_rule_skips_only_release_notes_before_tapioca():
    said = "StationPlay 1.33.1 fixes it."
    assert [h.word for h in scan([Unit("x", 1, said, brand=False)], [])] == []
    assert [h.word for h in scan([Unit("x", 1, said)], [])] == ["StationPlay"]
    old = {u.path for u in doc_units() if not u.brand}
    assert "docs/releases/v1.33.0.md" in old
    assert all(
        p.startswith("docs/releases/v") and _notes_version(ROOT / p) < FIRST_BRAND_NOTES
        for p in old
    )
    assert all(u.brand for u in page_units() + python_units())


def test_library_counts_on_the_page_and_in_the_code():
    assert _said("Your Media library and libraries", page_or_code=True) == ["library", "libraries"]
    assert _said("Your library", page_or_code=False) == []


def test_an_allowed_phrase_excuses_only_its_own_words():
    allowed = ("Channels DVR",)
    assert _said("Channels DVR works too", allowed=allowed) == []
    assert _said("Channels DVR has channels", allowed=allowed) == ["channels"]
    assert _said("Channels\n  DVR", allowed=allowed) == []


def test_markdown_skips_code_and_addresses():
    md = (
        "Say station.\n"
        "Ask `/api/channels` for them.\n"
        "```\nGET /api/channels\n```\n"
        "See [the stations](https://example.com/channels) or <https://x/channel>.\n"
        '<img src="channel.png" alt="A channel">\n'
        "A channel.\n"
    )
    hits = scan([Unit("x.md", 1, markdown_text(md))], [])
    assert [(h.line, h.word) for h in hits] == [(7, "channel"), (8, "channel")]


def test_javascript_strings():
    src = (
        "// a channel in a comment\n"
        "const a = 'The channel list', b = \"x/channels\";\n"
        "const r = /channel/g, c = 1 / 2 / 3;\n"
        "el(`Up ${n > 1 ? 'two channels' : `one`} next\n now`);\n"
        "const d = 'Library';\n"
        "h('div', { class: `panel channel ${on ? 'channel-on' : ''}` }, 'The channels');\n"
    )
    got = js_strings(src)
    assert (2, "The channel list") in got
    assert (2, "x/channels") in got
    assert (4, "two channels") in got
    assert (4, "Up 0 next\n now") in got
    assert (6, "Library") in got  # (the template above runs to line 5)
    assert (7, "The channels") in got
    assert not any("comment" in t or t == "channel" or "panel" in t or "-on" in t for _, t in got)
    assert _shown("Library") and not _shown("x/channels") and not _shown("channel_id")


def test_python_strings():
    src = (
        '"""A channel in a docstring."""\n'
        "def f(n):\n"
        '    """Another channel."""\n'
        '    "a channel used as a comment"\n'
        '    log.info("Found %d channels", n)\n'
        '    q = "SELECT id FROM channels WHERE x = ?"\n'
        '    key = "channel_id"\n'
        '    return f"{n} channels ready"\n'
        "def g(x):\n"
        "    return f'<channel id=\"{x}\"> or `channel` <b>channels</b>'\n"
    )
    assert [(n, " ".join(t.split())) for n, t in python_strings(src)] == [
        (5, "Found %d channels"),
        (8, "0 channels ready"),
        (10, "or channels"),
    ]
