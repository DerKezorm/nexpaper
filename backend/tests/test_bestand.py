"""Test "Bestand": every way in that worked in 1.12.0 still works in the running version.

The database comes from 1.12.0 itself (``tests/bestand/build.py``, stored as ``bestand-1.12.0.sql.gz``; the accounts
and their test values in ``bestand-1.12.0.json``). Each test loads it in place of the test database and then starts
the schema upkeep exactly as a container start after an update does (``init_db``). Then it signs in the way each
account could before: name and password (any case), second factor and recovery code, a provider, an open browser
session, a paired iPhone, an API key, an open invitation, an open link for a new password (made by the operator and
asked for by the person), an address waiting for its link, "Forgot your password?" by name and by address.

**Nothing here may be adapted to make a new version pass.** A red test means: an installation that runs 1.12.0 today
loses a way in after the update. Change the code, not the test. The only part that may change is the block at the
end (``AFTER_THE_CHANGE``): ways in that 1.12.0 did not have and that the shared account module brings. When the
module is wired in they pass, ``strict`` turns that red, and whoever wired it removes the marker.

**The fixture ages.** Sessions, invitations and links run out; loading pushes those dates into the future, nothing else
is touched before the start.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import SessionLocal, engine, init_db
from app.main import app
from app.models import Account
from app.security import MAX_FAILURES, SESSION_COOKIE
from app.services import notices, settings_service, totp
from app.vendor import nexoidc
from app.vendor.nexoidc import attempt, protocol

from .bestand.build import dump_file, manifest_file, totp_seed
from .oidc_helpers import fakes

MANIFEST = json.loads(manifest_file().read_text(encoding="utf-8"))
ACCOUNTS: list[dict[str, Any]] = MANIFEST["accounts"]
PROVIDER = MANIFEST["provider"]
TAB = {"X-Nexpaper-Client": "tab-bestand0"}
PUBLIC = "https://paper.example.com"
NEW_PASSWORD = "Bestand-ganz-neu-2026"

WITH_PASSWORD = [a for a in ACCOUNTS if a["password"] and not a.get("blocked")]
WITH_FACTOR = [a for a in ACCOUNTS if a.get("second_factor")]
WITH_PROVIDER = [a for a in ACCOUNTS if a.get("provider")]
MEMBERS_WITH_PASSWORD = [a for a in WITH_PASSWORD if not a.get("operator")]
#: Accounts with an address that no other account has (case ignored), confirmed or not.
_COUNT: dict[str, int] = {}
for _a in ACCOUNTS:
    if _a["email"]:
        _COUNT[_a["email"].lower()] = _COUNT.get(_a["email"].lower(), 0) + 1
UNIQUE_ADDRESS = [a for a in WITH_PASSWORD if a["email"] and _COUNT[a["email"].lower()] == 1]
UNIQUE_CONFIRMED = [a for a in UNIQUE_ADDRESS if a["email_confirmed"]]
SHARED_ADDRESS = [a for a in WITH_PASSWORD if a["email"] and _COUNT[a["email"].lower()] > 1]

#: The tables whose rows the start must leave as they are (nothing renamed, nothing deleted).
COUNTED = ("users", "vaults", "vault_members", "auth_sessions", "invites", "password_resets", "email_confirmations",
           "api_keys", "devices", "oidc_providers", "oidc_links", "settings")


def _name(account: dict[str, Any]) -> str:
    return str(account["name"])


def _schema(path: Path) -> tuple[dict[str, set[str]], dict[str, int]]:
    plain = sqlite3.connect(str(path))
    try:
        tables = [row[0] for row in plain.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE 'doc_fts%' AND name NOT LIKE 'doc_tri%'")]
        columns = {t: {row[1] for row in plain.execute(f'PRAGMA table_info("{t}")')} for t in tables}
        # Table names from COUNTED, never from outside.
        counts = {t: plain.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in COUNTED if t in columns}  # noqa: S608
    finally:
        plain.close()
    return columns, counts


@pytest.fixture
def bestand() -> tuple[dict[str, set[str]], dict[str, int]]:
    """The 1.12.0 database in place of the test database, then the start of the running version. Gives what the old
    database held (columns per table, rows per counted table), read before the start."""
    folder = Path(tempfile.mkdtemp(prefix="nexpaper-bestand-load-"))
    loaded = folder / "bestand.db"
    plain = sqlite3.connect(str(loaded))
    try:
        plain.executescript(gzip.decompress(dump_file().read_bytes()).decode("utf-8"))
        plain.execute("UPDATE auth_sessions SET expires_at = datetime('now', '+30 days')")
        plain.execute("UPDATE invites SET expires_at = datetime('now', '+7 days')")
        plain.execute("UPDATE password_resets SET expires_at = datetime('now', '+20 hours')")
        plain.execute("UPDATE email_confirmations SET expires_at = datetime('now', '+20 hours')")
        # A paired device rests after 365 days unused.
        plain.execute("UPDATE devices SET last_used_at = datetime('now')")
        plain.commit()
    finally:
        plain.close()
    before = _schema(loaded)
    engine.dispose()
    target = get_settings().database_path
    source = sqlite3.connect(str(loaded))
    into = sqlite3.connect(str(target))
    try:
        source.backup(into)
    finally:
        source.close()
        into.close()
    engine.dispose()
    init_db()
    return before


@pytest.fixture
def provider() -> Iterator[Any]:
    network = fakes.Network()
    nexoidc.use_transport(network.transport())
    protocol.clear_caches()
    attempt.forget_used_states()
    fake = network.add(fakes.FakeProvider(PROVIDER["issuer"], client_id=PROVIDER["client_id"],
                                          client_secret=PROVIDER["client_pass"]))
    yield fake
    nexoidc.use_transport(None)
    protocol.clear_caches()
    attempt.forget_used_states()


@pytest.fixture
def post(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Mail is set up (the fixture has none) and goes into a list instead of out."""
    sent: list[dict[str, Any]] = []

    def send_reset(_db: Any, to: str, link: str, *, name: str, hours: int) -> None:
        sent.append({"to": to, "link": link, "name": name, "hours": hours})

    monkeypatch.setattr(mailer, "send_reset", send_reset)
    with SessionLocal() as db:
        settings_service.save(db, {"smtp_host": "mail.example.com", "smtp_from": "paper@example.com",
                                   "public_url": PUBLIC})
    return sent


_hosts = iter(range(1, 250))


def browser() -> TestClient:
    """A browser of its own, from an address of its own (the brake per address is not what these tests are about)."""
    return TestClient(app, base_url="http://testserver", headers=TAB, follow_redirects=False,
                      client=(f"203.0.113.{next(_hosts)}", 50000))


def me(client: TestClient, **headers: str) -> dict[str, Any] | None:
    answer = client.get("/api/v1/auth/me", headers=headers)
    return answer.json() if answer.status_code == 200 else None


def with_password(client: TestClient, account: dict[str, Any], typed: str | None = None,
                  password: str | None = None) -> None:
    """The sign-in form of 1.12.0: field ``name``, then the code when the account has a second factor."""
    answer = client.post("/api/v1/auth/login", json={"name": typed or _name(account),
                                                      "password": password or account["password"]})
    assert answer.status_code == 200, (_name(account), answer.status_code, answer.text)
    if answer.json().get("second_factor"):
        code = totp.code_at(totp_seed(account["second_factor"]), time.time())
        second = client.post("/api/v1/auth/login/totp", json={"code": code})
        assert second.status_code == 200, (_name(account), second.text)


def refused(typed: str, password: str) -> int:
    return browser().post("/api/v1/auth/login", json={"name": typed, "password": password}).status_code


def through_provider(client: TestClient, fake: Any, person: dict[str, Any]) -> Any:
    fake.person = dict(person)
    start = client.get(f"/api/v1/oidc/{PROVIDER['slug']}/start")
    assert start.status_code in (302, 303, 307), start.text
    at_provider = start.headers["location"]
    path = urlsplit(fakes.query_of(at_provider)["redirect_uri"]).path
    return client.get(f"{path}?{urlencode(fake.authorize(at_provider))}")


def forgot(typed: str) -> None:
    answer = browser().post("/api/v1/auth/forgot", json={"name": typed})
    assert answer.status_code == 202, answer.text
    notices.settle()


def token_of(link: str) -> str:
    return link.rsplit("/", 1)[1]


# --- The start after the update ---------------------------------------------------------------------------------------


def test_the_fixture_is_from_1_12_0() -> None:
    assert MANIFEST["version"] == "1.12.0"
    raw = gzip.decompress(dump_file().read_bytes()).decode("utf-8")
    assert 'CREATE TABLE "users"' in raw or "CREATE TABLE users" in raw
    assert "PRAGMA user_version = 20;" in raw


def test_the_start_only_adds(bestand: tuple[dict[str, set[str]], dict[str, int]]) -> None:
    """Rule 10 of the draft: new columns with a default, nothing renamed or deleted, no row lost."""
    columns_before, counts_before = bestand
    columns_after, counts_after = _schema(get_settings().database_path)
    for table, columns in columns_before.items():
        assert table in columns_after, f"table {table} is gone"
        missing = columns - columns_after[table]
        assert not missing, f"{table}: columns gone {sorted(missing)}"
    assert counts_after == counts_before


def test_every_account_is_still_there_with_its_name_address_and_vault(bestand: Any) -> None:
    with SessionLocal() as db:
        rows = {row.name: row for row in db.query(Account).all()}
        assert set(rows) == {_name(a) for a in ACCOUNTS}
        for account in ACCOUNTS:
            row = rows[_name(account)]
            assert row.email == account["email"], _name(account)
            assert (row.email_confirmed_at is not None) == account["email_confirmed"], _name(account)
            assert bool(row.password_hash) == bool(account["password"]), _name(account)
            assert bool(row.totp_secret_enc) == bool(account.get("second_factor")), _name(account)
            assert (row.blocked_at is not None) == bool(account.get("blocked")), _name(account)
            assert (row.role == "operator") == bool(account.get("operator")), _name(account)
        from app.models import Vault

        personal = {vault.personal_of: vault.folder for vault in db.query(Vault).filter(Vault.personal_of.is_not(None))}
        # The folder on the disk is the name the account had when it was made; it never moves.
        assert personal == {row.id: row.name for row in rows.values()}


# --- Name and password ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("account", WITH_PASSWORD, ids=_name)
def test_name_and_password_still_sign_in(bestand: Any, account: dict[str, Any]) -> None:
    client = browser()
    with_password(client, account)
    assert (me(client) or {}).get("name") == _name(account)


@pytest.mark.parametrize("account", MEMBERS_WITH_PASSWORD, ids=_name)
def test_the_name_in_capitals_still_signs_in(bestand: Any, account: dict[str, Any]) -> None:
    client = browser()
    with_password(client, account, typed=f"  {_name(account).upper()} ")
    assert (me(client) or {}).get("name") == _name(account)


@pytest.mark.parametrize("account", WITH_PASSWORD, ids=_name)
def test_a_wrong_password_is_still_refused(bestand: Any, account: dict[str, Any]) -> None:
    assert refused(_name(account), account["password"] + "x") == 401


@pytest.mark.parametrize("account", WITH_FACTOR, ids=_name)
def test_a_recovery_code_still_stands_in_for_the_app(bestand: Any, account: dict[str, Any]) -> None:
    client = browser()
    first = client.post("/api/v1/auth/login", json={"name": _name(account), "password": account["password"]})
    assert first.status_code == 200 and first.json()["second_factor"], first.text
    second = client.post("/api/v1/auth/login/totp", json={"code": account["recovery_codes"][0]})
    assert second.status_code == 200, second.text
    assert (me(client) or {}).get("name") == _name(account)


def test_the_second_factor_is_still_asked_after_the_password(bestand: Any) -> None:
    account = WITH_FACTOR[0]
    client = browser()
    first = client.post("/api/v1/auth/login", json={"name": _name(account), "password": account["password"]})
    assert first.json().get("second_factor") is True
    assert me(client) is None


def test_a_blocked_account_still_gets_no_session(bestand: Any) -> None:
    """1.12.0 answers like a wrong password; the module says "blocked" after the right one (401 or 403). Either
    way: no session."""
    blocked = next(a for a in ACCOUNTS if a.get("blocked"))
    client = browser()
    answer = client.post("/api/v1/auth/login", json={"name": _name(blocked), "password": blocked["password"]})
    assert answer.status_code in (401, 403), answer.text
    assert me(client) is None


def test_a_deleted_account_stays_gone(bestand: Any) -> None:
    deleted = MANIFEST["deleted"]
    assert refused(deleted["name"], deleted["password"]) == 401


def test_password_sign_in_switched_off_still_keeps_members_out_and_lets_the_operator_in(bestand: Any) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"password_login": False})
    for account in WITH_PASSWORD:
        client = browser()
        if account.get("operator"):
            with_password(client, account)
            assert (me(client) or {}).get("name") == _name(account)
        else:
            answer = client.post("/api/v1/auth/login", json={"name": _name(account), "password": account["password"]})
            assert answer.status_code in (401, 403), (_name(account), answer.text)
            assert me(client) is None


def test_the_lock_after_wrong_passwords_still_holds_per_account(bestand: Any) -> None:
    """Wrong passwords from many addresses lock the account, not the address (1.12.0: ``MAX_FAILURES``); the module's
    ``authenticate`` has no lock, so the app has to keep this one."""
    account = next(a for a in MEMBERS_WITH_PASSWORD if not a.get("second_factor"))
    for _ in range(MAX_FAILURES):
        assert refused(_name(account), "wrong-wrong-wrong") == 401
    assert refused(_name(account), account["password"]) == 401


@pytest.mark.parametrize("account", [a for a in WITH_PROVIDER if not a["password"]], ids=_name)
def test_an_account_without_a_password_still_has_none(bestand: Any, account: dict[str, Any]) -> None:
    for attempt_ in ("-", " ", _name(account), "Bestand-anna-2026"):
        assert refused(_name(account), attempt_) == 401


# --- Providers --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("account", WITH_PROVIDER, ids=_name)
def test_the_provider_still_signs_in(bestand: Any, provider: Any, account: dict[str, Any]) -> None:
    client = browser()
    back = through_provider(client, provider, account["provider"])
    assert back.status_code in (302, 303), back.text
    assert "error" not in back.headers["location"], back.headers["location"]
    assert (me(client) or {}).get("name") == _name(account)


# --- What is signed in already ----------------------------------------------------------------------------------------


def test_an_open_browser_session_stays_open(bestand: Any) -> None:
    account = next(a for a in ACCOUNTS if a.get("session"))
    client = browser()
    client.cookies.set(SESSION_COOKIE, account["session"])
    assert (me(client) or {}).get("name") == _name(account)


def test_a_paired_iphone_stays_paired(bestand: Any) -> None:
    account = next(a for a in ACCOUNTS if a.get("device"))
    found = me(browser(), Authorization=f"Bearer {account['device']}")
    assert (found or {}).get("name") == _name(account)


def test_an_api_key_keeps_working(bestand: Any) -> None:
    account = next(a for a in ACCOUNTS if a.get("api_key"))
    answer = browser().get("/api/v1/me", headers={"Authorization": f"Bearer {account['api_key']}"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["name"] == _name(account)


# --- Invitations, links, addresses ------------------------------------------------------------------------------------


@pytest.mark.parametrize("invite", MANIFEST["open_invites"], ids=lambda i: i["email"] or "no-address")
def test_an_open_invitation_still_makes_an_account_with_the_fields_of_1_12_0(bestand: Any, invite: dict) -> None:
    """The request of 1.12.0: ``name`` and ``password``, nothing else (an open tab, a bookmarked page). The module
    wants a display name; the route has to do without one."""
    client = browser()
    assert client.get(f"/api/v1/invite/{invite['token']}").status_code == 200
    made = client.post(f"/api/v1/invite/{invite['token']}", json={"name": "neu.gast", "password": NEW_PASSWORD})
    assert made.status_code == 200, made.text
    own = me(client) or {}
    assert own.get("name") == "neu.gast"
    assert own.get("email") == invite["email"]
    again = browser()
    with_password(again, {"name": "neu.gast", "password": NEW_PASSWORD})
    assert (me(again) or {}).get("name") == "neu.gast"


@pytest.mark.parametrize("account", [a for a in ACCOUNTS if a.get("reset_link")], ids=_name)
def test_an_open_link_for_a_new_password_still_works(bestand: Any, account: dict[str, Any]) -> None:
    """One the operator made (24 hours) and one the person asked for: the hash of 1.12.0 stays the hash."""
    client = browser()
    state = client.get(f"/api/v1/reset/{account['reset_link']}")
    assert state.status_code == 200 and state.json()["name"] == _name(account), state.text
    assert client.post(f"/api/v1/reset/{account['reset_link']}", json={"password": NEW_PASSWORD}).status_code == 204
    after = browser()
    with_password(after, account, password=NEW_PASSWORD)
    assert (me(after) or {}).get("name") == _name(account)
    assert refused(_name(account), account["password"]) == 401


def test_an_address_waiting_for_its_link_is_still_confirmed_by_it(bestand: Any) -> None:
    account = next(a for a in ACCOUNTS if a.get("pending_link"))
    client = browser()
    state = client.get(f"/api/v1/email/confirm/{account['pending_link']}")
    assert state.status_code == 200 and state.json()["address"] == account["pending_email"], state.text
    assert client.post(f"/api/v1/email/confirm/{account['pending_link']}").status_code == 200
    with SessionLocal() as db:
        row = db.query(Account).filter_by(name=_name(account)).one()
        assert row.email == account["pending_email"] and row.email_confirmed_at is not None


# --- Forgot your password? --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("account", [a for a in WITH_PASSWORD if a["email"]], ids=_name)
def test_forgot_password_by_name_still_mails_a_link_to_the_own_address(
    bestand: Any, post: list[dict[str, Any]], account: dict[str, Any]
) -> None:
    """Every account with a password and an address got its link in 1.12.0, also with the address of its invitation
    (never confirmed) and with an address another account has too. The link goes to its own address."""
    forgot(_name(account))
    assert [mail["to"] for mail in post] == [account["email"]]
    assert post[0]["name"] == _name(account)
    assert browser().post(f"/api/v1/reset/{token_of(post[0]['link'])}",
                          json={"password": NEW_PASSWORD}).status_code == 204
    client = browser()
    with_password(client, account, password=NEW_PASSWORD)
    assert (me(client) or {}).get("name") == _name(account)


@pytest.mark.parametrize("account", UNIQUE_ADDRESS, ids=_name)
def test_forgot_password_by_a_unique_address_still_mails_a_link(
    bestand: Any, post: list[dict[str, Any]], account: dict[str, Any]
) -> None:
    """1.12.0 took the address on record, confirmed or not, in any case."""
    forgot(account["email"].upper())
    assert [mail["to"] for mail in post] == [account["email"]]
    assert post[0]["name"] == _name(account)


def test_forgot_password_for_a_shared_address_never_reaches_another_account(
    bestand: Any, post: list[dict[str, Any]]
) -> None:
    """1.12.0 sends each account of a shared address its own link to that address; the module sends none (rule 3 of
    the draft, strict test at the end). What may never happen: a link of one account goes to another's address."""
    forgot(SHARED_ADDRESS[0]["email"])
    shared = {a["email"].lower() for a in SHARED_ADDRESS}
    for mail in post:
        assert mail["to"].lower() in shared
        owner = next(a for a in SHARED_ADDRESS if a["name"] == mail["name"])
        assert mail["to"] == owner["email"]


@pytest.mark.parametrize("who", ["emil", "fritz", "hans", "ida", "nobody"])
def test_forgot_password_still_sends_nothing_without_a_way(bestand: Any, post: list[dict[str, Any]], who: str) -> None:
    """No address (emil), provider only (fritz), blocked (hans), deleted (ida), unknown: the same answer, no mail."""
    forgot(who)
    assert post == []


def test_a_shared_address_never_signs_in(bestand: Any) -> None:
    """True in 1.12.0 (no sign-in by address at all) and after the change (rule 3)."""
    for account in SHARED_ADDRESS:
        assert refused(account["email"], account["password"]) in (401, 422)


# --- After the change (account module): what 1.12.0 did not do -------------------------------------------------------

AFTER_THE_CHANGE = pytest.mark.xfail(strict=True, reason="comes with the account module (nexkonten)")

# The link of "Forgot your password?" goes out through the shared modules since the change (post, through nexpaper's
# kontenpost): the fixture ``post`` above catches it there, under the name it always used (Bauplan E51).
from app.services import kontenpost as mailer  # noqa: E402


@pytest.mark.parametrize("account", UNIQUE_CONFIRMED, ids=_name)
def test_after_the_change_a_unique_confirmed_address_signs_in(bestand: Any, account: dict[str, Any]) -> None:
    client = browser()
    with_password(client, account, typed=account["email"].upper())
    assert (me(client) or {}).get("name") == _name(account)


def test_after_the_change_a_shared_address_finds_no_account_for_a_link(bestand: Any, post: list[dict]) -> None:
    forgot(SHARED_ADDRESS[0]["email"])
    assert post == []
