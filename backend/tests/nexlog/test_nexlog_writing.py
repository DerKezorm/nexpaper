"""What reaches the file: one line per record, a traceback with its record, nothing of the app's keys and tokens."""

from __future__ import annotations

import logging
import secrets
from types import ModuleType
from typing import Any


def test_a_line_break_cannot_forge_a_record(app: Any, nexlog: ModuleType, probe: logging.Logger) -> None:
    name = nexlog.current().app_name
    forged = f"2026-09-26 12:00:00 INFO     {name}.auth [-] | probe-forged sign-in"
    probe.warning("Request for /api/x\r\n%s", forged)
    try:
        raise ValueError("probe-forged boom\n" + forged)
    except ValueError:
        probe.exception("probe-forged failed")
    raw = nexlog.log_file().read_text(encoding="utf-8")
    assert not any(line.startswith("2026-09-26 12:00:00") for line in raw.splitlines())
    lines = app.client("operator").get(app.prefix, params={"search": "probe-forged"}).json()
    assert lines and not any(line["logger"] == f"{name}.auth" for line in lines)


def test_a_traceback_keeps_its_lines_and_stays_with_its_record(app: Any, probe: logging.Logger) -> None:
    try:
        raise RuntimeError("probe-traceback boom")
    except RuntimeError:
        probe.exception("probe-traceback failed")
    lines = app.client("operator").get(app.prefix, params={"search": "probe-traceback"}).json()
    assert len(lines) == 1
    assert "Traceback" in lines[0]["message"] and "\n" in lines[0]["message"]
    assert lines[0]["message"].startswith("probe-traceback failed")


def test_the_apps_keys_and_tokens_never_reach_the_file(app: Any, nexlog: ModuleType, probe: logging.Logger) -> None:
    named = app.secrets()
    assert named, "the app names its keys and tokens"
    for secret in named:
        probe.warning(secret.message)
        try:
            raise RuntimeError(secret.message)
        except RuntimeError:
            probe.exception("probe-secret failed")
    raw = nexlog.log_file().read_text(encoding="utf-8")
    for secret in named:
        assert secret.hidden not in raw, secret.message
        for kept in secret.kept:
            assert kept in raw, kept


def _made() -> str:
    """A value made at run time: no secret is written into a test."""
    return "v" + secrets.token_hex(10)


def test_common_secrets_never_reach_the_file(app: Any, nexlog: ModuleType, probe: logging.Logger) -> None:
    made = [_made() for _ in range(6)]
    probe.warning("probe-common callback ?code=%s&state=%s", made[0], made[1])
    probe.warning("probe-common Authorization: Bearer %s", made[2])
    probe.warning("probe-common config password=%s api_key: %s", made[3], made[4])
    probe.warning("probe-common GET /api/invite/%s -> 200", made[5])
    raw = nexlog.log_file().read_text(encoding="utf-8")
    for hidden in made:
        assert hidden not in raw, hidden
    assert "probe-common GET /api/invite/… -> 200" in raw
    assert "?code=…&state=…" in raw and "Bearer …" in raw and "password=…" in raw
