"""What kind a file is comes from its content, never from its name or the type it claims."""

from __future__ import annotations

import pytest

from app.services import filetypes
from app.services.filetypes import NotAccepted, sniff

from . import files


@pytest.mark.parametrize("data, kind", [
    (files.make_pdf(), "pdf"),
    (files.make_image("jpeg"), "jpeg"),
    (files.make_image("png"), "png"),
    (files.make_tiff(2), "tiff"),
    (files.make_image("heic"), "heic"),
    (files.invoice_xml(), "xml"),
    (files.cii_xml(), "xml"),
], ids=["pdf", "jpeg", "png", "tiff", "heic", "ubl", "cii"])
def test_each_kind_that_is_taken_is_found_by_its_content(data: bytes, kind: str) -> None:
    assert sniff(data).kind == kind
    assert sniff(data[:filetypes.HEAD]).kind == kind  # the first bytes are enough


def test_a_pdf_may_start_after_a_byte_order_mark_and_white_space_and_after_nothing_else() -> None:
    assert sniff(b"\xef\xbb\xbf\r\n %PDF-1.7\n").kind == "pdf"
    # A program or a page with the marker somewhere behind other bytes is no PDF.
    with pytest.raises(NotAccepted):
        sniff(files.EXE + b"%PDF-1.4")
    with pytest.raises(NotAccepted):
        sniff(b"MZ%PDF-1.4")


@pytest.mark.parametrize("data", [
    files.EXE, files.HTML, files.SVG, b"GIF89a" + b"\x00" * 40, b"plain text", b"", b"\x00" * 100,
    b"PK\x03\x04" + b"\x00" * 60,  # a ZIP (an office document, an app package)
    b"#!/bin/sh\nrm -rf /\n",
    b"\x7fELF" + b"\x00" * 60,
    b"RIFF\x00\x00\x00\x00WAVEfmt ",
    b"RIFF\x00\x00\x00\x00WEBPJUNK",
    b"RIFF\x00\x00\x00\x00WAVEVP8 ",  # a chunk name of WebP in another kind of RIFF file
    b"RIFF\x00\x00\x00\x00AVI LIST",
    b"RIFF\x00\x00",
])
def test_what_is_not_a_document_is_turned_away_whatever_it_is_called(data: bytes) -> None:
    with pytest.raises(NotAccepted) as refused:
        sniff(data)
    assert refused.value.reason in ("unsupported_type", "xml_not_invoice", "xml_doctype")


def test_xml_is_taken_only_as_an_e_invoice_and_without_a_document_type() -> None:
    with pytest.raises(NotAccepted) as other:
        sniff(b'<?xml version="1.0"?><note><to>x</to></note>')
    assert other.value.reason == "xml_not_invoice"
    entity = (b'<?xml version="1.0"?><!DOCTYPE Invoice [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
              b"<Invoice>&xxe;</Invoice>")
    with pytest.raises(NotAccepted) as refused:
        sniff(entity)
    assert refused.value.reason == "xml_doctype"
    # A comment or a byte order mark before the first element changes nothing.
    assert sniff(b"\xef\xbb\xbf<!-- made up --><Invoice/>").kind == "xml"
    # An SVG and a web page are not invoices, with or without a prolog.
    for text in (files.SVG, b'<?xml version="1.0"?>' + files.SVG, files.HTML, b"<html></html>"):
        with pytest.raises(NotAccepted):
            sniff(text)


def test_webp_and_avif_are_taken_by_their_first_bytes() -> None:
    assert sniff(files.make_image("webp")).kind == "webp"
    assert sniff(files.make_animated_webp(2)).kind == "webp"
    assert sniff(files.make_image("avif")).kind == "avif"
    assert sniff(b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf").kind == "avif"
    assert sniff(b"\x00\x00\x00\x18ftypavis\x00\x00\x00\x00avismif1").kind == "avif"
    assert sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ").extension == ".webp"
    assert filetypes.MEDIA_TYPE["webp"] == "image/webp" and filetypes.MEDIA_TYPE["avif"] == "image/avif"
    # AVIF shares the container with HEIC (the generic brand ``mif1``): the codec brand decides.
    assert sniff(b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1heic").kind == "heic"


def test_the_sentence_for_a_refused_file_names_every_kind_that_is_taken() -> None:
    with pytest.raises(NotAccepted) as refused:
        sniff(b"GIF89a" + b"\x00" * 100)
    for name in ("PDF", "JPEG", "PNG", "TIFF", "HEIC", "WebP", "AVIF", "XML"):
        assert name in refused.value.text


def test_a_heic_photo_is_told_apart_from_other_files_of_the_same_container_family() -> None:
    mp4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    with pytest.raises(NotAccepted):
        sniff(mp4)


@pytest.mark.parametrize("name, title", [
    ("Strom Oktober.pdf", "Strom Oktober"),
    ("C:\\Users\\jule\\scan 001.PNG", "scan 001"),
    ("../../etc/passwd", "passwd"),
    ("..\\..\\boot.ini.pdf", "boot.ini"),
    ("tab\tand\nnewline.jpg", "tab and newline"),
    ("", "Document"),
    (".pdf", "Document"),
    ("  ..  ", "Document"),
    ("a" * 400 + ".pdf", "a" * 196),
    ("archive.tar.gz", "archive.tar"),
], ids=["plain", "windows path", "traversal", "backslash traversal", "control characters", "empty", "only ending",
        "dots", "long", "double ending"])
def test_the_name_of_a_file_is_only_a_proposal_for_a_title_and_a_safe_one(name: str, title: str) -> None:
    assert filetypes.title_from(name) == title


def test_every_file_dialog_and_the_share_menu_offer_what_the_server_takes_and_nothing_else() -> None:
    """The lists of the browser (``frontend/src/lib/formats.ts`` and the share target of the manifest) follow the kinds
    of this module: a kind added here without the lists would be taken but never offered, a kind in the lists
    without the server would be offered and turned away."""
    import json
    import re
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend"
    source = (frontend / "src" / "lib" / "formats.ts").read_text(encoding="utf-8")
    manifest = json.loads((frontend / "public" / "manifest.webmanifest").read_text(encoding="utf-8"))
    shared = set(manifest["share_target"]["params"]["files"][0]["accept"])
    endings = set(re.findall(r"'(\.[a-z0-9]+)'", source))
    types = set(re.findall(r"'((?:application|image|text)/[a-z0-9.+-]+)'", source))
    assert "image/*" not in shared and "image/*" not in types
    for kind in filetypes.KINDS:
        assert filetypes.EXTENSION[kind] in endings, kind
        assert filetypes.EXTENSION[kind] in shared, kind
        assert filetypes.MEDIA_TYPE[kind] in types, kind
        assert filetypes.MEDIA_TYPE[kind] in shared or kind == "xml", kind
    # Nothing is offered that the server turns away: every ending offered is one of a kind that is taken (the two
    # alternative spellings of JPEG and TIFF, and of HEIF, aside).
    spellings = {".jpeg": "jpeg", ".tiff": "tiff", ".heif": "heic"}
    for ending in endings:
        assert filetypes.KIND_OF_EXTENSION.get(ending) or ending in spellings, ending
