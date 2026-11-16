"""The worker's home (issue #5): a container started under an id without an entry in /etc/passwd (``user: 568:568`` on
TrueNAS) had no home for the worker, and a library that asked for it failed every recognition with a bare "failed"."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import processing


def test_the_worker_lives_in_its_own_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/server")
    monkeypatch.setenv("NEXPAPER_SECRET_FOR_THE_TEST", "not for the worker")
    environment = processing.worker_environment(str(tmp_path))
    assert environment["HOME"] == str(tmp_path)
    assert "NEXPAPER_SECRET_FOR_THE_TEST" not in environment
    assert "/home/server" not in environment.values()


def test_a_library_finds_the_home_without_one_from_the_server(tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH"):
        monkeypatch.delenv(name, raising=False)
    answer = subprocess.run(
        [sys.executable, "-I", "-c", "import pathlib; print(pathlib.Path.home())"],
        env=processing.worker_environment(str(tmp_path)), cwd=tmp_path, capture_output=True, text=True, timeout=60,
        check=False,
    )
    assert answer.returncode == 0, answer.stderr
    assert os.path.samefile(answer.stdout.strip(), tmp_path)


def test_a_failed_worker_names_the_kind_of_error_in_the_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=processing.logger.name)
    outcome = processing.spawn({"op": "render"}, 60)
    assert not outcome.ok
    assert outcome.error == "failed"
    assert any("The worker failed" in record.getMessage() and "KeyError" in record.getMessage()
               for record in caplog.records)
