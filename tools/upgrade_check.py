#!/usr/bin/env python3
"""Upgrade check, to run for every release: the release before it, then this
one on its data folder, then back again, and a fresh install.

1. The release before (by its git tag: the newest release tag older than
   this checkout's version, unless --from says: a tag, or a release's
   commit, its version as its app/__init__.py has it) is unpacked into a
   temporary folder with git archive, so the repository is left as it is.
2. It's started on a new data folder, against the tests' stand-in Plex
   served on a port of its own, and given data through its API: an Admin
   signed in on the page, a User with a passcode and a Viewing Level, a
   "Kids" User with neither a password nor a passcode, an app signed in on
   a linked device, settings, a station, and a problem from the app.
3. It's stopped, and this checkout is started on the same data folder,
   which must find everything there: everyone still signed in (the page and
   the app), the User's passcode and level, where everyone shows on the
   apps' pickers, the linked device, the settings and the station; and, if
   this version changes the database, the database backed up first, as
   before-<this version>-<date>.db, as the Logs tab says (otherwise no
   copy). What's new works with them: a problem with its journal, (from
   1.30.0) a person's report on the Broken files tab, with everyone able to
   report to start with, and (from 1.30.1) new people showing only on
   devices they sign in on, as the Admin never chose otherwise, and Use for
   everyone, which keeps Kids as they were.
4. Live alerts, kept across a restart (from 1.30.3): with Notify a web
   address on (to a stand-in here), the report becomes an alert, and
   backups failing another. The report is dismissed and StationPlay
   stopped before its next look, and started again: both alerts are there
   at once with the same IDs, neither is sent again, and the one fixed
   while it was stopped is said to be, once, at its first look; the other
   stays live.
5. It's stopped, and rolled back: first the release before is started on
   the database as it is, live alert and all (which it ignores, leaving the
   alerts as they were); then as the README's Rolling back says (the copy,
   if there is one, put back as stationplay.db, its -wal and -shm removed);
   the release before is started again, and must work with its data,
   signed in as before (or with what this version wrote, when there was no
   copy to put back), and with the broken-files list as this one left it:
   a program's entry as before, an entry for another of its versions (which
   a release before 1.30.0 doesn't know, and leaves alone; one from 1.30.0
   lists it too), and (from 1.30.2) one about the second of a movie's two
   files, listed as it is. There, the Admin chooses where new people show
   (Devices at home); this checkout is started again, and keeps that
   choice.
6. A fresh install of this checkout: it starts, takes its first Admin, and
   makes no copy; new people show only on devices they sign in on.

It prints PASS or FAIL for each check (failures always; all with -v) and
exits 1 if any failed. Each StationPlay it starts is on free ports of its
own, in a process group of its own, and only that group is stopped (by its
PID); nothing else is touched. Its temporary folders are deleted after
(--keep leaves them, with each StationPlay's output, for a look).

Run it from the repo root, with the tests' requirements installed:

    python tools/upgrade_check.py                  # the release before, to this checkout
    python tools/upgrade_check.py --from v1.28.1   # from another release
    python tools/upgrade_check.py -v --keep
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import logging
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app import __version__  # noqa: E402
from app.broken import CHECK, DEEP_SCAN, BrokenFiles  # noqa: E402
from app.db import Item, changes_needed  # noqa: E402
from tests.fakeplex import FakePlex  # noqa: E402

ADMIN = {"name": "Ada", "password": "correct horse battery"}
USER = {"name": "Sam", "password": "staple battery horse", "role": "user"}
KIDS = {"name": "Kids", "role": "user"}  # (no password, no passcode)
NEW = {"name": "Bo", "password": "horse staple battery", "role": "user"}
PASSCODE = "4321"
APP = {"app": "StationPlay for Android", "deviceName": "Den"}
STATION = {"number": 5, "name": "Upgrade TV", "sources": [{"type": "show", "ratingKey": "100"}]}
SETTINGS = {"tuners": 3, "picture": "1080p"}
START_S = 90.0  # how long a StationPlay may take to start (it tests ffmpeg first)
# The longest an alert is waited for: its checks look 20 seconds after
# StationPlay starts, then every minute.
ALERT_WAIT_S = 100.0


class Checks:
    """Counts PASS/FAIL and prints them (failures always; all with -v)."""

    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.passed = 0
        self.failed = 0

    def ok(self, passed: bool, what: str, detail: object = "") -> bool:
        if passed:
            self.passed += 1
            if self.verbose:
                print(f"  PASS  {what}")
        else:
            self.failed += 1
            print(f"  FAIL  {what}{f' — {detail}' if detail != '' else ''}")
        return passed

    def section(self, title: str) -> None:
        print(f"\n{title}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def version_of(tag: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", tag)[:3])


def version_at(ref: str) -> str:
    """The version a release (by its tag or commit) says it is."""
    source = subprocess.run(
        ["git", "show", f"{ref}:app/__init__.py"], cwd=ROOT, capture_output=True, text=True,
        check=True,
    ).stdout  # fmt: skip
    found = re.search(r'__version__ = "([^"]+)"', source)
    if found is None:
        raise SystemExit(f"{ref} doesn't say its version")
    return found.group(1)


def release_before(version: str) -> str:
    """The newest release tag older than `version`."""
    tags = subprocess.run(
        ["git", "tag", "--list", "v*"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    older = [
        t
        for t in tags
        if re.fullmatch(r"v\d+\.\d+\.\d+", t) and version_of(t) < version_of(version)
    ]
    if not older:
        raise SystemExit(f"No release tag older than {version}")
    return max(older, key=version_of)


def unpack(tag: str, folder: Path) -> None:
    """The release at `tag`, as its files were, into `folder`."""
    archive = subprocess.run(
        ["git", "archive", "--format=tar", tag, "app"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(folder, filter="data")


class StandInPlex:
    """The tests' stand-in Plex (a show of two episodes), served over HTTP on
    a port of its own, in a thread of its own; and, at /notify, the web
    address alerts are sent to (what's sent, in `notified`)."""

    def __init__(self) -> None:
        self.notified: list[dict] = []
        self.fp = FakePlex()
        self.fp.add_show("100", "Upgrade Show")
        for n in (1, 2):
            self.fp.add_episode(f"20{n}", "100", 1, n, f"Part {n}", f"/tv/u{n}.mkv", 22 * 60_000)
        sock = socket.create_server(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        config = uvicorn.Config(self._app, log_level="error", lifespan="off", interface="asgi3")
        self.server = uvicorn.Server(config)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self.loop.run_until_complete, args=(self.server.serve(sockets=[sock]),),
            daemon=True,
        )  # fmt: skip
        self.thread.start()
        while not self.server.started:
            time.sleep(0.05)

    async def _app(self, scope, receive, send) -> None:
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        if scope["path"] == "/notify":
            self.notified.append(json.loads(body))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        query = scope["query_string"].decode()
        request = httpx.Request(
            scope["method"],
            f"http://plex.test{scope['path']}{'?' + query if query else ''}",
            headers=[(k.decode(), v.decode()) for k, v in scope["headers"]],
            content=body,
        )
        answer = self.fp.handler(request)
        headers = [(k.encode(), v.encode()) for k, v in answer.headers.items()
                   if k.lower() not in ("content-length", "transfer-encoding")]  # fmt: skip
        await send(
            {"type": "http.response.start", "status": answer.status_code, "headers": headers}
        )
        await send({"type": "http.response.body", "body": answer.content})

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)


class StationPlay:
    """One StationPlay, from `code` (a folder holding app/), on `data`, in a
    process group of its own."""

    def __init__(self, code: Path, data: Path, plex: str, output: Path) -> None:
        self.data = data
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        env = {
            **os.environ, "PLEX_URL": plex, "PLEX_TOKEN": "token", "DATA_DIR": str(data),
            "PORT": str(self.port), "HW_ACCEL": "cpu", "PYTHONDONTWRITEBYTECODE": "1",
        }  # fmt: skip
        for name in ("PUBLIC_PORT", "PYTHONPATH", "BASE_URL"):  # (this one's own, only)
            env.pop(name, None)
        self.output = output.open("ab")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "app.main"], cwd=code, env=env, stdout=self.output,
            stderr=subprocess.STDOUT, start_new_session=True,
        )  # fmt: skip

    def started(self) -> bool:
        deadline = time.monotonic() + START_S
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                return False
            with contextlib.suppress(httpx.HTTPError):
                if httpx.get(f"{self.url}/api/v1/server", timeout=2).status_code == 200:
                    return True
            time.sleep(0.5)
        return False

    def stop(self) -> int | None:
        """Stops it (its own process group only); its exit code."""
        if self.proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(10)
        self.output.close()
        return self.proc.returncode


def give_data(checks: Checks, url: str) -> dict:
    """An Admin, a User with a passcode and a Viewing Level, Kids, an app
    signed in on a linked device, settings, a station and a problem; what
    was made."""
    page = httpx.Client(base_url=url, timeout=30)
    app = httpx.Client(base_url=url, timeout=30)
    checks.ok(
        page.post("/api/access/users", json=ADMIN).status_code == 201, "the first Admin is made"
    )
    checks.ok(page.post("/api/access/sign-in", json=ADMIN).status_code == 200, "the Admin signs in")
    sam = page.post("/api/access/users", json=USER).json()
    levels = page.get("/api/access/viewing").json()["levels"]
    teen = next(lv["id"] for lv in levels if lv["builtin"] == "teen")
    checks.ok(page.put(f"/api/access/users/{sam['id']}/viewing", json={"level": teen}).status_code == 200,
              "the User is given a Viewing Level")  # fmt: skip
    picker = page.put(
        f"/api/access/users/{sam['id']}/picker", json={"pin": PASSCODE, "showOn": "all"}
    )
    checks.ok(picker.status_code == 200, "the User is given a passcode", picker.text[:200])
    kids = page.post("/api/access/users", json=KIDS)
    checks.ok(
        kids.status_code == 201, "Kids are added, with no password or passcode", kids.text[:200]
    )
    signed = app.post("/api/internal/sign-in", json={**ADMIN, **APP, "picker": True}).json()
    checks.ok(
        bool(signed.get("token") and signed.get("deviceKey")), "an app signs in on a linked device"
    )
    checks.ok(page.put("/api/playback", json=SETTINGS).status_code == 200, "settings are changed")
    made = page.post("/api/channels", json=STATION)
    checks.ok(made.status_code == 201, "a station is made", made.text[:200])
    bearer = {"Authorization": f"Bearer {signed['token']}"}
    sent = app.post("/api/internal/problem", headers=bearer,
                    json={"kind": "crashed", "detail": "before the update", **APP})  # fmt: skip
    checks.ok(sent.status_code == 200, "the app sends a problem")
    return {
        "cookies": dict(page.cookies),
        "bearer": bearer,
        "device": signed["deviceKey"],
        "sam": sam["id"],
        "teen": teen,
        "users": sorted(u["name"] for u in page.get("/api/access/users").json()),
        "shown": shown_on(page),
        "devices": sorted(d["name"] for d in page.get("/api/access/devices").json()["devices"]),
    }


def shown_on(page: httpx.Client) -> dict[str, str]:
    """Where each person shows on the apps' pickers (their Show on)."""
    return {u["name"]: u["showOn"] for u in page.get("/api/access/users").json()}


def has_data(checks: Checks, url: str, made: dict, version: str, where: str) -> None:
    """Everything give_data made is there, everyone still signed in."""
    page = httpx.Client(base_url=url, timeout=30, cookies=made["cookies"])
    server = httpx.get(f"{url}/api/v1/server", timeout=10).json()
    checks.ok(server["version"] == version, f"{where}: it's {version}", server["version"])
    me = page.get("/api/access/me").json().get("user") or {}
    checks.ok(
        me.get("name") == ADMIN["name"], f"{where}: the Admin is still signed in on the page", me
    )
    app_me = httpx.get(f"{url}/api/internal/me", headers=made["bearer"], timeout=10).json()
    checks.ok((app_me.get("user") or {}).get("name") == ADMIN["name"],
              f"{where}: the app is still signed in", app_me)  # fmt: skip
    users = sorted(u["name"] for u in page.get("/api/access/users").json())
    checks.ok(users == made["users"], f"{where}: the same people", users)
    shown = shown_on(page)
    checks.ok(shown == made["shown"], f"{where}: everyone shows where they did", shown)
    level = page.get("/api/access/viewing").json()["users"].get(str(made["sam"]), {}).get("level")
    checks.ok(level == made["teen"], f"{where}: the User's Viewing Level is kept", level)
    devices = sorted(d["name"] for d in page.get("/api/access/devices").json()["devices"])
    checks.ok(devices == made["devices"], f"{where}: the linked device is kept", devices)
    playback = page.get("/api/playback").json()
    checks.ok((playback.get("tuners"), playback.get("picture")) == (3, "1080p"),
              f"{where}: the settings are kept", playback)  # fmt: skip
    stations = [(c["number"], c["name"]) for c in page.get("/api/channels").json()]
    checks.ok(
        stations == [(STATION["number"], STATION["name"])],
        f"{where}: the station is kept",
        stations,
    )
    guide = httpx.get(f"{url}/api/v1/guide", headers=made["bearer"], timeout=30)
    programs = guide.json()["stations"][0]["programs"] if guide.status_code == 200 else []
    checks.ok(bool(programs), f"{where}: the station's guide is there", guide.text[:200])
    # (Last: choosing someone on the device signs out who was there.)
    chose = httpx.post(f"{url}/api/internal/picker/choose", timeout=30,
                       headers={"stationplay-device": made["device"]},
                       json={"id": made["sam"], "pin": PASSCODE})  # fmt: skip
    checks.ok(
        chose.status_code == 200, f"{where}: the User's passcode still works", chose.text[:200]
    )


def alerts_of(url: str, bearer: dict) -> dict[str, dict]:
    """The alerts an Admin's app is given now, by kind."""
    got = httpx.get(f"{url}/api/internal/alerts", headers=bearer, timeout=10).json()["alerts"]
    return {a["kind"]: a for a in got}


def waited(found, seconds: float = ALERT_WAIT_S) -> bool:
    """Whether `found()` came true within `seconds`."""
    deadline = time.monotonic() + seconds
    while not found():
        if time.monotonic() > deadline:
            return False
        time.sleep(1)
    return True


def kept_alerts(data: Path) -> list[tuple]:
    """The alerts kept in a data folder's database (none before 1.30.3)."""
    conn = sqlite3.connect(f"{(data / 'stationplay.db').resolve().as_uri()}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'alerts'").fetchone():
            return []
        return conn.execute(
            "SELECT kind, about, since_ms, sentence, fixed_ms FROM alerts ORDER BY since_ms"
        ).fetchall()
    finally:
        conn.close()


def fail_backups(page: httpx.Client, data: Path) -> None:
    """Backups failing twice: the backups folder a file meanwhile."""
    folder, aside = data / "backups", data / "backups-aside"
    folder.rename(aside)
    folder.write_text("not a folder")
    try:
        for _ in range(2):
            page.post("/api/backups")
    finally:
        folder.unlink()
        aside.rename(folder)


def new_people(checks: Checks, url: str, made: dict) -> dict:
    """From 1.30.1: as the Admin never chose where new people show, they
    show only on devices they sign in on; Use for everyone shows everyone
    that way, but Kids, kept as they were; and the User, signed in on the
    linked device, is on its list. What the release before should find, if
    nothing is put back."""
    page = httpx.Client(base_url=url, timeout=30, cookies=made["cookies"])
    default = page.get("/api/access/devices").json()["default"]
    checks.ok(default == "signed-in", "new people show only on devices they sign in on, as the "
              "Admin never chose otherwise", default)  # fmt: skip
    bo = page.post("/api/access/users", json=NEW)
    checks.ok(bo.status_code == 201 and bo.json()["showOn"] == "signed-in",
              "someone new shows only on devices they sign in on", bo.text[:200])  # fmt: skip
    # (Who isn't shown that way yet: the Admin and the User, made before
    # 1.30.1; fewer when the release before was 1.30.1 or later.)
    moving = [u["name"] for u in page.get("/api/access/users").json()
              if u["showOn"] != "signed-in" and u["name"] != KIDS["name"]]  # fmt: skip
    everyone = page.post("/api/access/devices/everyone", json={"showOn": "signed-in"})
    said = everyone.json() if everyone.status_code == 200 else everyone.text[:200]
    checks.ok(said == {"default": "signed-in", "changed": len(moving), "kept": [KIDS["name"]]},
              f"Use for everyone: {len(moving)} change ({', '.join(moving) or 'no one'}), "
              "Kids are kept", said)  # fmt: skip
    signed = httpx.post(f"{url}/api/internal/picker/sign-in", timeout=30,
                        headers={"stationplay-device": made["device"]},
                        json={"name": USER["name"], "password": USER["password"]})  # fmt: skip
    checks.ok(
        signed.status_code == 200, "the User signs in on the linked device", signed.text[:200]
    )
    return {
        **made,
        "users": sorted([*made["users"], NEW["name"]]),
        "shown": shown_on(page),
    }


def stopped(checks: Checks, sp: StationPlay, version: str) -> None:
    """It stops when asked, its database closed (nothing left in its -wal).
    (Uvicorn raises SIGTERM again once it has shut down, as Docker expects.)"""
    code = sp.stop()
    wal = sp.data / "stationplay.db-wal"
    closed = not wal.exists() or wal.stat().st_size == 0
    checks.ok(code in (0, -signal.SIGTERM) and closed, f"{version} stops cleanly, its database closed",
              f"exit code {code}, -wal left: {not closed}")  # fmt: skip


def run(checks: Checks, before_tag: str, keep: bool) -> None:
    work = Path(tempfile.mkdtemp(prefix="upgrade-check-"))
    plex = StandInPlex()
    running: list[StationPlay] = []

    def start(code: Path, data: Path, name: str) -> StationPlay | None:
        sp = StationPlay(code, data, plex.url, work / f"{name}.log")
        running.append(sp)
        if not checks.ok(sp.started(), f"{name} starts", f"see {work / f'{name}.log'}"):
            sp.stop()
            return None
        return sp

    try:
        old_code = work / "release"
        unpack(before_tag, old_code)
        data = work / "data"
        before = version_at(before_tag)
        print(f"From {before_tag} to this checkout ({__version__}), in {work}")

        checks.section(f"{before}: a new install, given some data")
        sp = start(old_code, data, f"{before}-first")
        if sp is None:
            return
        made = give_data(checks, sp.url)
        stopped(checks, sp, before)
        # (What this version changes in that database, if anything: a release
        # that changes nothing in it makes no copy, as the README says.)
        checks.section(f"Updated to {__version__}")
        changes = changes_needed(data / "stationplay.db")
        sp = start(ROOT, data, f"{__version__}-updated")
        if sp is None:
            return
        page = httpx.Client(base_url=sp.url, timeout=30, cookies=made["cookies"])
        notify = {"on": True, "url": f"{plex.url}/notify", "format": "json"}
        checks.ok(page.put("/api/notify", json=notify).status_code == 200,
                  "alerts are sent to a web address")  # fmt: skip
        has_data(checks, sp.url, made, __version__, "updated")
        copies = sorted((data / "backups").glob(f"before-{__version__}-*.db"))
        logs = page.get("/api/logs").text
        if changes:
            checks.ok(len(copies) == 1, "the database was backed up before it was changed",
                      (changes, copies))  # fmt: skip
            checks.ok(bool(copies) and f"Backed up the database to backups/{copies[0].name}"
                      in logs, "the Logs tab says so")  # fmt: skip
        else:
            checks.ok(copies == [] and "Backed up the database" not in logs,
                      "nothing in the database needed changing, so no copy was made",
                      copies)  # fmt: skip
        if version_of(before) < (1, 30, 3):
            checks.ok("a new table, alerts" in logs, "(for the alerts it now keeps)")
        sent = page.post("/api/internal/problem", json={
            "kind": "crashed", "detail": "after the update", "journal": "a\nb", **APP})  # fmt: skip
        checks.ok(sent.status_code == 200, "what's new works (a problem with its journal)",
                  sent.text[:200])  # fmt: skip
        problems = page.get("/api/problems").json()["problems"]
        checks.ok(any(p.get("journal") for p in problems), "its journal is kept", problems)
        # (Signed in again: choosing someone on the device signed the app out.)
        app = httpx.post(f"{sp.url}/api/internal/sign-in", json={**ADMIN, **APP}, timeout=30)
        bearer = {"Authorization": f"Bearer {app.json().get('token')}"}
        if not copies:
            made["bearer"] = bearer  # (no copy to put back: rolled back, it's signed in so)
        reported = httpx.post(f"{sp.url}/api/internal/report-problem", headers=bearer, timeout=30,
                              json={"choice": "wrong-language", "station": STATION["number"]})  # fmt: skip
        checks.ok(reported.status_code == 200, "what's new works (a person's report, from a "
                  "station)", reported.text[:200])  # fmt: skip
        rows = page.get("/api/reports").json()["reports"]
        who = [(x["who"], x["label"]) for row in rows for x in row["reports"]]
        checks.ok(who == [(ADMIN["name"], "Wrong language")], "it's on the Broken files tab", rows)
        users = page.get("/api/access/users").json()
        checks.ok(all(u["canReport"] for u in users), "everyone can report problems, to start "
                  "with", [(u["name"], u.get("canReport")) for u in users])  # fmt: skip
        # Live alerts: the report (at the checks' next look), and backups.
        fail_backups(page, data)
        checks.ok(waited(lambda: alerts_of(sp.url, bearer).keys() == {"files", "backups"}),
                  "the report and backups failing are alerts", alerts_of(sp.url, bearer))  # fmt: skip
        live = {kind: a["id"] for kind, a in alerts_of(sp.url, bearer).items()}
        checks.ok(waited(lambda: len(plex.notified) == 2, 10)
                  and sorted(n["kind"] for n in plex.notified) == ["backups", "files"],
                  "each is sent to the web address", plex.notified)  # fmt: skip
        # The report dealt with, then stopped before the checks look again.
        if rows:
            page.post(f"/api/reports/{rows[0]['key']}/dismiss")
        stopped(checks, sp, __version__)

        checks.section(f"{__version__} started again, with the alerts live")
        sp = start(ROOT, data, f"{__version__}-restarted")
        if sp is None:
            return
        now = alerts_of(sp.url, bearer)
        checks.ok({k: a["id"] for k, a in now.items() if a["fixed"] is None} == live,
                  "both are there at once, with the same IDs", now)  # fmt: skip
        page = httpx.Client(base_url=sp.url, timeout=30, cookies=made["cookies"])
        logs = page.get("/api/logs").json()["text"]
        checks.ok(logs.count("Alert still going: ") == 2, "the Logs tab says they're still going",
                  logs[-2000:])  # fmt: skip
        checks.ok(waited(lambda: alerts_of(sp.url, bearer)["files"]["fixed"] is not None),
                  "the one fixed while StationPlay was stopped is fixed at its first look")  # fmt: skip
        now = alerts_of(sp.url, bearer)
        checks.ok({k: a["id"] for k, a in now.items()} == live and now["backups"]["fixed"] is None,
                  "with its ID, and the other still live", now)  # fmt: skip
        waited(lambda: len(plex.notified) > 2, 10)
        said = sorted((n["kind"], n["state"]) for n in plex.notified)
        checks.ok(said == [("backups", "started"), ("files", "fixed"), ("files", "started")],
                  "neither was sent again, and the fix was sent once", said)  # fmt: skip
        # (With no copy to put back, the release before finds what's changed
        # since, and the app's sign-in from just now.)
        since = {**new_people(checks, sp.url, made), "bearer": bearer}
        stopped(checks, sp, __version__)
        # The broken-files list, as this version keeps it: the station's
        # program, and another version of it (Media's alone).
        logging.disable(logging.WARNING)  # (what record() says, as it would in StationPlay's log)
        listed = BrokenFiles(data / "broken-files.json")
        first = Item(0, 0, 22 * 60_000, "201", "episode", "Part 1", show_title="Upgrade Show",
                     show_key="100", season=1, episode=1, file_path="/tv/u1.mkv")  # fmt: skip
        listed.record(first, "Deep scan: the picture breaks up around 3:00", STATION["number"],
                      problem="damaged", found=DEEP_SCAN)  # fmt: skip
        listed.record(replace(first, file_path="/tv/u1-4k.mkv"), "Check: no sound anywhere in it",
                      None, problem="damaged", version="2011", library="1")  # fmt: skip
        # (From 1.30.2: one about the second of a movie's two files.)
        movie = Item(0, 0, 120 * 60_000, "300", "movie", "Two Discs", year=1999,
                     file_path="/films/two-cd1.mkv")  # fmt: skip
        listed.record(movie, "Check: no sound anywhere in it", None, "/films/two-cd2.mkv",
                      problem="damaged", found=CHECK, part=(2, 2))  # fmt: skip
        logging.disable(logging.NOTSET)

        checks.section(f"{before} on {__version__}'s database as it is, alerts and all")
        as_is = work / "data-as-is"
        shutil.copytree(data, as_is)
        kept = kept_alerts(as_is)
        checks.ok(sorted((k[0], k[4] is None) for k in kept) == [("backups", True), ("files", False)],
                  "the alerts are kept, one live", kept)  # fmt: skip
        sp = start(old_code, as_is, f"{before}-as-is")
        if sp is None:
            return
        page = httpx.Client(base_url=sp.url, timeout=30, cookies=made["cookies"])
        server = page.get("/api/v1/server").json()
        me = page.get("/api/access/me").json().get("user") or {}
        stations = [(c["number"], c["name"]) for c in page.get("/api/channels").json()]
        checks.ok((server["version"], me.get("name"), stations)
                  == (before, ADMIN["name"], [(STATION["number"], STATION["name"])]),
                  "it starts, the Admin still signed in, the station there",
                  (server["version"], me, stations))  # fmt: skip
        stopped(checks, sp, before)
        checks.ok(kept_alerts(as_is) == kept, "it leaves the alerts as they were",
                  kept_alerts(as_is))  # fmt: skip
        shutil.rmtree(as_is)

        checks.section(f"Rolled back to {before}, as the README says")
        if copies:
            shutil.copyfile(copies[0], data / "stationplay.db")
            for suffix in ("-wal", "-shm"):
                (data / f"stationplay.db{suffix}").unlink(missing_ok=True)
        sp = start(old_code, data, f"{before}-rolled-back")
        if sp is None:
            return
        has_data(checks, sp.url, made if copies else since, before, "rolled back")
        page = httpx.Client(base_url=sp.url, timeout=30, cookies=made["cookies"])
        said = [p["details"] for p in page.get("/api/problems").json()["problems"]]
        if copies:
            checks.ok(said == [["before the update"]], "the database is as it was before the update",
                      said)  # fmt: skip
        else:
            checks.ok(sorted(d for details in said for d in details)
                      == ["after the update", "before the update"],
                      "with no copy to put back, it reads what was written since", said)  # fmt: skip
        entries = page.get("/api/broken").json()
        listed = sorted((e["ratingKey"], e.get("version") or "", e["reason"]) for e in entries)
        program = [
            ("201", "", "Deep scan: the picture breaks up around 3:00"),
            ("300", "", "Check: no sound anywhere in it, in part 2 of 2"),
        ]
        if version_of(before) < (1, 30, 0):
            checks.ok(listed == program, "the broken-files list: the programs' entries as before "
                      "(a movie's in two files listed as it is), another version's left alone",
                      entries)  # fmt: skip
        else:
            other = [("201", "2011", "Check: no sound anywhere in it")]
            checks.ok(listed == sorted(program + other), "the broken-files list, as this version "
                      "left it: the programs' entries (a movie's in two files listed as it is), "
                      "and another version's", entries)  # fmt: skip
        chose = page.put("/api/access/devices/default", json={"showOn": "home"})
        checks.ok(chose.status_code == 200, "the Admin chooses where new people show",
                  chose.text[:200])  # fmt: skip
        stopped(checks, sp, before)

        checks.section(f"Updated to {__version__} again")
        sp = start(ROOT, data, f"{__version__}-again")
        if sp is None:
            return
        page = httpx.Client(base_url=sp.url, timeout=30, cookies=made["cookies"])
        default = page.get("/api/access/devices").json()["default"]
        checks.ok(default == "home", "the Admin's choice stays: new people show on every device "
                  "at home", default)  # fmt: skip
        stopped(checks, sp, __version__)

        checks.section(f"A fresh install of {__version__}")
        fresh = work / "fresh"
        sp = start(ROOT, fresh, f"{__version__}-fresh")
        if sp is None:
            return
        page = httpx.Client(base_url=sp.url, timeout=30)
        server = page.get("/api/v1/server").json()
        checks.ok(server["version"] == __version__, f"it's {__version__}", server["version"])
        checks.ok(
            page.post("/api/access/users", json=ADMIN).status_code == 201, "its first Admin is made"
        )
        checks.ok(page.post("/api/access/sign-in", json=ADMIN).status_code == 200, "and signs in")
        made = page.post("/api/channels", json=STATION)
        checks.ok(made.status_code == 201, "a station is made", made.text[:200])
        shown = {who["name"]: page.post("/api/access/users", json=who).json().get("showOn")
                 for who in (NEW, KIDS)}  # fmt: skip
        checks.ok(shown == {NEW["name"]: "signed-in", KIDS["name"]: "home"},
                  "new people show only on devices they sign in on (Kids, on every device at "
                  "home, as they can't sign in)", shown)  # fmt: skip
        choices = page.get("/api/internal/report-choices").json().get("choices") or []
        checks.ok(len(choices) == 12, "people can report problems", choices)
        checks.ok(not list(fresh.glob("backups/before-*")), "no copy is made of a new database")
        stopped(checks, sp, __version__)
    finally:
        for sp in running:
            sp.stop()
        plex.stop()
        if keep:
            print(f"\nKept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--from", dest="before", default="", help="the release tag to start from")
    ap.add_argument("--keep", action="store_true", help="keep the temporary folders")
    ap.add_argument("-v", "--verbose", action="store_true", help="show every check")
    args = ap.parse_args()
    checks = Checks(args.verbose)
    run(checks, args.before or release_before(__version__), args.keep)
    print(f"\n{checks.passed} passed, {checks.failed} failed")
    return 1 if checks.failed else 0


if __name__ == "__main__":
    sys.exit(main())
