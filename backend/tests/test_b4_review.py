"""Round two of block B4: how many people and links a document is shared with (only for who may share it), where its
file lies (relative, nothing above the folder for documents), deleting for good only from a browser, and titles that
cannot turn the direction of their text around."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import Account

from . import files
from .conftest import make_account, new_client
from .intake import process_all, upload_one
from .papers import add_document, own_vault, shared_vault

RLO, PDF = "\u202e", "\u202c"


def test_a_document_counts_its_shares_and_live_links_for_who_may_share_it(client: TestClient, operator: Account) -> None:
    tom, lea = make_account("tom"), make_account("lea")
    vault = shared_vault("Haushalt", operator, (tom, "edit"))
    doc = add_document(vault, operator, "Steuerbescheid")
    plain = add_document(vault, operator, "Ohne alles")
    assert client.put(f"/api/v1/documents/{doc}/shares/{lea.id}", json={"right": "read"}).status_code == 200
    first = client.post(f"/api/v1/documents/{doc}/links", json={"recipient": "Steuerbüro", "days": 7}).json()
    client.post(f"/api/v1/documents/{doc}/links", json={"recipient": "Bank", "days": 7})
    assert client.delete(f"/api/v1/documents/{doc}/links/{first['id']}").status_code == 204
    shown = client.get(f"/api/v1/documents/{doc}").json()
    assert (shown["share_count"], shown["link_count"]) == (1, 1), "a revoked link no longer counts"
    assert (client.get(f"/api/v1/documents/{plain}").json()["share_count"], client.get(f"/api/v1/documents/{plain}").json()["link_count"]) == (0, 0)
    # In the list and the search the same numbers.
    listed = {d["id"]: d for d in client.get("/api/v1/documents").json()["items"]}
    assert (listed[doc]["share_count"], listed[doc]["link_count"]) == (1, 1)
    found = client.get("/api/v1/search?q=steuerbescheid").json()["items"][0]["document"]
    assert (found["share_count"], found["link_count"]) == (1, 1)
    # Tom may change it but not share it (not his, not a manager): he learns nothing of it.
    with new_client(tom) as session:
        his = session.get(f"/api/v1/documents/{doc}").json()
        assert his["can_share"] is False and his["share_count"] is None and his["link_count"] is None
    # Lea sees it through the share: nothing about the others either.
    with new_client(lea) as session:
        hers = session.get(f"/api/v1/documents/{doc}").json()
        assert hers["share_count"] is None and hers["link_count"] is None
    # Links switched off by the operator: none works.
    assert client.put("/api/v1/settings", json={"links_allowed": False}).status_code == 200
    assert client.get(f"/api/v1/documents/{doc}").json()["link_count"] == 0


def test_a_version_names_where_its_file_lies_from_the_folder_for_documents_on(client: TestClient, operator: Account) -> None:
    made = upload_one(client, "Rechnung.pdf", files.make_pdf(["Stadtwerke Lindenau Rechnung mit genug Text darauf"]))
    process_all()
    client.patch(f"/api/v1/documents/{made['id']}", json={"sender": "Stadtwerke Lindenau", "date": "2026-10-01", "title": "Abschlag"})
    process_all()
    path = client.get(f"/api/v1/documents/{made['id']}/versions").json()[0]["path"]
    assert path.split("/")[1:] == ["2026", "Stadtwerke Lindenau", path.split("/")[-1]] and path.endswith(".pdf")
    assert ":" not in path and not path.startswith("/") and "dokumente" not in path and ".." not in path.split("/")
    with new_client(make_account("outsider")) as stranger:
        assert stranger.get(f"/api/v1/documents/{made['id']}/versions").status_code == 404


def test_shown_paths_never_leave_the_storage() -> None:
    from app.routers.files import shown_path

    assert shown_path("Haushalt/2026/Anbieter/2026-03-14 Rechnung.pdf") == "Haushalt/2026/Anbieter/2026-03-14 Rechnung.pdf"
    assert shown_path("Haushalt\\2026\\x.pdf") == "Haushalt/2026/x.pdf"
    for bad in ("", "/data/dokumente/x.pdf", "C:/Daten/x.pdf", "\\\\server\\x.pdf", "a/../b.pdf", "a//b.pdf", "./a.pdf"):
        assert shown_path(bad) == "", bad


def test_deleting_for_good_needs_the_browser_not_a_device(client: TestClient, operator: Account) -> None:
    doc = add_document(own_vault(operator), operator, "Alt")
    assert client.delete(f"/api/v1/documents/{doc}").status_code == 200
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(client.app, base_url="http://testserver") as device:
        refused = device.post(f"/api/v1/documents/{doc}/purge", headers={"Authorization": f"Bearer {token}"})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "browser_only"
    assert client.get(f"/api/v1/documents/{doc}").json()["status"] == "trash"
    assert client.post(f"/api/v1/documents/{doc}/purge").status_code == 204


def test_a_title_cannot_turn_its_text_around(client: TestClient, operator: Account) -> None:
    doc = add_document(own_vault(operator), operator, "Brief")
    answer = client.patch(f"/api/v1/documents/{doc}", json={"title": f"strom {RLO}txt.exe{PDF} Rechnung"})
    assert answer.status_code == 200 and answer.json()["title"] == "strom txt.exe Rechnung"
    for mark in ("\u202a", "\u202b", "\u202d", "\u2066", "\u2067", "\u2068", "\u2069", "\u200e", "\u200f", "\u061c"):
        assert client.patch(f"/api/v1/documents/{doc}", json={"title": f"a{mark}b"}).json()["title"] == "ab", repr(mark)
    # A title made of the name of a file loses them too; a note keeps its text as written.
    made = upload_one(client, f"Rechnung{RLO}fdp.exe.pdf", files.make_pdf(["Ein Brief mit genug Text darauf, wirklich genug"]))
    assert made["title"] == "Rechnungfdp.exe"
    note = client.post(f"/api/v1/documents/{doc}/notes", json={"text": f"Hebräisch {RLO}abc"}).json()
    assert note["text"] == f"Hebräisch {RLO}abc"


def _send_in_pieces(client: TestClient, name: str, data: bytes) -> dict:
    import hashlib

    started = client.post("/api/v1/uploads", json={"filename": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    assert started.status_code == 201, started.text
    upload = started.json()["upload"]["id"]
    assert client.put(f"/api/v1/uploads/{upload}?offset=0", content=data, headers={"Content-Type": "application/octet-stream"}).status_code == 200
    finished = client.post(f"/api/v1/uploads/{upload}/finish")
    assert finished.status_code in (200, 201), finished.text
    return finished.json()["document"]


def test_a_title_is_made_of_a_file_name_once_in_pieces_as_in_one_request(client: TestClient, operator: Account) -> None:
    whole = upload_one(client, "Rechnung 1.2 Strom.pdf", files.make_pdf(["Rechnung eins mit genug Text darauf, wirklich"]))
    pieces = _send_in_pieces(client, "Rechnung 1.2 Strom.pdf", files.make_pdf(["Rechnung zwei mit genug Text darauf, wirklich"]))
    assert whole["title"] == pieces["title"] == "Rechnung 1.2 Strom"
    turned = _send_in_pieces(client, f"strom {RLO}txt.exe{PDF} Rechnung.pdf", files.make_pdf(["Rechnung drei mit genug Text darauf, wirklich"]))
    assert turned["title"] == "strom txt.exe Rechnung"


def test_a_file_name_of_nothing_but_direction_characters_gets_the_title_document(client: TestClient, operator: Account) -> None:
    from app.services import filetypes

    name = f"{RLO}{PDF}\u2066\u2069.pdf"
    assert upload_one(client, name, files.make_pdf(["Ein Brief vier mit genug Text darauf, wirklich"]))["title"] == "Document"
    assert _send_in_pieces(client, name, files.make_pdf(["Ein Brief fünf mit genug Text darauf, wirklich"]))["title"] == "Document"
    # The folder and the mailbox take their titles the same way (a mail without a file name: its subject).
    assert filetypes.title_from(name) == "Document"
    assert filetypes.plain_title(f"{RLO}\u200f") == "Document"
    assert filetypes.plain_title(f"Ihre {RLO}Rechnung") == "Ihre Rechnung"
    assert filetypes.file_name(f"ordner/sub/{RLO}Abrechnung 2.1.pdf") == "Abrechnung 2.1.pdf"


def test_who_sees_a_document_through_a_share_gets_its_place_without_the_vault(client: TestClient, operator: Account) -> None:
    lea = make_account("lea")
    doc = add_document(own_vault(operator), operator, "Brief", sender="Anbieter")
    assert client.put(f"/api/v1/documents/{doc}/shares/{lea.id}", json={"right": "read"}).status_code == 200
    mine = client.get(f"/api/v1/documents/{doc}/versions").json()[0]["path"]
    with new_client(lea) as session:
        hers = session.get(f"/api/v1/documents/{doc}/versions").json()[0]["path"]
    assert mine.split("/", 1)[1] == hers and mine.split("/", 1)[0] not in hers


def test_a_place_outside_the_storage_is_never_named(client: TestClient, operator: Account) -> None:
    from sqlalchemy import update

    from app.db import SessionLocal
    from app.models import Version

    doc = add_document(own_vault(operator), operator, "Brief")
    for stored in ("/data/dokumente/x.pdf", "C:/Daten/x.pdf", "a/../../secret.pdf"):
        with SessionLocal() as db:
            db.execute(update(Version).where(Version.document_id == doc).values(original_path=stored))
            db.commit()
        assert client.get(f"/api/v1/documents/{doc}/versions").json()[0]["path"] == "", stored


def test_only_who_may_share_a_document_learns_whom_it_is_shared_with(client: TestClient, operator: Account) -> None:
    lea, max_ = make_account("lea"), make_account("max")
    vault = shared_vault("Haushalt", operator, (lea, "read"))
    doc = add_document(vault, operator, "Brief")
    assert client.put(f"/api/v1/documents/{doc}/shares/{max_.id}", json={"right": "read"}).status_code == 200
    assert [s["user"]["name"] for s in client.get(f"/api/v1/documents/{doc}/shares").json()] == ["max"]
    for person in (lea, max_):
        with new_client(person) as session:
            for what in ("shares", "links"):
                answer = session.get(f"/api/v1/documents/{doc}/{what}")
                assert answer.status_code == 403 and answer.json()["detail"]["code"] == "forbidden", (person.name, what)
    with new_client(make_account("stranger")) as stranger:
        assert stranger.get(f"/api/v1/documents/{doc}/shares").status_code == 404
