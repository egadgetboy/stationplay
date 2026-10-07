"""Sonarr and Radarr, to replace broken files (optional: see replacing.py).

Only what was checked against their own code (Sonarr 4 and Radarr 5; both
answer the same way since Sonarr 3 and Radarr 3), through their API v3,
with the API key in the X-Api-Key header:

  GET    system/status                       what it is, and its version
  GET    series?tvdbId= / series / series/{id}  Sonarr's shows (monitored)
  GET    episode?seriesId= / episode/{id}    a show's episodes, or one (hasFile,
                                             episodeFileId, monitored)
  GET    episodefile/{id}                    an episode's file (relativePath, size)
  GET    movie?tmdbId= / movie / movie/{id}  Radarr's movies (hasFile, movieFile,
                                             monitored)
  GET    history?episodeId=&pageSize=        an episode's history, newest first
  GET    history/movie?movieId=              a movie's history
  POST   history/failed/{id}                 "Mark as Failed": its release is
                                             blocklisted (and searched for again,
                                             if the app is set to)
  DELETE episodefile/{id} / moviefile/{id}   the file, to the app's recycle bin
                                             if it has one
  POST   command {"name": "EpisodeSearch", "episodeIds": [..]}
                 {"name": "MoviesSearch", "movieIds": [..]}
                 {"name": "RescanSeries", "seriesId": ..} / {"name": "RescanMovie", "movieId": ..}
  GET    command/{id}                        how a command went
  GET    queue/details?episodeIds= / ?movieId=  what's downloading for it

A search asked for this way searches even for an episode or movie that
isn't monitored (it's a search a person asked for).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

SONARR, RADARR = "sonarr", "radarr"
APPS = (SONARR, RADARR)
NAMES = {SONARR: "Sonarr", RADARR: "Radarr"}
TIMEOUT_S = 30.0
# What Sonarr and Radarr call the history of an import from a download
# (it says which file it imported, and which download it came from) and of
# a release being grabbed.
IMPORTED, GRABBED = "downloadFolderImported", "grabbed"


class ArrError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status  # the HTTP status it answered with, if it answered


def clean_url(url: str) -> str:
    """An address as given (http or https, a host, maybe a port and a base
    path), without a trailing slash; ValueError if it isn't one."""
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("The address must start with http:// or https:// and include a host name")
    if parts.query or parts.fragment or parts.username:
        raise ValueError("The address can't contain a ?, a #, or a user name")
    return url


@dataclass
class Arr:
    """One Sonarr or Radarr."""

    app: str
    url: str
    key: str
    transport: httpx.AsyncBaseTransport | None = None

    @property
    def name(self) -> str:
        return NAMES[self.app]

    async def _call(
        self, method: str, path: str, params: dict | None = None, body: Any = None
    ) -> Any:
        """One call; ArrError if it can't be made or fails."""
        try:
            async with httpx.AsyncClient(
                base_url=f"{self.url}/api/v3/",
                headers={"X-Api-Key": self.key, "Accept": "application/json"},
                timeout=TIMEOUT_S,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                resp = await client.request(method, path, params=params, json=body)
        except httpx.HTTPError as e:
            raise ArrError(f"{self.name} can't be reached ({type(e).__name__})") from e
        if resp.status_code == 401:
            raise ArrError(f"{self.name} didn't accept the API key", 401)
        if resp.status_code >= 400:
            raise ArrError(
                f"{self.name} returned HTTP {resp.status_code} for {path}", resp.status_code
            )
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as e:
            raise ArrError(f"{self.name} sent an unexpected response. Check its address.") from e

    async def status(self) -> dict[str, Any]:
        """What it is and its version; ArrError if it isn't the app expected."""
        got = await self._call("GET", "system/status")
        if not isinstance(got, dict) or str(got.get("appName", "")).lower() != self.app:
            raise ArrError(f"That address doesn't point to {self.name}")
        return got

    # Sonarr ---------------------------------------------------------------------------

    async def series(self, tvdb: str | None = None) -> list[dict[str, Any]]:
        params = {"tvdbId": tvdb} if tvdb and tvdb.isdigit() else None
        return _listed(await self._call("GET", "series", params))

    async def show(self, series_id: int) -> dict[str, Any]:
        """One of Sonarr's shows (monitored or not)."""
        return _one(await self._call("GET", f"series/{int(series_id)}"))

    async def episodes(self, series_id: int) -> list[dict[str, Any]]:
        return _listed(await self._call("GET", "episode", {"seriesId": series_id}))

    async def episode(self, episode_id: int) -> dict[str, Any]:
        return _one(await self._call("GET", f"episode/{int(episode_id)}"))

    async def episode_file(self, file_id: int) -> dict[str, Any]:
        return _one(await self._call("GET", f"episodefile/{int(file_id)}"))

    async def episode_history(self, episode_id: int) -> list[dict[str, Any]]:
        got = await self._call(
            "GET",
            "history",
            {
                "episodeId": episode_id,
                "pageSize": 250,
                "sortKey": "date",
                "sortDirection": "descending",
            },
        )
        return _listed(got.get("records") if isinstance(got, dict) else None)

    # Radarr ---------------------------------------------------------------------------

    async def movies(self, tmdb: str | None = None) -> list[dict[str, Any]]:
        params = {"tmdbId": tmdb} if tmdb and tmdb.isdigit() else None
        return _listed(await self._call("GET", "movie", params))

    async def movie(self, movie_id: int) -> dict[str, Any]:
        return _one(await self._call("GET", f"movie/{int(movie_id)}"))

    async def movie_history(self, movie_id: int) -> list[dict[str, Any]]:
        return _listed(await self._call("GET", "history/movie", {"movieId": movie_id}))

    # Both ------------------------------------------------------------------------------

    async def history(self, item_id: int) -> list[dict[str, Any]]:
        """An episode's or a movie's history."""
        if self.app == SONARR:
            return await self.episode_history(item_id)
        return await self.movie_history(item_id)

    async def mark_failed(self, history_id: int) -> None:
        await self._call("POST", f"history/failed/{int(history_id)}")

    async def delete_file(self, file_id: int) -> None:
        kind = "episodefile" if self.app == SONARR else "moviefile"
        await self._call("DELETE", f"{kind}/{int(file_id)}")

    async def command(self, name: str, **fields: Any) -> int:
        """Starts one of its commands; its id."""
        got = _one(await self._call("POST", "command", body={"name": name, **fields}))
        if not isinstance(got.get("id"), int):
            raise ArrError(f"{self.name} didn't confirm it started {name}")
        return int(got["id"])

    async def command_status(self, command_id: int) -> str:
        """queued, started, completed, failed, aborted, cancelled or orphaned."""
        return str(_one(await self._call("GET", f"command/{int(command_id)}")).get("status", ""))

    async def search(self, item_id: int) -> int:
        if self.app == SONARR:
            return await self.command("EpisodeSearch", episodeIds=[item_id])
        return await self.command("MoviesSearch", movieIds=[item_id])

    async def rescan(self, parent_id: int) -> int:
        """Has it look at what's on disk for a show or movie."""
        if self.app == SONARR:
            return await self.command("RescanSeries", seriesId=parent_id)
        return await self.command("RescanMovie", movieId=parent_id)

    async def queue(self, item_id: int) -> list[dict[str, Any]]:
        """What's downloading for an episode or movie."""
        if self.app == SONARR:
            params: dict[str, Any] = {"episodeIds": item_id}
        else:
            params = {"movieId": item_id}
        return _listed(await self._call("GET", "queue/details", params))


def _listed(got: Any) -> list[dict[str, Any]]:
    return [x for x in got if isinstance(x, dict)] if isinstance(got, list) else []


def _one(got: Any) -> dict[str, Any]:
    return got if isinstance(got, dict) else {}
