"""Unit tests for the pure pieces: schedule math, replacements, the broken
list, stream stitching, tuner endpoints and source resolution."""

from __future__ import annotations

import itertools
import json
import logging
import os
import random
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import broken as broken_mod
from app import sources
from app.broken import BrokenFiles
from app.config import Settings, _path_mappings
from app.db import Item
from app.hdhr import device_id_valid, new_device_id, xmltv
from app.library import Library
from app.main import create_app, data_dir_problem
from app.plex import PlexClient, to_item
from app.replacement import pick_replacement
from app.schedule import (
    StationSchedule,
    build_playlist,
    show_key,
    shuffle_spread,
)
from app.sources import MediaAccess, local_candidates, resolve_source
from app.tsstitch import TsStitcher, count_adts_frames
from app.updates import compare

from .fakeplex import FakePlex
from .helpers import LegacyChannel, Schedule, add_again, like_plex

MIN = 60_000


def locate(channel, items, at_ms):
    return Schedule(channel, items).locate(at_ms)


def slots_between(channel, items, from_ms, to_ms):
    return Schedule(channel, items).between(from_ms, to_ms)


def ep(key: str, show: str, season: int, episode: int, minutes: float = 22) -> Item:
    return Item(
        position=0,
        start_ms=0,
        duration_ms=int(minutes * MIN),
        rating_key=key,
        kind="episode",
        title=f"{show} {season}x{episode}",
        show_title=show,
        show_key=f"show-{show}",
        season=season,
        episode=episode,
    )


def movie(key: str, title: str, minutes: float = 100) -> Item:
    return Item(0, 0, int(minutes * MIN), key, "movie", title, year=1990)


def channel(items: list[Item], epoch_ms: int = 0) -> LegacyChannel:
    return LegacyChannel(1, 5, "Test", "rotate", [], epoch_ms, sum(i.duration_ms for i in items), 0)


# Schedule -----------------------------------------------------------------


def test_rotate_interleaves_shows_in_episode_order():
    items = [
        ep("a2", "A", 1, 2),
        ep("b1", "B", 1, 1),
        ep("a1", "A", 1, 1),
        ep("a3", "A", 2, 1),
        ep("b2", "B", 1, 2),
    ]
    playlist = build_playlist(items, "rotate")
    assert [i.rating_key for i in playlist] == ["a1", "b1", "a2", "b2", "a3"]
    assert [i.start_ms for i in playlist] == [0, 22 * MIN, 44 * MIN, 66 * MIN, 88 * MIN]


def _longest_run(items) -> int:
    keys = [show_key(i) for i in items]
    return max((len(list(g)) for _, g in itertools.groupby(keys)), default=0)


def test_shuffle_never_plays_a_show_more_than_twice_in_a_row():
    rng = random.Random(7)
    for trial in range(500):
        counts = [rng.randint(1, 30) for _ in range(rng.randint(2, 6))]
        pool = [ep(f"{s}-{i}", f"S{s}", 1, i) for s, c in enumerate(counts) for i in range(c)]
        biggest = max(counts)
        if biggest > 2 * (sum(counts) - biggest + 1):
            continue  # one show dominates; no arrangement can avoid runs
        out = shuffle_spread(pool, random.Random(trial))
        assert sorted(i.rating_key for i in out) == sorted(i.rating_key for i in pool)
        assert _longest_run(out) <= 2, (counts, [show_key(i) for i in out])


def _shuffled_station(station_id: int = 9):
    items = build_playlist(
        [ep(f"a{n}", "Cartoon A", 1, n, 7) for n in range(12)]
        + [ep(f"b{n}", "Cartoon B", 1, n, 11) for n in range(9)]
        + [ep(f"c{n}", "Sitcom C", 1, n, 22) for n in range(10)]
        + [ep(f"a{n}", "Cartoon A", 1, n, 7) for n in range(3)],  # duplicates are dropped
        "shuffle",
    )
    ch = LegacyChannel(
        station_id, 3, "Station 3", "shuffle", [], 0, sum(i.duration_ms for i in items), 555
    )
    return ch, items


def test_shuffle_rules_hold_across_passes_and_days():
    ch, items = _shuffled_station()
    assert len(items) == 31
    slots = list(slots_between(ch, items, 0, 14 * 24 * 60 * MIN))
    assert _longest_run([s.item for s in slots]) <= 2
    assert all(a.item.rating_key != b.item.rating_key for a, b in itertools.pairwise(slots))
    # Real lengths, back to back: no padding to fixed time slots
    assert all(a.end_ms == b.start_ms for a, b in itertools.pairwise(slots))
    assert {s.duration_ms for s in slots} == {7 * MIN, 11 * MIN, 22 * MIN}
    # Every pass plays each program exactly once, in a new order each time
    passes = {}
    for s in slots:
        passes.setdefault(s.cycle, []).append(s.item.rating_key)
    full = [order for order in passes.values() if len(order) == 31]
    assert all(sorted(o) == sorted(i.rating_key for i in items) for o in full)
    assert len({tuple(o) for o in full}) == len(full)


def test_shuffle_keeps_repeats_apart_where_passes_meet():
    ch, items = _shuffled_station(station_id=10)
    slots = list(slots_between(ch, items, 0, 20 * 24 * 60 * MIN))
    keys = [s.item.rating_key for s in slots]
    window = max(3, min(len(items) // 3, 12))
    for n, key in enumerate(keys):
        assert key not in keys[n + 1 : n + 1 + window], (n, key)


def test_shuffle_rules_hold_on_many_random_stations():
    rng = random.Random(2026)
    checked = 0
    for sid in range(80):
        counts = [rng.randint(1, 20) for _ in range(rng.randint(2, 6))]
        biggest = max(counts)
        if biggest > 2 * (sum(counts) - biggest):
            continue  # impossible when passes follow each other forever
        pool = [
            ep(f"{s}-{i}", f"S{s}", 1, i, rng.choice([7, 11, 22]))
            for s, c in enumerate(counts)
            for i in range(c)
        ]
        items = build_playlist(pool, "shuffle")
        ch = LegacyChannel(
            300 + sid, 1, "x", "shuffle", [], 0, sum(i.duration_ms for i in items), sid
        )
        schedule = Schedule(ch, items)
        slot = schedule.locate(0)
        slots = []
        for _ in range(len(items) * 5):
            slots.append(slot)
            slot = schedule.after(slot)
        assert _longest_run([s.item for s in slots]) <= 2, counts
        keys = [s.item.rating_key for s in slots]
        window = max(3, min(len(items) // 3, 12)) if len(items) >= 8 else 1
        assert not any(k in keys[n + 1 : n + 1 + window] for n, k in enumerate(keys)), counts
        checked += 1
    assert checked > 50


def test_shuffle_varies_what_airs_at_the_same_time_each_day():
    ch, items = _shuffled_station()
    at_seven = [
        locate(ch, items, day * 24 * 60 * MIN + 19 * 60 * MIN).item.rating_key for day in range(14)
    ]
    assert len(set(at_seven)) >= 10


def test_schedule_is_the_same_after_a_restart():
    ch, items = _shuffled_station()
    first = [s.item.rating_key for s in Schedule(ch, items).between(0, 2 * 24 * 60 * MIN)]
    again = [s.item.rating_key for s in Schedule(ch, items).between(0, 2 * 24 * 60 * MIN)]
    assert first == again


def test_locate_loops_and_reports_wall_clock_slot():
    playlist = build_playlist([ep("1", "A", 1, 1, 30), ep("2", "A", 1, 2, 60)], "rotate")
    ch = channel(playlist, epoch_ms=1_000_000)
    slot = locate(ch, playlist, 1_000_000 + 45 * MIN)
    assert slot.item.rating_key == "2"
    assert (slot.start_ms, slot.end_ms) == (1_000_000 + 30 * MIN, 1_000_000 + 90 * MIN)
    # One full loop later: same item, shifted by the loop length
    later = locate(ch, playlist, 1_000_000 + 90 * MIN + 45 * MIN)
    assert later.item.rating_key == "2" and later.start_ms == slot.start_ms + 90 * MIN
    # Before the epoch still works (modular arithmetic)
    assert locate(ch, playlist, 1_000_000 - 1).item.rating_key == "2"


def test_guide_slots_are_contiguous():
    playlist = build_playlist([ep(str(n), "A", 1, n, 20 + n) for n in range(1, 6)], "rotate")
    ch = channel(playlist, epoch_ms=0)
    slots = list(slots_between(ch, playlist, 7 * MIN, 7 * MIN + 24 * 60 * MIN))
    assert slots[0].start_ms <= 7 * MIN < slots[0].end_ms
    for a, b in itertools.pairwise(slots):
        assert a.end_ms == b.start_ms
    assert slots[-1].end_ms >= 7 * MIN + 24 * 60 * MIN


def test_empty_channel_has_no_slot():
    assert locate(channel([]), [], 123) is None


# Replacements -------------------------------------------------------------


def test_replacement_prefers_same_show_and_long_enough():
    failed = ep("x", "A", 1, 1, 22)
    candidates = [ep("short", "A", 1, 2, 10), ep("other", "B", 1, 1, 30), ep("same", "A", 1, 3, 23)]
    pick = pick_replacement(candidates, failed, required_ms=22 * MIN, excluded=set(), seed=1)
    assert pick.rating_key == "same"


def test_replacement_falls_back_to_other_shows_then_movies():
    failed = ep("x", "A", 1, 1, 22)
    assert (
        pick_replacement(
            [ep("b", "B", 1, 1, 30), movie("m", "M")], failed, 22 * MIN, set(), 1
        ).rating_key
        == "b"
    )
    assert pick_replacement([movie("m", "M")], failed, 22 * MIN, set(), 1).rating_key == "m"


def test_replacement_excludes_broken_and_itself_and_is_seeded():
    failed = ep("x", "A", 1, 1, 22)
    pool = [
        failed,
        ep("bad", "A", 1, 2),
        ep("g1", "A", 1, 3),
        ep("g2", "A", 1, 4),
        ep("g3", "A", 1, 5),
    ]
    picks = {pick_replacement(pool, failed, 22 * MIN, {"bad"}, seed=9).rating_key for _ in range(5)}
    assert len(picks) == 1 and picks <= {"g1", "g2", "g3"}
    assert pick_replacement([failed], failed, 1, set(), 1) is None


# Broken list --------------------------------------------------------------


def test_broken_list_records_persists_and_accumulates(tmp_path):
    path = tmp_path / "broken-files.json"
    store = BrokenFiles(path)
    item = ep("42", "Cheers", 3, 7)
    store.record(item, "ffmpeg failed", 5, "/media/tv/Cheers/S03E07.mkv", 1234)
    store.record(item, "file ended early", 9)
    doc = json.loads(path.read_text())
    assert "delete its entry" in doc["about"]
    [entry] = doc["files"]
    assert entry["show"] == "Cheers" and entry["season"] == 3 and entry["episode"] == 7
    assert entry["failures"] == 2 and entry["reason"] == "file ended early"
    assert entry["stations"] == [5, 9]
    assert entry["file"] == "/media/tv/Cheers/S03E07.mkv" and entry["fileSize"] == 1234
    assert BrokenFiles(path).is_broken("42")  # survives a restart


def test_broken_list_reads_entries_from_older_versions(tmp_path):
    path = tmp_path / "broken-files.json"
    path.write_text(json.dumps({"files": [{"ratingKey": "7", "title": "Old", "channels": [3]}]}))
    [entry] = BrokenFiles(path).entries()
    assert entry["stations"] == [3] and "channels" not in entry


def test_station_names_default_to_station_number(api):
    client, _fp = api
    body = {"number": 12, "sources": [{"type": "show", "ratingKey": "100"}]}
    created = client.post("/api/channels", json=body).json()
    assert created["name"] == "Station 12" and created["aspectMode"] == "fit"
    renamed = client.put(
        f"/api/channels/{created['id']}", json={**body, "name": "  Cartoon Club "}
    ).json()
    assert renamed["name"] == "Cartoon Club"
    cleared = client.put(f"/api/channels/{created['id']}", json={**body, "name": ""}).json()
    assert cleared["name"] == "Station 12"
    assert (
        client.post(
            "/api/channels", json={**body, "number": 13, "aspectMode": "squish"}
        ).status_code
        == 400
    )


def test_station_guide_covers_the_same_two_days_as_plex(api):
    client, _fp = api
    created = client.post(
        "/api/channels", json={"number": 2, "sources": [{"type": "show", "ratingKey": "100"}]}
    ).json()
    guide = client.get(f"/api/channels/{created['id']}/guide?hours=500").json()
    span = guide[-1]["start"] - guide[0]["start"]
    assert 47 * 60 * MIN <= span <= 48 * 60 * MIN
    assert client.get(f"/api/channels/{created['id']}/guide").json() == guide


def test_picture_modes_only_change_narrow_programs():
    from app import ffmpeg as ff

    s = Settings()
    fit_43 = ff._video_filter(s, aspect_mode="fit", source_aspect=4 / 3)
    stretch_43 = ff._video_filter(s, aspect_mode="stretch", source_aspect=4 / 3)
    zoom_43 = ff._video_filter(s, aspect_mode="zoom", source_aspect=4 / 3)
    stretch_wide = ff._video_filter(s, aspect_mode="stretch", source_aspect=16 / 9)
    assert "pad=" in fit_43 and "pad=" not in stretch_43 and "crop=" in zoom_43
    assert stretch_wide == ff._video_filter(s, aspect_mode="fit", source_aspect=16 / 9)
    # Squeezed-pixel sources are made square before anything else
    assert "trunc(iw*sar/2)*2" in fit_43


def test_only_episodes_get_loudness_normalization():
    from app import ffmpeg as ff

    assert "loudnorm" in ff._audio_filter(True) and "loudnorm" not in ff._audio_filter(False)


def test_broken_list_picks_up_hand_edits_and_ignores_typos(tmp_path, monkeypatch):
    monkeypatch.setattr(broken_mod, "RELOAD_INTERVAL_S", 0)
    path = tmp_path / "broken-files.json"
    store = BrokenFiles(path)
    store.record(ep("1", "A", 1, 1), "bad", 1)
    store.record(ep("2", "A", 1, 2), "bad", 1)

    doc = json.loads(path.read_text())
    doc["files"] = [f for f in doc["files"] if f["ratingKey"] != "1"]
    path.write_text(json.dumps(doc))
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert not store.is_broken("1") and store.is_broken("2")

    path.write_text("{ oops")
    os.utime(path, (time.time() + 10, time.time() + 10))
    assert store.is_broken("2")  # kept the previous list

    path.unlink()
    assert store.keys() == set()


# Stream stitching ------------------------------------------------------------


def ts_packet(pid: int, cc: int, payload: bool = True) -> bytes:
    flags = (0x10 if payload else 0x20) | cc
    return bytes([0x47, (pid >> 8) & 0x1F, pid & 0xFF, flags]) + bytes(184)


def test_stitcher_renumbers_counters_across_programs():
    st = TsStitcher()
    first = b"".join(ts_packet(0x100, n) for n in range(5))
    second = b"".join(ts_packet(0x100, n) for n in range(3))  # new ffmpeg restarts at 0
    out = st.feed(first[:300]) + st.feed(first[300:]) + st.feed(second)
    ccs = [out[i + 3] & 0x0F for i in range(0, len(out), 188)]
    assert ccs == [0, 1, 2, 3, 4, 5, 6, 7]


def test_stitcher_keeps_counter_on_adaptation_only_packets_and_wraps():
    st = TsStitcher()
    out = st.feed(
        b"".join(ts_packet(0x101, 0) for _ in range(17)) + ts_packet(0x101, 0, payload=False)
    )
    ccs = [out[i + 3] & 0x0F for i in range(0, len(out), 188)]
    assert ccs[:16] == list(range(16)) and ccs[16] == 0 and ccs[17] == 0


def adts_frame(payload_len: int = 6) -> bytes:
    length = 7 + payload_len
    header = bytes(
        [
            0xFF,
            0xF1,
            0x4C,
            0x80 | (length >> 11),
            (length >> 3) & 0xFF,
            ((length & 7) << 5) | 0x1F,
            0xFC,
        ]
    )
    return header + bytes(payload_len)


def test_counts_bundled_aac_frames():
    assert count_adts_frames(adts_frame() * 13) == 13
    assert count_adts_frames(b"") == 1


def pes_packet(pid: int, stream_id: int, pts: int, payload: bytes) -> bytes:
    """One TS packet starting a PES packet with a PTS."""
    pts_bytes = bytes(
        [
            0x21 | ((pts >> 29) & 0x0E),
            (pts >> 22) & 0xFF,
            0x01 | ((pts >> 14) & 0xFE),
            (pts >> 7) & 0xFF,
            0x01 | ((pts << 1) & 0xFE),
        ]
    )
    pes = b"\x00\x00\x01" + bytes([stream_id]) + b"\x00\x00\x80\x80\x05" + pts_bytes + payload
    stuffing = 184 - len(pes)
    af = bytes([stuffing - 1, 0x00]) + b"\xff" * (stuffing - 2)
    return bytes([0x47, 0x40 | (pid >> 8), pid & 0xFF, 0x30]) + af + pes


def test_stitcher_measures_end_of_bundled_silent_audio():
    st = TsStitcher()
    st.begin_segment(100.0)
    base = 100 * 90_000 + 124_080
    st.feed(pes_packet(0x100, 0xE0, base + 1920, b"video"))
    st.feed(pes_packet(0x101, 0xC0, base, adts_frame() * 10))  # 10 bundled frames
    st.end_segment()
    assert st.segment_start == base
    assert st.segment_end == base + 10 * 1920


def test_a_program_with_no_picture_sends_nothing():
    """A program's output is held until its picture starts. One that ends
    with sound and no picture (FFmpeg 7 pads the sound of a file that ends
    just as it starts) sends nothing: its sound would leave a hole in the
    picture, with the next program starting after it."""
    st = TsStitcher()
    st.begin_segment(100.0)
    base = 100 * 90_000
    sound = [pes_packet(0x101, 0xC0, base + n * 1920, adts_frame()) for n in range(30)]
    assert b"".join(st.feed(p) for p in [ts_packet(0x0, 0), *sound]) == b""
    st.flush_partial()
    st.end_segment()
    assert st.segment_start is None and st.segment_end is None

    # A program that does have a picture sends everything, in order, from
    # its first packet, and its counters carry on from what was sent.
    st.begin_segment(100.0)
    picture = pes_packet(0x100, 0xE0, base + 3003, b"video")
    early = b"".join(st.feed(p) for p in [ts_packet(0x0, 0), *sound[:3]])
    assert early == b""
    out = st.feed(picture) + st.feed(sound[3])
    st.end_segment()
    sent = [ts_packet(0x0, 0), *sound[:3], picture, sound[3]]
    assert len(out) == 188 * len(sent)
    for n, packet in enumerate(sent):
        got = out[n * 188 : (n + 1) * 188]
        assert got[:3] == packet[:3] and got[4:] == packet[4:]
    assert [out[n * 188 + 3] & 0x0F for n in (0, 1, 2, 3, 5)] == [0, 0, 1, 2, 3]
    assert st.segment_start == base and st.segment_end == base + 4 * 1920


# Tuner endpoints & guide ------------------------------------------------------


def test_device_ids_validate():
    ids = {new_device_id() for _ in range(200)}
    assert len(ids) == 200 and all(device_id_valid(i) for i in ids)
    assert not device_id_valid("Tuner") and not device_id_valid("123456789")


def test_xmltv_is_well_formed_and_lists_episode_numbers():
    import xml.etree.ElementTree as ET

    playlist = build_playlist(
        [ep("1", "M*A*S*H & Co", 2, 3, 30), movie("2", "Jaws <1975>")], "rotate"
    )
    ch = channel(playlist)
    station = StationSchedule([Schedule(ch, playlist)])
    doc = ET.fromstring(xmltv([(ch, station)], "http://h:3310", 0, 6 * 3600 * 1000))
    progs = doc.findall("programme")
    assert progs and progs[0].get("channel") == "5"
    episode = next(p for p in progs if p.findtext("category") == "Series")
    assert episode.findtext("title") == "M*A*S*H & Co"
    assert episode.findtext("sub-title") == "M*A*S*H & Co 2x3"
    assert episode.find("episode-num[@system='xmltv_ns']").text == "1.2."
    assert any(
        p.findtext("category") == "Movie" and p.findtext("title") == "Jaws <1975>" for p in progs
    )


def test_odd_details_in_plex_never_spoil_the_guide():
    """Programs whose details in Plex are odd (stray control characters,
    half a character, no title, an episode 0, a nonsense year) still come
    out as programs Plex can read."""
    import xml.etree.ElementTree as ET
    from dataclasses import replace

    odd = [
        replace(ep("1", "Tuxedo\x0b Tales", 1, 23), show_key="91", summary="A bell\x07 rings.\x1f"),
        replace(ep("2", "Cartoons", 1, 0), title=""),  # an episode 0 with no title
        replace(ep("3", "", 2, 4), title="Only the episode\ud83d"),
        replace(movie("4", ""), year=0),
        replace(ep("5", "Specials?", 1, 1), season=None),
    ]
    playlist = build_playlist(odd, "rotate")
    ch = channel(playlist)
    station = StationSchedule([Schedule(ch, playlist)])
    text = xmltv([(ch, station)], "http://h:3310", 0, 6 * 3600 * 1000)
    text.encode("utf-8")  # (half a character couldn't be sent at all)
    progs = {p.findtext("title"): p for p in ET.fromstring(text).findall("programme")}
    assert progs["Tuxedo Tales"].findtext("desc") == "A bell rings."
    cartoon = progs["Cartoons"]
    assert cartoon.find("sub-title") is None  # no empty sub-title
    assert cartoon.find("episode-num[@system='xmltv_ns']") is None  # no "0.-1."
    assert cartoon.find("episode-num[@system='onscreen']").text == "S01E00"
    assert progs["Only the episode"].findtext("sub-title") == "Only the episode"
    assert progs["Untitled"].find("date") is None
    assert progs["Specials?"].find("episode-num") is None
    for prog in progs.values():
        for num in prog.findall("episode-num[@system='xmltv_ns']"):
            assert "-" not in num.text


def test_plex_items_skip_specials_and_items_without_duration():
    base = {
        "ratingKey": "1",
        "type": "episode",
        "title": "t",
        "grandparentTitle": "S",
        "grandparentRatingKey": "9",
        "index": 1,
    }
    assert to_item({**base, "parentIndex": 0, "duration": 60000}) is None
    assert to_item({**base, "parentIndex": 1}) is None
    item = to_item({**base, "parentIndex": 1, "duration": 60000})
    assert item and item.show_key == "9" and item.season == 1


def test_plex_tokens_never_reach_the_broken_list(tmp_path):
    store = BrokenFiles(tmp_path / "b.json")
    store.record(
        ep("1", "A", 1, 1),
        "cannot open file: http://plex:32400/library/parts/1/file.mkv?X-Plex-Token=SECRET123: I/O error",
        1,
    )
    text = (tmp_path / "b.json").read_text()
    assert "SECRET123" not in text and "X-Plex-Token=<hidden>" in text


def test_path_mappings():
    s = Settings(path_mappings=_path_mappings("/data/media:/media; /other:/mnt/other"))
    assert s.map_path("/data/media/tv/x.mkv") == "/media/tv/x.mkv"
    assert s.map_path("/data/mediax/y.mkv") == "/data/mediax/y.mkv"
    assert s.map_path("/other/z.mkv") == "/mnt/other/z.mkv"


# Telling what changed in Plex ---------------------------------------------------


def test_programs_plex_has_under_new_keys_are_the_same_programs():
    """Plex adding a show or movie again gives it new keys: nothing's added
    or removed, though the station must follow the new keys."""
    old = [ep("1", "A", 1, 1), ep("2", "A", 1, 2), movie("9", "Film")]
    new = [ep("11", "A", 1, 1), ep("12", "A", 1, 2), movie("19", "Film")]
    assert compare(old, new) == (0, 0, True)
    assert compare(old, old) == (0, 0, False)
    assert compare(old, [*new[:2], ep("13", "A", 1, 3)]) == (1, 1, True)


def test_programs_that_cant_be_told_apart_are_matched_by_key_alone():
    # Two shows of one name (an original and a remake): their episodes
    # have the same name and numbers.
    old = [ep("1", "The Office", 1, 1), ep("2", "The Office", 1, 1)]
    readded = [ep("11", "The Office", 1, 1), ep("12", "The Office", 1, 1)]
    assert compare(old, readded) == (2, 2, True)
    assert compare(old, [*old, ep("3", "The Office", 1, 1)]) == (1, 0, True)
    # An episode Plex numbers afresh under its key is still that episode.
    assert compare(old, [old[0], replace(old[1], episode=2)]) == (0, 0, False)


# Finding files ---------------------------------------------------------------


@pytest.fixture
def fake_plex(tmp_path) -> tuple[FakePlex, PlexClient, Path]:
    fp = FakePlex()
    fp.add_show("100", "Show")
    local = tmp_path / "ep.mkv"
    local.write_bytes(b"x")
    fp.add_episode("201", "100", 1, 1, "Pilot", str(local), 60000)
    return fp, PlexClient("http://plex.test", "token", transport=fp.transport()), local


async def test_resolve_prefers_plexs_current_file(fake_plex, tmp_path):
    _fp, client, local = fake_plex
    stale = replace(ep("201", "Show", 1, 1), file_path="/old/path.mkv")
    resolved = await resolve_source(Settings(), Library(client), stale)
    assert resolved.source == str(local) and not resolved.error


async def test_resolve_streams_from_plex_when_file_not_local(fake_plex):
    _fp, client, local = fake_plex
    local.unlink()
    resolved = await resolve_source(Settings(), Library(client), ep("201", "Show", 1, 1))
    assert resolved.source.startswith("http://plex.test/library/parts/201/")


async def test_resolve_when_plex_is_down_is_transient(fake_plex):
    fp, client, local = fake_plex
    fp.down = True
    item = replace(ep("201", "Show", 1, 1), file_path=str(local))
    assert (await resolve_source(Settings(), Library(client), item)).source == str(local)
    local.unlink()
    resolved = await resolve_source(Settings(), Library(client), item)
    assert resolved.error and resolved.transient


async def test_a_program_plex_no_longer_has_plays_from_its_file(tmp_path, monkeypatch, caplog):
    """Plex saying it has no such program (removed, or added again under a
    new key) isn't Plex being down: the file plays as it was, said once,
    and nothing waits to ask Plex again. With its file gone too, it's
    broken if Plex removed it; if Plex has it again under a new key, it
    plays from Plex's file for that (said once), or is skipped for now if
    that can't be read (the station takes the new key up at its next update)."""
    monkeypatch.setattr(sources, "_said_gone", set())
    monkeypatch.setattr(sources, "_said_moved", set())
    caplog.set_level(logging.INFO)
    fp = FakePlex()
    fp.add_show("100", "Show")
    local = tmp_path / "ep.mkv"
    local.write_bytes(b"x")
    fp.add_episode("201", "100", 1, 1, "Pilot", str(local), 60000)
    client = PlexClient("http://plex.test", "token", transport=like_plex(fp))
    item = replace(ep("201", "Show", 1, 1), file_path=str(local))
    add_again(fp, "100", "110")

    for _ in range(2):
        resolved = await resolve_source(Settings(), Library(client), item)
        assert resolved.source == str(local) and not resolved.error
    said = [r.getMessage() for r in caplog.records]
    assert sum("is no longer in Plex under its key" in m for m in said) == 1
    assert not any("failed" in m for m in said)

    local.unlink()
    for _ in range(2):
        resolved = await resolve_source(Settings(), Library(client), item)
        assert not resolved.error and "/library/parts/1201" in resolved.source  # (it's 1201 now)
    said = [r.getMessage() for r in caplog.records]
    assert sum("was re-added to Plex under a new key (1201)" in m for m in said) == 1
    del fp.episodes["1201"]["Media"][0]["Part"][0]["key"]  # (its file can't be read now)
    resolved = await resolve_source(Settings(), Library(client), item)
    assert resolved.error == sources.ADDED_AGAIN and resolved.transient
    fp.remove("1201")
    resolved = await resolve_source(Settings(), Library(client), item)
    assert resolved.error == sources.REMOVED and not resolved.transient  # broken: replaced on air


async def test_resolve_finds_files_under_a_different_mount_automatically(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    media = tmp_path / "media"
    (media / "TV" / "Show").mkdir(parents=True)
    for n in (1, 2):
        (media / "TV" / "Show" / f"S01E0{n}.mkv").write_bytes(b"x")
        # Plex's container sees the library under /data/media
        fp.add_episode(
            str(200 + n), "100", 1, n, f"Ep {n}", f"/data/media/TV/Show/S01E0{n}.mkv", 60000
        )
    client = PlexClient("http://plex.test", "token", transport=fp.transport())
    settings = Settings(media_dir=str(media))
    access = MediaAccess()

    first = await resolve_source(settings, Library(client), ep("201", "Show", 1, 1), access)
    assert first.source == str(media / "TV/Show/S01E01.mkv")
    assert access.learned == {"/data/media": str(media)}
    second = await resolve_source(settings, Library(client), ep("202", "Show", 1, 2), access)
    assert second.source == str(media / "TV/Show/S01E02.mkv")
    assert (access.direct, access.via_plex) == (2, 0)


async def test_resolve_falls_back_to_plex_when_media_isnt_mounted(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Ep", "/data/media/TV/Show/S01E01.mkv", 60000)
    client = PlexClient("http://plex.test", "token", transport=fp.transport())
    access = MediaAccess()
    resolved = await resolve_source(
        Settings(media_dir=str(tmp_path / "nothing")),
        Library(client),
        ep("201", "Show", 1, 1),
        access,
    )
    assert resolved.source.startswith("http://plex.test/") and access.via_plex == 1


def test_candidates_try_learned_mapping_first_then_tails():
    access = MediaAccess(learned={"/data/media": "/media"})
    paths = [
        c.path
        for c in local_candidates(Settings(media_dir="/media"), access, "/data/media/TV/A/x.mkv")
    ]
    assert paths[0] == "/media/TV/A/x.mkv"
    assert paths[1] == "/data/media/TV/A/x.mkv"  # as-is
    assert "/media/A/x.mkv" in paths and "/media/x.mkv" not in paths  # never the bare filename


async def test_resolve_deleted_from_plex_is_not_transient(fake_plex):
    _fp, client, _local = fake_plex
    resolved = await resolve_source(Settings(), Library(client), ep("999", "Show", 1, 9))
    assert resolved.error and not resolved.transient


# API ---------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path):
    fp = FakePlex()
    fp.add_show("100", "Show")
    for n in range(1, 4):
        fp.add_episode(str(200 + n), "100", 1, n, f"Ep {n}", f"/x/{n}.mkv", 22 * MIN)
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=fp.transport()),
    )
    with TestClient(app) as client:
        yield client, fp


def test_channel_lifecycle(api):
    client, _fp = api
    body = {
        "number": 3,
        "name": "Reruns",
        "orderMode": "rotate",
        "sources": [{"type": "show", "ratingKey": "100"}],
    }
    created = client.post("/api/channels", json=body)
    assert created.status_code == 201, created.text
    ch = created.json()
    assert ch["itemCount"] == 3 and ch["loopMs"] == 66 * MIN and ch["now"]["title"] == "Ep 1"

    assert client.post("/api/channels", json=body).status_code == 409  # number taken
    assert (
        client.post("/api/channels", json={**body, "number": 4, "orderMode": "bogus"}).status_code
        == 400
    )

    guide = client.get(f"/api/channels/{ch['id']}/guide?hours=2").json()
    assert [g["title"] for g in guide[:4]] == ["Ep 1", "Ep 2", "Ep 3", "Ep 1"]

    renamed = client.put(f"/api/channels/{ch['id']}", json={**body, "name": "Classic"}).json()
    assert (
        renamed["name"] == "Classic" and renamed["builtAt"] == ch["builtAt"]
    )  # no rebuild for a rename

    assert client.get("/lineup.json").json()[0]["GuideName"] == "Classic"
    assert "<programme" in client.get("/xmltv.xml").text
    playlist = client.get("/channels.m3u").text
    # Pointing every app at the guide: url-tvg for most, x-tvg-url for Kodi.
    first = playlist.splitlines()[0]
    assert first.startswith("#EXTM3U") and 'url-tvg="http' in first and 'x-tvg-url="http' in first
    assert first.endswith('/guide.xml"') and client.get("/stations.m3u").text == playlist

    assert client.delete(f"/api/channels/{ch['id']}").status_code == 204
    assert client.get("/api/channels").json() == []


def test_plex_errors_are_reported_not_crashed(api):
    client, fp = api
    fp.down = True
    resp = client.post(
        "/api/channels",
        json={"number": 1, "name": "X", "sources": [{"type": "show", "ratingKey": "100"}]},
    )
    assert resp.status_code == 502 and "Plex" in resp.json()["detail"]
    assert client.get("/api/channels").json() == []
    status = client.get("/api/status").json()
    assert status["plex"]["ok"] is False


def test_broken_api_clears_entries(api, tmp_path):
    client, _fp = api
    ctx = client.app.state.ctx
    ctx.broken.record(ep("201", "Show", 1, 1), "bad", 3)
    assert [e["ratingKey"] for e in client.get("/api/broken").json()] == ["201"]
    assert client.delete("/api/broken/201").status_code == 204
    assert client.get("/api/broken").json() == []
    assert client.delete("/api/broken/201").status_code == 404


# GPU ---------------------------------------------------------------------------


def test_gpu_candidates_follow_hw_accel(tmp_path):
    from app.gpu import find_candidates

    node = tmp_path / "renderD128"
    node.write_bytes(b"")
    assert find_candidates(Settings(hw_accel="cpu", hw_device=str(node))) == ([], [])
    candidates, _ = find_candidates(Settings(hw_accel="intel", hw_device=str(node)))
    assert [(c.kind, c.device) for c in candidates] == [("vaapi", str(node))]
    _, notes = find_candidates(Settings(hw_accel="nvidia"))
    assert notes and "NVIDIA" in notes[0]


def test_gpu_permission_note_names_the_group(tmp_path):
    from app.gpu import _permission_note

    node = tmp_path / "renderD128"
    node.write_bytes(b"")
    note = _permission_note(str(node))
    assert f'"{node.stat().st_gid}"' in note and "group_add" in note


def test_gpu_switches_off_after_repeated_cpu_rescues():
    from app.ffmpeg import Encoder
    from app.gpu import GPU_STRIKES_LIMIT, GpuManager

    gpu = GpuManager(Settings(), active=Encoder("vaapi", "/dev/dri/renderD128"), state="gpu")
    for _ in range(GPU_STRIKES_LIMIT - 1):
        gpu.gpu_failed("x")
        gpu.cpu_rescued()
    gpu.gpu_succeeded()  # a clean GPU program resets the count
    for _ in range(GPU_STRIKES_LIMIT - 1):
        gpu.cpu_rescued()
    assert gpu.state == "gpu" and gpu.encoder_for(False).is_gpu
    assert not gpu.encoder_for(True).is_gpu  # a program that failed on the GPU stays on the CPU
    gpu.cpu_rescued()
    assert gpu.state == "disabled" and not gpu.encoder_for(False).is_gpu


def test_every_encoder_makes_the_same_stream_shape():
    from app import ffmpeg as ff

    for encoder in (ff.CPU, ff.Encoder("vaapi", "/dev/dri/renderD128"), ff.Encoder("nvidia")):
        args = ff.program_command(Settings(), "/x.mkv", 0, 60, 10, 0, 0, "Ch", encoder)
        joined = " ".join(args)
        assert "-g 60 -bf 0" in joined and "-profile:v high" in joined and "-level:v 4.1" in joined
    slate = " ".join(ff.slate_command(Settings(), 5, 10, 0, "Ch", None))
    assert "libx264" in slate and "vaapi" not in slate and "nvenc" not in slate


def test_data_dir_problem_explains_how_to_fix_it(tmp_path, monkeypatch):
    data = tmp_path / "data"
    assert data_dir_problem(data) is None
    assert list(data.iterdir()) == []  # the write test cleans up after itself

    blocked = tmp_path / "not-a-folder"
    blocked.write_text("")
    problem = data_dir_problem(blocked / "data")
    assert problem is not None
    assert "can't write to" in problem and "chown -R" in problem

    (data / "stationplay.db").write_text("")
    monkeypatch.setattr(os, "access", lambda path, mode: False)
    problem = data_dir_problem(data)
    assert problem is not None and "stationplay.db" in problem

    # A reset-access file made by root (sudo touch) doesn't stop StationPlay:
    # it only has to exist, and StationPlay deletes it.
    (data / "stationplay.db").unlink()
    (data / "reset-access").write_text("")
    assert data_dir_problem(data) is None


def _paging_plex(
    total: int, honour_paging: bool = True, report_total: bool = True
) -> tuple[PlexClient, list[dict]]:
    """A Plex whose TV library holds `total` shows, answered a page at a time."""
    import httpx

    shows = [
        {"ratingKey": str(n), "type": "show", "title": f"Show {n}", "leafCount": 10}
        for n in range(total)
    ]
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        requests.append(dict(params))
        batch = shows
        if honour_paging and "X-Plex-Container-Start" in params:
            start = int(params["X-Plex-Container-Start"])
            batch = shows[start : start + int(params["X-Plex-Container-Size"])]
        container: dict = {"Metadata": batch}
        if report_total:
            container["totalSize"] = total
        return httpx.Response(200, json={"MediaContainer": container})

    client = PlexClient("http://plex.test", "token", transport=httpx.MockTransport(handler))
    return client, requests


async def test_big_libraries_are_read_a_page_at_a_time():
    client, requests = _paging_plex(2500)
    shows = await client.section_items("1")
    assert [s["title"] for s in shows] == [f"Show {n}" for n in range(2500)]
    assert len(requests) == 3


async def test_a_plex_that_ignores_paging_is_read_once():
    client, requests = _paging_plex(1000, honour_paging=False, report_total=False)
    assert len(await client.section_items("1")) == 1000
    assert len(requests) == 2  # the second page brought nothing new
    client, requests = _paging_plex(2500, honour_paging=False)
    assert len(await client.section_items("1")) == 2500
    assert len(requests) == 1
