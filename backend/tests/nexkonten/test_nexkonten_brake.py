"""The brake at every door (since 0.3.4), not only at the sign-in: a password typed to confirm a change (one's own
address or username, or an operator's action on another account), a code of the second factor, "Forgot your
password?" and the links for a new address. Each counts through the module's brake, so that no page of the app lets
somebody guess or flood where the sign-in would not.

Since 0.3.10 the brake at the sign-in itself is the module's (``login.sign_in``), checked through the app's own route
(``sign_in_from`` of the adapter), and "five free" means exactly five: the sixth attempt waits. An app whose own
tests counted six (``FREE + 1``) changes them to five."""

from __future__ import annotations

import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from konten_contract import password

ISSUER = "nexapp"
#: Five failures pass freely, exactly five (since 0.3.10; until 0.3.9 the sixth still ran): the sixth attempt waits.
FREE = 5
RUN = FREE


def _refused(konten: Any, call: Callable[[], Any]) -> str:
    with pytest.raises(konten.AccountError) as caught:
        call()
    return caught.value.code


def _doors(
    konten: Any, app: Any, operator: tuple[Any, str], alex_secret: str
) -> dict[str, Callable[[str], Any]]:
    """Each door that takes a password, as a call with the password typed there."""
    operator_id, _ = operator
    alex = app.seed("alex", email="alex@example.com", password=alex_secret)
    kim = app.seed("kim", password=password())

    def run(call: Callable[[Any], Any]) -> Any:
        with app.store() as store:
            return call(store)

    return {
        "own_address": lambda typed: run(
            lambda store: konten.profiles.change_email(store, alex, "new@example.com", password=typed)
        ),
        "own_username": lambda typed: run(
            lambda store: konten.profiles.change_username(store, alex, "alex2", actor_id=alex, password=typed)
        ),
        "operator_rename": lambda typed: run(
            lambda store: konten.profiles.change_username(store, kim, "kim2", actor_id=operator_id, password=typed)
        ),
        "operator_link": lambda typed: run(
            lambda store: konten.resets.reset_link(store, kim, actor_id=operator_id, password=typed)
        ),
        "operator_factor_reset": lambda typed: run(
            lambda store: konten.factor.operator_reset(store, kim, actor_id=operator_id, password=typed)
        ),
    }


@pytest.mark.parametrize(
    ("door", "whose"),
    [
        ("own_address", "alex"),
        ("own_username", "alex"),
        ("operator_rename", "boss"),
        ("operator_link", "boss"),
        ("operator_factor_reset", "boss"),
    ],
)
def test_a_wrong_password_at_any_door_counts_at_the_brake(
    app: Any, konten: Any, operator: tuple[Any, str], door: str, whose: str
) -> None:
    """Six wrong passwords at a door (five free), then even the right one waits (``too_many_attempts``, 429),
    counted at the account whose password it is: the operator's for an action on another account."""
    _, operator_secret = operator
    alex_secret = password()
    doors = _doors(konten, app, operator, alex_secret)
    for _ in range(RUN):
        assert _refused(konten, lambda: doors[door]("not the password at all")) == "wrong_password"
    with app.store() as store:
        account = konten.login.resolve_login(store, whose)
    right = operator_secret if whose == "boss" else alex_secret
    assert _refused(konten, lambda: doors[door](right)) == "too_many_attempts"
    assert konten.brake.BRAKE.wait((konten.brake.door_key("confirm", account.id),)) > 0


def test_the_owners_right_password_waits_too_once_a_session_guessed_five_times(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    with app.store() as store:
        for _ in range(RUN):
            assert _refused(
                konten, lambda: konten.profiles.change_email(store, alex, "a@example.com", password="wrong")
            ) == "wrong_password"
        assert _refused(
            konten, lambda: konten.profiles.change_email(store, alex, "a@example.com", password=secret)
        ) == "too_many_attempts"
        # The other doors of the same account wait as well: one count per account, not per page.
        assert _refused(
            konten, lambda: konten.profiles.change_username(store, alex, "alex2", actor_id=alex, password=secret)
        ) == "too_many_attempts"
    with app.store() as store:
        assert store.get_account(alex).email == ""


def test_a_right_password_takes_the_count_back(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    with app.store() as store:
        # Four wrong, then the right one, the last of the five free.
        for _ in range(FREE - 1):
            _refused(konten, lambda: konten.profiles.change_username(store, alex, "x1", actor_id=alex, password="no"))
        konten.profiles.change_username(store, alex, "alex2", actor_id=alex, password=secret)
        for _ in range(RUN):
            assert _refused(
                konten, lambda: konten.profiles.change_username(store, alex, "x1", actor_id=alex, password="no")
            ) == "wrong_password"


def test_codes_count_at_the_account_across_waiting_sign_ins(app: Any, konten: Any) -> None:
    """Each waiting sign-in ends after five wrong codes; the brake counts the codes of the account across them, so
    that a new sign-in with the password does not give five more."""
    secret = password()
    alex = app.seed("alex", password=secret)
    with app.store() as store:
        enrolment = konten.factor.begin_totp(store, alex, issuer=ISSUER)
        konten.factor.confirm_totp(store, alex, konten.factor.code_at(enrolment.seed, time.time()), password=secret)
    right = konten.factor.code_at(enrolment.seed, time.time() + 30)
    wrong = str((int(right[0]) + 5) % 10) + right[1:]
    with app.store() as store:
        first = konten.factor.start_waiting(alex)
        for _ in range(3):
            assert _refused(konten, lambda: konten.factor.finish_waiting(store, first, wrong)) == "code_wrong"
        second = konten.factor.start_waiting(alex)
        for _ in range(RUN - 3):
            assert _refused(konten, lambda: konten.factor.finish_waiting(store, second, wrong)) == "code_wrong"
        assert _refused(konten, lambda: konten.factor.finish_waiting(store, second, right)) == "too_many_attempts"
        assert _refused(konten, lambda: konten.factor.check_code(store, alex, right)) == "too_many_attempts"


def test_forgot_counts_the_sender_and_mails_one_account_only_so_often(app: Any, konten: Any) -> None:
    app.seed("alex", email="alex@example.com", password=password())
    jobs: list[Any] = []
    sent: list[Any] = []

    def ask(typed: str, sender: str) -> None:
        konten.resets.forgot_in_background(typed, open_store=app.store, send=sent.append, later=jobs.append,
                                           sender=sender)

    for _ in range(10):
        ask("alex", "203.0.113.9")
    # The same answer for every input once the sender's count is full: nothing tells a name from no account.
    assert _refused(konten, lambda: ask("alex", "203.0.113.9")) == "too_many_attempts"
    assert _refused(konten, lambda: ask("nobody", "203.0.113.9")) == "too_many_attempts"
    ask("alex", "198.51.100.7")
    for job in jobs:
        job()
    # Eleven requests reached the worker; the account got five links (five free), the rest were held back quietly.
    assert len(jobs) == 11 and len(sent) == RUN


def test_links_for_a_new_address_count_at_the_account(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    with app.store() as store:
        konten.profiles.change_email(store, alex, "new@example.com", password=secret, mail=True)
        for _ in range(RUN - 1):
            konten.profiles.resend_email_link(store, alex)
        assert _refused(konten, lambda: konten.profiles.resend_email_link(store, alex)) == "too_many_attempts"
        assert _refused(
            konten, lambda: konten.profiles.change_email(store, alex, "other@example.com", password=secret, mail=True)
        ) == "too_many_attempts"


class _Clock:
    """The brake's clock, moved by the test (the brake reads ``time.monotonic`` only)."""

    def __init__(self) -> None:
        self.now = 10_000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(konten: Any, monkeypatch: pytest.MonkeyPatch) -> _Clock:
    held = _Clock()
    monkeypatch.setattr(konten.brake, "time", SimpleNamespace(monotonic=held.monotonic))
    return held


def test_a_waiting_account_answers_like_a_wrong_password_and_signs_in_after_the_wait(
    app: Any, konten: Any, clock: _Clock
) -> None:
    """Decided for 0.3.10 (found in nexnotes, nextasks, nexpaper): ten wrong passwords from many senders get the
    answer of a wrong password every time (401, the app's old code), also while the count of the account waits: the
    brake then checks no password and tells nothing about the account. After the wait the right password signs in:
    the attempts the brake held back did not count towards the lock."""
    secret = password()
    alex = app.seed("alex", email="alex@example.com", password=secret)
    for number in range(10):
        typed = "alex" if number % 2 else "ALEX@example.com"
        assert app.sign_in_from(typed, "not the password", f"203.0.113.{number + 1}") == (401, None), number
    # While the account's count waits even the right password is answered like a wrong one, and not checked.
    assert app.sign_in_from("alex", secret, "198.51.100.1") == (401, None)
    clock.now += 3600 * 2
    assert app.sign_in_from("alex", secret, "198.51.100.2") == (200, alex)


def test_the_lock_after_ten_wrong_passwords_stays_next_to_the_brake(app: Any, konten: Any, clock: _Clock) -> None:
    """The brake does not replace the lock of the account (ten wrong passwords, a while): ten wrong passwords that
    the brake let through lock it, and then the right one is answered like a wrong one too."""
    if not app.lock_after:
        return
    secret = password()
    app.seed("alex", password=secret)
    for number in range(app.lock_after):
        clock.now += 3600 * 2
        assert app.sign_in_from("alex", "not the password", f"203.0.113.{number + 1}") == (401, None), number
    clock.now += 3600 * 2
    assert app.sign_in_from("alex", secret, "198.51.100.3") == (401, None)


def test_too_many_attempts_only_when_the_senders_count_is_full(app: Any, konten: Any, clock: _Clock) -> None:
    """429 comes only from the sender's count (thirty free), the same for a name that exists and one that does not;
    the count of one account or of one typed text never answers 429."""
    app.seed("alex", password=password())
    for number in range(30):
        assert app.sign_in_from(f"nobody{number}", "x", "192.0.2.50") == (401, None), number
    assert app.sign_in_from("alex", "x", "192.0.2.50")[0] == 429
    assert app.sign_in_from("nobody-else", "x", "192.0.2.50")[0] == 429
    for number in range(8):
        assert app.sign_in_from("nobody", "x", f"198.51.100.{number + 10}") == (401, None), number
