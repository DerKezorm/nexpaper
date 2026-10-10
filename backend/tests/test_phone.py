"""The phone: what the quick upload shows (only what the person may see), uploads that say where they came from, the
place the share menu of Android sends to (never takes files itself), the iPhone shortcut's link, keys for uploading
with their limits, and the camera allowed for this site alone."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clock, main
from app.db import SessionLocal
from app.middleware import SCANNER_CSP
from app.models import EDIT, FILED, INBOX, PROCESSING, READ, Account, Document
from app.services import apikeys

from .conftest import make_account, new_client
from .files import make_pdf
from .intake import post_files, upload_key
from .papers import add_document, own_vault, shared_vault


@pytest.fixture(autouse=True)
def fresh_counts() -> Iterator[None]:
    apikeys.forget()
    yield
    apikeys.forget()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def program() -> TestClient:
    return TestClient(main.app, base_url="http://testserver")


# --- The quick upload -------------------------------------------------------------------------------------------------


def test_the_quick_upload_shows_the_own_latest_and_what_waits(client: TestClient, operator: Account,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    mine = own_vault(operator)
    noor = make_account("noor")
    house = shared_vault("Haushalt", operator, (noor, EDIT))
    reading = add_document(mine, operator, "Wird gelesen", status=PROCESSING)
    waiting = add_document(house, operator, "Stromrechnung", status=INBOX)
    filed_now = add_document(mine, operator, "Heute abgelegt", status=FILED)
    old = add_document(mine, operator, "Alt abgelegt", status=FILED)
    with SessionLocal() as db:
        row = db.get(Document, old)
        assert row is not None
        row.added_at = clock.now() - timedelta(days=2)
        db.commit()
    # Somebody else's document in a vault the operator sees counts for the inbox, not for "your latest".
    theirs = add_document(house, noor, "Von Noor", status=INBOX)
    # A document in Noor's own vault is nowhere.
    add_document(own_vault(noor), noor, "Geheim", status=INBOX)
    body = client.get("/api/v1/quick").json()
    assert [doc["id"] for doc in body["recent"]] == [filed_now, waiting, reading]
    assert body["inbox"] == 2 and body["processing"] == 1
    assert body["target_vault_id"] == mine
    assert [(vault["id"], vault["mine"]) for vault in body["vaults"]] == [(mine, True), (house, False)]
    assert theirs not in [doc["id"] for doc in body["recent"]]


def test_the_quick_upload_names_only_vaults_one_may_add_to_and_follows_the_choice(client: TestClient,
                                                                                    operator: Account) -> None:
    noor = make_account("noor")
    read_only = shared_vault("Nur lesen", operator, (noor, READ))
    adding = shared_vault("Haushalt", operator, (noor, EDIT))
    with new_client(noor) as browser:
        body = browser.get("/api/v1/quick").json()
        assert [vault["name"] for vault in body["vaults"]] == ["noor", "Haushalt"]
        assert read_only not in [vault["id"] for vault in body["vaults"]]
        assert browser.put("/api/v1/me/preferences", json={"default_vault": read_only}).status_code == 422
        assert browser.put("/api/v1/me/preferences", json={"default_vault": adding}).status_code == 200
        assert browser.get("/api/v1/quick").json()["target_vault_id"] == adding


def test_a_stranger_and_a_key_for_uploading_see_nothing_of_it(client: TestClient, operator: Account) -> None:
    add_document(own_vault(operator), operator, "Meins", status=INBOX)
    with new_client(make_account("noor")) as stranger:
        body = stranger.get("/api/v1/quick").json()
        assert body["recent"] == [] and body["inbox"] == 0
    with program() as anyone:
        assert anyone.get("/api/v1/quick").status_code == 401
        assert anyone.get("/api/v1/quick", headers=bearer(upload_key(operator))).status_code == 403
        assert anyone.get("/api/v1/quick", headers=bearer(upload_key(operator, "read"))).status_code == 200


def test_the_quick_upload_is_reached_by_a_device(client: TestClient, operator: Account) -> None:
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with program() as device:
        assert device.get("/api/v1/quick", headers=bearer(token)).status_code == 200


# --- Where a file comes from ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("said", ["camera", "share"])
def test_an_upload_says_it_came_from_the_camera_or_the_share_menu(client: TestClient, operator: Account,
                                                                   said: str) -> None:
    answer = client.post(f"/api/v1/documents?source={said}",
                         files=[("file", ("Scan.pdf", make_pdf(), "application/pdf"))])
    assert answer.status_code == 201, answer.text
    assert answer.json()["items"][0]["document"]["source"] == said
    assert client.post("/api/v1/documents?source=mail",
                       files=[("file", ("x.pdf", make_pdf(), "application/pdf"))]).status_code == 422


def test_an_upload_in_pieces_says_where_it_came_from(client: TestClient, operator: Account) -> None:
    import hashlib

    content = make_pdf(["Seite eins"])
    started = client.post("/api/v1/uploads", json={"filename": "Scan.pdf", "size": len(content),
                                                   "sha256": hashlib.sha256(content).hexdigest(), "source": "camera"})
    assert started.status_code == 201, started.text
    upload = started.json()["upload"]["id"]
    assert client.put(f"/api/v1/uploads/{upload}?offset=0", content=content,
                      headers={"Content-Type": "application/octet-stream"}).status_code == 200
    assert client.post(f"/api/v1/uploads/{upload}/finish").json()["document"]["source"] == "camera"


# --- The share menu of Android ----------------------------------------------------------------------------------------


@pytest.fixture
def built(tmp_path: Path) -> Iterator[TestClient]:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>nexpaper</title>", encoding="utf-8")
    (dist / "scanner").mkdir()
    (dist / "scanner" / "worker.js").write_text("self.onmessage = () => {}\n", encoding="utf-8")
    app = FastAPI()
    main._mount_frontend(app, dist)
    from app.middleware import RequestContextMiddleware

    app.add_middleware(RequestContextMiddleware)
    with TestClient(app, base_url="http://testserver") as browser:
        yield browser


def documents_count() -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(Document.id)).all())


def test_files_shared_past_the_service_worker_are_never_taken(built: TestClient, operator: Account,
                                                              client: TestClient) -> None:
    """A form to ``/teilen`` carries the cookie and no header of our own: it might come from any site. Without a
    session, with one, and from another site, nothing is read and nothing is kept; the page is sent on."""
    shared = [("files", ("Rechnung.pdf", make_pdf(), "application/pdf"))]
    for cookies, headers in (({}, {}), (dict(client.cookies), {}),
                             (dict(client.cookies), {"Origin": "https://evil.example.org", "Sec-Fetch-Site": "cross-site"})):
        built.cookies.clear()
        for name, value in cookies.items():
            built.cookies.set(name, value)
        answer = built.post("/teilen", files=shared, headers=headers, follow_redirects=False)
        assert answer.status_code == 303 and answer.headers["location"] == "/teilen?missed=1"
    assert documents_count() == 0
    # The page itself is the app, as at every other address.
    assert built.get("/teilen").text.startswith("<!doctype html>")


def test_the_scanner_worker_gets_its_own_policy_and_the_page_keeps_the_strict_one(built: TestClient) -> None:
    worker = built.get("/scanner/worker.js")
    assert worker.headers["content-security-policy"].encode() == SCANNER_CSP
    page = built.get("/kamera")
    policy = page.headers["content-security-policy"]
    assert "unsafe-eval" not in policy and "script-src" not in policy
    assert page.headers["permissions-policy"].startswith("camera=(self)")


def test_the_camera_is_allowed_for_this_site_only(client: TestClient) -> None:
    policy = client.get("/api/v1/health").headers["permissions-policy"]
    assert "camera=(self)" in policy and "microphone=()" in policy and "geolocation=()" in policy


# --- The iPhone shortcut ----------------------------------------------------------------------------------------------

LINK = "https://www.icloud.com/shortcuts/" + "0123456789abcdef" * 2


def test_the_operator_shares_the_shortcut_by_an_icloud_link(client: TestClient, operator: Account) -> None:
    assert client.get("/api/v1/shortcut").json() == {
        "link": "", "address": "http://testserver", "upload_url": "http://testserver/api/v1/documents?source=share"}
    assert client.put("/api/v1/settings/shortcut", json={"link": LINK}).json() == {"link": LINK}
    assert client.get("/api/v1/settings/shortcut").json() == {"link": LINK}
    with new_client(make_account("noor")) as member:
        assert member.get("/api/v1/shortcut").json()["link"] == LINK
        assert member.put("/api/v1/settings/shortcut", json={"link": ""}).status_code == 403
    for wrong in ("https://evil.example.org/shortcuts/" + "0" * 32, "http://www.icloud.com/shortcuts/" + "0" * 32,
                  "https://www.icloud.com/shortcuts/xyz", "javascript:alert(1)", LINK + "?x=1"):
        answer = client.put("/api/v1/settings/shortcut", json={"link": wrong})
        assert (answer.status_code, answer.json()["detail"]["code"]) == (422, "shortcut_link_invalid"), wrong
    assert client.put("/api/v1/settings/shortcut", json={"link": ""}).json() == {"link": ""}


def test_the_shortcut_names_the_public_address(client: TestClient, operator: Account) -> None:
    assert client.put("/api/v1/settings", json={"public_url": "https://paper.example.com"}).status_code == 200
    assert client.get("/api/v1/shortcut").json()["upload_url"] == (
        "https://paper.example.com/api/v1/documents?source=share")


def test_a_shortcut_with_a_device_token_uploads_without_a_tab(client: TestClient, operator: Account) -> None:
    token = client.post("/api/v1/devices", json={"name": "iPhone, Kurzbefehl"}).json()["token"]
    with program() as shortcut:
        answer = shortcut.post("/api/v1/documents?source=share", headers=bearer(token),
                               files=[("file", ("Beleg.pdf", make_pdf(), "application/pdf"))])
    assert answer.status_code == 201, answer.text
    assert answer.json()["items"][0]["document"]["source"] == "share"


# --- Keys for uploading -----------------------------------------------------------------------------------------------


def test_a_key_for_uploading_is_made_in_the_account_and_shown_once(client: TestClient, operator: Account) -> None:
    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
    made = client.post("/api/v1/api-keys", json={"name": "Scanner im Flur", "scope": "upload"})
    assert made.status_code == 201, made.text
    secret = made.json()["secret"]
    assert made.json()["key"]["scope"] == "upload"
    assert all("secret" not in key for key in client.get("/api/v1/api-keys").json()["keys"])
    with program() as scanner:
        assert post_files(scanner, ("Scan.pdf", make_pdf()), headers=bearer(secret)).status_code == 201
        assert scanner.get("/api/v1/documents", headers=bearer(secret)).status_code == 403
    assert client.post("/api/v1/api-keys", json={"name": "x", "scope": "admin"}).status_code == 422
    # Deleting it ("sperren" on the page) ends it at once.
    key_id = made.json()["key"]["id"]
    assert client.delete(f"/api/v1/api-keys/{key_id}").status_code == 204
    with program() as scanner:
        assert post_files(scanner, ("Scan2.pdf", make_pdf(["zwei"])), headers=bearer(secret)).status_code == 401


def test_a_key_brings_in_at_most_its_files_an_hour(client: TestClient, operator: Account,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apikeys, "UPLOADS_PER_HOUR", 3)
    secret = upload_key(operator)
    with program() as scanner:
        first = post_files(scanner, ("a.pdf", make_pdf(["a"])), ("b.pdf", make_pdf(["b"])), headers=bearer(secret))
        assert [item["status"] for item in first.json()["items"]] == ["accepted", "accepted"]
        # Two more in one request: the first fits, the second does not.
        second = post_files(scanner, ("c.pdf", make_pdf(["c"])), ("d.pdf", make_pdf(["d"])), headers=bearer(secret))
        assert second.status_code == 201
        items = second.json()["items"]
        assert [item["status"] for item in items] == ["accepted", "rejected"]
        assert (items[1]["http_status"], items[1]["error"]["code"]) == (429, "upload_limit")
        full = post_files(scanner, ("e.pdf", make_pdf(["e"])), headers=bearer(secret))
        assert (full.status_code, full.json()["detail"]["code"]) == (429, "upload_limit")
        assert full.headers["retry-after"] == "600"
        # Pieces count the same.
        piece = scanner.post("/api/v1/uploads", headers=bearer(secret),
                             json={"filename": "f.pdf", "size": 10, "sha256": "a" * 64})
        assert (piece.status_code, piece.json()["detail"]["code"]) == (429, "upload_limit")
    assert documents_count() == 3


def test_the_hour_frees_up_again(operator: Account) -> None:
    for _ in range(apikeys.UPLOADS_PER_HOUR):
        assert apikeys.take_upload(7, now=1000.0)
    assert not apikeys.take_upload(7, now=1000.0) and apikeys.upload_room(7, now=1000.0) == 0
    assert apikeys.upload_room(7, now=1000.0 + 3601) == apikeys.UPLOADS_PER_HOUR
    assert apikeys.upload_room(8, now=1000.0) == apikeys.UPLOADS_PER_HOUR, "per key"


def test_a_file_the_server_has_already_costs_no_upload(client: TestClient, operator: Account,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    monkeypatch.setattr(apikeys, "UPLOADS_PER_HOUR", 1)
    secret = upload_key(operator)
    content = make_pdf(["schon da"])
    with program() as scanner:
        start = {"filename": "x.pdf", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        made = scanner.post("/api/v1/uploads", headers=bearer(secret), json=start)
        assert made.status_code == 201
        # The same start again goes on with the open upload: it is no new file.
        again = scanner.post("/api/v1/uploads", headers=bearer(secret), json=start)
        assert again.status_code == 200
        upload = made.json()["upload"]["id"]
        assert scanner.put(f"/api/v1/uploads/{upload}?offset=0", headers=bearer(secret), content=content).status_code == 200
        assert scanner.post(f"/api/v1/uploads/{upload}/finish", headers=bearer(secret)).status_code == 200


def test_a_key_makes_at_most_120_requests_a_minute(client: TestClient, operator: Account) -> None:
    assert apikeys.PER_MINUTE == 120
    secret = upload_key(operator, "read")
    with program() as reader:
        for _ in range(apikeys.PER_MINUTE):
            assert reader.get("/api/v1/kinds", headers=bearer(secret)).status_code == 200
        slow = reader.get("/api/v1/kinds", headers=bearer(secret))
        assert (slow.status_code, slow.json()["detail"]["code"]) == (429, "slow_down")


# --- Review: fixed limits, what a key sees, what "latest" may show ------------------------------------------------------


def test_the_limits_are_the_ones_the_page_names() -> None:
    assert (apikeys.PER_MINUTE, apikeys.UPLOADS_PER_HOUR) == (120, 50)


def test_latest_shows_only_what_the_person_may_still_see(client: TestClient, operator: Account) -> None:
    """Tom uploaded into the household, then left it: his documents there are no longer his to see."""
    from app.services import vaults as vaults_service

    tom = make_account("tom")
    house = shared_vault("Haushalt", operator, (tom, EDIT))
    gone = add_document(house, tom, "Haushalt-Rechnung", status=INBOX)
    kept = add_document(own_vault(tom), tom, "Eigene", status=INBOX)
    with new_client(tom) as browser:
        assert {doc["id"] for doc in browser.get("/api/v1/quick").json()["recent"]} == {gone, kept}
        with SessionLocal() as db:
            vaults_service.remove_member(db, operator.id, house, tom.id)
        body = browser.get("/api/v1/quick").json()
        assert [doc["id"] for doc in body["recent"]] == [kept]
        assert body["inbox"] == 1


def test_a_key_sees_and_goes_on_with_only_its_own_uploads(client: TestClient, operator: Account) -> None:
    import hashlib

    browser_file = make_pdf(["vom Browser"])
    started = client.post("/api/v1/uploads", json={"filename": "Steuer-Brief.pdf", "size": len(browser_file),
                                                   "sha256": hashlib.sha256(browser_file).hexdigest()})
    theirs = started.json()["upload"]["id"]
    secret = upload_key(operator)
    other = upload_key(operator)
    with program() as scanner:
        assert scanner.get("/api/v1/uploads", headers=bearer(secret)).json() == []
        for method, path in (("GET", f"/api/v1/uploads/{theirs}"), ("DELETE", f"/api/v1/uploads/{theirs}"),
                             ("POST", f"/api/v1/uploads/{theirs}/finish")):
            assert scanner.request(method, path, headers=bearer(secret)).status_code == 404, path
        assert scanner.put(f"/api/v1/uploads/{theirs}?offset=0", headers=bearer(secret),
                           content=browser_file).status_code == 404
        mine_file = make_pdf(["vom Scanner"])
        start = {"filename": "Scan.pdf", "size": len(mine_file), "sha256": hashlib.sha256(mine_file).hexdigest()}
        own = scanner.post("/api/v1/uploads", headers=bearer(secret), json=start).json()["upload"]["id"]
        assert [row["id"] for row in scanner.get("/api/v1/uploads", headers=bearer(secret)).json()] == [own]
        assert scanner.get("/api/v1/uploads", headers=bearer(other)).json() == []
        assert scanner.get(f"/api/v1/uploads/{own}", headers=bearer(other)).status_code == 404
        # The same file from the browser does not go on with the key's upload, and the other way round.
        assert scanner.post("/api/v1/uploads", headers=bearer(other), json=start).json()["upload"]["id"] != own
    # The browser of the account still sees every upload of it.
    assert {row["id"] for row in client.get("/api/v1/uploads").json()} >= {theirs, own}


def test_a_key_hears_that_a_file_is_there_but_not_which(client: TestClient, operator: Account) -> None:
    import hashlib

    content = make_pdf(["schon da, geheimer Titel"])
    first = client.post("/api/v1/documents", files=[("file", ("Geheimer Titel.pdf", content, "application/pdf"))])
    assert first.status_code == 201
    secret = upload_key(operator)
    with program() as scanner:
        start = {"filename": "x.pdf", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        answer = scanner.post("/api/v1/uploads", headers=bearer(secret), json=start)
        assert answer.status_code == 200 and answer.json() == {"exists": True, "upload": None, "document": None}
        again = post_files(scanner, ("y.pdf", content), headers=bearer(secret))
        item = again.json()["items"][0]
        assert item["status"] == "accepted" and item["duplicate"] is None and item["document"]["duplicate"] is None
        assert "Geheimer" not in again.text
    # The browser still hears which document it is.
    browser = client.post("/api/v1/uploads", json=start).json()
    assert browser["exists"] is True and browser["document"]["title"] == "Geheimer Titel"
