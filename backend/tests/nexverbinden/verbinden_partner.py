"""The partner of the contract tests (copied into every app with them), and the reference app of the module: a nex app
of any name of the catalog, in one SQLite file, with the module
``verbinden`` mounted as an app mounts it. It is the partner every app is tested against, and the module tests itself
with it (as nextasks with nexnotes as partner). A worked example of an app's ``Store``: every method says in one line
what the app writes, the tables (``SCHEMA``) are the template for an app that has none.

What it has of its own: accounts (``owner`` "kim", ``other`` "sam", ``operator``), two areas of ``owner`` and one of
``other``, items in the areas, and for each purpose it grants a route ``GET /api/v1/purpose/<purpose>`` that answers
the items the connection may see. Its older form (before the module) had API keys (``old_keys``) and one connection
typed in by hand (``old_links``); ``older=True`` writes exactly that before the module starts.

The session of a browser is the header ``X-Ref-Session: <role>``: only here, never in an app."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient

ROLES = {"owner": (1, "kim"), "other": (2, "sam"), "operator": (3, "op")}
AREAS = {1: [(11, "Zuhause"), (12, "Garten")], 2: [(21, "Arbeit")], 3: [(31, "Betrieb")]}

#: The tables the older version wrote (an app's own, untouched by the module).
SCHEMA_BEFORE = """
CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT, operator INTEGER DEFAULT 0, blocked INTEGER DEFAULT 0);
CREATE TABLE areas (id INTEGER PRIMARY KEY, account_id INTEGER, name TEXT);
CREATE TABLE items (id INTEGER PRIMARY KEY, account_id INTEGER, area_id INTEGER, title TEXT);
CREATE TABLE settings (name TEXT PRIMARY KEY, value TEXT);
CREATE TABLE old_keys (token_hash TEXT PRIMARY KEY, account_id INTEGER, expires_at TEXT, retired INTEGER DEFAULT 0);
CREATE TABLE old_links (account_id INTEGER, partner TEXT, base TEXT, key_sealed TEXT, shown TEXT, expires_at TEXT,
                        problem TEXT, ok_at TEXT);
"""

#: The module's tables: the template for an app.
SCHEMA = """
CREATE TABLE IF NOT EXISTS vb_connections (
  id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, partner TEXT NOT NULL, partner_base TEXT NOT NULL,
  partner_account TEXT NOT NULL, uses TEXT NOT NULL, grants TEXT NOT NULL, areas_granted TEXT, areas_used TEXT,
  held TEXT NOT NULL, issued_access_hash TEXT NOT NULL UNIQUE, issued_refresh_hash TEXT NOT NULL UNIQUE,
  issued_access_expires TEXT NOT NULL, created_at TEXT NOT NULL, used_at TEXT, ok_at TEXT, state TEXT NOT NULL,
  stale_since TEXT, problem TEXT, partner_version TEXT NOT NULL DEFAULT '', UNIQUE (account_id, partner));
CREATE TABLE IF NOT EXISTS vb_pending (state_hash TEXT PRIMARY KEY, account_id INTEGER, partner TEXT,
  partner_base TEXT, verifier TEXT, areas_granted TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS vb_codes (code_hash TEXT PRIMARY KEY, account_id INTEGER, partner TEXT, partner_base TEXT,
  redirect_uri TEXT, challenge TEXT, areas_granted TEXT, expires_at TEXT);
CREATE TABLE IF NOT EXISTS vb_spent (token_hash TEXT PRIMARY KEY, connection_id TEXT, at INTEGER);
CREATE TABLE IF NOT EXISTS vb_waiting (id INTEGER PRIMARY KEY, account_id INTEGER, partner_base TEXT, token TEXT,
  since TEXT);
"""


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ReferenceStore:
    """The ``Store`` over the tables above."""

    def __init__(self, db: sqlite3.Connection, pkg: ModuleType) -> None:
        self.db = db
        self.pkg = pkg

    # --- connections ---------------------------------------------------------------------------------------------
    def _connection(self, row: sqlite3.Row | None) -> Any:
        if row is None:
            return None
        return self.pkg.Connection(
            id=row["id"],
            account_id=row["account_id"],
            partner=row["partner"],
            partner_base=row["partner_base"],
            partner_account=row["partner_account"],
            uses=tuple(json.loads(row["uses"])),
            grants=tuple(json.loads(row["grants"])),
            areas_granted=json.loads(row["areas_granted"]) if row["areas_granted"] else None,
            areas_used=json.loads(row["areas_used"]) if row["areas_used"] else None,
            held=row["held"],
            issued_access_hash=row["issued_access_hash"],
            issued_refresh_hash=row["issued_refresh_hash"],
            issued_access_expires=_when(row["issued_access_expires"]),
            created_at=_when(row["created_at"]),
            used_at=_when(row["used_at"]),
            ok_at=_when(row["ok_at"]),
            state=row["state"],
            stale_since=_when(row["stale_since"]),
            problem=row["problem"],
            partner_version=row["partner_version"],
        )

    def connections(self, account_id: Any) -> list[Any]:
        rows = self.db.execute("SELECT * FROM vb_connections WHERE account_id = ? ORDER BY partner", (account_id,))
        return [self._connection(row) for row in rows]

    def connection(self, account_id: Any, partner: str) -> Any:
        row = self.db.execute(
            "SELECT * FROM vb_connections WHERE account_id = ? AND partner = ?", (account_id, partner)
        ).fetchone()
        return self._connection(row)

    def by_issued_access(self, token_hash: str) -> Any:
        row = self.db.execute("SELECT * FROM vb_connections WHERE issued_access_hash = ?", (token_hash,)).fetchone()
        return self._connection(row)

    def by_issued_refresh(self, token_hash: str) -> Any:
        row = self.db.execute("SELECT * FROM vb_connections WHERE issued_refresh_hash = ?", (token_hash,)).fetchone()
        return self._connection(row)

    def save(self, c: Any) -> None:
        """Writes the connection (a new one, or changes to one)."""
        self.db.execute(
            "INSERT OR REPLACE INTO vb_connections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                c.id, c.account_id, c.partner, c.partner_base, c.partner_account, json.dumps(list(c.uses)),
                json.dumps(list(c.grants)), json.dumps(c.areas_granted) if c.areas_granted is not None else None,
                json.dumps(c.areas_used) if c.areas_used is not None else None, c.held, c.issued_access_hash,
                c.issued_refresh_hash, _iso(c.issued_access_expires), _iso(c.created_at), _iso(c.used_at),
                _iso(c.ok_at), c.state, _iso(c.stale_since), c.problem, c.partner_version,
            ),
        )  # fmt: skip

    def remove(self, connection_id: str) -> None:
        """Deletes the connection and what was spent for it."""
        self.db.execute("DELETE FROM vb_connections WHERE id = ?", (connection_id,))
        self.db.execute("DELETE FROM vb_spent WHERE connection_id = ?", (connection_id,))

    # --- started connections and codes ---------------------------------------------------------------------------
    def add_pending(self, p: Any) -> None:
        self.db.execute(
            "INSERT INTO vb_pending VALUES (?,?,?,?,?,?,?)",
            (p.state_hash, p.account_id, p.partner, p.partner_base, p.verifier,
             json.dumps(p.areas_granted) if p.areas_granted is not None else None, _iso(p.created_at)),
        )  # fmt: skip

    def take_pending(self, state_hash: str) -> Any:
        row = self.db.execute("SELECT * FROM vb_pending WHERE state_hash = ?", (state_hash,)).fetchone()
        if row is None:
            return None
        self.db.execute("DELETE FROM vb_pending WHERE state_hash = ?", (state_hash,))
        return self.pkg.Pending(
            state_hash=row["state_hash"],
            account_id=row["account_id"],
            partner=row["partner"],
            partner_base=row["partner_base"],
            verifier=row["verifier"],
            areas_granted=json.loads(row["areas_granted"]) if row["areas_granted"] else None,
            created_at=_when(row["created_at"]),
        )

    def add_code(self, c: Any) -> None:
        self.db.execute(
            "INSERT INTO vb_codes VALUES (?,?,?,?,?,?,?,?)",
            (c.code_hash, c.account_id, c.partner, c.partner_base, c.redirect_uri, c.challenge,
             json.dumps(c.areas_granted) if c.areas_granted is not None else None, _iso(c.expires_at)),
        )  # fmt: skip

    def take_code(self, code_hash: str) -> Any:
        row = self.db.execute("SELECT * FROM vb_codes WHERE code_hash = ?", (code_hash,)).fetchone()
        if row is None:
            return None
        self.db.execute("DELETE FROM vb_codes WHERE code_hash = ?", (code_hash,))
        return self.pkg.Code(
            code_hash=row["code_hash"],
            account_id=row["account_id"],
            partner=row["partner"],
            partner_base=row["partner_base"],
            redirect_uri=row["redirect_uri"],
            challenge=row["challenge"],
            areas_granted=json.loads(row["areas_granted"]) if row["areas_granted"] else None,
            expires_at=_when(row["expires_at"]),
        )

    # --- spent ----------------------------------------------------------------------------------------------------
    def spend(self, connection_id: str, token_hash: str, keep: int) -> None:
        """Remembers a spent code or refresh token; only the last ``keep`` per connection."""
        at = self.db.execute("SELECT COALESCE(MAX(at), 0) + 1 FROM vb_spent").fetchone()[0]
        self.db.execute("INSERT OR REPLACE INTO vb_spent VALUES (?,?,?)", (token_hash, connection_id, at))
        self.db.execute(
            "DELETE FROM vb_spent WHERE connection_id = ? AND at NOT IN "
            "(SELECT at FROM vb_spent WHERE connection_id = ? ORDER BY at DESC LIMIT ?)",
            (connection_id, connection_id, keep),
        )

    def spent_by(self, token_hash: str) -> str | None:
        row = self.db.execute("SELECT connection_id FROM vb_spent WHERE token_hash = ?", (token_hash,)).fetchone()
        return row[0] if row else None

    # --- waiting revocations ----------------------------------------------------------------------------------------
    def revoke_later(self, account_id: Any, partner_base: str, sealed_token: str, now: datetime) -> None:
        self.db.execute(
            "INSERT INTO vb_waiting (account_id, partner_base, token, since) VALUES (?,?,?,?)",
            (account_id, partner_base, sealed_token, _iso(now)),
        )

    def waiting(self) -> list[Any]:
        rows = self.db.execute("SELECT * FROM vb_waiting ORDER BY id")
        return [self.pkg.Waiting(row["id"], row["partner_base"], row["token"], _when(row["since"])) for row in rows]

    def done_waiting(self, waiting_id: Any) -> None:
        self.db.execute("DELETE FROM vb_waiting WHERE id = ?", (waiting_id,))

    # --- the account and the app -------------------------------------------------------------------------------------
    def account_may(self, account_id: Any) -> bool:
        row = self.db.execute("SELECT blocked FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return row is not None and not row[0]

    def account_name(self, account_id: Any) -> str:
        row = self.db.execute("SELECT name FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return row[0] if row else "?"

    def areas(self, account_id: Any) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT id, name FROM areas WHERE account_id = ? ORDER BY id", (account_id,))
        return [{"id": row[0], "name": row[1]} for row in rows]

    def legacy(self, account_id: Any) -> list[Any]:
        rows = self.db.execute("SELECT * FROM old_links WHERE account_id = ?", (account_id,))
        return [
            self.pkg.Legacy(
                partner=row["partner"],
                partner_base=row["base"],
                shown=row["shown"],
                expires_at=_when(row["expires_at"]),
                ok_at=_when(row["ok_at"]),
                problem=row["problem"],
            )
            for row in rows
        ]

    def retire_key(self, token: str) -> bool:
        """Marks an older API key as ended."""
        done = self.db.execute(
            "UPDATE old_keys SET retired = 1 WHERE token_hash = ? AND retired = 0", (_digest(token),)
        )
        return done.rowcount > 0

    def setting(self, name: str) -> Any:
        row = self.db.execute("SELECT value FROM settings WHERE name = ?", (name,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_setting(self, name: str, value: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (name, json.dumps(value)))

    def local_allowed(self) -> bool:
        return bool(self.setting("connections_local_network"))

    # The reference seals by encoding only; an app seals with its own key (nexnotes ``encrypt_secret``).
    def seal(self, text: str) -> str:
        return "sealed:" + base64.b64encode(text.encode("utf-8")[::-1]).decode("ascii")

    def unseal(self, sealed: str) -> str:
        return base64.b64decode(sealed.removeprefix("sealed:"))[::-1].decode("utf-8")

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()


class ReferenceApp:
    """One app of the catalog, e.g. ``ReferenceApp(pkg, "nextasks", "https://tasks.example.com", folder)``."""

    def __init__(
        self,
        pkg: ModuleType,
        name: str,
        base: str,
        folder: Path,
        *,
        older_link: str | None = None,
        in_use: tuple[str, ...] | None = None,
    ) -> None:
        self.pkg = pkg
        self.name = name
        self.base = base
        self.path = folder / f"{name}.sqlite3"
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.older_key = ""
        self._older(older_link)
        # The module starts: its tables come beside the app's, nothing of the app's own changes.
        self.db.executescript(SCHEMA)
        self.db.commit()
        self.store = ReferenceStore(self.db, pkg)
        self.config = pkg.AppConfig(
            app_name=name,
            version="2.0.0",
            access_prefix=f"r{name[3:5]}c_",
            refresh_prefix=f"r{name[3:5]}r_",
            code_prefix=f"r{name[3:5]}o_",
            in_use=in_use,
        )
        self.old_key_for: dict[str, str] = {}
        self.api = self._app()

    def _older(self, link_partner: str | None) -> None:
        """What the older version wrote: accounts, areas, items, an API key of ``owner``, maybe a link typed in."""
        self.db.executescript(SCHEMA_BEFORE)
        for role, (number, name) in ROLES.items():
            self.db.execute("INSERT INTO accounts VALUES (?, ?, ?, 0)", (number, name, int(role == "operator")))
            for area, title in AREAS[number]:
                self.db.execute("INSERT INTO areas VALUES (?, ?, ?)", (area, number, title))
                self.db.execute(
                    "INSERT INTO items (account_id, area_id, title) VALUES (?, ?, ?)", (number, area, title)
                )
        self.older_key = f"old_{self.name}_" + "k" * 24
        later = datetime.now(UTC) + timedelta(days=90)
        self.db.execute("INSERT INTO old_keys VALUES (?, 1, ?, 0)", (_digest(self.older_key), later.isoformat()))
        if link_partner:
            soon = datetime.now(UTC) + timedelta(days=5)
            self.db.execute(
                "INSERT INTO old_links VALUES (1, ?, ?, ?, ?, ?, NULL, ?)",
                (link_partner, f"https://{link_partner}.example.com", "sealed-by-the-app", "ntk_AbCd",
                 soon.isoformat(), datetime.now(UTC).isoformat()),
            )  # fmt: skip
        self.db.commit()

    def tables_before(self) -> dict[str, list[tuple[Any, ...]]]:
        """Every row of the app's own tables (for the test that the module leaves them alone)."""
        names = ("accounts", "areas", "items", "old_keys", "old_links")
        return {name: [tuple(row) for row in self.db.execute(f"SELECT * FROM {name}")] for name in names}  # noqa: S608

    def everything(self) -> str:
        """All text the app keeps, for the test that no token stands in it unsealed."""
        return "\n".join(line for line in self.db.iterdump())

    def block(self, role: str, blocked: bool = True) -> None:
        self.db.execute("UPDATE accounts SET blocked = ? WHERE id = ?", (int(blocked), ROLES[role][0]))
        self.db.commit()

    def client(self, role: str | None = None) -> TestClient:
        headers = {"X-Ref-Session": role} if role else {}
        return TestClient(self.api, base_url=self.base, headers=headers)

    def _app(self) -> FastAPI:
        app = FastAPI()
        pkg = self.pkg
        api = importlib.import_module(f"{pkg.__name__}.api")

        def store() -> ReferenceStore:
            return self.store

        def account(x_ref_session: str | None = Header(default=None)) -> Any:
            if x_ref_session not in ROLES:
                raise HTTPException(status_code=401, detail={"code": "signed_out", "message": "Sign in."})
            number = ROLES[x_ref_session][0]
            if not self.store.account_may(number):
                raise HTTPException(status_code=401, detail={"code": "signed_out", "message": "Sign in."})
            return type("Account", (), {"id": number, "role": x_ref_session})()

        def operator(signed_in: Any = Depends(account)) -> Any:  # noqa: B008 (FastAPI's form)
            if signed_in.role != "operator":
                raise HTTPException(status_code=403, detail={"code": "operators_only", "message": "Operators only."})
            return signed_in

        app.include_router(
            api.router(
                config=self.config,
                store=store,
                account=account,
                operator=operator,
                address=lambda request: self.base,
                old_key=lambda data, who, partner: self.old_key_for.get(partner),
            )
        )

        def caller(request: Request) -> Any:
            header = request.headers.get("authorization", "")
            given = header[7:].strip() if header[:7].lower() == "bearer " else ""
            row = self.db.execute(
                "SELECT account_id, expires_at FROM old_keys WHERE token_hash = ? AND retired = 0", (_digest(given),)
            ).fetchone()
            if row is not None and datetime.fromisoformat(row[1]) > datetime.now(UTC):
                # An API key of the older version: all of its account, as before.
                return pkg.Caller(row[0], "", "", tuple(pkg.PURPOSES[self.name]), None, "write")
            try:
                return pkg.authenticate(self.store, self.config, given, datetime.now(UTC))
            except pkg.Refused as refusal:
                raise HTTPException(status_code=refusal.status, detail=refusal.as_dict()) from None

        @app.get("/api/v1/me")
        def me(found: Any = Depends(caller)) -> dict:  # noqa: B008
            return {"app": self.name, "account": self.store.account_name(found.account_id), "level": found.level}

        @app.get("/api/v1/purpose/{purpose}")
        def by_purpose(purpose: str, found: Any = Depends(caller)) -> dict:  # noqa: B008
            try:
                pkg.require(found, purpose)
            except pkg.Refused as refusal:
                raise HTTPException(status_code=refusal.status, detail=refusal.as_dict()) from None
            rows = self.db.execute(
                "SELECT area_id, title FROM items WHERE account_id = ? ORDER BY id", (found.account_id,)
            )
            shown = [{"area": row[0], "title": row[1]} for row in rows if found.areas is None or row[0] in found.areas]
            return {"purpose": purpose, "items": shown}

        return app
