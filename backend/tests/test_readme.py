"""The README names every setting of the environment, and only settings that exist."""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
#: Read by the container's entrypoint, not by the application.
OF_THE_IMAGE = {"NEXPAPER_PORT"}
#: Read by the tests only, named in the development notes.
FOR_TESTS = {"NEXPAPER_RECORD_OPENAPI", "NEXPAPER_RECORD_SCHEMA"}


def real() -> set[str]:
    return {f"NEXPAPER_{name.upper()}" for name in Settings.model_fields} | OF_THE_IMAGE


def test_every_setting_is_in_the_readme() -> None:
    missing = sorted(name for name in real() if name not in README)
    assert not missing, f"Not in the README's table: {missing}"


def test_the_readme_names_no_setting_that_does_not_exist() -> None:
    named = set(re.findall(r"NEXPAPER_[A-Z0-9_]+", README))
    assert not sorted(named - real() - FOR_TESTS), f"In the README but not in config.py: {sorted(named - real() - FOR_TESTS)}"


def test_the_table_is_in_the_environment_section() -> None:
    section = README.split("## Environment", 1)[1].split("\n## ", 1)[0]
    assert all(name in section for name in real()), "Every setting belongs in the table of the environment section"


def test_every_picture_and_file_the_readme_points_to_exists_and_is_small() -> None:
    targets = set(re.findall(r'(?:src="|\]\()((?:docs|frontend)/[^")#]+)', README))
    # The README shows no pictures yet (they come with the last block); whatever it points to must be there.
    for target in sorted(targets):
        path = ROOT / target
        assert path.exists(), f"{target} is named in the README but is not there"
        if path.is_file() and path.suffix in {".webp", ".png"}:
            assert path.stat().st_size <= 300 * 1024, f"{target} is larger than 300 KB"


def test_the_screenshot_folder_holds_both_looks_of_every_picture() -> None:
    shown = {path.stem for path in (ROOT / "docs" / "screenshots").glob("*.webp")}
    for name in sorted(shown):
        assert name.endswith("-dark") or f"{name}-dark" in shown, f"{name} has no dark twin"
