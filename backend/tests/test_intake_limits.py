"""The limits on what comes in: the operator sets them, they count at once, and a value outside the range is no value."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.models import Account
from app.services import limits, settings_service

from . import files
from .conftest import make_account, new_client
from .intake import limit, post_files, upload_one

DEFAULTS = {
    "upload_max_mb": 200, "upload_max_pages": 2000, "upload_max_megapixels": 100, "upload_open_count": 10,
    "upload_open_mb": 4096, "process_timeout_seconds": 300, "process_memory_mb": 2048, "cache_max_mb": 1024,
}


def test_the_settings_carry_the_limits_with_sensible_values_from_the_start(client: TestClient, operator: Account) -> None:
    shown = client.get("/api/v1/settings").json()
    assert {key: shown[key] for key in DEFAULTS} == DEFAULTS


def test_the_operator_changes_them_and_they_count_at_the_next_request(client: TestClient, operator: Account) -> None:
    changed = client.put("/api/v1/settings", json={"upload_max_mb": 1, "upload_max_pages": 7, "upload_max_megapixels": 3,
                                                   "upload_open_count": 2, "upload_open_mb": 50,
                                                   "process_timeout_seconds": 60, "process_memory_mb": 0})
    assert changed.status_code == 200
    with SessionLocal() as db:
        current = limits.current(db)
    assert (current.max_file, current.max_pages, current.max_pixels, current.open_count, current.open_bytes) == (
        1024 * 1024, 7, 3_000_000, 2, 50 * 1024 * 1024)
    assert (current.timeout_seconds, current.memory_mb) == (60, 0)
    assert current.max_request == 10 * 1024 * 1024 + 1024 * 1024
    big = files.make_pdf(["x"]) + b"\n%" + b"0" * (1024 * 1024 + 10)
    assert post_files(client, ("big.pdf", big)).status_code == 413
    assert client.put("/api/v1/settings", json={"upload_max_mb": 5}).status_code == 200
    assert post_files(client, ("big.pdf", big)).status_code == 201


@pytest.mark.parametrize("body", [
    {"upload_max_mb": 0}, {"upload_max_mb": 10241}, {"upload_max_mb": -1}, {"upload_max_mb": "200"},
    {"upload_max_pages": 0}, {"upload_max_pages": 20001}, {"upload_max_megapixels": 0}, {"upload_max_megapixels": 1001},
    {"upload_open_count": 0}, {"upload_open_count": 101}, {"upload_open_mb": 0}, {"process_timeout_seconds": 4},
    {"process_timeout_seconds": 86401}, {"process_memory_mb": -1}, {"process_memory_mb": 65537}, {"process_memory_mb": 100}, {"cache_max_mb": 63},
], ids=lambda b: "-".join(f"{k}={v}" for k, v in b.items()))
def test_a_limit_outside_its_range_is_refused_and_changes_nothing(client: TestClient, operator: Account,
                                                                  body: dict[str, object]) -> None:
    assert client.put("/api/v1/settings", json=body).status_code == 422
    shown = client.get("/api/v1/settings").json()
    assert {key: shown[key] for key in DEFAULTS} == DEFAULTS


def test_only_the_operator_in_a_browser_sets_limits(client: TestClient, operator: Account) -> None:
    with new_client(make_account("lea")) as member:
        assert member.put("/api/v1/settings", json={"upload_max_mb": 5}).status_code == 403
        assert member.get("/api/v1/settings").status_code == 403
        assert member.get("/api/v1/settings/queue").status_code == 403
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(client.app, base_url="http://testserver") as device:
        auth = {"Authorization": f"Bearer {token}"}
        assert device.put("/api/v1/settings", json={"upload_max_mb": 5}, headers=auth).status_code == 403
        assert device.get("/api/v1/settings/queue", headers=auth).status_code == 403
    assert client.get("/api/v1/settings").json()["upload_max_mb"] == 200


def test_a_value_the_database_holds_outside_the_range_is_pulled_back_not_trusted(client: TestClient,
                                                                                 operator: Account) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"upload_max_mb": 10**9, "upload_max_pages": -5, "process_memory_mb": "lots",
                                   "upload_open_count": None})
        current = limits.current(db)
    assert current.max_file == 10240 * 1024 * 1024 and current.max_pages == 1
    assert current.memory_mb == DEFAULTS["process_memory_mb"] and current.open_count == DEFAULTS["upload_open_count"]
    with SessionLocal() as db:
        settings_service.save(db, {"process_memory_mb": 100})
        assert limits.current(db).memory_mb == limits.MEMORY_FLOOR


def test_the_queue_says_how_many_documents_are_read_and_wait(client: TestClient, operator: Account) -> None:
    assert client.get("/api/v1/settings/queue").json() == {"running": 0, "waiting": 0}
    upload_one(client, "a.pdf", files.make_pdf(["a"]))
    upload_one(client, "b.pdf", files.make_pdf(["b"]))
    assert client.get("/api/v1/settings/queue").json() == {"running": 0, "waiting": 2}
    limit(upload_max_mb=200)
