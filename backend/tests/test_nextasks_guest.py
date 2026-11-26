"""nexpaper as the guest of nextasks (Bauplan V19, AUFTRAG Runde 2 Teil B, a draft in its smallest form): "Aufgabe in
nextasks" on a document's page makes a task over a connection made by a click, with the document's title and its page
as the link back; the same document again finds the task made first (``external_ref``); the card learns how it went
(``nexverbinden.reached``); a 401 is asked once more with a renewed access.

Through the module's contract world: the connection is made the whole way (start in nexpaper, consent in the partner,
return), and the partner is the module's reference app as nextasks with two routes of nextasks' ``/api/v1`` added
(``GET /lists`` for ``tasks.read``, ``POST /tasks`` for ``tasks.write``, refused 403 ``purpose_missing`` otherwise),
checked with the module's own ``authenticate`` and ``require`` as nextasks checks them."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent / "nexverbinden"))

import verbinden_contract as contract

from .nexverbinden_adapter import Adapter

LISTS = [
    {"id": "list-home", "space_id": "s1", "space_name": "Zuhause", "name": "Haushalt", "writable": True},
    {"id": "list-garden", "space_id": "s1", "space_name": "Zuhause", "name": "Garten", "writable": True},
]


class FakeNextasks:
    """What the partner keeps of nextasks: tasks per account with ``external_ref`` (one task per key, as nextasks),
    the requests that came, and a switch to answer 401 as a nextasks that ended the connection."""

    def __init__(self, world: Any) -> None:
        self.pkg = world.pkg
        self.partner = world.partner
        self.tasks: list[dict[str, Any]] = []
        self.seen: list[tuple[str, str]] = []
        self.ended = False
        api = world.partner.api
        api.add_api_route("/api/v1/lists", self.lists, methods=["GET"])
        api.add_api_route("/api/v1/tasks", self.make, methods=["POST"])

    def _caller(self, request: Request, purpose: str) -> Any:
        self.seen.append((request.method, request.url.path))
        header = request.headers.get("authorization", "")
        given = header[7:].strip() if header[:7].lower() == "bearer " else ""
        try:
            if self.ended:
                raise self.pkg.Refused("token_invalid")
            found = self.pkg.authenticate(self.partner.store, self.partner.config, given, datetime.now(UTC))
            self.pkg.require(found, purpose)
        except self.pkg.Refused as refusal:
            raise HTTPException(status_code=refusal.status, detail=refusal.as_dict()) from None
        return found

    def lists(self, request: Request) -> dict[str, Any]:
        self._caller(request, "tasks.read")
        return {"lists": LISTS}

    async def make(self, request: Request) -> Any:
        from fastapi.responses import JSONResponse

        found = self._caller(request, "tasks.write")
        body = await request.json()
        for task in self.tasks:
            if task["account"] == found.account_id and task["external_ref"] == body.get("external_ref"):
                return JSONResponse(task["out"], status_code=200)
        out = {"id": f"task-{len(self.tasks) + 1}", "title": body["title"], "list_id": body["list_id"],
               "url": body.get("url"), "link": f"https://nextasks.example.com/task/{len(self.tasks) + 1}"}
        self.tasks.append({"account": found.account_id, "external_ref": body.get("external_ref"), "out": out})
        return JSONResponse(out, status_code=201)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[Any]:
    adapter = Adapter()
    adapter.partner = "nextasks"
    yield from contract.world(contract.package(adapter), adapter, tmp_path)


@pytest.fixture
def nextasks(world: Any) -> FakeNextasks:
    return FakeNextasks(world)


def _document(title: str) -> int:
    from app.db import SessionLocal
    from app.models import Document

    with SessionLocal() as db:
        found = db.scalar(select(Document.id).where(Document.title == title))
    assert found is not None
    return int(found)


def _browser(world: Any) -> Any:
    return world.app.client("owner")


def test_a_task_from_a_document_over_the_click_connection(world: Any, nextasks: FakeNextasks) -> None:
    browser = _browser(world)
    assert browser.get("/api/v1/nextasks").json() == {"usable": False}
    assert world.connect("app").status_code == 200
    assert browser.get("/api/v1/nextasks").json() == {"usable": True}
    found = browser.get("/api/v1/nextasks/lists")
    assert found.status_code == 200, found.text
    assert [item["id"] for item in found.json()["lists"]] == ["list-home", "list-garden"]
    assert found.json()["last_list_id"] is None

    document = _document("Electricity")
    made = browser.post(f"/api/v1/documents/{document}/nextasks", json={"list_id": "list-garden"})
    assert made.status_code == 201, made.text
    assert made.json()["created"] is True and made.json()["title"] == "Electricity"
    assert made.json()["link"] == "https://nextasks.example.com/task/1"
    sent = nextasks.tasks[0]
    assert sent["out"]["url"] == f"https://paper.example.com/dokument/{document}"
    assert sent["out"]["list_id"] == "list-garden"
    assert sent["external_ref"] == f"nexpaper:document:{document}"
    # The list used last is chosen first the next time.
    assert browser.get("/api/v1/nextasks/lists").json()["last_list_id"] == "list-garden"
    assert world.card("app")["state"] == "connected"


def test_the_same_document_finds_its_first_task(world: Any, nextasks: FakeNextasks) -> None:
    assert world.connect("app").status_code == 200
    browser = _browser(world)
    document = _document("Electricity")
    first = browser.post(f"/api/v1/documents/{document}/nextasks", json={"list_id": "list-home"})
    again = browser.post(f"/api/v1/documents/{document}/nextasks", json={"list_id": "list-garden"})
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["task_id"] == first.json()["task_id"] and again.json()["created"] is False
    other = browser.post(f"/api/v1/documents/{_document('Rent')}/nextasks", json={"list_id": "list-home"})
    assert other.status_code == 201 and other.json()["task_id"] != first.json()["task_id"]
    assert len(nextasks.tasks) == 2


def test_a_401_is_asked_once_more_with_a_renewed_access(world: Any, nextasks: FakeNextasks) -> None:
    assert world.connect("app").status_code == 200
    # What nextasks gave nexpaper ends before nexpaper thinks so: the first answer is 401.
    world.expire_partner_issued()
    made = _browser(world).post(f"/api/v1/documents/{_document('Electricity')}/nextasks", json={"list_id": "list-home"})
    assert made.status_code == 201, made.text
    assert [path for method, path in nextasks.seen if method == "POST"] == ["/api/v1/tasks", "/api/v1/tasks"]
    assert world.card("app")["state"] == "connected"


def test_ended_in_nextasks_says_so_and_the_button_goes(world: Any, nextasks: FakeNextasks) -> None:
    assert world.connect("app").status_code == 200
    nextasks.ended = True
    browser = _browser(world)
    made = browser.post(f"/api/v1/documents/{_document('Electricity')}/nextasks", json={"list_id": "list-home"})
    assert made.status_code == 409 and made.json()["detail"]["code"] == "nextasks_disconnected"
    # Asked twice (once renewed), then the card says "Getrennt".
    assert len([path for method, path in nextasks.seen if method == "POST"]) == 2
    assert world.card("app")["state"] == "refused"
    assert browser.get("/api/v1/nextasks").json() == {"usable": False}
    assert nextasks.tasks == []


def test_nextasks_away_is_unreachable_on_the_card(world: Any, nextasks: FakeNextasks) -> None:
    assert world.connect("app").status_code == 200
    world.down.add(world.host(world.partner.base))
    browser = _browser(world)
    found = browser.get("/api/v1/nextasks/lists")
    assert found.status_code == 502 and found.json()["detail"]["code"] == "nextasks_unreachable"
    assert world.card("app")["state"] == "unreachable"
    # Away for now: the button stays, the person learns it when trying.
    assert browser.get("/api/v1/nextasks").json() == {"usable": True}
    world.down.clear()
    assert browser.get("/api/v1/nextasks/lists").status_code == 200
    assert world.card("app")["state"] == "connected"


def test_without_a_connection_nothing_goes(world: Any, nextasks: FakeNextasks) -> None:
    browser = _browser(world)
    found = browser.post(f"/api/v1/documents/{_document('Electricity')}/nextasks", json={"list_id": "list-home"})
    assert found.status_code == 409 and found.json()["detail"]["code"] == "nextasks_not_connected"
    assert nextasks.seen == []


def test_a_list_nextasks_refuses_is_declined(world: Any, nextasks: FakeNextasks) -> None:
    assert world.connect("app").status_code == 200

    async def gone(request: Request) -> Any:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Not found."})

    # nextasks says no to this list (deleted since): nexpaper says so, the connection holds.
    world.partner.api.router.routes = [route for route in world.partner.api.router.routes
                                       if getattr(route, "path", "") != "/api/v1/tasks"]
    world.partner.api.add_api_route("/api/v1/tasks", gone, methods=["POST"])
    made = _browser(world).post(f"/api/v1/documents/{_document('Electricity')}/nextasks", json={"list_id": "x"})
    assert made.status_code == 409
    assert made.json()["detail"]["code"] == "nextasks_declined" and made.json()["detail"]["reason"] == "not_found"
    assert world.card("app")["state"] == "connected"


def test_a_document_the_person_may_not_see_answers_404(world: Any, nextasks: FakeNextasks) -> None:
    assert world.connect("app").status_code == 200
    other = world.app.client("other")
    found = other.post(f"/api/v1/documents/{_document('Electricity')}/nextasks", json={"list_id": "list-home"})
    assert found.status_code == 404
    assert nextasks.tasks == []

