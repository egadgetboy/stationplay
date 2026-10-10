"""Backups: made every night and on request, and restored on the next start."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import __version__, backups, db
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex

MIN = 60_000
PNG = (  # a tiny picture, as ffmpeg makes one
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02"
    b"\x08\x02\x00\x00\x00\xfd\xd4\x9as\x00\x00\x00\tpHYs\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x00O%\xc4\xd6\x00\x00\x00\x10IDATx\x9cc\xf8\xcb\xc0"
    b"\x00D\x0c\x10\n\x00\x1f\xae\x03\xf5\xf6\x18*Y\x00\x00\x00\x00IEND\xae"
    b"B`\x82"
)


def plex() -> FakePlex:
    fp = FakePlex()
    fp.add_show("100", "The Jetsons")
    for n in (1, 2):
        fp.add_episode(f"2{n:02d}", "100", 1, n, f"Jetsons {n}", f"/tv/j{n}.mkv", 22 * MIN)
    return fp


def client_for(data_dir, fp: FakePlex) -> TestClient:
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=data_dir),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    app.state.ctx.restart = lambda: None  # a test mustn't stop itself
    return TestClient(app)


def add_station(client: TestClient, number: int, name: str) -> dict:
    made = client.post(
        "/api/channels",
        json={
            "number": number,
            "name": name,
            "orderMode": "rotate",
            "sources": [{"type": "show", "ratingKey": "100"}],
            "breaks": 2,
            "watermark": "logo",
        },
    )
    assert made.status_code == 201, made.text
    return made.json()


def test_a_backup_holds_everything_and_only_seven_are_kept(tmp_path):
    data = tmp_path / "data"
    with client_for(data, plex()) as client:
        add_station(client, 4, "Cartoons")
        (data / "logos").mkdir(exist_ok=True)
        (data / "logos" / "upload-abc123.png").write_bytes(PNG)
        (data / "logos" / "not-mine.png").write_bytes(PNG)
        (data / "broken-files.json").write_text('{"files": []}\n')
        made = client.post("/api/backups")
        assert made.status_code == 201
        name = made.json()["name"]
        listed = client.get("/api/backups").json()
        assert [b["name"] for b in listed["backups"]] == [name] and listed["keep"] == 7
        got = client.get(f"/api/backups/{name}")
        assert got.status_code == 200 and got.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(got.content)) as z:
            names = set(z.namelist())
            manifest = json.loads(z.read(backups.MANIFEST))
        assert names == {
            "stationplay.db",
            "device.json",
            "broken-files.json",
            "logos/upload-abc123.png",
            backups.MANIFEST,
        }
        assert manifest["app"] == "StationPlay"
        # Only stored backups can be downloaded.
        for bad in ("../stationplay.db", "device.json", "stationplay-backup-1.zip"):
            assert client.get(f"/api/backups/{bad}").status_code == 404
        # Old ones go.
        folder = data / "backups"
        for n in range(10):
            old = folder / f"stationplay-backup-2020010{n % 10}-00000{n}.zip"
            old.write_bytes(b"x")
            os.utime(old, (1_600_000_000 + n, 1_600_000_000 + n))
        client.post("/api/backups")
        kept = sorted(p.name for p in folder.glob("stationplay-backup-*.zip"))
        assert len(kept) == 7 and name in kept


def test_restoring_puts_everything_back_on_the_next_start(tmp_path):
    data = tmp_path / "data"
    fp = plex()
    with client_for(data, fp) as client:
        station = add_station(client, 4, "Cartoons")
        (data / "logos").mkdir(exist_ok=True)
        (data / "logos" / "upload-abc123.png").write_bytes(PNG)
        device = client.get("/discover.json").json()["DeviceID"]
        name = client.post("/api/backups").json()["name"]
        backup = client.get(f"/api/backups/{name}").content
        # Things change afterwards...
        client.delete(f"/api/channels/{station['id']}")
        add_station(client, 9, "Something else")
        (data / "logos" / "upload-abc123.png").unlink()
        (data / "logos" / "upload-ffff.png").write_bytes(PNG)
        # ...and the backup is restored. It's put in place when StationPlay
        # restarts, not while it's running.
        restarted = []
        client.app.state.ctx.restart = lambda: restarted.append(True)
        res = client.post("/api/restore", content=backup)
        assert res.status_code == 200, res.text
        assert res.json() == {"stations": 1, "users": 0, "logos": 1, "restarting": True}
        assert [c["number"] for c in client.get("/api/channels").json()] == [9]
        client.portal.call(__import__("asyncio").sleep, 1.3)
        assert restarted == [True]
    # StationPlay starts again.
    with client_for(data, fp) as client:
        channels = client.get("/api/channels").json()
        assert [(c["number"], c["name"], c["breaks"], c["watermark"]) for c in channels] == [
            (4, "Cartoons", 2, "logo")
        ]
        assert client.get("/discover.json").json()["DeviceID"] == device
        assert sorted(p.name for p in (data / "logos").glob("upload-*")) == ["upload-abc123.png"]
        assert not (data / backups.RESTORE_DIR).exists()
        # What was there before is kept, in case the restore wasn't wanted.
        before = [
            b for b in client.get("/api/backups").json()["backups"] if "before-restore" in b["name"]
        ]
        assert len(before) == 1
        # The station plays: its schedule came back too.
        assert client.get(f"/api/channels/{channels[0]['id']}/guide?hours=1").json()


def test_only_a_stationplay_backup_can_be_restored(tmp_path):
    data = tmp_path / "data"
    with client_for(data, plex()) as client:
        add_station(client, 4, "Cartoons")

        def zipped(files: dict[str, bytes]) -> bytes:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n, content in files.items():
                    z.writestr(n, content)
            return buf.getvalue()

        cases = {
            "not a zip": b"hello",
            "no database": zipped({"device.json": b"{}"}),
            "not a database": zipped({"stationplay.db": b"not sqlite at all" * 100}),
        }
        for why, body in cases.items():
            res = client.post("/api/restore", content=body)
            assert res.status_code == 400, why
            assert not (data / backups.RESTORE_DIR).exists(), why
        # Files it doesn't know are ignored, and can't land outside the folder.
        good = client.get(f"/api/backups/{client.post('/api/backups').json()['name']}").content
        with zipfile.ZipFile(io.BytesIO(good)) as z:
            files = {n: z.read(n) for n in z.namelist()}
        files["../../evil.txt"] = b"x"
        files["logos/../../evil.png"] = b"x"
        assert client.post("/api/restore", content=zipped(files)).status_code == 200
        assert not (tmp_path / "evil.txt").exists() and not (data.parent / "evil.png").exists()
        staged = sorted(
            str(p.relative_to(data / backups.RESTORE_DIR))
            for p in (data / backups.RESTORE_DIR).rglob("*")
            if p.is_file()
        )
        assert staged == ["READY", "device.json", "stationplay.db"]


def test_an_unfinished_restore_is_ignored(tmp_path):
    data = tmp_path / "data"
    with client_for(data, plex()) as client:
        add_station(client, 4, "Cartoons")
    staging = data / backups.RESTORE_DIR
    staging.mkdir()
    (staging / "stationplay.db").write_bytes(b"half an upload")  # no READY: it never finished
    with client_for(data, plex()) as client:
        assert [c["number"] for c in client.get("/api/channels").json()] == [4]
    assert not staging.exists()


def test_a_restore_that_fails_is_tried_once_and_the_settings_stay(tmp_path, caplog):
    data = tmp_path / "data"
    with client_for(data, plex()) as client:
        add_station(client, 4, "Cartoons")
    staging = data / backups.RESTORE_DIR
    staging.mkdir()
    (staging / backups.READY).write_text("{}")  # ready, but its database is missing
    with client_for(data, plex()) as client:
        assert [c["number"] for c in client.get("/api/channels").json()] == [4]
    assert "Couldn't restore the backup" in caplog.text
    assert not staging.exists()


# Before an update changes the database -------------------------------------------------


def as_1290(db_path) -> None:
    """Makes the database as StationPlay 1.29.0 kept it: without the
    problems' journal and how long trouble lasted (added in 1.29.1)."""
    conn = sqlite3.connect(db_path)
    for column in ("journal", "lasted_ms"):
        conn.execute(f"ALTER TABLE problems DROP COLUMN {column}")
    conn.commit()
    conn.close()


def columns(db_path, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_an_update_backs_up_the_database_before_changing_it(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    data = tmp_path / "data"
    fp = plex()
    with client_for(data, fp) as admin:
        assert not (data / "backups").exists() or not list((data / "backups").glob("before-*"))
        admin.post("/api/access/users", json={"name": "Ada", "password": "correct horse"})
        assert admin.post("/api/access/sign-in",
                          json={"name": "Ada", "password": "correct horse"}).status_code == 200  # fmt: skip
        add_station(admin, 4, "Cartoons")
        cookies = dict(admin.cookies)
    db_path = data / backups.DB_NAME
    as_1290(db_path)
    assert db.changes_needed(db_path) == [
        "a new column, problems.journal", "a new column, problems.lasted_ms"
    ]  # fmt: skip
    # Older copies: the newest three are kept, and nothing else is touched.
    folder = data / "backups"
    folder.mkdir(exist_ok=True)
    for stamp in ("20250101-000000", "20250102-000000", "20250103-000000"):
        (folder / f"before-1.28.0-{stamp}.db").write_bytes(b"old")
    (folder / "before-notes.txt").write_text("mine")
    with client_for(data, fp) as again:
        again.cookies.update(cookies)
        # Signed in as before; the station there; the database updated.
        assert again.get("/api/access/me").json()["user"]["name"] == "Ada"
        assert [c["number"] for c in again.get("/api/channels").json()] == [4]
        assert {"journal", "lasted_ms"} <= columns(db_path, "problems")
        logged = again.get("/api/logs").text
    [copy] = [p for p in folder.glob(f"before-{__version__}-*.db")]
    assert re.fullmatch(rf"before-{re.escape(__version__)}-\d{{8}}-\d{{6}}\.db", copy.name)
    assert sorted(p.name for p in folder.glob("before-*.db")) == sorted(
        ["before-1.28.0-20250102-000000.db", "before-1.28.0-20250103-000000.db", copy.name]
    )
    assert (folder / "before-notes.txt").exists()
    # The copy is the database as it was: whole, sign-ins and all, as one file.
    assert "journal" not in columns(copy, "problems")
    conn = sqlite3.connect(copy)
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] >= 1
    assert conn.execute("SELECT name FROM channels").fetchall() == [("Cartoons",)]
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    conn.close()
    assert f"Backed up the database to backups/{copy.name} before updating it for StationPlay" in (
        caplog.text
    )
    assert "Backed up the database" in logged  # (on the Logs tab too)
    # Started again, nothing needs changing: no other copy.
    with client_for(data, fp):
        pass
    assert len(list(folder.glob(f"before-{__version__}-*.db"))) == 1


def test_without_room_for_the_copy_nothing_is_changed(tmp_path, monkeypatch, caplog):
    data = tmp_path / "data"
    with client_for(data, plex()):
        pass
    db_path = data / backups.DB_NAME
    as_1290(db_path)
    before = db_path.read_bytes()
    full = shutil.disk_usage(tmp_path)._replace(free=1 << 20)
    monkeypatch.setattr(backups.shutil, "disk_usage", lambda _: full)
    with pytest.raises(SystemExit):
        client_for(data, plex())
    assert db_path.read_bytes() == before and "journal" not in columns(db_path, "problems")
    assert (
        f"StationPlay {__version__} needs to update its database, but couldn't back it up "
        "first, so it changed nothing and stopped: its data folder's disk has 1 MB free, and the "
        "copy needs about"
    ) in caplog.text
    assert "Free up room on that disk, then start StationPlay again." in caplog.text
    monkeypatch.undo()
    # A copy that fails partway (the disk filling, say) leaves nothing behind.
    real = db.copy_database

    def fails(source, dest, sign_ins=False):
        real(source, dest, sign_ins)
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(backups, "copy_database", fails)
    with pytest.raises(SystemExit):
        client_for(data, plex())
    assert "(database or disk is full)" in caplog.text
    assert list((data / "backups").glob("before-*")) == []
    assert "journal" not in columns(db_path, "problems")
    # With room again, it goes ahead.
    monkeypatch.undo()
    with client_for(data, plex()):
        pass
    assert "journal" in columns(db_path, "problems")
    assert len(list((data / "backups").glob("before-*.db"))) == 1


def test_what_an_update_would_change_is_found(tmp_path):
    path = tmp_path / "stationplay.db"
    db.Database(path).close()
    assert db.changes_needed(path) == []
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE titles")
    conn.execute("DROP INDEX progress_by_time")
    conn.execute("CREATE INDEX views_by_start ON views (start_ms)")
    conn.execute("CREATE TABLE channel_items (channel_id INTEGER)")
    conn.execute("INSERT INTO channels (number, name, created_ms) VALUES (3, 'Old', 0)")
    conn.commit()
    conn.close()
    assert db.changes_needed(path) == [
        "a new index, progress_by_time", "a new table, titles", "stations' programs kept as eras",
        "an old index dropped", "when stations were made",
    ]  # fmt: skip
    with pytest.raises(sqlite3.OperationalError):
        db.changes_needed(tmp_path / "not-there.db")
    assert not (tmp_path / "not-there.db").exists()
