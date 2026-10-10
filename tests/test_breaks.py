"""Commercials, trailers and Station ID cards: finding them, and sharing them
out after programs."""

from __future__ import annotations

import asyncio
import shutil
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import breaks as br
from app.breaks import ID_CARD, Clip, FillerLibrary, with_breaks
from app.broadcaster import _clip_at, between
from app.config import Settings
from app.db import Database, Item
from app.library import Library
from app.plex import PlexClient
from app.replacement import pick_replacement
from app.schedule import Slot
from app.sources import MediaAccess
from app.updates import compare

from .fakeplex import FakePlex
from .test_e2e import ff

S = 1000


CARD_MS = 5_000  # a Station ID card


def episode(key: str, ms: int = 60 * S, show: str = "s1") -> Item:
    return Item(0, 0, ms, key, "episode", f"Ep {key}", "Show", show, 1, int(key), None)


def movie(key: str, ms: int = 90 * 60 * S) -> Item:
    return Item(0, 0, ms, key, "movie", f"Movie {key}", year=1990)


def clips(prefix: str, n: int, ms: int = 30 * S) -> list[Clip]:
    return [Clip(f"/m/{prefix}{i}.mp4", ms, 100, 1.0) for i in range(n)]


def test_each_program_gets_its_commercials_or_trailers_then_the_card():
    items = [episode("1"), movie("2"), episode("3")]
    got = with_breaks(items, 2, CARD_MS, clips("c", 5), clips("t", 5, 120 * S), seed="7")
    ep, mv, ep2 = got
    assert [p.split("/")[-1][0] for p, _ in ep.breaks[:2]] == ["c", "c"]
    assert [p.split("/")[-1][0] for p, _ in mv.breaks[:2]] == ["t", "t"]
    for item in got:
        assert item.breaks[-1] == (ID_CARD, CARD_MS)
        assert len(item.breaks) == 3
    # The program keeps its length; the slot grows by what follows it.
    assert ep.program_ms == 60 * S
    assert ep.duration_ms == 60 * S + 2 * 30 * S + CARD_MS
    assert mv.duration_ms == 90 * 60 * S + 2 * 120 * S + CARD_MS
    assert ep2.breaks != ep.breaks or len(clips("c", 5)) < 4


def test_breaks_are_the_same_every_time_and_can_be_redone():
    items = [episode(str(n)) for n in range(1, 30)]
    pool = clips("c", 7)
    once = with_breaks(items, 2, 0, pool, [], seed="3")
    again = with_breaks(list(reversed(items)), 2, 0, list(reversed(pool)), [], seed="3")
    assert {i.rating_key: i.breaks for i in once} == {i.rating_key: i.breaks for i in again}
    # Redoing it on programs that already have breaks gives the same thing.
    assert with_breaks(once, 2, 0, pool, [], seed="3") == once
    # Another station deals them differently.
    other = with_breaks(items, 2, 0, pool, [], seed="4")
    assert [i.breaks for i in other] != [i.breaks for i in once]
    # Taking them away again restores the programs as they were.
    assert [i.duration_ms for i in with_breaks(once, 0, 0, pool, [], seed="3")] == [
        i.duration_ms for i in items
    ]


def test_clips_are_shared_out_evenly_and_never_twice_in_one_break():
    items = [episode(str(n)) for n in range(1, 101)]
    pool = clips("c", 9)
    got = with_breaks(items, 3, 0, pool, [], seed="x")
    plays = Counter(p for i in got for p, _ in i.breaks)
    assert sum(plays.values()) == 300
    assert max(plays.values()) - min(plays.values()) <= 2, plays
    for item in got:
        assert len({p for p, _ in item.breaks}) == 3


def test_a_decades_programs_get_that_decades_commercials():
    def dated(prefix: str, n: int, decade: int | None) -> list[Clip]:
        return [Clip(f"/m/{prefix}{i}.mp4", 30 * S, 100, 1.0, decade) for i in range(n)]

    def aired(year: int | None) -> Item:
        return Item(0, 0, 60 * S, f"{year}", "episode", "Ep", "Show", "s", 1, 1, year)

    items = [aired(1962), aired(1968), aired(1975), aired(1984), aired(None)]
    pool = dated("sixties", 4, 1960) + dated("seventies", 3, 1970) + dated("any", 5, None)
    got = {
        i.rating_key: {
            p.split("/")[-1].removesuffix(".mp4").rstrip("0123456789") for p, _ in i.breaks
        }
        for i in with_breaks(items, 2, 0, pool, [], seed="d")
    }
    assert got["1962"] == got["1968"] == {"sixties"}
    assert got["1975"] == {"seventies"}
    # No 1980s folder, or no year: the rest.
    assert got["1984"] == got["None"] == {"any"}
    # Every clip for some decade: a program from another gets any of them.
    only_dated = dated("sixties", 4, 1960) + dated("seventies", 3, 1970)
    (other,) = with_breaks([aired(1984)], 3, 0, only_dated, [], seed="d")
    assert len(other.breaks) == 3
    # Without decades' folders, the very same breaks as before: dealt from
    # one deck, as they always were.
    plain = clips("c", 7)
    deck = br._Deck(plain, "d:commercials")
    expected = {
        key: tuple((c.path, c.duration_ms) for c in deck.deal(2))
        for key in sorted(i.rating_key for i in items)
    }
    assert {
        i.rating_key: i.breaks for i in with_breaks(items, 2, 0, plain, [], seed="d")
    } == expected


def test_too_few_clips_still_fill_the_break():
    got = with_breaks([episode("1"), episode("2")], 3, 0, clips("c", 1), [], seed="x")
    assert [len(i.breaks) for i in got] == [3, 3]


def test_nothing_to_play_leaves_programs_alone():
    items = [episode("1"), movie("2")]
    assert with_breaks(items, 0, 0, clips("c", 3), clips("t", 3), seed="1") == items
    # Commercials wanted but none found: only the card, if that's on.
    got = with_breaks(items, 2, 0, [], [], seed="1")
    assert all(not i.breaks for i in got)
    assert [i.duration_ms for i in got] == [i.duration_ms for i in items]
    got = with_breaks(items, 2, CARD_MS, [], [], seed="1")
    assert [i.breaks for i in got] == [((ID_CARD, CARD_MS),)] * 2


def test_whats_on_during_the_break():
    item = with_breaks([episode("1", 60 * S)], 2, CARD_MS, clips("c", 2, 10 * S), [], seed="1")[0]
    slot = Slot(item, 0, 0, 1_000_000, 1_000_000 + item.duration_ms)
    assert between(slot, 1_000_000 + 59 * S) is None
    assert between(slot, 1_000_000 + 60 * S) == "commercials"
    assert between(slot, 1_000_000 + 79 * S) == "commercials"
    assert between(slot, 1_000_000 + 80 * S) == "station id"
    first = _clip_at(item, 1_000_000 + 60 * S, 1_000_000 + 65 * S)
    assert first is not None and first[1:] == (1_060_000, 1_070_000)
    assert _clip_at(item, 1_060_000, 1_000_000 + item.duration_ms) is None


def test_different_breaks_count_as_a_change():
    items = [episode("1"), episode("2")]
    a = with_breaks(items, 1, 0, clips("c", 4), [], seed="1")
    b = with_breaks(items, 1, 0, clips("d", 4), [], seed="1")
    assert compare(a, a) == (0, 0, False)
    assert compare(a, b) == (0, 0, True)
    assert compare(items, a)[2]


def test_a_replacement_only_needs_to_be_as_long_as_the_program():
    failed = with_breaks([episode("1", 60 * S)], 3, CARD_MS, clips("c", 3), [], seed="1")[0]
    # 50s long: shorter than the failed program's slot (with its breaks),
    # but long enough for the 40s of the program still to play.
    candidate = with_breaks([episode("2", 50 * S)], 3, CARD_MS, clips("c", 3), [], seed="1")[0]
    assert candidate.duration_ms > 60 * S
    assert pick_replacement([candidate], failed, 40 * S, set(), 1) is candidate
    assert pick_replacement([candidate], failed, 55 * S, set(), 1) is None


def test_breaks_are_saved_with_the_schedule(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    channel = db.create_channel(
        1, "One", [], order_mode="rotate", breaks=2, station_id=True, watermark="logo"
    )
    item = with_breaks([episode("1")], 2, CARD_MS, clips("c", 2), [], seed="1")[0]
    db.add_era(
        channel.id,
        [item],
        start_ms=0,
        epoch_ms=0,
        seed="s",
        order_mode="rotate",
        created_ms=0,
        reason="created",
    )
    saved = db.latest_items(channel.id)[0]
    assert saved.breaks == item.breaks and saved.program_ms == 60 * S
    stored = db.get_channel(channel.id)
    assert (stored.breaks, stored.station_id, stored.watermark) == (2, True, "logo")
    db.update_channel(channel.id, breaks=0)
    stored = db.get_channel(channel.id)
    assert (stored.breaks, stored.station_id, stored.watermark) == (0, True, "logo")
    db.close()


# Finding them on disk ---------------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def clip_file(path: Path, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ff(
        "-f", "lavfi", "-i", f"color=c=red:s=160x90:r=10:d={seconds}",
        "-f", "lavfi", "-i", "sine=f=300", "-t", str(seconds),
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path),
    )  # fmt: skip


def library(tmp_path: Path) -> tuple[SimpleNamespace, FakePlex]:
    plex = FakePlex()
    plex.set_locations("1", "/data/tv")
    plex.add_section("2", "Movies", "movie", ("/data/films",))
    plex.add_section("3", "More movies", "movie", ("/elsewhere/movies",))
    settings = Settings(plex_url="http://plex.test", plex_token="token", media_dir=str(tmp_path))
    ctx = SimpleNamespace(
        settings=settings,
        media_access=MediaAccess(),
        library=Library(PlexClient("http://plex.test", "token", transport=plex.transport())),
        db=Database(tmp_path / "db.sqlite"),
    )
    return ctx, plex


@needs_ffmpeg
async def test_finds_commercials_and_trailers_beside_the_libraries(tmp_path):
    ctx, _plex = library(tmp_path)
    clip_file(tmp_path / "tv/commercials/a.mp4", 4)
    clip_file(tmp_path / "tv/commercials/1990s/b.mkv", 5)
    clip_file(tmp_path / "films/trailers/t.mp4", 6)
    clip_file(tmp_path / "movies/trailers/other.mp4", 6)  # the third library's
    # Not these: the wrong case (Linux names are exact), too short, not video,
    # hidden, or not a video at all.
    clip_file(tmp_path / "tv/Commercials/wrong-case.mp4", 4)
    clip_file(tmp_path / "films/Trailers/wrong-case.mp4", 4)
    clip_file(tmp_path / "tv/commercials/blip.mp4", 1)
    clip_file(tmp_path / "tv/commercials/.hidden.mp4", 4)
    (tmp_path / "tv/commercials/.plexignore").write_text("*\n")
    (tmp_path / "tv/commercials/notes.txt").write_text("hi")
    (tmp_path / "tv/commercials/broken.mp4").write_bytes(b"not a video" * 100)
    fillers = FillerLibrary(ctx)
    await fillers.refresh()
    names = {k: sorted(Path(c.path).name for c in fillers.pool(k)) for k in fillers.clips}
    assert names == {"commercials": ["a.mp4", "b.mkv"], "trailers": ["other.mp4", "t.mp4"]}
    durations = {Path(c.path).name: c.duration_ms for c in fillers.pool("commercials")}
    assert abs(durations["a.mp4"] - 4000) < 150 and abs(durations["b.mkv"] - 5000) < 150
    # One in a decade's folder is for that decade's programs.
    decades = {Path(c.path).name: c.decade for c in fillers.pool("commercials")}
    assert decades == {"a.mp4": None, "b.mkv": 1990}
    info = fillers.as_dict()
    assert info["commercials"] == 2 and info["trailers"] == 2
    assert info["commercialFolders"] == [str(tmp_path / "tv/commercials")]


@needs_ffmpeg
async def test_a_station_made_while_the_first_look_is_going_waits_for_it(tmp_path):
    """A station made just after StationPlay starts, while it's still looking
    for commercials, gets them: ready() waits for the look under way (it
    once didn't, and the station had none until the next check for updates)."""
    ctx, _plex = library(tmp_path)
    clip_file(tmp_path / "tv/commercials/a.mp4", 4)
    fillers = FillerLibrary(ctx)
    go = asyncio.Event()
    asked = ctx.library.libraries

    async def slow_libraries():
        await go.wait()
        return await asked()

    ctx.library.libraries = slow_libraries
    first = asyncio.create_task(fillers.refresh())  # (as StationPlay starts)
    await asyncio.sleep(0.05)
    waiting = asyncio.create_task(fillers.ready())  # (a station being made)
    await asyncio.sleep(0.2)
    assert not waiting.done()
    go.set()
    await asyncio.wait_for(waiting, 30)
    assert [Path(c.path).name for c in fillers.pool("commercials")] == ["a.mp4"]
    await first
    # Once looked, ready() doesn't wait again; nor when the look failed.
    await asyncio.wait_for(fillers.ready(), 1)
    broken = FillerLibrary(ctx)

    async def no_plex():
        raise RuntimeError("Plex is down")

    ctx.library.libraries = no_plex
    await asyncio.wait_for(broken.ready(), 5)
    assert broken.pool("commercials") == []


@needs_ffmpeg
async def test_only_new_or_changed_files_are_opened_again(tmp_path, monkeypatch):
    ctx, _plex = library(tmp_path)
    clip_file(tmp_path / "tv/commercials/a.mp4", 4)
    fillers = FillerLibrary(ctx)
    await fillers.refresh()
    before = fillers.signature
    opened: list[str] = []
    real = br.ff.probe

    async def counting(settings, path, timeout=30.0):
        opened.append(Path(path).name)
        return await real(settings, path, timeout)

    monkeypatch.setattr(br.ff, "probe", counting)
    await fillers.refresh()
    assert opened == [] and fillers.signature == before
    clip_file(tmp_path / "tv/commercials/b.mp4", 4)
    await fillers.refresh()
    assert opened == ["b.mp4"] and fillers.signature != before


@needs_ffmpeg
async def test_a_clip_that_wont_play_is_left_out_until_it_changes(tmp_path):
    ctx, _plex = library(tmp_path)
    path = tmp_path / "tv/commercials/a.mp4"
    clip_file(path, 4)
    clip_file(tmp_path / "tv/commercials/b.mp4", 4)
    fillers = FillerLibrary(ctx)
    await fillers.refresh()
    signature = fillers.signature
    fillers.mark_bad(str(path), "test")
    assert fillers.is_bad(str(path))
    assert [Path(c.path).name for c in fillers.pool("commercials")] == ["b.mp4"]
    assert fillers.signature != signature
    assert fillers.as_dict()["unplayable"] == [str(path)]
    clip_file(path, 5)  # replaced with a new file
    await fillers.refresh()
    assert not fillers.is_bad(str(path))
    assert len(fillers.pool("commercials")) == 2


@needs_ffmpeg
async def test_a_share_that_doesnt_answer_keeps_what_was_found(tmp_path, monkeypatch):
    ctx, plex = library(tmp_path)
    clip_file(tmp_path / "tv/commercials/a.mp4", 4)
    fillers = FillerLibrary(ctx)
    await fillers.refresh()
    assert len(fillers.pool("commercials")) == 1

    async def hung(folder):
        raise TimeoutError

    monkeypatch.setattr(br, "_video_files", hung)
    await fillers.refresh()
    assert len(fillers.pool("commercials")) == 1
    plex.down = True
    await fillers.refresh()
    assert len(fillers.pool("commercials")) == 1


async def test_no_folders_means_no_commercials(tmp_path):
    ctx, _plex = library(tmp_path)
    fillers = FillerLibrary(ctx)
    await asyncio.wait_for(fillers.refresh(), 10)
    assert fillers.as_dict()["commercials"] == 0
    assert fillers.refreshed_ms > 0


def test_how_short_a_clip_may_play():
    from app.broadcaster import _clip_tolerance

    assert _clip_tolerance(4) == 1.0  # short clips: a second
    assert _clip_tolerance(8) == 2.0
    assert _clip_tolerance(30) == 3.0  # the sound often runs on past the picture
    assert _clip_tolerance(120) == 3.0


@needs_ffmpeg
def test_text_on_cards_is_shown_as_typed(tmp_path):
    """Names and titles with the characters ffmpeg's filters treat specially
    (: , ; [ ] ' % backslash) are drawn as they are, not dropped."""
    import subprocess

    from app import ffmpeg as ffm

    settings = Settings(plex_url="", plex_token="", video_width=320, video_height=180)

    def frame(lines: list[str], name: str = "") -> bytes:
        args = ffm.card_command(settings, 0.5, 0, 0.5, name, None, lines)
        ts = tmp_path / "card.ts"
        with open(ts, "wb") as f:
            subprocess.run(args, stdout=f, stderr=subprocess.DEVNULL, check=True)
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(ts), "-frames:v", "1", "-f", "rawvideo", "-"],
            capture_output=True,
            check=True,
        ).stdout

    blank = frame(["", "", ""])
    for text in ["Rock & Roll: 'Live' 50%", "Kids\\TV [HD]; a, b", "%{pts} 100%", "Ünïcødé"]:
        assert frame(["", text, ""]) != blank, text
        assert frame(["", "", ""], name=text) != blank, text
    # The slate's message too.
    slate = ffm.slate_command(settings, 0.5, 0, 0.5, "x", "We’re 100%: back")
    assert "expansion=none" in " ".join(slate)


@needs_ffmpeg
async def test_commercials_that_vanish_for_a_moment_stay(tmp_path, monkeypatch):
    """The folder unmounted or empty for a look or two (a share hiccup) keeps
    what was found; only a third look in a row finding nothing counts."""
    ctx, _plex = library(tmp_path)
    clip_file(tmp_path / "tv/commercials/a.mp4", 4)
    fillers = FillerLibrary(ctx)
    await fillers.refresh()
    shutil.move(tmp_path / "tv/commercials", tmp_path / "away")
    for _ in range(br.EMPTY_LOOKS - 1):
        await fillers.refresh()
        assert len(fillers.pool("commercials")) == 1
    await fillers.refresh()
    assert fillers.pool("commercials") == []
    shutil.move(tmp_path / "away", tmp_path / "tv/commercials")
    await fillers.refresh()
    assert len(fillers.pool("commercials")) == 1


@needs_ffmpeg
async def test_one_slow_file_doesnt_stop_the_rest(tmp_path, monkeypatch):
    ctx, _plex = library(tmp_path)
    clip_file(tmp_path / "tv/commercials/a.mp4", 4)
    clip_file(tmp_path / "tv/commercials/slow.mp4", 4)
    real = br.ff.probe

    async def slow_one(settings, path, timeout=30.0):
        if path.endswith("slow.mp4"):
            return br.ff.ProbeResult(ok=False, error="timed out", timed_out=True)
        return await real(settings, path, timeout)

    monkeypatch.setattr(br.ff, "probe", slow_one)
    fillers = FillerLibrary(ctx)
    await fillers.refresh()
    assert [Path(c.path).name for c in fillers.pool("commercials")] == ["a.mp4"]
    monkeypatch.setattr(br.ff, "probe", real)
    await fillers.refresh()  # looked at again
    assert len(fillers.pool("commercials")) == 2


@needs_ffmpeg
async def test_clips_that_failed_stay_left_out_after_a_restart(tmp_path):
    ctx, _plex = library(tmp_path)
    clip_file(tmp_path / "tv/commercials/a.mp4", 4)
    clip_file(tmp_path / "tv/commercials/b.mp4", 4)
    fillers = FillerLibrary(ctx)
    await fillers.refresh()
    fillers.mark_bad(str(tmp_path / "tv/commercials/a.mp4"), "test")
    again = FillerLibrary(ctx)  # StationPlay restarted
    await again.refresh()
    assert [Path(c.path).name for c in again.pool("commercials")] == ["b.mp4"]
    assert again.signature == fillers.signature


@needs_ffmpeg
async def test_a_library_that_is_the_whole_media_folder(tmp_path):
    """Plex's TV library is the folder mounted at /media: commercials are
    straight inside it."""
    ctx, plex = library(tmp_path)
    plex.set_locations("1", "/data")
    clip_file(tmp_path / "commercials/a.mp4", 4)
    fillers = FillerLibrary(ctx)
    await fillers.refresh()
    assert fillers.folders["commercials"] == [str(tmp_path / "commercials")]


# The corner logo's size and transparency ----------------------------------------


def test_large_and_low_transparency_is_how_1_6_0_drew_it():
    from app import ffmpeg as ffm

    settings = Settings(plex_url="", plex_token="", video_width=1280, video_height=720)
    logo = ffm._watermark(settings, ffm.Watermark(logo="/l/x.png"))
    assert "scale=94:94" in logo[0] and "aa=0.65" in logo[0]
    assert (
        ffm._watermark(settings, ffm.Watermark(logo="/l/x.png", size="large", transparency="low"))
        == logo
    )
    name = ffm._watermark(settings, ffm.Watermark(text="Hits"))[1]
    assert "fontsize=27" in name and "white@0.70" in name and "black@0.60" in name
    small = ffm._watermark(
        settings, ffm.Watermark(logo="/l/x.png", size="small", transparency="high")
    )
    assert "scale=51:51" in small[0] and "aa=0.26" in small[0]


@needs_ffmpeg
def test_smaller_and_more_see_through_really_are(tmp_path, media):
    """Rendered for real: each smaller size covers less of the corner, and
    each higher transparency changes the picture there less."""
    import subprocess

    from app import ffmpeg as ffm

    settings = Settings(plex_url="", plex_token="", video_width=640, video_height=360)
    logo = str(Path(ffm.__file__).parent / "logos" / "classic-tv.png")

    def corner(mark) -> list[int]:
        args = ffm.program_command(
            settings, str(media["good1"]), 2, 0.3, 0, 1, 0, "x", watermark=mark
        )
        ts = subprocess.run(args, capture_output=True, check=True).stdout
        return list(subprocess.run(
            ["ffmpeg", "-v", "error", "-i", "pipe:0", "-frames:v", "1", "-vf", "crop=100:80:540:280",
             "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            input=ts, capture_output=True, check=True,
        ).stdout)  # fmt: skip

    plain = corner(None)

    def change(size, transparency):
        got = corner(ffm.Watermark(logo=logo, size=size, transparency=transparency))
        diffs = [abs(a - b) for a, b in zip(got, plain, strict=True)]
        return sum(1 for d in diffs if d > 8), sum(diffs)

    area = {s: change(s, "low")[0] for s in ("large", "medium", "small")}
    strength = {t: change("large", t)[1] for t in ("low", "medium", "high")}
    assert area["large"] > area["medium"] > area["small"] > 0, area
    assert strength["low"] > strength["medium"] > strength["high"] > 0, strength


# The Station ID card's text -------------------------------------------------------


def test_titles_are_made_to_fit_not_cut_short():
    from app.ffmpeg import fit_lines, text_width

    # Short: as big as it goes, on one line.
    assert fit_lines("Friends", 800, 55, 32, 2) == (["Friends"], 55)
    # A bit long: a little smaller, still one line.
    lines, size = fit_lines("It's Always Sunny in Philadelphia", 800, 55, 32, 2)
    assert len(lines) == 1 and 41 <= size < 55
    # Long: two lines, split between words, every word kept.
    title = "Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb"
    lines, size = fit_lines(title, 800, 55, 32, 2)
    assert len(lines) == 2 and " ".join(lines) == title
    assert all(text_width(line, size) <= 800 for line in lines)
    # Beyond two lines even at the smallest size: only then cut short.
    lines, size = fit_lines("word " * 80, 800, 55, 32, 2)
    assert size == 32 and len(lines) == 2 and lines[-1].endswith("…")
    assert text_width(lines[-1], 32) <= 800
    assert fit_lines("", 800, 55, 32, 2)[0] == [""]


def test_the_card_says_whats_next_with_its_season_and_episode():
    from app.broadcaster import Broadcaster

    ctx = SimpleNamespace(broken=SimpleNamespace(is_broken=lambda key: False))
    b = Broadcaster(ctx, 1)  # type: ignore[arg-type]
    here = Slot(episode("1"), 0, 0, 0, 60 * S)

    def card(following):
        station = SimpleNamespace(
            locate=lambda at: Slot(following, 0, 1, at, at + 1),
            era_of=lambda slot: SimpleNamespace(special=None, start_ms=None),
        )
        return b._up_next(station, here)

    assert card(episode("2")) == ["UP NEXT", "Show", "Season 1, Episode 2 \u00b7 Ep 2"]
    assert card(movie("3")) == ["UP NEXT", "Movie 3", "1990"]
    assert card(Item(0, 0, 60 * S, "4", "movie", "No Year")) == ["UP NEXT", "No Year", ""]


@needs_ffmpeg
def test_measured_text_matches_what_ffmpeg_draws():
    """The card fits text by measuring it: the measurements must match the
    font ffmpeg draws with (DejaVu Sans, as in StationPlay's image)."""
    import subprocess

    from app import ffmpeg as ffm

    for size in (27, 55):
        for text in ("The Muppet Christmas Carol", "WWW MMM www", "It's 12:30 — 100%"):
            graph = f"color=c=black:s=1600x100:d=0.1,{ffm._text(text, 0, 20, size, 'white')}"
            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", graph, "-frames:v", "1",
                 "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                capture_output=True, check=True,
            ).stdout  # fmt: skip
            drawn = max(x for x in range(1600) if any(raw[y * 1600 + x] > 40 for y in range(100)))
            assert abs(drawn + 1 - ffm.text_width(text, size)) <= 0.04 * ffm.text_width(text, size)


@needs_ffmpeg
def test_long_titles_stay_on_the_card(tmp_path):
    """Rendered for real, with and without a logo: nothing runs off the
    right-hand side, and nothing is cut short."""
    import subprocess

    from app import ffmpeg as ffm

    settings = Settings(plex_url="", plex_token="", video_width=1280, video_height=720)
    logo = str(Path(ffm.__file__).parent / "logos" / "christmas-wreath.png")
    lines = [
        "UP NEXT",
        "Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb",
        "The One Where Everybody Finds Out About Monica and Chandler",
    ]
    for card_logo in (logo, None):
        args = ffm.card_command(settings, 0.2, 0, 0.2, "Kubrick Nights", card_logo, lines)
        ts = subprocess.run(args, capture_output=True, check=True).stdout
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", "pipe:0", "-frames:v", "1",
             "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            input=ts, capture_output=True, check=True,
        ).stdout  # fmt: skip
        text_right = max(
            x for x in range(1280) if any(raw[y * 1280 + x] > 120 for y in range(0, 720, 2))
        )
        assert text_right < 1280 - 1280 * 0.05 + 2, text_right
        drawn = " ".join(
            a.split("text='")[1].split("'")[0]
            for a in args[args.index("-i") + 1].split("drawtext=")[1:]
        )
        assert "…" not in drawn and "Monica" in drawn and "Bomb" in drawn


@needs_ffmpeg
def test_the_corner_logo_goes_in_the_corner_chosen(media):
    """Rendered for real: the mark is in its own corner and no other;
    bottom-right (the default) is where it always was."""
    import subprocess

    from app import ffmpeg as ffm

    settings = Settings(plex_url="", plex_token="", video_width=640, video_height=360)
    logo = str(Path(ffm.__file__).parent / "logos" / "classic-tv.png")
    assert ffm.Watermark().position == "bottom-right"

    def frame(mark) -> bytes:
        args = ffm.program_command(
            settings, str(media["good1"]), 2, 0.3, 0, 1, 0, "x", watermark=mark
        )
        ts = subprocess.run(args, capture_output=True, check=True).stdout
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-i", "pipe:0", "-frames:v", "1",
             "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            input=ts, capture_output=True, check=True,
        ).stdout  # fmt: skip

    def changed(a: bytes, b: bytes, corner: str) -> int:
        vertical, horizontal = corner.split("-")
        ys = range(90) if vertical == "top" else range(270, 360)
        xs = range(120) if horizontal == "left" else range(520, 640)
        return sum(1 for y in ys for x in xs if abs(a[y * 640 + x] - b[y * 640 + x]) > 8)

    plain = frame(None)
    for corner in ffm.WATERMARK_POSITIONS:
        marked = frame(ffm.Watermark(logo=logo, position=corner))
        where = {c: changed(plain, marked, c) for c in ffm.WATERMARK_POSITIONS}
        assert where[corner] > 200, (corner, where)
        # Elsewhere, at most the odd pixel the encoder puts differently.
        assert all(n < where[corner] / 10 for c, n in where.items() if c != corner), (corner, where)
    for corner in ffm.WATERMARK_POSITIONS:
        text = ffm._watermark(settings, ffm.Watermark(text="Hits", position=corner))[1]
        left, top = corner.endswith("left"), corner.startswith("top")
        assert (":x='22+" in text) == left and (":y='18+" in text) == top, (corner, text)


@needs_ffmpeg
def test_the_corner_logo_can_be_all_white(media):
    """White: the logo's light parts solid white, its dark parts faint, with
    a soft dark edge; in colour it's as before. Both work with "at the start"."""
    import subprocess

    from app import ffmpeg as ffm

    settings = Settings(plex_url="", plex_token="", video_width=640, video_height=360)
    logo = str(Path(ffm.__file__).parent / "logos" / "number-1-modern.png")  # a red badge

    def frame(mark) -> bytes:
        args = ffm.program_command(
            settings, str(media["good1"]), 2, 0.3, 0, 1, 0, "x", watermark=mark
        )
        ts = subprocess.run(args, capture_output=True, check=True).stdout
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-i", "pipe:0", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            input=ts, capture_output=True, check=True,
        ).stdout  # fmt: skip

    def corner(img: bytes):
        """The pixels of the bottom-right corner."""
        return [
            (img[(y * 640 + x) * 3 : (y * 640 + x) * 3 + 3])
            for y in range(290, 340)
            for x in range(550, 610)
        ]

    plain, colour, white = (
        corner(frame(m))
        for m in (None, ffm.Watermark(logo=logo), ffm.Watermark(logo=logo, style="white"))
    )

    def changed(px):
        return [
            p
            for p, q in zip(px, plain, strict=True)
            if sum(abs(a - b) for a, b in zip(p, q, strict=True)) > 30
        ]

    def colourful(px):
        return sum(max(p) - min(p) for p in px) / max(1, len(px))

    assert len(changed(colour)) > 400 and len(changed(white)) > 400
    assert colourful(changed(white)) < colourful(changed(colour)) / 2  # no red left
    source = ffm._watermark(settings, ffm.Watermark(logo=logo, style="white", until_s=30))[0]
    assert "geq=" in source and "fade=t=out" in source and source.endswith("[wm]")
    frame(ffm.Watermark(logo=logo, style="white", until_s=30))  # draws without an error


def test_a_mark_shown_at_the_start_covers_the_first_30_seconds():
    from app import ffmpeg as ffm
    from app.broadcaster import _mark_from

    start = ffm.Watermark(text="Hits", until_s=30)
    assert _mark_from(start, 0).until_s == 30  # the program's start
    assert _mark_from(start, 12).until_s == 18  # a part that starts 12s in
    assert _mark_from(start, 29) is None  # too little left to bother
    assert _mark_from(start, 45) is None
    always = ffm.Watermark(text="Hits")
    assert _mark_from(always, 45) is always and _mark_from(None, 0) is None
    settings = Settings(plex_url="", plex_token="", video_width=1280, video_height=720)
    source, put_on = ffm._watermark(settings, ffm.Watermark(logo="/l/x.png", until_s=30))
    assert "fade=t=out:st=29.00:d=1.00:alpha=1" in source and "enable='lt(t,30.00)'" in put_on


@needs_ffmpeg
def test_a_mark_at_the_start_fades_away_and_the_program_carries_on(media, tmp_path):
    import subprocess

    from app import ffmpeg as ffm

    from .test_e2e import media_seconds

    settings = Settings(plex_url="", plex_token="", video_width=640, video_height=360)
    logo = str(Path(ffm.__file__).parent / "logos" / "classic-tv.png")

    def play(mark, name: str) -> Path:
        args = ffm.program_command(
            settings, str(media["good1"]), 1, 6, 0, 6, 0, "x", watermark=mark
        )
        out = tmp_path / f"{name}.ts"
        out.write_bytes(subprocess.run(args, capture_output=True, check=True).stdout)
        return out

    def corner(path: Path, at: float) -> bytes:
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
             "-vf", "crop=110:50:520:300", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, check=True,
        ).stdout  # fmt: skip

    def differs(a: Path, b: Path, at: float) -> int:
        return sum(1 for x, y in zip(corner(a, at), corner(b, at), strict=True) if abs(x - y) > 8)

    plain = play(None, "plain")
    for n, mark in enumerate(
        (ffm.Watermark(logo=logo, until_s=3), ffm.Watermark(text="Hits", until_s=3))
    ):
        marked = play(mark, f"marked{n}")
        assert differs(marked, plain, 1.0) > 40, mark  # there at first
        assert differs(marked, plain, 4.5) < 5, mark  # gone after 3 seconds (faded over the last)
        assert abs(media_seconds(marked) - media_seconds(plain)) < 0.05  # the program plays on
