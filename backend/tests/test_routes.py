"""The interface is one: every route of the app is under ``/api/v1``, every route that is not open says 401 without a
sign-in, the description of the interface (``/api/v1/openapi.json``) is kept as a snapshot, and its page works under
the strict policy of the app.

When a route is added or changed on purpose, the snapshot is renewed by hand:

    NEXPAPER_RECORD_OPENAPI=1 python -m pytest tests/test_routes.py

and the open routes below are named here if the new route is open to everybody (it almost never should be).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import deps
from app.main import app
from app.models import Account

SNAPSHOT = Path(__file__).parent / "schema" / "openapi.json"

#: Routes that answer without a sign-in, on purpose: the state before and while signing in, the things the sign-in page
#: shows, the way back in (a link, a code), the provider's return, and the description of the interface itself.
OPEN = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/about"),
    ("GET", "/api/v1/docs"),
    ("GET", "/api/v1/locales"),
    ("GET", "/api/v1/locales/{code}"),
    ("GET", "/api/v1/setup"),
    ("POST", "/api/v1/setup"),
    ("GET", "/api/v1/auth/methods"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/login/totp"),
    ("POST", "/api/v1/auth/login/totp/cancel"),
    ("POST", "/api/v1/auth/passkey/begin"),
    ("POST", "/api/v1/auth/passkey"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/forgot"),
    # Sign-in through a provider: the buttons, off to the provider, and back (the second return belongs to the entry
    # ``oidc``, the address of 1.0.1).
    ("GET", "/api/v1/oidc/providers"),
    ("GET", "/api/v1/oidc/{slug}/start"),
    ("GET", "/api/v1/oidc/{slug}/callback"),
    ("GET", "/api/v1/oidc/callback"),
    ("GET", "/api/v1/invite/{token}"),
    ("POST", "/api/v1/invite/{token}"),
    ("GET", "/api/v1/email/confirm/{token}"),
    ("POST", "/api/v1/email/confirm/{token}"),
    ("GET", "/api/v1/reset/{token}"),
    ("POST", "/api/v1/reset/{token}"),
    # A link to one document: the token is the key (tests/test_links.py).
    ("GET", "/api/v1/l/{token}"),
    ("GET", "/api/v1/l/{token}/file"),
    ("GET", "/api/v1/l/{token}/preview"),
    ("GET", "/api/v1/l/{token}/pages/{page}"),
    # Pairing: a device trades the code it was shown, an app the code of OAuth with its verifier (tests/test_pairing.py).
    ("POST", "/api/v1/devices/pair"),
    ("POST", "/api/v1/oauth/token"),
    # The link that confirms an address a person forwards documents from (tests/test_mail_senders.py).
    ("GET", "/api/v1/mail-senders/confirm/{token}"),
    ("POST", "/api/v1/mail-senders/confirm/{token}"),
    ("GET", "/api/v1/l/{token}/text"),
    # A link to an export for the tax adviser: the token is the key (tests/test_exports.py).
    ("GET", "/api/v1/x/{token}"),
    ("GET", "/api/v1/x/{token}/file"),
}


def concrete(path: str) -> str:
    """A path with its parameters filled in, so that the router finds the route."""
    return re.sub(r"\{([^}:]+)(?::[^}]*)?\}", lambda m: "1" if m.group(1).endswith("id") else "a" * 32, path)


def every_route() -> list[Any]:
    """The routes of the app, the included routers opened (this FastAPI keeps them as a router inside a router)."""
    found: list[Any] = []
    for route in app.routes:
        inner = getattr(route, "original_router", None)
        found.extend(inner.routes if inner is not None else [route])
    return found


def api_routes() -> list[tuple[str, str]]:
    found = []
    for route in every_route():
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                found.append((method, route.path))
    return sorted(found)


def test_every_route_is_under_the_one_interface() -> None:
    outside = [route.path for route in every_route() if not str(getattr(route, "path", "")).startswith("/api/v1")]
    # The frontend is served from files and mounted only where it was built (not in the tests).
    assert outside == [], f"Routes outside /api/v1: {outside}"
    assert len(api_routes()) > 80


def test_nothing_is_called_under_the_old_prefix() -> None:
    with TestClient(app, base_url="http://testserver") as client:
        for path in ("/api/auth/me", "/api/health", "/api/setup", "/api/about"):
            assert client.get(path).status_code == 404, path


def test_every_route_that_is_not_open_says_401_without_a_sign_in() -> None:
    wrong: list[str] = []
    open_found: set[tuple[str, str]] = set()
    with TestClient(app, base_url="http://testserver", headers={"X-Nexpaper-Client": "tab-routes000"}) as client:
        for method, path in api_routes():
            if (method, path) in OPEN:
                open_found.add((method, path))
                continue
            answer = client.request(method, concrete(path), json={} if method in ("POST", "PUT", "PATCH") else None)
            if answer.status_code != 401:
                wrong.append(f"{method} {path} -> {answer.status_code}")
    assert wrong == [], "Routes that do not ask for a sign-in (name them in OPEN if that is meant): " + "; ".join(wrong)
    stale = sorted(OPEN - open_found)
    assert stale == [], f"Named open here, but not routes any more: {stale}"


def test_a_device_token_that_is_wrong_is_401_on_every_route_that_asks_for_one() -> None:
    """The same list with a token that does not exist: still 401 (or 403 where only a browser may come)."""
    odd: list[str] = []
    with TestClient(app, base_url="http://testserver") as client:
        for method, path in api_routes():
            if (method, path) in OPEN or path == "/api/v1/me":
                continue
            answer = client.request(method, concrete(path), headers={"Authorization": "Bearer npd_" + "w" * 43},
                                    json={} if method in ("POST", "PUT", "PATCH") else None)
            if answer.status_code not in (401, 403, 429):
                odd.append(f"{method} {path} -> {answer.status_code}")
    assert odd == [], odd


def _called(dependant: Any) -> set[Any]:
    """Every function a route asks for before it runs, the ones asked for by the ones asked for included."""
    found: set[Any] = set()
    for sub in dependant.dependencies:
        found.add(sub.call)
        found |= _called(sub)
    return found


def routes_asking_for(*guards: Any) -> list[tuple[str, str]]:
    found = []
    for route in every_route():
        if isinstance(route, APIRoute) and _called(route.dependant) & set(guards):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                found.append((method, route.path))
    return sorted(found)


#: The routes a device token reaches (the sign-in state and the own profile, the push registration of the device, the
#: model list of the AI): everything else needs the browser. A new route lands here only on purpose.
TOKEN_ROUTES = {
    ("GET", "/api/v1/about/updates"),
    ("POST", "/api/v1/auth/setup/done"),
    ("POST", "/api/v1/auth/setup/codes"),
    ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/auth/sessions"),
    ("PUT", "/api/v1/me/profile"),
    ("POST", "/api/v1/me/whats-new/seen"),
    ("PUT", "/api/v1/me/language"),
    ("PUT", "/api/v1/me/preferences"),
    ("PUT", "/api/v1/auth/avatar"),
    ("DELETE", "/api/v1/auth/avatar"),
    ("GET", "/api/v1/avatars/{account_id}"),
    ("GET", "/api/v1/ai"),
    ("GET", "/api/v1/push"),
    ("POST", "/api/v1/push/devices"),
    ("POST", "/api/v1/push/devices/lookup"),
    ("PUT", "/api/v1/push/devices/{device_id}"),
    ("DELETE", "/api/v1/push/devices/{device_id}"),
    ("POST", "/api/v1/push/test"),
    # Documents: changing them (a program with an API key only reads).
    ("PATCH", "/api/v1/documents/{document_id}"),
    ("DELETE", "/api/v1/documents/{document_id}"),
    ("POST", "/api/v1/documents/{document_id}/move"),
    ("POST", "/api/v1/documents/{document_id}/restore"),
    ("POST", "/api/v1/documents/{document_id}/notes"),
    ("PUT", "/api/v1/documents/{document_id}/notes/{note_id}"),
    ("DELETE", "/api/v1/documents/{document_id}/notes/{note_id}"),
    ("PUT", "/api/v1/documents/{document_id}/shares/{user_id}"),
    ("DELETE", "/api/v1/documents/{document_id}/shares/{user_id}"),
    ("POST", "/api/v1/documents/{document_id}/links"),
    ("DELETE", "/api/v1/documents/{document_id}/links/{link_id}"),
    ("POST", "/api/v1/documents/{document_id}/links/{link_id}/address"),
    ("PATCH", "/api/v1/senders/{sender_id}"),
    ("DELETE", "/api/v1/senders/{sender_id}"),
    ("PATCH", "/api/v1/tags/{tag_id}"),
    ("DELETE", "/api/v1/tags/{tag_id}"),
    ("POST", "/api/v1/senders/{sender_id}/merge"),
    ("POST", "/api/v1/tags/{tag_id}/merge"),
    # Bringing files in (a program with an API key of the scope ``upload`` reaches these and nothing else) and trying
    # again to read a document.
    ("POST", "/api/v1/documents"),
    ("POST", "/api/v1/documents/{document_id}/retry"),
    ("POST", "/api/v1/uploads"),
    ("GET", "/api/v1/uploads"),
    ("GET", "/api/v1/uploads/{upload_id}"),
    ("PUT", "/api/v1/uploads/{upload_id}"),
    ("POST", "/api/v1/uploads/{upload_id}/finish"),
    ("DELETE", "/api/v1/uploads/{upload_id}"),
    # The phone: where the iPhone shortcut sends its files.
    ("GET", "/api/v1/shortcut"),
    # Where the own documents can be sent (the mailbox, the own subfolder): an app may show it.
    ("GET", "/api/v1/me/intake"),
    # Exports for the tax adviser (B9): a device may look, delete and revoke; making one, its ZIP and its links need
    # the browser, and a key reaches none of it.
    ("GET", "/api/v1/exports/preview"),
    ("GET", "/api/v1/exports"),
    ("GET", "/api/v1/exports/{export_id}"),
    ("DELETE", "/api/v1/exports/{export_id}"),
    ("GET", "/api/v1/exports/{export_id}/links"),
    ("DELETE", "/api/v1/exports/{export_id}/links/{link_id}"),
    # The kinds of a vault (B6): made, changed and deleted by whoever may edit the vault; the ones of the whole server
    # stay the operator's, in a browser (``test_vault_kinds.py``).
    ("POST", "/api/v1/kinds"),
    ("PATCH", "/api/v1/kinds/{kind_id}"),
    ("DELETE", "/api/v1/kinds/{kind_id}"),
    ("POST", "/api/v1/kinds/{kind_id}/merge"),
    ("POST", "/api/v1/inbox/file"),
    # Sorting documents in (B6): the rules of the vaults a person manages, and a rule from a document in the inbox. The
    # operator's rules for the whole server need the browser (``/settings/rules``).
    ("GET", "/api/v1/rules"),
    ("POST", "/api/v1/rules"),
    ("PATCH", "/api/v1/rules/{rule_id}"),
    ("DELETE", "/api/v1/rules/{rule_id}"),
    ("POST", "/api/v1/documents/{document_id}/rule"),
    # The page tools (B5): changing pages, joining, splitting, versions.
    ("POST", "/api/v1/documents/{document_id}/pages"),
    ("POST", "/api/v1/documents/{document_id}/merge"),
    ("POST", "/api/v1/documents/{document_id}/split"),
    ("DELETE", "/api/v1/documents/{document_id}/separators"),
    ("POST", "/api/v1/documents/{document_id}/versions/{number}/restore"),
    ("POST", "/api/v1/documents/{document_id}/versions"),
    ("DELETE", "/api/v1/documents/{document_id}/versions/{number}"),
    # Keeping (F3): the keeping time of a kind and many documents into the trash.
    ("POST", "/api/v1/kinds/{kind_id}/keeping/preview"),
    ("PUT", "/api/v1/kinds/{kind_id}/keeping"),
    ("POST", "/api/v1/documents/trash"),
    # Deadlines (F1): done and open again for everybody, later for oneself.
    ("POST", "/api/v1/documents/{document_id}/dates/{kind}/done"),
    ("DELETE", "/api/v1/documents/{document_id}/dates/{kind}/done"),
    ("PUT", "/api/v1/documents/{document_id}/dates/{kind}/snooze"),
    ("DELETE", "/api/v1/documents/{document_id}/dates/{kind}/snooze"),
}

#: The routes that only read and that a program with an API key reaches too (as the browser and a device do). A route
#: that changes something is never in this list.
READ_ROUTES = {
    ("GET", "/api/v1/vaults"),
    ("GET", "/api/v1/vaults/{vault_id}"),
    ("GET", "/api/v1/people"),
    ("GET", "/api/v1/documents"),
    ("GET", "/api/v1/documents/{document_id}"),
    ("GET", "/api/v1/documents/{document_id}/notes"),
    ("GET", "/api/v1/documents/{document_id}/events"),
    ("GET", "/api/v1/documents/{document_id}/versions"),
    ("GET", "/api/v1/documents/{document_id}/versions/{number}/file"),
    ("GET", "/api/v1/documents/{document_id}/versions/{number}/archive"),
    ("GET", "/api/v1/documents/{document_id}/versions/{number}/preview"),
    ("GET", "/api/v1/documents/{document_id}/versions/{number}/pages/{page}"),
    ("GET", "/api/v1/documents/{document_id}/shares"),
    ("GET", "/api/v1/documents/{document_id}/links"),
    ("GET", "/api/v1/links"),
    ("GET", "/api/v1/sharing"),
    ("GET", "/api/v1/senders"),
    ("GET", "/api/v1/tags"),
    ("GET", "/api/v1/kinds"),
    # The inbox as a list and the numbers of the menu.
    ("GET", "/api/v1/inbox"),
    ("GET", "/api/v1/counts"),
    # Order: the lists with how many documents use each entry.
    ("GET", "/api/v1/order/senders"),
    ("GET", "/api/v1/order/tags"),
    ("GET", "/api/v1/order/kinds"),
    ("GET", "/api/v1/changes"),
    # The phone: what the quick upload shows.
    ("GET", "/api/v1/quick"),
    ("GET", "/api/v1/documents/{document_id}/origin"),
    # The search and the text of a document (B3).
    ("GET", "/api/v1/search"),
    ("GET", "/api/v1/search/overview"),
    ("GET", "/api/v1/documents/{document_id}/versions/{number}/text"),
    # The e-invoice of a document: its data and its XML (B6), read like the file.
    ("GET", "/api/v1/documents/{document_id}/einvoice"),
    ("GET", "/api/v1/documents/{document_id}/versions/{number}/einvoice"),
    # The blank separator pages of a document (B5).
    ("GET", "/api/v1/documents/{document_id}/separators"),
    # The documents whose keeping time is over (F3).
    ("GET", "/api/v1/keeping"),
    # The deadlines (F1).
    ("GET", "/api/v1/deadlines"),
}


def test_the_routes_a_device_token_reaches_are_the_ones_named_here() -> None:
    reached = set(routes_asking_for(deps.require_account, deps.require_reader, deps.require_uploader))
    assert reached == TOKEN_ROUTES | READ_ROUTES, (
        f"new: {sorted(reached - TOKEN_ROUTES - READ_ROUTES)}; gone: {sorted(TOKEN_ROUTES | READ_ROUTES - reached)}")


def test_the_routes_a_key_reaches_only_read() -> None:
    reading = set(routes_asking_for(deps.require_reader))
    assert reading == READ_ROUTES, f"new: {sorted(reading - READ_ROUTES)}; gone: {sorted(READ_ROUTES - reading)}"
    assert {method for method, _path in reading} == {"GET"}


def test_no_operator_route_is_reached_with_a_device_token(client: TestClient, operator: Account) -> None:
    """The operator's routes are found in the route list, not named by hand, so a route added tomorrow is covered."""
    operator_routes = routes_asking_for(deps.require_operator)
    assert ("GET", "/api/v1/settings") in operator_routes and ("POST", "/api/v1/invites") in operator_routes
    assert len(operator_routes) > 25, "the guard is found on the routes (a floor: this list may grow, not shrink)"
    token = client.post("/api/v1/devices", json={"name": "phone"}).json()["token"]
    odd: list[str] = []
    with TestClient(app, base_url="http://testserver") as device:
        for method, path in operator_routes:
            answer = device.request(method, concrete(path), headers={"Authorization": f"Bearer {token}"},
                                    json={} if method in ("POST", "PUT", "PATCH") else None)
            code = answer.json().get("detail", {}).get("code") if answer.headers.get("content-type", "").startswith(
                "application/json") else None
            if (answer.status_code, code) != (403, "browser_only"):
                odd.append(f"{method} {path} -> {answer.status_code} {code}")
    assert odd == [], odd
    # The same account in its browser still gets in.
    assert client.get("/api/v1/settings").status_code == 200


def test_the_description_of_the_interface_is_the_snapshot() -> None:
    current = json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("NEXPAPER_RECORD_OPENAPI") == "1":
        SNAPSHOT.write_text(current, encoding="utf-8", newline="\n")
    assert SNAPSHOT.is_file(), "No snapshot of the description; record it (see the top of this file)."
    assert SNAPSHOT.read_text(encoding="utf-8") == current, (
        "The interface changed. If that is on purpose, renew the snapshot: "
        "NEXPAPER_RECORD_OPENAPI=1 python -m pytest tests/test_routes.py (and commit the file)."
    )


def test_the_description_is_served_and_names_the_ways_in() -> None:
    with TestClient(app, base_url="http://testserver") as client:
        answer = client.get("/api/v1/openapi.json")
        assert answer.status_code == 200 and answer.json()["info"]["title"] == "nexpaper"
        assert all(path.startswith("/api/v1/") for path in answer.json()["paths"])
        assert "HTTPBearer" in str(answer.json()["components"]["securitySchemes"])


def test_the_page_of_the_interface_needs_no_script_and_loads_nothing_from_elsewhere() -> None:
    with TestClient(app, base_url="http://testserver") as client:
        page = client.get("/api/v1/docs")
        assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
        text = page.text
        assert "<script" not in text and "http://" not in text and "https://" not in text
        assert "/api/v1/auth/login" in text and "Authorization: Bearer" in text
        policy = page.headers["content-security-policy"]
        assert "default-src 'self'" in policy and "script-src" not in policy


@pytest.mark.parametrize("path", ["/api/v1/me", "/api/v1/auth/me", "/api/v1/devices"])
def test_what_the_interface_answers_is_never_kept(path: str) -> None:
    with TestClient(app, base_url="http://testserver") as client:
        assert client.get(path).headers["cache-control"] == "no-store"
