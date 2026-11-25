"""Contract: a backup made, listed, checked, restored, downloaded, brought in, deleted, through the module's routes,
with the app's real data."""

from __future__ import annotations

import zipfile
from typing import Any

from sicherung_contract import code_of, header


def _entries(client: Any, app: Any) -> list[dict[str, Any]]:
    response = client.get(f"{app.prefix}/backups")
    assert response.status_code == 200, response.text
    return response.json()["backups"]


def _make(client: Any, app: Any, note: str = "") -> str:
    response = client.post(f"{app.prefix}/backups", json={"note": note})
    assert response.status_code == 201, response.text
    return response.json()["name"]


def test_a_backup_made_now_is_listed_with_its_facts(app: Any, sicherung: Any) -> None:
    app.add_content("first")
    client = app.operator()
    name = _make(client, app, note="by hand")
    assert sicherung.current().name_pattern.fullmatch(name)
    entry = next(item for item in _entries(client, app) if item["name"] == name)
    assert entry["kind"] == "manual" and entry["readable"] and entry["size"] > 0 and not entry["uploaded"]
    assert entry["note"] == "by hand" and entry["version"]
    summary = client.get(f"{app.prefix}/backups").json()
    assert summary["last"]["created"] == entry["created"] and summary["running"] is False
    assert summary["schedule"]["every"] in ("off", "daily", "weekly")


def test_check_restore_and_the_next_start_bring_the_state_back(app: Any, sicherung: Any, restarts: list) -> None:
    app.add_content("kept")
    before = app.content()
    client = app.operator()
    name = _make(client, app)
    app.add_content("made later")
    assert app.content() != before
    brief = client.post(f"{app.prefix}/backups/{name}/check", json={}).json()
    assert brief["usable"] and brief["database_ok"] and brief["files_ok"] and not brief["too_new"]
    response = client.post(f"{app.prefix}/backups/{name}/restore", json={"password": app.password})
    restarting = sicherung.current().restore == "restart"
    assert response.status_code == (202 if restarting else 200), response.text
    assert response.json()["restarting"] is restarting and len(restarts) == (1 if restarting else 0)
    app.restart()
    assert app.content() == before
    # The way back: the state before the restore, kept as a copy of kind "update".
    notes = [item["note"] for item in _entries(app.operator(), app) if item["kind"] == "update"]
    assert f"before restoring {name}" in notes


def test_a_restore_needs_the_password_and_changes_nothing_without_it(app: Any, sicherung: Any, restarts: list) -> None:
    app.add_content("kept")
    client = app.operator()
    name = _make(client, app)
    app.add_content("stays")
    now = app.content()
    response = client.post(f"{app.prefix}/backups/{name}/restore", json={"password": "not-the-password"})
    assert response.status_code in (400, 401, 403), response.text
    assert restarts == [] and not sicherung.restore.pending_folder().exists()
    app.restart()
    assert app.content() == now


def test_only_the_operator_reaches_any_route(app: Any) -> None:
    client = app.operator()
    name = _make(client, app)
    member = app.member()
    calls = [
        ("get", f"{app.prefix}", None), ("get", f"{app.prefix}/backups", None),
        ("put", f"{app.prefix}/backups/schedule", {"every": "off", "time": "03:00", "keep": 3}),
        ("post", f"{app.prefix}/backups", {}), ("post", f"{app.prefix}/backups/{name}/check", {}),
        ("post", f"{app.prefix}/backups/{name}/download", {"password": app.password}),
        ("post", f"{app.prefix}/backups/{name}/restore", {"password": app.password}),
    ]
    if app.legacy_prefix:
        calls += [("get", app.legacy_prefix, None), ("post", f"{app.legacy_prefix}/{name}/check", {})]
    for method, path, body in calls:
        response = getattr(member, method)(path, **({"json": body} if body is not None else {}))
        assert response.status_code in (401, 403), (method, path, response.status_code)
    response = member.request("DELETE", f"{app.prefix}/backups/{name}", json={"password": app.password})
    assert response.status_code in (401, 403)
    assert any(item["name"] == name for item in _entries(client, app))


def test_download_and_upload_bring_a_backup_to_another_server(app: Any, sicherung: Any) -> None:
    app.add_content("travels")
    client = app.operator()
    name = _make(client, app)
    assert client.post(f"{app.prefix}/backups/{name}/download", json={"password": "wrong-one"}).status_code in (
        400, 401, 403)
    response = client.post(f"{app.prefix}/backups/{name}/download", json={"password": app.password})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    data = response.content
    assert data == sicherung.archives.path_of(name).read_bytes()
    refused = client.post(f"{app.prefix}/backups/upload", content=data, headers={"x-backup-password": header("no")})
    assert refused.status_code in (400, 401, 403)
    uploaded = client.post(f"{app.prefix}/backups/upload", content=data,
                           headers={"x-backup-password": header(app.password)})
    assert uploaded.status_code == 201, uploaded.text
    new = uploaded.json()["name"]
    assert new.endswith("-upload.zip") and new != name
    entry = next(item for item in _entries(client, app) if item["name"] == new)
    assert entry["uploaded"] and entry["readable"]
    assert client.post(f"{app.prefix}/backups/{new}/check", json={}).json()["usable"]


def test_an_upload_that_is_no_backup_of_the_app_is_refused(app: Any) -> None:
    client = app.operator()
    secret = {"x-backup-password": header(app.password)}
    before = len(_entries(client, app))
    garbage = client.post(f"{app.prefix}/backups/upload", content=b"not a zip at all", headers=secret)
    assert garbage.status_code == 400 and code_of(garbage) == "backup_invalid"
    empty = client.post(f"{app.prefix}/backups/upload", content=b"", headers=secret)
    assert empty.status_code == 400 and code_of(empty) == "empty"
    assert len(_entries(client, app)) == before


def test_a_damaged_backup_is_never_restored(app: Any, sicherung: Any, restarts: list, tmp_path: Any) -> None:
    app.add_content("whole")
    client = app.operator()
    name = _make(client, app)
    path = sicherung.archives.path_of(name)
    # Every member's bytes flipped in the middle, the directory left as it is.
    damaged = path.with_name(path.name.replace(".zip", "-9.zip"))
    data = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.compress_size > 64:
                start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
                middle = start + info.compress_size // 2
                for offset in range(middle, middle + 16):
                    data[offset] ^= 0xFF
    damaged.write_bytes(bytes(data))
    brief = client.post(f"{app.prefix}/backups/{damaged.name}/check", json={})
    assert brief.status_code in (200, 400)
    if brief.status_code == 200:
        assert not brief.json()["usable"]
    response = client.post(f"{app.prefix}/backups/{damaged.name}/restore", json={"password": app.password})
    assert response.status_code == 400 and code_of(response) in ("backup_damaged", "backup_invalid")
    assert restarts == [] and not sicherung.restore.pending_folder().exists()


def test_names_outside_the_list_are_not_found(app: Any) -> None:
    client = app.operator()
    for name in ("nonsense.zip", "..%2Fsecret.key", "x" * 90 + ".zip"):
        response = client.post(f"{app.prefix}/backups/{name}/check", json={})
        assert response.status_code == 404, (name, response.status_code)


def test_a_backup_is_deleted_with_the_password(app: Any) -> None:
    client = app.operator()
    name = _make(client, app)
    wrong = client.request("DELETE", f"{app.prefix}/backups/{name}", json={"password": "wrong-one"})
    assert wrong.status_code in (400, 401, 403)
    done = client.request("DELETE", f"{app.prefix}/backups/{name}", json={"password": app.password})
    assert done.status_code == 204
    assert all(item["name"] != name for item in _entries(client, app))
