"""Every test run gets its own empty data directory; nothing touches ``data/`` of the project."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

_DATA = tempfile.mkdtemp(prefix="nexpaper-tests-")
os.environ["NEXPAPER_DATA_DIR"] = _DATA
os.environ["NEXPAPER_DISABLE_BACKGROUND"] = "1"
os.environ["NEXPAPER_FRONTEND_DIST"] = os.path.join(_DATA, "no-frontend")
# Set, not removed: a value in the environment wins over a .env file in the project, a removed one does not.
os.environ["NEXPAPER_LOCALES_DIR"] = os.path.join(_DATA, "locales")
os.environ["NEXPAPER_LOG_LEVEL"] = ""
# Argon2 as cheap as it goes: the tests make many accounts. The strength itself is Argon2's business.
os.environ["NEXPAPER_ARGON2_TIME"] = "1"
os.environ["NEXPAPER_ARGON2_MEMORY_KIB"] = "1024"
os.environ["NEXPAPER_ARGON2_PARALLELISM"] = "1"
# Never GitHub from a test: port 9 refuses at once.
os.environ["NEXPAPER_UPDATE_URL"] = "http://127.0.0.1:9/releases/latest"
os.environ["NEXPAPER_SECRET_KEY"] = "test-secret-key-for-the-test-run-only"
SETUP_CODE = "test-setup-code"
os.environ["NEXPAPER_SETUP_TOKEN"] = SETUP_CODE

import shutil  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import MEMBER, OPERATOR, Account, Base, Setting  # noqa: E402
from app.security import SESSION_COOKIE, brake, hash_password, start_session  # noqa: E402
from app.services import (  # noqa: E402
    ai,
    apikeys,
    backups,
    brakes,
    jobs,
    notices,
    oidc,
    passkeys,
    push,
    settings_service,
    storage,
    totp,
    updates,
)

DATA_DIR = _DATA
TAB = {"X-Nexpaper-Client": "tab-tests000"}


@pytest.fixture(scope="session", autouse=True)
def schema() -> None:
    init_db()


@pytest.fixture(autouse=True)
def clean_db(schema: None) -> Iterator[None]:
    with SessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(delete(table))
        db.execute(delete(Setting))
        # nexpaper asks every account for a second factor from the start. Most tests are about something else and
        # sign in with a password alone; the tests of the second factor turn it on (``require_second_factor``).
        db.add(Setting(key="two_factor_required", value=False))
        db.commit()
    # Backups of a test before (an automatic one of the same second) must not decide what another test prunes.
    shutil.rmtree(backups.folder(), ignore_errors=True)
    # Files of a test before would take the names a later test expects (a counter in the file name) and hide what
    # a test leaves behind: every test starts with no documents on the disk and no cached pictures of them.
    for folder in (storage.FOLDER, "cache", "uploads"):
        shutil.rmtree(os.path.join(_DATA, folder), ignore_errors=True)
    oidc.clear_cache()
    brake.forget()
    brakes.forget()
    totp.forget()
    updates.forget()
    ai.forget()
    apikeys.forget()
    notices.forget()
    push.forget()
    passkeys.forget()
    # A test that ran the background loop leaves the flag "the server is stopping" set when the loop ends; a worker
    # started in a later test would take it as its own stop.
    jobs.stopping.clear()
    yield
    notices.settle()
    app.dependency_overrides.clear()


PASSWORD = "correct horse battery"


def require_second_factor(on: bool = True) -> None:
    """The operator's switch "require a second factor", as it stands from the start (on)."""
    with SessionLocal() as db:
        settings_service.save(db, {"two_factor_required": on})


def make_account(name: str, role: str = MEMBER, password: str = PASSWORD) -> Account:
    """An account with a password, straight into the database."""
    with SessionLocal() as db:
        row = Account(name=name, role=role, password_hash=hash_password(password))
        db.add(row)
        db.commit()
        db.expunge(row)
    return row


def sign_in(client: TestClient, account: Account) -> None:
    """The client carries a session of ``account`` from now on (a real one, as after signing in)."""
    with SessionLocal() as db:
        row = db.get(Account, account.id)
        assert row is not None
        token = start_session(db, row, "127.0.0.1", "tests")
    client.cookies.set(SESSION_COOKIE, token)


def new_client(account: Account | None = None) -> TestClient:
    """Another browser, signed in as ``account`` when one is given. Close it (``with``) when done."""
    client = TestClient(app, base_url="http://testserver", headers=TAB)
    if account is not None:
        sign_in(client, account)
    return client


def person(name: str) -> TestClient:
    """A browser signed in as a new member ``name``."""
    return new_client(make_account(name))


def _operator(client: TestClient) -> Account:
    with SessionLocal() as db:
        row = db.query(Account).filter_by(name="tester").one_or_none()
        if row is not None:
            db.expunge(row)
    if row is None:
        row = make_account("tester", OPERATOR)
    sign_in(client, row)
    return row


@pytest.fixture
def client() -> Iterator[TestClient]:
    # As the interface does: every request names its tab (changes are refused without it).
    with TestClient(app, base_url="http://testserver", headers=TAB) as test_client:
        yield test_client


@pytest.fixture
def push_service(monkeypatch: pytest.MonkeyPatch) -> object:
    """The stand-in of a push service (``fake_push.py``), added to the operator's list of push services, its name
    resolving to a public address. The check of where a message may go stays as it is."""
    from .fake_push import HOST, FakePushService, public_resolver

    fake = FakePushService()
    monkeypatch.setattr(push, "transport", fake.transport())
    monkeypatch.setattr(push, "resolver", public_resolver)
    with SessionLocal() as db:
        settings_service.save(db, {"push_hosts": [HOST]})
    return fake


@pytest.fixture
def operator(client: TestClient) -> Account:
    """The signed-in operator ``tester``."""
    return _operator(client)


@pytest.fixture
def account(client: TestClient) -> Account:
    """The same as ``operator``, under the name the tests from nexlore use."""
    return _operator(client)


def pytest_unconfigure(config: pytest.Config) -> None:
    """The data folder of this run goes when the run ends: the log file is closed first (Windows keeps open files),
    then the folder with everything in it."""
    import logging

    for logger in (logging.getLogger(), logging.getLogger("uvicorn.error")):
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
    from app.db import engine

    engine.dispose()
    shutil.rmtree(_DATA, ignore_errors=True)
