"""What a station's card says about it: its description, and how large its
pictures are, as Plex lists them."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.plex import PlexClient, resolution

from .fakeplex import FakePlex

MIN = 60_000


def test_picture_sizes_as_plex_names_them():
    def media(said):
        return {"Media": [{"videoResolution": said}, {"videoResolution": "sd"}]}

    assert resolution(media("4k")) == "4K"
    assert resolution(media("1080")) == "1080p"
    assert resolution(media("720")) == "720p"
    assert [resolution(media(s)) for s in ("576", "480", "sd", "SD")] == ["SD"] * 4
    assert resolution(media("2160")) == "4K" and resolution(media("8k")) == "4K"
    # Not said, or something else: not known (never guessed).
    assert resolution(media("")) is None and resolution(media("weird")) is None
    assert resolution({}) is None and resolution({"Media": []}) is None


@pytest.fixture
def plex():
    fp = FakePlex()
    fp.add_show("100", "Wagon Train")
    for n in (1, 2, 3):
        fp.add_episode(f"10{n}", "100", 1, n, f"Wagon {n}", f"/tv/w{n}.mkv", 50 * MIN)
    fp.add_show("200", "Gunsmoke")
    for n in (1, 2):
        fp.add_episode(f"20{n}", "200", 1, n, f"Gunsmoke {n}", f"/tv/g{n}.mkv", 25 * MIN)
    return fp


def sized(fp: FakePlex, keys: list[str], said: str) -> None:
    for key in keys:
        fp.episodes[key]["Media"][0]["videoResolution"] = said


def test_a_cards_picture_size_is_one_size_or_mixed(plex, tmp_path):
    sized(plex, ["101", "102", "103"], "1080")
    sized(plex, ["201", "202"], "4k")
    app = create_app(
        Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "data"),
        PlexClient("http://plex.test", "token", transport=plex.transport()),
    )
    with TestClient(app) as client:
        made = client.post(
            "/api/channels",
            json={
                "number": 5,
                "description": "Classic westerns, around the clock.",
                "sources": [{"type": "show", "ratingKey": "100"}],
            },
        ).json()
        assert made["programPictures"] == {"size": "1080p", "counts": {"1080p": 3}}
        assert made["description"] == "Classic westerns, around the clock."
        both = client.post(
            "/api/channels",
            json={
                "number": 6,
                "sources": [
                    {"type": "show", "ratingKey": "100"},
                    {"type": "show", "ratingKey": "200"},
                ],
            },
        ).json()
        assert both["programPictures"] == {"size": "Mixed", "counts": {"1080p": 3, "4K": 2}}
        # Plex not saying: nothing said (rather than a guess).
        plex.add_show("300", "Rawhide")
        plex.add_episode("301", "300", 1, 1, "Rawhide 1", "/tv/r1.mkv", 50 * MIN)
        unknown = client.post(
            "/api/channels", json={"number": 7, "sources": [{"type": "show", "ratingKey": "300"}]}
        ).json()
        assert unknown["programPictures"] is None
