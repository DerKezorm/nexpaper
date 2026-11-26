"""The description of the interface stays the app's: where the app had its own routes, the module's routes carry the
operationId, summary and schema names they had (nexpaper ``list_locales_api_v1_locales_get``, ``LocaleEntry``), so a
snapshot and a generated client keep working; without such names the module's own stand. Copied unchanged into every
app."""

from __future__ import annotations

from typing import Any

#: The module's routes: (path after the prefix, method), and FastAPI's name of the module's function.
ROUTES = {
    "list": ("", "get", "list_languages"),
    "template": ("/template", "get", "download_template"),
    "read": ("/{code}", "get", "read_language"),
    "upload": ("/{code}", "put", "upload_language"),
    "remove": ("/{code}", "delete", "remove_language"),
}


def _description(app: Any) -> dict[str, Any]:
    answer = app.client("operator").get(app.openapi_path)
    assert answer.status_code == 200, (app.openapi_path, answer.status_code)
    return answer.json()


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


def test_every_route_carries_the_summary_the_app_gave(app: Any) -> None:
    described = _description(app)
    for route, summary in app.summaries.items():
        assert _operation(described, app, route)["summary"] == summary, route


def test_the_schemas_carry_the_names_the_app_gave_or_the_modules(app: Any) -> None:
    described = _description(app)
    schemas = described["components"]["schemas"]
    listed = app.schema_names.get("LanguageEntry", "LanguageEntry")
    uploaded = app.schema_names.get("LocaleEntry", "LocaleEntry")
    assert listed in schemas and uploaded in schemas, sorted(schemas)
    doubled = [name for name in schemas if "__" in name and ("LanguageEntry" in name or "LocaleEntry" in name)]
    assert doubled == [], "one class per name, not one per mount"
    for renamed in set(app.schema_names) - set(app.schema_names.values()):
        assert renamed not in schemas, renamed
    items = _operation(described, app, "list")["responses"]["200"]["content"]["application/json"]["schema"]["items"]
    assert items == {"$ref": f"#/components/schemas/{listed}"}
    answer = _operation(described, app, "upload")["responses"]["200"]["content"]["application/json"]["schema"]
    assert answer == {"$ref": f"#/components/schemas/{uploaded}"}
    assert set(schemas[listed]["required"]) == {"code", "name", "keys"}


def test_an_upload_answers_three_fields_whatever_its_schema_is_called(app: Any, operator: Any) -> None:
    answer = operator.put(f"{app.prefix}/nl", content=b'{"a": "b"}', headers={"content-type": "application/json"})
    assert answer.status_code == 200 and answer.json() == {"code": "nl", "name": "nl", "keys": 1}
