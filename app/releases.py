"""StationPlay's own new versions: once a day, whether a newer release than
this one is out (the update check, an Admin's choice), and what the page's
banner says to update, for this kind of install (STATIONPLAY_INSTALL, set
in the YAML or compose file).

Nothing is asked of GitHub until an Admin says yes (the audit of 1.34.0):
a new server asks in setup's last step, and one updated from before 1.34.0
asks once, on the page. Even then, nothing is asked until setup is done.
Off, or not answered, it contacts nothing.

The check asks GitHub for StationPlay's latest release (api.github.com, its
public API: no account, nothing sent but the request itself, with
StationPlay's version in its User-Agent; GitHub sees the server's internet
address, as any website does). It asks by the repository's number, which
stays the same if the repository is renamed or moved. It waits 10 seconds,
follows no redirect, and keeps only the version found, its page's address
and when it looked. It never downloads anything, and never updates by
itself: each kind of install updates its image its own way, and the banner
says how (see STEPS).

The first start after an update says so in the log, once (note_version).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from . import __version__

if TYPE_CHECKING:
    from collections.abc import Callable

    from .db import Database

log = logging.getLogger(__name__)

META = "update_check"  # the Admin's answer, as JSON: {"on": true or false} (none: not yet)
SEEN_META = "update_seen"  # what the last look found, as JSON (see Seen)
VERSION_META = "version_started"  # the version that last started (from 1.34.0)
# StationPlay's repository on GitHub, by its number, which a rename or move
# doesn't change (gh api repos/egadgetboy/stationplay --jq .id).
REPOSITORY_ID = 1414995565
LATEST = f"https://api.github.com/repositories/{REPOSITORY_ID}/releases/latest"
RELEASES = "https://github.com/egadgetboy/stationplay/releases"
README = "https://github.com/egadgetboy/stationplay#updating"
IMAGE = "ghcr.io/egadgetboy/stationplay"
FIRST_S = 120.0  # after starting, before the first look
EVERY_S = 86_400.0  # then once a day
AGAIN_S = 3_600.0  # after a look that failed, before trying again
WAITING_S = 600.0  # answered yes, setup not done yet: before seeing again
WAIT_S = 10.0  # the longest an answer is waited for
SOONEST_S = 60.0  # Check now, at most this often
VERSION = re.compile(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})")
NOTES_MOST = 300  # characters of an address kept

# Each kind of install, as STATIONPLAY_INSTALL names it: its name, the
# banner's heading, how its image is updated (sentences), and a command to
# copy, if there's one. Each fetches the newest image as it updates, so
# starting StationPlay never needs the internet (the YAML and compose files
# ask for :latest, and Docker fetches it only when it hasn't got it). No
# command has &&: PowerShell, in Docker Desktop on Windows, hasn't got it.
IMAGE_LATEST = f"{IMAGE}:latest"
STEPS: dict[str, tuple[str, str, tuple[str, ...], str]] = {
    "truenas": (
        "TrueNAS",
        "To update on TrueNAS:",
        (
            "In TrueNAS, open Apps, then StationPlay. If it offers Update, choose it.",
            "If it doesn't, open System, then Shell, and run the command below. Then open Apps, "
            "choose StationPlay, and choose Edit, then Save.",
            "These TrueNAS steps haven't been confirmed yet. If StationPlay still shows this "
            "version afterward, see All the steps.",
        ),
        f"sudo docker pull {IMAGE_LATEST}",
    ),
    "compose": (
        "Docker Compose",
        "To update with Docker Compose:",
        ("In the folder with StationPlay's docker-compose.yml, run:",),
        "docker compose up -d --pull always",
    ),
    "docker-desktop": (
        "Docker Desktop",
        "To update with Docker Desktop:",
        ("In a terminal, in the folder with StationPlay's docker-compose.yml, run:",),
        "docker compose up -d --pull always",
    ),
    "unraid": (
        "Unraid",
        "To update on Unraid:",
        (
            "On Unraid's Docker tab, choose Check for Updates. When StationPlay shows an update, "
            "choose apply update.",
        ),
        "",
    ),
    "synology": (
        "Synology",
        "To update on Synology:",
        (
            "Connect over SSH, go to StationPlay's folder (such as /volume1/docker/stationplay), "
            "and run the command below.",
            "Container Manager's own way (open Project, choose StationPlay's project, then Stop "
            "and Build) hasn't been confirmed yet to fetch the newest image, so these steps "
            "haven't been confirmed yet either way. If StationPlay still shows this version "
            "afterward, see All the steps.",
        ),
        "sudo docker compose up -d --pull always",
    ),
    "docker-run": (
        "docker run",
        "To update with docker run:",
        (
            "Fetch the newest image with the command below. Then remove the container with "
            "docker rm -f stationplay (your data stays in its data folder), and start it again "
            "with the same docker run command as before.",
        ),
        f"docker pull {IMAGE_LATEST}",
    ),
}
ANY = (
    "",
    "To update:",
    (
        "Update StationPlay's image the way you installed it. The README's Updating section has "
        "the steps for each kind of install.",
    ),
    "",
)


class NotAsked(Exception):
    """The update check may not ask GitHub: an Admin hasn't said yes, or
    setup isn't done."""


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
    name, heading, said, command = STEPS.get(install.strip().lower(), ANY)
    return {
        "install": name,
        "heading": heading,
        "steps": list(said),
        "command": command or None,
        "readme": README,
    }


def note_version(db: Database, fresh: bool) -> None:
    """The first start after an update says so in the log, once (`fresh`:
    a new server, which has nothing to say). A version before 1.34.0 kept
    none, so from one of those, it says "from an earlier version"."""
    before = db.get_meta(VERSION_META, "")
    if before == __version__:
        return
    if before:
        log.info("Updated from %s to %s", before, __version__)
    elif not fresh:
        log.info("Updated to %s from an earlier version", __version__)
    db.set_meta(VERSION_META, __version__)


def _problem(status: int) -> str:
    """What went wrong, in words for the page, for GitHub's answer's status
    (which only the log gives)."""
    if status in (403, 429):
        return "GitHub asked StationPlay to wait, so it will look again later"
    if status == 404:
        return "GitHub couldn't find StationPlay's releases"
    if 300 <= status < 400:
        return "GitHub pointed somewhere else, which StationPlay doesn't follow"
    return "GitHub couldn't answer just then"


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

    def __init__(
        self, db: Database, install: str = "", set_up: Callable[[], bool] | None = None
    ) -> None:
        self.db = db
        self.install = install
        # Whether setup is done (see setup.py): until it is, nothing is asked.
        self.set_up: Callable[[], bool] = set_up or (lambda: True)
        try:
            saved = json.loads(db.get_meta(META, "") or "{}")
        except ValueError:
            saved = {}
        # The Admin's answer: None until there is one.
        answer = saved.get("on") if isinstance(saved, dict) else None
        self.on: bool | None = answer if isinstance(answer, bool) else None
        self._last_asked = 0.0
        self._answered: asyncio.Event | None = None  # (wakes the daily look: see run_forever)

    @property
    def seen(self) -> Seen | None:
        try:
            return _seen(json.loads(self.db.get_meta(SEEN_META, "") or "null"))
        except ValueError:
            return None

    def allowed(self) -> bool:
        """Whether GitHub may be asked: an Admin said yes, and setup is done."""
        return self.on is True and self.set_up()

    def save(self, on: bool) -> None:
        """An Admin's answer: whether to look."""
        self.on = on
        self.db.set_meta(META, json.dumps({"on": on}))
        if on and self._answered is not None:
            self._answered.set()

    def as_json(self) -> dict[str, Any]:
        """For the page: the answer (null: none yet), whether to ask it now
        (setup done, no answer yet), this version, the newest one found
        (when it's newer), and how this install updates."""
        seen = self.seen
        latest = seen.version if seen and self.on is True and newer(seen.version) else ""
        return {
            "on": self.on,
            "ask": self.on is None and self.set_up(),
            "current": __version__,
            "latest": {"version": latest, "url": seen.url} if latest and seen else None,
            "checked": seen.as_dict() if seen else None,
            **steps(self.install),
        }

    async def run_forever(self) -> None:
        """Looks a little after starting, then once a day, while it may (see
        allowed); an Admin's yes wakes it."""
        self._answered = answered = asyncio.Event()
        await asyncio.sleep(FIRST_S)
        while True:
            wait = EVERY_S
            if self.allowed():
                seen = await self.check()
                if seen.problem:
                    wait = AGAIN_S
            elif self.on is True:
                wait = WAITING_S  # (until setup is done)
            answered.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(answered.wait(), wait)

    async def check_now(self) -> Seen:
        """Check now (an Admin's Check now: at most once a minute).
        NotAsked if GitHub may not be asked."""
        if not self.allowed():
            raise NotAsked
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
        logged = ""
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=WAIT_S, follow_redirects=False, trust_env=False
            ) as client:
                got = await asyncio.wait_for(client.get(LATEST, headers=headers), WAIT_S)
            if got.status_code != 200:
                seen = Seen(at, "", "", _problem(got.status_code))
                logged = f"GitHub answered {got.status_code}"
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
                     logged or seen.problem)  # fmt: skip
            # (What was found before stays known.)
            before = self.seen
            if before and before.version:
                seen = Seen(at, before.version, before.url, seen.problem)
        elif newer(seen.version) and (self.seen is None or self.seen.version != seen.version):
            log.info("StationPlay %s is available (this is %s)", seen.version, __version__)
        self.db.set_meta(SEEN_META, json.dumps(seen.as_dict()))
        return seen
