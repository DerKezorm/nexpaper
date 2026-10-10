"""Schema 1 to schema 2 with accounts that already exist: each gets the vault of its own, nothing else is touched."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app import db as database

from .test_schema import RECORDS, scratch, version_of  # noqa: F401 - the fixture is used by name


def test_accounts_that_exist_get_their_vault_when_the_database_comes_to_schema_2(scratch: Path) -> None:  # noqa: F811
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v1.sql").read_text(encoding="utf-8"))
        for name, display in (("anna", ""), ("anna.2", "ANNA"), ("con", ""), ("jule", "Julia Mustermann")):
            connection.execute(
                "INSERT INTO users (name, display_name, whats_new_seen, role, sign_in, password_hash, email, oidc_subject, "
                "language, created_at, failed_logins, totp_secret_enc, totp_recovery, totp_last_step, signed_in_before, "
                "passkey_handle, ai_allowed, email_from_provider) VALUES (?, ?, '', 'member', 'password', 'x', '', '', '', "
                "'2026-01-01 00:00:00.000000', 0, '', '', 0, 0, '', 1, 0)", (name, display))
        connection.execute("INSERT INTO settings (key, value) VALUES ('kept', '\"yes\"')")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION
    with closing(sqlite3.connect(scratch)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        rows = connection.execute(
            "SELECT u.name, v.name, v.folder, v.icon, m.\"right\" FROM users u JOIN vaults v ON v.personal_of = u.id "
            "JOIN vault_members m ON m.vault_id = v.id AND m.user_id = u.id ORDER BY u.id").fetchall()
        assert rows == [
            ("anna", "anna", "anna", "user", "manage"),
            ("anna.2", "ANNA", "ANNA 2", "user", "manage"),
            ("con", "con", "_con", "user", "manage"),
            ("jule", "Julia Mustermann", "Julia Mustermann", "user", "manage"),
        ]
        assert connection.execute("SELECT count(*) FROM vaults").fetchone() == (4,)
        assert connection.execute("SELECT count(*) FROM vault_members").fetchone() == (4,)
        assert connection.execute("SELECT value FROM settings WHERE key = 'kept'").fetchone() == ('"yes"',)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        # The tables of this step are there, empty.
        for table in ("documents", "versions", "shares", "links", "events", "tombstones", "counters"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)  # noqa: S608 - fixed names
        # Only the job that builds the search index (schema 6), which finds nothing to do.
        assert connection.execute("SELECT kind, state FROM jobs").fetchall() == [("index", "queued")]  # no text jobs
    # A second start changes nothing.
    database.init_db()
    with closing(sqlite3.connect(scratch)) as connection:
        assert connection.execute("SELECT count(*) FROM vaults").fetchone() == (4,)
    assert made_a_backup_before_the_step()


def made_a_backup_before_the_step() -> bool:
    from .test_schema import made

    return made == [f"before schema {database.SCHEMA_VERSION}"]
