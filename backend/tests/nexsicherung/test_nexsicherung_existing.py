"""Contract, what was there before the module keeps working: a backup the app made with its old code is listed,
checked and restored; the old routes answer in their old shapes; the schedule is the one the app's settings route
reads."""

from __future__ import annotations

from typing import Any

from sicherung_contract import header


def test_a_backup_of_the_older_version_is_listed_checked_and_restored(app: Any, sicherung: Any) -> None:
    path, held = app.legacy_archive()
    app.add_content("after the old backup")
    assert app.content() != held
    client = app.operator()
    listed = client.get(f"{app.prefix}/backups").json()["backups"]
    entry = next(item for item in listed if item["name"] == path.name)
    assert entry["readable"], entry
    brief = client.post(f"{app.prefix}/backups/{path.name}/check", json={}).json()
    assert brief["usable"], brief
    response = client.post(f"{app.prefix}/backups/{path.name}/restore", json={"password": app.password})
    assert response.status_code in (200, 202), response.text
    app.restart()
    assert app.content() == held


def test_the_old_routes_answer_in_their_old_shapes(app: Any, sicherung: Any) -> None:
    if not app.legacy_prefix:
        return
    app.add_content("old ways")
    client = app.operator()
    made = client.post(app.legacy_prefix, json={"note": "old route"})
    assert made.status_code == 201 and set(made.json()) == {"name"}
    name = made.json()["name"]
    listed = client.get(app.legacy_prefix)
    assert listed.status_code == 200 and isinstance(listed.json(), list)
    entry = next(item for item in listed.json() if item["name"] == name)
    module_entry = next(item for item in client.get(f"{app.prefix}/backups").json()["backups"]
                        if item["name"] == name)
    # The old listing: the facts of the app at the top level, as before the module.
    for key, value in module_entry["facts"].items():
        assert entry[key] == value
    for key in ("name", "size", "created", "kind", "note", "version", "uploaded"):
        assert entry[key] == module_entry[key]
    brief = client.post(f"{app.legacy_prefix}/{name}/check").json()
    assert brief["usable"] and brief["name"] == name
    data = client.post(f"{app.legacy_prefix}/{name}/download", json={"password": app.password}).content
    assert data == sicherung.archives.path_of(name).read_bytes()
    if app.legacy_header:
        uploaded = client.post(f"{app.legacy_prefix}/upload", content=data,
                               headers={app.legacy_header: header(app.password)})
        assert uploaded.status_code == 201 and uploaded.json()["name"].endswith("-upload.zip")
    deleted = client.request("DELETE", f"{app.legacy_prefix}/{name}", json={"password": app.password})
    assert deleted.status_code == 204


def test_the_schedule_is_the_one_of_the_apps_settings(app: Any) -> None:
    client = app.operator()
    saved = client.put(f"{app.prefix}/backups/schedule", json={"every": "weekly", "time": "04:30", "keep": 3})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"every": "weekly", "time": "04:30", "keep": 3}
    assert client.get(f"{app.prefix}/backups").json()["schedule"] == {"every": "weekly", "time": "04:30", "keep": 3}
    assert app.settings_schedule() == ("weekly", 3)
    # "Jeden Monat", on the first at the time, in every app (nexmail could, so all can).
    monthly = client.put(f"{app.prefix}/backups/schedule", json={"every": "monthly", "time": "04:30", "keep": 3})
    assert monthly.status_code == 200 and app.settings_schedule() == ("monthly", 3)
    client.put(f"{app.prefix}/backups/schedule", json={"every": "weekly", "time": "04:30", "keep": 3})
    for body in ({"every": "yearly", "time": "04:30", "keep": 3}, {"every": "daily", "time": "25:00", "keep": 3},
                 {"every": "daily", "time": "04:30", "keep": 0}, {"every": "daily", "time": "04:30", "keep": 366},
                 {"every": "daily", "time": "04:30", "keep": "3"}):
        assert client.put(f"{app.prefix}/backups/schedule", json=body).status_code in (400, 422), body
    assert app.settings_schedule() == ("weekly", 3)


def test_only_automatic_copies_are_pruned(app: Any, sicherung: Any) -> None:
    client = app.operator()
    manual = sicherung.archives.create(kind=sicherung.MANUAL).name
    automatic = [sicherung.archives.create(kind=sicherung.SCHEDULED).name for _ in range(3)]
    client.put(f"{app.prefix}/backups/schedule", json={"every": "daily", "time": "03:00", "keep": 2})
    names = {item["name"] for item in client.get(f"{app.prefix}/backups").json()["backups"]}
    assert manual in names
    assert sum(name in names for name in automatic) == 2


def test_the_storage_card_names_what_the_app_takes(app: Any) -> None:
    app.add_content("takes room")
    client = app.operator()
    client.post(f"{app.prefix}/backups", json={})
    found = client.get(app.prefix).json()
    keys = [part["key"] for part in found["parts"]]
    assert "database" in keys and "backups" in keys
    assert found["used"] > 0 and found["total"] > 0 and 0 <= found["free"] <= found["total"]
    assert set(found["where"]) >= {"data"}
    assert found["network"] == [] or all(key in found["where"] for key in found["network"])
