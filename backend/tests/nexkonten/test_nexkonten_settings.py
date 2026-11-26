"""Since 1.1.0: what the settings of every app take from the module (plan "Einstellungen"): light or dark at the
account, the operator's sign-in switches with their rules, and "Ready for the internet?" through the app's route."""

from __future__ import annotations

from typing import Any

import pytest
from konten_contract import password


def test_the_theme_is_kept_at_the_account_and_a_browsers_value_is_taken_once(app: Any, konten: Any) -> None:
    kim = app.seed("kim", password=password())
    with app.store() as store:
        account = store.get_account(kim)
        assert account.theme == "" and konten.profiles.theme_of(account) == "system"
        # The browser's value of before 1.1.0 (nexmail kept JSON), once.
        assert konten.profiles.adopt_theme(store, kim, '"dark"') == "dark"
    with app.store() as store:
        assert store.get_account(kim).theme == "dark"
        assert konten.profiles.adopt_theme(store, kim, "light") == "dark"
        assert konten.profiles.change_theme(store, kim, "light").theme == "light"
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.profiles.change_theme(store, kim, "sepia")
    assert caught.value.code == "theme_invalid"
    # Since E45: without a value its browser kept, an account of before takes what the app showed before, once.
    other = app.seed("other", password=password())
    before = konten.config.current().theme_default_before
    with app.store() as store:
        assert konten.profiles.adopt_theme(store, other, "sepia") == before
        assert konten.profiles.adopt_theme(store, other, None) == before
    with app.store() as store:
        assert store.get_account(other).theme == before
        # Taken once: a value the browser kept later changes nothing any more.
        assert konten.profiles.adopt_theme(store, other, "light" if before != "light" else "dark") == before


def test_a_new_account_starts_with_system_whatever_the_browser_holds(app: Any, konten: Any) -> None:
    """Since E45: set up, invited or through a provider, a new account has "system" from the start; neither a value an
    earlier account left in the browser nor what the browser prefers counts as its choice."""
    with app.store() as store:
        first = konten.setup.setup(
            store, code=konten.setup.setup_code(), display_name="Alex Example", username="alex",
            email="alex@example.com", password=password(), language="de",
        ).account
    assert first.theme == "system"
    token = app.make_invite(email="new@example.com")
    with app.store() as store:
        invited = konten.invites.accept_invite(
            store, token, display_name="New Person", username="newbie", email="new@example.com", password=password(),
        ).account
    with app.store() as store:
        assert store.get_account(invited.id).theme == "system"
        assert konten.profiles.adopt_theme(store, invited.id, '"dark"') == "system"
    with app.oidc_store() as oidc:
        through_provider = oidc.create_account("provided", invite=None, email=None)
        oidc.commit()
    provided = app.account_of(through_provider)
    with app.store() as store:
        assert store.get_account(provided).theme == "system"
        assert konten.profiles.adopt_theme(store, provided, "dark") == "system"


def test_the_apps_default_of_before_is_one_of_the_themes(konten: Any) -> None:
    assert konten.config.current().theme_default_before in konten.profiles.THEMES


def test_password_sign_in_goes_off_only_with_an_active_provider(app: Any, konten: Any) -> None:
    secret = password()
    boss = app.seed("boss", password=secret, operator=True)
    app.provider_active(False)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.signin.change(store, boss, password_login=False)
    assert caught.value.code == "provider_first"
    app.provider_active(True)
    with app.store() as store:
        assert konten.signin.change(store, boss, password_login=False).password_login is False
    with app.store() as store:
        assert store.sign_in_settings().password_login is False
        assert konten.signin.change(store, boss, password_login=True).password_login is True


def test_the_second_factor_for_everybody_goes_on_only_with_an_own_one_and_off_only_with_the_password(
    app: Any, konten: Any
) -> None:
    secret = password()
    boss = app.seed("boss", password=secret, operator=True)
    app.switch("factor_required", False)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.signin.change(store, boss, factor_required=True)
    assert caught.value.code == "own_second_factor_first"
    with app.store() as store:
        assert konten.signin.view(store, boss)["factor_may_go_on"] is False
        # A provider that checks the second factor itself let the operator in: no lock-out.
        assert konten.signin.may_require_factor(store, boss, provider_checked=True) is True
    guarded = app.seed("guarded", password=secret, operator=True, second_factor="active")
    with app.store() as store:
        assert konten.signin.view(store, guarded)["factor_may_go_on"] is True
        assert konten.signin.change(store, guarded, factor_required=True).factor_required is True
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.signin.change(store, guarded, factor_required=False, password=secret + "x")
    assert caught.value.code == "wrong_password"
    with app.store() as store:
        assert store.sign_in_settings().factor_required is True
        assert konten.signin.change(store, guarded, factor_required=False, password=secret).factor_required is False


def test_passkeys_allowed_is_a_plain_switch_and_only_operators_change_any(app: Any, konten: Any) -> None:
    boss = app.seed("boss", password=password(), operator=True)
    member = app.seed("member", password=password())
    with app.store() as store:
        assert konten.signin.change(store, boss, passkeys_allowed=False).passkeys_allowed is False
    with app.store() as store:
        assert store.sign_in_settings().passkeys_allowed is False
        konten.signin.change(store, boss, passkeys_allowed=True)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.signin.change(store, member, passkeys_allowed=False)
    assert caught.value.code == "not_allowed"


def test_ready_for_the_internet_through_the_apps_route(app: Any, konten: Any) -> None:
    boss = app.seed("boss", password=password(), operator=True)
    found = app.readiness(boss)
    assert found["state"] in ("ok", "warn", "bad")
    keys = [point["key"] for point in found["points"]]
    common = [key for key in keys if key in konten.readiness.POINTS]
    assert common == list(konten.readiness.POINTS), "every common point, in the module's order"
    for point in found["points"]:
        assert point["state"] in ("ok", "warn", "bad")
        assert point["title"] and point["text"], point
        if point["key"] in konten.readiness.POINTS:
            assert point["title"] == f"account.ready.{point['key']}.title"
    assert found["open"] == sum(1 for point in found["points"] if point["state"] != "ok")
    # The operator has no second factor yet: their own account is open.
    assert next(point for point in found["points"] if point["key"] == "ownAccount")["state"] == "bad"


def test_addresses_of_before_the_update_need_no_link_and_a_new_one_does(app: Any, konten: Any) -> None:
    """E23: after the migration to 1.1.0 every address of before that counts is proven, so the box "Address not
    confirmed yet" does not show for it (nexpaper keeps its unproven ones); an address entered from now on without a
    link shows it."""
    legacy = app.legacy()
    typed = [login for login, _secret, works in legacy.logins if "@" in login and works]
    assert typed, "the older version's database has an address that signs in"
    with app.store() as store:
        for address in typed:
            for account in store.find_by_email(address):
                if account.email_confirmed and not app.keeps_unproven_addresses:
                    assert account.email_proven, address
                    assert not konten.profiles.needs_proof(account, mail_server=True), address
    secret = password()
    kim = app.seed("newcomer", password=secret)
    with app.store() as store:
        konten.profiles.change_email(store, kim, "newcomer@example.com", password=secret, mail=False)
    with app.store() as store:
        account = store.get_account(kim)
        assert account.email == "newcomer@example.com" and account.email_confirmed and not account.email_proven
        assert konten.profiles.needs_proof(account, mail_server=True)
        assert not konten.profiles.needs_proof(account, mail_server=False)
