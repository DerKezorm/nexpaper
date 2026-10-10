"""Helpers for the tests that look for a word in every byte the server keeps: the database file with its ``-wal`` and
``-shm``, the backups, the log. A word made for the run goes in, then every file is searched for it in UTF-8 and UTF-16,
in its own case and in lower and upper case."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterator

import pytest

from app.config import get_settings
from app.services import logs


def forms(word: str) -> list[bytes]:
    """Every way the word could stand in a file."""
    out: list[bytes] = []
    for variant in {word, word.lower(), word.upper(), word.casefold()}:
        for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
            out.append(variant.encode(encoding))
    return out


def found_in(data: bytes, word: str) -> bool:
    return any(form in data for form in forms(word))


@pytest.fixture
def word() -> str:
    # Letters in both cases, made now: no file can hold it by chance, and the case variants differ.
    return "Qx" + secrets.token_hex(6) + "Zy"


@pytest.fixture
def deep_log() -> Iterator[None]:
    """The most detailed log there is, so that nothing is hidden by a quiet level."""
    logs.set_mode("trace", 30)
    yield
    logs.set_mode(logs.DEFAULT_MODE)


@pytest.fixture
def journal_kept() -> Iterator[None]:
    """A connection held open for the whole test: SQLite empties and deletes the ``-wal`` when the last connection
    closes, and every request closes its own. Held open, the journal keeps every page written, as on a busy server."""
    connection = sqlite3.connect(get_settings().database_path)
    connection.execute("SELECT count(*) FROM users").fetchone()
    yield
    connection.close()
