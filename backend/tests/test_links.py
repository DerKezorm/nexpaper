"""Shares with people of this server, and links for people without an account."""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import app
from app.models import Account, Link, Share
from app.security import brake
from app.services import logs, sharing

from . import files
from .conftest import PASSWORD, make_account, new_client
from .papers import PDF, add_document, freeze, own_vault, shared_vault

START = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@pytest.fixture
def case(client: TestClient, operator: Account, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    freeze(monkeypatch, START)
    tom, lea, out = make_account("tom"), make_account("lea"), make_account("outsider")
    vault = shared_vault("Household", operator, (tom, "edit"), (lea, "read"))
    doc = add_document(vault, operator, "Contract", sender="Hansa", date=date(2026, 3, 14))
    return {"operator": operator, "tom": tom, "lea": lea, "out": out, "vault": vault, "doc": doc}


def make_link(client: TestClient, doc: object, **body: object) -> dict:
    payload = {"recipient": "Tax office", "days": 7, "allow_download": True, **body}
    answer = client.post(f"/api/v1/documents/{doc}/links", json=payload)
    assert answer.status_code == 201, answer.text
    return answer.json()


def public() -> TestClient:
    """Somebody without an account: no cookie, no header."""
    return TestClient(app, base_url="http://testserver")


# --- Shares -------------------------------------------------------------------------------------------------------------


def test_a_share_shows_one_document_to_one_person(client: TestClient, case: dict[str, object]) -> None:
    doc, out = case["doc"], case["out"]
    given = client.put(f"/api/v1/documents/{doc}/shares/{out.id}", json={"right": "read"})  # type: ignore[attr-defined]
    assert given.status_code == 200 and given.json()["user"]["name"] == "outsider"
    with new_client(out) as guest:  # type: ignore[arg-type]
        assert guest.get(f"/api/v1/documents/{doc}").json()["via_share"] is True
        assert [d["id"] for d in guest.get("/api/v1/documents").json()["items"]] == [doc]
        # Only that document: not the vault, not its other documents.
        assert guest.get(f"/api/v1/vaults/{case['vault']}").status_code == 404
        other = add_document(case["vault"], case["operator"], "Other", content=None)  # type: ignore[arg-type]
        assert guest.get(f"/api/v1/documents/{other}").status_code == 404
        assert guest.get(f"/api/v1/documents/{doc}/notes").status_code == 200
        # A guest does not see who else it was shared with: that is for whoever may share.
        assert guest.get(f"/api/v1/documents/{doc}/links").status_code == 403
    assert [s["user"]["name"] for s in client.get(f"/api/v1/documents/{doc}/shares").json()] == ["outsider"]
    changed = client.put(f"/api/v1/documents/{doc}/shares/{out.id}", json={"right": "edit"})  # type: ignore[attr-defined]
    assert changed.json()["right"] == "edit"
    assert client.delete(f"/api/v1/documents/{doc}/shares/{out.id}").status_code == 204  # type: ignore[attr-defined]
    with new_client(out) as guest:  # type: ignore[arg-type]
        assert guest.get(f"/api/v1/documents/{doc}").status_code == 404
    actions = [e["action"] for e in client.get(f"/api/v1/documents/{doc}/events").json()]
    assert actions[:3] == ["unshared", "share_changed", "shared"]


def test_only_managers_and_the_owner_share_and_not_with_oneself_or_the_vault(
    client: TestClient, case: dict[str, object],
) -> None:
    doc, out, tom, lea = case["doc"], case["out"], case["tom"], case["lea"]
    for member in (tom, lea):
        with new_client(member) as session:  # type: ignore[arg-type]
            assert session.put(f"/api/v1/documents/{doc}/shares/{out.id}", json={"right": "read"}).status_code == 403  # type: ignore[attr-defined]
            assert session.post(f"/api/v1/documents/{doc}/links", json={"recipient": "x", "days": 1}).status_code == 403
            assert session.get(f"/api/v1/documents/{doc}/shares").status_code == 403, "only who may share learns with whom"
    with new_client(out) as stranger:  # type: ignore[arg-type]
        assert stranger.put(f"/api/v1/documents/{doc}/shares/{out.id}", json={"right": "read"}).status_code == 404  # type: ignore[attr-defined]
    assert client.put(f"/api/v1/documents/{doc}/shares/{case['operator'].id}", json={"right": "read"}).status_code == 409  # type: ignore[attr-defined]
    assert client.put(f"/api/v1/documents/{doc}/shares/{tom.id}", json={"right": "read"}).status_code == 409  # type: ignore[attr-defined]
    assert client.put(f"/api/v1/documents/{doc}/shares/{out.id}", json={"right": "manage"}).status_code == 422  # type: ignore[attr-defined]
    assert client.put(f"/api/v1/documents/{doc}/shares/999999", json={"right": "read"}).status_code == 404
    # The owner of a document may share it even with only the right to read in the vault.
    owned = add_document(case["vault"], lea, "Lea's own", content=None)  # type: ignore[arg-type]
    with new_client(lea) as owner:  # type: ignore[arg-type]
        assert owner.put(f"/api/v1/documents/{owned}/shares/{out.id}", json={"right": "read"}).status_code == 200  # type: ignore[attr-defined]


def test_the_person_it_was_shared_with_can_give_it_back_but_not_take_it_from_others(
    client: TestClient, case: dict[str, object],
) -> None:
    doc, out = case["doc"], case["out"]
    third = make_account("third")
    client.put(f"/api/v1/documents/{doc}/shares/{out.id}", json={"right": "read"})  # type: ignore[attr-defined]
    client.put(f"/api/v1/documents/{doc}/shares/{third.id}", json={"right": "read"})
    with new_client(out) as guest:  # type: ignore[arg-type]
        assert guest.delete(f"/api/v1/documents/{doc}/shares/{third.id}").status_code == 403
        assert guest.delete(f"/api/v1/documents/{doc}/shares/{out.id}").status_code == 204  # type: ignore[attr-defined]
    with SessionLocal() as db:
        assert [s.user_id for s in db.scalars(select(Share))] == [third.id]


def test_two_shares_of_the_same_document_with_the_same_person_at_once_leave_one(
    client: TestClient, case: dict[str, object],
) -> None:
    doc, out = case["doc"], case["out"]
    barrier = threading.Barrier(2)
    answers: list[int] = []

    def share(right: str) -> None:
        with new_client(case["operator"]) as session:  # type: ignore[arg-type]
            barrier.wait(timeout=10)
            answers.append(session.put(f"/api/v1/documents/{doc}/shares/{out.id}", json={"right": right}).status_code)  # type: ignore[attr-defined]

    threads = [threading.Thread(target=share, args=("read",)), threading.Thread(target=share, args=("edit",))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert answers == [200, 200]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Share)) == 1


# --- Links --------------------------------------------------------------------------------------------------------------


def test_a_link_shows_one_document_to_somebody_without_an_account(client: TestClient, case: dict[str, object]) -> None:
    made = make_link(client, case["doc"], recipient="  Tax   office ", days=7)
    token = made["token"]
    assert token.startswith("lnk_") and made["url"].endswith(f"/l/{token}") and made["recipient"] == "Tax office"
    assert made["status"] == "active" and made["opened_count"] == 0
    listed = client.get(f"/api/v1/documents/{case['doc']}/links").json()
    assert len(listed) == 1 and "token" not in listed[0] and token not in str(listed)
    with SessionLocal() as db:
        row = db.scalar(select(Link))
        assert row is not None and row.token_hash != token and token not in row.token_hash
    with public() as outside:
        page = outside.get(f"/api/v1/l/{token}")
        assert page.status_code == 200
        assert page.json() == {
            # The operator has no display name: the page says nothing rather than the name they sign in with.
            "shared_by": "", "recipient": "Tax office", "title": "Contract", "sender": "Hansa", "kind": None,
            "date": "2026-03-14", "pages": 1, "until": "2026-10-15T12:00:00Z", "allow_download": True, "has_file": True,
            "viewable": True, "has_pages": True,
        }
        file = outside.get(f"/api/v1/l/{token}/file")
        assert file.status_code == 200 and file.content == PDF and file.headers["content-type"] == "application/pdf"
        assert file.headers["content-disposition"].startswith("inline")
        # Nothing else of the server answers to a link.
        for path in (f"/api/v1/documents/{case['doc']}", "/api/v1/vaults", "/api/v1/auth/me", "/api/v1/documents"):
            assert outside.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 401, path
        assert outside.get(f"/api/v1/documents?token={token}").status_code == 401


def test_a_link_counts_how_often_it_was_opened_and_the_history_says_so_now_and_then(
    client: TestClient, case: dict[str, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = make_link(client, case["doc"], recipient="Tax office")
    with public() as outside:
        for _ in range(3):
            assert outside.get(f"/api/v1/l/{made['token']}").status_code == 200
        outside.get(f"/api/v1/l/{made['token']}/file")
        freeze(monkeypatch, START + timedelta(minutes=11))
        outside.get(f"/api/v1/l/{made['token']}")
    shown = client.get(f"/api/v1/documents/{case['doc']}/links").json()[0]
    assert shown["opened_count"] == 4, "the file behind the page is not an opening"
    opened = [e for e in client.get(f"/api/v1/documents/{case['doc']}/events").json() if e["action"] == "link_opened"]
    assert len(opened) == 2 and opened[0]["by"] is None and opened[0]["by_link"] == "Tax office"


@pytest.mark.parametrize("body", [
    {"recipient": ""}, {"recipient": "   "}, {"recipient": "x" * 201}, {"recipient": "a\u0000b"}, {"days": 0}, {"days": 31},
    {"days": 1.5}, {"days": "7"}, {"days": 366}, {"allow_download": "maybe"},
])
def test_a_link_with_wrong_input_is_refused(client: TestClient, case: dict[str, object], body: dict) -> None:
    answer = client.post(f"/api/v1/documents/{case['doc']}/links", json={"recipient": "x", "days": 7, **body})
    assert answer.status_code == 422, (body, answer.text)
    assert client.get(f"/api/v1/documents/{case['doc']}/links").json() == []


def test_a_link_runs_out_by_itself(client: TestClient, case: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    made = make_link(client, case["doc"], days=2)
    with public() as outside:
        freeze(monkeypatch, START + timedelta(days=2, seconds=-1))
        assert outside.get(f"/api/v1/l/{made['token']}").status_code == 200
        freeze(monkeypatch, START + timedelta(days=2, seconds=1))
        assert outside.get(f"/api/v1/l/{made['token']}").status_code == 404
        assert outside.get(f"/api/v1/l/{made['token']}/file").status_code == 404
    assert client.get(f"/api/v1/documents/{case['doc']}/links").json()[0]["status"] == "expired"


def test_a_revoked_link_stops_at_once_and_the_one_who_made_it_may_revoke_it(
    client: TestClient, case: dict[str, object],
) -> None:
    doc = case["doc"]
    made = make_link(client, doc)
    other = make_link(client, doc, recipient="Landlord")
    assert client.delete(f"/api/v1/documents/{doc}/links/{made['id']}").status_code == 204
    with public() as outside:
        assert outside.get(f"/api/v1/l/{made['token']}").status_code == 404
        assert outside.get(f"/api/v1/l/{other['token']}").status_code == 200
    statuses = {link["recipient"]: link["status"] for link in client.get(f"/api/v1/documents/{doc}/links").json()}
    assert statuses == {"Tax office": "revoked", "Landlord": "active"}
    assert client.delete(f"/api/v1/documents/{doc}/links/999").status_code == 404
    with new_client(case["tom"]) as editor:  # type: ignore[arg-type]
        assert editor.delete(f"/api/v1/documents/{doc}/links/{other['id']}").status_code == 403
    actions = [e["action"] for e in client.get(f"/api/v1/documents/{doc}/events").json()]
    assert "link_revoked" in actions and actions.count("link_created") == 2


def test_the_operator_ends_every_link_at_once_and_sets_the_longest_time(
    client: TestClient, case: dict[str, object],
) -> None:
    doc = case["doc"]
    made = make_link(client, doc, days=30)
    assert client.put("/api/v1/settings", json={"link_max_days": 14}).status_code == 200
    assert client.get("/api/v1/sharing").json() == {"links_allowed": True, "link_max_days": 14}
    too_long = client.post(f"/api/v1/documents/{doc}/links", json={"recipient": "x", "days": 15})
    assert too_long.status_code == 422 and too_long.json()["detail"]["max_days"] == 14
    assert client.put("/api/v1/settings", json={"link_max_days": 45}).status_code == 422
    assert client.put("/api/v1/settings", json={"links_allowed": False}).status_code == 200
    with public() as outside:
        assert outside.get(f"/api/v1/l/{made['token']}").status_code == 404, "all existing links are dead"
        assert outside.get(f"/api/v1/l/{made['token']}/file").status_code == 404
    refused = client.post(f"/api/v1/documents/{doc}/links", json={"recipient": "x", "days": 1})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "links_off"
    assert client.get(f"/api/v1/documents/{doc}/links").json()[0]["status"] == "off"
    client.put("/api/v1/settings", json={"links_allowed": True})
    with public() as outside:
        assert outside.get(f"/api/v1/l/{made['token']}").status_code == 200, "switching on again revives what had not run out"
    with new_client(case["tom"]) as member:  # type: ignore[arg-type]
        assert member.put("/api/v1/settings", json={"links_allowed": False}).status_code == 403
        assert member.get("/api/v1/sharing").status_code == 200


def test_a_link_to_a_document_in_the_trash_is_dead_until_it_is_back(client: TestClient, case: dict[str, object]) -> None:
    doc = case["doc"]
    made = make_link(client, doc)
    client.delete(f"/api/v1/documents/{doc}")
    with public() as outside:
        assert outside.get(f"/api/v1/l/{made['token']}").status_code == 404
        assert outside.get(f"/api/v1/l/{made['token']}/file").status_code == 404
    assert client.post(f"/api/v1/documents/{doc}/links", json={"recipient": "x", "days": 1}).status_code == 409
    client.post(f"/api/v1/documents/{doc}/restore")
    with public() as outside:
        assert outside.get(f"/api/v1/l/{made['token']}").status_code == 200
        assert outside.get(f"/api/v1/l/{made['token']}/file").status_code == 200


def test_a_download_can_be_refused_and_only_pictures_and_pdfs_are_shown_in_place(
    client: TestClient, case: dict[str, object],
) -> None:
    viewing = make_link(client, case["doc"], allow_download=False)
    with public() as outside:
        page = outside.get(f"/api/v1/l/{viewing['token']}").json()
        assert page["allow_download"] is False and page["viewable"] is False and page["has_file"] is True
        # Without downloading the file is not handed out at all: not whole, not in parts, not to show in place.
        for headers in ({}, {"Range": "bytes=0-9"}, {"Range": "bytes=5-"}):
            refused = outside.get(f"/api/v1/l/{viewing['token']}/file", headers=headers)
            assert refused.status_code == 403 and PDF[:9] not in refused.content, headers
            assert refused.json()["detail"]["code"] == "download_not_allowed"
    invoice = add_document(case["vault"], case["operator"], "E-invoice", content=b"<x/>", extension=".xml")  # type: ignore[arg-type]
    xml_viewing = make_link(client, invoice, allow_download=False)
    xml_download = make_link(client, invoice, allow_download=True)
    with public() as outside:
        assert outside.get(f"/api/v1/l/{xml_viewing['token']}/file").status_code == 403
        answer = outside.get(f"/api/v1/l/{xml_download['token']}/file")
        assert answer.status_code == 200 and answer.headers["content-disposition"].startswith("attachment")
        assert answer.headers["content-type"] == "application/octet-stream"
        # An XML file is fetched, never shown in place: the page offers no "view in the browser".
        assert outside.get(f"/api/v1/l/{xml_download['token']}").json()["viewable"] is False
    # A WebP or AVIF original is fetched like a HEIC photo, never shown in place (the page shows the pages instead).
    for extension, kind in ((".webp", "webp"), (".avif", "avif")):
        photo = add_document(case["vault"], case["operator"], f"Photo {kind}", content=files.make_image(kind), extension=extension)  # type: ignore[arg-type]
        photo_link = make_link(client, photo, allow_download=True)
        with public() as outside:
            answer = outside.get(f"/api/v1/l/{photo_link['token']}/file")
            assert answer.status_code == 200 and answer.headers["content-disposition"].startswith("attachment"), kind
            assert answer.headers["content-type"] == f"image/{kind}", kind
            assert outside.get(f"/api/v1/l/{photo_link['token']}").json()["viewable"] is False, kind
    none_yet = add_document(case["vault"], case["operator"], "No file yet", content=None)  # type: ignore[arg-type]
    empty = make_link(client, none_yet)
    with public() as outside:
        assert outside.get(f"/api/v1/l/{empty['token']}").json()["has_file"] is False
        assert outside.get(f"/api/v1/l/{empty['token']}/file").status_code == 404


def test_wrong_tokens_answer_alike_and_a_run_of_them_is_slowed_down(client: TestClient, case: dict[str, object]) -> None:
    made = make_link(client, case["doc"])
    with public() as outside:
        wrong = [
            f"lnk_{'a' * 43}", "lnk_short", "x" * 50, made["token"][:-1] + ("a" if made["token"][-1] != "a" else "b"),
        ]
        answers = [outside.get(f"/api/v1/l/{token}") for token in wrong]
        assert {a.status_code for a in answers} == {404} and len({a.content for a in answers}) == 1, (
            "every wrong token answers the same")
        assert outside.get(f"/api/v1/l/{made['token']}").status_code == 200, "four wrong ones are no reason to rest"
        # More room than the sign-in has: a mail program that opens an old link ahead now and then is no attack.
        for _ in range(15):
            assert outside.get(f"/api/v1/l/{wrong[0]}").status_code == 404
        assert outside.get(f"/api/v1/l/{made['token']}").status_code == 200, "nineteen wrong ones still pass"
        # The twentieth wrong one in a row from one address: it rests, even for the right token.
        outside.get(f"/api/v1/l/{wrong[0]}")
        answer = outside.get(f"/api/v1/l/{made['token']}")
        assert answer.status_code == 429 and answer.json()["detail"]["code"] == "too_many_attempts"


def test_wrong_link_tokens_never_keep_the_address_from_signing_in(client: TestClient, case: dict[str, object]) -> None:
    """The brake of the links is a brake of its own: a run of dead links from one address does not lock its sign-in,
    and a run of wrong passwords does not lock a link that works."""
    made = make_link(client, case["doc"])
    with public() as outside:
        for _ in range(30):
            outside.get(f"/api/v1/l/lnk_{'b' * 43}")
        signed = outside.post("/api/v1/auth/login", json={"name": "tom", "password": PASSWORD},
                              headers={"X-Nexpaper-Client": "tab-tests000"})
        assert signed.status_code == 200, signed.text
    with public() as outside:
        brake_forget()
        for _ in range(6):
            outside.post("/api/v1/auth/login", json={"name": "tom", "password": "wrong password here"},
                         headers={"X-Nexpaper-Client": "tab-tests000"})
        assert outside.post("/api/v1/auth/login", json={"name": "lea", "password": PASSWORD},
                            headers={"X-Nexpaper-Client": "tab-tests000"}).status_code == 429
        assert outside.get(f"/api/v1/l/{made['token']}").status_code == 200


def test_the_token_never_reaches_the_log(client: TestClient, case: dict[str, object]) -> None:
    made = make_link(client, case["doc"])
    token = made["token"]
    for line in (f"GET /api/v1/l/{token} -> 200", f"GET /l/{token}", f"link {token} opened",
                 f"GET /api/v1/l/{token}/file?x=1", f"?token={token}"):
        assert token not in logs.redact(line), line
        assert token[10:30] not in logs.redact(line), line
    assert logs.redact("GET /api/v1/documents/12/links -> 200") == "GET /api/v1/documents/12/links -> 200"


def test_my_open_links_and_the_operators_overview_never_name_documents_to_the_operator(
    client: TestClient, case: dict[str, object],
) -> None:
    lea = case["lea"]
    own = add_document(case["vault"], lea, "Lea's own", content=None)  # type: ignore[arg-type]
    make_link(client, case["doc"], recipient="Tax office", days=3)
    with new_client(lea) as owner:  # type: ignore[arg-type]
        made = owner.post(f"/api/v1/documents/{own}/links", json={"recipient": "Bank", "days": 5}).json()
        mine = owner.get("/api/v1/links").json()
        assert [(m["recipient"], m["document_title"]) for m in mine] == [("Bank", "Lea's own")]
        assert owner.get("/api/v1/sharing/overview").status_code == 403
    assert [m["recipient"] for m in client.get("/api/v1/links").json()] == ["Tax office"]
    overview = client.get("/api/v1/sharing/overview").json()
    assert overview == {"open_links": 2, "people": 2, "next_end": "2026-10-11T12:00:00Z"}
    assert made["recipient"] == "Bank"


def test_a_link_is_made_by_a_device_but_never_by_a_key(client: TestClient, case: dict[str, object]) -> None:
    doc = case["doc"]
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    client.put("/api/v1/settings", json={"api_keys_allowed": True})
    key_token = client.post("/api/v1/api-keys", json={"name": "script", "scope": "read"}).json()["secret"]
    with public() as program:
        by_device = program.post(f"/api/v1/documents/{doc}/links", json={"recipient": "x", "days": 1},
                                 headers={"Authorization": f"Bearer {token}"})
        assert by_device.status_code == 201
        by_key = program.post(f"/api/v1/documents/{doc}/links", json={"recipient": "x", "days": 1},
                              headers={"Authorization": f"Bearer {key_token}"})
        assert by_key.status_code == 401 and by_key.json()["detail"]["code"] == "token_wrong_kind"
        listed = program.get(f"/api/v1/documents/{doc}/links", headers={"Authorization": f"Bearer {key_token}"})
        assert listed.status_code == 200
    assert sharing.LINK_PREFIX == "lnk_"
    assert own_vault(case["operator"])  # type: ignore[arg-type]


def brake_forget() -> None:
    brake.forget()


# --- Copying the address again ------------------------------------------------------------------------------------------


def test_the_address_of_a_link_can_be_copied_again_by_its_maker_and_the_managers(
    client: TestClient, case: dict[str, object],
) -> None:
    tom, lea = case["tom"], case["lea"]
    with new_client(tom) as as_tom:  # type: ignore[arg-type]
        # Tom owns no document here; give him one, he may share it and make a link.
        own = add_document(case["vault"], tom, "Toms", content=None)  # type: ignore[arg-type]
        made = as_tom.post(f"/api/v1/documents/{own}/links", json={"recipient": "Vermieter", "days": 3}).json()
        listed = as_tom.get(f"/api/v1/documents/{own}/links").json()
        assert listed[0]["can_copy"] is True and "token" not in listed[0]
        again = as_tom.post(f"/api/v1/documents/{own}/links/{made['id']}/address")
        assert again.status_code == 200 and again.json() == {"url": made["url"]}
    # The manager of the vault may copy it too; a reader of the vault may not, nor may somebody outside: 404 as for a
    # link that does not exist.
    assert client.post(f"/api/v1/documents/{own}/links/{made['id']}/address").json()["url"] == made["url"]
    with new_client(lea) as as_lea, new_client(case["out"]) as outsider:  # type: ignore[arg-type]
        for who in (as_lea, outsider):
            answer = who.post(f"/api/v1/documents/{own}/links/{made['id']}/address")
            assert answer.status_code == 404 and made["token"] not in answer.text
    assert client.post(f"/api/v1/documents/{own}/links/999999/address").status_code == 404
    # The owner of a document may share it, but the address of a link the manager made is not theirs to copy.
    managers = client.post(f"/api/v1/documents/{own}/links", json={"recipient": "Bank", "days": 2}).json()
    with new_client(tom) as as_tom:  # type: ignore[arg-type]
        listed = {link["id"]: link for link in as_tom.get(f"/api/v1/documents/{own}/links").json()}
        assert listed[managers["id"]]["can_copy"] is False and listed[made["id"]]["can_copy"] is True
        refused = as_tom.post(f"/api/v1/documents/{own}/links/{managers['id']}/address")
        assert refused.status_code == 404 and managers["token"] not in refused.text
    # The history says it was copied, by whom, never the address.
    history = client.get(f"/api/v1/documents/{own}/events").json()
    copied = [e for e in history if e["action"] == "link_copied"]
    assert len(copied) == 2 and {e["by"]["name"] for e in copied} == {"tom", "tester"}
    assert made["token"] not in str(history)
    # Nor in the log: the route names no token, and the answer is never written down.
    written = logs.log_file().read_text(encoding="utf-8", errors="replace") if logs.log_file().exists() else ""
    assert made["token"][4:] not in written
    # A revoked link has no address to copy.
    client.delete(f"/api/v1/documents/{own}/links/{made['id']}")
    assert client.post(f"/api/v1/documents/{own}/links/{made['id']}/address").status_code == 404
    revoked = next(link for link in client.get(f"/api/v1/documents/{own}/links").json() if link["id"] == made["id"])
    assert revoked["can_copy"] is False


def test_the_database_alone_tells_nobody_a_token(client: TestClient, case: dict[str, object],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    made = make_link(client, case["doc"])
    token = made["token"]
    secret_part = token[len("lnk_"):]
    from app.config import get_settings

    raw = get_settings().database_path.read_bytes()
    wal = get_settings().database_path.with_name("nexpaper.db-wal")
    raw += wal.read_bytes() if wal.exists() else b""
    for piece in (secret_part, secret_part[:20], secret_part[-20:]):
        assert piece.encode() not in raw
    with SessionLocal() as db:
        row = db.scalar(select(Link))
        assert row is not None and row.token_enc and secret_part not in row.token_enc
        # Opened with another secret, the sealed value says nothing.
        monkeypatch.setenv("NEXPAPER_SECRET_KEY", "a-different-secret-of-another-server")
        get_settings.cache_clear()
        try:
            assert sharing.decrypt_secret(row.token_enc, "link:" + row.token_hash) == ""
            answer = client.post(f"/api/v1/documents/{case['doc']}/links/{row.id}/address")
            assert answer.status_code == 409 and answer.json()["detail"]["code"] == "link_unreadable"
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()
    # A sealed value moved to another link does not open there.
    other = make_link(client, case["doc"], recipient="Second")
    with SessionLocal() as db:
        first, second = db.get(Link, made["id"]), db.get(Link, other["id"])
        assert first is not None and second is not None
        second.token_enc = first.token_enc
        db.commit()
    assert client.post(f"/api/v1/documents/{case['doc']}/links/{other['id']}/address").status_code == 409


# --- A link lives as long as the right of its maker ---------------------------------------------------------------------


def _link_by(maker_client: TestClient, doc: int) -> str:
    answer = maker_client.post(f"/api/v1/documents/{doc}/links", json={"recipient": "Steuerbuero", "days": 7})
    assert answer.status_code == 201, answer.text
    return answer.json()["token"]


def _works(token: str) -> bool:
    with public() as outside:
        return outside.get(f"/api/v1/l/{token}").status_code == 200


@pytest.mark.parametrize("loss", ["removed", "downgraded", "blocked", "deleted"])
def test_a_link_ends_when_its_maker_may_no_longer_share(
    client: TestClient, case: dict[str, object], loss: str,
) -> None:
    from app.models import Account as AccountRow

    maker = make_account(f"maker-{loss}")
    vault = case["vault"]
    client.put(f"/api/v1/vaults/{vault}/members/{maker.id}", json={"right": "manage"})
    with new_client(maker) as as_maker:
        token = _link_by(as_maker, case["doc"])  # type: ignore[arg-type]
    assert _works(token)
    if loss == "removed":
        client.delete(f"/api/v1/vaults/{vault}/members/{maker.id}")
    elif loss == "downgraded":
        client.put(f"/api/v1/vaults/{vault}/members/{maker.id}", json={"right": "edit"})
    elif loss == "blocked":
        with SessionLocal() as db:
            row = db.get(AccountRow, maker.id)
            assert row is not None
            row.blocked_at = START
            db.commit()
    else:
        assert client.request("DELETE", f"/api/v1/accounts/{maker.id}",
                              json={"current_password": PASSWORD, "confirm_name": maker.name}).status_code == 204
    assert not _works(token)
    listed = client.get(f"/api/v1/documents/{case['doc']}/links").json()
    assert listed[0]["status"] in ("ended", "revoked")
    if loss in ("removed", "downgraded"):
        # Given the right back, the link works again: nothing was destroyed, only checked.
        client.put(f"/api/v1/vaults/{vault}/members/{maker.id}", json={"right": "manage"})
        assert _works(token)
    # The overview of the operator counts only links that work.
    shown = client.get("/api/v1/sharing/overview").json()
    assert shown["open_links"] == (1 if loss in ("removed", "downgraded") else 0)


def test_the_owner_of_a_document_keeps_their_links_while_they_see_it(client: TestClient, case: dict[str, object]) -> None:
    tom = case["tom"]
    own = add_document(case["vault"], tom, "Toms", content=None)  # type: ignore[arg-type]
    with new_client(tom) as as_tom:  # type: ignore[arg-type]
        token = _link_by(as_tom, own)
    assert _works(token)
    client.put(f"/api/v1/vaults/{case['vault']}/members/{tom.id}", json={"right": "read"})  # type: ignore[attr-defined]
    assert _works(token), "an owner who still sees the document may still share it"
    client.delete(f"/api/v1/vaults/{case['vault']}/members/{tom.id}")  # type: ignore[attr-defined]
    assert not _works(token)


def test_a_lower_limit_of_the_operator_shortens_the_links_there_are(
    client: TestClient, case: dict[str, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = make_link(client, case["doc"], days=30)
    assert client.put("/api/v1/settings", json={"link_max_days": 7}).status_code == 200
    listed = client.get(f"/api/v1/documents/{case['doc']}/links").json()[0]
    assert listed["until"] == "2026-10-15T12:00:00Z" and listed["status"] == "active"
    freeze(monkeypatch, START + timedelta(days=6, hours=23))
    assert _works(made["token"])
    freeze(monkeypatch, START + timedelta(days=7, minutes=1))
    assert not _works(made["token"])
    # Raised again, the link has its own end once more.
    assert client.put("/api/v1/settings", json={"link_max_days": 30}).status_code == 200
    assert _works(made["token"])


def test_the_person_who_made_the_link_looking_at_it_is_no_opening(client: TestClient, case: dict[str, object]) -> None:
    made = make_link(client, case["doc"])
    # "so sieht es aus": the browser of the person who made it, with their session.
    assert client.get(f"/api/v1/l/{made['token']}").status_code == 200
    with new_client(case["lea"]) as reader:  # type: ignore[arg-type]
        assert reader.get(f"/api/v1/l/{made['token']}").status_code == 200, "a member who sees it anyway"
    shown = client.get(f"/api/v1/documents/{case['doc']}/links").json()[0]
    assert shown["opened_count"] == 0
    assert [e for e in client.get(f"/api/v1/documents/{case['doc']}/events").json() if e["action"] == "link_opened"] == []
    # Somebody signed in who may not see the document counts like anybody without an account.
    with new_client(case["out"]) as outsider:  # type: ignore[arg-type]
        assert outsider.get(f"/api/v1/l/{made['token']}").status_code == 200
    with public() as outside:
        assert outside.get(f"/api/v1/l/{made['token']}").status_code == 200
    assert client.get(f"/api/v1/documents/{case['doc']}/links").json()[0]["opened_count"] == 2


def test_copying_again_and_again_says_so_once_in_ten_minutes(
    client: TestClient, case: dict[str, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = make_link(client, case["doc"])
    other = make_link(client, case["doc"], recipient="Second")
    for _ in range(4):
        assert client.post(f"/api/v1/documents/{case['doc']}/links/{made['id']}/address").status_code == 200
    assert client.post(f"/api/v1/documents/{case['doc']}/links/{other['id']}/address").status_code == 200

    def copied() -> list[dict]:
        return [e for e in client.get(f"/api/v1/documents/{case['doc']}/events").json() if e["action"] == "link_copied"]

    assert sorted(e["detail"]["link"] for e in copied()) == sorted([made["id"], other["id"]])
    freeze(monkeypatch, START + timedelta(minutes=11))
    assert client.post(f"/api/v1/documents/{case['doc']}/links/{made['id']}/address").status_code == 200
    assert len(copied()) == 3


def test_the_maker_who_may_no_longer_share_cannot_copy_the_address(client: TestClient, case: dict[str, object]) -> None:
    """Mutation N09 of the second review: without the share right, ``may_copy`` alone would still hand the maker the
    address of a link that ended with their right."""
    maker = make_account("maker")
    client.put(f"/api/v1/vaults/{case['vault']}/members/{maker.id}", json={"right": "manage"})
    with new_client(maker) as as_maker:
        made = as_maker.post(f"/api/v1/documents/{case['doc']}/links", json={"recipient": "Bank", "days": 3}).json()
        assert as_maker.post(f"/api/v1/documents/{case['doc']}/links/{made['id']}/address").status_code == 200
        client.put(f"/api/v1/vaults/{case['vault']}/members/{maker.id}", json={"right": "edit"})
        answer = as_maker.post(f"/api/v1/documents/{case['doc']}/links/{made['id']}/address")
        assert answer.status_code == 404 and made["token"] not in answer.text
