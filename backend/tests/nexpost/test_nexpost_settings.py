"""The mail server's settings through the app's store: saved and read back, the password sealed and never shown, the
warning without encryption, nothing that breaks a header."""

from __future__ import annotations

from typing import Any

import pytest
from post_contract import password


def _save(app: Any, post: Any, secret: str | None = None, **values: Any) -> Any:
    fields: dict[str, Any] = {
        "host": "mail.example.com",
        "port": 587,
        "security": "starttls",
        "user": "robot",
        "sender": "robot@example.com",
        "sender_name": "",
    }
    fields.update(values)
    with app.store() as store:
        checked = post.settings.check(**fields, password_given=secret is not None)
        post.settings.save(store, checked, secret)
    return checked


def test_a_new_app_sends_nothing_and_shows_its_own_name_as_sender(app: Any, post: Any) -> None:
    with app.store() as store:
        assert store.mail_settings().configured is False
        shown = post.settings.view(store)
    assert shown["configured"] is False and shown["password_set"] is False and shown["warnings"] == []
    assert shown["sender_name_default"] == post.current().shown_name
    assert shown["last_ok_at"] is None and shown["last_error"] == ""


def test_the_settings_come_back_as_saved_and_the_password_only_sealed(app: Any, post: Any) -> None:
    secret = password()
    _save(app, post, secret, sender_name="Our notes", security="tls", port=465)
    with app.store() as store:
        settings = store.mail_settings()
        shown = post.settings.view(store)
    assert (settings.host, settings.port, settings.security, settings.user, settings.sender) == (
        "mail.example.com",
        465,
        post.TLS,
        "robot",
        "robot@example.com",
    )
    assert settings.sender_name == "Our notes" and settings.password == secret and settings.configured
    assert secret not in app.raw_text()
    assert shown["password_set"] is True and secret not in repr(shown)


def test_an_empty_password_field_keeps_the_stored_one_and_removing_it_is_explicit(app: Any, post: Any) -> None:
    secret = password()
    _save(app, post, secret)
    _save(app, post, None, user="robot2")
    with app.store() as store:
        settings = store.mail_settings()
    assert settings.user == "robot2" and settings.password == secret
    _save(app, post, "")
    with app.store() as store:
        assert store.mail_settings().password == ""


def test_without_encryption_the_page_warns_but_allows_it(app: Any, post: Any) -> None:
    checked = _save(app, post, password(), security="none", port=25)
    assert checked.warnings == [post.settings.WARNING_UNENCRYPTED]
    with app.store() as store:
        assert store.mail_settings().security == post.NONE
        assert post.settings.view(store)["warnings"] == [post.settings.WARNING_UNENCRYPTED]
    quiet = post.settings.check(host="mail.example.com", port=25, security="none", sender="robot@example.com")
    assert quiet.warnings == []


def test_nothing_typed_into_the_settings_breaks_a_header(app: Any, post: Any) -> None:
    _save(app, post, None, sender_name="Notes\r\nBcc: someone@example.org", user="robot\nX: y")
    with app.store() as store:
        settings = store.mail_settings()
    assert "\n" not in settings.sender_name and "\r" not in settings.sender_name and "\n" not in settings.user
    with pytest.raises(post.MailError) as caught:
        post.settings.check(
            host="mail.example.com", port=587, security="starttls", sender="a@example.com\nBcc: b@example.org"
        )
    assert caught.value.code == "mail_address_invalid"


@pytest.mark.parametrize(
    ("values", "code"),
    [
        ({"port": 0}, "mail_settings_invalid"),
        ({"port": "abc"}, "mail_settings_invalid"),
        ({"security": "maybe"}, "mail_settings_invalid"),
        ({"sender": ""}, "mail_settings_invalid"),
        ({"sender": "not an address"}, "mail_address_invalid"),
    ],
)
def test_what_cannot_work_is_refused(app: Any, post: Any, values: dict[str, Any], code: str) -> None:
    fields: dict[str, Any] = {
        "host": "mail.example.com",
        "port": 587,
        "security": "starttls",
        "sender": "a@example.com",
    }
    with pytest.raises(post.MailError) as caught:
        post.settings.check(**{**fields, **values})
    assert caught.value.code == code and caught.value.status == 422


def test_an_empty_server_turns_mail_off(app: Any, post: Any) -> None:
    _save(app, post, password())
    _save(app, post, None, host="", sender="")
    with app.store() as store:
        assert store.mail_settings().configured is False
