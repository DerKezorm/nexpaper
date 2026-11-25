"""What the older version saved keeps working: its mail server with its password, its values of encryption, and the
mails it left waiting."""

from __future__ import annotations

from typing import Any


def test_the_mail_server_of_the_older_version_still_sends(app: Any, post: Any, server: Any) -> None:
    legacy = app.legacy()
    assert legacy.settings.configured, "Legacy.settings: the mail server the older version saved"
    with app.store() as store:
        settings = store.mail_settings()
        assert settings == legacy.settings
        assert settings.security in post.SECURITY
        post.outbox.test_mail(store, "kim@example.org")
    assert len(server.sent) == 1
    if legacy.settings.user:
        assert server.logins == [(legacy.settings.user, legacy.settings.password)]


def test_the_mails_the_older_version_left_waiting_still_go_out(app: Any, post: Any, server: Any) -> None:
    legacy = app.legacy()
    with app.store() as store:
        sent = post.outbox.run_once(store)
    assert sent == legacy.queued and len(server.sent) == legacy.queued


def test_saving_the_settings_again_keeps_the_password_of_the_older_version(app: Any, post: Any) -> None:
    legacy = app.legacy()
    old = legacy.settings
    with app.store() as store:
        checked = post.settings.check(
            host=old.host,
            port=old.port,
            security=old.security,
            user=old.user,
            sender=old.sender,
            sender_name="Renamed",
        )
        post.settings.save(store, checked, None)
    with app.store() as store:
        settings = store.mail_settings()
    assert settings.password == old.password and settings.sender_name == "Renamed"
