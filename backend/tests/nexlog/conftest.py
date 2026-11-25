"""Loads the app's adapter (``backend/tests/nexlog_adapter.py``, or the file named by ``NEXLOG_ADAPTER``) and gives
every contract test a fresh app and the vendored package. Copied unchanged into every app."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Imported by name after the path is set: a plain import statement here would sit below code.
contract = importlib.import_module("log_contract")


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXLOG_ADAPTER") or HERE.parent / "nexlog_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexlog_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexlog_adapter"] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _adapter_module()


@pytest.fixture
def app() -> Iterator[Any]:
    adapter = ADAPTER.Adapter()
    adapter.start()
    try:
        yield adapter
    finally:
        package = contract.log_package(adapter)
        package.apply_mode(package.DEFAULT_MODE)
        adapter.stop()


@pytest.fixture
def nexlog(app: Any) -> ModuleType:
    return contract.log_package(app)


@pytest.fixture
def probe(nexlog: ModuleType) -> logging.Logger:
    """A logger of the app (``<app>.probe``)."""
    return logging.getLogger(f"{nexlog.current().app_name}.probe")
