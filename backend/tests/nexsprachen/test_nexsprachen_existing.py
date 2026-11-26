"""What was there before the module keeps working: a file the operator laid into the app's folder by hand (nexnotes,
nexdiary, nexfolk: ``<data>/locales/es.json`` with ``_meta``), or uploaded through the app's older routes, is listed
and read as before, under the same routes. Copied unchanged into every app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: A file as the older versions took it: ``_meta`` with a name, groups of texts.
SPANISH = {"_meta": {"name": "Español"}, "common": {"close": "Cerrar", "save": "Guardar"}, "nav": {"notes": "Notas"}}


def test_a_file_laid_into_the_folder_by_hand_is_listed_and_read(app: Any, reader: Any, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "es.json").write_text(json.dumps(SPANISH, ensure_ascii=False, indent=2), encoding="utf-8")
    entries = reader.get(app.prefix).json()
    assert entries[-1] == {"code": "es", "name": "Español", "keys": 3, "built_in": False, "own": True}
    assert reader.get(f"{app.prefix}/es").json() == {key: value for key, value in SPANISH.items() if key != "_meta"}


def test_a_changed_file_is_read_anew(app: Any, reader: Any, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "es.json").write_text('{"a": "uno"}', encoding="utf-8")
    assert reader.get(app.prefix).json()[-1]["keys"] == 1
    (folder / "es.json").write_text('{"a": "uno", "b": "dos"}', encoding="utf-8")
    assert reader.get(app.prefix).json()[-1]["keys"] == 2
    assert reader.get(f"{app.prefix}/es").json() == {"a": "uno", "b": "dos"}


def test_the_package_keeps_the_names_of_nexnotes_services_locales(nexsprachen: Any) -> None:
    for name in ("CODE_PATTERN", "MAX_BYTES", "MAX_DEPTH", "MAX_NAME", "MAX_FILES", "META_KEY", "LocaleError",
                 "Locale", "locales_dir", "valid_code", "load", "forget", "available", "save", "remove"):
        assert name in nexsprachen.__all__, name
    assert nexsprachen.MAX_BYTES == 512 * 1024 and nexsprachen.MAX_DEPTH == 8
