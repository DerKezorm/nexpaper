"""The app's store for the OIDC module answers with nexkonten: the same naming rules, reserved names, a display name
from the provider only when nobody else shows it, the provider's address never counting at once and never another
account's."""

from __future__ import annotations

from typing import Any

from konten_contract import password


def _create(app: Any, **values: Any) -> Any:
    arguments: dict[str, Any] = {"invite": None, "email": None, "display_name": "", "picture": ""}
    arguments.update(values)
    name = arguments.pop("name", "newcomer")
    with app.oidc_store() as oidc:
        created = oidc.create_account(name, **arguments)
        oidc.commit()
    return app.account_of(created)


def test_the_oidc_store_takes_the_naming_rules_of_konten(app: Any) -> None:
    with app.oidc_store() as oidc:
        assert oidc.clean_name("Max Müller") == "max-mueller"
        assert oidc.clean_name("max-2") == "max-2"
        assert oidc.clean_name("🦊") == ""


def test_a_former_name_and_a_display_name_are_taken_for_the_oidc_module(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    app.seed("kim", display_name="Chef", password=password())
    with app.store() as store:
        konten.profiles.change_username(store, alex, "alexa", actor_id=alex, password=secret)
    with app.oidc_store() as oidc:
        assert oidc.name_taken("ALEX") and oidc.name_taken("alexa") and oidc.name_taken("chef")
        assert not oidc.name_taken("nobody")


def test_a_display_name_from_the_provider_that_another_account_shows_stays_empty(app: Any) -> None:
    app.seed("kim", display_name="Kim Lee", password=password())
    taken = _create(app, name="kim2", display_name="KIM LEE")
    free = _create(app, name="alex", display_name="Alex Example")
    with app.store() as store:
        assert store.get_account(taken).display_name == ""
        assert store.get_account(free).display_name == "Alex Example"


def test_the_providers_address_follows_but_does_not_count(app: Any, konten: Any) -> None:
    account_id = _create(app, email="new@example.com")
    with app.store() as store:
        account = store.get_account(account_id)
    assert account.email == "new@example.com" and not account.email_confirmed and not account.email_proven
    assert account.email_source == konten.EMAIL_PROVIDER
    assert app.sign_in("new@example.com", "") is None


def test_an_address_another_account_has_is_not_taken_from_the_provider(app: Any) -> None:
    app.seed("kim", email="kim@example.com", password=password())
    account_id = _create(app, email="KIM@example.com")
    with app.store() as store:
        assert store.get_account(account_id).email == ""


def test_a_provider_address_follows_only_an_account_without_one_of_its_own(app: Any, konten: Any) -> None:
    own = app.seed("own", email="own@example.com", password=password())
    follows = app.seed("follows", password=None)
    with app.store() as store:
        assert not konten.profiles.follow_provider_email(store, own, "other@example.com")
        assert konten.profiles.follow_provider_email(store, follows, "first@example.com")
        assert konten.profiles.follow_provider_email(store, follows, "second@example.com")
        store.commit()
    with app.store() as store:
        assert store.get_account(own).email == "own@example.com"
        followed = store.get_account(follows)
    assert followed.email == "second@example.com" and not followed.email_confirmed


def test_a_provider_address_is_only_offered_to_an_account_with_a_password(app: Any, konten: Any) -> None:
    """Decided 25.11.2026 (0.3.3): an account with a password is only offered the provider's address ("Use the
    address from <provider>?"); an account through a provider only takes it at once."""
    secret = password()
    alex = app.seed("alex", password=secret)
    own = app.seed("own", email="own@example.com", password=secret)
    via = app.seed("via", password=None)
    profiles = konten.profiles
    with app.store() as store:
        assert profiles.provider_email(store, alex, "alex@id.example.com") == profiles.PROVIDER_EMAIL_OFFERED
        assert profiles.provider_email(store, own, "other@example.com") == profiles.PROVIDER_EMAIL_OFFERED
        assert profiles.provider_email(store, via, "via@example.com") == profiles.PROVIDER_EMAIL_TAKEN
        assert profiles.provider_email(store, alex, "VIA@example.com") == profiles.PROVIDER_EMAIL_NONE
        store.commit()
    with app.store() as store:
        offered = store.get_account(alex)
        assert (offered.email, offered.offered_email) == ("", "alex@id.example.com")
        assert store.get_account(own).email == "own@example.com"
        assert store.get_account(via).email == "via@example.com"
    assert app.sign_in("alex@id.example.com", secret) is None
    with app.store() as store:
        try:
            profiles.take_offered_email(store, alex, password=password())
            raise AssertionError("taken without the password")
        except konten.AccountError as error:
            assert error.code == "wrong_password"
    with app.store() as store:
        done = profiles.take_offered_email(store, alex, password=secret)
    assert done.account.email == "alex@id.example.com" and done.account.email_confirmed
    assert done.account.offered_email == "" and done.account.email_source == konten.EMAIL_OWN
    with app.store() as store:
        profiles.dismiss_offered_email(store, own)
    with app.store() as store:
        kept = store.get_account(own)
    assert (kept.email, kept.offered_email) == ("own@example.com", "")


def test_an_offer_keeps_the_providers_name_and_no_thanks_holds_for_that_address(app: Any, konten: Any) -> None:
    """Decided while building (0.3.4): the module keeps the name of the provider with the offered address ("Use the
    address from Pocket ID?"), and "No, thanks" holds for good for exactly this address: the offer comes back only
    with another one."""
    secret = password()
    alex = app.seed("alex", password=secret)
    profiles = konten.profiles
    with app.store() as store:
        assert profiles.provider_email(store, alex, "alex@id.example.com", provider="Pocket ID") == "offered"
        store.commit()
    with app.store() as store:
        offered = store.get_account(alex)
        assert (offered.offered_email, offered.offered_email_provider) == ("alex@id.example.com", "Pocket ID")
        profiles.dismiss_offered_email(store, alex)
    for _ in range(2):  # the next sign-ins at the provider
        with app.store() as store:
            assert profiles.provider_email(store, alex, "ALEX@id.example.com", provider="Pocket ID") == ""
            store.commit()
        with app.store() as store:
            kept = store.get_account(alex)
            assert (kept.offered_email, kept.offered_email_provider) == ("", "")
            assert kept.declined_email == "alex@id.example.com"
    with app.store() as store:
        assert profiles.provider_email(store, alex, "new@id.example.com", provider="authentik") == "offered"
        store.commit()
    with app.store() as store:
        again = store.get_account(alex)
        assert (again.offered_email, again.offered_email_provider) == ("new@id.example.com", "authentik")
        # Without a name (a caller of 0.3.3) the offer still comes; the name is then the app's to fill.
        assert profiles.provider_email(store, alex, "new@id.example.com") == "offered"
