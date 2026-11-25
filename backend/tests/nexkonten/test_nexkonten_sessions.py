"""Sessions through the app's store: found by the cookie and kept as a hash, "stay signed in", the session that can
only set up a factor, the list with a sign-out each, "sign out everywhere", and the mark of a known browser."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from konten_contract import password

COOKIE = "nexapp_session"


def _start(app: Any, konten: Any, account_id: Any, **values: Any) -> Any:
    with app.store() as store:
        started = konten.sessions.start(store, account_id, cookie_name=COOKIE, secure=True, **values)
        store.commit()
    return started


def _current(app: Any, konten: Any, token: str) -> Any:
    with app.store() as store:
        found = konten.sessions.current(store, token)
        store.commit()
    return found


def _near(moment: datetime, expected: datetime) -> bool:
    return abs((moment - expected).total_seconds()) < 120


def test_a_session_is_found_by_its_cookie_and_only_its_hash_is_kept(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    started = _start(app, konten, alex, label="Firefox on Linux", address="192.0.2.7")
    found = _current(app, konten, started.token)
    assert found is not None and found.uid == started.session.uid and found.account_id == alex
    assert (found.label, found.address, found.stage) == ("Firefox on Linux", "192.0.2.7", konten.model2.STAGE_FULL)
    assert _current(app, konten, started.token + "x") is None and _current(app, konten, "") is None
    assert started.token not in app.raw_text()
    cookie = started.cookie
    assert (cookie.name, cookie.value, cookie.http_only, cookie.secure, cookie.same_site, cookie.path) == (
        COOKIE,
        started.token,
        True,
        True,
        "lax",
        "/",
    )


def test_stay_signed_in_lasts_30_days_and_without_it_the_browser_session_12_hours(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    now = datetime.now(UTC)
    kept = _start(app, konten, alex)
    short = _start(app, konten, alex, remember=False)
    assert kept.cookie.max_age == konten.sessions.REMEMBER_COOKIE_DAYS * 86400 and short.cookie.max_age is None
    with app.store() as store:
        found_kept = store.session_by_hash(konten.sessions.hash_token(kept.token))
        found_short = store.session_by_hash(konten.sessions.hash_token(short.token))
    assert found_kept.remember is True and _near(found_kept.expires_at, now + timedelta(days=30))
    assert found_short.remember is False and _near(found_short.expires_at, now + timedelta(hours=12))


def test_a_remembered_session_slides_and_one_that_ran_out_is_gone(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    kept = _start(app, konten, alex)
    short = _start(app, konten, alex, remember=False)
    now = datetime.now(UTC)
    with app.store() as store:
        for started in (kept, short):
            store.touch_session(started.session.uid, now - timedelta(hours=1), now + timedelta(days=1))
        store.commit()
    assert _current(app, konten, kept.token) is not None and _current(app, konten, short.token) is not None
    with app.store() as store:
        slid = store.session_by_hash(konten.sessions.hash_token(kept.token))
        stayed = store.session_by_hash(konten.sessions.hash_token(short.token))
    assert _near(slid.expires_at, now + timedelta(days=30)) and _near(slid.last_seen_at, now)
    assert _near(stayed.expires_at, now + timedelta(days=1))
    with app.store() as store:
        store.touch_session(kept.session.uid, now - timedelta(days=2), now - timedelta(seconds=1))
        store.commit()
    assert _current(app, konten, kept.token) is None


def test_a_session_that_can_only_set_up_a_factor_lasts_15_minutes_then_becomes_full(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    now = datetime.now(UTC)
    started = _start(app, konten, alex, stage=konten.model2.STAGE_SETUP)
    assert started.cookie.max_age is None
    found = _current(app, konten, started.token)
    assert found.stage == konten.model2.STAGE_SETUP and _near(found.expires_at, now + timedelta(minutes=15))
    with app.store() as store:
        konten.sessions.finish_setup(store, found)
        store.commit()
    full = _current(app, konten, started.token)
    assert full.stage == konten.model2.STAGE_FULL and _near(full.expires_at, now + timedelta(days=30))


def test_the_list_shows_browsers_and_devices_and_each_signs_out_alone(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    kim = app.seed("kim", password=password())
    here = _start(app, konten, alex, label="Firefox")
    phone = _start(app, konten, alex, kind=konten.model2.KIND_DEVICE, label="iPhone")
    _start(app, konten, alex, kind=konten.model2.KIND_WAITING)
    with app.store() as store:
        listed = konten.sessions.listing(store, alex, here.session.uid)
    assert {entry["uid"] for entry in listed} == {here.session.uid, phone.session.uid}
    by_uid = {entry["uid"]: entry for entry in listed}
    assert by_uid[here.session.uid]["current"] is True and by_uid[here.session.uid]["device"] is False
    assert by_uid[phone.session.uid]["current"] is False and by_uid[phone.session.uid]["device"] is True
    with app.store() as store:
        assert konten.sessions.sign_out(store, kim, phone.session.uid) is False
        assert konten.sessions.sign_out(store, alex, phone.session.uid) is True
        store.commit()
    assert _current(app, konten, phone.token) is None and _current(app, konten, here.token) is not None


def test_sign_out_everywhere_keeps_this_browser_the_programs_and_other_accounts(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    kim = app.seed("kim", password=password())
    here = _start(app, konten, alex)
    other = _start(app, konten, alex, remember=False)
    phone = _start(app, konten, alex, kind=konten.model2.KIND_DEVICE)
    older = app.open_session(alex, "browser")
    program = app.open_session(alex, "program")
    kims = _start(app, konten, kim)
    with app.store() as store:
        assert konten.sessions.sign_out_everywhere(store, alex, keep_uid=here.session.uid) >= 3
        store.commit()
    assert _current(app, konten, here.token) is not None and _current(app, konten, kims.token) is not None
    assert _current(app, konten, other.token) is None and _current(app, konten, phone.token) is None
    assert not app.session_alive(older)
    if program is not None:
        assert app.session_alive(program)
        with app.store() as store:
            assert store.list_access(alex)


def test_a_new_password_ends_the_browsers_and_keeps_the_devices(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    browser = _start(app, konten, alex)
    phone = _start(app, konten, alex, kind=konten.model2.KIND_DEVICE)
    with app.store() as store:
        store.end_sessions(alex)
        store.commit()
    assert _current(app, konten, browser.token) is None and _current(app, konten, phone.token) is not None


def test_a_known_browser_mark_names_no_account_and_a_new_device_key_voids_it(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    kim = app.seed("kim", password=password())
    secret = secrets.token_bytes(32)
    with app.store() as store:
        key = store.device_key(alex)
        assert key and store.device_key(alex) == key and store.device_key(kim) != key
        store.commit()
    cookie = konten.sessions.add_mark("", konten.sessions.mark(secret, key))
    assert "alex" not in cookie and str(alex) not in re.split(r"[.~]", cookie) and cookie.count(".") == 1
    with app.store() as store:
        assert konten.sessions.is_known(cookie, secret, store.device_key(alex)) is True
        assert konten.sessions.is_known(cookie, secret, store.device_key(kim)) is False
        assert konten.sessions.is_known(cookie, secrets.token_bytes(32), store.device_key(alex)) is False
        store.renew_device_key(alex)
        store.commit()
    with app.store() as store:
        assert store.device_key(alex) != key
        assert konten.sessions.is_known(cookie, secret, store.device_key(alex)) is False


def test_a_waiting_sign_in_is_never_a_session_and_every_session_notes_its_last_use(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    waiting = _start(app, konten, alex, kind=konten.model2.KIND_WAITING)
    assert _current(app, konten, waiting.token) is None
    short = _start(app, konten, alex, remember=False)
    now = datetime.now(UTC)
    with app.store() as store:
        store.touch_session(short.session.uid, now - timedelta(hours=1), now + timedelta(hours=2))
        store.commit()
    assert _current(app, konten, short.token) is not None
    with app.store() as store:
        seen = store.session_by_hash(konten.sessions.hash_token(short.token))
    assert _near(seen.last_seen_at, now) and _near(seen.expires_at, now + timedelta(hours=2))


AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0 "
    "Security notice: confirm at https://evil.example.org/verify"
)


def test_the_list_names_the_browser_never_its_raw_text_and_devices_keep_their_name(app: Any, konten: Any) -> None:
    alex = app.seed("alex", password=password())
    here = _start(app, konten, alex, label=AGENT)
    _start(app, konten, alex, kind=konten.model2.KIND_DEVICE, label="Phone of Alex\n")
    with app.store() as store:
        listed = {
            entry["uid"]: entry for entry in konten.sessions.listing(store, alex, here.session.uid, language="de")
        }
        access = store.list_access(alex)
    assert listed[here.session.uid]["label"] == "Firefox auf Linux"
    assert sorted(entry["label"] for entry in listed.values()) == ["Firefox auf Linux", "Phone of Alex"]
    for text in [str(entry) for entry in listed.values()] + [repr(entry) for entry in access]:
        assert "Mozilla/" not in text and "evil" not in text
