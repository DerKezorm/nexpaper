"""The description of the interface stays the app's (E53): the old backup routes (``legacy_router``) carry the
operationIds and summaries the app gave (``routes.former_names``: what its own routes had before the module), and the
bodies of both routers the schema names it gave (``CreateIn``, ``app__routers__backups__PasswordIn`` …). Without names
the module's own stand. Read only through the adapter's ``description()``. Copied unchanged into every app."""

from __future__ import annotations

from typing import Any

import pytest

#: Old routes: name -> (path after ``legacy_prefix``, method, the module's schema of the body or None).
LEGACY = {
    "listing": ("", "get", None),
    "create": ("", "post", "NoteIn"),
    "upload": ("/upload", "post", None),
    "check": ("/{name}/check", "post", None),
    "restore_route": ("/{name}/restore", "post", "RestoreIn"),
    "download": ("/{name}/download", "post", "DownloadIn"),
    "delete": ("/{name}", "delete", "PasswordIn"),
}
#: The module's routes with a body: (path after ``prefix``, method, schema).
OWN = {
    "make": ("/backups", "post", "NoteIn"),
    "schedule": ("/backups/schedule", "put", "ScheduleIn"),
    "check": ("/backups/{name}/check", "post", "CheckIn"),
    "download": ("/backups/{name}/download", "post", "DownloadIn"),
    "restore_route": ("/backups/{name}/restore", "post", "RestoreIn"),
    "delete": ("/backups/{name}", "delete", "PasswordIn"),
}


def shown(target: str) -> set[str]:
    """How FastAPI may write a schema name: the name, or where two classes share it, place and name joined by
    ``__`` (``app__routers__backups__PasswordIn``)."""
    place, _, name = target.rpartition(".")
    return {name, f"{place.replace('.', '__')}__{name}"} if place else {target}


def _body(operation: dict[str, Any]) -> str:
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    reference = schema.get("$ref") or next(item["$ref"] for item in schema.get("anyOf", []) if "$ref" in item)
    return str(reference).rsplit("/", 1)[-1]


@pytest.fixture
def described(app: Any) -> dict[str, Any]:
    found = app.description()
    assert isinstance(found, dict) and "paths" in found, type(found)
    return found


def test_the_old_routes_carry_the_operation_ids_and_summaries_the_app_gave(app: Any,
                                                                           described: dict[str, Any]) -> None:
    if not app.legacy_prefix:
        # Without the module's old routes there is nothing to name (nexmail keeps its own).
        assert app.operation_ids == {} and app.summaries == {}
        return
    for route, (tail, method, _) in LEGACY.items():
        operation = described["paths"][f"{app.legacy_prefix}{tail}"][method]
        if route in app.operation_ids:
            assert operation["operationId"] == app.operation_ids[route], route
        else:
            assert operation["operationId"].startswith(f"{route}_"), (route, operation["operationId"])
        if route in app.summaries:
            assert operation["summary"] == app.summaries[route], route


def test_every_body_carries_the_schema_name_the_app_gave(app: Any, described: dict[str, Any]) -> None:
    routes = [(app.prefix, OWN)] + ([(app.legacy_prefix, LEGACY)] if app.legacy_prefix else [])
    for prefix, table in routes:
        for route, (tail, method, schema) in table.items():
            if schema is None:
                continue
            found = _body(described["paths"][f"{prefix}{tail}"][method])
            target = app.schema_names.get(schema)
            if target:
                assert found in shown(target), (prefix, route, found, target)
            else:
                assert found == schema or found.endswith(f"__{schema}"), (prefix, route, found)


def test_the_module_puts_no_class_of_its_own_beside_a_renamed_one(app: Any, described: dict[str, Any]) -> None:
    """A name the app gave replaces the module's class in both routers: no route of the module still answers with the
    module's own class, and no schema carries the module's long name. A schema of the app's own under the same short
    name (``RestoreIn`` of a trash, ``NoteIn`` of documents, which ``FORMER_SCHEMAS`` gives back their short names) is
    the app's, not the module's."""
    schemas = described["components"]["schemas"]
    for schema in app.schema_names:
        left = [name for name in schemas if name.endswith(f"nexsicherung__routes__{schema}")]
        assert left == [], (schema, left)
    routes = [(app.prefix, OWN)] + ([(app.legacy_prefix, LEGACY)] if app.legacy_prefix else [])
    for prefix, table in routes:
        for route, (tail, method, schema) in table.items():
            if schema in app.schema_names:
                found = _body(described["paths"][f"{prefix}{tail}"][method])
                assert found not in ({schema} - shown(app.schema_names[schema])), (prefix, route, found)
