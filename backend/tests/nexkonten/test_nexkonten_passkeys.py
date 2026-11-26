"""Passkeys through the app's store: added (confirmed with the password, begun and finished in two requests) and
signing in without a password, each answer counting once, the count only moving forward, the operator's switch, a
blocked account, and the last factor where one is required."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

import pytest
from konten_contract import password
from webauthn_device import Device

PUBLIC_URL = "https://app.example.com"
#: The password of the accounts here, made at run time.
SECRET = password()


def _where(konten: Any) -> Any:
    return konten.passkeys.party(PUBLIC_URL)


def _register(app: Any, konten: Any, account_id: Any, name: str = "Phone") -> tuple[Device, Any]:
    """As a browser does it: the options in one request, the answer in the next."""
    where = _where(konten)
    device = Device(where.origin, where.rp_id)
    with app.store() as store:
        token, options = konten.passkeys.begin_register(store, account_id, where, app_name="nexapp", password=SECRET)
    with app.store() as store:
        key = konten.passkeys.finish_register(store, account_id, token, device.create(options), where, name=name)
    return device, key


def _sign_in(app: Any, konten: Any, device: Device, **answer: Any) -> Any:
    where = _where(konten)
    with app.store() as store:
        token, options = konten.passkeys.begin_sign_in(store, where)
        return konten.passkeys.finish_sign_in(store, token, device.get(options, **answer), where)


def _refused(konten: Any, call: Any, code: str) -> None:
    with pytest.raises(konten.AccountError) as caught:
        call()
    assert caught.value.code == code


def test_the_party_is_the_public_address_of_the_app(konten: Any) -> None:
    where = konten.passkeys.party("https://Notes.Example.com:8443/app")
    assert (where.rp_id, where.origin) == ("notes.example.com", "https://notes.example.com:8443")
    local = konten.passkeys.party("http://localhost:5173")
    assert (local.rp_id, local.origin) == ("localhost", "http://localhost:5173")
    _refused(konten, lambda: konten.passkeys.party("notes.example.com"), "passkeys_off")
    _refused(konten, lambda: konten.passkeys.party("http://notes.example.com"), "passkeys_off")
    # A page on localhost (a secure context without https) gets exactly its host and port; other origins change nothing.
    there = konten.passkeys.party("https://notes.example.com", origin="http://localhost:5180")
    assert (there.rp_id, there.origin) == ("localhost", "http://localhost:5180")
    plain = konten.passkeys.party("https://notes.example.com")
    assert konten.passkeys.party("https://notes.example.com", origin="https://evil.example.org") == plain



def test_a_get_without_origin_takes_the_address_of_the_request(konten: Any) -> None:
    """Decided while building (0.3.3): browsers send no ``Origin`` with a GET on the same page; the address of the
    request stands in for it, by scheme, host and port, and only on localhost does it change the party."""
    asked = "http://localhost:5180/api/passkeys/sign-in?x=1"
    there = konten.passkeys.party("https://notes.example.com", request_url=asked)
    assert (there.rp_id, there.origin) == ("localhost", "http://localhost:5180")
    plain = konten.passkeys.party("https://notes.example.com")
    assert konten.passkeys.party("https://notes.example.com", request_url="https://evil.example.org/x") == plain
    # A given Origin wins over the address of the request.
    given = konten.passkeys.party("https://notes.example.com", origin="https://evil.example.org", request_url=asked)
    assert given == plain

def test_adding_a_passkey_is_confirmed_with_the_password(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=SECRET)
    where = _where(konten)
    with app.store() as store:
        for given in ("", password()):
            _refused(
                konten,
                lambda: konten.passkeys.begin_register(store, alex, where, app_name="x", password=given),  # noqa: B023
                "wrong_password",
            )
        token, _ = konten.passkeys.begin_register(store, alex, where, app_name="x", actor_confirmed=True)
    assert token
    provider_only = app.seed("viaprovider")
    with app.store() as store:
        _refused(
            konten,
            lambda: konten.passkeys.begin_register(store, provider_only, where, app_name="x"),
            "fresh_sign_in_needed",
        )


def test_the_user_handle_stays_from_the_first_request_to_the_sign_in(app: Any, konten: Any) -> None:
    """Begun in one request and finished in another: the handle the browser keeps is the one the store keeps."""
    alex = app.seed("alex", password=SECRET)
    device, _ = _register(app, konten, alex)
    with app.store() as store:
        assert store.user_handle(alex) == device.user_handle
    assert _sign_in(app, konten, device).id == alex


def test_a_passkey_is_added_and_signs_in_without_a_password(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=SECRET)
    device, key = _register(app, konten, alex, name="  Phone\nof Alex  ")
    assert key.name == "Phone of Alex" and key.sign_count == 0
    with app.store() as store:
        assert [entry.uid for entry in store.passkeys_of(alex)] == [key.uid]
        assert store.find_passkey(device.credential_id).account_id == alex
        assert konten.factor.has_factor(store, alex)
        # Without "second factor for everybody" a passkey is a way in of its own; the password alone still signs in.
        assert store.second_factor(alex) == konten.SECOND_FACTOR_NONE
        assert device.user_handle == store.user_handle(alex) and len(device.user_handle) >= 16
    assert _sign_in(app, konten, device).id == alex
    assert _sign_in(app, konten, device).id == alex
    with app.store() as store:
        used = store.passkeys_of(alex)[0]
    assert used.sign_count == 2 and used.last_used_at is not None
    shown = konten.passkeys.view(used)
    assert set(shown) == {"uid", "name", "created_at", "last_used_at"}


def test_the_same_passkey_is_not_added_twice_and_handles_differ_per_account(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=SECRET)
    kim = app.seed("kim", password=SECRET)
    device, _ = _register(app, konten, alex)
    where = _where(konten)
    with app.store() as store:
        token, options = konten.passkeys.begin_register(store, alex, where, app_name="nexapp", password=SECRET)
        assert device.credential_id != b"" and konten.passkeys.options_json(options)["excludeCredentials"]
        answer = device.create(options)
        _refused(konten, lambda: konten.passkeys.finish_register(store, alex, token, answer, where), "passkey_exists")
        assert store.user_handle(alex) != store.user_handle(kim)
        token, options = konten.passkeys.begin_register(store, alex, where, app_name="nexapp", password=SECRET)
        _refused(
            konten,
            lambda: konten.passkeys.finish_register(
                store, kim, token, Device(where.origin, where.rp_id).create(options), where
            ),
            "passkey_expired",
        )


def test_an_answer_counts_once_and_a_count_that_does_not_move_is_refused(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=SECRET)
    device, _ = _register(app, konten, alex)
    where = _where(konten)
    with app.store() as store:
        token, options = konten.passkeys.begin_sign_in(store, where)
        answer = device.get(options)
        assert konten.passkeys.finish_sign_in(store, token, answer, where).id == alex
        _refused(konten, lambda: konten.passkeys.finish_sign_in(store, token, answer, where), "passkey_expired")
    _refused(konten, lambda: _sign_in(app, konten, device, count_up=False), "passkey_invalid")
    with app.store() as store:
        uid = store.passkeys_of(alex)[0].uid
    with app.store() as first, app.store() as second:
        assert first.claim_counter(uid, 1, 5) is True
        first.commit()
        assert second.claim_counter(uid, 1, 5) is False


def test_a_wrong_origin_an_unknown_passkey_or_another_accounts_handle_is_refused(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=SECRET)
    kim = app.seed("kim", password=SECRET)
    device, _ = _register(app, konten, alex)
    _register(app, konten, kim)
    _refused(konten, lambda: _sign_in(app, konten, device, origin="https://app.example.org"), "passkey_invalid")
    with app.store() as store:
        other = store.user_handle(kim)
    _refused(konten, lambda: _sign_in(app, konten, device, user_handle=other), "passkey_invalid")
    stranger = Device(device.origin, device.rp_id)
    _refused(konten, lambda: _sign_in(app, konten, stranger), "passkey_invalid")
    assert _sign_in(app, konten, device).id == alex


def test_the_operator_turns_passkeys_off_and_none_signs_in_but_none_is_deleted(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=SECRET)
    device, _ = _register(app, konten, alex)
    with app.store() as store:
        assert store.passkeys_allowed() is True
    app.switch("passkeys_allowed", False)
    where = _where(konten)
    with app.store() as store:
        _refused(konten, lambda: konten.passkeys.begin_sign_in(store, where), "passkeys_off")
        _refused(
            konten,
            lambda: konten.passkeys.begin_register(store, alex, where, app_name="x", password=SECRET),
            "passkeys_off",
        )
        assert len(store.passkeys_of(alex)) == 1
    app.switch("passkeys_allowed", True)
    assert _sign_in(app, konten, device).id == alex


def test_a_blocked_account_hears_so_only_after_a_valid_answer(app: Any, konten: Any) -> None:
    if not app.blocking:
        return  # the app blocks no accounts (StandardAdapter.blocking)
    gone = app.seed("gone", password=SECRET, blocked=True)
    where = _where(konten)
    device = Device(where.origin, where.rp_id)
    with app.store() as store:
        device.user_handle = store.user_handle(gone)
        store.add_passkey(
            konten.model2.Passkey(
                uid=secrets.token_hex(16),
                account_id=gone,
                credential_id=device.credential_id,
                public_key=device.public_key(),
                sign_count=0,
                name="Phone",
                created_at=datetime.now(UTC),
            )
        )
        store.commit()
    _refused(konten, lambda: _sign_in(app, konten, device, origin="https://app.example.net"), "passkey_invalid")
    _refused(konten, lambda: _sign_in(app, konten, device), "account_blocked")


def test_the_last_factor_stays_where_the_operator_requires_one(app: Any, konten: Any) -> None:
    secret = SECRET
    alex = app.seed("alex", password=secret)
    _, first = _register(app, konten, alex)
    app.switch("factor_required", True)
    with app.store() as store:
        _refused(konten, lambda: konten.passkeys.remove(store, alex, first.uid, password=secret), "factor_required")
    _, second = _register(app, konten, alex)
    with app.store() as store:
        _refused(konten, lambda: konten.passkeys.remove(store, alex, first.uid, password=password()), "wrong_password")
        assert konten.passkeys.remove(store, alex, first.uid, password=secret) is True
    with app.store() as store:
        assert [key.uid for key in store.passkeys_of(alex)] == [second.uid]


def test_the_operators_reset_takes_the_passkeys_too(app: Any, konten: Any, operator: tuple[Any, str]) -> None:
    boss, boss_secret = operator
    alex = app.seed("alex", password=SECRET)
    device, _ = _register(app, konten, alex)
    with app.store() as store:
        assert konten.factor.operator_reset(store, alex, actor_id=boss, password=boss_secret) is None
    with app.store() as store:
        assert store.passkeys_of(alex) == [] and not konten.factor.has_factor(store, alex)
    _refused(konten, lambda: _sign_in(app, konten, device), "passkey_invalid")


def test_the_operators_reset_shows_the_passkeys_and_removes_them_unless_asked_not_to(
    app: Any, konten: Any, operator: tuple[Any, str]
) -> None:
    """Decided 25.11.2026 (0.3.3): the dialog shows the account's passkeys and offers "Remove the passkeys too",
    ticked by default (a lost phone may carry one)."""
    boss, boss_secret = operator
    alex = app.seed("alex", password=SECRET)
    device, _ = _register(app, konten, alex, name="Lost phone")
    with app.store() as store:
        seen = konten.factor.reset_overview(store, alex, actor_id=boss)
        _refused(konten, lambda: konten.factor.reset_overview(store, boss, actor_id=boss), "use_account_page")
    assert [key.name for key in seen.passkeys] == ["Lost phone"] and not seen.authenticator
    with app.store() as store:
        konten.factor.operator_reset(store, alex, actor_id=boss, password=boss_secret, remove_passkeys=False)
    with app.store() as store:
        assert len(store.passkeys_of(alex)) == 1
    assert _sign_in(app, konten, device).id == alex
    with app.store() as store:
        konten.factor.operator_reset(store, alex, actor_id=boss, password=boss_secret)
    with app.store() as store:
        assert store.passkeys_of(alex) == []


def test_the_reset_dialog_offers_to_remove_passkeys_only_for_an_account_that_has_some(
    app: Any, konten: Any, operator: tuple[Any, str]
) -> None:
    """Decided while building (0.3.4): the box "Remove the passkeys too" (and the list of passkeys) shows only when
    the account has passkeys; ``ResetOverview.parts`` names the parts as ``SECTIONS.operatorFactorReset`` does."""
    boss, _ = operator
    alex = app.seed("alex", password=SECRET)
    kim = app.seed("kim", password=SECRET)
    _register(app, konten, alex)
    with app.store() as store:
        with_keys = konten.factor.reset_overview(store, alex, actor_id=boss)
        without = konten.factor.reset_overview(store, kim, actor_id=boss)
    assert with_keys.parts == ("factorResetHint", "passkeys", "factorResetPasskeys", "factorResetDevices")
    assert without.parts == ("factorResetHint", "factorResetDevices")


def test_a_passkey_counts_as_the_second_factor_where_one_is_required(app: Any, konten: Any) -> None:
    """After the password (or the provider) the passkey is the second step; no authenticator is asked of it."""
    alex = app.seed("alex", password=SECRET)
    device, _ = _register(app, konten, alex)
    with app.store() as store:
        assert konten.common.next_step(store, store.get_account(alex)) == konten.NEXT_SESSION
        assert konten.factor.state(store, alex) == konten.SECOND_FACTOR_NONE
    app.switch("factor_required", True)
    with app.store() as store:
        assert store.second_factor(alex) == konten.SECOND_FACTOR_PASSKEY
        assert konten.factor.state(store, alex) == konten.SECOND_FACTOR_PASSKEY
        assert konten.common.next_step(store, store.get_account(alex)) == konten.NEXT_PASSKEY
    waiting = konten.factor.start_waiting(alex)
    account = _sign_in(app, konten, device)
    done = konten.factor.finish_waiting_by_passkey(waiting, account.id)
    assert done is not None and (done.account_id, done.method) == (alex, "passkey")
    assert konten.factor.waiting_account(waiting) is None
    plain = app.seed("plain", password=SECRET)
    with app.store() as store:
        assert konten.common.next_step(store, store.get_account(plain)) == konten.NEXT_SECOND_FACTOR_SETUP


def test_the_session_expired_dialog_offers_the_passkey_step_where_a_passkey_is_the_second_factor(
    app: Any, konten: Any
) -> None:
    """Decided while building (0.3.5): the dialog "Session expired" knows every second step. After the password it
    shows what ``next_step`` says: for an account whose second factor is a passkey "Sign in with a passkey", not a
    code field it could never fill (finding in nexnotes); then the passkey finishes the waiting sign-in."""
    alex = app.seed("alex", password=SECRET)
    device, _ = _register(app, konten, alex)
    app.switch("factor_required", True)
    assert konten.common.session_expired_parts(konten.NEXT_SIGN_IN) == (
        "sessionExpiredHint", "password", "signInAgain", "or",
    )
    with app.store() as store:
        account = konten.login.authenticate(store, "alex", SECRET)
        step = konten.common.next_step(store, account)
    parts = konten.common.session_expired_parts(step)
    assert step == konten.NEXT_PASSKEY and "passkeySignIn" in parts and "code" not in parts
    waiting = konten.factor.start_waiting(alex)
    done = konten.factor.finish_waiting_by_passkey(waiting, _sign_in(app, konten, device).id)
    assert done is not None and done.method == "passkey"
    assert konten.common.session_expired_parts(konten.NEXT_SECOND_FACTOR) == ("code", "signInAgain")
    assert konten.common.session_expired_parts(konten.NEXT_SESSION) == ()
    assert konten.common.session_expired_parts("unknown") == konten.common.session_expired_parts(konten.NEXT_SIGN_IN)
    for step in (konten.NEXT_SECOND_FACTOR_SETUP, konten.NEXT_SHOW_CODES):
        assert konten.common.session_expired_parts(step)


def test_adding_a_passkey_needs_a_public_https_address_or_the_page_on_localhost(konten: Any) -> None:
    """Since E49 (nexdiary had it): ``passkeys.can_add`` tells the box "Passkeys" whether it offers "Add a passkey";
    without, an operator reads where to enter the address, a member that the operator has to (the page's part,
    ``PasskeyAddition``). A public address set counts alone and only with https; without one only localhost."""
    can_add = konten.passkeys.can_add
    # A public https address: yes, whatever the page's name.
    for where in ({}, {"origin": "http://192.168.1.20:8570"}, {"request_url": "http://localhost:8570/api/auth/me"}):
        assert can_add("https://notes.example.com", **where) is True, where
    # A public http address: no, on localhost too (adding would fail there).
    for where in ({}, {"origin": "http://localhost:5173"}, {"request_url": "http://localhost:8570/api/auth/me"}):
        assert can_add("http://notes.example.com", **where) is False, where
        assert can_add("http://localhost:8570", **where) is False, where
    # No address: only the page on localhost.
    assert can_add("", origin="http://localhost:5173") is True
    assert can_add("", origin="https://localhost") is True
    assert can_add("", request_url="http://localhost:8570/api/auth/me") is True
    for where in (
        {"origin": "http://192.168.1.20:8570"},
        {"origin": "http://127.0.0.1:8570"},
        {"origin": "https://notes.example.com"},
        {"origin": "http://localhost.example.com"},
        {"request_url": "https://notes.example.com/settings/security"},
        {},
    ):
        assert can_add("", **where) is False, where
