"""The second factor through the app's store: a time-based code and recovery codes, sealed, each counting once; the
sign-in that waits for the code; the operator's reset and switch; and what the older version set up keeps working."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import pytest
from konten_contract import password

ISSUER = "nexapp"


def _wrong(code: str) -> str:
    return str((int(code[0]) + 5) % 10) + code[1:]


def _set_up(app: Any, konten: Any, account_id: Any, secret: str) -> tuple[str, list[str]]:
    with app.store() as store:
        enrolment = konten.factor.begin_totp(store, account_id, issuer=ISSUER)
        code = konten.factor.code_at(enrolment.seed, time.time())
        done = konten.factor.confirm_totp(store, account_id, code, password=secret)
    return enrolment.seed, done.codes


def _refused(konten: Any, call: Any, code: str) -> None:
    with pytest.raises(konten.AccountError) as caught:
        call()
    assert caught.value.code == code


def test_a_time_based_code_counts_only_once_a_code_confirmed_it_and_is_kept_sealed(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    with app.store() as store:
        enrolment = konten.factor.begin_totp(store, alex, issuer=ISSUER)
        assert enrolment.uri.startswith(f"otpauth://totp/{ISSUER}:alex?secret={enrolment.seed}&")
        assert store.totp_seed(alex) is None and not konten.factor.has_factor(store, alex)
        code = konten.factor.code_at(enrolment.seed, time.time())
        _refused(konten, lambda: konten.factor.confirm_totp(store, alex, _wrong(code), password=secret), "code_wrong")
        _refused(konten, lambda: konten.factor.confirm_totp(store, alex, code, password=password()), "wrong_password")
        assert store.totp_seed(alex) is None
        done = konten.factor.confirm_totp(store, alex, code, password=secret)
    assert len(done.codes) == 10 and len(set(done.codes)) == 10
    with app.store() as store:
        assert store.totp_seed(alex) == enrolment.seed
        assert store.second_factor(alex) == konten.SECOND_FACTOR_ACTIVE
        account = store.get_account(alex)
        assert konten.common.next_step(store, account) == konten.NEXT_SECOND_FACTOR
        # The code that confirmed it is used up.
        _refused(konten, lambda: konten.factor.check_code(store, alex, code), "code_wrong")
    raw = app.raw_text()
    assert enrolment.seed not in raw and enrolment.seed.lower() not in raw
    assert not any(entry in raw or entry.replace("-", "") in raw for entry in done.codes)


def test_a_half_set_up_authenticator_waits_sealed_in_the_store_across_a_restart(
    app: Any, konten: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decided while building (0.3.3): between the QR code and the first code the seed waits in the database,
    sealed, not only in memory; a restart in between loses nothing. It is no factor until a code confirmed it, and it
    waits ten minutes."""
    secret = password()
    alex = app.seed("alex", password=secret)
    kim = app.seed("kim", password=secret)
    with app.store() as store:
        enrolment = konten.factor.begin_totp(store, alex, issuer=ISSUER)
        late = konten.factor.begin_totp(store, kim, issuer=ISSUER)
    konten.factor.forget()  # the restart: nothing is left in memory
    raw = app.raw_text()
    assert enrolment.seed not in raw and enrolment.seed.lower() not in raw
    with app.store() as store:
        assert store.totp_seed(alex) is None and not konten.factor.has_factor(store, alex)
        assert store.pending_totp(alex)[0] == enrolment.seed
        code = konten.factor.code_at(enrolment.seed, time.time())
        assert konten.factor.confirm_totp(store, alex, code, password=secret).codes
    with app.store() as store:
        assert store.totp_seed(alex) == enrolment.seed and store.pending_totp(alex) is None
    now = konten.common.utcnow()
    monkeypatch.setattr(konten.common, "utcnow", lambda: now + timedelta(minutes=11))
    with app.store() as store:
        code = konten.factor.code_at(late.seed, time.time())
        _refused(konten, lambda: konten.factor.confirm_totp(store, kim, code, password=secret), "enrolment_expired")


def test_setting_up_shows_the_same_qr_code_again_while_it_waits(
    app: Any, konten: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decided while building (0.3.4): one way for every app to set up an authenticator, through the module; while it
    waits for its first code the page can ask for the QR code again (``pending_setup``), also after a restart, and
    gets the same seed and address. The factor set up before keeps counting until a code confirms the new one."""
    secret = password()
    alex = app.seed("alex", password=secret)
    kim = app.seed("kim", password=secret)
    old_seed, _ = _set_up(app, konten, alex, secret)
    with app.store() as store:
        assert konten.factor.pending_setup(store, alex, issuer=ISSUER) is None
        assert konten.factor.pending_setup(store, kim, issuer=ISSUER) is None
        enrolment = konten.factor.begin_totp(store, alex, issuer=ISSUER)
    assert enrolment.expires_at is not None
    konten.factor.forget()  # a restart between the QR code and the first code
    with app.store() as store:
        again = konten.factor.pending_setup(store, alex, issuer=ISSUER)
        assert again is not None and (again.seed, again.uri) == (enrolment.seed, enrolment.uri)
        assert again.uri.startswith(f"otpauth://totp/{ISSUER}:alex?secret={enrolment.seed}&")
        assert abs((again.expires_at - enrolment.expires_at).total_seconds()) < 2
        # Asking again restarts no clock and makes nothing a factor; the old authenticator still counts.
        assert store.totp_seed(alex) == old_seed
        assert konten.factor.check_code(store, alex, konten.factor.code_at(old_seed, time.time() + 30)) == "totp"
    with app.store() as store:
        code = konten.factor.code_at(enrolment.seed, time.time())
        konten.factor.confirm_totp(store, alex, code, password=secret)
    with app.store() as store:
        assert konten.factor.pending_setup(store, alex, issuer=ISSUER) is None
        assert store.totp_seed(alex) == enrolment.seed
        late = konten.factor.begin_totp(store, kim, issuer=ISSUER)
    now = konten.common.utcnow()
    monkeypatch.setattr(konten.common, "utcnow", lambda: now + timedelta(minutes=11))
    with app.store() as store:
        assert late.seed and konten.factor.pending_setup(store, kim, issuer=ISSUER) is None


def test_a_setup_started_over_an_authenticator_of_the_older_version_keeps_it_counting(app: Any, konten: Any) -> None:
    """Moving an app's own setup routes onto the module (0.3.4): the authenticators and codes the older version set
    up keep counting while a new one waits, and after it was given up."""
    legacy = app.legacy()
    username, seed, codes = legacy.factors[0]
    with app.store() as store:
        account = store.find_by_username(username)[0]
        konten.factor.begin_totp(store, account.id, issuer=ISSUER)
        assert konten.factor.pending_setup(store, account.id, issuer=ISSUER) is not None
        assert konten.factor.check_code(store, account.id, konten.factor.code_at(seed, time.time())) == "totp"
        if codes:
            assert konten.factor.check_code(store, account.id, codes[0]) == "recovery"
        assert konten.factor.has_factor(store, account.id)


def test_the_emergency_hammer_switches_the_second_factor_off_for_everybody(
    app: Any, konten: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decided 25.11.2026 (0.3.3): ``<APP>_SECOND_FACTOR_OFF`` beats every factor and "required of everybody";
    nothing is deleted, and without it everything counts again."""
    secret = password()
    alex = app.seed("alex", password=secret)
    kim = app.seed("kim", password=secret)
    _set_up(app, konten, alex, secret)
    app.switch("factor_required", True)
    with app.store() as store:
        assert konten.common.next_step(store, store.get_account(alex)) == konten.NEXT_SECOND_FACTOR
        assert konten.common.next_step(store, store.get_account(kim)) == konten.NEXT_SECOND_FACTOR_SETUP
    assert konten.factor.switched_off() is False
    app_name = konten.current().app_name
    assert konten.current().second_factor_off_env == app_name.upper().replace("-", "_") + "_SECOND_FACTOR_OFF"
    monkeypatch.setenv(konten.current().second_factor_off_env, "1")
    assert konten.factor.switched_off() is True
    with app.store() as store:
        for account_id in (alex, kim):
            assert konten.common.next_step(store, store.get_account(account_id)) == konten.NEXT_SESSION
            assert konten.factor.state(store, account_id) == konten.SECOND_FACTOR_NONE
        assert store.totp_seed(alex)
    monkeypatch.delenv(konten.current().second_factor_off_env)
    with app.store() as store:
        assert konten.common.next_step(store, store.get_account(alex)) == konten.NEXT_SECOND_FACTOR


def test_a_code_counts_once_also_for_two_requests_at_the_same_moment(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    seed, _ = _set_up(app, konten, alex, secret)
    later = konten.factor.code_at(seed, time.time() + konten.factor.STEP_SECONDS)
    with app.store() as store:
        assert konten.factor.check_code(store, alex, later) == "totp"
    with app.store() as store:
        _refused(konten, lambda: konten.factor.check_code(store, alex, later), "code_wrong")
    step = int(time.time()) // konten.factor.STEP_SECONDS + 10
    with app.store() as first, app.store() as second:
        assert first.claim_step(alex, step) is True
        first.commit()
        assert second.claim_step(alex, step) is False
        assert second.claim_step(alex, step + 1) is True
        second.commit()


def test_a_recovery_code_counts_once_in_any_spelling_and_new_ones_replace_the_old(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    _, codes = _set_up(app, konten, alex, secret)
    assert all(len(code) == 11 and code[5] == "-" for code in codes)
    with app.store() as store:
        assert konten.factor.check_code(store, alex, codes[0]) == "recovery"
    with app.store() as store:
        _refused(konten, lambda: konten.factor.check_code(store, alex, codes[0]), "code_wrong")
        assert konten.factor.check_code(store, alex, " " + codes[1].upper().replace("-", " ") + " ") == "recovery"
        assert len(store.recovery_hashes(alex)) == 8
    with app.store() as first, app.store() as second:
        stored = first.recovery_hashes(alex)[0]
        assert stored in second.recovery_hashes(alex)
        assert first.claim_recovery(alex, stored) is True
        first.commit()
        assert second.claim_recovery(alex, stored) is False
    with app.store() as store:
        fresh = konten.factor.new_codes(store, alex, password=secret)
    assert len(fresh) == 10 and not set(fresh) & set(codes)
    with app.store() as store:
        _refused(konten, lambda: konten.factor.check_code(store, alex, codes[2]), "code_wrong")
        assert konten.factor.check_code(store, alex, fresh[0]) == "recovery"


def test_the_owner_takes_the_code_away_unless_the_operator_requires_a_second_factor(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    _set_up(app, konten, alex, secret)
    app.switch("factor_required", True)
    with app.store() as store:
        _refused(konten, lambda: konten.factor.disable_totp(store, alex, password=secret), "factor_required")
        assert store.totp_seed(alex)
    app.switch("factor_required", False)
    with app.store() as store:
        _refused(konten, lambda: konten.factor.disable_totp(store, alex, password=password()), "wrong_password")
        konten.factor.disable_totp(store, alex, password=secret)
    with app.store() as store:
        assert store.totp_seed(alex) is None and store.recovery_hashes(alex) == []
        assert store.second_factor(alex) == konten.SECOND_FACTOR_NONE


def test_nobody_needs_a_second_factor_until_the_operator_switches_it_on(app: Any, konten: Any) -> None:
    plain = app.seed("plain", password=password())
    with app.store() as store:
        assert store.factor_required() is False
        assert konten.factor.state(store, plain) == konten.SECOND_FACTOR_NONE
        assert konten.common.next_step(store, store.get_account(plain)) == konten.NEXT_SESSION
    app.switch("factor_required", True)
    with app.store() as store:
        assert store.factor_required() is True
        assert konten.factor.state(store, plain) == konten.SECOND_FACTOR_REQUIRED
        assert store.second_factor(plain) == konten.SECOND_FACTOR_REQUIRED
        assert konten.common.next_step(store, store.get_account(plain)) == konten.NEXT_SECOND_FACTOR_SETUP


def test_the_operator_resets_every_factor_of_another_account_and_its_sessions_end(
    app: Any, konten: Any, operator: tuple[Any, str]
) -> None:
    boss, boss_secret = operator
    secret = password()
    alex = app.seed("alex", email="alex@example.com", password=secret)
    _set_up(app, konten, alex, secret)
    session = app.open_session(alex)
    with app.store() as store:
        _refused(
            konten,
            lambda: konten.factor.operator_reset(store, alex, actor_id=boss, password=password()),
            "wrong_password",
        )
        _refused(
            konten,
            lambda: konten.factor.operator_reset(store, boss, actor_id=boss, password=boss_secret),
            "use_account_page",
        )
        with pytest.raises(konten.AccountError):
            konten.factor.operator_reset(store, boss, actor_id=alex, password=secret)
    assert app.session_alive(session)
    with app.store() as store:
        mail = konten.factor.operator_reset(store, alex, actor_id=boss, password=boss_secret)
    assert mail is not None and mail.kind == konten.MAIL_FACTOR_RESET and mail.to == "alex@example.com"
    assert not app.session_alive(session)
    with app.store() as store:
        assert not konten.factor.has_factor(store, alex) and store.recovery_hashes(alex) == []


def test_the_waiting_sign_in_takes_the_code_and_ends_after_five_wrong_ones(app: Any, konten: Any) -> None:
    secret = password()
    alex = app.seed("alex", password=secret)
    seed, _ = _set_up(app, konten, alex, secret)
    token = konten.factor.start_waiting(alex, remember=False)
    assert konten.factor.waiting_account(token) == alex and konten.factor.waiting_account("other") is None
    wrong = _wrong(konten.factor.code_at(seed, time.time() + 30))
    for _ in range(konten.factor.MAX_ATTEMPTS):
        with app.store() as store:
            _refused(konten, lambda: konten.factor.finish_waiting(store, token, wrong), "code_wrong")
    with app.store() as store:
        right = konten.factor.code_at(seed, time.time() + 30)
        _refused(konten, lambda: konten.factor.finish_waiting(store, token, right), "sign_in_expired")
    token = konten.factor.start_waiting(alex, remember=False, provider_checked=True)
    with app.store() as store:
        waited = konten.factor.finish_waiting(store, token, right)
    assert (waited.account_id, waited.remember, waited.provider_checked, waited.method) == (alex, False, True, "totp")
    assert konten.factor.waiting_account(token) is None


def test_a_blocked_account_gets_no_further_with_its_code(app: Any, konten: Any) -> None:
    if not app.blocking:
        return  # the app blocks no accounts (StandardAdapter.blocking)
    gone = app.seed("gone", password=password(), blocked=True)
    seed = konten.factor.new_seed()
    with app.store() as store:
        store.set_totp(gone, seed)
        store.commit()
    token = konten.factor.start_waiting(gone)
    with app.store() as store:
        code = konten.factor.code_at(seed, time.time())
        _refused(konten, lambda: konten.factor.finish_waiting(store, token, code), "account_blocked")


def test_the_authenticator_apps_and_codes_of_the_older_version_keep_working(app: Any, konten: Any) -> None:
    legacy = app.legacy()
    assert legacy.factors, "Legacy.factors: the second factors the older version set up"
    for username, seed, codes in legacy.factors:
        with app.store() as store:
            account = store.find_by_username(username)[0]
            assert konten.factor.has_factor(store, account.id)
            assert store.second_factor(account.id) == konten.SECOND_FACTOR_ACTIVE
            assert konten.factor.check_code(store, account.id, konten.factor.code_at(seed, time.time())) == "totp"
        for code in codes:
            with app.store() as store:
                assert konten.factor.check_code(store, account.id, code) == "recovery"
            with app.store() as store:
                _refused(konten, lambda: konten.factor.check_code(store, account.id, code), "code_wrong")  # noqa: B023


def test_the_operators_reset_disconnects_paired_devices_unless_asked_not_to(
    app: Any, konten: Any, operator: tuple[Any, str]
) -> None:
    boss, boss_secret = operator
    alex = app.seed("alex", password=password())
    kim = app.seed("kim", password=password())
    for target, disconnect in ((alex, True), (kim, False)):
        device = app.open_session(target, "device")
        with app.store() as store:
            phone = konten.sessions.start(store, target, cookie_name="s", secure=True, kind=konten.model2.KIND_DEVICE)
            store.commit()
        with app.store() as store:
            konten.factor.operator_reset(
                store, target, actor_id=boss, password=boss_secret, disconnect_devices=disconnect
            )
        with app.store() as store:
            alive = konten.sessions.current(store, phone.token) is not None
        assert alive is (not disconnect) and app.session_alive(device) is (not disconnect)


def test_a_new_password_ends_the_waiting_sign_ins(app: Any, konten: Any) -> None:
    alex = app.seed("alex", email="alex@example.com", password=password())
    waiting = konten.factor.start_waiting(alex)
    with app.store() as store:
        token = konten.resets.forgot(store, "alex").token
        konten.resets.use_reset(store, token, password())
    assert konten.factor.waiting_account(waiting) is None


def test_an_account_without_a_password_replaces_its_authenticator_only_after_a_fresh_sign_in(
    app: Any, konten: Any
) -> None:
    viaprovider = app.seed("viaprovider")
    with app.store() as store:
        store.set_totp(viaprovider, konten.factor.new_seed())
        store.commit()
    with app.store() as store:
        enrolment = konten.factor.begin_totp(store, viaprovider, issuer=ISSUER)
        code = konten.factor.code_at(enrolment.seed, time.time())
        _refused(konten, lambda: konten.factor.confirm_totp(store, viaprovider, code), "fresh_sign_in_needed")
        konten.factor.confirm_totp(store, viaprovider, code, actor_confirmed=True)
    with app.store() as store:
        assert store.totp_seed(viaprovider) == enrolment.seed


def test_a_factor_set_up_at_sign_in_shows_its_codes_before_the_session(app: Any, konten: Any) -> None:
    """The operator asks a second factor of everybody: the session that can only set it up gets the ten codes and
    ``show_codes``; then a full session."""
    alex = app.seed("alex", password=password())
    app.switch("factor_required", True)
    with app.store() as store:
        assert konten.common.next_step(store, store.get_account(alex)) == konten.NEXT_SECOND_FACTOR_SETUP
        started = konten.sessions.start(store, alex, cookie_name="s", secure=True, stage=konten.model2.STAGE_SETUP)
        store.commit()
    with app.store() as store:
        enrolment = konten.factor.begin_totp(store, alex, issuer=ISSUER)
        code = konten.factor.code_at(enrolment.seed, time.time())
        done = konten.factor.confirm_totp(store, alex, code, actor_confirmed=True)
    assert done.next == konten.NEXT_SHOW_CODES and len(done.codes) == konten.factor.RECOVERY_CODES
    with app.store() as store:
        konten.sessions.finish_setup(store, started.session)
        store.commit()
    with app.store() as store:
        assert konten.sessions.current(store, started.token).stage == konten.model2.STAGE_FULL
        fresh = konten.factor.new_codes(store, alex, actor_confirmed=True)
    assert len(fresh) == konten.factor.RECOVERY_CODES


def test_a_fresh_sign_in_at_the_provider_is_at_most_five_minutes_old(konten: Any) -> None:
    now = konten.common.utcnow()
    assert konten.common.FRESH_SIGN_IN_MINUTES == 5
    assert konten.common.fresh_sign_in(now - timedelta(minutes=4, seconds=59), now) is True
    assert konten.common.fresh_sign_in(now - timedelta(minutes=5, seconds=1), now) is False
    assert konten.common.fresh_sign_in(now + timedelta(minutes=1), now) is False
    assert konten.common.fresh_sign_in(None, now) is False


def test_switching_the_authenticator_off_goes_through_the_module_and_means_off(app: Any, konten: Any) -> None:
    """Decided while building (0.3.5): every app switches the authenticator off with ``factor.disable_totp`` and
    keeps no route of its own for it. Confirmed with the password (an account through a provider only: a fresh
    sign-in there), counted at the brake, the codes go with it, a setup that still waits ends too, and the next
    sign-in asks no code."""
    secret = password()
    alex = app.seed("alex", password=secret)
    _set_up(app, konten, alex, secret)
    with app.store() as store:
        konten.factor.begin_totp(store, alex, issuer=ISSUER)
        assert konten.factor.pending_setup(store, alex, issuer=ISSUER) is not None
        konten.factor.disable_totp(store, alex, password=secret)
    with app.store() as store:
        assert store.totp_seed(alex) is None and store.recovery_hashes(alex) == []
        assert konten.factor.pending_setup(store, alex, issuer=ISSUER) is None
        assert konten.common.next_step(store, store.get_account(alex)) == konten.NEXT_SESSION
    kim = app.seed("kim")
    with app.store() as store:
        enrolment = konten.factor.begin_totp(store, kim, issuer=ISSUER)
        code = konten.factor.code_at(enrolment.seed, time.time())
        konten.factor.confirm_totp(store, kim, code, actor_confirmed=True)
    with app.store() as store:
        _refused(konten, lambda: konten.factor.disable_totp(store, kim), "fresh_sign_in_needed")
        konten.factor.disable_totp(store, kim, actor_confirmed=True)
    with app.store() as store:
        assert store.totp_seed(kim) is None
    bob = app.seed("bob", password=secret)
    _set_up(app, konten, bob, secret)
    with app.store() as store:
        for _ in range(konten.brake.FREE_OTHER + 1):
            _refused(konten, lambda: konten.factor.disable_totp(store, bob, password=password()), "wrong_password")
        _refused(konten, lambda: konten.factor.disable_totp(store, bob, password=secret), "too_many_attempts")
        assert store.totp_seed(bob)
