"""Saved searches (A1, "Gemerkt"): only the known parts of the archive's address are kept, at most 30 per person, in the
person's order; their numbers come from the search with its rights and its brake, and a vault the person lost shows a
hint instead of an error, without telling whether the vault is still there."""

from __future__ import annotations

import sqlite3
import threading
import zipfile
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app import clock
from app import db as database
from app.db import SessionLocal
from app.main import app
from app.models import Account, SavedSearch
from app.services import backups, brakes, saved, vaults

from .conftest import PASSWORD, make_account, new_client
from .papers import add_document, own_vault, shared_vault
from .searching import give_text
from .test_search_rights import raw_key

PATH = "/api/v1/saved-searches"
WORD = "nebenkostenabrechnung"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def keep(client: TestClient, query: str, name: str = "Gemerkt") -> dict[str, Any]:
    answer = client.post(PATH, json={"name": name, "query": query})
    assert answer.status_code == 201, answer.text
    return answer.json()  # type: ignore[no-any-return]


def listed(client: TestClient) -> list[dict[str, Any]]:
    answer = client.get(PATH)
    assert answer.status_code == 200, answer.text
    return answer.json()  # type: ignore[no-any-return]


@pytest.fixture(autouse=True)
def plenty(monkeypatch: pytest.MonkeyPatch) -> None:
    """The brake of the search has a test of its own below."""
    monkeypatch.setitem(brakes.LIMITS, "search", 100_000)


@pytest.fixture
def town(client: TestClient, operator: Account) -> dict[str, Any]:
    jule, tom = make_account("jule"), make_account("tom")
    house = shared_vault("Haushalt", operator, (jule, "manage"), (tom, "edit"))
    mine = own_vault(jule)
    shared_doc = add_document(house, jule, "Abrechnung Haus", amount=1000)
    private_doc = add_document(mine, jule, "Abrechnung privat", amount=2000)
    give_text(shared_doc, f"Die {WORD} 2025")
    give_text(private_doc, f"Meine {WORD} 2025")
    return {"jule": jule, "tom": tom, "house": house, "mine": mine, "shared_doc": shared_doc,
            "private_doc": private_doc, "operator": operator}


# --- What is kept -----------------------------------------------------------------------------------------------------


def test_only_the_known_parts_of_the_address_are_kept(town: dict[str, Any]) -> None:
    with new_client(town["jule"]) as c:
        row = keep(c, f"?q={WORD}&page=3&evil=%3Cscript%3E&sort=-amount&sort=title&n=100&kind=abc&vault=1%3B2"
                      "&year=99999&deadline=soon&keep=expired&tag=strom&callback=x")
        # The page is not kept, unknown parts and values the archive does not know are dropped, the first of a part
        # wins, and the rest is sorted.
        assert row["query"] == f"keep=expired&n=100&q={WORD}&sort=-amount&tag=strom"
        for nothing in ("", "page=2", "evil=1&foo=bar", "sort=sideways", "?"):
            answer = c.post(PATH, json={"name": "x", "query": nothing})
            assert answer.status_code == 422 and answer.json()["detail"]["code"] == "nothing_to_keep", nothing
        for name in ("", "   ", "a" * 61, "a\x00b", "zeile\nzwei"):
            answer = c.post(PATH, json={"name": name, "query": "q=x"})
            assert answer.status_code == 422 and answer.json()["detail"]["code"] == "invalid_name", name
        assert keep(c, "q=x", "  viel   Platz  ")["name"] == "viel Platz"


def test_the_number_is_what_the_search_finds_and_never_more(town: dict[str, Any]) -> None:
    t = town
    with new_client(t["jule"]) as c:
        keep(c, f"q={WORD}", "Alles")
        keep(c, f"q={WORD}&vault={t['house']}", "Haushalt")
        search = c.get("/api/v1/search", params={"q": WORD, "status": "filed"}).json()["total"]
        assert [(e["name"], e["count"], e["state"]) for e in listed(c)] == [("Alles", search, "ok"),
                                                                            ("Haushalt", 1, "ok")]
        assert search == 2
    with new_client(t["tom"]) as c:
        keep(c, f"q={WORD}", "Alles")
        # tom sees the household's document only: jule's own one is never counted for him.
        assert [e["count"] for e in listed(c)] == [1]
        # His list is his alone.
        assert [e["name"] for e in listed(c)] == ["Alles"]


def test_a_document_shared_one_by_one_counts_and_stops_counting(town: dict[str, Any]) -> None:
    t = town
    with new_client(t["tom"]) as c:
        keep(c, f"q={WORD}&vault=shared", "Mit mir geteilt")
        assert listed(c)[0]["count"] == 0
        with new_client(t["jule"]) as j:
            assert j.put(f"/api/v1/documents/{t['private_doc']}/shares/{t['tom'].id}",
                         json={"right": "read"}).status_code == 200
        assert listed(c)[0]["count"] == 1
        with new_client(t["jule"]) as j:
            assert j.delete(f"/api/v1/documents/{t['private_doc']}/shares/{t['tom'].id}").status_code == 204
        # The kept number does not outlive the share.
        assert listed(c)[0]["count"] == 0


def test_a_lost_vault_shows_a_hint_and_tells_nothing(town: dict[str, Any]) -> None:
    t = town
    with new_client(t["tom"]) as c:
        lost = keep(c, f"vault={t['house']}", "Haushalt")
        never = keep(c, "vault=999999", "Gab es nie")
        assert [e["state"] for e in listed(c)] == ["ok", "no_access"]
        with SessionLocal() as db:
            vaults.remove_member_unchecked(db, t["house"], t["tom"].id)
            db.commit()
        entries = {e["id"]: e for e in listed(c)}
        assert entries[lost["id"]]["state"] == entries[never["id"]]["state"] == "no_access"
        assert entries[lost["id"]]["count"] is None and entries[never["id"]]["count"] is None
        strip = lambda e: {k: v for k, v in e.items() if k not in ("id", "name", "query", "position")}
        assert strip(entries[lost["id"]]) == strip(entries[never["id"]])


def test_with_deadlines_switched_off_the_filter_counts_as_in_the_archive(town: dict[str, Any]) -> None:
    t = town
    soon = clock.now().date() + timedelta(days=10)
    add_document(t["house"], t["jule"], "Rechnung offen", dates=[("due", soon)])
    with new_client(t["jule"]) as c:
        keep(c, f"deadline=open&vault={t['house']}", "Offen")
        assert [(e["count"], e["deadlines_off"]) for e in listed(c)] == [(1, False)]
        with SessionLocal() as db:
            row = db.get(Account, t["jule"].id)
            assert row is not None
            row.profile = {**(row.profile or {}), "deadlines": False}
            db.commit()
        # The archive leaves the filter out for her: so does the number, and the entry says why.
        assert [(e["count"], e["deadlines_off"], e["state"]) for e in listed(c)] == [(2, True, "ok")]


# --- At most 30, the order, renaming, deleting ------------------------------------------------------------------------


def test_thirty_and_not_one_more(town: dict[str, Any]) -> None:
    with new_client(town["jule"]) as c:
        for n in range(saved.MAX):
            keep(c, f"q=wort{n}", f"Suche {n}")
        answer = c.post(PATH, json={"name": "Eine zu viel", "query": "q=zuviel"})
        assert answer.status_code == 409 and answer.json()["detail"] == {
            "code": "too_many_saved", "message": "At most 30 saved searches.", "max": 30}
        assert [e["position"] for e in listed(c)] == list(range(30))
        # Another person has their own thirty.
    with new_client(town["tom"]) as c:
        keep(c, "q=frei")


def test_two_saves_at_the_same_moment_cannot_pass_thirty(town: dict[str, Any]) -> None:
    with new_client(town["jule"]) as c:
        for n in range(saved.MAX - 1):
            keep(c, f"q=wort{n}")
    codes: list[int] = []

    def save(n: int) -> None:
        with new_client(town["jule"]) as c:
            codes.append(c.post(PATH, json={"name": f"x{n}", "query": f"q=gleichzeitig{n}"}).status_code)

    threads = [threading.Thread(target=save, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(codes) == [201, 409, 409, 409]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SavedSearch)) == saved.MAX


def test_up_down_rename_delete(town: dict[str, Any]) -> None:
    with new_client(town["jule"]) as c:
        a, b, d = keep(c, "q=a", "A"), keep(c, "q=b", "B"), keep(c, "q=d", "D")
        assert [e["name"] for e in c.post(f"{PATH}/{d['id']}/up").json()] == ["A", "D", "B"]
        assert [e["name"] for e in c.post(f"{PATH}/{a['id']}/up").json()] == ["A", "D", "B"]
        assert [e["name"] for e in c.post(f"{PATH}/{a['id']}/down").json()] == ["D", "A", "B"]
        assert [e["name"] for e in c.post(f"{PATH}/{b['id']}/down").json()] == ["D", "A", "B"]
        renamed = c.patch(f"{PATH}/{b['id']}", json={"name": "Belege"})
        assert renamed.status_code == 200 and renamed.json()["name"] == "Belege"
        assert c.delete(f"{PATH}/{a['id']}").status_code == 204
        assert [(e["name"], e["position"]) for e in listed(c)] == [("D", 0), ("Belege", 1)]
        assert c.delete(f"{PATH}/{a['id']}").status_code == 404


def test_two_moves_at_the_same_moment_keep_every_entry_once(town: dict[str, Any]) -> None:
    with new_client(town["jule"]) as c:
        rows = [keep(c, f"q=w{n}", f"S{n}") for n in range(6)]

    def move(saved_id: int, way: str) -> None:
        with new_client(town["jule"]) as c:
            for _ in range(5):
                assert c.post(f"{PATH}/{saved_id}/{way}").status_code == 200

    threads = [threading.Thread(target=move, args=(rows[0]["id"], "down")),
               threading.Thread(target=move, args=(rows[5]["id"], "up")),
               threading.Thread(target=move, args=(rows[2]["id"], "down"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with new_client(town["jule"]) as c:
        entries = listed(c)
    assert sorted(e["id"] for e in entries) == sorted(r["id"] for r in rows)
    assert [e["position"] for e in entries] == list(range(6))


def test_nobody_reaches_the_entries_of_another(town: dict[str, Any]) -> None:
    with new_client(town["jule"]) as c:
        row = keep(c, "q=geheim", "Meine Suche")
    with new_client(town["tom"]) as c:
        assert listed(c) == []
        for method, tail, body in (("PATCH", "", {"name": "Fremd"}), ("POST", "/up", None), ("POST", "/down", None),
                                   ("DELETE", "", None)):
            path = f"{PATH}/{row['id']}{tail}"
            mine = c.request(method, path, json=body)
            missing = c.request(method, f"{PATH}/999999{tail}", json=body)
            assert mine.status_code == missing.status_code == 404, (method, path)
            assert mine.json() == missing.json()
    with new_client(town["jule"]) as c:
        assert [e["name"] for e in listed(c)] == ["Meine Suche"]


def test_devices_and_keys(client: TestClient, town: dict[str, Any]) -> None:
    assert client.put("/api/v1/settings", json={"api_keys_allowed": True}).status_code == 200
    with new_client(town["jule"]) as c:
        keep(c, f"q={WORD}", "Im Browser")
        token = c.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    read_key, upload_key = raw_key(town["jule"], "read"), raw_key(town["jule"], "upload")
    with TestClient(app, base_url="http://testserver") as program:
        made = program.post(PATH, json={"name": "Vom Handy", "query": "q=handy"}, headers=bearer(token))
        assert made.status_code == 201, made.text
        assert [e["name"] for e in program.get(PATH, headers=bearer(token)).json()] == ["Im Browser", "Vom Handy"]
        # A read key reads, never changes; an upload key does neither.
        assert [e["count"] for e in program.get(PATH, headers=bearer(read_key)).json()] == [2, 0]
        for key in (read_key, upload_key):
            assert program.post(PATH, json={"name": "k", "query": "q=k"}, headers=bearer(key)).status_code == 401
            assert program.delete(f"{PATH}/{made.json()['id']}", headers=bearer(key)).status_code == 401
        assert program.get(PATH, headers=bearer(upload_key)).status_code == 403
        # A link to a document is no way in.
    with TestClient(app, base_url="http://testserver", headers={"X-Nexpaper-Client": "tab-tests000"}) as anonymous:
        assert anonymous.get(PATH).status_code == 401


def test_the_numbers_take_the_brake_of_the_search_once_and_are_kept_a_moment(
    town: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(brakes.LIMITS, "search", 2)
    with new_client(town["jule"]) as c:
        for n in range(5):
            keep(c, f"q=w{n}")
        assert listed(c)  # one brake for five numbers
        assert listed(c)  # kept: no brake
        add_document(town["house"], town["jule"], "Neu")  # a change: counted again
        assert listed(c)
        add_document(town["house"], town["jule"], "Noch eins")
        answer = c.get(PATH)
        assert answer.status_code == 429 and answer.json()["detail"]["code"] == "search_too_often"


def test_the_entries_go_with_the_account(client: TestClient, town: dict[str, Any]) -> None:
    with new_client(town["tom"]) as c:
        keep(c, "q=a")
        keep(c, "q=b")
    answer = client.request("DELETE", f"/api/v1/accounts/{town['tom'].id}",
                            json={"current_password": PASSWORD, "confirm_name": "tom", "documents": "delete_documents"})
    assert answer.status_code == 204, answer.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SavedSearch)) == 0


# --- The schema step and the backup -----------------------------------------------------------------------------------

RECORDS = Path(__file__).parent / "schema"


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "nexpaper.db"
    monkeypatch.setattr(database, "engine", create_engine(f"sqlite:///{path}"))
    monkeypatch.setattr(backups, "create", lambda **_kwargs: path)
    return path


def test_a_database_of_schema_14_comes_up_with_the_table_and_keeps_what_it_had(scratch: Path) -> None:
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v14.sql").read_text(encoding="utf-8"))
        connection.execute("INSERT INTO users (id, name, display_name, whats_new_seen, role, sign_in, password_hash, "
                           "email, oidc_subject, language, created_at, failed_logins, totp_secret_enc, totp_recovery, "
                           "totp_last_step) VALUES (1, 'jule', 'Jule', '', 'member', 'password', '', '', '', 'de', "
                           "'2026-10-01 08:00:00', 0, '', '', 0)")
        connection.execute("PRAGMA user_version = 14")
        connection.commit()
    database.init_db()
    with closing(sqlite3.connect(scratch)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        assert connection.execute("SELECT count(*) FROM saved_searches").fetchone()[0] == 0
        assert connection.execute("SELECT name FROM users").fetchall() == [("jule",)]
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("INSERT INTO saved_searches (user_id, name, query, position, created_at) VALUES "
                           "(1, 'Strom', 'q=strom', 0, '2026-11-12 08:00:00')")
        connection.execute("DELETE FROM users WHERE id = 1")
        assert connection.execute("SELECT count(*) FROM saved_searches").fetchone()[0] == 0, "goes with the person"


def test_the_backup_holds_the_saved_searches_and_its_trial_passes(town: dict[str, Any], tmp_path: Path) -> None:
    with new_client(town["jule"]) as c:
        keep(c, f"q={WORD}&sort=-amount", "Nebenkosten")
    path = backups.create(kind=backups.MANUAL)
    try:
        with zipfile.ZipFile(path) as archive:
            copy = tmp_path / "copy.db"
            copy.write_bytes(archive.read(backups.DATABASE_ENTRY))
        with closing(sqlite3.connect(copy)) as connection:
            assert connection.execute("SELECT user_id, name, query, position FROM saved_searches").fetchall() == [
                (town["jule"].id, "Nebenkosten", f"q={WORD}&sort=-amount", 0)]
        brief = backups.check(path.name)
        assert brief.usable and brief.schema == database.SCHEMA_VERSION
    finally:
        path.unlink(missing_ok=True)