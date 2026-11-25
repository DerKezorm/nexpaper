"""The outbox through the app's store: a queued mail goes out, again after 1, 5, 15, 60 and 180 minutes when the
server could not take it, at once given up when another try would not help; two workers never send one mail twice;
the test mail; the last result for the operator's page."""

from __future__ import annotations

import smtplib
from datetime import timedelta
from typing import Any

import pytest
from post_contract import password


def _configure(app: Any, post: Any) -> str:
    secret = password()
    with app.store() as store:
        checked = post.settings.check(
            host="mail.example.com", port=587, security="starttls", user="robot", sender="robot@example.com"
        )
        post.settings.save(store, checked, secret)
    return secret


def _queue(app: Any, post: Any, to: str = "kim@example.org") -> Any:
    letter = post.letters.compose(
        "invite", to, language="de", values={"by": "Alex", "valid": "7 Tage"}, link="https://notes.example.com/i/x"
    )
    with app.store() as store:
        item_id = post.outbox.queue(store, letter)
        store.commit()
    return item_id


def _run(app: Any, post: Any, now: Any = None) -> int:
    with app.store() as store:
        return int(post.outbox.run_once(store, now))


def test_a_queued_mail_goes_out_once_and_the_page_shows_it(app: Any, post: Any, server: Any) -> None:
    secret = _configure(app, post)
    _queue(app, post)
    assert _run(app, post) == 1
    assert len(server.sent) == 1 and server.logins == [("robot", secret)]
    sent = server.sent[0]
    assert sent["To"] == "kim@example.org" and "Alex" in sent["Subject"] and "robot@example.com" in sent["From"]
    assert _run(app, post) == 0 and len(server.sent) == 1
    with app.store() as store:
        assert store.due(post.common.utcnow() + timedelta(days=1), 10) == []
        assert store.mail_status().last_ok_at is not None


def test_without_a_mail_server_the_mail_waits(app: Any, post: Any, server: Any) -> None:
    _queue(app, post)
    assert _run(app, post) == 0 and server.connections == 0
    _configure(app, post)
    assert _run(app, post) == 1


def test_a_server_that_cannot_be_reached_is_tried_again_and_at_last_given_up(app: Any, post: Any, server: Any) -> None:
    _configure(app, post)
    _queue(app, post)
    now = post.common.utcnow()
    for minutes in post.outbox.RETRY_MINUTES:
        server.fail.append(smtplib.SMTPServerDisconnected("gone"))
        assert _run(app, post, now) == 0
        assert _run(app, post, now + timedelta(minutes=minutes) - timedelta(seconds=5)) == 0
        now += timedelta(minutes=minutes)
    with app.store() as store:
        status = store.mail_status()
    assert status.last_error == "mail_unreachable" and status.last_error_at is not None
    server.fail.append(smtplib.SMTPServerDisconnected("gone"))
    assert _run(app, post, now) == 0
    assert _run(app, post, now + timedelta(days=30)) == 0 and server.sent == []
    assert server.connections == len(post.outbox.RETRY_MINUTES) + 1


def test_a_refused_recipient_is_given_up_at_once_and_the_rest_goes_on(app: Any, post: Any, server: Any) -> None:
    _configure(app, post)
    _queue(app, post, "nobody@example.org")
    _queue(app, post, "kim@example.org")
    server.fail.append(smtplib.SMTPRecipientsRefused({"nobody@example.org": (550, b"no such user")}))
    now = post.common.utcnow()
    assert _run(app, post, now) == 1
    assert [mail["To"] for mail in server.sent] == ["kim@example.org"]
    assert _run(app, post, now + timedelta(days=1)) == 0
    with app.store() as store:
        assert store.mail_status().last_error == "mail_recipient_refused"


def test_two_workers_never_take_the_same_mail(app: Any, post: Any) -> None:
    _configure(app, post)
    item_id = _queue(app, post)
    now = post.common.utcnow()
    with app.store() as first, app.store() as second:
        assert [item.id for item in first.due(now, 10)] == [item_id]
        assert [item.id for item in second.due(now, 10)] == [item_id]
        assert first.claim(item_id, now, now + timedelta(minutes=2)) is True
        first.commit()
        assert second.claim(item_id, now, now + timedelta(minutes=2)) is False
        second.rollback()
    with app.store() as store:
        assert store.due(now + timedelta(minutes=1), 10) == []
        assert [item.id for item in store.due(now + timedelta(minutes=3), 10)] == [item_id]


def test_a_waiting_mail_keeps_its_letter(app: Any, post: Any) -> None:
    letter = post.letters.compose("test", "kim@example.org", language="fr", values={})
    with app.store() as store:
        post.outbox.queue(store, letter)
        store.commit()
    with app.store() as store:
        (item,) = store.due(post.common.utcnow(), 10)
    assert item.letter == letter and item.attempts == 0 and item.error == ""


def test_the_test_mail_goes_out_at_once_or_tells_why_not(app: Any, post: Any, server: Any) -> None:
    with app.store() as store, pytest.raises(post.MailError) as caught:
        post.outbox.test_mail(store, "kim@example.org")
    assert caught.value.code == "mail_off" and caught.value.status == 409
    _configure(app, post)
    with app.store() as store:
        post.outbox.test_mail(store, "kim@example.org", language="de")
    assert len(server.sent) == 1 and server.sent[0]["To"] == "kim@example.org"
    server.fail.append(smtplib.SMTPAuthenticationError(535, b"5.7.8 bad credentials"))
    with app.store() as store, pytest.raises(post.MailError) as caught:
        post.outbox.test_mail(store, "kim@example.org")
    assert caught.value.code == "mail_auth_refused" and "535" in caught.value.detail
    with app.store() as store:
        status = store.mail_status()
    assert status.last_error == "mail_auth_refused" and status.last_ok_at is not None


def test_a_server_that_says_later_is_tried_again(app: Any, post: Any, server: Any) -> None:
    _configure(app, post)
    _queue(app, post)
    server.fail.append(smtplib.SMTPRecipientsRefused({"kim@example.org": (450, b"4.2.0 Greylisted, try again later")}))
    now = post.common.utcnow()
    assert _run(app, post, now) == 0
    assert _run(app, post, now + timedelta(minutes=post.outbox.RETRY_MINUTES[0])) == 1
    assert [mail["To"] for mail in server.sent] == ["kim@example.org"]
