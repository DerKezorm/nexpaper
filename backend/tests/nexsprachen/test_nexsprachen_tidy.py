"""What a stopped process left of an upload (a hidden ``.<code>.<random>.part`` in the folder) is gone after the app
starts again (``tidy_at_start`` right after ``configure``); language files and every other name stay. Copied unchanged
into every app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: Left by an upload that stopped mid-write: the module's passing names, and the older apps' ``.<code>.json.part``.
LEFT = (".nl.k3j9x_2a.part", ".pt-BR.a1b2c3d4.part", ".nl.json.part")
#: Never touched: language files, and names that only look a little like a passing file.
KEPT = ("nl.json", "de.json", "nl.json.part", ".nl.part", ".hidden", "notes.part", ".NL.abc.part")


def test_a_restart_removes_what_a_stopped_upload_left_and_nothing_else(app: Any, reader: Any, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in LEFT:
        (folder / name).write_bytes(b'{"half": "writ')
    for name in KEPT:
        (folder / name).write_text('{"a": "b"}', encoding="utf-8")
    (folder / ".de.abc12345.part").mkdir()
    app.restart()
    assert sorted(path.name for path in folder.iterdir()) == sorted((*KEPT, ".de.abc12345.part"))
    assert (folder / "nl.json").read_text(encoding="utf-8") == '{"a": "b"}'
    assert "nl" in [entry["code"] for entry in reader.get(app.prefix).json()]


def test_starting_again_and_again_is_harmless(app: Any, reader: Any, operator: Any, folder: Path,
                                              nexsprachen: Any) -> None:
    upload = operator.put(f"{app.prefix}/nl", content=b'{"a": "b"}', headers={"content-type": "application/json"})
    assert upload.status_code == 200
    app.restart()
    app.restart()
    assert nexsprachen.tidy_at_start() == 0
    assert sorted(path.name for path in folder.iterdir()) == ["nl.json"]
    assert app.client("anonymous" if app.public_read else "member").get(f"{app.prefix}/nl").json() == {"a": "b"}
