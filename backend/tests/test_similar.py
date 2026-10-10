"""Finding what the person already has: the same file, and the same sheet scanned again.

The threshold of ``services/similar.py`` is not a guess: the first tests here measure it against made-up invoices of one
template (the case that fools a picture hash most) and the same invoice scanned again in ways that happen."""

from __future__ import annotations

import io
import random
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app import worker
from app.db import SessionLocal
from app.services import ocr, similar

from .conftest import make_account, new_client
from .intake import process_all, row_of, upload_and_read, upload_one, version_of
from .papers import own_vault, shared_vault

FONT = ImageFont.load_default(size=30)
SMALL = ImageFont.load_default(size=22)


def invoice(number: int, seed: int | None = None, lines: int = 12) -> Image.Image:
    """An invoice of Stadtwerke Lindenau for Julia Mustermann: the same form every month, other numbers and lines."""
    rng = random.Random(number if seed is None else seed)
    page = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(page)
    draw.text((100, 100), "Stadtwerke Lindenau", fill="black", font=FONT)
    draw.text((100, 150), "Musterweg 1, 12345 Lindenau", fill="black", font=SMALL)
    for row, text in enumerate(("Frau Julia Mustermann", "Beispielstrasse 5", "12345 Lindenau")):
        draw.text((100, 320 + row * 40), text, fill="black", font=SMALL)
    draw.text((100, 560), f"Rechnung Nr. 2026-{1000 + number}", fill="black", font=FONT)
    draw.text((700, 560), f"Datum: {1 + number % 28:02d}.{1 + number % 12:02d}.2026", fill="black", font=SMALL)
    y = 700
    for position in range(lines):
        item = rng.choice(["Strom Grundpreis", "Strom Arbeitspreis", "Gas", "Wasser", "Abwasser"])
        draw.text((100, y), f"Position {position + 1}  {item}  {rng.randint(10, 99)} kWh", fill="black", font=SMALL)
        draw.text((900, y), f"{rng.randint(1, 99)},{rng.randint(10, 99)} EUR", fill="black", font=SMALL)
        y += 45
    draw.line((100, y + 10, 1140, y + 10), fill="black", width=3)
    draw.text((700, y + 30), f"Summe {rng.randint(20, 400)},{rng.randint(10, 99)} EUR", fill="black", font=FONT)
    return page


def fingerprint(image: Image.Image) -> str:
    width = 512
    return worker.fingerprint(image.resize((width, round(image.height * width / image.width))))


def gap(a: str, b: str) -> int:
    return similar.distance(a, b)


def scanned_again(page: Image.Image) -> dict[str, Image.Image]:
    """The same sheet, the ways it comes back: another brightness, a little blur, half the resolution, a weak JPEG."""
    def jpeg(image: Image.Image, quality: int) -> Image.Image:
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=quality)
        return Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")

    return {
        "darker": ImageEnhance.Brightness(page).enhance(0.85),
        "brighter": ImageEnhance.Brightness(page).enhance(1.1),
        "blurred": page.filter(ImageFilter.GaussianBlur(1.0)),
        "half size": page.resize((620, 877), Image.Resampling.LANCZOS),
        "weak jpeg": jpeg(ImageEnhance.Brightness(page.resize((870, 1228))).enhance(1.1), 35),
    }


def test_the_threshold_lies_between_the_same_sheet_scanned_again_and_another_invoice_of_the_same_form() -> None:
    base = invoice(1)
    own = fingerprint(base)
    again = {name: gap(own, fingerprint(image)) for name, image in scanned_again(base).items()}
    others = [gap(own, fingerprint(invoice(n))) for n in range(2, 14)]
    # Every way of scanning again is within the threshold, every other invoice of the form is beyond it.
    assert max(again.values()) <= similar.THRESHOLD_BITS, again
    assert min(others) > similar.THRESHOLD_BITS, sorted(others)
    # The hash is a gradient hash of 32 x 32 bits in 256 hex digits.
    assert len(own) == 256 and 1 << 20 > gap(own, own) == 0


def test_two_other_invoices_of_the_same_form_are_far_from_each_other_in_all_pairs() -> None:
    prints = [fingerprint(invoice(n)) for n in range(1, 9)]
    pairs = [gap(a, b) for i, a in enumerate(prints) for b in prints[i + 1:]]
    assert min(pairs) > similar.THRESHOLD_BITS, sorted(pairs)[:5]


def test_a_page_with_almost_nothing_on_it_has_no_fingerprint_and_is_never_called_similar() -> None:
    assert fingerprint(Image.new("RGB", (1240, 1754), "white")) == ""
    line = Image.new("RGB", (1240, 1754), "white")
    ImageDraw.Draw(line).text((100, 100), "Rechnung", fill="black", font=SMALL)
    assert fingerprint(line) == ""
    assert similar.distance("", "a" * 256) > similar.THRESHOLD_BITS
    assert similar.distance("ab", "abc") > similar.THRESHOLD_BITS


def as_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def as_jpeg(image: Image.Image, quality: int = 80) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


@pytest.fixture
def first_scan(client: TestClient, operator: object) -> dict[str, Any]:
    return upload_and_read(client, "Rechnung 1.png", as_png(invoice(1)))


def test_the_same_sheet_scanned_again_gets_its_fingerprint_and_is_called_alike_only_with_its_text(
        client: TestClient, first_scan: dict[str, Any]) -> None:
    """A picture hash alone calls most follow-up invoices of one form a copy (the reviewer measured a median distance of 13
    bits of 1024 for monthly invoices), so the hint needs the text too (B3, ``tests/test_similar_text.py``)."""
    assert first_scan["duplicate"] is None
    assert version_of(first_scan["id"]).phash and len(version_of(first_scan["id"]).phash) == 256
    again = upload_and_read(client, "Rechnung 1 neu.jpg", as_jpeg(ImageEnhance.Brightness(invoice(1)).enhance(0.9)))
    # Alike once the text says so too (B3): where the text is recognised; without the recognition never by the picture.
    if ocr.available():
        assert again["duplicate"] == {"document_id": first_scan["id"], "title": "Rechnung 1", "kind": "similar"}
    else:
        assert again["duplicate"] is None and row_of(again["id"]).duplicate_of is None
    assert len(version_of(again["id"]).phash) == 256
    # The fingerprints are close (the same file drawn again, no turn).
    assert similar.distance(version_of(first_scan["id"]).phash, version_of(again["id"]).phash) <= similar.THRESHOLD_BITS
    other = upload_and_read(client, "Rechnung 2.png", as_png(invoice(2)))
    assert other["duplicate"] is None


def test_the_very_same_file_is_called_the_same_and_before_a_look_at_the_picture(client: TestClient,
                                                                                first_scan: dict[str, Any]) -> None:
    data = as_png(invoice(1))
    again = upload_one(client, "kopie.png", data)
    assert again["duplicate"] == {"document_id": first_scan["id"], "title": "Rechnung 1", "kind": "same"}
    process_all()
    # Reading keeps the finding that is stronger.
    assert row_of(again["id"]).duplicate_kind == "same" and row_of(again["id"]).duplicate_of == first_scan["id"]


def test_a_sheet_somebody_else_keeps_out_of_sight_is_not_mentioned(client: TestClient, operator: object) -> None:
    with new_client(make_account("lea")) as lea:
        upload_and_read(lea, "Privat.png", as_png(invoice(1)))
    with new_client(make_account("tom")) as tom:
        mine = upload_and_read(tom, "Meins.png", as_png(invoice(1)))
        assert mine["duplicate"] is None
    assert row_of(mine["id"]).duplicate_of is None


def test_a_sheet_in_a_vault_the_person_shares_is_found_and_stops_being_found_when_it_moves_out_of_sight(
        client: TestClient, operator: object) -> None:
    lea, tom = make_account("lea"), make_account("tom")
    household = shared_vault("Household", make_account("boss"), (lea, "edit"), (tom, "edit"))
    with new_client(lea) as lea_browser:
        shared = upload_and_read(lea_browser, "Haushalt.png", as_png(invoice(1)), vault_id=household)
        with new_client(tom) as tom_browser:
            mine = upload_and_read(tom_browser, "Meins.png", as_png(invoice(1)))
            assert mine["duplicate"] == {"document_id": shared["id"], "title": "Haushalt", "kind": "same"}
            # The other document leaves the shared vault for the personal one of lea: tom no longer sees it, so the hint
            # is gone for him, while the record itself stays.
            assert lea_browser.post(f"/api/v1/documents/{shared['id']}/move",
                                    json={"vault_id": own_vault(lea)}).status_code == 200
            assert tom_browser.get(f"/api/v1/documents/{mine['id']}").json()["duplicate"] is None
            assert row_of(mine["id"]).duplicate_of == shared["id"]
            # Back in the shared vault it is there again.
            lea_browser.post(f"/api/v1/documents/{shared['id']}/move", json={"vault_id": household})
            assert tom_browser.get(f"/api/v1/documents/{mine['id']}").json()["duplicate"]["document_id"] == shared["id"]
            # And in the trash it is not a document to point at.
            lea_browser.delete(f"/api/v1/documents/{shared['id']}")
            assert tom_browser.get(f"/api/v1/documents/{mine['id']}").json()["duplicate"] is None


def test_what_the_list_shows_is_checked_per_reader_too(client: TestClient, operator: object) -> None:
    lea, tom = make_account("lea"), make_account("tom")
    household = shared_vault("Household", make_account("boss"), (lea, "edit"), (tom, "read"))
    with new_client(lea) as lea_browser:
        upload_and_read(lea_browser, "Eins.png", as_png(invoice(1)))
        second = upload_and_read(lea_browser, "Zwei.png", as_png(invoice(1)), vault_id=household)
        # She sees both, so she is told that the second is the same file as the first.
        assert second["duplicate"]["title"] == "Eins"
    with new_client(tom) as tom_browser:
        # Tom sees the second, which stands in the shared vault, but not the first, in the vault of lea: nothing of it.
        listed = tom_browser.get("/api/v1/documents").json()["items"]
        assert [d["id"] for d in listed] == [second["id"]] and listed[0]["duplicate"] is None
        assert tom_browser.get(f"/api/v1/documents/{second['id']}").json()["duplicate"] is None
        assert tom_browser.get("/api/v1/changes?since=0").json()["items"][0]["document"]["duplicate"] is None
    assert row_of(second["id"]).duplicate_of is not None


def test_a_search_never_compares_what_it_may_not_see(client: TestClient, operator: object) -> None:
    lea, tom = make_account("lea"), make_account("tom")
    with new_client(lea) as lea_browser:
        hidden = upload_and_read(lea_browser, "Privat.png", as_png(invoice(1)))
    phash = version_of(hidden["id"]).phash
    assert phash
    with SessionLocal() as db:
        assert similar.similar_file(db, tom.id, phash) is None
        assert similar.same_file(db, tom.id, version_of(hidden["id"]).sha256) is None
        assert similar.similar_file(db, lea.id, phash) is not None
        assert similar.similar_file(db, lea.id, phash, exclude=hidden["id"]) is None


def test_the_nearest_document_wins_among_several(client: TestClient, operator: object) -> None:
    near = upload_and_read(client, "Nah.png", as_png(invoice(1)))
    upload_and_read(client, "Anders.png", as_png(invoice(5)))
    phash = version_of(near["id"]).phash
    with SessionLocal() as db:
        found = similar.similar_file(db, row_of(near["id"]).owner_id, phash)  # type: ignore[arg-type]
        assert found is not None and found.id == near["id"]


def test_a_reader_of_the_shared_copy_learns_nothing_of_the_same_file_in_a_vault_he_cannot_see(
        client: TestClient, operator: object) -> None:
    """The reviewer found `duplicate: same` in the history (`processed`) of the copy in the shared vault: anybody who could
    read that document could tell that its maker keeps the file elsewhere. Nothing of it may stand in any answer."""
    lea, tom = make_account("lea"), make_account("tom")
    household = shared_vault("Household", make_account("boss"), (lea, "edit"), (tom, "read"))
    data = as_png(invoice(7))
    with new_client(lea) as lea_browser:
        hidden = upload_and_read(lea_browser, "Geheim Arztbrief.png", data)
        shared = upload_and_read(lea_browser, "Haushalt.png", data, vault_id=household)
        assert shared["duplicate"]["document_id"] == hidden["id"]  # she sees both
    with new_client(tom) as tom_browser:
        answers = [
            tom_browser.get(f"/api/v1/documents/{shared['id']}").text,
            tom_browser.get(f"/api/v1/documents/{shared['id']}/events").text,
            tom_browser.get("/api/v1/documents").text,
            tom_browser.get("/api/v1/changes?since=0").text,
            tom_browser.get(f"/api/v1/documents/{shared['id']}/versions").text,
        ]
        events = tom_browser.get(f"/api/v1/documents/{shared['id']}/events").json()
    joined = " ".join(answers)
    assert "Geheim" not in joined and '"same"' not in joined and "similar" not in joined
    # Where the text is recognised, the proposals read from it come after (``proposed``: field names and sources only).
    assert [e["action"] for e in events if e["action"] != "proposed"][:2] == ["processed", "created"]
    assert all(set(e["detail"]) <= {"fields", "from"} for e in events if e["action"] == "proposed")
    # Numbers only (the text is recognised where the image carries Tesseract).
    recognised = 1 if ocr.available() else 0
    processed = next(e for e in events if e["action"] == "processed")
    assert processed["detail"] == {"pages": 1, "text_pages": recognised, "ocr_pages": recognised}
    assert all("duplicate" not in str(e["detail"]) for e in events)
    # And for lea herself the history says the same: the hint is a field of the document, not a line of the history.
    with new_client(lea) as lea_browser:
        assert "duplicate" not in lea_browser.get(f"/api/v1/documents/{shared['id']}/events").text
