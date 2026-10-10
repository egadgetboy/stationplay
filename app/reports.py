"""People's reports of problems in what they watch (from 1.30.0): picked
from a list in StationPlay's apps, never typed, about an episode or a movie
(from its page, or the player's menu) or what's on a station now (from the
station's player). StationPlay knows who sent each one, and on what device,
from the app's sign-in.

The choices come from here (GET /api/internal/report-choices), so they can
change without an app update. What a report does depends on what it says:

  * What StationPlay can check (no picture, the picture breaking up, no
    sound, the sound cutting out, stopping before the end, not playing):
    its file is checked at once, at the front of the queue (see
    scanner.Target): around where it happened first, then the quick check,
    then the deep scan if those find nothing and the report said where.
    Found: the file goes on the list, and is replaced as an Admin has that
    set. Not found: the report waits on the Broken files tab, saying
    StationPlay found nothing wrong, for an Admin to dismiss.
  * What a machine can't judge (the sound out of sync, the wrong language,
    the wrong episode or movie, poor picture quality, subtitles):
    StationPlay says what it can tell beside it (the file's sound
    languages, its length against the show's other episodes', its
    picture's size, its subtitles), and it waits for an Admin: Replace
    (Sonarr or Radarr, blocklisting its release, as for a broken file), Find
    a better copy (an upgrade search, keeping the file), or Dismiss. Only an
    Admin's choice replaces anything.
  * Wrong title, details or artwork: for an Admin to fix where the library
    keeps them (for Plex, in Plex), then dismiss.

A report never takes anything off the air, or out of Media, by itself.
Several reports on one program are one row on the tab, each under it. One
report a day per person per program, and ten a day per person, at most; an
Admin can turn reporting off for someone (Can report problems, on the Access
tab). Kept while they're waiting, and 90 days after they're dealt with (the
newest 5,000 at most).
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import access, catalog, jobs, ondemand, playing, replacing, viewing
from .appapi import app_label
from .applibrary import AWAY_OFF
from .arr import NAMES as ARR_NAMES
from .arr import ArrError
from .broken import REPORTED, file_key, version_key
from .catalog import Entry, Media
from .library import LibraryError, is_folder_key
from .markers import pieces
from .scanner import COULDNT, FOUND, GONE, KEPT, NOTHING, item_of, version_of
from .text import plain

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .main import AppContext

log = logging.getLogger("stationplay.reports")

# The choices, in order: (id, group, label).
CHOICES = (
    ("no-picture", "Picture", "No picture"),
    ("picture-breaks", "Picture", "The picture breaks up or freezes"),
    ("poor-quality", "Picture", "Poor picture quality"),
    ("no-sound", "Sound", "No sound"),
    ("sound-cuts", "Sound", "The sound cuts out"),
    ("out-of-sync", "Sound", "The sound is out of sync"),
    ("wrong-language", "Sound", "Wrong language"),
    ("subtitles", "Subtitles", "Subtitles are missing or wrong"),
    ("wont-play", "The program", "It won't play"),
    ("stops-early", "The program", "It stops before the end"),
    ("wrong-program", "The program", "Wrong episode or movie"),
    ("wrong-details", "Details", "Wrong title, details or artwork"),
)
LABELS = {choice: label for choice, _, label in CHOICES}
# What StationPlay checks; what waits for an Admin; details, for the library.
CHECKED = frozenset(
    {"no-picture", "picture-breaks", "no-sound", "sound-cuts", "stops-early", "wont-play"}
)
LOOKED = frozenset({"out-of-sync", "wrong-language", "wrong-program", "poor-quality", "subtitles"})
DETAILS = frozenset({"wrong-details"})

# What the apps show, as they're sent.
THANKS = "Thanks. An Admin will take a look."
TODAY = "You've reported this one today. Thanks."
ENOUGH = "That's all the reports for today. Thanks for your help."
TURNED_OFF = "An Admin has turned off reporting problems for you."
NOT_A_CHOICE = "Choose a problem from the list"
EPISODE_OR_MOVIE = "Report a problem with an episode or a movie"
ONE_OF_THEM = "Send the key of what you're watching, or its station, not both"
NO_STATION = "There's no such station"
NOTHING_ON = "Nothing's on that station right now"
# The limits: one a day per person per program; this many a day per person.
A_DAY = 10
KEEP_DAYS = 90
KEEP = 5000
COUNT_S = 10.0  # (how long the tab's count is kept: see Reports.needing_count)

# Where a report is: being checked; waiting for an Admin (what they're to
# choose, or what the check found, or didn't); or dealt with.
CHECKING, WAITING = "checking", "waiting"
REPLACING, BETTER, DISMISSED = "replacing", "better", "dismissed"
# (What a check came to: see scanner.Target. FOUND and GONE are dealt with;
# NOTHING, KEPT and COULDNT wait for an Admin.)
OPEN = (CHECKING, WAITING, NOTHING, KEPT, COULDNT)
NEEDS_YOU = (WAITING, NOTHING, KEPT, COULDNT)


def choices() -> list[dict[str, str]]:
    return [{"id": c, "group": g, "label": label} for c, g, label in CHOICES]


def named(program: dict[str, Any]) -> str:
    """A program as an Admin's alert says it: "Northbound S2 E4", "Jaws
    (1975)"."""
    show, season, episode = program.get("show"), program.get("season"), program.get("episode")
    if show:
        if isinstance(season, int) and isinstance(episode, int):
            return f"{show} S{season} E{episode}"
        return f"{show}: {program.get('title') or 'an episode'}"
    year = program.get("year")
    return f"{program.get('title') or 'a movie'}" + (f" ({year})" if year else "")


def _clock(ms: int | None) -> str:
    return playing.clock(ms / 1000) if ms else "0:00"


@dataclass
class Report:
    """One person's report (see the module's notes)."""

    id: int
    at_ms: int
    user_id: int | None
    who: str  # their name, as it was ("" while signing in is off)
    device: str  # which app on which device
    choice: str
    key: str  # the episode or movie
    version: str  # its version's ID ("": its first, as a station plays it)
    station: int | None  # the station's number, if it was on one
    position_ms: int | None
    how: dict[str, Any]  # how it was playing (see describe_how)
    program: dict[str, Any]  # show, title, season, episode, year, showKey, library
    facts: list[str]  # what StationPlay could tell about it (see facts_about)
    state: str
    note: str = ""
    done_ms: int | None = None

    @property
    def label(self) -> str:
        return LABELS.get(self.choice, self.choice)

    @property
    def file_key(self) -> str:
        return version_key(self.key, self.version)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "at": self.at_ms,
            "who": self.who or "Someone",
            "device": self.device,
            "choice": self.choice,
            "label": self.label,
            "station": self.station,
            "positionMs": self.position_ms,
            "how": self.how,
            "version": self.version,
            "state": self.state,
            "note": self.note,
        }


def _report(row: Any) -> Report:
    def loaded(text: str, empty: Any) -> Any:
        try:
            got = json.loads(text or "")
        except ValueError:
            return empty
        return got if isinstance(got, type(empty)) else empty

    return Report(
        id=row["id"], at_ms=row["at_ms"], user_id=row["user_id"], who=row["who"],
        device=row["device"], choice=row["choice"], key=row["rating_key"],
        version=row["version"], station=row["station"], position_ms=row["position_ms"],
        how=loaded(row["how"], {}), program=loaded(row["program"], {}),
        facts=loaded(row["facts"], []), state=row["state"], note=row["note"],
        done_ms=row["done_ms"],
    )  # fmt: skip


# What StationPlay can tell beside a report ------------------------------------------------


def describe_how(
    entry: Entry, media: Media | None, method: str | None, audio: str | None, subtitle: str | None
) -> dict[str, Any]:
    """How it was playing, as the app said, in words for the tab: as it is
    or a copy, which version, which sound track and subtitles."""
    how: dict[str, Any] = {}
    if method in ("direct", "repackage", "convert"):
        how["method"] = {"direct": "as it is", "repackage": "a copy", "convert": "a copy"}[method]
    if media is not None and len(entry.media) > 1:
        best = ondemand.best_first(entry.media)
        how["version"] = ondemand.version_labels(best)[best.index(media)]
    tracks = media.audio if media is not None else ()
    sound = next((t for t in tracks if audio and t.id == audio), None)
    if sound is not None:
        how["audio"] = ondemand.track_name(sound, True)
    shown = next(
        (
            t
            for t in (media.subtitles if media is not None else ())
            if subtitle and t.id == subtitle
        ),
        None,
    )
    if shown is not None:
        how["subtitle"] = ondemand.track_name(shown, False)
    return how


def facts_about(choice: str, entry: Entry, media: Media | None, others: list[Entry]) -> list[str]:
    """What StationPlay can tell about what a person reported, for an Admin
    to judge it by (`others`: the show's other episodes, for its length)."""
    if media is None:
        return []
    if choice == "wrong-language":
        spoken = list(
            dict.fromkeys(plain(t.language) or "an unknown language" for t in media.audio)
        )
        return [f"Its sound: {', '.join(spoken)}" if spoken else "It has no sound track"]
    if choice == "wrong-program":
        length = ondemand.length_of(entry, media)
        said = [f"It runs {_clock(length)}"] if length else []
        runs = [e.duration_ms for e in others if e.key != entry.key and e.duration_ms]
        if runs and length:
            said.append(
                f"the show's other episodes run about {_clock(int(statistics.median(runs)))}"
            )
        return ["; ".join(said)] if said else []
    if choice == "poor-quality":
        size = media.size_label or "its picture"
        exact = f" ({media.width}×{media.height})" if media.width and media.height else ""
        hdr = f", {ondemand.hdr_label(media)}" if ondemand.hdr_label(media) else ""
        rate = f", {playing.mbps(media.bitrate_kbps)}" if media.bitrate_kbps else ""
        return [f"Its picture: {size}{exact}{hdr}{rate}"]
    if choice == "subtitles":
        if not media.subtitles:
            return ["It has no subtitles"]
        return [
            f"Its subtitles: {', '.join(ondemand.track_name(t, False) for t in media.subtitles)}"
        ]
    return []


# Keeping them -----------------------------------------------------------------------------


class Reports:
    """People's reports, and what's done about them (see the module's notes)."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self._forgot_ms = 0
        self._count: tuple[float, int] | None = None  # (see needing_count)

    # Reading ------------------------------------------------------------------------

    def open(self) -> list[Report]:
        """The reports not dealt with yet, the oldest first."""
        return [_report(r) for r in self.ctx.db.reports_open(OPEN)]

    def found(self, rating_key: str) -> list[Report]:
        """The reports whose check found what took a program's file off the air."""
        return [_report(r) for r in self.ctx.db.reports_of(rating_key, (FOUND,))]

    def rows(self) -> list[dict[str, Any]]:
        """For the Broken files tab: the reports not dealt with, a row for
        each program, the newest first."""
        by_key: dict[str, list[Report]] = {}
        for r in self.open():
            by_key.setdefault(r.key, []).append(r)
        having = jobs.stations_having(self.ctx, set(by_key)) if by_key else {}
        out = [self._row(key, reports, having.get(key, [])) for key, reports in by_key.items()]
        out.sort(key=lambda row: row["at"], reverse=True)
        return out

    def _row(
        self, key: str, reports: list[Report], stations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        newest = max(reports, key=lambda r: r.at_ms)
        program = newest.program
        waiting = [r for r in reports if r.state == WAITING]
        looked = [r for r in waiting if r.choice in LOOKED]
        states = {r.state for r in reports}
        state = next(s for s in (WAITING, KEPT, NOTHING, COULDNT, CHECKING) if s in states)
        actions = ["dismiss"]
        if looked:
            actions = ["replace", "better", "dismiss"]
        facts = list(dict.fromkeys(f for r in reports for f in r.facts))
        notes = list(dict.fromkeys(r.note for r in reports if r.note and r.state != WAITING))
        if any(r.choice in DETAILS for r in waiting):
            notes.append(
                "Fix its title, details or artwork under Needs a match, then choose Dismiss."
                if is_folder_key(key)
                else "Fix its title, details or artwork in Plex (Fix Match, or Edit, on its "
                "page there), then choose Dismiss."
            )
        return {
            "key": key,
            "at": newest.at_ms,
            "program": program,
            "name": named(program),
            "state": state,
            "needs": any(r.state in NEEDS_YOU for r in reports),
            "actions": actions,
            "arr": self._arr(program),
            "facts": facts,
            "notes": notes,
            "on": stations,
            "media": bool(program.get("library"))
            and str(program.get("library")) in self.ctx.shared.keys,
            "reports": [r.as_dict() for r in sorted(reports, key=lambda r: r.at_ms, reverse=True)],
        }

    def _arr(self, program: dict[str, Any]) -> str | None:
        """Sonarr or Radarr, for Replace and Find a better copy: the one for
        a program, while it's on and replaces broken or damaged files (see
        replacing.what); None otherwise."""
        app = replacing.app_for(program)
        if (
            not replacing.enabled(self.ctx.db, app)
            or replacing.what(self.ctx.db) == replacing.MISSING
        ):
            return None
        return ARR_NAMES[app]

    def needing(self) -> list[tuple[int, str, str]]:
        """What needs an Admin on the Broken files tab, as the alert says it
        (see alerts.py): (when, what it is, what to say) for each report row
        waiting for them, and each file StationPlay found that does (see
        replacing.tab_section)."""
        out = []
        for row in self.rows():
            if row["needs"]:
                newest = row["reports"][0]
                out.append(
                    (row["at"], f"report:{row['key']}",
                     f"{newest['who']} reported {newest['label']} on {row['name']}")
                )  # fmt: skip
        entries = self.ctx.broken.entries()
        used = jobs.used_by(self.ctx, entries)
        for e in entries:
            section = replacing.tab_section(self.ctx.db, e, used.get(file_key(e), False))
            if section == replacing.NEEDS_YOU:
                out.append(replacing.needs_you_said(e, named(e)))
        return out

    def needing_count(self) -> int:
        """How many things need an Admin on the Broken files tab (see
        needing): the tab's count, kept COUNT_S (the page asks often)."""
        now = time.monotonic()
        if self._count is None or now - self._count[0] >= COUNT_S:
            self._count = (now, len(self.needing()))
        return self._count[1]

    def changed(self) -> None:
        """Something about the reports changed: counted afresh."""
        self._count = None

    # Sent from the apps --------------------------------------------------------------

    def sent_today(self, user_id: int | None, address: str, key: str) -> tuple[int, bool]:
        """How many reports someone (an address, while signing in is off)
        sent today, and whether one was about `key`."""
        day = time.strftime("%Y-%m-%d")
        rows = self.ctx.db.reports_sent(day, user_id, address if user_id is None else "")
        return len(rows), any(r["rating_key"] == key for r in rows)

    def add(self, report: Report, address: str) -> Report:
        now = int(time.time() * 1000)
        report.at_ms = now
        report.id = self.ctx.db.add_report(
            {
                "at_ms": now, "day": time.strftime("%Y-%m-%d"), "user_id": report.user_id,
                "who": report.who, "device": report.device, "address": address,
                "choice": report.choice, "rating_key": report.key, "version": report.version,
                "station": report.station, "position_ms": report.position_ms,
                "how": json.dumps(report.how), "program": json.dumps(report.program),
                "facts": json.dumps(report.facts), "state": report.state, "note": report.note,
            },
            KEEP,
        )  # fmt: skip
        self._forget_old(now)
        self.changed()
        return report

    def checked(self, ids: list[int], outcome: str, note: str) -> None:
        """What checking a file found, for the reports that asked for it
        (see scanner.Target)."""
        done = outcome in (FOUND, GONE)
        if outcome == KEPT:
            note = f"StationPlay found what's wrong ({note}), but you put it back on the air"
        elif outcome == GONE:
            note = "It's no longer in Plex"
        now = int(time.time() * 1000)
        self.ctx.db.set_reports(ids, outcome, note, now if done else None, only=(CHECKING,))
        self.changed()

    def _forget_old(self, now_ms: int) -> None:
        if now_ms - self._forgot_ms < 3_600_000:
            return
        self._forgot_ms = now_ms
        self.ctx.db.forget_reports(now_ms - KEEP_DAYS * 86_400_000)

    # An Admin's choices ----------------------------------------------------------------

    def _open_of(self, key: str) -> list[Report]:
        found = [r for r in self.open() if r.key == key]
        if not found:
            raise HTTPException(404, "There's no report waiting for that")
        return found

    def dismiss(self, key: str, by: str) -> int:
        reports = self._open_of(key)
        now = int(time.time() * 1000)
        self.ctx.db.set_reports([r.id for r in reports], DISMISSED, f"Dismissed by {by}", now)
        self.changed()
        log.info("%s dismissed the reports on %s", by, named(reports[-1].program))
        return len(reports)

    async def replace(self, key: str, by: str) -> str:
        """Replace: the file reported goes on the list (off the air until its
        new file passes), and Sonarr or Radarr replaces it, blocklisting its
        release, now."""
        reports = [r for r in self._open_of(key) if r.state == WAITING and r.choice in LOOKED]
        if not reports:
            raise HTTPException(400, "Only what StationPlay can't judge is replaced from a report")
        newest = reports[-1]
        app = replacing.app_for(newest.program)
        if not replacing.enabled(self.ctx.db, app):
            raise HTTPException(400, f"{ARR_NAMES[app]} isn't turned on")
        if replacing.what(self.ctx.db) == replacing.MISSING:
            raise HTTPException(
                400, "Sonarr and Radarr replace only missing files now (set on this tab)"
            )
        entry, media = await self._version(newest)
        file_key = newest.file_key
        if self.ctx.broken.entry(file_key) is None:
            said = ", ".join(dict.fromkeys(r.label for r in reports))
            self.ctx.broken.record(
                item_of(entry, media),
                f"Reported: {said}. {by} chose Replace",
                newest.station,
                media.file,
                media.size,
                problem="damaged",
                found=REPORTED,
                version=newest.version,
                library=entry.library or None,
            )
        jobs.start_try_again(self.ctx, file_key)
        note = f"{by} chose Replace: {ARR_NAMES[app]} is replacing it"
        self.ctx.db.set_reports(
            [r.id for r in reports], REPLACING, note, int(time.time() * 1000), only=(WAITING,)
        )
        self.changed()
        return note

    async def better(self, key: str, by: str) -> str:
        """Find a better copy: Sonarr or Radarr searches for an upgrade, and
        the file stays as it is."""
        reports = [r for r in self._open_of(key) if r.state == WAITING and r.choice in LOOKED]
        if not reports:
            raise HTTPException(400, "Only what StationPlay can't judge has a better copy found")
        newest = reports[-1]
        if self._arr(newest.program) is None:
            app = ARR_NAMES[replacing.app_for(newest.program)]
            raise HTTPException(400, f"{app} doesn't replace broken or damaged files now")
        program = {**newest.program, "ratingKey": key}
        try:
            said = await replacing.better_copy(self.ctx, program)
        except replacing.Cant as e:
            raise HTTPException(400, str(e)) from None
        except ArrError as e:
            raise HTTPException(503, str(e)) from None
        except LibraryError as e:
            raise HTTPException(503, f"StationPlay can't reach Plex right now ({e})") from None
        note = f"{by} chose Find a better copy: {said}"
        self.ctx.db.set_reports(
            [r.id for r in reports], BETTER, note, int(time.time() * 1000), only=(WAITING,)
        )
        self.changed()
        return note

    async def _version(self, report: Report) -> tuple[Entry, Media]:
        try:
            entry = await asyncio.wait_for(self.ctx.library.entry(report.key, details=True), 10)
        except (LibraryError, TimeoutError) as e:
            raise HTTPException(503, f"StationPlay can't reach Plex right now ({e})") from None
        if entry is None:
            raise HTTPException(404, "That file is no longer in Plex")
        media = next((m for m in entry.media if version_of(entry, m) == report.version), None)
        if media is None:
            raise HTTPException(404, "That file is no longer in Plex")
        return entry, media


# The apps' addresses ----------------------------------------------------------------------


class ReportIn(BaseModel):
    """A report, as an app sends it (see docs/internal-api.md)."""

    choice: str = Field(max_length=40)
    key: str | None = Field(default=None, max_length=20)
    station: int | None = Field(default=None, ge=1, le=999_999)
    positionMs: int | None = Field(default=None, ge=0, le=7 * 86_400_000)
    method: str | None = Field(default=None, max_length=20)
    version: str | None = Field(default=None, max_length=40)
    audio: str | None = Field(default=None, max_length=40)
    subtitle: str | None = Field(default=None, max_length=40)


def routes(app: FastAPI, ctx: AppContext) -> None:
    """The apps' addresses for reporting a problem, and the Broken files
    tab's for an Admin."""
    reports = ctx.reports

    @app.get("/api/internal/report-choices")
    async def report_choices():
        return {"choices": choices()}

    async def what_it_was(
        body: ReportIn, request: Request
    ) -> tuple[Entry, Media | None, int | None, int | None]:
        """What's reported, as this person may see it: (the episode or
        movie, the version that played, the station's number, where in it)."""
        user = access.signed_in(request)
        if (body.key is None) == (body.station is None):
            raise HTTPException(400, ONE_OF_THEM)
        if body.station is not None:
            channel = ctx.db.get_channel_by_number(body.station)
            if channel is None or not ctx.sees_station(user, channel.id):
                raise HTTPException(404, NO_STATION)
            now = int(time.time() * 1000)
            # (A big shuffle takes a moment to work out.)
            slot = await asyncio.to_thread(ctx.station(channel.id).locate, now)
            if slot is None:
                raise HTTPException(404, NOTHING_ON)
            item = slot.item
            into = max(
                0.0, min((now - slot.start_ms - item.lead_ms) / 1000, item.program_ms / 1000)
            )
            got = pieces(item.segments, into, 1.0)
            at_ms = int((got[0][0] if got else into) * 1000)
            entry = await _library_entry(ctx, item.rating_key)
            media = entry.media[0] if entry.media else None
            return entry, media, channel.number, at_ms
        key = str(body.key)
        if access.outside(request.scope) and not ctx.away.on:
            raise HTTPException(403, AWAY_OFF)
        try:
            async with asyncio.timeout(ondemand.LIBRARY_WAIT_S):
                entry = await ctx.catalog.entry(key)
                await _must_see(ctx, viewing_of(ctx, request), entry)
        except ondemand.NotShared:
            raise HTTPException(404, ondemand.NOT_SHARED) from None
        except LibraryError as e:
            if e.status == 404:
                raise HTTPException(404, ondemand.NOT_SHARED) from None
            raise HTTPException(503, ondemand.UNREACHABLE) from None
        except TimeoutError:
            raise HTTPException(503, ondemand.UNREACHABLE) from None
        if entry.kind not in (catalog.EPISODE, catalog.MOVIE):
            raise HTTPException(400, EPISODE_OR_MOVIE)
        asked = next((m for m in entry.media if body.version and m.id == body.version), None)
        if asked is None:
            # (As it played on this device lately, or else as it plays first.)
            sign_in = _sign_in(request)
            client = request.client.host if request.client else ""
            lately = ctx.plays.lately(sign_in, client)
            same = lately is not None and lately.entry.key == entry.key
            asked = lately.media if same and lately is not None else None
            if asked is None:
                asked = next(iter(ondemand.best_first(entry.media)), None)
        return entry, asked, None, body.positionMs

    @app.post("/api/internal/report-problem")
    async def report_problem(body: ReportIn, request: Request):
        """A person's report (see the module's notes)."""
        if body.choice not in LABELS:
            raise HTTPException(400, NOT_A_CHOICE)
        user = access.signed_in(request)
        if user is not None and not ctx.access.may_report(user):
            raise HTTPException(403, TURNED_OFF)
        entry, media, station, at_ms = await what_it_was(body, request)
        version = version_of(entry, media) if media is not None else ""
        others: list[Entry] = []
        if body.choice == "wrong-program" and entry.kind == catalog.EPISODE and entry.show_key:
            try:
                others = await asyncio.wait_for(ctx.library.show_episodes(entry.show_key), 10)
            except (LibraryError, TimeoutError):
                others = []
        # (The limits, and keeping it, with nothing awaited between: however
        # many come at once, the limits hold.)
        address = access.address(request.scope)
        sent, about_this = reports.sent_today(user.id if user else None, address, entry.key)
        if about_this:
            raise HTTPException(429, TODAY)
        if sent >= A_DAY:
            raise HTTPException(429, ENOUGH)
        how = describe_how(entry, media, body.method, body.audio, body.subtitle)
        if station is not None:
            how = {"station": station}
        report = reports.add(
            Report(
                id=0, at_ms=0, user_id=user.id if user else None, who=user.name if user else "",
                device=_device(ctx, request), choice=body.choice, key=entry.key,
                version=version, station=station, position_ms=at_ms, how=how,
                program=_program(entry), facts=facts_about(body.choice, entry, media, others),
                state=CHECKING if body.choice in CHECKED else WAITING,
            ),
            address,
        )  # fmt: skip
        who = user.name if user else "Someone"
        where = f", at {_clock(at_ms)}" if at_ms is not None else ""
        on = f" on {playing.station(station, '', mid=True)}" if station is not None else ""
        log.warning(
            "%s reported %s in %s%s%s (%s)",
            who, report.label, playing.title(entry), on, where, report.device,
        )  # fmt: skip
        if body.choice in CHECKED and media is not None:
            ctx.scanner.target(
                entry.key,
                version,
                at_ms / 1000 if at_ms is not None else None,
                f"{who} reported {report.label}",
                station,
                report.id,
                full=at_ms is not None,
                label=item_of(entry, media).label,
            )
        return {"detail": THANKS}

    # The Broken files tab ------------------------------------------------------------

    @app.get("/api/reports")
    async def report_rows():
        return {"reports": await asyncio.to_thread(reports.rows), "choices": choices()}

    def by(request: Request) -> str:
        user = access.signed_in(request)
        return user.name if user else "An Admin"

    @app.post("/api/reports/{key}/dismiss")
    async def report_dismiss(key: str, request: Request):
        reports.dismiss(key, by(request))
        return {"reports": await asyncio.to_thread(reports.rows)}

    @app.post("/api/reports/{key}/replace")
    async def report_replace(key: str, request: Request):
        note = await reports.replace(key, by(request))
        log.info("%s", note)
        return {"reports": await asyncio.to_thread(reports.rows), "note": note}

    @app.post("/api/reports/{key}/better")
    async def report_better(key: str, request: Request):
        note = await reports.better(key, by(request))
        log.info("%s", note)
        return {"reports": await asyncio.to_thread(reports.rows), "note": note}


def viewing_of(ctx: AppContext, request: Request) -> viewing.Viewer:
    return ctx.viewing.viewer(access.signed_in(request))


async def _must_see(ctx: AppContext, viewer: viewing.Viewer, entry: Entry) -> None:
    """NotShared (as for what isn't shared) unless `viewer` can see `entry`:
    an episode by its show's rating and library (see applibrary.py)."""
    if viewer.everything:
        return
    show = None
    if entry.kind == catalog.EPISODE and entry.show_key:
        try:
            show = await ctx.catalog.entry(entry.show_key)
        except ondemand.NotShared:
            show = None
    if not viewer.sees(viewing.judge_entry(entry, show)):
        raise ondemand.NotShared(entry.key)


async def _library_entry(ctx: AppContext, key: str) -> Entry:
    """A station's program, as the library has it now (503 if it can't be
    asked; 404 if it's gone)."""
    try:
        entry = await asyncio.wait_for(ctx.library.entry(key, details=True), 10)
    except (LibraryError, TimeoutError):
        raise HTTPException(503, ondemand.UNREACHABLE) from None
    if entry is None or entry.kind not in (catalog.EPISODE, catalog.MOVIE):
        raise HTTPException(404, NOTHING_ON)
    return entry


def _program(entry: Entry) -> dict[str, Any]:
    episode = entry.kind == catalog.EPISODE
    return {
        "title": plain(entry.title),
        "show": plain(entry.show_title) if episode else None,
        "season": entry.season if episode else None,
        "episode": entry.episode if episode else None,
        "year": entry.year,
        "showKey": entry.show_key if episode else None,
        "library": entry.library or None,
    }


def _sign_in(request: Request) -> str | None:
    user = access.signed_in(request)
    token = access.bearer(request.scope) or request.cookies.get(access.COOKIE)
    return access.session_hash(token) if user and token else None


def _device(ctx: AppContext, request: Request) -> str:
    """Which app on which device sent it, as its sign-in says."""
    sign_in = _sign_in(request)
    known = ctx.db.session_app(sign_in) if sign_in else None
    return known or app_label("", "")
