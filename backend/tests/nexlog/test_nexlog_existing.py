"""What the app had before the module stays: its files are read as they are, its stored level stays in force with its
end, the environment variable keeps its name."""

from __future__ import annotations

from datetime import datetime
from types import ModuleType
from typing import Any


def test_the_older_versions_lines_read_as_they_meant_them(app: Any, nexlog: ModuleType) -> None:
    legacy = app.legacy_lines()
    assert legacy, "the app gives lines of its older file"
    assert any(line.request_id for line in legacy)
    name = nexlog.current().app_name
    older = nexlog.log_dir() / f"{name}.log.1"
    older.write_text("".join(line.raw.rstrip("\n") + "\n" for line in legacy), encoding="utf-8")
    shown = app.client("operator").get(app.prefix, params={"limit": 1000}).json()
    for line in legacy:
        match = [
            entry
            for entry in shown
            if entry["message"] == line.message and entry["logger"] == line.logger and entry["level"] == line.level
        ]
        assert match, line.raw
        entry = match[0]
        assert (entry["request_id"], entry["user"]) == (line.request_id, line.user), line.raw
        if line.at:
            assert datetime.fromisoformat(entry["at"]) == datetime.fromisoformat(line.at), line.raw


def test_a_deep_level_stored_by_the_older_version_stays_until_its_end(app: Any, nexlog: ModuleType) -> None:
    app.store_legacy(deep=True, minutes_from_now=45)
    nexlog.apply_stored_mode()
    assert nexlog.current_mode() == "detailed"
    level = app.client("operator").get(f"{app.prefix}/level").json()
    assert level["mode"] == "detailed" and level["until"]
    app.store_legacy(deep=True, minutes_from_now=-5)
    nexlog.apply_stored_mode()
    assert nexlog.current_mode() == "normal"


def test_a_quiet_level_stored_by_the_older_version_stays(app: Any, nexlog: ModuleType) -> None:
    app.store_legacy(deep=False, minutes_from_now=0)
    nexlog.apply_stored_mode()
    assert nexlog.current_mode() == "quiet"
    assert app.client("operator").get(f"{app.prefix}/level").json()["mode"] == "quiet"


def test_the_environment_variable_keeps_its_name(app: Any, nexlog: ModuleType) -> None:
    with app.environment("warning"):
        assert nexlog.env_mode() == "quiet"
        refused = app.client("operator").put(f"{app.prefix}/level", json={"mode": "normal"})
        assert nexlog.current().variable in refused.text
