"""Since 1.1.5 (G26, decided 27.11.2026): paired devices rest while their account is blocked or deleted with its days
to bring it back. The app refuses them meanwhile (its own form, ``401 account_blocked``), keeps them, and lets them in
again after unblocking or bringing the account back, without pairing anew. The purge removes them; "sign out
everywhere" and the operator's reset of the second factor (``disconnect_devices=True``) disconnect them for good.

An app without paired devices (``StandardAdapter.paired_devices`` False: nexdiary, nexfolk until their iPhone app) is
passed over; every app with devices passes these."""

from __future__ import annotations

from typing import Any

from konten_contract import password


def _operator(app: Any) -> tuple[Any, str]:
    secret = password()
    return app.seed("boss", password=secret, operator=True), secret


def _rests(app: Any, device: Any, label: str) -> None:
    assert not app.device_works(device), f"{label}: the device of an account that is out is refused"
    assert app.device_kept(device), f"{label}: the device rests, it is not disconnected (G26)"


def _works(app: Any, device: Any, label: str) -> None:
    assert app.device_works(device), f"{label}: the device works again without pairing anew"
    assert app.device_kept(device), label


def _gone(app: Any, device: Any, label: str) -> None:
    assert not app.device_works(device), f"{label}: the device is refused"
    assert not app.device_kept(device), f"{label}: the device is disconnected for good"


def test_a_device_rests_while_its_account_is_blocked_and_works_again_after_unblocking(app: Any, konten: Any) -> None:
    if not app.paired_devices or not app.blocking:
        return  # the app pairs no devices, or blocks no accounts (StandardAdapter.paired_devices, .blocking)
    boss, secret = _operator(app)
    kim = app.seed("kim", password=password())
    device = app.pair_device(kim)
    _works(app, device, "paired")
    with app.store() as store:
        konten.manage.block(store, kim, actor_id=boss, password=secret)
    _rests(app, device, "blocked")
    with app.store() as store:
        konten.manage.unblock(store, kim, actor_id=boss, password=secret)
    _works(app, device, "unblocked")


def test_a_device_rests_while_its_account_is_deleted_and_works_again_after_bringing_it_back(
    app: Any, konten: Any
) -> None:
    if not app.paired_devices:
        return  # the app pairs no devices (StandardAdapter.paired_devices)
    boss, secret = _operator(app)
    kim = app.seed("kim", password=password())
    device = app.pair_device(kim)
    with app.store() as store:
        konten.manage.remove(store, kim, actor_id=boss, password=secret)
    _rests(app, device, "deleted")
    with app.store() as store:
        konten.manage.restore(store, kim, actor_id=boss, password=secret)
    _works(app, device, "brought back")
    if not app.blocking:
        return  # the rest blocks the account
    # Blocked, then deleted and brought back blocked: it rests all along and works once unblocked.
    with app.store() as store:
        konten.manage.block(store, kim, actor_id=boss, password=secret)
    with app.store() as store:
        konten.manage.remove(store, kim, actor_id=boss, password=secret)
    _rests(app, device, "blocked and deleted")
    with app.store() as store:
        konten.manage.restore(store, kim, actor_id=boss, password=secret)
    _rests(app, device, "brought back blocked")
    with app.store() as store:
        konten.manage.unblock(store, kim, actor_id=boss, password=secret)
    _works(app, device, "unblocked after bringing back")


def test_the_purge_removes_the_devices(app: Any, konten: Any) -> None:
    if not app.paired_devices:
        return  # the app pairs no devices (StandardAdapter.paired_devices)
    boss, secret = _operator(app)
    kim = app.seed("kim", password=password())
    alex = app.seed("alex", password=password())
    device, other = app.pair_device(kim), app.pair_device(alex)
    with app.store() as store:
        konten.manage.remove(store, kim, actor_id=boss, password=secret)
    app.age_deletion(kim, konten.manage.DELETE_DAYS + 1)
    with app.store() as store:
        assert konten.manage.purge_due(store) == [kim]
    _gone(app, device, "purged")
    _works(app, other, "another account's device")


def test_sign_out_everywhere_and_the_operators_reset_disconnect_the_devices_for_good(app: Any, konten: Any) -> None:
    if not app.paired_devices:
        return  # the app pairs no devices (StandardAdapter.paired_devices)
    boss, secret = _operator(app)
    kim = app.seed("kim", password=password())
    alex = app.seed("alex", password=password())
    everywhere, reset = app.pair_device(kim), app.pair_device(alex)
    with app.store() as store:
        konten.sessions.sign_out_everywhere(store, kim)
        store.commit()
    with app.store() as store:
        konten.factor.operator_reset(store, alex, actor_id=boss, password=secret, disconnect_devices=True)
    _gone(app, everywhere, "signed out everywhere")
    _gone(app, reset, "the operator's reset")
    if not app.blocking:
        return  # the rest blocks the accounts
    # Disconnected stays disconnected: blocking and unblocking brings nothing back.
    for target in (kim, alex):
        with app.store() as store:
            konten.manage.block(store, target, actor_id=boss, password=secret)
        with app.store() as store:
            konten.manage.unblock(store, target, actor_id=boss, password=secret)
    _gone(app, everywhere, "signed out everywhere, blocked and unblocked")
    _gone(app, reset, "the operator's reset, blocked and unblocked")
