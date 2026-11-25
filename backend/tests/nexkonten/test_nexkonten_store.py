"""The app's ``Store`` keeps the promises the module builds on: lookups without regard to case, uniqueness in the
database itself, one-row statements for everything that works once, hashes instead of tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from konten_contract import password, png


def _later(hours: int = 1) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


def _new(konten: Any, username: str, email: str = "") -> Any:
    return konten.NewAccount(
        username=username, display_name=username, email=email, email_confirmed=True, password=password()
    )


def test_a_username_is_found_in_any_case(app: Any) -> None:
    app.seed("Kim", password=password())
    with app.store() as store:
        for typed in ("kim", "KIM", "Kim"):
            found = store.find_by_username(typed)
            assert [account.username for account in found] == ["Kim"], typed


def test_every_account_of_an_address_is_found_in_any_case(app: Any) -> None:
    first = app.seed("first", email="same@example.com", password=password())
    second = app.seed("second", email="Same@Example.com", password=password())
    app.seed("third", email="other@example.com", password=password())
    with app.store() as store:
        found = store.find_by_email("SAME@example.com")
    assert {account.id for account in found} == {first, second}


def test_the_database_refuses_a_username_another_account_has_in_any_case(app: Any, konten: Any) -> None:
    app.seed("Kim", password=password())
    lee = app.seed("lee", password=password())
    with app.store() as store, pytest.raises(konten.Taken) as caught:
        store.set_username(lee, "kim")
    assert caught.value.what == "username"
    with app.store() as store, pytest.raises(konten.Taken) as caught:
        store.add_account(_new(konten, "kim"))
    assert caught.value.what == "username"


def test_two_renames_to_one_name_at_the_same_moment_do_not_both_get_through(app: Any, konten: Any) -> None:
    first = app.seed("first", password=password())
    second = app.seed("second", password=password())
    with app.store() as one, app.store() as other:
        # Both looked and found the name free before either wrote.
        assert one.find_by_username("wanted") == [] and other.find_by_username("wanted") == []
        one.set_username(first, "wanted")
        one.commit()
        with pytest.raises(konten.Taken):
            other.set_username(second, "wanted")
        other.rollback()
    with app.store() as store:
        assert store.get_account(first).username == "wanted"
        assert store.get_account(second).username == "second"


def test_an_account_is_read_back_as_it_was_written(app: Any, konten: Any) -> None:
    secret = password()
    with app.store() as store:
        account_id = store.add_account(
            konten.NewAccount(
                username="alex", display_name="Alex Ä 🦊", email="Alex@example.com", email_confirmed=True,
                password=secret, language="de",
            )
        )
        store.commit()
    with app.store() as store:
        account = store.get_account(account_id)
        assert store.check_password(account_id, secret) is True
        assert store.count_accounts() == 1
    assert (account.username, account.display_name, account.email) == ("alex", "Alex Ä 🦊", "Alex@example.com")
    assert account.email_confirmed and account.email_source == konten.EMAIL_OWN and account.has_password
    assert not account.blocked and not account.operator and account.picture == konten.PICTURE_NONE
    assert account.language == "de"
    assert secret not in app.raw_text()


def test_the_language_is_kept_and_read_back(app: Any) -> None:
    alex = app.seed("alex", password=password())
    with app.store() as store:
        assert store.get_account(alex).language == ""
        store.set_language(alex, "de")
        store.commit()
    with app.store() as store:
        assert store.get_account(alex).language == "de"


def test_blocked_accounts_count_and_say_so(app: Any) -> None:
    if not app.blocking:
        return  # the app blocks no accounts (StandardAdapter.blocking)
    blocked = app.seed("gone", password=password(), blocked=True)
    with app.store() as store:
        assert store.count_accounts() == 1
        assert store.get_account(blocked).blocked is True


def test_a_password_check_answers_false_for_nobody_and_for_an_account_without_one(app: Any) -> None:
    secret = password()
    with_password = app.seed("with", password=secret)
    provider_only = app.seed("without", password=None)
    with app.store() as store:
        assert store.check_password(None, secret) is False
        assert store.check_password(provider_only, secret) is False
        assert store.check_password(provider_only, "") is False
        assert store.check_password(with_password, secret + "x") is False
        assert store.check_password(with_password, secret) is True
        assert store.get_account(provider_only).has_password is False


def test_a_new_password_counts_and_is_kept_only_as_a_hash(app: Any) -> None:
    account_id = app.seed("alex", password=None)
    secret = password()
    with app.store() as store:
        store.set_password(account_id, secret)
        store.commit()
    with app.store() as store:
        assert store.check_password(account_id, secret) is True
        assert store.get_account(account_id).has_password is True
    assert secret not in app.raw_text()


def test_an_address_is_set_confirmed_or_not_with_its_source_and_taken_away(app: Any, konten: Any) -> None:
    account_id = app.seed("alex", password=password())
    with app.store() as store:
        store.set_email(account_id, "alex@example.com", confirmed=False, proven=False, source=konten.EMAIL_PROVIDER)
        store.commit()
    with app.store() as store:
        account = store.get_account(account_id)
        assert (account.email, account.email_confirmed, account.email_source) == (
            "alex@example.com", False, konten.EMAIL_PROVIDER,
        )
        store.set_email(account_id, "", confirmed=True, proven=False, source=konten.EMAIL_OWN)
        store.commit()
    with app.store() as store:
        assert store.get_account(account_id).email == ""
        assert store.find_by_email("alex@example.com") == []


def test_a_provider_picture_is_stored_only_while_the_account_has_none(app: Any, konten: Any) -> None:
    own = app.seed("own", password=password(), picture=True)
    none = app.seed("none", password=password())
    picture = konten.pictures.redraw(png())
    with app.store() as store:
        assert store.get_account(own).picture == konten.PICTURE_OWN
        assert store.set_provider_picture(own, picture) is False
        assert store.set_provider_picture(none, picture) is True
        store.commit()
    with app.store() as store:
        assert store.get_account(own).picture == konten.PICTURE_OWN
        assert store.get_account(none).picture == konten.PICTURE_PROVIDER
        assert store.set_provider_picture(none, picture) is False


def test_an_invitation_is_used_up_once_by_two_requests_at_the_same_moment(app: Any, operator: Any) -> None:
    token = app.make_invite(email="new@example.com", display_name="New")
    with app.store() as one, app.store() as other:
        first, second = one.find_invite(token), other.find_invite(token)
        assert first is not None and second is not None
        assert first.email == "new@example.com" and first.display_name == "New"
        assert one.consume_invite(first) is True
        one.commit()
        assert other.consume_invite(second) is False
        other.rollback()
    with app.store() as store:
        assert store.find_invite(token) is None


def test_a_password_link_is_used_up_once_and_kept_only_as_a_hash(app: Any, konten: Any, operator: Any) -> None:
    operator_id, _ = operator
    account_id = app.seed("alex", password=password())
    token = "reset-" + password()
    with app.store() as store:
        store.start_reset(account_id, token, _later(), created_by=operator_id, origin=konten.RESET_OPERATOR)
        store.commit()
    assert token not in app.raw_text()
    with app.store() as one, app.store() as other:
        first, second = one.find_reset(token), other.find_reset(token)
        assert first is not None and second is not None
        assert first.account_id == account_id and first.created_by == operator_id
        assert first.origin == konten.RESET_OPERATOR
        assert one.consume_reset(first) is True
        one.commit()
        assert other.consume_reset(second) is False
        other.rollback()
    with app.store() as store:
        assert store.find_reset(token) is None


def test_a_new_password_link_replaces_the_one_before(app: Any) -> None:
    account_id = app.seed("alex", password=password())
    old, new = "old-" + password(), "new-" + password()
    with app.store() as store:
        store.start_reset(account_id, old, _later(), created_by=None, origin="self")
        store.commit()
        store.start_reset(account_id, new, _later(), created_by=None, origin="self")
        store.commit()
    with app.store() as store:
        assert store.find_reset(old) is None
        found = store.find_reset(new)
        assert found is not None and found.created_by is None and found.origin == "self"
        store.drop_resets(account_id)
        store.commit()
    with app.store() as store:
        assert store.find_reset(new) is None


def test_an_address_change_is_used_up_once_and_kept_only_as_a_hash(app: Any) -> None:
    account_id = app.seed("alex", email="old@example.com", password=password())
    token = "mail-" + password()
    with app.store() as store:
        store.start_email_change(account_id, "new@example.com", token, _later(24))
        store.commit()
    assert token not in app.raw_text()
    with app.store() as store:
        assert store.get_account(account_id).pending_email == "new@example.com"
        assert store.get_account(account_id).email == "old@example.com"
    with app.store() as one, app.store() as other:
        first, second = one.find_email_change(token), other.find_email_change(token)
        assert first is not None and second is not None and first.address == "new@example.com"
        assert one.consume_email_change(first) is True
        one.commit()
        assert other.consume_email_change(second) is False
        other.rollback()


def test_a_withdrawn_address_change_is_gone(app: Any) -> None:
    account_id = app.seed("alex", password=password())
    token = "mail-" + password()
    with app.store() as store:
        store.start_email_change(account_id, "new@example.com", token, _later(24))
        store.commit()
        store.drop_email_change(account_id)
        store.commit()
    with app.store() as store:
        assert store.find_email_change(token) is None
        assert store.get_account(account_id).pending_email == ""


def test_an_expired_link_is_still_found_with_its_end(app: Any, operator: Any) -> None:
    account_id = app.seed("alex", password=password())
    token = "reset-" + password()
    with app.store() as store:
        store.start_reset(account_id, token, datetime.now(UTC) - timedelta(minutes=5), created_by=None, origin="self")
        store.commit()
    with app.store() as store:
        found = store.find_reset(token)
    assert found is not None
    end = found.expires_at if found.expires_at.tzinfo else found.expires_at.replace(tzinfo=UTC)
    assert end < datetime.now(UTC)


def test_an_address_counts_and_is_proven_as_two_answers(app: Any, konten: Any) -> None:
    account_id = app.seed("alex", password=password())
    with app.store() as store:
        store.set_email(account_id, "alex@example.com", confirmed=True, proven=False, source=konten.EMAIL_PROVIDER)
        store.commit()
    with app.store() as store:
        account = store.get_account(account_id)
        assert (account.email_confirmed, account.email_proven, account.email_source) == (
            True,
            False,
            konten.EMAIL_PROVIDER,
        )
        store.set_email(account_id, "alex@example.com", confirmed=True, proven=True, source=konten.EMAIL_OWN)
        store.commit()
    with app.store() as store:
        assert store.get_account(account_id).email_proven is True


def test_finders_return_blocked_accounts_too(app: Any) -> None:
    if not app.blocking:
        return  # the app blocks no accounts (StandardAdapter.blocking)
    gone = app.seed("gone", email="gone@example.com", password=password(), blocked=True)
    with app.store() as store:
        assert [account.id for account in store.find_by_username("GONE")] == [gone]
        assert [account.id for account in store.find_by_email("gone@example.com")] == [gone]
        assert store.get_account(gone).blocked


def test_a_former_name_stays_reserved_for_others_and_is_known_in_the_background(app: Any) -> None:
    alex = app.seed("alex", password=password())
    kim = app.seed("kim", password=password())
    with app.store() as store:
        store.set_username(alex, "alexa")
        store.commit()
    with app.store() as store:
        assert store.find_by_username("alex") == []
        assert store.name_reserved("ALEX", kim) is True
        assert store.name_reserved("alex", None) is True
        assert store.name_reserved("alex", alex) is False
        assert store.name_reserved("nobody", None) is False
        assert [account.id for account in store.find_by_former_name("Alex")] == [alex]


def test_the_name_of_a_deleted_account_stays_taken(app: Any, konten: Any) -> None:
    gone = app.seed("gone", password=password())
    app.delete_account(gone)
    with app.store() as store:
        assert konten.names.username_taken(store, "GONE")


def test_a_display_name_is_compared_without_case_and_width(app: Any) -> None:
    kim = app.seed("kim", display_name="Kim Lee", password=password())
    other = app.seed("other", password=password())
    with app.store() as store:
        assert store.display_name_taken("kim lee", other) is True
        assert store.display_name_taken("Ｋim Lee", other) is True
        assert store.display_name_taken("KIM LEE", kim) is False
        assert store.display_name_taken("Kim Leee", other) is False


def test_a_new_password_ends_browser_and_waiting_sign_ins_and_keeps_devices(app: Any) -> None:
    alex = app.seed("alex", password=password())
    browser = app.open_session(alex, "browser")
    waiting = app.open_session(alex, "waiting")
    device = app.open_session(alex, "device")
    with app.store() as store:
        store.end_sessions(alex)
        store.commit()
    assert not app.session_alive(browser) and not app.session_alive(waiting) and app.session_alive(device)
    with app.store() as store:
        listed = store.list_access(alex)
        assert len(listed) >= 1 and all(entry.kind for entry in listed)
        assert store.revoke_access(alex) >= 1
        store.commit()
    assert not app.session_alive(device)


def test_the_second_factor_of_an_account_is_told(app: Any, konten: Any) -> None:
    plain = app.seed("plain", password=password())
    active = app.seed("active", password=password(), second_factor="active")
    with app.store() as store:
        assert store.second_factor(plain) == konten.SECOND_FACTOR_NONE
        assert store.second_factor(active) == konten.SECOND_FACTOR_ACTIVE
    if app.required_second_factor:
        required = app.seed("required", password=password(), second_factor="required")
        with app.store() as store:
            assert store.second_factor(required) == konten.SECOND_FACTOR_REQUIRED


def test_failures_are_counted_at_the_account_and_a_success_starts_anew(app: Any) -> None:
    alex = app.seed("alex", password=password())
    with app.store() as store:
        for _ in range(app.lock_after or 3):
            store.note_failure(alex)
        store.commit()
    with app.store() as store:
        assert store.is_locked(alex) is bool(app.lock_after)
        store.note_success(alex)
        store.commit()
    with app.store() as store:
        assert store.is_locked(alex) is False


def test_an_existing_account_takes_the_rights_of_an_invitation(app: Any, operator: Any) -> None:
    alex = app.seed("alex", password=password())
    token = app.make_invite()
    with app.store() as store:
        invite = store.find_invite(token)
        assert store.consume_invite(invite) is True
        store.accept_invite(alex, invite)
        store.commit()
    with app.store() as store:
        assert store.find_invite(token) is None


def test_the_store_hears_what_happened_after_a_commit(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    with app.store() as store:
        store.notify(konten.Event(konten.EVENT_RENAMED, alex, old="alex", new="alexa"))


def test_a_failure_that_names_no_account_is_written_too(app: Any) -> None:
    with app.store() as store:
        store.note_failure(None)
        store.commit()


def test_links_of_one_origin_go_and_the_others_stay(app: Any, konten: Any, operator: Any) -> None:
    operator_id, _ = operator
    alex = app.seed("alex", password=password())
    kim = app.seed("kim", password=password())
    own, made = "own-" + password(), "made-" + password()
    with app.store() as store:
        store.start_reset(alex, own, _later(), created_by=None, origin=konten.RESET_SELF)
        store.start_reset(kim, made, _later(), created_by=operator_id, origin=konten.RESET_OPERATOR)
        store.commit()
        store.drop_resets(alex, origin=konten.RESET_OPERATOR)
        store.drop_resets(kim, origin=konten.RESET_SELF)
        store.commit()
    with app.store() as store:
        assert store.find_reset(own) is not None and store.find_reset(made) is not None
        store.drop_resets(alex, origin=konten.RESET_SELF)
        store.commit()
    with app.store() as store:
        assert store.find_reset(own) is None


def test_the_server_is_claimed_for_setup_once(app: Any) -> None:
    with app.store() as one, app.store() as other:
        assert one.claim_setup() is True
        one.commit()
        assert other.claim_setup() is False
        other.rollback()
