"""SQLite connection, and the schema with its version number.

There is no Alembic. The database carries the version of its schema in SQLite's ``user_version``:

* A new database is made from the models (``create_all``) and gets ``SCHEMA_VERSION``.
* An older one is brought up step by step: ``MIGRATIONS[n]`` takes a database from version ``n - 1`` to ``n``. Before
  the first step a backup is made (the way back if the new version goes wrong); each step runs in a transaction of its
  own and sets the version only when it went through.
* A database from a newer nexpaper than the running one is not touched: the start stops with a message.

Whoever changes a table in ``models.py`` raises ``SCHEMA_VERSION``, writes the step, and records the new schema in
``tests/schema/`` (``test_schema.py`` says how).

One exception, ``ADDITIONS``: new tables and new columns with a default that the released version before opens without
knowing them. They are made at every start when missing and do not raise the version, so that version can still start
on this database (it refuses one of a higher version): the way back for one version (1.1.0, the sign-in providers, back
to 1.0.1). Then the schema of the current version is recorded anew, and ``tests/schema/released/`` keeps what the
released version made. On a database of that released schema (``ADDITIONS_ON``) they run before every step as well, so
a later step finds their tables; like a step, each is written out as its tables stood, not taken from the models.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from .config import get_settings
from .models import Base
from .names import search_key

logger = logging.getLogger("nexpaper.db")

_settings = get_settings()
_settings.data_dir.mkdir(parents=True, exist_ok=True)

#: How long a write waits for another one to finish. Every writer keeps its transactions short; this is the margin
#: for a slow disk, not a wait anybody should see.
BUSY_SECONDS = 15

#: The version of the schema the models describe.
SCHEMA_VERSION = 11


def _step_v2(connection: Connection) -> None:
    """Vaults and documents. Every account that exists gets the vault of its own, as one made now would."""
    from datetime import UTC, datetime

    from .names import clean_segment, folded
    from .step_v2_schema import V2_STATEMENTS

    for statement in V2_STATEMENTS:
        connection.exec_driver_sql(statement)
    now = datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
    taken: set[str] = set()
    accounts = connection.execute(text("SELECT id, name, display_name FROM users ORDER BY id")).all()
    for account_id, name, display_name in accounts:
        label = display_name or name
        base = clean_segment(label, "vault")
        folder, counter = base, 1
        while folded(folder) in taken:
            counter += 1
            suffix = f" {counter}"
            folder = base[: 48 - len(suffix)].rstrip(" .") + suffix
        taken.add(folded(folder))
        created = connection.execute(
            text("INSERT INTO vaults (name, folder, icon, personal_of, created_at, created_by) "
                 "VALUES (:name, :folder, 'user', :uid, :now, :uid)"),
            {"name": label, "folder": folder, "uid": account_id, "now": now},
        )
        connection.execute(
            text("INSERT INTO vault_members (vault_id, user_id, \"right\") VALUES (:vault, :uid, 'manage')"),
            {"vault": created.lastrowid, "uid": account_id},
        )


def _step_v3(connection: Connection) -> None:
    """Receiving files: the pieces of an upload, what reading a file found (an error, a document it looks like) and
    the fingerprint of the first page."""
    for statement in (
        "ALTER TABLE documents ADD COLUMN duplicate_of INTEGER",
        "ALTER TABLE documents ADD COLUMN duplicate_kind VARCHAR(8) DEFAULT '' NOT NULL",
        "ALTER TABLE documents ADD COLUMN process_error VARCHAR(24) DEFAULT '' NOT NULL",
        "ALTER TABLE versions ADD COLUMN phash VARCHAR(256) DEFAULT '' NOT NULL",
        "CREATE INDEX ix_versions_sha256 ON versions (sha256)",
        (
            "CREATE TABLE uploads ( id VARCHAR(32) NOT NULL, user_id INTEGER NOT NULL, vault_id INTEGER NOT NULL, "
            "filename VARCHAR(200) NOT NULL, size INTEGER NOT NULL, sha256 VARCHAR(64) NOT NULL, "
            "received INTEGER NOT NULL, source VARCHAR(8) NOT NULL, state VARCHAR(10) NOT NULL, document_id INTEGER, "
            "created_at DATETIME NOT NULL, expires_at DATETIME NOT NULL, PRIMARY KEY (id), "
            "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, "
            "FOREIGN KEY(vault_id) REFERENCES vaults (id) ON DELETE CASCADE )"
        ),
        "CREATE INDEX ix_uploads_user ON uploads (user_id, state)",
    ):
        connection.exec_driver_sql(statement)


def _step_phone(connection: Connection) -> None:
    """The phone block: codes that pair a device once (a QR code, or OAuth 2 with PKCE), how each device was paired,
    and the API key an upload in pieces belongs to. Touches nothing but its own table and two added columns."""
    for statement in (
        "ALTER TABLE devices ADD COLUMN via VARCHAR(40) DEFAULT 'token' NOT NULL",
        "ALTER TABLE uploads ADD COLUMN api_key_id INTEGER",
        (
            "CREATE TABLE pairings ( id INTEGER NOT NULL, account_id INTEGER NOT NULL, kind VARCHAR(8) NOT NULL, "
            "code_hash VARCHAR(64) NOT NULL, created_at DATETIME NOT NULL, expires_at DATETIME NOT NULL, "
            "used_at DATETIME, device_id INTEGER, client_id VARCHAR(64) DEFAULT '' NOT NULL, "
            "redirect_uri VARCHAR(300) DEFAULT '' NOT NULL, challenge VARCHAR(128) DEFAULT '' NOT NULL, "
            "device_name VARCHAR(80) DEFAULT '' NOT NULL, PRIMARY KEY (id), "
            "FOREIGN KEY(account_id) REFERENCES users (id) ON DELETE CASCADE, UNIQUE (code_hash), "
            "FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE SET NULL )"
        ),
        "CREATE INDEX ix_pairings_account ON pairings (account_id, kind)",
    ):
        connection.exec_driver_sql(statement)


def _step_intake(connection: Connection) -> None:
    """Inputs (block B8): what came in through the intake folder or the mailbox, and the addresses people forward
    documents from. Only tables of its own; written out as they stood when the step was made."""
    for statement in (
        (
            "CREATE TABLE intake_items ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, document_id INTEGER, "
            "source VARCHAR(8) NOT NULL, \"key\" VARCHAR(600) NOT NULL, state VARCHAR(8) NOT NULL, "
            "sha256 VARCHAR(64) NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, "
            "message VARCHAR(64) NOT NULL, unknown BOOLEAN NOT NULL, detail JSON, at DATETIME NOT NULL, "
            "FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE SET NULL )"
        ),
        "CREATE INDEX ix_intake_items_document ON intake_items (document_id)",
        "CREATE UNIQUE INDEX uq_intake_items_mail ON intake_items (\"key\") WHERE source = 'mail'",
        "CREATE UNIQUE INDEX uq_intake_items_taken ON intake_items (source, \"key\") WHERE state = 'taken'",
        "CREATE INDEX ix_intake_items_message ON intake_items (message)",
        (
            "CREATE TABLE mail_senders ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
            "address VARCHAR(255) NOT NULL, address_key VARCHAR(255) NOT NULL, token_hash VARCHAR(64) NOT NULL, "
            "expires_at DATETIME, confirmed_at DATETIME, created_at DATETIME NOT NULL, "
            "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE )"
        ),
        "CREATE INDEX ix_mail_senders_key ON mail_senders (address_key)",
        "CREATE UNIQUE INDEX uq_mail_senders_user_key ON mail_senders (user_id, address_key)",
    ):
        connection.exec_driver_sql(statement)


def _step_search(connection: Connection) -> None:
    """Text and search (B3): the text of every version, the search index and what it holds per document. The index is
    filled by a job (``services/search_index.py``), queued here: the documents that are there are indexed right after
    the start, in short transactions, while the app already answers. Each document that was read gets a job ``text``
    that reads its text (``processing.read_text``)."""
    from datetime import UTC, datetime

    for statement in (
        (
            "CREATE TABLE version_texts ( version_id INTEGER NOT NULL, document_id INTEGER NOT NULL, "
            "text TEXT NOT NULL, pages INTEGER NOT NULL, ocr_pages INTEGER NOT NULL, languages VARCHAR(64) NOT NULL, "
            "digest VARCHAR(40) NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (version_id), "
            "FOREIGN KEY(version_id) REFERENCES versions (id) ON DELETE CASCADE, "
            "FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE )"
        ),
        "CREATE INDEX ix_version_texts_document_id ON version_texts (document_id)",
        (
            "CREATE TABLE search_entries ( document_id INTEGER NOT NULL, seq INTEGER NOT NULL, "
            "digest VARCHAR(40) NOT NULL, PRIMARY KEY (document_id), "
            "FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE )"
        ),
        (
            "CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(title, sender, text, notes, tags, scope, "
            "tokenize = 'unicode61 remove_diacritics 2', content = '', contentless_delete = 1)"
        ),
        (
            "CREATE VIRTUAL TABLE IF NOT EXISTS doc_tri USING fts5(title, sender, text, notes, tags, scope, "
            "tokenize = 'trigram remove_diacritics 1', content = '', contentless_delete = 1)"
        ),
        (
            "CREATE TRIGGER IF NOT EXISTS documents_search_gone AFTER DELETE ON documents BEGIN "
            "DELETE FROM doc_fts WHERE rowid = old.id; DELETE FROM doc_tri WHERE rowid = old.id; END"
        ),
    ):
        connection.exec_driver_sql(statement)
    now = datetime.now(UTC).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f")
    connection.execute(
        text("INSERT INTO jobs (kind, ref, payload, state, attempts, created_at, error) "
             "VALUES ('index', 0, NULL, 'queued', 0, :now, '')"),
        {"now": now},
    )
    # The documents read before there was text get it now, one job each (``processing.read_text``).
    connection.execute(
        text("INSERT INTO jobs (kind, ref, payload, state, attempts, created_at, error) "
             "SELECT 'text', d.id, NULL, 'queued', 0, :now, '' FROM documents d "
             "JOIN versions v ON v.document_id = d.id AND v.n = d.current_version "
             "WHERE d.status != 'processing' AND lower(v.original_path) NOT LIKE '%.xml' ORDER BY d.id"),
        {"now": now},
    )


def _step_paperless_export(connection: Connection) -> None:
    """The Paperless import and the export for the tax adviser (B9): what was taken from a Paperless server, the ZIPs
    people asked for, and the links to them. Only tables of its own; written out as they stood when the step was
    made."""
    for statement in (
        (
            "CREATE TABLE paperless_items ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
            "origin VARCHAR(64) NOT NULL, paperless_id INTEGER NOT NULL, document_id INTEGER, "
            "state VARCHAR(8) NOT NULL, reason VARCHAR(32) NOT NULL, inbox BOOLEAN NOT NULL, at DATETIME NOT NULL, "
            "FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE SET NULL )"
        ),
        "CREATE UNIQUE INDEX uq_paperless_items_origin ON paperless_items (origin, paperless_id)",
        "CREATE INDEX ix_paperless_items_document ON paperless_items (document_id)",
        (
            "CREATE TABLE exports ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
            "state VARCHAR(10) NOT NULL, params JSON, vault_ids JSON, language VARCHAR(8) NOT NULL, "
            "documents INTEGER NOT NULL, size INTEGER NOT NULL, total INTEGER NOT NULL, file VARCHAR(80) NOT NULL, "
            "error VARCHAR(40) NOT NULL, created_at DATETIME NOT NULL, finished_at DATETIME, "
            "expires_at DATETIME NOT NULL, "
            "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE )"
        ),
        "CREATE INDEX ix_exports_user ON exports (user_id, state)",
        (
            "CREATE TABLE export_links ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, export_id INTEGER NOT NULL, "
            "recipient VARCHAR(100) NOT NULL, token_hash VARCHAR(64) NOT NULL, token_enc VARCHAR(400) NOT NULL, "
            "until DATETIME NOT NULL, opened_count INTEGER NOT NULL, last_opened_at DATETIME, created_by INTEGER, "
            "created_at DATETIME NOT NULL, revoked_at DATETIME, "
            "FOREIGN KEY(export_id) REFERENCES exports (id) ON DELETE CASCADE, UNIQUE (token_hash), "
            "FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL )"
        ),
        "CREATE INDEX ix_export_links_export ON export_links (export_id)",
    ):
        connection.exec_driver_sql(statement)


def _step_pagetools(connection: Connection) -> None:
    """Page tools (B5): what a version is beyond its file (how it came about, whether it is read yet, its blank pages),
    and the document an upload in pieces becomes a new version of. Only a table and a column of its own."""
    for statement in (
        (
            "CREATE TABLE version_info ( version_id INTEGER NOT NULL, document_id INTEGER NOT NULL, "
            "origin VARCHAR(12) NOT NULL, from_n INTEGER, state VARCHAR(12) NOT NULL, error VARCHAR(24) NOT NULL, "
            "detail JSON, blanks JSON, split_dismissed BOOLEAN NOT NULL, PRIMARY KEY (version_id), "
            "FOREIGN KEY(version_id) REFERENCES versions (id) ON DELETE CASCADE, "
            "FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE )"
        ),
        "CREATE INDEX ix_version_info_document ON version_info (document_id, state)",
        "ALTER TABLE uploads ADD COLUMN target_document_id INTEGER",
    ):
        connection.exec_driver_sql(statement)


def _step_sorting(connection: Connection) -> None:
    """Sorting documents in (B6): the rules, the data of e-invoices, and the kinds of a vault. Tables of its own and the
    two columns of ``kinds``; written out as they stood when the step was made."""
    for statement in (
        (
            "CREATE TABLE rules ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, vault_id INTEGER, created_by INTEGER, "
            "position INTEGER NOT NULL, \"on\" BOOLEAN NOT NULL, hits INTEGER NOT NULL, last_hit_at DATETIME, "
            "\"when\" JSON NOT NULL, \"then\" JSON NOT NULL, created_at DATETIME NOT NULL, "
            "FOREIGN KEY(vault_id) REFERENCES vaults (id) ON DELETE CASCADE, "
            "FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL )"
        ),
        "CREATE INDEX ix_rules_vault ON rules (vault_id, position)",
        (
            "CREATE TABLE einvoices ( version_id INTEGER NOT NULL, document_id INTEGER NOT NULL, "
            "format VARCHAR(40) NOT NULL, number VARCHAR(100) NOT NULL, issued DATE, due DATE, "
            "seller VARCHAR(200) NOT NULL, seller_vat VARCHAR(40) NOT NULL, buyer VARCHAR(200) NOT NULL, "
            "buyer_ref VARCHAR(100) NOT NULL, iban VARCHAR(40) NOT NULL, currency VARCHAR(3) NOT NULL, net INTEGER, "
            "tax INTEGER, gross INTEGER, payable INTEGER, credit_note BOOLEAN NOT NULL, lines JSON, xml BLOB, "
            "created_at DATETIME NOT NULL, PRIMARY KEY (version_id), "
            "FOREIGN KEY(version_id) REFERENCES versions (id) ON DELETE CASCADE, "
            "FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE )"
        ),
        "CREATE INDEX ix_einvoices_document_id ON einvoices (document_id)",
        # The kinds a vault makes for itself (the others, for the whole server, keep an empty vault).
        "ALTER TABLE kinds ADD COLUMN vault_id INTEGER REFERENCES vaults (id) ON DELETE CASCADE",
        "ALTER TABLE kinds ADD COLUMN created_by INTEGER REFERENCES users (id) ON DELETE SET NULL",
        "DROP INDEX uq_kinds_name_key",
        "CREATE UNIQUE INDEX uq_kinds_server ON kinds (name_key) WHERE vault_id IS NULL",
        "CREATE UNIQUE INDEX uq_kinds_vault ON kinds (vault_id, name_key) WHERE vault_id IS NOT NULL",
    ):
        connection.exec_driver_sql(statement)


def _step_files(connection: Connection) -> None:
    """Checking the files (B10): the checksum of the searchable copy of a version, and what the last check of the files
    found for a document. Two added columns, nothing else. The search index is not touched (a backup leaves it out and
    builds it anew after a restore: ``models.SEARCH_STATEMENTS`` are run at every start)."""
    for statement in (
        "ALTER TABLE versions ADD COLUMN archive_sha256 VARCHAR(64) DEFAULT '' NOT NULL",
        "ALTER TABLE documents ADD COLUMN files_state VARCHAR(8) DEFAULT '' NOT NULL",
    ):
        connection.exec_driver_sql(statement)


def _step_keeping(connection: Connection) -> None:
    """Keeping documents (F3): how long the documents of a kind are kept, whether that was set for new documents only,
    and the mark on a dated term that a person set it (a ``keep_until`` worked out from the kind has none). Three added
    columns with a default, nothing else."""
    for statement in (
        "ALTER TABLE kinds ADD COLUMN keep_years INTEGER",
        "ALTER TABLE kinds ADD COLUMN keep_new_only BOOLEAN DEFAULT 0 NOT NULL",
        "ALTER TABLE document_dates ADD COLUMN manual BOOLEAN DEFAULT 0 NOT NULL",
        # Every keep_until there was came from a person: before this step nothing worked one out.
        "UPDATE document_dates SET manual = 1 WHERE kind = 'keep_until'",
    ):
        connection.exec_driver_sql(statement)


#: ``MIGRATIONS[n]`` brings a database from version ``n - 1`` to ``n``. Version 1 is the first schema; it has no step.
#: Later steps are written out as the tables stood then, not taken from the models, which move on.
MIGRATIONS: dict[int, Callable[[Connection], None]] = {
    2: _step_v2, 3: _step_v3, 4: _step_phone, 5: _step_intake, 6: _step_search,
    7: _step_paperless_export, 8: _step_pagetools,
    # B6, sorting documents in.
    9: _step_sorting,
    # B10, checking the files.
    10: _step_files,
    # F3, keeping documents (a number of its own until the steps of 1.4 are put together: after F1's).
    11: _step_keeping,
}

def _has_column(connection: Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in connection.exec_driver_sql(f'PRAGMA table_info("{table}")'))


def _additions_signin(connection: Connection) -> None:
    """1.1.0, the sign-in providers of the shared module (``services/oidc_store.py``): the list and the links as tables
    of their own, and the mark on a session that came in through a provider that checks the second factor. 1.0.1 reads
    neither and keeps working on the old settings and ``users.oidc_subject``, which the way back writes.

    Written out as the tables stood in 1.1.0, like a step, not taken from the models: the additions also run before
    the steps of a later version, and a step that changes these tables must find them as they were."""
    for statement in (
        (
            "CREATE TABLE IF NOT EXISTS oidc_providers ( id INTEGER NOT NULL, slug VARCHAR(40) NOT NULL, "
            "label VARCHAR(64) NOT NULL, issuer VARCHAR(500) NOT NULL, client_id VARCHAR(255) NOT NULL, "
            "client_secret_enc TEXT NOT NULL, scopes VARCHAR(500) NOT NULL, enabled BOOLEAN NOT NULL, "
            "auto_create BOOLEAN NOT NULL, trusts_second_factor BOOLEAN NOT NULL, managed VARCHAR(20) NOT NULL, "
            "position INTEGER NOT NULL, redirect_path VARCHAR(300) NOT NULL, "
            "registered_redirect VARCHAR(500) DEFAULT '' NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id), "
            "UNIQUE (slug) )"
        ),
        (
            "CREATE TABLE IF NOT EXISTS oidc_links ( id INTEGER NOT NULL, provider_id INTEGER NOT NULL, "
            "subject VARCHAR(255) NOT NULL, account_id INTEGER NOT NULL, issuer VARCHAR(500) NOT NULL, "
            "email VARCHAR(320), created_at DATETIME NOT NULL, last_used_at DATETIME, PRIMARY KEY (id), "
            "UNIQUE (provider_id, subject), UNIQUE (provider_id, account_id), "
            "FOREIGN KEY(provider_id) REFERENCES oidc_providers (id) ON DELETE CASCADE, "
            "FOREIGN KEY(account_id) REFERENCES users (id) ON DELETE CASCADE )"
        ),
        "CREATE INDEX IF NOT EXISTS ix_oidc_links_account_id ON oidc_links (account_id)",
        "CREATE INDEX IF NOT EXISTS ix_oidc_links_provider_id ON oidc_links (provider_id)",
    ):
        connection.exec_driver_sql(statement)
    if not _has_column(connection, "auth_sessions", "second_factor_by_provider"):
        # With a default: 1.0.1 inserts sessions without naming the column.
        connection.exec_driver_sql(
            "ALTER TABLE auth_sessions ADD COLUMN second_factor_by_provider BOOLEAN DEFAULT 0 NOT NULL"
        )


#: Made at every start when missing, without a new version (see the top of this file). Each is idempotent.
ADDITIONS: list[Callable[[Connection], None]] = [_additions_signin]

#: The schema the additions are made on: the one of 1.0.1. From there on they run before every step too, so that a
#: step of a later version finds their tables on a database 1.0.1 made (it would stop with "no such table" else).
ADDITIONS_ON = 10


# No pool with an upper bound: with the default pool the sixteenth concurrent request would block the event
# loop waiting for a connection. Opening a SQLite connection costs a fraction of a millisecond.
engine = create_engine(
    f"sqlite:///{_settings.database_path}",
    connect_args={"check_same_thread": False, "timeout": BUSY_SECONDS},
    poolclass=NullPool,
    # A failed statement names its values in the exception, and exceptions reach the log: never texts or hashes.
    hide_parameters=True,
)


def _wal(cursor: Any) -> None:
    """WAL mode, tried again while another connection holds the database: SQLite does not always wait by itself for
    a change of the journal mode."""
    deadline = time.monotonic() + BUSY_SECONDS
    while True:
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if ("locked" not in str(exc) and "busy" not in str(exc)) or time.monotonic() > deadline:
                raise
            time.sleep(0.05)


@event.listens_for(engine, "connect")
def _pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    # The wait first: switching to WAL needs the database to itself for a moment, and two first starts on an empty
    # folder asked at the same time (one of them broke off with "database is locked").
    cursor.execute(f"PRAGMA busy_timeout={BUSY_SECONDS * 1000}")
    _wal(cursor)
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    # What is deleted is overwritten, not left in free pages: a deleted token hash or secret must be gone from the file.
    cursor.execute("PRAGMA secure_delete=ON")
    cursor.close()
    # Case and accents aside, for a query that looks in titles: SQLite's own ``lower()`` folds ASCII letters only.
    dbapi_connection.create_function("search_key", 1, _search_key, deterministic=True)


def _search_key(value: Any) -> str | None:
    return search_key(value) if isinstance(value, str) else None


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


class SchemaTooNew(RuntimeError):
    """The database was written by a newer nexpaper; this one does not know its tables."""


def schema_version(connection: Connection) -> int:
    return int(connection.execute(text("PRAGMA user_version")).scalar() or 0)


def _set_version(connection: Connection, version: int) -> None:
    # PRAGMA takes no bound parameters; the value is an int from this module, never from outside.
    connection.execute(text(f"PRAGMA user_version = {int(version)}"))


def _schema_engine(url: Any = None) -> Engine:
    """An engine for changing the schema, on the same file. Python's sqlite3 opens no transaction before ``CREATE`` or
    ``ALTER`` and so commits each one at once; here every transaction begins with an explicit ``BEGIN``, so a step that
    breaks off leaves nothing behind (SQLAlchemy's recipe for pysqlite). Only for the schema: the everyday engine
    keeps the driver's way, which holds no read lock while a request only reads."""
    schema = create_engine(url or engine.url, poolclass=NullPool, connect_args={"timeout": BUSY_SECONDS})

    @event.listens_for(schema, "connect")
    def _no_driver_transactions(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        dbapi_connection.execute("PRAGMA secure_delete=ON")
        dbapi_connection.execute(f"PRAGMA busy_timeout={BUSY_SECONDS * 1000}")

    @event.listens_for(schema, "begin")
    def _begin(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    return schema


def _has_tables(connection: Connection) -> bool:
    found = connection.execute(text("SELECT count(*) FROM sqlite_master WHERE type = 'table'")).scalar()
    return bool(found)


def init_db() -> None:
    """Makes a new database, or brings an older one up to ``SCHEMA_VERSION``."""
    schema = _schema_engine()
    try:
        _init(schema)
    finally:
        schema.dispose()


def _init(schema: Engine, *, backup: bool = True) -> None:
    # Read under the write lock: of two processes starting at once, the second waits here and sees what the first did.
    with schema.begin() as connection:
        fresh = not _has_tables(connection)
        current = schema_version(connection)
        if fresh:
            # One transaction: a start that breaks off in between leaves no tables without a version behind.
            Base.metadata.create_all(connection)
            _set_version(connection, SCHEMA_VERSION)
    if fresh:
        logger.info("Database created schema=%s", SCHEMA_VERSION)
        return
    check_version(current)
    if current >= 6:
        # A backup leaves the search index out; its tables are made again (they cost nothing empty) and the job that
        # fills them is queued by ``jobs.recover``, which finds documents without an entry.
        from .models import SEARCH_STATEMENTS

        with schema.begin() as connection:
            for statement in SEARCH_STATEMENTS:
                connection.exec_driver_sql(statement)
    if current < SCHEMA_VERSION:
        if backup:
            # A schema change is the moment a backup is worth most: the way back if the new version goes wrong.
            from .services import backups

            backups.create(kind=backups.UPDATE, note=f"before schema {SCHEMA_VERSION}")
        for target in range(current + 1, SCHEMA_VERSION + 1):
            step = MIGRATIONS.get(target)
            if step is None:
                raise RuntimeError(f"No migration to schema {target}.")
            if target - 1 >= ADDITIONS_ON:
                _run_additions(schema)
            with schema.begin() as connection:
                # Read again under the lock: another process may have taken this step since the first read. A step
                # that is not idempotent (an added column, moved rows) must never run twice.
                if schema_version(connection) >= target:
                    continue
                step(connection)
                _set_version(connection, target)
            logger.info("Database migrated schema=%s", target)
    _run_additions(schema)


def _run_additions(schema: Engine) -> None:
    for addition in ADDITIONS:
        # Under the write lock, like a step; idempotent, so another process that did it first changes nothing here.
        with schema.begin() as connection:
            addition(connection)


class NotOurs(RuntimeError):
    """A database that is not a nexpaper database, or holds things nexpaper never made."""


_REFERENCE: tuple[dict[str, frozenset[str]], dict[str, str]] | None = None


def _squeezed(sql: object) -> str:
    """A statement as SQLite kept it, without the differences that mean nothing (spaces, line breaks, case)."""
    return " ".join(str(sql or "").split()).lower()


def _reference() -> tuple[dict[str, frozenset[str]], dict[str, str]]:
    """What a database of today holds, made the way a new one is: ``(tables with their columns, the statements of
    its triggers, views and virtual tables by name)``. Made once."""
    global _REFERENCE
    if _REFERENCE is None:
        reference = create_engine("sqlite://", poolclass=NullPool)
        # A memory database is gone with its connection: made and read on one.
        with reference.connect() as connection:
            Base.metadata.create_all(connection)
            names = [row[0] for row in
                     connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'")]
            tables = {
                name: frozenset(row[1] for row in connection.exec_driver_sql(f'PRAGMA table_info("{name}")'))
                for name in names if not name.startswith("sqlite_")
            }
            code = {
                row[0]: _squeezed(row[1]) for row in connection.exec_driver_sql(
                    "SELECT name, sql FROM sqlite_master WHERE type IN ('trigger', 'view') "
                    "OR (type = 'table' AND sql LIKE 'CREATE VIRTUAL%')")
            }
        reference.dispose()
        _REFERENCE = (tables, code)
    return _REFERENCE


def _foreign_objects(plain: sqlite3.Connection) -> list[str]:
    """What the database holds that code of nexpaper did not make and that is more than data: triggers and views (they
    would run at every write of the app, and name anything), and virtual tables (a module of SQLite stands behind
    each one). One of ours by name counts only when its statement is ours, too: a trigger named like the one that keeps
    the search index, with another body, is the first thing somebody would try. Plain tables of data nexpaper does not
    know are not in the list: nothing reads them."""
    _tables, own = _reference()
    query = "SELECT name, type, sql FROM sqlite_master WHERE type IN ('trigger', 'view', 'table')"
    found = []
    for name, kind, sql in plain.execute(query):
        if kind == "table" and not str(sql or "").lstrip().upper().startswith("CREATE VIRTUAL"):
            continue
        if own.get(name) != _squeezed(sql):
            found.append(name)
    return found


def rehearse(path: Path) -> None:
    """The start, run on a copy of a database that is about to be restored: the steps that would bring it up to
    ``SCHEMA_VERSION`` and then a look whether it holds every table and column nexpaper needs. Raises when anything of
    it fails (a database that is not nexpaper's, one with a step that cannot run on it); the file is changed, so only
    ever hand it a scratch copy.

    Triggers, views and virtual tables that nexpaper does not make are refused before anything is done: a trigger would
    run at every write of the app, and the restore would give it the keys to everything.
    """
    uri = f"file:{path.as_posix()}?mode=ro"
    plain = sqlite3.connect(uri, uri=True)
    try:
        if _foreign_objects(plain):
            raise NotOurs("triggers, views or virtual tables that nexpaper did not make")
        if plain.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0] == 0:
            raise NotOurs("no tables")
    finally:
        plain.close()
    schema = _schema_engine(f"sqlite:///{path.as_posix()}")
    try:
        _init(schema, backup=False)
    finally:
        schema.dispose()
    plain = sqlite3.connect(uri, uri=True)
    try:
        for name, columns in _reference()[0].items():
            found = {row[1] for row in plain.execute(f'PRAGMA table_info("{name}")')}
            if not columns <= found:
                raise NotOurs("a table or a column is missing")
    finally:
        plain.close()


def check_version(version: int) -> None:
    """A schema this nexpaper can open: made by nexpaper (at least 1), and not by a newer one. ``SchemaTooNew`` else."""
    if version > SCHEMA_VERSION:
        raise SchemaTooNew(
            f"The database has schema {version}, this nexpaper knows up to {SCHEMA_VERSION}. "
            "Start the newer version again, or restore a backup made with this one."
        )
    if version < 1:
        raise SchemaTooNew("The database has no schema version. It was not made by nexpaper.")
