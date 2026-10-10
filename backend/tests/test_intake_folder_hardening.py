"""The intake folder against what a share, a scanner or somebody with a shell on it can do: a new file under the same name
while one is taken, a folder nexpaper may only read, hard links, a folder or a file swapped for a link after the look,
accounts whose names make odd folders, many files of one person, and places that are never an intake folder."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.config import PROJECT_DIR
from app.db import SessionLocal
from app.models import Account
from app.services import intake, intake_folder, settings_service

from .conftest import make_account, new_client
from .files import make_pdf
from .test_intake_folder import Clock, _junction, docs, items, settle


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


# --- M4 ------------------------------------------------------------------------------------------------------------------


def test_a_new_file_under_the_same_name_while_one_is_taken_stays(operator: Account, ticks: Clock, folder: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    make_account("jule")
    intake_folder.scan()
    target = folder / "jule" / "scan.pdf"
    target.write_bytes(make_pdf(["erster Scan"]))
    real = intake.take

    def scanner_writes_again(*args: Any, **kwargs: Any) -> Any:
        made = real(*args, **kwargs)
        target.write_bytes(make_pdf(["zweiter Scan, ein wenig laenger"]))
        return made

    monkeypatch.setattr(intake, "take", scanner_writes_again)
    assert settle(ticks).taken == {"jule": 1}
    assert target.exists(), "the second scan is not removed with the first"
    monkeypatch.setattr(intake, "take", real)
    assert settle(ticks).taken == {"jule": 1}
    assert len(docs()) == 2 and not target.exists()
    assert [item.state for item in items()] == ["done", "done"]


def test_a_folder_nexpaper_may_only_read_is_not_taken_from_and_said_once(
        client: TestClient, operator: Account, ticks: Clock, folder: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    make_account("jule")
    intake_folder.scan()
    (folder / "jule" / "a.pdf").write_bytes(make_pdf())
    real = os.open

    def read_only(path: Any, flags: int, *args: Any) -> int:
        if flags & os.O_CREAT and Path(path).parent == folder:
            raise PermissionError(13, "Permission denied")
        return real(path, flags, *args)

    monkeypatch.setattr(intake_folder.os, "open", read_only)
    intake_folder.forget()
    for _ in range(4):
        settle(ticks)
    assert docs() == [] and (folder / "jule" / "a.pdf").exists()
    assert caplog.text.count("reason=folder_readonly") == 1
    body = client.get("/api/v1/settings/intake").json()["folder"]
    assert body["problem"] == "folder_readonly"
    monkeypatch.setattr(intake_folder.os, "open", real)
    intake_folder.forget()
    assert settle(ticks).taken == {"jule": 1}


def test_writable_tells_a_folder_that_takes_files_from_one_that_does_not(tmp_path: Path) -> None:
    intake_folder.forget()
    assert intake_folder.writable(tmp_path, fresh=True) is True
    assert list(tmp_path.iterdir()) == [], "the probe leaves nothing"
    assert intake_folder.writable(tmp_path / "gibt-es-nicht", fresh=True) is False


def test_a_subfolder_that_cannot_be_made_is_said_once(operator: Account, ticks: Clock, folder: Path,
                                                      caplog: pytest.LogCaptureFixture) -> None:
    make_account("jule")
    (folder / "jule").write_bytes(b"a file where the folder should be")
    for _ in range(5):
        intake_folder.scan()
    assert caplog.text.count("a subfolder could not be made") == 1


# --- N1, N2 --------------------------------------------------------------------------------------------------------------


def test_every_account_has_its_folder_under_its_name_and_the_card_says_the_same(client: TestClient, operator: Account,
                                                                                ticks: Clock, folder: Path) -> None:
    for name in ("ab..cd", "lea.berger", "abgelehnt"):
        make_account(name)
    intake_folder.scan()
    assert (folder / "ab..cd").is_dir() and (folder / "lea.berger").is_dir()
    assert not (folder / "abgelehnt").exists()
    shown = {p["name"]: p["path"] for p in client.get("/api/v1/settings/intake").json()["folder"]["people"]}
    assert "abgelehnt" not in shown and shown["ab..cd"].endswith("/ab..cd/")
    for name in shown:
        assert (folder / name).is_dir(), name
    with SessionLocal() as db:
        odd = db.query(Account).filter_by(name="abgelehnt").one()
        db.expunge(odd)
    with new_client(odd) as person:
        assert person.get("/api/v1/me/intake").json()["folder"] == "", "no path that does not exist"
    (folder / "ab..cd" / "x.pdf").write_bytes(make_pdf())
    assert settle(ticks).taken == {"ab..cd": 1}


def test_a_hard_link_is_set_aside(operator: Account, ticks: Clock, folder: Path, tmp_path: Path) -> None:
    make_account("jule")
    intake_folder.scan()
    outside = tmp_path / "anderswo.pdf"
    outside.write_bytes(make_pdf(["anderswo"]))
    os.link(outside, folder / "jule" / "link.pdf")
    found = settle(ticks)
    assert found.taken == {} and found.rejected == 1 and docs() == []
    aside = folder / "jule" / intake_folder.REJECTED
    assert "hard link" in (aside / "link.pdf.grund.txt").read_text(encoding="utf-8")
    assert outside.read_bytes() == make_pdf(["anderswo"])


# --- N5: swapped after the look ------------------------------------------------------------------------------------------


def test_a_folder_swapped_for_a_link_after_the_look_is_not_read_through(operator: Account, ticks: Clock, folder: Path,
                                                                        tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    make_account("jule")
    intake_folder.scan()
    mine = folder / "jule" / "scan.pdf"
    mine.write_bytes(make_pdf(["meins"]))
    outside = tmp_path / "draussen"
    outside.mkdir()
    real = intake_folder._settle_taken

    def swap(item: Any) -> bool:
        # Between the look and the open, the person's folder becomes a way out, with a file of the same size and time.
        shutil.copy2(mine, outside / "scan.pdf")
        shutil.rmtree(folder / "jule")
        _junction(folder / "jule", outside)
        return real(item)

    monkeypatch.setattr(intake_folder, "_settle_taken", swap)
    found = settle(ticks)
    assert found.taken == {} and docs() == []
    assert (outside / "scan.pdf").exists(), "nothing outside is taken or moved"


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links to files need developer mode on Windows; CI and WSL")
def test_a_file_swapped_for_a_link_is_not_opened_even_when_the_second_look_is_fooled(
        folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "geheim.pdf"
    secret.write_bytes(make_pdf(["geheim"]))
    (folder / "jule").mkdir()
    link = folder / "jule" / "scan.pdf"
    os.symlink(secret, link)
    info = os.stat(secret)
    # The link is swapped back to a plain file between the open and the second look: that look sees no link.
    monkeypatch.setattr(intake_folder.os, "lstat", os.stat)
    assert intake_folder._open(link, folder, info.st_size, info.st_mtime_ns) is None


# --- N4 ------------------------------------------------------------------------------------------------------------------


def test_one_person_with_many_files_does_not_hide_the_others(operator: Account, ticks: Clock, folder: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intake_folder, "MAX_ENTRIES", 10)
    monkeypatch.setattr(intake_folder, "PER_FOLDER_ENTRIES", 3)
    make_account("aaron")
    make_account("tom")
    intake_folder.scan()
    for number in range(12):
        (folder / "aaron" / f"a{number:02}.pdf").write_bytes(make_pdf([str(number)]))
    (folder / "tom" / "t.pdf").write_bytes(make_pdf(["tom"]))
    first = settle(ticks)
    assert first.taken.get("tom") == 1


def test_places_that_are_never_an_intake_folder(tmp_path: Path) -> None:
    with pytest.raises(intake_folder.FolderProblem):
        intake_folder.check_root(str(tmp_path / "a" / ".." / ".." / "x"))
    if os.name == "nt":
        assert intake_folder.forbidden(Path(os.environ["SystemRoot"])) is True
        assert intake_folder.forbidden(Path(os.environ["SystemRoot"]) / "Temp") is True
    else:
        assert intake_folder.forbidden(Path("/usr/share")) is True
    assert intake_folder.forbidden(PROJECT_DIR / "frontend") is True


def test_the_container_does_not_change_the_owners_inside_a_mounted_intake_folder() -> None:
    entrypoint = (PROJECT_DIR / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert not any(line.strip().startswith("chown -R") for line in entrypoint.splitlines())
    # The mount points below /data are read from the kernel and left out (a folder of the same disk too).
    assert "/proc/self/mountinfo" in entrypoint and '-path "$mounted" -prune' in entrypoint
    assert 'find /data "$@" -exec chown -h' in entrypoint
