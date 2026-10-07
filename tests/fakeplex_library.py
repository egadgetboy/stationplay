"""A stand-in for more of the Plex API: what browsing and playing your
library in StationPlay's apps asks (see ondemand.py). Built on FakePlex,
which it leaves as it is."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx

from .fakeplex import TYPES, FakePlex


class LibraryPlex(FakePlex):
    def __init__(self) -> None:
        super().__init__()
        # What each program's file holds, as Plex describes it (Media[0]
        # fields, and its Part's Streams), by rating key.
        self.media: dict[str, dict] = {}
        self.streams: dict[str, list[dict]] = {}
        self.files: dict[str, bytes] = {}  # file contents served from Plex, by rating key
        self.subtitle_files: dict[str, bytes] = {}  # external subtitles, by stream id
        self.released: dict[str, str] = {}  # originallyAvailableAt, by rating key
        self.versions: dict[str, list[tuple[dict, list[dict]]]] = {}  # more versions, by rating key

    def describe(
        self,
        key: str,
        container: str = "mkv",
        video: str = "h264",
        width: int = 1920,
        height: int = 1080,
        audio: str = "aac",
        **extra,
    ) -> None:
        """What a program's file holds: its container, picture and sound
        (extra: more of the video stream's fields, such as colorTrc)."""
        self.media[key] = {"id": int(key) * 100, "container": container, "videoCodec": video,
                           "bitrate": 8000}  # fmt: skip
        self.streams[key] = [
            {"id": int(key) * 10 + 1, "streamType": 1, "codec": video, "width": width,
             "height": height, "bitDepth": extra.pop("bitDepth", 8), "index": 0, **extra},
            {"id": int(key) * 10 + 2, "streamType": 2, "codec": audio, "channels": 6,
             "language": "English", "default": True, "index": 1},
        ]  # fmt: skip

    def add_version(
        self, key: str, width: int, height: int, video: str = "h264", bitrate: int = 4000, **extra
    ) -> None:
        """Another version of a described program's file (Plex lists each in
        its Media), its sound as the first's."""
        n = len(self.versions.setdefault(key, [])) + 1
        media = {"id": int(key) * 100 + n, "container": "mkv", "videoCodec": video,
                 "bitrate": bitrate, "duration": extra.pop("duration", None)}  # fmt: skip
        streams = [
            {"id": int(key) * 1000 + n * 10 + 1, "streamType": 1, "codec": video, "width": width,
             "height": height, "bitDepth": extra.pop("bitDepth", 8), "index": 0, **extra},
            *[t for t in self.streams[key] if t["streamType"] == 2],
        ]  # fmt: skip
        self.versions[key].append((media, streams))

    def add_subtitles(self, key: str, codec: str, language: str, external: bytes | None = None):
        stream = {
            "id": int(key) * 10 + 3 + len(self.streams[key]),
            "streamType": 3,
            "codec": codec,
            "language": language,
        }
        if external is None:
            stream["index"] = len(self.streams[key])
        else:
            stream["key"] = f"/library/streams/{stream['id']}"
            self.subtitle_files[str(stream["id"])] = external
        self.streams[key].append(stream)

    # Serving it --------------------------------------------------------------

    def _section_of(self, entry: dict) -> str:
        return str(entry.get("_section") or "")

    def _full(self, key: str) -> dict | None:
        """An entry as Plex describes one asked about alone."""
        if key in self.shows:
            show = self._public(self.shows[key])
            seasons = {e["parentIndex"] for e in self.episodes.values()
                       if e.get("grandparentRatingKey") == key}  # fmt: skip
            return {**show, "librarySectionID": int(self.shows[key]["_section"]),
                    "childCount": len(seasons), "summary": f"{show['title']} summary",
                    "art": f"/library/metadata/{key}/art/1"}  # fmt: skip
        if key not in self.episodes:
            return None
        raw = self.episodes[key]
        entry = self._public(raw)
        entry["librarySectionID"] = int(self._section_of(raw) or 0)
        entry["thumb"] = f"/library/metadata/{key}/thumb/1"
        if key in self.released:
            entry["originallyAvailableAt"] = self.released[key]
        if key in self.media:
            media = entry["Media"][0]
            entry["Media"] = [{**media, **self.media[key],
                               "Part": [{**media["Part"][0], "container": self.media[key]["container"],
                                         "Stream": self.streams[key]}]}]  # fmt: skip
            for n, (more, streams) in enumerate(self.versions.get(key, []), 1):
                part = {**media["Part"][0], "key": f"/library/parts/{key}/{n + 1}/file.mkv",
                        "file": f"{media['Part'][0]['file']}.v{n + 1}", "container": "mkv",
                        "Stream": streams}  # fmt: skip
                if more["duration"]:
                    part["duration"] = more["duration"]
                entry["Media"].append({**media, **{k: v for k, v in more.items() if v is not None},
                                       "Part": [part]})  # fmt: skip
        return entry

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        # (Files and subtitles are fetched with the token in the address,
        # as Plex's stream addresses have it.)
        if path.startswith(("/library/parts/", "/library/streams/")):
            self.requests.append(path)
            if params.get("X-Plex-Token") != "token" or self.down:
                return httpx.Response(401)
            if path.startswith("/library/streams/"):
                found = self.subtitle_files.get(path.rsplit("/", 1)[1])
                return httpx.Response(200, content=found) if found else httpx.Response(404)
            data = self.files.get(path.split("/")[3])
            if data is None:
                return httpx.Response(404)
            return _ranged(data, request.headers.get("range"))
        if self.down or request.headers.get("X-Plex-Token") != "token":
            return super().handler(request)
        parts = path.strip("/").split("/")
        if parts[:2] == ["library", "metadata"] and len(parts) == 3:
            self.requests.append(path)
            found = [e for k in parts[2].split(",") if (e := self._full(k)) is not None]
            if "," not in parts[2] and found and "includeMarkers" in params:
                found[0]["Marker"] = self.markers.get(parts[2], [])
            return _ok({"Metadata": found})
        if parts[:2] == ["library", "metadata"] and parts[3:] == ["allLeaves"]:
            answer = super().handler(request)
            body = json.loads(answer.content)
            show = self.shows.get(parts[2])
            body["MediaContainer"]["librarySectionID"] = int(show["_section"]) if show else 0
            for e in body["MediaContainer"].get("Metadata", []):
                e["thumb"] = f"/library/metadata/{e['ratingKey']}/thumb/1"
            return httpx.Response(200, content=json.dumps(body))
        if (
            parts[:2] == ["library", "sections"]
            and parts[3:] == ["all"]
            and (
                "title" in params
                or params.get("sort") in ("titleSort", "originallyAvailableAt:desc")
            )
        ):
            self.requests.append(path)
            kind = self.sections.get(parts[2], {}).get("type", "show")
            type_num = int(params.get("type", TYPES["show"] if kind == "show" else TYPES["movie"]))
            entries = self._entries(parts[2], type_num)
            words = params.get("title", "").casefold()
            entries = [e for e in entries if words in e["title"].casefold()]
            if params.get("sort") == "titleSort":
                entries.sort(key=lambda e: e["title"].casefold())
            else:
                entries.sort(key=lambda e: self.released.get(e["ratingKey"], ""), reverse=True)
            start = int(params.get("X-Plex-Container-Start", 0))
            size = int(params.get("X-Plex-Container-Size", len(entries) or 1))
            return _ok({"totalSize": len(entries), "librarySectionID": int(parts[2]),
                        "Metadata": [self._public(e) for e in entries[start : start + size]]})  # fmt: skip
        if parts[:2] == ["library", "metadata"] and parts[3:4] == ["art"]:
            return httpx.Response(
                200, content=b"\x89PNG art", headers={"content-type": "image/png"}
            )
        return super().handler(request)


def _ok(container: dict) -> httpx.Response:
    return httpx.Response(200, content=json.dumps({"MediaContainer": container}))


def _ranged(data: bytes, asked: str | None) -> httpx.Response:
    """A file, or the part of it asked for (bytes=a-b, as players ask)."""
    headers = {"content-type": "application/octet-stream", "accept-ranges": "bytes"}
    if not asked:
        return httpx.Response(200, content=data, headers=headers)
    first, _, last = asked.removeprefix("bytes=").partition("-")
    start = int(first)
    end = min(int(last) if last else len(data) - 1, len(data) - 1)
    if start >= len(data):
        return httpx.Response(416, headers={"content-range": f"bytes */{len(data)}"})
    headers["content-range"] = f"bytes {start}-{end}/{len(data)}"
    return httpx.Response(206, content=data[start : end + 1], headers=headers)
