"""Setup's tuner address from the internet (1.37.1, the owner, October 15:
"Setup missing actual personal IPs", the Tuner integration rows showing
http://<your NAS>:3310). From the internet tapiOca can't tell its home
address from the request, but Plex's Live TV & DVR has the address it
reaches tapiOca's tuner at: Setup shows that. Without one (tapiOca not in
Plex yet), it still says where your NAS's address goes."""

from __future__ import annotations

import asyncio
import contextlib
import socket

import httpx
import uvicorn

from app.main import create_app
from app.plex import PlexClient

from .helpers import PAGE
from .test_security import PAT, TUNNEL, plex, settings, through_tunnel


@contextlib.asynccontextmanager
async def serving(tmp_path):
    lan, public = (socket.create_server(("127.0.0.1", 0)) for _ in range(2))
    ports = lan.getsockname()[1], public.getsockname()[1]
    app = create_app(
        settings(tmp_path, port=ports[0], public_port=ports[1]),
        PlexClient("http://plex.test", "token", transport=plex().transport()),
    )
    app.state.ctx.trusted.save({"proxies": [{"network": TUNNEL}]}, by=None)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", proxy_headers=False))
    task = asyncio.create_task(server.serve(sockets=[lan, public]))
    while not server.started:
        await asyncio.sleep(0.02)
    try:
        yield app, *(f"http://127.0.0.1:{port}" for port in ports)
    finally:
        server.should_exit = True
        await task


def plex_has_the_tuner_at(app, uri: str) -> None:
    ctx = app.state.ctx

    async def dvrs():
        device = {"deviceIdentifier": ctx.device_id, "uri": uri, "status": "alive"}
        return [{"key": "16", "Device": [device]}]

    ctx.plex.dvrs = dvrs
    ctx.updater._dvr_checked_ms = 0


async def setup_from_the_internet(internet: str) -> tuple[str, str]:
    async with through_tunnel(internet, {"CF-Connecting-IP": "203.0.113.5"}) as visitor:
        assert (await visitor.post("/api/access/sign-in", json=PAT)).status_code == 200
        status = (await visitor.get("/api/status")).json()["tunerUrl"]
        checks = (await visitor.get("/api/setup/plex")).json()["tunerUrl"]
        return status, checks


async def test_from_the_internet_setup_has_the_address_plex_uses(tmp_path):
    async with serving(tmp_path) as (app, home, internet):
        async with httpx.AsyncClient(headers=PAGE, base_url=home) as inside:
            assert (await inside.post("/api/access/users", json=PAT)).status_code == 201
        plex_has_the_tuner_at(app, "http://192.168.50.2:3310/")
        await app.state.ctx.updater.find_dvr()
        assert await setup_from_the_internet(internet) == (
            "http://192.168.50.2:3310",
            "http://192.168.50.2:3310",
        )


async def test_an_address_that_isnt_one_is_never_shown(tmp_path):
    async with serving(tmp_path) as (app, home, internet):
        async with httpx.AsyncClient(headers=PAGE, base_url=home) as inside:
            assert (await inside.post("/api/access/users", json=PAT)).status_code == 201
        lan_port = home.rsplit(":", 1)[1]
        for uri in ("", "ftp://192.168.50.2", "http://", "http://user:pw@192.168.50.2:3310",
                    "http://192.168.50.2:3310/path?x=1", "javascript:alert(1)"):  # fmt: skip
            plex_has_the_tuner_at(app, uri)
            await app.state.ctx.updater.find_dvr()
            assert await setup_from_the_internet(internet) == (
                f"http://<your NAS>:{lan_port}",
                f"http://<your NAS>:{lan_port}",
            ), uri
