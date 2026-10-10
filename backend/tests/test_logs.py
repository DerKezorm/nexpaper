"""The log routes: reading with filters, the level with its expiry, download, clear, operator only."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.services import logs, settings_service

probe = logging.getLogger("nexpaper.probe")


@pytest.fixture(autouse=True)
def normal_mode_afterwards() -> Iterator[None]:
    """The level is process-wide; whatever a test sets, the next one starts at normal."""
    yield
    logs.apply_mode(logs.DEFAULT_MODE)


def test_without_an_operator_every_log_route_is_closed(client: TestClient) -> None:
    assert client.get("/api/v1/logs").status_code == 401
    assert client.get("/api/v1/logs/level").status_code == 401
    assert client.put("/api/v1/logs/level", json={"mode": "trace"}).status_code == 401
    assert client.get("/api/v1/logs/download").status_code == 401
    assert client.delete("/api/v1/logs").status_code == 401
    assert logs.current_mode() == "normal"


def test_every_response_carries_a_request_id_and_the_lines_carry_it_too(client: TestClient, operator: str) -> None:
    logs.set_mode("detailed")
    first = client.get("/api/v1/about")
    second = client.get("/api/v1/about")
    first_id, second_id = first.headers["x-request-id"], second.headers["x-request-id"]
    assert len(first_id) == 6 and first_id != second_id
    lines = client.get("/api/v1/logs", params={"search": first_id}).json()
    assert lines, "the request logged a line at detailed"
    assert all(line["request_id"] == first_id for line in lines)
    assert any("GET /api/v1/about -> 200" in line["message"] for line in lines)


def test_the_level_filter_includes_higher_levels(client: TestClient, operator: str) -> None:
    probe.info("probe-levels info line")
    probe.warning("probe-levels warning line")
    probe.error("probe-levels error line")
    lines = client.get("/api/v1/logs", params={"level": "WARNING", "search": "probe-levels"}).json()
    assert [line["level"] for line in lines] == ["ERROR", "WARNING"], "newest first, INFO left out"
    assert all(line["logger"] == "nexpaper.probe" for line in lines)
    everything = client.get("/api/v1/logs", params={"search": "probe-levels"}).json()
    assert [line["level"] for line in everything] == ["ERROR", "WARNING", "INFO"]
    assert client.get("/api/v1/logs", params={"level": "LOUD"}).status_code == 422


def test_quiet_keeps_info_out_of_the_file(client: TestClient, operator: str) -> None:
    assert client.put("/api/v1/logs/level", json={"mode": "quiet"}).status_code == 200
    probe.info("probe-quiet info line")
    probe.warning("probe-quiet warning line")
    text = logs.log_file().read_text(encoding="utf-8")
    assert "probe-quiet warning line" in text
    assert "probe-quiet info line" not in text


def test_a_deep_level_with_a_duration_expires(client: TestClient, operator: str) -> None:
    level = client.get("/api/v1/logs/level").json()
    assert (level["mode"], level["until"], level["fixed_by_env"]) == ("normal", None, False)
    assert level["modes"] == ["quiet", "normal", "detailed", "trace"] and 30 in level["durations"]

    changed = client.put("/api/v1/logs/level", json={"mode": "detailed", "minutes": 30})
    assert changed.status_code == 200, changed.text
    until = datetime.fromisoformat(changed.json()["until"])
    assert timedelta(minutes=29) < until - datetime.now(UTC) < timedelta(minutes=31)
    assert logs.current_mode() == "detailed"
    assert client.put("/api/v1/logs/level", json={"mode": "trace", "minutes": 7}).status_code == 422

    # Time passes: the stored end lies in the past.
    with SessionLocal() as db:
        settings_service.save(db, {"log_mode_until": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()})
    state = logs.state()
    assert (state.mode, state.until) == ("normal", None)
    assert logs.current_mode() == "normal"
    with SessionLocal() as db:
        assert settings_service.get(db, "log_mode") == "normal"
        assert settings_service.get(db, "log_mode_until") is None


def test_the_environment_fixes_the_level(client: TestClient, operator: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "log_level", "debug")
    assert client.get("/api/v1/logs/level").json() == {
        "mode": "detailed", "until": None, "fixed_by_env": True,
        "modes": ["quiet", "normal", "detailed", "trace"], "durations": list(logs.ALLOWED_MINUTES),
    }
    refused = client.put("/api/v1/logs/level", json={"mode": "quiet"})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "log_level_from_environment"


def test_the_download_includes_rotated_files(client: TestClient, operator: str) -> None:
    probe.warning("probe-download current line")
    rotated = logs.log_dir() / "nexpaper.log.1"
    rotated.write_bytes(b"2026-09-01 03:00:00 INFO     nexpaper.probe [-] | probe-download older line\n")
    try:
        response = client.get("/api/v1/logs/download")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert 'filename="nexpaper-log-' in response.headers["content-disposition"]
        text = response.text
        assert "===== nexpaper.log.1 =====" in text and "probe-download older line" in text
        assert "===== nexpaper.log =====" in text and "probe-download current line" in text
        assert text.index("nexpaper.log.1 =====") < text.index("===== nexpaper.log ====="), "oldest first"
    finally:
        rotated.unlink(missing_ok=True)


def test_clear_empties_the_file_and_removes_rotated_ones(client: TestClient, operator: str) -> None:
    probe.warning("probe-clear marker line")
    rotated = logs.log_dir() / "nexpaper.log.2"
    rotated.write_bytes(b"older\n")
    assert client.get("/api/v1/logs", params={"search": "probe-clear"}).json()
    assert client.delete("/api/v1/logs").status_code == 204
    assert not rotated.exists()
    assert "probe-clear marker line" not in logs.log_file().read_text(encoding="utf-8")
    assert any(line["message"] == "Log cleared by operator" for line in client.get("/api/v1/logs").json())
    probe.warning("probe-clear after line")
    assert "probe-clear after line" in logs.log_file().read_text(encoding="utf-8")


def test_a_line_break_in_a_request_cannot_forge_a_record(client: TestClient, operator: str) -> None:
    logs.set_mode("detailed")
    forged = "2026-09-26 12:00:00 INFO     nexpaper.auth [-] | probe-forged sign-in"
    client.get("/api/v1/x%0d%0a" + forged.replace(" ", "%20"))
    lines = client.get("/api/v1/logs", params={"search": "probe-forged"}).json()
    assert any(line["logger"] == "nexpaper.api" for line in lines), "the request was logged"
    assert not any(line["logger"] == "nexpaper.auth" for line in lines), lines
    raw = logs.log_file().read_text(encoding="utf-8")
    assert not any(line.startswith("2026-09-26 12:00:00") for line in raw.splitlines())
    assert "\\r\\n2026-09-26 12:00:00" in raw


def test_a_traceback_keeps_its_lines_and_stays_with_its_record(client: TestClient, operator: str) -> None:
    try:
        raise RuntimeError("probe-traceback boom")
    except RuntimeError:
        probe.exception("probe-traceback failed")
    lines = client.get("/api/v1/logs", params={"search": "probe-traceback"}).json()
    assert len(lines) == 1 and "Traceback" in lines[0]["message"] and "\n" in lines[0]["message"]


def test_tokens_in_addresses_never_reach_the_log() -> None:
    import secrets

    invite = secrets.token_urlsafe(24)
    key = "npk_" + secrets.token_urlsafe(32)
    code = secrets.token_urlsafe(16)
    lines = [
        f"POST /api/v1/invite/{invite} -> 200 in 3ms",
        f"GET /invite/{invite}",
        f"GET /api/v1/oidc/callback?code={code}&state={code} -> 303",
        f"GET /api/v1/me?token={key}",
        f"Pasted {key} somewhere",
        f"Pasted {'npd_' + invite} somewhere",
    ]
    for line in lines:
        shown = logs.redact(line)
        assert invite not in shown and key not in shown and code not in shown, shown
        assert "…" in shown
    # What is no token stays as it was.
    assert logs.redact("GET /api/v1/about/updates -> 200") == "GET /api/v1/about/updates -> 200"


def test_every_address_that_carries_a_token_is_masked() -> None:
    """The routes with a ``{token}`` in the path are found in the route list, so one added later is covered; the pages
    of the frontend that carry the same tokens are named here."""
    import secrets

    from .test_routes import api_routes

    token = secrets.token_urlsafe(24)
    paths = [path.replace("{token}", token) for _method, path in api_routes() if "{token}" in path]
    assert len(paths) >= 6, "the routes with a token in the path were found"
    paths += [f"/{page}/{token}" for page in ("invite", "reset", "mail")]
    for path in paths:
        for line in (f"GET {path} -> 200 in 3ms", f"Slow request: POST {path}?x=1 -> 404 in 4100ms"):
            assert token not in logs.redact(line), line
    # The key and the token of a device are masked wherever they stand.
    for prefix in ("npd_", "npk_"):
        secret = prefix + secrets.token_urlsafe(32)
        assert secret not in logs.redact(f"GET /api/v1/{secret}/x"), prefix


@pytest.mark.parametrize("slow", [False, True], ids=["normal", "slow"])
def test_a_confirmation_link_does_not_reach_the_log_file(
    client: TestClient, operator: str, monkeypatch: pytest.MonkeyPatch, slow: bool
) -> None:
    """The line of an ordinary request and the line of a slow one are two places that print the address."""
    import secrets

    from app import middleware

    logs.set_mode("detailed")
    if slow:
        monkeypatch.setattr(middleware, "SLOW_MS", 0)
    token = secrets.token_urlsafe(24)
    for path in (f"/api/v1/email/confirm/{token}", f"/api/v1/invite/{token}", f"/api/v1/reset/{token}"):
        client.get(path)
    raw = logs.log_file().read_text(encoding="utf-8")
    assert ("Slow request" in raw) is slow and "/api/v1/email/confirm/" in raw
    assert token not in raw


def test_a_token_in_the_words_of_an_exception_stays_out_of_the_log_file(client: TestClient, operator: str) -> None:
    """``logger.exception`` writes a traceback after the message; the message was cleaned, the traceback was not."""
    import secrets

    token = secrets.token_urlsafe(24)
    key = "npk_" + secrets.token_urlsafe(32)
    try:
        raise RuntimeError(f"GET /api/v1/email/confirm/{token} failed with {key}")
    except RuntimeError:
        probe.exception("probe-exception-token failed")
    probe.warning("probe-stack-token", stack_info=True, extra={})
    raw = logs.log_file().read_text(encoding="utf-8")
    assert "probe-exception-token failed" in raw and "RuntimeError" in raw, "the traceback is there"
    assert token not in raw and key not in raw
    shown = client.get("/api/v1/logs", params={"search": "probe-exception-token"}).json()
    assert len(shown) == 1 and "Traceback" in shown[0]["message"]
    assert token not in shown[0]["message"] and key not in shown[0]["message"]
