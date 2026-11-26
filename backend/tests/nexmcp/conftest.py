"""Loads the app's adapter (``backend/tests/nexmcp_adapter.py``, or the file named by ``NEXMCP_ADAPTER``) and gives
every contract test a fresh app. Copied unchanged into every app."""

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

contract = importlib.import_module("mcp_contract")


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXMCP_ADAPTER") or HERE.parent / "nexmcp_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexmcp_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexmcp_adapter"] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _adapter_module()


def _started(older: bool) -> Iterator[Any]:
    adapter = ADAPTER.Adapter()
    contract.package(adapter).brake.BRAKE.forget()
    if older:
        adapter.start_older()
    else:
        adapter.start()
    try:
        yield adapter
    finally:
        adapter.stop()
        contract.package(adapter).brake.BRAKE.forget()


@pytest.fixture
def fresh() -> Iterator[Any]:
    """The app as freshly installed: nothing switched on."""
    yield from _started(False)


@pytest.fixture
def app(fresh: Any) -> Any:
    """A fresh app with MCP switched on by the operator."""
    contract.switch_mcp(fresh, True)
    return fresh


@pytest.fixture
def older() -> Iterator[Any]:
    """The app updated from the older version."""
    yield from _started(True)


@pytest.fixture
def nexmcp(fresh: Any) -> ModuleType:
    return contract.package(fresh)
