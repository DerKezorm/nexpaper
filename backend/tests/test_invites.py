"""Invitations into nexpaper and blocking an account: both the operator's alone."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, AuthSession

from .conftest import PASSWORD, make_account, new_client


def _token(link: str) -> str:
    return link.rsplit("/", 1)[1]


def test_an_invitation_makes_one_account_and_works_once(client: TestClient, operator: Account) -> None:
    made = client.post("/api/v1/invites", json={"days": 7})
    assert made.status_code == 201, made.text
    token = _token(made.json()["link"])
    with new_client() as visitor:
        assert visitor.get(f"/api/v1/invite/{token}").json()["signed_in_as"] is None
        joined = visitor.post(f"/api/v1/invite/{token}", json={"name": "mia", "password": PASSWORD})
        assert joined.status_code == 200, joined.text
        assert joined.json()["name"] == "mia" and joined.json()["role"] == "member"
        assert visitor.get("/api/v1/auth/me").json()["name"] == "mia"
    with new_client() as second:
        assert second.get(f"/api/v1/invite/{token}").status_code == 404
        again = second.post(f"/api/v1/invite/{token}", json={"name": "tom", "password": PASSWORD})
        assert again.status_code == 404 and again.json()["detail"]["code"] == "invite_invalid"


def test_only_the_operator_invites(client: TestClient, operator: Account) -> None:
    with new_client(make_account("tom")) as tom:
        assert tom.post("/api/v1/invites", json={"days": 7}).status_code == 403
        assert tom.get("/api/v1/invites").status_code == 403
    assert client.post("/api/v1/invites", json={"days": 3}).json()["detail"]["code"] == "invalid_days"


def test_one_link_per_address_and_a_withdrawn_one_is_gone(client: TestClient, operator: Account) -> None:
    first = client.post("/api/v1/invites", json={"days": 7, "email": "a@example.com"})
    second = client.post("/api/v1/invites", json={"days": 30, "email": "A@example.com"})
    assert first.status_code == second.status_code == 201
    assert [i["id"] for i in client.get("/api/v1/invites").json()] == [second.json()["id"]], "the second replaced the first"
    with new_client() as visitor:
        assert visitor.get(f"/api/v1/invite/{_token(first.json()['link'])}").status_code == 404
    assert client.delete(f"/api/v1/invites/{second.json()['id']}").status_code == 204
    assert client.get("/api/v1/invites").json() == []
    with new_client() as visitor:
        assert visitor.get(f"/api/v1/invite/{_token(second.json()['link'])}").status_code == 404


def test_the_operator_blocks_an_account_and_lets_it_in_again(client: TestClient, operator: Account) -> None:
    rita = make_account("rita")
    assert client.post(f"/api/v1/accounts/{rita.id}/block", json={"current_password": "wrong"}).status_code == 401
    assert client.post(f"/api/v1/accounts/{operator.id}/block", json={"current_password": PASSWORD}).status_code == 409
    with new_client(rita) as browser:
        assert browser.get("/api/v1/auth/me").status_code == 200
        assert client.post(f"/api/v1/accounts/{rita.id}/block", json={"current_password": PASSWORD}).status_code == 204
        assert browser.get("/api/v1/auth/me").status_code == 401, "the open session ends with the block"
    with SessionLocal() as db:
        assert db.query(AuthSession).filter_by(account_id=rita.id).count() == 0, "and is gone, not only refused"
    with new_client() as stranger:
        assert stranger.post("/api/v1/auth/login", json={"name": "rita", "password": PASSWORD}).status_code == 401
    assert client.post(f"/api/v1/accounts/{rita.id}/unblock", json={"current_password": PASSWORD}).status_code == 204
    with SessionLocal() as db:
        assert db.get(Account, rita.id).blocked_at is None  # type: ignore[union-attr]
    with new_client() as stranger:
        assert stranger.post("/api/v1/auth/login", json={"name": "rita", "password": PASSWORD}).status_code == 200


def test_two_people_on_one_link_at_the_same_moment_make_one_account(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from app.services import accounts

    token = _token(client.post("/api/v1/invites", json={"days": 7}).json()["link"])
    # Both have found the invitation valid before either takes it: they meet between looking and taking.
    both_found = threading.Barrier(2, timeout=10)
    check_name = accounts.check_name

    met: set[str] = set()

    def meet_then_check(db: object, name: str) -> str:
        # The name is checked again when the account is made; only the first check is the meeting point.
        if name not in met:
            met.add(name)
            both_found.wait()
        return check_name(db, name)

    monkeypatch.setattr(accounts, "check_name", meet_then_check)
    answers: list[int] = []

    def accept(name: str) -> None:
        # Without "with": the app's start and stop are the test client's business, not each visitor's.
        visitor = new_client()
        answers.append(visitor.post(f"/api/v1/invite/{token}", json={"name": name, "password": PASSWORD}).status_code)

    threads = [threading.Thread(target=accept, args=(name,)) for name in ("lena", "paul")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(answers) == [200, 404], answers
    with SessionLocal() as db:
        assert db.query(Account).filter(Account.name.in_(["lena", "paul"])).count() == 1
