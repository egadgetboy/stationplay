"""A stand-in for the Plex API, serving a library of local test files."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx

TAG_FIELDS = ("genre", "director", "actor", "collection", "label")
# Filters beyond those, as Plex has them. Content ratings are named, not
# numbered, in Plex's filter addresses.
EXTRA_FIELDS = ("contentRating", "network", "studio", "country", "writer")
NAMED_FIELDS = ("contentRating",)
ALL_FIELDS = TAG_FIELDS + EXTRA_FIELDS
TYPES = {"movie": 1, "show": 2, "episode": 4}
# What Plex says each kind of library can be filtered on (includeMeta).
FILTERS = {
    "movie": [
        ("genre", "Genre", "string"), ("year", "Year", "integer"), ("decade", "Decade", "integer"),
        ("director", "Director", "string"), ("actor", "Actor", "string"),
        ("writer", "Writer", "string"), ("contentRating", "Content Rating", "string"),
        ("studio", "Studio", "string"), ("country", "Country", "string"),
        ("collection", "Collection", "string"), ("label", "Label", "string"),
        ("unwatched", "Unplayed", "boolean"),
    ],
    "show": [
        ("genre", "Genre", "string"), ("year", "Year", "integer"),
        ("network", "Network", "string"), ("contentRating", "Content Rating", "string"),
        ("studio", "Studio", "string"), ("country", "Country", "string"),
        ("collection", "Collection", "string"), ("label", "Label", "string"),
        ("actor", "Actor", "string"), ("unwatched", "Unplayed", "boolean"),
    ],
}  # fmt: skip
# When things were added to Plex, unless a test says otherwise.
LONG_AGO = 1_600_000_000


class FakePlex:
    def __init__(self) -> None:
        self.sections: dict[str, dict] = {"1": {"title": "TV Shows", "type": "show"}}
        self.shows: dict[str, dict] = {}
        self.episodes: dict[str, dict] = {}  # episodes and movies
        self.down = False
        self.requests: list[str] = []
        self.posts: list[str] = []
        self.changed = 1  # bumped whenever the library changes
        self.dvr_device: str | None = None  # device id of a DVR set up in Plex
        self.markers: dict[str, list[dict]] = {}  # by rating key, as Plex sends them
        self.marker_requests = 0
        self.meta = True  # False: an older Plex that doesn't describe its filters
        self._tag_ids: dict[tuple[str, str], int] = {}
        # Collections by rating key: {"title", "section", "children", "updatedAt"}.
        self.collections: dict[str, dict] = {}
        self.collections_down = False  # listing a library's collections fails
        # A newer Plex: collections listed with /all?type=18, their contents
        # at /items (rather than /collections and /children).
        self.newer_collections = False
        self.no_poster: set[str] = set()  # shows and movies without one

    # Building the library --------------------------------------------------

    def add_section(self, key: str, title: str, kind: str, locations: tuple = ()) -> None:
        self.sections[key] = {"title": title, "type": kind}
        self.set_locations(key, *locations)
        self.changed += 1

    def set_locations(self, key: str, *paths: str) -> None:
        """The library's folders, as Plex has them."""
        self.sections[key]["Location"] = [{"id": n, "path": p} for n, p in enumerate(paths, 1)]

    def _tags(self, field: str, titles) -> list[dict]:
        out = []
        for title in titles or ():
            if field in NAMED_FIELDS:
                tag_id: int | str = title
            else:
                tag_id = self._tag_ids.setdefault((field, title), len(self._tag_ids) + 100)
            out.append({"id": tag_id, "tag": title})
        return out

    def _set_tags(self, entry: dict, tags: dict) -> None:
        """Tags as genres=[...] (the older tests' way) or contentRating=[...]."""
        for field in ALL_FIELDS:
            entry["_" + field] = self._tags(field, tags.get(field + "s") or tags.get(field))
            # As Plex lists them: a plain value, or a list of tags.
            if field in NAMED_FIELDS and entry["_" + field]:
                entry[field] = entry["_" + field][0]["tag"]
            elif field in TAG_FIELDS and entry["_" + field]:
                entry[field.capitalize()] = [{"tag": t["tag"]} for t in entry["_" + field]]

    def add_show(
        self,
        key: str,
        title: str,
        year: int | None = None,
        section: str = "1",
        audience_rating: float | None = None,
        **tags,
    ) -> None:
        show = {"ratingKey": key, "type": "show", "title": title, "leafCount": 0, "year": year}
        show["thumb"] = f"/library/metadata/{key}/thumb/1"
        show["_section"] = section
        if audience_rating is not None:
            show["audienceRating"] = audience_rating
        self._set_tags(show, tags)
        self.shows[key] = show
        self.changed += 1

    def add_episode(
        self,
        key: str,
        show_key: str,
        season: int,
        episode: int,
        title: str,
        path: str,
        duration_ms: int,
        size: int = 1000,
        added_at: int = LONG_AGO,
    ) -> None:
        show = self.shows[show_key]
        show["leafCount"] += 1
        self.episodes[key] = {
            "ratingKey": key,
            "type": "episode",
            "title": title,
            "grandparentTitle": show["title"],
            "grandparentRatingKey": show_key,
            "parentIndex": season,
            "index": episode,
            "duration": duration_ms,
            "summary": f"{title} summary",
            "addedAt": added_at,
            "_section": show["_section"],
            "Media": [
                {
                    "duration": duration_ms,
                    "Part": [
                        {
                            "id": int(key),
                            "key": f"/library/parts/{key}/1/file.mkv",
                            "file": path,
                            "size": size,
                            "duration": duration_ms,
                        }
                    ],
                }
            ],
        }
        self.changed += 1

    def set_markers(self, key: str, *markers: tuple) -> None:
        """Markers for a program: ("intro", start_ms, end_ms) or
        ("credits", start_ms, end_ms, final)."""
        out = []
        for n, m in enumerate(markers):
            entry = {"id": n + 1, "type": m[0], "startTimeOffset": m[1], "endTimeOffset": m[2]}
            if len(m) > 3 and m[3]:
                entry["final"] = True
            out.append(entry)
        self.markers[key] = out

    def remove(self, key: str) -> None:
        item = self.episodes.pop(key)
        if item["type"] == "episode":
            self.shows[item["grandparentRatingKey"]]["leafCount"] -= 1
        self.changed += 1

    def add_movie(
        self,
        key: str,
        title: str,
        path: str,
        duration_ms: int,
        year: int = 2000,
        section: str = "1",
        added_at: int = LONG_AGO,
        audience_rating: float | None = None,
        **tags,
    ) -> None:
        movie = {
            "ratingKey": key,
            "type": "movie",
            "title": title,
            "thumb": f"/library/metadata/{key}/thumb/1",
            "year": year,
            "duration": duration_ms,
            "summary": f"{title} summary",
            "addedAt": added_at,
            "_section": section,
            "Media": [
                {
                    "duration": duration_ms,
                    "Part": [
                        {
                            "id": int(key),
                            "key": f"/library/parts/{key}/1/file.mkv",
                            "file": path,
                            "size": 1000,
                            "duration": duration_ms,
                        }
                    ],
                }
            ],
        }
        if audience_rating is not None:
            movie["audienceRating"] = audience_rating
        self._set_tags(movie, tags)
        self.episodes[key] = movie
        self.changed += 1

    def add_collection(self, key: str, title: str, section: str, *children: str) -> None:
        """A collection of shows or movies (by rating key). Like Plex, what's
        in a collection changing doesn't change its library's timestamps."""
        self.collections[key] = {
            "title": title, "section": section, "children": list(children), "updatedAt": 1,
        }  # fmt: skip

    def collect(self, key: str, *children: str) -> None:
        """Adds shows or movies to a collection."""
        self.collections[key]["children"] += children
        self.collections[key]["updatedAt"] += 1

    # Serving it --------------------------------------------------------------

    @staticmethod
    def _public(entry: dict) -> dict:
        return {k: v for k, v in entry.items() if not k.startswith("_")}

    def _entries(self, section: str, type_num: int) -> list[dict]:
        if type_num == TYPES["show"]:
            pool = list(self.shows.values())
        else:
            kind = "episode" if type_num == TYPES["episode"] else "movie"
            pool = [e for e in self.episodes.values() if e["type"] == kind]
        return [e for e in pool if e.get("_section") == section]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        if self.down:
            raise httpx.ConnectError("Plex is down", request=request)
        if request.headers.get("X-Plex-Token") != "token":
            return httpx.Response(401)

        def ok(container: dict) -> httpx.Response:
            return httpx.Response(200, content=json.dumps({"MediaContainer": container}))

        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        if request.method == "POST":
            self.posts.append(path)
            if path.startswith("/livetv/dvrs/") and path.endswith("/reloadGuide"):
                return httpx.Response(200)
            return httpx.Response(404)
        if path == "/photo/:/transcode":
            # Plex making a picture small: here, a stand-in.
            thumb = params.get("url", "").split("/")
            key = thumb[3] if len(thumb) > 4 and thumb[1:3] == ["library", "metadata"] else ""
            known = key in self.shows or key in self.episodes
            if not known or key in self.no_poster or "width" not in params:
                return httpx.Response(404)
            return httpx.Response(
                200, content=f"poster {key}".encode(), headers={"content-type": "image/jpeg"}
            )
        if path == "/identity":
            return ok({"machineIdentifier": "fake", "version": "1.41.0"})
        if path == "/livetv/dvrs":
            if not self.dvr_device:
                return ok({"size": 0})
            return ok(
                {
                    "Dvr": [
                        {
                            "key": "16",
                            "lineup": "lineup://tv.plex.providers.epg.xmltv/x",
                            "Device": [{"deviceIdentifier": self.dvr_device, "uri": "http://x"}],
                        }
                    ]
                }
            )
        if path == "/library/sections":
            return ok(
                {
                    "Directory": [
                        {"key": k, **s, "updatedAt": self.changed, "scannedAt": 1}
                        for k, s in self.sections.items()
                    ]
                }
            )
        parts = path.strip("/").split("/")
        listing = parts[3:] == (["all"] if self.newer_collections else ["collections"])
        if (
            parts[:2] == ["library", "sections"]
            and listing
            and (not self.newer_collections or params.get("type") == "18")
        ):
            if self.collections_down:
                return httpx.Response(500)
            kind = self.sections.get(parts[2], {}).get("type", "show")
            return ok(
                {
                    "Metadata": [
                        {"ratingKey": k, "type": "collection", "title": c["title"],
                         "subtype": kind, "childCount": len(c["children"]),
                         "updatedAt": c["updatedAt"]}
                        for k, c in self.collections.items()
                        if c["section"] == parts[2]
                    ]
                }
            )  # fmt: skip
        contents = ["items"] if self.newer_collections else ["children"]
        if parts[:2] == ["library", "collections"] and parts[3:] == contents:
            collection = self.collections.get(parts[2])
            if collection is None:
                return httpx.Response(404)
            everything = {**self.shows, **self.episodes}
            return ok(
                {
                    "Metadata": [
                        self._public(everything[k])
                        for k in collection["children"]
                        if k in everything
                    ]
                }
            )
        if parts[:2] == ["library", "sections"] and len(parts) == 4:
            section, what = parts[2], parts[3]
            kind = self.sections.get(section, {}).get("type", "show")
            if what == "all":
                default = TYPES["show"] if kind == "show" else TYPES["movie"]
                type_num = int(params.get("type", default))
                if params.get("includeMeta") == "1":
                    if not self.meta:
                        return ok({"size": 0})
                    kind_name = "show" if type_num == TYPES["show"] else "movie"
                    filters = [
                        {"filter": f, "title": t, "filterType": ft, "type": "filter",
                         "key": f"/library/sections/{section}/{f}"}
                        for f, t, ft in FILTERS[kind_name]
                    ]  # fmt: skip
                    return ok(
                        {"size": 0, "Meta": {"Type": [{"type": kind_name, "Filter": filters}]}}
                    )
                entries = self._entries(section, type_num)
                for field in ALL_FIELDS:
                    if field in params:
                        wanted = {v for v in params[field].split(",")}
                        entries = [
                            e
                            for e in entries
                            if wanted & {str(t["id"]) for t in e.get("_" + field, [])}
                        ]
                if params.get("sort") == "addedAt:desc":
                    entries = sorted(entries, key=lambda e: -e.get("addedAt", 0))
                start = int(params.get("X-Plex-Container-Start", 0))
                size = int(params.get("X-Plex-Container-Size", len(entries) or 1))
                page = entries[start : start + size]
                return ok({"totalSize": len(entries), "Metadata": [self._public(e) for e in page]})
            type_num = int(params.get("type", 2 if kind == "show" else 1))
            entries = self._entries(section, type_num)
            if what == "decade":
                decades = sorted({e["year"] // 10 * 10 for e in entries if e.get("year")})
                return ok({"Directory": [{"key": str(d), "title": f"{d}s"} for d in decades]})
            if what in ALL_FIELDS:
                tags = {t["id"]: t["tag"] for e in entries for t in e.get("_" + what, [])}
                return ok(
                    {
                        "Directory": [
                            {
                                "key": str(i),
                                "title": title,
                                "fastKey": f"/library/sections/{section}/all?{what}={i}",
                            }
                            for i, title in sorted(tags.items(), key=lambda kv: str(kv[0]))
                        ]
                    }
                )
            return httpx.Response(404)
        if parts[:2] == ["library", "metadata"] and len(parts) >= 3:
            key = parts[2]
            if len(parts) == 4 and parts[3] == "allLeaves":
                eps = [
                    self._public(e)
                    for e in self.episodes.values()
                    if e.get("grandparentRatingKey") == key
                ]
                return ok({"Metadata": eps})
            if len(parts) >= 4 and parts[3] == "thumb":
                if key in self.no_poster:
                    return httpx.Response(404)
                return httpx.Response(
                    200, content=b"\x89PNG fake", headers={"content-type": "image/png"}
                )
            if key in self.episodes:
                entry = self._public(self.episodes[key])
                # Like Plex: markers only for one program at a time, when asked.
                if params.get("includeMarkers") == "1":
                    self.marker_requests += 1
                    if self.markers.get(key):
                        entry["Marker"] = self.markers[key]
                return ok({"Metadata": [entry]})
            return ok({"Metadata": []})
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
