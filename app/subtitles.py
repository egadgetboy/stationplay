"""Subtitles drawn into the picture ("burned in"), as each station chooses:
off, forced only (just the lines meant to be read, such as a film's
foreign-language dialogue), or always (in the language set for audio,
AUDIO_LANGUAGE).

They come from the program's own file (text subtitles such as SRT and ASS,
or the picture subtitles of DVDs and Blu-rays) or from a subtitle file next
to it, named as Plex expects ("Film (1999).en.srt", "Film (1999).en.forced.srt").
Viewers can't turn burned-in subtitles off: the station decides. If they
can't be drawn, the program plays without them (see the broadcaster).

Text subtitles inside a program's file are read out into a small file of
their own first (Extraction), kept in the data folder: drawing them straight
from the program's file would mean reading the whole file before its first
picture. That's done in the background, a program ahead; until it's done,
the program plays without them.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg as ff
from .config import Settings
from .ffmpeg import ProbeResult, Subtitles, SubtitleTrack

log = logging.getLogger(__name__)

MODES = ("off", "forced", "always")
# In the data folder: plain-named links to subtitle files, and the text
# subtitles read out of programs' files.
FOLDER = "subtitles"
EXTRACT_TIMEOUT_S = 30 * 60  # (a big file on a slow share)
EXTRACTS_AT_ONCE = 2
RETRY_FAILED_S = 24 * 3600  # subtitles that couldn't be read aren't tried again sooner
KEEP_UNUSED_S = 30 * 24 * 3600  # subtitles read out and not used for this long go
# Subtitle formats drawn as text, and as pictures. (Others are left alone.)
TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}
STYLED_CODECS = {"ass", "ssa"}
IMAGE_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"}
SIDECAR_SUFFIXES = {".srt": "subrip", ".ass": "ass", ".ssa": "ssa", ".vtt": "webvtt"}
UNKNOWN_LANGUAGE = ("", "und", "unk", "zxx", "mis")

# Language names and two-letter codes as files and subtitle files give
# them, as the three-letter codes ffprobe uses (and AUDIO_LANGUAGE).
_LANGUAGES = {
    "eng": ("en", "english"),
    "spa": ("es", "spanish", "espanol", "español"),
    "fre": ("fr", "fra", "french", "francais", "français"),
    "ger": ("de", "deu", "german", "deutsch"),
    "ita": ("it", "italian", "italiano"),
    "por": ("pt", "portuguese", "portugues", "português"),
    "dut": ("nl", "nld", "dutch", "nederlands"),
    "swe": ("sv", "swedish", "svenska"),
    "nor": ("no", "nb", "nob", "norwegian", "norsk"),
    "dan": ("da", "danish", "dansk"),
    "fin": ("fi", "finnish", "suomi"),
    "pol": ("pl", "polish", "polski"),
    "rus": ("ru", "russian"),
    "jpn": ("ja", "japanese"),
    "chi": ("zh", "zho", "chinese"),
    "kor": ("ko", "korean"),
    "ara": ("ar", "arabic"),
    "heb": ("he", "hebrew"),
    "hin": ("hi", "hindi"),
    "tur": ("tr", "turkish"),
    "gre": ("el", "ell", "greek"),
    "cze": ("cs", "ces", "czech"),
    "hun": ("hu", "hungarian"),
    "rum": ("ro", "ron", "romanian"),
}
_ALIASES = {alias: code for code, aliases in _LANGUAGES.items() for alias in (code, *aliases)}
_FORCED = re.compile(r"\bforced\b", re.IGNORECASE)
_HEARING = re.compile(r"\b(sdh|cc|hi|hoh|hearing)\b", re.IGNORECASE)
# A language code as subtitle files and files' tags give them: "en",
# "eng", "pt-BR", "zh_Hans".
_CODE = re.compile(r"[a-z]{2,3}(?:[-_][a-z0-9]{2,8})*")


def language(text: str) -> str:
    """A language as a three-letter code where it's known ("en", "en-US",
    "English" and "eng" are all "eng"); otherwise its code without the
    region ("pt-BR" is "pt"), or as given, in lower case."""
    text = text.strip().lower()
    if text in _ALIASES:
        return _ALIASES[text]
    if _CODE.fullmatch(text):
        main = re.split(r"[-_]", text)[0]
        return _ALIASES.get(main, main)
    return text


def _is_language(word: str) -> bool:
    """Whether a word in a subtitle file's name names a language."""
    word = word.lower()
    return word in _ALIASES or bool(_CODE.fullmatch(word))


@dataclass(frozen=True)
class Candidate:
    """Subtitles that could be drawn: a stream in the file, or a file."""

    codec: str
    language: str  # (see language())
    forced: bool
    hearing_impaired: bool
    stream: int | None = None  # in the program's file
    path: str = ""  # a subtitle file

    @property
    def image(self) -> bool:
        return self.codec in IMAGE_CODECS


def from_streams(tracks: list[SubtitleTrack]) -> list[Candidate]:
    return [
        Candidate(
            t.codec,
            language(t.language),
            t.forced or bool(_FORCED.search(t.title)),
            t.hearing_impaired or bool(_HEARING.search(t.title)),
            stream=t.index,
        )
        for t in tracks
        if t.codec in TEXT_CODECS or t.codec in IMAGE_CODECS
    ]


def sidecars(source: str) -> list[Candidate]:
    """Subtitle files next to a program's file, named after it:
    "Film (1999).srt", "Film (1999).en.srt", "Film (1999).eng.forced.srt",
    "Film (1999).English.SDH.srt"."""
    folder, name = os.path.split(source)
    stem = os.path.splitext(name)[0]
    try:
        names = os.listdir(folder or ".")
    except OSError:
        return []
    found = []
    for other in sorted(names):
        base, suffix = os.path.splitext(other)
        codec = SIDECAR_SUFFIXES.get(suffix.lower())
        if codec is None or not (base == stem or base.startswith(stem + ".")):
            continue
        words = [w for w in base[len(stem) :].split(".") if w]
        flags = [w for w in words if w.lower() == "forced" or _HEARING.fullmatch(w)]
        lang = next((language(w) for w in words if w not in flags and _is_language(w)), "")
        found.append(
            Candidate(
                codec,
                lang,
                any(w.lower() == "forced" for w in words),
                any(_HEARING.fullmatch(w) for w in words),
                path=os.path.join(folder, other),
            )
        )
    return found


def choose(mode: str, wanted: str, candidates: list[Candidate]) -> tuple[Candidate, bool] | None:
    """The subtitles a station set to `mode` draws, in language `wanted`,
    from `candidates`; and whether only their forced lines are (a Blu-ray's
    picture subtitles, with no forced stream of their own). None: none."""
    wanted = language(wanted)
    mine = [c for c in candidates if c.language == wanted]

    def best(cs: list[Candidate]) -> Candidate | None:
        # Text before pictures (sharper, and lighter to draw); the file's
        # own before a subtitle file next to it.
        ranked = sorted(cs, key=lambda c: (c.image, c.stream is None))
        return ranked[0] if ranked else None

    if mode == "forced":
        forced = best([c for c in mine if c.forced])
        if forced is not None:
            return forced, False
        blu_ray = [c for c in mine if c.codec == "hdmv_pgs_subtitle" and c.stream is not None]
        return (blu_ray[0], True) if blu_ray else None
    if mode != "always":
        return None
    for group in (
        [c for c in mine if not c.forced and not c.hearing_impaired],
        [c for c in mine if not c.forced],
        # A subtitle file that doesn't say its language: someone put it there.
        [c for c in candidates if c.language in UNKNOWN_LANGUAGE and c.path and not c.forced],
        list(mine),
    ):
        chosen = best(group)
        if chosen is not None:
            return chosen, False
    return None


def _key(text: str) -> str:
    # (A file name may not be valid UTF-8: it's hashed as its bytes.)
    return hashlib.sha1(os.fsencode(text)).hexdigest()[:24]


def link(data_dir: Path, path: str) -> str | None:
    """A link to `path` with a plain name in the data folder (ffmpeg's
    subtitle drawing takes a file name in its filter, where most of the
    characters names can have would need escaping). None if it can't be
    made."""
    suffix = os.path.splitext(path)[1].lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", suffix):
        suffix = ""
    folder = data_dir / FOLDER
    made = folder / (_key(path) + suffix)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if made.is_symlink() and os.readlink(made) == path:
            return str(made)
        # Made under another name and put in place in one step, so a station
        # starting the same program at the same moment never finds it gone.
        new = folder / f"{made.name}.{secrets.token_hex(4)}.new"
        new.symlink_to(path)
        os.replace(new, made)
    except OSError as e:
        log.warning("Can't make a link to the subtitle file %s (%s)", path, e)
        return None
    return str(made)


def tidy(data_dir: Path) -> None:
    """Removes links whose files have gone, anything left half made, and
    subtitles read out of files that haven't been used for a month."""
    folder = data_dir / FOLDER
    if not folder.is_dir():
        return
    now = time.time()
    for entry in folder.iterdir():
        with contextlib.suppress(OSError):
            if entry.is_symlink():
                if not entry.exists():
                    entry.unlink()
            elif entry.name.endswith((".new", ".part")) or (
                entry.suffix == ".ass" and now - entry.stat().st_mtime > KEEP_UNUSED_S
            ):
                entry.unlink()


@dataclass(frozen=True)
class Extraction:
    """Text subtitles in a program's file (`stream`, among its subtitle
    streams), to be read out into a file of their own, `target`, before
    they're drawn."""

    source: str
    stream: int
    target: Path
    styled: bool

    def ready(self) -> Subtitles:
        return Subtitles(path=str(self.target), styled=self.styled)


_extracting: dict[Path, asyncio.Task[bool]] = {}
_failed: dict[Path, float] = {}  # (when)
_slots: dict[int, asyncio.Semaphore] = {}  # (one per event loop)


def extract(settings: Settings, job: Extraction) -> asyncio.Task[bool]:
    """Reads `job`'s subtitles out of its file in the background (once,
    however many ask): the task's result says whether they're ready."""
    task = _extracting.get(job.target)
    if task is None:
        task = asyncio.create_task(_extract(settings, job))
        _extracting[job.target] = task
        task.add_done_callback(lambda _t: _extracting.pop(job.target, None))
    return task


async def _extract(settings: Settings, job: Extraction) -> bool:
    loop = id(asyncio.get_running_loop())
    slots = _slots.setdefault(loop, asyncio.Semaphore(EXTRACTS_AT_ONCE))
    part = job.target.with_name(f"{job.target.name}.{secrets.token_hex(4)}.part")
    async with slots:
        if job.target.exists():
            return True
        args = [
            settings.ffmpeg_path, "-hide_banner", "-nostdin", "-v", "error", "-threads", "1",
            "-i", job.source, "-map", f"0:s:{job.stream}", "-c:s", "ass", "-f", "ass", "-y",
            str(part),
        ]  # fmt: skip
        try:
            code, said = await ff.run_to_end(args, EXTRACT_TIMEOUT_S)
            if code != 0 or not part.exists():
                raise RuntimeError(ff.redact(said or f"exit code {code}"))
            await asyncio.to_thread(os.replace, part, job.target)
        except (OSError, TimeoutError, RuntimeError) as e:
            _failed[job.target] = time.time()
            log.warning(
                "Couldn't extract the subtitles from %s; it plays without them (%s)",
                job.source,
                e or "it took too long",
            )
            return False
        finally:
            with contextlib.suppress(OSError):
                part.unlink(missing_ok=True)
    log.info("Extracted the subtitles from %s", os.path.basename(job.source))
    return True


def for_program(
    data_dir: Path, mode: str, wanted: str, source: str, probe: ProbeResult
) -> Subtitles | Extraction | None:
    """What subtitles a program on a station set to `mode` gets (None: it
    plays without; an Extraction: text subtitles in its file, to be read
    out first). Text subtitles are read from a file on disk, so a program
    streamed from Plex only gets picture subtitles. (It looks in the
    program's folder: run it off the event loop.)"""
    if mode not in ("forced", "always"):
        return None
    local = not source.startswith(("http://", "https://"))
    candidates = from_streams(probe.subtitles) + (sidecars(source) if local else [])
    if not local:
        candidates = [c for c in candidates if c.image]
    chosen = choose(mode, wanted, candidates)
    if chosen is None:
        return None
    candidate, forced_only = chosen
    if candidate.image:
        return Subtitles(stream=candidate.stream, image=True, forced_only=forced_only)
    styled = candidate.codec in STYLED_CODECS
    if candidate.stream is not None:
        # Read out once into a file of their own (the same file, unchanged,
        # has the same name).
        info = os.stat(source)
        target = (
            data_dir
            / FOLDER
            / (_key(f"{source}|{candidate.stream}|{info.st_size}|{info.st_mtime_ns}") + ".ass")
        )
        if target.exists():
            with contextlib.suppress(OSError):
                os.utime(target)  # (in use: see tidy)
            return Subtitles(path=str(target), styled=styled)
        if time.time() - _failed.get(target, 0) < RETRY_FAILED_S:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        return Extraction(source, candidate.stream, target, styled)
    linked = link(data_dir, candidate.path)
    if linked is None:
        return None
    return Subtitles(path=linked, styled=styled)
