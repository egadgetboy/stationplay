"""Where each group of a Media folder's list starts, for the apps' dial
(1.37.0, the owner's handoff "Media that follows the screen", October 14):
`marks` in GET /api/internal/libraries/{key}, for every sort, counted from
the same list as `total` and `items`, after Viewing Levels."""

from __future__ import annotations

import os
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import ondemand
from app.catalog import MOVIE, Entry

from .test_mark_show import app, plex  # noqa: F401  (the fixtures)
from .test_who_sees_what import ADA, KIT, kid_level, sign_in_app

DAY = 86_400_000


@pytest.fixture
def chicago():
    """The server's own time zone, Central (months and years are its)."""
    was = os.environ.get("TZ")
    os.environ["TZ"] = "America/Chicago"
    time.tzset()
    yield
    if was is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = was
    time.tzset()


def ms(text: str) -> int:
    """A local time ("2026-10-14 12:00") in ms since 1970."""
    return int(time.mktime(datetime.strptime(text, "%Y-%m-%d %H:%M").timetuple()) * 1000)


def movie(
    key: str, title: str, added: int | None = None, released: str = "", year: int | None = None
) -> Entry:
    return Entry(key=key, kind=MOVIE, title=title, added_ms=added, released=released, year=year)


def groups(entries: list[Entry], sort: str, now: int) -> list[tuple[int, str, str]]:
    listed = ondemand.sorted_by(entries, sort)
    return [(m["start"], m["kind"], m["value"]) for m in ondemand.marks(listed, sort, now)]


def well_formed(found: list[dict], total: int) -> None:
    """Every sort's: the first at 0, each later, no group twice, all within
    total, and each group's count (to the next start, or total) at least one,
    adding up to total."""
    starts = [m["start"] for m in found]
    assert not found or starts[0] == 0
    assert starts == sorted(set(starts)) and all(s < total for s in starts)
    assert len({(m["kind"], m["value"]) for m in found}) == len(found)
    ends = [*starts[1:], total] if starts else []
    counts = [b - a for a, b in zip(starts, ends, strict=True)]
    assert all(n >= 1 for n in counts) and sum(counts) == (total if found else 0)


def test_by_title_the_letters(chicago):
    films = [movie("1", "Zebra Ride"), movie("2", "9 Lives"), movie("3", "The Orbit Room"),
             movie("4", "Apple Lane"), movie("5", "Élan"), movie("6", "Orchard")]  # fmt: skip
    listed = ondemand.sorted_by(films, "title")
    found = ondemand.marks(listed, "title", ms("2026-10-14 12:00"))
    assert [(m["start"], m["kind"], m["value"]) for m in found] == [
        (0, "letter", "#"), (1, "letter", "A"), (2, "letter", "E"), (3, "letter", "O"), (5, "letter", "Z"),
    ]  # fmt: skip
    # (Exactly the letters' groups.)
    assert [(m["start"], m["value"]) for m in found] == [
        (x["start"], x["letter"]) for x in ondemand.letters(listed)
    ]
    well_formed(found, len(films))


def test_recently_added_this_week_this_years_months_earlier_years(chicago):
    now = ms("2026-10-14 12:00")
    films = [
        movie("1", "A", now - 3_600_000),  # an hour ago: this week
        movie("2", "B", now - 7 * DAY),  # exactly 7 days ago: still this week
        movie("3", "C", now - 7 * DAY - 60_000),  # a minute earlier: October
        movie("4", "D", ms("2026-09-30 23:30")),  # the month's last night, here: September
        movie("5", "E", ms("2026-01-01 00:10")),  # January
        movie("6", "F", ms("2025-12-31 23:50")),  # last year
        movie("7", "G", ms("2019-06-01 12:00")),
        movie("8", "H", None),  # no date
        movie("9", "I", now + DAY),  # later than now: this week
    ]
    assert groups(films, "added", now) == [
        (0, "week", ""), (3, "month", "2026-10"), (4, "month", "2026-09"), (5, "month", "2026-01"),
        (6, "year", "2025"), (7, "year", "2019"), (8, "undated", ""),
    ]  # fmt: skip
    well_formed(ondemand.marks(ondemand.sorted_by(films, "added"), "added", now), len(films))


def test_new_years_day_last_years_december_is_a_year(chicago):
    now = ms("2026-01-01 09:00")
    films = [movie("1", "A", ms("2025-12-30 12:00")), movie("2", "B", ms("2025-12-20 12:00"))]
    assert groups(films, "added", now) == [(0, "week", ""), (1, "year", "2025")]


def test_the_servers_time_zone_decides_the_month(chicago):
    # 11:30 PM on September 30 here is October 1 in UTC: the month is the server's.
    now = ms("2026-12-20 12:00")
    assert groups([movie("1", "A", ms("2026-09-30 23:30"))], "added", now) == [
        (0, "month", "2026-09")
    ]


def test_by_release_decades_then_undated_and_unknown_dates_last(chicago):
    now = ms("2026-10-14 12:00")
    films = [
        movie("1", "A", released="2021-05-01"),
        movie("2", "B", released="1985-02-02"),
        movie("3", "C", year=1989),  # a year, no date: its decade
        movie("4", "D", released="Unknown"),  # not a year: no date, last
        movie("5", "E", released="2026-01-09"),
        movie("6", "F"),
        movie("7", "G", released="1999-12-31"),
    ]
    listed = ondemand.sorted_by(films, "released")
    assert [e.key for e in listed][:5] == ["5", "1", "7", "3", "2"]
    assert {e.key for e in listed[5:]} == {"4", "6"}  # (before, "Unknown" sorted first)
    assert groups(films, "released", now) == [
        (0, "decade", "2020"), (2, "decade", "1990"), (3, "decade", "1980"), (5, "undated", ""),
    ]  # fmt: skip


def test_from_the_same_list_as_total_after_viewing_levels(app):  # noqa: F811
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        assert (
            admin.put(
                f"/api/access/users/{kit['id']}/viewing", json={"level": kid_level(admin)}
            ).status_code
            == 200
        )
        admin.portal.call(admin.app.state.ctx.titles.filled)
        admin.put("/api/app-libraries", json={"libraries": ["1", "2"]})
        shows = admin.get("/api/internal/libraries/1").json()
        assert [(m["start"], m["kind"], m["value"]) for m in shows["marks"]] == [
            (0, "letter", "N"),
            (1, "letter", "P"),
        ]
        assert shows["letters"] == [
            {"letter": "N", "start": 0},
            {"letter": "P", "start": 1},
        ]  # (as before)
        # A Kid never sees Night Shift (TV-MA): it isn't counted.
        as_kit = sign_in_app(app, KIT)
        theirs = TestClient(app).get("/api/internal/libraries/1", headers=as_kit).json()
        assert theirs["total"] == 1
        assert theirs["marks"] == [{"start": 0, "kind": "letter", "value": "P"}]
        for sort in ("title", "added", "released"):
            got = admin.get(f"/api/internal/libraries/2?sort={sort}").json()
            well_formed(got["marks"], got["total"])
        # Narrowed: Unwatched, as the list is.
        admin.post("/api/internal/progress", json={"key": "300", "watched": True})
        left = admin.get("/api/internal/libraries/2?unwatched=1").json()
        assert left["total"] == 0 and left["marks"] == []


def test_styled_letters_are_their_plain_letters_each_mark_once(chicago):
    # (The cold audit, 1.37.0: a styled letter, a mathematical bold Z or a squared A,
    # came out as a capital, sorted before every plain one, and made a second Z mark.)
    films = [movie("1", "\U0001d419ebra"), movie("2", "Zoo"), movie("3", "Apple"),
             movie("4", "\U0001f130rcade"), movie("5", "\uff22oat")]  # fmt: skip
    listed = ondemand.sorted_by(films, "title")
    found = ondemand.marks(listed, "title", ms("2026-10-14 12:00"))
    assert [(m["start"], m["value"]) for m in found] == [(0, "A"), (2, "B"), (3, "Z")]
    assert [(m["start"], m["value"]) for m in found] == [
        (x["start"], x["letter"]) for x in ondemand.letters(listed)
    ]
    well_formed(found, len(films))


def test_release_dates_only_with_a_plain_four_digit_year(chicago):
    # (The cold audit, 1.37.0: a date in other digits counted in its decade
    # but sorted after 2026, so the 2010s came twice; a year under 1000
    # sorted first, as text.)
    now = ms("2026-10-14 12:00")
    films = [movie("1", "A", released="\u0662\u0660\u0661\u0665-01-01"),
             movie("2", "B", released="2022-01-01"), movie("3", "C", released="2015-01-01"),
             movie("4", "D", year=999), movie("5", "E", year=1999, released="Unknown")]  # fmt: skip
    assert [e.key for e in ondemand.sorted_by(films, "released")] == ["2", "3", "5", "4", "1"]
    assert groups(films, "released", now) == [
        (0, "decade", "2020"), (1, "decade", "2010"), (2, "decade", "1990"),
        (3, "decade", "990"), (4, "undated", ""),
    ]  # fmt: skip
    well_formed(ondemand.marks(ondemand.sorted_by(films, "released"), "released", now), 5)


@pytest.fixture
def movies(plex):  # noqa: F811
    """Picnic (PG, 2000) and four more: genres, ratings and years to narrow by."""
    for key, title, year, genre, rating in (
        ("301", "Apple Cart", 1985, "Comedy", "PG"), ("302", "Bandit", 1999, "Drama", "R"),
        ("303", "Cobalt", 2021, "Comedy", "R"), ("304", "Delta", 2015, "Drama", "PG"),
    ):  # fmt: skip
        plex.add_movie(key, title, f"/m/{key}.mkv", 90 * 60_000, year=year, section="2",
                       genres=[genre], contentRating=[rating])  # fmt: skip
    return plex


def test_narrowed_by_genre_unwatched_and_a_level_for_every_sort(app, movies):  # noqa: F811
    # (The cold audit, 1.37.0: what the handoff's tests ask for, every sort.)
    with TestClient(app) as admin:
        admin.post("/api/access/users", json=ADA)
        kit = admin.post("/api/access/users", json={**KIT, "role": "user"}).json()
        level = kid_level(admin)
        assert admin.put(f"/api/access/users/{kit['id']}/viewing",
                         json={"level": level}).status_code == 200  # fmt: skip
        admin.portal.call(admin.app.state.ctx.titles.filled)
        admin.put("/api/app-libraries", json={"libraries": ["1", "2"]})

        def got(client: TestClient, query: str, **kw) -> tuple[int, list[tuple]]:
            body = client.get(f"/api/internal/libraries/2?{query}", **kw).json()
            well_formed(body["marks"], body["total"])
            return body["total"], [(m["start"], m["kind"], m["value"]) for m in body["marks"]]

        assert got(admin, "sort=released") == (5, [
            (0, "decade", "2020"), (1, "decade", "2010"), (2, "decade", "2000"),
            (3, "decade", "1990"), (4, "decade", "1980")])  # fmt: skip
        assert got(admin, "sort=released&genre=Comedy") == (2, [
            (0, "decade", "2020"), (1, "decade", "1980")])  # fmt: skip
        assert got(admin, "sort=title&genre=Drama") == (2, [
            (0, "letter", "B"), (1, "letter", "D")])  # fmt: skip
        # Unwatched: what's left, every sort.
        admin.post("/api/internal/progress", json={"key": "304", "watched": True})
        assert got(admin, "sort=released&unwatched=1") == (4, [
            (0, "decade", "2020"), (1, "decade", "2000"), (2, "decade", "1990"),
            (3, "decade", "1980")])  # fmt: skip
        total, marks = got(admin, "sort=added&unwatched=1")
        assert total == 4 and marks[0][0] == 0
        # A Kid never sees the R-rated two, in any sort.
        as_kit = sign_in_app(app, KIT)
        phone = TestClient(app)
        assert got(phone, "sort=released", headers=as_kit) == (3, [
            (0, "decade", "2010"), (1, "decade", "2000"), (2, "decade", "1980")])  # fmt: skip
        assert got(phone, "sort=title", headers=as_kit) == (3, [
            (0, "letter", "A"), (1, "letter", "D"), (2, "letter", "P")])  # fmt: skip
        assert got(phone, "sort=added", headers=as_kit)[0] == 3
