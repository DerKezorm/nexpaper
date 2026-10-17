"""Every route that brings files in against every kind of caller, from one table, checked against the list of routes the
app has (a route added without a line here fails the first test)."""

from __future__ import annotations

from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Account

from . import files
from .conftest import TAB, make_account, new_client
from .intake import device_token, sha, upload_key
from .papers import PDF, shared_vault
from .test_routes import READ_ROUTES, TOKEN_ROUTES, api_routes

DATA = files.make_image("png", size=(220, 300))


class Row(NamedTuple):
    method: str
    template: str
    #: Who may use it: ``vault`` (the caller needs the right to add in the vault they name) or ``owner`` (the upload is
    #: the caller's own; everybody else gets 404).
    need: str


# {u} the id of an upload of the owner, {v} the shared vault.
TABLE = [
    Row("POST", "/api/v1/documents", "vault"),
    Row("POST", "/api/v1/uploads", "vault"),
    Row("GET", "/api/v1/uploads", "list"),
    Row("GET", "/api/v1/uploads/{u}", "owner"),
    Row("PUT", "/api/v1/uploads/{u}", "owner"),
    Row("POST", "/api/v1/uploads/{u}/finish", "owner"),
    Row("DELETE", "/api/v1/uploads/{u}", "owner"),
]
PATHS = {(row.method, row.template.replace("{u}", "{upload_id}")) for row in TABLE}


def test_every_route_that_brings_files_in_is_in_the_table() -> None:
    found = {(m, p) for m, p in api_routes() if p.startswith("/api/v1/uploads") or (m, p) == ("POST", "/api/v1/documents")}
    assert found == PATHS, f"missing: {sorted(found - PATHS)}; not routes: {sorted(PATHS - found)}"


def test_the_routes_that_take_files_are_the_ones_a_device_and_a_key_for_uploading_reach() -> None:
    from app import deps

    from .test_routes import routes_asking_for

    assert set(routes_asking_for(deps.require_uploader)) == PATHS
    assert PATHS <= TOKEN_ROUTES
    assert not PATHS & READ_ROUTES


class World:
    def __init__(self) -> None:
        self.owner = make_account("owner")
        self.other = make_account("other")
        self.reader = make_account("reader")
        self.vault = shared_vault("Household", make_account("boss"), (self.owner, "edit"), (self.reader, "read"))
        with new_client(self.owner) as browser:
            started = browser.post("/api/v1/uploads", json={"filename": "a.png", "size": len(DATA), "sha256": sha(DATA)})
            self.upload = started.json()["upload"]["id"]


@pytest.fixture
def world(client: TestClient, operator: Account) -> World:
    return World()


def call(who: TestClient, row: Row, world: World, vault: int | None = None, **kwargs: Any) -> int:
    path = row.template.replace("{u}", world.upload)
    query = f"?vault_id={vault}" if vault is not None else ""
    if row.method == "PUT":
        return who.put(path + "?offset=0", content=DATA[:50], **kwargs).status_code
    if row.template == "/api/v1/documents":
        return who.post(path + query, files=[("file", ("n.pdf", files.make_pdf(["n"]), "application/pdf"))], **kwargs).status_code
    if row.template == "/api/v1/uploads":
        body = {"filename": "z.png", "size": 9, "sha256": "e" * 64}
        if vault is not None:
            body["vault_id"] = vault  # type: ignore[assignment]
        return who.post(path, json=body, **kwargs).status_code
    return who.request(row.method, path, **kwargs).status_code


@pytest.mark.parametrize("row", TABLE, ids=lambda r: f"{r.method} {r.template}")
def test_nobody_without_a_sign_in_gets_in(world: World, row: Row) -> None:
    with TestClient(app, base_url="http://testserver", headers=TAB) as nobody:
        assert call(nobody, row, world) == 401


@pytest.mark.parametrize("row", [r for r in TABLE if r.need == "owner"], ids=lambda r: f"{r.method} {r.template}")
def test_an_upload_belongs_to_the_account_that_made_it(world: World, row: Row) -> None:
    for who in (world.other, world.reader):
        with new_client(who) as stranger:
            assert call(stranger, row, world) == 404, (who.name, row)
    # The operator of the server is a stranger here too: nobody reaches the files of somebody else.
    with new_client(world.owner) as owner:
        assert call(owner, row, world) in (200, 204, 409)


@pytest.mark.parametrize("row", [r for r in TABLE if r.need == "vault"], ids=lambda r: f"{r.method} {r.template}")
def test_a_vault_takes_files_from_those_who_may_add_there_and_says_nothing_to_the_rest(world: World, row: Row) -> None:
    with new_client(world.owner) as owner:
        assert call(owner, row, world, vault=world.vault) in (200, 201)
    with new_client(world.reader) as reader:
        assert call(reader, row, world, vault=world.vault) == 403
    with new_client(world.other) as stranger:
        assert call(stranger, row, world, vault=world.vault) == 404
        assert call(stranger, row, world, vault=987654) == 404


@pytest.mark.parametrize("row", TABLE, ids=lambda r: f"{r.method} {r.template}")
def test_a_device_does_what_its_account_does(world: World, row: Row) -> None:
    with new_client(world.owner) as browser:
        token = device_token(browser)
    with TestClient(app, base_url="http://testserver") as device:
        status = call(device, row, world, headers={"Authorization": f"Bearer {token}"})
    assert status in (200, 201, 204, 409), (row, status)
    with new_client(world.other) as other:
        stranger_token = device_token(other)
    if row.need == "owner":
        with TestClient(app, base_url="http://testserver") as device:
            assert call(device, row, world, headers={"Authorization": f"Bearer {stranger_token}"}) == 404


@pytest.mark.parametrize("row", TABLE, ids=lambda r: f"{r.method} {r.template}")
def test_a_key_for_reading_does_not_upload_and_a_key_for_uploading_does(world: World, row: Row) -> None:
    read_key = upload_key(world.owner, "read")
    write_key = upload_key(world.owner, "upload")
    with TestClient(app, base_url="http://testserver") as program:
        refused = call(program, row, world, headers={"Authorization": f"Bearer {read_key}"})
        assert refused == 403, (row, refused)
        if "{u}" in row.template:
            # A key reaches only the uploads it started (a finding of the review): the browser's upload is none of its business.
            assert call(program, row, world, headers={"Authorization": f"Bearer {write_key}"}) == 404, row
            started = program.post("/api/v1/uploads", headers={"Authorization": f"Bearer {write_key}"},
                                   json={"filename": "k.png", "size": len(DATA), "sha256": sha(DATA)})
            assert started.status_code == 201, started.text
            world.upload = started.json()["upload"]["id"]
        allowed = call(program, row, world, headers={"Authorization": f"Bearer {write_key}"})
        assert allowed in (200, 201, 204, 409), (row, allowed)
        wrong = call(program, row, world, headers={"Authorization": "Bearer npk_" + "z" * 43})
        assert wrong == 401


def test_keys_that_the_operator_has_not_switched_on_are_no_way_in(world: World) -> None:
    key = upload_key(world.owner, "upload")
    from app.db import SessionLocal
    from app.services import settings_service

    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": False})
    with TestClient(app, base_url="http://testserver") as program:
        for row in TABLE:
            assert call(program, row, world, headers={"Authorization": f"Bearer {key}"}) == 401, row


def test_a_key_for_uploading_reads_nothing_and_changes_nothing_else(world: World) -> None:
    write_key = upload_key(world.owner, "upload")
    from .intake import upload_one

    with new_client(world.owner) as browser:
        made = upload_one(browser, "a.pdf", PDF)
    from .test_rights_matrix import fill

    ids = {"d": made["id"], "v": world.vault, "n": 1, "l": 1, "u": world.other.id, "s": 1, "t": 1, "k": 1}
    with TestClient(app, base_url="http://testserver") as program:
        headers = {"Authorization": f"Bearer {write_key}"}
        for method, path in sorted(READ_ROUTES):
            status = program.request(method, fill(_concrete(path), ids), headers=headers).status_code
            assert status == 403, (method, path, status)
        for method, path in sorted(TOKEN_ROUTES - PATHS):
            status = program.request(method, fill(_concrete(path), ids), headers=headers,
                                     json={} if method in ("POST", "PUT", "PATCH") else None).status_code
            assert status in (401, 403), (method, path, status)


def _concrete(path: str) -> str:
    import re

    names = {"document_id": "{d}", "vault_id": "{v}", "note_id": "{n}", "link_id": "{l}", "user_id": "{u}",
             "sender_id": "{s}", "tag_id": "{t}", "kind_id": "{k}", "number": "1", "page": "1", "device_id": "1"}
    return re.sub(r"\{(\w+)\}", lambda m: names.get(m.group(1), "1"), path)


def test_the_list_of_open_uploads_is_the_own_one_and_nobody_elses(world: World) -> None:
    with new_client(world.owner) as owner:
        listed = owner.get("/api/v1/uploads").json()
        assert [u["id"] for u in listed] == [world.upload]
    for who in (world.other, world.reader):
        with new_client(who) as stranger:
            assert stranger.get("/api/v1/uploads").json() == []
    # A key for uploading lists the uploads it started and no other, a key for reading does not list
    # at all (403), nobody without a sign-in does (401).
    write_key = upload_key(world.owner, "upload")
    read_key = upload_key(world.owner, "read")
    with TestClient(app, base_url="http://testserver") as program:
        assert program.get("/api/v1/uploads", headers={"Authorization": f"Bearer {write_key}"}).json() == []
        own = program.post("/api/v1/uploads", headers={"Authorization": f"Bearer {write_key}"},
                           json={"filename": "k.png", "size": len(DATA), "sha256": sha(DATA)}).json()["upload"]["id"]
        assert [u["id"] for u in program.get("/api/v1/uploads", headers={"Authorization": f"Bearer {write_key}"}).json()] == [own]
        assert program.get("/api/v1/uploads", headers={"Authorization": f"Bearer {read_key}"}).status_code == 403
        assert program.get("/api/v1/uploads").status_code == 401
