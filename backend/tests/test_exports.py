"""Exports for the tax adviser: only what the person may see, the ZIP as on the disk with safe names, the list safe for
spreadsheets, limits, the link for somebody without an account (its end, revoking, the operator's switch, the maker's
rights), cleaning up, and every route against callers who may not."""

from __future__ import annotations

import csv
import io
import shutil
import threading
import zipfile
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import clock
from app.db import SessionLocal
from app.models import Account, Export, ExportLink
from app.services import exports, jobs, push, settings_service, vaults

from .conftest import DATA_DIR, make_account, new_client
from .papers import PDF, add_document, own_vault, shared_vault

DE = {"X-Nexpaper-Language": "de"}


@pytest.fixture(autouse=True)
def clean_folders() -> Iterator[None]:
    shutil.rmtree(Path(DATA_DIR) / "exports", ignore_errors=True)
    yield


class World:
    def __init__(self, operator: Account) -> None:
        self.operator = operator
        self.jule = make_account("jule")
        self.tom = make_account("tom")
        self.firma = shared_vault("Firma", operator, (self.jule, "edit"))
        self.mine = own_vault(self.jule)
        self.strom = add_document(self.mine, self.jule, "Strom März", sender="Stadtwerke Lindenau",
                                  date=date(2026, 3, 14), amount=8400)
        self.rechnung = add_document(self.firma, self.jule, "Rechnung Heizungswartung", sender="Elektro Brandt GmbH",
                                     date=date(2026, 10, 6), amount=41250)
        self.old = add_document(self.mine, self.jule, "Alt", date=date(2025, 5, 1), amount=100)
        # Somebody else's in the same period: never in jule's export.
        self.foreign = add_document(own_vault(self.tom), self.tom, "Toms Geheimnis", sender="Geheim",
                                    date=date(2026, 6, 1), amount=99900)


@pytest.fixture
def world(client: TestClient, operator: Account) -> World:
    return World(operator)


def body(world: World, **extra: Any) -> dict[str, Any]:
    return {"date_from": "2026-01-01", "date_to": "2026-12-31", "vault_ids": [world.mine, world.firma], **extra}


def pack() -> None:
    jobs.run_pending(kinds=(jobs.EXPORT,))


def zip_of(client: TestClient, export_id: int) -> zipfile.ZipFile:
    answer = client.get(f"/api/v1/exports/{export_id}/file")
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(answer.content))


def make(client: TestClient, world: World, **extra: Any) -> dict[str, Any]:
    answer = client.post("/api/v1/exports", json=body(world, **extra), headers=DE)
    assert answer.status_code == 201, answer.text
    return answer.json()  # type: ignore[no-any-return]


def test_the_preview_counts_only_what_the_person_sees(world: World) -> None:
    with new_client(world.jule) as jule:
        answer = jule.get("/api/v1/exports/preview", params={"vault_ids": [world.mine, world.firma],
                                                             "date_from": "2026-01-01", "date_to": "2026-12-31"},
                          headers=DE)
        assert answer.status_code == 200, answer.text
        found = answer.json()
        assert found["documents"] == 2 and found["total"] == 8400 + 41250
        assert found["size"] == 2 * len(PDF)
        assert found["sample"][-1] == "liste.csv"
        assert any(path.startswith("Firma/2026/Elektro Brandt GmbH/2026-10-06 Rechnung Heizungswartung")
                   for path in found["sample"])
        # A vault of somebody else is as if it did not exist.
        stranger = jule.get("/api/v1/exports/preview", params={"vault_ids": [own_vault(world.tom)]})
        assert stranger.status_code == 404


def test_the_zip_holds_what_was_asked_for_and_nothing_of_anybody_else(world: World) -> None:
    with new_client(world.jule) as jule:
        made = make(jule, world, content={"pdf": True, "original": False, "csv": True, "xml": True})
        assert made["state"] == "queued"
        pack()
        shown = jule.get(f"/api/v1/exports/{made['id']}").json()
        assert shown["state"] == "ready" and shown["documents"] == 2 and shown["total"] == 49650
        archive = zip_of(jule, made["id"])
        names = sorted(archive.namelist())
        assert names == ["Firma/2026/Elektro Brandt GmbH/2026-10-06 Rechnung Heizungswartung.pdf",
                         "jule/2026/Stadtwerke Lindenau/2026-03-14 Strom März.pdf", "liste.csv"]
        assert archive.read(names[0]) == PDF
        listing = archive.read("liste.csv")
        assert listing.startswith(b"\xef\xbb\xbf")
        rows = list(csv.reader(io.StringIO(listing.decode("utf-8-sig")), delimiter=";"))
        assert rows[0] == ["Datum", "Titel", "Absender", "Art", "Betrag", "Währung", "Rechnungsnummer", "Tresor",
                           "Datei", "Fällig am", "Vertrag bis", "Kündigen bis", "Garantie bis", "Erledigt",
                           "Aufbewahren bis"]
        assert ["2026-03-14", "Strom März", "Stadtwerke Lindenau", "", "84,00", "EUR", "", "jule",
                "jule/2026/Stadtwerke Lindenau/2026-03-14 Strom März.pdf", "", "", "", "", "", ""] in rows
        assert not any("Geheim" in "".join(row) for row in rows)


def test_originals_and_the_english_list(world: World) -> None:
    with new_client(world.jule) as jule:
        answer = jule.post("/api/v1/exports", json=body(world, vault_ids=[world.mine],
                                                         content={"pdf": True, "original": True, "csv": True,
                                                                  "xml": False}))
        pack()
        archive = zip_of(jule, answer.json()["id"])
        # The original is the PDF itself: it is in the ZIP once.
        assert sorted(archive.namelist()) == ["jule/2026/Stadtwerke Lindenau/2026-03-14 Strom März.pdf", "list.csv"]
        assert archive.read("list.csv").decode("utf-8-sig").splitlines()[1].split(";")[4] == "84.00"


def test_the_list_cannot_carry_a_formula(world: World) -> None:
    for title in ("=HYPERLINK(\"http://example.com\")", "+1+1", "-2+3", "@SUM(A1)"):
        add_document(world.mine, world.jule, title, sender="=cmd|' /C calc'!A0", date=date(2026, 4, 1))
    with new_client(world.jule) as jule:
        made = make(jule, world)
        pack()
        listing = zip_of(jule, made["id"]).read("liste.csv").decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(listing), delimiter=";"))[1:]
    for row in rows:
        for index in (1, 2, 3, 7, 8):
            assert not row[index].startswith(("=", "+", "-", "@")), row
    assert any(row[1] == "'=HYPERLINK(\"http://example.com\")" for row in rows)
    assert any(row[2] == "'=cmd|' /C calc'!A0" for row in rows)


def test_names_in_the_zip_never_leave_it(world: World) -> None:
    add_document(world.mine, world.jule, "../../etc/passwd", sender="..\\..\\Windows", date=date(2026, 5, 1))
    add_document(world.mine, world.jule, "/absolut", sender="C:\\temp", date=date(2026, 5, 1))
    add_document(world.mine, world.jule, "/absolut", sender="C:\\temp", date=date(2026, 5, 1))
    with new_client(world.jule) as jule:
        made = make(jule, world)
        pack()
        names = zip_of(jule, made["id"]).namelist()
    for name in names:
        assert ".." not in name.split("/") and not name.startswith("/") and "\\" not in name and ":" not in name
    assert len(names) == len({name.casefold() for name in names}) == 6
    # Vault, year, sender, file: a slash in a title or a sender never makes a folder of its own.
    assert all(len(name.split("/")) == 4 for name in names if not name.endswith(".csv"))


def test_the_export_follows_the_filters_of_the_archive(world: World) -> None:
    with new_client(world.jule) as jule:
        made = make(jule, world, sender="Stadtwerke Lindenau")
        pack()
        assert jule.get(f"/api/v1/exports/{made['id']}").json()["documents"] == 1
        searched = make(jule, world, q="Heizungswartung")
        pack()
        assert jule.get(f"/api/v1/exports/{searched['id']}").json()["documents"] == 1


def test_a_vault_left_before_packing_counts_no_more(world: World) -> None:
    with new_client(world.jule) as jule:
        made = make(jule, world)
        with SessionLocal() as db:
            vaults.remove_member(db, world.operator.id, world.firma, world.jule.id)
        pack()
        shown = jule.get(f"/api/v1/exports/{made['id']}").json()
        assert shown["documents"] == 1
        assert "Firma/" not in " ".join(zip_of(jule, made["id"]).namelist())


def test_nobody_else_reaches_an_export(world: World) -> None:
    with new_client(world.jule) as jule:
        made = make(jule, world)
        pack()
    with new_client(world.tom) as tom:
        for method, path in (("GET", f"/api/v1/exports/{made['id']}"), ("GET", f"/api/v1/exports/{made['id']}/file"),
                             ("DELETE", f"/api/v1/exports/{made['id']}"),
                             ("GET", f"/api/v1/exports/{made['id']}/links"),
                             ("POST", f"/api/v1/exports/{made['id']}/links")):
            extra = {"json": {"recipient": "x", "days": 1}} if method == "POST" else {}
            assert tom.request(method, path, **extra).status_code == 404, path
        assert tom.get("/api/v1/exports").json() == []


def test_a_device_only_looks_and_a_key_reaches_nothing(world: World) -> None:
    """An export holds a whole period: making one, fetching its ZIP and handing it out by a link need the browser the
    person sits at. A device (a lost phone) may list, look, delete and revoke; a key nothing."""
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(world.jule) as jule:
        token = jule.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
        key = jule.post("/api/v1/api-keys", json={"name": "k", "scope": "read"}).json()["secret"]
        made, _link_token = linked(world)
        pack()
        link_id = jule.get(f"/api/v1/exports/{made['id']}/links").json()[0]["id"]
    with TestClient(jule.app, base_url="http://testserver") as program:
        device = {"Authorization": f"Bearer {token}"}
        for method, path, payload in (
            ("POST", "/api/v1/exports", body(world)),
            ("GET", f"/api/v1/exports/{made['id']}/file", None),
            ("POST", f"/api/v1/exports/{made['id']}/links", {"recipient": "x", "days": 2}),
            ("POST", f"/api/v1/exports/{made['id']}/links/{link_id}/address", None),
        ):
            extra = {"json": payload} if payload is not None else {}
            answer = program.request(method, path, headers=device, **extra)
            assert answer.status_code == 403 and answer.json()["detail"]["code"] == "browser_only", path
        assert program.get("/api/v1/exports", headers=device).status_code == 200
        assert program.get(f"/api/v1/exports/{made['id']}", headers=device).status_code == 200
        assert program.get("/api/v1/exports/preview", params={"vault_ids": [world.mine]}, headers=device).status_code == 200
        assert program.delete(f"/api/v1/exports/{made['id']}/links/{link_id}", headers=device).status_code == 204
        keyed = {"Authorization": f"Bearer {key}"}
        assert program.get(f"/api/v1/exports/{made['id']}/file", headers=keyed).status_code in (401, 403)
        assert program.post("/api/v1/exports", json=body(world), headers=keyed).status_code in (401, 403)
        assert program.get("/api/v1/exports", headers=keyed).status_code == 401
        assert program.delete(f"/api/v1/exports/{made['id']}", headers=device).status_code == 204


def test_limits_on_waiting_exports_and_double_clicks(world: World) -> None:
    with new_client(world.jule) as jule:
        answers: list[int] = []

        def go() -> None:
            with new_client(world.jule) as browser:
                answers.append(browser.post("/api/v1/exports", json=body(world)).status_code)

        threads = [threading.Thread(target=go) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(answers) == [201] * exports.MAX_WAITING + [409] * (6 - exports.MAX_WAITING)
        assert jule.post("/api/v1/exports", json=body(world)).json()["detail"]["code"] == "export_busy"


def test_too_many_documents_and_nothing_found_fail_with_their_reason(world: World,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(exports, "MAX_DOCUMENTS", 1)
    with new_client(world.jule) as jule:
        made = make(jule, world)
        pack()
        shown = jule.get(f"/api/v1/exports/{made['id']}").json()
        assert (shown["state"], shown["error"]) == ("failed", "too_many_documents")
        empty = make(jule, world, date_from="2030-01-01", date_to="2030-12-31")
        pack()
        assert jule.get(f"/api/v1/exports/{empty['id']}").json()["error"] == "nothing_found"
        assert jule.get(f"/api/v1/exports/{empty['id']}/file").json()["detail"]["code"] == "export_not_ready"


def test_wrong_requests(world: World) -> None:
    with new_client(world.jule) as jule:
        backwards = jule.post("/api/v1/exports", json=body(world, date_from="2026-12-31", date_to="2026-01-01"))
        assert backwards.json()["detail"]["code"] == "export_period_invalid"
        nothing = jule.post("/api/v1/exports", json=body(world, content={"pdf": False, "original": False,
                                                                          "csv": False, "xml": False}))
        assert nothing.json()["detail"]["code"] == "export_empty_choice"
        assert jule.post("/api/v1/exports", json=body(world, vault_ids=[])).status_code == 422
        assert jule.post("/api/v1/exports", json=body(world, link={"recipient": " ", "days": 3})).status_code == 422
        with SessionLocal() as db:
            assert db.scalar(select(Export.id)) is None


def test_ready_tells_the_person(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import notices

    told: list[tuple[int, str]] = []

    def capture(account_id: int, message_for: Any) -> push.Result:
        told.append((account_id, message_for("de").body))
        return push.Result()

    monkeypatch.setattr(push, "send_to_person", capture)
    with new_client(world.jule) as jule:
        make(jule, world)
        pack()
    notices.settle()
    assert told == [(world.jule.id, "Dein ZIP mit 2 Dokumenten liegt bereit.")]


# --- The link for somebody without an account ------------------------------------------------------------------------


def linked(world: World, **extra: Any) -> tuple[dict[str, Any], str]:
    with new_client(world.jule) as jule:
        made = make(jule, world, link={"recipient": "Steuerbüro Lindenau", "days": 14}, **extra)
    token = made["link"]["token"]
    assert token.startswith("lnx_") and made["link"]["url"].endswith(f"/x/{token}")
    return made, token


def test_the_link_shows_and_hands_out_the_zip_and_counts(world: World, client: TestClient) -> None:
    made, token = linked(world)
    with TestClient(client.app, base_url="http://testserver") as outsider:
        packing = outsider.get(f"/api/v1/x/{token}")
        assert packing.status_code == 200 and packing.json()["state"] == "packing"
        assert outsider.get(f"/api/v1/x/{token}/file").json()["detail"]["code"] == "export_not_ready"
        pack()
        shown = outsider.get(f"/api/v1/x/{token}").json()
        assert shown["state"] == "ready" and shown["documents"] == 2 and shown["recipient"] == "Steuerbüro Lindenau"
        assert "jule" not in shown["shared_by"]
        got = outsider.get(f"/api/v1/x/{token}/file")
        assert got.status_code == 200 and zipfile.ZipFile(io.BytesIO(got.content)).namelist()
    with new_client(world.jule) as jule:
        links = jule.get(f"/api/v1/exports/{made['id']}/links").json()
        # Asked once while packing (does not count), opened once when ready; fetching the ZIP is no second opening.
        assert links[0]["opened_count"] == 1 and links[0]["status"] == "active"
        # The maker looking does not count.
        jule.get(f"/api/v1/x/{token}")
        assert jule.get(f"/api/v1/exports/{made['id']}/links").json()[0]["opened_count"] == 1
        again = jule.post(f"/api/v1/exports/{made['id']}/links/{links[0]['id']}/address").json()["url"]
        assert again.endswith(token)
        # The ZIP stays as long as the link.
        assert jule.get(f"/api/v1/exports/{made['id']}").json()["expires_at"] >= links[0]["until"]


def test_a_revoked_link_and_a_wrong_one_answer_alike(world: World, client: TestClient) -> None:
    made, token = linked(world)
    pack()
    with new_client(world.jule) as jule:
        link_id = jule.get(f"/api/v1/exports/{made['id']}/links").json()[0]["id"]
        assert jule.delete(f"/api/v1/exports/{made['id']}/links/{link_id}").status_code == 204
    with TestClient(client.app, base_url="http://testserver") as outsider:
        revoked = outsider.get(f"/api/v1/x/{token}")
        wrong = outsider.get("/api/v1/x/lnx_" + "a" * 43)
        assert revoked.status_code == wrong.status_code == 404 and revoked.json() == wrong.json()
        assert outsider.get(f"/api/v1/x/{token}/file").status_code == 404


def test_wrong_tokens_count_on_the_brake_of_links(world: World, client: TestClient) -> None:
    with TestClient(client.app, base_url="http://testserver") as outsider:
        codes = [outsider.get("/api/v1/x/lnx_" + str(i) * 43).status_code for i in range(25)]
    assert codes[0] == 404 and codes[-1] == 429


def test_the_link_ends_by_itself_and_with_the_switch(world: World, client: TestClient,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    _made, token = linked(world)
    pack()
    with TestClient(client.app, base_url="http://testserver") as outsider:
        with SessionLocal() as db:
            settings_service.save(db, {"links_allowed": False})
        assert outsider.get(f"/api/v1/x/{token}").status_code == 404
        with SessionLocal() as db:
            settings_service.save(db, {"links_allowed": True, "link_max_days": 7})
        later = datetime.now(UTC) + timedelta(days=8)
        monkeypatch.setattr(clock, "now", lambda: later)
        assert outsider.get(f"/api/v1/x/{token}").status_code == 404


def test_the_link_ends_when_its_maker_no_longer_sees_what_is_in_it(world: World, client: TestClient) -> None:
    made, token = linked(world)
    pack()
    with SessionLocal() as db:
        vaults.remove_member(db, world.operator.id, world.firma, world.jule.id)
    with TestClient(client.app, base_url="http://testserver") as outsider:
        assert outsider.get(f"/api/v1/x/{token}").status_code == 404
    with new_client(world.jule) as jule:
        assert jule.get(f"/api/v1/exports/{made['id']}/file").json()["detail"]["code"] == "export_outdated"
        assert jule.get(f"/api/v1/exports/{made['id']}/links").json()[0]["status"] == "ended"


def test_the_link_ends_with_a_blocked_maker(world: World, client: TestClient) -> None:
    _made, token = linked(world)
    pack()
    # One more, asked for but not packed yet: its link ends with the maker too.
    with new_client(world.jule) as jule:
        waiting = make(jule, world, link={"recipient": "Steuerbüro", "days": 3})
    with SessionLocal() as db:
        row = db.get(Account, world.jule.id)
        assert row is not None
        row.blocked_at = clock.now()
        db.commit()
    with TestClient(client.app, base_url="http://testserver") as outsider:
        assert outsider.get(f"/api/v1/x/{token}").status_code == 404
        assert outsider.get(f"/api/v1/x/{waiting['link']['token']}").status_code == 404


def test_links_need_the_operator_s_switch_and_a_length_within_the_limit(world: World) -> None:
    with new_client(world.jule) as jule:
        too_long = jule.post("/api/v1/exports", json=body(world, link={"recipient": "x", "days": 31}))
        assert too_long.json()["detail"]["code"] == "invalid_days"
        with SessionLocal() as db:
            settings_service.save(db, {"links_allowed": False})
        off = jule.post("/api/v1/exports", json=body(world, link={"recipient": "x", "days": 3}))
        assert off.json()["detail"]["code"] == "links_off"
        with SessionLocal() as db:
            assert db.scalar(select(Export.id)) is None


# --- Cleaning up -----------------------------------------------------------------------------------------------------


def test_old_exports_go_with_their_file_and_links(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    made, _token = linked(world)
    pack()
    with SessionLocal() as db:
        export = db.get(Export, made["id"])
        assert export is not None
        path = exports.folder() / export.file
    assert path.is_file()
    stray = exports.folder() / "999-stray.zip"
    stray.write_bytes(b"left over")
    with SessionLocal() as db:
        exports.sweep(db)
    assert path.is_file() and not stray.exists()
    later = datetime.now(UTC) + timedelta(days=15)
    monkeypatch.setattr(clock, "now", lambda: later)
    with SessionLocal() as db:
        assert exports.sweep(db) == 1
    assert not path.exists()
    with SessionLocal() as db:
        assert db.scalar(select(ExportLink.id)) is None


def test_deleting_an_export_removes_the_zip(world: World) -> None:
    with new_client(world.jule) as jule:
        made = make(jule, world)
        pack()
        with SessionLocal() as db:
            export = db.get(Export, made["id"])
            assert export is not None
            path = exports.folder() / export.file
        assert jule.delete(f"/api/v1/exports/{made['id']}").status_code == 204
        assert not path.exists() and jule.get(f"/api/v1/exports/{made['id']}").status_code == 404


def test_csv_cells_and_amounts() -> None:
    assert exports.safe_cell("=1+1") == "'=1+1" and exports.safe_cell("\tx") == "'\tx"
    assert exports.safe_cell("Stadtwerke") == "Stadtwerke"
    assert exports.amount_text(-1250, "de") == "-12,50" and exports.amount_text(5, "en") == "0.05"
    assert exports.amount_text(None, "de") == ""


# --- Every new route against every kind of caller --------------------------------------------------------------------

#: (method, path, body, what the owner of the export gets, what anybody else gets). ``{e}`` the export, ``{k}`` its link.
TABLE = [
    ("GET", "/api/v1/exports/preview", None, 200, 404),
    ("POST", "/api/v1/exports", "body", 201, 404),
    ("GET", "/api/v1/exports", None, 200, 200),
    ("GET", "/api/v1/exports/{e}", None, 200, 404),
    ("GET", "/api/v1/exports/{e}/file", None, 200, 404),
    ("GET", "/api/v1/exports/{e}/links", None, 200, 404),
    ("POST", "/api/v1/exports/{e}/links", {"recipient": "Steuerbüro", "days": 2}, 201, 404),
    ("POST", "/api/v1/exports/{e}/links/{k}/address", None, 200, 404),
    ("DELETE", "/api/v1/exports/{e}/links/{k}", None, 204, 404),
    ("DELETE", "/api/v1/exports/{e}", None, 204, 404),
]
PUBLIC = [("GET", "/api/v1/x/{token}"), ("GET", "/api/v1/x/{token}/file")]
OPERATOR_ONLY = [("GET", "/api/v1/settings/paperless"), ("PUT", "/api/v1/settings/paperless"),
                 ("DELETE", "/api/v1/settings/paperless"), ("POST", "/api/v1/settings/paperless/check"),
                 ("POST", "/api/v1/settings/paperless/start"), ("POST", "/api/v1/settings/paperless/stop"),
                 ("GET", "/api/v1/settings/paperless/skipped")]


def test_every_route_of_this_block_is_in_a_table() -> None:
    from .test_routes import api_routes

    routes = {(m, p) for m, p in api_routes() if p.startswith(("/api/v1/exports", "/api/v1/x/",
                                                               "/api/v1/settings/paperless"))}
    named = {(m, p.replace("{e}", "{export_id}").replace("{k}", "{link_id}")) for m, p, *_ in TABLE}
    assert routes == named | set(PUBLIC) | set(OPERATOR_ONLY)


def _fill(template: str, export_id: int, link_id: int) -> str:
    return template.replace("{e}", str(export_id)).replace("{k}", str(link_id))


@pytest.mark.parametrize("row", TABLE, ids=lambda r: f"{r[0]} {r[1]}")
def test_the_owner_may_and_a_stranger_sees_nothing(world: World, row: tuple[Any, ...]) -> None:
    method, template, payload, mine, theirs = row
    with new_client(world.jule) as jule:
        made, _token = linked(world)
        pack()
        link_id = jule.get(f"/api/v1/exports/{made['id']}/links").json()[0]["id"]
    sent = body(world) if payload == "body" else payload
    extra = {"json": sent} if sent is not None else {}
    path = _fill(template, made["id"], link_id)
    if template == "/api/v1/exports/preview":
        extra = {"params": {"vault_ids": [world.mine]}}
    with new_client(world.tom) as tom:
        answer = tom.request(method, path, **extra)
        assert answer.status_code == theirs, (path, answer.text)
    with new_client(world.jule) as jule:
        answer = jule.request(method, path, **extra)
        assert answer.status_code == mine, (path, answer.text)


@pytest.mark.parametrize("row", TABLE, ids=lambda r: f"{r[0]} {r[1]}")
def test_a_key_reaches_no_export(world: World, client: TestClient, row: tuple[Any, ...]) -> None:
    method, template, payload, _mine, _theirs = row
    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(world.jule) as jule:
        key = jule.post("/api/v1/api-keys", json={"name": "k", "scope": "read"}).json()["secret"]
        made = make(jule, world)
    with TestClient(client.app, base_url="http://testserver") as program:
        sent = body(world) if payload == "body" else payload
        extra = {"json": sent} if sent is not None else {}
        answer = program.request(method, _fill(template, made["id"], 1), headers={"Authorization": f"Bearer {key}"},
                                 **extra)
    assert answer.status_code in (401, 403), (template, answer.status_code)


def test_the_trash_and_documents_being_read_stay_out(world: World) -> None:
    from app.models import Document

    gone = add_document(world.mine, world.jule, "Im Papierkorb", date=date(2026, 7, 1))
    reading = add_document(world.mine, world.jule, "Wird gelesen", date=date(2026, 7, 2))
    with SessionLocal() as db:
        row = db.get(Document, reading)
        assert row is not None
        row.status = "processing"
        db.commit()
    with new_client(world.jule) as jule:
        assert jule.delete(f"/api/v1/documents/{gone}").status_code in (200, 204)
        made = make(jule, world)
        pack()
        names = " ".join(zip_of(jule, made["id"]).namelist())
    assert "Papierkorb" not in names and "Wird gelesen" not in names


# --- After the review --------------------------------------------------------------------------------------------------


def test_a_file_dated_before_1980_does_not_spoil_the_zip(world: World) -> None:
    import os

    from app.models import Version
    from app.services import storage

    with SessionLocal() as db:
        version = db.scalar(select(Version).where(Version.document_id == world.strom))
        assert version is not None
        os.utime(storage.safe_path(version.original_path), (0, 0))
    with new_client(world.jule) as jule:
        made = make(jule, world)
        pack()
        assert jule.get(f"/api/v1/exports/{made['id']}").json()["state"] == "ready"
        assert len(zip_of(jule, made["id"]).namelist()) == 3


def test_a_vault_name_cannot_lead_out_of_the_zip(world: World) -> None:
    evil = shared_vault("../../evil/\\x:CON", world.operator, (world.jule, "read"))
    add_document(evil, world.jule, "Drin", sender="..", date=date(2026, 2, 2))
    with new_client(world.jule) as jule:
        made = make(jule, world, vault_ids=[evil])
        pack()
        names = zip_of(jule, made["id"]).namelist()
    folder = names[0].split("/")[0]
    assert folder == "evil x CON" and all(".." not in name.split("/") for name in names)
    assert all(len(name.split("/")) == 4 for name in names if not name.endswith(".csv"))
    assert all("\\" not in name and ":" not in name and not name.startswith("/") for name in names)


def test_the_preview_counts_in_the_database_per_currency(world: World) -> None:
    for number in range(8):
        add_document(world.mine, world.jule, f"Beleg {number}", date=date(2026, 4, 1 + number), amount=100)
    with SessionLocal() as db:
        from app.models import Document, Version

        row = db.get(Document, world.rechnung)
        assert row is not None
        row.currency = "CHF"
        # One document has a searchable copy beside its original: with PDFs and originals it counts twice.
        version = db.scalar(select(Version).where(Version.document_id == world.strom))
        assert version is not None
        version.archive_path = "jule/2026/Stadtwerke Lindenau/copy (searchable).pdf"
        db.commit()
    with new_client(world.jule) as jule:
        found = jule.get("/api/v1/exports/preview", params={"vault_ids": [world.mine, world.firma],
                                                             "date_from": "2026-01-01", "date_to": "2026-12-31",
                                                             "original": "true"}).json()
    assert found["documents"] == 10
    assert found["totals"] == {"CHF": 41250, "EUR": 8400 + 800}
    # The other nine PDFs are their own searchable copy: in the ZIP, and in the size, once.
    assert found["size"] == 11 * len(PDF)
    assert len(found["sample"]) == 7 and found["sample"][-1] == "list.csv"


def test_a_link_ends_at_its_own_date(world: World, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    with new_client(world.jule) as jule:
        made = make(jule, world, link={"recipient": "Steuerbüro", "days": 2})
    pack()
    token = made["link"]["token"]
    later = datetime.now(UTC) + timedelta(days=3)
    monkeypatch.setattr(clock, "now", lambda: later)
    with TestClient(client.app, base_url="http://testserver") as outsider:
        assert outsider.get(f"/api/v1/x/{token}").status_code == 404


def test_a_link_made_after_packing_keeps_the_zip(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    with new_client(world.jule) as jule:
        made = make(jule, world)
        pack()
        link = jule.post(f"/api/v1/exports/{made['id']}/links", json={"recipient": "Steuerbüro", "days": 20}).json()
        assert jule.get(f"/api/v1/exports/{made['id']}").json()["expires_at"] >= link["until"]
    with SessionLocal() as db:
        export = db.get(Export, made["id"])
        assert export is not None
        path = exports.folder() / export.file
    later = datetime.now(UTC) + timedelta(days=10)
    monkeypatch.setattr(clock, "now", lambda: later)
    with SessionLocal() as db:
        assert exports.sweep(db) == 0
    assert path.is_file()


def test_the_log_never_holds_an_export_token() -> None:
    from app.services import logs

    token = "lnx_" + "Ab3" * 14
    assert token not in logs.redact(f"opened {token} from somewhere")
    bare = "Zx9" * 12
    assert bare not in logs.redact(f"GET /api/v1/x/{bare} -> 404") and bare not in logs.redact(f"GET /x/{bare}")


def test_a_link_lives_only_with_the_export_s_owner_as_its_maker(world: World, client: TestClient) -> None:
    _made, token = linked(world)
    pack()
    with SessionLocal() as db:
        link = db.scalar(select(ExportLink))
        assert link is not None
        link.created_by = world.tom.id
        db.commit()
    with TestClient(client.app, base_url="http://testserver") as outsider:
        assert outsider.get(f"/api/v1/x/{token}").status_code == 404
