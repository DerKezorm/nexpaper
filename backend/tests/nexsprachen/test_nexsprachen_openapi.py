"""The description of the interface stays the app's (E53): the module's routes carry the operationId, summary and
schema names the app's routes had (``list_locales_api_v1_locales_get``, „Languages the operator added“,
``LocaleEntry``), so a snapshot and a generated client keep working. Without names from the app the module's defaults
are the names all eight apps had before. Copied unchanged into every app."""

from __future__ import annotations

from typing import Any

#: The module's routes: (path after the prefix, method), and FastAPI's name of the module's function.
ROUTES = {
    "list": ("", "get", "list_locales"),
    "template": ("/template", "get", "download_template"),
    "read": ("/{code}", "get", "read_locale"),
    "upload": ("/{code}", "put", "upload_locale"),
    "remove": ("/{code}", "delete", "delete_locale"),
}
#: What the routes said before the module (nexnotes' eigenbau, in all eight apps).
SUMMARIES = {
    "list": "Languages the operator added",
    "read": "The texts of one added language",
    "upload": "Add or replace a language (operator)",
    "remove": "Remove an added language (operator)",
}


def shown(target: str) -> set[str]:
    """How FastAPI writes a schema name: ``LocaleEntry``, or for a dotted place and name either the name or, where two
    classes share it, ``app__routers__locales__LocaleEntry``."""
    place, _, name = target.rpartition(".")
    return {name, f"{place.replace('.', '__')}__{name}"} if place else {target}


def _description(app: Any) -> dict[str, Any]:
    """Only through the adapter: an app may publish no description (nexmail) and hand over ``app.openapi()``."""
    described = app.description()
    assert isinstance(described, dict) and "paths" in described, type(described)
    return described


def _operation(described: dict[str, Any], app: Any, route: str) -> dict[str, Any]:
    tail, method, _ = ROUTES[route]
    return described["paths"][f"{app.prefix}{tail}"][method]


def test_every_route_carries_the_operation_id_the_app_gave_or_the_modules(app: Any) -> None:
    described = _description(app)
    for route, (_, _, function) in ROUTES.items():
        found = _operation(described, app, route)["operationId"]
        if route in app.operation_ids:
            assert found == app.operation_ids[route], route
        else:
            assert found.startswith(f"{function}_"), (route, found)


def test_every_route_carries_the_summary_the_app_gave_or_the_old_one(app: Any) -> None:
    described = _description(app)
    for route, summary in (SUMMARIES | app.summaries).items():
        assert _operation(described, app, route)["summary"] == summary, route


def test_the_schemas_carry_the_names_the_app_gave_or_the_modules(app: Any) -> None:
    described = _description(app)
    schemas = described["components"]["schemas"]
    listed = app.schema_names.get("LanguageEntry", "LocaleEntry")
    uploaded = app.schema_names.get("LocaleEntry", "LocaleEntry")
    assert not [name for name in schemas if "nexsprachen" in name], "a class of the module shares a name"
    items = _operation(described, app, "list")["responses"]["200"]["content"]["application/json"]["schema"]["items"]
    listed_as = items["$ref"].rsplit("/", 1)[-1]
    assert listed_as in shown(listed), (listed_as, listed)
    answer = _operation(described, app, "upload")["responses"]["200"]["content"]["application/json"]["schema"]
    uploaded_as = answer["$ref"].rsplit("/", 1)[-1]
    assert uploaded_as in shown(uploaded), (uploaded_as, uploaded)
    assert set(schemas[listed_as]["required"]) == {"code", "name", "keys"}
    assert set(schemas[uploaded_as]["required"]) == {"code", "name", "keys"}
    assert "LanguageEntry" not in schemas or "LanguageEntry" in shown(listed)


def test_an_upload_answers_three_fields_whatever_its_schema_is_called(app: Any, operator: Any) -> None:
    answer = operator.put(f"{app.prefix}/nl", content=b'{"a": "b"}', headers={"content-type": "application/json"})
    assert answer.status_code == 200 and answer.json() == {"code": "nl", "name": "nl", "keys": 1}
