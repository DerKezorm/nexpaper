"""Uploading in pieces: announced with size and checksum, received in order, resumed after a break, checked at the end."""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app import clock
from app.db import SessionLocal, engine
from app.models import Document, Job, Upload
from app.services import jobs, limits, uploads

from . import files
from .conftest import DATA_DIR, make_account, new_client
from .intake import (
    device_token,
    disk_files,
    limit,
    process_all,
    row_of,
    sha,
    upload_folder_files,
    upload_key,
    upload_one,
    version_of,
)
from .papers import add_document, own_vault, shared_vault

PNG = files.make_image("png", size=(400, 500))


def announce(client: TestClient, data: bytes = PNG, name: str = "scan.png", **extra: Any) -> Any:
    return client.post("/api/v1/uploads", json={"filename": name, "size": len(data), "sha256": sha(data), **extra})


def begin(client: TestClient, data: bytes = PNG, **extra: Any) -> str:
    answer = announce(client, data, **extra)
    assert answer.status_code == 201, answer.text
    return answer.json()["upload"]["id"]  # type: ignore[no-any-return]


def piece(client: TestClient, upload_id: str, data: bytes, offset: int) -> Any:
    return client.put(f"/api/v1/uploads/{upload_id}?offset={offset}", content=data)


def count(model: type) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_a_file_sent_in_pieces_becomes_a_document_with_the_checked_content(client: TestClient, operator: object) -> None:
    started = announce(client)
    assert started.status_code == 201
    body = started.json()
    assert body["exists"] is False and body["document"] is None
    upload = body["upload"]
    assert upload["received"] == 0 and upload["size"] == len(PNG) and upload["state"] == "open"
    assert upload["chunk_size"] == limits.PIECE and upload["max_piece"] == limits.MAX_PIECE
    cut = len(PNG) // 3
    first = piece(client, upload["id"], PNG[:cut], 0)
    assert first.status_code == 200 and first.json()["received"] == cut
    second = piece(client, upload["id"], PNG[cut:], cut)
    assert second.json()["received"] == len(PNG)
    finished = client.post(f"/api/v1/uploads/{upload['id']}/finish")
    assert finished.status_code == 200
    made = finished.json()
    assert made["created"] is True and made["duplicate"] is None
    document = made["document"]
    assert document["title"] == "scan" and document["status"] == "processing" and document["source"] == "upload"
    assert (Path(DATA_DIR) / "dokumente" / version_of(document["id"]).original_path).read_bytes() == PNG
    # The part file is gone, the upload is remembered as done (a repeated request gets the same document).
    assert upload_folder_files() == []
    assert client.get(f"/api/v1/uploads/{upload['id']}").json()["state"] == "done"
    process_all()
    assert client.get(f"/api/v1/documents/{document['id']}").json()["status"] == "inbox"


def test_an_app_that_lost_its_connection_asks_where_it_stands_and_goes_on(client: TestClient, operator: object) -> None:
    upload_id = begin(client)
    assert piece(client, upload_id, PNG[:100], 0).json()["received"] == 100
    # A new connection, a new client: the server says how far it is.
    with new_client(make_account("unused")) as other:
        assert other.get(f"/api/v1/uploads/{upload_id}").status_code == 404
    state = client.get(f"/api/v1/uploads/{upload_id}").json()
    assert state["received"] == 100
    assert piece(client, upload_id, PNG[100:], state["received"]).json()["received"] == len(PNG)
    assert client.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 200


def test_a_piece_in_the_wrong_place_is_refused_and_the_answer_says_where_to_go_on(client: TestClient,
                                                                                   operator: object) -> None:
    upload_id = begin(client)
    piece(client, upload_id, PNG[:100], 0)
    for offset in (0, 50, 101, 5000):  # an overlap, a gap
        refused = piece(client, upload_id, PNG[100:200], offset)
        assert refused.status_code == 409, offset
        assert refused.json()["detail"]["code"] == "offset_mismatch" and refused.json()["detail"]["received"] == 100
    assert client.get(f"/api/v1/uploads/{upload_id}").json()["received"] == 100
    # What was refused changed nothing: the file is the bytes sent, in order, and nothing else.
    piece(client, upload_id, PNG[100:], 100)
    assert client.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 200


def test_pieces_past_the_announced_size_and_empty_pieces_are_refused(client: TestClient, operator: object) -> None:
    upload_id = begin(client)
    assert piece(client, upload_id, PNG + b"x", 0).status_code == 413
    assert client.get(f"/api/v1/uploads/{upload_id}").json()["received"] == 0
    assert piece(client, upload_id, b"", 0).status_code == 422
    piece(client, upload_id, PNG[:200], 0)
    assert piece(client, upload_id, PNG[200:] + b"yy", 200).status_code == 413
    assert client.get(f"/api/v1/uploads/{upload_id}").json()["received"] == 200
    assert upload_folder_files()[0].stat().st_size == 200


def test_a_piece_larger_than_the_server_takes_is_413_and_cut_off(client: TestClient, operator: object,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limits, "MAX_PIECE", 100)
    upload_id = begin(client)
    refused = piece(client, upload_id, PNG[:300], 0)
    assert refused.status_code == 413 and refused.json()["detail"]["code"] == "piece_too_large"
    assert upload_folder_files()[0].stat().st_size == 0


def test_a_file_that_is_not_the_one_announced_is_thrown_away_at_the_end(client: TestClient, operator: object) -> None:
    other = files.make_image("png", size=(401, 500))
    assert len(other) != len(PNG) or other != PNG
    upload_id = begin(client, PNG)
    # Same size, other content: the checksum catches it.
    content = bytes([PNG[0] ^ 1]) + PNG[1:]
    piece(client, upload_id, content, 0)
    refused = client.post(f"/api/v1/uploads/{upload_id}/finish")
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "checksum_mismatch"
    assert client.get(f"/api/v1/uploads/{upload_id}").status_code == 404
    assert count(Document) == 0 and count(Upload) == 0 and upload_folder_files() == [] and disk_files() == []


def test_a_file_of_the_wrong_kind_with_the_right_checksum_is_415_at_the_end_and_thrown_away(client: TestClient,
                                                                                            operator: object) -> None:
    upload_id = begin(client, files.EXE, name="tool.pdf")
    piece(client, upload_id, files.EXE, 0)
    refused = client.post(f"/api/v1/uploads/{upload_id}/finish")
    assert refused.status_code == 415 and refused.json()["detail"]["code"] == "unsupported_type"
    assert count(Document) == 0 and count(Upload) == 0 and upload_folder_files() == [] and disk_files() == []


def test_finishing_before_everything_arrived_changes_nothing_and_the_upload_goes_on(client: TestClient,
                                                                                    operator: object) -> None:
    upload_id = begin(client)
    piece(client, upload_id, PNG[:100], 0)
    early = client.post(f"/api/v1/uploads/{upload_id}/finish")
    assert early.status_code == 409 and early.json()["detail"]["code"] == "incomplete"
    state = client.get(f"/api/v1/uploads/{upload_id}").json()
    assert state["state"] == "open" and state["received"] == 100
    piece(client, upload_id, PNG[100:], 100)
    assert client.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 200


def test_finishing_twice_makes_one_document_and_returns_it_again(client: TestClient, operator: object) -> None:
    upload_id = begin(client)
    piece(client, upload_id, PNG, 0)
    first = client.post(f"/api/v1/uploads/{upload_id}/finish").json()
    again = client.post(f"/api/v1/uploads/{upload_id}/finish")
    assert again.status_code == 200 and again.json()["created"] is False
    assert again.json()["document"]["id"] == first["document"]["id"]
    assert count(Document) == 1 and len(disk_files()) == 1
    # A piece or an abort after that is refused, and the document stays.
    assert piece(client, upload_id, b"x", len(PNG)).status_code == 409
    with SessionLocal() as db:
        assert count(Job) == 1 and db.scalar(select(func.count()).select_from(Job).where(Job.kind == jobs.PROCESS)) == 1


def test_a_double_click_on_finish_at_the_same_moment_makes_exactly_one_document(client: TestClient,
                                                                                 operator: object) -> None:
    lea = make_account("lea")
    with new_client(lea) as browser:
        upload_id = begin(browser)
        piece(browser, upload_id, PNG, 0)
        answers: list[tuple[int, Any]] = []
        gate = threading.Barrier(6, timeout=20)

        def click() -> None:
            with new_client(lea) as tab:
                gate.wait()
                answer = tab.post(f"/api/v1/uploads/{upload_id}/finish")
                answers.append((answer.status_code, answer.json()))

        threads = [threading.Thread(target=click) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert count(Document) == 1 and len(disk_files()) == 1 and upload_folder_files() == []
    statuses = sorted(code for code, _ in answers)
    # One call made it; the others met it half done (409) or after it (the same document again).
    assert statuses.count(200) >= 1 and set(statuses) <= {200, 409}
    ids = {body["document"]["id"] for code, body in answers if code == 200}
    assert len(ids) == 1
    assert sum(1 for code, body in answers if code == 200 and body["created"]) == 1


def test_another_account_cannot_reach_an_upload_it_did_not_make(client: TestClient, operator: object) -> None:
    upload_id = begin(client)
    piece(client, upload_id, PNG[:100], 0)
    with new_client(make_account("tom")) as tom:
        assert tom.get(f"/api/v1/uploads/{upload_id}").status_code == 404
        assert piece(tom, upload_id, PNG[100:], 100).status_code == 404
        assert tom.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 404
        assert tom.delete(f"/api/v1/uploads/{upload_id}").status_code == 404
        # Ids that were never made, or are no ids, answer the same.
        for bad in ("0" * 32, "x" * 32, "..", "A" * 32):
            assert tom.get(f"/api/v1/uploads/{bad}").status_code == 404
            assert piece(tom, bad, b"x", 0).status_code in (404, 413)
        assert tom.get(f"/api/v1/uploads/{'a' * 80}").status_code == 422
    assert client.get(f"/api/v1/uploads/{upload_id}").json()["received"] == 100


def test_an_upload_ends_24_hours_after_its_last_piece(client: TestClient, operator: object,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    start = clock.now()
    monkeypatch.setattr(clock, "now", lambda: start)
    upload_id = begin(client)
    piece(client, upload_id, PNG[:100], 0)
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(hours=23))
    # A piece moves the end.
    assert piece(client, upload_id, PNG[100:200], 100).status_code == 200
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(hours=23 + 23))
    assert client.get(f"/api/v1/uploads/{upload_id}").status_code == 200
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(hours=23 + 25))
    gone = client.get(f"/api/v1/uploads/{upload_id}")
    assert gone.status_code == 410 and gone.json()["detail"]["code"] == "upload_expired"
    # The record and the file went with that answer; the next request finds nothing.
    assert count(Upload) == 0 and upload_folder_files() == []
    assert piece(client, upload_id, PNG[200:], 200).status_code == 404
    assert client.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 404


def test_the_sweep_removes_what_ran_out_and_leaves_what_has_not(client: TestClient, operator: object,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    start = clock.now()
    monkeypatch.setattr(clock, "now", lambda: start)
    old = begin(client)
    piece(client, old, PNG[:50], 0)
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(hours=20))
    fresh = begin(client, files.make_image("png", size=(300, 300)))
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(hours=30))
    with SessionLocal() as db:
        assert uploads.sweep(db) == 1
    assert client.get(f"/api/v1/uploads/{old}").status_code == 404
    assert client.get(f"/api/v1/uploads/{fresh}").status_code == 200
    assert len(upload_folder_files()) == 1
    # A part file nobody has a record for goes after a day.
    stray = Path(DATA_DIR) / "uploads" / ("f" * 32 + ".part")
    stray.write_bytes(b"x")
    import os

    old_time = (start - timedelta(days=3)).timestamp()
    os.utime(stray, (old_time, old_time))
    with SessionLocal() as db:
        uploads.sweep(db)
    assert not stray.exists()


def test_cancelling_drops_the_record_and_what_arrived(client: TestClient, operator: object) -> None:
    upload_id = begin(client)
    piece(client, upload_id, PNG[:100], 0)
    assert client.delete(f"/api/v1/uploads/{upload_id}").status_code == 204
    assert client.get(f"/api/v1/uploads/{upload_id}").status_code == 404
    assert count(Upload) == 0 and upload_folder_files() == []
    assert client.delete(f"/api/v1/uploads/{upload_id}").status_code == 404


def test_bytes_that_stand_beyond_the_record_after_a_break_are_cut_off(client: TestClient, operator: object) -> None:
    """A piece written to the file whose count was not saved (the server stopped in between): the next request cuts the
    file back to what the record says, so that the file is never longer than what was counted."""
    upload_id = begin(client)
    piece(client, upload_id, PNG[:100], 0)
    part = upload_folder_files()[0]
    with part.open("ab") as handle:
        handle.write(b"garbage that was never counted")
    assert client.get(f"/api/v1/uploads/{upload_id}").json()["received"] == 100
    assert part.stat().st_size == 100
    with part.open("ab") as handle:
        handle.write(b"more")
    piece(client, upload_id, PNG[100:], 100)
    finished = client.post(f"/api/v1/uploads/{upload_id}/finish")
    assert finished.status_code == 200
    stored = version_of(finished.json()["document"]["id"]).original_path
    assert (Path(DATA_DIR) / "dokumente" / stored).read_bytes() == PNG


def test_a_part_file_that_is_shorter_than_the_record_lowers_the_record(client: TestClient, operator: object) -> None:
    upload_id = begin(client)
    piece(client, upload_id, PNG[:200], 0)
    upload_folder_files()[0].write_bytes(PNG[:50])
    assert client.get(f"/api/v1/uploads/{upload_id}").json()["received"] == 50
    assert piece(client, upload_id, PNG[50:], 50).status_code == 200
    assert client.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 200


def test_an_upload_that_was_half_finished_when_the_server_stopped_receives_again(client: TestClient,
                                                                                  operator: object) -> None:
    upload_id = begin(client)
    piece(client, upload_id, PNG, 0)
    with SessionLocal() as db:
        db.query(Upload).update({"state": "finishing"})
        db.commit()
    assert client.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 409
    with SessionLocal() as db:
        uploads.recover(db)
    assert client.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 200


# --- Announcing: size, checksum, quotas, the vault --------------------------------------------------------------------


def test_the_announcement_is_checked_before_a_byte_is_sent(client: TestClient, operator: object) -> None:
    limit(upload_max_mb=1)
    too_big = client.post("/api/v1/uploads", json={"filename": "a.pdf", "size": 1024 * 1024 + 1, "sha256": "a" * 64})
    assert too_big.status_code == 413 and too_big.json()["detail"]["code"] == "too_large"
    for body in (
        {"filename": "a.pdf", "size": 0, "sha256": "a" * 64},
        {"filename": "a.pdf", "size": -5, "sha256": "a" * 64},
        {"filename": "a.pdf", "size": 10, "sha256": "short"},
        {"filename": "a.pdf", "size": 10, "sha256": "z" * 64},
        {"filename": "a.pdf", "size": "10", "sha256": "a" * 64},
        {"filename": "", "size": 10, "sha256": "a" * 64},
        {"size": 10, "sha256": "a" * 64},
        {"filename": "a.pdf", "size": 10, "sha256": "a" * 64, "unknown": 1},
        {"filename": "a.pdf", "size": 10, "sha256": "a" * 64, "vault_id": "x"},
    ):
        assert client.post("/api/v1/uploads", json=body).status_code in (422,), body
    assert count(Upload) == 0 and upload_folder_files() == []
    # Capital letters in the checksum are the same checksum.
    assert announce(client, PNG, sha256=sha(PNG).upper()).status_code == 201


def test_how_many_uploads_and_how_many_bytes_an_account_may_have_open_is_limited(client: TestClient,
                                                                                  operator: object) -> None:
    limit(upload_open_count=2)
    one, two, three = (files.make_image("png", size=(100 + n, 100)) for n in range(3))
    begin(client, one)
    begin(client, two)
    refused = announce(client, three)
    assert refused.status_code == 429 and refused.json()["detail"]["code"] == "too_many_uploads"
    # Another account has its own room.
    with new_client(make_account("tom")) as tom:
        assert announce(tom, three).status_code == 201


def test_the_bytes_open_at_once_are_limited_too(client: TestClient, operator: object) -> None:
    limit(upload_open_mb=1)
    sizes = [700 * 1024, 700 * 1024]
    first = {"filename": "a.pdf", "size": sizes[0], "sha256": "1" * 64}
    second = {"filename": "b.pdf", "size": sizes[1], "sha256": "2" * 64}
    assert client.post("/api/v1/uploads", json=first).status_code == 201
    refused = client.post("/api/v1/uploads", json=second)
    assert refused.status_code == 429 and refused.json()["detail"]["code"] == "upload_space"


def test_a_cancelled_or_finished_upload_gives_its_place_back(client: TestClient, operator: object) -> None:
    limit(upload_open_count=1)
    first = begin(client, files.make_image("png", size=(120, 120)))
    assert announce(client, files.make_image("png", size=(130, 130))).status_code == 429
    client.delete(f"/api/v1/uploads/{first}")
    second = begin(client, files.make_image("png", size=(130, 130)))
    piece(client, second, files.make_image("png", size=(130, 130)), 0)
    client.post(f"/api/v1/uploads/{second}/finish")
    assert announce(client, files.make_image("png", size=(140, 140))).status_code == 201


def test_the_vault_of_an_upload_is_checked_when_it_is_announced(client: TestClient, operator: object) -> None:
    lea, tom = make_account("lea"), make_account("tom")
    household = shared_vault("Household", make_account("boss"), (lea, "edit"), (tom, "read"))
    with new_client(lea) as lea_browser:
        assert announce(lea_browser, vault_id=household).status_code == 201
        assert announce(lea_browser, files.make_image("png", size=(90, 90)), vault_id=own_vault(tom)).status_code == 404
    with new_client(tom) as tom_browser:
        assert announce(tom_browser, vault_id=household).status_code == 403
        assert announce(tom_browser, vault_id=424242).status_code == 404
        mine = announce(tom_browser)
        assert mine.status_code == 201
        piece(tom_browser, mine.json()["upload"]["id"], PNG, 0)
        document = tom_browser.post(f"/api/v1/uploads/{mine.json()['upload']['id']}/finish").json()["document"]
        assert document["vault_id"] == own_vault(tom)


def test_a_vault_that_is_lost_before_the_end_is_not_a_way_in(client: TestClient, operator: object) -> None:
    lea = make_account("lea")
    household = shared_vault("Household", make_account("boss"), (lea, "edit"))
    with new_client(lea) as browser:
        upload_id = begin(browser, vault_id=household)
        piece(browser, upload_id, PNG, 0)
        with SessionLocal() as db:
            from app.models import VaultMember

            db.query(VaultMember).filter_by(vault_id=household, user_id=lea.id).delete()
            db.commit()
        refused = browser.post(f"/api/v1/uploads/{upload_id}/finish")
        # The vault the upload named is one the account may no longer add to: nothing is made, and the file stays
        # where it is until the account cancels (or the upload runs out).
        assert refused.status_code == 404
        assert count(Document) == 0 and disk_files() == [] and len(upload_folder_files()) == 1
        assert browser.get(f"/api/v1/uploads/{upload_id}").json()["state"] == "open"
        assert browser.delete(f"/api/v1/uploads/{upload_id}").status_code == 204


# --- The same file, seen or not seen -----------------------------------------------------------------------------------


def test_a_file_the_person_has_is_not_sent_again(client: TestClient, operator: object) -> None:
    first = upload_one(client, "scan.png", PNG)
    again = announce(client)
    assert again.status_code == 200
    body = again.json()
    assert body["exists"] is True and body["upload"] is None
    assert body["document"] == {"id": first["id"], "title": "scan", "status": "processing"}
    assert count(Upload) == 0 and upload_folder_files() == []


def test_a_file_in_the_trash_is_not_an_existing_one(client: TestClient, operator: object) -> None:
    first = upload_one(client, "scan.png", PNG)
    client.delete(f"/api/v1/documents/{first['id']}")
    assert announce(client).status_code == 201


def test_a_file_in_a_vault_the_person_shares_is_an_existing_one(client: TestClient, operator: object) -> None:
    lea, tom = make_account("lea"), make_account("tom")
    household = shared_vault("Household", make_account("boss"), (lea, "edit"), (tom, "read"))
    add_document(household, lea, "Shared", content=PNG, extension=".png")
    with new_client(tom) as tom_browser:
        assert announce(tom_browser).json()["exists"] is True


def test_a_file_kept_where_the_person_cannot_look_is_treated_like_a_new_one_and_nothing_tells_otherwise(
        client: TestClient, operator: object) -> None:
    with new_client(make_account("lea")) as lea:
        upload_one(lea, "private.png", PNG)
    statements: list[str] = []

    def count_statements(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement)

    with new_client(make_account("tom")) as tom:
        event.listen(engine, "before_cursor_execute", count_statements)
        try:
            hidden = announce(tom)
            hidden_statements = len(statements)
            statements.clear()
            fresh = announce(tom, files.make_image("png", size=(77, 77)))
            fresh_statements = len(statements)
        finally:
            event.remove(engine, "before_cursor_execute", count_statements)
    assert hidden.status_code == fresh.status_code == 201
    assert hidden.json().keys() == fresh.json().keys() and hidden.json()["exists"] is False
    assert set(hidden.json()["upload"]) == set(fresh.json()["upload"])
    # The same work is done: no extra query, none missing, so neither the answer nor its cost tells.
    assert hidden_statements == fresh_statements


def test_a_file_in_the_personal_vault_of_somebody_else_is_not_an_existing_one_after_a_move_out_of_sight(
        client: TestClient, operator: object) -> None:
    lea, tom = make_account("lea"), make_account("tom")
    household = shared_vault("Household", make_account("boss"), (lea, "edit"), (tom, "read"))
    with new_client(lea) as lea_browser:
        made = upload_one(lea_browser, "scan.png", PNG, vault_id=household)
        with new_client(tom) as tom_browser:
            assert announce(tom_browser).json()["exists"] is True
            assert lea_browser.post(f"/api/v1/documents/{made['id']}/move", json={"vault_id": own_vault(lea)}).status_code == 200
            assert announce(tom_browser).status_code == 201


def test_device_and_key_uploads_come_from_the_api(client: TestClient, operator: object) -> None:
    lea = make_account("lea")
    with new_client(lea) as browser:
        token = device_token(browser)
    with TestClient(client.app, base_url="http://testserver") as program:
        auth = {"Authorization": f"Bearer {token}"}
        started = program.post("/api/v1/uploads", json={"filename": "a.png", "size": len(PNG), "sha256": sha(PNG)}, headers=auth)
        assert started.status_code == 201
        upload_id = started.json()["upload"]["id"]
        assert program.put(f"/api/v1/uploads/{upload_id}?offset=0", content=PNG, headers=auth).status_code == 200
        finished = program.post(f"/api/v1/uploads/{upload_id}/finish", headers=auth)
        assert finished.json()["document"]["source"] == "api"
        assert row_of(finished.json()["document"]["id"]).source == "api"
        key = upload_key(lea)
        again = program.post("/api/v1/uploads", json={"filename": "b.png", "size": 5, "sha256": "c" * 64},
                             headers={"Authorization": f"Bearer {key}"})
        assert again.status_code == 201
        read_key = upload_key(lea, "read")
        assert program.post("/api/v1/uploads", json={"filename": "c.png", "size": 5, "sha256": "d" * 64},
                            headers={"Authorization": f"Bearer {read_key}"}).status_code == 403
    process_all()


def test_a_failure_while_the_document_is_made_leaves_the_upload_whole_and_no_staged_file(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import receiving

    upload_id = begin(client)
    piece(client, upload_id, PNG, 0)

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(receiving, "accept", broken)
    with TestClient(client.app, base_url="http://testserver", headers=client.headers, raise_server_exceptions=False,
                    cookies=client.cookies) as quiet:
        assert quiet.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 500
    # Nothing was left in the document folder, the upload is receiving again, the bytes are still there.
    assert disk_files() == [] and len(upload_folder_files()) == 1
    assert client.get(f"/api/v1/uploads/{upload_id}").json()["state"] == "open"
    monkeypatch.undo()
    assert client.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 200


def test_the_same_file_announced_again_goes_on_with_the_open_upload_and_the_open_ones_are_listed(
        client: TestClient, operator: object) -> None:
    upload_id = begin(client)
    piece(client, upload_id, PNG[:100], 0)
    listed = client.get("/api/v1/uploads").json()
    assert [(u["id"], u["received"], u["filename"], u["state"]) for u in listed] == [(upload_id, 100, "scan.png", "open")]
    # A closed tab, a new page: the file is chosen again, and the server answers with the upload that waits (200).
    again = announce(client)
    assert again.status_code == 200 and again.json()["exists"] is False
    assert again.json()["upload"]["id"] == upload_id and again.json()["upload"]["received"] == 100
    assert count(Upload) == 1 and len(upload_folder_files()) == 1
    assert piece(client, upload_id, PNG[100:], 100).json()["received"] == len(PNG)
    assert client.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 200
    # Finished ones are not listed; another file is another upload; a file for another vault is another upload.
    assert client.get("/api/v1/uploads").json() == []


def test_another_file_another_size_or_another_vault_and_another_account_are_other_uploads(client: TestClient,
                                                                                         operator: object) -> None:
    lea = make_account("lea")
    household = shared_vault("Household", make_account("boss"), (lea, "edit"))
    with new_client(lea) as browser:
        mine = begin(browser)
        assert begin(browser, vault_id=household) != mine
        other = files.make_image("png", size=(300, 300))
        assert begin(browser, other) not in (mine,)
        assert len(browser.get("/api/v1/uploads").json()) == 3
    with new_client(make_account("tom")) as tom:
        assert tom.get("/api/v1/uploads").json() == []
        assert begin(tom) != mine


def test_an_open_upload_that_ran_out_is_not_offered_again_and_is_removed_by_the_list(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch) -> None:
    start = clock.now()
    monkeypatch.setattr(clock, "now", lambda: start)
    upload_id = begin(client)
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(hours=25))
    assert client.get("/api/v1/uploads").json() == [] and count(Upload) == 0 and upload_folder_files() == []
    assert begin(client) != upload_id


def test_asking_to_finish_again_shows_the_twin_only_while_the_person_may_see_it(client: TestClient,
                                                                              operator: object) -> None:
    from app.models import Document as DocumentRow

    lea, tom = make_account("lea"), make_account("tom")
    with new_client(tom) as tom_browser:
        private = upload_one(tom_browser, "privat.png", PNG)
    with new_client(lea) as browser:
        upload_id = begin(browser)  # the file of tom is not hers to see: it is a new upload
        piece(browser, upload_id, PNG, 0)
        made = browser.post(f"/api/v1/uploads/{upload_id}/finish").json()
        assert made["duplicate"] is None and made["created"] is True
        with SessionLocal() as db:
            db.get(DocumentRow, made["document"]["id"]).duplicate_of = private["id"]  # type: ignore[union-attr]
            db.commit()
        again = browser.post(f"/api/v1/uploads/{upload_id}/finish").json()
        # The record points at a document she cannot see: the answer says nothing of it.
        assert again["created"] is False and again["duplicate"] is None
    with new_client(tom) as tom_browser:
        assert tom_browser.put(f"/api/v1/documents/{private['id']}/shares/{lea.id}", json={"right": "read"}).status_code == 200
    with new_client(lea) as browser:
        shared = browser.post(f"/api/v1/uploads/{upload_id}/finish").json()
        assert shared["duplicate"] is not None and shared["duplicate"]["document_id"] == private["id"]


def test_asking_for_the_state_while_a_piece_is_received_leaves_that_piece_alone(client: TestClient,
                                                                               operator: object) -> None:
    """A second tab, or an app that asks where it stands, while a piece is on its way: the bytes of that piece stand
    beyond the record until it is counted. The question must not cut them off, or the file ends up with a hole."""
    import asyncio

    # Each half larger than the write buffer of Python (128 KiB), so that the first is on the disk while the second waits.
    data = files.make_pdf(["piece " * 40] * 30) + b"%" + bytes(range(256)) * 2400
    upload_id = begin(client, data)
    with SessionLocal() as db:
        uid = int(db.get(Upload, upload_id).user_id)  # type: ignore[union-attr]
    half = len(data) // 2
    asked: list[int] = []

    async def stream() -> Any:
        yield data[:half]
        # The first half is on the disk now; another request asks meanwhile.
        with SessionLocal() as other:
            asked.append(uploads.status(other, uid, upload_id).received)
            asked.append(len(uploads.open_ones(other, uid)))
            asked.append(uploads.start(other, uid, vault_id=None, filename="scan.pdf", size=len(data),
                                       sha256=sha(data), source="upload").upload.received)  # type: ignore[union-attr]
        yield data[half:]

    async def send() -> int:
        with SessionLocal() as db:
            return (await uploads.append(db, uid, upload_id, 0, stream())).received

    assert asyncio.run(send()) == len(data)
    assert asked == [0, 1, 0]
    assert (Path(DATA_DIR) / "uploads" / f"{upload_id}.part").read_bytes() == data
    assert client.post(f"/api/v1/uploads/{upload_id}/finish").status_code == 200
