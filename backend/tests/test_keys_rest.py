"""Bauplan E41: an account's own API keys rest while it is blocked or deleted and count again when it is back; only the
end of the 30 days removes them. Since konten 1.1.5 and geraete 0.1.0 (G26) its paired devices do the same: they rest
while the account is out and work again when it is back, without pairing anew (before, a block revoked them for good)."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account, ApiKey, Device
from app.security import brake
from app.services import apikeys, brakes, devices
from app.services.konten_store import KontenStore
from app.vendor.nexkonten import manage

from .conftest import PASSWORD, make_account, new_client


def reads(token: str) -> int:
    """An API key reads ``/api/v1/me``, a paired device its reminders (a key may not, a device may)."""
    apikeys.forget()
    brake.forget()
    brakes.forget()
    path = "/api/v1/me" if token.startswith("npk_") else "/api/v1/me/reminders"
    with new_client() as program:
        return program.get(path, headers={"Authorization": f"Bearer {token}"}).status_code


def test_keys_rest_while_the_account_is_out_and_go_only_with_it(client: TestClient, operator: Account) -> None:
    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
    jule = make_account("jule")
    with SessionLocal() as db:
        row = db.get(Account, jule.id)
        assert row is not None
        key, token = apikeys.make(db, row, "script", "upload")
        device, device_token = devices.make(db, row, "iPhone")
        key_id, device_id = key.id, device.id
    assert reads(token) == 200 and reads(device_token) == 200
    password = {"current_password": PASSWORD}

    # Blocked: the key rests, and so does the device (G26).
    assert client.post(f"/api/v1/accounts/{jule.id}/block", json=password).status_code == 204
    assert reads(token) == 401 and reads(device_token) == 401
    with SessionLocal() as db:
        assert db.get(ApiKey, key_id) is not None, "a block keeps the key"
        assert db.get(Device, device_id).revoked_at is None, "a block keeps the device"  # type: ignore[union-attr]
    # Unblocked: the key and the device count again.
    assert client.post(f"/api/v1/accounts/{jule.id}/unblock", json=password).status_code == 204
    assert reads(token) == 200 and reads(device_token) == 200

    # Deleted: the key rests again; brought back within the 30 days it counts again.
    gone = client.request("DELETE", f"/api/v1/accounts/{jule.id}",
                          json={**password, "confirm_name": "jule", "documents": "delete_documents"})
    assert gone.status_code == 204, gone.text
    assert reads(token) == 401
    assert reads(device_token) == 401
    assert client.post(f"/api/v1/accounts/{jule.id}/restore", json=password).status_code == 200
    assert reads(token) == 200 and reads(device_token) == 200

    # Deleted again and the 30 days over: only now the key goes, with the account.
    assert client.request("DELETE", f"/api/v1/accounts/{jule.id}",
                          json={**password, "confirm_name": "jule", "documents": "delete_documents"}).status_code == 204
    with SessionLocal() as db:
        row = db.get(Account, jule.id)
        assert row is not None and row.deleted_at is not None
        moved = row.deleted_at - timedelta(days=31)
        if row.blocked_at == row.deleted_at:
            row.blocked_at = moved
        row.deleted_at = moved
        db.commit()
        assert db.get(ApiKey, key_id) is not None, "the key rests until the end of the 30 days"
    with SessionLocal() as db:
        manage.purge_due(KontenStore(db))
        db.commit()
    with SessionLocal() as db:
        assert db.get(Account, jule.id) is None
        assert db.get(ApiKey, key_id) is None, "the end of the 30 days removes the key"
    assert reads(token) == 401
