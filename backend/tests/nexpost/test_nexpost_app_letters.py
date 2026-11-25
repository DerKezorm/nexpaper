"""Since 1.1.0: the app's own letters through the module (reports, notifications, reminders, deadlines): the outbox
keeps the whole letter (its headers, its key), takes a key only once, counts what waits, is nudged right after the
commit, and finds the account's address and language; the test mail carries the app's logo."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

from post_contract import password


def _configure(app: Any, post: Any) -> None:
    with app.store() as store:
        checked = post.settings.check(
            host="mail.example.com", port=587, security="starttls", user="robot", sender="robot@example.com"
        )
        post.settings.save(store, checked, password())


def _deadline(post: Any, to: Any, key: str = "") -> Any:
    return post.app_letters.write(
        to,
        kind="deadline",
        language="de",
        subject="Kündigen bis 30.11.2026: Strom",
        paragraphs=["Die Frist für Strom endet am 30.11.2026."],
        link="https://paper.example.com/documents/7",
        action="Dokument öffnen",
        unsubscribe="https://paper.example.com/api/unsubscribe/abc",
        key=key,
    )


def _logo_of(message: EmailMessage) -> bytes:
    for part in message.walk():
        if part.get_content_type() == "image/png" and part["Content-ID"] == "<logo>":
            return bytes(part.get_payload(decode=True))
    return b""


def test_a_letter_of_the_app_keeps_its_headers_and_key_in_the_outbox(app: Any, post: Any) -> None:
    letter = _deadline(post, "kim@example.org", key="deadline:7:2026-11-30")
    with app.store() as store:
        post.outbox.queue(store, letter)
        store.commit()
    with app.store() as store:
        (item,) = store.due(post.common.utcnow(), 10)
    assert item.letter == letter
    assert item.letter.header("List-Unsubscribe") == "<https://paper.example.com/api/unsubscribe/abc>"
    assert item.letter.key == "deadline:7:2026-11-30"


def test_a_key_goes_into_the_outbox_only_once(app: Any, post: Any, server: Any) -> None:
    _configure(app, post)
    with app.store() as store:
        first = post.outbox.queue(store, _deadline(post, "kim@example.org", key="daily:1:2026-11-25"))
        store.commit()
    with app.store() as store:
        again = post.outbox.queue(store, _deadline(post, "kim@example.org", key="daily:1:2026-11-25"))
        other = post.outbox.queue(store, _deadline(post, "kim@example.org", key="daily:1:2026-11-26"))
        store.commit()
    assert str(again) == str(first) and str(other) != str(first)
    with app.store() as store:
        assert post.outbox.run_once(store) == 2
    with app.store() as store:
        post.outbox.queue(store, _deadline(post, "kim@example.org", key="daily:1:2026-11-25"))
        store.commit()
        assert post.outbox.run_once(store) == 0
    assert len(server.sent) == 2


def test_the_sent_letter_carries_its_headers_and_the_logo(app: Any, post: Any, server: Any) -> None:
    _configure(app, post)
    with app.store() as store:
        post.outbox.queue(store, _deadline(post, "kim@example.org"))
        store.commit()
        post.outbox.run_once(store)
    (sent,) = server.sent
    assert sent["List-Unsubscribe"] == "<https://paper.example.com/api/unsubscribe/abc>"
    assert sent["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert sent["Content-Language"] == "de"
    assert sent["Auto-Submitted"] == "auto-generated"
    assert _logo_of(sent) == post.current().logo


def test_the_outbox_counts_what_waits(app: Any, post: Any, server: Any) -> None:
    with app.store() as store:
        assert post.outbox.waiting(store) == 0
        post.outbox.queue(store, _deadline(post, "kim@example.org"))
        post.outbox.queue(store, _deadline(post, "alex@example.org"))
        store.commit()
    with app.store() as store:
        assert post.outbox.waiting(store) == 2 and post.settings.view(store)["waiting"] == 2
    _configure(app, post)
    with app.store() as store:
        post.outbox.run_once(store)
    with app.store() as store:
        assert post.outbox.waiting(store) == 0


def test_a_queued_mail_nudges_the_outbox_after_the_commit_not_before(app: Any, post: Any, monkeypatch: Any) -> None:
    nudged: list[str] = []
    monkeypatch.setattr(post.outbox, "nudge", lambda: nudged.append("now") or True)
    with app.store() as store:
        post.outbox.queue(store, _deadline(post, "kim@example.org"))
        assert nudged == []
        store.commit()
    assert nudged == ["now"]
    with app.store() as store:
        post.outbox.queue(store, _deadline(post, "alex@example.org"))
        store.rollback()
    with app.store() as store:
        store.commit()
    assert nudged == ["now"]


def test_a_letter_to_an_account_goes_to_its_address_in_its_language(app: Any, post: Any) -> None:
    kim = app.account("kim@example.org", language="fr", name="Kim", confirmed=True)
    alex = app.account("alex@example.org", language="de", name="Alex", confirmed=False)
    with app.store() as store:
        found = post.app_letters.recipient(store, kim)
        assert post.app_letters.recipient(store, alex) is None, "an address that is not confirmed gets no letter"
        assert post.app_letters.recipient(store, 987654) is None
    assert found.address == "kim@example.org" and found.language == "fr"
    letter = post.app_letters.write(found, kind="report", subject="Ta semaine", paragraphs=["Trois tâches."])
    assert letter.to == "kim@example.org" and letter.header("Content-Language") == "fr"


def test_the_test_mail_carries_the_apps_logo(app: Any, post: Any, server: Any) -> None:
    logo = post.current().logo
    assert logo and logo.startswith(b"\x89PNG"), "nexpost.configure(AppConfig(logo=<the app's PNG>)) at start-up"
    _configure(app, post)
    with app.store() as store:
        post.outbox.test_mail(store, "kim@example.org", language="de")
    (sent,) = server.sent
    assert _logo_of(sent) == logo
    html = sent.get_body(("html",)).get_content()
    assert 'src="cid:logo"' in html and post.current().shown_name in sent["Subject"]
