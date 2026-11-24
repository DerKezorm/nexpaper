"""Builds the "Bestand" test database with the code that is checked out right now.

The test ``tests/test_bestand.py`` loads what this script wrote and checks that every way in that worked in that
version still works in the running one. That only means something if the database comes from the OLD code:

    git worktree add ../nexpaper-1.12.0 v1.12.0
    cd ../nexpaper-1.12.0/backend
    <venv>/python tests/bestand/build.py --target <this repo>/backend/tests/bestand

**Never rebuild it with a newer version and commit the result.** It would then describe the new schema, and the
test would prove nothing about installations that run 1.12.0 today. The script refuses to run when ``__version__`` is
not ``VERSION``; a fixture for a later version gets its own file name.

Only invented people and ``example.*`` addresses. Every random value the test must know (session cookies, device
and API tokens, invitation, reset and confirmation links, the second factor, recovery codes) is made predictable by
replacing ``secrets`` in the few modules that draw them; the code paths themselves are those of the version.
Password hashes and ids stay as the version makes them.

**Stored as gzip'ed SQL, not as ``.db``.** ``.gitignore`` and the guard tests keep databases out of the repository,
and the commit hook refuses 32+ hex characters in a text diff, which every token hash in a plain dump is. The search
index is left out; every start of every version since schema 6 makes it anew (``db._init``).
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

HERE = Path(__file__).resolve().parent
VERSION = "1.12.0"
#: The same as ``tests/conftest.py``: the second factor's seed and the provider's client secret are sealed with it.
TEST_KEY = "test-secret-key-for-the-test-run-only"
ISSUER = "https://sso.example.com"
CLIENT_ID = "nexpaper-bestand"
CLIENT_PASS = "bestand-client"
SLUG = "sso"
TAB = {"X-Nexpaper-Client": "tab-bestand0"}


def dump_file(folder: Path = HERE) -> Path:
    return folder / f"bestand-{VERSION}.sql.gz"


def manifest_file(folder: Path = HERE) -> Path:
    return folder / f"bestand-{VERSION}.json"


def totp_seed(label: str) -> str:
    """The seed of an account's second factor in the fixture, derived instead of stored (no secret-looking value in
    Git). The same form as ``totp.generate_seed``: base32 of 20 bytes, no padding."""
    return base64.b32encode(hashlib.sha256(f"bestand-totp-{label}".encode()).digest()[:20]).decode().rstrip("=")


class FixedChance:
    """Stands in for ``secrets`` in the modules that hand out values the test must know.

    ``token_urlsafe`` returns ``bestand-<label>-<n>``, ``n`` counting every value drawn, so two values never meet
    (a session per sign-in) and each says what it was for. ``choice`` walks the alphabet (recovery codes). Everything
    else is the real module, ``compare_digest`` included.
    """

    def __init__(self) -> None:
        self.label = "unnamed"
        self._count = 0
        self._step = 0

    def token_urlsafe(self, nbytes: int | None = None) -> str:
        self._count += 1
        return f"bestand-{self.label}-{self._count}"

    def choice(self, sequence: Any) -> Any:
        self._step += 1
        return sequence[(self._step * 7) % len(sequence)]

    def __getattr__(self, name: str) -> Any:
        return getattr(secrets, name)


def _environment(data: Path) -> None:
    os.environ["NEXPAPER_DATA_DIR"] = str(data)
    os.environ["NEXPAPER_DISABLE_BACKGROUND"] = "1"
    os.environ["NEXPAPER_FRONTEND_DIST"] = str(data / "no-frontend")
    os.environ["NEXPAPER_LOCALES_DIR"] = str(data / "locales")
    os.environ["NEXPAPER_LOG_LEVEL"] = ""
    os.environ["NEXPAPER_ARGON2_TIME"] = "1"
    os.environ["NEXPAPER_ARGON2_MEMORY_KIB"] = "1024"
    os.environ["NEXPAPER_ARGON2_PARALLELISM"] = "1"
    os.environ["NEXPAPER_UPDATE_URL"] = "http://127.0.0.1:9/releases/latest"
    os.environ["NEXPAPER_SECRET_KEY"] = TEST_KEY
    os.environ["NEXPAPER_SETUP_TOKEN"] = "bestand-setup"


def build(target: Path) -> None:
    data = Path(tempfile.mkdtemp(prefix="nexpaper-bestand-"))
    _environment(data)
    backend = HERE.parent.parent
    sys.path.insert(0, str(backend))
    sys.path.insert(0, str(backend / "tests" / "nexoidc"))

    import oidc_fakes as fakes
    from fastapi.testclient import TestClient

    from app import __version__, security
    from app.db import SessionLocal, engine, init_db
    from app.main import app
    from app.models import Account
    from app.services import accounts, apikeys, devices, emails, resets, settings_service, totp
    from app.vendor import nexoidc
    from app.vendor.nexoidc import attempt, protocol

    if __version__ != VERSION:
        sys.exit(f"This is nexpaper {__version__}; the fixture describes {VERSION}. Check out v{VERSION} first.")

    chance = FixedChance()
    for module in (security, accounts, apikeys, devices, emails, resets, totp):
        module.secrets = chance  # type: ignore[attr-defined]
    totp.generate_seed = lambda: totp_seed(chance.label)

    network = fakes.Network()
    nexoidc.use_transport(network.transport())
    protocol.clear_caches()
    attempt.forget_used_states()
    fake = network.add(fakes.FakeProvider(ISSUER, client_id=CLIENT_ID, client_secret=CLIENT_PASS))

    init_db()
    with SessionLocal() as db:
        # Most installations at home: no mail server, a second factor not required (the operator has one all the same),
        # API keys switched on, signing in with a password on.
        settings_service.save(db, {"two_factor_required": False, "api_keys_allowed": True, "password_login": True})

    people: list[dict[str, Any]] = []

    def browser(host: str = "198.51.100.10") -> TestClient:
        return TestClient(app, base_url="http://testserver", headers=TAB, follow_redirects=False,
                          client=(host, 50000))

    def ok(answer: Any, *codes: int) -> Any:
        assert answer.status_code in (codes or (200,)), (answer.status_code, answer.text[:300])
        return answer

    def row_of(name: str) -> Account:
        with SessionLocal() as db:
            found = db.query(Account).filter_by(name=name).one()
            db.expunge(found)
        return found

    def confirm_address(name: str, address: str, label: str) -> None:
        """The person's own address, confirmed by the link 1.12.0 mails (mail itself left out)."""
        chance.label = label
        with SessionLocal() as db:
            found = db.query(Account).filter_by(name=name).one()
            _made, token = emails.start(db, found, address)
            assert emails.confirm(db, token) is not None

    # --- The operator: setup code, password, own confirmed address, second factor with recovery codes -------------
    operator_pw = "Bestand-betreiber-2026"
    desk = browser()
    chance.label = "session-betreiber"
    ok(desk.post("/api/v1/setup", json={"name": "betreiber", "password": operator_pw, "code": "bestand-setup",
                                        "language": "de"}))
    confirm_address("betreiber", "betrieb@example.com", "email-betreiber")
    chance.label = "totp-betreiber"
    seed = ok(desk.post("/api/v1/auth/totp/begin")).json()["secret"]
    assert seed == totp_seed("totp-betreiber")
    code = totp.code_at(seed, __import__("time").time())
    codes = ok(desk.post("/api/v1/auth/totp/confirm", json={"code": code, "password": operator_pw})).json()
    people.append({"name": "betreiber", "password": operator_pw, "email": "betrieb@example.com",
                   "email_confirmed": True, "operator": True, "second_factor": "totp-betreiber",
                   "recovery_codes": codes["recovery_codes"],
                   "case": "operator, password, own confirmed address, second factor with recovery codes"})

    # --- A provider for the sign-in through OIDC -------------------------------------------------------------------
    ok(desk.post("/api/v1/oidc/admin/providers", json={
        "label": "SSO", "slug": SLUG, "issuer": ISSUER, "client_id": CLIENT_ID, "client_secret": CLIENT_PASS,
        "auto_create": True}), 201)

    def invite(label: str, email: str = "") -> str:
        chance.label = label
        made = ok(desk.post("/api/v1/invites", json={"days": 7, "email": email}), 201).json()
        return str(made["link"]).rsplit("/", 1)[1]

    def accept(token: str, name: str, password: str) -> TestClient:
        person = browser(f"198.51.100.{20 + len(people)}")
        chance.label = f"session-{name}"
        ok(person.post(f"/api/v1/invite/{token}", json={"name": name, "password": password}))
        return person

    # --- anna: own confirmed address, API key, paired iPhone, a link she asked for herself -------------------------
    anna_pw = "Bestand-anna-2026"
    accept(invite("invite-anna", "anna@example.com"), "anna", anna_pw)
    confirm_address("anna", "anna@example.com", "email-anna")
    with SessionLocal() as db:
        found = db.query(Account).filter_by(name="anna").one()
        chance.label = "api-anna"
        _key, api_token = apikeys.make(db, found, "Skript", "read")
        chance.label = "device-anna"
        _device, device_token = devices.make(db, found, "iPhone von Anna")
        chance.label = "reset-self-anna"
        _reset, anna_reset = resets.make(db, found)
    people.append({"name": "anna", "password": anna_pw, "email": "anna@example.com", "email_confirmed": True,
                   "api_key": api_token, "device": device_token, "reset_link": anna_reset,
                   "case": "password, own confirmed address, API key, paired iPhone, open link asked for herself"})

    # --- ben: the address of his invitation (typed by the operator, never confirmed), a link from the operator -----
    ben_pw = "Bestand-ben-2026x"
    accept(invite("invite-ben", "ben@example.net"), "ben", ben_pw)
    chance.label = "reset-operator-ben"
    sent = ok(desk.post(f"/api/v1/accounts/{row_of('ben').id}/reset-link", json={"current_password": operator_pw}))
    assert sent.json()["sent"] is False
    people.append({"name": "ben", "password": ben_pw, "email": "ben@example.net", "email_confirmed": False,
                   "reset_link": str(sent.json()["link"]).rsplit("/", 1)[1],
                   "case": "password, the invitation's address (not confirmed), open link the operator made"})

    # --- carla and dora: one address of a family; carla's from the invitation, dora's confirmed by its link -------
    carla_pw = "Bestand-carla-2026"
    accept(invite("invite-carla", "familie@example.org"), "carla", carla_pw)
    people.append({"name": "carla", "password": carla_pw, "email": "familie@example.org", "email_confirmed": False,
                   "shared_email": True, "case": "address shared with dora, from the invitation (not confirmed)"})
    dora_pw = "Bestand-dora-2026x"
    accept(invite("invite-dora"), "dora", dora_pw)
    confirm_address("dora", "Familie@Example.org", "email-dora")
    people.append({"name": "dora", "password": dora_pw, "email": "Familie@Example.org", "email_confirmed": True,
                   "shared_email": True, "case": "address shared with carla in other case, confirmed by its link"})

    # --- emil: no address, a new one waiting for its link, an open browser session ---------------------------------
    emil_pw = "Bestand-emil-2026x"
    emil = accept(invite("invite-emil"), "emil", emil_pw)
    session = emil.cookies.get(security.SESSION_COOKIE)
    assert session
    chance.label = "email-emil"
    with SessionLocal() as db:
        found = db.query(Account).filter_by(name="emil").one()
        _made, emil_link = emails.start(db, found, "emil@example.com")
    people.append({"name": "emil", "password": emil_pw, "email": "", "email_confirmed": False,
                   "pending_email": "emil@example.com", "pending_link": emil_link, "session": session,
                   "case": "password, no address, a new address waiting for its link, open browser session"})

    # --- fritz: through the provider only (made by it), the provider's address ------------------------------------
    def through_provider(client: TestClient, person: dict[str, Any]) -> Any:
        fake.person = dict(person)
        start = ok(client.get(f"/api/v1/oidc/{SLUG}/start"), 302, 303, 307)
        at_provider = start.headers["location"]
        path = urlsplit(fakes.query_of(at_provider)["redirect_uri"]).path
        return client.get(f"{path}?{urlencode(fake.authorize(at_provider))}")

    fritz_at_provider = {"sub": "bestand-fritz", "preferred_username": "fritz", "name": "Fritz Faber",
                         "email": "fritz@example.com", "email_verified": True}
    chance.label = "session-fritz"
    back = through_provider(browser("198.51.100.60"), fritz_at_provider)
    assert back.status_code in (302, 303) and "error" not in back.headers["location"], back.headers.get("location")
    people.append({"name": "fritz", "password": "", "email": "fritz@example.com", "email_confirmed": False,
                   "provider": fritz_at_provider,
                   "case": "provider only, made by it, its address (from the provider, not confirmed)"})

    # --- greta: password and a link to the provider -----------------------------------------------------------------
    greta_pw = "Bestand-greta-2026"
    greta = accept(invite("invite-greta", "greta@example.com"), "greta", greta_pw)
    greta_at_provider = {"sub": "bestand-greta", "preferred_username": "greta.g", "name": "Greta",
                         "email": "greta@example.com"}
    fake.person = dict(greta_at_provider)
    asked = ok(greta.post(f"/api/v1/oidc/{SLUG}/link", json={"password": greta_pw}))
    target_url = asked.json()["url"]
    path = urlsplit(fakes.query_of(target_url)["redirect_uri"]).path
    linked = greta.get(f"{path}?{urlencode(fake.authorize(target_url))}")
    assert linked.status_code in (302, 303) and "error" not in linked.headers["location"], linked.headers.get("location")
    people.append({"name": "greta", "password": greta_pw, "email": "greta@example.com", "email_confirmed": False,
                   "provider": greta_at_provider, "case": "password and provider, the invitation's address"})

    # --- hans: blocked by the operator ------------------------------------------------------------------------------
    hans_pw = "Bestand-hans-2026x"
    accept(invite("invite-hans", "hans@example.com"), "hans", hans_pw)
    ok(desk.post(f"/api/v1/accounts/{row_of('hans').id}/block", json={"current_password": operator_pw}), 204)
    people.append({"name": "hans", "password": hans_pw, "email": "hans@example.com", "email_confirmed": False,
                   "blocked": True, "case": "blocked by the operator"})

    # --- ida: deleted by the operator (nexpaper deletes; there is no deleted state) -----------------------------------
    ida_pw = "Bestand-ida-2026xx"
    accept(invite("invite-ida"), "ida", ida_pw)
    gone = desk.request("DELETE", f"/api/v1/accounts/{row_of('ida').id}",
                        json={"current_password": operator_pw, "confirm_name": "ida"})
    ok(gone, 204)
    deleted = {"name": "ida", "password": ida_pw, "case": "deleted by the operator: no row is left"}

    # --- Open invitations --------------------------------------------------------------------------------------------
    open_with = invite("invite-open-with", "neu@example.com")
    open_without = invite("invite-open-without")

    engine.dispose()
    nexoidc.use_transport(None)
    _write(data / "nexpaper.db", target)
    manifest = {
        "version": VERSION,
        "test_key": "tests/conftest.py (NEXPAPER_SECRET_KEY)",
        "provider": {"slug": SLUG, "issuer": ISSUER, "client_id": CLIENT_ID, "client_pass": CLIENT_PASS},
        "settings": {"two_factor_required": False, "api_keys_allowed": True, "password_login": True,
                     "mail": "none"},
        "accounts": people,
        "deleted": deleted,
        "open_invites": [{"token": open_with, "email": "neu@example.com"}, {"token": open_without, "email": ""}],
        "not_covered": "passkeys (need an authenticator; they hang on the account id like the second factor)",
    }
    manifest_file(target).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    shutil.rmtree(data, ignore_errors=True)
    print(f"Written: {dump_file(target)} and {manifest_file(target)}")


def _write(database: Path, target: Path) -> None:
    """The database as SQL without the search index, gzip'ed with a fixed time stamp."""
    copy = Path(tempfile.mkdtemp(prefix="nexpaper-bestand-copy-")) / "copy.db"
    source = sqlite3.connect(str(database))
    plain = sqlite3.connect(str(copy))
    try:
        source.backup(plain)
    finally:
        source.close()
    try:
        plain.execute("DROP TRIGGER IF EXISTS documents_search_gone")
        plain.execute("DROP TABLE IF EXISTS doc_fts")
        plain.execute("DROP TABLE IF EXISTS doc_tri")
        plain.commit()
        version = int(plain.execute("PRAGMA user_version").fetchone()[0])
        lines = list(plain.iterdump())
    finally:
        plain.close()
    text = "\n".join(lines) + f"\nPRAGMA user_version = {version};\n"
    target.mkdir(parents=True, exist_ok=True)
    with dump_file(target).open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as packed:
        packed.write(text.encode("utf-8"))
    shutil.rmtree(copy.parent, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--target", type=Path, default=HERE)
    build(parser.parse_args().target.resolve())


if __name__ == "__main__":
    main()
