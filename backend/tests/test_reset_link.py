"""``python -m app.reset_link``: the way back in for an operator who forgot their own password on a server without mail
(#job-215). The link it prints is the one the interface makes (``services/resets.py``): once, 24 hours, the lock lifted,
the second factor kept, a line in the log without the link."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

from app import reset_link
from app.db import SessionLocal
from app.models import OPERATOR, Account, PasswordReset, utcnow
from app.services import logs, resets, settings_service

from .conftest import make_account, require_second_factor
from .test_password_links import NEW, PUBLIC, stranger, token_of


@pytest.fixture(autouse=True)
def not_root(monkeypatch: pytest.MonkeyPatch) -> None:
    # The tests run as whoever runs them; root is a case of its own below.
    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = reset_link.main(list(args))
    out, err = capsys.readouterr()
    return code, out.strip(), err


def links() -> int:
    with SessionLocal() as db:
        return db.query(PasswordReset).count()


def test_a_locked_out_operator_gets_a_link_that_works_once(capsys: pytest.CaptureFixture[str]) -> None:
    require_second_factor(False)
    boss = make_account("boss", role=OPERATOR)
    with SessionLocal() as db:
        row = db.get(Account, boss.id)
        assert row is not None
        row.failed_logins = 5
        row.locked_until = utcnow() + timedelta(minutes=15)
        db.commit()
    code, out, err = run(capsys, "Boss")
    assert code == 0, err
    assert out.startswith("/reset/"), "without a public address only the path"
    assert "recovery codes" in err and "24 hours" in err
    token = token_of(out)
    assert stranger().get(f"/api/v1/reset/{token}").json()["name"] == "boss"
    assert stranger().post(f"/api/v1/reset/{token}", json={"password": NEW}).status_code == 204
    assert stranger("203.0.113.50").post("/api/v1/auth/login", json={"name": "boss", "password": NEW}).status_code == 200
    # Once only.
    again = stranger("203.0.113.51").post(f"/api/v1/reset/{token}", json={"password": "another long one"})
    assert again.status_code == 404 and links() == 0


def test_the_link_runs_out_after_24_hours(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    make_account("boss", role=OPERATOR)
    _, out, _ = run(capsys, "boss")
    with SessionLocal() as db:
        row = db.query(PasswordReset).one()
        lasts = row.expires_at - row.created_at
    assert timedelta(hours=23, minutes=59) <= lasts <= timedelta(hours=24)
    later = utcnow() + timedelta(hours=24, minutes=1)
    monkeypatch.setattr(resets, "utcnow", lambda: later)
    assert stranger().get(f"/api/v1/reset/{token_of(out)}").status_code == 404
    assert stranger("203.0.113.52").post(f"/api/v1/reset/{token_of(out)}", json={"password": NEW}).status_code == 404


def test_with_a_public_address_the_whole_link(capsys: pytest.CaptureFixture[str]) -> None:
    make_account("boss", role=OPERATOR)
    with SessionLocal() as db:
        settings_service.save(db, {"public_url": PUBLIC})
    code, out, _ = run(capsys, "boss")
    assert code == 0 and out.startswith(f"{PUBLIC}/reset/")


def test_a_new_link_replaces_the_one_before(capsys: pytest.CaptureFixture[str]) -> None:
    make_account("boss", role=OPERATOR)
    _, first, _ = run(capsys, "boss")
    _, second, _ = run(capsys, "boss")
    assert first != second and links() == 1
    assert stranger().get(f"/api/v1/reset/{token_of(first)}").status_code == 404
    assert stranger().get(f"/api/v1/reset/{token_of(second)}").status_code == 200


def test_as_root_nothing_is_made(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    make_account("boss", role=OPERATOR)
    monkeypatch.setattr(os, "getuid", lambda: 0, raising=False)
    code, out, err = run(capsys, "boss")
    assert code == 2 and out == "" and "-u nexpaper" in err and "gosu nexpaper" in err
    assert links() == 0


def test_an_unknown_name_says_which_there_are(capsys: pytest.CaptureFixture[str]) -> None:
    make_account("boss", role=OPERATOR)
    make_account("anna")
    code, out, err = run(capsys, "bos")
    assert code == 1 and out == "" and "No account named 'bos'" in err and "anna, boss" in err
    assert links() == 0


def test_without_a_name_the_accounts_are_listed(capsys: pytest.CaptureFixture[str]) -> None:
    make_account("boss", role=OPERATOR)
    make_account("anna")
    code, out, _ = run(capsys)
    assert code == 0 and out.splitlines() == ["anna  (member)", "boss  (operator)"]
    assert links() == 0


def test_a_blocked_account_gets_no_link(capsys: pytest.CaptureFixture[str]) -> None:
    anna = make_account("anna")
    with SessionLocal() as db:
        row = db.get(Account, anna.id)
        assert row is not None
        row.blocked_at = utcnow()
        db.commit()
    code, out, err = run(capsys, "anna")
    assert code == 1 and out == "" and "blocked" in err
    assert links() == 0


def test_with_passwords_off_only_an_operator_gets_one(capsys: pytest.CaptureFixture[str]) -> None:
    make_account("boss", role=OPERATOR)
    make_account("anna")
    with SessionLocal() as db:
        settings_service.save(db, {"password_login": False})
    assert run(capsys, "anna")[0] == 1
    assert run(capsys, "boss")[0] == 0


def test_the_log_names_the_command_and_never_the_token(capsys: pytest.CaptureFixture[str]) -> None:
    make_account("boss", role=OPERATOR)
    _, out, _ = run(capsys, "boss")
    text = logs.log_file().read_text(encoding="utf-8")
    assert "Password link made on the server with python -m app.reset_link name=boss" in text
    assert token_of(out) not in text
