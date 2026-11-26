"""What the contract tests ask of an app: the ``StandardAdapter`` the app's adapter extends, and helpers for MCP and
OAuth. The tests run the module inside the app: its own start, sessions and operators, its own check of keys and
``Store`` over its own tables, its own tools, the module's routes mounted from ``nexmcp.api``. Above all they prove
that **every key and every connected program made before still works** (``legacy_keys``, ``legacy_program``). They
never change; the app fills in its adapter (``backend/tests/nexmcp_adapter.py``)."""

from __future__ import annotations

import base64
import hashlib
import importlib
import secrets
from dataclasses import dataclass
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlsplit


@dataclass(frozen=True)
class LegacyKey:
    """A form of key that opened ``/api/mcp`` before the module (an MCP key made by hand, an API key with "also for
    MCP"), for the test's name and the adapter's ``make_legacy``."""

    label: str
    #: The app's own word for the form (the adapter's choice).
    form: str


@dataclass(frozen=True)
class LegacyProgram:
    """A program the older version connected: its client, where it returns to, and its current refresh token."""

    client_id: str
    redirect_uri: str
    refresh_token: str


class StandardAdapter:
    """Defaults; every method marked ``APP`` is the app's to write."""

    package = "app.vendor.nexmcp"
    #: Where the module ``schluessel`` mounts its routes (MCP keys are made there).
    keys_prefix = "/api/connections"
    #: ``nexmcp.api.router(prefix=…)``.
    prefix = "/api/connections/mcp"
    #: The operator can take AI from an account ("KI erlaubt": nexmail, nexpaper, nexdiary, nexlore).
    has_ai = False
    #: The older version had MCP on without anybody switching it on (nexnotes, nextime): after the update an
    #: installation keeps it on (decision 5).
    older_had_mcp_on = False

    def start(self) -> None:
        """APP: a freshly installed app, started as in production, with ``owner``, ``other`` (members, passwords,
        no second factor) and ``operator``; each with something to read (notes, events, tasks …)."""
        raise NotImplementedError("APP: start")

    def start_older(self) -> None:
        """APP: the app as the older version left it (its database written by the older version, nothing switched
        on by hand), then started as the new version on it. Only where ``legacy_keys`` or ``legacy_program`` or
        ``older_had_mcp_on`` have something to show."""
        raise NotImplementedError("APP: start_older")

    def stop(self) -> None:
        """APP: close the database, remove temporary folders."""

    def client(self, role: str) -> Any:
        """APP: a ``TestClient`` as ``owner``, ``other``, ``operator`` (browser sessions) or ``anonymous``."""
        raise NotImplementedError("APP: client")

    def config(self) -> Any:
        """APP: the app's ``nexmcp.AppConfig``."""
        raise NotImplementedError("APP: config")

    def keys_config(self) -> Any:
        """APP: the app's ``nexschluessel.AppConfig``."""
        raise NotImplementedError("APP: keys_config")

    def read_call(self) -> tuple[str, dict[str, Any]]:
        """APP: a call of a reading tool that finds something of ``owner`` (name, arguments)."""
        raise NotImplementedError("APP: read_call")

    def change_call(self) -> tuple[str, dict[str, Any]]:
        """APP: a call of a changing tool (level above the lowest) that works for ``owner``."""
        raise NotImplementedError("APP: change_call")

    def foreign_call(self) -> tuple[str, dict[str, Any]]:
        """APP: a call of a reading tool about something of ``other`` that ``owner`` may not read."""
        raise NotImplementedError("APP: foreign_call")

    def dangerous_call(self) -> tuple[str, dict[str, Any]] | None:
        """APP: a call of a tool that calls it dangerous (``Tool.dangerous``) and works for ``owner``; ``None`` where
        no tool of the app does."""
        return None

    def legacy_keys(self) -> list[LegacyKey]:
        """APP: every form of key that opened MCP before (empty for an app new to MCP)."""
        return []

    def make_legacy(self, spec: LegacyKey) -> str:
        """APP: on the app started by ``start_older``, the secret of a key of ``spec`` for ``owner``, written the way
        the older version wrote it (before ``start_older`` started the new version)."""
        raise NotImplementedError("APP: make_legacy")

    def legacy_program(self) -> LegacyProgram | None:
        """APP: on the app started by ``start_older``, a program of ``owner`` connected by the older version (``None``
        for an app that had no OAuth)."""
        return None

    def take_ai(self, account: str = "owner") -> None:
        raise NotImplementedError("APP: take_ai")

    def give_ai(self, account: str = "owner") -> None:
        raise NotImplementedError("APP: give_ai")

    def refusal(self, answer: Any) -> dict:
        """The body of a refusal of the module's own pages (default: FastAPI's ``detail``)."""
        return answer.json()["detail"]


def package(adapter: Any) -> ModuleType:
    found = importlib.import_module(adapter.package)
    importlib.import_module(f"{adapter.package}.api")
    return found


# --- helpers ----------------------------------------------------------------------------------------------------------


def switch_mcp(app: Any, on: bool) -> None:
    answer = app.client("operator").put(f"{app.keys_prefix}/interfaces", json={"mcp": on})
    assert answer.status_code == 200, answer.text


def mcp_key(app: Any, *, right: str | None = None, options: dict[str, bool] | None = None, role: str = "owner") -> Any:
    """A new MCP key by hand, through the module ``schluessel`` (decision 6)."""
    body: dict[str, Any] = {"kind": "mcp", "name": "Probe"}
    if right:
        body["right"] = right
    if options:
        body["options"] = options
    made = app.client(role).post(f"{app.keys_prefix}/keys", json=body)
    assert made.status_code == 201, made.text
    return made.json()


def rpc(app: Any, secret: str | None, method: str, params: dict | None = None, **headers: str) -> Any:
    sent = {"Content-Type": "application/json", **headers}
    if secret:
        sent["Authorization"] = f"Bearer {secret}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return app.client("anonymous").post(app.config().mcp_path, json=body, headers=sent)


def call(app: Any, secret: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    answer = rpc(app, secret, "tools/call", {"name": name, "arguments": args})
    assert answer.status_code == 200, answer.text
    return answer.json()["result"]


def names(app: Any, secret: str) -> set[str]:
    answer = rpc(app, secret, "tools/list")
    assert answer.status_code == 200, answer.text
    return {tool["name"] for tool in answer.json()["result"]["tools"]}


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    made = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, made


REDIRECT = "http://127.0.0.1:33418/callback"


def register(app: Any, redirect: str = REDIRECT) -> str:
    answer = app.client("anonymous").post(
        f"{app.config().oauth_prefix}/register", json={"client_name": "Probe client", "redirect_uris": [redirect]}
    )
    assert answer.status_code == 201, answer.text
    return str(answer.json()["client_id"])


def consent(app: Any, client_id: str, *, role: str = "owner", **choice: Any) -> tuple[str, str]:
    """The account agrees on the consent page; returns the code and the verifier."""
    verifier, challenge = pkce()
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "s1",
    }
    shown = app.client(role).get(f"{app.config().oauth_prefix}/authorize", params=params)
    assert shown.status_code == 200, shown.text
    answer = app.client(role).post(f"{app.config().oauth_prefix}/authorize", json={**params, "allow": True, **choice})
    assert answer.status_code == 200, answer.text
    query = parse_qs(urlsplit(answer.json()["redirect"]).query)
    assert query["state"] == ["s1"]
    return query["code"][0], verifier


def trade(app: Any, client_id: str, code: str, verifier: str) -> Any:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    return app.client("anonymous").post(f"{app.config().oauth_prefix}/token", data=form)


def refresh(app: Any, client_id: str, token: str) -> Any:
    form = {"grant_type": "refresh_token", "refresh_token": token, "client_id": client_id}
    return app.client("anonymous").post(f"{app.config().oauth_prefix}/token", data=form)


def connect(app: Any, **choice: Any) -> tuple[str, dict[str, Any]]:
    """A program registers, the owner agrees, the code is traded: ``(client_id, tokens)``."""
    client_id = register(app)
    code, verifier = consent(app, client_id, **choice)
    traded = trade(app, client_id, code, verifier)
    assert traded.status_code == 200, traded.text
    return client_id, traded.json()
