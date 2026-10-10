# ruff: noqa: F811 - the fixtures of the mailbox come from test_intake_mail
"""The rests of the second look at the inputs: long headers of real threads are taken, a person's subfolder nexpaper may
only read is left alone (and said at the person), the trusted server for ``Authentication-Results`` and only its
``dmarc=fail``, the mail worker within its time and memory, the folder probed at most once a minute."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.db import SessionLocal
from app.models import Account
from app.services import intake_folder, intake_mail, settings_service

from . import imap_server
from .conftest import make_account
from .files import make_pdf
from .test_intake_folder import Clock, docs, settle
from .test_intake_mail import (  # noqa: F401 - fixtures
    PDF,
    certificate,
    deliver,
    mail,
    mailbox,
    server,
    store,
    trusted,
)


def owner_names() -> list[str]:
    with SessionLocal() as db:
        names = {row.id: row.name for row in db.query(Account)}
    return [names.get(d.owner_id, "") for d in docs()]


# --- R1 ----------------------------------------------------------------------------------------------------------------


def test_a_long_thread_of_replies_is_taken(mailbox: imap_server.Store, operator: Account) -> None:
    message = mail(sender="a@example.org", files=[PDF])
    message["References"] = " ".join(f"<reply-{n:04}.thread@mail.example.com>" for n in range(300))
    raw = message.as_bytes()
    assert len(str(message["References"])) > 10_000 and intake_mail.too_elaborate(raw) is False
    deliver(mailbox, raw)
    done = intake_mail.fetch()
    assert done.skipped == 0 and done.files == 1


def test_address_and_mime_headers_keep_8_kb_others_64_kb() -> None:
    base = "From: a@example.org\r\nTo: paper@example.com\r\nSubject: s\r\n"
    assert intake_mail.too_elaborate((base + "Cc: " + "x" * 9000 + "\r\n\r\nx").encode()) is True
    assert intake_mail.too_elaborate((base + "Content-Type: text/plain; a=" + "x" * 9000 + "\r\n\r\nx").encode()) is True
    assert intake_mail.too_elaborate((base + "X-Long: " + "x" * 30_000 + "\r\n\r\nx").encode()) is False
    assert intake_mail.too_elaborate((base + "X-Long: " + "x" * 70_000 + "\r\n\r\nx").encode()) is True


# --- R2 ----------------------------------------------------------------------------------------------------------------


@pytest.fixture
def ticks(monkeypatch: pytest.MonkeyPatch) -> Iterator[Clock]:
    made = Clock()
    monkeypatch.setattr(clock, "monotonic", made)
    intake_folder.forget()
    yield made
    intake_folder.forget()


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    root = tmp_path / "eingang"
    root.mkdir()
    with SessionLocal() as db:
        settings_service.save(db, {"folder_on": True, "folder_path": str(root)})
    return root


def test_a_subfolder_nexpaper_may_only_read_is_left_alone_and_said_at_the_person(
        client: TestClient, operator: Account, ticks: Clock, folder: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    make_account("jule")
    make_account("tom")
    intake_folder.scan()
    (folder / "jule" / "a.pdf").write_bytes(make_pdf(["jule"]))
    (folder / "tom" / "b.pdf").write_bytes(make_pdf(["tom"]))
    real = intake_folder.os.open

    def jule_read_only(path: Any, flags: int, *args: Any) -> int:
        if flags & intake_folder.os.O_CREAT and Path(path).parent == folder / "jule":
            raise PermissionError(13, "Permission denied")
        return real(path, flags, *args)

    monkeypatch.setattr(intake_folder.os, "open", jule_read_only)
    intake_folder.forget()
    for _ in range(3):
        found = settle(ticks)
        if found.taken:
            assert found.taken == {"tom": 1}
    assert owner_names() == ["tom"] and (folder / "jule" / "a.pdf").exists()
    assert caplog.text.count("a subfolder cannot be used reason=folder_readonly") == 1
    people = {p["name"]: p["problem"] for p in client.get("/api/v1/settings/intake").json()["folder"]["people"]}
    assert people == {"jule": "folder_readonly", "tester": "", "tom": ""}


def test_the_folder_is_probed_at_most_once_a_minute_by_the_settings(client: TestClient, operator: Account,
                                                                     ticks: Clock, folder: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    probes: list[str] = []
    real = intake_folder.os.open

    def counting(path: Any, flags: int, *args: Any) -> int:
        if flags & intake_folder.os.O_CREAT and ".nexpaper-probe-" in str(path):
            probes.append(str(path))
        return real(path, flags, *args)

    monkeypatch.setattr(intake_folder.os, "open", counting)
    for _ in range(5):
        client.get("/api/v1/settings/intake")
        client.get("/api/v1/me/intake")
    assert len(probes) <= 2, probes
    ticks.wait(intake_folder.WRITABLE_SECONDS + 1)
    client.get("/api/v1/settings/intake")
    before = len(probes)
    client.put("/api/v1/settings/intake", json={"folder_on": True})
    assert len(probes) > before, "saving looks again at once"


# --- R3 ----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("trusted_name", "results", "owner"), [
    ("", "mx.google.com; dmarc=fail header.from=example.org", "jule"),
    ("mx.google.com", "mx.google.com; dmarc=fail header.from=example.org", "tester"),
    ("mx.google.com", "mx.google.com; spf=fail smtp.mailfrom=example.org; dmarc=pass", "jule"),
    ("mx.google.com", "example.com; dmarc=fail", "jule"),
    ("google.com", "mx.google.com; dmarc=fail", "tester"),
])
def test_the_trusted_server_and_only_its_dmarc_verdict_count(mailbox: imap_server.Store, operator: Account,
                                                             client: TestClient, trusted_name: str, results: str,
                                                             owner: str) -> None:
    make_account("jule")
    answer = client.put("/api/v1/settings/intake", json={"mail_auth_server": trusted_name})
    assert answer.status_code == 200 and answer.json()["mail"]["auth_server"] == trusted_name
    message = mail(sender="x@example.org", to="paper+jule@example.com", files=[PDF])
    message["Authentication-Results"] = results
    deliver(mailbox, message)
    intake_mail.fetch()
    assert owner_names() == [owner]


def test_the_trusted_server_is_a_name(client: TestClient, operator: Account) -> None:
    answer = client.put("/api/v1/settings/intake", json={"mail_auth_server": "mx.google.com; dmarc=pass"})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "mail_host_invalid"


# --- R4 and the worker -------------------------------------------------------------------------------------------------


def test_the_worker_is_gone_after_its_time(mailbox: imap_server.Store, operator: Account, tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    stand_in = tmp_path / "slow_worker.py"
    stand_in.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(intake_mail, "WORKER", stand_in)
    monkeypatch.setattr(intake_mail, "WORKER_SECONDS", 1)
    started: list[subprocess.Popen[bytes]] = []
    real = subprocess.Popen

    def keep(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        made = real(*args, **kwargs)
        if str(stand_in) in " ".join(str(one) for one in (args[0] if args else kwargs.get("args", []))):
            started.append(made)
        return made

    monkeypatch.setattr(intake_mail.subprocess, "Popen", keep)
    deliver(mailbox, mail(sender="a@example.org", files=[PDF]))
    begun = time.monotonic()
    done = intake_mail.fetch()
    assert done.skipped == 1 and time.monotonic() - begun < 8
    [process] = started
    assert process.poll() is not None, "killed, not left running"


def test_the_worker_has_little_time_and_a_low_priority() -> None:
    assert intake_mail.WORKER_SECONDS <= 20
    source = Path(intake_mail.WORKER).read_text(encoding="utf-8")
    assert "os.nice(19)" in source and "RLIMIT_CPU" in source


@pytest.mark.skipif(sys.platform == "win32", reason="a memory limit for a process needs setrlimit (Linux, CI, WSL)")
def test_a_mail_that_needs_more_memory_than_allowed_is_too_elaborate(mailbox: imap_server.Store, operator: Account,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    deliver(mailbox, mail(sender="a@example.org", files=[("gross.pdf", make_pdf() + b"0" * (20 * 1024 * 1024),
                                                          "application/pdf")]))
    monkeypatch.setattr(intake_mail, "WORKER_MEMORY_MB", 60)
    done = intake_mail.fetch()
    assert done.skipped == 1 and docs() == []
