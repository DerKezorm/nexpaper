"""A Paperless that misbehaves at the level of bytes and addresses: files without a length over the limit, a packed
answer that unpacks to far more than allowed, a file that drips past its deadline (with no socket to stop it), the
address forms that must never be reached, an archive that is not a whole PDF, and a redirect or an address changed
since the last start."""

from __future__ import annotations

import gzip
import socket
import tracemalloc
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.models import Account
from app.services import outbound, paperless

from . import fake_paperless
from .test_paperless import connect, pdf, run_import, run_state

HOST = "paperless.example.com"


@pytest.fixture(autouse=True)
def clean_folders() -> Iterator[None]:
    import shutil

    from .conftest import DATA_DIR

    shutil.rmtree(Path(DATA_DIR) / "paperless", ignore_errors=True)
    yield


@pytest.fixture
def fake() -> Iterator[tuple[fake_paperless.Paperless, fake_paperless.Server]]:
    made = fake_paperless.Paperless()
    server = fake_paperless.start(made)
    try:
        yield made, server
    finally:
        fake_paperless.stop(server)


class Pieces(httpx.SyncByteStream):
    """A body that comes in pieces, with no length announced; ``each`` runs before every piece."""

    def __init__(self, pieces: list[bytes], each: Any = None) -> None:
        self.pieces = pieces
        self.each = each
        self.sent = 0

    def __iter__(self) -> Iterator[bytes]:
        for piece in self.pieces:
            if self.each is not None:
                self.each()
            self.sent += 1
            yield piece


def numeric_only(host: str, port: int) -> list[str]:
    """Names of the tests resolve here; everything else only as written (no lookup in any DNS)."""
    if host.rstrip(".").lower() in (HOST, "localhost"):
        return ["127.0.0.1"]
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, flags=socket.AI_NUMERICHOST)
    except (OSError, UnicodeError) as exc:
        raise outbound.Unreachable(host) from exc
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


@pytest.fixture
def stand_in(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Paperless as a transport in memory (no socket, so only nexpaper's own checks keep the limits)."""
    answers: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        found = answers.get(request.url.path)
        if found is None:
            return httpx.Response(404, json={"detail": "Not found."})
        return found() if callable(found) else found

    monkeypatch.setattr(paperless, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(paperless, "resolver", numeric_only)
    return answers


def client_of() -> paperless.Client:
    return paperless.Client(paperless.Connection(f"http://{HOST}/", "made-up", True))


def test_a_file_without_a_length_ends_at_the_limit(stand_in: dict[str, Any], tmp_path: Path) -> None:
    stream = Pieces([b"%PDF-1.4\n" + b"x" * 400_000, b"y" * 400_000, b"z" * 400_000, b"w" * 400_000])
    stand_in["/api/documents/1/download/"] = lambda: httpx.Response(200, stream=stream)
    target = tmp_path / "file"
    with client_of() as client, pytest.raises(paperless.Skip) as caught:
        client.download("api/documents/1/download/", {}, target, 1_000_000)
    assert caught.value.reason == "too_large"
    assert not target.exists() and stream.sent == 3


def test_a_dripping_file_ends_at_its_deadline(stand_in: dict[str, Any], tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """No socket here: only the look at the clock after every piece ends it."""
    now = [0.0]
    monkeypatch.setattr(paperless, "ticks", lambda: now[0])
    monkeypatch.setattr(paperless, "FILE_SECONDS", 10.0)

    def later() -> None:
        now[0] += 3.0

    stream = Pieces([b"%PDF-1.4\n"] + [b"x"] * 20, each=later)
    stand_in["/api/documents/1/download/"] = lambda: httpx.Response(200, stream=stream)
    target = tmp_path / "file"
    with client_of() as client, pytest.raises(paperless.Skip) as caught:
        client.download("api/documents/1/download/", {}, target, 10_000_000)
    assert caught.value.reason == "download_timeout"
    assert not target.exists() and stream.sent < 6


def test_a_packed_answer_is_unpacked_only_up_to_the_limit(stand_in: dict[str, Any],
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """64 MB of zeros in 64 KB: the answer is refused, and never more than about the limit is held in memory."""
    bomb = gzip.compress(b"\0" * (64 * 1024 * 1024), 9)
    monkeypatch.setattr(paperless, "JSON_MAX", 1024 * 1024)
    stand_in["/api/tags/"] = lambda: httpx.Response(
        200, headers={"content-encoding": "gzip", "content-type": "application/json", "x-api-version": "7"},
        stream=Pieces([bomb[i : i + 16384] for i in range(0, len(bomb), 16384)]))
    tracemalloc.start()
    try:
        with client_of() as client, pytest.raises(paperless.Failure) as caught:
            client.get("api/tags/", {"page_size": 1})
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert caught.value.code == "paperless_unreadable"
    assert peak < 16 * 1024 * 1024, peak


def test_an_archive_that_is_not_a_whole_pdf_is_not_taken(tmp_path: Path) -> None:
    whole = tmp_path / "whole.pdf"
    whole.write_bytes(pdf("ganz"))
    cut = tmp_path / "cut.pdf"
    cut.write_bytes(b"%PDF-1.4\n" + b"x" * 5000)
    assert paperless.whole_pdf(whole) and not paperless.whole_pdf(cut)


def test_an_archive_that_is_not_whole_leaves_the_document_without_one(client: TestClient, operator: Account,
                                                                      fake: Any) -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Document, Version

    made, server = fake
    made.add(fake_paperless.Doc(1, "Halbe Archivfassung", pdf("Original"), archive=b"%PDF-1.4\n" + b"x" * 3000))
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    assert run_state(client)["taken"] == 1
    assert not list(paperless.staging().glob("*.pdf"))
    with SessionLocal() as db:
        document = db.scalar(select(Document))
        version = db.scalar(select(Version))
        assert document is not None and version is not None and version.archive_path == ""


# --- Addresses -------------------------------------------------------------------------------------------------------

#: The forms of the prover: in the own network (refused without the switch) or never reachable (refused with it).
FORMS = [
    "http://127.0.0.1:{p}/", "http://localhost:{p}/", "http://[::1]:{p}/", "http://2130706433:{p}/",
    "http://0x7f000001:{p}/", "http://0177.0.0.1:{p}/", "http://127.1:{p}/", "http://0.0.0.0:{p}/",
    "http://[::ffff:127.0.0.1]:{p}/", "http://[::ffff:7f00:1]:{p}/", "http://[::]:{p}/", "http://10.0.0.1/",
    "http://192.168.1.1/", "http://100.64.0.1/", "http://[fc00::1]/", "http://[64:ff9b::7f00:1]/",
    "http://[2002:7f00:1::]/", "http://172.16.0.1/", "http://169.254.169.254/", "http://[fe80::1]/",
    "http://[fd00:ec2::254]/", "http://[::ffff:169.254.169.254]/", "http://[64:ff9b::a9fe:a9fe]/",
    "http://[2002:a9fe:a9fe::]/", "http://100.100.100.200/", "http://192.0.0.192/", "http://224.0.0.1/",
    "http://[ff02::1]/", "http://paperless.example.com:{p}/", "http://0/", "http://[::127.0.0.1]/",
    "http://[0:0:0:0:0:ffff:7f00:1]/", "http://localhost.:{p}/", "http://LOCALHOST:{p}/",
]
#: Never reached, with or without the switch: link-local, multicast, unspecified, the metadata services, also inside
#: an IPv6 address (mapped, NAT64, 6to4).
NEVER = ["169.254.169.254", "fe80::1", "fd00:ec2::254", "::ffff:169.254.169.254", "64:ff9b::a9fe:a9fe",
         "2002:a9fe:a9fe::", "100.100.100.200", "192.0.0.192", "224.0.0.1", "ff02::1", "::", "0.0.0.0",
         "64:ff9b::e000:1", "2002:e000:1::"]


@pytest.mark.parametrize("address", NEVER)
def test_never_reached_also_inside_another_address(address: str) -> None:
    assert outbound.never(outbound.ip_of(address)), address


def test_inside_an_address_names_what_it_carries() -> None:
    assert [str(ip) for ip in outbound.inner(outbound.ip_of("64:ff9b::a9fe:a9fe"))][1:] == ["169.254.169.254"]
    assert [str(ip) for ip in outbound.inner(outbound.ip_of("2002:a9fe:a9fe::"))][1:] == ["169.254.169.254"]


@pytest.mark.parametrize("form", FORMS)
def test_no_form_of_the_own_network_is_reached_without_the_switch(client: TestClient, operator: Account, fake: Any,
                                                                  form: str, monkeypatch: pytest.MonkeyPatch) -> None:
    made, server = fake
    monkeypatch.setattr(paperless, "resolver", numeric_only)
    url = form.format(p=server.server_address[1])
    put = client.put("/api/v1/settings/paperless", json={"url": url, "token": made.token, "private": False})
    if put.status_code == 200:
        answer = client.post("/api/v1/settings/paperless/check")
        assert answer.status_code in (422, 502), (url, answer.status_code)
        assert answer.json()["detail"]["code"] in ("paperless_address_private", "paperless_address_refused",
                                                   "paperless_unreachable"), url
    else:
        assert put.status_code == 422, url
    assert made.requests == [], url


@pytest.mark.parametrize("form", [f for f in FORMS if any(part in f for part in (
    "169.254", "fd00:ec2", "100.100", "192.0.0.192", "fe80", "ff02", "224.", "a9fe", "[::]", "0.0.0.0", "//0/"))])
def test_never_reached_even_with_the_switch(client: TestClient, operator: Account, fake: Any, form: str,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    made, server = fake
    monkeypatch.setattr(paperless, "resolver", numeric_only)
    url = form.format(p=server.server_address[1])
    client.put("/api/v1/settings/paperless", json={"url": url, "token": made.token, "private": True})
    answer = client.post("/api/v1/settings/paperless/check")
    assert answer.json()["detail"]["code"] in ("paperless_address_refused", "paperless_unreachable"), url
    assert made.requests == []


# --- Telling the operator what happened -------------------------------------------------------------------------------


def test_a_redirect_says_so(client: TestClient, operator: Account, fake: Any) -> None:
    made, server = fake

    def to_https(handler: Any) -> bool:
        handler.send_response(301)
        handler.send_header("Location", "https://paperless.example.com/api/documents/")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return True

    made.hook(r"^/api/", to_https)
    connect(client, made, server)
    answer = client.post("/api/v1/settings/paperless/check")
    assert answer.status_code == 502 and answer.json()["detail"]["code"] == "paperless_redirected"


def test_going_on_after_the_address_changed_asks_to_look_again(client: TestClient, operator: Account,
                                                               fake: Any) -> None:
    made, server = fake
    made.add(fake_paperless.Doc(1, "Eins", pdf("eins")))
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    client.put("/api/v1/settings/paperless", json={"url": server.url + "other/", "token": made.token})
    answer = client.post("/api/v1/settings/paperless/start", json={"resume": True})
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "paperless_address_changed"


def test_a_certificate_that_is_not_trusted_says_so() -> None:
    failure = paperless._unreachable(httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"))
    assert failure.code == "paperless_tls_failed"
    assert paperless._unreachable(httpx.ConnectError("connection refused")).code == "paperless_unreachable"


def test_looking_says_which_owners_have_no_person_of_their_name(client: TestClient, operator: Account,
                                                                fake: Any) -> None:
    from .conftest import make_account

    made, server = fake
    tom = make_account("tom")
    made.users = {1: {"username": "tom", "groups": []}, 2: {"username": "scanner", "groups": []}}
    made.add(fake_paperless.Doc(1, "A", pdf("a"), owner=1))
    made.add(fake_paperless.Doc(2, "B", pdf("b"), owner=2))
    connect(client, made, server)
    owners = {o["name"]: o for o in client.post("/api/v1/settings/paperless/check").json()["owners"]}
    assert owners["tom"]["matched"] is True and owners["tom"]["user_id"] == tom.id
    assert owners["scanner"]["matched"] is False and owners["scanner"]["user_id"] == operator.id


def test_an_empty_file_says_so(client: TestClient, operator: Account, fake: Any) -> None:
    made, server = fake
    made.add(fake_paperless.Doc(1, "Leer", b""))
    connect(client, made, server)
    client.post("/api/v1/settings/paperless/start", json={"where": "owner", "people": []})
    run_import()
    assert run_state(client)["reasons"] == {"empty_file": 1}
