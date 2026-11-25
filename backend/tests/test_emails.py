"""The own mail address, through the shared account module: changed by a link sent to the new address where a mail
server is set up (without one it counts at once, but the intake does not trust it). The password is asked once more,
the old address stays until the link is opened, the link works once for 24 hours and is kept as a hash, a wrong link
counts against the sender, and the old address hears of a change (from the outbox of the shared post module)."""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Account, EmailConfirmation, utcnow
from app.security import brake
from app.services import notices, post_store, settings_service
from app.vendor.nexkonten.common import address_hint

from .conftest import PASSWORD, TAB, make_account, new_client
from .test_settings import FakeSmtp, smtp, text_of  # noqa: F401 - fixture

PUBLIC = "https://paper.example.com"


def mail_on(public: str = PUBLIC) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"smtp_host": "mail.example.com", "smtp_from": "paper@example.com",
                                   "public_url": public})


def token_of(smtp_class: type[FakeSmtp]) -> str:
    text = text_of(smtp_class.sent[-1])
    link = next(line for line in text.splitlines() if line.startswith(PUBLIC + "/mail/"))
    return link.rsplit("/", 1)[1]


def row_of(account: Account) -> Account:
    with SessionLocal() as db:
        found = db.get(Account, account.id)
        assert found is not None
        db.expunge(found)
        return found


def outbox() -> None:
    """The minute's round of the shared post module: the notices to the old address go out."""
    notices.settle()
    post_store.run_due()


def asks(client: TestClient, email: str, password: str = PASSWORD) -> object:
    return client.put("/api/v1/me/email", json={"email": email, "password": password})


def test_a_new_address_waits_for_its_link_and_the_old_one_stays(client: TestClient, operator: Account,
                                                                smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    answer = asks(client, "tester@example.com")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["email"] == "" and body["email_pending"] == "tester@example.com" and body["email_confirmed"] is False
    [sent] = smtp.sent
    assert sent["To"] == "tester@example.com" and "Confirm" in sent["Subject"]
    token = token_of(smtp)
    # The sign-in page of the link says whom it is for before anything is written.
    state = new_client().get(f"/api/v1/email/confirm/{token}")
    assert state.json() == {"name": "tester", "address": "tester@example.com"}
    assert row_of(operator).email == ""
    done = new_client().post(f"/api/v1/email/confirm/{token}")
    assert done.status_code == 200
    assert done.json() == {"name": "tester", "address": "tester@example.com", "old_told": False}
    mine = client.get("/api/v1/auth/me").json()
    assert mine["email"] == "tester@example.com" and mine["email_confirmed"] is True and mine["email_pending"] == ""


def test_the_link_works_once(client: TestClient, operator: Account, smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    asks(client, "tester@example.com")
    token = token_of(smtp)
    assert new_client().post(f"/api/v1/email/confirm/{token}").status_code == 200
    again = new_client().post(f"/api/v1/email/confirm/{token}")
    assert (again.status_code, again.json()["detail"]["code"]) == (404, "email_link_invalid")
    assert new_client().get(f"/api/v1/email/confirm/{token}").status_code == 404


def test_only_the_hash_is_stored_and_a_new_link_replaces_the_one_before(
    client: TestClient, operator: Account, smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    mail_on()
    asks(client, "first@example.com")
    first = token_of(smtp)
    asks(client, "second@example.com")
    second = token_of(smtp)
    with SessionLocal() as db:
        [row] = db.query(EmailConfirmation).all()
        assert row.address == "second@example.com" and first not in str(row.__dict__) and second not in str(row.__dict__)
    assert new_client().post(f"/api/v1/email/confirm/{first}").status_code == 404
    assert new_client().post(f"/api/v1/email/confirm/{second}").status_code == 200
    assert row_of(operator).email == "second@example.com"


def test_a_link_runs_out_after_24_hours(client: TestClient, operator: Account, smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    asks(client, "tester@example.com")
    token = token_of(smtp)
    with SessionLocal() as db:
        row = db.query(EmailConfirmation).one()
        assert timedelta(hours=23) < row.expires_at - utcnow() <= timedelta(hours=24)
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert new_client().post(f"/api/v1/email/confirm/{token}").status_code == 404
    assert client.get("/api/v1/auth/me").json()["email_pending"] == "", "a link that ran out waits for nothing"


def test_the_password_is_asked_again_and_counted(client: TestClient, operator: Account,
                                                 smtp: type[FakeSmtp]) -> None:  # noqa: F811
    """Wrong answers count at the shared module's door ``confirm:<account>``: five free, then the account waits."""
    mail_on()
    wrong = asks(client, "tester@example.com", "not the password")
    assert (wrong.status_code, wrong.json()["detail"]["code"]) == (401, "wrong_password")
    assert asks(client, "tester@example.com", "").status_code == 401
    assert smtp.sent == []
    with SessionLocal() as db:
        assert db.query(EmailConfirmation).count() == 0
    for _ in range(4):
        asks(client, "tester@example.com", "not the password")
    assert asks(client, "tester@example.com").status_code == 429


def test_nothing_is_sent_without_a_mail_server_or_a_public_address(client: TestClient, operator: Account,
                                                                   smtp: type[FakeSmtp]) -> None:  # noqa: F811
    """Without a mail server (or without the public address a link needs) the new address counts at once, as the
    shared account module does; it is not proven, so the intake does not trust it."""
    off = asks(client, "tester@example.com")
    assert off.status_code == 200 and off.json()["email"] == "tester@example.com"
    assert off.json()["email_counts"] is True and off.json()["email_confirmed"] is False
    with SessionLocal() as db:
        settings_service.save(db, {"smtp_host": "mail.example.com", "smtp_from": "paper@example.com"})
    other = asks(client, "other@example.com")
    assert other.status_code == 200 and other.json()["email"] == "other@example.com", "the link needs the public address"
    assert smtp.sent == []


def test_a_mail_server_that_fails_leaves_nothing_waiting(client: TestClient, operator: Account,
                                                        smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    smtp.fail = True
    failed = asks(client, "tester@example.com")
    assert (failed.status_code, failed.json()["detail"]["code"]) == (502, "mail_failed")
    with SessionLocal() as db:
        assert db.query(EmailConfirmation).count() == 0
    assert "secret@example.com" not in failed.text


@pytest.mark.parametrize("wrong", ["not an address", "a@b", "a b@example.com", "x" * 300 + "@example.com"])
def test_something_that_is_no_address_is_refused(client: TestClient, operator: Account, smtp: type[FakeSmtp],  # noqa: F811
                                                 wrong: str) -> None:
    mail_on()
    assert asks(client, wrong).status_code == 422
    assert smtp.sent == []


def test_the_confirmed_address_again_is_no_change(client: TestClient, operator: Account,
                                                  smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    asks(client, "tester@example.com")
    new_client().post(f"/api/v1/email/confirm/{token_of(smtp)}")
    same = asks(client, "Tester@Example.com")
    assert (same.status_code, same.json()["detail"]["code"]) == (409, "email_same")
    assert len(smtp.sent) == 1


def test_an_address_the_operator_typed_can_be_confirmed(client: TestClient, operator: Account,
                                                        smtp: type[FakeSmtp]) -> None:  # noqa: F811
    """An address from an invitation counts as unconfirmed until its owner opens a link."""
    mail_on()
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.email = "tester@example.com"
        db.commit()
    assert client.get("/api/v1/auth/me").json()["email_confirmed"] is False
    assert asks(client, "tester@example.com").status_code == 200
    new_client().post(f"/api/v1/email/confirm/{token_of(smtp)}")
    assert client.get("/api/v1/auth/me").json()["email_confirmed"] is True


def test_confirm_by_link_proves_the_address_there_is(client: TestClient, operator: Account,
                                                     smtp: type[FakeSmtp]) -> None:  # noqa: F811
    """"Per Link bestätigen" (the module's ``profiles.prove_email``, konten 0.3.10): a link to the address that counts
    and is not proven; opened, it is proven and nothing else changes. Nothing to prove answers ``nothing_to_prove``."""
    mail_on()
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.email = "tester@example.com"
        db.commit()
    sent = client.post("/api/v1/me/email/prove")
    assert sent.status_code == 200, sent.text
    assert sent.json()["email"] == "tester@example.com" and sent.json()["email_confirmed"] is False
    assert sent.json()["email_pending"] == "tester@example.com"
    assert new_client().post(f"/api/v1/email/confirm/{token_of(smtp)}").status_code in (200, 204)
    me = client.get("/api/v1/auth/me").json()
    assert me["email"] == "tester@example.com" and me["email_confirmed"] is True and me["email_pending"] == ""
    again = client.post("/api/v1/me/email/prove")
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "nothing_to_prove")


def test_confirm_by_link_needs_a_mail_server(client: TestClient, operator: Account) -> None:
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.email = "tester@example.com"
        db.commit()
    refused = client.post("/api/v1/me/email/prove")
    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "mail_off")


def test_the_address_can_be_taken_away_and_a_waiting_one_withdrawn(client: TestClient, operator: Account,
                                                                    smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    asks(client, "tester@example.com")
    token = token_of(smtp)
    assert client.delete("/api/v1/me/email/pending").status_code == 204
    assert new_client().post(f"/api/v1/email/confirm/{token}").status_code == 404
    new_client().post("/api/v1/email/confirm/x")  # a made-up token is only a miss
    asks(client, "tester@example.com")
    new_client().post(f"/api/v1/email/confirm/{token_of(smtp)}")
    gone = asks(client, "")
    assert gone.status_code == 200 and gone.json()["email"] == "" and gone.json()["email_confirmed"] is False


def test_each_person_changes_only_their_own_address(client: TestClient, operator: Account,
                                                    smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    anna = make_account("anna")
    with new_client(anna) as own:
        assert own.put("/api/v1/me/email", json={"email": "anna@example.com", "password": PASSWORD}).status_code == 200
    asks(client, "tester@example.com")
    assert row_of(anna).email == "" and row_of(operator).email == ""
    new_client().post(f"/api/v1/email/confirm/{token_of(smtp)}")
    assert row_of(anna).email == "" and row_of(operator).email == "tester@example.com"


def test_a_device_token_cannot_change_the_address(client: TestClient, operator: Account, smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(app, base_url="http://testserver") as device:
        refused = device.put("/api/v1/me/email", json={"email": "evil@example.com", "password": PASSWORD},
                             headers={"Authorization": f"Bearer {token}"})
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "browser_only")
    assert smtp.sent == []


def test_a_blocked_account_cannot_confirm(client: TestClient, operator: Account, smtp: type[FakeSmtp]) -> None:  # noqa: F811
    mail_on()
    anna = make_account("anna")
    with new_client(anna) as own:
        own.put("/api/v1/me/email", json={"email": "anna@example.com", "password": PASSWORD})
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None
        row.blocked_at = utcnow()
        db.commit()
    assert new_client().post(f"/api/v1/email/confirm/{token_of(smtp)}").status_code == 404


def test_links_that_do_not_hold_count_against_the_sender(client: TestClient, operator: Account) -> None:
    brake.forget()
    with TestClient(app, base_url="http://testserver", headers=TAB, client=("203.0.113.40", 50000)) as stranger:
        for index in range(5):
            assert stranger.post(f"/api/v1/email/confirm/{'x' * 20}{index}").status_code == 404
        rest = stranger.post(f"/api/v1/email/confirm/{'y' * 21}")
        assert rest.status_code == 429


def test_the_number_of_mails_is_limited(client: TestClient, operator: Account, smtp: type[FakeSmtp]) -> None:  # noqa: F811
    """Every link written counts at the shared module's door ``mail:<account>``: five pass, then it waits."""
    mail_on()
    for number in range(5):
        assert asks(client, f"a{number}@example.com").status_code == 200
    held = asks(client, "c@example.com")
    assert held.status_code == 429
    assert len(smtp.sent) == 5


def test_the_token_and_the_address_stay_out_of_the_log(client: TestClient, operator: Account, smtp: type[FakeSmtp],  # noqa: F811
                                                       caplog: pytest.LogCaptureFixture) -> None:
    mail_on()
    with caplog.at_level(logging.DEBUG):
        asks(client, "private.name@example.com")
        token = token_of(smtp)
        new_client().post(f"/api/v1/email/confirm/{token}")
    assert token not in caplog.text and "private.name@example.com" not in caplog.text


def test_a_provider_account_comes_with_an_address_its_owner_still_has_to_confirm(
    client: TestClient, operator: Account
) -> None:
    """A provider may send any address (authentik lets everybody change their own): it is the account's, but the mail
    intake counts it only once the person confirmed it by the link (``services/oidc_store.take_address``)."""
    from app.services.oidc_store import SqlStore

    with SessionLocal() as db:
        store = SqlStore(db)
        made = db.get(Account, store.create_account("sam", invite=None, email="sam@example.com"))
        bare = db.get(Account, store.create_account("kim", invite=None, email=""))
        db.commit()
        assert made is not None and bare is not None
        assert made.email == "sam@example.com" and made.email_from_provider and made.email_confirmed_at is None
        assert bare.email == "" and bare.email_confirmed_at is None


# --- One link, one writer ----------------------------------------------------------------------------------------------


def test_two_requests_with_one_link_at_the_same_moment_write_the_address_once(
    client: TestClient, operator: Account, smtp: type[FakeSmtp], monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    mail_on()
    set_confirmed(operator, "old@example.com")
    asks(client, "tester@example.com")
    token = token_of(smtp)
    # Both have found the link valid before either takes it: they meet between looking and taking.
    both_found = threading.Barrier(2, timeout=10)
    from app.services.konten_store import KontenStore

    find = KontenStore.find_email_change

    def find_then_wait(self: KontenStore, value: str) -> object:
        result = find(self, value)
        both_found.wait()
        return result

    monkeypatch.setattr(KontenStore, "find_email_change", find_then_wait)
    answers: list[int] = []

    def one(number: int) -> None:
        with TestClient(app, base_url="http://testserver", headers=TAB, client=(f"203.0.113.{80 + number}", 50000)) as box:
            answers.append(box.post(f"/api/v1/email/confirm/{token}").status_code)

    threads = [threading.Thread(target=one, args=(n,)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(answers) == [200, 404], answers
    outbox()
    assert row_of(operator).email == "tester@example.com"
    told = [message for message in smtp.sent if message["To"] == "old@example.com"]
    assert len(told) == 1, "the old address hears of the change once"


# --- The old address is told -------------------------------------------------------------------------------------------


def set_confirmed(account: Account, address: str, confirmed: bool = True) -> None:
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        row.email = address
        row.email_confirmed_at = utcnow() if confirmed else None
        db.commit()


def test_the_old_address_is_told_when_the_new_one_is_confirmed(
    client: TestClient, operator: Account, smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    mail_on()
    set_confirmed(operator, "old@example.com")
    asks(client, "tester@example.com")
    assert [message["To"] for message in smtp.sent] == ["tester@example.com"], "nothing goes to the old one before"
    done = new_client().post(f"/api/v1/email/confirm/{token_of(smtp)}")
    assert done.json()["old_told"] is True
    outbox()
    [notice] = [message for message in smtp.sent if message["To"] == "old@example.com"]
    text = notice.get_body(preferencelist=("plain",)).get_content()
    assert "t***@example.com" in text
    assert "tester@example.com" not in text, "the new address is not spelled out to the old one"


def test_an_old_address_that_counted_hears_of_it_too(
    client: TestClient, operator: Account, smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    """The owner's decision of 25.11.2026: the notice goes to every old address that counted for signing in, not only
    to one proven by a link (as nexpaper did up to 1.12.0)."""
    mail_on()
    set_confirmed(operator, "typed@example.com", confirmed=False)
    asks(client, "tester@example.com")
    done = new_client().post(f"/api/v1/email/confirm/{token_of(smtp)}")
    assert done.json()["old_told"] is True
    outbox()
    assert [message["To"] for message in smtp.sent] == ["tester@example.com", "typed@example.com"]


def test_a_first_address_has_no_old_one_to_tell(
    client: TestClient, operator: Account, smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    mail_on()
    asks(client, "tester@example.com")
    assert new_client().post(f"/api/v1/email/confirm/{token_of(smtp)}").json()["old_told"] is False
    outbox()
    assert len(smtp.sent) == 1


def test_a_mail_server_that_is_gone_by_then_tells_nobody(
    client: TestClient, operator: Account, smtp: type[FakeSmtp],  # noqa: F811
    caplog: pytest.LogCaptureFixture
) -> None:
    mail_on()
    set_confirmed(operator, "old@example.com")
    asks(client, "tester@example.com")
    token = token_of(smtp)
    with SessionLocal() as db:
        settings_service.save(db, {"smtp_host": ""})
    with caplog.at_level(logging.INFO):
        done = new_client().post(f"/api/v1/email/confirm/{token}")
    assert done.status_code == 200 and done.json()["old_told"] is False
    outbox()
    assert row_of(operator).email == "tester@example.com"
    assert [message["To"] for message in smtp.sent] == ["tester@example.com"]
    said = [line for line in caplog.messages if "Mail not queued" in line]
    assert len(said) == 1 and "no mail server" in said[0], "not told, and the log says why"
    assert "old@example.com" not in caplog.text and "tester@example.com" not in caplog.text


def test_the_address_is_hinted_not_spelled_out() -> None:
    hint = address_hint("Anna.Example@mail.example.com")
    assert hint.startswith("A") and hint.endswith("@mail.example.com") and "Example@" not in hint


def test_taking_a_confirmed_address_away_tells_the_old_address(
    client: TestClient, operator: Account, smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    mail_on()
    set_confirmed(operator, "old@example.com")
    gone = asks(client, "")
    assert gone.status_code == 200 and gone.json()["email"] == ""
    outbox()
    [notice] = smtp.sent
    assert notice["To"] == "old@example.com"
    assert "old@example.com" not in notice.get_body(preferencelist=("plain",)).get_content(), "the address is not spelled out in its own notice"


def test_taking_an_address_away_that_counted_tells_it(
    client: TestClient, operator: Account, smtp: type[FakeSmtp]  # noqa: F811
) -> None:
    """The owner's decision of 25.11.2026: also an address that only counted hears that it was taken away."""
    mail_on()
    set_confirmed(operator, "typed@example.com", confirmed=False)
    assert asks(client, "").status_code == 200
    outbox()
    assert [message["To"] for message in smtp.sent] == ["typed@example.com"]


def test_taking_an_address_away_without_a_mail_server_says_so_in_the_log(
    client: TestClient, operator: Account, smtp: type[FakeSmtp], caplog: pytest.LogCaptureFixture  # noqa: F811
) -> None:
    set_confirmed(operator, "old@example.com")
    with caplog.at_level(logging.INFO):
        assert asks(client, "").status_code == 200
    outbox()
    assert smtp.sent == []
    assert "old@example.com" not in caplog.text


