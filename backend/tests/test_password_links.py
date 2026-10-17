"""A new password by a link: the operator cannot set a password; they send a link, by mail where mail works,
otherwise shown to them once. A person can ask for a link on the sign-in page where mail works. The link works once for
24 hours, is stored as a hash, and sets a password the person chose: every session ends, the second factor stays."""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import SIGN_IN_OIDC, Account, AuthSession, PasswordReset, utcnow
from app.security import brake
from app.services import notices, resets, settings_service, totp

from .conftest import PASSWORD, TAB, make_account, new_client, require_second_factor
from .test_settings import FakeSmtp, smtp  # noqa: F401 - fixture

NEW = "a fresh and long password"
PUBLIC = "https://paper.example.com"


def mail_on(public: str = PUBLIC) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"smtp_host": "mail.example.com", "smtp_from": "paper@example.com",
                                   "public_url": public})


def set_email(account: Account, email: str) -> None:
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        row.email = email
        db.commit()


def token_of(link: str) -> str:
    return link.rsplit("/", 1)[1]


def stranger(host: str = "203.0.113.30") -> TestClient:
    return TestClient(app, base_url="http://testserver", headers=TAB, client=(host, 50000))


def stored_rows() -> list[PasswordReset]:
    with SessionLocal() as db:
        return list(db.query(PasswordReset))


# --- The operator sends a link -----------------------------------------------------------------------------------------


def test_the_operator_cannot_set_a_password_any_more(client: TestClient, operator: Account) -> None:
    anna = make_account("anna")
    gone = client.put(f"/api/v1/accounts/{anna.id}/password", json={"password": NEW, "current_password": PASSWORD})
    assert gone.status_code in (404, 405)
    assert client.post(f"/api/v1/accounts/{anna.id}/password", json={"password": NEW}).status_code in (404, 405)
    with SessionLocal() as db:
        assert db.get(Account, anna.id).password_hash != ""  # type: ignore[union-attr]
    assert stranger().post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200


def test_only_the_operator_sends_a_link_and_asks_for_the_password_again(client: TestClient, operator: Account) -> None:
    anna = make_account("anna")
    with new_client(make_account("tom")) as tom:
        assert tom.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD}).status_code == 403
    wrong = client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": "not it"})
    assert wrong.status_code == 401 and wrong.json()["detail"]["code"] == "wrong_password"
    assert stored_rows() == []
    own = client.post(f"/api/v1/accounts/{operator.id}/reset-link", json={"current_password": PASSWORD})
    assert own.status_code == 409 and own.json()["detail"]["code"] == "use_account_page"
    assert client.post("/api/v1/accounts/9999/reset-link", json={"current_password": PASSWORD}).status_code == 404
    client.post(f"/api/v1/accounts/{anna.id}/block", json={"current_password": PASSWORD})
    blocked = client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "account_blocked"


def test_without_mail_the_link_is_shown_once_and_sets_the_password_the_person_chose(
    client: TestClient, operator: Account
) -> None:
    anna = make_account("anna")
    victim = new_client(anna)
    made = client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD})
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["sent"] is False and "/reset/" in body["link"] and body["expires_at"]
    token = token_of(body["link"])
    # Only the hash is kept, and the link runs out after a day.
    [row] = stored_rows()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest() and token not in row.token_hash
    assert timedelta(hours=23) < row.expires_at - utcnow() <= timedelta(hours=24)
    assert row.created_by == operator.id

    page = stranger().get(f"/api/v1/reset/{token}")
    assert page.status_code == 200 and page.json()["name"] == "anna" and page.json()["min_password"] >= 12
    assert victim.get("/api/v1/auth/me").status_code == 200
    short = stranger().post(f"/api/v1/reset/{token}", json={"password": "short"})
    assert short.status_code == 422 and short.json()["detail"]["code"] == "password_too_short"
    assert stranger().get(f"/api/v1/reset/{token}").status_code == 200, "a refused password leaves the link"
    done = stranger().post(f"/api/v1/reset/{token}", json={"password": NEW})
    assert done.status_code == 204
    # The old password is gone, the new one works, and every session of the account ended.
    assert stranger("203.0.113.31").post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 401
    assert stranger("203.0.113.32").post("/api/v1/auth/login", json={"name": "anna", "password": NEW}).status_code == 200
    assert victim.get("/api/v1/auth/me").status_code == 401
    # Once.
    assert stranger().get(f"/api/v1/reset/{token}").status_code == 404
    again = stranger().post(f"/api/v1/reset/{token}", json={"password": NEW + "x"})
    assert again.status_code == 404 and again.json()["detail"]["code"] == "reset_invalid"
    assert stored_rows() == []


def test_the_second_factor_stays_when_the_password_is_set_by_a_link(client: TestClient, operator: Account) -> None:
    anna = make_account("anna")
    seed = totp.generate_seed()
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None
        row.totp_secret_enc = totp.seal_seed(seed)
        db.commit()
    token = token_of(client.post(f"/api/v1/accounts/{anna.id}/reset-link",
                                 json={"current_password": PASSWORD}).json()["link"])
    require_second_factor()
    assert stranger().post(f"/api/v1/reset/{token}", json={"password": NEW}).status_code == 204
    again = stranger("203.0.113.40").post("/api/v1/auth/login", json={"name": "anna", "password": NEW})
    assert again.status_code == 200 and again.json()["second_factor"] is True, "the new password is not enough"
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None and row.totp_secret_enc


def test_a_link_runs_out_and_a_new_one_replaces_the_old(client: TestClient, operator: Account) -> None:
    anna = make_account("anna")
    first = token_of(client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD}).json()["link"])
    second = token_of(client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD}).json()["link"])
    assert len(stored_rows()) == 1
    assert stranger().get(f"/api/v1/reset/{first}").status_code == 404
    assert stranger().get(f"/api/v1/reset/{second}").status_code == 200
    with SessionLocal() as db:
        row = db.query(PasswordReset).one()
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    brake.forget()
    gone = stranger().post(f"/api/v1/reset/{second}", json={"password": NEW})
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "reset_invalid"
    assert stranger("203.0.113.41").post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200


def test_a_blocked_account_or_a_deleted_one_has_no_valid_link(client: TestClient, operator: Account) -> None:
    anna, bert = make_account("anna"), make_account("bert")
    one = token_of(client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD}).json()["link"])
    two = token_of(client.post(f"/api/v1/accounts/{bert.id}/reset-link", json={"current_password": PASSWORD}).json()["link"])
    client.post(f"/api/v1/accounts/{anna.id}/block", json={"current_password": PASSWORD})
    assert stranger().get(f"/api/v1/reset/{one}").status_code == 404
    client.request("DELETE", f"/api/v1/accounts/{bert.id}", json={"confirm_name": "bert", "current_password": PASSWORD})
    assert stranger().get(f"/api/v1/reset/{two}").status_code == 404
    assert stored_rows() == [] or all(row.account_id != bert.id for row in stored_rows()), "gone with the account"


def test_two_requests_with_one_link_at_the_same_moment_set_it_once(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    anna = make_account("anna")
    token = token_of(client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD}).json()["link"])
    # Both have found the link valid before either takes it: they meet between looking and taking.
    both_found = threading.Barrier(2, timeout=10)
    hash_password = resets.hash_password
    monkeypatch.setattr(resets, "hash_password", lambda password: (both_found.wait(), hash_password(password))[1])
    answers: list[int] = []

    def one(number: int) -> None:
        browser = stranger(f"203.0.113.{60 + number}")
        answers.append(browser.post(f"/api/v1/reset/{token}", json={"password": f"{NEW} {number}"}).status_code)

    threads = [threading.Thread(target=one, args=(n,)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(answers) == [204, 404], answers


def test_guessing_links_is_braked_per_address(client: TestClient) -> None:
    box = stranger("203.0.113.70")
    answers = [box.get(f"/api/v1/reset/{'a' * 20}{n:02d}").status_code for n in range(7)]
    assert answers[:5] == [404] * 5 and answers[-1] == 429


def test_a_lock_and_waiting_sign_ins_end_with_the_new_password(client: TestClient, operator: Account) -> None:
    require_second_factor(False)
    anna = make_account("anna")
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None
        row.failed_logins = 3
        row.locked_until = utcnow() + timedelta(minutes=10)
        db.commit()
    token = token_of(client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD}).json()["link"])
    assert stranger().post(f"/api/v1/reset/{token}", json={"password": NEW}).status_code == 204
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None and row.locked_until is None and row.failed_logins == 0
        assert db.query(AuthSession).filter_by(account_id=anna.id).count() == 0


def test_with_signing_in_by_password_off_only_the_operator_can_use_a_link(client: TestClient, operator: Account) -> None:
    anna = make_account("anna")
    token = token_of(client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD}).json()["link"])
    with SessionLocal() as db:
        settings_service.save(db, {"password_login": False})
    assert stranger().get(f"/api/v1/reset/{token}").status_code == 404
    assert stranger().post(f"/api/v1/reset/{token}", json={"password": NEW}).status_code == 404


def test_the_token_never_reaches_the_log(
    client: TestClient, operator: Account, caplog: pytest.LogCaptureFixture
) -> None:
    anna = make_account("anna")
    with caplog.at_level(logging.DEBUG):
        token = token_of(client.post(f"/api/v1/accounts/{anna.id}/reset-link",
                                     json={"current_password": PASSWORD}).json()["link"])
        stranger().post(f"/api/v1/reset/{token}", json={"password": NEW})
    assert token not in caplog.text and NEW not in caplog.text
    assert "Password set through a link name=anna" in caplog.text


def test_the_log_masks_the_token_in_an_address() -> None:
    from app.services import logs

    token = "".join(chr(ord("a") + (number * 7) % 26) for number in range(30))  # made here, a literal looks real
    for line in (f"POST /api/v1/reset/{token} -> 204", f"GET /reset/{token}"):
        assert token not in logs.redact(line)


# --- By mail ---------------------------------------------------------------------------------------------------------------


def test_the_operator_sends_the_link_by_mail_to_the_address_on_record(
    client: TestClient, operator: Account, smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    mail_on()
    anna = make_account("anna")
    set_email(anna, "anna@example.com")
    sent = client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD},
                       headers={"Host": "evil.example.net"})
    assert sent.status_code == 200 and sent.json()["sent"] is True and "link" not in sent.json()
    [message] = smtp.sent
    text = message.get_content()
    assert message["To"] == "anna@example.com"
    [row] = stored_rows()
    link_line = next(line for line in text.splitlines() if "/reset/" in line)
    assert link_line.startswith(PUBLIC + "/reset/") and "evil" not in text
    assert row.token_hash == hashlib.sha256(token_of(link_line).encode()).hexdigest()
    assert "24 hours" in text and "ignore this mail" in text


def test_a_mail_that_does_not_go_out_leaves_no_link_behind(
    client: TestClient, operator: Account, smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    mail_on()
    anna = make_account("anna")
    set_email(anna, "anna@example.com")
    smtp.fail = True
    failed = client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD})
    assert failed.status_code == 502 and failed.json()["detail"]["code"] == "mail_failed"
    assert stored_rows() == []


def test_an_account_without_an_address_gets_the_link_shown_even_where_mail_works(
    client: TestClient, operator: Account, smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    mail_on()
    anna = make_account("anna")
    shown = client.post(f"/api/v1/accounts/{anna.id}/reset-link", json={"current_password": PASSWORD}).json()
    assert shown["sent"] is False and shown["link"].startswith(PUBLIC + "/reset/") and smtp.sent == []


# --- A person asks for a link ----------------------------------------------------------------------------------------


def ask(box: TestClient, who: str):
    return box.post("/api/v1/auth/forgot", json={"name": who})


def test_asking_is_offered_only_where_mail_and_the_public_address_are_set(client: TestClient) -> None:
    box = stranger()
    assert box.get("/api/v1/auth/methods").json()["forgot"] is False
    refused = ask(box, "anna")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "reset_off"
    with SessionLocal() as db:
        settings_service.save(db, {"smtp_host": "mail.example.com", "smtp_from": "paper@example.com"})
    assert box.get("/api/v1/auth/methods").json()["forgot"] is False, "the link needs the public address"
    mail_on()
    assert box.get("/api/v1/auth/methods").json()["forgot"] is True
    with SessionLocal() as db:
        settings_service.save(db, {"password_login": False})
    assert box.get("/api/v1/auth/methods").json()["forgot"] is False


def test_the_answer_is_the_same_whether_the_account_exists_or_not(smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    anna = make_account("anna")
    set_email(anna, "anna@example.com")
    blocked = make_account("rita")
    set_email(blocked, "rita@example.com")
    with SessionLocal() as db:
        row = db.get(Account, blocked.id)
        assert row is not None
        row.blocked_at = utcnow()
        oidc = Account(name="olga", role="member", sign_in=SIGN_IN_OIDC, email="olga@example.com")
        db.add(oidc)
        db.commit()
    make_account("nomail")
    answers = []
    for number, who in enumerate(("anna", "ANNA ", "ghost", "anna@example.com", "rita", "olga", "nomail",
                                  "nobody@example.com")):
        reply = ask(stranger(f"203.0.113.{80 + number}"), who)
        answers.append((reply.status_code, reply.json()))
    assert set(map(str, answers)) == {str((202, {"ok": True}))}
    notices.settle()
    # Mail went to the address on record of the account that can sign in with a password, nobody else.
    assert {message["To"] for message in smtp.sent} == {"anna@example.com"}
    assert len(stored_rows()) == 1


def test_the_link_asked_for_goes_to_the_address_on_record_and_comes_from_the_public_address(
    smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    mail_on()
    anna = make_account("anna")
    set_email(anna, "anna@example.com")
    box = stranger()
    assert ask(box, "anna@example.com").status_code == 202
    notices.settle()
    [message] = smtp.sent
    assert message["To"] == "anna@example.com"
    link = next(line for line in message.get_content().splitlines() if "/reset/" in line)
    assert link.startswith(PUBLIC + "/reset/")
    assert stranger("203.0.113.90").post(f"/api/v1/reset/{token_of(link)}", json={"password": NEW}).status_code == 204
    assert [row.created_by for row in stored_rows()] == []


def test_a_host_header_does_not_change_where_the_link_points(smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    set_email(make_account("anna"), "anna@example.com")
    box = stranger()
    ask_with_host = box.post("/api/v1/auth/forgot", json={"name": "anna"}, headers={"Host": "evil.example.net",
                                                                                  "X-Forwarded-Host": "evil.example.net"})
    assert ask_with_host.status_code == 202
    notices.settle()
    [message] = smtp.sent
    assert "evil" not in message.get_content() and PUBLIC + "/reset/" in message.get_content()


def test_asking_is_braked_per_address_and_per_account(smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    set_email(make_account("anna"), "anna@example.com")
    # Per account: the fourth request, from anywhere, sends nothing more, and answers as before.
    # (typed by name and by address alternately: what was typed is counted too, so the account's own count shows here)
    for number in range(2 * resets.PER_ACCOUNT):
        who = "anna" if number % 2 == 0 else "anna@example.com"
        assert ask(stranger(f"203.0.113.{100 + number}"), who).status_code == 202
    notices.settle()
    assert len(smtp.sent) == resets.PER_ACCOUNT
    # Per address: nine requests in a row from one, then it rests, for any name.
    brake.forget()
    box = stranger("203.0.113.120")
    codes = [ask(box, f"someone{n}").status_code for n in range(resets.PER_ADDRESS + 2)]
    assert codes[: resets.PER_ADDRESS] == [202] * resets.PER_ADDRESS and codes[-1] == 429


def test_the_same_name_typed_again_and_again_is_held_back_found_or_not(smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    set_email(make_account("anna"), "anna@example.com")
    brake.forget()
    # A name that does not exist is counted like one that does: the brake does not tell them apart.
    for who in ("anna", "ghost"):
        for number in range(resets.PER_ACCOUNT + 1):
            assert ask(stranger(f"203.0.114.{number + (0 if who == 'anna' else 20)}"), who).status_code == 202
    notices.settle()
    assert len(smtp.sent) == resets.PER_ACCOUNT


def test_many_jobs_at_the_same_moment_send_an_account_no_more_links_than_it_may_have(
    smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    mail_on()
    anna = make_account("anna")
    set_email(anna, "anna@example.com")
    start = threading.Barrier(8, timeout=10)

    def one() -> None:
        start.wait()
        resets.issue_and_send([anna.id])

    threads = [threading.Thread(target=one) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(smtp.sent) == resets.PER_ACCOUNT
    assert len(stored_rows()) == 1, "one link is open at a time, the last"


def test_the_brake_counts_and_asks_in_one_step() -> None:
    from app.security import Brake

    brake_here = Brake(quiet=True)
    answers = []
    start = threading.Barrier(10, timeout=10)

    def one() -> None:
        start.wait()
        answers.append(brake_here.claim("key", 3))

    threads = [threading.Thread(target=one) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert answers.count(0) == 3 and all(wait > 0 for wait in answers if wait)
    assert brake_here.wait_seconds("key", 3) > 0
    brake_here.succeeded("key")
    assert brake_here.claim("key", 3) == 0


def test_the_answer_does_not_wait_for_the_link_to_be_made_or_mailed(
    smtp: type[FakeSmtp], monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Found or not, the request does the same and answers: making the link and the mail come after, so that the time
    it takes does not tell whether the account exists."""
    mail_on()
    set_email(make_account("anna"), "anna@example.com")
    release = threading.Event()
    real = resets.issue_and_send
    monkeypatch.setattr(resets, "issue_and_send", lambda ids: (release.wait(10), real(ids))[1])
    answer = ask(stranger("203.0.113.130"), "anna")
    assert answer.status_code == 202
    assert stored_rows() == [] and smtp.sent == [], "nothing was made while the request answered"
    release.set()
    notices.settle()
    assert len(stored_rows()) == 1 and len(smtp.sent) == 1
