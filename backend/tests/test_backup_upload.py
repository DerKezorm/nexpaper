"""A backup brought in from elsewhere: for a move to a new server, the downloaded archive goes up again and joins the
list, to be checked and restored like any other."""

from __future__ import annotations

import base64
import io
import zipfile

from fastapi.testclient import TestClient

from app.models import Account
from app.services import backups

from .conftest import PASSWORD, make_account, new_client


def _header(password: str = PASSWORD) -> dict[str, str]:
    return {"X-Nexpaper-Password": base64.b64encode(password.encode("utf-8")).decode("ascii")}


def _downloaded(client: TestClient) -> bytes:
    """A backup made here, carried away and deleted: what someone moving to a new server holds in their hands."""
    name = client.post("/api/v1/backups", json={"note": "before the move"}).json()["name"]
    archive = client.post(f"/api/v1/backups/{name}/download", json={"password": PASSWORD}).content
    assert client.request("DELETE", f"/api/v1/backups/{name}", json={"password": PASSWORD}).status_code == 204
    return archive


def _names(client: TestClient) -> set[str]:
    return {entry["name"] for entry in client.get("/api/v1/backups").json()}


def _leftovers() -> list[str]:
    return [path.name for path in backups.folder().iterdir() if path.name.startswith(".upload-")]


def test_an_uploaded_backup_joins_the_list_checks_whole_and_restores(client: TestClient, operator: Account) -> None:
    archive = _downloaded(client)
    answer = client.post("/api/v1/backups/upload", content=archive, headers=_header())
    assert answer.status_code == 201, answer.text
    name = answer.json()["name"]
    assert name.endswith("-upload.zip") and backups.NAME.match(name)
    listed = {entry["name"]: entry for entry in client.get("/api/v1/backups").json()}
    assert listed[name]["uploaded"] is True and listed[name]["note"] == "before the move"
    assert client.post(f"/api/v1/backups/{name}/check").json()["usable"] is True
    # The restore itself is the one every backup has; here only that it takes this archive (the restart is not run).
    assert backups.stage_restore(name).usable
    assert _leftovers() == []


def test_the_same_archive_twice_keeps_both(client: TestClient, operator: Account) -> None:
    archive = _downloaded(client)
    first = client.post("/api/v1/backups/upload", content=archive, headers=_header()).json()["name"]
    second = client.post("/api/v1/backups/upload", content=archive, headers=_header()).json()["name"]
    assert first != second and {first, second} <= _names(client)


def test_an_upload_needs_the_password_and_keeps_nothing_without_it(client: TestClient, operator: Account) -> None:
    archive = _downloaded(client)
    before = _names(client)
    for headers in ({}, _header("wrong password here"), {"X-Nexpaper-Password": "not base64!"}):
        answer = client.post("/api/v1/backups/upload", content=archive, headers=headers)
        assert answer.status_code == 401, answer.text
    assert _names(client) == before
    assert _leftovers() == []


def test_only_the_operator_uploads(client: TestClient, operator: Account) -> None:
    archive = _downloaded(client)
    before = _names(client)
    with new_client(make_account("noor")) as member:
        assert member.post("/api/v1/backups/upload", content=archive, headers=_header()).status_code == 403
    assert _names(client) == before


def test_what_is_not_one_of_ours_is_refused_and_leaves_nothing(client: TestClient, operator: Account) -> None:
    before = _names(client)
    plain = io.BytesIO()
    with zipfile.ZipFile(plain, "w") as other:
        other.writestr("notes.txt", "not a backup")
    no_database = io.BytesIO()
    with zipfile.ZipFile(no_database, "w") as other:
        other.writestr(backups.MANIFEST, '{"version": "0.2.1", "created": "2026-10-05T07:00:00+00:00", "kind": "manual"}')
    for body in (b"just some bytes", plain.getvalue(), no_database.getvalue()):
        answer = client.post("/api/v1/backups/upload", content=body, headers=_header())
        assert answer.status_code == 400 and answer.json()["detail"]["code"] == "backup_invalid", answer.text
    assert client.post("/api/v1/backups/upload", content=b"", headers=_header()).status_code == 400
    assert _names(client) == before
    assert _leftovers() == []


def test_pruning_old_automatic_copies_leaves_an_uploaded_one(client: TestClient, operator: Account) -> None:
    archive = io.BytesIO(_downloaded(client))
    # A copy made by the nightly schedule elsewhere: its manifest says "scheduled".
    scheduled = io.BytesIO()
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(scheduled, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == backups.MANIFEST:
                data = data.replace(b'"kind": "manual"', b'"kind": "scheduled"')
            target.writestr(info, data)
    name = client.post("/api/v1/backups/upload", content=scheduled.getvalue(), headers=_header()).json()["name"]
    made = [backups.create(kind=backups.SCHEDULED).name for _ in range(3)]
    backups.prune(1)
    left = {entry.name for entry in backups.entries()}
    # The uploaded one stays although its manifest says "scheduled"; of the three made here only one (made within the
    # same second, which of them counts as newest is not fixed).
    assert name in left
    assert len([one for one in made if one in left]) == 1


def test_an_archive_larger_than_an_ordinary_request_goes_up(client: TestClient, operator: Account) -> None:
    """Ordinary requests stop at 16 MB; a real backup is bigger, and the upload has its own ceiling."""
    import os
    import sqlite3

    from app.config import get_settings

    path = get_settings().database_path
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE ballast (data BLOB)")
        connection.execute("INSERT INTO ballast VALUES (?)", (os.urandom(17 * 1024 * 1024),))
    connection.close()
    try:
        archive = _downloaded(client)
    finally:
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TABLE ballast")
        connection.close()
    assert len(archive) > 16 * 1024 * 1024
    answer = client.post("/api/v1/backups/upload", content=archive, headers=_header())
    assert answer.status_code == 201, answer.text
