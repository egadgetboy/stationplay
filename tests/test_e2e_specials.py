"""Specials on the air: watched straight through, the stream never breaks.
A Feature Presentation's card plays, then the movie; a block plays its own
shows; and either way the station then carries on with the program that
was due when it began."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time

import httpx
import pytest

from app import marathons, specials

from .fakeplex import FakePlex
from .test_e2e import assert_clean_stream, ff, media_seconds, record, start_server
from .test_e2e_skipping import runs

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

CLIP_S = 4
MOVIE_S = 6
SHOWS = ("yellow", "lime")
MOVIES = {"type": "section", "key": "2", "sectionType": "movie", "title": "Movies"}


def clip(path, colour: str, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ff(
        "-f", "lavfi", "-i", f"color=c={colour}:s=640x360:r=30",
        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000", "-t", str(seconds),
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path),
    )  # fmt: skip


async def test_a_feature_presentation_airs_and_the_station_carries_on(
    tmp_path, monkeypatch, caplog
):
    from app import main, updates

    monkeypatch.setattr(updates, "MARGIN_MS", 6000)
    monkeypatch.setattr(main, "MARGIN_MS", 6000)
    d = tmp_path / "media"
    d.mkdir()
    plex = FakePlex()
    for s, colour in enumerate(SHOWS, start=1):
        clip(d / f"{colour}.mkv", colour, CLIP_S)
        plex.add_show(str(s * 100), colour.title())
        for n in (1, 2, 3):
            shutil.copy(d / f"{colour}.mkv", d / f"{colour}{n}.mkv")
            plex.add_episode(
                str(s * 100 + n), str(s * 100), 1, n, f"{colour} {n}", str(d / f"{colour}{n}.mkv"),
                CLIP_S * 1000,
            )  # fmt: skip
    plex.add_section("2", "Movies", "movie")
    clip(d / "movie.mkv", "cyan", MOVIE_S)
    plex.add_movie("501", "The Cyan Film", str(d / "movie.mkv"), MOVIE_S * 1000, 1962, "2")
    # The Feature Presentation is due 14 seconds after the station is made.
    made_at = time.time() * 1000
    monkeypatch.setattr(
        marathons,
        "weekly",
        lambda days, at, a, b: [t for t in [int(made_at + 14_000)] if a <= t < b],
    )
    caplog.set_level(logging.INFO)
    base, app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={
                    "number": 4,
                    "orderMode": "rotate",
                    "introSeconds": 0,
                    "upNextSeconds": 0,
                    "watermark": "off",
                    "featureMode": "on",
                    "featureDays": "0",
                    "featureTime": "20:00",
                    "featureSource": MOVIES,
                    "sources": [{"type": "show", "ratingKey": str(s * 100)} for s in (1, 2)],
                },
            )
            assert made.status_code == 201, made.text
            eras = app.state.ctx.db.eras(made.json()["id"])
            (feature,) = [e for e in eras if e.special]
            carry = eras[eras.index(feature) + 1]
            due_then = app.state.ctx.station(made.json()["id"]).locate(carry.start_ms)
            data = await record(f"{base}/stream/4", 36)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "feature.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    shown = [(c, s) for c, s in runs(out) if s > 0.3]
    print("\naired:", " → ".join(f"{c} {s:.1f}s" for c, s in shown))
    films = [n for n, (c, s) in enumerate(shown) if c == "cyan"]
    assert len(films) == 1, shown
    n = films[0]
    assert abs(shown[n][1] - MOVIE_S) < 1.0, shown
    # Before it, the card (in the station's colours), for its ten seconds:
    # everything back to the last of the station's programs.
    card_s, k = 0.0, n - 1
    while k >= 0 and not (shown[k][0] in SHOWS and shown[k][1] > CLIP_S - 1):
        card_s += shown[k][1]
        k -= 1
    assert k >= 0, "the recording starts after the card"
    assert abs(card_s - specials.FEATURE_CARD_MS / 1000) < 1.5, shown
    # Then the station carries on with what was due when it began.
    assert n + 1 < len(shown), "the recording ends before the station carries on"
    assert shown[n + 1][0] == SHOWS[int(due_then.item.show_key) // 100 - 1], shown
    # It was drawn (not the plain card standing in).
    assert "plain card plays instead" not in caplog.text


async def test_a_block_airs_and_the_station_carries_on(tmp_path, monkeypatch):
    from app import main, updates

    monkeypatch.setattr(updates, "MARGIN_MS", 6000)
    monkeypatch.setattr(main, "MARGIN_MS", 6000)
    d = tmp_path / "media"
    d.mkdir()
    plex = FakePlex()
    for s, colour in enumerate((*SHOWS, "magenta"), start=1):
        clip(d / f"{colour}.mkv", colour, CLIP_S)
        plex.add_show(str(s * 100), colour.title())
        for n in (1, 2, 3):
            shutil.copy(d / f"{colour}.mkv", d / f"{colour}{n}.mkv")
            plex.add_episode(
                str(s * 100 + n), str(s * 100), 1, n, f"{colour} {n}", str(d / f"{colour}{n}.mkv"),
                CLIP_S * 1000,
            )  # fmt: skip
    # The block (magenta's three episodes) is due 14 seconds after the
    # station is made, for 12 seconds.
    at = int(time.time() * 1000 + 14_000)
    monkeypatch.setattr(
        specials,
        "due",
        lambda channel, a, b: (
            [specials.Due(specials.BLOCK, at, at + 12_000, channel.blocks[0])]
            if channel.blocks and a <= at < b
            else []
        ),
    )
    base, app, _settings, srv, task = await start_server(tmp_path, plex)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            made = await client.post(
                "/api/channels",
                json={
                    "number": 4, "orderMode": "rotate", "introSeconds": 0, "upNextSeconds": 0,
                    "watermark": "off",
                    "sources": [{"type": "show", "ratingKey": str(s * 100)} for s in (1, 2)],
                    "blocks": [{
                        "name": "Magenta Hour", "days": "0,1,2,3,4,5,6", "start": "08:00",
                        "end": "09:00", "sources": [{"type": "show", "ratingKey": "300"}],
                    }],
                },
            )  # fmt: skip
            assert made.status_code == 201, made.text
            eras = app.state.ctx.db.eras(made.json()["id"])
            (block,) = [e for e in eras if e.special]
            carry = eras[eras.index(block) + 1]
            due_then = app.state.ctx.station(made.json()["id"]).locate(carry.start_ms)
            data = await record(f"{base}/stream/4", 34)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "block.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    shown = [(c, s) for c, s in runs(out) if c != "black" and s > 0.5]
    print("\naired:", " → ".join(f"{c} {s:.1f}s" for c, s in shown))
    blocks = [n for n, (c, s) in enumerate(shown) if c == "magenta"]
    assert len(blocks) == 1, shown
    n = blocks[0]
    assert abs(shown[n][1] - 3 * CLIP_S) < 1.0, shown  # (its three episodes, back to back)
    assert n + 1 < len(shown), "the recording ends before the station carries on"
    assert shown[n + 1][0] == SHOWS[int(due_then.item.show_key) // 100 - 1], shown


@pytest.mark.skipif(
    not __import__("os").environ.get("STATIONPLAY_SOAK"),
    reason="set STATIONPLAY_SOAK=1 for the long run",
)
async def test_soak_with_everything_on(tmp_path, monkeypatch, caplog):
    """Minutes of two stations with everything on: marathons, Feature
    Presentations and blocks every couple of minutes, subtitles beside and
    inside files, commercials, Station ID cards, the Up Next Banner, a
    corner clock and logo, and someone flicking to one station and away
    again and again. Both streams stay clean and on time, nothing is logged
    as a warning, nothing's marked broken, and nothing's left running."""
    import logging
    import os
    import random

    from app import main, updates

    from .test_subtitles import srt

    monkeypatch.setattr(updates, "MARGIN_MS", 6000)
    monkeypatch.setattr(main, "MARGIN_MS", 6000)
    minutes = float(os.environ.get("STATIONPLAY_SOAK_MINUTES", "8"))
    root = tmp_path / "media"
    plex = FakePlex()
    plex.set_locations("1", "/data/tv")  # (Plex's path for the TV library)
    colours = ("yellow", "lime", "cyan", "magenta", "orange", "white")
    for s, colour in enumerate(colours, start=1):
        plex.add_show(str(s * 100), colour.title())
        for n in (1, 2, 3):
            path = root / "tv" / colour.title() / f"{n}.mkv"
            path.parent.mkdir(parents=True, exist_ok=True)
            clip(path, colour, 8)
            if s == 1:  # (subtitles beside the file)
                srt(path.with_suffix(".en.srt"), [(1.0, 6.0, "Beside the file")])
            if s == 2:  # (subtitles inside it)
                inside = path.with_name(f"{n}-subs.mkv")
                ff(
                    "-i", str(path), "-i", str(srt(path.with_suffix(".srt"), [(1.0, 6.0, "Inside")])),
                    "-map", "0", "-map", "1", "-c", "copy", "-c:s", "srt",
                    "-metadata:s:s:0", "language=eng", str(inside),
                )  # fmt: skip
                path = inside
            plex.add_episode(str(s * 100 + n), str(s * 100), 1, n, f"{colour} {n}", str(path), 8000)
    plex.add_show("900", "Toons")
    for n in (1, 2, 3, 4):
        path = root / "tv" / "Toons" / f"{n}.mkv"
        clip(path, "blue", 6)
        plex.add_episode(str(900 + n), "900", 1, n, f"Toon {n}", str(path), 6000)
    for name in ("one.mp4", "two.mp4"):
        clip(root / "tv" / "commercials" / name, "red", 3)
    (root / "tv" / "commercials" / ".plexignore").write_text("*\n")
    plex.add_section("2", "Movies", "movie")
    for n in (1, 2, 3):
        path = root / "movies" / f"Film {n}.mkv"
        path.parent.mkdir(parents=True, exist_ok=True)
        clip(path, "purple", 12)
        plex.add_movie(str(500 + n), f"Film {n}", str(path), 12_000, 1950 + n, "2")

    # On station 1: a marathon, a Feature Presentation and a 30-second block
    # in turn, every 90 seconds, all the way through.
    t0 = int(time.time() * 1000)
    cycle = []
    for k in range(int(minutes * 60 / 90) + 2):
        at = t0 + 40_000 + k * 90_000
        cycle.append((("marathon", "feature", "block")[k % 3], at))

    def due(channel, a, b):
        if channel.number != 1:
            return []
        return [
            specials.Due(kind, at, at + 30_000, channel.blocks[0] if kind == "block" else None)
            for kind, at in cycle
            if a <= at < b and (kind != "block" or channel.blocks)
        ]

    monkeypatch.setattr(specials, "due", due)
    caplog.set_level(logging.INFO)
    base, app, _settings, srv, task = await start_server(tmp_path, plex, media_dir=str(root))
    try:
        async with httpx.AsyncClient(base_url=base, timeout=60) as client:
            one = await client.post("/api/channels", json={
                "number": 1, "name": "Everything", "orderMode": "rotate",
                "sources": [{"type": "show", "ratingKey": str(s * 100)} for s in range(1, 7)],
                "subtitles": "always", "breaks": 1, "stationId": True, "idSeconds": 3,
                "upNextSeconds": 3, "watermark": "clock", "introSeconds": 3,
                "marathonMode": "random", "featureMode": "on", "featureDays": "0",
                "featureTime": "20:00", "featureSource": MOVIES,
                "blocks": [{"name": "Toons", "days": "0", "start": "08:00", "end": "09:00",
                            "sources": [{"type": "show", "ratingKey": "900"}]}],
            })  # fmt: skip
            assert one.status_code == 201, one.text
            two = await client.post("/api/channels", json={
                "number": 2, "name": "Shuffled", "orderMode": "shuffle", "picture": "480p",
                "sources": [{"type": "show", "ratingKey": str(s * 100)} for s in (3, 4, 5, 6)]
                + [MOVIES],
                "subtitles": "forced", "watermark": "logo", "introSeconds": 0,
            })  # fmt: skip
            assert two.status_code == 201, two.text

        async def flick() -> int:
            """Tunes in to station 1 for a few seconds, again and again."""
            times, rng = 0, random.Random(1)
            deadline = time.monotonic() + minutes * 60 - 15
            while time.monotonic() < deadline:
                await record(f"{base}/stream/1", rng.uniform(4, 12))
                times += 1
                await asyncio.sleep(rng.uniform(1, 4))
            return times

        started = time.time()
        one_data, two_data, flicks = await asyncio.gather(
            record(f"{base}/stream/1", minutes * 60),
            record(f"{base}/stream/2", minutes * 60),
            flick(),
        )
        elapsed = time.time() - started
        eras = app.state.ctx.db.eras(one.json()["id"])
        broken = app.state.ctx.broken.entries()
    finally:
        srv.should_exit = True
        await task
    for name, data in (("one", one_data), ("two", two_data)):
        out = tmp_path / f"soak-{name}.ts"
        out.write_bytes(data)
        assert_clean_stream(out)
        assert elapsed - 5 <= media_seconds(out) <= elapsed + 20, (name, media_seconds(out))
    # Every kind due well before the end aired.
    ended = t0 + elapsed * 1000
    aired = {e.special["kind"] for e in eras if e.special and e.start_ms < ended}
    assert aired == {kind for kind, at in cycle if at < ended - 20_000}, aired
    assert flicks >= minutes * 4
    assert broken == []
    warned = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warned, warned
    # Nothing's left running.
    await asyncio.sleep(2)
    me = str(os.getpid())
    left = [
        p
        for p in os.listdir("/proc")
        if p.isdigit() and _parent(p) == me and "ffmpeg" in _command(p)
    ]
    assert not left, left


def _parent(pid: str) -> str:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[1]
    except OSError:
        return ""


def _command(pid: str) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().decode(errors="replace")
    except OSError:
        return ""
