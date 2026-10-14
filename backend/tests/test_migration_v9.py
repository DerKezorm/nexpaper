"""Schema 8 to schema 9 (``db._step_sorting``): the rules and e-invoice tables come, and the kinds get an owner of their own
(a vault, or the whole server). The kinds that were there stay the server's, a name stays unique among them, and a vault
may have a kind of its own with a name that another vault has."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app import db as database

from .test_schema import RECORDS, schema_of, scratch, version_of  # noqa: F401 - the fixture is used by name


def test_the_kinds_that_were_there_stay_the_servers_and_the_vaults_may_have_their_own(scratch: Path) -> None:  # noqa: F811
    with closing(sqlite3.connect(scratch)) as connection:
        connection.executescript((RECORDS / "v8.sql").read_text(encoding="utf-8"))
        connection.execute(
            "INSERT INTO users (id, name, display_name, whats_new_seen, role, sign_in, password_hash, email, oidc_subject, "
            "language, created_at, failed_logins, totp_secret_enc, totp_recovery, totp_last_step, signed_in_before, "
            "passkey_handle, ai_allowed, email_from_provider) VALUES (1, 'jule', '', '', 'member', 'password', 'x', '', '', "
            "'', '2026-01-01 00:00:00.000000', 0, '', '', 0, 0, '', 1, 0)")
        for vault in (1, 2):
            connection.execute("INSERT INTO vaults (id, name, folder, icon, personal_of, created_at, created_by) "
                               "VALUES (?, ?, ?, 'user', NULL, '2026-01-01 00:00:00.000000', 1)", (vault, f"v{vault}", f"v{vault}"))
        connection.execute("INSERT INTO kinds (id, \"key\", name, name_key, hue, position) VALUES (1, 'invoice', 'Rechnung', 'rechnung', 28, 0)")
        connection.execute(
            "INSERT INTO documents (id, vault_id, owner_id, title, kind_id, currency, status, source, added_at, pages, "
            "current_version, change_seq, trashed_status, duplicate_kind, process_error) VALUES (1, 1, 1, 'Strom', 1, "
            "'EUR', 'filed', 'upload', '2026-01-01 00:00:00.000000', 1, 1, 1, '', '', '')")
        connection.execute("PRAGMA user_version = 8")
        connection.commit()
        before = schema_of(connection)
    database.init_db()
    assert version_of(scratch) == database.SCHEMA_VERSION
    with closing(sqlite3.connect(scratch)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        after = schema_of(connection)
        assert {name: columns[: len(before[name])] for name, columns in after.items() if name in before} == before
        assert {"rules", "einvoices"} <= set(after)
        added = [column[0] for column in after["kinds"][len(before["kinds"]):]]
        assert added[:2] == ["vault_id", "created_by"]
        # The kind that was there is the server's, and its document keeps it.
        assert connection.execute("SELECT vault_id, created_by FROM kinds WHERE id = 1").fetchone() == (None, None)
        assert connection.execute("SELECT kind_id FROM documents WHERE id = 1").fetchone() == (1,)
        # A name stays unique among the server's kinds ...
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO kinds (\"key\", name, name_key, hue, position) VALUES ('', 'Rechnung', 'rechnung', 1, 1)")
        # ... and within a vault, but two vaults may each have a kind of the same name.
        for vault in (1, 2):
            connection.execute("INSERT INTO kinds (\"key\", name, name_key, hue, position, vault_id) VALUES ('', 'Mietvertrag', 'mietvertrag', 1, 0, ?)", (vault,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO kinds (\"key\", name, name_key, hue, position, vault_id) VALUES ('', 'Mietvertrag', 'mietvertrag', 1, 1, 1)")
        # A vault that goes takes its kinds with it, and a document with one of them is left without.
        connection.execute("UPDATE documents SET kind_id = 2")
        connection.execute("DELETE FROM documents")
        connection.execute("DELETE FROM vaults WHERE id = 1")
        assert connection.execute("SELECT count(*) FROM kinds WHERE vault_id = 1").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM kinds WHERE vault_id = 2").fetchone() == (1,)
