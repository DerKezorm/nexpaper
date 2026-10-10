"""Security review before 1.0.0, nexpaper on the internet: the first setup, the sign-in brake, the operator's network;
the second factor required from the start and set up right after the password, every route closed to a session that
must set it up first, five failures and a quarter of an hour per account and per address, sessions and devices."""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import clock as app_clock
from app import security
from app.config import get_settings
from app.db import SessionLocal
from app.deps import CODES_ONLY_PATHS, SETUP_ONLY_PATHS, UNKNOWN_PROXY_FREE
from app.main import ROUTERS, app
from app.models import Account
from app.routers.auth import PENDING_COOKIE
from app.security import DEVICE_COOKIE, SESSION_COOKIE, brake
from app.services import accounts, settings_service, totp

from .conftest import PASSWORD, SETUP_CODE, make_account, require_second_factor, sign_in

GOOD = "a long enough password"


def fresh(host: str = "203.0.113.7") -> TestClient:
    return TestClient(app, base_url="http://testserver", headers={"X-Nexpaper-Client": "tab-hardening0"},
                      client=(host, 50000))


# --- The first setup ------------------------------------------------------------------------------------------------


def test_setup_without_the_code_or_with_a_wrong_one_is_refused(client: TestClient) -> None:
    assert client.get("/api/v1/setup").json()["code_required"] is True
    for code in ("", "guess"):
        refused = client.post("/api/v1/setup", json={"name": "boss", "password": GOOD, "code": code})
        assert refused.status_code == 403 and refused.json()["detail"]["code"] == "setup_code_wrong"
    assert client.get("/api/v1/setup").json()["needs_setup"] is True
    made = client.post("/api/v1/setup", json={"name": "boss", "password": GOOD, "code": SETUP_CODE})
    assert made.status_code == 200


def test_guessing_the_setup_code_is_braked(client: TestClient) -> None:
    brake.forget()
    answers = [client.post("/api/v1/setup", json={"name": "boss", "password": GOOD, "code": f"g{n}"}).status_code
               for n in range(7)]
    assert answers[:5] == [403] * 5 and answers[-1] == 429
    brake.forget()


def test_without_a_given_token_nexpaper_makes_a_code_and_writes_it_to_the_log(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(get_settings(), "setup_token", "")
    monkeypatch.setattr(accounts, "_generated_code", None)
    code = accounts.setup_code()
    assert len(code) == 14 and code == accounts.setup_code()
    from app.db import SessionLocal

    with caplog.at_level(logging.WARNING, logger="nexpaper.auth"), SessionLocal() as db:
        accounts.announce_setup_code(db)
    assert code in caplog.text
    made = client.post("/api/v1/setup", json={"name": "boss", "password": GOOD, "code": code.lower()})
    assert made.status_code == 200


def test_ten_setups_at_once_make_exactly_one_operator(client: TestClient) -> None:
    answers: list[int] = []
    start = threading.Barrier(10)

    def one(number: int) -> None:
        person = fresh(f"203.0.113.{number + 1}")
        start.wait()
        answers.append(person.post("/api/v1/setup", json={"name": f"boss{number}", "password": GOOD,
                                                       "code": SETUP_CODE}).status_code)

    threads = [threading.Thread(target=one, args=(n,)) for n in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(answers) == [200] + [409] * 9


# --- Guessing passwords ---------------------------------------------------------------------------------------------


def lock(name: str) -> None:
    """A stranger's five wrong passwords, each from a new address."""
    for number in range(security.MAX_FAILURES):
        brake.forget()
        fresh(f"198.51.100.{number + 1}").post("/api/v1/auth/login", json={"name": name, "password": "wrong guess"})
    brake.forget()


def test_a_locked_account_still_lets_in_the_browser_that_signed_in_before(client: TestClient) -> None:
    make_account("anna")
    own = fresh("192.0.2.10")
    assert own.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200
    assert own.cookies.get(DEVICE_COOKIE, path="/api/v1/auth")
    own.post("/api/v1/auth/logout")
    lock("anna")
    stranger = fresh("198.51.100.99")
    refused = stranger.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    assert refused.status_code == 401 and refused.json()["detail"]["code"] == "wrong_credentials"
    assert own.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200


def test_a_device_cookie_of_another_account_or_forged_does_not_open_a_lock(client: TestClient) -> None:
    make_account("anna")
    bob = make_account("bob")
    lock("anna")
    other = fresh()
    other.cookies.set(DEVICE_COOKIE, security.device_token(bob.id), path="/api/v1/auth")
    assert other.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 401
    forged = fresh()
    forged.cookies.set(DEVICE_COOKIE, "1.abc." + "0f" * 16, path="/api/v1/auth")  # well-formed, not signed
    assert forged.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 401


def test_sixty_wrong_passwords_at_once_count_no_more_than_the_lock_allows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_account("anna")
    counted: list[int] = []
    original = accounts.note_failure

    def counting(db, account) -> None:  # type: ignore[no-untyped-def]
        counted.append(1)
        original(db, account)

    monkeypatch.setattr(accounts, "note_failure", counting)
    start = threading.Barrier(30)

    def one(number: int) -> None:
        person = fresh(f"198.51.{number // 200}.{number % 200 + 1}")
        start.wait()
        person.post("/api/v1/auth/login", json={"name": "anna", "password": "wrong guess"})

    threads = [threading.Thread(target=one, args=(n,)) for n in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    brake.forget()
    assert len(counted) == security.MAX_FAILURES == 5


def test_behind_a_proxy_nexpaper_was_not_told_about_a_stranger_does_not_freeze_everybody(client: TestClient) -> None:
    make_account("anna")
    make_account("bob")
    proxy = fresh("172.18.0.2")
    for number in range(8):
        proxy.post("/api/v1/auth/login", json={"name": "anna", "password": "wrong guess"},
                   headers={"X-Forwarded-For": f"6.6.6.{number}"})
    answer = proxy.post("/api/v1/auth/login", json={"name": "bob", "password": PASSWORD},
                        headers={"X-Forwarded-For": "7.7.7.7"})
    assert answer.status_code == 200
    brake.forget()


def test_signing_in_to_an_own_account_does_not_reset_the_brake_for_guessing_others(client: TestClient) -> None:
    make_account("mallory")
    for name in ("anna", "bob", "carl", "dora", "emil", "fred"):
        make_account(name)
    sprayer = fresh("203.0.113.50")
    answers = []
    for round_ in range(10):
        for name in ("anna", "bob", "carl", "dora"):
            answers.append(sprayer.post("/api/v1/auth/login",
                                        json={"name": name, "password": f"guess {round_}"}).status_code)
        sprayer.post("/api/v1/auth/login", json={"name": "mallory", "password": PASSWORD})
    assert 429 in answers
    brake.forget()


def test_ports_and_spellings_of_one_address_are_one_sender(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.deps import normal_address

    assert {normal_address(x) for x in ("7.7.7.7", "7.7.7.7:4000", "::ffff:7.7.7.7", "[::ffff:7.7.7.7]:1")} == {
        "7.7.7.7"}
    assert normal_address("2001:db8::1") == normal_address("[2001:db8::2]:443") == "2001:db8::/64"
    monkeypatch.setattr(get_settings(), "trusted_proxies", "10.9.0.0/16")
    proxy = fresh("10.9.0.1")
    answers = [proxy.post("/api/v1/auth/login", json={"name": "nobody", "password": "x"},
                          headers={"X-Forwarded-For": f"7.7.7.7:{4000 + n}"}).status_code for n in range(7)]
    assert answers[-1] == 429
    brake.forget()


def test_checking_passwords_has_a_limit_and_answers_busy_beyond_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_account("anna")
    monkeypatch.setattr(security, "_hashing", threading.BoundedSemaphore(1))
    monkeypatch.setattr(security, "HASH_WAIT", 0.05)
    security._hashing.acquire()
    try:
        busy = fresh().post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    finally:
        security._hashing.release()
    assert busy.status_code == 503 and busy.json()["detail"]["code"] == "busy"


def test_the_brake_forgets_after_an_hour_and_keeps_its_table_small(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(app_clock, "monotonic", lambda: clock[0])
    own = security.Brake()
    for _ in range(8):
        own.failed("x")
    assert own.wait_seconds("x") > 0
    clock[0] += own.FORGET_AFTER + 1
    assert own.wait_seconds("x") == 0
    monkeypatch.setattr(security.Brake, "MAX_KEYS", 100)
    for number in range(500):
        own.failed(f"k{number}")
    assert len(own._fails) <= 101


# --- Invitations and the operator's network ---------------------------------------------------------------------------


def test_trying_taken_names_on_an_invitation_is_braked(client: TestClient, operator: object) -> None:
    for name in ("anna", "bob", "carl", "dora", "emil", "fred", "gina", "hans", "ida"):
        make_account(name)
    link = client.post("/api/v1/invites", json={"days": 7}).json()["link"].rsplit("/", 1)[-1]
    guest = fresh("203.0.113.77")
    answers = [guest.post(f"/api/v1/invite/{link}", json={"name": name, "password": GOOD}).status_code
               for name in ("anna", "bob", "carl", "dora", "emil", "fred", "gina", "hans", "ida")]
    assert answers[:8] == [409] * 8 and answers[-1] == 429
    brake.forget()


def test_operator_settings_only_from_the_operator_networks(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    boss = make_account("boss", "operator")
    home, away = fresh("192.168.1.20"), fresh("203.0.113.9")
    for person in (home, away):
        assert person.post("/api/v1/auth/login", json={"name": boss.name, "password": PASSWORD}).status_code == 200
    assert away.get("/api/v1/accounts").status_code == 200
    monkeypatch.setattr(get_settings(), "operator_networks", "192.168.0.0/16")
    assert home.get("/api/v1/accounts").status_code == 200
    refused = away.get("/api/v1/accounts")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "operator_network"
    # Everything else stays open from anywhere.
    assert away.get("/api/v1/api-keys").status_code == 200


# --- The second factor, required from the start (B7) -----------------------------------------------------------------


@pytest.fixture
def later(monkeypatch: pytest.MonkeyPatch) -> Callable[[float], None]:
    """Moves the server's clock (the wall clock and the brake's) ahead by the seconds given."""
    offset = [0.0]
    real_now, real_monotonic = app_clock.now, app_clock.monotonic
    monkeypatch.setattr(app_clock, "now", lambda: real_now() + timedelta(seconds=offset[0]))
    monkeypatch.setattr(app_clock, "monotonic", lambda: real_monotonic() + offset[0])

    def advance(seconds: float) -> None:
        offset[0] += seconds

    return advance


def test_the_second_factor_is_required_from_the_start() -> None:
    assert settings_service.DEFAULTS["two_factor_required"] is True
    assert settings_service.DEFAULTS["oidc_second_factor_by_provider"] is False


def password_only(name: str = "anna", host: str = "203.0.113.20", remember: bool = True) -> TestClient:
    """A browser that gave the password of an account without a second factor, where one is required."""
    browser = fresh(host)
    answer = browser.post("/api/v1/auth/login", json={"name": name, "password": PASSWORD, "remember": remember})
    assert answer.status_code == 200, answer.text
    assert answer.json()["session_stage"] == "setup" and answer.json()["second_factor_setup_required"] is True
    return browser


def set_up_totp(browser: TestClient) -> tuple[str, list[str]]:
    begun = browser.post("/api/v1/auth/totp/begin")
    assert begun.status_code == 200, begun.text
    seed = begun.json()["secret"]
    done = browser.post("/api/v1/auth/totp/confirm", json={"code": totp.code_at(seed, time.time())})
    assert done.status_code == 200, done.text
    return seed, done.json()["recovery_codes"]


def test_without_a_second_factor_it_is_set_up_right_after_the_password_and_only_then_the_session_is_full() -> None:
    require_second_factor()
    make_account("anna")
    browser = password_only()
    # Nothing but the setup: no device cookie yet, and no data.
    assert not browser.cookies.get(DEVICE_COOKIE, path="/api/v1/auth")
    me = browser.get("/api/v1/auth/me").json()
    assert me["session_stage"] == "setup" and me["second_factor_setup_required"] is True
    assert browser.get("/api/v1/devices").status_code == 403
    # Right after the password the code is enough; the password is not asked again.
    _seed, codes = set_up_totp(browser)
    assert len(codes) == totp.RECOVERY_CODES
    assert browser.get("/api/v1/auth/me").json()["session_stage"] == "codes"
    # Still nothing but saying the codes are kept.
    refused = browser.get("/api/v1/devices")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "second_factor_setup_required"
    assert browser.post("/api/v1/auth/totp/begin").status_code == 403
    old = browser.cookies.get(SESSION_COOKIE)
    done = browser.post("/api/v1/auth/setup/done")
    assert done.status_code == 200 and done.json()["session_stage"] == "full"
    # A new token for the full session; the one that lived through the setup opens nothing any more.
    assert browser.cookies.get(SESSION_COOKIE) != old
    assert browser.get("/api/v1/devices").status_code == 200
    assert browser.cookies.get(DEVICE_COOKIE, path="/api/v1/auth")
    stale = fresh()
    stale.cookies.set(SESSION_COOKIE, old)
    assert stale.get("/api/v1/auth/me").status_code == 401
    # Twice is once: the second click finds nothing to confirm.
    assert browser.post("/api/v1/auth/setup/done").status_code == 409


def test_the_first_operator_sets_up_the_second_factor_right_after_the_setup(client: TestClient) -> None:
    require_second_factor()
    made = client.post("/api/v1/setup", json={"name": "boss", "password": GOOD, "code": SETUP_CODE})
    assert made.status_code == 200 and made.json()["session_stage"] == "setup"
    assert client.get("/api/v1/settings").status_code == 403
    set_up_totp(client)
    assert client.post("/api/v1/auth/setup/done").status_code == 200
    assert client.get("/api/v1/settings").status_code == 200


def test_a_session_for_the_setup_lasts_a_quarter_of_an_hour(later: Callable[[float], None]) -> None:
    require_second_factor()
    make_account("anna")
    browser = password_only()
    later(security.SETUP_MINUTES * 60 + 1)
    assert browser.get("/api/v1/auth/me").status_code == 401


def test_a_setup_session_is_over_when_the_factor_was_set_up_elsewhere() -> None:
    require_second_factor()
    make_account("anna")
    first, second = password_only(host="203.0.113.21"), password_only(host="203.0.113.22")
    set_up_totp(first)
    # Whoever holds the other setup session knows the password at most: it cannot become anything now.
    assert second.get("/api/v1/auth/me").status_code == 401
    assert second.post("/api/v1/auth/setup/done").status_code == 401


def every_route() -> Iterator[tuple[str, str]]:
    """Every route of the API, as the app has them (not a list kept by hand)."""
    for module in ROUTERS:
        for route in module.router.routes:
            if isinstance(route, APIRoute) and route.path.startswith("/api/"):
                for method in sorted(route.methods):
                    yield method, route.path


def concrete(path: str) -> str:
    values = {"uid": "0" * 32, "token": "a" * 30, "date": "2026-10-07"}
    return re.sub(r"\{(\w+)(:[^}]*)?\}", lambda match: values.get(match.group(1), "1"), path)


def restricted_browsers() -> dict[str, TestClient]:
    """The three kinds of session that may only set up the second factor: right after the password, between the code
    and the recovery codes, and a full one of an account the operator now asks for a factor."""
    require_second_factor()
    make_account("anna")
    make_account("bert")
    carl = make_account("carl")
    setup = password_only("anna", "203.0.113.30")
    codes = password_only("bert", "203.0.113.31")
    set_up_totp(codes)
    full = fresh("203.0.113.32")
    sign_in(full, carl)
    return {"setup": setup, "codes": codes, "full": full}


def test_a_session_that_must_set_up_the_second_factor_reaches_no_other_route() -> None:
    browsers = restricted_browsers()
    allowed = {"setup": SETUP_ONLY_PATHS, "codes": CODES_ONLY_PATHS, "full": SETUP_ONLY_PATHS}
    nobody = fresh("203.0.113.33")
    checked = 0
    for method, path in every_route():
        if path == "/api/v1/auth/logout":
            continue
        url = concrete(path)
        brake.forget()
        without = nobody.request(method, url, json={})
        if without.status_code not in (401, 403):
            continue  # a route anyone may call, signed in or not
        for stage, browser in browsers.items():
            if path in allowed[stage]:
                continue
            brake.forget()
            answer = browser.request(method, url, json={})
            assert answer.status_code in (401, 403), (stage, method, path, answer.status_code)
            checked += 1
    # Floor: the routes were found at all.
    assert checked > 150
    # And each kind still reaches its own setup.
    assert browsers["setup"].get("/api/v1/auth/me").status_code == 200
    assert browsers["codes"].get("/api/v1/auth/me").json()["session_stage"] == "codes"
    assert browsers["full"].post("/api/v1/auth/totp/begin").status_code == 200


def test_a_full_session_reaches_the_same_routes() -> None:
    """The counterpart: the routes refused above are not refused for everybody."""
    make_account("anna")
    browser = fresh()
    sign_in(browser, make_account("dora"))
    assert browser.get("/api/v1/devices").status_code == 200
    assert browser.get("/api/v1/auth/sessions").status_code == 200


# --- Five failures, a quarter of an hour, per account and per address --------------------------------------------------


def test_five_wrong_passwords_lock_the_account_for_a_quarter_of_an_hour(later: Callable[[float], None]) -> None:
    make_account("anna")
    # Five, as decided (06.10.2026); written out, not taken from the code it checks.
    for number in range(5):
        answer = fresh(f"198.51.100.{number + 1}").post("/api/v1/auth/login", json={"name": "anna", "password": "no"})
        assert answer.status_code == 401
    # From a sixth address, with the right password: still locked, and saying no more than a wrong password.
    locked = fresh("198.51.100.50").post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    assert locked.status_code == 401 and locked.json()["detail"]["code"] == "wrong_credentials"
    later(security.LOCK_MINUTES * 60 - 30)
    assert fresh("198.51.100.51").post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 401
    later(31)
    assert fresh("198.51.100.52").post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200


def test_five_failures_from_one_address_make_it_rest_a_quarter_of_an_hour(later: Callable[[float], None]) -> None:
    make_account("anna")
    for name in ("x1", "x2", "x3", "x4", "x5"):
        assert fresh("203.0.113.60").post("/api/v1/auth/login", json={"name": name, "password": "no"}).status_code == 401
    resting = fresh("203.0.113.60").post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    assert resting.status_code == 429 and resting.headers["retry-after"] == str(security.LOCK_MINUTES * 60)
    # Another address is not touched.
    assert fresh("203.0.113.61").post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200
    later(security.LOCK_MINUTES * 60 - 30)
    assert fresh("203.0.113.60").post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 429
    later(31)
    assert fresh("203.0.113.60").post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200


def test_every_kind_of_failure_counts_for_the_address(client: TestClient, operator: object) -> None:
    """Wrong invitation links and wrong passwords: five together, and the address rests."""
    link = client.post("/api/v1/invites", json={"days": 7}).json()["link"].rsplit("/", 1)[-1]
    guest = fresh("203.0.113.70")
    assert guest.post("/api/v1/invite/" + "c" * 30, json={"name": "newbie", "password": GOOD}).status_code == 404
    for _ in range(2):
        assert guest.get("/api/v1/invite/" + "b" * 30).status_code == 404
    assert guest.post("/api/v1/auth/login", json={"name": "nobody", "password": "no"}).status_code == 401
    assert guest.post("/api/v1/auth/login", json={"name": "nobody", "password": "no"}).status_code == 401
    # Now even a valid invitation waits.
    assert guest.get(f"/api/v1/invite/{link}").status_code == 429


def test_a_forwarded_header_from_a_sender_nexpaper_does_not_trust_buys_nothing_much(client: TestClient) -> None:
    """Without a trusted proxy the header is not the sender's address; made-up hops get at most the proxy's room."""
    make_account("anna")
    sender = fresh("203.0.113.80")
    answers = [sender.post("/api/v1/auth/login", json={"name": f"n{n}", "password": "no"},
                           headers={"X-Forwarded-For": f"6.6.{n}.1"}).status_code for n in range(40)]
    assert answers.count(401) == UNKNOWN_PROXY_FREE and answers[-1] == 429


def test_an_unknown_name_and_a_wrong_password_answer_alike(monkeypatch: pytest.MonkeyPatch) -> None:
    make_account("anna")
    checks: list[int] = []
    original = security.verify_password

    def counting(password: str, password_hash: str) -> bool:
        checks.append(1)
        return original(password, password_hash)

    monkeypatch.setattr(accounts, "verify_password", counting)
    unknown = fresh("203.0.113.90").post("/api/v1/auth/login", json={"name": "nobody", "password": "no"})
    wrong = fresh("203.0.113.91").post("/api/v1/auth/login", json={"name": "anna", "password": "no"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    # Each costs exactly one password check: the time does not tell either.
    assert checks == [1, 1]


def test_the_same_code_at_the_same_moment_lets_in_once(client: TestClient, operator: object) -> None:
    begun = client.post("/api/v1/auth/totp/begin").json()
    client.post("/api/v1/auth/totp/confirm", json={"code": totp.code_at(begun["secret"], time.time()), "password": PASSWORD})
    browser = fresh("203.0.113.95")
    assert browser.post("/api/v1/auth/login", json={"name": "tester", "password": PASSWORD}).json()["second_factor"]
    twin = fresh("203.0.113.95")
    twin.cookies.set(PENDING_COOKIE, browser.cookies.get(PENDING_COOKIE, path="/api/v1/auth") or "")
    # A code of the next step, given twice at once with the same waiting sign-in, from two tabs.
    code = totp.code_at(begun["secret"], time.time() + totp.STEP_SECONDS)
    answers: list[int] = []
    start = threading.Barrier(2)

    def one(tab: TestClient) -> None:
        start.wait()
        answers.append(tab.post("/api/v1/auth/login/totp", json={"code": code}).status_code)

    threads = [threading.Thread(target=one, args=(tab,)) for tab in (browser, twin)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert answers.count(200) == 1 and len(answers) == 2


def test_a_recovery_code_is_taken_once_also_at_the_same_moment() -> None:
    account = make_account("anna")
    codes = totp.generate_recovery_codes()
    stored = totp.recovery_hashes(codes)
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        row.totp_recovery = stored
        db.commit()
        remaining = totp.use_recovery(stored, codes[0])
        assert remaining is not None
        assert totp.claim_recovery(db, account.id, stored, remaining) is True
        # A second request that read the same list before: it must not take the code once more.
        assert totp.claim_recovery(db, account.id, stored, remaining) is False


# --- Sessions and devices ------------------------------------------------------------------------------------------


def test_staying_signed_in_slides_thirty_days_and_ends_after_thirty_unused(later: Callable[[float], None]) -> None:
    make_account("anna")
    browser = fresh()
    answer = browser.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD, "remember": True})
    line = next(line for line in answer.headers.get_list("set-cookie") if line.startswith(SESSION_COOKIE + "="))
    assert "max-age=" in line.lower()
    days = get_settings().session_days
    for _ in range(3):
        later((days - 1) * 86400)
        assert browser.get("/api/v1/devices").status_code == 200, "used within 30 days: it goes on"
    later(days * 86400 + 1)
    assert browser.get("/api/v1/devices").status_code == 401


def test_without_staying_the_session_ends_with_the_browser_and_after_twelve_hours(
    later: Callable[[float], None],
) -> None:
    make_account("anna")
    browser = fresh()
    answer = browser.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD, "remember": False})
    line = next(line for line in answer.headers.get_list("set-cookie") if line.startswith(SESSION_COOKIE + "="))
    assert "max-age" not in line.lower() and "expires" not in line.lower()
    later(6 * 3600)
    assert browser.get("/api/v1/devices").status_code == 200
    later(security.SHORT_HOURS * 3600 - 6 * 3600 + 1)
    assert browser.get("/api/v1/devices").status_code == 401


def test_the_code_step_decides_whether_to_stay(client: TestClient, operator: object) -> None:
    begun = client.post("/api/v1/auth/totp/begin").json()
    client.post("/api/v1/auth/totp/confirm", json={"code": totp.code_at(begun["secret"], time.time()), "password": PASSWORD})
    browser = fresh("203.0.113.96")
    browser.post("/api/v1/auth/login", json={"name": "tester", "password": PASSWORD, "remember": True})
    code = totp.code_at(begun["secret"], time.time() + totp.STEP_SECONDS)
    answer = browser.post("/api/v1/auth/login/totp", json={"code": code, "remember": False})
    line = next(line for line in answer.headers.get_list("set-cookie") if line.startswith(SESSION_COOKIE + "="))
    assert "max-age" not in line.lower()


def test_the_devices_list_ends_one_or_all_others_and_never_another_accounts(client: TestClient) -> None:
    anna, bert = make_account("anna"), make_account("bert")
    phone = fresh("192.168.1.20")
    phone.headers["User-Agent"] = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1"
    assert phone.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200
    laptop = fresh("203.0.113.40")
    laptop.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0) Gecko/20100101 Firefox/131.0"
    assert laptop.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200
    third = fresh("203.0.113.41")
    sign_in(third, anna)
    stranger = fresh("203.0.113.42")
    sign_in(stranger, bert)
    listed = laptop.get("/api/v1/auth/sessions", headers={"X-Nexpaper-Language": "de"}).json()
    assert len(listed) == 3 and listed[0]["here"] is True and listed[0]["device"] == "Firefox unter Windows"
    by_device = {row["device"]: row for row in listed}
    assert by_device["Safari unter iPhone"]["phone"] is True
    assert by_device["Safari unter iPhone"]["network"] == "eigenes Netz 192.168.1.0/24"
    assert "token" not in str(listed) and "hash" not in str(listed)
    phone_id = by_device["Safari unter iPhone"]["id"]
    # Somebody else's session cannot be ended, nor even found.
    bert_id = stranger.get("/api/v1/auth/sessions").json()[0]["id"]
    assert laptop.delete(f"/api/v1/auth/sessions/{bert_id}").status_code == 404
    assert stranger.get("/api/v1/devices").status_code == 200
    # The own one here goes by "sign out", not from the list.
    assert laptop.delete(f"/api/v1/auth/sessions/{listed[0]['id']}").status_code == 409
    assert laptop.delete(f"/api/v1/auth/sessions/{phone_id}").status_code == 204
    assert phone.get("/api/v1/devices").status_code == 401
    assert laptop.post("/api/v1/auth/logout-all").status_code == 204
    assert third.get("/api/v1/devices").status_code == 401
    assert laptop.get("/api/v1/devices").status_code == 200
    assert [row["here"] for row in laptop.get("/api/v1/auth/sessions").json()] == [True]
    assert stranger.get("/api/v1/devices").status_code == 200


def test_session_tokens_are_kept_only_as_hashes(client: TestClient) -> None:
    make_account("anna")
    browser = fresh()
    browser.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    token = browser.cookies.get(SESSION_COOKIE)
    assert token
    path = get_settings().database_path
    raw = b"".join(candidate.read_bytes() for candidate in (path, path.with_name(path.name + "-wal"))
                   if candidate.exists())
    assert token.encode() not in raw and len(raw) > 0


def test_new_recovery_codes_only_while_they_wait_to_be_confirmed() -> None:
    """A reload loses the codes shown once: until they are confirmed, the session that set up the factor makes new
    ones; the old ones stop working. After that, new codes need the password (Account, Security)."""
    require_second_factor()
    account = make_account("anna")
    browser = password_only()
    _seed, first = set_up_totp(browser)
    again = browser.post("/api/v1/auth/setup/codes")
    assert again.status_code == 200 and len(again.json()["recovery_codes"]) == totp.RECOVERY_CODES
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        assert totp.use_recovery(row.totp_recovery, first[0]) is None
        assert totp.use_recovery(row.totp_recovery, again.json()["recovery_codes"][0]) is not None
    assert browser.post("/api/v1/auth/setup/done").status_code == 200
    assert browser.post("/api/v1/auth/setup/codes").status_code == 409


def test_a_time_step_is_taken_once_also_by_two_at_the_same_moment() -> None:
    """The code of a time step counts once wherever it is given (sign-in, saving the master key): checked and written
    in one statement, so of two at the same moment exactly one takes it."""
    account = make_account("anna")
    step = int(time.time()) // totp.STEP_SECONDS
    won: list[bool] = []
    start = threading.Barrier(4)

    def one() -> None:
        with SessionLocal() as db:
            start.wait()
            won.append(totp.claim_step(db, account.id, step))

    threads = [threading.Thread(target=one) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(won) == [False, False, False, True]
    with SessionLocal() as db:
        assert totp.claim_step(db, account.id, step) is False
        assert totp.claim_step(db, account.id, step + 1) is True


# --- A lock that strangers cause does not keep the owner out of the code step (B10) ----------------------------------


def with_second_factor(name: str) -> tuple[Account, str, list[str]]:
    """An account with a code from an app and recovery codes, straight in the database; gives the seed."""
    account = make_account(name)
    seed = totp.generate_seed()
    codes = totp.generate_recovery_codes()
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        row.totp_secret_enc, row.totp_recovery = totp.seal_seed(seed), totp.recovery_hashes(codes)
        db.commit()
    return account, seed, codes


def a_code(account: Account, seed: str) -> str:
    """The code of this moment, with the replay guard rewound so that any number of sign-ins can use it."""
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        row.totp_last_step = 0
        db.commit()
    return totp.code_at(seed, time.time())


def sign_in_with_code(browser: TestClient, account: Account, seed: str, name: str = "anna"):
    first = browser.post("/api/v1/auth/login", json={"name": name, "password": PASSWORD})
    assert first.status_code == 200 and first.json()["second_factor"] is True, first.text
    return browser.post("/api/v1/auth/login/totp", json={"code": a_code(account, seed)})


def test_strangers_who_lock_an_account_do_not_lock_its_owner_out_of_the_code_step() -> None:
    require_second_factor()
    anna, seed, codes = with_second_factor("anna")
    own = fresh("192.0.2.10")
    assert sign_in_with_code(own, anna, seed).status_code == 200
    assert own.cookies.get(DEVICE_COOKIE, path="/api/v1/auth")
    own.post("/api/v1/auth/logout")
    lock("anna")
    # The password step lets the owner's browser through a lock already; the code step now does as well.
    assert own.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).json()["second_factor"] is True
    answer = own.post("/api/v1/auth/login/totp", json={"code": a_code(anna, seed)})
    assert answer.status_code == 200, answer.text
    assert answer.json()["session_stage"] == "full"
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None and row.locked_until is None, "a passed code lifts the lock"
    # The same with a recovery code.
    own.post("/api/v1/auth/logout")
    lock("anna")
    own.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    by_recovery = own.post("/api/v1/auth/login/totp", json={"code": codes[0]})
    assert by_recovery.status_code == 200, by_recovery.text


def test_a_wrong_code_from_the_known_browser_neither_counts_towards_the_lock_nor_ends_the_sign_in_early() -> None:
    require_second_factor()
    anna, seed, _codes = with_second_factor("anna")
    own = fresh("192.0.2.11")
    assert sign_in_with_code(own, anna, seed).status_code == 200
    own.post("/api/v1/auth/logout")
    lock("anna")
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None
        until, counted = row.locked_until, row.failed_logins
    own.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    for _ in range(totp.MAX_ATTEMPTS - 1):
        wrong = own.post("/api/v1/auth/login/totp", json={"code": "000000"})
        assert wrong.status_code == 401 and wrong.json()["detail"]["code"] == "totp_code_wrong"
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None and (row.locked_until, row.failed_logins) == (until, counted)
    # What stays for it: five codes per sign-in, then the password again.
    last = own.post("/api/v1/auth/login/totp", json={"code": "000000"})
    assert last.status_code == 401 and last.json()["detail"]["code"] == "second_factor_expired"


def test_a_stranger_who_gets_to_the_code_step_of_a_locked_account_is_stopped() -> None:
    """Without the cookie of a browser that signed in as the account, the lock holds at the code step: right code,
    right recovery code or not."""
    require_second_factor()
    anna, seed, codes = with_second_factor("anna")
    stranger = fresh("198.51.100.50")
    assert stranger.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).json()["second_factor"]
    lock("anna")
    refused = stranger.post("/api/v1/auth/login/totp", json={"code": a_code(anna, seed)})
    assert refused.status_code == 429 and refused.json()["detail"]["code"] == "account_locked"
    # The waiting sign-in is over, and the recovery code gets no further.
    assert stranger.post("/api/v1/auth/login/totp", json={"code": codes[0]}).status_code == 401
    # A device cookie of another account or a forged one changes nothing.
    other, other_seed, _ = with_second_factor("bert")
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None
        row.locked_until = None
        db.commit()
    twin = fresh("198.51.100.51")
    assert twin.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).json()["second_factor"]
    lock("anna")
    twin.cookies.set(DEVICE_COOKIE, security.device_token(other.id), path="/api/v1/auth")
    assert twin.post("/api/v1/auth/login/totp", json={"code": a_code(anna, seed)}).status_code == 429
    assert other_seed


def test_the_known_browser_signs_in_with_a_passkey_while_strangers_hold_the_lock() -> None:
    from .test_passkeys import ORIGIN, SoftKey, add_key, passkey_sign_in

    with SessionLocal() as db:
        settings_service.save(db, {"public_url": ORIGIN})
    anna = make_account("anna")
    own = fresh("192.0.2.12")
    assert own.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200
    key = SoftKey()
    assert add_key(own, key).status_code == 201
    own.post("/api/v1/auth/logout")
    lock("anna")
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None and row.locked_until is not None
    stranger = fresh("198.51.100.60")
    assert passkey_sign_in(stranger, key)[0].status_code == 401
    brake.forget()
    answer, _ = passkey_sign_in(own, key)
    assert answer.status_code == 200, answer.text
