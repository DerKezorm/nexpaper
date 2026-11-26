"""nexpaper's own parts around the shared account module (``services/konten_store.py``): what the contract tests of
the module cannot know.

* **Pairing answers carry the account's id**, as a JSON number, on every route that pairs (``/devices/pair``,
  ``/devices``, ``/devices/sibling``, ``/oauth/token``), and ``account`` stays the account's first username (the bridge
  for nexpaper-ios up to 1.3, which keeps the connection by the name).
* **A rename keeps the intake:** the subfolder and the plus address of a former name still reach the account; a
  blocked account's do not, a deleted account's reach nobody (former names are reserved for good).
* **Two kinds of "confirmed":** an address that counts without a link (set without a mail server) signs in and gets
  "Forgot your password?", but the intake does not trust it; only a proven one lets mail into a vault.
* **The operator's list** has what the module's list needs, and the operator renames and takes addresses away.
* **The update from 1.12.0** adds columns and tables and keeps the second factor as it was required.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db as database
from app.db import SessionLocal
from app.models import Account, Vault
from app.models_accounts import FormerName
from app.services import backups, intake, mail_senders, settings_service
from app.services.konten_store import KontenStore, by_any_name, oldest_name
from app.vendor.nexkonten import AccountError, profiles

from .conftest import PASSWORD, make_account, new_client, remove_for_good, sign_in
from .test_pairing import ask as ask_oauth
from .test_pairing import bearer, code_from, pkce, program, redeem, show_code, trade

RECORDS = Path(__file__).parent / "schema"


def rename(account_id: int, new: str) -> None:
    with SessionLocal() as db:
        profiles.change_username(KontenStore(db), account_id, new, actor_id=account_id, actor_confirmed=True)


def assert_pairing_answer(body: dict[str, Any], account_id: int, first: str) -> None:
    # A JSON number, never text: nexpaper-ios reads it strictly as one.
    assert type(body["account_id"]) is int and body["account_id"] == account_id
    assert body["account"] == first


# --- Pairing answers -------------------------------------------------------------------------------------------------


def test_a_qr_code_pairs_with_the_account_id_and_the_first_name(client: TestClient, operator: Account) -> None:
    answer = redeem(show_code(client)["code"])
    assert answer.status_code == 201, answer.text
    assert_pairing_answer(answer.json(), operator.id, "tester")
    rename(operator.id, "chef")
    again = redeem(show_code(client)["code"])
    assert_pairing_answer(again.json(), operator.id, "tester")
    with program() as device:
        assert device.get("/api/v1/auth/me", headers=bearer(answer.json()["token"])).json()["name"] == "chef"


def test_a_device_made_in_the_browser_answers_with_the_account_id(client: TestClient, operator: Account) -> None:
    answer = client.post("/api/v1/devices", json={"name": "Scanner"})
    assert answer.status_code == 201, answer.text
    assert_pairing_answer(answer.json(), operator.id, "tester")


def test_a_sibling_device_answers_with_the_account_id(client: TestClient, operator: Account) -> None:
    token = redeem(show_code(client)["code"]).json()["token"]
    rename(operator.id, "chefin")
    with program() as device:
        answer = device.post("/api/v1/devices/sibling", headers=bearer(token), json={"name": "iPad"})
    assert answer.status_code == 201, answer.text
    assert_pairing_answer(answer.json(), operator.id, "tester")


def test_the_oauth_token_answers_with_the_account_id(client: TestClient, operator: Account) -> None:
    rename(operator.id, "chef")
    verifier, challenge = pkce()
    answer = trade(code_from(ask_oauth(client, challenge)), verifier)
    assert answer.status_code == 200, answer.text
    assert_pairing_answer(answer.json(), operator.id, "tester")


def test_the_first_name_is_the_oldest_of_several_renames() -> None:
    account = make_account("anna")
    rename(account.id, "anna-b")
    rename(account.id, "anna-c")
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None and oldest_name(db, row) == "anna"


# --- Former names in the intake ---------------------------------------------------------------------------------------


def test_a_former_name_still_reaches_its_account_for_the_plus_address() -> None:
    account = make_account("berta")
    rename(account.id, "berta.neu")
    with SessionLocal() as db:
        found = intake.account_named(db, "berta")
        assert found is not None and found.id == account.id
        assert intake.account_named(db, "BERTA.NEU") is not None


def test_a_blocked_account_s_former_name_reaches_nobody() -> None:
    account = make_account("carl")
    rename(account.id, "carl2")
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        from app.models import utcnow

        row.blocked_at = utcnow()
        db.commit()
        assert intake.account_named(db, "carl") is None


def test_a_deleted_account_s_names_reach_nobody_and_stay_reserved(client: TestClient, operator: Account) -> None:
    account = make_account("dora")
    rename(account.id, "dora2")
    answer = client.request("DELETE", f"/api/v1/accounts/{account.id}",
                            json={"current_password": PASSWORD, "confirm_name": "dora2"})
    assert answer.status_code == 204, answer.text
    with SessionLocal() as db:
        # Deleted, no mail and no file reaches it any more under either name, while it can still come back.
        assert intake.account_named(db, "dora") is None and intake.account_named(db, "dora2") is None
    remove_for_good(account)
    with SessionLocal() as db:
        assert by_any_name(db, "dora") is None and by_any_name(db, "dora2") is None
        reserved = {row.name for row in db.query(FormerName).filter(FormerName.account_id.is_(None))}
        assert {"dora", "dora2"} <= reserved
    other = make_account("emma")
    with SessionLocal() as db, pytest.raises(AccountError):
        profiles.change_username(KontenStore(db), other.id, "dora", actor_id=other.id, actor_confirmed=True)


def test_the_intake_folder_of_a_former_name_belongs_to_the_account(tmp_path: Path) -> None:
    from app.services import intake_folder

    account = make_account("fritz")
    rename(account.id, "fritz-neu")
    with SessionLocal() as db:
        settings_service.save(db, {"folder_on": True, "folder_path": str(tmp_path)})
    (tmp_path / "fritz").mkdir()
    (tmp_path / "fritz" / "brief.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    people: dict[str, int] = {}
    with SessionLocal() as db:
        from app.services.konten_store import names_by_account

        for uid, names in names_by_account(db).items():
            for name in names:
                people[name.casefold()] = uid
    assert people.get("fritz") == account.id
    found = intake_folder._candidates(tmp_path, people, set(), None)
    assert [(entry[2], entry[3]) for entry in found] == [(account.id, False)]


def test_my_intake_names_the_former_addresses(client: TestClient, operator: Account) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"mail_on": True, "mail_address": "papier@example.com"})
    rename(operator.id, "chef")
    seen = client.get("/api/v1/me/intake").json()
    assert seen["plus_address"] == "papier+chef@example.com"
    assert "papier+tester@example.com" in seen["former"]


# --- Counts and proven ------------------------------------------------------------------------------------------------


def test_an_address_without_a_mail_server_counts_but_the_intake_does_not_trust_it(
    client: TestClient, operator: Account
) -> None:
    answer = client.put("/api/v1/me/profile", json={"email": "tester@example.com", "password": PASSWORD})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["email"] == "tester@example.com" and body["email_counts"] is True and body["email_confirmed"] is False
    with SessionLocal() as db:
        assert mail_senders.owners(db, "tester@example.com") == set()
    # It counts: signing in with it works.
    with new_client() as browser:
        signed = browser.post("/api/v1/auth/login", json={"name": "tester@example.com", "password": PASSWORD})
        assert signed.status_code == 200, signed.text


def test_a_proven_address_lets_mail_into_the_vault(client: TestClient, operator: Account) -> None:
    with SessionLocal() as db:
        KontenStore(db).set_email(operator.id, "tester@example.com", confirmed=True, proven=True, source="")
        db.commit()
        assert operator.id in mail_senders.owners(db, "tester@example.com")


# --- The operator's list ----------------------------------------------------------------------------------------------


def test_the_list_has_what_the_module_s_list_needs(client: TestClient, operator: Account) -> None:
    other = make_account("gerd")
    with SessionLocal() as db:
        for account_id in (operator.id, other.id):
            row = db.get(Account, account_id)
            assert row is not None
            row.email = "same@example.com"
        db.commit()
    rows = {row["name"]: row for row in client.get("/api/v1/accounts").json()}
    assert rows["tester"]["self"] is True and rows["gerd"]["self"] is False
    assert rows["gerd"]["email_duplicate"] is True and rows["gerd"]["documents"] == 0
    assert "blocked_at" in rows["gerd"] and "email_counts" in rows["gerd"]


def test_the_operator_renames_with_the_own_password(client: TestClient, operator: Account) -> None:
    other = make_account("hans")
    wrong = client.put(f"/api/v1/accounts/{other.id}/name", json={"name": "hans2", "current_password": "x" * 12})
    assert wrong.status_code == 401
    done = client.put(f"/api/v1/accounts/{other.id}/name", json={"name": "hans2", "current_password": PASSWORD})
    assert done.status_code == 200 and done.json()["name"] == "hans2"
    shown = client.put(f"/api/v1/accounts/{other.id}/display-name",
                       json={"name": "Hans Zwei", "current_password": PASSWORD})
    assert shown.status_code == 200 and shown.json()["display_name"] == "Hans Zwei"
    with SessionLocal() as db:
        vault = db.query(Vault).filter_by(personal_of=other.id).one()
        # The folder on the disk never moves with the name.
        assert vault.folder == "hans"


def test_the_operator_takes_an_address_away_but_never_sets_one(client: TestClient, operator: Account) -> None:
    other = make_account("ida")
    with SessionLocal() as db:
        row = db.get(Account, other.id)
        assert row is not None
        row.email = "ida@example.com"
        db.commit()
    done = client.request("DELETE", f"/api/v1/accounts/{other.id}/email", json={"current_password": PASSWORD})
    assert done.status_code == 200, done.text
    assert done.json()["email"] == ""


def test_signing_out_everywhere_is_not_offered_at_the_own_account(client: TestClient, operator: Account) -> None:
    assert client.post(f"/api/v1/accounts/{operator.id}/sign-out").status_code == 409


def test_a_device_cannot_change_the_username(client: TestClient, operator: Account) -> None:
    token = redeem(show_code(client)["code"]).json()["token"]
    with program() as device:
        answer = device.put("/api/v1/me/profile", headers=bearer(token), json={"name": "other", "password": PASSWORD})
    assert answer.status_code == 403


# --- The update from 1.12.0 -------------------------------------------------------------------------------------------


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from sqlalchemy import create_engine

    path = tmp_path / "nexpaper.db"
    monkeypatch.setattr(database, "engine", create_engine(f"sqlite:///{path}"))
    made: list[str] = []
    monkeypatch.setattr(backups, "create", lambda **kwargs: made.append(kwargs.get("note", "")) or path)
    monkeypatch.setattr(database, "_made_backups", made, raising=False)
    return path


def test_a_database_of_1_12_0_gets_the_additions_and_keeps_the_second_factor_required(scratch: Path) -> None:
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "released" / "1.12.0.sql").read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version = 20")
        connection.execute(
            "INSERT INTO users (id, name, display_name, whats_new_seen, role, sign_in, password_hash, email, "
            "email_from_provider, oidc_subject, language, created_at, failed_logins, totp_secret_enc, totp_recovery, "
            "totp_last_step, signed_in_before, passkey_handle, ai_allowed) VALUES (1, 'anna', '', '', 'operator', "
            "'password', 'h', 'anna@example.com', 0, '', '', '2026-11-01 08:00:00', 0, '', '', 0, 1, '', 1)")
        connection.commit()
    database.init_db()
    assert database._made_backups == ["before the shared account module"]  # type: ignore[attr-defined]
    with closing(sqlite3.connect(scratch)) as connection:
        assert connection.execute("SELECT email_counts FROM users").fetchone() == (1,)
        assert connection.execute("SELECT value FROM settings WHERE key = 'two_factor_required'").fetchone() == (
            "true",)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"former_names", "setup_claims", "failed_unknown", "mail_outbox"} <= tables
    # A second start changes nothing and makes no other backup.
    database.init_db()
    assert database._made_backups == ["before the shared account module"]  # type: ignore[attr-defined]


def test_a_new_installation_requires_no_second_factor() -> None:
    assert settings_service.DEFAULTS["two_factor_required"] is False
    assert settings_service.DEFAULTS["passkeys_allowed"] is True


def test_the_profile_names_the_former_username(client: TestClient, operator: Account) -> None:
    rename(operator.id, "chef")
    with new_client() as browser:
        with SessionLocal() as db:
            row = db.get(Account, operator.id)
            assert row is not None
        sign_in(browser, row)
        assert browser.get("/api/v1/auth/me").json()["former_name"] == "tester"


# --- konten 0.3.10 ------------------------------------------------------------------------------------------------------


def test_the_password_s_last_change_is_kept_and_shown(client: TestClient, operator: Account) -> None:
    """``password_changed_at`` for "Zuletzt geändert am …" under Security: unknown for a password of 1.12.0, set by a
    change of the password."""
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None
        row.password_changed_at = None
        db.commit()
        assert KontenStore(db).get_account(operator.id).password_changed_at is None  # type: ignore[union-attr]
    assert client.get("/api/v1/auth/me").json()["password_changed_at"] is None
    changed = client.put("/api/v1/auth/password", json={"current": PASSWORD, "new": PASSWORD + " new",
                                                         "password_confirm": PASSWORD + " new"})
    assert changed.status_code in (200, 204), changed.text
    with SessionLocal() as db:
        assert KontenStore(db).get_account(operator.id).password_changed_at is not None  # type: ignore[union-attr]
    assert client.get("/api/v1/auth/me").json()["password_changed_at"]


def test_an_account_through_a_provider_only_is_asked_no_second_factor_of_its_own() -> None:
    """The store's hook ``provider_checks_factor`` (konten 0.3.10): "Require a second factor" does not reach an account
    without a password here; its provider brings the factor (as in 1.12.0). One with a password is asked."""
    from app.models import SIGN_IN_OIDC
    from app.vendor import nexkonten

    with SessionLocal() as db:
        settings_service.save(db, {"two_factor_required": True})
    member = make_account("anna")
    provider = make_account("pia")
    with SessionLocal() as db:
        row = db.get(Account, provider.id)
        assert row is not None
        row.sign_in, row.password_hash = SIGN_IN_OIDC, ""
        db.commit()
        store = KontenStore(db)
        assert store.provider_checks_factor(provider.id) is True
        assert store.provider_checks_factor(member.id) is False
        assert store.second_factor(provider.id) == nexkonten.SECOND_FACTOR_NONE
        assert store.second_factor(member.id) == nexkonten.SECOND_FACTOR_REQUIRED


def test_a_refusal_under_1_12_0_s_code_names_the_module_s_too(client: TestClient, operator: Account) -> None:
    """``account_code`` beside the old code (``AccountError.as_dict``, konten 0.3.10): the pages say the module's
    sentence where the answer keeps 1.12.0's name."""
    taken = make_account("anna")
    assert taken.id
    answer = client.put("/api/v1/me/profile", json={"name": "anna", "password": PASSWORD})
    detail = answer.json()["detail"]
    assert (answer.status_code, detail["code"], detail["account_code"]) == (409, "name_taken", "username_taken")

