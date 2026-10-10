"""The step from schema 1 to schema 2: vaults, documents and what hangs on them.

Written out as the tables stood then (``tests/schema/v2.sql``), not taken from the models, which move on. The
statements below are that record."""

from __future__ import annotations

V2_STATEMENTS = [
    'CREATE TABLE counters ( name VARCHAR(32) NOT NULL, value INTEGER NOT NULL, PRIMARY KEY (name) )',
    'CREATE TABLE document_dates ( id INTEGER NOT NULL, document_id INTEGER NOT NULL, kind VARCHAR(16) NOT NULL, date DATE NOT NULL, PRIMARY KEY (id), CONSTRAINT uq_document_dates_kind UNIQUE (document_id, kind), FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE )',
    'CREATE TABLE document_tags ( document_id INTEGER NOT NULL, tag_id INTEGER NOT NULL, PRIMARY KEY (document_id, tag_id), FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, FOREIGN KEY(tag_id) REFERENCES tags (id) ON DELETE CASCADE )',
    "CREATE TABLE documents ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, vault_id INTEGER NOT NULL, owner_id INTEGER, title VARCHAR(200) NOT NULL, sender_id INTEGER, kind_id INTEGER, date DATE, amount INTEGER, currency VARCHAR(3) DEFAULT 'EUR' NOT NULL, status VARCHAR(12) NOT NULL, source VARCHAR(16) NOT NULL, added_at DATETIME NOT NULL, pages INTEGER NOT NULL, current_version INTEGER NOT NULL, suggest JSON, trashed_at DATETIME, trashed_status VARCHAR(12) DEFAULT '' NOT NULL, change_seq INTEGER NOT NULL, FOREIGN KEY(vault_id) REFERENCES vaults (id) ON DELETE RESTRICT, FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE SET NULL, FOREIGN KEY(sender_id) REFERENCES senders (id) ON DELETE SET NULL, FOREIGN KEY(kind_id) REFERENCES kinds (id) ON DELETE SET NULL )",
    "CREATE TABLE events ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL, user_id INTEGER, by_link VARCHAR(100) DEFAULT '' NOT NULL, at DATETIME NOT NULL, action VARCHAR(24) NOT NULL, detail JSON, FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL )",
    "CREATE TABLE jobs ( id INTEGER NOT NULL, kind VARCHAR(16) NOT NULL, ref INTEGER NOT NULL, payload JSON, state VARCHAR(8) NOT NULL, attempts INTEGER NOT NULL, created_at DATETIME NOT NULL, started_at DATETIME, finished_at DATETIME, error VARCHAR(300) DEFAULT '' NOT NULL, PRIMARY KEY (id) )",
    'CREATE TABLE kinds ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "key" VARCHAR(32) NOT NULL, name VARCHAR(60) NOT NULL, name_key VARCHAR(160) NOT NULL, hue INTEGER NOT NULL, position INTEGER NOT NULL )',
    "CREATE TABLE links ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL, recipient VARCHAR(100) NOT NULL, token_hash VARCHAR(64) NOT NULL, token_enc VARCHAR(400) DEFAULT '' NOT NULL, until DATETIME NOT NULL, allow_download BOOLEAN DEFAULT 1 NOT NULL, opened_count INTEGER NOT NULL, last_opened_at DATETIME, created_by INTEGER, created_at DATETIME NOT NULL, revoked_at DATETIME, FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, UNIQUE (token_hash), FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL )",
    'CREATE TABLE notes ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL, user_id INTEGER, text TEXT NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME, FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL )',
    'CREATE TABLE senders ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, vault_id INTEGER NOT NULL, name VARCHAR(160) NOT NULL, "key" VARCHAR(400) NOT NULL, created_by INTEGER, FOREIGN KEY(vault_id) REFERENCES vaults (id) ON DELETE CASCADE, FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL )',
    'CREATE TABLE shares ( document_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "right" VARCHAR(8) NOT NULL, created_by INTEGER, created_at DATETIME NOT NULL, PRIMARY KEY (document_id, user_id), FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL )',
    'CREATE TABLE tags ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, vault_id INTEGER NOT NULL, name VARCHAR(40) NOT NULL, "key" VARCHAR(120) NOT NULL, created_by INTEGER, FOREIGN KEY(vault_id) REFERENCES vaults (id) ON DELETE CASCADE, FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL )',
    'CREATE TABLE tombstones ( seq INTEGER NOT NULL, kind VARCHAR(16) NOT NULL, document_id INTEGER, vault_id INTEGER, user_id INTEGER, at DATETIME NOT NULL, PRIMARY KEY (seq) )',
    'CREATE TABLE vault_members ( vault_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "right" VARCHAR(8) NOT NULL, PRIMARY KEY (vault_id, user_id), FOREIGN KEY(vault_id) REFERENCES vaults (id) ON DELETE CASCADE, FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE )',
    'CREATE TABLE vaults ( id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, name VARCHAR(80) NOT NULL, folder VARCHAR(64) NOT NULL, icon VARCHAR(16) NOT NULL, personal_of INTEGER, created_at DATETIME NOT NULL, created_by INTEGER, FOREIGN KEY(personal_of) REFERENCES users (id) ON DELETE RESTRICT, FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL )',
    "CREATE TABLE versions ( id INTEGER NOT NULL, document_id INTEGER NOT NULL, n INTEGER NOT NULL, original_path VARCHAR(600) NOT NULL, archive_path VARCHAR(600) DEFAULT '' NOT NULL, sha256 VARCHAR(64) NOT NULL, size INTEGER NOT NULL, pages INTEGER NOT NULL, created_by INTEGER, created_at DATETIME NOT NULL, note VARCHAR(200) DEFAULT '' NOT NULL, PRIMARY KEY (id), CONSTRAINT uq_versions_n UNIQUE (document_id, n), FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE SET NULL )",
    'CREATE INDEX ix_document_dates_document_id ON document_dates (document_id)',
    'CREATE INDEX ix_document_tags_tag_id ON document_tags (tag_id)',
    'CREATE INDEX ix_documents_change_seq ON documents (change_seq)',
    'CREATE INDEX ix_documents_trashed ON documents (trashed_at)',
    'CREATE INDEX ix_documents_vault_status ON documents (vault_id, status)',
    'CREATE INDEX ix_events_document ON events (document_id, id)',
    'CREATE INDEX ix_jobs_state ON jobs (state, id)',
    'CREATE INDEX ix_links_document_id ON links (document_id)',
    'CREATE INDEX ix_notes_document_id ON notes (document_id)',
    'CREATE INDEX ix_shares_user_id ON shares (user_id)',
    'CREATE INDEX ix_tombstones_at ON tombstones (at)',
    'CREATE INDEX ix_tombstones_user ON tombstones (user_id)',
    'CREATE INDEX ix_tombstones_vault ON tombstones (vault_id)',
    'CREATE INDEX ix_vault_members_user_id ON vault_members (user_id)',
    "CREATE UNIQUE INDEX uq_jobs_waiting ON jobs (kind, ref) WHERE state = 'queued'",
    'CREATE UNIQUE INDEX uq_kinds_name_key ON kinds (name_key)',
    'CREATE UNIQUE INDEX uq_senders_key ON senders (vault_id, "key")',
    'CREATE UNIQUE INDEX uq_tags_key ON tags (vault_id, "key")',
    'CREATE UNIQUE INDEX uq_vaults_folder ON vaults (lower(folder))',
    'CREATE UNIQUE INDEX uq_vaults_personal ON vaults (personal_of)',
    'CREATE UNIQUE INDEX uq_versions_original ON versions (lower(original_path))',
]
