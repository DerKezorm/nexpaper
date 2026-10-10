"""The import from Paperless-ngx against a made-up Paperless (``fake_paperless.py``): looking without writing, taking
everything over with its text and fields, the people and vaults, going on after a stop, never twice, what is skipped,
and a Paperless that misbehaves."""

from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import (
    FILED,
    INBOX,
    Account,
    Document,
    DocumentTag,
    Job,
    Kind,
    Note,
    PaperlessItem,
    Setting,
    Share,
    Tag,
    Vault,
    Version,
    VersionText,
)
from app.services import jobs, paperless, processing, settings_service

from . import fake_paperless, files
from .conftest import DATA_DIR, make_account, new_client
from .fake_paperless import Doc, Paperless
from .intake import process_all
from .papers import own_vault, shared_vault


@pytest.fixture(autouse=True)
def clean_folders() -> Iterator[None]:
    for name in ("paperless", "exports"):
        shutil.rmtree(Path(DATA_DIR) / name, ignore_errors=True)
    yield


@pytest.fixture
def fake() -> Iterator[tuple[Paperless, fake_paperless.Server]]:
    made = Paperless()
    server = fake_paperless.start(made)
    try:
        yield made, server
    finally:
        fake_paperless.stop(server)


def pdf(text: str) -> bytes:
    return files.make_pdf([text])


@pytest.fixture
def people() -> dict[str, Account]:
    return {"jule": make_account("jule"), "tom": make_account("tom")}


def fill(made: Paperless) -> None:
    """Three documents of three owners, the way a household's Paperless looks."""
    made.users = {1: {"username": "admin", "groups": []}, 2: {"username": "tom", "groups": [5]},
                  3: {"username": "scanner", "groups": []}}
    made.tags = {1: {"name": "Steuer 2026", "is_inbox_tag": False}, 2: {"name": "Posteingang", "is_inbox_tag": True}}
    made.correspondents = {1: "Stadtwerke Lindenau"}
    made.types = {1: "Rechnung", 2: "Nebenkostenabrechnung"}
    made.fields = {1: {"name": "Kundennummer", "data_type": "string"},
                   2: {"name": "Zahlart", "data_type": "select",
                       "extra_data": {"select_options": [{"id": "a1", "label": "Lastschrift"}]}}}
    made.add(Doc(1, "Strom März", pdf("Stromrechnung Lindenau Maerz"), archive=pdf("Stromrechnung archiv"),
                 content="Stromrechnung Lindenau Abschlag 84,00 EUR", correspondent=1, document_type=1, tags=[1],
                 owner=1, notes=[{"note": "bezahlt am 20.03.", "user": {"id": 1, "username": "admin"},
                                  "created": "2026-03-20T09:00:00Z"}],
                 custom_fields=[{"field": 1, "value": "K-778"}, {"field": 2, "value": "a1"}], asn=17,
                 original_file_name="strom.pdf"))
    made.add(Doc(2, "Nebenkosten 2025", pdf("Nebenkosten Wohnung"), content="Nebenkostenabrechnung Hausverwaltung",
                 created="2026-02-01", document_type=2, tags=[2], owner=2,
                 permissions={"view": {"users": [1], "groups": []}, "change": {"users": [], "groups": []}}))
    made.add(Doc(3, "Quittung Baumarkt", pdf("Quittung Baumarkt 14,90"), content="Quittung Baumarkt", owner=3,
                 created="2025-11-02"))


def connect(client: TestClient, made: Paperless, server: fake_paperless.Server) -> None:
    answer = client.put("/api/v1/settings/paperless", json={"url": server.url, "token": made.token, "private": True})
    assert answer.status_code == 200, answer.text


def mapping(client: TestClient, people: dict[str, Account]) -> list[dict[str, Any]]:
    return [{"paperless_id": 1, "user_id": people["jule"].id}, {"paperless_id": 2, "user_id": people["tom"].id},
            {"paperless_id": 3, "user_id": people["jule"].id}]


def run_import() -> None:
    jobs.run_pending(kinds=(jobs.IMPORT,))


def run_state(client: TestClient) -> dict[str, Any]:
    return client.get("/api/v1/settings/paperless").json()["run"]  # type: ignore[no-any-return]


@pytest.fixture
def ocr_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The operations the worker was asked for: the text of a document from Paperless is never recognised again."""
    seen: list[str] = []
    real = processing.spawn

    def spy(request: dict[str, Any], timeout: int) -> processing.Outcome:
        seen.append(str(request.get("op")))
        return real(request, timeout)

    monkeypatch.setattr(processing, "spawn", spy)
    return seen


def count(model: Any) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


# --- Looking first ---------------------------------------------------------------------------------------------------


def test_looking_says_what_paperless_holds_and_writes_nothing(client: TestClient, operator: Account,
                                                               people: dict[str, Account], fake: Any) -> None:
    made, server = fake
    fill(made)
    connect(client, made, server)
    kinds_before = count(Kind)
    with SessionLocal() as db:
        settings_before = {row.key: row.value for row in db.scalars(select(Setting))}
    answer = client.post("/api/v1/settings/paperless/check")
    assert answer.status_code == 200, answer.text
    found = answer.json()
    assert (found["documents"], found["tags"], found["correspondents"], found["document_types"]) == (3, 2, 1, 2)
    assert found["version"] == "2.14.7" and found["api_version"] == 7
    assert found["new_kinds"] == ["Nebenkostenabrechnung"]
    owners = {o["paperless_id"]: o for o in found["owners"]}
    assert owners[1]["name"] == "admin" and owners[1]["user_id"] == operator.id
    assert owners[2]["name"] == "tom" and owners[2]["user_id"] == people["tom"].id
    assert {p["name"] for p in found["people"]} >= {"jule", "tom", "tester"}
    # Nothing was written: no document, no kind, no item, the settings as they were.
    assert count(Document) == 0 and count(Kind) == kinds_before and count(PaperlessItem) == 0
    with SessionLocal() as db:
        assert {row.key: row.value for row in db.scalars(select(Setting))} == settings_before
    assert all("download" not in path for path in made.requests)


def test_the_token_is_kept_sealed_and_never_given_back(client: TestClient, operator: Account, fake: Any) -> None:
    made, server = fake
    connect(client, made, server)
    shown = client.get("/api/v1/settings/paperless")
    assert shown.json()["token_set"] is True and made.token not in shown.text
    with SessionLocal() as db:
        raw = json.dumps(settings_service.get(db, "paperless_token_enc"))
    assert made.token not in raw
    # A new address without a new token forgets the token: it would go to whatever host the address names.
    moved = client.put("/api/v1/settings/paperless", json={"url": "http://127.0.0.1:9/"})
    assert moved.json()["token_set"] is False
    gone = client.delete("/api/v1/settings/paperless")
    assert gone.json()["url"] == "" and gone.json()["token_set"] is False


def test_only_the_operator_in_a_browser_reaches_the_import(client: TestClient, operator: Account, fake: Any) -> None:
    made, server = fake
    member = make_account("member")
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with new_client(member) as stranger, TestClient(client.app, base_url="http://testserver") as device:
        for method, path, body in (("GET", "/api/v1/settings/paperless", None),
                                   ("PUT", "/api/v1/settings/paperless", {"url": server.url}),
                                   ("DELETE", "/api/v1/settings/paperless", None),
                                   ("POST", "/api/v1/settings/paperless/check", None),
                                   ("POST", "/api/v1/settings/paperless/start", {"where": "owner"}),
                                   ("POST", "/api/v1/settings/paperless/stop", None),
                                   ("GET", "/api/v1/settings/paperless/skipped", None)):
            extra = {"json": body} if body is not None else {}
            assert stranger.request(method, path, **extra).status_code == 403, path
            answer = device.request(method, path, headers={"Authorization": f"Bearer {token}"}, **extra)
            assert answer.status_code == 403 and answer.json()["detail"]["code"] == "browser_only", path
    assert made.requests == []


# --- Taking it over ----------------------------------------------------------------------------------------------------



def test_looking_counts_the_inbox_and_everything_can_wait_in_the_inbox_to_be_sorted_by_hand(
    client: TestClient, operator: Account, people: dict[str, Account], fake: Any,
) -> None:
    """The operator chooses at the start: sorted as in Paperless, or every document waits in the inbox. Looking first
    says how many there are and how many Paperless still has in its inbox, for that question."""
    made, server = fake
    fill(made)
    connect(client, made, server)
    looked = client.post("/api/v1/settings/paperless/check")
    assert looked.status_code == 200, looked.text
    assert (looked.json()["documents"], looked.json()["inbox_documents"]) == (3, 1)
    assert client.post("/api/v1/settings/paperless/start", json={"where": "owner", "sort": "elsewhere",
                                                                 "people": mapping(client, people)}).status_code == 422
    started = client.post("/api/v1/settings/paperless/start", json={"where": "owner", "sort": "inbox",
                                                                    "people": mapping(client, people)})
    assert started.status_code == 202, started.text
    assert started.json()["sort"] == "inbox"
    run_import()
    process_all()
    with SessionLocal() as db:
        statuses = [d.status for d in db.scalars(select(Document).join(
            PaperlessItem, PaperlessItem.document_id == Document.id))]
        assert statuses == [INBOX, INBOX, INBOX]
    # A second start goes on with the same choice.
    assert client.get("/api/v1/settings/paperless").json()["sort"] == "inbox"

def test_everything_comes_over_with_its_text_fields_people_and_no_new_recognition(
    client: TestClient, operator: Account, people: dict[str, Account], fake: Any, ocr_calls: list[str],
) -> None:
    made, server = fake
    fill(made)
    connect(client, made, server)
    started = client.post("/api/v1/settings/paperless/start", json={"where": "owner",
                                                                     "people": mapping(client, people)})
    assert started.status_code == 202, started.text
    assert started.json()["run"]["state"] == "queued"
    run_import()
    state = run_state(client)
    assert (state["state"], state["total"], state["done"], state["taken"], state["skipped"]) == ("done", 3, 3, 3, 0)
    process_all()
    assert "recognize" not in ocr_calls and "process" in ocr_calls
    with SessionLocal() as db:
        items = {i.paperless_id: i for i in db.scalars(select(PaperlessItem))}
        strom = db.get(Document, items[1].document_id)
        neben = db.get(Document, items[2].document_id)
        quittung = db.get(Document, items[3].document_id)
        assert strom is not None and neben is not None and quittung is not None
        # Owners as chosen, each in the own vault of its person.
        assert strom.owner_id == people["jule"].id and strom.vault_id == own_vault(people["jule"])
        assert neben.owner_id == people["tom"].id and neben.vault_id == own_vault(people["tom"])
        assert quittung.owner_id == people["jule"].id
        # Filed as in Paperless; the one with the inbox tag waits in the inbox, and the inbox tag is no tag here.
        assert strom.status == FILED and quittung.status == FILED and neben.status == INBOX
        assert strom.title == "Strom März" and str(strom.date) == "2026-03-14" and strom.source == "paperless"
        sender = db.get(Account, strom.owner_id)
        assert sender is not None
        tags = set(db.scalars(select(Tag.name).join(DocumentTag, DocumentTag.tag_id == Tag.id)
                              .where(DocumentTag.document_id == strom.id)))
        assert tags == {"Steuer 2026"}
        assert not list(db.scalars(select(DocumentTag).where(DocumentTag.document_id == neben.id)))
        kind = db.get(Kind, neben.kind_id)
        assert kind is not None and kind.name == "Nebenkostenabrechnung"
        # Made in the vault the document came to, never in the list of the whole server.
        assert kind.vault_id == neben.vault_id
        notes = [n.text for n in db.scalars(select(Note).where(Note.document_id == strom.id).order_by(Note.id))]
        assert notes[0] == "bezahlt am 20.03."
        assert "Kundennummer: K-778" in notes[1] and "Zahlart: Lastschrift" in notes[1] and "ASN: 17" in notes[1]
        # The text Paperless read is the text here, and its searchable copy is the archive.
        version = db.scalar(select(Version).where(Version.document_id == strom.id))
        assert version is not None and version.archive_path
        text = db.get(VersionText, version.id)
        assert text is not None and "Abschlag 84,00 EUR" in text.text and text.ocr_pages == 0
        archive = Path(DATA_DIR) / "dokumente" / version.archive_path
        assert archive.read_bytes() == made.documents[1].archive
        # Shared in Paperless with admin (whose documents go to jule): shared with jule here.
        share = db.get(Share, (neben.id, people["jule"].id))
        assert share is not None and share.right == "read"
    # The search finds it by the text from Paperless.
    with new_client(people["jule"]) as jule:
        found = jule.get("/api/v1/search", params={"q": "Abschlag"}).json()
        assert [hit["document"]["id"] for hit in found["items"]] == [strom.id]


def test_all_into_one_vault(client: TestClient, operator: Account, people: dict[str, Account], fake: Any) -> None:
    made, server = fake
    fill(made)
    connect(client, made, server)
    household = shared_vault("Haushalt", operator, (people["jule"], "edit"))
    answer = client.post("/api/v1/settings/paperless/start", json={"where": "vault", "vault_id": household,
                                                                    "people": mapping(client, people)})
    assert answer.status_code == 202, answer.text
    run_import()
    with SessionLocal() as db:
        assert set(db.scalars(select(Document.vault_id))) == {household}


def test_a_vault_of_another_person_cannot_be_the_target(client: TestClient, operator: Account,
                                                        people: dict[str, Account], fake: Any) -> None:
    made, server = fake
    connect(client, made, server)
    answer = client.post("/api/v1/settings/paperless/start",
                         json={"where": "vault", "vault_id": own_vault(people["tom"]), "people": []})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "paperless_vault_invalid"
    unknown = client.post("/api/v1/settings/paperless/start",
                          json={"where": "owner", "people": [{"paperless_id": 1, "user_id": 99999}]})
    assert unknown.json()["detail"]["code"] == "paperless_mapping_invalid"


def test_a_second_run_takes_only_what_is_new(client: TestClient, operator: Account, people: dict[str, Account],
                                             fake: Any) -> None:
    made, server = fake
    fill(made)
    connect(client, made, server)
    body = {"where": "owner", "people": mapping(client, people)}
    client.post("/api/v1/settings/paperless/start", json=body)
    run_import()
    assert count(Document) == 3
    made.add(Doc(4, "Versicherung", pdf("Versicherung Police"), owner=2, content="Police"))
    made.requests.clear()
    client.post("/api/v1/settings/paperless/start", json=body)
    run_import()
    assert count(Document) == 4
    state = run_state(client)
    assert (state["total"], state["done"], state["taken"]) == (4, 4, 1)
    # The documents taken before were not fetched again.
    assert not any("/api/documents/1/" in path for path in made.requests)


def test_a_stop_of_the_server_in_the_middle_goes_on_where_it_stopped(
    client: TestClient, operator: Account, people: dict[str, Account], fake: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    made, server = fake
    fill(made)
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": mapping(client, people)})
    real = paperless.take_one
    taken: list[int] = []

    def then_stop(*args: Any) -> int:
        made_id = real(*args)
        taken.append(made_id)
        if len(taken) == 1:
            jobs.stopping.set()
        return made_id

    monkeypatch.setattr(paperless, "take_one", then_stop)
    run_import()
    assert count(Document) == 1
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.kind == jobs.IMPORT))
        assert job is not None and job.state == "queued"
    assert run_state(client)["state"] == "running"
    jobs.stopping.clear()
    run_import()
    assert count(Document) == 3 and count(PaperlessItem) == 3
    assert run_state(client)["state"] == "done"


def test_the_operator_stops_and_starts_again(client: TestClient, operator: Account, people: dict[str, Account],
                                             fake: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    made, server = fake
    fill(made)
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": mapping(client, people)})
    real = paperless.take_one

    def and_stop(*args: Any) -> int:
        made_id = real(*args)
        with SessionLocal() as db:
            paperless.stop(db)
        return made_id

    monkeypatch.setattr(paperless, "take_one", and_stop)
    run_import()
    assert run_state(client)["state"] == "paused"
    assert count(Document) == 1
    monkeypatch.setattr(paperless, "take_one", real)
    # Going on keeps what was chosen: tom's document still goes to tom.
    assert client.post("/api/v1/settings/paperless/start", json={"resume": True}).status_code == 202
    run_import()
    assert run_state(client)["state"] == "done" and count(Document) == 3
    with SessionLocal() as db:
        owners = set(db.scalars(select(Document.owner_id)))
    assert owners == {people["jule"].id, people["tom"].id}


def test_two_starts_at_once_make_one_run(client: TestClient, operator: Account, people: dict[str, Account],
                                         fake: Any) -> None:
    made, server = fake
    fill(made)
    connect(client, made, server)
    body = {"where": "owner", "people": mapping(client, people)}
    answers: list[int] = []

    def go() -> None:
        with new_client(operator) as browser:
            answers.append(browser.post("/api/v1/settings/paperless/start", json=body).status_code)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(answers) == [202, 409, 409, 409]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == jobs.IMPORT)) == 1
    # While it runs nothing about the connection changes.
    assert client.put("/api/v1/settings/paperless", json={"url": server.url}).status_code == 409
    run_import()
    assert count(Document) == 3


# --- What is skipped -------------------------------------------------------------------------------------------------


def test_what_cannot_be_taken_is_skipped_with_its_reason(client: TestClient, operator: Account,
                                                         people: dict[str, Account], fake: Any,
                                                         caplog: pytest.LogCaptureFixture) -> None:
    made, server = fake
    made.users = {1: {"username": "admin", "groups": []}}
    made.add(Doc(1, "Gut", pdf("Gut"), owner=1))
    made.add(Doc(2, "Word mit PDF", b"PK\x03\x04 a word file" + b"\x00" * 200, archive=pdf("Word als PDF"),
                 owner=1, original_file_name="brief.docx"))
    made.add(Doc(3, "Word ohne PDF", b"PK\x03\x04 a word file" + b"\x00" * 200, owner=1))
    made.add(Doc(4, "Fehlt", pdf("Fehlt"), owner=1))
    made.add(Doc(5, "Kaputte Antwort", pdf("x"), owner=1))
    made.hook(r"^/api/documents/4/download/$", lambda h: h.send_json({"detail": "Not found."}, 404) or True)
    made.hook(r"^/api/documents/5/$", lambda h: h.send_json({"id": 6, "title": ["nope"]}) or True)
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    with caplog.at_level("INFO", logger="nexpaper.paperless"):
        run_import()
    state = run_state(client)
    assert state["state"] == "done" and state["taken"] == 2
    assert state["reasons"] == {"unsupported_type": 1, "file_missing": 1, "invalid_answer": 1}
    with SessionLocal() as db:
        items = {i.paperless_id: (i.state, i.reason) for i in db.scalars(select(PaperlessItem))}
        word = db.scalar(select(Document).where(Document.title == "Word mit PDF"))
        assert word is not None
        version = db.scalar(select(Version).where(Version.document_id == word.id))
        assert version is not None and version.original_path.endswith(".pdf")
    assert items[3] == ("skipped", "unsupported_type") and items[4] == ("skipped", "file_missing")
    assert "paperless_id=4 reason=file_missing" in caplog.text
    # A skipped one is tried again at the next run: here the file is back.
    made.hooks.clear()
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    assert run_state(client)["taken"] == 2 and count(Document) == 4


def test_an_office_file_with_a_pdf_from_paperless_is_taken_as_that_pdf_and_the_history_says_so(
        client: TestClient, operator: Account, fake: Any) -> None:
    from app.models import Event

    made, server = fake
    made.users = {1: {"username": "admin", "groups": []}}
    word = b"PK\x03\x04 a word file" + b"\x00" * 200
    made.add(Doc(1, "Brief", word, archive=pdf("Brief als PDF"), owner=1, original_file_name="brief.docx",
                 content="Brief als PDF"))
    made.add(Doc(2, "Tabelle", word, archive=pdf("Tabelle"), owner=1, original_file_name="Tabelle.XLSX"))
    made.add(Doc(3, "Ohne Endung", word, archive=pdf("Ohne"), owner=1, original_file_name="brief"))
    made.add(Doc(4, "Gut", pdf("Gut"), archive=pdf("Gut durchsuchbar"), owner=1))
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    assert run_state(client)["taken"] == 4
    seen = {}
    with SessionLocal() as db:
        for title in ("Brief", "Tabelle", "Ohne Endung", "Gut"):
            document = db.scalar(select(Document).where(Document.title == title))
            assert document is not None, title
            version = db.scalar(select(Version).where(Version.document_id == document.id))
            assert version is not None and version.original_path.endswith(".pdf"), title
            created = db.scalar(select(Event).where(Event.document_id == document.id, Event.action == "created"))
            assert created is not None
            seen[title] = created.detail
    assert seen["Brief"] == {"source": "paperless", "from_archive": "docx"}
    assert seen["Tabelle"] == {"source": "paperless", "from_archive": "xlsx"}
    assert seen["Ohne Endung"] == {"source": "paperless", "from_archive": "other"}
    # A document whose original was taken as it is says nothing of the kind.
    assert seen["Gut"] == {"source": "paperless"}


def test_the_list_of_the_skipped_gives_numbers_and_reasons_only_and_at_most_fifty(
        client: TestClient, operator: Account, fake: Any) -> None:
    made, server = fake
    made.users = {1: {"username": "admin", "groups": []}}
    made.add(Doc(1, "Gut", pdf("Gut"), owner=1))
    made.add(Doc(2, "Geheimer Titel", pdf("Fehlt"), owner=1, content="Geheimer Text"))
    made.hook(r"^/api/documents/2/download/$", lambda h: h.send_json({"detail": "Not found."}, 404) or True)
    assert client.get("/api/v1/settings/paperless/skipped").json() == {"items": [], "total": 0, "more": 0}
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    answer = client.get("/api/v1/settings/paperless/skipped")
    assert answer.status_code == 200
    assert answer.json() == {"items": [{"paperless_id": 2, "reason": "file_missing"}], "total": 1, "more": 0}
    assert "Geheimer" not in answer.text
    # Many: the first fifty by number, the rest only counted.
    from app import clock

    with SessionLocal() as db:
        origin = paperless._plan(db).origin
        for number in range(100, 160):
            db.add(PaperlessItem(origin=origin, paperless_id=number, document_id=None, state="skipped",
                                 reason="too_large", inbox=False, at=clock.now()))
        db.commit()
    many = client.get("/api/v1/settings/paperless/skipped").json()
    assert many["total"] == 61 and many["more"] == 11 and len(many["items"]) == 50
    assert [i["paperless_id"] for i in many["items"]][:3] == [2, 100, 101]


def gone_original(made: Paperless, *ids: int) -> None:
    """Paperless answers 404 for the original of these documents (the file is lost there), not for the copy."""
    pattern = r"^/api/documents/(" + "|".join(str(i) for i in ids) + r")/download/$"
    made.hook(pattern, lambda h: "original=true" in h.path and (h.send_json({"detail": "Not found."}, 404) or True))


def test_a_lost_original_is_replaced_by_the_searchable_copy_and_the_history_says_so(
        client: TestClient, operator: Account, fake: Any) -> None:
    from app.models import Event

    made, server = fake
    made.users = {1: {"username": "admin", "groups": []}}
    made.add(Doc(1, "Verloren", pdf("Original"), archive=pdf("Durchsuchbar"), owner=1, content="Durchsuchbar"))
    made.add(Doc(2, "Heil", pdf("Heil"), archive=pdf("Heil durchsuchbar"), owner=1))
    gone_original(made, 1)
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    state = run_state(client)
    assert state["taken"] == 2 and state["skipped"] == 0
    with SessionLocal() as db:
        lost = db.scalar(select(Document).where(Document.title == "Verloren"))
        whole = db.scalar(select(Document).where(Document.title == "Heil"))
        assert lost is not None and whole is not None
        version = db.scalar(select(Version).where(Version.document_id == lost.id))
        assert version is not None and version.original_path.endswith(".pdf")
        # What was taken is the copy: the file on the disk is the very bytes Paperless gave as the copy.
        assert (Path(DATA_DIR) / "dokumente" / version.original_path).read_bytes() == pdf("Durchsuchbar")
        created = {d.title: db.scalar(select(Event).where(Event.document_id == d.id, Event.action == "created"))
                   for d in (lost, whole)}
        assert created["Verloren"] is not None and created["Verloren"].detail == {
            "source": "paperless", "original_missing": True}
        assert created["Heil"] is not None and created["Heil"].detail == {"source": "paperless"}
        item = db.scalar(select(PaperlessItem).where(PaperlessItem.paperless_id == 1))
        assert item is not None and item.state == "done"
    assert not list((Path(DATA_DIR) / "dokumente").rglob(".incoming-*"))


@pytest.mark.parametrize("archive", [
    None,
    b"PK" + bytes([3, 4]) + b" the copy is no pdf" + bytes(100),
    files.make_pdf(["abgeschnitten"])[:200],
], ids=["no copy", "not a pdf", "cut off pdf"])
def test_a_lost_original_without_a_whole_copy_stays_skipped_and_is_tried_again_at_the_next_run(
        client: TestClient, operator: Account, fake: Any, archive: bytes | None) -> None:
    made, server = fake
    made.users = {1: {"username": "admin", "groups": []}}
    made.add(Doc(1, "Verloren", pdf("Original"), archive=archive, owner=1))
    made.hook(r"^/api/documents/1/download/$", lambda h: ("original=true" in h.path or archive is None)
              and (h.send_json({"detail": "Not found."}, 404) or True))
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    state = run_state(client)
    assert state["taken"] == 0 and state["reasons"] == {"file_missing": 1}
    assert count(Document) == 0
    assert not list((Path(DATA_DIR) / "dokumente").rglob(".incoming-*"))
    # The file is found again in Paperless: the next run takes the document (file_missing is not for good).
    made.hooks.clear()
    made.documents[1].archive = pdf("Wieder da")
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    assert run_state(client)["taken"] == 1 and count(Document) == 1


@pytest.mark.parametrize("archive", [
    b"PK\x03\x04 the archive is a word file again" + b"\x00" * 100,
    b"<html><script>alert(1)</script></html>",
    files.make_pdf(["abgeschnitten"])[:200],
], ids=["not a pdf", "a page", "cut off pdf"])
def test_an_office_file_whose_pdf_from_paperless_is_no_whole_pdf_is_skipped(
        client: TestClient, operator: Account, fake: Any, archive: bytes) -> None:
    made, server = fake
    made.users = {1: {"username": "admin", "groups": []}}
    made.add(Doc(1, "Brief", b"PK\x03\x04 a word file" + b"\x00" * 200, archive=archive, owner=1,
                 original_file_name="brief.docx"))
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    state = run_state(client)
    assert state["taken"] == 0 and state["reasons"] == {"unsupported_type": 1}
    assert count(Document) == 0
    assert not list((Path(DATA_DIR) / "dokumente").rglob(".incoming-*"))


def test_a_webp_original_from_paperless_is_taken_as_it_is(client: TestClient, operator: Account, fake: Any) -> None:
    made, server = fake
    made.users = {1: {"username": "admin", "groups": []}}
    made.add(Doc(1, "Foto", files.make_image("webp"), archive=pdf("Foto"), owner=1, original_file_name="foto.webp"))
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    assert run_state(client)["taken"] == 1
    with SessionLocal() as db:
        version = db.scalar(select(Version))
        assert version is not None and version.original_path.endswith(".webp")


def test_a_file_over_the_limit_is_skipped(client: TestClient, operator: Account, fake: Any) -> None:
    made, server = fake
    made.add(Doc(1, "Riesig", files.make_pdf(["gross"], padding=1_200_000)))
    made.add(Doc(2, "Klein", pdf("klein")))
    with SessionLocal() as db:
        settings_service.save(db, {"upload_max_mb": 1})
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    assert run_state(client)["reasons"] == {"too_large": 1}
    assert count(Document) == 1
    assert not list((Path(DATA_DIR) / "dokumente").rglob(".incoming-*"))


def test_a_file_the_person_has_already_is_not_taken_twice(client: TestClient, operator: Account, fake: Any) -> None:
    from .intake import upload_one

    made, server = fake
    same = pdf("Doppelt")
    upload_one(client, "doppelt.pdf", same)
    made.add(Doc(1, "Doppelt", same))
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    assert run_state(client)["reasons"] == {"exists": 1} and count(Document) == 1
    # And not even looked at again.
    made.requests.clear()
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    assert not any("/api/documents/1/" in path for path in made.requests)


def test_a_full_disk_stops_the_run(client: TestClient, operator: Account, fake: Any,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    made, server = fake
    made.add(Doc(1, "Eins", pdf("eins")))
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    monkeypatch.setattr(paperless.shutil, "disk_usage", lambda _path: shutil._ntuple_diskusage(10, 9, 1))  # type: ignore[attr-defined]
    run_import()
    state = run_state(client)
    assert state["state"] == "failed" and state["error"] == "disk_full" and count(Document) == 0


# --- A Paperless that misbehaves -------------------------------------------------------------------------------------


def check_code(client: TestClient) -> str:
    answer = client.post("/api/v1/settings/paperless/check")
    assert answer.status_code >= 400, answer.text
    return str(answer.json()["detail"]["code"])


def test_the_own_network_needs_the_switch_and_link_local_never(client: TestClient, operator: Account,
                                                               fake: Any) -> None:
    made, server = fake
    client.put("/api/v1/settings/paperless", json={"url": server.url, "token": made.token, "private": False})
    assert check_code(client) == "paperless_address_private"
    client.put("/api/v1/settings/paperless", json={"url": "http://169.254.169.254/", "token": made.token,
                                                   "private": True})
    assert check_code(client) == "paperless_address_refused"
    assert made.requests == []


def test_a_wrong_token_and_something_that_is_not_paperless(client: TestClient, operator: Account, fake: Any) -> None:
    made, server = fake
    client.put("/api/v1/settings/paperless", json={"url": server.url, "token": "wrong" * 4, "private": True})
    assert check_code(client) == "paperless_token_refused"
    connect(client, made, server)
    made.api_version = 0
    assert check_code(client) == "paperless_not_paperless"
    made.api_version = 2
    assert check_code(client) == "paperless_too_old"


def test_a_slow_answer_ends_at_the_deadline(client: TestClient, operator: Account, fake: Any,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    made, server = fake
    connect(client, made, server)
    monkeypatch.setattr(paperless, "JSON_SECONDS", 1.0)
    made.hook(r"^/api/documents/$", lambda h: fake_paperless.dribble(h, 0.2, 20))
    assert check_code(client) == "paperless_timeout"


def test_no_redirect_and_no_next_address_is_followed(client: TestClient, operator: Account, fake: Any) -> None:
    made, server = fake
    other = Paperless()
    elsewhere = fake_paperless.start(other)
    try:
        connect(client, made, server)
        for number in range(1, 1003):
            made.documents[number] = Doc(number, f"D{number}", b"%PDF-1.4")
        made.next_url = elsewhere.url + "api/documents/?page=2"
        assert client.post("/api/v1/settings/paperless/check").status_code == 200
        assert other.requests == []

        def redirect(handler: Any) -> bool:
            handler.send_response(302)
            handler.send_header("Location", elsewhere.url + "api/documents/")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return True

        made.hook(r"^/api/documents/$", redirect)
        assert check_code(client) == "paperless_redirected"
        assert other.requests == []
    finally:
        fake_paperless.stop(elsewhere)


def test_a_huge_answer_is_not_read(client: TestClient, operator: Account, fake: Any,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    made, server = fake
    connect(client, made, server)
    monkeypatch.setattr(paperless, "JSON_MAX", 2000)
    made.correspondents = {i: "Absender " + "x" * 50 for i in range(1, 200)}
    assert check_code(client) == "paperless_unreadable"


def test_answers_of_the_wrong_kind_are_read_carefully() -> None:
    found = paperless.Names(tags={1: ("Steuer", False)}, correspondents={1: "Stadtwerke"})
    hostile = {"id": 7, "title": {"a": 1}, "tags": ["1", 1, True, 2**40], "correspondent": "1", "owner": True,
               "content": "Text\x00mit\x07Steuerzeichen", "notes": [{"note": 5}, "x", {"note": "ok", "user": "1"}],
               "custom_fields": [{"field": "1", "value": "x"}], "created": "kein Datum",
               "permissions": {"view": {"users": ["2", 3], "groups": None}}}
    incoming = paperless.read(hostile, found, 7)
    assert incoming.title == "" and incoming.tags == ["Steuer"] and incoming.sender == "" and incoming.owner is None
    assert "\x00" not in incoming.content and "\x07" not in incoming.content
    assert incoming.notes == [("ok", None, None)] and incoming.fields == "" and incoming.day is None
    assert incoming.readers == [3]
    with pytest.raises(paperless.Skip):
        paperless.read({"id": 8}, found, 7)
    with pytest.raises(paperless.Skip):
        paperless.read(["not", "a", "dict"], found, 7)


@pytest.mark.parametrize("url", ["ftp://example.com/", "http://user:pw@example.com/", "http://example.com/?x=1",
                                 "http://example.com:99999/", "javascript:alert(1)", "", "http://exa mple.com/"])
def test_addresses_that_are_none(url: str) -> None:
    with pytest.raises(paperless.Failure):
        paperless.check_address(url)


def test_the_api_at_the_end_of_an_address_is_dropped() -> None:
    assert paperless.check_address("https://paperless.example.com/api/") == "https://paperless.example.com/"
    assert paperless.check_address("http://example.com:8000/sub/api") == "http://example.com:8000/sub/"


def test_vault_choices_name_shared_vaults_and_the_own(client: TestClient, operator: Account,
                                                      people: dict[str, Account], fake: Any) -> None:
    made, server = fake
    fill(made)
    connect(client, made, server)
    shared_vault("Firma", operator)
    found = client.post("/api/v1/settings/paperless/check").json()
    with SessionLocal() as db:
        names = {v.id: v.name for v in db.scalars(select(Vault))}
    chosen = {names[v["id"]] for v in found["vaults"]}
    assert "Firma" in chosen and "tom" not in chosen and "jule" not in chosen


def test_shares_come_over_as_paperless_2_14_answers_them(client: TestClient, operator: Account,
                                                         people: dict[str, Account], fake: Any) -> None:
    """The permissions only come with ``full_perms=true`` (as in 2.14.7): a user here of the same name gets the share,
    through a group too; nobody gets a share of what they own, and somebody nobody here is called gets none."""
    made, server = fake
    lea = make_account("lea")
    made.users = {3: {"username": "admin", "groups": []}, 4: {"username": "jule", "groups": []},
                  5: {"username": "tom", "groups": []}, 6: {"username": "lea", "groups": [9]},
                  7: {"username": "fremd", "groups": []}}
    made.add(Doc(1, "Heizungswartung", pdf("Heizungswartung"), owner=4,
                 permissions={"view": {"users": [5, 4, 7], "groups": []}, "change": {"users": [], "groups": [9]}}))
    made.add(Doc(2, "Nur bei jule", pdf("Nur bei jule"), owner=4))
    connect(client, made, server)
    found = client.post("/api/v1/settings/paperless/check").json()
    proposed = {o["paperless_id"]: o["user_id"] for o in found["owners"]}
    assert proposed == {4: people["jule"].id}
    client.post("/api/v1/settings/paperless/start",
                json={"where": "owner", "people": [{"paperless_id": 4, "user_id": people["jule"].id}]})
    run_import()
    assert any("/api/documents/1/?full_perms=true" in path for path in made.requests)
    with SessionLocal() as db:
        heating = db.scalar(select(Document).where(Document.title == "Heizungswartung"))
        assert heating is not None and heating.owner_id == people["jule"].id
        shares = {s.user_id: s.right for s in db.scalars(select(Share).where(Share.document_id == heating.id))}
        assert shares == {people["tom"].id: "read", lea.id: "edit"}
        alone = db.scalar(select(Document).where(Document.title == "Nur bei jule"))
        assert alone is not None
        assert not list(db.scalars(select(Share).where(Share.document_id == alone.id)))


def test_into_one_vault_the_owner_is_somebody_in_that_vault(client: TestClient, operator: Account,
                                                          people: dict[str, Account], fake: Any) -> None:
    """All into one shared vault: jule owns the document in Paperless but is not in the vault, so she would own a
    document she cannot see. The operator who started the run owns it instead, and jule keeps it as a share with the
    right to change it; tom, a reader there, gets it to read. Nobody gets a share of what they own."""
    made, server = fake
    made.users = {4: {"username": "jule", "groups": []}, 5: {"username": "tom", "groups": []},
                  3: {"username": "tester", "groups": []}}
    made.add(Doc(1, "Heizungswartung", pdf("Heizungswartung"), owner=4,
                 permissions={"view": {"users": [3, 5], "groups": []}, "change": {"users": [], "groups": []}}))
    connect(client, made, server)
    firma = shared_vault("Firma", operator)
    client.post("/api/v1/settings/paperless/start",
                json={"where": "vault", "vault_id": firma, "people": [{"paperless_id": 4, "user_id": people["jule"].id}]})
    run_import()
    with SessionLocal() as db:
        document = db.scalar(select(Document).where(Document.title == "Heizungswartung"))
        assert document is not None and document.owner_id == operator.id and document.vault_id == firma
        shares = {s.user_id: s.right for s in db.scalars(select(Share))}
    assert shares == {people["jule"].id: "edit", people["tom"].id: "read"}


def test_into_one_vault_the_operator_is_not_in_its_manager_owns(client: TestClient, operator: Account,
                                                                 people: dict[str, Account], fake: Any) -> None:
    from app.models import VaultMember

    made, server = fake
    made.users = {4: {"username": "jule", "groups": []}}
    made.add(Doc(1, "Heizungswartung", pdf("Heizungswartung"), owner=4))
    connect(client, made, server)
    firma = shared_vault("Firma", operator, (people["tom"], "manage"))
    with SessionLocal() as db:
        db.delete(db.get(VaultMember, (firma, operator.id)))
        db.commit()
    client.post("/api/v1/settings/paperless/start",
                json={"where": "vault", "vault_id": firma, "people": [{"paperless_id": 4, "user_id": people["jule"].id}]})
    run_import()
    with SessionLocal() as db:
        document = db.scalar(select(Document))
        assert document is not None and document.owner_id == people["tom"].id
        shares = {s.user_id: s.right for s in db.scalars(select(Share))}
    assert shares == {people["jule"].id: "edit"}


def test_each_person_is_told_what_the_import_brought_them(
    client: TestClient, operator: Account, people: dict[str, Account], fake: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import tell

    told: dict[int, tell.Notice] = {}
    monkeypatch.setattr(tell, "person", lambda account_id, notice: told.__setitem__(account_id, notice))
    made, server = fake
    fill(made)
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": mapping(client, people)})
    run_import()
    assert set(told) == {people["jule"].id, people["tom"].id}, "people who got nothing hear nothing"
    # jule owns two documents and has the one tom's inbox holds shared; tom owns one and it waits in his inbox.
    assert told[people["jule"].id].texts["en"][1] == "3 documents from Paperless are now yours."
    assert told[people["jule"].id].url == "/"
    assert told[people["tom"].id].texts["en"][1] == (
        "1 documents from Paperless are now yours. 1 are waiting in your inbox.")
    assert told[people["tom"].id].url == "/eingang"
    assert told[people["tom"].id].texts["de"][0] == "Paperless-Import fertig"
    # Numbers only: no title, sender or file name of a document is in a notice.
    for notice in told.values():
        every = " ".join(part for pair in notice.texts.values() for part in pair) + notice.mail_body
        assert "Strom" not in every and "Stadtwerke" not in every and "Nebenkosten" not in every


def test_an_import_that_took_nothing_tells_nobody(
    client: TestClient, operator: Account, people: dict[str, Account], fake: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import tell

    told: list[int] = []
    monkeypatch.setattr(tell, "person", lambda account_id, notice: told.append(account_id))
    made, server = fake
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": mapping(client, people)})
    run_import()
    assert told == []
