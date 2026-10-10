"""The page tools under pressure: the rename job in between, a worker that dies, an uploaded version that cannot be
finished, the limits of a person, what a page could do by itself, files a killed worker leaves behind, documents read
before the blank pages were looked for, and the order the worker serves people in."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pikepdf
import pytest
from fastapi.testclient import TestClient
from pikepdf import Array, Dictionary, Name, String
from sqlalchemy import select

from app import clock, worker
from app.db import SessionLocal
from app.models import Job, Version, VersionInfo
from app.services import brakes, jobs, pagetools, processing, separators, settings_service, storage

from . import scans
from .conftest import DATA_DIR, make_account, new_client
from .intake import disk_files, process_all, sha, upload_and_read
from .test_pagetools import edit, file_of, leftovers, made, pdf, upload_version, versions


def integrity() -> list[tuple[int, int, bool]]:
    """Every version: its file is there and has the checksum the version names."""
    with SessionLocal() as db:
        return [(v.document_id, v.n, file_of(v.original_path).is_file()
                 and sha(file_of(v.original_path).read_bytes()) == v.sha256)
                for v in db.scalars(select(Version).order_by(Version.document_id, Version.n))]


# --- The rename job in between (finding 1) ---------------------------------------------------------------------------


def test_restoring_while_the_rename_job_wants_to_run_restores_the_right_file(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch) -> None:
    document = made(client, "s.pdf", "Eins", "Zwei", "Drei")["id"]
    assert edit(client, document, [(3, 0), (1, 0)]).status_code == 200  # the rename job waits now
    real = pagetools._link_or_copy
    calls: list[int] = []

    def link(source: Path, label: str) -> Path:
        if not calls:
            calls.append(1)
            process_all()  # the rename job tries to run between the check and the link
        return real(source, label)

    monkeypatch.setattr(pagetools, "_link_or_copy", link)
    answer = client.post(f"/api/v1/documents/{document}/versions/1/restore", json={"base_version": 2})
    assert answer.status_code == 200, answer.text
    process_all()
    assert all(ok for _d, _n, ok in integrity()), integrity()
    v1, _v2, v3 = versions(document)
    assert v3.sha256 == v1.sha256 and file_of(v3.original_path).read_bytes() == file_of(v1.original_path).read_bytes()


def test_editing_right_after_saving_while_the_rename_job_runs_works(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch) -> None:
    document = made(client)["id"]
    assert edit(client, document, [(2, 0), (1, 0)]).status_code == 200
    real = processing.spawn

    def spawn(request: Any, timeout: int) -> Any:
        process_all()  # the rename job of the first edit comes due while the second runs
        return real(request, timeout)

    monkeypatch.setattr(processing, "spawn", spawn)
    answer = edit(client, document, [(2, 90), (1, 0)], base=2)
    assert answer.status_code == 200, answer.text
    monkeypatch.undo()
    process_all()
    assert [v.n for v in versions(document)] == [1, 2, 3] and all(ok for _d, _n, ok in integrity())
    assert leftovers() == []


def test_joining_right_after_a_title_change_while_the_rename_job_runs_works(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = made(client, "a.pdf", "Alpha")["id"], made(client, "b.pdf", "Beta")["id"]
    client.patch(f"/api/v1/documents/{second}", json={"sender": "Stadtwerke Lindenau"})  # a rename job waits
    real = processing.spawn

    def spawn(request: Any, timeout: int) -> Any:
        process_all()
        return real(request, timeout)

    monkeypatch.setattr(processing, "spawn", spawn)
    answer = client.post(f"/api/v1/documents/{first}/merge",
                         json={"base_version": 1, "others": [{"id": second, "base_version": 1}]})
    assert answer.status_code == 200, answer.text
    monkeypatch.undo()
    process_all()
    assert all(ok for _d, _n, ok in integrity())


def test_the_rename_job_waits_for_a_tool_and_runs_afterwards(client: TestClient, operator: object) -> None:
    document = made(client)["id"]
    edit(client, document, [(2, 0), (1, 0)])
    with storage.files_of([document], 0):
        assert jobs.run_pending(kinds=(jobs.RENAME,)) == 1
        with SessionLocal() as db:
            waiting = db.scalars(select(Job).where(Job.kind == jobs.RENAME, Job.state == "queued")).all()
            assert [(j.ref, j.attempts) for j in waiting] == [(document, 0)]
    process_all()
    v1, v2 = versions(document)
    assert "(version 1)" in v1.original_path and "(version" not in v2.original_path


# --- Joining: checked again under the lock, the change feed (findings 5, M7 and M11) ------------------------------------


def test_a_source_put_in_the_trash_while_joining_runs_stops_the_join(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = made(client, "a.pdf", "Alpha"), made(client, "b.pdf", "Beta")
    real = pagetools.assemble

    def assemble(*args: Any, **kwargs: Any) -> Any:
        out = real(*args, **kwargs)
        with SessionLocal() as db:  # somebody else puts the source in the trash meanwhile
            from app.services import documents

            documents.trash(db, operator.id, second["id"])  # type: ignore[attr-defined]
        return out

    monkeypatch.setattr(pagetools, "assemble", assemble)
    answer = client.post(f"/api/v1/documents/{first['id']}/merge",
                         json={"base_version": 1, "others": [{"id": second["id"], "base_version": 1}]})
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == "in_trash"
    assert len(versions(first["id"])) == 1 and leftovers() == []


def test_the_change_feed_shows_the_sources_of_a_join_and_a_split_stack_in_the_trash(
        client: TestClient, operator: object) -> None:
    first, second = made(client, "a.pdf", "Alpha"), made(client, "b.pdf", "Beta")
    stack = made(client, "s.pdf", "Eins", "Zwei")
    since = client.get("/api/v1/changes?since=0").json()["next"]
    client.post(f"/api/v1/documents/{first['id']}/merge",
                json={"base_version": 1, "others": [{"id": second["id"], "base_version": 1}]})
    client.post(f"/api/v1/documents/{stack['id']}/split",
                json={"base_version": 1, "parts": [{"pages": [{"page": 1}]}, {"pages": [{"page": 2}]}]})
    feed = client.get(f"/api/v1/changes?since={since}").json()
    shown = {item["document"]["id"]: item["document"]["status"] for item in feed["items"] if item.get("document")}
    assert shown[second["id"]] == "trash" and shown[stack["id"]] == "trash" and shown[first["id"]] == "inbox"
    assert sum(1 for status in shown.values() if status == "inbox") == 3  # the joined one and the two parts


# --- One run per person, two for the server (M14) ----------------------------------------------------------------------


def test_one_run_at_a_time_for_a_person_and_the_others_go_on(client: TestClient, operator: object) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    with new_client(jule) as first, new_client(tom) as second:
        mine, theirs = made(first, "j.pdf"), made(second, "t.pdf")
        pagetools._busy.add(jule.id)
        try:
            answer = edit(first, mine["id"], [(2, 0), (1, 0)])
            assert answer.status_code == 503 and answer.headers["retry-after"] == "5"
            assert edit(second, theirs["id"], [(2, 0), (1, 0)]).status_code == 200
        finally:
            pagetools._busy.discard(jule.id)
        assert edit(first, mine["id"], [(2, 0), (1, 0)]).status_code == 200
        assert pagetools._busy == set()


def test_two_runs_at_a_time_for_the_server(client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pagetools, "WAIT_SECONDS", 0.2)
    document = made(client)
    assert pagetools._gate.acquire(timeout=1)
    try:
        assert edit(client, document["id"], [(2, 0), (1, 0)]).status_code == 200  # one place is still free
        assert pagetools._gate.acquire(timeout=1)
        try:
            assert edit(client, document["id"], [(1, 90), (2, 0)], base=2).status_code == 503
        finally:
            pagetools._gate.release()
    finally:
        pagetools._gate.release()


def test_a_person_may_change_pages_thirty_times_a_minute(client: TestClient, operator: object,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    document = made(client)
    moment = [1000.0]
    monkeypatch.setattr(clock, "monotonic", lambda: moment[0])
    # The number itself, not the table's: a limit raised a hundredfold must make this test fail.
    for _ in range(30):
        brakes.take("pagetools", operator.id)  # type: ignore[attr-defined]
    answer = edit(client, document["id"], [(2, 0), (1, 0)])
    assert answer.status_code == 429 and answer.json()["detail"]["code"] == "tools_too_often"
    assert int(answer.headers["retry-after"]) >= 1
    moment[0] += 61
    assert edit(client, document["id"], [(2, 0), (1, 0)]).status_code == 200


# --- A worker that dies (finding 13) ---------------------------------------------------------------------------------


def test_a_worker_that_is_killed_answers_try_again_and_leaves_nothing(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch) -> None:
    document = made(client)["id"]
    before = {p.name for p in disk_files()}
    monkeypatch.setattr(processing, "spawn", lambda request, timeout: processing.Outcome(False, error="failed",
                                                                                         retry=True))
    answer = edit(client, document, [(2, 0), (1, 0)])
    assert answer.status_code == 503 and answer.json()["detail"]["code"] == "try_again" and answer.headers["retry-after"]
    assert {p.name for p in disk_files()} == before and leftovers() == [] and len(versions(document)) == 1


def test_a_worker_killed_while_writing_leaves_only_a_name_the_start_sweeps(tmp_path: Path) -> None:
    source = tmp_path / "big.pdf"
    big = pikepdf.new()
    for _ in range(1500):
        big.add_blank_page()
    big.save(source)
    folder = Path(DATA_DIR) / storage.FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    out = storage.incoming_path("tool-")
    request = {"op": "assemble", "sources": [str(source)], "outputs": [{"out": str(out), "pages": [[0, i, 0]
                                                                                                  for i in range(1500)]}]}
    child = subprocess.Popen([sys.executable, "-I", str(processing.WORKER)], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(tmp_path))
    assert child.stdin is not None
    child.stdin.write(json.dumps(request).encode())
    child.stdin.close()
    end = time.time() + 30
    seen: list[str] = []
    while time.time() < end and child.poll() is None:
        seen = [p.name for p in folder.iterdir()]
        if seen:  # the file being written, before it is whole
            child.kill()
            break
        time.sleep(0.002)
    child.wait()
    left = [p.name for p in folder.iterdir()]
    assert seen and all(name.startswith(worker.PART) for name in seen), seen
    assert all(name.startswith(storage.INCOMING) for name in left), left
    for _ in range(50):  # Windows lets go of the file of a killed process a moment later
        storage.sweep_incoming()
        if not list(folder.iterdir()):
            break
        time.sleep(0.1)
    assert list(folder.iterdir()) == []


# --- An uploaded version that cannot be finished (finding 2) ----------------------------------------------------------


def test_an_uploaded_version_whose_job_fails_for_good_is_marked_failed_and_can_be_put_away(
        client: TestClient, operator: object, monkeypatch: pytest.MonkeyPatch) -> None:
    document = made(client)["id"]
    assert upload_version(client, document, "neu.pdf", pdf("Neu")).status_code == 202

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(pagetools, "_finish_version", boom)
    process_all(12)
    monkeypatch.undo()
    with SessionLocal() as db:
        assert [j.state for j in db.scalars(select(Job).where(Job.kind == jobs.VERSION))] == ["failed"]
        assert [i.state for i in db.scalars(select(VersionInfo).where(VersionInfo.origin == "uploaded"))] == ["failed"]
    listed = client.get(f"/api/v1/documents/{document}/versions").json()
    assert (listed[0]["n"], listed[0]["state"]) == (2, "failed")
    assert edit(client, document, [(2, 0), (1, 0)]).status_code == 200  # the tools are free again
    assert client.delete(f"/api/v1/documents/{document}/versions/3").status_code == 409  # a version that was read stays
    assert client.delete(f"/api/v1/documents/{document}/versions/1").status_code == 409  # also one that is not current
    path = file_of(versions(document)[1].original_path)
    assert client.delete(f"/api/v1/documents/{document}/versions/2").status_code == 204
    assert [v.n for v in versions(document)] == [1, 3] and not path.exists()
    assert upload_version(client, document, "neu2.pdf", pdf("Neu2")).status_code == 202


def test_a_version_marked_as_being_read_without_a_job_holds_nothing(client: TestClient, operator: object) -> None:
    """Left by a server that stopped at the wrong moment: it counts as failed and can be put away."""
    document = made(client)["id"]
    assert upload_version(client, document, "neu.pdf", pdf("Neu")).status_code == 202
    with SessionLocal() as db:
        for job in db.scalars(select(Job).where(Job.kind == jobs.VERSION)):
            job.state = "failed"
        db.commit()
    assert client.get(f"/api/v1/documents/{document}/versions").json()[0]["state"] == "failed"
    assert edit(client, document, [(2, 0), (1, 0)]).status_code == 200
    assert client.delete(f"/api/v1/documents/{document}/versions/2").status_code == 204


def test_putting_away_a_version_needs_edit_and_a_stranger_sees_nothing(client: TestClient, operator: object) -> None:
    document = made(client)["id"]
    assert upload_version(client, document, "kaputt.pdf", files_encrypted()).status_code == 202
    process_all()
    with new_client(make_account("lea")) as stranger:
        assert stranger.delete(f"/api/v1/documents/{document}/versions/2").status_code == 404
    assert len(versions(document)) == 2


def files_encrypted() -> bytes:
    from . import files

    return files.encrypted_pdf("x")


# --- What a page could do by itself (finding 8) ----------------------------------------------------------------------


def hostile_pdf(path: Path) -> None:
    pdf_ = pikepdf.new()
    for _ in range(2):
        pdf_.add_blank_page()
    page = pdf_.pages[0]
    annots = Array([
        pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.FileAttachment, Rect=Array([10, 10, 30, 30]),
                                      FS=Dictionary(Type=Name.Filespec, F=String("att.bin")))),
        pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([10, 50, 90, 70]),
                                      A=Dictionary(S=Name.JavaScript, JS=String("app.alert(1)")))),
        pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Widget, FT=Name.Tx, T=String("f1"),
                                      Rect=Array([10, 100, 90, 120]),
                                      AA=Dictionary(K=Dictionary(S=Name.JavaScript, JS=String("app.alert(2)"))),
                                      A=Dictionary(S=Name.SubmitForm, F=String("https://example.com/")))),
        pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([10, 130, 90, 150]),
                                      A=Dictionary(S=Name.URI, URI=String("https://example.com/rechnung")))),
        pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([10, 160, 90, 190]),
                                      A=Dictionary(S=Name.Launch, F=String("cmd.exe")))),
        pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([10, 200, 90, 220]),
                                      A=Dictionary(S=Name.URI, URI=String("javascript:alert(3)")))),
        pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Text, Rect=Array([10, 230, 30, 250]),
                                      Contents=String("Notiz")))])
    page.Annots = annots
    page.AA = Dictionary(O=Dictionary(S=Name.JavaScript, JS=String("app.alert(4)")))
    pdf_.Root.OpenAction = Dictionary(S=Name.JavaScript, JS=String("app.alert(5)"))
    pdf_.save(path)


def test_a_new_version_keeps_what_a_page_shows_and_drops_what_it_could_do(tmp_path: Path) -> None:
    source, out = tmp_path / "evil.pdf", tmp_path / "out.pdf"
    hostile_pdf(source)
    worker.assemble({"sources": [str(source)], "outputs": [{"out": str(out), "pages": [[0, 0, 0], [0, 1, 90]]}]})
    with pikepdf.open(out) as made_:
        page = made_.pages[0].obj
        assert "/AA" not in page and "/OpenAction" not in made_.Root
        kinds = []
        for annot in page.Annots:
            kinds.append((str(annot.Subtype), str(annot.A.S) if "/A" in annot else None, "/AA" in annot))
        assert kinds == [("/Link", None, False), ("/Widget", None, False), ("/Link", "/URI", False),
                         ("/Link", None, False), ("/Link", None, False), ("/Text", None, False)]
        names = {str(obj.get("/S")) for obj in made_.objects if isinstance(obj, Dictionary) and "/S" in obj}
        assert not names & {"/JavaScript", "/Launch", "/SubmitForm"}


def field_tree_pdf(path: Path) -> None:
    """Three pages. A form field with two parents, each with a script of its own, has a widget on page 1 and another on
    page 3; a popup on page 1 hangs on a note that is not on any page, with scripts up a chain of its own."""
    pdf_ = pikepdf.new()
    for _ in range(3):
        pdf_.add_blank_page()
    pdf_.pages[2].Contents = pdf_.make_stream(b"BT (page three) Tj ET")

    def script(text: str) -> Dictionary:
        return Dictionary(E=Dictionary(S=Name.JavaScript, JS=String(text)))

    grand = pdf_.make_indirect(Dictionary(T=String("grand"), AA=script("app.alert('grand')")))
    parent = pdf_.make_indirect(Dictionary(FT=Name.Tx, T=String("parent"), Parent=grand, AA=script("app.alert('parent')"),
                                           A=Dictionary(S=Name.JavaScript, JS=String("app.alert('parent-action')"))))
    first = pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Widget, Rect=Array([10, 10, 90, 30]),
                                          Parent=parent, P=pdf_.pages[0].obj))
    third = pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Widget, Rect=Array([10, 10, 90, 30]),
                                          Parent=parent, P=pdf_.pages[2].obj))
    parent.Kids = Array([first, third])
    grand.Kids = Array([parent])
    top = pdf_.make_indirect(Dictionary(AA=script("app.alert('top')")))
    middle = pdf_.make_indirect(Dictionary(AA=script("app.alert('middle')"), Parent=top))
    note_above = pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Text, Rect=Array([0, 0, 5, 5]),
                                               AA=script("app.alert('note')"), Parent=middle))
    popup = pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Popup, Rect=Array([0, 40, 50, 80]),
                                          Parent=note_above))
    pdf_.pages[0].Annots = Array([first, popup])
    pdf_.pages[2].Annots = Array([third])
    pdf_.save(path)


def reachable_scripts(pdf_: pikepdf.Pdf) -> tuple[list[str], list[str]]:
    """The texts of all scripts and the names of all form fields that can be reached from the catalog."""
    scripts: list[str] = []
    fields: list[str] = []
    seen: set[tuple[int, int]] = set()

    def walk(item: object, depth: int = 0) -> None:
        if depth > 60:
            return
        if isinstance(item, Dictionary | Array | pikepdf.Stream) and item.is_indirect:  # type: ignore[union-attr]
            if item.objgen in seen:  # type: ignore[union-attr]
                return
            seen.add(item.objgen)  # type: ignore[union-attr]
        if isinstance(item, Dictionary):
            for key, value in item.items():
                if key == "/JS":
                    scripts.append(str(value))
                if key == "/T":
                    fields.append(str(value))
                walk(value, depth + 1)
        elif isinstance(item, Array):
            for value in item:
                walk(value, depth + 1)

    walk(pdf_.Root)
    return scripts, fields


def test_the_scripts_of_the_fields_above_a_widget_go_and_the_field_tree_is_not_taken_along(tmp_path: Path) -> None:
    source, out = tmp_path / "fields.pdf", tmp_path / "out.pdf"
    field_tree_pdf(source)
    with pikepdf.open(source) as before:
        assert len(reachable_scripts(before)[0]) == 6, "the file as made holds the scripts"
    worker.assemble({"sources": [str(source)], "outputs": [{"out": str(out), "pages": [[0, 0, 0]]}]})
    with pikepdf.open(out) as made_:
        scripts, fields = reachable_scripts(made_)
        assert scripts == [], scripts
        assert fields == [], "the field tree (with the widget of page 3 in it) stays behind"
        kinds = [str(annot.Subtype) for annot in made_.pages[0].Annots]
        assert kinds == ["/Widget", "/Popup"], "what the page shows stays"
        assert all("/Parent" not in annot or str(annot.Subtype) == "/Popup" for annot in made_.pages[0].Annots)
        assert all("/P" not in annot for annot in made_.pages[0].Annots)


def test_a_parent_chain_that_loops_does_not_hang_the_worker(tmp_path: Path) -> None:
    source, out = tmp_path / "loop.pdf", tmp_path / "out.pdf"
    pdf_ = pikepdf.new()
    pdf_.add_blank_page()
    one = pdf_.make_indirect(Dictionary(AA=Dictionary(E=Dictionary(S=Name.JavaScript, JS=String("app.alert(1)")))))
    two = pdf_.make_indirect(Dictionary(Parent=one, A=Dictionary(S=Name.JavaScript, JS=String("app.alert(2)"))))
    one.Parent = two
    note = pdf_.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Text, Rect=Array([0, 0, 5, 5]), Parent=one))
    pdf_.pages[0].Annots = Array([note])
    pdf_.save(source)
    worker.assemble({"sources": [str(source)], "outputs": [{"out": str(out), "pages": [[0, 0, 0]]}]})
    with pikepdf.open(out) as made_:
        assert reachable_scripts(made_)[0] == []


# --- Documents read before the blank pages were looked for (finding 14) -----------------------------------------------


def test_documents_in_the_inbox_read_without_blank_marks_get_them_from_a_job(client: TestClient, operator: object) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"ocr_blank_pages": False})
    stack = [scans.LETTER, scans.Sheet(seed=31), scans.Sheet(content="letter", seed=32)]
    document = upload_and_read(client, "Stapelscan.pdf", scans.pdf_of(stack))
    assert not client.get(f"/api/v1/documents/{document['id']}/separators").json()["checked"]
    # The operator turns the switch on: the inbox is looked at.
    assert client.put("/api/v1/settings/ocr", json={"blank_pages": True}).status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(Job.ref).where(Job.kind == jobs.BLANKS, Job.state == "queued")).all() == [document["id"]]
    process_all()
    found = client.get(f"/api/v1/documents/{document['id']}/separators").json()
    assert found["checked"] and found["blank_pages"] == [2] and found["suggested"]
    assert client.get(f"/api/v1/documents/{document['id']}").json()["split_suggested"]
    # At the next start nothing is queued again: the version was looked at.
    with SessionLocal() as db:
        assert separators.queue_missing(db) == 0


def test_keep_as_one_document_holds_after_the_pages_were_edited(client: TestClient, operator: object) -> None:
    stack = [scans.LETTER, scans.Sheet(seed=31), scans.Sheet(content="letter", seed=32), scans.LETTER]
    document = upload_and_read(client, "Stapelscan.pdf", scans.pdf_of(stack))
    assert client.delete(f"/api/v1/documents/{document['id']}/separators").status_code == 204
    assert edit(client, document["id"], [(1, 90), (2, 0), (3, 0), (4, 0)]).status_code == 200
    found = client.get(f"/api/v1/documents/{document['id']}/separators").json()
    assert found["version"] == 2 and found["dismissed"] and not found["suggested"]
    assert client.post(f"/api/v1/documents/{document['id']}/versions/1/restore",
                       json={"base_version": 2}).status_code == 200
    assert client.get(f"/api/v1/documents/{document['id']}/separators").json()["dismissed"]


# --- The order the worker serves people in (finding 9) ----------------------------------------------------------------


def test_a_job_version_counts_for_the_owner_of_its_document(client: TestClient, operator: object) -> None:
    jule, tom = make_account("jule"), make_account("tom")
    with new_client(jule) as first, new_client(tom) as second:
        served, waits = made(first, "j1.pdf"), made(first, "j2.pdf")
        theirs = made(second, "t.pdf")
        assert upload_version(first, served["id"], "a.pdf", pdf("Neu Jule eins")).status_code == 202
        assert upload_version(first, waits["id"], "b.pdf", pdf("Neu Jule zwei")).status_code == 202
        assert upload_version(second, theirs["id"], "c.pdf", pdf("Neu Tom")).status_code == 202
    with SessionLocal() as db:
        done, jule_waits, tom_waits = db.scalars(select(Job).where(Job.kind == jobs.VERSION).order_by(Job.id)).all()
        # Jule was just served (her first version): Tom comes before her second one, though it came first.
        done.state, done.started_at = "done", clock.now()
        db.commit()
        assert jobs._fair_choice(db, set(), (jobs.VERSION,)) == tom_waits.id
        assert jule_waits.id < tom_waits.id


def test_two_people_and_a_lock_never_wait_in_a_ring(client: TestClient, operator: object) -> None:
    """Joining a with b and b with a at once: the locks are taken in one order, one wins, the other hears 409 or 503."""
    a, b = made(client, "a.pdf", "Alpha"), made(client, "b.pdf", "Beta")
    results: list[int] = []
    barrier = threading.Barrier(2)

    def go(account: Any, first: dict[str, Any], other: dict[str, Any]) -> None:
        with new_client(account) as browser:
            barrier.wait()
            results.append(browser.post(f"/api/v1/documents/{first['id']}/merge", json={
                "base_version": 1, "others": [{"id": other["id"], "base_version": 1}]}).status_code)

    threads = [threading.Thread(target=go, args=(operator, a, b)), threading.Thread(target=go, args=(operator, b, a))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert len(results) == 2 and results.count(200) == 1, results
    assert leftovers() == []


def test_a_right_lost_while_the_worker_runs_writes_nothing(client: TestClient, operator: object,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """The check under the write lock: the operator takes Tom out of the vault while his edit is in the worker."""
    jule, tom = make_account("jule"), make_account("tom")
    from .papers import shared_vault

    vault = shared_vault("Haushalt", jule, (tom, "edit"))
    with new_client(jule) as owner:
        document = made(owner, "h.pdf", vault_id=vault)
    real = pagetools.assemble

    def assemble(*args: Any, **kwargs: Any) -> Any:
        out = real(*args, **kwargs)
        from app.services import vaults

        with SessionLocal() as db:
            vaults.remove_member(db, jule.id, vault, tom.id)
        return out

    monkeypatch.setattr(pagetools, "assemble", assemble)
    with new_client(tom) as browser:
        answer = edit(browser, document["id"], [(2, 0), (1, 0)])
    assert answer.status_code == 404
    assert len(versions(document["id"])) == 1 and leftovers() == []
