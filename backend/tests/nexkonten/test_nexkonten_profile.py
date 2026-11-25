"""The profile: everybody changes their own username; a new address counts with a mail server only after its link;
the operator changes names with the operator's own password and may only take an address away."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from konten_contract import password


def test_a_new_username_counts_at_once_and_the_old_one_stays_reserved(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", email="alex@example.com", password=secret)
    session = app.open_session(alex)
    with app.store() as store:
        letter = konten.profiles.change_username(store, alex, "Alex.New", actor_id=alex, password=secret)
    assert letter.kind == konten.MAIL_USERNAME_CHANGED and letter.to == "alex@example.com"
    assert letter.username == "alex.new"
    assert app.sign_in("alex.new", secret) == alex
    assert app.sign_in("alex", secret) is None
    assert app.session_alive(session) is True
    other_secret = password()
    other = app.seed("other", password=other_secret)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.change_username(store, other, "alex", actor_id=other, password=other_secret)
    assert caught.value.code == "username_taken"
    with app.store() as store:
        konten.profiles.change_username(store, alex, "alex", actor_id=alex, password=secret)
        assert store.get_account(alex).username == "alex"


def test_a_username_change_needs_the_own_password(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.change_username(store, alex, "new", actor_id=alex, password=secret + "x")
    assert caught.value.code == "wrong_password"
    with app.store() as store:
        assert store.get_account(alex).username == "alex"


def test_a_username_another_account_has_in_any_case_is_refused(app: Any, konten: Any) -> None:
    secret = password()
    app.seed("Kim", password=password())
    alex = app.seed("alex", password=secret)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.change_username(store, alex, "KIM", actor_id=alex, password=secret)
    assert caught.value.code == "username_taken"


def test_an_older_name_with_capitals_can_be_written_small_by_its_owner(app: Any, konten: Any) -> None:
    secret = password()
    kim = app.seed("Kim", password=secret)
    with app.store() as store:
        assert konten.profiles.change_username(store, kim, "kim", actor_id=kim, password=secret) is None
        assert store.get_account(kim).username == "kim"


def test_no_notice_goes_to_an_address_that_is_not_confirmed(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", email="alex@example.com", email_confirmed=False, password=secret)
    with app.store() as store:
        assert konten.profiles.change_username(store, alex, "alexa", actor_id=alex, password=secret) is None


def test_an_account_through_a_provider_only_changes_its_username_without_a_password(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=None)
    with app.store() as store:
        konten.profiles.change_username(store, alex, "alexa", actor_id=alex)
        assert store.get_account(alex).username == "alexa"


def test_the_operator_changes_names_with_the_own_password_a_member_not_at_all(
    app: Any, konten: Any, operator: Any
) -> None:
    operator_id, operator_secret = operator
    member_secret = password()
    alex = app.seed("alex", password=member_secret)
    kim = app.seed("kim", password=password())
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.change_username(store, alex, "x1", actor_id=operator_id, password=member_secret)
    assert caught.value.code == "wrong_password"
    with app.store() as store:
        konten.profiles.change_username(store, alex, "alex2", actor_id=operator_id, password=operator_secret)
        konten.profiles.change_display_name(store, alex, "Alex Zwei", actor_id=operator_id, password=operator_secret)
        account = store.get_account(alex)
    assert (account.username, account.display_name) == ("alex2", "Alex Zwei")
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.change_username(store, kim, "kim2", actor_id=alex, password=member_secret)
    assert caught.value.code == "not_allowed"


def test_a_display_name_equal_to_the_old_username_follows_it_any_other_stays(app: Any, konten: Any) -> None:
    copied = app.seed("Kim", display_name="Kim", password=None)
    own = app.seed("lee", display_name="Lee Example", password=None)
    almost = app.seed("max", display_name="Max", password=None)
    with app.store() as store:
        for account_id, new in ((copied, "kim.new"), (own, "lee.new"), (almost, "max.new")):
            konten.profiles.change_username(store, account_id, new, actor_id=account_id)
        shown = [store.get_account(account_id).display_name for account_id in (copied, own, almost)]
    assert shown == ["kim.new", "Lee Example", "Max"]


def test_the_language_is_kept_at_the_account(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    with app.store() as store:
        assert konten.profiles.change_language(store, alex, "en-GB").language == "en-GB"
    with app.store() as store:
        assert store.get_account(alex).language == "en-GB"
        assert konten.profiles.change_language(store, alex, "<script>").language == ""


def test_the_own_display_name_changes_without_a_password_and_may_be_empty(app: Any, konten: Any) -> None:
    alex = app.seed("alex", display_name="Alex", password=password())
    with app.store() as store:
        account = konten.profiles.change_display_name(store, alex, "  ", actor_id=alex)
    assert account.display_name == "" and konten.names.shown_name(account) == "alex"


def test_a_new_address_waits_for_its_link_and_the_old_one_counts_until_then(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", email="old@example.com", password=secret)
    with app.store() as store:
        changed = konten.profiles.change_email(store, alex, "new@example.com", password=secret, mail=True)
    assert changed.pending == "new@example.com" and changed.account.email == "old@example.com"
    assert app.sign_in("old@example.com", secret) == alex
    assert app.sign_in("new@example.com", secret) is None
    token = changed.mail.token
    with app.store() as store:
        assert konten.profiles.email_change_state(store, token).address == "new@example.com"
        konten.profiles.confirm_email(store, token)
    assert app.sign_in("new@example.com", secret) == alex
    assert app.sign_in("old@example.com", secret) is None
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.confirm_email(store, token)
    assert caught.value.code == "email_link_invalid"


def test_an_address_another_account_took_meanwhile_is_not_confirmed(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    kim = app.seed("kim", password=secret)
    with app.store() as store:
        changed = konten.profiles.change_email(store, alex, "both@example.com", password=secret, mail=True)
        konten.profiles.change_email(store, kim, "both@example.com", password=secret)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.confirm_email(store, changed.mail.token)
    assert caught.value.code == "email_taken"
    with app.store() as store:
        assert store.get_account(alex).email == ""


def test_an_expired_confirmation_link_says_so(app: Any, konten: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    with app.store() as store:
        token = konten.profiles.change_email(store, alex, "new@example.com", password=secret, mail=True).mail.token
    now = konten.common.utcnow()
    monkeypatch.setattr(konten.common, "utcnow", lambda: now + timedelta(hours=25))
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.confirm_email(store, token)
    assert caught.value.code == "email_link_expired"


def test_a_new_address_counts_at_once_without_a_mail_server(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", email="old@example.com", password=secret)
    with app.store() as store:
        changed = konten.profiles.change_email(store, alex, "new@example.com", password=secret)
    assert changed.mail is None and changed.account.email == "new@example.com" and changed.account.email_confirmed
    assert app.sign_in("new@example.com", secret) == alex


def test_an_address_change_is_refused_without_the_password_or_for_another_accounts_address(
    app: Any, konten: Any
) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    app.seed("kim", email="kim@example.com", password=password())
    for typed, given, code in (
        ("new@example.com", secret + "x", "wrong_password"),
        ("KIM@example.com", secret, "email_taken"),
        ("no address", secret, "email_invalid"),
    ):
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            konten.profiles.change_email(store, alex, typed, password=given)
        assert caught.value.code == code, typed


def test_an_address_can_always_be_taken_away(app: Any, konten: Any, operator: Any) -> None:
    operator_id, operator_secret = operator
    secret = password()
    alex = app.seed("alex", email="alex@example.com", password=secret)
    kim = app.seed("kim", email="kim@example.com", password=password())
    with app.store() as store:
        konten.profiles.change_email(store, alex, "new@example.com", password=secret, mail=True)
        assert konten.profiles.change_email(store, alex, "", password=secret).account.email == ""
        assert store.get_account(alex).pending_email == ""
        removed = konten.profiles.remove_email(store, kim, actor_id=operator_id, password=operator_secret)
        assert removed.account.email == ""


def test_a_waiting_address_can_be_withdrawn(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", email="old@example.com", password=secret)
    with app.store() as store:
        token = konten.profiles.change_email(store, alex, "new@example.com", password=secret, mail=True).mail.token
        konten.profiles.withdraw_email_change(store, alex)
        assert store.get_account(alex).email == "old@example.com"
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.confirm_email(store, token)
    assert caught.value.code == "email_link_invalid"


def test_an_operator_without_a_password_acts_after_a_fresh_sign_in_at_the_provider(app: Any, konten: Any) -> None:
    boss = app.seed("boss", password=None, operator=True)
    alex = app.seed("alex", email="alex@example.com", password=password())
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.change_username(store, alex, "alex2", actor_id=boss)
    assert caught.value.code == "fresh_sign_in_needed"
    with app.store() as store:
        konten.profiles.change_username(store, alex, "alex2", actor_id=boss, actor_confirmed=True)
        konten.profiles.remove_email(store, alex, actor_id=boss, actor_confirmed=True)
        account = store.get_account(alex)
    assert (account.username, account.email) == ("alex2", "")


def test_an_account_without_a_password_changes_its_address_only_after_a_fresh_sign_in(
    app: Any, konten: Any
) -> None:
    alex = app.seed("alex", password=None)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.change_email(store, alex, "alex@example.com")
    assert caught.value.code == "fresh_sign_in_needed"
    with app.store() as store:
        changed = konten.profiles.change_email(store, alex, "alex@example.com", actor_confirmed=True)
    assert changed.account.email == "alex@example.com"


def test_a_display_name_is_unique_and_never_another_accounts_username(app: Any, konten: Any) -> None:
    app.seed("kim", display_name="Kim Lee", password=password())
    alex = app.seed("alex", password=password())
    for shown in ("kim lee", "KIM"):
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            konten.profiles.change_display_name(store, alex, shown, actor_id=alex)
        assert caught.value.code == "display_name_taken", shown
    with app.store() as store:
        assert konten.profiles.change_display_name(store, alex, "Alex", actor_id=alex).display_name == "Alex"


def test_a_username_that_is_another_accounts_display_name_is_taken(app: Any, konten: Any) -> None:
    secret = password()
    app.seed("kim", display_name="Chef", password=password())
    alex = app.seed("alex", password=secret)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.change_username(store, alex, "chef", actor_id=alex, password=secret)
    assert caught.value.code == "username_taken"


def test_the_old_address_hears_of_a_confirmed_change(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", email="old@example.com", password=secret)
    with app.store() as store:
        token = konten.profiles.change_email(store, alex, "new@example.com", password=secret, mail=True).mail.token
        confirmed = konten.profiles.confirm_email(store, token)
    assert confirmed.account.email == "new@example.com" and confirmed.account.email_proven
    notice = confirmed.notice
    assert notice.kind == konten.MAIL_EMAIL_CHANGED and notice.to == "old@example.com"
    assert notice.new_hint == "n***@example.com"


def test_the_confirmation_link_can_be_sent_again(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.resend_email_link(store, alex)
    assert caught.value.code == "no_pending_email"
    with app.store() as store:
        first = konten.profiles.change_email(store, alex, "new@example.com", password=secret, mail=True).mail.token
        again = konten.profiles.resend_email_link(store, alex)
    assert again.to == "new@example.com" and again.token != first
    with app.store() as store, pytest.raises(konten.AccountError):
        konten.profiles.confirm_email(store, first)
    with app.store() as store:
        assert konten.profiles.confirm_email(store, again.token).account.email == "new@example.com"
