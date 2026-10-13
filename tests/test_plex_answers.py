"""(1.34.1) When Plex doesn't answer as it should, what people read is a
plain sentence: never Plex's address, the path asked for, an HTTP code or
an empty "()". Those go to the log, once a minute at most, for whoever
looks into it."""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from app import plex as plex_module
from app.plex import PlexClient, PlexError

ADDRESS = "http://192.168.1.20:32400"


def answering(error: type[Exception] | None = None, status: int = 200) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if error is not None:
            raise error("", request=request)  # (as httpx says it: often nothing at all)
        return httpx.Response(status, json={"MediaContainer": {}})

    return httpx.MockTransport(handle)


@pytest.mark.parametrize(
    ("error", "status", "said"),
    [
        (httpx.ConnectError, 200, "Plex isn't answering"),
        (httpx.ConnectTimeout, 200, "Plex isn't answering"),
        (httpx.ReadTimeout, 200, "Plex is taking too long to answer"),
        (httpx.RemoteProtocolError, 200, "Plex isn't answering"),
        (None, 500, "Plex had a problem and couldn't answer"),
        (None, 503, "Plex had a problem and couldn't answer"),
        (None, 404, "Plex doesn't have that now. It may have been removed from Plex."),
        (None, 403, "Plex turned down tapiOca's request"),
        (None, 401, "Plex didn't accept the token in PLEX_TOKEN"),
    ],
)
def test_plexs_problems_are_plain_sentences(monkeypatch, caplog, error, status, said):
    monkeypatch.setattr(plex_module, "RETRY_S", 0)
    client = PlexClient(ADDRESS, "token", transport=answering(error, status))
    caplog.set_level(logging.INFO, logger="app.plex")

    async def ask():
        try:
            await client.identity()
        finally:
            await client.close()

    with pytest.raises(PlexError) as got:
        asyncio.run(ask())
    assert str(got.value) == said
    if status >= 400:
        assert got.value.status == status
    # The details are in the log (not the address: Plex's settings have it).
    if status != 401:
        assert "/identity" in caplog.text
        assert ADDRESS not in caplog.text
        assert (error.__name__ if error else f"HTTP {status}") in caplog.text


def test_plexs_details_are_logged_once_a_minute(monkeypatch, caplog):
    monkeypatch.setattr(plex_module, "RETRY_S", 0)
    client = PlexClient(ADDRESS, "token", transport=answering(httpx.ConnectError))
    caplog.set_level(logging.INFO, logger="app.plex")

    async def ask_three_times():
        for _ in range(3):
            with pytest.raises(PlexError):
                await client.identity()
        await client.close()

    asyncio.run(ask_three_times())
    assert caplog.text.count("didn't answer") == 1


def test_what_plex_turned_down_is_remembered_by_kind_not_by_address(monkeypatch, caplog):
    """(1.34.1, the audit) Problems are logged once a minute by what they
    are, not by each address asked: what's remembered stays small however
    many different addresses fail."""
    monkeypatch.setattr(plex_module, "RETRY_S", 0)

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    client = PlexClient(ADDRESS, "token", transport=httpx.MockTransport(handle))
    caplog.set_level(logging.INFO, logger="app.plex")

    async def ask_many():
        for n in range(50):
            with pytest.raises(PlexError):
                await client._get(f"/library/metadata/{n}")
        await client.close()

    asyncio.run(ask_many())
    assert len(client._said) <= 2
    assert caplog.text.count("HTTP 404") == 1


def test_a_plex_that_never_connects_is_given_up_on_soon():
    """A wrong address that nothing answers at (a computer that's off, say)
    is given up on in a few seconds, not the full time an answer may take."""
    client = PlexClient(ADDRESS, "token")
    try:
        timeout = client._client.timeout
        assert timeout.connect is not None and timeout.connect <= plex_module.CONNECT_S <= 5
        assert timeout.read == 15.0
    finally:
        asyncio.run(client.close())


def test_the_example_plex_address_is_the_one_in_the_yaml_and_compose_file():
    """trouble() says when PLEX_URL is still the example: the one tapiOca's
    YAML and compose file have, to change."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for name in ("tapioca-server.yaml", "docker-compose.yml"):
        text = (root / name).read_text(encoding="utf-8")
        assert f'PLEX_URL: "{plex_module.EXAMPLE_URL}"' in text, name
    said = plex_module.trouble(plex_module.EXAMPLE_URL, None)
    assert said.endswith(
        "PLEX_URL is still the example address from tapiOca's YAML: change it to your Plex "
        "server's address, then restart tapiOca."
    )
    assert "example" not in plex_module.trouble("http://192.168.50.2:32400", None)


def test_the_sample_token_left_in_place_isnt_plex_set_up(tmp_path):
    """(The audit of October 13: tapiOca with or without Plex.) Someone
    without Plex who leaves the YAML's sample PLEX_URL and PLEX_TOKEN in
    place hasn't set Plex up: tapiOca doesn't count on Plex (whose absence
    would hold up checking their own folders' files), and setup says what
    to do about the two lines."""
    from pathlib import Path

    from fastapi.testclient import TestClient

    from app import setup
    from app.config import Settings
    from app.main import create_app

    root = Path(__file__).resolve().parent.parent
    for name in ("tapioca-server.yaml", "docker-compose.yml"):
        text = (root / name).read_text(encoding="utf-8")
        assert f'PLEX_TOKEN: "{plex_module.EXAMPLE_TOKEN}"' in text, name
    left = PlexClient(plex_module.EXAMPLE_URL, plex_module.EXAMPLE_TOKEN)
    assert not left.configured and left.sample_token
    assert PlexClient(plex_module.EXAMPLE_URL, "a-real-token").configured
    # (Only both lines, as the YAML has them: a real address with the sample
    # token is Plex set up, and Plex says whether it takes it. Some Plex
    # servers let their own network in without a token, and an update
    # mustn't take Plex away from them: the fourth audit of 1.35.0.)
    real = PlexClient("http://192.168.50.2:32400", plex_module.EXAMPLE_TOKEN)
    assert real.configured and not real.sample_token
    app = create_app(Settings(data_dir=tmp_path / "data", media_dir=str(tmp_path)), left)
    with TestClient(app) as c:
        state = c.get("/api/status").json()["plex"]
        assert state["configured"] is False and state["sample"] is True
        assert not app.state.ctx.library.plex_on
        # (Nor is the example address taken as Plex's, for Tuner access.)
        assert app.state.ctx.tuner.plex_url == ""
    check = setup.plex_check({"configured": False, "sample": True}, None, folders=1)
    assert check.state == "good"
    assert check.lines[1:] == [
        "PLEX_URL and PLEX_TOKEN still have the sample values from tapiOca’s YAML or Compose file.",
        "To use Plex, put your Plex server’s address and token there instead (the README’s "
        "“Finding your Plex token” shows where it is), then restart tapiOca. Without Plex, "
        "delete the two lines.",
    ]
