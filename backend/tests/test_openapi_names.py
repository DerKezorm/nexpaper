"""The interface keeps its names (Bauplan E53): every route nexpaper described before the settings pass (branch
``konten``, kept in ``tests/schema/names-before-settings.json``) is still there under its operationId and summary, and
every schema name of then still stands. New routes, schemas and fields may come; nothing of before is renamed, so a
client generated from the description of before keeps working. The snapshot test (``test_routes.py``) is renewed with
every change; this list is not.

Two summaries changed because the behaviour changed, and say so (listed for the operator of the plan): deleting an
account can be undone for 30 days, and a blocked key can be unblocked."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.main import app

BEFORE = json.loads((Path(__file__).parent / "schema" / "names-before-settings.json").read_text(encoding="utf-8"))

#: Summaries that changed with the behaviour (Bauplan E53, step 4): route -> the summary now.
CHANGED_WITH_BEHAVIOUR = {
    "DELETE /api/v1/accounts/{account_id}": "Delete an account (it can be brought back for 30 days)",
    "POST /api/v1/admin/api-keys/{key_id}/block": "Block a key (operator); its account sees it blocked",
}


def described() -> dict[str, Any]:
    return app.openapi()


def test_every_route_of_before_keeps_its_operation_id_and_summary() -> None:
    now = described()["paths"]
    gone, renamed = [], []
    for route, names in BEFORE["operations"].items():
        method, path = route.split(" ", 1)
        operation = now.get(path, {}).get(method.lower())
        if operation is None:
            gone.append(route)
            continue
        summary = CHANGED_WITH_BEHAVIOUR.get(route, names["summary"])
        if operation.get("operationId") != names["operationId"] or operation.get("summary") != summary:
            renamed.append((route, operation.get("operationId"), operation.get("summary")))
    assert gone == [] and renamed == []


def test_every_schema_name_of_before_still_stands() -> None:
    schemas = described()["components"]["schemas"]
    assert [name for name in BEFORE["schemas"] if name not in schemas] == []


def test_the_list_of_before_is_the_whole_interface_of_then() -> None:
    """A guard against an emptied list: the interface had 326 routes and 265 schemas on branch konten."""
    assert (len(BEFORE["operations"]), len(BEFORE["schemas"])) == (326, 265)
