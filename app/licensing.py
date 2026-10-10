"""The server's license (see the plan's Licensing): one lifetime license for
one StationPlay server unlocks StationPlay's apps on up to its number of
devices (15 for every license sold now). The server never locks anything:
it keeps the license file and hands it to the apps, which check its
signature (with public keys built into them) and decide. It checks only
that a license is well formed and is for this server, so the page can say
plainly what's installed. It never contacts anything to do so: a license
arrives only from an app (after a purchase) or an Admin's upload.

The server's ID is made once, at random, when StationPlay first starts, and
kept in the database, so a backup restored onto new hardware keeps it, and
the license with it; a fresh install gets a new one. Both are also kept in
the data folder (KEPT_FILE), so rolling back to the database as it was
before an update (see backups.py) keeps them too: when the database has
none, the file's are used. When the two differ, the database's win (a
backup restored from another server's install).

A license file is JSON:

    {"payload": "<the payload's JSON, base64url>",
     "signature": "<its Ed25519 signature, base64url>",
     "key": "<which public key signed it>"}

and its payload: {"license_id", "server_id", "tier", "device_limit",
"issued_at" (Unix seconds), "format_version" (1)}, with no expiry. A license
code is the same file as one line: "SPL1." and the file, base64url.

A device is one of StationPlay's apps linked to the server (see devices.py):
its slot is its place in the order the devices were linked, and the first
`device_limit` are covered. Unlinking one frees its slot for the next.
People watching through Plex, Jellyfin or other tuner apps, and StationPlay's
own page, never use one.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from . import access

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .db import Database
    from .main import AppContext

log = logging.getLogger("stationplay.license")

SERVER_ID_META = "server_id"
LICENSE_META = "license"
KEPT_FILE = "license.json"
CODE_PREFIX = "SPL1."
FORMAT_VERSION = 1
LICENSE_MOST = 8 * 1024  # (a license, as uploaded or pasted: a few hundred bytes)
PAYLOAD_MOST = 4 * 1024
FIELDS = ("license_id", "server_id", "tier", "device_limit", "issued_at", "format_version")
NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
SERVER_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

NOT_A_LICENSE = (
    "That isn't a StationPlay license. Upload the license file, or paste the whole license code."
)
OTHER_SERVER = "That license is for another StationPlay server: its server ID isn't this one's."
NEWER = "That license needs a newer StationPlay. Update StationPlay, then install it again."


@dataclass(frozen=True)
class License:
    """An installed license, as its payload says."""

    license_id: str
    server_id: str
    tier: str
    device_limit: int
    issued_at: int
    file: dict[str, str]  # (the file itself, for the apps to check)


def _unbase64(text: Any, most: int) -> bytes:
    if not isinstance(text, str) or not text or len(text) > most:
        raise ValueError(NOT_A_LICENSE)
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise ValueError(NOT_A_LICENSE) from None


def read(text: str, server_id: str) -> License:
    """A license, from its file or code, if it's well formed and for this
    server (`server_id`). ValueError, saying why, otherwise. Its signature
    is the apps' to check."""
    text = text.strip()
    if not text or len(text) > LICENSE_MOST:
        raise ValueError(NOT_A_LICENSE)
    if text.startswith(CODE_PREFIX):
        try:
            text = _unbase64(text[len(CODE_PREFIX) :], LICENSE_MOST).decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(NOT_A_LICENSE) from None
    try:
        file = json.loads(text)
        payload = json.loads(_unbase64(file["payload"], PAYLOAD_MOST))
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ValueError(NOT_A_LICENSE) from None
    if not isinstance(payload, dict):
        raise ValueError(NOT_A_LICENSE)
    # (Its version first: a later format may carry more than this one knows.)
    version = payload.get("format_version")
    if type(version) is not int or version < 1:
        raise ValueError(NOT_A_LICENSE)
    if version > FORMAT_VERSION:
        raise ValueError(NEWER)
    if set(file) != {"payload", "signature", "key"} or set(payload) != set(FIELDS):
        raise ValueError(NOT_A_LICENSE)
    if len(_unbase64(file["signature"], 128)) != 64:  # (an Ed25519 signature's size)
        raise ValueError(NOT_A_LICENSE)
    if not isinstance(file["key"], str) or not NAME.fullmatch(file["key"]):
        raise ValueError(NOT_A_LICENSE)
    texts = [payload[k] for k in ("license_id", "server_id", "tier")]
    numbers = [payload[k] for k in ("device_limit", "issued_at")]
    if not all(isinstance(t, str) and NAME.fullmatch(t) for t in texts):
        raise ValueError(NOT_A_LICENSE)
    if not all(type(n) is int for n in numbers) or not 1 <= numbers[0] <= 10_000 or numbers[1] < 0:
        raise ValueError(NOT_A_LICENSE)
    if payload["server_id"] != server_id:
        raise ValueError(OTHER_SERVER)
    return License(
        license_id=texts[0],
        server_id=texts[1],
        tier=texts[2],
        device_limit=numbers[0],
        issued_at=numbers[1],
        file={k: file[k] for k in ("payload", "signature", "key")},
    )


def code_of(file: dict[str, str]) -> str:
    """A license file as a license code (one line, to paste)."""
    text = json.dumps(file, separators=(",", ":"), sort_keys=True)
    return CODE_PREFIX + base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


class Licensing:
    """This server's ID, its license, and its devices' slots."""

    def __init__(self, db: Database, folder: Path) -> None:
        self.db = db
        self.file = folder / KEPT_FILE
        kept = self._read_file()
        ours, licensed = db.get_meta(SERVER_ID_META), db.get_meta(LICENSE_META)
        theirs, kept_license = kept.get("serverId", ""), kept.get("license", "")
        if theirs and kept_license and not licensed and self._is_for(kept_license, theirs):
            # (A license the database doesn't have: it was rolled back to its
            # copy from before an update, or a backup from before the license
            # was installed was restored. The license stays, and the ID it's
            # for with it.)
            ours = theirs
            db.set_meta(SERVER_ID_META, ours)
            db.set_meta(LICENSE_META, kept_license)
            log.info("Kept this StationPlay's server ID and license from its data folder")
        elif not ours and theirs:
            ours = theirs
            db.set_meta(SERVER_ID_META, ours)
        if not ours:
            ours = str(uuid.uuid4())
            db.set_meta(SERVER_ID_META, ours)
            log.info("This StationPlay's server ID is %s", ours)
        self.server_id = ours
        self._write_file()

    @staticmethod
    def _is_for(text: str, server_id: str) -> bool:
        try:
            read(text, server_id)
        except ValueError:
            return False
        return True

    def _read_file(self) -> dict[str, str]:
        """The server's ID and license as the data folder keeps them ({} if
        there's no such file, or it isn't one: it's then written anew)."""
        try:
            kept = json.loads(self.file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, RecursionError) as e:
            log.warning("Couldn't read %s (%s)", self.file.name, e)
            return {}
        if (
            not isinstance(kept, dict)
            or not isinstance(kept.get("serverId"), str)
            or not SERVER_ID.fullmatch(kept["serverId"])
            or not isinstance(kept.get("license"), str)
            or len(kept["license"]) > LICENSE_MOST
        ):
            log.warning("%s isn't as StationPlay keeps it, so it's set aside", self.file.name)
            return {}
        return {"serverId": kept["serverId"], "license": kept["license"]}

    def _write_file(self) -> None:
        """The server's ID and license, as the database has them, to the data
        folder too (see the module's notes)."""
        kept = {"serverId": self.server_id, "license": self.db.get_meta(LICENSE_META)}
        if self._read_file() == kept:
            return
        try:
            part = self.file.with_suffix(".json.part")
            part.write_text(json.dumps(kept), encoding="utf-8")
            part.replace(self.file)
        except OSError as e:
            log.warning("Couldn't keep the server's ID and license in %s (%s)", self.file.name, e)

    def current(self) -> License | None:
        """The license installed, if there's one (and it's still this
        server's: a database moved onto another server's keeps its own)."""
        kept = self.db.get_meta(LICENSE_META)
        if not kept:
            return None
        try:
            return read(kept, self.server_id)
        except ValueError:
            return None

    def install(self, text: str) -> License:
        """Installs a license (in place of any before it). ValueError."""
        found = read(text, self.server_id)
        self.db.set_meta(LICENSE_META, json.dumps(found.file, sort_keys=True))
        self._write_file()
        return found

    def remove(self) -> bool:
        """Removes the license: whether there was one."""
        had = bool(self.db.get_meta(LICENSE_META))
        self.db.set_meta(LICENSE_META, "")
        self._write_file()
        return had

    def slots(self) -> list[tuple[int, Any]]:
        """The linked devices in the order they were linked, each with its
        slot (1 for the first)."""
        # (By the order they were added: never by a clock that may be off.)
        rows = sorted(self.db.linked_devices(), key=lambda r: r["id"])
        return list(enumerate(rows, 1))

    def slot_of(self, device_id: int | None) -> int | None:
        return next((n for n, row in self.slots() if row["id"] == device_id), None)


class LicenseText(BaseModel):
    license: str = Field(max_length=LICENSE_MOST)


def routes(app: FastAPI, ctx: AppContext) -> None:
    licensing = ctx.licensing

    def who(request: Request) -> str:
        user = access.signed_in(request)
        return user.name if user else "Someone"

    def status() -> dict[str, Any]:
        """What the page shows: the server's ID, the license, and the
        devices in their slots."""
        found = licensing.current()
        limit = found.device_limit if found else 0
        about = None
        if found:
            about = {
                "licenseId": found.license_id,
                "tier": found.tier,
                "deviceLimit": found.device_limit,
                "issuedAt": found.issued_at,
                "code": code_of(found.file),  # (for the Admin to keep a copy)
            }
        slots = [
            {
                "id": row["id"],
                "name": row["name"],
                "slot": n,
                "covered": n <= limit,
                "linkedMs": row["created_ms"],
                "seenMs": row["seen_ms"],
            }
            for n, row in licensing.slots()
        ]
        return {"serverId": licensing.server_id, "license": about, "devices": slots}

    def install(body: LicenseText, request: Request) -> dict[str, Any]:
        try:
            found = licensing.install(body.license)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        ctx.access.record(
            logging.INFO,
            f"{who(request)} installed a license for {found.device_limit} devices "
            f"(license {found.license_id})",
        )
        return status()

    def remove(request: Request) -> dict[str, Any]:
        if licensing.remove():
            ctx.access.record(logging.INFO, f"{who(request)} removed the license")
        return status()

    def device_of(request: Request) -> int | None:
        """The linked device a request came from: its sign-in's, or the one
        whose key it carries."""
        token = access.sign_in_of(request)
        signed = ctx.db.session_user(token, 0) if token else None
        if signed is not None and signed.device_id is not None:
            return signed.device_id
        found = ctx.devices.device(request.headers.get("stationplay-device"))
        return found.id if found else None

    @app.get("/api/internal/license")
    async def for_the_apps(request: Request) -> dict[str, Any]:
        """For StationPlay's apps: this server's ID, its license file (None:
        not licensed), and this device's slot (None: not a linked device),
        of how many linked. The apps check the license themselves."""
        found = licensing.current()
        slot = licensing.slot_of(device_of(request))
        return {
            "serverId": licensing.server_id,
            "license": found.file if found else None,
            "device": {"slot": slot, "linked": len(licensing.slots())} if slot else None,
        }

    @app.post("/api/internal/license")
    async def install_from_an_app(body: LicenseText, request: Request) -> dict[str, Any]:
        """For an Admin, in an app (after buying one, or restoring it)."""
        return install(body, request)

    @app.delete("/api/internal/license")
    async def remove_from_an_app(request: Request) -> dict[str, Any]:
        return remove(request)

    @app.get("/api/access/license")
    async def on_the_page() -> dict[str, Any]:
        return status()

    @app.put("/api/access/license")
    async def install_on_the_page(body: LicenseText, request: Request) -> dict[str, Any]:
        return install(body, request)

    @app.delete("/api/access/license")
    async def remove_on_the_page(request: Request) -> dict[str, Any]:
        return remove(request)
