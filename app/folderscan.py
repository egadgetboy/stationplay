"""Reading a folder library from disk (see folders.py): walking its
folders, reading each new or changed file, and what the folders' and files'
names, the NFO files and the tags inside the files say about each show,
episode and movie. Those are the first three layers of a folder library's
details, in this order (the first that has a detail wins):

  1. NFO files (see nfo.py);
  2. tags inside the files (from ffprobe: title, date, description, show,
     season and episode, genre);
  3. folder and file names (see naming.py).

The online sources come later (After 1.0), after these.

Walking skips hidden files and folders, a NAS's own folders, extras
folders and samples (named so, or under SAMPLE_BYTES beside a much bigger
file), and anything whose real path is outside the media folder (a
symbolic link out of it). Only videos are read, by their extension.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import ffmpeg as ff
from . import naming
from .folderart import BACKDROP_NAMES, BANNER_NAMES, LOGO_NAMES, POSTER_NAMES, TYPES

log = logging.getLogger(__name__)

# The layers inside tapiOca, in order.
NFO, TAGS, NAMES = "nfo", "tags", "names"
LOCAL_LAYERS = (NFO, TAGS, NAMES)

# A video under this size beside one MUCH_BIGGER times its size is a sample.
SAMPLE_BYTES = 50 << 20
# A video named a sample under this size is one (as Plex has it): a bigger
# one is a program with "sample" in its name ("Free Sample").
NAMED_SAMPLE_BYTES = 300 << 20
MUCH_BIGGER = 10
DEPTH_MOST = 12  # folders inside a library folder, at most
PROBE_S = 60.0  # reading one file, at most
# Details as long as this, at most.
TEXT_MOST = 4000
NAME_MOST = 200
LIST_MOST = 50


@dataclass
class Walked:
    """What one of a library's folders holds: its videos (path, size,
    modified), every folder's file names (by their casefolded names), and
    its NFO files' sizes and times (to read again only those that change).
    `reachable`: False if the folder can't be read at all (a share that
    isn't mounted); `empty`: it can be read, but holds nothing."""

    root: str
    reachable: bool = True
    empty: bool = False
    videos: list[tuple[str, int, int]] = field(default_factory=list)
    names: dict[str, dict[str, str]] = field(default_factory=dict)
    nfos: dict[str, str] = field(default_factory=dict)
    skipped: int = 0
    unreadable: list[str] = field(default_factory=list)  # (folders below the top)
    bad_names: list[str] = field(default_factory=list)  # (as shown: not UTF-8)


def inside_dir(path: str, media_dir: str) -> bool:
    """Whether a folder's real path (links followed) is the media folder or
    inside it."""
    try:
        real, root = os.path.realpath(path), os.path.realpath(media_dir)
    except (OSError, ValueError):
        return False
    return bool(root) and os.path.commonpath([real, root]) == root


def walk(root: str, media_dir: str) -> Walked:
    """Everything under one library folder that may matter (run in a
    thread: it reads the disk).

    Real folders are walked first, then folders linked from inside the
    media folder, each real folder once: a link back up, or to a folder
    already walked (another show's), adds nothing. A folder that can't be
    listed below the top is kept in `unreadable` (what was read from it
    before stays), and a name that isn't UTF-8 in `bad_names` (skipped)."""
    out = Walked(root)
    if not os.path.isdir(root) or not inside_dir(root, media_dir):
        out.reachable = False
        return out
    real_media = os.path.realpath(media_dir)

    def inside(path: str) -> bool:
        real = os.path.realpath(path)
        return os.path.commonpath([real, real_media]) == real_media

    walked: set[str] = set()  # (each folder's real path)
    linked: list[tuple[str, int]] = []  # (links to folders: walked after the rest)

    def look(folder: str, depth: int) -> None:
        real = os.path.realpath(folder)
        if real in walked:
            out.skipped += 1
            return
        walked.add(real)
        try:
            with os.scandir(folder) as found:
                entries = list(found)
        except OSError:
            if folder == root:
                out.reachable = False
            else:
                out.unreadable.append(folder)
            return
        if folder == root and not entries:
            out.empty = True
        out.names[folder] = {e.name.casefold(): e.name for e in entries if utf8(e.name)}
        for e in sorted(entries, key=lambda e: e.name):
            if e.name.startswith("."):
                continue
            if not utf8(e.name):
                out.bad_names.append(os.fsencode(e.name).decode("utf-8", "replace"))
                continue
            try:
                is_dir = e.is_dir()
                is_file = not is_dir and e.is_file()
                is_link = e.is_symlink()
            except OSError:
                continue
            if is_link and not inside(e.path):
                out.skipped += 1  # (a link out of the media folder: never followed)
                continue
            if is_dir:
                if naming.skipped_folder(e.name, top=folder == root) or depth >= DEPTH_MOST:
                    out.skipped += 1
                elif is_link:
                    linked.append((e.path, depth + 1))
                else:
                    look(e.path, depth + 1)
                continue
            if not is_file:
                continue
            low = e.name.casefold()
            if low.endswith(".nfo"):
                with contextlib.suppress(OSError):
                    st = e.stat()
                    out.nfos[e.path] = f"{st.st_size}:{st.st_mtime_ns}"
                continue
            if not naming.is_video(e.name) or naming.is_extra(e.name):
                if naming.is_video(e.name):
                    out.skipped += 1
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            if naming.named_sample(e.name) and st.st_size < NAMED_SAMPLE_BYTES:
                out.skipped += 1
                continue
            out.videos.append((e.path, st.st_size, st.st_mtime_ns))

    look(root, 0)
    while linked:
        look(*linked.pop(0))
    return out


def utf8(name: str) -> bool:
    """Whether a name is UTF-8 (one that isn't comes with stand-ins for its
    bytes that can't be kept or shown)."""
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


# Reading a file ------------------------------------------------------------------

_ENTRIES = (
    "format=duration,bit_rate,format_name:format_tags"
    ":stream=index,codec_type,codec_name,profile,width,height,bit_rate,channels,"
    "color_transfer,bits_per_raw_sample,pix_fmt"
    ":stream_tags=language,title,mimetype,filename"
    ":stream_disposition=default,forced,attached_pic"
)
_DOLBY_VISION = ":stream_side_data=dv_profile"
_asks_dolby_vision = True
# A file's own tags tapiOca reads (by their lowercase names).
TAG_NAMES = frozenset({
    "title", "date", "date_released", "year", "description", "synopsis", "summary", "comment",
    "show", "season_number", "episode_sort", "episode_id", "genre",
})  # fmt: skip


async def read_file(ffprobe: str, path: str, timeout: float = PROBE_S) -> dict[str, Any]:
    """What a video file holds, as kept (see _small): its length, picture,
    sound and subtitle tracks, covers and tags. {"ok": False, "error": ...}
    if it can't be read. ffprobe runs at the lowest priority."""
    global _asks_dolby_vision
    while True:
        entries = _ENTRIES + (_DOLBY_VISION if _asks_dolby_vision else "")
        args = [*ff.low_priority(), ffprobe, "-v", "error", "-show_entries", entries, "-of", "json"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args, path,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )  # fmt: skip
        except OSError as e:
            return {"ok": False, "error": f"couldn't run ffprobe: {e}"}
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            return {"ok": False, "error": f"it took more than {timeout:.0f}s to open", "slow": True}
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        if proc.returncode != 0 and _asks_dolby_vision and b"No match for section" in err:
            _asks_dolby_vision = False
            continue
        break
    if proc.returncode != 0:
        said = err.decode(errors="replace").strip().splitlines()
        return {"ok": False, "error": said[-1][:200] if said else "it can't be opened"}
    try:
        data = json.loads(out or b"{}")
    except ValueError:
        return {"ok": False, "error": "ffprobe's answer couldn't be read"}
    return _small(data)


def _int(value: Any) -> int | None:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _small(data: dict[str, Any]) -> dict[str, Any]:
    """What ffprobe said, as much of it as tapiOca keeps."""
    fmt: dict[str, Any] = data["format"] if isinstance(data.get("format"), dict) else {}
    streams = [s for s in data.get("streams") or [] if isinstance(s, dict)]
    try:
        duration_ms = round(float(fmt.get("duration") or "") * 1000)
    except (TypeError, ValueError):
        duration_ms = 0
    pictures, audio, subtitles, covers = [], [], [], []
    for s in streams:
        kind = s.get("codec_type")
        tags = {str(k).lower(): str(v) for k, v in (s.get("tags") or {}).items()}
        disposition = s.get("disposition") or {}
        index = _int(s.get("index"))
        if kind == "video" and disposition.get("attached_pic"):
            covers.append({"stream": index, "codec": str(s.get("codec_name") or "")})
        elif kind == "video":
            transfer = str(s.get("color_transfer") or "")
            dv = None
            for side in s.get("side_data_list") or []:
                if isinstance(side, dict) and isinstance(side.get("dv_profile"), int):
                    dv = side["dv_profile"]
            depth = _int(s.get("bits_per_raw_sample")) or (
                10 if "10" in str(s.get("pix_fmt") or "") else 8
            )
            pictures.append({
                "codec": str(s.get("codec_name") or ""), "width": _int(s.get("width")) or 0,
                "height": _int(s.get("height")) or 0, "bitDepth": depth,
                "hdr": "hdr10" if transfer == "smpte2084" else "hlg" if transfer == "arib-std-b67" else "",
                "dv": dv,
            })  # fmt: skip
        elif kind in ("audio", "subtitle"):
            track = {
                "index": index,
                "codec": str(s.get("codec_name") or ""),
                "language": tags.get("language", "")[:20],
                "title": tags.get("title", "")[:NAME_MOST],
                "default": bool(disposition.get("default")),
            }
            if kind == "audio":
                track["channels"] = _int(s.get("channels"))
                audio.append(track)
            else:
                track["forced"] = bool(disposition.get("forced"))
                subtitles.append(track)
    tags = {
        str(k).lower(): " ".join(str(v).split())[:TEXT_MOST]
        for k, v in (fmt.get("tags") or {}).items()
        if str(k).lower() in TAG_NAMES
    }
    if not pictures:
        return {"ok": False, "error": "it has no picture", "tags": tags}
    return {
        "ok": True,
        "durationMs": duration_ms,
        "container": str(fmt.get("format_name") or "").split(",")[0],
        "bitrateKbps": (_int(fmt.get("bit_rate")) or 0) // 1000 or None,
        "video": pictures[0],
        "audio": audio,
        "subtitles": subtitles,
        "covers": covers[:3],
        "tags": tags,
    }


# What the layers say -------------------------------------------------------------


class Layers:
    """A show's, episode's or movie's details as the layers give them: each
    detail from the first layer that has it, with where it came from:
    {field: [value, layer, where]}. IDs are each kept from the first layer
    that has that kind of ID; one that another layer says differently is
    noted (see `disagree`)."""

    def __init__(self) -> None:
        self.found: dict[str, list] = {}
        self.ids: dict[str, list] = {}  # kind: [value, layer, where]
        self.disagree: list[str] = []

    def put(self, name: str, value: Any, layer: str, where: str) -> None:
        if name == "ids":
            for kind, v in (value or {}).items():
                had = self.ids.get(kind)
                if had is None:
                    self.ids[kind] = [v, layer, where]
                elif had[0] != v and had[1] != layer:
                    self.disagree.append(
                        f"{_where(had[2])} says its {kind.upper()} ID is {had[0]}, and "
                        f"{_where(where)} says {v}"
                    )
            return
        if name in self.found or value in (None, "", [], ()):
            return
        self.found[name] = [value, layer, where]

    def put_all(self, details: dict[str, Any], layer: str, where: str) -> None:
        for name, value in details.items():
            if name != "kind":
                self.put(name, value, layer, where)

    def value(self, name: str) -> Any:
        got = self.found.get(name)
        return got[0] if got else None

    def result(self) -> dict[str, list]:
        out = dict(self.found)
        if self.ids:
            out["ids"] = [
                {k: v[0] for k, v in self.ids.items()},
                min((v[1] for v in self.ids.values()), key=LOCAL_LAYERS.index),
                next(iter(self.ids.values()))[2],
            ]
        return out


def _where(where: str) -> str:
    return where if where else "a name"


def from_tags(tags: dict[str, str]) -> dict[str, Any]:
    """What a file's own tags say, by tapiOca's names for details."""
    out: dict[str, Any] = {}
    title = tags.get("title", "").strip()
    if title and not naming.looks_like_release(title):
        out["title"] = title[:NAME_MOST]
    for name in ("date_released", "date", "year"):
        said = tags.get(name, "").strip()
        day = re.match(r"(\d{4})-(\d{2})-(\d{2})", said)
        year = re.match(r"(\d{4})", said)
        if day and "released" not in out:
            out["released"] = day.group(0)
        if year and "year" not in out and 1880 <= int(year.group(1)) <= 2100:
            out["year"] = int(year.group(1))
    for name in ("description", "synopsis", "summary", "comment"):
        said = tags.get(name, "").strip()
        if said and not naming.looks_like_release(said) and len(said) > 20:
            out["summary"] = said[:TEXT_MOST]
            break
    show = tags.get("show", "").strip()
    if show:
        out["show"] = show[:NAME_MOST]
    season = _int(tags.get("season_number"))
    if season is not None and season < 10_000:
        out["season"] = season
    episode = _int(tags.get("episode_sort"))
    if episode is None:
        named = naming.episode_name(tags.get("episode_id", ""))
        if named.episodes:
            episode = named.episodes[0]
            if "season" not in out and named.season is not None:
                out["season"] = named.season
    if episode is not None and episode < 100_000:
        out["episode"] = episode
    genres = [g.strip() for g in re.split(r"[;/,]", tags.get("genre", "")) if g.strip()]
    if genres:
        out["genres"] = list(dict.fromkeys(genres))[:LIST_MOST]
    return out


# Building a library's shows, episodes and movies --------------------------------


@dataclass
class Found:
    """A show, an episode or a movie, as the folders have it: `path` is a
    show's folder (or for one whose episodes are loose in a library folder,
    that folder and its title), an episode's or movie's first file; `files`
    an episode's or movie's versions, each its parts in order; `local` its
    details from the layers inside tapiOca; `art` its pictures (paths,
    or "cover:<stream>:<codec>:<file>" for one inside a file); `needs` why
    it needs a match, if it does (see folders.py)."""

    kind: str
    path: str
    root: str
    show: str = ""  # (an episode's show, by its path)
    files: list[list[str]] = field(default_factory=list)
    local: dict[str, list] = field(default_factory=dict)
    art: dict[str, str] = field(default_factory=dict)
    needs: list[str] = field(default_factory=list)
    slot: tuple = ()  # (an episode's place in its show: see _slot)


Nfos = Callable[[str], list[dict[str, Any]] | None]


def _picture(names: dict[str, str], folder: str, wanted: tuple[str, ...]) -> str:
    for name in wanted:
        for ext in TYPES:
            found = names.get(f"{name}{ext}")
            if found:
                return os.path.join(folder, found)
    return ""


def _pictures_beside(
    names: dict[str, str], folder: str, own: bool, stem: str = ""
) -> dict[str, str]:
    """A show's or movie's pictures in its folder (`own`: the folder is its
    own, so its poster.jpg is its poster), and a movie's <file>-poster.jpg
    and <file>-fanart.jpg (`stem`: its file's name without its extension)."""
    art: dict[str, str] = {}
    low = stem.casefold()
    for kind, wanted in (
        ("poster", POSTER_NAMES),
        ("backdrop", BACKDROP_NAMES),
        ("logo", LOGO_NAMES),
        ("banner", BANNER_NAMES),
    ):
        found = ""
        if low:
            found = _picture(names, folder, tuple(f"{low}-{w}" for w in wanted))
        if not found and own:
            found = _picture(names, folder, wanted)
        if found:
            art[kind] = found
    return art


def _cover(path: str, probes: dict[str, dict[str, Any]]) -> str:
    covers = (probes.get(path) or {}).get("covers") or []
    if covers and covers[0].get("stream") is not None:
        return f"cover:{covers[0]['stream']}:{covers[0].get('codec') or ''}:{path}"
    return ""


def _size(path: str, sizes: dict[str, int]) -> int:
    return sizes.get(path, 0)


def _preferred(paths: list[str], probes: dict[str, dict[str, Any]]) -> list[str]:
    """Versions of one program, the one stations play first: the largest
    picture up to 1080 lines (a 4K one takes far more to convert), then the
    rest; any that can't be read last."""

    def order(path: str) -> tuple:
        probe = probes.get(path) or {}
        height = (probe.get("video") or {}).get("height") or 0
        return (not probe.get("ok"), height > 1100, -height if height <= 1100 else height, path)

    return sorted(paths, key=order)


def _without_samples(paths: list[str], sizes: dict[str, int]) -> list[str]:
    """`paths` less samples: under SAMPLE_BYTES beside one MUCH_BIGGER times
    their size."""
    biggest = max((_size(p, sizes) for p in paths), default=0)
    return [
        p
        for p in paths
        if not (
            _size(p, sizes) < SAMPLE_BYTES
            and biggest >= SAMPLE_BYTES
            and biggest >= MUCH_BIGGER * max(1, _size(p, sizes))
        )
    ]


def build(kind: str, walked: Walked, probes: dict[str, dict[str, Any]], nfos: Nfos) -> list[Found]:
    """A library folder's shows and episodes, or movies (`kind`)."""
    if kind == "show":
        return _shows(walked, probes, nfos)
    return _movies(walked, probes, nfos)


# Shows --------------------------------------------------------------------------


def _season_of_folder(folder: str, walked: Walked, nfos: Nfos) -> int | None:
    number = naming.season_folder(os.path.basename(folder))
    if number is not None:
        return number
    names = walked.names.get(folder, {})
    if "season.nfo" in names:
        for d in nfos(os.path.join(folder, names["season.nfo"])) or []:
            if d.get("kind") == "season" and isinstance(d.get("season"), int):
                return int(d["season"])
    return None


def _shows(walked: Walked, probes: dict[str, dict[str, Any]], nfos: Nfos) -> list[Found]:
    root = walked.root
    sizes = {p: s for p, s, _ in walked.videos}
    # (A library folder that's one show's own: its seasons' folders in it,
    # and no other folder with videos, which would be other shows: a
    # "Specials" folder among shows' is one of them.)
    holding = {  # (the folders right inside it that hold videos)
        rel.split(os.sep)[0]
        for path, _, _ in walked.videos
        if os.sep in (rel := os.path.relpath(path, root))
    }
    seasons = {name for name in holding if naming.season_folder(name) is not None}
    one_show = bool(seasons) and seasons == holding
    by_show: dict[str, list[str]] = {}
    loose: dict[str, tuple[str, list[str]]] = {}  # folded title: (title, files)
    for path, _, _ in walked.videos:
        rel = os.path.relpath(path, root)
        if one_show:
            by_show.setdefault(root, []).append(path)
        elif os.sep in rel:
            by_show.setdefault(os.path.join(root, rel.split(os.sep)[0]), []).append(path)
        else:
            # (Loose in a library folder: its show is in its name.)
            named = naming.episode_name(os.path.basename(path))
            title = named.show or _tags_of(path, probes).get("show", "")
            if not title:
                title = naming.title_from(os.path.basename(path)) or "Untitled"
            loose.setdefault(naming.folded(title), (title, []))[1].append(path)
    # (Loose files of a show that has its own folder too are that show's.)
    folders = {naming.folded(naming.show_folder(os.path.basename(f)).title): f for f in by_show}
    for key, (_, files) in list(loose.items()):
        if key in folders:
            by_show[folders[key]] += files
            del loose[key]
    out: list[Found] = []
    for folder, files in sorted(by_show.items()):
        out += _one_show(folder, files, walked, probes, nfos, sizes)
    for title, files in loose.values():
        out += _one_show(os.path.join(root, title), files, walked, probes, nfos, sizes, title)
    return out


def _tags_of(path: str, probes: dict[str, dict[str, Any]]) -> dict[str, str]:
    return (probes.get(path) or {}).get("tags") or {}


def _one_show(
    folder: str,
    files: list[str],
    walked: Walked,
    probes: dict[str, dict[str, Any]],
    nfos: Nfos,
    sizes: dict[str, int],
    loose_title: str = "",
) -> list[Found]:
    """One show and its episodes."""
    root = walked.root
    names = {} if loose_title else walked.names.get(folder, {})
    layers = Layers()
    if "tvshow.nfo" in names:
        where = names["tvshow.nfo"]
        for d in nfos(os.path.join(folder, where)) or []:
            if d.get("kind") in ("tvshow", ""):
                layers.put_all(d, NFO, where)
                break
    shows_said = Counter(t for p in files if (t := from_tags(_tags_of(p, probes)).get("show")))
    if len(shows_said) == 1:
        title, _ = shows_said.most_common(1)[0]
        layers.put("title", title, TAGS, os.path.basename(files[0]))
    named = naming.show_folder(loose_title or os.path.basename(folder))
    where = os.path.basename(files[0]) if loose_title else os.path.basename(folder)
    layers.put("title", named.title, NAMES, where)
    layers.put("year", named.year, NAMES, where)
    layers.put("ids", named.ids, NAMES, where)
    show = Found("show", folder, root, local={}, needs=list(dict.fromkeys(layers.disagree)))
    seasons: dict[str, str] = {}
    if not loose_title:
        show.art = _pictures_beside(names, folder, own=True)
        for low, name in names.items():
            m = re.fullmatch(r"season[\s._-]*(\d{1,4}|specials)-poster\.(jpe?g|png|webp)", low)
            if m:
                number = 0 if m.group(1) == "specials" else int(m.group(1))
                seasons[str(number)] = os.path.join(folder, name)
    # Episodes, each file's first; then grouped by their place in the show.
    slots: dict[tuple, list[tuple[str, Layers, list[str]]]] = {}
    season_folders: dict[str, int | None] = {}
    for path in files:
        for slot, ep_layers, needs in _episodes_in(
            path, folder, walked, probes, nfos, season_folders
        ):
            slots.setdefault(slot, []).append((path, ep_layers, needs))
    out: list[Found] = []
    for slot, found in slots.items():
        paths = _preferred(_without_samples([p for p, _, _ in found], sizes), probes)
        if not paths:
            continue
        first = next(f for f in found if f[0] == paths[0])
        ep = Found(
            "episode", paths[0], root, show=folder, files=[[p] for p in paths],
            local=first[1].result(), needs=list(dict.fromkeys(first[2] + first[1].disagree)),
            slot=slot,
        )  # fmt: skip
        ep.art = _episode_art(paths[0], walked, probes)
        out.append(ep)
    if not loose_title:
        for number in seasons_found(out):
            season_folder = _season_folder_of(out, number)
            if season_folder and str(number) not in seasons:
                pic = _picture(
                    walked.names.get(season_folder, {}), season_folder, ("poster", "folder")
                )
                if pic:
                    seasons[str(number)] = pic
        if seasons:
            show.art["seasons"] = json.dumps(seasons, sort_keys=True)
    show.local = layers.result()
    return [show, *out]


def seasons_found(episodes: list[Found]) -> list[int]:
    return sorted({s for e in episodes if isinstance(s := e.local.get("season", [None])[0], int)})


def _season_folder_of(episodes: list[Found], season: int) -> str:
    for e in episodes:
        if e.local.get("season", [None])[0] == season:
            folder = os.path.dirname(e.path)
            if folder != e.show:
                return folder
    return ""


def _episode_art(path: str, walked: Walked, probes: dict[str, dict[str, Any]]) -> dict[str, str]:
    folder, name = os.path.split(path)
    stem = naming.stem(name).casefold()
    names = walked.names.get(folder, {})
    found = _picture(names, folder, (f"{stem}-thumb", stem))
    if not found:
        found = _cover(path, probes)
    return {"thumb": found} if found else {}


def _episodes_in(
    path: str,
    show_folder: str,
    walked: Walked,
    probes: dict[str, dict[str, Any]],
    nfos: Nfos,
    season_folders: dict[str, int | None],
) -> list[tuple[tuple, Layers, list[str]]]:
    """The episodes one file holds: (its place in the show, its details,
    why it needs a match)."""
    folder, name = os.path.split(path)
    # Its season's folder: the nearest folder between it and its show's
    # that's named as one (or has a season.nfo saying which).
    season_dir: int | None = None
    here = folder
    while here.startswith(show_folder) and here != show_folder:
        if here not in season_folders:
            season_folders[here] = _season_of_folder(here, walked, nfos)
        if season_folders[here] is not None:
            season_dir = season_folders[here]
            break
        here = os.path.dirname(here)
    named = naming.episode_name(name)
    season_named = named.season if named.season is not None else season_dir
    numbers_named = list(named.episodes)
    title_named = named.title
    if not numbers_named and not named.aired and season_dir is not None:
        number, title_named = naming.number_only(name)
        if number is not None:
            numbers_named = [number]
    tags = from_tags(_tags_of(path, probes))
    stem = naming.stem(name)
    names = walked.names.get(folder, {})
    nfo_name = names.get(f"{stem.casefold()}.nfo")
    said = (
        [
            d
            for d in (nfos(os.path.join(folder, nfo_name)) or [])
            if d.get("kind") == "episodedetails"
        ]
        if nfo_name
        else []
    )
    out: list[tuple[tuple, Layers, list[str]]] = []
    # The numbers each layer gives.
    nfo_numbers = [
        (d.get("season"), d.get("episode")) for d in said if isinstance(d.get("episode"), int)
    ]
    # (As many as a file's name can say, at most: an NFO can't make one file
    # thousands of episodes.)
    count = min(max(len(said), len(numbers_named), 1), naming.RANGE_MOST)
    for n in range(count):
        layers = Layers()
        needs: list[str] = []
        d = said[n] if n < len(said) else None
        if d is not None:
            layers.put_all(d, NFO, nfo_name or "")
        if n == 0 or count == 1:
            layers.put_all({k: v for k, v in tags.items() if k != "show"}, TAGS, name)
        elif "season" in tags:
            layers.put("season", tags["season"], TAGS, name)
        number = numbers_named[n] if n < len(numbers_named) else None
        layers.put("season", season_named, NAMES, name)
        layers.put("episode", number, NAMES, name)
        if named.aired:
            layers.put("released", named.aired, NAMES, name)
            layers.put("year", int(named.aired[:4]), NAMES, name)
            layers.put("season", int(named.aired[:4]), NAMES, name)
        layers.put("title", title_named, NAMES, name)
        layers.put("ids", named.ids, NAMES, name)
        # Where the NFO and the name disagree about which episode it is.
        if d is not None and numbers_named and nfo_numbers:
            nfo_season, nfo_episode = d.get("season"), d.get("episode")
            if (
                (
                    isinstance(nfo_season, int)
                    and season_named is not None
                    and nfo_season != season_named
                )
                or (isinstance(nfo_episode, int) and number is not None and nfo_episode != number)
                or (len(nfo_numbers) != len(numbers_named))
            ):
                needs.append(
                    f"Its NFO says {_numbered(nfo_season, nfo_episode)}, and its name says "
                    f"{_numbered(season_named, number)}"
                )
        season = layers.value("season")
        episode = layers.value("episode")
        aired = layers.value("released") if named.aired else ""
        if isinstance(season, int) and isinstance(episode, int):
            slot: tuple = ("episode", season, episode)
        elif aired:
            slot = ("aired", aired, n)
        else:
            slot = ("file", path, n)
            needs.append(
                "tapiOca can't tell which episode this is: neither its name nor its NFO "
                "says its season and episode"
            )
        out.append((slot, layers, needs))
    return out


def _numbered(season: Any, episode: Any) -> str:
    if isinstance(season, int) and isinstance(episode, int):
        return f"S{season:02d}E{episode:02d}"
    if isinstance(episode, int):
        return f"episode {episode}"
    return "no episode"


# Movies -------------------------------------------------------------------------


def _movies(walked: Walked, probes: dict[str, dict[str, Any]], nfos: Nfos) -> list[Found]:
    root = walked.root
    sizes = {p: s for p, s, _ in walked.videos}
    by_folder: dict[str, list[str]] = {}
    for path, _, _ in walked.videos:
        by_folder.setdefault(os.path.dirname(path), []).append(path)
    out: list[Found] = []
    for folder, files in sorted(by_folder.items()):
        own_name = os.path.basename(folder) if folder != root else ""
        # (A sample is a small file of the same movie: anything small in a
        # movie's own folder, "Title (1999)"; elsewhere, a short film beside
        # a feature is a movie of its own.)
        if own_name and naming.show_folder(own_name).year is not None:
            files = _without_samples(files, sizes)
        groups: dict[tuple, list[tuple[str, naming.MovieName]]] = {}
        for path in sorted(files):
            named = naming.movie_name(os.path.basename(path), own_name)
            groups.setdefault((naming.folded(named.title), named.year), []).append((path, named))
        own = bool(own_name) and len(groups) == 1
        for found in groups.values():
            kept = set(_without_samples([p for p, _ in found], sizes))
            out.append(
                _one_movie(folder, [x for x in found if x[0] in kept], own, walked, probes, nfos)
            )
    return out


def _one_movie(
    folder: str,
    found: list[tuple[str, naming.MovieName]],
    own: bool,
    walked: Walked,
    probes: dict[str, dict[str, Any]],
    nfos: Nfos,
) -> Found:
    """One movie, from its files: its versions (by their labels: " - 4K",
    "{edition-...}"), each its parts (cd1, part2...) in order."""
    versions: dict[str, dict[int, list[str]]] = {}
    for path, named in found:
        versions.setdefault(named.label.casefold(), {}).setdefault(named.part or 0, []).append(path)
    files: list[list[str]] = []
    for label in sorted(versions, key=lambda x: (x != "", x)):
        parts = versions[label]
        # (Two files with one label and part: two versions.)
        most = max(len(p) for p in parts.values())
        files += [[parts[k][min(n, len(parts[k]) - 1)] for k in sorted(parts)] for n in range(most)]
    firsts = _preferred([v[0] for v in files], probes)
    files.sort(key=lambda v: firsts.index(v[0]))
    main = files[0][0]
    named = next(n for p, n in found if p == main)
    names = walked.names.get(folder, {})
    stem = naming.stem(os.path.basename(main))
    layers = Layers()
    for candidate in (f"{stem.casefold()}.nfo", *(("movie.nfo",) if own else ())):
        nfo_name = names.get(candidate)
        if not nfo_name:
            continue
        said = [
            d for d in nfos(os.path.join(folder, nfo_name)) or [] if d.get("kind") in ("movie", "")
        ]
        if said:
            layers.put_all(said[0], NFO, nfo_name)
            break
    layers.put_all(from_tags(_tags_of(main, probes)), TAGS, os.path.basename(main))
    # (Its own folder names it best: "Glass Garden (1999)/glass.garden.1999.mkv".)
    if own and (by_folder := naming.show_folder(os.path.basename(folder))).title:
        title, year, where = by_folder.title, by_folder.year, os.path.basename(folder)
        layers.put("ids", by_folder.ids, NAMES, where)
    else:
        title, year, where = (
            named.title or naming.title_from(os.path.basename(main)),
            named.year,
            os.path.basename(main),
        )
    layers.put("title", title, NAMES, where)
    layers.put("year", year, NAMES, where)
    layers.put("ids", named.ids, NAMES, os.path.basename(main))
    needs = list(layers.disagree)
    nfo_year = layers.value("year") if layers.found.get("year", [0, ""])[1] == NFO else None
    if nfo_year and year and nfo_year != year:
        needs.append(f"Its NFO says it's from {nfo_year}, and its name says {year}")
    movie = Found("movie", main, walked.root, files=files, local=layers.result(), needs=needs)
    movie.art = _pictures_beside(names, folder, own, stem)
    if "poster" not in movie.art and (cover := _cover(main, probes)):
        movie.art["poster"] = cover
    return movie
