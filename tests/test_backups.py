"""Backups: made every night and on request, and restored on the next start."""

from __future__ import annotations

import io
import json
import os
import zipfile

from fastapi.testclient import TestClient

from app import backups
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
