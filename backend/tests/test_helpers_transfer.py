"""The transfer code ("Überweisen", K1): what a transfer for a document can take with where each part comes from, and
the EPC QR code for one of the document's own IBANs. The lines are checked against the example of the standard
(EPC069-12); hostile input (a line break in the purpose, too long, a strange IBAN, another currency) is refused; the
IBAN and the purpose never reach the log; reading the document is enough, a link never is."""

from __future__ import annotations

import logging
from typing import Any

import pytest
import segno
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, Document, EInvoice, Version
from app.services import changes, settings_service, transfer

from .conftest import make_account, new_client
from .papers import add_document, own_vault, shared_vault
from .searching import give_text


def iban(country: str, bban: str) -> str:
    """An IBAN with the right check digits, made here (no real account)."""
    moved = bban + country + "00"
    digits = "".join(str(int(char, 36)) for char in moved)
    return f"{country}{98 - int(digits) % 97:02d}{bban}"


#: Two made-up IBANs of the same made-up bank, and one of nobody's documents.
FIRST = iban("DE", "1203000000" + "00004711")
SECOND = iban("DE", "1203000000" + "00004712")
STRANGER = iban("DE", "1203000000" + "00009999")
SPACED = " ".join(FIRST[i:i + 4] for i in range(0, len(FIRST), 4))


def path(document_id: int) -> str:
    return f"/api/v1/documents/{document_id}/transfer"


def code(client: TestClient, document_id: int, **body: Any) -> Any:
    return client.post(f"{path(document_id)}/code", json={"iban": FIRST, "amount": 12345, "purpose": "R-2026-17",
                                                            **body})


def with_invoice(document_id: int, *, payable: int | None = 10050, currency: str = "EUR", seller: str = "Stadtwerke "
                 "Lindenau", number: str = "R-2026-00017", account: str = FIRST, credit_note: bool = False) -> None:
    """The document carries an e-invoice with these data (as reading the XML would leave them)."""
    with SessionLocal() as db:
        changes.write_lock(db)
        row = db.get(Document, document_id)
        assert row is not None
        version = db.scalar(select(Version).where(Version.document_id == document_id))
        assert version is not None
        db.add(EInvoice(version_id=version.id, document_id=document_id, format="XRechnung (UBL)", number=number,
                        seller=seller, seller_vat="", buyer="", buyer_ref="", iban=account, currency=currency,
                        payable=payable, credit_note=credit_note))
        row.change_seq = changes.next_seq(db)
        db.commit()


@pytest.fixture
def jule(client: TestClient) -> Account:
    return make_account("jule")


# --- The lines of the code ----------------------------------------------------------------------------------------


def test_the_lines_are_those_of_the_example_of_the_standard() -> None:
    """EPC069-12, the example of a version 001 code (BIC, purpose code, a text and a note to the payer)."""
    made = transfer.payload(name="Red Cross of Belgium", iban="BE72000000001616", cents=100, text="Urgency fund",
                            bic="BPOTBEB1", purpose_code="CHAR", info="Sample EPC QR code", version="001")
    assert made == (b"BCD\n001\n1\nSCT\nBPOTBEB1\nRed Cross of Belgium\nBE72000000001616\nEUR1\nCHAR\n\n"
                    b"Urgency fund\nSample EPC QR code")


def test_nexpapers_own_lines_are_version_2_in_utf_8_with_a_point_and_two_places() -> None:
    made = transfer.payload(name="Stadtwerke Lindenau", iban=FIRST, cents=1234567, text="R-2026-00017 Müller")
    lines = made.decode("utf-8").split("\n")
    assert lines == ["BCD", "002", "1", "SCT", "", "Stadtwerke Lindenau", FIRST, "EUR12345.67", "", "",
                     "R-2026-00017 Müller"]
    assert transfer.payload(name="A", iban=FIRST, cents=5).decode().split("\n")[-1] == "EUR0.05", "no empty end"
    assert transfer.amount_text(99_999_999_999) == "EUR999999999.99"
    # Always two places, the point as the sign, no separator of thousands.
    assert [transfer.amount_text(c) for c in (1, 10, 1230, 100000, 123456789)] == [
        "EUR0.01", "EUR0.10", "EUR12.30", "EUR1000.00", "EUR1234567.89"]
    for wrong in (0, -1, 100_000_000_000):
        with pytest.raises(Exception) as caught:
            transfer.payload(name="A", iban=FIRST, cents=wrong)
        assert caught.value.status_code == 422  # type: ignore[attr-defined]


def test_the_svg_is_the_code_of_exactly_these_lines(client: TestClient, jule: Account) -> None:
    doc = add_document(own_vault(jule), jule, "Strom", sender="Stadtwerke Lindenau", amount=12345)
    give_text(doc, f"Rechnungsnummer R-2026-17\nBitte überweisen an {SPACED}")
    with new_client(jule) as browser:
        answer = code(browser, doc, iban=SPACED.lower())
        assert answer.status_code == 200, answer.text
        assert answer.headers["content-type"].startswith("image/svg+xml")
        assert answer.headers["cache-control"] == "no-store"
    wanted = transfer.svg_of(b"BCD\n002\n1\nSCT\n\nStadtwerke Lindenau\n" + FIRST.encode()
                             + b"\nEUR123.45\n\n\nR-2026-17")
    assert answer.text == wanted
    # The code itself: error correction M, as the standard asks.
    assert segno.make_qr(b"x", error="m", boost_error=False).error == "M"


# --- What the document gives ---------------------------------------------------------------------------------------


def test_from_the_text_each_part_says_where_it_comes_from(client: TestClient, jule: Account) -> None:
    doc = add_document(own_vault(jule), jule, "Werkstatt", sender="Autohaus Lindenau", amount=48900)
    give_text(doc, f"Rechnung Nr. W-88123\nIBAN {FIRST}\noder {SECOND}\nfalsch DE00120300000000004711")
    with new_client(jule) as browser:
        found = browser.get(path(doc)).json()
    assert found["ready"] is True and found["missing"] == []
    assert found["recipient"] == "Autohaus Lindenau" and found["recipient_origin"] == "sender"
    assert found["ibans"] == [{"iban": FIRST, "origin": "text"}, {"iban": SECOND, "origin": "text"}]
    assert (found["amount"], found["amount_origin"], found["currency"]) == (48900, "document", "EUR")
    assert (found["purpose"], found["purpose_origin"]) == ("W-88123", "text")


def test_an_e_invoice_goes_first_and_the_text_is_not_asked(client: TestClient, jule: Account) -> None:
    doc = add_document(own_vault(jule), jule, "Strom", sender="SWL", amount=99999)
    give_text(doc, f"Rechnung Nr. FAKE-1\nIBAN {STRANGER}")
    with_invoice(doc)
    with new_client(jule) as browser:
        found = browser.get(path(doc)).json()
        assert found["recipient"] == "Stadtwerke Lindenau" and found["recipient_origin"] == "einvoice"
        assert found["ibans"] == [{"iban": FIRST, "origin": "einvoice"}]
        assert (found["amount"], found["amount_origin"]) == (10050, "einvoice")
        assert (found["purpose"], found["purpose_origin"]) == ("R-2026-00017", "einvoice")
        # The IBAN of the text is no choice any more.
        assert code(browser, doc, iban=STRANGER).json()["detail"]["code"] == "unknown_iban"
        assert code(browser, doc).status_code == 200


@pytest.mark.parametrize(("fields", "invoice", "missing"), [
    ({"amount": None}, None, ["amount"]),
    ({"amount": 0}, None, ["amount"]),
    ({"amount": -500}, None, ["amount"]),
    ({"amount": 500, "currency": "CHF"}, None, ["currency"]),
    ({"amount": 500}, {"currency": "USD"}, ["currency"]),
    ({"amount": 500}, {"credit_note": True}, ["credit_note"]),
])
def test_what_is_not_enough_says_why(client: TestClient, jule: Account, fields: dict[str, Any],
                                     invoice: dict[str, Any] | None, missing: list[str]) -> None:
    currency = fields.pop("currency", None)
    doc = add_document(own_vault(jule), jule, "Beleg", sender="Laden", **fields)
    if currency:
        with SessionLocal() as db:
            row = db.get(Document, doc)
            assert row is not None
            row.currency = currency
            db.commit()
    give_text(doc, f"IBAN {FIRST}")
    if invoice is not None:
        with_invoice(doc, **invoice)
    with new_client(jule) as browser:
        found = browser.get(path(doc)).json()
        assert found["ready"] is False and found["missing"] == missing
        answer = code(browser, doc)
        if missing == ["amount"]:
            assert answer.status_code == 200, "the amount is typed in the dialog"
        else:
            assert answer.status_code == 409 and answer.json()["detail"]["code"] == "transfer_not_possible"


def test_no_iban_no_sender(client: TestClient, jule: Account) -> None:
    doc = add_document(own_vault(jule), jule, "Zettel", amount=500)
    give_text(doc, "Kein Konto hier")
    with new_client(jule) as browser:
        found = browser.get(path(doc)).json()
        assert found["missing"] == ["iban", "recipient"] and found["recipient_origin"] is None
        assert code(browser, doc).status_code == 409


# --- Hostile input --------------------------------------------------------------------------------------------------


@pytest.fixture
def ready(client: TestClient, jule: Account) -> int:
    doc = add_document(own_vault(jule), jule, "Strom", sender="Stadtwerke Lindenau", amount=12345)
    give_text(doc, f"Rechnungsnummer R-2026-17\nIBAN {FIRST}")
    return doc


@pytest.mark.parametrize("purpose", ["R-17\nBCD", "R-17\r\nX", "Tab\there", "a" * 141, "Rechnung <17>", "€ 12",
                                     "Zeile\u2028zwei", "\u202eabc"])
def test_a_purpose_outside_the_standard_is_refused(jule: Account, ready: int, purpose: str) -> None:
    with new_client(jule) as browser:
        answer = code(browser, ready, purpose=purpose)
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "invalid_purpose", answer.text


def test_the_purpose_may_be_empty_or_hold_the_umlauts(jule: Account, ready: int) -> None:
    with new_client(jule) as browser:
        assert code(browser, ready, purpose="").status_code == 200
        assert code(browser, ready, purpose="Müller Größe (2026) R-17/3, 'ok'? + :").status_code == 200
        assert code(browser, ready, purpose="a" * 140).status_code == 200


@pytest.mark.parametrize("amount", [0, -1, 100_000_000_000, 12.5, "100"])
def test_an_amount_outside_the_bounds_is_refused(jule: Account, ready: int, amount: Any) -> None:
    with new_client(jule) as browser:
        assert code(browser, ready, amount=amount).status_code == 422


@pytest.mark.parametrize("other", [STRANGER, "DE00120300000000004711", "", "x" * 60, FIRST + "0"])
def test_never_a_code_for_an_iban_the_document_does_not_carry(jule: Account, ready: int, other: str) -> None:
    with new_client(jule) as browser:
        answer = code(browser, ready, iban=other)
    assert answer.status_code == 422, answer.text
    assert answer.json()["detail"]["code"] in ("unknown_iban", "validation_error", "invalid_input") or \
        answer.json()["detail"][0]["type"]


def test_a_long_name_is_cut_to_seventy_characters(client: TestClient, jule: Account) -> None:
    doc = add_document(own_vault(jule), jule, "Lang", sender="Sehr " * 30, amount=100)
    give_text(doc, f"IBAN {FIRST}")
    with new_client(jule) as browser:
        found = browser.get(path(doc)).json()
        assert len(found["recipient"]) <= 70
        assert code(browser, doc).status_code == 200


def test_the_iban_and_the_purpose_never_reach_the_log(jule: Account, ready: int,
                                                      caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with new_client(jule) as browser:
        browser.get(path(ready))
        code(browser, ready, purpose="Geheimzweck 4242")
        code(browser, ready, iban=STRANGER, purpose="Geheimzweck 4242")
        code(browser, ready, purpose="Geheim\nzweck")
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for secret in (FIRST, STRANGER, FIRST[4:], "Geheimzweck", "4242"):
        assert secret not in logged


# --- Rights -----------------------------------------------------------------------------------------------------------


def test_reading_is_enough_and_a_stranger_sees_nothing(client: TestClient, operator: Account) -> None:
    jule, lea, bob = make_account("jule"), make_account("lea"), make_account("bob")
    house = shared_vault("Haushalt", operator, (jule, "manage"), (lea, "read"))
    doc = add_document(house, jule, "Strom", sender="Stadtwerke Lindenau", amount=12345)
    give_text(doc, f"IBAN {FIRST}")
    with new_client(lea) as reader:
        assert reader.get(path(doc)).json()["ready"] is True
        assert code(reader, doc).status_code == 200
    with new_client(bob) as stranger:
        assert stranger.get(path(doc)).status_code == 404
        assert code(stranger, doc).status_code == 404
        assert code(stranger, doc, iban=STRANGER).status_code == 404, "the rights come first"


@pytest.mark.parametrize("right", ["read", "edit"])
def test_a_share_alone_is_enough(client: TestClient, right: str) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    doc = add_document(own_vault(jule), jule, "Strom", sender="Stadtwerke Lindenau", amount=12345)
    give_text(doc, f"IBAN {FIRST}")
    with new_client(jule) as owner:
        assert owner.put(f"/api/v1/documents/{doc}/shares/{tom.id}", json={"right": right}).status_code == 200
    with new_client(tom) as shared:
        assert shared.get(path(doc)).json()["ibans"][0]["iban"] == FIRST
        assert code(shared, doc).status_code == 200


def test_a_device_reads_and_makes_the_code(client: TestClient, jule: Account, ready: int) -> None:
    with new_client(jule) as browser:
        token = browser.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(browser.app, base_url="http://testserver") as device:
        headers = {"Authorization": f"Bearer {token}"}
        assert device.get(path(ready), headers=headers).status_code == 200
        assert device.post(f"{path(ready)}/code", json={"iban": FIRST, "amount": 1, "purpose": ""},
                           headers=headers).status_code == 200


@pytest.mark.parametrize("scope", ["read", "upload"])
def test_a_key_reads_with_read_only_and_never_makes_a_code(client: TestClient, jule: Account, ready: int,
                                                           scope: str) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(jule) as browser:
        secret = browser.post("/api/v1/api-keys", json={"name": "k", "scope": scope}).json()["secret"]
    with TestClient(browser.app, base_url="http://testserver") as program:
        headers = {"Authorization": f"Bearer {secret}"}
        assert program.get(path(ready), headers=headers).status_code == (200 if scope == "read" else 403)
        assert program.post(f"{path(ready)}/code", json={"iban": FIRST, "amount": 1, "purpose": ""},
                            headers=headers).status_code == 401


def test_never_through_a_link(client: TestClient, jule: Account, ready: int) -> None:
    with new_client(jule) as browser:
        made = browser.post(f"/api/v1/documents/{ready}/links", json={"recipient": "Steuerbüro", "days": 3})
        assert made.status_code in (200, 201), made.text
        token = made.json()["url"].rstrip("/").rsplit("/", 1)[-1]
    with TestClient(browser.app, base_url="http://testserver") as outsider:
        for method, where in (("GET", path(ready)), ("POST", f"{path(ready)}/code"),
                              ("GET", f"/api/v1/l/{token}/transfer"), ("POST", f"/api/v1/l/{token}/transfer/code")):
            answer = outsider.request(method, where, headers={"Authorization": f"Bearer {token}"},
                                      json={"iban": FIRST, "amount": 1, "purpose": ""})
            assert answer.status_code in (400, 401, 404, 405), (method, where, answer.status_code)
        page = outsider.get(f"/api/v1/l/{token}")
        assert page.status_code == 200 and FIRST not in page.text
    # No route of a link speaks of a transfer.
    assert not [route for route in browser.app.routes if "/l/" in getattr(route, "path", "")
                and "transfer" in getattr(route, "path", "")]


@pytest.mark.parametrize("breaker", ["\n", "\r", "\r\n", "\x0b", "\x0c", "\x1e", "\x85", "\u2028", "\u2029"])
def test_a_name_from_an_e_invoice_never_parts_the_lines_of_the_code(client: TestClient, jule: Account,
                                                                      breaker: str) -> None:
    """The seller's name comes out of a file somebody sent. A line break in it must not start a new line of the code:
    what follows would be read as the next field (another IBAN). It becomes one line with a blank."""
    doc = add_document(own_vault(jule), jule, "Strom", sender="Stadtwerke Lindenau", amount=12345)
    with_invoice(doc, seller=f"Stadtwerke{breaker}{STRANGER}{breaker}Lindenau")
    with new_client(jule) as browser:
        found = browser.get(path(doc)).json()
        assert found["recipient"] == f"Stadtwerke {STRANGER} Lindenau" and found["ready"] is True
        answer = code(browser, doc)
        assert answer.status_code == 200, answer.text
    lines = b"BCD\n002\n1\nSCT\n\nStadtwerke " + STRANGER.encode() + b" Lindenau\n" + FIRST.encode() \
        + b"\nEUR123.45\n\n\nR-2026-17"
    assert answer.text == transfer.svg_of(lines)
    assert lines.count(b"\n") == 10


@pytest.mark.parametrize("breaker", ["\n", "\r", "\x85", "\u2028", "\x00"])
def test_the_lines_refuse_what_could_part_them(breaker: str) -> None:
    """The last guard, whatever cleaned the parts before: no part of a code holds a character that ends a line."""
    for parts in ({"name": f"A{breaker}B", "iban": FIRST, "cents": 100},
                  {"name": "A", "iban": FIRST, "cents": 100, "text": f"R{breaker}1"},
                  {"name": "A", "iban": f"{FIRST}{breaker}", "cents": 100}):
        with pytest.raises(Exception) as caught:
            transfer.payload(**parts)  # type: ignore[arg-type]
        assert caught.value.status_code == 422  # type: ignore[attr-defined]
