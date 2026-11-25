"""Nothing may break: every sign-in of the older version still works after the app's migration, by username, by
address where the older version took one; addresses several accounts share count for nothing; open invitations of
the older version stay valid, with the username they fixed."""

from __future__ import annotations

from typing import Any


def test_every_sign_in_of_the_older_version_works_after_the_migration(app: Any) -> None:
    legacy = app.legacy()
    assert len(legacy.logins) >= 6, "the older database needs accounts of every kind"
    assert any(works for _, _, works in legacy.logins) and any(not works for _, _, works in legacy.logins)
    for typed, given, works in legacy.logins:
        reached = app.sign_in(typed, given)
        assert (reached is not None) == works, (typed, works)


def test_open_invitations_of_the_older_version_stay_valid(app: Any, konten: Any) -> None:
    legacy = app.legacy()
    assert legacy.invites, "the older database needs an open invitation"
    with app.store() as store:
        for token in legacy.invites:
            form = konten.invites.invite_form(store, token)
            fixed = legacy.fixed_names.get(token)
            if fixed:
                assert form.username == fixed


def test_the_setup_code_is_never_asked_after_the_migration(app: Any, konten: Any) -> None:
    app.legacy()
    with app.store() as store:
        assert konten.setup.needed(store) is False


def test_every_sign_in_through_a_provider_of_the_older_version_works_after_the_migration(app: Any) -> None:
    legacy = app.legacy()
    assert legacy.provider_logins, "the older database needs an account through a provider"
    assert any(works for _, works in legacy.provider_logins)
    for subject, works in legacy.provider_logins:
        assert (app.provider_sign_in(subject) is not None) == works, (subject, works)
