"""The guard over the app's own texts (W11, W12): every entry in form in every built-in language, English as the
fallback names every version, the running version x.y.0 ships with its text in every language, and every released text
is frozen and unchanged. Red means: write the missing text, or run ``python bauplaene/wasneu/tools/sync.py freeze
<app>`` after a release, or put a released text back as it was. Copied unchanged into every app."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any


def test_the_texts_of_the_app_may_ship(nexwasneu: ModuleType) -> None:
    found = nexwasneu.problems()
    assert found == [], "\n".join(found)


def test_the_texts_lie_in_the_apps_package_so_that_the_image_carries_them(app: Any, nexwasneu: ModuleType) -> None:
    root = Path(importlib.import_module(app.root_package).__file__ or "").resolve().parent
    folder = nexwasneu.current().folder.resolve()
    assert root in folder.parents, f"{folder} is outside {root}"
    assert (folder / f"{nexwasneu.FALLBACK}.json").is_file()


def test_the_built_in_languages_hold_english_and_are_the_apps(nexwasneu: ModuleType) -> None:
    languages = nexwasneu.current().languages
    assert "en" in languages and len(set(languages)) == len(languages)
    for code in languages:
        assert nexwasneu.chain(code, languages)[0] == code
