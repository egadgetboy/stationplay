"""The Intro Bumper (the card when someone tunes in) and the corner clock."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import statistics
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db, intro
from app import ffmpeg as ff
from app.config import Settings
from app.main import create_app
from app.plex import PlexClient

from .fakeplex import FakePlex
from .test_e2e import assert_clean_stream, record, start_server
from .test_e2e_breaks import colour_of, frames, make_station, solid

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
LOGOS = Path(__file__).resolve().parents[1] / "app" / "logos"
FRAME_S = 1001 / 30000


def small() -> Settings:
    return Settings(plex_url="", plex_token="", video_width=640, video_height=360)


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return json.loads(out)


# --------------------------------------------------------------- the card


def test_its_colours_come_from_the_logo():
    navy, gold, clear = bytes((20, 22, 84, 255)), bytes((236, 190, 80, 255)), bytes(4)
    dark, _, accent = intro.palette(navy * 700 + gold * 200 + clear * 100)
    r, g, b = (int(dark[i : i + 2], 16) for i in (0, 2, 4))
    assert b > r and b > g and max(r, g, b) < 60  # a deep blue background
    r, g, b = (int(accent[i : i + 2], 16) for i in (0, 2, 4))
    assert r > g > b  # a gold accent
    # A yellow logo doesn't make the background olive: it gets deep blue.
    yellow = bytes((240, 210, 40, 255))
    dark, _, accent = intro.palette(yellow * 1000)
    r, g, b = (int(dark[i : i + 2], 16) for i in (0, 2, 4))
    assert b > r and b >= g
    assert int(accent[:2], 16) > 200
    assert intro.palette(clear * 50) == intro.PLAIN_COLOURS


def test_long_text_is_fitted_and_only_cut_as_a_last_resort():
    lines, size = intro.fit("The sitcoms you grew up with", intro.MEDIUM, 600, 32, 24, 3)
    assert lines == ["The sitcoms you grew up with"] and size == 32
    lines, size = intro.fit("word " * 60, intro.MEDIUM, 300, 32, 24, 3)
    assert len(lines) == 3 and lines[-1].endswith("…") and size == 24
    for line in lines:
        assert intro.text_width(line, intro.MEDIUM, size) <= 300


def test_every_length_has_four_different_sounds():
    for length in (3, 5, 10, 15):
        sounds = intro.sounds(length)
        assert len(sounds) == 4
        assert len({s.clicks for s in sounds}) == 4  # each flips the dial its own way
        for s in sounds:
            assert s.path.is_file()
            assert s.clicks[0] == 0 and list(s.clicks) == sorted(s.clicks)
            assert s.clicks[-1] < length
            assert all(0 <= a < b <= length for a, b in s.static)
    assert intro.sounds(7) == [] and intro.sound(7) is None


def test_the_static_never_hides_the_card():
    s = intro.sounds(15)[0]
    levels = [intro.snow(15, s.clicks, s.static, n / 30) for n in range(15 * 30)]
    assert levels[0] > 0.4  # a flash of static as it starts
    assert max(levels[10:]) <= 0.22  # then a light layer the card reads through


@needs_ffmpeg
@pytest.mark.parametrize("logo", ["night-reel", None])
def test_the_bumper_is_drawn_with_its_sound(tmp_path, logo):
    settings = small()
    path = str(LOGOS / f"{logo}.png") if logo else None
    card = intro.Card(
        "Night Reel", 12, "Thrillers and late-night movies.", path, ("NOW PLAYING", "Jaws", "1975")
    )
    colours = asyncio.run(intro.colours(settings, path))
    assert colours != intro.PLAIN_COLOURS if logo else colours == intro.PLAIN_COLOURS
    subprocess.run(intro.stills_command(settings, card, colours, tmp_path), check=True)
    drawn = {p.name for p in tmp_path.glob("*.png")}
    moving = {"logo.png", "shine.png"} if logo else set()
    assert drawn == {"base.png", "title.png", "full.png"} | moving
    out = tmp_path / "preview.mp4"
    sound = intro.sounds(5)[0]
    subprocess.run(intro.preview_command(settings, 5, tmp_path, sound, out), check=True)
    info = probe(out)
    assert abs(float(info["format"]["duration"]) - 5) < 0.15
    kinds = {s["codec_type"]: s for s in info["streams"]}
    assert kinds["video"]["width"] == 640 and kinds["video"]["height"] == 360
    assert "audio" in kinds
    # The words are on the card by 2 seconds in, the logo too. This is
    # where the station's name is written (further left without a logo):
    # white letters over a background that's around 50.
    words = frames(out, "200:32:300:118" if logo else "200:32:60:118")
    assert min(y for y, _, _ in words[60:70]) > 90
    if logo:
        assert max(y for y, _, _ in frames(out, "100:100:115:118")[60:70]) > 40
    loud = subprocess.run(
        ["ffmpeg", "-i", str(out), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr  # fmt: skip
    mean = float(loud.split("mean_volume:")[1].split("dB")[0])
    assert mean > -45  # the dial being flipped


def test_short_bumpers_get_the_quick_entrances():
    assert set(intro.entrances_for(3)) == set(intro.QUICK)
    assert {"spin", "materialize", "vibrate"}.isdisjoint(intro.entrances_for(5))
    assert set(intro.entrances_for(10)) == set(intro.entrances_for(15)) == set(intro.ENTRANCES)
    # A card cut short (tuned in partway) moves like a shorter one.
    assert intro.entrances_for(3.6) == intro.QUICK
    assert intro.entrances_for(4.2) == intro.entrances_for(5)
    assert intro.idles_for(3.6) == ("still",) and "still" not in intro.idles_for(4.2)
    for _ in range(50):
        how = intro.motion(3)
        assert how.entrance in intro.QUICK and how.idle == "still"
        assert intro.motion(15).idle in ("gleam", "float")


@needs_ffmpeg
def test_every_way_the_logo_arrives_draws(tmp_path):
    settings = small()
    card = intro.Card("Rerun Road", 4, "Sitcoms.", str(LOGOS / "rerun-road.png"))
    subprocess.run(intro.stills_command(settings, card, intro.PLAIN_COLOURS, tmp_path), check=True)
    done: set[str] = set()
    for length in (3, 5, 10):
        idles = intro.idles_for(length)
        for n, entrance in enumerate(intro.entrances_for(length)):
            if entrance in done:
                continue
            done.add(entrance)
            out = tmp_path / f"{entrance}.mp4"
            how = intro.Motion(entrance, idles[n % len(idles)])
            subprocess.run(
                intro.preview_command(
                    settings, length, tmp_path, intro.sounds(length)[0], out, how
                ),
                check=True,
            )
            logo = frames(out, "120:120:105:108")  # the middle of the logo's square
            # A moment after its entrance the logo is there: the sign's white
            # border crosses this square.
            settled = round((intro._ENTRANCE_S[length] * 1.25 + 0.5) * 30)
            assert max(y for y, _, _ in logo[settled : settled + 15]) > 60, (length, entrance)
    assert done == set(intro.ENTRANCES)


def band_level(path: Path, start: float, end: float, freq: int) -> float:
    """How loud `freq` is between `start` and `end` seconds (mean dB)."""
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", str(start), "-to", str(end), "-i", str(path),
         "-af", f"bandpass=f={freq}:width_type=h:w=40,volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr  # fmt: skip
    return float(out.split("mean_volume:")[1].split("dB")[0])


@needs_ffmpeg
@pytest.mark.parametrize("dial", [True, False], ids=["dial", "silent"])
def test_the_last_third_lands_on_the_shows_own_sound(tmp_path, dial):
    """With the bumper's sound turned off, the show's own sound still comes
    in for the last third: it's the show, not the bumper's sound."""
    settings = small()
    show = tmp_path / "show.mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=30",
         "-f", "lavfi", "-i", "sine=f=1000:sample_rate=48000", "-t", "30",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(show)],
        check=True,
    )  # fmt: skip
    card = intro.Card("Rerun Road", 4, "Sitcoms.", str(LOGOS / "rerun-road.png"))
    subprocess.run(intro.stills_command(settings, card, intro.PLAIN_COLOURS, tmp_path), check=True)
    out = tmp_path / "landing.mp4"
    subprocess.run(
        intro.preview_command(
            settings, 9, tmp_path, intro.sounds(10)[0] if dial else None, out, intro.Motion(),
            intro.ShowAudio(str(show), 12.0, 0, False),
        ),
        check=True,
    )  # fmt: skip
    assert abs(float(probe(out)["format"]["duration"]) - 9) < 0.15
    before, after = band_level(out, 0.5, 5.5, 1000), band_level(out, 6.8, 8.8, 1000)
    assert after > before + 12, (before, after)  # the show's tone, clearly, once landed


# ------------------------------------------------------- the Station ID card


def test_there_are_fifteen_jingles():
    jingles = intro.jingles()
    assert sorted(p.name for p in jingles) == sorted(f"jingle-{n}.m4a" for n in range(1, 16))
    assert intro.jingle() in jingles


def loudness(path: Path, seconds: float) -> tuple[float, float]:
    """(Loudness in LUFS, true peak in dBTP) of the first `seconds`, faded
    out at the end as the Station ID card does."""
    fade = max(0.2, min(0.6, seconds / 6))
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-t", str(seconds), "-i", str(path), "-af",
         f"afade=t=out:st={seconds - fade}:d={fade},ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr  # fmt: skip
    loud = float(out.rsplit("I:", 1)[1].split("LUFS")[0])
    peak = float(out.rsplit("Peak:", 1)[1].split("dBFS")[0])
    return loud, peak


@needs_ffmpeg
def test_no_jingle_is_louder_than_the_programs():
    """Programs are evened out to -24 LUFS with peaks under -2 dBTP: a
    Station ID card's jingle is quieter (by a decibel at least) however
    long the card is."""
    for path in intro.jingles():
        for seconds in intro.ID_LENGTHS:
            loud, peak = loudness(path, seconds)
            assert loud <= -25 and peak <= -6, (path.name, seconds, loud, peak)


_WORDS = re.compile(
    r"drawtext=fontfile='([^']*)':text='([^']*)':expansion=none:fontsize=(\d+)"
    r":fontcolor=0x\w+:x=\d+:y=(\d+)"
)


def written(filters: list[str]) -> list[tuple[str, Path, int, int]]:
    """Each line of words a card draws: (text, font, size, y)."""
    out = []
    for f in filters:
        if m := _WORDS.match(f):
            font, text, size, y = m.groups()
            text = text.replace("\\:", ":").replace("\\\\", "\\")
            out.append((text, Path(font), int(size), int(y)))
    return out


LONG_NAME = "The Saturday Morning Cartoon Clubhouse"
LONG_SHOW = "The Remarkable and Entirely Unlikely Adventures of the Midnight Lighthouse Keepers"
LONG_EPISODE = "Season 12, Episode 104 \u00b7 The One Where Everybody Forgets Where They Parked"


@pytest.mark.parametrize(
    ("name", "now"),
    [
        ("Night Reel", ("UP NEXT", "Jaws", "1975")),
        (LONG_NAME, ("UP NEXT", LONG_SHOW, LONG_EPISODE)),
        ("Rerun Road", ("", "Stay tuned", "")),
    ],
    ids=["short", "long", "unknown"],
)
def test_the_station_id_card_keeps_its_words_on_the_card(name, now):
    """However long the names, every line fits beside the logo, the show and
    the episode take two lines each at most, and it all stays on the card,
    centred on the logo when there's room."""
    w, h = 1280, 720
    tx = round(w * 0.461)
    room = (w - tx - round(w * 0.06)) * 0.97
    middle = round(h * 0.467)
    card = intro.Card(name, 12, "", "logo.png", now, intro.IDENT)
    title, rest = intro._ident_text(card, "F2B544", tx, room, middle, round)
    lines = written(title + rest)
    for text, font, size, _ in lines:
        assert intro.text_width(text, font, size) <= room, text
    top, bottom = lines[0][3], lines[-1][3] + lines[-1][2]
    assert top >= 50 and bottom <= 690
    shows = [t for t, font, _, _ in written(rest) if font == intro.BOLD]
    details = [t for t, font, _, _ in written(rest) if font == intro.MEDIUM]
    assert 1 <= len(shows) <= 2 and len(details) <= 2
    if name == "Night Reel":
        assert len(lines) == 5 and abs((top + bottom) / 2 - middle) < 40
        assert [t for t, *_ in lines[1:]] == ["Night Reel", "UP NEXT", "Jaws", "1975"]
    if name == LONG_NAME:
        assert shows[-1].endswith("\u2026") or " ".join(shows) == LONG_SHOW


@needs_ffmpeg
@pytest.mark.parametrize("with_jingle", [True, False], ids=["jingle", "silent"])
def test_the_station_id_card_is_drawn_with_its_jingle(tmp_path, with_jingle):
    settings = small()
    path = str(LOGOS / "night-reel.png")
    card = intro.Card("Night Reel", 12, "", path, ("UP NEXT", "Jaws", "1975"), intro.IDENT)
    colours = asyncio.run(intro.colours(settings, path))
    subprocess.run(intro.stills_command(settings, card, colours, tmp_path), check=True)
    out = tmp_path / "id.mp4"
    jingle = intro.jingles()[0] if with_jingle else None
    subprocess.run(intro.ident_preview_command(settings, 5, tmp_path, jingle, out), check=True)
    info = probe(out)
    assert abs(float(info["format"]["duration"]) - 5) < 0.15
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}
    # It fades in from black and out to black, with the station's name and
    # what's up next on it in between.
    whole = [y for y, _, _ in frames(out, "640:360:0:0")]
    assert whole[0] < 20 and whole[-1] < 20 and min(whole[30:-30]) > 35
    assert min(y for y, _, _ in frames(out, "170:28:298:110")[60:120]) > 75  # Night Reel
    assert min(y for y, _, _ in frames(out, "60:22:298:192")[60:120]) > 70  # Jaws
    loud = subprocess.run(
        ["ffmpeg", "-i", str(out), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr  # fmt: skip
    mean = float(loud.split("mean_volume:")[1].split("dB")[0])
    # The jingle sits under the card, quieter than programs; off is silent.
    assert -40 < mean < -22 if with_jingle else mean < -80


@needs_ffmpeg
async def test_a_card_never_shows_an_earlier_cards_logo(tmp_path):
    """A card's pictures go in the same folder each time: the logo of an
    earlier card mustn't be left there for one with none."""
    from app.broadcaster import Broadcaster

    b = Broadcaster(SimpleNamespace(settings=small()), 1)  # type: ignore[arg-type]
    folder = tmp_path / "card"
    card = intro.Card("Night Reel", 12, logo=str(LOGOS / "night-reel.png"), kind=intro.IDENT)
    assert await b._draw_card(card, folder, 30)
    assert (folder / "logo.png").is_file() and (folder / "shine.png").is_file()
    assert await b._draw_card(replace(card, logo=None), folder, 30)
    assert {p.name for p in folder.iterdir()} == {"base.png", "title.png", "full.png"}


# ------------------------------------------------------------- on the air


def media(tmp_path: Path, seconds: float = 20) -> FakePlex:
    """A show of two episodes: yellow with a 440 Hz tone, then cyan with 660."""
    plex = FakePlex()
    plex.set_locations("1", "/data/tv")
    plex.add_show("100", "Colours")
    for n, (colour, tone) in enumerate((("yellow", 440), ("cyan", 660)), start=1):
        path = tmp_path / "media" / "tv" / "Colours" / f"{n}.mkv"
        solid(path, colour, seconds, tone)
        plex.add_episode(f"20{n}", "100", 1, n, f"Episode {n}", str(path), round(seconds * 1000))
    return plex


@needs_ffmpeg
async def test_tuning_in_starts_with_the_intro_bumper(tmp_path, caplog):
    plex = media(tmp_path)
    base, _app, _settings, srv, task = await start_server(
        tmp_path, plex, media_dir=str(tmp_path / "media")
    )
    try:
        station = await make_station(
            base, introSeconds=5, description="Colours, all day.", logo="night-reel"
        )
        assert (station["introSeconds"], station["description"]) == (5, "Colours, all day.")
        async with httpx.AsyncClient(base_url=base) as client:
            guide = (await client.get(f"/api/channels/{station['id']}/guide?hours=1")).json()
        tuned = time.time() * 1000
        data = await record(f"{base}/stream/5", 16)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "intro.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    assert "Intro Bumper couldn't" not in caplog.text
    seen = [colour_of(*f) for f in frames(out, "64:48:20:20")]  # top left: card, then show
    n = round(5 / FRAME_S)
    # The first five seconds are the card; then the show, where the schedule
    # has got to by then (the guide doesn't move).
    assert not {"yellow", "cyan"} & set(seen[: n - 3]), seen[:n]
    after = seen[n + 3]
    assert after in ("yellow", "cyan")
    playing = next(g for g in guide if g["start"] <= tuned + 5000 < g["end"])
    assert after == ("yellow" if playing["title"] == "Episode 1" else "cyan")
    # Its last third is the show's own sound (the episode's tone), which
    # carries straight on as the picture arrives.
    tone = 440 if after == "yellow" else 660
    landed = band_level(out, 3.6, 4.9, tone)
    assert landed > band_level(out, 0.3, 3.0, tone) + 10, "the show's sound didn't come in"
    assert abs(band_level(out, 5.3, 6.5, tone) - landed) < 6


@needs_ffmpeg
async def test_the_corner_clock_shows_during_programs(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    plex = media(tmp_path, 6)
    base, _app, _settings, srv, task = await start_server(
        tmp_path, plex, media_dir=str(tmp_path / "media")
    )
    try:
        station = await make_station(
            base, watermark="clock", clockFormat="24", watermarkPosition="top-right"
        )
        assert (station["watermark"], station["clockFormat"]) == ("clock", "24")
        data = await record(f"{base}/stream/5", 8)
    finally:
        srv.should_exit = True
        await task
    out = tmp_path / "clock.ts"
    out.write_bytes(data)
    assert_clean_stream(out)
    centre = frames(out, "40:40:300:160")
    corner = frames(out, "56:18:562:18")  # where the time is written
    differ = [
        abs(cy - ky) + abs(cu - ku) + abs(cv - kv)
        for (cy, cu, cv), (ky, ku, kv) in zip(centre, corner, strict=True)
        if colour_of(cy, cu, cv) in ("yellow", "cyan")
    ]
    print(sorted(differ)[:5], sorted(differ)[-5:])
    # White writing on every frame of the show (its colour moves towards white).
    assert len(differ) > 100 and min(differ) > 12


def test_the_clock_tells_the_time_each_frame_airs():
    text = ff._clock(small(), ff.Watermark(clock="12", airs_at_s=1790773919.5), 1, "top", "left")
    assert r"%{pts\:localtime\:1790773919.500\:%-I\\\:%M %p}" in text
    text = ff._clock(small(), ff.Watermark(clock="24", airs_at_s=0), 1, "bottom", "right")
    assert r"%H\\\:%M" in text and "x='w-tw-" in text and "y='h-th-" in text


@needs_ffmpeg
def test_the_clock_is_drawn(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    shots = []
    for clock in (None, "24"):
        mark = (
            ff.Watermark(clock=clock, airs_at_s=1790773919, position="top-right") if clock else None
        )
        chain = ff._video_filter(small(), watermark=mark)
        shot = tmp_path / f"{clock}.png"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x3050A0:s=640x360:r=30000/1001",
             "-vf", chain, "-frames:v", "1", "-update", "1", str(shot)],
            check=True,
        )  # fmt: skip
        corner = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(shot), "-vf", "crop=100:40:530:10",
             "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, check=True,
        ).stdout  # fmt: skip
        shots.append(sum(1 for v in corner if v > 180))  # white writing
    assert shots[0] == 0 and shots[1] > 60


# -------------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep 1", "/x/1.mkv", 22 * 60_000)
    app = create_app(
        Settings(
            plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data",
            video_width=640, video_height=360,
        ),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )  # fmt: skip
    with TestClient(app) as c:
        yield c


def new(client, number, **extra):
    body = {"number": number, "sources": [{"type": "show", "ratingKey": "100"}], **extra}
    return client.post("/api/channels", json=body)


def test_new_stations_get_what_new_stations_start_with(client, monkeypatch):
    for setting, _, value in db.STATION_SETTINGS:
        monkeypatch.setitem(db.NEW_STATION, setting, value)  # as outside the tests
    made = new(client, 1).json()
    expected = {
        "orderMode": "shuffle", "aspectMode": "fit", "skipIntros": False, "breaks": 0,
        "stationId": False, "idSeconds": 5, "idSound": True,
        "watermark": "logo", "watermarkSize": "large", "watermarkTransparency": "medium",
        "watermarkPosition": "bottom-left", "watermarkTiming": "always", "watermarkStyle": "color",
        "clockFormat": "12", "introSeconds": 10, "introSound": True, "description": "",
        "introVideo": "", "upNextSeconds": 10, "upNextSize": "large",
    }  # fmt: skip
    assert {k: made[k] for k in expected} == expected
    assert made["logo"]  # one picked from the library
    made = new(client, 2, introSeconds=0, description="  Old   favourites  ").json()
    assert (made["introSeconds"], made["description"]) == (0, "Old favourites")
    edited = client.put(
        f"/api/channels/{made['id']}",
        json={"number": 2, "sources": made["sources"], "introSeconds": 15, "watermark": "clock",
              "clockFormat": "24", "introSound": False},
    ).json()  # fmt: skip
    assert (edited["introSeconds"], edited["description"]) == (15, "Old favourites")
    assert (edited["watermark"], edited["clockFormat"], edited["introSound"]) == (
        "clock",
        "24",
        False,
    )
    assert edited["orderMode"] == made["orderMode"]  # left out: unchanged


def test_intro_and_clock_settings_are_checked(client):
    assert new(client, 1, introSeconds=7).status_code == 400
    assert new(client, 1, clockFormat="13").status_code == 400
    assert new(client, 1, idSeconds=4).status_code == 400
    assert new(client, 1, orderMode="sideways").status_code == 400
    assert new(client, 1, description="x" * 141).status_code == 422
    assert new(client, 1, introSeconds=3, watermark="clock").status_code == 201


def test_stations_from_before_1_8_keep_their_settings(tmp_path):
    """Upgrading changes no station's settings: no Intro Bumper or Up Next
    Banner, and its Station ID card ten seconds long with no jingle, as
    before."""
    path = tmp_path / "old.db"
    old = db.Database(path)
    old.create_channel(1, "One", [], order_mode="rotate", station_id=True)
    for column in (
        "intro_seconds", "intro_sound", "description", "id_seconds", "id_sound", "intro_video",
        "up_next_seconds", "up_next_size",
    ):  # fmt: skip
        old._conn.execute(f"ALTER TABLE channels DROP COLUMN {column}")
    old._conn.commit()
    old.close()
    channel = db.Database(path).get_channel_by_number(1)
    assert channel is not None
    assert (channel.intro_seconds, channel.intro_sound, channel.description) == (0, True, "")
    assert channel.intro_video == "" and not channel.has_intro
    assert (channel.station_id, channel.id_seconds, channel.id_sound) == (True, 10, False)
    assert (channel.up_next_seconds, channel.up_next_size) == (0, "large")


@needs_ffmpeg
def detail(video: Path, at_s: float, crop: str) -> float:
    """How much an area of one frame varies (a logo's edges and lettering
    vary a lot; a plain background hardly at all)."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at_s), "-i", str(video), "-frames:v", "1",
         "-vf", f"crop={crop},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return statistics.pstdev(raw)


@needs_ffmpeg
def test_the_editor_can_preview_its_cards(client, tmp_path):
    made = new(client, 4, name="Rerun Road", logo="rerun-road").json()
    station = {"channelId": made["id"], "number": 4, "name": "Rerun Road", "logo": "rerun-road"}
    for card in (
        {"description": "The sitcoms you grew up with.", "seconds": 3},  # the Intro Bumper
        {"kind": "id", "seconds": 5, "sound": False},  # the Station ID card
    ):
        resp = client.post("/api/intro/preview", json={**station, **card})
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "video/mp4"
        assert resp.content[4:8] == b"ftyp"
        # With its logo (about 50 or more here; a plain background is under 10).
        video = tmp_path / "preview.mp4"
        video.write_bytes(resp.content)
        assert detail(video, card["seconds"] - 1, "150:150:90:93") > 25, card
    preview = lambda **body: client.post("/api/intro/preview", json={"number": 4, **body})  # noqa: E731
    assert preview(seconds=0).status_code == 400
    assert preview(kind="id", seconds=15).status_code == 400  # ID cards are 3, 5 or 10
    assert preview(kind="ad", seconds=5).status_code == 422
