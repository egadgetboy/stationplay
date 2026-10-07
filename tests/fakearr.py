"""A stand-in for Sonarr or Radarr, answering as their own code does (API
v3, checked against Sonarr 4 and Radarr 5): only what StationPlay asks of
them (see app/arr.py), with what's done to it kept to look at afterwards.

  * A search grabs the first release for the episode or movie that isn't
    blocklisted, unless it has a file (the quality it wants is met): the
    release goes in the queue; finish() imports it.
  * Marking a history record failed blocklists the release its download
    came from (found by the download's id, as Sonarr does; the record
    itself if it's a grab), and, if set to (as by default), searches
    again; one with no download behind it is refused (HTTP 500).
  * Deleting a file goes to the recycle bin; a rescan finds files gone
    from disk (gone()).
"""

from __future__ import annotations

import itertools
import json
from urllib.parse import parse_qs

import httpx

SONARR, RADARR = "sonarr", "radarr"


class FakeArr:
    def __init__(self, app: str, key: str = "abc123def456", version: str = "4.0.15.2941"):
        self.app = app
        self.key = key
        self.version = version
        self.down = False
        self.redownload = True  # (Failed Download Handling: Redownload)
        self.shows: dict[int, dict] = {}
        self.episodes: dict[int, dict] = {}
        self.movies: dict[int, dict] = {}
        self.files: dict[int, dict] = {}
        self.history: list[dict] = []
        self.queue: list[dict] = []
        self.blocklist: list[str] = []
        self.recycled: list[str] = []
        self.releases: dict[int, list[str]] = {}  # what a search finds, by episode or movie
        self.commands: list[dict] = []
        self.calls: list[str] = []  # "METHOD path", in order
        self.missing_on_disk: set[int] = set()  # files a rescan finds gone
        self._ids = itertools.count(100)
        self._dl = itertools.count(1)

    # Setting it up -------------------------------------------------------------------

    def add_show(self, sid: int, title: str, tvdb: int, year: int = 1959) -> None:
        self.shows[sid] = {"id": sid, "title": title, "year": year, "tvdbId": tvdb,
                           "path": f"/tv/{title}", "monitored": True}  # fmt: skip

    def add_episode(self, eid: int, sid: int, season: int, episode: int, title: str) -> None:
        self.episodes[eid] = {"id": eid, "seriesId": sid, "seasonNumber": season,
                              "episodeNumber": episode, "title": title, "hasFile": False,
                              "episodeFileId": 0, "monitored": True}  # fmt: skip

    def add_movie(self, mid: int, title: str, year: int, tmdb: int, imdb: str = "") -> None:
        self.movies[mid] = {"id": mid, "title": title, "year": year, "tmdbId": tmdb,
                            "imdbId": imdb, "path": f"/movies/{title} ({year})",
                            "hasFile": False, "movieFileId": 0, "monitored": True}  # fmt: skip

    def give_file(self, item: int, name: str, size: int, downloaded: str | None = None) -> int:
        """A file for an episode or movie: `downloaded` (a release's name) if
        the app downloaded it (its grab and import in History), else added
        by hand (none)."""
        fid = next(self._ids)
        folder = self._folder(item)
        self.files[fid] = {"id": fid, "relativePath": name, "path": f"{folder}/{name}",
                           "size": size, self._own: item}  # fmt: skip
        self._has(item, fid)
        if downloaded:
            dl = f"DL{next(self._dl)}"
            self._event(item, "grabbed", downloaded, dl, {})
            self._event(item, "downloadFolderImported", downloaded, dl,
                        {"fileId": str(fid), "importedPath": f"{folder}/{name}"})  # fmt: skip
        return fid

    def finish(self, item: int, name: str, size: int) -> int:
        """The download in the queue for it, done and imported."""
        queued = next(q for q in self.queue if q[self._own] == item)
        self.queue.remove(queued)
        fid = next(self._ids)
        folder = self._folder(item)
        self.files[fid] = {"id": fid, "relativePath": name, "path": f"{folder}/{name}",
                           "size": size, self._own: item}  # fmt: skip
        self._has(item, fid)
        self._event(item, "downloadFolderImported", queued["title"], queued["downloadId"],
                    {"fileId": str(fid), "importedPath": f"{folder}/{name}"})  # fmt: skip
        return fid

    def gone(self, file_id: int) -> None:
        """A file that's gone from disk (the app learns at its next rescan)."""
        self.missing_on_disk.add(file_id)

    # Inside --------------------------------------------------------------------------------

    @property
    def _own(self) -> str:
        return "episodeId" if self.app == SONARR else "movieId"

    def _folder(self, item: int) -> str:
        if self.app == SONARR:
            return self.shows[self.episodes[item]["seriesId"]]["path"]
        return self.movies[item]["path"]

    def _has(self, item: int, fid: int | None) -> None:
        target = self.episodes[item] if self.app == SONARR else self.movies[item]
        key = "episodeFileId" if self.app == SONARR else "movieFileId"
        target["hasFile"] = fid is not None
        target[key] = fid or 0

    def _event(self, item: int, kind: str, title: str, dl: str | None, data: dict) -> None:
        self.history.append({"id": next(self._ids), self._own: item, "eventType": kind,
                             "sourceTitle": title, "downloadId": dl, "data": data,
                             "date": f"2026-10-05T00:{len(self.history):02d}:00Z"})  # fmt: skip

    def _search(self, item: int) -> None:
        target = self.episodes[item] if self.app == SONARR else self.movies[item]
        if target["hasFile"]:
            return  # (what's there will do: no grab)
        fresh = [r for r in self.releases.get(item, []) if r not in self.blocklist]
        if not fresh or any(q[self._own] == item for q in self.queue):
            return
        dl = f"DL{next(self._dl)}"
        self._event(item, "grabbed", fresh[0], dl, {})
        self.queue.append({self._own: item, "title": fresh[0], "downloadId": dl,
                           "status": "downloading", "trackedDownloadState": "downloading"})  # fmt: skip

    def _item_view(self, item: dict) -> dict:
        if self.app == RADARR and item["hasFile"]:
            return {**item, "movieFile": dict(self.files[item["movieFileId"]])}
        return dict(item)

    # Answering --------------------------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        if request.headers.get("X-Api-Key") != self.key:
            return httpx.Response(401)
        path = request.url.path.removeprefix("/api/v3/")
        method = request.method
        self.calls.append(f"{method} {path}")
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        parts = path.split("/")

        def ok(body, status: int = 200) -> httpx.Response:
            return httpx.Response(status, content=json.dumps(body))

        if path == "system/status":
            return ok({"appName": "Sonarr" if self.app == SONARR else "Radarr",
                       "version": self.version})  # fmt: skip
        if self.app == SONARR:
            if path == "series":
                shows = list(self.shows.values())
                if "tvdbId" in params:
                    shows = [s for s in shows if str(s["tvdbId"]) == params["tvdbId"]]
                return ok(shows)
            if parts[0] == "series" and len(parts) == 2:
                show = self.shows.get(int(parts[1]))
                return ok(dict(show)) if show else httpx.Response(404)
            if path == "episode" and method == "GET":
                sid = int(params["seriesId"])
                return ok([dict(e) for e in self.episodes.values() if e["seriesId"] == sid])
            if parts[0] == "episode" and len(parts) == 2:
                e = self.episodes.get(int(parts[1]))
                return ok(dict(e)) if e else httpx.Response(404)
            if parts[0] == "episodefile" and len(parts) == 2:
                return self._file(method, int(parts[1]))
            if path == "history":
                eid = int(params["episodeId"])
                found = [h for h in self.history if h.get("episodeId") == eid]
                found.sort(key=lambda h: h["date"], reverse=True)
                return ok({"page": 1, "pageSize": int(params.get("pageSize", 10)),
                           "totalRecords": len(found), "records": found})  # fmt: skip
            if path == "queue/details":
                eid = int(params["episodeIds"])
                return ok([q for q in self.queue if q["episodeId"] == eid])
        else:
            if path == "movie":
                movies = [self._item_view(m) for m in self.movies.values()]
                if "tmdbId" in params:
                    movies = [m for m in movies if str(m["tmdbId"]) == params["tmdbId"]]
                return ok(movies)
            if parts[0] == "movie" and len(parts) == 2:
                m = self.movies.get(int(parts[1]))
                return ok(self._item_view(m)) if m else httpx.Response(404)
            if parts[0] == "moviefile" and len(parts) == 2:
                return self._file(method, int(parts[1]))
            if path == "history/movie":
                mid = int(params["movieId"])
                return ok([h for h in self.history if h.get("movieId") == mid])
            if path == "queue/details":
                mid = int(params["movieId"])
                return ok([q for q in self.queue if q["movieId"] == mid])
        if parts[:2] == ["history", "failed"] and method == "POST":
            return self._mark_failed(int(parts[2]))
        if path == "command" and method == "POST":
            body = json.loads(request.content)
            command = {"id": next(self._ids), "name": body["name"], "body": body}
            self.commands.append(command)
            self._run(body)
            return ok({"id": command["id"], "name": body["name"], "status": "queued"}, 201)
        if parts[0] == "command" and len(parts) == 2:
            return ok({"id": int(parts[1]), "status": "completed"})
        return httpx.Response(404)

    def _file(self, method: str, fid: int) -> httpx.Response:
        f = self.files.get(fid)
        if f is None:
            return httpx.Response(404)
        if method == "DELETE":
            del self.files[fid]
            self.recycled.append(f["path"])
            self._has(f[self._own], None)
            return httpx.Response(200)
        return httpx.Response(200, content=json.dumps(f))

    def _mark_failed(self, history_id: int) -> httpx.Response:
        record = next((h for h in self.history if h["id"] == history_id), None)
        if record is None:
            return httpx.Response(404)
        if self.app == RADARR:
            grabs = [record]  # (Radarr blocklists what's on the record it's given)
        elif record["downloadId"]:
            grabs = [h for h in self.history if h["eventType"] == "grabbed"
                     and h["downloadId"] == record["downloadId"]]  # fmt: skip
        else:
            grabs = [record] if record["eventType"] == "grabbed" else []
        if not grabs:
            return httpx.Response(500)  # ("no grabbed history available")
        self.blocklist.append(grabs[0]["sourceTitle"])
        self._event(record[self._own], "downloadFailed", grabs[0]["sourceTitle"],
                    record["downloadId"], {})  # fmt: skip
        if self.redownload:
            self._search(record[self._own])
        return httpx.Response(200, content=b"{}")

    def _run(self, body: dict) -> None:
        name = body["name"]
        if name in ("EpisodeSearch", "MoviesSearch"):
            for item in body.get("episodeIds") or body.get("movieIds") or []:
                self._search(int(item))
        elif name in ("RescanSeries", "RescanMovie"):
            for fid in list(self.missing_on_disk):
                f = self.files.pop(fid, None)
                if f is not None:
                    self._has(f[self._own], None)
            self.missing_on_disk.clear()

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def both(sonarr: FakeArr, radarr: FakeArr) -> httpx.MockTransport:
    """One transport for both, by host (sonarr.test and radarr.test)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return (sonarr if request.url.host.startswith("sonarr") else radarr).handler(request)

    return httpx.MockTransport(handler)
