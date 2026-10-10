"""Admin alerts: what StationPlay finds wrong that an Admin can act on, each
said once when it starts and again when it's fixed: in the Logs tab, in the
page's header (for Admins), to StationPlay's apps (GET /api/internal/alerts,
for Admins), and to the web address an Admin chose (see notify.py).

Only what StationPlay can tell for sure, and only once it has held a while,
so a moment's hiccup is never an alert; and once one starts, it's fixed
only once things have been right a while too, so none comes and goes:

  plex        Plex can't be reached (or won't take StationPlay's token): 5
              checks in a row, a minute apart. Fixed after 2 that reach it.
  data-full   The data folder's disk has less than 2 GB free: 3 checks in
              a row. Fixed once it has 3 GB free, twice. (A size, never a
              share: 2% of a large pool is still hundreds of GB.)
  data-write  Writing to the data folder fails: 2 checks in a row. Fixed
              after 2 that write.
  station     A station fails to start 3 times within 10 minutes: its stream
              engine failing, nothing on it playing for a program's time, or
              its stream for the apps not starting. Fixed when it plays a
              program again (a minute of it, or to its end), or it's
              deleted.
  backups     A backup (the nightly one, or one made from the page) failed
              twice in a row. Fixed when one is made.
  clock       StationPlay's clock is more than 2 minutes from Plex's, by the
              Date header Plex answers with: 3 checks in a row. Fixed under a
              minute, twice. It's the only reference StationPlay has without
              asking anything else: with no Date from Plex (or no Plex),
              the clock isn't checked.
  outside     StationPlay's apps can't reach it from outside: the outside
              check's own Down (see reach.py: two checks in a row, a minute
              apart, found a problem that counts). Fixed when it's Up again,
              or watching away from home is turned off.
  files       Something on the Broken files tab needs an Admin (see
              reports.py): a person's report, a file a station or Media
              plays that StationPlay found broken or damaged and that isn't
              being replaced by itself, or one Sonarr or Radarr couldn't
              replace. It says how many, and the newest. Fixed when nothing
              does. Said at most once an hour: once an hour has gone by
              since it was last said, anything new since then (still
              there) has it end, unsaid, and start again with a new ID (the
              apps notify once for each ID; the web address is told the
              same); until then, it only says what it is now.

Each has an ID that stays the same while it lasts (a new one starting
later has a new ID), its kind, a sentence an Admin can act on, when it
started, and when it was fixed. The alerts now, and those fixed in the last
day, are kept in the database as they change (never at every check), so
when StationPlay starts again they're as they were: one still going isn't
said again, and keeps its ID; it's fixed (and said to be, once) when its
check finds it right again, by that check's own rules, and until a check
can tell (Plex's first, or a station playing again), it stays as it was.
What's checked over again counts afresh: Plex's 5 checks, a station's 3
failures. (If the database can't be written to, they go on as they are,
and the log says so: a restart then may say them again.)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import sqlite3
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from . import playing, reach
from .notify import FIXED, STARTED
from .plex import PlexError

if TYPE_CHECKING:
    from collections.abc import Callable

    from .db import Database
    from .main import AppContext
    from .notify import Notify

log = logging.getLogger(__name__)

PLEX, DATA_FULL, DATA_WRITE = "plex", "data-full", "data-write"
STATION, BACKUPS, CLOCK, OUTSIDE = "station", "backups", "clock", "outside"
FILES = "files"
KINDS = (PLEX, DATA_FULL, DATA_WRITE, STATION, BACKUPS, CLOCK, OUTSIDE, FILES)
CHECK_S = 60.0  # how often what's checked is looked at
FIRST_S = 20.0  # the first look, after StationPlay starts
PLEX_WAIT_S = 10.0  # the longest Plex is waited for, in a check
FIXED_KEPT_S = 24 * 3600.0  # alerts fixed this long ago are still listed
FIXED_MOST = 100
# The data folder: low under either of these; fine again over both of these.
LOW_BYTES, ROOM_BYTES = 2 * 1024**3, 3 * 1024**3
WRITE_TEST = ".alerts-write-test"
# A station: failing to start this many times within this long.
STATION_FAILS, STATION_WINDOW_S = 3, 600.0
BACKUP_FAILS = 2
# The clock: off from Plex's by more than this; right again under this.
CLOCK_OFF_S, CLOCK_RIGHT_S = 120.0, 60.0
# The Broken files tab: said again (with a new ID) at most this often.
FILES_AGAIN_S = 3600.0
# That the alerts are kept by a StationPlay running now: noted at most this
# often. Alerts kept longer ago than ALIVE_STALE_S (StationPlay stopped that
# long, or an older version, which doesn't keep them, ran meanwhile) aren't
# brought back as going: anything still wrong is found, and said, afresh.
ALIVE_META, ALIVE_EVERY_S, ALIVE_STALE_S = "alerts_alive_ms", 600.0, 2 * 24 * 3600.0


@dataclass
class Alert:
    """One alert: its kind, and what it's about within its kind (`about`: a
    station's id; "" otherwise)."""

    kind: str
    about: str
    sentence: str
    since_ms: int
    fixed_ms: int | None = None
    untold: str = ""  # what the web address didn't take of it: STARTED or FIXED
    fixed_sentence: str = ""

    @property
    def id(self) -> str:
        return "-".join(x for x in (self.kind, self.about, str(self.since_ms)) if x)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "sentence": self.sentence,
            "since": self.since_ms,
            "fixed": self.fixed_ms,
        }


@dataclass
class _Streak:
    """Checks of one thing in a row that found it wrong, or right."""

    wrong: int = 0
    right: int = 0

    def note(self, wrong: bool) -> None:
        if wrong:
            self.wrong, self.right = self.wrong + 1, 0
        else:
            self.wrong, self.right = 0, self.right + 1


class Alerts:
    """The alerts now and lately, and what's found (see the module's notes)."""

    def __init__(
        self, notify: Notify, db: Database, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.notify = notify
        self.db = db
        self.clock = clock
        self._now: dict[tuple[str, str], Alert] = {}
        self._fixed: deque[Alert] = deque(maxlen=FIXED_MOST)
        self._streaks: dict[tuple[str, str], _Streak] = {}
        self._station_fails: dict[int, deque[float]] = {}
        self._backup_fails = 0
        # The Broken files tab: what needed an Admin when it was last looked
        # at (None: not yet, since StationPlay started), when the alert was
        # last said (started), and what's come since.
        self._files_seen: set[str] | None = set()
        self._files_said = 0.0
        self._files_unsaid: set[str] = set()
        self._files_kept: str = ""  # (what the database has of them)
        self._unkept = False  # (the database couldn't be written: said once)
        # What the web address didn't take before StationPlay stopped (it
        # didn't answer, or StationPlay stopped first): sent again at the
        # first look, when sending is under way.
        self._retell: list[tuple[Alert, str]] = []
        self._alive_at: float | None = None
        self._restore()
        self._alive()

    def _restore(self) -> None:
        """The alerts as they were kept, when StationPlay starts (see the
        module's notes)."""
        try:
            rows = self.db.kept_alerts()
            stations = {str(c.id) for c in self.db.list_channels()}
            alive = int(self.db.get_meta(ALIVE_META) or 0)
        except sqlite3.Error as e:
            log.warning("Couldn't read the alerts kept from before (%s)", e)
            return
        going = [r for r in rows if r["fixed_ms"] is None and r["kind"] in KINDS]
        if going and _now_ms() - alive > ALIVE_STALE_S * 1000:
            log.info(
                "The alerts kept from before are from too long ago to go on with; anything still "
                "wrong is found again"
            )
            self._keep(self.db.forget_going_alerts, KINDS)
            rows = [r for r in rows if r not in going]
        for row in rows:
            kept = json.loads(row["state"]) if row["state"] else {}
            alert = Alert(
                *(row[k] for k in ("kind", "about", "sentence", "since_ms", "fixed_ms")),
                untold=row["untold"], fixed_sentence=kept.get("fixed", ""),
            )  # fmt: skip
            if alert.kind not in KINDS:
                continue  # (a later version's, left for it)
            if alert.fixed_ms is not None:
                self._fixed.append(alert)
                if alert.untold == FIXED and alert.fixed_sentence:
                    self._retell.append((alert, FIXED))
            elif alert.kind == STATION and alert.about not in stations:
                # (Deleted, and said so then, though it couldn't be kept.)
                self._keep(self.db.forget_alert, alert.kind, alert.about, alert.since_ms)
            else:
                self._now[(alert.kind, alert.about)] = alert
                log.warning("Alert still going: %s", alert.sentence)
                if alert.untold == STARTED:
                    self._retell.append((alert, STARTED))
                if alert.kind == FILES and "seen" in kept:
                    self._files_seen = set(kept["seen"])
                    self._files_unsaid = set(kept.get("unsaid", ()))
                    self._files_kept = row["state"]
        files = self._now.get((FILES, ""))
        if files is not None:
            # When it was said, by this clock; what was there then (when
            # kept from before 1.31.0, found at the first look: see files).
            self._files_said = self.clock() - max(0.0, (_now_ms() - files.since_ms) / 1000)
            if not self._files_kept:
                self._files_seen = None

    def _alive(self) -> None:
        """Notes that the alerts are kept by a StationPlay running now (at
        most every ALIVE_EVERY_S)."""
        now = self.clock()
        if self._alive_at is None or now - self._alive_at >= ALIVE_EVERY_S:
            self._alive_at = now
            self._keep(self.db.set_meta, ALIVE_META, str(_now_ms()))

    def _untold(self, alert: Alert, state: str) -> Callable[[], None]:
        """What's done if the web address doesn't take `state` of `alert`
        ("" once it does: nothing's left to tell). Written only then, so
        never at every check."""

        def note() -> None:
            alert.untold = state
            self._keep(self.db.untold_alert, alert.kind, alert.about, alert.since_ms, state)

        return note

    # What's said ----------------------------------------------------------------

    def now(self) -> list[Alert]:
        """The alerts now, the newest first."""
        return sorted(self._now.values(), key=lambda a: a.since_ms, reverse=True)

    def listed(self) -> list[Alert]:
        """The alerts now, then those fixed in the last FIXED_KEPT_S (the
        most lately fixed first)."""
        since = _now_ms() - FIXED_KEPT_S * 1000
        fixed = [a for a in self._fixed if (a.fixed_ms or 0) >= since]
        return [*self.now(), *sorted(fixed, key=lambda a: a.fixed_ms or 0, reverse=True)]

    def start(self, kind: str, sentence: str, about: str = "", after: Alert | None = None) -> None:
        """An alert starts (or, while it lasts, says what it is now); in
        place of `after`, if given, which ended unsaid (with an ID of its
        own however soon after it)."""
        found = self._now.get((kind, about))
        if found is not None:
            if found.sentence != sentence:
                found.sentence = sentence
                self._keep(self._write, found)
            return
        since = max(_now_ms(), after.since_ms + 1) if after else _now_ms()
        alert = self._now[(kind, about)] = Alert(kind, about, sentence, since)
        self._keep(self._write, alert, after)
        log.warning("Alert: %s", sentence)
        self.notify.send(sentence, kind, STARTED, failed=self._untold(alert, STARTED))

    def fix(self, kind: str, sentence: str, about: str = "") -> None:
        """An alert is fixed (`sentence`: saying so), if there is one."""
        found = self._now.pop((kind, about), None)
        if found is None:
            return
        found.fixed_ms, found.fixed_sentence = _now_ms(), sentence
        self._fixed.append(found)
        self._keep(self._write, found)
        log.info("Alert fixed: %s", sentence)
        self.notify.send(sentence, kind, FIXED, failed=self._untold(found, FIXED))

    def _write(self, alert: Alert, instead_of: Alert | None = None) -> None:
        """An alert, as it is now, to the database (see Database.keep_alert);
        and, once one's fixed, those fixed too long ago forgotten."""
        # (Fixed: what's said of it so, should the web address need telling
        # after a restart.)
        fixed = json.dumps({"fixed": alert.fixed_sentence}) if alert.fixed_ms else None
        self.db.keep_alert(
            alert.kind, alert.about, alert.since_ms, alert.sentence, alert.fixed_ms,
            instead_of.since_ms if instead_of else None, fixed,
        )  # fmt: skip
        if alert.fixed_ms is not None:
            self.db.forget_fixed_alerts(alert.fixed_ms - int(FIXED_KEPT_S * 1000), FIXED_MOST)

    def _keep(self, write: Callable[..., None], *args: Any) -> None:
        """Writes a change to the database. If it can't be, the alerts go on
        as they are, and the log says so (once, till one can be again)."""
        try:
            write(*args)
        except sqlite3.Error as e:
            if not self._unkept:
                log.warning(
                    "Couldn't keep the alerts in the database (%s), so they may be said again "
                    "if StationPlay restarts",
                    e,
                )
            self._unkept = True
            return
        self._unkept = False

    def checked(
        self,
        kind: str,
        wrong: bool,
        sentence: str,
        fixed: str,
        start_after: int,
        fix_after: int,
        about: str = "",
    ) -> None:
        """What a check found: `wrong`, `start_after` checks in a row, starts
        an alert saying `sentence`; right, `fix_after` in a row, fixes it,
        saying `fixed`."""
        streak = self._streaks.setdefault((kind, about), _Streak())
        streak.note(wrong)
        going = (kind, about) in self._now
        if wrong and (going or streak.wrong >= start_after):
            self.start(kind, sentence, about)
        elif not wrong and going and streak.right >= fix_after:
            self.fix(kind, fixed, about)

    # Stations and backups, as they happen -----------------------------------------

    def station_failed(self, channel_id: int, number: int | None, name: str) -> None:
        """A station failed to start (see the module's notes)."""
        now = self.clock()
        fails = self._station_fails.setdefault(channel_id, deque())
        fails.append(now)
        while fails and now - fails[0] > STATION_WINDOW_S:
            fails.popleft()
        if len(fails) >= STATION_FAILS:
            named = playing.cap(playing.station(number, name, mid=True))
            self.start(
                STATION,
                f"{named} keeps failing to start: {len(fails)} times in the last "
                f"{STATION_WINDOW_S / 60:.0f} minutes. The Logs tab says why each time; check "
                "that Plex and the station's files can be reached.",
                str(channel_id),
            )

    def station_played(self, channel_id: int, number: int | None, name: str) -> None:
        """A station played a program (see broadcaster.PLAYED_S): it's
        working."""
        self._station_fails.pop(channel_id, None)
        named = playing.cap(playing.station(number, name, mid=True))
        self.fix(STATION, f"{named} is playing again.", str(channel_id))

    def station_gone(self, channel_id: int, number: int | None, name: str) -> None:
        self._station_fails.pop(channel_id, None)
        named = playing.cap(playing.station(number, name, mid=True))
        self.fix(STATION, f"{named} was deleted, so it no longer fails.", str(channel_id))

    def backup_failed(self) -> None:
        self._backup_fails += 1
        if self._backup_fails >= BACKUP_FAILS:
            self.start(
                BACKUPS,
                f"StationPlay's backups are failing: the last {self._backup_fails} tries didn't "
                "work. The Logs tab says why; check that the data folder has room and can be "
                "written to.",
            )

    def backup_made(self) -> None:
        self._backup_fails = 0
        self.fix(BACKUPS, "StationPlay made a backup again.")

    # The Broken files tab ----------------------------------------------------------

    def files(self, things: list[tuple[int, str, str]]) -> None:
        """What needs an Admin on the Broken files tab now (see the module's
        notes, and reports.Reports.needing): (when, which, what) for each."""
        seen = {which for _, which, _ in things}
        going = self._now.get((FILES, ""))
        if self._files_seen is None:
            # (The first look since StationPlay started again: what's come
            # since the alert was said is what's newer.)
            said_ms = going.since_ms if going else 0
            self._files_seen = {which for when, which, _ in things if when <= said_ms}
        # (What's come since it was said, and is still there.)
        self._files_unsaid = (self._files_unsaid | (seen - self._files_seen)) & seen
        self._files_seen = seen
        if not things:
            self.fix(FILES, "Nothing on the Broken files tab needs you now.")
            return
        n = len(things)
        _, _, newest = max(things)
        sentence = (
            f"There {'is' if n == 1 else 'are'} {n} file{'' if n == 1 else 's'} to look at on "
            f"the Broken files tab: {newest[:1].upper()}{newest[1:]}."
        )
        if going is not None and not (
            self._files_unsaid and self.clock() - self._files_said >= FILES_AGAIN_S
        ):
            self.start(FILES, sentence)  # (what it is now, unsaid)
            self._keep_files()
            return
        if going is not None:
            # (New things since it was said, an hour or more ago: said again, anew.)
            del self._now[(FILES, "")]
        self._files_said = self.clock()
        self._files_unsaid = set()
        self.start(FILES, sentence, after=going)
        self._keep_files()

    def _keep_files(self) -> None:
        """What the Broken files alert covers, kept with it as it changes:
        what was there at the last look, and what's come since it was said."""
        going = self._now.get((FILES, ""))
        state = json.dumps(
            {"seen": sorted(self._files_seen or ()), "unsaid": sorted(self._files_unsaid)}
        )
        if going is not None and state != self._files_kept:
            self._files_kept = state
            self._keep(self.db.alert_state, FILES, "", going.since_ms, state)

    # Checking --------------------------------------------------------------------

    async def run_forever(self, ctx: AppContext) -> None:
        """Looks every CHECK_S, for as long as StationPlay runs."""
        await asyncio.sleep(FIRST_S)
        while True:
            try:
                await self.look(ctx)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Checking for alerts failed")
            await asyncio.sleep(CHECK_S)

    async def look(self, ctx: AppContext) -> None:
        """Checks Plex (and the clock, by its answer), the data folder,
        whether the apps reach StationPlay from outside, and what needs an
        Admin on the Broken files tab."""
        self._alive()
        for alert, state in self._retell:
            sentence = alert.sentence if state == STARTED else alert.fixed_sentence
            self.notify.send(
                sentence, alert.kind, state, self._untold(alert, ""), self._untold(alert, state)
            )
        self._retell = []
        await self._look_at_plex(ctx)
        await asyncio.to_thread(self._look_at_data, ctx.settings.data_dir)
        self._look_outside(ctx.reach.status(), ctx.away.address)
        self.files(await asyncio.to_thread(ctx.reports.needing))

    async def _look_at_plex(self, ctx: AppContext) -> None:
        plex = ctx.plex
        if not plex.configured:
            return
        where = urlsplit(plex.base_url).netloc.rpartition("@")[2] or plex.base_url
        plex.clock_offset_s = None
        why = ""
        try:
            await asyncio.wait_for(plex.identity(), PLEX_WAIT_S)
        except PlexError as e:
            why = (
                f"Plex at {where} doesn't accept StationPlay's token. Check PLEX_TOKEN in "
                "StationPlay's settings."
                if e.status == 401
                else f"StationPlay can't reach Plex at {where}. Check that Plex is running."
            )
        except TimeoutError:
            why = f"StationPlay can't reach Plex at {where}. Check that Plex is running."
        self.checked(PLEX, bool(why), why, f"StationPlay can reach Plex at {where} again.", 5, 2)
        offset = plex.clock_offset_s
        if why or offset is None:
            return  # (nothing to tell the time by)
        if (CLOCK, "") in self._now:
            wrong = abs(offset) >= CLOCK_RIGHT_S
        else:
            wrong = abs(offset) > CLOCK_OFF_S
        minutes = max(1, round(abs(offset) / 60))
        said = f"{minutes} minute{'' if minutes == 1 else 's'} {'ahead of' if offset > 0 else 'behind'}"
        self.checked(
            CLOCK,
            wrong,
            f"StationPlay's clock is {said} Plex's. The guide and the stations' clocks go by "
            "it: check the date and time on this server (and on Plex's, if it runs elsewhere).",
            "StationPlay's clock agrees with Plex's again.",
            3,
            2,
        )

    def _look_at_data(self, folder: Path) -> None:
        """The data folder's free space, and whether it can be written to."""
        try:
            disk = shutil.disk_usage(folder)
        except OSError:
            disk = None
        if disk is not None and disk.total > 0:
            free, share = disk.free, disk.free / disk.total
            low = free < LOW_BYTES
            room = free >= ROOM_BYTES
            going = (DATA_FULL, "") in self._now
            self.checked(
                DATA_FULL,
                low or (going and not room),
                f"StationPlay's data folder has only {_size(free)} free ({share:.0%} of its disk). "
                "Free up room on its disk, or StationPlay can't keep stations, backups and "
                "settings.",
                f"StationPlay's data folder has room again ({_size(free)} free).",
                3,
                2,
            )
        problem = ""
        probe = folder / WRITE_TEST
        try:
            probe.write_text("StationPlay checks it can write here\n")
        except OSError as e:
            problem = e.strerror or type(e).__name__
        finally:
            with contextlib.suppress(OSError):
                probe.unlink()
        self.checked(
            DATA_WRITE,
            bool(problem),
            # (Not the folder's path: the apps show alerts, and never name a
            # file or folder.)
            f"StationPlay can't write to its data folder ({problem}). Check the folder's "
            "permissions, and that its disk has room.",
            "StationPlay can write to its data folder again.",
            2,
            2,
        )

    def _look_outside(self, status: reach.Status, address: str) -> None:
        """The outside check's status (see reach.py), which has waited for
        two checks in a row itself."""
        if status.state == reach.DOWN:
            self.start(
                OUTSIDE,
                f"StationPlay's apps can't reach it from outside at {address} "
                f"({status.short.lower()}). See StationPlay's apps away from home, on the "
                "Access tab.",
            )
        elif status.state in (reach.UP, reach.OFF):
            self.fix(
                OUTSIDE,
                f"StationPlay's apps can reach it from outside again, at {address}."
                if status.state == reach.UP
                else "Watching away from home was turned off, so StationPlay's apps no longer "
                "need to reach it from outside.",
            )


def _size(free: int) -> str:
    """Free space as people say it: "820 MB", "1.4 GB", "312 GB"."""
    gb = free / 1024**3
    if gb < 1:
        return f"{free / 1024**2:.0f} MB"
    return f"{gb:.1f} GB" if gb < 10 else f"{gb:.0f} GB"


def _now_ms() -> int:
    return int(time.time() * 1000)
