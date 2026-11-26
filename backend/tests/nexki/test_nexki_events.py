"""What went out (K5): a task a person started word for word, sealed, for its owner only; an automatic task as a line
without content; 14 days; clearable now; nothing of it in the log. Copied unchanged into every app."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ki_contract import KEY, package, shared, task

SECRET_TEXT = "The quetzal sleeps in the third drawer"


@pytest.mark.manual_only
def test_a_button_task_is_kept_word_for_word_for_its_owner_only(app: Any, service: Any) -> None:
    shared(app, service.base)
    assert task(app, "owner", SECRET_TEXT).status_code == 200
    events = app.client("owner").get(f"{app.me_prefix}/events").json()
    assert len(events) == 1
    event = events[0]
    assert event["manual"] is True and event["to"] == "local" and event["model"] == "plain" and event["outcome"] == "ok"
    assert SECRET_TEXT in event["sent"]["user"] and event["sent"]["system"]
    assert app.client("other").get(f"{app.me_prefix}/events").json() == []
    assert SECRET_TEXT not in app.dump()


@pytest.mark.automatic_only
def test_an_automatic_task_is_a_line_without_content(app: Any, service: Any) -> None:
    shared(app, service.base)
    app.automatic("owner", SECRET_TEXT)
    events = app.client("owner").get(f"{app.me_prefix}/events").json()
    assert len(events) == 1 and events[0]["manual"] is False and events[0]["sent"] is None
    assert events[0]["chars"] > len(SECRET_TEXT) - 1
    assert SECRET_TEXT not in app.dump()


def test_a_refused_request_is_kept_with_its_reason(app: Any, service: Any) -> None:
    shared(app, service.base, model="fail")
    task(app, "owner", SECRET_TEXT)
    events = app.client("owner").get(f"{app.me_prefix}/events").json()
    assert events[0]["outcome"] == "ai_service_failed"
    if events[0]["manual"]:
        # K-7 (0.1.2): the values of the refusal stay with a button task (``said`` only from the internet).
        assert events[0]["values"]["answered"] == 500 and "said" in events[0]["values"]


def test_an_answer_that_cannot_be_read_is_kept_too(app: Any, service: Any) -> None:
    """K-5 (0.1.2): the text went out, so what went out says so, whatever came back."""
    for number, model in enumerate(("garbled", "shapeless"), start=1):
        shared(app, service.base, model=model)
        task(app, "owner", f"{SECRET_TEXT} {number}")
        events = app.client("owner").get(f"{app.me_prefix}/events").json()
        assert len(events) == number and events[0]["outcome"] == "ai_unreadable", events
        if events[0]["manual"]:
            assert f"{SECRET_TEXT} {number}" in events[0]["sent"]["user"]


@pytest.mark.manual_only
def test_cleared_at_once_and_gone_after_14_days(app: Any, service: Any, monkeypatch: Any) -> None:
    shared(app, service.base)
    found = package(app).client
    monkeypatch.setattr(found, "_now", lambda: datetime.now(UTC) - timedelta(days=15))
    task(app, "owner", "An old text")
    monkeypatch.undo()
    task(app, "owner", "A new text")
    events = app.client("owner").get(f"{app.me_prefix}/events").json()
    assert [event["sent"]["user"].count("A new text") for event in events] == [1]
    owner = app.client("owner")
    assert owner.delete(f"{app.me_prefix}/events").json() == {"cleared": 1}
    assert owner.get(f"{app.me_prefix}/events").json() == []


def test_the_log_carries_neither_text_nor_key(app: Any, keyed: Any, caplog: Any) -> None:
    caplog.set_level(logging.DEBUG)
    shared(app, keyed.base, key=KEY)
    assert task(app, "owner", SECRET_TEXT).status_code == 200
    app.client("operator").post(f"{app.server_prefix}/probe")
    assert caplog.records
    assert SECRET_TEXT not in caplog.text and KEY not in caplog.text and "Done:" not in caplog.text
