"""Alert notifications to up to 3 web addresses (notify.py, from 1.34.0):
each message goes to every address, and one failing or slow never holds up
or changes the others; Slack's format; the setting kept so an older
tapiOca still notifies the first address; the API's `more`; and the log
naming only hosts.

The audit of 1.34.0: only saved addresses keep a Last sent (a test of one
typed but not saved keeps nothing), matched by the address, not its place
on the page; each address's line of messages is its own, by the address,
so one moving on the list never puts another behind its backlog; Discord's
markdown in what's sent is written as text, with no link previews; and
1.33.1 reads what 1.34.0 saves."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import notify
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.notify import Notify
from app.plex import PlexClient

from .fakeplex import FakePlex
from .test_alerts import Address, DiscordWebhook

NTFY = "https://ntfy.example.com/stationplay-secret-topic"
DISCORD = "https://discord.com/api/webhooks/1558849916279722034/2j5Kd-secret_token"
SLACK = "https://hooks.slack.com/services/T0001/B0001/slack-secret-key"
GOTIFY = "http://gotify.example.com/message?token=gotify-secret"


class SlackWebhook(Address):
    """Stands in for a Slack incoming webhook, as Slack answers: 400 for
    anything but JSON with its `text`, 200 "ok" once it's taken."""

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        try:
            body = json.loads(request.content)
        except ValueError:
            return httpx.Response(400, content=b"invalid_payload")
        if request.headers.get("content-type") != "application/json" or not isinstance(
            body.get("text") if isinstance(body, dict) else None, str
        ):
            return httpx.Response(400, content=b"invalid_payload")
        return httpx.Response(200, content=b"ok")


class Hosts:
    """Stands in for several web addresses, each by its host."""

    def __init__(self, **by_host: Address) -> None:
        self.by_host = {host.replace("_", "."): one for host, one in by_host.items()}

    async def handle(self, request: httpx.Request) -> httpx.Response:
        return await self.by_host[request.url.host].handle(request)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(tmp_path / "db.sqlite")


@pytest.fixture
def app(tmp_path):
    settings = Settings(plex_url="http://plex.test", plex_token="token", data_dir=tmp_path / "d")
    return create_app(
        settings, PlexClient("http://plex.test", "token", transport=FakePlex().transport())
    )


async def until(what, seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if what():
            return True
        await asyncio.sleep(0.01)
    return what()


class Said:
    """What's said of a message: taken (done) or not (failed)."""

    def __init__(self) -> None:
        self.done = 0
        self.failed = 0

    def took(self) -> None:
        self.done += 1

    def missed(self) -> None:
        self.failed += 1


async def running(sender: Notify) -> asyncio.Task:
    task = asyncio.create_task(sender.run_forever())
    await asyncio.sleep(0)
    return task


async def test_three_addresses_each_get_every_message(db):
    ntfy, discord, slack = Address(), DiscordWebhook(), SlackWebhook()
    sender = Notify(db)
    sender.transport = Hosts(
        ntfy_example_com=ntfy, discord_com=discord, hooks_slack_com=slack
    ).transport
    # (Discord's and Slack's addresses get their own format, whatever's chosen.)
    sender.save(True, NTFY, notify.TEXT, [(DISCORD, notify.TEXT), (SLACK, notify.JSON)])
    assert sender.addresses() == [
        (NTFY, notify.TEXT), (DISCORD, notify.DISCORD), (SLACK, notify.SLACK)
    ]  # fmt: skip
    task = await running(sender)
    said = Said()
    try:
        sender.send("Plex & co: <!channel> can't be reached.", "plex", "started", said.took, said.missed)  # fmt: skip
        sender.send("Plex is back.", "plex", "fixed")
        assert await until(lambda: all(len(a.asked) == 2 for a in (ntfy, discord, slack)))
    finally:
        task.cancel()
    assert ntfy.asked[0].content == b"Plex & co: <!channel> can't be reached."
    assert ntfy.asked[0].headers["title"] == "tapiOca"
    # Discord's: as it is, its markdown written as text (see
    # test_discord_shows_a_station_s_name_as_it_is).
    assert json.loads(discord.asked[0].content)["content"] == (
        "Plex & co: \\<!channel\\> can't be reached."
    )
    # Slack's format: its text, with &, < and > as Slack asks (never a ping).
    assert json.loads(slack.asked[0].content) == {
        "text": "Plex &amp; co: &lt;!channel&gt; can't be reached."
    }
    assert slack.asked[0].headers["content-type"] == "application/json"
    assert [json.loads(slack.asked[1].content)["text"]] == ["Plex is back."]
    assert (said.done, said.failed) == (1, 0)
    # Each one's "Last sent", its own.
    assert sender.last is not None and sender.last.status == "200 OK"
    assert sender.last_of(DISCORD).status == "204 No Content"  # type: ignore[union-attr]
    assert sender.last_of(SLACK).status == "200 OK"  # type: ignore[union-attr]


async def test_one_failing_while_the_others_still_get_theirs(db, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    ntfy, broken, gotify = Address(), Address(answer=500), Address()
    sender = Notify(db)
    sender.transport = Hosts(
        ntfy_example_com=ntfy, discord_com=broken, gotify_example_com=gotify
    ).transport
    sender.save(True, NTFY, notify.TEXT, [(DISCORD, notify.DISCORD), (GOTIFY, notify.JSON)])
    task = await running(sender)
    said = Said()
    try:
        sender.send("tapiOca can't reach Plex.", "plex", "started", said.took, said.missed)
        assert await until(lambda: len(broken.asked) == 2 and ntfy.asked and gotify.asked)
        await asyncio.sleep(0.05)
    finally:
        task.cancel()
    assert len(ntfy.asked) == 1 and len(gotify.asked) == 1  # (taken: never sent again)
    assert json.loads(gotify.asked[0].content)["message"] == "tapiOca can't reach Plex."
    # The others took it, so it's told: a restart never sends it them again.
    assert (said.done, said.failed) == (1, 0)
    assert sender.last.ok and sender.last_of(GOTIFY).ok  # type: ignore[union-attr]
    assert sender.last_of(DISCORD).status == "500 Internal Server Error"  # type: ignore[union-attr]
    # tapiOca's own log names the host only. (The HTTP library's own
    # lines are kept out of it: see main.py.)
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))
    assert "Couldn't notify https://discord.com of an alert: 500" in ours
    assert "secret" not in ours and "webhooks" not in ours


async def test_none_taking_it_is_untold_once(db, monkeypatch):
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    down = Address(answer=503)
    sender = Notify(db)
    sender.transport = down.transport
    sender.save(True, NTFY, notify.TEXT, [(GOTIFY, notify.JSON), (SLACK, notify.SLACK)])
    task = await running(sender)
    said = Said()
    try:
        sender.send("tapiOca can't reach Plex.", "plex", "started", said.took, said.missed)
        assert await until(lambda: len(down.asked) == 6 and said.failed)
        await asyncio.sleep(0.05)
    finally:
        task.cancel()
    assert (said.done, said.failed) == (0, 1)


async def test_a_slow_address_never_delays_the_others(db, monkeypatch):
    monkeypatch.setattr(notify, "WAIT_S", 3.0)
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    slow, discord, slack = Address(wait_s=10.0), DiscordWebhook(), SlackWebhook()
    sender = Notify(db)
    sender.transport = Hosts(
        ntfy_example_com=slow, discord_com=discord, hooks_slack_com=slack
    ).transport
    sender.save(True, NTFY, notify.TEXT, [(DISCORD, notify.DISCORD), (SLACK, notify.SLACK)])
    task = await running(sender)
    said = Said()
    began = time.monotonic()
    try:
        for n in range(3):
            sender.send(f"Station {n} keeps failing.", "station", "started", said.took, said.missed)
        assert await until(lambda: len(discord.asked) == 3 and len(slack.asked) == 3, 1.0)
        took = time.monotonic() - began
        # Meanwhile the slow one has its first, and waits on it.
        assert len(slow.asked) == 1
        # tapiOca stops: what the others took is told; nothing's untold.
        sender.unsent()
    finally:
        task.cancel()
    assert took < 1.0
    assert (said.done, said.failed) == (3, 0)


async def test_stopping_before_any_address_takes_it(db):
    """tapiOca stopping while the only addresses that would take it are
    still sending, or it's still waiting: it's untold (sent again after the
    restart), once."""
    hangs = Address(wait_s=30.0)
    sender = Notify(db)
    sender.transport = hangs.transport
    sender.save(True, NTFY, notify.TEXT, [(GOTIFY, notify.JSON)])
    task = await running(sender)
    first, second = Said(), Said()
    try:
        sender.send("One.", "plex", "started", first.took, first.missed)
        sender.send("Two.", "backups", "started", second.took, second.missed)
        assert await until(lambda: len(hangs.asked) == 2)
        sender.unsent()
        sender.unsent()  # (said once, however often)
    finally:
        task.cancel()
    assert (first.done, first.failed, second.done, second.failed) == (0, 1, 0, 1)


def test_slack_and_its_hooks():
    assert notify.is_slack(SLACK)
    assert notify.is_slack("https://HOOKS.slack.com/workflows/T1/A1/1/x")
    for url in (
        "https://slack.com/services/T/B/x",
        "https://hooks.slack.com.example.com/services/T/B/x",
        "https://example.com/hooks.slack.com",
        "https://mattermost.example.com/hooks/abc",
    ):
        assert not notify.is_slack(url), url
    for chosen in notify.FORMATS:
        assert notify.format_for(SLACK, chosen) == notify.SLACK
        assert notify.format_for(DISCORD, chosen) == notify.DISCORD
    assert notify.format_for("https://mattermost.example.com/hooks/abc", "slack") == "slack"
    assert notify.slack_text("a < b & c > d") == "a &lt; b &amp; c &gt; d"


async def test_slack_format_for_any_address_and_forced_on_slacks(tmp_path, db, monkeypatch):
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    slack = SlackWebhook()
    sender = Notify(db)
    sender.transport = slack.transport
    # Plain text or JSON to Slack's own address: Slack's format, so it's taken.
    for chosen in (notify.TEXT, notify.JSON):
        sent = await sender.post(SLACK, chosen, "Plex is back.", "plex", "fixed")
        assert (sent.ok, sent.status) == (True, "200 OK"), chosen
        assert json.loads(slack.asked[-1].content) == {"text": "Plex is back."}
    # Slack's format to another address (Mattermost, say), when chosen.
    sent = await sender.post(
        "https://chat.example.com/hooks/x", notify.SLACK, "Hi.", "k", "started"
    )
    assert sent.ok and json.loads(slack.asked[-1].content) == {"text": "Hi."}
    # Saved as JSON, it's Slack's; and kept so.
    sender.save(True, NTFY, notify.TEXT, [(SLACK, notify.JSON)])
    assert sender.more == [(SLACK, notify.SLACK)]
    assert Notify(Database(db.path)).more == [(SLACK, notify.SLACK)]
    sender.save(True, SLACK, notify.TEXT, [])
    assert (sender.url, sender.format) == (SLACK, notify.SLACK)


def test_an_upgrade_keeps_the_one_address(db):
    """1.33.x kept one address under `notify` (and how its last message
    went under `notify_last`): it's the first address, as it was."""
    before = {"on": True, "url": NTFY, "format": "json"}
    last = {"at": 1_791_000_000_000, "status": "200 OK", "ok": True, "test": False}
    db.set_meta(notify.META, json.dumps(before))
    db.set_meta(notify.LAST_META, json.dumps(last))
    sender = Notify(db)
    assert (sender.on, sender.url, sender.format, sender.more) == (True, NTFY, "json", [])
    assert sender.addresses() == [(NTFY, "json")]
    assert sender.last == notify.Sent(last["at"], "200 OK", True, False)
    # Saved again as it is, with no others: the same.
    sender.save(True, NTFY, "json", [])
    assert json.loads(db.get_meta(notify.META)) == before


async def test_the_first_address_is_kept_as_before(db, monkeypatch):
    """With 3 addresses saved, `notify` is still {on, url, format} for the
    first, and `notify_last` its last result, so rolling back to 1.33.x
    keeps the first one working; the others are kept apart."""
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    sender = Notify(db)
    sender.transport = Address().transport
    sender.save(True, NTFY, notify.TEXT, [(DISCORD, notify.TEXT), (GOTIFY, notify.JSON)])
    assert json.loads(db.get_meta(notify.META)) == {"on": True, "url": NTFY, "format": "text"}
    assert json.loads(db.get_meta(notify.META_MORE)) == [
        {"url": DISCORD, "format": "discord"}, {"url": GOTIFY, "format": "json"}
    ]  # fmt: skip
    task = await running(sender)
    try:
        sender.send("Plex is back.", "plex", "fixed")
        assert await until(lambda: sender.last_of(GOTIFY) is not None and sender.last)
        assert await until(lambda: sender.last_of(DISCORD) is not None)
    finally:
        task.cancel()
    assert set(json.loads(db.get_meta(notify.LAST_META))) == {"at", "status", "ok", "test"}
    assert set(json.loads(db.get_meta(notify.LAST_MORE))) == {DISCORD, GOTIFY}
    # Rolled back, and the first address changed there (to one that was
    # second): upgraded again, it's first, and listed once.
    db.set_meta(notify.META, json.dumps({"on": True, "url": DISCORD, "format": "text"}))
    again = Notify(Database(db.path))
    assert again.addresses() == [(DISCORD, notify.DISCORD), (GOTIFY, notify.JSON)]


async def test_where_last_sent_is_kept_as_the_list_changes(db, monkeypatch):
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    sender = Notify(db)
    sender.transport = Hosts(ntfy_example_com=Address(), gotify_example_com=Address(500)).transport
    sender.save(True, NTFY, notify.TEXT, [(GOTIFY, notify.JSON)])
    first = await sender.test(NTFY, notify.TEXT)
    second = await sender.test(GOTIFY, notify.JSON)
    assert (sender.last, sender.last_of(GOTIFY)) == (first, second)
    # A test of an address typed, not saved: nothing kept of it, neither
    # its address nor how it went (it may never be saved).
    typed = await sender.test("https://ntfy.example.com/other", notify.TEXT)
    assert typed.ok and sender.last == first and sender.last_of(GOTIFY) == second
    assert sender.last_of("https://ntfy.example.com/other") is None
    assert "other" not in (db.get_meta(notify.LAST_MORE) + db.get_meta(notify.LAST_META))
    # Swapped: each keeps its own.
    sender.save(True, GOTIFY, notify.JSON, [(NTFY, notify.TEXT)])
    assert (sender.last, sender.last_of(NTFY)) == (second, first)
    # The first removed: the second moves up, with its own Last sent.
    sender.save(True, NTFY, notify.TEXT, [])
    assert sender.addresses() == [(NTFY, notify.TEXT)] and sender.last == first
    # A new one first, the first moving to second: nothing sent to the new one yet.
    sender.save(True, "https://ntfy.example.com/new", notify.TEXT, [(NTFY, notify.TEXT)])
    assert (sender.last, sender.last_of(NTFY)) == (None, first)
    # (Changing the only address keeps its Last sent, as before 1.34.0.)
    sender.save(True, "https://ntfy.example.com/other", notify.TEXT, [])
    assert sender.last is None
    await sender.test("https://ntfy.example.com/other", notify.TEXT)
    sender.save(True, "https://ntfy.example.com/third", notify.TEXT, [])
    assert sender.last is not None and sender.last.ok


def test_four_duplicates_and_bad_addresses_refused(db):
    sender = Notify(db)
    sender.save(True, NTFY, notify.TEXT, [(DISCORD, notify.DISCORD)])
    for more, says in (
        ([(DISCORD, "text"), (SLACK, "slack"), (GOTIFY, "json")], "3 web addresses at most"),
        ([(NTFY, "json")], "listed only once"),
        ([(DISCORD, "text"), (" " + DISCORD + " ", "text")], "listed only once"),
        ([(DISCORD, "text"), ("ftp://x.example.com/", "text")], "Web address 3: Enter a web"),
        ([("file:///etc/passwd", "text")], "Web address 2: Enter a web address"),
        ([(GOTIFY, "xml")], "Choose a format"),
    ):
        with pytest.raises(ValueError, match=says):
            sender.save(True, NTFY, notify.TEXT, more)
    # Nothing changed by what was refused.
    assert sender.addresses() == [(NTFY, notify.TEXT), (DISCORD, notify.DISCORD)]
    assert Notify(Database(db.path)).addresses() == sender.addresses()
    # An empty address removes one; with none left, on is refused.
    sender.save(True, NTFY, notify.TEXT, [("", "text"), (GOTIFY, "json")])
    assert sender.addresses() == [(NTFY, notify.TEXT), (GOTIFY, notify.JSON)]
    with pytest.raises(ValueError, match="starts with http"):
        sender.save(True, "", notify.TEXT, [("", "text")])
    # The first left blank: the next moves up.
    sender.save(False, "", notify.TEXT, [(GOTIFY, "json")])
    assert (sender.url, sender.more) == (GOTIFY, [])


def test_the_api(app, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    ntfy, discord, slack = Address(), DiscordWebhook(), SlackWebhook()
    with TestClient(app) as home:
        ctx = app.state.ctx
        ctx.notify.transport = Hosts(
            ntfy_example_com=ntfy, discord_com=discord, hooks_slack_com=slack
        ).transport
        saved = home.put(
            "/api/notify",
            json={"on": True, "url": NTFY, "format": "text",
                  "more": [{"url": DISCORD, "format": "text"}, {"url": SLACK, "format": "json"}]},
        )  # fmt: skip
        assert saved.status_code == 200, saved.text
        got = home.get("/api/notify").json()
        assert got == {
            "on": True, "url": NTFY, "format": "text", "last": None,
            "more": [{"url": DISCORD, "format": "discord", "last": None},
                     {"url": SLACK, "format": "slack", "last": None}],
        }  # fmt: skip
        # A test of a saved address, by its place: its own Last sent.
        tested = home.post("/api/notify/test", json={"format": "slack", "which": 2}).json()
        assert tested["sent"]["ok"] and tested["more"][1]["last"]["test"]
        assert tested["last"] is None and tested["more"][0]["last"] is None
        assert json.loads(slack.asked[0].content) == {"text": notify.TEST_MESSAGE}
        # The first, as before 1.34.0.
        tested = home.post("/api/notify/test", json={}).json()
        assert tested["sent"]["ok"] and tested["last"]["test"] and len(ntfy.asked) == 1
        # Saved without `more`: the others stay.
        home.put("/api/notify", json={"on": True, "url": NTFY, "format": "json"})
        assert len(home.get("/api/notify").json()["more"]) == 2
        # Refused: a 4th, the same one twice, a bad one (nothing changes).
        for more, says in (
            ([DISCORD, SLACK, GOTIFY], "3 web addresses at most"),
            ([DISCORD, DISCORD], "listed only once"),
            (["javascript:alert(1)"], "Web address 2: Enter a web address"),
        ):
            refused = home.put(
                "/api/notify",
                json={"on": True, "url": NTFY, "more": [{"url": u} for u in more]},
            )
            assert refused.status_code == 400 and says in refused.json()["detail"], refused.text
        assert (
            home.post(
                "/api/notify/test", json={"url": "ftp://x.example.com", "which": 1}
            ).status_code
            == 400
        )
        assert home.post("/api/notify/test", json={"which": 3}).status_code == 422
        assert len(home.get("/api/notify").json()["more"]) == 2
        # An alert goes to all three.
        home.portal.call(ctx.alerts.start, "plex", "tapiOca can't reach Plex.")
        for _ in range(100):
            if len(ntfy.asked) == 2 and len(discord.asked) == 1 and len(slack.asked) == 2:
                break
            time.sleep(0.02)
        assert json.loads(ntfy.asked[1].content)["state"] == "started"
        assert json.loads(discord.asked[0].content)["content"] == "tapiOca can't reach Plex."
        assert json.loads(slack.asked[1].content) == {"text": "tapiOca can't reach Plex."}
        # The others removed: as before 1.34.0 again.
        home.put("/api/notify", json={"on": True, "url": NTFY, "format": "text", "more": []})
        assert set(home.get("/api/notify").json()) == {"on", "url", "format", "last"}
        # The log names only the hosts.
        logs = home.get("/api/logs").json()["text"]
    assert (
        "Alert notifications: on, to https://ntfy.example.com, as plain text; "
        "https://discord.com, as Discord; https://hooks.slack.com, as Slack"
    ) in logs
    for secret in ("secret", "/services/", "/api/webhooks"):
        assert secret not in logs, secret


async def test_turned_off_or_removed_meanwhile_is_neither(db):
    """A message still waiting when sending's turned off, or its address
    removed, is left out: neither taken nor untold (as before 1.34.0)."""
    quick = Address(wait_s=0.3)
    sender = Notify(db)
    sender.transport = quick.transport
    sender.save(True, NTFY, notify.TEXT, [(GOTIFY, notify.JSON)])
    task = await running(sender)
    first, second = Said(), Said()
    try:
        sender.send("One.", "plex", "started", first.took, first.missed)
        sender.send("Two.", "backups", "started", second.took, second.missed)
        assert await until(lambda: len(quick.asked) == 2)
        sender.save(False, NTFY, notify.TEXT, [])
        assert await until(lambda: first.done == 1)
        await asyncio.sleep(0.4)
    finally:
        task.cancel()
    assert len(quick.asked) == 2  # (Two never went)
    assert (first.done, first.failed, second.done, second.failed) == (1, 0, 0, 0)


def test_a_test_s_last_sent_is_kept_with_its_saved_address_whatever_its_place(app, monkeypatch):
    """(The audit of 1.34.0: a test was kept by its place on the page, so
    the second address, tested from the first place, became the first's
    Last sent; and one typed in place 2 or 3, never saved, was kept.)"""
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    ntfy, gotify = Address(), Address()
    with TestClient(app) as home:
        ctx = app.state.ctx
        ctx.notify.transport = Hosts(ntfy_example_com=ntfy, gotify_example_com=gotify).transport
        saved = home.put("/api/notify", json={"on": True, "url": NTFY, "format": "text",
                                              "more": [{"url": GOTIFY, "format": "json"}]})  # fmt: skip
        assert saved.status_code == 200, saved.text
        tested = home.post("/api/notify/test",
                           json={"url": GOTIFY, "format": "json", "which": 0}).json()  # fmt: skip
        assert tested["sent"]["ok"] and tested["last"] is None
        assert tested["more"][0]["last"]["ok"] and len(gotify.asked) == 1
        typed = "https://ntfy.example.com/typed-secret-topic"
        tested = home.post("/api/notify/test",
                           json={"url": typed, "format": "text", "which": 1}).json()  # fmt: skip
        assert tested["sent"]["ok"] and tested["last"] is None
        assert "typed-secret" not in json.dumps(tested)
        assert "typed-secret" not in ctx.db.get_meta(notify.LAST_MORE)


async def test_moving_on_the_list_never_puts_one_behind_another_s_backlog(db, monkeypatch):
    """Each address's messages wait in a line of its own, kept by its
    address: when the list changes, a message never waits behind another
    address's, and each address still gets its own one at a time."""
    monkeypatch.setattr(notify, "WAIT_S", 3.0)
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    slow, quick = Address(wait_s=0.5), Address()
    sender = Notify(db)
    sender.transport = Hosts(ntfy_example_com=slow, gotify_example_com=quick).transport
    sender.save(True, NTFY, notify.TEXT, [(GOTIFY, notify.JSON)])
    task = await running(sender)
    try:
        for n in range(3):
            sender.send(f"Station {n} keeps failing.", "station", "started")
        assert await until(lambda: len(quick.asked) == 3, 1.0)
        # The quick one moves up, the slow one (two still waiting) down.
        sender.save(True, GOTIFY, notify.JSON, [(NTFY, notify.TEXT)])
        began = time.monotonic()
        sender.send("Plex is back.", "plex", "fixed")
        assert await until(lambda: len(quick.asked) == 4, 1.0)
        assert time.monotonic() - began < 0.4
        assert await until(lambda: len(slow.asked) == 4, 4.0)
    finally:
        task.cancel()
    # (The slow one's, one at a time: its four in the order sent.)
    said = [r.content.decode() for r in slow.asked]
    assert said == [*(f"Station {n} keeps failing." for n in range(3)), "Plex is back."]


async def test_discord_shows_a_station_s_name_as_it_is(db, monkeypatch):
    """Discord reads markdown, links and mentions in what it's sent: a
    station named with them is written as text there, and no link preview
    is shown. The other formats send it as it is."""
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    discord, ntfy = DiscordWebhook(), Address()
    sender = Notify(db)
    sender.transport = Hosts(discord_com=discord, ntfy_example_com=ntfy).transport
    name = "**Late** _Night_ [Free](https://example.com) `x` > #1 ~~old~~ ||s|| <@123> \\ -"
    message = f"Station 7, {name} keeps failing to start."
    assert (await sender.post(DISCORD, notify.DISCORD, message, "station", "started")).ok
    body = json.loads(discord.asked[0].content)
    assert body["flags"] == 4  # (Discord's SUPPRESS_EMBEDS: no previews)
    content = body["content"]
    special = set("\\*_`~|>[]()#<@-")
    assert not special & set(re.sub(r"\\.", "", content)), content
    assert re.sub(r"\\(.)", r"\1", content) == message  # (shown as it was)
    # Cut to Discord's 2000 characters, never in the middle of one written as text.
    assert (await sender.post(DISCORD, notify.DISCORD, "*" * 1500, "station", "started")).ok
    long = json.loads(discord.asked[-1].content)["content"]
    assert len(long) <= 2000 and not re.search(r"(?<!\\)(\\\\)*\\$", long)
    assert (await sender.post(NTFY, notify.TEXT, message, "station", "started")).ok
    assert ntfy.asked[0].content.decode() == message


def read_as_1_33_1(db: Database) -> tuple:
    """What 1.33.1 reads of the alert setting, as its notify.py does (its
    Notify's __init__ and last, at f131b2c): on, the address, the format (one
    it doesn't know, such as Slack's, as plain text; a Discord webhook's
    always Discord's), and how the last message went."""
    try:
        saved = json.loads(db.get_meta("notify", "") or "{}")
    except ValueError:
        saved = {}
    saved = saved if isinstance(saved, dict) else {}
    on = saved.get("on") is True
    url = str(saved.get("url") or "")
    fmt = saved["format"] if saved.get("format") in ("text", "json", "discord") else "text"
    fmt = "discord" if notify.is_discord(url) else fmt
    try:
        got = json.loads(db.get_meta("notify_last", "") or "null")
        last = (int(got["at"]), str(got["status"]), bool(got["ok"]), bool(got["test"]))
    except (ValueError, TypeError, KeyError):
        last = None
    return on, url, fmt, last


@pytest.mark.parametrize(
    ("first", "fmt", "as_1_33_1"),
    [(NTFY, notify.JSON, "json"), (DISCORD, notify.TEXT, "discord"),
     (SLACK, notify.TEXT, "text"), ("https://chat.example.com/hooks/x", notify.SLACK, "text")],
)  # fmt: skip
async def test_1_33_1_reads_what_1_34_0_saves(db, monkeypatch, first, fmt, as_1_33_1):
    """Rolled back to 1.33.1, the first address goes on, with how its last
    message went. (1.33.1 has no Slack format: it sends a Slack address
    plain text, which the notes say.)"""
    monkeypatch.setattr(notify, "AGAIN_S", 0.0)
    sender = Notify(db)
    sender.transport = Hosts(
        ntfy_example_com=Address(), discord_com=DiscordWebhook(),
        hooks_slack_com=SlackWebhook(), chat_example_com=SlackWebhook(), gotify_example_com=Address(),
    ).transport  # fmt: skip
    sender.save(True, first, fmt, [(GOTIFY, notify.JSON)])
    sent = await sender.test(first, fmt)
    await sender.test(GOTIFY, notify.JSON)
    assert read_as_1_33_1(db) == (
        True, first, as_1_33_1, (sent.at_ms, sent.status, sent.ok, sent.test)
    )  # fmt: skip
    # Off, and the others gone: as 1.33.1 had it.
    sender.save(False, first, fmt, [])
    assert read_as_1_33_1(db)[:3] == (False, first, as_1_33_1)
