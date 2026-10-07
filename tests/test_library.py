"""The library layer (see library.py and docs/library.md): one place every
read of your shows and movies goes through, sending each call to the source
that owns the key it's about."""

from __future__ import annotations

import pytest

from app.db import Item
from app.library import Library, LibraryError, is_folder_key, is_key, is_plex_key
from app.plex import PlexClient, PlexError

from .fakeplex import FakePlex
from .helpers import like_plex


def test_a_keys_shape_says_whose_it_is():
    assert is_plex_key("12345") and not is_folder_key("12345")
    assert is_folder_key("f812") and not is_plex_key("f812")
    assert all(is_key(k) for k in ("1", "f1", "9" * 20))
    bad = ("", "f", "F1", "1f", "f-1", "f 1", "12a", "-1", "1.5", "٣", "9" * 21, "f" + "9" * 20)
    assert not any(is_key(k) for k in bad)


def test_plexs_errors_are_library_errors():
    e = PlexError("Plex says no", 404)
    assert isinstance(e, LibraryError) and e.status == 404 and str(e) == "Plex says no"


@pytest.fixture
def library() -> Library:
    fp = FakePlex()
    fp.add_show("100", "Show")
    fp.add_episode("201", "100", 1, 1, "Pilot", "/tv/Show/S01E01.mkv", 60_000)
    return Library(PlexClient("http://plex.test", "token", transport=like_plex(fp)))


async def test_plexs_keys_go_to_plex(library):
    assert library.configured
    await library.check()
    assert [s["title"] for s in await library.libraries()] != []
    part = await library.current_part("201")
    assert part is not None and part.file == "/tv/Show/S01E01.mkv"
    assert library.stream_url("201", part.key).startswith("http://plex.test/")
    items = await library.items_for_source({"type": "show", "ratingKey": "100"})
    assert [i.rating_key for i in items] == ["201"]
    with pytest.raises(LibraryError) as gone:
        await library.current_part("999")
    assert gone.value.status == 404


async def test_folder_keys_are_never_sent_to_plex(library):
    """Until folder libraries arrive, a folder key is simply not found:
    never asked of Plex, never an error that looks like Plex being away."""
    for ask in (
        library.current_part("f201"),
        library.markers("f201"),
        library.art("f201"),
        library.poster("f201", 100, 150),
        library.clear_logo("f201"),
        library.ids("f201"),
        library.library_items("f1"),
        library.scan_folder("f1", "/tv"),
    ):
        with pytest.raises(LibraryError) as e:
            await ask
        assert e.value.status == 404 and not isinstance(e.value, PlexError)
    assert library.stream_url("f201", "/library/parts/1/file.mkv") is None
    item = Item(
        position=0, start_ms=0, duration_ms=60_000, rating_key="f201", kind="episode", title="Pilot"
    )
    assert await library.find_again(item) is None


def test_the_plex_client_is_looked_up_each_time():
    """The app's Plex client is whatever it holds at the time."""
    clients = [PlexClient("http://one.test", "a"), PlexClient("http://two.test", "b")]
    library = Library(lambda: clients[0])
    assert library.plex is clients[0]
    clients.reverse()
    assert library.plex is clients[0]
