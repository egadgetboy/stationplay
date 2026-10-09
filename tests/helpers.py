"""Shared test helpers."""

from __future__ import annotations

from typing import NamedTuple

import httpx

from app.db import Item
from app.schedule import EraSchedule

from .fakeplex import FakePlex


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


class Proxy:
    """A reverse proxy in front of StationPlay (`app`), as StationPlay's check
    of its outside address meets one (see reach.py): it passes each request
    to `port`, saying it came over HTTPS (X-Forwarded-Proto) if `https`, and
    keeps StationPlay's answers. Its `transport` is what answers the check."""

    def __init__(self, app, port: int, https: bool = True) -> None:
        self.port, self.https = port, https
        self.answers: list[httpx.Response] = []
        stationplay = httpx.ASGITransport(app=app)

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
