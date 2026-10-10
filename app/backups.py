"""Backups of everything StationPlay keeps: stations and their schedules,
settings, the broken-files list, the tuner's identity, uploaded logos, who
can sign in (passwords only as hashes; not who's signed in) and viewing
statistics.

A backup is a zip file. One is made every night and the last KEEP are kept
in the data folder's backups/ folder; the web page can download one at any
time, and restore one.

Restoring never swaps files under a running StationPlay: the backup is
checked, unpacked into restore/ (and what's in it checked again: see
main.py), marked ready, and StationPlay restarts (Docker starts it again).
On the way up, before anything opens the database, the files are moved
into place, after a backup of what was there before. (Its Admin alerts are
left out: they were about when it was made. See _forget_alerts.)

Before an update changes the database (a new table or column, or anything
else Database does to bring one up to date: see db.changes_needed), the
database is copied as it is, sign-ins and all, to backups/ as
before-<version>-<date>.db (the newest BEFORE_KEPT kept), so going back to
the version before is putting that copy in place (see the README's
Updating). If the copy can't be made, StationPlay changes nothing and stops.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
import zlib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from . import __version__
from .db import changes_needed, copy_database
from .text import plain

if TYPE_CHECKING:
    from .main import AppContext

log = logging.getLogger(__name__)

KEEP = 7
BEFORE_KEPT = 3  # copies of the database from before an update changed it
BACKUP_DIR = "backups"
RESTORE_DIR = "restore"
READY = "READY"
DB_NAME = "stationplay.db"
# The files a backup holds, besides the database and uploaded logos.
FILES = ("device.json", "broken-files.json")
LOGO_NAME = re.compile(r"logos/upload-[0-9a-f]{1,32}\.png")
BACKUP_NAME = re.compile(r"stationplay-(backup|before-restore)-\d{8}-\d{6}\.zip")
BEFORE_NAME = re.compile(r"before-[0-9A-Za-z.+-]+-(\d{8}-\d{6})\.db")
MANIFEST = "stationplay-backup.json"
# A backup bigger than this, unpacked, isn't StationPlay's.
MAX_UNPACKED = 500 * 1024 * 1024
MAX_UPLOAD = 200 * 1024 * 1024
# The nightly backup is made in this hour (local time), or whenever the
# newest one is older than MAX_AGE_S.
NIGHTLY_HOUR = 3
MAX_AGE_S = 30 * 3600
CHECK_EVERY_S = 15 * 60


class BackupError(Exception):
    """A file that can't be restored, and why."""


class CantBackUp(Exception):
    """The database can't be copied before an update changes it: why, in a
    sentence for the log."""


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def backups_dir(data_dir: Path) -> Path:
    return data_dir / BACKUP_DIR


def make_backup(ctx: AppContext, kind: str = "backup") -> Path:
    """Writes a new backup into the backups folder and returns it. Keeps the
    newest KEEP of each kind."""
    data_dir = ctx.settings.data_dir
    folder = backups_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"stationplay-{kind}-{_stamp()}.zip"
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        db_copy = Path(tmp) / DB_NAME
        copy_database(ctx.db.path, db_copy)
        _write_zip(path, data_dir, db_copy)
    prune(folder, kind)
    return path


def _write_zip(path: Path, data_dir: Path, db_file: Path) -> None:
    part = path.with_suffix(".zip.part")
    names = [DB_NAME]
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(db_file, DB_NAME)
        for name in FILES:
            if (data_dir / name).is_file():
                z.write(data_dir / name, name)
                names.append(name)
        logos = data_dir / "logos"
        if logos.is_dir():
            for logo in sorted(logos.glob("upload-*.png")):
                name = f"logos/{logo.name}"
                if LOGO_NAME.fullmatch(name):
                    z.write(logo, name)
                    names.append(name)
        z.writestr(
            MANIFEST,
            json.dumps(
                {"app": "StationPlay", "version": __version__, "made": _stamp(), "files": names},
                indent=2,
            ),
        )
    os.replace(part, path)


def prune(folder: Path, kind: str = "backup") -> None:
    ours = sorted(folder.glob(f"stationplay-{kind}-*.zip"), reverse=True)
    for old in ours[KEEP:]:
        old.unlink(missing_ok=True)
    # Anything left half-written by a backup that was cut off.
    for part in folder.glob("*.zip.part"):
        with contextlib.suppress(OSError):
            if time.time() - part.stat().st_mtime > 3600:
                part.unlink()


def list_backups(data_dir: Path) -> list[dict]:
    folder = backups_dir(data_dir)
    if not folder.is_dir():
        return []
    out = []
    for path in folder.glob("stationplay-*.zip"):
        if BACKUP_NAME.fullmatch(path.name):
            try:
                st = path.stat()
            except OSError:
                continue  # removed just now
            out.append({"name": path.name, "size": st.st_size, "made": int(st.st_mtime * 1000)})
    return sorted(out, key=lambda b: b["made"], reverse=True)


def backup_path(data_dir: Path, name: str) -> Path | None:
    """A stored backup's file, if `name` is one."""
    if not BACKUP_NAME.fullmatch(name):
        return None
    path = backups_dir(data_dir) / name
    return path if path.is_file() else None


# Before an update changes the database -----------------------------------------------


def before_update(data_dir: Path) -> Path | None:
    """At startup, before the database is opened: if this version will change
    it, a copy of it as it is (see the module's notes), returned; None if
    there's nothing to change. CantBackUp if the copy can't be made, so
    nothing is changed."""
    current = data_dir / DB_NAME
    if not current.is_file():
        return None  # (a new install)
    try:
        changes = changes_needed(current)
    except sqlite3.Error as e:
        raise CantBackUp(
            f"StationPlay {__version__} couldn't read its database to see whether it needs "
            f"updating ({e}), so it changed nothing and stopped. Check its data folder's "
            "stationplay.db, or restore a backup."
        ) from None
    if not changes:
        return None
    folder = backups_dir(data_dir)
    path = folder / f"before-{__version__}-{_stamp()}.db"
    part = path.with_name(path.name + ".part")
    stop = (
        f"StationPlay {__version__} needs to update its database, but couldn't back it up "
        "first, so it changed nothing and stopped"
    )
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("before-*.db.part"):
            old.unlink()  # (a copy cut off last time)
        # (Room for the database and what's waiting to go into it, and a little more.)
        wal = current.with_name(DB_NAME + "-wal")
        need = current.stat().st_size + (wal.stat().st_size if wal.is_file() else 0) + (8 << 20)
        free = shutil.disk_usage(folder).free
        if free < need:
            raise CantBackUp(
                f"{stop}: its data folder's disk has {_mb(free)} free, and the copy needs about "
                f"{_mb(need)}. Free up room on that disk, then start StationPlay again."
            )
        copy_database(current, part, sign_ins=True)
        _check_copy(part)
        os.replace(part, path)
    except (OSError, sqlite3.Error) as e:
        part.unlink(missing_ok=True)
        raise CantBackUp(
            f"{stop} ({e}). Check that its data folder can be written to and its disk has "
            "room, then start StationPlay again."
        ) from None
    ours = sorted(
        ((found.group(1), p) for p in folder.glob("before-*.db")
         if (found := BEFORE_NAME.fullmatch(p.name))),
        reverse=True,
    )  # fmt: skip
    for _, old in ours[BEFORE_KEPT:]:
        old.unlink(missing_ok=True)
    log.info(
        "Backed up the database to backups/%s before updating it for StationPlay %s (%s). "
        "To go back to the version before, see Rolling back in the README.",
        path.name,
        __version__,
        "; ".join(changes),
    )
    return path


def _check_copy(path: Path) -> None:
    """Raises sqlite3.DatabaseError unless a copy just made is whole."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("the copy isn't whole")
    finally:
        conn.close()


def _mb(size: int) -> str:
    return f"{size / 1024**2:,.0f} MB"


# Restoring ----------------------------------------------------------------------


def stage_restore(data_dir: Path, data: bytes) -> dict:
    """Checks an uploaded backup and unpacks it, set aside to be put in place
    when StationPlay next starts, once it's marked ready (mark_ready).
    Returns what it holds."""
    if len(data) > MAX_UPLOAD:
        raise BackupError("That file is too big to be a StationPlay backup")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise BackupError("That isn't a StationPlay backup (it isn't a zip file)") from None
    with z:
        infos = {i.filename: i for i in z.infolist() if not i.is_dir()}
        if DB_NAME not in infos:
            raise BackupError("That isn't a StationPlay backup (it has no stationplay.db)")
        wanted = [n for n in infos if n == DB_NAME or n in FILES or LOGO_NAME.fullmatch(n)]
        if sum(infos[n].file_size for n in wanted) > MAX_UNPACKED:
            raise BackupError("That file is too big to be a StationPlay backup")
        staging = data_dir / RESTORE_DIR
        shutil.rmtree(staging, ignore_errors=True)
        (staging / "logos").mkdir(parents=True)
        try:
            for name in wanted:
                # Names are checked above, so they can't point outside.
                (staging / name).write_bytes(z.read(name))
            stations, users = _check_database(staging / DB_NAME)
        except BackupError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        except (OSError, zipfile.BadZipFile, zlib.error) as e:
            shutil.rmtree(staging, ignore_errors=True)
            raise BackupError(f"That backup couldn't be unpacked ({e})") from None
    return {
        "stations": stations,
        "users": users,
        "logos": sum(1 for n in wanted if n.startswith("logos/")),
    }


def tidy_staged_stations(data_dir: Path) -> list[tuple[str, str]]:
    """Makes the names and descriptions of the stations in a backup set aside
    to be restored plain, as they are now (see text.py; a backup from before
    1.9 may hold others), and returns what each is made of: (its name, its
    sources as stored). BackupError if they can't be read."""
    path = data_dir / RESTORE_DIR / DB_NAME
    conn = sqlite3.connect(path)
    try:
        with conn:
            rows = conn.execute("SELECT id, name, sources FROM channels").fetchall()
            for station_id, name, _ in rows:
                conn.execute(
                    "UPDATE channels SET name = ? WHERE id = ?", (plain(str(name)), station_id)
                )
            if any(r[1] == "description" for r in conn.execute("PRAGMA table_info(channels)")):
                for station_id, description in conn.execute(
                    "SELECT id, description FROM channels"
                ).fetchall():
                    conn.execute(
                        "UPDATE channels SET description = ? WHERE id = ?",
                        (plain(str(description or "")), station_id),
                    )
        conn.execute("PRAGMA journal_mode = DELETE")
    except sqlite3.DatabaseError as e:
        raise BackupError(f"Couldn't read the stations in that backup ({e})") from None
    finally:
        conn.close()
    return [(plain(str(name)), str(sources or "[]")) for _, name, sources in rows]


def staged_logos(data_dir: Path) -> list[Path]:
    """The uploaded logos in a backup set aside to be restored."""
    return sorted((data_dir / RESTORE_DIR / "logos").glob("upload-*.png"))


def mark_ready(data_dir: Path) -> None:
    """Marks a backup set aside as ready, to be put in place when StationPlay
    next starts."""
    (data_dir / RESTORE_DIR / READY).write_text(json.dumps({"staged": _stamp()}) + "\n")


def discard_restore(data_dir: Path) -> None:
    """Throws away a staged backup that isn't wanted after all."""
    shutil.rmtree(data_dir / RESTORE_DIR, ignore_errors=True)


def _check_database(path: Path) -> tuple[int, int]:
    """The number of stations and users in a backup's database (none in one
    made before 1.9); raises BackupError if it isn't a StationPlay database in
    good order."""
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("That backup's database is damaged")
            # StationPlay's databases have tables and indexes, nothing that
            # would run by itself once it's in use (a trigger) or hide one.
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type NOT IN ('table', 'index')"
            ).fetchone():
                raise BackupError("That backup's database wasn't made by StationPlay")
            stations = int(conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0])
            has_users = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'"
            ).fetchone()
            users = (
                int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]) if has_users else 0
            )
            return stations, users
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise BackupError(f"That isn't a StationPlay backup ({e})") from None


def apply_staged_restore(data_dir: Path) -> bool:
    """At startup, before the database is opened: puts a staged backup in
    place, keeping a copy of what was there before. True if it did."""
    staging = data_dir / RESTORE_DIR
    if not (staging / READY).is_file():
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)  # an unfinished upload
        return False
    try:
        _put_in_place(data_dir, staging)
    finally:
        # Once only, whatever happened: a restore that fails mustn't be
        # tried again on every start.
        shutil.rmtree(staging, ignore_errors=True)
    log.warning(
        "Restored the backup. A copy of the settings from before the restore is in %s",
        backups_dir(data_dir),
    )
    return True


def _put_in_place(data_dir: Path, staging: Path) -> None:
    folder = backups_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    current = data_dir / DB_NAME
    if current.is_file():
        # What's being replaced, in case the restore wasn't wanted after all.
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            copy = Path(tmp) / DB_NAME
            copy_database(current, copy)
            _write_zip(folder / f"stationplay-before-restore-{_stamp()}.zip", data_dir, copy)
        prune(folder, "before-restore")
    _forget_alerts(staging / DB_NAME)
    for suffix in ("-wal", "-shm"):
        (data_dir / (DB_NAME + suffix)).unlink(missing_ok=True)
    os.replace(staging / DB_NAME, current)
    for name in FILES:
        if (staging / name).is_file():
            os.replace(staging / name, data_dir / name)
        elif name == "broken-files.json":
            # The list was empty when the backup was made.
            (data_dir / name).unlink(missing_ok=True)
    logos = data_dir / "logos"
    logos.mkdir(exist_ok=True)
    for old in logos.glob("upload-*.png"):
        old.unlink()
    for new in (staging / "logos").glob("upload-*.png"):
        os.replace(new, logos / new.name)


def _forget_alerts(path: Path) -> None:
    """A backup's Admin alerts were about when it was made, not now: they're
    forgotten as it's put in place (what's still wrong is found, and said,
    again). One from before they were kept has none."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True)  # (never made here)
    try:
        with conn:
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alerts'"
            ).fetchone():
                conn.execute("DELETE FROM alerts")
    finally:
        conn.close()


# Every night ---------------------------------------------------------------------


def _newest_age_s(data_dir: Path) -> float:
    ours = list(backups_dir(data_dir).glob("stationplay-backup-*.zip"))
    if not ours:
        return float("inf")
    return time.time() - max(p.stat().st_mtime for p in ours)


async def nightly_forever(ctx: AppContext) -> None:
    data_dir = ctx.settings.data_dir
    while True:
        await asyncio.sleep(CHECK_EVERY_S)
        try:
            age = _newest_age_s(data_dir)
            tonight = time.localtime().tm_hour == NIGHTLY_HOUR and age > 12 * 3600
            if tonight or age > MAX_AGE_S:
                path = await asyncio.to_thread(make_backup, ctx)
                ctx.alerts.backup_made()
                log.info("Backed up StationPlay to %s", path.name)
        except Exception:
            log.exception("The nightly backup failed")
            ctx.alerts.backup_failed()
