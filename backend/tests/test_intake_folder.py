"""The intake folder: a subfolder per person, a file is taken only after 10 quiet seconds, then removed; what is not taken
waits in ``abgelehnt/`` with its reason; links and junctions are not followed; nothing is taken twice after a restart;
many files are taken in turns; what nobody can be told from goes to the operator, marked."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clock
from app.config import PROJECT_DIR, get_settings
from app.db import SessionLocal
from app.models import Account, Document, IntakeItem
from app.services import intake, intake_folder, settings_service

from .conftest import make_account
from .files import EXE, make_pdf
from .intake import limit
from .papers import own_vault, shared_vault


class Clock:
    def __init__(self) -> None:
        self.at = 1000.0

    def __call__(self) -> float:
        return self.at

    def wait(self, seconds: float) -> None:
        self.at += seconds


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


def docs() -> list[Document]:
    with SessionLocal() as db:
        found = list(db.scalars(select(Document).order_by(Document.id)))
        for row in found:
            db.expunge(row)
        return found


def items() -> list[IntakeItem]:
    with SessionLocal() as db:
        found = list(db.scalars(select(IntakeItem).order_by(IntakeItem.id)))
        for row in found:
            db.expunge(row)
        return found


def settle(ticks: Clock) -> intake_folder.Round:
    """Two rounds 10 seconds apart: a file that lay still is taken in the second."""
    intake_folder.scan()
    ticks.wait(intake_folder.QUIET_SECONDS)
    return intake_folder.scan()


def test_a_file_is_taken_after_ten_quiet_seconds_and_removed(operator: Account, ticks: Clock, folder: Path) -> None:
    jule = make_account("jule")
    intake_folder.scan()
    assert (folder / "jule").is_dir() and (folder / "tester").is_dir(), "a subfolder for every person"
    pdf = make_pdf()
    (folder / "jule" / "Rechnung Strom.pdf").write_bytes(pdf)
    assert intake_folder.scan().taken == {}
    ticks.wait(9.9)
    assert intake_folder.scan().taken == {}, "not before 10 quiet seconds"
    assert docs() == []
    ticks.wait(0.2)
    assert intake_folder.scan().taken == {"jule": 1}
    [document] = docs()
    assert document.owner_id == jule.id and document.vault_id == own_vault(jule)
    assert document.source == "folder" and document.status == "processing" and document.title == "Rechnung Strom"
    assert not (folder / "jule" / "Rechnung Strom.pdf").exists(), "removed once taken"
    [item] = items()
    assert item.state == "done" and item.document_id == document.id and item.unknown is False
    assert item.detail == {"folder": "jule", "file": "Rechnung Strom.pdf"}


def test_a_name_of_nothing_but_direction_characters_gives_the_title_document(operator: Account, ticks: Clock,
                                                                             folder: Path) -> None:
    intake_folder.scan()
    (folder / "tester" / f"{chr(0x202E)}{chr(0x2066)}.pdf").write_bytes(make_pdf())
    (folder / "tester" / f"Strom {chr(0x202E)}fdp.exe.pdf").write_bytes(make_pdf(["anders"]))
    settle(ticks)
    assert sorted(d.title for d in docs()) == ["Document", "Strom fdp.exe"]


def test_a_file_goes_to_the_vault_the_person_chose(operator: Account, ticks: Clock, folder: Path) -> None:
    jule = make_account("jule")
    household = shared_vault("Haushalt", operator, (jule, "edit"))
    with SessionLocal() as db:
        row = db.get(Account, jule.id)
        assert row is not None
        row.profile = {"default_vault": household}
        db.commit()
    intake_folder.scan()
    (folder / "jule" / "a.pdf").write_bytes(make_pdf())
    settle(ticks)
    [document] = docs()
    assert document.vault_id == household


def test_a_growing_file_waits_until_it_lies_still(operator: Account, ticks: Clock, folder: Path) -> None:
    make_account("jule")
    intake_folder.scan()
    target = folder / "jule" / "scan.pdf"
    whole = make_pdf(["eins", "zwei", "drei"])
    target.write_bytes(whole[:200])
    intake_folder.scan()
    ticks.wait(8)
    with target.open("ab") as handle:
        handle.write(whole[200:])
    assert intake_folder.scan().taken == {}
    ticks.wait(9)
    assert intake_folder.scan().taken == {}, "the quiet starts again with each change"
    ticks.wait(1.5)
    assert intake_folder.scan().taken == {"jule": 1}
    [item] = items()
    assert item.size == len(whole)


def test_what_is_not_taken_waits_in_abgelehnt_with_its_reason(operator: Account, ticks: Clock, folder: Path) -> None:
    make_account("jule")
    limit(upload_max_mb=1)
    intake_folder.scan()
    person = folder / "jule"
    (person / "brief.docx").write_bytes(b"PK\x03\x04" + b"\x00" * 100)
    (person / "programm.exe").write_bytes(EXE)
    (person / "leer.pdf").write_bytes(b"")
    (person / "riesig.pdf").write_bytes(b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10))
    found = settle(ticks)
    assert found.rejected == 4 and docs() == []
    aside = person / intake_folder.REJECTED
    names = sorted(path.name for path in aside.iterdir())
    assert names == sorted(["brief.docx", "brief.docx.grund.txt", "programm.exe", "programm.exe.grund.txt",
                            "leer.pdf", "leer.pdf.grund.txt", "riesig.pdf", "riesig.pdf.grund.txt"])
    assert (aside / "brief.docx").read_bytes().startswith(b"PK"), "set aside, not deleted"
    assert "not taken" in (aside / "riesig.pdf.grund.txt").read_text(encoding="utf-8").lower()
    assert "larger than the limit" in (aside / "riesig.pdf.grund.txt").read_text(encoding="utf-8")
    assert "empty" in (aside / "leer.pdf.grund.txt").read_text(encoding="utf-8")
    # The folder of what was set aside is not looked into again, and a second file of the same name does not overwrite.
    (person / "brief.docx").write_bytes(b"PK\x03\x04" + b"\x01" * 100)
    settle(ticks)
    assert (aside / "brief (2).docx").exists() and (aside / "brief.docx").read_bytes()[4:5] == b"\x00"
    assert docs() == []


def test_hidden_and_temporary_files_are_left_alone(operator: Account, ticks: Clock, folder: Path) -> None:
    make_account("jule")
    intake_folder.scan()
    person = folder / "jule"
    names = [".~lock.rechnung.pdf#", "~$brief.docx", "scan.pdf.part", "upload.tmp", ".versteckt.pdf", "Thumbs.db",
             "x.crdownload"]
    for name in names:
        (person / name).write_bytes(make_pdf())
    (folder / "@eaDir").mkdir()
    (folder / "@eaDir" / "a.pdf").write_bytes(make_pdf())
    (folder / "#recycle").mkdir()
    (folder / "#recycle" / "b.pdf").write_bytes(make_pdf())
    found = settle(ticks)
    assert found.taken == {} and found.rejected == 0 and docs() == []
    assert sorted(path.name for path in person.iterdir()) == sorted(names)
    assert not (person / intake_folder.REJECTED).exists()


def test_a_foreign_subfolder_and_the_folder_itself_go_to_the_operator_marked(operator: Account, ticks: Clock,
                                                                            folder: Path) -> None:
    make_account("jule")
    intake_folder.scan()
    (folder / "drucker").mkdir()
    (folder / "drucker" / "scan.pdf").write_bytes(make_pdf(["eins"]))
    (folder / "lose.pdf").write_bytes(make_pdf(["zwei"]))
    (folder / "jule" / "unter").mkdir()
    (folder / "jule" / "unter" / "tief.pdf").write_bytes(make_pdf(["drei"]))
    found = settle(ticks)
    assert found.taken == {"tester": 2, "jule": 1}
    by_key = {item.key: item for item in items()}
    assert by_key["drucker/scan.pdf"].unknown is True and by_key["drucker/scan.pdf"].detail["folder"] == "drucker"
    assert by_key["lose.pdf"].unknown is True and by_key["lose.pdf"].detail["folder"] == ""
    assert by_key["jule/unter/tief.pdf"].unknown is False
    owners = {d.title: d.owner_id for d in docs()}
    assert owners["scan"] == operator.id and owners["lose"] == operator.id
    assert not (folder / "drucker" / "scan.pdf").exists() and (folder / "drucker").is_dir()


def test_a_blocked_persons_files_wait(operator: Account, ticks: Clock, folder: Path) -> None:
    make_account("tom")
    intake_folder.scan()
    with SessionLocal() as db:
        row = db.scalar(select(Account).where(Account.name == "tom"))
        assert row is not None
        row.blocked_at = clock.now()
        db.commit()
    (folder / "tom" / "a.pdf").write_bytes(make_pdf())
    assert settle(ticks).taken == {}
    assert (folder / "tom" / "a.pdf").exists() and docs() == []


def test_nothing_is_taken_while_the_folder_is_switched_off(operator: Account, ticks: Clock, folder: Path) -> None:
    make_account("jule")
    intake_folder.scan()
    (folder / "jule" / "a.pdf").write_bytes(make_pdf())
    with SessionLocal() as db:
        settings_service.save(db, {"folder_on": False})
    assert settle(ticks).taken == {}
    assert (folder / "jule" / "a.pdf").exists() and docs() == []


def _junction(link: Path, target: Path) -> None:
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_links_and_junctions_are_not_followed(operator: Account, ticks: Clock, folder: Path, tmp_path: Path) -> None:
    make_account("jule")
    make_account("tom")
    outside = tmp_path / "draussen"
    outside.mkdir()
    secret = outside / "geheim.pdf"
    secret.write_bytes(make_pdf(["draussen"]))
    (outside / "brief.docx").write_bytes(b"PK" + b"0" * 40)
    _junction(folder / "querweg", outside)
    # A person's folder that is a junction is not made into one and not looked into.
    _junction(folder / "tom", outside)
    intake_folder.scan()
    (folder / "jule").mkdir(exist_ok=True)
    _junction(folder / "jule" / "weiter", outside)
    found = settle(ticks)
    assert found.taken == {} and found.rejected == 0 and docs() == []
    assert secret.exists() and sorted(p.name for p in outside.iterdir()) == ["brief.docx", "geheim.pdf"]


def test_a_linked_file_is_not_taken(operator: Account, ticks: Clock, folder: Path, tmp_path: Path) -> None:
    make_account("jule")
    intake_folder.scan()
    outside = tmp_path / "draussen.pdf"
    outside.write_bytes(make_pdf())
    try:
        os.symlink(outside, folder / "jule" / "link.pdf")
    except OSError:
        # Windows makes symbolic links only with developer mode or as administrator; CI runs this on Linux.
        pytest.skip("this system makes no symbolic links for this user")
    found = settle(ticks)
    assert found.taken == {} and docs() == []
    assert outside.exists()


def test_names_that_try_to_leave_the_folder_stay_inside(operator: Account, ticks: Clock, folder: Path) -> None:
    make_account("jule")
    intake_folder.scan()
    person = folder / "jule"
    odd = "a..\u202egpj..docx"
    (person / odd).write_bytes(b"PK\x03\x04" + b"\x00" * 40)
    long_name = "x" * 150 + ".docx"
    (person / long_name).write_bytes(b"PK\x03\x04" + b"\x00" * 40)
    (person / "Strom  M\u00e4rz.pdf").write_bytes(make_pdf())
    found = settle(ticks)
    assert found.rejected == 2 and found.taken == {"jule": 1}
    aside = person / intake_folder.REJECTED
    names = sorted(path.name for path in aside.iterdir())
    for name in names:
        assert "\u202e" not in name and ".." not in name and len(name) <= 130, name
    assert ("x" * 100 + ".docx") in names and ("x" * 100 + ".docx.grund.txt") in names
    assert sorted(p.name for p in folder.iterdir()) == ["jule", "tester"], "nothing landed beside the folders"
    [document] = docs()
    assert document.title == "Strom M\u00e4rz", document.title


def test_many_files_are_taken_in_turns(operator: Account, ticks: Clock, folder: Path) -> None:
    make_account("jule")
    make_account("tom")
    intake_folder.scan()
    for number in range(20):
        (folder / "jule" / f"j{number:02}.pdf").write_bytes(make_pdf([f"jule {number}"]))
    for number in range(3):
        (folder / "tom" / f"t{number}.pdf").write_bytes(make_pdf([f"tom {number}"]))
    first = settle(ticks)
    assert first.taken == {"jule": intake_folder.PER_PERSON, "tom": 3}, "tom does not wait for all of jule's"
    second = intake_folder.scan()
    third = intake_folder.scan()
    assert second.taken.get("jule", 0) + third.taken.get("jule", 0) == 20 - intake_folder.PER_PERSON
    assert len(docs()) == 23 and len(list((folder / "jule").iterdir())) == 0


def test_a_restart_between_taking_and_removing_takes_nothing_twice(operator: Account, ticks: Clock, folder: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    make_account("jule")
    intake_folder.scan()
    target = folder / "jule" / "a.pdf"
    target.write_bytes(make_pdf())
    monkeypatch.setattr(intake_folder, "_remove", lambda path, read=None: "failed")
    assert settle(ticks).taken == {"jule": 1}
    assert target.exists()
    [item] = items()
    assert item.state == "taken"
    # A restart: memory is gone, the file is found again, still lying still.
    monkeypatch.undo()
    monkeypatch.setattr(clock, "monotonic", ticks)
    intake_folder.forget()
    assert settle(ticks).taken == {}
    assert len(docs()) == 1 and not target.exists()
    [item] = items()
    assert item.state == "done"


def test_a_failure_before_the_document_was_written_takes_the_file_next_time(operator: Account, ticks: Clock,
                                                                             folder: Path,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    make_account("jule")
    intake_folder.scan()
    target = folder / "jule" / "a.pdf"
    target.write_bytes(make_pdf())

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the disk went away")

    original = intake.take
    monkeypatch.setattr(intake, "take", broken)
    assert settle(ticks).taken == {}
    assert target.exists() and docs() == [] and items() == []
    monkeypatch.setattr(intake, "take", original)
    assert settle(ticks).taken == {"jule": 1}
    assert len(docs()) == 1 and not target.exists()


# --- The setting -------------------------------------------------------------------------------------------------------


def put(client: TestClient, **values: Any) -> Any:
    return client.put("/api/v1/settings/intake", json=values)


def test_the_folder_must_not_be_a_place_whose_files_matter(client: TestClient, operator: Account,
                                                             tmp_path: Path) -> None:
    data = get_settings().data_dir
    for path in (str(data), str(data.parent), str(data / "dokumente"), str(data / "backups"), str(PROJECT_DIR),
                 str(PROJECT_DIR / "backend"), str(Path(PROJECT_DIR.anchor))):
        answer = put(client, folder_path=path, folder_on=True)
        assert answer.status_code == 422 and answer.json()["detail"]["code"] == "folder_forbidden", (path, answer.text)
    if os.name != "nt":
        for path in ("/etc", "/usr/lib", "/proc/self"):
            answer = put(client, folder_path=path, folder_on=True)
            assert answer.json()["detail"]["code"] == "folder_forbidden", path
    answer = put(client, folder_path="relativ/eingang", folder_on=True)
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "folder_invalid"
    answer = put(client, folder_path=str(tmp_path / "gibt-es-nicht"), folder_on=True)
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == "folder_missing"
    with SessionLocal() as db:
        assert settings_service.get(db, "folder_on") is False, "nothing was saved"


def test_the_default_folder_is_made_with_a_subfolder_per_person(client: TestClient, operator: Account) -> None:
    make_account("jule")
    answer = put(client, folder_on=True)
    assert answer.status_code == 200, answer.text
    body = answer.json()["folder"]
    used = Path(body["used"])
    assert used == get_settings().data_dir / "eingang" and body["problem"] == ""
    assert (used / "jule").is_dir() and (used / "tester").is_dir()
    assert [p["name"] for p in body["people"]] == ["jule", "tester"]
    assert body["people"][0]["path"].endswith("/jule/") and body["operator"] == "tester"


def test_a_member_sees_their_own_subfolder(client: TestClient, operator: Account, folder: Path) -> None:
    from .conftest import new_client

    jule = make_account("jule")
    with new_client(jule) as member:
        body = member.get("/api/v1/me/intake").json()
        assert body["folder_on"] is True and body["folder"] == f"{folder}/jule/"
        assert member.get("/api/v1/settings/intake").status_code == 403
        assert member.put("/api/v1/settings/intake", json={"folder_on": False}).status_code == 403


def test_a_junction_counts_as_a_link(tmp_path: Path) -> None:
    target = tmp_path / "ziel"
    target.mkdir()
    _junction(tmp_path / "weg", target)
    (tmp_path / "echt").mkdir()
    found = {entry.name: intake_folder._is_link(entry) for entry in os.scandir(tmp_path)}
    assert found == {"ziel": False, "weg": True, "echt": False}


def test_a_folder_above_the_data_folder_is_forbidden_wherever_it_lies(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "oben" / "daten")
    (tmp_path / "oben" / "daten").mkdir(parents=True)
    (tmp_path / "daneben").mkdir()
    assert intake_folder.forbidden(tmp_path / "oben") is True
    assert intake_folder.forbidden(tmp_path / "oben" / "daten") is True
    assert intake_folder.forbidden(tmp_path / "oben" / "daten" / "eingang") is False
    assert intake_folder.forbidden(tmp_path / "daneben") is False


def test_in_the_image_a_mounted_folder_beside_the_program_can_be_the_intake_folder(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The image keeps the code in /app/app and the interface in /app/static: the project's folder is the root of the
    # disk there. Taken as the program, it forbade every folder but /data/eingang (issue #1).
    from app import config

    image = tmp_path / "app"
    (image / "app").mkdir(parents=True)
    (image / "static").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "scans").mkdir()
    monkeypatch.setattr(config, "BACKEND_DIR", image)
    monkeypatch.setattr(config, "PROJECT_DIR", Path(tmp_path.anchor))
    monkeypatch.setattr(get_settings(), "frontend_dist", image / "static")
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "data")
    assert intake_folder.forbidden(tmp_path / "scans") is False
    assert intake_folder.usable_root(str(tmp_path / "scans")) == tmp_path / "scans"
    for place in (image, image / "app", image / "static", image / "static" / "assets", tmp_path):
        assert intake_folder.forbidden(place) is True, place
    assert intake_folder.forbidden(tmp_path / "data" / "eingang") is False


def test_a_file_written_to_while_it_is_read_waits_for_another_quiet_spell(operator: Account, ticks: Clock,
                                                                          folder: Path,
                                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    make_account("jule")
    intake_folder.scan()
    target = folder / "jule" / "scan.pdf"
    whole = make_pdf(["eins", "zwei"])
    target.write_bytes(whole[:300])
    original = intake_folder._copy
    calls = []

    def scanner_still_writing(handle: int, max_file: int) -> Any:
        found = original(handle, max_file)
        if not calls:
            with target.open("ab") as more:
                more.write(whole[300:])
            os.utime(target, ns=(target.stat().st_atime_ns, target.stat().st_mtime_ns + 1_000_000))
        calls.append(1)
        return found

    monkeypatch.setattr(intake_folder, "_copy", scanner_still_writing)
    assert settle(ticks).taken == {}, "what was read is thrown away"
    assert docs() == [] and target.exists()
    assert settle(ticks).taken == {"jule": 1}
    [item] = items()
    assert item.size == len(whole)
