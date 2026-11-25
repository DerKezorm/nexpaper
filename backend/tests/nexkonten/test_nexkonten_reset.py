"""A forgotten password: by mail to a confirmed address of one's own, or by a link from the operator. The operator
never sets a password; a link works once and ends every session."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from konten_contract import password


@pytest.mark.parametrize("typed", ["alex", "ALEX", "alex@example.com", "Alex@Example.COM"])
def test_a_person_asks_by_username_or_address_and_the_link_goes_to_the_confirmed_address(
    app: Any, konten: Any, typed: str
) -> None:
    alex = app.seed("alex", email="Alex@example.com", password=password())
    with app.store() as store:
        letter = konten.resets.forgot(store, typed)
    assert letter.kind == konten.MAIL_RESET and letter.to == "Alex@example.com" and letter.account_id == alex
    assert letter.hours == 1 and letter.token


@pytest.mark.parametrize(
    ("seeded", "typed"),
    [
        ({"email": "alex@example.com", "email_confirmed": False}, "alex"),
        ({"email": "alex@example.com", "email_confirmed": False}, "alex@example.com"),
        ({"email": ""}, "alex"),
        ({"email": "alex@example.com", "blocked": True}, "alex"),
        ({"email": "alex@example.com", "password": None}, "alex"),
        ({"email": "alex@example.com"}, "nobody"),
        ({"email": "alex@example.com"}, "nobody@example.com"),
    ],
)
def test_no_link_goes_out_where_it_must_not(app: Any, konten: Any, seeded: dict[str, Any], typed: str) -> None:
    if seeded.get("blocked") and not app.blocking:
        return  # the app blocks no accounts (StandardAdapter.blocking)
    values: dict[str, Any] = {"password": password(), **seeded}
    app.seed("alex", **values)
    with app.store() as store:
        assert konten.resets.forgot(store, typed) is None


def test_an_address_two_accounts_share_finds_nobody_but_a_username_gets_its_link_there(app: Any, konten: Any) -> None:
    first = app.seed("first", email="shared@example.com", password=password())
    second = app.seed("second", email="Shared@example.com", password=password())
    with app.store() as store:
        assert konten.resets.forgot(store, "shared@example.com") is None
        by_first = konten.resets.forgot(store, "first")
        by_second = konten.resets.forgot(store, "second")
    assert (by_first.account_id, by_first.to) == (first, "shared@example.com")
    assert (by_second.account_id, by_second.to) == (second, "Shared@example.com")


def test_the_link_sets_a_new_password_once_and_ends_every_session(app: Any, konten: Any) -> None:
    old = password()
    alex = app.seed("alex", email="alex@example.com", password=old)
    session = app.open_session(alex)
    with app.store() as store:
        token = konten.resets.forgot(store, "alex").token
        assert konten.resets.reset_state(store, token).id == alex
    new = password()
    with app.store() as store:
        konten.resets.use_reset(store, token, new)
    assert app.session_alive(session) is False
    assert app.sign_in("alex", new) == alex
    assert app.sign_in("alex", old) is None
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.resets.use_reset(store, token, password())
    assert caught.value.code == "reset_invalid"


def test_a_short_password_leaves_the_link_usable(app: Any, konten: Any) -> None:
    alex = app.seed("alex", email="alex@example.com", password=password())
    with app.store() as store:
        token = konten.resets.forgot(store, "alex").token
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.resets.use_reset(store, token, "short")
    assert caught.value.code == "password_too_short"
    with app.store() as store:
        assert konten.resets.use_reset(store, token, password()).account.id == alex


def test_a_link_a_person_asked_for_holds_one_hour(app: Any, konten: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    app.seed("alex", email="alex@example.com", password=password())
    with app.store() as store:
        token = konten.resets.forgot(store, "alex").token
    now = konten.common.utcnow()
    monkeypatch.setattr(konten.common, "utcnow", lambda: now + timedelta(minutes=61))
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.resets.use_reset(store, token, password())
    assert caught.value.code == "reset_expired"


def test_two_requests_with_one_link_set_one_password(
    app: Any, konten: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    alex = app.seed("alex", email="alex@example.com", password=password())
    with app.store() as store:
        token = konten.resets.forgot(store, "alex").token
    first, second = password(), password()
    with app.store() as one, app.store() as other:
        found = other.find_reset(token)
        monkeypatch.setattr(other, "find_reset", lambda key: found)
        konten.resets.use_reset(one, token, first)
        with pytest.raises(konten.AccountError) as caught:
            konten.resets.use_reset(other, token, second)
    assert caught.value.code == "reset_invalid"
    assert app.sign_in("alex", first) == alex
    assert app.sign_in("alex", second) is None


def test_the_operator_link_goes_by_mail_to_a_confirmed_address_else_it_is_shown(
    app: Any, konten: Any, operator: Any
) -> None:
    operator_id, secret = operator
    alex = app.seed("alex", email="alex@example.com", password=password())
    kim = app.seed("kim", email="kim@example.com", email_confirmed=False, password=None)
    with app.store() as store:
        mailed = konten.resets.reset_link(store, alex, actor_id=operator_id, password=secret, mail=True)
        shown = konten.resets.reset_link(store, kim, actor_id=operator_id, password=secret, mail=True)
        offline = konten.resets.reset_link(store, alex, actor_id=operator_id, password=secret, mail=False)
    assert mailed.token == "" and mailed.mail.to == "alex@example.com" and mailed.mail.hours == 24
    assert shown.mail is None and shown.token
    assert offline.mail is None and offline.token
    new = password()
    with app.store() as store:
        konten.resets.use_reset(store, shown.token, new)
    # An account through a provider only signs in with a password from now on.
    assert app.sign_in("kim", new) == kim


def test_the_operator_link_needs_the_operators_own_password(app: Any, konten: Any, operator: Any) -> None:
    operator_id, secret = operator
    member_secret = password()
    alex = app.seed("alex", password=member_secret)
    kim = app.seed("kim", password=password())
    for actor, given, target, code in (
        (operator_id, secret + "x", alex, "wrong_password"),
        (alex, member_secret, kim, "not_allowed"),
        (operator_id, secret, operator_id, "use_account_page"),
    ):
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            konten.resets.reset_link(store, target, actor_id=actor, password=given)
        assert caught.value.code == code


def test_a_mail_that_did_not_go_out_leaves_no_link(app: Any, konten: Any, operator: Any) -> None:
    operator_id, secret = operator
    alex = app.seed("alex", email="alex@example.com", password=password())
    with app.store() as store:
        token = konten.resets.reset_link(store, alex, actor_id=operator_id, password=secret, mail=True).mail.token
        konten.resets.reset_mail_failed(store, alex)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.resets.reset_state(store, token)
    assert caught.value.code == "reset_invalid"


def test_an_account_through_a_provider_only_gets_a_first_password_only_with_password_sign_in_on(
    app: Any, konten: Any, operator: Any
) -> None:
    operator_id, secret = operator
    kim = app.seed("kim", email="kim@example.com", password=None)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.resets.reset_link(store, kim, actor_id=operator_id, password=secret, password_login=False)
    assert caught.value.code == "password_login_off"
    with app.store() as store:
        assert konten.resets.reset_link(store, kim, actor_id=operator_id, password=secret).token


def test_with_password_sign_in_off_only_the_operator_sets_one(app: Any, konten: Any, operator: Any) -> None:
    operator_id, secret = operator
    alex = app.seed("alex", password=password())
    other = app.seed("other", password=password(), operator=True)
    with app.store() as store:
        member_token = konten.resets.reset_link(store, alex, actor_id=operator_id, password=secret).token
        operator_token = konten.resets.reset_link(store, other, actor_id=operator_id, password=secret).token
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.resets.use_reset(store, member_token, password(), password_login=False)
    assert caught.value.code == "reset_invalid"
    with app.store() as store:
        done = konten.resets.use_reset(store, operator_token, password(), password_login=False)
        assert done.account.id == other


def test_a_new_password_ends_browser_sign_ins_and_lists_what_still_has_access(app: Any, konten: Any) -> None:
    alex = app.seed("alex", email="alex@example.com", password=password())
    browser, waiting, device = (app.open_session(alex, kind) for kind in ("browser", "waiting", "device"))
    with app.store() as store:
        token = konten.resets.forgot(store, "alex").token
        done = konten.resets.use_reset(store, token, password())
    assert done.origin == konten.RESET_SELF and done.next == konten.NEXT_SESSION
    assert not app.session_alive(browser) and not app.session_alive(waiting) and app.session_alive(device)
    assert len(done.remaining) >= 1
    with app.store() as store:
        assert konten.resets.disconnect_all(store, alex) >= 1
    assert not app.session_alive(device)


def test_after_a_new_password_an_account_with_a_second_factor_is_asked_for_it(app: Any, konten: Any) -> None:
    alex = app.seed("alex", email="alex@example.com", password=password(), second_factor="active")
    cases = [("alex", konten.NEXT_SECOND_FACTOR)]
    kim = None
    if app.required_second_factor:
        kim = app.seed("kim", email="kim@example.com", password=password(), second_factor="required")
        cases.append(("kim", konten.NEXT_SECOND_FACTOR_SETUP))
    for typed, expected in cases:
        with app.store() as store:
            token = konten.resets.forgot(store, typed).token
            assert konten.resets.use_reset(store, token, password()).next == expected
    assert alex != kim


def test_the_operator_link_holds_one_seven_or_thirty_days(app: Any, konten: Any, operator: Any) -> None:
    operator_id, secret = operator
    alex = app.seed("alex", password=password())
    with app.store() as store:
        default = konten.resets.reset_link(store, alex, actor_id=operator_id, password=secret)
        month = konten.resets.reset_link(store, alex, actor_id=operator_id, password=secret, days=30)
        with pytest.raises(konten.AccountError) as caught:
            konten.resets.reset_link(store, alex, actor_id=operator_id, password=secret, days=2)
    assert caught.value.code == "invalid_days"
    now = konten.common.utcnow()
    assert round((default.expires_at - now).total_seconds() / 3600) == 24
    assert round((month.expires_at - now).total_seconds() / 86400) == 30


def test_a_blocked_account_gets_a_link_and_stays_blocked(app: Any, konten: Any, operator: Any) -> None:
    if not app.blocking:
        return  # the app blocks no accounts (StandardAdapter.blocking)
    operator_id, secret = operator
    gone = app.seed("gone", password=password(), blocked=True)
    new = password()
    with app.store() as store:
        token = konten.resets.reset_link(store, gone, actor_id=operator_id, password=secret).token
        done = konten.resets.use_reset(store, token, new)
    assert done.origin == konten.RESET_OPERATOR and done.next == konten.NEXT_SIGN_IN
    assert app.sign_in("gone", new) is None


def test_the_emergency_command_makes_a_link_without_an_operator(app: Any, konten: Any) -> None:
    alex = app.seed("alex", email="alex@example.com", password=password())
    with app.store() as store:
        made = konten.resets.server_reset_link(store, "ALEX")
        with pytest.raises(konten.AccountError) as caught:
            konten.resets.server_reset_link(store, "nobody")
    assert caught.value.code == "not_found" and made.mail is None and made.token
    with app.store() as store:
        assert store.find_reset(made.token).origin == konten.RESET_SERVER
        assert konten.resets.use_reset(store, made.token, password()).account.id == alex


def test_forgot_answers_at_once_and_does_the_rest_in_the_background(app: Any, konten: Any) -> None:
    app.seed("alex", email="alex@example.com", password=password())
    jobs: list[Any] = []
    sent: list[Any] = []
    for typed in ("alex", "nobody"):
        assert konten.resets.forgot_in_background(
            typed, open_store=app.store, send=sent.append, later=jobs.append
        ) is None
    assert sent == [] and len(jobs) == 2
    for job in jobs:
        job()
    assert [letter.to for letter in sent] == ["alex@example.com"]


def test_a_mail_that_fails_in_the_background_takes_its_link(app: Any, konten: Any) -> None:
    alex = app.seed("alex", email="alex@example.com", password=password())

    def broken(letter: Any) -> None:
        raise OSError("mail server gone")

    tokens: list[str] = []

    def keep(letter: Any) -> None:
        tokens.append(letter.token)
        broken(letter)

    konten.resets.forgot_in_background("alex", open_store=app.store, send=keep, later=lambda job: job())
    with app.store() as store, pytest.raises(konten.AccountError):
        konten.resets.reset_state(store, tokens[0])
    assert alex


@pytest.mark.parametrize("how", ["changed", "removed", "removed_by_operator", "confirmed"])
def test_a_link_a_person_asked_for_dies_when_the_address_changes(
    app: Any, konten: Any, operator: Any, how: str
) -> None:
    operator_id, operator_secret = operator
    secret = password()
    alex = app.seed("alex", email="alex@example.com", password=secret)
    with app.store() as store:
        token = konten.resets.forgot(store, "alex").token
        made = konten.resets.reset_link(store, alex, actor_id=operator_id, password=operator_secret).token
    # The operator's link replaced the person's: ask again for the person's own.
    with app.store() as store:
        token = konten.resets.forgot(store, "alex").token
    with app.store() as store:
        if how == "changed":
            konten.profiles.change_email(store, alex, "new@example.com", password=secret)
        elif how == "removed":
            konten.profiles.change_email(store, alex, "", password=secret)
        elif how == "removed_by_operator":
            konten.profiles.remove_email(store, alex, actor_id=operator_id, password=operator_secret)
        else:
            link = konten.profiles.change_email(store, alex, "new@example.com", password=secret, mail=True).mail
            konten.profiles.confirm_email(store, link.token)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.resets.reset_state(store, token)
    assert caught.value.code == "reset_invalid"
    assert made


def test_an_operator_link_outlives_a_change_of_the_address(app: Any, konten: Any, operator: Any) -> None:
    operator_id, operator_secret = operator
    secret = password()
    alex = app.seed("alex", email="alex@example.com", password=secret)
    with app.store() as store:
        made = konten.resets.reset_link(store, alex, actor_id=operator_id, password=operator_secret).token
        konten.profiles.change_email(store, alex, "new@example.com", password=secret)
    with app.store() as store:
        assert konten.resets.reset_state(store, made).id == alex


def test_devices_stay_connected_after_the_operators_link_too(
    app: Any, konten: Any, operator: tuple[Any, str]
) -> None:
    """Decided 25.11.2026: after any link for a new password the paired devices stay; the app lists them ("These
    devices still have access") with "Disconnect all"."""
    boss, boss_secret = operator
    alex = app.seed("alex", email="alex@example.com", password=password())
    browser, device = (app.open_session(alex, kind) for kind in ("browser", "device"))
    with app.store() as store:
        token = konten.resets.reset_link(store, alex, actor_id=boss, password=boss_secret).token
    with app.store() as store:
        done = konten.resets.use_reset(store, token, password())
    assert done.origin == konten.RESET_OPERATOR
    assert not app.session_alive(browser) and app.session_alive(device) and len(done.remaining) >= 1


def test_forgot_mails_at_once_through_the_route_and_a_failed_mail_never_waits_in_the_outbox(
    app: Any, konten: Any
) -> None:
    """Since 1.0.0 (nextasks put a failed mail into its outbox for another try): "Forgot your password?" sends at
    once; a mail that fails takes its link with it and never waits in the outbox, where it would arrive an hour later
    with a link that is gone. Through the app's own route."""
    app.seed("alex", email="alex@example.com", password=password())
    assert app.forgot_through_route("alex", mail_fails=True) == ([], 0)
    assert app.forgot_through_route("alex", mail_fails=False) == (["alex@example.com"], 0)
    assert app.forgot_through_route("nobody", mail_fails=False) == ([], 0)
