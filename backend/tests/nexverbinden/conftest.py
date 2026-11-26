"""Loads the app's adapter (``backend/tests/nexverbinden_adapter.py``, or the file named by ``NEXVERBINDEN_ADAPTER``)
and gives every contract test the app and its partner, reaching each other. Copied unchanged into every app."""

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

contract = importlib.import_module("verbinden_contract")


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXVERBINDEN_ADAPTER") or HERE.parent / "nexverbinden_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexverbinden_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexverbinden_adapter"] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _adapter_module()


@pytest.fixture
def world(tmp_path: Path) -> Iterator[Any]:
    """The app as freshly installed, and its partner."""
    adapter = ADAPTER.Adapter()
    yield from contract.world(contract.package(adapter), adapter, tmp_path)


@pytest.fixture
def older(tmp_path: Path) -> Iterator[Any]:
    """The app updated from the older version (an API key, maybe a connection typed in by hand), and its partner."""
    adapter = ADAPTER.Adapter()
    yield from contract.world(contract.package(adapter), adapter, tmp_path, older=True)


@pytest.fixture
def pkg(world: Any) -> ModuleType:
    return world.pkg
