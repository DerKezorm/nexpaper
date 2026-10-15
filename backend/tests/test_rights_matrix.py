"""Every route of vaults and documents against every kind of caller, from one table.

The table is checked against the list of routes the app has: a route added without a line here fails the first test, so
no new route escapes the check for the stranger, the reader, the device and the key.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient

from app.models import Account

from .conftest import make_account, new_client
from .papers import add_document, shared_vault
from .test_routes import api_routes

PREFIXES = ("/api/v1/vaults", "/api/v1/documents", "/api/v1/links", "/api/v1/senders", "/api/v1/tags", "/api/v1/kinds",
            "/api/v1/people", "/api/v1/changes", "/api/v1/sharing", "/api/v1/order",
            "/api/v1/inbox", "/api/v1/counts",
            "/api/v1/search", "/api/v1/deadlines",
            "/api/v1/keeping")


class Row(NamedTuple):
    method: str
    template: str
    body: dict[str, Any] | None
    #: What the caller needs: read, edit, manage (in the vault), operator, browser (any signed-in browser), `self`, or
    #: `copy` (the person who made the link or a manager; everybody else gets 404 as for a link that does not exist).
    need: str
    #: What a stranger (no right at all) gets.
    stranger: int


# {d} document, {v} the shared vault, {n} a note, {l} a link, {u} the person to share with / add, {s} a sender,
# {t} a tag, {k} a kind, {x} the number of a version (1), {g} a page (1), {w} the kind of a date (due). The routes that bring files in have a table of
# their own (``test_rights_uploads.py``).
TABLE = [
    Row("GET", "/api/v1/vaults", None, "any", 200),
    Row("GET", "/api/v1/vaults/{v}", None, "read", 404),
    Row("POST", "/api/v1/vaults", {"name": "New one"}, "operator", 403),
    Row("PATCH", "/api/v1/vaults/{v}", {"name": "Renamed"}, "manage-browser", 404),
    Row("DELETE", "/api/v1/vaults/{v}", None, "manage-browser", 404),
    Row("PUT", "/api/v1/vaults/{v}/members", {"members": []}, "manage-browser", 404),
    Row("PUT", "/api/v1/vaults/{v}/members/{u}", {"right": "read"}, "manage-browser", 404),
    Row("DELETE", "/api/v1/vaults/{v}/members/{u}", None, "manage-browser", 404),
    Row("POST", "/api/v1/vaults/{v}/leave", None, "read-browser", 404),
    Row("GET", "/api/v1/people", None, "any", 200),
    Row("GET", "/api/v1/documents", None, "any", 200),
    Row("GET", "/api/v1/documents/{d}", None, "read", 404),
    Row("PATCH", "/api/v1/documents/{d}", {"title": "Changed"}, "edit", 404),
    Row("DELETE", "/api/v1/documents/{d}", None, "edit", 404),
    Row("POST", "/api/v1/documents/{d}/restore", None, "edit", 404),
    Row("POST", "/api/v1/documents/{d}/move", {"vault_id": 0}, "edit", 404),
    Row("GET", "/api/v1/documents/{d}/notes", None, "read", 404),
    Row("POST", "/api/v1/documents/{d}/notes", {"text": "A note"}, "read-write", 404),
    Row("PUT", "/api/v1/documents/{d}/notes/{n}", {"text": "Changed"}, "own-note", 404),
    Row("DELETE", "/api/v1/documents/{d}/notes/{n}", None, "own-note", 404),
    Row("GET", "/api/v1/documents/{d}/events", None, "read", 404),
    Row("GET", "/api/v1/documents/{d}/versions", None, "read", 404),
    Row("GET", "/api/v1/documents/{d}/versions/{x}/file", None, "read", 404),
    Row("GET", "/api/v1/documents/{d}/versions/{x}/archive", None, "read", 404),
    Row("GET", "/api/v1/documents/{d}/versions/{x}/preview", None, "read", 404),
    Row("GET", "/api/v1/documents/{d}/versions/{x}/pages/{g}", None, "read", 404),
    Row("POST", "/api/v1/documents/{d}/retry", None, "edit", 404),
    Row("GET", "/api/v1/documents/{d}/shares", None, "manage", 404),
    Row("PUT", "/api/v1/documents/{d}/shares/{u}", {"right": "read"}, "manage", 404),
    Row("DELETE", "/api/v1/documents/{d}/shares/{u}", None, "manage", 404),
    Row("GET", "/api/v1/documents/{d}/links", None, "manage", 404),
    Row("POST", "/api/v1/documents/{d}/links", {"recipient": "x", "days": 1}, "manage", 404),
    Row("DELETE", "/api/v1/documents/{d}/links/{l}", None, "manage", 404),
    Row("POST", "/api/v1/documents/{d}/links/{l}/address", None, "copy", 404),
    Row("GET", "/api/v1/links", None, "any", 200),
    Row("GET", "/api/v1/sharing", None, "any", 200),
    Row("GET", "/api/v1/sharing/overview", None, "operator", 403),
    Row("GET", "/api/v1/senders", None, "any", 200),
    # A rename onto a name the vault already has joins the two: that needs `manage` (`test_catalog.py`, `409 name_taken`
    # for `edit`), and so does deleting a sender that documents use (`403` with `force`); the rows here use a free name.
    Row("PATCH", "/api/v1/senders/{s}", {"name": "Renamed sender"}, "edit-all", 404),
    Row("DELETE", "/api/v1/senders/{s}", None, "edit-all", 404),
    Row("GET", "/api/v1/tags", None, "any", 200),
    Row("PATCH", "/api/v1/tags/{t}", {"name": "renamed"}, "edit-all", 404),
    Row("DELETE", "/api/v1/tags/{t}", None, "edit-all", 404),
    Row("GET", "/api/v1/kinds", None, "any", 200),
    Row("POST", "/api/v1/kinds", {"name": "Brand new"}, "operator", 403),
    Row("PATCH", "/api/v1/kinds/{k}", {"name": "Renamed kind"}, "operator", 403),
    Row("DELETE", "/api/v1/kinds/{k}", None, "operator", 403),
    Row("GET", "/api/v1/order/senders", None, "any", 200),
    Row("GET", "/api/v1/order/tags", None, "any", 200),
    Row("GET", "/api/v1/order/kinds", None, "any", 200),
    # Merging needs `manage` in the vault (the editor may rename, not merge); the body names no entry, so a caller who
    # may merge gets 404 for the missing target, never 403.
    Row("POST", "/api/v1/senders/{s}/merge", {"into": 0}, "manage", 404),
    Row("POST", "/api/v1/tags/{t}/merge", {"into": 0}, "manage", 404),
    Row("POST", "/api/v1/kinds/{k}/merge", {"into": 0}, "operator", 403),
    # The inbox shows only what the caller may change; filing names every document it could not file.
    Row("GET", "/api/v1/inbox", None, "any", 200),
    Row("GET", "/api/v1/counts", None, "any", 200),
    Row("POST", "/api/v1/inbox/file", {"ids": [2**31 - 1]}, "any", 200),
    Row("GET", "/api/v1/changes", None, "any", 200),
    Row("GET", "/api/v1/documents/{d}/origin", None, "read", 404),
    Row("GET", "/api/v1/search", None, "any", 200),
    # The start of the archive: counts only what the caller may see (``test_search_pages.py``).
    Row("GET", "/api/v1/search/overview", None, "any", 200),
    Row("GET", "/api/v1/documents/{d}/versions/{x}/text", None, "read", 404),
    # Deleting for good from the trash (B4): a manager of the vault, or the owner while they may change it (the editor
    # owns this one), from a signed-in browser only; the document is not in the trash here, so who may gets 409.
    Row("POST", "/api/v1/documents/{d}/purge", None, "edit-browser", 404),
    # Sorting in (B6): the e-invoice is read like the file (this document carries none: 404 for everybody, the rights
    # come first all the same, ``test_einvoices.py`` has the ones that do); a rule from a document needs ``manage`` in
    # the vault it arrived in.
    Row("GET", "/api/v1/documents/{d}/einvoice", None, "read", 404),
    Row("GET", "/api/v1/documents/{d}/versions/{x}/einvoice", None, "read", 404),
    Row("POST", "/api/v1/documents/{d}/rule", {"tags": ["regel"]}, "manage", 404),
    # The page tools (B5).
    Row("POST", "/api/v1/documents/{d}/pages", {"base_version": 1, "pages": [{"page": 1, "turn": 0}]}, "edit", 404),
    Row("POST", "/api/v1/documents/{d}/merge", {"base_version": 1, "others": [{"id": 2**31 - 1, "base_version": 1}]},
        "edit", 404),
    Row("POST", "/api/v1/documents/{d}/split",
        {"base_version": 1, "parts": [{"pages": [{"page": 1}]}, {"pages": [{"page": 1}]}]}, "edit", 404),
    Row("GET", "/api/v1/documents/{d}/separators", None, "read", 404),
    Row("DELETE", "/api/v1/documents/{d}/separators", None, "edit", 404),
    Row("POST", "/api/v1/documents/{d}/versions/{x}/restore", {"base_version": 1}, "edit", 404),
    Row("POST", "/api/v1/documents/{d}/versions", None, "edit", 404),
    Row("DELETE", "/api/v1/documents/{d}/versions/{x}", None, "edit", 404),
    # Keeping (F3): the keeping time of a kind of the server is the operator's (``test_keeping.py`` has the vault's
    # kinds, edit against manage); "may go" and many documents into the trash look at each document on its own.
    Row("POST", "/api/v1/kinds/{k}/keeping/preview", {"years": 10}, "operator", 403),
    Row("PUT", "/api/v1/kinds/{k}/keeping", {"years": 10, "existing": True}, "operator", 403),
    Row("GET", "/api/v1/keeping", None, "any", 200),
    Row("POST", "/api/v1/documents/trash", {"ids": [2**31 - 1]}, "any", 200),
    # Deadlines (F1): only the deadlines of what the caller may change; done and later need `edit` (this document has
    # no due date, so whoever may gets 404 `no_such_date`, ``test_deadlines.py`` has the ones that do).
    Row("GET", "/api/v1/deadlines", None, "any", 200),
    Row("POST", "/api/v1/documents/{d}/dates/{w}/done", None, "edit", 404),
    Row("DELETE", "/api/v1/documents/{d}/dates/{w}/done", None, "edit", 404),
    Row("PUT", "/api/v1/documents/{d}/dates/{w}/snooze", {"days": 1}, "edit", 404),
    Row("DELETE", "/api/v1/documents/{d}/dates/{w}/snooze", None, "edit", 404),
]


def test_every_route_of_vaults_and_documents_is_in_the_table() -> None:
    from .test_rights_uploads import PATHS as UPLOAD_ROUTES

    routes = {(m, p) for m, p in api_routes() if p.startswith(PREFIXES)} - UPLOAD_ROUTES
    # Normalise the parameter names of the table to those of the routes.
    names = {"{d}": "{document_id}", "{v}": "{vault_id}", "{n}": "{note_id}", "{l}": "{link_id}", "{u}": "{user_id}",
             "{s}": "{sender_id}", "{t}": "{tag_id}", "{k}": "{kind_id}", "{x}": "{number}", "{g}": "{page}",
             "{w}": "{kind}"}
    table = set()
    for row in TABLE:
        template = row.template
        for short, long in names.items():
            template = template.replace(short, long)
        table.add((row.method, template))
    assert routes == table, f"missing in the table: {sorted(routes - table)}; not routes: {sorted(table - routes)}"


class World:
    """A shared vault with one document, one note, one link, a sender and a tag, and people of every right."""

    def __init__(self, operator: Account) -> None:
        self.operator = operator
        self.manager = make_account("manager")
        self.editor = make_account("editor")
        self.reader = make_account("reader")
        self.stranger = make_account("stranger")
        self.target = make_account("target")
        self.vault = shared_vault("Household", self.manager, (self.editor, "edit"), (self.reader, "read"),
                                  (operator, "manage"))
        self.other = shared_vault("Second", self.manager, (self.editor, "edit"), (operator, "edit"))
        self.document = add_document(self.vault, self.editor, "Matrix", sender="Matrix Sender", tags=["matrix"])

    def ids(self, client: TestClient) -> dict[str, int]:
        note = client.post(f"/api/v1/documents/{self.document}/notes", json={"text": "mine"}).json()["id"]
        link = client.post(f"/api/v1/documents/{self.document}/links", json={"recipient": "r", "days": 1}).json()["id"]
        shown = client.get(f"/api/v1/documents/{self.document}").json()
        sender = client.get("/api/v1/senders").json()[0]["items"][0]["id"]
        tag = client.get("/api/v1/tags").json()[0]["items"][0]["id"]
        kind = client.get("/api/v1/kinds").json()[0]["id"]
        return {"d": self.document, "v": self.vault, "n": note, "l": link, "u": self.target.id, "s": sender, "t": tag,
                "k": kind, "other": self.other, "title": shown["title"]}


def fill(template: str, ids: dict[str, int]) -> str:
    out = template.replace("{x}", "1").replace("{g}", "1").replace("{w}", "due")
    for key in ("d", "v", "n", "l", "u", "s", "t", "k"):
        out = out.replace("{" + key + "}", str(ids[key]))
    return out


def body_of(row: Row, ids: dict[str, int]) -> dict[str, Any] | None:
    if row.body is None:
        return None
    return {k: (ids["other"] if k == "vault_id" else v) for k, v in row.body.items()}


def call(who: TestClient, row: Row, ids: dict[str, int], **kwargs: Any) -> int:
    body = body_of(row, ids)
    extra = {"json": body} if body is not None else {}
    return who.request(row.method, fill(row.template, ids), **extra, **kwargs).status_code


@pytest.fixture
def world(client: TestClient, operator: Account) -> tuple[World, dict[str, int]]:
    built = World(operator)
    # The ids are made by the editor (owner of the document) acting as a manager would: use the manager's browser.
    with new_client(built.manager) as manager:
        ids = built.ids(manager)
    return built, ids


@pytest.mark.parametrize("row", TABLE, ids=lambda r: f"{r.method} {r.template}")
def test_the_stranger_sees_nothing(world: tuple[World, dict[str, int]], row: Row) -> None:
    built, ids = world
    with new_client(built.stranger) as stranger:
        status = call(stranger, row, ids)
    assert status == row.stranger, (row, status)


@pytest.mark.parametrize("row", [r for r in TABLE if r.need in ("edit", "manage", "manage-browser", "edit-all", "copy",
                                                                 "edit-browser")],
                         ids=lambda r: f"{r.method} {r.template}")
def test_the_reader_may_not_change(world: tuple[World, dict[str, int]], row: Row) -> None:
    built, ids = world
    with new_client(built.reader) as reader:
        status = call(reader, row, ids)
    assert status == (404 if row.need == "copy" else 403), (row, status)
    # And nothing changed.
    with new_client(built.manager) as manager:
        assert manager.get(f"/api/v1/documents/{ids['d']}").json()["title"] == "Matrix"
        assert manager.get(f"/api/v1/vaults/{ids['v']}").json()["name"] == "Household"


@pytest.mark.parametrize("row", [r for r in TABLE if r.need in ("manage", "manage-browser", "copy")],
                         ids=lambda r: f"{r.method} {r.template}")
def test_the_editor_may_not_do_what_needs_manage(world: tuple[World, dict[str, int]], row: Row) -> None:
    built, ids = world
    with new_client(built.editor) as editor:
        status = call(editor, row, ids)
    # The editor owns the document, so sharing and links stay theirs; only the vault's own affairs are refused. The
    # address of a link the manager made is not theirs to copy: it answers as if there were no such link.
    owner_may = row.template.startswith("/api/v1/documents/{d}/") and ("shares" in row.template or "links" in row.template)
    if row.need == "copy":
        assert status == 404, (row, status)
    elif owner_may:
        assert status != 403, (row, status)
    else:
        assert status == 403, (row, status)


@pytest.mark.parametrize("row", [r for r in TABLE if r.method == "GET"], ids=lambda r: r.template)
def test_a_key_reads_what_the_browser_reads(world: tuple[World, dict[str, int]], row: Row) -> None:
    built, ids = world
    from app.db import SessionLocal
    from app.services import settings_service

    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(built.manager) as manager:
        secret = manager.post("/api/v1/api-keys", json={"name": "k", "scope": "read"}).json()["secret"]
        browser = call(manager, row, ids)
    with TestClient(manager.app, base_url="http://testserver") as program:
        keyed = call(program, row, ids, headers={"Authorization": f"Bearer {secret}"})
        if row.need in ("operator", "manage"):
            assert keyed == browser or keyed in (403, 404), (row, keyed, browser)
        else:
            assert keyed == browser, (row, keyed, browser)
        wrong = call(program, row, ids, headers={"Authorization": "Bearer npk_" + "z" * 43})
        assert wrong == (403 if row.need == "operator" else 401), (row, wrong)


@pytest.mark.parametrize("row", [r for r in TABLE if r.method != "GET"], ids=lambda r: f"{r.method} {r.template}")
def test_a_key_never_changes_anything(world: tuple[World, dict[str, int]], row: Row) -> None:
    built, ids = world
    from app.db import SessionLocal
    from app.services import settings_service

    with SessionLocal() as db:
        settings_service.save(db, {"api_keys_allowed": True})
    with new_client(built.manager) as manager:
        secret = manager.post("/api/v1/api-keys", json={"name": "k", "scope": "read"}).json()["secret"]
    with TestClient(manager.app, base_url="http://testserver") as program:
        status = call(program, row, ids, headers={"Authorization": f"Bearer {secret}"})
    assert status in (401, 403), (row, status)
    with new_client(built.manager) as manager:
        assert manager.get(f"/api/v1/documents/{ids['d']}").json()["title"] == "Matrix"


@pytest.mark.parametrize("row", [r for r in TABLE if "browser" in r.need or r.need == "operator"],
                         ids=lambda r: f"{r.method} {r.template}")
def test_a_device_does_not_do_what_needs_a_browser(world: tuple[World, dict[str, int]], row: Row) -> None:
    built, ids = world
    with new_client(built.manager) as manager:
        token = manager.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    with TestClient(manager.app, base_url="http://testserver") as device:
        status = call(device, row, ids, headers={"Authorization": f"Bearer {token}"})
    assert status == 403, (row, status)


@pytest.mark.parametrize("row", [r for r in TABLE if r.need in ("read", "edit", "read-write", "own-note", "any", "manage",
                                                                 "copy")
                                 and r.method in ("GET", "PATCH", "POST", "PUT", "DELETE")],
                         ids=lambda r: f"{r.method} {r.template}")
def test_a_device_acts_with_the_rights_of_its_account(world: tuple[World, dict[str, int]], row: Row) -> None:
    built, ids = world
    for who, may in ((built.manager, True), (built.reader, row.need in ("read", "any", "read-write"))):
        with new_client(who) as session:
            token = session.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
        with TestClient(session.app, base_url="http://testserver") as device:
            status = call(device, row, ids, headers={"Authorization": f"Bearer {token}"})
        if may:
            assert status != 403 and status != 401, (who.name, row, status)  # type: ignore[attr-defined]
        else:
            assert status in (403, 404), (who.name, row, status)  # type: ignore[attr-defined]
