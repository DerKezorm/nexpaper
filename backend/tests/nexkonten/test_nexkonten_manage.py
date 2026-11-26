"""Since 1.1.0: the operator's account functions, the same in every app (plan "Einstellungen", Accounts): several
operators, block and unblock, delete with 30 days to bring back, purge after them; the storage limit and the rights
only where the app has the feature (``config.FEATURES``)."""

from __future__ import annotations

from typing import Any

import pytest
from konten_contract import password

#: The eight apps of the plan; an adapter of another name (the module's own tests) has no row to be held to.
APPS = ("nexnotes", "nexmail", "nextasks", "nextime", "nexpaper", "nexdiary", "nexlore", "nexfolk")


def _operator(app: Any) -> tuple[Any, str]:
    secret = password()
    return app.seed("boss", password=secret, operator=True), secret


def test_the_app_has_exactly_its_row_of_the_feature_table(konten: Any) -> None:
    config = konten.current()
    # The features come from the module's table by the app's name, never from the app (only the module's own tests,
    # for an app of another name, name them by hand).
    if config.app_name in APPS:
        assert config.features is None
    assert config.feature_set == (
        konten.config.features_of(config.app_name) if config.features is None else frozenset(config.features)
    )


def test_several_operators_and_back_to_member_with_the_own_password(app: Any, konten: Any) -> None:
    boss, secret = _operator(app)
    kim = app.seed("kim", password=password())
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.manage.set_role(store, kim, True, actor_id=boss, password=secret + "x")
    assert caught.value.code == "wrong_password"
    with app.store() as store:
        assert konten.manage.set_role(store, kim, True, actor_id=boss, password=secret).operator is True
        assert store.active_operators() == 2
    with app.store() as store:
        assert konten.manage.set_role(store, kim, False, actor_id=boss, password=secret).operator is False
        assert store.active_operators() == 1


def test_nothing_of_this_on_the_own_account(app: Any, konten: Any) -> None:
    boss, secret = _operator(app)
    for act, code in (
        (
            lambda store: konten.manage.set_role(store, boss, False, actor_id=boss, password=secret),
            "cannot_demote_self",
        ),
        (lambda store: konten.manage.block(store, boss, actor_id=boss, password=secret), "cannot_block_self"),
        (lambda store: konten.manage.remove(store, boss, actor_id=boss, password=secret), "cannot_delete_self"),
    ):
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            act(store)
        assert caught.value.code == code
    with app.store() as store:
        account = store.get_account(boss)
        assert account.operator and account.blocked_at is None and account.deleted_at is None


def test_a_member_does_none_of_this(app: Any, konten: Any) -> None:
    _operator(app)
    secret = password()
    kim = app.seed("kim", password=secret)
    alex = app.seed("alex", password=password())
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.manage.block(store, alex, actor_id=kim, password=secret)
    assert caught.value.code == "not_allowed"


def test_the_store_counts_only_operators_who_can_sign_in(app: Any, konten: Any) -> None:
    boss, secret = _operator(app)
    other = app.seed("other", password=password(), operator=True)
    third = app.seed("third", password=password(), operator=True)
    app.seed("member", password=password())
    with app.store() as store:
        assert store.active_operators() == 3
        konten.manage.block(store, other, actor_id=boss, password=secret)
    with app.store() as store:
        assert store.active_operators() == 2
        konten.manage.remove(store, third, actor_id=boss, password=secret)
    with app.store() as store:
        assert store.active_operators() == 1


def test_blocking_shuts_every_way_and_unblocking_lets_in_without_the_old_sessions(app: Any, konten: Any) -> None:
    boss, secret = _operator(app)
    own = password()
    kim = app.seed("kim", password=own)
    browser = app.open_session(kim, "browser")
    device = app.open_session(kim, "device")
    with app.store() as store:
        blocked = konten.manage.block(store, kim, actor_id=boss, password=secret)
    assert blocked.blocked and blocked.blocked_at is not None
    assert not app.session_alive(browser) and not app.session_alive(device)
    assert app.sign_in("kim", own) is None
    with app.store() as store:
        # Again: nothing happens.
        assert konten.manage.block(store, kim, actor_id=boss, password=secret).blocked_at == blocked.blocked_at
        unblocked = konten.manage.unblock(store, kim, actor_id=boss, password=secret)
    assert not unblocked.blocked and unblocked.blocked_at is None
    assert app.sign_in("kim", own) == kim
    assert not app.session_alive(browser)


def test_a_blocked_account_of_the_older_version_is_unblocked_with_the_functions(app: Any, konten: Any) -> None:
    boss, secret = _operator(app)
    own = password()
    gone = app.seed("gone", password=own, blocked=True)
    with app.store() as store:
        assert store.get_account(gone).blocked_at is not None
        konten.manage.unblock(store, gone, actor_id=boss, password=secret)
    assert app.sign_in("gone", own) == gone


def test_deleting_keeps_the_account_thirty_days_to_bring_back(app: Any, konten: Any) -> None:
    boss, secret = _operator(app)
    own = password()
    kim = app.seed("kim", email="kim@example.com", password=own)
    session = app.open_session(kim, "browser")
    with app.store() as store:
        removed = konten.manage.remove(store, kim, actor_id=boss, password=secret)
    assert removed.account.deleted_at is not None and removed.account.blocked
    assert removed.purge_at == konten.manage.purge_at(removed.account.deleted_at)
    assert (removed.purge_at - removed.account.deleted_at).days == konten.manage.DELETE_DAYS == 30
    assert not app.session_alive(session)
    assert app.sign_in("kim", own) is None
    with app.store() as store:
        # Its name stays taken while it can come back.
        assert konten.names.username_taken(store, "kim") is True
        assert konten.manage.purge_due(store) == []
        back = konten.manage.restore(store, kim, actor_id=boss, password=secret)
    assert back.deleted_at is None and not back.blocked
    assert app.sign_in("kim", own) == kim


def test_deleting_lets_every_open_password_link_lapse_and_bringing_back_brings_none(app: Any, konten: Any) -> None:
    """Since E37: the operator's link as well as the one the person asked for; the same in every app."""
    boss, secret = _operator(app)
    kim = app.seed("kim", email="kim@example.com", password=password())
    ann = app.seed("ann", email="ann@example.com", password=password())
    with app.store() as store:
        by_operator = konten.resets.reset_link(store, kim, actor_id=boss, password=secret, mail=False).token
        asked = konten.resets.forgot(store, "ann@example.com")
    assert by_operator and asked is not None and asked.token
    with app.store() as store:
        for target in (kim, ann):
            konten.manage.remove(store, target, actor_id=boss, password=secret)
    with app.store() as store:
        for target in (kim, ann):
            konten.manage.restore(store, target, actor_id=boss, password=secret)
    for token in (by_operator, asked.token):
        with app.store() as store, pytest.raises(konten.AccountError) as refused:
            konten.resets.use_reset(store, token, password())
        assert refused.value.code == "reset_invalid"
    # A new link after the return works as ever.
    with app.store() as store:
        fresh = konten.resets.reset_link(store, kim, actor_id=boss, password=secret, mail=False).token
        konten.resets.use_reset(store, fresh, password())


def test_after_its_days_a_deleted_account_goes_for_good_and_its_name_stays_reserved(app: Any, konten: Any) -> None:
    boss, secret = _operator(app)
    kim = app.seed("kim", password=password())
    with app.store() as store:
        konten.manage.remove(store, kim, actor_id=boss, password=secret)
    app.age_deletion(kim, konten.manage.DELETE_DAYS + 1)
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.manage.restore(store, kim, actor_id=boss, password=secret)
    assert caught.value.code == "not_found"
    with app.store() as store:
        assert konten.manage.purge_due(store) == [kim]
    with app.store() as store:
        assert store.get_account(kim) is None
        assert konten.names.username_taken(store, "kim") is True
        assert konten.manage.purge_due(store) == []


def test_a_deleted_account_cannot_be_blocked_or_given_a_role(app: Any, konten: Any) -> None:
    boss, secret = _operator(app)
    kim = app.seed("kim", password=password())
    with app.store() as store:
        konten.manage.remove(store, kim, actor_id=boss, password=secret)
    for act in (
        lambda store: konten.manage.block(store, kim, actor_id=boss, password=secret),
        lambda store: konten.manage.set_role(store, kim, True, actor_id=boss, password=secret),
    ):
        with app.store() as store, pytest.raises(konten.AccountError) as caught:
            act(store)
        assert caught.value.code == "not_found"


def test_the_storage_limit_only_where_the_app_has_it(app: Any, konten: Any) -> None:
    boss, secret = _operator(app)
    kim = app.seed("kim", password=password())
    has = konten.current().has(konten.config.FEATURE_STORAGE_LIMIT)
    with app.store() as store:
        if not has:
            with pytest.raises(konten.AccountError) as caught:
                konten.manage.set_storage_limit(store, kim, 5 * 1024**3, actor_id=boss, password=secret)
            assert caught.value.code == "feature_off"
            return
        limited = konten.manage.set_storage_limit(store, kim, 5 * 1024**3, actor_id=boss, password=secret)
        assert limited.storage_limit == 5 * 1024**3
    with app.store() as store, pytest.raises(konten.AccountError) as caught:
        konten.manage.set_storage_limit(store, kim, -1, actor_id=boss, password=secret)
    assert caught.value.code == "invalid_limit"
    with app.store() as store:
        assert konten.manage.set_storage_limit(store, kim, None, actor_id=boss, password=secret).storage_limit is None


def test_the_rights_of_the_app_save_at_once_without_a_password(app: Any, konten: Any) -> None:
    boss, _secret = _operator(app)
    kim = app.seed("kim", password=password())
    for right in konten.config.RIGHTS:
        with app.store() as store:
            if not konten.current().has(right):
                with pytest.raises(konten.AccountError) as caught:
                    konten.manage.set_right(store, kim, right, True, actor_id=boss)
                assert caught.value.code == "feature_off"
                continue
            assert right in konten.manage.set_right(store, kim, right, True, actor_id=boss).rights
        with app.store() as store:
            assert right in store.get_account(kim).rights
            assert right not in konten.manage.set_right(store, kim, right, False, actor_id=boss).rights
