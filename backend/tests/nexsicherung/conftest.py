"""Loads the app's adapter (``backend/tests/nexsicherung_adapter.py``, or the file named by ``NEXSICHERUNG_ADAPTER``)
and gives every contract test a fresh app. The process is never ended by a restore: ``restore.restart_soon`` only
counts. Copied unchanged into every app."""

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

contract = importlib.import_module("sicherung_contract")


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXSICHERUNG_ADAPTER") or HERE.parent / "nexsicherung_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexsicherung_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexsicherung_adapter"] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _adapter_module()


@pytest.fixture
def restarts(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    asked: list[float] = []
    package = contract.package_of(ADAPTER.Adapter)
    monkeypatch.setattr(package.restore, "restart_soon", lambda delay=1.5: asked.append(delay))
    return asked


@pytest.fixture
def app(restarts: list[float]) -> Iterator[Any]:
    adapter = ADAPTER.Adapter()
    adapter.start()
    try:
        yield adapter
    finally:
        adapter.stop()


@pytest.fixture
def sicherung(app: Any) -> ModuleType:
    return contract.package_of(app)
