"""The old routes refuse a backup name that is none of the app's as the app's own routes did (E53): ``../``, an
absolute path, a hidden file, another ending, another app's name or a name too long, each with the status the app's
routes answered on ``konten`` (measured in all six apps: 404 where the router finds no route, 422 where the name does
not match), before the password is asked, so a wrong name never counts as a wrong password. And the description shows
the pattern and the length again, for an app that gives ``name_pattern`` (``routes.former_names``). Copied
unchanged into every app."""

from __future__ import annotations

from typing import Any

import pytest
from sicherung_contract import package_of

#: The routes with ``{name}``: (method, path after ``{name}``).
ROUTES = {"delete": ("DELETE", ""), "check": ("POST", "/check"), "download": ("POST", "/download"),
          "restore": ("POST", "/restore")}


def cases(app_name: str) -> dict[str, tuple[str, int]]:
    """Case -> (name in the path, the status on konten)."""
    stamp = "2026-01-01-000000"
    return {
        "dot-dot, encoded": ("..%2F..%2Fsecret.zip", 404),
        "dot-dot": ("..", 404),
        "absolute path, encoded": ("%2Fetc%2Fpasswd", 404),
        "another ending": (f"{app_name}-{stamp}.tar", 422),
        "hidden file": (f".{app_name}-{stamp}.zip", 422),
        "work file": (f"{app_name}-{stamp}.zip.part", 422),
        "too long": (f"{app_name}-{stamp}-" + "1" * 40 + ".zip", 422),
        "another app": (f"nexother-{stamp}.zip", 422),
    }


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_a_name_that_is_none_of_the_apps_gets_the_status_of_before(app: Any, route: str) -> None:
    """With ``name_pattern`` the statuses of ``konten``; without (an app whose routes never had a pattern) at least a
    refusal, never a 2xx or a 5xx."""
    if not app.legacy_prefix:
        assert not app.name_pattern
        return
    client = app.operator()
    method, tail = ROUTES[route]
    app_name = package_of(app).current().app_name
    found = {}
    for case, (name, status) in cases(app_name).items():
        # The right password: a refusal can only come from the name.
        answer = client.request(method, f"{app.legacy_prefix}/{name}{tail}", json={"password": app.password})
        found[case] = (answer.status_code, status)
    if app.name_pattern:
        assert {case: got for case, (got, _) in found.items()} == {case: want for case, (_, want) in found.items()}
    else:
        assert all(400 <= got < 500 for got, _ in found.values()), found


def test_a_wrong_name_never_counts_as_a_wrong_password(app: Any) -> None:
    """With ``name_pattern`` the name is refused before the password is asked; without, the description keeps no
    pattern (it had none)."""
    if not app.legacy_prefix:
        assert not app.name_pattern
        return
    if not app.name_pattern:
        described = app.description()
        operation = described["paths"][f"{app.legacy_prefix}/{{name}}"]["delete"]
        schema = next(item["schema"] for item in operation["parameters"] if item["name"] == "name")
        assert "pattern" not in schema
        return
    client = app.operator()
    app_name = package_of(app).current().app_name
    for _ in range(12):
        answer = client.request("DELETE", f"{app.legacy_prefix}/.{app_name}-2026-01-01-000000.zip",
                                json={"password": "not the password"})
        assert answer.status_code == 422, answer.status_code
    described = app.description()
    pattern = package_of(app).current().name_pattern.pattern
    for tail in ("/{name}", "/{name}/check", "/{name}/download", "/{name}/restore"):
        for operation in described["paths"][f"{app.legacy_prefix}{tail}"].values():
            schema = next(item["schema"] for item in operation["parameters"] if item["name"] == "name")
            assert (schema.get("pattern"), schema.get("maxLength")) == (pattern, 64), (tail, schema)
