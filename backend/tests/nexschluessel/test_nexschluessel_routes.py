"""Who may call which route: an account sees and changes only its own keys, only an operator sees every key, locks
them and sets the switches; without a session nothing."""

from __future__ import annotations

from typing import Any


def test_without_a_session_nothing(app: Any) -> None:
    anonymous = app.client("anonymous")
    for method, path in (
        ("get", "/keys"),
        ("post", "/keys"),
        ("delete", "/keys/1"),
        ("get", "/admin/keys"),
        ("post", "/admin/keys/1/block"),
        ("get", "/interfaces"),
        ("put", "/interfaces"),
    ):
        answer = getattr(anonymous, method)(
            f"{app.prefix}{path}", **({"json": {}} if method in ("post", "put") else {})
        )
        assert answer.status_code in (401, 403), f"{method} {path}: {answer.status_code}"


def test_a_member_never_reaches_the_operators_routes(app: Any) -> None:
    member = app.client("owner")
    assert member.get(f"{app.prefix}/admin/keys").status_code == 403
    assert member.post(f"{app.prefix}/admin/keys/1/block").status_code == 403
    assert member.post(f"{app.prefix}/admin/keys/1/unblock").status_code == 403
    assert member.get(f"{app.prefix}/interfaces").status_code == 403
    assert member.put(f"{app.prefix}/interfaces", json={"api": False}).status_code == 403


def test_the_operator_sees_the_switches_the_app_has_and_no_other(app: Any, config: Any) -> None:
    operator = app.client("operator")
    shown = operator.get(f"{app.prefix}/interfaces").json()
    assert set(shown) == set(config.switches)
    for name in config.switches:
        before = shown[name]
        assert operator.put(f"{app.prefix}/interfaces", json={name: not before}).json()[name] is (not before)
        assert operator.put(f"{app.prefix}/interfaces", json={name: before}).json()[name] is before
    missing = [name for name in ("api", "mcp", "app", "pairing") if name not in config.switches]
    for name in missing:
        assert operator.put(f"{app.prefix}/interfaces", json={name: True}).status_code == 422


def test_locking_an_unknown_key_is_not_found(app: Any) -> None:
    operator = app.client("operator")
    assert operator.post(f"{app.prefix}/admin/keys/987654/block").status_code == 404
    assert operator.post(f"{app.prefix}/admin/keys/987654/unblock").status_code == 404


def test_the_page_names_the_address_and_the_paths_for_programs(app: Any, config: Any) -> None:
    listed = app.client("owner").get(f"{app.prefix}/keys").json()
    assert listed["address"].startswith("http") and listed["api_path"] == config.api_path
    assert listed["mcp_path"] == config.mcp_path and listed["programs"] is config.programs
    assert (listed["mcp"] is None) == (not config.has_mcp)
