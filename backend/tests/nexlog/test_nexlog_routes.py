"""The page's routes in the app: operators only, reading with filters and pages, the level with its end, the
environment, download, clear."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any


def test_without_an_operator_every_log_route_is_closed(app: Any, nexlog: ModuleType) -> None:
    base = app.prefix
    for role, status in (("anonymous", 401), ("member", 403)):
        client = app.client(role)
        assert client.get(base).status_code == status, role
        assert client.get(f"{base}/level").status_code == status, role
        assert client.put(f"{base}/level", json={"mode": "trace", "minutes": 60}).status_code == status, role
        assert client.get(f"{base}/download").status_code == status, role
        assert client.delete(base).status_code == status, role
    assert nexlog.current_mode() == "normal"


def test_the_level_filter_includes_higher_levels_newest_first(app: Any, probe: logging.Logger) -> None:
    probe.info("probe-levels info line")
    probe.warning("probe-levels warning line")
    probe.error("probe-levels error line")
    client = app.client("operator")
    lines = client.get(app.prefix, params={"level": "WARNING", "search": "probe-levels"}).json()
    assert [line["level"] for line in lines] == ["ERROR", "WARNING"]
    assert all(line["logger"] == probe.name for line in lines)
    everything = client.get(app.prefix, params={"search": "PROBE-LEVELS"}).json()
    assert [line["level"] for line in everything] == ["ERROR", "WARNING", "INFO"]
    assert all(line["at"] for line in everything)
    assert client.get(app.prefix, params={"level": "LOUD"}).status_code == 422


def test_older_lines_come_page_by_page(app: Any, probe: logging.Logger) -> None:
    for number in range(30):
        probe.warning("probe-pages line %02d", number)
    client = app.client("operator")
    first = client.get(app.prefix, params={"search": "probe-pages", "limit": 20}).json()
    second = client.get(app.prefix, params={"search": "probe-pages", "limit": 20, "offset": 20}).json()
    assert [line["message"] for line in first][:2] == ["probe-pages line 29", "probe-pages line 28"]
    assert len(first) == 20 and len(second) == 10
    assert second[-1]["message"] == "probe-pages line 00"


def test_every_request_names_its_number_and_who_made_it(app: Any, nexlog: ModuleType) -> None:
    client = app.client("operator")
    assert client.put(f"{app.prefix}/level", json={"mode": "detailed", "minutes": 30}).status_code == 200
    answer = client.get(app.probe_path)
    number = answer.headers[app.request_id_header]
    lines = client.get(app.prefix, params={"search": number}).json()
    assert lines, f"{app.probe_path} logged no line at detailed"
    assert all(line["request_id"] == number for line in lines)
    assert any(line["user"] == app.operator_name() for line in lines), "who made the request"


def test_quiet_keeps_info_out_of_the_file(app: Any, nexlog: ModuleType, probe: logging.Logger) -> None:
    assert app.client("operator").put(f"{app.prefix}/level", json={"mode": "quiet"}).status_code == 200
    probe.info("probe-quiet info line")
    probe.warning("probe-quiet warning line")
    text = nexlog.log_file().read_text(encoding="utf-8")
    assert "probe-quiet warning line" in text and "probe-quiet info line" not in text


def test_a_deep_level_runs_for_its_time_and_then_ends(app: Any, nexlog: ModuleType) -> None:
    client = app.client("operator")
    level = client.get(f"{app.prefix}/level").json()
    assert (level["mode"], level["until"], level["fixed_by_env"]) == ("normal", None, False)
    assert level["modes"] == ["quiet", "normal", "detailed", "trace"]
    assert level["durations"] == [30, 60, 120, 480]

    changed = client.put(f"{app.prefix}/level", json={"mode": "detailed", "minutes": 60})
    assert changed.status_code == 200, changed.text
    until = datetime.fromisoformat(changed.json()["until"])
    assert timedelta(minutes=59) < until - datetime.now(UTC) < timedelta(minutes=61)
    assert nexlog.current_mode() == "detailed"
    assert client.put(f"{app.prefix}/level", json={"mode": "trace", "minutes": 7}).status_code == 422
    assert client.put(f"{app.prefix}/level", json={"mode": "trace", "minutes": 0}).status_code == 422
    assert client.put(f"{app.prefix}/level", json={"mode": "loud"}).status_code == 422

    # Time passes: the stored end lies in the past (written the way the app always wrote it).
    app.store_legacy(deep=True, minutes_from_now=-1)
    level = client.get(f"{app.prefix}/level").json()
    assert (level["mode"], level["until"]) == ("normal", None)
    assert nexlog.current_mode() == "normal"
    assert nexlog.normalize_mode(app.stored()[0]) == "normal"
    assert nexlog.normalize_until(app.stored()[1]) is None


def test_the_environment_fixes_the_level(app: Any, nexlog: ModuleType) -> None:
    client = app.client("operator")
    with app.environment("debug"):
        assert client.get(f"{app.prefix}/level").json() == {
            "mode": "detailed",
            "until": None,
            "fixed_by_env": True,
            "variable": nexlog.current().variable,
            "modes": ["quiet", "normal", "detailed", "trace"],
            "durations": [30, 60, 120, 480],
        }
        refused = client.put(f"{app.prefix}/level", json={"mode": "quiet"})
        assert refused.status_code == 409
        assert "log_level_from_environment" in refused.text


def test_the_download_has_every_file_oldest_first(app: Any, nexlog: ModuleType, probe: logging.Logger) -> None:
    probe.warning("probe-download current line")
    name = nexlog.current().app_name
    rotated = nexlog.log_dir() / f"{name}.log.1"
    rotated.write_bytes(f"2026-09-01 03:00:00 INFO     {name}.probe [-] | probe-download older line\n".encode())
    response = app.client("operator").get(f"{app.prefix}/download")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert f'filename="{name}-log-' in response.headers["content-disposition"]
    text = response.text
    assert f"===== {name}.log.1 =====" in text and "probe-download older line" in text
    assert f"===== {name}.log =====" in text and "probe-download current line" in text
    assert text.index(f"{name}.log.1 =====") < text.index(f"===== {name}.log =====")
    assert any(
        line["message"] == "Log downloaded by operator" and line["user"] == app.operator_name()
        for line in app.client("operator").get(app.prefix).json()
    )


def test_clear_empties_the_file_and_removes_older_ones(app: Any, nexlog: ModuleType, probe: logging.Logger) -> None:
    probe.warning("probe-clear marker line")
    rotated = nexlog.log_dir() / f"{nexlog.current().app_name}.log.2"
    rotated.write_bytes(b"older\n")
    client = app.client("operator")
    assert client.get(app.prefix, params={"search": "probe-clear"}).json()
    assert client.delete(app.prefix).status_code == 204
    assert not rotated.exists()
    assert "probe-clear marker line" not in nexlog.log_file().read_text(encoding="utf-8")
    cleared = [line for line in client.get(app.prefix).json() if line["message"] == "Log cleared by operator"]
    assert cleared and cleared[0]["user"] == app.operator_name()
    probe.warning("probe-clear after line")
    assert "probe-clear after line" in nexlog.log_file().read_text(encoding="utf-8")
