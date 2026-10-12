"""StationPlay's own new versions: once a day, whether a newer release than
this one is out (the update check: on to start, offered in first-run setup,
an Admin's setting), and what the page's banner says to update, for this
kind of install (STATIONPLAY_INSTALL, set in the YAML or compose file).

The check asks GitHub's list of StationPlay's releases for the latest one
(api.github.com, its public API: no account, nothing sent but the request
itself, with StationPlay's version in its User-Agent). It waits 10 seconds,
follows no redirect, and keeps only the version found, its page's address
and when it looked. It never downloads anything, and never updates by
itself: each kind of install updates its image its own way, and the banner
says how (see STEPS). Off, it contacts nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from . import __version__

if TYPE_CHECKING:
    from .db import Database

log = logging.getLogger(__name__)

META = "update_check"  # the setting, as JSON: {"on": true or false}
SEEN_META = "update_seen"  # what the last look found, as JSON (see Seen)
LATEST = "https://api.github.com/repos/egadgetboy/stationplay/releases/latest"
RELEASES = "https://github.com/egadgetboy/stationplay/releases"
README = "https://github.com/egadgetboy/stationplay#updating"
IMAGE = "ghcr.io/egadgetboy/stationplay"
FIRST_S = 120.0  # after starting, before the first look
EVERY_S = 86_400.0  # then once a day
AGAIN_S = 3_600.0  # after a look that failed, before trying again
WAIT_S = 10.0  # the longest an answer is waited for
SOONEST_S = 60.0  # Check now, at most this often
VERSION = re.compile(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})")
NOTES_MOST = 300  # characters of an address kept

# Each kind of install, as STATIONPLAY_INSTALL names it: its name, and how
# its image is updated (sentences, then a command to copy, if there's one).
# The YAML and compose files ask for :latest with pull_policy: always.
STEPS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "truenas": (
        "TrueNAS",
        (
            "In TrueNAS, open Apps, then StationPlay.",
            "If it offers Update, choose it.",
            "If it doesn't, choose Edit, then Save: TrueNAS fetches the newest image.",
        ),
        "",
    ),
    "compose": (
        "Docker Compose",
        ("In the folder with StationPlay's docker-compose.yml, run:",),
        "docker compose pull && docker compose up -d",
    ),
    "docker-desktop": (
        "Docker Desktop",
        ("In a terminal, in the folder with StationPlay's docker-compose.yml, run:",),
        "docker compose pull && docker compose up -d",
    ),
    "unraid": (
        "Unraid",
        ("On Unraid's Docker tab, StationPlay shows an update: choose apply update.",),
        "",
    ),
    "synology": (
        "Synology",
        (
            "In Container Manager, open Project, then StationPlay's project.",
            "Choose Stop, then Build: Container Manager fetches the newest image and starts it.",
        ),
        "",
    ),
    "docker-run": (
        "docker run",
        (
            "Fetch the newest image, then remove the container and start it again with the same "
            "docker run command as before:",
        ),
        f"docker pull {IMAGE}:latest && docker stop stationplay && docker rm stationplay",
    ),
}
ANY = (
    "",
    (
        "Update StationPlay's image the way you installed it. The README's Updating section has "
        "the steps for each kind of install.",
    ),
    "",
)


def as_tuple(version: str) -> tuple[int, int, int] | None:
    """A version ("1.34.0", or a tag: "v1.34.0") as numbers to compare;
    None if it isn't one."""
    found = VERSION.fullmatch(version.strip())
    return (int(found[1]), int(found[2]), int(found[3])) if found else None


def newer(found: str, current: str = __version__) -> bool:
    """Whether `found` is a newer version than `current`."""
    a, b = as_tuple(found), as_tuple(current)
    return a is not None and b is not None and a > b


def steps(install: str) -> dict[str, Any]:
    """How this kind of install updates its image, for the banner."""
    name, said, command = STEPS.get(install.strip().lower(), ANY)
    return {"install": name, "steps": list(said), "command": command or None, "readme": README}


@dataclass(frozen=True)
class Seen:
    """What the last look found: when, the newest version out (or "") and
    its page, or why there was nothing to go on."""

    at_ms: int
    version: str
    url: str
    problem: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"at": self.at_ms, "version": self.version, "url": self.url, "problem": self.problem}


def _seen(got: Any) -> Seen | None:
    try:
        return Seen(int(got["at"]), str(got["version"]), str(got["url"]), str(got["problem"]))
    except (KeyError, TypeError, ValueError):
        return None


def _release_page(url: Any, version: str) -> str:
    """The release's page, if GitHub's answer gives StationPlay's own;
    otherwise the list of releases."""
    text = str(url or "")
    if text.startswith(RELEASES + "/") and len(text) <= NOTES_MOST:
        return text
    return f"{RELEASES}/tag/v{version}"


class Releases:
    """The update check (see the module's notes)."""

    # In tests, what answers at GitHub.
    transport: httpx.AsyncBaseTransport | None = None

    def __init__(self, db: Database, install: str = "") -> None:
        self.db = db
        self.install = install
        try:
            saved = json.loads(db.get_meta(META, "") or "{}")
        except ValueError:
            saved = {}
        # (On to start, for a new server and one updated from before 1.34.0.)
        self.on = not (isinstance(saved, dict) and saved.get("on") is False)
        self._last_asked = 0.0

    @property
    def seen(self) -> Seen | None:
        try:
            return _seen(json.loads(self.db.get_meta(SEEN_META, "") or "null"))
        except ValueError:
            return None

    def save(self, on: bool) -> None:
        self.on = on
        self.db.set_meta(META, json.dumps({"on": on}))

    def as_json(self) -> dict[str, Any]:
        """For the page: the setting, this version, the newest one found
        (when it's newer), and how this install updates."""
        seen = self.seen
        latest = seen.version if seen and self.on and newer(seen.version) else ""
        return {
            "on": self.on,
            "current": __version__,
            "latest": {"version": latest, "url": seen.url} if latest and seen else None,
            "checked": seen.as_dict() if seen else None,
            **steps(self.install),
        }

    async def run_forever(self) -> None:
        """Looks a little after starting, then once a day, while it's on."""
        await asyncio.sleep(FIRST_S)
        while True:
            wait = EVERY_S
            if self.on:
                seen = await self.check()
                if seen.problem:
                    wait = AGAIN_S
            await asyncio.sleep(wait)

    async def check_now(self) -> Seen:
        """Check now (an Admin's Check now: at most once a minute)."""
        now = time.monotonic()
        if self._last_asked and now - self._last_asked < SOONEST_S and (seen := self.seen):
            return seen
        self._last_asked = now
        return await self.check()

    async def check(self) -> Seen:
        """Asks GitHub for StationPlay's latest release, and keeps what it
        found (see the module's notes)."""
        at = int(time.time() * 1000)
        headers = {
            "User-Agent": f"StationPlay/{__version__}",
            "Accept": "application/vnd.github+json",
        }
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=WAIT_S, follow_redirects=False, trust_env=False
            ) as client:
                got = await asyncio.wait_for(client.get(LATEST, headers=headers), WAIT_S)
            if got.status_code != 200:
                seen = Seen(at, "", "", f"GitHub answered {got.status_code}")
            else:
                answer = got.json()
                tag = str(answer.get("tag_name") or "") if isinstance(answer, dict) else ""
                found = as_tuple(tag)
                if found is None:
                    seen = Seen(at, "", "", "GitHub's answer named no version")
                else:
                    version = ".".join(map(str, found))
                    seen = Seen(at, version, _release_page(answer.get("html_url"), version))
        except (TimeoutError, httpx.HTTPError, ValueError):
            seen = Seen(at, "", "", "GitHub couldn't be reached")
        if seen.problem:
            log.info("The update check couldn't tell whether a new StationPlay is out (%s)",
                     seen.problem)  # fmt: skip
            # (What was found before stays known.)
            before = self.seen
            if before and before.version:
                seen = Seen(at, before.version, before.url, seen.problem)
        elif newer(seen.version) and (self.seen is None or self.seen.version != seen.version):
            log.info("StationPlay %s is available (this is %s)", seen.version, __version__)
        self.db.set_meta(SEEN_META, json.dumps(seen.as_dict()))
        return seen
