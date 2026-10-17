"""The second factor (taken over from nextrmnl): RFC vectors, enrolment, the two-step sign-in, replay, recovery codes,
limits, the lockout that the password step does not undo, the operator's reset, the required mode, MCP keys. Nothing
secret reaches the log."""

from __future__ import annotations

import logging
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import SIGN_IN_OIDC, Account
from app.security import MAX_FAILURES, SESSION_COOKIE, brake, start_session
from app.services import totp

from .conftest import PASSWORD, make_account, sign_in

#: RFC 6238, appendix B: the ASCII seed "12345678901234567890", HMAC-SHA1, eight digits; the last six taken.
RFC_SEED = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
RFC_VECTORS = {59: "287082", 1111111109: "081804", 1234567890: "005924", 2000000000: "279037"}


class Clock:
    """The clock the second factor sees. Advancing it is how a test reaches the next code; the pending store keeps
    its own monotonic clock and is not touched."""

    def __init__(self) -> None:
        # Standing still, in the middle of a time step: a test that took a code and checks it a moment later never
        # crosses into the next step by chance (it did, under load, when this clock ran with the real one).
        step = totp.STEP_SECONDS
        self.start = (time.time() // step) * step + step / 2
        self.offset = 0.0

    def time(self) -> float:
        return self.start + self.offset

    def monotonic(self) -> float:
        return time.monotonic()

    def advance(self, seconds: float) -> None:
        self.offset += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(totp, "time", fake)
    return fake


def person(name: str) -> TestClient:
    client = TestClient(app, base_url="http://testserver", headers={"X-Nexpaper-Client": f"tab-{name:0<8}"})
    sign_in(client, make_account(name))
    return client


def current_code(secret: str) -> str:
    return totp.code_at(secret, totp.time.time())


def fresh_code(secret: str, clock: Clock) -> str:
    """The code of the next time step: the one used before counts as spent."""
    clock.advance(totp.STEP_SECONDS)
    return current_code(secret)


def enrol(client: TestClient) -> tuple[str, list[str]]:
    """Enrols the signed-in account; returns the seed and the recovery codes."""
    begun = client.post("/api/v1/auth/totp/begin")
    assert begun.status_code == 200, begun.text
    secret = begun.json()["secret"]
    assert begun.json()["uri"].startswith("otpauth://totp/nexpaper:")
    # Shown as a data: image, and a browser draws an SVG there only with its namespace.
    assert begun.json()["qr_svg"].startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    confirmed = client.post("/api/v1/auth/totp/confirm", json={"code": current_code(secret), "password": PASSWORD})
    assert confirmed.status_code == 200, confirmed.text
    codes = confirmed.json()["recovery_codes"]
    assert len(codes) == totp.RECOVERY_CODES and confirmed.json()["account"]["two_factor"] is True
    return secret, codes


def password_step(client: TestClient, name: str = "tester") -> None:
    response = client.post("/api/v1/auth/login", json={"name": name, "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json() ["second_factor"] is True
    cookie = response.headers.get("set-cookie", "")
    assert "nexpaper_2fa=" in cookie and "HttpOnly" in cookie and "Path=/api/v1/auth" in cookie
    assert f"{SESSION_COOKIE}=" not in cookie


def code_step(client: TestClient, code: str):
    return client.post("/api/v1/auth/login/totp", json={"code": code})


def sign_out(client: TestClient) -> None:
    client.post("/api/v1/auth/logout")
    client.cookies.clear()


# --- The algorithm ----------------------------------------------------------------------------------------------------


def test_codes_match_the_rfc_vectors() -> None:
    for moment, expected in RFC_VECTORS.items():
        assert totp.code_at(RFC_SEED, moment) == expected


def test_a_code_is_accepted_in_the_window_and_only_after_the_last_used_step() -> None:
    now = 1234567890
    step = now // totp.STEP_SECONDS
    assert totp.verify_code(RFC_SEED, "005924", now=now) == step
    # A step earlier and a step later still pass; two steps do not.
    assert totp.verify_code(RFC_SEED, totp.code_at(RFC_SEED, now - 30), now=now) == step - 1
    assert totp.verify_code(RFC_SEED, totp.code_at(RFC_SEED, now + 30), now=now) == step + 1
    assert totp.verify_code(RFC_SEED, totp.code_at(RFC_SEED, now + 60), now=now) is None
    assert totp.verify_code(RFC_SEED, totp.code_at(RFC_SEED, now - 60), now=now) is None
    # Replay: at or before the last accepted step is refused.
    assert totp.verify_code(RFC_SEED, "005924", after_step=step, now=now) is None
    assert totp.verify_code(RFC_SEED, "005924", after_step=step - 1, now=now) == step
    assert totp.verify_code(RFC_SEED, "00592", now=now) is None
    assert totp.verify_code(RFC_SEED, "abcdef", now=now) is None
    # An empty seed verifies nothing, not even the code everybody could work out from it.
    with pytest.raises(totp.SeedUnreadable):
        totp.verify_code("", "123456", now=now)


def test_recovery_codes_are_typed_from_paper() -> None:
    codes = totp.generate_recovery_codes()
    assert len(codes) == 8 and len(set(codes)) == 8
    for code in codes:
        head, tail = code.split("-")
        assert len(head) == 5 and len(tail) == 5
        assert not set(code.replace("-", "")) & set("0o1liO")
    stored = totp.recovery_hashes(codes)
    assert codes[0] not in stored
    remaining = totp.use_recovery(stored, codes[2].upper().replace("-", " "))
    assert remaining is not None and len(totp.load_recovery(remaining)) == 7
    assert totp.use_recovery(remaining, codes[2]) is None


# --- Enrolment --------------------------------------------------------------------------------------------------------


def test_enrolment_needs_the_password_and_a_matching_code(client: TestClient, operator: Account, clock: Clock) -> None:
    secret = client.post("/api/v1/auth/totp/begin").json()["secret"]
    wrong_password = client.post("/api/v1/auth/totp/confirm", json={"code": current_code(secret), "password": "not it"})
    assert wrong_password.status_code == 401 and wrong_password.json()["detail"]["code"] == "wrong_password"
    wrong_code = client.post("/api/v1/auth/totp/confirm", json={"code": "000000", "password": PASSWORD})
    assert wrong_code.status_code == 422 and wrong_code.json()["detail"]["code"] == "totp_code_wrong"
    assert client.get("/api/v1/auth/me").json()["two_factor"] is False

    confirmed = client.post("/api/v1/auth/totp/confirm", json={"code": current_code(secret), "password": PASSWORD})
    assert confirmed.status_code == 200, confirmed.text
    me = client.get("/api/v1/auth/me").json()
    assert me["two_factor"] is True and me["two_factor_recovery_left"] == 8
    # On already: a second enrolment is refused until it is turned off.
    assert client.post("/api/v1/auth/totp/begin").status_code == 409
    # The seed is stored sealed, not in the clear.
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None and row.totp_secret_enc and secret not in row.totp_secret_enc
        assert totp.open_seed(row.totp_secret_enc) == secret


def test_an_enrolment_runs_out(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = client.post("/api/v1/auth/totp/begin").json()["secret"]
    monkeypatch.setattr(totp, "ENROLMENT_SECONDS", 0)
    client.post("/api/v1/auth/totp/begin")
    late = client.post("/api/v1/auth/totp/confirm", json={"code": current_code(secret), "password": PASSWORD})
    assert late.status_code == 410 and late.json()["detail"]["code"] == "totp_enrolment_expired"


def test_nothing_secret_reaches_the_log(
    client: TestClient, operator: Account, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        secret, codes = enrol(client)
        sign_out(client)
        password_step(client)
        assert code_step(client, fresh_code(secret, clock)).status_code == 200
    assert secret not in caplog.text
    for code in codes:
        assert code not in caplog.text and code.replace("-", "") not in caplog.text
    assert "Second factor turned on name=tester" in caplog.text


# --- Signing in -------------------------------------------------------------------------------------------------------


def test_sign_in_takes_two_steps(client: TestClient, operator: Account, clock: Clock) -> None:
    secret, _codes = enrol(client)
    sign_out(client)
    password_step(client)
    # The password alone signs nobody in.
    assert client.get("/api/v1/auth/me").status_code == 401
    wrong = code_step(client, "000000")
    assert wrong.status_code == 401 and wrong.json()["detail"]["code"] == "totp_code_wrong"
    code = fresh_code(secret, clock)
    right = code_step(client, code)
    assert right.status_code == 200, right.text
    assert right.json()["name"] == "tester"
    assert client.get("/api/v1/auth/me").status_code == 200
    # The pending cookie is gone; the code step cannot be repeated.
    assert code_step(client, code).status_code == 401


def test_the_enrolment_code_is_spent_and_a_code_works_once(client: TestClient, operator: Account, clock: Clock) -> None:
    secret, _codes = enrol(client)
    sign_out(client)
    password_step(client)
    # The code that confirmed the enrolment belongs to a step used already.
    spent = code_step(client, current_code(secret))
    assert spent.status_code == 401 and spent.json()["detail"]["code"] == "totp_code_wrong"
    code = fresh_code(secret, clock)
    assert code_step(client, code).status_code == 200
    sign_out(client)
    password_step(client)
    replayed = code_step(client, code)
    assert replayed.status_code == 401 and replayed.json()["detail"]["code"] == "totp_code_wrong"
    assert code_step(client, fresh_code(secret, clock)).status_code == 200


def test_five_wrong_codes_end_the_pending_sign_in(client: TestClient, operator: Account, clock: Clock) -> None:
    secret, _codes = enrol(client)
    sign_out(client)
    password_step(client)
    for _ in range(totp.MAX_ATTEMPTS - 1):
        assert code_step(client, "000000").json()["detail"]["code"] == "totp_code_wrong"
    last = code_step(client, "000000")
    assert last.status_code == 401 and last.json()["detail"]["code"] == "second_factor_expired"
    # Even the right code is refused now: the password has to be given again.
    code = fresh_code(secret, clock)
    again = code_step(client, code)
    assert again.status_code == 401 and again.json()["detail"]["code"] == "second_factor_expired"
    # Five wrong codes are five failures: the address rests and the account is locked for a quarter of an hour.
    # Both lifted here to see the rest.
    brake.forget()
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None and row.locked_until is not None
        row.locked_until = None
        db.commit()
    password_step(client)
    assert code_step(client, code).status_code == 200


def test_the_brake_slows_a_guessing_sender(client: TestClient, operator: Account, clock: Clock) -> None:
    enrol(client)
    sign_out(client)
    password_step(client)
    for _ in range(totp.MAX_ATTEMPTS - 1):
        code_step(client, "000000")
    # Five failures from one address, of any kind: the fifth wrong code, then even the password waits.
    code_step(client, "000000")
    braked = client.post("/api/v1/auth/login", json={"name": "tester", "password": PASSWORD})
    assert braked.status_code == 429 and braked.json()["detail"]["code"] == "too_many_attempts"
    assert braked.headers["retry-after"] == "900"


def test_knowing_the_password_is_no_way_around_the_lockout(client: TestClient, operator: Account, clock: Clock) -> None:
    """A password step before every few wrong codes must not reset the count: the account locks after as many wrong
    codes as it would after wrong passwords, and then even the right code is refused."""
    secret, _codes = enrol(client)
    sign_out(client)
    wrong = 0
    while wrong < MAX_FAILURES:
        brake.forget()  # a guesser with many addresses: the brake per sender does not hold them
        password_step(client)
        for _ in range(min(totp.MAX_ATTEMPTS - 1, MAX_FAILURES - wrong)):
            code_step(client, "000000")
            wrong += 1
    brake.forget()
    locked = client.post("/api/v1/auth/login", json={"name": "tester", "password": PASSWORD})
    # Locked, and saying no more than a wrong password does (review before 1.0.0).
    assert locked.status_code == 401 and locked.json()["detail"]["code"] == "wrong_credentials"
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None and row.locked_until is not None
    # A passed code is what resets the count.
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.locked_until = None
        row.failed_logins = 3
        db.commit()
    password_step(client)
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None and row.failed_logins == 3
    assert code_step(client, fresh_code(secret, clock)).status_code == 200
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None and row.failed_logins == 0


def test_a_recovery_code_signs_in_once(client: TestClient, operator: Account, clock: Clock) -> None:
    _secret, codes = enrol(client)
    sign_out(client)
    password_step(client)
    used = code_step(client, codes[0])
    assert used.status_code == 200, used.text
    assert used.json()["two_factor_recovery_left"] == 7
    sign_out(client)
    password_step(client)
    assert code_step(client, codes[0]).status_code == 401
    assert code_step(client, codes[1]).status_code == 200


def test_new_recovery_codes_replace_the_old_ones(client: TestClient, operator: Account, clock: Clock) -> None:
    _secret, old = enrol(client)
    assert client.post("/api/v1/auth/totp/recovery", json={"password": "wrong one"}).status_code == 401
    renewed = client.post("/api/v1/auth/totp/recovery", json={"password": PASSWORD})
    assert renewed.status_code == 200
    new = renewed.json()["recovery_codes"]
    assert len(new) == 8 and not set(new) & set(old)
    sign_out(client)
    password_step(client)
    assert code_step(client, old[0]).status_code == 401
    assert code_step(client, new[0]).status_code == 200


def test_turning_it_off_needs_the_password(client: TestClient, operator: Account, clock: Clock) -> None:
    enrol(client)
    assert client.post("/api/v1/auth/totp/disable", json={"password": "wrong one"}).status_code == 401
    off = client.post("/api/v1/auth/totp/disable", json={"password": PASSWORD})
    assert off.status_code == 200 and off.json()["two_factor"] is False
    sign_out(client)
    # One step again.
    one = client.post("/api/v1/auth/login", json={"name": "tester", "password": PASSWORD})
    assert one.status_code == 200 and one.json()["name"] == "tester"


def test_a_seed_sealed_with_another_secret_fails_closed(
    client: TestClient, operator: Account, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret, _codes = enrol(client)
    sign_out(client)
    password_step(client)
    monkeypatch.setattr(totp, "decrypt_secret", lambda _stored: "")
    refused = code_step(client, fresh_code(secret, clock))
    assert refused.status_code == 401 and refused.json()["detail"]["code"] == "second_factor_unavailable"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_the_operator_resets_a_member_but_not_the_other_way_round(
    client: TestClient, operator: Account, clock: Clock
) -> None:
    anna = person("anna")
    enrol(anna)
    anna_id = anna.get("/api/v1/auth/me").json()["id"]
    assert anna.post(f"/api/v1/accounts/{operator.id}/totp/reset").status_code == 403
    # The operator turns their own off on the account page, not here.
    assert client.post(f"/api/v1/accounts/{operator.id}/totp/reset", json={"current_password": PASSWORD}).status_code == 409
    reset = client.post(f"/api/v1/accounts/{anna_id}/totp/reset", json={"current_password": PASSWORD})
    assert reset.status_code == 200 and reset.json()["two_factor"] is False
    assert client.post(f"/api/v1/accounts/{anna_id}/totp/reset", json={"current_password": PASSWORD}).status_code == 409
    # Every session of the account ended with it.
    assert anna.get("/api/v1/auth/me").status_code == 401
    listed = {row["name"]: row["two_factor"] for row in client.get("/api/v1/accounts").json()}
    assert listed["anna"] is False


# --- Required by the operator ----------------------------------------------------------------------------------------


def test_required_mode_lets_an_account_without_a_second_factor_only_enrol(
    client: TestClient, operator: Account, clock: Clock
) -> None:
    anna = person("anna")
    assert anna.get("/api/v1/api-keys").status_code == 200
    # The operator switches it on only with a factor of their own: else they would lock themselves out first.
    refused = client.put("/api/v1/settings", json={"two_factor_required": True})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "own_second_factor_first"
    enrol(client)
    assert client.put("/api/v1/settings", json={"two_factor_required": True}).json()["two_factor_required"] is True
    me = anna.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["second_factor_setup_required"] is True
    for method, path in (("GET", "/api/v1/api-keys"), ("GET", "/api/v1/about/updates"), ("PUT", "/api/v1/me/language")):
        blocked = anna.request(method, path, json={"language": ""})
        assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "second_factor_setup_required", path
    enrol(anna)
    assert anna.get("/api/v1/auth/me").json()["second_factor_setup_required"] is False
    assert anna.get("/api/v1/api-keys").status_code == 200


def test_an_account_through_a_provider_only_is_not_sent_to_set_one_up_but_may_enrol_its_own(
    client: TestClient, operator: Account, clock: Clock
) -> None:
    """With "Require a second factor" on, only password accounts are sent to set one up. An account
    through a provider only (no password here) is not forced; its own second factor, if it makes one, is asked after a
    provider whose entry does not check it (``tests/test_oidc_app.py``)."""
    with SessionLocal() as db:
        row = Account(name="idp-user", role="member", sign_in=SIGN_IN_OIDC, oidc_subject="sub-1", email="u@example.com")
        db.add(row)
        db.commit()
        token = start_session(db, row, "127.0.0.1", "tests")
    other = TestClient(app, base_url="http://testserver", headers={"X-Nexpaper-Client": "tab-idpuser0"})
    other.cookies.set(SESSION_COOKIE, token)
    enrol(client)
    assert client.put("/api/v1/settings", json={"two_factor_required": True}).status_code == 200
    assert other.get("/api/v1/api-keys").status_code == 200
    me = other.get("/api/v1/auth/me").json()
    assert me["second_factor_setup_required"] is False and me["second_factor_required"] is False
    # The switch of 1.0.1 is no setting any more: the entry of each provider says it (``oidc_store``).
    assert "oidc_second_factor_by_provider" not in client.get("/api/v1/settings").json()
    # Such an account may still enrol one of its own, without a password: right after signing in through the provider.
    begun = other.post("/api/v1/auth/totp/begin")
    assert begun.status_code == 200
    confirmed = other.post("/api/v1/auth/totp/confirm", json={"code": current_code(begun.json()["secret"])})
    assert confirmed.status_code == 200 and len(confirmed.json()["recovery_codes"]) == totp.RECOVERY_CODES
    with SessionLocal() as db:
        assert db.scalar(select(Account.totp_secret_enc).where(Account.name == "idp-user")) != ""


def test_an_account_from_a_provider_changes_its_factor_only_soon_after_signing_in(
    client: TestClient, operator: Account, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import timedelta

    from app import clock as app_clock

    with SessionLocal() as db:
        row = Account(name="idp-user", role="member", sign_in=SIGN_IN_OIDC, oidc_subject="sub-1", email="u@example.com")
        db.add(row)
        db.commit()
        token = start_session(db, row, "127.0.0.1", "tests")
    other = TestClient(app, base_url="http://testserver", headers={"X-Nexpaper-Client": "tab-idpuser0"})
    other.cookies.set(SESSION_COOKIE, token)
    later = app_clock.now() + timedelta(minutes=11)
    monkeypatch.setattr(app_clock, "now", lambda: later)
    begun = other.post("/api/v1/auth/totp/begin")
    stale = other.post("/api/v1/auth/totp/confirm", json={"code": current_code(begun.json()["secret"])})
    assert stale.status_code == 403 and stale.json()["detail"]["code"] == "sign_in_again"


# --- Recovery codes are kept as keyed hashes ------------------------------------------------------------------


def test_recovery_codes_are_stored_as_keyed_hashes_not_plain_sha256() -> None:
    import hashlib

    codes = totp.generate_recovery_codes()
    stored = totp.recovery_hashes(codes)
    for code in codes:
        plain = hashlib.sha256(code.replace("-", "").encode()).hexdigest()
        assert plain not in stored, "whoever reads the database alone can test no guess against it"
    entries = totp.load_recovery(stored)
    assert all(entry.startswith(totp.RECOVERY_MARK) and len(entry) == len(totp.RECOVERY_MARK) + 64 for entry in entries)
    assert len(set(entries)) == len(codes)
    # Typed the way people type them from paper, and counted once.
    remaining = totp.use_recovery(stored, codes[1].upper().replace("-", " "))
    assert remaining is not None and len(totp.load_recovery(remaining)) == len(codes) - 1
    assert totp.use_recovery(remaining, codes[1]) is None
    assert totp.use_recovery(stored, "abcde-fghjk") is None


def test_the_key_comes_from_the_server_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    codes = totp.generate_recovery_codes()
    stored = totp.recovery_hashes(codes)
    assert totp.use_recovery(stored, codes[0]) is not None
    monkeypatch.setattr(get_settings(), "secret_key", "another key entirely")
    assert totp.use_recovery(stored, codes[0]) is None, "another server secret: the list does not match, it fails closed"
    assert totp.recovery_hashes(codes) != stored


def test_a_list_made_before_still_signs_in_and_each_code_counts_once(client: TestClient, operator: Account, clock: Clock) -> None:
    secret, _codes = enrol(client)
    codes = totp.generate_recovery_codes()
    mixed = [totp.legacy_hash_recovery(code) for code in codes[:4]] + [totp.hash_recovery(code) for code in codes[4:]]
    import json

    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.totp_recovery = json.dumps(mixed)
        db.commit()
    for number in (0, 5):
        sign_out(client)
        password_step(client)
        used = code_step(client, codes[number])
        assert used.status_code == 200, used.text
        sign_out(client)
        password_step(client)
        assert code_step(client, codes[number]).status_code == 401, "once, in either form"
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None and len(totp.load_recovery(row.totp_recovery)) == 6
    assert secret
