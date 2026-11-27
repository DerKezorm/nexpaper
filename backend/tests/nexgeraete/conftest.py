"""Loads the app's adapter (``backend/tests/nexgeraete_adapter.py``, or the file named by ``NEXGERAETE_ADAPTER``) and
gives every contract test a fresh app. Copied unchanged into every app."""

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

contract = importlib.import_module("geraete_contract")


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXGERAETE_ADAPTER") or HERE.parent / "nexgeraete_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexgeraete_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexgeraete_adapter"] = module
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
        adapter.stop()


@pytest.fixture
def config(app: Any) -> Any:
    return app.config()


@pytest.fixture
def package(app: Any) -> ModuleType:
    return contract.package(app)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """``spec``: every form of device the app paired before the module, one test each."""
    if "spec" in metafunc.fixturenames:
        specs = ADAPTER.Adapter().legacy_devices()
        metafunc.parametrize("spec", specs, ids=[spec.label for spec in specs])
