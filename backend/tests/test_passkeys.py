"""Passkeys, against a software authenticator that signs for real (ES256), as in nextrmnl: adding one needs the
password, signing in with one needs neither password nor code, the relying party comes from the public address and
never from the Host header, a wrong origin or name, a challenge used twice and a counter that goes back are refused,
and a passkey counts as a second factor."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import struct

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Account
from app.security import SESSION_COOKIE, brake
from app.services import settings_service

from .conftest import PASSWORD, TAB, make_account, require_second_factor, sign_in

ORIGIN = "https://paper.example.com"
RP_ID = "paper.example.com"
#: Built at run time, so the secret scanner does not take a test value for a real password.
WRONG = PASSWORD[::-1]


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class SoftKey:
    """A passkey in software: one ES256 key pair, a counter, the user handle it was made for, and the two ceremonies
    of WebAuthn. It always says the user was verified (finger, face or PIN)."""

    def __init__(self, origin: str = ORIGIN, rp_id: str = RP_ID, verified: bool = True) -> None:
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(32)
        self.counter = 0
        self.origin, self.rp_id, self.verified = origin, rp_id, verified
        self.handle = b""

    def _cose(self) -> bytes:
        numbers = self.private.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def _auth_data(self, attested: bool) -> bytes:
        flags = 0x01 | (0x04 if self.verified else 0) | (0x40 if attested else 0)
        data = hashlib.sha256(self.rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", self.counter)
        if attested:
            data += bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + self._cose()
        return data

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}).encode()

    def create(self, options: dict) -> dict:
        self.handle = base64.urlsafe_b64decode(options["user"]["id"] + "=" * (-len(options["user"]["id"]) % 4))
        client_data = self._client_data("webauthn.create", options["challenge"])
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": self._auth_data(True)})
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {"clientDataJSON": b64(client_data), "attestationObject": b64(attestation),
                         "transports": ["internal"]},
            "clientExtensionResults": {},
        }

    def get(self, options: dict, counter: int | None = None, handle: bytes | None = None) -> dict:
        self.counter = self.counter + 1 if counter is None else counter
        client_data = self._client_data("webauthn.get", options["challenge"])
        auth_data = self._auth_data(False)
        signature = self.private.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(client_data),
                "authenticatorData": b64(auth_data),
                "signature": b64(signature),
                "userHandle": b64(self.handle if handle is None else handle),
            },
            "clientExtensionResults": {},
        }


@pytest.fixture(autouse=True)
def _public_address() -> None:
    """Passkeys follow the public address the operator set."""
    with SessionLocal() as db:
        settings_service.save(db, {"public_url": ORIGIN})


def browser(host: str = "203.0.113.5") -> TestClient:
    return TestClient(app, base_url="http://testserver", headers=TAB, client=(host, 50000))


def add_key(client: TestClient, key: SoftKey, name: str = "Laptop", password: str = PASSWORD):
    begun = client.post("/api/v1/auth/passkeys/begin")
    assert begun.status_code == 200, begun.text
    options = json.loads(begun.json()["options"])
    return client.post("/api/v1/auth/passkeys", json={"name": name, "password": password, "credential": key.create(options)})


def passkey_sign_in(client: TestClient, key: SoftKey, **kwargs):
    begun = client.post("/api/v1/auth/passkey/begin")
    assert begun.status_code == 200, begun.text
    options = json.loads(begun.json()["options"])
    return client.post("/api/v1/auth/passkey", json={"credential": key.get(options, **kwargs)}), options


def test_adding_a_passkey_needs_the_password_and_asks_for_a_discoverable_verified_key(
    client: TestClient, operator: Account
) -> None:
    begun = client.post("/api/v1/auth/passkeys/begin", headers={"Host": "evil.example.net"})
    options = json.loads(begun.json()["options"])
    # The name of the site comes from the public address, never from the Host header.
    assert options["rp"]["id"] == RP_ID and options["user"]["name"] == "tester"
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    key = SoftKey()
    refused = client.post("/api/v1/auth/passkeys", json={"name": "x", "password": WRONG, "credential": key.create(options)})
    assert refused.status_code == 401 and refused.json()["detail"]["code"] == "wrong_password"
    added = add_key(client, key, "Windows Hello")
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["passkey"]["name"] == "Windows Hello" and len(body["recovery_codes"]) == 8
    assert body["account"]["two_factor"] is True and body["account"]["passkeys"] == 1 and body["account"]["totp"] is False
    listed = client.get("/api/v1/auth/passkeys").json()
    assert [row["name"] for row in listed] == ["Windows Hello"] and "public_key" not in json.dumps(listed)
    assert listed[0]["last_used_at"] is None and listed[0]["created_at"]
    # The same key twice is refused (the browser would not offer it, excludeCredentials).
    again = add_key(client, key)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "passkey_exists"


def test_a_passkey_signs_in_without_password_and_code(client: TestClient, operator: Account) -> None:
    key = SoftKey()
    add_key(client, key)
    stranger = browser()
    answer, options = passkey_sign_in(stranger, key)
    assert options["userVerification"] == "required" and options.get("allowCredentials", []) == []
    assert answer.status_code == 200, answer.text
    assert answer.json()["name"] == "tester" and answer.json()["session_stage"] == "full"
    assert stranger.get("/api/v1/devices").status_code == 200
    used = client.get("/api/v1/auth/passkeys").json()[0]
    assert used["last_used_at"] is not None


def test_a_passkey_of_an_account_with_required_second_factor_is_enough(client: TestClient, operator: Account) -> None:
    key = SoftKey()
    add_key(client, key)
    require_second_factor()
    # A password sign-in now waits for a second factor and says a passkey would do.
    other = browser()
    first = other.post("/api/v1/auth/login", json={"name": "tester", "password": PASSWORD})
    assert first.json()["second_factor"] is True and first.json()["passkey"] is True and first.json()["totp"] is False
    answer, _ = passkey_sign_in(other, key)
    assert answer.status_code == 200 and answer.json()["session_stage"] == "full"
    # The waiting sign-in is done with.
    assert other.post("/api/v1/auth/login/totp", json={"code": "000000"}).json()["detail"]["code"] == "second_factor_expired"


@pytest.mark.parametrize(
    ("origin", "rp_id"),
    [("https://evil.example.net", RP_ID), (ORIGIN, "evil.example.net"), ("http://paper.example.com", RP_ID)],
)
def test_a_wrong_origin_or_site_name_is_refused(client: TestClient, operator: Account, origin: str, rp_id: str) -> None:
    key = SoftKey()
    add_key(client, key)
    key.origin, key.rp_id = origin, rp_id
    answer, _ = passkey_sign_in(browser(), key)
    assert answer.status_code == 401 and answer.json()["detail"]["code"] == "passkey_refused"


def test_a_challenge_counts_once(client: TestClient, operator: Account) -> None:
    key = SoftKey()
    add_key(client, key)
    other = browser()
    begun = other.post("/api/v1/auth/passkey/begin")
    options = json.loads(begun.json()["options"])
    answer = key.get(options)
    assert other.post("/api/v1/auth/passkey", json={"credential": answer}).status_code == 200
    # The same signed answer again, even with the cookie put back: the challenge is spent.
    replay = browser()
    replay.cookies.set("nexpaper_pk", begun.cookies.get("nexpaper_pk") or "")
    again = replay.post("/api/v1/auth/passkey", json={"credential": key.get(options)})
    assert again.status_code == 401
    # And a challenge is bound to the browser that asked: another one's answer does not open with it.
    third = browser()
    assert third.post("/api/v1/auth/passkey", json={"credential": key.get(options)}).status_code == 401


def test_a_counter_that_goes_back_is_refused_as_a_copied_key(
    client: TestClient, operator: Account, caplog: pytest.LogCaptureFixture
) -> None:
    key = SoftKey()
    add_key(client, key)
    assert passkey_sign_in(browser(), key, counter=5)[0].status_code == 200
    with caplog.at_level(logging.WARNING, logger="nexpaper.auth"):
        copied, _ = passkey_sign_in(browser("203.0.113.6"), key, counter=3)
    assert copied.status_code == 401
    assert "copied key" in caplog.text
    assert passkey_sign_in(browser("203.0.113.7"), key, counter=6)[0].status_code == 200


def test_a_key_without_user_verification_or_with_another_accounts_handle_is_refused(
    client: TestClient, operator: Account
) -> None:
    key = SoftKey()
    add_key(client, key)
    assert passkey_sign_in(browser(), key, handle=b"someone else")[0].status_code == 401
    key.verified = False
    assert passkey_sign_in(browser("203.0.113.8"), key)[0].status_code == 401


def test_an_unknown_passkey_lets_nobody_in(client: TestClient, operator: Account) -> None:
    answer, _ = passkey_sign_in(browser(), SoftKey())
    assert answer.status_code == 401 and answer.json()["detail"]["code"] == "passkey_refused"


def test_failed_passkeys_count_per_address_and_per_account(client: TestClient, operator: Account) -> None:
    key = SoftKey()
    add_key(client, key)
    key.origin = "https://evil.example.net"
    guesser = browser("203.0.113.9")
    for _ in range(5):
        assert passkey_sign_in(guesser, key)[0].status_code == 401
    assert guesser.post("/api/v1/auth/passkey/begin").status_code == 429
    with SessionLocal() as db:
        row = db.get(Account, operator.id)
        assert row is not None and row.locked_until is not None
    # A locked account does not open with its passkey from a stranger's browser either.
    brake.forget()
    key.origin = ORIGIN
    assert passkey_sign_in(browser("203.0.113.10"), key)[0].status_code == 401


def test_without_a_public_address_only_localhost(client: TestClient, operator: Account) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"public_url": ""})
    begun = client.post("/api/v1/auth/passkeys/begin", headers={"Host": "paper.example.com"})
    options = json.loads(begun.json()["options"])
    assert options["rp"]["id"] == "localhost"
    key = SoftKey(origin="http://localhost:8560", rp_id="localhost")
    assert client.post("/api/v1/auth/passkeys", json={"password": PASSWORD, "credential": key.create(options)}).status_code == 201
    assert passkey_sign_in(browser(), key)[0].status_code == 200
    # Another origin than localhost does not pass, whatever it calls itself.
    key.origin = "http://192.0.2.1:8560"
    assert passkey_sign_in(browser("203.0.113.11"), key)[0].status_code == 401
    # A public address without https: browsers offer no passkeys there, and nexpaper says so.
    with SessionLocal() as db:
        settings_service.save(db, {"public_url": "http://paper.example.com"})
    refused = client.post("/api/v1/auth/passkeys/begin")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "passkeys_need_https"
    assert client.get("/api/v1/auth/methods").json()["passkeys"] is False


def test_removing_needs_the_password_and_the_last_factor_stays_where_one_is_required(
    client: TestClient, operator: Account
) -> None:
    key = SoftKey()
    add_key(client, key)
    uid = client.get("/api/v1/auth/passkeys").json()[0]["id"]
    require_second_factor()
    wrong = client.post(f"/api/v1/auth/passkeys/{uid}/remove", json={"password": WRONG})
    assert wrong.status_code == 401
    last = client.post(f"/api/v1/auth/passkeys/{uid}/remove", json={"password": PASSWORD})
    assert last.status_code == 409 and last.json()["detail"]["code"] == "second_factor_required"
    require_second_factor(False)
    gone = client.post(f"/api/v1/auth/passkeys/{uid}/remove", json={"password": PASSWORD})
    assert gone.status_code == 200 and gone.json()["two_factor"] is False
    assert gone.json()["two_factor_recovery_left"] == 0
    assert passkey_sign_in(browser(), key)[0].status_code == 401


def test_nobody_removes_another_accounts_passkey(client: TestClient, operator: Account) -> None:
    add_key(client, SoftKey())
    uid = client.get("/api/v1/auth/passkeys").json()[0]["id"]
    anna = browser()
    sign_in(anna, make_account("anna"))
    assert anna.post(f"/api/v1/auth/passkeys/{uid}/remove", json={"password": PASSWORD}).status_code == 404
    assert len(client.get("/api/v1/auth/passkeys").json()) == 1


def test_a_passkey_set_up_right_after_the_password_needs_no_password_again() -> None:
    require_second_factor()
    make_account("anna")
    other = browser()
    first = other.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD})
    assert first.json()["session_stage"] == "setup"
    key = SoftKey()
    added = add_key(other, key, password="")
    assert added.status_code == 201 and len(added.json()["recovery_codes"]) == 8
    assert other.get("/api/v1/auth/me").json()["session_stage"] == "codes"
    assert other.post("/api/v1/auth/setup/done").status_code == 200
    assert other.get("/api/v1/auth/me").json()["session_stage"] == "full"
    assert other.cookies.get(SESSION_COOKIE)


def test_the_operator_reset_takes_the_passkeys_too(client: TestClient, operator: Account) -> None:
    anna = browser()
    member = make_account("anna")
    sign_in(anna, member)
    key = SoftKey()
    assert add_key(anna, key).status_code == 201
    reset = client.post(f"/api/v1/accounts/{member.id}/totp/reset", json={"current_password": PASSWORD})
    assert reset.status_code == 200 and reset.json()["two_factor"] is False and reset.json()["passkeys"] == 0
    assert passkey_sign_in(browser("203.0.113.12"), key)[0].status_code == 401


# --- Challenges: nobody who is not signed in crowds out the rest --------------------------------------------------


def test_a_sender_holds_a_limited_number_of_open_sign_in_challenges(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import passkeys as service

    monkeypatch.setattr(service, "BEGINS_PER_ADDRESS", 1000)
    greedy = browser("203.0.113.150")
    answers = [greedy.post("/api/v1/auth/passkey/begin").status_code for _ in range(service.PER_ADDRESS + 3)]
    assert answers[: service.PER_ADDRESS] == [200] * service.PER_ADDRESS
    assert set(answers[service.PER_ADDRESS :]) == {429}
    # Another sender is not in the way of it.
    assert browser("203.0.113.151").post("/api/v1/auth/passkey/begin").status_code == 200
    # A challenge that is used (or has run out) makes room again.
    service.forget()
    assert greedy.post("/api/v1/auth/passkey/begin").status_code == 200


def test_asking_for_challenges_counts_for_the_sender_apart_from_failed_passwords(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import passkeys as service

    monkeypatch.setattr(service, "PER_ADDRESS", 1000)
    make_account("anna")
    greedy = browser("203.0.113.152")
    answers = [greedy.post("/api/v1/auth/passkey/begin").status_code for _ in range(service.BEGINS_PER_ADDRESS + 2)]
    assert answers[: service.BEGINS_PER_ADDRESS] == [200] * service.BEGINS_PER_ADDRESS
    assert answers[-1] == 429
    rested = greedy.post("/api/v1/auth/passkey/begin")
    assert rested.headers["retry-after"] == "900"
    # Asking for challenges is not a failed sign-in: the password still works from the same address.
    assert greedy.post("/api/v1/auth/login", json={"name": "anna", "password": PASSWORD}).status_code == 200


def test_a_flood_of_sign_in_challenges_leaves_adding_and_confirming_alone(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import passkeys as service

    monkeypatch.setattr(service, "MAX_ANONYMOUS", 30)
    monkeypatch.setattr(service, "PER_ADDRESS", 3)
    key = SoftKey()
    adding = json.loads(client.post("/api/v1/auth/passkeys/begin").json()["options"])
    created = key.create(adding)
    # Fills the store of the sign-ins up to its end, from many senders, and past it.
    for number in range(60):
        brake.forget()
        assert browser(f"198.51.100.{number + 1}").post("/api/v1/auth/passkey/begin").status_code == 200
    assert len(service._anonymous) <= 30
    # The signed-in person finishes what they began, and can begin again.
    done = client.post("/api/v1/auth/passkeys", json={"name": "Laptop", "password": PASSWORD, "credential": created})
    assert done.status_code == 201, done.text
    again = client.post("/api/v1/auth/passkeys/begin")
    assert again.status_code == 200
    # And a sign-in of a new sender is not turned away while the store is full: the oldest made room.
    brake.forget()
    assert browser("198.51.100.200").post("/api/v1/auth/passkey/begin").status_code == 200


def test_the_challenges_of_one_account_do_not_crowd_out_another(
    client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import passkeys as service

    monkeypatch.setattr(service, "PER_ACCOUNT", 3)
    anna = browser()
    member = make_account("anna")
    sign_in(anna, member)
    options = json.loads(anna.post("/api/v1/auth/passkeys/begin").json()["options"])
    # The operator asks over and over, from many sessions of their own: only their own place fills.
    for number in range(6):
        extra = browser(f"203.0.113.{170 + number}")
        sign_in(extra, operator)
        assert extra.post("/api/v1/auth/passkeys/begin").status_code == 200
    assert len(service._accounts[operator.id]) == 3
    key = SoftKey()
    done = anna.post("/api/v1/auth/passkeys", json={"name": "Phone", "password": PASSWORD, "credential": key.create(options)})
    assert done.status_code == 201, done.text


def test_the_passkey_button_is_offered_without_a_public_address_only_on_localhost(
    client: TestClient, operator: Account
) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"public_url": ""})

    def offered(host: str) -> bool:
        return bool(client.get("/api/v1/auth/methods", headers={"Host": host}).json()["passkeys"])

    assert offered("localhost:8560") is True and offered("localhost") is True
    for host in ("testserver", "192.168.1.20:8560", "paper.example.com", "127.0.0.1:8560", "localhost.example.com"):
        assert offered(host) is False, host
    # With a public https address the name in the request does not matter: the address is the one passkeys are for.
    with SessionLocal() as db:
        settings_service.save(db, {"public_url": ORIGIN})
    assert offered("192.168.1.20:8560") is True
    with SessionLocal() as db:
        settings_service.save(db, {"public_url": "http://paper.example.com"})
    assert offered("localhost:8560") is False
