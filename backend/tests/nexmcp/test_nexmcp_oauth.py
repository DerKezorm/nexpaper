"""Connecting programs (decisions 6 and 7): metadata, registration, consent with PKCE, a code once, rotating refresh
tokens whose copies end the program, 90 days or 30 without use, the program revoking itself, the operator's switch."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from mcp_contract import REDIRECT, connect, consent, pkce, refresh, register, rpc, trade


def test_the_401_leads_a_program_to_the_metadata(app: Any) -> None:
    anonymous = app.client("anonymous")
    challenge = rpc(app, None, "ping").headers["www-authenticate"]
    where = challenge.split('resource_metadata="', 1)[1].rstrip('"')
    resource = anonymous.get(where[where.index("/.well-known") :]).json()
    assert resource["resource"].endswith(app.config().mcp_path) and resource["scopes_supported"] == ["mcp"]
    server = anonymous.get("/.well-known/oauth-authorization-server").json()
    assert server["code_challenge_methods_supported"] == ["S256"]
    assert server["token_endpoint_auth_methods_supported"] == ["none"]
    for name in ("token_endpoint", "registration_endpoint", "revocation_endpoint"):
        assert server[name].split("://", 1)[1].split("/", 1)[1].startswith(app.config().oauth_prefix.lstrip("/"))


def test_a_program_connects_calls_and_refreshes(app: Any) -> None:
    client_id, tokens = connect(app)
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == app.config().access_hours * 3600
    assert tokens["access_token"].startswith(app.config().access_prefix)
    assert rpc(app, tokens["access_token"], "ping").status_code == 200
    again = refresh(app, client_id, tokens["refresh_token"])
    assert again.status_code == 200 and again.headers["cache-control"] == "no-store"
    fresh = again.json()
    assert fresh["refresh_token"] != tokens["refresh_token"]
    assert rpc(app, fresh["access_token"], "ping").status_code == 200
    listed = app.client("owner").get(f"{app.keys_prefix}/keys").json()["keys"]
    assert any(key["program"] for key in listed)


def test_a_spent_refresh_token_brought_again_ends_the_program(app: Any) -> None:
    client_id, tokens = connect(app)
    fresh = refresh(app, client_id, tokens["refresh_token"]).json()
    copy = refresh(app, client_id, tokens["refresh_token"])
    assert copy.status_code == 400 and copy.json()["error"] == "invalid_grant"
    assert rpc(app, fresh["access_token"], "ping").status_code == 401
    assert refresh(app, client_id, fresh["refresh_token"]).status_code == 400


def test_a_code_is_good_once_and_only_with_its_verifier_and_return_address(app: Any) -> None:
    client_id = register(app)
    code, verifier = consent(app, client_id)
    assert trade(app, client_id, code, "x" * 50).status_code == 400
    code, verifier = consent(app, client_id)
    first = trade(app, client_id, code, verifier)
    assert first.status_code == 200
    second = trade(app, client_id, code, verifier)
    assert second.status_code == 400
    assert rpc(app, first.json()["access_token"], "ping").status_code == 401


def test_consent_refuses_what_a_program_may_not_ask(app: Any) -> None:
    client_id = register(app)
    _, challenge = pkce()
    base = {
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    path = f"{app.config().oauth_prefix}/authorize"
    owner = app.client("owner")
    assert owner.get(path, params={**base, "redirect_uri": "https://evil.example.com/cb"}).status_code == 400
    assert owner.get(path, params={**base, "code_challenge_method": "plain"}).status_code == 400
    assert owner.get(path, params={**base, "resource": "https://other.example.com/api/mcp"}).status_code == 400
    assert owner.get(path, params={**base, "client_id": "unknown"}).status_code == 400
    assert app.client("anonymous").get(path, params=base).status_code in (401, 403)
    shown = owner.get(path, params=base).json()
    assert shown["client"]["name"] == "Probe client" and shown["level"] == app.config().levels[0]
    declined = owner.post(path, json={**base, "allow": False, "state": "s"}).json()["redirect"]
    assert declined.startswith(REDIRECT) and "error=access_denied" in declined


def test_registration_takes_only_public_programs_with_safe_return_addresses(app: Any) -> None:
    path = f"{app.config().oauth_prefix}/register"
    anonymous = app.client("anonymous")
    for uris in (["http://example.com/cb"], ["https://example.com/cb#x"], ["https://user@example.com/cb"], []):
        assert anonymous.post(path, json={"redirect_uris": uris}).status_code == 400, uris
    secret = anonymous.post(
        path, json={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": "client_secret_basic"}
    )
    assert secret.status_code == 400


def test_a_program_signs_in_again_after_30_idle_days_and_after_90(app: Any, nexmcp: Any, monkeypatch: Any) -> None:
    """Decision 7."""
    client_id, tokens = connect(app)
    start = datetime.now(UTC)
    monkeypatch.setattr(nexmcp.api, "_now", lambda: start + timedelta(days=29))
    later = refresh(app, client_id, tokens["refresh_token"])
    assert later.status_code == 200
    monkeypatch.setattr(nexmcp.api, "_now", lambda: start + timedelta(days=29 + 31))
    assert refresh(app, client_id, later.json()["refresh_token"]).status_code == 400
    client_id, tokens = connect(app)
    for day in range(25, 100, 25):
        monkeypatch.setattr(nexmcp.api, "_now", lambda day=day: start + timedelta(days=day))
        answer = refresh(app, client_id, tokens["refresh_token"])
        if day <= 90:
            assert answer.status_code == 200, (day, answer.text)
            tokens = answer.json()
        else:
            assert answer.status_code == 400


def test_a_program_revokes_itself_and_the_operator_switches_programs_off(app: Any) -> None:
    client_id, tokens = connect(app)
    path = f"{app.config().oauth_prefix}/revoke"
    assert app.client("anonymous").post(path, data={"token": "nothing", "client_id": client_id}).status_code == 200
    assert (
        app.client("anonymous").post(path, data={"token": tokens["refresh_token"], "client_id": client_id}).status_code
        == 200
    )
    assert rpc(app, tokens["access_token"], "ping").status_code == 401
    client_id, tokens = connect(app)
    app.client("operator").put(f"{app.prefix}/admin", json={"programs": False})
    assert rpc(app, tokens["access_token"], "ping").status_code == 401
    assert app.client("anonymous").get("/.well-known/oauth-authorization-server").status_code == 404
    assert "resource_metadata" not in rpc(app, None, "ping").headers["www-authenticate"]
    app.client("operator").put(f"{app.prefix}/admin", json={"programs": True})
    assert rpc(app, tokens["access_token"], "ping").status_code == 200
