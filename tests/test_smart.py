"""Smart stations: one filter split into stations, one for each decade,
genre... (see smart.py), counted and made from what Plex has."""

from __future__ import annotations

from .test_updates import films, movie_filter  # noqa: F401  (a fixture, and its filter)


def split(client, by: str, **rules) -> list[tuple]:
    res = client.post("/api/smart/split", json={"filter": movie_filter(**rules), "split": by})
    assert res.status_code == 200, res.text
    return [(g["value"], g["matches"]) for g in res.json()["groups"]]


def test_a_filter_split_by_decade(films):  # noqa: F811
    client, _fp = films
    # (E.T. is in both libraries: it counts once.)
    assert split(client, "decade") == [(1970, 1), (1980, 2), (1990, 2), (2000, 1)]
    assert split(client, "decade", genre=["Comedy"]) == [(1990, 1), (2000, 1)]
    # Only the decades the filter has, if it has some.
    assert split(client, "decade", decade=[1980, 2000]) == [(1980, 2), (2000, 1)]


def test_a_filter_split_by_a_tag(films):  # noqa: F811
    client, _fp = films
    # The most matches first; nothing that matches nothing.
    assert split(client, "genre") == [
        ("Action", 2), ("Comedy", 2), ("Family", 2), ("Sci-Fi", 1), ("Thriller", 1),
    ]  # fmt: skip
    assert split(client, "genre", label=["Christmas"]) == [
        ("Comedy", 2), ("Action", 1), ("Family", 1),
    ]  # fmt: skip
    # The ones the filter already names, in its order: a station each.
    assert split(client, "genre", genre=["Thriller", "Comedy", "Western"]) == [
        ("Thriller", 1), ("Comedy", 2),
    ]  # fmt: skip
    assert split(client, "director", director=["Steven Spielberg", "Jon Favreau"]) == [
        ("Steven Spielberg", 2), ("Jon Favreau", 1),
    ]  # fmt: skip
    assert split(client, "label") == [("Christmas", 3)]


def test_making_several_stations_at_once(films):  # noqa: F811
    client, _fp = films
    taken = client.post("/api/channels", json={"number": 101, "sources": [movie_filter()]})
    assert taken.status_code == 201
    stations = [
        {
            "name": "1980s Movies",
            "source": {**movie_filter(decade=[1980]), "title": "Movies: 1980s"},
        },
        {
            "name": "1990s Movies",
            "source": {**movie_filter(decade=[1990]), "title": "Movies: 1990s"},
        },
    ]
    res = client.post("/api/smart/stations", json={"firstNumber": 100, "stations": stations})
    assert res.status_code == 201, res.text
    made = res.json()["made"]
    # The next free numbers from 100 (101 is taken).
    assert [(m["number"], m["name"], m["itemCount"]) for m in made] == [
        (100, "1980s Movies", 2),
        (102, "1990s Movies", 2),
    ]
    assert made[0]["sources"][0]["decade"] == [1980] and res.json()["problems"] == []
    # Set up as new stations are.
    from app.db import NEW_STATION

    assert made[0]["orderMode"] == NEW_STATION["order_mode"] and made[0]["logo"]


def test_smart_stations_are_checked(films):  # noqa: F811
    client, _fp = films
    bad_split = client.post("/api/smart/split", json={"filter": movie_filter(), "split": "genre!"})
    assert bad_split.status_code == 400
    no_library = {"filter": {"type": "filter", "kind": "movie", "libraries": []}, "split": "decade"}
    assert client.post("/api/smart/split", json=no_library).status_code == 400
    # Something that isn't a filter, or that matches nothing, isn't made.
    stations = [
        {"name": "Odd", "source": {"type": "show", "ratingKey": "600"}},
        {"name": "Westerns", "source": movie_filter(genre=["Western"])},
    ]
    res = client.post("/api/smart/stations", json={"firstNumber": 1, "stations": stations})
    assert res.status_code == 400
    assert "Odd: its source isn't a filter" in res.text and "Westerns:" in res.text
    assert client.get("/api/channels").json() == []
    too_many = [{"name": f"S{n}", "source": movie_filter()} for n in range(51)]
    assert (
        client.post(
            "/api/smart/stations", json={"firstNumber": 1, "stations": too_many}
        ).status_code
        == 422
    )


def test_users_can_make_smart_stations_too():
    from app.access import _for_users

    assert _for_users("/api/smart/split", "POST") and _for_users("/api/smart/stations", "POST")


def test_a_number_taken_meanwhile_moves_on_to_the_next(films, monkeypatch):  # noqa: F811
    client, _fp = films
    ctx = client.app.state.ctx
    real = ctx.updater.gather

    async def slow_gather(sources, skip_intros=False):
        # While Plex is asked, someone else takes the number.
        if not ctx.db.get_channel_by_number(100):
            ctx.db.create_channel(100, "Taken", [movie_filter()])
        return await real(sources, skip_intros)

    monkeypatch.setattr(ctx.updater, "gather", slow_gather)
    stations = [{"name": "Mine", "source": {**movie_filter(), "title": "Movies"}}]
    res = client.post("/api/smart/stations", json={"firstNumber": 100, "stations": stations})
    assert res.status_code == 201, res.text
    assert [m["number"] for m in res.json()["made"]] == [101]


def test_plex_going_away_stops_the_rest_and_says_so(films):  # noqa: F811
    client, fp = films
    fp.down = True
    stations = [{"name": f"S{n}", "source": movie_filter(decade=[1980])} for n in range(3)]
    res = client.post("/api/smart/stations", json={"firstNumber": 1, "stations": stations})
    assert res.status_code == 400
    assert "S0 and 2 more weren't made" in res.text


def test_splitting_by_people_needs_some_named_when_plex_doesnt_say(films):  # noqa: F811
    client, _fp = films
    res = client.post("/api/smart/split", json={"filter": movie_filter(), "split": "producer"})
    assert res.status_code == 400 and "choose which producers to make stations for" in res.text
