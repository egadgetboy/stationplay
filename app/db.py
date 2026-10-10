"""SQLite storage for stations, their eras and frozen playlists.

A station's schedule is a series of eras, each a playlist frozen when it
was made, taking over from the one before at a program break. An era never
changes once saved, so the schedule (and the guide Plex has downloaded)
never shifts on its own; updates only ever add a new era that starts after
what the guide already shows.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field, fields
from functools import cached_property
from operator import attrgetter
from pathlib import Path
from typing import Any

from .languages import Choice

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    number       INTEGER NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    order_mode   TEXT    NOT NULL DEFAULT 'shuffle',
    sources      TEXT    NOT NULL DEFAULT '[]',
    epoch_ms     INTEGER NOT NULL DEFAULT 0,
    total_ms     INTEGER NOT NULL DEFAULT 0,
    built_at_ms  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS eras (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    start_ms     INTEGER,             -- NULL: from the station's beginning
    epoch_ms     INTEGER NOT NULL,
    seed         TEXT    NOT NULL,
    order_mode   TEXT    NOT NULL,
    chained      INTEGER NOT NULL DEFAULT 0,
    first_pass   TEXT,
    tail         TEXT,
    created_ms   INTEGER NOT NULL,
    reason       TEXT    NOT NULL DEFAULT '',
    added        INTEGER NOT NULL DEFAULT 0,
    removed      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS era_items (
    era_id        INTEGER NOT NULL REFERENCES eras(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    start_ms      INTEGER NOT NULL,
    duration_ms   INTEGER NOT NULL,
    rating_key    TEXT    NOT NULL,
    kind          TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    show_title    TEXT,
    show_key      TEXT,
    season        INTEGER,
    episode       INTEGER,
    year          INTEGER,
    summary       TEXT,
    file_path     TEXT,
    part_key      TEXT,
    lead_ms       INTEGER NOT NULL DEFAULT 0,
    segments      TEXT,               -- JSON [[start, end], ...] ms; NULL: all
    breaks        TEXT,               -- JSON [[file, ms], ...] played after it
    PRIMARY KEY (era_id, position)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Intro and credits markers Plex has for each program, as last asked.
CREATE TABLE IF NOT EXISTS markers (
    rating_key   TEXT PRIMARY KEY,
    duration_ms  INTEGER NOT NULL,
    markers      TEXT    NOT NULL,     -- JSON [[kind, start, end, final], ...]
    checked_ms   INTEGER NOT NULL,     -- when Plex was last asked
    first_ms     INTEGER NOT NULL      -- since when it has said this
);
-- The marathons a station has had (or has coming), for choosing the next:
-- when each was due, the show, and where it left off (its last episode's
-- season and number).
CREATE TABLE IF NOT EXISTS marathons (
    channel_id   INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    due_ms       INTEGER NOT NULL,
    show_key     TEXT    NOT NULL,
    last_season  INTEGER NOT NULL DEFAULT 0,
    last_episode INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (channel_id, due_ms)
);
-- Feature Presentations and time-of-day blocks a station has had (or has
-- coming), for choosing what's next: by kind and when each was due, what
-- it was (the film's rating key, the block's id) and, for a block, where
-- its run of programs got to (see specials.py).
CREATE TABLE IF NOT EXISTS special_runs (
    channel_id   INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    kind         TEXT    NOT NULL,
    due_ms       INTEGER NOT NULL,
    key          TEXT    NOT NULL,
    value        TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (channel_id, kind, due_ms)
);
-- Programs a station's specials draw on besides its own (a Feature
-- Presentation's films, a block's shows), as Plex last listed them: JSON
-- items, by name ("feature", "block:<id>").
CREATE TABLE IF NOT EXISTS program_sets (
    channel_id   INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    items        TEXT    NOT NULL,
    PRIMARY KEY (channel_id, name)
);
-- Logos you've uploaded (the pictures are in the data folder's logos/).
CREATE TABLE IF NOT EXISTS logos (
    id           TEXT    PRIMARY KEY,
    name         TEXT    NOT NULL,
    created_ms   INTEGER NOT NULL
);
-- What checking each program's file found (see scanner.py).
CREATE TABLE IF NOT EXISTS scans (
    rating_key   TEXT    PRIMARY KEY,
    file         TEXT    NOT NULL,     -- Plex's path to the file checked
    size         INTEGER NOT NULL DEFAULT 0,
    quick_ms     INTEGER NOT NULL DEFAULT 0,   -- when the quick check last ran
    quick        TEXT    NOT NULL DEFAULT '',  -- ok, broken, damaged or unsupported
    deep_ms      INTEGER NOT NULL DEFAULT 0,   -- when a deep scan finished
    deep_at_s    REAL    NOT NULL DEFAULT 0,   -- how far an unfinished one got
    deep         TEXT    NOT NULL DEFAULT '',  -- ok, broken or damaged
    bad_minutes  TEXT    NOT NULL DEFAULT '[]', -- JSON: minutes with glitches
    tries        INTEGER NOT NULL DEFAULT 0,   -- deep scans cut off by read errors
    note         TEXT    NOT NULL DEFAULT '',
    kept         INTEGER NOT NULL DEFAULT 0,   -- you put it back on the air
    picture_to_s REAL    NOT NULL DEFAULT 0,   -- what the deep scan found so far:
    sound_from_s REAL    NOT NULL DEFAULT -1,  -- (see ScanRecord)
    sound_to_s   REAL    NOT NULL DEFAULT -1,
    black_s      REAL    NOT NULL DEFAULT 0,
    gaps         TEXT    NOT NULL DEFAULT '[]' -- JSON: [kind, from, to]
);
-- Who can sign in to StationPlay's page (none: anyone can use it).
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password     TEXT    NOT NULL,     -- scrypt hash (see access.py)
    role         TEXT    NOT NULL,     -- admin or user
    created_ms   INTEGER NOT NULL,
    signed_in_ms INTEGER NOT NULL DEFAULT 0,
    max_stations INTEGER               -- the most stations a User may make; NULL: no limit
);
-- Who's signed in, by a hash of their browser's token.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash   TEXT    PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_ms   INTEGER NOT NULL,
    seen_ms      INTEGER NOT NULL
);
-- Browsers someone has signed in on, by a hash of a token kept in them
-- (see access.py: signing in on one from the internet never waits behind
-- strangers' wrong passwords).
CREATE TABLE IF NOT EXISTS devices (
    token_hash   TEXT    PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_ms   INTEGER NOT NULL
);
-- API tokens an Admin made, for scripts and other apps (see api.py), by a
-- hash of the token: what each may do, and whose it is (gone with them).
CREATE TABLE IF NOT EXISTS api_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash   TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    scope        TEXT    NOT NULL,     -- viewer or admin
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_ms   INTEGER NOT NULL,
    used_ms      INTEGER NOT NULL DEFAULT 0,
    expires_ms   INTEGER               -- NULL: never
);
-- Signing in and out, and changes to who can (the newest kept).
CREATE TABLE IF NOT EXISTS access_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    time_ms      INTEGER NOT NULL,
    level        TEXT    NOT NULL,
    message      TEXT    NOT NULL
);
-- Each time a station was watched (see stats.py).
CREATE TABLE IF NOT EXISTS views (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id   INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    start_ms     INTEGER NOT NULL,
    end_ms       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS views_by_end ON views (end_ms);
CREATE INDEX IF NOT EXISTS views_by_station ON views (channel_id);
-- What aired while it was: seconds watched of each show or movie, by day.
CREATE TABLE IF NOT EXISTS watched (
    channel_id   INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    day          TEXT    NOT NULL,     -- the local date, YYYY-MM-DD
    title        TEXT    NOT NULL,     -- the show, or the movie
    kind         TEXT    NOT NULL,     -- episode or movie
    seconds      REAL    NOT NULL,
    PRIMARY KEY (channel_id, day, title, kind)
);
-- Who watched, as Plex says (its Live TV sessions, see stats.py): seconds
-- of each station and show or movie, by Plex user and day.
CREATE TABLE IF NOT EXISTS user_watched (
    user_id      TEXT    NOT NULL,     -- Plex's id for the user
    user_name    TEXT    NOT NULL,     -- as Plex last named them
    channel_id   INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    day          TEXT    NOT NULL,     -- the local date, YYYY-MM-DD
    title        TEXT    NOT NULL,     -- the show, or the movie
    kind         TEXT    NOT NULL,     -- episode or movie
    seconds      REAL    NOT NULL,
    PRIMARY KEY (user_id, channel_id, day, title, kind)
);
-- Who watched stations in StationPlay's apps (see stats.py): seconds of each
-- station and show or movie, by StationPlay user and day. (Plex users' are
-- in user_watched.)
CREATE TABLE IF NOT EXISTS app_watched (
    user_id      INTEGER NOT NULL,     -- StationPlay's id for them
    user_name    TEXT    NOT NULL,     -- as they were last named
    channel_id   INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    day          TEXT    NOT NULL,     -- the local date, YYYY-MM-DD
    title        TEXT    NOT NULL,     -- the show, or the movie
    kind         TEXT    NOT NULL,     -- episode or movie
    seconds      REAL    NOT NULL,
    PRIMARY KEY (user_id, channel_id, day, title, kind)
);
-- What was played on demand in StationPlay's apps (see stats.py): plays and
-- seconds of each show or movie, by StationPlay user (0 while signing in
-- is off) and day.
CREATE TABLE IF NOT EXISTS media_watched (
    user_id      INTEGER NOT NULL,
    user_name    TEXT    NOT NULL,     -- as they were last named ('' for no one)
    day          TEXT    NOT NULL,     -- the local date, YYYY-MM-DD
    title        TEXT    NOT NULL,     -- the show, or the movie
    kind         TEXT    NOT NULL,     -- episode or movie
    plays        INTEGER NOT NULL DEFAULT 0,
    seconds      REAL    NOT NULL,
    PRIMARY KEY (user_id, day, title, kind)
);
-- Where each person is in what they watch on demand in StationPlay's apps
-- (see ondemand.py), by StationPlay user (0 while signing in is off).
CREATE TABLE IF NOT EXISTS progress (
    user_id      INTEGER NOT NULL,
    rating_key   TEXT    NOT NULL,     -- the episode or movie
    show_key     TEXT,                 -- an episode's show
    position_ms  INTEGER NOT NULL,
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    watched      INTEGER NOT NULL DEFAULT 0,
    updated_ms   INTEGER NOT NULL,
    PRIMARY KEY (user_id, rating_key)
);
CREATE INDEX IF NOT EXISTS progress_by_time ON progress (user_id, updated_ms);
-- Each person's languages in StationPlay's apps (see languages.py), by
-- StationPlay user (0 while signing in is off): their own (key ''), and
-- what they chose for a show, an episode or a movie. NULL: not chosen there.
CREATE TABLE IF NOT EXISTS languages (
    user_id      INTEGER NOT NULL,
    item_key     TEXT    NOT NULL,     -- '' for their own; or a show, episode or movie
    audio        TEXT,                 -- a language's code ("jpn")
    captions     INTEGER,              -- 1 on, 0 off
    caption_language TEXT,
    updated_ms   INTEGER NOT NULL,
    PRIMARY KEY (user_id, item_key)
);
-- Viewing Levels: what their users can see (see viewing.py). Ages are
-- ratings read as ages (ratings.py); NULL: no limit. builtin names the four
-- that come with StationPlay ('' for an Admin's own).
CREATE TABLE IF NOT EXISTS levels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    movie_age    INTEGER,
    tv_age       INTEGER,
    unrated      INTEGER NOT NULL DEFAULT 1,  -- unrated titles shown
    libraries    TEXT,                        -- JSON list of library keys; NULL: all
    builtin      TEXT    NOT NULL DEFAULT ''
);
-- Stations allowed or blocked for a user, whatever their level says.
CREATE TABLE IF NOT EXISTS user_stations (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel_id   INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    allowed      INTEGER NOT NULL,            -- 1 allowed, 0 blocked
    PRIMARY KEY (user_id, channel_id)
);
-- StationPlay's apps linked to this server (see devices.py), by a hash of
-- the key each keeps: what each is, when it was linked and last used, and
-- who linked it (their name, kept if they're removed; and from 1.27, their
-- id, linked_by_id, which is what says it's theirs).
CREATE TABLE IF NOT EXISTS linked_devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash     TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    created_ms   INTEGER NOT NULL,
    seen_ms      INTEGER NOT NULL,
    linked_by    TEXT    NOT NULL DEFAULT ''
);
-- Who's on a device's picker other than as their Show on says (see
-- devices.py): signed in there, or chosen for it by an Admin; or who took
-- themselves off.
CREATE TABLE IF NOT EXISTS device_people (
    device_id    INTEGER NOT NULL REFERENCES linked_devices(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    how          TEXT    NOT NULL,            -- 'signed-in', 'chosen' or 'removed'
    PRIMARY KEY (device_id, user_id)
);
-- Invite codes (see devices.py): one at a time for each user, by a hash.
CREATE TABLE IF NOT EXISTS invites (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    code_hash    TEXT    NOT NULL,
    expires_ms   INTEGER NOT NULL
);
-- The rating and library of each show and movie on a station, and of an
-- episode with a rating of its own (see titles.py): what decides who can
-- see a station. checked_ms: when Plex was last asked about it directly (a
-- show's rating comes only that way); 0 if never.
CREATE TABLE IF NOT EXISTS titles (
    key          TEXT PRIMARY KEY,
    kind         TEXT    NOT NULL,     -- 'movie', 'show' or 'episode'
    rating       TEXT    NOT NULL DEFAULT '',
    library      TEXT    NOT NULL DEFAULT '',
    seen_ms      INTEGER NOT NULL,
    checked_ms   INTEGER NOT NULL DEFAULT 0
);
-- Problems StationPlay's apps ran into, sent by the apps themselves (see
-- problems.py): the same one again soon after counts on the same row.
-- first_ms and last_ms are when it happened, as the app says.
CREATE TABLE IF NOT EXISTS problems (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    first_ms     INTEGER NOT NULL,
    last_ms      INTEGER NOT NULL,
    times        INTEGER NOT NULL DEFAULT 1,
    kind         TEXT    NOT NULL,
    station      INTEGER,             -- the station's number, if it was one
    title        TEXT    NOT NULL DEFAULT '',
    detail       TEXT    NOT NULL DEFAULT '',
    app          TEXT    NOT NULL DEFAULT '',
    version      TEXT    NOT NULL DEFAULT '',
    device       TEXT    NOT NULL DEFAULT '',  -- the kind of device: model, and its system
    device_name  TEXT    NOT NULL DEFAULT '',
    user_id      INTEGER,
    away         INTEGER NOT NULL DEFAULT 0,
    journal      TEXT    NOT NULL DEFAULT '',  -- the app's last lines before it (the newest's)
    lasted_ms    INTEGER NOT NULL DEFAULT 0    -- how long trouble reaching StationPlay lasted
);
CREATE INDEX IF NOT EXISTS problems_by_last ON problems (last_ms);
-- People's reports of problems in what they watch, picked from a list in
-- the apps (see reports.py).
CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    at_ms        INTEGER NOT NULL,
    day          TEXT    NOT NULL,              -- the day it was sent (for the limits)
    user_id      INTEGER,                       -- who sent it (NULL while signing in is off)
    who          TEXT    NOT NULL DEFAULT '',   -- their name, as it was
    device       TEXT    NOT NULL DEFAULT '',   -- which app on which device
    address      TEXT    NOT NULL DEFAULT '',   -- where from (the limits, while signing in is off)
    choice       TEXT    NOT NULL,
    rating_key   TEXT    NOT NULL,              -- the episode or movie
    version      TEXT    NOT NULL DEFAULT '',   -- its version's ID ('': its first)
    station      INTEGER,                       -- the station's number, if it was on one
    position_ms  INTEGER,                       -- where in it
    how          TEXT    NOT NULL DEFAULT '{}', -- JSON: how it was playing
    program      TEXT    NOT NULL DEFAULT '{}', -- JSON: what it is (show, title...)
    facts        TEXT    NOT NULL DEFAULT '[]', -- JSON: what StationPlay could tell
    state        TEXT    NOT NULL,
    note         TEXT    NOT NULL DEFAULT '',
    done_ms      INTEGER                        -- when it was dealt with
);
CREATE INDEX IF NOT EXISTS reports_by_state ON reports (state);
CREATE INDEX IF NOT EXISTS reports_by_day ON reports (day);
-- Admin alerts (see alerts.py): those going now and those fixed lately,
-- written as they change, so a restart neither says them again nor loses
-- them. An alert's ID is its kind, about and since_ms.
CREATE TABLE IF NOT EXISTS alerts (
    kind         TEXT    NOT NULL,
    about        TEXT    NOT NULL DEFAULT '',  -- within its kind (a station's id)
    since_ms     INTEGER NOT NULL,
    sentence     TEXT    NOT NULL,
    fixed_ms     INTEGER,                      -- NULL while it's going
    PRIMARY KEY (kind, about, since_ms)
);
"""

Segments = tuple[tuple[int, int], ...]
Breaks = tuple[tuple[str, int], ...]


@dataclass
class Channel:
    id: int
    number: int
    name: str
    sources: list[dict]
    # The station's logo ("" shows its number instead).
    logo: str
    # Episode order (rotate) or shuffle.
    order_mode: str
    # How 4:3 programs fill the 16:9 picture: fit (black bars), stretch, zoom.
    aspect_mode: str
    # Skip intros and credits, where Plex has found them.
    skip_intros: bool
    # Commercials (after episodes) or trailers (after movies): 0 to 3.
    breaks: int
    # A Station ID card saying what's up next, after each program: whether,
    # how long, and with its jingle or silent.
    station_id: bool
    id_seconds: int
    id_sound: bool
    # The station's logo, name or a clock in the corner during programs:
    # off, logo, name or clock.
    watermark: str
    # How big it is (small, medium, large) and how see-through (high, medium,
    # low transparency).
    watermark_size: str
    watermark_transparency: str
    # Which corner: top-left, top-right, bottom-left or bottom-right.
    watermark_position: str
    # When: always, or at the start of each program (its first 30 seconds).
    watermark_timing: str
    # The logo in its own colours, or all in white (as real channels show it).
    watermark_style: str
    # The corner clock's format: 12 (8:05 PM) or 24 (20:05) hours.
    clock_format: str
    # The Intro Bumper when someone tunes in: its length in seconds (0: off),
    # with the dial's sound or silent, and the line it shows about the station.
    intro_seconds: int
    intro_sound: bool
    description: str
    # Or a video of your own instead (one of the bumpers you've uploaded).
    intro_video: str
    # Someone tuning in joins it where it is ("now", as on real TV), or the
    # program on now from its beginning ("start"; see broadcaster.py).
    tune_in: str
    # The Up Next Banner near the end of each program: how long it's shown
    # (0: off) and how big it is (small, medium, large).
    up_next_seconds: int
    up_next_size: str
    # Marathons (three episodes of one show in a row, now and then; see
    # marathons.py): off, at random times (marathons_a_week of them), or at
    # set times (on marathon_days, Monday 0 to Sunday 6, at marathon_time);
    # with each show's next episodes in order, or a random stretch.
    marathon_mode: str
    marathons_a_week: int
    marathon_days: str
    marathon_time: str
    marathon_episodes: str
    # The size of its picture: 480p, 720p or 1080p (see ff.PICTURES).
    picture: str
    # Subtitles drawn into the picture: off, forced (only the lines meant
    # to be read) or always (see subtitles.py).
    subtitles: str
    # A Feature Presentation (see specials.py): off or on, on feature_days
    # at feature_time, a movie from feature_source (a movie library or
    # collection, as a source; {} for the station's own movies).
    feature_mode: str
    feature_days: str
    feature_time: str
    feature_source: dict
    # Time-of-day blocks: [{"id", "name", "days", "start", "end", "sources"}].
    blocks: list[dict]
    # Who made it (a user's id), if it was made while signing in was on.
    created_by: int | None = None
    # When it was made; for a station made before 1.15, when it's known to
    # have been on the air by (created_exact False).
    created_ms: int = 0
    created_exact: bool = True

    @property
    def has_intro(self) -> bool:
        return bool(self.intro_video) or self.intro_seconds > 0


# A station's settings: its column, its name in the web API, and what a new
# station starts with. (Stations made before a setting existed keep how
# StationPlay behaved then: see the defaults in _ADDED_COLUMNS.)
STATION_SETTINGS: tuple[tuple[str, str, object], ...] = (
    ("order_mode", "orderMode", "shuffle"),
    ("aspect_mode", "aspectMode", "fit"),
    ("skip_intros", "skipIntros", False),
    ("breaks", "breaks", 0),
    ("station_id", "stationId", False),
    ("id_seconds", "idSeconds", 5),
    ("id_sound", "idSound", True),
    ("watermark", "watermark", "logo"),
    ("watermark_size", "watermarkSize", "large"),
    ("watermark_transparency", "watermarkTransparency", "medium"),
    ("watermark_position", "watermarkPosition", "bottom-left"),
    ("watermark_timing", "watermarkTiming", "always"),
    ("watermark_style", "watermarkStyle", "color"),
    ("clock_format", "clockFormat", "12"),
    ("intro_seconds", "introSeconds", 10),
    ("intro_sound", "introSound", True),
    ("description", "description", ""),
    ("intro_video", "introVideo", ""),
    ("tune_in", "tuneIn", "now"),
    ("up_next_seconds", "upNextSeconds", 10),
    ("up_next_size", "upNextSize", "large"),
    ("marathon_mode", "marathonMode", "off"),
    ("marathons_a_week", "marathonsAWeek", 2),
    ("marathon_days", "marathonDays", "5"),
    ("marathon_time", "marathonTime", "20:00"),
    ("marathon_episodes", "marathonEpisodes", "next"),
    # (A new station's is the one set for new stations: see playback.py.)
    ("picture", "picture", "720p"),
    ("subtitles", "subtitles", "off"),
    ("feature_mode", "featureMode", "off"),
    ("feature_days", "featureDays", "4"),
    ("feature_time", "featureTime", "20:00"),
    ("feature_source", "featureSource", {}),
    ("blocks", "blocks", ()),
)
# Its marathon, Feature Presentation and block settings (see specials.py).
SPECIAL_SETTINGS = tuple(
    c for c, _, _ in STATION_SETTINGS if c.startswith(("marathon", "feature")) or c == "blocks"
)
# What a new station starts with, unless told otherwise.
NEW_STATION: dict[str, object] = {column: default for column, _, default in STATION_SETTINGS}
# The settings stored as 0 or 1.
_FLAGS = frozenset(column for column, _, default in STATION_SETTINGS if isinstance(default, bool))
# Everything about a station that's stored with it.
_CHANNEL_COLUMNS = ("number", "name", "sources", "logo", *(c for c, _, _ in STATION_SETTINGS))


@dataclass(frozen=True)
class User:
    """Someone who can sign in to StationPlay's page."""

    id: int
    name: str
    role: str  # admin or user (see access.py)
    created_ms: int
    signed_in_ms: int  # when they last signed in; 0 if never
    max_stations: int | None  # the most stations they may make as a User; None: no limit
    level_id: int | None = None  # their Viewing Level (see viewing.py); None: Unrestricted
    has_pin: bool = False
    show_on: str = ""  # the pickers they're on (see devices); "": the server's default
    has_password: bool = True  # (a User may have none: they use only the apps' pickers)
    no_pin: bool = False  # they chose to have no PIN, so they're not asked for one again
    own_password: bool = True  # they may change their own password (an Admin always may)
    can_report: bool = True  # they may report problems from the apps (see reports.py)


@dataclass(frozen=True)
class SignedIn:
    """A sign-in: whose it is, and how it's been used."""

    user: User
    seen_ms: int  # when it was last seen
    device_id: int | None  # the linked device it's on, from its picker (see devices.py)
    app: str  # which of StationPlay's apps; "" for a browser
    active_ms: int  # when someone last used it, in a browser (see access.IDLE_SIGN_OUT_S)
    unlocked: bool  # made by picking someone without a PIN (see devices.choose)


@dataclass
class ScanRecord:
    """What checking one program's file found."""

    rating_key: str
    file: str
    size: int = 0
    quick_ms: int = 0
    quick: str = ""
    deep_ms: int = 0
    deep_at_s: float = 0.0
    deep: str = ""
    bad_minutes: list[int] = field(default_factory=list)
    tries: int = 0
    note: str = ""
    # You chose Retry after a check found a problem: checks leave this file
    # on the air.
    kept: bool = False
    # What the deep scan found so far (it can stop and carry on): how far
    # the picture went; the first and last moments with sound (-1: none
    # yet); how many seconds were black; and where the picture froze, or
    # the sound was silent, for long ([kind, from, to], kind "picture" or
    # "sound").
    picture_to_s: float = 0.0
    sound_from_s: float = -1.0
    sound_to_s: float = -1.0
    black_s: float = 0.0
    gaps: list[list] = field(default_factory=list)
    # Where the picture broke up, or the sound dropped out, as the deep scan
    # judges it ([kind, at], kind "picture" or "sound", at in seconds: see
    # scanner.what_it_costs). (bad_minutes are the minutes they're in.)
    glitches: list[list] = field(default_factory=list)


_SCAN_FIELDS = tuple(f.name for f in fields(ScanRecord))
_SCAN_JSON = ("bad_minutes", "gaps", "glitches")


@dataclass
class Item:
    """One scheduled entry in a channel's loop."""

    position: int
    start_ms: int  # offset of this item from the start of the loop
    duration_ms: int
    rating_key: str
    kind: str  # "episode" or "movie"
    title: str
    show_title: str | None = None
    show_key: str | None = None
    season: int | None = None
    episode: int | None = None
    year: int | None = None
    summary: str | None = None
    file_path: str | None = None
    part_key: str | None = None
    # A card that plays before the program (a Feature Presentation's), in
    # ms; its time is included in duration_ms.
    lead_ms: int = 0
    # The parts of the file that air, as (start, end) in ms of the file, in
    # order; None for the whole file. With intros and credits skipped,
    # duration_ms is how long these parts add up to: the program's length
    # on the station.
    segments: Segments | None = None
    # What plays straight after the program, in order: (file, ms) for each
    # commercial or trailer, and ("@id", ms) for the Station ID card. Their
    # time is included in duration_ms.
    breaks: Breaks | None = None
    # The program's rating and library as Plex gave them when it was last
    # asked (for titles.py; not kept with a station's eras).
    rating: str | None = None
    library: str | None = None

    @property
    def program_ms(self) -> int:
        """How long the program itself runs, without the card before it or
        what follows it."""
        return self.duration_ms - self.lead_ms - sum(ms for _, ms in self.breaks or ())

    @property
    def program_end_ms(self) -> int:
        """When the program ends, from the start of its slot: where what
        follows it begins."""
        return self.lead_ms + self.program_ms

    @property
    def display_title(self) -> str:
        return self.show_title or self.title

    @property
    def label(self) -> str:
        """e.g. 'Cheers S03E07 "Diane Meets Mom"' or '"Jaws" (1975)'."""
        if self.kind == "episode" and self.show_title:
            return (
                f"{self.show_title} S{self.season or 0:02d}E{self.episode or 0:02d} "
                f"\u201c{self.title}\u201d"
            )
        year = f" ({self.year})" if self.year else ""
        return f"\u201c{self.title}\u201d{year}"


def show_key(item: Item) -> str:
    """Programs with the same key count as "the same show"."""
    return item.show_key or f"movie:{item.rating_key}"


# era_items columns, in Item's field order (the two stored as JSON last;
# what's only passed on, never kept there, left out).
_JSON_FIELDS = ("segments", "breaks")
_PASSED_ON = ("rating", "library")
_ITEM_FIELDS = tuple(f.name for f in fields(Item) if f.name not in (*_JSON_FIELDS, *_PASSED_ON))
_ITEM_COLUMNS = ", ".join((*_ITEM_FIELDS, *_JSON_FIELDS))
# The columns a station's programs had before eras (the old channel_items).
_OLD_ITEM_COLUMNS = (
    "position, start_ms, duration_ms, rating_key, kind, title, show_title, show_key, "
    "season, episode, year, summary, file_path, part_key"
)
# What a deep scan found so far, cleared to start it afresh.
_DEEP_AFRESH = (
    "deep_at_s = 0, bad_minutes = '[]', picture_to_s = 0, sound_from_s = -1, "
    "sound_to_s = -1, black_s = 0, gaps = '[]', glitches = '[]'"
)
# Columns added since the first version: (table, column, definition).
_ADDED_COLUMNS = (
    ("channels", "aspect_mode", "TEXT NOT NULL DEFAULT 'fit'"),
    ("channels", "logo", "TEXT NOT NULL DEFAULT ''"),
    ("channels", "skip_intros", "INTEGER NOT NULL DEFAULT 0"),
    ("era_items", "segments", "TEXT"),
    ("era_items", "breaks", "TEXT"),
    ("channels", "breaks", "INTEGER NOT NULL DEFAULT 0"),
    ("channels", "station_id", "INTEGER NOT NULL DEFAULT 0"),
    ("channels", "watermark", "TEXT NOT NULL DEFAULT 'off'"),
    ("channels", "watermark_size", "TEXT NOT NULL DEFAULT 'large'"),
    ("channels", "watermark_transparency", "TEXT NOT NULL DEFAULT 'low'"),
    ("channels", "watermark_position", "TEXT NOT NULL DEFAULT 'bottom-right'"),
    ("channels", "watermark_timing", "TEXT NOT NULL DEFAULT 'always'"),
    ("channels", "watermark_style", "TEXT NOT NULL DEFAULT 'color'"),
    ("channels", "clock_format", "TEXT NOT NULL DEFAULT '12'"),
    # Added in 1.8. A station made before keeps how it played: no Intro
    # Bumper, and its Station ID card (if it has one) ten seconds and silent.
    ("channels", "intro_seconds", "INTEGER NOT NULL DEFAULT 0"),
    ("channels", "intro_sound", "INTEGER NOT NULL DEFAULT 1"),
    ("channels", "description", "TEXT NOT NULL DEFAULT ''"),
    ("channels", "id_seconds", "INTEGER NOT NULL DEFAULT 10"),
    ("channels", "id_sound", "INTEGER NOT NULL DEFAULT 0"),
    ("channels", "intro_video", "TEXT NOT NULL DEFAULT ''"),
    # Added in 1.8.3: a station made before has no Up Next Banner.
    ("channels", "up_next_seconds", "INTEGER NOT NULL DEFAULT 0"),
    ("channels", "up_next_size", "TEXT NOT NULL DEFAULT 'large'"),
    ("channels", "created_by", "INTEGER"),
    # (Users made by an early build of 1.9.0 have no limit.)
    ("users", "max_stations", "INTEGER"),
    # Added in 1.10: what the deep scan finds besides decoding errors.
    ("scans", "picture_to_s", "REAL NOT NULL DEFAULT 0"),
    ("scans", "sound_from_s", "REAL NOT NULL DEFAULT -1"),
    ("scans", "sound_to_s", "REAL NOT NULL DEFAULT -1"),
    ("scans", "black_s", "REAL NOT NULL DEFAULT 0"),
    ("scans", "gaps", "TEXT NOT NULL DEFAULT '[]'"),
    # Added in 1.13: marathons, and the eras they air in (special: what's
    # special about an era, as JSON; NULL for an ordinary one).
    ("channels", "marathon_mode", "TEXT NOT NULL DEFAULT 'off'"),
    ("channels", "marathons_a_week", "INTEGER NOT NULL DEFAULT 2"),
    ("channels", "marathon_days", "TEXT NOT NULL DEFAULT '5'"),
    ("channels", "marathon_time", "TEXT NOT NULL DEFAULT '20:00'"),
    ("channels", "marathon_episodes", "TEXT NOT NULL DEFAULT 'next'"),
    ("eras", "special", "TEXT"),
    # Added in 1.14: each station's picture size.
    ("channels", "picture", "TEXT NOT NULL DEFAULT '720p'"),
    # Added in 1.15: subtitles drawn in, Feature Presentations and blocks.
    ("channels", "subtitles", "TEXT NOT NULL DEFAULT 'off'"),
    ("channels", "feature_mode", "TEXT NOT NULL DEFAULT 'off'"),
    ("channels", "feature_days", "TEXT NOT NULL DEFAULT '4'"),
    ("channels", "feature_time", "TEXT NOT NULL DEFAULT '20:00'"),
    ("channels", "feature_source", "TEXT NOT NULL DEFAULT '{}'"),
    ("channels", "blocks", "TEXT NOT NULL DEFAULT '[]'"),
    ("era_items", "lead_ms", "INTEGER NOT NULL DEFAULT 0"),
    # Added in 1.15: when each station was made (see Channel.created_ms).
    ("channels", "created_ms", "INTEGER NOT NULL DEFAULT 0"),
    ("channels", "created_exact", "INTEGER NOT NULL DEFAULT 1"),
    # Added in 1.16: where someone tuning in joins.
    ("channels", "tune_in", "TEXT NOT NULL DEFAULT 'now'"),
    # Added in 1.16.3: where the deep scan found the picture or sound break up.
    ("scans", "glitches", "TEXT NOT NULL DEFAULT '[]'"),
    # Added in 1.19: which of StationPlay's apps a sign-in is ('' for a
    # browser), on what device, as the app says.
    ("sessions", "app", "TEXT NOT NULL DEFAULT ''"),
    # Added in 1.23: each user's Viewing Level (NULL: Unrestricted), PIN (a hash; ''
    # for none), and the pickers they're on ('': the server's default).
    ("users", "level_id", "INTEGER REFERENCES levels(id) ON DELETE SET NULL"),
    ("users", "pin", "TEXT NOT NULL DEFAULT ''"),
    ("users", "show_on", "TEXT NOT NULL DEFAULT ''"),
    # ...and which linked device a sign-in was made on, from its picker.
    ("sessions", "device_id", "INTEGER REFERENCES linked_devices(id) ON DELETE CASCADE"),
    # Added in 1.26: when someone last used a browser that's signed in (see
    # access.IDLE_SIGN_OUT_S). A browser signed in before then is taken as
    # last used when it was last seen.
    ("sessions", "active_ms", "INTEGER NOT NULL DEFAULT 0"),
    # Added in 1.27, as names can change: who linked each device, by their
    # id (NULL: no one there now). A device linked before then is taken as
    # linked by the user with the name it kept, if there is one.
    ("linked_devices", "linked_by_id", "INTEGER"),
    # Added in 1.28: whether someone chose to have no PIN, when an app asked
    # them for one (see devices.py), so they're not asked again.
    ("users", "no_pin", "INTEGER NOT NULL DEFAULT 0"),
    # ...and whether they may change their own password (see access.py): an
    # Admin's choice for each person, yes to start with.
    ("users", "own_password", "INTEGER NOT NULL DEFAULT 1"),
    # Added in 1.30: whether they may report problems from the apps (see
    # reports.py): an Admin's choice for each person, yes to start with.
    ("users", "can_report", "INTEGER NOT NULL DEFAULT 1"),
    # Added in 1.28.1: whether a sign-in was made by picking someone with no
    # PIN on a device's list (see devices.py), which proves nothing about
    # who's there, so it can't change their passcode.
    ("sessions", "unlocked", "INTEGER NOT NULL DEFAULT 0"),
    # Added in 1.29.1: an app's journal before a problem, and how long
    # trouble reaching StationPlay lasted (see problems.py).
    ("problems", "journal", "TEXT NOT NULL DEFAULT ''"),
    ("problems", "lasted_ms", "INTEGER NOT NULL DEFAULT 0"),
)


# The marathons remembered for each station (for choosing the next ones).
MARATHONS_KEPT = 200
# Programs each person's progress is kept for (the newest; see ondemand.py).
PROGRESS_KEPT = 5000


@dataclass(frozen=True)
class NewEra:
    """An era to save (see Database.replace_eras; Era for what each is)."""

    items: list[Item]
    start_ms: int | None
    epoch_ms: int
    seed: str
    order_mode: str
    created_ms: int
    reason: str
    first_pass: list[str] | None = None
    tail: list[tuple[str, str]] | None = None
    added: int = 0
    removed: int = 0
    special: dict | None = None


@dataclass(frozen=True)
class SpecialRun:
    """A Feature Presentation or block a station has had, or has coming:
    when it was due, what it was (the film, the block), and (a block) where
    its programs got to."""

    due_ms: int
    key: str
    value: str = ""


@dataclass(frozen=True)
class MarathonRecord:
    """A marathon a station has had, or has coming: when it was due, the
    show (its key), and the (season, episode) it left off at."""

    due_ms: int
    show_key: str
    last: tuple[int, int]


@dataclass
class Era:
    """One stretch of a station's schedule: a frozen playlist and where it
    takes over. See schedule.EraSchedule for how it's played. An era never
    changes once saved, so what's worked out from its items is kept."""

    id: int
    channel_id: int
    start_ms: int | None
    epoch_ms: int
    seed: str
    order_mode: str
    chained: bool
    first_pass: list[str] | None
    tail: list[tuple[str, str]]
    created_ms: int
    reason: str
    added: int
    removed: int
    items: list[Item]
    # What's special about it: {"kind": "marathon", "title": the show's
    # title, "show": its key, "due": when it was due}; None for an ordinary
    # era.
    special: dict | None = None

    @cached_property
    def total_ms(self) -> int:
        return sum(i.duration_ms for i in self.items)

    @cached_property
    def rating_keys(self) -> frozenset[str]:
        return frozenset(i.rating_key for i in self.items)

    @cached_property
    def trimmed_count(self) -> int:
        """Programs with an intro or credits skipped."""
        return sum(1 for i in self.items if i.segments)

    @cached_property
    def show_counts(self) -> Counter[str]:
        return Counter(show_key(i) for i in self.items)


@dataclass
class CachedMarkers:
    """What Plex last said about a program's markers."""

    duration_ms: int  # the program's length then (a new file means asking again)
    markers: str  # JSON
    checked_ms: int  # when
    first_ms: int  # since when it has said the same


def copy_database(source: Path, dest: Path, sign_ins: bool = False) -> None:
    """A consistent copy of a database for a backup, read through a connection
    of its own so nothing else waits for it. Sign-ins (and the browsers they
    were on) aren't copied unless asked (`sign_ins`): a backup restored later
    signs everyone out, and one passed around can't be used to sign in."""
    src = sqlite3.connect(source)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
        for table in () if sign_ins else ("sessions", "devices"):
            if out.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
                out.execute(f"DELETE FROM {table}")
        out.commit()
        out.execute("PRAGMA journal_mode = DELETE")  # one self-contained file
    finally:
        out.close()
        src.close()


def changes_needed(path: Path) -> list[str]:
    """What opening the database at `path` would change in it, as Database
    brings one made by an earlier version up to date: the tables, indexes
    and columns it lacks, and the older ways of keeping things it moves on
    from (see Database._upgrade). Nothing for one that's up to date, or has
    nothing in it yet. Only reads it."""
    want = sqlite3.connect(":memory:")
    have = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True)  # (never made here)
    try:
        want.executescript(SCHEMA)
        found = {
            (kind, name)
            for kind, name in have.execute("SELECT type, name FROM sqlite_master").fetchall()
        }
        if not found:
            return []  # (a new one)
        out = [
            f"a new {kind}, {name}"
            for kind, name in want.execute("SELECT type, name FROM sqlite_master").fetchall()
            if (kind, name) not in found and not name.startswith("sqlite_")
        ]
        columns = [
            (table, row[1])
            for (table,) in want.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            for row in want.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        for table, column in [*columns, *((t, c) for t, c, _ in _ADDED_COLUMNS)]:
            if ("table", table) in found:
                there = {row[1] for row in have.execute(f"PRAGMA table_info({table})")}
                if column not in there and f"a new column, {table}.{column}" not in out:
                    out.append(f"a new column, {table}.{column}")
        if ("table", "channel_items") in found:
            out.append("stations' programs kept as eras")
        if ("index", "views_by_start") in found:
            out.append("an old index dropped")
        dated = ("table", "channels") in found and any(
            row[1] == "created_ms" for row in have.execute("PRAGMA table_info(channels)")
        )
        if dated and have.execute("SELECT 1 FROM channels WHERE created_ms = 0").fetchone():
            out.append("when stations were made")
        return out
    finally:
        have.close()
        want.close()


@dataclass
class Database:
    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._upgrade()
        # Each station's eras are cached in memory; an era never changes, and
        # they're read on every schedule lookup.
        self._eras_cache: dict[int, list[Era]] = {}
        self._sets_cache: dict[int, dict[str, list[Item]]] = {}
        self.sets_version = 0  # (bumped whenever any station's program sets change)

    def close(self) -> None:
        self._conn.close()

    def _date_stations(self) -> None:
        """When stations made before 1.15 (or without a date for any other
        reason) were made: exactly, if the era they started with is still
        kept; otherwise the earliest they're known to have been on the air
        (their oldest era, or viewing), so made on or before then."""
        now = int(time.time() * 1000)
        with self._conn:
            for row in self._conn.execute(
                "SELECT id, built_at_ms FROM channels WHERE created_ms = 0"
            ).fetchall():
                made = self._conn.execute(
                    "SELECT MIN(created_ms) FROM eras WHERE channel_id = ? AND reason = 'created'",
                    (row["id"],),
                ).fetchone()[0]
                if made:
                    self._conn.execute(
                        "UPDATE channels SET created_ms = ?, created_exact = 1 WHERE id = ?",
                        (made, row["id"]),
                    )
                    continue
                known = [
                    self._conn.execute(
                        "SELECT MIN(created_ms) FROM eras WHERE channel_id = ?", (row["id"],)
                    ).fetchone()[0],
                    self._conn.execute(
                        "SELECT MIN(start_ms) FROM views WHERE channel_id = ?", (row["id"],)
                    ).fetchone()[0],
                    row["built_at_ms"] or None,
                    now,
                ]
                self._conn.execute(
                    "UPDATE channels SET created_ms = ?, created_exact = 0 WHERE id = ?",
                    (min(k for k in known if k), row["id"]),
                )

    def _upgrade(self) -> None:
        """Brings a database made by an earlier version up to date. (What's
        done here must be found by changes_needed too, so the database is
        backed up before it's changed: see backups.before_update.)"""
        with self._conn:
            self._conn.execute("DROP INDEX IF EXISTS views_by_start")  # (an early 1.9.0's)
        for table, column, definition in _ADDED_COLUMNS:
            have = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                with self._conn:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                    if (table, column) == ("sessions", "active_ms"):
                        self._conn.execute("UPDATE sessions SET active_ms = seen_ms")
                    if (table, column) == ("linked_devices", "linked_by_id"):
                        self._conn.execute(
                            "UPDATE linked_devices SET linked_by_id = (SELECT id FROM users "
                            "WHERE users.name = linked_devices.linked_by)"
                        )
        old = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'channel_items'"
        ).fetchone()
        if old:
            # Before eras, each station had one playlist. It becomes the
            # station's first era, scheduled exactly as before.
            with self._conn:
                for row in self._conn.execute(
                    "SELECT * FROM channels WHERE id IN (SELECT channel_id FROM channel_items)"
                ).fetchall():
                    cur = self._conn.execute(
                        "INSERT INTO eras (channel_id, start_ms, epoch_ms, seed, order_mode, "
                        "chained, created_ms, reason) VALUES (?, NULL, ?, ?, ?, 1, ?, 'built')",
                        (
                            row["id"],
                            row["epoch_ms"],
                            f"{row['id']}:{row['built_at_ms']}",
                            row["order_mode"],
                            row["built_at_ms"],
                        ),
                    )
                    self._conn.execute(
                        f"INSERT INTO era_items (era_id, {_OLD_ITEM_COLUMNS}) "
                        f"SELECT ?, {_OLD_ITEM_COLUMNS} FROM channel_items WHERE channel_id = ?",
                        (cur.lastrowid, row["id"]),
                    )
                self._conn.execute("DROP TABLE channel_items")
        self._date_stations()

    # Channels -------------------------------------------------------------

    def list_channels(self) -> list[Channel]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM channels ORDER BY number").fetchall()
        return [self._channel(r) for r in rows]

    def get_channel(self, channel_id: int) -> Channel | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM channels WHERE id = ?", (channel_id,)
            ).fetchone()
        return self._channel(row) if row else None

    def get_channel_by_number(self, number: int) -> Channel | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM channels WHERE number = ?", (number,)
            ).fetchone()
        return self._channel(row) if row else None

    def create_channel(
        self,
        number: int,
        name: str,
        sources: list[dict],
        logo: str = "",
        created_by: int | None = None,
        **settings,
    ) -> Channel:
        """A new station; settings not given (or None) are NEW_STATION's."""
        given = {k: v for k, v in settings.items() if v is not None}
        unknown = given.keys() - NEW_STATION.keys()
        if unknown:
            raise TypeError(f"Unknown station settings: {', '.join(sorted(unknown))}")
        values = _settings_row(
            {
                **NEW_STATION,
                **given,
                "number": number,
                "name": name,
                "sources": sources,
                "logo": logo,
            }
        )
        values["created_by"] = created_by
        values["created_ms"] = int(time.time() * 1000)
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"INSERT INTO channels ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                list(values.values()),
            )
        channel = self.get_channel(int(cur.lastrowid or 0))
        assert channel is not None
        return channel

    def update_channel(self, channel_id: int, **settings) -> None:
        """Changes the given settings of a station (number=, name=, logo=...);
        the others stay as they are."""
        unknown = settings.keys() - set(_CHANNEL_COLUMNS)
        if unknown:
            raise TypeError(f"Unknown station settings: {', '.join(sorted(unknown))}")
        values = _settings_row(settings)
        if not values:
            return
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE channels SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                [*values.values(), channel_id],
            )

    def delete_channel(self, channel_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
            self._eras_cache.pop(channel_id, None)
            self._sets_cache.pop(channel_id, None)

    # Eras -----------------------------------------------------------------

    def eras(self, channel_id: int) -> list[Era]:
        """The station's eras, earliest first."""
        cached = self._eras_cache.get(channel_id)
        if cached is not None:
            return cached
        # Loaded and cached under the lock, so an era being added on another
        # thread can't be missed by a cache filled just before it.
        with self._lock:
            cached = self._eras_cache.get(channel_id)
            if cached is not None:
                return cached
            rows = self._conn.execute(
                "SELECT * FROM eras WHERE channel_id = ? "
                "ORDER BY start_ms IS NOT NULL, start_ms, id",
                (channel_id,),
            ).fetchall()
            eras = [self._era(r, self._era_items(r["id"])) for r in rows]
            self._eras_cache[channel_id] = eras
            return eras

    def _era_items(self, era_id: int) -> list[Item]:
        cur = self._conn.cursor()
        cur.row_factory = None  # plain tuples, in Item's field order: much quicker
        rows = cur.execute(
            f"SELECT {_ITEM_COLUMNS} FROM era_items WHERE era_id = ? ORDER BY position",
            (era_id,),
        ).fetchall()
        return [
            Item(*r[:-2], segments=_load_segments(r[-2]), breaks=_load_breaks(r[-1]))  # type: ignore[misc]
            for r in rows
        ]

    def add_era(
        self,
        channel_id: int,
        items: list[Item],
        *,
        start_ms: int | None,
        epoch_ms: int,
        seed: str,
        order_mode: str,
        created_ms: int,
        reason: str,
        first_pass: list[str] | None = None,
        tail: list[tuple[str, str]] | None = None,
        added: int = 0,
        removed: int = 0,
        special: dict | None = None,
    ) -> Era:
        """Saves a new era. Its playlist must already have its offsets."""
        era = NewEra(
            items, start_ms, epoch_ms, seed, order_mode, created_ms, reason,
            first_pass, tail, added, removed, special,
        )  # fmt: skip
        return self.replace_eras(channel_id, [], [era])[0]

    def replace_eras(self, channel_id: int, era_ids: list[int], new: list[NewEra]) -> list[Era]:
        """Deletes the eras `era_ids` and saves `new` ones, all at once: if
        anything goes wrong, nothing changes."""
        with self._lock, self._conn:
            if era_ids:
                self._conn.executemany("DELETE FROM eras WHERE id = ?", [(i,) for i in era_ids])
            made = [self._insert_era(channel_id, e) for e in new]
            cached = self._eras_cache.get(channel_id)
            if cached is not None:
                # Keep the existing era objects, so their worked-out
                # schedules stay cached.
                self._eras_cache[channel_id] = sorted(
                    [*(e for e in cached if e.id not in era_ids), *made],
                    key=lambda e: (e.start_ms is not None, e.start_ms or 0, e.id),
                )
        return made

    def _insert_era(self, channel_id: int, new: NewEra) -> Era:
        """(With the lock held, in a transaction.)"""
        cur = self._conn.execute(
            "INSERT INTO eras (channel_id, start_ms, epoch_ms, seed, order_mode, chained, "
            "first_pass, tail, created_ms, reason, added, removed, special) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
            (
                channel_id,
                new.start_ms,
                new.epoch_ms,
                new.seed,
                new.order_mode,
                json.dumps(new.first_pass) if new.first_pass else None,
                json.dumps(new.tail) if new.tail else None,
                new.created_ms,
                new.reason,
                new.added,
                new.removed,
                json.dumps(new.special) if new.special else None,
            ),
        )
        era_id = int(cur.lastrowid or 0)
        values = attrgetter(*_ITEM_FIELDS)
        self._conn.executemany(
            f"INSERT INTO era_items (era_id, {_ITEM_COLUMNS}) "
            f"VALUES ({', '.join('?' * (len(_ITEM_FIELDS) + 3))})",
            [
                (
                    era_id,
                    *values(i),
                    json.dumps(i.segments) if i.segments else None,
                    json.dumps(i.breaks) if i.breaks else None,
                )
                for i in new.items
            ],
        )
        row = self._conn.execute("SELECT * FROM eras WHERE id = ?", (era_id,)).fetchone()
        return self._era(row, list(new.items))

    def delete_eras(self, channel_id: int, era_ids: list[int]) -> None:
        if era_ids:
            self.replace_eras(channel_id, era_ids, [])

    def latest_items(self, channel_id: int) -> list[Item]:
        """The station's programs as of its newest era (not counting a
        marathon's, which has only a few of them)."""
        latest = self.latest_era(channel_id)
        return latest.items if latest else []

    def latest_era(self, channel_id: int) -> Era | None:
        """The station's newest ordinary era (not a marathon's)."""
        return next((e for e in reversed(self.eras(channel_id)) if not e.special), None)

    # Marathons --------------------------------------------------------------

    def marathons(self, channel_id: int) -> list[MarathonRecord]:
        """The marathons a station has had or has coming, earliest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM marathons WHERE channel_id = ? ORDER BY due_ms", (channel_id,)
            ).fetchall()
        return [
            MarathonRecord(r["due_ms"], r["show_key"], (r["last_season"], r["last_episode"]))
            for r in rows
        ]

    def forget_marathons(self, channel_id: int, dues: list[int]) -> None:
        """Forgets marathons that won't happen after all (their eras were
        replaced before they aired), by when they were due."""
        if not dues:
            return
        with self._lock, self._conn:
            self._conn.executemany(
                "DELETE FROM marathons WHERE channel_id = ? AND due_ms = ?",
                [(channel_id, d) for d in dues],
            )

    def remember_marathon(self, channel_id: int, record: MarathonRecord) -> None:
        """Remembers a marathon, keeping the station's latest MARATHONS_KEPT."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO marathons "
                "(channel_id, due_ms, show_key, last_season, last_episode) "
                "VALUES (?, ?, ?, ?, ?)",
                (channel_id, record.due_ms, record.show_key, record.last[0], record.last[1]),
            )
            self._conn.execute(
                "DELETE FROM marathons WHERE channel_id = ? AND due_ms NOT IN "
                "(SELECT due_ms FROM marathons WHERE channel_id = ? "
                "ORDER BY due_ms DESC LIMIT ?)",
                (channel_id, channel_id, MARATHONS_KEPT),
            )

    # Feature Presentations and blocks: what they were, and their programs ---

    def special_runs(self, channel_id: int, kind: str) -> list[SpecialRun]:
        """A station's specials of `kind` it has had or has coming, earliest
        first (see specials.py)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT due_ms, key, value FROM special_runs WHERE channel_id = ? AND kind = ? "
                "ORDER BY due_ms",
                (channel_id, kind),
            ).fetchall()
        return [SpecialRun(r["due_ms"], r["key"], r["value"]) for r in rows]

    def remember_special(self, channel_id: int, kind: str, run: SpecialRun) -> None:
        """Remembers a special, keeping the station's latest MARATHONS_KEPT
        of its kind."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO special_runs (channel_id, kind, due_ms, key, value) "
                "VALUES (?, ?, ?, ?, ?)",
                (channel_id, kind, run.due_ms, run.key, run.value),
            )
            self._conn.execute(
                "DELETE FROM special_runs WHERE channel_id = ? AND kind = ? AND due_ms NOT IN "
                "(SELECT due_ms FROM special_runs WHERE channel_id = ? AND kind = ? "
                "ORDER BY due_ms DESC LIMIT ?)",
                (channel_id, kind, channel_id, kind, MARATHONS_KEPT),
            )

    def forget_specials(self, channel_id: int, dues: list[tuple[str, int]]) -> None:
        """Forgets specials that won't happen after all, by (kind, when due)."""
        if not dues:
            return
        with self._lock, self._conn:
            self._conn.executemany(
                "DELETE FROM special_runs WHERE channel_id = ? AND kind = ? AND due_ms = ?",
                [(channel_id, kind, due) for kind, due in dues],
            )

    def program_sets(self, channel_id: int) -> dict[str, list[Item]]:
        """The programs a station's specials draw on, by name (see
        save_program_sets). Don't change what's returned: it's kept."""
        cached = self._sets_cache.get(channel_id)
        if cached is not None:
            return cached
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, items FROM program_sets WHERE channel_id = ? ORDER BY name",
                (channel_id,),
            ).fetchall()
            found = {r["name"]: _items_from_json(r["items"]) for r in rows}
            self._sets_cache[channel_id] = found
        return found

    def program_set(self, channel_id: int, name: str) -> list[Item]:
        """The programs a station's special `name` draws on; [] if none."""
        return self.program_sets(channel_id).get(name, [])

    def program_set_names(self, channel_id: int) -> list[str]:
        return list(self.program_sets(channel_id))

    def save_program_sets(self, channel_id: int, sets: dict[str, list[Item]]) -> None:
        """A station's program sets are `sets` (any others go)."""
        with self._lock, self._conn:
            self._sets_cache.pop(channel_id, None)
            self.sets_version += 1
            self._conn.execute("DELETE FROM program_sets WHERE channel_id = ?", (channel_id,))
            self._conn.executemany(
                "INSERT INTO program_sets (channel_id, name, items) VALUES (?, ?, ?)",
                [(channel_id, name, _items_json(items)) for name, items in sets.items()],
            )

    # The ratings of what's on the stations (see titles.py) ---------------------

    def titles(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute("SELECT * FROM titles").fetchall()

    def save_titles(self, rows: list[tuple[str, str, str, str, int, int]]) -> None:
        """Titles as (key, kind, rating, library, seen_ms, checked_ms), each
        replacing what was kept for its key."""
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO titles (key, kind, rating, library, seen_ms, checked_ms) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (key) DO UPDATE SET kind = excluded.kind, "
                "rating = excluded.rating, library = excluded.library, "
                "seen_ms = excluded.seen_ms, checked_ms = excluded.checked_ms",
                rows,
            )

    # Viewing Levels, and stations allowed or blocked for a user (see viewing.py)

    def levels(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute("SELECT * FROM levels ORDER BY id").fetchall()

    def add_level(
        self,
        name: str,
        movie_age: int | None,
        tv_age: int | None,
        unrated: bool,
        libraries: list[str] | None,
        builtin: str = "",
    ) -> int:
        """Adds a level; sqlite3.IntegrityError if there's one by that name."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO levels (name, movie_age, tv_age, unrated, libraries, builtin) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, movie_age, tv_age, int(unrated), _json_or_null(libraries), builtin),
            )
        return int(cur.lastrowid or 0)

    def update_level(
        self,
        level_id: int,
        name: str,
        movie_age: int | None,
        tv_age: int | None,
        unrated: bool,
        libraries: list[str] | None,
    ) -> None:
        """sqlite3.IntegrityError if another level has that name."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE levels SET name = ?, movie_age = ?, tv_age = ?, unrated = ?, "
                "libraries = ? WHERE id = ?",
                (name, movie_age, tv_age, int(unrated), _json_or_null(libraries), level_id),
            )

    def make_level_builtin(self, level_id: int, builtin: str, name: str) -> None:
        """Marks a level as one StationPlay comes with (renamed to `name`,
        unless another level has that name)."""
        with self._lock, self._conn:
            self._conn.execute("UPDATE levels SET builtin = ? WHERE id = ?", (builtin, level_id))
            self._conn.execute(
                "UPDATE levels SET name = ? WHERE id = ? AND NOT EXISTS "
                "(SELECT 1 FROM levels WHERE name = ? COLLATE NOCASE AND id != ?)",
                (name, level_id, name, level_id),
            )

    def delete_level(self, level_id: int) -> None:
        """Removes a level (its users go back to Unrestricted)."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM levels WHERE id = ?", (level_id,))

    def set_user_level(self, user_id: int, level_id: int | None) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE users SET level_id = ? WHERE id = ?", (level_id, user_id))

    def user_stations(self) -> dict[int, dict[int, bool]]:
        """Stations allowed (True) or blocked (False), by user and station."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM user_stations").fetchall()
        out: dict[int, dict[int, bool]] = {}
        for r in rows:
            out.setdefault(r["user_id"], {})[r["channel_id"]] = bool(r["allowed"])
        return out

    def set_user_stations(self, user_id: int, stations: dict[int, bool]) -> None:
        """The stations allowed or blocked for a user are `stations` (any
        others are neither)."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM user_stations WHERE user_id = ?", (user_id,))
            self._conn.executemany(
                "INSERT INTO user_stations (user_id, channel_id, allowed) "
                "SELECT ?, id, ? FROM channels WHERE id = ?",
                [(user_id, int(allowed), channel_id) for channel_id, allowed in stations.items()],
            )

    def all_programs(self, channel_id: int) -> list[Item]:
        """A station's programs and those its specials draw on, each once."""
        out = {i.rating_key: i for i in self.latest_items(channel_id)}
        for items in self.program_sets(channel_id).values():
            for item in items:
                out.setdefault(item.rating_key, item)
        return list(out.values())

    # Intro and credits markers, as Plex last reported them ------------------

    def cached_markers(self, rating_keys: list[str]) -> dict[str, CachedMarkers]:
        """What Plex last said about each of these programs' markers."""
        out: dict[str, CachedMarkers] = {}
        with self._lock:
            for start in range(0, len(rating_keys), 500):
                chunk = rating_keys[start : start + 500]
                rows = self._conn.execute(
                    f"SELECT * FROM markers WHERE rating_key IN ({', '.join('?' * len(chunk))})",
                    chunk,
                ).fetchall()
                for r in rows:
                    out[r["rating_key"]] = CachedMarkers(
                        r["duration_ms"], r["markers"], r["checked_ms"], r["first_ms"]
                    )
        return out

    def save_markers(self, rows: list[tuple[str, int, str, int, int]]) -> None:
        """Saves (rating_key, duration_ms, markers JSON, checked_ms, first_ms) rows."""
        if not rows:
            return
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO markers (rating_key, duration_ms, markers, checked_ms, first_ms) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(rating_key) DO UPDATE SET "
                "duration_ms = excluded.duration_ms, markers = excluded.markers, "
                "checked_ms = excluded.checked_ms, first_ms = excluded.first_ms",
                rows,
            )

    def forget_markers_before(self, checked_ms: int) -> None:
        """Drops markers not asked about since `checked_ms` (programs long gone)."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM markers WHERE checked_ms < ?", (checked_ms,))

    # Logos you've uploaded --------------------------------------------------

    def custom_logos(self) -> list[tuple[str, str]]:
        """(id, name) of each uploaded logo, oldest first."""
        with self._lock:
            rows = self._conn.execute("SELECT id, name FROM logos ORDER BY created_ms").fetchall()
        return [(r["id"], r["name"]) for r in rows]

    def add_custom_logo(self, logo_id: str, name: str, created_ms: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO logos (id, name, created_ms) VALUES (?, ?, ?)",
                (logo_id, name, created_ms),
            )

    def delete_custom_logo(self, logo_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM logos WHERE id = ?", (logo_id,))

    # Settings kept between restarts ---------------------------------------

    # What checking files found ---------------------------------------------

    def scans(self) -> dict[str, ScanRecord]:
        with self._lock:
            rows = self._conn.execute(f"SELECT {', '.join(_SCAN_FIELDS)} FROM scans").fetchall()
        return {row["rating_key"]: _scan_record(row) for row in rows}

    def scan(self, rating_key: str) -> ScanRecord | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {', '.join(_SCAN_FIELDS)} FROM scans WHERE rating_key = ?", (rating_key,)
            ).fetchone()
        return _scan_record(row) if row else None

    def part_records(self, key: str) -> list[tuple[int, str]]:
        """The records of a version's files after its first (see
        broken.part_key): (which file, its record's key), in order."""
        prefix = f"{key}/part"
        with self._lock:
            rows = self._conn.execute(
                "SELECT rating_key FROM scans WHERE rating_key >= ? AND rating_key < ?",
                (prefix, f"{key}/paru"),  # (by the key's index: those starting with it)
            ).fetchall()
        found = [(r["rating_key"][len(prefix) :], r["rating_key"]) for r in rows]
        return sorted((int(n), k) for n, k in found if n.isdigit())

    def save_quick(self, record: ScanRecord) -> None:
        """Saves a quick check's result, leaving a deep scan's progress on
        the same file as it is (one may have moved on meanwhile)."""
        current = self.scan(record.rating_key)
        if current is not None and current.file == record.file and current.size == record.size:
            with self._lock, self._conn:
                self._conn.execute(
                    "UPDATE scans SET quick_ms = ?, quick = ? WHERE rating_key = ?",
                    (record.quick_ms, record.quick, record.rating_key),
                )
        else:
            self.save_scan(record)

    def save_scan(self, record: ScanRecord) -> None:
        values = [getattr(record, f) for f in _SCAN_FIELDS]
        for name in _SCAN_JSON:
            values[_SCAN_FIELDS.index(name)] = json.dumps(getattr(record, name))
        with self._lock, self._conn:
            self._conn.execute(
                f"INSERT OR REPLACE INTO scans ({', '.join(_SCAN_FIELDS)}) "
                f"VALUES ({', '.join('?' * len(_SCAN_FIELDS))})",
                values,
            )

    def keep_on_air(self, rating_key: str, file: str | None = None, size: int = 0) -> None:
        """Checks (and playing it, for what its file is) leave this program's
        current file on the air from now on. `file`: the file, if it may not
        have been checked yet (it was taken off the air as it played)."""
        with self._lock, self._conn:
            kept = self._conn.execute(
                "UPDATE scans SET kept = 1 WHERE rating_key = ?", (rating_key,)
            ).rowcount
        if not kept and file:
            self.save_scan(ScanRecord(rating_key, file, size, kept=True))

    def check_all_again(self, quick_ms: int) -> None:
        """Every program's file is checked again, from scratch (the checks
        changed), as if last quick-checked at `quick_ms`. Files you put back
        on the air stay there."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE scans SET quick_ms = ?, quick = '', deep_ms = 0, "
                f"deep = '', tries = 0, note = '', {_DEEP_AFRESH}",
                (quick_ms,),
            )

    def deep_scan_again(self, rating_keys: list[str]) -> None:
        """These programs' files are deep-scanned again, from scratch (what
        the deep scan judges changed); their quick checks stand, and so does
        your putting one back on the air."""
        with self._lock, self._conn:
            self._conn.executemany(
                f"UPDATE scans SET deep_ms = 0, deep = '', tries = 0, note = '', {_DEEP_AFRESH} "
                "WHERE rating_key = ?",
                [(k,) for k in rating_keys],
            )

    def forget_scans(self, rating_keys: list[str]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "DELETE FROM scans WHERE rating_key = ?", [(k,) for k in rating_keys]
            )

    def set_every_picture(self, picture: str) -> None:
        """Every station's picture is `picture` (see playback.start)."""
        with self._lock, self._conn:
            self._conn.execute("UPDATE channels SET picture = ?", (picture,))

    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # Users and signing in (see access.py) ------------------------------------

    def users(self) -> list[User]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM users ORDER BY name").fetchall()
        return [_user(r) for r in rows]

    def has_users(self) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def user_named(self, name: str) -> tuple[User, str] | None:
        """A user, by name (any case), with their password's hash."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
        return (_user(row), row["password"]) if row else None

    def add_user(
        self, name: str, password_hash: str, role: str, created_ms: int, max_stations: int | None
    ) -> User:
        """Adds a user; sqlite3.IntegrityError if there's one by that name."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO users (name, password, role, created_ms, max_stations) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, password_hash, role, created_ms, max_stations),
            )
        return User(int(cur.lastrowid or 0), name, role, created_ms, 0, max_stations)

    def user(self, user_id: int) -> User | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _user(row) if row else None

    def set_max_stations(self, user_id: int, max_stations: int | None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE users SET max_stations = ? WHERE id = ?", (max_stations, user_id)
            )

    def stations_made(self) -> dict[int, int]:
        """How many of the stations there are each user made, by their id."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT created_by, COUNT(*) AS n FROM channels "
                "WHERE created_by IS NOT NULL GROUP BY created_by"
            ).fetchall()
        return {r["created_by"]: r["n"] for r in rows}

    def rename_user(self, user_id: int, name: str) -> None:
        """Gives a user a new name; sqlite3.IntegrityError if someone else
        has it (in any case). Everything of theirs is kept by their id, so it
        stays theirs; what's kept with their name to show it (their viewing
        in the stats, the devices they linked) takes the new one."""
        with self._lock, self._conn:
            self._conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
            for table in ("app_watched", "media_watched"):
                self._conn.execute(
                    f"UPDATE {table} SET user_name = ? WHERE user_id = ?", (name, user_id)
                )
            self._conn.execute(
                "UPDATE linked_devices SET linked_by = ? WHERE linked_by_id = ?", (name, user_id)
            )

    def update_user(
        self, user_id: int, *, password_hash: str | None = None, role: str | None = None
    ) -> None:
        with self._lock, self._conn:
            if password_hash is not None:
                self._conn.execute(
                    "UPDATE users SET password = ? WHERE id = ?", (password_hash, user_id)
                )
                # Signed out everywhere: whoever knew the old one is out.
                self._conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            if role is not None:
                self._conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))

    def set_own_password(self, user_id: int, on: bool) -> None:
        """Whether someone may change their own password."""
        with self._lock, self._conn:
            self._conn.execute("UPDATE users SET own_password = ? WHERE id = ?", (on, user_id))

    def set_can_report(self, user_id: int, on: bool) -> None:
        """Whether someone may report problems from the apps."""
        with self._lock, self._conn:
            self._conn.execute("UPDATE users SET can_report = ? WHERE id = ?", (on, user_id))

    def delete_user(self, user_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self._conn.execute("DELETE FROM progress WHERE user_id = ?", (user_id,))
            self._conn.execute("DELETE FROM languages WHERE user_id = ?", (user_id,))

    def delete_all_users(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM users")
            self._conn.execute("DELETE FROM progress WHERE user_id != 0")
            self._conn.execute("DELETE FROM languages WHERE user_id != 0")

    # Progress in what's watched on demand (see ondemand.py) ----------------------

    def save_progress(
        self,
        user_id: int,
        rating_key: str,
        show_key: str | None,
        position_ms: int,
        duration_ms: int,
        watched: bool,
        now: int,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO progress (user_id, rating_key, show_key, position_ms, duration_ms, "
                "watched, updated_ms) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, rating_key) DO UPDATE SET show_key = excluded.show_key, "
                "position_ms = excluded.position_ms, duration_ms = excluded.duration_ms, "
                "watched = excluded.watched, updated_ms = excluded.updated_ms",
                (user_id, rating_key, show_key, position_ms, duration_ms, int(watched), now),
            )
            # (The newest PROGRESS_KEPT of each person's are kept.)
            self._conn.execute(
                "DELETE FROM progress WHERE user_id = ? AND rating_key NOT IN ("
                "SELECT rating_key FROM progress WHERE user_id = ? "
                "ORDER BY updated_ms DESC LIMIT ?)",
                (user_id, user_id, PROGRESS_KEPT),
            )

    def progress_of(self, user_id: int, keys: list[str]) -> dict[str, tuple[int, bool]]:
        """Someone's progress in these programs: key -> (position, watched)."""
        out: dict[str, tuple[int, bool]] = {}
        with self._lock:
            for at in range(0, len(keys), 500):
                batch = keys[at : at + 500]
                marks = ",".join("?" * len(batch))
                for row in self._conn.execute(
                    "SELECT rating_key, position_ms, watched FROM progress "
                    f"WHERE user_id = ? AND rating_key IN ({marks})",
                    (user_id, *batch),
                ):
                    out[row["rating_key"]] = (row["position_ms"], bool(row["watched"]))
        return out

    def recent_progress(self, user_id: int, most: int) -> list[sqlite3.Row]:
        """Someone's progress, newest first: rating_key, show_key,
        position_ms, watched."""
        with self._lock:
            return self._conn.execute(
                "SELECT rating_key, show_key, position_ms, watched FROM progress "
                "WHERE user_id = ? ORDER BY updated_ms DESC, rowid DESC LIMIT ?",
                (user_id, most),
            ).fetchall()

    def recent_progress_of_show(self, user_id: int, show_key: str, most: int) -> list[sqlite3.Row]:
        """recent_progress, for one show's episodes."""
        with self._lock:
            return self._conn.execute(
                "SELECT rating_key, show_key, position_ms, watched FROM progress "
                "WHERE user_id = ? AND show_key = ? ORDER BY updated_ms DESC, rowid DESC LIMIT ?",
                (user_id, show_key, most),
            ).fetchall()

    def watched_in_shows(self, user_id: int, show_keys: list[str]) -> dict[str, set[str]]:
        """The episodes someone has watched of these shows: show -> keys."""
        out: dict[str, set[str]] = {}
        with self._lock:
            for at in range(0, len(show_keys), 500):
                batch = show_keys[at : at + 500]
                marks = ",".join("?" * len(batch))
                for row in self._conn.execute(
                    "SELECT show_key, rating_key FROM progress "
                    f"WHERE user_id = ? AND watched = 1 AND show_key IN ({marks})",
                    (user_id, *batch),
                ):
                    out.setdefault(row["show_key"], set()).add(row["rating_key"])
        return out

    # Each person's languages in the apps (see languages.py) ----------------------

    def languages_of(self, user_id: int, keys: list[str]) -> dict[str, Choice]:
        """What someone chose in these places (their own: ''; a show, an
        episode or a movie: its key): key -> what's chosen there, for those
        with anything."""
        out: dict[str, Choice] = {}
        if not keys:
            return out
        marks = ",".join("?" * len(keys))
        with self._lock:
            for row in self._conn.execute(
                "SELECT item_key, audio, captions, caption_language FROM languages "
                f"WHERE user_id = ? AND item_key IN ({marks})",
                (user_id, *keys),
            ):
                captions = row["captions"]
                out[row["item_key"]] = Choice(
                    row["audio"], None if captions is None else bool(captions),
                    row["caption_language"],
                )  # fmt: skip
        return out

    def save_languages(self, user_id: int, key: str, chosen: Choice, now: int, keep: int) -> None:
        """Keeps what someone chose in one place, and only the `keep` newest
        places of theirs besides their own."""
        captions = None if chosen.captions is None else int(chosen.captions)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO languages (user_id, item_key, audio, captions, caption_language, "
                "updated_ms) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, item_key) DO UPDATE SET audio = excluded.audio, "
                "captions = excluded.captions, caption_language = excluded.caption_language, "
                "updated_ms = excluded.updated_ms",
                (user_id, key, chosen.audio, captions, chosen.caption_language, now),
            )
            self._conn.execute(
                "DELETE FROM languages WHERE user_id = ? AND item_key != '' AND item_key NOT IN ("
                "SELECT item_key FROM languages WHERE user_id = ? AND item_key != '' "
                "ORDER BY updated_ms DESC, rowid DESC LIMIT ?)",
                (user_id, user_id, keep),
            )

    def clear_languages(self, user_id: int, key: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM languages WHERE user_id = ? AND item_key = ?", (user_id, key)
            )

    def add_session(
        self,
        token_hash: str,
        user_id: int,
        now: int,
        keep: int,
        app: str = "",
        device_id: int | None = None,
        unlocked: bool = False,
    ) -> None:
        """Signs a browser (or `app`, one of StationPlay's; on a linked
        device, from its picker: `device_id`, and `unlocked` when picked
        without a PIN) in as a user, keeping only their `keep` newest sign-ins
        (the rest are signed out). On a linked device, whoever was signed in
        there before is signed out."""
        with self._lock, self._conn:
            if device_id is not None:
                self._conn.execute("DELETE FROM sessions WHERE device_id = ?", (device_id,))
            self._conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_ms, seen_ms, app, device_id, "
                "active_ms, unlocked) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (token_hash, user_id, now, now, app, device_id, now, int(unlocked)),
            )
            self._conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash NOT IN ("
                "SELECT token_hash FROM sessions WHERE user_id = ? ORDER BY created_ms DESC, rowid DESC "
                "LIMIT ?)",
                (user_id, user_id, keep),
            )
            self._conn.execute("UPDATE users SET signed_in_ms = ? WHERE id = ?", (now, user_id))

    def session_user(self, token_hash: str, since_ms: int) -> SignedIn | None:
        """Who's signed in with this token, if they were seen since `since_ms`,
        and how (see SignedIn)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT users.*, sessions.seen_ms, sessions.device_id, sessions.app, "
                "sessions.active_ms, sessions.unlocked FROM sessions JOIN users "
                "ON users.id = sessions.user_id WHERE token_hash = ? AND seen_ms >= ?",
                (token_hash, since_ms),
            ).fetchone()
        if row is None:
            return None
        return SignedIn(
            _user(row),
            row["seen_ms"],
            row["device_id"],
            row["app"],
            row["active_ms"],
            bool(row["unlocked"]),
        )

    def session_app(self, token_hash: str) -> str | None:
        """Which app a sign-in is (its app's label, '' for a browser); None
        if there's no such sign-in."""
        with self._lock:
            row = self._conn.execute(
                "SELECT app FROM sessions WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        return row["app"] if row else None

    def seen(self, token_hash: str, now: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET seen_ms = ? WHERE token_hash = ?", (now, token_hash)
            )

    def active(self, token_hash: str, now: int) -> None:
        """Someone used the browser signed in with this token."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET active_ms = ? WHERE token_hash = ?", (now, token_hash)
            )

    def add_device(self, token_hash: str, user_id: int, now: int, keep: int) -> None:
        """Remembers a browser someone signed in on, keeping their `keep`
        newest."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO devices (token_hash, user_id, created_ms) VALUES (?, ?, ?)",
                (token_hash, user_id, now),
            )
            self._conn.execute(
                "DELETE FROM devices WHERE user_id = ? AND token_hash NOT IN ("
                "SELECT token_hash FROM devices WHERE user_id = ? ORDER BY created_ms DESC, rowid DESC "
                "LIMIT ?)",
                (user_id, user_id, keep),
            )

    def device_user(self, token_hash: str) -> int | None:
        """Whose browser this is, if it's one they signed in on."""
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id FROM devices WHERE token_hash = ?", (token_hash,)
            ).fetchone()
        return int(row["user_id"]) if row else None

    def app_sessions(self, since_ms: int) -> list[dict]:
        """The apps signed in (seen since `since_ms`), newest first: {id,
        user, app, created_ms, seen_ms}."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT sessions.rowid AS id, users.name AS user, sessions.app, "
                "sessions.created_ms, sessions.seen_ms FROM sessions JOIN users "
                "ON users.id = sessions.user_id WHERE sessions.app != '' "
                "AND sessions.device_id IS NULL AND seen_ms >= ? "
                "ORDER BY sessions.seen_ms DESC",
                (since_ms,),
            ).fetchall()
        return [dict(row) for row in rows]

    def end_app_session(self, session_id: int) -> str | None:
        """Signs an app out, by its sign-in's id: what it was, or None."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT users.name AS user, sessions.app FROM sessions JOIN users "
                "ON users.id = sessions.user_id WHERE sessions.rowid = ? AND sessions.app != ''",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM sessions WHERE rowid = ?", (session_id,))
        return f"{row['app']} ({row['user']})"

    # Linked devices and their pickers (see devices.py) ----------------------------

    def add_linked_device(
        self, key_hash: str, name: str, now: int, linked_by: str, linked_by_id: int
    ) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO linked_devices (key_hash, name, created_ms, seen_ms, linked_by, "
                "linked_by_id) VALUES (?, ?, ?, ?, ?, ?)",
                (key_hash, name, now, now, linked_by, linked_by_id),
            )
        return int(cur.lastrowid or 0)

    def linked_device(self, key_hash: str) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM linked_devices WHERE key_hash = ?", (key_hash,)
            ).fetchone()

    def linked_devices(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM linked_devices ORDER BY seen_ms DESC"
            ).fetchall()

    def device_seen(self, device_id: int, now: int, name: str | None = None) -> None:
        with self._lock, self._conn:
            if name:
                self._conn.execute(
                    "UPDATE linked_devices SET seen_ms = ?, name = ? WHERE id = ?",
                    (now, name, device_id),
                )
            else:
                self._conn.execute(
                    "UPDATE linked_devices SET seen_ms = ? WHERE id = ?", (now, device_id)
                )

    def unlink_device(self, device_id: int) -> str | None:
        """Unlinks a device (and signs out whoever's signed in on it): its
        name, or None if there's no such device."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT name FROM linked_devices WHERE id = ?", (device_id,)
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM sessions WHERE device_id = ?", (device_id,))
            self._conn.execute("DELETE FROM linked_devices WHERE id = ?", (device_id,))
        return str(row["name"])

    def device_people(self) -> dict[int, dict[int, str]]:
        """How each person is on each device's picker, other than as their
        Show on says: by device, then person."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM device_people").fetchall()
        out: dict[int, dict[int, str]] = {}
        for r in rows:
            out.setdefault(r["device_id"], {})[r["user_id"]] = r["how"]
        return out

    def set_device_person(self, device_id: int, user_id: int, how: str | None) -> None:
        """How a person is on a device's picker (None: only as their Show
        on says)."""
        with self._lock, self._conn:
            if how is None:
                self._conn.execute(
                    "DELETE FROM device_people WHERE device_id = ? AND user_id = ?",
                    (device_id, user_id),
                )
            else:
                self._conn.execute(
                    "INSERT INTO device_people (device_id, user_id, how) VALUES (?, ?, ?) "
                    "ON CONFLICT (device_id, user_id) DO UPDATE SET how = excluded.how",
                    (device_id, user_id, how),
                )

    def set_chosen_devices(self, user_id: int, device_ids: list[int]) -> None:
        """The devices an Admin chose for someone (Selected devices) are
        these: any other they were chosen for, they're no longer on (unless
        they signed in there)."""
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM device_people WHERE user_id = ? AND how = 'chosen'", (user_id,)
            )
            self._conn.executemany(
                "INSERT INTO device_people (device_id, user_id, how) "
                "SELECT id, ?, 'chosen' FROM linked_devices WHERE id = ? "
                "ON CONFLICT (device_id, user_id) DO UPDATE SET how = 'chosen'",
                [(user_id, d) for d in device_ids],
            )

    def set_pin(self, user_id: int, pin_hash: str, no_pin: bool = False) -> None:
        """Someone's PIN ('' for none), and whether that's what they chose
        (`no_pin`: they're not asked for one again)."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE users SET pin = ?, no_pin = ? WHERE id = ?", (pin_hash, no_pin, user_id)
            )

    def pin_hash(self, user_id: int) -> str:
        with self._lock:
            row = self._conn.execute("SELECT pin FROM users WHERE id = ?", (user_id,)).fetchone()
        return str(row["pin"]) if row else ""

    def password_hash(self, user_id: int) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT password FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return str(row["password"]) if row else ""

    def set_show_on(self, user_ids: list[int], show_on: str) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "UPDATE users SET show_on = ? WHERE id = ?", [(show_on, i) for i in user_ids]
            )

    def move_show_on(self, was: tuple[str, ...], now: str) -> int:
        """Everyone shown in one of the ways in `was` is shown as `now`
        instead: how many."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"UPDATE users SET show_on = ? WHERE show_on IN ({', '.join('?' * len(was))})",
                (now, *was),
            )
        return cur.rowcount

    def set_invite(self, user_id: int, code_hash: str, expires_ms: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO invites (user_id, code_hash, expires_ms) VALUES (?, ?, ?) "
                "ON CONFLICT (user_id) DO UPDATE SET code_hash = excluded.code_hash, "
                "expires_ms = excluded.expires_ms",
                (user_id, code_hash, expires_ms),
            )

    def invite(self, user_id: int) -> tuple[str, int] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT code_hash, expires_ms FROM invites WHERE user_id = ?", (user_id,)
            ).fetchone()
        return (row["code_hash"], row["expires_ms"]) if row else None

    def end_invite(self, user_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM invites WHERE user_id = ?", (user_id,))

    def end_session(self, token_hash: str) -> bool:
        """Signs out whoever is signed in with this token: whether anyone was."""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        return cur.rowcount > 0

    # API tokens (see access.py and api.py) -----------------------------------------

    def add_api_token(
        self, token_hash: str, name: str, scope: str, user_id: int, now: int, expires_ms: int | None
    ) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO api_tokens (token_hash, name, scope, user_id, created_ms, expires_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (token_hash, name, scope, user_id, now, expires_ms),
            )
        return int(cur.lastrowid or 0)

    def api_tokens(self) -> list[tuple[dict, User]]:
        """Every API token (newest first), and whose it is."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT api_tokens.id AS token_id, api_tokens.name AS token_name, scope, "
                "api_tokens.created_ms AS token_created_ms, used_ms, expires_ms, users.* "
                "FROM api_tokens JOIN users ON users.id = api_tokens.user_id "
                "ORDER BY api_tokens.id DESC"
            ).fetchall()
        return [(_token_row(row), _user(row)) for row in rows]

    def api_token(self, token_hash: str) -> tuple[dict, User] | None:
        """The API token with this hash, and whose it is."""
        with self._lock:
            row = self._conn.execute(
                "SELECT api_tokens.id AS token_id, api_tokens.name AS token_name, scope, "
                "api_tokens.created_ms AS token_created_ms, used_ms, expires_ms, users.* "
                "FROM api_tokens JOIN users ON users.id = api_tokens.user_id "
                "WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        return (_token_row(row), _user(row)) if row else None

    def api_token_used(self, token_id: int, now: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE api_tokens SET used_ms = ? WHERE id = ?", (now, token_id))

    def delete_api_token(self, token_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM api_tokens WHERE id = ?", (token_id,))
        return cur.rowcount > 0

    def forget_sessions_before(self, seen_ms: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM sessions WHERE seen_ms < ?", (seen_ms,))

    def add_access_entry(self, time_ms: int, level: str, message: str, keep: int) -> None:
        """Adds an entry to the access log, keeping the newest `keep`."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO access_log (time_ms, level, message) VALUES (?, ?, ?)",
                (time_ms, level, message),
            )
            self._conn.execute(
                "DELETE FROM access_log WHERE id <= ?", (int(cur.lastrowid or 0) - keep,)
            )

    def access_entries(self, limit: int) -> list[tuple[int, str, str]]:
        """The newest `limit` entries in the access log, oldest first: (time
        in ms, level, message)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT time_ms, level, message FROM access_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [(r["time_ms"], r["level"], r["message"]) for r in reversed(rows)]

    # Problems the apps ran into (see problems.py) ------------------------------

    def add_problem(
        self, at_ms: int, fields: dict[str, Any], same_ms: int, keep: int, journals: int
    ) -> bool:
        """Notes a problem that happened at `at_ms`: on the row for the same
        one (the same kind, station, title, detail, app and device) within
        `same_ms` of it, counted again (its journal the newest's, its
        lasting added); otherwise a new row. The `keep` that happened last
        are kept, and the newest `journals` journals. True if it's new."""
        keys = ("kind", "station", "title", "detail", "app", "version", "device", "device_name")
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id FROM problems WHERE last_ms >= ? AND first_ms <= ? AND "
                + " AND ".join(f"{k} IS ?" for k in keys)
                + " ORDER BY last_ms DESC, id DESC LIMIT 1",
                (at_ms - same_ms, at_ms + same_ms, *(fields[k] for k in keys)),
            ).fetchone()
            if row is not None:
                self._conn.execute(
                    "UPDATE problems SET times = times + 1, lasted_ms = lasted_ms + ?, "
                    "journal = CASE WHEN ? >= last_ms AND ? != '' THEN ? ELSE journal END, "
                    "first_ms = MIN(first_ms, ?), last_ms = MAX(last_ms, ?) WHERE id = ?",
                    (fields["lasted_ms"], at_ms, fields["journal"], fields["journal"], at_ms,
                     at_ms, row["id"]),
                )  # fmt: skip
                return False
            self._conn.execute(
                "INSERT INTO problems (first_ms, last_ms, user_id, away, journal, lasted_ms, "
                + ", ".join(keys)
                + ") VALUES (?, ?, ?, ?, ?, ?, "
                + ", ".join("?" for _ in keys)
                + ")",
                (at_ms, at_ms, fields["user_id"], int(fields["away"]), fields["journal"],
                 fields["lasted_ms"], *(fields[k] for k in keys)),
            )  # fmt: skip
            # (By when each happened: what a device sends late goes first.)
            self._conn.execute(
                "DELETE FROM problems WHERE id IN (SELECT id FROM problems "
                "ORDER BY last_ms DESC, id DESC LIMIT -1 OFFSET ?)",
                (keep,),
            )
            self._conn.execute(
                "UPDATE problems SET journal = '' WHERE journal != '' AND id NOT IN "
                "(SELECT id FROM problems WHERE journal != '' ORDER BY last_ms DESC, id DESC "
                "LIMIT ?)",
                (journals,),
            )
            return True

    def problems_since(self, since_ms: int) -> list[dict[str, Any]]:
        """The problems last seen since `since_ms`, the newest first (their
        journals left out: see problem_journal)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, first_ms, last_ms, times, kind, station, title, detail, app, "
                "version, device, device_name, user_id, away, lasted_ms, "
                "journal != '' AS has_journal FROM problems WHERE last_ms >= ? "
                "ORDER BY last_ms DESC, id DESC",
                (since_ms,),
            ).fetchall()
        return [dict(r) for r in rows]

    def problem_journal(self, problem_id: int) -> tuple[int, str] | None:
        """A problem's journal, and when it happened; None if it has none."""
        with self._lock:
            row = self._conn.execute(
                "SELECT last_ms, journal FROM problems WHERE id = ? AND journal != ''",
                (problem_id,),
            ).fetchone()
        return (row["last_ms"], row["journal"]) if row else None

    def forget_problems(self, before_ms: int | None = None) -> None:
        """Forgets the problems last seen before `before_ms` (None: all of them)."""
        with self._lock, self._conn:
            if before_ms is None:
                self._conn.execute("DELETE FROM problems")
            else:
                self._conn.execute("DELETE FROM problems WHERE last_ms < ?", (before_ms,))

    # People's reports (see reports.py) ------------------------------------------------

    def add_report(self, fields: dict[str, Any], keep: int) -> int:
        """Keeps a report (keeping the newest `keep`); its id."""
        names = list(fields)
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"INSERT INTO reports ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                [fields[n] for n in names],
            )
            made = int(cur.lastrowid or 0)
            self._conn.execute("DELETE FROM reports WHERE id <= ?", (made - keep,))
            return made

    def reports_in(self, states: tuple[str, ...]) -> list[sqlite3.Row]:
        """The reports in these states, the oldest first."""
        with self._lock:
            return self._conn.execute(
                f"SELECT * FROM reports WHERE state IN ({', '.join('?' for _ in states)}) "
                "ORDER BY id",
                states,
            ).fetchall()

    def reports_sent(self, day: str, user_id: int | None, address: str) -> list[sqlite3.Row]:
        """The reports someone sent on a day (by address, without a user)."""
        with self._lock:
            if user_id is not None:
                return self._conn.execute(
                    "SELECT * FROM reports WHERE day = ? AND user_id = ?", (day, user_id)
                ).fetchall()
            return self._conn.execute(
                "SELECT * FROM reports WHERE day = ? AND user_id IS NULL AND address = ?",
                (day, address),
            ).fetchall()

    def set_reports(
        self,
        ids: list[int],
        state: str,
        note: str,
        done_ms: int | None,
        only: tuple[str, ...] | None = None,
    ) -> None:
        """Where these reports are now (`only`: those in these states)."""
        if not ids:
            return
        where = f"id IN ({', '.join('?' for _ in ids)})"
        values: list[Any] = [state, note, done_ms, *ids]
        if only:
            where += f" AND state IN ({', '.join('?' for _ in only)})"
            values += only
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE reports SET state = ?, note = ?, done_ms = ? WHERE {where}", values
            )

    def forget_reports(self, done_before_ms: int) -> None:
        """Forgets the reports dealt with before `done_before_ms`."""
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM reports WHERE done_ms IS NOT NULL AND done_ms < ?", (done_before_ms,)
            )

    # Admin alerts (see alerts.py) -------------------------------------------------------

    def kept_alerts(self) -> list[sqlite3.Row]:
        """The alerts kept: those fixed, the first fixed first, then those
        going, the oldest first."""
        with self._lock:
            return self._conn.execute(
                "SELECT kind, about, since_ms, sentence, fixed_ms FROM alerts "
                "ORDER BY fixed_ms IS NULL, fixed_ms, since_ms"
            ).fetchall()

    def keep_alert(
        self,
        kind: str,
        about: str,
        since_ms: int,
        sentence: str,
        fixed_ms: int | None,
        instead_of_ms: int | None = None,
    ) -> None:
        """Keeps an alert as it is now: going, or fixed at `fixed_ms`; in
        place of the one about the same thing since `instead_of_ms`, if
        given (it ended, unsaid)."""
        with self._lock, self._conn:
            if instead_of_ms is not None:
                self._conn.execute(
                    "DELETE FROM alerts WHERE kind = ? AND about = ? AND since_ms = ?",
                    (kind, about, instead_of_ms),
                )
            self._conn.execute(
                "INSERT INTO alerts (kind, about, since_ms, sentence, fixed_ms) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (kind, about, since_ms) "
                "DO UPDATE SET sentence = excluded.sentence, fixed_ms = excluded.fixed_ms",
                (kind, about, since_ms, sentence, fixed_ms),
            )

    def forget_alert(self, kind: str, about: str, since_ms: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM alerts WHERE kind = ? AND about = ? AND since_ms = ?",
                (kind, about, since_ms),
            )

    def forget_fixed_alerts(self, before_ms: int, keep: int) -> None:
        """Forgets the alerts fixed before `before_ms`, and all but the
        `keep` fixed last."""
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM alerts WHERE fixed_ms IS NOT NULL AND (fixed_ms < ? OR rowid NOT IN "
                "(SELECT rowid FROM alerts WHERE fixed_ms IS NOT NULL "
                "ORDER BY fixed_ms DESC LIMIT ?))",
                (before_ms, keep),
            )

    # Viewing (see stats.py) ---------------------------------------------------

    def add_view(
        self,
        channel_id: int,
        start_ms: int,
        end_ms: int,
        watched: list[tuple[str, str, str, float]],
    ) -> None:
        """Records a viewing of a station, and what aired in it: (day, show
        or movie, kind, seconds) for each."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO views (channel_id, start_ms, end_ms) VALUES (?, ?, ?)",
                (channel_id, start_ms, end_ms),
            )
            self._conn.executemany(
                "INSERT INTO watched (channel_id, day, title, kind, seconds) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(channel_id, day, title, kind) DO UPDATE SET seconds = seconds + excluded.seconds",
                [(channel_id, *w) for w in watched],
            )

    def views_since(self, since_ms: int) -> list[tuple[int, int, int]]:
        """(station's id, start, end) of each viewing that ended since `since_ms`."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT channel_id, start_ms, end_ms FROM views WHERE end_ms >= ?", (since_ms,)
            ).fetchall()
        return [(r["channel_id"], r["start_ms"], r["end_ms"]) for r in rows]

    def watched_since(self, since_day: str) -> list[tuple[int, str, str, float]]:
        """(station's id, show or movie, kind, seconds) watched on or since a day."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT channel_id, title, kind, SUM(seconds) AS seconds FROM watched "
                "WHERE day >= ? GROUP BY channel_id, title, kind",
                (since_day,),
            ).fetchall()
        return [(r["channel_id"], r["title"], r["kind"], r["seconds"]) for r in rows]

    def forget_views_before(self, start_ms: int, day: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM views WHERE end_ms < ?", (start_ms,))
            for table in ("watched", "user_watched", "app_watched", "media_watched"):
                self._conn.execute(f"DELETE FROM {table} WHERE day < ?", (day,))

    def add_app_watching(self, rows: list[tuple[int, str, int, str, str, str, float]]) -> None:
        """Adds what StationPlay's users watched on stations in its apps:
        (their id, name, station's id, day, show or movie, kind, seconds)
        for each. (Kept with their name now: the one given may be from
        before they were renamed.)"""
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO app_watched (user_id, user_name, channel_id, day, title, kind, "
                f"seconds) VALUES (?, {_NAME_NOW}, ?, ?, ?, ?, ?) "
                "ON CONFLICT (user_id, channel_id, day, title, kind) DO UPDATE SET "
                "seconds = seconds + excluded.seconds, user_name = excluded.user_name",
                [(r[0], r[0], *r[1:]) for r in rows],
            )

    def app_watched_since(self, since_day: str) -> list[tuple[int, str, int, str, str, float]]:
        """(StationPlay's id for a user, their name as of their latest
        viewing, station's id, show or movie, kind, seconds) watched in the
        apps on or since a day."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id, user_name, MAX(day) AS last_day, channel_id, title, kind, "
                "SUM(seconds) AS seconds FROM app_watched WHERE day >= ? "
                "GROUP BY user_id, user_name, channel_id, title, kind",
                (since_day,),
            ).fetchall()
        names = _latest_names(rows)
        summed: dict[tuple[int, int, str, str], float] = {}
        for r in rows:
            key = (r["user_id"], r["channel_id"], r["title"], r["kind"])
            summed[key] = summed.get(key, 0.0) + r["seconds"]
        return [
            (user, names[user], channel_id, title, kind, seconds)
            for (user, channel_id, title, kind), seconds in summed.items()
        ]

    def add_media_watching(self, row: tuple[int, str, str, str, str, int, float]) -> None:
        """Adds what was played on demand: (StationPlay's id for whoever
        played it, their name, day, show or movie, kind, plays, seconds).
        (Kept with their name now, as add_app_watching.)"""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO media_watched (user_id, user_name, day, title, kind, plays, seconds) "
                f"VALUES (?, {_NAME_NOW}, ?, ?, ?, ?, ?) "
                "ON CONFLICT (user_id, day, title, kind) DO UPDATE SET "
                "plays = plays + excluded.plays, seconds = seconds + excluded.seconds, "
                "user_name = excluded.user_name",
                (row[0], row[0], *row[1:]),
            )

    def media_watched_since(self, since_day: str) -> list[tuple[int, str, str, str, int, float]]:
        """(StationPlay's id for whoever played it, their name as of their
        latest play, show or movie, kind, plays, seconds) played on demand
        on or since a day."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id, user_name, MAX(day) AS last_day, title, kind, "
                "SUM(plays) AS plays, SUM(seconds) AS seconds FROM media_watched "
                "WHERE day >= ? GROUP BY user_id, user_name, title, kind",
                (since_day,),
            ).fetchall()
        names = _latest_names(rows)
        summed: dict[tuple[int, str, str], tuple[int, float]] = {}
        for r in rows:
            key = (r["user_id"], r["title"], r["kind"])
            plays, seconds = summed.get(key, (0, 0.0))
            summed[key] = (plays + r["plays"], seconds + r["seconds"])
        return [
            (user, names[user], title, kind, plays, seconds)
            for (user, title, kind), (plays, seconds) in summed.items()
        ]

    def add_user_watching(self, rows: list[tuple[str, str, int, str, str, str, float]]) -> None:
        """Adds what Plex users watched: (Plex's id for them, their name,
        station's id, day, show or movie, kind, seconds) for each."""
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO user_watched (user_id, user_name, channel_id, day, title, kind, "
                "seconds) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (user_id, channel_id, day, title, kind) DO UPDATE SET "
                "seconds = seconds + excluded.seconds, user_name = excluded.user_name",
                rows,
            )

    def user_watched_since(self, since_day: str) -> list[tuple[str, str, int, str, str, float]]:
        """(Plex's id for a user, their name as of their latest viewing,
        station's id, show or movie, kind, seconds) watched on or since a day."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id, user_name, MAX(day) AS last_day, channel_id, title, kind, "
                "SUM(seconds) AS seconds FROM user_watched WHERE day >= ? "
                "GROUP BY user_id, user_name, channel_id, title, kind",
                (since_day,),
            ).fetchall()
        latest: dict[str, tuple[str, str]] = {}
        for r in rows:
            if r["user_id"] not in latest or r["last_day"] > latest[r["user_id"]][0]:
                latest[r["user_id"]] = (r["last_day"], r["user_name"])
        summed: dict[tuple[str, int, str, str], float] = {}
        for r in rows:
            key = (r["user_id"], r["channel_id"], r["title"], r["kind"])
            summed[key] = summed.get(key, 0.0) + r["seconds"]
        return [
            (user, latest[user][1], channel_id, title, kind, seconds)
            for (user, channel_id, title, kind), seconds in summed.items()
        ]

    @staticmethod
    def _era(row: sqlite3.Row, items: list[Item]) -> Era:
        return Era(
            id=row["id"],
            channel_id=row["channel_id"],
            start_ms=row["start_ms"],
            epoch_ms=row["epoch_ms"],
            seed=row["seed"],
            order_mode=row["order_mode"],
            chained=bool(row["chained"]),
            first_pass=json.loads(row["first_pass"]) if row["first_pass"] else None,
            tail=[tuple(t) for t in json.loads(row["tail"])] if row["tail"] else [],
            created_ms=row["created_ms"],
            reason=row["reason"],
            added=row["added"],
            removed=row["removed"],
            items=items,
            special=_special(row["special"]),
        )

    @staticmethod
    def _channel(row: sqlite3.Row) -> Channel:
        settings: dict[str, Any] = {
            c: bool(row[c]) if c in _FLAGS else row[c] for c, _, _ in STATION_SETTINGS
        }
        settings["blocks"] = [b for b in _json_list(settings["blocks"]) if isinstance(b, dict)]
        settings["feature_source"] = _json_dict(settings["feature_source"])
        return Channel(
            id=row["id"],
            number=row["number"],
            name=row["name"],
            sources=json.loads(row["sources"] or "[]"),
            logo=row["logo"],
            **settings,
            created_by=row["created_by"],
            created_ms=row["created_ms"],
            created_exact=bool(row["created_exact"]),
        )


# A StationPlay user's name now, by their id (the first value given), or else
# the name given (the second): someone renamed while they watched is kept
# under their new name.
_NAME_NOW = "COALESCE((SELECT name FROM users WHERE id = ?), ?)"


def _latest_names(rows: list[sqlite3.Row]) -> dict[Any, str]:
    """Each user's name as of their latest day among `rows`."""
    latest: dict[Any, tuple[str, str]] = {}
    for r in rows:
        if r["user_id"] not in latest or r["last_day"] > latest[r["user_id"]][0]:
            latest[r["user_id"]] = (r["last_day"], r["user_name"])
    return {user: name for user, (_, name) in latest.items()}


def _json_list(text: str | None) -> list:
    try:
        value = json.loads(text or "[]")
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def _json_dict(text: str | None) -> dict:
    try:
        value = json.loads(text or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _user(row: sqlite3.Row) -> User:
    return User(
        row["id"], row["name"], row["role"], row["created_ms"], row["signed_in_ms"],
        row["max_stations"], row["level_id"], bool(row["pin"]), row["show_on"],
        bool(row["password"]), bool(row["no_pin"]), bool(row["own_password"]),
        bool(row["can_report"]),
    )  # fmt: skip


def _token_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["token_id"],
        "name": row["token_name"],
        "scope": row["scope"],
        "created_ms": row["token_created_ms"],
        "used_ms": row["used_ms"],
        "expires_ms": row["expires_ms"],
    }


def _json_or_null(value: list | None) -> str | None:
    return None if value is None else json.dumps(value)


def _items_json(items: list[Item]) -> str:
    return json.dumps([asdict(i) for i in items])


def _items_from_json(text: str) -> list[Item]:
    out = []
    for value in _json_list(text):
        if not isinstance(value, dict):
            continue
        try:
            segments, breaks = value.pop("segments", None), value.pop("breaks", None)
            out.append(
                Item(
                    **value,
                    segments=tuple((int(a), int(b)) for a, b in segments) if segments else None,
                    breaks=tuple((str(f), int(ms)) for f, ms in breaks) if breaks else None,
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def _load_segments(text: str | None) -> Segments | None:
    if not text:
        return None
    return tuple((int(a), int(b)) for a, b in json.loads(text))


def _settings_row(settings: dict) -> dict:
    """Station settings as stored: only those given, sources as JSON."""
    out = {k: settings[k] for k in _CHANNEL_COLUMNS if settings.get(k) is not None}
    for listed in ("sources", "blocks"):
        if listed in out:
            out[listed] = json.dumps(list(out[listed]))
    if "feature_source" in out:
        out["feature_source"] = json.dumps(dict(out["feature_source"]))
    for flag in _FLAGS & out.keys():
        out[flag] = int(out[flag])
    return out


def _scan_record(row: sqlite3.Row) -> ScanRecord:
    values = dict(row)
    for name in _SCAN_JSON:
        values[name] = json.loads(values[name] or "[]")
    values["kept"] = bool(values["kept"])
    return ScanRecord(**values)


def _special(text: str | None) -> dict | None:
    if not text:
        return None
    try:
        found = json.loads(text)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def _load_breaks(text: str | None) -> Breaks | None:
    if not text:
        return None
    return tuple((str(f), int(ms)) for f, ms in json.loads(text))
