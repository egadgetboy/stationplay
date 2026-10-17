"""INFO on the tuner (1.37.1, the owner, October 15: "INFO is an app not a
streaming station - so I know it will only be supported as a "station" by
tapioca - not Plex, Emby, etc."). Since 1.36.4, Plex's lineup, its guide and
the playlist leave INFO out once a real station exists; its stream routes
still played it to a Plex, Emby or Jellyfin that had it from before. They
refuse it whenever the lineup leaves it out; while INFO is the only station
(a new tapiOca: Plex's tuner setup wants one), it plays as before."""

from __future__ import annotations

import pytest

from app import infostation, playback

from .test_info_station import SHOW, make

pytestmark = pytest.mark.info_station


@pytest.mark.parametrize("path", ["/auto/v99", "/stream/99"])
def test_the_tuner_never_plays_info_beside_a_real_station(tmp_path, path):
    with make(tmp_path) as client:
        ctx = client.app.state.ctx
        assert (
            client.post("/api/channels", json={"number": 4, "sources": [SHOW]}).status_code == 201
        )
        info = infostation.find(ctx.db.list_channels())
        assert info is not None
        answer = client.get(path)
        assert answer.status_code == 404
        assert answer.json()["detail"] == "INFO is for tapiOca's apps."
        # Never started, so never a failure to count.
        assert info.id not in ctx.broadcasters
        assert ctx.alerts.now() == []


def test_while_info_is_the_only_station_the_tuner_still_has_it(tmp_path, monkeypatch):
    with make(tmp_path) as client:
        ctx = client.app.state.ctx
        assert infostation.others(ctx.db.list_channels()) == 0
        # (Every tuner busy: the answer that comes once past the check, with
        # nothing streamed.)
        monkeypatch.setattr(playback, "all_in_use", lambda ctx, b: [4])
        answer = client.get("/auto/v99")
        assert answer.status_code != 404


def test_tapiocas_apps_still_have_info(tmp_path):
    with make(tmp_path) as client:
        assert (
            client.post("/api/channels", json={"number": 4, "sources": [SHOW]}).status_code == 201
        )
        answer = client.get("/hls/99/index.m3u8")
        assert "INFO is for tapiOca's apps" not in answer.text
        # (Its playlist: not just any answer without the refusal, which a
        # missing station's 404 is too. The cold audit of 1.37.1.)
        assert answer.status_code == 200 and answer.text.startswith("#EXTM3U"), answer.text[:200]
