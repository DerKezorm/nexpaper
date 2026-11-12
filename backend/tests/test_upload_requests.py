"""Upload requests (U1): a person asks somebody without an account for files, by an address ``/u/<token>``.

What the stranger reaches is the core of these tests: one file a request, kind from the content, the limits, the same
answer for everything that does not work, nothing to read, and nothing that ever lands anywhere but in the inbox of the
person who asked."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import clock
from app.db import SessionLocal
from app.main import app
from app.middleware import GuardMiddleware
from app.models import Account, Document, IntakeItem, Rule, UploadRequest
from app.security import brake
from app.services import logs, settings_service, sorting, tell, upload_requests

from . import files
from .conftest import TAB, make_account, new_client
from .intake import device_token, upload_key
from .papers import PDF, own_vault, shared_vault

START = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
ADDRESS = "https://paper.example.com"


@pytest.fixture(autouse=True)
def fresh() -> Iterator[None]:
    upload_requests.forget()
    yield
    upload_requests.forget()


def switch(on: bool = True, address: str = ADDRESS) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"upload_requests_allowed": on, "public_url": address})


@pytest.fixture
def jule() -> Account:
    switch()
    account = make_account("jule")
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        row.display_name = "Jule Beispiel"
        db.commit()
    return account


def make(browser: TestClient, name: str = "Kanzlei Weber", days: int = 7, max_files: int = 10) -> dict:
    answer = browser.post("/api/v1/upload-requests", json={"name": name, "days": days, "max_files": max_files})
    assert answer.status_code == 201, answer.text
    return answer.json()


def token_of(made: dict) -> str:
    return made["url"].rsplit("/u/", 1)[1]


def stranger() -> TestClient:
    """Somebody without an account: no cookie, no tab header."""
    return TestClient(app, base_url="http://testserver")


def send(outside: TestClient, token: str, name: str = "rechnung.pdf", data: bytes = PDF,
         mime: str = "application/pdf"):  # the test client's answer
    return outside.post(f"/api/v1/u/{token}/files", files={"file": (name, data, mime)})


def documents_of(account: Account) -> list[Document]:
    with SessionLocal() as db:
        found = list(db.scalars(select(Document).where(Document.owner_id == account.id).order_by(Document.id)))
        for row in found:
            db.expunge(row)
        return found


# --- The operator's switch and the public address -------------------------------------------------------------------


def test_off_from_the_start_and_nobody_makes_one(client: TestClient, operator: Account) -> None:
    with SessionLocal() as db:
        assert settings_service.get(db, "upload_requests_allowed") is False
    assert client.get("/api/v1/settings").json()["upload_requests_allowed"] is False
    rules = client.get("/api/v1/upload-requests/rules").json()
    assert rules["allowed"] is False and rules["max_files"] == 50 and rules["default_files"] == 10
    answer = client.post("/api/v1/upload-requests", json={"name": "x", "days": 1})
    assert (answer.status_code, answer.json()["detail"]["code"]) == (409, "requests_off")
    ready = client.get("/api/v1/settings/readiness").json()["points"]
    assert {"key": "upload_requests", "state": "ok", "values": {"on": False}} in ready


def test_a_request_needs_the_public_address(client: TestClient, operator: Account) -> None:
    switch(address="")
    assert client.get("/api/v1/upload-requests/rules").json()["public_url_set"] is False
    answer = client.post("/api/v1/upload-requests", json={"name": "x", "days": 1})
    assert (answer.status_code, answer.json()["detail"]["code"]) == (409, "public_url_missing")
    # The operator switches it on in the settings; "Ready for the internet?" names it then.
    assert client.put("/api/v1/settings", json={"upload_requests_allowed": True, "public_url": ADDRESS}).status_code \
        == 200
    point = next(p for p in client.get("/api/v1/settings/readiness").json()["points"] if p["key"] == "upload_requests")
    assert point["state"] == "warn" and point["values"] == {"on": True, "open": 0}


# --- Making, listing, copying, revoking ----------------------------------------------------------------------------


def test_a_request_is_made_listed_copied_and_revoked(jule: Account) -> None:
    with new_client(jule) as browser:
        made = make(browser, "  Kanzlei   Weber ", days=7, max_files=3)
        token = token_of(made)
        assert token.startswith("upr_") and made["url"] == f"{ADDRESS}/u/{token}"
        assert made["name"] == "Kanzlei Weber" and made["max_files"] == 3 and made["status"] == "active"
        listed = browser.get("/api/v1/upload-requests").json()
        assert [r["id"] for r in listed] == [made["id"]] and token not in json.dumps(listed)
        with SessionLocal() as db:
            row = db.get(UploadRequest, made["id"])
            assert row is not None and token not in row.token_hash and token not in row.token_enc
        again = browser.post(f"/api/v1/upload-requests/{made['id']}/address").json()
        assert again["url"] == made["url"]
        assert browser.delete(f"/api/v1/upload-requests/{made['id']}").status_code == 204
        assert browser.get("/api/v1/upload-requests").json() == []
        assert browser.post(f"/api/v1/upload-requests/{made['id']}/address").status_code == 404
    with stranger() as outside:
        assert outside.get(f"/api/v1/u/{token}").status_code == 404


@pytest.mark.parametrize("body", [
    {"name": "", "days": 1}, {"name": "x" * 101, "days": 1}, {"name": "a\u202eb", "days": 1},
    {"name": "a\x07b", "days": 1}, {"name": "x", "days": 0}, {"name": "x", "days": 31},
    {"name": "x", "days": 1, "max_files": 0}, {"name": "x", "days": 1, "max_files": 51},
])
def test_what_a_request_may_be(jule: Account, body: dict) -> None:
    with new_client(jule) as browser:
        assert browser.post("/api/v1/upload-requests", json=body).status_code == 422


def test_at_most_twenty_open_requests_per_person(jule: Account) -> None:
    with new_client(jule) as browser:
        for n in range(upload_requests.MAX_OPEN):
            make(browser, f"Bitte {n}")
        answer = browser.post("/api/v1/upload-requests", json={"name": "one more", "days": 1})
        assert (answer.status_code, answer.json()["detail"]["code"]) == (409, "too_many_requests")


# --- The page and the upload -----------------------------------------------------------------------------------------


def test_the_page_shows_who_asks_and_how_many_still_go_and_nothing_else(jule: Account) -> None:
    with new_client(jule) as browser:
        token = token_of(make(browser, max_files=2))
    with stranger() as outside:
        page = outside.get(f"/api/v1/u/{token}")
        assert page.status_code == 200
        body = page.json()
        assert set(body) == {"requested_by", "name", "until", "remaining", "max_mb"}
        assert body["requested_by"] == "Jule Beispiel" and body["name"] == "Kanzlei Weber" and body["remaining"] == 2
        assert send(outside, token, "geheim-name.pdf").json() == {"status": "arrived", "remaining": 1}
        # Nothing of what came: no name of a file, no title, no number of documents.
        after = outside.get(f"/api/v1/u/{token}").text
        assert "geheim" not in after and after.count("remaining") == 1
        # Nothing else of the server answers to the token.
        for path in ("/api/v1/documents", "/api/v1/inbox", "/api/v1/auth/me", "/api/v1/upload-requests"):
            assert outside.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 401, path


@pytest.mark.parametrize(("name", "data", "mime"), [
    ("brief.pdf", files.make_pdf(), "application/pdf"),
    ("foto.jpg", files.make_image("jpeg"), "image/jpeg"),
    ("scan.png", files.make_image("png"), "image/png"),
    ("rechnung.xml", files.invoice_xml(), "application/xml"),
    ("bild.webp", files.make_image("webp"), "image/webp"),
])
def test_every_kind_the_inbox_takes_lands_in_the_inbox_of_the_person_who_asked(
    jule: Account, name: str, data: bytes, mime: str,
) -> None:
    household = shared_vault("Haushalt", make_account("tester", "operator"), (jule, "manage"))
    with new_client(jule) as browser:
        # Even with another vault chosen for the own uploads, a request goes into the personal one.
        assert browser.put("/api/v1/me/preferences", json={"default_vault": household}).status_code == 200
        token = token_of(make(browser))
    with stranger() as outside:
        answer = send(outside, token, name, data, mime)
    assert answer.status_code == 201, answer.text
    (document,) = documents_of(jule)
    assert document.vault_id == own_vault(jule) and document.source == "request"
    assert document.status in ("processing", "inbox")
    with SessionLocal() as db:
        item = db.scalar(select(IntakeItem).where(IntakeItem.document_id == document.id))
        assert item is not None and item.unknown is True and item.source == "request"
        assert item.detail["from"] == "Kanzlei Weber"
    with new_client(jule) as browser:
        origin = browser.get(f"/api/v1/documents/{document.id}/origin").json()
        assert origin["unknown"] is True and origin["source"] == "request" and origin["sender"] == "Kanzlei Weber"


@pytest.mark.parametrize(("name", "data", "status", "code"), [
    ("programm.pdf", files.EXE, 415, "unsupported_type"),
    ("seite.html", files.HTML, 415, "unsupported_type"),
    ("bild.svg", files.SVG, 415, "unsupported_type"),
    ("leer.pdf", b"", 422, "empty_file"),
])
def test_a_file_that_is_not_taken_says_why_and_costs_no_slot(
    jule: Account, name: str, data: bytes, status: int, code: str,
) -> None:
    with new_client(jule) as browser:
        token = token_of(make(browser, max_files=1))
    with stranger() as outside:
        answer = send(outside, token, name, data, "application/octet-stream")
        assert (answer.status_code, answer.json()["detail"]["code"]) == (status, code)
        assert outside.get(f"/api/v1/u/{token}").json()["remaining"] == 1
    assert documents_of(jule) == []


def test_a_bomb_is_taken_as_any_picture_and_left_to_the_worker_and_its_limits(jule: Account) -> None:
    with new_client(jule) as browser:
        token = token_of(make(browser))
    with stranger() as outside:
        assert send(outside, token, "bombe.png", files.bomb_png(), "image/png").status_code == 201
    (document,) = documents_of(jule)
    # Read in the worker like every upload: its limit of pixels holds there (``test_processing.py``).
    assert document.status == "processing" and document.source == "request"


def test_a_hostile_file_name_is_cleaned_and_never_a_path(jule: Account) -> None:
    with new_client(jule) as browser:
        token = token_of(make(browser))
    with stranger() as outside:
        assert send(outside, token, "..\\../../etc/passwd\u202egnp.pdf").status_code == 201
    (document,) = documents_of(jule)
    assert "/" not in document.title and "\\" not in document.title and "\u202e" not in document.title
    with SessionLocal() as db:
        from app.models import Version

        version = db.scalar(select(Version).where(Version.document_id == document.id))
        assert version is not None and ".." not in version.original_path and "passwd" not in version.original_path.split(
            "/")[0]


def test_a_file_too_large_is_refused_by_its_length_before_its_body_is_read(jule: Account) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"upload_max_mb": 1})
    with new_client(jule) as browser:
        token = token_of(make(browser))
    read: list[int] = []
    sent: list[dict] = []
    body_size = 5 * 1024 * 1024

    async def receive() -> dict:
        read.append(1)
        return {"type": "http.request", "body": b"x" * 65536, "more_body": len(read) * 65536 < body_size}

    async def remember(message: dict) -> None:
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": f"/api/v1/u/{token}/files", "headers": [
        (b"content-length", str(body_size).encode()), (b"content-type", b"multipart/form-data; boundary=x")],
        "query_string": b"", "client": ("127.0.0.1", 1), "server": ("testserver", 80), "scheme": "http",
        "root_path": "", "app": app}
    asyncio.run(GuardMiddleware(app.middleware_stack)(scope, receive, remember))  # type: ignore[arg-type]
    assert sent[0]["status"] == 413 and read == []
    assert documents_of(jule) == []


def test_a_body_without_a_length_is_not_read(jule: Account) -> None:
    with new_client(jule) as browser:
        token = token_of(make(browser))

    def pieces() -> Iterator[bytes]:
        yield b"--x\r\n"

    with stranger() as outside:
        answer = outside.post(f"/api/v1/u/{token}/files", content=pieces(),
                              headers={"Content-Type": "multipart/form-data; boundary=x"})
        assert (answer.status_code, answer.json()["detail"]["code"]) == (411, "length_required")


def test_only_one_file_a_request(jule: Account) -> None:
    with new_client(jule) as browser:
        token = token_of(make(browser))
    with stranger() as outside:
        answer = outside.post(f"/api/v1/u/{token}/files", files=[("file", ("a.pdf", PDF, "application/pdf")),
                                                                 ("file", ("b.pdf", PDF, "application/pdf"))])
        assert answer.status_code == 413
    assert documents_of(jule) == []


def test_the_same_file_twice_answers_like_any_file(jule: Account) -> None:
    with new_client(jule) as browser:
        token = token_of(make(browser, max_files=4))
    with stranger() as outside:
        first = send(outside, token, "a.pdf")
        second = send(outside, token, "a.pdf")
        other = send(outside, token, "b.pdf", files.make_pdf(["Ganz anders"]))
    assert (first.status_code, second.status_code, other.status_code) == (201, 201, 201)
    assert first.json()["status"] == second.json()["status"] == other.json()["status"] == "arrived"
    assert [first.json()["remaining"], second.json()["remaining"], other.json()["remaining"]] == [3, 2, 1]
    assert set(first.headers) == set(second.headers)
    # Both are there: the person sees in the inbox that one looks like the other.
    assert len(documents_of(jule)) == 3


# --- Limits -----------------------------------------------------------------------------------------------------------


def test_the_nth_file_goes_and_the_one_after_answers_like_an_unknown_token(jule: Account) -> None:
    with new_client(jule) as browser:
        made = make(browser, max_files=2)
    token = token_of(made)
    with stranger() as outside:
        assert send(outside, token).json()["remaining"] == 1
        assert send(outside, token, "b.pdf", files.make_pdf(["B"])).json()["remaining"] == 0
        full = send(outside, token, "c.pdf", files.make_pdf(["C"]))
        unknown = send(outside, "upr_" + "x" * 43, "c.pdf")
        assert (full.status_code, full.json()) == (unknown.status_code, unknown.json()) == (404, unknown.json())
        assert outside.get(f"/api/v1/u/{token}").status_code == 404
    assert len(documents_of(jule)) == 2
    with new_client(jule) as browser:
        (row,) = browser.get("/api/v1/upload-requests").json()
        assert row["status"] == "used" and row["received"] == 2 and row["last_used_at"] is not None


def test_two_uploads_at_once_at_the_last_slot_take_one_file(jule: Account) -> None:
    with new_client(jule) as browser:
        token = token_of(make(browser, max_files=1))
    barrier = threading.Barrier(2)
    codes: list[int] = []

    def one(name: str) -> None:
        with stranger() as outside:
            barrier.wait(timeout=10)
            codes.append(send(outside, token, name, files.make_pdf([name])).status_code)

    threads = [threading.Thread(target=one, args=(n,)) for n in ("a.pdf", "b.pdf")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(codes) == [201, 404]
    assert len(documents_of(jule)) == 1
    with SessionLocal() as db:
        assert db.scalar(select(UploadRequest.received)) == 1


def test_files_per_request_and_hour(jule: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upload_requests, "PER_REQUEST_HOUR", 2)
    moment = [1000.0]
    monkeypatch.setattr(clock, "monotonic", lambda: moment[0])
    with new_client(jule) as browser:
        token = token_of(make(browser))
    with stranger() as outside:
        # A refused file counts as a try too.
        assert send(outside, token, "x.exe", files.EXE).status_code == 415
        assert send(outside, token).status_code == 201
        busy = send(outside, token, "b.pdf", files.make_pdf(["B"]))
        assert (busy.status_code, busy.json()["detail"]["code"]) == (429, "request_busy")
        moment[0] += 3601
        assert send(outside, token, "b.pdf", files.make_pdf(["B"])).status_code == 201


def test_files_per_sender_and_hour_over_all_requests(jule: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upload_requests, "PER_ADDRESS_HOUR", 2)
    with new_client(jule) as browser:
        tokens = [token_of(make(browser, f"Bitte {n}")) for n in range(3)]
    with stranger() as outside:
        assert send(outside, tokens[0]).status_code == 201
        assert send(outside, tokens[1], "b.pdf", files.make_pdf(["B"])).status_code == 201
        assert send(outside, tokens[2], "c.pdf", files.make_pdf(["C"])).status_code == 429


def test_files_of_the_whole_server_per_day(jule: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "now", lambda: START)
    monkeypatch.setattr(upload_requests, "DAY_FILES", 1)
    with new_client(jule) as browser:
        token = token_of(make(browser))
    with stranger() as outside:
        assert send(outside, token).status_code == 201
        full = send(outside, token, "b.pdf", files.make_pdf(["B"]))
        assert (full.status_code, full.json()["detail"]["code"]) == (429, "request_day_full")
        monkeypatch.setattr(clock, "now", lambda: START + timedelta(days=1))
        assert send(outside, token, "b.pdf", files.make_pdf(["B"])).status_code == 201


def test_bytes_of_the_whole_server_per_day_count_what_arrived(jule: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "now", lambda: START)
    big = files.make_pdf(["groß"], padding=200_000)
    monkeypatch.setattr(upload_requests, "DAY_BYTES", len(big) * 2 + 1000)
    with new_client(jule) as browser:
        token = token_of(make(browser))
    with stranger() as outside:
        assert send(outside, token, "a.pdf", big).status_code == 201
        assert send(outside, token, "x.exe", files.EXE).status_code == 415
        # A refused file gave its bytes back; the second large one still fits, the third not.
        assert send(outside, token, "b.pdf", files.make_pdf(["zwei"], padding=200_000)).status_code == 201
        assert send(outside, token, "c.pdf", files.make_pdf(["drei"], padding=200_000)).status_code == 429


# --- The same answer for everything that does not work --------------------------------------------------------------


def _ended_ways(jule: Account, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """A token for each way a request stops, with the way."""
    with new_client(jule) as browser:
        revoked, expired, moved = (make(browser, f"Bitte {n}", days=1) for n in range(3))
        browser.delete(f"/api/v1/upload-requests/{revoked['id']}")
    with SessionLocal() as db:
        row = db.get(UploadRequest, expired["id"])
        assert row is not None
        row.until = clock.now() - timedelta(minutes=1)
        row2 = db.get(UploadRequest, moved["id"])
        assert row2 is not None
        row2.address = "https://old.example.com"
        db.commit()
    return [("unknown", "upr_" + "q" * 43), ("other prefix", "lnk_" + "q" * 43), ("revoked", token_of(revoked)),
            ("expired", token_of(expired)), ("address changed", token_of(moved))]


def test_everything_that_does_not_work_answers_alike_and_counts_on_the_brake(
    jule: Account, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ways = _ended_ways(jule, monkeypatch)
    with stranger() as outside:
        answers = set()
        for _way, token in ways:
            for answer in (outside.get(f"/api/v1/u/{token}"), send(outside, token)):
                answers.add((answer.status_code, answer.text))
        assert answers == {(404, json.dumps({"detail": {"code": "not_found", "message": "Not found."}},
                                            separators=(",", ":")))}
        # Wrong ones went on the brake of the requests: a few more and the sender waits.
        for _ in range(40):
            last = outside.get("/api/v1/u/upr_" + "z" * 43)
            if last.status_code == 429:
                break
        assert last.status_code == 429
    assert documents_of(jule) == []
    brake.forget()


def test_the_switch_off_ends_every_request_and_on_again_brings_them_back(jule: Account) -> None:
    with new_client(jule) as browser:
        token = token_of(make(browser))
    switch(False)
    with stranger() as outside:
        assert send(outside, token).status_code == 404
        assert outside.get(f"/api/v1/u/{token}").status_code == 404
    with new_client(jule) as browser:
        assert browser.get("/api/v1/upload-requests").json()[0]["status"] == "off"
        assert browser.post("/api/v1/upload-requests", json={"name": "x", "days": 1}).status_code == 409
    switch(True)
    with stranger() as outside:
        assert send(outside, token).status_code == 201


def test_a_request_revoked_while_its_file_arrives_keeps_nothing(jule: Account, monkeypatch: pytest.MonkeyPatch) -> None:
    with new_client(jule) as browser:
        made = make(browser)
    real = upload_requests.still_open

    def revoked_meanwhile(db, request_id):  # type: ignore[no-untyped-def]
        upload_requests.revoke(db, jule.id, request_id)
        return real(db, request_id)

    monkeypatch.setattr(upload_requests, "still_open", revoked_meanwhile)
    with stranger() as outside:
        assert send(outside, token_of(made)).status_code == 404
    assert documents_of(jule) == []


# --- Nothing lands elsewhere ------------------------------------------------------------------------------------------


def test_a_rule_proposes_but_never_moves_a_document_of_a_request(jule: Account) -> None:
    operator = make_account("tester", "operator")
    household = shared_vault("Haushalt", operator, (jule, "manage"))
    when = [{"field": "text", "op": "contains", "values": ["Rechnung"]}]
    with new_client(jule) as browser:
        made = browser.post("/api/v1/rules", json={"vault_id": own_vault(jule), "when": when, "then": [
            {"field": "vault", "value": household}, {"field": "tag", "value": "steuer"}]})
        assert made.status_code == 201, made.text
        token = token_of(make(browser))
    with stranger() as outside:
        assert send(outside, token).status_code == 201
    (document,) = documents_of(jule)
    with SessionLocal() as db:
        row = db.get(Document, document.id)
        assert row is not None
        sorting.propose(db, row, "Rechnung 2026-1001 Stadtwerke Lindenau")
        db.commit()
        db.refresh(row)
        # The rule's tag is proposed; the vault stays the one of the person who asked.
        assert row.vault_id == own_vault(jule)
        assert db.scalar(select(func.count()).select_from(Rule)) == 1
    # The same rule moves a document the person uploaded herself (the rule itself works).
    with new_client(jule) as browser:
        own = browser.post("/api/v1/documents", files={"file": ("x.pdf", files.make_pdf(["Rechnung 7"]), "application/pdf")})
        own_id = own.json()["items"][0]["document"]["id"]
    with SessionLocal() as db:
        mine = db.get(Document, own_id)
        assert mine is not None
        sorting.propose(db, mine, "Rechnung 2026-1001 Stadtwerke Lindenau")
        db.commit()
        db.refresh(mine)
        assert mine.vault_id == household


# --- Notices ----------------------------------------------------------------------------------------------------------


def test_one_notice_per_request_and_hour_with_the_name_and_the_number(
    jule: Account, monkeypatch: pytest.MonkeyPatch,
) -> None:
    told: list[tuple[int, tell.Notice]] = []
    monkeypatch.setattr(tell, "person", lambda account_id, notice: told.append((account_id, notice)))
    moment = [START]
    monkeypatch.setattr(clock, "now", lambda: moment[0])
    with new_client(jule) as browser:
        token = token_of(make(browser))
    with stranger() as outside:
        send(outside, token, "geheim-1.pdf")
        send(outside, token, "geheim-2.pdf", files.make_pdf(["zwei"]))
        assert len(told) == 1
        moment[0] = START + timedelta(hours=1, minutes=1)
        send(outside, token, "geheim-3.pdf", files.make_pdf(["drei"]))
    assert len(told) == 2 and {who for who, _n in told} == {jule.id}
    words = json.dumps([n.texts for _w, n in told], ensure_ascii=False) + told[1][1].mail_body
    assert "Kanzlei Weber" in words and "3" in told[1][1].texts["de"][1] and "geheim" not in words


# --- Life ------------------------------------------------------------------------------------------------------------


def test_blocking_ends_the_requests_for_good_and_deleting_takes_them_away(
    client: TestClient, operator: Account,
) -> None:
    switch()
    tom = make_account("tom")
    with new_client(tom) as browser:
        token = token_of(make(browser))
    assert client.post(f"/api/v1/accounts/{tom.id}/block", json={"current_password": "correct horse battery"}
                       ).status_code == 204
    with stranger() as outside:
        assert send(outside, token).status_code == 404
    client.post(f"/api/v1/accounts/{tom.id}/unblock", json={"current_password": "correct horse battery"})
    with stranger() as outside:
        assert send(outside, token).status_code == 404, "unblocking does not bring a request back"
    lea = make_account("lea")
    with new_client(lea) as browser:
        make(browser)
    gone = client.request("DELETE", f"/api/v1/accounts/{lea.id}",
                          json={"current_password": "correct horse battery", "confirm_name": "lea"})
    assert gone.status_code == 204, gone.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(UploadRequest).where(UploadRequest.user_id == lea.id)) == 0


# --- The token is never in the log -----------------------------------------------------------------------------------


def test_the_token_never_stands_in_a_log_line(jule: Account) -> None:
    with new_client(jule) as browser:
        token = token_of(make(browser))
    for line in (f"POST /api/v1/u/{token}/files -> 201", f"GET /u/{token}", f"pasted {token} here",
                 f"https://paper.example.com/u/{token}?x=1"):
        assert token not in logs.redact(line) and token[4:] not in logs.redact(line), line


# --- Rights ----------------------------------------------------------------------------------------------------------


def test_only_the_person_sees_copies_and_revokes_a_request(jule: Account) -> None:
    with new_client(jule) as browser:
        made = make(browser)
    operator = make_account("tester", "operator")
    for other in (make_account("tom"), operator):
        with new_client(other) as browser:
            assert browser.get("/api/v1/upload-requests").json() == []
            assert browser.post(f"/api/v1/upload-requests/{made['id']}/address").status_code == 404
            assert browser.delete(f"/api/v1/upload-requests/{made['id']}").status_code == 404
    with new_client(operator) as browser:
        assert browser.get("/api/v1/upload-requests/overview").json() == {"open_requests": 1, "people": 1}
        assert ADDRESS not in browser.get("/api/v1/upload-requests/overview").text
    with new_client(jule) as browser:
        assert browser.get("/api/v1/upload-requests/overview").status_code == 403
        assert browser.get("/api/v1/upload-requests").json()[0]["status"] == "active"


def test_a_device_makes_requests_and_a_key_of_either_scope_does_not(jule: Account) -> None:
    with new_client(jule) as browser:
        device = device_token(browser)
    with TestClient(app, base_url="http://testserver") as program:
        made = program.post("/api/v1/upload-requests", json={"name": "vom Handy", "days": 3},
                            headers={"Authorization": f"Bearer {device}"})
        assert made.status_code == 201
        for scope in ("read", "upload"):
            key = upload_key(jule, scope)
            for method, path in (("GET", "/api/v1/upload-requests"), ("POST", "/api/v1/upload-requests"),
                                 ("GET", "/api/v1/upload-requests/rules"),
                                 ("DELETE", f"/api/v1/upload-requests/{made.json()['id']}")):
                answer = program.request(method, path, headers={"Authorization": f"Bearer {key}"},
                                         json={"name": "x", "days": 1} if method == "POST" else None)
                assert answer.status_code == 401, (scope, method, path, answer.status_code)


def test_without_a_session_nothing_of_the_person_side_answers() -> None:
    with TestClient(app, base_url="http://testserver", headers=TAB) as nobody:
        for method, path in (("GET", "/api/v1/upload-requests"), ("POST", "/api/v1/upload-requests"),
                             ("GET", "/api/v1/upload-requests/rules"), ("GET", "/api/v1/upload-requests/overview"),
                             ("POST", "/api/v1/upload-requests/1/address"), ("DELETE", "/api/v1/upload-requests/1")):
            assert nobody.request(method, path, json={} if method == "POST" else None).status_code == 401, path


def test_the_way_without_the_tab_header_is_this_one_path_only(jule: Account) -> None:
    with new_client(jule) as browser:
        token = token_of(make(browser))
        cookies = dict(browser.cookies)
    with TestClient(app, base_url="http://testserver") as bare:
        bare.cookies.update(cookies)
        # The signed-in browser without the tab header: the person's own routes say no.
        refused = bare.post("/api/v1/upload-requests", json={"name": "x", "days": 1})
        assert (refused.status_code, refused.json()["detail"]["code"]) == (400, "client_required")
        assert bare.delete("/api/v1/upload-requests/1").status_code == 400
        assert bare.post(f"/api/v1/u/{token}/files/extra", files={"file": ("a.pdf", PDF)}).status_code == 400
        # The stranger's upload goes, and it neither reads the cookie nor sets one.
        answer = send(bare, token)
        assert answer.status_code == 201 and "set-cookie" not in answer.headers


def test_the_page_routes_are_found_open_and_named(client: TestClient) -> None:
    from .test_routes import OPEN

    assert ("GET", "/api/v1/u/{token}") in OPEN and ("POST", "/api/v1/u/{token}/files") in OPEN
