"""Signing in: "Username or email" and the password. Only confirmed addresses no other account has; the display name
never; one refusal for everything."""

from __future__ import annotations

from typing import Any

import pytest
from konten_contract import password


def test_a_username_signs_in_in_any_case(app: Any) -> None:
    secret = password()
    account_id = app.seed("alex", password=secret)
    for typed in ("alex", "ALEX", " Alex "):
        assert app.sign_in(typed, secret) == account_id, typed


def test_a_username_of_the_older_version_with_capitals_keeps_working(app: Any) -> None:
    secret = password()
    account_id = app.seed("Kim.Lee", password=secret)
    assert app.sign_in("kim.lee", secret) == account_id
    assert app.sign_in("Kim.Lee", secret) == account_id


def test_a_one_letter_name_of_the_older_version_keeps_working(app: Any) -> None:
    secret = password()
    account_id = app.seed("Q", password=secret)
    assert app.sign_in("q", secret) == account_id


def test_the_brake_counts_one_account_once_however_it_is_named(app: Any, konten: Any) -> None:
    alex = app.seed("alex", email="alex@example.com", password=password())
    with app.store() as store:
        keys = {konten.login.attempt_key(store, typed, "203.0.113.9")[1] for typed in ("alex", "ALEX@example.com")}
    assert keys == {f"account:{alex}"}


def test_a_confirmed_address_signs_in_in_any_case(app: Any) -> None:
    secret = password()
    account_id = app.seed("alex", email="Alex@Example.com", password=secret)
    assert app.sign_in("alex@example.com", secret) == account_id
    assert app.sign_in("ALEX@EXAMPLE.COM", secret) == account_id


def test_an_address_that_is_not_confirmed_does_not_sign_in(app: Any) -> None:
    secret = password()
    account_id = app.seed("alex", email="alex@example.com", email_confirmed=False, password=secret)
    assert app.sign_in("alex@example.com", secret) is None
    assert app.sign_in("alex", secret) == account_id


def test_an_address_two_accounts_share_signs_in_neither_but_each_username_does(app: Any) -> None:
    first_secret, second_secret = password(), password()
    first = app.seed("first", email="shared@example.com", password=first_secret)
    second = app.seed("second", email="SHARED@example.com", password=second_secret)
    assert app.sign_in("shared@example.com", first_secret) is None
    assert app.sign_in("shared@example.com", second_secret) is None
    assert app.sign_in("first", first_secret) == first
    assert app.sign_in("second", second_secret) == second


def test_the_display_name_never_signs_in(app: Any) -> None:
    secret = password()
    app.seed("alex", display_name="Chef", password=secret)
    assert app.sign_in("Chef", secret) is None


def test_an_account_through_a_provider_only_does_not_sign_in_with_a_password(app: Any) -> None:
    app.seed("alex", email="alex@example.com", password=None)
    assert app.sign_in("alex", "") is None
    assert app.sign_in("alex", password()) is None


def test_a_blocked_account_does_not_sign_in(app: Any) -> None:
    if not app.blocking:
        return  # the app blocks no accounts (StandardAdapter.blocking)
    secret = password()
    app.seed("alex", password=secret, blocked=True)
    assert app.sign_in("alex", secret) is None


def test_every_refusal_says_the_same(app: Any, konten: Any) -> None:
    secret = password()
    app.seed("alex", email="alex@example.com", password=secret)
    app.seed("pending", email="pending@example.com", email_confirmed=False, password=secret)
    answers = set()
    for typed, given in (
        ("alex", secret + "x"),
        ("nobody", secret),
        ("nobody@example.com", secret),
        ("pending@example.com", secret),
        ("", secret),
    ):
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            konten.login.authenticate(store, typed, given)
        answers.add((caught.value.code, caught.value.message, caught.value.status))
    assert answers == {("wrong_credentials", "Username, email or password is wrong.", 401)}


def test_a_blocked_account_hears_so_only_after_its_right_password(app: Any, konten: Any) -> None:
    if not app.blocking:
        return  # the app blocks no accounts (StandardAdapter.blocking)
    secret = password()
    app.seed("alex", password=secret, blocked=True)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.login.authenticate(store, "alex", secret + "x")
    assert caught.value.code == "wrong_credentials"
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.login.authenticate(store, "alex", secret)
    assert caught.value.code == "account_blocked"


def test_a_password_of_the_older_version_shorter_than_the_rule_still_signs_in(app: Any) -> None:
    short = password()[:10]
    account_id = app.seed("alex", password=short)
    assert app.sign_in("alex", short) == account_id


def test_a_former_username_does_not_sign_in_in_the_browser(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    with app.store() as store:
        konten.profiles.change_username(store, alex, "alexa", actor_id=alex, password=secret)
    assert app.sign_in("alex", secret) is None
    assert app.sign_in("alexa", secret) == alex


def test_programs_in_the_background_find_the_account_by_current_or_former_name_or_address(
    app: Any, konten: Any
) -> None:
    secret = password()
    alex = app.seed("alex", email="alex@example.com", email_confirmed=False, password=secret)
    app.seed("one", email="shared@example.com", password=password())
    app.seed("two", email="shared@example.com", password=password())
    with app.store() as store:
        konten.profiles.change_username(store, alex, "alexa", actor_id=alex, password=secret)
    with app.store() as store:
        for typed in ("alexa", "ALEX", "alex@example.com"):
            found = konten.login.background_account(store, typed)
            assert found is not None and found.id == alex, typed
        assert konten.login.background_account(store, "shared@example.com") is None
        assert konten.login.background_account(store, "nobody") is None


def test_wrong_passwords_lock_the_account_however_it_is_named(app: Any, konten: Any) -> None:
    if not app.lock_after:
        return
    secret = password()
    alex = app.seed("alex", email="alex@example.com", password=secret)
    for index in range(app.lock_after):
        typed = "alex" if index % 2 else "ALEX@example.com"
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            konten.login.authenticate(store, typed, secret + "x")
        assert caught.value.code == "wrong_credentials" and caught.value.account_id == alex
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.login.authenticate(store, "alex", secret)
    assert caught.value.code == "wrong_credentials"
    with app.store() as store:
        assert konten.login.authenticate(store, "alex", secret, known_browser=alex).id == alex
        konten.login.succeeded(store, alex)
    with app.store() as store:
        assert konten.login.authenticate(store, "alex", secret).id == alex


def test_failures_from_the_owners_own_browser_do_not_count(app: Any, konten: Any) -> None:
    if not app.lock_after:
        return
    secret = password()
    alex = app.seed("alex", password=secret)
    for _ in range(app.lock_after + 1):
        with app.store() as store, pytest.raises(konten.AccountError):
            konten.login.authenticate(store, "alex", secret + "x", known_browser=alex)
    with app.store() as store:
        assert konten.login.authenticate(store, "alex", secret).id == alex


def test_the_brake_counts_every_attempt_at_the_sender_and_at_what_it_names(app: Any, konten: Any) -> None:
    alex = app.seed("alex", email="alex@example.com", password=password())
    with app.store() as store:
        by_name = konten.login.attempt_key(store, "alex", "203.0.113.7")
        by_address = konten.login.attempt_key(store, "ALEX@example.com", "203.0.113.7")
        unknown = konten.login.attempt_key(store, "nobody", "203.0.113.7")
        again = konten.login.attempt_key(store, " Nobody ", "198.51.100.2")
    assert by_name == by_address == ("sender:203.0.113.7", f"account:{alex}")
    assert unknown[0] == "sender:203.0.113.7" and unknown[1].startswith("typed:")
    assert again[1] == unknown[1] and again[0] == "sender:198.51.100.2"


def test_a_brake_over_both_counts_tells_no_name_from_no_account(app: Any, konten: Any) -> None:
    """The brake as the module asks for it: both counts, for every input. Once the sender's count is full, a known
    name is refused exactly like an unknown one."""
    app.seed("alex", password=password())
    limit = 5
    counts: dict[str, int] = {}

    def attempt(typed: str) -> str:
        with app.store() as store:
            keys = konten.login.attempt_key(store, typed, "203.0.113.7")
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
        if any(counts[key] > limit for key in keys):
            return "too_many"
        return "tried"

    for index in range(limit):
        attempt(f"garbage{index}")
    answers = {typed: attempt(typed) for typed in ("alex", "bob", "alex@elsewhere.example.org")}
    assert set(answers.values()) == {"too_many"}, answers


def test_a_wrong_password_takes_as_long_for_a_known_name_as_for_an_unknown_one(app: Any, konten: Any) -> None:
    import time

    secret = password()
    for index in range(6):
        app.seed(f"user{index}", password=secret)

    def once(typed: str) -> float:
        with app.store() as store:
            started = time.perf_counter()
            with pytest.raises(konten.AccountError):
                konten.login.authenticate(store, typed, "wrong password")
            return time.perf_counter() - started

    known, unknown = [], []
    for round_ in range(5):
        for index in range(6):
            known.append(once(f"user{index}"))
            unknown.append(once(f"nobody{round_}{index}"))
    known.sort()
    unknown.sort()
    middle_known, middle_unknown = known[len(known) // 2], unknown[len(unknown) // 2]
    assert 0.6 < middle_known / middle_unknown < 1.6, (middle_known, middle_unknown)


def test_a_new_password_makes_the_known_browser_mark_worthless(app: Any, konten: Any) -> None:
    alex = app.seed("alex", email="alex@example.com", password=password())
    mark = app.open_session(alex, "known_browser")
    with app.store() as store:
        token = konten.resets.forgot(store, "alex").token
        konten.resets.use_reset(store, token, password())
    assert not app.session_alive(mark)


def test_a_known_browser_counts_in_a_pot_of_its_own_not_at_the_sender(app: Any, konten: Any) -> None:
    """Decided 25.11.2026 (0.3.3): a stranger behind the same router as the owner fills the sender's and the
    account's counts; the owner's known browser still gets five tries of its own, and only its own pot fills."""
    import secrets

    alex = app.seed("alex", password=password())
    secret = secrets.token_bytes(32)
    with app.store() as store:
        keys = konten.login.attempt_key(store, "alex", "192.0.2.10")
        key = store.device_key(alex)
        store.commit()
    cookie = konten.sessions.add_mark("", konten.sessions.mark(secret, key))
    other = konten.sessions.mark(secret, key)
    mark = konten.sessions.known_mark(cookie, secret, key)
    assert mark and konten.sessions.known_mark(cookie, secret, "another key") == ""
    held = konten.brake.BRAKE
    for _ in range(40):
        held.claim(keys)
    assert held.claim(keys) > 0
    # Five free failures, exactly five (since 0.3.10): the sixth waits.
    for _ in range(5):
        assert held.claim(keys, browser=mark) == 0.0
    assert held.claim(keys, browser=mark) > 0
    # Another browser of the owner has a pot of its own; a right password empties the pot.
    assert held.claim(keys, browser=other) == 0.0
    held.succeeded(keys, browser=mark)
    assert held.claim(keys, browser=mark) == 0.0
