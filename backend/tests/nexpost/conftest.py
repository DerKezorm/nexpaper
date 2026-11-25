"""Loads the app's adapter (``backend/tests/nexpost_adapter.py``, or the file named by ``NEXPOST_ADAPTER``) and gives
every contract test a fresh app, the vendored package and the mail server of the tests. Copied unchanged into every
app."""

from __future__ import annotations

import importlib
import importlib.util
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
contract = importlib.import_module("post_contract")


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXPOST_ADAPTER") or HERE.parent / "nexpost_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexpost_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexpost_adapter"] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _adapter_module()


@pytest.fixture
def server() -> Any:
    return contract.FakeServer()


@pytest.fixture
def app(server: Any) -> Iterator[Any]:
    adapter = ADAPTER.Adapter()
    adapter.start()
    package = contract.post_package(adapter)
    package.use_smtp(server.factory)
    try:
        yield adapter
    finally:
        package.use_smtp(None)
        adapter.stop()


@pytest.fixture
def post(app: Any) -> ModuleType:
    return contract.post_package(app)
