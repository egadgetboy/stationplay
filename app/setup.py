"""The setup: the questions an Admin answers when tapiOca is new, and
again, just the new ones, when an update brings something that needs an
answer; and the checks that say whether what's set up is working.

Each question has a version. When a question changes (it gains a choice,
say), its version goes up, and after the update the setup opens by itself,
once, with just the questions that are new or changed. What's been
answered is kept in `meta` (META_ANSWERED: each question's version when it
was answered). Run again from the Add to Plex tab, the setup asks
everything, with the current answers filled in. The page asks the
questions (web/js/setup.js); this says which, and runs the
checks.

The first step's checks look at the server itself: its media folder, video
encoding, the clock and backups. None of them waits on Plex, which is
checked in the Plex step: whether it answers, whether tapiOca finds the
files Plex lists, and whether Plex has tapiOca as a DVR (1.34.1, the
owner: a new tapiOca said Plex was Not working on the first page, before
there was any chance to connect it). Each gives a state ("good", "warn" for something to look at,
"bad" for something that keeps tapiOca from working, "info" for
something to know, "wait" for something that can't be checked yet), a
title, and a sentence or two, with what to do when something's wrong.
Nothing is guessed: a check that can't tell says so.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import backups, playback
from .playing import ago
from .plex import PlexError
from .sources import find_first, learn_mapping, local_candidates

if TYPE_CHECKING:
    from .main import AppContext

log = logging.getLogger(__name__)

META_ANSWERED = "setup_answered"  # {question: its version when answered} (JSON)

# The questions, in the order they're asked, with their versions.
QUESTIONS: dict[str, int] = {
    "playback": 1,  # how stations play: the picture size and the tuners
    "newStation": 1,  # what new stations start with
    "signIn": 1,  # who can use tapiOca
    "viewing": 1,  # who sees what: Viewing Levels (1.23)
    "away": 1,  # tapiOca's apps away from home
    "library": 2,  # Media in tapiOca's apps (2: on to start, 1.34.1)
    "fileChecks": 1,  # the overnight deep scan
    "plex": 1,  # adding tapiOca to Plex
}
# The questions the welcome before this one asked (until 1.22.3): someone who
# saw it answered them. Its version "3" added which corner, so with an
# earlier one, what new stations start with is asked again.
WELCOME_ASKED = ("playback", "newStation", "signIn", "fileChecks", "plex")


def answered(db: Any) -> dict[str, int]:
    """Each question answered, and its version then."""
    try:
        got = json.loads(db.get_meta(META_ANSWERED) or "{}")
    except ValueError:
        return {}
    if not isinstance(got, dict):
        return {}
    return {q: v for q, v in got.items() if q in QUESTIONS and type(v) is int}


def pending(db: Any) -> list[str]:
    """The questions not yet answered, or changed since, in the order they're asked."""
    done = answered(db)
    return [q for q, version in QUESTIONS.items() if done.get(q, 0) < version]


def mark(db: Any, questions: list[str]) -> list[str]:
    """Marks these questions answered, as they are now; what's still to
    answer. ValueError for one that isn't a question."""
    unknown = [q for q in questions if q not in QUESTIONS]
    if unknown:
        raise ValueError(f"{unknown[0]!r} isn't a question in the setup")
    done = answered(db)
    done.update({q: QUESTIONS[q] for q in questions})
    db.set_meta(META_ANSWERED, json.dumps(done, sort_keys=True))
    return pending(db)


def start(
    db: Any, stations: int, away_on: bool, sharing: bool, others: bool = False, chose: bool = False
) -> None:
    """At startup, the first time with this setup: what a tapiOca set up
    before it has already answered. A new one (no stations, no welcome seen)
    is asked everything. Otherwise, what the welcome asked counts as answered;
    so do the apps away from home, and your library in the apps, if they're
    already on. The rest (for tapiOca set up before them, perhaps
    without anyone noticing them) are asked once.

    Who sees what is asked of a tapiOca set up before it only if there
    are people to choose for (`others`: Users, not Admins). Media in the
    apps, on to start from 1.34.1, is asked again once, unless an Admin
    has chosen which folders (`chose`)."""
    if db.get_meta(META_ANSWERED):
        if not others and "viewing" in pending(db):
            mark(db, ["viewing"])
        if chose and "library" in pending(db):
            mark(db, ["library"])
        return
    welcomed = db.get_meta(playback.META_WELCOMED, "")
    if not welcomed and not stations:
        return
    done = [q for q in WELCOME_ASKED if q != "newStation" or welcomed == playback.WELCOME]
    if away_on:
        done.append("away")
    if sharing:
        done.append("library")
    if not others:
        done.append("viewing")
    mark(db, done)
    still = pending(db)
    if still:
        log.info("The setup has new questions: it opens for an Admin with %s", ", ".join(still))


def state(db: Any, stations: int) -> dict[str, Any]:
    """What the page needs: the questions in order, which are still to
    answer, and whether tapiOca is new (nothing answered, no stations)."""
    left = pending(db)
    return {
        "questions": list(QUESTIONS),
        "pending": left,
        "fresh": not stations and len(left) == len(QUESTIONS),
    }


# The checks -------------------------------------------------------------------------

GOOD, WARN, BAD, INFO, WAIT = "good", "warn", "bad", "info", "wait"

FIND_FILES_S = 8.0  # (as when a program plays: a stuck share can't hold the check up)
PLEX_ASK_S = 5.0  # the longest Plex is waited for, for a check or the page
PLEX_FILES_S = 8.0  # (and for the newest file in each library: a few questions)
BACKUP_FIRST_S = 20 * 60  # the first backup comes within 15 minutes of starting
BACKUP_OLD_S = 2 * 86400  # one a night: older than this, something's stopping them


@dataclass
class Check:
    id: str
    title: str
    state: str
    lines: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "state": self.state, "lines": self.lines}


def _sentence(text: str) -> str:
    """A sentence from elsewhere (Plex's errors, the GPU's notes): ending as
    one does, with the page's apostrophes."""
    text = text.strip().replace("'", "’")
    return text if text.endswith((".", "!", "?")) else text + "."


def plex_check(plex_state: dict[str, Any], plex_pass: bool | None) -> Check:
    title = "Plex"
    if not plex_state.get("configured"):
        return Check("plex", title, BAD, [
            "tapiOca isn’t connected to Plex: PLEX_URL and PLEX_TOKEN aren’t set.",
            "Set both in tapiOca’s app settings (its YAML, or its Compose file), then "
            "restart tapiOca. The README’s “Finding your Plex token” shows where to find "
            "the token.",
        ])  # fmt: skip
    if not plex_state.get("ok"):
        if plex_state.get("trouble"):
            # (What happened, and what to check for that: see plex.trouble.)
            return Check("plex", title, BAD, [_sentence(str(plex_state["trouble"]))])
        return Check("plex", title, BAD, [
            _sentence(str(plex_state.get("error") or "Plex didn’t answer")),
            "Check that Plex is running, and that PLEX_URL in tapiOca’s app settings is "
            "its address, such as http://192.168.1.20:32400.",
        ])  # fmt: skip
    version = plex_state.get("version")
    lines = [f"tapiOca is connected to Plex{f' {version}' if version else ''}."]
    if plex_pass is False:
        lines.append(
            "The account that owns this Plex server doesn’t have Plex Pass, which Plex’s "
            "Live TV & DVR needs to show your stations in Plex. Jellyfin, Emby, Kodi and "
            "tapiOca’s own apps don’t need it."
        )
        return Check("plex", title, WARN, lines)
    if plex_pass:
        lines.append("Plex Pass is on the account that owns this Plex server, so your "
                     "stations can be watched in Plex.")  # fmt: skip
    return Check("plex", title, GOOD, lines)


# The media folder ---------------------------------------------------------------------
# MEDIA_DIR (and any folder PATH_MAPPINGS names), looked at directly, with
# or without Plex: whether it's there, whether it can be read, what it
# holds, and whether a video in it can be read.

VIDEO_ENDINGS = (
    ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".m2ts", ".mts", ".wmv", ".webm", ".mpg",
    ".mpeg", ".flv", ".vob",
)  # fmt: skip
FOLDER_LOOK_S = 8.0  # (a stuck share can't hold the check up)
LOOK_MOST = 2000  # entries looked through, at most, for a video to read
LOOK_DEEP = 4  # folders down, at most
FOLDERS_SHOWN = 3


def _system(name: str) -> bool:
    """A name a system keeps, not media: hidden, a NAS's own (@eaDir,
    #recycle), or a disk's lost+found."""
    return name.startswith((".", "@", "#", "$")) or name in (
        "lost+found",
        "System Volume Information",
    )


@dataclass
class Folder:
    """What looking at a folder found. `state`: "ok", "missing", "denied",
    "empty" or "error" (`error` says what)."""

    state: str
    folders: list[str]  # the folders in it, by name (not the system's own)
    files: int  # the files in it (not in its folders)
    video: str | None = None  # a video in it (or below), read
    video_problem: str | None = None  # "denied", or why `video` couldn't be read
    error: str = ""


def look_at_folder(path: str) -> Folder:
    """Looks at a folder (run off the event loop: a share can be slow)."""
    try:
        if not os.path.isdir(path):
            return Folder("missing", [], 0)
        with os.scandir(path) as found:
            entries = [e for e in found if not _system(e.name)]
    except PermissionError:
        return Folder("denied", [], 0)
    except OSError as e:
        return Folder("error", [], 0, error=e.strerror or type(e).__name__)
    if not entries:
        return Folder("empty", [], 0)
    folders = sorted((e.name for e in entries if _is_dir(e)), key=str.casefold)
    files = sum(1 for e in entries if not _is_dir(e))
    video = _a_video(path)
    return Folder("ok", folders, files, video, _read_problem(video) if video is not None else None)


def _is_dir(entry: os.DirEntry) -> bool:
    try:
        return entry.is_dir()
    except OSError:
        return False


def _a_video(top: str) -> str | None:
    """A video in a folder or below it (the first found, breadth first),
    looking through at most LOOK_MOST entries."""
    looked = 0
    level = [top]
    for _ in range(LOOK_DEEP):
        below: list[str] = []
        for folder in level:
            try:
                with os.scandir(folder) as found:
                    for e in found:
                        looked += 1
                        if looked > LOOK_MOST:
                            return None
                        if _system(e.name):
                            continue
                        if _is_dir(e):
                            below.append(e.path)
                        elif e.name.lower().endswith(VIDEO_ENDINGS):
                            return e.path
            except OSError:
                continue
        level = sorted(below)
    return None


def _holds(folder: Folder) -> str:
    """What a folder holds, in a few words: "Movies and TV Shows"."""
    if folder.folders:
        names = folder.folders[:FOLDERS_SHOWN]
        more = len(folder.folders) - len(names)
        if more:
            return f"{', '.join(names)} and {more} other folder{'s' if more != 1 else ''}"
        return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    return f"{folder.files} file{'s' if folder.files != 1 else ''}"


def folders_check(looked: list[tuple[str, Folder | None]], media_dir: str) -> Check:
    """The media folder check: what looking at MEDIA_DIR and the folders
    PATH_MAPPINGS names found (None: it took too long)."""
    shown = [
        (path, f)
        for path, f in looked
        # (Nothing at MEDIA_DIR is fine while PATH_MAPPINGS points elsewhere.)
        if not (
            path == media_dir
            and f is not None
            and f.state == "missing"
            and any(g is not None and g.state == "ok" for _, g in looked[1:])
        )
    ]
    title = "Your media folders" if len(shown) > 1 else "Your media folder"
    lines: list[str] = []
    fixes: list[str] = []
    for path, f in shown:
        if f is None:
            lines.append(
                f"Reading {path} took too long. A network share may be slow or out of reach."
            )
            fixes.append("slow")
        elif f.state == "missing":
            lines.append(f"Nothing is mounted at {path}.")
            fixes.append("missing")
        elif f.state == "denied":
            lines.append(f"tapiOca isn’t allowed to read {path}.")
            fixes.append("denied")
        elif f.state == "error":
            lines.append(f"tapiOca couldn’t read {path} ({f.error}).")
            fixes.append("slow")
        elif f.state == "empty":
            lines.append(f"{path} is empty.")
            fixes.append("empty")
        elif f.video_problem == "denied":
            lines.append(f"tapiOca can see {path} but isn’t allowed to read the videos in it.")
            fixes.append("denied")
        elif f.video_problem:
            lines.append(
                f"tapiOca can see {path} but couldn’t read a video in it ({f.video_problem})."
            )
            fixes.append("slow")
        else:
            lines.append(f"tapiOca can read {path}, which holds {_holds(f)}.")
    if not fixes:
        lines.append("The Plex step checks that tapiOca finds the files Plex lists.")
        return Check("media", title, GOOD, lines)
    if "denied" in fixes:
        lines.append(
            "Give the user tapiOca runs as (1000, unless you changed it) permission to read "
            "your media, then choose Check again."
        )
    if "missing" in fixes:
        lines.append(
            "tapiOca can still stream your files from Plex, but reading them from disk is faster "
            f"and puts less load on Plex. Mount your media folder at {media_dir} in tapiOca’s app "
            "settings (its YAML or Compose file), then restart tapiOca."
        )
    if "empty" in fixes:
        lines.append(
            "If your media is on a share or another disk, check that it’s mounted on the server, "
            "then restart tapiOca."
        )
    if "slow" in fixes and not {"missing", "empty"} & set(fixes):
        lines.append("Until tapiOca can read it, it streams your files from Plex.")
    return Check("media", title, WARN, lines)


async def media_check(ctx: AppContext, plex_ok: bool, present: bool) -> Check:
    """(The Plex step.) Whether tapiOca can read the files Plex has: the
    newest in a library, looked for where tapiOca looks when a program
    plays."""
    title = "Plex’s files"
    media_dir = ctx.settings.media_dir
    if not plex_ok:
        return Check(
            "plexFiles", title, WAIT, ["This is checked once tapiOca is connected to Plex."]
        )
    try:
        files = await asyncio.wait_for(ctx.plex.newest_files(), PLEX_FILES_S)
    except (PlexError, TimeoutError):
        return Check(
            "plexFiles", title, WAIT, ["Plex didn’t say which files it has. Try again in a moment."]
        )
    if not files:
        return Check("plexFiles", title, INFO, [
            "Plex doesn’t list any shows or movies yet, so there’s nothing to check. Add them "
            "in Plex, then check again.",
        ])  # fmt: skip
    plex_file = files[0]
    name = os.path.basename(plex_file)
    found, timed_out = await find_first(
        local_candidates(ctx.settings, ctx.media_access, plex_file), FIND_FILES_S
    )
    problem = await asyncio.to_thread(_read_problem, found.path) if found is not None else None
    if found is not None and problem is None:
        learn_mapping(ctx.media_access, found)
        return Check("plexFiles", title, GOOD, [
            f"tapiOca reads your files straight from disk: it found {name} at {found.path}.",
        ])  # fmt: skip
    slower = "That works, but reading files from disk is faster and puts less load on Plex."
    if timed_out:
        return Check("plexFiles", title, WARN, [
            f"Looking for {name} in {media_dir} took too long. A network share may be slow or "
            "out of reach, so tapiOca streams files from Plex for now.",
            slower,
        ])  # fmt: skip
    if found is not None and problem == "denied":
        return Check("plexFiles", title, WARN, [
            f"tapiOca found {found.path} but isn’t allowed to read it, so it streams files "
            "from Plex. Give the user tapiOca runs as (1000, unless you changed it) "
            "permission to read your media.",
            slower,
        ])  # fmt: skip
    if found is not None:
        return Check("plexFiles", title, WARN, [
            f"tapiOca found {found.path} but couldn’t read it ({problem}), so it streams "
            "files from Plex. The disk or share it’s on may have a problem.",
            slower,
        ])  # fmt: skip
    if not present:
        return Check("plexFiles", title, WARN, [
            f"Nothing is mounted at {media_dir}, so tapiOca streams files from Plex.",
            slower + f" Mount your media folder at {media_dir} in tapiOca’s app settings.",
        ])  # fmt: skip
    return Check("plexFiles", title, WARN, [
        f"tapiOca couldn’t find {name} in {media_dir} (Plex has it at {plex_file}), so it "
        "streams files from Plex.",
        slower + f" Mount the folder that holds your shows and movies at {media_dir}, or set "
        "PATH_MAPPINGS (see “How tapiOca reads your files” in the README).",
    ])  # fmt: skip


def _read_problem(path: str) -> str | None:
    """Why the start of a file can't be read ("denied": not allowed); None if it can."""
    try:
        with open(path, "rb") as f:
            f.read(4096)
        return None
    except PermissionError:
        return "denied"
    except OSError as e:
        return e.strerror or type(e).__name__


# GPU notes that only say there's no GPU (or that it's turned off): those
# are something to know, not something to fix.
PLAIN_CPU = ("tapiOca can't see a GPU.", "GPU encoding is turned off (HW_ACCEL=cpu).")


def encoding_check(encoding: dict[str, Any], tone_mapping: bool, subtitling: bool) -> Check:
    title = "Video encoding"
    state = encoding.get("state")
    note = str(encoding.get("note") or "")
    lines: list[str]
    if state == "starting":
        return Check(
            "encoding",
            title,
            WAIT,
            ["tapiOca is still checking for a GPU. Check again in a minute."],
        )
    if state == "gpu":
        verdict, lines = GOOD, [f"Video is encoded on the {encoding.get('active')}."]
    elif state == "disabled":
        verdict, lines = BAD, [_sentence(note)]
    elif encoding.get("tested") or (note and note not in PLAIN_CPU):
        verdict, lines = WARN, [f"Video is encoded on the CPU. {_sentence(note)}"]
    else:
        verdict = INFO
        lines = [
            f"Video is encoded on the CPU. {_sentence(note)}"
            if note
            else "Video is encoded on the CPU.",
            "That works. A GPU lets this server play more stations at once: see “GPU encoding” "
            "in the README.",
        ]
    if not tone_mapping:
        lines.append(
            "tapiOca’s ffmpeg can’t convert HDR to standard color, so HDR programs look "
            "washed out. The Logs tab says why."
        )
        verdict = WARN if verdict in (GOOD, INFO) else verdict
    if not subtitling:
        lines.append(
            "tapiOca can’t draw subtitles, so programs play without them. The Logs tab says why."
        )
        verdict = WARN if verdict in (GOOD, INFO) else verdict
    return Check("encoding", title, verdict, lines)


def _zone_offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "−"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours}" + (f":{rest:02d}" if rest else "")


def clock_check(browser_offset: int | None, browser_zone: str, now: float | None = None) -> Check:
    """tapiOca's clock (its time zone, from TZ) against the browser's:
    schedules, blocks and the guide follow tapiOca's. `browser_offset`:
    the browser's minutes ahead of UTC."""
    title = "The clock"
    local = time.localtime(now)
    ours = local.tm_gmtoff // 60
    zone = os.environ.get("TZ", "").strip() or local.tm_zone or _zone_offset(ours)
    plain = zone == _zone_offset(ours) or (ours == 0 and zone.upper() in ("UTC", "GMT", "ETC/UTC"))
    shown = zone if plain else f"{zone} ({_zone_offset(ours)})"
    if browser_offset is None:
        return Check("clock", title, INFO, [
            f"tapiOca’s clock is set to {shown}. Schedules, blocks and the guide follow it.",
        ])  # fmt: skip
    if browser_offset == ours:
        return Check("clock", title, GOOD, [
            f"tapiOca’s clock is set to {shown}, the same as this browser’s. Schedules, "
            "blocks and the guide follow it.",
        ])  # fmt: skip
    theirs = browser_zone.strip()[:60] or _zone_offset(browser_offset)
    hours = abs(browser_offset - ours) / 60
    apart = f"{hours:g} hour{'s' if hours != 1 else ''}"
    return Check("clock", title, WARN, [
        f"tapiOca’s clock is set to {shown}, but this browser’s is {theirs}, {apart} apart. "
        "Schedules, blocks and the guide follow tapiOca’s clock.",
        f"If this browser is right, set TZ in tapiOca’s app settings to your time zone "
        f"(such as {theirs if '/' in theirs else 'America/Chicago'}), then restart tapiOca.",
    ])  # fmt: skip


def backups_check(made: list[dict[str, Any]], up_s: float, now_ms: int) -> Check:
    """The newest backup (`made`: backups.list_backups, newest first)."""
    title = "Backups"
    if not made:
        if up_s < BACKUP_FIRST_S:
            return Check("backups", title, WAIT, [
                "tapiOca makes its first backup within 15 minutes of starting, then one "
                "every night.",
            ])  # fmt: skip
        return Check("backups", title, BAD, [
            "tapiOca hasn’t been able to make a backup. Check that its data folder has room, "
            "and look on the Logs tab for why.",
        ])  # fmt: skip
    age_s = (now_ms - made[0]["made"]) / 1000
    when = ago(age_s)
    if age_s > BACKUP_OLD_S:
        return Check("backups", title, WARN, [
            f"The newest backup is from {when}. tapiOca backs up every night, so look on the "
            "Logs tab for why it hasn’t since.",
        ])  # fmt: skip
    return Check("backups", title, GOOD, [
        f"tapiOca last backed up your stations and settings {when}. It keeps the last "
        f"{backups.KEEP}, in the backups folder inside its data folder.",
    ])  # fmt: skip


def dvr_check(plex_ok: bool, guide: dict[str, Any], now_ms: int) -> Check:
    """Whether Plex has tapiOca as a DVR (it's found when tapiOca
    looks, as the Add to Plex tab does), and when Plex last downloaded its guide."""
    title = "tapiOca in Plex"
    if not plex_ok:
        return Check("dvr", title, WAIT, ["This is checked once tapiOca is connected to Plex."])
    downloaded = guide.get("plexDownloadedGuide")
    if guide.get("canRefreshPlexGuide"):
        lines = ["Plex has tapiOca as a DVR, so your stations are in its Live TV guide."]
        if downloaded:
            lines.append(
                f"Plex last downloaded tapiOca’s guide {ago((now_ms - downloaded) / 1000)}."
            )
        return Check("dvr", title, GOOD, lines)
    return Check("dvr", title, INFO, [
        "Plex doesn’t have tapiOca as a DVR yet. Adding it takes a few steps in Plex, shown "
        "in this setup and on the Add to Plex tab. (To watch only in Jellyfin, Emby, Kodi or "
        "tapiOca’s own apps, you can skip them.)",
    ])  # fmt: skip
