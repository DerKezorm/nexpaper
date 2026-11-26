"""Loads the app's adapter (``backend/tests/nexki_adapter.py``, or the file named by ``NEXKI_ADAPTER``) and gives every
contract test a fresh app and a stand-in service. Copied unchanged into every app."""

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

contract = importlib.import_module("ki_contract")
from nexki_service import Recorder, ReferenceService  # noqa: E402


def _adapter_module() -> ModuleType:
    path = Path(os.environ.get("NEXKI_ADAPTER") or HERE.parent / "nexki_adapter.py")
    if not path.is_file():
        raise RuntimeError(
            f"the contract tests need the app's adapter at {path} (template: tests-fuer-apps/adapter_template.py)"
        )
    spec = importlib.util.spec_from_file_location("nexki_adapter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["nexki_adapter"] = module
    spec.loader.exec_module(module)
    return module


ADAPTER = _adapter_module()


def pytest_configure(config: Any) -> None:
    config.addinivalue_line("markers", "manual_only: a case of button tasks (``has_manual``)")
    config.addinivalue_line("markers", "automatic_only: a case of automatic tasks (``has_automatic``)")
    config.addinivalue_line("markers", "older_own: a case of an older installation of own services (``own``)")


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    """Since 0.1.2 (K-8, K-10): the cases of a kind of task the app does not have fall away (deselected, not
    skipped); every other case runs through the kind it has."""
    adapter = ADAPTER.Adapter
    assert adapter.has_manual or adapter.has_automatic, "an app with the module has button or automatic tasks"
    kept, dropped = [], []
    for item in items:
        if (
            (item.get_closest_marker("manual_only") and not adapter.has_manual)
            or (item.get_closest_marker("automatic_only") and not adapter.has_automatic)
            or (item.get_closest_marker("older_own") and "own" not in adapter.older_forms)
        ):
            dropped.append(item)
        else:
            kept.append(item)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = kept


def _forget(adapter: Any) -> None:
    contract.package(adapter).brake.BRAKE.forget()


@pytest.fixture
def app() -> Iterator[Any]:
    """The app as freshly installed: nothing set up, the AI closed."""
    adapter = ADAPTER.Adapter()
    _forget(adapter)
    adapter.start()
    try:
        yield adapter
    finally:
        adapter.stop()
        _forget(adapter)


@pytest.fixture
def service() -> Iterator[ReferenceService]:
    """The stand-in service on 127.0.0.1 (the own network), without a key."""
    found = ReferenceService()
    found.serve()
    try:
        yield found
    finally:
        found.stop()


@pytest.fixture
def keyed() -> Iterator[ReferenceService]:
    """The stand-in service on 127.0.0.1 that wants the test key."""
    found = ReferenceService(key=contract.KEY)
    found.serve()
    try:
        yield found
    finally:
        found.stop()


@pytest.fixture
def recorder() -> Iterator[Recorder]:
    found = Recorder()
    try:
        yield found
    finally:
        found.stop()


@pytest.fixture
def nexki(app: Any) -> ModuleType:
    return contract.package(app)
