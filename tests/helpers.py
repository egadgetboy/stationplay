"""Shared test helpers."""

from __future__ import annotations

from typing import NamedTuple

import httpx

from app import __version__
from app.access import PAGE_FILES
from app.db import Item
from app.schedule import EraSchedule

from .fakeplex import FakePlex

# What tapiOca's page sends with each request (see access.PAGE_HEADER): the
# tests' clients send it as the page would (and so do tests' TestClients:
# see conftest.py).
PAGE = {"X-Tapioca-Page": "1"}


class LegacyChannel(NamedTuple):
    """A station as stored before eras: its schedule came from these."""

    id: int
    number: int
    name: str
    order_mode: str
    sources: list[dict]
    epoch_ms: int
    total_ms: int
    built_at_ms: int
    logo: str = ""


class Schedule(EraSchedule):
    """A single-era schedule for `channel`: how every station was scheduled
    before eras existed. The reference that stations upgraded from then
    must still match exactly."""

    def __init__(self, channel: LegacyChannel, items: list[Item]) -> None:
        super().__init__(
            items,
            epoch_ms=channel.epoch_ms,
            seed=f"{channel.id}:{channel.built_at_ms}",
            order_mode=channel.order_mode,
        )
        self.channel = channel


def like_plex(fp: FakePlex) -> httpx.MockTransport:
    """`fp`, answering as Plex does when asked for a program or show it
    doesn't have: "not found" (HTTP 404), rather than an empty list."""

    def handler(request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")
        if parts[:2] == ["library", "metadata"] and len(parts) in (3, 4):
            key, rest = parts[2], parts[3:]
            if rest == ["allLeaves"]:
                missing = key not in fp.shows
            else:
                missing = not rest and key not in fp.episodes
            if missing:
                fp.requests.append(request.url.path)
                return httpx.Response(404)
        return fp.handler(request)

    return httpx.MockTransport(handler)


# The tests' reverse proxy (1.36.0: only a trusted proxy an Admin listed is
# believed about who a request is for, or that it came over HTTPS).
PROXY_PEER = "192.168.1.2"


def list_proxy(app, address: str = PROXY_PEER) -> None:
    """Lists `address` as a trusted proxy, as an Admin would (keeping any
    others)."""
    trusted = app.state.ctx.trusted
    kept = trusted.proxies
    if not any(p["network"].split("/")[0] == address for p in kept):
        trusted.save({"proxies": [*kept, {"network": address, "label": "Proxy"}]}, by=None)


def through_proxy(app, **given):
    """A client of `app` through the tests' reverse proxy, listed as a
    trusted proxy."""
    from fastapi.testclient import TestClient

    list_proxy(app)
    return TestClient(app, client=(PROXY_PEER, 50000), **given)


class Proxy:
    """A reverse proxy in front of tapiOca (`app`), as tapiOca's check
    of its outside address meets one (see reach.py): it passes each request
    to `port`, saying it came over HTTPS (X-Forwarded-Proto) if `https`, and
    keeps tapiOca's answers. Its `transport` is what answers the check."""

    def __init__(self, app, port: int, https: bool = True) -> None:
        self.port, self.https = port, https
        self.answers: list[httpx.Response] = []
        list_proxy(app)
        stationplay = httpx.ASGITransport(app=app, client=(PROXY_PEER, 123))

        async def handler(request: httpx.Request) -> httpx.Response:
            url = request.url.copy_with(scheme="http", host="testserver", port=self.port)
            headers = {k: v for k, v in request.headers.items() if k != "host"}
            if self.https:
                headers["X-Forwarded-Proto"] = "https"
            got = await stationplay.handle_async_request(
                httpx.Request(request.method, url, headers=headers)
            )
            await got.aread()
            self.answers.append(got)
            return httpx.Response(got.status_code, headers=got.headers, content=got.content)

        self.transport = httpx.MockTransport(handler)


def add_again(fp: FakePlex, show_key: str, new_key: str) -> dict[str, str]:
    """Plex removing a show and adding it again (or matching it afresh): the
    same show, episodes and files under new rating keys. Returns {old
    episode key: new}."""
    episodes = [e for e in fp.episodes.values() if e.get("grandparentRatingKey") == show_key]
    title = fp.shows.pop(show_key)["title"]
    fp.add_show(new_key, title)
    moved = {}
    for e in episodes:
        old = fp.episodes.pop(e["ratingKey"])
        moved[old["ratingKey"]] = str(int(old["ratingKey"]) + 1000)
        part = old["Media"][0]["Part"][0]
        fp.add_episode(
            moved[old["ratingKey"]], new_key, old["parentIndex"], old["index"],
            old["title"], part["file"], old["duration"],
        )  # fmt: skip
    return moved


def page_code(client) -> str:
    """tapiOca's page as it's served, and each of its own files (its
    styles and scripts) as they're served: all of the page's code."""
    page = client.get("/").text
    files = [client.get(f"/web/{name}?v={__version__}") for name in PAGE_FILES]
    assert [f.status_code for f in files] == [200] * len(PAGE_FILES)
    return "\n".join([page, *(f.text for f in files)])
