"""The first account: only with the setup code, only while there is no account, and the operator signs in at once
with username or address."""

from __future__ import annotations

from typing import Any

import pytest
from konten_contract import password


def _setup(konten: Any, store: Any, **changes: Any) -> Any:
    values: dict[str, Any] = {
        "code": konten.setup.setup_code(),
        "display_name": "Alex Example",
        "username": "Alex",
        "email": "alex@example.com",
        "password": password(),
        "language": "de",
    }
    values.update(changes)
    return konten.setup.setup(store, **values).account


def test_a_wrong_setup_code_makes_no_account(app: Any, konten: Any) -> None:
    with app.store() as store:
        with pytest.raises(konten.AccountError) as caught:
            _setup(konten, store, code="WRONG-CODE-0000")
        assert caught.value.code == "setup_code_wrong" and caught.value.status == 403
        assert store.count_accounts() == 0


def test_the_setup_code_is_checked_before_any_field(app: Any, konten: Any) -> None:
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        _setup(konten, store, code="nope", display_name="", username="x", password="short")
    assert caught.value.code == "setup_code_wrong"


def test_the_setup_makes_the_operator_who_signs_in_with_username_and_address(app: Any, konten: Any) -> None:
    secret = password()
    code = konten.setup.setup_code()
    with app.store() as store:
        assert konten.setup.needed(store) is True
        account = _setup(konten, store, code=f"  {code.lower()} ", password=secret)
    assert account.operator and account.username == "alex" and account.display_name == "Alex Example"
    assert account.email == "alex@example.com" and account.email_confirmed
    assert app.sign_in("alex", secret) == account.id
    assert app.sign_in("ALEX@example.com", secret) == account.id
    with app.store() as store:
        assert konten.setup.needed(store) is False


def test_there_is_no_second_setup(app: Any, konten: Any) -> None:
    with app.store() as store:
        _setup(konten, store)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        _setup(konten, store, username="other", email="other@example.com")
    assert caught.value.code == "already_set_up" and caught.value.status == 409


def test_a_running_installation_never_asks_for_the_code(app: Any, konten: Any) -> None:
    app.seed("existing", password=password())
    with app.store() as store:
        assert konten.setup.needed(store) is False
        with pytest.raises(konten.AccountError) as caught:
            _setup(konten, store)
    assert caught.value.code == "already_set_up"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("display_name", "   ", "display_name_empty"),
        ("username", "a", "username_invalid"),
        ("username", "max@home", "username_invalid"),
        ("username", "-max", "username_invalid"),
        ("email", "not an address", "email_invalid"),
        ("password", "elevenchars", "password_too_short"),
    ],
)
def test_the_setup_refuses_a_field_that_breaks_the_rules(
    app: Any, konten: Any, field: str, value: str, code: str
) -> None:
    with app.store() as store:
        with pytest.raises(konten.AccountError) as caught:
            _setup(konten, store, **{field: value})
        assert caught.value.code == code
        assert store.count_accounts() == 0


def test_the_setup_code_also_guards_a_backup_restored_before_the_setup(app: Any, konten: Any) -> None:
    with app.store() as store:
        with pytest.raises(konten.AccountError) as caught:
            konten.setup.check_code(store, "wrong")
        assert caught.value.code == "setup_code_wrong"
        konten.setup.check_code(store, konten.setup.setup_code())
    app.seed("existing", password=password())
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.setup.check_code(store, konten.setup.setup_code())
    assert caught.value.code == "already_set_up"


def test_the_setup_takes_no_address_at_all(app: Any, konten: Any) -> None:
    with app.store() as store:
        account = _setup(konten, store, email="")
    assert account.email == ""


def test_after_the_setup_the_app_starts_a_session_or_the_setup_of_a_second_factor(app: Any, konten: Any) -> None:
    with app.store() as store:
        done = konten.setup.setup(
            store, code=konten.setup.setup_code(), display_name="Op", username="op", email="", password=password()
        )
    assert done.next in (konten.NEXT_SESSION, konten.NEXT_SECOND_FACTOR_SETUP)
    with app.store() as store:
        assert done.next == konten.common.next_step(store, done.account)
